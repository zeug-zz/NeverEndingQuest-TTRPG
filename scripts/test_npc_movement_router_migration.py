# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Guarded vertical tests for NPC movement decision router migration."""

import ast
import json
from pathlib import Path
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from scripts.core_chat_test_safety import (
    arm_process_tripwires,
    install_in_memory_usage_tracker,
)

_TRIPWIRES = arm_process_tripwires()
ROOT = Path(__file__).resolve().parents[1]

# Runtime imports intentionally happen only after process-wide tripwires.
import utils.ai_client_factory as factory
from utils.llm_router import GameLLMTerminalError, llm, reset_usage_stats
from utils.llm_runtime import make_legacy_receipt_observer


class _FakeSDK:
    def __init__(self, events, response=None, failure=None):
        self.events = events
        self.response = response
        self.failure = failure
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        self.events.append(("sdk-options", kwargs))
        return self

    def create(self, **kwargs):
        self.events.append(("sdk-call", kwargs))
        if self.failure is not None:
            raise self.failure
        return self.response


def _response(content):
    return {
        "choices": [{"message": {"content": content}}],
        "model": "fixture-resolved-model",
        "usage": {"prompt_tokens": 12, "completion_tokens": 6, "cost": 0.0},
    }


def _functions():
    tree = ast.parse((ROOT / "core/ai/action_handler.py").read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return ast.unparse(call.func)
    return ""


class NpcMovementRouterMigrationTests(unittest.TestCase):
    def setUp(self):
        reset_usage_stats()
        self.automatic_tracker = install_in_memory_usage_tracker(self)

    def tearDown(self):
        reset_usage_stats()

    def _execute(self, scripted, *, attempt=1, usage_enabled=True, fallback_script=None):
        events, trackers, traces = [], [], []
        sdk = _FakeSDK(events, response=scripted[0], failure=scripted[1])
        fallback_sdk = (
            _FakeSDK(events, response=fallback_script[0], failure=fallback_script[1])
            if fallback_script is not None else None
        )

        def create_client(**kwargs):
            events.append(("client-factory", kwargs))
            return fallback_sdk if kwargs.get("use_fallback") else sdk

        class Tracker:
            def track(self, response, metadata):
                trackers.append((response, metadata))
                events.append(("tracker", response))

        observer_factory = lambda **kwargs: make_legacy_receipt_observer(
            **kwargs,
            tracker_getter=lambda: Tracker(),
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: (traces.append((event, fields)), events.append(("trace", event, fields))),
        )
        namespace = {
            "GameLLMTerminalError": GameLLMTerminalError,
            "llm": llm,
            "make_legacy_receipt_observer": observer_factory,
            "USAGE_TRACKING_AVAILABLE": usage_enabled,
            "json": json,
            "re": re,
            "debug": lambda *args, **kwargs: None,
            "info": lambda *args, **kwargs: None,
            "warning": lambda *args, **kwargs: None,
            "error": lambda *args, **kwargs: None,
        }
        function = _functions()["get_ai_npc_movement_decision"]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     "<actual-npc-movement-function>", "exec"), namespace)
        real_call = llm.call
        facade_results = []

        def routed_call(*args, **kwargs):
            result = real_call(*args, **kwargs)
            facade_results.append(result)
            return result

        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", side_effect=create_client) as create_client_mock:
                with mock.patch.object(factory, "handle_provider_error", return_value={"should_fallback": True}) as error_handler:
                    with mock.patch.object(llm, "call", side_effect=routed_call) as facade_call:
                        try:
                            result = namespace["get_ai_npc_movement_decision"](
                                "Mira", "Mira left for the watchtower",
                                {"description": "Guide", "attitude": "friendly"},
                                {"locations": [{"locationId": "L1", "name": "Gate"},
                                               {"locationId": "L2", "name": "Tower"}]},
                                "L1", "fixture-module", [], attempt,
                            )
                            terminal_error = None
                        except GameLLMTerminalError as exc:
                            result = None
                            terminal_error = exc
        return (result, events, trackers, traces, facade_call, facade_results,
                create_client_mock, error_handler, terminal_error)

    def test_valid_json_preserves_decision_shape_and_attempt_specific_prompt(self):
        decision = {"action": "move", "reasoning": "Duty", "newLocation": "L2"}
        prompts = []
        for attempt in (1, 3):
            result, events, trackers, traces, facade, values, create, handle, terminal = self._execute(
                (_response(json.dumps(decision)), None), attempt=attempt
            )
            self.assertEqual(result, decision)
            self.assertIsInstance(values[0], str)
            self.assertEqual(facade.call_args.kwargs["task"], "updates")
            self.assertIs(facade.call_args.kwargs["json_output"], False)
            self.assertEqual(facade.call_args.kwargs["temperature"], 0.7)
            for forbidden in ("model", "timeout", "client", "use_fallback", "empty_retry_limit"):
                self.assertNotIn(forbidden, facade.call_args.kwargs)
            request = next(event[1] for event in events if event[0] == "sdk-call")
            self.assertEqual([row["role"] for row in request["messages"]], ["system", "user"])
            prompts.append(request["messages"][0]["content"])
            self.assertIn(f"Attempt: {attempt}/5", request["messages"][0]["content"])
            self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
            self.assertEqual((len(trackers), len(traces)), (1, 1))
            self.assertEqual(traces[0][1]["site"], "npc_movement_decision")
            self.assertEqual(traces[0][1]["cost_usd"], 0.0)
            self.assertEqual(traces[0][1]["purpose"], "npc_movement_decision")
            self.assertEqual(create.call_count, 1)
            handle.assert_not_called()
            self.assertIsNone(terminal)
        self.assertNotEqual(prompts[0], prompts[1])

    def test_malformed_json_retains_none_result_and_one_receipt(self):
        result, events, trackers, traces, facade, _, _, _, terminal = self._execute((_response("not json"), None))
        self.assertIsNone(result)
        self.assertEqual(facade.call_args.kwargs["task"], "updates")
        self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
        self.assertEqual((len(trackers), len(traces)), (1, 1))
        self.assertIsNone(terminal)

    def test_nonterminal_transport_fallback_is_router_owned_once(self):
        result, events, trackers, traces, facade, values, create, handle, terminal = self._execute(
            (None, RuntimeError("ordinary transport failure")),
            fallback_script=(_response('{"action":"remove"}'), None),
        )
        self.assertEqual(result, {"action": "remove"})
        self.assertEqual(values, ['{"action":"remove"}'])
        self.assertEqual(facade.call_count, 1)
        self.assertEqual([event[1] for event in events if event[0] == "client-factory"],
                         [{}, {"use_fallback": True}])
        self.assertEqual(create.call_count, 2)
        self.assertEqual(handle.call_count, 1)
        self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 2)
        self.assertEqual([row[1]["outcome"] for row in traces], ["transport_error", "response"])
        self.assertEqual(len(trackers), 1)
        self.assertIsNone(terminal)

    def test_terminal_quota_refusal_filter_escape_with_one_call_and_no_decision(self):
        terminal = (
            ("quota", None, RuntimeError("insufficient_quota")),
            ("refusal", {"choices": [{"message": {"content": "blocked", "refusal": "blocked"}}]}, None),
            ("content_filter", {"choices": [{"message": {"content": "blocked", "refusal": None},
                                                    "finish_reason": "content_filter"}]}, None),
        )
        for kind, raw, failure in terminal:
            with self.subTest(kind=kind):
                result, events, trackers, traces, facade, _, create, handle, caught = self._execute((raw, failure))
                self.assertIsNone(result)
                self.assertIsInstance(caught, GameLLMTerminalError)
                self.assertEqual(caught.terminal_kind, kind)
                self.assertEqual(facade.call_count, 1)
                self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
                self.assertEqual(create.call_count, 1)
                handle.assert_not_called()
                self.assertEqual(len(traces), 1)
                self.assertEqual(len(trackers), 0 if kind == "quota" else 1)

    def test_caller_rethrows_terminal_before_broad_failure_and_attempt_application(self):
        owner = _functions()["move_background_npc"]
        outer_try = next(node for node in ast.walk(owner) if isinstance(node, ast.Try)
                         and any(isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
                                 for handler in node.handlers)
                         and any(isinstance(handler.type, ast.Name) and handler.type.id == "GameLLMTerminalError"
                                 for handler in node.handlers))
        handler_types = [ast.unparse(handler.type) if handler.type else None for handler in outer_try.handlers]
        self.assertLess(handler_types.index("GameLLMTerminalError"), handler_types.index("Exception"))
        terminal_handler = outer_try.handlers[handler_types.index("GameLLMTerminalError")]
        self.assertEqual(ast.unparse(terminal_handler.body[0]), "raise")

        attempt_loop = next(node for node in ast.walk(owner) if isinstance(node, ast.For)
                            and any(isinstance(child, ast.Call) and _call_name(child) == "get_ai_npc_movement_decision"
                                    for child in ast.walk(node)))
        calls, validations, applications = [], [], []
        namespace = {
            "range": range,
            "debug": lambda *args, **kwargs: None,
            "get_ai_npc_movement_decision": lambda *args: (calls.append(args) or (_ for _ in ()).throw(GameLLMTerminalError("quota"))),
            "validate_npc_movement_decision": lambda *args: validations.append(args),
            "execute_npc_movement_decision": lambda *args: applications.append(args),
            "max_attempts": 5,
            "npc_name": "Mira", "context": "Mira left", "npc_data": {},
            "area_data": {}, "location_id": "L1", "module_name": "module", "party_npcs": [],
        }
        wrapper = ast.FunctionDef(
            name="run_attempt_loop",
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg=name) for name in (
                    "max_attempts", "npc_name", "context", "npc_data", "area_data",
                    "location_id", "module_name", "party_npcs",
                )],
                kwonlyargs=[], kw_defaults=[], defaults=[],
            ),
            body=[attempt_loop],
            decorator_list=[],
        )
        statement = ast.Module(body=[wrapper], type_ignores=[])
        with self.assertRaises(GameLLMTerminalError):
            exec(compile(ast.fix_missing_locations(statement), "<actual-npc-attempt-loop>", "exec"), namespace)
            namespace["run_attempt_loop"](5, "Mira", "Mira left", {}, {}, "L1", "module", [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-1], 1)
        self.assertEqual(validations, [])
        self.assertEqual(applications, [])

    def test_automatic_accounting_and_process_tripwires(self):
        result, _, trackers, traces, _, _, _, _, terminal = self._execute(
            (_response('{"action":"remove"}'), None), usage_enabled=False
        )
        self.assertEqual(result, {"action": "remove"})
        self.assertEqual(trackers, [])
        self.assertEqual(len(self.automatic_tracker.records), 1)
        self.assertEqual(self.automatic_tracker.records[0][1]["task"], "updates")
        self.assertEqual(len(traces), 1)
        self.assertIsNone(terminal)
        _TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
