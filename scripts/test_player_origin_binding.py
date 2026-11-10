# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for exact, generation-scoped player origin binding."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from web.extensions.opentunnel_sharing.origin_binding import PublicOriginBinder
from web.extensions.player import PLAYER_HOST, PLAYER_NAMESPACE, PLAYER_PORT, create_app
from web.extensions.player.app import VerifiedPlayerClientAssets
from web.extensions.player.auth import (
    PLAYER_SESSION_COOKIE,
    PRELOGIN_CSRF_COOKIE,
    PlayerSecurity,
)

LOCAL_HOST = f"{PLAYER_HOST}:{PLAYER_PORT}"
LOCAL_ORIGIN = f"http://{PLAYER_HOST}:{PLAYER_PORT}"
PUBLIC_HOST = "x.example"
PUBLIC_ORIGIN = "https://x.example"


def _dispatch_http(
    app: Any,
    method: str,
    path: str,
    *,
    host: str = LOCAL_HOST,
    origin: str | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
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
    body_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "method": method,
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "headers": selected_headers,
            },
            receive,
            send,
        )
    )
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], start["headers"], response_body


class PlayerOriginBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.security = PlayerSecurity(lambda: None)
        self.binder = PublicOriginBinder(self.security)
        self.assertTrue(self.binder.begin_generation(1))

    def _bind(self, origin: object = PUBLIC_ORIGIN, generation: int = 1) -> bool:
        return self.binder.bind(origin, generation, ready=True)

    def test_local_pair_remains_valid_bound_and_unbound(self) -> None:
        self.assertEqual(self.security.public_origin_status, (False, None))
        self.assertTrue(
            self.security.request_identity_is_valid(
                LOCAL_HOST, LOCAL_ORIGIN, require_origin=True
            )
        )
        self.assertTrue(
            self.security.request_identity_is_valid(
                LOCAL_HOST, None, require_origin=False
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )

        self.assertTrue(self._bind())
        self.assertEqual(self.security.public_origin_status, (True, 1))
        self.assertTrue(
            self.security.request_identity_is_valid(
                LOCAL_HOST, LOCAL_ORIGIN, require_origin=True
            )
        )
        self.assertTrue(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )

    def test_exact_public_pair_reaches_http_and_socket_handshake_validation(self) -> None:
        self.assertTrue(self._bind())
        app = create_app(security=self.security)

        status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/not-a-player-route",
            host=PUBLIC_HOST,
            origin=PUBLIC_ORIGIN,
        )
        self.assertEqual(status, 404)

        grant = self.security.create_session()
        self.assertIsNotNone(grant)
        assert grant is not None
        assets = VerifiedPlayerClientAssets(
            shell_document=b"",
            shell_content_type=b"text/html; charset=utf-8",
            client_build_id="0123456789abcdef0123456789abcdef",
            protocol_version=1,
            assets={},
        )
        app._client_assets = assets
        connect = app.socket_server.handlers[PLAYER_NAMESPACE]["connect"]
        environment = {
            "asgi.scope": {
                "type": "websocket",
                "headers": [
                    (b"host", PUBLIC_HOST.encode("ascii")),
                    (b"origin", PUBLIC_ORIGIN.encode("ascii")),
                    (
                        b"cookie",
                        f"{PLAYER_SESSION_COOKIE}={grant.cookie_value}".encode("ascii"),
                    ),
                ],
            }
        }
        auth = {
            "client_build_id": assets.client_build_id,
            "protocol_version": assets.protocol_version,
        }
        self.assertTrue(asyncio.run(connect("public-socket", environment, auth)))
        self.assertTrue(self.security.authorize_socket_event("public-socket"))
        self.assertIn("public-socket", self.security.authorized_socket_ids())

        self.binder.clear("stop")
        self.assertFalse(self.security.authorize_socket_event("public-socket"))
        self.assertNotIn("public-socket", self.security.authorized_socket_ids())

    def test_unbound_or_mixed_public_identity_is_rejected(self) -> None:
        app = create_app(security=self.security)
        for host, origin in (
            (PUBLIC_HOST, PUBLIC_ORIGIN),
            (PUBLIC_HOST, LOCAL_ORIGIN),
            (LOCAL_HOST, PUBLIC_ORIGIN),
        ):
            with self.subTest(host=host, origin=origin):
                status, _headers, _body = _dispatch_http(
                    app,
                    "GET",
                    "/not-a-player-route",
                    host=host,
                    origin=origin,
                )
                self.assertEqual(status, 403)
        self.assertEqual(self.security.public_origin_status, (False, None))

    def test_wildcard_suffix_subdomain_parent_and_case_variants_are_rejected(self) -> None:
        self.assertTrue(self._bind())
        request_pairs = (
            ("*.example", "https://*.example"),
            ("evil-example.trycloudflare.test", "https://evil-example.trycloudflare.test"),
            ("evil-x.example", "https://evil-x.example"),
            ("a.x.example", "https://a.x.example"),
            ("example", "https://example"),
            ("X.example", "https://x.example"),
            ("x.example", "https://X.example"),
        )
        for host, origin in request_pairs:
            with self.subTest(host=host, origin=origin):
                self.assertFalse(
                    self.security.request_identity_is_valid(
                        host, origin, require_origin=True
                    )
                )

        invalid_status_origins = (
            "https://*.example.test",
            "https://*.x.example",
            "https://X.example",
            "HTTPS://x.example",
        )
        for index, invalid_origin in enumerate(invalid_status_origins, start=1):
            with self.subTest(status_origin=invalid_origin):
                if index > 1:
                    self.assertTrue(self.binder.begin_generation(index))
                self.assertFalse(self.binder.bind(invalid_origin, index, ready=True))
                self.assertFalse(self.binder.is_bound)
                self.assertEqual(self.security.public_origin_status, (False, None))

    def test_http_port_mismatch_missing_and_extra_ports_are_rejected(self) -> None:
        self.assertTrue(self._bind())
        for host, origin in (
            (PUBLIC_HOST, "http://x.example"),
            ("x.example:8443", PUBLIC_ORIGIN),
            (PUBLIC_HOST, "https://x.example:8443"),
            ("x.example:443", "https://x.example:443"),
        ):
            with self.subTest(host=host, origin=origin):
                self.assertFalse(
                    self.security.request_identity_is_valid(
                        host, origin, require_origin=True
                    )
                )

        self.binder.clear("stop")
        self.assertTrue(self._bind("https://x.example:8443"))
        self.assertTrue(
            self.security.request_identity_is_valid(
                "x.example:8443", "https://x.example:8443", require_origin=True
            )
        )
        for host, origin in (
            (PUBLIC_HOST, "https://x.example:8443"),
            ("x.example:8443", PUBLIC_ORIGIN),
            ("x.example:9443", "https://x.example:8443"),
            ("x.example:8443", "https://x.example:9443"),
        ):
            with self.subTest(host=host, origin=origin):
                self.assertFalse(
                    self.security.request_identity_is_valid(
                        host, origin, require_origin=True
                    )
                )

    def test_explicit_default_port_is_canonicalized_and_not_accepted_on_requests(self) -> None:
        self.assertTrue(self._bind("https://x.example:443"))
        self.assertTrue(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                "x.example:443", "https://x.example:443", require_origin=True
            )
        )

    def test_invalid_status_origins_fail_closed_and_clear_prior_binding(self) -> None:
        invalid_origins: tuple[object, ...] = (
            "http://x.example",
            "https://user@x.example",
            "https://x.example/",
            "https://x.example/path",
            "https://x.example?query=1",
            "https://x.example#fragment",
            "https://x.example:",
            "https://x.example:abc",
            "https://x.example:0",
            "https://x.example:65536",
            "https://x.example:0443",
            "https://x.example.",
            "https://127.0.0.1",
            "https://[::1]",
            "https://x.example\r.evil",
            "https://x.example evil",
            "https://\u0435xample.test",
            "https://xn--xample-2of.test",
            "",
            None,
            123,
        )
        for index, invalid_origin in enumerate(invalid_origins, start=1):
            with self.subTest(status_origin=invalid_origin):
                if index > 1:
                    self.assertTrue(self.binder.begin_generation(index))
                self.assertTrue(self.binder.bind(PUBLIC_ORIGIN, index, ready=True))
                self.assertTrue(self.binder.is_bound)
                self.assertFalse(self.binder.bind(invalid_origin, index, ready=True))
                self.assertFalse(self.binder.is_bound)
                self.assertEqual(self.binder.state, "invalid_origin")
                self.assertEqual(self.security.public_origin_status, (False, None))
                self.assertFalse(
                    self.security.request_identity_is_valid(
                        PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
                    )
                )
                self.assertFalse(self.binder.bind(PUBLIC_ORIGIN, index, ready=True))

    def test_readiness_and_stale_generation_are_required_without_clobbering_current(self) -> None:
        self.assertFalse(self.binder.bind(PUBLIC_ORIGIN, 0, ready=True))
        self.assertFalse(self.binder.is_bound)
        self.assertFalse(self.binder.bind(PUBLIC_ORIGIN, 1, ready=False))
        self.assertEqual(self.binder.state, "not_ready")
        self.assertEqual(self.security.public_origin_status, (False, None))

        self.assertTrue(self._bind())
        self.assertFalse(self.binder.bind("https://old.example", 0, ready=True))
        self.assertTrue(self.binder.is_bound)
        self.assertEqual(self.binder.generation, 1)

        self.assertTrue(self.binder.begin_generation(2))
        self.assertFalse(self.binder.is_bound)
        self.assertFalse(self.binder.bind(PUBLIC_ORIGIN, 1, ready=True))
        self.assertEqual(self.security.public_origin_status, (False, None))

    def test_changed_origin_within_generation_clears_and_fails_closed(self) -> None:
        self.assertTrue(self._bind())
        self.assertFalse(self.binder.bind("https://changed.example", 1, ready=True))
        self.assertEqual(self.binder.state, "origin_changed")
        self.assertFalse(self.binder.is_bound)
        self.assertEqual(self.security.public_origin_status, (False, None))
        self.assertFalse(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                "changed.example", "https://changed.example", require_origin=True
            )
        )
        self.assertFalse(self.binder.bind(PUBLIC_ORIGIN, 1, ready=True))
        self.assertEqual(self.binder.state, "origin_changed")
        self.binder.clear("failed")
        self.assertFalse(self.binder.bind(PUBLIC_ORIGIN, 1, ready=True))
        self.assertFalse(self.binder.is_bound)

    def test_lifecycle_clear_reasons_revert_to_local_only_and_new_generation_rebinds(self) -> None:
        for generation, reason in enumerate(
            ("stop", "failed", "degraded", "rotation"), start=1
        ):
            if generation > 1:
                self.assertTrue(self.binder.begin_generation(generation))
            self.assertTrue(self.binder.bind(PUBLIC_ORIGIN, generation, ready=True))
            self.binder.clear(reason)
            self.assertEqual(self.binder.state, reason)
            self.assertFalse(self.binder.is_bound)
            self.assertEqual(self.security.public_origin_status, (False, None))
            self.assertTrue(
                self.security.request_identity_is_valid(
                    LOCAL_HOST, LOCAL_ORIGIN, require_origin=True
                )
            )
            self.assertFalse(
                self.security.request_identity_is_valid(
                    PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
                )
            )

        self.assertTrue(self.binder.begin_generation(5))
        self.assertTrue(self.binder.bind("https://new.example", 5, ready=True))
        self.assertTrue(
            self.security.request_identity_is_valid(
                "new.example", "https://new.example", require_origin=True
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(self.binder.begin_generation(5))
        self.assertFalse(self.binder.begin_generation(4))

    def test_player_listener_stop_also_clears_the_public_binding(self) -> None:
        self.assertTrue(self._bind())
        self.security.stop_listener()
        self.assertFalse(self.binder.is_bound)
        self.assertEqual(self.binder.state, "unbound")
        self.assertEqual(self.security.public_origin_status, (False, None))
        self.assertFalse(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )

    def test_player_listener_restart_requires_a_fresh_public_origin_check(self) -> None:
        self.assertTrue(self._bind())
        self.security.start_listener()
        self.assertFalse(self.binder.is_bound)
        self.assertEqual(self.binder.state, "unbound")
        self.assertEqual(self.security.public_origin_status, (False, None))
        self.assertFalse(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )

    def test_forwarded_headers_do_not_establish_identity_or_change_cookie_policy(self) -> None:
        self.assertTrue(self._bind())
        app = create_app(security=self.security)
        status, response_headers, _body = _dispatch_http(
            app,
            "GET",
            "/",
            host=PUBLIC_HOST,
            origin=PUBLIC_ORIGIN,
            headers=[
                (b"x-forwarded-host", b"attacker.invalid"),
                (b"x-forwarded-proto", b"http"),
                (b"forwarded", b"host=attacker.invalid;proto=http"),
            ],
        )
        self.assertEqual(status, 200)
        set_cookie = next(
            value for name, value in response_headers if name.lower() == b"set-cookie"
        )
        self.assertIn(b"Secure", set_cookie)
        self.assertNotIn(b"Domain=", set_cookie)

        spoofed_status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/not-a-player-route",
            host="attacker.invalid",
            origin="https://attacker.invalid",
            headers=[
                (b"x-forwarded-host", PUBLIC_HOST.encode("ascii")),
                (b"x-forwarded-proto", b"https"),
            ],
        )
        self.assertEqual(spoofed_status, 403)

    def test_bound_https_login_still_requires_the_existing_csrf_proof(self) -> None:
        self.assertTrue(self._bind())
        app = create_app(security=self.security)
        shell_status, shell_headers, shell_body = _dispatch_http(
            app, "GET", "/", host=PUBLIC_HOST, origin=PUBLIC_ORIGIN
        )
        self.assertEqual(shell_status, 200)
        nonce_match = re.search(rb'name="csrf_token" value="([A-Za-z0-9_-]+)"', shell_body)
        self.assertIsNotNone(nonce_match)
        nonce = nonce_match.group(1).decode("ascii") if nonce_match else ""
        prelogin_cookie = next(
            value.split(b"=", 1)[1].split(b";", 1)[0]
            for name, value in shell_headers
            if name.lower() == b"set-cookie"
            and value.startswith(PRELOGIN_CSRF_COOKIE.encode("ascii") + b"=")
        )
        body = json.dumps(
            {"password": "unused", "csrf_token": f"{nonce}-invalid"},
            separators=(",", ":"),
        ).encode("ascii")
        status, _headers, response_body = _dispatch_http(
            app,
            "POST",
            "/api/player/login",
            host=PUBLIC_HOST,
            origin=PUBLIC_ORIGIN,
            headers=[
                (b"content-type", b"application/json"),
                (
                    b"cookie",
                    PRELOGIN_CSRF_COOKIE.encode("ascii") + b"=" + prelogin_cookie,
                )
            ],
            body=body,
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(response_body), {"error": "csrf_rejected"})
        self.assertEqual(self.security.active_session_count, 0)

    def test_binding_observability_and_logs_never_include_the_origin(self) -> None:
        with self.assertNoLogs():
            self.assertTrue(self._bind())
            self.assertFalse(self.binder.bind("https://changed.example", 1, ready=True))
        observable = " ".join(
            (
                repr(self.binder),
                repr(self.security),
                repr(self.security.public_origin_status),
                self.binder.state,
            )
        )
        self.assertNotIn(PUBLIC_ORIGIN, observable)
        self.assertNotIn("changed.example", observable)

    def test_concurrent_bind_clear_and_validation_are_thread_safe(self) -> None:
        barrier = threading.Barrier(8)

        def exercise(index: int) -> int:
            barrier.wait(timeout=3)
            checks = 0
            for _iteration in range(30):
                if index % 3 == 0:
                    self.binder.clear("degraded")
                elif index % 3 == 1:
                    self.binder.bind(PUBLIC_ORIGIN, 1, ready=True)
                else:
                    checks += int(
                        self.security.request_identity_is_valid(
                            PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
                        )
                    )
            return checks

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(exercise, range(8)))
        self.assertEqual(len(results), 8)
        self.binder.clear("stop")
        self.assertTrue(
            self.security.request_identity_is_valid(
                LOCAL_HOST, LOCAL_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                PUBLIC_HOST, PUBLIC_ORIGIN, require_origin=True
            )
        )


if __name__ == "__main__":
    unittest.main()
