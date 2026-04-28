#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regression tests for narrator location exclusivity and exit grounding guards."""

import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.narrator_location_exclusivity_guard import (  # noqa: E402
    evaluate_authored_exit_grounding_decision,
    evaluate_location_exclusivity_decision,
    normalize_party_member_name,
)
from utils.scene_follower_state import (  # noqa: E402
    create_follower_record,
    find_follower,
    follower_at_location,
    get_follower_records,
    move_follower_to_location,
    remove_follower_record,
    validate_follower_schema,
)


class TestLocationExclusivityDecision(unittest.TestCase):
    """Behavior tests for metadata-first and fallback exclusivity guard."""

    def test_metadata_blocks_present_scene_anchor_without_transition(self):
        response_json = {
            "narration": "The Nexus Warden stands before you at the ritual altar.",
            "actions": [],
        }
        module_locations = [
            {"id": "A01", "name": "Outer Hall"},
            {
                "id": "B02",
                "name": "Nexus Chamber",
                "sceneAuthority": {
                    "presentSceneAnchors": [
                        {
                            "anchorId": "nexus_warden",
                            "aliases": ["Nexus Warden", "ritual altar"],
                            "foreshadowAllowed": True,
                        }
                    ]
                },
            },
        ]

        decision = evaluate_location_exclusivity_decision(
            response_json=response_json,
            module_name="Any_Module",
            current_location_id="A01",
            module_locations=module_locations,
        )

        self.assertFalse(decision.get("valid"))
        self.assertIn("Location exclusivity violation", decision.get("reason", ""))

    def test_metadata_allows_foreshadow_without_present_scene_instantiation(self):
        response_json = {
            "narration": "You sense the Nexus Warden deeper ahead, a distant ritual pulse in the stone.",
            "actions": [],
        }
        module_locations = [
            {"id": "A01", "name": "Outer Hall"},
            {
                "id": "B02",
                "name": "Nexus Chamber",
                "sceneAuthority": {
                    "presentSceneAnchors": [
                        {
                            "anchorId": "nexus_warden",
                            "aliases": ["Nexus Warden"],
                            "foreshadowAllowed": True,
                        }
                    ]
                },
            },
        ]

        decision = evaluate_location_exclusivity_decision(
            response_json=response_json,
            module_name="Any_Module",
            current_location_id="A01",
            module_locations=module_locations,
        )

        self.assertTrue(decision.get("valid"))

    def test_metadata_allows_present_scene_when_transition_committed(self):
        response_json = {
            "narration": "The Nexus Warden stands before you at the ritual altar.",
            "actions": [
                {
                    "action": "transitionLocation",
                    "parameters": {"newLocation": "B02"},
                }
            ],
        }
        module_locations = [
            {"id": "A01", "name": "Outer Hall"},
            {
                "id": "B02",
                "name": "Nexus Chamber",
                "sceneAuthority": {
                    "presentSceneAnchors": [
                        {
                            "anchorId": "nexus_warden",
                            "aliases": ["Nexus Warden", "ritual altar"],
                            "foreshadowAllowed": True,
                        }
                    ]
                },
            },
        ]

        decision = evaluate_location_exclusivity_decision(
            response_json=response_json,
            module_name="Any_Module",
            current_location_id="A01",
            module_locations=module_locations,
        )

        self.assertTrue(decision.get("valid"))

    def test_nc01_allows_foreshadowing(self):
        response_json = {
            "narration": "You sense Malarok deeper ahead, and a distant ritual pulse echoes through the cave.",
            "actions": [],
        }

        decision = evaluate_location_exclusivity_decision(
            response_json=response_json,
            module_name="The_Thornwood_Watch",
            current_location_id="NC01",
        )

        self.assertTrue(decision.get("valid"))

    def test_nc01_blocks_nc05_present_scene_anchor_without_transition(self):
        response_json = {
            "narration": "Malarok stands before you at the Voidstone altar, right here in this chamber.",
            "actions": [],
        }

        decision = evaluate_location_exclusivity_decision(
            response_json=response_json,
            module_name="The_Thornwood_Watch",
            current_location_id="NC01",
        )

        self.assertFalse(decision.get("valid"))
        self.assertIn("Location exclusivity violation", decision.get("reason", ""))

    def test_nc01_allows_present_scene_anchor_when_transition_committed(self):
        response_json = {
            "narration": "Malarok stands before you at the Voidstone altar.",
            "actions": [
                {
                    "action": "transitionLocation",
                    "parameters": {"newLocation": "NC05"},
                }
            ],
        }

        decision = evaluate_location_exclusivity_decision(
            response_json=response_json,
            module_name="The_Thornwood_Watch",
            current_location_id="NC01",
        )

        self.assertTrue(decision.get("valid"))


