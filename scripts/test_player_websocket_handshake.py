# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free regressions for the real player Engine.IO WebSocket path."""

from __future__ import annotations

import asyncio
import json
import socket
import unittest
import urllib.request
from typing import Any
from unittest import mock

import httpx
import openai
import requests

from web.extensions.player import PLAYER_HOST, PLAYER_NAMESPACE, PLAYER_PORT, create_app
from web.extensions.player.assets import VerifiedPlayerClientAssets
from web.extensions.player.auth import PLAYER_SESSION_COOKIE, PlayerSecurity, make_verifier


CLIENT_BUILD_ID = "0123456789abcdef0123456789abcdef"
CLIENT_AUTH = {"client_build_id": CLIENT_BUILD_ID, "protocol_version": 1}
EXPECTED_HOST = f"{PLAYER_HOST}:{PLAYER_PORT}"
EXPECTED_ORIGIN = f"http://{EXPECTED_HOST}"
ASGI_TIMEOUT_SECONDS = 5
EVENT_TIMEOUT_SECONDS = 2


def make_app() -> tuple[Any, str]:
    verifier = make_verifier("websocket-handshake-test-password", salt=b"w" * 16)
    security = PlayerSecurity(lambda: verifier)
    app = create_app(security=security)
    grant = security.create_session()
    if grant is None:
        raise AssertionError("test player session was not created")
    app._client_assets = VerifiedPlayerClientAssets(
        shell_document=b"",
        shell_content_type=b"text/html; charset=utf-8",
        client_build_id=CLIENT_BUILD_ID,
        protocol_version=1,
        assets={},
    )
    return app, grant.cookie_value


def request_headers(
    cookie_value: str | None,
    *,
    origin: str | None = EXPECTED_ORIGIN,
    host: str = EXPECTED_HOST,
) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"host", host.encode("ascii")),
        (b"connection", b"Upgrade"),
        (b"upgrade", b"websocket"),
        (b"sec-websocket-version", b"13"),
        (b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ=="),
    ]
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if cookie_value is not None:
        headers.append(
            (b"cookie", f"{PLAYER_SESSION_COOKIE}={cookie_value}".encode("ascii"))
        )
    return headers


