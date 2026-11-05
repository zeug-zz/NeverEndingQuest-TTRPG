# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Build deterministic, sandbox-only Mapping Pilot Arena fixture data."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    PROJECT_ROOT,
    ManifestVerificationError,
    verify_manifest,
)


MODULE_DIR_NAME = "Mapping_Pilot_Arena"
AREA_ID = "MPA001"
TOWER_AREA_ID = "MPA002"
MAP_ID = "MAP_MPA001"
TOWER_MAP_ID = "MAP_MPA002"
DEFAULT_MODULE_ROOT = Path(
    "tmp/combat_capture/modules/Mapping_Pilot_Arena"
)
FIXTURE_FILES = {
    "interior_tavern": "fixtures/interior_tavern.json",
    "landscape_village": "fixtures/landscape_village.json",
    "transition_tower_approach": "fixtures/transition_tower_approach.json",
    "combat_stage_tavern_zones": "fixtures/combat_stage_tavern.json",
}
LOCATION_ID_MAP = {
    "MPV2_LOC_TAVERN": "MP01",
    "MPV2_LOC_VILLAGE_GREEN": "MP02",
    "MPV2_LOC_TOWER_APPROACH": "MP03",
}
_LOCATION_COORDINATES = {
    "MP01": "X0Y0",
    "MP02": "X1Y0",
    "MP03": "X0Y0",
}
_AREA_BY_SOURCE_LOCATION_ID = {
    "MPV2_LOC_TAVERN": AREA_ID,
    "MPV2_LOC_VILLAGE_GREEN": AREA_ID,
    "MPV2_LOC_TOWER_APPROACH": TOWER_AREA_ID,
}
_AREA_BY_RUNTIME_LOCATION_ID = {
    LOCATION_ID_MAP[source_id]: area_id
    for source_id, area_id in _AREA_BY_SOURCE_LOCATION_ID.items()
}
_AREA_NAMES = {
    AREA_ID: "Mapping Pilot Arena",
    TOWER_AREA_ID: "Old Watchtower Approach",
}
_AREA_TYPES = {
    AREA_ID: "mixed",
    TOWER_AREA_ID: "outdoor",
}
_AREA_DESCRIPTIONS = {
    AREA_ID: (
        "A lively village gathering place, centered on a welcoming tavern and a green "
        "that opens toward the old watchtower."
    ),
    TOWER_AREA_ID: (
        "Quiet ground surrounds the old watchtower, where a worn path, closed gate, "
        "and distant village smoke mark the approach."
    ),
}
_MAP_IDS = {
    AREA_ID: MAP_ID,
    TOWER_AREA_ID: TOWER_MAP_ID,
}
_MAP_NAMES = {
    AREA_ID: "Mapping Pilot Arena",
    TOWER_AREA_ID: "Old Watchtower Approach",
}
_GRID_CELLS = (
    "northwest",
    "north",
    "northeast",
    "west",
    "center",
    "east",
    "southwest",
    "south",
    "southeast",
)
_POSITION_TOKENS = {
    "northwest": "northwest",
    "northeast": "northeast",
    "southwest": "southwest",
    "southeast": "southeast",
    "north": "north",
    "south": "south",
    "west": "west",
    "east": "east",
    "center": "center",
}
_LOCATION_SOURCE_ORDER = (
    ("interior_tavern", "MPV2_LOC_TAVERN"),
    ("landscape_village", "MPV2_LOC_VILLAGE_GREEN"),
    ("transition_tower_approach", "MPV2_LOC_TOWER_APPROACH"),
)
_DM_INSTRUCTIONS = {
    "interior_tavern": (
        "Let conversation at the Lantern and Reed unfold around the keeper, the "
        "hooded guest, and the hearth. The open front entrance leads out to the "
        "village green, while the other doors invite cautious investigation."
    ),
    "landscape_village": (
        "Use the well and the bellkeeper as natural focal points while the party "
        "considers the damaged bridge, woodland detour, and shallow ford."
    ),
    "transition_tower_approach": (
        "Let the closed gate and faint lantern glow create quiet tension. The "
        "watcher and mossy cairn offer points of interest, while the village smoke "
        "and return path keep the way back in view."
    ),
}
_RUNTIME_FACT_REPLACEMENTS = {
    "The front entrance is south; the village green is visible beyond it.": (
        "The front entrance stands open to the south, with the village green beyond."
    ),
    "A distant tower roofline is visible through a north window but is not reachable from this room.": (
        "A distant tower roofline shows through the north window."
    ),
    "The detour and ford are known indirect routes to the tower approach.": (
        "The detour and ford offer indirect routes to the tower approach."
    ),
    "The party has entered a second area, the Old Watchtower Approach.": (
        "The party reaches the Old Watchtower Approach."
    ),
    "The closed outer gate is north; the space beyond it is not a known destination.": (
        "The closed outer gate stands to the north."
    ),
    "The party can perceive the bar, long table, hearth, stairs, balcony rail and two melee groups plus the balcony archer.": (
        "The bar, long table, hearth, stairs, balcony rail, two melee groups, and balcony archer are in view."
    ),
    "The front exit is south and open; the kitchen and back-door destinations are unknown.": (
        "The front entrance stands open to the south, while the kitchen and back doors remain closed."
    ),
    "The watchtower roofline is visible through a window but is not a route from the combat stage.": (
        "The watchtower roofline shows through a window, distant beyond the tavern."
    ),
}


