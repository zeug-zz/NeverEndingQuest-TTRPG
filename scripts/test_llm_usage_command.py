# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the read-only usage command and Debug rollups."""

import ast
import contextlib
import copy
import io
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.core_chat_test_safety import arm_process_tripwires
from core.combat.commands import FastCommandIO, format_usage_report, run_fast_commands_stage
from core.combat.turn import (
    PhaseGateIO,
    run_input_phase_gate,
    should_consider_tactical_prefetch_replan,
)

PROCESS_TRIPWIRES = arm_process_tripwires()


def tearDownModule() -> None:
    """Fail the process if a live provider or network surface was reached."""
    PROCESS_TRIPWIRES.assert_untouched(unittest.TestCase())


class _FakeRouter:
    def __init__(self, stats):
        self.stats = copy.deepcopy(stats)
        self.snapshot_calls = 0
        self.provider_calls = 0

    def get_usage_stats(self):
        self.snapshot_calls += 1
        return copy.deepcopy(self.stats)

    def call(self, *args, **kwargs):
        self.provider_calls += 1
        raise AssertionError("/usage must not call the provider router")


def _load_main_command_functions(router, turn_time_sync):
    source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    loop_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main_game_loop"
    )
    local_handler = next(
        node
        for node in loop_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "handle_local_command"
    )
    function_names = {
        "_normalize_combat_command_input",
        "_is_usage_command_input",
        "_apply_turn_time_sync_for_input",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    namespace = {
        "colored": lambda text, _color: text,
        "llm": router,
        "apply_turn_time_sync": turn_time_sync,
    }
    module = ast.Module(body=functions + [local_handler], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(REPO_ROOT / "main.py"), "exec"), namespace)
    return namespace


