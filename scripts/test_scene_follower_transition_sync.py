# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regression tests for scene follower transition synchronization."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.file_operations import safe_write_json
import utils.scene_follower_state as follower_state
from utils.multi_pc_dm_note import build_multi_pc_dm_note


class TestSceneFollowerTransitionSync(unittest.TestCase):
    """Validate conservative follower sync after party transition."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="scene_follower_sync_")
        self.original_store_path = follower_state.FOLLOWER_STORE_PATH
        self.temp_store_path = os.path.join(self.temp_dir, "scene_followers.json")
        follower_state.FOLLOWER_STORE_PATH = self.temp_store_path

    def tearDown(self):
        follower_state.FOLLOWER_STORE_PATH = self.original_store_path

    def _write_store(self, records):
        safe_write_json(self.temp_store_path, {"followers": records})

    def test_traveling_follower_moves_on_transition(self):
        self._write_store(
            [
                {
                    "entity_id": "corrupted_ranger_thane",
                    "display_name": "Corrupted Ranger Thane",
                    "entity_type": "monster",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "present",
                    "current_location": "NC02",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        result = follower_state.sync_traveling_followers_to_location("NC02", "NC05")
        self.assertIn("corrupted_ranger_thane", result.get("moved", []))

        store = follower_state.load_followers()
        record = follower_state.find_follower(store, "corrupted_ranger_thane")
        self.assertEqual(record.get("current_location"), "NC05")

    def test_location_bound_follower_does_not_move(self):
        self._write_store(
            [
                {
                    "entity_id": "nexus_warden",
                    "display_name": "Nexus Warden",
                    "entity_type": "monster",
                    "disposition": "hostile",
                    "lifecycle_state": "present",
                    "current_location": "NC02",
                    "since_turn": 1,
                    "visible_in_strip": False,
                }
            ]
        )

        result = follower_state.sync_traveling_followers_to_location("NC02", "NC05")
        self.assertEqual(result.get("moved", []), [])
        self.assertIn("nexus_warden", result.get("skipped", []))

        store = follower_state.load_followers()
        record = follower_state.find_follower(store, "nexus_warden")
        self.assertEqual(record.get("current_location"), "NC02")

    def test_absent_follower_does_not_move(self):
        self._write_store(
            [
                {
                    "entity_id": "escort_mirna",
                    "display_name": "Escort Mirna",
                    "entity_type": "npc",
                    "disposition": "escorted",
                    "lifecycle_state": "hidden",
                    "current_location": "NC02",
                    "since_turn": 1,
                    "visible_in_strip": False,
                }
            ]
        )

        result = follower_state.sync_traveling_followers_to_location("NC02", "NC05")
        self.assertEqual(result.get("moved", []), [])

        store = follower_state.load_followers()
        record = follower_state.find_follower(store, "escort_mirna")
        self.assertEqual(record.get("current_location"), "NC02")

    def test_follower_at_other_location_does_not_teleport(self):
        self._write_store(
            [
                {
                    "entity_id": "thane",
                    "display_name": "Thane",
                    "entity_type": "npc",
                    "disposition": "following",
                    "lifecycle_state": "present",
                    "current_location": "NC07",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        result = follower_state.sync_traveling_followers_to_location("NC02", "NC05")
        self.assertEqual(result.get("moved", []), [])

        store = follower_state.load_followers()
        record = follower_state.find_follower(store, "thane")
        self.assertEqual(record.get("current_location"), "NC07")

    def test_restrained_captive_moves_on_transition(self):
        """restrained + guarded_guide + visible follower moves on transition."""
        self._write_store(
            [
                {
                    "entity_id": "corrupted_ranger_thane",
                    "display_name": "Corrupted Ranger Thane",
                    "entity_type": "monster",
                    "monster_type": "Corrupted Ranger Thane",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "restrained",
                    "current_location": "NC04",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        result = follower_state.sync_traveling_followers_to_location("NC04", "NC02")
        self.assertIn("corrupted_ranger_thane", result.get("moved", []))

        store = follower_state.load_followers()
        record = follower_state.find_follower(store, "corrupted_ranger_thane")
        self.assertEqual(record.get("current_location"), "NC02")

    def test_cleanup_states_do_not_move(self):
        """hidden/released/escaped/dead/joined_party/combat_started followers stay put."""
        cleanup_states = ["hidden", "released", "escaped", "dead", "joined_party", "combat_started"]
        for state in cleanup_states:
            self._write_store(
                [
                    {
                        "entity_id": "test_follower",
                        "display_name": "Test Follower",
                        "entity_type": "npc",
                        "disposition": "following",
                        "lifecycle_state": state,
                        "current_location": "NC04",
                        "since_turn": 1,
                        "visible_in_strip": True,
                    }
                ]
            )

            result = follower_state.sync_traveling_followers_to_location("NC04", "NC02")
            self.assertEqual(
                result.get("moved", []),
                [],
                f"Cleanup state '{state}' should not move",
            )


class TestSceneFollowerDMNoteProjection(unittest.TestCase):
    """Validate DM Note projection of present scene followers."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="scene_follower_dm_note_")
        self.original_store_path = follower_state.FOLLOWER_STORE_PATH
        self.temp_store_path = os.path.join(self.temp_dir, "scene_followers.json")
        follower_state.FOLLOWER_STORE_PATH = self.temp_store_path

    def tearDown(self):
        follower_state.FOLLOWER_STORE_PATH = self.original_store_path

    def _write_store(self, records):
        safe_write_json(self.temp_store_path, {"followers": records})

    def _base_party_state(self):
        return {
            "module": "",
            "partyMembers": [],
            "partyNPCs": [],
            "worldConditions": {
                "currentLocationId": "NC05",
                "currentLocation": "North Chapel",
                "currentAreaId": "NC001",
                "currentArea": "Nexus Chapel",
            },
        }

    def test_dm_note_includes_present_scene_followers_without_party_npcs(self):
        self._write_store(
            [
                {
                    "entity_id": "corrupted_ranger_thane",
                    "display_name": "Corrupted Ranger Thane",
                    "entity_type": "monster",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "present",
                    "current_location": "NC05",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        party_state = self._base_party_state()
        dm_note = build_multi_pc_dm_note(
            party_tracker_data=party_state,
            location_data=None,
            world_conditions=party_state["worldConditions"],
            date_time_str="1492 Ches 20 08:00",
            current_season="Spring",
            current_module_name="Nexus",
            current_location_name="North Chapel",
            current_location_id="NC05",
            current_area_name="Nexus Chapel",
            plot_points_str="None",
            side_quests_str="None",
            monsters_str="None",
            traps_str="None",
            connected_locations_str="NC04, NC06",
        )

        self.assertIn("--- SCENE FOLLOWERS PRESENT HERE ---", dm_note)
        self.assertIn("Corrupted Ranger Thane", dm_note)

    def test_dm_note_excludes_followers_at_other_location(self):
        self._write_store(
            [
                {
                    "entity_id": "corrupted_ranger_thane",
                    "display_name": "Corrupted Ranger Thane",
                    "entity_type": "monster",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "present",
                    "current_location": "NC07",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        party_state = self._base_party_state()
        dm_note = build_multi_pc_dm_note(
            party_tracker_data=party_state,
            location_data=None,
            world_conditions=party_state["worldConditions"],
            date_time_str="1492 Ches 20 08:00",
            current_season="Spring",
            current_module_name="Nexus",
            current_location_name="North Chapel",
            current_location_id="NC05",
            current_area_name="Nexus Chapel",
            plot_points_str="None",
            side_quests_str="None",
            monsters_str="None",
            traps_str="None",
            connected_locations_str="NC04, NC06",
        )

        self.assertNotIn("--- SCENE FOLLOWERS PRESENT HERE ---", dm_note)

    def test_dm_note_includes_restrained_follower_at_current_location(self):
        """Restrained captive with guarded_guide disposition appears in DM Note."""
        self._write_store(
            [
                {
                    "entity_id": "corrupted_ranger_thane",
                    "display_name": "Corrupted Ranger Thane",
                    "entity_type": "monster",
                    "monster_type": "Corrupted Ranger Thane",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "restrained",
                    "current_location": "NC05",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        party_state = self._base_party_state()
        dm_note = build_multi_pc_dm_note(
            party_tracker_data=party_state,
            location_data=None,
            world_conditions=party_state["worldConditions"],
            date_time_str="1492 Ches 20 08:00",
            current_season="Spring",
            current_module_name="Nexus",
            current_location_name="North Chapel",
            current_location_id="NC05",
            current_area_name="Nexus Chapel",
            plot_points_str="None",
            side_quests_str="None",
            monsters_str="None",
            traps_str="None",
            connected_locations_str="NC04, NC06",
        )

        self.assertIn("--- SCENE FOLLOWERS PRESENT HERE ---", dm_note)
        self.assertIn("Corrupted Ranger Thane", dm_note)

    def test_dm_note_excludes_cleanup_state_followers(self):
        """hidden follower is excluded from DM Note even at current location."""
        self._write_store(
            [
                {
                    "entity_id": "test_follower",
                    "display_name": "Test Follower",
                    "entity_type": "npc",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "hidden",
                    "current_location": "NC05",
                    "since_turn": 1,
                    "visible_in_strip": False,
                }
            ]
        )

        party_state = self._base_party_state()
        dm_note = build_multi_pc_dm_note(
            party_tracker_data=party_state,
            location_data=None,
            world_conditions=party_state["worldConditions"],
            date_time_str="1492 Ches 20 08:00",
            current_season="Spring",
            current_module_name="Nexus",
            current_location_name="North Chapel",
            current_location_id="NC05",
            current_area_name="Nexus Chapel",
            plot_points_str="None",
            side_quests_str="None",
            monsters_str="None",
            traps_str="None",
            connected_locations_str="NC04, NC06",
        )

        self.assertNotIn("--- SCENE FOLLOWERS PRESENT HERE ---", dm_note)


class TestAuthoritativePacketSceneFollowers(unittest.TestCase):
    """Validate scene followers appear in the authoritative state packet."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="scene_follower_packet_")
        self.original_store_path = follower_state.FOLLOWER_STORE_PATH
        self.temp_store_path = os.path.join(self.temp_dir, "scene_followers.json")
        follower_state.FOLLOWER_STORE_PATH = self.temp_store_path

    def tearDown(self):
        follower_state.FOLLOWER_STORE_PATH = self.original_store_path

    def _write_store(self, records):
        safe_write_json(self.temp_store_path, {"followers": records})

    def test_packet_includes_restrained_follower_at_current_location(self):
        """Authoritative packet includes restrained follower at current location."""
        self._write_store(
            [
                {
                    "entity_id": "corrupted_ranger_thane",
                    "display_name": "Corrupted Ranger Thane",
                    "entity_type": "monster",
                    "monster_type": "Corrupted Ranger Thane",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "restrained",
                    "current_location": "NC02",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        from utils.authoritative_state_packet import build_authoritative_state_packet

        party_data = {
            "module": "The_Thornwood_Watch",
            "partyMembers": [],
            "partyNPCs": [],
            "worldConditions": {
                "currentLocationId": "NC02",
                "currentLocation": "Blighted Thornbriar Grove",
                "currentAreaId": "NCW001",
                "currentArea": "Northern Corrupted Woods",
            },
        }
        packet = build_authoritative_state_packet(party_data)
        followers = packet.get("scene_followers", [])
        self.assertTrue(any("corrupted_ranger_thane" in str(r) for r in followers))

    def test_packet_excludes_follower_at_other_location(self):
        """Authoritative packet excludes follower not at current location."""
        self._write_store(
            [
                {
                    "entity_id": "corrupted_ranger_thane",
                    "display_name": "Corrupted Ranger Thane",
                    "entity_type": "monster",
                    "monster_type": "Corrupted Ranger Thane",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "restrained",
                    "current_location": "NC07",
                    "since_turn": 1,
                    "visible_in_strip": True,
                }
            ]
        )

        from utils.authoritative_state_packet import build_authoritative_state_packet

        party_data = {
            "module": "The_Thornwood_Watch",
            "partyMembers": [],
            "partyNPCs": [],
            "worldConditions": {
                "currentLocationId": "NC02",
                "currentLocation": "Blighted Thornbriar Grove",
                "currentAreaId": "NCW001",
                "currentArea": "Northern Corrupted Woods",
            },
        }
        packet = build_authoritative_state_packet(party_data)
        followers = packet.get("scene_followers", [])
        self.assertFalse(any("corrupted_ranger_thane" in str(r) for r in followers))

    def test_packet_excludes_hidden_follower(self):
        """Authoritative packet excludes hidden follower even at current location."""
        self._write_store(
            [
                {
                    "entity_id": "hidden_follower",
                    "display_name": "Hidden Follower",
                    "entity_type": "npc",
                    "disposition": "guarded_guide",
                    "lifecycle_state": "hidden",
                    "current_location": "NC02",
                    "since_turn": 1,
                    "visible_in_strip": False,
                }
            ]
        )

        from utils.authoritative_state_packet import build_authoritative_state_packet

        party_data = {
            "module": "The_Thornwood_Watch",
            "partyMembers": [],
            "partyNPCs": [],
            "worldConditions": {
                "currentLocationId": "NC02",
                "currentLocation": "Blighted Thornbriar Grove",
                "currentAreaId": "NCW001",
                "currentArea": "Northern Corrupted Woods",
            },
        }
        packet = build_authoritative_state_packet(party_data)
        followers = packet.get("scene_followers", [])
        self.assertFalse(any("hidden_follower" in str(r) for r in followers))
