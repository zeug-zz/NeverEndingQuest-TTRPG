# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the isolated player app and listener lifecycle."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlencode

from web.extensions.player import (
    PLAYER_HOST,
    PLAYER_NAMESPACE,
    PLAYER_PORT,
    PlayerInputAdmission,
    PlayerInputCommand,
    PlayerListener,
    PlayerSnapshot,
    create_app,
)
from web.extensions.player.assets import VerifiedPlayerClientAssets
from web.extensions.player.auth import (
    PLAYER_SESSION_COOKIE,
    PRELOGIN_CSRF_COOKIE,
    PRELOGIN_CSRF_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    PlayerSecurity,
    _cli,
    make_verifier,
    parse_verifier,
)
from web.extensions.player.limiters import PlayerLimiters
from web.extensions.player.limits import (
    EXPENSIVE_READS_PER_SESSION_PER_WINDOW,
    LOGIN_ATTEMPTS_PER_WINDOW,
    LOGIN_ATTEMPT_WINDOW_SECONDS,
    MAX_ACTIVE_SESSIONS,
    MAX_PRELOGIN_CHALLENGES,
    MAX_ADMITTED_PLAYER_COMMANDS,
    MAX_CONCURRENT_PLAYER_SOCKETS,
    MAX_HTTP_BODY_BYTES,
    MAX_PASSWORD_BYTES,
    MAX_PLAYER_INPUT_BYTES,
    MAX_REPLAY_BYTES,
    MAX_REPLAY_EVENTS,
    MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION,
    MAX_SNAPSHOT_BYTES,
    MAX_SOCKETIO_EVENT_BYTES,
    MEDIA_READS_PER_SESSION_PER_WINDOW,
    PLAYER_INPUTS_PER_SESSION_PER_WINDOW,
    PLAYER_INPUT_WINDOW_SECONDS,
    READ_WINDOW_SECONDS,
)


class _FakeGateway:
    def admit_input(self, command: PlayerInputCommand) -> PlayerInputAdmission:
        return PlayerInputAdmission(request_id=command.request_id, status="accepted")

    def read_snapshot(self) -> PlayerSnapshot:
        return PlayerSnapshot(revision=1, projection={"transcript": []})


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener_socket:
        listener_socket.bind((PLAYER_HOST, 0))
        return int(listener_socket.getsockname()[1])


class _FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_security(
    *,
    password: str = "correct horse battery staple",
    clock: _FakeClock | None = None,
    verifier_value: str | None = None,
) -> PlayerSecurity:
    verifier = verifier_value if verifier_value is not None else make_verifier(
        password,
        salt=b"p" * 16,
    )
    return PlayerSecurity(lambda: verifier, clock=clock or _FakeClock())


