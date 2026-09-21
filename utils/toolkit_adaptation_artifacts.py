# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Attempt Artifacts
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free contracts and atomic persistence for the LLM adaptation lane.
The artifacts are attempt-scoped diagnostics and provenance records. They are
not module files, runtime state, registry state, or source-of-truth gameplay
data.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root for full terms.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from utils.file_operations import safe_read_json, safe_write_json
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
    RIGHTS_REVIEW_REJECTED,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance

try:
    from jsonschema import Draft7Validator
except Exception:  # pragma: no cover - dependency availability is environment-specific
    Draft7Validator = None  # type: ignore[assignment,misc]


ADAPTATION_ARTIFACT_CONTRACT_VERSION = "toolkit_adaptation_artifact.v1"
ADAPTATION_ARTIFACT_SCHEMA_VERSION = ADAPTATION_ARTIFACT_CONTRACT_VERSION
ADAPTATION_ARTIFACT_ROOT = "adaptation_attempts"

ARTIFACT_KIND_SOURCE_CONTEXT = "source_context"
ARTIFACT_KIND_ADAPTATION_DOSSIER = "adaptation_dossier"
ARTIFACT_KIND_FAILURE_REPORT = "failure_report"
ARTIFACT_KIND_REVISION_REPORT = "revision_report"
ARTIFACT_KIND_BUILD_RESULT = "build_result"
ARTIFACT_KIND_PUBLICATION_REPORT = "publication_report"
# The build-result artifact is the attempt report.  This alias keeps the
# task-level terminology explicit without introducing a second artifact kind.
ARTIFACT_KIND_ATTEMPT_REPORT = ARTIFACT_KIND_BUILD_RESULT
VALID_ARTIFACT_KINDS = (
    ARTIFACT_KIND_SOURCE_CONTEXT,
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_REVISION_REPORT,
    ARTIFACT_KIND_BUILD_RESULT,
    ARTIFACT_KIND_PUBLICATION_REPORT,
)

ARTIFACT_VERSION_BY_KIND = {
    ARTIFACT_KIND_SOURCE_CONTEXT: "source_context.v1",
    ARTIFACT_KIND_ADAPTATION_DOSSIER: "adaptation_dossier.v1",
    ARTIFACT_KIND_FAILURE_REPORT: "failure_report.v1",
    ARTIFACT_KIND_REVISION_REPORT: "revision_report.v1",
    ARTIFACT_KIND_BUILD_RESULT: "build_result.v1",
    ARTIFACT_KIND_PUBLICATION_REPORT: "publication_report.v1",
}

ARTIFACT_STAGE_DRAFT = "draft"
ARTIFACT_STAGE_FAILED = "failed"
ARTIFACT_STAGE_REVISED = "revised"
ARTIFACT_STAGE_BUILD = "build"
ARTIFACT_STAGE_PUBLICATION = "publication"
VALID_ARTIFACT_STAGES = (
    ARTIFACT_STAGE_DRAFT,
    ARTIFACT_STAGE_FAILED,
    ARTIFACT_STAGE_REVISED,
    ARTIFACT_STAGE_BUILD,
    ARTIFACT_STAGE_PUBLICATION,
)

ARTIFACT_STATUS_DRAFT = "draft"
ARTIFACT_STATUS_FAILED = "failed"
ARTIFACT_STATUS_REVISED = "revised"
ARTIFACT_STATUS_PENDING = "pending"
ARTIFACT_STATUS_PASSED = "passed"
ARTIFACT_STATUS_BLOCKED = "blocked"
ARTIFACT_STATUS_PUBLISHED = "published"
ARTIFACT_STATUS_DEFERRED = "deferred"
VALID_ARTIFACT_STATUSES = (
    ARTIFACT_STATUS_DRAFT,
    ARTIFACT_STATUS_FAILED,
    ARTIFACT_STATUS_REVISED,
    ARTIFACT_STATUS_PENDING,
    ARTIFACT_STATUS_PASSED,
    ARTIFACT_STATUS_BLOCKED,
    ARTIFACT_STATUS_PUBLISHED,
    ARTIFACT_STATUS_DEFERRED,
)

FAILURE_CLASS_PROVIDER = "provider"
FAILURE_CLASS_FILE = "file"
FAILURE_CLASS_DEPENDENCY = "dependency"
FAILURE_CLASS_QUOTA = "quota"
FAILURE_CLASS_TIMEOUT = "timeout"
FAILURE_CLASS_RIGHTS = "rights"
FAILURE_CLASS_MECHANICAL = "mechanical"
FAILURE_CLASS_SEMANTIC = "semantic"
FAILURE_CLASS_PUBLICATION = "publication"
FAILURE_CLASS_UNKNOWN = "unknown"
VALID_FAILURE_CLASSES = (
    FAILURE_CLASS_PROVIDER,
    FAILURE_CLASS_FILE,
    FAILURE_CLASS_DEPENDENCY,
    FAILURE_CLASS_QUOTA,
    FAILURE_CLASS_TIMEOUT,
    FAILURE_CLASS_RIGHTS,
    FAILURE_CLASS_MECHANICAL,
    FAILURE_CLASS_SEMANTIC,
    FAILURE_CLASS_PUBLICATION,
    FAILURE_CLASS_UNKNOWN,
)

REVISION_DECISION_REVISE = "revise"
REVISION_DECISION_REFUSE = "refuse"
REVISION_DECISION_FAILED = "failed"
VALID_REVISION_DECISIONS = (
    REVISION_DECISION_REVISE,
    REVISION_DECISION_REFUSE,
    REVISION_DECISION_FAILED,
)

BUILD_STATUS_PENDING = "pending"
BUILD_STATUS_PASSED = "passed"
BUILD_STATUS_FAILED = "failed"
BUILD_STATUS_BLOCKED = "blocked"
VALID_BUILD_STATUSES = (
    BUILD_STATUS_PENDING,
    BUILD_STATUS_PASSED,
    BUILD_STATUS_FAILED,
    BUILD_STATUS_BLOCKED,
)

PUBLICATION_STATUS_PENDING = "pending"
PUBLICATION_STATUS_PUBLISHED = "published"
PUBLICATION_STATUS_FAILED = "failed"
PUBLICATION_STATUS_BLOCKED = "blocked"
PUBLICATION_STATUS_DEFERRED = "deferred"
VALID_PUBLICATION_STATUSES = (
    PUBLICATION_STATUS_PENDING,
    PUBLICATION_STATUS_PUBLISHED,
    PUBLICATION_STATUS_FAILED,
    PUBLICATION_STATUS_BLOCKED,
    PUBLICATION_STATUS_DEFERRED,
)

SOURCE_CONTEXT_STATUS_AVAILABLE = "available"
SOURCE_CONTEXT_STATUS_REFERENCED = "referenced"
SOURCE_CONTEXT_STATUS_UNAVAILABLE = "unavailable"
VALID_SOURCE_CONTEXT_STATUSES = (
    SOURCE_CONTEXT_STATUS_AVAILABLE,
    SOURCE_CONTEXT_STATUS_REFERENCED,
    SOURCE_CONTEXT_STATUS_UNAVAILABLE,
)

REPORT_FRESHNESS_CURRENT = "current"
REPORT_FRESHNESS_AUTHORITATIVE = "authoritative"
REPORT_FRESHNESS_DEGRADED = "degraded"
REPORT_FRESHNESS_STALE = "stale"
VALID_REPORT_FRESHNESS_STATES = (
    REPORT_FRESHNESS_CURRENT,
    REPORT_FRESHNESS_AUTHORITATIVE,
    REPORT_FRESHNESS_DEGRADED,
    REPORT_FRESHNESS_STALE,
)

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_SEVERITY_WARNING = "warning"
VALID_DIAGNOSTIC_SEVERITIES = (
    DIAGNOSTIC_SEVERITY_ERROR,
    DIAGNOSTIC_SEVERITY_WARNING,
)

ARTIFACT_DIAGNOSTIC_CODE_INVALID_JSON = "invalid_json"
ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE = "invalid_type"
ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD = "missing_field"
ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM = "invalid_enum"
ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE = "invalid_value"
ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD = "unexpected_field"
ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH = "invalid_project_relative_path"
ARTIFACT_DIAGNOSTIC_CODE_INVALID_SOURCE_REF = "invalid_source_reference"
ARTIFACT_DIAGNOSTIC_CODE_INVALID_PAYLOAD = "invalid_payload"
ARTIFACT_DIAGNOSTIC_CODE_INVALID_STAGE = "invalid_stage_for_artifact"
ARTIFACT_DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE = "schema_unavailable"
ARTIFACT_DIAGNOSTIC_CODE_ARTIFACT_EXISTS = "artifact_exists"
ARTIFACT_DIAGNOSTIC_CODE_WRITE_FAILED = "write_failed"
ARTIFACT_DIAGNOSTIC_CODE_UNBOUNDED_SOURCE = "unbounded_source_content"

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "toolkit_adaptation_artifact_schema.json"
)

