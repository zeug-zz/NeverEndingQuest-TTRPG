# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Focused launch-reset contract tests; never invoke application loops."""

import ast
import hashlib
import importlib
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

from scripts.core_chat_test_safety import arm_process_tripwires


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _function(source, name):
    tree = ast.parse(source)
    return next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


class RuntimeLaunchResetTests(unittest.TestCase):
    def test_helper_lazily_resets_only_the_two_existing_session_apis(self):
        with tempfile.TemporaryDirectory(
            prefix="llm-runtime-week-ledger-", dir=ROOT / "tmp"
        ) as scratch:
            events = []
            ledger = pathlib.Path(scratch) / "week-ledger.json"
            ledger.write_bytes(b'{"week_tokens":4321,"events":["historical"]}\n')
            fake_router = types.ModuleType("utils.llm_router")
            fake_router.reset_usage_stats = lambda: events.append("router")
            fake_factory = types.ModuleType("utils.ai_client_factory")
            fake_factory.reset_fallback_status = lambda: events.append("fallback")
            fake_usage_tracker = types.ModuleType("utils.llm_usage_tracker")
            fake_usage_tracker.reset = lambda: events.append("week-ledger-reset")

            tripwires = arm_process_tripwires()
            utils_package = importlib.import_module("utils")
            old_router_attr = getattr(utils_package, "llm_router", None)
            had_router_attr = hasattr(utils_package, "llm_router")
            utils_package.llm_router = fake_router
            sys.modules.pop("utils.llm_runtime", None)
            try:
                with mock.patch.dict(
                    sys.modules,
                    {
                        "utils.llm_router": fake_router,
                        "utils.ai_client_factory": fake_factory,
                        "utils.llm_usage_tracker": fake_usage_tracker,
                    },
                ):
                    runtime = importlib.import_module("utils.llm_runtime")
                    self.assertEqual(events, [])
                    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
                    runtime.begin_llm_session()
                    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
            finally:
                sys.modules.pop("utils.llm_runtime", None)
                if had_router_attr:
                    utils_package.llm_router = old_router_attr
                else:
                    del utils_package.llm_router
                tripwires.assert_untouched(self)
                for patcher in reversed(tripwires.patchers):
                    patcher.stop()

            self.assertEqual(events, ["router", "fallback"])
            self.assertEqual(before, after)

    def test_launch_sites_reset_once_before_setup_or_hydration(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        web_source = (ROOT / "web" / "web_interface.py").read_text(
            encoding="utf-8"
        )
        main_fn = _function(main_source, "main")
        web_fn = _function(web_source, "run_game_loop")

        def ordered_names(fn):
            return [
                node.value.func.id
                for node in fn.body
                if isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
            ]

        self.assertEqual(ordered_names(main_fn)[:2], ["begin_llm_session", "setup_utf8_console"])
        self.assertEqual(ordered_names(web_fn)[:1], ["begin_llm_session"])
        self.assertEqual(main_source.count("begin_llm_session()"), 1)
        self.assertEqual(web_source.count("begin_llm_session()"), 1)
        self.assertNotIn("reset_fallback_status()  # Reset fallback tracking at module load", main_source)
        self.assertIn("reset_fallback_status,", main_source)

    def test_recursive_restore_loop_does_not_reset_runtime(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        main_loop = _function(main_source, "main_game_loop")
        self.assertFalse(
            any(
                isinstance(node, ast.Name) and node.id == "begin_llm_session"
                for node in ast.walk(main_loop)
            )
        )
        self.assertIn('elif final_result == "restart":', main_source)
        self.assertIn("main_game_loop()", main_source)


if __name__ == "__main__":
    unittest.main()
