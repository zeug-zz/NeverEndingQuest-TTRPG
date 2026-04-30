# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - Mechanical Follow-Through Hardening Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Focused contracts for scene gift reconciliation, feature usage ops,
and pre-combat hostile scene presence wiring.
"""

import ast
import copy
import os
import sys
import unittest
from unittest.mock import patch
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

UPDATE_CHARACTER_INFO_PATH = os.path.join(REPO_ROOT, "updates", "update_character_info.py")


def _load_update_helpers():
    with open(UPDATE_CHARACTER_INFO_PATH, "r", encoding="utf-8") as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source)
    target_assign_names = {
        "SUPPORTED_CHARACTER_OPS",
        "_CURRENCY_ABBREVIATIONS",
        "OPS_ROUTING_REASON_APPLY_RECOVERABLE_WITH_CHANGES",
        "OPS_ROUTING_REASON_APPLY_RECOVERABLE_NO_FALLBACK",
        "OPS_ROUTING_REASON_APPLY_AUTHORITATIVE_HARD_FAIL",
    }
    target_func_names = {
        "_normalize_currency_type",
        "_get_currency_delta_value",
        "_to_int",
        "_canonicalize_ops_target_identity",
        "_resolve_named_entry",
        "_resolve_op_type",
        "_find_equipment_entry",
        "_find_ammunition_entry",
        "_find_class_feature_entry",
        "_classify_deterministic_ops_failure",
        "_resolve_apply_failure_route",
        "_read_feature_usage",
        "_write_feature_usage",
        "_apply_character_ops_deterministic",
    }

    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in target_assign_names:
                    selected_nodes.append(node)
                    break
        elif isinstance(node, ast.FunctionDef) and node.name in target_func_names:
            selected_nodes.append(node)

    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        "copy": copy,
        "re": __import__("re"),
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
    }
    exec(compile(helper_module, filename=UPDATE_CHARACTER_INFO_PATH, mode="exec"), namespace)
    return namespace


class TestSceneItemReconcile(unittest.TestCase):
    def test_generic_named_actor_gives_item(self):
        from utils.scene_item_reconcile import infer_scene_item_grant_actions

        parsed_response = {
            "narration": "Quartermaster Dain gives Scout Kira a healing potion.",
            "actions": [],
        }
        party_tracker = {
            "partyMembers": ["Chronos", "Blairen", "Vitreol"],
            "partyNPCs": [{"name": "Scout Kira"}],
        }
        location_data = {
            "npcs": [{"name": "Quartermaster Dain"}],
        }
        conversation_history = [{"role": "user", "content": "We accept Dain's help."}]

        inferred = infer_scene_item_grant_actions(parsed_response, party_tracker, location_data, conversation_history)
        self.assertEqual(len(inferred), 1)
        self.assertEqual(inferred[0]["parameters"]["characterName"], "Scout Kira")
        self.assertEqual(inferred[0]["parameters"]["ops"][0]["op"], "inventory_add")
        self.assertEqual(inferred[0]["parameters"]["ops"][0]["item"], "Healing Potion")

    def test_each_distribution_pattern_generates_per_recipient_grants(self):
        from utils.scene_item_reconcile import infer_scene_item_grant_actions

        parsed_response = {
            "narration": (
                "Quartermaster Dain offers gifts for the road. "
                "Chronos and Blairen take a ward stone each."
            ),
            "actions": [],
        }
        party_tracker = {
            "partyMembers": ["Chronos", "Blairen", "Vitreol"],
            "partyNPCs": [{"name": "Scout Kira"}],
        }
        location_data = {
            "npcs": [{"name": "Quartermaster Dain"}],
        }

        inferred = infer_scene_item_grant_actions(parsed_response, party_tracker, location_data, [])
        self.assertEqual(len(inferred), 2)
        targets = {item["parameters"]["characterName"] for item in inferred}
        self.assertEqual(targets, {"Chronos", "Blairen"})
        for item in inferred:
            self.assertEqual(item["parameters"]["ops"][0]["item"], "Ward Stone")
            self.assertEqual(item["parameters"]["ops"][0]["quantity"], 1)

    def test_recipient_receives_from_actor_pattern_supported(self):
        from utils.scene_item_reconcile import infer_scene_item_grant_actions

        parsed_response = {
            "narration": "Scout Kira receives the healing potion from Quartermaster Dain.",
            "actions": [],
        }
        party_tracker = {
            "partyMembers": ["Chronos", "Blairen", "Vitreol"],
            "partyNPCs": [{"name": "Scout Kira"}],
        }
        location_data = {
            "npcs": [{"name": "Quartermaster Dain"}],
        }

        inferred = infer_scene_item_grant_actions(parsed_response, party_tracker, location_data, [])
        self.assertEqual(len(inferred), 1)
        self.assertEqual(inferred[0]["parameters"]["characterName"], "Scout Kira")
        self.assertEqual(inferred[0]["parameters"]["ops"][0]["item"], "Healing Potion")

    def test_vague_reward_language_is_noop(self):
        from utils.scene_item_reconcile import infer_scene_item_grant_actions

        parsed_response = {
            "narration": "The party receives some supplies before departing.",
            "actions": [],
        }
        party_tracker = {
            "partyMembers": ["Chronos", "Blairen", "Vitreol"],
            "partyNPCs": [{"name": "Scout Kira"}],
        }

        inferred = infer_scene_item_grant_actions(parsed_response, party_tracker, {}, [])
        self.assertEqual(inferred, [])

    def test_scene_reconcile_has_no_maelo_hardwire(self):
        reconcile_path = os.path.join(REPO_ROOT, "utils", "scene_item_reconcile.py")
        with open(reconcile_path, "r", encoding="utf-8") as file_handle:
            source = file_handle.read().lower()

        self.assertNotIn("_has_maelo_context", source)
        self.assertNotIn("hermit maelo", source)


class TestFeatureUsageOps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        namespace = _load_update_helpers()
        cls.apply_ops = staticmethod(namespace["_apply_character_ops_deterministic"])
        cls.classify_failure = staticmethod(namespace["_classify_deterministic_ops_failure"])
        cls.resolve_failure_route = staticmethod(namespace["_resolve_apply_failure_route"])
        cls.canonicalize_identity = staticmethod(namespace["_canonicalize_ops_target_identity"])

    def test_feature_usage_delta_updates_nested_usage(self):
        character_data = {
            "classFeatures": [
                {"name": "Rage", "usage": {"current": 2, "max": 2, "refreshOn": "longRest"}}
            ]
        }
        ops = [{"op": "feature_usage_delta", "feature": "Rage", "delta": -1}]

        success, updated, error_message, unsupported = self.apply_ops(character_data, ops)
        self.assertTrue(success)
        self.assertEqual(error_message, "")
        self.assertEqual(unsupported, [])
        self.assertEqual(updated["classFeatures"][0]["usage"]["current"], 1)

    def test_feature_usage_set_updates_legacy_flat_usage(self):
        character_data = {
            "classFeatures": [
                {"name": "Second Wind", "currentUses": 1, "maxUses": 1, "uses": 1}
            ]
        }
        ops = [{"op": "feature_usage_set", "feature": "Second Wind", "current": 0, "max": 1}]

        success, updated, error_message, unsupported = self.apply_ops(character_data, ops)
        self.assertTrue(success)
        self.assertEqual(error_message, "")
        self.assertEqual(unsupported, [])
        self.assertEqual(updated["classFeatures"][0]["currentUses"], 0)
        self.assertEqual(updated["classFeatures"][0]["uses"], 0)
        self.assertEqual(updated["classFeatures"][0]["maxUses"], 1)

    def test_feature_usage_delta_matches_compacted_feature_alias(self):
        character_data = {
            "classFeatures": [
                {"name": "Divine Sense", "usage": {"current": 5, "max": 5, "refreshOn": "longRest"}}
            ]
        }
        ops = [{"op": "feature_usage_delta", "feature": "DivineSense", "delta": -1}]

        success, updated, error_message, unsupported = self.apply_ops(character_data, ops)
        self.assertTrue(success)
        self.assertEqual(error_message, "")
        self.assertEqual(unsupported, [])
        self.assertEqual(updated["classFeatures"][0]["usage"]["current"], 4)

    def test_feature_usage_delta_matches_legacy_compacted_lay_on_hands_alias(self):
        character_data = {
            "classFeatures": [
                {"name": "Lay on Hands", "usage": {"current": 5, "max": 5, "refreshOn": "longRest"}}
            ]
        }
        ops = [{"op": "feature_usage_delta", "feature": "LayonHands", "delta": -1}]

        success, updated, error_message, unsupported = self.apply_ops(character_data, ops)
        self.assertTrue(success)
        self.assertEqual(error_message, "")
        self.assertEqual(unsupported, [])
        self.assertEqual(updated["classFeatures"][0]["usage"]["current"], 4)

    def test_canonical_target_identity_strips_spacing_and_punctuation(self):
        self.assertEqual(self.canonicalize_identity("Divine Sense"), "divinesense")
        self.assertEqual(self.canonicalize_identity("Divine-Sense"), "divinesense")
        self.assertEqual(self.canonicalize_identity("Lay on Hands"), "layonhands")

    def test_recoverable_failure_route_degrades_when_changes_present(self):
        route = self.resolve_failure_route(
            "Expended 1 use of Divine Sense.",
            "unknown class feature: DivineSense",
        )
        self.assertEqual(route["mode"], "prose_fallback")
        self.assertEqual(route["reason"], "ops_apply_recoverable_with_changes_fallback")

    def test_authoritative_failure_route_stays_hard_fail_even_with_changes(self):
        route = self.resolve_failure_route(
            "Removed 2 arrows from inventory.",
            "cannot remove 2 Arrow; only 1 available",
        )
        self.assertEqual(route["mode"], "hard_fail")
        self.assertEqual(route["reason"], "ops_apply_authoritative_hard_fail")

    def test_authoritative_failure_classification_mentions_specific_user_message(self):
        classification = self.classify_failure("currency underflow for gold: 0+-5")
        self.assertEqual(classification["mode"], "hard_fail")
        self.assertIn("Could not safely apply character update", classification["user_message"])


class TestVisibleHostileExtraction(unittest.TestCase):
    def test_generic_location_monsters_do_not_become_visible_hostiles(self):
        from web.extensions.tabletop_socket_handlers import _extract_visible_location_hostiles

        location_data = {
            "name": "Cellar Hallway",
            "monsters": [
                {"name": "Cultist"},
                {"name": "Skeleton"},
            ],
        }

        self.assertEqual(_extract_visible_location_hostiles(location_data), [])

    def test_explicit_visible_hostiles_are_emitted(self):
        from web.extensions.tabletop_socket_handlers import _extract_visible_location_hostiles

        location_data = {
            "name": "Ritual Landing",
            "visibleHostiles": [
                {"name": "Cultist Lookout", "monsterType": "Cultist"},
                "Skeleton",
            ],
        }

        self.assertEqual(
            _extract_visible_location_hostiles(location_data),
            [
                {"name": "Cultist Lookout", "monsterType": "Cultist"},
                {"name": "Skeleton", "monsterType": "Skeleton"},
            ],
        )

    def test_source_identity_keys_support_strip_dedupe(self):
        from web.extensions.tabletop_socket_handlers import _collect_strip_identity_keys, _keys_overlap

        recruited_party_npc = {
            "name": "Thorn-Touched Dryad Sylara",
            "source_npc_name": "Thorn-Touched Dryad Sylara",
            "source_entity_slug": "thorn_touched_dryad_sylara",
            "character_file_ref": "thorn_touched_dryad_sylara",
        }
        current_location_npc = {
            "name": "Dryad Sylara",
            "source_npc_name": "Thorn-Touched Dryad Sylara",
            "source_entity_slug": "thorn_touched_dryad_sylara",
        }

        self.assertTrue(
            _keys_overlap(
                _collect_strip_identity_keys(recruited_party_npc),
                _collect_strip_identity_keys(current_location_npc),
            ),
            "Source metadata should dedupe recruited party NPCs against current-location NPCs",
        )

    def test_party_data_payload_suppresses_location_npc_matching_recruited_source_identity(self):
        from web.extensions.tabletop_socket_handlers import handle_party_data_request_impl

        party_tracker = {
            "module": "The_Thornwood_Watch",
            "partyMembers": ["Acheron"],
            "partyNPCs": [
                {
                    "name": "Thorn-Touched Dryad Sylara",
                    "source_npc_name": "Thorn-Touched Dryad Sylara",
                    "source_entity_slug": "thorn_touched_dryad_sylara",
                    "character_file_ref": "thorn_touched_dryad_sylara",
                }
            ],
            "worldConditions": {
                "currentAreaId": "RO001",
                "currentLocationId": "RO01",
            },
        }
        area_data = {
            "locations": [
                {
                    "locationId": "RO01",
                    "npcs": [
                        {"name": "Thorn-Touched Dryad Sylara"},
                    ],
                }
            ]
        }

        emitted = {}

        def fake_safe_read_json(path):
            if path == "party_tracker.json":
                return party_tracker
            if path.endswith("modules/The_Thornwood_Watch/areas/RO001.json"):
                return area_data
            if path.endswith("thorn_touched_dryad_sylara.json"):
                return {"name": "Thorn-Touched Dryad Sylara", "class": "NPC", "level": 3}
            return None

        def emit(event_name, payload):
            emitted[event_name] = payload

        with (
            patch("utils.file_operations.safe_read_json", side_effect=fake_safe_read_json),
            patch("utils.module_path_manager.ModulePathManager", lambda module_name: type("PM", (), {"get_character_path": lambda self_inner, name: os.path.join("/tmp", str(name).strip().lower().replace(' ', '_').replace('-', '_').replace("'", '_') + '.json')})()),
            patch("web.extensions.tabletop_socket_handlers.os.path.exists", return_value=True),
        ):
            handle_party_data_request_impl(emit, lambda *args, **kwargs: None)

        payload = emitted.get("party_data_response", {})
        self.assertEqual(payload.get("location_npcs"), [], "Recruited source identity should suppress duplicate location NPC emission")


class TestPreCombatHostilePresenceSourceContracts(unittest.TestCase):
    def test_party_data_payload_includes_location_hostiles(self):
        socket_handler_path = os.path.join(
            REPO_ROOT,
            "web",
            "extensions",
            "tabletop_socket_handlers.py",
        )
        with open(socket_handler_path, "r", encoding="utf-8") as file_handle:
            source = file_handle.read()

        self.assertIn("location_hostiles", source)
        self.assertIn("'type': 'location_hostile'", source)
        self.assertIn("'monsterType': monster_asset_key", source)

    def test_party_strip_renders_location_hostiles(self):
        template_path = os.path.join(
            REPO_ROOT,
            "web",
            "templates",
            "game_interface.html",
        )
        with open(template_path, "r", encoding="utf-8") as file_handle:
            source = file_handle.read()

        self.assertIn("response.location_hostiles", source)
        self.assertIn("Hostile Presence", source)
        self.assertIn("const hostileBasePath = `/media/monsters/${slugFromMeta}`;", source)
        self.assertIn("isLocationHostile ? hostileBasePath : npcBasePath", source)


class TestDMNoteMechanicalVisibilitySourceContracts(unittest.TestCase):
    def test_dm_note_uses_equipment_and_ammunition_visibility(self):
        dm_note_path = os.path.join(
            REPO_ROOT,
            "utils",
            "multi_pc_dm_note.py",
        )
        with open(dm_note_path, "r", encoding="utf-8") as file_handle:
            source = file_handle.read()

        self.assertIn("pc_data.get('equipment'", source)
        self.assertIn("pc_data.get('ammunition'", source)
        self.assertIn("_summarize_limited_resources", source)


class TestSceneFollowerStripEmission(unittest.TestCase):
    """Verify scene follower records emit correctly into party_data_response."""

    def setUp(self):
        self.base_dir = os.devnull

    def test_visible_monster_follower_emits_in_location_hostiles(self):
        from web.extensions.tabletop_socket_handlers import handle_party_data_request_impl

        party_tracker = {
            "module": "Test_Module",
            "partyMembers": ["Acheron"],
            "partyNPCs": [],
            "worldConditions": {
                "currentAreaId": "TC001",
                "currentLocationId": "T01",
            },
        }
        area_data = {"locations": [{"locationId": "T01"}]}
        follower_store = {
            "followers": [
                {
                    "entity_id": "corrupted_ranger",
                    "current_location": "T01",
                    "since_turn": 3,
                    "display_name": "Corrupted Ranger",
                    "entity_type": "monster",
                    "monster_type": "Corrupted Ranger",
                    "visible_in_strip": True,
                    "lifecycle_state": "present",
                    "disposition": "hostile",
                }
            ]
        }

        emitted = {}

        def fake_safe_read_json(path):
            if path == "party_tracker.json":
                return party_tracker
            if path.endswith("modules/Test_Module/areas/TC001.json"):
                return area_data
            if path == "data/runtime/scene_followers.json":
                return follower_store
            return None

        def fake_exists(path):
            if "Test_Module" in str(path):
                return True
            return False

        def emit(event_name, payload):
            emitted[event_name] = payload

        with (
            patch("utils.file_operations.safe_read_json", side_effect=fake_safe_read_json),
            patch("web.extensions.tabletop_socket_handlers.os.path.exists", side_effect=fake_exists),
            patch("utils.scene_follower_state.load_followers", return_value=follower_store),
        ):
            handle_party_data_request_impl(emit, lambda *args, **kwargs: None)

        payload = emitted.get("party_data_response", {})
        self.assertIn("location_hostiles", payload)
        hostiles = payload["location_hostiles"]
        self.assertEqual(len(hostiles), 1, "Visible monster follower should emit one hostile")
        self.assertEqual(hostiles[0]["type"], "location_hostile")
        self.assertEqual(hostiles[0]["name"], "Corrupted Ranger")

    def test_off_location_follower_does_not_emit(self):
        from web.extensions.tabletop_socket_handlers import handle_party_data_request_impl

        party_tracker = {
            "module": "Test_Module",
            "partyMembers": ["Acheron"],
            "partyNPCs": [],
            "worldConditions": {
                "currentAreaId": "TC001",
                "currentLocationId": "T01",
            },
        }
        area_data = {"locations": [{"locationId": "T01"}]}
        follower_store = {
            "followers": [
                {
                    "entity_id": "off_location_npc",
                    "current_location": "T99",
                    "since_turn": 3,
                    "display_name": "Off-Location NPC",
                    "entity_type": "monster",
                    "monster_type": "Off-Location NPC",
                    "visible_in_strip": True,
                    "lifecycle_state": "present",
                    "disposition": "hostile",
                }
            ]
        }

        emitted = {}

        def fake_safe_read_json(path):
            if path == "party_tracker.json":
                return party_tracker
            if path.endswith("modules/Test_Module/areas/TC001.json"):
                return area_data
            if path == "data/runtime/scene_followers.json":
                return follower_store
            return None

        def emit(event_name, payload):
            emitted[event_name] = payload

        with (
            patch("utils.file_operations.safe_read_json", side_effect=fake_safe_read_json),
            patch("web.extensions.tabletop_socket_handlers.os.path.exists", return_value=False),
            patch("utils.scene_follower_state.load_followers", return_value=follower_store),
        ):
            handle_party_data_request_impl(emit, lambda *args, **kwargs: None)

        payload = emitted.get("party_data_response", {})
        self.assertEqual(payload.get("location_hostiles", []), [])

    def test_cleanup_state_follower_does_not_emit(self):
        from web.extensions.tabletop_socket_handlers import handle_party_data_request_impl

        party_tracker = {
            "module": "Test_Module",
            "partyMembers": ["Acheron"],
            "partyNPCs": [],
            "worldConditions": {
                "currentAreaId": "TC001",
                "currentLocationId": "T01",
            },
        }
        area_data = {"locations": [{"locationId": "T01"}]}
        follower_store = {
            "followers": [
                {
                    "entity_id": "escaped_prisoner",
                    "current_location": "T01",
                    "since_turn": 3,
                    "display_name": "Escaped Prisoner",
                    "entity_type": "monster",
                    "monster_type": "Escaped Prisoner",
                    "visible_in_strip": True,
                    "lifecycle_state": "escaped",
                    "disposition": "escaped",
                }
            ]
        }

        emitted = {}

        def fake_safe_read_json(path):
            if path == "party_tracker.json":
                return party_tracker
            if path.endswith("modules/Test_Module/areas/TC001.json"):
                return area_data
            if path == "data/runtime/scene_followers.json":
                return follower_store
            return None

        def emit(event_name, payload):
            emitted[event_name] = payload

        with (
            patch("utils.file_operations.safe_read_json", side_effect=fake_safe_read_json),
            patch("web.extensions.tabletop_socket_handlers.os.path.exists", return_value=False),
            patch("utils.scene_follower_state.load_followers", return_value=follower_store),
        ):
            handle_party_data_request_impl(emit, lambda *args, **kwargs: None)

        payload = emitted.get("party_data_response", {})
        self.assertEqual(payload.get("location_hostiles", []), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