class TestLLMUsageCommand(unittest.TestCase):
    def test_usage_command_reads_snapshots_without_provider_call(self):
        router_stats = {
            "prompt_tokens": 1200,
            "cached_tokens": 300,
            "completion_tokens": 800,
            "calls": 5,
            "total_cost_usd": 0.12,
            "unpriced_calls": 2,
            "cost_complete": False,
        }
        session_stats = {
            "session_tokens": 2000,
            "session_cost_usd": 0.07,
            "session_cost_actual_usd": 0.03,
            "session_cost_estimated_usd": 0.04,
            "session_unpriced_calls": 1,
            "session_cost_complete": False,
            "week_tokens": 4500,
            "week_cost_usd": 0.07,
            "week_cost_actual_usd": 0.05,
            "week_cost_estimated_usd": 0.02,
            "week_unpriced_calls": 2,
            "week_cost_complete": False,
        }
        router = _FakeRouter(router_stats)
        turn_time_sync = mock.Mock(return_value={"status": "applied"})
        functions = _load_main_command_functions(router, turn_time_sync)
        tracker_module = __import__("utils.llm_usage_tracker", fromlist=["get_usage_stats"])
        output = io.StringIO()

        with mock.patch.object(
            tracker_module, "get_usage_stats", return_value=copy.deepcopy(session_stats)
        ) as tracker_snapshot:
            with contextlib.redirect_stdout(output):
                handled = functions["handle_local_command"]("/usage")

        self.assertTrue(handled)
        self.assertEqual(router.snapshot_calls, 1)
        self.assertEqual(router.provider_calls, 0)
        tracker_snapshot.assert_called_once_with()

        report = output.getvalue()
        for expected in (
            "Router: calls 5; tokens 2,000 (prompt 1,200, cached 300, completion 800)",
            "known cost $0.120000 USD; unpriced calls 2; cost coverage incomplete",
            "Session: tokens 2,000; actual $0.030000 USD; estimated $0.040000 USD",
            "known cost $0.070000 USD; unpriced calls 1; cost coverage incomplete",
            "Rolling week: tokens 4,500; actual $0.050000 USD; estimated $0.020000 USD",
            "known cost $0.070000 USD; unpriced calls 2; cost coverage incomplete",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, report)

    def test_combat_usage_bypasses_prefetch_phase_and_pc_dispatch_without_mutations(self):
        class _CombatManager:
            combat_phase = "PC_PHASE"
            current_pc_name = "Acheron"

            def get_next_pending_death_save_pc(self):
                raise AssertionError("/usage must bypass the death-save gate")

            def set_current_pc(self, _name):
                raise AssertionError("/usage must not switch PC focus")

            def handle_combat_command(self, *_args, **_kwargs):
                raise AssertionError("/usage must not reach PC-action dispatch")

        router_stats = {
            "prompt_tokens": 1200,
            "cached_tokens": 300,
            "completion_tokens": 800,
            "calls": 5,
            "total_cost_usd": 0.12,
            "unpriced_calls": 2,
            "cost_complete": False,
        }
        session_stats = {
            "session_tokens": 2000,
            "session_cost_usd": 0.07,
            "session_cost_actual_usd": 0.03,
            "session_cost_estimated_usd": 0.04,
            "session_unpriced_calls": 1,
            "session_cost_complete": False,
            "week_tokens": 4500,
            "week_cost_usd": 0.07,
            "week_cost_actual_usd": 0.05,
            "week_cost_estimated_usd": 0.02,
            "week_unpriced_calls": 2,
            "week_cost_complete": False,
        }
        router = _FakeRouter(router_stats)
        tracker_module = __import__(
            "utils.llm_usage_tracker", fromlist=["get_usage_stats"]
        )
        router_module = __import__("utils.llm_router", fromlist=["llm"])
        encounter = {
            "awaitingPcGroupRoll": True,
            "combat_round": 1,
            "combat_phase": "pc",
        }
        party_tracker = {
            "active_character": "Acheron",
            "worldConditions": {
                "activeCombatEncounter": "encounter-1",
                "time": "12:00",
            },
        }
        history = [{"role": "user", "content": "prior action"}]
        before = (copy.deepcopy(encounter), copy.deepcopy(party_tracker), copy.deepcopy(history))
        manager = _CombatManager()
        local_functions = _load_main_command_functions(router, mock.Mock())
        local_output = io.StringIO()
        combat_output = []
        gate_io = PhaseGateIO(
            emit=combat_output.append,
            flush=mock.Mock(),
            debug=mock.Mock(),
            save_json=mock.Mock(),
            parse_death_save_roll=mock.Mock(),
        )

        with mock.patch.object(
            tracker_module, "get_usage_stats", return_value=copy.deepcopy(session_stats)
        ) as tracker_snapshot, mock.patch.object(router_module, "llm", router):
            with contextlib.redirect_stdout(local_output):
                self.assertTrue(local_functions["handle_local_command"]("/usage"))

            gate = run_input_phase_gate(
                "[Merisiel]: /USAGE",
                encounter_data=encounter,
                multi_pc_manager=manager,
                party_tracker_data=party_tracker,
                json_file_path="encounter.json",
                conversation_history=history,
                conversation_history_file="history.json",
                io=gate_io,
                initiative_gate=mock.Mock(
                    side_effect=AssertionError("/usage must bypass initiative")
                ),
            )
            self.assertEqual(gate.control_action, "proceed")
            self.assertEqual(gate.clean_input, "/USAGE")
            self.assertEqual(gate.input_actor_name, "Merisiel")
            self.assertFalse(should_consider_tactical_prefetch_replan(
                "[Merisiel]: /USAGE", manager
            ))

            fast_io = FastCommandIO(
                emit=combat_output.append,
                flush=mock.Mock(),
                debug=mock.Mock(),
                warning=mock.Mock(),
                save_json=mock.Mock(),
                persist_encounter=mock.Mock(),
            )
            result = run_fast_commands_stage(
                cmd=gate.clean_input.lower(),
                clean_input=gate.clean_input,
                user_input_text="[Merisiel]: /USAGE",
                input_actor_name=gate.input_actor_name,
                multi_pc_manager=manager,
                encounter_data=encounter,
                encounter_id="encounter-1",
                party_tracker_data=party_tracker,
                conversation_history=history,
                conversation_history_file="history.json",
                io=fast_io,
            )

        self.assertEqual(result.control_action, "continue")
        self.assertEqual(router.snapshot_calls, 2)
        self.assertEqual(router.provider_calls, 0)
        self.assertEqual(tracker_snapshot.call_count, 2)
        self.assertEqual(local_output.getvalue().strip(), combat_output[0])
        self.assertEqual(combat_output[0], format_usage_report(router_stats, session_stats))
        self.assertEqual((encounter, party_tracker, history), before)
        gate_io.save_json.assert_not_called()
        fast_io.save_json.assert_not_called()
        fast_io.persist_encounter.assert_not_called()

    def test_usage_command_skips_turn_time_sync_for_tagged_and_casefolded_input(self):
        router = _FakeRouter({})
        turn_time_sync = mock.Mock(return_value={"status": "applied"})
        functions = _load_main_command_functions(router, turn_time_sync)

        for command in ("/usage", " /USAGE ", "[Acheron]: /usage"):
            with self.subTest(command=command):
                self.assertEqual(
                    functions["_apply_turn_time_sync_for_input"](command),
                    {"status": "no_op"},
                )
        turn_time_sync.assert_not_called()

        self.assertEqual(
            functions["_apply_turn_time_sync_for_input"]("/save"),
            {"status": "applied"},
        )
        turn_time_sync.assert_called_once_with()

    def test_usage_local_branch_has_no_campaign_mutators_and_returns_early(self):
        source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        loop_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main_game_loop"
        )
        handler = next(
            node
            for node in loop_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "handle_local_command"
        )
        usage_branch = next(
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "cmd"
            and any(
                isinstance(value, ast.Constant) and value.value == "/usage"
                for value in node.test.comparators
            )
        )
        called_names = {
            call.func.id if isinstance(call.func, ast.Name) else call.func.attr
            for statement in usage_branch.body
            for call in ast.walk(statement)
            if isinstance(call, ast.Call)
            and (isinstance(call.func, ast.Name) or isinstance(call.func, ast.Attribute))
        }
        for forbidden in (
            "call",
            "apply_turn_time_sync",
            "safe_write_json",
            "update_character_info",
            "save_conversation_history",
            "get_ai_response",
            "track_response",
            "track_image_cost",
            "reset_usage_stats",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, called_names)
        self.assertIsInstance(usage_branch.body[-1], ast.Return)
        self.assertIsInstance(usage_branch.body[-1].value, ast.Constant)
        self.assertIs(usage_branch.body[-1].value.value, True)

        local_dispatch = next(
            node
            for node in ast.walk(loop_node)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Call)
            and isinstance(node.test.func, ast.Name)
            and node.test.func.id == "handle_local_command"
        )
        self.assertTrue(
            any(isinstance(statement, ast.Continue) for statement in local_dispatch.body)
        )

    def test_incomplete_or_older_snapshots_use_unknown_placeholders(self):
        functions = _load_main_command_functions(_FakeRouter({}), mock.Mock())

        report = format_usage_report({}, {})

        self.assertIn("Router: calls --; tokens --", report)
        self.assertIn("known cost --; unpriced calls --; cost coverage unknown", report)
        self.assertIn("Session: tokens --; actual --; estimated --", report)
        self.assertIn("Rolling week: tokens --; actual --; estimated --", report)


