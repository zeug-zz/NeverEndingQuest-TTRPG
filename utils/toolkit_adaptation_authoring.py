# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Authoring Preflight
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Attempt-scoped orchestration for the LLM adaptation author.  Python owns the
source identity, rights metadata, artifact persistence, dossier validation,
and handoff gate.  This module deliberately stops before ModuleBuilder and
never creates or publishes module files.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root for full terms.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_SOURCE_CONTEXT,
    ARTIFACT_STAGE_FAILED,
    ARTIFACT_STATUS_FAILED,
    FAILURE_CLASS_DEPENDENCY,
    FAILURE_CLASS_FILE,
    FAILURE_CLASS_PROVIDER,
    FAILURE_CLASS_QUOTA,
    FAILURE_CLASS_TIMEOUT,
    FAILURE_CLASS_UNKNOWN,
    build_adaptation_artifact,
    build_adaptation_dossier_artifact,
    build_attempt_id,
    get_adaptation_artifact_path,
    persist_adaptation_artifact,
)
from utils.toolkit_adaptation_author import (
    DIAGNOSTIC_CODE_DOSSIER_FAILED,
    DIAGNOSTIC_CODE_DOSSIER_NOT_BUILD_READY,
    DIAGNOSTIC_CODE_DOSSIER_REFUSED,
    DIAGNOSTIC_CODE_INVALID_PROVENANCE,
    FAILURE_CLASS_DEPENDENCY as AUTHOR_FAILURE_CLASS_DEPENDENCY,
    FAILURE_CLASS_FILE as AUTHOR_FAILURE_CLASS_FILE,
    FAILURE_CLASS_MODEL_RESPONSE,
    FAILURE_CLASS_PROVIDER as AUTHOR_FAILURE_CLASS_PROVIDER,
    FAILURE_CLASS_QUOTA as AUTHOR_FAILURE_CLASS_QUOTA,
    FAILURE_CLASS_REFUSAL,
    FAILURE_CLASS_TIMEOUT as AUTHOR_FAILURE_CLASS_TIMEOUT,
    REASON_CATEGORY_AUTHOR_POLICY_REFUSAL,
    REASON_CATEGORY_DEPENDENCY,
    REASON_CATEGORY_DOSSIER_VALIDATION,
    REASON_CATEGORY_FILE_IO,
    REASON_CATEGORY_INVALID_INPUT,
    REASON_CATEGORY_NONE,
    REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
    REASON_CATEGORY_RIGHTS_OR_PROVENANCE,
    REASON_CATEGORY_TIMEOUT,
    REASON_CATEGORY_QUOTA,
    REASON_CODE_DEPENDENCY_IMPORT_FAILED,
    REASON_CODE_DOSSIER_FAILED,
    REASON_CODE_DOSSIER_NOT_BUILD_READY,
    REASON_CODE_DOSSIER_REFUSED,
    REASON_CODE_FILE_IO_FAILED,
    REASON_CODE_INVALID_AUTHOR_INPUT,
    REASON_CODE_NONE,
    REASON_CODE_PROVIDER_CALL_FAILED,
    REASON_CODE_QUOTA_EXCEEDED,
    REASON_CODE_REQUEST_TIMEOUT,
    REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH,
    parse_adaptation_author_response,
    run_llm_adaptation_author,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    ADAPTATION_DOSSIER_STATUS_READY,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_REVIEW_APPROVED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
    RIGHTS_REVIEW_REJECTED,
    VALID_RIGHTS_CLASSES,
    VALID_RIGHTS_REVIEW_STATUSES,
    VALID_SOURCE_PROFILES,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_adaptation_proposals import (
    build_adaptation_proposal_ledger,
    get_adaptation_proposal_path,
    persist_adaptation_proposal_ledger,
)


AUTHORING_STATUS_READY = "ready"
AUTHORING_STATUS_BLOCKED = "blocked"
AUTHORING_OUTCOME_HANDOFF_READY = "handoff_ready"
AUTHORING_OUTCOME_BLOCKED = "blocked"
AUTHORING_FAILURE_STAGE = ARTIFACT_STAGE_FAILED

DIAGNOSTIC_SEVERITY_ERROR = "error"
DIAGNOSTIC_CODE_INVALID_PREFLIGHT = "invalid_preflight"
DIAGNOSTIC_CODE_INVALID_SOURCE = "invalid_source_provenance"
DIAGNOSTIC_CODE_INVALID_RIGHTS = "invalid_rights_metadata"
DIAGNOSTIC_CODE_INVALID_MODEL_METADATA = "invalid_model_metadata"
DIAGNOSTIC_CODE_ATTEMPT_EXISTS = "attempt_already_exists"
DIAGNOSTIC_CODE_SOURCE_CONTEXT_PERSISTENCE = "source_context_persistence_failed"
DIAGNOSTIC_CODE_DOSSIER_PERSISTENCE = "dossier_persistence_failed"
DIAGNOSTIC_CODE_PROPOSAL_PERSISTENCE = "proposal_ledger_persistence_failed"
DIAGNOSTIC_CODE_FAILURE_REPORT_PERSISTENCE = "failure_report_persistence_failed"
DIAGNOSTIC_CODE_INVALID_DOSSIER = "invalid_authoring_dossier"
DIAGNOSTIC_CODE_RUNNER_EXCEPTION = "author_runner_failed"

MAX_DIAGNOSTICS = 12
MAX_DIAGNOSTIC_TEXT = 320
MAX_MODEL_METADATA_TEXT = 160
MAX_SOURCE_SUMMARY = 4000
MAX_SOURCE_REFERENCES = 32

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MODEL_METADATA_KEYS = frozenset(
    {
        "provider",
        "model",
        "model_version",
        "request_id",
        "parameter_profile",
        "temperature",
        "reasoning_effort",
        "verbosity",
    }
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ascii_text(value: Any, limit: int = MAX_DIAGNOSTIC_TEXT) -> str:
    text = str(value).encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _diagnostic(code: str, message: str, path: str = "") -> Dict[str, str]:
    return {
        "code": _ascii_text(code, 96),
        "message": _ascii_text(message),
        "path": _ascii_text(path, 160),
        "severity": DIAGNOSTIC_SEVERITY_ERROR,
    }


def _bounded_diagnostics(
    diagnostics: Any,
    *,
    fallback_code: str = DIAGNOSTIC_CODE_INVALID_PREFLIGHT,
    fallback_message: str = "Adaptation authoring was blocked.",
) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    if isinstance(diagnostics, Sequence) and not isinstance(diagnostics, (str, bytes)):
        for item in list(diagnostics)[:MAX_DIAGNOSTICS]:
            if isinstance(item, Mapping):
                result.append(
                    _diagnostic(
                        str(item.get("code") or fallback_code),
                        str(item.get("message") or fallback_message),
                        str(item.get("path") or ""),
                    )
                )
            elif item is not None:
                result.append(_diagnostic(fallback_code, str(item)))
    if not result:
        result.append(_diagnostic(fallback_code, fallback_message))
    return result[:MAX_DIAGNOSTICS]


def _safe_project_relative_path(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith(("/", "\\")) or "\\" in text:
        return None
    if re.match(r"^[A-Za-z]:", text):
        return None
    parts = PurePosixPath(text).parts
    if not parts or any(part == ".." for part in parts):
        return None
    return text


def _safe_artifact_path(path: Path) -> str:
    """Return a project-relative artifact reference when possible."""
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _source_reference(context: Mapping[str, Any]) -> Mapping[str, Any]:
    value = context.get("source_ref")
    return value if isinstance(value, Mapping) else {}


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _infer_provider(model: str, client: Any, explicit: Any) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return _ascii_text(explicit.strip().lower(), MAX_MODEL_METADATA_TEXT)
    if client is not None:
        return "injected"
    lowered = model.lower()
    if lowered.startswith(("moonshotai/", "anthropic/", "google/")):
        return "openrouter"
    if lowered.startswith(("gpt-", "openai/")):
        return "openai"
    return "configured"


def _configured_model() -> str:
    try:
        from model_config import DM_MAIN_MODEL

        if isinstance(DM_MAIN_MODEL, str) and DM_MAIN_MODEL.strip():
            return DM_MAIN_MODEL.strip()
    except Exception:
        pass
    return "configured-default"


def _model_metadata(
    supplied: Optional[Mapping[str, Any]],
    *,
    requested_model: Any,
    provider: Any,
    client: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    diagnostics: List[Dict[str, str]] = []
    if supplied is not None and not isinstance(supplied, Mapping):
        return {}, [_diagnostic(DIAGNOSTIC_CODE_INVALID_MODEL_METADATA, "model_metadata must be an object")]

    raw = dict(supplied or {})
    metadata: Dict[str, Any] = {}
    for key in _MODEL_METADATA_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, str):
            if not value.strip():
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_MODEL_METADATA, "model metadata text cannot be empty", key))
                continue
            metadata[key] = _ascii_text(value.strip(), MAX_MODEL_METADATA_TEXT)
        elif isinstance(value, bool):
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_MODEL_METADATA, "model metadata must use scalar provider fields", key))
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            metadata[key] = value
        else:
            diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_MODEL_METADATA, "model metadata value is invalid", key))

    if "temperature" in metadata and not 0 <= float(metadata["temperature"]) <= 2:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_MODEL_METADATA, "temperature is outside the supported range", "temperature"))
        metadata.pop("temperature", None)

    selected_model = _first_non_empty(requested_model, metadata.get("model"), _configured_model())
    if not selected_model:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_MODEL_METADATA, "model metadata requires a model"))
    else:
        metadata["model"] = _ascii_text(selected_model, MAX_MODEL_METADATA_TEXT)

    metadata["provider"] = _infer_provider(metadata["model"], client, provider or metadata.get("provider"))
    metadata.setdefault("parameter_profile", "toolkit_adaptation_author")
    metadata["parameter_profile"] = _ascii_text(metadata["parameter_profile"], MAX_MODEL_METADATA_TEXT)
    return metadata, diagnostics