MAX_ARTIFACT_BYTES = 2_000_000
MAX_ARTIFACT_TEXT_CHARS = 4000
MAX_FAILURE_MESSAGE_CHARS = 800
MAX_DIAGNOSTICS = 64
MAX_REVISION_HISTORY = 8
MAX_ARTIFACT_REFERENCES = 128
MAX_SOURCE_SECTIONS = 32
MAX_SOURCE_SUMMARY_CHARS = 4000
MAX_SOURCE_EXCERPT_CHARS = 800
MAX_SOURCE_SIZE_BYTES = 50_000_000

_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")

_FORBIDDEN_SOURCE_KEYS = {
    "raw_source",
    "raw_source_text",
    "source_text",
    "source_content",
    "full_source",
    "full_text",
    "raw_markdown",
    "raw_pdf",
}
_RUNTIME_STATE_FILENAMES = {
    "world_registry.json",
    "campaign.json",
    "party_tracker.json",
}

_ALLOWED_METADATA_KEYS = {
    "job_id",
    "operator_label",
    "source_profile",
    "source_format",
    "world_seed_status",
    "world_seed_version",
    "world_seed_hash",
    "world_context_status",
    "world_context_version",
    "world_context_hash",
    "context_hash",
    "world_context_selected_module",
    "parent_attempt_id",
    "created_by",
    "source_context_status",
    "publication_policy",
}


def _utc_now_iso() -> str:
    """Return a second-precision UTC timestamp for artifact metadata."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ascii_text(value: Any, limit: int = 240) -> str:
    """Return a bounded ASCII diagnostic string."""
    text = str(value).encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _diagnostic(code: str, message: str, path: str = "") -> Dict[str, str]:
    return {
        "code": code,
        "message": _ascii_text(message),
        "path": _ascii_text(path, 200),
        "severity": DIAGNOSTIC_SEVERITY_ERROR,
    }


def _result(
    normalized: Optional[Dict[str, Any]],
    diagnostics: List[Dict[str, str]],
) -> Dict[str, Any]:
    valid = normalized is not None and not diagnostics
    return {
        "valid": valid,
        "status": "valid" if valid else "invalid",
        "artifact": deepcopy(normalized) if valid else None,
        "diagnostics": diagnostics,
    }


def load_adaptation_artifact_schema() -> Dict[str, Any]:
    """Load the machine-checkable artifact envelope schema."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError("adaptation artifact schema must be a JSON object")
    return deepcopy(schema)


def get_adaptation_artifact_schema_path() -> Path:
    """Return the repository-local artifact schema path."""
    return SCHEMA_PATH


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _is_safe_attempt_id(value: Any) -> bool:
    if not isinstance(value, str) or ".." in value:
        return False
    return bool(_ATTEMPT_ID_RE.fullmatch(value))


def _is_project_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 512:
        return False
    if "\x00" in value or "\\" in value:
        return False
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    parts = PurePosixPath(value).parts
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _is_timestamp(value: Any) -> bool:
    return isinstance(value, str) and bool(_TIMESTAMP_RE.fullmatch(value))


def _is_safe_module_slug(value: Any) -> bool:
    return isinstance(value, str) and bool(_MODULE_SLUG_RE.fullmatch(value))


def _world_context_provenance(
    world_context: Any = None,
    world_context_provenance: Any = None,
) -> Optional[Dict[str, Any]]:
    """Normalize optional world context to reference-only provenance."""
    if world_context is None and world_context_provenance is None:
        return None
    return build_world_context_provenance(
        world_context if world_context is not None else world_context_provenance
    )


def _attach_world_context_provenance(
    provenance: Dict[str, Any],
    metadata: Dict[str, Any],
    world_context: Optional[Mapping[str, Any]],
) -> None:
    """Attach scalar seed provenance and immutable authority markers."""
    if not isinstance(world_context, Mapping):
        return

    provenance["world_context_provenance"] = deepcopy(dict(world_context))
    provenance["world_seed_status"] = world_context.get("world_seed_status")
    provenance["world_context_status"] = world_context.get("context_status")
    provenance["world_context_read_only"] = world_context.get("read_only") is True
    if world_context.get("context_version") not in (None, ""):
        provenance["world_context_version"] = world_context.get("context_version")
    if world_context.get("world_seed_version") not in (None, ""):
        provenance["world_seed_version"] = world_context.get("world_seed_version")
    if world_context.get("world_seed_hash") not in (None, ""):
        provenance["world_seed_hash"] = world_context.get("world_seed_hash")
    if world_context.get("context_hash") not in (None, ""):
        provenance["context_hash"] = world_context.get("context_hash")
        provenance["world_context_hash"] = world_context.get("context_hash")
    if world_context.get("selected_module") not in (None, ""):
        provenance["world_context_selected_module"] = world_context.get("selected_module")

    for key in (
        "world_seed_status",
        "world_context_status",
        "world_context_version",
        "world_seed_version",
        "world_seed_hash",
        "context_hash",
        "world_context_hash",
        "world_context_selected_module",
    ):
        value = provenance.get(key)
        if value not in (None, ""):
            metadata[key] = value


def build_attempt_id(
    source_hash: str,
    attempt_number: int = 1,
    job_id: str = "",
) -> str:
    """Build a stable, path-safe attempt id from immutable attempt inputs."""
    if not _is_sha256(source_hash):
        raise ValueError("source_hash must be a lowercase SHA-256 digest")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise ValueError("attempt_number must be an integer")
    if attempt_number < 1 or attempt_number > 1_000_000:
        raise ValueError("attempt_number is outside the supported range")
    normalized_job_id = str(job_id or "").strip()
    identity_seed = (
        normalized_job_id + "|" + source_hash + "|" + str(attempt_number)
    ).encode("utf-8")
    digest = hashlib.sha256(identity_seed).hexdigest()[:24]
    return f"adapt-{attempt_number:03d}-{digest}"


make_attempt_id = build_attempt_id


def get_adaptation_attempt_workspace(workspace: Path, attempt_id: str) -> Path:
    """Return the deterministic attempt directory without creating it."""
    if not _is_safe_attempt_id(attempt_id):
        raise ValueError("attempt_id is not a safe path segment")
    return Path(workspace) / ADAPTATION_ARTIFACT_ROOT / attempt_id


get_attempt_workspace = get_adaptation_attempt_workspace


def get_adaptation_artifact_path(
    workspace: Path,
    attempt_id: str,
    artifact_kind: str,
    revision_number: int = 0,
) -> Path:
    """Return a deterministic path for one attempt artifact.

    Revision zero uses the attempt root. Later revisions use a distinct
    ``revisions/revision_NNN`` directory, so a revised build never replaces
    the initial attempt artifact.
    """
    if artifact_kind not in VALID_ARTIFACT_KINDS:
        raise ValueError("unknown adaptation artifact kind")
    if isinstance(revision_number, bool) or not isinstance(revision_number, int):
        raise ValueError("revision_number must be an integer")
    if revision_number < 0 or revision_number > 100:
        raise ValueError("revision_number is outside the supported range")
    root = get_adaptation_attempt_workspace(workspace, attempt_id)
    if revision_number:
        root = root / "revisions" / f"revision_{revision_number:03d}"
    return root / f"{artifact_kind}.json"


def get_attempt_artifact_paths(
    workspace: Path,
    attempt_id: str,
    revision_number: int = 0,
) -> Dict[str, Path]:
    """Return all canonical artifact paths for one attempt revision."""
    return {
        kind: get_adaptation_artifact_path(
            workspace, attempt_id, kind, revision_number
        )
        for kind in VALID_ARTIFACT_KINDS
    }


def _schema_diagnostics(artifact: Dict[str, Any]) -> List[Dict[str, str]]:
    if Draft7Validator is None:
        return [
            _diagnostic(
                ARTIFACT_DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE,
                "jsonschema dependency is unavailable",
            )
        ]
    try:
        validator = Draft7Validator(load_adaptation_artifact_schema())
        errors = sorted(
            validator.iter_errors(artifact),
            key=lambda error: (
                tuple(str(part) for part in getattr(error, "absolute_path", [])),
                str(getattr(error, "validator", "")),
                str(getattr(error, "message", "")),
            ),
        )
    except Exception as exc:
        return [
            _diagnostic(
                ARTIFACT_DIAGNOSTIC_CODE_SCHEMA_UNAVAILABLE,
                "artifact schema could not be loaded: " + _ascii_text(exc),
            )
        ]

    diagnostics: List[Dict[str, str]] = []
    for error in errors:
        validator_name = str(getattr(error, "validator", ""))
        if validator_name == "required":
            code = ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD
        elif validator_name in {"enum", "pattern", "minimum", "maximum"}:
            code = ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE
        elif validator_name == "additionalProperties":
            code = ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD
        else:
            code = ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE
        path = ".".join(str(part) for part in getattr(error, "absolute_path", []))
        diagnostics.append(_diagnostic(code, str(error.message), path))
    return diagnostics


