# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Homebrew Upload Contracts
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Shared contract helpers for public toolkit Homebrew markdown and PDF upload artifacts.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from utils.file_operations import safe_write_json


PACKET_CONTRACT_VERSION = "v1"
REVIEW_POLICY_DEFAULT = "mandatory_human_review"
V2_ALIGNMENT_DEFAULT = "pre_v2_interactive_import"

REVIEW_DECISION_APPROVE = "approve"
REVIEW_DECISION_REJECT = "reject"

VALID_REVIEW_DECISIONS = {
    REVIEW_DECISION_APPROVE,
    REVIEW_DECISION_REJECT,
}

SOURCE_RIGHTS_USER_AUTHORED = "user_authored"
SOURCE_RIGHTS_LICENSED = "licensed_or_project_owned"
SOURCE_RIGHTS_RESTRICTED = "third_party_copyright_restricted"

VALID_SOURCE_RIGHTS_CLASSES = {
    SOURCE_RIGHTS_USER_AUTHORED,
    SOURCE_RIGHTS_LICENSED,
    SOURCE_RIGHTS_RESTRICTED,
}


def _utc_now_iso() -> str:
    """Return UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_workspace_files(workspace: Path) -> Dict[str, Path]:
    """Return canonical file paths for toolkit Homebrew upload workspace."""
    return {
        "source_original": workspace / "source_original.md",
        "source_upload_original_pdf": workspace / "source_upload_original.pdf",
        "pdf_conversion_report": workspace / "pdf_conversion_report.json",
        "source_preflight": workspace / "source_preflight.json",
        "normalized_packet": workspace / "normalized_packet.json",
        "normalization_report": workspace / "normalization_report.json",
        "builder_input": workspace / "builder_input.json",
        "builder_narrative": workspace / "builder_narrative.txt",
        "build_result": workspace / "build_result.json",
        "readiness_validation_report": workspace / "readiness_validation_report.json",
        "readiness_audit_report": workspace / "readiness_audit_report.json",
        "repair_report": workspace / "repair_report.json",
        "finishing_report": workspace / "finishing_report.json",
        "ui_review_snapshot": workspace / "ui_review_snapshot.json",
        "source_manifest": workspace / "source_manifest.json",
        "source_graph": workspace / "source_graph.json",
        "section_extractions_index": workspace / "section_extractions/index.json",
        "identity_resolution_report": workspace / "identity_resolution_report.json",
        "plot_topology_report": workspace / "plot_topology_report.json",
        "source_graph_synthesis_report": workspace / "source_graph_synthesis_report.json",
        "normalization_fidelity_report": workspace / "normalization_fidelity_report.json",
        "normalization_repair_report": workspace / "normalization_repair_report.json",
        "packet_repair_attempts_index": workspace / "packet_repair_attempts/index.json",
        "builder_blueprint": workspace / "builder_blueprint.json",
        "builder_blueprint_report": workspace / "builder_blueprint_report.json",
        "build_fidelity_report": workspace / "build_fidelity_report.json",
        "source_fidelity_report": workspace / "source_fidelity_report.json",
    }


def ensure_workspace_placeholders(workspace: Path) -> Dict[str, Any]:
    """Create stable placeholder files for later uploader stages."""
    workspace.mkdir(parents=True, exist_ok=True)
    files = get_workspace_files(workspace)

    placeholders = {
        "source_preflight": {
            "status": "pending",
            "stage": "preflight",
            "updated_at": _utc_now_iso(),
        },
        "normalized_packet": {
            "packet_version": PACKET_CONTRACT_VERSION,
            "status": "pending",
            "stage": "normalization",
            "updated_at": _utc_now_iso(),
        },
        "normalization_report": {
            "status": "pending",
            "stage": "normalization",
            "updated_at": _utc_now_iso(),
        },
        "builder_input": {
            "status": "pending",
            "stage": "builder_input",
            "updated_at": _utc_now_iso(),
        },
        "build_result": {
            "status": "pending",
            "stage": "build",
            "updated_at": _utc_now_iso(),
        },
        "readiness_validation_report": {
            "status": "pending",
            "stage": "readiness_validation",
            "updated_at": _utc_now_iso(),
        },
        "readiness_audit_report": {
            "status": "pending",
            "stage": "readiness_audit",
            "updated_at": _utc_now_iso(),
        },
        "repair_report": {
            "status": "pending",
            "stage": "repair",
            "updated_at": _utc_now_iso(),
        },
        "finishing_report": {
            "status": "pending",
            "stage": "finishing",
            "updated_at": _utc_now_iso(),
        },
        "ui_review_snapshot": {
            "status": "pending",
            "stage": "review",
            "updated_at": _utc_now_iso(),
        },
    }

    for key, payload in placeholders.items():
        target_path = files[key]
        if not target_path.exists():
            safe_write_json(str(target_path), payload)

    if not files["builder_narrative"].exists():
        files["builder_narrative"].write_text("", encoding="utf-8")

    return {"workspace": str(workspace), "files": {k: str(v) for k, v in files.items()}}


def compute_sha256(file_path: Path) -> str:
    """Return SHA-256 digest for file contents."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_normalized_packet_placeholder(
    source_path: Path,
    source_hash: str,
    preflight: Dict[str, Any],
    source_rights_class: str = SOURCE_RIGHTS_USER_AUTHORED,
    review_policy: str = REVIEW_POLICY_DEFAULT,
    v2_alignment: str = V2_ALIGNMENT_DEFAULT,
) -> Dict[str, Any]:
    """Build canonical normalized packet placeholder for normalization-required sources."""
    title = str(preflight.get("normalized_title") or preflight.get("title") or source_path.stem)
    warnings = []
    for issue in preflight.get("issues", []):
        if not isinstance(issue, dict):
            continue
        issue_type = str(issue.get("type") or "unknown")
        recommended = str(issue.get("recommended") or "")
        warnings.append(
            {
                "type": issue_type,
                "message": recommended or issue_type,
            }
        )

    return {
        "packet_version": PACKET_CONTRACT_VERSION,
        "normalization_state": "placeholder",
        "source_path": str(source_path),
        "source_hash": source_hash,
        "title": title,
        "author": "",
        "description": "",
        "estimated_level_min": None,
        "estimated_level_max": None,
        "adventure_summary": "",
        "module_tone": "",
        "acts": [],
        "locations": [],
        "connectivity_hints": [],
        "encounter_seeds": [],
        "npc_seeds": [],
        "monster_refs": [],
        "plot_progression": [],
        "continuity_hints": [],
        "media_hints": [],
        "assumptions": [
            "Readable source requires normalization before deterministic ingest/build."
        ],
        "warnings": warnings,
        "confidence_notes": {
            "source_readable": bool(preflight.get("source_readable", True)),
            "structure_class": preflight.get("structure_class", "unknown"),
            "routing_outcome": preflight.get("routing_outcome", "normalization_required"),
        },
        "provenance": {
            "source_filename": source_path.name,
            "created_at": _utc_now_iso(),
            "preflight": {
                "ready": bool(preflight.get("ready", False)),
                "can_auto_transform": bool(preflight.get("can_auto_transform", False)),
                "structure_class": preflight.get("structure_class", "unknown"),
            },
        },
        "source_rights_class": source_rights_class,
        "review_policy": review_policy,
        "v2_alignment": v2_alignment,
    }