def _merge_model_metadata(base: Mapping[str, Any], author_result: Mapping[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key in ("provider", "model"):
        value = author_result.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = _ascii_text(value.strip(), MAX_MODEL_METADATA_TEXT)
    response_metadata = author_result.get("response_metadata")
    if isinstance(response_metadata, Mapping):
        for key in ("model", "request_id"):
            value = response_metadata.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = _ascii_text(value.strip(), MAX_MODEL_METADATA_TEXT)
    params_used = author_result.get("params_used")
    if isinstance(params_used, Mapping):
        for key in ("temperature", "reasoning_effort", "verbosity"):
            value = params_used.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                if isinstance(value, str) and not value.strip():
                    continue
                merged[key] = _ascii_text(value, MAX_MODEL_METADATA_TEXT) if isinstance(value, str) else value
    return {key: value for key, value in merged.items() if key in _MODEL_METADATA_KEYS}


def _metadata_envelope(
    *,
    job_id: str,
    source_profile: str,
    source_format: Optional[str],
    context_status: str,
    world_context_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    metadata: Dict[str, str] = {
        "created_by": "toolkit_adaptation_authoring",
        "source_profile": _ascii_text(source_profile, 32),
        "source_context_status": _ascii_text(context_status, 32),
        "publication_policy": "python_authority_before_publication",
    }
    if job_id.strip():
        metadata["job_id"] = _ascii_text(job_id.strip(), 160)
    if source_format:
        metadata["source_format"] = _ascii_text(source_format, 32)
    world = build_world_context_provenance(world_context_provenance)
    scalar_fields = {
        "world_seed_status": world.get("world_seed_status"),
        "world_seed_version": world.get("world_seed_version"),
        "world_seed_hash": world.get("world_seed_hash"),
        "world_context_status": world.get("context_status"),
        "world_context_version": world.get("context_version"),
        "world_context_hash": world.get("context_hash"),
        "context_hash": world.get("context_hash"),
        "world_context_selected_module": world.get("selected_module"),
    }
    for key, value in scalar_fields.items():
        if value not in (None, ""):
            metadata[key] = _ascii_text(value, 240)
    return metadata


def _world_context_metadata(provenance: Mapping[str, Any]) -> Dict[str, Any]:
    """Return scalar world provenance fields for Python-owned attempt metadata."""
    values = {
        "world_seed_status": provenance.get("world_seed_status"),
        "world_seed_version": provenance.get("world_seed_version"),
        "world_seed_hash": provenance.get("world_seed_hash"),
        "world_context_status": provenance.get("context_status"),
        "world_context_version": provenance.get("context_version"),
        "world_context_hash": provenance.get("context_hash"),
        "context_hash": provenance.get("context_hash"),
        "world_context_selected_module": provenance.get("selected_module"),
        "world_context_read_only": provenance.get("read_only"),
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def _extract_context_refs(context: Mapping[str, Any], source_hash: str) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    refs: List[Dict[str, Any]] = []
    manifest_ref: Optional[Dict[str, Any]] = None
    seen = set()
    source_inputs = context.get("source_inputs")
    if isinstance(source_inputs, list):
        for item in source_inputs[:MAX_SOURCE_REFERENCES]:
            if not isinstance(item, Mapping):
                continue
            raw_ref = item.get("source_ref")
            if not isinstance(raw_ref, Mapping):
                continue
            path = _safe_project_relative_path(raw_ref.get("path"))
            digest = str(raw_ref.get("sha256") or "").strip().lower()
            if not path or not _SHA256_RE.fullmatch(digest) or digest != source_hash:
                continue
            key = (path, digest, str(item.get("kind") or "source_context"))
            if key in seen:
                continue
            seen.add(key)
            ref = {
                "path": path,
                "sha256": digest,
                "kind": _ascii_text(item.get("kind") or "source_context", 80),
                "reference_only": True,
            }
            refs.append(ref)
            if item.get("kind") == "source_manifest" and manifest_ref is None:
                manifest_ref = {"path": path, "sha256": digest}
    return refs[:MAX_SOURCE_REFERENCES], manifest_ref


def _build_source_context_payload(
    context: Mapping[str, Any],
    *,
    source_path: str,
    source_hash: str,
    source_profile: str,
) -> Dict[str, Any]:
    refs, manifest_ref = _extract_context_refs(context, source_hash)
    if not refs:
        refs = [{
            "path": source_path,
            "sha256": source_hash,
            "kind": "source_context",
            "reference_only": True,
        }]
    source_ref: Dict[str, Any] = {"path": source_path, "sha256": source_hash}
    raw_source_ref = _source_reference(context)
    if isinstance(raw_source_ref.get("size_bytes"), int) and not isinstance(raw_source_ref.get("size_bytes"), bool):
        if 0 <= raw_source_ref["size_bytes"] <= 50_000_000:
            source_ref["size_bytes"] = raw_source_ref["size_bytes"]
    context_status = context.get("context_status")
    if context_status not in {"available", "referenced", "unavailable"}:
        context_status = "referenced"
    profile_reason = _ascii_text(context.get("profile_reason") or "", 1000)
    summary = "Bounded source context prepared for adaptation authoring."
    if profile_reason:
        summary = "Profile guidance: " + profile_reason
    payload: Dict[str, Any] = {
        "context_status": context_status,
        "source_ref": source_ref,
        "source_profile": source_profile,
        "summary": summary[:MAX_SOURCE_SUMMARY],
        "bounded_context_refs": refs,
    }
    if manifest_ref is not None:
        payload["manifest_ref"] = manifest_ref
    if profile_reason:
        payload["profile_reason"] = profile_reason
    return payload


def _preflight_values(
    source_context: Any,
    *,
    world_context: Any,
    source_title: Optional[str],
    source_hash: Optional[str],
    source_path: Optional[str],
    source_profile: Optional[str],
    rights_metadata: Optional[Mapping[str, Any]],
    rights_class: Optional[str],
    rights_basis: Optional[str],
    rights_review_required: Optional[bool],
    rights_review_status: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    diagnostics: List[Dict[str, str]] = []
    if not isinstance(source_context, Mapping):
        return None, [_diagnostic(DIAGNOSTIC_CODE_INVALID_PREFLIGHT, "source_context must be an object")]
    rights = dict(rights_metadata or {}) if isinstance(rights_metadata, Mapping) else {}
    if rights_metadata is not None and not isinstance(rights_metadata, Mapping):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "rights_metadata must be an object"))

    ref = _source_reference(source_context)
    hash_candidates = [source_hash, source_context.get("source_hash"), ref.get("sha256")]
    resolved_hash = None
    for index, candidate in enumerate(hash_candidates):
        if isinstance(candidate, str) and candidate.strip():
            normalized = candidate.strip().lower()
            if _SHA256_RE.fullmatch(normalized):
                resolved_hash = normalized
                break
            if index == 0 or index == 1:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source hash must be a lowercase SHA-256 digest", "source_hash"))
    if source_hash is not None and not isinstance(source_hash, str):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source hash must be text", "source_hash"))
    if not resolved_hash:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source hash must be a lowercase SHA-256 digest", "source_hash"))
    for candidate in hash_candidates:
        if isinstance(candidate, str) and candidate.strip() and _SHA256_RE.fullmatch(candidate.strip().lower()):
            if resolved_hash and candidate.strip().lower() != resolved_hash:
                diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source hash references do not agree", "source_hash"))

    resolved_path = _safe_project_relative_path(_first_non_empty(source_path, ref.get("path")))
    if not resolved_path:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source path must be project-relative", "source_path"))
    resolved_title = _first_non_empty(source_title, source_context.get("source_title"))
    if not resolved_title:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source title is required", "source_title"))
        resolved_title = "Untitled readable source"
    resolved_title = _ascii_text(resolved_title, 4000)

    resolved_profile = _first_non_empty(source_profile, source_context.get("source_profile"))
    if resolved_profile not in VALID_SOURCE_PROFILES:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source profile is required", "source_profile"))
    resolved_profile = resolved_profile or "adventure"

    if source_context.get("assembly_status") == "invalid":
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_SOURCE, "source context assembly is invalid", "assembly_status"))

    resolved_rights_class = rights_class if rights_class is not None else rights.get("rights_class", source_context.get("rights_class"))
    resolved_rights_basis = rights_basis if rights_basis is not None else rights.get("rights_basis", source_context.get("rights_basis"))
    resolved_review_required = rights_review_required if rights_review_required is not None else rights.get("rights_review_required", source_context.get("rights_review_required"))
    resolved_review_status = rights_review_status if rights_review_status is not None else rights.get("rights_review_status", source_context.get("rights_review_status"))
    if resolved_rights_class not in VALID_RIGHTS_CLASSES:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "rights_class is required and unsupported", "rights_class"))
    if not isinstance(resolved_rights_basis, str) or not resolved_rights_basis.strip():
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "rights_basis is required", "rights_basis"))
    if not isinstance(resolved_review_required, bool):
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "rights_review_required must be boolean", "rights_review_required"))
    if resolved_review_status not in VALID_RIGHTS_REVIEW_STATUSES:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "rights_review_status is required and unsupported", "rights_review_status"))
    if resolved_rights_class == RIGHTS_CLASS_RESTRICTED and resolved_review_required is not True:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "restricted source requires rights review", "rights_review_required"))
    if resolved_review_required is True and resolved_review_status == RIGHTS_REVIEW_NOT_REQUIRED:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "required review cannot be not_required", "rights_review_status"))
    if resolved_review_required is False and resolved_review_status in {RIGHTS_REVIEW_PENDING, RIGHTS_REVIEW_REJECTED}:
        diagnostics.append(_diagnostic(DIAGNOSTIC_CODE_INVALID_RIGHTS, "non-required review cannot be pending or rejected", "rights_review_status"))

    world_context_candidate = world_context
    if world_context_candidate is None:
        for key in ("world_context", "world_narrative_context"):
            if isinstance(source_context.get(key), Mapping):
                world_context_candidate = source_context.get(key)
                break
    world_context_provenance = build_world_context_provenance(world_context_candidate)
    if diagnostics:
        return None, diagnostics
    return {
        "source_context": deepcopy(dict(source_context)),
        "world_context_provenance": world_context_provenance,
        "source_title": resolved_title,
        "source_hash": resolved_hash,
        "source_path": resolved_path,
        "source_profile": resolved_profile,
        "rights_class": str(resolved_rights_class),
        "rights_basis": _ascii_text(resolved_rights_basis, 500),
        "rights_review_required": resolved_review_required,
        "rights_review_status": str(resolved_review_status),
    }, []