def _bounded_value_diagnostics(
    value: Any,
    path: str = "",
    depth: int = 0,
) -> List[Dict[str, str]]:
    """Reject oversized JSON values before an artifact can be persisted."""
    if depth > 12:
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "payload nesting is too deep", path)]
    if isinstance(value, str):
        if len(value) > MAX_ARTIFACT_TEXT_CHARS:
            return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "text value exceeds artifact bound", path)]
        return []
    if isinstance(value, list):
        if len(value) > MAX_ARTIFACT_REFERENCES:
            return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "list exceeds artifact bound", path)]
        diagnostics: List[Dict[str, str]] = []
        for index, item in enumerate(value):
            diagnostics.extend(_bounded_value_diagnostics(item, f"{path}[{index}]", depth + 1))
            if len(diagnostics) >= MAX_DIAGNOSTICS:
                break
        return diagnostics[:MAX_DIAGNOSTICS]
    if isinstance(value, dict):
        if len(value) > 128:
            return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "object exceeds artifact bound", path)]
        diagnostics = []
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 160:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "object key is invalid", path))
                continue
            diagnostics.extend(_bounded_value_diagnostics(item, f"{path}.{key}".strip("."), depth + 1))
            if len(diagnostics) >= MAX_DIAGNOSTICS:
                break
        return diagnostics[:MAX_DIAGNOSTICS]
    return []


def _validate_source_reference(
    reference: Any,
    path: str,
    allow_kind: bool = False,
) -> List[Dict[str, str]]:
    if not isinstance(reference, Mapping):
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_SOURCE_REF, "source reference must be an object", path)]
    diagnostics: List[Dict[str, str]] = []
    if not _is_project_relative_path(reference.get("path")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH, "reference path must be project-relative", f"{path}.path"))
    if not _is_sha256(reference.get("sha256")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_SOURCE_REF, "reference sha256 must be lowercase SHA-256", f"{path}.sha256"))
    size = reference.get("size_bytes")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_SOURCE_SIZE_BYTES):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "reference size_bytes is outside the bound", f"{path}.size_bytes"))
    allowed = {"path", "sha256", "size_bytes"}
    if allow_kind:
        allowed.update({"kind", "role", "reference_only"})
    unexpected = sorted(set(reference) - allowed)
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected reference field: " + unexpected[0], path))
    if allow_kind and "reference_only" in reference and reference.get("reference_only") is not True:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "module references must be reference_only=true", f"{path}.reference_only"))
    return diagnostics


def _validate_report_freshness(value: Any) -> List[Dict[str, str]]:
    """Validate optional freshness metadata without declaring it current."""
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "report_freshness must be an object", "report_freshness")]
    diagnostics: List[Dict[str, str]] = []
    unexpected = sorted(set(value) - {"state", "authoritative", "written_at", "reason"})
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected report freshness field: " + unexpected[0], "report_freshness"))
    if value.get("state") not in VALID_REPORT_FRESHNESS_STATES:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "report freshness state is invalid", "report_freshness.state"))
    if not isinstance(value.get("authoritative"), bool):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "report freshness authoritative must be boolean", "report_freshness.authoritative"))
    if not _is_timestamp(value.get("written_at")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "report freshness written_at is invalid", "report_freshness.written_at"))
    if "reason" in value and (not isinstance(value.get("reason"), str) or len(value.get("reason", "")) > 240):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "report freshness reason is invalid", "report_freshness.reason"))
    return diagnostics


def _validate_provenance(artifact: Dict[str, Any]) -> List[Dict[str, str]]:
    provenance = artifact.get("provenance")
    if not isinstance(provenance, Mapping):
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "provenance must be an object", "provenance")]
    diagnostics: List[Dict[str, str]] = []
    if not _is_sha256(provenance.get("source_hash")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_SOURCE_REF, "provenance source_hash is invalid", "provenance.source_hash"))
    if not _is_project_relative_path(provenance.get("source_path")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH, "provenance source_path must be project-relative", "provenance.source_path"))
    if provenance.get("adaptation_mode") != ADAPTATION_MODE_LLM:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "provenance adaptation_mode is not llm_adaptation", "provenance.adaptation_mode"))
    size = provenance.get("source_size_bytes")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_SOURCE_SIZE_BYTES):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "provenance source_size_bytes is outside the bound", "provenance.source_size_bytes"))
    model_metadata = provenance.get("model_metadata")
    if model_metadata is not None:
        if not isinstance(model_metadata, Mapping):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "model_metadata must be an object", "provenance.model_metadata"))
        elif any(not isinstance(value, (str, int, float, bool)) for value in model_metadata.values()):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "model_metadata values must be bounded scalars", "provenance.model_metadata"))
    if provenance.get("world_seed_hash") is not None and not _is_sha256(provenance.get("world_seed_hash")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "world_seed_hash must be lowercase SHA-256", "provenance.world_seed_hash"))
    if provenance.get("world_seed_status") is not None and provenance.get("world_seed_status") not in {
        "available",
        "unavailable",
        "invalid",
    }:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "world_seed_status is invalid", "provenance.world_seed_status"))
    if provenance.get("world_context_status") is not None and provenance.get("world_context_status") not in {
        "available",
        "fallback",
        "unavailable",
    }:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "world_context_status is invalid", "provenance.world_context_status"))
    for key in ("world_context_hash", "context_hash"):
        if provenance.get(key) is not None and not _is_sha256(provenance.get(key)):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, key + " must be lowercase SHA-256", "provenance." + key))
    if provenance.get("world_context_read_only") is not None and provenance.get("world_context_read_only") is not True:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "world context must be read-only", "provenance.world_context_read_only"))
    world_context_provenance = provenance.get("world_context_provenance")
    if world_context_provenance is not None:
        if not isinstance(world_context_provenance, Mapping):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "world_context_provenance must be an object", "provenance.world_context_provenance"))
        else:
            normalized = build_world_context_provenance(world_context_provenance)
            if normalized != dict(world_context_provenance):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "world_context_provenance is not canonical", "provenance.world_context_provenance"))
            else:
                flat_fields = {
                    "world_seed_status": normalized.get("world_seed_status"),
                    "world_seed_version": normalized.get("world_seed_version"),
                    "world_seed_hash": normalized.get("world_seed_hash"),
                    "world_context_status": normalized.get("context_status"),
                    "world_context_version": normalized.get("context_version"),
                    "world_context_hash": normalized.get("context_hash"),
                    "context_hash": normalized.get("context_hash"),
                    "world_context_selected_module": normalized.get("selected_module"),
                    "world_context_read_only": normalized.get("read_only"),
                }
                for key, expected in flat_fields.items():
                    if key in provenance and provenance.get(key) not in (None, expected):
                        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, key + " contradicts world_context_provenance", "provenance." + key))
    rights_class = provenance.get("rights_class")
    rights_required = provenance.get("rights_review_required")
    rights_status = provenance.get("rights_review_status")
    if rights_class == RIGHTS_CLASS_RESTRICTED and rights_required is not True:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "restricted source requires rights review", "provenance.rights_review_required"))
    if rights_required is False and rights_status in {RIGHTS_REVIEW_PENDING, RIGHTS_REVIEW_REJECTED}:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "rights review status contradicts rights_review_required=false", "provenance.rights_review_status"))
    return diagnostics


def _validate_metadata(artifact: Dict[str, Any]) -> List[Dict[str, str]]:
    metadata = artifact.get("metadata")
    if not isinstance(metadata, Mapping):
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "metadata must be an object", "metadata")]
    diagnostics: List[Dict[str, str]] = []
    unexpected = sorted(set(metadata) - _ALLOWED_METADATA_KEYS)
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected metadata field: " + unexpected[0], "metadata"))
    for key, value in metadata.items():
        if key in {"world_seed_hash", "world_context_hash", "context_hash"}:
            if not _is_sha256(value):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, f"metadata {key} is invalid", f"metadata.{key}"))
        elif key == "parent_attempt_id":
            if not _is_safe_attempt_id(value):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "metadata parent_attempt_id is invalid", f"metadata.{key}"))
        elif not isinstance(value, str) or not value or len(value) > 240:
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "metadata values must be non-empty bounded text", f"metadata.{key}"))
    return diagnostics


