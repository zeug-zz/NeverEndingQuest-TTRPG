# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Blueprint Seed Writer
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free deterministic seed writer for the accurate-ingest pipeline.
Consumes builder_blueprint.v2 and emits a schema-valid skeletal NEQ module
before any LLM enrichment pass.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.file_operations import safe_write_json

SEED_REPORT_VERSION = "blueprint_seed_report.v1"
STATUS_SEED_REFUSED = "refused"
STATUS_SEED_PLANNED = "planned"
STATUS_SEED_SUCCESS = "success"
STATUS_SEED_DEGRADED = "degraded"
STATUS_SEED_FAILED = "failed"

# Seed artifact version constants
NPC_SEED_VERSION = "toolkit_npc_seed.v1"
MONSTER_SEED_VERSION = "toolkit_monster_seed.v1"
SEED_SOURCE_REPORT_VERSION = "toolkit_seed_source_report.v1"

LOCATION_REQUIRED_DEFAULTS: Dict[str, Any] = {
    "type": "room",
    "description": "",
    "dmInstructions": "",
    "coordinates": "X0Y0",
    "accessibility": "",
    "npcs": [],
    "monsters": [],
    "plotHooks": [],
    "lootTable": [],
    "dangerLevel": "Medium",
    "connectivity": [],
    "areaConnectivity": [],
    "areaConnectivityId": [],
    "traps": [],
    "features": [],
    "dcChecks": [],
    "encounters": [],
    "adventureSummary": "",
    "doors": [],
}