def _base_result(preflight: Mapping[str, Any], *, status: str, ok: bool) -> Dict[str, Any]:
    return {
        "status": status,
        "outcome": AUTHORING_OUTCOME_HANDOFF_READY if ok else AUTHORING_OUTCOME_BLOCKED,
        "ok": ok,
        "completed": False,
        "module_builder_allowed": bool(ok),
        "module_builder_started": False,
        "publication_started": False,
        "registry_mutated": False,
        "completed_module_artifacts": [],
        "attempt_id": preflight.get("attempt_id"),
        "attempt_number": preflight.get("attempt_number"),
        "attempt_metadata": deepcopy(preflight.get("attempt_metadata") or {}),
        "source_hash": preflight.get("source_hash"),
        "source_path": preflight.get("source_path"),
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "rights_class": preflight.get("rights_class"),
        "rights_review_required": preflight.get("rights_review_required"),
        "rights_review_status": preflight.get("rights_review_status"),
        "world_context_provenance": deepcopy(preflight.get("world_context_provenance") or {}),
        "world_seed_status": (preflight.get("world_context_provenance") or {}).get("world_seed_status"),
        "world_seed_version": (preflight.get("world_context_provenance") or {}).get("world_seed_version"),
        "world_seed_hash": (preflight.get("world_context_provenance") or {}).get("world_seed_hash"),
        "model_metadata": deepcopy(preflight.get("model_metadata") or {}),
        "source_context_artifact_path": preflight.get("source_context_artifact_path"),
        "source_context_artifact_persisted": bool(preflight.get("source_context_artifact_persisted")),
        "dossier_artifact_path": None,
        "dossier_artifact_persisted": False,
        "proposal_ledger_path": None,
        "proposal_ledger_persisted": False,
        "proposal_status": None,
        "proposal_count": 0,
        "proposal_ledger_hash": None,
        "failure_artifact_path": None,
        "failure_artifact_persisted": False,
        # Bounded safe diagnostics (task 3.2): authoring results carry an
        # explicit reason category/code and never consume the semantic
        # revision budget. Blocked paths override these via ``_record_failure``
        # and the ready path sets the none markers explicitly.
        "safe_class": None,
        "reason_code": None,
        "revision_eligible": False,
        "retryable": False,
        "terminal": False,
        "diagnostics": [],
        "dossier": None,
    }


