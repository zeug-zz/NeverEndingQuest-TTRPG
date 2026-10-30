# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free tests for the finite transition narration boundary."""

import ast
import copy
import builtins
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest import mock

from scripts.core_chat_test_safety import arm_process_tripwires

_TRIPWIRES = arm_process_tripwires()
ROOT = Path(__file__).resolve().parents[1]

# Import owners only after process-wide SDK, network, and outside-write guards.
import utils.ai_client_factory as factory
from utils.llm_router import GameLLMTerminalError, llm, reset_usage_stats
from utils.llm_runtime import make_legacy_receipt_observer


def _owner():
    tree = ast.parse((ROOT / "core/ai/action_handler.py").read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "process_action")


def _call_name(call):
    node = call.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _narration_try(owner):
    return next(
        node for node in ast.walk(owner)
        if isinstance(node, ast.Try) and any(
            isinstance(item, ast.Call) and _call_name(item) == "llm.call"
            for item in ast.walk(node)
        )
    )


def _finite_transition_nodes(owner):
    """Select the real commit statement and full transition_prompt if branch."""
    for node in ast.walk(owner):
        if not isinstance(node, (ast.FunctionDef, ast.If, ast.Try, ast.For, ast.While, ast.With)):
            continue
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if not isinstance(statements, list):
                continue
            for index, statement in enumerate(statements[:-1]):
                is_commit = isinstance(statement, ast.Assign) and any(
                    isinstance(call, ast.Call)
                    and _call_name(call) == "location_manager.handle_location_transition"
                    for call in ast.walk(statement.value)
                )
                if (is_commit and isinstance(statements[index + 1], ast.If)
                        and ast.unparse(statements[index + 1].test) == "transition_prompt"):
                    return statement, statements[index + 1]
    raise AssertionError("could not select finite commit-to-transition branch")


def _assert_location_manager_commit_precedes_prompt_return(test):
    manager_path = ROOT / "core/managers/location_manager.py"
    tree = ast.parse(manager_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "handle_location_transition")
    writes = [call for call in ast.walk(function) if isinstance(call, ast.Call)
              and _call_name(call) == "safe_json_dump" and len(call.args) > 1
              and ast.literal_eval(call.args[1]) == "party_tracker.json"]
    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    test.assertTrue(writes, "location manager must persist canonical party location")
    test.assertTrue(returns, "location manager must return the transition prompt")
    test.assertLess(min(node.lineno for node in writes), max(node.lineno for node in returns))


class _FakeSDK:
    def __init__(self, events, *, response=None, failure=None):
        self.events = events
        self.response = response
        self.failure = failure
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        self.events.append(("sdk-options", kwargs))
        return self

    def create(self, **kwargs):
        self.events.append(("sdk-call", copy.deepcopy(kwargs)))
        if self.failure is not None:
            raise self.failure
        return self.response


def _response(text):
    return {
        "choices": [{"message": {"content": text}}],
        "model": "fixture-resolved-model",
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "cost": 0.0},
    }


class _UnexpectedFakeDependencyFailure(BaseException):
    """Fatal fake-contract error; production Exception handlers must not hide it."""


class _History(list):
    def __init__(self, events, items):
        self.events = events
        super().__init__(items)

    def append(self, item):
        self.events.append(("history-append", copy.deepcopy(item)))
        super().append(item)


