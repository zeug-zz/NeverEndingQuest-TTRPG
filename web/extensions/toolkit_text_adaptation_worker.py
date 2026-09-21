# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Text-Description Adaptation Worker Seam - Pre-ModuleBuilder
Adaptation Branch for the Legacy Text-Description Build Worker
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.

Tasks 5.1 and 5.2 of toolkit-llm-adaptation-runtime-unification: the enabled
text-description build worker resolves the Python-owned ``text_description``
adaptation route, builds the bounded project-relative attempt workspace, and
invokes the shared adaptation authoring adapter exactly once BEFORE any
ModuleBuilder/module write. The seam fails closed on authoring refusal,
invalid/missing workspace, invalid dossier, or infrastructure failure and
never silently downgrades a selected adaptation attempt to direct legacy
generation. A ready authoring handoff is then consumed by the task 5.2 staged
publication function, which routes the provisional module through the SAME
shared transaction used by uploaded adventures: staged packet/build output,
schema/mechanical/readiness gates, semantic/report agreement, Markdown
quality/summary, registry integration as the final stateful publication,
campaign synchronization, post-write verification, and targeted rollback on
failure. Completion is reported only after that shared publication
verification; pre-publication failures remain explicit blocked outcomes.

The authoring seam stage (task 5.1) is deliberately side-effect free: it
never imports or calls a provider, the module builder, Flask/Socket.IO, or
the web host. It returns a bounded outcome dict (or None when the input stays
legacy) and the host worker owns event emission. Provider/network work stays
behind the injectable author client/runner/resolver seams forwarded to the
shared runtime adapter. The task 5.2 publication function lazily imports the
existing upload transaction helpers (packet builder and adaptation finisher)
inside the function body only, and every call site in tests injects
deterministic fakes so no builder, registry, or campaign write ever occurs
without the full shared transaction.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from utils.enhanced_logger import warning
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LLM_ADAPTATION,
    INPUT_KIND_TEXT_DESCRIPTION,
    ROUTE_DECISION_STATUS_ADAPTATION,
    resolve_adaptation_input_route,
    validate_adaptation_route_decision,
)
from utils.toolkit_adaptation_dossier import validate_adaptation_dossier
from utils.toolkit_adaptation_output_safety import (
    AdaptationOutputSafety,
    project_safe_event,
)
from utils.toolkit_adaptation_staging import (
    DEFAULT_ADAPTATION_STAGING_ROOT,
    create_adaptation_staging_target,
)
from web.extensions.toolkit_adaptation_runtime import (
    TEXT_DESCRIPTION_WORKSPACE_STATUS_READY,
    adaptation_convergence_callback,
    build_text_description_attempt_workspace,
    run_text_description_adaptation_authoring,
)
from web.extensions.toolkit_adaptation_job_reporting import (
    validate_adaptation_artifact_current,
)

TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION = "toolkit_text_description_worker_seam.v1"
TEXT_WORKER_OUTCOME_BLOCKED = "blocked"
TEXT_WORKER_OUTCOME_AUTHORING_READY = "authoring_ready_pending_publication"
TEXT_WORKER_STATUS_FAILED_CLOSED = "failed_closed"
TEXT_WORKER_STATUS_READY = "ready"
TEXT_PUBLICATION_CONTRACT_VERSION = "toolkit_text_description_publication.v1"
TEXT_WORKER_OUTCOME_COMPLETED = "completed"
TEXT_WORKER_STATUS_COMPLETED = "completed"
TEXT_WORKER_OUTCOME_SEMANTIC_REVISION = "semantic_revision"
TEXT_WORKER_STATUS_REVISION_REQUIRED = "adaptation_revision_required"

MAX_SEAM_DIAGNOSTICS = 12
MAX_SEAM_DIAGNOSTIC_CHARS = 320
MAX_SEAM_REASON_CODE_CHARS = 120
MAX_SEAM_JOB_ID_CHARS = 160
MAX_PUBLICATION_TEXT_CHARS = 240


def _bounded_diagnostics(items: Any) -> List[Dict[str, str]]:
    """Return bounded ASCII diagnostic entries (code + bounded message)."""
    bounded: List[Dict[str, str]] = []
    if not isinstance(items, (list, tuple)):
        return bounded
    for item in items[:MAX_SEAM_DIAGNOSTICS]:
        if isinstance(item, Mapping):
            event = project_safe_event(
                phase="adaptation_build",
                status="blocked",
                code=item.get("code"),
                message=item.get("message"),
            )
            code = event["code"][:MAX_SEAM_REASON_CODE_CHARS]
            message = event.get("message", "")[:MAX_SEAM_DIAGNOSTIC_CHARS]
            bounded.append({"code": code, "message": message})
        elif isinstance(item, str):
            event = project_safe_event(
                phase="adaptation_build", status="blocked", code="unclassified", message=item
            )
            bounded.append(
                {
                    "code": "unclassified",
                    "message": event.get("message", "")[:MAX_SEAM_DIAGNOSTIC_CHARS],
                }
            )
    return bounded


def _blocked_result(
    route_decision: Mapping[str, Any],
    reason_code: str,
    diagnostics: Any = None,
) -> Dict[str, Any]:
    """Return the explicit fail-closed adaptation outcome for one attempt."""
    return {
        "contract_version": TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION,
        "outcome": TEXT_WORKER_OUTCOME_BLOCKED,
        "status": TEXT_WORKER_STATUS_FAILED_CLOSED,
        "route_decision": dict(route_decision),
        "reason_code": str(reason_code or "adaptation_blocked")[
            :MAX_SEAM_REASON_CODE_CHARS
        ],
        "diagnostics": _bounded_diagnostics(diagnostics),
    }


