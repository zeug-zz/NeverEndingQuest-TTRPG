# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Resolve only the pinned, install-relative OpenTunnel v0.6.2 companion."""

from __future__ import annotations

import hashlib
import hmac
import os
import platform
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

OPEN_TUNNEL_VERSION = "v0.6.2"
DIGEST_CHUNK_SIZE = 64 * 1024

CompanionState = Literal[
    "resolved",
    "unsupported_platform",
    "missing_asset",
    "invalid_manifest",
    "unsafe_path",
]

_ASSET_STEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SUPPORTED_PLATFORMS = frozenset({"darwin-arm64", "linux-arm64"})
_VENV_COMPONENTS = frozenset({".venv", "venv"})


@dataclass(frozen=True, slots=True)
class CompanionResolution:
    """A bounded resolution result; paths and digests exist only on success."""

    state: CompanionState
    reason: str
    path: Path | None = None
    expected_sha256: str | None = None


def resolve_companion(
    install_root: Path,
    manifest: Mapping[str, object],
    *,
    system: str | None = None,
    machine: str | None = None,
) -> CompanionResolution:
    """Resolve a pinned binary beneath ``install_root`` without searching PATH.

    Only macOS arm64 and Linux arm64 are supported. ``manifest`` is injected by
    the packaging layer and maps those platform identifiers to an asset stem
    and lowercase SHA-256 digest. Resolution validates placement and executable
    status but does not hash the binary.
    """
    selected_system = platform.system() if system is None else system
    selected_machine = platform.machine() if machine is None else machine
    platform_key = _platform_key(selected_system, selected_machine)
    if platform_key is None or platform_key not in _SUPPORTED_PLATFORMS:
        return _failure("unsupported_platform", "unsupported_platform")

    if not isinstance(manifest, Mapping):
        return _failure("invalid_manifest", "invalid_manifest")
    if platform_key not in manifest:
        return _failure("missing_asset", "manifest_entry_missing")
    entry = manifest[platform_key]
    if not isinstance(entry, Mapping) or set(entry) != {"asset_stem", "sha256"}:
        return _failure("invalid_manifest", "invalid_manifest")

    asset_stem = entry.get("asset_stem")
    digest = entry.get("sha256")
    if (
        not isinstance(asset_stem, str)
        or len(asset_stem) > 64
        or _ASSET_STEM_RE.fullmatch(asset_stem) is None
        or not isinstance(digest, str)
        or _SHA256_RE.fullmatch(digest) is None
    ):
        return _failure("invalid_manifest", "invalid_manifest")

    try:
        root = Path(install_root).resolve(strict=True)
        if not root.is_dir():
            return _failure("unsafe_path", "install_root_not_directory")
    except FileNotFoundError:
        return _failure("missing_asset", "install_root_missing")
    except (OSError, RuntimeError, TypeError, ValueError):
        return _failure("unsafe_path", "install_root_unavailable")

    if _has_venv_component(root):
        return _failure("unsafe_path", "venv_placement")

    relative_parts = (
        "runtime",
        "opentunnel",
        OPEN_TUNNEL_VERSION,
        asset_stem,
        "opentunnel",
    )
    candidate = root
    for index, part in enumerate(relative_parts):
        candidate = candidate / part
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            return _failure("missing_asset", "binary_missing")
        except (OSError, RuntimeError, ValueError):
            return _failure("unsafe_path", "path_unavailable")

        if stat.S_ISLNK(metadata.st_mode):
            return _failure("unsafe_path", "symlink_component")
        if index < len(relative_parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            return _failure("unsafe_path", "non_directory_component")

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError:
        return _failure("missing_asset", "binary_missing")
    except (OSError, RuntimeError, ValueError):
        return _failure("unsafe_path", "outside_install_root")

    if _has_venv_component(resolved):
        return _failure("unsafe_path", "venv_placement")
    if not stat.S_ISREG(metadata.st_mode):
        return _failure("unsafe_path", "not_regular_file")
    try:
        executable = os.access(resolved, os.X_OK)
    except (OSError, ValueError):
        executable = False
    if not executable:
        return _failure("unsafe_path", "not_executable")

    return CompanionResolution(
        state="resolved",
        reason="resolved",
        path=resolved,
        expected_sha256=digest,
    )


def verify_companion_digest(path: Path, expected_sha256: str) -> bool:
    """Stream a file digest in bounded chunks and compare against a pin."""
    if not isinstance(expected_sha256, str) or _SHA256_RE.fullmatch(expected_sha256) is None:
        return False

    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            while True:
                chunk = stream.read(DIGEST_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(digest.hexdigest(), expected_sha256)


def _platform_key(system: object, machine: object) -> str | None:
    if not isinstance(system, str) or not isinstance(machine, str):
        return None
    normalized_system = system.casefold()
    normalized_machine = machine.casefold()
    if normalized_system == "darwin":
        normalized_os = "darwin"
    elif normalized_system == "linux":
        normalized_os = "linux"
    else:
        return None
    if normalized_machine not in {"arm64", "aarch64"}:
        return None
    return normalized_os + "-arm64"


def _has_venv_component(path: Path) -> bool:
    return any(part in _VENV_COMPONENTS for part in path.parts)


def _failure(state: CompanionState, reason: str) -> CompanionResolution:
    return CompanionResolution(state=state, reason=reason)
