# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Explicit, pinned, install-relative OpenTunnel companion installer."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import platform
import re
import shutil
import ssl
import stat
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Literal
from urllib.parse import urlsplit

from scripts.network_packaging.manifest import (
    PlatformPin,
    PinnedManifest,
    UPSTREAM_RELEASE_URL,
    load_pinned_manifest,
)
from web.extensions.opentunnel_sharing.companion import (
    resolve_companion,
    verify_companion_digest,
)

MAX_DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_SHA256SUMS_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXTRACTED_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 128
DOWNLOAD_CHUNK_BYTES = 64 * 1024
INSTALL_VERSION = "v0.6.2"
MAX_REDIRECTS = 3
_REDIRECT_HOST_ALLOWLIST = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)
_SENSITIVE_REQUEST_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)
_SUPPORTED_PLATFORM_KEYS = frozenset({"darwin-arm64", "linux-arm64"})
_PLATFORM_ASSETS = {
    "darwin-arm64": ("opentunnel-darwin-arm64.tar.gz", "opentunnel-darwin-arm64"),
    "linux-arm64": ("opentunnel-linux-arm64.tar.gz", "opentunnel-linux-arm64"),
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SUMS_LINE_RE = re.compile(r"\s*([0-9a-fA-F]{64})\s+\*?([^\s]+)\s*\Z")

InstallReason = Literal[
    "installed",
    "already_installed",
    "unsupported_platform",
    "download_failed",
    "checksum_mismatch",
    "sums_mismatch",
    "unsafe_archive",
    "executable_mismatch",
    "install_failed",
    "rolled_back",
]


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Bounded installer outcome; no raw errors, paths, or URLs are exposed."""

    reason: InstallReason
    platform_key: str | None = None


class DownloadSecurityError(ValueError):
    """Raised when a download URL violates the pinned HTTPS host boundary."""


class _InstallFailure(Exception):
    def __init__(self, reason: InstallReason) -> None:
        super().__init__(reason)
        self.reason = reason


class _ReleaseRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow a short HTTPS redirect chain on the frozen GitHub asset hosts."""

    def __init__(self) -> None:
        super().__init__()
        self.max_redirections = MAX_REDIRECTS
        self.max_repeats = 1

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request:
        _validate_redirect_url(newurl)
        redirect_count = getattr(req, "_neq_redirect_count", 0)
        visited_urls = getattr(req, "_neq_redirect_visited", (req.full_url,))
        if redirect_count >= MAX_REDIRECTS or newurl in visited_urls:
            raise DownloadSecurityError("redirect chain is repeated or too long")

        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            raise DownloadSecurityError("redirect request could not be created")
        redirected._neq_redirect_count = redirect_count + 1
        redirected._neq_redirect_visited = visited_urls + (newurl,)
        _remove_sensitive_headers(redirected)
        if _has_sensitive_headers(redirected):
            raise DownloadSecurityError("sensitive headers cannot cross redirects")
        return redirected


def install_companion(
    install_root: Path,
    manifest: PinnedManifest,
    *,
    platform_key: str,
    downloader: Callable[..., object],
    system: str | None = None,
    machine: str | None = None,
) -> InstallResult:
    """Download, verify, and atomically install one approved companion asset.

    ``downloader`` receives ``(url, destination, timeout_seconds=..., max_bytes=...)``.
    Tests inject a local fake; the CLI supplies :func:`download_release_asset`.
    """
    if not isinstance(platform_key, str) or platform_key not in _SUPPORTED_PLATFORM_KEYS:
        return InstallResult("unsupported_platform", None)

    selected_system = platform.system() if system is None else system
    selected_machine = platform.machine() if machine is None else machine
    if _platform_key(selected_system, selected_machine) != platform_key:
        return InstallResult("unsupported_platform", platform_key)
    if not _valid_manifest_for_install(manifest):
        return InstallResult("install_failed", platform_key)
    if not callable(downloader):
        return InstallResult("download_failed", platform_key)

    pin = manifest.platforms[platform_key]
    try:
        root = _validate_install_root(install_root)
        runtime_root = _ensure_directory_chain(root, ("runtime", "opentunnel"))
        version_root = _ensure_directory_chain(
            root, ("runtime", "opentunnel", INSTALL_VERSION)
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return InstallResult("install_failed", platform_key)

    target_dir = version_root / pin.asset_stem
    previous_dir = version_root / (pin.asset_stem + ".previous")
    resolver_manifest = _resolver_manifest(manifest)

    if _path_exists(previous_dir):
        return InstallResult("install_failed", platform_key)

    resolution = resolve_companion(
        root,
        resolver_manifest,
        system=selected_system,
        machine=selected_machine,
    )
    if (
        resolution.state == "resolved"
        and resolution.path is not None
        and resolution.expected_sha256 == pin.sha256
        and _is_mode_0755_regular(resolution.path)
        and verify_companion_digest(resolution.path, pin.sha256)
    ):
        return InstallResult("already_installed", platform_key)

    try:
        old_digest = _inspect_existing_asset(target_dir)
    except (OSError, RuntimeError, TypeError, ValueError):
        return InstallResult("install_failed", platform_key)

    stage_dir: Path | None = None
    transaction_started = False
    retained_previous = False
    result_reason: InstallReason = "install_failed"

    try:
        staging_root = runtime_root / ".staging"
        _ensure_private_staging_root(staging_root)
        stage_dir = Path(tempfile.mkdtemp(prefix="install-", dir=str(staging_root)))
        _verify_private_directory(stage_dir)

        sums_part = stage_dir / "SHA256SUMS.part"
        archive_part = stage_dir / (pin.asset_name + ".part")
        _download_with_bounds(
            downloader,
            manifest.sha256sums_provenance.url,
            sums_part,
            min(manifest.sha256sums_provenance.size_bytes, MAX_SHA256SUMS_BYTES),
        )
        try:
            sums_bytes = _read_downloaded_file(
                sums_part, MAX_SHA256SUMS_BYTES
            )
        except (OSError, ValueError):
            raise _InstallFailure("download_failed") from None
        if (
            len(sums_bytes) != manifest.sha256sums_provenance.size_bytes
            or not hmac.compare_digest(
                hashlib.sha256(sums_bytes).hexdigest(),
                manifest.sha256sums_provenance.sha256,
            )
        ):
            raise _InstallFailure("sums_mismatch")
        try:
            sums_text = sums_bytes.decode("ascii")
        except UnicodeDecodeError:
            raise _InstallFailure("sums_mismatch") from None

        _download_with_bounds(
            downloader,
            manifest.release_url + "/" + pin.asset_name,
            archive_part,
            min(pin.archive_size_bytes, MAX_ARCHIVE_BYTES),
        )
        try:
            archive_size = _validate_downloaded_file(archive_part, MAX_ARCHIVE_BYTES)
            archive_digest = _sha256_file(archive_part, MAX_ARCHIVE_BYTES)
        except (OSError, ValueError):
            raise _InstallFailure("download_failed") from None
        if archive_size != pin.archive_size_bytes or not hmac.compare_digest(
            archive_digest, pin.archive_sha256
        ):
            raise _InstallFailure("checksum_mismatch")
        sums_digest = _checksum_for_asset(sums_text, pin.asset_name)
        if sums_digest is None or not hmac.compare_digest(
            archive_digest, sums_digest
        ):
            raise _InstallFailure("sums_mismatch")

        extract_root = stage_dir / "extracted"
        try:
            extracted_binary = _safe_extract_archive(archive_part, extract_root, pin)
        except (OSError, EOFError, tarfile.TarError, ValueError):
            raise _InstallFailure("unsafe_archive") from None

        try:
            extracted_stat = extracted_binary.lstat()
            executable_digest = _sha256_file(
                extracted_binary, MAX_EXTRACTED_BYTES
            )
        except (OSError, ValueError):
            raise _InstallFailure("executable_mismatch") from None
        if (
            not stat.S_ISREG(extracted_stat.st_mode)
            or stat.S_ISLNK(extracted_stat.st_mode)
            or extracted_stat.st_size != pin.executable_size_bytes
            or not hmac.compare_digest(executable_digest, pin.sha256)
        ):
            raise _InstallFailure("executable_mismatch")

        candidate_dir = stage_dir / "candidate" / pin.asset_stem
        candidate_dir.mkdir(mode=0o755, parents=True, exist_ok=False)
        candidate_binary = candidate_dir / "opentunnel"
        os.replace(extracted_binary, candidate_binary)
        candidate_binary.chmod(0o755)
        if not _is_mode_0755_regular(candidate_binary):
            raise _InstallFailure("install_failed")

        if old_digest is not None:
            _recheck_install_directory(version_root, root)
            try:
                os.replace(target_dir, previous_dir)
            finally:
                if _path_exists(previous_dir) and not _path_exists(target_dir):
                    retained_previous = True
                    transaction_started = True
        try:
            os.replace(candidate_dir, target_dir)
        finally:
            if _path_exists(target_dir) and not _path_exists(candidate_dir):
                transaction_started = True

        if not _verify_promoted_asset(
            root,
            resolver_manifest,
            pin,
            platform_key,
            selected_system,
            selected_machine,
        ):
            raise _InstallFailure("install_failed")

        _cleanup_staging(stage_dir)
        stage_dir = None
        if retained_previous:
            _remove_real_directory(previous_dir, version_root)
            retained_previous = False
        result_reason = "installed"
    except _InstallFailure as exc:
        if transaction_started:
            result_reason = (
                "rolled_back"
                if _rollback_install(
                    root,
                    version_root,
                    target_dir,
                    previous_dir,
                    old_digest,
                    platform_key,
                    selected_system,
                    selected_machine,
                    retained_previous,
                )
                else "install_failed"
            )
        else:
            result_reason = exc.reason
    except KeyboardInterrupt:
        if transaction_started:
            _rollback_install(
                root,
                version_root,
                target_dir,
                previous_dir,
                old_digest,
                platform_key,
                selected_system,
                selected_machine,
                retained_previous,
            )
        raise
    except Exception:
        if transaction_started:
            result_reason = (
                "rolled_back"
                if _rollback_install(
                    root,
                    version_root,
                    target_dir,
                    previous_dir,
                    old_digest,
                    platform_key,
                    selected_system,
                    selected_machine,
                    retained_previous,
                )
                else "install_failed"
            )
        else:
            result_reason = "install_failed"
    finally:
        if stage_dir is not None:
            try:
                _cleanup_staging(stage_dir)
            except OSError:
                pass

    return InstallResult(result_reason, platform_key)


def download_release_asset(
    url: str,
    destination: Path,
    *,
    release_url: str,
    timeout_seconds: int,
    max_bytes: int,
) -> None:
    """Stream one pinned GitHub release file with proxy-free bounded transport."""
    _validate_download_url(url, release_url)
    if (
        type(timeout_seconds) is not int
        or timeout_seconds < 1
        or timeout_seconds > MAX_DOWNLOAD_TIMEOUT_SECONDS
        or type(max_bytes) is not int
        or max_bytes < 1
        or max_bytes > MAX_ARCHIVE_BYTES
    ):
        raise DownloadSecurityError("download bounds are invalid")

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _ReleaseRedirectHandler(),
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "NeverEndingQuest-network-installer"}
    )
    if _has_sensitive_headers(request):
        raise DownloadSecurityError("initial request contains sensitive headers")
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            _validate_redirect_url(response.geturl())
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    content_length = int(raw_length)
                except (TypeError, ValueError):
                    raise DownloadSecurityError("download length is invalid") from None
                if content_length < 0 or content_length > max_bytes:
                    raise DownloadSecurityError("download exceeds its size bound")

            total = 0
            with Path(destination).open("xb") as output:
                while True:
                    if time.monotonic() - started > timeout_seconds:
                        raise TimeoutError("download deadline exceeded")
                    chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, max_bytes - total + 1))
                    if time.monotonic() - started > timeout_seconds:
                        raise TimeoutError("download deadline exceeded")
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadSecurityError("download exceeds its size bound")
                    output.write(chunk)
    except BaseException:
        try:
            Path(destination).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _validate_download_url(url: str, release_url: str) -> None:
    """Accept only exact manifest release paths over the pinned HTTPS host."""
    try:
        base = urlsplit(release_url)
        parsed = urlsplit(url)
        base_port = base.port
        port = parsed.port
    except (AttributeError, TypeError, ValueError) as exc:
        raise DownloadSecurityError("download URL is invalid") from exc
    if (
        release_url != UPSTREAM_RELEASE_URL
        or base.scheme != "https"
        or base.hostname != "github.com"
        or base_port not in (None, 443)
        or parsed.scheme != "https"
        or parsed.hostname != base.hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in url
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise DownloadSecurityError("download URL is outside the pinned HTTPS host")
    allowed_paths = {
        base.path + "/SHA256SUMS",
        *(base.path + "/" + asset[0] for asset in _PLATFORM_ASSETS.values()),
    }
    if parsed.path not in allowed_paths or parsed.netloc not in {
        "github.com",
        "github.com:443",
    }:
        raise DownloadSecurityError("download URL is not an approved release asset")


def _validate_redirect_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise DownloadSecurityError("redirect URL is invalid") from exc
    hostname = parsed.hostname.casefold() if parsed.hostname else None
    normalized_netloc = parsed.netloc.casefold()
    if (
        parsed.scheme.casefold() != "https"
        or hostname not in _REDIRECT_HOST_ALLOWLIST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or normalized_netloc not in (hostname, hostname + ":443")
        or "\\" in url
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise DownloadSecurityError("redirect host is not allowlisted")


def _has_sensitive_headers(request: urllib.request.Request) -> bool:
    return any(
        key.casefold() in _SENSITIVE_REQUEST_HEADERS
        for headers in (request.headers, request.unredirected_hdrs)
        for key in headers
    )


def _remove_sensitive_headers(request: urllib.request.Request) -> None:
    for header_map in (request.headers, request.unredirected_hdrs):
        for header in list(header_map):
            if header.casefold() in _SENSITIVE_REQUEST_HEADERS:
                del header_map[header]


def _download_with_bounds(
    downloader: Callable[..., object],
    url: str,
    destination: Path,
    max_bytes: int,
) -> None:
    try:
        downloader(
            url,
            destination,
            timeout_seconds=MAX_DOWNLOAD_TIMEOUT_SECONDS,
            max_bytes=max_bytes,
        )
        _validate_downloaded_file(destination, max_bytes)
    except _InstallFailure:
        raise
    except Exception:
        raise _InstallFailure("download_failed") from None


def _read_downloaded_file(path: Path, max_bytes: int) -> bytes:
    metadata = Path(path).lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("download output is not a regular file")
    if metadata.st_size <= 0 or metadata.st_size > max_bytes:
        raise ValueError("download output exceeds its size bound")
    with Path(path).open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) != metadata.st_size or len(data) > max_bytes:
        raise ValueError("download output changed while reading")
    return data


def _validate_downloaded_file(path: Path, max_bytes: int) -> int:
    metadata = Path(path).lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("download output is not a regular file")
    if metadata.st_size <= 0 or metadata.st_size > max_bytes:
        raise ValueError("download output exceeds its size bound")
    return metadata.st_size


def _checksum_for_asset(sums_text: str, asset_name: str) -> str | None:
    matches: list[str] = []
    for line in sums_text.splitlines():
        match = _SUMS_LINE_RE.fullmatch(line)
        if match is not None and match.group(2) == asset_name:
            matches.append(match.group(1).lower())
    return matches[0] if len(matches) == 1 else None


def _safe_extract_archive(
    archive_path: Path, destination: Path, pin: PlatformPin
) -> Path:
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        binary_member = _validate_tar_members(members, pin)
        archive.extractall(path=destination, members=members, filter="data")

    binary_path = destination.joinpath(*PurePosixPath(binary_member.name).parts)
    try:
        binary_path.resolve(strict=True).relative_to(destination.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("extracted executable escaped staging") from exc
    if not _is_regular_non_symlink(binary_path):
        raise ValueError("extracted executable is not a regular file")
    return binary_path


def _validate_tar_members(
    members: list[tarfile.TarInfo], pin: PlatformPin
) -> tarfile.TarInfo:
    if not members or len(members) > MAX_ARCHIVE_MEMBERS:
        raise ValueError("archive member count is outside bounds")

    seen_names: set[str] = set()
    binary_members: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
    directory_paths: list[tuple[str, ...]] = []
    total_file_bytes = 0
    for member in members:
        name = member.name
        if not isinstance(name, str) or not name or "\\" in name:
            raise ValueError("archive member path is invalid")
        path = PurePosixPath(name)
        parts = path.parts
        if (
            path.is_absolute()
            or not parts
            or ".." in parts
            or re.match(r"^[A-Za-z]:", name) is not None
            or name in seen_names
        ):
            raise ValueError("archive contains an unsafe or duplicate member")
        seen_names.add(name)
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise ValueError("archive contains a link or special member")
        if member.size < 0:
            raise ValueError("archive member size is invalid")
        if member.isdir():
            if member.size != 0:
                raise ValueError("archive directory has an invalid size")
            directory_paths.append(parts)
            continue

        total_file_bytes += member.size
        if total_file_bytes > MAX_EXTRACTED_BYTES:
            raise ValueError("archive expanded size exceeds its bound")
        if member.size != pin.executable_size_bytes:
            raise ValueError("archive executable size does not match the pin")
        if path.name != "opentunnel":
            raise ValueError("archive contains an unexpected file")
        binary_members.append((member, parts))

    if len(binary_members) != 1:
        raise ValueError("archive must contain exactly one opentunnel executable")
    binary_member, binary_parts = binary_members[0]
    for directory_parts in directory_paths:
        if len(directory_parts) >= len(binary_parts) or binary_parts[: len(directory_parts)] != directory_parts:
            raise ValueError("archive contains an unexpected directory")
    return binary_member


def _valid_manifest_for_install(manifest: object) -> bool:
    try:
        if not isinstance(manifest, PinnedManifest):
            return False
        if (
            manifest.version != "0.6.2"
            or manifest.release_url != UPSTREAM_RELEASE_URL
            or set(manifest.platforms) != _SUPPORTED_PLATFORM_KEYS
        ):
            return False
        provenance = manifest.sha256sums_provenance
        if (
            provenance.url != manifest.release_url + "/SHA256SUMS"
            or _SHA256_RE.fullmatch(provenance.sha256) is None
            or type(provenance.size_bytes) is not int
            or provenance.size_bytes < 1
            or provenance.size_bytes > MAX_SHA256SUMS_BYTES
        ):
            return False
        for key, pin in manifest.platforms.items():
            expected_asset = _PLATFORM_ASSETS.get(key)
            if expected_asset is None:
                return False
            if (
                not isinstance(pin, PlatformPin)
                or pin.platform_key != key
                or (pin.asset_name, pin.asset_stem) != expected_asset
                or pin.runtime_path
                != "runtime/opentunnel/v0.6.2/" + pin.asset_stem + "/opentunnel"
                or _SHA256_RE.fullmatch(pin.archive_sha256) is None
                or _SHA256_RE.fullmatch(pin.sha256) is None
                or type(pin.archive_size_bytes) is not int
                or pin.archive_size_bytes < 1
                or pin.archive_size_bytes > MAX_ARCHIVE_BYTES
                or type(pin.executable_size_bytes) is not int
                or pin.executable_size_bytes < 1
                or pin.executable_size_bytes > MAX_EXTRACTED_BYTES
            ):
                return False
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def _validate_install_root(install_root: Path) -> Path:
    path = Path(install_root).expanduser()
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("install root must be a real directory")
    root = path.resolve(strict=True)
    if _has_venv_component(root):
        raise ValueError("install root is inside a virtual environment")
    return root


def _ensure_directory_chain(root: Path, parts: tuple[str, ...]) -> Path:
    current = root
    for part in parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o755)
            metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("install directory is not a real directory")
        current.resolve(strict=True).relative_to(root)
    return current


def _ensure_private_staging_root(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o700)
    _verify_private_directory(path)


def _verify_private_directory(path: Path) -> None:
    metadata = Path(path).lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError("staging directory is not private and owner-controlled")


def _inspect_existing_asset(target_dir: Path) -> str | None:
    try:
        metadata = target_dir.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("existing asset path is unsafe")
    binary = target_dir / "opentunnel"
    if not _is_mode_0755_regular(binary):
        raise ValueError("existing executable is unsafe")
    for child in target_dir.rglob("*"):
        child_metadata = child.lstat()
        if stat.S_ISLNK(child_metadata.st_mode):
            raise ValueError("existing asset directory contains a symlink")
    return _sha256_file(binary, MAX_EXTRACTED_BYTES)


def _verify_promoted_asset(
    root: Path,
    resolver_manifest: dict[str, dict[str, str]],
    pin: PlatformPin,
    platform_key: str,
    system: str,
    machine: str,
) -> bool:
    resolution = resolve_companion(
        root, resolver_manifest, system=system, machine=machine
    )
    return bool(
        resolution.state == "resolved"
        and resolution.path == (root / pin.runtime_path).resolve(strict=True)
        and resolution.expected_sha256 == pin.sha256
        and _is_mode_0755_regular(resolution.path)
        and verify_companion_digest(resolution.path, pin.sha256)
        and platform_key in resolver_manifest
    )


def _rollback_install(
    root: Path,
    version_root: Path,
    target_dir: Path,
    previous_dir: Path,
    old_digest: str | None,
    platform_key: str,
    system: str,
    machine: str,
    retained_previous: bool,
) -> bool:
    try:
        if _path_exists(target_dir):
            _remove_real_directory(target_dir, version_root)
        if not retained_previous:
            return old_digest is None
        os.replace(previous_dir, target_dir)
        if old_digest is None:
            return False
        old_manifest = {
            platform_key: {
                "asset_stem": target_dir.name,
                "sha256": old_digest,
            }
        }
        resolution = resolve_companion(
            root, old_manifest, system=system, machine=machine
        )
        return bool(
            resolution.state == "resolved"
            and resolution.path is not None
            and resolution.expected_sha256 == old_digest
            and _is_mode_0755_regular(resolution.path)
            and verify_companion_digest(resolution.path, old_digest)
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _remove_real_directory(path: Path, expected_parent: Path) -> None:
    metadata = Path(path).lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("refusing to remove a non-directory install path")
    resolved = Path(path).resolve(strict=True)
    resolved.relative_to(expected_parent.resolve(strict=True))
    shutil.rmtree(resolved)


def _cleanup_staging(path: Path) -> None:
    metadata = Path(path).lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("staging path is unsafe")
    shutil.rmtree(path)


def _sha256_file(path: Path, max_bytes: int) -> str:
    digest = hashlib.sha256()
    total = 0
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("file exceeds its size bound")
            digest.update(chunk)
    return digest.hexdigest()


def _is_regular_non_symlink(path: Path) -> bool:
    try:
        metadata = Path(path).lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)


def _is_mode_0755_regular(path: Path) -> bool:
    try:
        metadata = Path(path).lstat()
    except OSError:
        return False
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o755
    )