def _validate_source_context_payload(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = {
        "context_status",
        "source_ref",
        "source_profile",
        "summary",
        "manifest_ref",
        "section_summaries",
        "bounded_context_refs",
        "profile_reason",
    }
    diagnostics: List[Dict[str, str]] = []
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected source context field: " + unexpected[0], "payload"))
    context_status = payload.get("context_status")
    if context_status not in VALID_SOURCE_CONTEXT_STATUSES:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "source context status is invalid", "payload.context_status"))
    diagnostics.extend(_validate_source_reference(payload.get("source_ref"), "payload.source_ref"))
    summary = payload.get("summary", "")
    if not isinstance(summary, str) or len(summary) > MAX_SOURCE_SUMMARY_CHARS:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "source context summary is too large or invalid", "payload.summary"))
    profile_reason = payload.get("profile_reason")
    if profile_reason is not None and (not isinstance(profile_reason, str) or len(profile_reason) > 1000):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "profile_reason exceeds its bound", "payload.profile_reason"))
    sections = payload.get("section_summaries", [])
    if not isinstance(sections, list) or len(sections) > MAX_SOURCE_SECTIONS:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "section_summaries exceeds its bound", "payload.section_summaries"))
    else:
        for index, section in enumerate(sections):
            section_path = f"payload.section_summaries[{index}]"
            if not isinstance(section, Mapping):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "section summary must be an object", section_path))
                continue
            if not isinstance(section.get("heading"), str) or not section.get("heading"):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD, "section heading is required", section_path))
            if not isinstance(section.get("summary"), str) or len(section.get("summary", "")) > MAX_SOURCE_EXCERPT_CHARS:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "section summary is too large or invalid", section_path))
            if "source_ref" in section:
                diagnostics.extend(_validate_source_reference(section.get("source_ref"), section_path + ".source_ref"))
    if "manifest_ref" in payload:
        diagnostics.extend(_validate_source_reference(payload.get("manifest_ref"), "payload.manifest_ref"))
    refs = payload.get("bounded_context_refs", [])
    if not isinstance(refs, list) or len(refs) > MAX_ARTIFACT_REFERENCES:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "bounded_context_refs exceeds its bound", "payload.bounded_context_refs"))
    else:
        for index, reference in enumerate(refs):
            diagnostics.extend(_validate_source_reference(reference, f"payload.bounded_context_refs[{index}]", allow_kind=True))
    for key in _FORBIDDEN_SOURCE_KEYS:
        if key in payload:
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNBOUNDED_SOURCE, "raw source content is not persisted in source context", f"payload.{key}"))
    return diagnostics


def _validate_failure_payload(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = {
        "failure_class",
        "failed_stage",
        "diagnostics",
        "summary",
        "recoverable",
        "gate",
        "safe_class",
        "reason_code",
        "revision_eligible",
    }
    diagnostics: List[Dict[str, str]] = []
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected failure field: " + unexpected[0], "payload"))
    if payload.get("failure_class") not in VALID_FAILURE_CLASSES:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "failure_class is invalid", "payload.failure_class"))
    if payload.get("failed_stage") not in VALID_ARTIFACT_STAGES:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "failed_stage is invalid", "payload.failed_stage"))
    failure_items = payload.get("diagnostics")
    if not isinstance(failure_items, list) or not failure_items or len(failure_items) > MAX_DIAGNOSTICS:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "failure diagnostics must be a bounded non-empty list", "payload.diagnostics"))
    else:
        for index, item in enumerate(failure_items):
            item_path = f"payload.diagnostics[{index}]"
            if not isinstance(item, Mapping):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "failure diagnostic must be an object", item_path))
                continue
            if not isinstance(item.get("code"), str) or not item.get("code"):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD, "failure diagnostic code is required", item_path))
            message = item.get("message")
            if not isinstance(message, str) or not message or len(message) > MAX_FAILURE_MESSAGE_CHARS:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "failure diagnostic message is invalid or too large", item_path))
            if "severity" in item and item.get("severity") not in VALID_DIAGNOSTIC_SEVERITIES:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "failure diagnostic severity is invalid", item_path))
            if "path" in item and (not isinstance(item.get("path"), str) or len(item.get("path", "")) > 240):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "failure diagnostic path is too large", item_path))
    summary = payload.get("summary")
    if summary is not None and (not isinstance(summary, str) or len(summary) > MAX_FAILURE_MESSAGE_CHARS):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "failure summary is too large", "payload.summary"))
    if "recoverable" in payload and not isinstance(payload.get("recoverable"), bool):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "recoverable must be boolean", "payload.recoverable"))
    if "safe_class" in payload:
        safe_class = payload.get("safe_class")
        if not isinstance(safe_class, str) or not safe_class or len(safe_class) > 64 or not safe_class.isascii():
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "safe_class is invalid or too large", "payload.safe_class"))
    if "reason_code" in payload:
        reason_code = payload.get("reason_code")
        if not isinstance(reason_code, str) or not reason_code or len(reason_code) > 96 or not reason_code.isascii():
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "reason_code is invalid or too large", "payload.reason_code"))
    if "revision_eligible" in payload and not isinstance(payload.get("revision_eligible"), bool):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "revision_eligible must be boolean", "payload.revision_eligible"))
    return diagnostics


def _validate_artifact_reference_list(value: Any, path: str) -> List[Dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_ARTIFACT_REFERENCES:
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "artifact references exceed their bound", path)]
    diagnostics: List[Dict[str, str]] = []
    for index, reference in enumerate(value):
        diagnostics.extend(_validate_source_reference(reference, f"{path}[{index}]", allow_kind=True))
    return diagnostics


def _validate_revision_payload(artifact: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = {
        "revision_number",
        "decision",
        "reason",
        "failure_artifact_refs",
        "history",
        "revised_dossier_ref",
        "rebuild_directive",
        "fresh_staging_required",
    }
    diagnostics: List[Dict[str, str]] = []
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected revision field: " + unexpected[0], "payload"))
    revision_number = payload.get("revision_number")
    if revision_number != artifact.get("revision_number") or isinstance(revision_number, bool) or not isinstance(revision_number, int) or revision_number < 1:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "revision number must match the artifact revision", "payload.revision_number"))
    if payload.get("decision") not in VALID_REVISION_DECISIONS:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "revision decision is invalid", "payload.decision"))
    if not isinstance(payload.get("reason"), str) or not payload.get("reason") or len(payload.get("reason", "")) > MAX_FAILURE_MESSAGE_CHARS:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "revision reason is invalid or too large", "payload.reason"))
    diagnostics.extend(_validate_artifact_reference_list(payload.get("failure_artifact_refs", []), "payload.failure_artifact_refs"))
    history = payload.get("history")
    if not isinstance(history, list) or not history or len(history) > MAX_REVISION_HISTORY:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "revision history must be a bounded non-empty list", "payload.history"))
    else:
        for index, entry in enumerate(history):
            entry_path = f"payload.history[{index}]"
            if not isinstance(entry, Mapping):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "revision history entry must be an object", entry_path))
                continue
            if isinstance(entry.get("revision_number"), bool) or not isinstance(entry.get("revision_number"), int) or entry.get("revision_number") < 0:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "history revision number is invalid", entry_path))
            if not isinstance(entry.get("status"), str) or len(entry.get("status", "")) > 32:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "history status is invalid", entry_path))
            if not isinstance(entry.get("reason"), str) or len(entry.get("reason", "")) > MAX_FAILURE_MESSAGE_CHARS:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "history reason is invalid", entry_path))
    if "revised_dossier_ref" in payload:
        diagnostics.extend(_validate_source_reference(payload.get("revised_dossier_ref"), "payload.revised_dossier_ref", allow_kind=True))
    directive = payload.get("rebuild_directive")
    if directive is not None:
        if not isinstance(directive, Mapping):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "rebuild_directive must be an object", "payload.rebuild_directive"))
        else:
            allowed_directive = {"action", "target", "target_path"}
            unexpected_directive = sorted(set(directive) - allowed_directive)
            if unexpected_directive:
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected rebuild directive field", "payload.rebuild_directive"))
            if directive.get("action") != "fresh_build" or directive.get("target") != "staging":
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "revision directive must request a fresh staging build", "payload.rebuild_directive"))
            if "target_path" in directive and not _is_project_relative_path(directive.get("target_path")):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH, "revision target_path must be project-relative", "payload.rebuild_directive.target_path"))
    if payload.get("decision") == REVISION_DECISION_REVISE and payload.get("fresh_staging_required") is not True:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "revision must require fresh staging", "payload.fresh_staging_required"))
    return diagnostics


