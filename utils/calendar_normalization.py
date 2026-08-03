#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Calendar Normalization Utility
Build-time normalization of party tracker calendar months in canonical
build artifacts (party_tracker_BU.json). Does NOT touch runtime party_tracker.json.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict

from utils.file_operations import safe_read_json, safe_write_json
from utils.enhanced_logger import info, warning, error

# Month conversion mapping from Forgotten Realms to SRD
# (local copy to avoid coupling with calendar_migration module internals)
MONTH_CONVERSION: Dict[str, str] = {
    "Hammer": "Firstmonth",
    "Alturiak": "Coldmonth",
    "Ches": "Thawmonth",
    "Tarsakh": "Springmonth",
    "Mirtul": "Bloommonth",
    "Kythorn": "Sunmonth",
    "Flamerule": "Heatmonth",
    "Eleasis": "Harvestmonth",
    "Eleint": "Autumnmonth",
    "Marpenoth": "Fademonth",
    "Uktar": "Frostmonth",
    "Nightal": "Yearend",
}

# Schema-valid game months (local copy to avoid cross-module coupling)
VALID_GAME_MONTHS: Dict[str, str] = {
    "Firstmonth", "Coldmonth", "Thawmonth", "Springmonth",
    "Bloommonth", "Sunmonth", "Heatmonth", "Harvestmonth",
    "Autumnmonth", "Fademonth", "Frostmonth", "Yearend",
}


def normalize_party_calendar(module_dir: str) -> Dict[str, Any]:
    """Normalize party tracker calendar values in canonical build artifacts.

    Targets party_tracker_BU.json (canonical backup), NOT party_tracker.json
    (runtime). Uses MONTH_CONVERSION to map known invalid months to schema-valid
    values. Unknown invalid months fail closed with a diagnostic.

    Args:
        module_dir: Absolute or relative path to the module directory.

    Returns:
        Dictionary with normalization result:
        {
            "timestamp": ISO format timestamp,
            "status": "pass" | "changed" | "failed" | "skipped",
            "month_before": str | None,
            "month_after": str | None,
            "reason": str,
            "artifact_path": str,
        }
    """
    artifact_path = os.path.join(module_dir, "party_tracker_BU.json")
    timestamp = datetime.now(timezone.utc).isoformat()

    # Artifact does not exist -> skipped
    if not os.path.isfile(artifact_path):
        return {
            "timestamp": timestamp,
            "status": "skipped",
            "month_before": None,
            "month_after": None,
            "reason": "party_tracker_BU_missing",
            "artifact_path": artifact_path,
        }

    party_data = safe_read_json(artifact_path)
    if not party_data or not isinstance(party_data, dict):
        return {
            "timestamp": timestamp,
            "status": "failed",
            "month_before": None,
            "month_after": None,
            "reason": "invalid_BU_file",
            "artifact_path": artifact_path,
        }

    world_conditions = party_data.get("worldConditions")
    if not world_conditions or not isinstance(world_conditions, dict):
        return {
            "timestamp": timestamp,
            "status": "failed",
            "month_before": None,
            "month_after": None,
            "reason": "worldConditions_missing",
            "artifact_path": artifact_path,
        }

    raw_month = world_conditions.get("month")

    # Non-string month -> fail closed
    if raw_month is not None and not isinstance(raw_month, str):
        error(
            f"party_tracker_BU.json month is not a string: {type(raw_month).__name__}",
            category="calendar_normalization",
        )
        return {
            "timestamp": timestamp,
            "status": "failed",
            "month_before": str(raw_month) if raw_month is not None else None,
            "month_after": None,
            "reason": "non_string_month",
            "artifact_path": artifact_path,
        }

    month_str = raw_month.strip() if raw_month else ""

    # Empty or missing month -> default to Firstmonth
    if not month_str:
        info(
            "party_tracker_BU.json month is empty, defaulting to Firstmonth",
            category="calendar_normalization",
        )
        world_conditions["month"] = "Firstmonth"
        if safe_write_json(artifact_path, party_data):
            return {
                "timestamp": timestamp,
                "status": "changed",
                "month_before": month_str or None,
                "month_after": "Firstmonth",
                "reason": "empty_month_defaulted",
                "artifact_path": artifact_path,
            }
        else:
            return {
                "timestamp": timestamp,
                "status": "failed",
                "month_before": month_str or None,
                "month_after": None,
                "reason": "write_failed",
                "artifact_path": artifact_path,
            }

    # Already valid -> skipped
    if month_str in VALID_GAME_MONTHS:
        return {
            "timestamp": timestamp,
            "status": "skipped",
            "month_before": month_str,
            "month_after": month_str,
            "reason": "month_already_valid",
            "artifact_path": artifact_path,
        }

    # Known invalid month -> normalize
    if month_str in MONTH_CONVERSION:
        new_month = MONTH_CONVERSION[month_str]
        world_conditions["month"] = new_month
        if safe_write_json(artifact_path, party_data):
            info(
                f"Calendar normalized: {month_str} -> {new_month} in {artifact_path}",
                category="calendar_normalization",
            )
            return {
                "timestamp": timestamp,
                "status": "changed",
                "month_before": month_str,
                "month_after": new_month,
                "reason": "month_normalized",
                "artifact_path": artifact_path,
            }
        else:
            return {
                "timestamp": timestamp,
                "status": "failed",
                "month_before": month_str,
                "month_after": None,
                "reason": "write_failed",
                "artifact_path": artifact_path,
            }

    # Unknown invalid month -> fail closed
    warning(
        f"Unknown invalid month in {artifact_path}: '{month_str}'",
        category="calendar_normalization",
    )
    return {
        "timestamp": timestamp,
        "status": "failed",
        "month_before": month_str,
        "month_after": None,
        "reason": "unknown_invalid_month",
        "artifact_path": artifact_path,
    }
