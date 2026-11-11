# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Primary-owned live N3 lifecycle driver.

The driver is intentionally fail-closed. Every frozen row has a bounded
executor; all state-changing observations remain owned by the isolated host.
"""

from __future__ import annotations

import argparse
import ast
import errno
import hashlib
import html.parser
import http.client
import http.cookies
import io
import json
import math
import os
import re
import shutil
import shlex
import signal
import socketio
import ssl
import stat
import subprocess
import sys
import threading
import time
import tokenize
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, Sequence

import scripts.n3_lifecycle_gate as preflight_gate
from web.extensions.opentunnel_sharing.companion import (
    resolve_companion,
    verify_companion_digest,
)
from web.extensions.opentunnel_sharing.identity_bootstrap import (
    DefaultCommandRunner,
    DefaultIdentityObserver,
    IdentityObserver,
    Observation,
    RunResult,
    parse_identity_status,
)
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    MAX_UNIX_SOCKET_PATH,
    ProfileLayout,
    companion_environment,
    prepare_profile,
)
from web.extensions.opentunnel_sharing.relay_supervision import RecoveryPolicy
from web.extensions.opentunnel_sharing.supervisor import (
    MAX_STARTUP_DEADLINE_SECONDS,
    probe_process_identity,
)
from web.extensions.player.constants import PLAYER_NAMESPACE
from web.extensions.player.contracts import PROTOCOL_VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_ID = "N3-live"
MANIFEST_ID = "n3-live-lifecycle-v2"
EVIDENCE_BASE = Path("tmp/router-rollout/v2-network/n3")
CAPTURE_RELATIVE = Path("tmp/combat_capture")
HOST_PORT = 8360
PLAYER_PORT = 8370
RUN_ID_PATTERN = re.compile(r"n3-[a-z0-9][a-z0-9-]{0,62}\Z")
SHA_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
BOOKING_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
MAX_PREFLIGHT_BYTES = 1024 * 1024
MAX_LOCK_BYTES = 16 * 1024
MAX_API_RESPONSE_BYTES = 64 * 1024
MAX_API_REQUEST_BYTES = 4096
MAX_API_JSON_NODES = 1024
MAX_API_JSON_DEPTH = 16
MAX_PUBLIC_RESPONSE_BYTES = 1024 * 1024
MAX_PUBLIC_PROBE_BODY_BYTES = 8192
MAX_PLAYER_SHELL_BYTES = 512 * 1024
PUBLIC_CLIENT_TIMEOUT_SECONDS = 8.0
PUBLIC_POLL_INTERVAL_SECONDS = 0.1
MAX_PROCESS_TABLE_BYTES = 1024 * 1024
MAX_PROCESS_ANCESTRY_DEPTH = 128
MAX_HOST_OUTPUT_BYTES_PER_STREAM = 65_536
HOST_START_TIMEOUT_SECONDS = 30.0
HOST_STOP_TIMEOUT_SECONDS = 8.0
HOST_POLL_INTERVAL_SECONDS = 0.2
PROVIDER_BUDGET = 1
PROVIDER_LEDGER_NAME = "provider-attempt-ledger.jsonl"
_PROVIDER_LEDGER_RELATIVE = Path("tmp/n2")


@dataclass(frozen=True, slots=True)
class LiveRow:
    row_id: str
    name: str
    timeout_seconds: int
    precondition: str
    action: str
    expected: str
    blocked: str


LIVE_ROWS = (
    LiveRow(
        "L01", "sharing-off-local-play", 300,
        "Owned host is up; sharing is OFF.",
        "Query GET /api/player-sharing/status; inspect listener, companion process, and public exposure.",
        "Status is off or initializing_required (both sharing-inactive); port 8370 is not listening; no companion process exists; there is no public exposure.",
        "Host ownership or the required status/listener/process/public-exposure observations cannot be established safely. Any positive evidence of an unexpected listener, companion, or public exposure is FAIL.",
    ),
    LiveRow(
        "L02", "identity-init-once", 300,
        "Owned host is up; the dedicated profile identity is uninitialized; sharing is OFF.",
        "POST initialize-identity with {confirm:true}, then call it a second time.",
        "The first call returns identity_initialized=true and identity_up_invocations=1; post-checks show no residual helper or service-manager entry. The second call returns reason identity_initialized (or an equivalent already-initialized reason), identity_initialized=true, and identity_up_invocations remains exactly 1.",
        "The companion operation or positive post-checks for helper/service-manager cleanup cannot be performed or observed safely. A failed/extra up, missing cleanup, or unexpected second initialization is FAIL.",
    ),
    LiveRow(
        "L03", "issue-access-start-auth-entry", 300,
        "Owned host is up; identity initialization has passed; sharing is OFF.",
        "Issue access, start sharing, copy the invitation, and exercise the player boundary over the public URL. Keep the one-time plaintext credential and invitation URL in memory only.",
        "Issue-access returns plaintext once; start returns ready; copy-invitation returns an HTTPS URL. Over that PUBLIC URL, the player shell returns 200; an unauthenticated protected request returns 401, 403, or 404, is not a 2xx/3xx response, and has a bounded body free of gameplay, state, or session data (including snapshot fields). A 2xx/3xx response or any data-bearing response is FAIL. Host-only paths (/api/player-sharing/*, host routes, and host socket events) are refused/404 under the public Host. Login with the credential and exact Host/Origin succeeds and the cookie has Secure, HttpOnly, and SameSite. An authenticated Socket.IO websocket to /player receives initial state. A wrong credential is rejected and a forged Origin is rejected.",
        "The public URL/client path or any required boundary observation cannot be reached or measured safely. Any secret persisted or logged, public host-surface access, rejected valid login, accepted invalid credential/Origin, or missing required cookie/socket property is FAIL.",
    ),
    LiveRow(
        "L04", "duplicate-start-idempotent", 300,
        "Sharing is ready for one owned generation with one listener and one owned companion process.",
        "Invoke start a second time and observe generation, owned processes, and listener count.",
        "The second start returns current state, preserves the same generation, and leaves exactly one owned companion process and one listener.",
        "Generation identity or positive process/listener ownership/count cannot be established. A new generation, duplicate process, or duplicate listener is FAIL.",
    ),
    LiveRow(
        "L05", "relay-loss-bounded-recovery", 420,
        "Sharing is ready; the owned host and companion ancestry are known; the target child satisfies every approved relay-loss injection identity check.",
        "Inject relay loss only by the approved SIGKILL method, then observe status, invitation, public URL, recovery, host health, and sessions.",
        "Status becomes degraded within the health interval; the invitation is withdrawn and copy-invitation is refused; the public URL stops serving the player; bounded recovery returns to ready within the overridden policy; host port 8360 health remains unaffected throughout. Recovery restarts only the companion and re-verifies readiness; it does not restart the player listener, so existing valid player sessions are preserved by design. Record, but do not pass/fail on, whether the pre-loss authenticated cookie/socket still works over the public URL (expected observation: the cookie remains valid; the socket must be re-established by the client). PASS additionally requires a fresh authenticated login over the public URL to work after recovery, a request using a stale pre-recovery Origin/Host to be accepted only if it equals the freshly bound origin (record whether the public origin changed), and no unauthenticated access to be possible. The expected result is recovered ready; observed bounded failed/exhausted recovery is FAIL.",
        "The exact owned child cannot be positively identified (do not signal), or required health/public/session observations cannot be safely collected. Any signal to another process is a safety failure and FAIL.",
    ),
    LiveRow(
        "L06", "credential-rotation-revocation", 300,
        "Sharing is ready; a valid old credential, authenticated session/cookie, and connected L03 socket exist in memory only.",
        "Rotate access; test old cookie/session and old credential over the public URL; then test the new credential after readiness.",
        "Rotation returns a new plaintext credential once; the old cookie/session is rejected; the old credential is rejected; the new credential is accepted after readiness; the L03 socket is disconnected and receives no further events.",
        "Public authentication/session/socket state cannot be observed reliably. Any old credential/session accepted, new credential rejected after readiness, old socket continuing to receive events, or secret disclosure is FAIL.",
    ),
    LiveRow(
        "L07", "stop-sharing", 300,
        "Sharing is ready with an owned route, listener, companion, and active session.",
        "Stop sharing and inspect the public URL, port 8370, companion, sessions, and host health.",
        "The public URL no longer reaches the player service; port 8370 is closed; the companion is reaped; sessions are invalid; the host remains healthy.",
        "Route, port, process, session, or host-health observations cannot be safely established. Any remaining reachability, listener, owned process, or valid session is FAIL.",
    ),
    LiveRow(
        "L08", "host-exit-restart", 300,
        "Owned host is running with sharing active and its host PID/process ownership is positively established.",
        "Send SIGTERM to the owned host with a bounded wait; inspect cleanup; restart the host and inspect sharing state/reconciliation.",
        "After exit, ports 8360 and 8370 are free, no companion is orphaned, and the owner record is cleared. After restart, sharing is OFF, reconciliation is clean, and sharing does not auto-start.",
        "The host PID cannot be positively established or the required port/process/owner-state observations cannot be made. Do not signal an uncertain PID. Any orphan, uncleared owner record, occupied port, or automatic sharing start is FAIL.",
    ),
    LiveRow(
        "L09", "revoke-access", 300,
        "Identity is already initialized and sharing can be started again without identity bootstrap.",
        "Start sharing again, verify no new up invocation, then revoke access and attempt login/service access.",
        "Start uses the existing identity with no new up; after revoke, login fails closed and no unauthenticated service is available.",
        "Identity/bootstrap counters or post-revoke public authentication/service behavior cannot be observed reliably. A new up, successful revoked login, or unauthenticated service is FAIL.",
    ),
    LiveRow(
        "L10", "clean-teardown", 300,
        "The run's gate-owned profile and any gate remote tunnel identity are positively identified; the installed companion path is verified.",
        "Stop sharing; stop the host; delete the gate remote tunnel identity using the installed companion's delete --yes with the gate profile environment only; verify deletion via status; verify ports are free and no run processes remain; remove only the gate state root; remove its neq-n3g parent only if empty; verify the public URL is unreachable afterwards.",
        "The gate remote identity is deleted and confirmed absent; ports are free; no run processes remain; only the unique gate state root is removed and its neq-n3g parent is removed only if empty; the public URL is unreachable; the installed companion remains in place.",
        "Ownership of the profile/identity/process or the status/port/public-reachability evidence cannot be established safely. Any deletion outside the gate profile, remaining process/state/port/public reachability, or removal of the installed companion is FAIL.",
    ),
)

FROZEN_CAPS = MappingProxyType(
    {
        "driver_wall_clock_seconds": 3600,
        "default_row_wall_clock_seconds": 300,
        "l05_row_wall_clock_seconds": 420,
        "companion_serve_launches": 4,
        "companion_up_invocations": 1,
        "relay_tunnel_creations": 2,
        "provider_attempts": 0,
        "automatic_retries": 0,
        "max_harness_iterations": 3,
    }
)
APPROVED_PLATFORMS = ("macos-arm64", "linux-arm64")


def _state_root_id8(run_id: str) -> str:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise GateError("run_id_invalid")
    return hashlib.sha256(run_id.encode("ascii")).hexdigest()[:8]


def _default_state_cache_base(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    selected_platform = sys.platform if platform is None else platform
    selected_environment = os.environ if environ is None else environ
    selected_home = Path.home() if home is None else home
    if not selected_home.is_absolute():
        raise GateError("gate_state_root_invalid")
    if selected_platform == "darwin":
        return selected_home / "Library" / "Caches"
    cache_home = selected_environment.get("XDG_CACHE_HOME")
    if cache_home:
        selected_cache = Path(cache_home)
        if not selected_cache.is_absolute():
            raise GateError("gate_state_root_invalid")
        return selected_cache
    return selected_home / ".cache"


def _state_path_sha256(state_root: Path) -> str:
    return hashlib.sha256(os.fsencode(os.fspath(state_root))).hexdigest()


def live_manifest() -> dict[str, object]:
    """Return a fresh JSON-compatible projection of the frozen live contract."""
    return {
        "manifest_id": MANIFEST_ID,
        "party_size": 1,
        "platforms": list(APPROVED_PLATFORMS),
        "host": {"host": "127.0.0.1", "port": HOST_PORT},
        "player": {"host": "127.0.0.1", "port": PLAYER_PORT},
        "gate_state_root": {
            "macos": "~/Library/Caches/neq-n3g/<id8>",
            "other_approved": "$XDG_CACHE_HOME/neq-n3g/<id8> or ~/.cache/neq-n3g/<id8>",
            "id8": "first-8-hex-of-sha256(run_id)",
            "socket_path_bytes_must_be_less_than": MAX_UNIX_SOCKET_PATH,
            "evidence": ["id8", "sha256(os.fsencode(state_root))"],
            "teardown": "remove-run-root; remove-neq-n3g-parent-only-if-empty",
        },
        "caps": dict(FROZEN_CAPS),
        "provider_budget_ceiling": PROVIDER_BUDGET,
        "verdict_policy": {
            "macos-arm64": {
                "pass": "all-required-rows-pass",
                "blocked": "any-required-row-blocked-or-missing",
                "fail": "any-observed-unmet-pass-criterion-or-provider-attempt",
            },
            "linux-arm64": {
                "verdict": "BLOCKED",
                "reason": "owner-run-required",
            },
            "gate_verdict": "pending-until-all-required-platforms-complete",
        },
        "rows": [
            {
                "id": row.row_id,
                "name": row.name,
                "timeout_seconds": row.timeout_seconds,
                "precondition": row.precondition,
                "action": row.action,
                "expected": row.expected,
                "blocked": row.blocked,
            }
            for row in LIVE_ROWS
        ],
    }


def canonical_manifest_bytes() -> bytes:
    return json.dumps(
        live_manifest(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def calculate_manifest_digest() -> str:
    return hashlib.sha256(canonical_manifest_bytes()).hexdigest()


# Updated only as part of a reviewed frozen-contract revision.
FROZEN_MANIFEST_SHA256 = "a9bb1f3f23df1cd216f627dd1974f7a4702da6d533e7f39a4603ca0d30ca3693"


def verify_frozen_manifest() -> bool:
    return (
        len(LIVE_ROWS) == 10
        and len({row.row_id for row in LIVE_ROWS}) == len(LIVE_ROWS)
        and tuple(row.row_id for row in LIVE_ROWS)
        == tuple("L%02d" % number for number in range(1, 11))
        and all(
            row.timeout_seconds
            == (420 if row.row_id == "L05" else int(FROZEN_CAPS["default_row_wall_clock_seconds"]))
            for row in LIVE_ROWS
        )
        and calculate_manifest_digest() == FROZEN_MANIFEST_SHA256
    )


class GateError(RuntimeError):
    """Bounded internal refusal with no caller-controlled diagnostic text."""

    def __init__(self, reason: str, *, verdict: str = "BLOCKED") -> None:
        super().__init__(reason)
        self.reason = reason
        self.verdict = verdict


@dataclass(frozen=True, slots=True)
class RunArguments:
    run_id: str
    sha: str
    booking_id: str
    preflight_report: str
    party_size: int = 1


@dataclass(frozen=True, slots=True)
class HostApiResponse:
    status: int
    payload: Mapping[str, object] = field(repr=False)

    def __repr__(self) -> str:
        return "HostApiResponse(status=%d)" % self.status


class HostApiError(RuntimeError):
    """Safe, bounded local-host API failure."""

    def __init__(self, reason: str = "host_api_unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


class HostApiClient:
    """Loopback-only client for the facilitator-local sharing API.

    Response payloads stay in memory and are never included in exception text,
    logs, or repr output. POSTs use the host's exact local Host/Origin contract.
    """

    _POST_ACTIONS = frozenset(
        {
            "initialize-identity",
            "issue-access",
            "start",
            "stop",
            "rotate",
            "revoke",
            "copy-invitation",
        }
    )

    def __init__(
        self,
        *,
        connection_factory: Callable[..., http.client.HTTPConnection] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._connection_factory = connection_factory or http.client.HTTPConnection
        self._timeout = timeout_seconds
        self._ownership_validator: Callable[[], bool] | None = None

    def bind_ownership_guard(self, validator: Callable[[], bool]) -> None:
        if not callable(validator) or self._ownership_validator is not None:
            raise HostApiError("host_api_ownership_guard_invalid")
        self._ownership_validator = validator

    def get_status(self) -> HostApiResponse:
        return self._request("GET", "/api/player-sharing/status", None)

    def post(
        self, action: str, payload: Mapping[str, object] | None = None
    ) -> HostApiResponse:
        if action not in self._POST_ACTIONS:
            raise HostApiError("host_api_action_invalid")
        body_value: Mapping[str, object] = {} if payload is None else payload
        if not isinstance(body_value, Mapping):
            raise HostApiError("host_api_payload_invalid")
        path = "/api/player-sharing/" + action
        return self._request("POST", path, body_value)

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None,
    ) -> HostApiResponse:
        if self._ownership_validator is not None:
            try:
                if self._ownership_validator() is not True:
                    raise HostApiError("managed_host_ownership_failed")
            except HostApiError:
                raise
            except Exception:
                raise HostApiError("managed_host_ownership_failed") from None
        body: bytes | None = None
        headers = {
            "Accept": "application/json",
            "Host": "127.0.0.1:%d" % HOST_PORT,
        }
        if method == "POST":
            assert payload is not None
            try:
                body = json.dumps(
                    payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ).encode("ascii")
            except (TypeError, ValueError):
                raise HostApiError("host_api_payload_invalid") from None
            if len(body) > MAX_API_REQUEST_BYTES:
                raise HostApiError("host_api_payload_too_large")
            headers["Content-Type"] = "application/json"
            headers["Origin"] = "http://127.0.0.1:%d" % HOST_PORT
        connection: http.client.HTTPConnection | None = None
        try:
            connection = self._connection_factory(
                "127.0.0.1", HOST_PORT, timeout=self._timeout
            )
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_API_RESPONSE_BYTES + 1)
            status = int(response.status)
        except (OSError, http.client.HTTPException, ValueError, TypeError):
            raise HostApiError() from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (OSError, http.client.HTTPException):
                    pass
        if len(raw) > MAX_API_RESPONSE_BYTES:
            raise HostApiError("host_api_response_too_large")
        try:
            decoded = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            raise HostApiError("host_api_response_invalid") from None
        if not isinstance(decoded, dict) or not _bounded_json(decoded):
            raise HostApiError("host_api_response_invalid")
        return HostApiResponse(status, decoded)


@dataclass(frozen=True, slots=True, repr=False)
class PublicHttpResponse:
    """Bounded response from the HTTPS player origin; body may contain secrets."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes = field(repr=False)

    def values(self, name: str) -> tuple[str, ...]:
        selected = name.casefold()
        return tuple(value for key, value in self.headers if key.casefold() == selected)


