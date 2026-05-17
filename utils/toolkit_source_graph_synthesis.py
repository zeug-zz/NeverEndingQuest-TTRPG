# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Source Graph Synthesis
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Identity adjudication, plot topology synthesis, and packet synthesis
helpers for accurate-ingest multipass normalization.
"""

import hashlib
from typing import Any, Dict, List, Optional, Set

SYNTHESIS_REPORT_VERSION = "toolkit_source_synthesis.v1"
IDENTITY_RESOLUTION_VERSION = "toolkit_identity_resolution.v1"
_PLOT_TOPOLOGY_VERSION = "toolkit_plot_topology.v1"
_MAX_EXCERPT_CHARS = 200


# ---------------------------------------------------------------------------
#  Identity / alias adjudication
# ---------------------------------------------------------------------------

def build_identity_resolution_report(
    source_graph: Dict[str, Any],
    section_extractions: List[Dict[str, Any]],
    adjudication_model_output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an identity_resolution_report.json from mechanical graph atoms
    and section extraction facts.  Model‑supplied adjudication decisions
    are merged when present but never trusted over mechanical rules."""

    atoms = source_graph.get("atoms", [])
    canonical: Dict[str, Dict[str, Any]] = {}
    ambiguous: List[Dict[str, Any]] = []

    # Seed canonical identities from existing source graph atoms
    for a in atoms:
        aid = a.get("id", "")
        name = a.get("name", "")
        if not name and not aid:
            continue
        key = name.lower().strip() if name else aid
        if key not in canonical:
            canonical[key] = {
                "canonical_id": aid,
                "display_name": name or aid,
                "aliases": [],
                "entity_type": a.get("type", "unknown"),
                "criticality": a.get("criticality", "ambiguous"),
                "confidence": a.get("confidence", "medium"),
                "source_refs": a.get("source_refs", []),
                "adjudication": "mechanical_match",
            }

    # Merge section-extracted facts
    for sec in section_extractions:
        for fact in sec.get("extracted_atoms", []):
            fname = (fact.get("name") or fact.get("summary") or "").lower().strip()
            if not fname:
                continue
            if fname in canonical:
                # augment existing identity
                existing = canonical[fname]
                existing["source_refs"].extend(fact.get("source_refs", []))
                existing["source_refs"] = _dedupe_refs(existing["source_refs"])
                if (
                    fact.get("criticality") == "required"
                    and existing["criticality"] != "required"
                ):
                    existing["criticality"] = "required"
                    existing["adjudication"] = "promoted_by_evidence"
                continue

            canonical[fname] = {
                "canonical_id": fact.get("atom_id", ""),
                "display_name": fact.get("name", ""),
                "aliases": [],
                "entity_type": fact.get("type", "unknown"),
                "criticality": fact.get("criticality", "minor"),
                "confidence": fact.get("confidence", "low"),
                "source_refs": fact.get("source_refs", []),
                "adjudication": "section_fact_only",
            }

    # Model adjudication (aliases, merges, reclassifications)
    if adjudication_model_output:
        for decision in adjudication_model_output.get("decisions", []):
            _apply_adjudication_decision(canonical, ambiguous, decision)

    return {
        "identity_report_version": IDENTITY_RESOLUTION_VERSION,
        "canonical_identities": list(canonical.values()),
        "ambiguous_identities": ambiguous,
        "summary": {
            "total_canonical": len(canonical),
            "total_ambiguous": len(ambiguous),
        },
    }


