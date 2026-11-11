# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Byte-only prior-study baseline and Study 3b write-boundary helpers."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


PREP_ROOT_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study3b-prep"
)
STUDY3B_RUN_ROOT_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study3b"
)
BASELINE_PATH_RELATIVE = (
    PREP_ROOT_RELATIVE + "/prior-study-source-protocol-evidence-baseline.json"
)
_OFFLINE_EVIDENCE_ROOT = "tmp/router-rollout/mapping-pilot/mise-en-scene-offline"
_SOURCE_ROOT = "scripts/mise_en_scene"
_STUDY3B_SOURCE_ROOT = _SOURCE_ROOT + "/llm_staging_study3b"
_NEW_EVIDENCE_ROOTS = (
    _OFFLINE_EVIDENCE_ROOT + "/llm-staging-study3b-prep",
    _OFFLINE_EVIDENCE_ROOT + "/llm-staging-study3b",
)
_PROTOCOL_ROOTS = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation",
    "openspec/changes/v2-mise-en-scene-study3-contract-parity",
)
_SOURCE_INPUTS = (
    "modules/Into_the_Deepvault/areas/HA003_BU.json",
    "modules/Into_the_Deepvault/areas/SD005_BU.json",
    "modules/Xhalruuns_Masquerade/areas/TSU001_BU.json",
)
_PLAN_INPUTS = ("plans/v2-mapping-pilot.md",)
_VALID_SCOPES = frozenset({"source", "protocol", "evidence"})
_VALID_ACTIONS = frozenset(
    {"write", "reset", "replay", "append", "delete", "rename", "truncate"}
)
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


class BaselineScopeError(RuntimeError):
    """Raised when a baseline path cannot be safely inventoried."""


class BaselinePathRejected(BaselineScopeError):
    """Raised when traversal or a symlink violates a rooted path contract."""


class BaselineFileInvalid(BaselineScopeError):
    """Raised when a rooted path names a non-regular file."""


class PriorStudyMutationDenied(BaseException):
    """Uncatchable-by-ordinary-Exception sentinel for prior-study mutations."""


def _repository_root(repository_root: Path | str | None = None) -> Path:
    if repository_root is not None:
        raw = os.fspath(repository_root)
        if type(raw) is not str or "\\" in raw:
            raise BaselineScopeError("Repository root is invalid")
        if not os.path.isabs(raw):
            raw = os.path.join(os.getcwd(), raw)
        return Path(os.path.normpath(raw))
    return Path(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    )


