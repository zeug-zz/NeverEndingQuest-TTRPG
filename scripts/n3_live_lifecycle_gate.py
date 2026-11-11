# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Primary-owned live N3 lifecycle driver core.

This driver is intentionally fail-closed. The live row executors remain
placeholders until Tasks 6.5 and 6.6; a placeholder can never produce PASS.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import http.client
import io
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import tokenize
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


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_ID = "N3-live"
MANIFEST_ID = "n3-live-lifecycle-v1"
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
        "Sharing is off; port 8370 is not listening; no companion process exists; there is no public exposure.",
        "Host ownership or the required status/listener/process/public-exposure observations cannot be established safely. Any positive evidence of an unexpected listener, companion, or public exposure is FAIL.",
    ),
    LiveRow(
        "L02", "identity-init-once", 300,
        "Owned host is up; the dedicated profile identity is uninitialized; sharing is OFF.",
        "POST initialize-identity with {confirm:true}, then call it a second time.",
        "The first call initializes only after a real guarded up -> status -> down; post-checks show no residual helper or service-manager entry. The second call returns already_initialized and causes zero new up invocations.",
        "The companion operation or positive post-checks for helper/service-manager cleanup cannot be performed or observed safely. A failed/extra up, missing cleanup, or unexpected second initialization is FAIL.",
    ),
    LiveRow(
        "L03", "issue-access-start-auth-entry", 300,
        "Owned host is up; identity initialization has passed; sharing is OFF.",
        "Issue access, start sharing, copy the invitation, and exercise the player boundary over the public URL. Keep the one-time plaintext credential and invitation URL in memory only.",
        "Issue-access returns plaintext once; start returns ready; copy-invitation returns an HTTPS URL. Over that PUBLIC URL, the player shell returns 200; an unauthenticated protected request returns 401/403; host-only paths and host socket events are refused/404 under the public Host. Login with the credential and exact Host/Origin succeeds and the cookie has Secure, HttpOnly, and SameSite. An authenticated Socket.IO websocket to /player receives initial state. A wrong credential is rejected and a forged Origin is rejected.",
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
        "Status becomes degraded within the health interval; the invitation is withdrawn and copy-invitation is refused; the public URL stops serving the player; bounded recovery returns to ready within the overridden policy; host port 8360 health remains unaffected throughout. Document sessions after recovery; re-authentication is required. The expected result is recovered ready; observed bounded failed/exhausted recovery is FAIL.",
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
        "Stop sharing; stop the host; delete the gate remote tunnel identity using the installed companion's delete --yes with the gate profile environment only; verify deletion via status; verify ports are free and no run processes remain; remove the gate state root; verify the public URL is unreachable afterwards.",
        "The gate remote identity is deleted and confirmed absent; ports are free; no run processes remain; the gate state root is removed; the public URL is unreachable; the installed companion remains in place.",
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


def live_manifest() -> dict[str, object]:
    """Return a fresh JSON-compatible projection of the frozen live contract."""
    return {
        "manifest_id": MANIFEST_ID,
        "party_size": 1,
        "platforms": list(APPROVED_PLATFORMS),
        "host": {"host": "127.0.0.1", "port": HOST_PORT},
        "player": {"host": "127.0.0.1", "port": PLAYER_PORT},
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
FROZEN_MANIFEST_SHA256 = "7a06f3e17ec96f442dfcabb6ef1c43410ab1330d39a1cac1c77ff5c12bde8e02"


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
    secrets: list[str] = field(default_factory=list)

    def remember_secret(self, value: object) -> None:
        if isinstance(value, str) and len(value) >= 3 and value not in self.secrets:
            self.secrets.append(value)


class PlaceholderRowExecutor:
    """Fail-closed placeholder to be replaced by Tasks 6.5 and 6.6."""

    def __init__(self, row_id: str, name: str) -> None:
        self.row_id = row_id
        self.name = name

    def execute(self, _context: RowContext) -> RowExecutionResult:
        return RowExecutionResult("BLOCKED", "executor-not-implemented")


ROW_EXECUTORS: Mapping[str, RowExecutor] = MappingProxyType(
    {
        row.row_id: PlaceholderRowExecutor(row.row_id, row.name)
        for row in LIVE_ROWS
    }
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
        "XDG_STATE_HOME": state_root / "state",
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
        elif not _private_state_tree_matches(
            self.state_root, self._state_root_identity
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
    host_factory: Callable[[Path, Path, str], ManagedHostHarness]
    api_factory: Callable[[], HostApiClient]
    executor_registry: Mapping[str, RowExecutor] = ROW_EXECUTORS
    monotonic: Callable[[], float] = time.monotonic
    utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def _default_dependencies(root: Path) -> LiveGateDependencies:
    return LiveGateDependencies(
        root=root,
        identity_reader=preflight_gate.read_workspace_identity,
        port_inspector=preflight_gate.SystemPortInspector(),
        preflight_reader=load_preflight_report,
        companion_verifier=verify_installed_companion,
        sandbox_validator=validate_prepared_sandbox,
        host_factory=lambda sandbox, state, run_id: ManagedHostHarness(
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


def _validate_run_paths(root: Path, arguments: RunArguments) -> tuple[Path, Path, Path]:
    run_root = root / EVIDENCE_BASE / arguments.run_id
    capture_dir = run_root / "capture"
    state_root = run_root / "state"
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
    if state_root.exists() or state_root.is_symlink():
        raise GateError("gate_state_root_exists")
    return run_root, capture_dir, state_root


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
        for name in ("home", "config", "data", "state", "cache", "runtime", "tmp"):
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
    created_identity: tuple[int, int] | None = None
    created = False
    try:
        state_root.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = True
        root_info = state_root.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise GateError("gate_state_root_invalid")
        created_identity = (root_info.st_dev, root_info.st_ino)
        for name in ("home", "config", "data", "state", "cache", "runtime", "tmp"):
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
        if not cleanup_ok:
            raise GateError("gate_state_cleanup_failed") from None
        raise


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
            self.host = self.dependencies.host_factory(
                self.dependencies.root, self.dependencies.root / CAPTURE_RELATIVE,
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
            self.run_root, self.capture_dir, self.state_root = _validate_run_paths(
                self.dependencies.root, self.arguments
            )
        except GateError:
            raise
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
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise GateError("companion_digest_invalid")
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
