# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Web Extension - Toolkit Homebrew Fidelity Review
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Artifact-only fidelity review helpers for accurate-ingest workspaces.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from utils.toolkit_homebrew_upload_contract import get_workspace_files

_ACCURATE_INGEST_EVIDENCE_KEYS = (
    "source_graph",
    "identity_resolution_report",
    "plot_topology_report",
    "source_graph_synthesis_report",
    "normalization_fidelity_report",
    "normalization_repair_report",
    "packet_repair_attempts_index",
    "builder_blueprint",
    "builder_blueprint_report",
)

_REQUIRED_ACCURATE_INGEST_KEYS = (
    "source_graph",
    "identity_resolution_report",
    "plot_topology_report",
    "source_graph_synthesis_report",
    "normalization_fidelity_report",
    "normalization_report",
    "normalization_repair_report",
    "packet_repair_attempts_index",
    "builder_blueprint",
    "builder_blueprint_report",
)

_MAX_FINDINGS = 6
_MAX_ATTEMPTS = 3


def _load_json_artifact(path: Path) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    record: Dict[str, Any] = {
        "exists": path.exists(),
        "path": str(path),
        "artifact_path": str(path),
        "status": "missing",
    }

    if not path.exists():
        return record, None

    try:
        record["size_bytes"] = path.stat().st_size
    except Exception:
        record["size_bytes"] = None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            record["status"] = "failed"
            record["error"] = "json_not_object"
            return record, None
        record["status"] = "loaded"
        return record, payload
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        return record, None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _compact_finding(finding: Dict[str, Any], *, artifact_path: str) -> Dict[str, Any]:
    compact = {
        "severity": str(finding.get("severity") or "unknown"),
        "category": str(finding.get("category") or finding.get("type") or "unknown"),
        "message": str(
            finding.get("detail")
            or finding.get("message")
            or finding.get("reason")
            or ""
        ).strip(),
        "artifact_path": artifact_path,
    }

    packet_path = finding.get("packet_path") or finding.get("path") or ""
    if packet_path:
        compact["path"] = str(packet_path)

    source_atom_id = finding.get("source_atom_id") or ""
    if source_atom_id:
        compact["source_atom_id"] = str(source_atom_id)

    expected = finding.get("expected")
    if expected not in (None, ""):
        compact["expected"] = expected

    actual = finding.get("actual")
    if actual not in (None, ""):
        compact["actual"] = actual

    repairable = finding.get("repairable")
    if repairable is not None:
        compact["repairable"] = bool(repairable)

    return compact


def _bounded_findings(
    findings: Iterable[Dict[str, Any]],
    severity: str,
    *,
    artifact_path: str,
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("severity") or "").lower() != severity:
            continue
        matched.append(_compact_finding(finding, artifact_path=artifact_path))
        if len(matched) >= _MAX_FINDINGS:
            break
    return matched


def _count_source_atoms(source_graph: Dict[str, Any]) -> Dict[str, int]:
    atoms = source_graph.get("atoms") or []
    counts = Counter()
    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        atom_type = str(atom.get("type") or "").strip().lower()
        if atom_type:
            counts[atom_type] += 1

    return {
        "npc": counts.get("npc", 0),
        "location": counts.get("location", 0),
        "plot": counts.get("plot_beat", 0),
        "puzzle": counts.get("puzzle", 0),
        "clue": counts.get("clue", 0),
        "encounter": counts.get("encounter", 0),
        "item": counts.get("item", 0),
        "tone": counts.get("tone_marker", 0),
    }


def _summarize_fidelity_report(
    fidelity_report: Dict[str, Any],
    *,
    artifact_path: str,
) -> Dict[str, Any]:
    summary = fidelity_report.get("summary") or {}
    findings = fidelity_report.get("findings") or []
    if not isinstance(findings, list):
        findings = []

    blocking = _bounded_findings(findings, "blocking", artifact_path=artifact_path)
    warnings = _bounded_findings(findings, "warning", artifact_path=artifact_path)
    infos = _bounded_findings(findings, "info", artifact_path=artifact_path)

    return {
        "status": str(fidelity_report.get("status") or summary.get("status") or "unknown").lower(),
        "reason": str(fidelity_report.get("reason") or "").strip(),
        "blocking_count": _safe_int(summary.get("blocking_count"), len(blocking)),
        "warning_count": _safe_int(summary.get("warning_count"), len(warnings)),
        "info_count": _safe_int(summary.get("info_count"), len(infos)),
        "covered_required": _safe_int(summary.get("covered_required"), 0),
        "total_required": _safe_int(summary.get("total_required"), 0),
        "blockers": blocking,
        "warnings": warnings,
        "info": infos,
    }


