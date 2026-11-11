# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Primary-owned N3 lifecycle preflight tooling; never runs the live gate."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.controller import (
    RouteStatus,
    SharingController,
    SharingDependencies,
    SharingState,
)
from web.extensions.opentunnel_sharing.identity_bootstrap import BootstrapResult
from web.extensions.opentunnel_sharing.origin_binding import PublicOriginBinder
from web.extensions.opentunnel_sharing.profile_state import ProfileLayout, ProfileState
from web.extensions.opentunnel_sharing.service import (
    PlayerSharingService,
    SharingServiceDependencies,
)
from web.extensions.opentunnel_sharing.verifier_store import (
    IssuedCredential,
    VerifierLoad,
    VerifierStatus,
)
from web.extensions.player.auth import PlayerSecurity, make_verifier
from utils.file_operations import safe_write_json


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_BASE = Path("tmp/router-rollout/v2-network/n3")
CAPTURE_SOURCE_RELATIVE = Path("modules/Capture_Arena")
HOST_PORT = 8360
PLAYER_PORT = 8370
APPROVED_PLATFORMS = ("darwin-arm64", "linux-arm64")
RUN_ID_PATTERN = re.compile(r"n3-[a-z0-9][a-z0-9-]{0,62}\Z")
SHA_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MAX_EVIDENCE_STRING = 512
MAX_EVIDENCE_LIST = 64
FAKE_ORIGIN = "https://n3-preflight.example.net"
FAKE_PASSWORD = "n3-preflight-only-password"
FAKE_ROTATED_PASSWORD = "n3-preflight-rotated-password"
FAKE_PLAINTEXT_CREDENTIAL = "N3_PREFLIGHT_ONLY_CREDENTIAL"


@dataclass(frozen=True, slots=True)
class LifecycleRow:
    row_id: str
    expected: str


SCENARIO_ROWS = (
    LifecycleRow(
        "sharing-off-local-play",
        "Sharing stays off while the isolated local host remains available.",
    ),
    LifecycleRow(
        "identity-bootstrap-once",
        "Facilitator-confirmed identity initialization is performed once per profile.",
    ),
    LifecycleRow(
        "start-authenticated-entry",
        "An explicit start reaches ready and the local player security boundary accepts a session.",
    ),
    LifecycleRow(
        "duplicate-start-idempotent",
        "A duplicate start keeps the generation and owned resource counts unchanged.",
    ),
    LifecycleRow(
        "relay-loss-bounded-recovery",
        "A stubbed relay loss withdraws the invitation and recovers within one bounded recovery action.",
    ),
    LifecycleRow(
        "credential-rotation-revocation",
        "Credential rotation invalidates old sessions before readiness is rebound.",
    ),
    LifecycleRow(
        "explicit-stop",
        "Explicit stop clears the origin and stops only the fixture-owned listener and companion.",
    ),
    LifecycleRow(
        "host-exit-restart-sharing-off",
        "A restarted host does not implicitly restart sharing or revive the prior generation.",
    ),
    LifecycleRow(
        "route-session-revocation",
        "Access revocation removes the owned route and invalidates active player sessions.",
    ),
    LifecycleRow(
        "clean-teardown",
        "Lifecycle resources are absent before the host harness and live-window lock are released.",
    ),
)


@dataclass(frozen=True, slots=True)
class GateCaps:
    max_rows: int = 10
    max_attempts: int = 10
    max_attempts_per_row: int = 1
    max_row_seconds: int = 300
    max_run_seconds: int = 3600
    automatic_retries: int = 0
    provider_attempts: int = 0
    relay_connections: int = 0


FROZEN_CAPS = GateCaps()
_MANIFEST_PAYLOAD = {
    "schema_version": 1,
    "gate": "N3",
    "host": {"host": "127.0.0.1", "port": HOST_PORT},
    "player": {"host": "127.0.0.1", "port": PLAYER_PORT},
    "approved_platforms": APPROVED_PLATFORMS,
    "caps": asdict(FROZEN_CAPS),
    "rows": tuple(asdict(row) for row in SCENARIO_ROWS),
}
SCENARIO_MANIFEST_SHA256 = "985c1368b3d12767c05984dcf1c2c41cbd101eace7338537382091e7eb81f586"
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_verifier",
        "neq_player_password_verifier",
        "verifier",
        "raw_verifier",
        "cookie",
        "set_cookie",
        "cookies",
        "authorization",
        "csrf",
        "csrf_token",
        "csrf_nonce",
        "csrf_proof",
        "neq_player_session",
        "neq_player_prelogin",
        "session",
        "session_id",
        "session_cookie",
        "session_token",
        "session_epoch",
        "session_grant",
        "cookie_value",
        "invitation_value",
        "invitation_url",
        "credential",
        "credential_value",
        "plaintext_credential",
        "access_token",
        "token",
        "secret",
        "private_key",
        "invitation",
        "invitation_url",
        "raw_url",
        "url",
    }
)
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(password(?:[_-]?verifier)?|verifier|cookie(?:[_-]?(?:value|token))?|"
    r"set-cookie|authorization|csrf(?:[_-]?(?:token|nonce|proof))?|"
    r"session(?:[_-]?(?:id|cookie|token|epoch|grant))?|access[_-]?token|"
    r"credential(?:[_-]?value)?|invitation(?:[_-]?url)?)"
    r"\s*[:=]\s*[^\r\n,;]*"
)
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    git_sha: str
    worktree_clean: bool
    platform_key: str
    git_common_dir: Path
    source_files_sha256: str
    dependency_lock_sha256: str
    route_contract_sha256: str
    identity_freeze_sha256: str


@dataclass(frozen=True, slots=True)
class PortObservation:
    port: int
    state: str
    pids: tuple[int, ...] = ()


class PortInspector(Protocol):
    def inspect(self, port: int) -> PortObservation: ...


class LiveWindowLock(Protocol):
    @property
    def acquired(self) -> bool: ...

    def acquire(self, holder_record: Mapping[str, object]) -> bool: ...

    def release(self, release_record: Mapping[str, object]) -> bool: ...


class HostHarness(Protocol):
    @property
    def owner_pid(self) -> int: ...

    def start(self) -> bool: ...

    def is_ready(self) -> bool: ...

    def stop(self) -> bool: ...