class FixtureInputError(ValueError):
    """Raised when a verified fixture set does not satisfy its frozen contract."""


def _source_root(prereg_root: Optional[Union[str, Path]]) -> Path:
    if prereg_root is None:
        return DEFAULT_PREREG_ROOT
    root = Path(prereg_root)
    return root if root.is_absolute() else PROJECT_ROOT / root


def load_verified_fixtures(
    prereg_root: Optional[Union[str, Path]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Verify all frozen inputs before reading the four canonical fixtures."""
    root = _source_root(prereg_root)
    verified_hashes = verify_manifest(root)
    fixtures: Dict[str, Dict[str, Any]] = {}
    for expected_fixture_id, relative_path in FIXTURE_FILES.items():
        if relative_path not in verified_hashes:
            raise ManifestVerificationError(
                relative_path, "canonical fixture is not listed in manifest"
            )
        try:
            payload = json.loads((root / relative_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FixtureInputError("cannot load verified fixture: %s" % relative_path) from exc
        if not isinstance(payload, dict) or payload.get("fixture_id") != expected_fixture_id:
            raise FixtureInputError("unexpected fixture identity in %s" % relative_path)
        fixtures[expected_fixture_id] = payload
    return fixtures, verified_hashes


def _fixture_for_location(
    fixtures: Mapping[str, Mapping[str, Any]], fixture_id: str, location_id: str
) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    fixture = fixtures[fixture_id]
    locations = fixture.get("locations", [])
    matches = [
        location
        for location in locations
        if isinstance(location, Mapping) and location.get("location_id") == location_id
    ]
    if len(matches) != 1:
        raise FixtureInputError(
            "%s must contain exactly one location %s" % (fixture_id, location_id)
        )
    return fixture, matches[0]


def _all_hidden_facts(fixture: Mapping[str, Any]) -> list[str]:
    facts = list(fixture.get("hidden_facts", []))
    for location in fixture.get("locations", []):
        if isinstance(location, Mapping):
            facts.extend(location.get("hidden_facts", []))
    return facts


def build_expected_property_payloads(
    fixtures: Mapping[str, Mapping[str, Any]],
    source_hashes: Mapping[str, str],
) -> Dict[str, Dict[str, Any]]:
    """Purely derive scoring truth payloads; this function performs no I/O."""
    payloads: Dict[str, Dict[str, Any]] = {}
    for fixture_id, relative_path in FIXTURE_FILES.items():
        fixture = fixtures[fixture_id]
        if relative_path not in source_hashes:
            raise FixtureInputError("missing verified hash for %s" % relative_path)
        if fixture.get("fixture_id") != fixture_id:
            raise FixtureInputError("fixture identity mismatch for %s" % fixture_id)

        location_features = []
        for location in fixture.get("locations", []):
            if isinstance(location, Mapping):
                location_features.extend(
                    feature
                    for feature in location.get("features", [])
                    if isinstance(feature, Mapping)
                )
        feature_anchors = fixture.get("feature_anchors", location_features)
        npc_anchors = fixture.get("npc_anchors", [])
        exits = list(fixture.get("exits", []))
        for location in fixture.get("locations", []):
            if isinstance(location, Mapping):
                exits.extend(location.get("exits", []))

        payloads[fixture_id] = {
            "fixture_id": fixture_id,
            "source_file": relative_path,
            "source_sha256": source_hashes[relative_path],
            "location_ids": copy.deepcopy(fixture.get("location_ids", [])),
            "expected_properties": copy.deepcopy(fixture.get("expected_properties", {})),
            "perceivable_facts": [
                fact
                for location in fixture.get("locations", [])
                if isinstance(location, Mapping)
                for fact in location.get("perceivable_facts", [])
            ]
            + list(fixture.get("perceivable_facts", [])),
            "hidden_facts": _all_hidden_facts(fixture),
            "exits": copy.deepcopy(exits),
            "anchors": {
                "features": copy.deepcopy(list(feature_anchors)),
                "npcs": copy.deepcopy(list(npc_anchors)),
                "occupants": copy.deepcopy(fixture.get("occupant_roles", [])),
            },
            "zones": copy.deepcopy(fixture.get("zones", [])),
            "adjacency": copy.deepcopy(fixture.get("adjacency", [])),
            "pairwise_cover": copy.deepcopy(fixture.get("pairwise_cover", [])),
            "initial_placement_rules": copy.deepcopy(
                fixture.get("initial_placement_rules", {})
            ),
            "movement_allowance_zone_steps": copy.deepcopy(
                fixture.get("movement_allowance_zone_steps", {})
            ),
            "enemy_movement_policy": copy.deepcopy(fixture.get("enemy_movement_policy", {})),
            "visible_but_unreachable_landmarks": copy.deepcopy(
                fixture.get("visible_but_unreachable_landmarks", [])
            ),
            "authored_distances": copy.deepcopy(fixture.get("authored_distances", [])),
            "source_truth": copy.deepcopy(dict(fixture)),
        }
    return payloads


def _position_cell(position: str) -> str:
    normalized = position.lower().replace("-", "_")
    if "northwest" in normalized or "north_west" in normalized:
        return "northwest"
    if "northeast" in normalized or "north_east" in normalized or "north_and_east" in normalized:
        return "northeast"
    if "southwest" in normalized or "south_west" in normalized:
        return "southwest"
    if "southeast" in normalized or "south_east" in normalized:
        return "southeast"
    for token in ("north", "south", "west", "east", "center"):
        if token in normalized:
            return _POSITION_TOKENS[token]
    return "center"


def _merge_tavern_features(
    fixtures: Mapping[str, Mapping[str, Any]],
    location: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    features: Dict[str, Dict[str, Any]] = {}
    for feature in location.get("features", []):
        feature_id = str(feature.get("feature_id", ""))
        if feature_id and feature.get("perceivable") is True:
            features[feature_id] = dict(feature)

    combat = fixtures["combat_stage_tavern_zones"]
    for feature in combat.get("feature_anchors", []):
        feature_id = str(feature.get("feature_id", ""))
        if feature_id and feature_id not in features:
            features[feature_id] = dict(feature)

    result: list[Dict[str, Any]] = []
    for feature_id, feature in features.items():
        result.append(
            {
                "feature_id": feature_id,
                "name": str(feature.get("name", "")),
                "position": str(feature.get("position", "center")),
                "state": str(feature.get("state", "")),
                "reachable": feature.get("reachable"),
            }
        )
    zones = {str(zone.get("zone_id")): zone for zone in combat.get("zones", [])}
    for occupant in combat.get("occupant_roles", []):
        zone = zones.get(str(occupant.get("initial_zone_id")), {})
        result.append(
            {
                "feature_id": str(occupant.get("actor_id", "")),
                "name": str(occupant.get("name", "")),
                "position": str(zone.get("position", "center")),
                "state": "combat_stage_anchor",
                "reachable": True,
            }
        )
    return result


def _combined_npc_anchors(
    fixtures: Mapping[str, Mapping[str, Any]],
    location: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    anchors: Dict[str, Dict[str, Any]] = {}
    for source in (location.get("npc_anchors", []), fixtures["combat_stage_tavern_zones"].get("npc_anchors", [])):
        for anchor in source:
            if anchor.get("perceivable", True) is False:
                continue
            anchors[str(anchor.get("npc_id", anchor.get("name", "")))] = dict(anchor)
    return list(anchors.values())


def _location_description(
    fixture: Mapping[str, Any], location: Mapping[str, Any], *, combat_facts: bool = False
) -> str:
    fact_sources = list(location.get("perceivable_facts", []))
    if combat_facts:
        fact_sources.extend(fixture.get("perceivable_facts", []))
    paragraphs = []
    for fact in fact_sources:
        text = str(fact)
        lowered = text.lower()
        if "distance" in lowered or "schematic label" in lowered:
            continue
        paragraphs.append(_RUNTIME_FACT_REPLACEMENTS.get(text, text))
    return "\n\n".join(str(paragraph) for paragraph in paragraphs)


def _exit_text(
    exits: list[Mapping[str, Any]],
    name_by_id: Mapping[str, str],
    feature_name_by_id: Mapping[str, str],
) -> str:
    if not exits:
        return "There are no listed exits."
    lines = []
    for exit_row in exits:
        side = str(exit_row.get("side", "unspecified side"))
        state = str(exit_row.get("state", "unspecified state")).replace("_", " ")
        feature_id = str(exit_row.get("feature_id", ""))
        feature_name = feature_name_by_id.get(feature_id, "An opening")
        target_id = exit_row.get("known_destination_location_id")
        if target_id:
            target_name = name_by_id.get(str(target_id))
            if target_name:
                lines.append(
                    "%s is %s on the %s side, leading to %s."
                    % (feature_name, state, side, target_name)
                )
            else:
                lines.append(
                    "%s is %s on the %s side and leads onward."
                    % (feature_name, state, side)
                )
        else:
            lines.append(
                "%s is %s on the %s side; where it leads is not known."
                % (feature_name, state, side)
            )
    return " ".join(lines)


def _build_area_location(
    fixture: Mapping[str, Any],
    location: Mapping[str, Any],
    runtime_id: str,
    fixture_id: str,
    all_fixtures: Mapping[str, Mapping[str, Any]],
    name_by_id: Mapping[str, str],
    feature_name_by_id: Mapping[str, str],
    connected_ids: list[str],
    area_connectivity: list[str],
    area_connectivity_ids: list[str],
) -> Dict[str, Any]:
    source_location_id = str(location.get("location_id", ""))
    exits = list(location.get("exits", []))
    combined_features = _merge_tavern_features(all_fixtures, location) if source_location_id == "MPV2_LOC_TAVERN" else [
        {
            "feature_id": str(feature.get("feature_id", "")),
            "name": str(feature.get("name", "")),
            "position": str(feature.get("position", "center")),
            "state": str(feature.get("state", "")),
            "reachable": feature.get("reachable"),
        }
        for feature in location.get("features", [])
        if feature.get("perceivable") is True
    ]

    exits_by_feature = {
        str(exit_row.get("feature_id", "")): exit_row for exit_row in exits
    }
    feature_rows = []
    grid_items: Dict[str, list[str]] = {cell: [] for cell in _GRID_CELLS}
    for feature in combined_features:
        name = str(feature.get("name", ""))
        position = str(feature.get("position", "center"))
        state = str(feature.get("state", ""))
        description_parts = ["Position: %s." % position]
        if state:
            description_parts.append("State: %s." % state)
        reachable = feature.get("reachable")
        if reachable is True:
            description_parts.append("Reachable from this location.")
        elif reachable is False:
            description_parts.append("Visible but not reachable from this location.")
        exit_row = exits_by_feature.get(str(feature.get("feature_id", "")))
        if exit_row is not None:
            description_parts.append(
                _exit_text([exit_row], name_by_id, feature_name_by_id)
            )
        feature_rows.append({"name": name, "description": " ".join(description_parts)})
        cell = _position_cell(position)
        grid_items[cell].append("%s: %s" % (position, name))

    npc_anchors = location.get("npc_anchors", [])
    if source_location_id == "MPV2_LOC_TAVERN":
        npc_anchors = _combined_npc_anchors(all_fixtures, location)
    npc_rows = []
    for anchor in npc_anchors:
        if anchor.get("perceivable", True) is False:
            continue
        feature_name = next(
            (
                str(feature.get("name", ""))
                for feature in combined_features
                if feature.get("feature_id") == anchor.get("anchor_feature_id")
            ),
            "a nearby feature",
        )
        name = str(anchor.get("name", ""))
        position = str(anchor.get("position", "nearby")).replace("_", " ")
        npc_rows.append(
            {
                "name": name,
                "description": "Positioned at %s (%s)." % (feature_name, position),
                "attitude": "",
            }
        )
        grid_items[_position_cell(position)].append("%s: %s" % (position, name))

    is_tavern = source_location_id == "MPV2_LOC_TAVERN"
    description = _location_description(
        fixture,
        location,
        combat_facts=is_tavern,
    )
    if not description:
        description = "The scene offers little detail at first glance."

    fixture_name = str(location.get("name", ""))
    exit_summary = _exit_text(exits, name_by_id, feature_name_by_id)
    area_type = {
        "interior_tavern": "tavern",
        "landscape_village": "outdoor",
        "transition_tower_approach": "approach",
    }[fixture_id]
    danger_level = "Medium" if is_tavern else "Low"
    instructions = _DM_INSTRUCTIONS[fixture_id]
    accessibility = exit_summary
    return {
        "locationId": runtime_id,
        "name": fixture_name,
        "type": area_type,
        "description": description,
        "dmInstructions": instructions,
        "coordinates": _LOCATION_COORDINATES[runtime_id],
        "aliases": [fixture_name],
        "tactical_grid": [
            "%s: %s" % (cell, "; ".join(grid_items[cell]))
            for cell in _GRID_CELLS
        ],
        "accessibility": accessibility,
        "npcs": npc_rows,
        "monsters": [],
        "plotHooks": [],
        "lootTable": [],
        "dangerLevel": danger_level,
        "connectivity": connected_ids,
        "areaConnectivity": area_connectivity,
        "areaConnectivityId": area_connectivity_ids,
        "traps": [],
        "features": feature_rows,
        "dcChecks": [],
        "encounters": [],
        "adventureSummary": "",
        "doors": [],
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _build_module_payloads(
    fixtures: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    names_by_source_id: Dict[str, str] = {}
    feature_names_by_source_id: Dict[str, str] = {}
    source_locations: Dict[str, Tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for fixture_id, source_location_id in _LOCATION_SOURCE_ORDER:
        fixture, location = _fixture_for_location(fixtures, fixture_id, source_location_id)
        source_locations[source_location_id] = (fixture, location)
        names_by_source_id[source_location_id] = str(location.get("name", ""))

    for fixture in fixtures.values():
        for location in fixture.get("locations", []):
            if not isinstance(location, Mapping):
                continue
            for feature in location.get("features", []):
                if not isinstance(feature, Mapping):
                    continue
                feature_id = str(feature.get("feature_id", ""))
                feature_name = str(feature.get("name", ""))
                if feature_id and feature_name:
                    feature_names_by_source_id.setdefault(feature_id, feature_name)
        for feature in fixture.get("feature_anchors", []):
            if not isinstance(feature, Mapping):
                continue
            feature_id = str(feature.get("feature_id", ""))
            feature_name = str(feature.get("name", ""))
            if feature_id and feature_name:
                feature_names_by_source_id.setdefault(feature_id, feature_name)

    adjacency: Dict[str, set[str]] = {source_id: set() for source_id in LOCATION_ID_MAP}
    cross_area_targets: Dict[str, set[str]] = {
        source_id: set() for source_id in LOCATION_ID_MAP
    }
    for _fixture_id, source_location_id in _LOCATION_SOURCE_ORDER:
        _fixture, location = source_locations[source_location_id]
        for exit_row in location.get("exits", []):
            target_id = exit_row.get("known_destination_location_id")
            if target_id is None or str(target_id) not in adjacency:
                continue
            target_id = str(target_id)
            if (
                _AREA_BY_SOURCE_LOCATION_ID[source_location_id]
                == _AREA_BY_SOURCE_LOCATION_ID[target_id]
            ):
                adjacency[source_location_id].add(target_id)
                adjacency[target_id].add(source_location_id)
            else:
                cross_area_targets[source_location_id].add(target_id)
                cross_area_targets[target_id].add(source_location_id)

    locations_by_area: Dict[str, list[Dict[str, Any]]] = {
        AREA_ID: [],
        TOWER_AREA_ID: [],
    }
    for fixture_id, source_location_id in _LOCATION_SOURCE_ORDER:
        fixture, source_location = source_locations[source_location_id]
        runtime_id = LOCATION_ID_MAP[source_location_id]
        connected_ids = sorted(
            LOCATION_ID_MAP[neighbor]
            for neighbor in adjacency[source_location_id]
        )
        linked_source_ids = sorted(cross_area_targets[source_location_id])
        area_connectivity = sorted(
            {
                _AREA_NAMES[_AREA_BY_SOURCE_LOCATION_ID[source_id]]
                for source_id in linked_source_ids
            }
        )
        area_connectivity_ids = sorted(
            LOCATION_ID_MAP[source_id] for source_id in linked_source_ids
        )
        location = _build_area_location(
            fixture,
            source_location,
            runtime_id,
            fixture_id,
            fixtures,
            names_by_source_id,
            feature_names_by_source_id,
            connected_ids,
            area_connectivity,
            area_connectivity_ids,
        )
        area_id = _AREA_BY_SOURCE_LOCATION_ID[source_location_id]
        locations_by_area[area_id].append(location)

    areas = {
        area_id: {
            "areaId": area_id,
            "areaName": _AREA_NAMES[area_id],
            "areaType": _AREA_TYPES[area_id],
            "areaDescription": _AREA_DESCRIPTIONS[area_id],
            "dangerLevel": "Medium",
            "recommendedLevel": 1,
            "spatialContractVersion": 1,
            "locations": locations_by_area[area_id],
        }
        for area_id in (AREA_ID, TOWER_AREA_ID)
    }

    map_payloads: Dict[str, Dict[str, Any]] = {}
    for area_id in (AREA_ID, TOWER_AREA_ID):
        area_locations = locations_by_area[area_id]
        room_rows = []
        for location in area_locations:
            if location["locationId"] == "MP01":
                tags = ["interior", "combat_stage"]
            elif location["locationId"] == "MP02":
                tags = ["landscape"]
            else:
                tags = ["transition"]
            room_rows.append(
                {
                    "id": location["locationId"],
                    "name": location["name"],
                    "connections": list(location["connectivity"]),
                    "coordinates": _LOCATION_COORDINATES[location["locationId"]],
                    "directions": {},
                    "type": location["type"],
                    "tags": tags,
                    "purpose": "encounter" if location["locationId"] == "MP01" else "exploration",
                    "dangerLevel": location["dangerLevel"].lower(),
                }
            )
        map_payloads["map_%s.json" % area_id] = {
            "mapName": _MAP_NAMES[area_id],
            "mapId": _MAP_IDS[area_id],
            "totalRooms": len(room_rows),
            "startRoom": room_rows[0]["id"],
            "spatialContractVersion": 1,
            "rooms": room_rows,
            "layout": [[location["locationId"] for location in area_locations]],
        }

    locations = [
        location
        for area_id in (AREA_ID, TOWER_AREA_ID)
        for location in locations_by_area[area_id]
    ]

    npc_context: Dict[str, Dict[str, Any]] = {}
    for location in locations:
        source_location_id = next(
            source_id
            for source_id, mapped_id in LOCATION_ID_MAP.items()
            if mapped_id == location["locationId"]
        )
        _fixture_id = next(
            fixture_id
            for fixture_id, candidate_source_id in _LOCATION_SOURCE_ORDER
            if candidate_source_id == source_location_id
        )
        _fixture, source_location = source_locations[source_location_id]
        anchors = source_location.get("npc_anchors", [])
        if source_location_id == "MPV2_LOC_TAVERN":
            anchors = _combined_npc_anchors(fixtures, source_location)
        for anchor in anchors:
            if anchor.get("perceivable", True) is False:
                continue
            npc_id = "npc_" + _slug(str(anchor.get("name", "")))
            context_features = (
                _merge_tavern_features(fixtures, source_location)
                if source_location_id == "MPV2_LOC_TAVERN"
                else [
                    {
                        "feature_id": str(feature.get("feature_id", "")),
                        "name": str(feature.get("name", "")),
                    }
                    for feature in source_location.get("features", [])
                    if feature.get("perceivable") is True
                ]
            )
            feature_name = next(
                (
                    str(feature.get("name", ""))
                    for feature in context_features
                    if feature.get("feature_id") == anchor.get("anchor_feature_id")
                ),
                "a nearby feature",
            )
            npc_context[npc_id] = {
                "name": str(anchor.get("name", "")),
                "role": "Visible at %s (%s)." % (
                    feature_name,
                    str(anchor.get("position", "a nearby position")).replace("_", " "),
                ),
                "faction": "",
                "appears_in": [location["locationId"]],
            }

    locations_context = {
        location["locationId"]: {
            "name": location["name"],
            "aliases": list(location["aliases"]),
            "area": _AREA_BY_RUNTIME_LOCATION_ID[location["locationId"]],
        }
        for location in locations
    }
    plot_points = [
        {
            "id": "PP001",
            "title": "The Lantern and Reed Tavern",
            "description": "Explore the tavern and meet the keeper and the hooded guest.",
            "location": "MP01",
            "nextPoints": ["PP002"],
            "status": "not started",
            "plotImpact": "",
        },
        {
            "id": "PP002",
            "title": "Rillford Village Green",
            "description": "Consider the damaged bridge, woodland detour, and shallow ford.",
            "location": "MP02",
            "nextPoints": ["PP003"],
            "status": "not started",
            "plotImpact": "",
        },
        {
            "id": "PP003",
            "title": "Old Watchtower Approach",
            "description": "Reach the watchtower approach and keep the ford route back to the village in view.",
            "location": "MP03",
            "nextPoints": [],
            "status": "not started",
            "plotImpact": "",
        },
    ]
    context = {
        "module_name": "Mapping Pilot Arena",
        "module_id": "mapping_pilot_arena",
        "areas": {
            area_id: {
                "name": area["areaName"],
                "type": area["areaType"],
                "locations": [location["locationId"] for location in area["locations"]],
                "npcs": sorted(
                    npc_id
                    for npc_id, npc in npc_context.items()
                    if any(
                        _AREA_BY_RUNTIME_LOCATION_ID[location_id] == area_id
                        for location_id in npc["appears_in"]
                    )
                ),
                "plot_points": [
                    point["id"]
                    for point in plot_points
                    if _AREA_BY_RUNTIME_LOCATION_ID[point["location"]] == area_id
                ],
            }
            for area_id, area in areas.items()
        },
        "npcs": npc_context,
        "locations": locations_context,
        "plot_scopes": {
            point["id"]: _AREA_BY_RUNTIME_LOCATION_ID[point["location"]]
            for point in plot_points
        },
        "tone": "warm village fantasy with a quiet note of mystery",
        "continuity": {
            "continuity_version": "v1",
            "entry_state_variants": {
                "cold_start": {
                    "summary": "Begin at the tavern, where the keeper and a hooded guest are nearby."
                },
                "partial_context": {
                    "summary": "Keep the locations and routes consistent as the party travels."
                },
                "late_arc": {
                    "summary": "Keep the tavern, village green, and tower approach consistent while the facilitator steers the story."
                },
            },
            "cross_module_refs": [],
            "standalone_fallback": {
                "enabled": True,
                "clue_sources": ["module_context", "module_plot"],
                "notes": "The story can be played as a self-contained village adventure.",
            },
        },
    }
    plot = {
        "plotTitle": "The Village and the Old Watchtower",
        "mainObjective": "Explore the tavern and village green, then find a way to the old watchtower.",
        "plotPoints": plot_points,
    }
    id_map = {
        "mapping_version": 1,
        "source_namespace": "MPV2_",
        "runtime_location_ids": dict(LOCATION_ID_MAP),
        "reason": "NEQ locationfile_schema requires one to three uppercase letters followed by two digits; MPV2_ fixture IDs do not match that runtime pattern.",
    }

    payloads: Dict[str, Dict[str, Any]] = {}
    for area_id, area in areas.items():
        payloads["areas/%s.json" % area_id] = area
        payloads["areas/%s_BU.json" % area_id] = copy.deepcopy(area)
    payloads.update(map_payloads)
    payloads.update({
        "module_context.json": context,
        "module_context_BU.json": copy.deepcopy(context),
        "module_plot.json": plot,
        "module_plot_BU.json": copy.deepcopy(plot),
        "location_id_map.json": id_map,
    })
    return payloads


def build_fixture_payloads(
    fixtures: Mapping[str, Mapping[str, Any]],
    source_hashes: Mapping[str, str],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Pure in-memory builder for the module inputs and scoring expectations."""
    missing = sorted(set(FIXTURE_FILES) - set(fixtures))
    if missing:
        raise FixtureInputError("missing fixture payloads: %s" % ", ".join(missing))
    module_payloads = _build_module_payloads(fixtures)
    expected_payloads = build_expected_property_payloads(fixtures, source_hashes)
    return module_payloads, expected_payloads


def _validate_target_root(target_root: Union[str, Path]) -> Tuple[Path, Path]:
    requested = Path(target_root)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("target root must be project-relative and inside tmp/")
    if not requested.parts or requested.parts[0] != "tmp":
        raise ValueError("target root must be project-relative and inside tmp/")
    if len(requested.parts) < 3 or requested.parts[-2:] != ("modules", MODULE_DIR_NAME):
        raise ValueError(
            "target root must end with modules/%s inside tmp/" % MODULE_DIR_NAME
        )

    tmp_root = PROJECT_ROOT / "tmp"
    if tmp_root.is_symlink() or not tmp_root.is_dir():
        raise ValueError("project tmp/ must exist and must not be a symlink")
    module_root = PROJECT_ROOT.joinpath(*requested.parts)
    capture_root = module_root.parent.parent
    for candidate in (capture_root, module_root, module_root / "areas"):
        current = PROJECT_ROOT
        for part in candidate.relative_to(PROJECT_ROOT).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("target root must not traverse symlinks: %s" % current)
    resolved_tmp = tmp_root.resolve()
    for candidate in (capture_root, module_root):
        try:
            candidate.resolve(strict=False).relative_to(resolved_tmp)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("target root must be inside project tmp/") from exc
    return module_root, capture_root


def write_fixture_outputs(
    target_root: Union[str, Path] = DEFAULT_MODULE_ROOT,
    prereg_root: Optional[Union[str, Path]] = None,
) -> Dict[str, str]:
    """Verify, build in memory, then atomically write only below project tmp/."""
    fixtures, source_hashes = load_verified_fixtures(prereg_root)
    module_payloads, expected_payloads = build_fixture_payloads(fixtures, source_hashes)

    module_root, capture_root = _validate_target_root(target_root)
    expected_root = capture_root / "mapping_pilot" / "expected"
    outputs = {
        module_root / relative_path: payload
        for relative_path, payload in module_payloads.items()
    }
    outputs.update(
        {
            expected_root / (fixture_id + ".json"): payload
            for fixture_id, payload in expected_payloads.items()
        }
    )

    resolved_tmp = (PROJECT_ROOT / "tmp").resolve()
    for path in outputs:
        current = PROJECT_ROOT
        for part in path.relative_to(PROJECT_ROOT).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("refusing symlinked output path: %s" % current)
        try:
            path.parent.resolve(strict=False).relative_to(resolved_tmp)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("output path is outside project tmp/: %s" % path) from exc

    from utils.file_operations import safe_write_json

    written_hashes: Dict[str, str] = {}
    for path, payload in sorted(outputs.items(), key=lambda item: str(item[0])):
        if not safe_write_json(
            str(path),
            payload,
            create_backup=False,
            acquire_lock=False,
            json_kwargs={"ensure_ascii": True, "sort_keys": True},
        ):
            raise OSError("atomic JSON write failed: %s" % path)
        relative_output = path.relative_to(capture_root).as_posix()
        written_hashes[relative_output] = hashlib.sha256(path.read_bytes()).hexdigest()
    return written_hashes
