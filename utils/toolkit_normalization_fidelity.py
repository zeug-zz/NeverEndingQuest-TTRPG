# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Normalization Fidelity Verifier and Repair Loop
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Phase 3 of the accurate-ingest pipeline.  Compares source graph, identity,
and topology artifacts against the normalized packet, produces a fidelity
audit report, and optionally runs bounded repair attempts that patch only
the packet with source-backed evidence.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

FIDELITY_REPORT_VERSION = "normalization_fidelity.v1"
REPAIR_REPORT_VERSION = "normalization_repair.v1"
REPAIR_PATCH_VERSION = "normalization_packet_repair.v1"

# Maximum repair attempts before giving up
DEFAULT_MAX_REPAIR_ATTEMPTS = 3

# Allowed additive repair operations in this slice
_ALLOWED_REPAIR_OPS = frozenset(
    {
        "add_location",
        "add_npc_seed",
        "add_monster_ref",
        "add_plot_progression",
        "add_warning",
        "add_confidence_note",
        "add_connectivity_hint",
        "add_assumption",
    }
)

# ---- Finding model ----

_CATEGORIES = frozenset({"missing", "distorted", "unsupported", "ambiguous", "covered"})
_SEVERITIES = frozenset({"blocking", "warning", "info"})


def _stable_finding_id(category: str, source_atom_id: str, packet_path: str) -> str:
    raw = f"{category}:{source_atom_id}:{packet_path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_finding(
    category: str,
    severity: str,
    source_atom_id: str = "",
    packet_path: str = "",
    expected: str = "",
    actual: str = "",
    source_refs: Optional[List[Dict[str, Any]]] = None,
    repairable: bool = False,
    evidence_basis: str = "deterministic",
    detail: str = "",
) -> Dict[str, Any]:
    """Build a single fidelity audit finding record."""
    return {
        "finding_id": _stable_finding_id(category, source_atom_id, packet_path),
        "source_atom_id": source_atom_id,
        "category": category if category in _CATEGORIES else "ambiguous",
        "severity": severity if severity in _SEVERITIES else "warning",
        "repairable": repairable,
        "packet_path": packet_path,
        "expected": expected,
        "actual": actual,
        "source_refs": source_refs or [],
        "evidence_basis": evidence_basis,
        "detail": detail,
    }


# ---- Packet indexing ----