def _summarize_repair_attempts(
    workspace: Path,
    repair_report: Dict[str, Any],
    repair_index: Dict[str, Any],
) -> Dict[str, Any]:
    report_summary = repair_report.get("summary") or {}
    entries = repair_index.get("entries")
    if not isinstance(entries, list):
        entries = []

    compact_entries: List[Dict[str, Any]] = []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        attempt = _safe_int(entry.get("attempt"), 0)
        attempt_path = workspace / "packet_repair_attempts" / f"attempt_{attempt}.json"
        compact_entries.append(
            {
                "attempt": attempt,
                "status": str(entry.get("status") or "unknown"),
                "artifact_path": str(attempt_path),
            }
        )
        if len(compact_entries) >= _MAX_ATTEMPTS:
            break

    latest = compact_entries[0] if compact_entries else {}
    attempt_count = repair_index.get("total_attempts")
    if attempt_count is None:
        attempt_count = len(entries)
    if attempt_count is None:
        attempt_count = _safe_int(report_summary.get("repair_attempts"), 0)

    latest_path = latest.get("artifact_path") or str(workspace / "packet_repair_attempts" / "index.json")

    return {
        "attempt_count": _safe_int(attempt_count, 0),
        "latest_status": str(
            repair_report.get("status")
            or report_summary.get("repair_status")
            or latest.get("status")
            or "unknown"
        ),
        "latest_attempt_path": latest.get("artifact_path") or "",
        "report_path": repair_report.get("artifact_path") or repair_report.get("path") or "",
        "index_path": repair_index.get("artifact_path") or repair_index.get("path") or "",
        "attempts": compact_entries,
        "latest_artifact_path": latest_path,
    }


def _summarize_blueprint(
    workspace: Path,
    blueprint: Dict[str, Any],
    blueprint_report: Dict[str, Any],
) -> Dict[str, Any]:
    source_coverage = blueprint_report.get("source_coverage") or {}
    blueprint_coverage = blueprint_report.get("blueprint_coverage") or {}
    warnings = blueprint_report.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = []

    return {
        "status": str(blueprint_report.get("blueprint_status") or blueprint_report.get("status") or "missing").lower(),
        "fidelity_status": str(blueprint_report.get("fidelity_status") or "unknown").lower(),
        "refusal_reason": str(blueprint_report.get("refusal_reason") or "").strip(),
        "ready": str(blueprint_report.get("blueprint_status") or "").lower() == "ready",
        "artifact_path": blueprint_report.get("artifact_path") or blueprint_report.get("path") or str(
            get_workspace_files(workspace)["builder_blueprint_report"]
        ),
        "blueprint_path": blueprint.get("artifact_path") or blueprint.get("path") or str(
            get_workspace_files(workspace)["builder_blueprint"]
        ),
        "source_coverage": {
            "location_candidates": _safe_int(source_coverage.get("location_candidates"), 0),
            "npc_candidates": _safe_int(source_coverage.get("npc_candidates"), 0),
            "canonical_identities": _safe_int(source_coverage.get("canonical_identities"), 0),
            "plot_beats": _safe_int(source_coverage.get("plot_beats"), 0),
            "puzzle_chains": _safe_int(source_coverage.get("puzzle_chains"), 0),
        },
        "blueprint_coverage": {
            "locations_in_blueprint": _safe_int(blueprint_coverage.get("locations_in_blueprint"), 0),
            "npcs_in_blueprint": _safe_int(blueprint_coverage.get("npcs_in_blueprint"), 0),
        },
        "warnings": [
            {
                "severity": "warning",
                "category": str(item.get("source") or item.get("category") or "blueprint"),
                "message": str(item.get("message") or item.get("detail") or "").strip(),
            }
            for item in warnings[:_MAX_FINDINGS]
            if isinstance(item, dict)
        ],
    }


