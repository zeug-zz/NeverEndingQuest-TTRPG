# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Build a transient, allowlisted party/viewpoint layout projection."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Set as AbstractSet
from typing import Any, Optional

from scripts.mapping_pilot.layout import normalize_fixture_layout


_POSITION_SEMANTICS = "schematic"
_ABSENCE_SEMANTICS = "omission_does_not_prove_nonexistence"
_DISTANCE_ENDPOINT_KEYS = (
    "from_location_id",
    "to_location_id",
    "from_feature_id",
    "to_feature_id",
)
_DISTANCE_VALUE_KEYS = ("value", "distance", "unit")


def filter_layout_for_viewpoint(
    layout: Mapping[str, Any],
    *,
    current_location_id: str,
    active_actor_id: str,
    party_known_ids: AbstractSet[str],
    perceived_ids: Optional[AbstractSet[str]] = None,
    recent_movement: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return only safe facts for one current viewpoint.

    ``party_known_ids`` is shared, caller-owned knowledge for this invocation.
    ``perceived_ids`` is the active actor's current visibility subset; when
    omitted, fixture ``perceivable`` flags define the default view. Neither set
    is changed or retained. The result is a transient projection, not a
    per-character knowledge record.

    Location and combat-zone layouts are normalized and validated before use.
    The projection is constructed from explicit fields; fixture truth,
    arbitrary free-text facts, scoring properties, and combat-ledger rules are
    never copied through.
    """
    current_location_id = _require_id(current_location_id, "current_location_id")
    active_actor_id = _require_id(active_actor_id, "active_actor_id")
    known_ids = _normalize_id_set(party_known_ids, "party_known_ids")
    view_ids = (
        None
        if perceived_ids is None
        else _normalize_id_set(perceived_ids, "perceived_ids")
    )
    normalized = normalize_fixture_layout(layout)
    layout_type = normalized.get("layout_type")

    if layout_type == "locations":
        location = _find_location(normalized, current_location_id)
        feature_rows = location.get("features", [])
        npc_rows = location.get("npc_anchors", [])
        orientation = location.get("orientation", {})
    elif layout_type == "combat_zones":
        if normalized.get("location_id") != current_location_id:
            raise ValueError(
                "unknown current location %s in combat-zone layout"
                % current_location_id
            )
        location = None
        feature_rows = normalized.get("feature_anchors", [])
        npc_rows = normalized.get("npc_anchors", [])
        orientation = normalized.get("orientation", {})
    else:
        raise ValueError("unsupported normalized layout type")

    projected_features, visible_feature_ids, feature_names = _project_features(
        feature_rows, known_ids, view_ids
    )
    projected_npcs = _project_npcs(
        npc_rows, visible_feature_ids, known_ids, view_ids
    )
    exits = _project_exits(
        normalized.get("exits", [])
        if layout_type == "combat_zones"
        else location.get("exits", []),
        visible_feature_ids,
        known_ids,
    )
    projected_occupants = (
        _project_combat_occupants(normalized, visible_feature_ids, known_ids, view_ids)
        if layout_type == "combat_zones"
        else []
    )

    hidden_references = _filtered_reference_terms(
        feature_rows,
        npc_rows,
        visible_feature_ids,
        projected_npcs,
        normalized.get("occupant_roles", []),
        projected_occupants,
        normalized.get("locations", []),
        current_location_id,
    )
    for npc in projected_npcs:
        position = npc.get("position")
        if isinstance(position, str) and _contains_reference(
            position, hidden_references
        ):
            npc.pop("position", None)
    visible_landmarks = _project_visible_landmarks(
        normalized.get("visible_but_unreachable_landmarks", []),
        feature_rows,
        current_location_id,
        visible_feature_ids,
        feature_names,
    )
    current_location: dict[str, Any] = {"location_id": current_location_id}
    if location is not None and isinstance(location.get("name"), str):
        current_location["name"] = location["name"]

    result: dict[str, Any] = {
        "layout_type": layout_type,
        "current_location": current_location,
        "active_actor_id": active_actor_id,
        "orientation": _project_orientation(
            orientation, visible_feature_ids, hidden_references
        ),
        "position_semantics": _POSITION_SEMANTICS,
        "feature_anchors": projected_features,
        "npc_anchors": projected_npcs,
        "occupant_anchors": projected_occupants,
        "exits": exits,
        "visible_landmarks": visible_landmarks,
        "authored_distances": _project_authored_distances(
            normalized.get("authored_distances", []),
            visible_feature_ids,
            current_location_id,
        ),
        "absence_semantics": _ABSENCE_SEMANTICS,
    }
    movement = _project_recent_movement(
        recent_movement, current_location_id, known_ids
    )
    if movement is not None:
        result["recent_movement"] = movement
    return result


def _require_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("%s must be a non-empty string" % field_name)
    return value


def _normalize_id_set(values: AbstractSet[str], field_name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, AbstractSet):
        raise ValueError("%s must be a set of stable IDs" % field_name)
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError("%s must contain only non-empty string IDs" % field_name)
        normalized.add(value)
    return frozenset(normalized)


def _find_location(layout: Mapping[str, Any], location_id: str) -> Mapping[str, Any]:
    matches = [
        row
        for row in layout.get("locations", [])
        if isinstance(row, Mapping) and row.get("location_id") == location_id
    ]
    if len(matches) != 1:
        raise ValueError("unknown current location %s in layout" % location_id)
    return matches[0]


def _project_features(
    rows: Any,
    party_known_ids: frozenset[str],
    perceived_ids: Optional[frozenset[str]],
) -> tuple[list[dict[str, Any]], set[str], dict[str, str]]:
    projected: list[dict[str, Any]] = []
    currently_visible: set[str] = set()
    names: dict[str, str] = {}
    if not isinstance(rows, list):
        return projected, currently_visible, names

    for feature in rows:
        if not isinstance(feature, Mapping):
            continue
        feature_id = feature.get("feature_id")
        name = feature.get("name")
        if not isinstance(feature_id, str) or not feature_id:
            continue
        if isinstance(name, str) and name:
            names[feature_id] = name
        can_perceive = feature.get("perceivable", True) is not False
        is_perceived = can_perceive and (
            perceived_ids is None or feature_id in perceived_ids
        )
        if is_perceived:
            row: dict[str, Any] = {
                "feature_id": feature_id,
                "visibility": "perceived",
            }
            if isinstance(name, str):
                row["name"] = name
            position = feature.get("position")
            if isinstance(position, str):
                row["position"] = position
            state = feature.get("state")
            if isinstance(state, str):
                row["state"] = state
            reachable = feature.get("reachable")
            if isinstance(reachable, bool):
                row["reachability"] = (
                    "reachable_from_current_location"
                    if reachable
                    else "unreachable_from_current_location"
                )
            projected.append(row)
            currently_visible.add(feature_id)
        elif feature_id in party_known_ids:
            row = {"feature_id": feature_id, "visibility": "known_only"}
            if isinstance(name, str):
                row["name"] = name
            projected.append(row)
    return projected, currently_visible, names


def _project_npcs(
    rows: Any,
    visible_feature_ids: set[str],
    party_known_ids: frozenset[str],
    perceived_ids: Optional[frozenset[str]],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return projected

    for npc in rows:
        if not isinstance(npc, Mapping):
            continue
        npc_id = npc.get("npc_id")
        if not isinstance(npc_id, str) or not npc_id:
            continue
        anchor_id = npc.get("anchor_feature_id")
        anchor_is_visible = isinstance(anchor_id, str) and anchor_id in visible_feature_ids
        can_perceive = npc.get("perceivable", True) is not False
        is_perceived = can_perceive and (
            anchor_is_visible
            if perceived_ids is None
            else (npc_id in perceived_ids or anchor_is_visible)
        )
        is_known = npc_id in party_known_ids
        if not is_perceived and not is_known:
            continue

        row: dict[str, Any] = {
            "npc_id": npc_id,
            "visibility": "perceived" if is_perceived else "known_only",
        }
        name = npc.get("name")
        if isinstance(name, str):
            row["name"] = name
        if is_perceived and anchor_is_visible:
            row["anchor_feature_id"] = anchor_id
            position = npc.get("position")
            if isinstance(position, str):
                row["position"] = position
        projected.append(row)
    return projected


def _project_exits(
    rows: Any,
    visible_feature_ids: set[str],
    party_known_ids: frozenset[str],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return projected

    for exit_row in rows:
        if not isinstance(exit_row, Mapping):
            continue
        exit_id = exit_row.get("exit_id")
        feature_id = exit_row.get("feature_id")
        if (
            not isinstance(exit_id, str)
            or not exit_id
            or not isinstance(feature_id, str)
            or feature_id not in visible_feature_ids
            or exit_row.get("perceivable", True) is False
        ):
            continue
        side = exit_row.get("side")
        state = exit_row.get("state")
        if not isinstance(side, str) or not isinstance(state, str):
            continue
        destination_id = exit_row.get("known_destination_location_id")
        destination_known = (
            isinstance(destination_id, str)
            and destination_id in party_known_ids
            and exit_row.get("destination_knowledge") == "known"
        )
        projected.append(
            {
                "exit_id": exit_id,
                "feature_id": feature_id,
                "side": side,
                "state": state,
                "destination": destination_id if destination_known else "unknown",
            }
        )
    return projected


def _project_visible_landmarks(
    landmark_rows: Any,
    feature_rows: Any,
    current_location_id: str,
    visible_feature_ids: set[str],
    feature_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    landmark_ids: set[str] = set()
    if isinstance(landmark_rows, list):
        for landmark in landmark_rows:
            if not isinstance(landmark, Mapping):
                continue
            feature_id = landmark.get("feature_id")
            visible_from = landmark.get("visible_from_location_id")
            if (
                isinstance(feature_id, str)
                and visible_from == current_location_id
                and feature_id in visible_feature_ids
            ):
                landmark_ids.add(feature_id)

    if isinstance(feature_rows, list):
        for feature in feature_rows:
            if (
                isinstance(feature, Mapping)
                and feature.get("reachable") is False
                and feature.get("feature_id") in visible_feature_ids
            ):
                landmark_ids.add(feature["feature_id"])

    return [
        {
            "feature_id": feature_id,
            "name": feature_names.get(feature_id, ""),
            "visibility": "visible",
            "reachability": "unreachable_from_current_location",
        }
        for feature_id in sorted(landmark_ids)
    ]


def _project_combat_occupants(
    layout: Mapping[str, Any],
    visible_feature_ids: set[str],
    party_known_ids: frozenset[str],
    perceived_ids: Optional[frozenset[str]],
) -> list[dict[str, Any]]:
    zones = {
        row.get("zone_id"): row
        for row in layout.get("zones", [])
        if isinstance(row, Mapping) and isinstance(row.get("zone_id"), str)
    }
    projected: list[dict[str, Any]] = []
    for occupant in layout.get("occupant_roles", []):
        if not isinstance(occupant, Mapping):
            continue
        actor_id = occupant.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id:
            continue
        is_perceived = perceived_ids is None or actor_id in perceived_ids
        is_known = actor_id in party_known_ids
        if not is_perceived and not is_known:
            continue

        row: dict[str, Any] = {
            "actor_id": actor_id,
            "visibility": "perceived" if is_perceived else "known_only",
        }
        name = occupant.get("name")
        if isinstance(name, str):
            row["name"] = name
        if is_perceived:
            zone = zones.get(occupant.get("initial_zone_id"))
            if isinstance(zone, Mapping):
                anchor_id = zone.get("feature_id")
                if isinstance(anchor_id, str) and anchor_id in visible_feature_ids:
                    row["anchor_feature_id"] = anchor_id
                    position = zone.get("position")
                    if isinstance(position, str):
                        row["position"] = position
        projected.append(row)
    return projected


def _project_orientation(
    orientation: Any,
    visible_feature_ids: set[str],
    filtered_references: set[str],
) -> dict[str, Any]:
    if not isinstance(orientation, Mapping):
        return {"position_semantics": _POSITION_SEMANTICS}
    projected: dict[str, Any] = {"position_semantics": _POSITION_SEMANTICS}
    origin_id = orientation.get("origin_feature_id")
    if isinstance(origin_id, str) and origin_id in visible_feature_ids:
        projected["origin_feature_id"] = origin_id
    for key in ("north", "entry_facing"):
        value = orientation.get(key)
        if (
            isinstance(value, str)
            and value
            and not _contains_reference(value, filtered_references)
        ):
            projected[key] = value
    return projected


def _filtered_reference_terms(
    feature_rows: Any,
    npc_rows: Any,
    visible_feature_ids: set[str],
    projected_npcs: list[Mapping[str, Any]],
    occupant_rows: Any,
    projected_occupants: list[Mapping[str, Any]],
    location_rows: Any,
    current_location_id: str,
) -> set[str]:
    allowed_npc_ids = {row.get("npc_id") for row in projected_npcs if row.get("visibility") == "perceived"}
    allowed_occupant_ids = {
        row.get("actor_id")
        for row in projected_occupants
        if row.get("visibility") == "perceived"
    }
    filtered: set[str] = set()
    for rows, identity_key, visible_ids in (
        (feature_rows, "feature_id", visible_feature_ids),
        (npc_rows, "npc_id", allowed_npc_ids),
        (occupant_rows, "actor_id", allowed_occupant_ids),
    ):
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            identifier = row.get(identity_key)
            if isinstance(identifier, str) and identifier not in visible_ids:
                filtered.add(identifier)
                name = row.get("name")
                if isinstance(name, str) and name:
                    filtered.add(name)
    if isinstance(location_rows, list):
        for row in location_rows:
            if not isinstance(row, Mapping) or row.get("location_id") == current_location_id:
                continue
            for key in ("location_id", "name"):
                value = row.get(key)
                if isinstance(value, str) and value:
                    filtered.add(value)
    return filtered


def _contains_reference(text: str, references: set[str]) -> bool:
    folded = text.casefold()
    for reference in references:
        candidate = reference.casefold()
        if not candidate:
            continue
        if candidate.upper().startswith("MPV2_") or candidate.startswith("mpv2_"):
            if candidate in folded:
                return True
        elif re.search(r"(?<!\w)%s(?!\w)" % re.escape(candidate), folded):
            return True
    return False


def _project_authored_distances(
    rows: Any,
    visible_feature_ids: set[str],
    current_location_id: str,
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return projected
    visible_endpoints = set(visible_feature_ids)
    visible_endpoints.add(current_location_id)
    for distance in rows:
        if not isinstance(distance, Mapping):
            continue
        endpoints = {
            key: distance[key]
            for key in _DISTANCE_ENDPOINT_KEYS
            if isinstance(distance.get(key), str)
        }
        if len(endpoints) < 2 or any(
            endpoint not in visible_endpoints for endpoint in endpoints.values()
        ):
            continue
        row: dict[str, Any] = dict(endpoints)
        for key in _DISTANCE_VALUE_KEYS:
            value = distance.get(key)
            if isinstance(value, str) and value:
                row[key] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                if not isinstance(value, float) or math.isfinite(value):
                    row[key] = value
        if any(key in row for key in ("value", "distance")):
            projected.append(row)
    return projected


def _project_recent_movement(
    movement: Optional[Mapping[str, Any]],
    current_location_id: str,
    party_known_ids: frozenset[str],
) -> Optional[dict[str, str]]:
    if movement is None:
        return None
    if not isinstance(movement, Mapping):
        raise ValueError("recent_movement must be an object")
    from_id = movement.get("from_location_id")
    to_id = movement.get("to_location_id")
    if (
        not isinstance(from_id, str)
        or not isinstance(to_id, str)
        or to_id != current_location_id
        or from_id not in party_known_ids
    ):
        return None
    return {"from_location_id": from_id, "to_location_id": current_location_id}
