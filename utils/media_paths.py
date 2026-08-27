# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free helpers for safely authorizing web media files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional, Union

from utils.repo_paths import PathBoundaryError, resolve_contained_path


PathInput = Union[str, os.PathLike]


def resolve_media_file(
    requested: PathInput,
    approved_root: PathInput,
    *,
    allowed_extensions: Optional[Iterable[str]] = None,
) -> Optional[Path]:
    """Return a safe regular media file, or ``None`` for any unsafe target."""
    try:
        root = Path(approved_root)
        if root.is_symlink():
            return None
        candidate = resolve_contained_path(
            requested,
            root,
            relative_only=True,
            allow_missing=False,
            reject_symlinks=True,
        )
    except (PathBoundaryError, OSError, ValueError):
        return None

    if not candidate.is_file():
        return None
    if allowed_extensions is not None:
        extensions = {str(ext).lower() for ext in allowed_extensions}
        if candidate.suffix.lower() not in extensions:
            return None
    return candidate


def is_safe_media_request(requested: PathInput, approved_root: PathInput) -> bool:
    """Validate an untrusted media name before trying fallback roots."""
    try:
        if Path(approved_root).is_symlink():
            return False
        resolve_contained_path(
            requested,
            approved_root,
            relative_only=True,
            allow_missing=True,
            reject_symlinks=True,
        )
    except (PathBoundaryError, OSError, ValueError):
        return False
    return True


__all__ = ["is_safe_media_request", "resolve_media_file"]
