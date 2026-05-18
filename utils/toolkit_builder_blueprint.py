# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Builder Blueprint
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Phase 4 of the accurate-ingest pipeline.  Consumes Phase 2-3 artifacts
(source graph, identity, topology, packet, fidelity) and produces a
source-locked builder blueprint and narrative for the packet builder handoff.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

BUILDER_BLUEPRINT_VERSION = "source_faithful_builder_blueprint.v1"
BUILDER_BLUEPRINT_V2_VERSION = "source_faithful_builder_blueprint.v2"
BUILDER_HANDOFF_MODE_SOURCE_BLUEPRINT = "source_blueprint"
BUILDER_HANDOFF_MODE_LEGACY = "legacy"
_LOADED_ATTR_MARKER = "_blueprint_loader_used"

# Blueprint refusal and status constants
STATUS_READY = "ready"
STATUS_BLOCKED_BY_FIDELITY = "blocked_by_fidelity"
STATUS_MISSING_ARTIFACTS = "missing_artifacts"
STATUS_INVALID_PACKET = "invalid_packet"
STATUS_GENERATION_FAILED = "generation_failed"
STATUS_SKIPPED = "skipped"

# Source lock defaults
_SOURCE_LOCK_DEFAULTS = {
    "canonical_names_locked": True,
    "required_atom_omission_blocks_build": True,
    "invented_major_entities_forbidden": True,
    "replacement_plotlines_forbidden": True,
    "puzzle_rule_rewrite_forbidden": True,
}

_MAX_EXCERPT_CHARS = 200


# ---------------------------------------------------------------------------
# Artifact loaders
# ---------------------------------------------------------------------------

def load_artifact_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON artifact file.  Returns None for missing or unreadable files."""
    try:
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def load_phase2_artifacts(files: Dict[str, Path]) -> Dict[str, Any]:
    """Load all Phase 2-3 artifacts from a workspace files dict.

    Returns a dict with key names: source_graph, identity_resolution_report,
    plot_topology_report, source_graph_synthesis_report, normalized_packet,
    normalization_fidelity_report, normalization_report.
    Missing/unreadable artifacts return None for that key.
    """
    return {
        "source_graph": load_artifact_json(files.get("source_graph")),
        "identity_resolution_report": load_artifact_json(files.get("identity_resolution_report")),
        "plot_topology_report": load_artifact_json(files.get("plot_topology_report")),
        "source_graph_synthesis_report": load_artifact_json(files.get("source_graph_synthesis_report")),
        "normalized_packet": load_artifact_json(files.get("normalized_packet")),
        "normalization_fidelity_report": load_artifact_json(files.get("normalization_fidelity_report")),
        "normalization_report": load_artifact_json(files.get("normalization_report")),
    }


# ---------------------------------------------------------------------------
# Fidelity precheck
# ---------------------------------------------------------------------------

def _read_fidelity_status(
    fidelity_report: Optional[Dict[str, Any]],
    normalization_report: Optional[Dict[str, Any]],
) -> str:
    """Read final fidelity status from fidelity report or normalizer rollups."""
    if fidelity_report:
        status = fidelity_report.get("status", "")
        if status:
            return str(status).lower()
    if normalization_report:
        status = normalization_report.get("fidelity", {}).get("status", "")
        if status:
            return str(status).lower()
    return "unknown"


def _read_fidelity_findings(
    fidelity_report: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Read fidelity findings list, filtering for only blocking repairable ones."""
    if not fidelity_report:
        return []
    findings = fidelity_report.get("findings") or []
    return [f for f in findings if isinstance(f, dict)]


def _has_blocking_required_findings(findings: List[Dict[str, Any]]) -> bool:
    """Check if any blocking finding relates to a required source atom."""
    for f in findings:
        if f.get("severity") == "blocking":
            return True
    return False


