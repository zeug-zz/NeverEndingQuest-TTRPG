# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free schema and normalization tests for pilot layouts."""

from __future__ import annotations

import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot.fixtures import load_verified_fixtures
from scripts.mapping_pilot.layout import normalize_fixture_layout, validate_layout


class MappingPilotLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, _hashes = load_verified_fixtures()
        cls.known_locations = {
            location_id
            for fixture in cls.fixtures.values()
            for location_id in fixture.get("location_ids", [])
        }

    def test_all_four_fixtures_preserve_ids_exits_and_authored_relationship_data(self) -> None:
        for fixture in self.fixtures.values():
            with self.subTest(fixture=fixture["fixture_id"]):
                layout = normalize_fixture_layout(fixture, self.known_locations)
                self.assertEqual(layout["fixture_id"], fixture["fixture_id"])
                if layout["layout_type"] == "locations":
                    self.assertEqual(
                        [{key: value for key, value in row.items() if key != "npc_anchors"} for row in layout["locations"]],
                        fixture["locations"],
                    )
                    self.assertEqual(layout["locations"][0]["npc_anchors"], fixture["npc_anchors"])
                    self.assertEqual(layout["authored_distances"], fixture["authored_distances"])
                else:
                    for key in ("zones", "adjacency", "pairwise_cover", "bands", "occupant_roles", "initial_placement_rules", "movement_allowance_zone_steps", "enemy_movement_policy"):
                        self.assertEqual(layout[key], fixture[key])
                    self.assertEqual(layout["feature_anchors"], fixture["feature_anchors"])

    def test_null_destination_stays_unknown_and_positions_are_schematic(self) -> None:
        layout = normalize_fixture_layout(self.fixtures["interior_tavern"])
        loc = layout["locations"][0]
        self.assertIsNone(loc["exits"][1]["known_destination_location_id"])
        self.assertEqual(loc["exits"][1]["destination_knowledge"], "unknown")
        self.assertIn("schematic", loc["orientation"]["position_semantics"])
        self.assertEqual(loc["features"][0]["position"], "south_center")

    def test_external_destination_ids_are_allowed_unless_closed_set_is_supplied(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        fixture["locations"][0]["exits"][0]["known_destination_location_id"] = "EXTERNAL_LOCATION"
        validate_layout(fixture)
        with self.assertRaisesRegex(ValueError, "unknown destination location"):
            validate_layout(fixture, self.known_locations)

    def test_duplicate_ids_and_dangling_local_references_are_rejected(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        fixture["locations"][0]["features"].append(copy.deepcopy(fixture["locations"][0]["features"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate feature ID"):
            validate_layout(fixture)
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        fixture["locations"][0]["exits"][0]["feature_id"] = "MISSING_FEATURE"
        with self.assertRaisesRegex(ValueError, "unknown local feature"):
            validate_layout(fixture)

    def test_multi_location_references_are_local_with_positive_valid_graph(self) -> None:
        first = copy.deepcopy(self.fixtures["interior_tavern"]["locations"][0])
        second = copy.deepcopy(self.fixtures["landscape_village"]["locations"][0])
        second["location_id"] = "MPV2_LOC_SECOND"
        second["exits"] = []
        second["npc_anchors"] = []
        layout = {"fixture_id": "multi", "locations": [first, second], "authored_distances": []}
        validate_layout(layout)

        bad_exit = copy.deepcopy(layout)
        bad_exit["locations"][1]["exits"] = [{
            "exit_id": "EXIT_CROSS_LOCATION", "feature_id": first["features"][0]["feature_id"],
            "side": "north", "state": "open", "known_destination_location_id": None,
        }]
        with self.assertRaisesRegex(ValueError, "unknown local feature"):
            validate_layout(bad_exit)

        bad_npc = copy.deepcopy(layout)
        bad_npc["locations"][1]["npc_anchors"] = [{
            "npc_id": "NPC_CROSS_LOCATION", "anchor_feature_id": first["features"][0]["feature_id"],
        }]
        with self.assertRaisesRegex(ValueError, "unknown local feature"):
            validate_layout(bad_npc)

    def test_schema_rejects_bad_shape_and_inferred_distance_fields(self) -> None:
        fixture = copy.deepcopy(self.fixtures["landscape_village"])
        fixture["locations"][0]["orientation"]["position_semantics"] = "metric coordinates"
        with self.assertRaisesRegex(ValueError, "invalid layout"):
            validate_layout(fixture)
        fixture = copy.deepcopy(self.fixtures["landscape_village"])
        fixture["inferred_distances"] = [{"from": "well", "to": "bridge", "feet": 30}]
        with self.assertRaisesRegex(ValueError, "invalid layout"):
            validate_layout(fixture)
        fixture = copy.deepcopy(self.fixtures["landscape_village"])
        fixture["locations"][0]["features"][0]["estimated_distance"] = 12
        with self.assertRaisesRegex(ValueError, "estimated_distance"):
            validate_layout(fixture)

    def test_authored_distance_list_is_preserved_without_deriving_anything(self) -> None:
        fixture = copy.deepcopy(self.fixtures["landscape_village"])
        self.assertEqual(normalize_fixture_layout(fixture)["authored_distances"], [])
        fixture["authored_distances"] = [{"from_location_id": "MPV2_LOC_VILLAGE_GREEN", "to_location_id": "MPV2_LOC_TOWER_APPROACH", "value": "one day's walk", "source": "fixture author"}]
        normalized = normalize_fixture_layout(fixture, self.known_locations)
        self.assertEqual(normalized["authored_distances"], fixture["authored_distances"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
