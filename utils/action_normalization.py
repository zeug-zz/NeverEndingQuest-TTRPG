# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Action Authority Normalization
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Normalizes narrator action lists before runtime processing to enforce
same-module location authority contracts.
"""

from typing import Any, Dict, List, Tuple


_LOCATION_KEYS = {
    "currentLocationId",
    "currentLocation",
    "currentAreaId",
    "currentArea",
}


def _safe_dict(value: Any) -> Dict[str, Any]:
    """Return value when dict, otherwise empty dict."""
    if isinstance(value, dict):
        return value
    return {}


def _safe_str(value: Any) -> str:
    """Return stripped string value."""
    return str(value or "").strip()


def normalize_action_list_for_authority(
    actions: List[Dict[str, Any]],
    party_tracker_data: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Normalize final narrator action list before processing.

    Contracts:
    - Same-module updatePartyTracker.currentLocationId -> transitionLocation
    - No-op same-location tracker location keys are stripped
    - Non-location tracker fields are preserved
    - Cross-module tracker updates are preserved

    Args:
        actions: Parsed action list from narrator JSON response.
        party_tracker_data: Current party tracker state.

    Returns:
        Tuple of (normalized_actions, normalization_events).
    """
    if not isinstance(actions, list):
        return [], [
            {
                "type": "invalid_actions_payload",
                "reason": "actions_not_list",
            }
        ]

    world_conditions = _safe_dict(_safe_dict(party_tracker_data).get("worldConditions"))
    current_module = _safe_str(_safe_dict(party_tracker_data).get("module"))
    current_location_id = _safe_str(world_conditions.get("currentLocationId"))

    normalized_actions: List[Dict[str, Any]] = []
    normalization_events: List[Dict[str, Any]] = []

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            normalized_actions.append(action)
            continue

        action_name = _safe_str(action.get("action"))
        if action_name != "updatePartyTracker":
            normalized_actions.append(action)
            continue

        params = _safe_dict(action.get("parameters"))
        has_location_keys = any(key in params for key in _LOCATION_KEYS)
        if not has_location_keys:
            normalized_actions.append(action)
            continue

        target_location_id = _safe_str(params.get("currentLocationId"))
        target_module = _safe_str(params.get("module"))
        same_module_scope = not target_module or (
            current_module and target_module == current_module
        )

        stripped_tracker_params = {
            key: value for key, value in params.items() if key not in _LOCATION_KEYS
        }

        if (
            target_location_id
            and current_location_id
            and target_location_id == current_location_id
            and same_module_scope
        ):
            if stripped_tracker_params:
                normalized_actions.append(
                    {
                        "action": "updatePartyTracker",
                        "parameters": stripped_tracker_params,
                    }
                )
                normalization_events.append(
                    {
                        "type": "stripped_noop_same_location_tracker_keys",
                        "action_index": index,
                        "current_location_id": current_location_id,
                        "target_location_id": target_location_id,
                        "preserved_tracker_keys": sorted(stripped_tracker_params.keys()),
                    }
                )
            else:
                normalization_events.append(
                    {
                        "type": "removed_noop_same_location_update_party_tracker",
                        "action_index": index,
                        "current_location_id": current_location_id,
                    }
                )
            continue

        if target_location_id and same_module_scope:
            normalized_actions.append(
                {
                    "action": "transitionLocation",
                    "parameters": {"newLocation": target_location_id},
                }
            )
            normalization_events.append(
                {
                    "type": "converted_same_module_tracker_location_to_transition",
                    "action_index": index,
                    "current_module": current_module,
                    "target_location_id": target_location_id,
                }
            )
            if stripped_tracker_params:
                normalized_actions.append(
                    {
                        "action": "updatePartyTracker",
                        "parameters": stripped_tracker_params,
                    }
                )
                normalization_events.append(
                    {
                        "type": "preserved_tracker_fields_after_transition_conversion",
                        "action_index": index,
                        "preserved_tracker_keys": sorted(stripped_tracker_params.keys()),
                    }
                )
            continue

        normalized_actions.append(action)

    return normalized_actions, normalization_events
