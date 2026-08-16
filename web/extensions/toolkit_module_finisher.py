# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Web Extension - Toolkit module post-build finishing helper.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from utils.enhanced_logger import error, info, warning
from utils.file_operations import safe_read_json, safe_write_json
from utils.module_semantic_authority import enrich_module_semantic_authority
from utils.toolkit_report_agreement import compose_report_agreement


_TOOLKIT_REPORT_FRESHNESS_CONTRACT_VERSION = "toolkit_build_report_refresh_contract.v1"


def _utc_now_iso() -> str:
    """Return UTC timestamp in ISO-8601 format."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _normalize_stage_status(status: str) -> str:
    """Normalize stage status into success/degraded/failed."""
    normalized = str(status or "").strip().lower()
    if normalized in {"success", "ok", "passed"}:
        return "success"
    if normalized in {"degraded", "warning", "warn", "partial", "skipped"}:
        return "degraded"
    return "failed"


def _derive_report_freshness(
    *,
    status: str,
    phase: str,
    ready_status: str,
    publishable_status: str,
    workflow: str,
    refresh_reason: str,
) -> Dict[str, Any]:
    """Build machine-readable freshness metadata for toolkit reports."""
    normalized_phase = str(phase or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    normalized_ready = str(ready_status or "").strip().lower()
    normalized_publishable = str(publishable_status or "").strip().lower()

    if (
        normalized_phase == "pre_publishability"
        or normalized_ready == "pending"
        or normalized_publishable == "pending"
    ):
        freshness_state = "stale"
        authoritative = False
        stale_reason = "publishability_pending"
    elif normalized_status == "degraded":
        freshness_state = "degraded"
        authoritative = True
        stale_reason = None
    else:
        freshness_state = "current"
        authoritative = True
        stale_reason = None

    return {
        "state": freshness_state,
        "authoritative": authoritative,
        "written_at": _utc_now_iso(),
        "phase": phase,
        "workflow": str(workflow or "toolkit_postbuild_finisher"),
        "refresh_reason": str(refresh_reason or "postbuild_finishing"),
        "contract": _TOOLKIT_REPORT_FRESHNESS_CONTRACT_VERSION,
        "stale_reason": stale_reason,
    }


def _run_continuity_stage(
    module_slug: str, module_dir: Path, strict: bool
) -> Dict[str, Any]:
    """Run continuity normalization/enrichment stage."""
    from scripts.homebrew_ingest_dev import (
        _ensure_continuity_contract_keys,
        _normalize_continuity_contract,
        enrich_continuity_cross_refs,
    )

    context_path = module_dir / "module_context.json"
    plot_path = module_dir / "module_plot.json"

    if not context_path.exists() or not plot_path.exists():
        return {
            "status": "failed",
            "reason": "Required module context or plot file missing",
            "context_path": str(context_path),
            "plot_path": str(plot_path),
        }

    module_context = safe_read_json(str(context_path)) or {}
    module_plot = safe_read_json(str(plot_path)) or {}

    continuity_patch = _ensure_continuity_contract_keys(module_context, module_slug)
    module_context = continuity_patch.get("module_context", module_context)

    continuity_enrichment = enrich_continuity_cross_refs(
        module_slug=module_slug,
        module_context=module_context,
        module_plot=module_plot,
    )
    module_context = continuity_enrichment.get("module_context", module_context)

    changed = bool(continuity_patch.get("changed")) or bool(
        continuity_enrichment.get("changed")
    )
    if changed:
        write_ok = safe_write_json(str(context_path), module_context)
        if not write_ok:
            return {
                "status": "failed",
                "reason": "Failed to persist continuity normalization",
                "continuity_patch": continuity_patch,
                "continuity_enrichment": continuity_enrichment,
            }

    continuity_contract = _normalize_continuity_contract(
        module_context=module_context,
        module_plot=module_plot,
        strict=strict,
        alias_registry=None,
    )
    contract_status = str(continuity_contract.get("status", "success"))

    if strict and contract_status == "error":
        stage_status = "failed"
    elif contract_status in {"warning"}:
        stage_status = "degraded"
    else:
        stage_status = "success"

    return {
        "status": stage_status,
        "continuity_patch": continuity_patch,
        "continuity_enrichment": continuity_enrichment,
        "continuity_contract": continuity_contract,
        "context_path": str(context_path),
    }


def _run_registry_stage(module_slug: str) -> Dict[str, Any]:
    """Run registry verification and best-effort integration."""
    from core.generators.module_stitcher import ModuleStitcher
    from scripts.homebrew_registry_guard import verify_present

    verify_before = verify_present(module_slug)
    if verify_before.get("present", False):
        return {
            "status": "success",
            "verify_before": verify_before,
            "integration_attempted": False,
        }

    integration_attempted = True
    integration_success = False
    integration_error = None

    try:
        stitcher = ModuleStitcher()
        integration_success = bool(stitcher.integrate_module(module_slug))
        provider_stage_errors = list(
            getattr(stitcher, "provider_stage_errors", []) or []
        )
    except Exception as stitch_error:
        integration_error = str(stitch_error)
        provider_stage_errors = []

    verify_after = verify_present(module_slug)
    if verify_after.get("present", False):
        result = {
            "status": "degraded" if provider_stage_errors else "success",
            "verify_before": verify_before,
            "verify_after": verify_after,
            "integration_attempted": integration_attempted,
            "integration_success": integration_success,
            "integration_error": integration_error,
        }
        if provider_stage_errors:
            result["provider_stage_errors"] = provider_stage_errors
        return result

    return {
        "status": "failed",
        "reason": "Module not present in registry after integration attempt",
        "verify_before": verify_before,
        "verify_after": verify_after,
        "integration_attempted": integration_attempted,
        "integration_success": integration_success,
        "integration_error": integration_error,
    }


def _sync_context_backup(module_dir: Path, module_slug: str) -> bool:
    """Mirror module_context.json to module_context_BU.json atomically.

    Returns True if both files exist in parity after the call.
    Used after in-place mutations to keep canonical backup current.
    """
    ctx_path = module_dir / "module_context.json"
    bu_path = module_dir / "module_context_BU.json"

    if not ctx_path.exists():
        return False

    try:
        payload = safe_read_json(str(ctx_path))
        if not payload or not isinstance(payload, dict):
            return False
        return safe_write_json(str(bu_path), payload)
    except Exception:
        warning(
            f"TOOLKIT_FINISHER: Failed to sync module_context_BU.json for {module_slug}",
            category="module_ingest",
        )
        return False


def _run_context_backup_parity_stage(module_dir: Path) -> Dict[str, Any]:
    """Verify module_context.json and module_context_BU.json are in exact parity.

    Must run AFTER all possible context mutations (classification, semantic
    authority, enrichment). A mismatch or missing file blocks playable status
    through the report-agreement stage.
    """
    context_path = module_dir / "module_context.json"
    backup_path = module_dir / "module_context_BU.json"

    if not context_path.exists() or not backup_path.exists():
        return {
            "status": "failed",
            "reason": "context_backup_missing",
            "context_path": str(context_path),
            "backup_path": str(backup_path),
        }

    live = safe_read_json(str(context_path))
    backup = safe_read_json(str(backup_path))
    if not isinstance(live, dict) or not isinstance(backup, dict):
        return {"status": "failed", "reason": "context_backup_invalid_json"}

    if live != backup:
        return {"status": "failed", "reason": "context_backup_mismatch"}

    return {"status": "success"}


def _run_semantic_authority_stage(module_slug: str, module_dir: Path) -> Dict[str, Any]:
    """Run semantic-authority enrichment stage (non-blocking in this phase)."""
    context_path = module_dir / "module_context.json"
    plot_path = module_dir / "module_plot.json"

    if not context_path.exists() or not plot_path.exists():
        return {
            "status": "degraded",
            "reason": "Semantic authority stage skipped due to missing context/plot file",
            "context_path": str(context_path),
            "plot_path": str(plot_path),
            "semantic_authority": {},
            "warnings": ["semantic_authority_missing_context_or_plot"],
            "errors": [],
        }

    module_context = safe_read_json(str(context_path)) or {}
    module_plot = safe_read_json(str(plot_path)) or {}

    stage_result = enrich_module_semantic_authority(
        module_slug=module_slug,
        module_context=module_context,
        module_plot=module_plot,
        module_dir=module_dir,
    )

    if stage_result.get("changed"):
        write_ok = safe_write_json(
            str(context_path), stage_result.get("module_context") or module_context
        )
        if not write_ok:
            stage_result["status"] = "degraded"
            stage_result.setdefault("warnings", []).append(
                f"Failed to persist semantic authority payload to {context_path}"
            )
        else:
            # TABLETOP MODE: Sync BU backup after live context mutation.
            if not _sync_context_backup(module_dir, module_slug):
                stage_result["status"] = "degraded"
                stage_result.setdefault("warnings", []).append(
                    "context_backup_sync_failed"
                )

    if stage_result.get("status") == "failed":
        return {
            "status": "degraded",
            "reason": "Semantic authority enrichment reported failure (fail-open this phase)",
            "semantic_authority": stage_result.get("semantic_authority", {}),
            "warnings": stage_result.get("warnings", []),
            "errors": stage_result.get("errors", []),
        }

    return {
        "status": stage_result.get("status", "success"),
        "semantic_authority": stage_result.get("semantic_authority", {}),
        "warnings": stage_result.get("warnings", []),
        "errors": stage_result.get("errors", []),
    }


def _run_monster_materialization_stage(module_slug: str) -> Dict[str, Any]:
    """Run module-local monster materialization stage."""
    try:
        from scripts.homebrew_materialize_monsters import materialize_monsters

        parsed_output = materialize_monsters(
            module_slug=module_slug,
            strict=False,
            dry_run=False,
        )
    except Exception as mat_error:
        return {
            "status": "failed",
            "reason": f"Monster materialization invocation failed: {mat_error}",
        }

    blocked_count = int(parsed_output.get("blocked_count", 0) or 0)
    blocker_classes = parsed_output.get("blocker_classes") or {}
    parsed_status = _normalize_stage_status(parsed_output.get("status", "success"))
    if blocked_count > 0:
        stage_status = "failed"
    else:
        stage_status = parsed_status

    if stage_status == "failed":
        if blocked_count > 0:
            stage_reason = (
                "Monster hydration blocked by structured blocker classes: "
                f"{', '.join(sorted(blocker_classes.keys())) or 'unknown'}"
            )
        else:
            stage_reason = "Monster materialization reported failure"
    elif stage_status == "degraded":
        stage_reason = "Monster materialization completed with degraded status"
    else:
        stage_reason = None

    return {
        "status": stage_status,
        "reason": stage_reason,
        "returncode": 0,
        "parsed_output": parsed_output,
    }


def _detect_media_only_debt(publishability_stage: Dict[str, Any]) -> bool:
    """Detect if publishability gate failed only because media is missing.

    The finisher receives a wrapped stage payload from `_run_publishability_stage()`
    where the raw audit report is under `publishability_stage["report"]`.
    """
    if not isinstance(publishability_stage, dict):
        return False

    report = publishability_stage.get("report") or {}
    if not isinstance(report, dict):
        return False

    publishable_status = str(
        publishability_stage.get("publishable_status")
        or report.get("publishable_status")
        or ""
    ).strip().lower()
    if publishable_status != "fail":
        return False

    readiness_report = report.get("readiness") or {}
    readiness_status = str(readiness_report.get("overall_status") or "").strip().lower()
    ready_status = str(
        publishability_stage.get("ready_status") or report.get("ready_status") or ""
    ).strip().lower()

    categories = report.get("remediation_categories") or []
    if "structured_monster_media_missing" not in categories:
        return False
    if "mixed_media_semantic_blocking" in categories:
        return False
    if "semantic_publishability_blocking" in categories:
        return False

    toolkit_media_policy = report.get("toolkit_media_policy") or {}
    structural_media_debt_count = int(
        toolkit_media_policy.get("structural_media_debt_count") or 0
    )
    if structural_media_debt_count <= 0:
        return False

    if ready_status == "pass" and readiness_status == "pass":
        readiness_is_media_only = True
    elif ready_status == "fail" and readiness_status == "fail":
        gates = readiness_report.get("gates") or {}
        failed_gates = sorted(
            gate_name
            for gate_name, gate in gates.items()
            if isinstance(gate, dict)
            and str(gate.get("status") or "").strip().lower() == "fail"
        )
        readiness_is_media_only = failed_gates == ["gameplay"]
    else:
        readiness_is_media_only = False

    if not readiness_is_media_only:
        return False

    blocking_errors = report.get("blocking_errors") or []
    if not blocking_errors:
        return True

    media_related_terms = (
        "media",
        "monster",
        "portrait",
        "image",
        "readiness_gate_failed",
        "gameplay_gate_failed",
    )
    return all(
        any(term in str(item or "").lower() for term in media_related_terms)
        for item in blocking_errors
    )


def _extract_media_debt_details(publishability_stage: Dict[str, Any]) -> Dict[str, Any]:
    """Extract missing media debt details for handoff reporting."""
    if not isinstance(publishability_stage, dict):
        return {}

    report = publishability_stage.get("report") or {}
    if not isinstance(report, dict):
        return {}

    toolkit_media_policy = report.get("toolkit_media_policy") or {}
    debt_slugs = toolkit_media_policy.get("structural_media_debt_slugs") or []
    normalized_slugs = [
        str(slug).strip()
        for slug in debt_slugs
        if str(slug or "").strip()
    ]
    media_debt_count = int(
        toolkit_media_policy.get("structural_media_debt_count") or len(normalized_slugs)
    )

    return {
        "media_debt_count": media_debt_count,
        "media_debt_slugs": normalized_slugs,
        "media_debt_workflow": (
            "Module Builder -> Module Media Generator"
        ),
        "media_debt_workflow_detail": (
            "Toolkit modules require manual monster portrait generation. "
            "Use: Module Builder -> Module Media Generator -> Generate Monster Images"
        ),
    }


def _run_llm_classification_stage(
    module_slug: str, module_dir: Path
) -> Dict[str, Any]:
    from web.extensions.toolkit_llm_classification import (
        is_classification_enabled,
        run_llm_classification_pass,
        apply_entity_classifications,
        apply_destination_classifications,
        apply_npc_visibility_classifications,
        persist_classification_metadata,
    )

    if not is_classification_enabled():
        return {"status": "skipped", "reason": "classification_disabled"}

    try:
        class_result = run_llm_classification_pass(
            str(module_dir), module_slug
        )
        if class_result.get("status") != "success":
            return {
                "status": "degraded",
                "reason": "classification_failed",
                "classification": class_result,
            }

        classifications = class_result.get("classifications", {})
        entity_apply = apply_entity_classifications(
            str(module_dir), classifications.get("entity", {})
        )
        dest_apply = apply_destination_classifications(
            str(module_dir), classifications.get("destination", {})
        )
        npc_apply = apply_npc_visibility_classifications(
            str(module_dir), classifications.get("npc_visibility", {})
        )
        persist_classification_metadata(
            str(module_dir),
            classifications.get("entity", {}),
            classifications.get("destination", {}),
            classifications.get("npc_visibility", {}),
        )

        # TABLETOP MODE: Mirror classification_metadata to module_context_BU.json
        if not _sync_context_backup(module_dir, module_slug):
            return {
                "status": "degraded",
                "reason": "context_backup_sync_failed",
                "classification_summary": class_result.get("summaries", {}),
                "applied": {
                    "entity": entity_apply,
                    "destination": dest_apply,
                    "npc_visibility": npc_apply,
                },
            }

        return {
            "status": "success",
            "classification_summary": class_result.get("summaries", {}),
            "applied": {
                "entity": entity_apply,
                "destination": dest_apply,
                "npc": npc_apply,
            },
        }
    except Exception as exc:
        warning(
            f"LLM classification stage failed for {module_slug}: {exc}",
            category="llm_classification",
        )
        return {"status": "degraded", "reason": f"classification_exception: {exc}"}


def _run_llm_remediation_stage(
    module_slug: str,
    module_dir: Path,
    publishability_stage: Dict[str, Any],
) -> Dict[str, Any]:
    from web.extensions.toolkit_llm_classification import (
        is_classification_enabled,
        build_remediation_proposal_batch,
        call_llm_remediation_proposals,
        validate_remediation_proposals,
    )

    if not is_classification_enabled():
        return {"status": "skipped", "reason": "classification_disabled"}

    blocker_report = publishability_stage.get("report", {})
    if not blocker_report:
        return {"status": "skipped", "reason": "no_publishability_report"}

    blocker_classes = blocker_report.get(
        "remediation_categories",
        blocker_report.get("failure_categories", []),
    )
    if not blocker_classes:
        return {"status": "skipped", "reason": "no_blockers"}

    try:
        batch = build_remediation_proposal_batch(
            str(module_dir), blocker_report
        )
        if not batch:
            return {"status": "skipped", "reason": "no_affordances"}

        provider_errors: List[Dict[str, Any]] = []
        proposals = call_llm_remediation_proposals(
            batch, error_sink=provider_errors
        )
        if not proposals:
            result = {"status": "skipped", "reason": "api_returned_empty"}
            if provider_errors:
                result["status"] = "degraded"
                result["provider_errors"] = provider_errors
            return result

        validated = validate_remediation_proposals(
            str(module_dir), proposals
        )
        valid_count = sum(
            1
            for p in validated
            if p.get("safety", "").startswith(("pass", "warning"))
        )

        result = {
            "status": "degraded" if provider_errors else "success",
            "proposal_count": len(proposals),
            "valid_count": valid_count,
            "proposals": validated,
        }
        if provider_errors:
            result["provider_errors"] = provider_errors
        return result
    except Exception as exc:
        warning(
            f"LLM remediation stage failed for {module_slug}: {exc}",
            category="llm_classification",
        )
        return {"status": "degraded", "reason": f"remediation_exception: {exc}"}


def _run_publishability_stage(module_slug: str, source: str = "watcher") -> Dict[str, Any]:
    """Run standalone publishability audit stage."""
    from scripts.audit_module_publishability import audit_module_publishability

    report = audit_module_publishability(module_slug, source=source)
    ready_status = str(report.get("ready_status", "fail") or "fail")
    publishable_status = str(report.get("publishable_status", "fail") or "fail")

    if publishable_status == "pass":
        stage_status = "success"
    elif ready_status == "pass":
        stage_status = "degraded"
    else:
        stage_status = "failed"

    return {
        "status": stage_status,
        "ready_status": ready_status,
        "publishable_status": publishable_status,
        "source": source,
        "report": report,
    }


def run_toolkit_module_postbuild_finishing(
    module_slug: str,
    strict: bool = True,
    refresh_reason: str = "postbuild_finishing",
    refresh_workflow: str = "toolkit_postbuild_finisher",
    extra_stages: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run post-build publication parity stages for toolkit-generated modules."""
    module_slug = str(module_slug or "").strip()
    if not module_slug:
        return {
            "status": "failed",
            "module_slug": module_slug,
            "reason": "Missing module slug",
            "stages": {},
        }

    module_dir = Path("modules") / module_slug
    if not module_dir.exists() or not module_dir.is_dir():
        return {
            "status": "failed",
            "module_slug": module_slug,
            "reason": "Module directory not found",
            "module_dir": str(module_dir),
            "stages": {},
        }

    info(
        f"TOOLKIT_FINISHER: Starting post-build finishing for {module_slug}",
        category="module_ingest",
    )

    stages: Dict[str, Dict[str, Any]] = {}
    overall_status = "success"

    # Ingest extra stages from caller (e.g., seed/enrichment status from v2 builds)
    if extra_stages and isinstance(extra_stages, dict):
        for stage_key, stage_payload in extra_stages.items():
            if stage_key not in stages and isinstance(stage_payload, dict):
                stages[stage_key] = stage_payload

    continuity_stage = _run_continuity_stage(
        module_slug=module_slug, module_dir=module_dir, strict=strict
    )
    stages["continuity"] = continuity_stage
    if continuity_stage.get("status") == "failed":
        overall_status = "failed"
    elif continuity_stage.get("status") == "degraded":
        overall_status = "degraded"

    semantic_authority_stage = _run_semantic_authority_stage(
        module_slug=module_slug, module_dir=module_dir
    )
    stages["semantic_authority"] = semantic_authority_stage
    if (
        semantic_authority_stage.get("status") in {"failed", "degraded"}
        and overall_status != "failed"
    ):
        overall_status = "degraded"

    registry_stage = _run_registry_stage(module_slug=module_slug)
    stages["registry"] = registry_stage
    if registry_stage.get("status") == "failed":
        overall_status = "failed"
    elif registry_stage.get("status") == "degraded" and overall_status != "failed":
        overall_status = "degraded"

    materialization_stage = _run_monster_materialization_stage(module_slug=module_slug)
    stages["monster_materialization"] = materialization_stage
    if materialization_stage.get("status") == "failed":
        overall_status = "failed"
    elif (
        materialization_stage.get("status") == "degraded" and overall_status != "failed"
    ):
        overall_status = "degraded"

    # TABLETOP MODE: LLM-assisted narrative classification (Phase 2)
    llm_classification_stage = _run_llm_classification_stage(
        module_slug=module_slug, module_dir=module_dir
    )
    stages["llm_classification"] = llm_classification_stage
    if (
        llm_classification_stage.get("status") == "degraded"
        and overall_status != "failed"
    ):
        overall_status = "degraded"

    # Generate Homebrewery module adventure summary
    try:
        from utils.homebrewery_adventure_writer import generate_homebrewery_adventure
        md = generate_homebrewery_adventure(module_slug)
        if md and len(md) > 100:
            md_path = module_dir / "MODULE_SUMMARY.md"
            with open(str(md_path), "w", encoding="utf-8") as f:
                f.write(md)
            stages["module_summary"] = {
                "status": "success",
                "path": str(md_path),
                "bytes": len(md),
            }
        else:
            stages["module_summary"] = {
                "status": "degraded",
                "reason": "generated_content_too_short",
                "bytes": len(md) if md else 0,
            }
            overall_status = "degraded"
    except Exception as exc:
        error(
            f"TOOLKIT_FINISHER: Failed to generate module summary for {module_slug}: {exc}",
            category="module_ingest",
        )
        stages["module_summary"] = {
            "status": "degraded",
            "reason": "generation_exception",
            "exception": str(exc),
        }
        overall_status = "degraded"

    def _run_report_agreement_stage(
        publishability_result: Dict[str, Any],
        final_ready_status: str,
        final_publishable_status: str,
        pipeline_overall_status: str,
        source_fidelity_report_persisted: bool,
    ) -> Dict[str, Any]:
        """Run report-agreement check using in-memory pipeline data.

        Uses final override statuses (post media-handoff, post degradation)
        rather than raw stage data. Passes actual pipeline status to avoid
        hiding contradictions behind hardcoded values.

        If source_fidelity_report.json could not be persisted to disk, the
        missing report is treated as a playable blocker.
        """
        try:
            from utils.toolkit_report_agreement import _derive_validation_status

            pub_report = publishability_result.get("report", {}) or {}
            sf_s = str(pub_report.get("source_fidelity_status", "unknown") or "unknown")
            eps = str(pub_report.get("effective_publishable_status", "unknown") or "unknown")
            ready_s = str(final_ready_status or "").strip().lower()
            pub_s = str(final_publishable_status or "").strip().lower()

            # Normalize pub_s: treat fail_with_media_handoff as degraded, not blocked
            if pub_s == "fail_with_media_handoff":
                pub_s = "degraded"

            # Validation: read from disk, derive using shared helper
            validation_report_path = module_dir / "validation_report.json"
            vs = "unknown"
            missing_validation = False
            try:
                if validation_report_path.exists():
                    vr = json.loads(validation_report_path.read_text(encoding="utf-8"))
                    vs = _derive_validation_status(vr)
                else:
                    missing_validation = True
            except Exception:
                missing_validation = True

            # Map pipeline overall_status to canonical value for agreement check
            pipeline_normalized = str(pipeline_overall_status or "unknown").strip().lower()
            if pipeline_normalized in {"success", "pass", "complete"}:
                tts = "pass"
            elif pipeline_normalized in {"failed", "fail", "blocked"}:
                tts = "blocked"
            elif pipeline_normalized == "degraded":
                tts = "degraded"
            else:
                tts = pipeline_normalized

            # If required reports are missing (not on disk or failed to persist), add them
            missing_list = []
            if missing_validation:
                missing_list.append("validation")
            if not source_fidelity_report_persisted:
                missing_list.append("source_fidelity")

            # Load accepted final reconciliation report if present
            final_rec_accepted = False
            final_rec_status = None
            sfe_status = None
            try:
                from utils.toolkit_final_reconciliation import (
                    load_final_reconciliation_report,
                    is_final_reconciliation_accepted,
                )
                recon_report = load_final_reconciliation_report(module_dir)
                if recon_report is not None and is_final_reconciliation_accepted(recon_report):
                    final_rec_accepted = True
                    final_rec_status = recon_report.get("status", "accepted")
                    sfe_status = recon_report.get("source_fidelity_effective_status")
            except Exception:
                pass

            agreement = compose_report_agreement(
                source_fidelity_status=sf_s,
                validation_status=vs,
                ready_status=ready_s,
                publishable_status=pub_s,
                effective_publishable_status=eps,
                toolkit_top_level_status=tts,
                source_fidelity_effective_status=sfe_status,
                final_reconciliation_accepted=final_rec_accepted,
                final_reconciliation_status=final_rec_status,
                missing_reports=missing_list if missing_list else None,
            )

            stage_status = agreement.get("status", "failed")
            return {
                "status": stage_status,
                "internal_coherent": agreement.get("internal_coherent", False),
                "playable_publication_status": agreement.get("playable_publication_status", "unknown"),
                "source_fidelity_status": agreement.get("source_fidelity_status", "unknown"),
                "source_fidelity_effective_status": agreement.get("source_fidelity_effective_status", "unknown"),
                "final_reconciliation_accepted": agreement.get("final_reconciliation_accepted", False),
                "final_reconciliation_status": agreement.get("final_reconciliation_status", "not_applicable"),
                "source_fidelity_reconciled": agreement.get("source_fidelity_reconciled", False),
                "validation_status": agreement.get("validation_status", "unknown"),
                "ready_status": agreement.get("ready_status", "unknown"),
                "publishable_status": agreement.get("publishable_status", "unknown"),
                "effective_publishable_status": agreement.get("effective_publishable_status", "unknown"),
                "blockers": agreement.get("blockers", []),
                "diagnostics": agreement.get("diagnostics", []),
                "missing_reports": agreement.get("missing_reports", []),
                "stale_reports": agreement.get("stale_reports", []),
                "agreement": agreement,
            }
        except Exception as exc:
            warning(
                f"TOOLKIT_FINISHER: Report agreement stage failed for {module_slug}: {exc}",
                category="module_ingest",
            )
            return {
                "status": "failed",
                "internal_coherent": False,
                "reason": f"report_agreement_exception: {exc}",
                "blockers": [],
                "diagnostics": [f"Report agreement stage raised exception: {exc}"],
            }

    report_path = module_dir / "toolkit_build_report.json"

    def _build_report(
        *, status: str, ready_status: str, publishable_status: str, phase: str
    ) -> Dict[str, Any]:
        freshness = _derive_report_freshness(
            status=status,
            phase=phase,
            ready_status=ready_status,
            publishable_status=publishable_status,
            workflow=refresh_workflow,
            refresh_reason=refresh_reason,
        )
        return {
            "generated_at": _utc_now_iso(),
            "module_slug": module_slug,
            "status": status,
            "ready_status": ready_status,
            "publishable_status": publishable_status,
            "freshness_state": freshness.get("state"),
            "report_freshness": freshness,
            "strict": bool(strict),
            "source": "toolkit",
            "provenance": {
                "source": "toolkit",
                "artifact": "toolkit_build_report.json",
                "contract": "toolkit_build_report_required",
                "phase": phase,
                "refresh_contract": _TOOLKIT_REPORT_FRESHNESS_CONTRACT_VERSION,
                "refresh_workflow": str(
                    refresh_workflow or "toolkit_postbuild_finisher"
                ),
                "refresh_reason": str(refresh_reason or "postbuild_finishing"),
            },
            "stages": stages,
            "publication_parity_note": (
                "Post-build parity now reports both structural readiness and semantic publishability."
            ),
            "semantic_authority_note": (
                "Semantic authority and semantic probes now feed a standalone publishable gate distinct from readiness."
            ),
        }

    # TABLETOP MODE: Persist toolkit provenance before toolkit-source readiness
    # and publishability checks so same-run toolkit audits can self-validate.
    pre_publishability_report = _build_report(
        status=overall_status,
        ready_status="pending",
        publishable_status="pending",
        phase="pre_publishability",
    )
    pre_write_ok = safe_write_json(str(report_path), pre_publishability_report)
    if not pre_write_ok:
        error(
            f"TOOLKIT_FINISHER: Failed to write pre-publishability report for {module_slug}",
            category="module_ingest",
        )
        stages["toolkit_provenance"] = {
            "status": "failed",
            "reason": "toolkit_provenance_write_failed",
            "report_path": str(report_path),
        }
        overall_status = "failed"
    else:
        stages["toolkit_provenance"] = {
            "status": "success",
            "reason": "toolkit_provenance_prepared",
            "report_path": str(report_path),
        }

    publishability_stage = _run_publishability_stage(
        module_slug=module_slug,
        source="toolkit",
    )
    stages["publishability"] = publishability_stage

    # TABLETOP MODE: Persist module-level source_fidelity_report.json
    # so publishability audit can consume the same status on subsequent runs.
    _sf_report_persisted = False
    try:
        from scripts.audit_module_publishability import _build_source_fidelity_report_artifact
        pub_report = publishability_stage.get("report", {})
        if pub_report:
            sf_report = _build_source_fidelity_report_artifact(
                module_slug=module_slug,
                module_path=module_dir,
                publishability_report=pub_report,
            )
            if safe_write_json(str(module_dir / "source_fidelity_report.json"), sf_report):
                _sf_report_persisted = True
    except Exception:
        warning(f"TOOLKIT_FINISHER: Failed to persist source_fidelity_report for {module_slug}", category="module_ingest")

    # TABLETOP MODE: LLM-assisted remediation proposals (Phase 2 DP4)
    llm_remediation_stage = _run_llm_remediation_stage(
        module_slug=module_slug,
        module_dir=module_dir,
        publishability_stage=publishability_stage,
    )
    stages["llm_remediation"] = llm_remediation_stage

    # TABLETOP MODE: Context backup parity stage -- verify module_context.json
    # and module_context_BU.json are in exact parity after all mutations.
    # Failure here blocks playable status through pipeline_overall_status.
    context_parity_stage = _run_context_backup_parity_stage(module_dir)
    stages["context_backup_parity"] = context_parity_stage
    if context_parity_stage.get("status") == "failed":
        overall_status = "failed"

    ready_status = str(publishability_stage.get("ready_status", "fail") or "fail")
    publishable_status = str(
        publishability_stage.get("publishable_status", "fail") or "fail"
    )

    # Source fidelity lives inside publishability_stage["report"], not on the stage wrapper
    _pub_report = publishability_stage.get("report", {}) or {}
    source_fidelity_status = str(
        _pub_report.get("source_fidelity_status", "unknown") or "unknown"
    )
    source_fidelity_categories = _pub_report.get("source_fidelity_categories", [])

    if _detect_media_only_debt(publishability_stage):
        media_debt = _extract_media_debt_details(publishability_stage)
        stages["publishability"]["media_handoff"] = {
            "status": "media_only_debt",
            "build_outcome": "success_with_media_handoff",
            "message": (
                "Build completed successfully. Manual media generation required for "
                "monster portraits. Use: Module Builder -> Module Media Generator"
            ),
            "next_step": "Module Builder -> Module Media Generator",
            "next_step_detail": media_debt.get("media_debt_workflow_detail", ""),
            "media_debt_count": media_debt.get("media_debt_count", 0),
            "media_debt_slugs": media_debt.get("media_debt_slugs", []),
        }
        stages["publishability"]["status"] = "degraded"
        publishable_status = "fail_with_media_handoff"
        info(
            f"TOOLKIT_FINISHER: Media-only debt detected for {module_slug} - reporting success_with_media_handoff",
            category="module_ingest",
        )
    elif publishable_status == "fail":
        overall_status = "failed"
    elif publishability_stage.get("status") == "failed":
        overall_status = "failed"
    elif (
        publishability_stage.get("status") == "degraded" and overall_status != "failed"
    ):
        overall_status = "degraded"

    # TABLETOP MODE: Report agreement stage -- check all persisted reports for
    # contradictions before declaring playable status. Must run AFTER status
    # computation to use final override values.
    report_agreement_stage = _run_report_agreement_stage(
        publishability_result=publishability_stage,
        final_ready_status=ready_status,
        final_publishable_status=publishable_status,
        pipeline_overall_status=overall_status,
        source_fidelity_report_persisted=_sf_report_persisted,
    )
    stages["report_agreement"] = report_agreement_stage
    ra_status = report_agreement_stage.get("status", "failed")
    ra_blockers = report_agreement_stage.get("blockers", [])

    # Degrade overall status if report_agreement found any blockers
    # (missing_reports, stale_reports, or contradictions).
    if ra_status in {"failed", "blocked", "stale"} and ra_blockers:
        if overall_status != "failed":
            overall_status = "degraded"
        info(
            f"TOOLKIT_FINISHER: Report agreement {ra_status} for {module_slug}: {ra_blockers}",
            category="module_ingest",
        )

    report = _build_report(
        status=overall_status,
        ready_status=ready_status,
        publishable_status=publishable_status,
        phase="final",
    )

    report["source_fidelity_status"] = source_fidelity_status
    report["source_fidelity_categories"] = list(source_fidelity_categories) if isinstance(source_fidelity_categories, list) else []
    if _sf_report_persisted:
        report["source_fidelity_report"] = "source_fidelity_report.json"

    # Inject report-agreement and playable-publication fields
    effective_pub = report_agreement_stage.get("effective_publishable_status", "unknown")
    playable_pub = report_agreement_stage.get("playable_publication_status", "unknown")
    report["effective_publishable_status"] = effective_pub
    report["playable_publication_status"] = playable_pub
    report["report_agreement"] = report_agreement_stage.get("agreement", {})
    report["report_agreement_status"] = report_agreement_stage.get("status", "unknown")
    report["report_agreement_internal_coherent"] = bool(
        report_agreement_stage.get("internal_coherent", False)
    )

    report["source_fidelity_effective_status"] = report_agreement_stage.get(
        "source_fidelity_effective_status", source_fidelity_status
    )
    report["final_reconciliation_accepted"] = report_agreement_stage.get(
        "final_reconciliation_accepted", False
    )
    report["final_reconciliation_status"] = report_agreement_stage.get(
        "final_reconciliation_status", "not_applicable"
    )
    report["source_fidelity_reconciled"] = report_agreement_stage.get(
        "source_fidelity_reconciled", False
    )

    write_ok = safe_write_json(str(report_path), report)
    if not write_ok:
        error(
            f"TOOLKIT_FINISHER: Failed to write report for {module_slug}",
            category="module_ingest",
        )
        if overall_status != "failed":
            overall_status = "degraded"
        report["status"] = overall_status
        report["report_write_error"] = True

    report["report_path"] = str(report_path)

    info(
        f"TOOLKIT_FINISHER: Completed post-build finishing for {module_slug} status={overall_status}",
        category="module_ingest",
    )
    return report


def refresh_toolkit_build_report(
    module_slug: str,
    strict: bool = True,
    refresh_reason: str = "toolkit_revalidation",
    extra_stages: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run explicit report-refresh contract for publishability-facing workflows."""
    return run_toolkit_module_postbuild_finishing(
        module_slug=module_slug,
        strict=strict,
        refresh_reason=refresh_reason,
        refresh_workflow="toolkit_report_refresh",
        extra_stages=extra_stages,
    )
