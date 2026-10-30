# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for factory-owned HTTP transport request deadlines."""

import sys
import time
import types
import unittest
from unittest import mock

from openai import APITimeoutError, OpenAI

import httpcore
import httpx

_REAL_HTTPX_CLIENT = httpx._client.Client

from utils.llm_router import llm, reset_usage_stats
import utils.ai_client_factory as factory
from utils.llm_transport_deadline import (
    TotalDeadlineTransport,
    _DeadlineNetworkStream,
    _DeadlineNetworkBackend,
)


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, stream: httpx.SyncByteStream) -> None:
        self.stream = stream
        self.response: httpx.Response | None = None
        self.request_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        self.response = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=self.stream,
            request=request,
        )
        return self.response

    def close(self) -> None:
        return None


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], delay_seconds: float = 0.0) -> None:
        self.chunks = chunks
        self.delay_seconds = delay_seconds
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            yield chunk

    def close(self) -> None:
        self.closed = True


class _SequenceClient:
    """Minimal provider-free SDK-shaped client for router fallback checks."""

    def __init__(self, outcomes: list[object]) -> None:
        self.calls: list[dict[str, object]] = []
        self._outcomes = list(outcomes)
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(dict(kwargs))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def with_options(self, **kwargs):
        self.options = dict(kwargs)
        return self


class TransportDeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests use fake in-memory transports only; scope the restore so co-loaded tripwire modules are intact after each test.
        patcher = mock.patch.object(httpx, "Client", _REAL_HTTPX_CLIENT)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _client(
        self,
        stream: httpx.SyncByteStream,
        deadline_seconds: float,
    ) -> tuple[httpx.Client, _FakeTransport]:
        inner = _FakeTransport(stream)
        transport = TotalDeadlineTransport(inner, deadline_seconds)
        client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(max(deadline_seconds, 0.2)),
        )
        return client, inner

    def test_continuous_body_chunks_cannot_extend_deadline_and_stream_closes(self) -> None:
        deadline_seconds = 0.09
        stream = _ChunkStream([b"a", b"b", b"c", b"d", b"e"], 0.025)
        client, inner = self._client(stream, deadline_seconds)
        started = time.monotonic()
        try:
            with self.assertRaises(httpx.ReadTimeout):
                client.post("https://provider.invalid/v1/chat/completions")
        finally:
            client.close()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, deadline_seconds + 0.06)
        self.assertIsNotNone(inner.response)
        self.assertTrue(stream.closed)

    def test_fast_response_content_is_unchanged(self) -> None:
        stream = _ChunkStream([b"complete ", b"response"])
        client, _inner = self._client(stream, 0.2)
        try:
            response = client.post("https://provider.invalid/v1/chat/completions")
            self.assertEqual(response.content, b"complete response")
            response.close()
        finally:
            client.close()

    def test_one_blocked_network_read_is_capped_to_remaining_deadline(self) -> None:
        deadline_seconds = 0.08

        class BlockingSocketStream:
            def __init__(self) -> None:
                self.timeout: float | None = None
                self.closed = False

            def read(self, _max_bytes: int, timeout: float | None = None) -> bytes:
                self.timeout = timeout
                time.sleep(timeout or 0.0)
                raise httpcore.ReadTimeout("fake socket read timed out")

            def write(self, _buffer: bytes, timeout: float | None = None) -> None:
                self.timeout = timeout

            def start_tls(self, *_args, **_kwargs):
                return self

            def close(self) -> None:
                self.closed = True

            def get_extra_info(self, _info: str) -> None:
                return None

        socket_stream = BlockingSocketStream()
        deadline_network_stream = _DeadlineNetworkStream(socket_stream)

        class BlockingBody(httpx.SyncByteStream):
            def __init__(self) -> None:
                self.closed = False

            def __iter__(self):
                try:
                    yield deadline_network_stream.read(1, timeout=10.0)
                except httpcore.ReadTimeout as exc:
                    raise httpx.ReadTimeout("fake socket read timed out") from exc

            def close(self) -> None:
                self.closed = True
                socket_stream.close()

        stream = BlockingBody()
        client, _inner = self._client(stream, deadline_seconds)
        started = time.monotonic()
        try:
            with self.assertRaises(httpx.ReadTimeout):
                client.post("https://provider.invalid/v1/chat/completions")
        finally:
            client.close()
        elapsed = time.monotonic() - started

        self.assertIsNotNone(socket_stream.timeout)
        self.assertLessEqual(socket_stream.timeout, deadline_seconds)
        self.assertLess(elapsed, deadline_seconds + 0.06)
        self.assertTrue(socket_stream.closed)
        self.assertTrue(stream.closed)

    def test_sdk_api_timeout_error_emits_transport_receipt_then_one_fallback(self) -> None:
        factory.reset_fallback_status()
        reset_usage_stats()
        sdk_error_shape = APITimeoutError(
            request=httpx.Request(
                "POST", "https://provider.invalid/v1/chat/completions"
            )
        )
        self.assertNotIn("timeout", str(sdk_error_shape).lower())
        primary_stream = _ChunkStream(
            [b'{"choices":', b"[]}", b" ", b" "],
            delay_seconds=0.025,
        )
        primary_inner_transport = _FakeTransport(primary_stream)
        primary_transport = TotalDeadlineTransport(
            primary_inner_transport, deadline_seconds=0.07
        )
        primary_http_client = httpx.Client(
            transport=primary_transport,
            timeout=httpx.Timeout(1.0),
        )
        primary = OpenAI(
            api_key="PROVIDER_FREE_TEST_KEY",
            http_client=primary_http_client,
            max_retries=0,
        )
        fallback = _SequenceClient(
            [{
                "choices": [{"message": {"content": "fallback response"}}],
                "model": "gpt-6-luna",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }]
        )
        receipts = []
        try:
            with mock.patch.object(
                factory,
                "_get_actual_provider",
                side_effect=[("openrouter", True), ("openai", False)],
            ):
                with mock.patch.object(
                    factory,
                    "create_chat_client",
                    side_effect=[primary, fallback],
                ) as create_client:
                    result = llm.call(
                        "dm_main",
                        [],
                        observer=lambda receipt, _raw: receipts.append(receipt),
                    )
        finally:
            primary.close()
            factory.reset_fallback_status()

        self.assertEqual(result, "fallback response")
        self.assertEqual(primary_inner_transport.request_count, 1)
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual(fallback.calls[0]["model"], "gpt-6-luna")
        create_client.assert_has_calls([mock.call(), mock.call(use_fallback=True)])
        self.assertEqual(create_client.call_count, 2)
        self.assertEqual([receipt.kind for receipt in receipts], [
            "transport_error", "response",
        ])
        self.assertEqual(receipts[0].error_type, "APITimeoutError")
        self.assertTrue(receipts[1].fallback)

    def test_both_factory_chat_clients_receive_deadline_transports(self) -> None:
        import model_config
        import utils.llm_transport_deadline as deadline_transport

        config_stub = types.ModuleType("config")
        config_stub.OPENAI_API_KEY = "PROVIDER_FREE_TEST_OPENAI_KEY"
        config_stub.OPENROUTER_API_KEY = "PROVIDER_FREE_TEST_OPENROUTER_KEY"
        constructed = []

        openai_sentinel = object()

        def fake_openai(**kwargs):
            constructed.append(dict(kwargs))
            return openai_sentinel

        clients = []
        try:
            with mock.patch.dict(sys.modules, {"config": config_stub}):
                with mock.patch.object(factory, "configure_provider_log_safety"):
                    with mock.patch.object(factory, "OpenAI", side_effect=fake_openai):
                        with mock.patch.object(
                            factory,
                            "_get_actual_provider",
                            return_value=("openrouter", True),
                        ):
                            factory.create_chat_client()
                        with mock.patch.object(
                            factory,
                            "_get_actual_provider",
                            return_value=("openai", False),
                        ):
                            factory.create_chat_client()

            self.assertEqual(len(constructed), 2)
            openrouter_kwargs, openai_kwargs = constructed
            for kwargs in constructed:
                http_client = kwargs["http_client"]
                clients.append(http_client)
                self.assertIsInstance(http_client, httpx.Client)
                self.assertIsInstance(
                    http_client._transport._transport._pool._network_backend,
                    _DeadlineNetworkBackend,
                )
                self.assertEqual(
                    http_client.timeout.read,
                    model_config.API_TIMEOUT_SECONDS,
                )
                self.assertEqual(
                    kwargs["timeout"].read,
                    model_config.API_TIMEOUT_SECONDS,
                )

            self.assertEqual(
                set(openrouter_kwargs),
                {"api_key", "base_url", "timeout", "http_client", "default_headers"},
            )
            self.assertEqual(openrouter_kwargs["base_url"], model_config.OPENROUTER_BASE_URL)
            self.assertEqual(
                openrouter_kwargs["default_headers"],
                {
                    "HTTP-Referer": model_config.OPENROUTER_HTTP_REFERER,
                    "X-Title": model_config.OPENROUTER_APP_TITLE,
                },
            )
            self.assertEqual(
                set(openai_kwargs),
                {"api_key", "timeout", "http_client"},
            )
        finally:
            for client in clients:
                client.close()
            factory.reset_fallback_status()


if __name__ == "__main__":
    unittest.main()
