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
    for area_name, area_id in area_ids.items():
        count = len(area_locations.get(area_name, []))
        files.append({"path": str(base / "areas" / f"{area_id}_BU.json"), "purpose": f"area {area_name} with {count} locations"})
        files.append({"path": str(base / "areas" / f"{area_id}.json"), "purpose": f"runtime area {area_name}"})
        files.append({"path": str(base / f"map_{area_id}.json"), "purpose": f"map for area {area_name}"})
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

    return {
        "module_name": module_name,
        "module_id": module_id,
        "areas": areas,
        "npcs": npcs_dict,
        "locations": locations_dict,
        "plot_scopes": plot_scopes,
        "references": references,
    }


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

        # Determine connectivity from location_roster source refs
        connectivity: List[str] = []
        atom_id = loc_entry.get("atom_id", "")
        if atom_id:
            for other in location_roster:
                oid = other.get("atom_id", "")
                oname = other.get("display_name", "")
                if oid != atom_id and oname:
                    connectivity.append(oname)

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
    )
    _safe_write_json(module_path / "module_context.json", context, created_files, skipped_files)
    _safe_write_json(module_path / "module_context_BU.json", context, created_files, skipped_files)

    plot_data = _build_module_plot(blueprint, plot_graph, area_ids, area_locations)
    _safe_write_json(module_path / "module_plot.json", plot_data, created_files, skipped_files)
    _safe_write_json(module_path / "module_plot_BU.json", plot_data, created_files, skipped_files)

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

    unassigned_npcs = _find_unassigned_npcs(npc_roster, location_roster)
    unassigned_count = len(unassigned_npcs)

    return {
        "seed_status": STATUS_SEED_SUCCESS,
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
        "warnings": _gather_seed_warnings(blueprint, unassigned_npcs),
        "blockers": [],
    }
