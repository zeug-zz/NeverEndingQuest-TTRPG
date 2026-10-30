# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free source and ownership contracts for router cleanup."""

import ast
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.core_chat_test_safety import arm_process_tripwires

PROCESS_TRIPWIRES = arm_process_tripwires()

import model_config
from utils import ai_client_factory


def tearDownModule() -> None:
    """Fail the process if a real provider or network surface was reached."""
    PROCESS_TRIPWIRES.assert_untouched(unittest.TestCase())


class TestLLMRouterCleanup(unittest.TestCase):
    def test_removed_selector_data_and_helpers_are_absent(self) -> None:
        unused_model_registry_name = "AVAILABLE_" + "MODELS"
        self.assertFalse(hasattr(model_config, unused_model_registry_name))
        legacy_alias_name = "THINKING_ENABLED_" + "TASKS"
        self.assertFalse(hasattr(model_config, legacy_alias_name))

        removed_helpers = (
            "is_thinking_" + "enabled",
            "get_task_" + "complexity",
            "get_model_for_" + "task",
        )
        for helper_name in removed_helpers:
            with self.subTest(helper=helper_name):
                self.assertFalse(hasattr(ai_client_factory, helper_name))

        migration_script = REPO_ROOT / "scripts" / ("migrate_to_" + "openrouter.py")
        self.assertFalse(migration_script.exists())

    def test_active_selection_and_factory_ownership_remain(self) -> None:
        self.assertEqual(
            model_config.COMPLEX_TASKS,
            [
                "dm_main",
                "dm_validation",
                "combat_main",
                "action_prediction",
                "character_validator",
                "npc_builder",
                "monster_builder",
                "level_up",
                "dm_full",
                "location_compression",
            ],
        )

        for constant in (
            "OPENROUTER_STRATEGY",
            "OPENROUTER_CHAT_MODEL",
            "OPENROUTER_FULL_MODEL",
            "OPENROUTER_MINI_MODEL",
        ):
            with self.subTest(constant=constant):
                self.assertTrue(hasattr(model_config, constant))

        for owner in (
            "get_model_config",
            "get_chat_model_name",
            "create_chat_client",
            "_get_actual_provider",
            "finalize_chat_params",
            "handle_provider_error",
            "get_fallback_notification",
            "reset_fallback_status",
        ):
            with self.subTest(owner=owner):
                self.assertTrue(callable(getattr(ai_client_factory, owner)))

        with mock.patch.object(
            ai_client_factory,
            "_get_actual_provider",
            return_value=("openrouter", True),
        ):
            with mock.patch.object(model_config, "OPENROUTER_STRATEGY", "kimi_thinking"):
                complex_result = ai_client_factory.get_model_config("dm_main")
                simple_result = ai_client_factory.get_model_config("summaries")

            with mock.patch.object(model_config, "OPENROUTER_STRATEGY", "dual_model"):
                complex_model = ai_client_factory.get_model_config("dm_main")["model"]
                simple_model = ai_client_factory.get_model_config("summaries")["model"]

        self.assertEqual(
            complex_result["extra_body"]["extra_body"]["thinking"]["type"],
            "enabled",
        )
        self.assertEqual(
            simple_result["extra_body"]["extra_body"]["thinking"]["type"],
            "disabled",
        )
        self.assertEqual(complex_model, model_config.OPENROUTER_FULL_MODEL)
        self.assertEqual(simple_model, model_config.OPENROUTER_MINI_MODEL)

    def test_main_does_not_import_unused_display_helper(self) -> None:
        source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "utils.ai_client_factory"
            for alias in node.names
        }
        self.assertNotIn("get_chat_model_name", imported_names)


if __name__ == "__main__":
    unittest.main()
