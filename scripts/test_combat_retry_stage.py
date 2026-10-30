# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Provider Retry Stage Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.

Provider-free tests for normal-turn provider, JSON, validation, and retry
handoff behavior.
"""

import builtins
import copy
import importlib
import io
import json
import os
from pathlib import Path
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import ast

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts.test_llm_router import ProviderTripwire
from core.combat.turn import CombatRetryDependencies, CombatRetryInputs, run_combat_provider_retry_stage


class ExternalWriteDenied(BaseException):
    """Fatal sentinel proving tests cannot fall through to a real write."""


def _sdk_result(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class CombatRetryStageTests(unittest.TestCase):
    def setUp(self):
        self.tripwire = ProviderTripwire()
        self.tripwire.__enter__()
        self.addCleanup(lambda: self.tripwire.__exit__(None, None, None))
        self.calls = {
            "provider": [], "validation": [], "integrity": [], "compress": [], "trace": [],
            "status": [], "writes": [], "errors": [], "warnings": [], "debug": [], "usage": [],
        }
        self.replies = []

        def create(**kwargs):
            self.calls["provider"].append(kwargs)
            item = self.replies.pop(0)
            if isinstance(item, Exception):
                raise item
            return _sdk_result(item)

        def llm_call(task, messages, **kwargs):
            call = {"task": task, "messages": messages, **kwargs}
            self.calls["provider"].append(call)
            item = self.replies.pop(0)
            if isinstance(item, Exception):
                raise item
            if kwargs.get("observer") is not None:
                kwargs["observer"](
                    SimpleNamespace(kind="response", call_id="fixture-call", attempt_id=str(len(self.calls["provider"]))),
                    _sdk_result(item),
                )
            return item

        def receipt_observer_factory(**kwargs):
            self.calls.setdefault("observer_options", []).append(kwargs)

            def observe(receipt, response):
                self.calls["trace"].append(("provider", ("combat_main", response)))
                if kwargs["track_usage"]:
                    self.calls["usage"].append(response)

            return observe

        class FakeClient:
            chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def open_fake(path, mode="r", **kwargs):
            self.calls["writes"].append((path, mode))
            return io.StringIO()

        def get_params(role, model, **kwargs):
            return {"model": model, **kwargs}

        self.dependencies = CombatRetryDependencies(
            client=FakeClient(), use_gpt5_models=False,
            gpt5_mini_model="fixture-mini", gpt5_high_reasoning_on_retry=True,
            combat_main_model="fixture-main",
            get_completion_params=get_params, get_temperature=lambda encounter, validation_attempt: 0.2 + validation_attempt * 0.1,
            perf_counter=lambda: 10.0, trace_stage=lambda *args: self.calls["trace"].append(("stage", args)),
            trace_provider_call=lambda *args: self.calls["trace"].append(("provider", args)),
            export_open=open_fake, makedirs=lambda *a, **k: self.calls["writes"].append((a, "mkdir")),
            emit=lambda message: None, debug=lambda *a, **k: self.calls["debug"].append((a, k)),
            warning=lambda *a, **k: self.calls["warnings"].append((a, k)),
            error=lambda *a, **k: self.calls["errors"].append((a, k)),
            usage_tracking_available=True, track_usage=lambda result: self.calls["usage"].append(result),
            is_valid_json=lambda value: _is_json(value), check_multiple_update_encounter=lambda actions: False,
            make_multiple_update_feedback=lambda parsed: "multiple updateEncounter correction",
            validate_combatant_integrity=lambda *a, **k: self.calls["integrity"].append((a, k)) or True,
            validate_combat_response=lambda *a, **k: self.calls["validation"].append((a, k)) or True,
            update_status=lambda message, processing: self.calls["status"].append((message, processing)),
            llm_call=llm_call,
            receipt_observer_factory=receipt_observer_factory,
        )
        self.history = [{"role": "system", "content": "seed"}, {"role": "user", "content": "attack"}]
        self.encounter = {"encounterId": "fixture", "creatures": []}
        self.party = {"partyMembers": ["Acheron"]}
        self.inputs = CombatRetryInputs(
            conversation_history=self.history, initial_conversation_length=2,
            encounter_data=self.encounter, party_tracker_data=self.party,
            multi_pc_manager=None, user_input_text="attack",
        )

    def _run_guarded(self, inputs=None, dependencies=None):
        real_open = builtins.open

        def deny_write(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise ExternalWriteDenied(f"blocked external write: {file}")
            return real_open(file, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=deny_write), \
             patch("os.open", side_effect=ExternalWriteDenied), \
             patch("os.remove", side_effect=ExternalWriteDenied), \
             patch("os.rename", side_effect=ExternalWriteDenied), \
             patch("os.replace", side_effect=ExternalWriteDenied), \
             patch("os.mkdir", side_effect=ExternalWriteDenied), \
             patch("os.makedirs", side_effect=ExternalWriteDenied):
            return run_combat_provider_retry_stage(inputs or self.inputs, dependencies or self.dependencies)

    def test_initial_success_returns_apply_handoff_and_only_one_call(self):
        self.replies = ['{"narration":"The goblin advances.","actions":[]}']
        result = self._run_guarded()
        self.assertTrue(result.valid_response)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.narration, "The goblin advances.")
        self.assertLessEqual(len(self.calls["provider"]), 5)
        self.assertEqual(len(self.calls["provider"]), 1)
        self.assertEqual(self.history, [{"role": "system", "content": "seed"}, {"role": "user", "content": "attack"}])

    def test_invalid_json_feedback_is_local_and_ordered_before_recovery(self):
        self.replies = ["not-json", '{"narration":"recovered","actions":[]}']
        result = self._run_guarded()
        self.assertTrue(result.valid_response)
        self.assertEqual(len(self.calls["provider"]), 2)
        self.assertEqual(self.calls["provider"][0]["messages"][-1]["content"], "attack")
        self.assertIn("not a valid JSON object", self.calls["provider"][1]["messages"][-1]["content"])
        self.assertEqual(self.calls["validation"][0][0][0], '{"narration":"recovered","actions":[]}')
        self.assertEqual(len(result.validation_attempts), 1)
        self.assertEqual(result.validation_attempts[0]["error_type"], "json_format")
        self.assertEqual(self.history[-1]["content"], "attack")

    def test_validation_feedback_precedes_next_provider_attempt(self):
        self.replies = ['{"narration":"first","actions":[]}', '{"narration":"second","actions":[]}']
        outcomes = iter(["correct the turn", True])
        self.dependencies = replace(
            self.dependencies,
            validate_combat_response=lambda *a, **k: self.calls["validation"].append((a, k)) or next(outcomes),
        )
        result = self._run_guarded()
        self.assertTrue(result.valid_response)
        self.assertIn("correct the turn", self.calls["provider"][1]["messages"][-1]["content"])
        self.assertEqual(result.validation_attempts[0]["error_type"], "combat_logic")
        self.assertEqual(self.history, [{"role": "system", "content": "seed"}, {"role": "user", "content": "attack"}])

    def test_five_attempt_exhaustion_is_bounded_and_error_retries_continue(self):
        self.replies = [RuntimeError("fixture provider failure") for _ in range(5)]
        result = self._run_guarded()
        self.assertLessEqual(len(self.calls["provider"]), 5)
        self.assertLessEqual(len(self.calls["errors"]), 5)
        self.assertEqual(
            [
                (call[0][0], str(call[1]["exception"]))
                for call in self.calls["errors"]
            ],
            [
                (f"FAILURE: Failed to get or validate AI response (Attempt {attempt}/5)", "fixture provider failure")
                for attempt in range(1, 6)
            ],
        )
        self.assertEqual(len(self.calls["validation"]), 0)
        self.assertFalse(result.valid_response)
        self.assertTrue(self.calls["warnings"])

    def test_typed_terminal_errors_escape_without_semantic_retry_or_validation(self):
        from utils.llm_router import GameLLMTerminalError

        for terminal_kind in ("quota", "refusal", "content_filter"):
            with self.subTest(terminal_kind=terminal_kind):
                self.calls["writes"].clear()
                self.calls["validation"].clear()
                calls = []
                dependencies = replace(
                    self.dependencies,
                    llm_call=lambda *args, **kwargs: calls.append((args, kwargs)) or (_ for _ in ()).throw(
                        GameLLMTerminalError(terminal_kind)
                    ),
                )
                with self.assertRaises(GameLLMTerminalError):
                    self._run_guarded(dependencies=dependencies)
                self.assertEqual(len(calls), 1)
                self.assertEqual(self.calls["validation"], [])
                self.assertFalse(any(path == "debug/debug_ai_response.json" for path, _ in self.calls["writes"]))

    def test_gpt5_high_reasoning_escalates_after_first_attempt(self):
        self.dependencies = replace(self.dependencies, use_gpt5_models=True)
        self.replies = ["bad-json", '{"narration":"still bad","actions":[]}', '{"narration":"ok","actions":[]}']
        outcomes = iter(["retry again", True])
        self.dependencies = replace(self.dependencies, validate_combat_response=lambda *a, **k: next(outcomes))
        result = self._run_guarded()
        self.assertTrue(result.valid_response)
        self.assertLessEqual(len(self.calls["provider"]), 5)
        self.assertEqual(len(self.calls["provider"]), 3)
        self.assertNotIn("retry_tier", self.calls["provider"][0])
        self.assertEqual(self.calls["provider"][1]["retry_tier"], "high")
        self.assertEqual(self.calls["provider"][2]["retry_tier"], "high")
        self.assertNotIn("timeout", self.calls["provider"][0])

    def test_incoming_diagnostic_temperature_survives_gpt_json_and_validation_retries(self):
        self.dependencies = replace(self.dependencies, use_gpt5_models=True)
        self.inputs = replace(self.inputs, diagnostic_temperature=0.63)
        self.replies = [
            "not-json",
            '{"narration":"rejected","actions":[]}',
            '{"narration":"accepted","actions":[]}',
        ]
        outcomes = iter(["validation rejection", True])
        self.dependencies = replace(
            self.dependencies,
            validate_combat_response=lambda *a, **k: next(outcomes),
        )
        result = self._run_guarded()
        self.assertTrue(result.valid_response)
        self.assertEqual(result.temperature_used, 0.63)
        self.assertEqual(
            [attempt["temperature_used"] for attempt in result.validation_attempts],
            [0.63, 0.63],
        )
        for call in self.calls["provider"]:
            self.assertNotIn("temperature", call)
            self.assertNotIn("temperature_override", call)
            self.assertNotIn("top_p", call)
            self.assertNotIn("frequency_penalty", call)
            self.assertNotIn("presence_penalty", call)

    def test_legacy_recomputes_temperature_and_next_stage_hands_off_diagnostic(self):
        temperatures = iter([0.71, 0.61])
        outcomes = iter(["retry legacy turn", True])
        self.dependencies = replace(
            self.dependencies,
            get_temperature=lambda encounter, validation_attempt: next(temperatures),
            validate_combat_response=lambda *a, **k: next(outcomes),
        )
        self.replies = [
            '{"narration":"legacy one","actions":[]}',
            '{"narration":"legacy two","actions":[]}',
        ]
        first_result = self._run_guarded()
        self.assertTrue(first_result.valid_response)
        self.assertEqual(first_result.temperature_used, 0.61)
        self.assertEqual(
            [attempt["temperature_used"] for attempt in first_result.validation_attempts],
            [0.71],
        )
        self.assertEqual(
            [call["temperature"] for call in self.calls["provider"]],
            [0.71, 0.61],
        )

        next_inputs = replace(self.inputs, diagnostic_temperature=first_result.temperature_used)
        next_deps = replace(
            self.dependencies,
            use_gpt5_models=True,
            validate_combat_response=lambda *a, **k: True,
        )
        self.replies = ['{"narration":"next turn","actions":[]}']
        second_result = self._run_guarded(next_inputs, next_deps)
        self.assertTrue(second_result.valid_response)
        self.assertEqual(second_result.temperature_used, 0.61)
        self.assertNotIn("temperature_override", self.calls["provider"][-1])
        self.assertNotIn("temperature", self.calls["provider"][-1])

    def test_routed_legacy_branch_keeps_temperature_without_caller_timeout(self):
        self.replies = ['{"narration":"ok","actions":[]}']
        self._run_guarded()
        call = self.calls["provider"][0]
        self.assertEqual(call["task"], "combat_main")
        self.assertIs(call["json_output"], False)
        self.assertEqual(call["temperature"], 0.2)
        self.assertNotIn("timeout", call)
        self.assertNotIn("model", call)
        self.assertEqual(len(self.calls["observer_options"]), 1)

    def test_trace_status_compression_and_write_intents_are_injected(self):
        self.replies = ['{"narration":"ok","actions":[]}']
        self._run_guarded()
        self.assertEqual(self.calls["compress"], [])
        self.assertIn(("stage", ("prompt_prep", 10.0)), self.calls["trace"])
        self.assertTrue(any(event[0] == "provider" for event in self.calls["trace"]))
        self.assertEqual(self.calls["writes"], [])
        self.assertTrue(any(message == "Combat AI processing your action..." for message, _ in self.calls["status"]))
        self.assertTrue(any(message == "Validating combat actions..." for message, _ in self.calls["status"]))
        self.assertEqual(len(self.calls["usage"]), 1)

    def test_legacy_owner_dependency_builder_resolves_current_patch_bindings(self):
        bootstrap_client = SimpleNamespace()
        patched_client = SimpleNamespace()
        real_open = builtins.open

        def deny_write(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise ExternalWriteDenied(f"blocked import-time write: {file}")
            return real_open(file, mode, *args, **kwargs)

        with patch("utils.ai_client_factory.create_chat_client", return_value=bootstrap_client), \
             patch("os.makedirs", return_value=None), \
             patch("builtins.open", side_effect=deny_write):
            owner = importlib.import_module("core.combat.combat_manager")
        with patch.object(owner, "client", patched_client), \
             patch.object(owner, "get_chat_completion_params", return_value={"model": "patched-model"}) as params:
            dependencies = owner._build_combat_retry_dependencies()
        self.assertIsNot(dependencies.client, bootstrap_client)
        self.assertIs(dependencies.client, patched_client)
        self.assertFalse(hasattr(dependencies, "compressor"))
        self.assertIs(dependencies.get_completion_params, params)
        self.assertTrue(callable(dependencies.llm_call))
        self.assertTrue(callable(dependencies.receipt_observer_factory))

    def test_owner_passes_diagnostic_temperature_and_keeps_initial_retry_owner(self):
        source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        bootstrap_source = Path("core/combat/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("temperature_used: Optional[float] = None", source)
        self.assertIn("diagnostic_temperature=temperature_used", source)
        self.assertIn("max_retries = 3", bootstrap_source)
        self.assertIn("validate_response(\n                initial_response,", bootstrap_source)
        self.assertIn("run_startup_narrative(", source)
        self.assertIn("run_combat_provider_retry_stage(", source)

    def test_real_router_and_receipt_adapter_drive_actual_retry_stage(self):
        import utils.ai_client_factory as factory
        import utils.llm_router as router_module
        from utils.llm_runtime import make_legacy_receipt_observer

        def response(content, *, refusal=None, finish_reason="stop"):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=content, refusal=refusal),
                    finish_reason=finish_reason,
                )],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

        class SDKClient:
            def __init__(self, script, sdk_events):
                self.script = script
                self.sdk_events = sdk_events
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def with_options(self, **kwargs):
                self.sdk_events.append(("client_options", kwargs))
                return self

            def create(self, **kwargs):
                self.sdk_events.append(("sdk", kwargs))
                item = self.script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        def run_vertical(script, *, gpt5=False, high_retry=True, temperature=0.27,
                         validation_results=None, inputs=None):
            sdk_events, receipt_events, facade_calls = [], [], []
            client = SDKClient(list(script), sdk_events)

            def tracker_getter():
                return SimpleNamespace(track=lambda raw, metadata: receipt_events.append(("tracker", raw, metadata)))

            def trace_writer(event, **fields):
                receipt_events.append(("trace", event, fields))

            def observer_factory(**kwargs):
                return make_legacy_receipt_observer(
                    trace_site=kwargs.get("trace_site"),
                    legacy_context=kwargs.get("legacy_context"),
                    track_usage=kwargs.get("track_usage", True),
                    trace_gate=lambda: True,
                    trace_writer=trace_writer,
                    tracker_getter=tracker_getter,
                )

            real_call = router_module.llm.call

            def actual_llm_call(task, messages, **kwargs):
                facade_calls.append({"task": task, "messages": copy.deepcopy(messages), **kwargs})
                return real_call(task, messages, **kwargs)

            outcomes = iter(validation_results or [True] * 5)
            dependencies = replace(
                self.dependencies,
                use_gpt5_models=gpt5,
                gpt5_high_reasoning_on_retry=high_retry,
                get_temperature=lambda encounter, validation_attempt: temperature + validation_attempt * 0.1,
                llm_call=actual_llm_call,
                receipt_observer_factory=observer_factory,
                validate_combat_response=lambda *args, **kwargs: next(outcomes),
            )
            with patch.object(factory, "create_chat_client", return_value=client) as make_client:
                result = self._run_guarded(inputs=inputs, dependencies=dependencies)
            return result, sdk_events, receipt_events, facade_calls, make_client

        valid = '{"narration":"The goblin advances.","actions":[]}'
        result, sdk_events, receipt_events, facade_calls, make_client = run_vertical(
            [response("  " + valid + "  ")],
        )
        self.assertTrue(result.valid_response)
        self.assertEqual(result.ai_response, valid)
        self.assertEqual([call["task"] for call in facade_calls], ["combat_main"])
        self.assertIs(facade_calls[0]["json_output"], False)
        self.assertEqual(facade_calls[0]["temperature"], 0.27)
        self.assertNotIn("timeout", facade_calls[0])
        self.assertEqual(len([event for event in sdk_events if event[0] == "sdk"]), 1)
        self.assertEqual(make_client.call_count, 1)
        self.assertTrue(all(call.kwargs == {} for call in make_client.call_args_list))
        self.assertEqual(make_client.call_args_list[0].args, ())
        self.assertEqual(make_client.call_args_list[0].kwargs, {})
        self.assertEqual(next(event[1] for event in sdk_events if event[0] == "client_options"), {"max_retries": 0})
        self.assertNotIn("timeout", next(event[1] for event in sdk_events if event[0] == "sdk"))
        self.assertEqual([event[0] for event in receipt_events], ["trace", "tracker"])
        self.assertEqual(receipt_events[0][2]["retry_tier"], None)
        self.assertEqual(len([event for event in receipt_events if event[0] == "tracker"]), 1)

        result, sdk_events, receipt_events, facade_calls, _ = run_vertical(
            [response("not-json"), response(valid)],
        )
        self.assertTrue(result.valid_response)
        self.assertEqual(len([event for event in sdk_events if event[0] == "sdk"]), 2)
        self.assertEqual(len(receipt_events), 4)
        self.assertIn("not a valid JSON object", facade_calls[1]["messages"][-1]["content"])

        result, sdk_events, receipt_events, facade_calls, _ = run_vertical(
            [response(valid), response(valid)], gpt5=True,
            validation_results=["retry after semantic validation", True],
        )
        self.assertTrue(result.valid_response)
        self.assertNotIn("temperature", facade_calls[0])
        self.assertNotIn("retry_tier", facade_calls[0])
        self.assertEqual(facade_calls[1]["retry_tier"], "high")
        self.assertNotIn("temperature", facade_calls[1])
        self.assertEqual(len([event for event in sdk_events if event[0] == "sdk"]), 2)
        self.assertEqual(len([event for event in receipt_events if event[0] == "tracker"]), 2)

        result, _, _, facade_calls, _ = run_vertical(
            [response(valid), response(valid)], gpt5=True, high_retry=False,
            validation_results=["retry with unchanged tier", True],
        )
        self.assertTrue(result.valid_response)
        self.assertTrue(all("retry_tier" not in call and "temperature" not in call for call in facade_calls))

        exhausted_inputs = replace(self.inputs, max_retries=3)
        result, sdk_events, receipt_events, facade_calls, make_client = run_vertical(
            [RuntimeError("nonretryable fixture failure") for _ in range(3)],
            inputs=exhausted_inputs,
        )
        self.assertFalse(result.valid_response)
        self.assertEqual(len(facade_calls), 3)
        self.assertEqual(len([event for event in sdk_events if event[0] == "sdk"]), 3)
        self.assertEqual(len([event for event in receipt_events if event[0] == "trace"]), 3)
        self.assertEqual(make_client.call_count, 3)
        self.assertTrue(all(call.kwargs == {} for call in make_client.call_args_list))

    def test_real_router_terminals_stop_retry_and_late_terminal_cannot_escape_caller_block(self):
        import utils.ai_client_factory as factory
        import utils.llm_router as router_module
        from utils.llm_router import GameLLMTerminalError
        from utils.llm_runtime import make_legacy_receipt_observer

        def response(content, *, refusal=None, finish_reason="stop"):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=content, refusal=refusal),
                    finish_reason=finish_reason,
                )],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        class SDKClient:
            def __init__(self, script, events):
                self.script, self.events = list(script), events
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def with_options(self, **kwargs):
                return self

            def create(self, **kwargs):
                self.events.append(kwargs)
                item = self.script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        valid_candidate = '{"narration":"stale","actions":[{"action":"damage"}]}'
        manager_source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        manager_tree = ast.parse(manager_source)
        owner = next(
            node for node in ast.walk(manager_tree)
            if isinstance(node, ast.FunctionDef)
            and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "run_combat_provider_retry_stage" for call in ast.walk(node))
        )
        coordinator_call = next(
            node for node in ast.walk(owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "run_combat_provider_retry_stage"
        )
        retry_assignment = next(
            node for node in ast.walk(owner)
            if isinstance(node, ast.Assign) and coordinator_call in ast.walk(node.value)
        )
        coordinator_body = next(
            node for node in ast.walk(owner)
            if isinstance(node, ast.If) and ast.unparse(node.test) == "valid_response or ai_response"
        )
        consumed_names = {"valid_response", "ai_response", "parsed_response", "narration", "actions"}
        consuming_assignments = [
            node for node in ast.walk(owner)
            if isinstance(node, ast.Assign)
            and node.lineno > retry_assignment.lineno
            and any(isinstance(target, ast.Name) and target.id in consumed_names for target in node.targets)
            and any(isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                    and value.value.id == "retry_result" for value in ast.walk(node.value))
        ]
        self.assertTrue(consuming_assignments)
        source_calls = []
        for node in ast.walk(owner):
            if not isinstance(node, (ast.Expr, ast.Assign)):
                continue
            calls = [item for item in ast.walk(node) if isinstance(item, ast.Call)]
            names = {item.func.id for item in calls if isinstance(item.func, ast.Name)}
            if (
                "save_json_file" in names and node.lineno > coordinator_body.lineno
                and any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                        and item.func.id == "save_json_file"
                        and item.args and isinstance(item.args[0], ast.Name)
                        and item.args[0].id == "conversation_history_file"
                        for item in calls)
            ):
                source_calls.append(node)
            if "publish_combat_narration" in names:
                source_calls.append(node)
            if "process_combat_action_batch" in names:
                source_calls.append(node)
        # D7 moved the normal-path accepted-response history write into
        # _commit_normal_combat_turn so the manifest is durable before the
        # first character write. This owner now contains only the action,
        # publication, and manifest-missing fallback-save statements; the
        # focused commit tests assert that the relocated write remains single.
        self.assertEqual(len(source_calls), 3)
        protected = [copy.deepcopy(retry_assignment)]
        protected.extend(copy.deepcopy(node) for node in sorted(consuming_assignments, key=lambda item: item.lineno))
        protected.extend(copy.deepcopy(node) for node in sorted([coordinator_body] + source_calls, key=lambda item: item.lineno))

        for kind, sdk_outcome in (
            ("quota", RuntimeError("fixture quota")),
            ("refusal", response(None, refusal="not allowed")),
            ("content_filter", response(None, finish_reason="content_filter")),
        ):
            with self.subTest(terminal=kind):
                source_inputs = copy.deepcopy(self.inputs)
                encounter_before = copy.deepcopy(source_inputs.encounter_data)
                party_before = copy.deepcopy(source_inputs.party_tracker_data)
                sdk_events, observations, admitted = [], [], []

                def forbidden(label):
                    admitted.append(label)
                    raise AssertionError("terminal retry reached caller admission/application: " + label)

                client = SDKClient([sdk_outcome], sdk_events)
                real_call = router_module.llm.call

                def actual_llm_call(task, messages, **kwargs):
                    return real_call(task, messages, **kwargs)

                def observer_factory(**kwargs):
                    return make_legacy_receipt_observer(
                        trace_site=kwargs.get("trace_site"),
                        trace_gate=lambda: True,
                        trace_writer=lambda event, **fields: observations.append(("trace", event, fields)),
                        tracker_getter=lambda: SimpleNamespace(
                            track=lambda raw, metadata: observations.append(("tracker", raw, metadata))
                        ),
                        track_usage=True,
                    )

                dependencies = replace(
                    self.dependencies,
                    llm_call=actual_llm_call,
                    receipt_observer_factory=observer_factory,
                )
                coordinator_code = ast.Module(body=protected, type_ignores=[])
                namespace = {
                    "run_combat_provider_retry_stage": run_combat_provider_retry_stage,
                    "CombatRetryInputs": CombatRetryInputs,
                    "_build_combat_retry_dependencies": lambda: dependencies,
                    "conversation_history": copy.deepcopy(source_inputs.conversation_history),
                    "encounter_data": source_inputs.encounter_data,
                    "party_tracker_data": source_inputs.party_tracker_data,
                    "multi_pc_manager": None,
                    "user_input_text": source_inputs.user_input_text,
                    "temperature_used": None,
                    "len": len,
                    "session": SimpleNamespace(bind_history=lambda value: forbidden("history")),
                    "initial_conversation_length": len(source_inputs.conversation_history),
                    "validation_attempts": [],
                    "process_combat_action_batch": lambda *a, **k: forbidden("action_batch"),
                    "save_json_file": lambda *a, **k: forbidden("save"),
                    "publish_combat_narration": lambda *a, **k: forbidden("narration"),
                    "trace_combat_observation": lambda *a, **k: None,
                    "capture_pre_round_transition_combat_context": lambda *a, **k: None,
                    "g3_logical_turn": 0,
                    "conversation_history_file": "fixture-history.json",
                    "encounter_id": "fixture-encounter",
                    "final_character_updates": {},
                    "is_combat_ending": False,
                    "CombatActionDependencies": lambda **kwargs: kwargs,
                    "_queue_final_character_update": lambda *a, **k: None,
                    "update_encounter": SimpleNamespace(update_encounter=lambda *a, **k: None),
                    "normalize_encounter_status": lambda *a, **k: None,
                    "info": lambda *a, **k: None,
                    "debug": lambda *a, **k: None,
                    "error": lambda *a, **k: None,
                    "warning": lambda *a, **k: None,
                    "calculate_xp": lambda *a, **k: None,
                    "MULTI_PC_COMBAT_AVAILABLE": False,
                    "emit_combat_event": lambda *a, **k: None,
                    "check_all_monsters_defeated": lambda *a, **k: None,
                    "PCStatus": SimpleNamespace(ACTED="acted"),
                    "CombatantType": SimpleNamespace(NPC="npc", PC="pc"),
                    "print": lambda *a, **k: None,
                    "sys": SimpleNamespace(stdout=SimpleNamespace(flush=lambda: None)),
                }
                with patch.object(factory, "create_chat_client", return_value=client) as make_client:
                    caught = None
                    try:
                        exec(compile(ast.fix_missing_locations(coordinator_code), "<finite-combat-coordinator>", "exec"), namespace)
                    except GameLLMTerminalError as exc:
                        caught = exc
                self.assertIsNotNone(caught, "terminal did not interrupt the actual coordinator before its admission block")
                self.assertEqual(caught.terminal_kind, kind)
                self.assertEqual(len(sdk_events), 1)
                self.assertEqual(make_client.call_count, 1)
                self.assertEqual([event[0] for event in observations], ["trace"] if kind == "quota" else ["trace", "tracker"])
                self.assertEqual(admitted, [])
                self.assertEqual(source_inputs.encounter_data, encounter_before)
                self.assertEqual(source_inputs.party_tracker_data, party_before)

        # A previously parsed but semantically rejected candidate is followed by
        # a terminal quota SDK error: only those two SDK invocations are allowed.
        late_events = []
        client = SDKClient([response(valid_candidate), RuntimeError("fixture quota")], late_events)
        dependencies = replace(
            self.dependencies,
            validate_combat_response=lambda *args, **kwargs: "retry candidate",
        )
        dependencies = replace(
            dependencies,
            llm_call=lambda task, messages, **kwargs: router_module.llm.call(task, messages, **kwargs),
            receipt_observer_factory=lambda **kwargs: make_legacy_receipt_observer(
                trace_site="combat_main",
                trace_gate=lambda: True,
                trace_writer=lambda event, **fields: observations.append(("trace", event, fields)),
                tracker_getter=lambda: SimpleNamespace(
                    track=lambda raw, metadata: observations.append(("tracker", raw, metadata))
                ),
                track_usage=True,
            ),
        )
        observations = []
        with patch.object(factory, "create_chat_client", return_value=client):
            with self.assertRaises(GameLLMTerminalError):
                self._run_guarded(inputs=replace(self.inputs, max_retries=3), dependencies=dependencies)
        self.assertEqual(len(late_events), 2)
        self.assertEqual([event[0] for event in observations], ["trace", "tracker", "trace"])

        callback_events, callback_observations = [], []
        callback_client = SDKClient([response(valid_candidate)], callback_events)
        callback_dependencies = replace(
            self.dependencies,
            validate_combat_response=lambda *args, **kwargs: (_ for _ in ()).throw(
                GameLLMTerminalError("refusal")
            ),
            llm_call=lambda task, messages, **kwargs: router_module.llm.call(task, messages, **kwargs),
            receipt_observer_factory=lambda **kwargs: make_legacy_receipt_observer(
                trace_site="combat_main",
                trace_gate=lambda: True,
                trace_writer=lambda event, **fields: callback_observations.append(("trace", event, fields)),
                tracker_getter=lambda: SimpleNamespace(
                    track=lambda raw, metadata: callback_observations.append(("tracker", raw, metadata))
                ),
                track_usage=True,
            ),
        )
        with patch.object(factory, "create_chat_client", return_value=callback_client):
            with self.assertRaises(GameLLMTerminalError):
                self._run_guarded(dependencies=callback_dependencies)
        self.assertEqual(len(callback_events), 1)
        self.assertEqual([event[0] for event in callback_observations], ["trace", "tracker"])

    def test_real_facade_actual_validator_and_retry_caller_block_terminal_admission(self):
        import utils.ai_client_factory as factory
        import utils.llm_router as router_module
        from utils.llm_runtime import make_legacy_receipt_observer
        from utils.llm_router import GameLLMTerminalError
        from scripts.test_combat_validation_stage import _dependencies as validation_dependencies
        from core.combat.validation import validate_combat_response

        sdk_events, observer_events, facade_requests, downstream = [], [], [], []

        class SDKClient:
            def __init__(self):
                self.items = [
                    SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(
                            content=(
                                '{"narration":"candidate","actions":['
                                '{"action":"updateEncounter","parameters":{"changes":"fixture"}}]}'
                            )))],
                        model="fixture-model",
                    ),
                    RuntimeError("insufficient_quota"),
                ]
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def with_options(self, **kwargs):
                sdk_events.append(("options", kwargs))
                return self

            def create(self, **kwargs):
                sdk_events.append(("sdk", kwargs))
                item = self.items.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        client = SDKClient()
        tracker = SimpleNamespace(track=lambda raw, metadata: observer_events.append(("usage", raw, metadata)))

        def actual_llm_call(task, messages, **kwargs):
            facade_requests.append({"task": task, "messages": copy.deepcopy(messages), **kwargs})
            return router_module.llm.call(task, messages, **kwargs)

        def observer_factory(**kwargs):
            return make_legacy_receipt_observer(
                **kwargs,
                tracker_getter=lambda: tracker,
                api_logger=lambda *args, **metadata: observer_events.append(("api", args, metadata)),
                trace_gate=lambda: True,
                trace_writer=lambda event, **fields: observer_events.append(("trace", event, fields)),
            )

        validation_deps, _ = validation_dependencies()
        validation_deps = replace(
            validation_deps,
            llm_call=actual_llm_call,
            receipt_observer_factory=observer_factory,
            usage_tracking_available=True,
        )

        def actual_validator(response, encounter, user_input, history, *, multi_pc_manager):
            return validate_combat_response(
                response, encounter, user_input, conversation_history=history,
                multi_pc_manager=multi_pc_manager, dependencies=validation_deps,
            )

        dependencies = replace(
            self.dependencies,
            llm_call=actual_llm_call,
            receipt_observer_factory=observer_factory,
            validate_combat_response=actual_validator,
        )
        original_encounter = copy.deepcopy(self.encounter)
        original_history = copy.deepcopy(self.history)

        def finite_admission_block():
            try:
                result = self._run_guarded(dependencies=dependencies)
            except GameLLMTerminalError:
                raise
            if result.valid_response:
                downstream.append("admitted")
                downstream.append("persisted")

        with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
             patch.object(factory, "create_chat_client", return_value=client):
            with self.assertRaises(GameLLMTerminalError) as caught:
                finite_admission_block()

        self.assertEqual(caught.exception.terminal_kind, "quota")
        self.assertEqual([request["task"] for request in facade_requests], ["combat_main", "combat_validation"])
        self.assertTrue(all(request["json_output"] is False for request in facade_requests))
        self.assertNotIn("timeout", facade_requests[1])
        self.assertEqual(len([event for event in sdk_events if event[0] == "sdk"]), 2)
        self.assertTrue([event[1] for event in sdk_events if event[0] == "options"])
        self.assertTrue(all(event[1] == {"max_retries": 0}
                            for event in sdk_events if event[0] == "options"))
        self.assertTrue(all("timeout" not in event[1]
                            for event in sdk_events if event[0] == "sdk"))
        self.assertEqual(downstream, [])
        self.assertEqual(self.encounter, original_encounter)
        self.assertEqual(self.history, original_history)
        self.assertEqual([event[0] for event in observer_events], ["trace", "usage", "trace"])


def _is_json(value):
    try:
        json.loads(value)
        return True
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    unittest.main(verbosity=2)
