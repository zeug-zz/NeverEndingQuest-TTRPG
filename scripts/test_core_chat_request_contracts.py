# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Execute finite provider-boundary expressions selected from live owner ASTs."""

import ast
import copy
import contextlib
import builtins
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from scripts.core_chat_test_safety import arm_process_tripwires

_TRIPWIRES = arm_process_tripwires()
ROOT = Path(__file__).resolve().parents[1]


def _owner_functions(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _name(call):
    node = call.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _calls(node):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)]


def _boundaries(function):
    names = {
        "request_chat_completion_with_recovery",
        "_startup_provider_call",
        "llm.call",
        "dependencies.llm_call",
    }
    return [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and (
            _name(node).endswith("chat.completions.create")
            or _name(node) in names
        )
    ]


class _FakeClient:
    def __init__(self, name, events, content='{"narration":"fixture output"}', failure=None):
        self.name = name
        self.events = events
        self.content = content
        self.failure = failure
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.events.append((self.name, kwargs))
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class _OfflineUsageTracker:
    """In-memory implementation of the global tracker boundary for tests."""

    def __init__(self):
        self.events = []

    def track(self, response, context=None):
        self.events.append((copy.deepcopy(response), copy.deepcopy(context)))


class _Dependencies:
    def __init__(self, events):
        self.client = _FakeClient("primary", events)
        self.combat_main_model = "fixture-combat-main-model"
        self.api_timeout_seconds = 37
        self.combat_api_timeout_seconds = 37
        self.validation_model = "fixture-validation-model"
        self.completion_params = lambda task, model, **kwargs: _params(events, task, model, **kwargs)
        self.get_completion_params = self.completion_params
        self.export_open = lambda *args, **kwargs: contextlib.nullcontext(io.StringIO())
        self.emit = lambda *args, **kwargs: None
        self.perf_counter = lambda: 1.0
        self.trace_provider_call = lambda *args: events.append(("trace", args))
        self.receipt_observer_factory = lambda **kwargs: None
        self.log_api_call = lambda *args, **kwargs: events.append(("api", args, kwargs))
        self.usage_tracking_available = False
        self.debug_dumps_enabled = lambda: False

        def llm_call(task, messages, **kwargs):
            events.append(("router", {"task": task, "messages": copy.deepcopy(messages), **kwargs}))
            return '{"narration":"fixture output"}'

        self.llm_call = llm_call
        self.receipt_observer_factory = lambda **kwargs: None


def _params(events, task, model, **kwargs):
    events.append(("task", task, model, dict(kwargs)))
    return {"model": model, **kwargs}


def _exec_expression(node, namespace):
    expression = ast.Expression(body=node)
    ast.fix_missing_locations(expression)
    return eval(compile(expression, "<selected-owner-request>", "eval"), namespace)


def _message_digest(messages):
    payload = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unique_request_message_dumps(function):
    """Return distinct message ASTs in first-seen order, ignoring transport shape."""
    result = []
    seen = set()
    for boundary in _boundaries(function):
        values = [keyword.value for keyword in boundary.keywords if keyword.arg == "messages"]
        if not values and _name(boundary) in {"llm.call", "dependencies.llm_call"} and len(boundary.args) > 1:
            values = [boundary.args[1]]
        if not values and _name(boundary) == "_startup_provider_call" and boundary.args:
            values = [boundary.args[0]]
        for value in values:
            canonical = ast.dump(value, include_attributes=False)
            if canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
    return result


def _assembly_digest_for_function(function, target_names):
    """Digest selected assembly statements plus unique request message ASTs."""
    pieces = []
    selected = []
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target_node, ast.Name) and target_node.id in target_names
                for target in targets for target_node in ast.walk(target)
            ):
                selected.append(node)
        elif (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr in ("append", "extend")
            and any(
                isinstance(target_node, ast.Name) and target_node.id in target_names
                for target_node in ast.walk(node.value.func.value)
            )
        ):
            selected.append(node)
    pieces.extend(
        (function.name, ast.dump(node, include_attributes=False))
        for node in sorted(selected, key=lambda item: (item.lineno, item.col_offset))
    )
    pieces.extend(("request-messages", value) for value in _unique_request_message_dumps(function))
    return hashlib.sha256(repr(pieces).encode("utf-8")).hexdigest(), len(pieces)


PROMPT_ASSEMBLY_TARGETS = {
    ("main.py", "generate_arrival_narration"): ("narration_request_messages",),
    ("main.py", "generate_seamless_transition_narration"): (),
    ("main.py", "validate_ai_response"): ("validation_conversation", "validation_messages_to_send"),
    ("main.py", "generate_module_summary"): ("summary_prompt",),
    ("main.py", "get_ai_response"): ("messages_to_send",),
    ("core/combat/bootstrap.py", "_run_resume_narrative"): ("resume_prompt", "messages_to_send"),
    ("core/combat/bootstrap.py", "_run_initial_scene_generation"): ("initial_prompt", "messages_to_send"),
    ("core/combat/turn.py", "run_combat_provider_retry_stage"): ("messages_to_send",),
    ("core/combat/validation.py", "validate_combat_response"): ("validation_conversation",),
    ("core/combat/combat_manager.py", "summarize_dialogue"): ("dialogue_summary_prompt", "clean_conversation"),
    ("core/combat/combat_manager.py", "generate_combat_round_summary"): ("prompt",),
    ("core/combat/initiative_tracker_ai.py", "generate_live_initiative_tracker"): ("api_messages",),
    ("core/ai/action_handler.py", "_ai_analyze_starting_location"): ("system_prompt", "user_prompt"),
    ("core/ai/action_handler.py", "process_action"): ("transition_messages",),
    ("core/ai/action_handler.py", "get_ai_npc_movement_decision"): ("system_prompt", "user_prompt"),
}
PROMPT_ASSEMBLY_HELPERS = {
    ("core/combat/bootstrap.py", "_run_initial_scene_generation"): (("core/combat/bootstrap.py", "_build_initial_scene_prompt"),),
    ("core/combat/turn.py", "run_combat_provider_retry_stage"): (("core/combat/prompts.py", "assemble_combat_context"), ("core/combat/prompts.py", "assemble_combat_prompt")),
    ("core/combat/initiative_tracker_ai.py", "generate_live_initiative_tracker"): (("core/combat/initiative_tracker_ai.py", "create_initiative_prompt"),),
}
PROMPT_HELPER_TARGETS = {
    ("core/combat/prompts.py", "assemble_combat_context"): ("dynamic_state_parts", "user_controlled_parts", "dm_controlled_parts", "enemy_parts", "user_prompt"),
    ("core/combat/prompts.py", "assemble_combat_prompt"): ("prompt",),
}
PROMPT_ASSEMBLY_BASELINES = {
    ("main.py", "generate_arrival_narration"): "9650ca4b181021a39070328def7e2d331e520b0fa465bca6908d38dd2f89fa7e",
    ("main.py", "generate_seamless_transition_narration"): "fc66061146a6be70d8c1e86d36254dd8417d50f5d87035c7e046e190598a459f",
    ("main.py", "validate_ai_response"): "0cec84235d2b4d98572658a58a3fc3b46fa5ca7e1edfe7a08af81779d2a20549",
    ("main.py", "generate_module_summary"): "9e4430f0a45b79ed20270f874a18f2ab12998092498cabcd6c259eed10f3b139",
    ("main.py", "get_ai_response"): "bf523ca98a02930bd5f029e8457d1759f77579020f4a20f5df25b499997ea0d8",
    # Task 3.2: resume prompt history is sent uncompressed.
    ("core/combat/bootstrap.py", "_run_resume_narrative"): "8599645af39894308592f8b25e6dd63d05be3c271be30d54f96394a94b5b3edd",
    # Task 3.2: initial-scene prompt history is sent uncompressed.
    ("core/combat/bootstrap.py", "_run_initial_scene_generation"): "fb8f71add186c806693b2b58f628aebe9c332f4fe9d02a175ff837c70728a49b",
    # Tasks 3.1-3.3: legacy timeout kwargs are removed, history is uncompressed,
    # and per-attempt debug dump I/O is gated.
    ("core/combat/turn.py", "run_combat_provider_retry_stage"): "3197d733d73b14cbbf01fb428aa2f60129c3505d97299861e7607203394f1559",
    ("core/combat/validation.py", "validate_combat_response"): "89cae998836feccb96a14a8adb1e3bb40bcd0d12204f536ef28fd9c611b9ee48",
    ("core/combat/combat_manager.py", "summarize_dialogue"): "17ce65e820abfc829d133d5ae90a0db3ef9fcb61242378973c020f93e27994b4",
    ("core/combat/combat_manager.py", "generate_combat_round_summary"): "7decbcf854b892139d6060d3b53f9c1f717df7f4b3682089c4972c721b521f4a",
    ("core/combat/initiative_tracker_ai.py", "generate_live_initiative_tracker"): "f68aef2f99636ddcf64292d4b13b07ee9b51a75b642a1b2926179a497602a9a6",
    ("core/ai/action_handler.py", "_ai_analyze_starting_location"): "d35bf17e581c9f9a4ae48b95fc7b1f0e86ea2943c84e4583d6aeac4fad4c24e8",
    ("core/ai/action_handler.py", "process_action"): "dcf6ab5ab021b73b44d0f1d77812083140232080dbbce51815d6412a7acf3dec",
    ("core/ai/action_handler.py", "get_ai_npc_movement_decision"): "cdd81c5e06e85c05fb7e9e8e5d98311a3977741bb6da540b1c292c75412d6a3a",
}
PROMPT_ASSET_BASELINES = {
    "prompts/combat/combat_sim_prompt.txt": "148d4211474c9189ec54b43ee5fa39eb505a3d1a8d284d7d42581e25ccc7e54b",
    "prompts/combat/combat_sim_prompt_multipc_compressed.txt": "b31ad6960e340d8b05eb76849f983533044f503eb88cf82714beb6526412647e",
    "prompts/initiative_tracker_compressed.txt": "de4692d2cbaa6d9dbe0cb252a1f5554582888ac0cbfd13dbca3fcec3f21bad1d",
    "prompts/combat/combat_validation_prompt.txt": "ca12e479668a623b124efa7aa1777554e2ef25b169bf34240e6fc797f7eb486a",
    "prompts/combat/combat_validation_prompt_compressed.txt": "18ac9069aea90e5d5225e4f2c40420c051d19ee378387e8a32f2ebe99e9c2dda",
    "prompts/combat/combat_validation_prompt_multipc_compressed.txt": "7f905bd2902bc74780eb4f24705d80645d4c5d229f57fe6dda8d9c4f13f84812",
}


