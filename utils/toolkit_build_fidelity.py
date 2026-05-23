# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Build Fidelity Audit
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Artifact-only build fidelity audit helpers for accurate-ingest workspaces.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from model_config import ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES
from utils.toolkit_homebrew_upload_contract import (
    get_workspace_files,
    load_json_artifact,
    load_source_graph_artifact,
    load_builder_blueprint_artifact,
    load_builder_blueprint_report_artifact,
    load_normalized_packet_artifact,
)

MAX_ATOM_FINDINGS = 3
ATOM_CATEGORY_KEYS = {
    "npc",
    "location",
    "plot_beat",
    "puzzle",
    "clue",
    "encounter",
    "item",
}

# Categories with deterministic module-level artifacts that can be verified.
_VERIFIABLE_CATEGORIES = {
    "npc",
    "location",
    "plot_beat",
}


def is_build_fidelity_required(workspace: Path) -> bool:
    """Return true when accurate-ingest build fidelity gates apply."""
    if not ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES:
        return False
    ws = Path(workspace)
    files = get_workspace_files(ws)
    source_graph = files.get("source_graph")
    blueprint = files.get("builder_blueprint")
    return bool(
        (source_graph and source_graph.exists())
        or (blueprint and blueprint.exists())
    )


def _find_required_atoms(source_graph: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Extract required atoms from source graph, grouped by category."""
    atoms: Dict[str, List[Dict[str, Any]]] = {}
    for raw in source_graph.get("atoms") or []:
        if not isinstance(raw, dict):
            continue
        atom_type = str(raw.get("type") or "").strip().lower()
        if atom_type in ATOM_CATEGORY_KEYS:
            atoms.setdefault(atom_type, []).append(raw)
    return atoms


def _find_blueprint_required(
    blueprint: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """Extract required NPCs, locations from blueprint."""
    required: Dict[str, List[Dict[str, Any]]] = {}
    npc_roster = blueprint.get("npc_roster") or []
    required["npc"] = [n for n in npc_roster if isinstance(n, dict)]
    area_plan = blueprint.get("area_plan") or []
    required["location"] = []
    for area in area_plan:
        if not isinstance(area, dict):
            continue
        for loc in area.get("location_roster") or []:
            if isinstance(loc, dict):
                required["location"].append(loc)
    plot_graph = blueprint.get("plot_graph") or []
    if isinstance(plot_graph, dict):
        beats = plot_graph.get("beats") or []
    elif isinstance(plot_graph, list):
        beats = plot_graph
    else:
        beats = []
    required["plot_beat"] = [b for b in beats if isinstance(b, dict)]
    return required


def _normalize_name(name: str) -> str:
    """Normalize a character/NPC name for comparison."""
    return name.strip().lower().replace(" ", "_").replace("-", "_").rstrip(",:;.!?")


def _scan_module_areas(
    module_dir: Path,
) -> Dict[str, List[Dict[str, Any]]]:
    """Scan generated module directory for areas, NPCs, monsters."""
    result: Dict[str, List[Dict[str, Any]]] = {
        "areas": [],
        "npcs": [],
        "monsters": [],
    }
    areas_dir = module_dir / "areas"
    monsters_dir = module_dir / "monsters"
    characters_dir = module_dir / "characters"

    if areas_dir.is_dir():
        for path in sorted(areas_dir.iterdir()):
            if path.suffix == ".json" and path.is_file():
                try:
                    data = load_json_artifact(path)
                    result["areas"].append(data)
                except Exception:
                    pass

    for src_dir, key in [(monsters_dir, "monsters"), (characters_dir, "npcs")]:
        if src_dir.is_dir():
            for path in sorted(src_dir.iterdir()):
                if path.suffix == ".json" and path.is_file():
                    try:
                        data = load_json_artifact(path)
                        result[key].append(data)
                    except Exception:
                        pass

    # Also collect NPCs defined inline in area locations[].npcs.
    # Current modules store NPCs primarily in this form rather than
    # standalone character JSON files.
    seen_npc_names: Set[str] = set()
    for area in result["areas"]:
        for loc in area.get("locations") or []:
            for npc in loc.get("npcs") or []:
                if not isinstance(npc, dict):
                    continue
                name = str(npc.get("name") or "").strip()
                if not name:
                    continue
                lower_name = name.strip().lower()
                if lower_name not in seen_npc_names:
                    seen_npc_names.add(lower_name)
                    result["npcs"].append(npc)

    # Scan module_context.npcs for structured NPC entries (seed writer output).
    ctx_path = module_dir / "module_context.json"
    if ctx_path.is_file():
        try:
            ctx = load_json_artifact(ctx_path)
            for npc_key, npc_val in (ctx.get("npcs") or {}).items():
                if not isinstance(npc_val, dict):
                    continue
                name = str(npc_val.get("name") or "").strip()
                if not name:
                    continue
                lower_name = name.strip().lower()
                if lower_name not in seen_npc_names:
                    seen_npc_names.add(lower_name)
                    result["npcs"].append(npc_val)
        except Exception:
            pass

    # Scan npcs_seed.json for structured NPC entries.
    seed_path = module_dir / "npcs_seed.json"
    if seed_path.is_file():
        try:
            seed = load_json_artifact(seed_path)
            for npc in (seed.get("npcs") or []) or []:
                if not isinstance(npc, dict):
                    continue
                name = str(npc.get("name") or "").strip()
                if not name:
                    continue
                lower_name = name.strip().lower()
                if lower_name not in seen_npc_names:
                    seen_npc_names.add(lower_name)
                    result["npcs"].append(npc)
        except Exception:
            pass

    return result


def _check_atoms_vs_module(
    category: str,
    required_atoms: List[Dict[str, Any]],
    module_data: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compare required source atoms against generated module content.

    Returns (blockers, warnings).
    """
    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    found_count = 0
    total_count = len(required_atoms)

    if total_count == 0:
        return blockers, warnings

    for atom in required_atoms:
        name = atom.get("name") or atom.get("label") or ""
        if not name:
            continue
        normalized = _normalize_name(str(name))
        atom_id = atom.get("source_atom_id") or ""
        criticality = str(atom.get("criticality") or "required").lower()

        matched = False
        if category == "npc":
            for npc in module_data.get("npcs", []):
                npc_name = str(
                    npc.get("name")
                    or npc.get("character_name")
                    or npc.get("fileName")
                    or ""
                )
                if _normalize_name(npc_name) == normalized:
                    matched = True
                    break
            if not matched:
                for mon in module_data.get("monsters", []):
                    mon_name = str(mon.get("name") or mon.get("fileName") or "")
                    if _normalize_name(mon_name) == normalized:
                        matched = True
                        break
        elif category == "location":
            for area in module_data.get("areas", []):
                area_id = str(area.get("areaId") or "")
                area_name = str(area.get("areaName") or "")
                if _normalize_name(area_id) == normalized or _normalize_name(
                    area_name
                ) == normalized:
                    matched = True
                    break
                for loc in area.get("locations") or []:
                    loc_name = str(loc.get("name") or loc.get("locationId") or "")
                    if _normalize_name(loc_name) == normalized:
                        matched = True
                        break
        elif category == "plot_beat":
            plot_path = module_data.get("plot_path")
            if plot_path and plot_path.exists():
                try:
                    plot_data = json.loads(plot_path.read_text(encoding="utf-8"))
                    for beat in plot_data.get("plotPoints") or plot_data.get(
                        "beats"
                    ) or []:
                        beat_name = str(
                            beat.get("name")
                            or beat.get("title")
                            or beat.get("label")
                            or ""
                        )
                        if _normalize_name(beat_name) == normalized:
                            matched = True
                            break
                except Exception:
                    pass

        if matched:
            found_count += 1
        else:
            if criticality == "advisory":
                warnings.append(
                    {
                        "category": category,
                        "message": f"Advisory {category} '{name}' not found in module",
                        "source_atom_id": atom_id,
                    }
                )
            else:
                blockers.append(
                    {
                        "category": category,
                        "message": f"Required {category} '{name}' not found in module",
                        "source_atom_id": atom_id,
                    }
                )

    return blockers, warnings


def _build_coverage(
    required: Dict[str, List[Dict[str, Any]]],
    blockers: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    module_data: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build coverage section of the report."""
    coverage: Dict[str, Any] = {}
    for cat in ATOM_CATEGORY_KEYS:
        req_list = required.get(cat) or []
        total = len(req_list)
        missing_blockers = sum(
            1 for b in blockers if b.get("category") == cat
        )
        missing_warnings = sum(
            1 for w in warnings if w.get("category") == cat
        )
        present = total - missing_blockers - missing_warnings
        coverage[cat] = {
            "found": present,
            "total": total,
        }
    coverage["areas_generated"] = len(module_data.get("areas", []))
    coverage["npcs_generated"] = len(module_data.get("npcs", []))
    coverage["monsters_generated"] = len(module_data.get("monsters", []))
    return coverage


def build_build_fidelity_report(
    workspace: Path,
    module_dir: Path,
) -> Dict[str, Any]:
    """Return artifact-only report comparing generated module to source/blueprint artifacts."""
    ws = Path(workspace)
    md = Path(module_dir)
    files = get_workspace_files(ws)

    source_graph = load_source_graph_artifact(ws)
    blueprint = load_builder_blueprint_artifact(ws)
    blueprint_report = load_builder_blueprint_report_artifact(ws)
    packet = load_normalized_packet_artifact(ws)

    source_artifacts: Dict[str, Any] = {
        "source_graph": str(files.get("source_graph", "")),
        "source_graph_exists": bool(
            files.get("source_graph") and files["source_graph"].exists()
        ),
        "builder_blueprint": str(files.get("builder_blueprint", "")),
        "builder_blueprint_exists": bool(
            files.get("builder_blueprint") and files["builder_blueprint"].exists()
        ),
        "builder_blueprint_report": str(files.get("builder_blueprint_report", "")),
        "builder_blueprint_report_exists": bool(
            files.get("builder_blueprint_report")
            and files["builder_blueprint_report"].exists()
        ),
        "normalized_packet": str(files.get("normalized_packet", "")),
        "normalized_packet_exists": bool(
            files.get("normalized_packet") and files["normalized_packet"].exists()
        ),
        "module_dir": str(md),
        "module_dir_exists": md.is_dir(),
    }

    if not source_artifacts["source_graph_exists"] and not source_artifacts["builder_blueprint_exists"]:
        return {
            "version": 1,
            "status": "legacy",
            "module_path": str(md),
            "source_artifacts": source_artifacts,
            "coverage": {},
            "blockers": [],
            "warnings": [],
            "stage_results": {},
            "can_continue": True,
            "refusal_reason": "",
        }

    if not md.is_dir():
        return {
            "version": 1,
            "status": "failed",
            "module_path": str(md),
            "source_artifacts": source_artifacts,
            "coverage": {},
            "blockers": [
                {
                    "category": "module",
                    "message": f"Generated module directory not found: {md}",
                }
            ],
            "warnings": [],
            "stage_results": {},
            "can_continue": False,
            "refusal_reason": "module_dir_missing",
        }

    required: Dict[str, List[Dict[str, Any]]] = {}

    if source_graph:
        required = _find_required_atoms(source_graph)

    if blueprint:
        bp_req = _find_blueprint_required(blueprint)
        for cat, items in bp_req.items():
            existing = required.setdefault(cat, [])
            existing_names = {_normalize_name(str(r.get("name") or "")) for r in existing}
            for item in items:
                item_name = _normalize_name(str(item.get("name") or item.get("label") or ""))
                if item_name and item_name not in existing_names:
                    existing.append(item)
                    existing_names.add(item_name)

    module_data = _scan_module_areas(md)
    module_data["plot_path"] = md / "module_plot.json"

    all_blockers: List[Dict[str, Any]] = []
    all_warnings: List[Dict[str, Any]] = []

    for cat in _VERIFIABLE_CATEGORIES:
        req_list = required.get(cat) or []
        if not req_list:
            continue
        b, w = _check_atoms_vs_module(cat, req_list, module_data)
        all_blockers.extend(b)
        all_warnings.extend(w)

    # Non-verifiable categories (puzzle, clue, encounter, item): emit advisory warnings
    # when deterministic module-level artifacts do not yet exist for comparison.
    for cat in ATOM_CATEGORY_KEYS:
        if cat in _VERIFIABLE_CATEGORIES:
            continue
        req_list = required.get(cat) or []
        for atom in req_list:
            name = atom.get("name") or atom.get("label") or ""
            if name:
                all_warnings.append(
                    {
                        "category": cat,
                        "message": f"Source {cat} '{name}' could not be verified against module artifacts",
                        "source_atom_id": atom.get("source_atom_id") or "",
                    }
                )

    coverage = _build_coverage(
        required, all_blockers, all_warnings, module_data
    )

    # Determine status
    if all_blockers:
        status = "blocked"
        refusal_reason = "; ".join(
            str(b.get("message", "")) for b in all_blockers[:3]
        )
        can_continue = False
    elif source_artifacts.get("source_graph_exists") and not source_graph:
        status = "failed"
        refusal_reason = "source_graph_load_failed"
        can_continue = False
    elif source_artifacts.get("builder_blueprint_exists") and not blueprint:
        status = "failed"
        refusal_reason = "builder_blueprint_load_failed"
        can_continue = False
    elif all_warnings:
        status = "degraded"
        refusal_reason = ""
        can_continue = True
    else:
        status = "pass"
        refusal_reason = ""
        can_continue = True

    return {
        "version": 1,
        "status": status,
        "module_path": str(md),
        "source_artifacts": source_artifacts,
        "coverage": coverage,
        "blockers": all_blockers[:MAX_ATOM_FINDINGS * 4],
        "warnings": all_warnings[:MAX_ATOM_FINDINGS * 4],
        "stage_results": {
            "areas_count": len(module_data.get("areas", [])),
            "npcs_count": len(module_data.get("npcs", [])),
            "monsters_count": len(module_data.get("monsters", [])),
        },
        "can_continue": can_continue,
        "refusal_reason": refusal_reason,
    }


def can_continue_after_build_fidelity(
    report: Dict[str, Any],
) -> Tuple[bool, str]:
    """Return whether finishing/publication can continue."""
    status = str(report.get("status") or "").lower()
    if status in {"blocked", "failed"}:
        return False, str(
            report.get("refusal_reason") or f"build_fidelity_{status}"
        )
    blockers = report.get("blockers") or []
    if blockers:
        return False, str(report.get("refusal_reason") or "blockers_present")
    return True, ""


def build_source_fidelity_rollup(
    workspace: Path,
    build_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Return final source fidelity rollup across normalization, blueprint, and build phases."""
    ws = Path(workspace)
    files = get_workspace_files(ws)

    normalization_fidelity_status = "unknown"
    normalization_fidelity_path = str(files.get("normalization_fidelity_report", ""))
    if files.get("normalization_fidelity_report") and files[
        "normalization_fidelity_report"
    ].exists():
        try:
            nfr = load_json_artifact(str(files["normalization_fidelity_report"]))
            normalization_fidelity_status = str(
                nfr.get("status") or "unknown"
            ).lower()
        except Exception:
            normalization_fidelity_status = "load_failed"

    blueprint_status = "unknown"
    blueprint_path = str(files.get("builder_blueprint_report", ""))
    if files.get("builder_blueprint_report") and files[
        "builder_blueprint_report"
    ].exists():
        try:
            bpr = load_json_artifact(str(files["builder_blueprint_report"]))
            blueprint_status = str(
                bpr.get("blueprint_status") or bpr.get("status") or "unknown"
            ).lower()
        except Exception:
            blueprint_status = "load_failed"

    build_status = str(build_report.get("status") or "unknown").lower()
    build_fidelity_path = str(files.get("build_fidelity_report", ""))

    final_blocker_count = len(build_report.get("blockers") or [])
    final_warning_count = len(build_report.get("warnings") or [])
    coverage = build_report.get("coverage") or {}
    source_artifact_paths = build_report.get("source_artifacts") or {}

    def _rollup_continue_ok(s: str) -> bool:
        return s in {"pass", "degraded", "legacy", "disabled", "clean", "repaired"}

    all_ok = (
        _rollup_continue_ok(normalization_fidelity_status)
        and _rollup_continue_ok(blueprint_status)
        and _rollup_continue_ok(build_status)
        and final_blocker_count == 0
    )

    if not all_ok:
        rollup_status = "blocked"
    elif final_warning_count > 0:
        rollup_status = "degraded"
    else:
        rollup_status = "pass"

    return {
        "status": rollup_status,
        "normalization_fidelity": {
            "status": normalization_fidelity_status,
            "path": normalization_fidelity_path,
        },
        "blueprint": {
            "status": blueprint_status,
            "path": blueprint_path,
        },
        "build_fidelity": {
            "status": build_status,
            "path": build_fidelity_path,
        },
        "final_blocker_count": final_blocker_count,
        "final_warning_count": final_warning_count,
        "coverage": coverage,
        "source_artifact_paths": source_artifact_paths,
    }


__all__ = [
    "is_build_fidelity_required",
    "build_build_fidelity_report",
    "can_continue_after_build_fidelity",
    "build_source_fidelity_rollup",
]
