# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the isolated cross-process provider budget."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import httpx

from utils import provider_attempt_budget as budget


_ENV_NAMES = (
    budget.PROVIDER_ATTEMPT_BUDGET_ENV,
    budget.PROVIDER_ATTEMPT_LEDGER_ENV,
    budget.PROVIDER_ATTEMPT_RUN_ID_ENV,
)


def _response_body(content: str = "ok") -> dict[str, Any]:
    return {
        "id": "chatcmpl-provider-budget-test",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _process_attempt_worker(
    runtime_root: str,
    ledger_path: str,
    run_id: str,
    attempt_count: int,
    ready_path: str,
    start_path: str,
    result_path: str,
) -> None:
    from unittest import mock as child_mock

    from utils import provider_attempt_budget as child_budget

    os.environ[child_budget.PROVIDER_ATTEMPT_BUDGET_ENV] = "30"
    os.environ[child_budget.PROVIDER_ATTEMPT_LEDGER_ENV] = ledger_path
    os.environ[child_budget.PROVIDER_ATTEMPT_RUN_ID_ENV] = run_id
    with child_mock.patch.object(
        child_budget, "repository_root", return_value=Path(runtime_root)
    ):
        child_budget.activate_provider_attempt_budget()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    sent = 0
    refused = 0
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        Path(ready_path).write_text("ready\n", encoding="ascii")
        deadline = time.monotonic() + 20
        while not Path(start_path).exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("provider attempt process start marker timed out")
            time.sleep(0.01)
        for _ in range(attempt_count):
            try:
                client.get("https://provider.example.invalid/v1/test")
                sent += 1
            except child_budget.ProviderAttemptBudgetExceeded:
                refused += 1
    Path(result_path).write_text(
        json.dumps({"sent": sent, "refused": refused}) + "\n",
        encoding="ascii",
    )


class ProviderAttemptBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_environment = {name: os.environ.get(name) for name in _ENV_NAMES}
        for name in _ENV_NAMES:
            os.environ.pop(name, None)
        self._saved_sync_method = httpx.Client._send_single_request
        self._saved_async_method = httpx.AsyncClient._send_single_request
        self._saved_config = budget._ACTIVE_CONFIG
        self._saved_activation_error = budget._ACTIVATION_ERROR
        self._temporary_directory = tempfile.TemporaryDirectory(dir="tmp/n2")
        self.scratch_root = Path(self._temporary_directory.name)
        self.repository = self.scratch_root / "fixture-repository"
        self.repository.mkdir()
        (self.repository / "AGENTS.md").write_text("fixture\n", encoding="ascii")
        (self.repository / "model_config.py").write_text("", encoding="ascii")
        self.capture_root = self.repository / "tmp" / "combat_capture"
        self.capture_root.mkdir(parents=True)
        self.ledger_path = self.capture_root / "tmp" / "n2" / "attempts.jsonl"
        self.run_id = "provider-budget-test"

    def tearDown(self) -> None:
        httpx.Client._send_single_request = self._saved_sync_method
        httpx.AsyncClient._send_single_request = self._saved_async_method
        budget._ACTIVE_CONFIG = self._saved_config
        budget._ACTIVATION_ERROR = self._saved_activation_error
        for name, value in self._saved_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._temporary_directory.cleanup()

    def _configure_environment(self, *, ledger_path: Path | None = None) -> None:
        os.environ[budget.PROVIDER_ATTEMPT_BUDGET_ENV] = "30"
        os.environ[budget.PROVIDER_ATTEMPT_LEDGER_ENV] = str(ledger_path or self.ledger_path)
        os.environ[budget.PROVIDER_ATTEMPT_RUN_ID_ENV] = self.run_id

    def _activate(self) -> None:
        self._configure_environment()
        with mock.patch.object(budget, "repository_root", return_value=self.capture_root):
            budget.activate_provider_attempt_budget()

    def _ledger_records(self) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in self.ledger_path.read_text(encoding="ascii").splitlines()
        ]

    def test_exactly_30_requests_are_sent_and_the_31st_is_refused_before_send(self) -> None:
        self._activate()
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            for _ in range(30):
                client.post(
                    "https://provider.example.invalid/v1/chat/completions?query=QUERY_SECRET",
                    headers={"Authorization": "Bearer HEADER_SECRET"},
                    content="BODY_SECRET",
                )
            with self.assertRaises(budget.ProviderAttemptBudgetExceeded) as refused:
                client.post(
                    "https://provider.example.invalid/v1/chat/completions?query=QUERY_SECRET",
                    headers={"Authorization": "Bearer HEADER_SECRET"},
                    content="BODY_SECRET",
                )

        self.assertEqual(len(sent), 30)
        self.assertEqual(refused.exception.reservation_number, 31)
        records = self._ledger_records()
        reservations = [record for record in records if record["event"] == "reservation"]
        refusals = [record for record in records if record["event"] == "refusal"]
        self.assertEqual(len(reservations), 30)
        self.assertEqual(reservations[-1]["reservation_number"], 30)
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["reservation_number"], 31)
        self.assertEqual(reservations[0]["path"], "/v1/chat/completions")
        ledger = self.ledger_path.read_text(encoding="ascii")
        for secret in ("QUERY_SECRET", "HEADER_SECRET", "BODY_SECRET", "Bearer"):
            self.assertNotIn(secret, ledger)

    def test_sdk_retries_and_router_fallback_each_reserve_a_transport_attempt(self) -> None:
        from openai import OpenAI

        self._activate()
        retry_count = 0

        def retry_handler(request: httpx.Request) -> httpx.Response:
            nonlocal retry_count
            retry_count += 1
            if retry_count < 3:
                raise httpx.ConnectError("synthetic provider-free retry", request=request)
            return httpx.Response(200, request=request, json=_response_body())

        retry_http_client = httpx.Client(transport=httpx.MockTransport(retry_handler))
        retry_client = OpenAI(
            api_key="fixture-only",
            max_retries=2,
            http_client=retry_http_client,
        )
        response = retry_client.chat.completions.create(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )
        self.assertEqual(response.choices[0].message.content, "ok")
        self.assertEqual(retry_count, 3)

        primary_sends = 0
        fallback_sends = 0

        def primary_handler(request: httpx.Request) -> httpx.Response:
            nonlocal primary_sends
            primary_sends += 1
            return httpx.Response(503, request=request, json={"error": {"message": "temporary"}})

        def fallback_handler(request: httpx.Request) -> httpx.Response:
            nonlocal fallback_sends
            fallback_sends += 1
            return httpx.Response(200, request=request, json=_response_body("fallback"))

        primary_client = OpenAI(
            api_key="fixture-only",
            base_url="https://openrouter.example.invalid/api/v1",
            max_retries=2,
            http_client=httpx.Client(transport=httpx.MockTransport(primary_handler)),
        )
        fallback_client = OpenAI(
            api_key="fixture-only",
            base_url="https://openai.example.invalid/v1",
            max_retries=2,
            http_client=httpx.Client(transport=httpx.MockTransport(fallback_handler)),
        )
        with mock.patch(
            "requests.get",
            side_effect=AssertionError("unexpected non-mocked network request"),
        ), mock.patch.object(budget, "repository_root", return_value=self.capture_root):
            from utils import ai_client_factory
            from utils.llm_router import llm

            with mock.patch.object(
                ai_client_factory, "_get_actual_provider", return_value=("openrouter", True)
            ), mock.patch.object(
                ai_client_factory,
                "create_chat_client",
                side_effect=[primary_client, fallback_client],
            ):
                result = llm.call(
                    "dm_main",
                    [{"role": "user", "content": "fallback test"}],
                )

        self.assertEqual(result, "fallback")
        self.assertEqual(primary_sends, 1)
        self.assertEqual(fallback_sends, 1)
        self.assertEqual(
            len([record for record in self._ledger_records() if record["event"] == "reservation"]),
            5,
        )
        retry_client.close()
        primary_client.close()
        fallback_client.close()

    def test_async_httpx_dispatch_is_reserved(self) -> None:
        self._activate()
        sent: list[httpx.Request] = []

        async def exercise() -> None:
            async def handler(request: httpx.Request) -> httpx.Response:
                sent.append(request)
                return httpx.Response(200, request=request)

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                await client.get("https://provider.example.invalid/v1/async")

        asyncio.run(exercise())
        self.assertEqual(len(sent), 1)
        self.assertEqual(
            len([record for record in self._ledger_records() if record["event"] == "reservation"]),
            1,
        )

    def test_concurrent_thread_dispatch_never_exceeds_the_budget(self) -> None:
        self._activate()
        sent_lock = threading.Lock()
        sent_count = 0
        thread_count = 48
        start_barrier = threading.Barrier(thread_count)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal sent_count
            with sent_lock:
                sent_count += 1
            return httpx.Response(200, request=request)

        def attempt(client: httpx.Client) -> bool:
            start_barrier.wait(timeout=20)
            try:
                client.get("https://provider.example.invalid/v1/thread")
                return True
            except budget.ProviderAttemptBudgetExceeded:
                return False

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            threads = [threading.Thread(target=attempt, args=(client,)) for _ in range(thread_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=25)
            self.assertTrue(all(not thread.is_alive() for thread in threads))

        records = self._ledger_records()
        self.assertEqual(sent_count, 30)
        self.assertEqual(
            len([record for record in records if record["event"] == "reservation"]), 30
        )
        self.assertEqual(
            len([record for record in records if record["event"] == "refusal"]), 18
        )

    def test_concurrent_process_dispatch_never_exceeds_the_budget(self) -> None:
        self._activate()
        context = multiprocessing.get_context("spawn")
        process_count = 4
        attempts_per_process = 12
        start_path = self.scratch_root / "go"
        ready_paths = [self.scratch_root / "ready-{0}".format(index) for index in range(process_count)]
        result_paths = [self.scratch_root / "result-{0}.json".format(index) for index in range(process_count)]
        processes = [
            context.Process(
                target=_process_attempt_worker,
                args=(
                    str(self.capture_root),
                    str(self.ledger_path),
                    self.run_id,
                    attempts_per_process,
                    str(ready_paths[index]),
                    str(start_path),
                    str(result_paths[index]),
                ),
            )
            for index in range(process_count)
        ]
        for process in processes:
            process.start()
        ready_deadline = time.monotonic() + 25
        while not all(path.exists() for path in ready_paths):
            failed_processes = [process for process in processes if process.exitcode not in (None, 0)]
            if failed_processes:
                self.fail("provider attempt worker failed before the start barrier")
            if time.monotonic() >= ready_deadline:
                self.fail("provider attempt workers did not reach the start barrier")
            time.sleep(0.01)
        start_path.write_text("go\n", encoding="ascii")
        for process in processes:
            process.join(timeout=40)
        self.assertTrue(all(process.exitcode == 0 for process in processes))
        results = [json.loads(path.read_text(encoding="ascii")) for path in result_paths]

        sent_count = sum(result["sent"] for result in results)
        refused_count = sum(result["refused"] for result in results)
        records = self._ledger_records()
        self.assertEqual(sent_count, 30)
        self.assertEqual(refused_count, 18)
        self.assertEqual(
            len([record for record in records if record["event"] == "reservation"]), 30
        )
        self.assertEqual(
            len([record for record in records if record["event"] == "refusal"]), 18
        )

    def test_loopback_httpx_requests_are_not_counted(self) -> None:
        self._activate()
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            for url in (
                "http://127.0.0.1:8357/health",
                "http://[::1]:8370/health",
                "http://localhost:8360/health",
            ):
                client.get(url)

        self.assertEqual(len(sent), 3)
        self.assertEqual(
            len([record for record in self._ledger_records() if record["event"] == "reservation"]),
            0,
        )

    def test_missing_activation_record_refuses_dispatch_before_transport_send(self) -> None:
        self._activate()
        header = self._ledger_records()[0]
        self.ledger_path.write_text(json.dumps(header) + "\n", encoding="ascii")
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(budget.ProviderAttemptBudgetUnavailable):
                client.get("https://provider.example.invalid/v1/no-activation")

        self.assertEqual(sent, [])
        self.assertEqual(self._ledger_records(), [header])

    def test_no_activation_leaves_httpx_untouched_and_does_not_touch_the_ledger(self) -> None:
        sync_method = httpx.Client._send_single_request
        async_method = httpx.AsyncClient._send_single_request
        with mock.patch.object(budget, "repository_root") as root_lookup:
            self.assertIsNone(budget.activate_provider_attempt_budget())
        self.assertIs(httpx.Client._send_single_request, sync_method)
        self.assertIs(httpx.AsyncClient._send_single_request, async_method)
        root_lookup.assert_not_called()
        self.assertFalse(self.ledger_path.exists())

    def test_partial_activation_fails_before_transport_patch_or_ledger_io(self) -> None:
        os.environ[budget.PROVIDER_ATTEMPT_BUDGET_ENV] = "30"
        os.environ[budget.PROVIDER_ATTEMPT_LEDGER_ENV] = str(self.ledger_path)
        sync_method = httpx.Client._send_single_request
        with self.assertRaises(budget.ProviderAttemptBudgetConfigurationError):
            budget.activate_provider_attempt_budget()
        self.assertIs(httpx.Client._send_single_request, sync_method)
        self.assertFalse(self.ledger_path.exists())

    def test_activation_outside_isolated_capture_root_fails_closed(self) -> None:
        self._configure_environment()
        sync_method = httpx.Client._send_single_request
        with mock.patch.object(budget, "repository_root", return_value=Path.cwd()):
            with self.assertRaisesRegex(
                budget.ProviderAttemptBudgetConfigurationError,
                "outside tmp/combat_capture",
            ):
                budget.activate_provider_attempt_budget()
        self.assertIs(httpx.Client._send_single_request, sync_method)
        self.assertFalse(self.ledger_path.exists())


if __name__ == "__main__":
    unittest.main()