def _validate_build_payload(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = {
        "build_status",
        "module_slug",
        "staging",
        "gate_summary",
        "module_artifacts",
        "output_hash",
        "build_started_at",
        "build_completed_at",
        "failure_artifact_ref",
        "source_ref",
    }
    diagnostics: List[Dict[str, str]] = []
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected build field: " + unexpected[0], "payload"))
    if payload.get("build_status") not in VALID_BUILD_STATUSES:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "build_status is invalid", "payload.build_status"))
    staging = payload.get("staging")
    if not isinstance(staging, Mapping):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD, "staging evidence is required", "payload.staging"))
    else:
        if not _is_project_relative_path(staging.get("path")):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH, "staging path must be project-relative", "payload.staging.path"))
        if staging.get("isolated") is not True:
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "staging must be explicitly isolated", "payload.staging.isolated"))
        if staging.get("target_kind") not in {"staging", "backup_safe"}:
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "staging target_kind is invalid", "payload.staging.target_kind"))
    if payload.get("module_slug") is not None and not _is_safe_module_slug(payload.get("module_slug")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "module_slug is invalid", "payload.module_slug"))
    if payload.get("output_hash") is not None and not _is_sha256(payload.get("output_hash")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "output_hash is invalid", "payload.output_hash"))
    for field in ("build_started_at", "build_completed_at"):
        if payload.get(field) is not None and not _is_timestamp(payload.get(field)):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, field + " is invalid", f"payload.{field}"))
    gate_summary = payload.get("gate_summary")
    if not isinstance(gate_summary, Mapping) or len(gate_summary) > 16:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "gate_summary must be bounded", "payload.gate_summary"))
    else:
        for gate, value in gate_summary.items():
            if not isinstance(gate, str) or len(gate) > 80 or not isinstance(value, (str, bool, int, float, dict)):
                diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "gate_summary values must be bounded", "payload.gate_summary"))
    diagnostics.extend(_validate_artifact_reference_list(payload.get("module_artifacts", []), "payload.module_artifacts"))
    if "failure_artifact_ref" in payload:
        diagnostics.extend(_validate_source_reference(payload.get("failure_artifact_ref"), "payload.failure_artifact_ref", allow_kind=True))
    if "source_ref" in payload:
        diagnostics.extend(_validate_source_reference(payload.get("source_ref"), "payload.source_ref"))
    if any(
        isinstance(reference, Mapping)
        and Path(str(reference.get("path", ""))).name in _RUNTIME_STATE_FILENAMES
        for reference in payload.get("module_artifacts", [])
        if isinstance(payload.get("module_artifacts", []), list)
    ):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "runtime state cannot be a module artifact reference", "payload.module_artifacts"))
    return diagnostics


def _validate_gate_evidence(value: Any, path: str) -> List[Dict[str, str]]:
    if not isinstance(value, Mapping):
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "gate evidence must be an object", path)]
    diagnostics: List[Dict[str, str]] = []
    status = value.get("status")
    if status not in {"pass", "fail", "blocked", "not_run", "deferred", "unknown", "not_applicable"}:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "gate evidence status is invalid", path + ".status"))
    if "report_path" in value and not _is_project_relative_path(value.get("report_path")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH, "gate report_path must be project-relative", path + ".report_path"))
    if "summary" in value and (not isinstance(value.get("summary"), str) or len(value.get("summary", "")) > MAX_FAILURE_MESSAGE_CHARS):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "gate summary is too large", path + ".summary"))
    return diagnostics


def _validate_publication_payload(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    allowed = {
        "publication_status",
        "readiness_evidence",
        "registry_evidence",
        "markdown_evidence",
        "source_fidelity_status",
        "module_artifact_refs",
        "campaign_evidence",
        "published_at",
        "failure_artifact_ref",
        "source_ref",
    }
    diagnostics: List[Dict[str, str]] = []
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_UNEXPECTED_FIELD, "unexpected publication field: " + unexpected[0], "payload"))
    if payload.get("publication_status") not in VALID_PUBLICATION_STATUSES:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "publication_status is invalid", "payload.publication_status"))
    readiness = payload.get("readiness_evidence")
    if not isinstance(readiness, Mapping) or not readiness:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD, "readiness_evidence is required", "payload.readiness_evidence"))
    else:
        if len(readiness) > 16:
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "readiness_evidence is too large", "payload.readiness_evidence"))
        for gate, evidence in readiness.items():
            diagnostics.extend(_validate_gate_evidence(evidence, f"payload.readiness_evidence.{gate}"))
    registry = payload.get("registry_evidence")
    if not isinstance(registry, Mapping):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD, "registry_evidence is required", "payload.registry_evidence"))
    else:
        if registry.get("status") not in {"pass", "fail", "blocked", "not_run", "deferred"}:
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "registry evidence status is invalid", "payload.registry_evidence.status"))
        if "verified" in registry and not isinstance(registry.get("verified"), bool):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "registry evidence verified must be boolean", "payload.registry_evidence.verified"))
        if "path" in registry and not _is_project_relative_path(registry.get("path")):
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH, "registry evidence path must be project-relative", "payload.registry_evidence.path"))
    for field in ("markdown_evidence", "campaign_evidence"):
        if field in payload:
            diagnostics.extend(_validate_gate_evidence(payload.get(field), f"payload.{field}"))
    if payload.get("source_fidelity_status") is not None and payload.get("source_fidelity_status") not in {"not_applicable", "informational", "pass", "blocked", "unknown"}:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "source_fidelity_status is invalid", "payload.source_fidelity_status"))
    if payload.get("published_at") is not None and not _is_timestamp(payload.get("published_at")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "published_at is invalid", "payload.published_at"))
    if payload.get("publication_status") == PUBLICATION_STATUS_PUBLISHED and payload.get("published_at") is None:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_MISSING_FIELD, "published_at is required for a published report", "payload.published_at"))
    diagnostics.extend(_validate_artifact_reference_list(payload.get("module_artifact_refs", []), "payload.module_artifact_refs"))
    if "failure_artifact_ref" in payload:
        diagnostics.extend(_validate_source_reference(payload.get("failure_artifact_ref"), "payload.failure_artifact_ref", allow_kind=True))
    if "source_ref" in payload:
        diagnostics.extend(_validate_source_reference(payload.get("source_ref"), "payload.source_ref"))
    return diagnostics


def _payload_diagnostics(artifact: Dict[str, Any]) -> List[Dict[str, str]]:
    payload = artifact.get("payload")
    if not isinstance(payload, dict):
        return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "payload must be an object", "payload")]
    kind = artifact.get("artifact_kind")
    if kind == ARTIFACT_KIND_SOURCE_CONTEXT:
        return _validate_source_context_payload(payload)
    if kind == ARTIFACT_KIND_ADAPTATION_DOSSIER:
        dossier_result = validate_adaptation_dossier(payload)
        if dossier_result.get("valid"):
            provenance = artifact.get("provenance", {})
            if payload.get("source_hash") != provenance.get("source_hash"):
                return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_SOURCE_REF, "dossier source_hash does not match provenance", "payload.source_hash")]
            return []
        return [
            _diagnostic(
                ARTIFACT_DIAGNOSTIC_CODE_INVALID_PAYLOAD,
                "adaptation dossier is invalid: " + str(item.get("code", "invalid")),
                "payload." + str(item.get("path", "")),
            )
            for item in dossier_result.get("diagnostics", [])[:MAX_DIAGNOSTICS]
        ]
    if kind == ARTIFACT_KIND_FAILURE_REPORT:
        return _validate_failure_payload(payload)
    if kind == ARTIFACT_KIND_REVISION_REPORT:
        return _validate_revision_payload(artifact, payload)
    if kind == ARTIFACT_KIND_BUILD_RESULT:
        return _validate_build_payload(payload)
    if kind == ARTIFACT_KIND_PUBLICATION_REPORT:
        return _validate_publication_payload(payload)
    return [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_ENUM, "artifact_kind is unsupported", "artifact_kind")]


