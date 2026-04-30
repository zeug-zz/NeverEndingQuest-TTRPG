# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
GPT-5.4-mini chat parameter shim contract tests.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.ai_client_factory as ai_client_factory


class TestGPT54MiniChatParamsShim(unittest.TestCase):
    def setUp(self) -> None:
        self._legacy_temperature_flag = ai_client_factory.GPT5_INCLUDE_LEGACY_TEMPERATURE
        self._actual_provider = ai_client_factory._get_actual_provider

    def tearDown(self) -> None:
        ai_client_factory.GPT5_INCLUDE_LEGACY_TEMPERATURE = self._legacy_temperature_flag
        ai_client_factory._get_actual_provider = self._actual_provider

    def test_gpt5_dm_main_omits_legacy_sampling_controls(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-5.4-mini-2026-03-17",
            temperature_override=0.7,
        )

        self.assertEqual(params["model"], "gpt-5.4-mini-2026-03-17")
        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_gpt5_validation_prefers_low_reasoning_and_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_validation",
            "gpt-5.4-mini-2026-03-17",
            temperature_override=0.1,
        )

        self.assertEqual(params["reasoning_effort"], "low")
        self.assertEqual(params["verbosity"], "low")
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_non_gpt5_preserves_temperature(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-4.1-2025-04-14",
            temperature_override=0.42,
        )

        self.assertEqual(params["model"], "gpt-4.1-2025-04-14")
        self.assertEqual(params["temperature"], 0.42)
        self.assertNotIn("reasoning_effort", params)
        self.assertNotIn("verbosity", params)

    def test_rollback_flag_can_restore_legacy_temperature(self) -> None:
        ai_client_factory.GPT5_INCLUDE_LEGACY_TEMPERATURE = True

        params = ai_client_factory.get_chat_completion_params(
            "combat_main",
            "gpt-5.4-mini-2026-03-17",
            temperature_override=0.8,
        )

        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")
        self.assertEqual(params["temperature"], 0.8)

    def test_openrouter_passthrough_keeps_existing_extra_body_shape(self) -> None:
        ai_client_factory._get_actual_provider = lambda use_fallback=False: ("openrouter", True)

        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-4.1-2025-04-14",
            temperature_override=0.7,
        )

        self.assertEqual(params["temperature"], 0.7)
        if "extra_body" in params:
            self.assertEqual(params["extra_body"]["thinking"]["type"], "enabled")
        else:
            self.assertEqual(params["thinking"]["type"], "enabled")

    def test_hotpath_files_now_use_chat_param_helper(self) -> None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(os.path.join(root, "main.py"), "r", encoding="utf-8") as handle:
            main_text = handle.read()
        with open(
            os.path.join(root, "core", "managers", "combat_manager.py"),
            "r",
            encoding="utf-8",
        ) as handle:
            combat_text = handle.read()
        with open(
            os.path.join(root, "core", "ai", "action_handler.py"),
            "r",
            encoding="utf-8",
        ) as handle:
            action_text = handle.read()

        self.assertIn("get_chat_completion_params", main_text)
        self.assertIn("get_chat_completion_params", combat_text)
        self.assertIn("get_chat_completion_params", action_text)


if __name__ == "__main__":
    unittest.main()