def evaluate_blueprint_fidelity_precheck(
    source_graph: Optional[Dict[str, Any]],
    normalized_packet: Optional[Dict[str, Any]],
    fidelity_report: Optional[Dict[str, Any]],
    normalization_report: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate whether blueprint generation is allowed based on fidelity status.

    Returns:
        A dict::
            {
              "precheck_status": "allowed|refused|skipped",
              "refusal_reason": "...",
              "fidelity_status": "...",
              "blocking_findings": [...],
            }
    """
    fidelity_status = _read_fidelity_status(fidelity_report, normalization_report)
    findings = _read_fidelity_findings(fidelity_report)

    # Missing required source artifacts
    if source_graph is None:
        return {
            "precheck_status": "refused",
            "refusal_reason": STATUS_MISSING_ARTIFACTS,
            "fidelity_status": fidelity_status,
            "blocking_findings": findings,
            "detail": "source_graph is required for blueprint generation",
        }
    if normalized_packet is None:
        return {
            "precheck_status": "refused",
            "refusal_reason": STATUS_MISSING_ARTIFACTS,
            "fidelity_status": fidelity_status,
            "blocking_findings": findings,
            "detail": "normalized_packet is required for blueprint generation",
        }

    # Blocked or failed fidelity
    if fidelity_status in ("blocked", "failed"):
        return {
            "precheck_status": "refused",
            "refusal_reason": STATUS_BLOCKED_BY_FIDELITY,
            "fidelity_status": fidelity_status,
            "blocking_findings": findings,
            "detail": f"Fidelity status '{fidelity_status}' prevents blueprint generation",
        }

    # Degraded with blocking findings
    if fidelity_status == "degraded" and _has_blocking_required_findings(findings):
        return {
            "precheck_status": "refused",
            "refusal_reason": STATUS_BLOCKED_BY_FIDELITY,
            "fidelity_status": fidelity_status,
            "blocking_findings": findings,
            "detail": "Degraded fidelity with pending blocking findings prevents blueprint generation",
        }

    # Allowed: clean, repaired, or degraded without blockers
    return {
        "precheck_status": "allowed",
        "refusal_reason": "",
        "fidelity_status": fidelity_status,
        "blocking_findings": findings,
        "detail": "Fidelity precheck passed",
    }


# ---------------------------------------------------------------------------
# Blueprint report builder
# ---------------------------------------------------------------------------

def build_builder_blueprint_report(
    blueprint_status: str,
    artifacts: Dict[str, Any],
    precheck_result: Dict[str, Any],
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build ``builder_blueprint_report.json`` with compact status and coverage.

    The report is always workspace-local and reviewable.  It records input
    artifact availability, fidelity status, blueprint status, refusal reasons,
    coverage counts, and warnings.
    """
    from datetime import datetime, timezone

    source_graph = artifacts.get("source_graph")
    identity_report = artifacts.get("identity_resolution_report")
    topology_report = artifacts.get("plot_topology_report")

    # Compute coverage counts from source_graph
    atoms = source_graph.get("atoms", []) if source_graph else []
    location_candidates = [a for a in atoms if a.get("type") == "location"]
    npc_candidates = [a for a in atoms if a.get("type") == "npc"]

    identity_count = 0
    if identity_report:
        identity_count = len(identity_report.get("canonical_identities") or [])

    plot_beat_count = 0
    puzzle_count = 0
    if topology_report:
        plot_beat_count = len(topology_report.get("plot_beats") or [])
        puzzle_count = len(topology_report.get("puzzle_chains") or [])

    # Blueprint coverage counts
    blueprint_location_count = 0
    blueprint_npc_count = 0
    if blueprint and blueprint_status == STATUS_READY:
        blueprint_location_count = len(blueprint.get("location_roster") or [])
        blueprint_npc_count = len(blueprint.get("npc_roster") or [])

    return {
        "blueprint_report_version": "builder_blueprint_report.v1",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "blueprint_status": blueprint_status,
        "fidelity_status": precheck_result.get("fidelity_status", "unknown"),
        "refusal_reason": precheck_result.get("refusal_reason", ""),
        "input_artifacts": {
            "source_graph_present": source_graph is not None,
            "identity_resolution_present": identity_report is not None,
            "plot_topology_present": topology_report is not None,
            "normalized_packet_present": artifacts.get("normalized_packet") is not None,
            "normalization_fidelity_present": artifacts.get("normalization_fidelity_report") is not None,
            "normalization_report_present": artifacts.get("normalization_report") is not None,
        },
        "source_coverage": {
            "location_candidates": len(location_candidates),
            "npc_candidates": len(npc_candidates),
            "canonical_identities": identity_count,
            "plot_beats": plot_beat_count,
            "puzzle_chains": puzzle_count,
        },
        "blueprint_coverage": {
            "locations_in_blueprint": blueprint_location_count,
            "npcs_in_blueprint": blueprint_npc_count,
        },
        "warnings": _gather_warnings(artifacts),
    }


def _gather_warnings(artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collect warnings from fidelity and normalization reports."""
    warnings: List[Dict[str, Any]] = []

    # Fidelity findings that are not blocking
    fidelity_report = artifacts.get("normalization_fidelity_report")
    if fidelity_report:
        for f in fidelity_report.get("findings") or []:
            if isinstance(f, dict) and f.get("severity") in ("warning", "info"):
                warnings.append({
                    "source": "fidelity_audit",
                    "finding_id": f.get("finding_id", ""),
                    "message": f.get("detail", "") or f"{f.get('category', '')}: expected={f.get('expected', '')} actual={f.get('actual', '')}",
                })

    # Unsupported additions from fidelity report
    if fidelity_report:
        for f in fidelity_report.get("findings") or []:
            if isinstance(f, dict) and f.get("category") == "unsupported":
                warnings.append({
                    "source": "unsupported_addition",
                    "finding_id": f.get("finding_id", ""),
                    "message": f.get("detail", "") or f"Unsupported: {f.get('expected', '')}",
                })

    return warnings


# ---------------------------------------------------------------------------
# Blueprint generation
# ---------------------------------------------------------------------------

def generate_builder_blueprint(
    source_graph: Dict[str, Any],
    identity_report: Optional[Dict[str, Any]],
    plot_topology: Optional[Dict[str, Any]],
    synthesis_report: Optional[Dict[str, Any]],
    normalized_packet: Dict[str, Any],
    fidelity_report: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generate ``builder_blueprint.json`` from Phase 2-3 artifacts.

    The blueprint is a source-backed construction plan for the builder.
    It preserves source atom IDs, original display names, aliases, criticality,
    source refs, and carries unsupported findings into warnings/forbidden replacements.
    """
    from datetime import datetime, timezone
    import hashlib

    atoms = source_graph.get("atoms", [])

    # Derive module identity
    packet_title = str(normalized_packet.get("title") or "Unknown Module").strip()
    packet_summary = str(normalized_packet.get("adventure_summary") or normalized_packet.get("description") or "").strip()

    tone_markers = _extract_tone_markers(atoms)
    unsupported_inventions = _collect_unsupported_findings(fidelity_report)

    # Build rosters
    location_roster = _build_location_roster(atoms, identity_report)
    npc_roster = _build_npc_roster(atoms, identity_report)
    area_plan = _build_area_plan(location_roster, atoms)
    plot_graph = _build_plot_graph(plot_topology)
    puzzle_graph = _build_puzzle_graph(plot_topology)
    clue_graph = _build_clue_graph(plot_topology)
    encounter_plan = _build_encounter_plan(atoms)
    item_roster = _build_item_roster(atoms)
    tone_requirements = _build_tone_requirements(tone_markers)

    # Source refs
    source_refs = []
    for a in atoms:
        refs = a.get("source_refs") or []
        if refs:
            source_refs.append({
                "atom_id": a.get("id", ""),
                "name": a.get("name", ""),
                "type": a.get("type", "unknown"),
                "refs": refs,
            })

    source_hash = str(normalized_packet.get("source_hash") or "")
    packet_hash = hashlib.sha256(json.dumps(normalized_packet, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()[:16]

    return {
        "blueprint_version": BUILDER_BLUEPRINT_VERSION,
        "source_hash": source_hash,
        "normalized_packet_hash": packet_hash,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "fidelity_status": _read_fidelity_status(fidelity_report, None),
        "blueprint_status": STATUS_READY,
        "module": {
            "title": packet_title,
            "summary": packet_summary,
            "tone_profile": {
                "markers": tone_markers,
                "unsupported_inventions": unsupported_inventions,
            },
        },
        "source_lock": dict(_SOURCE_LOCK_DEFAULTS),
        "area_plan": area_plan,
        "location_roster": location_roster,
        "npc_roster": npc_roster,
        "plot_graph": plot_graph,
        "puzzle_graph": puzzle_graph,
        "clue_graph": clue_graph,
        "encounter_plan": encounter_plan,
        "item_roster": item_roster,
        "tone_requirements": tone_requirements,
        "source_refs": source_refs[:50],
        "warnings": _gather_warnings({
            "normalization_fidelity_report": fidelity_report,
            "normalization_report": None,
        }),
    }


def _extract_tone_markers(atoms: List[Dict[str, Any]]) -> List[str]:
    """Extract tone marker names from source atoms."""
    markers = []
    for a in atoms:
        if a.get("type") == "tone_marker":
            name = a.get("name", "").strip()
            if name:
                markers.append(name)
    return markers


def _collect_unsupported_findings(
    fidelity_report: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collect unsupported-addition findings from fidelity report for forbidden replacements."""
    if not fidelity_report:
        return []
    result = []
    for f in fidelity_report.get("findings") or []:
        if isinstance(f, dict) and f.get("category") == "unsupported":
            result.append({
                "finding_id": f.get("finding_id", ""),
                "detail": f.get("detail", "") or f.get("expected", ""),
            })
    return result


def _build_location_roster(
    atoms: List[Dict[str, Any]],
    identity_report: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build location roster from source atoms and identity aliases."""
    alias_map = _build_alias_map(identity_report)
    roster = []
    seen = set()

    for a in atoms:
        if a.get("type") != "location":
            continue
        loc_id = a.get("id", "")
        name = a.get("name", "")
        key = name.lower().strip() if name else loc_id
        if key in seen:
            continue
        seen.add(key)

        entry = {
            "atom_id": loc_id,
            "display_name": name,
            "aliases": list(alias_map.get(name.lower(), set())),
            "source_section": a.get("source_section", ""),
            "criticality": a.get("criticality", "ambiguous"),
            "parent_area": a.get("parent_area", ""),
            "source_refs": a.get("source_refs", []),
        }
        roster.append(entry)

    return roster


def _build_npc_roster(
    atoms: List[Dict[str, Any]],
    identity_report: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build NPC roster from source atoms and identity adjudication."""
    alias_map = _build_alias_map(identity_report)
    roster = []
    seen: set = set()

    for a in atoms:
        if a.get("type") != "npc":
            continue
        npc_id = a.get("id", "")
        name = a.get("name", "")
        key = name.lower().strip() if name else npc_id
        if key in seen:
            continue
        seen.add(key)

        # Look for additional data in identity report
        role = ""
        faction = ""
        location_binding = ""
        scene_presence = "present"

        from_identity = _find_identity(identity_report, name, npc_id)
        if from_identity is not None:
            entity_type = from_identity.get("entity_type", "")
            if entity_type:
                role = entity_type

        entry = {
            "atom_id": npc_id,
            "display_name": name,
            "aliases": list(alias_map.get(name.lower(), set())),
            "role": role,
            "faction": faction,
            "location_binding": location_binding,
            "scene_presence": scene_presence,
            "criticality": a.get("criticality", "ambiguous"),
            "source_refs": a.get("source_refs", []),
        }
        roster.append(entry)

    return roster


def _build_alias_map(identity_report: Optional[Dict[str, Any]]) -> Dict[str, set]:
    """Build a case-insensitive alias map from identity report."""
    alias_map: Dict[str, set] = {}
    if not identity_report:
        return alias_map
    for ident in identity_report.get("canonical_identities") or []:
        display = str(ident.get("display_name") or "").lower().strip()
        if not display:
            continue
        if display not in alias_map:
            alias_map[display] = set()
        for alias in ident.get("aliases") or []:
            if isinstance(alias, str):
                alias_map[display].add(alias)
            elif isinstance(alias, dict):
                a_name = str(alias.get("name") or "").strip()
                if a_name:
                    alias_map[display].add(a_name)
    return alias_map


def _find_identity(
    identity_report: Optional[Dict[str, Any]],
    name: str,
    atom_id: str,
) -> Optional[Dict[str, Any]]:
    """Find a canonical identity by display name or atom_id."""
    if not identity_report:
        return None
    name_lower = name.lower().strip()
    for ident in identity_report.get("canonical_identities") or []:
        if ident.get("canonical_id") == atom_id:
            return ident
        if ident.get("display_name", "").lower().strip() == name_lower:
            return ident
    return None


def _build_area_plan(
    location_roster: List[Dict[str, Any]],
    atoms: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Group locations into area planning hints."""
    area_map: Dict[str, Dict[str, Any]] = {}
    for loc in location_roster:
        parent = loc.get("parent_area", "") or "default_area"
        if parent not in area_map:
            area_map[parent] = {
                "area_name": parent,
                "source_locations": [],
            }
        area_map[parent]["source_locations"].append({
            "atom_id": loc["atom_id"],
            "display_name": loc["display_name"],
        })
    return list(area_map.values())


def _build_plot_graph(
    plot_topology: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build plot graph entries from plot topology report."""
    if not plot_topology:
        return []
    beats = plot_topology.get("plot_beats") or []
    result = []
    for b in beats:
        if isinstance(b, dict):
            result.append({
                "beat_id": b.get("beat_id", b.get("id", "")),
                "title": b.get("title", ""),
                "trigger": b.get("trigger", ""),
                "dependencies": b.get("dependencies", b.get("depends_on", [])),
                "required_location": b.get("required_location", ""),
                "required_npc": b.get("required_npc", ""),
                "outcome": b.get("outcome", ""),
                "failure_state": b.get("failure_state", ""),
                "beat_type": b.get("beat_type", b.get("classification", "mainline")),
            })
    return result


def _build_puzzle_graph(
    plot_topology: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build puzzle graph entries from plot topology report."""
    if not plot_topology:
        return []
    chains = plot_topology.get("puzzle_chains") or []
    result = []
    for chain in chains:
        if isinstance(chain, dict):
            result.append({
                "chain_id": chain.get("chain_id", chain.get("id", "")),
                "title": chain.get("title", ""),
                "setup": chain.get("setup", ""),
                "player_prompt": chain.get("player_prompt", ""),
                "rules": chain.get("rules", ""),
                "solution": chain.get("solution", ""),
                "failure_consequences": chain.get("failure_consequences", ""),
                "unlocks": chain.get("unlocks", ""),
                "clue_dependencies": chain.get("clue_dependencies", []),
            })
    return result


def _build_clue_graph(
    plot_topology: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build clue graph entries from plot topology report."""
    if not plot_topology:
        return []
    clues = plot_topology.get("clues") or plot_topology.get("clue_dependencies") or []
    result = []
    for c in clues:
        if isinstance(c, dict):
            result.append({
                "clue_id": c.get("clue_id", c.get("id", "")),
                "description": c.get("description", ""),
                "location": c.get("location", ""),
                "reveals": c.get("reveals", ""),
                "mandatory": c.get("mandatory", False),
                "supports_beat": c.get("supports_beat", ""),
            })
        elif isinstance(c, str):
            result.append({
                "clue_id": "",
                "description": c,
            })
    return result


def _build_encounter_plan(atoms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build encounter plan from source atoms."""
    plan = []
    for a in atoms:
        if a.get("type") != "encounter":
            continue
        plan.append({
            "atom_id": a.get("id", ""),
            "name": a.get("name", ""),
            "location": a.get("location", ""),
            "purpose": a.get("summary", ""),
            "monster_names": _find_monster_names_for_encounter(a),
            "avoidable": a.get("avoidable", False),
            "social": a.get("social", False),
            "source_refs": a.get("source_refs", []),
        })
    return plan


def _find_monster_names_for_encounter(atom: Dict[str, Any]) -> List[str]:
    """Extract monster/creature name hints from encounter atom."""
    monsters = atom.get("monster_names") or atom.get("creatures") or []
    if isinstance(monsters, list):
        return [str(m) for m in monsters if m]
    return []


def _build_item_roster(atoms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build item roster from source atoms."""
    roster = []
    for a in atoms:
        if a.get("type") != "item":
            continue
        roster.append({
            "atom_id": a.get("id", ""),
            "display_name": a.get("name", ""),
            "location": a.get("location", ""),
            "required": a.get("required", False),
        })
    return roster


def _build_tone_requirements(markers: List[str]) -> List[str]:
    """Build tone requirement guidance strings from markers."""
    if not markers:
        return ["Preserve source tone where available"]
    return [f"Tone marker: {m}" for m in markers]


# ---------------------------------------------------------------------------
# Blueprint v2 generation
# ---------------------------------------------------------------------------

_ENRICHMENT_ALLOWLIST_DEFAULT = {
    "npc_description": {
        "field": "description",
        "target_paths": ["npcs/{npc_key}.description"],
        "scope": "module_context.json",
        "max_chars": 500,
    },
    "npc_role": {
        "field": "role",
        "target_paths": ["npcs/{npc_key}.role"],
        "scope": "module_context.json",
        "max_chars": 100,
    },
    "npc_faction": {
        "field": "faction",
        "target_paths": ["npcs/{npc_key}.faction"],
        "scope": "module_context.json",
        "max_chars": 100,
    },
    "plot_main_objective": {
        "field": "mainObjective",
        "target_paths": ["mainObjective"],
        "scope": "module_plot_BU.json",
        "max_chars": 500,
    },
    "plot_point_description": {
        "field": "description",
        "target_paths": ["plotPoints[{index}].description"],
        "scope": "module_plot_BU.json",
        "max_chars": 800,
    },
    "plot_point_impact": {
        "field": "plotImpact",
        "target_paths": ["plotPoints[{index}].plotImpact"],
        "scope": "module_plot_BU.json",
        "max_chars": 400,
    },
    "area_description": {
        "field": "areaDescription",
        "target_paths": ["areaDescription"],
        "scope": "area_*_BU.json",
        "max_chars": 1000,
    },
    "location_description": {
        "field": "description",
        "target_paths": ["locations[{index}].description"],
        "scope": "area_*_BU.json",
        "max_chars": 1500,
    },
    "location_dm_instructions": {
        "field": "dmInstructions",
        "target_paths": ["locations[{index}].dmInstructions"],
        "scope": "area_*_BU.json",
        "max_chars": 2000,
    },
    "location_adventure_summary": {
        "field": "adventureSummary",
        "target_paths": ["locations[{index}].adventureSummary"],
        "scope": "area_*_BU.json",
        "max_chars": 600,
    },
    "location_plot_hooks": {
        "field": "plotHooks",
        "target_paths": ["locations[{index}].plotHooks[{hook_index}]"],
        "scope": "area_*_BU.json",
        "max_chars": 300,
    },
}


def generate_builder_blueprint_v2(
    source_graph: Dict[str, Any],
    identity_report: Optional[Dict[str, Any]],
    plot_topology: Optional[Dict[str, Any]],
    synthesis_report: Optional[Dict[str, Any]],
    normalized_packet: Dict[str, Any],
    fidelity_report: Optional[Dict[str, Any]],
    content_blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Generate a builder_blueprint v2 artifact from source artifacts.

    Reuses v1 roster builders and augments with v2-specific fields:
    enrichment_allowlist, artifact_refs, coverage, and granular status.
    Preserves source names, order, IDs, and refs.

    The content_blocks parameter accepts Phase 10 deterministic parser
    output for additional map-key structure context.
    """
    # Start with v1 blueprint for core rosters
    v1 = generate_builder_blueprint(
        source_graph=source_graph,
        identity_report=identity_report,
        plot_topology=plot_topology,
        synthesis_report=synthesis_report,
        normalized_packet=normalized_packet,
        fidelity_report=fidelity_report,
    )

    atoms = source_graph.get("atoms", [])
    location_count = len(v1.get("location_roster", []))
    npc_count = len(v1.get("npc_roster", []))
    plot_count = len(v1.get("plot_graph", []))
    puzzle_count = len(v1.get("puzzle_graph", []))
    clue_count = len(v1.get("clue_graph", []))
    encounter_count = len(v1.get("encounter_plan", []))
    item_count = len(v1.get("item_roster", []))

    # Merge deterministic content block data where available
    if content_blocks:
        location_roster = _merge_content_blocks_into_roster(
            v1.get("location_roster", []), content_blocks
        )
        v1["location_roster"] = location_roster
        location_count = len(location_roster)

    # Artifact refs
    artifact_refs = {
        "source_graph": "source_graph.json" if source_graph else None,
        "identity_resolution_report": "identity_resolution_report.json" if identity_report else None,
        "plot_topology_report": "plot_topology_report.json" if plot_topology else None,
        "source_graph_synthesis_report": "source_graph_synthesis_report.json" if synthesis_report else None,
        "normalized_packet": "normalized_packet.json",
        "normalization_fidelity_report": "normalization_fidelity_report.json" if fidelity_report else None,
    }

    coverage = {
        "locations_in_blueprint": location_count,
        "npcs_in_blueprint": npc_count,
        "plot_beats_in_blueprint": plot_count,
        "puzzles_in_blueprint": puzzle_count,
        "clues_in_blueprint": clue_count,
        "encounters_in_blueprint": encounter_count,
        "items_in_blueprint": item_count,
    }

    # Determine granular blueprint status
    bp_status = _compute_blueprint_v2_status(v1, location_count, npc_count)

    # Blockers
    blockers = _compute_blueprint_v2_blockers(
        v1, location_count, npc_count, plot_count, puzzle_count
    )

    v1["blueprint_version"] = BUILDER_BLUEPRINT_V2_VERSION
    v1["blueprint_status"] = bp_status
    v1["coverage"] = coverage
    v1["enrichment_allowlist"] = dict(_ENRICHMENT_ALLOWLIST_DEFAULT)
    v1["artifact_refs"] = artifact_refs
    v1["blockers"] = blockers
    # Add the module_summary_is_derived_only lock
    v1.setdefault("source_lock", {})["module_summary_is_derived_only"] = True

    return v1


def _merge_content_blocks_into_roster(
    location_roster: List[Dict[str, Any]],
    content_blocks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge deterministic content-block metadata into location roster entries.

    Enriches existing entries with source heading style, raw content,
    map-key number, and subsection data from Phase 10 parsing.
    """
    block_map: Dict[str, Dict[str, Any]] = {}
    for block in content_blocks:
        name_key = (block.get("_source_title") or block.get("name") or "").lower().strip()
        if name_key:
            block_map[name_key] = block
        src_num = block.get("_source_number")
        if src_num is not None:
            block_map[str(src_num)] = block

    enriched = []
    for loc in location_roster:
        loc_name = loc.get("display_name", "").lower().strip()
        match = block_map.get(loc_name)
        if not match and loc.get("aliases"):
            for alias in loc["aliases"]:
                match = block_map.get(alias.lower().strip())
                if match:
                    break
        if match:
            enriched_loc = dict(loc)
            enriched_loc["_source_block_kind"] = match.get("_source_block_kind")
            enriched_loc["_source_style"] = match.get("_source_block_style")
            enriched_loc["_source_number"] = match.get("_source_number")
            enriched_loc["_raw_content_snippet"] = (match.get("raw_content") or "")[:200]
            enriched_loc["description_excerpt"] = (match.get("description") or "")[:200]
            enriched.append(enriched_loc)
        else:
            enriched.append(loc)
    return enriched


def _compute_blueprint_v2_status(
    blueprint: Dict[str, Any],
    location_count: int,
    npc_count: int,
) -> str:
    """Compute granular blueprint v2 status based on content and fidelity."""

    fidelity_status = _read_fidelity_status(
        blueprint.get("normalization_fidelity_report"),
        blueprint.get("normalization_report"),
    )

    if fidelity_status in ("blocked", "failed"):
        return STATUS_BLOCKED_BY_FIDELITY

    if location_count == 0 and npc_count == 0:
        return STATUS_GENERATION_FAILED

    if location_count == 0 or npc_count == 0:
        return "degraded"

    if fidelity_status == "degraded":
        return "degraded"

    return STATUS_READY


def _compute_blueprint_v2_blockers(
    blueprint: Dict[str, Any],
    location_count: int,
    npc_count: int,
    plot_count: int,
    puzzle_count: int,
) -> List[Dict[str, Any]]:
    """Compute blocker entries for blueprint v2 validation."""
    blockers: List[Dict[str, Any]] = []

    if location_count == 0:
        blockers.append({
            "category": "missing_locations",
            "severity": "blocker",
            "message": "No source locations in blueprint. Cannot seed module without location data.",
        })
    if npc_count == 0:
        blockers.append({
            "category": "missing_npcs",
            "severity": "warning",
            "message": "No source NPCs in blueprint. NPC descriptions will not be seeded.",
        })
    if plot_count == 0:
        blockers.append({
            "category": "missing_plot",
            "severity": "warning",
            "message": "No plot beats in blueprint. Module plot will not be seeded.",
        })

    has_blocking_fidelity = blueprint.get("blueprint_status") == STATUS_BLOCKED_BY_FIDELITY
    if has_blocking_fidelity:
        blockers.append({
            "category": "fidelity_blocked",
            "severity": "blocker",
            "message": "Blueprint fidelity status prevents seed materialization.",
        })

    return blockers


def validate_builder_blueprint_v2(
    blueprint: Dict[str, Any],
    *,
    require_locations: bool = True,
    require_npcs: bool = True,
    require_plot: bool = True,
) -> Dict[str, Any]:
    """Validate a builder_blueprint v2 artifact for completeness.

    Returns:
        Dict with:
          - valid: bool
          - status: "pass|degraded|blocked"
          - blockers: list of blocker dicts
          - warnings: list of warning dicts
          - coverage: dict from blueprint
    """
    version = str(blueprint.get("blueprint_version") or "").strip()
    if version != BUILDER_BLUEPRINT_V2_VERSION:
        return {
            "valid": False,
            "status": "blocked",
            "reason": f"Expected blueprint v2 version '{BUILDER_BLUEPRINT_V2_VERSION}', got '{version}'",
            "blockers": [{
                "category": "version_mismatch",
                "severity": "blocker",
                "message": f"Expected v2, got '{version}'",
            }],
            "warnings": [],
            "coverage": {},
        }

    bp_status = str(blueprint.get("blueprint_status") or "").strip()
    if bp_status in ("blocked", "failed", STATUS_BLOCKED_BY_FIDELITY):
        blockers = blueprint.get("blockers") or []
        return {
            "valid": False,
            "status": "blocked",
            "reason": f"Blueprint status is '{bp_status}'",
            "blockers": blockers or [{
                "category": "blueprint_status",
                "severity": "blocker",
                "message": f"Blueprint status '{bp_status}' prevents seeding",
            }],
            "warnings": blueprint.get("warnings", []),
            "coverage": blueprint.get("coverage", {}),
        }

    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    required_sections = ["module", "source_lock", "area_plan", "location_roster",
                         "npc_roster", "plot_graph", "puzzle_graph", "clue_graph",
                         "encounter_plan", "item_roster", "enrichment_allowlist",
                         "artifact_refs"]

    for section in required_sections:
        if section not in blueprint:
            blockers.append({
                "category": "missing_section",
                "severity": "blocker",
                "message": f"Required blueprint section '{section}' is missing",
            })

    source_lock = blueprint.get("source_lock", {})
    lock_keys = ["canonical_names_locked", "required_atom_omission_blocks_build",
                 "invented_major_entities_forbidden", "replacement_plotlines_forbidden",
                 "puzzle_rule_rewrite_forbidden", "module_summary_is_derived_only"]
    for key in lock_keys:
        if not source_lock.get(key):
            warnings.append({
                "category": "source_lock",
                "severity": "warning",
                "message": f"Source lock '{key}' is not enabled",
            })

    coverage = blueprint.get("coverage", {})
    loc_count = int(coverage.get("locations_in_blueprint", 0))
    npc_count = int(coverage.get("npcs_in_blueprint", 0))
    plot_count = int(coverage.get("plot_beats_in_blueprint", 0))

    if require_locations and loc_count == 0:
        blockers.append({
            "category": "empty_location_roster",
            "severity": "blocker",
            "message": "Location roster is empty when locations are required",
        })
    if require_npcs and npc_count == 0:
        warnings.append({
            "category": "empty_npc_roster",
            "severity": "warning",
            "message": "NPC roster is empty",
        })
    if require_plot and plot_count == 0:
        warnings.append({
            "category": "empty_plot_graph",
            "severity": "warning",
            "message": "Plot graph is empty",
        })

    valid = len(blockers) == 0
    status = "pass" if valid else "blocked"
    if valid and warnings:
        status = "degraded"

    return {
        "valid": valid,
        "status": status,
        "reason": "" if valid else f"{len(blockers)} validation blocker(s)",
        "blockers": blockers,
        "warnings": warnings,
        "coverage": coverage,
    }


# ---------------------------------------------------------------------------
# Narrative serialization
# ---------------------------------------------------------------------------

SECTION_SEPARATOR = "=" * 68
_SUB_SECTION = "-" * 40


def _fmt_line(label: str, value: str) -> str:
    """Format a compact two-column line for narrative text."""
    return f"  {label}: {value}".rstrip()


def serialize_builder_blueprint_to_narrative(blueprint: Dict[str, Any]) -> str:
    """Serialize ``builder_blueprint.json`` into a source-locked builder narrative.

    The narrative is a deterministic text document with section headings
    that the builder's prompt can consume as ``builder_narrative.md``.
    """
    lines: List[str] = []

    # Section 1: Source-faithful build lock
    lines.append(SECTION_SEPARATOR)
    lines.append("SOURCE-FAITHFUL BUILD LOCK")
    lines.append(SECTION_SEPARATOR)
    source_lock = blueprint.get("source_lock", {})
    if source_lock.get("canonical_names_locked"):
        lines.append("- Canonical source names are LOCKED. Do not rename required locations, NPCs, or items without an approved alias mapping.")
    if source_lock.get("required_atom_omission_blocks_build"):
        lines.append("- Required source locations, NPCs, plot beats, puzzles, and clues MUST appear in the output module or the build is invalid.")
    if source_lock.get("invented_major_entities_forbidden"):
        lines.append("- Invented major entities (factions, villains, locations, NPCs) are FORBIDDEN unless the source explicitly supports them.")
    if source_lock.get("replacement_plotlines_forbidden"):
        lines.append("- Replacement plotlines that displace source plot topology are FORBIDDEN.")
    if source_lock.get("puzzle_rule_rewrite_forbidden"):
        lines.append("- Source puzzle/trial setup, rules, solutions, and failure consequences MUST be preserved.")
    lines.append("")

    # Section 2: Module identity and tone
    lines.append(SECTION_SEPARATOR)
    lines.append("MODULE IDENTITY AND TONE")
    lines.append(SECTION_SEPARATOR)
    mod = blueprint.get("module", {})
    lines.append(_fmt_line("Title", mod.get("title", "")))
    lines.append(_fmt_line("Summary", mod.get("summary", "")))
    tone_profile = mod.get("tone_profile", {})
    markers = tone_profile.get("markers") or []
    for m in markers:
        lines.append(_fmt_line("Tone marker", m))
    unsupported = tone_profile.get("unsupported_inventions") or []
    for u in unsupported:
        lines.append(_fmt_line("Forbidden invention", u.get("detail", "")))
    lines.append("")

    # Section 3: Required location roster
    lines.append(SECTION_SEPARATOR)
    lines.append("REQUIRED LOCATION ROSTER")
    lines.append(SECTION_SEPARATOR)
    locations = blueprint.get("location_roster") or []
    for loc in locations:
        name = loc.get("display_name", "")
        aliases = loc.get("aliases") or []
        alias_text = f" (aliases: {', '.join(aliases)})" if aliases else ""
        crit = loc.get("criticality", "ambiguous")
        lines.append(f"  - {name}{alias_text} [{crit}]")
        refs = loc.get("source_refs") or []
        for r in refs[:1]:
            excerpt = str(r.get("excerpt", ""))[:_MAX_EXCERPT_CHARS]
            if excerpt:
                lines.append(f"       Source: {excerpt}")
    if not locations:
        lines.append("  (no source locations found in blueprint)")
    lines.append("")

    # Section 4: Required NPC roster
    lines.append(SECTION_SEPARATOR)
    lines.append("REQUIRED NPC ROSTER")
    lines.append(SECTION_SEPARATOR)
    npcs = blueprint.get("npc_roster") or []
    for npc in npcs:
        name = npc.get("display_name", "")
        role = npc.get("role", "")
        faction = npc.get("faction", "")
        aliases = npc.get("aliases") or []
        alias_text = f" (aliases: {', '.join(aliases)})" if aliases else ""
        crit = npc.get("criticality", "ambiguous")
        role_text = f" role={role}" if role else ""
        faction_text = f" faction={faction}" if faction else ""
        lines.append(f"  - {name}{alias_text}{role_text}{faction_text} [{crit}]")
        refs = npc.get("source_refs") or []
        for r in refs[:1]:
            excerpt = str(r.get("excerpt", ""))[:_MAX_EXCERPT_CHARS]
            if excerpt:
                lines.append(f"       Source: {excerpt}")
    if not npcs:
        lines.append("  (no source NPCs found in blueprint)")
    lines.append("")

    # Section 5: Plot topology
    lines.append(SECTION_SEPARATOR)
    lines.append("PLOT TOPOLOGY")
    lines.append(SECTION_SEPARATOR)
    plot = blueprint.get("plot_graph") or []
    for beat in plot:
        title = beat.get("title", "")
        btype = beat.get("beat_type", "mainline")
        trigger = beat.get("trigger", "")
        deps = beat.get("dependencies") or []
        dep_text = f" depends_on={deps}" if deps else ""
        lines.append(f"  - [{btype}] {title}{dep_text}")
        if trigger:
            lines.append(f"       Trigger: {trigger}")
        outcome = beat.get("outcome", "")
        if outcome:
            lines.append(f"       Outcome: {outcome}")
        failure = beat.get("failure_state", "")
        if failure:
            lines.append(f"       Failure: {failure}")
    if not plot:
        lines.append("  (no plot topology in blueprint)")
    lines.append("")

    # Section 6: Puzzle and trial rules
    lines.append(SECTION_SEPARATOR)
    lines.append("PUZZLE AND TRIAL RULES")
    lines.append(SECTION_SEPARATOR)
    puzzles = blueprint.get("puzzle_graph") or []
    for p in puzzles:
        ptitle = p.get("title", "")
        lines.append(f"  - {ptitle}")
        setup = p.get("setup", "")
        if setup:
            lines.append(f"       Setup: {setup}")
        rules = p.get("rules", "")
        if rules:
            lines.append(f"       Rules: {rules}")
        solution = p.get("solution", "")
        if solution:
            lines.append(f"       Solution: {solution}")
        failure = p.get("failure_consequences", "")
        if failure:
            lines.append(f"       Failure: {failure}")
        unlocks = p.get("unlocks", "")
        if unlocks:
            lines.append(f"       Unlocks: {unlocks}")
        clue_deps = p.get("clue_dependencies") or []
        if clue_deps:
            lines.append(f"       Requires clues: {clue_deps}")
    if not puzzles:
        lines.append("  (no source puzzles in blueprint)")
    lines.append("")

    # Section 7: Clue graph
    lines.append(SECTION_SEPARATOR)
    lines.append("CLUE GRAPH")
    lines.append(SECTION_SEPARATOR)
    clues = blueprint.get("clue_graph") or []
    for c in clues:
        desc = c.get("description", "")
        loc = c.get("location", "")
        reveals = c.get("reveals", "")
        mandatory = c.get("mandatory", False)
        mandatory_text = " [MANDATORY]" if mandatory else ""
        loc_text = f" at {loc}" if loc else ""
        lines.append(f"  - {desc}{loc_text}{mandatory_text}")
        if reveals:
            lines.append(f"       Reveals: {reveals}")
    if not clues:
        lines.append("  (no clue graph in blueprint)")
    lines.append("")

    # Section 8: Encounter and monster plan
    lines.append(SECTION_SEPARATOR)
    lines.append("ENCOUNTER AND MONSTER PLAN")
    lines.append(SECTION_SEPARATOR)
    enemies = blueprint.get("encounter_plan") or []
    for e in enemies:
        ename = e.get("name", "")
        eloc = e.get("location", "")
        epurpose = e.get("purpose", "")
        monsters = e.get("monster_names") or []
        m_text = f" monsters={monsters}" if monsters else ""
        avoid_text = " [AVOIDABLE]" if e.get("avoidable") else ""
        social_text = " [SOCIAL]" if e.get("social") else ""
        lines.append(f"  - {ename} at {eloc}{m_text}{avoid_text}{social_text}")
        if epurpose:
            lines.append(f"       Purpose: {epurpose}")
    if not enemies:
        lines.append("  (no encounter plan in blueprint)")
    lines.append("")

    # Section 9: Item and treasure plan
    lines.append(SECTION_SEPARATOR)
    lines.append("ITEM AND TREASURE PLAN")
    lines.append(SECTION_SEPARATOR)
    items = blueprint.get("item_roster") or []
    for item in items:
        iname = item.get("display_name", "")
        iloc = item.get("location", "")
        ireq = item.get("required", False)
        req_text = " [REQUIRED]" if ireq else ""
        loc_text = f" at {iloc}" if iloc else ""
        lines.append(f"  - {iname}{loc_text}{req_text}")
    if not items:
        lines.append("  (no item plan in blueprint)")
    lines.append("")

    # Section 10: Forbidden inventions and replacements
    lines.append(SECTION_SEPARATOR)
    lines.append("FORBIDDEN INVENTIONS AND REPLACEMENTS")
    lines.append(SECTION_SEPARATOR)
    warnings = blueprint.get("warnings") or []
    has_forbidden = False
    for w in warnings:
        if w.get("source") == "unsupported_addition":
            has_forbidden = True
            lines.append(f"  - {w.get('message', '')}")
    if not has_forbidden:
        lines.append("  (no forbidden inventions reported by fidelity audit)")
    lines.append("")

    # Section 11: Allowed compression or merge notes
    lines.append(SECTION_SEPARATOR)
    lines.append("ALLOWED COMPRESSION OR MERGE NOTES")
    lines.append(SECTION_SEPARATOR)
    for w in warnings:
        if w.get("source") not in ("unsupported_addition",):
            lines.append(f"  - {w.get('message', '')}")
    if not warnings:
        lines.append("  (no compression or merge notes from fidelity audit)")
    lines.append("")

    return "\n".join(lines)
