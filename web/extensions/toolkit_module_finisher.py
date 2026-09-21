# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Web Extension - Toolkit module post-build finishing helper.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from utils.enhanced_logger import error, info, warning
from utils.file_operations import safe_read_json, safe_write_json
from utils.module_semantic_authority import enrich_module_semantic_authority
from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM
from utils.toolkit_adaptation_markdown_quality import (
    check_adaptation_markdown_quality,
)
from utils.toolkit_adaptation_provenance import (
    adaptation_provenance_surface_fields,
    build_adaptation_provenance,
    persist_adaptation_module_provenance,
    validate_adaptation_provenance,
)
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_BUILD_RESULT,
    ARTIFACT_KIND_PUBLICATION_REPORT,
    BUILD_STATUS_PASSED,
    PUBLICATION_STATUS_BLOCKED,
    PUBLICATION_STATUS_DEFERRED,
    PUBLICATION_STATUS_PENDING,
    PUBLICATION_STATUS_PUBLISHED,
    build_publication_report_artifact,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
    persist_publication_report_artifact,
)
from utils.toolkit_report_agreement import (
    compose_adaptation_report_agreement,
    compose_report_agreement,
)
from web.extensions.toolkit_adaptation_job_reporting import (
    validate_adaptation_artifact_current,
)


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