class LifecycleHarness(Protocol):
    service: PlayerSharingService
    security: PlayerSecurity
    state: "_SharedProfileState"

    def controller(self) -> SharingController | None: ...

    def actions(self) -> Mapping[str, Callable[[], Mapping[str, object]]]: ...

    def restart_service(self) -> "LifecycleHarness": ...

    def cleanup(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class PreflightDependencies:
    root: Path
    identity_reader: Callable[[Path], WorkspaceIdentity]
    port_inspector: PortInspector
    lock_factory: Callable[[WorkspaceIdentity, str, str, Path], LiveWindowLock]
    capture_copier: Callable[[Path, Path], str]
    host_factory: Callable[[Path, PortInspector], HostHarness]
    lifecycle_factory: Callable[[Path, HostHarness, Callable[[], float]], LifecycleHarness]
    clock: Callable[[], float] = time.monotonic
    utc_now: Callable[[], str] = lambda: _utc_now()
    evidence_writer: Callable[[Path, Mapping[str, object], Sequence[str]], bool] = (
        lambda path, payload, secrets: write_redacted_evidence(path, payload, secrets)
    )
    lifecycle_actions_factory: (
        Callable[[LifecycleHarness], Mapping[str, Callable[[], Mapping[str, object]]]]
        | None
    ) = None


def canonical_manifest_bytes() -> bytes:
    return json.dumps(
        _MANIFEST_PAYLOAD,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def calculate_manifest_sha256() -> str:
    return hashlib.sha256(canonical_manifest_bytes()).hexdigest()


def verify_frozen_manifest() -> bool:
    return (
        len(SCENARIO_ROWS) == FROZEN_CAPS.max_rows
        and calculate_manifest_sha256() == SCENARIO_MANIFEST_SHA256
        and len({row.row_id for row in SCENARIO_ROWS}) == len(SCENARIO_ROWS)
    )


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _file_set_hash(root: Path, relative_paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(relative_paths, key=lambda item: item.as_posix()):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("identity_file_unavailable")
        data = path.read_bytes()
        digest.update(relative.as_posix().encode("ascii"))
        digest.update(b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


IDENTITY_SOURCE_FILES = (
    Path("scripts/n3_lifecycle_gate.py"),
    Path("web/extensions/opentunnel_sharing/cleanup.py"),
    Path("web/extensions/opentunnel_sharing/companion.py"),
    Path("web/extensions/opentunnel_sharing/controller.py"),
    Path("web/extensions/opentunnel_sharing/identity_bootstrap.py"),
    Path("web/extensions/opentunnel_sharing/origin_binding.py"),
    Path("web/extensions/opentunnel_sharing/profile_state.py"),
    Path("web/extensions/opentunnel_sharing/service.py"),
    Path("web/extensions/opentunnel_sharing/supervisor.py"),
    Path("web/extensions/opentunnel_sharing/verifier_store.py"),
    Path("web/extensions/player/auth.py"),
    Path("web/extensions/player/listener.py"),
)


def _run_git(root: Path, args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
            check=False,
            shell=False,
            env={"LC_ALL": "C", "PATH": os.defpath},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("git_identity_unavailable") from None
    if result.returncode != 0:
        raise RuntimeError("git_identity_unavailable")
    return result.stdout.strip()


def _platform_key(system: str | None = None, machine: str | None = None) -> str:
    selected_system = platform.system() if system is None else system
    selected_machine = platform.machine() if machine is None else machine
    normalized_machine = selected_machine.lower()
    if normalized_machine in {"arm64", "aarch64"}:
        normalized_machine = "arm64"
    else:
        normalized_machine = normalized_machine.replace("_", "-")
    normalized_system = {
        "darwin": "darwin",
        "linux": "linux",
    }.get(selected_system.lower(), selected_system.lower())
    return normalized_system + "-" + normalized_machine


def read_workspace_identity(root: Path) -> WorkspaceIdentity:
    git_sha = _run_git(root, ("rev-parse", "HEAD"))
    if SHA_PATTERN.fullmatch(git_sha) is None:
        raise RuntimeError("git_sha_invalid")
    worktree = _run_git(root, ("status", "--porcelain", "--untracked-files=all"))
    common_raw = _run_git(
        root, ("rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    common_dir = Path(common_raw).resolve(strict=True)
    source_hash = _file_set_hash(root, IDENTITY_SOURCE_FILES)
    dependency_path = root / "requirements-lock.txt"
    if dependency_path.is_symlink() or not dependency_path.is_file():
        raise RuntimeError("dependency_identity_unavailable")
    dependency_hash = hashlib.sha256(dependency_path.read_bytes()).hexdigest()
    route_contract_hash = _canonical_hash(
        {
            "host_listener": {"host": "127.0.0.1", "port": HOST_PORT},
            "tunnel_target": {"host": "127.0.0.1", "port": PLAYER_PORT},
            "player_auth": "existing-n1-player-security",
            "companion": "stub-only-for-preflight",
        }
    )
    identity_freeze_hash = _canonical_hash(
        {
            "git_sha": git_sha,
            "source_files_sha256": source_hash,
            "dependency_lock_sha256": dependency_hash,
            "route_contract_sha256": route_contract_hash,
            "manifest_sha256": SCENARIO_MANIFEST_SHA256,
        }
    )
    return WorkspaceIdentity(
        git_sha=git_sha,
        worktree_clean=not bool(worktree),
        platform_key=_platform_key(),
        git_common_dir=common_dir,
        source_files_sha256=source_hash,
        dependency_lock_sha256=dependency_hash,
        route_contract_sha256=route_contract_hash,
        identity_freeze_sha256=identity_freeze_hash,
    )


def _identity_record(identity: WorkspaceIdentity) -> dict[str, object]:
    return {
        "git_sha": identity.git_sha,
        "worktree": "clean" if identity.worktree_clean else "dirty",
        "platform": identity.platform_key,
        "source_files_sha256": identity.source_files_sha256,
        "dependency_lock_sha256": identity.dependency_lock_sha256,
        "route_contract_sha256": identity.route_contract_sha256,
        "identity_freeze_sha256": identity.identity_freeze_sha256,
    }


def _redact_text(text: str, secrets: Sequence[str]) -> str:
    selected = text
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 3:
            selected = selected.replace(secret, "[REDACTED]")
    selected = _SENSITIVE_TEXT_PATTERN.sub(lambda match: match.group(1) + "=[REDACTED]", selected)
    selected = _URL_PATTERN.sub("[REDACTED_URL]", selected)
    return selected[:MAX_EVIDENCE_STRING]


def redact_evidence(value: object, secrets: Sequence[str] = (), *, key: str = "") -> object:
    normalized_key = key.lower().replace("-", "_")
    if normalized_key in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for child_key, child_value in list(value.items())[:MAX_EVIDENCE_LIST]:
            safe_key = str(child_key)[:80]
            result[safe_key] = redact_evidence(child_value, secrets, key=safe_key)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_evidence(item, secrets) for item in value[:MAX_EVIDENCE_LIST]]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[OMITTED]"


def write_redacted_evidence(
    path: Path,
    payload: Mapping[str, object],
    secrets: Sequence[str] = (),
) -> bool:
    safe_payload = redact_evidence(payload, secrets)
    if not isinstance(safe_payload, dict):
        return False
    try:
        return safe_write_json(
            str(path),
            safe_payload,
            create_backup=False,
            acquire_lock=False,
            json_kwargs={"ensure_ascii": True, "sort_keys": True, "indent": 2},
        ) is True
    except (OSError, TypeError, ValueError):
        return False


def _safe_capture_tree(source: Path, destination: Path) -> str:
    original_source = Path(os.path.abspath(source))
    if original_source.is_symlink():
        raise RuntimeError("capture_source_symlink_rejected")
    source = original_source.resolve(strict=True)
    if (
        original_source != source
        or not source.is_dir()
        or destination.exists()
        or destination.is_symlink()
    ):
        raise RuntimeError("capture_copy_precondition_failed")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("capture_source_symlink_rejected")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=False)
    return _tree_sha256(destination)


def _tree_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("capture_copy_invalid")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise RuntimeError("capture_copy_symlink_rejected")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("ascii", errors="strict"))
        digest.update(b"\0")
        if path.is_file():
            data = path.read_bytes()
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
        elif path.is_dir():
            digest.update(b"D")
        else:
            raise RuntimeError("capture_copy_entry_invalid")
    return digest.hexdigest()


class SystemPortInspector:
    """Read-only lsof port observations; never probes by binding a socket."""

    def inspect(self, port: int) -> PortObservation:
        if port not in {HOST_PORT, PLAYER_PORT}:
            return PortObservation(port, "unknown")
        try:
            lsof_path = shutil.which(
                "lsof", path="/usr/bin:/bin:/usr/sbin:/sbin"
            )
            if lsof_path is None:
                return PortObservation(port, "unknown")
            result = subprocess.run(
                [lsof_path, "-nP", "-Fpn", "-iTCP:%d" % port, "-sTCP:LISTEN"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5.0,
                check=False,
                shell=False,
                env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return PortObservation(port, "unknown")
        if result.stderr.strip():
            return PortObservation(port, "unknown")
        if result.returncode == 1 and not result.stdout.strip():
            return PortObservation(port, "free")
        if result.returncode != 0:
            return PortObservation(port, "unknown")
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
                if pid > 0:
                    pids.add(pid)
        return PortObservation(port, "occupied" if pids else "unknown", tuple(sorted(pids)))


@dataclass(frozen=True, slots=True)
class LockRequest:
    coordination_dir: Path
    run_id: str
    booking_id: str


class FileLiveWindowLock:
    """Atomic lock adapter matching the existing N2 coordination protocol."""

    def __init__(self, request: LockRequest) -> None:
        self.request = request
        self.lock_dir = request.coordination_dir / "live-window.lock"
        self._acquired = False
        self._recorded = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self, holder_record: Mapping[str, object]) -> bool:
        self.request.coordination_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.request.coordination_dir.is_symlink() or not self.request.coordination_dir.is_dir():
            return False
        try:
            self.lock_dir.mkdir(mode=0o700)
        except FileExistsError:
            return False
        self._acquired = True
        line = json.dumps(
            redact_evidence(holder_record),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        holder = self.lock_dir / "holder.json"
        try:
            with holder.open("x", encoding="ascii") as stream:
                os.chmod(holder, 0o600)
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._append_booking(line)
        except (OSError, TypeError, ValueError):
            return False
        self._recorded = True
        return True

    def release(self, release_record: Mapping[str, object]) -> bool:
        if not self._acquired or not self._recorded:
            return False
        holder_path = self.lock_dir / "holder.json"
        try:
            metadata = os.lstat(holder_path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                return False
            holder = json.loads(holder_path.read_text(encoding="ascii"))
            if holder.get("booking_id") != self.request.booking_id:
                return False
            line = json.dumps(
                redact_evidence(release_record),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            self._append_booking(line)
            holder_path.unlink()
            self.lock_dir.rmdir()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        self._acquired = False
        self._recorded = False
        return True

    def _append_booking(self, line: str) -> None:
        path = self.request.coordination_dir / "bookings.log"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("booking_log_invalid")
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, (line + "\n").encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _lock_factory(
    identity: WorkspaceIdentity,
    run_id: str,
    _sha: str,
    _evidence_dir: Path,
) -> LiveWindowLock:
    return FileLiveWindowLock(
        LockRequest(
            coordination_dir=identity.git_common_dir / "neq-coordination",
            run_id=run_id,
            booking_id="N3-preflight-" + run_id,
        )
    )


class _ProbeRequestHandler(BaseHTTPRequestHandler):
    server_version = "N3Preflight/1"
    sys_version = ""

    def do_GET(self) -> None:
        if self.path != "/__n3_preflight_health":
            self.send_error(404)
            return
        body = json.dumps(
            {"status": "ready", "capture_sha256": self.server.capture_sha256},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class LocalHostHarness:
    """Loopback-only health endpoint used by preflight, not the live N3 gate."""

    def __init__(self, capture_copy: Path, port_inspector: PortInspector) -> None:
        self.capture_copy = capture_copy
        self.port_inspector = port_inspector
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._thread_started = False
        self._copy_sha256 = _tree_sha256(capture_copy)

    @property
    def owner_pid(self) -> int:
        return os.getpid()

    def start(self) -> bool:
        if self._server is not None:
            return False
        handler = _ProbeRequestHandler
        try:
            server = ThreadingHTTPServer(("127.0.0.1", HOST_PORT), handler)
        except OSError:
            return False
        server.daemon_threads = True
        server.capture_sha256 = self._copy_sha256  # type: ignore[attr-defined]
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="n3-preflight-loopback-host",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        try:
            thread.start()
            self._thread_started = True
        except RuntimeError:
            server.server_close()
            self._server = None
            self._thread = None
            self._thread_started = False
            return False
        return self.is_ready()

    def is_ready(self) -> bool:
        if self._server is None or self._thread is None or not self._thread.is_alive():
            return False
        connection: http.client.HTTPConnection | None = None
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", HOST_PORT, timeout=1.0
            )
            connection.request("GET", "/__n3_preflight_health")
            response = connection.getresponse()
            body = json.loads(response.read(2048).decode("ascii"))
            return (
                response.status == 200
                and body.get("status") == "ready"
                and body.get("capture_sha256") == self._copy_sha256
            )
        except (OSError, http.client.HTTPException, UnicodeError, ValueError):
            return False
        finally:
            if connection is not None:
                connection.close()

    def stop(self) -> bool:
        server = self._server
        thread = self._thread
        if server is None:
            return True
        try:
            if self._thread_started:
                server.shutdown()
            server.server_close()
            if thread is not None and self._thread_started:
                thread.join(timeout=2.0)
        except (OSError, RuntimeError):
            return False
        stopped = thread is None or not thread.is_alive()
        if stopped:
            self._server = None
            self._thread = None
            self._thread_started = False
        return stopped


def _host_factory(capture_copy: Path, port_inspector: PortInspector) -> HostHarness:
    return LocalHostHarness(capture_copy, port_inspector)


@dataclass(slots=True)
class _SharedProfileState:
    layout: ProfileLayout
    profile_ready: bool = False
    identity_initialized: bool = False
    credential_present: bool = False
    credential_generation: int = 0
    raw_verifier: str | None = None
    password: str = FAKE_PASSWORD
    identity_calls: int = 0
    issue_calls: int = 0
    rotate_calls: int = 0
    revoke_calls: int = 0
    companion_starts: int = 0
    companion_stops: int = 0
    listener_starts: int = 0
    route_starts: int = 0
    listener_running: bool = False
    route_healthy: bool = False
    gameplay_inputs: int = 0
    session_grant: object | None = None
    pending_challenge: object | None = None


@lru_cache(maxsize=2)
def _fake_verifier(password: str) -> str:
    salt = b"\x00" * 16 if password == FAKE_PASSWORD else b"\x01" * 16
    return make_verifier(password, salt=salt)


class _StubCompanion:
    def __init__(self, state: _SharedProfileState) -> None:
        self._state = state
        self._lifecycle = "stopped"
        self._reaped = True

    @property
    def state(self) -> str:
        return self._lifecycle

    @property
    def reaped(self) -> bool:
        return self._reaped

    def start(self, _deadline: float) -> str:
        self._lifecycle = "running"
        self._reaped = False
        self._state.route_healthy = True
        self._state.route_starts += 1
        self._state.companion_starts += 1
        return "running"

    def stop(self, _deadline: float) -> bool:
        self._lifecycle = "stopped"
        self._reaped = True
        self._state.route_healthy = False
        self._state.companion_stops += 1
        return True

    def diagnostics(self) -> dict[str, object]:
        return {"state": self._lifecycle}

    def simulate_exit(self) -> None:
        self._lifecycle = "exited"
        self._reaped = True
        self._state.route_healthy = False


class PreflightLifecycleHarness:
    """Real service/controller composition with only local injected fakes."""

    def __init__(
        self,
        capture_copy: Path,
        host: HostHarness,
        clock: Callable[[], float],
        shared_state: _SharedProfileState | None = None,
    ) -> None:
        self.capture_copy = capture_copy
        self.host = host
        self.clock = clock
        profile_root = capture_copy / ".n3-preflight-state"
        layout = ProfileLayout(
            profile="neq-n3-preflight",
            state_root=profile_root,
            profile_root=profile_root,
            config_home=profile_root / "config",
            data_home=profile_root / "data",
            state_home=profile_root / "state",
            runtime_dir=profile_root / "run",
            verifier_dir=profile_root / "verifier",
            owner_file=profile_root / "profile_owner.json",
            socket_path=profile_root / "run" / "neq-n3-preflight.sock",
        )
        self.state = shared_state or _SharedProfileState(layout=layout)
        self.security = PlayerSecurity(
            verifier_provider=lambda: self.state.raw_verifier,
            clock=clock,
        )
        self._companions: list[_StubCompanion] = []
        self._controller: SharingController | None = None
        dependencies = SharingServiceDependencies(
            prepare_profile=self._prepare_profile,
            identity_initialized=lambda _layout: self.state.identity_initialized,
            verifier_status=self._verifier_status,
            resolve_companion=self._resolve_companion,
            initialize_identity=self._initialize_identity,
            controller_factory=self._controller_factory,
            issue_credential=self._issue_credential,
            rotate_credential=self._rotate_credential,
            revoke_access=self._revoke_access,
        )
        self.service = PlayerSharingService(dependencies)

    def controller(self) -> SharingController | None:
        return self._controller

    def restart_service(self) -> "PreflightLifecycleHarness":
        return PreflightLifecycleHarness(
            self.capture_copy, self.host, self.clock, shared_state=self.state
        )

    def cleanup(self) -> bool:
        result = self.service.shutdown()
        return bool(
            result.ok
            and result.status.lifecycle.state
            in {SharingState.OFF, SharingState.INITIALIZING_REQUIRED}
            and not self.state.listener_running
            and not self.state.route_healthy
            and all(
                companion.reaped and companion.state in {"stopped", "exited"}
                for companion in self._companions
            )
            and self.security.active_session_count == 0
            and self.security.public_origin_status[0] is False
        )

    def actions(self) -> Mapping[str, Callable[[], Mapping[str, object]]]:
        return {
            "sharing-off-local-play": self._row_sharing_off,
            "identity-bootstrap-once": self._row_identity_once,
            "start-authenticated-entry": self._row_start_authenticated,
            "duplicate-start-idempotent": self._row_duplicate_start,
            "relay-loss-bounded-recovery": self._row_relay_recovery,
            "credential-rotation-revocation": self._row_rotation,
            "explicit-stop": self._row_stop,
            "host-exit-restart-sharing-off": self._row_host_restart,
            "route-session-revocation": self._row_revoke,
            "clean-teardown": self._row_clean_teardown,
        }

    def _prepare_profile(self, create: bool) -> ProfileState:
        if create:
            self.state.profile_ready = True
        if not self.state.profile_ready:
            return ProfileState("absent", "profile_absent")
        return ProfileState("ready", "ready", self.state.layout)

    def _verifier_status(self, _layout: ProfileLayout) -> VerifierStatus:
        return VerifierStatus(
            "present" if self.state.credential_present else "absent",
            "ready" if self.state.credential_present else "verifier_absent",
            generation=self.state.credential_generation or None,
        )

    def _load_verifier(self) -> VerifierLoad:
        if not self.state.credential_present or self.state.raw_verifier is None:
            return VerifierLoad("absent", "verifier_absent")
        return VerifierLoad(
            "present",
            "ready",
            verifier=object(),
            raw_verifier=self.state.raw_verifier,
            generation=self.state.credential_generation,
        )

    def _resolve_companion(self) -> CompanionResolution:
        return CompanionResolution(
            "resolved", "resolved", Path("stubbed-companion"), "0" * 64
        )

    def _initialize_identity(
        self,
        _layout: ProfileLayout,
        _resolution: CompanionResolution,
        facilitator_confirmed: bool,
    ) -> BootstrapResult:
        self.state.identity_calls += 1
        if facilitator_confirmed is not True:
            return BootstrapResult("refused", "facilitator_confirmation_required")
        self.state.identity_initialized = True
        return BootstrapResult("initialized", "identity_initialized")

    def _issue_credential(self, _layout: ProfileLayout) -> IssuedCredential:
        self.state.issue_calls += 1
        self.state.credential_present = True
        self.state.credential_generation = max(1, self.state.credential_generation)
        self.state.password = FAKE_PASSWORD
        self.state.raw_verifier = _fake_verifier(self.state.password)
        return IssuedCredential(FAKE_PLAINTEXT_CREDENTIAL)

    def _rotate_credential(self, _layout: ProfileLayout) -> IssuedCredential:
        self.security.stop_listener()
        self.state.rotate_calls += 1
        self.state.credential_present = True
        self.state.credential_generation += 1
        self.state.password = FAKE_ROTATED_PASSWORD
        self.state.raw_verifier = _fake_verifier(self.state.password)
        self.security.start_listener()
        return IssuedCredential(FAKE_PLAINTEXT_CREDENTIAL)

    def _revoke_access(self, _layout: ProfileLayout) -> VerifierLoad:
        self.security.stop_listener()
        self.state.revoke_calls += 1
        self.state.credential_present = False
        self.state.raw_verifier = None
        self.state.credential_generation += 1
        return VerifierLoad("absent", "verifier_absent")

    def _controller_factory(self, _layout: ProfileLayout) -> SharingController:
        binder = PublicOriginBinder(self.security)

        def start_listener() -> bool:
            if not self.host.is_ready() or not self._capture_copy_is_valid():
                return False
            self.security.start_listener()
            self.state.listener_running = True
            self.state.listener_starts += 1
            return True

        def stop_listener() -> None:
            self.security.stop_listener()
            self.state.listener_running = False

        def start_companion(_generation: int) -> _StubCompanion:
            companion = _StubCompanion(self.state)
            self._companions.append(companion)
            return companion

        def route_status(handle: object, generation: int) -> RouteStatus:
            healthy = bool(
                isinstance(handle, _StubCompanion)
                and handle.state == "running"
                and self.state.route_healthy
            )
            return RouteStatus(healthy, FAKE_ORIGIN if healthy else None, generation)

        dependencies = SharingDependencies(
            local_runtime_ok=self.host.is_ready,
            assets_ok=self._capture_copy_is_valid,
            start_player_listener=start_listener,
            stop_player_listener=stop_listener,
            listener_authenticated_probe=lambda: (
                self.state.listener_running and self.security._active
            ),
            load_verifier=self._load_verifier,
            resolve_companion=self._resolve_companion,
            identity_initialized=lambda: self.state.identity_initialized,
            start_companion=start_companion,
            route_status=route_status,
            origin_binder=binder,
            clock=self.clock,
            sleeper=lambda _seconds: None,
            companion_start_deadline_seconds=1.0,
            companion_stop_deadline_seconds=1.0,
            route_wait_seconds=0.0,
            route_poll_interval_seconds=0.01,
        )
        self._controller = SharingController(dependencies)
        return self._controller

    def _capture_copy_is_valid(self) -> bool:
        try:
            return (
                not self.capture_copy.is_symlink()
                and self.capture_copy.is_dir()
                and (self.capture_copy / "module_context.json").is_file()
                and (self.capture_copy / "areas").is_dir()
            )
        except OSError:
            return False

    def _current_controller(self) -> SharingController | None:
        return self._controller

    def _row_sharing_off(self) -> Mapping[str, object]:
        status = self.service.status()
        return {
            "ok": bool(
                self.host.is_ready()
                and status.lifecycle.state
                in {SharingState.OFF, SharingState.INITIALIZING_REQUIRED}
                and self.state.companion_starts == 0
                and not self.state.listener_running
                and not self.state.route_healthy
            ),
            "host_available": self.host.is_ready(),
            "sharing_state": status.lifecycle.state.value,
            "companion_starts": self.state.companion_starts,
            "listener_running": self.state.listener_running,
        }

    def _row_identity_once(self) -> Mapping[str, object]:
        first = self.service.initialize_identity(facilitator_confirmed=True)
        second = self.service.initialize_identity(facilitator_confirmed=True)
        issued = self.service.issue_access()
        return {
            "ok": bool(
                first.ok
                and second.ok
                and self.state.identity_calls == 1
                and issued.ok
                and self.state.issue_calls == 1
                and self.state.credential_present
            ),
            "identity_calls": self.state.identity_calls,
            "credential_issued": issued.ok,
            "credential_generation": self.state.credential_generation,
        }

    def _row_start_authenticated(self) -> Mapping[str, object]:
        result = self.service.start()
        grant = None
        challenge = self.security.issue_prelogin_challenge()
        if challenge is not None and self.security.verify_password(self.state.password):
            consumed = self.security.consume_prelogin_challenge(
                challenge.cookie_value, challenge.csrf_nonce
            )
            if consumed:
                grant = self.security.create_session()
        self.state.session_grant = grant
        self.state.pending_challenge = self.security.issue_prelogin_challenge()
        session_valid = bool(
            grant is not None
            and self.security.session_context_for_cookie(grant.cookie_value) is not None
            and self.security.csrf_is_valid(grant.cookie_value, grant.csrf_token)
        )
        checks = result.status.lifecycle.checks
        return {
            "ok": bool(
                result.ok
                and result.status.lifecycle.state is SharingState.READY
                and checks.listener_authenticated
                and session_valid
                and self.state.listener_starts >= 1
                and self.state.route_starts >= 1
            ),
            "sharing_state": result.status.lifecycle.state.value,
            "listener_authenticated": checks.listener_authenticated,
            "authenticated_session_valid": session_valid,
            "listener_starts": self.state.listener_starts,
            "route_starts": self.state.route_starts,
            "generation": result.status.lifecycle.generation,
        }

    def _row_duplicate_start(self) -> Mapping[str, object]:
        before = self.state.companion_starts
        before_listener_starts = self.state.listener_starts
        before_route_starts = self.state.route_starts
        first_controller = self._current_controller()
        before_generation = first_controller.generation if first_controller else 0
        result = self.service.start()
        controller = self._current_controller()
        after_generation = controller.generation if controller else 0
        return {
            "ok": bool(
                result.ok
                and result.status.lifecycle.state is SharingState.READY
                and before == self.state.companion_starts
                and before_listener_starts == self.state.listener_starts
                and before_route_starts == self.state.route_starts
                and before_generation == after_generation
            ),
            "companion_starts_before": before,
            "companion_starts_after": self.state.companion_starts,
            "listener_starts_before": before_listener_starts,
            "listener_starts_after": self.state.listener_starts,
            "route_starts_before": before_route_starts,
            "route_starts_after": self.state.route_starts,
            "generation_before": before_generation,
            "generation_after": after_generation,
        }

    def _row_relay_recovery(self) -> Mapping[str, object]:
        controller = self._current_controller()
        if controller is None or not self._companions:
            return {"ok": False, "reason": "controller_unavailable"}
        generation = controller.generation
        self._companions[-1].simulate_exit()
        degraded = controller.mark_degraded(
            "route_unhealthy",
            expected_generation=generation,
            expected_state=SharingState.READY,
        )
        invitation_withdrawn = self.service.copy_invitation().ok is False
        recovered = controller.recover()
        return {
            "ok": bool(
                degraded.state is SharingState.DEGRADED
                and invitation_withdrawn
                and recovered.state is SharingState.READY
                and recovered.generation == generation
                and self.state.gameplay_inputs == 0
            ),
            "degraded_state": degraded.state.value,
            "invitation_withdrawn": invitation_withdrawn,
            "recovered_state": recovered.state.value,
            "generation_preserved": recovered.generation == generation,
            "gameplay_inputs": self.state.gameplay_inputs,
        }

    def _row_rotation(self) -> Mapping[str, object]:
        old_grant = self.state.session_grant
        old_cookie = getattr(old_grant, "cookie_value", None)
        pending_challenge = self.state.pending_challenge
        pending_challenge_revoked = True
        rotate_calls_before = self.state.rotate_calls
        result = self.service.rotate_access()
        if pending_challenge is not None:
            pending_challenge_revoked = not self.security.consume_prelogin_challenge(
                getattr(pending_challenge, "cookie_value", None),
                getattr(pending_challenge, "csrf_nonce", None),
            )
        old_session_revoked = (
            old_cookie is None
            or self.security.session_context_for_cookie(old_cookie) is None
        )
        old_csrf_revoked = (
            old_cookie is None
            or not self.security.csrf_is_valid(
                old_cookie, getattr(old_grant, "csrf_token", None)
            )
        )
        origin_bound, bound_generation = self.security.public_origin_status
        return {
            "ok": bool(
                result.ok
                and self.state.rotate_calls == rotate_calls_before + 1
                and old_session_revoked
                and pending_challenge_revoked
                and old_csrf_revoked
                and self.state.credential_generation >= 2
                and origin_bound
                and bound_generation == result.status.lifecycle.generation
            ),
            "rotation_succeeded": result.ok,
            "rotation_calls": self.state.rotate_calls - rotate_calls_before,
            "old_session_revoked": old_session_revoked,
            "old_challenge_revoked": pending_challenge_revoked,
            "old_csrf_revoked": old_csrf_revoked,
            "new_origin_bound": origin_bound,
            "credential_generation": self.state.credential_generation,
        }

    def _row_stop(self) -> Mapping[str, object]:
        companion_stops_before = self.state.companion_stops
        result = self.service.stop()
        controller = self._current_controller()
        origin_bound = self.security.public_origin_status[0]
        return {
            "ok": bool(
                result.ok
                and result.status.lifecycle.state is SharingState.OFF
                and not origin_bound
                and not self.state.listener_running
                and not self.state.route_healthy
                and self.state.companion_stops == companion_stops_before + 1
                and (controller is None or controller.status().state is SharingState.OFF)
            ),
            "sharing_state": result.status.lifecycle.state.value,
            "origin_bound": origin_bound,
            "listener_running": self.state.listener_running,
            "route_healthy": self.state.route_healthy,
            "companion_stops": self.state.companion_stops - companion_stops_before,
        }

    def _row_host_restart(self) -> Mapping[str, object]:
        old_service = self.service
        before_starts = self.state.companion_starts
        shutdown = old_service.shutdown()
        host_stopped = self.host.stop()
        host_started = self.host.start()
        restarted = self.restart_service()
        self._restarted_service = restarted
        status = restarted.service.status()
        return {
            "ok": bool(
                shutdown.ok
                and host_stopped
                and host_started
                and self.host.is_ready()
                and status.lifecycle.state is SharingState.OFF
                and self.state.companion_starts == before_starts
                and not self.state.listener_running
                and not self.state.route_healthy
            ),
            "restart_sharing_state": status.lifecycle.state.value,
            "host_stopped": host_stopped,
            "host_restarted": host_started,
            "automatic_starts": self.state.companion_starts - before_starts,
            "listener_running": self.state.listener_running,
            "route_healthy": self.state.route_healthy,
        }

    def _row_revoke(self) -> Mapping[str, object]:
        restarted = getattr(self, "_restarted_service", None)
        if not isinstance(restarted, PreflightLifecycleHarness):
            restarted = self.restart_service()
            self._restarted_service = restarted
        start = restarted.service.start()
        grant = restarted.security.create_session() if start.ok else None
        revoke_calls_before = restarted.state.revoke_calls
        result = restarted.service.revoke_access()
        status = restarted.service.status()
        route_clear = not restarted.state.route_healthy
        session_clear = (
            grant is None
            or restarted.security.session_context_for_cookie(grant.cookie_value) is None
        )
        return {
            "ok": bool(
                start.ok
                and result.ok
                and restarted.state.revoke_calls == revoke_calls_before + 1
                and status.credential_state == "absent"
                and route_clear
                and session_clear
                and not restarted.security.public_origin_status[0]
            ),
            "revocation_succeeded": result.ok,
            "revocation_calls": restarted.state.revoke_calls - revoke_calls_before,
            "credential_absent": status.credential_state == "absent",
            "route_removed": route_clear,
            "session_revoked": session_clear,
            "origin_bound": restarted.security.public_origin_status[0],
        }

    def _row_clean_teardown(self) -> Mapping[str, object]:
        restarted = getattr(self, "_restarted_service", self)
        clean = restarted.cleanup()
        return {
            "ok": clean,
            "listener_running": restarted.state.listener_running,
            "route_healthy": restarted.state.route_healthy,
            "active_sessions": restarted.security.active_session_count,
            "origin_bound": restarted.security.public_origin_status[0],
        }


def _lifecycle_factory(
    capture_copy: Path,
    host: HostHarness,
    clock: Callable[[], float],
) -> LifecycleHarness:
    return PreflightLifecycleHarness(capture_copy, host, clock)


def _port_is_free(observation: PortObservation, port: int) -> bool:
    return observation.port == port and observation.state == "free" and not observation.pids


def _port_is_owned_by(observation: PortObservation, port: int, owner_pid: int) -> bool:
    return (
        observation.port == port
        and observation.state == "occupied"
        and observation.pids == (owner_pid,)
    )


def _inspect_ports(
    inspector: PortInspector,
    ports: Sequence[int],
    *,
    expected_owner: tuple[int, int] | None = None,
) -> tuple[bool, list[dict[str, object]], list[str]]:
    observations: list[dict[str, object]] = []
    failures: list[str] = []
    for port in ports:
        try:
            observation = inspector.inspect(port)
        except Exception:
            observation = PortObservation(port, "unknown")
        if expected_owner is not None and port == expected_owner[0]:
            okay = _port_is_owned_by(observation, port, expected_owner[1])
            check = "owned_by_preflight_host" if okay else "host_owner_mismatch"
        else:
            okay = _port_is_free(observation, port)
            check = "free" if okay else "occupied_or_unknown"
        if not okay:
            failures.append("port_%d_%s" % (port, check))
        observations.append(
            {"port": port, "check": check, "pids": list(observation.pids)}
        )
    return not failures, observations, failures


def _coverage_valid(
    declared_rows: Sequence[LifecycleRow],
    actions: Mapping[str, Callable[[], Mapping[str, object]]],
) -> tuple[bool, list[str]]:
    if tuple(declared_rows) != SCENARIO_ROWS:
        return False, ["scenario_manifest_mismatch"]
    expected_ids = [row.row_id for row in declared_rows]
    actual_ids = list(actions)
    missing = [row_id for row_id in expected_ids if row_id not in actions]
    extra = [row_id for row_id in actual_ids if row_id not in expected_ids]
    duplicates = sorted({row_id for row_id in actual_ids if actual_ids.count(row_id) > 1})
    declared_duplicates = sorted(
        {row_id for row_id in expected_ids if expected_ids.count(row_id) > 1}
    )
    if missing:
        return False, ["missing_row:" + row_id for row_id in missing]
    if extra:
        return False, ["unexpected_row:" + row_id for row_id in extra]
    if duplicates:
        return False, ["duplicate_row:" + row_id for row_id in duplicates]
    if declared_duplicates:
        return False, ["duplicate_manifest_row:" + row_id for row_id in declared_duplicates]
    return True, []


def exercise_lifecycle_rows(
    harness: LifecycleHarness | None,
    *,
    clock: Callable[[], float],
    caps: GateCaps = FROZEN_CAPS,
    declared_rows: Sequence[LifecycleRow] = SCENARIO_ROWS,
    actions: Mapping[str, Callable[[], Mapping[str, object]]] | None = None,
    run_started_at: float | None = None,
) -> dict[str, object]:
    selected_actions = (
        actions
        if actions is not None
        else harness.actions()
        if harness is not None
        else {}
    )
    coverage_ok, coverage_failures = _coverage_valid(declared_rows, selected_actions)
    records: list[dict[str, object]] = []
    if not coverage_ok:
        for row in declared_rows:
            records.append(
                {
                    "row_id": row.row_id,
                    "expected": row.expected,
                    "observed": {"reason": "row_manifest_incomplete"},
                    "verdict": "BLOCKED",
                }
            )
        return {
            "rows": records,
            "attempts": 0,
            "infrastructure_failures": coverage_failures,
            "semantic_failures": [],
        }

    try:
        started = float(clock()) if run_started_at is None else float(run_started_at)
    except Exception:
        started = 0.0
        coverage_failures = ["clock_unavailable"]
    attempts = 0
    attempts_by_row: dict[str, int] = {}
    infrastructure_failures: list[str] = list(coverage_failures)
    semantic_failures: list[str] = []
    stopped = bool(coverage_failures)

    for index, row in enumerate(declared_rows):
        if stopped:
            records.append(
                {
                    "row_id": row.row_id,
                    "expected": row.expected,
                    "observed": {"reason": "fail_fast"},
                    "verdict": "BLOCKED",
                }
            )
            continue
        try:
            elapsed = float(clock()) - started
        except Exception:
            elapsed = caps.max_run_seconds + 1
        if elapsed > caps.max_run_seconds:
            infrastructure_failures.append("run_time_cap_exceeded")
            stopped = True
            records.append(
                {
                    "row_id": row.row_id,
                    "expected": row.expected,
                    "observed": {"reason": "run_time_cap_exceeded"},
                    "verdict": "BLOCKED",
                }
            )
            continue
        if attempts >= caps.max_attempts or attempts >= caps.max_rows:
            infrastructure_failures.append("attempt_cap_exceeded")
            stopped = True
            records.append(
                {
                    "row_id": row.row_id,
                    "expected": row.expected,
                    "observed": {"reason": "attempt_cap_exceeded"},
                    "verdict": "BLOCKED",
                }
            )
            continue
        if attempts_by_row.get(row.row_id, 0) >= caps.max_attempts_per_row:
            infrastructure_failures.append("row_attempt_cap_exceeded:" + row.row_id)
            stopped = True
            records.append(
                {
                    "row_id": row.row_id,
                    "expected": row.expected,
                    "observed": {"reason": "row_attempt_cap_exceeded"},
                    "verdict": "BLOCKED",
                }
            )
            continue
        attempts += 1
        attempts_by_row[row.row_id] = attempts_by_row.get(row.row_id, 0) + 1
        try:
            row_started = float(clock())
            observed = selected_actions[row.row_id]()
            row_elapsed = float(clock()) - row_started
        except Exception:
            observed = {"ok": False, "reason": "row_execution_failed"}
            row_elapsed = 0.0
        row_ok = observed.get("ok") is True
        cap_failure: str | None = None
        if row_elapsed > caps.max_row_seconds:
            infrastructure_failures.append("row_time_cap_exceeded:" + row.row_id)
            cap_failure = "row_time_cap_exceeded"
        try:
            elapsed_after_row = float(clock()) - started
        except Exception:
            elapsed_after_row = caps.max_run_seconds + 1
        if elapsed_after_row > caps.max_run_seconds:
            if "run_time_cap_exceeded" not in infrastructure_failures:
                infrastructure_failures.append("run_time_cap_exceeded")
            cap_failure = "run_time_cap_exceeded"
        if cap_failure is not None:
            row_ok = False
            observed = {"reason": cap_failure}
        record = {
            "row_id": row.row_id,
            "expected": row.expected,
            "observed": dict(observed),
            "elapsed_seconds": max(0.0, round(row_elapsed, 3)),
            "verdict": (
                "BLOCKED" if cap_failure is not None else "PASS" if row_ok else "FAIL"
            ),
        }
        records.append(record)
        if not row_ok:
            if not infrastructure_failures:
                semantic_failures.append("row_assertion_failed:" + row.row_id)
            stopped = True
            for pending in declared_rows[index + 1 :]:
                records.append(
                    {
                        "row_id": pending.row_id,
                        "expected": pending.expected,
                        "observed": {"reason": "fail_fast"},
                        "verdict": "BLOCKED",
                    }
                )
            break

    return {
        "rows": records,
        "attempts": attempts,
        "infrastructure_failures": infrastructure_failures,
        "semantic_failures": semantic_failures,
    }


class _ProbeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _lock_release_allowed(ports_free: bool) -> bool:
    return ports_free is True


def _run_fault_injection_checks() -> dict[str, dict[str, object]]:
    row_actions: dict[str, Callable[[], Mapping[str, object]]] = {
        row.row_id: (lambda: {"ok": True}) for row in SCENARIO_ROWS
    }
    missing_actions = dict(row_actions)
    missing_actions.pop(SCENARIO_ROWS[-1].row_id)
    missing = exercise_lifecycle_rows(
        None,
        clock=_ProbeClock(),
        actions=missing_actions,
    )
    missing_passed = bool(
        missing["attempts"] == 0
        and any(
            item.startswith("missing_row:")
            for item in missing["infrastructure_failures"]
        )
        and all(row["verdict"] == "BLOCKED" for row in missing["rows"])
    )

    attempt_cap = exercise_lifecycle_rows(
        None,
        clock=_ProbeClock(),
        caps=GateCaps(max_attempts=9),
        actions=row_actions,
    )
    attempt_cap_passed = bool(
        attempt_cap["attempts"] == 9
        and "attempt_cap_exceeded" in attempt_cap["infrastructure_failures"]
        and attempt_cap["rows"][-1]["verdict"] == "BLOCKED"
    )

    time_clock = _ProbeClock()
    timed_actions = dict(row_actions)

    def exceed_run_cap() -> Mapping[str, object]:
        time_clock.advance(2.0)
        return {"ok": True}

    timed_actions[SCENARIO_ROWS[0].row_id] = exceed_run_cap
    time_cap = exercise_lifecycle_rows(
        None,
        clock=time_clock,
        caps=GateCaps(max_run_seconds=1, max_row_seconds=10),
        actions=timed_actions,
    )
    time_cap_passed = bool(
        time_cap["attempts"] == 1
        and "run_time_cap_exceeded" in time_cap["infrastructure_failures"]
        and all(row["verdict"] == "BLOCKED" for row in time_cap["rows"][1:])
    )

    return {
        "missing_row_fail_fast": {
            "expected": "BLOCKED before row dispatch",
            "observed": "BLOCKED" if missing_passed else "FAILED",
            "passed": missing_passed,
        },
        "attempt_cap_fail_fast": {
            "expected": "stop before attempt 10",
            "observed": "stopped at attempt 9" if attempt_cap_passed else "FAILED",
            "passed": attempt_cap_passed,
        },
        "time_cap_fail_fast": {
            "expected": "stop after run cap and block remaining rows",
            "observed": "remaining rows BLOCKED" if time_cap_passed else "FAILED",
            "passed": time_cap_passed,
        },
        "teardown_failure_retains_lock": {
            "expected": "do not release lock while ports are occupied or unknown",
            "observed": "retained" if not _lock_release_allowed(False) else "FAILED",
            "passed": not _lock_release_allowed(False),
        },
    }


def _initial_report(
    *,
    run_id: str,
    expected_sha: str,
    command: Sequence[str],
    cwd: str,
    pythonpath: str,
    dry_run: bool,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "gate": "N3-provider-free-preflight",
        "run_id": run_id,
        "created_at": _utc_now(),
        "invocation": {
            "command": list(command),
            "cwd": cwd,
            "pythonpath": pythonpath,
            "python_dont_write_bytecode": os.environ.get(
                "PYTHONDONTWRITEBYTECODE", ""
            ),
            "expected_sha": expected_sha,
        },
        "manifest": {
            "sha256": SCENARIO_MANIFEST_SHA256,
            "row_ids": [row.row_id for row in SCENARIO_ROWS],
            "frozen_caps": asdict(FROZEN_CAPS),
            "approved_platforms": list(APPROVED_PLATFORMS),
        },
        "preflight_mode": "dry-run" if dry_run else "provider-free",
        "preflight_verdict": "NOT_RUN" if dry_run else "PENDING",
        "gate_verdict": "PENDING",
        "is_gate_pass": False,
        "rows": [],
        "attempts": 0,
        "providers_called": 0,
        "relay_connections": 0,
        "infrastructure_failures": [],
        "semantic_failures": [],
        "ports": {"host": HOST_PORT, "player": PLAYER_PORT},
        "teardown": {"required": not dry_run, "complete": False},
    }


def _check_run_inputs(
    root: Path,
    *,
    run_id: str,
    expected_sha: str,
    cwd: str,
    pythonpath: str,
    identity: WorkspaceIdentity,
) -> list[str]:
    failures: list[str] = []
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        failures.append("run_id_invalid")
    if SHA_PATTERN.fullmatch(expected_sha) is None:
        failures.append("expected_sha_invalid")
    if identity.git_sha != expected_sha:
        failures.append("git_sha_mismatch")
    if not identity.worktree_clean:
        failures.append("worktree_dirty")
    if identity.platform_key not in APPROVED_PLATFORMS:
        failures.append("unsupported_platform")
    try:
        if Path(cwd).resolve(strict=True) != root.resolve(strict=True):
            failures.append("cwd_mismatch")
    except (OSError, RuntimeError):
        failures.append("cwd_unavailable")
    if pythonpath != ".":
        failures.append("pythonpath_mismatch")
    if not verify_frozen_manifest():
        failures.append("manifest_digest_mismatch")
    return failures


def _create_evidence_directory(root: Path, run_id: str) -> tuple[Path | None, str | None]:
    if root.is_symlink() or not root.is_dir():
        return None, "evidence_root_invalid"
    base = root / EVIDENCE_BASE
    cursor = root
    for component in EVIDENCE_BASE.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            return None, "evidence_path_symlink_rejected"
    run_root = base / run_id
    if run_root.exists() or run_root.is_symlink():
        return None, "evidence_run_path_already_exists"
    evidence_dir = run_root / "preflight"
    try:
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        run_root.mkdir(mode=0o700, exist_ok=False)
        evidence_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        return None, "evidence_run_path_already_exists"
    except OSError:
        return None, "evidence_path_unavailable"
    return evidence_dir, None


def _preflight_holder_record(
    run_id: str,
    sha: str,
    evidence_dir: Path,
    now: str,
) -> dict[str, object]:
    try:
        start = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except ValueError:
        start = datetime.now(timezone.utc)
        now = start.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    window_end = (
        start + timedelta(seconds=FROZEN_CAPS.max_run_seconds)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "booking_id": "N3-preflight-" + run_id,
        "holder": "primary-orchestrator provider-free preflight",
        "gate": "N3-preflight",
        "git_sha": sha,
        "window_start": now,
        "window_end": window_end,
        "window_end_cap_seconds": FROZEN_CAPS.max_run_seconds,
        "frozen_caps": asdict(FROZEN_CAPS),
        "evidence_path": evidence_dir.as_posix(),
    }


def run_preflight(
    dependencies: PreflightDependencies,
    *,
    run_id: str,
    expected_sha: str,
    command: Sequence[str],
    cwd: str,
    pythonpath: str,
    dry_run: bool = False,
    caps: GateCaps = FROZEN_CAPS,
) -> dict[str, object]:
    report = _initial_report(
        run_id=run_id,
        expected_sha=expected_sha,
        command=command,
        cwd=cwd,
        pythonpath=pythonpath,
        dry_run=dry_run,
    )
    report["effective_caps"] = asdict(caps)
    report["caps_match_manifest"] = caps == FROZEN_CAPS
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        report["preflight_verdict"] = "BLOCKED"
        report["infrastructure_failures"] = ["run_id_invalid"]
        return report
    try:
        identity = dependencies.identity_reader(dependencies.root)
    except Exception:
        report["preflight_verdict"] = "BLOCKED"
        report["infrastructure_failures"] = ["workspace_identity_unavailable"]
        return report
    report["identity"] = _identity_record(identity)
    identity_failures = _check_run_inputs(
        dependencies.root,
        run_id=run_id,
        expected_sha=expected_sha,
        cwd=cwd,
        pythonpath=pythonpath,
        identity=identity,
    )
    if dry_run:
        if caps != FROZEN_CAPS:
            identity_failures.append("caps_manifest_mismatch")
        report["preflight_verdict"] = "NOT_RUN"
        report["dry_run"] = {
            "side_effects": False,
            "lock_acquired": False,
            "ports_probed": False,
            "capture_copy_created": False,
            "host_started": False,
        }
        report["preflight_eligibility"] = (
            "eligible" if not identity_failures else "blocked"
        )
        report["infrastructure_failures"] = identity_failures
        return report

    evidence_dir = dependencies.root / EVIDENCE_BASE / run_id / "preflight"
    capture_copy = evidence_dir / "capture_arena_copy"
    report["evidence_path"] = evidence_dir.relative_to(dependencies.root).as_posix()
    created_evidence_dir, path_error = _create_evidence_directory(
        dependencies.root, run_id
    )
    if created_evidence_dir is None:
        report["preflight_verdict"] = "BLOCKED"
        report["infrastructure_failures"] = [path_error or "evidence_path_unavailable"]
        return report
    evidence_dir = created_evidence_dir
    capture_copy = evidence_dir / "capture_arena_copy"

    infrastructure_failures: list[str] = list(identity_failures)
    semantic_failures: list[str] = []
    rows: list[dict[str, object]] = []
    lock: LiveWindowLock | None = None
    lock_acquired = False
    host: HostHarness | None = None
    lifecycle: LifecycleHarness | None = None
    capture_created = False
    host_started = False
    host_stopped = True
    service_stopped = True
    capture_removed = True
    ports_free_after = False
    lock_released = False
    port_records: list[dict[str, object]] = []
    capture_sha256: str | None = None
    try:
        started_at = float(dependencies.clock())
        clock_available = True
    except Exception:
        started_at = 0.0
        clock_available = False
    fault_checks = _run_fault_injection_checks()
    if not all(check["passed"] is True for check in fault_checks.values()):
        add_failure = "preflight_fault_injection_check_failed"
        if add_failure not in infrastructure_failures:
            infrastructure_failures.append(add_failure)

    def add_infrastructure(code: str) -> None:
        if code not in infrastructure_failures:
            infrastructure_failures.append(code)

    def run_cap_available() -> bool:
        try:
            elapsed = float(dependencies.clock()) - started_at
        except Exception:
            add_infrastructure("clock_unavailable")
            return False
        if elapsed > caps.max_run_seconds:
            add_infrastructure("run_time_cap_exceeded")
            return False
        return True

    if not clock_available:
        add_infrastructure("clock_unavailable")
    if identity_failures:
        add_infrastructure("preflight_identity_invalid")
    if not infrastructure_failures and run_cap_available():
        free, observations, failures = _inspect_ports(
            dependencies.port_inspector, (HOST_PORT, PLAYER_PORT)
        )
        port_records.extend(observations)
        if not free:
            for failure in failures:
                add_infrastructure("initial_" + failure)
    if not infrastructure_failures and run_cap_available():
        try:
            lock = dependencies.lock_factory(
                identity, run_id, expected_sha, evidence_dir
            )
            lock_record = _preflight_holder_record(
                run_id, expected_sha, evidence_dir, dependencies.utc_now()
            )
            lock_acquired = lock.acquire(lock_record)
        except Exception:
            lock_acquired = False
        if not lock_acquired:
            add_infrastructure("live_window_lock_unavailable")
    if lock_acquired:
        report["lock"] = {"acquired": True, "protocol": "git-common-dir/live-window.lock"}
    else:
        report["lock"] = {"acquired": False, "protocol": "git-common-dir/live-window.lock"}

    if not infrastructure_failures and run_cap_available():
        free, observations, failures = _inspect_ports(
            dependencies.port_inspector, (HOST_PORT, PLAYER_PORT)
        )
        port_records.extend(observations)
        if not free:
            for failure in failures:
                add_infrastructure("post_lock_" + failure)

    if not infrastructure_failures and run_cap_available():
        source = dependencies.root / CAPTURE_SOURCE_RELATIVE
        try:
            capture_sha256 = dependencies.capture_copier(source, capture_copy)
            capture_created = True
            report["capture_copy"] = {
                "source": CAPTURE_SOURCE_RELATIVE.as_posix(),
                "destination": capture_copy.relative_to(dependencies.root).as_posix(),
                "tree_sha256": capture_sha256,
            }
        except Exception:
            capture_created = capture_copy.exists() or capture_copy.is_symlink()
            add_infrastructure("capture_copy_failed")

    if not infrastructure_failures and run_cap_available():
        try:
            host = dependencies.host_factory(capture_copy, dependencies.port_inspector)
            host_started = host.start() is True
        except Exception:
            host_started = False
        if not host_started:
            add_infrastructure("preflight_host_start_failed")

    if host_started and host is not None:
        try:
            expected_host_pid = host.owner_pid
        except Exception:
            expected_host_pid = -1
            add_infrastructure("preflight_host_owner_unavailable")
        owned, observations, failures = _inspect_ports(
            dependencies.port_inspector,
            (HOST_PORT, PLAYER_PORT),
            expected_owner=(HOST_PORT, expected_host_pid),
        )
        port_records.extend(observations)
        host_record: dict[str, object] = {
            "expected_owner_pid": expected_host_pid if expected_host_pid > 0 else None,
            "ready": False,
        }
        report["preflight_host"] = host_record
        if not owned:
            for failure in failures:
                add_infrastructure("host_ownership_" + failure)
        try:
            host_ready = host.is_ready()
        except Exception:
            host_ready = False
        host_record["ready"] = host_ready
        if not host_ready:
            add_infrastructure("preflight_host_probe_failed")

    if not infrastructure_failures and host is not None and run_cap_available():
        try:
            lifecycle = dependencies.lifecycle_factory(
                capture_copy, host, dependencies.clock
            )
            actions = (
                dependencies.lifecycle_actions_factory(lifecycle)
                if dependencies.lifecycle_actions_factory is not None
                else lifecycle.actions()
            )
            matrix = exercise_lifecycle_rows(
                lifecycle,
                clock=dependencies.clock,
                caps=caps,
                actions=actions,
                run_started_at=started_at,
            )
            rows = list(matrix["rows"])
            infrastructure_failures.extend(
                item
                for item in matrix["infrastructure_failures"]
                if item not in infrastructure_failures
            )
            semantic_failures.extend(
                item
                for item in matrix["semantic_failures"]
                if item not in semantic_failures
            )
            report["attempts"] = matrix["attempts"]
        except Exception:
            add_infrastructure("lifecycle_harness_failed")

    if lifecycle is not None:
        try:
            service_stopped = lifecycle.cleanup()
        except Exception:
            service_stopped = False
        if not service_stopped:
            add_infrastructure("service_teardown_failed")
    if host is not None:
        try:
            host_stopped = host.stop() is True
        except Exception:
            host_stopped = False
        if not host_stopped:
            add_infrastructure("host_teardown_failed")
    if capture_created:
        try:
            if capture_copy.is_symlink() or capture_copy.parent != evidence_dir:
                capture_removed = False
            else:
                shutil.rmtree(capture_copy)
                capture_removed = not capture_copy.exists()
        except OSError:
            capture_removed = False
        if not capture_removed:
            add_infrastructure("capture_copy_teardown_failed")

    try:
        ports_free_after, observations, failures = _inspect_ports(
            dependencies.port_inspector, (HOST_PORT, PLAYER_PORT)
        )
    except Exception:
        ports_free_after, observations, failures = False, [], ["port_probe_failed"]
    port_records.extend(observations)
    if not ports_free_after:
        for failure in failures:
            add_infrastructure("teardown_" + failure)

    if lock is not None and lock.acquired:
        if _lock_release_allowed(ports_free_after):
            try:
                lock_released = lock.release(
                    {
                        "event": "release",
                        "booking_id": "N3-preflight-" + run_id,
                        "released_at": dependencies.utc_now(),
                        "evidence_path": evidence_dir.relative_to(
                            dependencies.root
                        ).as_posix(),
                        "git_sha": expected_sha,
                    }
                )
            except Exception:
                lock_released = False
        if not lock_released:
            add_infrastructure("live_window_lock_release_failed")

    try:
        elapsed_total = max(0.0, float(dependencies.clock()) - float(started_at))
    except Exception:
        elapsed_total = float(caps.max_run_seconds) + 1
    if elapsed_total > caps.max_run_seconds:
        add_infrastructure("run_time_cap_exceeded")
    if caps != FROZEN_CAPS:
        add_infrastructure("caps_manifest_mismatch")
    rows_complete = (
        len(rows) == len(SCENARIO_ROWS)
        and [row.get("row_id") for row in rows]
        == [row.row_id for row in SCENARIO_ROWS]
        and all(row.get("verdict") == "PASS" for row in rows)
    )
    teardown_complete = bool(
        service_stopped
        and host_stopped
        and capture_removed
        and ports_free_after
        and (not lock_acquired or lock_released)
    )
    report.update(
        {
            "created_at": dependencies.utc_now(),
            "capture_copy_sha256": capture_sha256,
            "rows": rows,
            "row_coverage_complete": rows_complete,
            "port_observations": port_records,
            "elapsed_seconds": round(elapsed_total, 3),
            "infrastructure_failures": infrastructure_failures,
            "semantic_failures": semantic_failures,
            "fault_checks": fault_checks,
            "teardown": {
                "service_stopped": service_stopped,
                "host_stopped": host_stopped,
                "capture_copy_removed": capture_removed,
                "ports_free": ports_free_after,
                "lock_released": lock_released,
                "complete": teardown_complete,
            },
        }
    )
    if not rows_complete and not infrastructure_failures and not semantic_failures:
        infrastructure_failures.append("required_row_evidence_incomplete")
        report["infrastructure_failures"] = infrastructure_failures
    if infrastructure_failures:
        report["preflight_verdict"] = "BLOCKED"
    elif semantic_failures or not rows_complete or not teardown_complete:
        report["preflight_verdict"] = "FAIL"
    else:
        report["preflight_verdict"] = "READY_FOR_PRIMARY_REVIEW"
    report["gate_verdict"] = "PENDING"
    report["is_gate_pass"] = False
    report["provider_attempt_budget_used"] = 0
    report["relay_attempt_budget_used"] = 0

    evidence_secrets = (
        FAKE_PASSWORD,
        FAKE_ROTATED_PASSWORD,
        FAKE_PLAINTEXT_CREDENTIAL,
        _fake_verifier(FAKE_PASSWORD),
        _fake_verifier(FAKE_ROTATED_PASSWORD),
    )
    if not dependencies.evidence_writer(
        evidence_dir / "preflight.json", report, evidence_secrets
    ):
        report["preflight_verdict"] = "BLOCKED"
        infrastructure_failures.append("evidence_write_failed")
        report["infrastructure_failures"] = infrastructure_failures
    return report


def _default_dependencies(root: Path) -> PreflightDependencies:
    return PreflightDependencies(
        root=root,
        identity_reader=read_workspace_identity,
        port_inspector=SystemPortInspector(),
        lock_factory=_lock_factory,
        capture_copier=_safe_capture_tree,
        host_factory=_host_factory,
        lifecycle_factory=_lifecycle_factory,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run only the provider-free N3 preflight; the live gate is primary-owned."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    preflight = subparsers.add_parser(
        "preflight", help="run provider-free N3 lifecycle preflight"
    )
    preflight.add_argument("--run-id", required=True, help="frozen unique N3 run ID")
    preflight.add_argument("--sha", required=True, help="exact 40- or 64-character git SHA")
    preflight.add_argument(
        "--dry-run",
        action="store_true",
        help="print the frozen plan without locks, ports, copies, hosts, or evidence writes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.operation != "preflight":
        parser.error("unsupported operation")
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        parser.error("--run-id must match n3-[a-z0-9][a-z0-9-]{0,62}")
    root = REPO_ROOT
    command = [sys.executable, *sys.argv]
    dependencies = _default_dependencies(root)
    report = run_preflight(
        dependencies,
        run_id=args.run_id,
        expected_sha=args.sha,
        command=command,
        cwd=os.getcwd(),
        pythonpath=os.environ.get("PYTHONPATH", ""),
        dry_run=args.dry_run,
    )
    print(
        json.dumps(
            {
                "run_id": report["run_id"],
                "preflight_verdict": report["preflight_verdict"],
                "gate_verdict": report["gate_verdict"],
                "manifest_sha256": SCENARIO_MANIFEST_SHA256,
                "evidence_path": report.get("evidence_path"),
                "infrastructure_failures": report.get("infrastructure_failures", []),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    if args.dry_run:
        return 0
    if report["preflight_verdict"] == "READY_FOR_PRIMARY_REVIEW":
        return 0
    if report["preflight_verdict"] == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
