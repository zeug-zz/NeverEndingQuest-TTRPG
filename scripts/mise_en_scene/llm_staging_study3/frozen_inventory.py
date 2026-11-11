# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Verify Study 1/2 frozen trees using only relative paths, sizes, and hashes.

The frozen source-code baseline lists only authored source files. Python may
create ephemeral ``__pycache__/*.pyc`` files while tests or tools run, so those
files alone are excluded in source roots. Every other regular file, regardless
of suffix or directory, is inventoried; runtime and protocol roots include
their bytecode caches as frozen artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_INVENTORY_SHA256 = "ee19b7f7e62f857fbd84c08253f52c4c9cba312f5bf1a8bc97fbab5b09a48db7"
FROZEN_FILE_COUNTS = {
    "study1_protocol": 16,
    "study1_runtime": 54,
    "study1_source_code": 6,
    "study2_protocol": 13,
    "study2_runtime": 174,
    "study2_source_code": 8,
}
FROZEN_ROOTS = {
    "study1_protocol": (
        "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
        "llm-staging-protocol",
        False,
    ),
    "study1_runtime": (
        "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging",
        False,
    ),
    "study1_source_code": ("scripts/mise_en_scene/llm_staging", True),
    "study2_protocol": (
        "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
        "llm-staging-study2/protocol",
        False,
    ),
    "study2_runtime": (
        "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2",
        False,
    ),
    "study2_source_code": ("scripts/mise_en_scene/llm_staging_study2", True),
}
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_HASH_CHUNK_BYTES = 1024 * 1024


class FrozenInventoryError(RuntimeError):
    """Metadata-only failure from the immutable Study 1/2 tree audit."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def verify_frozen_inventories() -> dict[str, Any]:
    """Return a metadata-only summary only when every frozen byte matches."""

    inventories: dict[str, dict[str, dict[str, Any]]] = {}
    try:
        for group, (relative_root, exclude_ephemeral_pycache) in FROZEN_ROOTS.items():
            inventories[group] = _scan_tree(
                relative_root,
                exclude_ephemeral_pycache=exclude_ephemeral_pycache,
            )
    except FrozenInventoryError:
        raise
    except (OSError, ValueError, RecursionError):
        raise FrozenInventoryError("FROZEN_INVENTORY_UNAVAILABLE") from None

    if any(
        len(inventories.get(group, {})) != expected_count
        for group, expected_count in FROZEN_FILE_COUNTS.items()
    ):
        raise FrozenInventoryError("FROZEN_INVENTORY_FILE_COUNT_MISMATCH")

    digest = hashlib.sha256(_canonical_bytes(inventories)).hexdigest()
    if digest != FROZEN_INVENTORY_SHA256:
        raise FrozenInventoryError("FROZEN_INVENTORY_HASH_MISMATCH")
    return {
        "status": "PASS",
        "inventory_sha256": digest,
        "file_counts": dict(FROZEN_FILE_COUNTS),
    }


def _scan_tree(
    relative_root: str,
    *,
    exclude_ephemeral_pycache: bool,
) -> dict[str, dict[str, Any]]:
    parts = Path(relative_root).parts
    if not parts or Path(relative_root).is_absolute() or ".." in parts:
        raise FrozenInventoryError("FROZEN_INVENTORY_ROOT_INVALID")
    directory_fd: int | None = None
    try:
        directory_fd = os.open(REPO_ROOT, _DIRECTORY_FLAGS)
        for part in parts:
            metadata = os.stat(part, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise FrozenInventoryError("FROZEN_INVENTORY_PATH_UNSAFE")
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory_fd)
            opened = os.fstat(next_fd)
            named = os.stat(part, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                os.close(next_fd)
                raise FrozenInventoryError("FROZEN_INVENTORY_PATH_UNSAFE")
            os.close(directory_fd)
            directory_fd = next_fd

        rows: dict[str, dict[str, Any]] = {}
        _scan_directory(
            directory_fd,
            "",
            rows,
            exclude_ephemeral_pycache=exclude_ephemeral_pycache,
        )
        return rows
    except FrozenInventoryError:
        raise
    except FileNotFoundError:
        raise FrozenInventoryError("FROZEN_INVENTORY_ROOT_MISSING") from None
    except (OSError, ValueError, RecursionError):
        raise FrozenInventoryError("FROZEN_INVENTORY_UNAVAILABLE") from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _scan_directory(
    directory_fd: int,
    prefix: str,
    rows: dict[str, dict[str, Any]],
    *,
    exclude_ephemeral_pycache: bool,
) -> None:
    for name in sorted(os.listdir(directory_fd)):
        relative = name if not prefix else prefix + "/" + name
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(metadata.st_mode):
            raise FrozenInventoryError("FROZEN_INVENTORY_SYMLINK_PRESENT")
        if stat.S_ISDIR(metadata.st_mode):
            child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
            opened = os.fstat(child_fd)
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                os.close(child_fd)
                raise FrozenInventoryError("FROZEN_INVENTORY_PATH_UNSAFE")
            try:
                _scan_directory(
                    child_fd,
                    relative,
                    rows,
                    exclude_ephemeral_pycache=exclude_ephemeral_pycache,
                )
                opened_after = os.fstat(child_fd)
                named_after = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISLNK(named_after.st_mode)
                    or (opened_after.st_dev, opened_after.st_ino)
                    != (opened.st_dev, opened.st_ino)
                    or (named_after.st_dev, named_after.st_ino)
                    != (opened.st_dev, opened.st_ino)
                ):
                    raise FrozenInventoryError("FROZEN_INVENTORY_PATH_CHANGED")
            finally:
                os.close(child_fd)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise FrozenInventoryError("FROZEN_INVENTORY_SPECIAL_FILE_PRESENT")
        parent_parts = relative.split("/")[:-1]
        if (
            exclude_ephemeral_pycache
            and "__pycache__" in parent_parts
            and name.endswith(".pyc")
        ):
            continue
        rows[relative] = _hash_file(directory_fd, name, metadata)


def _hash_file(
    directory_fd: int,
    name: str,
    named_metadata: os.stat_result,
) -> dict[str, Any]:
    file_fd: int | None = None
    try:
        file_fd = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
        opened = os.fstat(file_fd)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(named_after.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (named_metadata.st_dev, named_metadata.st_ino)
            or (opened.st_dev, opened.st_ino)
            != (named_after.st_dev, named_after.st_ino)
        ):
            raise FrozenInventoryError("FROZEN_INVENTORY_FILE_CHANGED")
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(file_fd, _HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after_read = os.fstat(file_fd)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            size != opened.st_size
            or (after_read.st_dev, after_read.st_ino)
            != (opened.st_dev, opened.st_ino)
            or (named_after.st_dev, named_after.st_ino)
            != (opened.st_dev, opened.st_ino)
            or stat.S_ISLNK(named_after.st_mode)
            or after_read.st_mtime_ns != opened.st_mtime_ns
            or after_read.st_ctime_ns != opened.st_ctime_ns
        ):
            raise FrozenInventoryError("FROZEN_INVENTORY_FILE_CHANGED")
        return {"bytes": size, "sha256": digest.hexdigest()}
    except FrozenInventoryError:
        raise
    except (OSError, ValueError):
        raise FrozenInventoryError("FROZEN_INVENTORY_FILE_UNAVAILABLE") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def main(argv: list[str] | None = None) -> int:
    """Expose the frozen inventory as a hash-only preflight gate."""

    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        print('{"reason_code":"FROZEN_INVENTORY_ARGUMENTS_INVALID","status":"BLOCKED"}')
        return 2
    try:
        report = verify_frozen_inventories()
    except FrozenInventoryError as error:
        report = {"reason_code": error.code, "status": "BLOCKED"}
        print(_canonical_bytes(report).decode("ascii"))
        return 1
    print(_canonical_bytes(report).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FROZEN_FILE_COUNTS",
    "FROZEN_INVENTORY_SHA256",
    "FrozenInventoryError",
    "main",
    "verify_frozen_inventories",
]