def persist_preflight_artifact(workspace: Path, preflight: Dict[str, Any]) -> bool:
    """Persist source preflight artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["source_preflight"]), preflight)


def persist_normalized_packet_artifact(workspace: Path, packet: Dict[str, Any]) -> bool:
    """Persist normalized packet artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["normalized_packet"]), packet)


def persist_normalization_report_artifact(workspace: Path, report: Dict[str, Any]) -> bool:
    """Persist normalization report artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["normalization_report"]), report)


def persist_builder_narrative_artifact(workspace: Path, narrative: str) -> bool:
    """Persist builder narrative artifact text file."""
    files = get_workspace_files(workspace)
    try:
        files["builder_narrative"].write_text(str(narrative or ""), encoding="utf-8")
        return True
    except Exception:
        return False


def persist_builder_input_artifact(workspace: Path, builder_input: Dict[str, Any]) -> bool:
    """Persist builder input artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["builder_input"]), builder_input)


def persist_build_result_artifact(workspace: Path, build_result: Dict[str, Any]) -> bool:
    """Persist build result artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["build_result"]), build_result)


def persist_readiness_validation_artifact(
    workspace: Path,
    validation_report: Dict[str, Any],
) -> bool:
    """Persist readiness validation artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["readiness_validation_report"]), validation_report)


def persist_readiness_audit_artifact(
    workspace: Path,
    readiness_audit_report: Dict[str, Any],
) -> bool:
    """Persist readiness audit artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["readiness_audit_report"]), readiness_audit_report)


def persist_repair_report_artifact(workspace: Path, repair_report: Dict[str, Any]) -> bool:
    """Persist repair report artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["repair_report"]), repair_report)


def persist_source_manifest_artifact(workspace: Path, manifest: Dict[str, Any]) -> bool:
    """Persist source manifest artifact using atomic JSON helper."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["source_manifest"]), manifest)


def persist_source_graph_artifact(workspace: Path, graph: Dict[str, Any]) -> bool:
    """Persist source graph artifact using atomic JSON helper."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["source_graph"]), graph)


