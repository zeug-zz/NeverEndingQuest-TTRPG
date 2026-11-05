# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Validate and normalize frozen location and combat-zone layout inputs.

Combat fixtures are zone-shaped, not location-shaped. They are exposed as a
separate ``combat_zones`` variant and retain all zone/ledger facts verbatim;
this module does not convert or infer a locations graph from those facts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Set

from jsonschema import Draft202012Validator


SCHEMA_PATH = Path(__file__).with_name("layout_schema.json")
with SCHEMA_PATH.open(encoding="utf-8") as _schema_file:
    LAYOUT_SCHEMA = json.load(_schema_file)


def normalize_fixture_layout(
    fixture: Mapping[str, Any],
    known_location_ids: Optional[Set[str]] = None,
) -> dict[str, Any]:
    """Return a validated, detached layout preserving all authored fixture data.

    Null destinations remain null (the packet-facing meaning is ``unknown``).
    External destination IDs are accepted by default; pass the complete known
    location ID set to reject references outside that set.
    """
    if not isinstance(fixture, Mapping):
        raise ValueError("fixture must be an object")
    payload = copy.deepcopy(dict(fixture))
    _reject_unauthored_distance_fields(payload)
    if "zones" in payload:
        payload["layout_type"] = "combat_zones"
        payload["location_id"] = _single_location_id(payload)
    else:
        payload["layout_type"] = "locations"
        for location in payload.get("locations", []):
            if isinstance(location, dict) and "npc_anchors" not in location:
                location["npc_anchors"] = copy.deepcopy(payload.get("npc_anchors", []))
    errors = sorted(Draft202012Validator(LAYOUT_SCHEMA).iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.path) or "<root>"
        detail = error.message
        if error.context:
            detail = "; ".join(child.message for child in error.context[:3])
        raise ValueError("invalid layout at %s: %s" % (path, detail))

    ids: dict[str, str] = {}
    feature_ids: set[str] = set()
    exit_ids: set[str] = set()
    npc_ids: set[str] = set()
    locations = payload.get("locations", [])
    if locations:
        location_ids = [row["location_id"] for row in locations]
    else:
        location_ids = [payload["location_id"]]
    _unique_ids(location_ids, "location", ids)
    for row in locations:
        local_feature_ids: set[str] = set()
        for feature in row["features"]:
            _add_unique(feature["feature_id"], "feature", feature_ids)
            local_feature_ids.add(feature["feature_id"])
        for exit_row in row["exits"]:
            _add_unique(exit_row["exit_id"], "exit", exit_ids)
            if exit_row["feature_id"] not in local_feature_ids:
                raise ValueError("exit %s references unknown local feature %s" % (exit_row["exit_id"], exit_row["feature_id"]))
        for npc in row["npc_anchors"]:
            _add_unique(npc["npc_id"], "NPC", npc_ids)
            if npc["anchor_feature_id"] not in local_feature_ids:
                raise ValueError("NPC %s references unknown local feature %s" % (npc["npc_id"], npc["anchor_feature_id"]))
    if payload.get("layout_type") == "combat_zones":
        for feature in payload["feature_anchors"]:
            _add_unique(feature["feature_id"], "feature", feature_ids)
        for exit_row in payload["exits"]:
            _add_unique(exit_row["exit_id"], "exit", exit_ids)
            if exit_row["feature_id"] not in feature_ids:
                raise ValueError("exit %s references unknown local feature %s" % (exit_row["exit_id"], exit_row["feature_id"]))
        for npc in payload["npc_anchors"]:
            _add_unique(npc["npc_id"], "NPC", npc_ids)
            if npc["anchor_feature_id"] not in feature_ids:
                raise ValueError("NPC %s references unknown local feature %s" % (npc["npc_id"], npc["anchor_feature_id"]))
        zone_ids: set[str] = set()
        for zone in payload["zones"]:
            _add_unique(zone.get("zone_id"), "zone", zone_ids)
            if zone.get("feature_id") not in feature_ids:
                raise ValueError("zone %s references unknown local feature %s" % (zone.get("zone_id"), zone.get("feature_id")))
        for pair in payload["adjacency"]:
            if any(zone_id not in zone_ids for zone_id in pair):
                raise ValueError("adjacency references unknown local zone: %s" % pair)
    if known_location_ids is not None:
        for row in locations:
            _check_destinations(row["exits"], known_location_ids)
        if payload.get("layout_type") == "combat_zones":
            _check_destinations(payload["exits"], known_location_ids)
    return payload


def validate_layout(
    layout: Mapping[str, Any], known_location_ids: Optional[Set[str]] = None
) -> dict[str, Any]:
    """Validate a prototype layout (including D1 ``locations`` inputs)."""
    if not isinstance(layout, Mapping):
        raise ValueError("layout must be an object")
    return normalize_fixture_layout(layout, known_location_ids)


def _single_location_id(fixture: Mapping[str, Any]) -> str:
    location_ids = fixture.get("location_ids")
    if not isinstance(location_ids, list) or len(location_ids) != 1 or not isinstance(location_ids[0], str):
        raise ValueError("combat zone fixture requires exactly one location_id")
    return location_ids[0]


def _add_unique(value: Any, kind: str, seen: set[str]) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("%s ID must be a non-empty string" % kind)
    if value in seen:
        raise ValueError("duplicate %s ID: %s" % (kind, value))
    seen.add(value)


def _unique_ids(values: list[str], kind: str, _unused: dict[str, str]) -> None:
    seen: set[str] = set()
    for value in values:
        _add_unique(value, kind, seen)


def _check_destinations(exits: list[Mapping[str, Any]], known_ids: Set[str]) -> None:
    for exit_row in exits:
        destination = exit_row["known_destination_location_id"]
        if destination is not None and destination not in known_ids:
            raise ValueError("exit %s references unknown destination location %s" % (exit_row["exit_id"], destination))


def _reject_unauthored_distance_fields(value: Any, path: str = "<root>") -> None:
    """Reject distance-like keys recursively, except inside authored_distances."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = "%s.%s" % (path, key_text)
            if key_text == "authored_distances":
                continue
            if "distance" in key_text.lower() and key_text != "distance_policy":
                raise ValueError("invalid layout: unauthored distance field at %s" % child_path)
            _reject_unauthored_distance_fields(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_unauthored_distance_fields(child, "%s[%d]" % (path, index))
