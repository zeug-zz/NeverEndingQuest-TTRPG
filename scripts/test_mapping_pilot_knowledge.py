# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free security and viewpoint tests for mapping-pilot knowledge."""

from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Arm network and outside-write tripwires before importing fixture helpers.
from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.mapping_pilot.fixtures import load_verified_fixtures
from scripts.mapping_pilot.knowledge import filter_layout_for_viewpoint
from scripts.mapping_pilot.layout import normalize_fixture_layout


class MappingPilotKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, _hashes = load_verified_fixtures()

    def test_all_normalized_fixture_variants_project_without_mutating_sources(self) -> None:
        for fixture in self.fixtures.values():
            with self.subTest(fixture=fixture["fixture_id"]):
                source = copy.deepcopy(fixture)
                layout = normalize_fixture_layout(fixture)
                current_location_id = fixture["location_ids"][0]
                result = filter_layout_for_viewpoint(
                    layout,
                    current_location_id=current_location_id,
                    active_actor_id="Acheron",
                    party_known_ids=frozenset(fixture["location_ids"]),
                )
                self.assertEqual(fixture, source)
                self.assertEqual(
                    result["layout_type"],
                    "combat_zones"
                    if fixture["fixture_id"] == "combat_stage_tavern_zones"
                    else "locations",
                )
                self.assertEqual(
                    result["current_location"]["location_id"], current_location_id
                )
                self.assertEqual(result["position_semantics"], "schematic")
                self.assertEqual(result["authored_distances"], [])
                self.assertEqual(
                    result["absence_semantics"],
                    "omission_does_not_prove_nonexistence",
                )
                serialized = json.dumps(result, ensure_ascii=True, sort_keys=True)
                self.assertNotIn("hidden_facts", serialized)
                self.assertNotIn("expected_properties", serialized)
                self.assertNotIn("perceivable_facts", serialized)

    def test_allowlisted_projection_drops_hidden_and_arbitrary_fact_sentinels(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        secret = "SECRET_SENTINEL_KITCHEN_CONTENTS_71"
        location = fixture["locations"][0]
        fixture.setdefault("hidden_facts", []).append(secret)
        location["hidden_facts"].append("SECRET_SENTINEL_LOCAL_HIDDEN_72")
        location["perceivable_facts"].append("SECRET_SENTINEL_FREE_TEXT_73")
        fixture["expected_properties"]["secret_answer"] = "SECRET_SENTINEL_SCORE_74"
        fixture["mutable_features"][0]["private_note"] = "SECRET_SENTINEL_MUTATION_75"
        location["features"][0]["private_note"] = "SECRET_SENTINEL_FEATURE_76"
        location["exits"][1]["route_label"] = "SECRET_SENTINEL_EXIT_77"
        fixture["unrecognized_metadata"] = {"note": "SECRET_SENTINEL_METADATA_78"}
        before = copy.deepcopy(fixture)

        result = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Acheron",
            party_known_ids=frozenset({"MPV2_LOC_VILLAGE_GREEN"}),
        )
        serialized = json.dumps(result, ensure_ascii=True, sort_keys=True)
        for sentinel in (
            "SECRET_SENTINEL_KITCHEN_CONTENTS_71",
            "SECRET_SENTINEL_LOCAL_HIDDEN_72",
            "SECRET_SENTINEL_FREE_TEXT_73",
            "SECRET_SENTINEL_SCORE_74",
            "SECRET_SENTINEL_MUTATION_75",
            "SECRET_SENTINEL_FEATURE_76",
            "SECRET_SENTINEL_EXIT_77",
            "SECRET_SENTINEL_METADATA_78",
        ):
            self.assertNotIn(sentinel, serialized)
        for forbidden_key in (
            "hidden_facts",
            "perceivable_facts",
            "expected_properties",
            "mutable_features",
            "source_truth",
            "unrecognized_metadata",
            "zones",
            "occupant_roles",
            "initial_placement_rules",
        ):
            self.assertNotIn(forbidden_key, result)
        self.assertEqual(fixture, before)

    def test_viewpoint_subset_filters_anchors_exits_npcs_and_distance_relations(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        location = fixture["locations"][0]
        front_id = "MPV2_F_TAVERN_FRONT_DOOR"
        table_id = "MPV2_F_TAVERN_LONG_TABLE"
        bar_id = "MPV2_F_TAVERN_BAR"
        kitchen_id = "MPV2_F_TAVERN_KITCHEN_DOOR"
        keeper_id = "MPV2_NPC_TAVERN_KEEPER"
        fixture["authored_distances"] = [
            {
                "from_feature_id": front_id,
                "to_feature_id": table_id,
                "value": "three paces",
                "unit": "paces",
                "private_note": "SECRET_SENTINEL_DISTANCE_METADATA_81",
            },
            {
                "from_feature_id": front_id,
                "to_feature_id": kitchen_id,
                "value": "SECRET_SENTINEL_FILTERED_DISTANCE_82",
                "unit": "paces",
            },
        ]
        before = copy.deepcopy(fixture)

        result = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Merisiel",
            party_known_ids=frozenset({"MPV2_LOC_VILLAGE_GREEN", keeper_id}),
            perceived_ids=frozenset({front_id, table_id}),
        )
        rendered = json.dumps(result, ensure_ascii=True, sort_keys=True)
        feature_ids = {row["feature_id"] for row in result["feature_anchors"]}
        self.assertEqual(feature_ids, {front_id, table_id})
        self.assertNotIn(kitchen_id, rendered)
        self.assertNotIn("MPV2_F_TAVERN_BACK_DOOR", rendered)
        self.assertNotIn(bar_id, rendered)
        self.assertNotIn("Wooden bar", rendered)
        self.assertEqual(
            [row["feature_id"] for row in result["exits"]], [front_id]
        )
        self.assertEqual(result["exits"][0]["destination"], "MPV2_LOC_VILLAGE_GREEN")
        keeper = next(row for row in result["npc_anchors"] if row["npc_id"] == keeper_id)
        self.assertEqual(keeper["visibility"], "known_only")
        self.assertNotIn("anchor_feature_id", keeper)
        self.assertNotIn("position", keeper)
        self.assertEqual(len(result["authored_distances"]), 1)
        self.assertNotIn("private_note", result["authored_distances"][0])
        self.assertEqual(result["authored_distances"][0]["value"], "three paces")
        self.assertNotIn("SECRET_SENTINEL_DISTANCE_METADATA_81", rendered)
        self.assertNotIn("SECRET_SENTINEL_FILTERED_DISTANCE_82", rendered)
        self.assertEqual(fixture, before)

    def test_unknown_destinations_are_literal_unknown_without_target_name_leak(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        kitchen_exit = fixture["locations"][0]["exits"][1]
        kitchen_exit["known_destination_location_id"] = None
        kitchen_exit["destination_knowledge"] = "unknown"
        kitchen_exit["destination_name"] = "SECRET_SENTINEL_BEYOND_DOOR_91"
        back_exit = fixture["locations"][0]["exits"][2]
        back_exit["known_destination_location_id"] = "MPV2_LOC_SECRET_BACK_ROOM"
        back_exit["destination_knowledge"] = "unknown"
        result = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Acheron",
            party_known_ids=frozenset(),
        )
        kitchen_projection = next(
            row for row in result["exits"] if row["exit_id"] == "MPV2_EXIT_TAVERN_KITCHEN"
        )
        self.assertEqual(kitchen_projection["destination"], "unknown")
        self.assertNotIn("known_destination_location_id", kitchen_projection)
        self.assertNotIn("destination_name", kitchen_projection)
        back_projection = next(
            row for row in result["exits"] if row["exit_id"] == "MPV2_EXIT_TAVERN_BACK"
        )
        self.assertEqual(back_projection["destination"], "unknown")
        self.assertNotIn("MPV2_LOC_SECRET_BACK_ROOM", json.dumps(result))
        self.assertNotIn("SECRET_SENTINEL_BEYOND_DOOR_91", json.dumps(result))

    def test_viewpoint_changes_are_transient_and_do_not_accumulate_per_actor_knowledge(self) -> None:
        shared_known = frozenset({"MPV2_LOC_VILLAGE_GREEN"})
        fixture = self.fixtures["interior_tavern"]
        first = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Acheron",
            party_known_ids=shared_known,
            perceived_ids=frozenset({"MPV2_F_TAVERN_FRONT_DOOR"}),
        )
        second = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Merisiel",
            party_known_ids=shared_known,
            perceived_ids=frozenset({"MPV2_F_TAVERN_BAR"}),
        )
        third = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Acheron",
            party_known_ids=shared_known,
            perceived_ids=frozenset({"MPV2_F_TAVERN_HEARTH"}),
        )

        self.assertEqual(shared_known, frozenset({"MPV2_LOC_VILLAGE_GREEN"}))
        self.assertEqual(first["active_actor_id"], "Acheron")
        self.assertEqual(second["active_actor_id"], "Merisiel")
        self.assertNotEqual(first["feature_anchors"], second["feature_anchors"])
        self.assertEqual(
            {row["feature_id"] for row in second["feature_anchors"]},
            {"MPV2_F_TAVERN_BAR"},
        )
        self.assertEqual(
            {row["feature_id"] for row in third["feature_anchors"]},
            {"MPV2_F_TAVERN_HEARTH"},
        )
        self.assertNotIn("per_pc_knowledge", second)
        self.assertNotIn("knowledge_by_actor", second)
        self.assertEqual(second["exits"], [])

    def test_absence_is_not_reported_as_nonexistence(self) -> None:
        result = filter_layout_for_viewpoint(
            self.fixtures["interior_tavern"],
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Acheron",
            party_known_ids=frozenset(),
            perceived_ids=frozenset(),
        )
        self.assertEqual(result["feature_anchors"], [])
        self.assertEqual(result["npc_anchors"], [])
        self.assertEqual(result["exits"], [])
        self.assertEqual(
            result["absence_semantics"],
            "omission_does_not_prove_nonexistence",
        )
        rendered = json.dumps(result, ensure_ascii=True).lower()
        self.assertNotIn("there are no exits", rendered)
        self.assertNotIn("no anchors exist", rendered)

    def test_visible_unreachable_landmarks_are_separate_from_routes(self) -> None:
        result = filter_layout_for_viewpoint(
            self.fixtures["landscape_village"],
            current_location_id="MPV2_LOC_VILLAGE_GREEN",
            active_actor_id="Acheron",
            party_known_ids=frozenset({"MPV2_LOC_TOWER_APPROACH"}),
        )
        tower_id = "MPV2_F_VILLAGE_WATCHTOWER"
        tower = next(
            row for row in result["feature_anchors"] if row["feature_id"] == tower_id
        )
        self.assertEqual(
            tower["reachability"], "unreachable_from_current_location"
        )
        landmarks_by_id = {
            row["feature_id"]: row for row in result["visible_landmarks"]
        }
        self.assertEqual(
            landmarks_by_id[tower_id],
            {
                "feature_id": tower_id,
                "name": "Watchtower across the river",
                "visibility": "visible",
                "reachability": "unreachable_from_current_location",
            },
        )
        self.assertIn("MPV2_F_VILLAGE_RIVER", landmarks_by_id)
        self.assertNotIn(tower_id, {row["feature_id"] for row in result["exits"]})
        self.assertNotIn("known_route", json.dumps(result))
        self.assertNotIn("indirect routes", json.dumps(result).lower())

    def test_combat_zone_projection_keeps_known_enemy_existence_not_hidden_position(self) -> None:
        fixture = copy.deepcopy(self.fixtures["combat_stage_tavern_zones"])
        fixture["zones"][1]["private_note"] = "SECRET_SENTINEL_ZONE_101"
        fixture["occupant_roles"][2]["private_note"] = "SECRET_SENTINEL_OCCUPANT_102"
        fixture["expected_properties"]["private_note"] = "SECRET_SENTINEL_SCORE_103"
        fixture["orientation"]["north"] = "toward the Balcony archer"
        result = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Kira",
            party_known_ids=frozenset({"MPV2_ENEMY_BALCONY_ARCHER"}),
            perceived_ids=frozenset(
                {"MPV2_F_TAVERN_LONG_TABLE", "MPV2_ENEMY_MELEE_ALPHA"}
            ),
        )
        rendered = json.dumps(result, ensure_ascii=True, sort_keys=True)
        self.assertEqual(result["layout_type"], "combat_zones")
        self.assertEqual(
            {row["feature_id"] for row in result["feature_anchors"]},
            {"MPV2_F_TAVERN_LONG_TABLE"},
        )
        alpha = next(
            row
            for row in result["occupant_anchors"]
            if row["actor_id"] == "MPV2_ENEMY_MELEE_ALPHA"
        )
        self.assertEqual(alpha["anchor_feature_id"], "MPV2_F_TAVERN_LONG_TABLE")
        self.assertEqual(alpha["position"], "center")
        archer = next(
            row
            for row in result["occupant_anchors"]
            if row["actor_id"] == "MPV2_ENEMY_BALCONY_ARCHER"
        )
        self.assertEqual(archer["visibility"], "known_only")
        self.assertNotIn("anchor_feature_id", archer)
        self.assertNotIn("position", archer)
        self.assertNotIn("initial_zone_id", archer)
        self.assertNotIn("MPV2_ENEMY_MELEE_BETA", rendered)
        self.assertNotIn("MPV2_Z_BALCONY", rendered)
        self.assertNotIn("Balcony archer", result["orientation"].get("north", ""))
        for sentinel in (
            "SECRET_SENTINEL_ZONE_101",
            "SECRET_SENTINEL_OCCUPANT_102",
            "SECRET_SENTINEL_SCORE_103",
        ):
            self.assertNotIn(sentinel, rendered)
        for forbidden_key in (
            "zones",
            "adjacency",
            "pairwise_cover",
            "occupant_roles",
            "initial_placement_rules",
            "enemy_movement_policy",
        ):
            self.assertNotIn(forbidden_key, result)

    def test_orientation_is_schematic_and_does_not_name_filtered_anchors(self) -> None:
        fixture = copy.deepcopy(self.fixtures["interior_tavern"])
        location = fixture["locations"][0]
        location["orientation"]["north"] = "toward the Secret Lantern"
        location["features"].append(
            {
                "feature_id": "MPV2_F_SECRET_LANTERN",
                "name": "Secret Lantern",
                "position": "north_hidden",
                "state": "lit",
                "perceivable": True,
                "reachable": False,
            }
        )
        result = filter_layout_for_viewpoint(
            fixture,
            current_location_id="MPV2_LOC_TAVERN",
            active_actor_id="Acheron",
            party_known_ids=frozenset(),
            perceived_ids=frozenset({"MPV2_F_TAVERN_FRONT_DOOR"}),
        )
        self.assertEqual(result["orientation"]["position_semantics"], "schematic")
        self.assertEqual(
            result["orientation"]["origin_feature_id"],
            "MPV2_F_TAVERN_FRONT_DOOR",
        )
        self.assertNotIn("north", result["orientation"])
        self.assertNotIn("Secret Lantern", json.dumps(result))

    def test_recent_movement_is_shared_known_and_allowlisted(self) -> None:
        result = filter_layout_for_viewpoint(
            self.fixtures["transition_tower_approach"],
            current_location_id="MPV2_LOC_TOWER_APPROACH",
            active_actor_id="Acheron",
            party_known_ids=frozenset({"MPV2_LOC_VILLAGE_GREEN"}),
            recent_movement={
                "from_location_id": "MPV2_LOC_VILLAGE_GREEN",
                "to_location_id": "MPV2_LOC_TOWER_APPROACH",
                "private_note": "SECRET_SENTINEL_MOVEMENT_111",
            },
        )
        self.assertEqual(
            result["recent_movement"],
            {
                "from_location_id": "MPV2_LOC_VILLAGE_GREEN",
                "to_location_id": "MPV2_LOC_TOWER_APPROACH",
            },
        )
        self.assertNotIn("SECRET_SENTINEL_MOVEMENT_111", json.dumps(result))
        unknown_previous = filter_layout_for_viewpoint(
            self.fixtures["transition_tower_approach"],
            current_location_id="MPV2_LOC_TOWER_APPROACH",
            active_actor_id="Acheron",
            party_known_ids=frozenset(),
            recent_movement={
                "from_location_id": "MPV2_LOC_HIDDEN",
                "to_location_id": "MPV2_LOC_TOWER_APPROACH",
            },
        )
        self.assertNotIn("recent_movement", unknown_previous)

    def test_unknown_current_location_fails_closed(self) -> None:
        for fixture in self.fixtures.values():
            with self.subTest(fixture=fixture["fixture_id"]):
                with self.assertRaisesRegex(ValueError, "unknown current location"):
                    filter_layout_for_viewpoint(
                        fixture,
                        current_location_id="MPV2_LOC_DOES_NOT_EXIST",
                        active_actor_id="Acheron",
                        party_known_ids=frozenset(),
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