class TestAuthoredExitGroundingDecision(unittest.TestCase):
    """Behavior tests for authored-adjacent route-block grounding guard."""

    def setUp(self):
        self.current_location_data = {
            "locationId": "NC01",
            "connectivity": ["NC02", "NC03"],
        }

    def test_blocks_unsupported_route_claim_when_authored_adjacency_exists(self):
        response_json = {
            "narration": "The path to NC02 is blocked and impassable.",
            "actions": [],
        }

        decision = evaluate_authored_exit_grounding_decision(
            response_json=response_json,
            current_location_id="NC01",
            current_location_data=self.current_location_data,
        )

        self.assertFalse(decision.get("valid"))
        self.assertIn("Authored-exit grounding violation", decision.get("reason", ""))

    def test_allows_block_claim_with_authored_blocker_metadata(self):
        response_json = {
            "narration": "The path to NC02 is blocked by a cave-in.",
            "actions": [],
        }
        location_data = {
            "locationId": "NC01",
            "connectivity": ["NC02", "NC03"],
            "transition_hints": [
                {
                    "type": "blocked_exit",
                    "description": "North tunnel blocked by cave-in debris.",
                }
            ],
        }

        decision = evaluate_authored_exit_grounding_decision(
            response_json=response_json,
            current_location_id="NC01",
            current_location_data=location_data,
        )

        self.assertTrue(decision.get("valid"))

    def test_allows_block_claim_with_deterministic_action_support(self):
        response_json = {
            "narration": "The route ahead is blocked by hostile defenders.",
            "actions": [
                {
                    "action": "createEncounter",
                    "parameters": {
                        "encounterSummary": "Hostiles block the passage.",
                        "player": "Acheron",
                        "npcs": [],
                        "monsters": ["Bandit"],
                    },
                }
            ],
        }

        decision = evaluate_authored_exit_grounding_decision(
            response_json=response_json,
            current_location_id="NC01",
            current_location_data=self.current_location_data,
        )

        self.assertTrue(decision.get("valid"))

    def test_scene_authority_metadata_does_not_regress_exit_grounding(self):
        response_json = {
            "narration": "The path to NC02 is blocked and impassable.",
            "actions": [],
        }
        location_data = {
            "locationId": "NC01",
            "connectivity": ["NC02", "NC03"],
            "sceneAuthority": {
                "presentSceneAnchors": [
                    {
                        "anchorId": "dummy_anchor",
                        "aliases": ["Dummy Anchor"],
                    }
                ]
            },
        }

        decision = evaluate_authored_exit_grounding_decision(
            response_json=response_json,
            current_location_id="NC01",
            current_location_data=location_data,
        )

        self.assertFalse(decision.get("valid"))
        self.assertIn("Authored-exit grounding violation", decision.get("reason", ""))


