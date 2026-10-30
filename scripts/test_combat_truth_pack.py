# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - Combat Truth Pack Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Tests for touched-combatant extraction, inventory relevance gating, and
combat-manager truth-pack hook wiring.
"""

import ast
import builtins
import copy
import contextlib
import io
import os
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest.mock import patch

from scripts.test_llm_router import ProviderTripwire


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMBAT_MANAGER_PATH = os.path.join(
    REPO_ROOT,
    "core",
    "combat",
    "combat_manager.py",
)


class OutsideWriteDenied(BaseException):
    """Fatal sentinel: ordinary Exception handlers must not swallow guard trips."""


def _load_helper_functions():
    with ProviderTripwire() as provider_tripwire, _deny_test_writes():
        with open(COMBAT_MANAGER_PATH, "r", encoding="utf-8") as file_handle:
            source = file_handle.read()

        parsed = ast.parse(source)
        target_names = {
            "_is_combat_inventory_or_ammo_change",
            "_extract_touched_character_updates_from_response_json",
        }
        selected_nodes = [
            node
            for node in parsed.body
            if isinstance(node, ast.FunctionDef) and node.name in target_names
        ]

        helper_module = ast.Module(body=selected_nodes, type_ignores=[])
        namespace = {}
        exec(compile(helper_module, filename=COMBAT_MANAGER_PATH, mode="exec"), namespace)
        for guard in provider_tripwire.guards.values():
            guard.assert_not_called()
        return namespace


class TestCombatTruthPackBehavior(unittest.TestCase):
    """Behavior tests for combat touched-character extraction helpers."""

    @classmethod
    def setUpClass(cls):
        helper_namespace = _load_helper_functions()
        cls.extract_touched = staticmethod(
            helper_namespace["_extract_touched_character_updates_from_response_json"]
        )
        cls.inventory_relevance = staticmethod(
            helper_namespace["_is_combat_inventory_or_ammo_change"]
        )

    def test_extracts_touched_character_names_from_update_character_info_actions(self):
        response_json = {
            "actions": [
                {
                    "action": "updateCharacterInfo",
                    "parameters": {
                        "characterName": "Acheron",
                        "changes": "HP 21->16 after claw hit",
                    },
                },
                {
                    "action": "updateEncounter",
                    "parameters": {"changes": "Enemy attacks summary"},
                },
                {
                    "action": "updateCharacterInfo",
                    "parameters": {
                        "characterName": "Scout Kira",
                        "changes": "Expended 1 arrow from ammunition",
                    },
                },
            ]
        }

        touched = self.extract_touched(response_json)

        self.assertIn("Acheron", touched)
        self.assertIn("Scout Kira", touched)
        self.assertEqual(len(touched["Acheron"]["changes"]), 1)
        self.assertEqual(len(touched["Scout Kira"]["changes"]), 1)

    def test_omits_truth_pack_inputs_when_no_update_character_info_actions_exist(self):
        response_json = {
            "actions": [
                {
                    "action": "updateEncounter",
                    "parameters": {"changes": "Enemy takes 8 damage"},
                },
                {"action": "exit", "parameters": {}},
            ]
        }

        touched = self.extract_touched(response_json)
        self.assertEqual(touched, {})

    def test_inventory_ammo_relevance_gating_contract(self):
        self.assertTrue(self.inventory_relevance("Expended 1 arrow from ammunition"))
        self.assertTrue(self.inventory_relevance("Removed rope from inventory"))
        self.assertFalse(self.inventory_relevance("HP 14->9 after bite damage"))
        self.assertFalse(self.inventory_relevance("Condition changed to poisoned"))

    def test_outside_write_tripwire_is_fatal_and_blocks_all_write_hooks(self):
        swallowed = False
        try:
            try:
                raise OutsideWriteDenied("fatal guard self-test")
            except Exception:
                swallowed = True
        except OutsideWriteDenied:
            pass
        self.assertFalse(swallowed)

        with _deny_test_writes():
            paths = [Path("tmp") / ("task45-write-guard-" + uuid.uuid4().hex + suffix)
                     for suffix in ("-builtins.txt", "-io.txt", "-os.txt")]
            self.assertTrue(all(not path.exists() for path in paths))
            with self.assertRaises(OutsideWriteDenied):
                builtins.open(paths[0], "w", encoding="utf-8")
            with self.assertRaises(OutsideWriteDenied):
                io.open(paths[1], "w", encoding="utf-8")
            with self.assertRaises(OutsideWriteDenied):
                os.open(paths[2], os.O_CREAT | os.O_WRONLY)
            self.assertTrue(all(not path.exists() for path in paths))

    def test_committed_state_pack_never_promotes_candidate_changes(self):
        with ProviderTripwire() as provider_tripwire, _deny_test_writes():
            with open(COMBAT_MANAGER_PATH, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            required = {
                "_is_combat_inventory_or_ammo_change",
                "_extract_touched_character_updates_from_response_json",
                "_build_compact_combat_truth_pack",
            }
            nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in required]
            namespace = {}
            exec(compile(ast.Module(body=nodes, type_ignores=[]), COMBAT_MANAGER_PATH, "exec"), namespace)
            records = {
                name.lower(): {"name": name, "hitPoints": hp, "maxHitPoints": 20,
                               "condition_affected": [], "spellSlots": {}, "deathSaves": {},
                               "ammunition": [{"name": "arrow", "quantity": 3}],
                               "equipment": [{"item_name": "longsword", "quantity": 1}],
                               "currency": {"gold": 2, "silver": 1, "copper": 0}}
                for name, hp in (("Acheron", 20), ("Blairen", 12), ("Merisiel", 20),
                                 ("Kira", 20), ("Vitreol", 20))
            }
            state_before = copy.deepcopy(records)
            fake_pc_manager = types.ModuleType("utils.pc_manager")
            fake_pc_manager.get_character_state = lambda name: records.get(name.lower())
            rosters = {
                "1PC": [{"name": "Acheron", "type": "player"}, {"name": "Blairen", "type": "npc"}],
                "4PC": [{"name": name, "type": "player"} for name in
                        ("Acheron", "Merisiel", "Kira", "Vitreol")] + [{"name": "Blairen", "type": "npc"}],
            }
            candidate = {"actions": [
                {"action": "updateCharacterInfo", "parameters": {
                    "characterName": "Acheron", "changes": "HP 20->12; ALREADY_APPLIED"}},
                {"action": "updateCharacterInfo", "parameters": {
                    "characterName": "Blairen", "changes": "HP 20->12; ALREADY_APPLIED"}},
            ]}
            for party_label, creatures in rosters.items():
                encounter = {"encounterId": party_label, "creatures": copy.deepcopy(creatures)}
                before = (copy.deepcopy(candidate), copy.deepcopy(encounter), copy.deepcopy(records))
                with patch.dict(sys.modules, {"utils.pc_manager": fake_pc_manager}):
                    packs = namespace["_build_compact_combat_truth_pack"](candidate, encounter)
                by_name = {item["characterName"]: item for item in packs}
                self.assertEqual(by_name["Acheron"]["hp"], 20)  # HP20proposed-8
                self.assertEqual(by_name["Blairen"]["hp"], 12)  # genuine Python state
                self.assertTrue(all("touchedChanges" not in item for item in packs))
                self.assertEqual((candidate, encounter, records), before)

            committed12 = copy.deepcopy(records)
            committed12["acheron"]["hitPoints"] = 12
            committed_pc_manager = types.ModuleType("utils.pc_manager")
            committed_pc_manager.get_character_state = lambda name: committed12.get(name.lower())
            actual_candidate = {"actions": [{"action": "updateCharacterInfo", "parameters": {
                "characterName": "Acheron", "changes": "HP 20->12"}}]}
            with patch.dict(sys.modules, {"utils.pc_manager": committed_pc_manager}):
                actual_pack = namespace["_build_compact_combat_truth_pack"](
                    actual_candidate, {"creatures": rosters["1PC"]})
            self.assertEqual(actual_pack[0]["hp"], 12)  # actualcommitted12

            ops_only = {"actions": [{"action": "updateCharacterInfo", "parameters": {
                "characterName": "Acheron", "ops": [{"op": "hp_delta", "delta": -8}]}}]}
            with patch.dict(sys.modules, {"utils.pc_manager": fake_pc_manager}):
                ops_pack = namespace["_build_compact_combat_truth_pack"](
                    ops_only, {"creatures": rosters["1PC"]})
            self.assertEqual(ops_pack[0]["hp"], 20)
            self.assertNotIn("touchedChanges", ops_pack[0])

            inventory = {"actions": [{"action": "updateCharacterInfo", "parameters": {
                "characterName": "Acheron", "changes": "Ammunition 3->99; ALREADY_APPLIED"}}]}
            with patch.dict(sys.modules, {"utils.pc_manager": fake_pc_manager}):
                inventory_pack = namespace["_build_compact_combat_truth_pack"](
                    inventory, {"creatures": rosters["1PC"]})
            self.assertEqual(inventory_pack[0]["inventory"]["ammunition"][0]["quantity"], 3)
            self.assertEqual(records, state_before)
            provider_tripwire.assert_untouched(self)


class _deny_test_writes:
    """Fail fatally on filesystem write paths while allowing source reads."""

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

        def deny_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise OutsideWriteDenied("outside-write tripwire: builtins.open")
            return real_open(file, mode, *args, **kwargs)

        def deny_io_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise OutsideWriteDenied("outside-write tripwire: io.open")
            return real_io_open(file, mode, *args, **kwargs)

        def deny_os_open(file, flags, *args, **kwargs):
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            if flags & write_flags:
                raise OutsideWriteDenied("outside-write tripwire: os.open")
            return real_os_open(file, flags, *args, **kwargs)

        self.stack.enter_context(patch("builtins.open", side_effect=deny_open))
        self.stack.enter_context(patch("io.open", side_effect=deny_io_open))
        self.stack.enter_context(patch("os.open", side_effect=deny_os_open))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


class TestCombatTruthPackSourceContract(unittest.TestCase):
    """Source-contract tests for combat validation truth-pack hook wiring."""

    @classmethod
    def setUpClass(cls):
        with open(COMBAT_MANAGER_PATH, "r", encoding="utf-8") as file_handle:
            cls.combat_manager_source = file_handle.read()
        validation_path = os.path.join(REPO_ROOT, "core", "combat", "validation.py")
        with open(validation_path, "r", encoding="utf-8") as file_handle:
            cls.validation_source = file_handle.read()

    def test_combat_manager_contains_truth_pack_context_hook(self):
        self.assertIn("=== COMMITTED PYTHON COMBATANT STATE", self.validation_source)
        self.assertIn("truth_pack_builder(", self.validation_source)

    def test_truth_pack_assembly_failure_is_fail_open(self):
        self.assertIn(
            "Skipping truth pack due to error",
            self.validation_source,
        )

    def test_truth_pack_supports_nested_feature_usage_and_equipment(self):
        self.assertIn("resource_item[\"usage\"]", self.combat_manager_source)
        self.assertIn("inventory_block[\"equipment\"]", self.combat_manager_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
