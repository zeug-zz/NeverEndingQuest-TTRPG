# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Decision Stage Tests - Provider-free seam contracts.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import ast
import inspect
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock

from core.combat.decisions import (
    PCActionDecisionStatus,
    pc_action_decision_eligible,
    resolve_pc_action_actor,
    run_pc_action_decision,
)
from scripts.test_llm_router import ProviderTripwire


class CombatPCActionDecisionTests(unittest.TestCase):
    def setUp(self):
        self.manager = type("Manager", (), {"combat_phase": "PC_PHASE", "current_pc_name": "Manager PC"})()
        self.trace = Mock()
        self.parser_loader = Mock()

    def _run(self, *, parsed=None, applied=True, eligible=True, loader=None):
        parsed = parsed if parsed is not None else {"handled": False, "fallback_reason": "unrecognized_action"}
        parse = Mock(return_value=parsed)
        apply = Mock(return_value=applied)
        self.parser_loader.return_value = (parse, apply)
        with ProviderTripwire() as tripwire:
            result = run_pc_action_decision(
                eligible=eligible,
                clean_input="attack Goblin roll 18",
                encounter_data={"creatures": []},
                party_tracker_data={"active_character": "Tracker PC"},
                actor_name="Input PC",
                multi_pc_manager=self.manager,
                encounter_id="encounter-1",
                decision_started_at=1.25,
                trace_decision=self.trace,
                parser_loader=loader or self.parser_loader,
            )
            tripwire.assert_untouched(self)
        return result, parse, apply

    def test_eligible_parse_miss_is_declined_and_falls_through_once(self):
        result, parse, apply = self._run()
        self.assertEqual(result.status, PCActionDecisionStatus.DECLINED)
        parse.assert_called_once_with(
            "attack Goblin roll 18", {"creatures": []}, {"active_character": "Tracker PC"}, actor_name="Input PC"
        )
        apply.assert_not_called()
        self.trace.assert_called_once_with(
            "pc_phase_parser", "llm_fallback", 1.25, False,
            outcome="miss", llm_fallback=True,
        )

    def test_unavailable_gate_and_missing_parser_are_distinct_and_do_not_trace(self):
        result, _, _ = self._run(eligible=False)
        self.assertEqual(result.status, PCActionDecisionStatus.UNAVAILABLE)
        self.parser_loader.assert_not_called()
        self.trace.assert_not_called()

        missing = Mock(side_effect=ImportError("parser absent"))
        result, _, _ = self._run(loader=missing)
        self.assertEqual(result.status, PCActionDecisionStatus.UNAVAILABLE)
        self.assertIsInstance(result.import_error, ImportError)
        missing.assert_called_once_with()
        self.trace.assert_called_once_with(
            "pc_phase_parser", "llm_fallback", 1.25, False,
            outcome="unavailable", llm_fallback=True,
        )

    def test_gate_preserves_flag_phase_slash_and_backslash_eligibility(self):
        def eligible(enabled=True, phase="PC_PHASE", clean="move", cmd="move"):
            self.manager.combat_phase = phase
            return pc_action_decision_eligible(
                enabled=enabled,
                multi_pc_manager=self.manager,
                clean_input=clean,
                cmd=cmd,
            )

        self.assertTrue(eligible())
        self.assertFalse(eligible(enabled=False))
        self.assertFalse(eligible(phase="ENEMY_PHASE"))
        self.assertFalse(eligible(clean="/att Goblin 18", cmd="/att Goblin 18"))
        self.assertFalse(eligible(clean="\\att Goblin 18", cmd="\\att Goblin 18"))
        self.assertFalse(pc_action_decision_eligible(enabled=True, multi_pc_manager=None, clean_input="move", cmd="move"))

    def test_actor_precedence_is_input_then_manager_then_tracker_then_default(self):
        self.assertEqual(resolve_pc_action_actor("Input", self.manager, {"active_character": "Tracker"}), "Input")
        self.assertEqual(resolve_pc_action_actor(None, self.manager, {"active_character": "Tracker"}), "Manager PC")
        self.assertEqual(resolve_pc_action_actor(None, None, {"active_character": "Tracker"}), "Tracker")
        self.assertEqual(resolve_pc_action_actor(None, None, {}), "Player")

    def test_handled_apply_success_keeps_existing_deterministic_trace(self):
        result, parse, apply = self._run(parsed={"handled": True, "log_msg": "old history"})
        self.assertEqual(result.status, PCActionDecisionStatus.HANDLED)
        apply.assert_called_once_with(
            {"handled": True, "log_msg": "old history"}, self.manager,
            {"creatures": []}, "encounter-1", "Input PC"
        )
        self.trace.assert_called_once_with(
            "pc_phase_parser", "deterministic", 1.25, True,
            outcome="hit", llm_fallback=False,
        )
        parse.assert_called_once()

    def test_handled_apply_false_falls_back_without_emitting_or_history_mutation(self):
        result, _, apply = self._run(
            parsed={"handled": True, "mechanical_feedback": "must-not-emit", "log_msg": "must-not-log"},
            applied=False,
        )
        self.assertEqual(result.status, PCActionDecisionStatus.DECLINED)
        apply.assert_called_once()
        self.assertIsNotNone(result.parse_result["mechanical_feedback"])
        self.assertIsNotNone(result.parse_result["log_msg"])
        self.trace.assert_called_once_with(
            "pc_phase_parser", "llm_fallback", 1.25, False,
            outcome="false_positive", llm_fallback=True,
        )

    def test_unexpected_parser_and_apply_errors_propagate(self):
        def exploding_parser(*args, **kwargs):
            raise RuntimeError("parse broke")

        def exploding_loader():
            return exploding_parser, Mock()

        with self.assertRaisesRegex(RuntimeError, "parse broke"):
            self._run(loader=exploding_loader)

        def handled_loader():
            return Mock(return_value={"handled": True}), Mock(side_effect=RuntimeError("apply broke"))

        with self.assertRaisesRegex(RuntimeError, "apply broke"):
            self._run(loader=handled_loader)

    def test_decision_stage_is_provider_free_and_has_no_added_provider_operations(self):
        source = inspect.getsource(run_pc_action_decision)
        for forbidden in ("llm.call", "chat.completions.create", "provider_call", "client."):
            self.assertNotIn(forbidden, source)
        result, _, _ = self._run()
        self.assertEqual(result.status, PCActionDecisionStatus.DECLINED)

    def test_tripwire_self_test_blocks_provider_and_network_without_networking(self):
        with ProviderTripwire() as tripwire:
            with self.assertRaisesRegex(AssertionError, "provider tripwire"):
                socket.create_connection(("example.invalid", 443))
            tripwire.guards["socket.create_connection"].assert_called_once()

    def test_actual_owner_ast_orders_stage_and_gates_effects_on_handled(self):
        owner_source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        owner = next(
            node for node in ast.walk(ast.parse(owner_source))
            if isinstance(node, ast.FunctionDef) and node.name == "_run_combat_simulation_internal"
        )
        owner_calls = [
            node for node in ast.walk(owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "prepare_combat_normal_turn"
        ]
        self.assertEqual(len(owner_calls), 1)

        turn_source = Path("core/combat/turn.py").read_text(encoding="utf-8")
        turn_module = ast.parse(turn_source)
        turn_stage = next(
            node for node in turn_module.body
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_combat_normal_turn"
        )
        calls = [
            node for node in ast.walk(turn_stage)
            if isinstance(node, ast.Call)
        ]
        def call_lines(name):
            return [
                node.lineno for node in calls
                if (isinstance(node.func, ast.Name) and node.func.id == name)
                or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            ]
        phase_calls = call_lines("input_phase_gate")
        fast_calls = call_lines("fast_command_stage")
        deterministic_calls = call_lines("deterministic_command_stage")
        seam_calls = call_lines("run_pc_action_decision")
        inventory_calls = call_lines("enhance_inventory_context")
        context_calls = call_lines("assemble_context")
        self.assertEqual([len(group) for group in (
            phase_calls, fast_calls, deterministic_calls, seam_calls, inventory_calls, context_calls,
        )], [1, 1, 1, 1, 1, 1])
        self.assertLess(phase_calls[0], fast_calls[0])
        self.assertLess(fast_calls[0], deterministic_calls[0])
        self.assertLess(deterministic_calls[0], seam_calls[0])
        self.assertLess(seam_calls[0], inventory_calls[0])
        self.assertLess(inventory_calls[0], context_calls[0])

        handled_gate = next(
            node for node in ast.walk(turn_stage)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Attribute)
            and node.test.left.attr == "status"
            and isinstance(node.test.comparators[0], ast.Attribute)
            and node.test.comparators[0].attr == "HANDLED"
        )
        gated = list(ast.walk(ast.Module(body=handled_gate.body, type_ignores=[])))
        gated_attributes = [
            node.func.attr for node in gated
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertIn("emit", gated_attributes)
        self.assertIn("save_json", gated_attributes)
        self.assertTrue(any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            for node in gated
        ))
        self.assertTrue(any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "CombatNormalTurnResult"
            and isinstance(node.value.args[0], ast.Constant)
            and node.value.args[0].value == "continue"
            for node in gated
        ))
        self.assertEqual(handled_gate.orelse, [])
        self.assertGreater(context_calls[0], handled_gate.end_lineno)
        self.assertIn('not clean_input.startswith("/")', inspect.getsource(pc_action_decision_eligible))
        self.assertIn('not cmd.startswith("\\\\")', inspect.getsource(pc_action_decision_eligible))


if __name__ == "__main__":
    unittest.main()