class TestMainIntegrationSourceGuards(unittest.TestCase):
    """Source guards to keep main validation integration wired."""

    def test_main_calls_location_exclusivity_and_exit_grounding_guards(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_path = os.path.join(repo_root, "main.py")
        with open(main_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("evaluate_location_exclusivity_decision", source)
        self.assertIn("evaluate_authored_exit_grounding_decision", source)
        self.assertIn("module_locations=known_locations", source)
        self.assertIn("Narrator location exclusivity guard failed", source)
        self.assertIn("Narrator authored-exit grounding guard failed", source)

    def test_main_passes_party_member_names_to_guard(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_path = os.path.join(repo_root, "main.py")
        with open(main_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("party_member_names", source)
        self.assertIn("normalize_party_member_name", source)


class TestPartyIdentityCollision(unittest.TestCase):
    """Party member identification collision resolution for location exclusivity."""

    def _make_anchor_location(self, location_id, aliases):
        return [
            {"id": "CURR", "name": "Current Room"},
            {
                "id": location_id,
                "name": "Other Room",
                "sceneAuthority": {
                    "presentSceneAnchors": [
                        {"anchorId": "test_anchor", "aliases": aliases}
                    ]
                },
            },
        ]

    def test_bare_party_member_alias_no_longer_fails(self):
        """Task 4.1: Bare party member alias is ignored as identity collision."""
        response = {
            "narration": "Vitreol wakes by the cold fire.",
            "actions": [],
        }
        party_names = {normalize_party_member_name("Vitreol")}

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=self._make_anchor_location("OTHER", ["Vitreol", "corrupted Vitreol"]),
            party_member_names=party_names,
        )

        self.assertTrue(decision.get("valid"), "Bare party alias should be exempt")

    def test_distinctive_alias_still_fails(self):
        """Task 4.2: Distinctive multi-word alias still triggers exclusivity."""
        response = {
            "narration": "corrupted Vitreol stands before you.",
            "actions": [],
        }
        party_names = {normalize_party_member_name("Vitreol")}

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=self._make_anchor_location("OTHER", ["Vitreol", "corrupted Vitreol"]),
            party_member_names=party_names,
        )

        self.assertFalse(decision.get("valid"), "Distinctive alias should still fail")

    def test_non_party_off_location_anchor_still_fails(self):
        """Task 4.3: Non-party off-location anchor still fails."""
        response = {
            "narration": "The Thornwraith stands before you.",
            "actions": [],
        }
        party_names = {normalize_party_member_name("Vitreol")}

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=self._make_anchor_location("OTHER", ["Thornwraith"]),
            party_member_names=party_names,
        )

        self.assertFalse(decision.get("valid"), "Non-party anchor should still fail")

    def test_no_party_names_parameter_preserves_strict_behavior(self):
        """Task 4.3: Existing callers without party_member_names remain strict."""
        response = {
            "narration": "Vitreol stands before you.",
            "actions": [],
        }

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=self._make_anchor_location("OTHER", ["Vitreol"]),
        )

        self.assertFalse(decision.get("valid"),
                         "Without party_member_names, strict behavior must remain")

    def test_normalize_party_member_name_available(self):
        """Helper function is importable and produces consistent output."""
        canonical = normalize_party_member_name("Anselara")
        self.assertEqual(canonical, "anselara")
        canonical2 = normalize_party_member_name("Sir Gawain the Pure")
        self.assertEqual(canonical2, "sir gawain the pure")


class TestFollowerRecordExclusivityIntegration(unittest.TestCase):
    """Scene-entity follower authorization in location exclusivity guard."""

    def _make_follower_records(self, mapping):
        return {
            str(k).strip().lower(): str(v).strip().upper()
            for k, v in mapping.items()
        }

    def _make_anchor_location(self, location_id, aliases):
        return [{
            "id": location_id,
            "name": f"{location_id} Name",
            "sceneAuthority": {
                "presentSceneAnchors": [{
                    "anchorId": f"anchor_{location_id}",
                    "aliases": aliases,
                }]
            },
        }]

    def _make_response(self, narration):
        return {"narration": narration, "actions": []}

    def test_follower_at_current_location_authorizes_present_scene(self):
        """Follower record at tracked location allows anchor present-scene claim."""
        response = self._make_response("Blarg stands before you, ready to follow.")
        modules = self._make_anchor_location("OTHER", ["Blarg"])

        follower_records = {"blarg": "CURR"}

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=modules,
            follower_records=follower_records,
        )
        self.assertTrue(decision.get("valid"),
                        "Follower at current location must authorize present scene")

    def test_follower_at_other_location_still_blocks_present_scene(self):
        """Follower at a different location does NOT authorize present scene."""
        response = self._make_response("Blarg stands before you, ready to follow.")
        modules = self._make_anchor_location("OTHER", ["Blarg"])

        follower_records = {"blarg": "OTHER"}  # follower at the anchor location

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=modules,
            follower_records=follower_records,
        )
        self.assertFalse(decision.get("valid"),
                         "Follower not at current location must still block")

    def test_no_follower_record_still_blocks_present_scene(self):
        """No follower record = unchanged strict behavior."""
        response = self._make_response("Blarg stands before you, ready to follow.")
        modules = self._make_anchor_location("OTHER", ["Blarg"])

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=modules,
        )
        self.assertFalse(decision.get("valid"),
                         "No follower_records must preserve strict behavior")

    def test_follower_empty_dict_still_blocks_present_scene(self):
        """Empty follower_records dict must not authorize anything."""
        response = self._make_response("Blarg stands before you, ready to follow.")
        modules = self._make_anchor_location("OTHER", ["Blarg"])

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=modules,
            follower_records={},
        )
        self.assertFalse(decision.get("valid"),
                         "Empty follower_records must preserve strict behavior")

    def test_follower_not_in_follower_records_still_blocks(self):
        """Alias not present in follower_records is not authorized."""
        response = self._make_response("Nexus Warden stands before you.")
        modules = self._make_anchor_location("OTHER", ["Nexus Warden"])

        follower_records = {"blarg": "CURR"}  # different follower

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=modules,
            follower_records=follower_records,
        )
        self.assertFalse(decision.get("valid"),
                         "Non-matching follower must still block")

    def test_follower_records_with_party_names_both_skip(self):
        """Both party_member_names and follower_records filtering apply."""
        response = self._make_response("Blarg stands before you.")
        modules = self._make_anchor_location("OTHER", ["Blarg"])

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=modules,
            party_member_names={"blarg"},
            follower_records={"blarg": "CURR"},
        )
        self.assertTrue(decision.get("valid"),
                        "Both filters should work together")

    def test_follower_with_hyphenated_identity_normalizes_correctly(self):
        """Follower entity_id with hyphens normalizes to match guard alias."""
        response = self._make_response("Blarg the Corrupted stands before you.")
        modules = self._make_anchor_location("OTHER", ["Blarg the Corrupted"])

        follower_records = {"blarg the corrupted": "CURR"}

        decision = evaluate_location_exclusivity_decision(
            response_json=response,
            module_name="Any_Module",
            current_location_id="CURR",
            module_locations=modules,
            follower_records=follower_records,
        )
        self.assertTrue(decision.get("valid"),
                        "Hyphenated entity_id must normalize to match guard alias")


