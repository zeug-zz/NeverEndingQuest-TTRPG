# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Staging Targets
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, attempt-scoped output targets for the explicit LLM adaptation
builder lane. A target is reserved once and is never reused or overwritten.
The helper does not publish modules or touch registry, campaign, or runtime
state.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root for full terms.
"""

from __future__ import annotations

import re
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Optional, Tuple

from utils.file_operations import safe_read_json, safe_write_json
from utils.toolkit_adaptation_artifacts import build_attempt_id


ADAPTATION_STAGING_CONTRACT_VERSION = "toolkit_adaptation_staging.v1"
DEFAULT_ADAPTATION_STAGING_ROOT = "tmp/adaptation-staging"
STAGING_TARGET_KIND = "staging"
STAGING_METADATA_FILENAME = "staging_metadata.json"

STAGING_STATE_RESERVED = "reserved"
STAGING_STATE_BUILDING = "building"
STAGING_STATE_COMPLETED = "completed"
STAGING_STATE_FAILED = "failed"
STAGING_STATE_CLEANED = "cleaned"
VALID_STAGING_STATES = frozenset(
    {
        STAGING_STATE_RESERVED,
        STAGING_STATE_BUILDING,
        STAGING_STATE_COMPLETED,
        STAGING_STATE_FAILED,
        STAGING_STATE_CLEANED,
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_MAX_METADATA_TEXT = 240


class AdaptationStagingError(ValueError):
    """Base error for invalid or unsafe adaptation staging requests."""


class AdaptationStagingTargetExistsError(AdaptationStagingError):
    """Raised when an attempt/revision target already exists."""


def _utc_now_iso() -> str:
    """Return a second-precision UTC timestamp."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ascii_text(value: Any, limit: int = _MAX_METADATA_TEXT) -> str:
    """Return bounded ASCII metadata text."""
    text = str(value or "").strip().encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _repo_root(repo_root: Optional[Path]) -> Path:
    """Resolve the trusted project root used for derived filesystem paths."""
    if repo_root is None:
        return Path(__file__).resolve().parents[1]
    return Path(repo_root).resolve()


