# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free facade model and retry-tier contract for character updates."""

import ast
import builtins
import logging
import logging.handlers
import socket
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch


_PROJECT = Path(__file__).resolve().parents[1]
_ALLOWED_WRITE_ROOT = _PROJECT / "tmp"
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))


class _SafetyTripwire(BaseException):
    pass


def _deny_network(*args, **kwargs):
    raise _SafetyTripwire("network access is forbidden in this test")


def _guard_writes():
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            path = Path(file).resolve()
            if not path.is_relative_to(_ALLOWED_WRITE_ROOT):
                raise _SafetyTripwire(f"write outside project tmp is forbidden: {path}")
        return real_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open


_guard_writes()
socket.create_connection = _deny_network
socket.socket.connect = _deny_network
urllib.request.urlopen = _deny_network
logging.handlers.RotatingFileHandler = lambda *args, **kwargs: logging.NullHandler()

from utils import ai_client_factory
from utils.llm_router import llm
from updates import update_character_info


def _production_facade_call():
    source = (_PROJECT / "updates" / "update_character_info.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "update_character_info"
    )
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "call"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "llm"
    ]
    if len(calls) != 1:
        raise AssertionError(f"expected one facade call, found {len(calls)}")
    call = calls[0]
    if call.args or any(keyword.arg is None for keyword in call.keywords):
        raise AssertionError("facade call unexpectedly uses positional or expanded arguments")
    ast.fix_missing_locations(call)
    return compile(ast.Expression(body=call), "update_character_info_facade_call", "eval")


class _FakeFacade:
    def __init__(self):
        self.calls = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return "{}"


class CharacterUpdateModelParamsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facade_call_code = _production_facade_call()

    def _capture(self, attempt=1):
        messages = [
            {"role": "system", "content": "unchanged system prompt"},
            {"role": "user", "content": "award 50 XP"},
        ]
        facade = _FakeFacade()
        observer = object()
        namespace = {
            "llm": facade,
            "messages": messages,
            "attempt": attempt,
            "observer": observer,
        }
        result = eval(self.facade_call_code, namespace)
        self.assertEqual(result, "{}")
        self.assertEqual(len(facade.calls), 1)
        return facade.calls[0], messages, observer

    def test_update_call_uses_updates_profile_without_provider_parameters(self):
        request, messages, observer = self._capture()
        self.assertEqual(request["task"], "updates")
        self.assertEqual(request["messages"], messages)
        self.assertIs(request["json_output"], False)
        self.assertIs(request["observer"], observer)
        self.assertIsNone(request["retry_tier"])
        self.assertFalse(
            {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(
                request
            )
        )

    def test_retry_tier_is_preserved_for_later_caller_attempts(self):
        first, _, _ = self._capture(attempt=1)
        retry, _, _ = self._capture(attempt=2)
        self.assertIsNone(first["retry_tier"])
        self.assertEqual(retry["retry_tier"], "retry")

    def test_character_helper_keeps_legacy_model_source_while_router_uses_auto(self):
        profile = llm.resolve_profile("updates")
        self.assertEqual(profile["provider_name"], "openrouter")
        self.assertEqual(profile["model"], "openrouter/auto")
        configured_model = ai_client_factory.get_chat_model_name()
        self.assertEqual(update_character_info.get_model_for_character("player"), configured_model)
        self.assertEqual(update_character_info.get_model_for_character("npc"), configured_model)

    def test_no_direct_chat_transport_remains_in_character_update(self):
        source = (_PROJECT / "updates" / "update_character_info.py").read_text(encoding="utf-8")
        self.assertNotIn("chat.completions.create", source)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("get_chat_completion_params", source)


if __name__ == "__main__":
    unittest.main()
