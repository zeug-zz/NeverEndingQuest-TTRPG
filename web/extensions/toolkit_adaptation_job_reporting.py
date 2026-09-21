# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Web Extension - Toolkit adaptation job reporting.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free, bounded status projection for the explicit LLM adaptation lane.
The projection is derived from Python-owned job and publication reports. It is
safe for polling responses and never exposes raw provider payloads, prompts,
credentials, or source content.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils.toolkit_adaptation_output_safety import (
    project_persisted_diagnostic,
    project_safe_event,
)


ADAPTATION_JOB_REPORT_CONTRACT_VERSION = "toolkit_adaptation_job_reporting.v1"
ADAPTATION_MODE_LLM = "llm_adaptation"

ADAPTATION_OUTCOME_IN_PROGRESS = "in_progress"
ADAPTATION_OUTCOME_SEMANTIC_REVISION = "semantic_revision"
ADAPTATION_OUTCOME_REVISION_EXHAUSTED = "revision_exhausted"
ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE = "infrastructure_failure"
ADAPTATION_OUTCOME_BLOCKED = "blocked"
ADAPTATION_OUTCOME_COMPLETED = "completed"
VALID_ADAPTATION_OUTCOMES = frozenset(
    {
        ADAPTATION_OUTCOME_IN_PROGRESS,
        ADAPTATION_OUTCOME_SEMANTIC_REVISION,
        ADAPTATION_OUTCOME_REVISION_EXHAUSTED,
        ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE,
        ADAPTATION_OUTCOME_BLOCKED,
        ADAPTATION_OUTCOME_COMPLETED,
    }
)

ADAPTATION_JOB_STATUS_REVISION_REQUIRED = "adaptation_revision_required"
ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED = "adaptation_revision_exhausted"
ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED = "adaptation_infrastructure_failed"
ADAPTATION_JOB_STATUS_BLOCKED = "adaptation_blocked"
ADAPTATION_JOB_STATUS_COMPLETED = "adaptation_completed"
ADAPTATION_TERMINAL_JOB_STATES = frozenset(
    {
        ADAPTATION_JOB_STATUS_REVISION_REQUIRED,
        ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED,
        ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED,
        ADAPTATION_JOB_STATUS_BLOCKED,
        ADAPTATION_JOB_STATUS_COMPLETED,
    }
)

ADAPTATION_PHASE_PREFLIGHT = "adaptation_preflight"
ADAPTATION_PHASE_SOURCE_CONTEXT = "adaptation_source_context"
ADAPTATION_PHASE_AUTHORING = "adaptation_authoring"
ADAPTATION_PHASE_STAGING = "adaptation_staging"
ADAPTATION_PHASE_BUILD = "adaptation_build"
ADAPTATION_PHASE_VALIDATION = "adaptation_validation"
ADAPTATION_PHASE_READINESS = "adaptation_readiness"
ADAPTATION_PHASE_SEMANTIC_AUDIT = "adaptation_semantic_audit"
ADAPTATION_PHASE_REVISION = "adaptation_revision"
ADAPTATION_PHASE_REVISION_BUILD = "adaptation_revision_build"
ADAPTATION_PHASE_REPORT = "adaptation_report"
ADAPTATION_PHASE_MARKDOWN = "adaptation_markdown"
ADAPTATION_PHASE_REGISTRY = "adaptation_registry"
ADAPTATION_PHASE_CAMPAIGN_SYNC = "adaptation_campaign_sync"
ADAPTATION_PHASE_ROLLBACK = "adaptation_rollback"
ADAPTATION_PHASE_COMPLETED = "adaptation_completed"
ADAPTATION_PHASE_REVISION_EXHAUSTED = "adaptation_revision_exhausted"
ADAPTATION_PHASE_INFRASTRUCTURE_FAILED = "adaptation_infrastructure_failed"
ADAPTATION_PHASE_BLOCKED = "adaptation_blocked"

ADAPTATION_CANONICAL_PHASES = (
    ADAPTATION_PHASE_PREFLIGHT,
    ADAPTATION_PHASE_SOURCE_CONTEXT,
    ADAPTATION_PHASE_AUTHORING,
    ADAPTATION_PHASE_STAGING,
    ADAPTATION_PHASE_BUILD,
    ADAPTATION_PHASE_VALIDATION,
    ADAPTATION_PHASE_READINESS,
    ADAPTATION_PHASE_SEMANTIC_AUDIT,
    ADAPTATION_PHASE_REVISION,
    ADAPTATION_PHASE_REVISION_BUILD,
    ADAPTATION_PHASE_REPORT,
    ADAPTATION_PHASE_MARKDOWN,
    ADAPTATION_PHASE_REGISTRY,
    ADAPTATION_PHASE_CAMPAIGN_SYNC,
    ADAPTATION_PHASE_ROLLBACK,
    ADAPTATION_PHASE_COMPLETED,
    ADAPTATION_PHASE_REVISION_EXHAUSTED,
    ADAPTATION_PHASE_INFRASTRUCTURE_FAILED,
    ADAPTATION_PHASE_BLOCKED,
)

_INFRASTRUCTURE_FAILURE_CLASSES = frozenset(
    {"provider", "file", "dependency", "quota", "timeout"}
)
_POLICY_FAILURE_CLASSES = frozenset({"rights", "refusal"})
_PUBLICATION_FAILURE_CLASSES = frozenset(
    {"publication", "rollback", "verification"}
)
_SEMANTIC_FAILURE_CLASSES = frozenset({"semantic", "mechanical"})
# Readiness-gate terminal statuses are explicit non-success outcomes for an
# adaptation job: the build never reaches the finisher and the job must map to
# the bounded blocked terminal instead of an in-progress surface.
_READINESS_BLOCKED_STATUSES = frozenset(
    {
        "repair_budget_exhausted",
        "ready_failed",
        "readiness_failed",
        "not_ready",
        "repair_failed",
        "validation_failed",
        "continuity_failed",
        "gate_blocked",
    }
)
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_SAFE_STAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_MAX_DIAGNOSTICS = 6
_MAX_HISTORY_ITEMS = 8
_ADAPTATION_PUBLICATION_TERMINAL_ERROR_PREFIX = "adaptation_publication_"
_ADAPTATION_PUBLICATION_CONTINUATION_STAGE = "adaptation_publication_continuation"
_ADAPTATION_FRESH_ARTIFACT_STATES = frozenset(
    {"current", "authoritative", "degraded"}
)


