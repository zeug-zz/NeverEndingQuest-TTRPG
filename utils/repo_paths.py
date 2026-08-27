# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Small, provider-free helpers for repository-local path authorization."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path
from typing import Optional, Union


PathInput = Union[str, os.PathLike]


class PathBoundaryError(ValueError):
    """Raised when a path cannot be safely contained by an approved root."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("unsafe path: {0}".format(reason))


def repository_root(source_file: Optional[PathInput] = None) -> Path:
    """Return the installed repository root derived from a source file.

    The default source is this utility's installed location.  In particular,
    this function never consults the process current working directory.
    """
    source = Path(source_file) if source_file is not None else Path(__file__)
    source = source.resolve(strict=True)
    # This module lives in <root>/utils/repo_paths.py.
    root = source.parent.parent
    if not root.is_dir():
        raise PathBoundaryError("repository root is unavailable")
    return root


def _is_absolute_input(value: str) -> bool:
    """Recognize POSIX and Windows absolute path spellings on every platform."""
    return Path(value).is_absolute() or ntpath.isabs(value)


def _has_traversal_component(value: str) -> bool:
    """Reject explicit parent components before normalization can hide them."""
    return any(part == ".." for part in value.replace("\\", "/").split("/"))


def _contains_symlink(path: Path, root: Path) -> bool:
    """Check existing components from root through path without following links."""
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return True

    current = root
    for part in relative_parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            # An inaccessible component is not safe to authorize.
            raise PathBoundaryError("path component cannot be inspected")
        if not current.exists() and not current.is_symlink():
            # A missing final target, or missing descendants, is allowed.  Any
            # existing parent components before it have already been checked.
            break
    return False


def resolve_contained_path(
    requested: PathInput,
    approved_root: PathInput,
    *,
    relative_only: bool = True,
    allow_missing: bool = True,
    reject_symlinks: bool = True,
) -> Path:
    """Resolve ``requested`` beneath ``approved_root`` safely.

    ``requested`` may be relative to the approved root.  With
    ``relative_only=True`` (the default), absolute and traversal inputs are
    rejected even when normalization would leave them inside the root.
    Missing final targets are returned when ``allow_missing`` is true, while
    existing parent components are still checked for symlinks.
    """
    if not isinstance(requested, (str, os.PathLike)):
        raise PathBoundaryError("path must be a string or path-like value")
    if not isinstance(approved_root, (str, os.PathLike)):
        raise PathBoundaryError("approved root is invalid")

    raw = os.fspath(requested)
    if isinstance(raw, bytes):
        raise PathBoundaryError("path must be text")
    raw = str(raw)
    if not raw:
        raise PathBoundaryError("path is empty")
    if relative_only and _is_absolute_input(raw):
        raise PathBoundaryError("absolute paths are not allowed")
    if _has_traversal_component(raw):
        raise PathBoundaryError("path traversal is not allowed")

    root = Path(approved_root).resolve(strict=True)
    lexical_candidate = (root / Path(raw)) if not _is_absolute_input(raw) else Path(raw)
    candidate = lexical_candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PathBoundaryError("path is outside the approved root") from exc

    # Inspect the lexical path, rather than the resolved path: resolving first
    # would erase evidence that an otherwise-contained component was a link.
    if reject_symlinks and _contains_symlink(lexical_candidate, root):
        raise PathBoundaryError("symlinked path components are not allowed")
    if not allow_missing and not candidate.exists():
        raise PathBoundaryError("target does not exist")
    return candidate


def resolve_repository_path(
    requested: PathInput,
    *,
    root: Optional[PathInput] = None,
    relative_only: bool = True,
    allow_missing: bool = True,
    reject_symlinks: bool = True,
) -> Path:
    """Resolve an application path beneath the installed repository root."""
    return resolve_contained_path(
        requested,
        repository_root() if root is None else root,
        relative_only=relative_only,
        allow_missing=allow_missing,
        reject_symlinks=reject_symlinks,
    )


__all__ = [
    "PathBoundaryError",
    "repository_root",
    "resolve_contained_path",
    "resolve_repository_path",
]