def is_accurate_ingest_workspace(workspace: Path) -> bool:
    files = get_workspace_files(Path(workspace))
    return any(
        bool(files.get(key) and files[key].exists())
        for key in _ACCURATE_INGEST_EVIDENCE_KEYS
    )


def build_fidelity_review_payload(workspace: Path) -> Dict[str, Any]:
    workspace = Path(workspace)
    files = get_workspace_files(workspace)

    artifact_records: Dict[str, Dict[str, Any]] = {}
    payloads: Dict[str, Dict[str, Any]] = {}
    for key in _REQUIRED_ACCURATE_INGEST_KEYS:
        record, payload = _load_json_artifact(files[key])
        artifact_records[key] = record
        if payload is not None:
            payloads[key] = payload

    evidence_present = is_accurate_ingest_workspace(workspace)
    if not evidence_present:
        return {
            "mode": "legacy",
            "status": "legacy",
            "can_approve": True,
            "can_reject": False,
            "blockers": [],
            "warnings": [],
            "coverage": {
                "required": {"covered_required": 0, "total_required": 0},
                "source_atoms": {},
                "blueprint": {},
            },
            "repair": {
                "attempt_count": 0,
                "latest_status": "none",
                "latest_attempt_path": "",
                "report_path": "",
                "index_path": "",
                "attempts": [],
            },
            "blueprint": {
                "status": "missing",
                "fidelity_status": "unknown",
                "refusal_reason": "",
                "ready": False,
                "artifact_path": str(files["builder_blueprint_report"]),
                "blueprint_path": str(files["builder_blueprint"]),
                "source_coverage": {
                    "location_candidates": 0,
                    "npc_candidates": 0,
                    "canonical_identities": 0,
                    "plot_beats": 0,
                    "puzzle_chains": 0,
                },
                "blueprint_coverage": {
                    "locations_in_blueprint": 0,
                    "npcs_in_blueprint": 0,
                },
                "warnings": [],
            },
            "artifacts": artifact_records,
            "signature": "",
            "blocker_signature": "",
        }

    missing_artifacts: List[str] = []
    malformed_artifacts: List[str] = []
    for key in _REQUIRED_ACCURATE_INGEST_KEYS:
        record = artifact_records.get(key, {})
        if not record.get("exists"):
            missing_artifacts.append(key)
        elif record.get("status") == "failed":
            malformed_artifacts.append(key)

    fidelity_report = payloads.get("normalization_fidelity_report") or {}
    normalization_report = payloads.get("normalization_report") or {}
    repair_report = payloads.get("normalization_repair_report") or {}
    repair_index = payloads.get("packet_repair_attempts_index") or {}
    blueprint = payloads.get("builder_blueprint") or {}
    blueprint_report = payloads.get("builder_blueprint_report") or {}
    source_graph = payloads.get("source_graph") or {}

    fidelity_summary = _summarize_fidelity_report(
        fidelity_report,
        artifact_path=str(files["normalization_fidelity_report"]),
    )
    repair_summary = _summarize_repair_attempts(workspace, repair_report, repair_index)
    blueprint_summary = _summarize_blueprint(workspace, blueprint, blueprint_report)
    source_atom_counts = _count_source_atoms(source_graph)

    coverage = {
        "required": {
            "covered_required": _safe_int(fidelity_summary.get("covered_required"), 0),
            "total_required": _safe_int(fidelity_summary.get("total_required"), 0),
        },
        "source_atoms": source_atom_counts,
        "blueprint": {
            **blueprint_summary.get("source_coverage", {}),
            **blueprint_summary.get("blueprint_coverage", {}),
        },
    }

    blockers = list(fidelity_summary.get("blockers") or [])
    warnings = list(fidelity_summary.get("warnings") or [])
    warnings.extend(blueprint_summary.get("warnings") or [])

    if missing_artifacts:
        status = "missing"
        refusal_reason = f"missing_artifacts: {', '.join(sorted(missing_artifacts))}"
        blockers = blockers or [
            {
                "severity": "blocking",
                "category": "artifact",
                "message": f"{artifact_name} is missing",
                "artifact_path": str(files[artifact_name]),
            }
            for artifact_name in sorted(missing_artifacts)
        ]
    elif malformed_artifacts:
        status = "failed"
        refusal_reason = f"malformed_artifacts: {', '.join(sorted(malformed_artifacts))}"
        blockers = blockers or [
            {
                "severity": "blocking",
                "category": "artifact",
                "message": f"{artifact_name} is malformed",
                "artifact_path": str(files[artifact_name]),
            }
            for artifact_name in sorted(malformed_artifacts)
        ]
    else:
        refusal_reason = str(blueprint_summary.get("refusal_reason") or fidelity_summary.get("reason") or "").strip()
        if fidelity_summary["status"] == "blocked":
            status = "blocked"
            if not refusal_reason:
                refusal_reason = "blocking_fidelity_findings"
        elif fidelity_summary["status"] == "failed":
            status = "failed"
            if not refusal_reason:
                refusal_reason = "failed_fidelity"
        elif fidelity_summary["status"] == "skipped":
            status = "missing"
            if not refusal_reason:
                refusal_reason = fidelity_report.get("reason") or "missing_source_artifacts"
        elif not blueprint_summary.get("ready"):
            status = "blocked"
            if not refusal_reason:
                refusal_reason = blueprint_summary.get("refusal_reason") or "blueprint_not_ready"
        elif fidelity_summary["status"] == "degraded" and repair_summary.get("attempt_count", 0) > 0:
            status = "repaired"
        elif fidelity_summary["status"] == "degraded":
            status = "degraded"
        else:
            status = "clean"

    payload: Dict[str, Any] = {
        "mode": "accurate_ingest",
        "status": status,
        "refusal_reason": refusal_reason,
        "blockers": blockers[:_MAX_FINDINGS],
        "warnings": warnings[:_MAX_FINDINGS],
        "coverage": coverage,
        "repair": repair_summary,
        "blueprint": blueprint_summary,
        "artifacts": artifact_records,
        "signature": _signature_for_artifacts(artifact_records, payloads),
    }
    payload["blocker_signature"] = _signature_for_blockers(payload)
    payload["can_approve"] = can_approve_fidelity_review(payload)[0]
    payload["can_reject"] = True
    return payload