def _prompt_assembly_digest(path, function_name):
    """Hash source AST for prompt assembly, not transport/observer kwargs."""
    functions = _owner_functions(path)
    target_names = set(PROMPT_ASSEMBLY_TARGETS[(path, function_name)])
    pieces = []
    source_functions = [(path, function_name)] + list(PROMPT_ASSEMBLY_HELPERS.get((path, function_name), ()))
    for source_path, name in source_functions:
        helper_functions = _owner_functions(source_path)
        function = helper_functions[name]
        selected_targets = set(PROMPT_HELPER_TARGETS.get((source_path, name), target_names))
        function_digest, node_count = _assembly_digest_for_function(function, selected_targets)
        pieces.append((source_path, name, function_digest, node_count))
    return hashlib.sha256(repr(pieces).encode("utf-8")).hexdigest(), len(pieces)


def _assignment(function, name):
    return next(
        node for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


def _return(function, expression_contains):
    return next(
        node for node in ast.walk(function)
        if isinstance(node, ast.Return) and node.value is not None
        and expression_contains in ast.unparse(node.value)
    )


def _exec_statement(node, namespace):
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "<selected-owner-result>", "exec"), namespace)


def _request_fixture_namespace(events):
    primary = _FakeClient("primary", events)
    fallback = _FakeClient("fallback", events)
    fixture_messages = [
        {"role": "system", "content": "fixture system bytes"},
        {"role": "user", "content": "fixture user bytes"},
    ]
    deps = _Dependencies(events)
    deps.client = primary

    def fake_router_call(task, messages, json_output, observer=None, **kwargs):
        request = {"task": task, "messages": copy.deepcopy(messages), "json_output": json_output, **kwargs}
        events.append(("router", request))
        raw_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"narration":"fixture output"}'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        receipt = SimpleNamespace(kind="response", attempt_id="fake-attempt", call_id="fake-call")
        if observer is not None:
            observer(receipt, raw_response)
        return '{"narration":"fixture output"}'

    namespace = {
        "client": primary,
        "summary_client": primary,
        "fallback_client": fallback,
        "summary_model": "fixture-summary-model",
        "combat_model": "fixture-combat-model",
        "model_name": "fixture-owner-model",
        "actual_model": "fixture-actual-model",
        "selected_model": "fixture-selected-model",
        "gpt5_mini_model": "fixture-mini-model",
        "DM_MAIN_MODEL": "legacy-dm-main-model",
        "DM_VALIDATION_MODEL": "legacy-dm-validation-model",
        "DM_SUMMARIZATION_MODEL": "legacy-summary-model",
        "DM_MINI_MODEL": "legacy-mini-model",
        "GPT5_MINI_MODEL": "fixture-gpt5-mini-model",
        "GPT5_FULL_MODEL": "fixture-gpt5-full-model",
        "COMBAT_DIALOGUE_SUMMARY_MODEL": "legacy-combat-summary-model",
        "TEMPERATURE": 0.7,
        "NARRATOR_API_TIMEOUT_SECONDS": 41,
        "messages": fixture_messages,
        "messages_to_send": fixture_messages,
        "model_tier": "complex",
        "call_options": {},
        "observe_main_attempt": lambda *args: None,
        "validation_conversation": fixture_messages,
        "narration_request_messages": fixture_messages,
        "validation_messages_to_send": fixture_messages,
        "transition_messages": fixture_messages,
        "dialogue_summary_prompt": fixture_messages,
        "api_messages": fixture_messages,
        "system_prompt": "fixture system bytes",
        "user_prompt": "fixture user bytes",
        "arrival_prompt": "fixture arrival prompt bytes",
        "stitching_prompt": "fixture stitching prompt bytes",
        "summary_prompt": "fixture summary prompt bytes",
        "prompt": "fixture round summary prompt bytes",
        "temperature_used": 0.37,
        "result": SimpleNamespace(temperature_used=0.37),
        "dependencies": deps,
        "llm": SimpleNamespace(call=fake_router_call),
        "make_legacy_receipt_observer": lambda **kwargs: None,
        "USAGE_TRACKING_AVAILABLE": True,
        "observer": lambda *args, **kwargs: None,
        "validation_receipt_observer": lambda *args, **kwargs: None,
        "transition_observer": lambda *args, **kwargs: None,
        "get_chat_completion_params": lambda task, model, **kwargs: _params(events, task, model, **kwargs),
        "get_completion_params": lambda task, model, **kwargs: _params(events, task, model, **kwargs),
        "request_chat_completion_with_recovery": __import__(
            "utils.provider_response_recovery", fromlist=["request_chat_completion_with_recovery"]
        ).request_chat_completion_with_recovery,
        "NARRATOR_API_TIMEOUT_SECONDS": 41,
        "config": SimpleNamespace(
            DM_MAIN_MODEL="legacy-dm-main-model",
            DM_MINI_MODEL="legacy-mini-model",
            NPC_INFO_UPDATE_MODEL="legacy-updates-model",
        ),
        "OPENAI_API_KEY": "fake-only",
        "OpenAI": lambda **kwargs: events.append(("fake-openai-constructor", kwargs)) or primary,
        "json": json,
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
    }
    return namespace