def _ascii_text(value: Any, limit: int = 240) -> str:
    """Return bounded, whitespace-normalized ASCII text."""
    if value is None:
        return ""
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    return text[:limit] + "..." if len(text) > limit else text


def _safe_code(value: Any, default: str = "unclassified") -> str:
    candidate = _ascii_text(value, 120).lower().replace(" ", "_")
    return candidate if _SAFE_CODE_RE.fullmatch(candidate) else default


def _safe_stage(value: Any) -> str:
    candidate = _ascii_text(value, 160).lower().replace(" ", "_")
    return candidate if _SAFE_STAGE_RE.fullmatch(candidate) else ""


def _safe_int(value: Any, default: int = 0, maximum: int = 100) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, min(value, maximum))


def _safe_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _mapping(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) else None


def _adaptation_identity(value: Any) -> Dict[str, Any]:
    """Extract the bounded identity carried by an adaptation artifact/report."""
    if not isinstance(value, Mapping):
        return {}
    provenance = _mapping(value.get("provenance")) or {}
    attempt_metadata = _mapping(value.get("attempt_metadata")) or {}
    nested_attempt = _mapping(value.get("attempt")) or {}
    source_identity = _mapping(value.get("source_identity")) or {}
    payload = _mapping(value.get("payload")) or {}
    source_ref = _mapping(payload.get("source_ref")) or {}
    nested_provenance = _mapping(value.get("adaptation_provenance")) or {}
    nested_provenance_attempt = _mapping(
        nested_provenance.get("attempt_metadata")
    ) or {}

    def first(*candidates: Any) -> Any:
        for candidate in candidates:
            if candidate not in (None, ""):
                return candidate
        return None

    return {
        "attempt_id": first(
            value.get("attempt_id"),
            provenance.get("attempt_id"),
            attempt_metadata.get("attempt_id"),
            nested_attempt.get("attempt_id"),
            nested_provenance.get("attempt_id"),
            nested_provenance_attempt.get("attempt_id"),
        ),
        "revision_number": first(
            value.get("revision_number"),
            provenance.get("revision_number"),
            attempt_metadata.get("revision_number"),
            nested_attempt.get("revision_number"),
            nested_provenance.get("revision_number"),
            nested_provenance_attempt.get("revision_number"),
        ),
        "attempt_number": first(
            value.get("attempt_number"),
            provenance.get("attempt_number"),
            attempt_metadata.get("attempt_number"),
            nested_attempt.get("attempt_number"),
            nested_provenance.get("attempt_number"),
            nested_provenance_attempt.get("attempt_number"),
        ),
        "source_hash": first(
            value.get("source_hash"),
            provenance.get("source_hash"),
            source_identity.get("source_hash"),
            source_ref.get("sha256"),
            nested_provenance.get("source_hash"),
        ),
        "source_path": first(
            value.get("source_path"),
            provenance.get("source_path"),
            source_identity.get("source_path"),
            source_ref.get("path"),
            nested_provenance.get("source_path"),
        ),
    }


def validate_adaptation_artifact_current(
    artifact: Any,
    *,
    expected_attempt_id: Any,
    expected_revision_number: Any,
    expected_source_hash: Any,
    expected_source_path: Any = None,
    label: str = "artifact",
) -> Dict[str, Any]:
    """Reject missing, stale, or cross-attempt adaptation artifacts.

    This helper is intentionally provider-free and returns only bounded identity
    diagnostics. Source paths are compared when both sides carry them; the
    existing handoff contract does not require every in-memory report to carry
    a source path.
    """
    safe_label = _safe_code(label, "artifact")
    if not isinstance(artifact, Mapping):
        return {
            "status": "blocked",
            "reason_code": f"adaptation_{safe_label}_missing",
            "diagnostics": [f"missing_current_artifact:{safe_label}"],
            "identity": {},
        }

    identity = _adaptation_identity(artifact)
    expected_id = str(expected_attempt_id or "").strip()
    expected_hash = str(expected_source_hash or "").strip().lower()
    expected_path = str(expected_source_path or "").strip()
    actual_id = str(identity.get("attempt_id") or "").strip()
    actual_hash = str(identity.get("source_hash") or "").strip().lower()
    actual_path = str(identity.get("source_path") or "").strip()
    try:
        expected_revision = int(expected_revision_number)
    except (TypeError, ValueError):
        expected_revision = 0
    actual_revision = identity.get("revision_number")
    try:
        actual_revision = int(actual_revision)
    except (TypeError, ValueError):
        actual_revision = None

    if expected_id and actual_id != expected_id:
        reason = "attempt_id_mismatch"
    elif expected_hash and actual_hash != expected_hash:
        reason = "source_hash_mismatch"
    elif actual_revision != expected_revision:
        reason = "revision_number_mismatch"
    elif expected_path and actual_path and actual_path != expected_path:
        reason = "source_path_mismatch"
    else:
        freshness = artifact.get("report_freshness")
        if isinstance(freshness, Mapping):
            freshness_state = str(freshness.get("state") or "unknown").strip().lower()
        else:
            freshness_state = str(artifact.get("freshness_state") or "current").strip().lower()
        if freshness_state not in _ADAPTATION_FRESH_ARTIFACT_STATES:
            reason = f"freshness_{freshness_state or 'unknown'}"
        elif not actual_id or not actual_hash or actual_revision is None:
            reason = "identity_missing"
        else:
            return {
                "status": "pass",
                "reason_code": "adaptation_artifact_current",
                "diagnostics": [],
                "identity": {
                    "attempt_id": actual_id,
                    "revision_number": actual_revision,
                    "source_hash": actual_hash,
                    "source_path": actual_path,
                },
            }

    return {
        "status": "blocked",
        "reason_code": f"adaptation_{safe_label}_stale",
        "diagnostics": [f"stale_current_artifact:{safe_label}:{reason}"],
        "identity": {
            "attempt_id": actual_id,
            "revision_number": actual_revision,
            "source_hash": actual_hash,
            "source_path": actual_path,
        },
    }


