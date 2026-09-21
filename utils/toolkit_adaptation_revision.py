# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""
NeverEndingQuest Utility - Toolkit Adaptation Final Revision
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-facing revision orchestration for the LLM adaptation lane. The
orchestrator accepts only a Python-validated failure packet, asks an injected
semantic auditor for a bounded revision, validates the resulting dossier and
logical rebuild directive, and invokes an injected build callback with a new
isolated staging target. It never publishes, registers, or mutates campaign
state.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_BUILD_RESULT,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_REVISION_REPORT,
    ARTIFACT_STAGE_BUILD,
    ARTIFACT_STAGE_REVISED,
    ADAPTATION_MODE_LLM,
    build_adaptation_artifact,
    get_adaptation_artifact_path,
    persist_adaptation_artifact,
)
from utils.toolkit_adaptation_auditor import (
    AUDITOR_DECISION_FAILED,
    AUDITOR_DECISION_REFUSE,
    AUDITOR_DECISION_REVISE,
    parse_adaptation_auditor_response,
    run_llm_adaptation_auditor,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_READY,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_failure_classifier import (
    DEFAULT_MAX_SEMANTIC_REVISIONS,
    FAILURE_CLASS_FILE,
    FAILURE_CLASS_MECHANICAL,
    FAILURE_CLASS_SEMANTIC,
    REVISION_BUDGET_DECISION_ELIGIBLE,
    REVISION_BUDGET_DECISION_EXHAUSTED,
    classify_adaptation_failure,
    is_infrastructure_failure,
)
from utils.toolkit_adaptation_failure_packet import (
    build_adaptation_failure_packet,
    validate_adaptation_failure_packet,
)
from utils.toolkit_adaptation_rebuild_directive import (
    ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION,
    REBUILD_DIRECTIVE_ACTION_FRESH_BUILD,
    REBUILD_DIRECTIVE_BASIS_REVISED_DOSSIER,
    REBUILD_DIRECTIVE_TARGET_STAGING,
    validate_adaptation_rebuild_directive,
)
from utils.toolkit_adaptation_staging import (
    DEFAULT_ADAPTATION_STAGING_ROOT,
    STAGING_STATE_COMPLETED,
    STAGING_STATE_FAILED,
    AdaptationStagingTargetExistsError,
    create_adaptation_staging_target,
    get_adaptation_staging_target_path,
    update_adaptation_staging_target,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_adaptation_proposals import (
    build_adaptation_proposal_ledger,
    get_adaptation_proposal_path,
    persist_adaptation_proposal_ledger,
)
from utils.toolkit_adaptation_output_safety import (
    AdaptationOutputSafety,
    is_adaptation_output_active,
    project_safe_event,
)


ADAPTATION_REVISION_CONTRACT_VERSION = "toolkit_adaptation_revision.v1"
DEFAULT_MAX_FINAL_REVISIONS = DEFAULT_MAX_SEMANTIC_REVISIONS
MAX_FINAL_REVISIONS = 2

REVISION_STATUS_NO_REVISION = "no_revision"
REVISION_STATUS_INFRASTRUCTURE_FAILED = "infrastructure_failed"
REVISION_STATUS_BLOCKED = "blocked"
REVISION_STATUS_FAILED = "failed"
REVISION_STATUS_REVISION_PASSED = "revision_passed"

REVISION_OUTCOME_NO_REVISION = REVISION_STATUS_NO_REVISION
REVISION_OUTCOME_INFRASTRUCTURE_FAILED = REVISION_STATUS_INFRASTRUCTURE_FAILED
REVISION_OUTCOME_BLOCKED = REVISION_STATUS_BLOCKED
REVISION_OUTCOME_FAILED = REVISION_STATUS_FAILED
REVISION_OUTCOME_PASSED = REVISION_STATUS_REVISION_PASSED

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_MODULE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_SECRET_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|password|secret|credential|token)"
    r"\s*[:=]\s*[^\s,;]+|\b(?:sk|rk|pk|key)[_-][a-z0-9][a-z0-9._-]{7,}"
)
_WHITESPACE_RE = re.compile(r"\s+")


