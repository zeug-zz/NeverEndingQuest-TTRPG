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


_SPATIAL_REPORT_FILENAME = "spatial_repair_report.json"

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
