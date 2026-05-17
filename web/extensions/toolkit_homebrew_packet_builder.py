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
    load_json_artifact,
    load_builder_blueprint_artifact,
    load_builder_blueprint_report_artifact,
    persist_build_result_artifact,
    persist_builder_input_artifact,
    persist_build_fidelity_report_artifact,
    persist_source_fidelity_report_artifact,
    validate_review_packet,
)

try:
    from model_config import ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF
except Exception:
    ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF = True


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
        `source_blueprint_ready` -- blueprint artifacts exist and status is ready.
        `blueprint_required_not_ready` -- blueprint is required but not ready.
        `legacy_allowed` -- workspace has no accurate-ingest evidence or blueprint handoff.
    """
    blueprint_enabled = bool(ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF)
    if not blueprint_enabled:
        return "legacy_allowed"

    blueprint_status = str((blueprint_artifact or {}).get("blueprint_status") or "").strip().lower()
    report_status = str((blueprint_report_artifact or {}).get("blueprint_status") or "").strip().lower()

    # Source-blueprint mode requires both artifacts to be present and ready.
    if blueprint_status == "ready" and report_status == "ready":
        return "source_blueprint_ready"

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
) -> Dict[str, Any]:
    """Build one approved Homebrew upload workspace from normalized packet."""
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

    if handoff_class == "source_blueprint_ready" and blueprint_report_artifact:
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

    narrative_bundle = _read_builder_narrative(files, packet, blueprint=blueprint_artifact)

    builder_input = {
        "status": "ready",
        "stage": "builder_input",
        "created_at": _utc_now_iso(),
        "job_id": job_id,
        "build_mode": "packet_workspace_v1",
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
            "build_mode": "packet_workspace_v1",
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
            "build_mode": "packet_workspace_v1",
            "completed_at": _utc_now_iso(),
            "packet_identity": builder_input["packet_identity"],
            "module_name": params["module_name"],
            "output_directory": params["output_directory"],
            "builder_input_path": str(files["builder_input"]),
            "build_result_path": str(files["build_result"]),
            "error": str(build_error),
        }

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

    build_result["build_result_persisted"] = persist_build_result_artifact(workspace, build_result)
    if not build_result["build_result_persisted"]:
        build_result["status"] = "failed"
        build_result["error"] = "build_result_persist_failed"
        return build_result

    return build_result