def _dispatch_http(
    app: Any,
    method: str,
    path: str,
    *,
    body: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    host: str = f"{PLAYER_HOST}:{PLAYER_PORT}",
    origin: str | None = None,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    selected_headers = list(headers or [])
    if not any(name.lower() == b"host" for name, _value in selected_headers):
        selected_headers.append((b"host", host.encode("ascii")))
    if origin is not None and not any(
        name.lower() == b"origin" for name, _value in selected_headers
    ):
        selected_headers.append((b"origin", origin.encode("ascii")))
    if body and not any(name.lower() == b"content-length" for name, _value in selected_headers):
        selected_headers.append((b"content-length", str(len(body)).encode("ascii")))
    messages: list[dict[str, Any]] = []
    sent_body = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if sent_body:
            return {"type": "http.disconnect"}
        sent_body = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": selected_headers,
            },
            receive,
            send,
        )
    )
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    response_headers = next(
        message["headers"] for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return status, response_headers, response_body


def _header_values(headers: list[tuple[bytes, bytes]], name: bytes) -> list[bytes]:
    return [value for header, value in headers if header.lower() == name]


def _login(
    app: Any,
    password: str,
    *,
    csrf_nonce: str | None = None,
    prelogin_cookie: str | None = None,
    origin: str = f"http://{PLAYER_HOST}:{PLAYER_PORT}",
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    if csrf_nonce is None or prelogin_cookie is None:
        _status, shell_headers, shell_body = _dispatch_http(app, "GET", "/")
        if csrf_nonce is None:
            match = re.search(rb'name="csrf_token" value="([A-Za-z0-9_-]+)"', shell_body)
            csrf_nonce = match.group(1).decode("ascii") if match is not None else None
        if prelogin_cookie is None:
            for value in _header_values(shell_headers, b"set-cookie"):
                if value.startswith(PRELOGIN_CSRF_COOKIE.encode("ascii") + b"="):
                    prelogin_cookie = value.split(b"=", 1)[1].split(b";", 1)[0].decode("ascii")
                    break
    request_body = json.dumps(
        {"password": password, "csrf_token": csrf_nonce},
        separators=(",", ":"),
    ).encode("utf-8")
    request_headers = [
        (b"content-type", b"application/json"),
        (b"cookie", f"{PRELOGIN_CSRF_COOKIE}={prelogin_cookie}".encode("ascii")),
    ]
    return _dispatch_http(
        app,
        "POST",
        "/api/player/login",
        body=request_body,
        headers=request_headers,
        origin=origin,
    )


class PlayerAccessTests(unittest.TestCase):
    def test_app_registers_only_player_namespace_and_requires_authenticated_connect(self) -> None:
        gateway = _FakeGateway()
        app = create_app(gateway=gateway)

        self.assertIs(app.gateway, gateway)
        self.assertEqual(app.socket_server.handlers.keys(), {PLAYER_NAMESPACE})
        self.assertEqual(
            set(app.socket_server.handlers[PLAYER_NAMESPACE]),
            {"connect", "disconnect", "player.input.submit"},
        )
        self.assertEqual(app.socket_server.namespace_handlers, {})
        self.assertEqual(app.socket_server.namespaces, [PLAYER_NAMESPACE])
        self.assertEqual(app.socket_server.eio.max_http_buffer_size, MAX_SOCKETIO_EVENT_BYTES)
        connect_handler = app.socket_server.handlers[PLAYER_NAMESPACE]["connect"]
        self.assertFalse(asyncio.run(connect_handler("test-sid", {})))

    def test_http_router_serves_csrf_login_shell_and_only_auth_routes(self) -> None:
        app = create_app(security=_make_security())

        root_status, root_headers, root_body = _dispatch_http(app, "GET", "/")
        self.assertEqual(root_status, 200)
        self.assertIn(b"Player login", root_body)
        self.assertIn(b"name=\"csrf_token\"", root_body)
        self.assertIn(b"cache-control", [name for name, _value in root_headers])
        self.assertEqual(len(_header_values(root_headers, b"set-cookie")), 1)
        self.assertIn(b"Secure", _header_values(root_headers, b"set-cookie")[0])
        self.assertIn(b"HttpOnly", _header_values(root_headers, b"set-cookie")[0])
        self.assertIn(b"SameSite=Strict", _header_values(root_headers, b"set-cookie")[0])
        self.assertNotIn(b"Domain=", _header_values(root_headers, b"set-cookie")[0])

        unknown_status, _unknown_headers, _unknown_body = _dispatch_http(
            app,
            "GET",
            "/api/player/snapshot",
        )
        self.assertEqual(unknown_status, 404)

    def test_absent_wrong_correct_and_malformed_credentials_fail_closed(self) -> None:
        missing_app = create_app(security=PlayerSecurity(lambda: None))
        absent_status, _headers, absent_body = _login(missing_app, "provided password")
        self.assertEqual(absent_status, 401)
        self.assertEqual(json.loads(absent_body), {"error": "invalid_credentials"})
        self.assertEqual(missing_app.security.active_session_count, 0)

        missing_password_app = create_app(security=_make_security())
        _status, shell_headers, shell_body = _dispatch_http(missing_password_app, "GET", "/")
        nonce_match = re.search(rb'value="([A-Za-z0-9_-]+)"', shell_body)
        self.assertIsNotNone(nonce_match)
        challenge_cookie = _header_values(shell_headers, b"set-cookie")[0]
        challenge_value = challenge_cookie.split(b"=", 1)[1].split(b";", 1)[0]
        missing_status, _headers, missing_body = _dispatch_http(
            missing_password_app,
            "POST",
            "/api/player/login",
            body=json.dumps(
                {"csrf_token": nonce_match.group(1).decode("ascii") if nonce_match else ""}
            ).encode("ascii"),
            headers=[
                (b"content-type", b"application/json"),
                (b"cookie", PRELOGIN_CSRF_COOKIE.encode("ascii") + b"=" + challenge_value),
            ],
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(missing_status, 401)
        self.assertEqual(json.loads(missing_body), {"error": "invalid_credentials"})

        malformed_app = create_app(security=_make_security(verifier_value="not-a-verifier"))
        malformed_status, _headers, malformed_body = _login(malformed_app, "provided password")
        self.assertEqual(malformed_status, 401)
        self.assertEqual(json.loads(malformed_body), {"error": "invalid_credentials"})
        self.assertEqual(malformed_app.security.active_session_count, 0)

        app = create_app(security=_make_security())
        wrong_status, wrong_headers, wrong_body = _login(app, "wrong password")
        self.assertEqual(wrong_status, 401)
        self.assertEqual(json.loads(wrong_body), {"error": "invalid_credentials"})
        self.assertFalse(_header_values(wrong_headers, b"set-cookie"))
        self.assertEqual(app.security.active_session_count, 0)

        correct_status, correct_headers, correct_body = _login(app, "correct horse battery staple")
        self.assertEqual(correct_status, 200)
        grant_payload = json.loads(correct_body)
        self.assertRegex(grant_payload["csrf_token"], r"^[A-Za-z0-9_-]{32,128}$")
        session_cookie_headers = [
            value
            for value in _header_values(correct_headers, b"set-cookie")
            if value.startswith(PLAYER_SESSION_COOKIE.encode("ascii") + b"=")
        ]
        self.assertEqual(len(session_cookie_headers), 1)
        self.assertIn(b"Max-Age=14400", session_cookie_headers[0])
        self.assertIn(b"Secure", session_cookie_headers[0])
        self.assertIn(b"HttpOnly", session_cookie_headers[0])
        self.assertIn(b"SameSite=Strict", session_cookie_headers[0])
        self.assertNotIn(b"Domain=", session_cookie_headers[0])
        self.assertEqual(app.security.active_session_count, 1)

    def test_scrypt_verifier_uses_real_fixed_parameters_and_rejects_oversized_password(self) -> None:
        encoded = make_verifier("correct horse battery staple", salt=b"s" * 16)
        verifier = parse_verifier(encoded)
        self.assertIsNotNone(verifier)
        assert verifier is not None
        self.assertTrue(verifier.verify("correct horse battery staple"))
        self.assertFalse(verifier.verify("incorrect"))
        self.assertFalse(verifier.verify("x" * (MAX_PASSWORD_BYTES + 1)))
        self.assertIsNone(parse_verifier(encoded.replace("$32768$", "$16384$")))
        self.assertIsNone(parse_verifier(encoded[:-1] + "g"))

    def test_verifier_cli_reads_password_interactively_and_never_prints_it(self) -> None:
        from contextlib import redirect_stdout

        output = io.StringIO()
        secret = "cli-only-player-secret"
        with mock.patch("web.extensions.player.auth.getpass.getpass", return_value=secret):
            with redirect_stdout(output):
                status = _cli(["--make-verifier"])
        self.assertEqual(status, 0)
        self.assertNotIn(secret, output.getvalue())
        self.assertIsNotNone(parse_verifier(output.getvalue().strip()))

    def test_login_never_logs_supplied_password(self) -> None:
        app = create_app(security=_make_security())
        secret = "password-that-must-not-be-logged"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            status, _headers, _body = _login(app, secret)
        finally:
            root_logger.removeHandler(handler)
            handler.close()
        self.assertEqual(status, 401)
        self.assertNotIn(secret, stream.getvalue())

    def test_login_rate_limit_precedes_password_verification(self) -> None:
        clock = _FakeClock()
        app = create_app(security=_make_security(clock=clock))
        verify = mock.Mock(return_value=False)
        app.security.verify_password = verify
        body = b'{"password":"bad","csrf_token":"bad"}'
        for attempt in range(LOGIN_ATTEMPTS_PER_WINDOW):
            status, _headers, _response = _dispatch_http(
                app,
                "POST",
                "/api/player/login",
                body=body,
                headers=[(b"content-type", b"application/json")],
                origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            )
            self.assertEqual(status, 403, msg=f"attempt={attempt + 1}")
        status, _headers, _response = _dispatch_http(
            app,
            "POST",
            "/api/player/login",
            body=body,
            headers=[(b"content-type", b"application/json")],
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(status, 429)
        verify.assert_not_called()
        clock.advance(LOGIN_ATTEMPT_WINDOW_SECONDS)
        self.assertTrue(app.security.allow_login_attempt())

    def test_password_verification_runs_off_event_loop_thread(self) -> None:
        app = create_app(security=_make_security())
        event_loop_thread_id = threading.get_ident()
        verifier_thread_ids: list[int] = []

        def verify_password(password: str | None) -> bool:
            verifier_thread_ids.append(threading.get_ident())
            return password == "injected verifier password"

        app.security.verify_password = verify_password
        status, _headers, _body = _login(app, "injected verifier password")

        self.assertEqual(status, 200)
        self.assertEqual(len(verifier_thread_ids), 1)
        self.assertNotEqual(verifier_thread_ids[0], event_loop_thread_id)

    def test_oversized_password_is_rejected_before_scrypt(self) -> None:
        app = create_app(security=_make_security())
        shell_status, shell_headers, shell_body = _dispatch_http(app, "GET", "/")
        self.assertEqual(shell_status, 200)
        nonce = re.search(rb'value="([A-Za-z0-9_-]+)"', shell_body)
        self.assertIsNotNone(nonce)
        cookie = _header_values(shell_headers, b"set-cookie")[0].split(b"=", 1)[1].split(b";", 1)[0]
        verifier = mock.Mock(return_value=False)
        app.security.verify_password = verifier
        body = json.dumps(
            {
                "password": "x" * (MAX_PASSWORD_BYTES + 1),
                "csrf_token": nonce.group(1).decode("ascii") if nonce else "",
            },
            separators=(",", ":"),
        ).encode("ascii")
        status, _headers, _response = _dispatch_http(
            app,
            "POST",
            "/api/player/login",
            body=body,
            headers=[
                (b"content-type", b"application/json"),
                (b"cookie", PRELOGIN_CSRF_COOKIE.encode("ascii") + b"=" + cookie),
            ],
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(status, 400)
        verifier.assert_not_called()

    def test_session_expiry_restart_logout_and_csrf_revocation(self) -> None:
        clock = _FakeClock()
        security = _make_security(clock=clock)
        app = create_app(security=security)
        status, headers, body = _login(app, "correct horse battery staple")
        self.assertEqual(status, 200)
        csrf_token = json.loads(body)["csrf_token"]
        session_cookie = next(
            value.split(b"=", 1)[1].split(b";", 1)[0].decode("ascii")
            for value in _header_values(headers, b"set-cookie")
            if value.startswith(PLAYER_SESSION_COOKIE.encode("ascii") + b"=")
        )
        self.assertIsNotNone(security.session_id_for_cookie(session_cookie))
        self.assertTrue(security.csrf_is_valid(session_cookie, csrf_token))
        self.assertFalse(security.csrf_is_valid(session_cookie, "wrong-token"))
        self.assertTrue(
            security.register_socket(
                "session-socket",
                session_cookie,
                f"{PLAYER_HOST}:{PLAYER_PORT}",
                f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            )
        )
        disconnect_sockets = mock.AsyncMock()
        app.http_router._disconnect_sockets = disconnect_sockets

        wrong_logout_status, _headers, _body = _dispatch_http(
            app,
            "POST",
            "/api/player/logout",
            body=b'{"csrf_token":"wrong-token"}',
            headers=[
                (b"content-type", b"application/json"),
                (b"cookie", f"{PLAYER_SESSION_COOKIE}={session_cookie}".encode("ascii")),
            ],
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(wrong_logout_status, 403)
        self.assertIsNotNone(security.session_id_for_cookie(session_cookie))

        logout_status, logout_headers, _body = _dispatch_http(
            app,
            "POST",
            "/api/player/logout",
            body=json.dumps({"csrf_token": csrf_token}).encode("ascii"),
            headers=[
                (b"content-type", b"application/json"),
                (b"cookie", f"{PLAYER_SESSION_COOKIE}={session_cookie}".encode("ascii")),
            ],
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(logout_status, 204)
        self.assertTrue(any(b"Max-Age=0" in value for value in _header_values(logout_headers, b"set-cookie")))
        self.assertIsNone(security.session_id_for_cookie(session_cookie))
        disconnect_sockets.assert_awaited_once_with(["session-socket"])
        self.assertFalse(security.authorize_socket_event("session-socket"))

        second = security.create_session()
        self.assertIsNotNone(second)
        assert second is not None
        old_instance = security.server_instance_id
        security.start_listener()
        self.assertNotEqual(security.server_instance_id, old_instance)
        self.assertIsNone(security.session_id_for_cookie(second.cookie_value))

        expiring = security.create_session()
        self.assertIsNotNone(expiring)
        assert expiring is not None
        malformed_cookie = expiring.cookie_value.split(".")
        malformed_cookie[3] = "\u00b2"
        self.assertIsNone(security.session_id_for_cookie(".".join(malformed_cookie)))
        clock.advance(SESSION_TTL_SECONDS)
        self.assertIsNone(security.session_id_for_cookie(expiring.cookie_value))
        self.assertIsNotNone(security.create_session())

    def test_prelogin_csrf_is_origin_checked_and_one_use(self) -> None:
        app = create_app(security=_make_security())
        _status, headers, body = _dispatch_http(app, "GET", "/")
        match = re.search(rb'value="([A-Za-z0-9_-]+)"', body)
        self.assertIsNotNone(match)
        nonce = match.group(1).decode("ascii") if match else ""
        cookie = _header_values(headers, b"set-cookie")[0].split(b"=", 1)[1].split(b";", 1)[0]
        invalid_origin_status, _headers, _body = _login(
            app,
            "correct horse battery staple",
            csrf_nonce=nonce,
            prelogin_cookie=cookie.decode("ascii"),
            origin="http://attacker.invalid",
        )
        self.assertEqual(invalid_origin_status, 403)
        valid_status, _headers, _body = _login(
            app,
            "correct horse battery staple",
            csrf_nonce=nonce,
            prelogin_cookie=cookie.decode("ascii"),
        )
        self.assertEqual(valid_status, 200)
        replay_status, _headers, _body = _login(
            app,
            "correct horse battery staple",
            csrf_nonce=nonce,
            prelogin_cookie=cookie.decode("ascii"),
        )
        self.assertEqual(replay_status, 403)
        wrong_nonce_status, _headers, _body = _login(
            app,
            "incorrect",
            csrf_nonce="wrong-nonce",
        )
        self.assertEqual(wrong_nonce_status, 403)

    def test_prelogin_challenge_expires(self) -> None:
        clock = _FakeClock()
        security = _make_security(clock=clock)
        challenge = security.issue_prelogin_challenge()
        self.assertIsNotNone(challenge)
        assert challenge is not None
        clock.advance(PRELOGIN_CSRF_TTL_SECONDS)
        self.assertFalse(
            security.consume_prelogin_challenge(
                challenge.cookie_value,
                challenge.csrf_nonce,
            )
        )

    def test_native_login_form_uses_short_lived_prelogin_cookie(self) -> None:
        app = create_app(security=_make_security())
        _status, headers, body = _dispatch_http(app, "GET", "/")
        nonce_match = re.search(rb'value="([A-Za-z0-9_-]+)"', body)
        self.assertIsNotNone(nonce_match)
        nonce = nonce_match.group(1).decode("ascii") if nonce_match else ""
        prelogin_cookie = next(
            value.split(b"=", 1)[1].split(b";", 1)[0]
            for value in _header_values(headers, b"set-cookie")
            if value.startswith(PRELOGIN_CSRF_COOKIE.encode("ascii") + b"=")
        )
        form = urlencode(
            {"password": "correct horse battery staple", "csrf_token": nonce}
        ).encode("ascii")
        status, response_headers, response_body = _dispatch_http(
            app,
            "POST",
            "/api/player/login",
            body=form,
            headers=[
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"cookie", PRELOGIN_CSRF_COOKIE.encode("ascii") + b"=" + prelogin_cookie),
            ],
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(response_body)["csrf_token"])
        self.assertTrue(
            any(
                value.startswith(PLAYER_SESSION_COOKIE.encode("ascii") + b"=")
                for value in _header_values(response_headers, b"set-cookie")
            )
        )

    def test_raw_host_origin_and_forwarding_headers_control_access(self) -> None:
        app = create_app(security=_make_security())
        forwarded_status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/",
            headers=[
                (b"x-forwarded-host", b"attacker.invalid"),
                (b"x-forwarded-proto", b"https"),
                (b"forwarded", b"host=attacker.invalid;proto=https"),
            ],
        )
        self.assertEqual(forwarded_status, 200)
        forwarded_cookie = _header_values(_headers, b"set-cookie")[0]
        self.assertIn(b"Secure", forwarded_cookie)
        bad_host_status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/",
            host="attacker.invalid",
            headers=[(b"x-forwarded-host", f"{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii"))],
        )
        self.assertEqual(bad_host_status, 403)
        bad_origin_status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/",
            origin="http://attacker.invalid",
        )
        self.assertEqual(bad_origin_status, 403)
        duplicate_host_status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/",
            headers=[
                (b"host", f"{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii")),
                (b"host", f"{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii")),
            ],
        )
        self.assertEqual(duplicate_host_status, 403)
        no_origin_status, _headers, _body = _dispatch_http(
            app,
            "POST",
            "/api/player/login",
            body=b"{}",
            headers=[(b"content-type", b"application/json")],
        )
        self.assertEqual(no_origin_status, 403)

    def test_unauthenticated_socketio_handshake_is_rejected_before_engineio(self) -> None:
        app = create_app(security=_make_security())
        messages: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        asyncio.run(
            app(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/socket.io/",
                    "query_string": b"EIO=4&transport=polling",
                    "headers": [
                        (b"host", f"{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii")),
                        (b"origin", f"http://{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii")),
                    ],
                },
                receive,
                send,
            )
        )
        self.assertEqual(messages[0]["status"], 401)
        self.assertEqual(app.security.active_socket_count, 0)

    def test_authenticated_socket_connect_origin_and_connection_cap(self) -> None:
        security = _make_security()
        app = create_app(security=security)
        grant = security.create_session()
        self.assertIsNotNone(grant)
        assert grant is not None
        connect = app.socket_server.handlers[PLAYER_NAMESPACE]["connect"]
        assets = VerifiedPlayerClientAssets(
            shell_document=b"",
            shell_content_type=b"text/html; charset=utf-8",
            client_build_id="0123456789abcdef0123456789abcdef",
            protocol_version=1,
            assets={},
        )
        app._client_assets = assets
        client_auth = {
            "client_build_id": assets.client_build_id,
            "protocol_version": assets.protocol_version,
        }

        def environ(
            origin: str | None,
            host: str = f"{PLAYER_HOST}:{PLAYER_PORT}",
        ) -> dict[str, Any]:
            headers = [(b"host", host.encode("ascii"))]
            if origin is not None:
                headers.append((b"origin", origin.encode("ascii")))
            headers.append(
                (
                    b"cookie",
                    f"{PLAYER_SESSION_COOKIE}={grant.cookie_value}".encode("ascii"),
                )
            )
            return {
                "asgi.scope": {
                    "type": "websocket",
                    "headers": headers,
                }
            }

        for index in range(MAX_CONCURRENT_PLAYER_SOCKETS):
            self.assertTrue(
                asyncio.run(
                    connect(
                        f"sid-{index}",
                        environ(f"http://{PLAYER_HOST}:{PLAYER_PORT}"),
                        client_auth,
                    )
                )
            )
        self.assertFalse(
            asyncio.run(
                connect(
                    "over-cap",
                    environ(f"http://{PLAYER_HOST}:{PLAYER_PORT}"),
                    client_auth,
                )
            )
        )
        self.assertFalse(
            asyncio.run(
                connect(
                    "bad-origin",
                    environ("http://attacker.invalid"),
                    client_auth,
                )
            )
        )
        self.assertFalse(
            asyncio.run(connect("missing-origin", environ(None), client_auth))
        )
        self.assertFalse(
            asyncio.run(
                connect(
                    "bad-host",
                    environ(f"http://{PLAYER_HOST}:{PLAYER_PORT}", "attacker.invalid"),
                    client_auth,
                )
            )
        )
        self.assertEqual(security.active_socket_count, MAX_CONCURRENT_PLAYER_SOCKETS)
        self.assertTrue(security.authorize_socket_event("sid-0"))
        security.unregister_socket("sid-0")
        self.assertTrue(
            asyncio.run(
                connect(
                    "replacement",
                    environ(f"http://{PLAYER_HOST}:{PLAYER_PORT}"),
                    client_auth,
                )
            )
        )
        self.assertEqual(security.active_socket_count, MAX_CONCURRENT_PLAYER_SOCKETS)
        socket_ids = security.stop_listener()
        self.assertIn("replacement", socket_ids)
        self.assertFalse(security.authorize_socket_event("replacement"))

    def test_all_configured_resource_boundaries_and_no_eviction(self) -> None:
        clock = _FakeClock()
        limiters = PlayerLimiters(clock)

        self.assertTrue(limiters.http_body_allowed(MAX_HTTP_BODY_BYTES))
        self.assertFalse(limiters.http_body_allowed(MAX_HTTP_BODY_BYTES + 1))
        self.assertTrue(limiters.password_allowed("p" * MAX_PASSWORD_BYTES))
        self.assertFalse(limiters.password_allowed("p" * (MAX_PASSWORD_BYTES + 1)))
        self.assertTrue(limiters.password_allowed("\u00e9" * (MAX_PASSWORD_BYTES // 2)))
        self.assertFalse(limiters.password_allowed("\u00e9" * (MAX_PASSWORD_BYTES // 2 + 1)))
        self.assertTrue(limiters.event_payload_allowed(b"e" * MAX_SOCKETIO_EVENT_BYTES))
        self.assertFalse(limiters.event_payload_allowed(b"e" * (MAX_SOCKETIO_EVENT_BYTES + 1)))
        exact_event = {"text": "e" * (MAX_SOCKETIO_EVENT_BYTES - 11)}
        oversized_event = {"text": "e" * (MAX_SOCKETIO_EVENT_BYTES - 10)}
        self.assertTrue(limiters.event_payload_allowed(exact_event))
        self.assertFalse(limiters.event_payload_allowed(oversized_event))
        self.assertTrue(limiters.snapshot_allowed(b"s" * MAX_SNAPSHOT_BYTES))
        self.assertFalse(limiters.snapshot_allowed(b"s" * (MAX_SNAPSHOT_BYTES + 1)))
        self.assertTrue(limiters.replay_allowed([b"r"] * MAX_REPLAY_EVENTS))
        self.assertFalse(limiters.replay_allowed([b"r"] * (MAX_REPLAY_EVENTS + 1)))
        self.assertTrue(limiters.replay_allowed([b"r" * MAX_REPLAY_BYTES]))
        self.assertFalse(limiters.replay_allowed([b"r" * (MAX_REPLAY_BYTES + 1)]))

        for _attempt in range(LOGIN_ATTEMPTS_PER_WINDOW):
            self.assertTrue(limiters.allow_login_attempt())
        self.assertFalse(limiters.allow_login_attempt())
        clock.advance(LOGIN_ATTEMPT_WINDOW_SECONDS)
        self.assertTrue(limiters.allow_login_attempt())

        security = _make_security(clock=clock)
        challenges = [security.issue_prelogin_challenge() for _index in range(MAX_PRELOGIN_CHALLENGES)]
        self.assertTrue(all(challenge is not None for challenge in challenges))
        self.assertIsNone(security.issue_prelogin_challenge())
        assert challenges[0] is not None
        self.assertTrue(
            security.consume_prelogin_challenge(
                challenges[0].cookie_value,
                challenges[0].csrf_nonce,
            )
        )
        self.assertIsNotNone(security.issue_prelogin_challenge())
        grants = [security.create_session() for _index in range(MAX_ACTIVE_SESSIONS)]
        self.assertTrue(all(grant is not None for grant in grants))
        self.assertEqual(security.active_session_count, MAX_ACTIVE_SESSIONS)
        self.assertIsNone(security.create_session())
        assert grants[0] is not None
        self.assertIsNotNone(security.session_id_for_cookie(grants[0].cookie_value))
        self.assertEqual(security.revoke_session(grants[0].cookie_value, grants[0].csrf_token), [])
        self.assertIsNotNone(security.create_session())

        first = next(grant for grant in grants if grant is not None and security.session_id_for_cookie(grant.cookie_value))
        session_id = security.session_id_for_cookie(first.cookie_value)
        self.assertIsNotNone(session_id)
        assert session_id is not None
        self.assertEqual(limiters.session_count(), 0)
        self.assertTrue(security.limiters.register_session(session_id))
        self.assertTrue(security.limiters.admit_input(session_id, "i" * MAX_PLAYER_INPUT_BYTES).allowed)
        self.assertFalse(security.limiters.admit_input(session_id, "i" * (MAX_PLAYER_INPUT_BYTES + 1)).allowed)
        for _input in range(PLAYER_INPUTS_PER_SESSION_PER_WINDOW - 1):
            self.assertTrue(security.limiters.admit_input(session_id, "ok").allowed)
        self.assertFalse(security.limiters.admit_input(session_id, "over-rate").allowed)
        clock.advance(PLAYER_INPUT_WINDOW_SECONDS)
        self.assertTrue(security.limiters.admit_input(session_id, "window-reset").allowed)

        self.assertTrue(security.limiters.try_admit_command())
        self.assertFalse(security.limiters.try_admit_command())
        self.assertTrue(security.limiters.finish_command())
        self.assertTrue(security.limiters.try_admit_command())
        self.assertTrue(security.limiters.finish_command())
        self.assertFalse(security.limiters.finish_command())

        for _read in range(EXPENSIVE_READS_PER_SESSION_PER_WINDOW):
            self.assertTrue(security.limiters.allow_expensive_read(session_id))
        self.assertFalse(security.limiters.allow_snapshot_read(session_id))
        clock.advance(READ_WINDOW_SECONDS)
        self.assertTrue(security.limiters.allow_snapshot_read(session_id))
        for _read in range(MEDIA_READS_PER_SESSION_PER_WINDOW):
            self.assertTrue(security.limiters.allow_media_read(session_id))
        self.assertFalse(security.limiters.allow_media_read(session_id))
        clock.advance(READ_WINDOW_SECONDS)
        self.assertTrue(security.limiters.allow_media_read(session_id))

        for index in range(MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION):
            self.assertTrue(
                security.limiters.retain_receipt(session_id, f"request-{index}", {"n": index})
            )
        self.assertFalse(
            security.limiters.retain_receipt(
                session_id,
                "request-over-cap",
                {"n": MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION},
            )
        )
        self.assertEqual(
            security.limiters.get_receipt(session_id, "request-0"),
            {"n": 0},
        )
        self.assertEqual(
            security.limiters.receipt_count(session_id),
            MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION,
        )
        pending = PlayerLimiters(clock)
        self.assertTrue(pending.try_admit_command())
        pending.clear_sessions()
        self.assertFalse(pending.try_admit_command())
        self.assertTrue(pending.finish_command())

    def test_http_body_limit_is_checked_before_json_parsing(self) -> None:
        app = create_app(security=_make_security())
        boundary_body = b" " * MAX_HTTP_BODY_BYTES
        boundary_status, _headers, _body = _dispatch_http(
            app,
            "POST",
            "/api/player/login",
            body=boundary_body,
            headers=[(b"content-type", b"application/json")],
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(boundary_status, 400)
        oversized_body = b"{" + b" " * MAX_HTTP_BODY_BYTES
        with mock.patch("web.extensions.player.app.json.loads") as json_parser:
            status, _headers, _body = _dispatch_http(
                app,
                "POST",
                "/api/player/login",
                body=oversized_body,
                headers=[(b"content-type", b"application/json")],
                origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            )
            json_parser.assert_not_called()
        self.assertEqual(status, 413)
        self.assertEqual(app.security.active_session_count, 0)

    def test_listener_rejects_non_loopback_hosts_and_unconfigured_ports(self) -> None:
        listener = PlayerListener()
        for host in ("0.0.0.0", "::1", "localhost"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    listener.start(host=host)
                self.assertFalse(listener.is_running)

        with self.assertRaises(ValueError):
            listener.start(port=PLAYER_PORT + 1)
        self.assertFalse(listener.is_running)

    def test_listener_start_stop_is_idempotent_and_releases_ephemeral_port(self) -> None:
        port = _free_loopback_port()
        listener = PlayerListener(test_only_port=port)
        listener.stop()

        listener.start(host=PLAYER_HOST, port=port)
        self.assertTrue(listener.is_running)
        server = listener._server
        self.assertIsNotNone(server)
        assert server is not None
        config = server.config
        self.assertEqual(config.host, PLAYER_HOST)
        self.assertEqual(config.port, port)
        self.assertEqual(config.ws, "websockets")
        self.assertEqual(config.workers, 1)
        self.assertFalse(config.reload)
        self.assertEqual(config.ws_max_size, MAX_SOCKETIO_EVENT_BYTES)
        self.assertFalse(config.proxy_headers)
        self.assertEqual(config.forwarded_allow_ips, "")
        self.assertFalse(config.server_header)
        self.assertFalse(config.access_log)
        self.assertTrue(listener._thread is not None and listener._thread.daemon)

        with socket.create_connection((PLAYER_HOST, port), timeout=1.0):
            pass

        listener.stop()
        listener.stop()
        self.assertFalse(listener.is_running)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((PLAYER_HOST, port))

    def test_imports_do_not_start_player_listener_or_import_host_from_player_package(self) -> None:
        root = Path(__file__).resolve().parents[1]
        player_script = (
            "import sys\n"
            "import web.extensions.player\n"
            "from web.extensions.player import create_app\n"
            "create_app()\n"
            "assert 'web.web_interface' not in sys.modules\n"
        )
        for module, script in (
            ("player package", player_script),
            ("host web interface", "import web.web_interface\n"),
            ("run_web entrypoint", "import run_web\n"),
        ):
            with self.subTest(module=module):
                probe_script = (
                    script
                    + "import socket\n"
                    + "probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
                    + f"probe.bind(({PLAYER_HOST!r}, {PLAYER_PORT}))\n"
                    + "probe.close()\n"
                )
                completed = subprocess.run(
                    [sys.executable, "-c", probe_script],
                    cwd=root,
                    env=os.environ.copy(),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
                )

    def test_decision_three_limits_are_centralized(self) -> None:
        self.assertEqual(LOGIN_ATTEMPTS_PER_WINDOW, 10)
        self.assertEqual(LOGIN_ATTEMPT_WINDOW_SECONDS, 60)
        self.assertEqual(MAX_ACTIVE_SESSIONS, 16)
        self.assertEqual(MAX_PRELOGIN_CHALLENGES, MAX_ACTIVE_SESSIONS)
        self.assertEqual(MAX_CONCURRENT_PLAYER_SOCKETS, 8)
        self.assertEqual(MAX_HTTP_BODY_BYTES, 16 * 1024)
        self.assertEqual(MAX_SOCKETIO_EVENT_BYTES, 16 * 1024)
        self.assertEqual(MAX_PASSWORD_BYTES, 1024)
        self.assertEqual(MAX_PLAYER_INPUT_BYTES, 4 * 1024)
        self.assertEqual(PLAYER_INPUTS_PER_SESSION_PER_WINDOW, 12)
        self.assertEqual(PLAYER_INPUT_WINDOW_SECONDS, 60)
        self.assertEqual(MAX_ADMITTED_PLAYER_COMMANDS, 1)
        self.assertEqual(MAX_SNAPSHOT_BYTES, 256 * 1024)
        self.assertEqual(MAX_REPLAY_EVENTS, 256)
        self.assertEqual(MAX_REPLAY_BYTES, 256 * 1024)
        self.assertEqual(EXPENSIVE_READS_PER_SESSION_PER_WINDOW, 60)
        self.assertEqual(MEDIA_READS_PER_SESSION_PER_WINDOW, 30)
        self.assertEqual(MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION, 1024)


if __name__ == "__main__":
    unittest.main()