def _build_packet_index(packet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build deterministic coverage indexes from the normalized packet."""
    index: Dict[str, Dict[str, Any]] = {}

    # Locations
    for loc in packet.get("locations", []):
        if isinstance(loc, dict):
            name = (loc.get("name") or "").lower().strip()
            if name:
                index[f"loc:{name}"] = loc

    # NPCs
    for npc in packet.get("npc_seeds", []):
        if isinstance(npc, dict):
            name = (npc.get("name") or "").lower().strip()
            if name:
                index[f"npc:{name}"] = npc

    # Monster refs
    for mref in packet.get("monster_refs", []):
        name = (str(mref) if not isinstance(mref, dict) else mref.get("name", "")).lower().strip()
        if name:
            index[f"monster:{name}"] = mref if isinstance(mref, dict) else {"name": mref}

    # Plot progression
    for beat in packet.get("plot_progression", []):
        if isinstance(beat, dict):
            title = (beat.get("title") or beat.get("name") or "").lower().strip()
            if title:
                index[f"plot:{title}"] = beat

    # Connectivity hints
    for hint in packet.get("connectivity_hints", []):
        if isinstance(hint, dict):
            src = (hint.get("from") or "").lower().strip()
            dst = (hint.get("to") or "").lower().strip()
            if src and dst:
                index[f"conn:{src}->{dst}"] = hint

    # Warnings
    for warn in packet.get("warnings", []):
        msg = ""
        if isinstance(warn, dict):
            msg = (warn.get("message") or warn.get("type") or "").lower().strip()
        elif isinstance(warn, str):
            msg = warn.lower().strip()
        if msg:
            index[f"warn:{msg[:60]}"] = warn if isinstance(warn, dict) else {"message": warn}

    return index


# ---- Fidelity audit logic ----

def _get_source_atoms(source_graph: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not source_graph:
        return []
    return source_graph.get("atoms", [])


def run_normalization_fidelity_audit(
    source_graph: Optional[Dict[str, Any]] = None,
    identity_report: Optional[Dict[str, Any]] = None,
    plot_topology: Optional[Dict[str, Any]] = None,
    normalized_packet: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare source-backed artifacts against the normalized packet.

    Returns a normalization_fidelity_report.json-compatible dict with
    findings, coverage counts, status, and summary fields.
    """
    findings: List[Dict[str, Any]] = []

    # Degrade safely when source artifacts are missing
    if not source_graph:
        return {
            "fidelity_report_version": FIDELITY_REPORT_VERSION,
            "status": "skipped",
            "reason": "missing_source_artifacts",
            "findings": findings,
            "summary": {
                "status": "skipped",
                "blocking_count": 0,
                "warning_count": 0,
                "info_count": 0,
                "covered_required": 0,
                "total_required": 0,
            },
        }

    if not normalized_packet:
        return {
            "fidelity_report_version": FIDELITY_REPORT_VERSION,
            "status": "failed",
            "reason": "missing_packet",
            "findings": findings,
            "summary": {
                "status": "failed",
                "blocking_count": 0,
                "warning_count": 0,
                "info_count": 0,
                "covered_required": 0,
                "total_required": 0,
            },
        }

    packet_index = _build_packet_index(normalized_packet)
    atoms = _get_source_atoms(source_graph)

    # Canonical identities from identity report (if available)
    identity_map: Dict[str, str] = {}
    if identity_report:
        for ident in identity_report.get("canonical_identities", []):
            if isinstance(ident, dict):
                name = (ident.get("display_name") or "").lower().strip()
                aliases = ident.get("aliases", [])
                if name:
                    identity_map[name] = name
                    for alias in aliases:
                        identity_map[str(alias).lower().strip()] = name

    # Check required/major atoms
    required_atoms = [
        a for a in atoms
        if a.get("criticality") in ("required", "major")
        and a.get("type") in ("npc", "location", "plot_beat", "puzzle", "clue", "monster")
    ]
    covered_required = 0

    for atom in required_atoms:
        atype = atom.get("type", "")
        name = (atom.get("name") or "").lower().strip()
        atom_id = atom.get("id", "")

        lookup_names = {name}
        if name in identity_map:
            lookup_names.add(identity_map[name])
        # also check aliases of any matching identity
        if identity_report:
            for ident in identity_report.get("canonical_identities", []):
                if isinstance(ident, dict) and (ident.get("display_name") or "").lower().strip() == name:
                    for alias in ident.get("aliases", []):
                        lookup_names.add(str(alias).lower().strip())

        covered = False
        for ln in lookup_names:
            if not ln:
                continue
            if atype in ("npc", "location"):
                if f"npc:{ln}" in packet_index or f"loc:{ln}" in packet_index:
                    covered = True
                    break
            elif atype == "monster":
                if f"monster:{ln}" in packet_index:
                    covered = True
                    break
            elif atype in ("plot_beat", "puzzle", "clue"):
                if f"plot:{ln}" in packet_index:
                    covered = True
                    break

        if covered:
            covered_required += 1
        else:
            repairable = atype in ("npc", "location", "monster", "plot_beat")
            findings.append(
                make_finding(
                    category="missing",
                    severity="blocking" if atom.get("criticality") == "required" else "warning",
                    source_atom_id=atom_id,
                    packet_path=f"{atype}s" if atype != "plot_beat" else "plot_progression",
                    expected=name,
                    actual="",
                    source_refs=atom.get("source_refs", []),
                    repairable=repairable,
                    detail=f"Required {atype} source atom not found in normalized packet.",
                )
            )

    # Check topology coverage (puzzle chains, clue dependencies)
    if plot_topology:
        for beat in plot_topology.get("plot_beats", []):
            if not isinstance(beat, dict):
                continue
            bname = (beat.get("label") or beat.get("title") or "").lower().strip()
            if not bname or f"plot:{bname}" in packet_index:
                continue
            findings.append(
                make_finding(
                    category="missing",
                    severity="warning",
                    packet_path="plot_progression",
                    expected=bname,
                    actual="",
                    repairable=True,
                    detail="Topology plot beat not represented in packet.",
                )
            )

    # Check for unsupported additions (invented names not in source graph)
    source_npc_names: Set[str] = set()
    source_loc_names: Set[str] = set()
    source_monster_names: Set[str] = set()
    for a in atoms:
        aname = (a.get("name") or "").lower().strip()
        atype = a.get("type", "")
        if atype == "npc":
            source_npc_names.add(aname)
        elif atype == "location":
            source_loc_names.add(aname)
        elif atype == "monster":
            source_monster_names.add(aname)
        # also add identity aliases
        if identity_report and aname in identity_map:
            source_npc_names.add(aname)

    for npc in normalized_packet.get("npc_seeds", []):
        pname = (npc.get("name") if isinstance(npc, dict) else str(npc)).lower().strip()
        if pname and pname not in source_npc_names:
            findings.append(
                make_finding(
                    category="unsupported",
                    severity="warning",
                    source_atom_id="",
                    packet_path="npc_seeds",
                    expected="",
                    actual=pname,
                    repairable=False,
                    detail="NPC in packet not sourced from source graph.",
                )
            )

    for loc in normalized_packet.get("locations", []):
        lname = (loc.get("name") if isinstance(loc, dict) else str(loc)).lower().strip()
        if lname and lname not in source_loc_names:
            findings.append(
                make_finding(
                    category="unsupported",
                    severity="warning" if source_loc_names else "blocking",
                    source_atom_id="",
                    packet_path="locations",
                    expected="",
                    actual=lname,
                    repairable=False,
                    detail="Location in packet not sourced from source graph.",
                )
            )

    blocking = [f for f in findings if f["severity"] == "blocking"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]

    if blocking:
        status = "blocked"
    elif warnings:
        status = "degraded"
    else:
        status = "clean"

    return {
        "fidelity_report_version": FIDELITY_REPORT_VERSION,
        "status": status,
        "findings": findings,
        "summary": {
            "status": status,
            "blocking_count": len(blocking),
            "warning_count": len(warnings),
            "info_count": len(infos),
            "covered_required": covered_required,
            "total_required": len(required_atoms),
        },
    }


# ---- Repair patch model ----

def validate_repair_operations(
    operations: List[Dict[str, Any]],
    fidelity_findings: List[Dict[str, Any]],
    source_graph: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate repair patch operations against source evidence.

    Returns (accepted_ops, rejected_ops).  Each rejected op includes a
    reason string.
    """
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    repairable_ids = {
        f["source_atom_id"] for f in fidelity_findings if f.get("repairable")
    }

    for op in operations:
        if not isinstance(op, dict):
            rejected.append({"operation": op, "reason": "not_a_dict"})
            continue

        op_type = (op.get("op") or "").lower()
        if op_type not in _ALLOWED_REPAIR_OPS:
            rejected.append({"operation": op, "reason": f"unsupported_or_destructive_op: {op_type}"})
            continue

        # All operations must carry source evidence
        source_atom_id = (op.get("source_atom_id") or "").strip()
        source_refs = op.get("source_refs")
        has_refs = isinstance(source_refs, list) and len(source_refs) > 0

        if not source_atom_id and not has_refs:
            rejected.append({"operation": op, "reason": "missing_source_evidence"})
            continue

        # If source_atom_id is provided, it should correspond to a repairable finding
        if source_atom_id and source_atom_id not in repairable_ids:
            rejected.append({"operation": op, "reason": f"source_atom_id_not_repairable: {source_atom_id}"})
            continue

        accepted.append(op)

    return accepted, rejected


def apply_repair_operations(
    packet: Dict[str, Any],
    operations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply accepted repair operations to a packet copy.

    Returns a new packet dict; does not mutate the input.
    """
    repaired = dict(packet)

    target_map: Dict[str, str] = {
        "add_location": "locations",
        "add_npc_seed": "npc_seeds",
        "add_monster_ref": "monster_refs",
        "add_plot_progression": "plot_progression",
        "add_warning": "warnings",
        "add_confidence_note": "confidence_notes",
        "add_connectivity_hint": "connectivity_hints",
        "add_assumption": "assumptions",
    }

    for op in operations:
        op_type = (op.get("op") or "").lower()
        target_key = target_map.get(op_type)
        if not target_key:
            continue
        value = op.get("value")
        if value is None:
            continue
        if target_key == "confidence_notes":
            existing = repaired.get(target_key, {})
            if not isinstance(existing, dict):
                existing = {}
            # Merge additive keys
            if isinstance(value, dict):
                for k, v in value.items():
                    existing.setdefault(k, v)
            repaired[target_key] = existing
        else:
            arr = list(repaired.get(target_key, []))
            arr.append(value)
            repaired[target_key] = arr

    return repaired


def build_repair_attempt_artifact(
    attempt: int,
    repair_prompt: str,
    model_output: str,
    proposed_ops: List[Dict[str, Any]],
    accepted_ops: List[Dict[str, Any]],
    rejected_ops: List[Dict[str, Any]],
    applied: bool,
    status: str,
    reason: str = "",
) -> Dict[str, Any]:
    """Build a packet_repair_attempts/attempt_<n>.json record."""
    return {
        "repair_attempt_version": REPAIR_REPORT_VERSION,
        "attempt": attempt,
        "repair_prompt": repair_prompt[:2000],
        "model_output_preview": model_output[:2000],
        "proposed_operations_count": len(proposed_ops),
        "accepted_operations": accepted_ops,
        "rejected_operations": rejected_ops,
        "applied": applied,
        "status": status,
        "reason": reason,
    }


def build_fidelity_summary_for_report(audit_report: Dict[str, Any]) -> Dict[str, Any]:
    """Build compact fidelity status fields for normalization_report.json."""
    summary = audit_report.get("summary", {})
    return {
        "fidelity_status": summary.get("status", "unknown"),
        "fidelity_blocking_count": summary.get("blocking_count", 0),
        "fidelity_warning_count": summary.get("warning_count", 0),
        "fidelity_covered_required": summary.get("covered_required", 0),
        "fidelity_total_required": summary.get("total_required", 0),
    }