class TestSceneFollowerStateModule(unittest.TestCase):
    """Unit tests for utils.scene_follower_state CRUD helpers."""

    def setUp(self):
        self.store = {"followers": []}

    def test_load_empty_store_returns_default(self):
        store = {"followers": []}
        records = get_follower_records(store)
        self.assertEqual(records, [])

    def test_create_follower_record(self):
        rec = create_follower_record(self.store, "blarg", "CURR", 1)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["entity_id"], "blarg")
        self.assertEqual(rec["current_location"], "CURR")
        self.assertEqual(rec["since_turn"], 1)

    def test_create_follower_dedupes(self):
        create_follower_record(self.store, "blarg", "CURR", 1)
        count = len(self.store["followers"])
        rec2 = create_follower_record(self.store, "blarg", "CURR", 2)
        self.assertEqual(len(self.store["followers"]), count,
                         "Duplicate create must return existing")
        self.assertIsNotNone(rec2)

    def test_find_follower(self):
        create_follower_record(self.store, "blarg", "CURR", 1)
        result = find_follower(self.store, "blarg")
        self.assertIsNotNone(result)
        self.assertEqual(result["entity_id"], "blarg")

    def test_follower_at_location_true(self):
        create_follower_record(self.store, "blarg", "B02", 1)
        self.assertTrue(follower_at_location(self.store, "blarg", "B02"))

    def test_follower_at_location_false(self):
        create_follower_record(self.store, "blarg", "B02", 1)
        self.assertFalse(follower_at_location(self.store, "blarg", "CURR"))

    def test_move_follower(self):
        create_follower_record(self.store, "blarg", "B02", 1)
        self.assertTrue(move_follower_to_location(self.store, "blarg", "CURR"))
        self.assertTrue(follower_at_location(self.store, "blarg", "CURR"))

    def test_remove_follower(self):
        create_follower_record(self.store, "blarg", "CURR", 1)
        self.assertTrue(remove_follower_record(self.store, "blarg"))
        self.assertIsNone(find_follower(self.store, "blarg"))

    def test_remove_nonexistent_returns_false(self):
        self.assertFalse(remove_follower_record(self.store, "nonexistent"))

    def test_validate_follower_schema_valid(self):
        self.assertTrue(validate_follower_schema(self.store))

    def test_validate_follower_schema_missing_keys(self):
        self.store["followers"] = [{"bad": "data"}]
        self.assertFalse(validate_follower_schema(self.store))

    def test_validate_follower_schema_wrong_type(self):
        self.assertFalse(validate_follower_schema("not_a_dict"))


if __name__ == "__main__":
    unittest.main()
