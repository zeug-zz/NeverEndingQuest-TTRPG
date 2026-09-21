# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Spatial Repair Utility
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Deterministic spatial repair helper that recomputes coordinates, cardinal
adjacency, map links, and area connectivity from finalized location artifacts.
Wraps scripts.remediate_module_coordinates with a clean API and compact report.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Ensure repo root is in sys.path for imports from scripts/
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.remediate_module_coordinates import remediate_module
from utils.enhanced_logger import info, warning, error
from utils.file_operations import safe_write_json
from utils.spatial_contract import is_valid_coordinate, parse_coordinate


_SPATIAL_REPORT_FILENAME = "spatial_repair_report.json"
_ADAPTATION_SPATIAL_REPORT_FILENAME = "adaptation_spatial_convergence_report.json"

_BACKUP_EXCLUDED_TOKENS = ("_BU.json", ".bak", ".backup", ".tmp", "_backup.json")


def _is_backup_file(path: Path) -> bool:
    """Return True if the file path matches known backup/exclusion patterns."""
    name = path.name
    return any(token in name for token in _BACKUP_EXCLUDED_TOKENS)


def _count_input_locations(module_dir: Path) -> int:
    """Count total locations across all active area files in the module."""
    areas_dir = module_dir / "areas"
    if not areas_dir.exists():
        return 0

    total = 0
    for area_path in sorted(areas_dir.glob("*.json")):
        if _is_backup_file(area_path):
            continue
        try:
            with open(area_path, "r", encoding="utf-8") as handle:
                area_data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            warning(
                f"SPATIAL_REPAIR: Cannot parse {area_path.name}: {exc}",
                category="spatial_repair",
            )
            continue
        if not isinstance(area_data, dict):
            continue
        locations = area_data.get("locations")
        if isinstance(locations, list):
            total += len(locations)
    return total


def _count_connectivity_edges(module_dir: Path) -> int:
    """Count total connectivity edges across all locations in all active area files."""
    areas_dir = module_dir / "areas"
    if not areas_dir.exists():
        return 0

    total = 0
    for area_path in sorted(areas_dir.glob("*.json")):
        if _is_backup_file(area_path):
            continue
        try:
            with open(area_path, "r", encoding="utf-8") as handle:
                area_data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            warning(
                f"SPATIAL_REPAIR: Cannot parse {area_path.name} for edge count: {exc}",
                category="spatial_repair",
            )
            continue
        if not isinstance(area_data, dict):
            continue
        locations = area_data.get("locations")
        if not isinstance(locations, list):
            continue
        for location in locations:
            if not isinstance(location, dict):
                continue
            connectivity = location.get("connectivity")
            if isinstance(connectivity, list):
                total += len(connectivity)
    return total