def _text_source_hash(narrative: Any) -> str:
    """Return the stable lowercase SHA-256 identity of the bounded concept."""
    raw = ""
    if isinstance(narrative, bytes):
        try:
            raw = narrative.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    elif isinstance(narrative, str):
        raw = narrative
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _run_text_description_adaptation_seam(
    module_name: str,
    narrative: str,
    params: Optional[Mapping[str, Any]] = None,
    *,
    client: Any = None,
    author_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    parameter_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    timeout_seconds: Optional[float] = 120,
    artifact_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
    proposal_persister: Optional[Callable[[Path, Mapping[str, Any]], bool]] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Run the pre-ModuleBuilder adaptation branch for one text-description build.

    Returns ``None`` when the input is not eligible or adaptation is not
    enabled (missing, invalid, or exactly False flag): the host worker then
    preserves the legacy direct-builder path unchanged. Otherwise returns a
    bounded outcome dict:

      * ``outcome=blocked`` -- an explicit fail-closed adaptation outcome
        (authoring refusal, invalid/missing workspace, invalid dossier,
        infrastructure failure, invalid route authority). The legacy direct
        builder MUST NOT run.
      * ``outcome=authoring_ready_pending_publication`` -- the ready
        Python-validated dossier, reserved staging target, bounded provenance,
        and attempt/workspace identity are preserved for the downstream
        shared publication transaction (task 5.2). No module is written and no
        legacy success event may be emitted.

    The seam invokes ``run_text_description_adaptation_authoring`` exactly
    once per attempt. Provider/network work is only reachable through the
    injected ``client``/``author_runner``/``parameter_resolver`` seams.
    """
    diagnostics: List[Dict[str, str]] = []
    source_hash = _text_source_hash(narrative)
    job_id = ""
    if isinstance(params, Mapping):
        raw_job_id = params.get("job_id")
        if isinstance(raw_job_id, str) and raw_job_id.strip():
            job_id = raw_job_id.strip()[:MAX_SEAM_JOB_ID_CHARS]

    try:
        route_decision = resolve_adaptation_input_route(
            INPUT_KIND_TEXT_DESCRIPTION,
            module_name=module_name,
            description=narrative,
            source_kind=INPUT_KIND_TEXT_DESCRIPTION,
            source_hash=source_hash or None,
            source_title=module_name,
            job_id=job_id or None,
            attempt_number=1,
        )
    except Exception:
        # Route resolution itself must never decide the build route silently.
        return _blocked_result(
            {
                "contract_version": "toolkit_adaptation_route_decision.v1",
                "status": ROUTE_DECISION_STATUS_ADAPTATION,
                "route_selected": BUILD_MODE_LLM_ADAPTATION,
            },
            "adaptation_route_resolution_failed",
            [{"code": "adaptation_route_resolution_failed", "message": "route resolution failed"}],
        )
    if not isinstance(route_decision, Mapping):
        return None
    if route_decision.get("status") != ROUTE_DECISION_STATUS_ADAPTATION:
        # Missing/invalid/False flag or ineligible input: explicit legacy.
        return None

    authority = validate_adaptation_route_decision(route_decision)
    if (
        not isinstance(authority, Mapping)
        or authority.get("authoritative") is not True
        or authority.get("status") != ROUTE_DECISION_STATUS_ADAPTATION
    ):
        return _blocked_result(
            route_decision,
            "adaptation_route_authority_invalid",
            authority.get("diagnostics") if isinstance(authority, Mapping) else None,
        )

    # ---- Build the bounded project-relative attempt workspace -------------
    try:
        workspace_manifest = build_text_description_attempt_workspace(
            module_name,
            narrative,
            job_id=job_id,
            attempt_number=1,
            source_title=module_name,
        )
    except Exception as exc:
        return _blocked_result(
            route_decision,
            "text_description_workspace_infrastructure_failure",
            [
                {
                    "code": "text_description_workspace_infrastructure_failure",
                    "message": str(exc)[:MAX_SEAM_DIAGNOSTIC_CHARS]
                    or "attempt workspace could not be created",
                }
            ],
        )
    if not isinstance(workspace_manifest, Mapping) or workspace_manifest.get(
        "status"
    ) != TEXT_DESCRIPTION_WORKSPACE_STATUS_READY:
        workspace_diagnostics = (
            workspace_manifest.get("diagnostics")
            if isinstance(workspace_manifest, Mapping)
            else None
        )
        return _blocked_result(
            route_decision,
            "text_description_workspace_failed",
            workspace_diagnostics
            or [
                {
                    "code": "text_description_workspace_failed",
                    "message": "attempt workspace could not be prepared",
                }
            ],
        )

    # ---- Invoke the shared authoring adapter exactly once -----------------
    try:
        authoring_result = run_text_description_adaptation_authoring(
            workspace_manifest,
            client=client,
            author_runner=author_runner,
            parameter_resolver=parameter_resolver,
            timeout_seconds=timeout_seconds,
            artifact_persister=artifact_persister,
            proposal_persister=proposal_persister,
            model=model,
            provider=provider,
        )
    except Exception as exc:
        return _blocked_result(
            route_decision,
            "text_description_authoring_infrastructure_failure",
            [
                {
                    "code": "text_description_authoring_infrastructure_failure",
                    "message": str(exc)[:MAX_SEAM_DIAGNOSTIC_CHARS]
                    or "adaptation authoring failed",
                }
            ],
        )
    if not isinstance(authoring_result, Mapping) or not bool(authoring_result.get("ok")):
        authoring = (
            authoring_result.get("authoring")
            if isinstance(authoring_result, Mapping)
            else None
        )
        authoring = authoring if isinstance(authoring, Mapping) else {}
        safe_class = str(authoring.get("safe_class") or "").lower()
        reason_code = str(
            authoring.get("reason_code") or "text_description_authoring_blocked"
        )
        if safe_class == "provider_infrastructure":
            reason_code = "text_description_authoring_infrastructure_failure"
        authoring_diagnostics = (
            authoring_result.get("diagnostics")
            if isinstance(authoring_result, Mapping)
            else None
        )
        return _blocked_result(
            route_decision,
            reason_code,
            authoring_diagnostics
            or [
                {
                    "code": reason_code,
                    "message": "adaptation authoring was blocked",
                }
            ],
        )

    # ---- Require a Python-validated build-ready dossier -------------------
    dossier = authoring_result.get("dossier")
    dossier_validation = (
        validate_adaptation_dossier(dossier)
        if isinstance(dossier, Mapping)
        else {"valid": False, "build_ready": False}
    )
    if not bool(dossier_validation.get("valid")) or not bool(
        dossier_validation.get("build_ready")
    ):
        return _blocked_result(
            route_decision,
            "text_description_dossier_not_ready",
            [
                {
                    "code": "text_description_dossier_not_ready",
                    "message": "adaptation authoring did not produce a ready dossier",
                }
            ],
        )

    source_identity = authoring_result.get("source_identity")
    source_identity = source_identity if isinstance(source_identity, Mapping) else {}
    attempt = authoring_result.get("attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    authoring = authoring_result.get("authoring")
    authoring = authoring if isinstance(authoring, Mapping) else {}
    authoring_source_hash = str(source_identity.get("source_hash") or "").strip().lower()
    if not authoring_source_hash:
        return _blocked_result(
            route_decision,
            "text_description_source_identity_missing",
            [
                {
                    "code": "text_description_source_identity_missing",
                    "message": "adaptation authoring lost the text source identity",
                }
            ],
        )

    # ---- Reserve the isolated staging target (post-dossier handoff) -------
    try:
        staging_target = create_adaptation_staging_target(
            authoring_source_hash,
            attempt_id=str(attempt.get("attempt_id") or "") or None,
            attempt_number=int(attempt.get("attempt_number") or 1),
            revision_number=int(attempt.get("revision_number") or 0),
            job_id=str(attempt.get("job_id") or "") or "",
            source_path=str(source_identity.get("source_path") or ""),
            module_slug=module_name,
            staging_root=DEFAULT_ADAPTATION_STAGING_ROOT,
        )
    except Exception as staging_error:
        return _blocked_result(
            route_decision,
            "adaptation_staging_reservation_failed",
            [
                {
                    "code": "adaptation_staging_reservation_failed",
                    "message": str(staging_error)[:MAX_SEAM_DIAGNOSTIC_CHARS]
                    or "staging reservation failed",
                }
            ],
        )
    if not isinstance(staging_target, Mapping) or not staging_target:
        return _blocked_result(
            route_decision,
            "adaptation_staging_reservation_failed",
            [
                {
                    "code": "adaptation_staging_reservation_failed",
                    "message": "staging reservation produced no target",
                }
            ],
        )

    # ---- Bounded handoff identity for the downstream transaction ----------
    workspace_block = workspace_manifest.get("workspace")
    workspace_block = workspace_block if isinstance(workspace_block, Mapping) else {}
    world_context = authoring_result.get("world_context")
    world_context = world_context if isinstance(world_context, Mapping) else {}
    rights = authoring_result.get("rights")
    rights = rights if isinstance(rights, Mapping) else {}
    model_metadata = authoring_result.get("model_metadata")
    model_metadata = model_metadata if isinstance(model_metadata, Mapping) else {}
    provenance: Dict[str, Any] = {
        "attempt_metadata": {
            "attempt_id": attempt.get("attempt_id"),
            "attempt_number": attempt.get("attempt_number"),
            "revision_number": attempt.get("revision_number"),
            "job_id": attempt.get("job_id"),
        },
        "model_metadata": dict(model_metadata),
        "world_context_provenance": dict(world_context),
        "source_hash": authoring_source_hash,
        "source_title": source_identity.get("source_title"),
        "source_path": source_identity.get("source_path"),
        "source_format": str(authoring_result.get("input_kind") or ""),
        "dossier_artifact_path": authoring.get("dossier_artifact_path"),
        "rights_class": rights.get("rights_class"),
        "rights_basis": rights.get("rights_basis"),
        "rights_review_required": rights.get("rights_review_required"),
        "rights_review_status": rights.get("rights_review_status"),
    }
    adaptation_handoff: Dict[str, Any] = {
        "module_name": module_name,
        "source_hash": authoring_source_hash,
        "source_title": source_identity.get("source_title"),
        "dossier": deepcopy(dossier),
        "attempt": {
            "attempt_id": attempt.get("attempt_id"),
            "attempt_number": attempt.get("attempt_number"),
            "revision_number": attempt.get("revision_number"),
            "job_id": attempt.get("job_id"),
        },
        "rights": dict(rights),
        "world_context": dict(world_context),
        "model_metadata": dict(model_metadata),
        "dossier_artifact_path": authoring.get("dossier_artifact_path"),
        "workspace_path": str(workspace_block.get("path") or ""),
        "staging_target": dict(staging_target),
        "staging_target_path": str(staging_target.get("path") or ""),
        "staging_root": str(staging_target.get("staging_root") or ""),
        "provenance": provenance,
    }
    return {
        "contract_version": TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION,
        "outcome": TEXT_WORKER_OUTCOME_AUTHORING_READY,
        "status": TEXT_WORKER_STATUS_READY,
        "route_decision": dict(route_decision),
        "adaptation_handoff": adaptation_handoff,
        "diagnostics": [],
    }


def _bounded_publication_text(value: Any) -> str:
    """Bound one ASCII publication summary field."""
    return str(value or "")[:MAX_PUBLICATION_TEXT_CHARS]


def _bounded_handoff_identity(handoff: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the bounded identity block of a ready adaptation handoff."""
    attempt = handoff.get("attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    rights = handoff.get("rights")
    rights = rights if isinstance(rights, Mapping) else {}
    world_context = handoff.get("world_context")
    world_context = world_context if isinstance(world_context, Mapping) else {}
    provenance = handoff.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    return {
        "module_name": _bounded_publication_text(handoff.get("module_name")),
        "source_hash": _bounded_publication_text(handoff.get("source_hash")),
        "source_title": _bounded_publication_text(handoff.get("source_title")),
        "attempt": {
            "attempt_id": attempt.get("attempt_id"),
            "attempt_number": attempt.get("attempt_number"),
            "revision_number": attempt.get("revision_number"),
            "job_id": attempt.get("job_id"),
        },
        "rights": dict(rights),
        "world_context": dict(world_context),
        "dossier_artifact_path": _bounded_publication_text(
            handoff.get("dossier_artifact_path")
        ),
        "workspace_path": _bounded_publication_text(handoff.get("workspace_path")),
        "staging_target_path": _bounded_publication_text(
            handoff.get("staging_target_path")
        ),
        "staging_root": _bounded_publication_text(handoff.get("staging_root")),
        "provenance": dict(provenance),
    }


def _handoff_artifact_identity(handoff: Mapping[str, Any]) -> Dict[str, Any]:
    """Resolve the Python-owned identity expected by a publication retry."""
    attempt = handoff.get("attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    provenance = handoff.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    nested_attempt = provenance.get("attempt_metadata")
    nested_attempt = nested_attempt if isinstance(nested_attempt, Mapping) else {}
    staging = handoff.get("staging_target")
    staging = staging if isinstance(staging, Mapping) else {}
    dossier = handoff.get("dossier")
    dossier = dossier if isinstance(dossier, Mapping) else {}

    def first(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    return {
        "attempt_id": first(
            attempt.get("attempt_id"),
            nested_attempt.get("attempt_id"),
            provenance.get("attempt_id"),
            staging.get("attempt_id"),
        ),
        "revision_number": first(
            attempt.get("revision_number"),
            nested_attempt.get("revision_number"),
            provenance.get("revision_number"),
            staging.get("revision_number"),
            0,
        ),
        "source_hash": first(
            handoff.get("source_hash"),
            dossier.get("source_hash"),
            provenance.get("source_hash"),
            staging.get("source_hash"),
        ),
        "source_path": first(provenance.get("source_path"), staging.get("source_path")),
    }


def _validate_current_build_result(
    build_result: Mapping[str, Any], handoff: Mapping[str, Any]
) -> Dict[str, Any]:
    """Reject a retry result that belongs to another adaptation revision."""
    expected = _handoff_artifact_identity(handoff)
    checks = [("build_result", build_result)]
    attempt_report = build_result.get("adaptation_attempt_report")
    if isinstance(attempt_report, Mapping):
        checks.append(("build_attempt_report", attempt_report))
    staging_target = build_result.get("staging_target")
    if isinstance(staging_target, Mapping):
        checks.append(("build_staging_target", staging_target))
    gates = build_result.get("adaptation_gates")
    if isinstance(gates, Mapping) and isinstance(gates.get("provenance"), Mapping):
        checks.append(("readiness_gate", gates["provenance"]))

    for label, artifact in checks:
        validation = validate_adaptation_artifact_current(
            artifact,
            expected_attempt_id=expected.get("attempt_id"),
            expected_revision_number=expected.get("revision_number", 0),
            expected_source_hash=expected.get("source_hash"),
            expected_source_path=expected.get("source_path"),
            label=label,
        )
        if validation.get("status") != "pass":
            return validation
    return {"status": "pass", "reason_code": "adaptation_build_artifact_current"}


def _bounded_publication_summary(
    build_result: Any,
    finisher_report: Any,
) -> Dict[str, Any]:
    """Build a bounded publication summary from staged build/finisher reports.

    Only scalars, statuses, and verification facts are copied; runtime
    registry/campaign payloads and raw reports are never echoed.
    """
    summary: Dict[str, Any] = {}
    if isinstance(build_result, Mapping):
        summary["build_status"] = _bounded_publication_text(
            build_result.get("status")
        )
        summary["build_stage"] = _bounded_publication_text(build_result.get("stage"))
        gates = build_result.get("adaptation_gates")
        if isinstance(gates, Mapping):
            summary["gate_playable_status"] = _bounded_publication_text(
                gates.get("playable_status")
            )
            gate_domains = gates.get("gates")
            if isinstance(gate_domains, Mapping):
                summary["gate_domains"] = sorted(
                    str(name) for name in gate_domains if str(name)
                )[:64]
    if isinstance(finisher_report, Mapping):
        summary["finisher_status"] = _bounded_publication_text(
            finisher_report.get("status")
        )
        summary["finisher_reason"] = _bounded_publication_text(
            finisher_report.get("reason")
        )
        summary["publication_status"] = _bounded_publication_text(
            finisher_report.get("publication_status")
        )
        stages = finisher_report.get("stages")
        if isinstance(stages, Mapping):
            registry_stage = stages.get("registry")
            if isinstance(registry_stage, Mapping):
                summary["registry_status"] = _bounded_publication_text(
                    registry_stage.get("status")
                )
                summary["registry_verified"] = bool(registry_stage.get("verified"))
                summary["registry_reason"] = _bounded_publication_text(
                    registry_stage.get("reason")
                )
            campaign_stage = stages.get("campaign_sync")
            if isinstance(campaign_stage, Mapping):
                summary["campaign_sync_status"] = _bounded_publication_text(
                    campaign_stage.get("status")
                )
                summary["campaign_visibility_verified"] = bool(
                    campaign_stage.get("campaign_visibility_verified")
                )
            publication_rollback = stages.get("publication_rollback")
            if isinstance(publication_rollback, Mapping):
                summary["rollback_status"] = _bounded_publication_text(
                    publication_rollback.get("status")
                )
                summary["rollback_verified"] = bool(
                    publication_rollback.get("verified")
                )
        rollback = finisher_report.get("rollback")
        if isinstance(rollback, Mapping):
            summary["rollback_status"] = _bounded_publication_text(
                rollback.get("status") or summary.get("rollback_status")
            )
            summary["rollback_verified"] = bool(rollback.get("verified"))
        python_authoritative = finisher_report.get("python_authoritative")
        if python_authoritative is not None:
            summary["python_authoritative"] = bool(python_authoritative)
    return summary


def _publication_blocked_result(
    route_decision: Any,
    reason_code: str,
    diagnostics: Any = None,
    *,
    module_name: str = "",
    handoff: Optional[Mapping[str, Any]] = None,
    build_result: Any = None,
    finisher_report: Any = None,
) -> Dict[str, Any]:
    """Return the explicit fail-closed publication outcome for one attempt."""
    publication = _bounded_publication_summary(build_result, finisher_report)
    if not publication.get("registry_status"):
        publication["registry_status"] = "not_attempted"
    if not publication.get("campaign_sync_status"):
        publication["campaign_sync_status"] = "not_attempted"
    if not publication.get("rollback_status"):
        publication["rollback_status"] = "not_attempted"
    result: Dict[str, Any] = {
        "contract_version": TEXT_PUBLICATION_CONTRACT_VERSION,
        "outcome": TEXT_WORKER_OUTCOME_BLOCKED,
        "status": TEXT_WORKER_STATUS_FAILED_CLOSED,
        "module_name": module_name,
        "route_decision": (
            dict(route_decision) if isinstance(route_decision, Mapping) else {}
        ),
        "reason_code": str(reason_code or "text_description_publication_blocked")[
            :MAX_SEAM_REASON_CODE_CHARS
        ],
        "diagnostics": _bounded_diagnostics(diagnostics),
        "adaptation_publication": publication,
    }
    if isinstance(handoff, Mapping):
        result["adaptation_handoff"] = _bounded_handoff_identity(handoff)
    return result


def _publication_revision_required_result(
    route_decision: Any,
    *,
    module_name: str,
    handoff: Optional[Mapping[str, Any]],
    build_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Project an eligible first content-gate failure without publishing."""
    classification = build_result.get("failure_classification")
    classification = classification if isinstance(classification, Mapping) else {}
    budget = build_result.get("revision_budget")
    budget = budget if isinstance(budget, Mapping) else classification.get("revision_budget")
    budget = budget if isinstance(budget, Mapping) else {}
    diagnostics = build_result.get("failure_diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = [{
            "code": str(build_result.get("failure_code") or "content_gate_failed")[:120],
            "message": str(build_result.get("error") or "content gate failed")[:320],
        }]
    result = _publication_blocked_result(
        route_decision,
        "adaptation_revision_required",
        diagnostics,
        module_name=module_name,
        handoff=handoff,
        build_result=build_result,
    )
    result["outcome"] = TEXT_WORKER_OUTCOME_SEMANTIC_REVISION
    result["status"] = TEXT_WORKER_STATUS_REVISION_REQUIRED
    result["reason_code"] = "adaptation_revision_required"
    result["retry_diagnostics"] = {
        "status": "available",
        "decision": "semantic_revision",
        "next_revision_eligible": True,
        "revision_eligible": True,
        "semantic_revision_eligible": True,
        "current_revision": budget.get("current_revision", 0),
        "max_revisions": budget.get("max_revisions", 1),
        "remaining_revisions": budget.get("remaining_before_failure", budget.get("remaining_revisions", 0)),
        "failure_class": classification.get("failure_class", "semantic"),
        "failure_code": classification.get("code") or build_result.get("failure_code"),
        "failed_stage": classification.get("stage") or build_result.get("failed_stage"),
        "failure_domain": classification.get("domain") or build_result.get("failure_domain"),
    }
    result["next_revision_eligible"] = True
    result["revision_budget"] = dict(budget)
    result["failure_classification"] = dict(classification)
    result["adaptation_publication"].update({
        "publication_status": "not_attempted",
        "registry_status": "not_attempted",
        "campaign_sync_status": "not_attempted",
        "rollback_status": "not_attempted",
        "publication_attempted": False,
    })
    return result


def _persist_final_adaptation_build_projection(
    *,
    workspace_path: str,
    job_id: str,
    handoff: Mapping[str, Any],
    staging_target: Mapping[str, Any],
    build_result: Mapping[str, Any],
) -> None:
    """Refresh the canonical attempt artifact after worker projection.

    The packet builder persists before the worker converts a blocked build into
    its public revision outcome. Keep that artifact aligned with the bounded
    Python-owned projection without touching the staged module or prior
    revision artifacts.
    """
    try:
        from web.extensions.toolkit_homebrew_packet_builder import (
            _persist_adaptation_attempt_report,
        )

        _persist_adaptation_attempt_report(
            workspace=Path(workspace_path),
            job_id=job_id,
            build_result=dict(build_result),
            adaptation_handoff=handoff,
            staging_target=staging_target,
            build_started_at=None,
            overwrite=True,
        )
    except Exception as persistence_error:
        # Artifact refresh is observability-only and must not change the
        # fail-closed publication outcome.
        warning(
            "TOOLKIT_ADAPTATION: Final build projection refresh failed: "
            f"{type(persistence_error).__name__}: {persistence_error}",
            category="toolkit_adaptation",
        )
        return


def _publication_revision_exhausted_result(
    route_decision: Any,
    *,
    module_name: str,
    handoff: Optional[Mapping[str, Any]],
    build_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Project an exhausted revision as terminal and explicitly non-retryable."""
    result = _publication_blocked_result(
        route_decision,
        "adaptation_revision_exhausted",
        build_result.get("failure_diagnostics") or [
            {
                "code": "revision_budget_exhausted",
                "message": "bounded semantic revision budget was exhausted",
            }
        ],
        module_name=module_name,
        handoff=handoff,
        build_result=build_result,
    )
    result["outcome"] = TEXT_WORKER_OUTCOME_BLOCKED
    result["status"] = TEXT_WORKER_STATUS_FAILED_CLOSED
    result["reason_code"] = "adaptation_revision_exhausted"
    budget = build_result.get("revision_budget")
    result["revision_budget"] = dict(budget) if isinstance(budget, Mapping) else {}
    result["next_revision_eligible"] = False
    result["revision_eligible"] = False
    result["semantic_revision_eligible"] = False
    result["retry_diagnostics"] = {
        "status": "exhausted",
        "decision": "blocked",
        "retryable": False,
        "next_revision_eligible": False,
        "revision_eligible": False,
        "semantic_revision_eligible": False,
        "current_revision": result["revision_budget"].get("current_revision", 0),
        "max_revisions": result["revision_budget"].get("max_revisions", 1),
        "remaining_revisions": 0,
        "failure_class": build_result.get("failure_class") or "semantic",
        "failure_code": build_result.get("failure_code") or "revision_budget_exhausted",
        "failed_stage": build_result.get("failed_stage") or "build",
        "failure_domain": build_result.get("failure_domain") or "semantic_revision",
    }
    return result


def _run_text_description_adaptation_publication(
    seam_result: Mapping[str, Any],
    *,
    build_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    finisher_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    adaptation_revision_callback: Optional[Callable[[Mapping[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Route a ready task 5.1 handoff through the shared publication transaction.

    Consumes the bounded ``authoring_ready_pending_publication`` seam result
    and runs the SAME ordered transaction used by uploaded adventures:

      1. staged packet/build output through the adaptation-aware packet
         builder (which runs the shared schema/mechanical/readiness gates and
         the semantic/report agreement composition against the reserved
         staging target);
      2. the shared adaptation finisher, which re-runs the gate order,
         persists provenance, generates and validates the Markdown summary,
         persists the pre-registration report, integrates the registry as the
         final stateful publication, verifies registry entries post-write,
         synchronizes the active campaign, and performs targeted rollback on
         any post-registration failure;
      3. a completed outcome ONLY after the finisher reports verified
         success. Every pre-publication or publication failure returns an
         explicit blocked outcome and never reports success, never falls
         through to the legacy direct builder, and never claims registry or
         campaign mutation.

    The packet builder and finisher helpers are imported lazily inside the
    function body so provider-free tests always inject deterministic fakes
    through ``build_runner``/``finisher_runner``. No module, registry, or
    campaign write is performed by this function itself.
    """
    route_decision: Any = {}
    handoff: Optional[Mapping[str, Any]] = None
    if isinstance(seam_result, Mapping):
        route_decision = seam_result.get("route_decision")
        if not isinstance(route_decision, Mapping):
            route_decision = {}
        handoff = seam_result.get("adaptation_handoff")
        if not isinstance(handoff, Mapping):
            handoff = None
    module_name = ""
    if handoff is not None:
        module_name = str(handoff.get("module_name") or "").strip()
    if (
        handoff is None
        or seam_result.get("outcome") != TEXT_WORKER_OUTCOME_AUTHORING_READY
    ):
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_handoff_invalid",
            [
                {
                    "code": "text_description_publication_handoff_invalid",
                    "message": "a ready adaptation authoring handoff is required",
                }
            ],
            module_name=module_name,
            handoff=handoff,
        )

    dossier = handoff.get("dossier")
    if not isinstance(dossier, Mapping):
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_dossier_missing",
            [
                {
                    "code": "text_description_publication_dossier_missing",
                    "message": "the ready handoff lost the validated dossier",
                }
            ],
            module_name=module_name,
            handoff=handoff,
        )
    staging_target = handoff.get("staging_target")
    if not isinstance(staging_target, Mapping) or not str(
        staging_target.get("path") or ""
    ).strip():
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_staging_missing",
            [
                {
                    "code": "text_description_publication_staging_missing",
                    "message": "the ready handoff lost the reserved staging target",
                }
            ],
            module_name=module_name,
            handoff=handoff,
        )
    workspace_path = str(handoff.get("workspace_path") or "").strip()
    if not module_name or not workspace_path:
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_handoff_invalid",
            [
                {
                    "code": "text_description_publication_handoff_invalid",
                    "message": "module name and workspace reference are required",
                }
            ],
            module_name=module_name,
            handoff=handoff,
        )
    if Path(workspace_path).is_absolute():
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_workspace_invalid",
            [
                {
                    "code": "text_description_publication_workspace_invalid",
                    "message": "attempt workspace must be a project-relative reference",
                }
            ],
            module_name=module_name,
            handoff=handoff,
        )
    provenance = handoff.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    attempt = handoff.get("attempt")
    attempt = attempt if isinstance(attempt, Mapping) else {}
    job_id = str(attempt.get("job_id") or "").strip()

    def _progress(phase: str, message: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(phase, message)
        except Exception:
            pass

    if build_runner is None:
        try:
            from web.extensions.toolkit_homebrew_packet_builder import (
                run_toolkit_homebrew_packet_build,
            )

            build_runner = run_toolkit_homebrew_packet_build
        except Exception as import_error:
            return _publication_blocked_result(
                route_decision,
                "text_description_publication_build_unavailable",
                [
                    {
                        "code": "text_description_publication_build_unavailable",
                        "message": str(import_error)[:MAX_SEAM_DIAGNOSTIC_CHARS]
                        or "the shared packet builder is unavailable",
                    }
                ],
                module_name=module_name,
                handoff=handoff,
            )

    _progress("adaptation_build", "Running the staged adaptation build and shared gates...")
    try:
        build_result = build_runner(
            Path(workspace_path),
            job_id,
            progress_callback=progress_callback,
            adaptation_route=BUILD_MODE_LLM_ADAPTATION,
            adaptation_dossier=dossier,
            adaptation_provenance=provenance,
            adaptation_staging_root=str(
                handoff.get("staging_root") or DEFAULT_ADAPTATION_STAGING_ROOT
            ),
            adaptation_staging_target=staging_target,
            adaptation_convergence_callback=adaptation_convergence_callback,
            adaptation_revision_callback=adaptation_revision_callback,
        )
    except Exception as build_error:
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_build_infrastructure_failure",
            [
                {
                    "code": "text_description_publication_build_infrastructure_failure",
                    "message": str(build_error)[:MAX_SEAM_DIAGNOSTIC_CHARS]
                    or "the staged adaptation build failed",
                }
            ],
            module_name=module_name,
            handoff=handoff,
        )
    if not isinstance(build_result, Mapping):
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_build_result_missing",
            [
                {
                    "code": "text_description_publication_build_result_missing",
                    "message": "the shared packet builder returned no result",
                }
            ],
            module_name=module_name,
            handoff=handoff,
        )
    build_status = str(build_result.get("status") or "failed").strip().lower()
    if build_status != "success":
        revision_budget = build_result.get("revision_budget")
        classification = build_result.get("failure_classification")
        exhausted = (
            isinstance(revision_budget, Mapping)
            and revision_budget.get("decision") == "exhausted"
        ) or (
            isinstance(classification, Mapping)
            and isinstance(classification.get("revision_budget"), Mapping)
            and classification["revision_budget"].get("decision") == "exhausted"
        )
        if exhausted:
            if isinstance(revision_budget, Mapping):
                exhausted_budget = dict(revision_budget)
            elif isinstance(classification, Mapping) and isinstance(
                classification.get("revision_budget"), Mapping
            ):
                exhausted_budget = dict(classification["revision_budget"])
            else:
                exhausted_budget = {}
            exhausted_budget["remaining_revisions"] = 0
            exhausted_budget["remaining_before_failure"] = 0
            exhausted_budget["decision"] = "exhausted"
            build_result = dict(build_result)
            build_result.update(
                {
                    "revision_budget": exhausted_budget,
                    "revision_eligible": False,
                    "next_revision_eligible": False,
                    "semantic_revision_eligible": False,
                    "semantic_revision_budget_consumed": True,
                }
            )
            _persist_final_adaptation_build_projection(
                workspace_path=workspace_path,
                job_id=job_id,
                handoff=handoff,
                staging_target=staging_target,
                build_result=build_result,
            )
            return _publication_revision_exhausted_result(
                route_decision,
                module_name=module_name,
                handoff=handoff,
                build_result=build_result,
            )
        if (
            build_result.get("next_revision_eligible") is True
            and build_result.get("revision_eligible") is True
            and str(build_result.get("failure_class") or "").lower()
            in {"semantic", "mechanical"}
        ):
            _persist_final_adaptation_build_projection(
                workspace_path=workspace_path,
                job_id=job_id,
                handoff=handoff,
                staging_target=staging_target,
                build_result=build_result,
            )
            return _publication_revision_required_result(
                route_decision,
                module_name=module_name,
                handoff=handoff,
                build_result=build_result,
            )
        build_stage = _bounded_publication_text(build_result.get("stage"))
        build_error_text = _bounded_publication_text(build_result.get("error"))
        return _publication_blocked_result(
            route_decision,
            "text_description_adaptation_build_blocked",
            [
                {
                    "code": "text_description_adaptation_build_blocked",
                    "message": build_error_text
                    or f"staged adaptation build ended at {build_stage}",
                }
            ],
            module_name=module_name,
            handoff=handoff,
            build_result=build_result,
        )

    build_identity = _validate_current_build_result(build_result, handoff)
    if build_identity.get("status") != "pass":
        reason_code = str(
            build_identity.get("reason_code")
            or "text_description_adaptation_build_artifact_stale"
        )
        return _publication_blocked_result(
            route_decision,
            reason_code,
            [
                {
                    "code": reason_code,
                    "message": "current adaptation build identity does not match the retry handoff",
                },
                *[
                    {"code": "artifact_identity", "message": item}
                    for item in (build_identity.get("diagnostics") or [])[:4]
                ],
            ],
            module_name=module_name,
            handoff=handoff,
            build_result=build_result,
        )

    module_slug = (
        str(build_result.get("module_name") or "").strip() or module_name
    )
    finisher_gates = build_result.get("adaptation_gates")
    if not isinstance(finisher_gates, Mapping):
        finisher_gates = None
    staging_target_used = build_result.get("staging_target")
    if not isinstance(staging_target_used, Mapping):
        staging_target_used = staging_target
    module_dir = str(build_result.get("output_directory") or "").strip() or None
    provenance_used = build_result.get("adaptation_provenance")
    if not isinstance(provenance_used, Mapping):
        provenance_used = provenance
    artifact_workspace = (
        str(build_result.get("adaptation_artifact_workspace") or "").strip()
        or None
    )

    if finisher_runner is None:
        try:
            from web.extensions.toolkit_module_finisher import (
                run_toolkit_module_postbuild_finishing,
            )

            finisher_runner = run_toolkit_module_postbuild_finishing
        except Exception as import_error:
            return _publication_blocked_result(
                route_decision,
                "text_description_publication_finisher_unavailable",
                [
                    {
                        "code": "text_description_publication_finisher_unavailable",
                        "message": str(import_error)[:MAX_SEAM_DIAGNOSTIC_CHARS]
                        or "the shared adaptation finisher is unavailable",
                    }
                ],
                module_name=module_slug,
                handoff=handoff,
                build_result=build_result,
            )

    _progress(
        "adaptation_readiness",
        "Running the shared readiness, report, Markdown, registry, campaign, "
        "and rollback transaction...",
    )
    try:
        finisher_report = finisher_runner(
            module_slug,
            strict=True,
            adaptation_mode=BUILD_MODE_LLM_ADAPTATION,
            adaptation_gates=finisher_gates,
            adaptation_staging_target=staging_target_used,
            adaptation_module_dir=module_dir,
            adaptation_provenance=provenance_used,
            adaptation_artifact_workspace=artifact_workspace,
        )
    except Exception as finisher_error:
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_finisher_infrastructure_failure",
            [
                {
                    "code": "text_description_publication_finisher_infrastructure_failure",
                    "message": str(finisher_error)[:MAX_SEAM_DIAGNOSTIC_CHARS]
                    or "the shared adaptation finisher failed",
                }
            ],
            module_name=module_slug,
            handoff=handoff,
            build_result=build_result,
        )
    if not isinstance(finisher_report, Mapping):
        return _publication_blocked_result(
            route_decision,
            "text_description_publication_finisher_result_missing",
            [
                {
                    "code": "text_description_publication_finisher_result_missing",
                    "message": "the shared adaptation finisher returned no report",
                }
            ],
            module_name=module_slug,
            handoff=handoff,
            build_result=build_result,
        )
    finisher_status = str(finisher_report.get("status") or "failed").strip().lower()
    if finisher_status != "success":
        finisher_reason = _bounded_publication_text(finisher_report.get("reason"))
        return _publication_blocked_result(
            route_decision,
            finisher_reason or "text_description_publication_blocked",
            [
                {
                    "code": "text_description_publication_finisher_not_success",
                    "message": (
                        f"shared publication transaction ended with "
                        f"{finisher_status}"
                    ),
                }
            ],
            module_name=module_slug,
            handoff=handoff,
            build_result=build_result,
            finisher_report=finisher_report,
        )

    _progress("adaptation_completed", "Adaptation publication verified.")
    return {
        "contract_version": TEXT_PUBLICATION_CONTRACT_VERSION,
        "outcome": TEXT_WORKER_OUTCOME_COMPLETED,
        "status": TEXT_WORKER_STATUS_COMPLETED,
        "module_name": module_slug,
        "route_decision": dict(route_decision),
        "adaptation_handoff": _bounded_handoff_identity(handoff),
        "adaptation_publication": _bounded_publication_summary(
            build_result, finisher_report
        ),
        "reason_code": "text_description_adaptation_published",
        "diagnostics": [],
    }


def run_text_description_adaptation_seam(*args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]:
    """Run the text adaptation seam inside the opt-in output boundary."""
    with AdaptationOutputSafety(
        phase="adaptation_authoring", status="running", redirect_streams=True
    ):
        return _run_text_description_adaptation_seam(*args, **kwargs)


def run_text_description_adaptation_publication(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Run text adaptation publication with safe progress and streams."""
    progress_callback = kwargs.get("progress_callback")

    def safe_progress(phase: Any, message: Any) -> None:
        with_scope = scope.emit({
            "phase": phase,
            "status": "running",
            "code": phase,
            "message": message,
        })
        if progress_callback is not None:
            try:
                progress_callback(with_scope["phase"], with_scope.get("message", ""))
            except Exception:
                pass

    kwargs["progress_callback"] = safe_progress
    with AdaptationOutputSafety(
        phase="adaptation_build", status="running", redirect_streams=True
    ) as scope:
        return _run_text_description_adaptation_publication(*args, **kwargs)


def validate_text_description_publication_result(result: Any) -> Dict[str, Any]:
    """Validate a bounded text-description publication result (round trip)."""
    if not isinstance(result, Mapping):
        return {"valid": False, "ok": False, "reason": "not_a_mapping"}
    if result.get("contract_version") != TEXT_PUBLICATION_CONTRACT_VERSION:
        return {"valid": False, "ok": False, "reason": "contract_version_mismatch"}
    outcome = str(result.get("outcome") or "")
    if outcome == TEXT_WORKER_OUTCOME_COMPLETED:
        if result.get("status") != TEXT_WORKER_STATUS_COMPLETED:
            return {"valid": False, "ok": False, "reason": "completed_status_mismatch"}
    elif outcome == TEXT_WORKER_OUTCOME_BLOCKED:
        if result.get("status") != TEXT_WORKER_STATUS_FAILED_CLOSED:
            return {"valid": False, "ok": False, "reason": "blocked_status_mismatch"}
    else:
        return {"valid": False, "ok": False, "reason": "invalid_outcome"}
    if not isinstance(result.get("adaptation_publication"), Mapping):
        return {
            "valid": False,
            "ok": False,
            "reason": "publication_summary_missing",
        }
    if not isinstance(result.get("adaptation_handoff"), Mapping):
        return {"valid": False, "ok": False, "reason": "handoff_identity_missing"}
    module_name = str(result.get("module_name") or "").strip()
    if (
        not module_name
        or "/" in module_name
        or "\\" in module_name
        or ".." in module_name
    ):
        return {"valid": False, "ok": False, "reason": "module_name_not_path_safe"}
    reason_code = str(result.get("reason_code") or "").strip()
    if not reason_code:
        return {"valid": False, "ok": False, "reason": "reason_code_missing"}
    return {"valid": True, "ok": True, "reason": "valid"}


__all__ = [
    "MAX_SEAM_DIAGNOSTIC_CHARS",
    "MAX_SEAM_DIAGNOSTICS",
    "MAX_SEAM_JOB_ID_CHARS",
    "MAX_SEAM_REASON_CODE_CHARS",
    "TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION",
    "TEXT_PUBLICATION_CONTRACT_VERSION",
    "TEXT_WORKER_OUTCOME_AUTHORING_READY",
    "TEXT_WORKER_OUTCOME_BLOCKED",
    "TEXT_WORKER_OUTCOME_COMPLETED",
    "TEXT_WORKER_STATUS_COMPLETED",
    "TEXT_WORKER_STATUS_FAILED_CLOSED",
    "TEXT_WORKER_STATUS_READY",
    "run_text_description_adaptation_publication",
    "run_text_description_adaptation_seam",
    "validate_text_description_publication_result",
]
