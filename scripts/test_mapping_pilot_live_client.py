# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the D1 live-client router adapter."""

from __future__ import annotations

import hashlib
import json
import pathlib
import socket
import sys
import unittest
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot.live_client import (
    ROUTER_TASK,
    LiveClientPreflightError,
    create_live_client,
)


_PROFILE = {
    "profile": "production-auto",
    "provider_name": "openrouter",
    "is_openrouter": True,
    "model": "openrouter/auto",
    "explicit_model": False,
}


class _FakeRouter:
    def __init__(self, profile: Optional[dict[str, Any]] = None) -> None:
        self.profile = dict(profile or _PROFILE)
        self.resolved_tasks: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.result: Any = {"layout_type": "locations", "locations": []}
        self.error: Optional[Exception] = None
        self.receipt: Any = None
        self.raw_response: Any = None

    def resolve_profile(self, task: str) -> dict[str, Any]:
        self.resolved_tasks.append(task)
        return dict(self.profile)

    def call(
        self,
        task: str,
        messages: Any,
        json_output: bool = False,
        *,
        observer: Any = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "task": task,
                "messages": messages,
                "json_output": json_output,
                "kwargs": dict(kwargs),
            }
        )
        if observer is not None and self.receipt is not None:
            observer(self.receipt, self.raw_response)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeQuotaError(RuntimeError):
    def __init__(self) -> None:
        self.terminal_kind = "quota"
        super().__init__("PRIVATE_ERROR_TEXT_DO_NOT_STORE")


class MappingPilotLiveClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connect_guard = patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network access prohibited in this test"),
        )
        self.connect_guard.start()
        self.addCleanup(self.connect_guard.stop)

    def test_production_auto_preflight_and_json_text_response(self) -> None:
        router = _FakeRouter()
        receipts: list[dict[str, Any]] = []
        client = create_live_client(receipts, router=router)

        self.assertEqual(router.resolved_tasks, [ROUTER_TASK])
        self.assertEqual(router.calls, [])
        prompt = "PROMPT_SECRET_DO_NOT_STORE"
        result = client(prompt)

        self.assertEqual(
            result,
            '{"layout_type":"locations","locations":[]}',
        )
        self.assertEqual(router.resolved_tasks, [ROUTER_TASK, ROUTER_TASK])
        self.assertEqual(len(router.calls), 1)
        self.assertEqual(router.calls[0]["task"], "location_generator")
        self.assertEqual(router.calls[0]["json_output"], True)
        self.assertEqual(
            router.calls[0]["messages"],
            [{"role": "user", "content": prompt}],
        )
        self.assertEqual(router.calls[0]["kwargs"], {})
        self.assertEqual(receipts, [])

    def test_non_production_auto_profile_is_refused_before_router_call(self) -> None:
        router = _FakeRouter({**_PROFILE, "profile": "titan-auto"})
        receipts: list[dict[str, Any]] = []

        with self.assertRaises(LiveClientPreflightError) as raised:
            create_live_client(receipts, router=router)

        self.assertEqual(raised.exception.observed_profile, "titan-auto")
        self.assertIn("observed profile=titan-auto", str(raised.exception))
        self.assertEqual(router.calls, [])
        self.assertEqual(receipts, [])

    def test_model_pin_is_refused_even_when_profile_label_matches(self) -> None:
        router = _FakeRouter({**_PROFILE, "model": "vendor/pinned-model"})

        with self.assertRaises(LiveClientPreflightError) as raised:
            create_live_client([], router=router)

        self.assertEqual(raised.exception.observed_profile, "production-auto")
        self.assertEqual(raised.exception.reason, "model_not_auto")
        self.assertEqual(router.calls, [])

    def test_receipt_allowlist_unknowns_and_response_privacy(self) -> None:
        router = _FakeRouter()
        router.result = {"area": "The Keep"}
        router.receipt = SimpleNamespace(
            kind="response",
            call_id="call-1",
            attempt_id="attempt-1",
            attempt_number=1,
            task=ROUTER_TASK,
            tier="simple",
            profile="production-auto",
            transport_retry=False,
            retry_tier=None,
            fallback=False,
            transport_provider="openrouter",
            observed_upstream_provider="provider-x",
            requested_model="openrouter/auto",
            resolved_model="vendor/actual-model",
            prompt_tokens=12,
            cached_tokens=0,
            completion_tokens=6,
            usage_complete=True,
            provider_reported_cost_usd=0.0,
            cost_usd=0.0,
            cost_provenance="actual",
            cost_complete=True,
            error_type=None,
            elapsed_ms=14.5,
            stats_snapshot={"must_not_be_copied": "stats"},
        )
        router.raw_response = {"content": "RAW_RESPONSE_DO_NOT_STORE"}
        receipts: list[dict[str, Any]] = []
        client = create_live_client(receipts, router=router)
        prompt = "PROMPT_SECRET_DO_NOT_STORE"

        self.assertEqual(client(prompt), '{"area":"The Keep"}')
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        self.assertEqual(
            set(receipt),
            {
                "invocation_index",
                "prompt_sha256",
                "kind",
                "call_id",
                "attempt_id",
                "attempt_index",
                "task",
                "tier",
                "profile",
                "transport_retry",
                "retry_tier",
                "fallback",
                "transport_provider",
                "observed_upstream_provider",
                "requested_model",
                "resolved_model",
                "prompt_tokens",
                "cached_tokens",
                "completion_tokens",
                "usage_complete",
                "provider_reported_cost_usd",
                "cost_usd",
                "cost_provenance",
                "cost_complete",
                "error_type",
                "terminal_kind",
                "elapsed_ms",
            },
        )
        self.assertEqual(receipt["prompt_sha256"], hashlib.sha256(prompt.encode()).hexdigest())
        self.assertEqual(receipt["prompt_tokens"], 12)
        self.assertEqual(receipt["cached_tokens"], 0)
        self.assertEqual(receipt["provider_reported_cost_usd"], 0.0)
        self.assertEqual(receipt["cost_usd"], 0.0)
        self.assertEqual(receipt["resolved_model"], "vendor/actual-model")
        self.assertIsNone(receipt["terminal_kind"])
        serialized = json.dumps(receipts, ensure_ascii=True)
        self.assertNotIn(prompt, serialized)
        self.assertNotIn("RAW_RESPONSE_DO_NOT_STORE", serialized)
        self.assertNotIn("must_not_be_copied", serialized)

    def test_unknown_receipt_fields_remain_unknown_not_zero(self) -> None:
        router = _FakeRouter()
        router.receipt = {"kind": "response", "resolved_model": "openrouter/auto"}
        receipts: list[dict[str, Any]] = []
        client = create_live_client(receipts, router=router)

        client("safe prompt")

        receipt = receipts[0]
        self.assertEqual(receipt["resolved_model"], "unknown")
        self.assertEqual(receipt["requested_model"], "unknown")
        self.assertEqual(receipt["observed_upstream_provider"], "unknown")
        self.assertEqual(receipt["fallback"], "unknown")
        self.assertIsNone(receipt["prompt_tokens"])
        self.assertIsNone(receipt["completion_tokens"])
        self.assertIsNone(receipt["cost_usd"])
        self.assertIsNone(receipt["elapsed_ms"])

    def test_provider_error_receipt_has_no_invented_terminal_kind(self) -> None:
        router = _FakeRouter()
        router.receipt = {
            "kind": "transport_error",
            "profile": "production-auto",
            "requested_model": "openrouter/auto",
            "error_type": "ProviderConnectionError",
        }
        router.error = RuntimeError("PRIVATE_ERROR_TEXT_DO_NOT_STORE")
        router.raw_response = {"secret": "RAW_ERROR_RESPONSE_DO_NOT_STORE"}
        receipts: list[dict[str, Any]] = []
        client = create_live_client(receipts, router=router)

        with self.assertRaises(RuntimeError):
            client("PROMPT_ERROR_DO_NOT_STORE")

        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["kind"], "transport_error")
        self.assertEqual(receipts[0]["error_type"], "ProviderConnectionError")
        self.assertIsNone(receipts[0]["terminal_kind"])
        serialized = json.dumps(receipts, ensure_ascii=True)
        self.assertNotIn("PROMPT_ERROR_DO_NOT_STORE", serialized)
        self.assertNotIn("RAW_ERROR_RESPONSE_DO_NOT_STORE", serialized)
        self.assertNotIn("PRIVATE_ERROR_TEXT_DO_NOT_STORE", serialized)

    def test_quota_failure_keeps_error_receipt_and_terminal_kind(self) -> None:
        router = _FakeRouter()
        router.receipt = SimpleNamespace(
            kind="transport_error",
            call_id="call-quota",
            attempt_id="attempt-quota",
            attempt_number=1,
            task=ROUTER_TASK,
            tier="simple",
            profile="production-auto",
            fallback=False,
            transport_provider="openrouter",
            observed_upstream_provider="unknown",
            requested_model="openrouter/auto",
            resolved_model="unknown",
            prompt_tokens=None,
            cached_tokens=None,
            completion_tokens=None,
            usage_complete=False,
            provider_reported_cost_usd=None,
            cost_usd=None,
            cost_provenance="error",
            cost_complete=False,
            error_type="QuotaTransportError",
            elapsed_ms=10.0,
        )
        router.error = _FakeQuotaError()
        router.raw_response = {"secret": "RAW_ERROR_RESPONSE_DO_NOT_STORE"}
        receipts: list[dict[str, Any]] = []
        client = create_live_client(receipts, router=router)

        with self.assertRaises(_FakeQuotaError):
            client("PROMPT_ERROR_DO_NOT_STORE")

        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["kind"], "transport_error")
        self.assertEqual(receipts[0]["error_type"], "QuotaTransportError")
        self.assertEqual(receipts[0]["terminal_kind"], "quota")
        self.assertIsNone(receipts[0]["prompt_tokens"])
        self.assertEqual(receipts[0]["resolved_model"], "unknown")
        serialized = json.dumps(receipts, ensure_ascii=True)
        self.assertNotIn("PROMPT_ERROR_DO_NOT_STORE", serialized)
        self.assertNotIn("RAW_ERROR_RESPONSE_DO_NOT_STORE", serialized)
        self.assertNotIn("PRIVATE_ERROR_TEXT_DO_NOT_STORE", serialized)

    def test_error_without_router_receipt_is_summarized_without_message(self) -> None:
        router = _FakeRouter()
        router.error = _FakeQuotaError()
        receipts: list[dict[str, Any]] = []
        client = create_live_client(receipts, router=router)

        with self.assertRaises(_FakeQuotaError):
            client("PROMPT_ERROR_DO_NOT_STORE")

        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["kind"], "call_error")
        self.assertEqual(receipts[0]["error_type"], "_FakeQuotaError")
        self.assertEqual(receipts[0]["terminal_kind"], "quota")
        self.assertIsNone(receipts[0]["attempt_index"])
        serialized = json.dumps(receipts, ensure_ascii=True)
        self.assertNotIn("PROMPT_ERROR_DO_NOT_STORE", serialized)
        self.assertNotIn("PRIVATE_ERROR_TEXT_DO_NOT_STORE", serialized)


if __name__ == "__main__":
    unittest.main()
