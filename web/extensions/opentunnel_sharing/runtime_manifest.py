# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Strict local runtime-manifest reader and explicit installer writer."""

# TABLETOP MODE: This module handles only facilitator-installed local companion metadata.

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from scripts.network_packaging.manifest import PinnedManifest, PlatformPin

RUNTIME_MANIFEST_SCHEMA = "neq.opentunnel.runtime_manifest.v1"
RUNTIME_MANIFEST_VERSION = "0.6.2"
MAX_RUNTIME_MANIFEST_BYTES = 8 * 1024
_PLATFORM_STEMS = {
    "darwin-arm64": "opentunnel-darwin-arm64",
    "linux-arm64": "opentunnel-linux-arm64",
}
_SUPPORTED_PLATFORMS = frozenset(_PLATFORM_STEMS)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ASSET_STEM_RE = re.compile(r"opentunnel-(?:darwin|linux)-arm64\Z")
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_DIRECTORY_FLAGS |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
_FILE_READ_FLAGS |= getattr(os, "O_NOFOLLOW", 0)
_FILE_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL
_FILE_WRITE_FLAGS |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


class ManifestError(ValueError):
    """Bounded runtime-manifest failure; ``reason`` is safe for status output."""

    def __init__(self, reason: str = "invalid_manifest") -> None:
        if reason not in {"invalid_manifest", "manifest_missing"}:
            reason = "invalid_manifest"
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RuntimeManifestSnapshot:
    """Validated pre-update manifest bytes used for explicit rollback."""

    content: bytes