def _utc_now_iso() -> str:
    """Return UTC timestamp in ISO-8601 format."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def repair_module_spatial(module_dir: str) -> Dict[str, Any]:
    """Repair spatial representation for a module directory.

    Recomputes coordinates, cardinal adjacency, map links, and area
    connectivity consistency from finalized location artifacts.

    Delegates to scripts.remediate_module_coordinates.remediate_module
    with force_relayout=True, then produces a compact audit report.

    Returns:
        {
            "timestamp": ISO timestamp,
            "status": "pass" | "changed" | "failed",
            "input_location_count": int,
            "repaired_area_count": int,
            "edge_count": int,
            "unresolved_count": int,
            "details": {
                "processed": int,
                "changed": int,
                "errors": [str],
            }
        }
    """
    module_path = Path(module_dir)
    info(
        f"SPATIAL_REPAIR: Starting spatial repair for {module_path.name}",
        category="spatial_repair",
    )

    # Capture input state before repair
    input_location_count = _count_input_locations(module_path)
    edge_count = _count_connectivity_edges(module_path)

    # Run remediation with force_relayout=True, apply=True
    remediation = remediate_module(
        module_path=module_path,
        apply=True,
        force_relayout=True,
    )

    processed = int(remediation.get("processed", 0) or 0)
    changed = int(remediation.get("changed", 0) or 0)
    errors: List[str] = remediation.get("errors") or []
    unresolved_count = len(errors)

    # Determine status
    if unresolved_count > 0:
        status = "failed"
    elif changed > 0:
        status = "changed"
    else:
        status = "pass"

    report: Dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "status": status,
        "input_location_count": input_location_count,
        "repaired_area_count": changed,
        "edge_count": edge_count,
        "unresolved_count": unresolved_count,
        "details": {
            "processed": processed,
            "changed": changed,
            "errors": errors,
        },
    }

    # Persist report to module directory
    report_path = module_path / _SPATIAL_REPORT_FILENAME
    write_ok = safe_write_json(str(report_path), report)
    if write_ok:
        info(
            f"SPATIAL_REPAIR: Report written to {report_path}",
            category="spatial_repair",
        )
    else:
        warning(
            f"SPATIAL_REPAIR: Failed to write report to {report_path}",
            category="spatial_repair",
        )

    info(
        f"SPATIAL_REPAIR: status={status} locations={input_location_count} "
        f"repaired={changed} edges={edge_count} unresolved={unresolved_count}",
        category="spatial_repair",
    )

    return report


def _adaptation_staging_path(module_dir: Path) -> bool:
    """Return True for a project-local staging target, never a live module."""
    resolved = module_dir.resolve()
    parts = set(resolved.parts)
    return "modules" not in parts and not module_dir.is_symlink()


def _logical_targets(location: Dict[str, Any]) -> List[str]:
    """Read the existing logical connectivity contract without inventing one."""
    values = location.get("areaConnectivityId")
    if not isinstance(values, list):
        return []
    return sorted({value.strip() for value in values if isinstance(value, str) and value.strip()})


def normalize_adaptation_spatial_topology(module_dir: str) -> Dict[str, Any]:
    """Normalize adaptation map edges without changing legacy spatial repair.

    Non-cardinal map edges are reclassified only when the paired area already
    declares the same relationship through ``areaConnectivityId``.  All other
    malformed or unsafe edges remain in the input files and are reported as
    blockers.  Successful writes are limited to a non-live staging directory.
    """
    module_path = Path(module_dir)
    report: Dict[str, Any] = {
        "contract_version": "adaptation_spatial_convergence.v1",
        "status": "blocked",
        "changed_files": [],
        "changed_edges": [],
        "blockers": [],
        "preserved_edge_count": 0,
    }
    if not _adaptation_staging_path(module_path):
        report["blockers"] = [{"code": "live_module_path_forbidden", "path": str(module_path)}]
        return report

    area_dir = module_path / "areas"
    if not area_dir.is_dir():
        report["blockers"] = [{"code": "areas_directory_missing"}]
        return report

    pending: List[tuple[Path, Dict[str, Any], Path, Dict[str, Any]]] = []
    for map_path in sorted(module_path.glob("map_*.json")):
        if _is_backup_file(map_path):
            continue
        area_path = area_dir / f"{map_path.stem[4:]}.json"
        try:
            map_data = json.loads(map_path.read_text(encoding="utf-8"))
            area_data = json.loads(area_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report["blockers"].append({"code": "malformed_topology_artifact", "file": map_path.name, "detail": str(exc)[:160]})
            continue
        if not isinstance(map_data, dict) or not isinstance(area_data, dict):
            report["blockers"].append({"code": "topology_payload_not_object", "file": map_path.name})
            continue
        rooms = map_data.get("rooms")
        locations = area_data.get("locations")
        if not isinstance(rooms, list) or not isinstance(locations, list):
            report["blockers"].append({"code": "topology_collection_malformed", "file": map_path.name})
            continue
        location_index = {
            item.get("locationId"): item
            for item in locations
            if isinstance(item, dict) and isinstance(item.get("locationId"), str)
        }
        room_ids = set(location_index)
        for room in rooms:
            if not isinstance(room, dict) or not isinstance(room.get("id"), str):
                report["blockers"].append({"code": "map_room_malformed", "file": map_path.name})
                continue
            source = room["id"]
            connections = room.get("connections")
            if connections is None:
                continue
            if not isinstance(connections, list):
                report["blockers"].append({"code": "map_connections_malformed", "file": map_path.name, "source": source})
                continue
            source_location = location_index.get(source)
            if source_location is None:
                report["blockers"].append({"code": "map_room_unknown", "file": map_path.name, "source": source})
                continue
            source_coordinate = parse_coordinate(room.get("coordinates")) if is_valid_coordinate(room.get("coordinates")) else None
            for target in list(connections):
                edge = {"file": map_path.name, "source": source, "target": target}
                if not isinstance(target, str) or not target.strip() or target not in room_ids:
                    report["blockers"].append({**edge, "code": "non_repairable_map_edge"})
                    continue
                target_room = next((item for item in rooms if isinstance(item, dict) and item.get("id") == target), None)
                target_coordinate = parse_coordinate(target_room.get("coordinates")) if target_room and is_valid_coordinate(target_room.get("coordinates")) else None
                if source_coordinate is not None and target_coordinate is not None and abs(source_coordinate[0] - target_coordinate[0]) + abs(source_coordinate[1] - target_coordinate[1]) == 1:
                    report["preserved_edge_count"] += 1
                    continue
                target_location = location_index.get(target, {})
                declared = target in _logical_targets(source_location) or source in _logical_targets(target_location)
                if not declared:
                    report["blockers"].append({**edge, "code": "ambiguous_non_cardinal_edge"})
                    continue
                report["changed_edges"].append({**edge, "classification": "logical_area_connection", "reason_code": "authored_areaConnectivityId"})
                connections.remove(target)
                if target not in _logical_targets(source_location):
                    source_location.setdefault("areaConnectivityId", []).append(target)
                report["preserved_edge_count"] += 1
        pending.append((map_path, map_data, area_path, area_data))

    report["changed_edges"] = sorted(report["changed_edges"], key=lambda item: (item["file"], item["source"], item["target"]))
    report["blockers"] = sorted(report["blockers"], key=lambda item: (item.get("file", ""), item.get("source", ""), item.get("target", ""), item["code"]))
    if report["blockers"]:
        report["status"] = "blocked"
    else:
        report["status"] = "changed" if report["changed_edges"] else "pass"
        for map_path, map_data, area_path, area_data in pending:
            if any(edge["file"] == map_path.name for edge in report["changed_edges"]):
                if not safe_write_json(str(area_path), area_data, create_backup=False):
                    report["blockers"].append({"code": "staging_write_failed", "file": area_path.name})
                    continue
                if not safe_write_json(str(map_path), map_data, create_backup=False):
                    report["blockers"].append({"code": "staging_write_failed", "file": map_path.name})
                    continue
                report["changed_files"].extend([area_path.name, map_path.name])
    report["changed_files"] = sorted(set(report["changed_files"]))
    report_path = module_path / _ADAPTATION_SPATIAL_REPORT_FILENAME
    if not safe_write_json(str(report_path), report, create_backup=False):
        report["status"] = "failed"
        report["blockers"].append({"code": "spatial_report_write_failed"})
    return report
