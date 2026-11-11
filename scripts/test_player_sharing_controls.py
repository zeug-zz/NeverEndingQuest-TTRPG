# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for facilitator-local player-sharing routes and UI."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from flask import Flask

from web.extensions.opentunnel_sharing.controller import (
    ReadinessChecks,
    SharingCounters,
    SharingSnapshot,
    SharingState,
)
from web.extensions.opentunnel_sharing.service import (
    SharingActionResult,
    SharingServiceStatus,
)
from web.extensions.opentunnel_sharing.verifier_store import IssuedCredential
from web.extensions.player import PLAYER_NAMESPACE, create_app
from web.extensions.player.auth import PlayerSecurity
from web.extensions.player.capabilities import (
    PLAYER_HTTP_ALLOWLIST,
    PLAYER_SOCKET_EMISSION_ALLOWLIST,
    PLAYER_SOCKET_EVENT_ALLOWLIST,
    PLAYER_SOCKET_LIFECYCLE_EVENTS,
)
from web.routes.player_sharing_routes import register_player_sharing_routes


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8357"
HOST_AUTHORITY = "127.0.0.1:8357"
SENTINEL_CREDENTIAL = "player-credential-sentinel_A1"
ROTATED_CREDENTIAL = "rotated-credential-sentinel_B2"
SENTINEL_INVITATION = "https://neq-share.account.opentunnel.xyz"
PLAYER_SHARING_PATHS = (
    "/api/player-sharing/status",
    "/api/player-sharing/initialize-identity",
    "/api/player-sharing/issue-access",
    "/api/player-sharing/start",
    "/api/player-sharing/stop",
    "/api/player-sharing/rotate",
    "/api/player-sharing/revoke",
    "/api/player-sharing/copy-invitation",
)