def _validate_blueprint_for_seeding(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    """Validate that a blueprint can be seeded.

    Returns dict with keys: valid, reason, blockers, warnings
    """
    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    version = str(blueprint.get("blueprint_version") or "").strip()
    if "v2" not in version:
        blockers.append({
            "category": "version_mismatch",
            "severity": "blocker",
            "message": f"Expected blueprint v2 version, got '{version}'",
        })

    bp_status = str(blueprint.get("blueprint_status") or "").strip()
    if bp_status in ("blocked", "failed", "blocked_by_fidelity", "generation_failed"):
        blockers.append({
            "category": "blueprint_status",
            "severity": "blocker",
            "message": f"Blueprint status '{bp_status}' prevents seed materialization",
        })

    required_sections = [
        "module", "source_lock", "area_plan", "location_roster",
        "npc_roster", "plot_graph",
    ]
    for section in required_sections:
        if section not in blueprint:
            blockers.append({
                "category": "missing_section",
                "severity": "blocker",
                "message": f"Required blueprint section '{section}' is missing",
            })

    coverage = blueprint.get("coverage", {})
    loc_count = int(coverage.get("locations_in_blueprint", 0))
    npc_count = int(coverage.get("npcs_in_blueprint", 0))

    if loc_count == 0:
        blockers.append({
            "category": "empty_location_roster",
            "severity": "blocker",
            "message": "No locations in blueprint - cannot seed module",
        })
    if npc_count == 0:
        warnings.append({
            "category": "empty_npc_roster",
            "severity": "warning",
            "message": "No NPCs in blueprint - NPC entries will be empty",
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
    }


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    s = s.strip('_')
    return s or "module"


def _generate_area_id(index: int) -> str:
    return f"A{index:03d}"


def _generate_location_id(area_id: str, index: int) -> str:
    prefix = "".join(c for c in area_id if c.isalpha())
    return f"{prefix}{index+1:02d}"


def _group_locations_by_area(
    area_plan: List[Dict[str, Any]],
    location_roster: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group location_roster entries by their parent_area from area_plan."""
    area_map: Dict[str, List[Dict[str, Any]]] = {}
    if area_plan:
        for area_entry in area_plan:
            area_name = area_entry.get("area_name", "")
            if area_name:
                area_map[area_name] = []
        for loc in location_roster:
            parent = loc.get("parent_area", "")
            if parent and parent in area_map:
                area_map[parent].append(loc)
            elif parent:
                area_map.setdefault(parent, []).append(loc)
    if not area_map:
        area_map["default_area"] = list(location_roster)
    return area_map


def _find_unassigned_npcs(
    npc_roster: List[Dict[str, Any]],
    location_roster: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Find NPCs with no location_binding that matches any known location."""
    known_names: Set[str] = set()
    for loc in location_roster:
        name = loc.get("display_name", "").lower().strip()
        if name:
            known_names.add(name)
        for alias in loc.get("aliases", []):
            known_names.add(alias.lower().strip())

    unassigned: List[Dict[str, Any]] = []
    for npc in npc_roster:
        binding = (npc.get("location_binding") or "").lower().strip()
        if binding and binding in known_names:
            continue
        unassigned.append(npc)
    return unassigned


def _gather_seed_warnings(
    blueprint: Dict[str, Any],
    unassigned_npcs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []
    if unassigned_npcs:
        names = [n.get("display_name", "?") for n in unassigned_npcs[:5]]
        suffix = f" (and {len(unassigned_npcs) - 5} more)" if len(unassigned_npcs) > 5 else ""
        warnings.append({
            "category": "unassigned_npcs",
            "severity": "warning",
            "message": f"{len(unassigned_npcs)} NPC(s) without location binding: {', '.join(names)}{suffix}. "
                       "NPC entries will appear in module_context but not in any area file.",
        })
    obs = blueprint.get("encounter_plan", [])
    if obs:
        warnings.append({
            "category": "monster_stats_not_seeded",
            "severity": "info",
            "message": f"{len(obs)} encounter(s) planned but monster stat files not created. "
                       "Enrichment phase should add monster stats.",
        })
    return warnings


def _build_npc_location_map(
    npc_roster: List[Dict[str, Any]],
    location_roster: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Build mapping of NPC display_name to their location display_name."""
    known: Dict[str, str] = {}
    for loc in location_roster:
        loc_name = loc.get("display_name", "")
        for npc in npc_roster:
            binding = (npc.get("location_binding") or "").lower().strip()
            if binding:
                if binding == loc_name.lower().strip():
                    known[npc.get("display_name", "")] = loc_name
                else:
                    for alias in loc.get("aliases", []):
                        if binding == alias.lower().strip():
                            known[npc.get("display_name", "")] = loc_name
                            break
    return known


def _compute_planned_files(
    module_dir: str,
    area_ids: Dict[str, str],
    area_locations: Dict[str, list],
) -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    base = Path(module_dir)
    files.append({"path": str(base / "module_context.json"), "purpose": "module identity and NPC roster"})
    files.append({"path": str(base / "module_context_BU.json"), "purpose": "canonical backup of module_context"})
    files.append({"path": str(base / "module_plot.json"), "purpose": "plot points from source topology"})
    files.append({"path": str(base / "module_plot_BU.json"), "purpose": "canonical backup of module_plot"})
    files.append({"path": str(base / "party_tracker_BU.json"), "purpose": "canonical party tracker backup"})
    for area_name, area_id in area_ids.items():
        count = len(area_locations.get(area_name, []))
        files.append({"path": str(base / "areas" / f"{area_id}_BU.json"), "purpose": f"area {area_name} with {count} locations"})
        files.append({"path": str(base / "areas" / f"{area_id}.json"), "purpose": f"runtime area {area_name}"})
        files.append({"path": str(base / f"map_{area_id}.json"), "purpose": f"map for area {area_name}"})
    # Seed support artifacts
    files.append({"path": str(base / "npcs_seed.json"), "purpose": "NPC seed for media prewarm and materialization"})
    files.append({"path": str(base / "monsters_seed.json"), "purpose": "monster seed for media prewarm and materialization"})
    files.append({"path": str(base / "seed_source_report.json"), "purpose": "source-preservation sidecar with IDs, order, and refs"})
    return files


def _safe_write_json(
    filepath: Path,
    data: Dict[str, Any],
    created: list,
    skipped: list,
) -> None:
    """Write JSON file atomically, recording success or skip."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(str(filepath), data)
        created.append(str(filepath))
    except Exception as e:
        skipped.append({"path": str(filepath), "reason": str(e)})


def _build_module_context(
    module_name: str,
    module_id: str,
    area_ids: Dict[str, str],
    area_locations: Dict[str, List[Dict[str, Any]]],
    location_roster: List[Dict[str, Any]],
    npc_roster: List[Dict[str, Any]],
    plot_graph: List[Dict[str, Any]],
    area_plan: List[Dict[str, Any]],
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build module_context.json from blueprint data."""

    # Build area_name -> area_type lookup from area_plan (default to wilderness)
    area_type_map: Dict[str, str] = {}
    for area_entry in area_plan:
        aname = area_entry.get("area_name", "")
        atype = area_entry.get("area_type", "wilderness")
        area_type_map[aname] = atype

    # Build location_id -> display_name mapping
    loc_id_map: Dict[str, str] = {}
    for area_name, locs in area_locations.items():
        area_id = area_ids.get(area_name, "")
        if not area_id:
            continue
        for i, loc in enumerate(locs):
            lid = _generate_location_id(area_id, i)
            loc_id_map[lid] = loc.get("display_name", "")

    # Build areas dict
    areas: Dict[str, Any] = {}
    for area_name, locs in area_locations.items():
        area_id = area_ids.get(area_name, "")
        if not area_id:
            continue
        loc_ids: List[str] = []
        area_npcs: List[str] = []
        for i, loc in enumerate(locs):
            lid = _generate_location_id(area_id, i)
            loc_ids.append(lid)
        area_type = area_type_map.get(area_name, "wilderness")
        areas[area_id] = {
            "name": area_name,
            "type": area_type,
            "locations": loc_ids,
            "npcs": area_npcs,
            "plot_points": [],
        }

    # Build NPCs dict
    npcs_dict: Dict[str, Any] = {}
    for npc in npc_roster:
        key = _slugify(npc.get("display_name", ""))
        if not key:
            continue
        entry: Dict[str, Any] = {
            "name": npc.get("display_name", ""),
            "role": npc.get("role", ""),
            "faction": npc.get("faction", ""),
            "appears_in": [],
        }
        binding = (npc.get("location_binding") or "").lower().strip()
        if binding:
            for area_name, locs in area_locations.items():
                area_id = area_ids.get(area_name, "")
                if not area_id:
                    continue
                for i, loc in enumerate(locs):
                    dname = (loc.get("display_name") or "").lower().strip()
                    if binding == dname or binding in [a.lower().strip() for a in loc.get("aliases", [])]:
                        lid = _generate_location_id(area_id, i)
                        entry["appears_in"].append({
                            "area": area_id,
                            "location": lid,
                        })
                        area_npc_list = areas.get(area_id, {}).get("npcs", [])
                        if isinstance(area_npc_list, list) and npc.get("display_name", "") not in area_npc_list:
                            area_npc_list.append(npc.get("display_name", ""))
                        break
        npcs_dict[key] = entry

    # Build locations dict
    locations_dict: Dict[str, Any] = {}
    for area_name, locs in area_locations.items():
        area_id = area_ids.get(area_name, "")
        if not area_id:
            continue
        for i, loc in enumerate(locs):
            lid = _generate_location_id(area_id, i)
            locations_dict[lid] = {
                "name": loc.get("display_name", ""),
                "aliases": loc.get("aliases", []),
                "area": area_id,
            }

    # Build plot_scopes
    plot_scopes: Dict[str, str] = {}
    for beat in plot_graph:
        beat_id = beat.get("beat_id", "")
        if not beat_id:
            continue
        req_loc = beat.get("required_location", "")
        if req_loc:
            for area_name, locs in area_locations.items():
                area_id = area_ids.get(area_name, "")
                if not area_id:
                    continue
                for loc in locs:
                    if loc.get("display_name", "").lower().strip() == req_loc.lower().strip():
                        plot_scopes[beat_id] = area_id
                        break
        if beat_id not in plot_scopes and area_ids:
            plot_scopes[beat_id] = list(area_ids.values())[0]

    # Build references
    references: Dict[str, List[str]] = {}
    for npc in npc_roster:
        npc_name = npc.get("display_name", "")
        if npc_name:
            ref_key = f"npc:{npc_name}"
            references[ref_key] = ["module:plotStages"]

    result: Dict[str, Any] = {
        "module_name": module_name,
        "module_id": module_id,
        "areas": areas,
        "npcs": npcs_dict,
        "locations": locations_dict,
        "plot_scopes": plot_scopes,
        "references": references,
    }
    if blueprint:
        tone_reqs = blueprint.get("tone_requirements") or {}
        if isinstance(tone_reqs, str):
            tone_label = tone_reqs
        elif isinstance(tone_reqs, list):
            tone_label = " ".join(str(t) for t in tone_reqs)
        elif isinstance(tone_reqs, dict):
            tone_label = " ".join(str(v) for v in tone_reqs.values())
        else:
            tone_label = ""
        result["tone"] = tone_label
        result["classification_metadata"] = {
            "tone": tone_label if tone_label else blueprint.get("module", {}).get("summary", ""),
        }
    return result


def _build_module_plot(
    blueprint: Dict[str, Any],
    plot_graph: List[Dict[str, Any]],
    area_ids: Dict[str, str],
    area_locations: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build module_plot.json from blueprint plot_graph."""
    mod = blueprint.get("module", {})
    plot_title = mod.get("title", "Unknown Module") + " - Plot"
    main_objective = mod.get("summary", "")

    plot_points: List[Dict[str, Any]] = []
    for i, beat in enumerate(plot_graph):
        req_loc = beat.get("required_location", "")
        location_str = ""
        if req_loc:
            for area_name, locs in area_locations.items():
                for loc in locs:
                    if loc.get("display_name", "").lower().strip() == req_loc.lower().strip():
                        area_id = area_ids.get(area_name, "")
                        if area_id:
                            location_str = f"{area_id}:{req_loc}"
                        break
                if location_str:
                    break

        next_points: List[str] = []
        deps = beat.get("dependencies", [])
        for dep in deps:
            dep_id = dep if isinstance(dep, str) else ""
            if dep_id:
                next_points.append(dep_id)

        pp = {
            "id": beat.get("beat_id", f"PP{i+1:03d}"),
            "title": beat.get("title", ""),
            "description": beat.get("outcome", ""),
            "location": location_str,
            "nextPoints": next_points,
            "status": "not started",
            "plotImpact": "",
            "sideQuests": [],
        }
        plot_points.append(pp)

    return {
        "plotTitle": plot_title,
        "mainObjective": main_objective,
        "plotPoints": plot_points,
    }


def _build_area_file(
    area_id: str,
    area_name: str,
    loc_entries: List[Dict[str, Any]],
    location_roster: List[Dict[str, Any]],
    npc_loc_map: Dict[str, str],
    plot_graph: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build area JSON file from blueprint location roster data."""

    # Build location entries
    locations: List[Dict[str, Any]] = []
    for i, loc_entry in enumerate(loc_entries):
        lid = _generate_location_id(area_id, i)
        dname = loc_entry.get("display_name", "")

        # Find NPCs bound to this location
        loc_npcs: List[Dict[str, Any]] = []
        for npc_name, npc_loc in npc_loc_map.items():
            if npc_loc.lower().strip() == dname.lower().strip():
                loc_npcs.append({
                    "name": npc_name,
                    "description": "",
                    "attitude": "",
                })

        # Build connectivity from same-area location IDs (chain adjacency).
        # Use generated location IDs to avoid validator "unknown room" errors.
        connectivity: List[str] = []
        area_room_ids = [_generate_location_id(area_id, j) for j in range(len(loc_entries))]
        if i > 0:
            connectivity.append(area_room_ids[i - 1])
        if i < len(area_room_ids) - 1:
            connectivity.append(area_room_ids[i + 1])

        loc: Dict[str, Any] = {
            "name": dname,
            "type": "room",
            "description": "",
            "dmInstructions": "",
            "locationId": lid,
            "coordinates": "X0Y0",
            "accessibility": "",
            "npcs": loc_npcs,
            "monsters": [],
            "plotHooks": [],
            "lootTable": [],
            "dangerLevel": "Medium",
            "connectivity": connectivity,
            "areaConnectivity": [],
            "areaConnectivityId": [],
            "traps": [],
            "features": [],
            "dcChecks": [],
            "encounters": [],
            "adventureSummary": "",
            "doors": [],
        }
        locations.append(loc)

    # Map rooms
    rooms = []
    for i, loc in enumerate(locations):
        lid = loc["locationId"]
        rooms.append({
            "id": lid,
            "name": loc["name"],
            "connections": loc.get("connectivity", []),
            "coordinates": loc.get("coordinates", "X0Y0"),
        })

    return {
        "areaId": area_id,
        "areaName": area_name,
        "areaType": "wilderness",
        "areaDescription": "",
        "dangerLevel": "Medium",
        "recommendedLevel": 1,
        "climate": "temperate",
        "terrain": "wilderness",
        "map": {
            "mapId": f"MAP_{area_id}",
            "mapName": f"{area_name} Map",
            "totalRooms": len(rooms),
            "rooms": rooms,
            "layout": _generate_default_layout(rooms),
        },
        "locations": locations,
    }


def _generate_default_layout(rooms: List[Dict[str, Any]]) -> List[List[str]]:
    """Generate a simple grid layout from room connections."""
    if not rooms:
        return [["   "]]
    grid_size = max(3, int(len(rooms) ** 0.5) + 1)
    placed: Dict[str, Tuple[int, int]] = {}
    grid = [["   " for _ in range(grid_size)] for _ in range(grid_size)]

    for i, room in enumerate(rooms):
        row = i // grid_size
        col = i % grid_size
        if row < grid_size and col < grid_size:
            rid = room["id"]
            placed[rid] = (row, col)
            grid[row][col] = rid

    return grid


def _build_map_file(area_file: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build map JSON from area file map data."""
    map_data = area_file.get("map")
    if not map_data:
        return None
    rooms = map_data.get("rooms", [])
    if not rooms:
        return None
    return {
        "mapName": map_data.get("mapName", ""),
        "mapId": map_data.get("mapId", ""),
        "totalRooms": map_data.get("totalRooms", len(rooms)),
        "startRoom": rooms[0]["id"] if rooms else "",
        "rooms": rooms,
        "layout": map_data.get("layout", _generate_default_layout(rooms)),
    }


def _build_npcs_seed(
    blueprint: Dict[str, Any],
    npc_roster: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build npcs_seed.json content from blueprint NPC roster.

    Args:
        blueprint: builder_blueprint.v2 dict
        npc_roster: Blueprint npc_roster list

    Returns:
        Dict with schema_version, source, blueprint_version, module_title,
        source_hash, and npcs array preserving names, aliases, role, faction,
        location_binding, scene_presence, criticality, and source_refs.
    """
    mod = blueprint.get("module", {})
    source_hash = blueprint.get("source_hash", "")
    bp_version = blueprint.get("blueprint_version", "")

    npcs: List[Dict[str, Any]] = []
    for npc in npc_roster:
        entry: Dict[str, Any] = {
            "name": npc.get("display_name", ""),
            "aliases": npc.get("aliases", []),
            "role": npc.get("role", ""),
            "faction": npc.get("faction", ""),
            "location_binding": npc.get("location_binding", ""),
            "scene_presence": npc.get("scene_presence", ""),
            "criticality": npc.get("criticality", "optional"),
            "source_refs": npc.get("source_refs", []),
        }
        npcs.append(entry)

    return {
        "schema_version": NPC_SEED_VERSION,
        "source": "builder_blueprint.v2",
        "blueprint_version": bp_version,
        "module_title": mod.get("title", ""),
        "source_hash": source_hash,
        "npcs": npcs,
    }


def _build_monsters_seed(
    blueprint: Dict[str, Any],
    location_roster: List[Dict[str, Any]],
    encounter_plan: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build monsters_seed.json content conservatively from blueprint data.

    Does not generate monster stat files. Preserves source monster names
    and materialization hints for downstream media/builder tooling.

    Deduplicates by normalized name, keeping first source order.

    Args:
        blueprint: builder_blueprint.v2 dict
        location_roster: Blueprint location_roster list
        encounter_plan: Blueprint encounter_plan list

    Returns:
        Dict with schema_version, source, blueprint_version, module_title,
        source_hash, and monsters array.
    """
    mod = blueprint.get("module", {})
    source_hash = blueprint.get("source_hash", "")
    bp_version = blueprint.get("blueprint_version", "")

    seen: Set[str] = set()
    monsters: List[Dict[str, Any]] = []

    def _add(name: str, location: str, criticality: str, source_refs: list, hint: str) -> None:
        key = name.lower().strip()
        if not key or key in seen:
            return
        seen.add(key)
        monsters.append({
            "name": name,
            "location_binding": location,
            "criticality": criticality,
            "source_refs": source_refs,
            "materialization_hint": hint,
        })

    # Priority 1: Encounter plan explicit monster/creature entries
    for enc in encounter_plan:
        for monster_ref in enc.get("monsters", enc.get("creatures", [])):
            if isinstance(monster_ref, str):
                _add(monster_ref, "", "major", [], "srd_lookup_candidate")
            elif isinstance(monster_ref, dict):
                mname = monster_ref.get("name", monster_ref.get("creature", ""))
                hint = monster_ref.get("materialization_hint", "custom_needed")
                loc = monster_ref.get("location_binding", "")
                _add(mname, loc, "major", monster_ref.get("source_refs", []), hint)
        # Support builder blueprint monster_names list
        enc_loc = enc.get("location", enc.get("required_location", ""))
        enc_refs = enc.get("source_refs", [])
        for mname in enc.get("monster_names", []):
            if isinstance(mname, str):
                _add(mname, enc_loc, "major", enc_refs, "srd_lookup_candidate")

    # Priority 2: Location roster structured monster refs
    for loc in location_roster:
        loc_monsters = loc.get("monsters", [])
        if isinstance(loc_monsters, list):
            for mref in loc_monsters:
                if isinstance(mref, str):
                    _add(mref, loc.get("display_name", ""), "minor", loc.get("source_refs", []), "srd_lookup_candidate")
                elif isinstance(mref, dict):
                    mname = mref.get("name", mref.get("creature", ""))
                    hint = mref.get("materialization_hint", "custom_needed")
                    _add(mname, loc.get("display_name", ""), "minor", mref.get("source_refs", []), hint)

    # Priority 3: Normalized packet monster hints
    if "monster_hints" in blueprint:
        mh = blueprint["monster_hints"]
        if isinstance(mh, list):
            for hint_entry in mh:
                if isinstance(hint_entry, str):
                    _add(hint_entry, "", "minor", [], "srd_lookup_candidate")
                elif isinstance(hint_entry, dict):
                    _add(
                        hint_entry.get("name", ""),
                        hint_entry.get("location_binding", ""),
                        hint_entry.get("criticality", "minor"),
                        hint_entry.get("source_refs", []),
                        "srd_lookup_candidate",
                    )

    return {
        "schema_version": MONSTER_SEED_VERSION,
        "source": "builder_blueprint.v2",
        "blueprint_version": bp_version,
        "module_title": mod.get("title", ""),
        "source_hash": source_hash,
        "monsters": monsters,
    }


def _build_party_tracker_backup(
    module_name: str,
    area_ids: Dict[str, str],
    area_locations: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build canonical starting party tracker backup for seeded modules."""
    first_area_name = next(iter(area_locations.keys()), "")
    first_area_id = area_ids.get(first_area_name, "")
    first_location: Dict[str, Any] = {}
    if first_area_name and area_locations.get(first_area_name):
        first_location = area_locations[first_area_name][0] or {}

    return {
        "module": module_name,
        "partyMembers": [],
        "partyNPCs": [],
        "worldConditions": {
            "year": 1492,
            "month": "Hammer",
            "day": 1,
            "time": "08:00:00",
            "weather": "Clear",
            "season": "Winter",
            "dayNightCycle": "Day",
            "moonPhase": "New Moon",
            "currentLocation": str(first_location.get("display_name") or first_location.get("name") or ""),
            "currentLocationId": str(first_location.get("location_id") or first_location.get("locationId") or ""),
            "currentArea": first_area_name,
            "currentAreaId": first_area_id,
            "majorEventsUnderway": [],
            "politicalClimate": "",
            "activeEncounter": "",
            "activeCombatEncounter": "",
            "weatherConditions": "",
            "lastCompletedEncounter": "",
        },
        "activeQuests": [],
    }


def _build_seed_source_report(
    blueprint: Dict[str, Any],
    area_plan: List[Dict[str, Any]],
    location_roster: List[Dict[str, Any]],
    npc_roster: List[Dict[str, Any]],
    plot_graph: List[Dict[str, Any]],
    puzzle_graph: List[Dict[str, Any]],
    clue_graph: List[Dict[str, Any]],
    encounter_plan: List[Dict[str, Any]],
    item_roster: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build seed source report preserving blueprint IDs, source order, and refs.

    Serves as the sidecar source-preservation artifact when module schemas
    cannot carry all blueprint metadata directly.

    Args:
        blueprint: builder_blueprint.v2 dict
        area_plan: Blueprint area_plan list
        location_roster: Blueprint location_roster list
        npc_roster: Blueprint npc_roster list
        plot_graph: Blueprint plot_graph list
        puzzle_graph: Blueprint puzzle_graph list
        clue_graph: Blueprint clue_graph list
        encounter_plan: Blueprint encounter_plan list
        item_roster: Blueprint item_roster list

    Returns:
        Dict with report_version, module_title, source_hash, source,
        and arrays for locations, npcs, plot_beats, puzzles, clues,
        encounters, and items preserving source order and source refs.
    """
    mod = blueprint.get("module", {})
    source_hash = blueprint.get("source_hash", "")
    bp_version = blueprint.get("blueprint_version", "")

    locations: List[Dict[str, Any]] = []
    for i, loc in enumerate(location_roster):
        source_refs = loc.get("source_refs", [])
        locations.append({
            "source_order": i,
            "atom_id": loc.get("atom_id", ""),
            "display_name": loc.get("display_name", ""),
            "aliases": loc.get("aliases", []),
            "parent_area": loc.get("parent_area", ""),
            "criticality": loc.get("criticality", "optional"),
            "source_refs": source_refs,
        })

    npcs: List[Dict[str, Any]] = []
    for i, npc in enumerate(npc_roster):
        npcs.append({
            "source_order": i,
            "atom_id": npc.get("atom_id", ""),
            "display_name": npc.get("display_name", ""),
            "aliases": npc.get("aliases", []),
            "role": npc.get("role", ""),
            "faction": npc.get("faction", ""),
            "location_binding": npc.get("location_binding", ""),
            "scene_presence": npc.get("scene_presence", ""),
            "criticality": npc.get("criticality", "optional"),
            "source_refs": npc.get("source_refs", []),
        })

    plot_beats: List[Dict[str, Any]] = []
    for i, beat in enumerate(plot_graph):
        plot_beats.append({
            "source_order": i,
            "beat_id": beat.get("beat_id", ""),
            "title": beat.get("title", ""),
            "trigger": beat.get("trigger", ""),
            "dependencies": beat.get("dependencies", []),
            "required_location": beat.get("required_location", ""),
            "required_npc": beat.get("required_npc", ""),
            "outcome": beat.get("outcome", ""),
            "failure_state": beat.get("failure_state", ""),
            "beat_type": beat.get("beat_type", ""),
            "criticality": beat.get("criticality", "required"),
            "source_refs": beat.get("source_refs", []),
        })

    puzzles: List[Dict[str, Any]] = []
    for i, puzzle in enumerate(puzzle_graph):
        puzzles.append({
            "source_order": i,
            "chain_id": puzzle.get("chain_id", ""),
            "title": puzzle.get("title", ""),
            "setup": puzzle.get("setup", ""),
            "rules": puzzle.get("rules", ""),
            "solution": puzzle.get("solution", ""),
            "failure_consequences": puzzle.get("failure_consequences", ""),
            "unlocks": puzzle.get("unlocks", ""),
            "criticality": puzzle.get("criticality", "required"),
            "source_refs": puzzle.get("source_refs", []),
        })

    clues: List[Dict[str, Any]] = []
    for i, clue in enumerate(clue_graph):
        clues.append({
            "source_order": i,
            "clue_id": clue.get("clue_id", ""),
            "description": clue.get("description", ""),
            "location": clue.get("location", ""),
            "reveals": clue.get("reveals", ""),
            "mandatory": bool(clue.get("mandatory", False)),
            "supports_beat": clue.get("supports_beat", ""),
            "criticality": clue.get("criticality", "required") if clue.get("mandatory", False) else "optional",
            "source_refs": clue.get("source_refs", []),
        })

    encounters: List[Dict[str, Any]] = []
    for i, enc in enumerate(encounter_plan):
        encounters.append({
            "source_order": i,
            "atom_id": enc.get("atom_id", ""),
            "name": enc.get("name", enc.get("title", "")),
            "location": enc.get("location", enc.get("required_location", "")),
            "purpose": enc.get("purpose", enc.get("summary", "")),
            "monsters": enc.get("monsters", enc.get("creatures", [])),
            "monster_names": enc.get("monster_names", []),
            "avoidable": bool(enc.get("avoidable", False)),
            "social": bool(enc.get("social", False)),
            "criticality": enc.get("criticality", "major"),
            "source_refs": enc.get("source_refs", []),
        })

    items: List[Dict[str, Any]] = []
    for i, item in enumerate(item_roster):
        items.append({
            "source_order": i,
            "atom_id": item.get("atom_id", ""),
            "name": item.get("name", item.get("display_name", "")),
            "display_name": item.get("display_name", ""),
            "type": item.get("type", ""),
            "location": item.get("location", item.get("location_binding", "")),
            "description": item.get("description", ""),
            "required": bool(item.get("required", False)),
            "criticality": item.get("criticality", "optional"),
            "source_refs": item.get("source_refs", []),
        })

    bp_coverage = blueprint.get("coverage", {})
    coverage_meta = {
        "locations_count": len(locations),
        "npcs_count": len(npcs),
        "plot_beats_count": len(plot_beats),
        "puzzles_count": len(puzzles),
        "clues_count": len(clues),
        "encounters_count": len(encounters),
        "items_count": len(items),
        "locations_in_blueprint": bp_coverage.get("locations_in_blueprint", 0),
        "npcs_in_blueprint": bp_coverage.get("npcs_in_blueprint", 0),
        "plot_beats_in_blueprint": bp_coverage.get("plot_beats_in_blueprint", 0),
        "puzzles_in_blueprint": bp_coverage.get("puzzles_in_blueprint", 0),
        "clues_in_blueprint": bp_coverage.get("clues_in_blueprint", 0),
        "encounters_in_blueprint": bp_coverage.get("encounters_in_blueprint", 0),
        "items_in_blueprint": bp_coverage.get("items_in_blueprint", 0),
    }

    return {
        "report_version": SEED_SOURCE_REPORT_VERSION,
        "source": "builder_blueprint.v2",
        "blueprint_version": bp_version,
        "module_title": mod.get("title", ""),
        "source_hash": source_hash,
        "coverage": coverage_meta,
        "locations": locations,
        "npcs": npcs,
        "plot_beats": plot_beats,
        "puzzles": puzzles,
        "clues": clues,
        "encounters": encounters,
        "items": items,
    }


def materialize_module_from_blueprint(
    blueprint: Dict[str, Any],
    module_dir: str,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Materialize a skeletal NEQ module from a builder_blueprint.v2.

    Refuses blocked/failed/non-v2 blueprints by default.
    In dry_run mode returns planned files and coverage without writing.

    Args:
        blueprint: builder_blueprint.v2 dict
        module_dir: Target module directory path
        overwrite: Allow overwriting existing module directory
        dry_run: Return planned files without writing

    Returns:
        Dict with: seed_status, module_dir, created_files, skipped_files,
                   coverage, warnings, blockers
    """
    validation = _validate_blueprint_for_seeding(blueprint)
    if not validation["valid"]:
        return {
            "seed_status": STATUS_SEED_REFUSED,
            "validation": validation,
            "module_dir": module_dir,
            "created_files": [],
            "skipped_files": [],
            "coverage": {},
            "warnings": validation.get("warnings", []),
            "blockers": validation.get("blockers", []),
        }

    module_path = Path(module_dir)

    if module_path.exists() and not overwrite and not dry_run:
        return {
            "seed_status": STATUS_SEED_REFUSED,
            "validation": {
                "valid": False,
                "reason": f"Module directory '{module_dir}' exists and overwrite=False",
            },
            "module_dir": module_dir,
            "created_files": [],
            "skipped_files": [],
            "coverage": {},
            "warnings": [],
            "blockers": [{
                "category": "directory_exists",
                "severity": "blocker",
                "message": f"Module directory '{module_dir}' already exists. Set overwrite=True to replace.",
            }],
        }

    module_name = blueprint.get("module", {}).get("title", "Unknown Module")
    module_id = _slugify(module_name)

    area_plan = blueprint.get("area_plan", [])
    location_roster = blueprint.get("location_roster", [])
    npc_roster = blueprint.get("npc_roster", [])
    plot_graph = blueprint.get("plot_graph", [])
    puzzle_graph = blueprint.get("puzzle_graph", [])
    clue_graph = blueprint.get("clue_graph", [])
    encounter_plan = blueprint.get("encounter_plan", [])
    item_roster = blueprint.get("item_roster", [])

    area_locations = _group_locations_by_area(area_plan, location_roster)
    area_ids: Dict[str, str] = {}
    for i, area_name in enumerate(area_locations.keys()):
        area_ids[area_name] = _generate_area_id(i)

    if dry_run:
        unassigned_npcs = _find_unassigned_npcs(npc_roster, location_roster)
        planned = _compute_planned_files(module_dir, area_ids, area_locations)
        unassigned_count = len(unassigned_npcs)
        coverage_counts = {
            "areas": len(area_ids),
            "locations": sum(len(v) for v in area_locations.values()),
            "npcs_in_roster": len(npc_roster),
            "npcs_assigned_to_locations": len(npc_roster) - unassigned_count,
            "plot_beats": len(plot_graph),
            "puzzles": len(puzzle_graph),
            "clues": len(clue_graph),
            "encounters_planned": len(encounter_plan),
            "items_planned": len(item_roster),
        }
        return {
            "seed_status": STATUS_SEED_PLANNED,
            "module_dir": module_dir,
            "created_files": [],
            "skipped_files": [],
            "planned_files": planned,
            "coverage": coverage_counts,
            "warnings": _gather_seed_warnings(blueprint, unassigned_npcs),
            "blockers": [],
        }

    os.makedirs(str(module_path / "areas"), exist_ok=True)
    os.makedirs(str(module_path / "monsters"), exist_ok=True)

    created_files: List[str] = []
    skipped_files: List[Dict[str, Any]] = []

    context = _build_module_context(
        module_name, module_id, area_ids, area_locations,
        location_roster, npc_roster, plot_graph, area_plan,
        blueprint,
    )
    _safe_write_json(module_path / "module_context.json", context, created_files, skipped_files)
    _safe_write_json(module_path / "module_context_BU.json", context, created_files, skipped_files)

    plot_data = _build_module_plot(blueprint, plot_graph, area_ids, area_locations)
    _safe_write_json(module_path / "module_plot.json", plot_data, created_files, skipped_files)
    _safe_write_json(module_path / "module_plot_BU.json", plot_data, created_files, skipped_files)

    party_tracker_bu = _build_party_tracker_backup(module_name, area_ids, area_locations)
    _safe_write_json(module_path / "party_tracker_BU.json", party_tracker_bu, created_files, skipped_files)

    npc_loc_map = _build_npc_location_map(npc_roster, location_roster)
    for area_name, loc_entries in area_locations.items():
        area_id = area_ids.get(area_name, "")
        if not area_id:
            continue
        area_file = _build_area_file(
            area_id, area_name, loc_entries, location_roster,
            npc_loc_map, plot_graph,
        )
        _safe_write_json(module_path / "areas" / f"{area_id}_BU.json", area_file, created_files, skipped_files)
        _safe_write_json(module_path / "areas" / f"{area_id}.json", area_file, created_files, skipped_files)

        map_file = _build_map_file(area_file)
        if map_file:
            _safe_write_json(module_path / f"map_{area_id}.json", map_file, created_files, skipped_files)

    # Build and write seed support artifacts
    npcs_seed_data = _build_npcs_seed(blueprint, npc_roster)
    _safe_write_json(module_path / "npcs_seed.json", npcs_seed_data, created_files, skipped_files)

    monsters_seed_data = _build_monsters_seed(blueprint, location_roster, encounter_plan)
    _safe_write_json(module_path / "monsters_seed.json", monsters_seed_data, created_files, skipped_files)

    seed_source_report_data = _build_seed_source_report(
        blueprint, area_plan, location_roster, npc_roster,
        plot_graph, puzzle_graph, clue_graph, encounter_plan, item_roster,
    )
    _safe_write_json(module_path / "seed_source_report.json", seed_source_report_data, created_files, skipped_files)

    unassigned_npcs = _find_unassigned_npcs(npc_roster, location_roster)
    unassigned_count = len(unassigned_npcs)

    # Classify required vs optional write failures
    created_set = set(created_files)
    skipped_paths = {str(s["path"]) for s in skipped_files}

    # Build complete required write list
    required_writes: List[str] = []

    # Required: core context/plot files
    for fn in ("module_context.json", "module_context_BU.json",
               "module_plot.json", "module_plot_BU.json", "party_tracker_BU.json",
               "npcs_seed.json", "monsters_seed.json", "seed_source_report.json"):
        required_writes.append(fn)

    # Required: area files per area
    for area_id in area_ids.values():
        required_writes.append(f"areas/{area_id}_BU.json")
        required_writes.append(f"areas/{area_id}.json")
        required_writes.append(f"map_{area_id}.json")

    required_failed: List[Dict[str, Any]] = []
    optional_failed: List[Dict[str, Any]] = []
    for skip in skipped_files:
        spath = skip.get("path", "")
        sreason = skip.get("reason", "unknown error")
        is_required = any(spath.endswith("/" + r) for r in required_writes)
        entry = {"path": spath, "reason": sreason}
        if is_required:
            required_failed.append(entry)
        else:
            optional_failed.append(entry)

    seed_blockers: List[Dict[str, Any]] = []
    seed_warnings: List[Dict[str, Any]] = _gather_seed_warnings(blueprint, unassigned_npcs)

    if required_failed:
        for fail in required_failed:
            seed_blockers.append({
                "category": "required_write_failed",
                "severity": "blocker",
                "message": f"Required artifact write failed: {fail['path']} - {fail['reason']}",
            })
        seed_status = STATUS_SEED_FAILED
    elif optional_failed:
        for fail in optional_failed:
            seed_warnings.append({
                "category": "optional_write_failed",
                "severity": "warning",
                "message": f"Optional artifact write failed: {fail['path']} - {fail['reason']}",
            })
        seed_status = STATUS_SEED_DEGRADED
    else:
        seed_status = STATUS_SEED_SUCCESS

    return {
        "seed_status": seed_status,
        "module_dir": module_dir,
        "created_files": created_files,
        "skipped_files": skipped_files,
        "coverage": {
            "areas": len(area_ids),
            "locations": sum(len(v) for v in area_locations.values()),
            "npcs_in_roster": len(npc_roster),
            "npcs_assigned_to_locations": len(npc_roster) - unassigned_count,
            "plot_beats": len(plot_graph),
            "puzzles": len(puzzle_graph),
            "clues": len(clue_graph),
            "encounters_planned": len(encounter_plan),
            "items_planned": len(item_roster),
        },
        "warnings": seed_warnings,
        "blockers": seed_blockers,
    }