def _relative_parts(relative_path: object) -> tuple[str, ...]:
    if type(relative_path) is not str or not relative_path or "\\" in relative_path:
        raise ValueError("Baseline path is invalid")
    parts = tuple(relative_path.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Baseline path is invalid")
    return parts


def _absolute_relative_parts(root: Path, path: object) -> tuple[str, ...]:
    try:
        raw = os.fspath(path)
    except (TypeError, ValueError, OSError):
        raise ValueError("Path is invalid") from None
    if type(raw) is not str or not raw or "\\" in raw or "\x00" in raw:
        raise ValueError("Path is invalid")
    if ".." in raw.split(os.sep):
        raise ValueError("Path traversal is invalid")
    root_text = os.path.normcase(os.path.normpath(os.fspath(root)))
    if os.path.isabs(raw):
        normalized = os.path.normcase(os.path.normpath(raw))
        if normalized != os.path.normcase(raw):
            raise ValueError("Path is not lexical")
        try:
            if os.path.commonpath((normalized, root_text)) != root_text:
                raise ValueError("Path is outside the repository")
        except (ValueError, OSError):
            raise ValueError("Path is outside the repository") from None
        relative = os.path.relpath(normalized, root_text).replace(os.sep, "/")
    else:
        relative = raw
    return _relative_parts(relative)


def _open_root_directory(root: Path) -> int:
    descriptor = os.open(os.fspath(root), _DIRECTORY_FLAGS)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise BaselineScopeError("Repository root is not a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_child_directory(parent_fd: int, name: str) -> int:
    if "/" in name or name in ("", ".", ".."):
        raise BaselinePathRejected("Unsafe directory component")
    named_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(named_before.st_mode):
        raise BaselinePathRejected("Symlink in rooted path")
    if not stat.S_ISDIR(named_before.st_mode):
        raise BaselineScopeError("Non-directory or symlink in baseline scope")
    descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_ISLNK(named_after.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (named_before.st_dev, named_before.st_ino)
            or (named_after.st_dev, named_after.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise BaselineScopeError("Directory changed while opening")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_directory_parts(root_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            child = _open_child_directory(descriptor, part)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _stat_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_or_hash_regular_file(
    root_fd: int,
    relative_path: str,
    *,
    digest: Any | None = None,
) -> tuple[bytes | None, os.stat_result, str | None]:
    parts = _relative_parts(relative_path)
    parent_fd = _open_directory_parts(root_fd, parts[:-1])
    descriptor: int | None = None
    try:
        name = parts[-1]
        named_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(named_before.st_mode):
            raise BaselinePathRejected("Symlink in rooted file path")
        if not stat.S_ISREG(named_before.st_mode):
            raise BaselineFileInvalid("Rooted path is not a regular file")
        descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
        before = os.fstat(descriptor)
        named_after_open = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(named_after_open.st_mode)
            or (before.st_dev, before.st_ino)
            != (named_before.st_dev, named_before.st_ino)
            or (named_after_open.st_dev, named_after_open.st_ino)
            != (before.st_dev, before.st_ino)
        ):
            raise BaselinePathRejected("File changed while opening")

        chunks: list[bytes] | None = [] if digest is None else None
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            if digest is not None:
                digest.update(chunk)
            else:
                assert chunks is not None
                chunks.append(chunk)

        after = os.fstat(descriptor)
        named_after_read = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _stat_identity(before) != _stat_identity(after)
            or (named_after_read.st_dev, named_after_read.st_ino)
            != (after.st_dev, after.st_ino)
        ):
            raise BaselinePathRejected("File changed while reading")
        raw = None if chunks is None else b"".join(chunks)
        return raw, before, None if digest is None else digest.hexdigest()
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def _read_file_at_root(root_fd: int, relative_path: str) -> bytes:
    raw, _metadata, _digest = _read_or_hash_regular_file(
        root_fd, relative_path
    )
    assert raw is not None
    return raw


def _read_project_file(repository_root: Path | str, relative_path: str) -> bytes:
    root = _repository_root(repository_root)
    parts = _relative_parts(relative_path)
    root_fd = _open_root_directory(root)
    try:
        return _read_file_at_root(root_fd, "/".join(parts))
    finally:
        os.close(root_fd)


def _make_directory_parts(
    root_fd: int, parts: tuple[str, ...], *, mode: int = 0o700
) -> int:
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            try:
                child = _open_child_directory(descriptor, part)
            except FileNotFoundError:
                os.mkdir(part, mode, dir_fd=descriptor)
                child = _open_child_directory(descriptor, part)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _assert_no_symlink_path(
    root: Path, parts: tuple[str, ...], *, allow_missing_leaf: bool
) -> None:
    root_fd = _open_root_directory(root)
    current_fd = root_fd
    try:
        for index, part in enumerate(parts):
            try:
                named = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                if allow_missing_leaf:
                    return
                raise
            if stat.S_ISLNK(named.st_mode):
                raise BaselinePathRejected("Symlink in protected path")
            if index < len(parts) - 1:
                child_fd = _open_child_directory(current_fd, part)
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = child_fd
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _scoped_roots(repository_fd: int) -> list[tuple[str, str]]:
    roots: list[tuple[str, str]] = [(_SOURCE_ROOT, "source")]
    scripts_fd = _open_directory_parts(repository_fd, ("scripts",))
    try:
        for name in sorted(os.listdir(scripts_fd)):
            if not name.startswith("test_mise_en_scene") or name.startswith(
                "test_mise_en_scene_study3b_"
            ):
                continue
            named = os.stat(name, dir_fd=scripts_fd, follow_symlinks=False)
            if stat.S_ISLNK(named.st_mode):
                raise BaselineScopeError("Symlink encountered in prior-study scope")
            if stat.S_ISREG(named.st_mode):
                roots.append(("scripts/" + name, "source"))
    finally:
        os.close(scripts_fd)
    roots.extend((path, "source") for path in _SOURCE_INPUTS)
    roots.extend((path, "protocol") for path in _PROTOCOL_ROOTS)
    roots.extend((path, "protocol") for path in _PLAN_INPUTS)
    roots.append((_OFFLINE_EVIDENCE_ROOT, "evidence"))
    return roots


def _iter_scoped_files(
    repository_fd: int, relative_root: str, scope: str
) -> Iterator[tuple[str, str]]:
    parts = _relative_parts(relative_root)
    parent_fd = _open_directory_parts(repository_fd, parts[:-1])
    root_name = parts[-1]
    try:
        root_stat = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
    except BaseException:
        os.close(parent_fd)
        raise
    if stat.S_ISLNK(root_stat.st_mode):
        os.close(parent_fd)
        raise BaselineScopeError("Symlink encountered in prior-study scope")
    if stat.S_ISREG(root_stat.st_mode):
        os.close(parent_fd)
        yield relative_root, scope
        return
    if not stat.S_ISDIR(root_stat.st_mode):
        os.close(parent_fd)
        raise BaselineScopeError("Non-file baseline root encountered")

    try:
        root_directory_fd = _open_child_directory(parent_fd, root_name)
    finally:
        os.close(parent_fd)
    pending: list[tuple[int, str]] = [(root_directory_fd, relative_root)]
    try:
        while pending:
            current_fd, relative_current = pending.pop()
            try:
                for name in sorted(os.listdir(current_fd), reverse=True):
                    if relative_current == _SOURCE_ROOT and name == "llm_staging_study3b":
                        continue
                    if relative_current == _OFFLINE_EVIDENCE_ROOT and name in {
                        Path(path).name for path in _NEW_EVIDENCE_ROOTS
                    }:
                        continue
                    named = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                    if stat.S_ISLNK(named.st_mode):
                        raise BaselineScopeError(
                            "Symlink encountered in prior-study scope"
                        )
                    relative = relative_current + "/" + name
                    if stat.S_ISDIR(named.st_mode):
                        pending.append((_open_child_directory(current_fd, name), relative))
                    elif stat.S_ISREG(named.st_mode):
                        yield relative, scope
                    else:
                        raise BaselineScopeError(
                            "Non-regular file in prior-study scope"
                        )
            finally:
                os.close(current_fd)
    finally:
        for descriptor in pending:
            os.close(descriptor[0])


def _opaque_bytes_path(relative_path: str) -> bool:
    normalized = "/" + relative_path.lower().strip("/") + "/"
    name = Path(relative_path).name.lower()
    return ("response" in name and "metadata" not in name) or "/responses/" in normalized


def build_prior_study_baseline(
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    """Hash every prior source, protocol, and evidence file as opaque bytes."""

    root = _repository_root(repository_root)
    entries_by_path: dict[str, dict[str, Any]] = {}
    scanned_roots: list[str] = []
    repository_fd = _open_root_directory(root)
    try:
        for relative_root, scope in _scoped_roots(repository_fd):
            try:
                files = _iter_scoped_files(repository_fd, relative_root, scope)
                for relative_path, file_scope in files:
                    digest = hashlib.sha256()
                    try:
                        _raw, before, digest_text = _read_or_hash_regular_file(
                            repository_fd, relative_path, digest=digest
                        )
                    except OSError as exc:
                        raise BaselineScopeError(
                            "Unable to hash prior-study file"
                        ) from exc
                    if digest_text is None:
                        raise BaselineScopeError("Prior-study hash was not produced")
                    if relative_path in entries_by_path:
                        raise BaselineScopeError(
                            "Overlapping baseline roots encountered"
                        )
                    entries_by_path[relative_path] = {
                        "path": relative_path,
                        "size_bytes": before.st_size,
                        "sha256": digest_text,
                        "scope": file_scope,
                        "opaque_bytes": _opaque_bytes_path(relative_path),
                    }
            except FileNotFoundError as exc:
                raise BaselineScopeError(
                    "Required prior-study baseline root is missing"
                ) from exc
            scanned_roots.append(relative_root)
    finally:
        os.close(repository_fd)

    entries = [entries_by_path[path] for path in sorted(entries_by_path)]
    return {
        "format": "neq-prior-study-byte-baseline-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "path_base": ".",
        "scanned_roots": scanned_roots,
        "excluded_new_study3b_roots": list(_NEW_EVIDENCE_ROOTS),
        "file_count": len(entries),
        "opaque_bytes_count": sum(1 for entry in entries if entry["opaque_bytes"]),
        "files": entries,
    }


def validate_baseline_metadata(payload: object) -> dict[str, Any]:
    """Validate the metadata-only baseline contract without opening source files."""

    if type(payload) is not dict:
        raise ValueError("Baseline must be a JSON object")
    required_keys = {
        "format",
        "created_at_utc",
        "path_base",
        "scanned_roots",
        "excluded_new_study3b_roots",
        "file_count",
        "opaque_bytes_count",
        "files",
    }
    if set(payload) != required_keys:
        raise ValueError("Baseline contains unexpected or missing metadata fields")
    if payload["format"] != "neq-prior-study-byte-baseline-v1":
        raise ValueError("Unsupported baseline format")
    if payload["path_base"] != ".":
        raise ValueError("Baseline paths must be project-relative")
    if type(payload["created_at_utc"]) is not str:
        raise ValueError("Baseline timestamp must be metadata text")
    if type(payload["scanned_roots"]) is not list or type(
        payload["excluded_new_study3b_roots"]
    ) is not list:
        raise ValueError("Baseline roots must be metadata lists")
    if type(payload["file_count"]) is not int or type(
        payload["opaque_bytes_count"]
    ) is not int:
        raise ValueError("Baseline counts must be integers")
    if type(payload["files"]) is not list:
        raise ValueError("Baseline files must be a list")

    previous_path = ""
    opaque_count = 0
    file_keys = {"path", "size_bytes", "sha256", "scope", "opaque_bytes"}
    for entry in payload["files"]:
        if type(entry) is not dict or set(entry) != file_keys:
            raise ValueError("Baseline entries must contain metadata and hashes only")
        path = entry["path"]
        if type(path) is not str or not path or path.startswith("/"):
            raise ValueError("Baseline file paths must be project-relative")
        path_parts = Path(path).parts
        if ".." in path_parts or "\\" in path:
            raise ValueError("Baseline file path is not normalized")
        if path <= previous_path:
            raise ValueError("Baseline file paths must be unique and sorted")
        previous_path = path
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0:
            raise ValueError("Baseline file size must be a non-negative integer")
        digest = entry["sha256"]
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("Baseline SHA-256 must be lowercase hexadecimal")
        scope = entry["scope"]
        if type(scope) is not str or scope not in _VALID_SCOPES:
            raise ValueError("Baseline scope is invalid")
        if type(entry["opaque_bytes"]) is not bool:
            raise ValueError("Baseline opaque-byte marker must be boolean")
        opaque_count += int(entry["opaque_bytes"])
    if payload["file_count"] != len(payload["files"]):
        raise ValueError("Baseline file count does not match entries")
    if payload["opaque_bytes_count"] != opaque_count:
        raise ValueError("Baseline opaque-byte count does not match entries")
    return payload


def read_baseline_metadata(
    path: Path | str = BASELINE_PATH_RELATIVE,
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    """Read and validate the JSON metadata file, never response artifacts."""

    root = _repository_root(repository_root)
    try:
        parts = _absolute_relative_parts(root, path)
    except ValueError as exc:
        raise ValueError("Baseline metadata path is invalid") from exc
    root_fd: int | None = None
    try:
        root_fd = _open_root_directory(root)
        raw = _read_file_at_root(root_fd, "/".join(parts))
        payload = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError, BaselineScopeError) as exc:
        raise ValueError("Unable to read prior-study baseline metadata") from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
    return validate_baseline_metadata(payload)


def write_baseline_exclusive(
    repository_root: Path | str | None = None,
    output_path: Path | str = BASELINE_PATH_RELATIVE,
) -> Path:
    """Create the byte baseline once; an existing file is never replaced."""

    root = _repository_root(repository_root)
    payload = build_prior_study_baseline(root)
    validate_baseline_metadata(payload)
    parts = _absolute_relative_parts(root, output_path)
    destination = root.joinpath(*parts)
    assert_study3b_write_target(destination, repository_root=root, action="write")
    encoded = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode(
        "ascii"
    )
    root_fd: int | None = None
    parent_fd: int | None = None
    file_descriptor: int | None = None
    created = False
    try:
        root_fd = _open_root_directory(root)
        parent_fd = _make_directory_parts(root_fd, parts[:-1])
        file_descriptor = os.open(
            parts[-1],
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        created = True
        offset = 0
        while offset < len(encoded):
            written = os.write(file_descriptor, encoded[offset:])
            if written <= 0:
                raise OSError("short baseline metadata write")
            offset += written
        os.fsync(file_descriptor)
        os.fsync(parent_fd)
    except BaseException:
        if created and parent_fd is not None:
            try:
                os.unlink(parts[-1], dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if parent_fd is not None:
            os.close(parent_fd)
        if root_fd is not None:
            os.close(root_fd)
    return destination


def _path_forms(path: object, repository_root: Path) -> tuple[str, ...]:
    try:
        parts = _absolute_relative_parts(repository_root, path)
    except (TypeError, ValueError, OSError):
        return ()
    lexical = os.path.normcase(
        os.path.normpath(os.fspath(repository_root.joinpath(*parts)))
    )
    return (lexical,)


def _under(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath((candidate, root)) == root
    except (ValueError, OSError):
        return False


def _is_prior_study_path(candidate: str, repository_root: Path) -> bool:
    repo_base = os.path.normcase(os.path.normpath(os.fspath(repository_root)))
    if not _under(candidate, repo_base):
        return False
    relative = os.path.relpath(candidate, repo_base).replace(os.sep, "/")

    if relative == _SOURCE_ROOT or relative.startswith(_SOURCE_ROOT + "/"):
        if relative != _STUDY3B_SOURCE_ROOT and not relative.startswith(
            _STUDY3B_SOURCE_ROOT + "/"
        ):
            return True
    if relative.startswith("scripts/test_mise_en_scene_") and not relative.startswith(
        "scripts/test_mise_en_scene_study3b_"
    ):
        return True
    for protected_root in _PROTOCOL_ROOTS:
        if relative == protected_root or relative.startswith(protected_root + "/"):
            return True
    for protected_path in (*_SOURCE_INPUTS, *_PLAN_INPUTS):
        if relative == protected_path:
            return True
    if relative == _OFFLINE_EVIDENCE_ROOT or relative.startswith(
        _OFFLINE_EVIDENCE_ROOT + "/"
    ):
        for allowed_root in _NEW_EVIDENCE_ROOTS:
            if relative == allowed_root or relative.startswith(allowed_root + "/"):
                return False
        return True
    return False


def assert_study3b_write_target(
    path: object,
    repository_root: Path | str | None = None,
    action: str = "write",
) -> None:
    """Reject prior-tree and outside-repository mutations at the helper boundary.

    This helper is not yet wired into Study 3b runtime or ledger entrypoints.
    Each later write entrypoint must invoke it or provide equivalent fail-closed
    protection; integration is verified under tasks 2.2 and 2.3.
    """

    if action not in _VALID_ACTIONS:
        raise ValueError("Unsupported write-boundary action")
    root = _repository_root(repository_root)
    candidates = _path_forms(path, root)
    if not candidates:
        raise PriorStudyMutationDenied("Study 3b write target could not be normalized")
    repo_lexical = os.path.normcase(os.path.normpath(os.fspath(root)))
    if any(not _under(candidate, repo_lexical) for candidate in candidates):
        raise PriorStudyMutationDenied(
            "Study 3b write target is outside the repository (action=" + action + ")"
        )
    if any(_is_prior_study_path(candidate, root) for candidate in candidates):
        raise PriorStudyMutationDenied(
            "Study 1/2/3 paths are immutable for Study 3b (action=" + action + ")"
        )
    try:
        parts = _absolute_relative_parts(root, path)
        if not parts:
            raise ValueError("Repository root cannot be a write target")
        _assert_no_symlink_path(root, parts, allow_missing_leaf=True)
    except (OSError, ValueError, BaselineScopeError):
        raise PriorStudyMutationDenied(
            "Study 3b write target is unsafe (action=" + action + ")"
        ) from None
