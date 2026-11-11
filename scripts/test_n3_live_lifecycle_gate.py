# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline tests for the frozen N3 live lifecycle driver core."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import math
import os
import signal
import shutil
import socket
import shlex
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping
from unittest.mock import patch

import scripts.n3_lifecycle_gate as preflight_gate
import scripts.n3_live_lifecycle_gate as gate
import web.extensions.opentunnel_sharing.profile_state as profile_state_module
from web.extensions.opentunnel_sharing.cleanup import (
    OwnedProcessRecord,
    write_owner_record,
)
from web.extensions.opentunnel_sharing.identity_bootstrap import Observation
from web.extensions.opentunnel_sharing.profile_state import prepare_profile
from web.extensions.player.contracts import make_snapshot_envelope


TEST_SHA = "a" * 40
TEST_RUN_ID = "n3-20261111-test-run"
TEST_BOOKING = "n3-booking-test"
TEST_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SCRATCH_ROOT = gate.REPO_ROOT / "tmp" / "n3-live-lifecycle-gate-tests"


class FakePortInspector:
    def __init__(self) -> None:
        self.host_pid: int | None = None
        self.host_pids: tuple[int, ...] | None = None
        self.busy_ports: set[int] = set()
        self.seen: list[int] = []

    def inspect(self, port: int) -> preflight_gate.PortObservation:
        self.seen.append(port)
        if port in self.busy_ports:
            return preflight_gate.PortObservation(port, "occupied", (999,))
        if port == gate.HOST_PORT and self.host_pids is not None:
            return preflight_gate.PortObservation(port, "occupied", self.host_pids)
        if port == gate.HOST_PORT and self.host_pid is not None:
            return preflight_gate.PortObservation(port, "occupied", (self.host_pid,))
        return preflight_gate.PortObservation(port, "free")


class FakeHost:
    def __init__(self, root: Path, sandbox: Path, state_root: Path, run_id: str, ports: FakePortInspector) -> None:
        self.owner_pid = 444
        self.owned_pids: list[int] = []
        self.listener_pids: list[int] = []
        self.state_root = state_root
        self._state_root_identity: tuple[int, int] | None = None
        self._state_parent_identity: tuple[int, int] | None = None
        self._state_parent_created = False
        self.environment = gate.build_host_environment(sandbox, state_root, run_id)
        self.output = gate.ManagedHostOutputCounters()
        self.ports = ports
        self.started = False
        self.stopped = False
        self.root = root
        self.sandbox = sandbox

    def start(self) -> bool:
        if self._state_root_identity is None:
            self._state_parent_created = gate._create_private_state_tree(
                self.state_root
            )
            self._state_root_identity = gate._private_state_tree_identity(
                self.state_root
            )
            self._state_parent_identity = gate._private_state_parent_identity(
                self.state_root.parent
            )
        self.started = True
        self.ports.host_pid = self.owner_pid
        self.owned_pids.append(self.owner_pid)
        self.listener_pids.append(self.owner_pid)
        ledger = Path(self.environment["NEQ_PROVIDER_ATTEMPT_LEDGER"])
        ledger.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "event": "header",
                "schema_version": 1,
                "budget": gate.PROVIDER_BUDGET,
                "run_id": self.environment["NEQ_PROVIDER_ATTEMPT_RUN_ID"],
            },
            {
                "event": "activated",
                "schema_version": 1,
                "budget": gate.PROVIDER_BUDGET,
                "run_id": self.environment["NEQ_PROVIDER_ATTEMPT_RUN_ID"],
                "transport_guard": "httpx-client-single-request",
                "pid": self.owner_pid,
            },
        ]
        ledger.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="ascii",
        )
        return True

    def stop(self) -> bool:
        self.stopped = True
        self.ports.host_pid = None
        return True


class FakeApi:
    def __init__(self, status_values: list[Mapping[str, object]] | None = None) -> None:
        self.status_values = list(status_values or [])
        self.calls: list[tuple[str, object]] = []
        self.last_status: Mapping[str, object] = {
            "ok": True,
            "status": {"companion_launches": 0, "identity_up_invocations": 0},
        }

    def get_status(self) -> gate.HostApiResponse:
        self.calls.append(("GET", "/api/player-sharing/status"))
        if self.status_values:
            self.last_status = self.status_values.pop(0)
        return gate.HostApiResponse(200, self.last_status)

    def post(self, action: str, payload: Mapping[str, object] | None = None) -> gate.HostApiResponse:
        self.calls.append(("POST", (action, dict(payload or {}))))
        return gate.HostApiResponse(200, {"ok": True, "reason": "stopped"})


class FakeProcess:
    def __init__(self, pid: int = 101, *, term_exits: bool = False) -> None:
        self.pid = pid
        self.stdout = io.BytesIO(b"stdout-secret-sentinel")
        self.stderr = io.BytesIO(b"stderr-secret-sentinel")
        self.returncode: int | None = None
        self.term_exits = term_exits
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("owned-host", timeout)
        return self.returncode


class PassingExecutor:
    def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
        return gate.RowExecutionResult("PASS", "injected-core-test")


class LifecycleFakeApi:
    def __init__(
        self,
        status: Mapping[str, object] | None = None,
        *,
        status_sequence: list[Mapping[str, object]] | None = None,
        on_status=None,
        post_handlers: Mapping[str, object] | None = None,
    ) -> None:
        self.status = dict(status or {})
        self.status_sequence = list(status_sequence or [])
        self.on_status = on_status
        self.post_handlers = dict(post_handlers or {})
        self.status_calls = 0
        self.calls: list[tuple[str, object]] = []

    def get_status(self) -> gate.HostApiResponse:
        self.calls.append(("GET", "/api/player-sharing/status"))
        if self.status_sequence:
            selected = self.status_sequence.pop(0)
        else:
            selected = self.status
        self.status_calls += 1
        if callable(self.on_status):
            self.on_status(selected, self.status_calls)
        return gate.HostApiResponse(200, {"ok": True, "status": dict(selected)})

    def post(
        self, action: str, payload: Mapping[str, object] | None = None
    ) -> gate.HostApiResponse:
        clean_payload = dict(payload or {})
        self.calls.append(("POST", (action, clean_payload)))
        handler = self.post_handlers.get(action)
        if callable(handler):
            return handler(clean_payload)
        if action == "copy-invitation":
            return gate.HostApiResponse(
                409, {"ok": False, "reason": "invitation_unavailable"}
            )
        return gate.HostApiResponse(
            200,
            {"ok": True, "reason": "ready", "status": self.status},
        )


class MappedPortInspector:
    def __init__(
        self, observations: Mapping[int, preflight_gate.PortObservation]
    ) -> None:
        self.observations = dict(observations)
        self.calls: list[int] = []

    def inspect(self, port: int) -> preflight_gate.PortObservation:
        self.calls.append(port)
        return self.observations.get(
            port, preflight_gate.PortObservation(port, "unknown")
        )


class FakeProcessTable:
    def __init__(self, records: tuple[gate.ProcessRecord, ...]) -> None:
        self.records = records
        self.calls = 0

    def snapshot(self) -> tuple[gate.ProcessRecord, ...]:
        self.calls += 1
        return self.records


class FakeIdentityObserver:
    def __init__(self, state: str = "absent") -> None:
        self.state = state

    def service_manager_entries(self, _profile: str) -> Observation:
        return Observation(self.state, "fake", 0)

    def profile_processes(self, _profile: str) -> Observation:
        return Observation(self.state, "fake", 0)

    def helper_processes(self) -> Observation:
        return Observation(self.state, "fake", 0)


class FakeIdentityCommandRunner:
    def __init__(
        self,
        *,
        absent_after_delete: bool = True,
        delete_returncode: int | None = 0,
        status_output: str | None = None,
    ) -> None:
        self.absent_after_delete = absent_after_delete
        self.delete_returncode = delete_returncode
        self.status_output = status_output
        self.deleted = False
        self.calls: list[tuple[tuple[str, ...], dict[str, str], float]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        environment: Mapping[str, str],
        timeout: float,
    ) -> gate.RunResult:
        self.calls.append((tuple(argv), dict(environment), timeout))
        if argv[-1] == "status":
            if self.status_output is not None:
                output = self.status_output
            elif self.deleted and self.absent_after_delete:
                output = "No tunnel exists for this profile\nService: Stopped\n"
            else:
                output = (
                    "Hostname: identity-fixture.opentunnel.xyz\n"
                    "Tunnel ID: fixture-tunnel-id\n"
                    "Service: Stopped\n"
                )
            return gate.RunResult(0, output)
        if "delete" in argv:
            if self.delete_returncode == 0 and self.absent_after_delete:
                self.deleted = True
            return gate.RunResult(self.delete_returncode, "")
        return gate.RunResult(2, "")


class FakePublicSocket:
    def __init__(self, server: "FakePublicService") -> None:
        self.server = server
        self.connected = False
        self.handlers: dict[tuple[str, str], object] = {}
        self.eio = SimpleNamespace(state="disconnected")
        self.events_received = 0

    def on(self, event: str, handler, *, namespace: str) -> None:
        self.handlers[(namespace, event)] = handler

    def connect(self, url: str, **kwargs: object) -> None:
        if not self.server.available:
            raise gate.socketio.exceptions.ConnectionError("transport unavailable")
        if kwargs.get("namespaces") == ["/"]:
            self.eio.state = "connected"
            if self.server.allow_host_namespace:
                self.connected = True
                return
            raise gate.socketio.exceptions.ConnectionError("namespace / refused")
        headers = kwargs.get("headers")
        auth = kwargs.get("auth")
        if (
            url != self.server.accepted_origin
            or self.server.player_namespace_refused
            or not isinstance(headers, Mapping)
            or headers.get("Origin") != self.server.accepted_origin
            or not self.server._cookie_value(
                headers.get("Cookie", ""), "neq_player_session"
            )
            or not isinstance(auth, Mapping)
            or set(auth) != {"client_build_id", "protocol_version"}
        ):
            raise gate.socketio.exceptions.ConnectionError(
                "namespace /player refused"
            )
        self.connected = True
        self.eio.state = "connected"

    def emit(self, event: str, _payload: object, *, namespace: str) -> None:
        handler = self.handlers.get((namespace, "player.snapshot"))
        if (
            event == "player.snapshot.request"
            and callable(handler)
            and not self.server.suppress_socket_snapshot
        ):
            self.events_received += 1
            handler(self.server.snapshot)

    def push(self, event: str, payload: object) -> None:
        handler = self.handlers.get(("/player", event))
        if self.connected and callable(handler):
            self.events_received += 1
            handler(payload)

    def disconnect(self) -> None:
        self.connected = False
        self.eio.state = "disconnected"