def _reason_for_authoring_class(
    failure_class: Any,
) -> Tuple[str, str]:
    """Map a bounded authoring failure class to a safe reason category/code."""
    if failure_class == FAILURE_CLASS_TIMEOUT:
        return REASON_CATEGORY_TIMEOUT, REASON_CODE_REQUEST_TIMEOUT
    if failure_class == FAILURE_CLASS_QUOTA:
        return REASON_CATEGORY_QUOTA, REASON_CODE_QUOTA_EXCEEDED
    if failure_class == FAILURE_CLASS_DEPENDENCY:
        return REASON_CATEGORY_DEPENDENCY, REASON_CODE_DEPENDENCY_IMPORT_FAILED
    if failure_class == FAILURE_CLASS_FILE:
        return REASON_CATEGORY_FILE_IO, REASON_CODE_FILE_IO_FAILED
    if failure_class == FAILURE_CLASS_PROVIDER:
        return REASON_CATEGORY_PROVIDER_INFRASTRUCTURE, REASON_CODE_PROVIDER_CALL_FAILED
    return REASON_CATEGORY_INVALID_INPUT, REASON_CODE_INVALID_AUTHOR_INPUT


def _reason_from_diagnostics(
    diagnostics: Any,
) -> Optional[Tuple[str, str]]:
    """Derive a safe reason category/code from bounded diagnostic codes.

    Used as the fallback when an injected author runner does not yet carry
    ``safe_class``/``reason_code``, so refusal, rights/provenance, and dossier
    outcomes stay distinguishable at the authoring boundary.
    """
    if not isinstance(diagnostics, Sequence) or isinstance(diagnostics, (str, bytes)):
        return None
    codes: set[str] = set()
    for item in diagnostics:
        if isinstance(item, Mapping):
            code = item.get("code")
            if isinstance(code, str) and code:
                codes.add(code)
    if DIAGNOSTIC_CODE_DOSSIER_REFUSED in codes:
        return REASON_CATEGORY_AUTHOR_POLICY_REFUSAL, REASON_CODE_DOSSIER_REFUSED
    if DIAGNOSTIC_CODE_INVALID_PROVENANCE in codes:
        return REASON_CATEGORY_RIGHTS_OR_PROVENANCE, REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH
    if DIAGNOSTIC_CODE_DOSSIER_FAILED in codes:
        return REASON_CATEGORY_DOSSIER_VALIDATION, REASON_CODE_DOSSIER_FAILED
    if DIAGNOSTIC_CODE_DOSSIER_NOT_BUILD_READY in codes:
        return REASON_CATEGORY_DOSSIER_VALIDATION, REASON_CODE_DOSSIER_NOT_BUILD_READY
    return None


