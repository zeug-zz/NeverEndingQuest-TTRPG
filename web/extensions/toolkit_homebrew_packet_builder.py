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

import math
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from utils.enhanced_logger import error, info, warning
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    get_workspace_files,
    load_builder_blueprint_artifact,
    load_builder_blueprint_report_artifact,
    load_json_artifact,
    persist_build_result_artifact,
    persist_builder_input_artifact,
    persist_build_fidelity_report_artifact,
    persist_narrative_enrichment_plan_artifact,
    persist_source_fidelity_report_artifact,
    validate_review_packet,
)

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

_VALID_SEED_WRITER_MODES = frozenset({"fallback", "preview", "support"})
_SEED_BUILD_MODES = {
    "fallback": "blueprint_seed_fallback",
    "preview": "blueprint_seed_preview",
    "support": "blueprint_seed_support",
}


def _utc_now_iso() -> str:
    """Return UTC timestamp in ISO-8601 format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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

    params = builder_input["derived_builder_parameters"]
    config = BuilderConfig(
        module_name=params["module_name"],
        num_areas=params["num_areas"],
        locations_per_area=params["locations_per_area"],
        output_directory=params["output_directory"],
        verbose=True,
    )
    builder = ModuleBuilder(config)
    if progress_callback:
        builder.progress_callback = progress_callback

        original_log = builder.log

        def _log_with_progress(message: str) -> None:
            original_log(message)
            progress_callback("log", message)

        builder.log = _log_with_progress  # type: ignore[assignment]

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
    # v2 mode — seed writer handles whatever the packet contains.
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


def run_toolkit_homebrew_packet_build(
    workspace: Path,
    job_id: str,
    builder_executor: Optional[Callable[..., None]] = None,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    overwrite_confirmed: bool = False,
    seed_writer_mode: Optional[str] = None,
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

    Returns:
        Dict with build result status and metadata.
    """
    files = get_workspace_files(workspace)
    packet = load_json_artifact(files["normalized_packet"])
    packet_ok, packet_error = validate_review_packet(packet)
    if not packet_ok:
        return {
            "status": "failed",
            "stage": "build",
            "error": f"normalized_packet_invalid:{packet_error}",
            "job_id": job_id,
        }

    review_snapshot = load_json_artifact(files["ui_review_snapshot"])
    review_error = _validate_review_snapshot(packet, review_snapshot)
    if review_error:
        return {
            "status": "failed",
            "stage": "build",
            "error": review_error,
            "job_id": job_id,
        }

    params = _derive_builder_shape(packet)
    blueprint_artifact = load_builder_blueprint_artifact(workspace)
    blueprint_report_artifact = load_builder_blueprint_report_artifact(workspace)
    handoff_class = _classify_blueprint_handoff(files, blueprint_artifact, blueprint_report_artifact)

    # Overwrite authorization: refuse to write over an existing module
    # directory unless route-level confirmation or a valid rebuild plan
    # artifact is present.
    _module_dir = Path(params["output_directory"])
    if _module_dir.exists() and not overwrite_confirmed:
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

    _build_mode = "packet_workspace_v1"
    if _use_seed_writer and _seed_writer_mode:
        _build_mode = _SEED_BUILD_MODES.get(_seed_writer_mode, "packet_workspace_v2")
    elif handoff_class in ("source_blueprint_v2_ready", "source_blueprint_v2_degraded"):
        _build_mode = "source_enhanced_modulebuilder"
    elif handoff_class == "source_blueprint_ready":
        _build_mode = "source_blueprint_modulebuilder"

    _v2_build_result: Optional[Dict[str, Any]] = None
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
        if blueprint_metadata:
            builder_input["handoff_mode"] = "source_blueprint"
            builder_input["blueprint"] = blueprint_metadata

        # Source contract: carry source-fidelity tokens from the blueprint
        # so ModuleBuilder receives required NPCs, locations, puzzles, and tone
        # guidance without needing to re-read the blueprint file.
        if blueprint_metadata and isinstance(blueprint_artifact, dict) and blueprint_artifact:
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

        if not persist_builder_input_artifact(workspace, builder_input):
            return {
                "status": "failed",
                "stage": "build",
                "error": "builder_input_persist_failed",
                "job_id": job_id,
                "packet_identity": builder_input["packet_identity"],
            }

        executor = builder_executor or _execute_module_builder

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
                "packet_identity": builder_input["packet_identity"],
                "module_name": params["module_name"],
                "output_directory": params["output_directory"],
                "builder_input_path": str(files["builder_input"]),
                "build_result_path": str(files["build_result"]),
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
                "packet_identity": builder_input["packet_identity"],
                "module_name": params["module_name"],
                "output_directory": params["output_directory"],
                "builder_input_path": str(files["builder_input"]),
                "build_result_path": str(files["build_result"]),
                "error": str(build_error),
            }

    if _use_seed_writer:
        build_result = _v2_build_result  # type: ignore[assignment]
        build_result["build_mode"] = _build_mode
        if _seed_writer_mode:
            build_result["seed_writer_mode"] = _seed_writer_mode

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
            fidelity_report = build_build_fidelity_report(workspace, module_dir)
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
            if not can_continue:
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

    build_result["build_result_persisted"] = persist_build_result_artifact(workspace, build_result)
    if not build_result["build_result_persisted"]:
        build_result["status"] = "failed"
        build_result["error"] = "build_result_persist_failed"
        return build_result

    return build_result