class FakePublicService:
    def __init__(
        self,
        origin: str = "https://neq-share.account.opentunnel.xyz",
        *,
        credential: str = "credential-secret-sentinel",
    ) -> None:
        self.accepted_origin = origin
        self.credential: str | None = credential
        self.available = True
        self.route_reachable = True
        self.challenge_index = 0
        self.session_index = 0
        self.challenges: dict[str, tuple[str, str]] = {}
        self.sessions: set[str] = set()
        self.sockets: list[FakePublicSocket] = []
        self.calls: list[tuple[str, str, str]] = []
        self.overrides: dict[tuple[str, str], gate.PublicHttpResponse] = {}
        self.suppress_socket_snapshot = False
        self.allow_host_namespace = False
        self.player_namespace_refused = False
        self.accept_invalid_credentials = False
        self.accept_forged_origin = False
        self.session_cookie_attributes = "Secure; HttpOnly; SameSite=Strict"
        self.snapshot = make_snapshot_envelope(
            "instance-id-sentinel-000000000000",
            "session-epoch-sentinel-000000000000",
            0,
            0,
            {
                "party": {
                    "members": [],
                    "active_character": None,
                    "active_character_revision": 0,
                    "world": {},
                },
                "busy": False,
            },
        )

    def socket_factory(self) -> FakePublicSocket:
        client = FakePublicSocket(self)
        self.sockets.append(client)
        return client

    def set_available(self, value: bool) -> None:
        self.available = value
        if not value:
            for client in self.sockets:
                client.disconnect()

    def start_sharing(self) -> None:
        self.available = True
        self.route_reachable = True

    def stop_sharing(self) -> None:
        self.route_reachable = False
        self.sessions.clear()
        self.challenges.clear()
        for client in self.sockets:
            client.disconnect()

    def rotate_credential(self, credential: str) -> None:
        self.credential = credential
        self.sessions.clear()
        self.challenges.clear()
        for client in self.sockets:
            client.disconnect()

    def revoke_access(self) -> None:
        self.credential = None
        self.stop_sharing()

    def emit_player_event(self, event: str = "player.update") -> None:
        for client in self.sockets:
            client.push(event, {"event": "bounded-test-event"})

    def request(
        self,
        hostname: str,
        port: int,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes | None,
        _timeout: float,
    ) -> gate.PublicHttpResponse:
        self.calls.append((method, path, hostname))
        if not self.available:
            raise gate.PublicClientError("public_transport_unavailable")
        if not self.route_reachable:
            return self._json(404, {"error": "not_found"})
        authority = hostname if port == 443 else "%s:%d" % (hostname, port)
        origin = "https://" + authority
        if headers.get("Host") != authority:
            return self._json(403, {"error": "request_rejected"})
        if origin != self.accepted_origin:
            return self._json(404, {"error": "not_found"})
        override = self.overrides.get((method, path))
        if override is not None:
            return override
        request_origin = headers.get("Origin")
        if path == "/" and method == "GET":
            self.challenge_index += 1
            nonce = "n" * 40 + str(self.challenge_index)
            cookie = "p" * 40 + str(self.challenge_index)
            self.challenges[cookie] = (
                nonce,
                request_origin or self.accepted_origin,
            )
            shell = (
                '<html><head><meta name="neq-client-build" content="'
                + "a" * 32
                + '"><meta name="neq-protocol-version" content="1"></head>'
                + '<body><input name="csrf_token" value="'
                + nonce
                + '"></body></html>'
            ).encode("ascii")
            return gate.PublicHttpResponse(
                200,
                (
                    (
                        "Set-Cookie",
                        "neq_player_prelogin=%s; Path=/; Secure; HttpOnly; SameSite=Strict"
                        % cookie,
                    ),
                    ("Content-Type", "text/html; charset=utf-8"),
                ),
                shell,
            )
        if path == "/api/player/login" and method == "POST":
            try:
                payload = json.loads((body or b"").decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                return self._json(400, {"error": "invalid_request"})
            prelogin = self._cookie_value(
                headers.get("Cookie", ""), "neq_player_prelogin"
            )
            challenge = self.challenges.get(prelogin or "")
            if (
                request_origin != self.accepted_origin
                and not self.accept_forged_origin
            ):
                return self._json(403, {"error": "request_rejected"})
            if (
                challenge is None
                or challenge[0] != payload.get("csrf_token")
                or challenge[1] != self.accepted_origin
            ):
                return self._json(403, {"error": "csrf_rejected"})
            if (
                payload.get("password") != self.credential
                and not self.accept_invalid_credentials
            ):
                return self._json(401, {"error": "invalid_credentials"})
            self.session_index += 1
            cookie = "s" * 40 + str(self.session_index)
            self.sessions.add(cookie)
            return gate.PublicHttpResponse(
                200,
                (
                    (
                        "Set-Cookie",
                        "neq_player_session=%s; Path=/; Max-Age=14400; %s"
                        % (cookie, self.session_cookie_attributes),
                    ),
                ),
                json.dumps(
                    {
                        "csrf_token": "c" * 40 + str(self.session_index),
                        "expires_at": 1900000000,
                    }
                ).encode("ascii"),
            )
        if path == "/api/player/snapshot" and method == "GET":
            if request_origin != self.accepted_origin:
                return self._json(403, {"error": "request_rejected"})
            cookie = self._cookie_value(
                headers.get("Cookie", ""), "neq_player_session"
            )
            if cookie is None or cookie not in self.sessions:
                return self._json(404, {"error": "not_found"})
            return self._json(200, self.snapshot)
        if path.startswith("/api/player-sharing/"):
            return self._json(404, {"error": "not_found"})
        return self._json(404, {"error": "not_found"})

    @staticmethod
    def _cookie_value(header: object, name: str) -> str | None:
        if not isinstance(header, str):
            return None
        for item in header.split(";"):
            key, separator, value = item.strip().partition("=")
            if separator and key == name:
                return value
        return None

    @staticmethod
    def _json(status: int, payload: Mapping[str, object]) -> gate.PublicHttpResponse:
        return gate.PublicHttpResponse(
            status,
            (("Content-Type", "application/json"),),
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        )


@contextlib.contextmanager
def network_process_tripwires():
    """Fail any accidental real process, socket, or HTTP activity in tests."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("real subprocess.run")))
        stack.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("real subprocess.Popen")))
        stack.enter_context(patch.object(socket, "socket", side_effect=AssertionError("real socket")))
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("real socket connection")))
        stack.enter_context(patch.object(http.client, "HTTPConnection", side_effect=AssertionError("real HTTP connection")))
        stack.enter_context(patch.object(http.client, "HTTPSConnection", side_effect=AssertionError("real HTTPS connection")))
        stack.enter_context(patch.object(gate.socketio, "Client", side_effect=AssertionError("real Socket.IO client")))
        stack.enter_context(patch.object(os, "kill", side_effect=AssertionError("real process signal")))
        stack.enter_context(patch.object(os, "killpg", side_effect=AssertionError("real process-group signal")))
        stack.enter_context(patch.object(socket, "getaddrinfo", side_effect=AssertionError("real DNS lookup")))
        yield


class N3LiveLifecycleGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self) -> None:
        self.tripwires = network_process_tripwires()
        self.tripwires.__enter__()
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH_ROOT)
        self.root = Path(self.temp.name)
        self.state_base = self._make_short_state_base()
        self.addCleanup(self._cleanup_state_base)
        protected_root = self.root / "profile-state-protected"
        self.profile_root_patch = patch.object(
            profile_state_module, "_REPOSITORY_ROOT", protected_root
        )
        self.install_root_patch = patch.object(
            profile_state_module, "_INSTALL_ROOT", protected_root
        )
        self.profile_root_patch.start()
        self.install_root_patch.start()
        self.addCleanup(self.install_root_patch.stop)
        self.addCleanup(self.profile_root_patch.stop)
        self.run_id = TEST_RUN_ID
        self._owned_context_counter = 0
        self.report_argument = (
            gate.EVIDENCE_BASE / self.run_id / "preflight" / "preflight.json"
        ).as_posix()
        self.sha = TEST_SHA
        self.booking_id = TEST_BOOKING
        self.common_dir = self.root / ".git"
        self.common_dir.mkdir()
        self.identity = preflight_gate.WorkspaceIdentity(
            git_sha=self.sha,
            worktree_clean=True,
            platform_key="darwin-arm64",
            git_common_dir=self.common_dir,
            source_files_sha256="1" * 64,
            dependency_lock_sha256="2" * 64,
            route_contract_sha256="3" * 64,
            identity_freeze_sha256="4" * 64,
        )
        self.ports = FakePortInspector()
        self._prepare_python()
        self._prepare_sandbox()
        self._prepare_companion()
        self._prepare_run_root()
        self.write_preflight()
        self.write_lock()
        self.fake_host: FakeHost | None = None
        self.fake_api = FakeApi()
        self.host_factory_calls = 0
        self.pass_registry = {
            row.row_id: PassingExecutor() for row in gate.LIVE_ROWS
        }
        self.dependencies = self.make_dependencies()
        self.arguments = gate.RunArguments(
            run_id=self.run_id,
            sha=self.sha,
            booking_id=self.booking_id,
            preflight_report=self.report_argument,
            party_size=1,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.tripwires.__exit__(None, None, None)

    def _make_short_state_base(self) -> Path:
        scratch = gate.REPO_ROOT / "tmp"
        for suffix in "0123456789abcdef":
            candidate = scratch / ("s" + suffix)
            try:
                candidate.mkdir(mode=0o700)
            except FileExistsError:
                continue
            return candidate
        raise AssertionError("could not allocate an isolated short state base")

    def _cleanup_state_base(self) -> None:
        if self.state_base.exists() and not self.state_base.is_symlink():
            shutil.rmtree(self.state_base)

    def _prepare_python(self) -> None:
        python = self.root / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="ascii")

    def _prepare_sandbox(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        (sandbox / "web" / "frontend").mkdir(parents=True)
        (sandbox / "web" / "web_interface.py").write_text(
            "# isolated web server\n", encoding="ascii"
        )
        (sandbox / "run_web.py").write_text("# isolated host\n", encoding="ascii")
        (sandbox / "config.py").write_text("WEB_PORT = 8360\n", encoding="ascii")
        (sandbox / "web" / "frontend" / "index.html").write_text("", encoding="ascii")

    def _prepare_companion(self) -> None:
        self._write_companion_install(self.root / gate.CAPTURE_RELATIVE)

    def _write_companion_install(self, install_root: Path) -> Path:
        content = b"fake pinned companion"
        companion = (
            install_root
            / "runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel"
        )
        companion.parent.mkdir(parents=True)
        companion.write_bytes(content)
        companion.chmod(0o700)
        manifest = companion.parent.parent / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": "neq.opentunnel.runtime_manifest.v1",
                    "version": "0.6.2",
                    "platforms": {
                        "darwin-arm64": {
                            "asset_stem": "opentunnel-darwin-arm64",
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="ascii",
        )
        manifest.chmod(0o644)
        return companion

    def make_row_context(
        self,
        *,
        run_id: str | None = None,
        api: object | None = None,
        public_service: FakePublicService | None = None,
        ports: MappedPortInspector | None = None,
        process_table: FakeProcessTable | None = None,
        process_identity_probe=None,
        signal_process=None,
        identity_observer_factory=None,
        monotonic=None,
        sleep=None,
    ) -> gate.RowContext:
        service = public_service or FakePublicService()
        factory = lambda: gate.PublicUrlClient(
            requester=service.request,
            socket_factory=service.socket_factory,
            timeout_seconds=0.1,
        )

        def unexpected_signal(*_args: object) -> None:
            raise AssertionError("executor attempted an uninjected process signal")

        selected_run_id = self.run_id if run_id is None else run_id
        run_root = self.root / gate.EVIDENCE_BASE / selected_run_id
        run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        capture_dir = run_root / "executor-capture"
        capture_dir.mkdir(exist_ok=True)
        port_inspector = ports or MappedPortInspector(
            {
                gate.HOST_PORT: preflight_gate.PortObservation(
                    gate.HOST_PORT, "occupied", (444,)
                ),
                gate.PLAYER_PORT: preflight_gate.PortObservation(
                    gate.PLAYER_PORT, "free"
                ),
            }
        )
        selected_api = api or LifecycleFakeApi()
        return gate.RowContext(
            selected_run_id,
            self.root,
            run_root,
            capture_dir,
            self.root / gate.CAPTURE_RELATIVE,
            selected_api,
            SimpleNamespace(
                owner_pid=444,
                state_root=self.state_root_for(selected_run_id),
            ),
            self.root / gate.CAPTURE_RELATIVE,
            public_client=factory(),
            public_client_factory=factory,
            process_table=process_table or FakeProcessTable(()),
            process_identity_probe=process_identity_probe or (lambda _pid: None),
            signal_process=signal_process or unexpected_signal,
            port_inspector=port_inspector,
            companion_path=(
                self.root
                / gate.CAPTURE_RELATIVE
                / "runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel"
            ),
            identity_observer_factory=(
                identity_observer_factory
                or (lambda _layout, _path: FakeIdentityObserver())
            ),
            monotonic=monotonic or (lambda: 1000.0),
            sleep=sleep or (lambda _seconds: None),
        )

    def prepare_public_client(
        self,
        context: gate.RowContext,
        service: FakePublicService,
        *,
        credential: str | None = None,
        connect_socket: bool = False,
    ) -> gate.PublicPlayerSession:
        client = context.public_client
        client.bind_invitation(service.accepted_origin)
        challenge_response, challenge = client.login_challenge()
        if challenge_response.status != 200 or challenge is None:
            raise AssertionError("fake public challenge setup failed")
        selected_credential = service.credential if credential is None else credential
        if not isinstance(selected_credential, str):
            raise AssertionError("fake public credential setup failed")
        login_response, session = client.login(challenge, selected_credential)
        if login_response.status != 200 or session is None:
            raise AssertionError("fake public session setup failed")
        snapshot = gate._decode_player_snapshot(client.authenticated_snapshot(session))
        if snapshot is None:
            raise AssertionError("fake public snapshot setup failed")
        if connect_socket and not client.connect_player_socket(session, snapshot):
            raise AssertionError("fake public socket setup failed")
        for secret in (
            selected_credential,
            challenge.csrf_nonce,
            challenge.prelogin_cookie,
            session.cookie,
            session.csrf_token,
            service.accepted_origin,
        ):
            context.remember_secret(secret)
        return session

    def make_owned_lifecycle_context(
        self,
        service: FakePublicService,
        *,
        initial_status: Mapping[str, object] | None = None,
        companion_runner=None,
    ) -> tuple[gate.RowContext, LifecycleFakeApi, object, object]:
        self._owned_context_counter += 1
        context_run_id = "%s-%d" % (self.run_id, self._owned_context_counter)
        context = self.make_row_context(
            run_id=context_run_id, public_service=service
        )
        companion = context.companion_path
        assert companion is not None
        context.companion_sha256 = hashlib.sha256(companion.read_bytes()).hexdigest()
        state_root = self.state_root_for(context.run_id)
        state_parent_created = gate._create_private_state_tree(state_root)
        install_path = Path(os.path.abspath(os.fspath(context.sandbox_root)))
        install_marker = "neq-" + hashlib.sha256(
            os.fsencode(install_path)
        ).hexdigest()[:32]
        profile_state = prepare_profile(
            state_root,
            install_marker=install_marker,
            profile=gate.DEFAULT_PROFILE,
            create=True,
        )
        if profile_state.layout is None:
            raise AssertionError("fake OpenTunnel profile setup failed")
        layout = profile_state.layout
        context.host = None

        class MutablePorts:
            def __init__(self) -> None:
                self.host_pid: int | None = 445
                self.player_pid: int | None = None
                self.unknown: set[int] = set()

            def inspect(self, port: int) -> preflight_gate.PortObservation:
                if port in self.unknown:
                    return preflight_gate.PortObservation(port, "unknown")
                pid = self.host_pid if port == gate.HOST_PORT else self.player_pid
                if pid is None:
                    return preflight_gate.PortObservation(port, "free")
                return preflight_gate.PortObservation(port, "occupied", (pid,))

        class MutableTable:
            def __init__(self) -> None:
                self.records: tuple[gate.ProcessRecord, ...] = ()

            def snapshot(self) -> tuple[gate.ProcessRecord, ...]:
                return self.records

        class OwnedProcess:
            def __init__(self, pid: int) -> None:
                self.pid = pid
                self.returncode: int | None = None

            def poll(self) -> int | None:
                return self.returncode

        ports = MutablePorts()
        table = MutableTable()
        identity_map: dict[int, object] = {}
        host_started = datetime(2026, 11, 11, 11, 0, 0)

        def host_record(
            pid: int, token: str, started_at: datetime
        ) -> gate.ProcessRecord:
            python = str(self.root / ".venv" / "bin" / "python")
            argv = (python, "-c", "import run_web; run_web.main()")
            command = shlex.join(argv)
            record = gate.ProcessRecord(
                pid, 1, os.getuid(), started_at, token, command
            )
            identity_map[pid] = SimpleNamespace(
                pid=pid,
                creation_token=token,
                executable_path=python,
                argv=argv,
                command_line=command,
            )
            return record

        def server_record(
            pid: int, parent_pid: int, token: str, started_at: datetime
        ) -> gate.ProcessRecord:
            python = str(self.root / ".venv" / "bin" / "python")
            script = str(context.sandbox_root / "web" / "web_interface.py")
            argv = (python, script)
            command = shlex.join(argv)
            record = gate.ProcessRecord(
                pid, parent_pid, os.getuid(), started_at, token, command
            )
            identity_map[pid] = SimpleNamespace(
                pid=pid,
                creation_token=token,
                executable_path=python,
                argv=argv,
                command_line=command,
            )
            return record

        def companion_record(pid: int, parent_pid: int) -> gate.ProcessRecord:
            token = "child-token-%d" % pid
            started = datetime(2026, 11, 11, 11, 1, 0)
            record = gate.ProcessRecord(
                pid,
                parent_pid,
                os.getuid(),
                started,
                token,
                shlex.join(
                    [str(companion), "serve", "--profile", gate.DEFAULT_PROFILE]
                ),
            )
            identity_map[pid] = SimpleNamespace(
                pid=pid,
                creation_token=token,
                executable_path=str(companion),
                argv=(str(companion), "serve", "--profile", gate.DEFAULT_PROFILE),
                command_line=record.command,
            )
            return record

        class OwnedHost:
            def __init__(self) -> None:
                self.state_root = state_root
                self._state_root_identity = gate._private_state_tree_identity(
                    state_root
                )
                self._state_parent_identity = gate._private_state_parent_identity(
                    state_root.parent
                )
                self._state_parent_created = state_parent_created
                self.environment = gate.build_host_environment(
                    context.sandbox_root, state_root, context.run_id
                )
                self.process_generation = 1
                self.owned_pids = [444, 445]
                self.listener_pids = [445]
                ports.host_pid = 445
                self.process: OwnedProcess | None = OwnedProcess(444)
                self._server_pid: int | None = 445
                self._next_launcher_pid = 446
                self._next_server_pid = 447
                self.on_stop = None
                self.on_restart = None
                self._refresh_processes(False)

            @property
            def owner_pid(self) -> int | None:
                return None if self.process is None else self._server_pid

            @property
            def launcher_pid(self) -> int | None:
                return None if self.process is None else self.process.pid

            def _getpgid(self, pid: int) -> int:
                if pid == self.owner_pid and self.launcher_pid is not None:
                    return self.launcher_pid
                if pid == self.launcher_pid and self.launcher_pid is not None:
                    return self.launcher_pid
                return -1

            def _refresh_processes(self, with_companion: bool) -> None:
                process = self.process
                if process is None:
                    table.records = ()
                    return
                start = host_record(
                    process.pid,
                    "host-token-%d" % process.pid,
                    host_started + timedelta(seconds=self.process_generation),
                )
                server_pid = self._server_pid
                if server_pid is None:
                    raise AssertionError("fake server process is missing")
                server = server_record(
                    server_pid,
                    process.pid,
                    "server-token-%d" % server_pid,
                    host_started + timedelta(seconds=self.process_generation),
                )
                if with_companion:
                    table.records = (start, server, companion_record(555, server_pid))
                    record = OwnedProcessRecord(
                        profile=gate.DEFAULT_PROFILE,
                        uid=os.getuid(),
                        pid=555,
                        creation_token="child-token-555",
                        exe_path=str(companion.resolve()),
                        started_at="2026-11-11T11:01:00Z",
                        generation=self.process_generation,
                        route_id="gate-route",
                    )
                    if not write_owner_record(layout, record):
                        raise AssertionError("fake companion owner record setup failed")
                else:
                    table.records = (start, server)

            def stop(self) -> bool:
                if self.process is not None:
                    self.process.returncode = 0
                self.process = None
                self._server_pid = None
                ports.host_pid = None
                ports.player_pid = None
                self._refresh_processes(False)
                service.stop_sharing()
                owner_record = layout.state_home / "owned_process.json"
                if owner_record.exists():
                    owner_record.unlink()
                if callable(self.on_stop):
                    self.on_stop()
                return True

            def start(self) -> bool:
                process = OwnedProcess(self._next_launcher_pid)
                self._server_pid = self._next_server_pid
                self._next_launcher_pid += 2
                self._next_server_pid += 2
                self.process = process
                self.process_generation += 1
                self.owned_pids.extend((process.pid, self._server_pid))
                self.listener_pids.append(self._server_pid)
                ports.host_pid = self._server_pid
                ports.player_pid = None
                self._refresh_processes(False)
                if callable(self.on_restart):
                    self.on_restart()
                return True

        host = OwnedHost()
        context.host = host
        context.port_inspector = ports
        context.process_table = table
        context.process_identity_probe = lambda pid: identity_map.get(pid)
        context.host_api = None

        api: LifecycleFakeApi

        def copy_invitation(_payload: Mapping[str, object]) -> gate.HostApiResponse:
            current = dict(api.status)
            if current.get("state") != "ready":
                return gate.HostApiResponse(
                    409, {"ok": False, "reason": "invitation_unavailable"}
                )
            return gate.HostApiResponse(
                200,
                {
                    "ok": True,
                    "invitation": service.accepted_origin,
                    "status": current,
                },
            )

        def start_sharing(_payload: Mapping[str, object]) -> gate.HostApiResponse:
            service.start_sharing()
            host_pid = host.owner_pid
            assert host_pid is not None
            ports.player_pid = host_pid
            host._refresh_processes(True)
            api.status = {
                "state": "ready",
                "reason": "ready",
                "identity_initialized": True,
                "identity_up_invocations": 1,
                "companion_launches": 1,
                "generation": 1,
            }
            return gate.HostApiResponse(
                200, {"ok": True, "reason": "ready", "status": api.status}
            )

        def stop_sharing(_payload: Mapping[str, object]) -> gate.HostApiResponse:
            service.stop_sharing()
            ports.player_pid = None
            host._refresh_processes(False)
            owner_record = layout.state_home / "owned_process.json"
            if owner_record.exists():
                owner_record.unlink()
            api.status = {
                **dict(api.status),
                "state": "off",
                "reason": "stopped",
            }
            return gate.HostApiResponse(
                200, {"ok": True, "reason": "stopped", "status": api.status}
            )

        def rotate(_payload: Mapping[str, object]) -> gate.HostApiResponse:
            new_credential = "credential-secret-rotated-sentinel"
            service.rotate_credential(new_credential)
            api.status = {
                **dict(api.status),
                "state": "ready",
                "reason": "ready",
            }
            return gate.HostApiResponse(
                200,
                {
                    "ok": True,
                    "reason": "credential_rotated",
                    "credential": new_credential,
                    "status": api.status,
                },
            )

        def revoke(_payload: Mapping[str, object]) -> gate.HostApiResponse:
            service.revoke_access()
            ports.player_pid = None
            host._refresh_processes(False)
            owner_record = layout.state_home / "owned_process.json"
            if owner_record.exists():
                owner_record.unlink()
            api.status = {
                **dict(api.status),
                "state": "off",
                "reason": "stopped",
            }
            return gate.HostApiResponse(
                200,
                {"ok": True, "reason": "access_revoked", "status": api.status},
            )

        api = LifecycleFakeApi(
            status=initial_status
            or {
                "state": "off",
                "reason": "off",
                "identity_initialized": True,
                "identity_up_invocations": 1,
                "companion_launches": 0,
            },
            post_handlers={
                "start": start_sharing,
                "stop": stop_sharing,
                "copy-invitation": copy_invitation,
                "rotate": rotate,
                "revoke": revoke,
            },
        )
        host.on_stop = lambda: setattr(
            api,
            "status",
            {
                **dict(api.status),
                "state": "off",
                "reason": "shutting_down",
                "companion_launches": 0,
            },
        )
        host.on_restart = lambda: setattr(
            api,
            "status",
            {
                **dict(api.status),
                "state": "off",
                "reason": "off",
                "identity_initialized": True,
                "identity_up_invocations": 1,
                "companion_launches": 0,
                "generation": 0,
            },
        )
        context.host_api = api
        if companion_runner is not None:
            context.companion_runner = companion_runner
        return context, api, ports, table

    def companion_process_fixture(
        self, *, mismatch_child_token: bool = False
    ) -> tuple[tuple[gate.ProcessRecord, ...], dict[int, object]]:
        companion = (
            self.root
            / gate.CAPTURE_RELATIVE
            / "runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel"
        )
        uid = os.getuid()
        host_started = datetime(2026, 11, 11, 11, 0, 0)
        child_started = datetime(2026, 11, 11, 11, 1, 0)
        host_token = "host-created-20261111-110000"
        child_token = "child-created-20261111-110000"
        launcher_record = gate.ProcessRecord(
            444,
            1,
            uid,
            host_started,
            host_token,
            "python run_web.main()",
        )
        python = str(self.root / ".venv" / "bin" / "python")
        server_script = str(
            self.root / gate.CAPTURE_RELATIVE / "web" / "web_interface.py"
        )
        server_token = "server-created-20261111-110010"
        server_record = gate.ProcessRecord(
            445,
            444,
            uid,
            host_started + timedelta(seconds=10),
            server_token,
            shlex.join([python, server_script]),
        )
        child_record = gate.ProcessRecord(
            555,
            445,
            uid,
            child_started,
            child_token,
            shlex.join(
                [str(companion), "serve", "--profile", gate.DEFAULT_PROFILE]
            ),
        )
        child_identity_token = "different-child-token" if mismatch_child_token else child_token
        identities = {
            444: SimpleNamespace(
                pid=444,
                creation_token=host_token,
                executable_path=python,
                argv=(python, "-c", "import run_web; run_web.main()"),
                command_line="python run_web.main()",
            ),
            445: SimpleNamespace(
                pid=445,
                creation_token=server_token,
                executable_path=python,
                argv=(python, server_script),
                command_line=server_record.command,
            ),
            555: SimpleNamespace(
                pid=555,
                creation_token=child_identity_token,
                executable_path=str(companion),
                argv=(
                    str(companion),
                    "serve",
                    "--profile",
                    gate.DEFAULT_PROFILE,
                ),
                command_line=shlex.join(
                    [str(companion), "serve", "--profile", gate.DEFAULT_PROFILE]
                ),
            ),
        }
        return (launcher_record, server_record, child_record), identities

    def make_l05_context(
        self, *, origin_changed: bool = False, mismatch_child_token: bool = False
    ) -> tuple[gate.RowContext, FakePublicService, list[tuple[int, int]]]:
        old_origin = "https://neq-share.account.opentunnel.xyz"
        new_origin = "https://neq-share-next.account.opentunnel.xyz"
        service = FakePublicService(old_origin)
        records, identities = self.companion_process_fixture(
            mismatch_child_token=mismatch_child_token
        )
        context = self.make_row_context(public_service=service)
        context.host = SimpleNamespace(
            owner_pid=445,
            launcher_pid=444,
            owned_pids=[444, 445],
            _getpgid=lambda _pid: 444,
        )
        signal_calls: list[tuple[int, int]] = []

        def on_status(status: Mapping[str, object], count: int) -> None:
            if count == 3 and status.get("state") == "ready":
                if origin_changed:
                    service.accepted_origin = new_origin
                service.set_available(True)

        api = LifecycleFakeApi(
            status_sequence=[
                {
                    "state": "ready",
                    "reason": "ready",
                    "generation": 1,
                    "companion_launches": 1,
                },
                {
                    "state": "degraded",
                    "reason": "relay_unavailable",
                    "generation": 1,
                    "companion_launches": 1,
                },
                {
                    "state": "ready",
                    "reason": "ready",
                    "generation": 1,
                    "companion_launches": 2,
                },
                {
                    "state": "ready",
                    "reason": "ready",
                    "generation": 1,
                    "companion_launches": 2,
                },
            ],
            on_status=on_status,
            post_handlers={
                "copy-invitation": lambda _payload: (
                    gate.HostApiResponse(
                        409,
                        {"ok": False, "reason": "invitation_unavailable"},
                    )
                    if sum(
                        1
                        for method, request in api.calls
                        if method == "POST"
                        and isinstance(request, tuple)
                        and request[0] == "copy-invitation"
                    )
                    == 1
                    else gate.HostApiResponse(
                        200,
                        {
                            "ok": True,
                            "invitation": service.accepted_origin,
                            "status": {
                                "state": "ready",
                                "reason": "ready",
                                "generation": 1,
                                "companion_launches": 2,
                            },
                        },
                    )
                )
            },
        )
        # The callback closes over the API for the copy-invitation call counter.
        client_factory = lambda: gate.PublicUrlClient(
            requester=service.request,
            socket_factory=service.socket_factory,
            timeout_seconds=0.1,
        )
        client = client_factory()
        client.bind_invitation(old_origin)
        challenge_response, challenge = client.login_challenge()
        if challenge_response.status != 200 or challenge is None:
            raise AssertionError("fake public login challenge invalid")
        login_response, session = client.login(challenge, service.credential)
        if login_response.status != 200 or session is None:
            raise AssertionError("fake public login failed")
        snapshot = gate._decode_player_snapshot(client.authenticated_snapshot(session))
        if snapshot is None or not client.connect_player_socket(session, snapshot):
            raise AssertionError("fake public socket setup failed")

        def signal_process(pid: int, selected_signal: int) -> None:
            signal_calls.append((pid, selected_signal))
            service.set_available(False)

        ports = MappedPortInspector(
            {
                gate.HOST_PORT: preflight_gate.PortObservation(
                    gate.HOST_PORT, "occupied", (445,)
                ),
                gate.PLAYER_PORT: preflight_gate.PortObservation(
                    gate.PLAYER_PORT, "occupied", (445,)
                ),
            }
        )
        context.host_api = api
        context.public_client = client
        context.public_client_factory = client_factory
        context.process_table = FakeProcessTable(records)
        context.process_identity_probe = lambda pid: identities.get(pid)
        context.signal_process = signal_process
        context.port_inspector = ports
        context.remember_secret(service.credential)
        context.remember_secret(session.cookie)
        context.remember_secret(session.csrf_token)
        return context, service, signal_calls

    def _prepare_run_root(self) -> None:
        (self.root / gate.EVIDENCE_BASE / self.run_id / "preflight").mkdir(
            parents=True
        )

    def state_root_for(self, run_id: str) -> Path:
        return self.state_base / "neq-n3g" / gate._state_root_id8(run_id)

    def write_preflight(self, document: Mapping[str, object] | None = None) -> Path:
        path = self.root / self.report_argument
        payload = {
            "schema_version": 1,
            "gate": "N3-provider-free-preflight",
            "run_id": self.run_id,
            "preflight_mode": "provider-free",
            "preflight_verdict": "READY_FOR_PRIMARY_REVIEW",
            "gate_verdict": "PENDING",
            "is_gate_pass": False,
            "identity": {
                "git_sha": self.sha,
                "worktree": "clean",
                "platform": "darwin-arm64",
                "source_files_sha256": self.identity.source_files_sha256,
                "dependency_lock_sha256": self.identity.dependency_lock_sha256,
                "route_contract_sha256": self.identity.route_contract_sha256,
                "identity_freeze_sha256": self.identity.identity_freeze_sha256,
            },
            "invocation": {
                "command": [
                    "/usr/bin/python3",
                    "scripts/n3_lifecycle_gate.py",
                    "preflight",
                    "--run-id",
                    self.run_id,
                ],
                "cwd": str(self.root),
                "pythonpath": ".",
                "expected_sha": self.sha,
            },
            "manifest": {
                "sha256": preflight_gate.SCENARIO_MANIFEST_SHA256,
                "row_ids": [row.row_id for row in preflight_gate.SCENARIO_ROWS],
                "frozen_caps": preflight_gate.asdict(preflight_gate.FROZEN_CAPS),
                "approved_platforms": list(preflight_gate.APPROVED_PLATFORMS),
            },
            "caps_match_manifest": True,
            "effective_caps": preflight_gate.asdict(preflight_gate.FROZEN_CAPS),
            "row_coverage_complete": True,
            "rows": [
                {
                    "row_id": row.row_id,
                    "expected": row.expected,
                    "observed": {"ok": True},
                    "elapsed_seconds": 0.1,
                    "verdict": "PASS",
                }
                for row in preflight_gate.SCENARIO_ROWS
            ],
            "attempts": len(preflight_gate.SCENARIO_ROWS),
            "ports": {"host": gate.HOST_PORT, "player": gate.PLAYER_PORT},
            "teardown": {
                "service_stopped": True,
                "host_stopped": True,
                "capture_copy_removed": True,
                "ports_free": True,
                "lock_released": True,
                "complete": True,
            },
            "fault_checks": {
                key: {"passed": True}
                for key in (
                    "missing_row_fail_fast",
                    "attempt_cap_fail_fast",
                    "time_cap_fail_fast",
                    "teardown_failure_retains_lock",
                )
            },
            "providers_called": 0,
            "relay_connections": 0,
            "provider_attempt_budget_used": 0,
            "relay_attempt_budget_used": 0,
            "infrastructure_failures": [],
            "semantic_failures": [],
        }
        if document is not None:
            payload = dict(document)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def lock_record(self) -> dict[str, object]:
        return {
            "booking_id": self.booking_id,
            "holder": "N agent-run",
            "gate": "N3-live",
            "authorizing_ruling": "approved-n3-booking-ruling",
            "window_start": (TEST_NOW - timedelta(minutes=30)).isoformat(),
            "window_end": (TEST_NOW + timedelta(minutes=30)).isoformat(),
            "run_id": self.run_id,
            "evidence": (gate.EVIDENCE_BASE / self.run_id / "capture").as_posix(),
            "preflight_report": self.report_argument,
            "head": self.sha,
            "frozen_caps": {
                "party_size": 1,
                "platform": "macos-arm64",
                "provider_dispatch_attempts": 0,
                "max_tunnel_creations": 2,
                "max_companion_launches": 4,
                "window_hours": 1,
            },
        }

    def write_lock(self, record: Mapping[str, object] | None = None) -> Path:
        lock = self.common_dir / "neq-coordination" / "live-window.lock"
        lock.mkdir(parents=True, exist_ok=True)
        holder = lock / "holder.json"
        holder.write_text(
            json.dumps(dict(record or self.lock_record()), separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        return lock

    def make_dependencies(
        self,
        *,
        identity: preflight_gate.WorkspaceIdentity | None = None,
        ports: FakePortInspector | None = None,
        executors: Mapping[str, gate.RowExecutor] | None = None,
        api: FakeApi | None = None,
        companion_error: str | None = None,
        sandbox_error: str | None = None,
        state_base_provider=None,
    ) -> gate.LiveGateDependencies:
        selected_ports = ports or self.ports
        selected_api = api or self.fake_api

        def make_host(
            root: Path, sandbox: Path, state_root: Path, run_id: str
        ) -> FakeHost:
            self.host_factory_calls += 1
            self.fake_host = FakeHost(
                root, sandbox, state_root, run_id, selected_ports
            )
            return self.fake_host

        def check_companion(
            companion_install_root: Path, platform_key: str
        ) -> Mapping[str, object]:
            if companion_error:
                raise gate.GateError(companion_error)
            return gate.verify_installed_companion(
                companion_install_root, platform_key
            )

        def check_sandbox(root: Path) -> Path:
            if sandbox_error:
                raise gate.GateError(sandbox_error)
            return gate.validate_prepared_sandbox(root)

        return gate.LiveGateDependencies(
            root=self.root,
            identity_reader=lambda _root: identity or self.identity,
            port_inspector=selected_ports,
            preflight_reader=gate.load_preflight_report,
            companion_verifier=check_companion,
            sandbox_validator=check_sandbox,
            host_factory=make_host,
            api_factory=lambda: selected_api,
            state_base_provider=state_base_provider or (lambda: self.state_base),
            executor_registry=(
                self.pass_registry if executors is None else executors
            ),
            monotonic=lambda: 1000.0,
            utc_now=lambda: TEST_NOW,
        )

    def test_l01_passes_both_inactive_states_and_fails_on_exposure(self) -> None:
        for state in ("off", "initializing_required"):
            with self.subTest(state=state):
                context = self.make_row_context(
                    api=LifecycleFakeApi(
                        status={
                            "state": state,
                            "reason": state,
                            "identity_initialized": False,
                        }
                    )
                )
                result = gate.L01SharingOffExecutor().execute(context)
                self.assertEqual(result.verdict, "PASS")
                self.assertEqual(result.observed["sharing_state"], state)

        listener_ports = MappedPortInspector(
            {
                gate.PLAYER_PORT: preflight_gate.PortObservation(
                    gate.PLAYER_PORT, "occupied", (999,)
                )
            }
        )
        listener = gate.L01SharingOffExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off", "identity_initialized": False}
                ),
                ports=listener_ports,
            )
        )
        self.assertEqual(listener.verdict, "FAIL")
        self.assertEqual(listener.reason, "unexpected_player_listener")

        records, _identities = self.companion_process_fixture()
        companion = gate.L01SharingOffExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off", "identity_initialized": False}
                ),
                process_table=FakeProcessTable(records),
            )
        )
        self.assertEqual(companion.verdict, "FAIL")
        self.assertEqual(companion.reason, "unexpected_companion_process")

        companion_record = records[1]
        companion_path = (
            self.root
            / gate.CAPTURE_RELATIVE
            / "runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel"
        )
        other_profile_process = gate.ProcessRecord(
            companion_record.pid,
            companion_record.parent_pid,
            companion_record.uid,
            companion_record.started_at,
            companion_record.creation_token,
            shlex.join(
                [
                    str(companion_path),
                    "serve",
                    "--profile",
                    "unrelated-profile",
                ]
            ),
        )
        other_profile = gate.L01SharingOffExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off", "identity_initialized": False}
                ),
                process_table=FakeProcessTable((other_profile_process,)),
            )
        )
        self.assertEqual(other_profile.verdict, "FAIL")
        self.assertEqual(other_profile.reason, "unexpected_companion_process")

        unobservable = gate.L01SharingOffExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off", "identity_initialized": False}
                ),
                ports=MappedPortInspector({}),
            )
        )
        self.assertEqual(unobservable.verdict, "BLOCKED")
        self.assertEqual(
            unobservable.reason, "player_listener_observation_unavailable"
        )

        def execute_public_probe(response: gate.HostApiResponse) -> gate.RowExecutionResult:
            context = self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off", "identity_initialized": False},
                    post_handlers={"copy-invitation": lambda _payload: response},
                )
            )
            return gate.L01SharingOffExecutor().execute(context)

        exposed = execute_public_probe(
            gate.HostApiResponse(
                200,
                {
                    "ok": True,
                    "invitation": "https://neq-share.account.opentunnel.xyz",
                },
            )
        )
        self.assertEqual(exposed.verdict, "FAIL")
        self.assertEqual(exposed.reason, "unexpected_public_exposure")
        unavailable_public_observation = execute_public_probe(
            gate.HostApiResponse(503, {"ok": False, "reason": "service_unavailable"})
        )
        self.assertEqual(unavailable_public_observation.verdict, "BLOCKED")
        self.assertEqual(
            unavailable_public_observation.reason,
            "public_exposure_observation_unavailable",
        )

    def test_companion_process_identification_uses_capture_copy_path(self) -> None:
        context = self.make_row_context()
        records, _identities = self.companion_process_fixture()
        capture_companion = gate._companion_path(context)
        repository_companion = self._write_companion_install(self.root)
        repository_record = gate.ProcessRecord(
            556,
            444,
            os.getuid(),
            datetime(2026, 11, 11, 11, 2, 0),
            "repository-copy-child",
            shlex.join(
                [
                    str(repository_companion),
                    "serve",
                    "--profile",
                    gate.DEFAULT_PROFILE,
                ]
            ),
        )

        matches = gate._matching_companion_processes(
            (*records, repository_record),
            capture_companion,
            gate.DEFAULT_PROFILE,
        )

        expected_capture_path = (
            context.companion_install_root
            / "runtime/opentunnel/v0.6.2/opentunnel-darwin-arm64/opentunnel"
        )
        self.assertEqual(capture_companion, expected_capture_path)
        self.assertEqual(matches, (records[2],))

    def test_l02_initializes_once_checks_projection_and_cleanup(self) -> None:
        initial = {
            "state": "initializing_required",
            "reason": "initializing_required",
            "identity_initialized": False,
            "identity_up_invocations": 0,
        }
        initialized = {
            "state": "off",
            "reason": "off",
            "identity_initialized": True,
            "identity_up_invocations": 1,
        }
        init_calls = 0

        def initialize(payload: Mapping[str, object]) -> gate.HostApiResponse:
            nonlocal init_calls
            init_calls += 1
            self.assertEqual(dict(payload), {"confirm": True})
            return gate.HostApiResponse(
                200,
                {
                    "ok": True,
                    "reason": "identity_initialized",
                    "status": initialized,
                },
            )

        context_for_profile = self.make_row_context(api=LifecycleFakeApi(status=initial))
        profile_calls: list[tuple[Path, Mapping[str, object]]] = []

        def fake_prepare_profile(path: Path, **kwargs: object) -> object:
            profile_calls.append((path, kwargs))
            return SimpleNamespace(state="ready", layout=object())

        with patch.object(gate, "prepare_profile", side_effect=fake_prepare_profile):
            self.assertIsNotNone(gate._gate_profile_layout(context_for_profile))
        self.assertEqual(
            profile_calls[0][0],
            context_for_profile.host.state_root,
        )

        def execute(observer: FakeIdentityObserver) -> gate.RowExecutionResult:
            context = self.make_row_context(
                api=LifecycleFakeApi(
                    status=initial,
                    post_handlers={"initialize-identity": initialize},
                ),
                identity_observer_factory=lambda _layout, _path: observer,
            )
            with patch.object(
                gate,
                "prepare_profile",
                return_value=SimpleNamespace(state="ready", layout=object()),
            ):
                return gate.L02IdentityInitExecutor().execute(context)

        result = execute(FakeIdentityObserver())
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(init_calls, 2)
        self.assertEqual(result.observed["identity_up_invocations"], 1)
        self.assertTrue(
            all(item["state"] == "absent" for item in result.observed["postchecks"])
        )
        residual = execute(FakeIdentityObserver("present"))
        self.assertEqual(residual.verdict, "FAIL")
        self.assertEqual(residual.reason, "identity_residual_resource_found")
        unknown = execute(FakeIdentityObserver("unknown"))
        self.assertEqual(unknown.verdict, "BLOCKED")
        self.assertEqual(unknown.reason, "identity_postcheck_unavailable")

        invalid_counter = gate.L02IdentityInitExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={**initial, "identity_up_invocations": True}
                )
            )
        )
        self.assertEqual(invalid_counter.verdict, "FAIL")

    def test_l03_public_access_boundary_uses_only_injected_fakes(self) -> None:
        service = FakePublicService()
        ready = {
            "state": "ready",
            "reason": "ready",
            "generation": 1,
            "companion_launches": 1,
        }
        api = LifecycleFakeApi(
            status={"state": "off", "reason": "off"},
            post_handlers={
                "issue-access": lambda _payload: gate.HostApiResponse(
                    200, {"ok": True, "credential": service.credential}
                ),
                "start": lambda _payload: gate.HostApiResponse(
                    200, {"ok": True, "reason": "ready", "status": ready}
                ),
                "copy-invitation": lambda _payload: gate.HostApiResponse(
                    200,
                    {
                        "ok": True,
                        "invitation": service.accepted_origin,
                        "status": ready,
                    },
                ),
            },
        )
        context = self.make_row_context(api=api, public_service=service)
        result = gate.L03PublicAccessExecutor().execute(context)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(result.observed["unauthenticated_snapshot_data_free"])
        self.assertEqual(result.observed["unauthenticated_snapshot_status"], 404)
        self.assertTrue(result.observed["authenticated_socket_snapshot_valid"])
        self.assertTrue(result.observed["host_socket_namespace_refused"])
        self.assertNotIn(service.credential, repr(result))
        self.assertNotIn(service.accepted_origin, repr(result))
        self.assertIn(service.credential, context.secrets)

        exposed_service = FakePublicService()
        exposed_service.overrides[("POST", "/api/player-sharing/start")] = (
            FakePublicService._json(200, {"state": "ready"})
        )
        exposed = gate.L03PublicAccessExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off"},
                    post_handlers={
                        "issue-access": lambda _payload: gate.HostApiResponse(
                            200,
                            {"ok": True, "credential": exposed_service.credential},
                        ),
                        "start": lambda _payload: gate.HostApiResponse(
                            200, {"ok": True, "reason": "ready", "status": ready}
                        ),
                        "copy-invitation": lambda _payload: gate.HostApiResponse(
                            200,
                            {
                                "ok": True,
                                "invitation": exposed_service.accepted_origin,
                            },
                        ),
                    },
                ),
                public_service=exposed_service,
            )
        )
        self.assertEqual(exposed.verdict, "FAIL")
        self.assertEqual(exposed.reason, "public_host_route_exposed")

        data_service = FakePublicService()
        data_service.overrides[("GET", "/api/player/snapshot")] = (
            FakePublicService._json(403, {"error": "not_found", "party": {"name": "secret"}})
        )
        data_exposure = gate.L03PublicAccessExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off"},
                    post_handlers={
                        "issue-access": lambda _payload: gate.HostApiResponse(
                            200, {"ok": True, "credential": data_service.credential}
                        ),
                        "start": lambda _payload: gate.HostApiResponse(
                            200, {"ok": True, "reason": "ready", "status": ready}
                        ),
                        "copy-invitation": lambda _payload: gate.HostApiResponse(
                            200,
                            {"ok": True, "invitation": data_service.accepted_origin},
                        ),
                    },
                ),
                public_service=data_service,
            )
        )
        self.assertEqual(data_exposure.verdict, "FAIL")
        self.assertEqual(
            data_exposure.reason, "unauthenticated_snapshot_boundary_failed"
        )

        unavailable_service = FakePublicService()
        unavailable_service.set_available(False)
        unavailable = gate.L03PublicAccessExecutor().execute(
            self.make_row_context(
                api=LifecycleFakeApi(
                    status={"state": "off"},
                    post_handlers={
                        "issue-access": lambda _payload: gate.HostApiResponse(
                            200,
                            {"ok": True, "credential": unavailable_service.credential},
                        ),
                        "start": lambda _payload: gate.HostApiResponse(
                            200, {"ok": True, "reason": "ready", "status": ready}
                        ),
                        "copy-invitation": lambda _payload: gate.HostApiResponse(
                            200,
                            {
                                "ok": True,
                                "invitation": unavailable_service.accepted_origin,
                            },
                        ),
                    },
                ),
                public_service=unavailable_service,
            )
        )
        self.assertEqual(unavailable.verdict, "BLOCKED")

        def execute_l03_variant(
            variant_service: FakePublicService,
        ) -> gate.RowExecutionResult:
            variant_api = LifecycleFakeApi(
                status={"state": "off", "reason": "off"},
                post_handlers={
                    "issue-access": lambda _payload: gate.HostApiResponse(
                        200,
                        {"ok": True, "credential": variant_service.credential},
                    ),
                    "start": lambda _payload: gate.HostApiResponse(
                        200, {"ok": True, "reason": "ready", "status": ready}
                    ),
                    "copy-invitation": lambda _payload: gate.HostApiResponse(
                        200,
                        {
                            "ok": True,
                            "invitation": variant_service.accepted_origin,
                        },
                    ),
                },
            )
            return gate.L03PublicAccessExecutor().execute(
                self.make_row_context(
                    api=variant_api, public_service=variant_service
                )
            )

        unauthenticated_200_service = FakePublicService()
        unauthenticated_200_service.overrides[("GET", "/api/player/snapshot")] = (
            FakePublicService._json(200, unauthenticated_200_service.snapshot)
        )
        unauthenticated_200 = execute_l03_variant(unauthenticated_200_service)
        self.assertEqual(unauthenticated_200.verdict, "FAIL")
        self.assertEqual(
            unauthenticated_200.reason,
            "unauthenticated_snapshot_boundary_failed",
        )

        exposed_socket_service = FakePublicService()
        exposed_socket_service.allow_host_namespace = True
        exposed_socket = execute_l03_variant(exposed_socket_service)
        self.assertEqual(exposed_socket.verdict, "FAIL")
        self.assertEqual(
            exposed_socket.reason, "public_host_socket_namespace_exposed"
        )

        accepted_wrong_password_service = FakePublicService()
        accepted_wrong_password_service.accept_invalid_credentials = True
        accepted_wrong_password = execute_l03_variant(
            accepted_wrong_password_service
        )
        self.assertEqual(accepted_wrong_password.verdict, "FAIL")
        self.assertEqual(accepted_wrong_password.reason, "invalid_credential_accepted")

        accepted_forged_origin_service = FakePublicService()
        accepted_forged_origin_service.accept_forged_origin = True
        accepted_forged_origin = execute_l03_variant(accepted_forged_origin_service)
        self.assertEqual(accepted_forged_origin.verdict, "FAIL")
        self.assertEqual(accepted_forged_origin.reason, "forged_origin_accepted")

        refused_socket_service = FakePublicService()
        refused_socket_service.player_namespace_refused = True
        refused_socket = execute_l03_variant(refused_socket_service)
        self.assertEqual(refused_socket.verdict, "FAIL")
        self.assertEqual(refused_socket.reason, "public_response_contract_invalid")

        insecure_cookie_service = FakePublicService()
        insecure_cookie_service.session_cookie_attributes = "HttpOnly; SameSite=Lax"
        insecure_cookie = execute_l03_variant(insecure_cookie_service)
        self.assertEqual(insecure_cookie.verdict, "FAIL")
        self.assertEqual(insecure_cookie.reason, "public_response_contract_invalid")

        missing_socket_snapshot_service = FakePublicService()
        missing_socket_snapshot_service.suppress_socket_snapshot = True
        missing_socket_snapshot = execute_l03_variant(
            missing_socket_snapshot_service
        )
        self.assertEqual(missing_socket_snapshot.verdict, "FAIL")
        self.assertEqual(
            missing_socket_snapshot.reason, "public_response_contract_invalid"
        )

    def test_public_url_client_rejects_unsafe_inputs_and_bounds_failures(self) -> None:
        service = FakePublicService()
        client = gate.PublicUrlClient(
            requester=service.request,
            socket_factory=service.socket_factory,
            timeout_seconds=0.1,
        )
        client.bind_invitation(service.accepted_origin)
        for unsafe in (
            "http://neq-share.account.opentunnel.xyz",
            "https://user@neq-share.account.opentunnel.xyz",
            "https://neq-share.account.opentunnel.xyz/path",
            "https://neq-share.account.opentunnel.xyz?query=1",
            "https://neq-share.account.opentunnel.xyz#fragment",
            "https://*.account.opentunnel.xyz",
            "https://NEQ-share.account.opentunnel.xyz",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(gate.PublicClientError):
                    client.bind_invitation(unsafe)
        with self.assertRaisesRegex(gate.PublicClientError, "public_request_invalid"):
            client.request("DELETE", "/api/player/snapshot")
        with self.assertRaisesRegex(gate.PublicClientError, "public_request_invalid"):
            client.request("GET", "/not-allowlisted")
        with self.assertRaisesRegex(
            gate.PublicClientError, "public_host_override_refused"
        ):
            client.request("GET", "/", headers={"Host": "attacker.invalid"})
        with self.assertRaisesRegex(ValueError, "public_client_timeout_invalid"):
            gate.PublicUrlClient(timeout_seconds=31)

        def timeout_requester(*_args: object) -> gate.PublicHttpResponse:
            raise TimeoutError("credential-secret-sentinel")

        timed = gate.PublicUrlClient(requester=timeout_requester, timeout_seconds=0.1)
        timed.bind_invitation(service.accepted_origin)
        with self.assertRaises(gate.PublicClientError) as raised:
            timed.request("GET", "/")
        self.assertEqual(raised.exception.reason, "public_transport_unavailable")
        self.assertNotIn("credential-secret-sentinel", str(raised.exception))

        delayed_service = FakePublicService()
        delayed_service.suppress_socket_snapshot = True
        delayed_client = gate.PublicUrlClient(
            requester=delayed_service.request,
            socket_factory=delayed_service.socket_factory,
            timeout_seconds=0.01,
        )
        delayed_client.bind_invitation(delayed_service.accepted_origin)
        _response, challenge = delayed_client.login_challenge()
        self.assertIsNotNone(challenge)
        assert challenge is not None
        _login_response, session = delayed_client.login(
            challenge, delayed_service.credential
        )
        self.assertIsNotNone(session)
        assert session is not None
        snapshot = gate._decode_player_snapshot(
            delayed_client.authenticated_snapshot(session)
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        with self.assertRaisesRegex(
            gate.PublicClientError, "public_socket_snapshot_timeout"
        ):
            delayed_client.connect_player_socket(session, snapshot)

    def test_l04_duplicate_start_checks_generation_listener_and_owned_process(self) -> None:
        ready = {
            "state": "ready",
            "reason": "ready",
            "generation": 3,
            "companion_launches": 1,
        }
        records, identities = self.companion_process_fixture()
        ports = MappedPortInspector(
            {
                gate.HOST_PORT: preflight_gate.PortObservation(
                    gate.HOST_PORT, "occupied", (445,)
                ),
                gate.PLAYER_PORT: preflight_gate.PortObservation(
                    gate.PLAYER_PORT, "occupied", (445,)
                )
            }
        )
        api = LifecycleFakeApi(
            status=ready,
            post_handlers={
                "start": lambda _payload: gate.HostApiResponse(
                    200, {"ok": True, "reason": "ready", "status": ready}
                )
            },
        )
        context = self.make_row_context(
            api=api,
            ports=ports,
            process_table=FakeProcessTable(records),
            process_identity_probe=lambda pid: identities.get(pid),
        )
        context.host = SimpleNamespace(
            owner_pid=445,
            launcher_pid=444,
            owned_pids=[444, 445],
            _getpgid=lambda _pid: 444,
        )
        result = gate.L04DuplicateStartExecutor().execute(context)
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(result.observed["companion_process_count"], 1)
        self.assertEqual(
            ports.calls,
            [gate.PLAYER_PORT, gate.HOST_PORT, gate.PLAYER_PORT, gate.HOST_PORT],
        )

        changed_api = LifecycleFakeApi(
            status=ready,
            post_handlers={
                "start": lambda _payload: gate.HostApiResponse(
                    200,
                    {
                        "ok": True,
                        "reason": "ready",
                        "status": {**ready, "generation": 4},
                    },
                )
            },
        )
        changed_context = self.make_row_context(
                api=changed_api,
                ports=ports,
                process_table=FakeProcessTable(records),
                process_identity_probe=lambda pid: identities.get(pid),
            )
        changed_context.host = SimpleNamespace(
            owner_pid=445,
            launcher_pid=444,
            owned_pids=[444, 445],
            _getpgid=lambda _pid: 444,
        )
        changed = gate.L04DuplicateStartExecutor().execute(changed_context)
        self.assertEqual(changed.verdict, "FAIL")
        self.assertEqual(changed.reason, "duplicate_start_changed_generation")

        launcher_record, server_record, child_record = records
        replacement_record = gate.ProcessRecord(
            child_record.pid,
            child_record.parent_pid,
            child_record.uid,
            child_record.started_at + timedelta(seconds=5),
            "replacement-process-creation-token",
            child_record.command,
        )
        replacement_identity = dict(identities)
        replacement_identity[555] = SimpleNamespace(
            pid=555,
            creation_token=replacement_record.creation_token,
            executable_path=identities[555].executable_path,
            argv=identities[555].argv,
            command_line=identities[555].command_line,
        )

        class RestartedProcessTable:
            def __init__(self) -> None:
                self.calls = 0

            def snapshot(self) -> tuple[gate.ProcessRecord, ...]:
                self.calls += 1
                child = child_record if self.calls == 1 else replacement_record
                return launcher_record, server_record, child

        process_table = RestartedProcessTable()

        def restarted_process_probe(pid: int) -> object | None:
            if pid == 555 and process_table.calls > 1:
                return replacement_identity.get(pid)
            return identities.get(pid)

        restarted_context = self.make_row_context(
                api=LifecycleFakeApi(
                    status=ready,
                    post_handlers={
                        "start": lambda _payload: gate.HostApiResponse(
                            200, {"ok": True, "reason": "ready", "status": ready}
                        )
                    },
                ),
                ports=ports,
                process_table=process_table,
                process_identity_probe=restarted_process_probe,
            )
        restarted_context.host = SimpleNamespace(
            owner_pid=445,
            launcher_pid=444,
            owned_pids=[444, 445],
            _getpgid=lambda _pid: 444,
        )
        restarted = gate.L04DuplicateStartExecutor().execute(restarted_context)
        self.assertEqual(restarted.verdict, "FAIL")
        self.assertEqual(restarted.reason, "duplicate_companion_created")

        _other_records, mismatched_identities = self.companion_process_fixture(
            mismatch_child_token=True
        )
        blocked_api = LifecycleFakeApi(status=ready)
        blocked_context = self.make_row_context(
                api=blocked_api,
                ports=ports,
                process_table=FakeProcessTable(records),
                process_identity_probe=lambda pid: mismatched_identities.get(pid),
            )
        blocked_context.host = SimpleNamespace(
            owner_pid=445,
            launcher_pid=444,
            owned_pids=[444, 445],
            _getpgid=lambda _pid: 444,
        )
        blocked = gate.L04DuplicateStartExecutor().execute(blocked_context)
        self.assertEqual(blocked.verdict, "BLOCKED")
        self.assertFalse(
            any(
                method == "POST"
                and isinstance(request, tuple)
                and request[0] == "start"
                for method, request in blocked_api.calls
            )
        )

    def test_l05_uses_owned_sigkill_and_accepts_recovery_with_same_or_fresh_origin(self) -> None:
        for origin_changed in (False, True):
            with self.subTest(origin_changed=origin_changed):
                context, _service, signal_calls = self.make_l05_context(
                    origin_changed=origin_changed
                )
                result = gate.L05RelayLossRecoveryExecutor().execute(context)
                self.assertEqual(result.verdict, "PASS")
                self.assertEqual(signal_calls, [(555, signal.SIGKILL)])
                self.assertEqual(result.recovery_attempts, 1)
                self.assertTrue(result.observed["host_health_preserved"])
                self.assertGreaterEqual(result.observed["host_health_observations"], 4)
                self.assertTrue(result.observed["player_listener_preserved"])
                self.assertGreaterEqual(
                    result.observed["player_listener_observations"], 4
                )
                self.assertTrue(result.observed["fresh_session_snapshot_valid"])
                self.assertTrue(result.observed["unauthenticated_snapshot_data_free"])
                self.assertEqual(
                    result.observed["public_origin_changed"], origin_changed
                )
                self.assertEqual(
                    result.observed["stale_origin_accepted"], not origin_changed
                )
                self.assertNotIn("credential-secret-sentinel", repr(result))
                self.assertNotIn("neq-share.account.opentunnel.xyz", repr(result))

    def test_l05_blocks_before_signal_when_child_identity_is_unproven(self) -> None:
        context, _service, signal_calls = self.make_l05_context(
            mismatch_child_token=True
        )
        result = gate.L05RelayLossRecoveryExecutor().execute(context)
        self.assertEqual(result.verdict, "BLOCKED")
        self.assertEqual(result.reason, "owned_companion_target_unproven")
        self.assertEqual(signal_calls, [])

    def test_l05_rejects_launcher_pid_as_listener_pid(self) -> None:
        context, _service, signal_calls = self.make_l05_context()
        context.host.launcher_pid = context.host.owner_pid

        result = gate.L05RelayLossRecoveryExecutor().execute(context)

        self.assertEqual(result.verdict, "BLOCKED")
        self.assertEqual(result.reason, "owned_companion_target_unproven")
        self.assertEqual(signal_calls, [])

    def test_l05_revalidates_process_creation_identity_before_signal(self) -> None:
        context, _service, signal_calls = self.make_l05_context()
        records, identities = self.companion_process_fixture()
        child_observations = 0

        def changing_probe(pid: int) -> object | None:
            nonlocal child_observations
            identity = identities.get(pid)
            if pid != 555 or identity is None:
                return identity
            child_observations += 1
            if child_observations == 1:
                return identity
            return SimpleNamespace(
                pid=555,
                creation_token="reused-pid-different-creation",
                executable_path=identity.executable_path,
                argv=identity.argv,
                command_line=identity.command_line,
            )

        context.process_table = FakeProcessTable(records)
        context.process_identity_probe = changing_probe
        result = gate.L05RelayLossRecoveryExecutor().execute(context)
        self.assertEqual(result.verdict, "BLOCKED")
        self.assertEqual(result.reason, "owned_companion_target_changed")
        self.assertEqual(child_observations, 2)
        self.assertEqual(signal_calls, [])

    def test_l05_fails_exhausted_recovery_and_host_health_loss(self) -> None:
        context, _service, signal_calls = self.make_l05_context()
        context.host_api.status_sequence = [
            {
                "state": "ready",
                "reason": "ready",
                "generation": 1,
                "companion_launches": 1,
            },
            {
                "state": "degraded",
                "reason": "relay_unavailable",
                "generation": 1,
                "companion_launches": 1,
            },
            {
                "state": "failed",
                "reason": "recovery_exhausted",
                "generation": 1,
                "companion_launches": 2,
            },
        ]
        failed_recovery = gate.L05RelayLossRecoveryExecutor().execute(context)
        self.assertEqual(failed_recovery.verdict, "FAIL")
        self.assertEqual(failed_recovery.reason, "bounded_recovery_failed")
        self.assertEqual(signal_calls, [(555, signal.SIGKILL)])

        context, _service, signal_calls = self.make_l05_context()
        context.port_inspector = MappedPortInspector(
            {
                gate.HOST_PORT: preflight_gate.PortObservation(
                    gate.HOST_PORT, "free"
                )
            }
        )
        lost_host = gate.L05RelayLossRecoveryExecutor().execute(context)
        self.assertEqual(lost_host.verdict, "FAIL")
        self.assertEqual(
            lost_host.reason, "host_health_lost_before_relay_loss"
        )
        self.assertEqual(signal_calls, [])

    def test_l05_fails_if_generation_changes_or_player_listener_is_lost(self) -> None:
        context, _service, _signal_calls = self.make_l05_context()
        context.host_api.status_sequence = [
            {
                "state": "ready",
                "reason": "ready",
                "generation": 1,
                "companion_launches": 1,
            },
            {
                "state": "degraded",
                "reason": "relay_unavailable",
                "generation": 1,
                "companion_launches": 1,
            },
            {
                "state": "ready",
                "reason": "ready",
                "generation": 2,
                "companion_launches": 2,
            },
        ]
        changed_generation = gate.L05RelayLossRecoveryExecutor().execute(context)
        self.assertEqual(changed_generation.verdict, "FAIL")
        self.assertEqual(
            changed_generation.reason, "sharing_generation_changed_during_recovery"
        )

        context, _service, signal_calls = self.make_l05_context()
        original_signal = context.signal_process

        def lose_player_listener(pid: int, selected_signal: int) -> None:
            original_signal(pid, selected_signal)
            assert isinstance(context.port_inspector, MappedPortInspector)
            context.port_inspector.observations[gate.PLAYER_PORT] = (
                preflight_gate.PortObservation(gate.PLAYER_PORT, "free")
            )

        context.signal_process = lose_player_listener
        lost_listener = gate.L05RelayLossRecoveryExecutor().execute(context)
        self.assertEqual(lost_listener.verdict, "FAIL")
        self.assertEqual(
            lost_listener.reason, "player_listener_lost_during_relay_loss"
        )
        self.assertEqual(signal_calls, [(555, signal.SIGKILL)])

    def test_l05_polling_remains_bounded_with_a_stalled_injected_clock(self) -> None:
        context, _service, signal_calls = self.make_l05_context()
        still_ready = {
            "state": "ready",
            "reason": "ready",
            "generation": 1,
            "companion_launches": 1,
        }
        context.host_api.status = still_ready
        context.host_api.status_sequence = [still_ready]
        result = gate.L05RelayLossRecoveryExecutor().execute(context)
        self.assertEqual(result.verdict, "FAIL")
        self.assertEqual(result.reason, "degraded_transition_not_observed")
        expected_max = (
            math.ceil(
                gate.RecoveryPolicy(
                    max_attempts=1, backoff_schedule=(1.0,)
                ).health_check_interval
                / gate.PUBLIC_POLL_INTERVAL_SECONDS
            )
            + 2
        )
        self.assertEqual(context.host_api.status_calls, expected_max)
        self.assertEqual(signal_calls, [(555, signal.SIGKILL)])

    def test_l06_rotation_revokes_cookie_credential_and_connected_socket(self) -> None:
        service = FakePublicService()
        context, api, _ports, _table = self.make_owned_lifecycle_context(service)
        self.assertEqual(api.post("start", {}).payload["status"]["state"], "ready")
        session = self.prepare_public_client(
            context, service, connect_socket=True
        )
        old_socket = service.sockets[-1]
        events_before_rotation = old_socket.events_received

        result = gate.L06CredentialRotationExecutor().execute(context)
        service.emit_player_event()

        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(result.observed["old_session_status"], 404)
        self.assertEqual(result.observed["old_credential_status"], 401)
        self.assertEqual(result.observed["new_login_status"], 200)
        self.assertFalse(old_socket.connected)
        self.assertEqual(old_socket.events_received, events_before_rotation)
        self.assertEqual(context.public_client.session.credential, service.credential)
        recorded = json.dumps(result.observed, sort_keys=True)
        for secret in context.secrets:
            self.assertNotIn(secret, recorded)
        self.assertNotIn(session.cookie, recorded)

        blocked_context, _blocked_api, _ports, _table = (
            self.make_owned_lifecycle_context(FakePublicService())
        )
        blocked = gate.L06CredentialRotationExecutor().execute(blocked_context)
        self.assertEqual(blocked.verdict, "BLOCKED")

        failed_service = FakePublicService()
        failed_context, failed_api, _ports, _table = (
            self.make_owned_lifecycle_context(failed_service)
        )
        failed_api.post("start", {})
        self.prepare_public_client(failed_context, failed_service, connect_socket=True)

        def rotate_without_session_revocation(
            _payload: Mapping[str, object],
        ) -> gate.HostApiResponse:
            replacement = "credential-secret-rotated-sentinel"
            failed_service.credential = replacement
            for connected in failed_service.sockets:
                connected.disconnect()
            failed_api.status = {**failed_api.status, "state": "ready"}
            return gate.HostApiResponse(
                200,
                {
                    "ok": True,
                    "reason": "credential_rotated",
                    "credential": replacement,
                    "status": failed_api.status,
                },
            )

        failed_api.post_handlers["rotate"] = rotate_without_session_revocation
        failed = gate.L06CredentialRotationExecutor().execute(failed_context)
        self.assertEqual(failed.verdict, "FAIL")
        self.assertEqual(failed.reason, "old_session_accepted_after_rotation")

    def test_l07_stop_checks_public_listener_session_and_host(self) -> None:
        service = FakePublicService()
        context, api, _ports, _table = self.make_owned_lifecycle_context(service)
        api.post("start", {})
        self.prepare_public_client(context, service)
        stopped = gate.L07StopSharingExecutor().execute(context)
        self.assertEqual(stopped.verdict, "PASS")
        self.assertTrue(stopped.observed["host_healthy"])

        failed_service = FakePublicService()
        failed_context, failed_api, _ports, _table = (
            self.make_owned_lifecycle_context(failed_service)
        )
        failed_api.post("start", {})
        self.prepare_public_client(failed_context, failed_service)

        def stop_without_withdrawing_route(
            _payload: Mapping[str, object],
        ) -> gate.HostApiResponse:
            failed_api.status = {**failed_api.status, "state": "off"}
            return gate.HostApiResponse(
                200,
                {"ok": True, "reason": "stopped", "status": failed_api.status},
            )

        failed_api.post_handlers["stop"] = stop_without_withdrawing_route
        failed = gate.L07StopSharingExecutor().execute(failed_context)
        self.assertEqual(failed.verdict, "FAIL")
        self.assertEqual(failed.reason, "public_player_reachable_after_stop")

        blocked_service = FakePublicService()
        blocked_context, blocked_api, blocked_ports, _table = (
            self.make_owned_lifecycle_context(blocked_service)
        )
        blocked_api.post("start", {})
        self.prepare_public_client(blocked_context, blocked_service)
        stop_handler = blocked_api.post_handlers["stop"]

        def stop_with_unknown_player_port(
            payload: Mapping[str, object],
        ) -> gate.HostApiResponse:
            response = stop_handler(payload)
            blocked_ports.unknown.add(gate.PLAYER_PORT)
            return response

        blocked_api.post_handlers["stop"] = stop_with_unknown_player_port
        blocked = gate.L07StopSharingExecutor().execute(blocked_context)
        self.assertEqual(blocked.verdict, "BLOCKED")
        self.assertEqual(blocked.reason, "player_listener_observation_unavailable")

    def test_l08_host_exit_restart_reconciles_without_autostart(self) -> None:
        service = FakePublicService()
        context, api, _ports, _table = self.make_owned_lifecycle_context(service)
        api.post("start", {})
        self.prepare_public_client(context, service)
        result = gate.L08HostExitRestartExecutor().execute(context)
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(result.observed["sharing_state_after_restart"], "off")
        self.assertEqual(context.host.process_generation, 2)

        failed_service = FakePublicService()
        failed_context, failed_api, failed_ports, failed_table = (
            self.make_owned_lifecycle_context(failed_service)
        )
        failed_api.post("start", {})
        self.prepare_public_client(failed_context, failed_service)
        original_stop = failed_context.host.stop

        def stop_with_orphaned_owner_record() -> bool:
            process = failed_context.host.process
            if process is not None:
                process.returncode = 0
            failed_context.host.process = None
            failed_ports.host_pid = None
            failed_ports.player_pid = None
            failed_service.stop_sharing()
            failed_table.records = ()
            return True

        failed_context.host.stop = stop_with_orphaned_owner_record
        failed = gate.L08HostExitRestartExecutor().execute(failed_context)
        self.assertEqual(failed.verdict, "FAIL")
        self.assertEqual(failed.reason, "owner_record_remains_after_host_exit")
        self.assertIsNotNone(original_stop)

        blocked_service = FakePublicService()
        blocked_context, blocked_api, _ports, _table = (
            self.make_owned_lifecycle_context(blocked_service)
        )
        blocked_api.post("start", {})
        self.prepare_public_client(blocked_context, blocked_service)
        blocked_context.host.process = None
        blocked = gate.L08HostExitRestartExecutor().execute(blocked_context)
        self.assertEqual(blocked.verdict, "BLOCKED")
        self.assertEqual(blocked.reason, "host_process_ownership_unavailable")

    def test_l09_revoke_rejects_login_without_identity_rebootstrap(self) -> None:
        service = FakePublicService()
        context, _api, _ports, _table = self.make_owned_lifecycle_context(service)
        self.prepare_public_client(context, service)
        result = gate.L09RevokeAccessExecutor().execute(context)
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(result.observed["identity_up_invocations_before"], 1)
        self.assertEqual(result.observed["identity_up_invocations_after_revoke"], 1)

        failed_service = FakePublicService()
        failed_context, failed_api, _ports, _table = (
            self.make_owned_lifecycle_context(failed_service)
        )
        self.prepare_public_client(failed_context, failed_service)
        revoke_handler = failed_api.post_handlers["revoke"]

        def revoke_without_invalidating(
            payload: Mapping[str, object],
        ) -> gate.HostApiResponse:
            failed_api.status = {**failed_api.status, "state": "off"}
            return gate.HostApiResponse(
                200,
                {
                    "ok": True,
                    "reason": "access_revoked",
                    "status": failed_api.status,
                },
            )

        failed_api.post_handlers["revoke"] = revoke_without_invalidating
        failed = gate.L09RevokeAccessExecutor().execute(failed_context)
        self.assertEqual(failed.verdict, "FAIL")
        self.assertEqual(failed.reason, "session_accepted_after_revoke")
        self.assertIsNotNone(revoke_handler)

        blocked_context, _api, _ports, _table = self.make_owned_lifecycle_context(
            FakePublicService(),
            initial_status={
                "state": "off",
                "identity_initialized": True,
                "companion_launches": 0,
            },
        )
        blocked = gate.L09RevokeAccessExecutor().execute(blocked_context)
        self.assertEqual(blocked.verdict, "BLOCKED")
        self.assertEqual(blocked.reason, "identity_up_counter_unavailable")

    def test_l10_teardown_deletes_only_verified_gate_identity(self) -> None:
        service = FakePublicService()
        runner = FakeIdentityCommandRunner()
        context, _api, _ports, _table = self.make_owned_lifecycle_context(
            service, companion_runner=runner
        )
        context.public_client.bind_invitation(service.accepted_origin)
        result = gate.L10CleanTeardownExecutor().execute(context)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(result.observed["gate_state_root_removed"])
        self.assertTrue(result.observed["gate_state_parent_removed_if_empty"])
        self.assertEqual(
            result.observed["gate_state_root_id8"],
            gate._state_root_id8(context.run_id),
        )
        self.assertEqual(
            result.observed["gate_state_path_sha256"],
            gate._state_path_sha256(context.host.state_root),
        )
        self.assertTrue(runner.deleted)
        self.assertFalse(context.host.state_root.exists())
        self.assertFalse(context.host.state_root.parent.exists())
        self.assertTrue(context.companion_path.is_file())
        self.assertEqual(len(runner.calls), 3)
        delete_argv, environment, timeout = runner.calls[1]
        self.assertEqual(delete_argv[1:3], ("--profile", gate.DEFAULT_PROFILE))
        self.assertEqual(delete_argv[-2:], ("delete", "--yes"))
        self.assertEqual(set(environment), {
            "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"
        })
        self.assertEqual(timeout, 30.0)

        sibling_service = FakePublicService()
        sibling_runner = FakeIdentityCommandRunner()
        sibling_context, _api, _ports, _table = self.make_owned_lifecycle_context(
            sibling_service, companion_runner=sibling_runner
        )
        sibling_parent = sibling_context.host.state_root.parent
        sibling_cache = sibling_parent / "unrelated-cache-entry"
        sibling_cache.mkdir(mode=0o700)
        sibling_marker = sibling_cache / "keep.txt"
        sibling_marker.write_text("unrelated-cache-sentinel", encoding="ascii")
        sibling_context.public_client.bind_invitation(
            sibling_service.accepted_origin
        )
        sibling_result = gate.L10CleanTeardownExecutor().execute(sibling_context)
        self.assertEqual(sibling_result.verdict, "PASS")
        self.assertFalse(
            sibling_result.observed["gate_state_parent_removed_if_empty"]
        )
        self.assertTrue(sibling_marker.is_file())
        self.assertEqual(sibling_marker.read_text(encoding="ascii"), "unrelated-cache-sentinel")

        failed_runner = FakeIdentityCommandRunner(absent_after_delete=False)
        failed_service = FakePublicService()
        failed_context, _api, _ports, _table = self.make_owned_lifecycle_context(
            failed_service, companion_runner=failed_runner
        )
        failed_context.public_client.bind_invitation(failed_service.accepted_origin)
        failed = gate.L10CleanTeardownExecutor().execute(failed_context)
        self.assertEqual(failed.verdict, "FAIL")
        self.assertEqual(failed.reason, "gate_remote_identity_remains")
        self.assertTrue(failed_context.host.state_root.exists())

        blocked_runner = FakeIdentityCommandRunner(
            status_output="Hostname: identity-fixture.opentunnel.xyz\n"
        )
        blocked_service = FakePublicService()
        blocked_context, _api, _ports, _table = self.make_owned_lifecycle_context(
            blocked_service, companion_runner=blocked_runner
        )
        blocked_context.public_client.bind_invitation(blocked_service.accepted_origin)
        blocked = gate.L10CleanTeardownExecutor().execute(blocked_context)
        self.assertEqual(blocked.verdict, "BLOCKED")
        self.assertEqual(blocked.reason, "identity_status_before_delete_invalid")

    def test_lifecycle_rows_l06_through_l10_complete_in_one_offline_simulation(self) -> None:
        service = FakePublicService()
        runner = FakeIdentityCommandRunner()
        context, api, ports, _table = self.make_owned_lifecycle_context(
            service, companion_runner=runner
        )
        started = api.post("start", {})
        self.assertEqual(started.payload["status"]["state"], "ready")
        self.prepare_public_client(context, service, connect_socket=True)

        results = [
            gate.L06CredentialRotationExecutor().execute(context),
            gate.L07StopSharingExecutor().execute(context),
            gate.L08HostExitRestartExecutor().execute(context),
            gate.L09RevokeAccessExecutor().execute(context),
            gate.L10CleanTeardownExecutor().execute(context),
        ]

        self.assertEqual([item.verdict for item in results], ["PASS"] * 5)
        self.assertTrue(all(gate._bounded_json(dict(item.observed)) for item in results))
        self.assertEqual(ports.inspect(gate.HOST_PORT).state, "free")
        self.assertEqual(ports.inspect(gate.PLAYER_PORT).state, "free")
        self.assertTrue(runner.deleted)
        self.assertTrue(context.companion_path.is_file())

    def test_process_table_is_bounded_and_parses_fixed_system_output(self) -> None:
        output = (
            b"123 1 501 Wed Nov 11 11:00:00 2026 "
            b"/runtime/opentunnel serve --profile neq\n"
        )

        def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess([], 0, output, b"")

        records = gate.SystemProcessTable(runner=runner).snapshot()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].pid, 123)
        self.assertEqual(records[0].parent_pid, 1)
        self.assertEqual(records[0].uid, 501)
        self.assertEqual(
            records[0].command, "/runtime/opentunnel serve --profile neq"
        )

        oversized = gate.SystemProcessTable(
            runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
                [], 0, b"x" * (gate.MAX_PROCESS_TABLE_BYTES + 1), b""
            )
        )
        with self.assertRaises(gate.ProcessTableError):
            oversized.snapshot()

        def timeout_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            raise subprocess.TimeoutExpired("ps", 3)

        with self.assertRaises(gate.ProcessTableError):
            gate.SystemProcessTable(runner=timeout_runner).snapshot()

    def test_frozen_manifest_digest_and_contract_rows(self) -> None:
        self.assertTrue(gate.verify_frozen_manifest())
        self.assertEqual(gate.calculate_manifest_digest(), gate.FROZEN_MANIFEST_SHA256)
        self.assertEqual(gate.calculate_manifest_digest(), gate.calculate_manifest_digest())
        self.assertEqual(
            [(row.row_id, row.name) for row in gate.LIVE_ROWS],
            [
                ("L01", "sharing-off-local-play"),
                ("L02", "identity-init-once"),
                ("L03", "issue-access-start-auth-entry"),
                ("L04", "duplicate-start-idempotent"),
                ("L05", "relay-loss-bounded-recovery"),
                ("L06", "credential-rotation-revocation"),
                ("L07", "stop-sharing"),
                ("L08", "host-exit-restart"),
                ("L09", "revoke-access"),
                ("L10", "clean-teardown"),
            ],
        )
        self.assertEqual(gate.LIVE_ROWS[4].timeout_seconds, 420)
        self.assertEqual(gate.FROZEN_CAPS["driver_wall_clock_seconds"], 3600)
        self.assertEqual(gate.FROZEN_CAPS["companion_serve_launches"], 4)
        self.assertEqual(gate.FROZEN_CAPS["companion_up_invocations"], 1)
        self.assertEqual(gate.FROZEN_CAPS["relay_tunnel_creations"], 2)
        self.assertEqual(gate.FROZEN_CAPS["provider_attempts"], 0)
        self.assertEqual(gate.FROZEN_CAPS["automatic_retries"], 0)
        manifest = gate.live_manifest()
        self.assertTrue(
            all("precondition" in row and "expected" in row for row in manifest["rows"])
        )
        self.assertEqual(
            manifest["verdict_policy"]["linux-arm64"]["reason"],
            "owner-run-required",
        )
        self.assertEqual(manifest["provider_budget_ceiling"], 1)

    def test_plan_and_help_have_no_side_effects(self) -> None:
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        stdout = io.StringIO()
        with patch("sys.stdout", stdout), patch.object(
            gate, "_default_dependencies", side_effect=AssertionError("plan dependencies")
        ):
            self.assertEqual(gate.main(["plan"]), 0)
        plan = json.loads(stdout.getvalue())
        self.assertTrue(plan["plan_only"])
        self.assertFalse(plan["side_effects"])
        self.assertEqual(plan["gate_verdict"], "PENDING")
        self.assertEqual(plan["companion_install_root"], "tmp/combat_capture")
        self.assertEqual(
            plan["companion_missing_refusal"],
            "companion_not_installed_in_capture_root",
        )
        after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        self.assertEqual(before, after)
        help_output = io.StringIO()
        with patch("sys.stdout", help_output):
            with self.assertRaises(SystemExit) as raised:
                gate.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage:", help_output.getvalue())

    def test_capture_creation_failure_returns_blocked_without_launch(self) -> None:
        original_mkdir = Path.mkdir
        capture = self.root / gate.EVIDENCE_BASE / self.run_id / "capture"

        def refuse_capture(path: Path, *args: object, **kwargs: object) -> None:
            if path == capture:
                raise PermissionError("capture create refused")
            original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", refuse_capture):
            result = gate.run_live_gate(self.dependencies, self.arguments)
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertIn(
            "capture_directory_create_failed", result["infrastructure_failures"]
        )
        self.assertIsNone(result["evidence_path"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_partial_private_state_tree_creation_is_cleaned_up(self) -> None:
        original_mkdir = Path.mkdir
        state_root = self.state_root_for(self.run_id)

        def refuse_config(path: Path, *args: object, **kwargs: object) -> None:
            if path == state_root / "config":
                raise PermissionError("state child create refused")
            original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", refuse_config):
            with self.assertRaises(PermissionError):
                gate._create_private_state_tree(state_root)
        self.assertFalse(state_root.exists())

    def test_failed_host_start_teardown_removes_only_driver_owned_state(self) -> None:
        original_start = FakeHost.start

        def fail_after_state_creation(host: FakeHost) -> bool:
            self.assertTrue(original_start(host))
            return False

        with patch.object(FakeHost, "start", fail_after_state_creation):
            result = gate.run_live_gate(self.dependencies, self.arguments)

        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertIsNotNone(self.fake_host)
        assert self.fake_host is not None
        self.assertTrue(self.fake_host.stopped)
        self.assertFalse(self.fake_host.state_root.exists())
        self.assertFalse(self.fake_host.state_root.parent.exists())
        self.assertIsNotNone(result["evidence_path"])
        run_record = json.loads(
            (
                self.root
                / str(result["evidence_path"])
                / "run.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(run_record["teardown"]["gate_state_root_removed"])
        self.assertTrue(
            run_record["teardown"]["gate_state_parent_removed_if_empty"]
        )
        summary_record = json.loads(
            (
                self.root
                / str(result["evidence_path"])
                / "summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(summary_record["teardown_complete"])

    def test_state_cleanup_refuses_a_replaced_run_root(self) -> None:
        state_root = self.state_root_for(self.run_id)
        host = FakeHost(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            state_root,
            self.run_id,
            self.ports,
        )
        self.assertTrue(host.start())
        original_root = state_root.with_name(state_root.name + "-owned")
        state_root.rename(original_root)
        gate._create_private_state_tree(state_root)

        cleanup = gate._cleanup_driver_state_root(
            host, run_id=self.run_id, repository_root=self.root
        )

        self.assertIsNone(cleanup)
        self.assertTrue(state_root.is_dir())
        self.assertTrue(original_root.is_dir())

    def test_preflight_report_accepts_frozen_n3_and_compact_n2_shapes(self) -> None:
        n3_path = self.write_preflight()
        self.assertEqual(
            gate.load_preflight_report(self.root, self.report_argument, self.sha)["gate"],
            "N3-provider-free-preflight",
        )
        n2 = {"head": self.sha, "infrastructure_failures": []}
        n3_path.write_text(json.dumps(n2), encoding="utf-8")
        self.assertEqual(
            gate.load_preflight_report(self.root, self.report_argument, self.sha), n2
        )
        result = gate.run_live_gate(self.dependencies, self.arguments)
        self.assertNotIn(
            "preflight_identity_mismatch", result["infrastructure_failures"]
        )
        self.assertEqual(self.host_factory_calls, 1)

    def test_compact_n2_preflight_binds_sha_and_rejects_infrastructure_failures(self) -> None:
        path = self.write_preflight(
            {"head": "b" * 40, "infrastructure_failures": []}
        )
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)
        path = self.write_preflight(
            {"head": self.sha, "infrastructure_failures": ["preflight-fault"]}
        )
        with self.assertRaisesRegex(
            gate.GateError, "preflight_infrastructure_failures"
        ):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)

    def test_preflight_refuses_incomplete_rows_faults_semantic_failures_and_attempts(self) -> None:
        mutations = (
            lambda document: document.update({"run_id": "n3-other-run"}),
            lambda document: document.update({"head": "b" * 40}),
            lambda document: document["invocation"].update({"cwd": "/outside"}),
            lambda document: document["invocation"].update({"pythonpath": ""}),
            lambda document: document.update({"row_coverage_complete": False}),
            lambda document: document["rows"][0].update({"verdict": "BLOCKED"}),
            lambda document: document["rows"][0].update({"expected": "different"}),
            lambda document: document["fault_checks"].pop("attempt_cap_fail_fast"),
            lambda document: document["fault_checks"]["time_cap_fail_fast"].update(
                {"passed": False}
            ),
            lambda document: document.update({"semantic_failures": ["semantic-failure"]}),
            lambda document: document.update({"providers_called": 1}),
            lambda document: document.update({"attempts": 0}),
            lambda document: document["teardown"].update({"complete": False}),
            lambda document: document["teardown"].update({"lock_released": False}),
        )
        for mutate in mutations:
            document = json.loads(self.write_preflight().read_text(encoding="utf-8"))
            mutate(document)
            self.write_preflight(document)
            with self.subTest(document=document), self.assertRaisesRegex(
                gate.GateError, "preflight_report_invalid"
            ):
                gate.load_preflight_report(
                    self.root, self.report_argument, self.sha
                )

    def test_preflight_report_path_must_be_bound_to_its_run_id(self) -> None:
        source = self.write_preflight()
        other_run = self.root / gate.EVIDENCE_BASE / "n3-other-run" / "preflight"
        other_run.mkdir(parents=True)
        other_path = other_run / "preflight.json"
        other_path.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(
                self.root,
                other_path.relative_to(self.root).as_posix(),
                self.sha,
            )

    def test_preflight_refuses_missing_invalid_infrastructure_and_identity_mismatch(self) -> None:
        with self.assertRaisesRegex(gate.GateError, "preflight_report_missing"):
            gate.load_preflight_report(self.root, "tmp/missing.json", self.sha)
        path = self.write_preflight()
        path.write_text("not-json", encoding="ascii")
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)
        dirty = json.loads(self.write_preflight().read_text(encoding="utf-8"))
        dirty["infrastructure_failures"] = ["fault"]
        path.write_text(json.dumps(dirty), encoding="utf-8")
        with self.assertRaisesRegex(gate.GateError, "preflight_infrastructure_failures"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)
        mismatched = json.loads(self.write_preflight().read_text(encoding="utf-8"))
        mismatched["identity"]["git_sha"] = "b" * 40
        path.write_text(json.dumps(mismatched), encoding="utf-8")
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)

    def test_workspace_dirty_sha_and_unsupported_platform_refuse_before_side_effects(self) -> None:
        cases = (
            (False, self.sha, "darwin-arm64", "worktree_dirty"),
            (True, "b" * 40, "darwin-arm64", "sha_mismatch"),
            (True, self.sha, "linux-arm64", "live_platform_not_supported"),
        )
        for clean, sha, platform_key, expected in cases:
            identity = preflight_gate.WorkspaceIdentity(
                git_sha=sha,
                worktree_clean=clean,
                platform_key=platform_key,
                git_common_dir=self.common_dir,
                source_files_sha256="1" * 64,
                dependency_lock_sha256="2" * 64,
                route_contract_sha256="3" * 64,
                identity_freeze_sha256="4" * 64,
            )
            dependencies = self.make_dependencies(identity=identity)
            result = gate.run_live_gate(dependencies, self.arguments)
            self.assertEqual(result["gate_verdict"], "BLOCKED")
            self.assertIn(expected, result["infrastructure_failures"])
            self.assertIsNone(result["evidence_path"])
            self.assertEqual(self.host_factory_calls, 0)
        invalid_party = gate.RunArguments(
            run_id=self.run_id,
            sha=self.sha,
            booking_id=self.booking_id,
            preflight_report=self.report_argument,
            party_size=True,
        )
        result = gate.run_live_gate(self.dependencies, invalid_party)
        self.assertIn("party_size_unsupported", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_preflight_identity_hashes_must_match_live_workspace(self) -> None:
        preflight = self.write_preflight()
        document = json.loads(preflight.read_text(encoding="utf-8"))
        document["identity"]["route_contract_sha256"] = "9" * 64
        self.write_preflight(document)
        result = gate.run_live_gate(self.dependencies, self.arguments)
        self.assertIn("preflight_identity_mismatch", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_lock_record_verifies_and_each_required_field_is_bound(self) -> None:
        lock = self.write_lock()
        valid = gate.verify_lock_record(
            lock,
            root=self.root,
            arguments=self.arguments,
            platform_key="macos-arm64",
            now=TEST_NOW,
        )
        self.assertEqual(valid["booking_id"], self.booking_id)
        mutations = {
            "booking_id": "other-booking",
            "holder": "other-holder",
            "gate": "N2-live",
            "authorizing_ruling": "",
            "window_start": "not-a-date",
            "window_end": "not-a-date",
            "run_id": "other-run",
            "evidence": "tmp/other/capture",
            "preflight_report": "other-report.json",
            "head": "b" * 40,
        }
        for key, value in mutations.items():
            invalid = dict(self.lock_record())
            invalid[key] = value
            self.write_lock(invalid)
            with self.subTest(field=key), self.assertRaises(gate.GateError):
                gate.verify_lock_record(
                    lock,
                    root=self.root,
                    arguments=self.arguments,
                    platform_key="macos-arm64",
                    now=TEST_NOW,
                )
        for key, value in {
            "party_size": 4,
            "platform": "linux-arm64",
            "provider_dispatch_attempts": 1,
            "max_tunnel_creations": 3,
            "max_companion_launches": 5,
            "window_hours": 4,
        }.items():
            invalid = dict(self.lock_record())
            invalid["frozen_caps"] = dict(invalid["frozen_caps"])
            invalid["frozen_caps"][key] = value
            self.write_lock(invalid)
            with self.subTest(cap=key), self.assertRaisesRegex(
                gate.GateError, "lock_caps_mismatch"
            ):
                gate.verify_lock_record(
                    lock,
                    root=self.root,
                    arguments=self.arguments,
                    platform_key="macos-arm64",
                    now=TEST_NOW,
                )

    def test_lock_window_expired_and_over_three_hours_refuse(self) -> None:
        lock = self.write_lock()
        expired = self.lock_record()
        expired["window_start"] = (TEST_NOW - timedelta(hours=5)).isoformat()
        expired["window_end"] = (TEST_NOW - timedelta(seconds=1)).isoformat()
        self.write_lock(expired)
        with self.assertRaisesRegex(gate.GateError, "lock_window_expired"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        boundary = self.lock_record()
        boundary["window_end"] = TEST_NOW.isoformat()
        self.write_lock(boundary)
        with self.assertRaisesRegex(gate.GateError, "lock_window_expired"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        too_long = self.lock_record()
        too_long["window_start"] = (TEST_NOW - timedelta(hours=2)).isoformat()
        too_long["window_end"] = (TEST_NOW + timedelta(hours=2)).isoformat()
        too_long["frozen_caps"] = dict(too_long["frozen_caps"])
        too_long["frozen_caps"]["window_hours"] = 3
        self.write_lock(too_long)
        with self.assertRaisesRegex(gate.GateError, "lock_window_expired"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )

    def test_lock_requires_single_line_json_and_existing_directory(self) -> None:
        lock = self.write_lock()
        holder = lock / "holder.json"
        holder.write_text("{}\n{}\n", encoding="ascii")
        with self.assertRaisesRegex(gate.GateError, "lock_record_invalid"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        with self.assertRaisesRegex(gate.GateError, "lock_unavailable"):
            gate.verify_lock_record(
                self.root / "absent-lock",
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )

    def test_lock_rejects_symlinked_directory_and_holder(self) -> None:
        lock = self.write_lock()
        coordination = lock.parent
        lock_link = coordination / "linked-lock"
        lock_link.symlink_to(lock, target_is_directory=True)
        with self.assertRaisesRegex(gate.GateError, "lock_record_invalid"):
            gate.verify_lock_record(
                lock_link,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        holder = lock / "holder.json"
        target = coordination / "holder-copy.json"
        target.write_bytes(holder.read_bytes())
        holder.unlink()
        holder.symlink_to(target)
        with self.assertRaisesRegex(gate.GateError, "lock_record_invalid"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )

    def test_capture_destination_ports_and_companion_refusals(self) -> None:
        capture = self.root / gate.EVIDENCE_BASE / self.run_id / "capture"
        capture.mkdir()
        result = gate.run_live_gate(self.make_dependencies(), self.arguments)
        self.assertIn("capture_destination_exists", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)
        capture.rmdir()

        busy = FakePortInspector()
        busy.busy_ports.add(gate.PLAYER_PORT)
        result = gate.run_live_gate(self.make_dependencies(ports=busy), self.arguments)
        self.assertIn("gate_port_not_free", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)
        self.assertNotIn(8357, busy.seen)

        result = gate.run_live_gate(
            self.make_dependencies(companion_error="companion_digest_invalid"), self.arguments
        )
        self.assertIn("companion_digest_invalid", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_repo_root_only_companion_is_refused_before_host_start(self) -> None:
        capture_runtime = self.root / gate.CAPTURE_RELATIVE / "runtime"
        shutil.rmtree(capture_runtime)
        repository_companion = self._write_companion_install(self.root)
        self.assertTrue(repository_companion.is_file())

        result = gate.run_live_gate(self.make_dependencies(), self.arguments)

        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertFalse(result["is_gate_pass"])
        self.assertEqual(
            result["platform_verdicts"]["macos-arm64"]["reason"],
            "companion_not_installed_in_capture_root",
        )
        self.assertIn(
            "companion_not_installed_in_capture_root",
            result["infrastructure_failures"],
        )
        self.assertEqual(self.host_factory_calls, 0)
        self.assertFalse(
            (self.root / gate.EVIDENCE_BASE / self.run_id / "capture").exists()
        )

    def test_gate_state_cache_path_policy_and_pre_side_effect_refusals(self) -> None:
        home = Path("/Users/facilitator")
        self.assertEqual(
            gate._default_state_cache_base(
                platform="darwin",
                environ={"XDG_CACHE_HOME": "/ignored/cache"},
                home=home,
            ),
            home / "Library" / "Caches",
        )
        self.assertEqual(
            gate._default_state_cache_base(
                platform="linux", environ={"XDG_CACHE_HOME": "/cache/xdg"}, home=home
            ),
            Path("/cache/xdg"),
        )
        self.assertEqual(
            gate._default_state_cache_base(platform="linux", environ={}, home=home),
            home / ".cache",
        )
        with self.assertRaisesRegex(gate.GateError, "gate_state_root_invalid"):
            gate._default_state_cache_base(
                platform="linux", environ={"XDG_CACHE_HOME": "relative-cache"}, home=home
            )

        state_root = self.state_root_for(self.run_id)
        socket_path = (
            state_root
            / "neq"
            / "opentunnel"
            / gate.DEFAULT_PROFILE
            / "run"
            / (gate.DEFAULT_PROFILE + ".sock")
        )
        self.assertLess(len(os.fsencode(socket_path)), gate.MAX_UNIX_SOCKET_PATH)
        self.assertEqual(state_root.name, gate._state_root_id8(self.run_id))
        self.assertEqual(
            gate._validate_run_paths(self.root, self.arguments, self.state_base)[2],
            state_root,
        )

        too_long_base = self.state_base / ("long" * 20)
        result = gate.run_live_gate(
            self.make_dependencies(state_base_provider=lambda: too_long_base),
            self.arguments,
        )
        self.assertIn("state_root_too_long", result["infrastructure_failures"])
        self.assertFalse(
            (self.root / gate.EVIDENCE_BASE / self.run_id / "capture").exists()
        )
        self.assertEqual(self.host_factory_calls, 0)

        namespace = self.state_base / "neq-n3g"
        namespace.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(gate.GateError, "gate_state_root_invalid"):
            gate._validate_run_paths(self.root, self.arguments, self.state_base)
        namespace.unlink()

        namespace.mkdir(mode=0o700)
        state_root.mkdir(mode=0o700)
        with self.assertRaisesRegex(gate.GateError, "gate_state_root_exists"):
            gate._validate_run_paths(self.root, self.arguments, self.state_base)
        shutil.rmtree(state_root)
        namespace.rmdir()

        with patch.object(gate.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(gate.GateError, "gate_state_root_invalid"):
                gate._validate_run_paths(self.root, self.arguments, self.state_base)

    def test_l06_failure_stops_later_rows_and_still_tears_down(self) -> None:
        class FailRotation:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                return gate.RowExecutionResult("FAIL", "old_access_still_valid")

        registry = {
            row.row_id: PassingExecutor() for row in gate.LIVE_ROWS
        }
        registry["L06"] = FailRotation()
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry), self.arguments
        )
        self.assertEqual(result["gate_verdict"], "FAIL")
        self.assertEqual([row["verdict"] for row in result["rows"][:5]], ["PASS"] * 5)
        self.assertEqual(result["rows"][5]["verdict"], "FAIL")
        self.assertEqual(
            [row["reason"] for row in result["rows"][6:]], ["fail-fast"] * 4
        )
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)
        assert self.fake_host is not None
        self.assertFalse(self.fake_host.state_root.exists())
        self.assertFalse(self.fake_host.state_root.parent.exists())
        self.assertIn(("POST", ("stop", {})), self.fake_api.calls)
        run_record = json.loads(
            (
                self.root
                / str(result["evidence_path"])
                / "run.json"
            ).read_text(encoding="utf-8")
        )
        summary_record = json.loads(
            (
                self.root
                / str(result["evidence_path"])
                / "summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(run_record["teardown"]["gate_state_root_removed"])
        self.assertTrue(summary_record["teardown_complete"])

    def test_full_simulated_run_passes_rows_but_stays_pending_and_redacts(self) -> None:
        secrets = [
            "credential-secret-%s-sentinel" % row.row_id
            for row in gate.LIVE_ROWS
        ]

        class PassingExecutor:
            def __init__(self, secret: str, row_id: str) -> None:
                self.secret = secret
                self.row_id = row_id

            def execute(self, context: gate.RowContext) -> gate.RowExecutionResult:
                context.remember_secret(self.secret)
                return gate.RowExecutionResult(
                    "PASS",
                    "offline-simulated-pass",
                    {
                        "credential": self.secret,
                        "invitation": "https://%s.invalid/private-path" % self.row_id,
                        "row_observed": self.row_id,
                    },
                )

        registry = {
            row.row_id: PassingExecutor(secret, row.row_id)
            for row, secret in zip(gate.LIVE_ROWS, secrets)
        }
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry), self.arguments
        )

        self.assertEqual(result["gate_verdict"], "PENDING")
        self.assertFalse(result["is_gate_pass"])
        self.assertEqual(
            result["platform_verdicts"]["macos-arm64"]["verdict"], "PASS"
        )
        self.assertEqual(
            result["platform_verdicts"]["linux-arm64"]["reason"],
            "owner-run-required",
        )
        self.assertEqual(
            [row["row_id"] for row in result["rows"]],
            [row.row_id for row in gate.LIVE_ROWS],
        )
        self.assertEqual([row["verdict"] for row in result["rows"]], ["PASS"] * 10)
        evidence = self.root / result["evidence_path"]
        for artifact in evidence.iterdir():
            if not artifact.is_file():
                continue
            content = artifact.read_text(encoding="utf-8")
            for secret in secrets:
                self.assertNotIn(secret, content)
            for row in gate.LIVE_ROWS:
                self.assertNotIn(
                    "https://%s.invalid" % row.row_id, content
                )
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)

    def test_prepared_sandbox_config_is_parsed_without_execution(self) -> None:
        config = self.root / gate.CAPTURE_RELATIVE / "config.py"
        config.write_text("WEB_PORT = 8360\nprint('config-executed-sentinel')\n", encoding="ascii")
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            selected = gate.validate_prepared_sandbox(self.root)
        self.assertEqual(selected, self.root / gate.CAPTURE_RELATIVE)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(gate._config_has_exact_web_port(b"WEB_PORT = 8360\n"))
        for source in (
            b"WEB_PORT = 8357\n",
            b"WEB_PORT = 8360; OTHER = 1\n",
            b"WEB_PORT = int('8360')\n",
            b"WEB_PORT = 8360\nWEB_PORT = 8360\n",
            b"def f(WEB_PORT):\n    pass\nWEB_PORT = 8360\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(gate._config_has_exact_web_port(source))

    def test_environment_allowlist_is_exact_and_contract_overrides_parent(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        overrides = {
            "NEQ_OPEN_BROWSER": "1",
            "NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS": "3",
            "NEQ_N3_GATE_RUN_ID": "wrong-run",
            "NEQ_PROVIDER_ATTEMPT_BUDGET": "30",
            "NEQ_PROVIDER_ATTEMPT_LEDGER": "/outside/ledger",
            "OPENAI_API_KEY": "secret-env-sentinel",
            "AWS_SECRET_ACCESS_KEY": "secret-env-sentinel",
        }
        with patch.dict(os.environ, overrides, clear=False):
            environment = gate.build_host_environment(sandbox, state, self.run_id)
        expected = {
            "PATH",
            "PYTHONPATH",
            "PYTHONUNBUFFERED",
            "PYTHONDONTWRITEBYTECODE",
            "NEQ_OPEN_BROWSER",
            "NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS",
            "NEQ_N3_GATE_RUN_ID",
            "NEQ_PROVIDER_ATTEMPT_BUDGET",
            "NEQ_PROVIDER_ATTEMPT_LEDGER",
            "NEQ_PROVIDER_ATTEMPT_RUN_ID",
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
            "XDG_RUNTIME_DIR",
            "TMPDIR",
        }
        self.assertEqual(set(environment), expected)
        self.assertEqual(environment["NEQ_OPEN_BROWSER"], "0")
        self.assertEqual(environment["NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS"], "1")
        self.assertEqual(environment["NEQ_N3_GATE_RUN_ID"], self.run_id)
        self.assertEqual(environment["NEQ_PROVIDER_ATTEMPT_BUDGET"], "1")
        self.assertEqual(environment["NEQ_PROVIDER_ATTEMPT_RUN_ID"], self.run_id)
        self.assertEqual(environment["PYTHONPATH"], str(sandbox))
        self.assertTrue(environment["XDG_STATE_HOME"].startswith(str(state)))
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)
        self.assertNotIn("NEQ_PLAYER_PASSWORD_VERIFIER", environment)
        self.assertNotIn("NEQ_PLAYER_DEV_LISTENER", environment)

    def test_host_api_uses_loopback_host_origin_and_json_headers_without_logging(self) -> None:
        class Response:
            status = 200

            def read(self, _limit: int) -> bytes:
                return b'{"ok":true,"credential":"credential-sentinel","invitation":"https://relay.invalid/path"}'

        class Connection:
            def __init__(self, host: str, port: int, *, timeout: float) -> None:
                self.target = (host, port, timeout)
                self.calls: list[tuple[object, ...]] = []

            def request(self, *args: object, **kwargs: object) -> None:
                self.calls.append((args, kwargs))

            def getresponse(self) -> Response:
                return Response()

            def close(self) -> None:
                return

        connections: list[Connection] = []

        def factory(host: str, port: int, *, timeout: float) -> Connection:
            connection = Connection(host, port, timeout=timeout)
            connections.append(connection)
            return connection

        client = gate.HostApiClient(connection_factory=factory)
        status = client.get_status()
        post = client.post("initialize-identity", {"confirm": True})
        self.assertEqual(status.status, 200)
        self.assertEqual(post.payload["credential"], "credential-sentinel")
        get_args, get_kwargs = connections[0].calls[0]
        self.assertEqual(get_args, ("GET", "/api/player-sharing/status"))
        self.assertEqual(get_kwargs["headers"]["Host"], "127.0.0.1:8360")
        post_args, post_kwargs = connections[1].calls[0]
        self.assertEqual(post_args, ("POST", "/api/player-sharing/initialize-identity"))
        self.assertEqual(post_kwargs["headers"]["Host"], "127.0.0.1:8360")
        self.assertEqual(post_kwargs["headers"]["Origin"], "http://127.0.0.1:8360")
        self.assertEqual(post_kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(post_kwargs["body"], b'{"confirm":true}')
        self.assertNotIn("credential-sentinel", repr(post))
        self.assertNotIn("relay.invalid", repr(post))

    def test_host_api_bounds_response_and_rejects_unknown_action(self) -> None:
        class LargeResponse:
            status = 200

            def read(self, limit: int) -> bytes:
                return b" " * limit

        class Connection:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                return

            def request(self, *_args: object, **_kwargs: object) -> None:
                return

            def getresponse(self) -> LargeResponse:
                return LargeResponse()

            def close(self) -> None:
                return

        client = gate.HostApiClient(connection_factory=Connection)
        with self.assertRaisesRegex(gate.HostApiError, "host_api_response_too_large"):
            client.get_status()
        with self.assertRaisesRegex(gate.HostApiError, "host_api_action_invalid"):
            client.post("delete-identity")

    def test_host_api_refuses_when_owned_port_guard_fails(self) -> None:
        connection_calls: list[object] = []

        def factory(*args: object, **kwargs: object) -> object:
            connection_calls.append((args, kwargs))
            raise AssertionError("must not connect without ownership")

        client = gate.HostApiClient(connection_factory=factory)
        client.bind_ownership_guard(lambda: False)
        with self.assertRaisesRegex(
            gate.HostApiError, "managed_host_ownership_failed"
        ):
            client.get_status()
        self.assertEqual(connection_calls, [])
        with self.assertRaisesRegex(
            gate.HostApiError, "host_api_ownership_guard_invalid"
        ):
            client.bind_ownership_guard(lambda: True)

    def test_verdict_derivation_never_passes_gate_with_linux_blocked(self) -> None:
        all_pass = [{"row_id": row.row_id, "verdict": "PASS"} for row in gate.LIVE_ROWS]
        result = gate.derive_verdicts(all_pass)
        self.assertEqual(result["platform_verdicts"]["macos-arm64"]["verdict"], "PASS")
        self.assertEqual(result["platform_verdicts"]["linux-arm64"]["reason"], "owner-run-required")
        self.assertEqual(result["gate_verdict"], "PENDING")
        self.assertFalse(result["is_gate_pass"])
        blocked = list(all_pass)
        blocked[0] = {"row_id": "L01", "verdict": "BLOCKED"}
        self.assertEqual(
            gate.derive_verdicts(blocked)["platform_verdicts"]["macos-arm64"]["verdict"],
            "BLOCKED",
        )
        failed = list(all_pass)
        failed[0] = {"row_id": "L01", "verdict": "FAIL"}
        self.assertEqual(gate.derive_verdicts(failed)["gate_verdict"], "FAIL")
        duplicate_failure = list(all_pass)
        duplicate_failure[0] = {"row_id": "L01", "verdict": "PASS"}
        duplicate_failure.append({"row_id": "L01", "verdict": "FAIL"})
        self.assertEqual(
            gate.derive_verdicts(duplicate_failure)["gate_verdict"], "FAIL"
        )
        self.assertFalse(gate._bounded_json({"number": float("inf")}))

    def test_all_rows_have_concrete_executors_and_driver_summary_is_not_pass(self) -> None:
        self.assertEqual(set(gate.ROW_EXECUTORS), {row.row_id for row in gate.LIVE_ROWS})
        for row_id, executor in gate.ROW_EXECUTORS.items():
            with self.subTest(row_id=row_id):
                self.assertNotEqual(type(executor).__name__, "PlaceholderRowExecutor")

        class BlockedExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                return gate.RowExecutionResult("BLOCKED", "injected-observation-gap")

        registry = {row.row_id: BlockedExecutor() for row in gate.LIVE_ROWS}
        dependencies = self.make_dependencies(executors=registry)
        result = gate.run_live_gate(dependencies, self.arguments)
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertFalse(result["is_gate_pass"])
        self.assertEqual(result["rows"][0]["row_id"], "L01")
        self.assertEqual(result["rows"][0]["verdict"], "BLOCKED")
        self.assertEqual(result["rows"][0]["reason"], "injected-observation-gap")
        self.assertTrue(all(row["verdict"] == "BLOCKED" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)
        self.assertIn(("POST", ("stop", {})), self.fake_api.calls)
        self.assertTrue(result["evidence_written"])
        capture = self.root / result["evidence_path"]
        self.assertTrue((capture / "run.json").is_file())
        self.assertTrue((capture / "rows.jsonl").is_file())
        self.assertTrue((capture / "summary.json").is_file())
        self.assertTrue((capture / "managed-host-output.json").is_file())
        self.assertTrue((capture / "provider-attempt-ledger.jsonl").is_file())
        self.assertTrue((capture / "SHA256SUMS").is_file())
        run_record = json.loads((capture / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(
            run_record["gate_state_root_id8"], gate._state_root_id8(self.run_id)
        )
        self.assertEqual(
            run_record["gate_state_path_sha256"],
            gate._state_path_sha256(self.state_root_for(self.run_id)),
        )
        for artifact in capture.iterdir():
            if artifact.is_file():
                self.assertNotIn(
                    str(self.state_base), artifact.read_text(encoding="utf-8")
                )

    def test_evidence_checksum_failure_forces_persisted_platform_block(self) -> None:
        class PassingExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                return gate.RowExecutionResult("PASS", "observed")

        registry = {row.row_id: PassingExecutor() for row in gate.LIVE_ROWS}
        with patch.object(gate, "_write_sha256sums", return_value=False):
            result = gate.run_live_gate(
                self.make_dependencies(executors=registry), self.arguments
            )
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertEqual(
            result["platform_verdicts"]["macos-arm64"]["verdict"], "BLOCKED"
        )
        self.assertFalse(result["evidence_written"])
        summary = json.loads(
            (self.root / result["evidence_path"] / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(summary["gate_verdict"], "BLOCKED")
        self.assertEqual(
            summary["platform_verdicts"]["macos-arm64"]["verdict"], "BLOCKED"
        )

    def test_executor_exception_fails_fast_and_teardown_is_always_invoked(self) -> None:
        class ExplodingExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                raise RuntimeError("executor-secret-sentinel")

        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = ExplodingExecutor()
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry), self.arguments
        )
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertIn("executor_exception:L01", result["infrastructure_failures"])
        self.assertEqual(result["rows"][0]["reason"], "executor_exception")
        self.assertTrue(all(row["reason"] == "fail-fast" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)
        self.assertIn(("POST", ("stop", {})), self.fake_api.calls)
        evidence = self.root / result["evidence_path"]
        for path in evidence.iterdir():
            if path.is_file():
                self.assertNotIn("executor-secret-sentinel", path.read_text(encoding="utf-8"))

    def test_counter_cap_breach_stops_after_one_row(self) -> None:
        class PassingExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                return gate.RowExecutionResult("PASS", "observed")

        statuses = [
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 5, "identity_up_invocations": 0}},
        ]
        api = FakeApi(statuses)
        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = PassingExecutor()
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry, api=api), self.arguments
        )
        self.assertIn("companion_launch_cap_breached", result["infrastructure_failures"])
        self.assertEqual(result["rows"][0]["verdict"], "FAIL")
        self.assertTrue(all(row["verdict"] == "BLOCKED" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)

    def test_initial_companion_activity_fails_l01_without_row_dispatch(self) -> None:
        class NeverCalledExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                raise AssertionError("initial companion activity must fail before row")

        api = FakeApi(
            [
                {
                    "ok": True,
                    "status": {
                        "companion_launches": 1,
                        "identity_up_invocations": 0,
                    },
                }
            ]
        )
        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = NeverCalledExecutor()
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry, api=api), self.arguments
        )
        self.assertEqual(result["gate_verdict"], "FAIL")
        self.assertEqual(result["rows"][0]["row_id"], "L01")
        self.assertEqual(result["rows"][0]["verdict"], "FAIL")
        self.assertEqual(result["rows"][0]["reason"], "unexpected_initial_companion_counters")
        self.assertTrue(all(row["verdict"] == "BLOCKED" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)

    def test_counter_cap_is_checked_before_the_next_executor(self) -> None:
        class CountingPassExecutor:
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                self.calls += 1
                return gate.RowExecutionResult("PASS", "observed")

        statuses = [
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 5, "identity_up_invocations": 0}},
        ]
        api = FakeApi(statuses)
        first = CountingPassExecutor()
        later = CountingPassExecutor()
        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = first
        registry["L02"] = later
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry, api=api), self.arguments
        )
        self.assertEqual(first.calls, 1)
        self.assertEqual(later.calls, 0)
        self.assertEqual(result["rows"][1]["reason"], "companion_launch_cap_breached")
        self.assertEqual(result["rows"][1]["verdict"], "FAIL")
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)

    def test_teardown_never_posts_stop_to_unowned_host_port(self) -> None:
        runner = gate.LiveGateRunner(self.dependencies, self.arguments)
        runner.host = FakeHost(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.root / gate.EVIDENCE_BASE / self.run_id / "state",
            self.run_id,
            self.ports,
        )
        runner.api = self.fake_api
        runner.host_attempted = True
        runner.host_started = True
        self.ports.busy_ports.add(gate.HOST_PORT)
        runner._teardown()
        self.assertFalse(runner.teardown["sharing_stop_attempted"])
        self.assertFalse(any(call[0] == "POST" for call in self.fake_api.calls))
        self.assertIn("sharing_teardown_failed", runner.infrastructure_failures)

    def test_teardown_stops_sharing_when_failed_start_left_owned_listener(self) -> None:
        runner = gate.LiveGateRunner(self.dependencies, self.arguments)
        runner.host = FakeHost(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.root / gate.EVIDENCE_BASE / self.run_id / "state",
            self.run_id,
            self.ports,
        )
        runner.api = self.fake_api
        self.ports.host_pid = runner.host.owner_pid
        runner.host_started = False
        runner._teardown()
        self.assertTrue(runner.teardown["sharing_stop_attempted"])
        self.assertIn(("POST", ("stop", {})), self.fake_api.calls)

    def test_counter_totals_include_restarted_host_epochs(self) -> None:
        runner = gate.LiveGateRunner(self.dependencies, self.arguments)
        runner.host = FakeHost(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.root / gate.EVIDENCE_BASE / self.run_id / "state",
            self.run_id,
            self.ports,
        )
        runner._observe_counter_sample(
            {"companion_launches": 4, "identity_up_invocations": 1}
        )
        runner._observe_counter_sample(
            {"companion_launches": 5, "identity_up_invocations": 1}
        )
        runner.host.owner_pid = 555
        runner._observe_counter_sample(
            {"companion_launches": 0, "identity_up_invocations": 0}
        )
        runner._observe_counter_sample(
            {"companion_launches": 1, "identity_up_invocations": 0}
        )
        self.assertEqual(
            runner.cumulative_counters,
            {"companion_launches": 6, "identity_up_invocations": 1},
        )
        with self.assertRaisesRegex(gate.GateError, "host_counters_regressed"):
            runner._observe_counter_sample(
                {"companion_launches": 0, "identity_up_invocations": 0}
            )

    def test_provider_ledger_reservation_is_fail(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        ledger = Path(
            gate.build_host_environment(sandbox, state, self.run_id)[
                "NEQ_PROVIDER_ATTEMPT_LEDGER"
            ]
        )
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"event": "header", "schema_version": 1, "budget": 1, "run_id": self.run_id})
            + "\n"
            + json.dumps({"event": "activated", "schema_version": 1, "budget": 1, "run_id": self.run_id, "transport_guard": "httpx-client-single-request", "pid": 444})
            + "\n"
            + json.dumps({"event": "reservation", "schema_version": 1, "budget": 1, "run_id": self.run_id, "reservation_number": 1, "pid": 444, "host": "provider-secret.example"})
            + "\n",
            encoding="ascii",
        )
        result = gate._validate_provider_ledger(
            ledger, self.run_id, expected_pids=[444]
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["reservation_count"], 1)

    def test_provider_ledger_activations_follow_listener_pid_sequence(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        ledger = Path(
            gate.build_host_environment(sandbox, state, self.run_id)[
                "NEQ_PROVIDER_ATTEMPT_LEDGER"
            ]
        )
        ledger.parent.mkdir(parents=True, exist_ok=True)
        record_base = {
            "schema_version": 1,
            "budget": 1,
            "run_id": self.run_id,
        }
        records = [
            {"event": "header", **record_base},
            {
                "event": "activated",
                **record_base,
                "pid": 445,
                "transport_guard": "httpx-client-single-request",
            },
            {
                "event": "activated",
                **record_base,
                "pid": 447,
                "transport_guard": "httpx-client-single-request",
            },
        ]
        ledger.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="ascii",
        )
        result = gate._validate_provider_ledger(
            ledger, self.run_id, expected_pids=[445, 447]
        )
        self.assertEqual(result["activation_count"], 2)
        with self.assertRaisesRegex(gate.GateError, "provider_ledger_invalid"):
            gate._validate_provider_ledger(
                ledger, self.run_id, expected_pids=[444, 445]
            )
        reused_pid_records = records[:2] + [dict(records[1])]
        ledger.write_text(
            "".join(
                json.dumps(record) + "\n" for record in reused_pid_records
            ),
            encoding="ascii",
        )
        reused = gate._validate_provider_ledger(
            ledger, self.run_id, expected_pids=[445, 445]
        )
        self.assertEqual(reused["activation_count"], 2)

    def test_provider_ledger_rejects_boolean_counts_and_symlinks(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        ledger = Path(
            gate.build_host_environment(sandbox, state, self.run_id)[
                "NEQ_PROVIDER_ATTEMPT_LEDGER"
            ]
        )
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"event": "header", "schema_version": True, "budget": 1, "run_id": self.run_id})
            + "\n"
            + json.dumps({"event": "activated", "schema_version": 1, "budget": 1, "run_id": self.run_id, "transport_guard": "httpx-client-single-request", "pid": 444})
            + "\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(gate.GateError, "provider_ledger_preexisting"):
            gate._validate_provider_ledger_target(
                sandbox, self.run_id, must_not_exist=True
            )
        with self.assertRaisesRegex(gate.GateError, "provider_ledger_identity_mismatch"):
            gate._validate_provider_ledger(
                ledger, self.run_id, expected_pids=[444]
            )
        ledger.unlink()
        outside = self.root / "tmp" / "provider-ledger-outside.jsonl"
        outside.write_text("{}\n", encoding="ascii")
        ledger.symlink_to(outside)
        with self.assertRaises(gate.GateError):
            gate._validate_provider_ledger(
                ledger, self.run_id, expected_pids=[444]
            )

    def test_evidence_redacts_urls_credentials_cookies_and_tunnel_ids(self) -> None:
        evidence = {
            "invitation_url": "https://public-secret.invalid/invite",
            "tunnel_id": "tunnel-id-secret-sentinel",
            "credential": "credential-secret-sentinel",
            "cookie": "cookie-secret-sentinel",
            "note": "credential=inline-secret-sentinel",
        }
        redacted = gate.redact_live_evidence(
            evidence,
            [
                "https://public-secret.invalid/invite",
                "tunnel-id-secret-sentinel",
                "credential-secret-sentinel",
                "cookie-secret-sentinel",
                "inline-secret-sentinel",
            ],
        )
        serialized = json.dumps(redacted)
        for sentinel in (
            "public-secret.invalid",
            "tunnel-id-secret-sentinel",
            "credential-secret-sentinel",
            "cookie-secret-sentinel",
            "inline-secret-sentinel",
        ):
            self.assertNotIn(sentinel, serialized)

    def test_host_harness_start_readiness_stop_escalation_and_port_discipline(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.state_root_for(self.run_id)
        ports = FakePortInspector()
        process = FakeProcess()
        server_pid = 202
        factory_calls: list[tuple[list[str], dict[str, object]]] = []
        clock = [10.0]
        readiness = [False, True]

        def process_factory(command: list[str], **kwargs: object) -> FakeProcess:
            factory_calls.append((command, kwargs))
            ports.host_pid = server_pid
            return process

        def ready() -> bool:
            return readiness.pop(0) if readiness else True

        def sleep(seconds: float) -> None:
            clock[0] += seconds

        signalled: list[int] = []

        def signal_group(pgid: int, selected_signal: int) -> None:
            signalled.append(selected_signal)
            if selected_signal == signal.SIGKILL:
                process.returncode = -signal.SIGKILL
                ports.host_pid = None

        getpgid_calls: list[int] = []

        def getpgid(pid: int) -> int:
            getpgid_calls.append(pid)
            return process.pid

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=ready,
            signal_group=signal_group,
            getpgid=getpgid,
            monotonic=lambda: clock[0],
            sleep=sleep,
            start_timeout=1,
            stop_timeout=0.3,
            poll_interval=0.1,
        )
        self.assertTrue(host.start())
        self.assertEqual(host.owner_pid, server_pid)
        self.assertEqual(host.launcher_pid, process.pid)
        self.assertEqual(host.owned_pids, [process.pid, server_pid])
        command, options = factory_calls[0]
        self.assertEqual(
            command,
            [str(self.root / ".venv" / "bin" / "python"), "-c", "import run_web; run_web.main()"],
        )
        self.assertEqual(options["cwd"], str(sandbox))
        self.assertTrue(options["start_new_session"])
        self.assertFalse(options["shell"])
        self.assertEqual(options["env"], host.environment)
        self.assertEqual(options["env"]["NEQ_OPEN_BROWSER"], "0")
        self.assertEqual(options["env"]["NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS"], "1")
        self.assertTrue(host.stop())
        self.assertEqual(host.owner_pid, None)
        self.assertEqual(host.launcher_pid, None)
        self.assertEqual(host.owned_pids, [process.pid, server_pid])
        self.assertEqual(getpgid_calls, [server_pid])
        self.assertEqual(signalled, [signal.SIGTERM, signal.SIGKILL])
        self.assertTrue(all(port in {8360, 8370} for port in ports.seen))
        snapshot = host.output.snapshot()
        self.assertFalse(snapshot["raw_output_retained"])
        output = json.dumps(snapshot)
        self.assertNotIn("stdout-secret-sentinel", output)
        self.assertNotIn("stderr-secret-sentinel", output)
        self.assertGreater(snapshot["processes"][0]["stdout"]["bytes_observed"], 0)

    def test_host_harness_rejects_listener_outside_launcher_process_group(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.state_root_for(self.run_id)
        ports = FakePortInspector()
        process = FakeProcess(pid=501, term_exits=True)
        server_pid = 502

        def process_factory(_command: list[str], **_kwargs: object) -> FakeProcess:
            ports.host_pid = server_pid
            return process

        def signal_group(_pgid: int, _signal: int) -> None:
            process.returncode = 0
            ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=lambda: True,
            signal_group=signal_group,
            getpgid=lambda _pid: 777,
            monotonic=lambda: 100.0,
            sleep=lambda _seconds: None,
            stop_timeout=0.1,
            poll_interval=0.05,
        )
        with self.assertRaisesRegex(
            gate.GateError, "managed_host_port_ownership_failed"
        ):
            host.start()
        self.assertEqual(host.launcher_pid, None)
        self.assertEqual(host.owner_pid, None)
        self.assertEqual(host.owned_pids, [process.pid])
        self.assertIsNotNone(process.returncode)

    def test_host_harness_term_success_avoids_sigkill(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.state_root_for(self.run_id)
        ports = FakePortInspector()
        process = FakeProcess(term_exits=True)
        server_pid = 401

        def process_factory(_command: list[str], **_kwargs: object) -> FakeProcess:
            ports.host_pid = server_pid
            return process

        def signal_group(_pgid: int, selected_signal: int) -> None:
            if selected_signal == signal.SIGTERM:
                process.returncode = 0
                ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=lambda: True,
            signal_group=signal_group,
            getpgid=lambda pid: process.pid if pid == server_pid else -1,
            monotonic=lambda: 100.0,
            sleep=lambda _seconds: None,
            stop_timeout=0.1,
            poll_interval=0.05,
        )
        self.assertTrue(host.start())
        self.assertTrue(host.stop())

    def test_host_harness_restarts_owned_process_with_same_private_state_tree(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.state_root_for(self.run_id)
        ports = FakePortInspector()
        processes = [
            FakeProcess(pid=201, term_exits=True),
            FakeProcess(pid=202, term_exits=True),
        ]
        server_pids = [301, 302]
        by_pid = {process.pid: process for process in processes}
        server_to_launcher = dict(zip(server_pids, (201, 202)))
        factory_calls = 0

        def process_factory(_command: list[str], **_kwargs: object) -> FakeProcess:
            nonlocal factory_calls
            process = processes[factory_calls]
            ports.host_pid = server_pids[factory_calls]
            factory_calls += 1
            return process

        def signal_group(pgid: int, selected_signal: int) -> None:
            if selected_signal == signal.SIGTERM:
                by_pid[pgid].returncode = 0
                ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=lambda: True,
            signal_group=signal_group,
            getpgid=lambda pid: server_to_launcher.get(pid, -1),
            monotonic=lambda: 100.0,
            sleep=lambda _seconds: None,
            stop_timeout=0.1,
            poll_interval=0.05,
        )
        self.assertTrue(host.start())
        self.assertTrue(host.stop())
        state_identity = (state.stat().st_dev, state.stat().st_ino)
        self.assertTrue(host.start())
        self.assertTrue(host.stop())
        self.assertEqual(host.process_generation, 2)
        self.assertEqual(host.owned_pids, [201, 301, 202, 302])
        self.assertEqual(host.listener_pids, [301, 302])
        self.assertEqual(host.owner_pid, None)
        self.assertEqual((state.stat().st_dev, state.stat().st_ino), state_identity)
        self.assertEqual(factory_calls, 2)

    def test_host_harness_refuses_replaced_private_state_tree_on_restart(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.state_root_for(self.run_id)
        ports = FakePortInspector()
        process = FakeProcess(pid=301, term_exits=True)
        server_pid = 401

        def process_factory(_command: list[str], **_kwargs: object) -> FakeProcess:
            ports.host_pid = server_pid
            return process

        def signal_group(_pgid: int, selected_signal: int) -> None:
            if selected_signal == signal.SIGTERM:
                process.returncode = 0
                ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=lambda: True,
            signal_group=signal_group,
            getpgid=lambda pid: process.pid if pid == server_pid else -1,
            monotonic=lambda: 100.0,
            sleep=lambda _seconds: None,
            stop_timeout=0.1,
            poll_interval=0.05,
        )
        self.assertTrue(host.start())
        self.assertTrue(host.stop())
        original_root = state.rename(state.with_name("gate-state-original"))
        state.mkdir(mode=0o700)
        with self.assertRaisesRegex(gate.GateError, "gate_state_root_invalid"):
            host.start()
        self.assertTrue(original_root.is_dir())
        self.assertTrue(host.process is None)

    def test_host_harness_refuses_ports_without_touching_8357(self) -> None:
        ports = FakePortInspector()
        ports.busy_ports.add(gate.HOST_PORT)
        host = gate.ManagedHostHarness(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.state_root_for(self.run_id),
            self.run_id,
            process_factory=lambda *_args, **_kwargs: self.fail("must not spawn"),
            port_inspector=ports,
            readiness_probe=lambda: True,
        )
        self.assertFalse(host.start())
        self.assertNotIn(8357, ports.seen)


if __name__ == "__main__":
    unittest.main()