def prepare_adaptation_authoring_preflight(
    source_context: Mapping[str, Any],
    *,
    workspace: Path,
    world_context: Any = None,
    job_id: str = "",
    attempt_number: int = 1,
    source_title: Optional[str] = None,
    source_hash: Optional[str] = None,
    source_path: Optional[str] = None,
    source_profile: Optional[str] = None,
    source_format: Optional[str] = None,
    rights_metadata: Optional[Mapping[str, Any]] = None,
    rights_class: Optional[str] = None,
    rights_basis: Optional[str] = None,
    rights_review_required: Optional[bool] = None,
    rights_review_status: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    client: Any = None,
    artifact_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
) -> Dict[str, Any]:
    """Persist the immutable authoring preflight before provider or builder work."""
    values, diagnostics = _preflight_values(
        source_context,
        world_context=world_context,
        source_title=source_title,
        source_hash=source_hash,
        source_path=source_path,
        source_profile=source_profile,
        rights_metadata=rights_metadata,
        rights_class=rights_class,
        rights_basis=rights_basis,
        rights_review_required=rights_review_required,
        rights_review_status=rights_review_status,
    )
    if diagnostics or values is None:
        return {
            "ok": False,
            "status": AUTHORING_STATUS_BLOCKED,
            "diagnostics": _bounded_diagnostics(diagnostics),
            "attempt_id": None,
            "source_context_artifact_persisted": False,
            "module_builder_allowed": False,
            "completed": False,
        }

    if isinstance(job_id, str):
        safe_job_id = _ascii_text(job_id.strip(), 160)
    else:
        safe_job_id = ""
    try:
        attempt_id = build_attempt_id(values["source_hash"], attempt_number, safe_job_id)
    except Exception as exc:
        return {
            "ok": False,
            "status": AUTHORING_STATUS_BLOCKED,
            "diagnostics": [_diagnostic(DIAGNOSTIC_CODE_INVALID_PREFLIGHT, "attempt identity could not be created")],
            "attempt_id": None,
            "source_context_artifact_persisted": False,
            "module_builder_allowed": False,
            "completed": False,
            "error_class": FAILURE_CLASS_FILE,
        }
    if not _ATTEMPT_ID_RE.fullmatch(attempt_id):
        return {
            "ok": False,
            "status": AUTHORING_STATUS_BLOCKED,
            "diagnostics": [_diagnostic(DIAGNOSTIC_CODE_INVALID_PREFLIGHT, "attempt identity is not path-safe")],
            "attempt_id": None,
            "source_context_artifact_persisted": False,
            "module_builder_allowed": False,
            "completed": False,
        }

    requested_model = model
    metadata, metadata_diagnostics = _model_metadata(
        model_metadata,
        requested_model=requested_model,
        provider=provider,
        client=client,
    )
    if metadata_diagnostics:
        return {
            "ok": False,
            "status": AUTHORING_STATUS_BLOCKED,
            "diagnostics": _bounded_diagnostics(metadata_diagnostics),
            "attempt_id": attempt_id,
            "source_context_artifact_persisted": False,
            "module_builder_allowed": False,
            "completed": False,
            "error_class": FAILURE_CLASS_DEPENDENCY,
        }

    context_status = str(values["source_context"].get("context_status") or "referenced")
    if context_status not in {"available", "referenced", "unavailable"}:
        context_status = "referenced"
    attempt_metadata: Dict[str, Any] = {
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "revision_number": 0,
        "source_title": values["source_title"],
        "source_hash": values["source_hash"],
        "source_profile": values["source_profile"],
        "rights_class": values["rights_class"],
        "rights_basis": values["rights_basis"],
        "rights_review_required": values["rights_review_required"],
        "rights_review_status": values["rights_review_status"],
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "provider": metadata["provider"],
    }
    attempt_metadata.update(_world_context_metadata(values["world_context_provenance"]))
    if safe_job_id:
        attempt_metadata["job_id"] = safe_job_id

    workspace_path = Path(workspace)
    source_artifact_path = get_adaptation_artifact_path(
        workspace_path,
        attempt_id,
        ARTIFACT_KIND_SOURCE_CONTEXT,
    )
    preflight: Dict[str, Any] = {
        **values,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "attempt_metadata": attempt_metadata,
        "model_metadata": metadata,
        "source_context_artifact_path": _safe_artifact_path(source_artifact_path),
        "source_context_artifact_persisted": False,
        "artifact_persister": artifact_persister or persist_adaptation_artifact,
        "workspace": workspace_path,
        "source_format": source_format,
        "job_id": safe_job_id,
        "context_status": context_status,
    }

    # An existing source artifact is evidence for this exact attempt. Never
    # overwrite it and do not invoke the provider a second time.
    if source_artifact_path.exists():
        preflight["attempt_exists"] = True
        preflight["diagnostics"] = [_diagnostic(DIAGNOSTIC_CODE_ATTEMPT_EXISTS, "attempt identity already has source context evidence")]
        return preflight

    try:
        source_artifact = build_adaptation_artifact(
            ARTIFACT_KIND_SOURCE_CONTEXT,
            attempt_id=attempt_id,
            source_title=values["source_title"],
            source_hash=values["source_hash"],
            source_path=values["source_path"],
            attempt_number=attempt_number,
            revision_number=0,
            rights_class=values["rights_class"],
            rights_basis=values["rights_basis"],
            rights_review_required=values["rights_review_required"],
            rights_review_status=values["rights_review_status"],
            source_profile=values["source_profile"],
            source_format=source_format,
            model_metadata=metadata,
            metadata=_metadata_envelope(
                job_id=safe_job_id,
                source_profile=values["source_profile"],
                source_format=source_format,
                context_status=context_status,
                world_context_provenance=values["world_context_provenance"],
            ),
            world_context_provenance=values["world_context_provenance"],
            payload=_build_source_context_payload(
                values["source_context"],
                source_path=values["source_path"],
                source_hash=values["source_hash"],
                source_profile=values["source_profile"],
            ),
        )
        persisted = bool(preflight["artifact_persister"](workspace_path, source_artifact))
    except Exception:
        persisted = False
    if not persisted:
        preflight["diagnostics"] = [_diagnostic(DIAGNOSTIC_CODE_SOURCE_CONTEXT_PERSISTENCE, "source context provenance could not be persisted")]
        preflight["error_class"] = FAILURE_CLASS_FILE
        return preflight

    preflight["source_context_artifact_persisted"] = True
    preflight["source_context_artifact"] = source_artifact
    preflight["ok"] = True
    preflight["status"] = AUTHORING_STATUS_READY
    return preflight


