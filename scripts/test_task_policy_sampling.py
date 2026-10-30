# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free task-family sampling policy and transport tripwires."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from scripts.core_chat_test_safety import arm_process_tripwires

_TRIPWIRES = arm_process_tripwires()

import model_config
from utils import ai_client_factory, llm_router


_ROOT_EXCLUDED = frozenset(
    {"docs", "plans", "openspec", "memory-bank", "tmp", ".git"}
)
_DIRECTORY_EXCLUDED = frozenset(
    {".venv", "venv", "node_modules", "__pycache__", "tests"}
)
_EXPECTED_LITERAL_TASKS = frozenset(
    {
        "action_prediction",
        "adventure_summary",
        "builders",
        "character_validator",
        "combat_main",
        "combat_summary",
        "combat_validation",
        "compression",
        "dm_main",
        "dm_mini",
        "dm_validation",
        "encounter_update",
        "generate_area_description",
        "generate_area_name",
        "generate_thematic_names",
        "level_up",
        "location_compression",
        "location_generator",
        "location_generator_batch",
        "location_summarizer",
        "module_generator",
        "monster_builder",
        "npc_builder",
        "npc_name_canonicalizer",
        "parse_module_params",
        "plot_generator",
        "plot_update",
        "prompt_sanitizer",
        "safety_review",
        "storage_processor",
        "summaries",
        "travel_narration",
        "unify_plots",
        "update_plot_hooks",
        "updates",
        "validation",
    }
)
_EXPECTED_CONSTANT_TASKS = frozenset(
    {
        "toolkit_adaptation_author",
        "toolkit_adaptation_convergence",
        "toolkit_adaptation_semantic_auditor",
        "toolkit_final_reconciliation",
    }
)


def _call_parts(node: ast.expr) -> tuple[str, ...]:
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return tuple(reversed(parts))


def _is_facade_call(node: ast.Call) -> bool:
    parts = _call_parts(node.func)
    return parts == ("llm", "call") or parts[-1:] in {
        ("llm_call",),
        ("facade_call",),
    }


def _task_node(node: ast.Call) -> ast.expr | None:
    task = next((item.value for item in node.keywords if item.arg == "task"), None)
    if task is not None:
        return task
    return node.args[0] if node.args else None


def _task_keys_in_production_source() -> tuple[set[str], set[str]]:
    literal_keys: set[str] = set()
    resolved_keys: set[str] = set()
    for directory, child_directories, filenames in os.walk(ROOT, topdown=True):
        current = Path(directory)
        relative_directory = current.relative_to(ROOT)
        is_root = not relative_directory.parts
        child_directories[:] = sorted(
            name
            for name in child_directories
            if name not in _DIRECTORY_EXCLUDED
            and not (is_root and name in _ROOT_EXCLUDED)
        )
        for filename in filenames:
            if not filename.endswith(".py") or filename.startswith("test_"):
                continue
            source_path = current / filename
            relative_path = source_path.relative_to(ROOT).as_posix()
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_path)
            constants: dict[str, str] = {}
            for statement in tree.body:
                if isinstance(statement, ast.Assign):
                    targets = statement.targets
                    value = statement.value
                elif isinstance(statement, ast.AnnAssign):
                    targets = [statement.target]
                    value = statement.value
                else:
                    continue
                if value is None:
                    continue
                try:
                    literal = ast.literal_eval(value)
                except (TypeError, ValueError):
                    continue
                if not isinstance(literal, str):
                    continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = literal

            for call in ast.walk(tree):
                if not isinstance(call, ast.Call) or not _is_facade_call(call):
                    continue
                task = _task_node(call)
                if isinstance(task, ast.Constant) and isinstance(task.value, str):
                    literal_keys.add(task.value)
                    resolved_keys.add(task.value)
                elif isinstance(task, ast.Name) and task.id in constants:
                    resolved_keys.add(constants[task.id])
    return literal_keys, resolved_keys


