# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Prompt Context Stage Contract Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free runtime fixture coverage for extracted context and prompt assembly.
"""

import ast
import hashlib
import builtins
import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from scripts.test_llm_router import ProviderTripwire

from core.combat.prompts import (
    CombatContextDependencies,
    CombatContextInputs,
    InventoryContextInputs,
    assemble_combat_context,
    enhance_combat_input_with_inventory,
)


STATIC_PROMPT_HASHES = {
    "prompts/combat/combat_sim_prompt.txt": "148d4211474c9189ec54b43ee5fa39eb505a3d1a8d284d7d42581e25ccc7e54b",
    "prompts/combat/combat_sim_prompt_compressed.txt": "25d87b3116cd0425d59425dd63735aaff587d8c1248f8464037392f0c9c846cb",
    "prompts/combat/combat_sim_prompt_multipc.txt": "7f6c4aaa9567208bf0d766e3bf1b5770d3cd8519a31d727ddfe022aafb715957",
    "prompts/combat/combat_sim_prompt_multipc_compressed.txt": "b31ad6960e340d8b05eb76849f983533044f503eb88cf82714beb6526412647e",
    "prompts/combat/combat_sim_prompt_uncompressed.txt": "3bb128e94901f3810b97191b6db16dee9662976e951620f8fd80f57cc6fed612",
    "prompts/combat/combat_validation_prompt.txt": "ca12e479668a623b124efa7aa1777554e2ef25b169bf34240e6fc797f7eb486a",
    "prompts/combat/combat_validation_prompt_compressed.txt": "18ac9069aea90e5d5225e4f2c40420c051d19ee378387e8a32f2ebe99e9c2dda",
    "prompts/combat/combat_validation_prompt_multipc.txt": "2db539f355904ee88a76bc70e0de611a3a0de0c3c69fd1926de8ae2a0bbdf0eb",
    "prompts/combat/combat_validation_prompt_multipc_compressed.txt": "7f905bd2902bc74780eb4f24705d80645d4c5d229f57fe6dda8d9c4f13f84812",
}

REVIEWED_CASES = (
    {
        "name": "one-pc-pc-phase",
        "party_size": 1,
        "active": "Acheron",
        "phase": "PC_PHASE",
        "history": "Synthetic ledger: no prior action; resume marker absent.",
        "unconscious": False,
        "prompt_sha256": "74ddf6085ae97c6cdf4db1f6e9c44efbf1215b9f686c8e69f5f5186df55c1abc",
        "prompt_bytes": 1842,
        "dynamic_state_sha256": "aaf0c92a915390caae10808a3548bb128fa2f600483962eacd236b3e202722a0",
        "dynamic_state_bytes": 571,
    },
    {
        "name": "four-pc-active-rotation",
        "party_size": 4,
        "active": "Lidda",
        "phase": "PC_PHASE",
        "history": "Synthetic ledger: no prior action; resume marker absent.",
        "unconscious": True,
        "prompt_sha256": "d8a918288a02bc0bf0ad438ed6956774cbe54f33bcde658ae6ca46fc98813a6b",
        "prompt_bytes": 1925,
        "dynamic_state_sha256": "63a10e4a90ad4373b279e011c8b4d36aa7b29924ba7b0567bc7272241ab8f412",
        "dynamic_state_bytes": 625,
    },
    {
        "name": "four-pc-enemy-phase-resume-ledger",
        "party_size": 4,
        "active": "Vitreol",
        "phase": "ENEMY_PHASE",
        "history": "Synthetic ledger: Acheron action applied. Resume marker: session resumed after completed turn.",
        "unconscious": False,
        "prompt_sha256": "6b8e0ca216870084f87f23d284142b460bdb5529c871d2f34d9287874538bba4",
        "prompt_bytes": 1976,
        "dynamic_state_sha256": "2a221f491951f7138a071a3bfe242b51df0568e1d09baa6d45a589abc829b119",
        "dynamic_state_bytes": 627,
    },
)

REVIEWED_DYNAMIC_STATE_BYTES = {
    "one-pc-pc-phase": (
        "Active Player Characters (User Controlled):\n"
        "  Acheron: HP 17/21, alive, Spell Slots: L1:1/2\n"
        "Accompanied by Party NPCs (DM Controlled):\n"
        "  Scout Kira: HP 8/12, alive\n"
        "Enemies (DM Controlled):\n"
        "  Goblin Raider: HP 7/7, alive\n"
        "  Fallen Skeleton: HP 0/13, dead\n\n"
        "++ VALID TARGETS & ACTORS (IMMUTABLE) ++\n"
        "- Acheron (player)\n- Scout Kira (npc)\n- Goblin Raider (enemy)\n- Fallen Skeleton (enemy)\n"
        "RULES: This is the definitive list of all beings in the scene. "
        "Do NOT narrate actions for anyone not on this list. "
        "During ENEMY_PHASE, PCs remain forbidden as actors but are valid targets."
    ),
    "four-pc-active-rotation": (
        "Active Player Characters (User Controlled):\n"
        "  Lidda: HP 17/21, alive, Spell Slots: L1:1/2\n"
        "Accompanied by Party NPCs (DM Controlled):\n"
        "  Scout Kira: HP 8/12, alive\n"
        "Enemies (DM Controlled):\n"
        "  Goblin Raider: HP 7/7, alive\n"
        "  Fallen Skeleton: HP 0/13, dead\n\n"
        "++ VALID TARGETS & ACTORS (IMMUTABLE) ++\n"
        "- Acheron (player)\n- Merisiel (player)\n- Lidda (player)\n- Vitreol (player)\n"
        "- Scout Kira (npc)\n- Goblin Raider (enemy)\n- Fallen Skeleton (enemy)\n"
        "RULES: This is the definitive list of all beings in the scene. "
        "Do NOT narrate actions for anyone not on this list. "
        "During ENEMY_PHASE, PCs remain forbidden as actors but are valid targets."
    ),
    "four-pc-enemy-phase-resume-ledger": (
        "Active Player Characters (User Controlled):\n"
        "  Vitreol: HP 17/21, alive, Spell Slots: L1:1/2\n"
        "Accompanied by Party NPCs (DM Controlled):\n"
        "  Scout Kira: HP 8/12, alive\n"
        "Enemies (DM Controlled):\n"
        "  Goblin Raider: HP 7/7, alive\n"
        "  Fallen Skeleton: HP 0/13, dead\n\n"
        "++ VALID TARGETS & ACTORS (IMMUTABLE) ++\n"
        "- Acheron (player)\n- Merisiel (player)\n- Lidda (player)\n- Vitreol (player)\n"
        "- Scout Kira (npc)\n- Goblin Raider (enemy)\n- Fallen Skeleton (enemy)\n"
        "RULES: This is the definitive list of all beings in the scene. "
        "Do NOT narrate actions for anyone not on this list. "
        "During ENEMY_PHASE, PCs remain forbidden as actors but are valid targets."
    ),
}


class FixtureManager:
    """Synthetic multi-PC collaborator mirroring the reviewed AST fixture."""

    def __init__(self, party, active, phase, calls, history_text):
        self.party = party
        self.current_pc_name = active
        self.combat_phase = phase
        self.calls = calls
        self.pc_phase_complete = phase != "PC_PHASE"
        self.history_text = history_text

    def format_initiative_tracker(self, encounter):
        self.calls.append("format_initiative_tracker")
        return (
            f"[>] {self.current_pc_name}\n```json\n"
            f"{{\"player_name\":\"{self.current_pc_name}\","
            f"\"process_until\":\"{self.combat_phase}\","
            f"\"turn_window\":[\"{self.current_pc_name}\"]}}\n```"
        )

    def get_current_actor(self):
        self.calls.append("get_current_actor")
        return type("FixtureActor", (), {"name": self.current_pc_name})()

    def get_required_response_prompt(self):
        self.calls.append("get_required_response_prompt")
        return "--- REQUIRED RESPONSE ---\nContinue the current phase.\n" + self.history_text

    def get_remaining_enemies_for_round(self):
        self.calls.append("get_remaining_enemies_for_round")
        return ["Goblin Raider"]

    def format_party_turn_summary(self):
        self.calls.append("format_party_turn_summary")
        return "fixture-party-turn-summary"

    def format_pc_context_for_prompt(self, name):
        self.calls.append(f"format_pc_context_for_prompt:{name}")
        return f"fixture-pc-context:{name}"


def make_reviewed_fixture(case):
    party = ["Acheron"] if case["party_size"] == 1 else ["Acheron", "Merisiel", "Lidda", "Vitreol"]
    active = case["active"]
    calls = []
    writes = []
    manager = FixtureManager(party, active, case["phase"], calls, case["history"])
    creatures = [
        {
            "name": name,
            "type": "player",
            "currentHitPoints": 17,
            "maxHitPoints": 21,
            "armorClass": 16,
            "status": "alive",
            "condition": "none",
        }
        for name in party
    ]
    if case["unconscious"]:
        creatures[-1].update(currentHitPoints=0, status="unconscious", condition="Unconscious")
    creatures.extend(
        [
            {"name": "Scout Kira", "type": "npc", "currentHitPoints": 8, "maxHitPoints": 12, "armorClass": 13, "status": "alive", "condition": "none"},
            {"name": "Goblin Raider", "type": "enemy", "monsterType": "goblin", "currentHitPoints": 7, "maxHitPoints": 7, "armorClass": 15, "status": "alive", "condition": "none"},
            {"name": "Fallen Skeleton", "type": "enemy", "monsterType": "skeleton", "currentHitPoints": 0, "maxHitPoints": 13, "armorClass": 13, "status": "dead", "condition": "none"},
        ]
    )
    encounter = {
        "encounterId": "SYNTHETIC_FIXTURE",
        "combat_round": 3,
        "initiativeMode": "two_group_phase1",
        "initiativeRolls": {"pcGroup": 15, "dmGroup": 12},
        "initiativeWinner": "pcGroup",
        "roundStartsWith": "pcGroup",
        "preroll_cache": {"round": 3, "rolls": "SYNTHETIC PREROLLS", "preroll_id": "fixture-3"},
        "creatures": creatures,
    }
    character_data = {
        "hitPoints": 17,
        "maxHitPoints": 21,
        "status": "alive",
        "condition": "none",
        "condition_affected": [],
        "spellcasting": {"spellSlots": {"level1": {"current": 1, "max": 2}}},
    }
    player_info = {"name": party[-1], **character_data}
    if case["unconscious"]:
        player_info.update(hitPoints=0, status="unconscious", condition_affected=["Unconscious"])
    player_files = {
        f"fixture-character:{name}": {
            **character_data,
            "hitPoints": 0 if case["unconscious"] and name == party[-1] else 17,
            "status": "unconscious" if case["unconscious"] and name == party[-1] else "alive",
            "condition_affected": ["Unconscious"] if case["unconscious"] and name == party[-1] else [],
        }
        for name in party
    }

    def safe_load(path):
        calls.append(f"safe_json_load:{path}")
        return player_files.get(path)

    def load_npc(name, path_manager):
        calls.append(f"load_npc_with_fuzzy_match:{name}")
        return ({"name": name, "maxHitPoints": 12}, "fixture-npc") if name == "Scout Kira" else (None, None)

    def collect_roster(encounter_data, **kwargs):
        calls.append("_collect_authoritative_combat_roster:fixture")
        return [{"name": creature["name"], "type": creature["type"]} for creature in encounter_data["creatures"]]

    class FakePaths:
        def get_character_path(self, name):
            return f"fixture-character:{name}"

        def get_monster_path(self, name):
            return f"fixture-monster:{name}"

    deps = CombatContextDependencies(
        normalize_character_name=lambda name: name,
        safe_json_load=safe_load,
        load_npc_with_fuzzy_match=load_npc,
        collect_authoritative_combat_roster=collect_roster,
        generate_prerolls=lambda encounter_data, round_num: "SYNTHETIC PREROLLS",
        save_json_file=lambda path, data: writes.append((path, data)),
        module_path_manager_factory=lambda *args, **kwargs: FakePaths(),
        file_exists=lambda path: False,
        logger_debug=lambda *args, **kwargs: None,
        logger_error=lambda *args, **kwargs: None,
        emit=lambda value: None,
        random_int=lambda low, high: 1234,
        fallback_initiative_tracker=lambda *args: self.fail("unexpected lazy initiative fallback"),
    )
    inputs = CombatContextInputs(
        encounter_data=encounter,
        multi_pc_manager=manager,
        party_tracker_data={
            "partyMembers": party,
            "active_character": active,
            "partyNPCs": [],
            "module": "Fixture",
            "worldConditions": {
                "combatInitiative": {"partyRoll": 15, "enemyRoll": 12, "partyGoesFirst": True}
            },
        },
        player_info=player_info,
        player_name_display=active,
        current_hp=17,
        max_hp=21,
        pre_context_player_data=character_data,
        path_manager=FakePaths(),
        json_file_path="fixture-encounter-path",
        conversation_history=[{"role": "user", "content": "synthetic prior context"}],
        user_input_text=f"[{active}]: Hold position",
    )
    return inputs, deps, calls, writes


class CombatPromptStageTests(unittest.TestCase):
    def setUp(self):
        # Fail closed if a tested stage attempts real networking or file writes.
        original_open = builtins.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                raise AssertionError("real filesystem writes forbidden in prompt-stage test")
            return original_open(file, mode, *args, **kwargs)

        self.provider_tripwire = ProviderTripwire()
        self.provider_tripwire.__enter__()
        self.addCleanup(lambda: self.provider_tripwire.__exit__(None, None, None))
        self.write_guard = patch("builtins.open", side_effect=guarded_open)
        self.write_guard.start()
        self.addCleanup(self.write_guard.stop)
        self.filesystem_guards = []
        for operation in ("open", "write", "truncate", "ftruncate", "remove", "unlink", "rename", "replace", "mkdir", "makedirs", "rmdir"):
            if hasattr(os, operation):
                guard = patch.object(
                    os,
                    operation,
                    side_effect=AssertionError(f"real os.{operation} forbidden in prompt-stage test"),
                )
                guard.start()
                self.filesystem_guards.append(guard)
                self.addCleanup(guard.stop)

    def tearDown(self):
        self.provider_tripwire.assert_untouched(self)

    def test_reviewed_fixture_cases_match_fixed_user_prompt_and_state_bytes(self):
        expected_calls = (
            "safe_json_load:fixture-character:Acheron",
            "load_npc_with_fuzzy_match:Scout Kira",
            "_collect_authoritative_combat_roster:fixture",
            "format_initiative_tracker",
            "get_current_actor",
            "get_required_response_prompt",
            "get_remaining_enemies_for_round",
            "format_party_turn_summary",
        )
        for case in REVIEWED_CASES:
            inputs, deps, calls, writes = make_reviewed_fixture(case)
            if case["party_size"] == 4:
                expected_calls = (
                    f"safe_json_load:fixture-character:{case['active']}",
                    "load_npc_with_fuzzy_match:Scout Kira",
                    "_collect_authoritative_combat_roster:fixture",
                    "format_initiative_tracker",
                    "get_current_actor",
                    "get_required_response_prompt",
                    "get_remaining_enemies_for_round",
                    "format_party_turn_summary",
                    f"format_pc_context_for_prompt:{case['active']}",
                )
            else:
                expected_calls = (
                    "safe_json_load:fixture-character:Acheron",
                    "load_npc_with_fuzzy_match:Scout Kira",
                    "_collect_authoritative_combat_roster:fixture",
                    "format_initiative_tracker",
                    "get_current_actor",
                    "get_required_response_prompt",
                    "get_remaining_enemies_for_round",
                    "format_party_turn_summary",
                    "format_pc_context_for_prompt:Acheron",
                )
            with self.subTest(case=case["name"]):
                result = assemble_combat_context(inputs, deps)
                prompt_bytes = result.user_prompt.encode("utf-8")
                state_bytes = result.dynamic_state.encode("utf-8")
                self.assertFalse(result.return_early)
                self.assertEqual(hashlib.sha256(prompt_bytes).hexdigest(), case["prompt_sha256"])
                self.assertEqual(len(prompt_bytes), case["prompt_bytes"])
                self.assertEqual(hashlib.sha256(state_bytes).hexdigest(), case["dynamic_state_sha256"])
                self.assertEqual(len(state_bytes), case["dynamic_state_bytes"])
                self.assertEqual(result.dynamic_state, REVIEWED_DYNAMIC_STATE_BYTES[case["name"]])
                self.assertEqual(calls, list(expected_calls))
                self.assertEqual(writes, [])
                self.assertEqual(result.encounter_data["preroll_cache"]["rolls"], "SYNTHETIC PREROLLS")

    def test_static_combat_prompt_assets_retain_all_nine_frozen_hashes(self):
        for path, expected_hash in STATIC_PROMPT_HASHES.items():
            with self.subTest(path=path):
                with open(path, "rb") as prompt_file:
                    actual_hash = hashlib.sha256(prompt_file.read()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

    def test_prompt_module_is_standalone_and_has_no_runtime_code_generation(self):
        tree = ast.parse(Path("core/combat/prompts.py").read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertFalse(
            any(
                module.startswith(("openai", "requests", "httpx"))
                or module == "utils.ai_client_factory"
                for module in imported
            ),
            msg=f"Provider/client import found in pure prompt module: {sorted(imported)}",
        )
        forbidden_calls = {"exec", "eval", "compile", "__import__"}
        self.assertFalse(
            [
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in forbidden_calls
            ]
        )

    def test_new_round_preserves_one_preroll_cache_write(self):
        case = REVIEWED_CASES[0]
        inputs, deps, calls, writes = make_reviewed_fixture(case)
        inputs.encounter_data["combat_round"] = 4
        generated = []
        deps = CombatContextDependencies(
            **{
                **deps.__dict__,
                "generate_prerolls": lambda encounter, round_num: generated.append(round_num) or "NEW ROLL POOL",
            }
        )
        result = assemble_combat_context(inputs, deps)
        self.assertEqual(generated, [4])
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], "fixture-encounter-path")
        self.assertEqual(writes[0][1]["preroll_cache"], {"round": 4, "rolls": "NEW ROLL POOL", "preroll_id": "4-1234"})
        self.assertIn("NEW ROLL POOL", result.user_prompt)

        case_inputs, case_deps, _, missing_cache_writes = make_reviewed_fixture(case)
        case_inputs.encounter_data["preroll_cache"] = {"round": 3}
        fallback_rolls = []
        case_deps = replace(
            case_deps,
            generate_prerolls=lambda encounter, round_num: fallback_rolls.append(round_num) or "CACHE REPAIR ROLLS",
        )
        cache_result = assemble_combat_context(case_inputs, case_deps)
        self.assertEqual(fallback_rolls, [3])
        self.assertEqual(len(missing_cache_writes), 1)
        self.assertEqual(
            missing_cache_writes[0][1]["preroll_cache"],
            {"round": 3, "rolls": "CACHE REPAIR ROLLS", "preroll_id": "3-1234"},
        )
        self.assertIn("CACHE REPAIR ROLLS", cache_result.user_prompt)

    def test_failed_tracker_returns_legacy_early_result_and_lazy_fallback_receives_history_tail(self):
        case = REVIEWED_CASES[0]
        inputs, deps, calls, writes = make_reviewed_fixture(case)
        inputs.multi_pc_manager.format_initiative_tracker = lambda encounter: None
        inputs = replace(
            inputs,
            conversation_history=[{"role": "user", "content": str(index)} for index in range(8)],
        )
        fallback_calls = []
        deps = CombatContextDependencies(
            **{
                **deps.__dict__,
                "fallback_initiative_tracker": lambda encounter, history, round_num: fallback_calls.append((history, round_num)) or None,
            }
        )
        result = assemble_combat_context(inputs, deps)
        self.assertTrue(result.return_early)
        self.assertEqual(result.return_value, (None, None))
        self.assertEqual((result.current_hp, result.max_hp), (17, 21))
        self.assertEqual(fallback_calls, [(inputs.conversation_history[-6:], 3)])
        self.assertEqual(writes, [])

    def test_fresh_character_read_failure_keeps_pre_context_hp_and_spell_slots(self):
        inputs, deps, calls, writes = make_reviewed_fixture(REVIEWED_CASES[0])
        inputs = replace(inputs, current_hp=9, max_hp=21)
        deps = CombatContextDependencies(**{**deps.__dict__, "safe_json_load": lambda path: None})
        result = assemble_combat_context(inputs, deps)
        self.assertIn("Acheron: HP 9/21", result.dynamic_state)
        self.assertIn("Spell Slots: L1:1/2", result.dynamic_state)
        self.assertEqual(writes, [])

        raising_inputs, raising_deps, _, raising_writes = make_reviewed_fixture(REVIEWED_CASES[0])
        raising_inputs = replace(raising_inputs, current_hp=9, max_hp=21)
        raising_deps = replace(
            raising_deps,
            safe_json_load=lambda path: (_ for _ in ()).throw(OSError("synthetic file read failure")),
        )
        raised_result = assemble_combat_context(raising_inputs, raising_deps)
        self.assertIn("Acheron: HP 9/21", raised_result.dynamic_state)
        self.assertIn("Spell Slots: L1:1/2", raised_result.dynamic_state)
        self.assertEqual(raising_writes, [])

    def test_sequential_context_calls_carry_forward_last_fresh_hp_and_max_hp(self):
        inputs, deps, _, first_writes = make_reviewed_fixture(REVIEWED_CASES[0])
        stale_player_info = {
            "name": "Acheron",
            "hitPoints": 9,
            "maxHitPoints": 20,
            "status": "stale-status",
            "condition": "Stale Condition",
            "condition_affected": ["StaleCondition"],
            "spellcasting": {"spellSlots": {"level1": {"current": 1, "max": 2}}},
        }
        fresh_player_data = {
            "hitPoints": 4,
            "maxHitPoints": 12,
            "status": "alive",
            "condition": "none",
            "condition_affected": [],
            "spellcasting": {"spellSlots": {"level1": {"current": 0, "max": 3}}},
            "classFeatures": [],
        }
        first_inputs = replace(
            inputs,
            player_info=stale_player_info,
            current_hp=9,
            max_hp=20,
            pre_context_player_data=None,
        )
        first_deps = replace(deps, safe_json_load=lambda path: fresh_player_data)
        first_result = assemble_combat_context(first_inputs, first_deps)
        self.assertEqual((first_result.current_hp, first_result.max_hp), (4, 12))
        self.assertIn("Acheron: HP 4/12, alive, Spell Slots: L1:0/3", first_result.dynamic_state)
        self.assertEqual(first_result.player_info["spellcasting"], fresh_player_data["spellcasting"])

        second_inputs = replace(
            first_inputs,
            player_info=first_result.player_info,
            current_hp=first_result.current_hp,
            max_hp=first_result.max_hp,
            pre_context_player_data=first_result.fresh_player_data,
        )
        second_deps = replace(deps, safe_json_load=lambda path: None)
        second_result = assemble_combat_context(second_inputs, second_deps)
        self.assertEqual((second_result.current_hp, second_result.max_hp), (4, 12))
        self.assertIn(
            "Acheron: HP 4/12, stale-status, Stale Condition, conditions: StaleCondition, Spell Slots: L1:0/3",
            second_result.dynamic_state,
        )
        self.assertEqual(first_writes, [])

    def test_owner_explicitly_unpacks_carried_hp_fields_from_context_result(self):
        owner_source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        owner_ast = ast.parse(owner_source)
        owner = next(
            node for node in ast.walk(owner_ast)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_run_combat_simulation_internal"
        )
        assignments = {}
        for node in ast.walk(owner):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            value = node.value
            if (
                isinstance(target, ast.Name)
                and target.id in {"current_hp", "max_hp"}
                and isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "context_result"
            ):
                assignments[target.id] = value.attr
        self.assertEqual(assignments, {"current_hp": "current_hp", "max_hp": "max_hp"})

    def test_inventory_enrichment_keeps_pre_context_read_order_and_fail_open_input(self):
        calls = []
        data = {"equipment": [{"name": "fixture bow"}]}

        class Paths:
            def get_character_path(self, name):
                calls.append(("character_path", name))
                return "fixture-character-path"

        def load(path):
            calls.append(("load", path))
            return data

        def enrich(text, character, party, characters, *, in_combat):
            calls.append(("enhance", character, party, characters, in_combat))
            return text + " [inventory]"

        inventory = enhance_combat_input_with_inventory(
            InventoryContextInputs(
                user_input_text="[Acheron]: Attack",
                player_name_display="Acheron",
                path_manager=Paths(),
                normalize_character_name=lambda value: value.lower(),
                safe_json_load=load,
                enhance_player_input_with_inventory=enrich,
                party_tracker_data={"active_character": "Acheron"},
                debug=lambda *args, **kwargs: None,
            )
        )
        self.assertEqual(inventory.user_input_text, "[Acheron]: Attack [inventory]")
        self.assertIs(inventory.fresh_player_data, data)
        self.assertEqual(calls, [
            ("character_path", "acheron"),
            ("load", "fixture-character-path"),
            ("enhance", data, {"active_character": "Acheron"}, None, True),
        ])

        failed = enhance_combat_input_with_inventory(
            InventoryContextInputs(
                user_input_text="[Acheron]: Wait",
                player_name_display="Acheron",
                path_manager=Paths(),
                normalize_character_name=lambda value: value,
                safe_json_load=lambda path: (_ for _ in ()).throw(OSError("fixture read failed")),
                enhance_player_input_with_inventory=enrich,
                party_tracker_data={},
                debug=lambda *args, **kwargs: None,
                preexisting_player_data=data,
            )
        )
        self.assertEqual(failed.user_input_text, "[Acheron]: Wait")
        self.assertIs(failed.fresh_player_data, data)


if __name__ == "__main__":
    unittest.main()