def _artifact_metadata(preflight: Mapping[str, Any]) -> Dict[str, str]:
    return _metadata_envelope(
        job_id=str(preflight.get("job_id") or ""),
        source_profile=str(preflight.get("source_profile") or ""),
        source_format=preflight.get("source_format"),
        context_status=str(preflight.get("context_status") or "referenced"),
        world_context_provenance=preflight.get("world_context_provenance"),
    )


def _artifact_failure_class(raw_class: Any) -> str:
    value = str(raw_class or "").strip().lower()
    if value in {FAILURE_CLASS_TIMEOUT, AUTHOR_FAILURE_CLASS_TIMEOUT}:
        return FAILURE_CLASS_TIMEOUT
    if value in {FAILURE_CLASS_QUOTA, AUTHOR_FAILURE_CLASS_QUOTA}:
        return FAILURE_CLASS_QUOTA
    if value in {AUTHOR_FAILURE_CLASS_DEPENDENCY, FAILURE_CLASS_DEPENDENCY, "parameter_resolution"}:
        return FAILURE_CLASS_DEPENDENCY
    if value in {AUTHOR_FAILURE_CLASS_FILE, FAILURE_CLASS_FILE, "invalid_input", "prompt_failure"}:
        return FAILURE_CLASS_FILE
    if value in {AUTHOR_FAILURE_CLASS_PROVIDER, FAILURE_CLASS_PROVIDER, FAILURE_CLASS_MODEL_RESPONSE, FAILURE_CLASS_REFUSAL, "provider_failed", "model_response"}:
        return FAILURE_CLASS_PROVIDER
    if value in {"persistence", "source_context_persistence", "dossier_persistence"}:
        return FAILURE_CLASS_FILE
    return FAILURE_CLASS_UNKNOWN


def _record_failure(
    preflight: Mapping[str, Any],
    diagnostics: Any,
    *,
    failure_class: Any,
    artifact_persister: Callable[[Path, Mapping[str, Any]], bool],
    safe_class: Optional[str] = None,
    reason_code: Optional[str] = None,
    revision_eligible: bool = False,
    retryable: Optional[bool] = None,
    terminal: Optional[bool] = None,
) -> Dict[str, Any]:
    result = _base_result(preflight, status=AUTHORING_STATUS_BLOCKED, ok=False)
    bounded = _bounded_diagnostics(diagnostics)
    result["diagnostics"] = bounded
    resolved_class = _artifact_failure_class(failure_class)
    derived = _reason_from_diagnostics(bounded)
    if derived is None:
        derived = _reason_for_authoring_class(resolved_class)
    result["safe_class"] = safe_class or derived[0]
    result["reason_code"] = reason_code or derived[1]
    result["revision_eligible"] = bool(revision_eligible)
    # Retry eligibility defaults follow the derived safe category: timeout,
    # quota, and provider-infrastructure outcomes may be retried; every other
    # bounded outcome (refusal, rights, dossier, parameter, file, input) is
    # terminal and never consumes the semantic revision budget.
    derived_retryable = derived[0] in {
        REASON_CATEGORY_TIMEOUT,
        REASON_CATEGORY_QUOTA,
        REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
    }
    result["retryable"] = (
        bool(retryable) if retryable is not None else derived_retryable
    )
    result["terminal"] = (
        bool(terminal) if terminal is not None else not result["retryable"]
    )
    if not preflight.get("attempt_id") or not preflight.get("source_hash") or not preflight.get("source_path"):
        result["failure_artifact_persisted"] = False
        return result
    try:
        artifact = build_adaptation_artifact(
            ARTIFACT_KIND_FAILURE_REPORT,
            attempt_id=str(preflight["attempt_id"]),
            source_title=str(preflight.get("source_title") or "Untitled readable source"),
            source_hash=str(preflight["source_hash"]),
            source_path=str(preflight["source_path"]),
            attempt_number=int(preflight.get("attempt_number") or 1),
            revision_number=0,
            rights_class=str(preflight.get("rights_class") or ""),
            rights_basis=str(preflight.get("rights_basis") or ""),
            rights_review_required=bool(preflight.get("rights_review_required")),
            rights_review_status=str(preflight.get("rights_review_status") or RIGHTS_REVIEW_NOT_REQUIRED),
            source_profile=str(preflight.get("source_profile") or ""),
            source_format=preflight.get("source_format"),
            model_metadata=preflight.get("model_metadata") or {},
            metadata=_artifact_metadata(preflight),
            world_context_provenance=preflight.get("world_context_provenance"),
            stage=AUTHORING_FAILURE_STAGE,
            status=ARTIFACT_STATUS_FAILED,
            payload={
                "failure_class": resolved_class,
                "failed_stage": AUTHORING_FAILURE_STAGE,
                "diagnostics": bounded,
                "recoverable": False,
                "summary": "Adaptation authoring was blocked before ModuleBuilder.",
                "safe_class": result["safe_class"],
                "reason_code": result["reason_code"],
                "revision_eligible": result["revision_eligible"],
            },
        )
        persisted = bool(artifact_persister(Path(preflight["workspace"]), artifact))
    except Exception:
        artifact = None
        persisted = False
    if artifact is not None:
        failure_path = get_adaptation_artifact_path(
            Path(preflight["workspace"]),
            str(preflight["attempt_id"]),
            ARTIFACT_KIND_FAILURE_REPORT,
        )
        result["failure_artifact_path"] = _safe_artifact_path(failure_path)
    result["failure_artifact_persisted"] = persisted
    if not persisted:
        result["diagnostics"] = bounded + [_diagnostic(
            DIAGNOSTIC_CODE_FAILURE_REPORT_PERSISTENCE,
            "bounded failure diagnostics could not be persisted",
        )]
    return result