async def run_websocket_handshake(
    app: Any,
    headers: list[tuple[bytes, bytes]],
    *,
    auth: object = CLIENT_AUTH,
) -> tuple[list[dict[str, Any]], list[int]]:
    incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    sent: list[dict[str, Any]] = []
    active_sockets_at_namespace_ack: list[int] = []

    async def receive() -> dict[str, Any]:
        return await incoming.get()

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        packet = message.get("text")
        if isinstance(packet, str) and packet.startswith(f"40{PLAYER_NAMESPACE},"):
            active_sockets_at_namespace_ack.append(app.security.active_socket_count)
        await outgoing.put(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "http",
        "path": "/socket.io/",
        "raw_path": b"/socket.io/",
        "query_string": b"EIO=4&transport=websocket",
        "headers": headers,
        "client": (PLAYER_HOST, 0),
        "server": (PLAYER_HOST, PLAYER_PORT),
        "subprotocols": [],
    }
    async def run_app() -> None:
        await asyncio.wait_for(
            app(scope, receive, send),
            timeout=ASGI_TIMEOUT_SECONDS,
        )

    async def wait_for_message(predicate: Any) -> dict[str, Any]:
        async def receive_matching() -> dict[str, Any]:
            for _ in range(16):
                message = await outgoing.get()
                if predicate(message) or message.get("type") == "websocket.close":
                    return message
            raise AssertionError(
                f"expected ASGI WebSocket event was not observed: {sent!r}"
            )

        return await asyncio.wait_for(
            receive_matching(),
            timeout=EVENT_TIMEOUT_SECONDS,
        )

    app_task = asyncio.create_task(run_app())
    try:
        await incoming.put({"type": "websocket.connect"})
        opening = await wait_for_message(
            lambda message: message.get("type") == "websocket.accept"
        )
        if opening.get("type") == "websocket.close":
            return sent, active_sockets_at_namespace_ack

        engineio_open = await wait_for_message(
            lambda message: isinstance(message.get("text"), str)
            and message["text"].startswith("0{")
        )
        if engineio_open.get("type") == "websocket.close":
            return sent, active_sockets_at_namespace_ack

        if auth is not None:
            packet = f"40{PLAYER_NAMESPACE},{json.dumps(auth, separators=(',', ':'))}"
            await incoming.put({"type": "websocket.receive", "text": packet})
            await wait_for_message(
                lambda message: isinstance(message.get("text"), str)
                and message["text"].startswith(
                    (f"40{PLAYER_NAMESPACE},", f"44{PLAYER_NAMESPACE},")
                )
            )
        return sent, active_sockets_at_namespace_ack
    finally:
        if not app_task.done():
            await incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(app_task, timeout=ASGI_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            app_task.cancel()
            await asyncio.gather(app_task, return_exceptions=True)
        await asyncio.wait_for(
            app.socket_server.shutdown(),
            timeout=EVENT_TIMEOUT_SECONDS,
        )


class PlayerWebsocketHandshakeTests(unittest.TestCase):
    def test_real_asgi_websocket_handshake_accepts_auth_and_rejects_bad_identity(self) -> None:
        network_attempts: list[str] = []

        def tripwire(name: str):
            def fail(*_args: object, **_kwargs: object) -> None:
                network_attempts.append(name)
                raise AssertionError(f"unexpected {name} during in-process handshake")

            return fail

        async def exercise() -> None:
            app, cookie_value = make_app()
            accepted, active_sockets_at_ack = await run_websocket_handshake(
                app,
                request_headers(cookie_value),
            )
            accepted_packets = [
                message.get("text")
                for message in accepted
                if message.get("type") == "websocket.send"
            ]
            self.assertTrue(
                any(packet.startswith("40/player,") for packet in accepted_packets),
                repr(accepted),
            )
            self.assertFalse(any(packet.startswith("44/player,") for packet in accepted_packets))
            self.assertTrue(
                any(
                    isinstance(message.get("text"), str)
                    and message["text"].startswith("0{")
                    for message in accepted
                ),
                repr(accepted),
            )
            self.assertEqual(active_sockets_at_ack, [1])
            self.assertEqual(app.security.active_socket_count, 0)

            refused_identity_cases = (
                ("missing-origin", {"origin": None}),
                ("wrong-origin", {"origin": "http://attacker.invalid"}),
                ("wrong-host", {"host": "attacker.invalid"}),
            )
            for label, identity_override in refused_identity_cases:
                with self.subTest(case=label):
                    refused_app, refused_cookie = make_app()
                    headers = request_headers(refused_cookie, **identity_override)
                    messages, active_sockets = await run_websocket_handshake(
                        refused_app,
                        headers,
                    )
                    self.assertEqual(
                        messages,
                        [{"type": "websocket.close", "code": 1008}],
                    )
                    self.assertEqual(active_sockets, [])
                    self.assertEqual(refused_app.security.active_socket_count, 0)

            refused_session_cases = (
                ("missing-session-cookie", None),
                ("invalid-session-cookie", "invalid-session-cookie"),
            )
            for label, session_cookie in refused_session_cases:
                with self.subTest(case=label):
                    refused_app, _valid_cookie = make_app()
                    messages, active_sockets = await run_websocket_handshake(
                        refused_app,
                        request_headers(session_cookie),
                    )
                    self.assertEqual(
                        messages,
                        [{"type": "websocket.close", "code": 1008}],
                    )
                    self.assertEqual(active_sockets, [])
                    self.assertEqual(refused_app.security.active_socket_count, 0)

            invalid_auth_app, invalid_cookie = make_app()
            invalid_auth, active_sockets = await run_websocket_handshake(
                invalid_auth_app,
                request_headers(invalid_cookie),
                auth={"client_build_id": CLIENT_BUILD_ID, "protocol_version": 999},
            )
            invalid_auth_packets = [
                message.get("text")
                for message in invalid_auth
                if message.get("type") == "websocket.send"
            ]
            self.assertFalse(any(packet.startswith("40/player,") for packet in invalid_auth_packets))
            self.assertTrue(any(packet.startswith("44/player,") for packet in invalid_auth_packets))
            self.assertTrue(
                any(
                    isinstance(message.get("text"), str)
                    and message["text"].startswith("0{")
                    for message in invalid_auth
                ),
                repr(invalid_auth),
            )
            self.assertEqual(active_sockets, [])
            self.assertEqual(invalid_auth_app.security.active_socket_count, 0)

        async def with_tripwires() -> None:
            with (
                mock.patch.object(socket.socket, "bind", side_effect=tripwire("socket-bind")),
                mock.patch.object(socket.socket, "listen", side_effect=tripwire("socket-listen")),
                mock.patch.object(socket.socket, "connect", side_effect=tripwire("socket-connect")),
                mock.patch.object(socket.socket, "connect_ex", side_effect=tripwire("socket-connect")),
                mock.patch.object(socket.socket, "sendto", side_effect=tripwire("socket-send")),
                mock.patch.object(socket, "create_connection", side_effect=tripwire("socket-connect")),
                mock.patch.object(socket, "getaddrinfo", side_effect=tripwire("dns-lookup")),
                mock.patch.object(socket, "gethostbyname", side_effect=tripwire("dns-lookup")),
                mock.patch.object(httpx, "Client", side_effect=tripwire("httpx-provider-dispatch")),
                mock.patch.object(httpx, "AsyncClient", side_effect=tripwire("httpx-provider-dispatch")),
                mock.patch.object(requests.sessions.Session, "request", side_effect=tripwire("requests-provider-dispatch")),
                mock.patch.object(requests.api, "request", side_effect=tripwire("requests-provider-dispatch")),
                mock.patch.object(openai, "OpenAI", side_effect=tripwire("openai-provider-dispatch")),
                mock.patch.object(openai, "AsyncOpenAI", side_effect=tripwire("openai-provider-dispatch")),
                mock.patch.object(urllib.request, "urlopen", side_effect=tripwire("urllib-network-dispatch")),
            ):
                await exercise()

        asyncio.run(with_tripwires())
        self.assertEqual(network_attempts, [])


if __name__ == "__main__":
    unittest.main()
