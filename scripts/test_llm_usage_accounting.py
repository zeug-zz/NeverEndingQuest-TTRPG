# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for router receipt reconciliation in session/week usage."""

import unittest
from unittest import mock

import utils.llm_router as router_module
import utils.llm_usage_tracker as tracker_module
from utils.llm_runtime import make_legacy_receipt_observer
from utils.llm_usage_tracker import LLMUsageTracker, track_image_cost


def _offline_tracker():
    """Create a tracker without importing local config or making network calls."""
    def load_test_config(tracker):
        tracker.usd_to_nzd_rate = 1.0
        tracker.week_window_days = 7
        tracker.fallback_rate = 1.5
        tracker.usd_to_nzd_source = "test"
        tracker.exchange_configured_currency = "USD"
        tracker.exchange_effective_currency = "USD"
        tracker.exchange_fallback_rate = 1.0

    with mock.patch.object(LLMUsageTracker, "_load_config", load_test_config):
        return LLMUsageTracker(telemetry_log="/dev/null")


def _response(model, usage):
    return {"model": model, "usage": usage}


def _receipt(index, profile, response):
    return router_module.LLMRouter._receipt(
        kind="response",
        call_id="call-%s" % index,
        attempt_id="attempt-%s" % index,
        attempt_number=1,
        task="dm_main",
        profile=profile,
        fallback=False,
        started_at=None,
        retry_tier=None,
        response=response,
    )


class LLMUsageAccountingTests(unittest.TestCase):
    def test_tracker_counts_a_receipt_attempt_once_even_if_redelivered(self):
        tracker = _offline_tracker()
        response = {
            "usage": {
                "prompt_tokens": 4,
                "completion_tokens": 2,
                "total_tokens": 11,
                "cost": 0.0,
            }
        }
        context = {
            "call_id": "call-dedup",
            "attempt_id": "attempt-dedup",
            "cost_provenance": "actual",
            "cost_usd": 0.0,
            "cost_complete": True,
        }

        tracker.track(response, context)
        tracker.track(response, context)

        stats = tracker.get_current_stats()
        self.assertEqual(stats["session_requests"], 1)
        self.assertEqual(stats["session_tokens"], 11)
        self.assertEqual(stats["session_prompt_tokens"], 4)
        self.assertEqual(stats["session_completion_tokens"], 2)
        self.assertEqual(stats["session_cost_actual_usd"], 0.0)

    def test_router_receipts_reconcile_once_and_unpriced_keeps_tokens(self):
        tracker = _offline_tracker()
        # If the receipt is ignored, this legacy estimate would make the
        # unpriced response look priceable and greatly inflate the total.
        tracker.fallback_rate = 1000.0
        observer = make_legacy_receipt_observer(tracker_getter=lambda: tracker)
        profile = {
            "model": "vendor/model",
            "provider_name": "openrouter",
            "profile": "verified-profile",
            "tier": "complex",
            "price_per_1k": {"prompt": 2.0, "completion": 4.0},
        }
        responses = [
            _response(
                "vendor/model",
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "cost": 0.0,
                },
            ),
            _response(
                "vendor/model",
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            ),
            _response(
                "resolved-other",
                {
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            ),
            _response("vendor/model", None),
        ]
        receipts = [_receipt(index, profile, raw) for index, raw in enumerate(responses)]
        self.assertEqual(
            [receipt.cost_provenance for receipt in receipts],
            ["actual", "estimated", "unpriced", "unpriced"],
        )
        self.assertEqual(receipts[0].cost_usd, 0.0)
        self.assertAlmostEqual(receipts[1].cost_usd, 0.04)
        self.assertIsNone(receipts[2].cost_usd)

        for receipt, raw in zip(receipts, responses):
            observer(receipt, raw)
            observer(receipt, raw)

        stats = tracker.get_current_stats()
        self.assertEqual(stats["session_requests"], 4)
        self.assertEqual(stats["session_tokens"], 40)
        self.assertEqual(stats["session_prompt_tokens"], 28)
        self.assertEqual(stats["session_completion_tokens"], 12)
        self.assertEqual(stats["session_cost_actual_usd"], 0.0)
        self.assertAlmostEqual(stats["session_cost_estimated_usd"], 0.04)
        self.assertAlmostEqual(stats["session_cost_usd"], 0.04)
        self.assertEqual(stats["session_unpriced_calls"], 2)
        self.assertFalse(stats["session_cost_complete"])
        self.assertEqual(stats["week_tokens"], 40)
        self.assertEqual(stats["week_cost_actual_usd"], 0.0)
        self.assertAlmostEqual(stats["week_cost_estimated_usd"], 0.04)
        self.assertAlmostEqual(stats["week_cost_usd"], 0.04)
        self.assertEqual(stats["week_unpriced_calls"], 2)
        self.assertFalse(stats["week_cost_complete"])

    def test_cost_only_media_remains_outside_chat_token_totals(self):
        tracker = _offline_tracker()
        tracker.track(
            {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "cost": 0.01}}
        )
        before = tracker.get_current_stats()

        with mock.patch.object(tracker_module, "_global_tracker", tracker):
            self.assertTrue(track_image_cost(cost_usd=0.05, context={"purpose": "portrait"}))

        after = tracker.get_current_stats()
        self.assertEqual(after["session_tokens"], before["session_tokens"])
        self.assertEqual(after["session_prompt_tokens"], before["session_prompt_tokens"])
        self.assertEqual(after["session_completion_tokens"], before["session_completion_tokens"])
        self.assertEqual(after["session_requests"], before["session_requests"])
        self.assertAlmostEqual(after["session_cost_usd"], before["session_cost_usd"] + 0.05)
        self.assertAlmostEqual(after["session_cost_actual_usd"], 0.01)
        self.assertAlmostEqual(after["session_cost_estimated_usd"], 0.05)
        self.assertEqual(after["week_tokens"], before["week_tokens"])
        self.assertAlmostEqual(after["week_cost_usd"], before["week_cost_usd"] + 0.05)

    def test_legacy_tracker_calls_keep_the_blended_estimator(self):
        tracker = _offline_tracker()
        tracker.track(
            {"usage": {"prompt_tokens": 600, "completion_tokens": 400, "total_tokens": 1000}},
            context={"endpoint": "legacy"},
        )

        stats = tracker.get_current_stats()
        self.assertAlmostEqual(stats["session_cost_usd"], 0.0015)
        self.assertAlmostEqual(stats["session_cost_estimated_usd"], 0.0015)
        self.assertEqual(stats["session_unpriced_calls"], 0)
        self.assertTrue(stats["session_cost_complete"])
        self.assertEqual(stats["session_requests"], 1)


if __name__ == "__main__":
    unittest.main()