def _run_publishability_finalizer_stage(
    module_slug: str, module_dir: Path
) -> Dict[str, Any]:
    """Run centralized publishability metadata finalization.

    Calls ``finalize_module_publishability_metadata()`` which applies
    continuity contract keys, continuity cross-ref enrichment, and semantic
    authority enrichment in one deterministic pass, atomically persisting
    any changes to ``module_context.json`` (and BU mirror if present).

    Fail-open/degraded: errors are reported in the stage result but do not
    crash the pipeline.
    """
    from utils.toolkit_publishability_finalizer import (
        finalize_module_publishability_metadata,
    )

    try:
        result = finalize_module_publishability_metadata(module_slug, module_dir)
        stage_status = result.get("status", "degraded")
        return {
            "status": stage_status,
            "changed": result.get("changed", False),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
        }
    except Exception as exc:
        warning(
            f"TOOLKIT_FINISHER: Publishability finalizer stage failed for {module_slug}: {exc}",
            category="module_ingest",
        )
        return {
            "status": "degraded",
            "changed": False,
            "errors": [f"publishability_finalizer_exception: {exc}"],
            "warnings": [],
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


def _run_registry_stage(
    module_slug: str,
    *,
    module_dir: Optional[Path] = None,
    adaptation: bool = False,
) -> Dict[str, Any]:
    """Run legacy registry integration or the strict adaptation transaction."""
    if adaptation:
        if module_dir is None:
            return {
                "status": "blocked",
                "reason": "adaptation_registry_module_dir_missing",
                "integration_attempted": False,
            }
        try:
            from utils.toolkit_adaptation_registry import (
                integrate_adaptation_registry,
            )

            return integrate_adaptation_registry(
                module_slug,
                module_dir,
                registry_path=Path.cwd() / "modules" / "world_registry.json",
            )
        except Exception as exc:
            return {
                "status": "blocked",
                "reason": f"adaptation_registry_integration_exception:{exc}",
                "integration_attempted": False,
            }

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
    provider_stage_errors = []

    try:
        stitcher = ModuleStitcher()
        integration_success = bool(stitcher.integrate_module(module_slug))
        provider_stage_errors = list(
            getattr(stitcher, "provider_stage_errors", []) or []
        )
    except Exception as stitch_error:
        integration_error = str(stitch_error)

    verify_after = verify_present(module_slug)
    if verify_after.get("present", False):
        return {
            "status": "degraded" if provider_stage_errors else "success",
            "verify_before": verify_before,
            "verify_after": verify_after,
            "integration_attempted": integration_attempted,
            "integration_success": integration_success,
            "integration_error": integration_error,
            "provider_stage_errors": provider_stage_errors,
        }

    return {
        "status": "failed",
        "reason": "Module not present in registry after integration attempt",
        "verify_before": verify_before,
        "verify_after": verify_after,
        "integration_attempted": integration_attempted,
        "integration_success": integration_success,
        "integration_error": integration_error,
        "provider_stage_errors": provider_stage_errors,
    }


def _run_adaptation_campaign_sync_stage(
    module_slug: str,
    *,
    registry_path: Optional[Path] = None,
    campaign_path: Optional[Path] = None,
    require_active_campaign: bool = False,
) -> Dict[str, Any]:
    """Synchronize adaptation availability after verified registry publication."""
    try:
        from utils.toolkit_adaptation_campaign import (
            synchronize_adaptation_campaign_module,
        )

        return synchronize_adaptation_campaign_module(
            module_slug,
            campaign_path=campaign_path
            if campaign_path is not None
            else Path.cwd() / "modules" / "campaign.json",
            registry_path=registry_path
            if registry_path is not None
            else Path.cwd() / "modules" / "world_registry.json",
            require_active_campaign=require_active_campaign,
        )
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": f"campaign_sync_exception:{exc}",
            "module_slug": module_slug,
            "campaign_visibility_verified": False,
            "write": {"status": "not_attempted", "atomic": True},
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


def _run_ingest_sidecar_persistence_stage(
    module_slug: str,
    module_dir: Path,
    build_status: str,
) -> Dict[str, Any]:
    """Persist ingest sidecar for a module build.

    Calls ``persist_ingest_sidecar()`` which writes a deterministic sidecar
    JSON file to ``modules/ingest/archive/<timestamp>_<slug>.result.json``.

    The sidecar satisfies the contract expected by
    ``find_latest_sidecar_for_slug()`` and passes
    ``homebrew_sidecar_audit.py --require-success`` when written.

    If *build_status* is ``"failed"``, the stage is skipped (with a warning)
    to avoid creating a misleading success sidecar for a terminally failed
    build.

    Fail-open/degraded: errors are reported in the stage result but do not
    crash the pipeline.
    """
    from utils.toolkit_publishability_finalizer import persist_ingest_sidecar

    # Do not write success sidecar for a terminally failed build
    if build_status == "failed":
        return {
            "status": "skipped",
            "sidecar_path": "",
            "errors": [],
            "warnings": ["sidecar_skipped_build_failed"],
        }

    try:
        result = persist_ingest_sidecar(
            module_slug=module_slug,
            module_dir=module_dir,
            status="success",
        )
        stage_status = result.get("status", "degraded")
        return {
            "status": stage_status,
            "sidecar_path": result.get("sidecar_path", ""),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
        }
    except Exception as exc:
        warning(
            f"TOOLKIT_FINISHER: Ingest sidecar persistence stage failed for {module_slug}: {exc}",
            category="module_ingest",
        )
        return {
            "status": "degraded",
            "sidecar_path": "",
            "errors": [f"ingest_sidecar_persistence_exception: {exc}"],
            "warnings": [],
        }


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


def _run_monster_media_closure_stage(module_dir: Path) -> Dict[str, Any]:
    """Close missing monster base media with placeholder JPEGs.

    Calls ``close_monster_base_media()`` which writes a minimal valid JPEG
    placeholder at ``media/monsters/<slug>.jpg`` for every monster slug that
    has a JSON stat block but no base media file.  Existing files are never
    overwritten.

    Fail-open/degraded: errors are recorded in the stage result but do not
    crash the pipeline.  This stage MUST run after monster materialization
    so that the materialization stage has already created all monster JSON
    files (and thus the slug list is complete).
    """
    from utils.module_monster_media_closure import close_monster_base_media

    try:
        result = close_monster_base_media(str(module_dir))
        created = int(result.get("created", 0))
        skipped = int(result.get("skipped", 0))
        errors = list(result.get("errors", []))
        if errors:
            stage_status = "degraded"
        else:
            stage_status = "success"
        return {
            "status": stage_status,
            "created": created,
            "skipped": skipped,
            "errors": errors,
        }
    except Exception as exc:
        warning(
            f"TOOLKIT_FINISHER: Monster media closure stage failed: {exc}",
            category="module_ingest",
        )
        return {
            "status": "degraded",
            "created": 0,
            "skipped": 0,
            "errors": [f"monster_media_closure_exception: {exc}"],
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

        provider_errors = []
        proposals = call_llm_remediation_proposals(
            batch,
            error_sink=provider_errors,
        )
        if provider_errors:
            return {
                "status": "degraded",
                "reason": "provider_error",
                "provider_errors": provider_errors,
            }
        if not proposals:
            return {"status": "skipped", "reason": "api_returned_empty"}

        validated = validate_remediation_proposals(
            str(module_dir), proposals
        )
        valid_count = sum(
            1
            for p in validated
            if p.get("safety", "").startswith(("pass", "warning"))
        )

        return {
            "status": "success",
            "proposal_count": len(proposals),
            "valid_count": valid_count,
            "proposals": validated,
        }
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


_ADAPTATION_PUBLICATION_ORDER = (
    "schema",
    "readiness",
    "mechanical_closure",
    "semantic_authority",
    "semantic_probes",
    "report_agreement",
    "markdown",
    "registry",
)


def _is_llm_adaptation_mode(adaptation_mode: Optional[str]) -> bool:
    """Return True only for the explicit adaptation publication mode."""
    return str(adaptation_mode or "").strip().lower() == ADAPTATION_MODE_LLM


def _resolve_adaptation_module_dir(
    *,
    staging_target: Optional[Mapping[str, Any]],
    module_dir: Optional[str],
) -> Dict[str, Any]:
    """Resolve a staged adaptation directory without accepting live modules.

    The packet builder has already reserved and built the target. Finishing
    validates the identity envelope again before reading or writing provisional
    reports. A completed staging marker is accepted here because the builder
    marks the candidate complete before the separate finishing transaction
    starts; no target is reused or re-reserved by this helper.
    """
    if not isinstance(staging_target, Mapping):
        return {
            "status": "failed",
            "reason": "adaptation_staging_target_missing",
        }

    raw_target_path = str(staging_target.get("path") or "").strip()
    if not raw_target_path:
        return {
            "status": "failed",
            "reason": "adaptation_staging_target_path_missing",
        }

    project_root = Path.cwd().resolve()
    candidate = Path(raw_target_path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    candidate = candidate.resolve()

    try:
        candidate.relative_to(project_root)
    except ValueError:
        return {
            "status": "failed",
            "reason": "adaptation_staging_target_outside_project",
        }

    modules_root = (project_root / "modules").resolve()
    try:
        candidate.relative_to(modules_root)
    except ValueError:
        pass
    else:
        return {
            "status": "failed",
            "reason": "adaptation_staging_target_inside_modules",
        }

    if module_dir:
        explicit = Path(str(module_dir))
        if not explicit.is_absolute():
            explicit = project_root / explicit
        explicit = explicit.resolve()
        if explicit != candidate:
            return {
                "status": "failed",
                "reason": "adaptation_module_dir_target_mismatch",
            }

    if not candidate.is_dir() or candidate.is_symlink():
        return {
            "status": "failed",
            "reason": "adaptation_staging_target_not_directory",
            "module_dir": str(candidate),
        }
    if not (candidate / "staging_metadata.json").is_file():
        return {
            "status": "failed",
            "reason": "adaptation_staging_metadata_missing",
            "module_dir": str(candidate),
        }

    return {
        "status": "success",
        "module_dir": candidate,
        "module_slug": str(staging_target.get("module_slug") or candidate.name).strip(),
    }


def _adaptation_gate_status(gate: Any) -> str:
    """Normalize one adaptation gate status without treating missing as pass."""
    if not isinstance(gate, Mapping):
        return "blocked"
    value = gate.get("effective_status", gate.get("status"))
    normalized = str(value or "").strip().lower()
    if normalized in {"pass", "success", "ok", "complete", "completed"}:
        return "pass"
    return "blocked"


def _adaptation_finishing_identity(
    provenance: Optional[Mapping[str, Any]],
    staging_target: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Resolve the current attempt identity for finishing artifact reads."""
    provenance = provenance if isinstance(provenance, Mapping) else {}
    staging_target = staging_target if isinstance(staging_target, Mapping) else {}
    nested_attempt = provenance.get("attempt_metadata")
    nested_attempt = nested_attempt if isinstance(nested_attempt, Mapping) else {}

    def first(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    return {
        "attempt_id": first(
            provenance.get("attempt_id"),
            nested_attempt.get("attempt_id"),
            staging_target.get("attempt_id"),
        ),
        "revision_number": first(
            provenance.get("revision_number"),
            nested_attempt.get("revision_number"),
            staging_target.get("revision_number"),
            0,
        ),
        "source_hash": first(
            provenance.get("source_hash"),
            staging_target.get("source_hash"),
        ),
        "source_path": first(
            provenance.get("source_path"),
            staging_target.get("source_path"),
        ),
    }


def _validate_adaptation_finishing_artifacts(
    *,
    adaptation_gates: Any,
    staging_target: Optional[Mapping[str, Any]],
    adaptation_provenance: Optional[Mapping[str, Any]],
    artifact_workspace: Optional[Path],
) -> Dict[str, Any]:
    """Ensure finishing consumes only the current build and gate artifacts."""
    if not isinstance(adaptation_provenance, Mapping):
        # Existing helper/test callers without adaptation provenance remain on
        # the legacy-compatible finisher path.
        return {"status": "pass", "reason_code": "adaptation_identity_not_supplied"}

    expected = _adaptation_finishing_identity(
        adaptation_provenance, staging_target
    )
    if not expected.get("attempt_id") or not expected.get("source_hash"):
        return {
            "status": "blocked",
            "reason_code": "adaptation_current_artifact_identity_missing",
            "diagnostics": ["current adaptation attempt identity is incomplete"],
        }

    target_check = validate_adaptation_artifact_current(
        staging_target,
        expected_attempt_id=expected["attempt_id"],
        expected_revision_number=expected.get("revision_number", 0),
        expected_source_hash=expected["source_hash"],
        expected_source_path=expected.get("source_path"),
        label="finishing_staging_target",
    )
    if target_check.get("status") != "pass":
        return target_check

    if artifact_workspace is None:
        return {
            "status": "blocked",
            "reason_code": "adaptation_current_build_artifact_missing",
            "diagnostics": ["adaptation artifact workspace is missing"],
        }

    build_artifact = load_adaptation_artifact(
        artifact_workspace,
        str(expected["attempt_id"]),
        ARTIFACT_KIND_BUILD_RESULT,
        int(expected.get("revision_number", 0)),
    )
    build_check = validate_adaptation_artifact_current(
        build_artifact,
        expected_attempt_id=expected["attempt_id"],
        expected_revision_number=expected.get("revision_number", 0),
        expected_source_hash=expected["source_hash"],
        expected_source_path=expected.get("source_path"),
        label="current_build_result",
    )
    if build_check.get("status") != "pass":
        return build_check

    if isinstance(adaptation_gates, Mapping):
        gate_provenance = adaptation_gates.get("provenance")
        if isinstance(gate_provenance, Mapping):
            gate_check = validate_adaptation_artifact_current(
                gate_provenance,
                expected_attempt_id=expected["attempt_id"],
                expected_revision_number=expected.get("revision_number", 0),
                expected_source_hash=expected["source_hash"],
                expected_source_path=expected.get("source_path"),
                label="readiness_gate",
            )
            if gate_check.get("status") != "pass":
                return gate_check

    return {
        "status": "pass",
        "reason_code": "adaptation_finishing_artifacts_current",
        "diagnostics": [],
    }


def _run_adaptation_gate_order_stage(
    adaptation_gates: Any,
) -> Dict[str, Any]:
    """Require the Python-owned adaptation gates before publication.

    Task 4.2 already composes these gates in the isolated staging target. This
    stage is the finishing boundary: it refuses to call Markdown generation or
    registry integration unless the complete gate result is present, current
    for this candidate, and explicitly playable.
    """
    if not isinstance(adaptation_gates, Mapping):
        return {
            "status": "failed",
            "reason": "adaptation_gate_result_missing",
            "order": list(_ADAPTATION_PUBLICATION_ORDER),
        }

    raw_gates = adaptation_gates.get("gates")
    if not isinstance(raw_gates, Mapping):
        return {
            "status": "failed",
            "reason": "adaptation_gate_domains_missing",
            "order": list(_ADAPTATION_PUBLICATION_ORDER),
        }

    required_domains = _ADAPTATION_PUBLICATION_ORDER[:6]
    failed_domains = [
        domain
        for domain in required_domains
        if _adaptation_gate_status(raw_gates.get(domain)) != "pass"
    ]

    top_status = str(adaptation_gates.get("status") or "").strip().lower()
    playable_status = str(
        adaptation_gates.get("playable_status")
        or adaptation_gates.get("adaptation_status")
        or ""
    ).strip().lower()
    candidate_eligible = adaptation_gates.get("candidate_eligible") is True

    report_gate = raw_gates.get("report_agreement")
    report_agreement = (
        report_gate.get("agreement")
        if isinstance(report_gate, Mapping)
        else None
    )
    report_playable_status = str(
        (report_gate or {}).get("playable_publication_status")
        if isinstance(report_gate, Mapping)
        else ""
    ).strip().lower()
    if not report_playable_status and isinstance(report_agreement, Mapping):
        report_playable_status = str(
            report_agreement.get("playable_publication_status") or ""
        ).strip().lower()

    if top_status not in {"pass", "success"}:
        failed_domains.append("adaptation_gate_result")
    if playable_status not in {"pass", "ready_for_publication"}:
        failed_domains.append("adaptation_playable_status")
    if not candidate_eligible:
        failed_domains.append("adaptation_candidate_eligibility")
    if report_playable_status not in {"pass", "success"}:
        failed_domains.append("report_agreement_playable_status")

    failed_domains = list(dict.fromkeys(failed_domains))
    if failed_domains:
        return {
            "status": "failed",
            "reason": "adaptation_prepublication_gates_failed",
            "failed_domains": failed_domains,
            "order": list(_ADAPTATION_PUBLICATION_ORDER),
            "gate_statuses": {
                domain: _adaptation_gate_status(raw_gates.get(domain))
                for domain in required_domains
            },
        }

    return {
        "status": "success",
        "reason": "adaptation_prepublication_gates_passed",
        "failed_domains": [],
        "order": list(_ADAPTATION_PUBLICATION_ORDER),
        "gate_statuses": {
            domain: _adaptation_gate_status(raw_gates.get(domain))
            for domain in required_domains
        },
        "python_authoritative": True,
        "registry_allowed": False,
    }


def _run_adaptation_hard_safety_stage(
    *,
    adaptation_gates: Any,
    adaptation_provenance: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Enforce Python-owned policy and revision state before finalization.

    LLM readiness is only a candidate signal.  The gate composer remains the
    source of structural truth, while this small boundary rejects incomplete
    rights/policy envelopes and stale revision claims before any staged
    artifact is promoted.
    """
    diagnostics = []
    if isinstance(adaptation_provenance, Mapping):
        canonical_provenance = build_adaptation_provenance(
            provenance=adaptation_provenance,
            adaptation_status=adaptation_provenance.get("adaptation_status", "adapted"),
        )
        validation = validate_adaptation_provenance(
            canonical_provenance,
            require_source_identity=True,
        )
        if not validation.get("valid"):
            diagnostics.extend(list(validation.get("diagnostics") or [])[:8])
        review_required = adaptation_provenance.get("rights_review_required")
        review_status = str(
            adaptation_provenance.get("rights_review_status") or ""
        ).strip().lower()
        if not isinstance(review_required, bool):
            diagnostics.append("rights_review_required_missing")
        elif review_required and review_status != "approved":
            diagnostics.append("rights_review_not_approved")
        elif not review_required and review_status != "not_required":
            diagnostics.append("rights_review_status_invalid")

    if isinstance(adaptation_gates, Mapping):
        # A revision-required or exhausted candidate is never publishable,
        # even if an LLM has returned a positive readiness claim.
        projection = adaptation_gates.get("revision_projection")
        if not isinstance(projection, Mapping):
            projection = adaptation_gates.get("revision_budget")
        if isinstance(projection, Mapping):
            if projection.get("revision_required") is True:
                diagnostics.append("revision_required")
            if str(projection.get("decision") or "").strip().lower() in {
                "required",
                "exhausted",
            }:
                diagnostics.append("revision_required")
        if adaptation_gates.get("revision_required") is True:
            diagnostics.append("revision_required")
        finalization = adaptation_gates.get("finalization")
        if isinstance(finalization, Mapping) and str(
            finalization.get("status") or ""
        ).strip().lower() not in {"", "ready", "pass", "success"}:
            diagnostics.append("finalization_candidate_not_ready")
        policy = adaptation_gates.get("policy")
        if isinstance(policy, Mapping) and str(
            policy.get("status") or "pass"
        ).strip().lower() not in {"pass", "success", "approved"}:
            diagnostics.append("adaptation_policy_not_approved")

    if diagnostics:
        return {
            "status": "failed",
            "reason": "adaptation_hard_safety_boundary_failed",
            "diagnostics": list(dict.fromkeys(diagnostics))[:12],
            "python_authoritative": True,
        }
    return {
        "status": "success",
        "reason": "adaptation_hard_safety_boundary_passed",
        "diagnostics": [],
        "python_authoritative": True,
    }


def _write_text_atomically(path: Path, content: str) -> bool:
    """Write UTF-8 text using a same-directory temporary file and replace."""
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        return True
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except Exception:
                pass
        return False


def _run_module_summary_stage(
    module_slug: str,
    module_dir: Path,
    *,
    adaptation_mode: bool = False,
    adaptation_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate and persist the derived Markdown summary.

    Legacy finishing keeps its existing degraded behavior. Adaptation
    finishing uses the same renderer with the exact adaptation notice and
    treats a failed strict quality check as a hard pre-registration blocker.
    """
    try:
        from utils.homebrewery_adventure_writer import generate_homebrewery_adventure

        if adaptation_mode:
            summary_kwargs: Dict[str, Any] = {
                "module_dir": module_dir,
                "adaptation_notice": True,
            }
            if isinstance(adaptation_provenance, Mapping):
                summary_kwargs["adaptation_provenance"] = dict(adaptation_provenance)
            markdown = generate_homebrewery_adventure(module_slug, **summary_kwargs)
            quality = check_adaptation_markdown_quality(
                markdown,
                module_slug=module_slug,
            )
        else:
            markdown = generate_homebrewery_adventure(module_slug)
            quality = {
                "valid": bool(markdown and len(markdown) > 100),
                "reason": "readable_markdown"
                if markdown and len(markdown) > 100
                else "generated_content_too_short",
                "bytes": len(markdown.encode("utf-8")) if isinstance(markdown, str) else 0,
            }

        if not quality["valid"]:
            return {
                "status": "failed" if adaptation_mode else "degraded",
                "reason": quality["reason"],
                "bytes": quality["bytes"],
                "quality": quality,
            }

        summary_path = module_dir / "MODULE_SUMMARY.md"
        if not isinstance(markdown, str) or not _write_text_atomically(
            summary_path, markdown
        ):
            return {
                "status": "failed" if adaptation_mode else "degraded",
                "reason": "module_summary_write_failed",
                "bytes": quality["bytes"],
                "quality": quality,
                "path": str(summary_path),
            }

        return {
            "status": "success",
            "path": str(summary_path),
            "bytes": quality["bytes"],
            "quality": quality,
        }
    except Exception as exc:
        error(
            f"TOOLKIT_FINISHER: Failed to generate module summary for {module_slug}: {exc}",
            category="module_ingest",
        )
        return {
            "status": "failed" if adaptation_mode else "degraded",
            "reason": "generation_exception",
            "exception": str(exc),
        }


def _run_adaptation_provenance_stage(
    *,
    module_slug: str,
    module_dir: Path,
    adaptation_provenance: Any,
    adaptation_gates: Any,
) -> Dict[str, Any]:
    """Persist canonical provenance on the staged module and fidelity report."""
    if not isinstance(adaptation_provenance, Mapping):
        return {
            "status": "not_available",
            "reason": "adaptation_provenance_not_supplied",
        }

    canonical = build_adaptation_provenance(
        provenance=adaptation_provenance,
        adaptation_status="adapted",
        module_slug=module_slug,
    )
    validation = validate_adaptation_provenance(
        canonical,
        require_source_identity=True,
    )
    if not validation.get("valid"):
        return {
            "status": "failed",
            "reason": "adaptation_provenance_invalid",
            "diagnostics": list(validation.get("diagnostics") or []),
        }

    if not persist_adaptation_module_provenance(
        module_dir,
        canonical,
        adaptation_status="adapted",
    ):
        return {
            "status": "failed",
            "reason": "adaptation_module_provenance_persist_failed",
            "module_context_path": str(module_dir / "module_context.json"),
        }

    source_report = None
    if isinstance(adaptation_gates, Mapping):
        candidate = adaptation_gates.get("source_fidelity_report")
        if isinstance(candidate, Mapping):
            source_report = dict(candidate)
    if source_report is None:
        from utils.toolkit_adaptation_source_fidelity import (
            build_adaptation_source_fidelity_report,
        )

        source_report = build_adaptation_source_fidelity_report(
            attempt_metadata=canonical,
            module_slug=module_slug,
        )

    source_report.update(
        adaptation_provenance_surface_fields(
            canonical,
            adaptation_status="adapted",
        )
    )
    source_report["adaptation_mode"] = canonical["adaptation_mode"]
    source_report["source_fidelity_mode"] = canonical["adaptation_mode"]
    source_report["source_fidelity_status"] = canonical["source_fidelity_status"]
    source_report["source_fidelity_effective_status"] = canonical[
        "source_fidelity_status"
    ]
    source_report["literal_source_fidelity"] = canonical["literal_source_fidelity"]
    source_report["fidelity_claim"] = canonical["fidelity_claim"]
    source_report["report_freshness"] = {
        "state": "current",
        "authoritative": True,
        "written_at": _utc_now_iso(),
        "stage": "adaptation_provenance",
        "attempt_id": canonical.get("attempt_id", ""),
    }
    source_report_path = module_dir / "source_fidelity_report.json"
    if not safe_write_json(str(source_report_path), source_report):
        return {
            "status": "failed",
            "reason": "adaptation_source_fidelity_report_persist_failed",
            "path": str(source_report_path),
        }

    return {
        "status": "success",
        "reason": "adaptation_provenance_persisted",
        "module_context_path": str(module_dir / "module_context.json"),
        "source_fidelity_report_path": str(source_report_path),
        "adaptation_provenance": canonical,
    }


def _build_adaptation_finishing_report(
    *,
    module_slug: str,
    module_dir: Path,
    stages: Dict[str, Any],
    status: str,
    reason: str = "",
    adaptation_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the bounded adaptation publication report envelope."""
    generated_at = _utc_now_iso()
    report: Dict[str, Any] = {
        "generated_at": generated_at,
        "module_slug": module_slug,
        "module_dir": str(module_dir),
        "status": status,
        "publication_status": "completed"
        if status == "success"
        else "pending"
        if status == "ready_for_registry"
        else "blocked"
        if status in {"blocked", "failed"}
        else str(status or "incomplete"),
        "terminal_status": "completed"
        if status == "success"
        else "blocked"
        if status in {"blocked", "failed"}
        else "incomplete",
        "ready_status": "pass"
        if (
            stages.get("adaptation_gate_order", {}).get("status") == "success"
            and status in {"success", "ready_for_registry"}
        )
        else "fail",
        "publishable_status": "pass"
        if (
            stages.get("adaptation_gate_order", {}).get("status") == "success"
            and status in {"success", "ready_for_registry"}
            and isinstance(stages.get("adaptation_gates"), Mapping)
            and stages["adaptation_gates"].get("publishable_status") == "pass"
        )
        else "fail",
        "adaptation_mode": ADAPTATION_MODE_LLM,
        "stages": _public_adaptation_report_value(stages),
        "publication_order": list(_ADAPTATION_PUBLICATION_ORDER),
        "registry_is_final_stateful_publication": True,
        "python_authoritative": True,
        "llm_publication_override": False,
        "report_freshness": {
            "state": "current",
            "authoritative": True,
            "written_at": generated_at,
            "contract": _TOOLKIT_REPORT_FRESHNESS_CONTRACT_VERSION,
        },
    }
    if isinstance(adaptation_provenance, Mapping):
        canonical = build_adaptation_provenance(
            provenance=adaptation_provenance,
            adaptation_status=status,
            module_slug=module_slug,
        )
        report.update(adaptation_provenance_surface_fields(canonical))
        report["source_fidelity_mode"] = canonical["adaptation_mode"]
        report["source_reference"] = {
            "path": canonical.get("source_path"),
            "sha256": canonical.get("source_hash"),
        }
        report["report_freshness"].update(
            {
                "attempt_id": canonical.get("attempt_id", ""),
                "revision_number": canonical.get("revision_number", 0),
                "source_hash": canonical.get("source_hash", ""),
                "source_path": canonical.get("source_path", ""),
            }
        )
    campaign_stage = stages.get("campaign_sync")
    if isinstance(campaign_stage, Mapping):
        report["campaign_sync"] = dict(campaign_stage)
        report["campaign_visibility_verified"] = (
            campaign_stage.get("campaign_visibility_verified") is True
        )
    if reason:
        report["reason"] = reason
    return report


def _persist_adaptation_finishing_report(
    module_dir: Path,
    report: Dict[str, Any],
    *,
    artifact_workspace: Optional[Path] = None,
    adaptation_provenance: Optional[Mapping[str, Any]] = None,
    staging_target: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Persist module and attempt-scoped publication reports atomically.

    The module report remains the GUI-facing surface. When the caller supplies
    the attempt workspace and provenance, the same report is also reduced to a
    validated publication artifact keyed by attempt, revision, and source
    hash. Missing identity is treated as a non-adaptation test/helper call;
    real adaptation publication callers provide the full identity envelope.
    """
    report_path = module_dir / "toolkit_build_report.json"
    report["report_path"] = str(report_path)
    publication_artifact: Optional[Dict[str, Any]] = None
    publication_artifact_path: Optional[Path] = None
    canonical: Optional[Dict[str, Any]] = None
    if artifact_workspace is not None and isinstance(adaptation_provenance, Mapping):
        try:
            canonical = build_adaptation_provenance(
                provenance=adaptation_provenance,
                adaptation_status=report.get("adaptation_status", report.get("status")),
                module_slug=report.get("module_slug"),
            )
            attempt_id = str(
                canonical.get("attempt_id")
                or (staging_target or {}).get("attempt_id")
                or ""
            ).strip()
            source_hash = str(canonical.get("source_hash") or "").strip().lower()
            source_path = str(canonical.get("source_path") or "").strip()
            if attempt_id and source_hash and source_path:
                attempt_number = int(
                    canonical.get(
                        "attempt_number",
                        (staging_target or {}).get("attempt_number", 1),
                    )
                )
                revision_number = int(
                    canonical.get("revision_number", (staging_target or {}).get("revision_number", 0))
                )
                stages = report.get("stages") if isinstance(report.get("stages"), Mapping) else {}
                publication_status = (
                    PUBLICATION_STATUS_PUBLISHED
                    if str(report.get("status") or "").strip().lower() == "success"
                    else PUBLICATION_STATUS_PENDING
                    if str(report.get("status") or "").strip().lower() == "ready_for_registry"
                    else PUBLICATION_STATUS_BLOCKED
                    if str(report.get("status") or "").strip().lower() in {"blocked", "failed"}
                    else PUBLICATION_STATUS_DEFERRED
                )

                def _stage_evidence(name: str) -> Dict[str, Any]:
                    stage = stages.get(name)
                    if not isinstance(stage, Mapping):
                        return {"status": "not_run"}
                    raw_status = str(stage.get("status") or "unknown").strip().lower()
                    evidence_status = {
                        "success": "pass",
                        "ok": "pass",
                        "passed": "pass",
                        "complete": "pass",
                        "completed": "pass",
                        "failed": "fail",
                        "error": "fail",
                        "pending": "not_run",
                        "not_attempted": "not_run",
                    }.get(raw_status, raw_status)
                    if evidence_status not in {
                        "pass",
                        "fail",
                        "blocked",
                        "not_run",
                        "deferred",
                        "unknown",
                        "not_applicable",
                    }:
                        evidence_status = "unknown"
                    evidence: Dict[str, Any] = {
                        "status": evidence_status,
                    }
                    for key in ("verified", "campaign_visibility_verified", "reason", "path", "report_path"):
                        if stage.get(key) not in (None, ""):
                            evidence[key] = stage.get(key)
                    return evidence

                module_refs = []
                repo_root = Path.cwd().resolve()
                for filename in (
                    "MODULE_SUMMARY.md",
                    "module_context.json",
                    "module_context_BU.json",
                    "module_plot.json",
                    "module_plot_BU.json",
                ):
                    candidate = module_dir / filename
                    if not candidate.is_file() or candidate.is_symlink():
                        continue
                    try:
                        relative = candidate.resolve().relative_to(repo_root).as_posix()
                        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                    except Exception:
                        continue
                    module_refs.append(
                        {
                            "path": relative,
                            "sha256": digest,
                            "size_bytes": candidate.stat().st_size,
                            "kind": "module_artifact",
                            "reference_only": True,
                        }
                    )

                registry_evidence = _stage_evidence("registry")
                if publication_status == PUBLICATION_STATUS_PUBLISHED:
                    registry_evidence.setdefault("verified", report.get("campaign_visibility_verified") is not False)
                publication_artifact = build_publication_report_artifact(
                    attempt_id=attempt_id,
                    source_title=str(canonical.get("source_title") or "Adaptation source"),
                    source_hash=source_hash,
                    source_path=source_path,
                    readiness_evidence={
                        name: _stage_evidence(name)
                        for name in (
                            "schema",
                            "readiness",
                            "mechanical_closure",
                            "semantic_authority",
                            "semantic_probes",
                            "report_agreement",
                        )
                    },
                    registry_evidence=registry_evidence,
                    publication_status=publication_status,
                    module_artifact_refs=module_refs,
                    markdown_evidence=_stage_evidence("markdown"),
                    campaign_evidence=_stage_evidence("campaign_sync"),
                    source_fidelity_status=str(
                        report.get("source_fidelity_status") or "not_applicable"
                    ),
                    attempt_number=attempt_number,
                    revision_number=revision_number,
                    published_at=report.get("generated_at")
                    if publication_status == PUBLICATION_STATUS_PUBLISHED
                    else None,
                    rights_class=str(canonical.get("rights_class") or "user_authored"),
                    rights_basis=str(canonical.get("rights_basis") or ""),
                    rights_review_required=(
                        canonical.get("rights_review_required") is True
                    ),
                    rights_review_status=str(
                        canonical.get("rights_review_status")
                        or "not_required"
                    ),
                    source_profile=(
                        str(canonical.get("source_profile"))
                        if canonical.get("source_profile") not in (None, "")
                        else None
                    ),
                    source_format=(
                        str(canonical.get("source_format"))
                        if canonical.get("source_format") not in (None, "")
                        else None
                    ),
                    model_metadata=(
                        canonical.get("model_metadata")
                        if isinstance(canonical.get("model_metadata"), Mapping)
                        else None
                    ),
                    metadata={
                        "created_by": "toolkit_module_finisher",
                        "publication_policy": "python_authority_before_publication",
                    },
                    world_context_provenance=canonical.get("world_context_provenance"),
                )
                publication_artifact_path = get_adaptation_artifact_path(
                    Path(artifact_workspace),
                    attempt_id,
                    ARTIFACT_KIND_PUBLICATION_REPORT,
                    revision_number,
                )
                attempt_artifact_path = get_adaptation_artifact_path(
                    Path(artifact_workspace),
                    attempt_id,
                    ARTIFACT_KIND_BUILD_RESULT,
                    revision_number,
                )
                report["attempt_report"] = {
                    "status": "referenced",
                    "path": str(attempt_artifact_path),
                    "artifact_kind": ARTIFACT_KIND_BUILD_RESULT,
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "revision_number": revision_number,
                }
                report["publication_report"] = {
                    "status": "pending_persist",
                    "path": str(publication_artifact_path),
                    "artifact_kind": ARTIFACT_KIND_PUBLICATION_REPORT,
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "revision_number": revision_number,
                    "created_at": publication_artifact.get("created_at"),
                }
        except Exception as exc:
            report["publication_report"] = {
                "status": "not_persisted",
                "reason": f"publication_report_build_failed:{exc}",
            }
            publication_artifact = None
    try:
        report_written = bool(safe_write_json(str(report_path), report))
    except Exception as exc:
        error(
            f"TOOLKIT_FINISHER: Adaptation report write failed: {exc}",
            category="module_ingest",
        )
        return False
    if not report_written:
        return False
    if (
        artifact_workspace is not None
        and isinstance(adaptation_provenance, Mapping)
        and publication_artifact is None
    ):
        report["adaptation_report_agreement"] = {
            "contract_version": "toolkit_adaptation_report_agreement.v1",
            "status": "blocked",
            "internal_coherent": False,
            "blockers": ["adaptation_publication_report_not_persisted"],
            "diagnostics": [],
        }
        report.setdefault("publication_report", {})["status"] = "agreement_blocked"
        report["publication_report"]["reason"] = "adaptation_publication_report_not_persisted"
        try:
            safe_write_json(str(report_path), report)
        except Exception:
            pass
        return False
    if publication_artifact is not None and artifact_workspace is not None:
        persisted = persist_publication_report_artifact(
            Path(artifact_workspace),
            publication_artifact,
            overwrite=True,
        )
        report.setdefault("publication_report", {})["status"] = (
            "persisted" if persisted else "not_persisted"
        )
        if not persisted:
            report["publication_report"]["reason"] = "publication_report_persist_failed"
            try:
                safe_write_json(str(report_path), report)
            except Exception:
                pass
            return False

        attempt_artifact = load_adaptation_artifact(
            Path(artifact_workspace),
            attempt_id,
            ARTIFACT_KIND_BUILD_RESULT,
            revision_number,
        )
        persisted_publication_artifact = load_adaptation_artifact(
            Path(artifact_workspace),
            attempt_id,
            ARTIFACT_KIND_PUBLICATION_REPORT,
            revision_number,
        )
        agreement = compose_adaptation_report_agreement(
            attempt_artifact,
            persisted_publication_artifact,
            expected_attempt_id=attempt_id,
            expected_source_hash=source_hash,
            expected_revision_number=revision_number,
            require_publication=True,
            completion_claim=report,
        )
        report["adaptation_report_agreement"] = agreement
        try:
            safe_write_json(str(report_path), report)
        except Exception:
            pass
        if agreement.get("status") != "pass":
            report["publication_report"]["status"] = "agreement_blocked"
            report["publication_report"]["reason"] = "adaptation_report_agreement_blocked"
            try:
                safe_write_json(str(report_path), report)
            except Exception:
                pass
            return False
    return True


def _public_adaptation_report_value(value: Any) -> Any:
    """Remove private in-memory rollback payloads before report persistence."""
    if isinstance(value, Mapping):
        return {
            key: _public_adaptation_report_value(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_public_adaptation_report_value(item) for item in value]
    return value


def _rollback_adaptation_registry_stage(
    registry_stage: Any,
    failure_reason: str,
) -> Dict[str, Any]:
    """Idempotently restore runtime state after a post-registration failure."""
    if not isinstance(registry_stage, dict):
        return {
            "status": "blocked",
            "attempted": False,
            "verified": False,
            "reason": "rollback_metadata_missing",
        }

    snapshot = registry_stage.get("_rollback_snapshot")
    if not isinstance(snapshot, Mapping):
        existing = registry_stage.get("rollback")
        if isinstance(existing, Mapping) and existing.get("status") == "success":
            return dict(existing)
        return {
            "status": "blocked",
            "attempted": False,
            "verified": False,
            "reason": "rollback_metadata_missing",
        }

    try:
        from utils.toolkit_adaptation_publication_transaction import (
            rollback_adaptation_publication,
        )

        rollback_result = rollback_adaptation_publication(
            snapshot,
            failure_reason=failure_reason,
        )
    except Exception as exc:
        rollback_result = {
            "status": "blocked",
            "attempted": True,
            "verified": False,
            "reason": f"rollback_exception:{exc}",
        }
    registry_stage["rollback"] = rollback_result
    registry_stage["publication_status"] = "blocked"
    return rollback_result


def _run_adaptation_postbuild_finishing(
    *,
    module_slug: str,
    adaptation_gates: Any,
    adaptation_staging_target: Optional[Mapping[str, Any]],
    adaptation_module_dir: Optional[str],
    adaptation_provenance: Optional[Mapping[str, Any]] = None,
    adaptation_artifact_workspace: Optional[str] = None,
    extra_stages: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Finish a staged adaptation with registry integration last.

    This is deliberately separate from the legacy finisher. The adaptation
    gate composer has already run the Python-owned schema, readiness,
    mechanical, semantic, and report-agreement checks against the staging
    target. This wrapper makes that contract explicit, adds the Markdown
    readability/write check, and calls the Python-owned registry stage only
    after every pre-publication check succeeds.
    """
    resolved = _resolve_adaptation_module_dir(
        staging_target=adaptation_staging_target,
        module_dir=adaptation_module_dir,
    )
    if resolved.get("status") != "success":
        return {
            "status": "failed",
            "module_slug": module_slug,
            "adaptation_mode": ADAPTATION_MODE_LLM,
            "reason": resolved.get("reason"),
            "stages": {
                "adaptation_gate_order": {
                    "status": "failed",
                    "reason": "staging_target_not_usable",
                },
                "registry": {
                    "status": "not_attempted",
                    "reason": "pre_registry_boundary_not_reached",
                },
            },
            "publication_order": list(_ADAPTATION_PUBLICATION_ORDER),
            "registry_is_final_stateful_publication": True,
            "python_authoritative": True,
        }

    module_dir = resolved["module_dir"]
    module_slug = str(resolved.get("module_slug") or module_slug).strip()
    artifact_workspace = (
        Path(adaptation_artifact_workspace)
        if adaptation_artifact_workspace
        else None
    )

    def _persist_report(report: Dict[str, Any]) -> bool:
        return _persist_adaptation_finishing_report(
            module_dir,
            report,
            artifact_workspace=artifact_workspace,
            adaptation_provenance=adaptation_provenance,
            staging_target=adaptation_staging_target,
        )

    stages: Dict[str, Any] = {}
    if extra_stages and isinstance(extra_stages, dict):
        for key, payload in extra_stages.items():
            if isinstance(payload, dict):
                stages[key] = payload

    artifact_check = _validate_adaptation_finishing_artifacts(
        adaptation_gates=adaptation_gates,
        staging_target=adaptation_staging_target,
        adaptation_provenance=adaptation_provenance,
        artifact_workspace=artifact_workspace,
    )
    if artifact_check.get("status") != "pass":
        stages["adaptation_artifact_freshness"] = {
            "status": "failed",
            "reason": str(
                artifact_check.get("reason_code")
                or "adaptation_current_artifact_stale"
            ),
            "diagnostics": list(artifact_check.get("diagnostics") or [])[:6],
        }
        stages["registry"] = {
            "status": "not_attempted",
            "reason": "adaptation_current_artifact_not_usable",
        }
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="blocked",
            reason=str(
                artifact_check.get("reason_code")
                or "adaptation_current_artifact_stale"
            ),
            adaptation_provenance=adaptation_provenance,
        )
        _persist_report(report)
        return report

    hard_safety_stage = _run_adaptation_hard_safety_stage(
        adaptation_gates=adaptation_gates,
        adaptation_provenance=adaptation_provenance,
    )
    stages["adaptation_hard_safety"] = hard_safety_stage
    if hard_safety_stage.get("status") != "success":
        stages["registry"] = {
            "status": "not_attempted",
            "reason": "adaptation_hard_safety_boundary_failed",
        }
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="blocked",
            reason="adaptation_hard_safety_boundary_failed",
            adaptation_provenance=adaptation_provenance,
        )
        _persist_report(report)
        return report

    gate_stage = _run_adaptation_gate_order_stage(adaptation_gates)
    stages["adaptation_gate_order"] = gate_stage
    if isinstance(adaptation_gates, Mapping):
        # Retain the complete Python-owned composition for truthful status
        # reporting; do not infer publication from the finisher stage alone.
        stages["adaptation_gates"] = dict(adaptation_gates)
    if isinstance(adaptation_gates, Mapping) and isinstance(
        adaptation_gates.get("gates"), Mapping
    ):
        for domain in _ADAPTATION_PUBLICATION_ORDER[:6]:
            gate_payload = adaptation_gates["gates"].get(domain)
            if isinstance(gate_payload, Mapping):
                stages[domain] = dict(gate_payload)
    if gate_stage.get("status") != "success":
        stages["registry"] = {
            "status": "not_attempted",
            "reason": "pre_registry_gate_failed",
        }
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="failed",
            reason="adaptation_prepublication_gates_failed",
            adaptation_provenance=adaptation_provenance,
        )
        _persist_report(report)
        return report

    report_gate = (
        adaptation_gates.get("gates", {}).get("report_agreement", {})
        if isinstance(adaptation_gates, Mapping)
        else {}
    )
    stages["report_agreement"] = dict(report_gate) if isinstance(report_gate, Mapping) else {}

    provenance_stage = _run_adaptation_provenance_stage(
        module_slug=module_slug,
        module_dir=module_dir,
        adaptation_provenance=adaptation_provenance,
        adaptation_gates=adaptation_gates,
    )
    stages["adaptation_provenance"] = provenance_stage
    if provenance_stage.get("status") == "failed":
        stages["registry"] = {
            "status": "not_attempted",
            "reason": "adaptation_provenance_persist_failed",
        }
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="failed",
            reason="adaptation_provenance_persist_failed",
            adaptation_provenance=adaptation_provenance,
        )
        _persist_report(report)
        return report

    # Generate Homebrewery module adventure summary and run the bounded
    # readability check before registry integration. The persisted artifact is
    # MODULE_SUMMARY.md.
    markdown_stage = _run_module_summary_stage(
        module_slug,
        module_dir,
        adaptation_mode=True,
        adaptation_provenance=adaptation_provenance,
    )
    stages["module_summary"] = markdown_stage
    stages["markdown"] = markdown_stage
    if markdown_stage.get("status") != "success":
        stages["registry"] = {
            "status": "not_attempted",
            "reason": "markdown_quality_check_failed",
        }
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="failed",
            reason="adaptation_markdown_quality_failed",
            adaptation_provenance=adaptation_provenance,
        )
        _persist_report(report)
        return report

    # Persist a pre-registration report before any registry write. This makes
    # report persistence itself a fail-closed boundary without claiming that
    # the candidate is completed before the final stateful step.
    stages["pre_registry_report"] = {
        "status": "pending_registry",
        "registry_allowed": True,
    }
    pre_registry_report = _build_adaptation_finishing_report(
        module_slug=module_slug,
        module_dir=module_dir,
        stages=stages,
        status="ready_for_registry",
        adaptation_provenance=adaptation_provenance,
    )
    if not _persist_report(pre_registry_report):
        stages["pre_registry_report"] = {
            "status": "failed",
            "reason": "pre_registry_report_persist_failed",
        }
        stages["registry"] = {
            "status": "not_attempted",
            "reason": "pre_registry_report_persist_failed",
        }
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="failed",
            reason="adaptation_pre_registry_report_failed",
            adaptation_provenance=adaptation_provenance,
        )
        _persist_report(report)
        return report

    # Registry integration remains the final world-registry write in the
    # adaptation path. The helper owns atomic module-plus-area integration and
    # exact post-write verification. Campaign availability is a separate,
    # Python-owned runtime-state sync after registry verification. The helper
    # captures rollback state before writing so later publication failures can
    # restore both runtime files.
    registry_stage = _run_registry_stage(
        module_slug=module_slug,
        module_dir=module_dir,
        adaptation=True,
    )
    if not isinstance(registry_stage, Mapping):
        registry_stage = {
            "status": "blocked",
            "reason": "adaptation_registry_stage_result_missing",
            "integration_attempted": False,
            "rollback": {
                "status": "blocked",
                "attempted": False,
                "verified": False,
                "reason": "rollback_metadata_missing",
            },
        }
    stages["registry"] = registry_stage
    registry_status = str(registry_stage.get("status") or "failed").strip().lower()
    registry_verified = registry_stage.get("verified") is True
    if registry_status == "success" and not registry_verified:
        registry_stage = dict(registry_stage)
        registry_stage["status"] = "blocked"
        registry_stage["reason"] = "registry_post_write_verification_missing"
        registry_stage["publication_status"] = "blocked"
        stages["registry"] = registry_stage
        registry_status = "blocked"

    if registry_status == "success":
        campaign_sync_stage = (
            registry_stage.get("campaign_sync")
            if isinstance(registry_stage.get("campaign_sync"), Mapping)
            else None
        )
        if campaign_sync_stage is None:
            campaign_sync_stage = _run_adaptation_campaign_sync_stage(
                module_slug,
                registry_path=Path.cwd() / "modules" / "world_registry.json",
                campaign_path=Path.cwd() / "modules" / "campaign.json",
            )
        if not isinstance(campaign_sync_stage, Mapping):
            campaign_sync_stage = {
                "status": "blocked",
                "reason": "adaptation_campaign_sync_result_missing",
                "campaign_visibility_verified": False,
            }
        stages["campaign_sync"] = campaign_sync_stage
        if isinstance(registry_stage, dict):
            registry_stage["campaign_sync"] = campaign_sync_stage
        campaign_sync_status = str(
            campaign_sync_stage.get("status") or "blocked"
        ).strip().lower()
        campaign_verified = (
            campaign_sync_status == "deferred"
            or campaign_sync_stage.get("campaign_visibility_verified") is True
        )
        final_status = (
            "success"
            if campaign_sync_status in {"success", "deferred"}
            and campaign_verified
            else "blocked"
        )
        final_reason = (
            ""
            if final_status == "success"
            else "adaptation_campaign_post_write_verification_failed"
        )
    else:
        existing_campaign_sync = registry_stage.get("campaign_sync")
        if isinstance(existing_campaign_sync, Mapping):
            stages["campaign_sync"] = dict(existing_campaign_sync)
        else:
            stages["campaign_sync"] = {
                "status": "not_attempted",
                "reason": "registry_publication_not_verified",
                "campaign_visibility_verified": False,
            }
        if isinstance(registry_stage, dict):
            registry_stage["campaign_sync"] = stages["campaign_sync"]
        final_status = "blocked"
        existing_campaign_status = str(
            stages["campaign_sync"].get("status") or "not_attempted"
        ).strip().lower()
        final_reason = (
            "adaptation_campaign_sync_failed"
            if existing_campaign_status in {"blocked", "failed"}
            else "adaptation_registry_stage_failed"
        )
    report = _build_adaptation_finishing_report(
        module_slug=module_slug,
        module_dir=module_dir,
        stages=stages,
        status=final_status,
        reason=final_reason,
        adaptation_provenance=adaptation_provenance,
    )
    if final_status != "success":
        _rollback_adaptation_registry_stage(
            registry_stage,
            final_reason or "adaptation_publication_failed",
        )
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="blocked",
            reason=final_reason or "adaptation_publication_blocked",
            adaptation_provenance=adaptation_provenance,
        )
    if not _persist_report(report):
        rollback_result = _rollback_adaptation_registry_stage(
            registry_stage,
            "adaptation_final_report_persist_failed",
        )
        stages["publication_rollback"] = rollback_result
        report = _build_adaptation_finishing_report(
            module_slug=module_slug,
            module_dir=module_dir,
            stages=stages,
            status="blocked",
            reason="adaptation_final_report_persist_failed",
            adaptation_provenance=adaptation_provenance,
        )
        report["publication_status"] = "blocked"
        report["rollback"] = rollback_result
        # Retry only the terminal report write. A persistent write failure
        # remains blocked and cannot claim a completed publication.
        _persist_report(report)
    return report