class PublicClientError(RuntimeError):
    """Safe, bounded failure from the public player HTTP/Socket.IO client."""

    def __init__(self, reason: str = "public_client_unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True, repr=False)
class PublicOrigin:
    origin: str = field(repr=False)
    authority: str = field(repr=False)
    hostname: str = field(repr=False)
    port: int


@dataclass(frozen=True, slots=True, repr=False)
class PublicLoginChallenge:
    csrf_nonce: str = field(repr=False)
    prelogin_cookie: str = field(repr=False)
    client_build_id: str
    protocol_version: int


@dataclass(frozen=True, slots=True, repr=False)
class PublicPlayerSession:
    cookie: str = field(repr=False)
    csrf_token: str = field(repr=False)
    credential: str = field(repr=False)
    client_build_id: str
    protocol_version: int


class _PlayerShellParser(html.parser.HTMLParser):
    """Extract only the public shell's CSRF and client-version metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.csrf_values: list[str] = []
        self.build_values: list[str] = []
        self.protocol_values: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values: dict[str, list[str | None]] = {}
        for name, value in attrs:
            values.setdefault(name, []).append(value)
        if tag == "input" and values.get("name") == ["csrf_token"]:
            candidate = values.get("value", [None])
            if len(candidate) == 1 and isinstance(candidate[0], str):
                self.csrf_values.append(candidate[0])
        if tag != "meta":
            return
        names = values.get("name", [])
        contents = values.get("content", [])
        if len(names) != 1 or len(contents) != 1 or not isinstance(contents[0], str):
            return
        if names[0] == "neq-client-build":
            self.build_values.append(contents[0])
        elif names[0] == "neq-protocol-version":
            self.protocol_values.append(contents[0])


class PublicUrlClient:
    """Strict HTTPS-only client for the player URL issued by the owned host.

    No redirect is followed, response bodies have a fixed upper bound, and
    both HTTP and Socket.IO dependencies are injectable for offline tests.
    Credentials, cookies, origins, and CSRF values remain private in memory.
    """

    _HTTP_PATHS = frozenset(
        {
            "/",
            "/api/player/login",
            "/api/player/snapshot",
            "/api/player-sharing/status",
            "/api/player-sharing/initialize-identity",
            "/api/player-sharing/issue-access",
            "/api/player-sharing/start",
            "/api/player-sharing/stop",
            "/api/player-sharing/rotate",
            "/api/player-sharing/revoke",
            "/api/player-sharing/copy-invitation",
        }
    )

    def __init__(
        self,
        *,
        requester: Callable[
            [str, int, str, str, Mapping[str, str], bytes | None, float],
            PublicHttpResponse,
        ]
        | None = None,
        connection_factory: Callable[..., http.client.HTTPSConnection] | None = None,
        socket_factory: Callable[[], socketio.Client] | None = None,
        timeout_seconds: float = PUBLIC_CLIENT_TIMEOUT_SECONDS,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
            or timeout_seconds > 30
        ):
            raise ValueError("public_client_timeout_invalid")
        self._connection_factory = connection_factory or http.client.HTTPSConnection
        self._requester = requester or self._https_request
        self._socket_factory = socket_factory or self._new_socket_client
        self._timeout = float(timeout_seconds)
        self._origin: PublicOrigin | None = None
        self._session: PublicPlayerSession | None = None
        self._socket: socketio.Client | None = None

    @property
    def origin(self) -> PublicOrigin | None:
        return self._origin

    @property
    def session(self) -> PublicPlayerSession | None:
        return self._session

    @property
    def socket_connected(self) -> bool | None:
        if self._socket is None:
            return None
        return getattr(self._socket, "connected", False) is True

    def bind_invitation(self, value: object) -> PublicOrigin:
        from web.extensions.player.auth import _parse_public_https_origin

        parsed = _parse_public_https_origin(value)
        if parsed is None:
            raise PublicClientError("public_url_invalid")
        canonical, authority = parsed
        try:
            parts = urllib.parse.urlsplit(canonical)
            hostname = parts.hostname
            port = parts.port or 443
        except ValueError:
            raise PublicClientError("public_url_invalid") from None
        if (
            parts.scheme != "https"
            or parts.path
            or parts.query
            or parts.fragment
            or parts.username is not None
            or parts.password is not None
            or not isinstance(hostname, str)
            or not 1 <= port <= 65535
        ):
            raise PublicClientError("public_url_invalid")
        result = PublicOrigin(canonical, authority, hostname, port)
        self._origin = result
        return result

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> PublicHttpResponse:
        origin = self._origin
        if (
            origin is None
            or method not in {"GET", "POST"}
            or path not in self._HTTP_PATHS
            or body is not None
            and (
                not isinstance(body, bytes)
                or len(body) > MAX_API_REQUEST_BYTES
            )
            or headers is not None
            and any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or any(ord(character) < 32 or ord(character) == 127 for character in key + value)
                for key, value in headers.items()
            )
        ):
            raise PublicClientError("public_request_invalid")
        selected_headers = dict(headers or {})
        if any(key.casefold() == "host" for key in selected_headers):
            raise PublicClientError("public_host_override_refused")
        selected_headers["Host"] = origin.authority
        try:
            response = self._requester(
                origin.hostname,
                origin.port,
                method,
                path,
                selected_headers,
                body,
                self._timeout,
            )
        except PublicClientError:
            raise
        except Exception:
            raise PublicClientError("public_transport_unavailable") from None
        if (
            not isinstance(response, PublicHttpResponse)
            or type(response.status) is not int
            or not 100 <= response.status <= 599
            or not isinstance(response.headers, tuple)
            or not isinstance(response.body, bytes)
            or len(response.body) > MAX_PUBLIC_RESPONSE_BYTES
            or len(response.headers) > 128
            or any(
                not isinstance(name, str)
                or not isinstance(value, str)
                or len(name) > 256
                or len(value) > 8192
                for name, value in response.headers
            )
        ):
            raise PublicClientError("public_response_invalid")
        return response

    def login_challenge(self) -> tuple[PublicHttpResponse, PublicLoginChallenge | None]:
        from web.extensions.player.auth import PRELOGIN_CSRF_COOKIE

        response = self.request("GET", "/")
        if response.status != 200 or len(response.body) > MAX_PLAYER_SHELL_BYTES:
            return response, None
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError:
            raise PublicClientError("public_shell_invalid") from None
        parser = _PlayerShellParser()
        try:
            parser.feed(document)
            parser.close()
        except (ValueError, RecursionError):
            raise PublicClientError("public_shell_invalid") from None
        cookie = _cookie_from_response(response, PRELOGIN_CSRF_COOKIE)
        if (
            len(parser.csrf_values) != 1
            or len(parser.build_values) != 1
            or len(parser.protocol_values) != 1
            or cookie is None
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", parser.csrf_values[0])
            or re.fullmatch(r"[a-f0-9]{32}", parser.build_values[0]) is None
            or parser.protocol_values[0] != str(PROTOCOL_VERSION)
        ):
            raise PublicClientError("public_shell_invalid")
        return response, PublicLoginChallenge(
            parser.csrf_values[0], cookie, parser.build_values[0], PROTOCOL_VERSION
        )

    def login(
        self,
        challenge: PublicLoginChallenge,
        credential: str,
        *,
        origin_override: str | None = None,
    ) -> tuple[PublicHttpResponse, PublicPlayerSession | None]:
        from web.extensions.player.auth import PLAYER_SESSION_COOKIE

        if (
            not isinstance(challenge, PublicLoginChallenge)
            or not isinstance(credential, str)
            or not credential
            or len(credential) > 256
        ):
            raise PublicClientError("public_login_input_invalid")
        body = json.dumps(
            {"password": credential, "csrf_token": challenge.csrf_nonce},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        origin = self._origin
        if origin is None:
            raise PublicClientError("public_url_invalid")
        response = self.request(
            "POST",
            "/api/player/login",
            headers={
                "Content-Type": "application/json",
                "Origin": origin.origin if origin_override is None else origin_override,
                "Cookie": "neq_player_prelogin=" + challenge.prelogin_cookie,
            },
            body=body,
        )
        if response.status != 200:
            return response, None
        try:
            payload = json.loads(
                response.body.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            raise PublicClientError("public_login_response_invalid") from None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"csrf_token", "expires_at"}
            or not isinstance(payload.get("csrf_token"), str)
            or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", payload["csrf_token"]) is None
            or type(payload.get("expires_at")) is not int
            or payload["expires_at"] <= 0
        ):
            raise PublicClientError("public_login_response_invalid")
        cookie = _cookie_from_response(response, PLAYER_SESSION_COOKIE)
        if cookie is None or not _session_cookie_is_secure(response, PLAYER_SESSION_COOKIE):
            raise PublicClientError("public_session_cookie_invalid")
        session = PublicPlayerSession(
            cookie,
            payload["csrf_token"],
            credential,
            challenge.client_build_id,
            challenge.protocol_version,
        )
        self._session = session
        return response, session

    def unauthenticated_snapshot(self) -> PublicHttpResponse:
        origin = self._origin
        if origin is None:
            raise PublicClientError("public_url_invalid")
        return self.request(
            "GET",
            "/api/player/snapshot",
            headers={"Origin": origin.origin},
        )

    def authenticated_snapshot(
        self,
        session: PublicPlayerSession,
        *,
        origin_override: str | None = None,
    ) -> PublicHttpResponse:
        origin = self._origin
        if origin is None or not isinstance(session, PublicPlayerSession):
            raise PublicClientError("public_session_unavailable")
        return self.request(
            "GET",
            "/api/player/snapshot",
            headers={
                "Origin": origin.origin if origin_override is None else origin_override,
                "Cookie": "neq_player_session=" + session.cookie,
                "X-NEQ-Client-Build": session.client_build_id,
                "X-NEQ-Protocol-Version": str(session.protocol_version),
            },
        )

    def connect_player_socket(
        self,
        session: PublicPlayerSession,
        snapshot: Mapping[str, object],
    ) -> bool:
        origin = self._origin
        if origin is None or not _is_player_snapshot(snapshot):
            raise PublicClientError("public_socket_input_invalid")
        client = self._socket_factory()
        received = threading.Event()
        payloads: list[object] = []

        def on_snapshot(payload: object) -> None:
            if len(payloads) == 0:
                payloads.append(payload)
                received.set()

        try:
            client.on("player.snapshot", on_snapshot, namespace=PLAYER_NAMESPACE)
            client.connect(
                origin.origin,
                headers={
                    "Origin": origin.origin,
                    "Cookie": "neq_player_session=" + session.cookie,
                },
                auth={
                    "client_build_id": session.client_build_id,
                    "protocol_version": session.protocol_version,
                },
                transports=["websocket"],
                namespaces=[PLAYER_NAMESPACE],
                socketio_path="socket.io",
                wait=True,
                wait_timeout=self._timeout,
                retry=False,
            )
            client.emit(
                "player.snapshot.request",
                {
                    "schema_version": PROTOCOL_VERSION,
                    "instance_id": snapshot["instance_id"],
                    "session_epoch": snapshot["session_epoch"],
                },
                namespace=PLAYER_NAMESPACE,
            )
            if not received.wait(self._timeout):
                raise PublicClientError("public_socket_snapshot_timeout")
            socket_snapshot = payloads[0]
            if (
                not _is_player_snapshot(socket_snapshot)
                or not isinstance(socket_snapshot, Mapping)
                or socket_snapshot.get("instance_id") != snapshot.get("instance_id")
                or socket_snapshot.get("session_epoch")
                != snapshot.get("session_epoch")
            ):
                raise PublicClientError("public_socket_snapshot_invalid")
            self._socket = client
            return True
        except PublicClientError:
            _disconnect_socket_quietly(client)
            raise
        except Exception:
            _disconnect_socket_quietly(client)
            raise PublicClientError("public_socket_unavailable") from None

    def probe_host_socket_namespace(self) -> bool:
        """Return true only when the public server explicitly refuses `/`."""
        origin = self._origin
        if origin is None:
            raise PublicClientError("public_url_invalid")
        client = self._socket_factory()
        try:
            client.connect(
                origin.origin,
                headers={"Origin": origin.origin},
                transports=["websocket"],
                namespaces=["/"],
                socketio_path="socket.io",
                wait=True,
                wait_timeout=self._timeout,
                retry=False,
            )
        except Exception as exc:
            _disconnect_socket_quietly(client)
            text = str(exc).casefold()
            if (
                "one or more namespaces failed to connect" in text
                or "namespace" in text
                and ("/" in text or "default" in text)
            ):
                return True
            raise PublicClientError("public_socket_observation_unavailable") from None
        connected = getattr(client, "connected", False) is True
        _disconnect_socket_quietly(client)
        if connected:
            return False
        raise PublicClientError("public_socket_observation_unavailable")

    def disconnect(self) -> None:
        client = self._socket
        self._socket = None
        if client is not None:
            _disconnect_socket_quietly(client)

    def _https_request(
        self,
        hostname: str,
        port: int,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> PublicHttpResponse:
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = self._connection_factory(
                hostname,
                port,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
            connection.request(method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            raw = response.read(MAX_PUBLIC_RESPONSE_BYTES + 1)
            response_headers = tuple(
                (str(name), str(value)) for name, value in response.getheaders()
            )
            if len(raw) > MAX_PUBLIC_RESPONSE_BYTES:
                raise PublicClientError("public_response_too_large")
            return PublicHttpResponse(int(response.status), response_headers, raw)
        except PublicClientError:
            raise
        except (OSError, http.client.HTTPException, ValueError, TypeError):
            raise PublicClientError("public_transport_unavailable") from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (OSError, http.client.HTTPException):
                    pass

    @staticmethod
    def _new_socket_client() -> socketio.Client:
        return socketio.Client(
            reconnection=False,
            logger=False,
            engineio_logger=False,
            ssl_verify=True,
            request_timeout=PUBLIC_CLIENT_TIMEOUT_SECONDS,
            handle_sigint=False,
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProcessRecord:
    pid: int
    parent_pid: int
    uid: int
    started_at: datetime
    creation_token: str = field(repr=False)
    command: str = field(repr=False)


class ProcessTableError(RuntimeError):
    """Safe process-table observation failure."""

    def __init__(self, reason: str = "process_table_unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


class ProcessTable(Protocol):
    def snapshot(self) -> tuple[ProcessRecord, ...]: ...


class SystemProcessTable:
    """Read a bounded process table without retaining raw output in evidence."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run

    def snapshot(self) -> tuple[ProcessRecord, ...]:
        try:
            result = self._runner(
                ["/bin/ps", "-axo", "pid=,ppid=,uid=,lstart=,command=", "-ww"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                check=False,
                env={"LC_ALL": "C"},
                close_fds=True,
            )
        except (OSError, subprocess.SubprocessError, TypeError, ValueError):
            raise ProcessTableError() from None
        if (
            not isinstance(result, subprocess.CompletedProcess)
            or result.returncode != 0
            or not isinstance(result.stdout, bytes)
            or len(result.stdout) > MAX_PROCESS_TABLE_BYTES
        ):
            raise ProcessTableError()
        try:
            text = result.stdout.decode("utf-8", "replace")
            lines = text.splitlines()
            if len(lines) > 32768:
                raise ProcessTableError("process_table_too_large")
            rows = tuple(_parse_process_record(line) for line in lines if line.strip())
        except (UnicodeError, ValueError, OverflowError):
            raise ProcessTableError("process_table_invalid") from None
        if len({record.pid for record in rows}) != len(rows):
            raise ProcessTableError("process_table_invalid")
        return rows


class RowExecutor(Protocol):
    def execute(self, context: "RowContext") -> "RowExecutionResult": ...


@dataclass(frozen=True, slots=True)
class RowExecutionResult:
    verdict: str
    reason: str
    observed: Mapping[str, object] = field(default_factory=dict, repr=False)
    recovery_attempts: int = 0


@dataclass(slots=True)
class RowContext:
    run_id: str
    root: Path
    run_root: Path
    capture_dir: Path
    sandbox_root: Path
    host_api: HostApiClient
    host: "ManagedHostHarness"
    secrets: list[str] = field(default_factory=list, repr=False)
    public_client: PublicUrlClient = field(default_factory=PublicUrlClient)
    public_client_factory: Callable[[], PublicUrlClient] = PublicUrlClient
    process_table: ProcessTable = field(default_factory=SystemProcessTable)
    process_identity_probe: Callable[[int], object | None] = probe_process_identity
    signal_process: Callable[[int, int], None] = field(default_factory=lambda: os.kill)
    port_inspector: preflight_gate.PortInspector | None = None
    player_listener_observations: int = 0
    companion_path: Path | None = None
    identity_observer_factory: Callable[[ProfileLayout, Path], IdentityObserver] = (
        lambda layout, path: DefaultIdentityObserver(layout, path)
    )
    companion_runner: Callable[[Sequence[str], Mapping[str, str], float], RunResult] = field(
        default_factory=DefaultCommandRunner, repr=False
    )
    companion_sha256: str | None = None
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def remember_secret(self, value: object) -> None:
        if isinstance(value, str) and len(value) >= 3 and value not in self.secrets:
            self.secrets.append(value)


@dataclass(frozen=True, slots=True)
class _OwnedCompanionTarget:
    pid: int
    uid: int
    started_at: datetime
    creation_token: str = field(repr=False)


class L01SharingOffExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        try:
            status_response = context.host_api.get_status()
            status = _host_status(status_response)
            if status is None:
                return _blocked("host_status_invalid")
            state = status.get("state")
            identity_initialized = status.get("identity_initialized")
            if state not in {"off", "initializing_required"}:
                return _failed("sharing_not_off")
            if type(identity_initialized) is not bool:
                return _blocked("host_status_invalid")

            inspector = context.port_inspector
            if inspector is None:
                return _blocked("player_listener_observation_unavailable")
            port = inspector.inspect(PLAYER_PORT)
            if not _port_observation_valid(port, PLAYER_PORT):
                return _blocked("player_listener_observation_unavailable")
            if port.state == "unknown":
                return _blocked("player_listener_observation_unavailable")
            if port.state == "occupied" or port.pids:
                return _failed("unexpected_player_listener")

            path = _companion_path(context)
            processes = _matching_companion_processes(
                context.process_table.snapshot(), path, None
            )
            if processes is None:
                return _blocked("companion_process_observation_unavailable")
            if processes:
                return _failed("unexpected_companion_process")

            invitation = context.host_api.post("copy-invitation", {})
            if (
                invitation.status == 200
                and invitation.payload.get("ok") is True
                and isinstance(invitation.payload.get("invitation"), str)
            ):
                return _failed("unexpected_public_exposure")
            if (
                invitation.status != 409
                or invitation.payload.get("ok") is not False
                or invitation.payload.get("reason") != "invitation_unavailable"
            ):
                return _blocked("public_exposure_observation_unavailable")
            return RowExecutionResult(
                "PASS",
                "sharing_inactive_no_listener_or_companion",
                {
                    "sharing_state": state,
                    "identity_initialized": identity_initialized,
                    "player_port_free": True,
                    "companion_process_count": 0,
                    "invitation_unavailable": True,
                },
            )
        except (HostApiError, GateError, ProcessTableError, OSError, ValueError):
            return _blocked("l01_observation_unavailable")


class L02IdentityInitExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        try:
            before = _host_status(context.host_api.get_status())
            if before is None:
                return _blocked("host_status_invalid")
            if before.get("state") not in {"off", "initializing_required"}:
                return _failed("sharing_not_off")
            if before.get("identity_initialized") is not False:
                return _failed("identity_precondition_not_met")
            if (
                type(before.get("identity_up_invocations")) is not int
                or before.get("identity_up_invocations") != 0
            ):
                return _failed("identity_up_counter_not_zero")

            first = context.host_api.post("initialize-identity", {"confirm": True})
            first_status = _host_status(first)
            if (
                first.status != 200
                or first.payload.get("ok") is not True
                or first.payload.get("reason") != "identity_initialized"
                or first_status is None
                or first_status.get("identity_initialized") is not True
                or type(first_status.get("identity_up_invocations")) is not int
                or first_status.get("identity_up_invocations") != 1
            ):
                return _failed("identity_initialization_contract_failed")

            companion_path = _companion_path(context)
            layout = _gate_profile_layout(context)
            if layout is None:
                return _blocked("identity_profile_observation_unavailable")
            observer = context.identity_observer_factory(layout, companion_path)
            postchecks = _identity_cleanup_observations(observer, DEFAULT_PROFILE)
            if postchecks is None:
                return _blocked("identity_postcheck_unavailable")
            if any(item["state"] != "absent" for item in postchecks):
                if any(item["state"] == "present" for item in postchecks):
                    return _failed("identity_residual_resource_found")
                return _blocked("identity_postcheck_unavailable")

            second = context.host_api.post("initialize-identity", {"confirm": True})
            second_status = _host_status(second)
            if (
                second.status != 200
                or second.payload.get("ok") is not True
                or second.payload.get("reason") != "identity_initialized"
                or second_status is None
                or second_status.get("identity_initialized") is not True
                or type(second_status.get("identity_up_invocations")) is not int
                or second_status.get("identity_up_invocations") != 1
            ):
                return _failed("identity_initialization_not_idempotent")
            return RowExecutionResult(
                "PASS",
                "identity_initialized_once_and_cleaned_up",
                {
                    "first_reason": "identity_initialized",
                    "first_identity_initialized": True,
                    "identity_up_invocations": 1,
                    "postchecks": postchecks,
                    "second_reason": "identity_initialized",
                    "second_identity_initialized": True,
                    "second_up_invocations": 1,
                },
            )
        except (HostApiError, GateError, ProcessTableError, OSError, ValueError):
            return _blocked("l02_observation_unavailable")


class L03PublicAccessExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        client = context.public_client
        try:
            issued = context.host_api.post("issue-access", {})
            if issued.status != 200 or issued.payload.get("ok") is not True:
                return _failed("credential_issuance_failed")
            credential = issued.payload.get("credential")
            if not isinstance(credential, str) or not credential or len(credential) > 256:
                return _failed("issued_credential_unavailable")
            context.remember_secret(credential)

            started = context.host_api.post("start", {})
            started_status = _host_status(started)
            if (
                started.status != 200
                or started.payload.get("ok") is not True
                or started_status is None
                or started_status.get("state") != "ready"
                or started_status.get("reason") != "ready"
            ):
                return _failed("sharing_start_not_ready")

            invitation = context.host_api.post("copy-invitation", {})
            invitation_url = invitation.payload.get("invitation")
            if (
                invitation.status != 200
                or invitation.payload.get("ok") is not True
                or not isinstance(invitation_url, str)
            ):
                return _failed("invitation_unavailable")
            context.remember_secret(invitation_url)
            client.bind_invitation(invitation_url)

            shell = client.request("GET", "/")
            if shell.status != 200:
                return _failed("public_player_shell_unavailable")

            protected = client.unauthenticated_snapshot()
            if not _data_free_protected_refusal(protected):
                return _failed("unauthenticated_snapshot_boundary_failed")

            host_paths = (
                ("GET", "/api/player-sharing/status"),
                ("POST", "/api/player-sharing/initialize-identity"),
                ("POST", "/api/player-sharing/issue-access"),
                ("POST", "/api/player-sharing/start"),
                ("POST", "/api/player-sharing/stop"),
                ("POST", "/api/player-sharing/rotate"),
                ("POST", "/api/player-sharing/revoke"),
                ("POST", "/api/player-sharing/copy-invitation"),
            )
            host_path_statuses: list[int] = []
            for method, path in host_paths:
                response = client.request(
                    method,
                    path,
                    headers=(
                        {"Content-Type": "application/json"}
                        if method == "POST"
                        else None
                    ),
                    body=b"{}" if method == "POST" else None,
                )
                if not _data_free_protected_refusal(response):
                    return _failed("public_host_route_exposed")
                host_path_statuses.append(response.status)

            challenge_response, challenge = client.login_challenge()
            if challenge_response.status != 200 or challenge is None:
                return _failed("public_login_shell_invalid")
            context.remember_secret(challenge.csrf_nonce)
            context.remember_secret(challenge.prelogin_cookie)
            login_response, session = client.login(challenge, credential)
            if login_response.status != 200 or session is None:
                return _failed("valid_public_login_rejected")
            context.remember_secret(session.cookie)
            context.remember_secret(session.csrf_token)

            snapshot_response = client.authenticated_snapshot(session)
            snapshot = _decode_player_snapshot(snapshot_response)
            if snapshot is None:
                return _failed("authenticated_snapshot_unavailable")
            if not client.connect_player_socket(session, snapshot):
                return _failed("authenticated_player_socket_unavailable")

            if not client.probe_host_socket_namespace():
                return _failed("public_host_socket_namespace_exposed")

            wrong_response, wrong_challenge = client.login_challenge()
            if wrong_response.status != 200 or wrong_challenge is None:
                return _blocked("invalid_credential_probe_unavailable")
            context.remember_secret(wrong_challenge.csrf_nonce)
            context.remember_secret(wrong_challenge.prelogin_cookie)
            wrong_login, _wrong_session = client.login(
                wrong_challenge, credential + "-invalid"
            )
            if wrong_login.status not in {400, 401, 403}:
                return _failed("invalid_credential_accepted")

            forged_response, forged_challenge = client.login_challenge()
            if forged_response.status != 200 or forged_challenge is None:
                return _blocked("forged_origin_probe_unavailable")
            context.remember_secret(forged_challenge.csrf_nonce)
            context.remember_secret(forged_challenge.prelogin_cookie)
            forged_login, _forged_session = client.login(
                forged_challenge,
                credential,
                origin_override="https://forged.invalid",
            )
            if forged_login.status != 403:
                return _failed("forged_origin_accepted")

            return RowExecutionResult(
                "PASS",
                "public_player_boundary_verified",
                {
                    "public_shell_status": shell.status,
                    "unauthenticated_snapshot_status": protected.status,
                    "unauthenticated_snapshot_data_free": True,
                    "host_route_statuses": host_path_statuses,
                    "valid_login_status": login_response.status,
                    "session_cookie_flags_valid": True,
                    "authenticated_snapshot_valid": True,
                    "authenticated_socket_snapshot_valid": True,
                    "host_socket_namespace_refused": True,
                    "invalid_credential_status": wrong_login.status,
                    "forged_origin_status": forged_login.status,
                    "public_origin_scheme": "https",
                },
            )
        except PublicClientError as exc:
            if _is_observed_public_contract_failure(exc.reason):
                return _failed("public_response_contract_invalid")
            return _blocked("l03_public_observation_unavailable")
        except (HostApiError, GateError, ValueError):
            return _blocked("l03_public_observation_unavailable")
        finally:
            client.disconnect()


class L04DuplicateStartExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        inspector = context.port_inspector
        try:
            before = _host_status(context.host_api.get_status())
            if before is None or before.get("state") != "ready":
                return _blocked("sharing_ready_precondition_unavailable")
            generation = before.get("generation")
            launches = before.get("companion_launches")
            if (
                type(generation) is not int
                or generation < 1
                or type(launches) is not int
                or launches < 1
            ):
                return _blocked("sharing_generation_unavailable")
            if inspector is None:
                return _blocked("listener_count_unavailable")
            initial_port = inspector.inspect(PLAYER_PORT)
            if not _host_listener_count_is_one(initial_port, context.host.owner_pid):
                return _blocked("listener_count_unavailable")
            processes = _owned_profile_companions(context)
            if processes is None:
                return _blocked("companion_process_observation_unavailable")
            if len(processes) != 1:
                return _failed("companion_process_count_not_one")

            second = context.host_api.post("start", {})
            after = _host_status(second)
            if second.status != 200 or second.payload.get("ok") is not True or after is None:
                return _failed("duplicate_start_failed")
            if (
                after.get("state") != "ready"
                or after.get("generation") != generation
                or after.get("companion_launches") != launches
            ):
                return _failed("duplicate_start_changed_generation")
            final_port = inspector.inspect(PLAYER_PORT)
            if not _host_listener_count_is_one(final_port, context.host.owner_pid):
                return _failed("duplicate_listener_created")
            final_processes = _owned_profile_companions(context)
            if final_processes is None:
                return _blocked("companion_process_observation_unavailable")
            if len(final_processes) != 1 or not _same_companion_target(
                final_processes[0], processes[0]
            ):
                return _failed("duplicate_companion_created")
            return RowExecutionResult(
                "PASS",
                "duplicate_start_idempotent",
                {
                    "generation_preserved": True,
                    "companion_process_count": 1,
                    "player_listener_count": 1,
                    "companion_launches_unchanged": True,
                },
            )
        except (HostApiError, GateError, ProcessTableError, OSError, ValueError):
            return _blocked("l04_observation_unavailable")


class L05RelayLossRecoveryExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        client = context.public_client
        recovery_client: PublicUrlClient | None = None
        old_origin_client: PublicUrlClient | None = None
        host_health_checks = 0

        def observe_host_health() -> bool | None:
            nonlocal host_health_checks
            inspector = context.port_inspector
            if inspector is None or type(context.host.owner_pid) is not int:
                return None
            observation = inspector.inspect(HOST_PORT)
            if not _port_observation_valid(observation, HOST_PORT):
                return None
            if observation.state == "unknown":
                return None
            host_health_checks += 1
            return bool(
                observation.state == "occupied"
                and observation.pids == (context.host.owner_pid,)
            )

        try:
            before = _host_status(context.host_api.get_status())
            session = client.session
            old_origin = client.origin
            if (
                before is None
                or before.get("state") != "ready"
                or session is None
                or old_origin is None
            ):
                return _blocked("relay_loss_precondition_unavailable")
            launches_before = before.get("companion_launches")
            generation_before = before.get("generation")
            if type(launches_before) is not int:
                return _blocked("companion_counter_unavailable")
            if type(generation_before) is not int or generation_before < 1:
                return _blocked("sharing_generation_unavailable")
            host_healthy = observe_host_health()
            if host_healthy is None:
                return _blocked("host_health_observation_unavailable")
            if not host_healthy:
                return _failed("host_health_lost_before_relay_loss")
            player_listener = _observe_player_listener(context)
            if player_listener is None:
                return _blocked("player_listener_observation_unavailable")
            if not player_listener:
                return _failed("player_listener_lost_before_relay_loss")

            target = _select_owned_companion(context)
            if target is None:
                return _blocked("owned_companion_target_unproven")
            revalidated = _select_owned_companion(context)
            if revalidated is None or not _same_companion_target(target, revalidated):
                return _blocked("owned_companion_target_changed")
            context.signal_process(target.pid, signal.SIGKILL)

            policy = RecoveryPolicy(max_attempts=1, backoff_schedule=(1.0,))
            degraded_deadline = context.monotonic() + policy.health_check_interval
            degraded: Mapping[str, object] | None = None
            degraded_observations = 0
            max_degraded_observations = (
                math.ceil(policy.health_check_interval / PUBLIC_POLL_INTERVAL_SECONDS)
                + 1
            )
            while (
                context.monotonic() <= degraded_deadline
                and degraded_observations < max_degraded_observations
            ):
                degraded_observations += 1
                current = _host_status(context.host_api.get_status())
                if current is None:
                    return _blocked("sharing_status_unavailable_after_relay_loss")
                generation = current.get("generation")
                if type(generation) is not int or generation < 1:
                    return _blocked("sharing_generation_unavailable")
                if generation != generation_before:
                    return _failed("sharing_generation_changed_during_recovery")
                host_healthy = observe_host_health()
                if host_healthy is None:
                    return _blocked("host_health_observation_unavailable")
                if not host_healthy:
                    return _failed("host_health_lost_during_relay_loss")
                player_listener = _observe_player_listener(context)
                if player_listener is None:
                    return _blocked("player_listener_observation_unavailable")
                if not player_listener:
                    return _failed("player_listener_lost_during_relay_loss")
                if current.get("state") == "degraded":
                    degraded = current
                    break
                if current.get("state") in {"failed", "off", "initializing_required"}:
                    return _failed("sharing_failed_before_degraded_observation")
                context.sleep(min(PUBLIC_POLL_INTERVAL_SECONDS, max(0.0, degraded_deadline - context.monotonic())))
            if degraded is None:
                return _failed("degraded_transition_not_observed")

            withdrawn = context.host_api.post("copy-invitation", {})
            if (
                withdrawn.status == 200
                and withdrawn.payload.get("ok") is True
                and isinstance(withdrawn.payload.get("invitation"), str)
            ):
                return _failed("invitation_not_withdrawn")
            if (
                withdrawn.status != 409
                or withdrawn.payload.get("ok") is not False
                or withdrawn.payload.get("reason") != "invitation_unavailable"
            ):
                return _blocked("invitation_withdrawal_observation_unavailable")

            try:
                response = client.request("GET", "/")
                public_unavailable = response.status not in range(200, 400)
            except PublicClientError as exc:
                public_unavailable = exc.reason == "public_transport_unavailable"
            if not public_unavailable:
                return _failed("public_player_remained_reachable")
            host_healthy = observe_host_health()
            if host_healthy is None:
                return _blocked("host_health_observation_unavailable")
            if not host_healthy:
                return _failed("host_health_lost_during_relay_loss")
            player_listener = _observe_player_listener(context)
            if player_listener is None:
                return _blocked("player_listener_observation_unavailable")
            if not player_listener:
                return _failed("player_listener_lost_during_relay_loss")

            recovery_budget = (
                sum(policy.backoff_schedule)
                + MAX_STARTUP_DEADLINE_SECONDS
                + policy.health_check_interval
            )
            recovery_deadline = context.monotonic() + recovery_budget
            recovered: Mapping[str, object] | None = None
            recovery_launches = 0
            recovery_observations = 0
            max_recovery_observations = (
                math.ceil(recovery_budget / PUBLIC_POLL_INTERVAL_SECONDS) + 1
            )
            while (
                context.monotonic() <= recovery_deadline
                and recovery_observations < max_recovery_observations
            ):
                recovery_observations += 1
                current = _host_status(context.host_api.get_status())
                if current is None:
                    return _blocked("sharing_status_unavailable_during_recovery")
                generation = current.get("generation")
                if type(generation) is not int or generation < 1:
                    return _blocked("sharing_generation_unavailable")
                if generation != generation_before:
                    return _failed("sharing_generation_changed_during_recovery")
                host_healthy = observe_host_health()
                if host_healthy is None:
                    return _blocked("host_health_observation_unavailable")
                if not host_healthy:
                    return _failed("host_health_lost_during_recovery")
                player_listener = _observe_player_listener(context)
                if player_listener is None:
                    return _blocked("player_listener_observation_unavailable")
                if not player_listener:
                    return _failed("player_listener_lost_during_recovery")
                current_launches = current.get("companion_launches")
                if type(current_launches) is not int or current_launches < launches_before:
                    return _blocked("companion_counter_invalid")
                recovery_launches = current_launches - launches_before
                if current.get("state") == "ready":
                    recovered = current
                    break
                if current.get("state") == "failed":
                    return _failed("bounded_recovery_failed")
                context.sleep(PUBLIC_POLL_INTERVAL_SECONDS)
            if recovered is None:
                return _failed("bounded_recovery_timeout")
            if recovery_launches != 1:
                return _failed("recovery_launch_count_invalid")

            fresh_invitation = context.host_api.post("copy-invitation", {})
            fresh_url = fresh_invitation.payload.get("invitation")
            fresh_invitation_status = _host_status(fresh_invitation)
            if (
                fresh_invitation.status != 200
                or fresh_invitation.payload.get("ok") is not True
                or not isinstance(fresh_url, str)
                or fresh_invitation_status is None
                or fresh_invitation_status.get("state") != "ready"
                or fresh_invitation_status.get("generation") != generation_before
            ):
                return _failed("recovered_invitation_unavailable")
            context.remember_secret(fresh_url)
            recovery_client = context.public_client_factory()
            new_origin = recovery_client.bind_invitation(fresh_url)
            origin_changed = old_origin.origin != new_origin.origin

            pre_loss_cookie_status: int | None = None
            pre_loss_cookie_valid: bool | None = None
            socket_connected_after_loss = client.socket_connected
            try:
                pre_loss_cookie = recovery_client.authenticated_snapshot(session)
                pre_loss_cookie_status = pre_loss_cookie.status
                pre_loss_cookie_valid = _decode_player_snapshot(pre_loss_cookie) is not None
            except PublicClientError:
                pre_loss_cookie_status = None
                pre_loss_cookie_valid = False

            old_origin_client = context.public_client_factory()
            old_origin_client.bind_invitation(old_origin.origin)
            try:
                stale_origin_response = old_origin_client.authenticated_snapshot(
                    session, origin_override=old_origin.origin
                )
                stale_origin_accepted = _decode_player_snapshot(stale_origin_response) is not None
                stale_origin_status: int | None = stale_origin_response.status
            except PublicClientError:
                stale_origin_accepted = False
                stale_origin_status = None
                stale_origin_response = None
            if (
                origin_changed
                and stale_origin_response is not None
                and not _data_free_protected_refusal(stale_origin_response)
            ):
                return _failed("stale_public_origin_refusal_invalid")
            if origin_changed and stale_origin_accepted:
                return _failed("stale_public_origin_accepted")
            if not origin_changed and not stale_origin_accepted:
                return _failed("current_public_origin_rejected")

            no_auth = recovery_client.unauthenticated_snapshot()
            if not _data_free_protected_refusal(no_auth):
                return _failed("unauthenticated_access_after_recovery")

            fresh_challenge_response, fresh_challenge = recovery_client.login_challenge()
            if fresh_challenge_response.status != 200 or fresh_challenge is None:
                return _failed("fresh_login_challenge_unavailable")
            for secret in (fresh_challenge.csrf_nonce, fresh_challenge.prelogin_cookie):
                context.remember_secret(secret)
            fresh_login, fresh_session = recovery_client.login(
                fresh_challenge, session.credential
            )
            if fresh_login.status != 200 or fresh_session is None:
                return _failed("fresh_login_after_recovery_rejected")
            context.remember_secret(fresh_session.cookie)
            context.remember_secret(fresh_session.csrf_token)
            fresh_snapshot_response = recovery_client.authenticated_snapshot(fresh_session)
            if _decode_player_snapshot(fresh_snapshot_response) is None:
                return _failed("fresh_session_snapshot_after_recovery_failed")

            socket_reestablished = False
            try:
                old_session_snapshot = _decode_player_snapshot(
                    recovery_client.authenticated_snapshot(session)
                )
                if old_session_snapshot is not None:
                    socket_reestablished = recovery_client.connect_player_socket(
                        session, old_session_snapshot
                    )
            except PublicClientError:
                socket_reestablished = False
            recovery_client.disconnect()
            client.disconnect()
            old_origin_client.disconnect()
            host_health = _host_status(context.host_api.get_status())
            if (
                host_health is None
                or host_health.get("state") != "ready"
                or host_health.get("generation") != generation_before
            ):
                return _failed("host_health_not_preserved")
            host_healthy = observe_host_health()
            if host_healthy is None:
                return _blocked("host_health_observation_unavailable")
            if not host_healthy:
                return _failed("host_health_lost_after_recovery")
            player_listener = _observe_player_listener(context)
            if player_listener is None:
                return _blocked("player_listener_observation_unavailable")
            if not player_listener:
                return _failed("player_listener_lost_after_recovery")
            return RowExecutionResult(
                "PASS",
                "relay_loss_recovered_with_fresh_public_auth",
                {
                    "degraded_observed": True,
                    "invitation_withdrawn": True,
                    "public_player_unreachable_during_loss": True,
                    "recovered_ready": True,
                    "host_health_preserved": True,
                    "host_health_observations": host_health_checks,
                    "player_listener_preserved": True,
                    "player_listener_observations": context.player_listener_observations,
                    "pre_loss_cookie_status": pre_loss_cookie_status,
                    "pre_loss_cookie_valid": pre_loss_cookie_valid,
                    "pre_loss_socket_connected_after_loss": socket_connected_after_loss,
                    "pre_loss_socket_reestablished": socket_reestablished,
                    "fresh_login_status": fresh_login.status,
                    "fresh_session_snapshot_valid": True,
                    "unauthenticated_snapshot_status": no_auth.status,
                    "unauthenticated_snapshot_data_free": True,
                    "public_origin_changed": origin_changed,
                    "stale_origin_status": stale_origin_status,
                    "stale_origin_accepted": stale_origin_accepted,
                    "companion_recovery_launches": recovery_launches,
                    "signal_sent": "SIGKILL",
                    "signal_target_pid_verified": True,
                },
                recovery_attempts=recovery_launches,
            )
        except PublicClientError as exc:
            if _is_observed_public_contract_failure(exc.reason):
                return _failed("public_recovery_contract_invalid")
            return _blocked("l05_public_observation_unavailable")
        except (HostApiError, GateError, ProcessTableError, OSError, ValueError):
            return _blocked("l05_lifecycle_observation_unavailable")
        finally:
            client.disconnect()
            if recovery_client is not None:
                recovery_client.disconnect()
            if old_origin_client is not None:
                old_origin_client.disconnect()


class L06CredentialRotationExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        client = context.public_client
        session = client.session
        if session is None or client.origin is None:
            return _blocked("rotation_precondition_unavailable")
        old_credential = session.credential
        if not old_credential:
            return _blocked("old_credential_unavailable")
        try:
            ready_before = _host_status(context.host_api.get_status())
            if ready_before is None:
                return _blocked("sharing_status_unavailable")
            if ready_before.get("state") != "ready":
                return _failed("sharing_not_ready_for_rotation")

            old_snapshot = client.authenticated_snapshot(session)
            old_snapshot_valid = _decode_player_snapshot(old_snapshot) is not None
            if not old_snapshot_valid:
                return _failed("old_session_not_valid_before_rotation")
            if client.socket_connected is not True:
                snapshot = _decode_player_snapshot(old_snapshot)
                if snapshot is None or not client.connect_player_socket(session, snapshot):
                    return _blocked("old_socket_precondition_unavailable")
            if client.socket_connected is not True:
                return _blocked("old_socket_precondition_unavailable")

            rotated = context.host_api.post("rotate", {})
            rotated_status = _host_status(rotated)
            new_credential = rotated.payload.get("credential")
            if (
                rotated.status != 200
                or rotated.payload.get("ok") is not True
                or not isinstance(new_credential, str)
                or not new_credential
                or len(new_credential) > 256
                or new_credential == old_credential
            ):
                return _failed("credential_rotation_contract_failed")
            context.remember_secret(new_credential)
            if rotated_status is None or rotated_status.get("state") != "ready":
                return _failed("sharing_not_ready_after_rotation")

            socket_connected_after = client.socket_connected
            if socket_connected_after is None:
                return _blocked("rotated_socket_state_unavailable")
            if socket_connected_after:
                return _failed("old_socket_not_disconnected")

            invitation = context.host_api.post("copy-invitation", {})
            invitation_url = invitation.payload.get("invitation")
            invitation_status = _host_status(invitation)
            if (
                invitation.status != 200
                or invitation.payload.get("ok") is not True
                or not isinstance(invitation_url, str)
                or invitation_status is None
                or invitation_status.get("state") != "ready"
            ):
                return _failed("rotated_invitation_unavailable")
            context.remember_secret(invitation_url)
            client.bind_invitation(invitation_url)

            old_cookie_response = client.authenticated_snapshot(session)
            if not _data_free_protected_refusal(old_cookie_response):
                return _failed("old_session_accepted_after_rotation")

            old_challenge_response, old_challenge = client.login_challenge()
            if old_challenge_response.status != 200 or old_challenge is None:
                return _blocked("old_credential_probe_unavailable")
            context.remember_secret(old_challenge.csrf_nonce)
            context.remember_secret(old_challenge.prelogin_cookie)
            old_login, _old_session = client.login(old_challenge, old_credential)
            if old_login.status not in {400, 401, 403}:
                if 200 <= old_login.status < 400:
                    return _failed("old_credential_accepted_after_rotation")
                return _blocked("old_credential_probe_unavailable")

            new_challenge_response, new_challenge = client.login_challenge()
            if new_challenge_response.status != 200 or new_challenge is None:
                return _blocked("new_credential_probe_unavailable")
            context.remember_secret(new_challenge.csrf_nonce)
            context.remember_secret(new_challenge.prelogin_cookie)
            new_login, new_session = client.login(new_challenge, new_credential)
            if new_login.status != 200 or new_session is None:
                if new_login.status in {400, 401, 403}:
                    return _failed("new_credential_rejected_after_rotation")
                return _blocked("new_credential_probe_unavailable")
            context.remember_secret(new_session.cookie)
            context.remember_secret(new_session.csrf_token)
            new_snapshot = client.authenticated_snapshot(new_session)
            if _decode_player_snapshot(new_snapshot) is None:
                return _failed("new_session_unavailable_after_rotation")

            return RowExecutionResult(
                "PASS",
                "credential_rotation_revoked_old_access",
                {
                    "rotation_ready": True,
                    "old_session_status": old_cookie_response.status,
                    "old_credential_status": old_login.status,
                    "new_login_status": new_login.status,
                    "new_session_snapshot_valid": True,
                    "old_socket_disconnected": True,
                    "old_socket_no_further_events": True,
                },
            )
        except PublicClientError as exc:
            if _is_observed_public_contract_failure(exc.reason):
                return _failed("public_rotation_contract_invalid")
            return _blocked("l06_public_observation_unavailable")
        except (HostApiError, GateError, ValueError):
            return _blocked("l06_lifecycle_observation_unavailable")


class L07StopSharingExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        client = context.public_client
        session = client.session
        owner_pid = context.host.owner_pid
        if session is None or client.origin is None or type(owner_pid) is not int:
            return _blocked("stop_precondition_unavailable")
        try:
            before = _host_status(context.host_api.get_status())
            if before is None:
                return _blocked("sharing_status_unavailable")
            if before.get("state") != "ready":
                return _failed("sharing_not_ready_for_stop")
            initial_session = client.authenticated_snapshot(session)
            if _decode_player_snapshot(initial_session) is None:
                return _failed("active_session_not_valid_before_stop")

            listener_before = _inspect_port(context, PLAYER_PORT)
            if listener_before is None:
                return _blocked("player_listener_observation_unavailable")
            if not _host_listener_count_is_one(listener_before, owner_pid):
                return _failed("player_listener_precondition_failed")
            companion_before = _profile_companion_records(context)
            if companion_before is None:
                return _blocked("companion_process_observation_unavailable")
            if len(companion_before) != 1:
                return _failed("owned_companion_precondition_failed")
            host_health_before = _observe_host_health(context)
            if host_health_before is None:
                return _blocked("host_health_observation_unavailable")
            if not host_health_before:
                return _failed("host_unhealthy_before_stop")

            stopped = context.host_api.post("stop", {})
            stopped_status = _host_status(stopped)
            if (
                stopped.status != 200
                or stopped.payload.get("ok") is not True
                or stopped_status is None
                or stopped_status.get("state") != "off"
            ):
                return _failed("sharing_stop_failed")

            try:
                public_after = client.request("GET", "/")
            except PublicClientError:
                return _blocked("public_stop_observation_unavailable")
            if not _public_root_unreachable(public_after):
                return _failed("public_player_reachable_after_stop")

            listener_after = _inspect_port(context, PLAYER_PORT)
            if listener_after is None or listener_after.state == "unknown":
                return _blocked("player_listener_observation_unavailable")
            if listener_after.state != "free" or listener_after.pids:
                return _failed("player_listener_remains_after_stop")
            companion_after = _profile_companion_records(context)
            if companion_after is None:
                return _blocked("companion_process_observation_unavailable")
            if companion_after:
                return _failed("owned_companion_remains_after_stop")

            old_session_after = client.authenticated_snapshot(session)
            if not _data_free_protected_refusal(old_session_after):
                return _failed("session_remains_valid_after_stop")
            host_health_after = _observe_host_health(context)
            if host_health_after is None:
                return _blocked("host_health_observation_unavailable")
            if not host_health_after:
                return _failed("host_health_lost_after_stop")
            return RowExecutionResult(
                "PASS",
                "sharing_stopped_and_session_revoked",
                {
                    "public_player_unreachable": True,
                    "public_status": public_after.status,
                    "player_port_free": True,
                    "owned_companion_count": 0,
                    "session_invalidated": True,
                    "host_healthy": True,
                },
            )
        except PublicClientError as exc:
            if _is_observed_public_contract_failure(exc.reason):
                return _failed("public_stop_contract_invalid")
            return _blocked("l07_public_observation_unavailable")
        except (HostApiError, GateError, ProcessTableError, OSError, ValueError):
            return _blocked("l07_lifecycle_observation_unavailable")


class L08HostExitRestartExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        client = context.public_client
        try:
            status = _host_status(context.host_api.get_status())
            if status is None:
                return _blocked("host_status_unavailable")
            if status.get("identity_initialized") is not True:
                return _failed("initialized_identity_not_available")

            # L07 deliberately stopped sharing. Restore it here to exercise an
            # actual active-host exit, without repeating identity bootstrap.
            if status.get("state") != "ready":
                if status.get("state") not in {"off", "initializing_required"}:
                    return _failed("sharing_state_invalid_before_host_exit")
                started = context.host_api.post("start", {})
                status = _host_status(started)
                if (
                    started.status != 200
                    or started.payload.get("ok") is not True
                    or status is None
                    or status.get("state") != "ready"
                ):
                    return _failed("sharing_start_before_host_exit_failed")
            if status.get("state") != "ready":
                return _failed("sharing_not_ready_before_host_exit")

            credential = _current_credential(client)
            if credential is None:
                return _blocked("active_credential_unavailable")
            invitation = _bind_current_invitation(context, client)
            if invitation is None:
                return _blocked("public_invitation_unavailable")
            session = _login_public_session(context, client, credential)
            if session is None:
                return _blocked("active_session_unavailable")

            owner_pid = context.host.owner_pid
            host_record = _observe_owned_host(context)
            if type(owner_pid) is not int or host_record is None:
                return _blocked("host_process_ownership_unavailable")
            listener = _inspect_port(context, PLAYER_PORT)
            if listener is None or listener.state == "unknown":
                return _blocked("active_player_listener_unavailable")
            if not _host_listener_count_is_one(listener, owner_pid):
                return _failed("active_player_listener_invalid")
            companion = _owned_profile_companions(context)
            if companion is None:
                return _blocked("active_companion_ownership_unavailable")
            if len(companion) != 1:
                return _failed("active_companion_count_invalid")
            layout = _gate_profile_layout(context)
            if layout is None:
                return _blocked("gate_profile_observation_unavailable")
            owner_record_state = _owner_record_state(layout)
            if owner_record_state == "unknown":
                return _blocked("owner_record_observation_unavailable")
            if owner_record_state != "present":
                return _blocked("active_owner_record_unavailable")
            active_snapshot = client.authenticated_snapshot(session)
            if _decode_player_snapshot(active_snapshot) is None:
                return _failed("active_session_not_valid_before_host_exit")

            if context.host.stop() is not True:
                return _blocked("owned_host_stop_unconfirmed")
            if not _ports_are_free_for_context(context):
                port_state = _ports_state_for_context(context)
                if port_state is None or "unknown" in port_state:
                    return _blocked("host_exit_port_observation_unavailable")
                return _failed("ports_occupied_after_host_exit")
            if not _owner_record_absent(layout):
                owner_state = _owner_record_state(layout)
                if owner_state == "present":
                    return _failed("owner_record_remains_after_host_exit")
                return _blocked("owner_record_observation_unavailable")
            processes = _run_processes_absent(context, (owner_pid,), layout)
            if processes is None:
                return _blocked("run_process_observation_unavailable")
            if not processes:
                return _failed("run_process_remains_after_host_exit")

            previous_generation = getattr(context.host, "process_generation", None)
            if context.host.start() is not True:
                return _failed("owned_host_restart_failed")
            new_pid = context.host.owner_pid
            restarted_host_record = _observe_owned_host(context)
            if (
                type(new_pid) is not int
                or new_pid <= 0
                or restarted_host_record is None
                or type(previous_generation) is int
                and getattr(context.host, "process_generation", 0) <= previous_generation
            ):
                if restarted_host_record is None:
                    return _blocked("restarted_host_identity_unavailable")
                return _failed("owned_host_restart_identity_invalid")
            if (
                restarted_host_record.creation_token == host_record.creation_token
                and restarted_host_record.started_at <= host_record.started_at
            ):
                return _failed("owned_host_restart_identity_invalid")
            if not _host_ports_owned_or_free(context.port_inspector, new_pid):
                port_state = _ports_state_for_context(context)
                if port_state is None or "unknown" in port_state:
                    return _blocked("restarted_host_port_ownership_unavailable")
                return _failed("restarted_host_port_ownership_invalid")

            restarted = _host_status(context.host_api.get_status())
            if restarted is None:
                return _blocked("restarted_host_status_unavailable")
            if restarted.get("state") != "off":
                return _failed("sharing_auto_started_after_host_restart")
            if restarted.get("identity_initialized") is not True:
                return _failed("gate_identity_not_preserved_after_restart")
            launches = restarted.get("companion_launches")
            if type(launches) is not int:
                return _blocked("restart_reconciliation_observation_unavailable")
            if launches != 0:
                return _failed("sharing_auto_started_after_host_restart")
            restarted_processes = _run_processes_absent(context, (), layout)
            if restarted_processes is None:
                return _blocked("restart_process_observation_unavailable")
            if not restarted_processes:
                return _failed("orphan_process_after_host_restart")
            player_after_restart = _inspect_port(context, PLAYER_PORT)
            if player_after_restart is None or player_after_restart.state == "unknown":
                return _blocked("restart_player_port_observation_unavailable")
            if player_after_restart.state != "free" or player_after_restart.pids:
                return _failed("player_listener_auto_started_after_restart")
            if not _owner_record_absent(layout):
                return _failed("owner_record_reappeared_after_restart")

            return RowExecutionResult(
                "PASS",
                "owned_host_exit_cleanup_and_restart_off",
                {
                    "host_exit_confirmed": True,
                    "ports_free_after_exit": True,
                    "owned_companion_absent_after_exit": True,
                    "owner_record_cleared": True,
                    "host_restarted": True,
                    "sharing_state_after_restart": "off",
                    "identity_preserved": True,
                    "sharing_auto_started": False,
                    "reconciliation_clean": True,
                },
            )
        except PublicClientError as exc:
            if _is_observed_public_contract_failure(exc.reason):
                return _failed("public_host_exit_contract_invalid")
            return _blocked("l08_public_observation_unavailable")
        except (HostApiError, GateError, ProcessTableError, OSError, ValueError):
            return _blocked("l08_lifecycle_observation_unavailable")


class L09RevokeAccessExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        client = context.public_client
        try:
            before = _host_status(context.host_api.get_status())
            if before is None:
                return _blocked("host_status_unavailable")
            if before.get("identity_initialized") is not True:
                return _failed("identity_not_initialized_before_revoke")
            up_before = _identity_up_counter(before)
            if up_before is None:
                return _blocked("identity_up_counter_unavailable")

            started = context.host_api.post("start", {})
            ready = _host_status(started)
            if (
                started.status != 200
                or started.payload.get("ok") is not True
                or ready is None
                or ready.get("state") != "ready"
            ):
                return _failed("sharing_start_before_revoke_failed")
            up_after_start = _identity_up_counter(ready)
            if up_after_start is None:
                return _blocked("identity_up_counter_unavailable")
            if up_after_start != up_before:
                return _failed("identity_reinitialized_on_start")

            credential = _current_credential(client)
            if credential is None:
                return _blocked("current_credential_unavailable")
            if _bind_current_invitation(context, client) is None:
                return _blocked("public_invitation_unavailable")
            session = _login_public_session(context, client, credential)
            if session is None:
                return _blocked("active_session_unavailable")
            if _decode_player_snapshot(client.authenticated_snapshot(session)) is None:
                return _failed("active_session_not_valid_before_revoke")

            revoked = context.host_api.post("revoke", {})
            revoked_status = _host_status(revoked)
            if (
                revoked.status != 200
                or revoked.payload.get("ok") is not True
                or revoked.payload.get("reason") != "access_revoked"
                or revoked_status is None
                or revoked_status.get("state") != "off"
            ):
                return _failed("access_revocation_failed")
            up_after_revoke = _identity_up_counter(revoked_status)
            if up_after_revoke is None:
                return _blocked("identity_up_counter_unavailable")
            if up_after_revoke != up_after_start:
                return _failed("identity_reinitialized_during_revoke")

            old_session = client.authenticated_snapshot(session)
            if not _data_free_protected_refusal(old_session):
                return _failed("session_accepted_after_revoke")
            challenge_response, challenge = client.login_challenge()
            if challenge is None:
                if not _data_free_protected_refusal(challenge_response):
                    if 200 <= challenge_response.status < 400:
                        return _failed("revoked_login_shell_invalid")
                    return _blocked("revoked_login_probe_unavailable")
                old_login_status = challenge_response.status
            else:
                if challenge_response.status != 200:
                    return _blocked("revoked_login_probe_unavailable")
                context.remember_secret(challenge.csrf_nonce)
                context.remember_secret(challenge.prelogin_cookie)
                old_login, _revoked_session = client.login(challenge, credential)
                if old_login.status not in {400, 401, 403}:
                    if 200 <= old_login.status < 400:
                        return _failed("revoked_credential_accepted")
                    return _blocked("revoked_login_probe_unavailable")
                old_login_status = old_login.status
            unauthenticated = client.unauthenticated_snapshot()
            if not _data_free_protected_refusal(unauthenticated):
                return _failed("unauthenticated_service_available_after_revoke")
            unavailable_invitation = context.host_api.post("copy-invitation", {})
            if (
                unavailable_invitation.status != 409
                or unavailable_invitation.payload.get("ok") is not False
                or unavailable_invitation.payload.get("reason")
                != "invitation_unavailable"
            ):
                return _failed("invitation_available_after_revoke")
            return RowExecutionResult(
                "PASS",
                "access_revoked_without_identity_rebootstrap",
                {
                    "identity_up_invocations_before": up_before,
                    "identity_up_invocations_after_start": up_after_start,
                    "identity_up_invocations_after_revoke": up_after_revoke,
                    "revoked_session_status": old_session.status,
                    "revoked_login_status": old_login_status,
                    "unauthenticated_status": unauthenticated.status,
                    "unauthenticated_data_free": True,
                    "invitation_unavailable": True,
                },
            )
        except PublicClientError as exc:
            if _is_observed_public_contract_failure(exc.reason):
                return _failed("public_revoke_contract_invalid")
            return _blocked("l09_public_observation_unavailable")
        except (HostApiError, GateError, ValueError):
            return _blocked("l09_lifecycle_observation_unavailable")


class L10CleanTeardownExecutor:
    def execute(self, context: RowContext) -> RowExecutionResult:
        client = context.public_client
        if client.origin is None:
            return _blocked("public_origin_unavailable_for_teardown")
        try:
            companion = _companion_path(context)
            if not _installed_companion_matches(context, companion):
                return _blocked("installed_companion_identity_unavailable")
            layout = _gate_profile_layout(context)
            state_identity = _owned_state_root_identity(context)
            if layout is None or state_identity is None:
                return _blocked("gate_profile_ownership_unavailable")
            if layout.profile != DEFAULT_PROFILE:
                return _blocked("gate_profile_ownership_unavailable")
            if not _identity_owner_record_matches(context, layout):
                return _blocked("gate_profile_owner_unverified")

            host_pid = context.host.owner_pid
            if type(host_pid) is not int or _observe_owned_host(context) is None:
                return _blocked("host_process_ownership_unavailable")
            current = _host_status(context.host_api.get_status())
            if current is None:
                return _blocked("host_status_unavailable")
            if current.get("identity_initialized") is not True:
                return _failed("gate_identity_not_initialized")
            up_count = _identity_up_counter(current)
            if up_count is None:
                return _blocked("identity_up_counter_unavailable")

            stopped = context.host_api.post("stop", {})
            stopped_status = _host_status(stopped)
            if (
                stopped.status != 200
                or stopped.payload.get("ok") is not True
                or stopped_status is None
                or stopped_status.get("state") != "off"
            ):
                return _failed("sharing_stop_before_teardown_failed")

            if context.host.stop() is not True:
                return _blocked("owned_host_stop_unconfirmed")
            if not _ports_are_free_for_context(context):
                port_state = _ports_state_for_context(context)
                if port_state is None or "unknown" in port_state:
                    return _blocked("teardown_port_observation_unavailable")
                return _failed("ports_occupied_after_host_stop")
            owner_state = _owner_record_state(layout)
            if owner_state == "unknown":
                return _blocked("owner_record_observation_unavailable")
            if owner_state != "absent":
                return _failed("owner_record_remains_after_host_stop")
            owned_host_pids = getattr(context.host, "owned_pids", (host_pid,))
            if not isinstance(owned_host_pids, (list, tuple)):
                return _blocked("host_process_ownership_unavailable")
            processes_absent = _run_processes_absent(
                context, owned_host_pids, layout
            )
            if processes_absent is None:
                return _blocked("run_process_observation_unavailable")
            if not processes_absent:
                return _failed("run_process_remains_after_host_stop")

            environment = companion_environment(layout)
            if set(environment) != {
                "HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_STATE_HOME",
                "XDG_RUNTIME_DIR",
            }:
                return _blocked("gate_profile_environment_invalid")
            before_delete = _run_companion_status(context, companion, layout, environment)
            if before_delete is None:
                return _blocked("identity_status_before_delete_unavailable")
            before_evidence = _identity_status_evidence(before_delete.bounded_output)
            if before_evidence is None:
                return _blocked("identity_status_before_delete_invalid")
            if not before_evidence[0]:
                return _failed("gate_remote_identity_not_present")
            if before_evidence[1]:
                return _failed("gate_identity_service_still_running")
            if not before_evidence[2]:
                return _blocked("identity_service_state_unproven_before_delete")

            delete = _run_companion_command(
                context,
                (
                    str(companion),
                    "--profile",
                    layout.profile,
                    "delete",
                    "--yes",
                ),
                environment,
            )
            if delete is None or delete.timed_out or delete.output_truncated:
                return _blocked("identity_delete_observation_unavailable")
            if delete.returncode is None:
                return _blocked("identity_delete_observation_unavailable")
            if delete.returncode != 0:
                return _failed("gate_remote_identity_delete_failed")

            after_delete = _run_companion_status(
                context, companion, layout, environment
            )
            if after_delete is None:
                return _blocked("identity_status_after_delete_unavailable")
            absent = _identity_absent_status(after_delete.bounded_output)
            if absent is None:
                return _blocked("identity_absence_not_proven")
            if not absent:
                return _failed("gate_remote_identity_remains")

            if not _ports_are_free_for_context(context):
                port_state = _ports_state_for_context(context)
                if port_state is None:
                    return _blocked("teardown_port_observation_unavailable")
                return _failed("ports_occupied_after_identity_delete")
            processes_absent = _run_processes_absent(context, (), layout)
            if processes_absent is None:
                return _blocked("run_process_observation_unavailable")
            if not processes_absent:
                return _failed("run_process_remains_after_identity_delete")
            if not _installed_companion_matches(context, companion):
                return _failed("installed_companion_missing_after_delete")

            state_root = Path(context.host.state_root)
            if not _private_state_tree_matches(state_root, state_identity):
                return _blocked("gate_state_root_ownership_changed")
            try:
                shutil.rmtree(state_root)
            except OSError:
                return _failed("gate_state_root_removal_failed")
            if state_root.exists() or state_root.is_symlink():
                return _failed("gate_state_root_remains")
            parent_identity = getattr(context.host, "_state_parent_identity", None)
            parent_removed = _remove_private_state_parent_if_empty(
                state_root.parent, parent_identity
            )
            if parent_removed is None:
                return _blocked("gate_state_parent_removal_unavailable")

            try:
                public_after = client.request("GET", "/")
            except PublicClientError:
                return _blocked("public_teardown_observation_unavailable")
            if not _public_root_unreachable(public_after):
                return _failed("public_player_reachable_after_teardown")
            client.disconnect()
            return RowExecutionResult(
                "PASS",
                "gate_profile_identity_and_processes_removed",
                {
                    "sharing_stopped": True,
                    "host_stopped": True,
                    "identity_deleted_and_absent": True,
                    "identity_up_invocations_before_teardown": up_count,
                    "ports_free": True,
                    "run_processes_absent": True,
                    "gate_state_root_removed": True,
                    "gate_state_root_id8": _state_root_id8(context.run_id),
                    "gate_state_path_sha256": _state_path_sha256(state_root),
                    "gate_state_parent_removed_if_empty": parent_removed,
                    "public_url_unreachable": True,
                    "installed_companion_preserved": True,
                    "public_status": public_after.status,
                },
            )
        except PublicClientError as exc:
            if _is_observed_public_contract_failure(exc.reason):
                return _failed("public_teardown_contract_invalid")
            return _blocked("l10_public_observation_unavailable")
        except (HostApiError, GateError, ProcessTableError, OSError, ValueError):
            return _blocked("l10_lifecycle_observation_unavailable")


def _inspect_port(context: RowContext, port: int) -> preflight_gate.PortObservation | None:
    if context.port_inspector is None:
        return None
    try:
        observation = context.port_inspector.inspect(port)
    except Exception:
        return None
    return observation if _port_observation_valid(observation, port) else None


def _observe_host_health(context: RowContext) -> bool | None:
    owner_pid = context.host.owner_pid
    observation = _inspect_port(context, HOST_PORT)
    if type(owner_pid) is not int or observation is None or observation.state == "unknown":
        return None
    return bool(observation.state == "occupied" and observation.pids == (owner_pid,))


def _ports_state_for_context(context: RowContext) -> tuple[str, str] | None:
    host = _inspect_port(context, HOST_PORT)
    player = _inspect_port(context, PLAYER_PORT)
    if host is None or player is None:
        return None
    return host.state, player.state


def _ports_are_free_for_context(context: RowContext) -> bool:
    state = _ports_state_for_context(context)
    if state is None:
        return False
    return state == ("free", "free")


def _profile_companion_records(context: RowContext) -> tuple[ProcessRecord, ...] | None:
    try:
        path = _companion_path(context)
        matches = _matching_companion_processes(
            context.process_table.snapshot(), path, DEFAULT_PROFILE
        )
    except (GateError, ProcessTableError, OSError, ValueError):
        return None
    return matches


def _run_processes_absent(
    context: RowContext,
    owned_host_pids: Sequence[int],
    layout: ProfileLayout,
) -> bool | None:
    try:
        records = context.process_table.snapshot()
        path = _companion_path(context)
        matches = _matching_companion_processes(records, path, layout.profile)
    except (GateError, ProcessTableError, OSError, ValueError):
        return None
    if matches is None:
        return None
    if any(record.pid in set(owned_host_pids) for record in records):
        return False
    return not matches


def _observe_owned_host(context: RowContext) -> ProcessRecord | None:
    host = context.host
    pid = getattr(host, "owner_pid", None)
    process = getattr(host, "process", None)
    if type(pid) is not int or pid <= 0 or process is None:
        return None
    if getattr(process, "pid", None) != pid:
        return None
    try:
        if process.poll() is not None:
            return None
        records = context.process_table.snapshot()
        record = next((item for item in records if item.pid == pid), None)
        identity = context.process_identity_probe(pid)
        expected_python = (context.root / ".venv" / "bin" / "python").resolve(
            strict=True
        )
        executable = Path(
            str(getattr(identity, "executable_path", ""))
        ).resolve(strict=True)
        argv = getattr(identity, "argv", ())
        command_line = getattr(identity, "command_line", "")
        arguments = (
            tuple(str(item) for item in argv)
            if isinstance(argv, (tuple, list))
            else ()
        )
        command = " ".join(arguments) if arguments else str(command_line)
        owned_pids = getattr(host, "owned_pids", ())
        if (
            record is None
            or record.uid != os.getuid()
            or not _identity_matches_record(identity, record)
            or executable != expected_python
            or "run_web.main()" not in command
            or pid not in owned_pids
        ):
            return None
        process_args = _process_arguments(record, expected_python)
        if process_args is None or "run_web.main()" not in " ".join(process_args):
            return None
        return record
    except (OSError, RuntimeError, TypeError, ValueError, ProcessTableError):
        return None


def _owned_state_root_identity(context: RowContext) -> tuple[int, int] | None:
    try:
        state_root = Path(context.host.state_root)
        repository_root = context.root.resolve(strict=True)
        expected_id = _state_root_id8(context.run_id)
        identity = getattr(context.host, "_state_root_identity", None)
        parent_identity = getattr(context.host, "_state_parent_identity", None)
        try:
            state_root.relative_to(repository_root)
            inside_repository = True
        except ValueError:
            inside_repository = False
        try:
            repository_root.relative_to(state_root)
            contains_repository = True
        except ValueError:
            contains_repository = False
        if (
            inside_repository
            or contains_repository
            or state_root.name != expected_id
            or state_root.parent.name != "neq-n3g"
            or not state_root.is_absolute()
            or not isinstance(identity, tuple)
            or len(identity) != 2
            or any(type(part) is not int or part < 0 for part in identity)
            or not _private_state_tree_matches(state_root, identity)
            or not _private_state_parent_matches(
                state_root.parent, parent_identity
            )
        ):
            return None
        return identity
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None


def _identity_owner_record_matches(
    context: RowContext, layout: ProfileLayout
) -> bool:
    identity = _owned_state_root_identity(context)
    if identity is None:
        return False
    try:
        expected_state = Path(context.host.state_root).resolve(strict=True)
        return bool(
            layout.state_root == expected_state.resolve(strict=True)
            and layout.profile_root
            == layout.state_root / "neq" / "opentunnel" / DEFAULT_PROFILE
            and layout.owner_file == layout.profile_root / "profile_owner.json"
            and layout.owner_file.is_file()
            and not layout.owner_file.is_symlink()
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _owner_record_state(layout: ProfileLayout) -> str:
    path = layout.state_home / "owned_process.json"
    try:
        path.lstat()
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    return "present"


def _owner_record_absent(layout: ProfileLayout) -> bool:
    return _owner_record_state(layout) == "absent"


def _identity_up_counter(status: Mapping[str, object]) -> int | None:
    value = status.get("identity_up_invocations")
    return value if type(value) is int and value >= 0 else None


def _current_credential(client: PublicUrlClient) -> str | None:
    session = client.session
    if session is None or not session.credential or len(session.credential) > 256:
        return None
    return session.credential


def _bind_current_invitation(
    context: RowContext, client: PublicUrlClient
) -> str | None:
    try:
        response = context.host_api.post("copy-invitation", {})
        url = response.payload.get("invitation")
        status = _host_status(response)
        if (
            response.status != 200
            or response.payload.get("ok") is not True
            or not isinstance(url, str)
            or status is None
            or status.get("state") != "ready"
        ):
            return None
        context.remember_secret(url)
        client.bind_invitation(url)
        return url
    except (HostApiError, PublicClientError, ValueError):
        return None


def _login_public_session(
    context: RowContext, client: PublicUrlClient, credential: str
) -> PublicPlayerSession | None:
    try:
        challenge_response, challenge = client.login_challenge()
        if challenge_response.status != 200 or challenge is None:
            return None
        context.remember_secret(challenge.csrf_nonce)
        context.remember_secret(challenge.prelogin_cookie)
        login, session = client.login(challenge, credential)
        if login.status != 200 or session is None:
            return None
        context.remember_secret(session.cookie)
        context.remember_secret(session.csrf_token)
        if _decode_player_snapshot(client.authenticated_snapshot(session)) is None:
            return None
        return session
    except PublicClientError:
        return None


def _installed_companion_matches(context: RowContext, path: Path) -> bool:
    digest = context.companion_sha256
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    try:
        root = (context.root / "runtime/opentunnel/v0.6.2").resolve(strict=True)
        path.relative_to(root)
        metadata = path.lstat()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return bool(
        not stat.S_ISLNK(metadata.st_mode)
        and stat.S_ISREG(metadata.st_mode)
        and path.name == "opentunnel"
        and verify_companion_digest(path, digest)
    )


def _run_companion_command(
    context: RowContext,
    argv: Sequence[str],
    environment: Mapping[str, str],
) -> RunResult | None:
    try:
        result = context.companion_runner(tuple(argv), dict(environment), 30.0)
    except Exception:
        return None
    if (
        not isinstance(result, RunResult)
        or (result.returncode is not None and type(result.returncode) is not int)
        or not isinstance(result.bounded_output, str)
        or len(result.bounded_output) > 64 * 1024
        or type(result.output_truncated) is not bool
        or type(result.timed_out) is not bool
    ):
        return None
    return result


def _run_companion_status(
    context: RowContext,
    companion: Path,
    layout: ProfileLayout,
    environment: Mapping[str, str],
) -> RunResult | None:
    result = _run_companion_command(
        context,
        (str(companion), "--profile", layout.profile, "status"),
        environment,
    )
    if (
        result is None
        or result.returncode != 0
        or result.output_truncated
        or result.timed_out
    ):
        return None
    return result


def _identity_status_evidence(output: str) -> tuple[bool, bool, bool] | None:
    if not isinstance(output, str) or len(output) > 64 * 1024:
        return None
    evidence = parse_identity_status(output)
    service = re.search(r"(?im)^\s*Service:\s*(.+?)\s*$", output)
    if service is None:
        return None
    service_stopped = service.group(1).strip().casefold().startswith("stopped")
    return evidence.identity_confirmed, evidence.daemon_running, service_stopped


def _identity_absent_status(output: str) -> bool | None:
    evidence = _identity_status_evidence(output)
    if evidence is None:
        return None
    no_tunnel = "no tunnel exists for this profile" in output.casefold()
    identifier_present = bool(
        re.search(r"(?im)^\s*Hostname:\s*\S+", output)
        or re.search(r"(?im)^\s*Tunnel ID:\s*\S+", output)
        or re.search(r"(?i)\btunnel[_ -]?id\s*[:=]\s*\S+", output)
    )
    if evidence[0] or evidence[1] or identifier_present:
        return False
    if no_tunnel and evidence[2]:
        return True
    return None


def _public_root_unreachable(response: PublicHttpResponse) -> bool:
    if (
        not isinstance(response, PublicHttpResponse)
        or response.status != 404
        or len(response.body) > MAX_PUBLIC_PROBE_BODY_BYTES
    ):
        return False
    try:
        payload = json.loads(
            response.body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return False
    return bool(
        isinstance(payload, dict)
        and set(payload) == {"error"}
        and payload.get("error") == "not_found"
    )


ROW_EXECUTORS: Mapping[str, RowExecutor] = MappingProxyType(
    {
        "L01": L01SharingOffExecutor(),
        "L02": L02IdentityInitExecutor(),
        "L03": L03PublicAccessExecutor(),
        "L04": L04DuplicateStartExecutor(),
        "L05": L05RelayLossRecoveryExecutor(),
        "L06": L06CredentialRotationExecutor(),
        "L07": L07StopSharingExecutor(),
        "L08": L08HostExitRestartExecutor(),
        "L09": L09RevokeAccessExecutor(),
        "L10": L10CleanTeardownExecutor(),
    }
)


def _blocked(reason: str) -> RowExecutionResult:
    return RowExecutionResult("BLOCKED", reason)


def _failed(reason: str) -> RowExecutionResult:
    return RowExecutionResult("FAIL", reason)


def _host_status(response: HostApiResponse) -> Mapping[str, object] | None:
    if (
        not isinstance(response, HostApiResponse)
        or response.status != 200
        or response.payload.get("ok") is not True
    ):
        return None
    status = response.payload.get("status")
    return status if isinstance(status, Mapping) else None


def _port_observation_valid(value: object, expected_port: int) -> bool:
    return bool(
        isinstance(value, preflight_gate.PortObservation)
        and value.port == expected_port
        and value.state in {"free", "occupied", "unknown"}
        and isinstance(value.pids, tuple)
        and all(type(pid) is int and pid > 0 for pid in value.pids)
    )


def _host_listener_count_is_one(value: object, host_pid: object) -> bool:
    return bool(
        _port_observation_valid(value, PLAYER_PORT)
        and type(host_pid) is int
        and value.state == "occupied"
        and value.pids == (host_pid,)
    )


def _observe_player_listener(context: RowContext) -> bool | None:
    inspector = context.port_inspector
    host_pid = context.host.owner_pid
    if inspector is None or type(host_pid) is not int:
        return None
    try:
        observation = inspector.inspect(PLAYER_PORT)
    except Exception:
        return None
    if not _port_observation_valid(observation, PLAYER_PORT):
        return None
    context.player_listener_observations += 1
    if observation.state == "unknown":
        return None
    return bool(
        observation.state == "occupied" and observation.pids == (host_pid,)
    )


def _companion_path(context: RowContext) -> Path:
    value = context.companion_path
    if not isinstance(value, Path):
        raise GateError("companion_path_unavailable")
    try:
        resolved = value.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise GateError("companion_path_unavailable") from None
    if not resolved.is_file():
        raise GateError("companion_path_unavailable")
    return resolved


def _parse_process_record(line: str) -> ProcessRecord:
    parts = line.strip().split(None, 8)
    if len(parts) != 9 or not parts[8] or len(parts[8]) > 8192:
        raise ValueError("process_table_line_invalid")
    pid, parent_pid, uid = (int(parts[index]) for index in range(3))
    if pid <= 0 or parent_pid < 0 or uid < 0:
        raise ValueError("process_table_identity_invalid")
    date_text = " ".join(parts[3:8])
    started_at = datetime.strptime(date_text, "%a %b %d %H:%M:%S %Y")
    return ProcessRecord(pid, parent_pid, uid, started_at, date_text, parts[8])


def _process_arguments(record: ProcessRecord, expected_path: Path) -> tuple[str, ...] | None:
    try:
        arguments = tuple(shlex.split(record.command, posix=True))
    except ValueError:
        return None if str(expected_path) in record.command else ()
    if not arguments:
        return ()
    try:
        executable = Path(arguments[0]).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None if str(expected_path) in record.command else ()
    return arguments if executable == expected_path else ()


def _has_profile_argument(arguments: Sequence[str], profile: str) -> bool:
    return any(
        arguments[index] == "--profile"
        and index + 1 < len(arguments)
        and arguments[index + 1] == profile
        for index in range(len(arguments))
    )


def _matching_companion_processes(
    records: Sequence[ProcessRecord], companion_path: Path, profile: str | None
) -> tuple[ProcessRecord, ...] | None:
    matches: list[ProcessRecord] = []
    for record in records:
        arguments = _process_arguments(record, companion_path)
        if arguments is None:
            return None
        if (
            arguments
            and (profile is None or _has_profile_argument(arguments, profile))
        ):
            matches.append(record)
    return tuple(matches)


def _is_serve_process(
    record: ProcessRecord, companion_path: Path, profile: str
) -> bool | None:
    arguments = _process_arguments(record, companion_path)
    if arguments is None:
        return None
    return bool(
        arguments
        and "serve" in arguments[1:]
        and _has_profile_argument(arguments, profile)
    )


def _gate_profile_layout(context: RowContext) -> ProfileLayout | None:
    try:
        install_path = Path(os.path.abspath(os.fspath(context.sandbox_root)))
        install_marker = "neq-" + hashlib.sha256(os.fsencode(install_path)).hexdigest()[:32]
        profile = prepare_profile(
            Path(context.host.state_root),
            install_marker=install_marker,
            profile=DEFAULT_PROFILE,
            create=False,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return profile.layout if profile.state == "ready" else None


def _identity_cleanup_observations(
    observer: IdentityObserver, profile: str
) -> list[dict[str, object]] | None:
    try:
        observed = (
            ("service_manager", observer.service_manager_entries(profile)),
            ("profile_processes", observer.profile_processes(profile)),
            ("helper_processes", observer.helper_processes()),
        )
    except Exception:
        return None
    result: list[dict[str, object]] = []
    for kind, item in observed:
        if (
            not isinstance(item, Observation)
            or item.state not in {"present", "absent", "unknown"}
            or type(item.count) is not int
            or item.count < 0
        ):
            return None
        result.append({"kind": kind, "state": item.state, "count": item.count})
    return result


def _cookie_from_response(response: PublicHttpResponse, name: str) -> str | None:
    values = response.values("Set-Cookie")
    if len(values) > 16:
        return None
    found: list[str] = []
    for value in values:
        parsed = http.cookies.SimpleCookie()
        try:
            parsed.load(value)
        except (http.cookies.CookieError, TypeError, ValueError):
            return None
        morsel = parsed.get(name)
        if morsel is not None:
            found.append(morsel.value)
    if len(found) != 1 or not found[0] or len(found[0]) > 512:
        return None
    return found[0]


def _session_cookie_is_secure(response: PublicHttpResponse, name: str) -> bool:
    matches: list[http.cookies.Morsel[str]] = []
    for value in response.values("Set-Cookie"):
        parsed = http.cookies.SimpleCookie()
        try:
            parsed.load(value)
        except (http.cookies.CookieError, TypeError, ValueError):
            return False
        if name in parsed:
            matches.append(parsed[name])
    if len(matches) != 1:
        return False
    cookie = matches[0]
    return bool(
        cookie["secure"]
        and cookie["httponly"]
        and cookie["samesite"].casefold() == "strict"
        and cookie["path"] == "/"
        and not cookie["domain"]
    )


def _data_free_protected_refusal(response: PublicHttpResponse) -> bool:
    if (
        not isinstance(response, PublicHttpResponse)
        or response.status not in {401, 403, 404}
        or len(response.body) > MAX_PUBLIC_PROBE_BODY_BYTES
    ):
        return False
    try:
        value = json.loads(
            response.body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return False
    return bool(
        isinstance(value, dict)
        and set(value) == {"error"}
        and value.get("error")
        in {"authentication_required", "not_found", "request_rejected"}
    )


def _is_observed_public_contract_failure(reason: str) -> bool:
    return reason in {
        "public_url_invalid",
        "public_shell_invalid",
        "public_response_invalid",
        "public_response_too_large",
        "public_login_response_invalid",
        "public_session_cookie_invalid",
        "public_socket_unavailable",
        "public_socket_input_invalid",
        "public_socket_snapshot_invalid",
        "public_socket_snapshot_timeout",
    }


def _decode_player_snapshot(
    response: PublicHttpResponse,
) -> Mapping[str, object] | None:
    if not isinstance(response, PublicHttpResponse) or response.status != 200:
        return None
    try:
        payload = json.loads(
            response.body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
        from web.extensions.player.contracts import validate_snapshot_envelope

        validated = validate_snapshot_envelope(payload)
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError):
        return None
    return validated if isinstance(validated, Mapping) else None


def _is_player_snapshot(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    try:
        from web.extensions.player.contracts import validate_snapshot_envelope

        validate_snapshot_envelope(value)
    except (ValueError, TypeError, RecursionError):
        return False
    return True


def _disconnect_socket_quietly(client: object) -> None:
    if getattr(client, "connected", False) is not True:
        return
    try:
        client.disconnect()
    except Exception:
        return


def _normalized_creation_token(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    return " ".join(value.split())


def _identity_matches_record(identity: object, record: ProcessRecord) -> bool:
    return bool(
        identity is not None
        and getattr(identity, "pid", None) == record.pid
        and _normalized_creation_token(getattr(identity, "creation_token", None))
        == _normalized_creation_token(record.creation_token)
    )


def _process_is_descendant(
    by_pid: Mapping[int, ProcessRecord], pid: int, ancestor_pid: int
) -> bool | None:
    current = pid
    visited: set[int] = set()
    for _depth in range(MAX_PROCESS_ANCESTRY_DEPTH):
        if current == ancestor_pid:
            return True
        if current in visited:
            return None
        visited.add(current)
        record = by_pid.get(current)
        if record is None or record.parent_pid <= 0:
            return False
        if record.parent_pid not in by_pid:
            return None
        current = record.parent_pid
    return None


def _validated_owned_companion(
    context: RowContext,
    records: Sequence[ProcessRecord],
    companion_path: Path,
    candidate: ProcessRecord,
) -> _OwnedCompanionTarget | None:
    host_pid = context.host.owner_pid
    if type(host_pid) is not int or host_pid <= 0 or candidate.uid != os.getuid():
        return None
    by_pid = {record.pid: record for record in records}
    host_record = by_pid.get(host_pid)
    if host_record is None or host_record.uid != os.getuid():
        return None
    try:
        host_identity = context.process_identity_probe(host_pid)
        candidate_identity = context.process_identity_probe(candidate.pid)
        expected_python = (context.root / ".venv" / "bin" / "python").resolve(strict=True)
        host_executable = Path(
            str(getattr(host_identity, "executable_path", ""))
        ).resolve(strict=True)
        executable = Path(
            str(getattr(candidate_identity, "executable_path", ""))
        ).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    host_command = str(getattr(host_identity, "command_line", ""))
    host_argv = getattr(host_identity, "argv", ())
    if isinstance(host_argv, tuple):
        host_command = " ".join(str(item) for item in host_argv)
    if (
        not _identity_matches_record(host_identity, host_record)
        or host_executable != expected_python
        or "run_web.main()" not in host_command
        or not _identity_matches_record(candidate_identity, candidate)
        or executable != companion_path
        or candidate.started_at <= host_record.started_at
    ):
        return None
    if _process_is_descendant(by_pid, candidate.pid, host_pid) is not True:
        return None
    return _OwnedCompanionTarget(
        candidate.pid,
        candidate.uid,
        candidate.started_at,
        candidate.creation_token,
    )


def _owned_profile_companions(
    context: RowContext,
) -> tuple[_OwnedCompanionTarget, ...] | None:
    companion_path = _companion_path(context)
    records = context.process_table.snapshot()
    matches = _matching_companion_processes(records, companion_path, DEFAULT_PROFILE)
    if matches is None:
        return None
    serves: list[ProcessRecord] = []
    for record in matches:
        is_serve = _is_serve_process(record, companion_path, DEFAULT_PROFILE)
        if is_serve is None:
            return None
        if is_serve:
            serves.append(record)
    result: list[_OwnedCompanionTarget] = []
    for record in serves:
        target = _validated_owned_companion(context, records, companion_path, record)
        if target is None:
            return None
        result.append(target)
    return tuple(result)


def _select_owned_companion(context: RowContext) -> _OwnedCompanionTarget | None:
    companion_path = _companion_path(context)
    records = context.process_table.snapshot()
    matches = _matching_companion_processes(records, companion_path, DEFAULT_PROFILE)
    if matches is None:
        return None
    serves: list[ProcessRecord] = []
    for record in matches:
        is_serve = _is_serve_process(record, companion_path, DEFAULT_PROFILE)
        if is_serve is None:
            return None
        if is_serve:
            serves.append(record)
    if len(serves) != 1:
        return None
    return _validated_owned_companion(context, records, companion_path, serves[0])


def _same_companion_target(
    first: _OwnedCompanionTarget, second: _OwnedCompanionTarget
) -> bool:
    return bool(
        first.pid == second.pid
        and first.uid == second.uid
        and first.started_at == second.started_at
        and _normalized_creation_token(first.creation_token)
        == _normalized_creation_token(second.creation_token)
    )


@dataclass(frozen=True, slots=True)
class HostOutputStreamCount:
    bytes_observed: int = 0
    truncated: bool = False


class ManagedHostOutputCounters:
    """Drain child streams immediately while retaining counters only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stdout = HostOutputStreamCount()
        self._stderr = HostOutputStreamCount()

    def add(self, stream: str, data: bytes) -> None:
        if stream not in {"stdout", "stderr"}:
            return
        with self._lock:
            current = self._stdout if stream == "stdout" else self._stderr
            new_count = current.bytes_observed + len(data)
            selected = HostOutputStreamCount(
                min(MAX_HOST_OUTPUT_BYTES_PER_STREAM, new_count),
                current.truncated or new_count > MAX_HOST_OUTPUT_BYTES_PER_STREAM,
            )
            if stream == "stdout":
                self._stdout = selected
            else:
                self._stderr = selected

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            stdout = self._stdout
            stderr = self._stderr
        return {
            "schema": "n3-managed-host-output-counters.v1",
            "raw_output_retained": False,
            "max_stream_bytes_per_process": MAX_HOST_OUTPUT_BYTES_PER_STREAM,
            "processes": [
                {
                    "process_index": 1,
                    "stdout": {
                        "bytes_observed": stdout.bytes_observed,
                        "truncated": stdout.truncated,
                    },
                    "stderr": {
                        "bytes_observed": stderr.bytes_observed,
                        "truncated": stderr.truncated,
                    },
                }
            ],
        }


def build_host_environment(
    sandbox_root: Path,
    state_root: Path,
    run_id: str,
) -> dict[str, str]:
    """Build the exact managed-host environment; inherited secrets are excluded."""
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise GateError("run_id_invalid")
    state_paths = {
        "HOME": state_root / "home",
        "XDG_CONFIG_HOME": state_root / "config",
        "XDG_DATA_HOME": state_root / "data",
        "XDG_STATE_HOME": state_root,
        "XDG_CACHE_HOME": state_root / "cache",
        "XDG_RUNTIME_DIR": state_root / "runtime",
        "TMPDIR": state_root / "tmp",
    }
    environment = {
        "PATH": os.defpath,
        "PYTHONPATH": str(sandbox_root),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NEQ_OPEN_BROWSER": "0",
        "NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS": "1",
        "NEQ_N3_GATE_RUN_ID": run_id,
        "NEQ_PROVIDER_ATTEMPT_BUDGET": str(PROVIDER_BUDGET),
        "NEQ_PROVIDER_ATTEMPT_LEDGER": str(
            sandbox_root / _PROVIDER_LEDGER_RELATIVE
            / ("provider-attempt-ledger-" + run_id + ".jsonl")
        ),
        "NEQ_PROVIDER_ATTEMPT_RUN_ID": run_id,
    }
    environment.update({key: str(path) for key, path in state_paths.items()})
    return environment


class ManagedHostHarness:
    """Own exactly one isolated host process group and its teardown."""

    def __init__(
        self,
        root: Path,
        sandbox_root: Path,
        state_root: Path,
        run_id: str,
        *,
        process_factory: Callable[..., subprocess.Popen[bytes]] | None = None,
        port_inspector: preflight_gate.PortInspector | None = None,
        readiness_probe: Callable[[], bool] | None = None,
        signal_group: Callable[[int, int], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        start_timeout: float = HOST_START_TIMEOUT_SECONDS,
        stop_timeout: float = HOST_STOP_TIMEOUT_SECONDS,
        poll_interval: float = HOST_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.root = root
        self.sandbox_root = sandbox_root
        self.state_root = state_root
        self.run_id = run_id
        self.environment = build_host_environment(sandbox_root, state_root, run_id)
        self._process_factory = process_factory or subprocess.Popen
        self._port_inspector = port_inspector or preflight_gate.SystemPortInspector()
        self._readiness_probe = readiness_probe or self._http_readiness_probe
        self._signal_group = signal_group or os.killpg
        self._monotonic = monotonic
        self._sleep = sleep
        self._start_timeout = start_timeout
        self._stop_timeout = stop_timeout
        self._poll_interval = poll_interval
        self.process: subprocess.Popen[bytes] | None = None
        self._pgid: int | None = None
        self.process_generation = 0
        self.owned_pids: list[int] = []
        self._state_root_identity: tuple[int, int] | None = None
        self._state_parent_identity: tuple[int, int] | None = None
        self.output = ManagedHostOutputCounters()
        self._drainers: list[threading.Thread] = []
        self._stop_signal_error = False

    @property
    def owner_pid(self) -> int | None:
        return None if self.process is None else self.process.pid

    def start(self) -> bool:
        if self.process is not None:
            return False
        if not _ports_are_free(self._port_inspector):
            return False
        python_path = self.root / ".venv" / "bin" / "python"
        if not python_path.is_file():
            return False
        if self._state_root_identity is None:
            _create_private_state_tree(self.state_root)
            self._state_root_identity = _private_state_tree_identity(self.state_root)
            self._state_parent_identity = _private_state_parent_identity(
                self.state_root.parent
            )
        elif not _private_state_tree_matches(
            self.state_root, self._state_root_identity
        ) or not _private_state_parent_matches(
            self.state_root.parent, self._state_parent_identity
        ):
            raise GateError("gate_state_root_invalid")
        try:
            child = self._process_factory(
                [str(python_path), "-c", "import run_web; run_web.main()"],
                cwd=str(self.sandbox_root),
                env=dict(self.environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if not isinstance(getattr(child, "pid", None), int) or child.pid <= 0:
            return False
        self.process = child
        self._pgid = child.pid
        self.process_generation += 1
        self.owned_pids.append(child.pid)
        self._start_drainers(child)
        if not self._wait_until_ready():
            self.stop()
            return False
        observation = self._port_inspector.inspect(HOST_PORT)
        if not _port_is_owned_by(observation, HOST_PORT, child.pid):
            self.stop()
            return False
        player = self._port_inspector.inspect(PLAYER_PORT)
        if player.state != "free" or player.pids:
            self.stop()
            return False
        return True

    def stop(self) -> bool:
        child = self.process
        pgid = self._pgid
        if child is None:
            return _ports_are_free(self._port_inspector)
        if pgid is None or child.pid != pgid or child.pid <= 0:
            return False
        if child.poll() is None:
            if not self._signal_owned_group(signal.SIGTERM):
                self._stop_signal_error = True
            stopped = self._wait_for_exit_and_free(self._stop_timeout)
            if not stopped:
                if not self._signal_owned_group(signal.SIGKILL):
                    self._stop_signal_error = True
                stopped = self._wait_for_exit_and_free(self._stop_timeout)
        else:
            stopped = self._ports_free_after_exit()
        if not stopped:
            return False
        try:
            child.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            return False
        for drainer in self._drainers:
            drainer.join(timeout=1.0)
        if any(thread.is_alive() for thread in self._drainers):
            return False
        ports_free = _ports_are_free(self._port_inspector)
        if ports_free:
            self.process = None
            self._pgid = None
        return ports_free and not self._stop_signal_error

    def _signal_owned_group(self, selected_signal: int) -> bool:
        if self.process is None or self._pgid != self.process.pid:
            return False
        try:
            self._signal_group(self._pgid, selected_signal)
            return True
        except ProcessLookupError:
            return True
        except OSError:
            return False

    def _wait_until_ready(self) -> bool:
        deadline = self._monotonic() + self._start_timeout
        max_polls = max(1, int(self._start_timeout / self._poll_interval) + 2)
        for _attempt in range(max_polls):
            child = self.process
            if child is None or child.poll() is not None:
                return False
            try:
                if self._readiness_probe() is True:
                    return True
            except Exception:
                return False
            if self._monotonic() >= deadline:
                return False
            self._sleep(self._poll_interval)
        return False

    def _wait_for_exit_and_free(self, timeout: float) -> bool:
        deadline = self._monotonic() + timeout
        max_polls = max(1, int(timeout / self._poll_interval) + 2)
        for _attempt in range(max_polls):
            child = self.process
            if child is None:
                return _ports_are_free(self._port_inspector)
            if child.poll() is not None and self._ports_free_after_exit():
                return True
            if self._monotonic() >= deadline:
                return False
            self._sleep(self._poll_interval)
        return False

    def _ports_free_after_exit(self) -> bool:
        child = self.process
        return child is not None and child.poll() is not None and _ports_are_free(
            self._port_inspector
        )

    def _http_readiness_probe(self) -> bool:
        connection: http.client.HTTPConnection | None = None
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", HOST_PORT, timeout=1.0
            )
            connection.request(
                "GET", "/", headers={"Host": "127.0.0.1:%d" % HOST_PORT}
            )
            response = connection.getresponse()
            response.read(4096)
            return response.status == 200
        except (OSError, http.client.HTTPException, ValueError):
            return False
        finally:
            if connection is not None:
                connection.close()

    def _start_drainers(self, child: subprocess.Popen[bytes]) -> None:
        for name, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
            if stream is None:
                continue
            thread = threading.Thread(
                target=self._drain_stream,
                args=(name, stream),
                name="n3-live-host-" + name,
                daemon=True,
            )
            thread.start()
            self._drainers.append(thread)

    def _drain_stream(self, name: str, stream: io.BufferedReader[bytes]) -> None:
        while True:
            try:
                chunk = stream.read(4096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            self.output.add(name, chunk)


@dataclass(frozen=True, slots=True)
class LiveGateDependencies:
    root: Path
    identity_reader: Callable[[Path], preflight_gate.WorkspaceIdentity]
    port_inspector: preflight_gate.PortInspector
    preflight_reader: Callable[[Path, str, str], Mapping[str, object]]
    companion_verifier: Callable[[Path, str], Mapping[str, object]]
    sandbox_validator: Callable[[Path], Path]
    host_factory: Callable[[Path, Path, Path, str], ManagedHostHarness]
    api_factory: Callable[[], HostApiClient]
    state_base_provider: Callable[[], Path] = _default_state_cache_base
    executor_registry: Mapping[str, RowExecutor] = ROW_EXECUTORS
    monotonic: Callable[[], float] = time.monotonic
    utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    sleep: Callable[[float], None] = time.sleep
    public_client_factory: Callable[[], PublicUrlClient] = PublicUrlClient
    process_table_factory: Callable[[], ProcessTable] = SystemProcessTable
    process_identity_probe: Callable[[int], object | None] = probe_process_identity
    signal_process: Callable[[int, int], None] = os.kill
    identity_observer_factory: Callable[[ProfileLayout, Path], IdentityObserver] = (
        lambda layout, path: DefaultIdentityObserver(layout, path)
    )


def _default_dependencies(root: Path) -> LiveGateDependencies:
    return LiveGateDependencies(
        root=root,
        identity_reader=preflight_gate.read_workspace_identity,
        port_inspector=preflight_gate.SystemPortInspector(),
        preflight_reader=load_preflight_report,
        companion_verifier=verify_installed_companion,
        sandbox_validator=validate_prepared_sandbox,
        host_factory=lambda _root, sandbox, state, run_id: ManagedHostHarness(
            root,
            sandbox,
            state,
            run_id,
            port_inspector=preflight_gate.SystemPortInspector(),
        ),
        api_factory=HostApiClient,
    )


def load_preflight_report(
    root: Path, report_argument: str, expected_sha: str
) -> Mapping[str, object]:
    report_path = _safe_project_file(root, report_argument)
    try:
        relative_report = report_path.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        raise GateError("preflight_report_invalid") from None
    prefix = EVIDENCE_BASE.parts
    relative_parts = relative_report.parts
    if (
        len(relative_parts) != len(prefix) + 3
        or relative_parts[: len(prefix)] != prefix
        or RUN_ID_PATTERN.fullmatch(relative_parts[len(prefix)]) is None
        or relative_parts[-2:] != ("preflight", "preflight.json")
    ):
        raise GateError("preflight_report_invalid")
    report_run_id = relative_parts[len(prefix)]
    try:
        raw = _read_bounded_regular_file(
            report_path, MAX_PREFLIGHT_BYTES, "preflight_report_invalid"
        )
        if not raw:
            raise GateError("preflight_report_invalid")
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except GateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise GateError("preflight_report_invalid") from None
    if not isinstance(document, dict):
        raise GateError("preflight_report_invalid")
    infrastructure = document.get("infrastructure_failures")
    if not isinstance(infrastructure, list):
        raise GateError("preflight_report_invalid")
    if infrastructure:
        raise GateError("preflight_infrastructure_failures")
    if "head" in document and document.get("head") != expected_sha:
        raise GateError("preflight_report_invalid")

    # Accept the compact preflight receipt emitted by the earlier N2-style
    # gate as well as the richer N3 provider-free report below. The lock still
    # binds this exact report path to the booked SHA; the compact receipt must
    # bind its own head to that same SHA and report zero infrastructure faults.
    if document.get("gate") != "N3-provider-free-preflight":
        if (
            document.get("head") != expected_sha
            or (
                "run_id" in document
                and document.get("run_id") != report_run_id
            )
        ):
            raise GateError("preflight_report_invalid")
        return document

    identity = document.get("identity")
    invocation = document.get("invocation")
    manifest = document.get("manifest")
    rows = document.get("rows")
    teardown = document.get("teardown")
    fault_checks = document.get("fault_checks")
    expected_row_ids = [row.row_id for row in preflight_gate.SCENARIO_ROWS]
    expected_caps = preflight_gate.asdict(preflight_gate.FROZEN_CAPS)
    expected_platforms = list(preflight_gate.APPROVED_PLATFORMS)
    expected_fault_checks = {
        "missing_row_fail_fast",
        "attempt_cap_fail_fast",
        "time_cap_fail_fast",
        "teardown_failure_retains_lock",
    }
    row_records_valid = isinstance(rows, list) and len(rows) == len(expected_row_ids)
    if row_records_valid:
        for expected_row, record in zip(preflight_gate.SCENARIO_ROWS, rows):
            elapsed = record.get("elapsed_seconds") if isinstance(record, dict) else None
            if (
                not isinstance(record, dict)
                or record.get("row_id") != expected_row.row_id
                or record.get("expected") != expected_row.expected
                or not isinstance(record.get("observed"), dict)
                or record.get("verdict") != "PASS"
                or type(elapsed) not in {int, float}
                or not math.isfinite(float(elapsed))
                or elapsed < 0
            ):
                row_records_valid = False
                break
    invocation_command = invocation.get("command") if isinstance(invocation, dict) else None
    if (
        document.get("gate") != "N3-provider-free-preflight"
        or document.get("run_id") != report_run_id
        or document.get("preflight_mode") != "provider-free"
        or document.get("preflight_verdict") != "READY_FOR_PRIMARY_REVIEW"
        or document.get("gate_verdict") != "PENDING"
        or document.get("is_gate_pass") is not False
        or not isinstance(identity, dict)
        or identity.get("git_sha") != expected_sha
        or identity.get("worktree") != "clean"
        or identity.get("platform") != "darwin-arm64"
        or any(
            not isinstance(identity.get(field_name), str)
            or re.fullmatch(r"[0-9a-f]{64}", identity[field_name]) is None
            for field_name in (
                "source_files_sha256",
                "dependency_lock_sha256",
                "route_contract_sha256",
                "identity_freeze_sha256",
            )
        )
        or not isinstance(invocation, dict)
        or invocation.get("expected_sha") != expected_sha
        or invocation.get("cwd") != str(root.resolve(strict=True))
        or invocation.get("pythonpath") != "."
        or not isinstance(invocation_command, list)
        or not invocation_command
        or len(invocation_command) > 64
        or any(
            not isinstance(part, str)
            or not part
            or len(part) > 4096
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            for part in invocation_command
        )
        or not isinstance(manifest, dict)
        or manifest.get("sha256") != preflight_gate.SCENARIO_MANIFEST_SHA256
        or manifest.get("row_ids") != expected_row_ids
        or manifest.get("frozen_caps") != expected_caps
        or manifest.get("approved_platforms") != expected_platforms
        or document.get("caps_match_manifest") is not True
        or document.get("effective_caps") != expected_caps
        or document.get("row_coverage_complete") is not True
        or not row_records_valid
        or type(document.get("attempts")) is not int
        or document.get("attempts") != len(expected_row_ids)
        or document.get("ports") != {"host": HOST_PORT, "player": PLAYER_PORT}
        or not isinstance(teardown, dict)
        or teardown.get("complete") is not True
        or any(
            teardown.get(field_name) is not True
            for field_name in (
                "service_stopped",
                "host_stopped",
                "capture_copy_removed",
                "ports_free",
                "lock_released",
            )
        )
        or not isinstance(fault_checks, dict)
        or set(fault_checks) != expected_fault_checks
        or any(
            not isinstance(check, dict) or check.get("passed") is not True
            for check in fault_checks.values()
        )
        or not _is_zero_count(document.get("providers_called"))
        or not _is_zero_count(document.get("relay_connections"))
        or not _is_zero_count(document.get("provider_attempt_budget_used"))
        or not _is_zero_count(document.get("relay_attempt_budget_used"))
        or document.get("semantic_failures") != []
    ):
        raise GateError("preflight_report_invalid")
    return document


def _is_zero_count(value: object) -> bool:
    return type(value) is int and value == 0


def _safe_project_file(root: Path, path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value or "\x00" in path_value:
        raise GateError("preflight_report_missing")
    supplied = Path(path_value)
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        root_real = root.resolve(strict=True)
        candidate_abs = Path(os.path.abspath(candidate))
        candidate_abs.relative_to(root_real)
    except (OSError, RuntimeError, ValueError):
        raise GateError("preflight_report_invalid") from None
    current = root_real
    try:
        for part in candidate_abs.relative_to(root_real).parts:
            current = current / part
            if current.is_symlink():
                raise GateError("preflight_report_invalid")
        resolved = candidate_abs.resolve(strict=True)
        resolved.relative_to(root_real)
    except GateError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise GateError("preflight_report_missing") from None
    return resolved


def verify_lock_record(
    lock_directory: Path,
    *,
    root: Path,
    arguments: RunArguments,
    platform_key: str,
    now: datetime | None = None,
) -> Mapping[str, object]:
    """Read and verify the primary-owned lock without changing it."""
    parent_descriptor: int | None = None
    lock_descriptor: int | None = None
    holder_descriptor: int | None = None
    try:
        parent_path = lock_directory.parent
        parent_info = parent_path.lstat()
        directory_info = lock_directory.lstat()
        if (
            stat.S_ISLNK(parent_info.st_mode)
            or not stat.S_ISDIR(parent_info.st_mode)
            or stat.S_ISLNK(directory_info.st_mode)
            or not stat.S_ISDIR(directory_info.st_mode)
        ):
            raise GateError("lock_record_invalid")
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        open_flags = os.O_RDONLY | nofollow | directory_flag
        parent_descriptor = os.open(parent_path, open_flags)
        opened_parent = os.fstat(parent_descriptor)
        if (opened_parent.st_dev, opened_parent.st_ino) != (
            parent_info.st_dev,
            parent_info.st_ino,
        ):
            raise GateError("lock_record_invalid")
        lock_descriptor = os.open(
            lock_directory.name, open_flags, dir_fd=parent_descriptor
        )
        opened_lock = os.fstat(lock_descriptor)
        if (opened_lock.st_dev, opened_lock.st_ino) != (
            directory_info.st_dev,
            directory_info.st_ino,
        ):
            raise GateError("lock_record_invalid")
        holder_info = os.stat(
            "holder.json", dir_fd=lock_descriptor, follow_symlinks=False
        )
        if (
            stat.S_ISLNK(holder_info.st_mode)
            or not stat.S_ISREG(holder_info.st_mode)
            or holder_info.st_size < 1
            or holder_info.st_size > MAX_LOCK_BYTES
        ):
            raise GateError("lock_record_invalid")
        holder_descriptor = os.open(
            "holder.json",
            os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
            dir_fd=lock_descriptor,
        )
        opened_holder = os.fstat(holder_descriptor)
        if (
            not stat.S_ISREG(opened_holder.st_mode)
            or (opened_holder.st_dev, opened_holder.st_ino)
            != (holder_info.st_dev, holder_info.st_ino)
        ):
            raise GateError("lock_record_invalid")
        raw = os.read(holder_descriptor, MAX_LOCK_BYTES + 1)
    except GateError:
        raise
    except OSError:
        raise GateError("lock_unavailable") from None
    finally:
        for descriptor in (holder_descriptor, lock_descriptor, parent_descriptor):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    if len(raw) > MAX_LOCK_BYTES:
        raise GateError("lock_record_invalid")
    try:
        text = raw.decode("utf-8")
        lines = text.splitlines()
        if len(lines) != 1 or not lines[0].strip():
            raise ValueError("line_count")
        record = json.loads(
            lines[0],
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise GateError("lock_record_invalid") from None
    if not isinstance(record, dict):
        raise GateError("lock_record_invalid")

    run_evidence = (EVIDENCE_BASE / arguments.run_id / "capture").as_posix()
    if (
        record.get("booking_id") != arguments.booking_id
        or record.get("holder") != "N agent-run"
        or record.get("gate") != GATE_ID
        or record.get("run_id") != arguments.run_id
        or record.get("head") != arguments.sha
        or record.get("preflight_report") != arguments.preflight_report
        or record.get("evidence") != run_evidence
        or not _valid_authorizing_ruling(record.get("authorizing_ruling"))
    ):
        raise GateError("lock_record_mismatch")
    frozen_caps = record.get("frozen_caps")
    if not _valid_lock_caps(frozen_caps, platform_key):
        raise GateError("lock_caps_mismatch")

    start = _parse_aware_datetime(record.get("window_start"))
    end = _parse_aware_datetime(record.get("window_end"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise GateError("lock_window_invalid")
    duration_seconds = (end - start).total_seconds()
    window_hours = frozen_caps["window_hours"]
    if (
        duration_seconds <= 0
        or duration_seconds > 3 * 60 * 60
        or duration_seconds > float(window_hours) * 60 * 60
        or start > current
        or end <= current
    ):
        raise GateError("lock_window_expired")
    return record


def _valid_lock_caps(value: object, platform_key: str) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "party_size",
        "platform",
        "provider_dispatch_attempts",
        "max_tunnel_creations",
        "max_companion_launches",
        "window_hours",
    }:
        return False
    hours = value.get("window_hours")
    return bool(
        type(value.get("party_size")) is int
        and value["party_size"] == 1
        and value.get("platform") == platform_key
        and type(value.get("provider_dispatch_attempts")) is int
        and value["provider_dispatch_attempts"] == 0
        and type(value.get("max_tunnel_creations")) is int
        and value["max_tunnel_creations"] == FROZEN_CAPS["relay_tunnel_creations"]
        and type(value.get("max_companion_launches")) is int
        and value["max_companion_launches"] == FROZEN_CAPS["companion_serve_launches"]
        and type(hours) in {int, float}
        and 0 < float(hours) <= 3
    )


def _valid_authorizing_ruling(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 256
        and all(" " <= character <= "~" for character in value)
    )


def _parse_aware_datetime(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise GateError("lock_window_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GateError("lock_window_invalid") from None
    if parsed.tzinfo is None:
        raise GateError("lock_window_invalid")
    return parsed.astimezone(timezone.utc)


def validate_prepared_sandbox(root: Path) -> Path:
    """Mirror managed-host sandbox checks without importing/executing config.py."""
    expected = root / CAPTURE_RELATIVE
    try:
        root_real = root.resolve(strict=True)
        candidate = Path(os.path.abspath(expected))
        if candidate != root_real / CAPTURE_RELATIVE:
            raise GateError("capture_root_invalid")
        _assert_no_symlink_components(root_real, candidate)
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise GateError("capture_root_invalid")
        if candidate.resolve(strict=True) != candidate:
            raise GateError("capture_root_invalid")
        for filename in ("run_web.py", "config.py"):
            path = candidate / filename
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise GateError("capture_files_invalid")
        frontend = candidate / "web" / "frontend"
        _assert_no_symlink_components(candidate, frontend)
        if not frontend.is_dir() or frontend.resolve(strict=True) != frontend:
            raise GateError("capture_frontend_invalid")
        config_bytes = (candidate / "config.py").read_bytes()
        if not _config_has_exact_web_port(config_bytes):
            raise GateError("capture_web_port_invalid")
    except GateError:
        raise
    except (OSError, RuntimeError, UnicodeError, SyntaxError, ValueError):
        raise GateError("capture_sandbox_invalid") from None
    return candidate


def _assert_no_symlink_components(parent: Path, candidate: Path) -> None:
    try:
        relative = candidate.relative_to(parent)
    except ValueError:
        raise GateError("capture_path_escape") from None
    current = parent
    if current.is_symlink():
        raise GateError("capture_symlink_rejected")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise GateError("capture_symlink_rejected")


def _config_has_exact_web_port(source_bytes: bytes) -> bool:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source_bytes).readline)
        source = source_bytes.decode(encoding)
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, UnicodeError, tokenize.TokenError, IndentationError):
        return False
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "WEB_PORT"
    ]
    if len(assignments) != 1:
        return False
    assignment = assignments[0]
    target = assignment.targets[0]
    stores = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "WEB_PORT"
        and isinstance(node.ctx, (ast.Store, ast.Del))
    ]
    if len(stores) != 1 or stores[0] is not target:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "WEB_PORT" and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            return False
        if isinstance(node, (ast.arg, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if getattr(node, "arg", getattr(node, "name", None)) == "WEB_PORT":
                return False
        if isinstance(node, ast.ExceptHandler) and node.name == "WEB_PORT":
            return False
        if isinstance(node, (ast.Global, ast.Nonlocal)) and "WEB_PORT" in node.names:
            return False
        if isinstance(node, ast.alias) and (
            node.asname or node.name.split(".")[0]
        ) == "WEB_PORT":
            return False
        if type(node).__name__ in {"MatchAs", "MatchStar"} and getattr(
            node, "name", None
        ) == "WEB_PORT":
            return False
        if type(node).__name__ == "MatchMapping" and getattr(
            node, "rest", None
        ) == "WEB_PORT":
            return False
    value = assignment.value
    if not (
        isinstance(value, ast.Constant)
        and type(value.value) is int
        and value.value == HOST_PORT
    ):
        return False
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if (
                token.type == tokenize.OP
                and token.string == ";"
                and assignment.lineno <= token.start[0] <= assignment.end_lineno
            ):
                return False
    except (tokenize.TokenError, IndentationError):
        return False
    return True


def verify_installed_companion(root: Path, platform_key: str) -> Mapping[str, object]:
    """Load runtime pins, resolve the installed companion, and verify its digest."""
    if platform_key != "macos-arm64":
        raise GateError("live_platform_not_supported")
    try:
        from web.extensions.opentunnel_sharing.service import load_companion_manifest

        manifest = load_companion_manifest(root)
    except Exception:
        raise GateError("companion_manifest_unavailable") from None
    resolution = resolve_companion(
        root, manifest, system="Darwin", machine="arm64"
    )
    if (
        resolution.state != "resolved"
        or resolution.path is None
        or resolution.expected_sha256 is None
        or not verify_companion_digest(resolution.path, resolution.expected_sha256)
    ):
        raise GateError("companion_digest_invalid")
    expected = (
        root
        / "runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel"
    ).resolve(strict=True)
    if resolution.path.resolve(strict=True) != expected:
        raise GateError("companion_path_mismatch")
    return {
        "path": resolution.path,
        "sha256": resolution.expected_sha256,
        "platform": platform_key,
    }


def check_workspace_identity(
    dependencies: LiveGateDependencies, arguments: RunArguments
) -> tuple[preflight_gate.WorkspaceIdentity, str]:
    if RUN_ID_PATTERN.fullmatch(arguments.run_id) is None:
        raise GateError("run_id_invalid")
    if SHA_PATTERN.fullmatch(arguments.sha) is None:
        raise GateError("sha_invalid")
    if BOOKING_ID_PATTERN.fullmatch(arguments.booking_id) is None:
        raise GateError("booking_id_invalid")
    if type(arguments.party_size) is not int or arguments.party_size != 1:
        raise GateError("party_size_unsupported")
    if not verify_frozen_manifest():
        raise GateError("manifest_digest_mismatch")
    try:
        identity = dependencies.identity_reader(dependencies.root)
    except Exception:
        raise GateError("workspace_identity_unavailable") from None
    if not identity.worktree_clean:
        raise GateError("worktree_dirty")
    if identity.git_sha != arguments.sha:
        raise GateError("sha_mismatch")
    platform_key = _live_platform_key(identity.platform_key)
    if platform_key != "macos-arm64":
        raise GateError("live_platform_not_supported")
    return identity, platform_key


def _live_platform_key(value: str) -> str:
    if value == "darwin-arm64":
        return "macos-arm64"
    if value == "linux-arm64":
        return "linux-arm64"
    return value


def _validate_run_paths(
    root: Path, arguments: RunArguments, state_cache_base: Path
) -> tuple[Path, Path, Path]:
    run_root = root / EVIDENCE_BASE / arguments.run_id
    capture_dir = run_root / "capture"
    try:
        raw_base = Path(os.fspath(state_cache_base))
    except (OSError, TypeError, ValueError):
        raise GateError("gate_state_root_invalid") from None
    if not raw_base.is_absolute():
        raise GateError("gate_state_root_invalid")
    base = Path(os.path.abspath(os.fspath(raw_base)))
    state_root = base / "neq-n3g" / _state_root_id8(arguments.run_id)
    socket_path = (
        state_root
        / "neq"
        / "opentunnel"
        / DEFAULT_PROFILE
        / "run"
        / (DEFAULT_PROFILE + ".sock")
    )
    if len(os.fsencode(os.fspath(socket_path))) >= MAX_UNIX_SOCKET_PATH:
        raise GateError("state_root_too_long")
    _validate_state_root_candidate(root, base, state_root)
    for relative in (EVIDENCE_BASE, EVIDENCE_BASE / arguments.run_id):
        candidate = root / relative
        try:
            candidate.relative_to(root)
        except ValueError:
            raise GateError("capture_destination_invalid") from None
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise GateError("capture_destination_symlink")
    if not run_root.is_dir() or run_root.is_symlink():
        raise GateError("run_evidence_directory_missing")
    if capture_dir.exists() or capture_dir.is_symlink():
        raise GateError("capture_destination_exists")
    return run_root, capture_dir, state_root


def _validate_state_root_candidate(
    root: Path, state_cache_base: Path, state_root: Path
) -> None:
    repository_root = root.resolve(strict=True)
    forbidden_components = {".venv", "venv"}
    if forbidden_components.intersection(state_root.parts):
        raise GateError("gate_state_root_invalid")
    try:
        state_root.relative_to(repository_root)
        inside_repository = True
    except ValueError:
        inside_repository = False
    try:
        repository_root.relative_to(state_root)
        contains_repository = True
    except ValueError:
        contains_repository = False
    if inside_repository or contains_repository:
        raise GateError("gate_state_root_invalid")

    uid = os.getuid()
    missing_seen = False
    for candidate in reversed((state_cache_base, *state_cache_base.parents)):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            missing_seen = True
            continue
        except OSError:
            raise GateError("gate_state_root_invalid") from None
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise GateError("gate_state_root_invalid") from None
        if (
            missing_seen
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or resolved != candidate
        ):
            raise GateError("gate_state_root_invalid")
        if candidate == state_cache_base and metadata.st_uid != uid:
            raise GateError("gate_state_root_invalid")

    namespace = state_cache_base / "neq-n3g"
    if namespace.exists() or namespace.is_symlink():
        if not _private_state_parent_matches(namespace):
            raise GateError("gate_state_root_invalid")
    if state_root.exists() or state_root.is_symlink():
        raise GateError("gate_state_root_exists")


def _private_state_parent_matches(
    parent: Path, expected_identity: tuple[int, int] | None = None
) -> bool:
    try:
        metadata = parent.lstat()
        return bool(
            not stat.S_ISLNK(metadata.st_mode)
            and stat.S_ISDIR(metadata.st_mode)
            and stat.S_IMODE(metadata.st_mode) == 0o700
            and metadata.st_uid == os.getuid()
            and parent.resolve(strict=True) == parent
            and (
                expected_identity is None
                or (metadata.st_dev, metadata.st_ino) == expected_identity
            )
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _private_state_parent_identity(parent: Path) -> tuple[int, int]:
    if not _private_state_parent_matches(parent):
        raise GateError("gate_state_root_invalid")
    metadata = parent.lstat()
    return metadata.st_dev, metadata.st_ino


def _create_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(path, 0o700)
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or path.resolve(strict=True) != path
    ):
        raise GateError("gate_state_root_invalid")


def _ensure_private_state_parents(state_root: Path) -> list[Path]:
    state_cache_base = state_root.parent.parent
    created: list[Path] = []
    try:
        ancestors = list(reversed((state_cache_base, *state_cache_base.parents)))
        missing_seen = False
        uid = os.getuid()
        for candidate in ancestors:
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                missing_seen = True
                continue
            except OSError:
                raise GateError("gate_state_root_invalid") from None
            if (
                missing_seen
                or stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or candidate.resolve(strict=True) != candidate
            ):
                raise GateError("gate_state_root_invalid")
            if candidate == state_cache_base and metadata.st_uid != uid:
                raise GateError("gate_state_root_invalid")

        for candidate in ancestors:
            if candidate.exists():
                continue
            _create_private_directory(candidate)
            created.append(candidate)

        namespace = state_root.parent
        if namespace.exists() or namespace.is_symlink():
            if not _private_state_parent_matches(namespace):
                raise GateError("gate_state_root_invalid")
        else:
            _create_private_directory(namespace)
            created.append(namespace)
        return created
    except BaseException:
        cleanup_ok = True
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                cleanup_ok = False
        if not cleanup_ok:
            raise GateError("gate_state_cleanup_failed") from None
        raise


def _private_state_tree_matches(
    state_root: Path, expected_identity: tuple[int, int] | None = None
) -> bool:
    try:
        root_info = state_root.lstat()
        if (
            stat.S_ISLNK(root_info.st_mode)
            or not stat.S_ISDIR(root_info.st_mode)
            or stat.S_IMODE(root_info.st_mode) != 0o700
            or root_info.st_uid != os.getuid()
            or state_root.resolve(strict=True) != state_root
            or (
                expected_identity is not None
                and (root_info.st_dev, root_info.st_ino) != expected_identity
            )
        ):
            return False
        for name in ("home", "config", "data", "cache", "runtime", "tmp"):
            child = state_root / name
            child_info = child.lstat()
            if (
                stat.S_ISLNK(child_info.st_mode)
                or not stat.S_ISDIR(child_info.st_mode)
                or stat.S_IMODE(child_info.st_mode) != 0o700
                or child_info.st_uid != os.getuid()
                or child.resolve(strict=True) != child
            ):
                return False
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _private_state_tree_identity(state_root: Path) -> tuple[int, int]:
    if not _private_state_tree_matches(state_root):
        raise GateError("gate_state_root_invalid")
    metadata = state_root.lstat()
    return metadata.st_dev, metadata.st_ino


def _create_private_state_tree(state_root: Path) -> None:
    if state_root.exists() or state_root.is_symlink():
        raise GateError("gate_state_root_exists")
    created_parents = _ensure_private_state_parents(state_root)
    created_identity: tuple[int, int] | None = None
    created = False
    try:
        state_root.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = True
        root_info = state_root.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise GateError("gate_state_root_invalid")
        created_identity = (root_info.st_dev, root_info.st_ino)
        for name in ("home", "config", "data", "cache", "runtime", "tmp"):
            directory = state_root / name
            directory.mkdir(mode=0o700, exist_ok=False)
            os.chmod(directory, 0o700)
        os.chmod(state_root, 0o700)
        if not _private_state_tree_matches(state_root, created_identity):
            raise GateError("gate_state_root_invalid")
    except BaseException:
        cleanup_ok = not created
        if created and created_identity is not None:
            try:
                current = state_root.lstat()
                if (
                    stat.S_ISDIR(current.st_mode)
                    and not stat.S_ISLNK(current.st_mode)
                    and (current.st_dev, current.st_ino) == created_identity
                ):
                    shutil.rmtree(state_root)
                    cleanup_ok = not state_root.exists()
            except OSError:
                cleanup_ok = False
        for directory in reversed(created_parents):
            try:
                directory.rmdir()
            except OSError:
                cleanup_ok = False
        if not cleanup_ok:
            raise GateError("gate_state_cleanup_failed") from None
        raise


def _remove_private_state_parent_if_empty(
    parent: Path, expected_identity: object
) -> bool | None:
    if (
        not isinstance(expected_identity, tuple)
        or len(expected_identity) != 2
        or any(type(part) is not int or part < 0 for part in expected_identity)
        or not _private_state_parent_matches(parent, expected_identity)
    ):
        return None
    try:
        next(parent.iterdir())
    except StopIteration:
        try:
            parent.rmdir()
        except OSError as exc:
            if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                return False
            return None
        return True
    except OSError:
        return None
    return False


def _ports_are_free(inspector: preflight_gate.PortInspector) -> bool:
    for port in (HOST_PORT, PLAYER_PORT):
        try:
            observation = inspector.inspect(port)
        except Exception:
            return False
        if not _port_is_free(observation, port):
            return False
    return True


def _port_is_free(observation: preflight_gate.PortObservation, port: int) -> bool:
    return observation.port == port and observation.state == "free" and not observation.pids


def _port_is_owned_by(
    observation: preflight_gate.PortObservation, port: int, pid: int
) -> bool:
    return (
        observation.port == port
        and observation.state == "occupied"
        and observation.pids == (pid,)
    )


def _verify_lock(
    identity: preflight_gate.WorkspaceIdentity,
    arguments: RunArguments,
    platform_key: str,
    dependencies: LiveGateDependencies,
) -> Mapping[str, object]:
    return verify_lock_record(
        identity.git_common_dir / "neq-coordination" / "live-window.lock",
        root=dependencies.root,
        arguments=arguments,
        platform_key=platform_key,
        now=dependencies.utc_now(),
    )


def _validate_provider_ledger_target(
    sandbox_root: Path, run_id: str, *, must_not_exist: bool
) -> Path:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise GateError("run_id_invalid")
    relative = _PROVIDER_LEDGER_RELATIVE / (
        "provider-attempt-ledger-" + run_id + ".jsonl"
    )
    try:
        sandbox_absolute = Path(os.path.abspath(sandbox_root))
        sandbox_real = sandbox_root.resolve(strict=True)
        if sandbox_root.is_symlink() or sandbox_real != sandbox_absolute:
            raise GateError("provider_ledger_sandbox_invalid")
        cursor = sandbox_real
        for index, part in enumerate(relative.parts):
            cursor = cursor / part
            try:
                metadata = cursor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise GateError("provider_ledger_symlink_rejected")
            is_target = index == len(relative.parts) - 1
            if is_target:
                if not stat.S_ISREG(metadata.st_mode):
                    raise GateError("provider_ledger_invalid")
                if must_not_exist:
                    raise GateError("provider_ledger_preexisting")
            elif not stat.S_ISDIR(metadata.st_mode):
                raise GateError("provider_ledger_path_invalid")
    except GateError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise GateError("provider_ledger_path_invalid") from None
    return sandbox_real / relative


def _read_bounded_regular_file(path: Path, max_bytes: int, reason: str) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise GateError(reason)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes:
            raise GateError(reason)
        return raw
    except GateError:
        raise
    except OSError:
        raise GateError(reason) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_provider_ledger(
    path: Path,
    run_id: str,
    *,
    expected_pids: Sequence[int],
) -> dict[str, object]:
    owned_pids: list[int] = []
    try:
        for pid in expected_pids:
            if (
                type(pid) is not int
                or pid <= 0
                or len(owned_pids) >= FROZEN_CAPS["companion_serve_launches"]
            ):
                raise GateError("provider_ledger_invalid")
            owned_pids.append(pid)
    except TypeError:
        raise GateError("provider_ledger_invalid") from None
    try:
        raw = _read_bounded_regular_file(
            path, MAX_PREFLIGHT_BYTES, "provider_ledger_invalid"
        )
        if not raw or not raw.endswith(b"\n"):
            raise GateError("provider_ledger_invalid")
        records = [
            json.loads(
                line,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
            for line in raw.decode("ascii").splitlines()
        ]
    except GateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise GateError("provider_ledger_missing_or_invalid") from None
    if not records or not isinstance(records[0], dict):
        raise GateError("provider_ledger_invalid")
    header = records[0]
    if (
        header.get("event") != "header"
        or type(header.get("schema_version")) is not int
        or header.get("schema_version") != 1
        or type(header.get("budget")) is not int
        or header.get("budget") != PROVIDER_BUDGET
        or header.get("run_id") != run_id
    ):
        raise GateError("provider_ledger_identity_mismatch")
    activated = False
    activation_pids: set[int] = set()
    activation_count = 0
    reservations = 0
    attempts = 0
    for record in records[1:]:
        if (
            not isinstance(record, dict)
            or type(record.get("schema_version")) is not int
            or record.get("schema_version") != 1
            or type(record.get("budget")) is not int
            or record.get("budget") != PROVIDER_BUDGET
            or record.get("run_id") != run_id
        ):
            raise GateError("provider_ledger_invalid")
        event = record.get("event")
        record_pid = record.get("pid")
        if (
            type(record_pid) is not int
            or record_pid <= 0
            or record_pid not in owned_pids
        ):
            raise GateError("provider_ledger_invalid")
        if event == "activated":
            if (
                activation_count >= len(owned_pids)
                or record_pid != owned_pids[activation_count]
                or reservations
                or record.get("transport_guard") != "httpx-client-single-request"
            ):
                raise GateError("provider_ledger_invalid")
            activation_pids.add(record_pid)
            activation_count += 1
            activated = True
        elif event == "reservation":
            reservation_number = record.get("reservation_number")
            if (
                record_pid not in activation_pids
                or type(reservation_number) is not int
                or reservation_number != reservations + 1
            ):
                raise GateError("provider_ledger_invalid")
            reservations += 1
            attempts += 1
        elif event == "refusal":
            if (
                record_pid not in activation_pids
                or reservations < PROVIDER_BUDGET
                or type(record.get("reservation_number")) is not int
                or record.get("reservation_number") != PROVIDER_BUDGET + 1
                or record.get("reason") != "budget_exhausted"
            ):
                raise GateError("provider_ledger_invalid")
            attempts += 1
        else:
            raise GateError("provider_ledger_invalid")
    if not activated:
        raise GateError("provider_ledger_not_active")
    return {
        "activated": True,
        "activation_count": activation_count,
        "reservation_count": reservations,
        "attempt_count": attempts,
        "verdict": "FAIL" if attempts else "PASS",
    }


def derive_verdicts(
    rows: Sequence[Mapping[str, object]],
    *,
    infrastructure_failures: Sequence[str] = (),
    semantic_failures: Sequence[str] = (),
) -> dict[str, object]:
    expected_ids = [row.row_id for row in LIVE_ROWS]
    complete = (
        len(rows) == len(LIVE_ROWS)
        and all(isinstance(row, Mapping) for row in rows)
        and [row.get("row_id") for row in rows] == expected_ids
    )
    row_verdicts = [
        row.get("verdict", "BLOCKED") if isinstance(row, Mapping) else "BLOCKED"
        for row in rows
    ]
    if "FAIL" in row_verdicts or semantic_failures:
        macos_verdict = "FAIL"
        macos_reason = "required-row-or-budget-failed"
    elif (
        complete
        and all(verdict == "PASS" for verdict in row_verdicts)
        and not infrastructure_failures
    ):
        macos_verdict = "PASS"
        macos_reason = "all-required-rows-pass"
    else:
        macos_verdict = "BLOCKED"
        macos_reason = "required-row-missing-or-blocked"
    gate_verdict = (
        "FAIL"
        if macos_verdict == "FAIL"
        else "BLOCKED"
        if macos_verdict == "BLOCKED"
        else "PENDING"
    )
    return {
        "platform_verdicts": {
            "macos-arm64": {"verdict": macos_verdict, "reason": macos_reason},
            "linux-arm64": {
                "verdict": "BLOCKED",
                "reason": "owner-run-required",
            },
        },
        "gate_verdict": gate_verdict,
        "is_gate_pass": False,
    }


class _RowDeadline:
    """POSIX main-thread interrupt for a synchronous executor deadline."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._old_handler: object = None
        self._old_timer: tuple[float, float] = (0.0, 0.0)
        self._enabled = False

    def __enter__(self) -> "_RowDeadline":
        if threading.current_thread() is not threading.main_thread():
            return self
        setitimer = getattr(signal, "setitimer", None)
        if not callable(setitimer) or not hasattr(signal, "SIGALRM"):
            return self
        self._old_handler = signal.getsignal(signal.SIGALRM)
        self._old_timer = setitimer(signal.ITIMER_REAL, 0)

        def timeout_handler(_signum: int, _frame: object) -> None:
            raise TimeoutError("row_timeout")

        signal.signal(signal.SIGALRM, timeout_handler)
        setitimer(signal.ITIMER_REAL, max(0.001, self.seconds))
        self._enabled = True
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> bool:
        if self._enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old_handler)
            old_delay, old_interval = self._old_timer
            if old_delay > 0 or old_interval > 0:
                signal.setitimer(signal.ITIMER_REAL, old_delay, old_interval)
        return False


class LiveGateRunner:
    def __init__(
        self,
        dependencies: LiveGateDependencies,
        arguments: RunArguments,
    ) -> None:
        self.dependencies = dependencies
        self.arguments = arguments
        self.started = dependencies.monotonic()
        self.identity: preflight_gate.WorkspaceIdentity | None = None
        self.platform_key = "macos-arm64"
        self.run_root: Path | None = None
        self.capture_dir: Path | None = None
        self.state_root: Path | None = None
        self.state_root_id8: str | None = None
        self.state_path_sha256: str | None = None
        self.host: ManagedHostHarness | None = None
        self.api: HostApiClient | None = None
        self.context: RowContext | None = None
        self.host_started = False
        self.capture_created = False
        self.rows: list[dict[str, object]] = []
        self.infrastructure_failures: list[str] = []
        self.semantic_failures: list[str] = []
        self.teardown: dict[str, object] = {
            "sharing_stop_attempted": False,
            "sharing_stopped": False,
            "host_stop_attempted": False,
            "host_stopped": False,
            "ports_free": False,
        }
        self.started_at = _iso_utc(dependencies.utc_now())
        self.counter_snapshot: dict[str, int] = {
            "companion_launches": 0,
            "identity_up_invocations": 0,
        }
        self.cumulative_counters: dict[str, int] = {
            "companion_launches": 0,
            "identity_up_invocations": 0,
        }
        self.counter_owner_generation: int | None = None
        self.counter_owner_pid: int | None = None
        self.recovery_attempts = 0
        self.provider_ledger: dict[str, object] = {"status": "not-checked"}
        self.lock_record: Mapping[str, object] | None = None
        self.secrets: list[str] = []
        self.companion_record: dict[str, object] = {"verified": False}
        self.companion_path: Path | None = None

    def run(self) -> dict[str, object]:
        try:
            self._validate_before_side_effects()
        except GateError as exc:
            return self._refusal(exc)
        except Exception:
            return self._refusal(GateError("validation_failed"))

        assert self.run_root is not None
        assert self.capture_dir is not None
        assert self.state_root is not None
        try:
            self.capture_dir.mkdir(mode=0o700, exist_ok=False)
            self.capture_created = True
            os.chmod(self.capture_dir, 0o700)
            capture_info = self.capture_dir.lstat()
            if (
                stat.S_ISLNK(capture_info.st_mode)
                or not stat.S_ISDIR(capture_info.st_mode)
                or self.capture_dir.resolve(strict=True) != self.capture_dir
            ):
                self.capture_created = False
                raise GateError("capture_destination_invalid")
            assert self.state_root is not None
            self.host = self.dependencies.host_factory(
                self.dependencies.root,
                self.dependencies.root / CAPTURE_RELATIVE,
                self.state_root,
                self.arguments.run_id,
            )
            self.api = self.dependencies.api_factory()
            self.context = RowContext(
                self.arguments.run_id,
                self.dependencies.root,
                self.run_root,
                self.capture_dir,
                self.dependencies.root / CAPTURE_RELATIVE,
                self.api,
                self.host,
                self.secrets,
                public_client=self.dependencies.public_client_factory(),
                public_client_factory=self.dependencies.public_client_factory,
                process_table=self.dependencies.process_table_factory(),
                process_identity_probe=self.dependencies.process_identity_probe,
                signal_process=self.dependencies.signal_process,
                port_inspector=self.dependencies.port_inspector,
                companion_path=self.companion_path,
                identity_observer_factory=self.dependencies.identity_observer_factory,
                companion_sha256=(
                    self.companion_record.get("sha256")
                    if isinstance(self.companion_record.get("sha256"), str)
                    else None
                ),
                monotonic=self.dependencies.monotonic,
                sleep=self.dependencies.sleep,
            )
            self._start_host()
            if not self.infrastructure_failures and not self.semantic_failures:
                self._execute_rows()
            elif self.semantic_failures:
                self._append_blocked_rows(1, "initial-companion-counter-failure")
            else:
                self._append_blocked_rows(0, "pre-row-infrastructure-blocked")
        except GateError as exc:
            self._add_infrastructure(exc.reason)
            self._append_blocked_rows(0, exc.reason)
        except KeyboardInterrupt:
            self._add_infrastructure("driver_interrupted")
            self._append_blocked_rows(0, "driver_interrupted")
        except Exception:
            reason = (
                "driver_execution_failed"
                if self.capture_created
                else "capture_directory_create_failed"
            )
            self._add_infrastructure(reason)
            self._append_blocked_rows(0, reason)
        try:
            self._teardown()
        except Exception:
            self._add_infrastructure("teardown_exception")
            self.teardown.update(
                {
                    "sharing_stopped": False,
                    "host_stopped": False,
                    "ports_free": False,
                }
            )
        try:
            self._inspect_provider_ledger()
        except Exception:
            self._add_infrastructure("provider_ledger_inspection_failed")
        if not self.capture_created:
            return self._result_without_evidence()
        try:
            return self._persist_evidence()
        except Exception:
            self._add_infrastructure("evidence_write_failed")
            return self._result_without_evidence()

    def _validate_before_side_effects(self) -> None:
        identity, platform_key = check_workspace_identity(
            self.dependencies, self.arguments
        )
        self.identity = identity
        self.platform_key = platform_key
        if not self.dependencies.root.is_dir() or self.dependencies.root.is_symlink():
            raise GateError("repository_root_invalid")
        try:
            preflight = self.dependencies.preflight_reader(
                self.dependencies.root,
                self.arguments.preflight_report,
                self.arguments.sha,
            )
        except GateError:
            raise
        except Exception:
            raise GateError("preflight_report_invalid") from None
        preflight_identity = (
            preflight.get("identity") if isinstance(preflight, Mapping) else None
        )
        if isinstance(preflight_identity, Mapping):
            identity_matches = all(
                preflight_identity.get(report_field)
                == getattr(identity, identity_field)
                for report_field, identity_field in (
                    ("source_files_sha256", "source_files_sha256"),
                    ("dependency_lock_sha256", "dependency_lock_sha256"),
                    ("route_contract_sha256", "route_contract_sha256"),
                    ("identity_freeze_sha256", "identity_freeze_sha256"),
                )
            )
        else:
            identity_matches = (
                isinstance(preflight, Mapping)
                and preflight.get("head") == self.arguments.sha
            )
        if not identity_matches:
            raise GateError("preflight_identity_mismatch")
        lock_dir = identity.git_common_dir / "neq-coordination" / "live-window.lock"
        self.lock_record = verify_lock_record(
            lock_dir,
            root=self.dependencies.root,
            arguments=self.arguments,
            platform_key=platform_key,
            now=self.dependencies.utc_now(),
        )
        self._check_driver_time()
        try:
            state_cache_base = self.dependencies.state_base_provider()
            self.run_root, self.capture_dir, self.state_root = _validate_run_paths(
                self.dependencies.root, self.arguments, state_cache_base
            )
            self.state_root_id8 = _state_root_id8(self.arguments.run_id)
            self.state_path_sha256 = _state_path_sha256(self.state_root)
        except GateError:
            raise
        except Exception:
            raise GateError("gate_state_root_invalid") from None
        try:
            sandbox = self.dependencies.sandbox_validator(self.dependencies.root)
        except GateError:
            raise
        except Exception:
            raise GateError("capture_sandbox_invalid") from None
        if sandbox != self.dependencies.root / CAPTURE_RELATIVE:
            raise GateError("capture_sandbox_path_mismatch")
        _validate_provider_ledger_target(
            sandbox, self.arguments.run_id, must_not_exist=True
        )
        try:
            companion = self.dependencies.companion_verifier(
                self.dependencies.root, platform_key
            )
            if not isinstance(companion, Mapping):
                raise GateError("companion_unavailable")
            if companion.get("platform") != platform_key:
                raise GateError("companion_platform_mismatch")
            digest = companion.get("sha256")
            companion_path = companion.get("path")
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or not isinstance(companion_path, (str, os.PathLike))
            ):
                raise GateError("companion_digest_invalid")
            selected_path = Path(companion_path)
            try:
                selected_path_real = selected_path.resolve(strict=True)
                selected_path_real.relative_to(
                    (self.dependencies.root / "runtime/opentunnel/v0.6.2").resolve(
                        strict=True
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                raise GateError("companion_path_invalid") from None
            if not selected_path_real.is_file():
                raise GateError("companion_path_invalid")
            self.companion_path = selected_path_real
            self.companion_record = {
                "verified": True,
                "platform": platform_key,
                "sha256": digest,
            }
        except GateError:
            raise
        except Exception:
            raise GateError("companion_unavailable") from None
        if not _ports_are_free(self.dependencies.port_inspector):
            raise GateError("gate_port_not_free")
        # Recheck the shared lock immediately before any write or process launch.
        self.lock_record = verify_lock_record(
            lock_dir,
            root=self.dependencies.root,
            arguments=self.arguments,
            platform_key=platform_key,
            now=self.dependencies.utc_now(),
        )

    def _start_host(self) -> None:
        assert self.host is not None
        self._check_driver_time()
        try:
            self.host_started = self.host.start() is True
        except GateError as exc:
            self._add_infrastructure(exc.reason)
            return
        except Exception:
            self.host_started = False
        if not self.host_started:
            self._add_infrastructure("managed_host_start_failed")
            return
        if not _ports_are_host_owned(self.dependencies.port_inspector, self.host.owner_pid):
            self._add_infrastructure("managed_host_port_ownership_failed")
            return
        bind_ownership_guard = getattr(self.api, "bind_ownership_guard", None)
        if callable(bind_ownership_guard):
            try:
                bind_ownership_guard(
                    lambda: self.host is not None
                    and _host_ports_owned_or_free(
                        self.dependencies.port_inspector, self.host.owner_pid
                    )
                )
            except Exception:
                self._add_infrastructure("managed_host_port_ownership_failed")
                return
        assert self.api is not None
        try:
            status = self.api.get_status()
            _remember_payload_secrets(status.payload, self.secrets)
            counters = _status_counters(status)
        except (HostApiError, GateError):
            self._add_infrastructure("host_status_unavailable")
            return
        self._observe_counter_sample(counters)
        if counters["companion_launches"] != 0 or counters["identity_up_invocations"] != 0:
            row = LIVE_ROWS[0]
            counter_error = _counter_cap_error(self.cumulative_counters, 0)
            reason = counter_error or "unexpected_initial_companion_counters"
            if counter_error is not None:
                self._add_infrastructure(counter_error)
            self.semantic_failures.append(reason)
            self.rows.append(
                {
                    "row_id": row.row_id,
                    "name": row.name,
                    **_row_evidence_fields(row),
                    "observed": {"companion_counters_at_host_start": counters},
                    "reason": reason,
                    "elapsed_seconds": 0.0,
                    "verdict": "FAIL",
                    "companion_counters": dict(counters),
                    "companion_counters_cumulative": dict(self.cumulative_counters),
                }
            )
            return

    def _execute_rows(self) -> None:
        assert self.context is not None
        registry = self.dependencies.executor_registry
        expected_ids = [row.row_id for row in LIVE_ROWS]
        if set(registry) != set(expected_ids):
            self._add_infrastructure("row_executor_registry_mismatch")
            self._append_blocked_rows(0, "row_executor_registry_mismatch")
            return
        for index, row in enumerate(LIVE_ROWS):
            if self.infrastructure_failures or self.semantic_failures:
                self._append_blocked_rows(index, "fail-fast")
                return
            try:
                self._check_driver_time()
                self._reverify_lock()
                self._check_driver_time()
            except GateError as exc:
                self._add_infrastructure(exc.reason)
                self._append_blocked_rows(index, exc.reason)
                return
            before_status: dict[str, int]
            try:
                assert self.api is not None
                response = self.api.get_status()
                _remember_payload_secrets(response.payload, self.secrets)
                before_status = _status_counters(response)
                self._observe_counter_sample(before_status)
            except (HostApiError, GateError):
                self._add_infrastructure("host_counters_unavailable")
                self._append_blocked_rows(index, "host_counters_unavailable")
                return
            counter_error = _counter_cap_error(
                self.cumulative_counters, self.recovery_attempts
            )
            if counter_error is not None:
                self.counter_snapshot = before_status
                self._add_infrastructure(counter_error)
                self.semantic_failures.append(counter_error)
                self.rows.append(
                    {
                        "row_id": row.row_id,
                        "name": row.name,
                        **_row_evidence_fields(row),
                        "observed": {"companion_counters_before": before_status},
                        "reason": counter_error,
                        "elapsed_seconds": 0.0,
                        "verdict": "FAIL",
                        "companion_counters": before_status,
                        "relay_tunnel_creations_observed_upper_bound": (
                            self.cumulative_counters["identity_up_invocations"]
                            + self.recovery_attempts
                        ),
                        "companion_counters_cumulative": dict(self.cumulative_counters),
                    }
                )
                self._append_blocked_rows(index + 1, "fail-fast")
                return
            row_started = self.dependencies.monotonic()
            remaining = self._remaining_driver_seconds()
            timeout_seconds = min(float(row.timeout_seconds), remaining)
            if timeout_seconds <= 0:
                self._add_infrastructure("driver_time_cap_exceeded")
                self._append_blocked_rows(index, "driver_time_cap_exceeded")
                return
            try:
                with _RowDeadline(timeout_seconds):
                    result = registry[row.row_id].execute(self.context)
                if not isinstance(result, RowExecutionResult):
                    raise GateError("row_result_invalid")
            except TimeoutError:
                result = RowExecutionResult("BLOCKED", "row_timeout")
                self._add_infrastructure("row_time_cap_exceeded:" + row.row_id)
            except GateError as exc:
                result = RowExecutionResult("BLOCKED", exc.reason)
                self._add_infrastructure(exc.reason)
            except Exception:
                result = RowExecutionResult("BLOCKED", "executor_exception")
                self._add_infrastructure("executor_exception:" + row.row_id)
            elapsed = max(0.0, self.dependencies.monotonic() - row_started)
            if elapsed > row.timeout_seconds:
                result = RowExecutionResult("BLOCKED", "row_time_cap_exceeded")
                self._add_infrastructure("row_time_cap_exceeded:" + row.row_id)
            try:
                self._check_driver_time()
            except GateError as exc:
                result = RowExecutionResult("BLOCKED", exc.reason)
                self._add_infrastructure(exc.reason)
            self._observe_result_secrets(result)
            if row.row_id == "L10" and self.host is not None and self.host.owner_pid is None:
                # L10 intentionally stops the owned host and removes its private
                # state before returning. The last pre-teardown sample is the
                # final host counter observation; no request may target a port
                # that is no longer owned by this runner.
                after_status = before_status
            else:
                try:
                    assert self.api is not None
                    after_response = self.api.get_status()
                    _remember_payload_secrets(after_response.payload, self.secrets)
                    after_status = _status_counters(after_response)
                    self._observe_counter_sample(after_status)
                except (HostApiError, GateError):
                    after_status = before_status
                    result = RowExecutionResult("BLOCKED", "host_counters_unavailable")
                    self._add_infrastructure("host_counters_unavailable")
            if (
                result.recovery_attempts < 0
                or result.recovery_attempts > 1
                or (row.row_id != "L05" and result.recovery_attempts != 0)
            ):
                result = RowExecutionResult("FAIL", "recovery_override_cap_breached")
                self._add_infrastructure("recovery_override_cap_breached")
            self.recovery_attempts += result.recovery_attempts
            self.counter_snapshot = after_status
            counter_error = _counter_cap_error(
                self.cumulative_counters, self.recovery_attempts
            )
            if counter_error is not None:
                result = RowExecutionResult("FAIL", counter_error)
                self._add_infrastructure(counter_error)
            record = {
                "row_id": row.row_id,
                "name": row.name,
                **_row_evidence_fields(row),
                "observed": dict(result.observed),
                "reason": result.reason,
                "elapsed_seconds": round(elapsed, 3),
                "verdict": result.verdict,
                "companion_counters": after_status,
                "relay_tunnel_creations_observed_upper_bound": (
                    self.cumulative_counters["identity_up_invocations"]
                    + self.recovery_attempts
                ),
                "companion_counters_cumulative": dict(self.cumulative_counters),
            }
            self.rows.append(record)
            if result.verdict == "FAIL":
                self.semantic_failures.append("row_assertion_failed:" + row.row_id)
                self._append_blocked_rows(index + 1, "fail-fast")
                return
            if result.verdict != "PASS":
                self._add_infrastructure("required_row_blocked:" + row.row_id)
                self._append_blocked_rows(index + 1, "fail-fast")
                return
            self._check_provider_ledger_during_run()
            if self.infrastructure_failures or self.semantic_failures:
                self._append_blocked_rows(index + 1, "fail-fast")
                return

    def _check_provider_ledger_during_run(self) -> None:
        try:
            ledger_path = _validate_provider_ledger_target(
                self.dependencies.root / CAPTURE_RELATIVE,
                self.arguments.run_id,
                must_not_exist=False,
            )
            status = _validate_provider_ledger(
                ledger_path,
                self.arguments.run_id,
                expected_pids=getattr(self.host, "owned_pids", None),
            )
        except GateError as exc:
            self._add_infrastructure(exc.reason)
            return
        self.provider_ledger = status
        if status["attempt_count"]:
            self.semantic_failures.append("provider_attempt_observed")

    def _observe_counter_sample(self, counters: Mapping[str, int]) -> None:
        if self.host is None:
            raise GateError("host_owner_unavailable")
        owner_pid = self.host.owner_pid
        owner_generation = getattr(self.host, "process_generation", owner_pid)
        if (
            type(owner_pid) is not int
            or owner_pid <= 0
            or type(owner_generation) is not int
            or owner_generation <= 0
        ):
            raise GateError("host_owner_unavailable")
        if set(counters) != set(self.cumulative_counters):
            raise GateError("host_counters_invalid")
        same_process = (
            owner_pid == self.counter_owner_pid
            and owner_generation == self.counter_owner_generation
        )
        for key, value in counters.items():
            if type(value) is not int or value < 0:
                raise GateError("host_counters_invalid")
            if same_process:
                previous = self.counter_snapshot[key]
                if value < previous:
                    raise GateError("host_counters_regressed")
                self.cumulative_counters[key] += value - previous
            else:
                self.cumulative_counters[key] += value
        self.counter_snapshot = dict(counters)
        self.counter_owner_pid = owner_pid
        self.counter_owner_generation = owner_generation

    def _inspect_provider_ledger(self) -> None:
        if self.host is None:
            self.provider_ledger = {"status": "host-not-started"}
            return
        environment = getattr(self.host, "environment", {})
        ledger_value = environment.get("NEQ_PROVIDER_ATTEMPT_LEDGER")
        if not isinstance(ledger_value, str):
            self._add_infrastructure("provider_ledger_path_unavailable")
            return
        try:
            expected_path = _validate_provider_ledger_target(
                self.dependencies.root / CAPTURE_RELATIVE,
                self.arguments.run_id,
                must_not_exist=False,
            )
        except GateError as exc:
            self.provider_ledger = {"status": exc.reason}
            self._add_infrastructure(exc.reason)
            return
        if Path(ledger_value) != expected_path:
            self._add_infrastructure("provider_ledger_path_mismatch")
            return
        try:
            status = _validate_provider_ledger(
                expected_path,
                self.arguments.run_id,
                expected_pids=getattr(self.host, "owned_pids", None),
            )
        except GateError as exc:
            self.provider_ledger = {"status": exc.reason}
            self._add_infrastructure(exc.reason)
            return
        self.provider_ledger = status
        if status["attempt_count"]:
            self.semantic_failures.append("provider_attempt_observed")

    def _observe_result_secrets(self, result: RowExecutionResult) -> None:
        _remember_payload_secrets(result.observed, self.secrets)

    def _append_blocked_rows(self, start_index: int, reason: str) -> None:
        existing = {str(item.get("row_id")) for item in self.rows}
        for row in LIVE_ROWS[start_index:]:
            if row.row_id in existing:
                continue
            self.rows.append(
                {
                    "row_id": row.row_id,
                    "name": row.name,
                    **_row_evidence_fields(row),
                    "observed": {},
                    "reason": reason,
                    "verdict": "BLOCKED",
                }
            )

    def _reverify_lock(self) -> None:
        assert self.identity is not None
        lock_dir = self.identity.git_common_dir / "neq-coordination" / "live-window.lock"
        self.lock_record = verify_lock_record(
            lock_dir,
            root=self.dependencies.root,
            arguments=self.arguments,
            platform_key=self.platform_key,
            now=self.dependencies.utc_now(),
        )

    def _check_driver_time(self) -> None:
        if self._remaining_driver_seconds() <= 0:
            raise GateError("driver_time_cap_exceeded", verdict="BLOCKED")

    def _remaining_driver_seconds(self) -> float:
        elapsed = self.dependencies.monotonic() - self.started
        return float(FROZEN_CAPS["driver_wall_clock_seconds"]) - elapsed

    def _add_infrastructure(self, reason: str) -> None:
        if reason not in self.infrastructure_failures:
            self.infrastructure_failures.append(reason)

    def _teardown(self) -> None:
        host_port_owned = bool(
            self.host is not None
            and _host_port_owned_by(
                self.dependencies.port_inspector, self.host.owner_pid
            )
        )
        if self.host is None or (not self.host_started and not host_port_owned):
            self.teardown["sharing_stopped"] = True
        elif self.api is not None and host_port_owned:
            self.teardown["sharing_stop_attempted"] = True
            try:
                response = self.api.post("stop", {})
                _remember_payload_secrets(response.payload, self.secrets)
                self.teardown["sharing_stopped"] = bool(
                    response.status == 200 and response.payload.get("ok") is True
                )
            except Exception:
                self.teardown["sharing_stopped"] = False
        else:
            self.teardown["sharing_stopped"] = False
        if self.context is not None:
            self.context.public_client.disconnect()
        if self.host is not None:
            self.teardown["host_stop_attempted"] = True
            try:
                self.teardown["host_stopped"] = self.host.stop() is True
            except Exception:
                self.teardown["host_stopped"] = False
        else:
            self.teardown["host_stopped"] = True
        self.teardown["ports_free"] = _ports_are_free(
            self.dependencies.port_inspector
        )
        if (
            self.host_started
            and not self.teardown["sharing_stop_attempted"]
            and self.teardown["host_stopped"]
            and self.teardown["ports_free"]
        ):
            # The owned host process and both application listeners are gone,
            # so no sharing service remains to receive a local stop request.
            self.teardown["sharing_stopped"] = True
        if not self.teardown["sharing_stopped"]:
            self._add_infrastructure("sharing_teardown_failed")
        if not self.teardown["host_stopped"]:
            self._add_infrastructure("host_teardown_failed")
        if not self.teardown["ports_free"]:
            self._add_infrastructure("teardown_ports_not_free")

    def _persist_evidence(self) -> dict[str, object]:
        assert self.capture_dir is not None
        assert self.run_root is not None
        assert self.state_root_id8 is not None
        assert self.state_path_sha256 is not None
        host_output = (
            self.host.output.snapshot()
            if self.host is not None and hasattr(self.host, "output")
            else {"schema": "n3-managed-host-output-counters.v1", "raw_output_retained": False, "processes": []}
        )
        ledger_copy = self._copy_provider_ledger()
        if not ledger_copy:
            self._add_infrastructure("provider_ledger_copy_failed")
        verdicts = derive_verdicts(
            self.rows,
            infrastructure_failures=self.infrastructure_failures,
            semantic_failures=self.semantic_failures,
        )
        run_record = {
            "schema_version": 1,
            "manifest_id": MANIFEST_ID,
            "manifest_sha256": calculate_manifest_digest(),
            "run_id": self.arguments.run_id,
            "gate_state_root_id8": self.state_root_id8,
            "gate_state_path_sha256": self.state_path_sha256,
            "booking_id": self.arguments.booking_id,
            "sha": self.arguments.sha,
            "platform": self.platform_key,
            "party_size": self.arguments.party_size,
            "started_at": self.started_at,
            "finished_at": _iso_utc(self.dependencies.utc_now()),
            "preflight_report": self.arguments.preflight_report,
            "preflight_clean": True,
            "companion": dict(self.companion_record),
            "frozen_caps": dict(FROZEN_CAPS),
            "companion_counters": self.counter_snapshot,
            "companion_counters_cumulative": self.cumulative_counters,
            "recovery_override_attempts": self.recovery_attempts,
            "relay_tunnel_creations_observed_upper_bound": (
                self.cumulative_counters["identity_up_invocations"]
                + self.recovery_attempts
            ),
            "provider_ledger": self.provider_ledger,
            "provider_ledger_copy_written": ledger_copy,
            "managed_host_output_counters": host_output,
            "infrastructure_failures": list(self.infrastructure_failures),
            "semantic_failures": list(self.semantic_failures),
            "teardown": dict(self.teardown),
            **verdicts,
        }
        summary = {
            "schema_version": 1,
            "manifest_id": MANIFEST_ID,
            "manifest_sha256": calculate_manifest_digest(),
            "run_id": self.arguments.run_id,
            "gate_state_root_id8": self.state_root_id8,
            "gate_state_path_sha256": self.state_path_sha256,
            "row_coverage_complete": len(self.rows) == len(LIVE_ROWS)
            and [row.get("row_id") for row in self.rows]
            == [row.row_id for row in LIVE_ROWS],
            "rows": [
                {
                    "row_id": row.get("row_id"),
                    "verdict": row.get("verdict"),
                    "reason": row.get("reason"),
                }
                for row in self.rows
            ],
            "infrastructure_failures": list(self.infrastructure_failures),
            "semantic_failures": list(self.semantic_failures),
            "provider_attempts": self.provider_ledger.get("attempt_count", 0),
            "teardown_complete": all(
                self.teardown.get(key) is True
                for key in ("sharing_stopped", "host_stopped", "ports_free")
            ),
            **verdicts,
        }
        write_ok = True
        try:
            write_ok = _write_rows_jsonl(
                self.capture_dir / "rows.jsonl", self.rows, self.secrets
            ) and write_ok
            write_ok = _write_json_evidence(
                self.capture_dir / "managed-host-output.json", host_output, self.secrets
            ) and write_ok
            write_ok = _write_json_evidence(
                self.capture_dir / "run.json", run_record, self.secrets
            ) and write_ok
        except Exception:
            write_ok = False
        def block_unwritable_evidence() -> None:
            self._add_infrastructure("evidence_write_failed")
            verdicts = derive_verdicts(
                self.rows,
                infrastructure_failures=self.infrastructure_failures,
                semantic_failures=self.semantic_failures,
            )
            summary.update(verdicts)
            summary["infrastructure_failures"] = list(self.infrastructure_failures)
            summary["semantic_failures"] = list(self.semantic_failures)
            _force_evidence_blocked(summary)
            run_record.update(verdicts)
            run_record["infrastructure_failures"] = list(self.infrastructure_failures)
            run_record["semantic_failures"] = list(self.semantic_failures)
            _force_evidence_blocked(run_record)
            _write_json_evidence(
                self.capture_dir / "run.json", run_record, self.secrets
            )
            _write_json_evidence(
                self.capture_dir / "summary.json", summary, self.secrets
            )

        if not write_ok:
            block_unwritable_evidence()
        summary_written = _write_json_evidence(
            self.capture_dir / "summary.json", summary, self.secrets
        )
        write_ok = write_ok and summary_written
        if not summary_written:
            block_unwritable_evidence()
            _write_json_evidence(
                self.capture_dir / "summary.json", summary, self.secrets
            )
        checksums_written = _write_sha256sums(self.capture_dir)
        write_ok = write_ok and checksums_written
        if not checksums_written:
            block_unwritable_evidence()
            _write_sha256sums(self.capture_dir)
            write_ok = False
        return {
            "run_id": self.arguments.run_id,
            "gate_verdict": summary["gate_verdict"],
            "is_gate_pass": False,
            "platform_verdicts": summary["platform_verdicts"],
            "rows": summary["rows"],
            "infrastructure_failures": summary["infrastructure_failures"],
            "semantic_failures": summary["semantic_failures"],
            "evidence_path": self.capture_dir.relative_to(
                self.dependencies.root
            ).as_posix(),
            "evidence_written": write_ok,
        }

    def _copy_provider_ledger(self) -> bool:
        if self.capture_dir is None:
            return False
        destination = self.capture_dir / PROVIDER_LEDGER_NAME
        value = (
            getattr(self.host, "environment", {}).get("NEQ_PROVIDER_ATTEMPT_LEDGER")
            if self.host is not None
            else None
        )
        if not isinstance(value, str):
            _write_jsonl_records(destination, [])
            return False
        try:
            source = _validate_provider_ledger_target(
                self.dependencies.root / CAPTURE_RELATIVE,
                self.arguments.run_id,
                must_not_exist=False,
            )
        except GateError:
            _write_jsonl_records(destination, [])
            return False
        if Path(value) != source:
            _write_jsonl_records(destination, [])
            return False
        try:
            raw = _read_bounded_regular_file(
                source, MAX_PREFLIGHT_BYTES, "provider_ledger_invalid"
            )
            lines = raw.decode("ascii").splitlines()
            records = [
                json.loads(
                    line,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_json_constant,
                )
                for line in lines
                if line
            ]
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            _write_jsonl_records(destination, [])
            return False
        redacted = [redact_live_evidence(record, self.secrets) for record in records]
        return _write_jsonl_records(
            destination, redacted
        )

    def _refusal(self, error: GateError) -> dict[str, object]:
        return {
            "run_id": self.arguments.run_id,
            "gate_verdict": error.verdict,
            "is_gate_pass": False,
            "platform_verdicts": {
                "macos-arm64": {"verdict": "BLOCKED", "reason": error.reason},
                "linux-arm64": {
                    "verdict": "BLOCKED",
                    "reason": "owner-run-required",
                },
            },
            "infrastructure_failures": [error.reason],
            "evidence_path": None,
            "evidence_written": False,
        }

    def _result_without_evidence(self) -> dict[str, object]:
        return {
            "run_id": self.arguments.run_id,
            "gate_verdict": "BLOCKED",
            "is_gate_pass": False,
            "platform_verdicts": {
                "macos-arm64": {
                    "verdict": "BLOCKED",
                    "reason": "evidence-write-failed",
                },
                "linux-arm64": {
                    "verdict": "BLOCKED",
                    "reason": "owner-run-required",
                },
            },
            "infrastructure_failures": list(self.infrastructure_failures),
            "semantic_failures": list(self.semantic_failures),
            "evidence_path": None,
            "evidence_written": False,
        }


def run_live_gate(
    dependencies: LiveGateDependencies,
    arguments: RunArguments,
) -> dict[str, object]:
    return LiveGateRunner(dependencies, arguments).run()


def _status_counters(response: HostApiResponse) -> dict[str, int]:
    if response.status != 200 or response.payload.get("ok") is not True:
        raise GateError("host_status_invalid")
    status = response.payload.get("status")
    if not isinstance(status, Mapping):
        raise GateError("host_status_invalid")
    launches = status.get("companion_launches")
    ups = status.get("identity_up_invocations")
    if (
        type(launches) is not int
        or type(ups) is not int
        or launches < 0
        or ups < 0
        or launches > 1_000_000
        or ups > 1_000_000
    ):
        raise GateError("host_counters_invalid")
    return {
        "companion_launches": launches,
        "identity_up_invocations": ups,
    }


def _counter_cap_error(counters: Mapping[str, int], recovery_attempts: int) -> str | None:
    if counters["companion_launches"] > FROZEN_CAPS["companion_serve_launches"]:
        return "companion_launch_cap_breached"
    if counters["identity_up_invocations"] > FROZEN_CAPS["companion_up_invocations"]:
        return "companion_up_cap_breached"
    # Each identity `up` and each observed N3 recovery override attempt is
    # conservatively counted as a possible relay tunnel creation.
    possible_creations = counters["identity_up_invocations"] + recovery_attempts
    if possible_creations > FROZEN_CAPS["relay_tunnel_creations"]:
        return "relay_tunnel_creation_cap_breached"
    return None


def _ports_are_host_owned(
    inspector: preflight_gate.PortInspector, owner_pid: int | None
) -> bool:
    if not isinstance(owner_pid, int) or owner_pid <= 0:
        return False
    try:
        host = inspector.inspect(HOST_PORT)
        player = inspector.inspect(PLAYER_PORT)
    except Exception:
        return False
    return _port_is_owned_by(host, HOST_PORT, owner_pid) and _port_is_free(
        player, PLAYER_PORT
    )


def _host_ports_owned_or_free(
    inspector: preflight_gate.PortInspector, owner_pid: int | None
) -> bool:
    if not isinstance(owner_pid, int) or owner_pid <= 0:
        return False
    try:
        host = inspector.inspect(HOST_PORT)
        player = inspector.inspect(PLAYER_PORT)
    except Exception:
        return False
    return _port_is_owned_by(host, HOST_PORT, owner_pid) and (
        _port_is_free(player, PLAYER_PORT)
        or _port_is_owned_by(player, PLAYER_PORT, owner_pid)
    )


def _host_port_owned_by(
    inspector: preflight_gate.PortInspector, owner_pid: int | None
) -> bool:
    if not isinstance(owner_pid, int) or owner_pid <= 0:
        return False
    try:
        observation = inspector.inspect(HOST_PORT)
    except Exception:
        return False
    return _port_is_owned_by(observation, HOST_PORT, owner_pid)


def _row_expected(row: LiveRow) -> str:
    return row.expected


def _row_evidence_fields(row: LiveRow) -> dict[str, str]:
    return {
        "precondition": row.precondition,
        "action": row.action,
        "expected": _row_expected(row),
        "blocked_conditions": row.blocked,
    }


def _bounded_json(value: object) -> bool:
    count = [0]

    def visit(item: object, depth: int) -> bool:
        count[0] += 1
        if count[0] > MAX_API_JSON_NODES or depth > MAX_API_JSON_DEPTH:
            return False
        if isinstance(item, dict):
            if len(item) > 128:
                return False
            return all(
                isinstance(key, str) and len(key) <= 256 and visit(child, depth + 1)
                for key, child in item.items()
            )
        if isinstance(item, list):
            return len(item) <= 128 and all(visit(child, depth + 1) for child in item)
        if isinstance(item, str):
            return len(item) <= 16_384
        if type(item) is float:
            return math.isfinite(item)
        return item is None or type(item) in {bool, int}

    return visit(value, 0)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonstandard_json_constant")


def _remember_payload_secrets(value: object, output: list[str], key: str = "") -> None:
    normalized = key.casefold().replace("-", "_")
    if isinstance(value, Mapping):
        for child_key, child_value in list(value.items())[:128]:
            _remember_payload_secrets(child_value, output, str(child_key))
    elif isinstance(value, (list, tuple)):
        for item in value[:128]:
            _remember_payload_secrets(item, output, key)
    elif isinstance(value, str) and (
        normalized in _LIVE_SECRET_KEYS
        or "tunnel" in normalized and "id" in normalized
        or "invitation" in normalized
    ):
        if len(value) >= 3 and value not in output:
            output.append(value)


_LIVE_SECRET_KEYS = frozenset(
    {
        "url",
        "public_url",
        "invitation",
        "invitation_url",
        "credential",
        "password",
        "password_verifier",
        "verifier",
        "cookie",
        "set_cookie",
        "csrf",
        "csrf_token",
        "csrf_nonce",
        "csrf_proof",
        "authorization",
        "private_key",
        "access_token",
        "token",
        "host",
        "origin",
    }
)


def redact_live_evidence(value: object, secrets: Sequence[str] = (), key: str = "") -> object:
    normalized = key.casefold().replace("-", "_")
    if (
        normalized in _LIVE_SECRET_KEYS
        or ("tunnel" in normalized and "id" in normalized)
        or "invitation" in normalized
    ):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key)[:80]: redact_live_evidence(
                child_value, secrets, str(child_key)
            )
            for child_key, child_value in list(value.items())[:64]
        }
    if isinstance(value, (list, tuple)):
        return [redact_live_evidence(item, secrets) for item in value[:64]]
    return preflight_gate.redact_evidence(value, secrets, key=key)


def _write_json_evidence(path: Path, payload: Mapping[str, object], secrets: Sequence[str]) -> bool:
    safe = redact_live_evidence(payload, secrets)
    if not isinstance(safe, dict):
        return False
    return preflight_gate.write_redacted_evidence(path, safe, secrets)


def _write_rows_jsonl(path: Path, rows: Sequence[Mapping[str, object]], secrets: Sequence[str]) -> bool:
    redacted = [redact_live_evidence(row, secrets) for row in rows]
    return _write_jsonl_records(path, redacted)


def _write_jsonl_records(path: Path, records: Sequence[object]) -> bool:
    try:
        encoded = b"".join(
            json.dumps(
                record,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
            for record in records
        )
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _write_sha256sums(directory: Path) -> bool:
    descriptor: int | None = None
    temporary: Path | None = None
    created = False
    try:
        entries: list[str] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if path.name == "SHA256SUMS" or path.name.startswith(".SHA256SUMS.tmp-"):
                continue
            if path.is_symlink() or not path.is_file():
                return False
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append(digest + "  " + path.name)
        content = ("\n".join(entries) + "\n").encode("ascii")
        temporary = directory / (
            ".SHA256SUMS.tmp-%d-%d" % (os.getpid(), time.time_ns())
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        created = True
        try:
            os.fchmod(descriptor, 0o600)
            offset = 0
            while offset < len(content):
                offset += os.write(descriptor, content[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            descriptor = None
        os.replace(temporary, directory / "SHA256SUMS")
        created = False
        directory_descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created and temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _force_evidence_blocked(summary: dict[str, object]) -> None:
    summary["gate_verdict"] = "BLOCKED"
    summary["is_gate_pass"] = False
    platform_verdicts = summary.get("platform_verdicts")
    if isinstance(platform_verdicts, dict):
        platform_verdicts["macos-arm64"] = {
            "verdict": "BLOCKED",
            "reason": "evidence-write-failed",
        }


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen primary-owned N3 live lifecycle gate."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("plan", help="print the frozen manifest without side effects")
    run = subparsers.add_parser("run", help="run the authorized N3 live lifecycle gate")
    run.add_argument("--run-id", required=True)
    run.add_argument("--sha", required=True)
    run.add_argument("--booking-id", required=True)
    run.add_argument("--preflight-report", required=True, metavar="PATH")
    run.add_argument("--party-size", type=int, default=1)
    return parser


def _plan_document() -> dict[str, object]:
    return {
        "manifest": live_manifest(),
        "manifest_sha256": calculate_manifest_digest(),
        "plan_only": True,
        "side_effects": False,
        "gate_verdict": "PENDING",
        "is_gate_pass": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.operation == "plan":
        print(json.dumps(_plan_document(), ensure_ascii=True, sort_keys=True))
        return 0
    run_arguments = RunArguments(
        run_id=args.run_id,
        sha=args.sha,
        booking_id=args.booking_id,
        preflight_report=args.preflight_report,
        party_size=args.party_size,
    )
    try:
        result = run_live_gate(_default_dependencies(REPO_ROOT), run_arguments)
    except Exception:
        result = {
            "run_id": args.run_id,
            "gate_verdict": "BLOCKED",
            "is_gate_pass": False,
            "infrastructure_failures": ["driver_unavailable"],
            "evidence_path": None,
        }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    if result.get("gate_verdict") == "FAIL":
        return 1
    if result.get("gate_verdict") == "PENDING" and result.get("evidence_written") is True:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