class CoreChatSelectedRequestContracts(unittest.TestCase):
    """Each selected expression comes directly from the current owner AST."""

    def test_prompt_digest_ignores_transport_shape_and_equivalent_duplicate_branches(self):
        legacy = ast.parse(
            """def owner():
    messages = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "prompt"}]
    response = client.chat.completions.create(messages=messages, timeout=8)
    response = client.chat.completions.create(messages=messages, model="legacy")
"""
        ).body[0]
        migrated = ast.parse(
            """def owner():
    messages = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "prompt"}]
    response = llm.call(task="dm_main", messages=messages, json_output=False)
    response = dependencies.llm_call(task="dm_main", messages=messages)
"""
        ).body[0]

        legacy_digest, _ = _assembly_digest_for_function(legacy, {"messages"})
        migrated_digest, _ = _assembly_digest_for_function(migrated, {"messages"})
        self.assertEqual(len(_unique_request_message_dumps(legacy)), 1)
        self.assertEqual(len(_unique_request_message_dumps(migrated)), 1)
        self.assertEqual(legacy_digest, migrated_digest)

        distinct_branches = ast.parse(
            """def owner():
    messages = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "prompt"}]
    response = llm.call(task="dm_main", messages=messages)
    response = llm.call(task="dm_main", messages=[{"role": "developer", "content": "prompt"}])
"""
        ).body[0]
        self.assertEqual(len(_unique_request_message_dumps(distinct_branches)), 2)
        self.assertNotEqual(
            legacy_digest,
            _assembly_digest_for_function(distinct_branches, {"messages"})[0],
        )

    def test_validator_provider_loop_preserves_three_nonterminal_attempts_and_terminal_priority(self):
        from utils.llm_router import GameLLMTerminalError

        validator = _owner_functions("main.py")["validate_ai_response"]
        loop = next(
            node for node in validator.body
            if isinstance(node, ast.For)
            and any(_name(call) == "llm.call" for call in _calls(node))
        )
        router_call = next(call for call in _calls(loop) if _name(call) == "llm.call")
        keywords = {item.arg: item.value for item in router_call.keywords}
        self.assertEqual(ast.literal_eval(keywords["task"]), "dm_validation")
        self.assertIs(ast.literal_eval(keywords["json_output"]), False)
        self.assertEqual(ast.literal_eval(keywords["temperature"]), 0.1)
        self.assertNotIn("timeout", keywords)
        observer_factory_call = next(
            call for call in _calls(loop)
            if _name(call) == "make_legacy_receipt_observer"
        )
        observer_keywords = {item.arg: item.value for item in observer_factory_call.keywords}
        self.assertEqual(ast.literal_eval(observer_keywords["trace_site"]), "main_validation")

        for terminal_kind in ("quota", "refusal", "content_filter"):
            calls = []
            actions = ["must remain untouched"]

            def terminal_call(**kwargs):
                calls.append(kwargs)
                raise GameLLMTerminalError(terminal_kind)

            namespace = {
                "llm": SimpleNamespace(call=terminal_call),
                "GameLLMTerminalError": GameLLMTerminalError,
                "make_legacy_receipt_observer": lambda **kwargs: lambda *a: None,
                "USAGE_TRACKING_AVAILABLE": False,
                "validation_messages_to_send": [{"role": "system", "content": "fixed bytes"}],
                "max_validation_retries": 3,
                "actions": actions,
            }
            wrapper = ast.FunctionDef(
                name="run_loop", args=ast.arguments(posonlyargs=[], args=[],
                    kwonlyargs=[], kw_defaults=[], defaults=[]),
                body=[ast.Assign(targets=[ast.Name(id="validation_resolved_model", ctx=ast.Store())], value=ast.Constant(None)), loop],
                decorator_list=[],
            )
            module = ast.Module(body=[wrapper], type_ignores=[])
            exec(compile(ast.fix_missing_locations(module), "<validator-loop>", "exec"), namespace)
            with self.subTest(terminal=terminal_kind):
                with self.assertRaises(GameLLMTerminalError):
                    namespace["run_loop"]()
                self.assertEqual(len(calls), 1)
                self.assertEqual(actions, ["must remain untouched"])

        calls = []

        def malformed_call(**kwargs):
            calls.append(kwargs)
            kwargs["observer"](SimpleNamespace(
                resolved_model="fixture-resolved", kind="response", call_id="c",
                attempt_id=str(len(calls)), attempt_number=len(calls), task="dm_validation",
            ), None)
            return "not-json"

        namespace = {
            "llm": SimpleNamespace(call=malformed_call),
            "GameLLMTerminalError": GameLLMTerminalError,
            "make_legacy_receipt_observer": lambda **kwargs: lambda *a: None,
            "USAGE_TRACKING_AVAILABLE": False,
            "validation_messages_to_send": [{"role": "system", "content": "fixed bytes"}],
            "max_validation_retries": 3,
            "debug": lambda *args, **kwargs: None,
            "parse_json_safely": lambda value: json.loads(value),
            "json": json,
        }
        wrapper = ast.FunctionDef(
            name="run_loop", args=ast.arguments(posonlyargs=[], args=[],
                kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=[ast.Assign(targets=[ast.Name(id="validation_resolved_model", ctx=ast.Store())], value=ast.Constant(None)), loop],
            decorator_list=[],
        )
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), "<validator-nonterminal>", "exec"), namespace)
        namespace["run_loop"]()
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call["messages"] == namespace["validation_messages_to_send"] for call in calls))

    def test_validator_empty_and_invalid_content_retries_then_fails_open(self):
        from utils.llm_router import GameLLMTerminalError

        validator = _owner_functions("main.py")["validate_ai_response"]
        loop = next(
            node for node in validator.body
            if isinstance(node, ast.For)
            and any(_name(call) == "llm.call" for call in _calls(node))
        )
        loop_index = validator.body.index(loop)
        fail_open_tail = copy.deepcopy(validator.body[loop_index + 1 :])
        messages = [{"role": "system", "content": "fixed validator prompt"}]
        response_to_validate = '{"narration":"authoritative response","actions":[]}'

        class ScriptedRouter:
            def __init__(self, response):
                self.response = response
                self.calls = []

            def call(self, **kwargs):
                self.calls.append(kwargs)
                raw_response = SimpleNamespace(content=self.response)
                kwargs["observer"](
                    SimpleNamespace(resolved_model="fixture-resolved-model"),
                    raw_response,
                )
                return self.response

        def run_loop(response):
            router = ScriptedRouter(response)
            receipt_events = []
            warnings = []

            def observer_factory(**kwargs):
                def observe(receipt, raw_response):
                    receipt_events.append((receipt, raw_response))
                return observe

            wrapper = ast.FunctionDef(
                name="run_loop",
                args=ast.arguments(
                    posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id="validation_resolved_model", ctx=ast.Store())],
                        value=ast.Constant(None),
                    ),
                    copy.deepcopy(loop),
                    *fail_open_tail,
                ],
                decorator_list=[],
            )
            namespace = {
                "llm": router,
                "GameLLMTerminalError": GameLLMTerminalError,
                "make_legacy_receipt_observer": observer_factory,
                "USAGE_TRACKING_AVAILABLE": False,
                "validation_messages_to_send": messages,
                "max_validation_retries": 3,
                "response_to_validate": response_to_validate,
                "fixed_response": response_to_validate,
                "primary_response": response_to_validate,
                "structure_message": "Structure valid",
                "user_input": "fixture input",
                "validation_conversation": messages,
                "parse_json_safely": json.loads,
                "json": json,
                "os": SimpleNamespace(makedirs=lambda *args, **kwargs: None),
                "datetime": SimpleNamespace(
                    now=lambda: SimpleNamespace(isoformat=lambda: "fixture-time")
                ),
                "open": lambda *args, **kwargs: contextlib.nullcontext(io.StringIO()),
                "debug": lambda *args, **kwargs: None,
                "warning": lambda message, **kwargs: warnings.append(message),
            }
            module = ast.Module(body=[wrapper], type_ignores=[])
            exec(
                compile(ast.fix_missing_locations(module), "<validator-empty-content>", "exec"),
                namespace,
            )
            result = namespace["run_loop"]()
            return result, router, receipt_events, warnings

        for response in (None, "", "   ", "not-json"):
            with self.subTest(response=response):
                result, router, receipts, warnings = run_loop(response)
                self.assertEqual(result, (True, response_to_validate))
                self.assertEqual(len(router.calls), 3)
                self.assertEqual(len(receipts), 3)
                self.assertTrue(
                    all(call["task"] == "dm_validation" for call in router.calls)
                )
                self.assertTrue(
                    all(call["messages"] is messages for call in router.calls)
                )
                self.assertTrue(
                    all("empty_retry_limit" not in call for call in router.calls)
                )
                self.assertEqual(len(warnings), 1)
                self.assertIn("Assuming primary response is valid", warnings[0])

        valid_response = '{"valid":true,"reason":"fixture accepted"}'
        result, router, receipts, warnings = run_loop(valid_response)
        self.assertEqual(result, (True, response_to_validate))
        self.assertEqual(len(router.calls), 1)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(warnings, [])

    def test_router_accounts_none_dm_validation_content_and_leaves_retry_to_caller(self):
        import utils.ai_client_factory as factory
        import utils.llm_usage_tracker as usage_tracker
        from utils.llm_router import LLMRouter

        raw_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, refusal=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            model="fixture-validator-model",
        )
        sdk_calls = []
        receipts = []

        class FakeSDKClient:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=self.create)
                )

            def with_options(self, **kwargs):
                return self

            def create(self, **kwargs):
                sdk_calls.append(kwargs)
                return raw_response

        router = LLMRouter()
        messages = [{"role": "system", "content": "fixed validator prompt"}]
        offline_tracker = _OfflineUsageTracker()
        tracker_getter = mock.Mock(return_value=offline_tracker)
        with mock.patch.object(usage_tracker, "get_global_tracker", tracker_getter):
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
                with mock.patch.object(factory, "create_chat_client", return_value=FakeSDKClient()):
                    result = router.call(
                        task="dm_validation",
                        messages=messages,
                        json_output=False,
                        temperature=0.1,
                        observer=lambda receipt, raw: receipts.append((receipt, raw)),
                    )

        self.assertIsNone(result)
        self.assertEqual(len(sdk_calls), 1)
        self.assertEqual(sdk_calls[0]["messages"], messages)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0][0].kind, "response")
        self.assertEqual(receipts[0][0].completion_tokens, 2)
        self.assertIs(receipts[0][1], raw_response)
        tracker_getter.assert_called_once_with()
        self.assertEqual(len(offline_tracker.events), 1)
        tracked_response, tracker_context = offline_tracker.events[0]
        self.assertEqual(
            tracked_response,
            {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
        )
        self.assertEqual(tracker_context["task"], "dm_validation")
        self.assertEqual(tracker_context["attempt_id"], receipts[0][0].attempt_id)

    def test_prompt_digest_detects_message_literal_role_and_assembly_changes(self):
        baseline_source = """def owner():
    messages = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "prompt"}]
    response = llm.call(task="dm_main", messages=messages)
"""
        baseline = ast.parse(baseline_source).body[0]
        baseline_digest = _assembly_digest_for_function(baseline, {"messages"})[0]

        changed_literal = ast.parse(baseline_source.replace('"prompt"', '"changed prompt"')).body[0]
        changed_role = ast.parse(baseline_source.replace('"role": "user"', '"role": "assistant"')).body[0]
        changed_assembly = ast.parse(
            baseline_source.replace(
                "    response = llm.call",
                '    messages.append({"role": "user", "content": "added"})\n    response = llm.call',
            )
        ).body[0]
        for changed in (changed_literal, changed_role, changed_assembly):
            with self.subTest(changed=ast.dump(changed, include_attributes=False)):
                self.assertNotEqual(baseline_digest, _assembly_digest_for_function(changed, {"messages"})[0])

    def test_pre_migration_prompt_assembly_ast_and_asset_goldens_cover_all_15_owners(self):
        self.assertEqual(len(PROMPT_ASSEMBLY_BASELINES), 15)
        for key, expected in PROMPT_ASSEMBLY_BASELINES.items():
            with self.subTest(owner=key):
                actual, node_count = _prompt_assembly_digest(*key)
                self.assertGreater(node_count, 0)
                self.assertEqual(actual, expected)

        for relative_path, expected in PROMPT_ASSET_BASELINES.items():
            with self.subTest(asset=relative_path):
                actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)

    def test_all_15_actual_producer_requests_execute_with_fake_clients_and_task_params(self):
        operation_specs = [
            ("main.py", "generate_arrival_narration", 1),
            ("main.py", "generate_seamless_transition_narration", 1),
            ("main.py", "validate_ai_response", 1),
            ("main.py", "generate_module_summary", 1),
            ("main.py", "get_ai_response", 1),
            ("core/combat/bootstrap.py", "_run_resume_narrative", 2),
            ("core/combat/bootstrap.py", "_run_initial_scene_generation", 1),
            ("core/combat/turn.py", "run_combat_provider_retry_stage", 3),
            ("core/combat/validation.py", "validate_combat_response", 1),
            ("core/combat/combat_manager.py", "summarize_dialogue", 1),
            ("core/combat/combat_manager.py", "generate_combat_round_summary", 1),
            ("core/combat/initiative_tracker_ai.py", "generate_live_initiative_tracker", 1),
            ("core/ai/action_handler.py", "_ai_analyze_starting_location", 1),
            ("core/ai/action_handler.py", "process_action", 1),
            ("core/ai/action_handler.py", "get_ai_npc_movement_decision", 1),
        ]
        all_events = []
        message_digests = []
        executed = 0
        for path, function_name, expected_count in operation_specs:
            function = _owner_functions(path)[function_name]
            boundaries = _boundaries(function)
            self.assertEqual(len(boundaries), expected_count, path + "::" + function_name)
            for boundary in boundaries:
                events = []
                namespace = _request_fixture_namespace(events)
                if path == "main.py" and function_name == "generate_module_summary":
                    namespace["summary_messages"] = [
                        {"role": "system", "content": "fixture summary system"},
                        {"role": "user", "content": "fixture summary prompt bytes"},
                    ]
                if _name(boundary) == "_startup_provider_call":
                    helper = _owner_functions(path)["_startup_provider_call"]
                    helper = copy.deepcopy(helper)
                    helper.returns = None
                    for argument in helper.args.args + helper.args.kwonlyargs:
                        argument.annotation = None
                    module = ast.Module(body=[helper], type_ignores=[])
                    exec(compile(ast.fix_missing_locations(module), "<startup-provider-helper>", "exec"), namespace)
                    namespace.update({"messages_to_send": namespace["messages"], "context": "re-engage", "model": "fixture-model"})
                if path == "core/combat/bootstrap.py":
                    namespace["dependencies"] = namespace["dependencies"]
                # Inject only names explicitly referenced by this real AST call.
                for item in ast.walk(boundary):
                    if isinstance(item, ast.Name) and item.id not in namespace and item.id not in {"True", "False", "None"}:
                        self.fail(f"missing explicit fake dependency {item.id} for {path}::{function_name}")
                result = _exec_expression(boundary, namespace)
                self.assertIsNotNone(result, path + "::" + function_name)
                if _name(boundary).endswith("chat.completions.create"):
                    sdk_events = [event for event in events if event[0] in ("primary", "fallback")]
                    self.assertEqual(len(sdk_events), 1, path + "::" + function_name)
                    self.assertIn("messages", sdk_events[0][1])
                    message_digests.append((path, function_name, _message_digest(sdk_events[0][1]["messages"])))
                    task_events = [event for event in events if event[0] == "task"]
                    if not (path == "core/combat/initiative_tracker_ai.py"):
                        self.assertTrue(task_events, path + "::" + function_name)
                        self.assertTrue(all(event[1] == task_events[0][1] for event in task_events))
                elif _name(boundary) in {"llm.call", "dependencies.llm_call"}:
                    router_events = [event for event in events if event[0] == "router"]
                    self.assertEqual(len(router_events), 1, path + "::" + function_name)
                    expected_task = {
                        "validate_ai_response": "dm_validation",
                        "_ai_analyze_starting_location": "dm_validation",
                        "generate_module_summary": "summaries",
                        "_run_resume_narrative": "combat_main",
                        "_run_initial_scene_generation": "combat_main",
                        "run_combat_provider_retry_stage": "combat_main",
                        "validate_combat_response": "combat_validation",
                        "summarize_dialogue": "combat_summary",
                        "generate_combat_round_summary": "compression",
                        "generate_live_initiative_tracker": "combat_main",
                        "get_ai_npc_movement_decision": "updates",
                    }.get(function_name, "dm_main")
                    self.assertEqual(router_events[0][1]["task"], expected_task)
                    self.assertIs(router_events[0][1]["json_output"], False)
                    message_digests.append((path, function_name, _message_digest(router_events[0][1]["messages"])))
                else:
                    self.assertTrue(any(event[0] in ("primary", "fallback", "trace", "router") for event in events),
                                    path + "::" + function_name)
                all_events.extend(events)
                executed += 1

        self.assertEqual(executed, 18)
        observed_tasks = {event[1] for event in all_events if event[0] == "task"}
        observed_tasks.update(event[1]["task"] for event in all_events if event[0] == "router")
        self.assertTrue({"dm_main", "dm_validation", "summaries", "combat_main",
                         "combat_validation", "combat_summary", "compression", "updates"}.issubset(observed_tasks))
        source_inline_hashes = {
            ("core/combat/combat_manager.py", "generate_combat_round_summary"): "b2600028673e6dc9d510cce3f15e7c094e5a659c68593b90ee90190d8b00bca7",
        }
        for key, expected_hash in source_inline_hashes.items():
            self.assertIn((key[0], key[1], expected_hash), message_digests)

    def test_actual_module_summary_uses_router_and_preserves_summary_and_receipt_contract(self):
        from utils.llm_router import GameLLMTerminalError
        from utils.llm_runtime import make_legacy_receipt_observer as actual_observer_factory

        function = _owner_functions("main.py")["generate_module_summary"]
        module = ast.Module(body=[copy.deepcopy(function)], type_ignores=[])
        events = []
        requests = []
        observer_options = []
        raw_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="  Chronicle from the road.  "))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        )

        def observer_factory(**kwargs):
            observer_options.append(kwargs)
            return actual_observer_factory(
                **kwargs,
                api_logger=lambda endpoint, messages, response, metadata: events.append(
                    ("api", endpoint, messages, response, metadata)
                ),
                tracker_getter=lambda: SimpleNamespace(
                    track=lambda response, context: events.append(
                        ("tracker", response, context)
                    )
                ),
            )

        def router_call(**kwargs):
            requests.append(kwargs)
            kwargs["observer"](
                SimpleNamespace(kind="response", attempt_id="attempt-1", call_id="call-1"),
                raw_response,
            )
            return "  Chronicle from the road.  "

        namespace = {
            "GameLLMTerminalError": GameLLMTerminalError,
            "llm": SimpleNamespace(call=router_call),
            "make_legacy_receipt_observer": observer_factory,
            "USAGE_TRACKING_AVAILABLE": True,
            "debug": lambda *args, **kwargs: None,
            "warning": lambda *args, **kwargs: None,
            "error": lambda *args, **kwargs: None,
        }
        exec(compile(ast.fix_missing_locations(module), "<module-summary-owner>", "exec"), namespace)
        history = [
            {"role": "system", "content": "system context"},
            {"role": "user", "content": "A previous event."},
            {"role": "assistant", "content": "A prior response."},
            {"role": "user", "content": "Module summary: obsolete summary"},
            {"role": "system", "content": "new system context"},
            {"role": "user", "content": "We entered the moonlit wood."},
            {"role": "assistant", "content": "The owls watched from above."},
            {"role": "user", "content": "Location transition: ignored technical event"},
            {"role": "assistant", "content": "Dungeon Master Note: ignored technical event"},
            {"role": "assistant", "content": "We found a silver trail."},
        ]
        result = namespace["generate_module_summary"](history, {}, "Test Module", 10)
        expected_conversation = (
            "Player: We entered the moonlit wood.\n\n"
            "DM: The owls watched from above.\n\n"
            "DM: We found a silver trail.\n\n"
        )
        expected_prompt = (
            "You are creating an adventure chronicle for a 5th edition session. "
            "Summarize this actual gameplay conversation from the Test Module module into a compelling narrative story.\n\n"
            "IMPORTANT: Only include events that actually happened in the conversation. Do not add events from other sources.\n\n"
            "Focus on:\n"
            "- Actual player actions and decisions made\n"
            "- NPCs encountered and interactions that occurred  \n"
            "- Locations visited and described\n"
            "- Plot developments that happened\n"
            "- Character relationships and moments\n\n"
            "Write in an elevated fantasy prose style, like a chronicle or epic tale. Make it engaging but accurate to what actually occurred.\n\n"
            f"ACTUAL GAMEPLAY CONVERSATION:\n{expected_conversation}\n\n"
            "Write a compelling chronicle of these actual events:"
        )
        expected_messages = [
            {
                "role": "system",
                "content": "You are an expert at creating beautiful adventure chronicles from 5th edition gameplay, focusing only on events that actually occurred.",
            },
            {"role": "user", "content": expected_prompt},
        ]
        self.assertEqual(result, "=== MODULE SUMMARY ===\n\nTest Module:\n------------------------------\nChronicle from the road.")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["task"], "summaries")
        self.assertIs(requests[0]["json_output"], False)
        self.assertEqual(requests[0]["temperature"], 0.7)
        self.assertNotIn("timeout", requests[0])
        self.assertEqual(requests[0]["messages"], expected_messages)
        self.assertEqual(observer_options[0]["messages"], expected_messages)
        self.assertEqual(observer_options[0]["endpoint_name"], "module_summary")
        self.assertEqual(observer_options[0]["api_log_before_tracker"], True)
        self.assertEqual(observer_options[0]["track_usage"], True)
        self.assertEqual(observer_options[0]["legacy_context"]["purpose"], "generate_module_summary")
        self.assertEqual([event[0] for event in events], ["api", "tracker"])
        self.assertEqual(events[0][1:4], ("module_summary", expected_messages, raw_response))
        self.assertEqual(events[1][1], {"usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}})

        events.clear()
        no_usage_namespace = dict(namespace)
        no_usage_namespace["USAGE_TRACKING_AVAILABLE"] = False
        exec(compile(ast.fix_missing_locations(copy.deepcopy(module)), "<module-summary-no-usage>", "exec"), no_usage_namespace)
        self.assertEqual(
            no_usage_namespace["generate_module_summary"](history, {}, "Test Module", 10),
            result,
        )
        self.assertEqual([event[0] for event in events], ["api"])

        for terminal_kind in ("quota", "refusal", "content_filter"):
            terminal_calls = []
            terminal_namespace = dict(namespace)

            def terminal_router(**kwargs):
                terminal_calls.append(kwargs)
                raise GameLLMTerminalError(terminal_kind)

            terminal_namespace["llm"] = SimpleNamespace(call=terminal_router)
            exec(compile(ast.fix_missing_locations(copy.deepcopy(module)), "<module-summary-terminal>", "exec"), terminal_namespace)
            with self.subTest(terminal=terminal_kind):
                with self.assertRaises(GameLLMTerminalError):
                    terminal_namespace["generate_module_summary"](history, {}, "Test Module", 10)
                self.assertEqual(len(terminal_calls), 1)
                self.assertEqual(terminal_calls[0]["task"], "summaries")

        ordinary_namespace = dict(namespace)
        ordinary_calls = []

        def ordinary_failure(**kwargs):
            ordinary_calls.append(kwargs)
            raise RuntimeError("transient summary failure")

        ordinary_namespace["llm"] = SimpleNamespace(call=ordinary_failure)
        exec(compile(ast.fix_missing_locations(copy.deepcopy(module)), "<module-summary-failure>", "exec"), ordinary_namespace)
        self.assertEqual(
            ordinary_namespace["generate_module_summary"](history, {}, "Test Module", 10),
            "Short adventure in Test Module with several interactions.",
        )
        self.assertEqual(len(ordinary_calls), 1)

        no_call_namespace = dict(namespace)
        no_call_requests = []
        no_call_namespace["llm"] = SimpleNamespace(call=lambda **kwargs: no_call_requests.append(kwargs))
        exec(compile(ast.fix_missing_locations(copy.deepcopy(module)), "<module-summary-short>", "exec"), no_call_namespace)
        self.assertEqual(
            no_call_namespace["generate_module_summary"]([], {}, "Test Module", 0),
            "Brief activities in Test Module.",
        )
        self.assertEqual(no_call_requests, [])

    def test_initiative_tracker_request_uses_combat_main_facade_without_caller_model(self):
        function = _owner_functions("core/combat/initiative_tracker_ai.py")["generate_live_initiative_tracker"]
        router_call = next(call for call in _boundaries(function) if _name(call) == "llm.call")
        events = []
        namespace = _request_fixture_namespace(events)
        result = _exec_expression(router_call, namespace)
        self.assertIsNotNone(result)
        request = next(event[1] for event in events if event[0] == "router")
        self.assertEqual(request["task"], "combat_main")
        self.assertIs(request["json_output"], False)
        self.assertEqual(request["temperature"], 0.1)
        self.assertNotIn("model", request)
        self.assertNotIn("timeout", request)

    def test_actual_owner_parser_and_return_expressions_preserve_current_shapes(self):
        main = _owner_functions("main.py")
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='  {"valid":true}  '))])

        main_response_ns = {"content": '  {"valid":true}  '}
        _exec_statement(_assignment(main["get_ai_response"], "content"), main_response_ns)
        self.assertEqual(main_response_ns["content"], '{"valid":true}')
        self.assertEqual(_exec_expression(_return(main["get_ai_response"], "content").value, main_response_ns), '{"valid":true}')

        validator_ns = {"response_to_validate": "{" + '"actions":[]}' , "reason": "fixture reason"}
        passed_return = next(
            node for node in ast.walk(main["validate_ai_response"])
            if isinstance(node, ast.Return) and node.value is not None
            and "True" in ast.unparse(node.value) and "response_to_validate" in ast.unparse(node.value)
        )
        self.assertEqual(_exec_expression(passed_return.value, validator_ns), (True, '{"actions":[]}'))

        summary_ns = {"response_text": "  Chronicle bytes.  ",
                      "module_name": "Fixture Module"}
        for name in ("ai_summary", "formatted_summary"):
            _exec_statement(_assignment(main["generate_module_summary"], name), summary_ns)
        self.assertEqual(summary_ns["ai_summary"], "Chronicle bytes.")
        self.assertEqual(
            _exec_expression(_return(main["generate_module_summary"], "formatted_summary").value, summary_ns),
            "=== MODULE SUMMARY ===\n\nFixture Module:\n------------------------------\nChronicle bytes.",
        )

        combat = _owner_functions("core/combat/combat_manager.py")
        dialogue_ns = {
            "llm": SimpleNamespace(call=lambda **kwargs: ' {"narration":"Victory."} '),
            "make_legacy_receipt_observer": lambda **kwargs: None,
            "USAGE_TRACKING_AVAILABLE": True,
            "TEMPERATURE": 0.8,
            "dialogue_summary_prompt": [],
            "observer": None,
            "GameLLMTerminalError": RuntimeError,
            "json": json,
            "debug": lambda *args, **kwargs: None,
        }
        _exec_statement(_assignment(combat["summarize_dialogue"], "dialogue_summary"), dialogue_ns)
        narration_try = next(
            node for node in ast.walk(combat["summarize_dialogue"])
            if isinstance(node, ast.Try) and "parsed_summary" in ast.unparse(node)
        )
        _exec_statement(narration_try, dialogue_ns)
        self.assertEqual(dialogue_ns["dialogue_summary"], "Victory.")

        round_ns = {"summary_text": '{"round":4}', "json": json}
        _exec_statement(_assignment(combat["generate_combat_round_summary"], "summary"), round_ns)
        self.assertEqual(round_ns["summary"], {"round": 4})
        self.assertEqual(_exec_expression(_return(combat["generate_combat_round_summary"], "summary").value, round_ns), {"round": 4})

        initiative = _owner_functions("core/combat/initiative_tracker_ai.py")["generate_live_initiative_tracker"]
        marker_if = next(node for node in ast.walk(initiative) if isinstance(node, ast.If) and "Live Initiative Tracker" in ast.unparse(node.test))
        tracker_return = _return(initiative, "tracker_text.strip")
        tracker_ns = {"tracker_text": "**Live Initiative Tracker:**\nAcheron"}
        self.assertTrue(_exec_expression(marker_if.test, tracker_ns))
        self.assertEqual(_exec_expression(tracker_return.value, tracker_ns), "**Live Initiative Tracker:**\nAcheron")

    def test_selected_fallback_client_edges_execute_and_preserve_true_flag(self):
        main_owner = _owner_functions("main.py")["get_ai_response"]
        main_fallback_edges = [call for call in _calls(main_owner) if _name(call) == "create_chat_client"]
        self.assertEqual(main_fallback_edges, [])
        self.assertFalse(any(_name(call) == "request_chat_completion_with_recovery" for call in _calls(main_owner)))

        movement = _owner_functions("core/ai/action_handler.py")["get_ai_npc_movement_decision"]
        self.assertEqual(sum(_name(call) == "llm.call" for call in _calls(movement)), 1)
        self.assertFalse(any(_name(call) == "create_chat_client" for call in _calls(movement)))
        self.assertFalse(any(_name(call).endswith("chat.completions.create") for call in _calls(movement)))

    def test_bounded_main_terminal_vertical_skips_stale_admission_and_waits_for_next_input(self):
        from utils.llm_router import GameLLMTerminalError

        main = _owner_functions("main.py")
        main_loop = main["main_game_loop"]
        generation_try = next(
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.Try)
            and any(_name(call) == "get_ai_response" for call in _calls(node))
            and any(handler.type is not None and ast.unparse(handler.type) == "GameLLMTerminalError" for handler in node.handlers)
        )
        validation_try = next(
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.Try)
            and any(_name(call) == "validate_ai_response" for call in _calls(node))
            and any(handler.type is not None and ast.unparse(handler.type) == "GameLLMTerminalError" for handler in node.handlers)
        )
        terminal_guard = next(
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.If) and ast.unparse(node.test) == "terminal_llm_failure"
        )
        exhaustion_guard = next(
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.If) and "not valid_response_received" in ast.unparse(node.test)
        )
        call_try = next(
            node for node in ast.walk(main["get_ai_response"])
            if isinstance(node, ast.Try) and any(_name(call) == "llm.call" for call in _calls(node))
        )
        validation_call_try = next(
            node for node in ast.walk(main["validate_ai_response"])
            if isinstance(node, ast.Try) and any(_name(call) == "llm.call" for call in _calls(node))
        )

        class _Facade:
            def __init__(self, terminal_kind=None, terminal_owner="generation"):
                self.terminal_kind = terminal_kind
                self.terminal_owner = terminal_owner
                self.generation_calls = 0
                self.validation_calls = 0

            def call(self, **kwargs):
                owner = "validation" if kwargs["task"] == "dm_validation" else "generation"
                if owner == "validation":
                    self.validation_calls += 1
                    count = self.validation_calls
                else:
                    self.generation_calls += 1
                    count = self.generation_calls
                if count == 1 and owner == self.terminal_owner and self.terminal_kind:
                    raise GameLLMTerminalError(self.terminal_kind)
                return '{"narration":"fresh-next-input"}' if owner == "generation" else '{"valid":true,"reason":"ok"}'

        class _ForbiddenPersistence(Exception):
            pass

        for owner in ("generation", "validation"):
            for terminal_kind in ("quota", "refusal", "content_filter"):
                with self.subTest(owner=owner, terminal=terminal_kind):
                    facade = _Facade(terminal_kind, owner)
                    status_events = []
                    processed = []

                    def invoke_generation(*args, **kwargs):
                        namespace = {
                            "llm": facade,
                            "GameLLMTerminalError": GameLLMTerminalError,
                            "messages_to_send": [{"role": "user", "content": "fixture"}],
                            "model_tier": "complex",
                            "call_options": {},
                            "observe_main_attempt": lambda *a: None,
                        }
                        exec(compile(ast.Module(body=[copy.deepcopy(call_try)], type_ignores=[]), "<selected-main-router-call>", "exec"), namespace)
                        return namespace["content"].strip()

                    def invoke_validation(*args, **kwargs):
                        namespace = {
                            "llm": facade,
                            "GameLLMTerminalError": GameLLMTerminalError,
                            "validation_messages_to_send": [{"role": "system", "content": "fixture"}],
                            "make_legacy_receipt_observer": lambda **kw: lambda *a: None,
                            "validation_receipt_observer": lambda *a: None,
                            "USAGE_TRACKING_AVAILABLE": False,
                            "max_validation_retries": 3,
                            "attempt": 0,
                        }
                        exec(compile(ast.Module(body=[copy.deepcopy(validation_call_try)], type_ignores=[]), "<selected-validation-router-call>", "exec"), namespace)
                        return True, namespace["validation_response"]

                    def run_vertical(remove_terminal_guard=False):
                        facade.generation_calls = 0
                        facade.validation_calls = 0
                        namespace = {
                            "GameLLMTerminalError": GameLLMTerminalError,
                            "get_ai_response": invoke_generation,
                            "validate_ai_response": invoke_validation,
                            "conversation_history": [],
                            "user_input_text": "fixture input",
                            "validation_prompt_text": "fixture validation",
                            "party_tracker_data": {},
                            "retry_correction_note": None,
                            "retry_count": 0,
                            "terminal_llm_failure": False,
                            "valid_response_received": False,
                            "ai_response_content": "STALE FAILED RESPONSE",
                            "is_valid": False,
                            "validation_reason": "",
                            "last_validation_reason": None,
                            "error": lambda *a, **kw: None,
                            "status_ready": lambda: status_events.append("ready"),
                            "log_rejected_narrator_turn": lambda *a, **kw: (_ for _ in ()).throw(_ForbiddenPersistence("rejected-response write reached")),
                            "save_conversation_history": lambda *a, **kw: (_ for _ in ()).throw(_ForbiddenPersistence("history write reached")),
                            "process_ai_response": lambda content, *a: processed.append(content),
                            "party_tracker_data": {},
                            "location_data": {},
                        }
                        loop_body = [
                            copy.deepcopy(generation_try),
                            copy.deepcopy(validation_try),
                            ast.Assign(targets=[ast.Name(id="valid_response_received", ctx=ast.Store())], value=ast.Constant(True)),
                            ast.Assign(targets=[ast.Name(id="is_valid", ctx=ast.Store())], value=ast.Constant(True)),
                            ast.Break(),
                        ]
                        turn_loop = ast.While(
                            test=ast.BoolOp(op=ast.And(), values=[
                                ast.Compare(left=ast.Name(id="retry_count", ctx=ast.Load()), ops=[ast.Lt()], comparators=[ast.Constant(5)]),
                                ast.UnaryOp(op=ast.Not(), operand=ast.Name(id="valid_response_received", ctx=ast.Load())),
                            ]),
                            body=loop_body,
                            orelse=[],
                        )
                        admitted = ast.If(
                            test=ast.Name(id="is_valid", ctx=ast.Load()),
                            body=[ast.Expr(value=ast.Call(func=ast.Name(id="process_ai_response", ctx=ast.Load()), args=[ast.Name(id="ai_response_content", ctx=ast.Load()), ast.Name(id="party_tracker_data", ctx=ast.Load()), ast.Name(id="location_data", ctx=ast.Load()), ast.Name(id="conversation_history", ctx=ast.Load())], keywords=[]))],
                            orelse=[],
                        )
                        turn_body = [
                            ast.Assign(targets=[ast.Name(id="retry_count", ctx=ast.Store())], value=ast.Constant(0)),
                            ast.Assign(targets=[ast.Name(id="valid_response_received", ctx=ast.Store())], value=ast.Constant(False)),
                            ast.Assign(targets=[ast.Name(id="terminal_llm_failure", ctx=ast.Store())], value=ast.Constant(False)),
                            ast.Assign(targets=[ast.Name(id="ai_response_content", ctx=ast.Store())], value=ast.Constant("STALE FAILED RESPONSE")),
                            ast.Assign(targets=[ast.Name(id="is_valid", ctx=ast.Store())], value=ast.Constant(False)),
                            turn_loop,
                        ]
                        if not remove_terminal_guard:
                            turn_body.append(copy.deepcopy(terminal_guard))
                        turn_body.extend([copy.deepcopy(exhaustion_guard), admitted])
                        for_node = ast.For(
                            target=ast.Name(id="turn", ctx=ast.Store()),
                            iter=ast.Call(func=ast.Name(id="range", ctx=ast.Load()), args=[ast.Constant(1 if remove_terminal_guard else 2)], keywords=[]),
                            body=turn_body,
                            orelse=[],
                        )
                        function_node = ast.FunctionDef(
                            name="run",
                            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                            body=[for_node],
                            decorator_list=[],
                        )
                        module = ast.Module(body=[function_node], type_ignores=[])
                        exec(compile(ast.fix_missing_locations(module), "<bounded-main-input-vertical>", "exec"), namespace)
                        namespace["run"]()

                    run_vertical()
                    self.assertEqual(status_events, ["ready"])
                    self.assertEqual(processed, ['{"narration":"fresh-next-input"}'])
                    if owner == "generation":
                        self.assertEqual((facade.generation_calls, facade.validation_calls), (2, 1))
                    else:
                        self.assertEqual((facade.generation_calls, facade.validation_calls), (2, 2))

                    with self.assertRaises(_ForbiddenPersistence):
                        run_vertical(remove_terminal_guard=True)

    def test_main_tier_hint_preserves_predictor_and_forced_full_route_table(self):
        narrator = _owner_functions("main.py")["get_ai_response"]
        tier_assignment = next(
            node for node in ast.walk(narrator)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "model_tier" for target in node.targets)
        )
        cases = (
            (True, 0, False, False, "simple"),
            (True, 0, False, True, "complex"),
            (True, 1, False, False, "complex"),
            (True, 2, False, True, "complex"),
            (True, 3, False, False, "complex"),
            (True, 4, False, False, "complex"),
            (True, 0, True, False, "complex"),
            (False, 0, False, False, "complex"),
        )
        for enabled, retry, module_prompt, requires_actions, expected in cases:
            namespace = {
                "ENABLE_INTELLIGENT_ROUTING": enabled,
                "validation_retry_count": retry,
                "has_module_creation_prompt": module_prompt,
                "prediction": {"requires_actions": requires_actions},
            }
            _exec_statement(tier_assignment, namespace)
            with self.subTest(case=(enabled, retry, module_prompt, requires_actions)):
                self.assertEqual(namespace["model_tier"], expected)

        family_branch = next(
            node for node in narrator.body
            if isinstance(node, ast.If) and ast.unparse(node.test) == "USE_GPT5_MODELS"
            and any(isinstance(item, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "call_options"
                for target in item.targets
            ) for item in ast.walk(node))
        )
        for use_gpt5, expected_options in ((True, {}), (False, {"temperature": 0.7})):
            namespace = {
                "USE_GPT5_MODELS": use_gpt5,
                "GPT5_MINI_MODEL": "legacy-gpt5-mini",
                "GPT5_FULL_MODEL": "legacy-gpt5-full",
                "validation_retry_count": 4,
                "selected_model": "legacy-selection",
                "TEMPERATURE": 0.7,
                "print": lambda *a, **kw: None,
            }
            _exec_statement(family_branch, namespace)
            self.assertEqual(namespace["call_options"], expected_options)

    def test_main_empty_exhaustion_escapes_one_facade_call_without_outer_retry(self):
        from utils.provider_response_recovery import EmptyProviderResponseError
        from utils.llm_router import GameLLMTerminalError

        narrator = _owner_functions("main.py")["get_ai_response"]
        call_try = next(
            node for node in ast.walk(narrator)
            if isinstance(node, ast.Try) and any(_name(call) == "llm.call" for call in _calls(node))
        )
        events = []

        class ExhaustedFacade:
            def call(self, **kwargs):
                events.append(kwargs)
                raise EmptyProviderResponseError(attempts=6, context="dm_main")

        namespace = {
            "llm": ExhaustedFacade(),
            "GameLLMTerminalError": GameLLMTerminalError,
            "messages_to_send": [{"role": "user", "content": "fixed"}],
            "model_tier": "complex",
            "call_options": {},
            "observe_main_attempt": lambda *a: None,
        }
        with self.assertRaises(EmptyProviderResponseError) as raised:
            exec(compile(ast.Module(body=[copy.deepcopy(call_try)], type_ignores=[]), "<main-empty-exhaustion>", "exec"), namespace)
        self.assertEqual(raised.exception.attempts, 6)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["empty_retry_limit"], 2)
        self.assertFalse(any(_name(call) == "request_chat_completion_with_recovery" for call in _calls(narrator)))

    def test_actual_dormant_main_helpers_preserve_messages_returns_and_callback_order(self):
        main_functions = _owner_functions("main.py")
        from utils.llm_router import GameLLMTerminalError
        from utils.llm_runtime import make_legacy_receipt_observer

        for function_name, arguments in (
            ("generate_arrival_narration", ("Departed the old bridge.",
              {"worldConditions": {"currentLocation": "North Gate", "currentArea": "Stone Reach"}},
              [{"role": "system", "content": "discard system context"}, {"role": "user", "content": "The party arrives."}])),
            ("generate_seamless_transition_narration", ("Left the harbor.", "Reached the tower.")),
        ):
            events = []
            content = ' {"narration":"The road opens."} ' if function_name == "generate_arrival_narration" else "The road opens."
            raw_response = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )
            receipt = SimpleNamespace(
                kind="response", call_id="call-1", attempt_id="attempt-1", attempt_number=1,
                task="dm_main", tier="full", profile="fixture", transport_retry=False,
                retry_tier=None, fallback=False, transport_provider="openai",
                observed_upstream_provider=None, requested_model="fixture-model",
                resolved_model="fixture-model", provider_reported_cost_usd=0.0,
                cost_usd=0.0, cost_provenance="actual", cost_complete=True,
                usage_complete=True, prompt_tokens=2, cached_tokens=0, completion_tokens=3,
                error_type=None,
            )
            tracker = SimpleNamespace(track=lambda *args: events.append(("track", args)))

            def observer_factory(**kwargs):
                return make_legacy_receipt_observer(
                    **kwargs,
                    tracker_getter=lambda: tracker,
                    api_logger=lambda *args, **kw: events.append(("api-log", args[0], args[1], kw)),
                )

            class FakeRouter:
                def call(self, **kwargs):
                    events.append(("router", kwargs))
                    self.kwargs = kwargs
                    kwargs["observer"](receipt, raw_response)
                    return content

            namespace = {
                "llm": FakeRouter(),
                "make_legacy_receipt_observer": observer_factory,
                "GameLLMTerminalError": GameLLMTerminalError,
                "debug": lambda *a, **k: events.append(("debug", a[0])),
                "error": lambda *a, **k: events.append(("error", a[0])),
                "TEMPERATURE": 0.7,
                "sanitize_text": lambda value: value,
                "json": json,
                "USAGE_TRACKING_AVAILABLE": True,
            }
            function_node = main_functions[function_name]
            exec(compile(ast.Module(body=[function_node], type_ignores=[]), "<main-owner-function>", "exec"), namespace)
            response = namespace[function_name](*arguments)
            self.assertEqual(response, "The road opens.")
            self.assertEqual([event[0] for event in events if event[0] in ("router", "track", "api-log")], ["router", "api-log", "track"])
            request = next(event[1] for event in events if event[0] == "router")
            expected_hash = {
                "generate_arrival_narration": "679f1f24e08598cbab8a5d95f4679fe8d5baff71d7d83a50810c601e7f141431",
                "generate_seamless_transition_narration": "15a6c624f077e8e3de71e5b616c57593a0521cc9fc8e3a856ac8e426469aafce",
            }[function_name]
            self.assertEqual(_message_digest(request["messages"]), expected_hash, repr(request["messages"]))
            self.assertEqual(request["task"], "dm_main")
            self.assertIs(request["json_output"], False)
            self.assertEqual(request["temperature"], 0.7)
            self.assertEqual(request["messages"][0]["role"], "system")
            self.assertEqual(request["messages"][-1]["role"], "user")
            self.assertEqual(sum(event[0] == "track" for event in events), 1)
            self.assertEqual(sum(event[0] == "api-log" for event in events), 1)
            tracker_metadata = next(event[1][1] for event in events if event[0] == "track")
            api_log = next(event for event in events if event[0] == "api-log")
            expected_labels = {
                "generate_arrival_narration": ("narration_generator", "generate_narrative_summary", "narration_generator"),
                "generate_seamless_transition_narration": ("narrative_stitching", "stitch_location_descriptions", "narrative_stitcher"),
            }[function_name]
            self.assertEqual((tracker_metadata["endpoint"], tracker_metadata["purpose"], api_log[1]), expected_labels)
            self.assertEqual(_message_digest(api_log[2]), expected_hash)
            self.assertEqual(api_log[3]["metadata"]["context"], "module_transition_arrival" if function_name == "generate_arrival_narration" else "module_transition_stitch")
            self.assertFalse(any(event[0] == "error" for event in events))
            self.assertTrue(any(event[0] == "debug" and "SUCCESS:" in event[1] for event in events))

        for function_name, args, expected in (
            ("generate_seamless_transition_narration", ("", "arrival"), "arrival"),
            ("generate_seamless_transition_narration", ("departure", ""), "departure"),
        ):
            empty_events = []
            namespace = {"debug": lambda *a, **k: None, "llm": SimpleNamespace(call=lambda **kw: empty_events.append(kw))}
            function_node = main_functions[function_name]
            exec(compile(ast.Module(body=[function_node], type_ignores=[]), "<main-owner-empty>", "exec"), namespace)
            self.assertEqual(namespace[function_name](*args), expected)
            self.assertEqual(empty_events, [])

        for function_name, args, expected in (
            ("generate_arrival_narration", ("departed", {"worldConditions": {"currentLocation": "North Gate", "currentArea": "Stone Reach"}}, []), "(The journey to North Gate is uneventful.)"),
            ("generate_seamless_transition_narration", ("departure", "arrival"), "departure\n\narrival"),
        ):
            function_node = main_functions[function_name]
            for terminal_kind in ("quota", "refusal", "content_filter"):
                terminal = GameLLMTerminalError(terminal_kind)
                events = []
                calls = []

                def terminal_call(**kwargs):
                    calls.append(kwargs)
                    raise terminal

                namespace = {
                    "GameLLMTerminalError": GameLLMTerminalError,
                    "make_legacy_receipt_observer": lambda **kwargs: lambda *a: None,
                    "llm": SimpleNamespace(call=terminal_call),
                    "debug": lambda *a, **k: events.append(("debug", a[0])),
                    "error": lambda *a, **k: events.append(("error", a[0])),
                    "sanitize_text": lambda value: value,
                    "json": json,
                    "TEMPERATURE": 0.7,
                    "USAGE_TRACKING_AVAILABLE": True,
                }
                exec(compile(ast.Module(body=[function_node], type_ignores=[]), "<main-owner-terminal>", "exec"), namespace)
                with self.subTest(function=function_name, terminal=terminal_kind):
                    with self.assertRaises(GameLLMTerminalError):
                        namespace[function_name](*args)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0]["task"], "dm_main")
                    self.assertIs(calls[0]["json_output"], False)
                    self.assertFalse(any(event[0] == "error" for event in events))

            events = []
            namespace = {
                "GameLLMTerminalError": GameLLMTerminalError,
                "make_legacy_receipt_observer": lambda **kwargs: lambda *a: None,
                "llm": SimpleNamespace(call=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("ordinary failure"))),
                "debug": lambda *a, **k: events.append(("debug", a[0])),
                "error": lambda *a, **k: events.append(("error", a[0])),
                "sanitize_text": lambda value: value,
                "json": json,
                "TEMPERATURE": 0.7,
                "USAGE_TRACKING_AVAILABLE": True,
            }
            exec(compile(ast.Module(body=[function_node], type_ignores=[]), "<main-owner-nonterminal>", "exec"), namespace)
            self.assertEqual(namespace[function_name](*args), expected)

    def test_actual_router_with_fake_sdk_returns_text_to_actual_selected_helper(self):
        import utils.ai_client_factory as factory
        import utils.llm_usage_tracker as usage_tracker
        from utils.llm_router import GameLLMTerminalError, LLMRouter
        from utils.llm_runtime import make_legacy_receipt_observer

        events = []
        content = '  {"narration":"The seam opens."}  '
        raw_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content, refusal=None))],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=5, total_tokens=9),
            model="fixture-router-model",
        )

        class FakeSDKClient:
            def with_options(self, **kwargs):
                events.append(("sdk-options", kwargs))
                return self

            class Completions:
                def create(inner_self, **kwargs):
                    events.append(("sdk-call", kwargs))
                    return raw_response

            def __init__(self):
                self.chat = SimpleNamespace(completions=self.Completions())

        sdk = FakeSDKClient()
        router = LLMRouter()
        tracker_getter_calls = []
        logged = []
        offline_tracker = _OfflineUsageTracker()
        global_tracker_getter = mock.Mock(return_value=offline_tracker)

        def observer_factory(**kwargs):
            return make_legacy_receipt_observer(
                **kwargs,
                tracker_getter=lambda: tracker_getter_calls.append("getter"),
                api_logger=lambda *args, **kw: logged.append((args, kw)),
            )

        function = _owner_functions("main.py")["generate_arrival_narration"]
        namespace = {
            "GameLLMTerminalError": GameLLMTerminalError,
            "llm": router,
            "make_legacy_receipt_observer": observer_factory,
            "USAGE_TRACKING_AVAILABLE": False,
            "TEMPERATURE": 0.7,
            "sanitize_text": lambda value: value,
            "json": json,
            "debug": lambda *args, **kwargs: events.append(("debug", args[0])),
            "error": lambda *args, **kwargs: events.append(("error", args[0])),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<actual-main-arrival>", "exec"), namespace)
        with mock.patch.object(usage_tracker, "get_global_tracker", global_tracker_getter):
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
                with mock.patch.object(factory, "create_chat_client", return_value=sdk):
                    with mock.patch.object(router, "_request_kwargs", wraps=router._request_kwargs) as request_kwargs:
                        result = namespace["generate_arrival_narration"](
                            "Departed.",
                            {"worldConditions": {"currentLocation": "North Gate", "currentArea": "Stone Reach"}},
                            [],
                        )

        self.assertEqual(result, "The seam opens.")
        self.assertEqual(len([event for event in events if event[0] == "sdk-call"]), 1)
        request_kwargs.assert_called_once()
        self.assertEqual(request_kwargs.call_args.kwargs["temperature"], 0.7)
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0][0][0], "narration_generator")
        self.assertEqual(tracker_getter_calls, [])
        global_tracker_getter.assert_called_once_with()
        self.assertEqual(len(offline_tracker.events), 1)
        tracked_response, tracker_context = offline_tracker.events[0]
        self.assertEqual(
            tracked_response,
            {"usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9}},
        )
        self.assertEqual(tracker_context["task"], "dm_main")
        self.assertEqual(
            tracker_context["attempt_id"], logged[0][1]["metadata"]["attempt_id"]
        )
        self.assertFalse(any(event[0] == "error" for event in events))
        self.assertTrue(any(event[0] == "debug" and "SUCCESS:" in event[1] for event in events))

    def test_actual_action_handler_functions_preserve_returns_and_fallback_callback_order(self):
        movement = _owner_functions("core/ai/action_handler.py")["get_ai_npc_movement_decision"]
        self.assertEqual(sum(_name(call) == "llm.call" for call in _calls(movement)), 1)
        self.assertFalse(any(_name(call).endswith("chat.completions.create") for call in _calls(movement)))
        self.assertFalse(any(_name(call) == "create_chat_client" for call in _calls(movement)))

    def test_actual_process_action_transition_block_preserves_request_history_and_save_order(self):
        transition_owner = _owner_functions("core/ai/action_handler.py")["process_action"]
        block = next(
            node for node in ast.walk(transition_owner)
            if isinstance(node, ast.Try)
            and any(_name(call) == "llm.call" for call in _calls(node))
        )
        events = []
        history = [{"role": "user", "content": "go north"}]

        def fake_call(**kwargs):
            events.append(("router", kwargs))
            return "The party reaches the tower."

        namespace = {
            "llm": SimpleNamespace(call=fake_call),
            "make_legacy_receipt_observer": lambda **kwargs: events.append(("observer", kwargs)) or "observer",
            "USAGE_TRACKING_AVAILABLE": True,
            "GameLLMTerminalError": RuntimeError,
            "transition_prompt": "Exact transition prompt fixture.",
            "new_location_name": "The Tower",
            "conversation_history": history,
            "save_conversation_history": lambda value: events.append(("save", copy.deepcopy(value))),
            "debug": lambda *a, **k: None,
            "info": lambda *a, **k: None,
            "warning": lambda *a, **k: None,
            "error": lambda *a, **k: None,
        }
        module = ast.Module(body=[block], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "<process-action-transition-block>", "exec"), namespace)
        self.assertEqual(history[-1], {"role": "assistant", "content": "The party reaches the tower."})
        self.assertEqual([event[0] for event in events], ["observer", "router", "save"])
        request = events[1][1]
        self.assertEqual(request["task"], "dm_main")
        self.assertIs(request["json_output"], False)
        self.assertEqual(request["temperature"], 0.7)
        self.assertEqual(_message_digest(request["messages"]), "417d070c9a52f643b020e823d5e39f362bb7cb53146cf21d45fc055114a9e773")

    def test_tripwires_are_untouched_by_provider_free_selected_requests(self):
        _TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