def _path_exists(path: Path) -> bool:
    try:
        Path(path).lstat()
    except FileNotFoundError:
        return False
    return True


def _recheck_install_directory(version_root: Path, root: Path) -> None:
    metadata = version_root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("version directory changed before activation")
    version_root.resolve(strict=True).relative_to(root.resolve(strict=True))


def _resolver_manifest(
    manifest: PinnedManifest,
) -> dict[str, dict[str, str]]:
    return {
        key: {"asset_stem": pin.asset_stem, "sha256": pin.sha256}
        for key, pin in manifest.platforms.items()
    }


def _platform_key(system: object, machine: object) -> str | None:
    if not isinstance(system, str) or not isinstance(machine, str):
        return None
    os_name = system.casefold()
    arch = machine.casefold()
    if os_name not in {"darwin", "linux"} or arch not in {"arm64", "aarch64"}:
        return None
    return os_name + "-arm64"


def _has_venv_component(path: Path) -> bool:
    return any(part.casefold() in {".venv", "venv"} for part in path.parts)


def main(argv: list[str] | None = None) -> int:
    """Run the explicitly consented companion installation CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args(argv)
    if not args.install:
        print("OpenTunnel installation: refused (explicit --install required)")
        return 2

    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "packaging/opentunnel-v0.6.2.manifest.json"
    )
    try:
        manifest = load_pinned_manifest(manifest_path)
    except Exception:
        print("OpenTunnel installation: install_failed")
        return 1

    selected_system = platform.system()
    selected_machine = platform.machine()
    key = _platform_key(selected_system, selected_machine)
    if key is None:
        result = InstallResult("unsupported_platform", None)
    else:
        result = install_companion(
            Path(args.install_root),
            manifest,
            platform_key=key,
            system=selected_system,
            machine=selected_machine,
            downloader=lambda url, destination, *, timeout_seconds, max_bytes: download_release_asset(
                url,
                destination,
                release_url=manifest.release_url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            ),
        )
    print("OpenTunnel installation: " + result.reason)
    return 0 if result.reason in {"installed", "already_installed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
