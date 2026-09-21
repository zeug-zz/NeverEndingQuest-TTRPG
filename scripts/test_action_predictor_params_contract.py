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
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utils import action_predictor  # noqa: E402


def _fake_response(content: str) -> Any:
    message = mock.MagicMock()
    message.content = content
    choice = mock.MagicMock()
    choice.message = message
    response = mock.MagicMock()
    response.choices = [choice]
    return response


class TestActionPredictorParamsContract(unittest.TestCase):
    def test_source_routes_through_factory_shim(self) -> None:
        source = (REPO_ROOT / "utils" / "action_predictor.py").read_text(encoding="utf-8")
        self.assertIn("get_chat_completion_params(", source)
        self.assertNotIn("temperature=0.1,  # Low temperature for consistent predictions\n", source)

    def test_gpt5_request_omits_temperature(self) -> None:
        fake = _fake_response(json.dumps({"requires_actions": True, "reason": "movement"}))
        with mock.patch.object(action_predictor.client.chat.completions, "create", return_value=fake) as create:
            result = action_predictor.predict_actions_required("I go to the tavern.")
        kwargs = create.call_args.kwargs
        self.assertNotIn("temperature", kwargs)
        self.assertTrue(kwargs.get("model"))
        self.assertIn("messages", kwargs)
        self.assertTrue(result["requires_actions"])

    def test_prediction_contract_preserved(self) -> None:
        fake = _fake_response(json.dumps({"requires_actions": False, "reason": "pure dialogue"}))
        with mock.patch.object(action_predictor.client.chat.completions, "create", return_value=fake):
            result = action_predictor.predict_actions_required("I say hello.")
        self.assertEqual(
            sorted(result.keys()),
            ["confidence", "reason", "requires_actions"],
        )
        self.assertFalse(result["requires_actions"])

    def test_error_fallback_remains_conservative(self) -> None:
        with mock.patch.object(
            action_predictor.client.chat.completions,
            "create",
            side_effect=RuntimeError("provider down"),
        ):
            result = action_predictor.predict_actions_required("I open the door.")
        self.assertTrue(result["requires_actions"])
        self.assertEqual(result["confidence"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