def _signature_for_artifacts(
    artifact_records: Dict[str, Dict[str, Any]],
    payloads: Dict[str, Dict[str, Any]],
) -> str:
    signature_source = {
        "artifacts": {
            name: {
                "status": record.get("status"),
                "exists": record.get("exists"),
                "size_bytes": record.get("size_bytes"),
            }
            for name, record in sorted(artifact_records.items())
        },
        "status": {
            "fidelity": payloads.get("normalization_fidelity_report", {}).get("status"),
            "blueprint": payloads.get("builder_blueprint_report", {}).get("blueprint_status"),
            "repair": payloads.get("normalization_repair_report", {}).get("status"),
        },
    }
    return json.dumps(signature_source, sort_keys=True, ensure_ascii=True)


def _signature_for_blockers(payload: Dict[str, Any]) -> str:
    blocker_source = {
        "status": payload.get("status"),
        "refusal_reason": payload.get("refusal_reason"),
        "blockers": payload.get("blockers") or [],
        "blueprint_status": (payload.get("blueprint") or {}).get("status"),
    }
    return json.dumps(blocker_source, sort_keys=True, ensure_ascii=True)


def can_approve_fidelity_review(payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict) or not payload:
        return False, "fidelity_payload_missing"

    if str(payload.get("mode") or "").lower() == "legacy":
        return True, ""

    status = str(payload.get("status") or "unknown").lower()
    if status in {"missing", "failed", "blocked"}:
        return False, str(payload.get("refusal_reason") or f"fidelity_{status}")

    blockers = payload.get("blockers") or []
    if blockers:
        return False, str(payload.get("refusal_reason") or "blockers_present")

    blueprint = payload.get("blueprint") or {}
    if str(blueprint.get("status") or "").lower() != "ready":
        return False, str(blueprint.get("refusal_reason") or "blueprint_not_ready")

    return True, ""


__all__ = [
    "build_fidelity_review_payload",
    "can_approve_fidelity_review",
    "is_accurate_ingest_workspace",
]