def load_source_manifest_artifact(workspace: Path) -> Optional[Dict[str, Any]]:
    """Load source manifest artifact if present. Returns None for
    backward-compatible workspaces that lack this artifact."""
    files = get_workspace_files(workspace)
    path = files.get("source_manifest")
    if path and path.exists():
        return load_json_artifact(path)
    return None


def load_source_graph_artifact(workspace: Path) -> Optional[Dict[str, Any]]:
    """Load source graph artifact if present. Returns None for
    backward-compatible workspaces that lack this artifact."""
    files = get_workspace_files(workspace)
    path = files.get("source_graph")
    if path and path.exists():
        return load_json_artifact(path)
    return None


def load_normalized_packet_artifact(workspace: Path) -> Dict[str, Any]:
    """Load normalized packet artifact from canonical workspace location."""
    files = get_workspace_files(workspace)
    return load_json_artifact(files["normalized_packet"])


def normalize_review_decision(raw_decision: Optional[str]) -> str:
    """Normalize review decision input to canonical lowercase action."""
    return str(raw_decision or "").strip().lower()


def validate_review_packet(packet: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate normalized packet has minimum reviewable identity fields."""
    if not isinstance(packet, dict) or not packet:
        return False, "normalized_packet_missing"

    packet_version = str(packet.get("packet_version") or "").strip()
    if not packet_version:
        return False, "packet_version_missing"

    source_hash = str(packet.get("source_hash") or "").strip()
    if not source_hash:
        return False, "source_hash_missing"

    title = str(packet.get("title") or "").strip()
    if not title:
        return False, "title_missing"

    normalization_state = str(packet.get("normalization_state") or "").strip().lower()
    if normalization_state != "normalized":
        return False, "normalization_state_not_ready"

    return True, "ok"


def validate_normalization_artifacts(workspace: Path) -> Tuple[bool, str]:
    """Validate normalization artifacts are persisted and review-ready."""
    files = get_workspace_files(workspace)

    packet = load_json_artifact(files["normalized_packet"])
    packet_ok, packet_error = validate_review_packet(packet)
    if not packet_ok:
        return False, f"normalized_packet_invalid:{packet_error}"

    report = load_json_artifact(files["normalization_report"])
    if not isinstance(report, dict) or not report:
        return False, "normalization_report_missing"

    report_status = str(report.get("status") or "").strip().lower()
    if report_status != "success":
        return False, "normalization_report_not_success"

    if not files["builder_narrative"].exists():
        return False, "builder_narrative_missing"

    try:
        narrative_text = files["builder_narrative"].read_text(encoding="utf-8").strip()
    except Exception:
        return False, "builder_narrative_unreadable"

    if not narrative_text:
        return False, "builder_narrative_empty"

    return True, "ok"


def build_review_summary(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Build curated review summary payload from normalized packet."""
    return {
        "title": str(packet.get("title") or "").strip(),
        "author": str(packet.get("author") or "").strip(),
        "description": str(packet.get("description") or "").strip(),
        "estimated_level_min": packet.get("estimated_level_min"),
        "estimated_level_max": packet.get("estimated_level_max"),
        "locations": packet.get("locations") or [],
        "npc_seeds": packet.get("npc_seeds") or [],
        "monster_refs": packet.get("monster_refs") or [],
        "warnings": packet.get("warnings") or [],
        "assumptions": packet.get("assumptions") or [],
    }


def build_review_snapshot(
    job_id: str,
    decision: str,
    packet: Dict[str, Any],
    source_rights_class: str,
) -> Dict[str, Any]:
    """Build canonical review snapshot artifact for audit and later handoff."""
    return {
        "status": "recorded",
        "stage": "review",
        "job_id": job_id,
        "decision": decision,
        "recorded_at": _utc_now_iso(),
        "packet_identity": {
            "packet_version": packet.get("packet_version"),
            "source_hash": packet.get("source_hash"),
            "source_path": packet.get("source_path"),
            "title": packet.get("title"),
        },
        "source_rights_class": source_rights_class,
    }


def persist_review_snapshot_artifact(workspace: Path, snapshot: Dict[str, Any]) -> bool:
    """Persist review snapshot artifact using atomic JSON helper."""
    files = get_workspace_files(workspace)
    return safe_write_json(str(files["ui_review_snapshot"]), snapshot)


def load_json_artifact(file_path: Path) -> Dict[str, Any]:
    """Load JSON artifact file with simple fallback."""
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def persist_section_extraction_artifact(
    workspace: Path,
    section_id: str,
    payload: Dict[str, Any],
) -> bool:
    """Persist a per-section extraction artifact using atomic JSON helper."""
    from utils.file_operations import safe_write_json

    section_dir = workspace / "section_extractions"
    section_dir.mkdir(parents=True, exist_ok=True)
    target = section_dir / f"{section_id}.json"
    return safe_write_json(str(target), payload)


def persist_section_extractions_index(
    workspace: Path,
    index_payload: Dict[str, Any],
) -> bool:
    """Persist the section_extractions/index.json registry."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    index_path = files["section_extractions_index"]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    return safe_write_json(str(index_path), index_payload)


def persist_identity_resolution_artifact(
    workspace: Path,
    report: Dict[str, Any],
) -> bool:
    """Persist identity_resolution_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["identity_resolution_report"]), report)