def _decision_has_evidence(decision: Dict[str, Any]) -> bool:
    """Check whether an adjudication decision carries source evidence."""
    if decision.get("source_refs"):
        refs = decision["source_refs"]
        if isinstance(refs, list) and len(refs) > 0:
            return True
    if decision.get("evidence_refs"):
        refs = decision["evidence_refs"]
        if isinstance(refs, list) and len(refs) > 0:
            return True
    for field in ("evidence", "reason"):
        val = decision.get(field)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _apply_adjudication_decision(
    canonical: Dict[str, Dict[str, Any]],
    ambiguous: List[Dict[str, Any]],
    decision: Dict[str, Any],
) -> None:
    """Fold one model adjudication decision into canonical/ambiguous.

    Merge decisions require explicit source evidence.  Merges without
    evidence are recorded as ambiguous instead of being silently applied.
    """
    d_type = (decision.get("type") or "").lower()
    name_a = (decision.get("name_a") or "").lower().strip()
    name_b = (decision.get("name_b") or "").lower().strip()

    if d_type == "merge" and name_a and name_b:
        if not _decision_has_evidence(decision):
            decision_copy = dict(decision)
            decision_copy["reason"] = decision_copy.get("reason", "merge_missing_evidence")
            ambiguous.append(decision_copy)
            return
        a = canonical.get(name_a)
        b = canonical.get(name_b)
        if a and b:
            a["aliases"].append(b["display_name"])
            a["source_refs"].extend(b.get("source_refs", []))
            a["source_refs"] = _dedupe_refs(a["source_refs"])
            a["adjudication"] = "merged"
            if b["criticality"] == "required":
                a["criticality"] = "required"
            canonical.pop(name_b, None)
        elif a:
            a["aliases"].append(decision.get("name_b", ""))
            a["adjudication"] = "alias_added"
    elif d_type == "ambiguous" and name_a:
        ambiguous.append(dict(decision))
    elif d_type == "reclassify" and name_a:
        target = canonical.get(name_a)
        if target:
            new_type = decision.get("entity_type")
            if new_type:
                target["entity_type"] = new_type
            new_crit = decision.get("criticality")
            if new_crit:
                target["criticality"] = new_crit


# ---------------------------------------------------------------------------
#  Plot / puzzle / clue topology synthesis
# ---------------------------------------------------------------------------