def _utc_now_iso() -> str:
    """Return a second-precision UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _ascii_text(value: Any, limit: int = 320) -> str:
    """Return bounded, redacted ASCII text for diagnostics and reports."""
    if value is None:
        return ""
    text = _SECRET_RE.sub("[REDACTED_CREDENTIAL]", str(value))
    text = _WHITESPACE_RE.sub(" ", text.replace("\x00", " ")).strip()
    text = text.encode("ascii", "replace").decode("ascii")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _safe_provider_reason(value: Any, default: str) -> str:
    """Return a stable diagnostic, never provider response or exception text."""
    if not isinstance(value, str):
        return default
    # Reasons are provider-controlled and may contain an entire response,
    # prompt, request body, credential, or an absolute path.  Keep only a
    # short allowlisted code when one is supplied; prose is not an artifact.
    candidate = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}", candidate):
        return default
    return candidate


def _diagnostic(code: str, message: str, path: str = "") -> Dict[str, str]:
    if is_adaptation_output_active():
        event = project_safe_event(
            phase="adaptation_revision",
            status="failed",
            code=code,
            message=message,
        )
        safe_path = str(path or "")
        if safe_path.startswith(("/", "\\")) or ":\\" in safe_path:
            safe_path = ""
        return {
            "code": event["code"],
            "message": event.get("message", ""),
            "path": safe_path,
        }
    return {
        "code": _ascii_text(code, 120),
        "message": _ascii_text(message, 320),
        "path": _ascii_text(path, 200),
    }


def _safe_hash(value: Any) -> str:
    return value if isinstance(value, str) and _SHA256_RE.fullmatch(value) else ""


def _safe_non_negative_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if 0 <= value <= 100 else default


def _configured_revision_limit() -> Any:
    """Read model configuration lazily so legacy imports remain unaffected."""
    try:
        from model_config import LLM_ADAPTATION_MAX_REVISIONS

        return LLM_ADAPTATION_MAX_REVISIONS
    except Exception:
        return DEFAULT_MAX_FINAL_REVISIONS


def normalize_adaptation_revision_limit(value: Any = None) -> int:
    """Normalize the semantic revision limit to the hard range 0..2."""
    configured = _configured_revision_limit() if value is None else value
    if isinstance(configured, bool) or not isinstance(configured, int):
        return DEFAULT_MAX_FINAL_REVISIONS
    if configured < 0:
        return 0
    return min(configured, MAX_FINAL_REVISIONS)


resolve_adaptation_revision_limit = normalize_adaptation_revision_limit
get_adaptation_revision_limit = normalize_adaptation_revision_limit


def describe_adaptation_revision_limit(value: Any = None) -> Dict[str, Any]:
    """Return the bounded configuration decision for diagnostics and tests."""
    configured = _configured_revision_limit() if value is None else value
    normalized = normalize_adaptation_revision_limit(configured)
    valid_type = isinstance(configured, int) and not isinstance(configured, bool)
    return {
        "configured": configured,
        "max_revisions": normalized,
        "hard_maximum": MAX_FINAL_REVISIONS,
        "default": DEFAULT_MAX_FINAL_REVISIONS,
        "clamped": bool(valid_type and configured != normalized),
        "invalid": not valid_type,
    }


def _module_slug(value: Any) -> str:
    text = _ascii_text(value, 120)
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_-")
    if not text:
        return "Adapted_Module"
    text = text[:120]
    return text if _SAFE_MODULE_SLUG_RE.fullmatch(text) else "Adapted_Module"


def _metadata_model(attempt: Mapping[str, Any], auditor_result: Any) -> Dict[str, Any]:
    base = attempt.get("model_metadata")
    result_metadata = (
        auditor_result.get("model_metadata")
        if isinstance(auditor_result, Mapping)
        else None
    )
    merged: Dict[str, Any] = {}
    for source in (base, result_metadata):
        if not isinstance(source, Mapping):
            continue
        for key in (
            "provider",
            "model",
            "model_version",
            "request_id",
            "parameter_profile",
            "temperature",
            "reasoning_effort",
            "verbosity",
        ):
            value = source.get(key)
            if isinstance(value, (str, int, float, bool)) and not (
                isinstance(value, str) and not value.strip()
            ):
                merged[key] = _ascii_text(value, 200) if isinstance(value, str) else value
    if "model" not in merged:
        merged["model"] = "not_recorded"
    if "provider" not in merged:
        merged["provider"] = "not_recorded"
    return merged


def _artifact_metadata(attempt: Mapping[str, Any]) -> Dict[str, str]:
    values = {
        "job_id": attempt.get("job_id"),
        "source_profile": attempt.get("source_profile"),
        "source_format": attempt.get("source_format"),
        "source_context_status": attempt.get("source_context_status"),
        "parent_attempt_id": attempt.get("attempt_id"),
        "created_by": "toolkit_adaptation_revision",
        "publication_policy": "deferred",
    }
    world = build_world_context_provenance(attempt)
    values.update(
        {
            "world_seed_status": world.get("world_seed_status"),
            "world_seed_version": world.get("world_seed_version"),
            "world_seed_hash": world.get("world_seed_hash"),
            "world_context_status": world.get("context_status"),
            "world_context_version": world.get("context_version"),
            "world_context_hash": world.get("context_hash"),
            "context_hash": world.get("context_hash"),
            "world_context_selected_module": world.get("selected_module"),
        }
    )
    return {
        key: _ascii_text(value, 240)
        for key, value in values.items()
        if value not in (None, "")
    }


def _artifact_provenance_kwargs(
    attempt: Mapping[str, Any],
    *,
    model_metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    source_path = attempt.get("source_path")
    if isinstance(source_path, str) and Path(source_path).is_absolute():
        try:
            source_path = Path(source_path).resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            source_path = ""
    return {
        "attempt_id": str(attempt.get("attempt_id") or ""),
        "source_title": _ascii_text(attempt.get("source_title") or "Adapted source", 400),
        "source_hash": str(attempt.get("source_hash") or ""),
        "source_path": str(source_path or ""),
        "attempt_number": int(attempt.get("attempt_number") or 1),
        "rights_class": str(attempt.get("rights_class") or "user_authored"),
        "rights_basis": _ascii_text(attempt.get("rights_basis") or "operator supplied source", 500),
        "rights_review_required": bool(attempt.get("rights_review_required")),
        "rights_review_status": str(attempt.get("rights_review_status") or "not_required"),
        "source_profile": _ascii_text(attempt.get("source_profile") or "adaptation", 32),
        "source_format": _ascii_text(attempt.get("source_format") or "unknown", 32),
        "model_metadata": dict(model_metadata),
        "metadata": _artifact_metadata(attempt),
        "world_context_provenance": build_world_context_provenance(attempt),
    }


def _reference_for_file(
    path: Path,
    repo_root: Path,
    *,
    role: str,
    kind: str,
) -> Optional[Dict[str, Any]]:
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(repo_root.resolve()).as_posix()
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except Exception:
        return None
    return {
        "path": relative,
        "sha256": digest,
        "kind": _ascii_text(kind, 80),
        "role": _ascii_text(role, 80),
        "reference_only": True,
    }


def _packet_evidence_refs(packet: Mapping[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen = set()
    for collection_name in ("gate_statuses", "gate_findings"):
        collection = packet.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, Mapping) or not isinstance(item.get("evidence_ref"), Mapping):
                continue
            reference = dict(item["evidence_ref"])
            if not reference.get("path") or not reference.get("sha256"):
                continue
            reference["reference_only"] = True
            reference.setdefault("role", "failure_evidence")
            identity = json.dumps(reference, sort_keys=True, separators=(",", ":"))
            if identity not in seen:
                refs.append(reference)
                seen.add(identity)
    return refs[:16]


def _failure_reason(packet: Mapping[str, Any]) -> str:
    classification = packet.get("failure_classification")
    if isinstance(classification, Mapping):
        return _ascii_text(
            classification.get("message")
            or classification.get("code")
            or "Initial adaptation candidate failed a Python gate.",
            800,
        )
    return "Initial adaptation candidate failed a Python gate."


def _history_entry(revision_number: int, status: str, reason: Any) -> Dict[str, Any]:
    return {
        "revision_number": revision_number,
        "status": _ascii_text(status, 32) or "failed",
        "reason": _ascii_text(reason, 800) or "No bounded revision detail was recorded.",
    }


def _initial_history(packet: Mapping[str, Any]) -> List[Dict[str, Any]]:
    current = _safe_non_negative_int(packet.get("revision_number"), 0)
    return [_history_entry(current, "failed", _failure_reason(packet))]


def _result(
    *,
    status: str,
    attempt: Mapping[str, Any],
    budget: Mapping[str, Any],
    revision_number: int,
    diagnostics: Optional[Sequence[Mapping[str, Any]]] = None,
    history: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    world = build_world_context_provenance(attempt)
    return {
        "contract_version": ADAPTATION_REVISION_CONTRACT_VERSION,
        "status": status,
        "outcome": status,
        "ok": status == REVISION_STATUS_REVISION_PASSED,
        "attempt_id": attempt.get("attempt_id"),
        "attempt_number": attempt.get("attempt_number"),
        "source_hash": attempt.get("source_hash"),
        "world_context_provenance": world,
        "world_context_status": world.get("context_status"),
        "world_context_version": world.get("context_version"),
        "world_context_hash": world.get("context_hash"),
        "context_hash": world.get("context_hash"),
        "world_seed_status": world.get("world_seed_status"),
        "world_seed_version": world.get("world_seed_version"),
        "world_seed_hash": world.get("world_seed_hash"),
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "rights_class": attempt.get("rights_class"),
        "rights_review_status": attempt.get("rights_review_status"),
        "revision_number": revision_number,
        "attempted_revision_number": None,
        "max_revisions": budget.get("max_revisions"),
        "revision_budget": deepcopy(dict(budget)),
        "semantic_revision_budget_consumed": False,
        "next_revision_eligible": False,
        "revision_eligible": False,
        "semantic_revision_eligible": False,
        "failure_class": None,
        "failure_code": None,
        "failed_stage": None,
        "failure_domain": None,
        "failure_diagnostics": [],
        "module_builder_started": False,
        "publication_started": False,
        "registry_mutated": False,
        "published": False,
        "staging_target": None,
        "staging_targets": [],
        "revision_report_path": None,
        "revision_report_persisted": False,
        "proposal_ledger_path": None,
        "proposal_ledger_persisted": False,
        "proposal_status": None,
        "proposal_count": 0,
        "proposal_ledger_hash": None,
        "build_result_path": None,
        "build_result_persisted": False,
        "failure_artifact_path": None,
        "failure_artifact_persisted": False,
        "auditor_decision": None,
        "auditor_status": None,
        "diagnostics": [dict(item) for item in list(diagnostics or [])[:32]],
        "history": [dict(item) for item in list(history or [])[:8]],
    }


def _apply_revision_projection(
    result: Dict[str, Any],
    classification: Optional[Mapping[str, Any]],
    budget: Mapping[str, Any],
    *,
    status: Optional[str] = None,
) -> None:
    """Attach one bounded revision decision to every revision result surface."""
    classification = classification if isinstance(classification, Mapping) else {}
    current = int(budget.get("current_revision", result.get("revision_number", 0)) or 0)
    maximum = int(budget.get("max_revisions", 1) or 0)
    remaining = int(
        budget.get("remaining_revisions", max(0, maximum - current)) or 0
    )
    exhausted = maximum > 0 and current >= maximum
    eligible = bool(
        classification.get("revision_eligible") is True
        or classification.get("semantic_revision_eligible") is True
    )
    semantic_eligible = classification.get("semantic_revision_eligible") is True
    consumed = bool(
        result.get("semantic_revision_budget_consumed") is True
        or current > 0
    )
    if exhausted or status == REVISION_STATUS_REVISION_PASSED:
        eligible = semantic_eligible = False
    result["next_revision_eligible"] = bool(eligible and not exhausted)
    result["revision_eligible"] = bool(eligible and not exhausted)
    result["semantic_revision_eligible"] = bool(semantic_eligible and not exhausted)
    result["semantic_revision_budget_consumed"] = consumed
    projection_budget = {
        **dict(budget),
        "current_revision": max(0, current),
        "max_revisions": max(0, min(MAX_FINAL_REVISIONS, maximum)),
        "remaining_revisions": max(0, min(MAX_FINAL_REVISIONS, remaining)),
    }
    if exhausted:
        projection_budget["decision"] = "exhausted"
    result["revision_budget"] = projection_budget
    result["failure_class"] = classification.get("failure_class")
    result["failure_code"] = classification.get("code")
    result["failed_stage"] = classification.get("stage")
    result["failure_domain"] = classification.get("domain")
    result["failure_diagnostics"] = [
        dict(item) for item in list(classification.get("diagnostics") or [])[:6]
        if isinstance(item, Mapping)
    ]


def _call_injected(
    callback: Callable[..., Any],
    values: Mapping[str, Any],
    *,
    positional_order: Sequence[str],
) -> Any:
    """Call a seam without retrying it after an internal TypeError."""
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return callback(**dict(values))

    parameters = list(signature.parameters.values())
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        required_positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            and parameter.default is inspect.Parameter.empty
        ]
        missing_positional = [
            parameter
            for parameter in required_positional
            if parameter.kind == inspect.Parameter.POSITIONAL_ONLY
            or parameter.name not in values
        ]
        if missing_positional:
            positional = [
                values[name]
                for name in positional_order[: len(missing_positional)]
                if name in values
            ]
            if len(positional) != len(missing_positional):
                raise TypeError("injected callback has an unsupported required parameter")
            kwargs = dict(values)
            for parameter in missing_positional:
                kwargs.pop(parameter.name, None)
            return callback(*positional, **kwargs)
        return callback(**dict(values))
    if len(parameters) == 1 and parameters[0].name in {
        "request",
        "build_request",
        "revision_request",
        "builder_input",
    }:
        return callback(dict(values))

    aliases = {
        "target": "staging_target",
        "stage": "staging_target",
        "revised_dossier": "dossier",
        "rebuild_directive": "directive",
    }
    kwargs: Dict[str, Any] = {}
    positional: List[Any] = []
    for parameter in parameters:
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            positional.extend(values[name] for name in positional_order if name in values)
            continue
        name = parameter.name
        value_name = name if name in values else aliases.get(name)
        if value_name in values:
            if parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
                positional.append(values[value_name])
            else:
                kwargs[name] = values[value_name]
            continue
        if parameter.default is inspect.Parameter.empty:
            raise TypeError("injected callback has an unsupported required parameter")
    return callback(*positional, **kwargs)


def _auditor_response_mapping(auditor_result: Mapping[str, Any]) -> Optional[Any]:
    response = auditor_result.get("response")
    if response is not None:
        return response
    if "version" in auditor_result and "gate_evidence_refs" in auditor_result:
        return auditor_result
    return None


def _auditor_decision(auditor_result: Mapping[str, Any], response: Any = None) -> str:
    for value in (
        auditor_result.get("decision"),
        auditor_result.get("outcome"),
        response.get("decision") if isinstance(response, Mapping) else None,
    ):
        if value in {AUDITOR_DECISION_REVISE, AUDITOR_DECISION_REFUSE, AUDITOR_DECISION_FAILED}:
            return str(value)
    return ""


def _auditor_failure_class(auditor_result: Mapping[str, Any]) -> str:
    response = auditor_result.get("response")
    failure = response.get("failure") if isinstance(response, Mapping) else None
    if isinstance(failure, Mapping) and failure.get("class"):
        return str(failure.get("class"))
    for key in ("failure_class", "class", "status", "error_class"):
        if auditor_result.get(key):
            return str(auditor_result.get(key))
    return "provider"


def _auditor_reason(auditor_result: Mapping[str, Any], response: Any = None) -> str:
    # Do not persist provider-supplied prose.  A refusal remains distinct, but
    # the report contains only a bounded code and a Python-owned explanation.
    decision = _auditor_decision(auditor_result, response)
    if decision == AUDITOR_DECISION_REFUSE:
        return "auditor_refused_revision"
    reason_code = auditor_result.get("reason_code")
    return _safe_provider_reason(reason_code, "auditor_did_not_authorize_revision")


def _build_report_artifact(
    kind: str,
    *,
    attempt: Mapping[str, Any],
    revision_number: int,
    payload: Mapping[str, Any],
    model_metadata: Mapping[str, Any],
    stage: str,
    status: str,
) -> Dict[str, Any]:
    kwargs = _artifact_provenance_kwargs(attempt, model_metadata=model_metadata)
    return build_adaptation_artifact(
        kind,
        **kwargs,
        revision_number=revision_number,
        stage=stage,
        status=status,
        payload=payload,
    )


def _persist_artifact(
    workspace: Path,
    artifact: Mapping[str, Any],
    persister: Callable[..., bool],
) -> bool:
    try:
        return bool(
            _call_injected(
                persister,
                {"workspace": workspace, "artifact": artifact},
                positional_order=("workspace", "artifact"),
            )
        )
    except Exception:
        return False


def _mark_target(
    target: Mapping[str, Any],
    state: str,
    repo_root: Path,
    error: str = "",
) -> Tuple[Dict[str, Any], Optional[Dict[str, str]]]:
    try:
        updated = update_adaptation_staging_target(
            target,
            state,
            repo_root=repo_root,
            error=_ascii_text(error, 800) if error else "",
        )
        return updated, None
    except Exception as exc:
        return dict(target), _diagnostic("staging_state_persist_failed", type(exc).__name__)


def _target_exists(
    *,
    source_hash: str,
    attempt_id: str,
    attempt_number: int,
    revision_number: int,
    staging_root: str,
    repo_root: Path,
) -> bool:
    try:
        target = get_adaptation_staging_target_path(
            source_hash=source_hash,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            revision_number=revision_number,
            staging_root=staging_root,
            repo_root=repo_root,
        )
        return target.exists()
    except Exception:
        return True


def _build_status(build_result: Any, gate_result: Any = None) -> str:
    if isinstance(build_result, Mapping):
        value = str(build_result.get("status") or build_result.get("build_status") or "").lower()
        if value in {"failed", "failure", "error", "blocked", "invalid"}:
            return "blocked" if value == "blocked" else "failed"
        status = "passed" if value in {"", "success", "passed", "pass", "completed", "ready"} else "failed"
    else:
        status = "passed"
    if isinstance(gate_result, Mapping):
        gate_status = str(gate_result.get("status") or "").lower()
        if gate_status in {"failed", "blocked", "invalid"}:
            return "blocked" if gate_status == "blocked" else "failed"
        if gate_result.get("candidate_eligible") is False:
            return "blocked"
    return status


def _failure_classification_for_build(
    build_result: Mapping[str, Any],
    *,
    attempt: Mapping[str, Any],
    revision_number: int,
    max_revisions: int,
) -> Dict[str, Any]:
    raw: Any = build_result.get("failure_classification")
    if not isinstance(raw, Mapping):
        raw = build_result.get("failure")
    if not isinstance(raw, Mapping):
        raw = build_result
    gate_result = build_result.get("gate_result")
    if not isinstance(gate_result, Mapping):
        gate_result = build_result.get("gates")
    failure_class = raw.get("failure_class") if isinstance(raw, Mapping) else None
    if not failure_class and isinstance(gate_result, Mapping):
        if gate_result.get("semantic_authority") or gate_result.get("semantic_probes"):
            failure_class = FAILURE_CLASS_SEMANTIC
        elif gate_result.get("mechanical_closure") or gate_result.get("readiness"):
            failure_class = FAILURE_CLASS_MECHANICAL
    if not failure_class:
        failure_class = build_result.get("failure_class") or "unknown"
    failure_input = dict(raw) if isinstance(raw, Mapping) else {}
    failure_input["failure_class"] = failure_class
    # Keep the existing classifier semantics; provider error text is bounded
    # before it can enter any persisted artifact.
    failure_input.setdefault(
        "message",
        "revision build failed before publication",
    )
    explicit_opt_in = build_result.get("revision_eligible")
    if explicit_opt_in is None:
        explicit_opt_in = build_result.get("allow_semantic_revision")
    if explicit_opt_in is None and isinstance(gate_result, Mapping):
        for domain in ("semantic_authority", "semantic_probes", "mechanical_closure"):
            domain_report = gate_result.get(domain)
            if isinstance(domain_report, Mapping) and str(domain_report.get("status", "")).lower() in {"failed", "blocked"}:
                explicit_opt_in = True
                break
    return classify_adaptation_failure(
        failure_input,
        attempt_metadata=attempt,
        revision_number=revision_number,
        stage="build",
        revision_eligible=explicit_opt_in,
        max_revisions=max_revisions,
    )


def _revision_authorized(classification: Mapping[str, Any]) -> bool:
    """Return whether a classified content failure may start another round.

    ``consumes_semantic_revision_budget`` describes an accepted operation and
    is therefore false for the initial eligible failure. Authorization uses
    eligibility plus the classifier's budget decision instead.
    """
    if not isinstance(classification, Mapping):
        return False
    if classification.get("semantic_revision_eligible") is not True:
        return False
    budget = classification.get("revision_budget")
    if not isinstance(budget, Mapping):
        return False
    if budget.get("decision") != REVISION_BUDGET_DECISION_ELIGIBLE:
        return False
    remaining = budget.get("remaining_before_failure")
    if remaining is None:
        remaining = budget.get("remaining_revisions")
    if remaining is None:
        return True
    return isinstance(remaining, int) and not isinstance(remaining, bool) and remaining > 0


def _fallback_gate_results(build_result: Mapping[str, Any], failure_class: str) -> Dict[str, Any]:
    domains = {
        "schema": {"status": "pass"},
        "readiness": {"status": "pass"},
        "mechanical_closure": {"status": "pass"},
        "semantic_authority": {"status": "pass"},
        "semantic_probes": {"status": "pass"},
        "report_agreement": {"status": "pass"},
    }
    domain = "semantic_authority" if failure_class == FAILURE_CLASS_SEMANTIC else "mechanical_closure"
    domains[domain] = {
        "status": "blocked",
        "errors": [_ascii_text(build_result.get("error") or "adaptation build failed", 320)],
    }
    return {"gates": domains}


def _next_failure_packet(
    build_result: Mapping[str, Any],
    *,
    current_packet: Mapping[str, Any],
    target: Mapping[str, Any],
    classification: Mapping[str, Any],
    failure_artifact_ref: Optional[Mapping[str, Any]],
    repo_root: Path,
) -> Optional[Dict[str, Any]]:
    supplied = build_result.get("failure_packet")
    if isinstance(supplied, Mapping):
        validation = validate_adaptation_failure_packet(supplied, repo_root=repo_root)
        if not validation.get("valid"):
            return None
        supplied_attempt = supplied.get("attempt_metadata")
        if not isinstance(supplied_attempt, Mapping) or supplied_attempt.get("attempt_id") != current_packet.get("attempt_id"):
            return None
        return deepcopy(dict(supplied))

    gate_results = build_result.get("gate_results")
    if not isinstance(gate_results, Mapping):
        gate_results = build_result.get("gates")
    if not isinstance(gate_results, Mapping):
        gate_results = build_result.get("gate_result")
    if not isinstance(gate_results, Mapping):
        gate_results = _fallback_gate_results(
            build_result, str(classification.get("failure_class") or "unknown")
        )
    if "gates" not in gate_results:
        gate_results = _fallback_gate_results(build_result, str(classification.get("failure_class") or "unknown")) | {"gates": gate_results}

    current_attempt = current_packet.get("attempt_metadata")
    if not isinstance(current_attempt, Mapping):
        return None
    attempt = deepcopy(dict(current_attempt))
    attempt["revision_number"] = target.get("revision_number")
    attempt["stage"] = "build"
    attempt["stage_id"] = target.get("stage_id")
    refs = list(attempt.get("artifact_refs") or []) if isinstance(attempt.get("artifact_refs"), list) else []
    if failure_artifact_ref is not None:
        refs.append(dict(failure_artifact_ref))
    if refs:
        attempt["artifact_refs"] = refs[:16]
    try:
        packet = build_adaptation_failure_packet(
            gate_results,
            attempt_metadata=attempt,
            staging_target=target,
            module_summaries=build_result.get("module_summaries") or current_packet.get("module_summaries"),
            source_context_refs=current_packet.get("source_context_refs"),
            world_context_provenance=current_packet.get("world_context_provenance"),
            publication_goals=current_packet.get("publication_goals"),
            failure_classification=classification,
            stage="build",
            revision_number=target.get("revision_number"),
            repo_root=repo_root,
        )
    except Exception:
        return None
    validation = validate_adaptation_failure_packet(packet, repo_root=repo_root)
    return deepcopy(packet) if validation.get("valid") else None


def _persist_revision_report(
    workspace: Path,
    *,
    attempt: Mapping[str, Any],
    revision_number: int,
    decision: str,
    reason: str,
    history: Sequence[Mapping[str, Any]],
    model_metadata: Mapping[str, Any],
    failure_refs: Optional[Sequence[Mapping[str, Any]]] = None,
    dossier_ref: Optional[Mapping[str, Any]] = None,
    directive: Optional[Mapping[str, Any]] = None,
    persister: Callable[..., bool],
) -> Tuple[Optional[Path], bool]:
    payload: Dict[str, Any] = {
        "revision_number": revision_number,
        "decision": decision,
        "reason": _safe_provider_reason(reason, "bounded_revision_failure"),
        "failure_artifact_refs": [dict(item) for item in (failure_refs or [])][:16],
        "history": [dict(item) for item in list(history)[:8]],
        "fresh_staging_required": decision == AUDITOR_DECISION_REVISE,
    }
    if dossier_ref is not None:
        payload["revised_dossier_ref"] = dict(dossier_ref)
    if isinstance(directive, Mapping):
        safe_directive = {
            "action": REBUILD_DIRECTIVE_ACTION_FRESH_BUILD,
            "target": REBUILD_DIRECTIVE_TARGET_STAGING,
        }
        payload["rebuild_directive"] = safe_directive
    try:
        artifact = _build_report_artifact(
            ARTIFACT_KIND_REVISION_REPORT,
            attempt=attempt,
            revision_number=revision_number,
            payload=payload,
            model_metadata=model_metadata,
            stage=ARTIFACT_STAGE_REVISED,
            status="revised" if decision == AUDITOR_DECISION_REVISE else "failed",
        )
        persisted = _persist_artifact(workspace, artifact, persister)
        path = get_adaptation_artifact_path(
            workspace,
            str(attempt["attempt_id"]),
            ARTIFACT_KIND_REVISION_REPORT,
            revision_number,
        )
        return path, persisted
    except Exception:
        return None, False


def _persist_dossier_artifact(
    workspace: Path,
    *,
    attempt: Mapping[str, Any],
    dossier: Mapping[str, Any],
    revision_number: int,
    model_metadata: Mapping[str, Any],
    persister: Callable[..., bool],
) -> Tuple[Optional[Path], bool]:
    try:
        dossier_attempt = dict(attempt)
        dossier_attempt["source_title"] = dossier.get("source_title", attempt.get("source_title"))
        artifact = _build_report_artifact(
            ARTIFACT_KIND_ADAPTATION_DOSSIER,
            attempt=dossier_attempt,
            revision_number=revision_number,
            payload=dossier,
            model_metadata=model_metadata,
            stage="revised" if revision_number else "draft",
            status="revised" if revision_number else "draft",
        )
        persisted = _persist_artifact(workspace, artifact, persister)
        path = get_adaptation_artifact_path(
            workspace,
            str(attempt["attempt_id"]),
            ARTIFACT_KIND_ADAPTATION_DOSSIER,
            revision_number,
        )
        return path, persisted
    except Exception:
        return None, False


def _persist_build_artifacts(
    workspace: Path,
    *,
    attempt: Mapping[str, Any],
    target: Mapping[str, Any],
    revision_number: int,
    build_result: Mapping[str, Any],
    build_status: str,
    model_metadata: Mapping[str, Any],
    failure_classification: Optional[Mapping[str, Any]],
    repo_root: Path,
    persister: Callable[..., bool],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "build_result_path": None,
        "build_result_persisted": False,
        "failure_artifact_path": None,
        "failure_artifact_persisted": False,
        "diagnostics": [],
        "raw_provider_payload_exposed": False,
    }
    failure_ref: Optional[Dict[str, Any]] = None
    if build_status != "passed":
        failure_class = str((failure_classification or {}).get("failure_class") or "unknown")
        diagnostic = {
            "code": _ascii_text(build_result.get("error_code") or build_result.get("stage") or "revision_build_failed", 120),
            "message": "Revision build failed before publication.",
            "severity": "error",
        }
        try:
            failure_artifact = _build_report_artifact(
                ARTIFACT_KIND_FAILURE_REPORT,
                attempt=attempt,
                revision_number=revision_number,
                payload={
                    "failure_class": failure_class,
                    "failed_stage": ARTIFACT_STAGE_BUILD,
                    "diagnostics": [diagnostic],
                    "recoverable": bool((failure_classification or {}).get("semantic_revision_eligible")),
                    "summary": "Adaptation revision build failed before publication.",
                    "gate": _ascii_text(build_result.get("stage") or "build", 120),
                },
                model_metadata=model_metadata,
                stage="failed",
                status="failed",
            )
            persisted = _persist_artifact(workspace, failure_artifact, persister)
            failure_path = get_adaptation_artifact_path(
                workspace,
                str(attempt["attempt_id"]),
                ARTIFACT_KIND_FAILURE_REPORT,
                revision_number,
            )
            result["failure_artifact_path"] = failure_path
            result["failure_artifact_persisted"] = persisted
            if persisted:
                failure_ref = _reference_for_file(
                    failure_path,
                    repo_root,
                    role="revision_failure",
                    kind=ARTIFACT_KIND_FAILURE_REPORT,
                )
        except Exception:
            result["diagnostics"].append(
                _diagnostic("failure_artifact_persist_failed", "revision failure artifact could not be persisted")
            )

    gate_summary = build_result.get("gate_summary")
    if not isinstance(gate_summary, Mapping):
        gate_summary = {}
        for key in ("status", "stage", "failure_class", "revision_eligible"):
            if key in build_result and isinstance(build_result.get(key), (str, int, bool)):
                gate_summary[key] = build_result.get(key)
        if failure_classification:
            gate_summary["failure_class"] = failure_classification.get("failure_class")
    bounded_gate_summary = {
        _ascii_text(key, 80): value
        for key, value in list(gate_summary.items())[:16]
        if isinstance(key, str) and isinstance(value, (str, bool, int, float, dict))
    }
    revision_projection = build_result.get("revision_projection")
    if not isinstance(revision_projection, Mapping):
        revision_projection = {
            "next_revision_eligible": bool(build_result.get("next_revision_eligible")),
            "revision_eligible": bool(build_result.get("revision_eligible")),
            "semantic_revision_eligible": bool(build_result.get("semantic_revision_eligible")),
            "revision_budget": dict(build_result.get("revision_budget") or {})
            if isinstance(build_result.get("revision_budget"), Mapping)
            else {},
            "semantic_revision_budget_consumed": bool(
                build_result.get("semantic_revision_budget_consumed")
            ),
            "failure_diagnostics": list(build_result.get("failure_diagnostics") or [])[:6],
        }
    bounded_gate_summary["revision_projection"] = dict(revision_projection)
    artifact_is_exhausted = bool(
        isinstance(failure_classification, Mapping)
        and isinstance(failure_classification.get("revision_budget"), Mapping)
        and failure_classification["revision_budget"].get("decision") == REVISION_BUDGET_DECISION_EXHAUSTED
    ) or (isinstance(revision_projection, Mapping) and revision_projection.get("revision_budget", {}).get("decision") == "exhausted")
    artifact_status = "blocked" if artifact_is_exhausted else ("passed" if build_status == "passed" else ("blocked" if build_status == "blocked" else "failed"))
    output_hash = build_result.get("output_hash")
    if not _safe_hash(output_hash):
        output_hash = None
    module_artifacts: List[Dict[str, Any]] = []
    raw_refs = build_result.get("module_artifacts")
    if isinstance(raw_refs, list):
        for item in raw_refs[:32]:
            if not isinstance(item, Mapping):
                continue
            path = item.get("path")
            digest = item.get("sha256")
            if (
                isinstance(path, str)
                and isinstance(digest, str)
                and _SHA256_RE.fullmatch(digest)
                and not path.startswith("/")
                and ".." not in path.split("/")
            ):
                module_artifacts.append(
                    {
                        "path": path,
                        "sha256": digest,
                        "kind": _ascii_text(item.get("kind") or "module_artifact", 80),
                        "role": _ascii_text(item.get("role") or "module_artifact", 80),
                        "reference_only": True,
                    }
                )
    try:
        build_artifact = _build_report_artifact(
            ARTIFACT_KIND_BUILD_RESULT,
            attempt=attempt,
            revision_number=revision_number,
            payload={
                "build_status": artifact_status,
                "module_slug": target.get("module_slug") or None,
                "staging": {
                    "path": target.get("path"),
                    "isolated": True,
                    "target_kind": "staging",
                },
                "gate_summary": bounded_gate_summary,
                "module_artifacts": module_artifacts,
                **({"output_hash": output_hash} if output_hash else {}),
                **({"failure_artifact_ref": failure_ref} if failure_ref else {}),
            },
            model_metadata=model_metadata,
            stage=ARTIFACT_STAGE_BUILD,
            status=artifact_status,
        )
        persisted = _persist_artifact(workspace, build_artifact, persister)
        build_path = get_adaptation_artifact_path(
            workspace,
            str(attempt["attempt_id"]),
            ARTIFACT_KIND_BUILD_RESULT,
            revision_number,
        )
        result["build_result_path"] = build_path
        result["build_result_persisted"] = persisted
    except Exception:
        result["diagnostics"].append(
            _diagnostic("build_result_persist_failed", "revision build result could not be persisted")
        )
    return result


def _run_adaptation_final_revision(
    failure_packet: Mapping[str, Any],
    *,
    workspace: Path,
    build_callback: Optional[Callable[..., Any]],
    current_dossier: Optional[Mapping[str, Any]] = None,
    max_revisions: Any = None,
    staging_root: str = DEFAULT_ADAPTATION_STAGING_ROOT,
    module_slug: Optional[str] = None,
    repo_root: Optional[Path] = None,
    auditor_runner: Callable[..., Dict[str, Any]] = run_llm_adaptation_auditor,
    auditor_client: Any = None,
    auditor_model: Optional[str] = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: Optional[float] = 120,
    artifact_persister: Optional[Callable[..., bool]] = None,
    proposal_persister: Optional[Callable[..., bool]] = None,
    staging_reserver: Callable[..., Dict[str, Any]] = create_adaptation_staging_target,
    gate_runner: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Run at most two bounded semantic adaptation revisions.

    ``auditor_runner`` and ``build_callback`` are injectable seams. The build
    callback receives only a fresh Python-reserved target plus the validated
    dossier, directive, and strict rebuild plan. A callback result may expose
    ``gate_results`` or a prebuilt ``failure_packet`` for a second bounded
    revision. No callback result is treated as publication and no registry or
    campaign file is touched here.
    """
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    workspace_path = Path(workspace)
    persister = artifact_persister or persist_adaptation_artifact
    proposal_writer = proposal_persister or persist_adaptation_proposal_ledger
    budget_info = describe_adaptation_revision_limit(max_revisions)
    budget = {
        "configured": budget_info["configured"],
        "max_revisions": budget_info["max_revisions"],
        "hard_maximum": MAX_FINAL_REVISIONS,
        "clamped": budget_info["clamped"],
        "default": DEFAULT_MAX_FINAL_REVISIONS,
        "current_revision": 0,
        "remaining_revisions": budget_info["max_revisions"],
    }

    packet_validation = validate_adaptation_failure_packet(failure_packet, repo_root=root)
    if not packet_validation.get("valid"):
        diagnostics = packet_validation.get("diagnostics") or [
            _diagnostic("failure_packet_invalid", "failure packet is invalid")
        ]
        fallback_attempt = failure_packet.get("attempt_metadata", {}) if isinstance(failure_packet, Mapping) else {}
        return _result(
            status=REVISION_STATUS_BLOCKED,
            attempt=fallback_attempt if isinstance(fallback_attempt, Mapping) else {},
            budget=budget,
            revision_number=0,
            diagnostics=diagnostics,
        )

    current_packet: Dict[str, Any] = deepcopy(dict(failure_packet))
    attempt_value = current_packet.get("attempt_metadata")
    if not isinstance(attempt_value, Mapping):
        return _result(
            status=REVISION_STATUS_BLOCKED,
            attempt={},
            budget=budget,
            revision_number=0,
            diagnostics=[_diagnostic("attempt_metadata_missing", "failure packet attempt metadata is required")],
        )
    attempt = deepcopy(dict(attempt_value))
    current_revision = _safe_non_negative_int(attempt.get("revision_number"), 0)
    budget["current_revision"] = current_revision
    budget["remaining_revisions"] = max(0, budget["max_revisions"] - current_revision)
    history = _initial_history(current_packet)
    result = _result(
        status=REVISION_STATUS_NO_REVISION,
        attempt=attempt,
        budget=budget,
        revision_number=current_revision,
        history=history,
    )

    # A zero budget is an intentional no-op, not an exhausted failure.  Keep
    # the packet and attempt metadata available to callers without invoking
    # either injected seam or creating a staging target.  A packet that has
    # already consumed a positive budget is an exhausted attempt and must
    # return the explicit terminal failed status without any side effect.
    if current_revision >= budget["max_revisions"]:
        result["revision_budget"] = deepcopy(budget)
        if budget["max_revisions"] > 0:
            classification_value = current_packet.get("failure_classification")
            if isinstance(classification_value, Mapping):
                result["failure_classification"] = deepcopy(dict(classification_value))
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [
                _diagnostic(
                    "revision_budget_exhausted",
                    "bounded semantic revision budget was already exhausted",
                )
            ]
        return result

    while current_revision < budget["max_revisions"]:
        classification_input = current_packet.get("failure_classification")
        if not isinstance(classification_input, Mapping):
            result["status"] = REVISION_STATUS_BLOCKED
            result["outcome"] = REVISION_STATUS_BLOCKED
            result["diagnostics"] = [_diagnostic("failure_classification_missing", "Python failure classification is required")]
            result["history"] = history[:8]
            return result
        opt_in = classification_input.get("semantic_revision_eligible")
        if opt_in is None:
            opt_in = classification_input.get("revision_eligible")
        if opt_in is None and classification_input.get("classification_status") == "revision_eligible":
            opt_in = True
        classification = classify_adaptation_failure(
            classification_input,
            attempt_metadata=attempt,
            revision_number=current_revision,
            stage="build",
            revision_eligible=opt_in,
            max_revisions=budget["max_revisions"],
        )
        result["failure_classification"] = deepcopy(classification)
        _apply_revision_projection(result, classification, budget)
        if not _revision_authorized(classification):
            result["status"] = REVISION_STATUS_INFRASTRUCTURE_FAILED if is_infrastructure_failure(classification) else REVISION_STATUS_BLOCKED
            result["outcome"] = result["status"]
            result["diagnostics"] = [_diagnostic(
                "revision_not_authorized",
                classification.get("message") or "Failure classification does not authorize semantic revision.",
            )]
            result["history"] = history[:8]
            return result

        next_revision = current_revision + 1
        result["attempted_revision_number"] = next_revision
        if build_callback is None:
            result["status"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["outcome"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["diagnostics"] = [_diagnostic("build_callback_missing", "an injected revision build callback is required")]
            result["history"] = history[:8]
            return result

        attempt_id = str(attempt.get("attempt_id") or "")
        attempt_number = int(attempt.get("attempt_number") or 1)
        source_hash = str(attempt.get("source_hash") or "")
        if _target_exists(
            source_hash=source_hash,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            revision_number=next_revision,
            staging_root=staging_root,
            repo_root=root,
        ):
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [_diagnostic("revision_target_exists", "fresh revision staging target already exists; it was not reused")]
            result["history"] = history[:8]
            return result

        try:
            auditor_result = _call_injected(
                auditor_runner,
                {
                    "failure_packet": current_packet,
                    "client": auditor_client,
                    "model": auditor_model,
                    "parameter_resolver": parameter_resolver,
                    "timeout_seconds": timeout_seconds,
                },
                positional_order=("failure_packet",),
            )
        except Exception as exc:
            result["status"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["outcome"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["auditor_status"] = "provider_failed"
            result["auditor_decision"] = AUDITOR_DECISION_FAILED
            result["diagnostics"] = [_diagnostic("auditor_runner_failed", type(exc).__name__)]
            result["history"] = history[:8]
            return result

        if not isinstance(auditor_result, Mapping):
            result["status"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["outcome"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["auditor_status"] = "invalid_result"
            result["auditor_decision"] = AUDITOR_DECISION_FAILED
            result["diagnostics"] = [_diagnostic("auditor_result_invalid", "auditor runner did not return an object")]
            result["history"] = history[:8]
            return result

        response_candidate = _auditor_response_mapping(auditor_result)
        decision = _auditor_decision(auditor_result, response_candidate)
        result["auditor_status"] = _ascii_text(auditor_result.get("status") or "", 80)
        result["auditor_decision"] = decision or None
        if decision == AUDITOR_DECISION_REFUSE:
            reason = _auditor_reason(auditor_result, response_candidate)
            report_history = history + [_history_entry(next_revision, AUDITOR_DECISION_REFUSE, reason)]
            report_path, persisted = _persist_revision_report(
                workspace_path,
                attempt=attempt,
                revision_number=next_revision,
                decision=AUDITOR_DECISION_REFUSE,
                reason=reason,
                history=report_history,
                model_metadata=_metadata_model(attempt, auditor_result),
                failure_refs=_packet_evidence_refs(current_packet),
                persister=persister,
            )
            result["revision_number"] = next_revision
            result["revision_report_path"] = str(report_path.relative_to(root).as_posix()) if report_path and report_path.is_absolute() and report_path.is_relative_to(root) else (str(report_path) if report_path else None)
            result["revision_report_persisted"] = persisted
            result["diagnostics"] = [_diagnostic("auditor_refused_revision", reason)]
            result["status"] = REVISION_STATUS_BLOCKED
            result["outcome"] = REVISION_STATUS_BLOCKED
            result["history"] = report_history[:8]
            return result
        if decision != AUDITOR_DECISION_REVISE:
            failure_class = _auditor_failure_class(auditor_result)
            auditor_classification = classify_adaptation_failure(
                {"failure_class": failure_class, "message": _auditor_reason(auditor_result, response_candidate)},
                attempt_metadata=attempt,
                revision_number=current_revision,
                stage="semantic_auditor",
                max_revisions=budget["max_revisions"],
            )
            if is_infrastructure_failure(auditor_classification):
                result["status"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
                result["outcome"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
                result["diagnostics"] = [_diagnostic("auditor_infrastructure_failure", auditor_classification.get("failure_class"))]
                result["history"] = history[:8]
                return result
            decision_for_report = decision if decision in {AUDITOR_DECISION_REFUSE, AUDITOR_DECISION_FAILED} else AUDITOR_DECISION_FAILED
            reason = _auditor_reason(auditor_result, response_candidate)
            report_history = history + [_history_entry(next_revision, decision_for_report, reason)]
            report_path, persisted = _persist_revision_report(
                workspace_path,
                attempt=attempt,
                revision_number=next_revision,
                decision=decision_for_report,
                reason=reason,
                history=report_history,
                model_metadata=_metadata_model(attempt, auditor_result),
                failure_refs=_packet_evidence_refs(current_packet),
                persister=persister,
            )
            result["revision_number"] = next_revision
            result["revision_report_path"] = str(report_path.relative_to(root).as_posix()) if report_path and report_path.is_absolute() and report_path.is_relative_to(root) else (str(report_path) if report_path else None)
            result["revision_report_persisted"] = persisted
            result["status"] = REVISION_STATUS_BLOCKED
            result["outcome"] = REVISION_STATUS_BLOCKED
            result["diagnostics"] = [_diagnostic("auditor_revision_not_accepted", reason)]
            result["history"] = report_history[:8]
            return result

        if response_candidate is None:
            result["status"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["outcome"] = REVISION_STATUS_INFRASTRUCTURE_FAILED
            result["diagnostics"] = [_diagnostic("auditor_response_missing", "revise requires the task-5.2 response contract")]
            result["history"] = history[:8]
            return result
        if isinstance(response_candidate, str):
            response_text = response_candidate
        else:
            try:
                response_text = json.dumps(response_candidate, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            except (TypeError, ValueError):
                response_text = ""
        parsed = parse_adaptation_auditor_response(response_text, current_packet)
        if not parsed.get("valid") or parsed.get("decision") != AUDITOR_DECISION_REVISE:
            result["status"] = REVISION_STATUS_BLOCKED
            result["outcome"] = REVISION_STATUS_BLOCKED
            result["diagnostics"] = [dict(item) for item in list(parsed.get("diagnostics") or [])[:32]] or [_diagnostic("auditor_response_invalid", "auditor revise response failed Python validation")]
            result["history"] = history[:8]
            return result

        response = parsed.get("response") if isinstance(parsed.get("response"), Mapping) else {}
        revised_dossier = response.get("revised_dossier")
        directive = response.get("rebuild_directive")
        if revised_dossier is not None and directive is not None:
            result["status"] = REVISION_STATUS_BLOCKED
            result["outcome"] = REVISION_STATUS_BLOCKED
            result["diagnostics"] = [_diagnostic("revision_payload_ambiguous", "auditor revise response contained more than one build payload")]
            result["history"] = history[:8]
            return result

        if revised_dossier is not None:
            build_dossier = revised_dossier
            directive_for_validation: Any = {
                "version": ADAPTATION_REBUILD_DIRECTIVE_CONTRACT_VERSION,
                "action": REBUILD_DIRECTIVE_ACTION_FRESH_BUILD,
                "target": REBUILD_DIRECTIVE_TARGET_STAGING,
                "basis": REBUILD_DIRECTIVE_BASIS_REVISED_DOSSIER,
                "scope": "semantic_adaptation",
                "reason": "Apply the validated revised dossier as a fresh semantic adaptation build.",
                "constraints": ["Preserve bounded semantic adaptation content."],
            }
        else:
            build_dossier = current_dossier
            directive_for_validation = directive
            if build_dossier is None:
                result["status"] = REVISION_STATUS_BLOCKED
                result["outcome"] = REVISION_STATUS_BLOCKED
                result["diagnostics"] = [_diagnostic("base_dossier_missing", "a directive-only revision requires a bounded current dossier")]
                result["history"] = history[:8]
                return result

        parsed_dossier = validate_adaptation_dossier(build_dossier)
        if not parsed_dossier.get("valid") or not parsed_dossier.get("build_ready") or parsed_dossier.get("dossier", {}).get("status") != ADAPTATION_DOSSIER_STATUS_READY:
            result["status"] = REVISION_STATUS_BLOCKED
            result["outcome"] = REVISION_STATUS_BLOCKED
            result["diagnostics"] = [_diagnostic("revision_dossier_invalid", "revision dossier is not build-ready")]
            result["history"] = history[:8]
            return result
        normalized_dossier = parsed_dossier["dossier"]

        attempt_id = str(attempt.get("attempt_id") or "")
        attempt_number = int(attempt.get("attempt_number") or 1)
        source_hash = str(attempt.get("source_hash") or "")
        if isinstance(directive_for_validation, Mapping) and isinstance(directive_for_validation.get("target"), Mapping):
            identity = directive_for_validation["target"]
            if (
                identity.get("attempt_id") != attempt_id
                or identity.get("attempt_number") != attempt_number
                or identity.get("revision_number") != next_revision
                or identity.get("source_hash") != source_hash
            ):
                result["status"] = REVISION_STATUS_BLOCKED
                result["outcome"] = REVISION_STATUS_BLOCKED
                result["diagnostics"] = [_diagnostic("revision_target_identity_mismatch", "auditor target identity is not the next Python-owned revision")]
                result["history"] = history[:8]
                return result

        if _target_exists(
            source_hash=source_hash,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            revision_number=next_revision,
            staging_root=staging_root,
            repo_root=root,
        ):
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [_diagnostic("revision_target_exists", "fresh revision staging target already exists; it was not reused")]
            result["history"] = history[:8]
            return result

        try:
            target = _call_injected(
                staging_reserver,
                {
                    "source_hash": source_hash,
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "revision_number": next_revision,
                    "job_id": attempt.get("job_id", ""),
                    "source_path": attempt.get("source_path", ""),
                    "module_slug": module_slug or _module_slug(normalized_dossier.get("adapted_title")),
                    "staging_root": staging_root,
                    "repo_root": root,
                },
                positional_order=("source_hash",),
            )
            if not isinstance(target, Mapping):
                raise ValueError("staging reserver did not return an object")
            target = dict(target)
        except AdaptationStagingTargetExistsError:
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [_diagnostic("revision_target_exists", "fresh revision staging target already exists; it was not reused")]
            result["history"] = history[:8]
            return result
        except Exception as exc:
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [_diagnostic("staging_reservation_failed", type(exc).__name__)]
            result["history"] = history[:8]
            return result

        result["staging_target"] = deepcopy(target)
        result["staging_targets"].append(deepcopy(target))
        strict_validation = validate_adaptation_rebuild_directive(
            directive_for_validation,
            failure_packet=current_packet,
            staging_target=target,
            revised_dossier=normalized_dossier,
            repo_root=root,
            require_reserved=True,
        )
        if not strict_validation.get("valid") or not isinstance(strict_validation.get("plan"), Mapping) or not isinstance(strict_validation.get("dossier"), Mapping):
            target, _ = _mark_target(target, STAGING_STATE_FAILED, root, "unsafe or invalid revision directive")
            result["staging_target"] = deepcopy(target)
            result["diagnostics"] = [dict(item) for item in list(strict_validation.get("diagnostics") or [])[:32]] or [_diagnostic("revision_directive_invalid", "revision directive failed strict Python validation")]
            result["status"] = REVISION_STATUS_BLOCKED
            result["outcome"] = REVISION_STATUS_BLOCKED
            result["history"] = history[:8]
            return result

        validated_dossier = deepcopy(dict(strict_validation["dossier"]))
        validated_plan = deepcopy(dict(strict_validation["plan"]))
        revision_attempt = deepcopy(dict(attempt))
        revision_attempt.update({
            "revision_number": next_revision,
            "stage": "build",
            "stage_id": target.get("stage_id"),
        })
        revision_model_metadata = _metadata_model(attempt, auditor_result)
        dossier_path, dossier_persisted = _persist_dossier_artifact(
            workspace_path,
            attempt=revision_attempt,
            dossier=validated_dossier,
            revision_number=next_revision,
            model_metadata=revision_model_metadata,
            persister=persister,
        )
        result["dossier_artifact_path"] = str(dossier_path.relative_to(root).as_posix()) if dossier_path and dossier_path.is_absolute() and dossier_path.is_relative_to(root) else (str(dossier_path) if dossier_path else None)
        if not dossier_persisted or dossier_path is None:
            target, _ = _mark_target(target, STAGING_STATE_FAILED, root, "revised dossier persistence failed")
            result["staging_target"] = deepcopy(target)
            result["diagnostics"] = [_diagnostic("revised_dossier_persist_failed", "validated revised dossier could not be persisted")]
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["history"] = history[:8]
            return result

        # TABLETOP MODE: Revised world hooks and continuations remain in a
        # fresh, pending-only proposal ledger; they are never applied here.
        try:
            proposal_ledger = build_adaptation_proposal_ledger(
                validated_dossier,
                attempt_metadata=revision_attempt,
                world_context_provenance=(
                    current_packet.get("world_context_provenance")
                    or build_world_context_provenance(revision_attempt)
                ),
                revision_number=next_revision,
                model_metadata=revision_model_metadata,
            )
            proposal_persisted = bool(
                proposal_writer(workspace_path, proposal_ledger)
            )
            proposal_path = get_adaptation_proposal_path(
                workspace_path,
                str(revision_attempt["attempt_id"]),
                next_revision,
            )
        except Exception:
            proposal_ledger = None
            proposal_persisted = False
            proposal_path = None
        if not proposal_persisted or proposal_ledger is None:
            target, _ = _mark_target(target, STAGING_STATE_FAILED, root, "proposal ledger persistence failed")
            result["staging_target"] = deepcopy(target)
            result["diagnostics"] = [_diagnostic("proposal_ledger_persist_failed", "revised world proposals could not be persisted as a pending ledger")]
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["history"] = history[:8]
            return result
        result["proposal_ledger_path"] = str(proposal_path.relative_to(root).as_posix()) if proposal_path and proposal_path.is_absolute() and proposal_path.is_relative_to(root) else (str(proposal_path) if proposal_path else None)
        result["proposal_ledger_persisted"] = True
        result["proposal_status"] = proposal_ledger.get("status")
        result["proposal_count"] = proposal_ledger.get("proposal_count", 0)
        result["proposal_ledger_hash"] = proposal_ledger.get("ledger_hash")

        dossier_ref = _reference_for_file(dossier_path, root, role="revised_dossier", kind=ARTIFACT_KIND_ADAPTATION_DOSSIER)
        report_history = history + [_history_entry(next_revision, "scheduled", _auditor_reason(auditor_result, response))]
        report_path, report_persisted = _persist_revision_report(
            workspace_path,
            attempt=revision_attempt,
            revision_number=next_revision,
            decision=AUDITOR_DECISION_REVISE,
            reason=_auditor_reason(auditor_result, response),
            history=report_history,
            model_metadata=revision_model_metadata,
            failure_refs=_packet_evidence_refs(current_packet),
            dossier_ref=dossier_ref,
            directive={"target_path": target.get("path")},
            persister=persister,
        )
        result["revision_report_path"] = str(report_path.relative_to(root).as_posix()) if report_path and report_path.is_absolute() and report_path.is_relative_to(root) else (str(report_path) if report_path else None)
        result["revision_report_persisted"] = report_persisted
        if not report_persisted:
            target, _ = _mark_target(target, STAGING_STATE_FAILED, root, "revision report persistence failed")
            result["staging_target"] = deepcopy(target)
            result["diagnostics"] = [_diagnostic("revision_report_persist_failed", "revision metadata could not be persisted")]
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["history"] = report_history[:8]
            return result

        request_values = {
            "dossier": deepcopy(validated_dossier),
            "revised_dossier": deepcopy(validated_dossier),
            "directive": deepcopy(directive_for_validation),
            "rebuild_directive": deepcopy(directive_for_validation),
            "rebuild_plan": deepcopy(validated_plan),
            "staging_target": deepcopy(target),
            "target": deepcopy(target),
            "revision_number": next_revision,
            "attempt_metadata": deepcopy(revision_attempt),
            "world_context_provenance": build_world_context_provenance(revision_attempt),
            "build_mode": ADAPTATION_MODE_LLM,
            "module_slug": target.get("module_slug") or _module_slug(validated_dossier.get("adapted_title")),
        }
        try:
            result["module_builder_started"] = True
            build_output = _call_injected(
                build_callback,
                request_values,
                positional_order=("staging_target", "dossier", "directive", "attempt_metadata"),
            )
            build_output = dict(build_output) if isinstance(build_output, Mapping) else {"status": "success"}
        except Exception as exc:
            build_output = {
                "status": "failed",
                "failure_class": "provider",
                "error_code": "build_callback_exception",
                "error": type(exc).__name__,
            }

        gate_output = None
        if gate_runner is not None and _build_status(build_output) == "passed":
            try:
                gate_output = _call_injected(
                    gate_runner,
                    {
                        "staging_target": deepcopy(target),
                        "module_dir": root / str(target.get("path")),
                        "build_result": deepcopy(build_output),
                        "dossier": deepcopy(validated_dossier),
                        "directive": deepcopy(directive_for_validation),
                        "attempt_metadata": deepcopy(revision_attempt),
                    },
                    positional_order=("staging_target", "build_result"),
                )
            except Exception as exc:
                gate_output = {"status": "failed", "failure_class": FAILURE_CLASS_FILE, "error": type(exc).__name__}
        effective_build_status = _build_status(build_output, gate_output)
        if isinstance(gate_output, Mapping):
            build_output["gate_result"] = dict(gate_output)
        failure_classification = None
        if effective_build_status != "passed":
            failure_classification = _failure_classification_for_build(
                build_output,
                attempt=revision_attempt,
                revision_number=next_revision,
                max_revisions=budget["max_revisions"],
            )
            # The terminal result must carry the failure class that ended the
            # attempt, not the classification of the packet that started it.
            result["failure_classification"] = deepcopy(failure_classification)
        build_budget = {
            "current_revision": next_revision,
            "max_revisions": budget["max_revisions"],
            "remaining_revisions": max(0, budget["max_revisions"] - next_revision),
            "decision": (
                str((failure_classification or {}).get("revision_budget", {}).get("decision") or "")
                if isinstance(failure_classification, Mapping)
                else ""
            ),
        }
        build_exhausted = next_revision >= budget["max_revisions"] and budget["max_revisions"] > 0
        if build_exhausted:
            build_budget["decision"] = "exhausted"
        build_output.update(
            {
                "revision_budget": build_budget,
                "next_revision_eligible": False if build_exhausted else bool(
                    (failure_classification or {}).get("revision_eligible") is True
                ),
                "revision_eligible": False if build_exhausted else bool(
                    (failure_classification or {}).get("revision_eligible") is True
                ),
                "semantic_revision_eligible": False if build_exhausted else bool(
                    (failure_classification or {}).get("semantic_revision_eligible") is True
                ),
                "semantic_revision_budget_consumed": True,
                "failure_class": (failure_classification or {}).get("failure_class"),
                "failure_code": (failure_classification or {}).get("code"),
                "failed_stage": (failure_classification or {}).get("stage"),
                "failure_domain": (failure_classification or {}).get("domain"),
                "failure_diagnostics": list(
                    (failure_classification or {}).get("diagnostics") or []
                )[:6],
                "revision_projection": {
                    "next_revision_eligible": False if build_exhausted else bool(
                        (failure_classification or {}).get("revision_eligible") is True
                    ),
                    "revision_eligible": False if build_exhausted else bool(
                        (failure_classification or {}).get("revision_eligible") is True
                    ),
                    "semantic_revision_eligible": False if build_exhausted else bool(
                        (failure_classification or {}).get("semantic_revision_eligible") is True
                    ),
                    "revision_budget": dict(build_budget),
                    "semantic_revision_budget_consumed": True,
                    "failure_diagnostics": list(
                        (failure_classification or {}).get("diagnostics") or []
                    )[:6],
                },
            }
        )
        persisted_build = _persist_build_artifacts(
            workspace_path,
            attempt=revision_attempt,
            target=target,
            revision_number=next_revision,
            build_result=build_output,
            build_status=effective_build_status,
            model_metadata=revision_model_metadata,
            failure_classification=failure_classification,
            repo_root=root,
            persister=persister,
        )
        result.update(persisted_build)
        if persisted_build["diagnostics"]:
            target, _ = _mark_target(target, STAGING_STATE_FAILED, root, "revision artifact persistence failed")
            result["staging_target"] = deepcopy(target)
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = persisted_build["diagnostics"]
            result["history"] = report_history[:8]
            return result

        target_state = STAGING_STATE_COMPLETED if effective_build_status == "passed" else STAGING_STATE_FAILED
        target, staging_error = _mark_target(
            target,
            target_state,
            root,
            "revision build failed" if target_state == STAGING_STATE_FAILED else "",
        )
        result["staging_target"] = deepcopy(target)
        result["staging_targets"][-1] = deepcopy(target)
        if staging_error is not None:
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [staging_error]
            result["history"] = report_history[:8]
            return result

        result["revision_number"] = next_revision
        result["semantic_revision_budget_consumed"] = True
        budget["current_revision"] = next_revision
        budget["remaining_revisions"] = max(0, budget["max_revisions"] - next_revision)
        result["revision_budget"] = deepcopy(budget)
        _apply_revision_projection(
            result,
            failure_classification,
            budget,
            status=(
                REVISION_STATUS_REVISION_PASSED
                if effective_build_status == "passed"
                else None
            ),
        )
        if effective_build_status == "passed":
            result["status"] = REVISION_STATUS_REVISION_PASSED
            result["outcome"] = REVISION_STATUS_REVISION_PASSED
            result["dossier"] = deepcopy(validated_dossier)
            result["directive"] = deepcopy(directive_for_validation)
            result["rebuild_plan"] = deepcopy(validated_plan)
            result["history"] = (report_history + [_history_entry(next_revision, "passed", "Fresh staged revision passed the injected build gates.")])[:8]
            return result

        result["history"] = (report_history + [_history_entry(next_revision, "failed", "fresh_staged_revision_failed")])[:8]
        # Carry the accumulated revision history into the next bounded
        # iteration and into the terminal exhaustion result.
        history = list(result["history"])
        if failure_classification is None or not _revision_authorized(failure_classification):
            budget_decision = ""
            if isinstance(failure_classification, Mapping):
                revision_budget = failure_classification.get("revision_budget")
                if isinstance(revision_budget, Mapping):
                    budget_decision = str(revision_budget.get("decision") or "")
            if budget_decision == REVISION_BUDGET_DECISION_EXHAUSTED:
                result["status"] = REVISION_STATUS_FAILED
                result["outcome"] = REVISION_STATUS_FAILED
                result["diagnostics"] = [
                    _diagnostic("revision_budget_exhausted", "bounded semantic revision budget was exhausted")
                ]
            else:
                result["status"] = REVISION_STATUS_INFRASTRUCTURE_FAILED if failure_classification and is_infrastructure_failure(failure_classification) else REVISION_STATUS_FAILED
                result["outcome"] = result["status"]
                result["diagnostics"] = [_diagnostic("revision_build_not_retryable", (failure_classification or {}).get("message") or "revision build did not authorize another semantic revision")]
            return result

        failure_ref = None
        if persisted_build.get("failure_artifact_persisted") and isinstance(persisted_build.get("failure_artifact_path"), Path):
            failure_ref = _reference_for_file(
                persisted_build["failure_artifact_path"],
                root,
                role="revision_failure",
                kind=ARTIFACT_KIND_FAILURE_REPORT,
            )
        next_packet = _next_failure_packet(
            build_output,
            current_packet=current_packet,
            target=target,
            classification=failure_classification,
            failure_artifact_ref=failure_ref,
            repo_root=root,
        )
        if next_packet is None:
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [_diagnostic("next_failure_packet_invalid", "a bounded next-revision failure packet could not be built")]
            return result
        current_packet = next_packet
        current_attempt_value = current_packet.get("attempt_metadata")
        if not isinstance(current_attempt_value, Mapping):
            result["status"] = REVISION_STATUS_FAILED
            result["outcome"] = REVISION_STATUS_FAILED
            result["diagnostics"] = [_diagnostic("next_attempt_metadata_invalid", "next revision attempt metadata is invalid")]
            return result
        attempt = deepcopy(dict(current_attempt_value))
        current_revision = next_revision
        result["revision_number"] = current_revision
        current_dossier = deepcopy(validated_dossier)

    result["status"] = REVISION_STATUS_FAILED
    result["outcome"] = REVISION_STATUS_FAILED
    result["diagnostics"] = [_diagnostic("revision_budget_exhausted", "bounded semantic revision budget was exhausted")]
    result["history"] = history[:8]
    return result


def run_adaptation_final_revision(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Run revision/finalization under the explicit adaptation output boundary."""
    with AdaptationOutputSafety(
        phase="adaptation_revision", status="running", redirect_streams=True
    ):
        return _run_adaptation_final_revision(*args, **kwargs)


run_final_adaptation_revision = run_adaptation_final_revision
orchestrate_adaptation_revision = run_adaptation_final_revision
run_adaptation_revision = run_adaptation_final_revision


__all__ = [
    "ADAPTATION_REVISION_CONTRACT_VERSION",
    "DEFAULT_MAX_FINAL_REVISIONS",
    "MAX_FINAL_REVISIONS",
    "REVISION_STATUS_NO_REVISION",
    "REVISION_STATUS_INFRASTRUCTURE_FAILED",
    "REVISION_STATUS_BLOCKED",
    "REVISION_STATUS_FAILED",
    "REVISION_STATUS_REVISION_PASSED",
    "REVISION_OUTCOME_NO_REVISION",
    "REVISION_OUTCOME_INFRASTRUCTURE_FAILED",
    "REVISION_OUTCOME_BLOCKED",
    "REVISION_OUTCOME_FAILED",
    "REVISION_OUTCOME_PASSED",
    "describe_adaptation_revision_limit",
    "get_adaptation_revision_limit",
    "normalize_adaptation_revision_limit",
    "resolve_adaptation_revision_limit",
    "orchestrate_adaptation_revision",
    "run_adaptation_final_revision",
    "run_adaptation_revision",
    "run_final_adaptation_revision",
]
