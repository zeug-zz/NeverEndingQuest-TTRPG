# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free authorization helpers for repository-local SQLite targets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from utils.repo_paths import PathBoundaryError, repository_root, resolve_contained_path


DEFAULT_DATABASE_TARGET = "data/memory.db"


def _database_root(root: Path) -> Path:
    """Return the repository data root without authorizing a symlink root."""
    data_root = root / "data"
    if data_root.is_symlink():
        raise PathBoundaryError("database root is symlinked")
    if not data_root.is_dir():
        raise PathBoundaryError("database root is unavailable")
    return data_root


def resolve_database_target(
    requested: Optional[os.PathLike | str] = None,
    *,
    root: Optional[os.PathLike | str] = None,
) -> Path:
    """Resolve an approved database target beneath the repository data root.

    Both ``memory.db`` and the repository-relative ``data/memory.db`` spelling
    are accepted.  The returned path is absolute for the SQLite call, while
    all authorization is performed before it is returned.
    """
    repository = repository_root() if root is None else Path(root).resolve(strict=True)
    data_root = _database_root(repository)
    raw = DEFAULT_DATABASE_TARGET if requested is None else requested
    if not isinstance(raw, (str, os.PathLike)):
        raise PathBoundaryError("database target must be text")
    value = os.fspath(raw)
    if isinstance(value, bytes):
        raise PathBoundaryError("database target must be text")
    value = str(value).replace("\\", "/")
    parts = Path(value).parts
    if parts and parts[0] == "data":
        value = "/".join(parts[1:])
    if not value or Path(value).suffix.lower() != ".db":
        raise PathBoundaryError("database target must use the .db suffix")
    return resolve_contained_path(
        value,
        data_root,
        relative_only=True,
        allow_missing=True,
        reject_symlinks=True,
    )


def database_target_label(path: Path, *, root: Optional[os.PathLike | str] = None) -> str:
    """Return a stable repository-relative label without exposing host paths."""
    repository = repository_root() if root is None else Path(root).resolve(strict=True)
    relative = path.resolve(strict=False).relative_to((repository / "data").resolve(strict=True))
    return (Path("data") / relative).as_posix()


__all__ = ["DEFAULT_DATABASE_TARGET", "database_target_label", "resolve_database_target"]