class TestDebugUsageRollupRendering(unittest.TestCase):
    def test_debug_payload_adds_provenance_without_replacing_legacy_fields(self):
        source = (REPO_ROOT / "web" / "web_interface.py").read_text(encoding="utf-8")
        for prefix in ("session", "week"):
            fields = (
                "%s_cost_actual_usd" % prefix,
                "%s_cost_estimated_usd" % prefix,
                "%s_unpriced_calls" % prefix,
                "%s_cost_complete" % prefix,
            )
            for field in fields:
                with self.subTest(field=field):
                    self.assertIn("'%s': stats.get('%s')" % (field, field), source)
                    self.assertIn("'%s': None" % field, source)

        for legacy_field in ("tpm", "rpm", "total_tokens"):
            self.assertIn("'%s': stats.get('%s', 0)" % (legacy_field, legacy_field), source)

    def test_debug_template_renders_provenance_and_older_payload_placeholders(self):
        template = (REPO_ROOT / "web" / "templates" / "game_interface.html").read_text(
            encoding="utf-8"
        )
        for element_id in (
            "session-cost-actual-usd",
            "session-cost-estimated-usd",
            "session-unpriced-calls",
            "session-cost-complete",
            "week-cost-actual-usd",
            "week-cost-estimated-usd",
            "week-unpriced-calls",
            "week-cost-complete",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s">--</span>' % element_id, template)
                self.assertIn("document.getElementById('%s')" % element_id, template)

        self.assertIn("return '--';", template)
        self.assertIn("data.tpm", template)
        self.assertIn("data.rpm", template)
        self.assertIn("data.total_tokens", template)


if __name__ == "__main__":
    unittest.main()
