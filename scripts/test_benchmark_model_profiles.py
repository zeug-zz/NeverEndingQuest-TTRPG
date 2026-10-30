# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the optional live benchmark orchestration."""

import contextlib
import io
import sys
import unittest
from unittest import mock

from scripts.core_chat_test_safety import (
    arm_process_tripwires,
    install_in_memory_usage_tracker,
)

_PROCESS_TRIPWIRES = arm_process_tripwires()

from scripts import benchmark_model_profiles as benchmark


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.chat = type("Chat", (), {})()
        self.chat.completions = type("Completions", (), {})()
        self.chat.completions.create = self.create

    def with_options(self, **_kwargs):
        return self

    def create(self, **_kwargs):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def response(content, model="vendor/live-model", cost=0.001):
    return {
        "model": model,
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 2},
            "cost": cost,
        },
    }


class TestBenchmarkLiveContracts(unittest.TestCase):
    def setUp(self):
        self.usage_tracker = install_in_memory_usage_tracker(self)

    def test_default_run_is_synthetic_and_has_twelve_calls(self):
        import utils.ai_client_factory as factory

        with mock.patch.object(factory, "OpenAI", side_effect=AssertionError("live constructor")):
            report = benchmark.build_report("production-auto")
        self.assertTrue(report["synthetic"])
        self.assertEqual(sum(item["request_count"] for item in report["candidates"].values()), 12)
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(len(self.usage_tracker.records), 12)

    def test_live_requires_actual_openrouter_without_constructing_client(self):
        import utils.ai_client_factory as factory

        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client") as create:
                with self.assertRaisesRegex(RuntimeError, "configured OpenRouter"):
                    benchmark.build_live_report("production-auto")
        create.assert_not_called()

    def test_live_report_separates_fixture_and_transport_counts(self):
        import utils.ai_client_factory as factory

        fake = FakeClient([response('{"ok":true}') for _ in benchmark.FIXTURES * 2])
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", return_value=fake):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    report = benchmark.build_live_report("production-auto")
        self.assertFalse(report["synthetic"])
        self.assertEqual(report["openrouter_candidate"]["fixture_count"], 4)
        self.assertEqual(report["openrouter_candidate"]["request_count"], 4)
        self.assertEqual(report["openrouter_candidate"]["successful_response_count"], 4)
        self.assertEqual(report["direct_openai_reference"]["fixture_count"], 4)
        self.assertEqual(report["direct_openai_reference"]["request_count"], 4)
        self.assertEqual(report["network_requests"], 8)
        self.assertFalse(report["openrouter_candidate"]["cost"]["unpriced_calls"])
        self.assertEqual(report["openrouter_candidate"]["actual_models"], ["vendor/live-model"])
        self.assertEqual(report["direct_openai_reference"]["requested_models"], ["gpt-6-luna"])
        self.assertEqual(len(report["openrouter_candidate"]["latency_ms"]["samples"]), 4)

    def test_live_malformed_json_retry_reports_actual_transport_attempts(self):
        import utils.ai_client_factory as factory

        fake = FakeClient(
            [
                response("narration"),
                response("not-json"),
                response('{"ok":true}'),
                response('{"encounter":true}'),
                response("summary"),
            ]
        )
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", return_value=fake):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = benchmark._run_live_candidate("production-auto")
        self.assertEqual(result["fixture_count"], 4)
        self.assertEqual(result["request_count"], 5)
        self.assertEqual(result["successful_response_count"], 5)

    def test_constructor_failure_is_not_a_transport_and_restores_state(self):
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        before = llm.get_usage_stats()
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", side_effect=RuntimeError("constructor")):
                with self.assertRaisesRegex(RuntimeError, "constructor"):
                    benchmark.build_live_report("production-auto")
        after = llm.get_usage_stats()
        self.assertEqual(after, before)
        self.assertEqual(after["transport_attempts"], before["transport_attempts"])

    def test_live_transient_fallback_failure_is_terminal(self):
        import utils.ai_client_factory as factory

        primary = FakeClient([RuntimeError("503")])
        fallback = FakeClient([RuntimeError("503")])
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]):
                with self.assertRaisesRegex(RuntimeError, "503"):
                    benchmark.build_live_report("production-auto")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