def _result_mapping(job: Mapping[str, Any]) -> Mapping[str, Any]:
    result = _mapping(job.get("result"))
    return result or {}


def _known_maps(job: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return only bounded, known report containers for signal extraction."""
    result = _result_mapping(job)
    maps: List[Mapping[str, Any]] = [job, result]
    for parent in (job, result):
        for key in (
            "adaptation",
            "adaptation_report",
            "failure_classification",
            "revision_report",
            "revision_result",
            "publication_report",
            "publication",
            "adaptation_gates",
            "adaptation_convergence",
            "rollback",
        ):
            candidate = _mapping(parent.get(key))
            if candidate is not None:
                maps.append(candidate)

        stages = _mapping(parent.get("stages"))
        if stages is not None:
            for stage_name in (
                "adaptation_authoring",
                "adaptation_revision",
                "adaptation_gates",
                "module_summary",
                "markdown",
                "registry",
                "campaign_sync",
                "publication_rollback",
                "report_agreement",
            ):
                candidate = _mapping(stages.get(stage_name))
                if candidate is not None:
                    maps.append(candidate)
    return maps


def _first_value(maps: Sequence[Mapping[str, Any]], *keys: str) -> Any:
    for item in maps:
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return value
    return None


def _is_adaptation_mode(value: Any) -> bool:
    return str(value or "").strip().lower() == ADAPTATION_MODE_LLM


def is_adaptation_job(job: Any) -> bool:
    """Return True only when the job explicitly selects adaptation mode."""
    if not isinstance(job, Mapping):
        return False
    if _is_adaptation_mode(job.get("adaptation_mode")):
        return True
    if str(job.get("build_mode") or "").strip().lower() == ADAPTATION_MODE_LLM:
        return True
    if job.get("adaptation_job") is True:
        return True
    result = _result_mapping(job)
    return _is_adaptation_mode(result.get("adaptation_mode")) or _is_adaptation_mode(
        result.get("build_mode")
    )


def _normalize_phase(value: Any, message: Any = None) -> str:
    """Map a Python stage or progress message to an adaptation phase."""
    raw = _safe_stage(value)
    text = f"{raw} {_ascii_text(message, 240).lower()}".strip()

    exact = {
        phase: phase for phase in ADAPTATION_CANONICAL_PHASES
    }
    aliases = {
        "upload": ADAPTATION_PHASE_PREFLIGHT,
        "preflight": ADAPTATION_PHASE_PREFLIGHT,
        "normalizing": ADAPTATION_PHASE_SOURCE_CONTEXT,
        "normalization": ADAPTATION_PHASE_SOURCE_CONTEXT,
        "context": ADAPTATION_PHASE_SOURCE_CONTEXT,
        "source_context": ADAPTATION_PHASE_SOURCE_CONTEXT,
        "authoring": ADAPTATION_PHASE_AUTHORING,
        "dossier": ADAPTATION_PHASE_AUTHORING,
        "builder_input": ADAPTATION_PHASE_AUTHORING,
        "staging": ADAPTATION_PHASE_STAGING,
        "build": ADAPTATION_PHASE_BUILD,
        "building": ADAPTATION_PHASE_BUILD,
        "validation": ADAPTATION_PHASE_VALIDATION,
        "readiness": ADAPTATION_PHASE_READINESS,
        "semantic": ADAPTATION_PHASE_SEMANTIC_AUDIT,
        "semantic_audit": ADAPTATION_PHASE_SEMANTIC_AUDIT,
        "revision": ADAPTATION_PHASE_REVISION,
        "revision_build": ADAPTATION_PHASE_REVISION_BUILD,
        "report": ADAPTATION_PHASE_REPORT,
        "report_agreement": ADAPTATION_PHASE_REPORT,
        "markdown": ADAPTATION_PHASE_MARKDOWN,
        "module_summary": ADAPTATION_PHASE_MARKDOWN,
        "registry": ADAPTATION_PHASE_REGISTRY,
        "campaign": ADAPTATION_PHASE_CAMPAIGN_SYNC,
        "campaign_sync": ADAPTATION_PHASE_CAMPAIGN_SYNC,
        "rollback": ADAPTATION_PHASE_ROLLBACK,
    }
    if raw in exact:
        return exact[raw]
    if raw in aliases:
        return aliases[raw]

    if "rollback" in text or "rolling back" in text or "cleanup" in text:
        return ADAPTATION_PHASE_ROLLBACK
    if "campaign" in text and ("sync" in text or "availab" in text):
        return ADAPTATION_PHASE_CAMPAIGN_SYNC
    if "registry" in text or "register" in text:
        return ADAPTATION_PHASE_REGISTRY
    if "markdown" in text or "module summary" in text or "module_summary" in text:
        return ADAPTATION_PHASE_MARKDOWN
    if "report agreement" in text or "publication report" in text:
        return ADAPTATION_PHASE_REPORT
    if (
        ("revision" in text or "revised" in text)
        and ("build" in text or "rebuild" in text)
    ):
        return ADAPTATION_PHASE_REVISION_BUILD
    if "revision" in text or "revised dossier" in text:
        return ADAPTATION_PHASE_REVISION
    if "semantic" in text or "content gate" in text:
        return ADAPTATION_PHASE_SEMANTIC_AUDIT
    if "readiness" in text or "continuity" in text:
        return ADAPTATION_PHASE_READINESS
    if "schema" in text or "mechanical" in text or "validat" in text:
        return ADAPTATION_PHASE_VALIDATION
    if "staging" in text or "isolated target" in text:
        return ADAPTATION_PHASE_STAGING
    if "author" in text or "dossier" in text:
        return ADAPTATION_PHASE_AUTHORING
    if "source context" in text or "world context" in text:
        return ADAPTATION_PHASE_SOURCE_CONTEXT
    if "preflight" in text or "rights" in text:
        return ADAPTATION_PHASE_PREFLIGHT
    if raw in {"queued", "running", "approved_for_build"} or not raw:
        return ADAPTATION_PHASE_PREFLIGHT
    return ADAPTATION_PHASE_BUILD


def normalize_adaptation_progress_stage(
    progress_status: Any, progress_message: Any
) -> str:
    """Normalize builder callback signals to adaptation-specific phases."""
    return _normalize_phase(progress_status, progress_message)


def _failure_signal(job: Mapping[str, Any]) -> Dict[str, Any]:
    maps = _known_maps(job)
    result = _result_mapping(job)
    classification: Mapping[str, Any] = {}
    for item in maps:
        candidate = _mapping(item.get("failure_classification"))
        if candidate is not None:
            classification = candidate
            break

    result_status = str(result.get("status") or "").strip().lower()
    result_has_explicit_failure = result_status in {
        "blocked", "failed", "error", "not_publishable",
    } and (
        any(result.get(key) not in (None, "") for key in (
            "failure_code", "failure_class", "failed_stage", "failure_diagnostics",
        ))
        or (
            result.get("error") not in (None, "")
            and not isinstance(result.get("failure_classification"), Mapping)
        )
    )
    # A terminal result is the last Python-owned projection boundary. Prefer
    # its concrete error/stage over a nested successful convergence reason.
    signal_maps: Sequence[Mapping[str, Any]] = (
        [result, job, *maps]
        if result_has_explicit_failure
        else [classification, *maps]
    )

    raw_class = _first_value(
        signal_maps, "failure_class", "class", "error_class"
    )
    failure_class = _safe_code(raw_class, "unknown")
    raw_group = _first_value(
        signal_maps, "failure_group", "group", "classification_group"
    )
    failure_group = _safe_code(raw_group, "unknown")
    failure_kind = _safe_code(
        _first_value(signal_maps, "failure_kind"), ""
    )
    raw_code = _first_value(
        signal_maps,
        "code",
        "error_code",
        "diagnostic_code",
        "failure_code",
        "error",
        "reason_code",
        "artifact_freshness_reason",
        "reason",
    )
    code = _safe_code(raw_code, failure_class)
    raw_job_status = str(
        _first_value([job, _result_mapping(job)], "status", "job_status") or ""
    ).strip().lower()
    # A malformed or early-gate result may not have a classification yet.  Do
    # not surface the unhelpful ``unclassified`` placeholder on terminal
    # adaptation jobs; retain a stable, actionable bounded code instead.
    if code == "unclassified" or (not raw_code and failure_class == "unknown"):
        code = {
            "failed": "adaptation_failed",
            "error": "adaptation_failed",
            "blocked": "adaptation_blocked",
            "not_publishable": "adaptation_blocked",
        }.get(raw_job_status, "adaptation_status_unclassified")
    raw_stage = _first_value(
        signal_maps, "failed_stage", "failure_stage", "stage", "phase"
    )
    stage = _safe_stage(raw_stage)
    raw_domain = _first_value(
        signal_maps, "failure_domain", "domain", "failure_area"
    )
    domain = _safe_stage(raw_domain)
    eligible = _safe_bool(
        _first_value(
            signal_maps,
            "semantic_revision_eligible",
            "revision_eligible",
            "allow_semantic_revision",
        )
    )
    next_revision_eligible = _safe_bool(
        _first_value(signal_maps, "next_revision_eligible")
    )
    if next_revision_eligible is True:
        # Convergence is the authoritative post-gate opt-in marker.  An
        # intermediate classification may conservatively report false before
        # convergence has decided whether a fresh revision is allowed.
        eligible = True
    consumes_budget = _safe_bool(
        _first_value(
            signal_maps, "consumes_semantic_revision_budget"
        )
    )
    budget_consumed = _safe_bool(
        _first_value(signal_maps, "semantic_revision_budget_consumed")
    )
    if budget_consumed is None:
        budget_consumed = consumes_budget
    budget = _mapping(_first_value(signal_maps, "revision_budget")) or {}
    current_revision = _safe_int(
        _first_value([budget, classification, *maps], "current_revision", "revision_number"),
        0,
    )
    max_revisions = _safe_int(
        _first_value([budget, classification, *maps], "max_revisions"), 1, 2
    )
    decision = _safe_code(
        _first_value([budget, classification, *maps], "decision"), "not_applicable"
    )
    terminal = _safe_bool(
        _first_value(signal_maps, "terminal", "is_terminal")
    )
    remaining = _safe_int(
        _first_value(
            [budget, classification, *maps],
            "remaining_before_failure",
            "remaining_revisions",
        ),
        max(0, max_revisions - current_revision),
        2,
    )
    raw_diagnostics = _first_value(
        signal_maps, "diagnostics", "failure_diagnostics"
    )
    diagnostics = []
    if isinstance(raw_diagnostics, Sequence) and not isinstance(raw_diagnostics, (str, bytes)):
        for item in list(raw_diagnostics)[:_MAX_DIAGNOSTICS]:
            if isinstance(item, Mapping):
                safe = project_persisted_diagnostic(
                    {
                        **dict(item),
                        "phase": raw_stage,
                        "status": "blocked",
                        "code": item.get("code"),
                        "message": item.get("message") or item.get("reason"),
                    }
                )
                diagnostics.append(
                    {
                        "code": safe["code"],
                        "message": safe.get("message", ""),
                    }
                )
            else:
                safe = project_persisted_diagnostic(
                    {"phase": raw_stage, "status": "blocked", "code": "unclassified", "message": item}
                )
                diagnostics.append({"code": "unclassified", "message": safe.get("message", "")})

    # Some terminal continuation failures are emitted before the builder has
    # attached a failure classification.  Use only the Python-owned,
    # namespaced publication errors here; arbitrary provider/error text must
    # not be promoted to a publication failure.  In particular, a nested
    # convergence callback_success is not an outcome or failure signal.
    publication_continuation = _mapping(
        result.get("adaptation_publication_continuation")
    ) or {}
    terminal_error = _safe_code(result.get("error"), "")
    result_stage = _safe_stage(result.get("failed_stage") or result.get("stage"))
    is_terminal_result = result_status in {"blocked", "failed", "error", "not_publishable"}
    is_publication_stage = result_stage.startswith(
        _ADAPTATION_PUBLICATION_TERMINAL_ERROR_PREFIX
    ) or bool(publication_continuation)
    if (
        is_terminal_result
        and is_publication_stage
        and terminal_error.startswith(_ADAPTATION_PUBLICATION_TERMINAL_ERROR_PREFIX)
    ):
        stage = _safe_stage(
            result.get("failed_stage")
            or result.get("stage")
            or _ADAPTATION_PUBLICATION_CONTINUATION_STAGE
        ) or _ADAPTATION_PUBLICATION_CONTINUATION_STAGE
        fallback_diagnostics = [
            {
                "code": terminal_error,
                "message": _ascii_text(result.get("error")),
            }
        ]
        blockers = publication_continuation.get("blockers")
        if isinstance(blockers, Sequence) and not isinstance(blockers, (str, bytes)):
            for blocker in list(blockers)[: _MAX_DIAGNOSTICS - 1]:
                blocker_code = _safe_code(blocker, "publication_blocker")
                fallback_diagnostics.append(
                    {"code": blocker_code, "message": _ascii_text(blocker)}
                )
        failure_class = "publication"
        failure_group = "publication"
        failure_kind = "publication"
        code = terminal_error
        domain = "publication"
        eligible = False
        next_revision_eligible = False
        consumes_budget = False
        budget_consumed = False
        terminal = True
        diagnostics = fallback_diagnostics
    return {
        "failure_class": failure_class,
        "failure_group": failure_group,
        "failure_kind": failure_kind,
        "code": code,
        "stage": stage,
        "domain": domain,
        "revision_eligible": eligible is True,
        "semantic_revision_eligible": eligible is True,
        "next_revision_eligible": next_revision_eligible is True,
        "consumes_budget": budget_consumed is True,
        "current_revision": current_revision,
        "max_revisions": max_revisions,
        "remaining_revisions": remaining,
        "budget_decision": decision,
        "terminal": terminal is True,
        "classification_present": bool(classification),
        "diagnostics": diagnostics,
    }


def _publication_details(job: Mapping[str, Any]) -> Dict[str, Any]:
    maps = _known_maps(job)
    result = _result_mapping(job)
    stages = _mapping(result.get("stages")) or _mapping(job.get("stages")) or {}
    registry = _mapping(stages.get("registry")) or _mapping(result.get("registry")) or {}
    campaign = _mapping(stages.get("campaign_sync")) or _mapping(result.get("campaign_sync")) or {}
    publication_status = _safe_code(
        _first_value([result, job, *maps], "publication_status", "adaptation_publication_status"),
        "unknown",
    )
    terminal_status = _safe_code(
        _first_value([result, job, *maps], "terminal_status"), "incomplete"
    )
    registry_status = _safe_code(registry.get("status"), "not_attempted")
    campaign_status = _safe_code(campaign.get("status"), "not_attempted")
    python_authoritative = _safe_bool(
        _first_value([result, job, *maps], "python_authoritative")
    )
    override = _safe_bool(
        _first_value([result, job, *maps], "llm_publication_override")
    )
    registry_verified = _safe_bool(
        _first_value(
            [registry, result, job, *maps],
            "verified",
            "registry_verified",
            "post_write_verified",
        )
    )
    completed = (
        publication_status in {"completed", "published", "success"}
        and terminal_status == "completed"
        and registry_status in {"success", "published", "completed"}
        and campaign_status in {"success", "deferred", "published", "completed"}
        and python_authoritative is True
        and override is not True
    )
    return {
        "publication_status": publication_status,
        "terminal_status": terminal_status,
        "registry_status": registry_status,
        "campaign_sync_status": campaign_status,
        "registry_verified": registry_verified is True,
        "python_authoritative": python_authoritative is True,
        "llm_publication_override": override is True,
        "verified": completed,
    }


def _is_publication_failure(job: Mapping[str, Any], signal: Mapping[str, Any]) -> bool:
    phase_text = " ".join(
        _safe_stage(value)
        for value in (
            signal.get("stage"),
            job.get("stage"),
            job.get("adaptation_stage"),
            job.get("pipeline_status"),
        )
    )
    return bool(
        signal.get("failure_class") in _PUBLICATION_FAILURE_CLASSES
        or signal.get("failure_group") == "publication"
        or signal.get("failure_class") in _POLICY_FAILURE_CLASSES
        or any(
            token in phase_text
            for token in ("registry", "campaign", "rollback", "markdown", "report_agreement")
        )
    )


def _controlled_status_text(
    outcome: str,
    phase: str,
    failure_surface: str,
    retry: Mapping[str, Any],
) -> str:
    if outcome == ADAPTATION_OUTCOME_COMPLETED:
        return "Adaptation completed after Python-owned publication and verification."
    if outcome == ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE:
        return (
            "Adaptation stopped because a provider or runtime dependency failed. "
            "No semantic revision budget was consumed."
        )
    if outcome == ADAPTATION_OUTCOME_REVISION_EXHAUSTED:
        return (
            "Semantic revision budget exhausted. Publication is blocked and no "
            "registry completion is reported."
        )
    if outcome == ADAPTATION_OUTCOME_SEMANTIC_REVISION:
        if retry.get("status") == "available":
            return (
                "A semantic adaptation issue is revision-eligible. A bounded fresh "
                "revision is available; no publication is complete."
            )
        return "Semantic adaptation revision is being evaluated in a fresh staging target."
    if outcome == ADAPTATION_OUTCOME_BLOCKED:
        if failure_surface == "publication":
            return (
                "Adaptation publication is blocked by a Python-owned registry, "
                "campaign, rollback, Markdown, or report gate."
            )
        if failure_surface == "completion_verification":
            return "Adaptation completion could not be verified; publication remains blocked."
        if failure_surface == "policy":
            return "Adaptation is blocked pending the required rights or policy review."
        if failure_surface == "readiness":
            return (
                "Adaptation is blocked by the Python-owned readiness gate; "
                "no publication is reported."
            )
        return "Adaptation is blocked by a Python-owned validation or safety gate."

    phase_text = {
        ADAPTATION_PHASE_PREFLIGHT: "Checking adaptation inputs and rights metadata.",
        ADAPTATION_PHASE_SOURCE_CONTEXT: "Preparing bounded source and world context.",
        ADAPTATION_PHASE_AUTHORING: "Authoring the adaptation dossier.",
        ADAPTATION_PHASE_STAGING: "Reserving an isolated adaptation build target.",
        ADAPTATION_PHASE_BUILD: "Building the adapted module from the dossier.",
        ADAPTATION_PHASE_VALIDATION: "Running Python-owned structural and mechanical checks.",
        ADAPTATION_PHASE_READINESS: "Checking readiness, continuity, and semantic authority.",
        ADAPTATION_PHASE_SEMANTIC_AUDIT: "Reviewing adaptation semantics and gate findings.",
        ADAPTATION_PHASE_REVISION: "Preparing a bounded semantic revision.",
        ADAPTATION_PHASE_REVISION_BUILD: "Rebuilding the revised adaptation in fresh staging.",
        ADAPTATION_PHASE_REPORT: "Checking adaptation report agreement.",
        ADAPTATION_PHASE_MARKDOWN: "Generating and checking the readable adaptation summary.",
        ADAPTATION_PHASE_REGISTRY: "Verifying publication before registry integration.",
        ADAPTATION_PHASE_CAMPAIGN_SYNC: "Verifying campaign availability after publication.",
        ADAPTATION_PHASE_ROLLBACK: "Restoring publication state after a failed transaction.",
    }
    return phase_text.get(phase, "Adaptation build is in progress.")


def _job_status_for_outcome(outcome: str, signal: Mapping[str, Any]) -> str:
    if outcome == ADAPTATION_OUTCOME_COMPLETED:
        return ADAPTATION_JOB_STATUS_COMPLETED
    if outcome == ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE:
        return ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED
    if outcome == ADAPTATION_OUTCOME_REVISION_EXHAUSTED:
        return ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED
    if outcome == ADAPTATION_OUTCOME_SEMANTIC_REVISION:
        return ADAPTATION_JOB_STATUS_REVISION_REQUIRED
    if outcome == ADAPTATION_OUTCOME_BLOCKED:
        return ADAPTATION_JOB_STATUS_BLOCKED
    return _safe_stage(signal.get("job_status")) or "running"


def _build_retry_diagnostics(
    outcome: str,
    signal: Mapping[str, Any],
    failure_surface: str,
) -> Dict[str, Any]:
    if outcome == ADAPTATION_OUTCOME_SEMANTIC_REVISION:
        retry_status = (
            "exhausted"
            if signal.get("remaining_revisions", 0) <= 0
            else "available"
        )
        decision = "semantic_revision" if retry_status == "available" else "blocked"
    elif outcome == ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE:
        retry_status = "not_consumed"
        decision = "infrastructure_retry"
    elif outcome == ADAPTATION_OUTCOME_REVISION_EXHAUSTED:
        retry_status = "exhausted"
        decision = "blocked"
    elif outcome == ADAPTATION_OUTCOME_COMPLETED:
        retry_status = "not_applicable"
        decision = "completed"
    elif outcome == ADAPTATION_OUTCOME_BLOCKED:
        retry_status = "not_retryable"
        decision = "blocked"
    else:
        retry_status = "pending"
        decision = "continue"

    failure_class = str(signal.get("failure_class") or "unknown")
    retryable = retry_status == "available"
    next_revision_eligible = bool(signal.get("next_revision_eligible")) and retryable
    revision_eligible = bool(signal.get("revision_eligible")) and retryable
    semantic_revision_eligible = bool(signal.get("semantic_revision_eligible")) and retryable
    return {
        "status": retry_status,
        "decision": decision,
        "failure_class": failure_class,
        "failure_group": str(signal.get("failure_group") or "unknown"),
        "failure_surface": failure_surface,
        "code": str(signal.get("code") or "unclassified"),
        "revision_number": signal.get("current_revision", 0),
        "max_revisions": signal.get("max_revisions", 1),
        "remaining_revisions": signal.get("remaining_revisions", 0),
        "retryable": retryable,
        "next_revision_eligible": next_revision_eligible,
        "revision_eligible": revision_eligible,
        "semantic_revision_eligible": semantic_revision_eligible,
        "failed_stage": str(signal.get("stage") or ""),
        "failure_domain": str(signal.get("domain") or ""),
        "diagnostics": list(signal.get("diagnostics") or [])[:_MAX_DIAGNOSTICS],
        "semantic_revision_budget_consumed": bool(signal.get("consumes_budget")),
        "diagnostics_bounded": True,
    }


def build_adaptation_job_status(job: Any) -> Dict[str, Any]:
    """Build a bounded adaptation status envelope for API and GUI consumers."""
    if not isinstance(job, Mapping):
        return {
            "contract_version": ADAPTATION_JOB_REPORT_CONTRACT_VERSION,
            "is_adaptation": False,
            "adaptation_mode": None,
        }

    adaptation = is_adaptation_job(job)
    if not adaptation:
        return {
            "contract_version": ADAPTATION_JOB_REPORT_CONTRACT_VERSION,
            "is_adaptation": False,
            "adaptation_mode": None,
        }

    maps = _known_maps(job)
    result = _result_mapping(job)
    raw_status = str(job.get("status") or result.get("status") or "running").strip().lower()
    raw_stage = _first_value(
        [job, result, *maps],
        "adaptation_phase",
        "adaptation_stage",
        "adaptation_progress_stage",
        "progress_stage",
        "stage",
    )
    raw_message = _first_value([job, result, *maps], "adaptation_progress_message", "progress_message")
    phase = _normalize_phase(raw_stage, raw_message)
    signal = _failure_signal(job)
    signal["job_status"] = raw_status
    if not signal.get("stage"):
        signal["stage"] = phase
    identity = _adaptation_identity(job)
    result_identity = _adaptation_identity(result)
    for key, value in result_identity.items():
        if identity.get(key) in (None, "") and value not in (None, ""):
            identity[key] = value
    attempt_id = _safe_code(identity.get("attempt_id"), "")
    attempt_number = _safe_int(identity.get("attempt_number"), 0, 2_000_000_000)
    revision_number = _safe_int(identity.get("revision_number"), signal.get("current_revision", 0), 100)
    publication = _publication_details(job)
    failure_surface = "none"

    explicit_statuses = {
        ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED,
        ADAPTATION_JOB_STATUS_REVISION_REQUIRED,
        ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED,
        ADAPTATION_JOB_STATUS_BLOCKED,
        ADAPTATION_JOB_STATUS_COMPLETED,
    }
    is_failure_status = raw_status in {
        "failed",
        "blocked",
        "not_publishable",
        "finishing_failed",
        "final_reconciliation_required",
        "adaptation_infrastructure_failed",
        "adaptation_revision_required",
        "adaptation_revision_exhausted",
        "adaptation_blocked",
    }
    terminal_noneligible = bool(
        signal.get("terminal")
        and not signal.get("revision_eligible")
        and signal.get("budget_decision") == "explicit_opt_in_required"
    )
    infrastructure_failure = bool(
        signal.get("failure_class") in _INFRASTRUCTURE_FAILURE_CLASSES
        or signal.get("failure_group") == "infrastructure"
        or raw_status == ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED
    )
    policy_failure = signal.get("failure_class") in _POLICY_FAILURE_CLASSES
    hard_content_failure = str(signal.get("failure_kind") or "").lower() in {
        "hard",
        "infrastructure",
        "policy",
        "publication",
    }
    publication_failure = _is_publication_failure(job, signal)
    non_revision_failure = bool(
        infrastructure_failure
        or policy_failure
        or publication_failure
        or hard_content_failure
    )
    semantic_failure = bool(
        not terminal_noneligible
        and not non_revision_failure
        and (
            (
                signal.get("failure_class") in _SEMANTIC_FAILURE_CLASSES
                and (
                    signal.get("revision_eligible")
                    or signal.get("consumes_budget")
                )
            )
            or raw_status in {
                ADAPTATION_JOB_STATUS_REVISION_REQUIRED,
                ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED,
            }
            or (
                signal.get("budget_decision") == "exhausted"
                and signal.get("failure_class") in _SEMANTIC_FAILURE_CLASSES
            )
        )
    )
    revision_exhausted = bool(
        not terminal_noneligible
        and (
            raw_status == ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED
            or signal.get("budget_decision") == "exhausted"
            or (
                semantic_failure
                and signal.get("max_revisions", 1) >= 0
                and signal.get("current_revision", 0) >= signal.get("max_revisions", 1)
                and is_failure_status
            )
        )
    )

    if publication.get("verified"):
        outcome = ADAPTATION_OUTCOME_COMPLETED
        phase = ADAPTATION_PHASE_COMPLETED
    elif raw_status in {ADAPTATION_JOB_STATUS_COMPLETED, "completed", "published"}:
        outcome = ADAPTATION_OUTCOME_BLOCKED
        failure_surface = "completion_verification"
        phase = ADAPTATION_PHASE_BLOCKED
    elif terminal_noneligible:
        outcome = ADAPTATION_OUTCOME_BLOCKED
        failure_surface = "validation"
        phase = ADAPTATION_PHASE_BLOCKED
    elif infrastructure_failure:
        outcome = ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE
        failure_surface = "infrastructure"
        phase = ADAPTATION_PHASE_INFRASTRUCTURE_FAILED
    elif semantic_failure and revision_exhausted:
        outcome = ADAPTATION_OUTCOME_REVISION_EXHAUSTED
        failure_surface = "semantic_revision"
        phase = ADAPTATION_PHASE_REVISION_EXHAUSTED
    elif semantic_failure and (is_failure_status or phase in {ADAPTATION_PHASE_REVISION, ADAPTATION_PHASE_REVISION_BUILD}):
        outcome = ADAPTATION_OUTCOME_SEMANTIC_REVISION
        failure_surface = "semantic_revision"
        if is_failure_status:
            phase = ADAPTATION_PHASE_REVISION
    elif (
        policy_failure
        or publication_failure
        or raw_status in {"blocked", "not_publishable", "finishing_failed", "final_reconciliation_required"}
        or raw_status in _READINESS_BLOCKED_STATUSES
    ):
        outcome = ADAPTATION_OUTCOME_BLOCKED
        if raw_status in _READINESS_BLOCKED_STATUSES:
            # Readiness is an explicit pre-publication gate; its failure
            # statuses are bounded non-success outcomes for adaptation jobs.
            failure_surface = "readiness"
        elif policy_failure:
            failure_surface = "policy"
        elif publication_failure:
            failure_surface = "publication"
        else:
            failure_surface = "validation"
        phase = ADAPTATION_PHASE_BLOCKED
    elif raw_status in explicit_statuses and raw_status != ADAPTATION_JOB_STATUS_COMPLETED:
        outcome = ADAPTATION_OUTCOME_BLOCKED
        failure_surface = "validation"
        phase = ADAPTATION_PHASE_BLOCKED
    elif raw_status in {"failed", "error"}:
        outcome = ADAPTATION_OUTCOME_BLOCKED
        failure_surface = "validation" if hard_content_failure else "unknown"
        phase = ADAPTATION_PHASE_BLOCKED
    else:
        outcome = ADAPTATION_OUTCOME_IN_PROGRESS

    retry = _build_retry_diagnostics(outcome, signal, failure_surface)
    terminal = outcome in {
        ADAPTATION_OUTCOME_COMPLETED,
        ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE,
        ADAPTATION_OUTCOME_REVISION_EXHAUSTED,
        ADAPTATION_OUTCOME_BLOCKED,
        ADAPTATION_OUTCOME_SEMANTIC_REVISION,
    }
    job_status = _job_status_for_outcome(outcome, signal)
    status_text = _controlled_status_text(outcome, phase, failure_surface, retry)

    history = _first_value([job, result, *maps], "history", "revision_history")
    history_count = len(history) if isinstance(history, list) else 0
    return {
        "contract_version": ADAPTATION_JOB_REPORT_CONTRACT_VERSION,
        "is_adaptation": True,
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "phase": phase,
        "stage": phase,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "revision_number": revision_number,
        "outcome": outcome,
        "job_status": job_status,
        "terminal": terminal,
        "status_text": status_text,
        "failure_surface": failure_surface,
        "failure_class": signal.get("failure_class", "unknown"),
        "failure_code": signal.get("code", "unclassified"),
        "failed_stage": str(signal.get("stage") or ""),
        "next_revision_eligible": bool(signal.get("next_revision_eligible"))
        and outcome == ADAPTATION_OUTCOME_SEMANTIC_REVISION
        and retry.get("status") == "available",
        "revision_eligible": bool(signal.get("revision_eligible")) and outcome == ADAPTATION_OUTCOME_SEMANTIC_REVISION and retry.get("status") == "available",
        "semantic_revision_eligible": bool(signal.get("semantic_revision_eligible")) and outcome == ADAPTATION_OUTCOME_SEMANTIC_REVISION and retry.get("status") == "available",
        "revision_budget": {
            "current_revision": signal.get("current_revision", 0),
            "max_revisions": signal.get("max_revisions", 1),
            "remaining_revisions": signal.get("remaining_revisions", 0),
        },
        "failure_diagnostics": list(signal.get("diagnostics") or [])[:_MAX_DIAGNOSTICS],
        "retry_diagnostics": retry,
        "revision_history_count": min(history_count, _MAX_HISTORY_ITEMS),
        "publication": publication,
        "python_authoritative": publication.get("python_authoritative", False),
        "raw_provider_payload_exposed": False,
    }


def _safe_public_scalar(key: str, value: Any) -> Any:
    if key in {"size_bytes", "progress_tick", "revision_number", "attempt_number"}:
        return _safe_int(value, 0, 2_000_000_000)
    if key in {"rebuild_mode", "adaptation_job"}:
        return bool(value)
    return _ascii_text(value, 240)


_PUBLIC_JOB_KEYS = (
    "job_id",
    "job_type",
    "status",
    "stage",
    "pipeline_status",
    "created_at",
    "updated_at",
    "source_kind",
    "source_filename",
    "source_rights_class",
    "size_bytes",
    "build_started_at",
    "module_name",
    "expected_module_name",
    "review_decision",
    "rebuild_mode",
    "progress_tick",
    "attempt_id",
    "attempt_number",
    "revision_number",
)


def sanitize_adaptation_job_for_public(job: Any) -> Dict[str, Any]:
    """Return an allowlisted API job payload for adaptation polling."""
    if not isinstance(job, Mapping):
        return {}
    summary = build_adaptation_job_status(job)
    if not summary.get("is_adaptation"):
        return dict(job)

    public_job: Dict[str, Any] = {
        key: _safe_public_scalar(key, job.get(key))
        for key in _PUBLIC_JOB_KEYS
        if job.get(key) not in (None, "")
    }
    public_job.update(
        {
            "adaptation_mode": ADAPTATION_MODE_LLM,
            "adaptation_phase": summary["phase"],
            "adaptation_outcome": summary["outcome"],
            "adaptation_terminal": summary["terminal"],
            "adaptation_status_text": summary["status_text"],
            "adaptation_failure_surface": summary["failure_surface"],
            "adaptation_failure_class": summary["failure_class"],
            "adaptation_failure_code": summary["failure_code"],
            "attempt_id": summary["attempt_id"],
            "attempt_number": summary["attempt_number"],
            "revision_number": summary["revision_number"],
            "adaptation_retry_diagnostics": summary["retry_diagnostics"],
            "adaptation_publication": summary["publication"],
            "adaptation_status_contract": summary["contract_version"],
            "raw_provider_payload_exposed": False,
            "result": {
                "adaptation_mode": ADAPTATION_MODE_LLM,
                "phase": summary["phase"],
                "outcome": summary["outcome"],
                "status_text": summary["status_text"],
                "failure_surface": summary["failure_surface"],
                "failure_class": summary["failure_class"],
                "failure_code": summary["failure_code"],
                "attempt_id": summary["attempt_id"],
                "attempt_number": summary["attempt_number"],
                "revision_number": summary["revision_number"],
                "retry_diagnostics": summary["retry_diagnostics"],
                "publication": summary["publication"],
                "raw_provider_payload_exposed": False,
            },
        }
    )
    return public_job


def adaptation_public_response_fields(job: Any) -> Dict[str, Any]:
    """Return bounded adaptation fields to add beside a public job payload."""
    summary = build_adaptation_job_status(job)
    if not summary.get("is_adaptation"):
        return {}
    return {
        "adaptation_job": summary,
        "adaptation_phase": summary["phase"],
        "adaptation_outcome": summary["outcome"],
    }


__all__ = [
    "ADAPTATION_JOB_REPORT_CONTRACT_VERSION",
    "ADAPTATION_MODE_LLM",
    "ADAPTATION_OUTCOME_IN_PROGRESS",
    "ADAPTATION_OUTCOME_SEMANTIC_REVISION",
    "ADAPTATION_OUTCOME_REVISION_EXHAUSTED",
    "ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE",
    "ADAPTATION_OUTCOME_BLOCKED",
    "ADAPTATION_OUTCOME_COMPLETED",
    "ADAPTATION_JOB_STATUS_REVISION_REQUIRED",
    "ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED",
    "ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED",
    "ADAPTATION_JOB_STATUS_BLOCKED",
    "ADAPTATION_JOB_STATUS_COMPLETED",
    "ADAPTATION_TERMINAL_JOB_STATES",
    "ADAPTATION_CANONICAL_PHASES",
    "normalize_adaptation_progress_stage",
    "is_adaptation_job",
    "validate_adaptation_artifact_current",
    "build_adaptation_job_status",
    "sanitize_adaptation_job_for_public",
    "adaptation_public_response_fields",
]