class _FakeClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.chat = type("Chat", (), {})()
        self.chat.completions = type("Completions", (), {})()
        self.chat.completions.create = self._create

    def with_options(self, **_kwargs: object) -> "_FakeClient":
        return self

    def _create(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(dict(kwargs))
        return {"choices": [{"message": {"content": "provider-free response"}}]}


class TaskPolicySamplingTests(unittest.TestCase):
    def test_every_production_facade_task_has_a_policy(self) -> None:
        literal_keys, resolved_keys = _task_keys_in_production_source()
        policies = model_config.TASK_POLICY_SAMPLING

        self.assertTrue(_EXPECTED_LITERAL_TASKS.issubset(literal_keys))
        self.assertTrue(_EXPECTED_CONSTANT_TASKS.issubset(resolved_keys))
        self.assertEqual(
            literal_keys - set(policies),
            set(),
            "production facade task keys missing sampling policies",
        )
        self.assertEqual(
            resolved_keys - set(policies),
            set(),
            "resolved facade task keys missing sampling policies",
        )
        self.assertEqual(set(policies), resolved_keys)
        for task, policy in policies.items():
            with self.subTest(task=task):
                self.assertEqual(policy["reasoning"], {"family": "reasoning"})
                non_reasoning = policy["non_reasoning"]
                self.assertEqual(non_reasoning["family"], "non_reasoning")
                self.assertIsInstance(non_reasoning["temperature"], (int, float))
                ai_client_factory.get_task_sampling_policy(task)
                if task == "compression":
                    self.assertEqual(non_reasoning["top_p"], 1.0)
                else:
                    self.assertNotIn("top_p", non_reasoning)

    def test_known_reasoning_models_omit_sampling_controls(self) -> None:
        for model in ("gpt-6-luna", "gpt-5.6-luna"):
            with self.subTest(model=model):
                params = ai_client_factory.finalize_chat_params(
                    model,
                    params={"temperature": 0.9, "top_p": 0.2},
                    temperature=0.8,
                    task_id="dm_main",
                )
                self.assertEqual(params["model"], model)
                self.assertEqual(params["reasoning_effort"], "medium")
                self.assertEqual(params["verbosity"], "medium")
                self.assertNotIn("temperature", params)
                self.assertNotIn("top_p", params)

    def test_nonreasoning_models_use_task_sampling_values(self) -> None:
        params = ai_client_factory.finalize_chat_params(
            "vendor/unknown-model",
            params={"temperature": 0.9, "top_p": 0.2},
            task_id="dm_mini",
        )
        self.assertEqual(params["temperature"], 0.4)
        self.assertNotIn("top_p", params)
        self.assertNotIn("reasoning_effort", params)

    def test_malformed_task_policy_fails_closed(self) -> None:
        malformed_policy = {
            "reasoning": {"family": "reasoning"},
            "non_reasoning": {
                "family": "non_reasoning",
                "temperature": 0.5,
                "top_p": None,
            },
        }
        with mock.patch.object(
            model_config,
            "TASK_POLICY_SAMPLING",
            {"malformed": malformed_policy},
        ):
            with self.assertRaisesRegex(
                ai_client_factory.TaskSamplingPolicyError,
                "top_p must be numeric",
            ):
                ai_client_factory.finalize_chat_params(
                    "vendor/unknown-model", task_id="malformed"
                )

    def test_factory_task_policy_overrides_per_call_temperature(self) -> None:
        with mock.patch.object(
            ai_client_factory,
            "_get_actual_provider",
            return_value=("openai", False),
        ):
            params = ai_client_factory.get_chat_completion_params(
                "dm_main",
                "vendor/nonreasoning-model",
                temperature_override=0.3,
            )

        self.assertEqual(params["model"], "vendor/nonreasoning-model")
        self.assertEqual(params["temperature"], 0.7)

    def test_openrouter_auto_uses_task_values_and_configured_top_p_only(self) -> None:
        auto_dm_mini = ai_client_factory.finalize_chat_params(
            "openrouter/auto",
            params={"temperature": 0.9, "top_p": 0.2},
            is_openrouter=True,
            task_id="dm_mini",
        )
        self.assertEqual(auto_dm_mini["temperature"], 0.4)
        self.assertNotIn("top_p", auto_dm_mini)

        auto_compression = ai_client_factory.finalize_chat_params(
            "openrouter/auto",
            params={"temperature": 0.9},
            is_openrouter=True,
            task_id="compression",
        )
        self.assertEqual(auto_compression["temperature"], 0.3)
        self.assertEqual(auto_compression["top_p"], 1.0)

    def test_missing_policy_fails_before_client_or_transport(self) -> None:
        client = _FakeClient()
        with mock.patch.object(model_config, "TASK_POLICY_SAMPLING", {}), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            return_value=client,
        ) as create_client:
            with self.assertRaisesRegex(
                ai_client_factory.TaskSamplingPolicyError,
                "Missing TASK_POLICY_SAMPLING policy",
            ):
                llm_router.llm.call("unregistered_production_task", [])

        create_client.assert_not_called()
        self.assertEqual(client.requests, [])

    def test_direct_gpt6_luna_request_shape_is_unchanged(self) -> None:
        client = _FakeClient()
        messages = [{"role": "user", "content": "exact request contract"}]
        with mock.patch.object(
            ai_client_factory,
            "_get_actual_provider",
            return_value=("openai", False),
        ), mock.patch.object(
            ai_client_factory,
            "create_chat_client",
            return_value=client,
        ):
            response = llm_router.llm.call("dm_main", messages)

        self.assertEqual(response, "provider-free response")
        self.assertEqual(
            client.requests,
            [
                {
                    "model": "gpt-6-luna",
                    "reasoning_effort": "medium",
                    "verbosity": "medium",
                    "messages": messages,
                }
            ],
        )
        _TRIPWIRES.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