class FakeSharingService:
    """In-memory service fake; no listener, process, tunnel, or network access."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state = SharingSnapshot(
            SharingState.INITIALIZING_REQUIRED,
            "identity_not_initialized",
            0,
            ReadinessChecks(),
            SharingCounters(),
        )
        self.profile_state = "absent"
        self.initialized = False
        self.credential_state = "absent"
        self.credential_generation: int | None = None
        self.last_credential: IssuedCredential | None = None

    def diagnostics(self) -> SharingServiceStatus:
        self.calls.append("diagnostics")
        return self._status()

    def initialize_identity(self, *, facilitator_confirmed: bool) -> SharingActionResult:
        self.calls.append("initialize_identity")
        if facilitator_confirmed is not True:
            return self._result(False, "facilitator_confirmation_required")
        self.profile_state = "ready"
        self.initialized = True
        self.state = replace(
            self.state,
            state=SharingState.OFF,
            reason="off",
        )
        return self._result(True, "identity_initialized")

    def issue_access(self) -> SharingActionResult:
        self.calls.append("issue_access")
        self.credential_state = "present"
        self.credential_generation = 1
        self.last_credential = IssuedCredential(SENTINEL_CREDENTIAL)
        return self._result(True, "credential_issued", credential=self.last_credential)

    def start(self) -> SharingActionResult:
        self.calls.append("start")
        self.state = replace(
            self.state,
            state=SharingState.READY,
            reason="ready",
            generation=1,
        )
        return self._result(True, "ready")

    def stop(self) -> SharingActionResult:
        self.calls.append("stop")
        self.state = replace(self.state, state=SharingState.OFF, reason="stopped")
        return self._result(True, "stopped")

    def rotate_access(self) -> SharingActionResult:
        self.calls.append("rotate_access")
        self.credential_state = "present"
        self.credential_generation = 2
        self.last_credential = IssuedCredential(ROTATED_CREDENTIAL)
        return self._result(True, "credential_rotated", credential=self.last_credential)

    def revoke_access(self) -> SharingActionResult:
        self.calls.append("revoke_access")
        self.credential_state = "absent"
        self.credential_generation = None
        self.state = replace(self.state, state=SharingState.OFF, reason="off")
        return self._result(True, "access_revoked")

    def copy_invitation(self) -> SharingActionResult:
        self.calls.append("copy_invitation")
        return self._result(True, "invitation_ready", invitation=SENTINEL_INVITATION)

    def _status(self) -> SharingServiceStatus:
        return SharingServiceStatus(
            lifecycle=self.state,
            profile_state=self.profile_state,
            identity_initialized=self.initialized,
            credential_state=self.credential_state,
            credential_generation=self.credential_generation,
        )

    def _result(
        self,
        ok: bool,
        reason: str,
        *,
        credential: IssuedCredential | None = None,
        invitation: str | None = None,
    ) -> SharingActionResult:
        return SharingActionResult(
            operation="fake",
            ok=ok,
            reason=reason,
            status=self._status(),
            credential=credential,
            invitation=invitation,
        )


def _build_host_app(
    service_provider,
    *,
    start_blocked=None,
) -> Flask:
    app = Flask(__name__)
    app.config.update(TESTING=True)
    register_player_sharing_routes(
        app,
        service_provider,
        host_port=8357,
        start_blocked=start_blocked,
    )
    return app


def _headers(origin: str = BASE_URL) -> dict[str, str]:
    return {"Origin": origin, "Host": HOST_AUTHORITY}


async def _dispatch_player_asgi(app: Any, path: str) -> int:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:8370")],
        },
        receive,
        send,
    )
    response = next(message for message in messages if message["type"] == "http.response.start")
    return int(response["status"])


class PlayerSharingControlsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeSharingService()
        self.provider_calls = 0

        def provider() -> FakeSharingService:
            self.provider_calls += 1
            return self.service

        self.app = _build_host_app(provider)
        self.client = self.app.test_client()

    def test_registering_routes_is_lazy_and_all_controls_work_with_fake_service(self) -> None:
        self.assertEqual(self.provider_calls, 0)
        status = self.client.get(
            "/api/player-sharing/status",
            headers={"Host": HOST_AUTHORITY},
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json["status"]["state"], "initializing_required")
        self.assertEqual(status.json["status"]["reason"], "identity_not_initialized")
        self.assertNotIn(SENTINEL_CREDENTIAL, status.get_data(as_text=True))
        self.assertNotIn(SENTINEL_INVITATION, status.get_data(as_text=True))

        initialized = self.client.post(
            "/api/player-sharing/initialize-identity",
            json={"confirm": True},
            headers=_headers(),
        )
        self.assertEqual(initialized.status_code, 200)
        self.assertTrue(initialized.json["ok"])

        issued = self.client.post(
            "/api/player-sharing/issue-access",
            json={},
            headers=_headers(),
        )
        self.assertEqual(issued.status_code, 200)
        self.assertEqual(issued.json["credential"], SENTINEL_CREDENTIAL)
        self.assertIn("no-store", issued.headers["Cache-Control"])
        self.assertEqual(issued.headers["Pragma"], "no-cache")
        with self.assertRaises(RuntimeError):
            self.service.last_credential.reveal()  # type: ignore[union-attr]

        started = self.client.post(
            "/api/player-sharing/start",
            json={},
            headers=_headers(),
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json["status"]["state"], "ready")

        copied = self.client.post(
            "/api/player-sharing/copy-invitation",
            json={},
            headers=_headers(),
        )
        self.assertEqual(copied.status_code, 200)
        self.assertEqual(copied.json["invitation"], SENTINEL_INVITATION)
        self.assertIn("no-store", copied.headers["Cache-Control"])

        rotated = self.client.post(
            "/api/player-sharing/rotate",
            json={},
            headers=_headers(),
        )
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(rotated.json["credential"], ROTATED_CREDENTIAL)
        self.assertIn("no-store", rotated.headers["Cache-Control"])

        revoked = self.client.post(
            "/api/player-sharing/revoke",
            json={},
            headers=_headers(),
        )
        stopped = self.client.post(
            "/api/player-sharing/stop",
            json={},
            headers=_headers(),
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(
            self.service.calls,
            [
                "diagnostics",
                "initialize_identity",
                "issue_access",
                "start",
                "copy_invitation",
                "rotate_access",
                "revoke_access",
                "stop",
            ],
        )
        self.assertGreater(self.provider_calls, 0)

    def test_error_bodies_are_uniform_bounded_reason_codes_and_invalid_requests_are_lazy(self) -> None:
        bad_type = self.client.post(
            "/api/player-sharing/start",
            data="x=1",
            content_type="application/x-www-form-urlencoded",
            headers=_headers(),
        )
        self.assertEqual(bad_type.status_code, 415)
        self.assertEqual(bad_type.json, {"ok": False, "reason": "json_required"})
        self.assertEqual(self.provider_calls, 0)

        oversized = self.client.post(
            "/api/player-sharing/start",
            data=b" " * 4097,
            content_type="application/json",
            headers=_headers(),
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json, {"ok": False, "reason": "request_too_large"})
        self.assertEqual(self.provider_calls, 0)

        malformed = self.client.post(
            "/api/player-sharing/start",
            data='{"confirm":true,"confirm":false}',
            content_type="application/json",
            headers=_headers(),
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json, {"ok": False, "reason": "invalid_json"})
        self.assertEqual(self.provider_calls, 0)

    def test_wrong_origin_host_and_non_loopback_requests_are_rejected(self) -> None:
        wrong_origin = self.client.post(
            "/api/player-sharing/start",
            json={},
            headers=_headers("http://example.invalid:8357"),
        )
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(wrong_origin.json, {"ok": False, "reason": "origin_not_allowed"})

        mismatched_origin_authority = self.client.post(
            "/api/player-sharing/start",
            json={},
            headers=_headers("http://localhost:8357"),
        )
        self.assertEqual(mismatched_origin_authority.status_code, 403)

        wrong_host = self.client.post(
            "/api/player-sharing/start",
            json={},
            headers={"Origin": BASE_URL, "Host": "127.0.0.1:8358"},
        )
        self.assertEqual(wrong_host.status_code, 403)
        self.assertEqual(wrong_host.json, {"ok": False, "reason": "host_not_allowed"})

        no_origin = self.client.post(
            "/api/player-sharing/start",
            json={},
            headers={"Host": HOST_AUTHORITY},
        )
        self.assertEqual(no_origin.status_code, 403)

        non_loopback = self.client.post(
            "/api/player-sharing/start",
            json={},
            headers=_headers(),
            environ_base={"REMOTE_ADDR": "192.0.2.44"},
        )
        self.assertEqual(non_loopback.status_code, 403)
        self.assertEqual(self.provider_calls, 0)

    def test_initialize_identity_requires_explicit_boolean_confirmation(self) -> None:
        for payload in ({}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/player-sharing/initialize-identity",
                    json=payload,
                    headers=_headers(),
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json, {"ok": False, "reason": "confirmation_required"})
        self.assertNotIn("initialize_identity", self.service.calls)
        self.assertEqual(self.provider_calls, 0)

    def test_dev_listener_conflict_fails_closed_before_service_construction(self) -> None:
        provider_calls: list[bool] = []
        service = FakeSharingService()

        def provider() -> FakeSharingService:
            provider_calls.append(True)
            return service

        app = _build_host_app(provider, start_blocked=lambda: True)
        response = app.test_client().post(
            "/api/player-sharing/start",
            json={},
            headers=_headers(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json, {"ok": False, "reason": "listener_port_in_use"})
        self.assertEqual(provider_calls, [])
        self.assertNotIn("start", service.calls)

    def test_secrets_and_invitation_are_never_written_to_logs_or_status(self) -> None:
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        self.app.logger.addHandler(handler)
        try:
            self.client.post(
                "/api/player-sharing/initialize-identity",
                json={"confirm": True},
                headers=_headers(),
            )
            issued = self.client.post(
                "/api/player-sharing/issue-access",
                json={},
                headers=_headers(),
            )
            copied = self.client.post(
                "/api/player-sharing/copy-invitation",
                json={},
                headers=_headers(),
            )
            status = self.client.get(
                "/api/player-sharing/status",
                headers={"Host": HOST_AUTHORITY},
            )
        finally:
            self.app.logger.removeHandler(handler)
            handler.close()
        self.assertEqual(issued.status_code, 200)
        self.assertEqual(copied.status_code, 200)
        status_text = status.get_data(as_text=True)
        self.assertNotIn(SENTINEL_CREDENTIAL, status_text)
        self.assertNotIn(SENTINEL_INVITATION, status_text)
        logs = log_stream.getvalue()
        self.assertNotIn(SENTINEL_CREDENTIAL, logs)
        self.assertNotIn(ROTATED_CREDENTIAL, logs)
        self.assertNotIn(SENTINEL_INVITATION, logs)

    def test_player_asgi_app_has_no_sharing_routes_or_socket_events(self) -> None:
        player_app = create_app(security=PlayerSecurity(lambda: None))
        self.assertEqual(player_app.registered_socket_events, PLAYER_SOCKET_EVENT_ALLOWLIST)
        self.assertEqual(player_app.socket_server.namespaces, [PLAYER_NAMESPACE])
        self.assertEqual(
            set(player_app.socket_server.handlers.get(PLAYER_NAMESPACE, {})),
            set(PLAYER_SOCKET_EVENT_ALLOWLIST | PLAYER_SOCKET_LIFECYCLE_EVENTS),
        )
        self.assertFalse(
            any("sharing" in event.casefold() for event in player_app.registered_socket_events)
        )
        for path in PLAYER_SHARING_PATHS:
            with self.subTest(path=path):
                self.assertEqual(asyncio.run(_dispatch_player_asgi(player_app, path)), 404)

        self.assertEqual(
            PLAYER_HTTP_ALLOWLIST,
            frozenset(
                {
                    ("GET", "/"),
                    ("GET", "/static/player/<asset-id>"),
                    ("POST", "/api/player/login"),
                    ("POST", "/api/player/logout"),
                    ("GET", "/api/player/snapshot"),
                    ("GET", "/api/player/media/<media-id>"),
                }
            ),
        )
        self.assertEqual(
            PLAYER_SOCKET_EVENT_ALLOWLIST,
            frozenset(
                {
                    "player.snapshot.request",
                    "player.active_pc.select",
                    "player.input.submit",
                }
            ),
        )
        self.assertEqual(
            PLAYER_SOCKET_EMISSION_ALLOWLIST,
            frozenset({"player.snapshot", "player.event", "player.input.receipt", "player.error"}),
        )

    def test_host_template_and_script_keep_the_invitation_transient_and_local(self) -> None:
        template = (REPOSITORY_ROOT / "web/templates/game_interface.html").read_text(encoding="utf-8")
        script = (REPOSITORY_ROOT / "web/static/js/player_sharing.js").read_text(encoding="utf-8")
        self.assertIn("Share with players", template)
        self.assertIn("Initialize sharing identity", template)
        self.assertIn("Copy invitation", template)
        self.assertIn("player-sharing-secret-value", template)
        self.assertIn("player-sharing-dismiss", template)
        self.assertIn("filename='js/player_sharing.js'", template)
        self.assertNotIn("SENTINEL_CREDENTIAL", template + script)
        self.assertNotRegex(script, re.compile(r"\b(?:localStorage|sessionStorage)\b", re.I))
        self.assertNotRegex(script, re.compile(r"fetch\s*\(\s*['\"]https?://", re.I))
        self.assertIn("fetch('/api/player-sharing/", script)
        self.assertIn("secretValue.textContent = ''", script)
        self.assertIn("secretValue.textContent = credential", script)
        self.assertNotIn("console.log", script)

    def test_facilitator_control_states_follow_safe_status_fields(self) -> None:
        script = (REPOSITORY_ROOT / "web/static/js/player_sharing.js").read_text(encoding="utf-8")
        self.assertIn("const initialized = status.identity_initialized === true", script)
        self.assertIn("buttons.initialize.disabled = initialized", script)
        self.assertIn("buttons.issue.disabled = !initialized", script)
        self.assertIn("buttons.start.disabled = !initialized", script)
        self.assertIn("buttons.copy.disabled = state !== 'ready'", script)
        self.assertIn("buttons.rotate.disabled = !initialized", script)
        self.assertIn("buttons.revoke.disabled = status.credential_state !== 'present'", script)
        self.assertIn("buttons.stop.disabled = state === 'off' || state === 'initializing_required'", script)

    def test_host_registration_passes_the_service_provider_without_eager_invocation(self) -> None:
        source_path = REPOSITORY_ROOT / "web/web_interface.py"
        source = source_path.read_text(encoding="utf-8")
        module = compile(source, str(source_path), "exec")
        del module
        import ast

        tree = ast.parse(source, filename="web/web_interface.py")
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "register_player_sharing_routes"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [argument.id if isinstance(argument, ast.Name) else None for argument in calls[0].args],
            ["app", "_get_player_sharing_service"],
        )
        self.assertNotIsInstance(calls[0].args[1], ast.Call)


if __name__ == "__main__":
    unittest.main()
