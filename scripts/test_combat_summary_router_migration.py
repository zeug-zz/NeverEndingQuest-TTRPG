"""Provider-free vertical contracts for the two core combat summaries."""

import json
import ast
import sys
import unittest
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.core_chat_test_safety import (
    arm_process_tripwires,
    install_in_memory_usage_tracker,
)

_TRIPWIRES = arm_process_tripwires()

import utils.ai_client_factory as factory
from utils.llm_router import GameLLMTerminalError, llm
from utils.llm_runtime import make_legacy_receipt_observer
import utils.encoding_utils as encoding_utils

_SOURCE = Path(__file__).resolve().parents[1] / "core/combat/combat_manager.py"
_TREE = ast.parse(_SOURCE.read_text(encoding="utf-8"))
_FUNCTIONS = {
    node.name: node for node in _TREE.body
    if isinstance(node, ast.FunctionDef)
    and node.name in {"summarize_dialogue", "generate_combat_round_summary"}
}


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        self.sdk_options = kwargs
        return self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def response(content, *, refusal=None, finish_reason=None):
    message = {"content": content}
    if refusal is not None:
        message["refusal"] = refusal
    choice = {"message": message}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice], "model": "fake-resolved", "usage": {
        "prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "cost": 0.0,
    }}


class CombatSummaryRouterTests(unittest.TestCase):
    def setUp(self):
        self.automatic_tracker = install_in_memory_usage_tracker(self)
        self.events = []
        self.owner_ns = {
            "json": json, "time": time, "llm": llm,
            "GameLLMTerminalError": GameLLMTerminalError,
            "make_legacy_receipt_observer": make_legacy_receipt_observer,
            "USAGE_TRACKING_AVAILABLE": True, "TEMPERATURE": 0.8,
            "debug": lambda *args, **kwargs: None,
            "warning": lambda *args, **kwargs: None,
            "error": lambda *args, **kwargs: None,
            "info": lambda *args, **kwargs: None,
            "safe_json_load": lambda path: None,
            "safe_write_json": lambda path, value: True,
            "get_current_area_id": lambda: "AREA1",
            "conversation_history_file": "fixture-history",
        }
        selected = ast.Module(body=list(_FUNCTIONS.values()), type_ignores=[])
        exec(compile(ast.fix_missing_locations(selected), str(_SOURCE), "exec"), self.owner_ns)
        self.tracker = SimpleNamespace(track=lambda value, context=None: self.events.append(("tracker", value, context)))
        self.client = None
        self.router_calls = []
        real_call = llm.call
        def recorded_call(*args, **kwargs):
            self.router_calls.append((args, kwargs.copy()))
            return real_call(*args, **kwargs)
        self.router_patch = mock.patch.object(llm, "call", side_effect=recorded_call)
        self.router_patch.start()
        self.addCleanup(self.router_patch.stop)
        self.create_client = mock.patch.object(factory, "create_chat_client", side_effect=self._client)
        self.create_client.start()
        self.addCleanup(self.create_client.stop)
        self.provider = mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False))
        self.provider.start()
        self.addCleanup(self.provider.stop)
        self.owner_ns["make_legacy_receipt_observer"] = self._observer

    def _client(self, **kwargs):
        return self.client

    def _observer(self, **kwargs):
        self.events.append(("observer-options", kwargs.copy()))
        return make_legacy_receipt_observer(
            **kwargs,
            tracker_getter=lambda: self.tracker,
            api_logger=lambda endpoint, messages, raw, metadata=None: self.events.append(
                ("api", endpoint, messages, raw, metadata)
            ),
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: self.events.append(("trace", event, fields)),
        )

    def _dialogue_persistence(self, location):
        area = {"locations": [location]}
        manager = SimpleNamespace(get_area_path=lambda area_id: "fixture-area")
        path_manager_module = SimpleNamespace(ModulePathManager=lambda module: manager)
        self.modules_patch = mock.patch.dict("sys.modules", {"utils.module_path_manager": path_manager_module})
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        values = iter([{"module": "Fixture"}, area])
        self.owner_ns["safe_json_load"] = lambda path: next(values)
        self.owner_ns["safe_write_json"] = lambda path, value: self.events.append(("save", path, value)) or True
        self.owner_ns["get_current_area_id"] = lambda: "AREA1"
        self.modules_patch = mock.patch.dict("sys.modules", {"utils.module_path_manager": SimpleNamespace(ModulePathManager=lambda module: manager)})
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        self.encoding_patch = mock.patch.object(encoding_utils, "safe_json_load", side_effect=lambda path: next(values))
        self.encoding_patch.start()
        self.addCleanup(self.encoding_patch.stop)

    def test_dialogue_summary_full_owner_prompt_parse_receipt_persistence_and_return(self):
        self.client = FakeClient(response('  {"narration":"The last foe fell."}  '))
        location = {"locationId": "LOC1", "encounters": []}
        self._dialogue_persistence(location)
        history = [
            {"role": "system", "content": "omit"},
            {"role": "user", "content": "Advance."},
            {"role": "assistant", "content": ' {"narration":"A strike."} '},
            {"role": "assistant", "content": 'Combat Summary: {"narration":"Old ending."}'},
            {"role": "assistant", "content": "Combat Summary: not-json"},
            {"role": "assistant", "content": "A plain response."},
        ]
        party = {"worldConditions": {"currentLocationId": "LOC1", "activeCombatEncounter": "E-7", "year": "1492", "month": "Mirtul", "day": "4", "time": "noon"}}
        result = self.owner_ns["summarize_dialogue"](history, location, party)
        expected_text = "Player: Advance.\n\nDungeon Master: A strike.\n\nDungeon Master: Old ending.\n\nDungeon Master: Combat Summary: not-json\n\nDungeon Master: A plain response."
        expected_messages = [
            {"role": "system", "content": "Your task is to create a vivid, colorful narrative summary of this combat encounter. Capture the dramatic highs and lows - critical hits, narrow misses, clever tactics, desperate moments, and heroic actions. Write it as an exciting story paragraph that captures the flow and feel of the battle. Include: the initial setup, key turning points, memorable moments, the final blow, total XP awarded, and what remains after combat (defeated foes, environmental changes). Write in past tense as a complete narrative summary, not a play-by-play. Make it engaging and memorable - this will be the permanent record of this battle."},
            {"role": "user", "content": expected_text},
        ]
        self.assertEqual(result, "The last foe fell.")
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0]["messages"], expected_messages)
        self.assertEqual(self.router_calls[0][1]["task"], "combat_summary")
        self.assertEqual(self.router_calls[0][1]["temperature"], 0.8)
        self.assertIs(self.router_calls[0][1]["json_output"], False)
        self.assertEqual(self.client.sdk_options, {"max_retries": 0})
        self.assertNotIn("timeout", self.client.requests[0])
        self.assertNotIn("model", self.router_calls[0][1])
        self.assertNotIn("timeout", self.router_calls[0][1])
        options = next(event[1] for event in self.events if event[0] == "observer-options")
        self.assertEqual((options["endpoint_name"], options["trace_site"]), ("combat_summary", "combat_dialogue_summary"))
        self.assertEqual(options["legacy_context"], {"temperature": 0.8, "context": "dialogue_summary"})
        self.assertTrue(options["track_usage"])
        self.assertTrue(options["api_log_before_tracker"])
        self.assertEqual([event[0] for event in self.events if event[0] in ("trace", "tracker", "api")], ["trace", "api", "tracker"])
        tracker_event = next(event for event in self.events if event[0] == "tracker")
        api_event = next(event for event in self.events if event[0] == "api")
        self.assertEqual(tracker_event[2]["cost_usd"], 0.0)
        self.assertEqual(tracker_event[2]["cost_provenance"], "actual")
        self.assertEqual(api_event[4]["provider_reported_cost_usd"], 0.0)
        self.assertEqual(api_event[4]["cost_provenance"], "actual")
        self.assertEqual(len([event for event in self.events if event[0] == "save"]), 2)
        self.assertEqual([row["role"] for row in history[-2:]], ["assistant", "user"])
        self.assertTrue(history[-2]["content"].startswith("Combat Summary: The last foe fell."))
        self.assertEqual(self.events[-1][1], "fixture-history")

    def test_dialogue_terminal_stops_before_location_history_and_save_mutations(self):
        for kind, raw in (("quota", RuntimeError("insufficient_quota")), ("refusal", response("", refusal="no")), ("content_filter", response("", finish_reason="content_filter"))):
            with self.subTest(kind=kind):
                self.events.clear()
                self.client = FakeClient(raw)
                location = {"locationId": "LOC1", "encounters": []}
                self._dialogue_persistence(location)
                history = [{"role": "user", "content": "fight"}]
                party = {"worldConditions": {"currentLocationId": "LOC1"}}
                with self.assertRaises(GameLLMTerminalError):
                    self.owner_ns["summarize_dialogue"](history, location, party)
                self.assertEqual(location["encounters"], [])
                self.assertEqual(history, [{"role": "user", "content": "fight"}])
                self.assertFalse(any(row[0] == "save" for row in self.events))

    def test_round_summary_real_router_json_parse_receipt_and_observer_gating(self):
        self.client = FakeClient(response('{"round":3,"narrative_highlights":[]}'))
        self.owner_ns["USAGE_TRACKING_AVAILABLE"] = False
        result = self.owner_ns["generate_combat_round_summary"](3, [{"role": "user", "content": "A hit."}])
        self.assertEqual(result, {"round": 3, "narrative_highlights": []})
        request = self.client.requests[0]
        self.assertEqual(self.router_calls[0][1]["task"], "compression")
        self.assertEqual(self.router_calls[0][1]["temperature"], 0.1)
        self.assertIs(self.router_calls[0][1]["json_output"], False)
        self.assertNotIn("response_format", request)
        options = next(event[1] for event in self.events if event[0] == "observer-options")
        self.assertNotIn("endpoint_name", options)
        self.assertEqual(options["trace_site"], "compression")
        self.assertEqual(options["legacy_context"], {"endpoint": "combat_dm", "purpose": "combat_turn_processing"})
        self.assertFalse(options["track_usage"])
        self.assertEqual([event[0] for event in self.events if event[0] in ("trace", "tracker", "api")], ["trace"])
        self.assertEqual(len(self.automatic_tracker.records), 1)
        self.assertEqual(self.automatic_tracker.records[0][1]["task"], "compression")
        trace = next(event[2] for event in self.events if event[0] == "trace")
        self.assertEqual(trace["task"], "compression")
        self.assertEqual(trace["requested_model"], "gpt-6-luna")
        self.assertEqual(trace["resolved_model"], "fake-resolved")
        self.assertNotIn("legacy_context_model", trace)

        self.events.clear()
        self.automatic_tracker.records.clear()
        self.client = FakeClient(response('{"round":3,"narrative_highlights":[]}'))
        self.owner_ns["USAGE_TRACKING_AVAILABLE"] = True
        self.assertEqual(self.owner_ns["generate_combat_round_summary"](3, []), {"round": 3, "narrative_highlights": []})
        self.assertEqual([event[0] for event in self.events if event[0] in ("trace", "tracker", "api")], ["trace", "tracker"])
        self.assertFalse(any(event[0] == "api" for event in self.events))
        self.assertEqual(self.automatic_tracker.records, [])

    def test_round_malformed_json_and_ordinary_error_return_none_but_terminal_propagates(self):
        self.client = FakeClient(response("not-json"))
        self.assertIsNone(self.owner_ns["generate_combat_round_summary"](3, []))
        self.client = FakeClient(RuntimeError("ordinary transport failure"))
        self.assertIsNone(self.owner_ns["generate_combat_round_summary"](3, []))
        for raw in (RuntimeError("insufficient_quota"), response("", refusal="no"), response("", finish_reason="content_filter")):
            self.client = FakeClient(raw)
            with self.assertRaises(GameLLMTerminalError):
                self.owner_ns["generate_combat_round_summary"](3, [])

    def test_dialogue_missing_area_and_usage_gate_keep_legacy_return(self):
        self.client = FakeClient(response(" plain result "))
        location = {"locationId": "OTHER", "encounters": []}
        self._dialogue_persistence(location)
        self.owner_ns["USAGE_TRACKING_AVAILABLE"] = False
        result = self.owner_ns["summarize_dialogue"]([], location, {"worldConditions": {"currentLocationId": "LOC1"}})
        self.assertEqual(result, "plain result")
        options = next(event[1] for event in self.events if event[0] == "observer-options")
        self.assertFalse(options["track_usage"])
        self.assertEqual(len(self.automatic_tracker.records), 1)
        self.assertEqual(self.automatic_tracker.records[0][1]["task"], "combat_summary")
        self.assertFalse(any(row[0] == "save" for row in self.events))
        self.assertEqual(location["encounters"], [])

    def test_dialogue_missing_area_file_returns_summary_without_history_save(self):
        self.client = FakeClient(response("area-missing plain output"))
        self.owner_ns["safe_json_load"] = lambda path: {"module": "Fixture"}
        manager = SimpleNamespace(get_area_path=lambda area_id: "fixture-area")
        self.modules_patch = mock.patch.dict("sys.modules", {"utils.module_path_manager": SimpleNamespace(ModulePathManager=lambda module: manager)})
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        values = iter([{"module": "Fixture"}, None])
        self.encoding_patch = mock.patch.object(encoding_utils, "safe_json_load", side_effect=lambda path: next(values))
        self.encoding_patch.start()
        self.addCleanup(self.encoding_patch.stop)
        location = {"locationId": "LOC1", "encounters": []}
        history = [{"role": "user", "content": "fight"}]
        party = {"worldConditions": {"currentLocationId": "LOC1", "activeCombatEncounter": "E-1", "year": 1, "month": "M", "day": 1, "time": "noon"}}
        result = self.owner_ns["summarize_dialogue"](history, location, party)
        self.assertEqual(result, "area-missing plain output")
        self.assertEqual(len(location["encounters"]), 1)
        self.assertEqual(history, [{"role": "user", "content": "fight"}])
        self.assertFalse(any(row[0] == "save" for row in self.events))


if __name__ == "__main__":
    unittest.main()