class TransitionRouterMigrationTests(unittest.TestCase):
    def setUp(self):
        reset_usage_stats()

    def tearDown(self):
        reset_usage_stats()

    def _run_transition(self, scripts, *, cross_module=True):
        events, trackers, traces = [], [], []
        history = _History(events, [
            {"role": "user", "content": "prior conversation"},
        ])
        canonical = {"worldConditions": {"currentLocation": "Old Keep", "currentLocationId": "A01"}, "module": "old"}
        followers = {"guide": "A01"}
        clients = [_FakeSDK(events, response=response, failure=failure) for response, failure in scripts]

        def create_client(**kwargs):
            events.append(("client-factory", kwargs))
            if not clients:
                raise _UnexpectedFakeDependencyFailure("unexpected extra SDK client construction")
            return clients.pop(0)

        def observer_factory(**kwargs):
            return make_legacy_receipt_observer(
                **kwargs,
                tracker_getter=lambda: SimpleNamespace(track=lambda *args: (trackers.append(args), events.append(("tracker", args[0])))),
                trace_gate=lambda: True,
                trace_writer=lambda event, **fields: (traces.append((event, fields)), events.append(("trace", event, fields))),
            )

        class LocationOwner:
            def handle_location_transition(self, *args):
                events.append(("location-commit", args))
                canonical["worldConditions"] = {"currentLocation": "Salt Road", "currentLocationId": "B02"}
                return "transition prompt bytes\nwith exact spacing  "

        class CampaignManager:
            def __init__(self):
                events.append(("campaign-manager",))

            def detect_module_transition(self, old_id, new_id):
                events.append(("campaign-detect", old_id, new_id))
                return cross_module, "old", "new"

        follower_module = SimpleNamespace(sync_traveling_followers_to_location=self._sync_followers(events, followers))

        def fake_safe_load(path):
            if path != "party_tracker.json":
                raise _UnexpectedFakeDependencyFailure("unexpected safe_json_load path: " + str(path))
            events.append(("party-load", path))
            return copy.deepcopy(canonical)

        def fake_safe_dump(value, path):
            if path != "party_tracker.json":
                raise _UnexpectedFakeDependencyFailure("unexpected safe_json_dump path: " + str(path))
            events.append(("party-write", path, copy.deepcopy(value)))
            canonical.clear()
            canonical.update(copy.deepcopy(value))

        def save_history(value):
            events.append(("history-save", copy.deepcopy(value)))

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "main":
                return SimpleNamespace(save_conversation_history=save_history)
            if name == "utils.scene_follower_state":
                return follower_module
            if name == "core.managers.campaign_manager":
                return SimpleNamespace(CampaignManager=CampaignManager)
            raise _UnexpectedFakeDependencyFailure("unexpected import during finite transition: " + name)

        namespace = {
            "GameLLMTerminalError": GameLLMTerminalError,
            "llm": llm,
            "make_legacy_receipt_observer": observer_factory,
            "USAGE_TRACKING_AVAILABLE": True,
            "location_manager": LocationOwner(),
            "current_location_name": "Old Keep",
            "current_location_id": "A01",
            "new_location_name_or_id": "B02",
            "current_area_name": "Old Area",
            "current_area_id": "OLD001",
            "auto_area_connectivity_id": None,
            "safe_json_load": fake_safe_load,
            "safe_json_dump": fake_safe_dump,
            "sanitize_text": lambda text: text,
            "transition_messages": None,
            "conversation_history": history,
            "new_location_name": "Salt Road",
            "updated_party_tracker": None,
            "needs_conversation_history_update": False,
            "__name__": "__main__",
            "__builtins__": {**vars(builtins), "__import__": fake_import},
            "sys": SimpleNamespace(path=[]),
            "os": SimpleNamespace(path=SimpleNamespace(dirname=lambda _: "", abspath=lambda _: "")),
            "info": lambda message, **kwargs: events.append(("info", message)),
            "debug": lambda message, **kwargs: events.append(("debug", message)),
            "warning": lambda message, **kwargs: events.append(("warning", message)),
            "error": lambda message, **kwargs: events.append(("error", message)),
            "print": lambda message: events.append(("print", message)),
        }
        selected = _finite_transition_nodes(_owner())
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", side_effect=create_client):
                with mock.patch.object(factory, "handle_provider_error", side_effect=lambda exc, **kwargs: {
                    "should_fallback": "temporary transport failure" in str(exc)
                }):
                    outcome = None
                    try:
                        terminal_return = ast.Return(value=ast.Tuple(elts=[
                            ast.Constant(value="terminal"),
                            ast.Name(id="terminal_error", ctx=ast.Load()),
                            ast.Call(func=ast.Attribute(value=ast.Call(
                                func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[]),
                                attr="get", ctx=ast.Load()),
                                args=[ast.Constant(value="needs_conversation_history_update")], keywords=[]),
                        ], ctx=ast.Load()))
                        success_return = ast.Return(value=ast.Tuple(elts=[
                            ast.Constant(value="success"),
                            ast.Name(id="transition_narration", ctx=ast.Load()),
                            ast.Name(id="needs_conversation_history_update", ctx=ast.Load()),
                        ], ctx=ast.Load()))
                        wrapper = ast.FunctionDef(
                            name="finite_transition", args=ast.arguments(posonlyargs=[], args=[],
                                kwonlyargs=[], kw_defaults=[], defaults=[]),
                            body=[ast.Try(
                                body=copy.deepcopy(list(selected)),
                                handlers=[ast.ExceptHandler(
                                    type=ast.Name(id="GameLLMTerminalError", ctx=ast.Load()),
                                    name="terminal_error", body=[terminal_return],
                                )],
                                orelse=[], finalbody=[],
                            ), success_return], decorator_list=[],
                        )
                        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                                     "<actual-finite-transition-source>", "exec"), namespace)
                        outcome = namespace["finite_transition"]()
                    except GameLLMTerminalError as exc:
                        outcome = exc
        return namespace, events, trackers, traces, history, canonical, followers, outcome

    @staticmethod
    def _sync_followers(events, followers):
        def sync_traveling_followers_to_location(*, old_location_id, new_location_id, reason):
            events.append(("follower-sync", old_location_id, new_location_id, reason))
            for name, location_id in list(followers.items()):
                if location_id == old_location_id:
                    followers[name] = new_location_id
            return {"moved": ["guide"], "skipped": [], "errors": []}
        return sync_traveling_followers_to_location


    def test_real_source_keeps_committed_preboundary_order_and_facade_has_one_request(self):
        owner = _owner()
        boundary = _narration_try(owner)
        calls = [node for node in ast.walk(owner) if isinstance(node, ast.Call)]
        self.assertEqual(sum(_call_name(call) == "llm.call" for call in calls), 1)
        self.assertFalse(any(_call_name(call).endswith("chat.completions.create") for call in calls))
        request = next(call for call in calls if _call_name(call) == "llm.call")
        keywords = {keyword.arg: keyword.value for keyword in request.keywords}
        self.assertEqual(ast.literal_eval(keywords["task"]), "dm_main")
        self.assertIs(ast.literal_eval(keywords["json_output"]), False)
        self.assertEqual(ast.literal_eval(keywords["temperature"]), 0.7)
        for forbidden in ("model", "timeout", "client", "use_fallback", "empty_retry_limit"):
            self.assertNotIn(forbidden, keywords)

        commit = next(node for node in ast.walk(owner) if isinstance(node, ast.Call)
                      and _call_name(node) == "location_manager.handle_location_transition")
        before = [node for node in ast.walk(owner) if isinstance(node, ast.Expr)
                  and isinstance(node.value, ast.Call)
                  and _call_name(node.value) in {"conversation_history.append", "save_conversation_history"}
                  and commit.lineno < node.lineno < boundary.lineno]
        marker = next(node for node in before if _call_name(node.value) == "conversation_history.append")
        marker_save = next(node for node in before if _call_name(node.value) == "save_conversation_history")
        follower = next(node for node in ast.walk(owner) if isinstance(node, ast.Call)
                        and _call_name(node) == "sync_traveling_followers_to_location")
        self.assertLess(commit.lineno, follower.lineno)
        self.assertLess(follower.lineno, marker.lineno)
        self.assertLess(marker.lineno, marker_save.lineno)
        self.assertLess(marker_save.lineno, boundary.lineno)
        self.assertTrue(any(isinstance(handler.type, ast.Name) and handler.type.id == "GameLLMTerminalError"
                            for handler in boundary.handlers))
        _assert_location_manager_commit_precedes_prompt_return(self)

    def test_success_strips_text_preserves_message_and_appends_then_saves(self):
        namespace, events, trackers, traces, history, canonical, followers, outcome = self._run_transition(
            [(_response("  The road opens.  "), None)]
        )
        self.assertEqual(outcome, ("success", "The road opens.", True))
        narration = next(event for event in events if event[0] == "sdk-call")[1]["messages"]
        self.assertEqual(narration, [
            {"role": "system", "content": "You are a skilled Dungeon Master narrating a location transition."},
            {"role": "user", "content": "transition prompt bytes\nwith exact spacing  "},
        ])
        request = next(event[1] for event in events if event[0] == "sdk-call")
        self.assertEqual(request["messages"], narration)
        self.assertNotIn("timeout", request)
        self.assertEqual([entry["role"] for entry in history], ["user", "user", "assistant"])
        self.assertEqual(canonical["worldConditions"]["currentLocationId"], "B02")
        self.assertEqual(followers["guide"], "B02")
        self.assertEqual(len(trackers), 1)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0][1]["site"], "transition_narration")
        self.assertEqual(traces[0][1]["cost_usd"], 0.0)
        self.assertEqual([item[0] for item in events if item[0] in
                          ("location-commit", "party-load", "follower-sync", "history-append",
                           "history-save", "sdk-call", "trace", "tracker", "campaign-manager",
                           "campaign-detect", "party-write", "info")],
                          ["location-commit", "party-load", "follower-sync", "info", "history-append",
                           "history-save", "info", "sdk-call", "trace", "tracker", "info",
                          "history-append", "history-save", "campaign-manager", "campaign-detect",
                           "info", "party-write", "info"])

    def test_terminal_outcomes_make_one_attempt_and_leave_preboundary_history_untouched(self):
        terminal_cases = (
            ("quota", None, RuntimeError("insufficient_quota")),
            ("refusal", {"choices": [{"message": {"content": "ignored", "refusal": "blocked"}, "finish_reason": "stop"}]}, None),
            ("content_filter", {"choices": [{"message": {"content": "ignored"}, "finish_reason": "content_filter"}]}, None),
        )
        for terminal_kind, response, failure in terminal_cases:
            with self.subTest(terminal_kind=terminal_kind):
                namespace, events, trackers, traces, history, canonical, followers, outcome = self._run_transition(
                    [(response, failure)]
                )
                self.assertEqual(outcome[0], "terminal")
                self.assertIsInstance(outcome[1], GameLLMTerminalError)
                self.assertEqual(outcome[1].terminal_kind, terminal_kind)
                self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
                self.assertEqual([event for event in events if event[0] == "client-factory"], [("client-factory", {})])
                self.assertEqual(canonical["worldConditions"], {"currentLocation": "Salt Road", "currentLocationId": "B02"})
                self.assertEqual(followers, {"guide": "B02"})
                self.assertEqual([entry for entry in history if entry["role"] == "user"], [
                    {"role": "user", "content": "prior conversation"},
                    {"role": "user", "content": "Location transition: Old Keep (A01) to Salt Road (B02)"},
                ])
                self.assertEqual(len([event for event in events if event[0] == "history-save"]), 1)
                self.assertEqual(len([event for event in events if event[0] == "history-append"]), 1)
                self.assertFalse(any(event[0] in {"campaign-manager", "campaign-detect", "party-write"}
                                     for event in events))
                self.assertFalse(any(event[0] == "info" and "SUCCESS:" in event[1] for event in events))
                self.assertIsNone(outcome[2], "success-tail state assignment must not execute after terminal narration")
                self.assertEqual(len([event for event in events if event[0] == "history-save"]), 1)
                self.assertEqual(len(trackers), 0 if terminal_kind == "quota" else 1)
                self.assertEqual(len(traces), 1)

    def test_transient_router_fallback_and_nonterminal_owner_fallback_are_preserved(self):
        _, events, trackers, traces, history, canonical, followers, outcome = self._run_transition([
            (None, RuntimeError("temporary transport failure")),
            (_response("  Returned by fallback.  "), None),
        ])
        self.assertEqual(outcome, ("success", "Returned by fallback.", True))
        self.assertEqual([event[1] for event in events if event[0] == "client-factory"], [{}, {"use_fallback": True}])
        self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 2)
        self.assertEqual(len(trackers), 1)
        self.assertEqual([trace[1]["outcome"] for trace in traces], ["transport_error", "response"])
        self.assertEqual(len([event for event in events if event[0] == "history-save"]), 2)
        self.assertEqual(followers["guide"], "B02")

        _, events, trackers, traces, history, canonical, followers, outcome = self._run_transition([
            (None, RuntimeError("unexpected but nonterminal provider failure")),
        ])
        self.assertEqual(outcome, ("success", "The party travels to Salt Road.", True))
        self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
        self.assertEqual(len([event for event in events if event[0] == "client-factory"]), 1)
        self.assertEqual(len(history), 3)
        self.assertEqual(len([event for event in events if event[0] == "history-save"]), 2)
        self.assertEqual(trackers, [])
        self.assertEqual(len(traces), 1)
        self.assertEqual(followers["guide"], "B02")
        self.assertEqual([event[0] for event in events if event[0] in {
            "location-commit", "party-load", "follower-sync", "history-append", "history-save",
            "info", "sdk-call", "trace", "error", "campaign-manager", "campaign-detect",
            "party-write",
        }], [
            "location-commit", "party-load", "follower-sync", "info", "history-append", "history-save",
            "info", "sdk-call", "trace", "error", "history-append", "history-save",
            "campaign-manager", "campaign-detect", "info", "party-write", "info",
        ])

    def test_process_tripwires_remain_untouched(self):
        _TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
