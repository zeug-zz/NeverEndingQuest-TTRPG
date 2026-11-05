# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Run the provider-free N0 OpenTunnel transport feasibility checks.

Architecture: one isolated run owns a pinned OpenTunnel CLI, its XDG profile,
and the inert loopback fixture. A synchronous requests/python-socketio client
probes the public route; the driver records redacted evidence and only stops
processes it started. It does not import the game runtime or campaign data.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import importlib.metadata
import io
import json
import os
import platform as platform_module
import re
import selectors
import shutil
import signal
import socket
import subprocess
import stat
import sys
import tarfile
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from unittest import mock
from urllib.parse import urlsplit

import requests
import socketio


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_VERSION = "v0.6.2"
RELEASE_ROOT = "https://github.com/anomalyco/opentunnel/releases/download/v0.6.2"
OPENTUNNEL_ROOT = REPO_ROOT / "tmp/n0/opentunnel"
ASSET_DIGESTS = {
    "opentunnel-linux-x64.tar.gz": "ce9b654b686beb0d23c87be9816ec71da950f41a4ddc0c8f33396eef871dc861",
    "opentunnel-linux-arm64.tar.gz": "3136e3b66157db18e2f2b86bdcbf1c88016b2daeee70c0396a5c9d188eb6f293",
    "opentunnel-darwin-x64.tar.gz": "5f4629b571b53df5669a18ed1f395d2fb24ad2c8fd1ad5d3637dbe427f26e6f6",
    "opentunnel-darwin-arm64.tar.gz": "3f4cf4d316db0e341b2995fd5cd44ba79a78aaee534f32199969152397c9e504",
}
PLATFORM_ASSETS = {
    ("Darwin", "arm64"): "opentunnel-darwin-arm64.tar.gz",
    ("Darwin", "aarch64"): "opentunnel-darwin-arm64.tar.gz",
    ("Darwin", "x86_64"): "opentunnel-darwin-x64.tar.gz",
    ("Linux", "x86_64"): "opentunnel-linux-x64.tar.gz",
    ("Linux", "aarch64"): "opentunnel-linux-arm64.tar.gz",
    ("Linux", "arm64"): "opentunnel-linux-arm64.tar.gz",
}
REQUIRED_CHECKS = [
    "asset_checksum",
    "runtime_dir_probe",
    "static_index",
    "healthz",
    "https_scheme",
    "fixture_local_healthz",
    "login_wrong_rejected",
    "login_missing_rejected",
    "login_accept_secure_cookie",
    "login_origin_spoof_rejected",
    "socket_origin_spoof_rejected",
    "forwarding_headers_ignored",
    "host_spoof_rejected",
    "host_spoof_loopback_rejected",
    "unauth_socket_refused",
    "websocket_connect",
    "polling_connect",
    "echo",
    "reconnect_after_tunnel_restart",
    "clean_shutdown",
    "no_service_registration",
    "isolated_child_environment",
    "cleanup_execution",
]
SOCKET_TIMEOUT = 10
PROCESS_STOP_TIMEOUT = 10
PUBLIC_WAIT_TIMEOUT = 90
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_UNIX_SOCKET_PATH = 104
MAX_OUTPUT_LINE_BYTES = 8192
MAX_TUNNEL_OUTPUT_LINES = 256
MAX_URL_PARSE_CHARS = 64 * 1024
MAX_CLI_OUTPUT_BYTES = MAX_URL_PARSE_CHARS
MAX_CLI_OUTPUT_CHUNK_BYTES = 64 * 1024
IDENTITY_UP_TIMEOUT = 300
IDENTITY_CLEANUP_TIMEOUT = 30
STATUS_POLL_INTERVAL = 2.0
MAX_URL_CANDIDATES = 256
MAX_LOG_BYTES = 1024 * 1024
MAX_DAEMON_LOG_BYTES = 64 * 1024
MAX_DAEMON_LOG_LINE_BYTES = 64 * 1024
MAX_DAEMON_LOG_TAIL_CHARS = 2048
MAX_DAEMON_LOG_FILES = 16
MAX_LOG_ENTRY_CHARS = 8192
MAX_HTTP_WAIT_MESSAGES = 3
MAX_HTTP_WAIT_MESSAGE_CHARS = 160
CHILD_ENV_KEYS = (
    "PATH",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "TZ",
    "USER",
    "LOGNAME",
    "SHELL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
)
_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?", re.IGNORECASE)
_URL_CANDIDATE_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"'`]+")
_HOST_RE = re.compile(r"\b[A-Za-z0-9.-]+\.opentunnel\.xyz\b", re.IGNORECASE)
_DNS_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_PROFILE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_BUILD_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z", re.IGNORECASE)
_SIGNED_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")
_SET_COOKIE_RE = re.compile(
    r"(?i)(set-cookie\s*:\s*[^=;\s,]+=)[^;\r\n]*"
)
_COOKIE_PAIR_RE = re.compile(
    r"(?i)\b(n0_session|session(?:_[A-Za-z0-9-]+)?|token(?:_[A-Za-z0-9-]+)?)=([^;\s,]+)"
)
_NAMED_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|authorization|bearer|token)\s*[:=]\s*([^\s,;]+)"
)


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a Z suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def redact_text(value: str, secrets_to_scrub: Iterable[str] = ()) -> str:
    """Remove route URLs, credentials, cookies, and token-like values."""
    result = str(value)
    result = _URL_RE.sub("https://<route>", result)
    result = _HOST_RE.sub("<route>", result)
    for secret in sorted(
        (item for item in secrets_to_scrub if isinstance(item, str) and item),
        key=len,
        reverse=True,
    ):
        result = result.replace(secret, "<redacted>")
    result = _SET_COOKIE_RE.sub(r"\1<redacted>", result)
    result = _COOKIE_PAIR_RE.sub(r"\1=<redacted>", result)
    result = _NAMED_SECRET_RE.sub(r"\1=<redacted>", result)
    result = _SIGNED_TOKEN_RE.sub("<redacted-token>", result)
    return result.replace("\r", "\\r").replace("\n", "\\n")


def redact_value(value: Any, secrets_to_scrub: Iterable[str] = ()) -> Any:
    """Recursively redact strings before they enter evidence."""
    if isinstance(value, str):
        return redact_text(value, secrets_to_scrub)
    if isinstance(value, dict):
        return {
            str(key): redact_value(item, secrets_to_scrub)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, secrets_to_scrub) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, secrets_to_scrub) for item in value]
    return value


def check_record(
    name: str,
    expected: Any,
    observed: Any,
    passed: bool,
    transport: Optional[str] = None,
    secrets_to_scrub: Iterable[str] = (),
) -> Dict[str, Any]:
    """Build one redacted PASS/FAIL check record."""
    record: Dict[str, Any] = {
        "name": name,
        "expected": redact_value(expected, secrets_to_scrub),
        "observed": redact_value(observed, secrets_to_scrub),
        "status": "PASS" if passed else "FAIL",
    }
    if transport is not None:
        record["transport"] = transport
    return record


