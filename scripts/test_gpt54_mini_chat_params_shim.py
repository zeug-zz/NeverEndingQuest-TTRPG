# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
GPT-5.6 Luna chat parameter shim contract tests (generic GPT-5 family).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.core_chat_test_safety import arm_process_tripwires

_PROCESS_TRIPWIRES = arm_process_tripwires()

import utils.ai_client_factory as ai_client_factory


class TestGPT54MiniChatParamsShim(unittest.TestCase):
    def setUp(self) -> None:
        self._legacy_temperature_flag = ai_client_factory.GPT5_INCLUDE_LEGACY_TEMPERATURE
        self._actual_provider = ai_client_factory._get_actual_provider
        ai_client_factory._get_actual_provider = lambda use_fallback=False: ("openai", False)

    def tearDown(self) -> None:
        ai_client_factory.GPT5_INCLUDE_LEGACY_TEMPERATURE = self._legacy_temperature_flag
        ai_client_factory._get_actual_provider = self._actual_provider

    def test_gpt5_dm_main_omits_legacy_sampling_controls(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-5.6-luna",
            temperature_override=0.7,
        )

        self.assertEqual(params["model"], "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_gpt5_validation_prefers_low_reasoning_and_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_validation",
            "gpt-5.6-luna",
            temperature_override=0.1,
        )

        self.assertEqual(params["reasoning_effort"], "low")
        self.assertEqual(params["verbosity"], "low")
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_non_gpt5_uses_task_temperature_policy(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-4.1-2025-04-14",
            temperature_override=0.42,
        )

        self.assertEqual(params["model"], "gpt-4.1-2025-04-14")
        self.assertEqual(params["temperature"], 0.7)
        self.assertNotIn("reasoning_effort", params)
        self.assertNotIn("verbosity", params)

    def test_rollback_flag_can_restore_legacy_temperature(self) -> None:
        ai_client_factory.GPT5_INCLUDE_LEGACY_TEMPERATURE = True

        params = ai_client_factory.get_chat_completion_params(
            "combat_main",
            "gpt-5.6-luna",
            temperature_override=0.8,
        )

        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")
        self.assertEqual(params["temperature"], 0.8)

    def test_openrouter_passthrough_uses_sdk_compatible_extra_body_shape(self) -> None:
        ai_client_factory._get_actual_provider = lambda use_fallback=False: ("openrouter", True)

        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-4.1-2025-04-14",
            temperature_override=0.7,
        )

        self.assertEqual(params["temperature"], 0.7)
        self.assertEqual(
            params["extra_body"],
            {"thinking": {"type": "enabled"}},
        )
        self.assertNotIn("thinking", params)

    def test_migrated_hotpaths_use_facade_routes_without_caller_sdk_parameters(self) -> None:
        import ast
        from scripts.test_core_chat_inventory_contract import _functions, _calls, _call_name

        expected = {
            ("main.py", "get_ai_response"): ("dm_main", 1),
            ("core/combat/turn.py", "run_combat_provider_retry_stage"): ("combat_main", 3),
            ("core/combat/combat_manager.py", "summarize_dialogue"): ("combat_summary", 1),
            ("core/ai/action_handler.py", "get_ai_npc_movement_decision"): ("updates", 1),
        }
        for (path, owner_name), (task, count) in expected.items():
            owner = _functions(path)[owner_name]
            calls = _calls(owner)
            routed = [
                call for call in calls
                if _call_name(call) in {"llm.call", "dependencies.llm_call"}
            ]
            self.assertEqual(len(routed), count, path + "::" + owner_name)
            for call in routed:
                task_node = next(
                    (item.value for item in call.keywords if item.arg == "task"),
                    call.args[0] if call.args else None,
                )
                self.assertEqual(ast.literal_eval(task_node), task)
                keywords = {item.arg for item in call.keywords}
                self.assertNotIn("timeout", keywords)
                self.assertNotIn("model", keywords)
            self.assertFalse(any(
                _call_name(call).endswith("chat.completions.create")
                or _call_name(call) in {"OpenAI", "create_chat_client"}
                for call in calls
            ))


if __name__ == "__main__":
    unittest.main()
