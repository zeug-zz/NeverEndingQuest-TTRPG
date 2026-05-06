# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Party tracker merge utilities for deterministic state updates.

This module provides testable helpers for merging updatePartyTracker
parameters into party tracker data with special handling for:
- Location keys (currentLocationId, etc.)
- Peaceful resolution markers (resolvedHostilesByLocation)
- Nested world conditions merge
"""

from typing import Dict, Any, Optional


_LOCATION_KEYS = {"currentLocationId", "currentLocation", "currentAreaId", "currentArea"}


class PartyTrackerMergeError(ValueError):
    """Raised when updatePartyTracker merge violates authority contracts."""

    def __init__(self, message: str, reason: str = "unsafe_same_module_location_write"):
        super().__init__(message)
        self.reason = reason


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _has_unsafe_same_module_location_write(
    current_party_data: Dict[str, Any],
    parameters: Dict[str, Any],
    current_module: Optional[str],
    allow_same_module_location_write: bool,
) -> bool:
    """Return True when updatePartyTracker attempts unsafe same-module location write."""
    if allow_same_module_location_write:
        return False
    if not isinstance(parameters, dict):
        return False
    if "currentLocationId" not in parameters:
        return False

    target_location_id = _safe_str(parameters.get("currentLocationId"))
    if not target_location_id:
        return False

    world_conditions = current_party_data.get("worldConditions", {})
    if not isinstance(world_conditions, dict):
        world_conditions = {}

    current_location_id = _safe_str(world_conditions.get("currentLocationId"))
    if current_location_id and current_location_id == target_location_id:
        return False

    active_module = _safe_str(current_module or current_party_data.get("module"))
    target_module = _safe_str(parameters.get("module"))
    if target_module and active_module and target_module != active_module:
        return False

    return True


def _merge_party_tracker_updates(
    current_party_data: Dict[str, Any],
    parameters: Dict[str, Any],
    *,
    current_module: Optional[str] = None,
    allow_same_module_location_write: bool = False,
) -> Dict[str, Any]:
    """
    Merge updatePartyTracker parameters into current party tracker data.
    
    Handles special keys and nested merges deterministically:
    - Location keys (currentLocationId, currentLocation, currentAreaId, currentArea) -> worldConditions
    - module -> top-level
    - resolvedHostilesByLocation -> worldConditions.resolvedHostilesByLocation (merged non-destructively)
    - worldConditions -> nested merge with special handling for resolvedHostilesByLocation
    - All other keys -> top-level
    
    Args:
        current_party_data: Current party tracker dictionary
        parameters: Parameters dict from updatePartyTracker action
        
    Returns:
        Updated party tracker dictionary
    """
    # TABLETOP MODE: Fail-closed guard for unsafe same-module location writes.
    if _has_unsafe_same_module_location_write(
        current_party_data,
        parameters,
        current_module,
        allow_same_module_location_write,
    ):
        raise PartyTrackerMergeError(
            "Unsafe same-module location update detected in updatePartyTracker. "
            "Use transitionLocation for same-module movement.",
            reason="unsafe_same_module_location_write",
        )

    # Update party tracker with all provided parameters
    for key, value in parameters.items():
        if key in _LOCATION_KEYS:
            if "worldConditions" not in current_party_data:
                current_party_data["worldConditions"] = {}
            current_party_data["worldConditions"][key] = value
        elif key == "module":
            current_party_data["module"] = value
        elif key == "resolvedHostilesByLocation":
            # Peaceful resolution markers for hostile locations (e.g., guardian parlay success)
            if "worldConditions" not in current_party_data:
                current_party_data["worldConditions"] = {}
            # Merge to preserve existing location markers
            existing = current_party_data["worldConditions"].get("resolvedHostilesByLocation", {})
            if isinstance(value, dict) and isinstance(existing, dict):
                existing.update(value)
                current_party_data["worldConditions"]["resolvedHostilesByLocation"] = existing
            else:
                current_party_data["worldConditions"]["resolvedHostilesByLocation"] = value
        elif key == "worldConditions":
            # Nested world conditions merge (non-destructive)
            if "worldConditions" not in current_party_data:
                current_party_data["worldConditions"] = {}
            if isinstance(value, dict):
                # Merge nested dict, preserving existing keys unless explicitly updated
                for wc_key, wc_value in value.items():
                    if wc_key == "resolvedHostilesByLocation" and isinstance(wc_value, dict):
                        # Special merge for location markers
                        existing_markers = current_party_data["worldConditions"].get("resolvedHostilesByLocation", {})
                        if isinstance(existing_markers, dict):
                            existing_markers.update(wc_value)
                            current_party_data["worldConditions"]["resolvedHostilesByLocation"] = existing_markers
                        else:
                            current_party_data["worldConditions"]["resolvedHostilesByLocation"] = wc_value
                    else:
                        current_party_data["worldConditions"][wc_key] = wc_value
            else:
                # Non-dict value replaces entirely (unexpected, but handled)
                current_party_data["worldConditions"] = value
        else:
            # Handle any other party tracker fields
            current_party_data[key] = value
    
    return current_party_data