def build_plot_topology_report(
    source_graph: Dict[str, Any],
    section_extractions: List[Dict[str, Any]],
    topology_model_output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build plot_topology_report.json from source graph atoms and section facts.

    Model-supplied topology is merged as advisory and never overrides
    mechanically detected source order.
    """

    report: Dict[str, Any] = {
        "topology_version": _PLOT_TOPOLOGY_VERSION,
        "plot_beats": [],
        "puzzle_chains": [],
        "clue_dependencies": [],
        "trials": [],
        "endings": [],
        "assumptions": [],
        "unresolved": [],
    }

    # Extract from model output first (if available), then layer mechanical hints
    if topology_model_output:
        for key in (
            "plot_beats",
            "puzzle_chains",
            "clue_dependencies",
            "trials",
            "endings",
        ):
            items = topology_model_output.get(key, [])
            if isinstance(items, list):
                report[key] = items
        report["assumptions"] = topology_model_output.get("assumptions", [])
        report["unresolved"] = topology_model_output.get("unresolved", [])

    # Ensure source order: sort plot beats by line_start from any attached refs
    for beat_list_key in ("plot_beats", "puzzle_chains", "trials"):
        beats = report.get(beat_list_key, [])
        if isinstance(beats, list):
            beats.sort(key=_beat_line_key)

    # Check for missing required atoms that weren't captured in topology
    atoms = source_graph.get("atoms", [])
    required_ids = {
        a["id"]
        for a in atoms
        if a.get("criticality") == "required" and a.get("type") in ("plot_beat", "puzzle", "clue", "location")
    }
    represented_ids: Set[str] = set()
    for beat_list_key in ("plot_beats", "puzzle_chains", "trials", "clue_dependencies"):
        for beat in report.get(beat_list_key, []):
            for ref in beat.get("source_refs", []):
                atom_id = ref.get("atom_id", "")
                if atom_id:
                    represented_ids.add(atom_id)

    missing = required_ids - represented_ids
    if missing:
        report["unresolved"].append(
            {
                "type": "missing_required_atoms",
                "missing_atom_ids": sorted(missing),
                "note": "Required source atoms not represented in synthesized topology.",
            }
        )

    return report


def _beat_line_key(beat: Dict[str, Any]) -> int:
    """Extract minimal line start from beat source refs for stable sorting."""
    best = 9999999
    for ref in beat.get("source_refs", []):
        try:
            ls = int(ref.get("line_start", 0) or 0)
            if 0 < ls < best:
                best = ls
        except Exception:
            pass
    return best


# ---------------------------------------------------------------------------
#  Packet synthesis from source graph + synthesis artifacts
# ---------------------------------------------------------------------------

def synthesize_normalized_packet(
    source_graph: Dict[str, Any],
    identity_report: Dict[str, Any],
    plot_topology: Dict[str, Any],
    legacy_model_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a review‑compatible normalized packet from source graph and
    synthesis reports.  Falls back to legacy model payload for fields that
    cannot be synthesized from mechanical evidence."""

    # Base from legacy payload when available
    packet: Dict[str, Any] = {
        "title": "",
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
        "assumptions": [],
        "warnings": [],
        "confidence_notes": {},
    }

    if legacy_model_payload:
        for key in set(packet) & set(legacy_model_payload):
            legacy_val = legacy_model_payload[key]
            if legacy_val is not None:
                packet[key] = legacy_val

    # Overlay source graph data
    identities = identity_report.get("canonical_identities", [])
    npc_ids = [i for i in identities if i.get("entity_type") in ("npc", "entity")]
    loc_ids = [i for i in identities if i.get("entity_type") == "location"]

    if not packet["npc_seeds"]:
        packet["npc_seeds"] = [
            {
                "name": i["display_name"],
                "role": i.get("entity_type", ""),
                "criticality": i.get("criticality", "minor"),
            }
            for i in npc_ids
            if i.get("criticality") in ("required", "major")
        ]

    if not packet["locations"]:
        packet["locations"] = [
            {
                "name": i["display_name"],
                "summary": i.get("display_name", ""),
                "criticality": i.get("criticality", "minor"),
            }
            for i in loc_ids
            if i.get("criticality") in ("required", "major")
        ]

    # Enrich confidence notes with source graph provenance (additive only)
    notes = packet.get("confidence_notes", {}) or {}
    notes["source_graph_atom_count"] = source_graph.get("summary", {}).get(
        "total_atoms", 0
    )
    notes["identity_count"] = identity_report.get("summary", {}).get(
        "total_canonical", 0
    )
    notes["plot_beats_count"] = len(
        plot_topology.get("plot_beats", [])
    )
    notes["puzzle_chains_count"] = len(
        plot_topology.get("puzzle_chains", [])
    )
    packet["confidence_notes"] = notes

    return packet


def build_source_graph_synthesis_report(
    source_graph: Dict[str, Any],
    section_extractions: List[Dict[str, Any]],
    identity_report: Dict[str, Any],
    plot_topology: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a source_graph_synthesis_report.json rollup."""

    section_statuses = [
        sec.get("status", "pending")
        for sec in section_extractions
    ]
    degraded_count = sum(1 for s in section_statuses if s == "degraded")
    success_count = sum(1 for s in section_statuses if s in ("success", "cached"))

    return {
        "synthesis_version": SYNTHESIS_REPORT_VERSION,
        "section_extraction": {
            "total_units": len(section_extractions),
            "degraded_units": degraded_count,
            "completed_units": success_count,
        },
        "identity": {
            "canonical_count": identity_report.get("summary", {}).get(
                "total_canonical", 0
            ),
            "ambiguous_count": identity_report.get("summary", {}).get(
                "total_ambiguous", 0
            ),
        },
        "plot_topology": {
            "plot_beats": len(plot_topology.get("plot_beats", [])),
            "puzzle_chains": len(plot_topology.get("puzzle_chains", [])),
            "trials": len(plot_topology.get("trials", [])),
            "assumptions": len(plot_topology.get("assumptions", [])),
            "unresolved": len(plot_topology.get("unresolved", [])),
        },
    }


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _dedupe_refs(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """De-duplicate source reference list by content identity."""
    merged: List[Dict[str, Any]] = []
    seen: Set[tuple] = set()
    for ref in refs:
        key = (
            ref.get("source_path", ""),
            ref.get("section", ""),
            ref.get("line_start", 0),
            ref.get("line_end", 0),
            str(ref.get("excerpt", ""))[:_MAX_EXCERPT_CHARS],
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
    return merged