def load_companion_manifest(install_root: Path) -> Mapping[str, Mapping[str, str]]:
    """Read and validate the install-relative manifest without creating anything."""
    directory_fd = -1
    manifest_fd = -1
    try:
        _root, directory_fd = _open_version_directory(install_root, create=False)
        manifest_fd = _open_manifest_readonly(directory_fd)
        metadata = os.fstat(manifest_fd)
        _validate_manifest_metadata(metadata)
        content = _read_bounded(manifest_fd)
        after = os.fstat(manifest_fd)
        if not _same_file_metadata(metadata, after):
            raise ManifestError()
        return _parse_runtime_manifest(content)
    except ManifestError:
        raise
    except FileNotFoundError as exc:
        raise ManifestError("manifest_missing") from exc
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError) as exc:
        raise ManifestError() from exc
    finally:
        if manifest_fd >= 0:
            os.close(manifest_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def write_runtime_manifest(
    install_root: Path,
    packaged_manifest_entry_or_pinned_manifest: PinnedManifest,
    platform_key: str,
) -> None:
    """Atomically publish one validated source-manifest entry for this platform.

    A previously valid runtime manifest is merged so an approved entry for the
    other platform is retained. An absent manifest starts as a single-platform
    document; an invalid existing manifest is not silently overwritten.
    """
    entry = _entry_from_pinned_manifest(
        packaged_manifest_entry_or_pinned_manifest, platform_key
    )
    directory_fd = -1
    try:
        _root, directory_fd = _open_version_directory(install_root, create=True)
        platforms: dict[str, dict[str, str]] = {}
        try:
            platforms.update(
                {
                    key: dict(value)
                    for key, value in load_companion_manifest(install_root).items()
                }
            )
        except ManifestError as exc:
            if exc.reason != "manifest_missing":
                raise
        platforms[platform_key] = entry
        document = {
            "schema": RUNTIME_MANIFEST_SCHEMA,
            "version": RUNTIME_MANIFEST_VERSION,
            "platforms": platforms,
        }
        encoded = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("ascii")
        _atomic_replace(directory_fd, encoded)
    except ManifestError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ManifestError() from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def snapshot_runtime_manifest(install_root: Path) -> RuntimeManifestSnapshot | None:
    """Capture valid prior bytes, or return ``None`` when none are installed."""
    try:
        content = _read_runtime_manifest_bytes(install_root)
    except ManifestError as exc:
        if exc.reason == "manifest_missing":
            return None
        raise
    return RuntimeManifestSnapshot(content)


def restore_runtime_manifest(
    install_root: Path,
    snapshot: RuntimeManifestSnapshot | None,
) -> bool:
    """Restore prior manifest bytes (or absence) using an atomic local operation."""
    directory_fd = -1
    try:
        _root, directory_fd = _open_version_directory(install_root, create=True)
        if snapshot is None:
            try:
                metadata = os.stat(
                    "manifest.json", dir_fd=directory_fd, follow_symlinks=False
                )
            except FileNotFoundError:
                return True
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                return False
            os.unlink("manifest.json", dir_fd=directory_fd)
            os.fsync(directory_fd)
            return True

        # Snapshots are created only from a validated file; revalidate before
        # using this rollback seam so arbitrary bytes cannot be installed.
        _parse_runtime_manifest(snapshot.content)
        _atomic_replace(directory_fd, snapshot.content)
        return True
    except (ManifestError, OSError, RuntimeError, TypeError, ValueError):
        return False
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def _read_runtime_manifest_bytes(install_root: Path) -> bytes:
    directory_fd = -1
    manifest_fd = -1
    try:
        _root, directory_fd = _open_version_directory(install_root, create=False)
        manifest_fd = _open_manifest_readonly(directory_fd)
        metadata = os.fstat(manifest_fd)
        _validate_manifest_metadata(metadata)
        content = _read_bounded(manifest_fd)
        after = os.fstat(manifest_fd)
        if not _same_file_metadata(metadata, after):
            raise ManifestError()
        _parse_runtime_manifest(content)
        return content
    except ManifestError:
        raise
    except FileNotFoundError as exc:
        raise ManifestError("manifest_missing") from exc
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError) as exc:
        raise ManifestError() from exc
    finally:
        if manifest_fd >= 0:
            os.close(manifest_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _open_version_directory(install_root: Path, *, create: bool) -> tuple[Path, int]:
    try:
        supplied_root = Path(install_root).expanduser()
        root_metadata = supplied_root.lstat()
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
            raise ManifestError()
        if _has_venv_component(supplied_root):
            raise ManifestError()
        root = supplied_root.resolve(strict=True)
        if _has_venv_component(root):
            raise ManifestError()
        descriptor = os.open(root, _DIRECTORY_FLAGS)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ManifestError()
    except ManifestError:
        raise
    except FileNotFoundError as exc:
        raise ManifestError("manifest_missing") from exc
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ManifestError() from exc

    try:
        for component in ("runtime", "opentunnel", "v0.6.2"):
            try:
                child_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise ManifestError("manifest_missing") from None
                os.mkdir(component, 0o755, dir_fd=descriptor)
                child_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError as exc:
                raise ManifestError() from exc
            if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                os.close(child_fd)
                raise ManifestError()
            os.close(descriptor)
            descriptor = child_fd
        return root, descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_manifest_readonly(directory_fd: int) -> int:
    try:
        metadata = os.stat(
            "manifest.json", dir_fd=directory_fd, follow_symlinks=False
        )
    except FileNotFoundError:
        raise ManifestError("manifest_missing") from None
    except OSError as exc:
        raise ManifestError() from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ManifestError()
    try:
        descriptor = os.open("manifest.json", _FILE_READ_FLAGS, dir_fd=directory_fd)
    except OSError as exc:
        raise ManifestError() from exc
    opened = os.fstat(descriptor)
    if not _same_file(metadata, opened):
        os.close(descriptor)
        raise ManifestError()
    return descriptor


def _validate_manifest_metadata(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or metadata.st_size < 1
        or metadata.st_size > MAX_RUNTIME_MANIFEST_BYTES
    ):
        raise ManifestError()


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(4096, MAX_RUNTIME_MANIFEST_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_RUNTIME_MANIFEST_BYTES:
            raise ManifestError()


def _parse_runtime_manifest(content: bytes) -> Mapping[str, Mapping[str, str]]:
    try:
        text = content.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ManifestError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ManifestError() from exc
    if not isinstance(document, dict) or set(document) != {
        "schema",
        "version",
        "platforms",
    }:
        raise ManifestError()
    if (
        document["schema"] != RUNTIME_MANIFEST_SCHEMA
        or document["version"] != RUNTIME_MANIFEST_VERSION
    ):
        raise ManifestError()
    raw_platforms = document["platforms"]
    if (
        not isinstance(raw_platforms, dict)
        or not raw_platforms
        or not set(raw_platforms).issubset(_SUPPORTED_PLATFORMS)
    ):
        raise ManifestError()

    platforms: dict[str, Mapping[str, str]] = {}
    for key, raw_entry in raw_platforms.items():
        if not isinstance(raw_entry, dict) or set(raw_entry) != {
            "asset_stem",
            "sha256",
        }:
            raise ManifestError()
        asset_stem = raw_entry["asset_stem"]
        digest = raw_entry["sha256"]
        if (
            not isinstance(asset_stem, str)
            or _ASSET_STEM_RE.fullmatch(asset_stem) is None
            or asset_stem != _PLATFORM_STEMS[key]
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
        ):
            raise ManifestError()
        platforms[key] = MappingProxyType(
            {"asset_stem": asset_stem, "sha256": digest}
        )
    return MappingProxyType(platforms)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ManifestError()


def _entry_from_pinned_manifest(
    manifest: PinnedManifest,
    platform_key: str,
) -> dict[str, str]:
    if (
        not isinstance(manifest, PinnedManifest)
        or manifest.version != RUNTIME_MANIFEST_VERSION
        or set(manifest.platforms) != _SUPPORTED_PLATFORMS
        or not isinstance(platform_key, str)
        or platform_key not in _SUPPORTED_PLATFORMS
    ):
        raise ManifestError()
    pin = manifest.platforms.get(platform_key)
    if (
        not isinstance(pin, PlatformPin)
        or pin.platform_key != platform_key
        or pin.asset_stem != _PLATFORM_STEMS[platform_key]
        or _ASSET_STEM_RE.fullmatch(pin.asset_stem) is None
        or not isinstance(pin.sha256, str)
        or _SHA256_RE.fullmatch(pin.sha256) is None
    ):
        raise ManifestError()
    return {"asset_stem": pin.asset_stem, "sha256": pin.sha256}


def _atomic_replace(directory_fd: int, content: bytes) -> None:
    if len(content) > MAX_RUNTIME_MANIFEST_BYTES:
        raise ManifestError()
    temporary_name: str | None = None
    descriptor = -1
    try:
        for _attempt in range(10):
            candidate = ".manifest.json." + uuid.uuid4().hex + ".tmp"
            try:
                descriptor = os.open(
                    candidate,
                    _FILE_WRITE_FLAGS,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if descriptor < 0 or temporary_name is None:
            raise OSError("unable to create manifest temporary file")

        os.fchmod(descriptor, 0o644)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("manifest write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1

        try:
            existing = os.stat(
                "manifest.json", dir_fd=directory_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            stat.S_ISLNK(existing.st_mode)
            or not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.getuid()
            or stat.S_IMODE(existing.st_mode) & 0o022
        ):
            raise ManifestError()
        os.replace(
            temporary_name,
            "manifest.json",
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        os.fsync(directory_fd)
    except BaseException:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        raise


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_file_metadata(left: os.stat_result, right: os.stat_result) -> bool:
    return _same_file(left, right) and (
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (right.st_size, right.st_mtime_ns, right.st_ctime_ns)


def _has_venv_component(path: Path) -> bool:
    return any(part.casefold() in {".venv", "venv"} for part in path.parts)