def persist_plot_topology_artifact(
    workspace: Path,
    report: Dict[str, Any],
) -> bool:
    """Persist plot_topology_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["plot_topology_report"]), report)


def persist_source_graph_synthesis_artifact(
    workspace: Path,
    report: Dict[str, Any],
) -> bool:
    """Persist source_graph_synthesis_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["source_graph_synthesis_report"]), report)


def load_section_extraction_artifact(
    workspace: Path,
    section_id: str,
) -> Optional[Dict[str, Any]]:
    """Load a per-section extraction artifact if present. Returns None if missing."""
    section_dir = workspace / "section_extractions"
    target = section_dir / f"{section_id}.json"
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def persist_normalization_fidelity_artifact(
    workspace: Path,
    report: Dict[str, Any],
) -> bool:
    """Persist normalization_fidelity_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["normalization_fidelity_report"]), report)


def persist_normalization_repair_artifact(
    workspace: Path,
    report: Dict[str, Any],
) -> bool:
    """Persist normalization_repair_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["normalization_repair_report"]), report)


def persist_packet_repair_attempt_artifact(
    workspace: Path,
    attempt: int,
    payload: Dict[str, Any],
) -> bool:
    """Persist a packet_repair_attempts/attempt_<n>.json artifact."""
    from utils.file_operations import safe_write_json

    attempts_dir = workspace / "packet_repair_attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    target = attempts_dir / f"attempt_{attempt}.json"
    return safe_write_json(str(target), payload)


def persist_packet_repair_attempts_index(
    workspace: Path,
    index_payload: Dict[str, Any],
) -> bool:
    """Persist the packet_repair_attempts/index.json registry."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    index_path = files["packet_repair_attempts_index"]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    return safe_write_json(str(index_path), index_payload)


def persist_builder_blueprint_artifact(workspace: Path, blueprint: Dict[str, Any]) -> bool:
    """Persist builder_blueprint.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["builder_blueprint"]), blueprint)


def persist_builder_blueprint_report_artifact(workspace: Path, report: Dict[str, Any]) -> bool:
    """Persist builder_blueprint_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["builder_blueprint_report"]), report)


def load_builder_blueprint_artifact(workspace: Path) -> Optional[Dict[str, Any]]:
    """Load builder_blueprint.json if present.  Returns None for legacy workspaces."""
    files = get_workspace_files(workspace)
    path = files.get("builder_blueprint")
    if path and path.exists():
        return load_json_artifact(path)
    return None


def load_builder_blueprint_report_artifact(workspace: Path) -> Optional[Dict[str, Any]]:
    """Load builder_blueprint_report.json if present."""
    files = get_workspace_files(workspace)
    path = files.get("builder_blueprint_report")
    if path and path.exists():
        return load_json_artifact(path)
    return None


def persist_build_fidelity_report_artifact(workspace: Path, report: Dict[str, Any]) -> bool:
    """Persist build_fidelity_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["build_fidelity_report"]), report)


def load_build_fidelity_report_artifact(workspace: Path) -> Optional[Dict[str, Any]]:
    """Load build_fidelity_report.json if present."""
    files = get_workspace_files(workspace)
    path = files.get("build_fidelity_report")
    if path and path.exists():
        return load_json_artifact(path)
    return None


def persist_source_fidelity_report_artifact(workspace: Path, report: Dict[str, Any]) -> bool:
    """Persist source_fidelity_report.json."""
    from utils.file_operations import safe_write_json

    files = get_workspace_files(workspace)
    return safe_write_json(str(files["source_fidelity_report"]), report)


def load_source_fidelity_report_artifact(workspace: Path) -> Optional[Dict[str, Any]]:
    """Load source_fidelity_report.json if present."""
    files = get_workspace_files(workspace)
    path = files.get("source_fidelity_report")
    if path and path.exists():
        return load_json_artifact(path)
    return None