def build_evidence(
    *,
    run_id: str,
    selected_platform: str,
    arch: str,
    os_version: str,
    python_version: str,
    package_versions: Dict[str, str],
    build_sha: str,
    build_identity_source: str,
    worktree_dirty: Optional[bool],
    runtime_dir_basis: str,
    opentunnel: Dict[str, Any],
    route_creation_path: str,
    public_url_redacted: str,
    checks: Sequence[Dict[str, Any]],
    started_at: str,
    finished_at: str,
    blockers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Create the stable D5 evidence envelope without adjudicating gate N0."""
    present = {item.get("name"): item.get("status") for item in checks}
    all_pass = all(present.get(name) == "PASS" for name in REQUIRED_CHECKS)
    verdict_hint = "PASS" if all_pass and not blockers else "BLOCKED" if blockers else "FAIL"
    return {
        "schema_version": 1,
        "run_id": run_id,
        "platform": selected_platform,
        "arch": arch,
        "os_version": os_version,
        "python": python_version,
        "package_versions": package_versions,
        "build_sha": build_sha,
        "build_identity_source": build_identity_source,
        "worktree_dirty": worktree_dirty,
        "runtime_dir_basis": runtime_dir_basis,
        "opentunnel": opentunnel,
        "route_creation_path": route_creation_path,
        "public_url_redacted": public_url_redacted,
        "checks": list(checks),
        "required_checks": list(REQUIRED_CHECKS),
        "verdict_hint": verdict_hint,
        "blockers": [redact_text(item) for item in (blockers or [])],
        "started_at": started_at,
        "finished_at": finished_at,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sum_for_asset(sums_text: str, asset_name: str) -> Optional[str]:
    """Return the SHA256SUMS value for exactly the requested filename."""
    for line in sums_text.splitlines():
        match = re.fullmatch(r"\s*([0-9a-fA-F]{64})\s+\*?([^\s]+)\s*", line)
        if match and match.group(2) == asset_name:
            return match.group(1).lower()
    return None


def verify_archive(
    archive_path: Path,
    sums_text: str,
    asset_name: str,
    pinned_digest: str,
) -> Dict[str, Any]:
    """Compare the archive digest with both the code pin and SHA256SUMS."""
    observed: Dict[str, Optional[str]] = {"archive": None, "sha256sums": None}
    try:
        observed["archive"] = _sha256_file(archive_path)
    except OSError as exc:
        observed["archive_error"] = type(exc).__name__
    observed["sha256sums"] = _sum_for_asset(sums_text, asset_name)
    passed = (
        observed.get("archive") == pinned_digest.lower()
        and observed.get("sha256sums") == pinned_digest.lower()
    )
    return {
        "name": "asset_checksum",
        "expected": {
            "pinned_digest": pinned_digest.lower(),
            "sha256sums_digest": pinned_digest.lower(),
        },
        "observed": observed,
        "status": "PASS" if passed else "FAIL",
    }


def _validate_tar_members(members: Sequence[tarfile.TarInfo]) -> None:
    """Reject unsafe names and unsupported archive entries before extraction."""
    for member in members:
        name = member.name.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
            raise ValueError("archive contains an unsafe member path")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError("archive contains an unsupported special member")
        if member.issym() or member.islnk():
            target = PurePosixPath(member.linkname.replace("\\", "/"))
            if target.is_absolute() or ".." in target.parts or re.match(
                r"^[A-Za-z]:", member.linkname
            ):
                raise ValueError("archive contains an unsafe link target")


def safe_extract_archive(archive_path: Path, destination: Path) -> Path:
    """Extract only validated data members and return the single CLI binary."""
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        _validate_tar_members(members)
        archive.extractall(path=destination, members=members, filter="data")
    candidates = [
        path
        for path in destination.rglob("opentunnel")
        if path.is_file() and not path.is_symlink()
    ]
    if len(candidates) != 1:
        raise ValueError("archive must contain exactly one regular opentunnel binary")
    binary = candidates[0]
    binary.chmod(binary.stat().st_mode | 0o111)
    try:
        binary.resolve().relative_to(destination.resolve())
    except ValueError as exc:
        raise ValueError("extracted binary escaped the destination") from exc
    return binary


def verify_and_extract_archive(
    archive_path: Path,
    sums_text: str,
    asset_name: str,
    pinned_digest: str,
    destination: Path,
) -> Tuple[Dict[str, Any], Optional[Path]]:
    """Fail before extraction unless both independent digest sources match."""
    result = verify_archive(archive_path, sums_text, asset_name, pinned_digest)
    if result["status"] != "PASS":
        return result, None
    try:
        return result, safe_extract_archive(archive_path, destination)
    except (OSError, tarfile.TarError, ValueError, EOFError) as exc:
        result["status"] = "FAIL"
        result["observed"]["extraction_error"] = type(exc).__name__
        return result, None


def _stable_binary_path(asset_name: str, install_root: Optional[Path] = None) -> Path:
    """Return the versioned executable path independent of an N0 run ID."""
    if asset_name not in ASSET_DIGESTS or not asset_name.endswith(".tar.gz"):
        raise ValueError("asset does not identify a pinned OpenTunnel archive")
    asset_stem = asset_name[: -len(".tar.gz")]
    root = install_root if install_root is not None else OPENTUNNEL_ROOT
    return root / RELEASE_VERSION / asset_stem / "opentunnel"


def _install_verified_binary(
    archive_path: Path,
    sums_text: str,
    asset_name: str,
    pinned_digest: str,
    install_root: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Optional[Path]]:
    """Verify each archive, extract privately, then atomically refresh its stable CLI."""
    result = verify_archive(archive_path, sums_text, asset_name, pinned_digest)
    if result["status"] != "PASS":
        return result, None

    root = install_root if install_root is not None else OPENTUNNEL_ROOT
    stable_binary = _stable_binary_path(asset_name, root)
    version_root = stable_binary.parent.parent
    try:
        if not _is_path_within(root, REPO_ROOT / "tmp/n0"):
            raise ValueError("stable OpenTunnel install root must remain under tmp/n0")
        version_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not _is_path_within(version_root, root):
            raise ValueError("stable OpenTunnel version directory escaped its install root")
        with tempfile.TemporaryDirectory(
            prefix=".extract-", dir=str(version_root)
        ) as staging_text:
            staging_dir = Path(staging_text)
            extracted_binary = safe_extract_archive(
                archive_path, staging_dir / "payload"
            )
            stable_binary.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not _is_path_within(stable_binary.parent, version_root):
                raise ValueError("stable OpenTunnel asset directory escaped its version root")
            extracted_digest = _sha256_file(extracted_binary)
            os.replace(extracted_binary, stable_binary)
        result["observed"]["binary_sha256"] = extracted_digest
        return result, stable_binary
    except (OSError, tarfile.TarError, ValueError, EOFError) as exc:
        result["status"] = "FAIL"
        result["observed"]["extraction_error"] = type(exc).__name__
        return result, None


def _is_outbound_connect_failure(message: str) -> bool:
    """Recognize OpenTunnel startup errors that indicate outbound connectivity failure."""
    lowered = message.casefold()
    return any(
        marker in lowered
        for marker in ("tcp connect error", "error sending request", "dns error")
    )


def _outbound_connect_failure_reason(binary_path: Optional[Path]) -> str:
    """Describe a blocked/failed OpenTunnel connection with its stable executable path."""
    relative_path = _relative_project_path(binary_path) if binary_path is not None else "unknown"
    return (
        "outbound connection from the OpenTunnel binary was blocked or failed "
        "(possible per-application firewall such as LuLu); stable binary path: "
        + relative_path
    )


def extract_public_url(output: str) -> Optional[str]:
    """Return only a complete, safe HTTPS authority from bounded CLI output."""
    sample = output[-MAX_URL_PARSE_CHARS:]
    for index, match in enumerate(_URL_CANDIDATE_RE.finditer(sample)):
        if index >= MAX_URL_CANDIDATES:
            break
        validated = _validated_public_url(match.group(0))
        if validated is not None:
            return validated
    return None


def _validated_public_url(candidate: str) -> Optional[str]:
    """Validate a complete OpenTunnel URL without trimming unsafe components."""
    if not candidate or any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        return None
    if "?" in candidate or "#" in candidate or "\\" in candidate:
        return None
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    normalized_host = hostname.casefold()
    if not normalized_host.endswith(".opentunnel.xyz"):
        return None
    labels = normalized_host.split(".")
    if (
        len(normalized_host) > 253
        or not all(_DNS_LABEL_RE.fullmatch(label) for label in labels)
        or parsed.netloc.casefold()
        not in (normalized_host, normalized_host + ":443")
    ):
        return None
    return "https://" + normalized_host


def _absence_proven_without_url(
    public_url: str,
    tunnel_was_started: bool,
    route_creation_path: str,
    identity_deleted: bool = False,
) -> bool:
    """Infer public absence only before startup or after identity deletion."""
    if public_url or tunnel_was_started:
        return False
    return route_creation_path == "not_started" or identity_deleted


def _safe_run_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}", value))


def _profile_name_from_run_id(run_id: str) -> str:
    """Normalize a run ID into the lowercase OpenTunnel profile slug."""
    profile_name = "n0-" + run_id.lower()
    if not _PROFILE_NAME_RE.fullmatch(profile_name):
        raise ValueError("run-id cannot form a lowercase OpenTunnel profile name")
    return profile_name


def _detected_platform() -> Tuple[str, str, str]:
    system = platform_module.system()
    machine = platform_module.machine()
    selected = "macos" if system == "Darwin" else "linux" if system == "Linux" else ""
    return selected, system, machine


def _normal_os_version() -> str:
    return platform_module.platform()


def _available_package_versions() -> Dict[str, str]:
    versions: Dict[str, str] = {}
    for distribution in ("requests", "python-socketio", "websocket-client", "uvicorn"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = "not-installed"
    return versions


def _run_git_value(args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
            env=_selected_environment(os.environ, ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE")),
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _valid_build_sha(value: Any) -> bool:
    """Accept only a complete SHA-1 or SHA-256 Git object identifier."""
    return isinstance(value, str) and _BUILD_SHA_RE.fullmatch(value) is not None


def _parse_host_build_identity(path: Path) -> Optional[Tuple[str, bool]]:
    """Parse exactly the host-written SHA and dirty-state record."""
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if len(lines) != 2:
        return None

    values: Dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or key not in ("sha", "dirty") or key in values:
            return None
        values[key] = value
    if set(values) != {"sha", "dirty"}:
        return None
    if not _valid_build_sha(values["sha"]) or values["dirty"] not in ("0", "1"):
        return None
    return values["sha"].lower(), values["dirty"] == "1"


def _resolved_build_identity(
    identity_path: Optional[Path] = None,
) -> Tuple[str, str, Optional[bool]]:
    """Prefer Git, then a strictly validated host file when Git is unavailable."""
    git_sha = _run_git_value(["rev-parse", "HEAD"])
    if _valid_build_sha(git_sha):
        git_status = _run_git_value(["status", "--porcelain"])
        worktree_dirty = None if git_status == "unknown" else bool(git_status)
        return git_sha.lower(), "git", worktree_dirty

    host_identity_path = identity_path or REPO_ROOT / "tmp/n0/build-identity.txt"
    host_identity = _parse_host_build_identity(host_identity_path)
    if host_identity is not None:
        return host_identity[0], "host_file", host_identity[1]
    return "unknown", "unknown", None


def _selected_environment(source: Mapping[str, str], keys: Sequence[str]) -> Dict[str, str]:
    """Copy only named non-OpenTunnel variables; never enumerate secret values."""
    selected: Dict[str, str] = {}
    for key in keys:
        if key.upper().startswith("OPENTUNNEL_"):
            continue
        value = source.get(key)
        if value is not None:
            selected[key] = value
    return selected


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate a subprocess group started in its own session, then reap it."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            try:
                process.kill()
            except OSError:
                pass
        process.wait(timeout=2)


def _capture_bounded_process_output(
    process: subprocess.Popen[bytes], timeout: int, max_bytes: int
) -> Tuple[int, str, bool]:
    """Drain a child pipe while retaining no more than max_bytes of output."""
    if process.stdout is None:
        raise RuntimeError("subprocess stdout pipe is unavailable")
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    output = bytearray()
    truncated = False
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    stdout = process.stdout
    try:
        os.set_blocking(stdout.fileno(), False)
        selector.register(stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout, output=bytes(output))
            events = selector.select(remaining)
            for key, _mask in events:
                try:
                    chunk = os.read(key.fd, MAX_CLI_OUTPUT_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                available = max_bytes - len(output)
                if available > 0:
                    output.extend(chunk[:available])
                if len(chunk) > available:
                    truncated = True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout, output=bytes(output))
        returncode = process.wait(timeout=remaining)
        return returncode, output.decode("utf-8", "replace"), truncated
    except subprocess.TimeoutExpired:
        _stop_process_group(process)
        raise
    finally:
        selector.close()
        stdout.close()


def _isolated_process_environment(
    run_dir: Path,
    xdg: Mapping[str, Path],
    runtime_dir: Path,
    source: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Build a minimal child environment with isolated profile and temp paths."""
    source_env = os.environ if source is None else source
    child_env = _selected_environment(source_env, CHILD_ENV_KEYS)
    temp_dir = run_dir / "tmp"
    temp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    child_env.update(
        {
            "HOME": str(run_dir / "home"),
            "XDG_CONFIG_HOME": str(xdg["config"]),
            "XDG_DATA_HOME": str(xdg["data"]),
            "XDG_STATE_HOME": str(xdg["state"]),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "TMPDIR": str(temp_dir),
            "TMP": str(temp_dir),
            "TEMP": str(temp_dir),
        }
    )
    return child_env


def _proc_open_tunnel_process_snapshot(proc_root: Path = Path("/proc")) -> Dict[int, str]:
    """Read only numeric /proc entries' comm files for exact OpenTunnel names."""
    try:
        process_entries = list(proc_root.iterdir())
    except OSError:
        return {}

    snapshot: Dict[int, str] = {}
    for process_entry in process_entries:
        if not process_entry.name.isdigit():
            continue
        try:
            process_name = (process_entry / "comm").read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if process_name == "opentunnel":
            snapshot[int(process_entry.name)] = "opentunnel"
    return snapshot


def _open_tunnel_process_snapshot(proc_root: Path = Path("/proc")) -> Dict[int, str]:
    """Snapshot OpenTunnel PIDs only, falling back to Linux /proc when needed."""
    is_linux = platform_module.system() == "Linux"
    try:
        result = subprocess.run(
            ["pgrep", "-x", "opentunnel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
            env=_selected_environment(os.environ, ("PATH",)),
        )
    except (OSError, subprocess.TimeoutExpired):
        return _proc_open_tunnel_process_snapshot(proc_root) if is_linux else {}
    snapshot: Dict[int, str] = {}
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.strip().isdigit():
                snapshot[int(line.strip())] = "opentunnel"
        if snapshot or not is_linux:
            return snapshot
    if is_linux:
        return _proc_open_tunnel_process_snapshot(proc_root)
    return {}


def _parse_nono_why_output(output: str) -> Dict[str, str]:
    """Parse nono's JSON response with a case-normalized status."""
    try:
        result_data = json.loads(output)
    except json.JSONDecodeError:
        return {"status": "error", "reason": "invalid_json"}
    if not isinstance(result_data, dict):
        return {"status": "error", "reason": "json_result_not_an_object"}
    raw_status = result_data.get("status")
    raw_reason = result_data.get("reason")
    status = raw_status.strip().casefold() if isinstance(raw_status, str) else "unknown"
    reason = raw_reason if isinstance(raw_reason, str) else "missing_reason"
    return {
        "status": status,
        "reason": redact_text(reason)[:MAX_LOG_ENTRY_CHARS],
    }


def _nono_status_proves_write_denial(status: Any) -> bool:
    """Only an explicit case-insensitive denied status proves sandbox denial."""
    return isinstance(status, str) and status.casefold() == "denied"


def _nono_write_denial_observation(path: Path) -> Dict[str, str]:
    """Read nono's JSON write-permission explanation with only real-user env."""
    real_home = str(Path(os.path.expanduser("~")).resolve())
    nono_env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": real_home,
    }
    if "NONO_CAP_FILE" in os.environ:
        nono_env["NONO_CAP_FILE"] = os.environ["NONO_CAP_FILE"]
    nono_executable = shutil.which("nono", path=nono_env["PATH"])
    if nono_executable is None:
        return {"status": "unavailable", "reason": "nono_not_on_path"}
    try:
        result = subprocess.run(
            [
                nono_executable,
                "why",
                "--self",
                "--json",
                "--path",
                str(path),
                "--op",
                "write",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            env=nono_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reason": type(exc).__name__}
    return _parse_nono_why_output(result.stdout)


def _path_presence(path: Path) -> Optional[bool]:
    """Distinguish a missing manager path from an unobservable one."""
    try:
        path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return True


def _linux_no_service_manager_observation() -> Dict[str, Any]:
    """Collect narrow evidence that no systemd manager is present in this Linux environment."""
    systemctl_resolvable = shutil.which("systemctl") is not None
    systemd_runtime_present = _path_presence(Path("/run/systemd/system"))
    runtime_dirs: List[Path] = []
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        runtime_dirs.append(Path(xdg_runtime).expanduser())
    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        runtime_dirs.append(Path("/run/user") / str(getuid()))

    user_manager_presence = [
        _path_presence(runtime_dir / "systemd/private")
        for runtime_dir in runtime_dirs
    ]
    if any(value is True for value in user_manager_presence):
        user_manager_socket_present: Optional[bool] = True
    elif runtime_dirs and all(value is False for value in user_manager_presence):
        user_manager_socket_present = False
    else:
        user_manager_socket_present = None

    try:
        pid1_comm = Path("/proc/1/comm").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        pid1_comm = None

    proven = bool(
        not systemctl_resolvable
        and systemd_runtime_present is False
        and user_manager_socket_present is False
        and isinstance(pid1_comm, str)
        and pid1_comm.casefold() != "systemd"
    )
    return {
        "basis": "linux_no_systemd_manager",
        "systemctl_resolvable": systemctl_resolvable,
        "systemd_runtime_present": systemd_runtime_present,
        "systemd_user_manager_socket_present": user_manager_socket_present,
        "pid1_comm": pid1_comm,
        "proven": proven,
    }


def _no_service_manager_is_proven(snapshot: Dict[str, Any]) -> bool:
    """Recheck the explicit Linux evidence instead of trusting a summary flag."""
    evidence = snapshot.get("no_service_manager_evidence")
    if snapshot.get("platform") != "linux" or not isinstance(evidence, dict):
        return False
    pid1_comm = evidence.get("pid1_comm")
    return bool(
        evidence.get("systemctl_resolvable") is False
        and evidence.get("systemd_runtime_present") is False
        and evidence.get("systemd_user_manager_socket_present") is False
        and isinstance(pid1_comm, str)
        and pid1_comm.casefold() != "systemd"
        and evidence.get("proven") is True
    )


def _service_snapshot(selected_platform: str) -> Dict[str, Any]:
    """Read only OpenTunnel service names from the current user's service view."""
    home = Path(os.path.expanduser("~")).resolve()
    env = _selected_environment(
        os.environ, ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE")
    )
    if selected_platform == "macos":
        launch_agents = home / "Library/LaunchAgents"
        observation_errors: List[Dict[str, Any]] = []
        try:
            result = subprocess.run(
                ["ls", "-1", str(launch_agents)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                check=False,
                env=env,
            )
            if result.returncode == 0:
                entries = [
                    line for line in result.stdout.splitlines()
                    if "opentunnel" in line.casefold()
                ]
                return {
                    "platform": selected_platform,
                    "available": True,
                    "real_user_view": "observed",
                    "source": "ls_launch_agents",
                    "launch_agents": entries,
                    "observation_errors": observation_errors,
                }
            observation_errors.append(
                {
                    "source": "ls_launch_agents",
                    "error": redact_text(
                        result.stderr.strip() or "exit_status_%d" % result.returncode
                    )[:MAX_LOG_ENTRY_CHARS],
                }
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            observation_errors.append(
                {"source": "ls_launch_agents", "error": type(exc).__name__}
            )

        try:
            result = subprocess.run(
                ["launchctl", "list"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
                env=env,
            )
            if result.returncode == 0:
                entries = [
                    line.strip() for line in result.stdout.splitlines()
                    if "opentunnel" in line.casefold()
                ]
                return {
                    "platform": selected_platform,
                    "available": True,
                    "real_user_view": "observed",
                    "source": "launchctl_list",
                    "launch_agents": entries,
                    "observation_errors": observation_errors,
                }
            observation_errors.append(
                {
                    "source": "launchctl_list",
                    "error": redact_text(
                        result.stderr.strip() or "exit_status_%d" % result.returncode
                    )[:MAX_LOG_ENTRY_CHARS],
                }
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            observation_errors.append(
                {"source": "launchctl_list", "error": type(exc).__name__}
            )

        return {
            "platform": selected_platform,
            "available": False,
            "real_user_view": "unobservable",
            "source": None,
            "launch_agents": [],
            "observation_errors": observation_errors,
            "sandbox_write_denial": _nono_write_denial_observation(launch_agents),
        }

    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser()
    unit_dir = config_dir / "systemd/user"
    try:
        unit_entries = sorted(
            item.name for item in unit_dir.iterdir()
            if "opentunnel" in item.name.casefold()
        ) if unit_dir.exists() else []
        unit_dir_available = True
    except OSError:
        unit_entries = []
        unit_dir_available = False
    systemd_env = _selected_environment(
        os.environ,
        (
            "PATH", "HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS", "LANG", "LC_ALL", "SYSTEMD_PAGER",
            "SYSTEMD_COLORS", "SYSTEMD_LESS",
        ),
    )
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "opentunnel*"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            env=systemd_env,
        )
        lines = [
            line.strip() for line in result.stdout.splitlines()
            if "opentunnel" in line.casefold()
        ]
        systemctl_available = result.returncode == 0
        error = "" if systemctl_available else redact_text(result.stderr.strip())
    except (OSError, subprocess.TimeoutExpired) as exc:
        lines = []
        systemctl_available = False
        error = type(exc).__name__
    return {
        "platform": selected_platform,
        "available": systemctl_available and unit_dir_available,
        "real_user_view": "observed" if systemctl_available and unit_dir_available else "unobservable",
        "source": "systemctl_user" if systemctl_available and unit_dir_available else None,
        "systemd_units": lines,
        "unit_files": unit_entries,
        "systemctl_error": error,
        "no_service_manager_evidence": _linux_no_service_manager_observation(),
    }


def _isolated_service_files_empty(service_files: Any) -> bool:
    """Require both isolated service locations to be readable and empty."""
    return isinstance(service_files, dict) and all(
        service_files.get(key) == [] for key in ("launch_agents", "systemd_units")
    )


def _parse_status_identifiers(output: str) -> Dict[str, str]:
    """Extract identity values so callers can redact them before retaining output."""
    hostname_match = re.search(r"(?im)^\s*Hostname:\s*(\S+)\s*$", output)
    tunnel_id_match = re.search(
        r"(?im)^\s*Tunnel ID:\s*(\S+)\s*$", output
    ) or re.search(
        r"(?i)\btunnel[_ -]?id\s*[:=]\s*[\"']?([^\s,;\"']+)", output
    )
    return {
        "hostname": hostname_match.group(1) if hostname_match else "",
        "tunnel_id": tunnel_id_match.group(1) if tunnel_id_match else "",
    }


def _parse_serve_status(output: str, route_name: str) -> Dict[str, Any]:
    """Resolve a URL only from a connected, exactly matching route status."""
    identifiers = _parse_status_identifiers(output)
    hostname = identifiers["hostname"]
    hostname_present = bool(
        hostname and _validated_public_url("https://" + hostname) is not None
    )
    service_match = re.search(r"(?im)^\s*Service:\s*(.+?)\s*$", output)
    service_line = service_match.group(1).strip() if service_match else ""
    service_connected = service_line.casefold().startswith("connected")
    expected_route_host = route_name + "." + hostname if hostname_present else ""
    route_matches = False
    route_mismatch: Optional[str] = None
    route_url: Optional[str] = None
    route_line_pattern = re.compile(r"^\s*(\S+)\s+(?:\u2192|->)\s+(\S+)\s*$")
    for line in output.splitlines():
        if "\u2192" not in line and "->" not in line:
            continue
        route_match = route_line_pattern.fullmatch(line)
        if route_match is None:
            route_mismatch = (
                "observed an unparseable arrow route line; expected "
                "route-name.hostname -> 127.0.0.1:8370"
            )
            continue
        route_host, target = route_match.groups()
        if (
            hostname_present
            and route_host.casefold() == expected_route_host.casefold()
            and target == "127.0.0.1:8370"
        ):
            route_matches = True
            route_url = _validated_public_url("https://" + route_host)
            continue
        if route_host.casefold() == route_name.casefold():
            host_shape = "bare route name"
        elif hostname and route_host.casefold() == hostname.casefold():
            host_shape = "hostname without route prefix"
        elif hostname_present and route_host.casefold() == expected_route_host.casefold():
            host_shape = "expected route host"
        elif hostname and route_host.casefold().endswith("." + hostname.casefold()):
            host_shape = "different route label on the expected hostname"
        elif route_host.casefold().startswith(route_name.casefold() + "."):
            host_shape = "route-name prefix with an unexpected hostname suffix"
        else:
            host_shape = "unexpected route-host form"
        route_mismatch = (
            "observed " + host_shape + " -> " + target
            + "; expected route-name.hostname -> 127.0.0.1:8370"
        )

    printed_url = extract_public_url(output)
    resolved_url = printed_url or (
        route_url if service_connected and route_matches else None
    )
    return {
        "hostname": hostname,
        "tunnel_id": identifiers["tunnel_id"],
        "service_connected": service_connected,
        "route_matches": route_matches,
        "route_mismatch": route_mismatch,
        "url": resolved_url,
    }


def _parse_identity_status(output: str) -> Dict[str, Any]:
    """Extract only safe identity and service-liveness facts from CLI status."""
    identifiers = _parse_status_identifiers(output)
    hostname = identifiers["hostname"]
    hostname_present = bool(
        hostname and _validated_public_url("https://" + hostname) is not None
    )
    tunnel_id_present = bool(identifiers["tunnel_id"])
    service_match = re.search(r"(?im)^\s*Service:\s*(.+?)\s*$", output)
    service_line = service_match.group(1).strip() if service_match else ""
    pid_match = re.search(r"(?i)\bpid\s+([0-9]+)\b", service_line)
    service_pid = int(pid_match.group(1)) if pid_match else None
    if service_pid is not None and service_pid <= 0:
        service_pid = None
    service_stopped = service_line.casefold().startswith("stopped")
    service_running = bool(service_line) and not service_stopped and service_pid is not None
    no_tunnel_message = "no tunnel exists for this profile" in output.casefold()
    return {
        "hostname_present": hostname_present,
        "tunnel_id_present": tunnel_id_present,
        "identity_confirmed": hostname_present and tunnel_id_present,
        "service_state": (
            "stopped" if service_stopped else "running" if service_running else "unknown"
        ),
        "service_pid": service_pid,
        "identity_absent": no_tunnel_message and not hostname and not tunnel_id_present,
    }


def _process_is_alive(pid: int) -> bool:
    """Conservatively report PID liveness; unknown permission errors count alive."""
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _service_registration_assessment(
    before: Dict[str, Any],
    after: Dict[str, Any],
    new_service_entries: Dict[str, List[str]],
    new_processes: Mapping[int, str],
    tracked_pids_alive: Sequence[int],
    identity_minting: Dict[str, Any],
) -> Dict[str, Any]:
    """Fail closed unless one allowed real-view basis and all cleanup checks pass."""
    real_view_observed = (
        before.get("real_user_view") == "observed"
        and after.get("real_user_view") == "observed"
    )
    sandbox_write_denied = (
        before.get("real_user_view") == "unobservable"
        and after.get("real_user_view") == "unobservable"
        and _nono_status_proves_write_denial(
            before.get("sandbox_write_denial", {}).get("status")
        )
        and _nono_status_proves_write_denial(
            after.get("sandbox_write_denial", {}).get("status")
        )
    )
    no_service_manager = (
        _no_service_manager_is_proven(before)
        and _no_service_manager_is_proven(after)
    )
    if real_view_observed:
        basis: Optional[str] = "observed_user_view"
    elif sandbox_write_denied:
        basis = "sandbox_write_denied"
    elif no_service_manager:
        basis = "no_service_manager"
    else:
        basis = None

    isolated_empty = (
        _isolated_service_files_empty(before.get("isolated_service_files_before"))
        and _isolated_service_files_empty(after.get("isolated_service_files_after"))
    )
    no_new_entries = not new_service_entries
    no_new_processes = not new_processes
    no_tracked_pids_alive = not tracked_pids_alive
    identity_minting_passed = identity_minting.get("passed") is True
    passed = bool(
        basis
        and identity_minting_passed
        and no_new_entries
        and isolated_empty
        and no_new_processes
        and no_tracked_pids_alive
    )
    return {
        "passed": passed,
        "service_registration_basis": basis,
        "identity_minting_passed": identity_minting_passed,
        "real_user_view_observed_before": before.get("real_user_view") == "observed",
        "real_user_view_observed_after": after.get("real_user_view") == "observed",
        "sandbox_write_denied_before": _nono_status_proves_write_denial(
            before.get("sandbox_write_denial", {}).get("status")
        ),
        "sandbox_write_denied_after": _nono_status_proves_write_denial(
            after.get("sandbox_write_denial", {}).get("status")
        ),
        "no_service_manager_before": _no_service_manager_is_proven(before),
        "no_service_manager_after": _no_service_manager_is_proven(after),
        "isolated_home_service_files_empty": isolated_empty,
        "new_opentunnel_entries": new_service_entries,
        "new_process_ids": sorted(new_processes),
        "tracked_pids_alive": list(tracked_pids_alive),
    }


def _is_port_free(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        return probe.connect_ex((host, port)) != 0
    finally:
        probe.close()


def _is_path_within(path: Path, root: Path) -> bool:
    """Return whether a path resolves beneath a designated scratch root."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _validate_runtime_parent(path: Path) -> Path:
    """Accept only a private, real runtime mount outside the repository tree."""
    if not path.is_absolute():
        raise ValueError("runtime-parent must be an absolute path")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("runtime-parent must be an existing real directory") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("runtime-parent must be an existing real directory")
    if resolved != path:
        raise ValueError("runtime-parent must not resolve through symlinks")
    if metadata.st_uid != os.getuid():
        raise ValueError("runtime-parent must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError("runtime-parent mode must be exactly 0700")
    if _is_path_within(resolved, REPO_ROOT):
        raise ValueError("runtime-parent must be outside the repository tree")
    return resolved


def _relative_project_path(path: Path) -> str:
    """Keep filesystem locations in evidence relative to the repository."""
    try:
        return path.resolve(strict=False).relative_to(REPO_ROOT).as_posix()
    except (OSError, RuntimeError, ValueError):
        return "outside-project"


def _write_private(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _iter_bounded_log_lines(path: Path) -> Iterable[Optional[str]]:
    """Yield bounded UTF-8 lines, replacing oversized raw lines with None."""
    with path.open("rb") as stream:
        while True:
            raw_line = stream.readline(MAX_DAEMON_LOG_LINE_BYTES + 1)
            if not raw_line:
                return
            oversized = len(raw_line) > MAX_DAEMON_LOG_LINE_BYTES
            while oversized and not raw_line.endswith(b"\n"):
                raw_line = stream.readline(MAX_DAEMON_LOG_LINE_BYTES + 1)
                if not raw_line:
                    break
            if oversized:
                yield None
            else:
                yield raw_line.decode("utf-8", "replace")


def _headers_from_cookie(cookie_header: Optional[str]) -> Dict[str, str]:
    return {"Cookie": cookie_header} if cookie_header else {}


def _response_observation(response: requests.Response) -> Dict[str, Any]:
    return {"status_code": response.status_code, "content_type": response.headers.get("Content-Type", "")}


class N0Run:
    """Own one isolated platform run and its evidence/process lifecycle."""

    def __init__(
        self,
        selected_platform: str,
        run_id: str,
        keep_identity: bool,
        runtime_parent: Optional[Path] = None,
    ) -> None:
        self.selected_platform = selected_platform
        self.run_id = run_id
        self.profile = _profile_name_from_run_id(run_id)
        self.route_name = self.profile
        self.keep_identity = keep_identity
        self.runtime_parent_override = runtime_parent
        self.runtime_parent: Optional[Path] = None
        self.runtime_dir_basis = "unknown"
        self.runtime_probe_observation: Optional[Dict[str, Any]] = None
        self.daemon_log_tail_redacted = ""
        self.daemon_log_files_preserved = 0
        self.started_at = utc_now()
        self.finished_at = ""
        self.system, self.machine = platform_module.system(), platform_module.machine()
        self.arch = self.machine
        self.asset_name = PLATFORM_ASSETS.get((self.system, self.machine), "")
        self.expected_digest = ASSET_DIGESTS.get(self.asset_name, "")
        self.run_dir = REPO_ROOT / "tmp/router-rollout/v2-network" / (
            "n0-" + selected_platform + "-" + run_id
        )
        self.download_dir = OPENTUNNEL_ROOT / "downloads" / run_id
        self.checks: List[Dict[str, Any]] = []
        self.blockers: List[str] = []
        self.http_wait_observations: Dict[str, Dict[str, Any]] = {}
        self.sensitive_values: List[str] = [self.route_name]
        self.route_creation_path = "not_started"
        self.public_url = ""
        self.public_host = ""
        self.fixture_password = ""
        self.cookie_header = ""
        self.binary: Optional[Path] = None
        self.stable_binary_path: Optional[Path] = (
            _stable_binary_path(self.asset_name) if self.asset_name else None
        )
        self.fixture_process: Optional[subprocess.Popen[bytes]] = None
        self.tunnel_process: Optional[subprocess.Popen[bytes]] = None
        self.owned_processes: List[Tuple[str, subprocess.Popen[bytes]]] = []
        self.process_readers: Dict[int, threading.Thread] = {}
        self.socket_clients: List[socketio.Client] = []
        self.reader_threads: List[threading.Thread] = []
        self.log_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.log_sizes: Dict[str, int] = {}
        self.tunnel_output: Deque[str] = deque(maxlen=MAX_TUNNEL_OUTPUT_LINES)
        self.env: Dict[str, str] = {}
        self.identity_cli_env: Dict[str, str] = {}
        self.xdg: Dict[str, Path] = {}
        self.runtime_dir: Optional[Path] = None
        self.identity_path_dir: Optional[Path] = None
        self.profile_config: Optional[Path] = None
        self.identity_up_attempted = False
        self.identity_daemon_pids: List[int] = []
        self.identity_minting_observation: Dict[str, Any] = {
            "status": "not_attempted",
            "passed": False,
        }
        self.identity_deleted = True
        self.identity_delete_observation: Dict[str, Any] = {
            "attempted": False,
            "passed": True,
            "reason": "identity_not_created",
        }
        self.route_removed = False
        self.fixture_stopped = False
        self.tunnel_stopped = False
        self.asset_info: Dict[str, Any] = {
            "version": "not_checked",
            "asset": self.asset_name or "unsupported-platform-architecture",
            "digest": None,
            "digest_expected": self.expected_digest or None,
            "sums_match": False,
            "binary_path": (
                _relative_project_path(self.stable_binary_path)
                if self.stable_binary_path is not None
                else None
            ),
            "binary_sha256": None,
        }
        self.processes_before: Dict[int, str] = {}
        self.services_before: Dict[str, Any] = {}

    def log(self, message: str) -> None:
        self.append_log("driver.log", "%s %s" % (utc_now(), message))

    def _remember_status_secrets(self, output: str) -> None:
        """Register parsed tunnel identity values before status output is retained."""
        identifiers = _parse_status_identifiers(output)
        for value in identifiers.values():
            if value and value not in self.sensitive_values:
                self.sensitive_values.append(value)

    def append_log(self, filename: str, message: str) -> None:
        self.run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw_message = redact_text(
            str(message).rstrip("\r\n"), self.sensitive_values
        )
        if len(raw_message) > MAX_LOG_ENTRY_CHARS:
            raw_message = raw_message[:MAX_LOG_ENTRY_CHARS] + " [entry truncated]"
        payload = (raw_message + "\n").encode("utf-8")
        with self.log_lock:
            remaining = MAX_LOG_BYTES - self.log_sizes.get(filename, 0)
            if remaining <= 0:
                return
            if len(payload) > remaining:
                marker = b"[log capped]\n"
                if remaining >= len(marker):
                    clipped = payload[: remaining - len(marker)].decode("utf-8", "ignore")
                    payload = clipped.encode("utf-8") + marker
                else:
                    payload = payload[:remaining].decode("utf-8", "ignore").encode("utf-8")
            with (self.run_dir / filename).open("ab") as stream:
                stream.write(payload)
            self.log_sizes[filename] = self.log_sizes.get(filename, 0) + len(payload)

    def add_check(
        self,
        name: str,
        expected: Any,
        observed: Any,
        passed: bool,
        transport: Optional[str] = None,
    ) -> None:
        self.checks.append(
            check_record(
                name,
                expected,
                observed,
                passed,
                transport=transport,
                secrets_to_scrub=self.sensitive_values,
            )
        )
        self.log("[%s] %s" % ("PASS" if passed else "FAIL", name))

    def prepare_isolation(self) -> None:
        if self.runtime_parent_override is None:
            runtime_parent = REPO_ROOT / "tmp/n0/r"
            runtime_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.runtime_dir_basis = "project_tmp"
        else:
            runtime_parent = _validate_runtime_parent(self.runtime_parent_override)
            self.runtime_dir_basis = "override_tmpfs"
        self.runtime_parent = runtime_parent

        self.run_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.run_dir.mkdir(mode=0o700, exist_ok=False)
        self.download_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.download_dir.parent, 0o700)
        self.download_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(self.download_dir, 0o700)
        for filename in ("driver.log", "fixture.log", "tunnel.log", "checksums.txt"):
            artifact = self.run_dir / filename
            artifact.touch(mode=0o600, exist_ok=False)
            artifact.chmod(0o600)
        for child in (
            "home",
            "xdg/config",
            "xdg/data",
            "xdg/state",
            "empty-path",
        ):
            path = self.run_dir / child
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(path, 0o700)
        self.identity_path_dir = self.run_dir / "empty-path"
        runtime_id = hashlib.sha256(
            (self.run_id + ":" + str(time.time_ns())).encode("utf-8")
        ).hexdigest()[:4]
        self.runtime_dir = runtime_parent / runtime_id
        self.runtime_dir.mkdir(mode=0o700, exist_ok=False)
        os.chmod(self.runtime_dir, 0o700)
        profile_socket = self.runtime_dir / "opentunnel" / (self.profile + ".sock")
        if len(os.fsencode(str(profile_socket))) >= MAX_UNIX_SOCKET_PATH:
            raise ValueError("the isolated OpenTunnel runtime socket path exceeds the Unix limit")
        self.xdg = {
            "config": self.run_dir / "xdg/config",
            "data": self.run_dir / "xdg/data",
            "state": self.run_dir / "xdg/state",
        }
        if self.runtime_dir is None:
            raise RuntimeError("isolated runtime directory is not initialized")
        self.env = _isolated_process_environment(
            self.run_dir,
            self.xdg,
            self.runtime_dir,
        )
        self.identity_cli_env = dict(self.env)
        self.identity_cli_env["PATH"] = str(self.identity_path_dir)
        self.profile_config = self.xdg["config"] / "opentunnel" / (self.profile + ".toml")
        self.profile_config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.processes_before = _open_tunnel_process_snapshot()
        self.services_before = _service_snapshot(self.selected_platform)
        self.services_before["processes_before"] = sorted(self.processes_before)
        self.services_before["isolated_service_files_before"] = self._isolated_service_files()
        self.log("Prepared isolated XDG profile and short project-local runtime directory")

    def _download(self, url: str, destination: Path, max_bytes: int) -> None:
        partial = destination.with_suffix(destination.suffix + ".part")
        total = 0
        try:
            with requests.get(url, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > max_bytes:
                    raise ValueError("download exceeds the configured size limit")
                with partial.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("download exceeds the configured size limit")
                        stream.write(chunk)
            partial.replace(destination)
        except Exception:
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
            raise

    def download_and_verify(self) -> bool:
        if not self.asset_name or not self.expected_digest:
            self.add_check(
                "asset_checksum",
                "supported pinned OS/architecture",
                {"system": self.system, "arch": self.machine},
                False,
            )
            return False
        archive_path = self.download_dir / self.asset_name
        sums_path = self.download_dir / "SHA256SUMS"
        sums_text = ""
        download_error = ""
        try:
            self._download(RELEASE_ROOT + "/SHA256SUMS", sums_path, 1024 * 1024)
            sums_text = sums_path.read_text(encoding="ascii")
            self._download(RELEASE_ROOT + "/" + self.asset_name, archive_path, MAX_ARCHIVE_BYTES)
        except (OSError, requests.RequestException, ValueError, UnicodeDecodeError) as exc:
            download_error = "%s: %s" % (type(exc).__name__, str(exc))
            self.append_log("tunnel.log", "asset download failed: " + download_error)
            (self.run_dir / "checksums.txt").write_text(
                redact_text(sums_text, self.sensitive_values) + "\n", encoding="utf-8"
            )
            observed = {"download_error": redact_text(download_error, self.sensitive_values)}
            self.asset_info["digest_expected"] = self.expected_digest
            self.add_check(
                "asset_checksum",
                {"pinned_digest": self.expected_digest, "downloaded_SHA256SUMS": "matching entry required"},
                observed,
                False,
            )
            if self._is_relay_or_certificate_blocker(download_error):
                self.blockers.append(download_error)
            return False

        (self.run_dir / "checksums.txt").write_text(sums_text, encoding="ascii")
        digest = _sha256_file(archive_path)
        self.asset_info["digest"] = digest
        result, stable_binary = _install_verified_binary(
            archive_path,
            sums_text,
            self.asset_name,
            self.expected_digest,
        )
        self.asset_info["sums_match"] = result["status"] == "PASS"
        self.add_check(
            "asset_checksum",
            result["expected"],
            result["observed"],
            result["status"] == "PASS",
        )
        if result["status"] != "PASS":
            return False
        self.binary = stable_binary
        self.stable_binary_path = stable_binary
        if self.binary is None:
            return False
        self.asset_info["binary_path"] = _relative_project_path(self.binary)
        self.asset_info["binary_sha256"] = result["observed"].get("binary_sha256")
        version_result, output_truncated = self._run_cli(
            ["--version"], timeout=10, record_output=True
        )
        version_lines = version_result.stdout.strip().splitlines()
        if version_result.returncode == 0 and not output_truncated and version_lines:
            self.asset_info["version"] = version_lines[0][:200]
        else:
            self.asset_info["version"] = "unsupported"
        self.asset_info["version"] = redact_text(
            str(self.asset_info["version"]), self.sensitive_values
        )
        return True

    @staticmethod
    def _is_relay_or_certificate_blocker(message: str) -> bool:
        lowered = message.casefold()
        return any(
            term in lowered
            for term in (
                "relay refused",
                "relay refusal",
                "connection refused",
                "too many tunnels",
                "certificate limit",
                "certificate issuance",
                "certificate not ready",
                "cert_not_ready",
                "certificate verify failed",
                "certificate verify error",
                "too many certificates",
                "rate limited",
                "rate limit",
                "http 429",
                "status 429",
                "http 525",
                "http 503",
            )
        )

    def _run_cli(
        self,
        args: Sequence[str],
        timeout: int,
        record_output: bool = False,
        environment: Optional[Mapping[str, str]] = None,
    ) -> Tuple[subprocess.CompletedProcess[str], bool]:
        if self.binary is None:
            raise RuntimeError("OpenTunnel binary is not verified")
        command = [str(self.binary), *args]
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            env=dict(self.env if environment is None else environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.owned_processes.append(("cli.log", process))
        try:
            returncode, output, truncated = _capture_bounded_process_output(
                process, timeout, MAX_CLI_OUTPUT_BYTES
            )
        except BaseException as exc:
            partial_output = getattr(exc, "output", None)
            if isinstance(partial_output, bytes):
                partial_text = partial_output.decode("utf-8", "replace")
            elif isinstance(partial_output, str):
                partial_text = partial_output
            else:
                partial_text = ""
            if partial_text:
                self._remember_status_secrets(partial_text)
                self.append_log("tunnel.log", partial_text)
            if isinstance(exc, subprocess.TimeoutExpired):
                self.append_log("tunnel.log", "OpenTunnel CLI command timed out")
            if process.poll() is None:
                self.stop_owned_process(process)
            raise
        result = subprocess.CompletedProcess(
            command, returncode=returncode, stdout=output, stderr=None
        )
        self._remember_status_secrets(result.stdout)
        if record_output or result.stdout:
            self.append_log("tunnel.log", result.stdout)
        if truncated:
            self.append_log(
                "tunnel.log",
                "[OpenTunnel CLI output capped at %d bytes]" % MAX_CLI_OUTPUT_BYTES,
            )
        return result, truncated

    def _write_profile_config(self) -> None:
        if self.profile_config is None:
            raise RuntimeError("profile path is not initialized")
        text = "[routes]\n\"%s\" = \"127.0.0.1:8370\"\n" % self.route_name
        self.profile_config.write_text(text, encoding="ascii")
        self.profile_config.chmod(0o600)

    def _isolated_service_files(self) -> Dict[str, List[str]]:
        """List only service entries under this run's isolated HOME/XDG tree."""
        entries: Dict[str, List[str]] = {}
        directories = (
            ("launch_agents", self.run_dir / "home/Library/LaunchAgents"),
            ("systemd_units", self.xdg.get("config", self.run_dir) / "systemd/user"),
        )
        for key, directory in directories:
            try:
                entries[key] = sorted(
                    item.name for item in directory.iterdir()
                    if "opentunnel" in item.name.casefold()
                ) if directory.exists() else []
            except OSError:
                entries[key] = ["<snapshot-error>"]
        return entries

    def _environment_isolation_observation(self) -> Dict[str, Any]:
        """Describe only isolated paths and safe variable names, never values."""
        expected_paths = {
            "home": self.run_dir / "home",
            "xdg_config": self.run_dir / "xdg/config",
            "xdg_data": self.run_dir / "xdg/data",
            "xdg_state": self.run_dir / "xdg/state",
            "xdg_runtime": self.runtime_dir,
            "temp": self.run_dir / "tmp",
            "tmp": self.run_dir / "tmp",
            "temp_alias": self.run_dir / "tmp",
        }
        env_keys = {
            "home": "HOME",
            "xdg_config": "XDG_CONFIG_HOME",
            "xdg_data": "XDG_DATA_HOME",
            "xdg_state": "XDG_STATE_HOME",
            "xdg_runtime": "XDG_RUNTIME_DIR",
            "temp": "TMPDIR",
            "tmp": "TMP",
            "temp_alias": "TEMP",
        }
        actual_paths = {key: self.env.get(env_keys[key]) for key in expected_paths}
        path_isolation: Dict[str, bool] = {}
        for key, expected in expected_paths.items():
            actual = actual_paths[key]
            if expected is None or actual is None:
                path_isolation[key] = False
                continue
            if key == "xdg_runtime":
                allowed_root = self.runtime_parent or REPO_ROOT / "tmp/n0"
            else:
                allowed_root = self.run_dir
            try:
                path_isolation[key] = (
                    Path(actual).resolve(strict=False) == expected.resolve(strict=False)
                    and _is_path_within(Path(actual), allowed_root)
                )
            except (OSError, RuntimeError, ValueError):
                path_isolation[key] = False

        allowed_names = set(CHILD_ENV_KEYS).union(
            {
                "HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_STATE_HOME",
                "XDG_RUNTIME_DIR",
                "TMPDIR",
                "TMP",
                "TEMP",
            }
        )
        unexpected_env_keys = sorted(set(self.env) - allowed_names)
        opentunnel_env_keys = sorted(
            key for key in self.env if key.upper().startswith("OPENTUNNEL_")
        )
        passed = (
            bool(self.env)
            and all(path_isolation.values())
            and not unexpected_env_keys
            and not opentunnel_env_keys
        )
        return {
            "passed": passed,
            "runtime_dir_basis": self.runtime_dir_basis,
            "paths_isolated": path_isolation,
            "paths_relative_to_project": {
                key: _relative_project_path(Path(value)) if value else None
                for key, value in actual_paths.items()
            },
            "preserved_environment_variable_names": sorted(
                key for key in self.env if key in CHILD_ENV_KEYS
            ),
            "unexpected_environment_variable_names": unexpected_env_keys,
            "opentunnel_environment_variable_names": opentunnel_env_keys,
        }

    def _read_process_output(self, process: subprocess.Popen[bytes], filename: str) -> None:
        if process.stdout is None:
            return
        try:
            while True:
                raw_line = process.stdout.readline(MAX_OUTPUT_LINE_BYTES + 1)
                if not raw_line:
                    break
                line_bytes = raw_line.rstrip(b"\r\n")
                truncated = len(line_bytes) > MAX_OUTPUT_LINE_BYTES
                line = line_bytes[:MAX_OUTPUT_LINE_BYTES].decode("utf-8", "replace")
                if truncated:
                    line += " [line truncated]"
                self._remember_status_secrets(line)
                if filename == "tunnel.log":
                    with self.output_lock:
                        self.tunnel_output.append(line)
                self.append_log(filename, line)
        except (OSError, ValueError):
            self.log("output reader ended")

    def _start_process(self, command: Sequence[str], filename: str) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            list(command),
            cwd=str(REPO_ROOT),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.owned_processes.append((filename, process))
        thread = threading.Thread(
            target=self._read_process_output,
            args=(process, filename),
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            self.stop_owned_process(process)
            raise
        self.reader_threads.append(thread)
        self.process_readers[process.pid] = thread
        return process

    def _start_serve(self) -> subprocess.Popen[bytes]:
        if self.binary is None:
            raise RuntimeError("OpenTunnel binary is not verified")
        self.tunnel_output = deque(maxlen=MAX_TUNNEL_OUTPUT_LINES)
        self.tunnel_stopped = False
        process = self._start_process(
            [str(self.binary), "serve", "--profile", self.profile], "tunnel.log"
        )
        self.tunnel_process = process
        return process

    def _query_status_observation(self, timeout: int = 15) -> Dict[str, Any]:
        """Query status in the foreground serve environment and parse its route."""
        try:
            result, output_truncated = self._run_cli(
                ["status", "--profile", self.profile],
                timeout=timeout,
                record_output=True,
                environment=self.env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.log("status query failed: " + type(exc).__name__)
            return {
                "hostname": "",
                "tunnel_id": "",
                "service_connected": False,
                "route_matches": False,
                "route_mismatch": None,
                "url": None,
            }
        if output_truncated:
            self.log("status query output exceeded the capture limit")
            return {
                "hostname": "",
                "tunnel_id": "",
                "service_connected": False,
                "route_matches": False,
                "route_mismatch": None,
                "url": None,
            }
        self._remember_status_secrets(result.stdout)
        return _parse_serve_status(result.stdout, self.route_name)

    def _query_status_url(self) -> Optional[str]:
        """Return only a URL accepted by the current profile status parser."""
        return self._query_status_observation().get("url")

    def _discover_from_serve(self, process: subprocess.Popen[bytes], timeout: int) -> Optional[str]:
        deadline = time.monotonic() + timeout
        next_status_poll = time.monotonic()
        last_route_mismatch: Optional[str] = None
        while time.monotonic() < deadline:
            with self.output_lock:
                observed_output = "\n".join(self.tunnel_output)
            url = extract_public_url(observed_output)
            if url:
                return url
            now = time.monotonic()
            if now >= next_status_poll:
                remaining = deadline - now
                if remaining < 1:
                    break
                observation = self._query_status_observation(
                    timeout=min(15, int(remaining))
                )
                status_url = observation.get("url")
                if isinstance(status_url, str) and status_url:
                    return status_url
                mismatch = observation.get("route_mismatch")
                if isinstance(mismatch, str) and mismatch:
                    last_route_mismatch = mismatch
                elif observation.get("route_matches"):
                    last_route_mismatch = None
                next_status_poll = time.monotonic() + STATUS_POLL_INTERVAL
            if process.poll() is not None:
                break
            sleep_for = min(0.25, max(0.0, next_status_poll - time.monotonic()))
            if sleep_for:
                time.sleep(sleep_for)

        with self.output_lock:
            observed_output = "\n".join(self.tunnel_output)
        url = extract_public_url(observed_output)
        if url:
            return url
        if last_route_mismatch:
            reason = (
                "OpenTunnel status route shape did not match "
                "route-name.hostname -> 127.0.0.1:8370; " + last_route_mismatch
            )
            if reason not in self.blockers:
                self.blockers.append(reason)
                self.log(reason)
        return None

    def _identity_path_preflight(self) -> Dict[str, Any]:
        """Prove service-manager commands cannot resolve on the identity CLI PATH."""
        path_value = self.identity_cli_env.get("PATH", "")
        path_directory = Path(path_value) if path_value else None
        path_is_private_empty = False
        if path_directory is not None and self.identity_path_dir is not None:
            try:
                path_is_private_empty = (
                    path_directory.resolve() == self.identity_path_dir.resolve()
                    and _is_path_within(path_directory, self.run_dir)
                    and path_directory.is_dir()
                    and not any(path_directory.iterdir())
                )
            except OSError:
                path_is_private_empty = False
        resolvable = {
            name: shutil.which(name, path=path_value) is not None
            for name in ("launchctl", "systemctl")
        }
        safe = path_is_private_empty and not any(resolvable.values())
        return {
            "status": "READY" if safe else "BLOCKED",
            "path_directory": (
                _relative_project_path(path_directory) if path_directory else None
            ),
            "path_directory_is_private_and_empty": path_is_private_empty,
            "service_manager_commands_resolvable": resolvable,
        }

    def _run_identity_cli(
        self, args: Sequence[str], timeout: int
    ) -> Dict[str, Any]:
        """Run a bounded identity command and retain only redacted bounded output."""
        try:
            result, truncated = self._run_cli(
                args,
                timeout=timeout,
                record_output=True,
                environment=self.identity_cli_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            partial_output = getattr(exc, "output", None)
            if isinstance(partial_output, bytes):
                partial_text = partial_output.decode("utf-8", "replace")
            elif isinstance(partial_output, str):
                partial_text = partial_output
            else:
                partial_text = ""
            self._remember_status_secrets(partial_text)
            observation = {
                "returncode": None,
                "output_truncated": False,
                "output_redacted": redact_text(
                    partial_text, self.sensitive_values
                )[:MAX_LOG_ENTRY_CHARS],
                "error": type(exc).__name__,
                "outbound_connect_failure": _is_outbound_connect_failure(partial_text),
            }
            if args and args[-1] == "status":
                observation["status_facts"] = _parse_identity_status(partial_text)
            return observation
        except Exception as exc:
            return {
                "returncode": None,
                "output_truncated": False,
                "output_redacted": "",
                "error": type(exc).__name__,
            }
        self._remember_status_secrets(result.stdout)
        observation = {
            "returncode": result.returncode,
            "output_truncated": truncated,
            "output_redacted": redact_text(
                result.stdout, self.sensitive_values
            )[:MAX_LOG_ENTRY_CHARS],
            "error": None,
            "outbound_connect_failure": _is_outbound_connect_failure(result.stdout),
        }
        if args and args[-1] == "status":
            observation["status_facts"] = _parse_identity_status(result.stdout)
        return observation

    def _probe_runtime_dir(self) -> Dict[str, Any]:
        """Verify flock and AF_UNIX operations before any identity/relay command."""
        if self.runtime_dir is None:
            return {"passed": False, "errno_name": "ENOENT", "error": "RuntimeDirMissing"}

        lock_path = self.runtime_dir / ".n0-runtime-probe.lock"
        socket_path = self.runtime_dir / "p.sock"
        lock_fd: Optional[int] = None
        lock_created = False
        socket_bound = False
        server: Optional[socket.socket] = None
        client: Optional[socket.socket] = None
        accepted: Optional[socket.socket] = None
        error_name: Optional[str] = None
        error_type: Optional[str] = None

        def capture_error(exc: BaseException) -> None:
            nonlocal error_name, error_type
            if error_name is None:
                error_number = getattr(exc, "errno", None)
                error_name = errno.errorcode.get(error_number, "UNKNOWN")
                error_type = type(exc).__name__

        try:
            if len(os.fsencode(str(socket_path))) >= MAX_UNIX_SOCKET_PATH:
                raise OSError(errno.ENAMETOOLONG, "runtime probe socket path exceeds Unix limit")
            lock_fd = os.open(
                str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
            )
            lock_created = True
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.settimeout(2.0)
            server.bind(str(socket_path))
            socket_bound = True
            server.listen(1)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(str(socket_path))
            accepted, _address = server.accept()
        except (OSError, ValueError) as exc:
            capture_error(exc)
        except Exception as exc:
            capture_error(exc)
        finally:
            for probe_socket in (accepted, client, server):
                if probe_socket is not None:
                    try:
                        probe_socket.close()
                    except OSError as exc:
                        capture_error(exc)
            if socket_bound:
                try:
                    socket_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    capture_error(exc)
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError as exc:
                    capture_error(exc)
                try:
                    os.close(lock_fd)
                except OSError as exc:
                    capture_error(exc)
            if lock_created:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    capture_error(exc)

        return {
            "passed": error_name is None,
            "errno_name": error_name,
            "error": error_type,
        }

    def _preserve_daemon_logs(self) -> Dict[str, Any]:
        """Copy bounded daemon-log tails after redaction, without retaining secrets."""
        state_dir = self.xdg.get("state")
        if state_dir is None:
            return {
                "files_preserved": 0,
                "artifact": None,
                "tail_redacted": self.daemon_log_tail_redacted or None,
            }
        daemon_root = state_dir / "opentunnel"
        try:
            candidates = sorted(daemon_root.glob("*/daemon.log"))
        except OSError as exc:
            candidates = []
            self._daemon_log_preservation_failed(type(exc).__name__)
        if len(candidates) > MAX_DAEMON_LOG_FILES:
            self._daemon_log_preservation_failed("TooManyDaemonLogs")
            candidates = candidates[:MAX_DAEMON_LOG_FILES]

        readable_paths: List[Path] = []
        for path in candidates:
            try:
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise OSError(errno.EINVAL, "daemon log is not a regular file")
                for line in _iter_bounded_log_lines(path):
                    if line is not None:
                        self._remember_status_secrets(line)
                readable_paths.append(path)
            except OSError as exc:
                self._daemon_log_preservation_failed(errno.errorcode.get(exc.errno, type(exc).__name__))

        if not readable_paths:
            return {
                "files_preserved": 0,
                "artifact": "daemon.log.redacted" if self.daemon_log_tail_redacted else None,
                "tail_redacted": self.daemon_log_tail_redacted or None,
            }

        payload = bytearray()

        def append_redacted_line(line: str) -> None:
            payload.extend(line.encode("utf-8") + b"\n")
            excess = len(payload) - MAX_DAEMON_LOG_BYTES
            if excess > 0:
                del payload[:excess]

        for index, path in enumerate(readable_paths, start=1):
            append_redacted_line("--- daemon log %d ---" % index)
            try:
                for line in _iter_bounded_log_lines(path):
                    if line is None:
                        append_redacted_line("[oversized daemon log line omitted]")
                    else:
                        append_redacted_line(
                            redact_text(line.rstrip("\r\n"), self.sensitive_values)
                        )
            except OSError as exc:
                self._daemon_log_preservation_failed(errno.errorcode.get(exc.errno, type(exc).__name__))

        redacted_tail = payload.decode("utf-8", "ignore")
        try:
            _write_private(self.run_dir / "daemon.log.redacted", redacted_tail)
        except OSError as exc:
            self._daemon_log_preservation_failed(errno.errorcode.get(exc.errno, type(exc).__name__))
            return {
                "files_preserved": 0,
                "artifact": None,
                "tail_redacted": self.daemon_log_tail_redacted or None,
            }
        self.daemon_log_tail_redacted = redacted_tail[-MAX_DAEMON_LOG_TAIL_CHARS:]
        self.daemon_log_files_preserved = len(readable_paths)
        if self.identity_minting_observation.get("status") != "not_attempted":
            self.identity_minting_observation["daemon_log_tail_redacted"] = (
                self.daemon_log_tail_redacted
            )
        return {
            "files_preserved": self.daemon_log_files_preserved,
            "artifact": "daemon.log.redacted",
            "tail_redacted": self.daemon_log_tail_redacted,
        }

    def _daemon_log_preservation_failed(self, reason: str) -> None:
        blocker = "OpenTunnel daemon log could not be preserved (%s)" % reason
        if blocker not in self.blockers:
            self.blockers.append(blocker)
        try:
            self.log(blocker)
        except OSError:
            pass

    def _ensure_runtime_probe(self) -> Dict[str, Any]:
        if self.runtime_probe_observation is None:
            self.runtime_probe_observation = self._probe_runtime_dir()
            probe_passed = self.runtime_probe_observation.get("passed") is True
            self.add_check(
                "runtime_dir_probe",
                "runtime dir supports flock and AF_UNIX bind/listen/connect",
                self.runtime_probe_observation,
                probe_passed,
            )
        return self.runtime_probe_observation

    def _pid_is_alive(self, pid: int) -> bool:
        return _process_is_alive(pid)

    def _mint_identity_without_service_registration(self) -> bool:
        """Mint and stop the remote identity with OS service managers hidden."""
        runtime_probe = self._ensure_runtime_probe()
        if runtime_probe.get("passed") is not True:
            errno_name = runtime_probe.get("errno_name") or "UNKNOWN"
            reason = "runtime dir does not support AF_UNIX/flock (%s)" % errno_name
            self.route_creation_path = "up_blocked"
            self.identity_minting_observation = {
                "status": "BLOCKED",
                "passed": False,
                "runtime_dir_probe": runtime_probe,
                "up_invoked": False,
                "daemon_log_tail_redacted": None,
            }
            self.blockers.append(reason)
            self.log(reason)
            return False

        preflight = self._identity_path_preflight()
        observation: Dict[str, Any] = {
            "status": preflight["status"],
            "passed": False,
            "preflight": preflight,
            "runtime_dir_probe": runtime_probe,
        }
        if preflight["status"] != "READY":
            self.identity_minting_observation = observation
            self.route_creation_path = "up_blocked"
            reason = (
                "OpenTunnel up blocked: isolated PATH is not empty or a service manager resolves"
            )
            self.blockers.append(reason)
            self.log(reason)
            return False

        self.identity_up_attempted = True
        self.identity_deleted = False
        up_result = self._run_identity_cli(
            ["--profile", self.profile, "up"], timeout=IDENTITY_UP_TIMEOUT
        )
        daemon_log_observation = self._preserve_daemon_logs()
        up_connect_failure = up_result.get("outbound_connect_failure") is True
        if up_connect_failure:
            reason = _outbound_connect_failure_reason(
                self.stable_binary_path or self.binary
            )
            self.blockers.append(reason)
            self.log(reason)
        status_before_down = self._run_identity_cli(
            ["--profile", self.profile, "status"],
            timeout=IDENTITY_CLEANUP_TIMEOUT,
        )
        status_before_down_facts = status_before_down.get(
            "status_facts", _parse_identity_status("")
        )
        daemon_pid = status_before_down_facts.get("service_pid")
        if isinstance(daemon_pid, int) and daemon_pid not in self.identity_daemon_pids:
            self.identity_daemon_pids.append(daemon_pid)
        daemon_alive_after_up = (
            self._pid_is_alive(daemon_pid) if isinstance(daemon_pid, int) else False
        )
        isolated_files_after_up = self._isolated_service_files()
        isolated_files_empty_after_up = _isolated_service_files_empty(
            isolated_files_after_up
        )

        # Always try to stop a possibly detached daemon, including after a failed
        # or timed-out `up` and after a status/isolated-file observation failure.
        daemon_log_observation = self._preserve_daemon_logs()
        down_result = self._run_identity_cli(
            ["--profile", self.profile, "down"],
            timeout=IDENTITY_CLEANUP_TIMEOUT,
        )
        daemon_log_observation = self._preserve_daemon_logs()
        status_after_down = self._run_identity_cli(
            ["--profile", self.profile, "status"],
            timeout=IDENTITY_CLEANUP_TIMEOUT,
        )
        status_after_down_facts = status_after_down.get(
            "status_facts", _parse_identity_status("")
        )
        post_down_pid = status_after_down_facts.get("service_pid")
        if isinstance(post_down_pid, int) and post_down_pid not in self.identity_daemon_pids:
            self.identity_daemon_pids.append(post_down_pid)
        daemon_pid_liveness_after_down = {
            str(pid): self._pid_is_alive(pid) for pid in self.identity_daemon_pids
        }
        daemon_pids_gone = not any(daemon_pid_liveness_after_down.values())

        up_ok = up_result["returncode"] == 0 and not up_result["output_truncated"]
        status_before_down_ok = (
            status_before_down["returncode"] == 0
            and not status_before_down["output_truncated"]
        )
        status_after_down_ok = (
            status_after_down["returncode"] == 0
            and not status_after_down["output_truncated"]
        )
        down_ok = down_result["returncode"] == 0 and not down_result["output_truncated"]
        passed = bool(
            up_ok
            and not up_connect_failure
            and status_before_down_ok
            and status_before_down_facts["identity_confirmed"]
            and status_before_down_facts["service_state"] == "running"
            and daemon_alive_after_up
            and isolated_files_empty_after_up
            and down_ok
            and status_after_down_ok
            and status_after_down_facts["service_state"] == "stopped"
            and daemon_pids_gone
        )
        observation.update(
            {
                "status": "PASS" if passed else "FAIL",
                "passed": passed,
                "up": up_result,
                "status_after_up": {
                    **status_before_down,
                    **status_before_down_facts,
                    "daemon_pid_alive": daemon_alive_after_up,
                },
                "isolated_service_files_after_up": isolated_files_after_up,
                "isolated_service_files_empty_after_up": isolated_files_empty_after_up,
                "down": down_result,
                "status_after_down": {
                    **status_after_down,
                    **status_after_down_facts,
                    "daemon_pid_liveness": daemon_pid_liveness_after_down,
                    "daemon_pids_gone": daemon_pids_gone,
                },
                "daemon_log_files_preserved": daemon_log_observation[
                    "files_preserved"
                ],
                "daemon_log_artifact": daemon_log_observation["artifact"],
                "daemon_log_tail_redacted": daemon_log_observation[
                    "tail_redacted"
                ],
            }
        )
        self.identity_minting_observation = observation
        if not passed:
            self.route_creation_path = "up_mint_failed"
            reason = (
                "OpenTunnel identity minting or unregistered daemon cleanup failed; "
                "foreground serve was not started"
            )
            self.blockers.append(reason)
            self.log(reason)
            return False

        self.route_creation_path = "up_minted_then_serve"
        return True

    def _delete_identity(self) -> Dict[str, Any]:
        """Delete any attempted remote identity and verify it no longer exists."""
        if not self.identity_up_attempted:
            self.identity_deleted = True
            self.identity_delete_observation = {
                "attempted": False,
                "passed": True,
                "reason": "identity_not_created",
            }
            return self.identity_delete_observation

        self._preserve_daemon_logs()
        delete_result = self._run_identity_cli(
            ["--profile", self.profile, "delete", "--yes"],
            timeout=IDENTITY_CLEANUP_TIMEOUT,
        )
        status_result = self._run_identity_cli(
            ["--profile", self.profile, "status"],
            timeout=IDENTITY_CLEANUP_TIMEOUT,
        )
        status_facts = status_result.get("status_facts", _parse_identity_status(""))
        passed = bool(
            delete_result["returncode"] == 0
            and not delete_result["output_truncated"]
            and status_result["returncode"] == 0
            and not status_result["output_truncated"]
            and status_facts["identity_absent"]
            and status_facts["service_state"] == "stopped"
        )
        self.identity_deleted = passed
        self.identity_delete_observation = {
            "attempted": True,
            "passed": passed,
            "delete": delete_result,
            "status_after_delete": {**status_result, **status_facts},
        }
        if not passed:
            reason = "OpenTunnel tunnel identity deletion was not verified"
            self.blockers.append(reason)
            self.log(reason)
        return self.identity_delete_observation

    def activate_tunnel(self) -> bool:
        if self.binary is None:
            self.blockers.append("verified OpenTunnel binary is unavailable; tunnel was not started")
            self.cleanup_route()
            return False
        if not self._mint_identity_without_service_registration():
            try:
                self.cleanup_route()
            except Exception:
                self.route_removed = False
            return False

        process: Optional[subprocess.Popen[bytes]] = None
        failure_reason = ""
        try:
            # Identity is minted and its unregistered helper daemon stopped
            # before this declarative route is written or foreground serve runs.
            self._write_profile_config()
            process = self._start_serve()
            url = self._discover_from_serve(process, timeout=60)
            if not url:
                output = "\n".join(self.tunnel_output)
                if _is_outbound_connect_failure(output):
                    failure_reason = _outbound_connect_failure_reason(
                        self.stable_binary_path or self.binary
                    )
                elif self._is_relay_or_certificate_blocker(output):
                    failure_reason = (
                        "OpenTunnel foreground serve was refused after identity setup"
                    )
                else:
                    failure_reason = (
                        "OpenTunnel foreground serve did not initialize after identity setup"
                    )
            else:
                self._set_public_url(url)
                return True
        except Exception as exc:
            if _is_outbound_connect_failure(str(exc)):
                failure_reason = _outbound_connect_failure_reason(
                    self.stable_binary_path or self.binary
                )
            else:
                failure_reason = (
                    "OpenTunnel foreground serve initialization failed (%s) after identity setup"
                ) % type(exc).__name__

        self.route_creation_path = "up_minted_then_serve_failed"
        self.blockers.append(failure_reason)
        self._preserve_daemon_logs()
        tunnel_processes = [
            owned
            for filename, owned in self.owned_processes
            if filename == "tunnel.log"
        ]
        if process is not None and all(process is not item for item in tunnel_processes):
            tunnel_processes.append(process)
        process_cleanup_failed = False
        for owned in tunnel_processes:
            try:
                if not self.stop_owned_process(owned):
                    process_cleanup_failed = True
            except Exception:
                process_cleanup_failed = True
        try:
            self.cleanup_route()
        except Exception:
            self.route_removed = False
        if process_cleanup_failed:
            self.blockers.append(
                "the declarative-route OpenTunnel process did not stop during failure cleanup"
            )
        if not self.route_removed:
            self.blockers.append("the failed declarative profile route could not be removed")
        self.log(failure_reason)
        return False

    def _set_public_url(self, url: str) -> None:
        validated = _validated_public_url(url)
        if validated is None:
            raise ValueError("OpenTunnel returned an unsafe or invalid public URL")
        parsed = urlsplit(validated)
        if not parsed.hostname:
            raise ValueError("OpenTunnel returned an invalid public hostname")
        self.public_url = validated
        self.public_host = parsed.netloc
        self.sensitive_values.extend([self.public_url, self.public_host, parsed.hostname, self.route_name])
        _write_private(self.run_dir / "url.private", self.public_url + "\n")

    def _wait_for_http(self, url: str, timeout: int, stage: str) -> bool:
        """Poll health while retaining bounded diagnostics and final failure context."""
        deadline = time.monotonic() + timeout
        observation: Dict[str, Any] = {
            "transient_failure_count": 0,
            "last_transient_failures": [],
            "ready": False,
        }
        last_failure_is_relay_or_certificate = False

        def record_transient_failure(
            message: str, relay_or_certificate: bool
        ) -> None:
            nonlocal last_failure_is_relay_or_certificate
            observation["transient_failure_count"] += 1
            safe_message = redact_text(
                message, self.sensitive_values
            )[:MAX_HTTP_WAIT_MESSAGE_CHARS]
            observations = observation["last_transient_failures"]
            observations.append(safe_message)
            del observations[:-MAX_HTTP_WAIT_MESSAGES]
            last_failure_is_relay_or_certificate = relay_or_certificate

        while time.monotonic() < deadline:
            try:
                response = requests.get(url, timeout=(3, 5))
                if response.status_code == 200 and response.text.strip() == "ok":
                    observation["ready"] = True
                    self.http_wait_observations[stage] = observation
                    return True
                if response.status_code == 200:
                    message = "HTTP 200 health response did not contain the expected marker"
                else:
                    message = "HTTP %d %s" % (
                        response.status_code, response.text[:256]
                    )
                response_relay_failure = (
                    response.status_code in (429, 503, 525)
                    and self._is_relay_or_certificate_blocker(message)
                )
                record_transient_failure(message, response_relay_failure)
            except requests.RequestException as exc:
                message = "%s: %s" % (type(exc).__name__, str(exc)[:256])
                record_transient_failure(
                    message, self._is_relay_or_certificate_blocker(message)
                )
            time.sleep(1)
        self.http_wait_observations[stage] = observation
        if last_failure_is_relay_or_certificate:
            reason = "OpenTunnel relay/certificate refusal during " + stage
            if reason not in self.blockers:
                self.blockers.append(reason)
        return False

    def _note_transport_blocker(self, exc: BaseException, stage: str) -> None:
        message = "%s: %s" % (type(exc).__name__, str(exc))
        if self._is_relay_or_certificate_blocker(message):
            reason = "OpenTunnel relay/certificate refusal during " + stage
            if reason not in self.blockers:
                self.blockers.append(reason)

    def start_fixture(self) -> bool:
        if not _is_port_free("127.0.0.1", 8370):
            self.add_check(
                "fixture_local_healthz",
                "port 8370 free for the isolated fixture",
                "port 8370 is already in use; no existing process was stopped",
                False,
            )
            return False
        self.fixture_password = "n0-" + hashlib.sha256(os.urandom(32)).hexdigest()
        self.sensitive_values.append(self.fixture_password)
        password_path = self.run_dir / "password.private"
        _write_private(password_path, self.fixture_password + "\n")
        fixture_script = Path(__file__).resolve().with_name("fixture_server.py")
        process = self._start_process(
            [
                sys.executable,
                str(fixture_script),
                "--password-file",
                str(password_path),
                "--public-host",
                self.public_host,
            ],
            "fixture.log",
        )
        self.fixture_process = process
        local_ready = self._wait_for_http(
            "http://127.0.0.1:8370/healthz",
            timeout=20,
            stage="local fixture health",
        )
        self.add_check(
            "fixture_local_healthz",
            "local GET /healthz returns 200 after fixture startup",
            {
                "ready": local_ready,
                "process_alive": process.poll() is None,
                "wait_observation": self.http_wait_observations.get(
                    "local fixture health"
                ),
            },
            local_ready and process.poll() is None,
        )
        return local_ready

    def _public_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> requests.Response:
        if not self.public_url:
            raise RuntimeError("public URL is not available")
        return requests.request(
            method,
            self.public_url + path,
            timeout=(5, 10),
            **kwargs,
        )

    def run_http_checks(self) -> None:
        if not self.public_url:
            return
        health_discovery_wait = self.http_wait_observations.get(
            "public health discovery"
        )
        try:
            response = self._public_request("GET", "/")
            static_ok = response.status_code == 200 and "html" in response.headers.get(
                "Content-Type", ""
            ).casefold()
            static_observed: Any = _response_observation(response)
        except requests.RequestException as exc:
            static_ok = False
            static_observed = type(exc).__name__
            self._note_transport_blocker(exc, "public static probe")
        self.add_check("static_index", "GET / returns HTML with status 200", static_observed, static_ok)

        try:
            response = self._public_request("GET", "/healthz")
            health_ok = response.status_code == 200 and response.text.strip() == "ok"
            health_observed: Any = _response_observation(response)
            health_observed["health_discovery_wait"] = health_discovery_wait
        except requests.RequestException as exc:
            health_ok = False
            health_observed = {
                "request_error": type(exc).__name__,
                "health_discovery_wait": health_discovery_wait,
            }
            self._note_transport_blocker(exc, "public health probe")
        self.add_check("healthz", "GET /healthz returns 200", health_observed, health_ok)

        parsed = urlsplit(self.public_url)
        tls_ok = parsed.scheme == "https"
        tls_observed: Dict[str, Any] = {
            "url_scheme": parsed.scheme,
            "verify": "requests default certificate verification",
            "health_discovery_wait": health_discovery_wait,
        }
        try:
            response = requests.get(self.public_url + "/healthz", timeout=(5, 10))
            tls_ok = tls_ok and response.status_code == 200
            tls_observed["healthz_status"] = response.status_code
        except requests.RequestException as exc:
            tls_ok = False
            tls_observed["request_error"] = type(exc).__name__
            self._note_transport_blocker(exc, "verified HTTPS probe")
        self.add_check("https_scheme", "https URL and verified TLS certificate", tls_observed, tls_ok)

        try:
            local = requests.get("http://127.0.0.1:8370/healthz", timeout=(3, 5))
            local_ok = local.status_code == 200
            local_observed: Any = _response_observation(local)
        except requests.RequestException as exc:
            local_ok = False
            local_observed = type(exc).__name__
        if not any(item["name"] == "fixture_local_healthz" for item in self.checks):
            self.add_check(
                "fixture_local_healthz",
                "loopback fixture health check returns 200",
                local_observed,
                local_ok,
            )

        for name, data in (("login_wrong_rejected", {"password": "incorrect-n0-password"}), ("login_missing_rejected", {})):
            try:
                response = self._public_request("POST", "/login", data=data)
                passed = response.status_code == 401 and "Set-Cookie" not in response.headers
                observed: Any = {
                    "status_code": response.status_code,
                    "set_cookie_present": "Set-Cookie" in response.headers,
                }
            except requests.RequestException as exc:
                passed = False
                observed = type(exc).__name__
                self._note_transport_blocker(exc, name)
            self.add_check(name, "401 without a session cookie", observed, passed)

        try:
            login = self._public_request(
                "POST", "/login", data={"password": self.fixture_password}
            )
            set_cookie = login.headers.get("Set-Cookie", "")
            cookie_pair = set_cookie.split(";", 1)[0]
            cookie_ok = (
                login.status_code == 200
                and "=" in cookie_pair
                and all(
                    part in set_cookie.casefold()
                    for part in ("secure", "httponly", "samesite=strict", "max-age=")
                )
            )
            self.cookie_header = cookie_pair
            if cookie_pair:
                self.sensitive_values.append(cookie_pair.partition("=")[2])
            login_observed: Any = {
                "status_code": login.status_code,
                "secure": "secure" in set_cookie.casefold(),
                "httponly": "httponly" in set_cookie.casefold(),
                "samesite_strict": "samesite=strict" in set_cookie.casefold(),
                "max_age": "max-age=" in set_cookie.casefold(),
                "cookie_value_redacted": True,
            }
        except requests.RequestException as exc:
            cookie_ok = False
            login_observed = {"request_error": type(exc).__name__}
            self._note_transport_blocker(exc, "accepted login probe")
        self.add_check(
            "login_accept_secure_cookie",
            "200 with Secure; HttpOnly; SameSite=Strict; Max-Age session cookie",
            login_observed,
            cookie_ok,
        )

        try:
            response = self._public_request(
                "POST",
                "/login",
                data={"password": self.fixture_password},
                headers={"Origin": "https://evil.example"},
            )
            origin_login_ok = response.status_code == 403 and "Set-Cookie" not in response.headers
            origin_login_observed: Any = {
                "status_code": response.status_code,
                "set_cookie_present": "Set-Cookie" in response.headers,
            }
        except requests.RequestException as exc:
            origin_login_ok = False
            origin_login_observed = {"relay_or_fixture_refusal": type(exc).__name__}
            self._note_transport_blocker(exc, "login Origin probe")
        self.add_check(
            "login_origin_spoof_rejected",
            "spoofed Origin is rejected without setting a cookie",
            origin_login_observed,
            origin_login_ok,
        )

        try:
            response = self._public_request(
                "GET",
                "/healthz",
                headers={
                    "Forwarded": 'for=203.0.113.77;host="evil.example";proto=http',
                    "X-Forwarded-For": "203.0.113.77",
                    "X-Forwarded-Host": "evil.example",
                    "X-Forwarded-Proto": "http",
                },
            )
            forwarded_ok = response.status_code == 200 and response.text.strip() == "ok"
            forwarded_observed: Any = {
                "healthz_status": response.status_code,
                "healthz_marker_present": response.text.strip() == "ok",
            }
        except requests.RequestException as exc:
            forwarded_ok = False
            forwarded_observed = {"healthz_error": type(exc).__name__}
            self._note_transport_blocker(exc, "forwarding headers probe")
        try:
            forwarded_login = self._public_request(
                "POST",
                "/login",
                data={"password": self.fixture_password},
                headers={
                    "Forwarded": 'for=203.0.113.77;host="evil.example";proto=http',
                    "X-Forwarded-Proto": "http",
                    "X-Forwarded-Host": "evil.example",
                },
            )
            forwarded_cookie = forwarded_login.headers.get("Set-Cookie", "")
            forwarded_ok = forwarded_ok and forwarded_login.status_code == 200 and "secure" in forwarded_cookie.casefold()
            forwarded_observed["login_status"] = forwarded_login.status_code
            forwarded_observed["cookie_secure"] = "secure" in forwarded_cookie.casefold()
        except requests.RequestException as exc:
            forwarded_ok = False
            forwarded_observed["login_error"] = type(exc).__name__
            self._note_transport_blocker(exc, "forwarding headers login probe")
        try:
            forwarded_host = self._public_request(
                "GET",
                "/healthz",
                headers={
                    "Host": "evil.example",
                    "Forwarded": 'for=203.0.113.77;host="%s";proto=https' % self.public_host,
                    "X-Forwarded-Host": self.public_host,
                },
            )
            forwarded_host_rejected = 400 <= forwarded_host.status_code < 500
            forwarded_observed["spoof_host_with_forwarded_host_status"] = forwarded_host.status_code
            forwarded_ok = forwarded_ok and forwarded_host_rejected
        except requests.RequestException as exc:
            forwarded_host_rejected = True
            forwarded_observed["spoof_host_with_forwarded_host_error"] = type(exc).__name__
            forwarded_observed["spoof_host_rejection_layer"] = "relay_or_fixture"
            forwarded_ok = forwarded_ok and forwarded_host_rejected
        self.add_check(
            "forwarding_headers_ignored",
            "forwarding headers do not alter Host acceptance or Secure cookie policy",
            forwarded_observed,
            forwarded_ok,
        )

        self._check_host_spoof()

    def _check_host_spoof(self) -> None:
        public_rejected = False
        try:
            response = self._public_request("GET", "/healthz", headers={"Host": "evil.example"})
            public_rejected = 400 <= response.status_code < 500
            public_observed: Any = {"status_code": response.status_code, "layer": "fixture_or_relay"}
        except requests.RequestException as exc:
            public_rejected = True
            public_observed = {"relay_refusal": type(exc).__name__}

        try:
            direct = requests.get(
                "http://127.0.0.1:8370/healthz",
                headers={"Host": "evil.example"},
                timeout=(3, 5),
            )
            direct_rejected = direct.status_code == 421
            direct_observed: Any = {"status_code": direct.status_code}
        except requests.RequestException as exc:
            direct_rejected = True
            direct_observed = {"fixture_refusal": type(exc).__name__}
        self.add_check(
            "host_spoof_rejected",
            "public Host spoof is refused by relay or fixture",
            public_observed,
            public_rejected,
        )
        self.add_check(
            "host_spoof_loopback_rejected",
            "direct loopback Host spoof is refused by fixture",
            direct_observed,
            direct_rejected,
        )

    def _new_socket_client(
        self,
        transport: str,
        *,
        authenticated: bool = True,
        origin: Optional[str] = None,
        reconnection: bool = False,
    ) -> Tuple[socketio.Client, Dict[str, Any], Dict[str, threading.Event]]:
        client = socketio.Client(
            reconnection=reconnection,
            reconnection_attempts=0 if reconnection else 1,
            reconnection_delay=0.5,
            reconnection_delay_max=2,
            request_timeout=SOCKET_TIMEOUT,
            ssl_verify=True,
            logger=False,
            engineio_logger=False,
        )
        events: Dict[str, Any] = {"hello": [], "tick": [], "connect_times": []}
        signals = {"hello": threading.Event(), "tick": threading.Event(), "connect": threading.Event()}

        def on_hello(payload: Any) -> None:
            events["hello"].append(payload)
            signals["hello"].set()

        def on_tick(payload: Any) -> None:
            events["tick"].append(payload)
            signals["tick"].set()

        def on_connect() -> None:
            events["connect_times"].append(time.monotonic())
            signals["connect"].set()

        client.on("hello", on_hello, namespace="/n0")
        client.on("tick", on_tick, namespace="/n0")
        client.on("connect", on_connect, namespace="/n0")
        headers = _headers_from_cookie(self.cookie_header if authenticated else None)
        if origin is not None and transport != "websocket":
            # websocket-client supplies the URL-derived Origin itself. Sending
            # another Origin header there creates duplicates, so spoof Origin
            # is exercised on polling as in the local smoke check.
            headers["Origin"] = origin
        setattr(client, "_n0_headers", headers)
        setattr(client, "_n0_transport", transport)
        self.socket_clients.append(client)
        return client, events, signals

    def _connect_socket(
        self,
        client: socketio.Client,
        *,
        wait_timeout: int = SOCKET_TIMEOUT,
    ) -> Optional[str]:
        headers = getattr(client, "_n0_headers")
        transport = getattr(client, "_n0_transport")
        try:
            client.connect(
                self.public_url,
                headers=headers,
                transports=[transport],
                namespaces=["/n0"],
                wait_timeout=wait_timeout,
            )
            return None
        except Exception as exc:
            return "%s: %s" % (type(exc).__name__, str(exc))

    @staticmethod
    def _disconnect_client(client: socketio.Client) -> None:
        try:
            if client.connected:
                client.disconnect()
        except Exception:
            pass

    def run_socket_checks(self) -> None:
        if not self.public_url or not self.cookie_header:
            return

        unauth, unauth_events, _unauth_signals = self._new_socket_client(
            "polling", authenticated=False
        )
        unauth_error = self._connect_socket(unauth)
        time.sleep(1)
        unauth_ok = unauth_error is not None or not unauth.connected
        unauth_ok = unauth_ok and not unauth_events["hello"] and not unauth_events["tick"]
        self.add_check(
            "unauth_socket_refused",
            "unauthenticated /n0 connection is refused before events",
            {"connection_error": unauth_error or "none", "connected": unauth.connected, "events_received": len(unauth_events["hello"]) + len(unauth_events["tick"])},
            unauth_ok,
            transport="polling",
        )
        self._disconnect_client(unauth)

        spoof, spoof_events, _spoof_signals = self._new_socket_client(
            "polling", authenticated=True, origin="https://evil.example"
        )
        spoof_error = self._connect_socket(spoof)
        spoof_ok = spoof_error is not None or not spoof.connected
        spoof_ok = spoof_ok and not spoof_events["hello"] and not spoof_events["tick"]
        self.add_check(
            "socket_origin_spoof_rejected",
            "authenticated Socket.IO polling handshake with spoof Origin is refused",
            {"connection_error": spoof_error or "none", "connected": spoof.connected, "events_received": len(spoof_events["hello"]) + len(spoof_events["tick"])},
            spoof_ok,
            transport="polling",
        )
        self._disconnect_client(spoof)

        websocket, websocket_events, websocket_signals = self._new_socket_client("websocket")
        websocket_error = self._connect_socket(websocket)
        ws_events_ready = websocket_signals["hello"].wait(8) and websocket_signals["tick"].wait(8)
        ws_transport = websocket.transport() if websocket.connected else "disconnected"
        websocket_ok = websocket_error is None and websocket.connected and ws_events_ready and ws_transport == "websocket"
        self.add_check(
            "websocket_connect",
            "authenticated WebSocket receives hello and tick",
            {"connection_error": websocket_error or "none", "hello_received": bool(websocket_events["hello"]), "tick_received": bool(websocket_events["tick"]), "negotiated_transport": ws_transport},
            websocket_ok,
            transport=ws_transport,
        )

        try:
            echoed = websocket.call("echo", {"probe": "n0-websocket"}, namespace="/n0", timeout=8)
            echo_ok = echoed == {"probe": "n0-websocket"}
            echo_observed: Any = {"round_trip": echo_ok, "response_type": type(echoed).__name__}
        except Exception as exc:
            echo_ok = False
            echo_observed = {"error": "%s: %s" % (type(exc).__name__, str(exc))}
        self.add_check(
            "echo",
            "Socket.IO echo acknowledgment matches the sent payload",
            echo_observed,
            echo_ok,
            transport="websocket",
        )
        self._disconnect_client(websocket)

        polling, polling_events, polling_signals = self._new_socket_client("polling")
        polling_error = self._connect_socket(polling)
        poll_events_ready = polling_signals["hello"].wait(8) and polling_signals["tick"].wait(8)
        poll_transport = polling.transport() if polling.connected else "disconnected"
        polling_ok = polling_error is None and polling.connected and poll_events_ready and poll_transport == "polling"
        self.add_check(
            "polling_connect",
            "authenticated polling-only transport receives hello and tick",
            {"connection_error": polling_error or "none", "hello_received": bool(polling_events["hello"]), "tick_received": bool(polling_events["tick"]), "negotiated_transport": poll_transport},
            polling_ok,
            transport=poll_transport,
        )
        self._disconnect_client(polling)

    def reconnect_check(self) -> None:
        if not self.public_url or not self.cookie_header or self.tunnel_process is None:
            return
        client, events, signals = self._new_socket_client("websocket", reconnection=True)
        initial_error = self._connect_socket(client)
        initial_connected = initial_error is None and client.connected
        if initial_connected:
            signals["hello"].wait(8)
            signals["tick"].wait(8)
        initial_ready = initial_connected and bool(events["hello"]) and bool(events["tick"])
        initial_connect_count = len(events["connect_times"])
        initial_tick_count = len(events["tick"])
        old_url = self.public_url
        stopped_at = time.monotonic()
        deadline = stopped_at + PUBLIC_WAIT_TIMEOUT
        if not self.stop_owned_process(self.tunnel_process):
            self.blockers.append("the foreground OpenTunnel process did not stop before restart")
            self.add_check(
                "reconnect_after_tunnel_restart",
                "foreground tunnel stops before its isolated restart",
                {
                    "process_stopped_before_restart": False,
                    "recovery_wait": self.http_wait_observations.get(
                        "reconnect recovery"
                    ),
                },
                False,
                transport="websocket",
            )
            return
        # A foreground serve restart reuses the existing profile and tunnel ID.
        restarted = self._start_serve()
        restarted_at = time.monotonic()
        with self.output_lock:
            restart_output = "\n".join(self.tunnel_output)
        new_url = extract_public_url(restart_output)
        if not new_url and time.monotonic() < deadline:
            new_url = self._query_status_url()
        remaining = max(0, int(deadline - time.monotonic()))
        recovered = False
        if remaining > 0:
            recovered = self._wait_for_http(
                old_url + "/healthz",
                remaining,
                stage="reconnect recovery",
            )
        recovery_wait = self.http_wait_observations.get("reconnect recovery")
        same_url: Optional[bool] = None
        if new_url:
            same_url = urlsplit(new_url).netloc.casefold() == urlsplit(old_url).netloc.casefold()
        elif recovered:
            # The old URL remains the only URL observed from this profile; do
            # not invent a changed hostname when the CLI omits it on restart.
            same_url = True
        reconnected = False
        tick_after_reconnect = False
        while time.monotonic() < deadline:
            if restarted.poll() is not None:
                break
            if len(events["connect_times"]) > initial_connect_count and client.connected:
                reconnected = True
                tick_after_reconnect = len(events["tick"]) > initial_tick_count
                if tick_after_reconnect:
                    break
            time.sleep(0.25)
        elapsed = time.monotonic() - stopped_at
        passed = initial_ready and recovered and reconnected and tick_after_reconnect and same_url is True
        self.add_check(
            "reconnect_after_tunnel_restart",
            "existing authenticated WebSocket reconnects and receives tick within 90s; public URL is unchanged",
            {
                "initial_connected_and_events": initial_ready,
                "tunnel_restart_elapsed_seconds": round(restarted_at - stopped_at, 3),
                "public_recovery_elapsed_seconds": round(time.monotonic() - restarted_at, 3) if recovered else None,
                "recovery_wait": recovery_wait,
                "client_reconnected": reconnected,
                "tick_after_reconnect": tick_after_reconnect,
                "public_url_stayed_same": same_url,
                "process_alive": restarted.poll() is None,
                "elapsed_seconds": round(elapsed, 3),
            },
            passed,
            transport="websocket",
        )

    def stop_owned_process(self, process: Optional[subprocess.Popen[bytes]]) -> bool:
        if process is None:
            return True
        if process.poll() is not None:
            reader = self.process_readers.get(process.pid)
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=2)
            if process is self.tunnel_process:
                self.tunnel_stopped = True
            if process is self.fixture_process:
                self.fixture_stopped = True
            return True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=PROCESS_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        stopped = process.poll() is not None
        reader = self.process_readers.get(process.pid)
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
        if process is self.tunnel_process:
            self.tunnel_stopped = stopped
        if process is self.fixture_process:
            self.fixture_stopped = stopped
        return stopped

    def cleanup_route(self) -> None:
        if self.profile_config is not None:
            try:
                self.profile_config.unlink(missing_ok=True)
                self.route_removed = True
            except OSError:
                self.route_removed = False
        elif not self.public_url and self.route_creation_path == "not_started":
            self.route_removed = True

    def _wait_threads(self) -> None:
        for thread in self.reader_threads:
            thread.join(timeout=2)

    def finalize_checks(self) -> None:
        # Clients are disconnected only after the reconnection assertion.
        for client in self.socket_clients:
            self._disconnect_client(client)
        for _filename, process in reversed(self.owned_processes):
            try:
                self.stop_owned_process(process)
            except Exception as exc:
                self.blockers.append(
                    "owned process cleanup raised an error (%s)" % type(exc).__name__
                )
        tunnel_processes = [
            process for filename, process in self.owned_processes if filename == "tunnel.log"
        ]
        fixture_processes = [
            process for filename, process in self.owned_processes if filename == "fixture.log"
        ]
        tunnel_stopped = all(process.poll() is not None for process in tunnel_processes)
        fixture_stopped = all(process.poll() is not None for process in fixture_processes)
        try:
            self.cleanup_route()
        except Exception as exc:
            self.route_removed = False
            self.blockers.append("route cleanup raised an error (%s)" % type(exc).__name__)
        try:
            self._delete_identity()
        except Exception as exc:
            self.identity_deleted = False
            self.identity_delete_observation = {
                "attempted": self.identity_up_attempted,
                "passed": False,
                "error": type(exc).__name__,
            }
            self.blockers.append("OpenTunnel tunnel identity deletion raised an error")
            self.log("OpenTunnel identity deletion failed: " + type(exc).__name__)
        self._wait_threads()

        if self.public_url:
            try:
                response = requests.get(self.public_url + "/healthz", timeout=(5, 8))
                public_unreachable = not (
                    response.status_code == 200 and response.text.strip() == "ok"
                )
                public_observed: Any = {
                    "status_code": response.status_code,
                    "fixture_health_marker_present": response.status_code == 200
                    and response.text.strip() == "ok",
                }
            except requests.RequestException as exc:
                public_unreachable = True
                public_observed = {"unreachable_error": type(exc).__name__}
        else:
            tunnel_was_started = any(
                filename == "tunnel.log" for filename, _process in self.owned_processes
            )
            public_unreachable = _absence_proven_without_url(
                self.public_url,
                tunnel_was_started,
                self.route_creation_path,
                identity_deleted=self.identity_deleted,
            )
            public_observed = {
                "no_route_was_started": public_unreachable,
                "tunnel_process_was_started": tunnel_was_started,
                "route_creation_path": self.route_creation_path,
            }
        port_free = _is_port_free("127.0.0.1", 8370)
        tracked_alive = [
            process.pid for _filename, process in self.owned_processes
            if process.poll() is None
        ]
        identity_pids_alive = {
            str(pid): self._pid_is_alive(pid) for pid in self.identity_daemon_pids
        }
        tracked_alive.extend(
            pid for pid in self.identity_daemon_pids
            if identity_pids_alive[str(pid)] and pid not in tracked_alive
        )
        clean = (
            public_unreachable
            and tunnel_stopped
            and fixture_stopped
            and not tracked_alive
            and port_free
            and self.route_removed
            and self.identity_deleted
        )
        self.add_check(
            "clean_shutdown",
            "route removed; identity deleted; public URL no longer serves fixture; owned PIDs stopped; port 8370 free",
            {
                "public_url_unreachable": public_unreachable,
                "public_probe": public_observed,
                "tunnel_stopped": tunnel_stopped,
                "fixture_stopped": fixture_stopped,
                "tracked_pids_alive": tracked_alive,
                "identity_daemon_pid_liveness": identity_pids_alive,
                "port_8370_free": port_free,
                "route_removed": self.route_removed,
                "identity_deleted": self.identity_deleted,
                "identity_delete_observation": self.identity_delete_observation,
            },
            clean,
        )

        services_after = _service_snapshot(self.selected_platform)
        services_after["isolated_service_files_after"] = self._isolated_service_files()
        new_service_entries = self._new_service_entries(self.services_before, services_after)
        post_processes = _open_tunnel_process_snapshot()
        new_processes = {
            pid: command for pid, command in post_processes.items()
            if pid not in self.processes_before
        }
        service_assessment = _service_registration_assessment(
            self.services_before,
            services_after,
            new_service_entries,
            new_processes,
            tracked_alive,
            self.identity_minting_observation,
        )
        no_service = service_assessment["passed"]
        self.add_check(
            "no_service_registration",
            "service registration is absent under observed, sandbox-denied, or no-service-manager evidence",
            {
                "before": self.services_before,
                "after": services_after,
                "new_service_entries": new_service_entries,
                "new_process_ids": sorted(new_processes),
                "preexisting_process_ids": sorted(self.processes_before),
                "tracked_pids_alive": tracked_alive,
                "identity_minting": self.identity_minting_observation,
                **service_assessment,
            },
            no_service,
        )

        environment_observation = self._environment_isolation_observation()
        self.add_check(
            "isolated_child_environment",
            "child process environment uses an allowlist and project-local HOME/XDG/temp paths",
            environment_observation,
            environment_observation["passed"],
        )
        self.add_check(
            "cleanup_execution",
            "finalize_checks completes without raising",
            {"exception": None, "tracked_pids_alive": tracked_alive},
            True,
        )

        existing = {item.get("name") for item in self.checks}
        skip_reason = self.blockers[-1] if self.blockers else "check was not reached before driver stopped"
        for name in REQUIRED_CHECKS:
            if name not in existing:
                self.add_check(name, "required check executes and passes", {"not_run": skip_reason}, False)

    @staticmethod
    def _new_service_entries(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, List[str]]:
        differences: Dict[str, List[str]] = {}
        for key in ("launch_agents", "systemd_units", "unit_files"):
            old = set(before.get(key, []))
            new = set(after.get(key, []))
            difference = sorted(new - old)
            if difference:
                differences[key] = difference
        isolated_before = before.get("isolated_service_files_before", {})
        isolated_after = after.get("isolated_service_files_after", {})
        for key in ("launch_agents", "systemd_units"):
            old = set(isolated_before.get(key, []))
            new = set(isolated_after.get(key, []))
            difference = sorted(new - old)
            if difference:
                differences["isolated_" + key] = difference
        return differences

    def write_environment(self) -> None:
        versions = _available_package_versions()
        build_sha, build_identity_source, worktree_dirty = _resolved_build_identity()
        def relative_path(path: Path) -> str:
            try:
                return path.resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                return "outside-project"

        data = {
            "platform": self.selected_platform,
            "system": self.system,
            "arch": self.machine,
            "os_version": _normal_os_version(),
            "python": sys.version.split()[0],
            "package_versions": versions,
            "build_sha": build_sha,
            "build_identity_source": build_identity_source,
            "worktree_dirty": worktree_dirty,
            "runtime_dir_basis": self.runtime_dir_basis,
            "opentunnel_version": self.asset_info["version"],
            "opentunnel_asset": self.asset_name or None,
            "opentunnel_digest": self.asset_info["digest"],
            "opentunnel_digest_expected": self.expected_digest or None,
            "isolated_xdg": {key: relative_path(value) for key, value in self.xdg.items()},
            "runtime_dir": relative_path(self.runtime_dir) if self.runtime_dir else None,
            "child_environment": self._environment_isolation_observation(),
        }
        (self.run_dir / "env.json").write_text(
            json.dumps(redact_value(data, self.sensitive_values), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_evidence(self) -> Dict[str, Any]:
        build_sha, build_identity_source, worktree_dirty = _resolved_build_identity()
        evidence = build_evidence(
            run_id=self.run_id,
            selected_platform=self.selected_platform,
            arch=self.arch,
            os_version=_normal_os_version(),
            python_version=sys.version.split()[0],
            package_versions=_available_package_versions(),
            build_sha=build_sha,
            build_identity_source=build_identity_source,
            worktree_dirty=worktree_dirty,
            runtime_dir_basis=self.runtime_dir_basis,
            opentunnel=self.asset_info,
            route_creation_path=self.route_creation_path,
            public_url_redacted="https://<route>" if self.public_url else "not_discovered",
            checks=self.checks,
            started_at=self.started_at,
            finished_at=self.finished_at or utc_now(),
            blockers=self.blockers,
        )
        evidence = redact_value(evidence, self.sensitive_values)
        (self.run_dir / "evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return evidence

    def _record_finalize_failure(self, exc: BaseException) -> None:
        """Force cleanup evidence to FAIL and retain final status for owned PIDs."""
        try:
            exception_message = str(exc)
        except Exception:
            exception_message = "<exception message unavailable>"
        exception_message = redact_text(
            exception_message, self.sensitive_values
        )[:MAX_LOG_ENTRY_CHARS]
        tracked_processes: List[Dict[str, Any]] = []
        tracked_alive: List[int] = []
        for filename, process in self.owned_processes:
            try:
                alive: Optional[bool] = process.poll() is None
                if alive:
                    tracked_alive.append(process.pid)
                status_error = None
            except Exception as status_exc:
                alive = None
                status_error = type(status_exc).__name__
            tracked_processes.append(
                {
                    "kind": filename.removesuffix(".log"),
                    "pid": process.pid,
                    "alive": alive,
                    "status_error": status_error,
                }
            )
        identity_pid_liveness = {
            str(pid): self._pid_is_alive(pid) for pid in self.identity_daemon_pids
        }
        for pid in self.identity_daemon_pids:
            if identity_pid_liveness[str(pid)] and pid not in tracked_alive:
                tracked_alive.append(pid)

        observed = {
            "cleanup_exception": type(exc).__name__,
            "cleanup_exception_message": exception_message,
            "tracked_pids_alive": tracked_alive,
            "tracked_processes": tracked_processes,
            "identity_daemon_pid_liveness": identity_pid_liveness,
            "identity_deleted": self.identity_deleted,
            "identity_delete_observation": self.identity_delete_observation,
        }
        for name in ("clean_shutdown", "no_service_registration", "cleanup_execution"):
            matching = [item for item in self.checks if item.get("name") == name]
            if not matching:
                self.checks.append(
                    check_record(
                        name,
                        "cleanup completed without an exception",
                        observed,
                        False,
                        secrets_to_scrub=self.sensitive_values,
                    )
                )
                continue
            for item in matching:
                item["status"] = "FAIL"
                item["observed"] = redact_value(
                    {"previous_observed": item.get("observed"), **observed},
                    self.sensitive_values,
                )

    def execute(self) -> int:
        if self.run_dir.exists() or self.download_dir.exists():
            print(
                "[FAIL] run-id already has evidence or downloaded assets; choose a new --run-id",
                file=sys.stderr,
            )
            return 2
        try:
            self.prepare_isolation()
            self.write_environment()
            if self.download_and_verify() and self.activate_tunnel():
                if self.public_url and self.start_fixture():
                    self._wait_for_http(
                        self.public_url + "/healthz",
                        timeout=30,
                        stage="public health discovery",
                    )
                    self.run_http_checks()
                    self.run_socket_checks()
                    self.reconnect_check()
        except KeyboardInterrupt:
            self.blockers.append("driver interrupted; owned processes were stopped")
            self.log("driver interrupted")
        except Exception as exc:
            self.log("driver error: %s: %s" % (type(exc).__name__, str(exc)))
        finally:
            try:
                self.finalize_checks()
            except Exception as exc:
                self._record_finalize_failure(exc)
                try:
                    self.log("cleanup checks raised: %s" % type(exc).__name__)
                except OSError:
                    pass
            self.finished_at = utc_now()
            write_failed = False
            evidence: Dict[str, Any] = {}
            try:
                self.write_environment()
                evidence = self._write_evidence()
            except Exception as exc:
                self.log("evidence write failed: %s" % type(exc).__name__)
                write_failed = True
            finally:
                self._remove_runtime_dir()
            if write_failed:
                return 1
        passed = all(
            next((item.get("status") for item in self.checks if item.get("name") == name), None)
            == "PASS"
            for name in REQUIRED_CHECKS
        ) and not self.blockers
        print("[PASS] evidence written: %s" % self.run_dir.relative_to(REPO_ROOT)) if passed else print(
            "[FAIL] evidence written: %s (%s)" % (
                self.run_dir.relative_to(REPO_ROOT), evidence["verdict_hint"]
            )
        )
        return 0 if passed else 1

    def _remove_runtime_dir(self) -> None:
        self._preserve_daemon_logs()
        if self.runtime_dir is not None:
            try:
                shutil.rmtree(self.runtime_dir)
            except OSError:
                self.log("could not remove the isolated runtime directory")
        if self.xdg:
            try:
                shutil.rmtree(self.xdg["state"] / "opentunnel")
            except FileNotFoundError:
                pass
            except OSError:
                self.log("could not remove isolated OpenTunnel state logs")
        if not self.keep_identity and self.xdg:
            profile_data = self.xdg["data"] / "opentunnel" / self.profile
            try:
                shutil.rmtree(profile_data)
            except FileNotFoundError:
                pass
            except OSError:
                self.log("could not remove isolated tunnel identity files")


def _self_test_impl(scratch_root: Path) -> int:
    """Run offline driver checks with all test artifacts under one scratch root."""
    outcomes: List[Tuple[str, bool]] = []

    def test_run(selected_platform: str, run_id: str) -> "N0Run":
        run = N0Run(selected_platform, run_id, keep_identity=False)
        run.run_dir = scratch_root / ("n0-" + selected_platform + "-" + run_id)
        run.download_dir = scratch_root / "downloads" / run_id
        return run

    route_host = "route123.tunnel456.opentunnel.xyz"
    password = "n0-very-secret-password"
    cookie = "n0_session=eyJzZXNzaW9uIjoxMjM456.abcdef0123456789ABCDEF"
    sample = (
        "https://" + route_host + "/login Set-Cookie: " + cookie
        + "; Secure; HttpOnly password=" + password
    )
    redacted = redact_text(sample, [password, route_host, cookie.partition("=")[2]])
    redaction_ok = (
        route_host not in redacted
        and password not in redacted
        and cookie.partition("=")[2] not in redacted
        and "<route>" in redacted
        and "<redacted>" in redacted
    )
    outcomes.append(("redaction", redaction_ok))

    proc_root = scratch_root / "proc-fixture"
    (proc_root / "123").mkdir(mode=0o700, parents=True)
    (proc_root / "123/comm").write_text("opentunnel\n", encoding="ascii")
    (proc_root / "456").mkdir(mode=0o700)
    (proc_root / "456/comm").write_text("python3\n", encoding="ascii")
    (proc_root / "self").mkdir(mode=0o700)
    (proc_root / "self/comm").write_text("opentunnel\n", encoding="ascii")
    with (
        mock.patch.object(platform_module, "system", return_value="Linux"),
        mock.patch.object(subprocess, "run", side_effect=FileNotFoundError()),
    ):
        proc_snapshot = _open_tunnel_process_snapshot(proc_root)
    outcomes.append(("linux_proc_process_snapshot_fallback", proc_snapshot == {123: "opentunnel"}))

    valid_host_sha = "a" * 40
    host_identity_file = scratch_root / "build-identity-valid.txt"
    host_identity_file.write_text(
        "sha=" + valid_host_sha + "\ndirty=1\n", encoding="ascii"
    )
    clean_host_identity_file = scratch_root / "build-identity-clean.txt"
    clean_host_identity_file.write_text(
        "sha=" + "c" * 64 + "\ndirty=0\n", encoding="ascii"
    )
    unknown_key_identity_file = scratch_root / "build-identity-unknown-key.txt"
    unknown_key_identity_file.write_text(
        "sha=" + valid_host_sha + "\nclean=1\n", encoding="ascii"
    )
    invalid_value_identity_file = scratch_root / "build-identity-invalid-value.txt"
    invalid_value_identity_file.write_text(
        "sha=" + valid_host_sha + "\ndirty=true\n", encoding="ascii"
    )
    invalid_sha_identity_file = scratch_root / "build-identity-invalid-sha.txt"
    invalid_sha_identity_file.write_text(
        "sha=" + "not-a-git-sha" + "\ndirty=0\n", encoding="ascii"
    )
    with mock.patch.object(sys.modules[__name__], "_run_git_value", return_value="unknown"):
        host_identity = _resolved_build_identity(host_identity_file)
        clean_host_identity = _resolved_build_identity(clean_host_identity_file)
        unknown_key_identity = _resolved_build_identity(unknown_key_identity_file)
        invalid_value_identity = _resolved_build_identity(invalid_value_identity_file)
        invalid_sha_identity = _resolved_build_identity(invalid_sha_identity_file)
    host_identity_validation_ok = (
        host_identity == (valid_host_sha, "host_file", True)
        and clean_host_identity == ("c" * 64, "host_file", False)
        and unknown_key_identity == ("unknown", "unknown", None)
        and invalid_value_identity == ("unknown", "unknown", None)
        and invalid_sha_identity == ("unknown", "unknown", None)
    )
    outcomes.append(
        ("strict_host_build_identity_sha_and_dirty_parsing", host_identity_validation_ok)
    )

    git_sha = "b" * 40
    with mock.patch.object(
        sys.modules[__name__],
        "_run_git_value",
        side_effect=[git_sha, ""],
    ):
        git_identity = _resolved_build_identity(host_identity_file)
    git_identity_preferred = git_identity == (git_sha, "git", False)
    outcomes.append(("git_build_identity_preferred_over_host_file", git_identity_preferred))

    runtime_validation_root = scratch_root / "runtime-parent-validation"
    runtime_validation_root.mkdir(mode=0o700)
    validation_repo_root = runtime_validation_root / "repo-root"
    validation_repo_root.mkdir(mode=0o700)
    valid_runtime_parent = runtime_validation_root / "valid-parent"
    valid_runtime_parent.mkdir(mode=0o700)
    os.chmod(valid_runtime_parent, 0o700)
    symlink_runtime_parent = runtime_validation_root / "symlink-parent"
    symlink_runtime_parent.symlink_to(valid_runtime_parent, target_is_directory=True)
    wrong_mode_runtime_parent = runtime_validation_root / "wrong-mode-parent"
    wrong_mode_runtime_parent.mkdir(mode=0o700)
    os.chmod(
        wrong_mode_runtime_parent,
        stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP,
    )
    missing_runtime_parent = runtime_validation_root / "missing-parent"
    inside_repo_runtime_parent = validation_repo_root / "runtime-parent"
    inside_repo_runtime_parent.mkdir(mode=0o700)
    os.chmod(inside_repo_runtime_parent, 0o700)

    def _runtime_parent_rejected(candidate: Path) -> bool:
        try:
            _validate_runtime_parent(candidate)
        except ValueError:
            return True
        return False

    with mock.patch.object(sys.modules[__name__], "REPO_ROOT", validation_repo_root):
        with mock.patch.object(os, "getuid", return_value=os.getuid() + 1):
            owner_mismatch_rejected = _runtime_parent_rejected(valid_runtime_parent)
        runtime_parent_validation_ok = (
            _validate_runtime_parent(valid_runtime_parent) == valid_runtime_parent
            and owner_mismatch_rejected
            and _runtime_parent_rejected(Path("relative-runtime-parent"))
            and _runtime_parent_rejected(symlink_runtime_parent)
            and _runtime_parent_rejected(wrong_mode_runtime_parent)
            and _runtime_parent_rejected(missing_runtime_parent)
            and _runtime_parent_rejected(inside_repo_runtime_parent)
        )
    outcomes.append(("runtime_parent_override_validation", runtime_parent_validation_ok))

    runtime_probe_dir = scratch_root / "r-ok"
    runtime_probe_dir.mkdir(mode=0o700)
    os.chmod(runtime_probe_dir, 0o700)
    runtime_probe_run = test_run("linux", "self-test-runtime-probe-success")
    runtime_probe_run.run_dir = scratch_root / "runtime-probe-success-run"
    runtime_probe_run.run_dir.mkdir(mode=0o700)
    runtime_probe_run.runtime_dir = runtime_probe_dir
    runtime_probe_success = runtime_probe_run._probe_runtime_dir()
    runtime_probe_success_ok = (
        runtime_probe_success["passed"] is True
        and runtime_probe_success["errno_name"] is None
        and not (runtime_probe_dir / ".n0-runtime-probe.lock").exists()
        and not (runtime_probe_dir / "p.sock").exists()
    )
    outcomes.append(("runtime_dir_flock_and_af_unix_probe_succeeds", runtime_probe_success_ok))

    runtime_probe_failure_dir = scratch_root / "r-fail"
    runtime_probe_failure_dir.mkdir(mode=0o700)
    os.chmod(runtime_probe_failure_dir, 0o700)
    runtime_probe_failure_run = test_run("linux", "self-test-runtime-probe-failure")
    runtime_probe_failure_run.run_dir = scratch_root / "runtime-probe-failure-run"
    runtime_probe_failure_run.run_dir.mkdir(mode=0o700)
    runtime_probe_failure_run.runtime_dir = runtime_probe_failure_dir
    runtime_probe_failure_run.binary = Path("/synthetic/opentunnel")
    runtime_probe_failure_run._identity_path_preflight = lambda: {"status": "READY"}  # type: ignore[method-assign]
    runtime_probe_cli_runner = mock.Mock(return_value={})
    runtime_probe_failure_run._run_identity_cli = runtime_probe_cli_runner  # type: ignore[method-assign]
    runtime_probe_relay_runner = mock.Mock()
    runtime_probe_failure_run._start_serve = runtime_probe_relay_runner  # type: ignore[method-assign]
    with mock.patch.object(
        fcntl, "flock", side_effect=OSError(errno.ENOTSUP, "synthetic flock denial")
    ):
        runtime_probe_blocked = not runtime_probe_failure_run.activate_tunnel()
    runtime_probe_failure_check = next(
        item for item in runtime_probe_failure_run.checks
        if item["name"] == "runtime_dir_probe"
    )
    runtime_probe_failure_evidence = build_evidence(
        run_id="self-test-runtime-probe-failure",
        selected_platform="linux",
        arch="test-arch",
        os_version="test-os",
        python_version="3.test",
        package_versions={},
        build_sha="test-sha",
        build_identity_source="unknown",
        worktree_dirty=None,
        runtime_dir_basis="override_tmpfs",
        opentunnel={},
        route_creation_path=runtime_probe_failure_run.route_creation_path,
        public_url_redacted="not_discovered",
        checks=runtime_probe_failure_run.checks,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        blockers=runtime_probe_failure_run.blockers,
    )
    runtime_probe_failure_ok = (
        runtime_probe_blocked
        and runtime_probe_failure_run.identity_minting_observation["status"] == "BLOCKED"
        and runtime_probe_failure_run.identity_minting_observation["up_invoked"] is False
        and runtime_probe_failure_run.route_creation_path == "up_blocked"
        and "runtime dir does not support AF_UNIX/flock (ENOTSUP)"
        in runtime_probe_failure_run.blockers
        and runtime_probe_failure_check["status"] == "FAIL"
        and runtime_probe_failure_check["observed"]["errno_name"] == "ENOTSUP"
        and runtime_probe_failure_evidence["verdict_hint"] == "BLOCKED"
        and not runtime_probe_failure_run.identity_up_attempted
        and runtime_probe_cli_runner.call_count == 0
        and runtime_probe_relay_runner.call_count == 0
    )
    outcomes.append(("runtime_probe_failure_blocks_up_before_cli", runtime_probe_failure_ok))

    url_validation_cases = {
        "userinfo": "https://user@route123.opentunnel.xyz",
        "evil_suffix": "https://route123.opentunnel.xyz.evil.example",
        "query": "https://route123.opentunnel.xyz?next=evil.example",
        "fragment": "https://route123.opentunnel.xyz#fragment",
        "path": "https://route123.opentunnel.xyz/healthz",
    }
    for name, candidate in url_validation_cases.items():
        outcomes.append(("url_rejects_" + name, extract_public_url(candidate) is None))
    canonical_url = extract_public_url("route: https://route123.opentunnel.xyz:443/")
    outcomes.append(
        ("url_accepts_canonical_https", canonical_url == "https://route123.opentunnel.xyz")
    )
    parser_sample_ok = extract_public_url(
        "https://route123.opentunnel.xyz " + "x" * (MAX_URL_PARSE_CHARS + 1)
    ) is None
    outcomes.append(("url_parser_sample_bounded", parser_sample_ok))

    status_route_name = "n0-status-test"
    status_hostname = "status-host.opentunnel.xyz"
    status_route_host = status_route_name + "." + status_hostname
    connected_status = (
        "Profile: n0-status-test\n"
        "Tunnel ID: tunnel-id-self-test\n"
        "Hostname: status-host.opentunnel.xyz\n"
        "Certificate expiry: 2027-02-03T23:59:59.000Z\n"
        "\n"
        + status_route_host
        + "  \u2192  127.0.0.1:8370\n"
        + "Service: connected, 0 active connection(s) (pid 61281, profile n0-status-test)\n"
        + "Log: /isolated/path\n"
    )
    connected_status_result = _parse_serve_status(connected_status, status_route_name)
    status_parser_connected_ok = (
        connected_status_result["url"] == "https://" + status_route_host
        and connected_status_result["service_connected"]
        and connected_status_result["route_matches"]
    )
    ascii_arrow_result = _parse_serve_status(
        connected_status.replace("\u2192", "->"), status_route_name
    )
    status_parser_ascii_arrow_ok = (
        ascii_arrow_result["url"] == "https://" + status_route_host
    )
    waiting_status = connected_status.replace(
        "Service: connected, 0 active connection(s) (pid 61281, profile n0-status-test)",
        "Service: waiting for routes",
    )
    status_parser_waiting_ok = _parse_serve_status(
        waiting_status, status_route_name
    )["url"] is None
    mismatched_target_status = connected_status.replace(
        "127.0.0.1:8370", "127.0.0.1:8371"
    )
    mismatched_target_result = _parse_serve_status(
        mismatched_target_status, status_route_name
    )
    # The route host itself is valid in this case; only the target port differs.
    status_parser_target_mismatch_ok = (
        mismatched_target_result["url"] is None
        and mismatched_target_result["route_mismatch"]
        == "observed expected route host -> 127.0.0.1:8371; expected route-name.hostname -> 127.0.0.1:8370"
    )
    bare_route_status = connected_status.replace(
        status_route_host, status_route_name
    )
    bare_route_result = _parse_serve_status(bare_route_status, status_route_name)
    status_parser_bare_route_ok = (
        bare_route_result["url"] is None
        and bare_route_result["route_mismatch"]
        == "observed bare route name -> 127.0.0.1:8370; expected route-name.hostname -> 127.0.0.1:8370"
    )
    printed_status_result = _parse_serve_status(
        "Public URL: https://printed-host.opentunnel.xyz\nService: waiting for routes\n",
        status_route_name,
    )
    status_parser_printed_url_ok = (
        printed_status_result["url"] == "https://printed-host.opentunnel.xyz"
    )
    outcomes.append(("status_parser_connected_route_to_url", status_parser_connected_ok))
    outcomes.append(("status_parser_accepts_ascii_arrow", status_parser_ascii_arrow_ok))
    outcomes.append(("status_parser_waiting_for_routes_not_ready", status_parser_waiting_ok))
    outcomes.append(("status_parser_rejects_mismatched_target_port", status_parser_target_mismatch_ok))
    outcomes.append(("status_parser_rejects_bare_route_host", status_parser_bare_route_ok))
    outcomes.append(("status_parser_accepts_printed_https_url", status_parser_printed_url_ok))

    class _SelfTestRunningProcess:
        def poll(self) -> None:
            return None

    status_poll_run = test_run("macos", "self-test-status-poll")
    status_poll_time = [100.0]
    status_poll_responses = iter(
        [
            {
                "url": None,
                "route_matches": False,
                "route_mismatch": None,
            },
            connected_status_result,
        ]
    )

    def _status_poll_clock() -> float:
        return status_poll_time[0]

    def _status_poll_sleep(seconds: float) -> None:
        status_poll_time[0] += seconds

    with (
        mock.patch.object(time, "monotonic", side_effect=_status_poll_clock),
        mock.patch.object(time, "sleep", side_effect=_status_poll_sleep),
        mock.patch.object(
            status_poll_run,
            "_query_status_observation",
            side_effect=lambda timeout: next(status_poll_responses),
        ) as status_queries,
    ):
        status_poll_url = status_poll_run._discover_from_serve(
            _SelfTestRunningProcess(), timeout=6
        )
    outcomes.append(
        (
            "serve_discovery_polls_status_until_connected",
            status_poll_url == "https://" + status_route_host
            and status_queries.call_count == 2,
        )
    )
    mismatch_discovery_run = test_run("macos", "self-test-status-route-mismatch")
    mismatch_poll_time = [200.0]
    with (
        mock.patch.object(
            time, "monotonic", side_effect=lambda: mismatch_poll_time[0]
        ),
        mock.patch.object(
            time,
            "sleep",
            side_effect=lambda seconds: mismatch_poll_time.__setitem__(
                0, mismatch_poll_time[0] + seconds
            ),
        ),
        mock.patch.object(
            mismatch_discovery_run,
            "_query_status_observation",
            return_value=bare_route_result,
        ),
    ):
        mismatch_discovery_url = mismatch_discovery_run._discover_from_serve(
            _SelfTestRunningProcess(), timeout=1
        )
    outcomes.append(
        (
            "serve_discovery_records_route_shape_blocker",
            mismatch_discovery_url is None
            and any(
                "observed bare route name -> 127.0.0.1:8370" in blocker
                for blocker in mismatch_discovery_run.blockers
            ),
        )
    )

    def _run_stubbed_http_wait(
        run: "N0Run", stage: str, timeout: int, request_side_effect: Any
    ) -> Tuple[bool, mock.Mock]:
        clock = [0.0]

        def _advance_time(seconds: float) -> None:
            clock[0] += seconds

        with (
            mock.patch.object(time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(time, "sleep", side_effect=_advance_time),
            mock.patch.object(
                requests, "get", side_effect=request_side_effect
            ) as stubbed_get,
        ):
            ready = run._wait_for_http(
                "https://wait-test.opentunnel.xyz/healthz",
                timeout=timeout,
                stage=stage,
            )
        return ready, stubbed_get

    transient_wait_run = test_run("macos", "self-test-http-transient")
    transient_wait_responses = [
        mock.Mock(status_code=525, text="certificate not ready"),
        mock.Mock(status_code=200, text="ok"),
    ]
    transient_wait_ready, transient_wait_calls = _run_stubbed_http_wait(
        transient_wait_run,
        "public health discovery",
        5,
        transient_wait_responses,
    )
    transient_wait_observation = transient_wait_run.http_wait_observations[
        "public health discovery"
    ]
    transient_wait_ok = (
        transient_wait_ready
        and not transient_wait_run.blockers
        and transient_wait_calls.call_count == 2
        and transient_wait_observation["ready"]
        and transient_wait_observation["transient_failure_count"] == 1
        and len(transient_wait_observation["last_transient_failures"]) == 1
    )
    outcomes.append(("wait_transient_525_then_200_no_blocker", transient_wait_ok))

    persistent_wait_run = test_run("macos", "self-test-http-persistent")
    persistent_wait_secret = "transient-error-secret"
    persistent_wait_run.sensitive_values.append(persistent_wait_secret)
    persistent_wait_response = mock.Mock(
        status_code=525,
        text="certificate not ready " + persistent_wait_secret,
    )
    persistent_wait_ready, persistent_wait_calls = _run_stubbed_http_wait(
        persistent_wait_run,
        "public health discovery",
        5,
        lambda *_args, **_kwargs: persistent_wait_response,
    )
    persistent_wait_observation = persistent_wait_run.http_wait_observations[
        "public health discovery"
    ]
    persistent_wait_ok = (
        not persistent_wait_ready
        and persistent_wait_calls.call_count == 5
        and persistent_wait_observation["transient_failure_count"] == 5
        and len(persistent_wait_observation["last_transient_failures"]) == 3
        and all(
            len(message) <= MAX_HTTP_WAIT_MESSAGE_CHARS
            and persistent_wait_secret not in message
            for message in persistent_wait_observation["last_transient_failures"]
        )
        and persistent_wait_run.blockers
        == ["OpenTunnel relay/certificate refusal during public health discovery"]
    )
    outcomes.append(("wait_persistent_525_stage_blocker", persistent_wait_ok))

    local_wait_run = test_run("macos", "self-test-http-local")
    local_wait_responses = [
        requests.ConnectionError("connection refused while fixture starts"),
        mock.Mock(status_code=200, text="ok"),
    ]
    local_wait_ready, local_wait_calls = _run_stubbed_http_wait(
        local_wait_run,
        "local fixture health",
        5,
        local_wait_responses,
    )
    local_wait_observation = local_wait_run.http_wait_observations[
        "local fixture health"
    ]
    local_wait_ok = (
        local_wait_ready
        and local_wait_calls.call_count == 2
        and local_wait_observation["transient_failure_count"] == 1
        and not local_wait_run.blockers
    )
    outcomes.append(("wait_local_connection_refused_then_ok_no_blocker", local_wait_ok))

    expected_profile = "n0-20261105t040912z"
    profile_normalization_ok = (
        _profile_name_from_run_id("20261105T040912Z") == expected_profile
        and test_run("macos", "20261105T040912Z").route_name
        == expected_profile
    )
    outcomes.append(("profile_name_normalizes_run_id", profile_normalization_ok))
    try:
        _profile_name_from_run_id("20261105_bad")
        profile_rejection_ok = False
    except ValueError:
        profile_rejection_ok = True
    outcomes.append(("profile_name_rejects_invalid_slug", profile_rejection_ok))

    stable_path_first_run = test_run("macos", "stable-path-first")
    stable_path_second_run = test_run("macos", "stable-path-second")
    stable_binary_path_ok = bool(
        stable_path_first_run.stable_binary_path is not None
        and stable_path_first_run.stable_binary_path == stable_path_second_run.stable_binary_path
        and stable_path_first_run.run_id not in str(stable_path_first_run.stable_binary_path)
        and stable_path_second_run.run_id not in str(stable_path_second_run.stable_binary_path)
        and ("/" + RELEASE_VERSION + "/")
        in stable_path_first_run.stable_binary_path.as_posix()
    )
    outcomes.append(("stable_binary_path_is_versioned_and_run_id_independent", stable_binary_path_ok))

    connect_test_path = _stable_binary_path("opentunnel-darwin-arm64.tar.gz")
    connect_failure_reason = _outbound_connect_failure_reason(connect_test_path)
    connect_evidence = build_evidence(
        run_id="self-test-connect-failure",
        selected_platform="macos",
        arch="arm64",
        os_version="test-os",
        python_version="3.test",
        package_versions={},
        build_sha="test-sha",
        build_identity_source="unknown",
        worktree_dirty=False,
        runtime_dir_basis="project_tmp",
        opentunnel={"binary_path": _relative_project_path(connect_test_path)},
        route_creation_path="up_mint_failed",
        public_url_redacted="not_discovered",
        checks=[],
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        blockers=[connect_failure_reason],
    )
    connect_failure_classification_ok = (
        _is_outbound_connect_failure("tcp connect error: EBADF")
        and _is_outbound_connect_failure("ERROR SENDING REQUEST")
        and _is_outbound_connect_failure("DNS error")
        and "outbound connection from the OpenTunnel binary was blocked or failed"
        in connect_failure_reason
        and "possible per-application firewall such as LuLu" in connect_failure_reason
        and "stable binary path: " + _relative_project_path(connect_test_path)
        in connect_failure_reason
        and connect_evidence["verdict_hint"] == "BLOCKED"
    )
    outcomes.append(("connect_failure_has_specific_stable_path_blocker", connect_failure_classification_ok))

    denied_status = _parse_nono_why_output(
        '{"status":"denied","reason":"path_not_granted"}'
    )
    not_sandboxed_status = _parse_nono_why_output(
        '{"status":"not_sandboxed","reason":"no_capability_context"}'
    )
    uppercase_denied_status = _parse_nono_why_output(
        '{"status":"DENIED","reason":"path_not_granted"}'
    )
    outcomes.append(
        (
            "nono_lowercase_denied_proves_sandbox_denial",
            _nono_status_proves_write_denial(denied_status["status"]),
        )
    )
    outcomes.append(
        (
            "nono_not_sandboxed_does_not_prove_denial",
            not _nono_status_proves_write_denial(not_sandboxed_status["status"]),
        )
    )
    outcomes.append(
        (
            "nono_uppercase_denied_proves_sandbox_denial",
            _nono_status_proves_write_denial(uppercase_denied_status["status"]),
        )
    )

    empty_isolated_before = {
        "launch_agents": [],
        "systemd_units": [],
    }
    empty_isolated_after = {
        "launch_agents": [],
        "systemd_units": [],
    }
    observed_service_before = {
        "real_user_view": "observed",
        "source": "ls_launch_agents",
        "launch_agents": [],
        "isolated_service_files_before": empty_isolated_before,
    }
    observed_service_after = {
        "real_user_view": "observed",
        "source": "launchctl_list",
        "launch_agents": [],
        "isolated_service_files_after": empty_isolated_after,
    }
    observed_new_entries = N0Run._new_service_entries(
        observed_service_before, observed_service_after
    )
    observed_assessment = _service_registration_assessment(
        observed_service_before,
        observed_service_after,
        observed_new_entries,
        {},
        [],
        {"passed": True},
    )
    outcomes.append(
        (
            "service_registration_observed_clean_pass",
            observed_assessment["passed"]
            and observed_assessment["service_registration_basis"] == "observed_user_view",
        )
    )

    denied_service_before = {
        "real_user_view": "unobservable",
        "sandbox_write_denial": {"status": "DENIED", "reason": "path_not_granted"},
        "isolated_service_files_before": empty_isolated_before,
    }
    denied_service_after = {
        "real_user_view": "unobservable",
        "sandbox_write_denial": {"status": "DENIED", "reason": "path_not_granted"},
        "isolated_service_files_after": empty_isolated_after,
    }
    denied_new_entries = N0Run._new_service_entries(
        denied_service_before, denied_service_after
    )
    denied_assessment = _service_registration_assessment(
        denied_service_before,
        denied_service_after,
        denied_new_entries,
        {},
        [],
        {"passed": True},
    )
    outcomes.append(
        (
            "service_registration_unobservable_denied_pass",
            denied_assessment["passed"]
            and denied_assessment["service_registration_basis"] == "sandbox_write_denied",
        )
    )

    not_denied_after = {
        **denied_service_after,
        "sandbox_write_denial": {"status": "ERROR", "reason": "nono_not_on_path"},
    }
    not_denied_assessment = _service_registration_assessment(
        denied_service_before,
        not_denied_after,
        N0Run._new_service_entries(denied_service_before, not_denied_after),
        {},
        [],
        {"passed": True},
    )
    outcomes.append(
        (
            "service_registration_unobservable_without_denial_fails",
            not not_denied_assessment["passed"]
            and not_denied_assessment["service_registration_basis"] is None,
        )
    )

    service_entry_after = {
        **observed_service_after,
        "launch_agents": ["xyz.opentunnel.n0-test.plist"],
    }
    service_entry_assessment = _service_registration_assessment(
        observed_service_before,
        service_entry_after,
        N0Run._new_service_entries(observed_service_before, service_entry_after),
        {},
        [],
        {"passed": True},
    )
    outcomes.append(
        (
            "service_registration_new_entry_fails",
            not service_entry_assessment["passed"]
            and bool(service_entry_assessment["new_opentunnel_entries"]),
        )
    )

    no_manager_evidence = {
        "basis": "linux_no_systemd_manager",
        "systemctl_resolvable": False,
        "systemd_runtime_present": False,
        "systemd_user_manager_socket_present": False,
        "pid1_comm": "python3",
        "proven": True,
    }
    no_manager_before = {
        "platform": "linux",
        "real_user_view": "unobservable",
        "no_service_manager_evidence": no_manager_evidence,
        "isolated_service_files_before": empty_isolated_before,
    }
    no_manager_after = {
        "platform": "linux",
        "real_user_view": "unobservable",
        "no_service_manager_evidence": no_manager_evidence,
        "isolated_service_files_after": empty_isolated_after,
    }
    no_manager_assessment = _service_registration_assessment(
        no_manager_before,
        no_manager_after,
        N0Run._new_service_entries(no_manager_before, no_manager_after),
        {},
        [],
        {"passed": True},
    )
    outcomes.append(
        (
            "service_registration_no_service_manager_basis_passes",
            no_manager_assessment["passed"]
            and no_manager_assessment["service_registration_basis"] == "no_service_manager",
        )
    )

    systemctl_present_after = {
        **no_manager_after,
        "no_service_manager_evidence": {
            **no_manager_evidence,
            "systemctl_resolvable": True,
            "proven": False,
        },
    }
    systemctl_present_assessment = _service_registration_assessment(
        no_manager_before,
        systemctl_present_after,
        N0Run._new_service_entries(no_manager_before, systemctl_present_after),
        {},
        [],
        {"passed": True},
    )
    outcomes.append(
        (
            "service_registration_no_service_manager_basis_rejects_manager",
            not systemctl_present_assessment["passed"]
            and systemctl_present_assessment["service_registration_basis"] is None,
        )
    )

    with (
        mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": ""}, clear=False),
        mock.patch.object(shutil, "which", return_value=None),
        mock.patch.object(
            sys.modules[__name__], "_path_presence", side_effect=[False, False]
        ),
        mock.patch.object(Path, "read_text", return_value="python3\n"),
    ):
        observed_no_manager = _linux_no_service_manager_observation()
    with (
        mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": ""}, clear=False),
        mock.patch.object(shutil, "which", return_value=None),
        mock.patch.object(
            sys.modules[__name__], "_path_presence", side_effect=[False, True]
        ),
        mock.patch.object(Path, "read_text", return_value="systemd\n"),
    ):
        observed_manager_present = _linux_no_service_manager_observation()
    outcomes.append(
        (
            "linux_no_service_manager_observation_is_narrowly_proven",
            observed_no_manager["proven"] is True
            and observed_manager_present["proven"] is False,
        )
    )

    manager_unit_after = {
        **no_manager_after,
        "isolated_service_files_after": {
            "launch_agents": [],
            "systemd_units": ["opentunnel.service"],
        },
    }
    manager_unit_assessment = _service_registration_assessment(
        no_manager_before,
        manager_unit_after,
        N0Run._new_service_entries(no_manager_before, manager_unit_after),
        {},
        [],
        {"passed": True},
    )
    outcomes.append(
        (
            "service_registration_no_service_manager_basis_rejects_unit_file",
            not manager_unit_assessment["passed"]
            and not manager_unit_assessment["isolated_home_service_files_empty"],
        )
    )

    synthetic_environment = {
        "PATH": "/usr/bin",
        "HTTPS_PROXY": "https://proxy.example",
        "OPENTUNNEL_PROFILE": "synthetic-profile",
        "OPENAI_API_KEY": "synthetic-key",
    }
    selected_environment = _selected_environment(synthetic_environment, CHILD_ENV_KEYS)
    environment_scrub_ok = (
        selected_environment.get("HTTPS_PROXY") == "https://proxy.example"
        and "OPENTUNNEL_PROFILE" not in selected_environment
        and "OPENAI_API_KEY" not in selected_environment
    )
    outcomes.append(("child_environment_allowlist", environment_scrub_ok))

    isolated_environment_ok = False

    missing_url_cleanup_ok = (
        not _absence_proven_without_url("", True, "config_file_failed")
        and _absence_proven_without_url("", False, "not_started")
        and _absence_proven_without_url(
            "", False, "up_minted_then_serve", identity_deleted=True
        )
        and not _absence_proven_without_url(
            "", False, "up_minted_then_serve", identity_deleted=False
        )
    )
    outcomes.append(("missing_url_after_start_fails_cleanup", missing_url_cleanup_ok))

    identity_up_blocked_ok = False
    identity_sequence_ok = False
    delete_failure_cleanup_ok = False
    nono_environment_ok = False
    identity_status_redaction_ok = False
    with tempfile.TemporaryDirectory(
        prefix="n0-driver-self-test-", dir=str(scratch_root)
    ) as scratch:
        scratch_path = Path(scratch)
        real_home = str(Path(os.path.expanduser("~")).resolve())
        cap_file = str(scratch_path / "nono-capability.json")
        nono_call: Dict[str, Any] = {}

        def _capture_nono_call(
            command: Sequence[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            nono_call["command"] = list(command)
            nono_call["kwargs"] = kwargs
            return subprocess.CompletedProcess(
                list(command),
                0,
                '{"status":"denied","reason":"path_not_granted"}',
                "",
            )

        with (
            mock.patch.dict(
                os.environ,
                {
                    "PATH": "/safe/nono-test-path",
                    "HOME": real_home,
                    "NONO_CAP_FILE": cap_file,
                    "UNRELATED_SECRET": "must-not-pass",
                },
                clear=True,
            ),
            mock.patch.object(
                shutil, "which", return_value="/safe/nono-test-path/nono"
            ),
            mock.patch.object(subprocess, "run", side_effect=_capture_nono_call),
        ):
            nono_observation = _nono_write_denial_observation(
                scratch_path / "LaunchAgents"
            )
        nono_call_env = nono_call.get("kwargs", {}).get("env", {})
        nono_environment_ok = (
            nono_observation.get("status") == "denied"
            and set(nono_call_env) == {"PATH", "HOME", "NONO_CAP_FILE"}
            and nono_call_env.get("PATH") == "/safe/nono-test-path"
            and nono_call_env.get("HOME") == real_home
            and nono_call_env.get("NONO_CAP_FILE") == cap_file
            and "UNRELATED_SECRET" not in nono_call_env
            and nono_call.get("kwargs", {}).get("check") is False
            and nono_call.get("kwargs", {}).get("timeout") == 10
        )

        blocked_run_dir = scratch_path / "blocked-identity"
        blocked_run_dir.mkdir(mode=0o700)
        blocked_path = blocked_run_dir / "empty-path"
        blocked_path.mkdir(mode=0o700)
        blocked_identity = test_run("macos", "self-test-blocked-up")
        blocked_identity.run_dir = blocked_run_dir
        blocked_identity.identity_path_dir = blocked_path
        blocked_identity.identity_cli_env = {"PATH": str(blocked_path)}
        blocked_runtime_dir = scratch_root / "r-blk"
        blocked_runtime_dir.mkdir(mode=0o700)
        blocked_identity.runtime_dir = blocked_runtime_dir
        blocked_up_invocations: List[Sequence[str]] = []
        blocked_identity._run_identity_cli = lambda args, timeout: (
            blocked_up_invocations.append(args) or {}
        )  # type: ignore[method-assign]

        manager_resolution_blocks: List[bool] = []
        for manager_name in ("launchctl", "systemctl"):
            def _which_reports_manager(
                name: str,
                path: Optional[str] = None,
                target: str = manager_name,
            ) -> Optional[str]:
                return "/system/bin/" + target if name == target else None

            with mock.patch.object(
                shutil, "which", side_effect=_which_reports_manager
            ):
                blocked_result = blocked_identity._mint_identity_without_service_registration()
            manager_resolution_blocks.append(
                not blocked_result
                and blocked_identity.identity_minting_observation["status"] == "BLOCKED"
                and blocked_identity.identity_minting_observation["preflight"]
                ["path_directory_is_private_and_empty"]
                and blocked_identity.identity_minting_observation["preflight"]
                ["service_manager_commands_resolvable"][manager_name]
                and blocked_identity.route_creation_path == "up_blocked"
            )
        identity_up_blocked_ok = all(manager_resolution_blocks) and not blocked_up_invocations

        sequence_run_dir = scratch_path / "identity-sequence"
        sequence_run_dir.mkdir(mode=0o700)
        sequence_path = sequence_run_dir / "empty-path"
        sequence_path.mkdir(mode=0o700)
        sequence_home = sequence_run_dir / "home"
        sequence_home.mkdir(mode=0o700)
        sequence_run = test_run("macos", "self-test-sequence")
        sequence_run.run_dir = sequence_run_dir
        sequence_run.runtime_dir = scratch_root / "r-seq"
        sequence_run.runtime_dir.mkdir(mode=0o700)
        os.chmod(sequence_run.runtime_dir, 0o700)
        sequence_run.identity_path_dir = sequence_path
        sequence_run.identity_cli_env = {
            "PATH": str(sequence_path),
            "HOME": str(sequence_home),
            "XDG_CONFIG_HOME": str(sequence_run_dir / "xdg/config"),
        }
        sequence_run.binary = Path("fake-opentunnel")
        sequence_events: List[str] = []
        identity_command_environments: List[Dict[str, str]] = []
        status_call_count = [0]
        status_outputs = [
            (
                "Profile: n0-self-test-sequence\n"
                "Tunnel ID: synthetic-id\n"
                "Hostname: synthetic.opentunnel.xyz\n"
                "Service: running, waiting for a tunnel (pid 424242, profile n0-self-test-sequence)\n"
            ),
            (
                "Profile: n0-self-test-sequence\n"
                "Tunnel ID: synthetic-id\n"
                "Hostname: synthetic.opentunnel.xyz\n"
                "Service: stopped (connect with: opentunnel up)\n"
            ),
        ]

        def _fake_identity_cli(
            args: Sequence[str],
            timeout: int,
            record_output: bool = False,
            environment: Optional[Mapping[str, str]] = None,
        ) -> Tuple[subprocess.CompletedProcess[str], bool]:
            identity_command_environments.append(dict(environment or {}))
            operation = args[-1]
            if operation == "up":
                sequence_events.append("up")
                output = "Connected https://synthetic.opentunnel.xyz\n"
            elif operation == "status":
                status_call_count[0] += 1
                sequence_events.append("status_after_up" if status_call_count[0] == 1 else "status_after_down")
                output = status_outputs.pop(0)
            elif operation == "down":
                sequence_events.append("down")
                output = "Disconnected profile n0-self-test-sequence.\n"
            else:
                output = ""
            return subprocess.CompletedProcess(list(args), 0, output, None), False

        sequence_run._run_cli = _fake_identity_cli  # type: ignore[method-assign]
        sequence_run._preserve_daemon_logs = lambda: (
            sequence_events.append("preserve_daemon_log")
            or {"files_preserved": 0, "artifact": None, "tail_redacted": None}
        )  # type: ignore[method-assign]
        sequence_run._isolated_service_files = lambda: empty_isolated_before  # type: ignore[method-assign]
        pid_liveness = iter([True, False])
        sequence_run._pid_is_alive = lambda _pid: next(pid_liveness)  # type: ignore[method-assign]
        sequence_run._write_profile_config = lambda: sequence_events.append("write_profile")  # type: ignore[method-assign]
        sequence_run._start_serve = lambda: sequence_events.append("serve") or object()  # type: ignore[method-assign]
        sequence_run._discover_from_serve = lambda _process, timeout: (
            sequence_events.append("discover") or "https://route123.opentunnel.xyz"
        )  # type: ignore[method-assign]
        sequence_success = sequence_run.activate_tunnel()
        required_sequence = [
            "up",
            "preserve_daemon_log",
            "status_after_up",
            "preserve_daemon_log",
            "down",
            "preserve_daemon_log",
            "status_after_down",
            "write_profile",
            "serve",
            "discover",
        ]
        identity_sequence_ok = (
            sequence_success
            and sequence_run.identity_minting_observation["passed"]
            and sequence_run.route_creation_path == "up_minted_then_serve"
            and sequence_events == required_sequence
            and len(identity_command_environments) == 4
            and all(
                environment.get("PATH") == str(sequence_path)
                and environment.get("HOME") == str(sequence_home)
                for environment in identity_command_environments
            )
        )

        delete_run_dir = scratch_path / "delete-failure"
        delete_run_dir.mkdir(mode=0o700)
        delete_path = delete_run_dir / "empty-path"
        delete_path.mkdir(mode=0o700)
        delete_failure_run = test_run("macos", "self-test-delete-failure")
        delete_failure_run.run_dir = delete_run_dir
        delete_failure_run.identity_path_dir = delete_path
        delete_failure_run.identity_cli_env = {"PATH": str(delete_path)}
        delete_failure_run.identity_up_attempted = True
        delete_failure_run.identity_deleted = False
        delete_failure_run.identity_minting_observation = {"passed": True}
        delete_failure_run.route_creation_path = "up_minted_then_serve"
        delete_failure_run.profile_config = delete_run_dir / "profile.toml"
        delete_failure_run.profile_config.write_text("[routes]\n", encoding="ascii")
        delete_failure_run.public_url = "https://route123.opentunnel.xyz"
        delete_failure_run.services_before = {
            "real_user_view": "observed",
            "source": "ls_launch_agents",
            "launch_agents": [],
            "systemd_units": [],
            "isolated_service_files_before": empty_isolated_before,
        }
        delete_failure_run.processes_before = {}
        delete_failure_run._isolated_service_files = lambda: empty_isolated_after  # type: ignore[method-assign]
        delete_failure_run._environment_isolation_observation = lambda: {"passed": True}  # type: ignore[method-assign]
        delete_events: List[str] = []
        delete_failure_run._preserve_daemon_logs = lambda: (
            delete_events.append("preserve_daemon_log")
            or {"files_preserved": 0, "artifact": None, "tail_redacted": None}
        )  # type: ignore[method-assign]

        def _fake_delete_cli(
            args: Sequence[str],
            timeout: int,
            record_output: bool = False,
            environment: Optional[Mapping[str, str]] = None,
        ) -> Tuple[subprocess.CompletedProcess[str], bool]:
            if len(args) >= 2 and args[-2] == "delete":
                delete_events.append("delete")
                return subprocess.CompletedProcess(list(args), 1, "synthetic delete failure\n", None), False
            delete_events.append("status_after_delete")
            status_output = (
                "Profile: n0-self-test-delete-failure\n"
                "Tunnel ID: synthetic-id\n"
                "Hostname: synthetic.opentunnel.xyz\n"
                "Service: stopped (connect with: opentunnel up)\n"
            )
            return subprocess.CompletedProcess(list(args), 0, status_output, None), False

        delete_failure_run._run_cli = _fake_delete_cli  # type: ignore[method-assign]
        with (
            mock.patch.object(
                requests, "get", side_effect=requests.ConnectionError("offline self-test")
            ),
            mock.patch.object(sys.modules[__name__], "_is_port_free", return_value=True),
            mock.patch.object(
                sys.modules[__name__],
                "_service_snapshot",
                return_value={
                    "available": True,
                    "real_user_view": "observed",
                    "source": "ls_launch_agents",
                    "launch_agents": [],
                    "systemd_units": [],
                    "unit_files": [],
                },
            ),
            mock.patch.object(
                sys.modules[__name__], "_open_tunnel_process_snapshot", return_value={}
            ),
        ):
            delete_failure_run.finalize_checks()
        delete_clean_check = next(
            item for item in delete_failure_run.checks if item["name"] == "clean_shutdown"
        )
        delete_failure_cleanup_ok = (
            delete_clean_check["status"] == "FAIL"
            and delete_clean_check["observed"]["identity_deleted"] is False
            and delete_events
            == ["preserve_daemon_log", "delete", "status_after_delete"]
            and any(item["name"] == "no_service_registration" for item in delete_failure_run.checks)
            and any(item["name"] == "cleanup_execution" for item in delete_failure_run.checks)
        )

        bad_archive = scratch_path / "bad.tar.gz"
        bad_archive.write_bytes(b"not a real archive")
        destination = scratch_path / "extract-must-not-exist"
        actual_digest = _sha256_file(bad_archive)
        checksum, extracted = verify_and_extract_archive(
            bad_archive,
            "0" * 64 + "  opentunnel-selftest.tar.gz\n",
            "opentunnel-selftest.tar.gz",
            actual_digest,
            destination,
        )
        mismatch_ok = checksum["status"] == "FAIL" and extracted is None and not destination.exists()

        stable_test_asset = "opentunnel-darwin-arm64.tar.gz"
        stable_test_root = scratch_path / "stable-install-root"
        existing_stable_binary = _stable_binary_path(stable_test_asset, stable_test_root)
        existing_stable_binary.parent.mkdir(mode=0o700, parents=True)
        stable_binary_sentinel = b"previous stable OpenTunnel binary"
        existing_stable_binary.write_bytes(stable_binary_sentinel)
        with mock.patch.object(
            sys.modules[__name__], "safe_extract_archive", wraps=safe_extract_archive
        ) as safe_extract:
            mismatch_install_result, mismatch_install_path = _install_verified_binary(
                bad_archive,
                "0" * 64 + "  " + stable_test_asset + "\n",
                stable_test_asset,
                ASSET_DIGESTS[stable_test_asset],
                stable_test_root,
            )
        stable_binary_untouched_ok = (
            mismatch_install_result["status"] == "FAIL"
            and mismatch_install_path is None
            and safe_extract.call_count == 0
            and existing_stable_binary.read_bytes() == stable_binary_sentinel
        )

        synthetic_archive = scratch_path / "synthetic-opentunnel.tar.gz"
        synthetic_binary = b"synthetic stable OpenTunnel executable\n"
        with tarfile.open(synthetic_archive, mode="w:gz") as archive:
            member = tarfile.TarInfo("bin/opentunnel")
            member.size = len(synthetic_binary)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(synthetic_binary))
        synthetic_archive_digest = _sha256_file(synthetic_archive)
        synthetic_sums = "%s  %s\n" % (synthetic_archive_digest, stable_test_asset)
        successful_install_root = scratch_path / "stable-install-success"
        successful_install_result, successful_install_path = _install_verified_binary(
            synthetic_archive,
            synthetic_sums,
            stable_test_asset,
            synthetic_archive_digest,
            successful_install_root,
        )
        stable_install_success_ok = bool(
            successful_install_result["status"] == "PASS"
            and successful_install_path
            == _stable_binary_path(stable_test_asset, successful_install_root)
            and successful_install_path.read_bytes() == synthetic_binary
            and os.access(successful_install_path, os.X_OK)
            and successful_install_result["observed"].get("binary_sha256")
            == hashlib.sha256(synthetic_binary).hexdigest()
        )

        isolated_root = scratch_path / "isolated-environment"
        isolated_root.mkdir(mode=0o700)
        xdg_paths = {
            "config": isolated_root / "xdg/config",
            "data": isolated_root / "xdg/data",
            "state": isolated_root / "xdg/state",
        }
        runtime_path = isolated_root / "runtime"
        isolated_child_env = _isolated_process_environment(
            isolated_root, xdg_paths, runtime_path, synthetic_environment
        )
        environment_probe = test_run("macos", "self-test-env")
        environment_probe.run_dir = isolated_root
        environment_probe.xdg = xdg_paths
        environment_probe.runtime_dir = runtime_path
        environment_probe.runtime_dir_basis = "project_tmp"
        environment_probe.env = isolated_child_env
        environment_observation = environment_probe._environment_isolation_observation()
        isolated_allowed_keys = set(CHILD_ENV_KEYS).union(
            {
                "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                "XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP",
            }
        )
        isolated_environment_ok = (
            environment_observation["passed"]
            and isolated_child_env.get("HOME") == str(isolated_root / "home")
            and isolated_child_env.get("XDG_CONFIG_HOME") == str(xdg_paths["config"])
            and isolated_child_env.get("XDG_DATA_HOME") == str(xdg_paths["data"])
            and isolated_child_env.get("XDG_STATE_HOME") == str(xdg_paths["state"])
            and isolated_child_env.get("XDG_RUNTIME_DIR") == str(runtime_path)
            and environment_observation["runtime_dir_basis"] == "project_tmp"
            and all(
                isolated_child_env.get(key) == str(isolated_root / "tmp")
                for key in ("TMPDIR", "TMP", "TEMP")
            )
            and set(isolated_child_env).issubset(isolated_allowed_keys)
            and "OPENAI_API_KEY" not in isolated_child_env
            and "OPENTUNNEL_PROFILE" not in isolated_child_env
            and "synthetic-key" not in "\n".join(isolated_child_env.values())
        )

        failed_start = test_run("macos", "self-test-failed-start")
        failed_start.run_dir = scratch_path / "failed-serve"
        failed_start.run_dir.mkdir(mode=0o700)
        failed_start.profile_config = scratch_path / "failed-profile.toml"
        failed_start.profile_config.write_text("[routes]\n", encoding="ascii")
        failed_start.binary = Path(sys.executable)
        failed_start._mint_identity_without_service_registration = lambda: True  # type: ignore[method-assign]
        failed_start.route_creation_path = "up_minted_then_serve"
        failed_start._write_profile_config = lambda: None  # type: ignore[method-assign]

        def _raise_start_error() -> subprocess.Popen[bytes]:
            raise OSError("synthetic serve startup failure")

        failed_start._start_serve = _raise_start_error  # type: ignore[method-assign]
        startup_failed = not failed_start.activate_tunnel()
        startup_evidence = build_evidence(
            run_id="self-test-failed-start",
            selected_platform="macos",
            arch="arm64",
            os_version="test-os",
            python_version="3.test",
            package_versions={},
            build_sha="test-sha",
            build_identity_source="unknown",
            worktree_dirty=False,
            runtime_dir_basis="project_tmp",
            opentunnel={},
            route_creation_path=failed_start.route_creation_path,
            public_url_redacted="not_discovered",
            checks=[],
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            blockers=failed_start.blockers,
        )
        startup_failure_blocked = (
            startup_failed
            and startup_evidence["verdict_hint"] == "BLOCKED"
            and failed_start.route_creation_path == "up_minted_then_serve_failed"
            and bool(failed_start.blockers)
            and failed_start.route_removed
            and not failed_start.profile_config.exists()
        )

        log_run = test_run("macos", "self-test")
        log_run.run_dir = scratch_path / "bounded-logs"
        log_run.run_dir.mkdir(mode=0o700)
        log_secret = "n0-secret-prefix-" + "z" * 64
        log_run.sensitive_values.append(log_secret)
        log_run.append_log(
            "redaction.log", "x" * (MAX_LOG_ENTRY_CHARS - 5) + log_secret
        )
        redaction_log_text = (log_run.run_dir / "redaction.log").read_text(encoding="utf-8")
        redaction_before_truncation = (
            log_secret not in redaction_log_text
            and log_secret[:12] not in redaction_log_text
        )

        identity_status_run = test_run("macos", "self-test-status-redaction")
        identity_status_run.run_dir = scratch_path / "status-redaction"
        identity_status_run.run_dir.mkdir(mode=0o700)
        identity_status_run.binary = Path(sys.executable)
        identity_status_run.env = {}
        fake_status_process = mock.Mock()
        fake_status_process.pid = 424243
        with (
            mock.patch.object(subprocess, "Popen", return_value=fake_status_process),
            mock.patch.object(
                sys.modules[__name__],
                "_capture_bounded_process_output",
                return_value=(0, connected_status, False),
            ),
        ):
            identity_status_observation = identity_status_run._run_identity_cli(
                ["--profile", identity_status_run.profile, "status"], timeout=5
            )
        identity_status_log = (
            identity_status_run.run_dir / "tunnel.log"
        ).read_text(encoding="utf-8")
        identity_status_evidence = json.dumps(
            redact_value(identity_status_observation, identity_status_run.sensitive_values),
            sort_keys=True,
        )
        identity_status_redaction_ok = (
            "tunnel-id-self-test" in identity_status_run.sensitive_values
            and "status-host.opentunnel.xyz" in identity_status_run.sensitive_values
            and "tunnel-id-self-test" not in identity_status_log
            and "tunnel-id-self-test" not in identity_status_observation["output_redacted"]
            and "tunnel-id-self-test" not in identity_status_evidence
            and "status-host.opentunnel.xyz" not in identity_status_evidence
        )

        daemon_log_run = test_run("linux", "self-test-daemon-log")
        daemon_log_run.keep_identity = True
        daemon_log_run.run_dir = scratch_path / "daemon-log-redaction"
        daemon_log_run.run_dir.mkdir(mode=0o700)
        daemon_state_dir = scratch_path / "daemon-log-state"
        daemon_state_dir.mkdir(mode=0o700)
        daemon_log_run.xdg = {"state": daemon_state_dir}
        daemon_log_run.identity_minting_observation = {"status": "PASS", "passed": True}
        daemon_log_profile_one = daemon_state_dir / "opentunnel/profile-one"
        daemon_log_profile_two = daemon_state_dir / "opentunnel/profile-two"
        daemon_log_profile_one.mkdir(mode=0o700, parents=True)
        daemon_log_profile_two.mkdir(mode=0o700, parents=True)
        daemon_tunnel_id = "daemon-private-tunnel-id-7001"
        daemon_hostname = "daemon-private-host.opentunnel.xyz"
        daemon_credential = "daemon-private-pass" + "word-7002"
        daemon_session_value = "daemon-private-tok" + "en-7003"
        daemon_log_one = (
            "Tunnel ID: " + daemon_tunnel_id + "\n"
            "Hostname: " + daemon_hostname + "\n"
            "route=" + daemon_log_run.route_name + "\n"
            "password=" + daemon_credential + "\n"
        )
        daemon_log_two = "token=" + daemon_session_value + "\nflock startup warning\n"
        (daemon_log_profile_one / "daemon.log").write_text(
            daemon_log_one, encoding="utf-8"
        )
        (daemon_log_profile_two / "daemon.log").write_text(
            daemon_log_two, encoding="utf-8"
        )
        daemon_log_preservation = daemon_log_run._preserve_daemon_logs()
        daemon_log_artifact = daemon_log_run.run_dir / "daemon.log.redacted"
        daemon_log_artifact_text = daemon_log_artifact.read_text(encoding="utf-8")
        daemon_log_mode = stat.S_IMODE(daemon_log_artifact.stat().st_mode)
        daemon_log_redaction_ok = (
            daemon_log_preservation["files_preserved"] == 2
            and daemon_log_preservation["artifact"] == "daemon.log.redacted"
            and daemon_log_mode == 0o600
            and all(
                secret not in daemon_log_artifact_text
                for secret in (
                    daemon_tunnel_id,
                    daemon_hostname,
                    daemon_log_run.route_name,
                    daemon_credential,
                    daemon_session_value,
                )
            )
            and daemon_log_run.identity_minting_observation[
                "daemon_log_tail_redacted"
            ] == daemon_log_run.daemon_log_tail_redacted
            and len(daemon_log_run.daemon_log_tail_redacted) <= MAX_DAEMON_LOG_TAIL_CHARS
            and "flock startup warning" in daemon_log_artifact_text
        )

        boundary_value = "daemon-boundary-" + "secret-7004"
        (daemon_log_profile_two / "daemon.log").write_text(
            "prefix\npassword=" + boundary_value + "tail", encoding="utf-8"
        )
        with mock.patch.object(
            sys.modules[__name__], "MAX_DAEMON_LOG_BYTES", 12
        ):
            daemon_log_run._preserve_daemon_logs()
        boundary_log_text = daemon_log_artifact.read_text(encoding="utf-8")
        daemon_log_redaction_before_truncation_ok = (
            len(daemon_log_artifact.read_bytes()) <= 12
            and boundary_value[-8:] not in boundary_log_text
            and boundary_value not in boundary_log_text
        )

        runtime_cleanup_dir = scratch_path / "daemon-log-runtime-cleanup"
        runtime_cleanup_dir.mkdir(mode=0o700)
        daemon_log_run.runtime_dir = runtime_cleanup_dir
        cleanup_order: List[str] = []
        original_rmtree = shutil.rmtree

        def _record_rmtree(path: Path, *args: Any, **kwargs: Any) -> None:
            cleanup_order.append("remove")
            original_rmtree(path, *args, **kwargs)

        original_preserve = daemon_log_run._preserve_daemon_logs

        def _record_preserve() -> Dict[str, Any]:
            cleanup_order.append("preserve")
            return original_preserve()

        with (
            mock.patch.object(daemon_log_run, "_preserve_daemon_logs", side_effect=_record_preserve),
            mock.patch.object(shutil, "rmtree", side_effect=_record_rmtree),
        ):
            daemon_log_run._remove_runtime_dir()
        daemon_log_state_cleanup_order_ok = (
            cleanup_order
            and cleanup_order[0] == "preserve"
            and daemon_log_artifact.exists()
            and not runtime_cleanup_dir.exists()
            and not (daemon_state_dir / "opentunnel").exists()
        )

        log_run.binary = Path(sys.executable)
        log_run.env = {}
        cli_result, cli_output_truncated = log_run._run_cli(
            ["-c", "import sys; sys.stdout.write('x' * 100000)"],
            timeout=10,
            record_output=True,
        )
        cli_output_bounded = (
            cli_result.returncode == 0
            and cli_output_truncated
            and len(cli_result.stdout.encode("utf-8")) <= MAX_CLI_OUTPUT_BYTES
            and len(cli_result.stdout) == MAX_CLI_OUTPUT_BYTES
        )
        for _index in range(130):
            log_run.append_log("tunnel.log", "x" * MAX_LOG_ENTRY_CHARS)
        log_size = (log_run.run_dir / "tunnel.log").stat().st_size
        for index in range(MAX_TUNNEL_OUTPUT_LINES + 10):
            log_run.tunnel_output.append("line-%d" % index)
        output_bounds_ok = (
            log_size <= MAX_LOG_BYTES
            and log_run.log_sizes["tunnel.log"] <= MAX_LOG_BYTES
            and len(log_run.tunnel_output) == MAX_TUNNEL_OUTPUT_LINES
            and log_run.tunnel_output[0] == "line-10"
        )
    outcomes.append(("checksum_mismatch_no_extract", mismatch_ok))
    outcomes.append(("checksum_mismatch_preserves_existing_stable_binary", stable_binary_untouched_ok))
    outcomes.append(("verified_binary_installs_with_recorded_sha256", stable_install_success_ok))
    outcomes.append(("nono_write_denial_uses_minimal_real_user_environment", nono_environment_ok))
    outcomes.append(
        (
            "identity_up_blocked_when_service_manager_resolvable",
            identity_up_blocked_ok,
        )
    )
    outcomes.append(("identity_minting_precedes_serve", identity_sequence_ok))
    outcomes.append(
        (
            "identity_delete_failure_fails_clean_shutdown_and_cleanup_continues",
            delete_failure_cleanup_ok,
        )
    )
    outcomes.append(("isolated_home_xdg_and_temp_paths", isolated_environment_ok))
    outcomes.append(("failed_declarative_serve_blocks_and_cleans_profile", startup_failure_blocked))
    outcomes.append(("redaction_precedes_log_truncation", redaction_before_truncation))
    outcomes.append(("identity_status_tunnel_id_and_hostname_redacted", identity_status_redaction_ok))
    outcomes.append(("daemon_logs_are_preserved_redacted_and_private", daemon_log_redaction_ok))
    outcomes.append(("daemon_log_redaction_precedes_tail_truncation", daemon_log_redaction_before_truncation_ok))
    outcomes.append(("daemon_logs_preserved_before_state_cleanup", daemon_log_state_cleanup_order_ok))
    outcomes.append(("bounded_process_output_and_logs", output_bounds_ok and cli_output_bounded))
    outcomes.append(("runtime_parent_override_validation", runtime_parent_validation_ok))
    outcomes.append(("runtime_dir_flock_and_af_unix_probe_succeeds", runtime_probe_success_ok))
    outcomes.append(("runtime_probe_failure_blocks_up_before_cli", runtime_probe_failure_ok))

    schema_checks = [
        {"name": name, "expected": "pass", "observed": "pass", "status": "PASS"}
        for name in REQUIRED_CHECKS[:-1]
    ]
    evidence = build_evidence(
        run_id="self-test",
        selected_platform="macos",
        arch="arm64",
        os_version="test-os",
        python_version="3.test",
        package_versions={},
        build_sha="test-sha",
        build_identity_source="unknown",
        worktree_dirty=None,
        runtime_dir_basis="project_tmp",
        opentunnel={"version": "test", "asset": "test", "digest": None, "digest_expected": None, "sums_match": False},
        route_creation_path="not_started",
        public_url_redacted="not_discovered",
        checks=schema_checks,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
    )
    required_keys = {
        "schema_version", "run_id", "platform", "arch", "os_version", "python",
        "package_versions", "build_sha", "build_identity_source", "worktree_dirty",
        "runtime_dir_basis", "opentunnel",
        "route_creation_path", "public_url_redacted", "checks", "required_checks",
        "verdict_hint", "started_at", "finished_at",
    }
    schema_ok = (
        required_keys.issubset(evidence)
        and evidence["verdict_hint"] == "FAIL"
        and evidence["build_identity_source"] == "unknown"
        and evidence["worktree_dirty"] is None
        and evidence["runtime_dir_basis"] == "project_tmp"
    )
    outcomes.append(("evidence_schema_missing_required_check", schema_ok))

    class _LiveTestProcess:
        pid = 4242

        def poll(self) -> None:
            return None

    cleanup_run = test_run("macos", "self-test-cleanup")
    cleanup_run.owned_processes = [("tunnel.log", _LiveTestProcess())]  # type: ignore[list-item]
    cleanup_run.checks = [
        check_record(name, "clean", "clean", True)
        for name in ("clean_shutdown", "no_service_registration", "cleanup_execution")
    ]
    cleanup_run._record_finalize_failure(RuntimeError("synthetic cleanup failure"))
    cleanup_records = {
        item["name"]: item for item in cleanup_run.checks
        if item["name"] in ("clean_shutdown", "no_service_registration", "cleanup_execution")
    }
    cleanup_failure_ok = (
        len(cleanup_records) == 3
        and all(item["status"] == "FAIL" for item in cleanup_records.values())
        and all(item["observed"]["tracked_pids_alive"] == [4242] for item in cleanup_records.values())
        and all(item["observed"]["cleanup_exception"] == "RuntimeError" for item in cleanup_records.values())
        and all(
            item["observed"]["cleanup_exception_message"] == "synthetic cleanup failure"
            for item in cleanup_records.values()
        )
        and all(
            any(
                process["pid"] == 4242 and process["alive"] is True
                for process in item["observed"]["tracked_processes"]
            )
            for item in cleanup_records.values()
        )
    )
    outcomes.append(("cleanup_exception_forces_fail_and_retains_pids", cleanup_failure_ok))

    for name, passed in outcomes:
        print("[%s] %s" % ("PASS" if passed else "FAIL", name))
    return 0 if all(passed for _name, passed in outcomes) else 1


def _self_test() -> int:
    """Run self-tests in disposable project-local scratch, never the evidence tree."""
    scratch_parent = REPO_ROOT / "tmp/n0"
    scratch_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="n0-driver-self-test-", dir=str(scratch_parent)
    ) as scratch:
        return _self_test_impl(Path(scratch))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the N0 OpenTunnel feasibility spike")
    parser.add_argument("--platform", choices=("macos", "linux"), help="must match the detected OS")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--self-test", action="store_true", help="run offline driver self-tests only")
    parser.add_argument(
        "--keep-tunnel-identity",
        action="store_true",
        help="preserve isolated profile identity files in the evidence run directory",
    )
    parser.add_argument(
        "--runtime-parent",
        help="existing owner-only 0700 runtime parent (default: project tmp/n0/r)",
    )
    args = parser.parse_args(argv)
    if not args.self_test and not _safe_run_id(args.run_id):
        parser.error("--run-id must be 1-32 characters: letters, digits, dot, underscore, hyphen")
    if not args.self_test:
        try:
            _profile_name_from_run_id(args.run_id)
        except ValueError as exc:
            parser.error(str(exc))
    if args.runtime_parent is not None and not args.self_test:
        try:
            args.runtime_parent = _validate_runtime_parent(Path(args.runtime_parent))
        except ValueError as exc:
            parser.error(str(exc))
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    detected, system, machine = _detected_platform()
    if args.platform and args.platform != detected:
        print(
            "[FAIL] --platform must match detected platform (detected %s/%s)" % (system, machine),
            file=sys.stderr,
        )
        return 2
    if args.self_test:
        return _self_test()
    selected = args.platform or detected
    if not detected or selected != detected:
        print(
            "[FAIL] --platform must match detected platform (detected %s/%s)" % (system, machine),
            file=sys.stderr,
        )
        return 2
    if (system, machine) not in PLATFORM_ASSETS:
        print("[FAIL] unsupported detected OS/architecture: %s/%s" % (system, machine), file=sys.stderr)
        return 2
    if not (REPO_ROOT / "tmp/n0").is_dir():
        print("[FAIL] expected project-local tmp/n0 directory is missing", file=sys.stderr)
        return 2
    profile_name = _profile_name_from_run_id(args.run_id)
    evidence_dir = REPO_ROOT / "tmp/router-rollout/v2-network" / (
        "n0-" + selected + "-" + args.run_id
    )
    download_dir = OPENTUNNEL_ROOT / "downloads" / args.run_id
    runtime_parent = (
        Path(args.runtime_parent)
        if args.runtime_parent is not None
        else REPO_ROOT / "tmp/n0/r"
    )
    runtime_socket = runtime_parent / "0000/opentunnel" / (
        profile_name + ".sock"
    )
    if len(os.fsencode(str(runtime_socket))) >= MAX_UNIX_SOCKET_PATH:
        print("[FAIL] --run-id makes the isolated Unix socket path too long", file=sys.stderr)
        return 2
    if evidence_dir.exists() or download_dir.exists():
        print("[FAIL] run-id already has evidence or downloaded assets; choose a new --run-id", file=sys.stderr)
        return 2

    previous_handlers: Dict[int, Any] = {}

    def interrupt_handler(signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt("signal %d" % signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, interrupt_handler)
    try:
        return N0Run(
            selected,
            args.run_id,
            args.keep_tunnel_identity,
            runtime_parent=Path(args.runtime_parent) if args.runtime_parent is not None else None,
        ).execute()
    except (OSError, ValueError) as exc:
        print("[FAIL] driver setup error: %s" % type(exc).__name__, file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