def run_toolkit_module_postbuild_finishing(
    module_slug: str,
    strict: bool = True,
    refresh_reason: str = "postbuild_finishing",
    refresh_workflow: str = "toolkit_postbuild_finisher",
    extra_stages: Optional[Dict[str, Any]] = None,
    adaptation_mode: Optional[str] = None,
    adaptation_gates: Optional[Mapping[str, Any]] = None,
    adaptation_staging_target: Optional[Mapping[str, Any]] = None,
    adaptation_module_dir: Optional[str] = None,
    adaptation_provenance: Optional[Mapping[str, Any]] = None,
    adaptation_artifact_workspace: Optional[str] = None,
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

    if _is_llm_adaptation_mode(adaptation_mode):
        resolved_adaptation_gates: Any = adaptation_gates
        if resolved_adaptation_gates is None and isinstance(extra_stages, dict):
            for key in ("adaptation_gates", "adaptation_gate_composition"):
                candidate = extra_stages.get(key)
                if isinstance(candidate, Mapping):
                    resolved_adaptation_gates = candidate
                    break
        return _run_adaptation_postbuild_finishing(
            module_slug=module_slug,
            adaptation_gates=resolved_adaptation_gates,
            adaptation_staging_target=adaptation_staging_target,
            adaptation_module_dir=adaptation_module_dir,
            adaptation_provenance=adaptation_provenance,
            adaptation_artifact_workspace=adaptation_artifact_workspace,
            extra_stages=extra_stages,
        )

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

    # TABLETOP MODE: Publishability metadata finalization (continuity + semantic
    # authority) using the centralized helper. Runs before the individual
    # continuity and semantic-authority stages so that they find no remaining
    # work and report no-op status.
    publishability_finalizer_stage = _run_publishability_finalizer_stage(
        module_slug=module_slug, module_dir=module_dir
    )
    stages["publishability_finalizer"] = publishability_finalizer_stage
    if (
        publishability_finalizer_stage.get("status") == "degraded"
        and overall_status != "failed"
    ):
        overall_status = "degraded"

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

    # TABLETOP MODE: Monster base media closure -- write placeholder JPEGs
    # for any monster that lacks a media/monsters/<slug>.jpg file.  Runs
    # after monster materialization so that the slug list is complete.
    monster_media_closure_stage = _run_monster_media_closure_stage(
        module_dir=module_dir
    )
    stages["monster_media_closure"] = monster_media_closure_stage
    if (
        monster_media_closure_stage.get("status") == "degraded"
        and overall_status != "failed"
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

    # Generate Homebrewery module adventure summary. Legacy finishing retains
    # its existing degraded-on-summary-failure behavior; the explicit
    # adaptation branch above uses the same helper as a hard pre-registration
    # gate.
    stages["module_summary"] = _run_module_summary_stage(
        module_slug,
        module_dir,
        adaptation_mode=False,
    )
    if stages["module_summary"].get("status") == "degraded":
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
            sf_mode = pub_report.get(
                "source_fidelity_mode", pub_report.get("adaptation_mode")
            )
            if not sf_mode:
                try:
                    source_report_path = module_dir / "source_fidelity_report.json"
                    if source_report_path.exists():
                        source_report_payload = json.loads(
                            source_report_path.read_text(encoding="utf-8")
                        )
                        if isinstance(source_report_payload, dict):
                            sf_mode = source_report_payload.get(
                                "adaptation_mode",
                                source_report_payload.get("source_fidelity_mode"),
                            )
                except Exception:
                    sf_mode = None
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

            report_freshness_states = {}
            source_report_path = module_dir / "source_fidelity_report.json"
            try:
                if source_report_path.exists():
                    source_report_payload = json.loads(
                        source_report_path.read_text(encoding="utf-8")
                    )
                    if isinstance(source_report_payload, dict):
                        freshness = source_report_payload.get(
                            "report_freshness", source_report_payload.get("freshness")
                        )
                        if isinstance(freshness, dict):
                            freshness_state = freshness.get(
                                "state", freshness.get("freshness_state")
                            )
                        else:
                            freshness_state = freshness
                        if not freshness_state:
                            freshness_state = source_report_payload.get(
                                "freshness_state"
                            )
                        if freshness_state:
                            report_freshness_states["source_fidelity"] = str(
                                freshness_state
                            ).strip().lower()
            except Exception:
                report_freshness_states["source_fidelity"] = "stale"

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
                source_fidelity_mode=sf_mode,
                report_freshness_states=(
                    report_freshness_states if report_freshness_states else None
                ),
                missing_reports=missing_list if missing_list else None,
            )

            stage_status = agreement.get("status", "failed")
            return {
                "status": stage_status,
                "internal_coherent": agreement.get("internal_coherent", False),
                "playable_publication_status": agreement.get("playable_publication_status", "unknown"),
                "source_fidelity_status": agreement.get("source_fidelity_status", "unknown"),
                "source_fidelity_mode": agreement.get("source_fidelity_mode"),
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
    if (
        llm_remediation_stage.get("status") == "degraded"
        and overall_status != "failed"
    ):
        overall_status = "degraded"

    # TABLETOP MODE: Context backup parity stage -- verify module_context.json
    # and module_context_BU.json are in exact parity after all mutations.
    # Failure here blocks playable status through pipeline_overall_status.
    context_parity_stage = _run_context_backup_parity_stage(module_dir)
    stages["context_backup_parity"] = context_parity_stage
    if context_parity_stage.get("status") == "failed":
        overall_status = "failed"

    # TABLETOP MODE: Ingest sidecar persistence -- write sidecar JSON for
    # sidecar audit compatibility.  Runs after all mutation stages.
    # Skipped if build has already failed to avoid misleading success sidecar.
    ingest_sidecar_stage = _run_ingest_sidecar_persistence_stage(
        module_slug=module_slug,
        module_dir=module_dir,
        build_status=overall_status,
    )
    stages["ingest_sidecar_persistence"] = ingest_sidecar_stage
    if (
        ingest_sidecar_stage.get("status") == "degraded"
        and overall_status != "failed"
    ):
        overall_status = "degraded"

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
    adaptation_mode: Optional[str] = None,
    adaptation_gates: Optional[Mapping[str, Any]] = None,
    adaptation_staging_target: Optional[Mapping[str, Any]] = None,
    adaptation_module_dir: Optional[str] = None,
    adaptation_provenance: Optional[Mapping[str, Any]] = None,
    adaptation_artifact_workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Run explicit report-refresh contract for publishability-facing workflows."""
    runner_kwargs: Dict[str, Any] = {
        "module_slug": module_slug,
        "strict": strict,
        "refresh_reason": refresh_reason,
        "refresh_workflow": "toolkit_report_refresh",
        "extra_stages": extra_stages,
    }
    if adaptation_mode is not None:
        runner_kwargs.update(
            {
                "adaptation_mode": adaptation_mode,
                "adaptation_gates": adaptation_gates,
                "adaptation_staging_target": adaptation_staging_target,
                "adaptation_module_dir": adaptation_module_dir,
                "adaptation_provenance": adaptation_provenance,
                "adaptation_artifact_workspace": adaptation_artifact_workspace,
            }
        )
    return run_toolkit_module_postbuild_finishing(
        **runner_kwargs,
    )