def validate_adaptation_artifact(artifact: Any) -> Dict[str, Any]:
    """Validate one attempt artifact without provider or file side effects."""
    if not isinstance(artifact, Mapping):
        return _result(None, [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "artifact must be a JSON object")])
    normalized = deepcopy(dict(artifact))
    diagnostics = _schema_diagnostics(normalized)
    diagnostics.extend(_validate_provenance(normalized))
    diagnostics.extend(_validate_metadata(normalized))
    diagnostics.extend(_validate_report_freshness(normalized.get("report_freshness")))
    if not _is_safe_attempt_id(normalized.get("attempt_id")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "attempt_id is not path-safe", "attempt_id"))
    if normalized.get("artifact_version") != ARTIFACT_VERSION_BY_KIND.get(normalized.get("artifact_kind")):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "artifact_version does not match artifact_kind", "artifact_version"))
    expected_stages = {
        ARTIFACT_KIND_SOURCE_CONTEXT: {ARTIFACT_STAGE_DRAFT},
        ARTIFACT_KIND_ADAPTATION_DOSSIER: {ARTIFACT_STAGE_DRAFT, ARTIFACT_STAGE_REVISED},
        ARTIFACT_KIND_FAILURE_REPORT: {ARTIFACT_STAGE_FAILED},
        ARTIFACT_KIND_REVISION_REPORT: {ARTIFACT_STAGE_REVISED},
        ARTIFACT_KIND_BUILD_RESULT: {ARTIFACT_STAGE_BUILD},
        ARTIFACT_KIND_PUBLICATION_REPORT: {ARTIFACT_STAGE_PUBLICATION},
    }
    if normalized.get("stage") not in expected_stages.get(normalized.get("artifact_kind"), set()):
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_STAGE, "stage is not valid for artifact kind", "stage"))
    try:
        serialized = json.dumps(normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_ARTIFACT_BYTES:
            diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_VALUE, "artifact exceeds the serialized size bound"))
    except (TypeError, ValueError) as exc:
        diagnostics.append(_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_TYPE, "artifact is not JSON serializable: " + _ascii_text(exc)))
    diagnostics.extend(_bounded_value_diagnostics(normalized.get("payload"), "payload"))
    diagnostics.extend(_payload_diagnostics(normalized))
    return _result(normalized, diagnostics[:MAX_DIAGNOSTICS])


def _parse_json_value(raw: Any) -> Tuple[Optional[Any], List[Dict[str, str]]]:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_JSON, "artifact response is not valid UTF-8")]
    if isinstance(raw, Mapping):
        return deepcopy(dict(raw)), []
    if not isinstance(raw, str) or not raw.strip():
        return None, [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_JSON, "artifact response must be non-empty JSON")]
    try:
        value = json.loads(
            raw,
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError("non-standard JSON constant: " + constant)),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, [_diagnostic(ARTIFACT_DIAGNOSTIC_CODE_INVALID_JSON, "json.loads failed: " + _ascii_text(exc))]
    return value, []


def parse_adaptation_artifact(raw: Any) -> Dict[str, Any]:
    """Parse and validate a provider-free artifact JSON value."""
    parsed, diagnostics = _parse_json_value(raw)
    if diagnostics:
        return _result(None, diagnostics)
    return validate_adaptation_artifact(parsed)


parse_attempt_artifact = parse_adaptation_artifact
validate_attempt_artifact = validate_adaptation_artifact


def _default_stage_status(kind: str, revision_number: int) -> Tuple[str, str]:
    if kind == ARTIFACT_KIND_SOURCE_CONTEXT:
        return ARTIFACT_STAGE_DRAFT, ARTIFACT_STATUS_DRAFT
    if kind == ARTIFACT_KIND_ADAPTATION_DOSSIER:
        return (
            (ARTIFACT_STAGE_REVISED, ARTIFACT_STATUS_REVISED)
            if revision_number
            else (ARTIFACT_STAGE_DRAFT, ARTIFACT_STATUS_DRAFT)
        )
    if kind == ARTIFACT_KIND_FAILURE_REPORT:
        return ARTIFACT_STAGE_FAILED, ARTIFACT_STATUS_FAILED
    if kind == ARTIFACT_KIND_REVISION_REPORT:
        return ARTIFACT_STAGE_REVISED, ARTIFACT_STATUS_REVISED
    if kind == ARTIFACT_KIND_BUILD_RESULT:
        return ARTIFACT_STAGE_BUILD, ARTIFACT_STATUS_PENDING
    if kind == ARTIFACT_KIND_PUBLICATION_REPORT:
        return ARTIFACT_STAGE_PUBLICATION, ARTIFACT_STATUS_PENDING
    raise ValueError("unknown adaptation artifact kind")


