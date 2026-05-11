#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Regression tests for travel-intent state sync guard.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.travel_state_sync_guard import (
    evaluate_travel_state_sync_decision,
    evaluate_travel_state_sync_guard,
    _is_topology_safe_destination,
    _is_module_graph_reachable,
)


class TestTravelStateSyncGuardBehavior(unittest.TestCase):
    """Behavior tests for deterministic travel-state guard logic."""

    def _known_locations(self):
        return [
            {"id": "NIG01", "name": "Ma's Watering Hole", "area_id": "NIG001"},
            {"id": "NIG03", "name": "Cathedral Storage", "area_id": "NIG001"},
            {"id": "NIG06", "name": "Cathedral Underlevel", "area_id": "NIG001"},
        ]

    def test_reconciles_clear_arrival_without_transition(self):
        response = {
            "narration": "You travel through the tunnel and reach Cathedral Storage.",
            "actions": [],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Room 3: Cathedral Storage", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertTrue(decision.get("valid"))
        self.assertEqual(decision.get("reconciliation"), "arrival_autocommit")
        inferred_actions = decision.get("inferred_actions", [])
        self.assertEqual(len(inferred_actions), 1)
        self.assertEqual(inferred_actions[0].get("action"), "transitionLocation")
        self.assertEqual(inferred_actions[0].get("parameters", {}).get("newLocation"), "NIG03")

    def test_allows_travel_with_transition_action(self):
        response = {
            "narration": "You travel to Cathedral Storage and take cover behind crates.",
            "actions": [{"action": "transitionLocation", "parameters": {"newLocation": "NIG03"}}],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Cathedral Storage", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertTrue(decision.get("valid"))
        self.assertEqual(decision.get("reconciliation"), "explicit_transition")

    def test_explicit_transition_to_unknown_destination_is_invalid(self):
        response = {
            "narration": "You descend into the crypt.",
            "actions": [{"action": "transitionLocation", "parameters": {"newLocation": "NIG09"}}],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ruined Cathedral Main Hall",
            current_location_id="NIG02",
            known_location_names=["Ruined Cathedral Main Hall", "Cathedral Storage", "Brother Lintar's Place"],
            known_locations=[
                {"id": "NIG02", "name": "Ruined Cathedral Main Hall", "area_id": "NIG001"},
                {"id": "NIG03", "name": "Cathedral Storage", "area_id": "NIG001"},
                {"id": "NIG08", "name": "Brother Lintar's Place", "area_id": "NIG001"},
            ],
            adjacent_location_ids=["NIG03", "NIG08", "NIG01"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG08"],
        )
        self.assertFalse(decision.get("valid"))
        self.assertIn("does not exist in module", decision.get("reason", ""))

    def test_explicit_transition_to_unreachable_destination_is_invalid(self):
        response = {
            "narration": "You press onward into the catacombs.",
            "actions": [{"action": "transitionLocation", "parameters": {"newLocation": "NIG06"}}],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ruined Cathedral Main Hall",
            current_location_id="NIG02",
            known_location_names=["Ruined Cathedral Main Hall", "Dead End Ritual Chamber"],
            known_locations=[
                {"id": "NIG02", "name": "Ruined Cathedral Main Hall", "area_id": "NIG001"},
                {"id": "NIG06", "name": "Dead End Ritual Chamber", "area_id": "NIG001"},
            ],
            adjacent_location_ids=["NIG03", "NIG08", "NIG01"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG08"],
        )
        self.assertFalse(decision.get("valid"))
        self.assertIn("not topology-safe", decision.get("reason", ""))

    def test_allows_current_location_blocker_without_transition(self):
        response = {
            "narration": "The tunnel loops and is blocked. You remain at Ma's Watering Hole.",
            "actions": [],
        }
        is_valid, reason = evaluate_travel_state_sync_guard(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Cathedral Storage", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")

    def test_allows_clarifier_without_transition(self):
        response = {
            "narration": "Which route do you choose from here before we continue?",
            "actions": [],
        }
        is_valid, reason = evaluate_travel_state_sync_guard(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Cathedral Storage", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")

    def test_rejects_contradictory_mixed_location_narration(self):
        response = {
            "narration": (
                "You reach Cathedral Storage through the tunnel. "
                "A moment later, you step up into Ma's Watering Hole."
            ),
            "actions": [],
        }
        is_valid, reason = evaluate_travel_state_sync_guard(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Cathedral Storage", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertFalse(is_valid)
        self.assertIn("contradictory", reason)

    def test_progress_turn_persists_in_transit_without_forcing_arrival(self):
        response = {
            "narration": "You make your way toward Cathedral Underlevel, lanterns raised.",
            "actions": [],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Cathedral Underlevel", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertTrue(decision.get("valid"))
        self.assertEqual(decision.get("reconciliation"), "progress_in_transit")
        inferred_actions = decision.get("inferred_actions", [])
        self.assertEqual(len(inferred_actions), 2)
        self.assertEqual(inferred_actions[0].get("action"), "updateTime")
        self.assertEqual(inferred_actions[1].get("action"), "updatePartyTracker")
        progress = inferred_actions[1].get("parameters", {}).get("worldConditions", {}).get("travelProgress", {})
        self.assertEqual(progress.get("mode"), "in_transit")
        self.assertEqual(progress.get("targetLocationId"), "NIG06")

    def test_current_location_alias_is_not_treated_as_destination(self):
        response = {
            "narration": "You leave the priest's lodging and pause to listen at the cellar door.",
            "actions": [],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Room 4: Priest's Lodging",
            current_location_id="NIG04",
            known_location_names=["Room 4: Priest's Lodging", "Room 5: Cellar Hallway"],
            known_locations=[
                {
                    "id": "NIG04",
                    "name": "Room 4: Priest's Lodging",
                    "area_id": "NIG001",
                    "source_room_title": "Priest's Lodging",
                },
                {
                    "id": "NIG05",
                    "name": "Room 5: Cellar Hallway",
                    "area_id": "NIG001",
                    "source_room_title": "Cellar Hallway",
                },
            ],
            adjacent_location_ids=["NIG05"],
            reachable_location_ids=["NIG04", "NIG05"],
        )
        self.assertTrue(decision.get("valid"))
        self.assertEqual(decision.get("reason"), "")
        self.assertEqual(decision.get("inferred_actions"), [])

    def test_user_utterance_can_resolve_honorific_place_alias_for_arrival(self):
        response = {
            "narration": "At dawn, you reach Brother Lintar's modest dwelling and see the lantern in the window.",
            "actions": [
                {"action": "rest", "parameters": {"type": "long"}},
                {"action": "updateTime", "parameters": {"timeEstimate": 480}},
            ],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            user_utterance="After resting we head to Lintar's place. Is he home?",
            known_location_names=["Brother Lintar's Place", "Ma's Watering Hole"],
            known_locations=[
                {
                    "id": "NIG01",
                    "name": "Ma's Watering Hole",
                    "area_id": "NIG001",
                    "source_room_title": "Ma's Watering Hole",
                },
                {
                    "id": "NIG08",
                    "name": "Brother Lintar's Place",
                    "area_id": "NIG001",
                    "source_room_title": "Brother Lintar's Place",
                },
            ],
            adjacent_location_ids=["NIG08", "NIG02", "NIG04"],
            reachable_location_ids=["NIG01", "NIG02", "NIG04", "NIG08"],
        )
        self.assertTrue(decision.get("valid"))
        inferred_actions = decision.get("inferred_actions", [])
        self.assertEqual(len(inferred_actions), 1)
        self.assertEqual(inferred_actions[0].get("action"), "transitionLocation")
        self.assertEqual(inferred_actions[0].get("parameters", {}).get("newLocation"), "NIG08")
        self.assertEqual(decision.get("reconciliation"), "arrival_autocommit")

    def test_narration_only_response_still_autocommits_when_user_utterance_clearly_arrives(self):
        response = {
            "narration": "The party stands beneath the inn's dim rafters, deciding what to do next.",
            "actions": [],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            user_utterance="We leave Ma's and walk to Lintar's place, knock on the door to see if he's in.",
            known_location_names=["Brother Lintar's Place", "Ma's Watering Hole"],
            known_locations=[
                {"id": "NIG01", "name": "Ma's Watering Hole", "area_id": "NIG001", "source_room_title": "Ma's Watering Hole"},
                {"id": "NIG08", "name": "Brother Lintar's Place", "area_id": "NIG001", "source_room_title": "Brother Lintar's Place"},
            ],
            adjacent_location_ids=["NIG08", "NIG02", "NIG04"],
            reachable_location_ids=["NIG01", "NIG02", "NIG04", "NIG08"],
        )
        inferred_actions = decision.get("inferred_actions", [])
        self.assertEqual(len(inferred_actions), 1)
        self.assertEqual(inferred_actions[0].get("action"), "transitionLocation")
        self.assertEqual(inferred_actions[0].get("parameters", {}).get("newLocation"), "NIG08")

    def test_ambiguous_prose_fails_open(self):
        response = {
            "narration": "Cold air moves through the stone and the lantern trembles.",
            "actions": [],
        }
        is_valid, reason = evaluate_travel_state_sync_guard(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Cathedral Storage", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")

    def test_impossible_destination_is_blocked(self):
        response = {
            "narration": "You reach Forbidden Catacombs beyond the ridge.",
            "actions": [],
        }
        is_valid, reason = evaluate_travel_state_sync_guard(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Forbidden Catacombs", "Ma's Watering Hole"],
            known_locations=[
                {"id": "NIG01", "name": "Ma's Watering Hole", "area_id": "NIG001"},
                {"id": "NIG99", "name": "Forbidden Catacombs", "area_id": "NIG001"},
            ],
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertFalse(is_valid)
        self.assertIn("topology-safe", reason)

    def test_non_travel_turn_is_unchanged(self):
        response = {
            "narration": "You sit by the hearth and review your notes.",
            "actions": [],
        }
        is_valid, reason = evaluate_travel_state_sync_guard(
            response_json=response,
            is_travel_intent=False,
            current_location_name="Ma's Watering Hole",
            current_location_id="NIG01",
            known_location_names=["Cathedral Storage", "Ma's Watering Hole"],
            known_locations=self._known_locations(),
            adjacent_location_ids=["NIG03", "NIG02"],
            reachable_location_ids=["NIG01", "NIG02", "NIG03", "NIG06"],
        )
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")


class TestTravelStateSyncGuardSourceContracts(unittest.TestCase):
    """Source-contract checks for main.py integration."""

    def test_main_calls_travel_state_sync_guard(self):
        main_py_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main.py",
        )
        with open(main_py_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn(
            "evaluate_travel_state_sync_decision",
            content,
            "main.py should invoke travel-state sync guard",
        )

    def test_main_supports_reconcile_first_inferred_actions(self):
        main_py_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main.py",
        )
        with open(main_py_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn(
            "Travel reconcile-first injected",
            content,
            "main.py should inject inferred travel actions when reconciliation is safe",
        )

    def test_main_marks_travel_state_sync_as_deterministic(self):
        main_py_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main.py",
        )
        with open(main_py_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn(
            "classify_validator_failure_domains",
            content,
            "main.py should classify travel-state guard failures through domain helper",
        )
        self.assertIn(
            '"travel_state_sync"',
            content,
            "main.py should treat travel_state_sync as deterministic domain",
        )


class TestCrossAreaTopology(unittest.TestCase):
    """Regression tests for cross-area same-module topology reachability."""

    def _thornwood_known_locations(self):
        """Return a minimal Thornwood location catalog with cross-area edges."""
        return [
            {
                "id": "NC02",
                "name": "Blighted Thornbriar Grove",
                "area_id": "NCW001",
                "connectivity": ["NC01", "NC04", "NC05"],
            },
            {
                "id": "NC01",
                "name": "Corrupted Entry Cave",
                "area_id": "NCW001",
                "connectivity": ["NC02", "TW05"],
            },
            {
                "id": "NC04",
                "name": "Doomed Explorer's Camp",
                "area_id": "NCW001",
                "connectivity": ["NC02"],
            },
            {
                "id": "NC05",
                "name": "The Corrupted Nexus",
                "area_id": "NCW001",
                "connectivity": ["NC02"],
            },
            {
                "id": "TW05",
                "name": "Bandit Stronghold",
                "area_id": "TWW001",
                "connectivity": ["NC01", "TW02", "TW04"],
            },
            {
                "id": "TW02",
                "name": "Bandit Trail",
                "area_id": "TWW001",
                "connectivity": ["TW05"],
            },
            {
                "id": "RO06",
                "name": "North Tower Overlook",
                "area_id": "RO0001",
                "connectivity": [],
            },
        ]

    def test_cross_area_path_accepted_for_explicit_transition(self):
        """NC02 -> TW05 via NC01 is topology-safe for explicit transitionLocation."""
        response = {
            "narration": "Thane leads the party toward the bandit stronghold.",
            "actions": [
                {"action": "transitionLocation", "parameters": {"newLocation": "TW05"}}
            ],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Blighted Thornbriar Grove",
            current_location_id="NC02",
            known_location_names=["Blighted Thornbriar Grove"],
            known_locations=self._thornwood_known_locations(),
            adjacent_location_ids=["NC01", "NC04", "NC05"],
            reachable_location_ids=["NC01", "NC02", "NC04", "NC05"],
        )
        self.assertTrue(decision.get("valid"), f"Expected valid, got: {decision.get('reason')}")
        self.assertEqual(decision.get("reconciliation"), "explicit_transition")

    def test_cross_area_path_accepted_for_arrival_narration(self):
        """NC02 -> TW05 is topology-safe for narrator-claimed arrival."""
        response = {
            "narration": "Thane leads the stretcher bearers through the grove's outer edge and you arrive at the Bandit Stronghold just as dusk settles.",
            "actions": [],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Blighted Thornbriar Grove",
            current_location_id="NC02",
            known_location_names=[
                "Blighted Thornbriar Grove",
                "Bandit Stronghold",
                "Corrupted Entry Cave",
                "Doomed Explorer's Camp",
                "The Corrupted Nexus",
                "Bandit Trail",
            ],
            known_locations=self._thornwood_known_locations(),
            adjacent_location_ids=["NC01", "NC04", "NC05"],
            reachable_location_ids=["NC01", "NC02", "NC04", "NC05"],
        )
        self.assertTrue(decision.get("valid"), f"Expected valid, got: {decision.get('reason')}")

    def test_unreachable_destination_blocked(self):
        """RO06 is in the module catalog but no graph path exists from NC02."""
        response = {
            "narration": "You arrive at North Tower Overlook.",
            "actions": [
                {"action": "transitionLocation", "parameters": {"newLocation": "RO06"}}
            ],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Blighted Thornbriar Grove",
            current_location_id="NC02",
            known_location_names=["Blighted Thornbriar Grove", "North Tower Overlook"],
            known_locations=self._thornwood_known_locations(),
            adjacent_location_ids=["NC01", "NC04", "NC05"],
            reachable_location_ids=["NC01", "NC02", "NC04", "NC05"],
        )
        self.assertFalse(decision.get("valid"))
        self.assertIn("not topology-safe", decision.get("reason", ""))

    def test_graph_reachability_caches_nothing(self):
        """BFS reachability returns True for a valid multi-hop path."""
        locs = self._thornwood_known_locations()
        result = _is_module_graph_reachable(
            destination_id="TW05",
            current_location_id="NC02",
            known_locations=locs,
        )
        self.assertTrue(result)

    def test_graph_reachability_rejects_unreachable(self):
        """BFS reachability returns False when no path exists."""
        locs = self._thornwood_known_locations()
        result = _is_module_graph_reachable(
            destination_id="RO06",
            current_location_id="NC02",
            known_locations=locs,
        )
        self.assertFalse(result)

    def test_graph_reachability_rejects_missing_destination(self):
        """BFS reachability returns False for unknown destination ID."""
        locs = self._thornwood_known_locations()
        result = _is_module_graph_reachable(
            destination_id="ZZ99",
            current_location_id="NC02",
            known_locations=locs,
        )
        self.assertFalse(result)

    def test_graph_reachability_no_false_positives_on_all_entries(self):
        """BFS does not accept destinations just because they exist in the catalog."""
        locs = self._thornwood_known_locations()
        for loc in locs:
            loc_id = loc["id"]
            reachable = _is_module_graph_reachable(
                destination_id=loc_id,
                current_location_id="NC02",
                known_locations=locs,
            )
            if loc_id in ("NC01", "NC02", "NC04", "NC05", "TW05", "TW02"):
                self.assertTrue(
                    reachable,
                    f"Expected {loc_id} to be reachable from NC02 via graph",
                )
            else:
                self.assertFalse(
                    reachable,
                    f"Expected {loc_id} to be unreachable from NC02",
                )

    def test_topology_safe_falls_back_to_graph(self):
        """_is_topology_safe_destination uses graph reachability as third pass."""
        locs = self._thornwood_known_locations()
        safe = _is_topology_safe_destination(
            destination_id="TW05",
            current_location_id="NC02",
            adjacent_location_ids=["NC01", "NC04", "NC05"],
            reachable_location_ids=["NC01", "NC02", "NC04", "NC05"],
            known_locations=locs,
        )
        self.assertTrue(safe)

    def test_topology_safe_rejects_no_path(self):
        """_is_topology_safe_destination rejects unreachable catalog entries."""
        locs = self._thornwood_known_locations()
        safe = _is_topology_safe_destination(
            destination_id="RO06",
            current_location_id="NC02",
            adjacent_location_ids=["NC01", "NC04", "NC05"],
            reachable_location_ids=["NC01", "NC02", "NC04", "NC05"],
            known_locations=locs,
        )
        self.assertFalse(safe)

    def test_scene_follower_guided_travel_to_cross_area_destination(self):
        """Present follower Thane at NC02 guiding toward TW05 is valid."""
        response = {
            "narration": "Thane gives no speech at first -- just a sharp turn of the head and a crooked hand pointing away from the cave mouth, toward the thinner briars along the grove's outer edge. He seems to favor a safer line that skirts the corrupted caves entirely, likely angling you toward the Doomed Explorer's Camp before you try to circle back toward the bandit stronghold. If you follow him, it should be the long way, but the cleaner one.",
            "actions": [],
        }
        decision = evaluate_travel_state_sync_decision(
            response_json=response,
            is_travel_intent=True,
            current_location_name="Blighted Thornbriar Grove",
            current_location_id="NC02",
            user_utterance="I lash Thane to the stretcher... Mush! Lead the way back to sanctuary at my old mate Gorvek's bandit stronghold!",
            known_location_names=[
                "Blighted Thornbriar Grove",
                "Bandit Stronghold",
                "Corrupted Entry Cave",
                "Doomed Explorer's Camp",
                "The Corrupted Nexus",
                "Bandit Trail",
            ],
            known_locations=self._thornwood_known_locations(),
            adjacent_location_ids=["NC01", "NC04", "NC05"],
            reachable_location_ids=["NC01", "NC02", "NC04", "NC05"],
        )
        self.assertTrue(decision.get("valid"), f"Expected valid, got: {decision.get('reason')}")


if __name__ == "__main__":
    unittest.main()