def run_adaptation_authoring(
    source_context: Mapping[str, Any],
    *,
    workspace: Path,
    world_context: Any = None,
    job_id: str = "",
    attempt_number: int = 1,
    source_title: Optional[str] = None,
    source_hash: Optional[str] = None,
    source_path: Optional[str] = None,
    source_profile: Optional[str] = None,
    source_format: Optional[str] = None,
    rights_metadata: Optional[Mapping[str, Any]] = None,
    rights_class: Optional[str] = None,
    rights_basis: Optional[str] = None,
    rights_review_required: Optional[bool] = None,
    rights_review_status: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    model_metadata: Optional[Mapping[str, Any]] = None,
    client: Any = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: Optional[float] = 120,
    author_runner: Callable[..., Dict[str, Any]] = run_llm_adaptation_author,
    artifact_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
    proposal_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
) -> Dict[str, Any]:
    """Author and persist a bounded dossier, stopping before ModuleBuilder.

    A successful return is only a Python-validated, attempt-scoped handoff
    candidate. ``completed`` is always false here; publication is intentionally
    owned by later tasks.
    """
    preflight = prepare_adaptation_authoring_preflight(
        source_context,
        workspace=workspace,
        world_context=world_context,
        job_id=job_id,
        attempt_number=attempt_number,
        source_title=source_title,
        source_hash=source_hash,
        source_path=source_path,
        source_profile=source_profile,
        source_format=source_format,
        rights_metadata=rights_metadata,
        rights_class=rights_class,
        rights_basis=rights_basis,
        rights_review_required=rights_review_required,
        rights_review_status=rights_review_status,
        model=model,
        provider=provider,
        model_metadata=model_metadata,
        client=client,
        artifact_persister=artifact_persister,
    )
    persister = artifact_persister or persist_adaptation_artifact
    proposal_writer = proposal_persister or persist_adaptation_proposal_ledger
    if preflight.get("attempt_exists"):
        result = _base_result(preflight, status=AUTHORING_STATUS_BLOCKED, ok=False)
        result["diagnostics"] = _bounded_diagnostics(preflight.get("diagnostics"), fallback_code=DIAGNOSTIC_CODE_ATTEMPT_EXISTS)
        result["idempotent_replay"] = True
        return result
    if not preflight.get("source_context_artifact_persisted"):
        return _record_failure(
            preflight,
            preflight.get("diagnostics"),
            failure_class=preflight.get("error_class", FAILURE_CLASS_FILE),
            artifact_persister=persister,
            safe_class=(
                REASON_CATEGORY_DEPENDENCY
                if preflight.get("error_class") == FAILURE_CLASS_DEPENDENCY
                else REASON_CATEGORY_FILE_IO
                if preflight.get("error_class") == FAILURE_CLASS_FILE
                else REASON_CATEGORY_INVALID_INPUT
            ),
            reason_code=(
                REASON_CODE_DEPENDENCY_IMPORT_FAILED
                if preflight.get("error_class") == FAILURE_CLASS_DEPENDENCY
                else REASON_CODE_FILE_IO_FAILED
                if preflight.get("error_class") == FAILURE_CLASS_FILE
                else REASON_CODE_INVALID_AUTHOR_INPUT
            ),
        )

    attempt_metadata = preflight["attempt_metadata"]
    requested_model = str((preflight.get("model_metadata") or {}).get("model") or _configured_model())
    try:
        author_result = author_runner(
            preflight["source_context"],
            attempt_metadata,
            client=client,
            model=requested_model,
            parameter_resolver=parameter_resolver,
            timeout_seconds=timeout_seconds,
            world_context=preflight.get("world_context_provenance"),
        )
    except Exception:
        return _record_failure(
            preflight,
            [_diagnostic(DIAGNOSTIC_CODE_RUNNER_EXCEPTION, "adaptation author runner raised an exception")],
            failure_class=FAILURE_CLASS_PROVIDER,
            artifact_persister=persister,
            safe_class=REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
            reason_code=REASON_CODE_PROVIDER_CALL_FAILED,
        )

    if not isinstance(author_result, Mapping):
        return _record_failure(
            preflight,
            [_diagnostic(DIAGNOSTIC_CODE_INVALID_DOSSIER, "adaptation author returned an invalid result envelope")],
            failure_class=FAILURE_CLASS_PROVIDER,
            artifact_persister=persister,
            safe_class=REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
            reason_code=REASON_CODE_PROVIDER_CALL_FAILED,
        )
    result_model_metadata = _merge_model_metadata(preflight["model_metadata"], author_result)
    preflight = dict(preflight)
    preflight["model_metadata"] = result_model_metadata
    if not author_result.get("ok"):
        failure_class = author_result.get("failure_class") or author_result.get("status")
        return _record_failure(
            preflight,
            author_result.get("diagnostics"),
            failure_class=failure_class,
            artifact_persister=persister,
            safe_class=author_result.get("safe_class"),
            reason_code=author_result.get("reason_code"),
            revision_eligible=bool(author_result.get("revision_eligible")),
            retryable=author_result.get("retryable"),
            terminal=author_result.get("terminal"),
        )

    dossier = author_result.get("dossier")
    if not isinstance(dossier, Mapping):
        return _record_failure(
            preflight,
            [_diagnostic(DIAGNOSTIC_CODE_INVALID_DOSSIER, "successful author result did not contain a dossier")],
            failure_class=FAILURE_CLASS_PROVIDER,
            artifact_persister=persister,
            safe_class=REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
            reason_code=REASON_CODE_PROVIDER_CALL_FAILED,
        )

    try:
        raw_dossier = json.dumps(dict(dossier), ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return _record_failure(
            preflight,
            [_diagnostic(DIAGNOSTIC_CODE_INVALID_DOSSIER, "author dossier was not JSON serializable")],
            failure_class=FAILURE_CLASS_PROVIDER,
            artifact_persister=persister,
            safe_class=REASON_CATEGORY_INVALID_INPUT,
            reason_code=REASON_CODE_INVALID_AUTHOR_INPUT,
        )
    parsed = parse_adaptation_author_response(raw_dossier, attempt_metadata=attempt_metadata)
    if not parsed.get("ok") or not isinstance(parsed.get("dossier"), Mapping):
        return _record_failure(
            preflight,
            parsed.get("diagnostics"),
            failure_class=parsed.get("failure_class", FAILURE_CLASS_PROVIDER),
            artifact_persister=persister,
            safe_class=parsed.get("safe_class"),
            reason_code=parsed.get("reason_code"),
            revision_eligible=bool(parsed.get("revision_eligible")),
            retryable=parsed.get("retryable"),
            terminal=parsed.get("terminal"),
        )
    normalized_dossier = dict(parsed["dossier"])
    for key in (
        "source_hash",
        "source_title",
        "source_profile",
        "rights_class",
        "rights_basis",
        "rights_review_required",
        "rights_review_status",
        "adaptation_mode",
    ):
        expected = ADAPTATION_MODE_LLM if key == "adaptation_mode" else preflight.get(key)
        if normalized_dossier.get(key) != expected:
            return _record_failure(
                preflight,
                [_diagnostic(DIAGNOSTIC_CODE_INVALID_DOSSIER, "provider changed Python-owned provenance metadata", key)],
                failure_class=FAILURE_CLASS_PROVIDER,
                artifact_persister=persister,
                safe_class=REASON_CATEGORY_RIGHTS_OR_PROVENANCE,
                reason_code=REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH,
            )
    if normalized_dossier.get("status") != ADAPTATION_DOSSIER_STATUS_READY:
        return _record_failure(
            preflight,
            [_diagnostic(DIAGNOSTIC_CODE_INVALID_DOSSIER, "dossier is not ready for a future builder handoff", "status")],
            failure_class=FAILURE_CLASS_PROVIDER,
            artifact_persister=persister,
            safe_class=REASON_CATEGORY_DOSSIER_VALIDATION,
            reason_code=REASON_CODE_DOSSIER_NOT_BUILD_READY,
        )

    try:
        dossier_artifact = build_adaptation_dossier_artifact(
            normalized_dossier,
            attempt_id=str(preflight["attempt_id"]),
            source_path=str(preflight["source_path"]),
            attempt_number=int(preflight["attempt_number"]),
            revision_number=0,
            model_metadata=result_model_metadata,
            metadata=_artifact_metadata(preflight),
            world_context_provenance=preflight.get("world_context_provenance"),
        )
        dossier_persisted = bool(persister(Path(preflight["workspace"]), dossier_artifact))
    except Exception:
        dossier_artifact = None
        dossier_persisted = False
    if not dossier_persisted or dossier_artifact is None:
        return _record_failure(
            preflight,
            [_diagnostic(DIAGNOSTIC_CODE_DOSSIER_PERSISTENCE, "validated adaptation dossier could not be persisted")],
            failure_class=FAILURE_CLASS_FILE,
            artifact_persister=persister,
            safe_class=REASON_CATEGORY_FILE_IO,
            reason_code=REASON_CODE_FILE_IO_FAILED,
        )

    result = _base_result(preflight, status=AUTHORING_STATUS_READY, ok=True)
    result["model_metadata"] = result_model_metadata
    result["dossier"] = deepcopy(normalized_dossier)
    result["safe_class"] = REASON_CATEGORY_NONE
    result["reason_code"] = REASON_CODE_NONE
    dossier_path = get_adaptation_artifact_path(
        Path(preflight["workspace"]),
        str(preflight["attempt_id"]),
        ARTIFACT_KIND_ADAPTATION_DOSSIER,
    )
    result["dossier_artifact_path"] = _safe_artifact_path(dossier_path)
    result["dossier_artifact_persisted"] = True

    # TABLETOP MODE: World hooks and continuations are persisted separately as
    # pending proposals. This ledger is not a canon or publication artifact.
    try:
        proposal_ledger = build_adaptation_proposal_ledger(
            normalized_dossier,
            attempt_metadata={
                **dict(preflight["attempt_metadata"]),
                "source_path": preflight.get("source_path"),
                "source_title": preflight.get("source_title"),
                "source_profile": preflight.get("source_profile"),
            },
            world_context_provenance=preflight.get("world_context_provenance"),
            revision_number=0,
            model_metadata=result_model_metadata,
        )
        proposal_persisted = bool(
            proposal_writer(Path(preflight["workspace"]), proposal_ledger)
        )
        proposal_path = get_adaptation_proposal_path(
            Path(preflight["workspace"]),
            str(preflight["attempt_id"]),
            0,
        )
    except Exception:
        proposal_ledger = None
        proposal_persisted = False
        proposal_path = None

    if not proposal_persisted or proposal_ledger is None:
        return _record_failure(
            preflight,
            [_diagnostic(
                DIAGNOSTIC_CODE_PROPOSAL_PERSISTENCE,
                "validated world proposals could not be persisted as a pending ledger",
            )],
            failure_class=FAILURE_CLASS_FILE,
            artifact_persister=persister,
        )

    result["proposal_ledger_path"] = _safe_artifact_path(proposal_path)
    result["proposal_ledger_persisted"] = True
    result["proposal_status"] = proposal_ledger.get("status")
    result["proposal_count"] = proposal_ledger.get("proposal_count", 0)
    result["proposal_ledger_hash"] = proposal_ledger.get("ledger_hash")
    result["handoff_ready"] = True
    return result


run_adaptation_authoring_preflight = run_adaptation_authoring
author_adaptation = run_adaptation_authoring


__all__ = [
    "ADAPTATION_MODE_LLM",
    "AUTHORING_OUTCOME_BLOCKED",
    "AUTHORING_OUTCOME_HANDOFF_READY",
    "AUTHORING_STATUS_BLOCKED",
    "AUTHORING_STATUS_READY",
    "author_adaptation",
    "prepare_adaptation_authoring_preflight",
    "run_adaptation_authoring",
    "run_adaptation_authoring_preflight",
]
