# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free stop/go checks for the copied mapping-pilot runtime seams."""

from __future__ import annotations

import ast
import pathlib
import symtable
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Arm process-wide guards before importing any production runtime owner.
from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

# The prompt module is provider-free. main.py and combat_manager.py are
# deliberately checked as source because importing them initializes runtime
# owners and is unnecessary to prove their name-resolution contracts.
import core.combat.prompts as combat_prompts


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _tree(relative_path: str) -> ast.Module:
    return ast.parse(_source(relative_path), filename=relative_path)


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("missing function %s" % name)


def _module_scope(source: str, filename: str) -> symtable.SymbolTable:
    return symtable.symtable(source, filename, "exec")


def _function_scope(
    module_scope: symtable.SymbolTable, name: str
) -> symtable.SymbolTable:
    for child in module_scope.get_children():
        if child.get_name() == name and child.get_type() == "function":
            return child
    raise AssertionError("missing function scope %s" % name)


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _parent_map(root: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(root)
        for child in ast.iter_child_nodes(parent)
    }


def _assignment_target_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }


def _noop(*args, **kwargs):
    return None


class MappingPilotSeamTests(unittest.TestCase):
    def test_a_main_dm_note_binding_is_common_to_party_sizes(self):
        relative_path = "main.py"
        source = _source(relative_path)
        tree = ast.parse(source, filename=relative_path)
        import_bindings = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "core.ai.inventory_context_integration"
            and any(
                alias.name == "build_enhanced_dm_note"
                and alias.asname is None
                for alias in node.names
            )
        ]
        self.assertEqual(
            len(import_bindings),
            1,
            "seam (a): expected main.py:189 to bind the module global "
            "build_enhanced_dm_note",
        )

        main_game_loop = _top_level_function(tree, "main_game_loop")
        call_sites = [
            node
            for node in ast.walk(tree)
            if _call_name(node) == "build_enhanced_dm_note"
        ]
        self.assertEqual(
            len(call_sites),
            1,
            "seam (a): expected the sole exploration call at main.py:8035; "
            "a separate party-size call path would need to be enumerated",
        )
        call = call_sites[0]
        calls_in_loop = [
            node
            for node in ast.walk(main_game_loop)
            if _call_name(node) == "build_enhanced_dm_note"
        ]
        self.assertEqual(
            calls_in_loop,
            [call],
            "seam (a): main.py:8035 must be inside main_game_loop",
        )
        multi_pc_note_calls = [
            node
            for node in ast.walk(main_game_loop)
            if _call_name(node) == "build_multi_pc_dm_note"
        ]
        self.assertTrue(
            len(multi_pc_note_calls) == 1
            and multi_pc_note_calls[0].lineno < call.lineno,
            "seam (a): the separate multi-PC note construction at main.py:7932 "
            "must converge on the shared main.py:8035 enhancement call",
        )

        loop_scope = _function_scope(
            _module_scope(source, relative_path), "main_game_loop"
        )
        binding = loop_scope.lookup("build_enhanced_dm_note")
        self.assertTrue(
            binding.is_global() and not binding.is_local(),
            "seam (a): main.py:8035 must resolve the patchable module global "
            "bound at main.py:189",
        )

        multiparty_tag_branches = [
            node
            for node in ast.walk(main_game_loop)
            if isinstance(node, ast.If)
            and any(
                isinstance(child, ast.Name) and child.id == "should_tag_messages"
                for child in ast.walk(node.test)
            )
        ]
        self.assertTrue(
            multiparty_tag_branches and call.lineno < multiparty_tag_branches[0].lineno,
            "seam (a): the shared DM-note call at main.py:8035 must precede "
            "party-size-specific message handling near main.py:8053",
        )

    def test_b_combat_prompt_caller_resolves_patched_module_global(self):
        relative_path = "core/combat/prompts.py"
        tree = _tree(relative_path)
        context_function = _top_level_function(tree, "assemble_combat_context")
        calls = [
            node
            for node in ast.walk(context_function)
            if _call_name(node) == "assemble_combat_prompt"
        ]
        self.assertEqual(
            len(calls),
            1,
            "seam (b): expected assemble_combat_context to call the module "
            "global assemble_combat_prompt at core/combat/prompts.py:763",
        )
        self.assertTrue(
            callable(combat_prompts.assemble_combat_prompt),
            "seam (b): core.combat.prompts.assemble_combat_prompt must be "
            "importable and patchable",
        )

        encounter = {
            "id": "seam-encounter",
            "encounterId": "seam-encounter",
            "combat_round": 1,
            "preroll_cache": {
                "round": 1,
                "rolls": "Acheron: d20=10",
                "preroll_id": "1-seam",
            },
            "creatures": [
                {
                    "name": "Acheron",
                    "type": "player",
                    "initiative": 15,
                    "currentHitPoints": 10,
                    "maxHitPoints": 10,
                    "armorClass": 15,
                    "status": "alive",
                },
                {
                    "name": "Goblin",
                    "type": "enemy",
                    "initiative": 10,
                    "currentHitPoints": 7,
                    "maxHitPoints": 7,
                    "armorClass": 13,
                    "status": "alive",
                },
            ],
        }
        inputs = combat_prompts.CombatContextInputs(
            encounter_data=encounter,
            multi_pc_manager=None,
            party_tracker_data={
                "module": "Capture_Arena",
                "partyMembers": ["Acheron"],
                "partyNPCs": [],
                "worldConditions": {"activeCombatEncounter": "seam-encounter"},
            },
            player_info={"name": "Acheron", "spellcasting": {}},
            player_name_display="Acheron",
            current_hp=10,
            max_hp=10,
            pre_context_player_data=None,
            path_manager=SimpleNamespace(
                get_character_path=lambda name: "characters/acheron.json"
            ),
            json_file_path="characters/acheron.json",
            conversation_history=[],
            user_input_text="Move toward the gate.",
        )
        dependencies = combat_prompts.CombatContextDependencies(
            normalize_character_name=lambda name: name,
            safe_json_load=lambda path: {
                "hitPoints": 10,
                "maxHitPoints": 10,
                "status": "alive",
                "condition": "none",
                "condition_affected": [],
                "spellcasting": {},
            },
            load_npc_with_fuzzy_match=lambda name, manager: (None, None),
            collect_authoritative_combat_roster=lambda data, **kwargs: [
                {"name": creature["name"], "type": creature["type"]}
                for creature in data["creatures"]
            ],
            generate_prerolls=lambda data, **kwargs: "",
            save_json_file=_noop,
            module_path_manager_factory=lambda module: SimpleNamespace(
                get_monster_path=lambda name: "monsters/%s.json" % name
            ),
            file_exists=lambda path: False,
            logger_debug=_noop,
            logger_error=_noop,
            emit=_noop,
            random_int=lambda low, high: low,
            fallback_initiative_tracker=lambda data, history, round_number: (
                "Initiative [>] Acheron\n"
                "```json\n"
                '{"player_name":"Acheron","turn_window":["Acheron"],'
                '"process_until":"Acheron"}\n'
                "```"
            ),
        )
        sentinel_result = combat_prompts.CombatPromptResult(
            dynamic_state="sentinel dynamic state",
            user_prompt="sentinel prompt",
        )
        with mock.patch.object(
            combat_prompts,
            "assemble_combat_prompt",
            return_value=sentinel_result,
        ) as patched_assembler:
            result = combat_prompts.assemble_combat_context(inputs, dependencies)

        self.assertEqual(
            patched_assembler.call_count,
            1,
            "seam (b): patching core.combat.prompts.assemble_combat_prompt "
            "must intercept the caller at line 763",
        )
        self.assertEqual(result.user_prompt, "sentinel prompt")
        self.assertEqual(
            patched_assembler.call_args.args[0].player_action,
            "Move toward the gate.",
        )

    def test_c_raw_combat_response_reaches_patchable_validation_binding(self):
        manager_path = "core/combat/combat_manager.py"
        manager_tree = _tree(manager_path)
        manager_source = _source(manager_path)
        manager_scope = _module_scope(manager_source, manager_path)

        wrapper = _top_level_function(manager_tree, "validate_combat_response")
        wrapper_args = [argument.arg for argument in wrapper.args.args]
        self.assertTrue(
            wrapper_args and wrapper_args[0] == "response",
            "seam (c): combat_manager.validate_combat_response at "
            "core/combat/combat_manager.py:1429 must accept the raw response",
        )
        stage_calls = [
            node
            for node in ast.walk(wrapper)
            if _call_name(node) == "validate_stage"
        ]
        self.assertTrue(
            stage_calls
            and stage_calls[0].args
            and isinstance(stage_calls[0].args[0], ast.Name)
            and stage_calls[0].args[0].id == "response",
            "seam (c): combat_manager.py:1437 must forward response unchanged "
            "to core.combat.validation.validate_combat_response",
        )

        retry_builder = _top_level_function(
            manager_tree, "_build_combat_retry_dependencies"
        )
        dependency_bindings = [
            keyword.value
            for node in ast.walk(retry_builder)
            if isinstance(node, ast.Call)
            and _call_name(node) == "CombatRetryDependencies"
            for keyword in node.keywords
            if keyword.arg == "validate_combat_response"
        ]
        self.assertTrue(
            len(dependency_bindings) == 1
            and isinstance(dependency_bindings[0], ast.Name)
            and dependency_bindings[0].id == "validate_combat_response",
            "seam (c): retry dependencies must resolve the module global at "
            "core/combat/combat_manager.py:1482",
        )
        manager_symbol = _function_scope(
            manager_scope, "_build_combat_retry_dependencies"
        ).lookup("validate_combat_response")
        self.assertTrue(
            manager_symbol.is_global() and not manager_symbol.is_local(),
            "seam (c): combat_manager.py:1482 must resolve the patchable "
            "module global, not a captured local alias",
        )

        turn_path = "core/combat/turn.py"
        turn_tree = _tree(turn_path)
        retry_stage = _top_level_function(
            turn_tree, "run_combat_provider_retry_stage"
        )
        calls = [
            node
            for node in ast.walk(retry_stage)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "validate_combat_response"
        ]
        self.assertTrue(
            len(calls) == 1
            and calls[0].args
            and isinstance(calls[0].args[0], ast.Attribute)
            and isinstance(calls[0].args[0].value, ast.Name)
            and calls[0].args[0].value.id == "result"
            and calls[0].args[0].attr == "ai_response",
            "seam (c): turn.py:1085 must pass result.ai_response to the "
            "validation wrapper",
        )
        raw_capture_lines = [
            node.lineno
            for node in ast.walk(retry_stage)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "result"
                and target.attr == "ai_response"
                for target in node.targets
            )
        ]
        self.assertTrue(
            raw_capture_lines and min(raw_capture_lines) < calls[0].lineno,
            "seam (c): turn.py:990 must retain the candidate response before "
            "the validation observation at turn.py:1085",
        )

    def test_d_user_input_entry_supports_launcher_owned_turn_identity(self):
        relative_path = "main.py"
        source = _source(relative_path)
        tree = ast.parse(source, filename=relative_path)
        main_game_loop = _top_level_function(tree, "main_game_loop")
        parents = _parent_map(main_game_loop)
        input_assignments = []
        for node in ast.walk(main_game_loop):
            if _call_name(node) != "input":
                continue
            parent = parents.get(node)
            if isinstance(parent, ast.Assign):
                target_names = _assignment_target_names(parent.targets[0])
                input_assignments.append((node, target_names))

        user_turn_calls = [
            (call, targets)
            for call, targets in input_assignments
            if "user_input_text" in targets
        ]
        self.assertEqual(
            len(user_turn_calls),
            2,
            "seam (d): expected the two mutually exclusive per-user-input "
            "sites at main.py:7178 and main.py:7180",
        )
        user_turn_lines = {call.lineno for call, _targets in user_turn_calls}
        self.assertEqual(
            user_turn_lines,
            {7178, 7180},
            "seam (d): user_input_text entry locations changed; re-audit "
            "the launcher boundary in main.py",
        )

        main_scope = _function_scope(
            _module_scope(source, relative_path), "main_game_loop"
        )
        input_binding = main_scope.lookup("input")
        self.assertTrue(
            input_binding.is_global() and not input_binding.is_local(),
            "seam (d): main.py:7178/7180 must resolve the builtins input "
            "function so a copied-runtime launcher can wrap it",
        )

        nearest_loops = []
        for call, _targets in user_turn_calls:
            parent = parents.get(call)
            while parent is not None and not isinstance(parent, ast.While):
                parent = parents.get(parent)
            nearest_loops.append(parent)
        self.assertTrue(
            nearest_loops[0] is not None and nearest_loops[0] is nearest_loops[1],
            "seam (d): both user-input sites must share the main logical-turn "
            "loop at main.py:7178/7180",
        )

        all_input_calls = [
            node for node in ast.walk(main_game_loop) if _call_name(node) == "input"
        ]
        nested_prompt_targets = [
            name
            for _call, targets in input_assignments
            for name in targets
            if name != "user_input_text"
        ]
        self.assertTrue(
            len(all_input_calls) == 4
            and sorted(nested_prompt_targets) == ["level_up_input", "level_up_input"],
            "seam (d): distinguish main user-input entries from nested "
            "level-up prompts at main.py:6698 and main.py:8371",
        )

        enhancement_calls = [
            node
            for node in ast.walk(main_game_loop)
            if _call_name(node) == "build_enhanced_dm_note"
        ]
        self.assertTrue(
            enhancement_calls
            and max(user_turn_lines) < enhancement_calls[0].lineno,
            "seam (d): the user-input boundary must precede the shared prompt "
            "path at main.py:8035",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
