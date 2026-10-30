#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider-free regression tests for action predictor GPT-5 parameter parity.

Discovered during the Jev Phase 0 spike: predict_actions_required() passed a
legacy temperature value directly to the direct-OpenAI GPT-5.6 Luna endpoint,
which rejects it, causing every call to fall through to the conservative
"requires_actions: True" error fallback.
"""

from __future__ import annotations

import json
import ast
import builtins
import io
import os
import sys
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires  # noqa: E402


# Arm fatal transport and write guards before importing any project owners.
PROCESS_TRIPWIRES = arm_process_tripwires()


class _PrivateRootReadDenied(BaseException):
    """Fatal sentinel for reads of private root configuration/runtime fixtures."""


def _is_private_root_read(path: Any) -> bool:
    try:
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate.parent.resolve() == REPO_ROOT.resolve() and candidate.name in {
            "config.py",
            "party_tracker.json",
        }
    except (TypeError, ValueError, OSError):
        return False


def _arm_private_root_read_guard():
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    denied = []

    def check(path, operation):
        if _is_private_root_read(path):
            denied.append(operation)
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

    patches = [
        mock.patch("builtins.open", guarded_open),
        mock.patch("io.open", guarded_io_open),
        mock.patch("os.open", guarded_os_open),
    ]
    for patcher in patches:
        patcher.start()
    return patches, denied


PRIVATE_READ_PATCHES, PRIVATE_READ_DENIALS = _arm_private_root_read_guard()

# These are public, checked-in model settings. The private config fixture is
# deliberately never opened; all root configuration names come from this
# public module and keys are replaced with nonempty sentinels.
import model_config  # noqa: E402
from utils import ai_client_factory  # noqa: E402


def _load_action_predictor_function():
    """Execute the actual predictor function and prompt without module init."""
    source_path = REPO_ROOT / "utils" / "action_predictor.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "predict_actions_required":
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ACTION_PREDICTION_PROMPT"
            for target in node.targets
        ):
            selected.append(node)
    if len(selected) != 2:
        raise AssertionError("actual predictor function/prompt source closure is incomplete")

    class _InertCompletions:
        def create(self, **kwargs):
            raise TripwireFailure("unexpected unpatched action prediction request")

    inert_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_InertCompletions())
    )
    namespace = {
        "json": json,
        "llm": types.SimpleNamespace(call=lambda **kwargs: ""),
        "ACTION_PREDICTION_MODEL": model_config.ACTION_PREDICTION_MODEL,
        "get_chat_completion_params": ai_client_factory.get_chat_completion_params,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec"), namespace)
    return source, namespace, inert_client


ACTION_PREDICTOR_SOURCE, ACTION_PREDICTOR_NAMESPACE, ACTION_PREDICTOR_CLIENT = (
    _load_action_predictor_function()
)


def _fake_response(content: str) -> Any:
    message = mock.MagicMock()
    message.content = content
    choice = mock.MagicMock()
    choice.message = message
    response = mock.MagicMock()
    response.choices = [choice]
    return response


class TestActionPredictorParamsContract(unittest.TestCase):
    def test_source_routes_through_facade(self) -> None:
        self.assertIn('task="action_prediction"', ACTION_PREDICTOR_SOURCE)
        self.assertIn("json_output=False", ACTION_PREDICTOR_SOURCE)
        self.assertNotIn("chat.completions.create", ACTION_PREDICTOR_SOURCE)

    def test_harness_loads_actual_function_without_private_config_or_owner_init(self) -> None:
        with self.assertRaises(_PrivateRootReadDenied):
            builtins.open(REPO_ROOT / "config.py", "r", encoding="utf-8")
        with self.assertRaises(_PrivateRootReadDenied):
            (REPO_ROOT / "party_tracker.json").read_text(encoding="utf-8")
        with self.assertRaises(_PrivateRootReadDenied):
            os.open(REPO_ROOT / "config.py", os.O_RDONLY)
        self.assertTrue(callable(ACTION_PREDICTOR_NAMESPACE["llm"].call))
        self.assertEqual(
            ACTION_PREDICTOR_NAMESPACE["ACTION_PREDICTION_MODEL"],
            model_config.ACTION_PREDICTION_MODEL,
        )
        self.assertTrue(ACTION_PREDICTOR_NAMESPACE["ACTION_PREDICTION_PROMPT"])
        self.assertEqual(
            PRIVATE_READ_DENIALS,
            ["builtins.open", "io.open", "os.open"],
        )
        PROCESS_TRIPWIRES.assert_untouched(self)
        for name in ("openai.OpenAI", "socket.socket", "urlopen"):
            guard = PROCESS_TRIPWIRES.calls[name]
            with self.subTest(guard=name), self.assertRaises(TripwireFailure):
                guard()
            guard.reset_mock()
        PROCESS_TRIPWIRES.assert_untouched(self)

    def test_gpt5_request_omits_temperature(self) -> None:
        response_text = json.dumps({"requires_actions": True, "reason": "movement"})
        with mock.patch.object(ACTION_PREDICTOR_NAMESPACE["llm"], "call", return_value=response_text) as call:
            result = ACTION_PREDICTOR_NAMESPACE["predict_actions_required"]("I go to the tavern.")
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["task"], "action_prediction")
        self.assertIs(kwargs["json_output"], False)
        self.assertEqual(kwargs["messages"][1]["content"], "Analyze this user input: 'I go to the tavern.'")
        self.assertFalse({"model", "temperature", "timeout", "client"}.intersection(kwargs))
        self.assertTrue(result["requires_actions"])

    def test_prediction_contract_preserved(self) -> None:
        with mock.patch.object(ACTION_PREDICTOR_NAMESPACE["llm"], "call", return_value=json.dumps({"requires_actions": False, "reason": "pure dialogue"})):
            result = ACTION_PREDICTOR_NAMESPACE["predict_actions_required"]("I say hello.")
        self.assertEqual(
            sorted(result.keys()),
            ["confidence", "reason", "requires_actions"],
        )
        self.assertFalse(result["requires_actions"])

    def test_error_fallback_remains_conservative(self) -> None:
        with mock.patch.object(ACTION_PREDICTOR_NAMESPACE["llm"], "call", side_effect=RuntimeError("provider down")):
            result = ACTION_PREDICTOR_NAMESPACE["predict_actions_required"]("I open the door.")
        self.assertTrue(result["requires_actions"])
        self.assertEqual(result["confidence"], "error")


def _dummy_config_fixture():
    fixture = types.ModuleType("config")
    for name in dir(model_config):
        if name.isupper() and not name.startswith("_"):
            setattr(fixture, name, getattr(model_config, name))
    fixture.OPENAI_API_KEY = "DUMMY_OPENAI_KEY_FOR_PARAMETER_CONTRACT"
    fixture.OPENROUTER_API_KEY = "DUMMY_OPENROUTER_KEY_FOR_PARAMETER_CONTRACT"
    return fixture


if __name__ == "__main__":
    unittest.main(verbosity=2)
