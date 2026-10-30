# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Regression coverage for resumed combat replay guards.
"""

import ast
import builtins
import io
import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires

PROCESS_TRIPWIRES = arm_process_tripwires()
_PRIVATE_READ_DENIALS = []


class _PrivateRootReadDenied(BaseException):
    pass


def _is_private_root_read(path):
    try:
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.parent.resolve() == Path(PROJECT_ROOT).resolve() and candidate.name in {
            "config.py", "party_tracker.json",
        }
    except (TypeError, ValueError, OSError):
        return False


def _arm_private_root_read_guard():
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def check(path, operation):
        if _is_private_root_read(path):
            _PRIVATE_READ_DENIALS.append(operation)
            raise _PrivateRootReadDenied("private root read denied: " + operation)

    def guarded_open(path, mode="r", *args, **kwargs):
        check(path, "builtins.open")
        return real_open(path, mode, *args, **kwargs)

    def guarded_io_open(path, mode="r", *args, **kwargs):
        check(path, "io.open")
        return real_io_open(path, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        check(path, "os.open")
        return real_os_open(path, flags, *args, **kwargs)

    patches = [patch("builtins.open", guarded_open), patch("io.open", guarded_io_open), patch("os.open", guarded_os_open)]
    for patcher in patches:
        patcher.start()
    return patches


PRIVATE_READ_PATCHES = _arm_private_root_read_guard()


def _load_replay_helpers():
    """Execute the actual replay functions and their complete pure closure."""
    source_path = Path(PROJECT_ROOT, "updates", "update_encounter.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names = {
        "_coerce_int", "_normalize_name_key", "_extract_expected_enemy_transitions",
        "_is_prepared_encounter_ops_replay",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise AssertionError("Replay helper source closure is incomplete")
    constants = [node for node in tree.body if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "NON_LIVING_ENEMY_STATUSES" for target in node.targets
    )]
    namespace = {"re": __import__("re"), "Any": object, "Dict": dict, "List": list}
    exec(compile(ast.Module(body=constants + nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace


_REPLAY_HELPERS = _load_replay_helpers()
_extract_expected_enemy_transitions = _REPLAY_HELPERS["_extract_expected_enemy_transitions"]
_is_prepared_encounter_ops_replay = _REPLAY_HELPERS["_is_prepared_encounter_ops_replay"]
from utils.combat_summary_history import (  # noqa: E402
    HISTORICAL_COMBAT_PREFIX,
    HISTORICAL_COMBAT_REWARD_GUARD,
    build_historical_combat_summary_message,
)


def _has_summary_helper_import(tree):
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "utils.combat_summary_history"
        and any(alias.name == "build_historical_combat_summary_message" for alias in node.names)
        for node in ast.walk(tree)
    )


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _contains_fresh_action_or_reward(block):
    forbidden_calls = {
        "update_character_info", "update_encounter", "process_action",
        "calculate_xp", "calculate_rewards", "award_experience",
    }
    for node in ast.walk(block):
        if isinstance(node, ast.Call) and _call_name(node.func) in forbidden_calls:
            return True
        if isinstance(node, ast.Dict):
            if any(isinstance(key, ast.Constant) and key.value == "action" for key in node.keys):
                return True
    return False


class TestCombatSummaryHistoryContracts(unittest.TestCase):
    def test_helper_wraps_summary_as_historical_record(self):
        message = build_historical_combat_summary_message("Combat Summary: skeleton falls.")
        self.assertIn(HISTORICAL_COMBAT_PREFIX, message)
        self.assertIn(HISTORICAL_COMBAT_REWARD_GUARD, message)
        self.assertIn("Combat Summary: skeleton falls.", message)

    def test_main_resume_path_uses_historical_summary_helper(self):
        main_path = os.path.join(PROJECT_ROOT, "main.py")
        with open(main_path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=main_path)

        self.assertTrue(_has_summary_helper_import(tree))
        summary_assignments = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "combat_summary_message" for target in node.targets)
            and isinstance(node.value, ast.Call)
            and _call_name(node.value.func) == "build_historical_combat_summary_message"
        ]
        self.assertEqual(len(summary_assignments), 1)
        self.assertEqual(len(summary_assignments[0].value.args), 1)
        self.assertIsInstance(summary_assignments[0].value.args[0], ast.Name)
        self.assertEqual(summary_assignments[0].value.args[0].id, "dialogue_summary")

        user_history_appends = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node.func) == "append"
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "conversation_history"
            and node.args and isinstance(node.args[0], ast.Dict)
            and any(isinstance(key, ast.Constant) and key.value == "role" and isinstance(value, ast.Constant) and value.value == "user"
                    for key, value in zip(node.args[0].keys, node.args[0].values))
            and any(isinstance(key, ast.Constant) and key.value == "content" and isinstance(value, ast.Name) and value.id == "combat_summary_message"
                    for key, value in zip(node.args[0].keys, node.args[0].values))
        ]
        self.assertEqual(len(user_history_appends), 1)
        enclosing_guard = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.If) and user_history_appends[0] in list(ast.walk(node))
            and isinstance(node.test, ast.Name) and node.test.id == "dialogue_summary"
        )
        self.assertFalse(_contains_fresh_action_or_reward(enclosing_guard))

    def test_action_handler_uses_same_historical_summary_helper(self):
        action_handler_path = os.path.join(PROJECT_ROOT, "core/ai/action_handler.py")
        with open(action_handler_path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=action_handler_path)

        self.assertTrue(_has_summary_helper_import(tree))
        summary_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node.func) == "build_historical_combat_summary_message"
        ]
        self.assertEqual(len(summary_calls), 1)
        self.assertEqual(len(summary_calls[0].args), 1)
        self.assertIsInstance(summary_calls[0].args[0], ast.Subscript)
        self.assertIsInstance(summary_calls[0].args[0].value, ast.Name)
        self.assertEqual(summary_calls[0].args[0].value.id, "combat_summary")
        self.assertIsInstance(summary_calls[0].args[0].slice, ast.Constant)
        self.assertEqual(summary_calls[0].args[0].slice.value, "content")

        history_appends = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node.func) == "append"
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "conversation_history"
            and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "modified_combat_summary"
        ]
        self.assertEqual(len(history_appends), 1)
        summary_guard = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.If) and history_appends[0] in list(ast.walk(node))
            and isinstance(node.test, ast.Name) and node.test.id == "combat_summary"
        )
        modified_message = next(
            node for node in ast.walk(summary_guard)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "modified_combat_summary" for target in node.targets)
            and isinstance(node.value, ast.Dict)
        )
        role_value = next(
            value for key, value in zip(modified_message.value.keys, modified_message.value.values)
            if isinstance(key, ast.Constant) and key.value == "role"
        )
        self.assertIsInstance(role_value, ast.Constant)
        self.assertEqual(role_value.value, "user")
        content_value = next(
            value for key, value in zip(modified_message.value.keys, modified_message.value.values)
            if isinstance(key, ast.Constant) and key.value == "content"
        )
        self.assertIsInstance(content_value, ast.Call)
        self.assertEqual(_call_name(content_value.func), "build_historical_combat_summary_message")
        self.assertFalse(_contains_fresh_action_or_reward(summary_guard))


class TestEncounterReplayGuard(unittest.TestCase):
    def _build_encounter(self, hp_value, status="alive"):
        return {
            "creatures": [
                {
                    "name": "Skeleton_2",
                    "type": "enemy",
                    "currentHitPoints": hp_value,
                    "status": status,
                }
            ]
        }

    def test_extract_expected_enemy_transitions_reads_hp_mirror(self):
        transitions = _extract_expected_enemy_transitions(
            "Skeleton_2 takes 9 damage from Xorn's battleaxe (HP 13->4) and is now bloodied."
        )
        self.assertEqual(transitions["skeleton 2"]["final_hp"], 4)
        self.assertEqual(transitions["skeleton 2"]["final_status"], None)

    def test_replay_guard_detects_already_applied_positive_hp_update(self):
        encounter_info = self._build_encounter(4, "alive")
        prepared_ops = [
            {"op": "hp_delta", "creature": encounter_info["creatures"][0], "delta": -9, "index": 0}
        ]
        changes = "Skeleton_2 takes 9 damage from Xorn's battleaxe (HP 13->4) and is now bloodied."

        self.assertTrue(_is_prepared_encounter_ops_replay(encounter_info, prepared_ops, changes))

    def test_replay_guard_allows_fresh_positive_hp_update(self):
        encounter_info = self._build_encounter(13, "alive")
        prepared_ops = [
            {"op": "hp_delta", "creature": encounter_info["creatures"][0], "delta": -9, "index": 0}
        ]
        changes = "Skeleton_2 takes 9 damage from Xorn's battleaxe (HP 13->4) and is now bloodied."

        self.assertFalse(_is_prepared_encounter_ops_replay(encounter_info, prepared_ops, changes))

    def test_replay_guard_detects_already_applied_kill_update(self):
        encounter_info = self._build_encounter(0, "dead")
        prepared_ops = [
            {"op": "set_hp", "creature": encounter_info["creatures"][0], "hp": 0, "index": 0},
            {"op": "set_status", "creature": encounter_info["creatures"][0], "status": "dead", "index": 1},
        ]
        changes = "Skeleton_2 takes 10 damage from Xorn (HP 4->-6) and is now dead."

        self.assertTrue(_is_prepared_encounter_ops_replay(encounter_info, prepared_ops, changes))


class TestImportSafetyProof(unittest.TestCase):
    def test_private_root_reads_and_external_capabilities_are_denied(self):
        for protected in ("config.py", "party_tracker.json"):
            target = os.path.join(PROJECT_ROOT, protected)
            for operation, attempt in (
                ("builtins.open", lambda: builtins.open(target, "r", encoding="utf-8")),
                ("io.open", lambda: io.open(target, "r", encoding="utf-8")),
                ("os.open", lambda: os.open(target, os.O_RDONLY)),
            ):
                with self.subTest(path=protected, operation=operation), self.assertRaises(_PrivateRootReadDenied):
                    attempt()
        self.assertEqual(
            _PRIVATE_READ_DENIALS,
            ["builtins.open", "io.open", "os.open"] * 2,
        )
        PROCESS_TRIPWIRES.assert_untouched(self)
        for name in ("openai.OpenAI", "socket.socket", "urlopen"):
            guard = PROCESS_TRIPWIRES.calls[name]
            with self.subTest(guard=name), self.assertRaises(TripwireFailure):
                guard()
            guard.reset_mock()
        PROCESS_TRIPWIRES.assert_untouched(self)

if __name__ == "__main__":
    unittest.main()
