# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free vertical tests for starting-location router migration."""

import ast
import json
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace

from scripts.core_chat_test_safety import (
    arm_process_tripwires,
    install_in_memory_usage_tracker,
)

_TRIPWIRES = arm_process_tripwires()
ROOT = Path(__file__).resolve().parents[1]

# Imports intentionally occur after the process-wide SDK/network/write guards.
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
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 6,
            "cost": 0.0,
        },
    }


def _selected_function():
    tree = ast.parse((ROOT / "core/ai/action_handler.py").read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_ai_analyze_starting_location"
    )


class StartingLocationRouterMigrationTests(unittest.TestCase):
    def setUp(self):
        reset_usage_stats()
        self.automatic_tracker = install_in_memory_usage_tracker(self)

    def tearDown(self):
        reset_usage_stats()

    def _execute(self, sdk_scripts, *, usage_enabled=True):
        events = []
        trackers = []
        traces = []
        facade_results = []
        clients = [_FakeSDK(events, response=value, failure=failure) for value, failure in sdk_scripts]

        def create_client(**kwargs):
            events.append(("client-factory", kwargs))
            if not clients:
                raise AssertionError("unexpected extra SDK client construction")
            return clients.pop(0)

        class Tracker:
            def track(self, response, metadata):
                trackers.append((response, metadata))
                events.append(("tracker", response))

        def write_trace(event, **fields):
            traces.append((event, fields))
            events.append(("trace", event, fields))

        def observer_factory(**kwargs):
            return make_legacy_receipt_observer(
                **kwargs,
                tracker_getter=lambda: Tracker(),
                trace_gate=lambda: True,
                trace_writer=write_trace,
            )

        namespace = {
            "GameLLMTerminalError": GameLLMTerminalError,
            "llm": llm,
            "make_legacy_receipt_observer": observer_factory,
            "USAGE_TRACKING_AVAILABLE": usage_enabled,
            "json": json,
            "debug": lambda *args, **kwargs: None,
            "info": lambda *args, **kwargs: None,
            "_get_fallback_starting_location": lambda data: ("F1", "Fallback", "FA", "Fallback Area"),
        }
        node = _selected_function()
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                     "<actual-starting-location-function>", "exec"), namespace)
        real_call = llm.call

        def routed_call(*args, **kwargs):
            value = real_call(*args, **kwargs)
            facade_results.append(value)
            return value

        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", side_effect=create_client):
                with mock.patch.object(factory, "handle_provider_error", return_value={"should_fallback": True}):
                    with mock.patch.object(llm, "call", side_effect=routed_call) as facade_call:
                        result = namespace["_ai_analyze_starting_location"](
                            {"areas": {"A1": {"areaName": "Reach", "locations": [{"locationId": "L1", "name": "Gate"}]}}}
                        )
        return result, events, trackers, traces, facade_call.call_args.kwargs, facade_results[0]

    def test_valid_and_fenced_json_return_the_legacy_tuple_and_explicit_facade_contract(self):
        for content in (
            '{"locationId":"L1","locationName":"Gate","areaId":"A1","areaName":"Reach"}',
            '```json\n{"locationId":"L1","locationName":"Gate","areaId":"A1","areaName":"Reach"}\n```',
        ):
            with self.subTest(content=content):
                result, events, trackers, traces, facade_args, facade_text = self._execute([(_response(content), None)])
                self.assertEqual(result, ("L1", "Gate", "A1", "Reach"))
                self.assertIsInstance(facade_text, str)
                self.assertEqual(facade_args["task"], "dm_validation")
                self.assertIs(facade_args["json_output"], False)
                self.assertEqual(facade_args["temperature"], 0.1)
                for forbidden in ("model", "timeout", "client", "use_fallback", "empty_retry_limit"):
                    self.assertNotIn(forbidden, facade_args)
                request = next(event[1] for event in events if event[0] == "sdk-call")
                self.assertEqual(len(request["messages"]), 2)
                self.assertEqual([message["role"] for message in request["messages"]], ["system", "user"])
                self.assertNotIn("timeout", request)
                self.assertNotIn("client", request)
                self.assertEqual(len(trackers), 1)
                self.assertEqual(len(traces), 1)
                callback_names = [event[0] for event in events if event[0] in ("trace", "tracker")]
                self.assertEqual(callback_names, ["trace", "tracker"])
                self.assertEqual(traces[0][1]["site"], "starting_location_analysis")
                self.assertEqual(traces[0][1]["cost_usd"], 0.0)
                self.assertEqual(traces[0][1]["purpose"], "starting_location_analysis")

    def test_malformed_json_preserves_nonterminal_fallback_tuple(self):
        result, events, trackers, traces, _, _ = self._execute([(_response("not json"), None)])
        self.assertEqual(result, ("F1", "Fallback", "FA", "Fallback Area"))
        self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
        self.assertEqual(len(trackers), 1)
        self.assertEqual(len(traces), 1)

    def test_transient_failure_uses_router_fallback_once_and_receipts_once_per_sdk_attempt(self):
        result, events, trackers, traces, _, _ = self._execute([
            (None, RuntimeError("temporary transport failure")),
            (_response('{"locationId":"L1","locationName":"Gate","areaId":"A1","areaName":"Reach"}'), None),
        ])
        self.assertEqual(result, ("L1", "Gate", "A1", "Reach"))
        self.assertEqual([event[1] for event in events if event[0] == "client-factory"], [{}, {"use_fallback": True}])
        self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 2)
        self.assertEqual(len(trackers), 1)
        self.assertEqual([event[1]["outcome"] for event in traces], ["transport_error", "response"])
        self.assertEqual(len({event[1]["call_id"] for event in traces}), 1)

    def test_terminal_quota_escapes_before_fallback_or_location_tuple(self):
        terminal_cases = (
            ("quota", None, RuntimeError("insufficient_quota")),
            ("refusal", {
                "choices": [{"message": {"content": "ignored", "refusal": "blocked"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "cost": 0.0},
            }, None),
            ("content_filter", {
                "choices": [{"message": {"content": "ignored", "refusal": None}, "finish_reason": "content_filter"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "cost": 0.0},
            }, None),
        )
        for terminal_kind, response, failure in terminal_cases:
            with self.subTest(terminal_kind=terminal_kind):
                events = []
                terminal_sdk = _FakeSDK(events, response=response, failure=failure)
                fallback_calls = []
                tracks = []
                traces = []
                namespace = {
                    "GameLLMTerminalError": GameLLMTerminalError,
                    "llm": llm,
                    "make_legacy_receipt_observer": lambda **kwargs: make_legacy_receipt_observer(
                        **kwargs,
                        tracker_getter=lambda: SimpleNamespace(track=lambda *args: tracks.append(args)),
                        trace_gate=lambda: True,
                        trace_writer=lambda event, **fields: traces.append((event, fields)),
                    ),
                    "USAGE_TRACKING_AVAILABLE": True,
                    "json": json,
                    "debug": lambda *args, **kwargs: None,
                    "info": lambda *args, **kwargs: None,
                    "_get_fallback_starting_location": lambda data: fallback_calls.append(data) or ("F1", "Fallback", "FA", "Fallback Area"),
                }
                exec(compile(ast.fix_missing_locations(ast.Module(body=[_selected_function()], type_ignores=[])),
                             "<terminal-starting-location-function>", "exec"), namespace)
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
                    with mock.patch.object(factory, "create_chat_client", return_value=terminal_sdk):
                        with self.assertRaises(GameLLMTerminalError) as raised:
                            namespace["_ai_analyze_starting_location"]({"areas": {}})
                self.assertEqual(raised.exception.terminal_kind, terminal_kind)
                self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
                self.assertEqual(fallback_calls, [])
                self.assertEqual(len(tracks), 0 if terminal_kind == "quota" else 1)
                self.assertEqual(len(traces), 1)

    def test_outer_starting_location_caller_rethrows_terminal_before_generic_fallback(self):
        tree = ast.parse((ROOT / "core/ai/action_handler.py").read_text(encoding="utf-8"))
        owner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_module_starting_location")
        start_call = next(node for node in ast.walk(owner) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Name) and node.func.id == "_ai_analyze_starting_location")
        persistence_call = next(node for node in ast.walk(owner) if isinstance(node, ast.Call)
                                and isinstance(node.func, ast.Name) and node.func.id == "safe_json_dump")
        self.assertLess(start_call.lineno, persistence_call.lineno)
        guarded = [node for node in ast.walk(owner) if isinstance(node, ast.Try) and any(
            isinstance(handler.type, ast.Name) and handler.type.id == "GameLLMTerminalError"
            for handler in node.handlers
        )]
        self.assertTrue(guarded, "outer caller must not swallow terminal router outcomes")
        handler_types = [ast.unparse(handler.type) if handler.type else None for handler in guarded[0].handlers]
        self.assertLess(handler_types.index("GameLLMTerminalError"), handler_types.index("Exception"))

    def test_automatic_accounting_remains_active_when_legacy_tracking_is_unavailable(self):
        result, events, trackers, traces, _, _ = self._execute([(_response("bad json"), None)], usage_enabled=False)
        self.assertEqual(result, ("F1", "Fallback", "FA", "Fallback Area"))
        self.assertEqual(trackers, [])
        self.assertEqual(len(self.automatic_tracker.records), 1)
        self.assertEqual(self.automatic_tracker.records[0][1]["task"], "dm_validation")
        self.assertEqual(len(traces), 1)

    def test_process_tripwires_remain_untouched(self):
        _TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
