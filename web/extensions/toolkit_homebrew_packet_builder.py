# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Web Extension - Toolkit Homebrew Packet Builder
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Packet-aware builder facade for approved Homebrew upload workspaces.
"""

import json
import math
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from utils.enhanced_logger import error, info, warning
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    get_workspace_files,
    load_builder_blueprint_artifact,
    load_builder_blueprint_report_artifact,
    load_json_artifact,
    persist_build_result_artifact as persist_legacy_build_result_artifact,
    persist_builder_input_artifact,
    persist_build_fidelity_report_artifact,
    persist_narrative_enrichment_plan_artifact,
    persist_source_fidelity_report_artifact,
    validate_review_packet,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_BUILD_RESULT,
    BUILD_STATUS_BLOCKED,
    BUILD_STATUS_FAILED,
    BUILD_STATUS_PASSED,
    BUILD_STATUS_PENDING,
    FAILURE_CLASS_DEPENDENCY,
    FAILURE_CLASS_FILE,
    FAILURE_CLASS_SEMANTIC,
    FAILURE_CLASS_TIMEOUT,
    build_build_result_artifact,
    get_adaptation_artifact_path,
    persist_build_result_artifact as persist_adaptation_build_result_artifact,
)
from utils.toolkit_adaptation_failure_classifier import (
    classify_adaptation_failure,
    FAILURE_CLASS_MECHANICAL,
    FAILURE_CLASS_SEMANTIC,
)
from utils.toolkit_adaptation_revision import normalize_adaptation_revision_limit
from utils.toolkit_adaptation_output_safety import AdaptationOutputSafety
from utils.toolkit_adaptation_failure_packet import build_adaptation_failure_packet
from utils.toolkit_adaptation_monster_guardrail import (
    build_adaptation_canonical_monster_registry,
)
from utils.toolkit_adaptation_publication_convergence import (
    BUILD_MODE_LLM_ADAPTATION,
    run_adaptation_publication_convergence as _adaptation_finalization_round,
)
from utils.toolkit_adaptation_staging import (
    DEFAULT_ADAPTATION_STAGING_ROOT,
    STAGING_STATE_BUILDING,
    STAGING_STATE_COMPLETED,
    STAGING_STATE_FAILED,
    create_adaptation_staging_target,
    update_adaptation_staging_target,
    validate_adaptation_staging_target,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_adaptation_provenance import (
    adaptation_provenance_surface_fields,
    build_adaptation_provenance,
)
from utils.file_operations import safe_read_json, safe_write_json

try:
    from model_config import ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF
except Exception:
    ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF = True

try:
    from model_config import ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD
except Exception:
    ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD = False

try:
    from model_config import ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK
except Exception:
    ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK = False

# TABLETOP MODE: Adaptation lane rollout gate. Disabled by default; requests
# for the adaptation route resolve to the explicit legacy accurate-ingest
# route until rollout enables ENABLE_LLM_ADAPTATION.
try:
    from model_config import ENABLE_LLM_ADAPTATION
except Exception:
    ENABLE_LLM_ADAPTATION = False

try:
    from model_config import MODULE_GENERATION_API_TIMEOUT_SECONDS
except Exception:
    MODULE_GENERATION_API_TIMEOUT_SECONDS = None

try:
    from utils.toolkit_adaptation_config import (
        canonical_monster_generation_enabled,
        resolve_adaptation_routing,
    )
except Exception:  # pragma: no cover - defensive fallback keeps module importable
    def canonical_monster_generation_enabled(enabled_override=None):
        """Fallback resolver: never enable canonical generation when unavailable."""
        return False

    def resolve_adaptation_routing(requested_mode=None, enabled_override=None):
        """Fallback resolver: never enable adaptation when unavailable."""
        return {
            "status": "legacy",
            "mode": "accurate_ingest_legacy",
            "legacy_mode": "accurate_ingest_legacy",
            "requested_mode": requested_mode if isinstance(requested_mode, str) else None,
            "reason": "not_requested" if not requested_mode else "disabled",
        }

_VALID_SEED_WRITER_MODES = frozenset({"fallback", "preview", "support"})
_SEED_BUILD_MODES = {
    "fallback": "blueprint_seed_fallback",
    "preview": "blueprint_seed_preview",
    "support": "blueprint_seed_support",
}

MAX_LLM_ADAPTATION_HANDOFF_CHARS = 32000
_ADAPTATION_PROVENANCE_TEXT_FIELDS = (
    "attempt_id",
    "source_path",
    "source_format",
    "dossier_artifact_path",
)
_ADAPTATION_MODEL_METADATA_FIELDS = (
    "provider",
    "model",
    "task_id",
    "prompt_contract",
)

_ADAPTATION_FAILURE_STAGES = frozenset(
    {
        "adaptation_monster_guardrail",
        "adaptation_monster_normalization",
        "monster_closure",
    }
)

_MATERIALIZATION_FILE_REASONS = frozenset(
    {
        "file_not_found",
        "missing_path",
        "missing_required_fields",
        "read_error",
        "invalid_json",
        "invalid_payload",
        "staging_root_missing",
        "invalid_staging_root",
        "staging_directory_unavailable",
        "staging_target_symlink",
        "staging_write_failed",
        "area_atomic_write_failed",
        "generation_missing_output",
        "generation_output_symlink",
        "generation_target_outside_staging",
        "generation_invalid_json",
        "generation_incomplete_schema",
    }
)
_MATERIALIZATION_DEPENDENCY_REASONS = frozenset(
    {
        "generation_builder_missing",
        "generation_subprocess_error",
        "generation_nonzero_exit",
    }
)
_MATERIALIZATION_TIMEOUT_REASONS = frozenset({"generation_timeout"})
_SEMANTIC_MONSTER_REASONS = frozenset(
    {
        "ambiguous_canonical_match",
        "no_canonical_match",
        "unresolved_prose",
        "unresolved_monster_reference",
    }
)
_HARD_MONSTER_REASONS = frozenset(
    {
        "invalid_json",
        "invalid_payload",
        "missing_required_fields",
        "staging_write_failed",
        "generation_invalid_json",
        "generation_incomplete_schema",
        "generation_target_outside_staging",
        "generation_output_symlink",
        "staging_target_symlink",
        "generation_timeout",
        "generation_builder_missing",
        "generation_subprocess_error",
        "generation_nonzero_exit",
        "stale_artifact_identity",
        "unsafe_identity_substitution",
        "transaction_failure",
    }
)


def _adaptation_report_reason(report: Any) -> str:
    """Return one allowlisted diagnostic reason without copying report text."""
    if not isinstance(report, Mapping):
        return ""
    for collection_name in (
        "resolution_diagnostics",
        "unresolved_diagnostics",
        "diagnostics",
    ):
        collection = report.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection[:24]:
            if not isinstance(item, Mapping):
                continue
            for key in ("reason", "code"):
                candidate = str(item.get(key) or "").strip()
                if candidate in (
                    _MATERIALIZATION_FILE_REASONS
                    | _MATERIALIZATION_DEPENDENCY_REASONS
                    | _MATERIALIZATION_TIMEOUT_REASONS
                    | _SEMANTIC_MONSTER_REASONS
                    | _HARD_MONSTER_REASONS
                ):
                    return candidate
    return ""


def _adaptation_failure_classification(
    result: Mapping[str, Any],
    *,
    adaptation_handoff: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Classify a terminal adaptation monster failure with bounded signals.

    Only fixed stage/error codes and allowlisted report reasons enter the
    provider-free classifier.  In particular, exception strings and report
    payloads are never used as classification input.
    """
    stage = str(result.get("stage") or "").strip()
    if stage not in _ADAPTATION_FAILURE_STAGES:
        return None
    if str(result.get("status") or "").strip().lower() not in {
        "blocked",
        "failed",
    }:
        return None

    failure_class = FAILURE_CLASS_SEMANTIC
    code = "adaptation_monster_failure"
    domain = stage
    message = "Adaptation monster semantic guardrail failed."
    failure_kind = "content"

    if stage == "adaptation_monster_guardrail":
        reason = _adaptation_report_reason(
            result.get("adaptation_monster_guardrail")
        )
        if reason in _MATERIALIZATION_TIMEOUT_REASONS:
            failure_class = FAILURE_CLASS_TIMEOUT
            code = reason
            domain = "adaptation_monster_materialization"
            message = "Adaptation monster materialization timed out."
            failure_kind = "hard"
        elif reason in _MATERIALIZATION_DEPENDENCY_REASONS:
            failure_class = FAILURE_CLASS_DEPENDENCY
            code = reason
            domain = "adaptation_monster_materialization"
            message = "Adaptation monster materialization dependency failed."
            failure_kind = "hard"
        elif reason in _MATERIALIZATION_FILE_REASONS:
            failure_class = FAILURE_CLASS_FILE
            code = reason
            domain = "adaptation_monster_materialization"
            message = "Adaptation monster artifact materialization failed."
            failure_kind = "hard"
        elif reason in _SEMANTIC_MONSTER_REASONS:
            code = reason
            message = "Adaptation monster reference was not semantically canonical."
        elif reason in _HARD_MONSTER_REASONS:
            failure_class = FAILURE_CLASS_MECHANICAL
            code = reason
            domain = "adaptation_monster_materialization"
            message = "Adaptation monster safety or artifact check failed."
            failure_kind = "hard"
        else:
            code = "adaptation_monster_guardrail_unresolved"
    elif stage == "adaptation_monster_normalization":
        reason = _adaptation_report_reason(
            result.get("adaptation_monster_normalization")
        )
        if reason in _MATERIALIZATION_FILE_REASONS:
            failure_class = FAILURE_CLASS_FILE
            code = reason
            domain = "adaptation_monster_normalization"
            message = "Adaptation monster normalization artifact write failed."
        else:
            code = "adaptation_monster_normalization_blocked"
            message = "Adaptation monster normalization left an unsafe reference."
            failure_kind = "hard"
    else:
        code = "monster_closure_unresolved"
        message = "Adaptation monster closure left an unresolved canonical reference."

    provenance = {}
    if isinstance(adaptation_handoff, Mapping):
        candidate = adaptation_handoff.get("provenance")
        if isinstance(candidate, Mapping):
            provenance = candidate
    revision_eligible = result.get("revision_eligible")
    max_revisions = result.get("max_revisions")
    classification = classify_adaptation_failure(
        {
            "failure_class": failure_class,
            "code": code,
            "message": message,
            "failure_kind": failure_kind,
            "source_grounded": failure_kind == "content",
            "terminal": failure_kind == "hard",
        },
        attempt_metadata=provenance,
        attempt_id=provenance.get("attempt_id"),
        revision_number=provenance.get("revision_number"),
        stage=stage,
        domain=domain,
        revision_eligible=revision_eligible,
        max_revisions=max_revisions,
    )
    # The classifier's canonical names are ``stage`` and ``failure_group``;
    # these aliases make the terminal result explicit for status consumers.
    classification["failed_stage"] = classification.get("stage", stage)
    classification["group"] = classification.get("failure_group", "unknown")
    return classification


def _apply_adaptation_continuation_failure(
    build_result: Dict[str, Any],
    continuation: Mapping[str, Any],
    *,
    error_code: str,
    adaptation_handoff: Optional[Mapping[str, Any]] = None,
) -> None:
    """Project a blocked publication continuation as a terminal failure.

    The continuation is the last Python-owned join before publication.  Its
    refusal must therefore override any successful nested convergence callback
    signal, without reopening semantic revision eligibility.
    """
    blockers = continuation.get("blockers")
    if not isinstance(blockers, (list, tuple)):
        blockers = []
    safe_blockers = [
        _bounded_ascii_provenance_text(item, 240)
        for item in blockers[:12]
        if _bounded_ascii_provenance_text(item, 240)
    ]
    code = _bounded_ascii_provenance_text(error_code, 120) or "adaptation_publication_continuation_failed"
    stage = "adaptation_publication_continuation"
    diagnostics = [{"code": code, "message": code}]
    diagnostics.extend(
        {"code": "publication_continuation_blocker", "message": blocker}
        for blocker in safe_blockers
    )
    classification = classify_adaptation_failure(
        {
            "failure_class": "publication",
            "code": code,
            "message": "Python-owned adaptation publication continuation blocked.",
            "failure_kind": "publication",
        },
        attempt_metadata=(
            adaptation_handoff.get("provenance", {})
            if isinstance(adaptation_handoff, Mapping)
            else {}
        ),
        stage=stage,
        domain="publication",
        revision_eligible=False,
        max_revisions=normalize_adaptation_revision_limit(),
    )
    classification["failed_stage"] = stage
    classification["diagnostics"] = diagnostics[:12]
    build_result.update(
        {
            "failure_classification": classification,
            "failure_class": "publication",
            "failure_group": "publication",
            "failure_kind": "publication",
            "failure_domain": "publication",
            "failure_code": code,
            "failed_stage": stage,
            "revision_eligible": False,
            "semantic_revision_eligible": False,
            "next_revision_eligible": False,
            "semantic_revision_budget_consumed": False,
            "failure_diagnostics": diagnostics[:12],
        }
    )


