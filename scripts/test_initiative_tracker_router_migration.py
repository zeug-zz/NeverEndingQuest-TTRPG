# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free whole-function tests for the live initiative tracker facade path."""

import ast
import io
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest import mock

from scripts.core_chat_test_safety import arm_process_tripwires

_TRIPWIRES = arm_process_tripwires()
ROOT = Path(__file__).resolve().parents[1]


def _tracker_function():
    source = (ROOT / "core/combat/initiative_tracker_ai.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "generate_live_initiative_tracker"
    )
    return copy_ast(function)


def copy_ast(node):
    return ast.parse(ast.unparse(node)).body[0]


class _MemoryDebugFile(io.StringIO):
    def __init__(self, storage, mode):
        self.storage = storage
        self.mode = mode
        super().__init__("" if mode == "w" else storage.get("debug/api_captures/initiative_messages_to_api.json", ""))

    def __exit__(self, exc_type, exc, traceback):
        if self.mode == "w":
            self.storage["debug/api_captures/initiative_messages_to_api.json"] = self.getvalue()
        self.close()
        return False


class _FakeSDKClient:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )

    def with_options(self, **kwargs):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.callback(**kwargs)


def _response(content="**Live Initiative Tracker:**\nInstructions stay intact.", *, refusal=None, finish_reason=None):
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7, total_tokens=12),
        cost=0,
    )


class InitiativeTrackerRouterMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from core.combat import initiative_tracker_ai
        from utils.llm_router import GameLLMTerminalError, llm
        from utils.llm_runtime import make_legacy_receipt_observer

        cls.owner_module = initiative_tracker_ai
        cls.GameLLMTerminalError = GameLLMTerminalError
        cls.llm = llm
        cls.make_observer = staticmethod(make_legacy_receipt_observer)

    def setUp(self):
        self.debug_store = {}
        self.events = []
        self.observer_options = []
        self.sdk_clients = []
        self.debug_dumps_enabled = False

        def response_observer_factory(**kwargs):
            self.observer_options.append(kwargs)
            return self.make_observer(
                **kwargs,
                tracker_getter=lambda: SimpleNamespace(
                    track=lambda response, metadata: self.events.append(("tracker", response, metadata))
                ),
                api_logger=lambda *args, **kw: self.events.append(("api", args, kw)),
                trace_gate=lambda: True,
                trace_writer=lambda event, **fields: self.events.append(("trace", event, fields)),
            )

        self.observer_factory = response_observer_factory

        def fake_open(path, mode="r", *args, **kwargs):
            self.assertEqual(str(path), "debug/api_captures/initiative_messages_to_api.json")
            return _MemoryDebugFile(self.debug_store, mode)

        self.namespace = {
            "json": json,
            "re": __import__("re"),
            "logger": SimpleNamespace(
                debug=lambda *args, **kwargs: None,
                warning=lambda *args, **kwargs: None,
                error=lambda *args, **kwargs: self.events.append(("error", args)),
            ),
            "INITIATIVE_TRACKER_PROMPT": self.owner_module.INITIATIVE_TRACKER_PROMPT,
            "extract_recent_combat_messages": self._extract_recent,
            "create_initiative_prompt": self.owner_module.create_initiative_prompt,
            "llm": self.llm,
            "make_legacy_receipt_observer": self.observer_factory,
            "GameLLMTerminalError": self.GameLLMTerminalError,
            "combat_debug_dumps_enabled": lambda: self.debug_dumps_enabled,
            "open": fake_open,
            "print": lambda *args, **kwargs: self.events.append(("print", args)),
        }
        function = _tracker_function()
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "<initiative-tracker-owner>", "exec"), self.namespace)
        self.function = self.namespace["generate_live_initiative_tracker"]

    @staticmethod
    def _extract_recent(conversation, current_round):
        from core.combat import initiative_tracker_ai
        return initiative_tracker_ai.extract_recent_combat_messages(conversation, current_round)

    def _inputs(self):
        encounter = {
            "current_round": 2,
            "creatures": [
                {"name": "Acheron", "type": "player", "initiative": 18, "status": "alive"},
                {"name": "Goblin", "type": "npc", "initiative": 11, "status": "alive"},
            ],
        }
        history = [
            {"role": "system", "content": "filtered system message"},
            {"role": "user", "content": "Round: 2\nThe fighter advances."},
            {"role": "assistant", "content": "The goblin raises its shield."},
        ]
        return encounter, history

    def _invoke_with_sdk(self, outcome):
        from utils import ai_client_factory
        from utils import llm_router

        def fake_client_factory(**kwargs):
            self.events.append(("client-factory", kwargs))
            client = _FakeSDKClient(outcome)
            self.sdk_clients.append(client)
            return client

        with (
            mock.patch.object(ai_client_factory, "_get_actual_provider", return_value=("openai", False)),
            mock.patch.object(ai_client_factory, "create_chat_client", side_effect=fake_client_factory),
            mock.patch.object(ai_client_factory, "handle_provider_error", return_value={"should_fallback": False}),
        ):
            encounter, history = self._inputs()
            result = self.function(encounter, history)
        return result

    def _debug_messages(self):
        return json.loads(self.debug_store["debug/api_captures/initiative_messages_to_api.json"])

    def test_actual_facade_response_preserves_prompt_debug_marker_and_tracks_once(self):
        raw_text = "  **Live Initiative Tracker:**\n\n>>> PROCESS ALL OF THESE IN ONE RESPONSE\n- Goblin\n>>> THEN STOP AT: Acheron  \n"
        self.debug_dumps_enabled = True
        result = self._invoke_with_sdk(lambda **kwargs: _response(raw_text))

        self.assertEqual(result, raw_text.strip())
        self.assertEqual(len(self.sdk_clients), 1)
        self.assertEqual(len(self.sdk_clients[0].calls), 1)
        request = self.sdk_clients[0].calls[0]
        self.assertEqual(request["messages"], [
            {"role": "system", "content": self.owner_module.INITIATIVE_TRACKER_PROMPT},
            {"role": "user", "content": self.owner_module.create_initiative_prompt(
                self.owner_module.extract_recent_combat_messages(self._inputs()[1], 2),
                self._inputs()[0]["creatures"],
                2,
            )},
        ])
        self.assertNotIn("timeout", request)
        self.assertNotIn("api_key", request)
        source_function = _tracker_function()
        facade_call = next(
            call for call in ast.walk(source_function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute) and call.func.attr == "call"
        )
        facade_keywords = {keyword.arg: keyword.value for keyword in facade_call.keywords}
        self.assertEqual(ast.literal_eval(facade_keywords["temperature"]), 0.1)
        self.assertEqual(ast.literal_eval(facade_keywords["task"]), "combat_main")
        self.assertIs(ast.literal_eval(facade_keywords["json_output"]), False)
        self.assertEqual(self.observer_options[0]["legacy_context"], {
            "endpoint": "initiative_tracker",
            "function": "generate_live_initiative_tracker",
            "purpose": "initiative_tracker",
        })
        self.assertEqual(self.observer_options[0]["trace_site"], "initiative_tracker")
        self.assertNotIn("endpoint_name", self.observer_options[0])
        self.assertNotIn("messages", self.observer_options[0])
        self.assertEqual([event[0] for event in self.events if event[0] in ("trace", "tracker", "api")], ["trace", "tracker"])
        self.assertEqual(self.events[[event[0] for event in self.events].index("tracker")][1], {
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12, "cost": 0.0}
        })
        tracker_metadata = self.events[[event[0] for event in self.events].index("tracker")][2]
        self.assertEqual(tracker_metadata["task"], "combat_main")
        self.assertEqual(self._debug_messages(), [
            {"role": "system", "content": self.owner_module.INITIATIVE_TRACKER_PROMPT},
            {"role": "user", "content": self.owner_module.create_initiative_prompt(
                self.owner_module.extract_recent_combat_messages(self._inputs()[1], 2),
                self._inputs()[0]["creatures"],
                2,
            )},
            {"role": "assistant", "content": raw_text},
        ])

    def test_absent_marker_empty_and_malformed_facade_content_return_none_but_keep_actual_debug_text(self):
        self.debug_dumps_enabled = True
        for content in ("Instructions without the required marker", "", ["malformed", "shape"]):
            with self.subTest(content=content):
                self.events.clear()
                self.observer_options.clear()
                self.debug_store.clear()
                self.assertIsNone(self._invoke_with_sdk(lambda **kwargs: _response(content)))
                debug_data = self._debug_messages()
                self.assertEqual(debug_data[-1], {"role": "assistant", "content": content})
                self.assertEqual(len([event for event in self.events if event[0] == "tracker"]), 1)

    def test_terminal_quota_refusal_and_filter_rethrow_once_without_response_debug_append(self):
        self.debug_dumps_enabled = True
        outcomes = [
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("quota exceeded")),
            lambda **kwargs: _response("refused", refusal="safety refusal"),
            lambda **kwargs: _response(None, finish_reason="content_filter"),
        ]
        for outcome_index, outcome in enumerate(outcomes):
            with self.subTest(outcome=outcome):
                self.events.clear()
                self.observer_options.clear()
                self.debug_store.clear()
                with self.assertRaises(self.GameLLMTerminalError):
                    self._invoke_with_sdk(outcome)
                self.assertEqual(len(self.sdk_clients[-1].calls), 1)
                debug_data = self._debug_messages()
                self.assertEqual(len(debug_data), 2)
                expected_tracker_events = 0 if outcome_index == 0 else 1
                self.assertEqual(len([event for event in self.events if event[0] == "tracker"]), expected_tracker_events)

    def test_transport_error_is_ordinary_none_and_emits_no_usage_or_assistant_debug_entry(self):
        self.debug_dumps_enabled = True
        self.events.clear()
        self.debug_store.clear()

        def transport_error(**kwargs):
            raise RuntimeError("transport unavailable")

        self.assertIsNone(self._invoke_with_sdk(transport_error))
        self.assertEqual(len(self.sdk_clients[-1].calls), 1)
        self.assertEqual(len(self._debug_messages()), 2)
        self.assertFalse(any(event[0] == "tracker" for event in self.events))
        self.assertTrue(any(event[0] == "trace" for event in self.events))

    def test_debug_dump_gate_off_skips_file_io(self):
        self.assertIsNotNone(self._invoke_with_sdk(lambda **kwargs: _response()))
        self.assertEqual(self.debug_store, {})

    def test_no_creatures_or_no_history_returns_before_facade_or_observer(self):
        calls = []
        original_llm = self.namespace["llm"]
        self.namespace["llm"] = SimpleNamespace(call=lambda **kwargs: calls.append(kwargs))
        self.assertIsNone(self.function({"creatures": []}, []))
        self.assertIsNone(self.function({"creatures": [{"name": "Acheron"}]}, []))
        self.assertEqual(calls, [])
        self.assertEqual(self.observer_options, [])
        self.namespace["llm"] = original_llm

    def test_factory_credential_construction_failure_is_ordinary_none_with_zero_sdk_attempts(self):
        from utils import ai_client_factory

        with (
            mock.patch.object(ai_client_factory, "_get_actual_provider", return_value=("openai", False)),
            mock.patch.object(ai_client_factory, "create_chat_client", side_effect=RuntimeError("factory credential unavailable")),
            mock.patch.object(ai_client_factory, "handle_provider_error", return_value={"should_fallback": False}),
        ):
            encounter, history = self._inputs()
            self.assertIsNone(self.function(encounter, history))
        self.assertEqual(self.sdk_clients, [])
        self.assertEqual(len(self.observer_options), 1)
        self.assertFalse(any(event[0] == "tracker" for event in self.events))

    def test_source_has_no_direct_constructor_or_openai_credential_gate_and_prompt_guard_rethrows_terminals(self):
        source = (ROOT / "core/combat/initiative_tracker_ai.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "generate_live_initiative_tracker")
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
        self.assertEqual(sum(isinstance(call.func, ast.Name) and call.func.id == "OpenAI" for call in calls), 0)
        self.assertEqual(sum(isinstance(call.func, ast.Attribute) and call.func.attr == "create" for call in calls), 0)
        self.assertFalse(any(isinstance(call.func, ast.Name) and call.func.id == "create_chat_client" for call in calls))
        facade_call = next(call for call in calls if isinstance(call.func, ast.Attribute) and call.func.attr == "call")
        facade_keywords = {keyword.arg for keyword in facade_call.keywords}
        self.assertFalse({"model", "timeout", "client", "fallback_client", "use_fallback"} & facade_keywords)
        self.assertFalse(any(isinstance(node, ast.Name) and node.id in {"OPENAI_API_KEY", "DM_MAIN_MODEL"} for node in ast.walk(function)))
        imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any("openai" in ast.unparse(node) or "OPENAI_API_KEY" in ast.unparse(node) or "DM_MAIN_MODEL" in ast.unparse(node) for node in imports))

        prompt_tree = ast.parse((ROOT / "core/combat/prompts.py").read_text(encoding="utf-8"))
        context_function = next(node for node in prompt_tree.body if isinstance(node, ast.FunctionDef) and node.name == "assemble_combat_context")
        generic_handlers = [handler for node in ast.walk(context_function) if isinstance(node, ast.Try) for handler in node.handlers if handler.type is not None and ast.unparse(handler.type) == "Exception" and "fallback_initiative_tracker" in ast.unparse(node)]
        self.assertEqual(len(generic_handlers), 1)
        self.assertTrue(any(ast.unparse(handler.type) == "Exception" for handler in generic_handlers))
        self.assertIn("GameLLMTerminalError", ast.unparse(generic_handlers[0]))
        self.assertLess(ast.unparse(generic_handlers[0]).index("GameLLMTerminalError"), ast.unparse(generic_handlers[0]).index("logger_debug"))
        _TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
