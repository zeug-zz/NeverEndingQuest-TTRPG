# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for OpenRouter activation routing and accounting."""

from __future__ import annotations

import copy
import unittest
from typing import Any, Dict, List
from unittest import mock

from scripts.test_llm_router import ProviderTripwire, SequenceProviderClient


def _response(
    *,
    model: str,
    usage: Dict[str, Any] | None = None,
    provider: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    response: Dict[str, Any] = {
        "choices": [{"message": {"content": "provider-free response"}}],
        "model": model,
    }
    if usage is not None:
        response["usage"] = usage
    if provider is not None:
        response["provider"] = provider
    if metadata is not None:
        response["metadata"] = metadata
    return response


def _complete_usage(*, cost: Any = None) -> Dict[str, Any]:
    usage: Dict[str, Any] = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 4},
    }
    if cost is not None:
        usage["cost"] = cost
    return usage


class _BillingStatusError(RuntimeError):
    """Mimic a provider status exception whose body is not in its message."""

    status_code = 402

    def __init__(self) -> None:
        super().__init__("provider request rejected")
        self.body = {"error": {"code": "billing_hard_limit_reached"}}


class TestOpenRouterActivationContracts(unittest.TestCase):
    def setUp(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import reset_usage_stats

        reset_usage_stats()
        factory.reset_fallback_status()

    @staticmethod
    def _profiles(model: str, rates: Dict[str, float] | None = None) -> Dict[str, Any]:
        import model_config

        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = model
            profiles["production-auto"][tier]["price_per_1k"] = copy.deepcopy(rates or {})
        return profiles

    def test_openrouter_receipt_preserves_requested_resolved_and_provider_identity(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        response = _response(
            model="anthropic/claude-candidate",
            provider="anthropic",
            usage=_complete_usage(cost=0.0125),
        )
        client = SequenceProviderClient([response])
        receipts = []
        with ProviderTripwire() as tripwire:
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                with mock.patch.object(factory, "create_chat_client", return_value=client):
                    result = llm.call(
                        "dm_main", [{"role": "user", "content": "fixture"}],
                        observer=lambda receipt, raw: receipts.append((receipt, raw)),
                    )
            tripwire.assert_untouched(self)

        self.assertEqual(result, "provider-free response")
        self.assertEqual(client.calls[0]["model"], "openrouter/auto")
        self.assertEqual(len(receipts), 1)
        receipt, raw = receipts[0]
        self.assertEqual(receipt.requested_model, "openrouter/auto")
        self.assertEqual(receipt.resolved_model, "anthropic/claude-candidate")
        self.assertEqual(receipt.transport_provider, "openrouter")
        self.assertEqual(receipt.observed_upstream_provider, "anthropic")
        self.assertIs(raw, response)
        self.assertEqual(receipt.provider_reported_cost_usd, 0.0125)
        self.assertEqual(receipt.cost_usd, 0.0125)
        self.assertEqual(receipt.cost_provenance, "actual")
        self.assertTrue(receipt.cost_complete)
        stats = llm.get_usage_stats()
        self.assertEqual(stats["calls"], 1)
        self.assertEqual(stats["total_cost_usd"], 0.0125)
        self.assertEqual(stats["by_model"]["anthropic/claude-candidate"]["calls"], 1)
        self.assertEqual(stats["diagnostics"][0]["requested_model"], "openrouter/auto")
        self.assertEqual(stats["diagnostics"][0]["resolved_model"], "anthropic/claude-candidate")
        self.assertEqual(stats["diagnostics"][0]["provider"], "openrouter")
        self.assertEqual(stats["diagnostics"][0]["observed_upstream_provider"], "anthropic")
        self.assertEqual(stats["diagnostics"][0]["provider_reported_cost_usd"], 0.0125)
        self.assertEqual(stats["diagnostics"][0]["cost_usd"], 0.0125)
        self.assertEqual(stats["diagnostics"][0]["cost_provenance"], "actual")
        self.assertTrue(stats["diagnostics"][0]["cost_complete"])

    def test_reported_cost_wins_over_verified_estimate(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = self._profiles(
            "vendor/concrete",
            {"prompt": 2.0, "completion": 4.0, "cache_read": 1.0},
        )
        client = SequenceProviderClient(
            [
                _response(
                    model="vendor/concrete",
                    usage=_complete_usage(cost=0.0125),
                    metadata={"provider": "provider-from-metadata"},
                )
            ]
        )
        receipts = []
        with ProviderTripwire() as tripwire:
            with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                    with mock.patch.object(factory, "create_chat_client", return_value=client):
                        llm.call("dm_main", [], observer=lambda receipt, raw: receipts.append(receipt))
            tripwire.assert_untouched(self)

        receipt = receipts[0]
        self.assertEqual(receipt.observed_upstream_provider, "provider-from-metadata")
        self.assertEqual(receipt.provider_reported_cost_usd, 0.0125)
        self.assertEqual(receipt.cost_usd, 0.0125)
        self.assertEqual(receipt.cost_provenance, "actual")
        self.assertTrue(receipt.cost_complete)
        self.assertEqual(llm.get_usage_stats()["total_cost_usd"], 0.0125)

    def test_verified_rate_estimate_is_recorded_once_for_matching_complete_usage(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = self._profiles(
            "vendor/rated",
            {"prompt": 2.0, "completion": 4.0, "cache_read": 1.0},
        )
        client = SequenceProviderClient(
            [_response(model="vendor/rated", usage=_complete_usage())]
        )
        receipts = []
        with ProviderTripwire() as tripwire:
            with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                    with mock.patch.object(factory, "create_chat_client", return_value=client):
                        llm.call("dm_main", [], observer=lambda receipt, raw: receipts.append(receipt))
            tripwire.assert_untouched(self)

        receipt = receipts[0]
        self.assertIsNone(receipt.provider_reported_cost_usd)
        self.assertAlmostEqual(receipt.cost_usd, 0.036)
        self.assertEqual(receipt.cost_provenance, "estimated")
        self.assertTrue(receipt.usage_complete)
        self.assertTrue(receipt.cost_complete)
        stats = llm.get_usage_stats()
        self.assertAlmostEqual(stats["total_cost_usd"], 0.036)
        self.assertEqual(stats["diagnostics"][0]["provenance"], "estimated")

    def test_incomplete_usage_or_unverified_model_rate_stays_unpriced(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        cases = (
            (
                "partial usage",
                "vendor/rated",
                _response(model="vendor/rated", usage={"prompt_tokens": 10, "completion_tokens": 5}),
            ),
            (
                "different resolved model",
                "vendor/rated",
                _response(model="vendor/other", usage=_complete_usage()),
            ),
            (
                "auto is not a priced concrete model",
                "openrouter/auto",
                _response(model="vendor/selected", usage=_complete_usage()),
            ),
            ("usage absent", "vendor/rated", _response(model="vendor/rated")),
        )
        rates = {"prompt": 2.0, "completion": 4.0, "cache_read": 1.0}

        for label, configured_model, response in cases:
            with self.subTest(label=label):
                self.setUp()
                profiles = self._profiles(configured_model, rates)
                client = SequenceProviderClient([response])
                receipts = []
                with ProviderTripwire() as tripwire:
                    with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                            with mock.patch.object(factory, "create_chat_client", return_value=client):
                                llm.call("dm_main", [], observer=lambda receipt, raw: receipts.append(receipt))
                    tripwire.assert_untouched(self)

                receipt = receipts[0]
                self.assertIsNone(receipt.cost_usd)
                self.assertIsNone(receipt.provider_reported_cost_usd)
                self.assertEqual(receipt.cost_provenance, "unpriced")
                self.assertFalse(receipt.cost_complete)
                stats = llm.get_usage_stats()
                self.assertEqual(stats["unpriced_calls"], 1)
                self.assertFalse(stats["cost_complete"])
                self.assertEqual(stats["diagnostics"][0]["provenance"], "unpriced")
                self.assertIsNone(stats["diagnostics"][0]["cost_usd"])
                self.assertIsNone(stats["diagnostics"][0]["provider_reported_cost_usd"])
                self.assertFalse(stats["diagnostics"][0]["cost_complete"])

    def test_openrouter_transient_fallback_is_one_direct_gpt6_attempt_and_sanitizes_fields(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        observations: List[Any] = []
        clients: List[SequenceProviderClient] = []
        for party_size in (1, 4):
            primary = SequenceProviderClient([RuntimeError("connection reset")])
            fallback = SequenceProviderClient(
                [
                    _response(
                        model="gpt-6-luna",
                        provider="openai",
                        usage=_complete_usage(cost=0.02),
                    )
                ]
            )
            clients.extend((primary, fallback))
            receipts = []
            messages = [
                {
                    "role": "user",
                    "content": "provider-free combat fixture party_size=%d" % party_size,
                }
            ]
            with ProviderTripwire() as tripwire:
                with mock.patch.object(
                    factory,
                    "_get_actual_provider",
                    side_effect=[("openrouter", True), ("openai", False)],
                ):
                    with mock.patch.object(
                        factory, "create_chat_client", side_effect=[primary, fallback]
                    ) as create_client:
                        result = llm.call(
                            "combat_main",
                            messages,
                            provider={"order": ["vendor-a"]},
                            plugins=[{"id": "fixture-plugin"}],
                            transforms=["middle-out"],
                            models=["vendor/candidate"],
                            thinking={"type": "enabled"},
                            extra_body={"openrouter_fixture": True},
                            observer=lambda receipt, raw: receipts.append(receipt),
                        )
                tripwire.assert_untouched(self)

            self.assertEqual(result, "provider-free response")
            create_client.assert_has_calls([mock.call(), mock.call(use_fallback=True)])
            self.assertEqual(create_client.call_count, 2)
            self.assertEqual(len(primary.calls), 1)
            self.assertEqual(len(fallback.calls), 1)
            self.assertEqual(primary.calls[0]["model"], "openrouter/auto")
            self.assertIn("provider", primary.calls[0]["extra_body"])
            self.assertIn("plugins", primary.calls[0]["extra_body"])
            self.assertIn("thinking", primary.calls[0]["extra_body"])
            self.assertTrue(primary.calls[0]["extra_body"]["openrouter_fixture"])
            self.assertEqual(primary.calls[0]["models"], ["vendor/candidate"])
            self.assertEqual(primary.calls[0]["transforms"], ["middle-out"])

            direct_request = fallback.calls[0]
            self.assertEqual(direct_request["model"], "gpt-6-luna")
            for field in ("provider", "plugins", "transforms", "thinking", "extra_body", "models"):
                self.assertNotIn(field, direct_request)
            self.assertEqual([receipt.kind for receipt in receipts], ["transport_error", "response"])
            self.assertEqual(receipts[0].transport_provider, "openrouter")
            self.assertEqual(receipts[1].transport_provider, "openai")
            self.assertTrue(receipts[1].fallback)
            self.assertEqual(receipts[1].requested_model, "gpt-6-luna")
            self.assertEqual(receipts[1].resolved_model, "gpt-6-luna")
            self.assertEqual(receipts[1].observed_upstream_provider, "openai")
            observations.append((receipts[1].requested_model, receipts[1].resolved_model, len(fallback.calls)))

        self.assertEqual(observations, [("gpt-6-luna", "gpt-6-luna", 1)] * 2)
        self.assertEqual(llm.get_usage_stats()["fallbacks"], 2)
        self.assertEqual(llm.get_usage_stats()["calls"], 2)

    def test_direct_openai_primary_transient_fallback_profile_and_attempts_are_preserved(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        error = RuntimeError("connection reset")
        primary = SequenceProviderClient([error])
        fallback = SequenceProviderClient(
            [_response(model="gpt-6-luna", provider="openai", usage=_complete_usage(cost=0.02))]
        )
        receipts = []
        with ProviderTripwire() as tripwire:
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
                with mock.patch.object(
                    factory, "create_chat_client", side_effect=[primary, fallback]
                ) as create_client:
                    result = llm.call(
                        "dm_main", [], observer=lambda receipt, raw: receipts.append(receipt)
                    )
            tripwire.assert_untouched(self)

        self.assertEqual(result, "provider-free response")
        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual(primary.calls[0]["model"], "gpt-6-luna")
        self.assertEqual(fallback.calls[0]["model"], "gpt-6-luna")
        create_client.assert_has_calls([mock.call(), mock.call(use_fallback=True)])
        self.assertEqual(create_client.call_count, 2)
        self.assertEqual([receipt.kind for receipt in receipts], ["transport_error", "response"])
        self.assertEqual([receipt.attempt_number for receipt in receipts], [1, 2])
        self.assertEqual([receipt.profile for receipt in receipts], ["openai/fallback"] * 2)
        self.assertEqual([receipt.transport_provider for receipt in receipts], ["openai"] * 2)
        self.assertEqual([receipt.requested_model for receipt in receipts], ["gpt-6-luna"] * 2)
        self.assertEqual([receipt.resolved_model for receipt in receipts], ["unknown", "gpt-6-luna"])
        self.assertEqual([receipt.fallback for receipt in receipts], [False, True])
        self.assertEqual(llm.get_usage_stats()["fallbacks"], 1)

    def test_quota_and_billing_errors_are_terminal_without_fallback(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMTerminalError, llm

        for error in (RuntimeError("insufficient_quota rate limit 429"), RuntimeError("billing account disabled"), _BillingStatusError()):
            with self.subTest(error_type=type(error).__name__, error=str(error)):
                self.setUp()
                primary = SequenceProviderClient([error])
                with ProviderTripwire() as tripwire:
                    with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                        with mock.patch.object(factory, "create_chat_client", return_value=primary) as create_client:
                            with self.assertRaises(GameLLMTerminalError) as raised:
                                llm.call("dm_main", [])
                    tripwire.assert_untouched(self)

                self.assertEqual(raised.exception.terminal_kind, "quota")
                self.assertNotIn(str(error), str(raised.exception))
                self.assertEqual(len(primary.calls), 1)
                create_client.assert_called_once_with()
                self.assertEqual(llm.get_usage_stats()["fallbacks"], 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