def _is_within(path: Path, parent: Path) -> bool:
    """Return whether ``path`` is equal to or below ``parent``."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_relative_path(value: Any, field_name: str) -> str:
    """Validate a project-relative POSIX path segment sequence."""
    if not isinstance(value, (str, Path)):
        raise AdaptationStagingError(f"{field_name} must be project-relative")
    text = str(value).strip()
    if (
        not text
        or text in {".", ".."}
        or "\x00" in text
        or "\\" in text
        or text.startswith("/")
        or _DRIVE_PATH_RE.match(text)
    ):
        raise AdaptationStagingError(f"{field_name} must be project-relative")
    raw_parts = text.split("/")
    if any(not part or part in {".", ".."} for part in raw_parts):
        raise AdaptationStagingError(f"{field_name} contains an unsafe path segment")
    return PurePosixPath(*raw_parts).as_posix()


def _validate_staging_root(staging_root: Any, repo_root: Path) -> Tuple[Path, str]:
    """Validate and resolve an explicit staging root inside the project."""
    relative_root = _validate_relative_path(staging_root, "staging_root")
    root = (repo_root / Path(*PurePosixPath(relative_root).parts)).resolve()
    if not _is_within(root, repo_root):
        raise AdaptationStagingError("staging_root resolves outside the project")

    # Adaptation staging must never be placed in live module or runtime roots.
    if _is_within(root, (repo_root / "modules").resolve()):
        raise AdaptationStagingError("staging_root cannot be inside modules")
    if _is_within(root, (repo_root / "characters").resolve()):
        raise AdaptationStagingError("staging_root cannot be inside characters")
    if _is_within(root, (repo_root / "data").resolve()):
        raise AdaptationStagingError("staging_root cannot be inside data")
    return root, relative_root


def _validate_source_hash(source_hash: Any) -> str:
    if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash):
        raise AdaptationStagingError("source_hash must be a lowercase SHA-256 digest")
    return source_hash


def _validate_attempt_id(attempt_id: Any) -> str:
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise AdaptationStagingError("attempt_id is not path-safe")
    return attempt_id


def _validate_attempt_number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1_000_000:
        raise AdaptationStagingError("attempt_number is outside the supported range")
    return value


def _validate_revision_number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise AdaptationStagingError("revision_number is outside the supported range")
    return value


def _validate_module_slug(value: Any) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not _MODULE_SLUG_RE.fullmatch(value):
        raise AdaptationStagingError("module_slug is not path-safe")
    return value


def _validate_optional_source_path(value: Any) -> str:
    if value in (None, ""):
        return ""
    return _validate_relative_path(value, "source_path")


def _target_path(
    root: Path,
    relative_root: str,
    attempt_id: str,
    revision_number: int,
    repo_root: Path,
) -> Tuple[Path, str]:
    """Build and validate the exact attempt/revision target path."""
    target = root / attempt_id / f"revision_{revision_number:03d}"
    resolved_target = target.resolve()
    if not _is_within(resolved_target, root):
        raise AdaptationStagingError("staging target resolves outside staging_root")
    if _is_within(resolved_target, (repo_root / "modules").resolve()):
        raise AdaptationStagingError("staging target cannot be inside modules")
    relative_path = resolved_target.relative_to(repo_root).as_posix()
    return resolved_target, relative_path


def _validated_target_metadata(
    target: Mapping[str, Any],
    *,
    repo_root: Optional[Path] = None,
    expected_source_hash: Optional[str] = None,
    expected_attempt_id: Optional[str] = None,
    expected_attempt_number: Optional[int] = None,
    expected_module_slug: Optional[str] = None,
    expected_revision_number: Optional[int] = None,
    require_reserved: bool = False,
) -> Tuple[Dict[str, Any], Path]:
    """Validate a target envelope and derive its filesystem path."""
    if not isinstance(target, Mapping):
        raise AdaptationStagingError("staging target metadata must be an object")
    root_path = _repo_root(repo_root)
    if target.get("contract_version") != ADAPTATION_STAGING_CONTRACT_VERSION:
        raise AdaptationStagingError("unsupported staging target contract")
    if target.get("target_kind") != STAGING_TARGET_KIND:
        raise AdaptationStagingError("unsupported staging target kind")
    if target.get("completion_state") not in VALID_STAGING_STATES:
        raise AdaptationStagingError("staging target completion state is invalid")
    source_hash = _validate_source_hash(target.get("source_hash"))
    attempt_id = _validate_attempt_id(target.get("attempt_id"))
    attempt_number = _validate_attempt_number(target.get("attempt_number"))
    revision_number = _validate_revision_number(target.get("revision_number"))
    module_slug = _validate_module_slug(target.get("module_slug", ""))
    staging_root, relative_root = _validate_staging_root(
        target.get("staging_root"), root_path
    )
    target_path, relative_path = _target_path(
        staging_root,
        relative_root,
        attempt_id,
        revision_number,
        root_path,
    )
    if target.get("path") != relative_path or target.get("output_directory") != relative_path:
        raise AdaptationStagingError("staging target path metadata does not match its identity")
    if target.get("stage_id") != f"{attempt_id}:revision_{revision_number:03d}":
        raise AdaptationStagingError("staging target stage_id does not match its identity")
    if expected_source_hash is not None and source_hash != _validate_source_hash(expected_source_hash):
        raise AdaptationStagingError("staging target source hash does not match the dossier")
    if expected_attempt_id is not None and attempt_id != _validate_attempt_id(expected_attempt_id):
        raise AdaptationStagingError("staging target attempt does not match the dossier")
    if expected_attempt_number is not None and attempt_number != _validate_attempt_number(expected_attempt_number):
        raise AdaptationStagingError("staging target attempt number does not match the dossier")
    if expected_module_slug is not None and module_slug != _validate_module_slug(expected_module_slug):
        raise AdaptationStagingError("staging target module slug does not match the dossier")
    if expected_revision_number is not None and revision_number != _validate_revision_number(expected_revision_number):
        raise AdaptationStagingError("staging target revision does not match the requested revision")
    if require_reserved and target.get("completion_state") != STAGING_STATE_RESERVED:
        raise AdaptationStagingError("staging target is already in use")
    normalized = deepcopy(dict(target))
    normalized.update(
        {
            "source_hash": source_hash,
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "revision_number": revision_number,
            "module_slug": module_slug,
            "staging_root": relative_root,
            "path": relative_path,
            "output_directory": relative_path,
        }
    )
    return normalized, target_path


def get_adaptation_staging_target_path(
    *,
    source_hash: str,
    attempt_id: Optional[str] = None,
    attempt_number: int = 1,
    revision_number: int = 0,
    job_id: str = "",
    staging_root: str = DEFAULT_ADAPTATION_STAGING_ROOT,
    repo_root: Optional[Path] = None,
) -> Path:
    """Return a safe target path without creating or reusing it."""
    trusted_root = _repo_root(repo_root)
    digest = _validate_source_hash(source_hash)
    number = _validate_attempt_number(attempt_number)
    revision = _validate_revision_number(revision_number)
    resolved_attempt_id = (
        build_attempt_id(digest, number, _ascii_text(job_id, 160))
        if attempt_id is None
        else _validate_attempt_id(attempt_id)
    )
    root, relative_root = _validate_staging_root(staging_root, trusted_root)
    target, _ = _target_path(
        root,
        relative_root,
        resolved_attempt_id,
        revision,
        trusted_root,
    )
    return target


def create_adaptation_staging_target(
    source_hash: str,
    *,
    attempt_id: Optional[str] = None,
    attempt_number: int = 1,
    revision_number: int = 0,
    job_id: str = "",
    source_path: str = "",
    module_slug: str = "",
    staging_root: str = DEFAULT_ADAPTATION_STAGING_ROOT,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Reserve a fresh, deterministic staging target for one build revision.

    The target directory is created with exclusive directory semantics and a
    metadata marker is persisted before the caller can start ModuleBuilder.
    Existing targets, including stale partial targets, are never reused.
    """
    trusted_root = _repo_root(repo_root)
    digest = _validate_source_hash(source_hash)
    number = _validate_attempt_number(attempt_number)
    revision = _validate_revision_number(revision_number)
    resolved_attempt_id = (
        build_attempt_id(digest, number, _ascii_text(job_id, 160))
        if attempt_id is None
        else _validate_attempt_id(attempt_id)
    )
    safe_source_path = _validate_optional_source_path(source_path)
    safe_module_slug = _validate_module_slug(module_slug)
    root, relative_root = _validate_staging_root(staging_root, trusted_root)
    target, relative_path = _target_path(
        root,
        relative_root,
        resolved_attempt_id,
        revision,
        trusted_root,
    )
    if target.exists() or target.is_symlink():
        raise AdaptationStagingTargetExistsError(
            "staging target already exists for this attempt and revision"
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir()
    except FileExistsError as exc:
        raise AdaptationStagingTargetExistsError(
            "staging target already exists for this attempt and revision"
        ) from exc
    except Exception as exc:
        raise AdaptationStagingError("staging target could not be created") from exc

    created_at = _utc_now_iso()
    metadata: Dict[str, Any] = {
        "contract_version": ADAPTATION_STAGING_CONTRACT_VERSION,
        "target_kind": STAGING_TARGET_KIND,
        "stage_id": f"{resolved_attempt_id}:revision_{revision:03d}",
        "attempt_id": resolved_attempt_id,
        "attempt_number": number,
        "revision_number": revision,
        "source_hash": digest,
        "source_path": safe_source_path,
        "module_slug": safe_module_slug,
        "staging_root": relative_root,
        "path": relative_path,
        "output_directory": relative_path,
        "completion_state": STAGING_STATE_RESERVED,
        "created_at": created_at,
        "updated_at": created_at,
        "metadata_path": f"{relative_path}/{STAGING_METADATA_FILENAME}",
    }
    marker_path = target / STAGING_METADATA_FILENAME
    try:
        if not safe_write_json(str(marker_path), metadata, create_backup=False):
            raise AdaptationStagingError("staging metadata could not be persisted")
    except Exception:
        # Only remove the directory reserved by this call. Never walk up to
        # the attempt root, staging root, or any live module path.
        try:
            shutil.rmtree(target)
        except Exception:
            pass
        raise
    return metadata


def validate_adaptation_staging_target(
    target: Mapping[str, Any],
    *,
    source_hash: Optional[str] = None,
    attempt_id: Optional[str] = None,
    attempt_number: Optional[int] = None,
    module_slug: Optional[str] = None,
    revision_number: Optional[int] = None,
    repo_root: Optional[Path] = None,
    require_reserved: bool = True,
) -> Dict[str, Any]:
    """Validate an active target without allowing target reuse."""
    normalized, target_path = _validated_target_metadata(
        target,
        repo_root=repo_root,
        expected_source_hash=source_hash,
        expected_attempt_id=attempt_id,
        expected_attempt_number=attempt_number,
        expected_module_slug=module_slug,
        expected_revision_number=revision_number,
        require_reserved=require_reserved,
    )
    if not require_reserved and normalized.get("completion_state") not in {
        STAGING_STATE_RESERVED,
        STAGING_STATE_BUILDING,
    }:
        raise AdaptationStagingError("staging target is no longer active")
    if not target_path.is_dir() or target_path.is_symlink():
        raise AdaptationStagingError("staging target is not a safe directory")
    persisted = safe_read_json(str(target_path / STAGING_METADATA_FILENAME))
    if not isinstance(persisted, Mapping):
        raise AdaptationStagingError("staging target metadata is missing")
    persisted_normalized, _ = _validated_target_metadata(
        persisted,
        repo_root=repo_root,
        expected_source_hash=source_hash,
        expected_attempt_id=attempt_id,
        expected_attempt_number=attempt_number,
        expected_module_slug=module_slug,
        expected_revision_number=revision_number,
    )
    if persisted_normalized.get("stage_id") != normalized.get("stage_id"):
        raise AdaptationStagingError("staging target metadata identity mismatch")
    return persisted_normalized


def update_adaptation_staging_target(
    target: Mapping[str, Any],
    completion_state: str,
    *,
    repo_root: Optional[Path] = None,
    error: str = "",
    output_hash: str = "",
) -> Dict[str, Any]:
    """Atomically update the completion state for a reserved target."""
    if completion_state not in VALID_STAGING_STATES:
        raise AdaptationStagingError("invalid staging completion state")
    normalized, target_path = _validated_target_metadata(target, repo_root=repo_root)
    if not target_path.is_dir() or target_path.is_symlink():
        raise AdaptationStagingError("staging target is not a safe directory")
    marker_path = target_path / STAGING_METADATA_FILENAME
    persisted = safe_read_json(str(marker_path))
    if not isinstance(persisted, Mapping):
        raise AdaptationStagingError("staging target metadata is missing")
    persisted_normalized, _ = _validated_target_metadata(
        persisted,
        repo_root=repo_root,
    )
    if persisted_normalized.get("stage_id") != normalized.get("stage_id"):
        raise AdaptationStagingError("staging target metadata identity mismatch")
    updated = deepcopy(dict(persisted_normalized))
    updated["completion_state"] = completion_state
    updated["updated_at"] = _utc_now_iso()
    if completion_state in {STAGING_STATE_COMPLETED, STAGING_STATE_FAILED}:
        updated["completed_at"] = updated["updated_at"]
    if error:
        updated["error"] = _ascii_text(error, 800)
    else:
        updated.pop("error", None)
    if output_hash:
        if not _SHA256_RE.fullmatch(output_hash):
            raise AdaptationStagingError("output_hash must be a lowercase SHA-256 digest")
        updated["output_hash"] = output_hash
    if not safe_write_json(str(marker_path), updated, create_backup=False):
        raise AdaptationStagingError("staging metadata update could not be persisted")
    return updated


def cleanup_adaptation_staging_target(
    target: Mapping[str, Any],
    *,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Remove only the exact newly-created staging target.

    Missing targets are a safe no-op. A symlink, live-module path, or invalid
    target envelope is never followed or removed.
    """
    normalized, target_path = _validated_target_metadata(target, repo_root=repo_root)
    if not target_path.exists():
        return {
            "status": "not_found",
            "stage_id": normalized["stage_id"],
            "path": normalized["path"],
        }
    if target_path.is_symlink() or not target_path.is_dir():
        return {
            "status": "cleanup_failed",
            "reason": "target_is_not_a_directory",
            "stage_id": normalized["stage_id"],
            "path": normalized["path"],
        }
    shutil.rmtree(target_path)
    return {
        "status": "cleaned",
        "stage_id": normalized["stage_id"],
        "path": normalized["path"],
    }


# Short aliases make the helper easy to discover without changing the
# explicit names used by the adaptation orchestration code.
reserve_adaptation_staging_target = create_adaptation_staging_target
get_staging_target_path = get_adaptation_staging_target_path
mark_adaptation_staging_target = update_adaptation_staging_target
cleanup_staging_target = cleanup_adaptation_staging_target


__all__ = [
    "ADAPTATION_STAGING_CONTRACT_VERSION",
    "DEFAULT_ADAPTATION_STAGING_ROOT",
    "STAGING_TARGET_KIND",
    "STAGING_METADATA_FILENAME",
    "STAGING_STATE_RESERVED",
    "STAGING_STATE_BUILDING",
    "STAGING_STATE_COMPLETED",
    "STAGING_STATE_FAILED",
    "STAGING_STATE_CLEANED",
    "VALID_STAGING_STATES",
    "AdaptationStagingError",
    "AdaptationStagingTargetExistsError",
    "create_adaptation_staging_target",
    "reserve_adaptation_staging_target",
    "get_adaptation_staging_target_path",
    "get_staging_target_path",
    "validate_adaptation_staging_target",
    "update_adaptation_staging_target",
    "mark_adaptation_staging_target",
    "cleanup_adaptation_staging_target",
    "cleanup_staging_target",
]