def build_adaptation_artifact(
    artifact_kind: str,
    *,
    attempt_id: str,
    source_title: str,
    source_hash: str,
    source_path: str,
    payload: Mapping[str, Any],
    attempt_number: int = 1,
    revision_number: int = 0,
    rights_class: str = "user_authored",
    rights_basis: str = "",
    rights_review_required: bool = False,
    rights_review_status: str = RIGHTS_REVIEW_NOT_REQUIRED,
    source_size_bytes: Optional[int] = None,
    source_profile: Optional[str] = None,
    source_format: Optional[str] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    world_context: Any = None,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    created_at: Optional[str] = None,
    report_freshness: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build and validate one attempt artifact envelope.

    This helper never writes to disk. Call ``persist_adaptation_artifact``
    after the returned envelope has been accepted by the caller.
    """
    if artifact_kind not in VALID_ARTIFACT_KINDS:
        raise ValueError("unknown adaptation artifact kind")
    default_stage, default_status = _default_stage_status(artifact_kind, revision_number)
    artifact_metadata: Dict[str, Any] = deepcopy(dict(metadata or {}))
    normalized_world_context = _world_context_provenance(
        world_context,
        world_context_provenance,
    )
    provenance: Dict[str, Any] = {
        "source_title": source_title,
        "source_hash": source_hash,
        "source_path": source_path,
        "rights_class": rights_class,
        "rights_review_required": rights_review_required,
        "rights_review_status": rights_review_status,
        "adaptation_mode": ADAPTATION_MODE_LLM,
    }
    if rights_basis:
        provenance["rights_basis"] = rights_basis
    if source_size_bytes is not None:
        provenance["source_size_bytes"] = source_size_bytes
    if source_profile is not None:
        provenance["source_profile"] = source_profile
    if source_format is not None:
        provenance["source_format"] = source_format
    if model_metadata is not None:
        provenance["model_metadata"] = deepcopy(dict(model_metadata))
    else:
        provenance["model_metadata"] = {
            "provider": "not_recorded",
            "model": "not_recorded",
        }
    _attach_world_context_provenance(
        provenance,
        artifact_metadata,
        normalized_world_context,
    )
    artifact_created_at = created_at or _utc_now_iso()
    freshness = deepcopy(dict(report_freshness or {}))
    freshness.setdefault("state", REPORT_FRESHNESS_CURRENT)
    freshness.setdefault("authoritative", True)
    freshness.setdefault("written_at", artifact_created_at)
    artifact = {
        "version": ADAPTATION_ARTIFACT_CONTRACT_VERSION,
        "artifact_kind": artifact_kind,
        "artifact_version": ARTIFACT_VERSION_BY_KIND[artifact_kind],
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "revision_number": revision_number,
        "stage": stage or default_stage,
        "status": status or default_status,
        "created_at": artifact_created_at,
        "report_freshness": freshness,
        "provenance": provenance,
        "metadata": artifact_metadata,
        "payload": deepcopy(dict(payload)),
    }
    result = validate_adaptation_artifact(artifact)
    if not result.get("valid"):
        first = (result.get("diagnostics") or [{}])[0]
        raise ValueError(_ascii_text(first.get("message", "invalid adaptation artifact"), 500))
    return artifact


def build_source_context_artifact(
    *,
    attempt_id: str,
    source_title: str,
    source_hash: str,
    source_path: str,
    summary: str = "",
    source_profile: Optional[str] = None,
    source_size_bytes: Optional[int] = None,
    manifest_ref: Optional[Mapping[str, Any]] = None,
    section_summaries: Optional[Sequence[Mapping[str, Any]]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    world_context: Any = None,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a source-context artifact without embedding raw source text."""
    payload: Dict[str, Any] = {
        "context_status": SOURCE_CONTEXT_STATUS_REFERENCED,
        "source_ref": {
            "path": source_path,
            "sha256": source_hash,
        },
        "summary": summary,
        "section_summaries": [dict(item) for item in (section_summaries or [])],
    }
    if source_profile is not None:
        payload["source_profile"] = source_profile
    if source_size_bytes is not None:
        payload["source_ref"]["size_bytes"] = source_size_bytes
    if manifest_ref is not None:
        payload["manifest_ref"] = dict(manifest_ref)
    return build_adaptation_artifact(
        ARTIFACT_KIND_SOURCE_CONTEXT,
        attempt_id=attempt_id,
        source_title=source_title,
        source_hash=source_hash,
        source_path=source_path,
        source_size_bytes=source_size_bytes,
        source_profile=source_profile,
        payload=payload,
        metadata=metadata,
        world_context=world_context,
        world_context_provenance=world_context_provenance,
    )


def build_adaptation_dossier_artifact(
    dossier: Mapping[str, Any],
    *,
    attempt_id: str,
    source_path: str,
    attempt_number: int = 1,
    revision_number: int = 0,
    model_metadata: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    world_context: Any = None,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an artifact only when the existing strict dossier validates."""
    result = validate_adaptation_dossier(dossier)
    if not result.get("valid"):
        raise ValueError("adaptation dossier does not satisfy its schema")
    normalized = result["dossier"]
    return build_adaptation_artifact(
        ARTIFACT_KIND_ADAPTATION_DOSSIER,
        attempt_id=attempt_id,
        source_title=str(normalized["source_title"]),
        source_hash=str(normalized["source_hash"]),
        source_path=source_path,
        attempt_number=attempt_number,
        revision_number=revision_number,
        rights_class=str(normalized["rights_class"]),
        rights_basis=str(normalized["rights_basis"]),
        rights_review_required=bool(normalized["rights_review_required"]),
        rights_review_status=str(normalized["rights_review_status"]),
        source_profile=str(normalized["source_profile"]),
        model_metadata=model_metadata,
        payload=normalized,
        metadata=metadata,
        world_context=world_context,
        world_context_provenance=world_context_provenance,
    )


def build_failure_report_artifact(
    *,
    attempt_id: str,
    source_title: str,
    source_hash: str,
    source_path: str,
    failure_class: str,
    failed_stage: str,
    diagnostics: Sequence[Mapping[str, Any]],
    revision_number: int = 0,
    summary: str = "",
    recoverable: bool = False,
    gate: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
    world_context: Any = None,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "failure_class": failure_class,
        "failed_stage": failed_stage,
        "diagnostics": [dict(item) for item in diagnostics],
        "recoverable": recoverable,
    }
    if summary:
        payload["summary"] = summary
    if gate:
        payload["gate"] = gate
    return build_adaptation_artifact(
        ARTIFACT_KIND_FAILURE_REPORT,
        attempt_id=attempt_id,
        source_title=source_title,
        source_hash=source_hash,
        source_path=source_path,
        revision_number=revision_number,
        payload=payload,
        metadata=metadata,
        world_context=world_context,
        world_context_provenance=world_context_provenance,
        status=ARTIFACT_STATUS_FAILED,
    )


def build_revision_report_artifact(
    *,
    attempt_id: str,
    source_title: str,
    source_hash: str,
    source_path: str,
    revision_number: int,
    decision: str,
    reason: str,
    history: Sequence[Mapping[str, Any]],
    failure_artifact_refs: Optional[Sequence[Mapping[str, Any]]] = None,
    revised_dossier_ref: Optional[Mapping[str, Any]] = None,
    rebuild_directive: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    world_context: Any = None,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "revision_number": revision_number,
        "decision": decision,
        "reason": reason,
        "history": [dict(item) for item in history],
        "failure_artifact_refs": [dict(item) for item in (failure_artifact_refs or [])],
        "fresh_staging_required": decision == REVISION_DECISION_REVISE,
    }
    if revised_dossier_ref is not None:
        payload["revised_dossier_ref"] = dict(revised_dossier_ref)
    if rebuild_directive is not None:
        payload["rebuild_directive"] = dict(rebuild_directive)
    return build_adaptation_artifact(
        ARTIFACT_KIND_REVISION_REPORT,
        attempt_id=attempt_id,
        source_title=source_title,
        source_hash=source_hash,
        source_path=source_path,
        revision_number=revision_number,
        payload=payload,
        metadata=metadata,
        world_context=world_context,
        world_context_provenance=world_context_provenance,
        status=ARTIFACT_STATUS_REVISED if decision == REVISION_DECISION_REVISE else ARTIFACT_STATUS_FAILED,
    )


def build_build_result_artifact(
    *,
    attempt_id: str,
    source_title: str,
    source_hash: str,
    source_path: str,
    staging_path: str,
    build_status: str = BUILD_STATUS_PENDING,
    module_slug: Optional[str] = None,
    gate_summary: Optional[Mapping[str, Any]] = None,
    module_artifacts: Optional[Sequence[Mapping[str, Any]]] = None,
    revision_number: int = 0,
    output_hash: Optional[str] = None,
    build_started_at: Optional[str] = None,
    build_completed_at: Optional[str] = None,
    source_size_bytes: Optional[int] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    world_context: Any = None,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "build_status": build_status,
        "staging": {
            "path": staging_path,
            "isolated": True,
            "target_kind": "staging",
        },
        "gate_summary": dict(gate_summary or {}),
        "module_artifacts": [dict(item) for item in (module_artifacts or [])],
        "source_ref": {
            "path": source_path,
            "sha256": source_hash,
        },
    }
    if source_size_bytes is not None:
        payload["source_ref"]["size_bytes"] = source_size_bytes
    if module_slug is not None:
        payload["module_slug"] = module_slug
    if output_hash is not None:
        payload["output_hash"] = output_hash
    if build_started_at is not None:
        payload["build_started_at"] = build_started_at
    if build_completed_at is not None:
        payload["build_completed_at"] = build_completed_at
    return build_adaptation_artifact(
        ARTIFACT_KIND_BUILD_RESULT,
        attempt_id=attempt_id,
        source_title=source_title,
        source_hash=source_hash,
        source_path=source_path,
        revision_number=revision_number,
        payload=payload,
        model_metadata=model_metadata,
        metadata=metadata,
        world_context=world_context,
        world_context_provenance=world_context_provenance,
        status=build_status,
    )


def build_publication_report_artifact(
    *,
    attempt_id: str,
    source_title: str,
    source_hash: str,
    source_path: str,
    readiness_evidence: Mapping[str, Any],
    registry_evidence: Mapping[str, Any],
    publication_status: str = PUBLICATION_STATUS_PENDING,
    module_artifact_refs: Optional[Sequence[Mapping[str, Any]]] = None,
    markdown_evidence: Optional[Mapping[str, Any]] = None,
    campaign_evidence: Optional[Mapping[str, Any]] = None,
    source_fidelity_status: str = "not_applicable",
    attempt_number: int = 1,
    revision_number: int = 0,
    published_at: Optional[str] = None,
    source_size_bytes: Optional[int] = None,
    rights_class: str = "user_authored",
    rights_basis: str = "",
    rights_review_required: bool = False,
    rights_review_status: str = RIGHTS_REVIEW_NOT_REQUIRED,
    source_profile: Optional[str] = None,
    source_format: Optional[str] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    world_context: Any = None,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "publication_status": publication_status,
        "readiness_evidence": dict(readiness_evidence),
        "registry_evidence": dict(registry_evidence),
        "source_fidelity_status": source_fidelity_status,
        "module_artifact_refs": [dict(item) for item in (module_artifact_refs or [])],
        "source_ref": {
            "path": source_path,
            "sha256": source_hash,
        },
    }
    if source_size_bytes is not None:
        payload["source_ref"]["size_bytes"] = source_size_bytes
    if markdown_evidence is not None:
        payload["markdown_evidence"] = dict(markdown_evidence)
    if campaign_evidence is not None:
        payload["campaign_evidence"] = dict(campaign_evidence)
    if published_at is not None:
        payload["published_at"] = published_at
    return build_adaptation_artifact(
        ARTIFACT_KIND_PUBLICATION_REPORT,
        attempt_id=attempt_id,
        source_title=source_title,
        source_hash=source_hash,
        source_path=source_path,
        attempt_number=attempt_number,
        revision_number=revision_number,
        rights_class=rights_class,
        rights_basis=rights_basis,
        rights_review_required=rights_review_required,
        rights_review_status=rights_review_status,
        source_profile=source_profile,
        source_format=source_format,
        model_metadata=model_metadata,
        payload=payload,
        metadata=metadata,
        world_context=world_context,
        world_context_provenance=world_context_provenance,
        status=publication_status,
    )


def persist_adaptation_artifact(
    workspace: Path,
    artifact: Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> bool:
    """Persist one valid artifact through the repository atomic JSON helper.

    Existing paths are rejected by default. ``overwrite=True`` is explicit
    and uses the helper's backup behavior; normal revision writes use a new
    revision directory instead of replacing an earlier artifact.
    """
    result = validate_adaptation_artifact(artifact)
    if not result.get("valid"):
        return False
    normalized = result["artifact"]
    try:
        target = get_adaptation_artifact_path(
            Path(workspace),
            normalized["attempt_id"],
            normalized["artifact_kind"],
            normalized["revision_number"],
        )
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False

    reservation: Optional[Path] = None
    try:
        if target.exists() and not overwrite:
            return False
        if not overwrite:
            reservation = Path(str(target) + ".reserve")
            fd = os.open(str(reservation), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            if target.exists():
                return False
        return bool(
            safe_write_json(
                str(target),
                normalized,
                create_backup=bool(overwrite),
            )
        )
    except Exception:
        return False
    finally:
        if reservation is not None:
            try:
                reservation.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass


persist_attempt_artifact = persist_adaptation_artifact

# Explicit task-level aliases. Attempt reports remain build-result artifacts
# so existing artifact kinds and paths remain compatible.
build_attempt_report_artifact = build_build_result_artifact
build_adaptation_attempt_report = build_build_result_artifact


def load_adaptation_artifact(
    workspace: Path,
    attempt_id: str,
    artifact_kind: str,
    revision_number: int = 0,
) -> Optional[Dict[str, Any]]:
    """Load one artifact only when its persisted contract remains valid."""
    try:
        path = get_adaptation_artifact_path(workspace, attempt_id, artifact_kind, revision_number)
        raw = safe_read_json(str(path))
    except Exception:
        return None
    result = validate_adaptation_artifact(raw)
    return result.get("artifact") if result.get("valid") else None


load_attempt_artifact = load_adaptation_artifact
load_attempt_report_artifact = load_adaptation_artifact
load_adaptation_attempt_report = load_adaptation_artifact

# Short aliases keep the generic contract convenient for future orchestration
# code while the explicit names remain the preferred public API.
build_artifact = build_adaptation_artifact
persist_artifact = persist_adaptation_artifact
load_artifact = load_adaptation_artifact
get_artifact_path = get_adaptation_artifact_path


def _persist_kind_artifact(workspace: Path, artifact: Mapping[str, Any], overwrite: bool = False) -> bool:
    return persist_adaptation_artifact(workspace, artifact, overwrite=overwrite)


def persist_source_context_artifact(workspace: Path, artifact: Mapping[str, Any], *, overwrite: bool = False) -> bool:
    return _persist_kind_artifact(workspace, artifact, overwrite)


def persist_adaptation_dossier_artifact(workspace: Path, artifact: Mapping[str, Any], *, overwrite: bool = False) -> bool:
    return _persist_kind_artifact(workspace, artifact, overwrite)


def persist_failure_report_artifact(workspace: Path, artifact: Mapping[str, Any], *, overwrite: bool = False) -> bool:
    return _persist_kind_artifact(workspace, artifact, overwrite)


def persist_revision_report_artifact(workspace: Path, artifact: Mapping[str, Any], *, overwrite: bool = False) -> bool:
    return _persist_kind_artifact(workspace, artifact, overwrite)


def persist_build_result_artifact(workspace: Path, artifact: Mapping[str, Any], *, overwrite: bool = False) -> bool:
    """Persist an adaptation artifact or a legacy packet-builder result.

    The packet builder historically imported this symbol under the same name
    as the adaptation artifact writer. Keep the adaptation contract strict,
    while routing its plain build-result payload to the legacy workspace
    artifact writer instead of silently reporting persistence failure.
    """
    if isinstance(artifact, Mapping) and "artifact_kind" not in artifact:
        from utils.toolkit_homebrew_upload_contract import (
            persist_build_result_artifact as persist_legacy_build_result_artifact,
        )

        return bool(
            persist_legacy_build_result_artifact(
                Path(workspace),
                dict(artifact),
            )
        )
    return _persist_kind_artifact(workspace, artifact, overwrite)


def persist_publication_report_artifact(workspace: Path, artifact: Mapping[str, Any], *, overwrite: bool = False) -> bool:
    return _persist_kind_artifact(workspace, artifact, overwrite)


persist_attempt_report_artifact = persist_build_result_artifact
persist_adaptation_attempt_report = persist_build_result_artifact


__all__ = [
    "ADAPTATION_ARTIFACT_CONTRACT_VERSION",
    "ADAPTATION_ARTIFACT_SCHEMA_VERSION",
    "ADAPTATION_ARTIFACT_ROOT",
    "ARTIFACT_KIND_SOURCE_CONTEXT",
    "ARTIFACT_KIND_ADAPTATION_DOSSIER",
    "ARTIFACT_KIND_FAILURE_REPORT",
    "ARTIFACT_KIND_REVISION_REPORT",
    "ARTIFACT_KIND_BUILD_RESULT",
    "ARTIFACT_KIND_PUBLICATION_REPORT",
    "ARTIFACT_KIND_ATTEMPT_REPORT",
    "VALID_ARTIFACT_KINDS",
    "ARTIFACT_VERSION_BY_KIND",
    "ARTIFACT_STAGE_DRAFT",
    "ARTIFACT_STAGE_FAILED",
    "ARTIFACT_STAGE_REVISED",
    "ARTIFACT_STAGE_BUILD",
    "ARTIFACT_STAGE_PUBLICATION",
    "VALID_ARTIFACT_STAGES",
    "ARTIFACT_STATUS_DRAFT",
    "ARTIFACT_STATUS_FAILED",
    "ARTIFACT_STATUS_REVISED",
    "ARTIFACT_STATUS_PENDING",
    "ARTIFACT_STATUS_PASSED",
    "ARTIFACT_STATUS_BLOCKED",
    "ARTIFACT_STATUS_PUBLISHED",
    "ARTIFACT_STATUS_DEFERRED",
    "FAILURE_CLASS_PROVIDER",
    "FAILURE_CLASS_FILE",
    "FAILURE_CLASS_DEPENDENCY",
    "FAILURE_CLASS_QUOTA",
    "FAILURE_CLASS_TIMEOUT",
    "FAILURE_CLASS_RIGHTS",
    "FAILURE_CLASS_MECHANICAL",
    "FAILURE_CLASS_SEMANTIC",
    "FAILURE_CLASS_PUBLICATION",
    "FAILURE_CLASS_UNKNOWN",
    "VALID_FAILURE_CLASSES",
    "REVISION_DECISION_REVISE",
    "REVISION_DECISION_REFUSE",
    "REVISION_DECISION_FAILED",
    "VALID_REVISION_DECISIONS",
    "BUILD_STATUS_PENDING",
    "BUILD_STATUS_PASSED",
    "BUILD_STATUS_FAILED",
    "BUILD_STATUS_BLOCKED",
    "VALID_BUILD_STATUSES",
    "PUBLICATION_STATUS_PENDING",
    "PUBLICATION_STATUS_PUBLISHED",
    "PUBLICATION_STATUS_FAILED",
    "PUBLICATION_STATUS_BLOCKED",
    "PUBLICATION_STATUS_DEFERRED",
    "VALID_PUBLICATION_STATUSES",
    "SOURCE_CONTEXT_STATUS_AVAILABLE",
    "SOURCE_CONTEXT_STATUS_REFERENCED",
    "SOURCE_CONTEXT_STATUS_UNAVAILABLE",
    "VALID_SOURCE_CONTEXT_STATUSES",
    "REPORT_FRESHNESS_CURRENT",
    "REPORT_FRESHNESS_AUTHORITATIVE",
    "REPORT_FRESHNESS_DEGRADED",
    "REPORT_FRESHNESS_STALE",
    "VALID_REPORT_FRESHNESS_STATES",
    "ARTIFACT_DIAGNOSTIC_CODE_ARTIFACT_EXISTS",
    "ARTIFACT_DIAGNOSTIC_CODE_INVALID_JSON",
    "ARTIFACT_DIAGNOSTIC_CODE_INVALID_PATH",
    "ARTIFACT_DIAGNOSTIC_CODE_UNBOUNDED_SOURCE",
    "ARTIFACT_DIAGNOSTIC_CODE_WRITE_FAILED",
    "MAX_ARTIFACT_BYTES",
    "MAX_SOURCE_SUMMARY_CHARS",
    "build_attempt_id",
    "make_attempt_id",
    "get_adaptation_artifact_schema_path",
    "get_adaptation_attempt_workspace",
    "get_attempt_workspace",
    "get_adaptation_artifact_path",
    "get_attempt_artifact_paths",
    "load_adaptation_artifact_schema",
    "validate_adaptation_artifact",
    "validate_attempt_artifact",
    "parse_adaptation_artifact",
    "parse_attempt_artifact",
    "build_adaptation_artifact",
    "build_artifact",
    "build_source_context_artifact",
    "build_adaptation_dossier_artifact",
    "build_failure_report_artifact",
    "build_revision_report_artifact",
    "build_build_result_artifact",
    "build_attempt_report_artifact",
    "build_adaptation_attempt_report",
    "build_publication_report_artifact",
    "persist_adaptation_artifact",
    "persist_artifact",
    "persist_attempt_artifact",
    "persist_source_context_artifact",
    "persist_adaptation_dossier_artifact",
    "persist_failure_report_artifact",
    "persist_revision_report_artifact",
    "persist_build_result_artifact",
    "persist_attempt_report_artifact",
    "persist_adaptation_attempt_report",
    "persist_publication_report_artifact",
    "load_adaptation_artifact",
    "load_artifact",
    "load_attempt_artifact",
    "load_attempt_report_artifact",
    "load_adaptation_attempt_report",
    "get_artifact_path",
]