def _adaptation_monster_revision_context(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract only bounded registry evidence for one monster revision round."""
    def _values(*keys: str) -> list:
        values = []
        for key in keys:
            value = report.get(key)
            if isinstance(value, str):
                value = [value]
            if isinstance(value, (list, tuple)):
                values.extend(item for item in value if isinstance(item, str))
        return list(dict.fromkeys(values))[:32]

    unresolved = _values("unresolved_refs", "unresolved_references")
    registry = report.get("canonical_registry")
    if not isinstance(registry, Mapping):
        registry = report.get("registry") if isinstance(report.get("registry"), Mapping) else {}
    entries = registry.get("entries", []) if isinstance(registry, Mapping) else []
    approved = _values("approved_monster_identities", "approved_canonical_identities", "approved_monster_ids")
    locations = []
    quantities = []
    source_refs = list(_values("source_reference_ids", "source_refs", "approval_provenance"))
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, Mapping):
            continue
        identity = entry.get("canonical_identity") or entry.get("canonical_name")
        if isinstance(identity, str) and identity not in approved:
            approved.append(identity)
        locations.extend(entry.get("affected_location_ids") or []) if isinstance(entry.get("affected_location_ids"), list) else None
        quantities.extend(entry.get("quantity_evidence") or []) if isinstance(entry.get("quantity_evidence"), list) else None
        source_refs.extend(entry.get("approval_provenance") or []) if isinstance(entry.get("approval_provenance"), list) else None
    for diagnostic in report.get("contradiction_diagnostics", []) if isinstance(report.get("contradiction_diagnostics"), list) else []:
        if isinstance(diagnostic, Mapping):
            location = diagnostic.get("source_location") or diagnostic.get("location_id")
            if location:
                source_refs.append(str(location))
    approved = list(dict.fromkeys(item for item in approved if isinstance(item, str)))[:16]
    unresolved = list(dict.fromkeys(unresolved))[:16]
    bounds = {}
    for item in quantities:
        if isinstance(item, Mapping):
            ref = item.get("reference_key") or item.get("monster_ref") or (unresolved[0] if unresolved else "")
            quantity = item.get("quantity")
            if ref and isinstance(quantity, Mapping):
                bounds[str(ref)] = {"min": quantity.get("min", 0), "max": quantity.get("max", quantity.get("min", 0))}
    return {
        "approved_monster_identities": approved[:16],
        "monster_reference_keys": unresolved,
        "source_reference_ids": list(dict.fromkeys(str(item) for item in source_refs if item))[:32],
        "canonical_location_ids": list(dict.fromkeys(str(item) for item in locations if item))[:32],
        "quantity_bounds": bounds,
    }


def _route_adaptation_monster_revision(
    *,
    build_result: Dict[str, Any],
    guardrail_report: Mapping[str, Any],
    classification: Mapping[str, Any],
    adaptation_handoff: Mapping[str, Any],
    staging_target: Mapping[str, Any],
    workspace: Path,
    job_id: str,
    staging_root: str,
    module_slug: str,
    revision_callback: Optional[Callable[[Mapping[str, Any]], Any]],
    rerun_callback: Optional[Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Route one eligible initial monster failure to the bounded revision seam."""
    if revision_callback is None or classification.get("revision_eligible") is not True:
        return None
    budget = classification.get("revision_budget")
    if not isinstance(budget, Mapping) or int(budget.get("remaining_before_failure", 0) or 0) <= 0:
        return None
    provenance = adaptation_handoff.get("provenance") if isinstance(adaptation_handoff, Mapping) else {}
    provenance = provenance if isinstance(provenance, Mapping) else {}
    attempt = dict(provenance)
    attempt.update({"revision_number": staging_target.get("revision_number", 0), "stage": "monster_closure"})
    context = _adaptation_monster_revision_context(guardrail_report)
    monster_packet = {
        "attempt_metadata": attempt,
        "revision_budget": {
            "current_revision": staging_target.get("revision_number", 0),
            "max_revisions": budget.get("max_revisions", 0),
            "remaining_before_failure": budget.get("remaining_before_failure", 0),
        },
        "canonical_registry": guardrail_report.get("canonical_registry") or guardrail_report.get("registry"),
        "guardrail_report": guardrail_report,
        "normalized_reference": (context.get("monster_reference_keys") or ["unknown"])[0],
        "raw_reference": (guardrail_report.get("unresolved_refs") or ["unknown"])[0],
        "approved_canonical_identities": context["approved_monster_identities"],
        "candidate_canonical_identities": context["approved_monster_identities"],
        "affected_locations": context["canonical_location_ids"],
        "quantity_records": guardrail_report.get("quantity_evidence") or [],
        "scene_evidence": guardrail_report.get("contradiction_diagnostics") or [],
        "source_reference_ids": context["source_reference_ids"],
        "failure_code": classification.get("code") or "monster_closure_unresolved",
        "failed_stage": "monster_closure",
    }
    packet = build_adaptation_failure_packet(
        {"gates": {"mechanical_closure": {"status": "blocked", "errors": ["monster closure unresolved"]}}, "failure_classification": classification},
        attempt_metadata=attempt,
        staging_target=staging_target,
        failure_classification=classification,
        stage="monster_closure",
        revision_number=staging_target.get("revision_number", 0),
        repo_root=Path.cwd(),
        monster_content_failure=monster_packet,
    )
    if packet.get("packet_status") == "invalid":
        return None
    next_revision = int(staging_target.get("revision_number", 0) or 0) + 1
    source_hash = str(attempt.get("source_hash") or "")
    target = create_adaptation_staging_target(
        source_hash,
        attempt_id=str(attempt.get("attempt_id") or ""),
        attempt_number=int(attempt.get("attempt_number") or 1),
        revision_number=next_revision,
        job_id=job_id,
        source_path=str(attempt.get("source_path") or ""),
        module_slug=module_slug,
        staging_root=staging_root,
    )
    validation_context = {
        **context,
        "approved_monster_ids": context["approved_monster_identities"],
        "authored_target_ids": (),
        "topology": {"location_ids": context["canonical_location_ids"], "edges": []},
        "status": "blocked",
        "repairable": True,
    }
    def provider_callback(callback_context: Mapping[str, Any]) -> Mapping[str, Any]:
        response = revision_callback({"failure_packet": deepcopy(packet), "convergence_context": deepcopy(dict(callback_context))})
        if isinstance(response, Mapping) and "proposal" in response:
            normalized = dict(response)
        else:
            normalized = {"status": "accepted", "proposal": response}
        normalized.setdefault("attempt_id", callback_context.get("attempt_id"))
        normalized.setdefault("attempt_number", callback_context.get("attempt_number"))
        normalized.setdefault("revision_number", callback_context.get("revision_number"))
        normalized.setdefault("source_hash", callback_context.get("source_hash"))
        normalized.setdefault("staging_identity", callback_context.get("staging_identity"))
        return normalized
    # Adaptation-only helper: this seam is reachable only from the explicit
    # adaptation failure branches below and never from the legacy builder.
    convergence = _adaptation_finalization_round(
        str(Path.cwd() / str(target["path"])), mode=BUILD_MODE_LLM_ADAPTATION,
        attempt_id=str(target["attempt_id"]), attempt_number=int(target["attempt_number"]),
        revision_number=int(target["revision_number"]), source_hash=source_hash,
        provider_callback=provider_callback, validation_context=validation_context,
        repo_root=Path.cwd(),
    )
    accepted_operation = convergence.get("accepted_operation") if isinstance(convergence, Mapping) else None
    if (
        isinstance(convergence, Mapping)
        and convergence.get("status") == "ready"
        and isinstance(accepted_operation, Mapping)
        and accepted_operation.get("operation") == "resolve_monster_reference"
        and rerun_callback is not None
    ):
        rerun = rerun_callback(target, accepted_operation)
        if isinstance(rerun, Mapping):
            rerun_result = deepcopy(dict(rerun))
            rerun_result["adaptation_revision"] = {
                "status": "rerun_completed" if rerun_result.get("status") == "success" else "rerun_failed",
                "pre_revision_status": "adaptation_revision_required",
                "accepted_operation": deepcopy(dict(accepted_operation)),
                "staging_target": deepcopy(target),
                "prior_staging_target": deepcopy(staging_target),
                "normalization_reentered": True,
                "full_pipeline_rerun": True,
            }
            rerun_result.setdefault("semantic_revision_budget_consumed", True)
            rerun_result.setdefault("revision_budget", {
                "current_revision": next_revision,
                "max_revisions": budget.get("max_revisions", 0),
                "remaining_revisions": max(0, int(budget.get("max_revisions", 0) or 0) - next_revision),
                "decision": "exhausted" if next_revision >= int(budget.get("max_revisions", 0) or 0) else "consumed",
            })
            if rerun_result.get("status") == "success":
                return rerun_result
            if rerun_result.get("revision_budget", {}).get("remaining_revisions", 0) <= 0:
                rerun_result["error"] = "adaptation_revision_exhausted"
                rerun_result["revision_eligible"] = False
                rerun_result["next_revision_eligible"] = False
            return rerun_result
    build_result.update({
        "status": "blocked", "stage": "adaptation_revision",
        "error": "adaptation_revision_required",
        "failure_packet": packet,
        "adaptation_revision": convergence,
        "revision_eligible": True,
        "next_revision_eligible": True,
        "semantic_revision_eligible": True,
        "semantic_revision_budget_consumed": False,
        "revision_budget": {"current_revision": staging_target.get("revision_number", 0), "max_revisions": budget.get("max_revisions", 0), "remaining_revisions": budget.get("remaining_before_failure", 0), "decision": "eligible"},
    })
    return build_result


def _project_adaptation_gate_revision(
    gate_result: Mapping[str, Any],
    *,
    convergence_result: Optional[Mapping[str, Any]],
    staging_target: Mapping[str, Any],
    adaptation_handoff: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Carry a bounded content-gate revision decision past gate composition.

    Gate composition is conservative by default.  This boundary is Python
    owned: a semantic/mechanical gate plus remaining configured budget opts the
    existing classifier into its normal revision taxonomy.  Infrastructure,
    policy, publication, and monster guardrail failures are never promoted.
    """
    if not isinstance(gate_result, Mapping):
        return None
    classification = gate_result.get("failure_classification")
    if not isinstance(classification, Mapping):
        return None
    failure_class = str(classification.get("failure_class") or "").strip().lower()
    if failure_class not in {FAILURE_CLASS_SEMANTIC, FAILURE_CLASS_MECHANICAL}:
        return deepcopy(dict(classification))
    gates = gate_result.get("gates")
    domain = ""
    if isinstance(gates, Mapping):
        for candidate_domain, report in gates.items():
            if isinstance(report, Mapping) and str(
                report.get("effective_status") or report.get("status") or ""
            ).lower() != "pass":
                domain = str(candidate_domain)
                break
    code = str(classification.get("code") or "content_gate_failed")
    # Continuity is a Python-owned contract, not source-grounded semantic
    # content.  It must already have been finalized before gate composition;
    # keep any residual continuity failure terminal and out of the LLM route.
    continuity_failure = domain == "readiness" and (
        "continuity" in code.lower()
        or "continuity" in str(classification.get("message") or "").lower()
        or "continuity" in str(classification.get("stage") or "").lower()
    )
    try:
        current_revision = int(staging_target.get("revision_number", 0))
    except (TypeError, ValueError):
        current_revision = 0
    max_revisions = normalize_adaptation_revision_limit()
    provenance: Mapping[str, Any] = {}
    if isinstance(adaptation_handoff, Mapping) and isinstance(
        adaptation_handoff.get("provenance"), Mapping
    ):
        provenance = adaptation_handoff["provenance"]
    if continuity_failure:
        terminal = classify_adaptation_failure(
            {
                "failure_class": FAILURE_CLASS_FILE,
                "code": "adaptation_continuity_contract_blocked",
                "message": "Python-owned continuity contract remains invalid after deterministic finalization",
            },
            attempt_metadata=provenance,
            revision_number=current_revision,
            stage="adaptation_readiness",
            domain="readiness",
            revision_eligible=False,
            max_revisions=max_revisions,
        )
        terminal["next_revision_eligible"] = False
        terminal["semantic_revision_eligible"] = False
        terminal["consumes_semantic_revision_budget"] = False
        terminal["semantic_revision_budget_consumed"] = False
        terminal["diagnostics"] = [{
            "code": "adaptation_continuity_contract_blocked",
            "message": "Python-owned continuity contract remains invalid after deterministic finalization",
        }]
        return terminal
    if current_revision >= max_revisions:
        return deepcopy(dict(classification))
    # A convergence refusal is an explicit Python-owned non-revision decision.
    # Preserve a semantic gate's bounded revision path when the earlier
    # adaptation gate has already blocked.  A failed convergence preparation
    # must not turn that controlled content failure into a non-retryable
    # publication outcome before the continuation join is considered.
    gate_already_blocked = str(
        gate_result.get("playable_status") or ""
    ).strip().lower() != "pass"
    explicit_opt_in = failure_class == FAILURE_CLASS_SEMANTIC and gate_already_blocked
    if not explicit_opt_in:
        explicit_opt_in = not (
            isinstance(convergence_result, Mapping)
            and convergence_result.get("next_revision_eligible") is False
        )
    projected = classify_adaptation_failure(
        {
            "failure_class": failure_class,
            "code": code,
            "message": classification.get("message") or (domain + " gate failed"),
        },
        attempt_metadata=provenance,
        revision_number=current_revision,
        stage="adaptation_gates",
        domain=domain or classification.get("domain"),
        revision_eligible=explicit_opt_in,
        max_revisions=max_revisions,
    )
    projected["failed_stage"] = projected.get("stage") or "adaptation_gates"
    projected["group"] = projected.get("failure_group", "unknown")
    projected["next_revision_eligible"] = bool(
        projected.get("revision_eligible")
    )
    projected["diagnostics"] = [
        {
            "code": str(projected.get("code") or "content_gate_failed")[:120],
            "message": str(projected.get("message") or "content gate failed")[:320],
        }
    ]
    return projected


def _merge_source_string_values(*raw_values: Any) -> list:
    """Merge non-empty strings from one or more sources, deduping order-preserving.

    Each positional arg may be None, a string, or a list of strings.
    Empty/whitespace-only entries are discarded.
    """
    seen: set = set()
    result: list = []
    for raw in raw_values:
        if raw is None:
            continue
        if isinstance(raw, str):
            items = [raw]
        elif isinstance(raw, list):
            items = raw
        else:
            continue
        for item in items:
            val = str(item).strip()
            if val and val not in seen:
                seen.add(val)
                result.append(val)
    return result


def _compact_source_text(value: Any, max_chars: int = 160) -> str:
    """Normalize a source value to compact, ASCII-only, stripped text.

    Returns empty string for blank/whitespace-only values.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.encode("ascii", "replace").decode("ascii")
    return text[:max_chars]


def _build_module_builder_source_context(builder_input: Dict[str, Any]) -> str:
    """Build compact source-enhanced context string for ModuleBuilder.

    Returns empty string when no source-enhanced fields are present.
    """
    lines: list = []
    _append_if_present(lines, "NPCS", builder_input.get("source_npc_names"))
    _append_if_present(lines, "LOCATIONS", builder_input.get("source_location_names"))
    _append_if_present(lines, "PUZZLES", builder_input.get("source_puzzle_ids"))
    _append_if_present(lines, "TONE", builder_input.get("source_tone"))
    _append_if_present(lines, "MONSTERS", builder_input.get("source_monster_refs"))
    _encounter_seeds = builder_input.get("source_encounter_seeds", [])
    if _encounter_seeds:
        seeds = []
        for s in _encounter_seeds[:12]:
            compact = _compact_source_text(s)
            if compact:
                seeds.append(f"- {compact}")
        if seeds:
            lines.append("ENCOUNTER_SEEDS:")
            lines.extend(seeds)
    _blueprint = builder_input.get("blueprint", {})
    _source_lock = _blueprint.get("source_lock", {})
    if _source_lock:
        _locked = [k for k, v in _source_lock.items() if v is True]
        if _locked:
            lines.append(f"SOURCE_LOCKS: {', '.join(_locked)}")
    if not lines:
        return ""
    return "=== SOURCE LOCK CONTEXT ===\n" + "\n".join(lines)


def _append_if_present(dest: list, label: str, values: Any) -> None:
    """Append a compact label: value line if values contain any non-blank entries."""
    if not isinstance(values, list) or not values:
        return
    items = []
    for v in values[:12]:
        compact = _compact_source_text(v)
        if compact:
            items.append(compact)
    if items:
        dest.append(f"{label}: {', '.join(items)}")


def _bounded_ascii_provenance_text(value: Any, limit: int = 240) -> str:
    """Return bounded ASCII provenance text without trusting arbitrary input."""
    text = str(value or "").strip()
    if not text:
        return ""
    return text.encode("ascii", "replace").decode("ascii")[:limit]


def _safe_provenance_path(value: Any) -> str:
    """Keep only project-relative-looking provenance references."""
    text = _bounded_ascii_provenance_text(value, 512)
    if not text or text.startswith("/") or "\\" in text or "\x00" in text:
        return ""
    if any(part in {"", ".", ".."} for part in text.split("/")):
        return ""
    return text


def _apply_adaptation_fidelity_boundary(
    *,
    workspace: Path,
    fidelity_report: Mapping[str, Any],
    classification: Mapping[str, Any],
    adaptation_provenance: Optional[Mapping[str, Any]],
    staging_target: Optional[Mapping[str, Any]],
    module_slug: str,
    source_graph: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Apply the non-literal adaptation fidelity boundary.

    Literal build-fidelity evidence remains authoritative diagnostics, but it
    is not a publication gate for an adaptation.  This helper only permits
    the explicit editorial-only classification and a current canonical
    adaptation provenance envelope.  Structural, schema, topology, closure,
    readiness, and semantic failures remain outside this boundary.
    """
    result: Dict[str, Any] = {
        "eligible": False,
        "reason": "adaptation_literal_fidelity_not_eligible",
    }
    if not isinstance(adaptation_provenance, Mapping):
        result["reason"] = "adaptation_provenance_missing"
        return result
    try:
        from utils.toolkit_adaptation_provenance import validate_adaptation_provenance
        provenance_validation = validate_adaptation_provenance(
            adaptation_provenance,
            require_source_identity=True,
        )
    except Exception:
        provenance_validation = {"valid": False, "diagnostics": ["provenance_validation_failed"]}
    if not provenance_validation.get("valid"):
        result["reason"] = "adaptation_provenance_invalid"
        result["provenance_diagnostics"] = list(provenance_validation.get("diagnostics") or [])[:8]
        return result
    if str(classification.get("status") or "") != "editorial":
        result["reason"] = "adaptation_fidelity_classification_not_editorial_only"
        return result
    if int(classification.get("fatal_count", 0) or 0) != 0:
        result["reason"] = "adaptation_fidelity_fatal_blocker_present"
        return result
    if classification.get("warnings"):
        result["reason"] = "adaptation_fidelity_unknown_blocker_present"
        return result

    from utils.toolkit_adaptation_source_fidelity import (
        build_adaptation_source_fidelity_report,
    )

    evidence = {
        "source_fidelity_status": "blocked",
        "status": "blocked",
        "coverage": fidelity_report.get("coverage") or {},
    }
    report = build_adaptation_source_fidelity_report(
        source_fidelity_evidence=evidence,
        literal_mismatch_evidence=list(fidelity_report.get("blockers") or [])
        + list(fidelity_report.get("warnings") or []),
        attempt_metadata=adaptation_provenance,
        staging_target=staging_target,
        module_slug=module_slug,
        stage="adaptation_build_fidelity_boundary",
    )
    if report.get("report_agreement", {}).get("blocking"):
        result["reason"] = "adaptation_source_fidelity_evidence_invalid"
        result["report"] = report
        return result
    try:
        persist_source_fidelity_report_artifact(workspace, report)
    except Exception:
        result["reason"] = "adaptation_source_fidelity_report_persist_failed"
        return result
    result.update(
        {
            "eligible": True,
            "reason": "adaptation_literal_fidelity_informational",
            "report": report,
            "literal_blocker_count": len(fidelity_report.get("blockers") or []),
            "literal_warning_count": len(fidelity_report.get("warnings") or []),
        }
    )
    return result


def build_llm_adaptation_handoff(
    dossier: Any,
    provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and bound the dossier before the ModuleBuilder handoff.

    The returned envelope is the only adaptation payload accepted by the
    builder. Source candidates are intentionally not copied into legacy
    ``source_*`` fields or converted into source-lock context.
    """
    raw_dossier: Any = dossier
    if provenance is not None and not isinstance(provenance, Mapping):
        raise ValueError("llm_adaptation_provenance_invalid")
    supplied_provenance: Mapping[str, Any] = provenance or {}
    if isinstance(dossier, Mapping) and "dossier" in dossier:
        raw_dossier = dossier.get("dossier")
        envelope_provenance = dossier.get("provenance")
        if isinstance(envelope_provenance, Mapping):
            supplied_provenance = envelope_provenance
        elif envelope_provenance is not None:
            raise ValueError("llm_adaptation_provenance_invalid")

    validation = validate_adaptation_dossier(raw_dossier)
    if (
        not validation.get("valid")
        or not validation.get("build_ready")
        or not isinstance(validation.get("dossier"), Mapping)
    ):
        diagnostics = validation.get("diagnostics") or []
        first = diagnostics[0] if diagnostics and isinstance(diagnostics[0], Mapping) else {}
        code = str(first.get("code") or "not_build_ready")
        raise ValueError(f"llm_adaptation_dossier_invalid:{code}")

    normalized = deepcopy(dict(validation["dossier"]))
    nested_attempt_metadata = supplied_provenance.get("attempt_metadata")
    if not isinstance(nested_attempt_metadata, Mapping):
        nested_attempt_metadata = {}
    nested_model_metadata = supplied_provenance.get("model_metadata")
    if not isinstance(nested_model_metadata, Mapping):
        nested_model_metadata = {}

    safe_provenance: Dict[str, Any] = {
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "source_title": normalized["source_title"],
        "source_hash": normalized["source_hash"],
        "source_profile": normalized["source_profile"],
        "rights_class": normalized["rights_class"],
        "rights_review_required": normalized["rights_review_required"],
        "rights_review_status": normalized["rights_review_status"],
        "adaptation_notice": normalized["adaptation_notice"],
    }

    for field_name in _ADAPTATION_PROVENANCE_TEXT_FIELDS:
        value = supplied_provenance.get(field_name, nested_attempt_metadata.get(field_name))
        if field_name.endswith("_path") or field_name == "dossier_artifact_path":
            value = _safe_provenance_path(value)
        else:
            value = _bounded_ascii_provenance_text(value)
        if value:
            safe_provenance[field_name] = value

    for field_name in ("attempt_number", "revision_number"):
        value = supplied_provenance.get(field_name, nested_attempt_metadata.get(field_name))
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe_provenance[field_name] = value

    # Adaptation generation is never inferred from a building target alone.
    # Preserve only the explicit boolean policy opt-in for the guarded seam.
    if canonical_monster_generation_enabled():
        safe_provenance["allow_canonical_monster_generation"] = True

    model_metadata: Dict[str, str] = {}
    for field_name in _ADAPTATION_MODEL_METADATA_FIELDS:
        value = supplied_provenance.get(field_name)
        if value is None:
            value = nested_model_metadata.get(field_name)
        if value is not None:
            compact = _bounded_ascii_provenance_text(value, 160)
            if compact:
                model_metadata[field_name] = compact
    if model_metadata:
        safe_provenance["model_metadata"] = model_metadata

    # Adaptation workspace roots are Python-owned filesystem inputs. Preserve
    # every explicitly supplied root so exact reuse cannot be hidden by a
    # convenience cap; each path is still validated as a project-relative
    # provenance reference.
    for roots_key in ("reusable_module_dirs", "reusable_roots", "bestiary_roots", "compendium_roots"):
        raw_roots = supplied_provenance.get(roots_key)
        if not isinstance(raw_roots, (list, tuple)):
            continue
        safe_roots = []
        for raw_root in raw_roots:
            safe_root = _safe_provenance_path(raw_root)
            if safe_root and safe_root not in safe_roots:
                safe_roots.append(safe_root)
        if safe_roots:
            safe_provenance[roots_key] = safe_roots

    world_context = supplied_provenance.get("world_context_provenance")
    if world_context is None:
        world_context = supplied_provenance.get("world_context")
    if world_context is None:
        world_context = nested_attempt_metadata
    safe_world_context = build_world_context_provenance(world_context)
    safe_provenance["world_context_provenance"] = safe_world_context
    safe_provenance["world_seed_status"] = safe_world_context.get("world_seed_status")
    if safe_world_context.get("world_seed_version"):
        safe_provenance["world_seed_version"] = safe_world_context.get("world_seed_version")
    if safe_world_context.get("world_seed_hash"):
        safe_provenance["world_seed_hash"] = safe_world_context.get("world_seed_hash")
    safe_provenance["world_context_status"] = safe_world_context.get("context_status")
    safe_provenance["world_context_hash"] = safe_world_context.get("context_hash")
    safe_provenance["context_hash"] = safe_world_context.get("context_hash")

    handoff = {
        "dossier": normalized,
        "provenance": safe_provenance,
    }
    try:
        serialized = json.dumps(handoff, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("llm_adaptation_dossier_not_serializable") from exc
    if len(serialized) > MAX_LLM_ADAPTATION_HANDOFF_CHARS:
        raise ValueError("llm_adaptation_dossier_exceeds_handoff_limit")
    return handoff


def _utc_now_iso() -> str:
    """Return UTC timestamp in ISO-8601 format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _adaptation_build_status(value: Any) -> str:
    """Map packet-builder statuses to the attempt-artifact vocabulary."""
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "pass", "passed", "completed"}:
        return BUILD_STATUS_PASSED
    if normalized in {"blocked", "not_publishable"}:
        return BUILD_STATUS_BLOCKED
    if normalized in {"failed", "error"}:
        return BUILD_STATUS_FAILED
    return BUILD_STATUS_PENDING


def _has_full_adaptation_gate_envelope(value: Any) -> bool:
    """Identify the complete gate-composer envelope required for continuation.

    The real composer always supplies per-domain reports and an identity-bearing
    provenance envelope.  A few provider-free packet-builder harnesses inject a
    deliberately small passing gate marker to exercise the envelope handoff;
    those harnesses do not claim to exercise publication continuation.  Keep
    that compatibility seam explicit rather than teaching the continuation
    validator to accept incomplete production reports.
    """
    if not isinstance(value, Mapping):
        return False
    required_domains = {
        "schema",
        "readiness",
        "mechanical_closure",
        "semantic_authority",
        "semantic_probes",
        "report_agreement",
    }
    gates = value.get("gates")
    provenance = value.get("provenance")
    return (
        isinstance(gates, Mapping)
        and required_domains.issubset(gates)
        and isinstance(provenance, Mapping)
    )


def _adaptation_authority_inputs_are_complete(files: Mapping[str, Any]) -> bool:
    """Return whether the optional source authority inputs are fully present.

    Adaptation test/build workspaces may intentionally omit the source manifest
    (or contain only a partial normalized packet) after the module has already
    passed the Python-owned authority and gate stages.  In that case the
    continuation join must consume the current staged authority rather than
    inventing replacement evidence.  If both canonical inputs are present,
    their normal refresh path remains mandatory, including malformed-input
    failures.
    """
    try:
        return all(
            Path(files[name]).is_file()
            for name in ("source_manifest", "normalized_packet")
            if name in files
        ) and all(name in files for name in ("source_manifest", "normalized_packet"))
    except (TypeError, OSError, ValueError):
        return False


def _finalize_adaptation_continuity(
    module_dir: Path,
    module_slug: str,
) -> Dict[str, Any]:
    """Finalize continuity metadata on one adaptation staging target.

    This is deliberately adaptation-scoped and runs before convergence or any
    readiness/gate consumer.  The helpers are deterministic and the write is
    atomic; a failed repair is a concrete hard failure, not an LLM semantic
    revision candidate.
    """
    context_path = module_dir / "module_context.json"
    plot_path = module_dir / "module_plot.json"
    try:
        module_context = safe_read_json(str(context_path))
        module_plot = safe_read_json(str(plot_path))
        if not isinstance(module_context, dict):
            return {
                "status": "failed",
                "reason_code": "adaptation_continuity_finalization_failed",
                "errors": ["module_context_missing_or_invalid"],
            }
        if not isinstance(module_plot, dict):
            return {
                "status": "failed",
                "reason_code": "adaptation_continuity_finalization_failed",
                "errors": ["module_plot_missing_or_invalid"],
            }

        from scripts.homebrew_ingest_dev import (
            _ensure_continuity_contract_keys,
            _normalize_continuity_contract,
            enrich_continuity_cross_refs,
        )

        continuity_patch = _ensure_continuity_contract_keys(
            module_context, module_slug
        )
        finalized_context = continuity_patch.get("module_context")
        if not isinstance(finalized_context, dict):
            return {
                "status": "failed",
                "reason_code": "adaptation_continuity_finalization_failed",
                "errors": ["continuity_normalization_returned_invalid_context"],
            }
        continuity_enrichment = enrich_continuity_cross_refs(
            module_slug=module_slug,
            module_context=finalized_context,
            module_plot=module_plot,
        )
        finalized_context = continuity_enrichment.get(
            "module_context", finalized_context
        )
        if not isinstance(finalized_context, dict):
            return {
                "status": "failed",
                "reason_code": "adaptation_continuity_finalization_failed",
                "errors": ["continuity_enrichment_returned_invalid_context"],
            }

        contract = _normalize_continuity_contract(
            module_context=finalized_context,
            module_plot=module_plot,
            strict=True,
            alias_registry=None,
        )
        if str(contract.get("status") or "error") == "error":
            return {
                "status": "failed",
                "reason_code": "adaptation_continuity_finalization_failed",
                "errors": list(contract.get("errors") or [])[:8],
                "continuity_contract": contract,
            }

        changed = bool(continuity_patch.get("changed")) or bool(
            continuity_enrichment.get("changed")
        )
        if changed and not safe_write_json(str(context_path), finalized_context):
            return {
                "status": "failed",
                "reason_code": "adaptation_continuity_finalization_failed",
                "errors": ["continuity_context_atomic_write_failed"],
                "continuity_contract": contract,
            }
        return {
            "status": "success",
            "reason_code": "adaptation_continuity_finalized",
            "changed": changed,
            "injected_keys": continuity_patch.get("injected_keys", []),
            "continuity_contract": contract,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "reason_code": "adaptation_continuity_finalization_failed",
            "errors": [f"continuity_finalization_exception:{type(exc).__name__}"],
        }


def _adaptation_revision_projection(
    build_result: Mapping[str, Any],
    classification: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the bounded revision decision persisted with build artifacts."""
    classification = classification if isinstance(classification, Mapping) else {}
    budget = build_result.get("revision_budget")
    if not isinstance(budget, Mapping):
        budget = classification.get("revision_budget")
    budget = dict(budget) if isinstance(budget, Mapping) else {}
    current = budget.get("current_revision", build_result.get("revision_number", 0))
    maximum = budget.get("max_revisions", 1)
    remaining = budget.get("remaining_before_failure", budget.get("remaining_revisions"))
    try:
        current = max(0, int(current))
    except (TypeError, ValueError):
        current = 0
    try:
        maximum = max(0, min(2, int(maximum)))
    except (TypeError, ValueError):
        maximum = 1
    if remaining is None:
        remaining = max(0, maximum - current)
    try:
        remaining = max(0, min(2, int(remaining)))
    except (TypeError, ValueError):
        remaining = max(0, maximum - current)
    eligible = build_result.get("revision_eligible")
    if not isinstance(eligible, bool):
        eligible = classification.get("revision_eligible") is True
    semantic_eligible = build_result.get("semantic_revision_eligible")
    if not isinstance(semantic_eligible, bool):
        semantic_eligible = classification.get("semantic_revision_eligible") is True
    next_eligible = build_result.get("next_revision_eligible")
    if not isinstance(next_eligible, bool):
        next_eligible = classification.get("next_revision_eligible") is True
    consumed = build_result.get("semantic_revision_budget_consumed")
    if not isinstance(consumed, bool):
        consumed = classification.get("semantic_revision_budget_consumed") is True
    exhausted = current >= maximum and maximum > 0
    if exhausted:
        remaining = 0
        eligible = semantic_eligible = next_eligible = False
    diagnostics = build_result.get("failure_diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = classification.get("diagnostics")
    bounded_diagnostics = []
    if isinstance(diagnostics, list):
        for item in diagnostics[:6]:
            if isinstance(item, Mapping):
                bounded_diagnostics.append({
                    "code": _bounded_ascii_provenance_text(item.get("code") or "unclassified", 120),
                    "message": _bounded_ascii_provenance_text(item.get("message") or item.get("reason") or "", 240),
                })
    return {
        "status": _bounded_ascii_provenance_text(build_result.get("status") or "unknown", 32),
        "outcome": _bounded_ascii_provenance_text(build_result.get("outcome") or "", 48),
        "next_revision_eligible": bool(next_eligible),
        "revision_eligible": bool(eligible),
        "semantic_revision_eligible": bool(semantic_eligible),
        "current_revision": current,
        "max_revisions": maximum,
        "remaining_revisions": remaining,
        "semantic_revision_budget_consumed": bool(consumed),
        "failure_class": _bounded_ascii_provenance_text(
            build_result.get("failure_class") or classification.get("failure_class") or "", 64
        ),
        "failure_code": _bounded_ascii_provenance_text(
            build_result.get("failure_code") or classification.get("code") or "", 120
        ),
        "failed_stage": _bounded_ascii_provenance_text(
            build_result.get("failed_stage") or classification.get("stage") or "", 120
        ),
        "failure_domain": _bounded_ascii_provenance_text(
            build_result.get("failure_domain") or classification.get("domain") or "", 120
        ),
        "diagnostics": bounded_diagnostics,
    }


def _persist_adaptation_attempt_report(
    *,
    workspace: Path,
    job_id: str,
    build_result: Dict[str, Any],
    adaptation_handoff: Mapping[str, Any],
    staging_target: Optional[Mapping[str, Any]],
    build_started_at: Optional[str],
    overwrite: bool = False,
) -> Optional[Dict[str, Any]]:
    """Persist the Python-owned build attempt report for an adaptation.

    The artifact is deliberately separate from the upload workspace's legacy
    ``build_result.json``.  It carries the immutable source identity and a
    fresh report timestamp so later publication agreement cannot trust a stale
    completion claim.
    """
    if not isinstance(staging_target, Mapping):
        return None
    provenance = adaptation_handoff.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    dossier = adaptation_handoff.get("dossier")
    dossier = dossier if isinstance(dossier, Mapping) else {}
    attempt_id = str(staging_target.get("attempt_id") or provenance.get("attempt_id") or "").strip()
    source_hash = str(dossier.get("source_hash") or provenance.get("source_hash") or "").strip().lower()
    source_path = str(provenance.get("source_path") or "").strip()
    if not attempt_id or not source_hash or not source_path:
        build_result["adaptation_attempt_report"] = {
            "status": "not_persisted",
            "reason": "source_identity_incomplete",
        }
        return None

    attempt_number = staging_target.get("attempt_number", provenance.get("attempt_number", 1))
    revision_number = staging_target.get("revision_number", provenance.get("revision_number", 0))
    completed_at = str(build_result.get("completed_at") or _utc_now_iso())
    gate_summary = {
        "build_status": _adaptation_build_status(build_result.get("status")),
        "stage": str(build_result.get("stage") or "build"),
        "status": str(build_result.get("status") or "unknown"),
    }
    if build_result.get("error"):
        gate_summary["error"] = _bounded_ascii_provenance_text(
            build_result.get("error"), 800
        )
    for key, limit in (
        ("failure_class", 64),
        ("failure_group", 64),
        ("failure_domain", 120),
        ("failure_code", 120),
        ("failed_stage", 120),
    ):
        if build_result.get(key):
            gate_summary[key] = _bounded_ascii_provenance_text(build_result[key], limit)
    if isinstance(build_result.get("failure_diagnostics"), list):
        first_diagnostic = next(
            (
                item
                for item in build_result["failure_diagnostics"][:12]
                if isinstance(item, Mapping)
            ),
            None,
        )
        if first_diagnostic:
            gate_summary["diagnostic"] = _bounded_ascii_provenance_text(
                first_diagnostic.get("message")
                or first_diagnostic.get("reason")
                or first_diagnostic.get("code"),
                240,
            )
    failure_classification = build_result.get("failure_classification")
    # Keep the artifact contract bounded.  The classification contains nested
    # revision-budget and diagnostic payloads that exceed gate-summary value
    # bounds. Preserve only scalar classification fields; the full
    # classification remains on the in-memory build result.
    if isinstance(failure_classification, Mapping):
        compact_classification = {}
        for key, value in list(failure_classification.items()):
            if not isinstance(key, str):
                continue
            if isinstance(value, (str, bool, int, float)):
                compact_classification[key] = value
            elif key == "revision_budget" and isinstance(value, Mapping):
                compact_classification[key] = {
                    nested_key: nested_value
                    for nested_key, nested_value in list(value.items())[:8]
                    if isinstance(nested_key, str)
                    and isinstance(nested_value, (str, bool, int, float))
                }
            if len(compact_classification) >= 16:
                break
        if isinstance(failure_classification.get("revision_budget"), Mapping):
            compact_classification["revision_budget"] = {
                nested_key: nested_value
                for nested_key, nested_value in list(
                    failure_classification["revision_budget"].items()
                )[:8]
                if isinstance(nested_key, str)
                and isinstance(nested_value, (str, bool, int, float))
            }
        if compact_classification:
            gate_summary["failure_classification"] = compact_classification
    gate_summary["revision_projection"] = _adaptation_revision_projection(
        build_result, failure_classification
    )
    if isinstance(build_result.get("adaptation_gates"), Mapping):
        adaptation_gates = build_result["adaptation_gates"]
        gate_summary.update(
            {
                "adaptation_gate_status": str(adaptation_gates.get("status") or "unknown"),
                "playable_status": str(adaptation_gates.get("playable_status") or "unknown"),
                "candidate_eligible": adaptation_gates.get("candidate_eligible") is True,
            }
        )
    metadata = {
        "job_id": str(job_id or "adaptation-build"),
        "source_profile": str(dossier.get("source_profile") or provenance.get("source_profile") or "adaptation"),
        "created_by": "toolkit_homebrew_packet_builder",
    }
    source_format = provenance.get("source_format")
    if source_format:
        metadata["source_format"] = str(source_format)
    artifact = build_build_result_artifact(
        attempt_id=attempt_id,
        source_title=str(dossier.get("source_title") or provenance.get("source_title") or "Adaptation source"),
        source_hash=source_hash,
        source_path=source_path,
        staging_path=str(staging_target.get("path") or ""),
        build_status=_adaptation_build_status(build_result.get("status")),
        module_slug=str(build_result.get("module_name") or staging_target.get("module_slug") or "") or None,
        gate_summary=gate_summary,
        revision_number=int(revision_number),
        build_started_at=build_started_at,
        build_completed_at=completed_at,
        model_metadata=provenance.get("model_metadata") if isinstance(provenance.get("model_metadata"), Mapping) else {},
        metadata=metadata,
        world_context_provenance=provenance.get("world_context_provenance"),
    )
    # TABLETOP MODE: Publication agreement compares the complete attempt
    # identity across every artifact, including the staging attempt number.
    artifact["attempt_number"] = int(attempt_number)
    persisted = persist_adaptation_build_result_artifact(
        workspace, artifact, overwrite=overwrite
    )
    path = get_adaptation_artifact_path(
        workspace,
        attempt_id,
        ARTIFACT_KIND_BUILD_RESULT,
        int(revision_number),
    )
    # TABLETOP MODE: Verify the attempt-scoped write.  A compatibility writer
    # may report success while leaving an older reserved artifact untouched;
    # retry the same atomic artifact write only when its projection is stale.
    if overwrite:
        try:
            written = safe_read_json(str(path))
            expected_projection = (
                artifact.get("payload", {}).get("gate_summary", {}).get(
                    "revision_projection", {}
                )
            )
            actual_projection = (
                written.get("payload", {}).get("gate_summary", {}).get(
                    "revision_projection", {}
                )
                if isinstance(written, Mapping)
                else {}
            )
            if not persisted or actual_projection != expected_projection:
                from utils.toolkit_adaptation_artifacts import persist_adaptation_artifact

                persisted = bool(
                    persist_adaptation_artifact(workspace, artifact, overwrite=True)
                )
        except Exception as verification_error:
            warning(
                "TOOLKIT_HOMEBREW: Adaptation attempt artifact verification "
                f"degraded: {type(verification_error).__name__}",
                category="toolkit_adaptation",
            )
    build_result["adaptation_attempt_report"] = {
        "status": "persisted" if persisted else "not_persisted",
        "path": str(path.relative_to(Path.cwd())) if path.is_relative_to(Path.cwd()) else str(path),
        "artifact_kind": ARTIFACT_KIND_BUILD_RESULT,
        "attempt_id": attempt_id,
        "attempt_number": int(attempt_number),
        "revision_number": int(revision_number),
        "created_at": artifact.get("created_at"),
        "source_hash": source_hash,
    }
    if not persisted:
        warning(
            "TOOLKIT_HOMEBREW: Adaptation attempt artifact was not persisted "
            f"(path={path}, overwrite={overwrite}, "
            f"artifact_kind={artifact.get('artifact_kind')})",
            category="toolkit_adaptation",
        )
    build_result["adaptation_artifact_workspace"] = str(workspace)
    return artifact if persisted else None


def _persist_current_adaptation_build_result(
    workspace: Path,
    build_result: Dict[str, Any],
) -> bool:
    """Persist the current adaptation result in the active workspace.

    The plain workspace ``build_result.json`` is the compatibility/equivalent
    failure artifact for paths that terminate before a complete adaptation
    provenance envelope exists.  It is deliberately overwritten with the
    current in-memory result so a prior attempt cannot masquerade as current.
    """
    try:
        persisted = bool(
            persist_legacy_build_result_artifact(Path(workspace), build_result)
        )
    except Exception as persistence_error:
        warning(
            "TOOLKIT_HOMEBREW: Current adaptation build result persistence failed",
            category="web_interface",
        )
        persisted = False

    build_result["build_result_persisted"] = persisted
    if not persisted:
        build_result["status"] = "failed"
        build_result["stage"] = "adaptation_artifact_persistence"
        build_result["error"] = "build_result_persist_failed"
    return persisted


def _adaptation_reusable_roots(handoff: Mapping[str, Any]) -> list:
    """Collect Python-supplied reusable roots without widening legacy builds."""
    roots = []
    for container_key in ("provenance", "dossier"):
        container = handoff.get(container_key)
        if not isinstance(container, Mapping):
            continue
        for key in ("reusable_module_dirs", "reusable_roots", "bestiary_roots", "compendium_roots"):
            value = container.get(key)
            values = value if isinstance(value, (list, tuple)) else [value]
            for item in values:
                if isinstance(item, (str, os.PathLike)) and str(item).strip():
                    root = str(item)
                    if root not in roots:
                        roots.append(root)
    return roots


def _adaptation_generation_context(
    handoff: Mapping[str, Any], approved_identities: Any
) -> Dict[str, Any]:
    """Build bounded, identity-scoped source context for monster generation."""
    dossier = handoff.get("dossier")
    dossier = dossier if isinstance(dossier, Mapping) else {}
    approved = []
    for value in approved_identities if isinstance(approved_identities, (list, tuple)) else []:
        identity = _bounded_ascii_provenance_text(value, 160)
        if identity and identity not in approved:
            approved.append(identity)
    approved = approved[:128]
    evidence = []
    seeds = dossier.get("encounter_seeds")
    if isinstance(seeds, list):
        for seed in seeds[:8]:
            if not isinstance(seed, Mapping):
                continue
            adversaries = seed.get("adversaries")
            if not isinstance(adversaries, list):
                continue
            matched = [
                identity for identity in approved
                if any(str(item).strip().lower() == identity.strip().lower() for item in adversaries)
            ]
            if not matched:
                continue
            evidence.append({
                "approved_identities": matched[:8],
                "encounter_name": _bounded_ascii_provenance_text(seed.get("name"), 160),
                "location": _bounded_ascii_provenance_text(seed.get("location"), 160),
                "role": _bounded_ascii_provenance_text(seed.get("setup"), 240),
                "stakes": _bounded_ascii_provenance_text(seed.get("stakes"), 240),
                "source_basis": _bounded_ascii_provenance_text(seed.get("source_basis"), 200),
            })
    return {
        "approved_identities": approved,
        "encounter_evidence": evidence[:8],
        "level_range": _bounded_ascii_provenance_text(dossier.get("level_range"), 64),
        "srd_exemplar_guidance": (
            "Use compact 5e SRD-compatible mechanics and official baseline statistics "
            "where the approved identity is a standard creature. Do not classify prose, "
            "rename identities, substitute creatures, or add identities."
        ),
    }


def _run_adaptation_monster_guardrail(*args: Any, **kwargs: Any) -> Any:
    """Lazy, provider-free seam for adaptation monster guardrail evaluation.

    Keeping the dependency lazy preserves the legacy import boundary while
    giving route tests an explicit injectable production seam.
    """
    from utils.toolkit_adaptation_monster_guardrail import (
        build_adaptation_monster_guardrail_report,
    )

    return build_adaptation_monster_guardrail_report(*args, **kwargs)


def _sanitize_module_name(raw_name: str) -> str:
    """Return a builder-safe module name."""
    safe = "".join(ch for ch in str(raw_name or "") if ch.isalnum() or ch in {"_", "-", " "}).strip()
    safe = safe.replace("-", "_").replace(" ", "_")
    if not safe:
        return "Homebrew_Upload_Module"
    return safe


def _derive_builder_shape(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Derive stable builder parameters from normalized packet shape."""
    acts = packet.get("acts") or []
    locations = packet.get("locations") or []

    if isinstance(acts, list) and acts:
        num_areas = max(1, min(len(acts), 10))
    else:
        num_areas = 3

    location_count = len(locations) if isinstance(locations, list) else 0
    if location_count > 0:
        locations_per_area = int(math.ceil(float(location_count) / float(num_areas)))
        locations_per_area = max(3, min(locations_per_area, 30))
    else:
        locations_per_area = 5

    title = str(packet.get("title") or "Homebrew Upload Module").strip()
    module_name = _sanitize_module_name(title)

    return {
        "module_name": module_name,
        "num_areas": num_areas,
        "locations_per_area": locations_per_area,
        "output_directory": f"./modules/{module_name}",
    }


def derive_packet_module_name(packet: Dict[str, Any]) -> str:
    """Return normalized module slug derived from packet content."""
    params = _derive_builder_shape(packet)
    return str(params.get("module_name") or "").strip()


def _read_builder_narrative(
    files: Dict[str, Path],
    packet: Dict[str, Any],
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Resolve builder narrative text with blueprint preference then packet fallback."""
    blueprint_enabled = bool(ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF)
    narrative_text = ""
    source = "packet_fallback"

    # Prefer blueprint-derived narrative when blueprint is ready
    if blueprint_enabled and blueprint and blueprint.get("blueprint_status") == "ready":
        narrative_path = files["builder_narrative"]
        try:
            narrative_text = narrative_path.read_text(encoding="utf-8").strip()
        except Exception:
            narrative_text = ""
        if narrative_text:
            source = "blueprint_narrative"
            return {
                "narrative": narrative_text,
                "source": source,
            }

    # Fallback: workspace narrative file
    narrative_path = files["builder_narrative"]
    try:
        narrative_text = narrative_path.read_text(encoding="utf-8").strip()
    except Exception:
        narrative_text = ""

    if narrative_text:
        source = "workspace_builder_narrative"
    else:
        title = str(packet.get("title") or "Unknown Module").strip()
        description = str(packet.get("description") or "").strip()
        summary = str(packet.get("adventure_summary") or "").strip()
        narrative_text = "\n\n".join(
            line
            for line in [
                f"Build module: {title}",
                description,
                summary,
            ]
            if line
        ).strip()
        if not narrative_text:
            narrative_text = f"Build module: {title}"

    return {
        "narrative": narrative_text,
        "source": source,
    }


def _validate_review_snapshot(packet: Dict[str, Any], review_snapshot: Dict[str, Any]) -> Optional[str]:
    """Validate review snapshot and packet identity alignment."""
    if not isinstance(review_snapshot, dict) or not review_snapshot:
        return "review_snapshot_missing"

    decision = str(review_snapshot.get("decision") or "").strip().lower()
    if decision != REVIEW_DECISION_APPROVE:
        return "review_snapshot_not_approved"

    packet_identity = review_snapshot.get("packet_identity") or {}
    review_source_hash = str(packet_identity.get("source_hash") or "").strip()
    packet_source_hash = str(packet.get("source_hash") or "").strip()
    if review_source_hash and packet_source_hash and review_source_hash != packet_source_hash:
        return "review_packet_identity_mismatch"

    return None


def _execute_module_builder(
    builder_input: Dict[str, Any],
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> None:
    """Run the upstream module builder using derived packet parameters."""
    from core.generators.module_builder import BuilderConfig, ModuleBuilder

    params = dict(builder_input["derived_builder_parameters"])
    _staging_target = builder_input.get("staging_target")
    if (
        str(builder_input.get("build_mode") or "") == ADAPTATION_MODE_LLM
        and isinstance(_staging_target, Mapping)
    ):
        _adaptation_payload = builder_input.get("llm_adaptation")
        _adaptation_dossier = (
            _adaptation_payload.get("dossier")
            if isinstance(_adaptation_payload, Mapping)
            else None
        )
        _staging_source_hash = (
            str(_adaptation_dossier.get("source_hash") or "").strip().lower()
            if isinstance(_adaptation_dossier, Mapping)
            else None
        )
        _staging_provenance = (
            _adaptation_payload.get("provenance")
            if isinstance(_adaptation_payload, Mapping)
            else None
        )
        _staging_target = validate_adaptation_staging_target(
            _staging_target,
            source_hash=_staging_source_hash or None,
            attempt_id=(
                str(_staging_provenance.get("attempt_id"))
                if isinstance(_staging_provenance, Mapping)
                and _staging_provenance.get("attempt_id") is not None
                else None
            ),
            attempt_number=(
                _staging_provenance.get("attempt_number")
                if isinstance(_staging_provenance, Mapping)
                else None
            ),
            module_slug=str(params.get("module_name") or ""),
            revision_number=(
                _staging_target.get("revision_number")
                if isinstance(_staging_target, Mapping)
                else None
            ),
            require_reserved=False,
        )
        params["output_directory"] = _staging_target["path"]
    config = BuilderConfig(
        module_name=params["module_name"],
        num_areas=params["num_areas"],
        locations_per_area=params["locations_per_area"],
        output_directory=params["output_directory"],
        verbose=True,
        build_mode=str(builder_input.get("build_mode") or "legacy"),
        llm_timeout_seconds=(
            MODULE_GENERATION_API_TIMEOUT_SECONDS
            if str(builder_input.get("build_mode") or "") == ADAPTATION_MODE_LLM
            else None
        ),
    )
    builder = ModuleBuilder(config)
    if progress_callback:
        builder.progress_callback = progress_callback

        original_log = builder.log

        def _log_with_progress(message: str) -> None:
            original_log(message)
            progress_callback("log", message)

        builder.log = _log_with_progress  # type: ignore[assignment]

    _adaptation_payload = builder_input.get("llm_adaptation")
    if (
        str(builder_input.get("build_mode") or "") == ADAPTATION_MODE_LLM
        and _adaptation_payload is None
    ):
        raise ValueError("llm_adaptation_payload_missing")
    if _adaptation_payload is not None:
        if str(builder_input.get("build_mode") or "") != ADAPTATION_MODE_LLM:
            raise ValueError("llm_adaptation_payload_requires_adaptation_build_mode")
        _adaptation_payload = build_llm_adaptation_handoff(_adaptation_payload)
        # Adaptation is a dossier handoff, not a source-lock prompt. Prompt
        # consumption belongs to the later adaptation-aware builder task.
        builder.build_module(
            builder_input["builder_narrative"],
            llm_adaptation=_adaptation_payload,
        )
        return

    _source_context = _build_module_builder_source_context(builder_input)
    if _source_context:
        builder.build_module(
            builder_input["builder_narrative"] + "\n\n" + _source_context
        )
    else:
        builder.build_module(builder_input["builder_narrative"])


def _execute_seed_writer_build(
    workspace: Path,
    job_id: str,
    files: Dict[str, Path],
    params: Dict[str, Any],
    blueprint_artifact: Dict[str, Any],
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """Run v2 seed writer build instead of ModuleBuilder for accurate-ingest."""
    module_dir = Path(params["output_directory"])

    if progress_callback:
        progress_callback("seeding", "Seeding module from source blueprint")

    try:
        from utils.toolkit_blueprint_seed_writer import materialize_module_from_blueprint

        if module_dir.exists():
            seed_result = materialize_module_from_blueprint(
                blueprint_artifact, str(module_dir), overwrite=True, dry_run=False
            )
        else:
            seed_result = materialize_module_from_blueprint(
                blueprint_artifact, str(module_dir), overwrite=False, dry_run=False
            )

        seed_status = seed_result.get("seed_status", "failed")
        if seed_status != "success":
            error(
                f"TOOLKIT_HOMEBREW: Seed writer returned status '{seed_status}' for job={job_id}",
                category="web_interface",
            )
            return {
                "status": "failed",
                "stage": "seed",
                "error": f"seed_writer_{seed_status}",
                "job_id": job_id,
                "module_name": params["module_name"],
                "output_directory": params["output_directory"],
            }
    except Exception as e:
        error(
            f"TOOLKIT_HOMEBREW: Seed writer failed for job={job_id}: {e}",
            exception=e,
            category="web_interface",
        )
        return {
            "status": "failed",
            "stage": "seed",
            "error": f"seed_writer_exception:{e}",
            "job_id": job_id,
            "module_name": params["module_name"],
            "output_directory": params["output_directory"],
        }

    all_warnings: list = list(seed_result.get("warnings", []))

    if progress_callback:
        progress_callback("enriching", "Running bounded enrichment")

    enrichment_status = "skipped"
    enrichment_warnings: list = []
    try:
        from utils.toolkit_blueprint_enrichment import run_enrichment_pipeline

        enrichment_result = run_enrichment_pipeline(blueprint_artifact, str(module_dir))
        enrichment_status = enrichment_result.get("status", "skipped")
        enrichment_warnings = enrichment_result.get("warnings", [])
        all_warnings.extend(enrichment_warnings)
    except Exception as e:
        warning(
            f"TOOLKIT_HOMEBREW: Enrichment pipeline failed for job={job_id}: {e}",
            category="web_interface",
        )
        enrichment_status = "degraded"
        all_warnings.append(f"Enrichment pipeline failed: {e}")

    info(
        f"TOOLKIT_HOMEBREW: Seed writer build complete for job={job_id} "
        f"seed={seed_status} enrichment={enrichment_status}",
        category="web_interface",
    )

    return {
        "status": "success",
        "stage": "build",
        "job_id": job_id,
        "build_mode": "packet_workspace_v2",
        "completed_at": _utc_now_iso(),
        "module_name": params["module_name"],
        "output_directory": params["output_directory"],
        "seed_status": seed_status,
        "seed_coverage": seed_result.get("coverage", {}),
        "enrichment_status": enrichment_status,
        "warnings": all_warnings,
    }


_ACCURATE_INGEST_EVIDENCE_PATHS = [
    "source_graph",
    "normalization_fidelity_report",
    "identity_resolution_report",
    "plot_topology_report",
]


def _classify_blueprint_handoff(
    files: Dict[str, Path],
    blueprint_artifact: Optional[Dict[str, Any]],
    blueprint_report_artifact: Optional[Dict[str, Any]],
) -> str:
    """Classify handoff mode for this workspace.

    Returns one of:
        `source_blueprint_v2_ready` -- v2 blueprint artifacts, status is ready.
        `source_blueprint_ready` -- v1 blueprint artifacts, status is ready.
        `blueprint_required_not_ready` -- blueprint is required but not ready.
        `legacy_allowed` -- workspace has no accurate-ingest evidence or blueprint handoff.
    """
    blueprint_enabled = bool(ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF)
    if not blueprint_enabled:
        return "legacy_allowed"

    blueprint_status = str((blueprint_artifact or {}).get("blueprint_status") or "").strip().lower()
    report_status = str((blueprint_report_artifact or {}).get("blueprint_status") or "").strip().lower()
    fidelity_status = str((blueprint_report_artifact or {}).get("fidelity_status") or "").strip().lower()

    # Source-blueprint mode requires both artifacts to be present and ready.
    if blueprint_status == "ready" and report_status == "ready":
        version = str((blueprint_artifact or {}).get("blueprint_version") or "").strip()
        if "v2" in version.lower():
            return "source_blueprint_v2_ready"
        return "source_blueprint_ready"

    # blocked_by_fidelity: blueprint was blocked by precheck findings but the
    # normalized packet and fidelity report are complete.  Accept as degraded
    # v2 mode - seed writer handles whatever the packet contains.
    if report_status == "blocked_by_fidelity":
        return "source_blueprint_v2_degraded"

    # If report is ready but blueprint is missing (fidelity blocked creation),
    # and the normalized packet exists, treat as degraded v2 mode
    if report_status == "ready" and not blueprint_status:
        if fidelity_status == "blocked":
            return "source_blueprint_v2_degraded"

    # If either artifact exists, blueprint mode has been attempted and must fail closed.
    if blueprint_artifact or blueprint_report_artifact:
        return "blueprint_required_not_ready"

    # Blueprint report missing but accurate-ingest evidence exists
    has_evidence = any(
        files.get(p) and files[p].exists()
        for p in _ACCURATE_INGEST_EVIDENCE_PATHS
    )
    if has_evidence:
        return "blueprint_required_not_ready"

    # No blueprint artifacts and no accurate-ingest evidence = legacy workspace
    return "legacy_allowed"


def _describe_blueprint_not_ready(
    blueprint_artifact: Optional[Dict[str, Any]],
    blueprint_report_artifact: Optional[Dict[str, Any]],
) -> str:
    """Return a deterministic failure reason for non-ready blueprint handoff."""
    blueprint_status = str((blueprint_artifact or {}).get("blueprint_status") or "").strip().lower()
    report_status = str((blueprint_report_artifact or {}).get("blueprint_status") or "").strip().lower()

    if blueprint_status == "ready" and not report_status:
        return "missing_blueprint_report"
    if report_status == "ready" and not blueprint_status:
        return "missing_blueprint"
    if blueprint_status and not report_status:
        return f"blueprint_{blueprint_status}"
    if report_status and not blueprint_status:
        return f"report_{report_status}"
    if blueprint_status and report_status:
        if blueprint_status != "ready":
            return f"blueprint_{blueprint_status}"
        if report_status != "ready":
            return f"report_{report_status}"
    return "missing_artifacts"


def _run_toolkit_homebrew_packet_build(
    workspace: Path,
    job_id: str,
    builder_executor: Optional[Callable[..., None]] = None,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    overwrite_confirmed: bool = False,
    seed_writer_mode: Optional[str] = None,
    adaptation_route: Optional[str] = None,
    adaptation_dossier: Optional[Mapping[str, Any]] = None,
    adaptation_provenance: Optional[Mapping[str, Any]] = None,
    adaptation_staging_root: Optional[str] = None,
    adaptation_staging_target: Optional[Mapping[str, Any]] = None,
    adaptation_convergence_callback: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    adaptation_revision_callback: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    adaptation_finalization_operation: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one approved Homebrew upload workspace from normalized packet.

    Args:
        workspace: Upload workspace directory.
        job_id: Unique job identifier.
        builder_executor: Optional override for the module builder callable.
        progress_callback: Optional progress callback (status, message).
        overwrite_confirmed: Whether route-level overwrite confirmation has been
            obtained. If the output module directory already exists and this is
            False, the build fails before any writes.
        seed_writer_mode: Optional explicit seed writer mode ("fallback",
            "preview", "support"). When None, seed writer is gated by
            ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK config. Invalid
            values fail closed.
        adaptation_route: Optional explicit adaptation route request
            ("llm_adaptation"). While ENABLE_LLM_ADAPTATION is disabled (the
            default), the request resolves to the explicit legacy
            accurate-ingest route and this build continues unchanged. When
            adaptation is enabled but no validated dossier is supplied, the
            build fails closed instead of silently running the legacy
            pipeline.
        adaptation_dossier: Optional validated-author handoff payload. This
            is accepted only when the explicit adaptation route is enabled;
            it never changes the default or legacy route.
        adaptation_provenance: Optional bounded attempt/model metadata for the
            adaptation handoff. Python-owned dossier provenance remains
            authoritative.
        adaptation_staging_root: Optional project-relative root for an explicit
            adaptation staging target. Legacy builds ignore this parameter.
        adaptation_staging_target: Optional target previously reserved by the
            adaptation staging helper. It is accepted only for the matching
            adaptation dossier and is never reused after its state changes.
        adaptation_convergence_callback: Provider-free callback seam for
            adaptation convergence tests. Legacy builds never use it.

    Returns:
        Dict with build result status and metadata.
    """
    _pre_requested_adaptation_route = adaptation_route
    if _pre_requested_adaptation_route is None and adaptation_dossier is not None:
        _pre_requested_adaptation_route = ADAPTATION_MODE_LLM
    _pre_adaptation_resolution: Optional[Dict[str, Any]] = None
    if _pre_requested_adaptation_route is not None:
        _pre_adaptation_resolution = resolve_adaptation_routing(
            _pre_requested_adaptation_route,
            enabled_override=ENABLE_LLM_ADAPTATION,
        )

    def _persist_pre_staging_adaptation_failure(
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist failures that occur before a staging target is available."""
        if (
            not isinstance(_pre_adaptation_resolution, Mapping)
            or _pre_adaptation_resolution.get("status") != "enabled"
        ):
            return result
        provenance = (
            adaptation_provenance
            if isinstance(adaptation_provenance, Mapping)
            else {}
        )
        nested_attempt = provenance.get("attempt_metadata")
        nested_attempt = nested_attempt if isinstance(nested_attempt, Mapping) else {}
        attempt_id = provenance.get("attempt_id") or nested_attempt.get("attempt_id")
        attempt_number = provenance.get("attempt_number")
        if attempt_number is None:
            attempt_number = nested_attempt.get("attempt_number")
        revision_number = provenance.get("revision_number")
        if revision_number is None:
            revision_number = nested_attempt.get("revision_number")
        if attempt_id:
            try:
                safe_attempt_number = int(attempt_number or 1)
            except (TypeError, ValueError):
                safe_attempt_number = 1
            try:
                safe_revision_number = int(revision_number or 0)
            except (TypeError, ValueError):
                safe_revision_number = 0
            result["adaptation_attempt_identity"] = {
                "attempt_id": _bounded_ascii_provenance_text(attempt_id, 64),
                "attempt_number": safe_attempt_number,
                "revision_number": safe_revision_number,
            }
        result["adaptation_route_resolution"] = deepcopy(
            _pre_adaptation_resolution
        )
        _persist_current_adaptation_build_result(Path(workspace), result)
        return result

    files = get_workspace_files(workspace)
    packet = load_json_artifact(files["normalized_packet"])
    packet_ok, packet_error = validate_review_packet(packet)
    if not packet_ok:
        return _persist_pre_staging_adaptation_failure({
            "status": "failed",
            "stage": "build",
            "error": f"normalized_packet_invalid:{packet_error}",
            "job_id": job_id,
        })

    review_snapshot = load_json_artifact(files["ui_review_snapshot"])
    review_error = _validate_review_snapshot(packet, review_snapshot)
    if review_error:
        return _persist_pre_staging_adaptation_failure({
            "status": "failed",
            "stage": "build",
            "error": review_error,
            "job_id": job_id,
        })

    params = _derive_builder_shape(packet)

    # TABLETOP MODE: Adaptation route resolution (rollout gated). A dossier is
    # itself an explicit handoff request, but the feature flag still controls
    # whether that handoff may leave the legacy path.
    _adaptation_resolution: Optional[Dict[str, Any]] = _pre_adaptation_resolution
    _requested_adaptation_route = adaptation_route
    if _requested_adaptation_route is None and adaptation_dossier is not None:
        _requested_adaptation_route = ADAPTATION_MODE_LLM
    _adaptation_handoff: Optional[Dict[str, Any]] = None
    _adaptation_surface_provenance: Optional[Dict[str, Any]] = None
    if _requested_adaptation_route is not None:
        _adaptation_resolution = resolve_adaptation_routing(
            _requested_adaptation_route,
            enabled_override=ENABLE_LLM_ADAPTATION,
        )
        if _adaptation_resolution["status"] == "enabled":
            if adaptation_dossier is None:
                return _persist_pre_staging_adaptation_failure({
                    "status": "failed",
                    "stage": "builder_input",
                    "error": "llm_adaptation_dossier_missing",
                    "reason": "Adaptation route selected but no validated dossier "
                              "handoff was supplied; refusing to fall through "
                              "to legacy routing.",
                    "job_id": job_id,
                    "module_name": params.get("module_name"),
                    "adaptation_route_resolution": _adaptation_resolution,
                })
            try:
                _adaptation_handoff = build_llm_adaptation_handoff(
                    adaptation_dossier,
                    adaptation_provenance,
                )
            except (TypeError, ValueError) as adaptation_error:
                return _persist_pre_staging_adaptation_failure({
                    "status": "failed",
                    "stage": "builder_input",
                    "error": str(adaptation_error),
                    "job_id": job_id,
                    "module_name": params.get("module_name"),
                    "adaptation_route_resolution": _adaptation_resolution,
                })
            packet_source_hash = str(packet.get("source_hash") or "").strip().lower()
            dossier_source_hash = str(
                _adaptation_handoff["dossier"].get("source_hash") or ""
            ).strip().lower()
            if packet_source_hash and packet_source_hash != dossier_source_hash:
                return _persist_pre_staging_adaptation_failure({
                    "status": "failed",
                    "stage": "builder_input",
                    "error": "llm_adaptation_source_hash_mismatch",
                    "job_id": job_id,
                    "module_name": params.get("module_name"),
                    "adaptation_route_resolution": _adaptation_resolution,
                })
            _adaptation_surface_provenance = build_adaptation_provenance(
                dossier=_adaptation_handoff.get("dossier"),
                provenance=_adaptation_handoff.get("provenance"),
                adaptation_status="adapted",
                module_slug=params.get("module_name"),
            )

    _is_adaptation_build = _adaptation_handoff is not None
    if adaptation_staging_target is not None and not _is_adaptation_build:
        return {
            "status": "failed",
            "stage": "staging",
            "error": "adaptation_staging_target_requires_adaptation",
            "job_id": job_id,
        }
    if _is_adaptation_build:
        # Adaptation consumes its validated dossier, not the legacy blueprint
        # or its source-lock requirements.
        blueprint_artifact = {}
        blueprint_report_artifact = {}
        handoff_class = "llm_adaptation_ready"
    else:
        blueprint_artifact = load_builder_blueprint_artifact(workspace)
        blueprint_report_artifact = load_builder_blueprint_report_artifact(workspace)
        handoff_class = _classify_blueprint_handoff(files, blueprint_artifact, blueprint_report_artifact)

    # Overwrite authorization: refuse to write over an existing module
    # directory unless route-level confirmation or a valid rebuild plan
    # artifact is present.
    _module_dir = Path(params["output_directory"])
    if not _is_adaptation_build and _module_dir.exists() and not overwrite_confirmed:
        return {
            "status": "failed",
            "stage": "build",
            "error": "overwrite_not_authorized",
            "reason": "Module directory already exists and overwrite was not confirmed. "
                      "Retry with confirm_overwrite=true to authorize a backup-clean rebuild.",
            "job_id": job_id,
            "module_name": params["module_name"],
            "module_dir": str(_module_dir),
        }

    if _is_adaptation_build and seed_writer_mode is not None:
        return _persist_pre_staging_adaptation_failure({
            "status": "failed",
            "stage": "build",
            "error": "llm_adaptation_seed_writer_incompatible",
            "job_id": job_id,
            "module_name": params["module_name"],
        })

    # TABLETOP MODE: seed writer path (explicit mode or fallback flag)
    _seed_writer_mode: Optional[str] = seed_writer_mode
    if _seed_writer_mode is not None and _seed_writer_mode not in _VALID_SEED_WRITER_MODES:
        return {
            "status": "failed",
            "stage": "build",
            "error": f"seed_writer_mode_invalid:{_seed_writer_mode}",
            "job_id": job_id,
            "allowed_modes": sorted(_VALID_SEED_WRITER_MODES),
        }

    _use_seed_writer = False
    if _seed_writer_mode is not None:
        _use_seed_writer = True
    elif (
        bool(ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD)
        and bool(ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK)
        and handoff_class
        in (
            "source_blueprint_v2_ready",
            "source_blueprint_v2_degraded",
        )
    ):
        _use_seed_writer = True
        _seed_writer_mode = "fallback"

    _build_mode = ADAPTATION_MODE_LLM if _is_adaptation_build else "packet_workspace_v1"
    if _is_adaptation_build:
        _use_seed_writer = False
    elif _use_seed_writer and _seed_writer_mode:
        _build_mode = _SEED_BUILD_MODES.get(_seed_writer_mode, "packet_workspace_v2")
    elif handoff_class in ("source_blueprint_v2_ready", "source_blueprint_v2_degraded"):
        _build_mode = "source_enhanced_modulebuilder"
    elif handoff_class == "source_blueprint_ready":
        _build_mode = "source_blueprint_modulebuilder"

    # TABLETOP MODE: Adaptation candidates are always built outside the live
    # modules tree. The target helper reserves a fresh attempt/revision path;
    # legacy accurate-ingest output remains unchanged.
    _adaptation_staging_target: Optional[Dict[str, Any]] = None
    if _is_adaptation_build:
        _adaptation_provenance = _adaptation_handoff.get("provenance", {})
        if not isinstance(_adaptation_provenance, Mapping):
            _adaptation_provenance = {}
        _staging_source_hash = str(
            _adaptation_handoff["dossier"].get("source_hash") or ""
        ).strip().lower()
        _staging_attempt_id = _adaptation_provenance.get("attempt_id")
        _staging_attempt_number = _adaptation_provenance.get("attempt_number", 1)
        _staging_revision_number = _adaptation_provenance.get("revision_number", 0)
        _staging_source_path = _adaptation_provenance.get("source_path", "")
        try:
            if adaptation_staging_target is not None:
                _adaptation_staging_target = validate_adaptation_staging_target(
                    adaptation_staging_target,
                    source_hash=_staging_source_hash,
                    attempt_id=(
                        str(_staging_attempt_id)
                        if _staging_attempt_id is not None
                        else None
                    ),
                    attempt_number=_staging_attempt_number,
                    module_slug=str(params["module_name"]),
                    revision_number=_staging_revision_number,
                )
            else:
                _adaptation_staging_target = create_adaptation_staging_target(
                    _staging_source_hash,
                    attempt_id=(
                        str(_staging_attempt_id)
                        if _staging_attempt_id is not None
                        else None
                    ),
                    attempt_number=_staging_attempt_number,
                    revision_number=_staging_revision_number,
                    job_id=job_id,
                    source_path=str(_staging_source_path or ""),
                    module_slug=str(params["module_name"]),
                    staging_root=(
                        adaptation_staging_root or DEFAULT_ADAPTATION_STAGING_ROOT
                    ),
                )
        except (TypeError, ValueError) as staging_error:
            return _persist_pre_staging_adaptation_failure({
                "status": "failed",
                "stage": "staging",
                "error": str(staging_error),
                "job_id": job_id,
                "module_name": params.get("module_name"),
                "build_mode": _build_mode,
            })

        params = dict(params)
        params["output_directory"] = _adaptation_staging_target["path"]
        _module_dir = Path(params["output_directory"])
        try:
            _adaptation_staging_target = update_adaptation_staging_target(
                _adaptation_staging_target,
                STAGING_STATE_BUILDING,
            )
        except (TypeError, ValueError) as staging_error:
            return _persist_pre_staging_adaptation_failure({
                "status": "failed",
                "stage": "staging",
                "error": f"staging_state_update_failed:{staging_error}",
                "job_id": job_id,
                "module_name": params.get("module_name"),
                "build_mode": _build_mode,
                "staging_target": deepcopy(_adaptation_staging_target),
            })

    def _finish_adaptation_staging(result: Dict[str, Any]) -> Dict[str, Any]:
        """Record terminal stage state without deleting provisional output."""
        if _is_adaptation_build and "failure_classification" not in result:
            classification = _adaptation_failure_classification(
                result,
                adaptation_handoff=_adaptation_handoff,
            )
            if classification is not None:
                result["failure_classification"] = classification
        if _is_adaptation_build and _adaptation_surface_provenance is not None:
            canonical = build_adaptation_provenance(
                provenance=_adaptation_surface_provenance,
                adaptation_status=result.get("status"),
                module_slug=params.get("module_name"),
            )
            result.update(adaptation_provenance_surface_fields(canonical))
        if _adaptation_staging_target is None:
            return result
        desired_state = (
            STAGING_STATE_COMPLETED
            if result.get("status") == "success"
            else STAGING_STATE_FAILED
        )
        try:
            updated_target = update_adaptation_staging_target(
                _adaptation_staging_target,
                desired_state,
                error=str(result.get("error") or "") if desired_state == STAGING_STATE_FAILED else "",
            )
            _adaptation_staging_target.clear()
            _adaptation_staging_target.update(updated_target)
            result["staging_target"] = deepcopy(_adaptation_staging_target)
        except Exception as staging_error:
            result["staging_state_error"] = str(staging_error)
            result["staging_target"] = deepcopy(_adaptation_staging_target)
            if desired_state == STAGING_STATE_COMPLETED:
                result["status"] = "failed"
                result["error"] = "staging_completion_persist_failed"

        if _is_adaptation_build:
            # Keep both the canonical attempt artifact and the workspace
            # compatibility artifact current before any early return.  The
            # overwrite is scoped to this attempt/revision, not a prior one.
            try:
                _persist_adaptation_attempt_report(
                    workspace=Path(workspace),
                    job_id=job_id,
                    build_result=result,
                    adaptation_handoff=_adaptation_handoff or {},
                    staging_target=_adaptation_staging_target,
                    build_started_at=build_started_at,
                    overwrite=True,
                )
            except Exception as attempt_report_error:
                result["adaptation_attempt_report"] = {
                    "status": "not_persisted",
                    "reason": "attempt_report_persist_failed",
                }
            _persist_current_adaptation_build_result(Path(workspace), result)
        return result

    def _rerun_adaptation_revision(
        revision_target: Mapping[str, Any],
        accepted_operation: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Re-enter the same adaptation builder from normalization.

        This callback is intentionally Python-owned.  The accepted operation
        is carried as bounded in-memory input; the recursive build receives a
        fresh reserved target and therefore executes the ordinary adaptation
        normalization, materialization, closure, convergence, and gate order.
        """
        revised_provenance = deepcopy(
            dict(_adaptation_handoff.get("provenance", {}))
            if isinstance(_adaptation_handoff, Mapping)
            else {}
        )
        revised_provenance["revision_number"] = revision_target.get("revision_number")
        revised_provenance["stage"] = "normalization"
        revised_provenance["stage_id"] = revision_target.get("stage_id")

        target_identity = {
            key: revision_target.get(key)
            for key in (
                "attempt_id",
                "attempt_number",
                "revision_number",
                "source_hash",
                "stage_id",
                "module_slug",
                "path",
                "output_directory",
            )
        }

        def _accepted_round_callback(context: Mapping[str, Any]) -> Dict[str, Any]:
            return {
                "status": "success",
                **{
                    key: context.get(key)
                    for key in (
                        "attempt_id",
                        "attempt_number",
                        "revision_number",
                        "source_hash",
                    )
                },
                "staging_identity": dict(context.get("staging_identity") or target_identity),
            }

        return run_toolkit_homebrew_packet_build(
            Path(workspace),
            job_id,
            builder_executor=builder_executor,
            progress_callback=progress_callback,
            overwrite_confirmed=overwrite_confirmed,
            adaptation_route=ADAPTATION_MODE_LLM,
            adaptation_dossier=(
                _adaptation_handoff.get("dossier")
                if isinstance(_adaptation_handoff, Mapping)
                else adaptation_dossier
            ),
            adaptation_provenance=revised_provenance,
            adaptation_staging_root=adaptation_staging_root or DEFAULT_ADAPTATION_STAGING_ROOT,
            adaptation_staging_target=revision_target,
            adaptation_convergence_callback=_accepted_round_callback,
            adaptation_revision_callback=None,
            adaptation_finalization_operation=accepted_operation,
        )

    _v2_build_result: Optional[Dict[str, Any]] = None
    build_started_at: Optional[str] = None
    if _use_seed_writer:
        _v2_build_result = _execute_seed_writer_build(
            workspace, job_id, files, params, blueprint_artifact, progress_callback,
        )
        if _v2_build_result.get("status") != "success":
            return _v2_build_result

    # Handle blueprint required but not ready -- fail closed before executor
    if handoff_class == "blueprint_required_not_ready":
        bp_status = _describe_blueprint_not_ready(
            blueprint_artifact,
            blueprint_report_artifact,
        )
        return {
            "status": "failed",
            "stage": "build",
            "error": f"blueprint_not_ready:{bp_status}",
            "job_id": job_id,
            "blueprint_status": bp_status,
        }

    blueprint_metadata: Dict[str, Any] = {}

    if handoff_class in ("source_blueprint_ready", "source_blueprint_v2_ready") and blueprint_report_artifact:
        blueprint_metadata = {
            "handoff_mode": "source_blueprint",
            "blueprint_path": str(files.get("builder_blueprint", "")),
            "blueprint_status": "ready",
            "fidelity_status": str(blueprint_report_artifact.get("fidelity_status") or ""),
            "source_lock": {
                "canonical_names_locked": True,
                "invented_major_entities_forbidden": True,
                "replacement_plotlines_forbidden": True,
                "puzzle_rule_rewrite_forbidden": True,
            },
            "source_artifacts": {
                "source_graph": str(files.get("source_graph", "")),
                "identity_resolution_report": str(files.get("identity_resolution_report", "")),
                "plot_topology_report": str(files.get("plot_topology_report", "")),
                "normalization_fidelity_report": str(files.get("normalization_fidelity_report", "")),
            },
        }

    if not _use_seed_writer:
        narrative_bundle = _read_builder_narrative(files, packet, blueprint=blueprint_artifact)

        builder_input = {
            "status": "ready",
            "stage": "builder_input",
            "created_at": _utc_now_iso(),
            "job_id": job_id,
            "build_mode": _build_mode,
            "packet_identity": {
                "packet_version": packet.get("packet_version"),
                "source_hash": packet.get("source_hash"),
                "source_path": packet.get("source_path"),
                "title": packet.get("title"),
            },
            "review_snapshot": {
                "decision": review_snapshot.get("decision"),
                "recorded_at": review_snapshot.get("recorded_at"),
                "job_id": review_snapshot.get("job_id"),
            },
            "derived_builder_parameters": params,
            "builder_narrative_source": narrative_bundle["source"],
            "builder_narrative": narrative_bundle["narrative"],
        }
        if _is_adaptation_build:
            builder_input["llm_adaptation"] = deepcopy(_adaptation_handoff)
            builder_input["staging_target"] = deepcopy(_adaptation_staging_target)
            builder_input["world_context_provenance"] = deepcopy(
                _adaptation_handoff.get("provenance", {}).get("world_context_provenance", {})
            )
            if isinstance(adaptation_finalization_operation, Mapping):
                builder_input["accepted_finalization_operation"] = deepcopy(
                    dict(adaptation_finalization_operation)
                )
        if blueprint_metadata:
            builder_input["handoff_mode"] = "source_blueprint"
            builder_input["blueprint"] = blueprint_metadata

        # Source contract: carry source-fidelity tokens from the blueprint
        # so ModuleBuilder receives required NPCs, locations, puzzles, and tone
        # guidance without needing to re-read the blueprint file.
        if (
            not _is_adaptation_build
            and blueprint_metadata
            and isinstance(blueprint_artifact, dict)
            and blueprint_artifact
        ):
            _source_npc_names = [
                n.get("name") or n.get("display_name", "")
                for n in blueprint_artifact.get("npc_roster", [])
                if isinstance(n, dict) and (n.get("name") or n.get("display_name"))
            ]
            if _source_npc_names:
                builder_input["source_npc_names"] = _source_npc_names

            _source_location_names = [
                l.get("name") or l.get("display_name", "")
                for l in blueprint_artifact.get("location_roster", [])
                if isinstance(l, dict) and (l.get("name") or l.get("display_name"))
            ]
            if _source_location_names:
                builder_input["source_location_names"] = _source_location_names

            _source_puzzle_ids = [
                p.get("puzzle_id") or p.get("chain_id") or p.get("title", "")
                for p in blueprint_artifact.get("puzzle_graph", [])
                if isinstance(p, dict) and (p.get("puzzle_id") or p.get("chain_id") or p.get("title"))
            ]
            if _source_puzzle_ids:
                builder_input["source_puzzle_ids"] = _source_puzzle_ids

            _raw_tone = blueprint_artifact.get("tone_requirements")
            _source_tone: list = []
            if isinstance(_raw_tone, str) and _raw_tone.strip():
                _source_tone = [_raw_tone.strip()]
            elif isinstance(_raw_tone, list):
                _source_tone = [str(t) for t in _raw_tone if t]
            if _source_tone:
                builder_input["source_tone"] = _source_tone

        # Source monster refs / encounter seeds for source-enhanced ModuleBuilder
        # (packet-first, active for source-enhanced modes even without ready blueprint)
        if _build_mode in ("source_enhanced_modulebuilder", "source_blueprint_modulebuilder"):
            _source_blueprint = blueprint_artifact if isinstance(blueprint_artifact, dict) else {}
            _source_monster_refs = _merge_source_string_values(
                packet.get("monster_refs"),
                _source_blueprint.get("monster_refs"),
            )
            if _source_monster_refs:
                builder_input["source_monster_refs"] = _source_monster_refs

            _source_encounter_seeds = _merge_source_string_values(
                packet.get("encounter_seeds"),
                _source_blueprint.get("encounter_seeds"),
            )
            if _source_encounter_seeds:
                builder_input["source_encounter_seeds"] = _source_encounter_seeds

        if not persist_builder_input_artifact(workspace, builder_input):
            return _finish_adaptation_staging({
                "status": "failed",
                "stage": "build",
                "error": "builder_input_persist_failed",
                "job_id": job_id,
                "packet_identity": builder_input["packet_identity"],
                "staging_target": deepcopy(_adaptation_staging_target),
            })

        executor = builder_executor or _execute_module_builder
        build_started_at = _utc_now_iso()

        try:
            info(
                (
                    f"TOOLKIT_HOMEBREW: Starting packet-driven build job={job_id} "
                    f"module={params['module_name']}"
                ),
                category="web_interface",
            )
            try:
                if progress_callback:
                    executor(builder_input, progress_callback=progress_callback)
                else:
                    executor(builder_input)
            except TypeError as executor_error:
                if progress_callback and "unexpected keyword argument 'progress_callback'" in str(
                    executor_error
                ):
                    executor(builder_input)
                else:
                    raise

            build_result = {
                "status": "success",
                "stage": "build",
                "job_id": job_id,
                "build_mode": _build_mode,
                "completed_at": _utc_now_iso(),
                "build_started_at": build_started_at,
                "packet_identity": builder_input["packet_identity"],
                "module_name": params["module_name"],
                "output_directory": params["output_directory"],
                "builder_input_path": str(files["builder_input"]),
                "build_result_path": str(files["build_result"]),
                "staging_target": deepcopy(_adaptation_staging_target),
                **(
                    {"world_context_provenance": deepcopy(builder_input.get("world_context_provenance"))}
                    if _is_adaptation_build
                    else {}
                ),
            }
        except Exception as build_error:
            error(
                f"TOOLKIT_HOMEBREW: Packet-driven build failed for job={job_id}: {build_error}",
                exception=build_error,
                category="web_interface",
            )
            build_result = {
                "status": "failed",
                "stage": "build",
                "job_id": job_id,
                "build_mode": _build_mode,
                "completed_at": _utc_now_iso(),
                "build_started_at": build_started_at,
                "packet_identity": builder_input["packet_identity"],
                "module_name": params["module_name"],
                "output_directory": params["output_directory"],
                "builder_input_path": str(files["builder_input"]),
                "build_result_path": str(files["build_result"]),
                "error": str(build_error),
                "staging_target": deepcopy(_adaptation_staging_target),
                **(
                    {"world_context_provenance": deepcopy(builder_input.get("world_context_provenance"))}
                    if _is_adaptation_build
                    else {}
                ),
            }
            build_result = _finish_adaptation_staging(build_result)

    if _use_seed_writer:
        build_result = _v2_build_result  # type: ignore[assignment]
        build_result["build_mode"] = _build_mode
        if _seed_writer_mode:
            build_result["seed_writer_mode"] = _seed_writer_mode

    # TABLETOP MODE: Adaptation monster semantics must be resolved in the
    # active staging tree before the generic closure scans location data. The
    # guardrail is intentionally adaptation-only; its materializer defaults to
    # the existing bounded, provider-free generation policy.
    _module_name = params.get("module_name", "")
    _module_dir_str = str(Path(params["output_directory"]).resolve())
    _effective_adaptation_guardrail_input: Any = _adaptation_handoff or {}
    if _is_adaptation_build and _build_mode == ADAPTATION_MODE_LLM:
        try:
            from utils.toolkit_adaptation_monster_guardrail import (
                ADAPTATION_MONSTER_GUARDRAIL_REPORT_VERSION,
                DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS,
                _canonical_monster_slug,
                build_effective_adaptation_guardrail_input,
                normalize_adaptation_module_monsters,
            )

            # TABLETOP MODE: Reconcile only explicit source packet evidence
            # before guardrail evaluation.  The persisted dossier remains the
            # validated author contract; the effective input is in-memory and
            # its bounded provenance report is attached to build_result.
            _reconciliation = build_effective_adaptation_guardrail_input(
                _adaptation_handoff or {},
                source_packet=packet,
                builder_input=builder_input,
                accepted_finalization_operation=adaptation_finalization_operation,
            )
            _effective_adaptation_guardrail_input = _reconciliation.get(
                "effective_guardrail_input",
                _adaptation_handoff or {},
            )
            build_result["adaptation_monster_source_reconciliation"] = deepcopy(
                _reconciliation.get("reconciliation_report", {})
            )

            # Normalize generated location.monsters before materialization so
            # every structural identity is present in the staging tree before
            # the final no-generation closure pass.
            _canonical_registry = build_adaptation_canonical_monster_registry(
                _effective_adaptation_guardrail_input,
                source_packet=packet,
                builder_input=builder_input,
                module_dir=_module_dir_str,
                staging_root=_module_dir_str,
                reusable_module_dirs=_adaptation_reusable_roots(
                    _effective_adaptation_guardrail_input
                ),
            )
            build_result["adaptation_monster_canonical_registry"] = {
                "version": _canonical_registry.get("version"),
                "status": _canonical_registry.get("status"),
                "approved_identities": list(_canonical_registry.get("approved_identities", []))[:128],
            }
            _normalization_report = normalize_adaptation_module_monsters(
                _module_dir_str,
                _effective_adaptation_guardrail_input,
                canonical_registry=_canonical_registry,
            )
            build_result["adaptation_monster_normalization"] = {
                key: deepcopy(value)
                for key, value in dict(_normalization_report).items()
                if key in {
                    "version", "status", "areas_scanned", "locations_scanned",
                    "entries_seen", "normalized_refs", "excluded_entries",
                    "unresolved_entries", "diagnostics", "files_changed",
                }
            }
            if str(_normalization_report.get("status") or "").lower() == "blocked":
                build_result["status"] = "blocked"
                build_result["stage"] = "adaptation_monster_normalization"
                build_result["error"] = "adaptation_monster_normalization_blocked"
                return _finish_adaptation_staging(build_result)

            # Build one stable Python-owned approval set for both the provider
            # context and materializer.  Dossier encounter adversaries are
            # authoritative and precede canonical identities normalized from
            # staged location.monsters.  Advisory normalized_packet.monster_refs
            # never enter this set because they were excluded by source
            # reconciliation above.
            _approved_canonical_identities: list = []
            _approved_canonical_slugs = set()
            _effective_dossier = (
                _effective_adaptation_guardrail_input.get("dossier")
                if isinstance(_effective_adaptation_guardrail_input, Mapping)
                and isinstance(
                    _effective_adaptation_guardrail_input.get("dossier"), Mapping
                )
                else _effective_adaptation_guardrail_input
            )
            _effective_seeds = (
                _effective_dossier.get("encounter_seeds", [])
                if isinstance(_effective_dossier, Mapping)
                else []
            )
            if isinstance(_effective_seeds, list):
                for _seed in _effective_seeds[:128]:
                    if not isinstance(_seed, Mapping):
                        continue
                    _seed_adversaries = _seed.get("adversaries", [])
                    if not isinstance(_seed_adversaries, list):
                        continue
                    for _identity in _seed_adversaries[:16]:
                        if not isinstance(_identity, str) or not _identity.strip():
                            continue
                        _identity = _identity.strip()
                        _identity_slug = _canonical_monster_slug(_identity)
                        if _identity_slug and _identity_slug not in _approved_canonical_slugs:
                            _approved_canonical_identities.append(_identity)
                            _approved_canonical_slugs.add(_identity_slug)
            for _identity in _normalization_report.get("normalized_refs", [])[:128]:
                if not isinstance(_identity, str) or not _identity.strip():
                    continue
                _identity_slug = _canonical_monster_slug(_identity)
                if _identity_slug and _identity_slug not in _approved_canonical_slugs:
                    _approved_canonical_identities.append(_identity.strip())
                    _approved_canonical_slugs.add(_identity_slug)
            _approved_canonical_identities = _approved_canonical_identities[:128]

            _adaptation_monster_builder_path = str(
                Path(__file__).resolve().parents[2]
                / "core"
                / "generators"
                / "monster_builder.py"
            )
            _explicit_generation_opt_in = bool(
                isinstance(_effective_adaptation_guardrail_input, Mapping)
                and isinstance(
                    _effective_adaptation_guardrail_input.get("provenance"), Mapping
                )
                and _effective_adaptation_guardrail_input["provenance"].get(
                    "allow_canonical_monster_generation"
                ) is True
            )
            # Validate the persisted staging marker immediately before the
            # generation seam.  The in-memory handoff may describe an older
            # state, so it is not sufficient for authorization.
            # The legacy envelope check (_adaptation_staging_target.get("completion_state")
            # == STAGING_STATE_BUILDING) remains documentary compatibility only;
            # the validated on-disk marker below is authoritative.
            _generation_gate_reason = None
            _validated_generation_target = None
            try:
                if not isinstance(_adaptation_staging_target, Mapping):
                    raise ValueError("staging target metadata is missing")
                _validated_generation_target = validate_adaptation_staging_target(
                    _adaptation_staging_target,
                    require_reserved=False,
                )
                if _validated_generation_target.get("completion_state") != STAGING_STATE_BUILDING:
                    _generation_gate_reason = "inactive_staging_target"
            except Exception:
                _generation_gate_reason = "invalid_staging_target"
            _allow_adaptation_generation = bool(
                _explicit_generation_opt_in
                and _generation_gate_reason is None
                and isinstance(_validated_generation_target, Mapping)
                and _validated_generation_target.get("completion_state")
                == STAGING_STATE_BUILDING
            )
            _guardrail_report = _run_adaptation_monster_guardrail(
                _effective_adaptation_guardrail_input,
                module_dir=_module_dir_str,
                staging_root=_module_dir_str,
                reusable_module_dirs=_adaptation_reusable_roots(
                    _effective_adaptation_guardrail_input
                ),
                # Adaptation's pre-existing closure path permits canonical
                # missing-monster generation. Keep that policy explicit while
                # the guardrail enforces reuse-first and staging-only writes.
                allow_generation=_allow_adaptation_generation,
                generation_opt_in=_explicit_generation_opt_in,
                generation_gate_reason=_generation_gate_reason,
                monster_builder_path=_adaptation_monster_builder_path,
                generation_timeout_seconds=DEFAULT_MONSTER_GENERATION_TIMEOUT_SECONDS,
                additional_canonical_refs=_normalization_report.get(
                    "normalized_refs", []
                ),
                generation_context={
                    "approved_identities": list(_approved_canonical_identities),
                    **_adaptation_generation_context(
                        _effective_adaptation_guardrail_input,
                        _approved_canonical_identities,
                    ),
                },
                # Python owns the approved identity set; the provider seam
                # cannot generate a reference that normalization did not
                # approve for this staging revision.
                approved_canonical_refs=_approved_canonical_identities,
            )
            if not isinstance(_guardrail_report, Mapping):
                _guardrail_report = {
                    "version": ADAPTATION_MONSTER_GUARDRAIL_REPORT_VERSION,
                    "report_version": ADAPTATION_MONSTER_GUARDRAIL_REPORT_VERSION,
                    "status": "blocked",
                    "diagnostics": [
                        {
                            "code": "invalid_guardrail_report",
                            "message": "adaptation monster guardrail returned an invalid report",
                        }
                    ],
                }
            _guardrail_report_keys = {
                "version",
                "report_version",
                "status",
                "adversaries",
                "adversaries_planned",
                "monsters_planned",
                "monsters_reused",
                 "monsters_generated",
                 "monsters_unresolved",
                 "monsters_excluded",
                 "encounters_planned",
                 "encounters_bound",
                 "encounters_scene_resolved",
                 "encounters_unresolved",
                "encounters_unbound",
                 "unresolved_refs",
                 "non_monster_refs",
                "unresolved_diagnostics",
                "encounter_bindings",
                "resolution_diagnostics",
                 "diagnostics",
                 "generation_policy",
            }
            build_result["adaptation_monster_guardrail"] = {
                key: deepcopy(value)
                for key, value in dict(_guardrail_report).items()
                if key in _guardrail_report_keys
            }
            build_result["adaptation_monster_materialization"] = {
                key: deepcopy(value)
                for key, value in dict(_guardrail_report).items()
                if key in {
                    "status", "monsters_planned", "monsters_reused",
                     "monsters_generated", "monsters_unresolved",
                     "monsters_excluded",
                     "encounters_scene_resolved",
                     "unresolved_refs", "non_monster_refs", "unresolved_diagnostics", "diagnostics",
                     "resolution_diagnostics", "artifact_paths",
                     "generation_policy",
                 }
            }
            # Keep an explicit, bounded post-normalization report name for
            # adaptation consumers.  The existing materialization key remains
            # for compatibility with earlier staging/report readers.
            build_result["adaptation_monster_post_normalization_materialization"] = deepcopy(
                build_result["adaptation_monster_materialization"]
            )

            _guardrail_status = str(
                _guardrail_report.get("status") or ""
            ).strip().lower()
            _guardrail_unresolved = bool(
                _guardrail_report.get("unresolved_refs")
            )
            for _count_key in (
                "monsters_unresolved",
                "encounters_unresolved",
                "encounters_unbound",
            ):
                try:
                    _guardrail_unresolved = _guardrail_unresolved or int(
                        _guardrail_report.get(_count_key, 0) or 0
                    ) > 0
                except (TypeError, ValueError):
                    _guardrail_unresolved = True

            if _guardrail_status in {"blocked", "unresolved"} or _guardrail_unresolved:
                build_result["status"] = "blocked"
                build_result["stage"] = "adaptation_monster_guardrail"
                build_result["error"] = "adaptation_monster_guardrail_unresolved"
                build_result["max_revisions"] = normalize_adaptation_revision_limit()
                build_result["revision_eligible"] = True
                classification = _adaptation_failure_classification(
                    build_result, adaptation_handoff=_adaptation_handoff
                ) or {}
                if classification.get("revision_eligible") is True:
                    routed = _route_adaptation_monster_revision(
                        build_result=build_result,
                        guardrail_report=_guardrail_report,
                        classification=classification,
                        adaptation_handoff=_adaptation_handoff or {},
                        staging_target=_adaptation_staging_target or {},
                        workspace=Path(workspace),
                        job_id=job_id,
                        staging_root=adaptation_staging_root or DEFAULT_ADAPTATION_STAGING_ROOT,
                        module_slug=str(params.get("module_name") or "Adapted_Module"),
                        revision_callback=adaptation_revision_callback or adaptation_convergence_callback,
                        rerun_callback=_rerun_adaptation_revision,
                    )
                    if routed is not None:
                        if isinstance(routed.get("adaptation_revision"), Mapping) and routed["adaptation_revision"].get("full_pipeline_rerun"):
                            return routed
                        return _finish_adaptation_staging(routed)
                return _finish_adaptation_staging(build_result)
        except Exception as guardrail_error:
            warning(
                f"TOOLKIT_HOMEBREW: Adaptation monster guardrail failed: {guardrail_error}",
                category="web_interface",
            )
            build_result["adaptation_monster_guardrail"] = {
                "version": "toolkit_adaptation_monster_guardrail.v1",
                "report_version": "toolkit_adaptation_monster_guardrail.v1",
                "status": "blocked",
                "diagnostics": [
                    {
                        "code": "guardrail_exception",
                        "message": "adaptation monster guardrail could not complete",
                    }
                ],
            }
            build_result["status"] = "blocked"
            build_result["stage"] = "adaptation_monster_guardrail"
            build_result["error"] = "adaptation_monster_guardrail_exception"
            return _finish_adaptation_staging(build_result)

    # TABLETOP MODE: Run monster reference closure as the final adaptation
    # consistency check after guardrail materialization and normalization.
    # Adaptation closure must inspect only the staged result and never invoke
    # the legacy prose-to-stat-block generation path. Legacy callers retain
    # the existing default generation behavior.
    try:
        from utils.monster_reference_closure import (  # type: ignore[import-untyped]
            ensure_monster_reference_closure,
        )
        if _is_adaptation_build and _build_mode == ADAPTATION_MODE_LLM:
            _closure_report = ensure_monster_reference_closure(
                _module_name,
                _module_dir_str,
                allow_generation=False,
            )
        else:
            _closure_report = ensure_monster_reference_closure(
                _module_name,
                _module_dir_str,
            )
        build_result["monster_closure"] = {
            "required": _closure_report.get("required", 0),
            "existing_before": _closure_report.get("existing_before", 0),
            "generated": _closure_report.get("generated", 0),
            "unresolved": _closure_report.get("unresolved", 0),
            "ambiguous_npc_like": _closure_report.get("ambiguous_npc_like", []),
            "report_path": str(Path(_module_dir_str) / "monster_closure_report.json"),
        }
        if _closure_report.get("unresolved", 0) > 0:
            # Initial source-grounded closure failures are eligible for the
            # bounded adaptation finalization seam. Hard materialization
            # failures continue through the terminal path below.
            build_result["status"] = "blocked"
            build_result["stage"] = "monster_closure"
            build_result["error"] = (
                f"monster_closure_unresolved:{_closure_report['unresolved']} "
                f"unresolved monster reference(s)"
            )
            build_result["max_revisions"] = normalize_adaptation_revision_limit()
            build_result["revision_eligible"] = True
            classification = _adaptation_failure_classification(
                build_result, adaptation_handoff=_adaptation_handoff
            ) or {}
            if classification.get("revision_eligible") is True:
                routed = _route_adaptation_monster_revision(
                    build_result=build_result,
                    guardrail_report=_closure_report,
                    classification=classification,
                    adaptation_handoff=_adaptation_handoff or {},
                    staging_target=_adaptation_staging_target or {},
                    workspace=Path(workspace),
                    job_id=job_id,
                    staging_root=adaptation_staging_root or DEFAULT_ADAPTATION_STAGING_ROOT,
                    module_slug=str(params.get("module_name") or "Adapted_Module"),
                        revision_callback=adaptation_revision_callback or adaptation_convergence_callback,
                        rerun_callback=_rerun_adaptation_revision,
                )
                if routed is not None:
                    if isinstance(routed.get("adaptation_revision"), Mapping) and routed["adaptation_revision"].get("full_pipeline_rerun"):
                        return routed
                    return _finish_adaptation_staging(routed)
            info(
                f"TOOLKIT_HOMEBREW: Monster closure blocked build with "
                f"{_closure_report['unresolved']} unresolved references",
                category="web_interface",
            )
            return _finish_adaptation_staging(build_result)
    except Exception as e:
        warning(
            f"TOOLKIT_HOMEBREW: Monster closure exception: {e}",
            category="web_interface",
        )
        # Fail open: if closure itself crashes, let fidelity gates proceed.
        # The validator will catch missing monsters as reference_integrity
        # failures.

    # TABLETOP MODE: Run spatial repair after monster closure, before fidelity gates.
    # Recomputes coordinates, cardinal adjacency, map links, and area
    # connectivity to ensure spatial contract compliance before validation.
    try:
        from utils.spatial_repair import repair_module_spatial
        _spatial_report = repair_module_spatial(_module_dir_str)
        build_result["spatial_repair"] = {
            "status": _spatial_report.get("status", "unknown"),
            "input_location_count": _spatial_report.get("input_location_count", 0),
            "repaired_area_count": _spatial_report.get("repaired_area_count", 0),
            "edge_count": _spatial_report.get("edge_count", 0),
            "unresolved_count": _spatial_report.get("unresolved_count", 0),
            "report_path": str(Path(_module_dir_str) / "spatial_repair_report.json"),
        }
        if _spatial_report.get("status") == "failed":
            # Spatial repair failed -> structural fatal blocker.
            build_result["status"] = "blocked"
            build_result["stage"] = "spatial_repair"
            build_result["error"] = (
                f"spatial_repair_failed:{_spatial_report.get('unresolved_count', 0)} "
                f"unresolved spatial issue(s)"
            )
            info(
                f"TOOLKIT_HOMEBREW: Spatial repair blocked build with "
                f"{_spatial_report.get('unresolved_count', 0)} unresolved issues",
                category="web_interface",
            )
            return _finish_adaptation_staging(build_result)
    except Exception as e:
        warning(
            f"TOOLKIT_HOMEBREW: Spatial repair exception: {e}",
            category="web_interface",
        )
        # Fail open: if repair itself crashes, let fidelity gates proceed.
        # The validator will catch spatial contract failures.

    # TABLETOP MODE: Run calendar normalization after spatial repair, before fidelity gates.
    # Normalizes party_tracker_BU.json calendar values to schema-valid months.
    try:
        from utils.calendar_normalization import normalize_party_calendar
        _calendar_report = normalize_party_calendar(_module_dir_str)
        build_result["calendar_normalization"] = {
            "status": _calendar_report.get("status", "unknown"),
            "month_before": _calendar_report.get("month_before", ""),
            "month_after": _calendar_report.get("month_after", ""),
            "reason": _calendar_report.get("reason", ""),
        }
        if _calendar_report.get("status") == "failed":
            build_result["status"] = "blocked"
            build_result["stage"] = "calendar_normalization"
            build_result["error"] = (
                f"calendar_normalization_failed:{_calendar_report.get('reason', 'unknown')}"
            )
            info(
                f"TOOLKIT_HOMEBREW: Calendar normalization blocked build: "
                f"{_calendar_report.get('reason', 'unknown')}",
                category="web_interface",
            )
            return _finish_adaptation_staging(build_result)
    except Exception as e:
        warning(
            f"TOOLKIT_HOMEBREW: Calendar normalization exception: {e}",
            category="web_interface",
        )
        # Fail open: validator catches invalid months as party failures.

    # TABLETOP MODE: Run build fidelity gates before finishing/publication
    _fidelity_required = False
    _fidelity_inputs_present = bool(
        (files.get("source_graph") and files["source_graph"].exists())
        or (files.get("builder_blueprint") and files["builder_blueprint"].exists())
    )
    try:
        from utils.toolkit_build_fidelity import (
            is_build_fidelity_required,
            build_build_fidelity_report,
            can_continue_after_build_fidelity,
            build_source_fidelity_rollup,
        )

        _fidelity_required = is_build_fidelity_required(workspace)
        if _fidelity_required:
            module_dir = Path(params["output_directory"]).resolve()
            fidelity_report = build_build_fidelity_report(
                workspace, module_dir, build_mode=_build_mode
            )
            persist_build_fidelity_report_artifact(workspace, fidelity_report)
            rollup = build_source_fidelity_rollup(workspace, fidelity_report)
            persist_source_fidelity_report_artifact(workspace, rollup)

            can_continue, refusal = can_continue_after_build_fidelity(fidelity_report)
            build_result["build_fidelity"] = {
                "status": fidelity_report.get("status"),
                "blocker_count": len(fidelity_report.get("blockers") or []),
                "warning_count": len(fidelity_report.get("warnings") or []),
                "can_continue": can_continue,
                "refusal_reason": refusal,
                "report_path": str(files["build_fidelity_report"]),
                "rollup_path": str(files["source_fidelity_report"]),
                "coverage": fidelity_report.get("coverage"),
            }

            # Adaptation is explicitly non-literal: preserve the complete
            # build-fidelity evidence, but do not route editorial mismatches
            # through the accurate-ingest final editor.  This branch is
            # intentionally narrow and runs only after the provider-free
            # classifier has separated editorial evidence from fatal blockers.
            _adaptation_fidelity_boundary = False

            # Step 4.1: attach final blocker classification metadata
            if not can_continue:
                try:
                    from utils.toolkit_final_blocker_classifier import (
                        classify_final_build_blockers,
                    )
                    classification = classify_final_build_blockers(
                        fidelity_report, module_dir=module_dir,
                    )
                except Exception:
                    classification = {
                        "status": "unknown",
                        "fatal_blockers": [],
                        "editorial_blockers": [],
                        "warnings": [{
                            "type": "classification_failed",
                            "message": "classify_final_build_blockers raised exception",
                            "category": "input_validation",
                        }],
                        "can_attempt_final_reconciliation": False,
                        "fatal_count": 0,
                        "editorial_count": 0,
                        "original_refusal_reason": "",
                        "report_paths": {},
                    }
                build_result["final_blocker_classification"] = classification
                build_result["build_fidelity"]["final_blocker_classification_status"] = classification.get("status", "unknown")

                if _is_adaptation_build and _build_mode == ADAPTATION_MODE_LLM:
                    _boundary = _apply_adaptation_fidelity_boundary(
                        workspace=Path(workspace),
                        fidelity_report=fidelity_report,
                        classification=classification,
                        adaptation_provenance=_adaptation_surface_provenance,
                        staging_target=_adaptation_staging_target,
                        module_slug=str(params.get("module_name") or ""),
                    )
                    build_result["adaptation_fidelity_boundary"] = {
                        key: deepcopy(value)
                        for key, value in _boundary.items()
                        if key != "report"
                    }
                    if isinstance(_boundary.get("report"), Mapping):
                        build_result["adaptation_source_fidelity"] = deepcopy(
                            _boundary["report"]
                        )
                    if _boundary.get("eligible") is True:
                        _adaptation_fidelity_boundary = True
                        can_continue = True
                        refusal = ""
                        build_result["build_fidelity"]["can_continue"] = True
                        build_result["build_fidelity"]["source_fidelity_status"] = "not_applicable"
                        build_result["build_fidelity"]["source_fidelity_effective_status"] = "not_applicable"
                        build_result["build_fidelity"]["literal_mismatch_evidence_retained"] = True
                        build_result["source_fidelity_status"] = "not_applicable"
                        build_result["source_fidelity_effective_status"] = "not_applicable"

            if not can_continue:
                _cls_status = classification.get("status", "unknown")
                _is_final_reconciliation = False

                # Step 4.3: editorial-only -> reconciliation required, not terminal block
                if _cls_status == "editorial" and not _adaptation_fidelity_boundary:
                    try:
                        from utils.toolkit_final_reconciliation import (
                            build_final_reconciliation_brief,
                            is_final_reconciliation_accepted,
                            load_final_reconciliation_report,
                            should_persist_final_reconciliation_brief,
                            persist_final_reconciliation_brief,
                        )
                    except Exception:
                        build_result["status"] = "blocked"
                        build_result["stage"] = "final_reconciliation"
                        build_result["error"] = "final_reconciliation_brief_persist_failed:import_error"
                        info(
                            f"TOOLKIT_HOMEBREW: Reconciliation brief import failed job={job_id}",
                            category="web_interface",
                        )
                        return _finish_adaptation_staging(build_result)

                    if should_persist_final_reconciliation_brief(classification):
                        module_name = params["module_name"]

                        # TABLETOP MODE: Load source graph for brief evidence enrichment.
                        # Fail-open: missing/malformed source graph does not block brief.
                        _source_graph: Optional[Dict[str, Any]] = None
                        try:
                            _sg_path = files.get("source_graph")
                            if _sg_path is not None and _sg_path.exists():
                                _loaded = load_json_artifact(_sg_path)
                                if isinstance(_loaded, dict):
                                    _source_graph = _loaded
                        except Exception:
                            pass

                        brief = build_final_reconciliation_brief(
                            classification,
                            job_id=job_id,
                            module_name=module_name,
                            module_dir=module_dir,
                            source_graph=_source_graph,
                        )

                        # Step 4.4: check for accepted reconciliation report before pausing
                        _accepted_report = load_final_reconciliation_report(workspace)
                        if _accepted_report is not None and is_final_reconciliation_accepted(_accepted_report):
                            build_result["final_reconciliation_accepted"] = True
                            build_result["final_reconciliation"] = _accepted_report
                            build_result["source_fidelity_effective_status"] = "reconciled_degraded"
                            build_result["build_fidelity"]["final_reconciliation_accepted"] = True
                            build_result["build_fidelity"]["source_fidelity_effective_status"] = "reconciled_degraded"
                            _is_final_reconciliation = True
                            info(
                                f"TOOLKIT_HOMEBREW: Final reconciliation accepted job={job_id} "
                                f"module={module_name}",
                                category="web_interface",
                            )
                            # Continue to normal build_result persistence
                        else:
                            persist_result = persist_final_reconciliation_brief(workspace, brief)

                            if persist_result["status"] != "written":
                                build_result["status"] = "blocked"
                                build_result["stage"] = "final_reconciliation"
                                build_result["error"] = f"final_reconciliation_brief_persist_failed:{persist_result.get('error', 'unknown')}"
                                info(
                                    f"TOOLKIT_HOMEBREW: Reconciliation brief persist failed job={job_id}",
                                    category="web_interface",
                                )
                                return _finish_adaptation_staging(build_result)

                            # Step 5.1: invoke the LLM Builder final editor pipeline.
                            # The editor consumes the freshly persisted brief and either
                            # accepts the reconciliation (persists an accepted report and
                            # sets reconciled_degraded metadata) or fails closed with a
                            # blocked state and diagnostics. Falls back to the legacy
                            # final_reconciliation_required pause only if the helper API
                            # itself is unavailable (per task 5.1 step 6).
                            _editor_accepted = _invoke_final_editor_or_fallback(
                                build_result=build_result,
                                brief=brief,
                                module_dir=module_dir,
                                workspace=workspace,
                                job_id=job_id,
                                module_name=module_name,
                                brief_persist_result=persist_result,
                                classification=classification,
                            )
                            if _editor_accepted:
                                # Step 5.2 gate: editor accepted and persisted
                                # -> accepted metadata is now on build_result
                                # (final_reconciliation_accepted=True and
                                #  source_fidelity_effective_status="reconciled_degraded")
                                # AND build_result["status"] is still "success"
                                # (helper did NOT mutate it on the accepted path).
                                # The route layer's build_status == "success"
                                # branch will launch readiness/finisher, and the
                                # finisher will load the persisted accepted
                                # report from module_dir via the legacy
                                # ``is_final_reconciliation_accepted`` oracle.
                                _is_final_reconciliation = True
                                # Continue to normal build_result persistence
                            else:
                                # Either the editor was unavailable and we fell back
                                # to final_reconciliation_required, or the editor
                                # returned non-accepted and the helper already set
                                # build_result to blocked / required. Honor the
                                # helper's verdict in both cases.
                                # In BOTH sub-paths the helper mutates
                                # build_result["status"]:
                                #   - "blocked"           -> route layer returns
                                #     before reaching the build_status == "success"
                                #     branch.
                                #   - "final_reconciliation_required" -> route
                                #     layer returns at the dedicated branch
                                #     before reaching the success branch.
                                # In neither sub-path does the build reach
                                # readiness/finisher. The Step 5.2 gate is
                                # therefore: build_status == "success" is the
                                # only signal that readiness/finisher may run.
                                _is_final_reconciliation = True
                                _resolved_status = build_result.get("status")
                                if _resolved_status == "blocked":
                                    # Non-accepted or persist failure path: stop here.
                                    return _finish_adaptation_staging(build_result)
                                # Legacy fallback path (final_reconciliation_required):
                                # fall through to normal build_result persistence.

                # Step 4.2 + Step 5.3: fatal/mixed/unknown -> terminal block.
                # The final editor (and the helper that invokes it) is reached
                # ONLY through the `if _cls_status == "editorial":` branch
                # above; this guard catches everything else and keeps the
                # build blocked at the build_fidelity layer with no editor
                # invocation and no reconciliation fields set.
                if not _is_final_reconciliation:
                    build_result["status"] = "blocked"
                    build_result["stage"] = "build_fidelity"
                    build_result["error"] = f"build_fidelity_blocked:{refusal}"
                    info(
                        (
                            f"TOOLKIT_HOMEBREW: Build fidelity blocked job={job_id} "
                            f"module={params['module_name']} reason={refusal}"
                        ),
                        category="web_interface",
                    )
    except Exception as build_fidelity_error:
        if _fidelity_required or _fidelity_inputs_present:
            module_dir = Path(params["output_directory"]).resolve()
            error(
                f"TOOLKIT_HOMEBREW: Build fidelity audit failed for job={job_id}: {build_fidelity_error}",
                exception=build_fidelity_error,
                category="web_interface",
            )
            _fallback_report = {
                "version": 1,
                "status": "failed",
                "module_path": str(module_dir),
                "source_artifacts": {
                    "source_graph": str(files.get("source_graph", "")),
                    "builder_blueprint": str(files.get("builder_blueprint", "")),
                    "builder_blueprint_report": str(files.get("builder_blueprint_report", "")),
                    "normalized_packet": str(files.get("normalized_packet", "")),
                    "module_dir": str(module_dir),
                },
                "blockers": [
                    {
                        "category": "build_fidelity",
                        "message": f"Build fidelity audit failed: {build_fidelity_error}",
                    }
                ],
                "warnings": [],
                "can_continue": False,
                "refusal_reason": f"build_fidelity_audit_error:{build_fidelity_error}",
                "coverage": {},
                "stage_results": {},
            }
            persist_build_fidelity_report_artifact(workspace, _fallback_report)
            build_result["build_fidelity"] = {
                "status": "failed",
                "blocker_count": len(_fallback_report.get("blockers") or []),
                "warning_count": 0,
                "can_continue": False,
                "refusal_reason": str(build_fidelity_error),
                "report_path": str(files["build_fidelity_report"]),
                "rollup_path": str(files["source_fidelity_report"]),
                "coverage": _fallback_report.get("coverage"),
            }
            build_result["status"] = "blocked"
            build_result["stage"] = "build_fidelity"
            build_result["error"] = f"build_fidelity_audit_error:{build_fidelity_error}"
        else:
            warning(
                f"TOOLKIT_HOMEBREW: Build fidelity audit failed for job={job_id}: {build_fidelity_error}",
                category="web_interface",
            )

    # TABLETOP MODE: Generate narrative enrichment plan artifact (default profile "none")
    # Skipped for v2 builds (enrichment already handled in seed writer path)
    if not _use_seed_writer:
        try:
            from utils.toolkit_narrative_enrichment_plan import build_enrichment_plan

            enrichment_plan = build_enrichment_plan(
                build_result=build_result,
                profile="none",
                report_path=files.get("build_fidelity_report"),
                rollup_path=files.get("source_fidelity_report"),
            )
            persist_narrative_enrichment_plan_artifact(workspace, enrichment_plan)
            build_result["narrative_enrichment_plan"] = {
                "status": enrichment_plan.get("status"),
                "profile": enrichment_plan.get("profile"),
                "blocker_count": len(enrichment_plan.get("blockers") or []),
                "warning_count": len(enrichment_plan.get("warnings") or []),
            }
        except Exception as enrichment_error:
            warning(
                f"TOOLKIT_HOMEBREW: Narrative enrichment plan generation failed with default profile: {enrichment_error}",
                category="web_interface",
            )

    _adaptation_attempt_artifact: Optional[Dict[str, Any]] = None
    if _is_adaptation_build:
        try:
            _adaptation_attempt_artifact = _persist_adaptation_attempt_report(
                workspace=Path(workspace),
                job_id=job_id,
                build_result=build_result,
                adaptation_handoff=_adaptation_handoff or {},
                staging_target=_adaptation_staging_target,
                build_started_at=build_started_at,
            )
        except Exception as attempt_report_error:
            build_result["adaptation_attempt_report"] = {
                "status": "not_persisted",
                "reason": "attempt_report_persist_failed",
            }

    # TABLETOP MODE: Finalize the Python-owned continuity contract before any
    # convergence, readiness, gameplay, or publishability gate consumes the
    # adaptation staging build.  This repair is deterministic and does not
    # consume the bounded LLM revision budget.
    _adaptation_continuity_result: Optional[Dict[str, Any]] = None
    if _is_adaptation_build and build_result.get("status") == "success":
        try:
            validated_continuity_target = validate_adaptation_staging_target(
                _adaptation_staging_target,
                repo_root=Path.cwd(),
                require_reserved=False,
            )
            continuity_path = (
                Path.cwd() / str(validated_continuity_target["path"])
            ).resolve()
            output_path = Path(params["output_directory"]).resolve()
            if continuity_path != output_path:
                raise ValueError("continuity target does not match staging output")
            _adaptation_continuity_result = _finalize_adaptation_continuity(
                continuity_path,
                str(params.get("module_name") or "Adaptation"),
            )
        except Exception:
            _adaptation_continuity_result = {
                "status": "failed",
                "reason_code": "adaptation_continuity_finalization_failed",
                "errors": ["adaptation_continuity_staging_target_invalid"],
            }
        build_result["adaptation_continuity_finalization"] = {
            key: _adaptation_continuity_result.get(key)
            for key in (
                "status", "reason_code", "changed", "injected_keys", "errors"
            )
            if key in _adaptation_continuity_result
        }
        if _adaptation_continuity_result.get("status") != "success":
            continuity_provenance = (
                _adaptation_handoff.get("provenance", {})
                if isinstance(_adaptation_handoff, Mapping)
                else {}
            )
            continuity_classification = classify_adaptation_failure(
                {
                    "failure_class": FAILURE_CLASS_FILE,
                    "code": "adaptation_continuity_finalization_failed",
                    "message": "Python-owned continuity metadata could not be finalized",
                    "failure_kind": "hard",
                    "terminal": True,
                },
                attempt_metadata=(
                    continuity_provenance
                    if isinstance(continuity_provenance, Mapping)
                    else {}
                ),
                revision_number=_adaptation_staging_target.get("revision_number", 0),
                stage="adaptation_continuity_finalization",
                domain="readiness",
                revision_eligible=False,
                max_revisions=normalize_adaptation_revision_limit(),
            )
            build_result.update(
                {
                    "status": "blocked",
                    "stage": "adaptation_continuity_finalization",
                    "error": _adaptation_continuity_result.get(
                        "reason_code", "adaptation_continuity_finalization_failed"
                    ),
                    "failure_class": FAILURE_CLASS_FILE,
                    "failure_code": "adaptation_continuity_finalization_failed",
                    "failure_domain": "readiness",
                    "revision_eligible": False,
                    "next_revision_eligible": False,
                    "semantic_revision_eligible": False,
                    "semantic_revision_budget_consumed": False,
                    "failure_diagnostics": [
                        {
                            "code": "adaptation_continuity_finalization_failed",
                            "message": "Python-owned continuity metadata could not be finalized",
                        }
                    ],
                    "failure_classification": continuity_classification,
                }
            )

    # TABLETOP MODE: Convergence is the adaptation-only boundary before any
    # readiness, gameplay, or publishability gate consumes the staging build.
    _adaptation_convergence_result: Optional[Dict[str, Any]] = None
    if _is_adaptation_build and build_result.get("status") == "success":
        try:
            from utils.toolkit_adaptation_publication_convergence import (
                prepare_adaptation_repair_context,
                run_adaptation_publication_convergence,
            )

            # TABLETOP MODE: Prepare and forward only the bounded staged
            # repair context. Legacy builds never enter this boundary.
            _adaptation_repair_context = prepare_adaptation_repair_context(
                workspace=Path(workspace),
                staged_module_path=Path(params["output_directory"]).resolve(),
                module_slug=str(_adaptation_staging_target.get("module_slug") or ""),
                attempt={
                    "attempt_id": str(_adaptation_staging_target.get("attempt_id") or ""),
                    "attempt_number": int(_adaptation_staging_target.get("attempt_number", 0)),
                    "revision_number": int(_adaptation_staging_target.get("revision_number", 0)),
                    "source_hash": str(_adaptation_staging_target.get("source_hash") or ""),
                },
                repo_root=Path.cwd(),
            )
            build_result["adaptation_repair_context"] = {
                key: _adaptation_repair_context.get(key)
                for key in (
                    "status", "reason_code", "identity", "validation_context",
                    "diagnostics",
                )
                if key in _adaptation_repair_context
            }
            _adaptation_convergence_result = run_adaptation_publication_convergence(
                str(Path(params["output_directory"]).resolve()),
                mode=_build_mode,
                attempt_id=str(_adaptation_staging_target.get("attempt_id") or ""),
                attempt_number=int(_adaptation_staging_target.get("attempt_number", 0)),
                revision_number=int(_adaptation_staging_target.get("revision_number", 0)),
                source_hash=str(_adaptation_staging_target.get("source_hash") or ""),
                validation_context=(
                    _adaptation_repair_context.get("validation_context")
                    if _adaptation_repair_context.get("status") == "repairable"
                    else None
                ),
                provider_callback=adaptation_convergence_callback,
                repo_root=Path.cwd(),
            )
            build_result["adaptation_convergence"] = {
                key: _adaptation_convergence_result.get(key)
                for key in (
                    "status", "reason_code", "attempt_id", "attempt_number",
                    "revision_number", "source_hash", "report_path",
                    "next_revision_eligible",
                )
            }
            if _adaptation_convergence_result.get("status") != "ready":
                build_result["status"] = "blocked"
                build_result["stage"] = "adaptation_convergence"
                build_result["error"] = "adaptation_convergence_blocked"
            elif _adaptation_convergence_result.get("accepted_operation"):
                # Recompute authority from the post-application staging
                # revision before any downstream gate reads semantic data.
                _adaptation_refresh = prepare_adaptation_repair_context(
                    workspace=Path(workspace),
                    staged_module_path=Path(params["output_directory"]).resolve(),
                    module_slug=str(_adaptation_staging_target.get("module_slug") or ""),
                    attempt={
                        "attempt_id": str(_adaptation_staging_target.get("attempt_id") or ""),
                        "attempt_number": int(_adaptation_staging_target.get("attempt_number", 0)),
                        "revision_number": int(_adaptation_staging_target.get("revision_number", 0)),
                        "source_hash": str(_adaptation_staging_target.get("source_hash") or ""),
                    },
                    repo_root=Path.cwd(),
                )
                build_result["adaptation_repair_refresh"] = {
                    key: _adaptation_refresh.get(key)
                    for key in ("status", "reason_code", "identity", "diagnostics")
                    if key in _adaptation_refresh
                }
                if _adaptation_refresh.get("status") not in {
                    "no_repairable_blocker", "repairable"
                }:
                    build_result["status"] = "blocked"
                    build_result["stage"] = "adaptation_convergence"
                    build_result["error"] = "adaptation_authority_refresh_blocked"
        except Exception:
            build_result["adaptation_convergence"] = {
                "status": "blocked",
                "reason_code": "adaptation_convergence_exception",
            }
            build_result["status"] = "blocked"
            build_result["stage"] = "adaptation_convergence"
            build_result["error"] = "adaptation_convergence_exception"

    # Refresh the attempt artifact after convergence so downstream gate
    # agreement cannot consume the pre-convergence report revision.
    if _is_adaptation_build and _adaptation_convergence_result is not None:
        try:
            _adaptation_attempt_artifact = _persist_adaptation_attempt_report(
                workspace=Path(workspace),
                job_id=job_id,
                build_result=build_result,
                adaptation_handoff=_adaptation_handoff or {},
                staging_target=_adaptation_staging_target,
                build_started_at=build_started_at,
                overwrite=True,
            )
        except Exception:
            _adaptation_attempt_artifact = None

    # TABLETOP MODE: Keep the continuation boundary fail-closed when the gate
    # stage is skipped because convergence or an earlier stage blocked. This
    # also avoids an unbound local on the production adaptation path.
    _adaptation_gate_result: Optional[Dict[str, Any]] = None

    # TABLETOP MODE: Adaptation candidates must pass the deterministic gate
    # composer before the staged build can be considered eligible for the
    # later Python-owned publication transaction. The composer only reads or
    # repairs the isolated staging target; it never registers the candidate.
    if (
        _is_adaptation_build
        and build_result.get("status") == "success"
        and isinstance(_adaptation_convergence_result, Mapping)
        and _adaptation_convergence_result.get("status") == "ready"
    ):
        try:
            from utils.toolkit_adaptation_gate_composer import (
                run_adaptation_gate_composer,
            )

            _adaptation_gate_result = run_adaptation_gate_composer(
                _adaptation_staging_target,
                module_dir=Path(params["output_directory"]).resolve(),
                build_result=build_result,
                attempt_metadata=(
                    _adaptation_handoff.get("provenance", {})
                    if isinstance(_adaptation_handoff, Mapping)
                    else None
                ),
                attempt_report=_adaptation_attempt_artifact,
                convergence_result=_adaptation_convergence_result,
            )
            _adaptation_gate_result["convergence_rerun"] = {
                "accepted": True,
                "full_gate_set": True,
                # Keep the report envelope project-relative; absolute host
                # paths are not allowed to cross the adaptation boundary.
                "staging_path": str(_adaptation_staging_target.get("path") or ""),
                "attempt_id": _adaptation_staging_target.get("attempt_id"),
                "attempt_number": _adaptation_staging_target.get("attempt_number"),
                "revision_number": _adaptation_staging_target.get("revision_number"),
                "source_hash": _adaptation_staging_target.get("source_hash"),
            }
            projected_classification = _project_adaptation_gate_revision(
                _adaptation_gate_result,
                convergence_result=_adaptation_convergence_result,
                staging_target=_adaptation_staging_target,
                adaptation_handoff=_adaptation_handoff,
            )
            if projected_classification is not None:
                _adaptation_gate_result["failure_classification"] = projected_classification
                build_result["failure_classification"] = deepcopy(projected_classification)
                budget = projected_classification.get("revision_budget") or {}
                build_result.update(
                    {
                        "next_revision_eligible": bool(
                            projected_classification.get("revision_eligible")
                        ),
                        "revision_eligible": bool(
                            projected_classification.get("revision_eligible")
                        ),
                        "semantic_revision_eligible": bool(
                            projected_classification.get("semantic_revision_eligible")
                        ),
                        "revision_budget": deepcopy(dict(budget)),
                        "semantic_revision_budget_consumed": bool(
                            budget.get("current_revision", 0) > 0
                        ),
                        "failure_class": projected_classification.get("failure_class"),
                        "failure_code": projected_classification.get("code"),
                        "failed_stage": projected_classification.get("stage"),
                        "failure_domain": projected_classification.get("domain"),
                        "failure_diagnostics": [
                            {
                                "code": str(projected_classification.get("code") or "content_gate_failed")[:120],
                                "message": str(projected_classification.get("message") or "content gate failed")[:320],
                            }
                        ],
                        "publication_allowed": False,
                        "publication_attempted": False,
                    }
                )
            build_result["adaptation_gates"] = _adaptation_gate_result
            if _adaptation_gate_result.get("playable_status") != "pass":
                build_result["status"] = "blocked"
                build_result["stage"] = "adaptation_gates"
                build_result["error"] = "adaptation_gates_blocked"
        except Exception as adaptation_gate_error:
            build_result["adaptation_gates"] = {
                "status": "blocked",
                "playable_status": "blocked",
                "python_authoritative": True,
                "publication": {
                    "authority": "python",
                    "attempted": False,
                    "allowed": False,
                },
                "errors": [f"adaptation_gate_composer_exception:{adaptation_gate_error}"],
            }
            build_result["status"] = "blocked"
            build_result["stage"] = "adaptation_gates"
            build_result["error"] = "adaptation_gate_composer_exception"

    # TABLETOP MODE: Persist the final gate projection immediately after gate
    # evaluation.  The earlier attempt write intentionally precedes the gate,
    # but semantic gate failures can return through paths where the terminal
    # staging finalizer is not the artifact writer observed by consumers.  Use
    # the current target and explicit overwrite so only this attempt/revision
    # is refreshed; prior revision artifacts remain immutable.
    if _is_adaptation_build and _adaptation_gate_result is not None:
        try:
            _adaptation_attempt_artifact = _persist_adaptation_attempt_report(
                workspace=Path(workspace),
                job_id=job_id,
                build_result=build_result,
                adaptation_handoff=_adaptation_handoff or {},
                staging_target=_adaptation_staging_target,
                build_started_at=build_started_at,
                overwrite=True,
            )
        except Exception:
            _adaptation_attempt_artifact = None

    # TABLETOP MODE: Record adaptation route resolution when a route was
    # explicitly requested. Default calls (no route requested) keep the
    # previous result shape exactly.
    if _adaptation_resolution is not None:
        build_result["adaptation_route_resolution"] = _adaptation_resolution

    # TABLETOP MODE: The finisher is a publication boundary.  Do not allow a
    # passing-looking gate result to promote a stale attempt, revision, or
    # source identity.  This join is provider-free and must run immediately
    # before the finisher consumes the staged result.
    if (
        _is_adaptation_build
        and build_result.get("status") == "success"
        and isinstance(_adaptation_gate_result, Mapping)
        and _adaptation_gate_result.get("playable_status") == "pass"
        and _has_full_adaptation_gate_envelope(_adaptation_gate_result)
    ):
        try:
            from utils.toolkit_adaptation_publication_convergence import (
                validate_adaptation_publication_continuation,
            )

            current_context = safe_read_json(
                str(Path(params["output_directory"]).resolve() / "module_context.json")
            )
            current_authority = (
                current_context.get("semantic_authority")
                if isinstance(current_context, Mapping)
                else None
            )
            # TABLETOP MODE: Reassert the current adaptation identity at the
            # final handoff.  The convergence refresh normally writes this
            # payload, but a downstream gate/finisher adapter may have
            # replaced the staged context with a legacy-shaped copy.  Rebuild
            # only the staging-local authority from the canonical source
            # artifacts rather than relaxing the continuation gate.
            _current_identity = {
                "attempt_id": _adaptation_staging_target.get("attempt_id"),
                "attempt_number": _adaptation_staging_target.get("attempt_number"),
                "revision_number": _adaptation_staging_target.get("revision_number"),
                "source_hash": _adaptation_staging_target.get("source_hash"),
            }
            if (
                not isinstance(current_authority, Mapping)
                or current_authority.get("attempt") != _current_identity
                or not isinstance(current_authority.get("adaptation_provenance"), Mapping)
                or current_authority["adaptation_provenance"].get("source_hash")
                != _current_identity["source_hash"]
            ):
                if _adaptation_authority_inputs_are_complete(files):
                    from utils.toolkit_adaptation_semantic_authority import (
                        build_adaptation_semantic_authority,
                        persist_adaptation_semantic_authority,
                    )

                    _authority_manifest = load_json_artifact(files["source_manifest"])
                    _authority_packet = load_json_artifact(files["normalized_packet"])
                    _authority_result = build_adaptation_semantic_authority(
                        str(_adaptation_staging_target.get("module_slug") or ""),
                        Path(params["output_directory"]).resolve(),
                        attempt=_current_identity,
                        source_manifest=_authority_manifest,
                        normalized_packet=_authority_packet,
                    )
                    _authority_persisted = persist_adaptation_semantic_authority(
                        Path(params["output_directory"]).resolve(), _authority_result
                    )
                    if _authority_persisted.get("status") != "persisted":
                        raise ValueError("adaptation_semantic_authority_refresh_failed")
                    current_context = safe_read_json(
                        str(Path(params["output_directory"]).resolve() / "module_context.json")
                    )
                    current_authority = (
                        current_context.get("semantic_authority")
                        if isinstance(current_context, Mapping)
                        else None
                    )
                else:
                    # A partial fixture workspace has no canonical evidence
                    # from which to rebuild authority.  Continue only when the
                    # already-passing gate envelope proves the current
                    # identity and the existing authority has no contradictory
                    # identity; this reasserts metadata, not evidence.
                    _gate_provenance = _adaptation_gate_result.get("provenance")
                    _semantic_gate = (_adaptation_gate_result.get("gates") or {}).get(
                        "semantic_authority"
                    )
                    _gate_identity = (
                        {key: _gate_provenance.get(key) for key in _current_identity}
                        if isinstance(_gate_provenance, Mapping)
                        else {}
                    )
                    _authority_attempt = (
                        current_authority.get("attempt")
                        if isinstance(current_authority, Mapping)
                        else None
                    )
                    _authority_provenance = (
                        current_authority.get("adaptation_provenance")
                        if isinstance(current_authority, Mapping)
                        else None
                    )
                    if (
                        not isinstance(current_authority, Mapping)
                        or (isinstance(_authority_attempt, Mapping) and _authority_attempt != _current_identity)
                        or (
                            isinstance(_authority_provenance, Mapping)
                            and _authority_provenance.get("source_hash")
                            not in (None, _current_identity["source_hash"])
                        )
                        or _gate_identity != _current_identity
                        or not isinstance(_semantic_gate, Mapping)
                        or _semantic_gate.get("effective_status", _semantic_gate.get("status")) != "pass"
                    ):
                        raise ValueError("adaptation_semantic_authority_refresh_failed")
                    current_authority = deepcopy(dict(current_authority))
                    current_authority["attempt"] = dict(_current_identity)
                    _reasserted_provenance = deepcopy(
                        dict(_authority_provenance)
                        if isinstance(_authority_provenance, Mapping)
                        else {}
                    )
                    _reasserted_provenance.update(
                        {
                            "mode": BUILD_MODE_LLM_ADAPTATION,
                            "module_slug": str(_adaptation_staging_target.get("module_slug") or ""),
                            "source_hash": _current_identity["source_hash"],
                        }
                    )
                    current_authority["adaptation_provenance"] = _reasserted_provenance

            # The persisted artifact schema keeps source_hash in its
            # provenance envelope.  The continuation contract also accepts a
            # root-level projection; provide all four identity fields here so
            # this final join cannot accidentally receive a partial report.
            _continuation_attempt_report = deepcopy(_adaptation_attempt_artifact or {})
            if isinstance(_continuation_attempt_report, Mapping):
                _continuation_attempt_report = dict(_continuation_attempt_report)
                _continuation_attempt_report["attempt_id"] = _current_identity["attempt_id"]
                _continuation_attempt_report["attempt_number"] = _current_identity["attempt_number"]
                _continuation_attempt_report["revision_number"] = _current_identity["revision_number"]
                _continuation_attempt_report["source_hash"] = _current_identity["source_hash"]
            _adaptation_continuation = validate_adaptation_publication_continuation(
                staging_target=_adaptation_staging_target,
                build_result=build_result,
                attempt_report=_continuation_attempt_report,
                semantic_authority=current_authority or {},
                convergence_result=_adaptation_convergence_result or {},
                gate_result=_adaptation_gate_result,
            )
            build_result["adaptation_publication_continuation"] = _adaptation_continuation
            _adaptation_gate_result["publication_continuation"] = _adaptation_continuation
            if not _adaptation_continuation.get("allowed"):
                build_result["status"] = "blocked"
                build_result["stage"] = "adaptation_publication_continuation"
                build_result["error"] = "adaptation_publication_inputs_disagree"
                _apply_adaptation_continuation_failure(
                    build_result,
                    _adaptation_continuation,
                    error_code="adaptation_publication_inputs_disagree",
                    adaptation_handoff=_adaptation_handoff,
                )
                _adaptation_gate_result.setdefault("blockers", []).extend(
                    _adaptation_continuation.get("blockers", [])
                )
                _adaptation_gate_result["publication"] = {
                    "authority": "python",
                    "attempted": False,
                    "allowed": False,
                }
        except Exception as continuation_error:
            build_result["adaptation_publication_continuation"] = {
                "allowed": False,
                "status": "blocked",
                "reason_code": "publication_continuation_exception",
                "blockers": ["publication_continuation_exception:" + str(continuation_error)[:240]],
            }
            build_result["status"] = "blocked"
            build_result["stage"] = "adaptation_publication_continuation"
            build_result["error"] = "adaptation_publication_continuation_exception"
            _apply_adaptation_continuation_failure(
                build_result,
                build_result["adaptation_publication_continuation"],
                error_code="adaptation_publication_continuation_exception",
                adaptation_handoff=_adaptation_handoff,
            )
            if isinstance(_adaptation_gate_result, Mapping):
                _adaptation_gate_result["publication"] = {
                    "authority": "python",
                    "attempted": False,
                    "allowed": False,
                }

    build_result = _finish_adaptation_staging(build_result)
    if not _is_adaptation_build:
        build_result["build_result_persisted"] = persist_legacy_build_result_artifact(
            workspace, build_result
        )
        if not build_result["build_result_persisted"]:
            build_result["status"] = "failed"
            build_result["error"] = "build_result_persist_failed"
            return _finish_adaptation_staging(build_result)

    return build_result


# ---------------------------------------------------------------------------
# Step 5.1: Final editor invocation helper
# ---------------------------------------------------------------------------


def _invoke_final_editor_or_fallback(
    build_result: Dict[str, Any],
    brief: Dict[str, Any],
    module_dir: Path,
    workspace: Path,
    job_id: str,
    module_name: str,
    brief_persist_result: Dict[str, Any],
    classification: Dict[str, Any],
) -> bool:
    """Invoke the LLM Builder final editor pipeline for an editorial-only brief.

    Step 5.1 of the ``toolkit-accurate-ingest-llm-builder-final-editor`` change.
    The helper owns the entire editorial-only live-invocation contract:

    1. If the helper API (``utils.toolkit_llm_final_reconciliation``) cannot be
       imported, the helper falls back to the legacy
       ``final_reconciliation_required`` pause (per task 5.1 step 6) by
       populating ``build_result`` with the existing pause metadata. Returns
       ``False`` so the caller does not continue as accepted.
    2. If the import succeeds, the orchestrator is invoked with the freshly
       built brief and the resolved ``module_dir``. Live-provider errors are
       caught fail-closed: ``build_result`` is set to ``blocked`` and the
       caller is expected to stop.
    3. When the orchestrator returns ``accepted``, the accepted report is
       persisted via ``persist_accepted_final_reconciliation_report(...)``.
       On persist success, the helper sets the accepted metadata
       (``final_reconciliation_accepted``, ``source_fidelity_effective_status:
       reconciled_degraded``, plus the nested ``build_fidelity`` mirror) and
       returns ``True`` so the caller continues to normal build-result
       persistence. On persist failure, the helper shapes a blocked report via
       ``build_blocked_final_reconciliation_report(...)`` and sets the build
       result to ``blocked``.
    4. When the orchestrator returns any non-accepted status (``rejected``,
       ``not_retryable``, ``invalid_brief``, etc.), the helper shapes a
       blocked report and sets the build result to ``blocked`` with
       ``stage=final_reconciliation`` and a ``final_reconciliation_editor_rejected:``
       error string.

    The helper NEVER mutates ``brief`` or ``classification``. It ONLY mutates
    ``build_result`` (the same in-place mutation pattern the surrounding
    packet-builder flow already uses). It does not persist the brief itself
    (the caller persists the brief first, before calling the helper) and it
    does not persist the blocked report (the helper's blocked report shape is
    used as in-memory metadata only, per the "fail closed and write nothing"
    contract that already exists in the helper API).

    Returns:
        ``True`` only when the editor was invoked and produced an accepted
        reconciliation that was successfully persisted. ``False`` in every
        other case (fallback pause, non-accepted orchestrator result, or
        accepted-but-persist-failed).
    """
    try:
        from utils.toolkit_llm_final_reconciliation import (
            run_final_reconciliation_with_bounded_retry,
            persist_accepted_final_reconciliation_report,
            build_blocked_final_reconciliation_report,
        )
    except Exception as editor_import_error:
        # Helper API unavailable: fall back to the legacy
        # final_reconciliation_required pause (per task 5.1 step 6).
        build_result["final_reconciliation_required"] = True
        build_result["final_reconciliation_brief"] = brief_persist_result
        build_result["build_fidelity"]["final_reconciliation_required"] = True
        build_result["build_fidelity"]["final_reconciliation_brief_path"] = (
            brief_persist_result.get("path")
        )
        build_result["status"] = "final_reconciliation_required"
        build_result["stage"] = "final_reconciliation"
        build_result.pop("error", None)
        info(
            (
                f"TOOLKIT_HOMEBREW: Final editor API import failed job={job_id} "
                f"module={module_name} error={editor_import_error}; "
                "falling back to final_reconciliation_required"
            ),
            category="web_interface",
        )
        return False

    # Invoke the orchestrator. The helper has its own bounded retry + provider
    # fail-closed semantics, so the surrounding code only needs to catch
    # unexpected exceptions (e.g. import-time side effects) and treat any
    # non-accepted orchestrator status as a fail-closed blocked result.
    try:
        orchestrator_result = run_final_reconciliation_with_bounded_retry(
            brief=brief,
            module_dir=str(module_dir),
        )
    except Exception as editor_error:
        build_result["status"] = "blocked"
        build_result["stage"] = "final_reconciliation"
        build_result["error"] = (
            f"final_reconciliation_editor_exception:{editor_error}"
        )
        build_result["final_reconciliation_required"] = True
        build_result["final_reconciliation_brief"] = brief_persist_result
        build_result["build_fidelity"]["final_reconciliation_required"] = True
        build_result["build_fidelity"]["final_reconciliation_brief_path"] = (
            brief_persist_result.get("path")
        )
        build_result["final_reconciliation_editor_result"] = {
            "status": "error",
            "error": str(editor_error),
            "editor_invoked": True,
        }
        error(
            (
                f"TOOLKIT_HOMEBREW: Final editor exception job={job_id} "
                f"module={module_name} error={editor_error}"
            ),
            exception=editor_error,
            category="web_interface",
        )
        return False

    editor_status = (
        orchestrator_result.get("status")
        if isinstance(orchestrator_result, dict)
        else "unknown"
    )

    if editor_status == "accepted":
        # Persist the accepted report. On any persist failure, fail closed
        # with the blocked report shape; do NOT continue as accepted.
        try:
            persist_report_result = persist_accepted_final_reconciliation_report(
                module_dir=str(module_dir),
                orchestrator_result=orchestrator_result,
                brief=brief,
            )
        except Exception as persist_error:
            persist_report_result = {
                "status": "failed",
                "path": None,
                "report": None,
                "error": str(persist_error),
                "diagnostics": [],
                "bytes": 0,
            }

        if persist_report_result.get("status") != "written":
            # Build a minimal blocked-shape metadata dict directly so we do NOT
            # delegate to ``build_blocked_final_reconciliation_report`` (which
            # passes through to the accepted report for accepted orchestrator
            # results). The build is blocked here, so the metadata must reflect
            # the blocked state, not the underlying accepted orchestrator
            # status.
            blocked_metadata = {
                "status": "blocked",
                "reconciliation_status": "blocked",
                "source_fidelity_effective_status": "blocked",
                "playable_publication_candidate": False,
                "decisions": [],
                "changed_files": [],
                "persist_error": persist_report_result.get("error"),
            }
            build_result["status"] = "blocked"
            build_result["stage"] = "final_reconciliation"
            build_result["error"] = (
                "final_reconciliation_persist_failed:"
                f"{persist_report_result.get('error', 'unknown')}"
            )
            build_result["final_reconciliation_required"] = True
            build_result["final_reconciliation_brief"] = brief_persist_result
            build_result["build_fidelity"]["final_reconciliation_required"] = True
            build_result["build_fidelity"]["final_reconciliation_brief_path"] = (
                brief_persist_result.get("path")
            )
            build_result["final_reconciliation_editor_result"] = blocked_metadata
            error(
                (
                    f"TOOLKIT_HOMEBREW: Final report persist failed job={job_id} "
                    f"module={module_name} "
                    f"error={persist_report_result.get('error')}"
                ),
                category="web_interface",
            )
            return False

        # Accepted path: set accepted metadata, do not claim clean pass.
        accepted_report = persist_report_result.get("report") or {}
        build_result["final_reconciliation_accepted"] = True
        build_result["final_reconciliation"] = accepted_report
        build_result["source_fidelity_effective_status"] = "reconciled_degraded"
        build_result["build_fidelity"]["final_reconciliation_accepted"] = True
        build_result["build_fidelity"]["source_fidelity_effective_status"] = (
            "reconciled_degraded"
        )
        info(
            (
                f"TOOLKIT_HOMEBREW: Final reconciliation accepted job={job_id} "
                f"module={module_name} via final editor "
                f"path={persist_report_result.get('path')}"
            ),
            category="web_interface",
        )
        return True

    # Non-accepted orchestrator result: shape a blocked report and stop.
    blocked_report = build_blocked_final_reconciliation_report(
        orchestrator_result=orchestrator_result,
        brief=brief,
    )
    build_result["status"] = "blocked"
    build_result["stage"] = "final_reconciliation"
    build_result["error"] = f"final_reconciliation_editor_rejected:{editor_status}"
    build_result["final_reconciliation_required"] = True
    build_result["final_reconciliation_brief"] = brief_persist_result
    build_result["build_fidelity"]["final_reconciliation_required"] = True
    build_result["build_fidelity"]["final_reconciliation_brief_path"] = (
        brief_persist_result.get("path")
    )
    build_result["final_reconciliation_editor_result"] = blocked_report
    warning(
        (
            f"TOOLKIT_HOMEBREW: Final editor did not accept job={job_id} "
            f"module={module_name} status={editor_status}"
        ),
        category="web_interface",
    )
    return False


def run_toolkit_homebrew_packet_build(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Keep upload adaptation output inside the opt-in safety boundary."""
    adaptation = (
        kwargs.get("adaptation_route") == BUILD_MODE_LLM_ADAPTATION
        or kwargs.get("adaptation_dossier") is not None
    )
    if not adaptation:
        # Legacy accurate-ingest/concept builds retain their existing output.
        return _run_toolkit_homebrew_packet_build(*args, **kwargs)

    progress_callback = kwargs.get("progress_callback")
    with AdaptationOutputSafety(
        phase="adaptation_build", status="running", redirect_streams=True
    ) as scope:
        if progress_callback is not None:
            def safe_progress(stage: Any, message: Any) -> Any:
                event = scope.emit({
                    "phase": stage,
                    "status": "running",
                    "code": stage,
                    "message": message,
                })
                try:
                    return progress_callback(event["phase"], event.get("message", ""))
                except Exception:
                    return None
            kwargs["progress_callback"] = safe_progress
        return _run_toolkit_homebrew_packet_build(*args, **kwargs)
