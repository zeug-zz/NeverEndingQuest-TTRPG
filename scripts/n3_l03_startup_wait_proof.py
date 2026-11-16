# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free proof for the N3 L03 startup-wait real-runtime signal.

The live L03 gate row's startup wait (scripts/n3_live_lifecycle_gate.py,
_start_local_game_runtime) now treats the real host as alive once a
Socket.IO status_response reports game_started=True, instead of the
/api/player-sharing/status "local_runtime" flag, which only ever becomes
True once player sharing is turned ON -- something the startup wait never
does. This script demonstrates that signal honestly, without ever placing a
real call to an LLM provider:

  * --self-test (this agent may run this): drives the real gate driver
    function, scripts.n3_live_lifecycle_gate._start_local_game_runtime,
    against a synthetic in-process socket/HTTP host built entirely in this
    script. No real host, sandbox, or network is used. It proves this
    script's own Socket.IO-adapter and loopback-HTTP-adapter plumbing is
    correct, and that the driver's status_response based wait genuinely
    depends on a real game_started flip rather than any local_runtime flag.
    scripts.n3_live_lifecycle_gate (the "gate" module) is imported lazily,
    only inside the --self-test functions that need it, because importing it
    at module scope pulls web.extensions.opentunnel_sharing.native_process_info
    and therefore the repository's web/utils packages into this process's
    sys.modules -- which real-host mode must never do (see below).

  * real-host mode (this agent must NOT run this; the primary runs it):
    delegates the entire sandboxed real-host lifecycle -- egress guard,
    provider SDK/process-launch tripwires, router stubbing of only the two
    expected startup tasks (action_prediction, dm_main), sandboxed import of
    web.web_interface, the real Socket.IO start_game/request_status
    exchange, and teardown -- to the already-reviewed, UNMODIFIED call
    contract of n3_start_game_offline_proof.run_startup_diagnostic(), which
    this script does not duplicate. No host_importer is ever passed: passing
    one marks "real_host_imports" unverified in that tool's own report
    (real_host_importer = host_importer is None), which would make the
    diagnostic's own verdict BLOCKED for a reason unrelated to this proof.
    Instead this script passes only the new, optional, exception-safe
    observe_running_host keyword that run_startup_diagnostic() now exposes
    (default None, byte-identical behavior otherwise). That hook,
    observe_real_host() below, is called by the diagnostic itself, with its
    own real Socket.IO test client and the real imported web module, and
    never imports scripts.n3_live_lifecycle_gate or any other repository
    module; it only uses the client/web_module objects it is given.

    Because the diagnostic must run in a process that has never imported the
    repository's web/utils packages, and this script's own module-level code
    (argument parsing, this docstring's self-test description) must remain
    importable without triggering that import either, real-host mode runs as
    a parent process plus a short-lived worker subprocess, mirroring
    n3_start_game_offline_proof.py's own --diagnostic-worker split:

      1. The parent (run_real_host_proof) validates arguments, runs
         n3_start_game_offline_proof.run_guard_self_test() exactly as that
         script's own main() does, resolves this proof's own bounded result
         path and refuses to proceed if it already exists, then launches a
         fresh worker interpreter (same executable, this script's own path
         with --worker, cwd=REPO_ROOT, a credential-free environment from
         n3_start_game_offline_proof._startup_diagnostic_worker_environment(),
         stdin/stdout/stderr discarded) under a bounded timeout.
      2. The worker (this script's own --worker branch) is a fresh process
         that has never imported the gate module; it calls
         run_startup_diagnostic(..., observe_running_host=observe_real_host,
         isolated_worker=True) directly, composes a small, strictly bounded
         verdict mapping from that diagnostic's own report, and writes only
         that bounded mapping to this proof's own result file (the full
         diagnostic report is written separately, by run_startup_diagnostic
         itself, under startup_diagnostic.json next to it).
      3. The parent reads that result file back, re-validates its size and
         re-validates every field against a strict key/type allowlist
         (_validate_worker_result), and only then trusts and prints it. A
         worker crash, timeout, missing file, oversized file, or malformed
         file all resolve to an explicit BLOCKED verdict from the parent,
         never a silent pass.

    This script's own final verdict is PASS only if the diagnostic's own
    verdict is PASS AND the hook's recorded status_response.game_started is
    True AND the hook's recorded local_runtime -- read from the real route's
    production response shape, status.checks.local_runtime, never from a
    top-level status.local_runtime that does not exist -- is False AND no
    provider/network attempt was ever counted by the diagnostic; otherwise it
    reports BLOCKED or FAIL with an explicit fixed reason, with bounded
    attribution detail (HTTP status, JSON-decoded, status/checks presence,
    and a fixed local_runtime reason string such as http_error, json_invalid,
    status_missing, checks_missing, or non_bool) carried in the observation
    and surfaced as sharing_local_runtime_reason in this proof's own result. This script never
    re-runs the gate driver's own _start_local_game_runtime against this real
    host: doing so would require a second, separate real game start, hitting
    the host's "already starting or running" guard. The driver function's
    own code path -- the status_response rule, the fail-closed bounded wait,
    and its real-signal observed() diagnostics -- is instead proved by this
    script's --self-test, against a synthetic but behaviorally faithful
    in-process host. This script never asserts, implies, or stands in for a
    live L03 gate PASS, and it does not replace the required live L03 gate
    row.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from scripts import n3_start_game_offline_proof as offline_proof


DEFAULT_OUTPUT_PARENT = Path("tmp/router-rollout/v2-network/n3/l03-startup-wait-proof")
DEFAULT_RUN_ID = "l03-startup-wait-proof-a"
PROOF_ORIGIN = offline_proof.PROOF_ORIGIN
SHARING_STATUS_PATH = "/api/player-sharing/status"
MAX_PROOF_RESULT_BYTES = 1024 * 1024
MAX_WORKER_RESULT_STRING_LENGTH = 500

# Mirrors scripts.n3_live_lifecycle_gate.HOST_PORT. Duplicated as a plain
# literal (never imported from the gate module) so that neither real-host
# mode nor its worker subprocess ever imports scripts.n3_live_lifecycle_gate,
# which would pull the repository's web/utils packages into this process.
_HOST_PORT = 8360

_WORKER_RESULT_BOOL_FIELDS = (
    "status_response_game_started",
    "sharing_local_runtime_false",
    "no_network_attempts",
)
_WORKER_RESULT_OPTIONAL_STRING_FIELDS = (
    "diagnostic_verdict",
    "observation_failure",
    "sharing_local_runtime_reason",
)
_WORKER_RESULT_REQUIRED_STRING_FIELDS = ("verdict", "reason", "diagnostic_report_path")
_WORKER_RESULT_ALLOWED_KEYS = frozenset(
    _WORKER_RESULT_BOOL_FIELDS
    + _WORKER_RESULT_OPTIONAL_STRING_FIELDS
    + _WORKER_RESULT_REQUIRED_STRING_FIELDS
    + ("network_attempt_count",)
)
_WORKER_RESULT_VERDICTS = ("PASS", "BLOCKED", "FAIL")


def resolve_output_file(
    output_dir: Optional[str | Path],
    run_id: str,
    repo_root: Path = offline_proof.REPO_ROOT,
) -> Path:
    """Resolve a report file under repository tmp; mirrors the offline proof's
    resolve_output_file but with this script's own default output parent."""
    safe_run_id = offline_proof.validate_run_id(run_id)
    repo = repo_root.resolve(strict=True)
    tmp_root = repo / "tmp"
    if not tmp_root.is_dir() or tmp_root.is_symlink():
        raise ValueError("repository tmp directory is unavailable")
    if output_dir is None:
        supplied = DEFAULT_OUTPUT_PARENT / safe_run_id / "proof.json"
    else:
        supplied = Path(output_dir)
        if supplied.suffix.lower() != ".json":
            supplied = supplied / "proof.json"
    candidate = offline_proof._absolute_lexical_path(supplied, repo)
    offline_proof._reject_symlink_components(candidate, tmp_root)
    try:
        candidate.resolve(strict=False).relative_to(tmp_root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("proof output must be below repository tmp") from exc
    return candidate


class SocketIOEventAdapter:
    """Adapts a Socket.IO test-client-shaped object (an object exposing
    .emit(name, *args) and .get_received() -> [{"name":..., "args":[...]}])
    to the on/connect/emit/connected surface that the live gate driver's
    _start_local_game_runtime expects from host_socket_client_factory."""

    def __init__(self, test_client: Any) -> None:
        self._client = test_client
        self._handlers: dict[str, list[Callable[..., None]]] = {}
        self.connected = False

    def on(self, event: str, handler: Callable[..., None], namespace: Any = None) -> None:
        del namespace
        self._handlers.setdefault(event, []).append(handler)

    def connect(self, url: str, **kwargs: Any) -> None:
        del url, kwargs
        self.connected = True
        self._drain()

    def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self._client.emit(event, *args)
        self._drain()

    def disconnect(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self.connected = False

    def _drain(self) -> None:
        for received in self._client.get_received():
            if not isinstance(received, Mapping):
                continue
            name = received.get("name")
            args = received.get("args")
            if not isinstance(args, (list, tuple)):
                args = ()
            for handler in tuple(self._handlers.get(name, ())):
                handler(*args)


class _LoopbackHttpResponse:
    """Minimal http.client.HTTPResponse-shaped wrapper used only by
    HostApiLoopbackConnection.getresponse()."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, _max_bytes: int = -1) -> bytes:
        del _max_bytes
        return self._body


class HostApiLoopbackConnection:
    """Bridges HostApiClient's http.client.HTTPConnection usage to a real,
    in-process Flask test client -- real production route code, but zero
    real sockets and zero real network. Pass this as HostApiClient's
    connection_factory."""

    def __init__(
        self,
        flask_test_client: Any,
        host: str = "127.0.0.1",
        port: int = _HOST_PORT,
        *,
        timeout: float | None = None,
    ) -> None:
        del host, port, timeout
        self._flask_client = flask_test_client
        self._method: str | None = None
        self._path: str | None = None
        self._body: bytes | None = None
        self._headers: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._method = method
        self._path = path
        self._body = body
        self._headers = dict(headers or {})

    def getresponse(self) -> _LoopbackHttpResponse:
        if self._method == "GET":
            response = self._flask_client.get(self._path, headers=self._headers)
        else:
            response = self._flask_client.post(
                self._path,
                data=self._body,
                headers=self._headers,
                content_type=self._headers.get("Content-Type", "application/json"),
            )
        return _LoopbackHttpResponse(response.status_code, response.get_data())

    def close(self) -> None:
        return None


def host_api_loopback_factory(
    flask_test_client: Any,
) -> Callable[..., HostApiLoopbackConnection]:
    def factory(host: str, port: int, *, timeout: float | None = None) -> HostApiLoopbackConnection:
        return HostApiLoopbackConnection(flask_test_client, host, port, timeout=timeout)

    return factory


def _sharing_status_projection(flask_test_client: Any) -> dict[str, Any]:
    """Call the real /api/player-sharing/status route and return a small,
    bounded diagnostic mapping about it, so that any failure to read
    local_runtime is attributable instead of silently defaulting. The
    production response shape (web/routes/player_sharing_routes.py,
    _status_projection) is {"ok": bool, "status": {"checks":
    {"local_runtime": bool, ...}, ...}} -- local_runtime lives under
    status.checks, never at the top level of status. Never raises for an
    HTTP error, invalid JSON, or an unexpected shape: each resolves to a
    fixed, named local_runtime reason string instead."""
    response = flask_test_client.get(
        SHARING_STATUS_PATH,
        headers={"Host": "127.0.0.1:%d" % _HOST_PORT},
    )
    http_status = getattr(response, "status_code", None)
    http_status = http_status if isinstance(http_status, int) else 0
    if http_status != 200:
        return {
            "http_status": http_status,
            "json_decoded": False,
            "ok": False,
            "status_present": False,
            "checks_present": False,
            "local_runtime": "http_error",
        }
    try:
        decoded = json.loads(response.get_data().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {
            "http_status": http_status,
            "json_decoded": False,
            "ok": False,
            "status_present": False,
            "checks_present": False,
            "local_runtime": "json_invalid",
        }
    ok = isinstance(decoded, dict) and decoded.get("ok") is True
    status = decoded.get("status") if isinstance(decoded, dict) else None
    if not isinstance(status, dict):
        return {
            "http_status": http_status,
            "json_decoded": True,
            "ok": ok,
            "status_present": False,
            "checks_present": False,
            "local_runtime": "status_missing",
        }
    checks = status.get("checks")
    if not isinstance(checks, dict):
        return {
            "http_status": http_status,
            "json_decoded": True,
            "ok": ok,
            "status_present": True,
            "checks_present": False,
            "local_runtime": "checks_missing",
        }
    local_runtime_raw = checks.get("local_runtime")
    local_runtime = local_runtime_raw if isinstance(local_runtime_raw, bool) else "non_bool"
    return {
        "http_status": http_status,
        "json_decoded": True,
        "ok": ok,
        "status_present": True,
        "checks_present": True,
        "local_runtime": local_runtime,
    }


def drive_status_response_proof(
    context: Any,
    socket_adapter: SocketIOEventAdapter,
    flask_test_client: Any,
) -> dict[str, Any]:
    """Run the real gate driver's _start_local_game_runtime against the
    given adapters and record the real status_response/game_started/
    local_runtime signal evidence around it. Self-test only: imports the
    gate module lazily, never at this script's module scope."""
    from scripts import n3_live_lifecycle_gate as gate

    status_response_history: list[dict[str, Any]] = []

    def record_status_response(*args: Any) -> None:
        payload = args[0] if args else None
        if isinstance(payload, Mapping):
            status_response_history.append(dict(payload))

    socket_adapter.on("status_response", record_status_response)

    pre_sharing_status = _sharing_status_projection(flask_test_client)
    socket_adapter.connect(
        "http://127.0.0.1:%d" % gate.HOST_PORT,
        headers={"Origin": gate.HOST_SOCKET_ORIGIN},
        transports=["polling"],
        wait=True,
        wait_timeout=1.0,
        retry=False,
    )
    socket_adapter.emit("request_status")
    pre_status_response = dict(status_response_history[-1]) if status_response_history else None

    observed, failure = gate._start_local_game_runtime(context)

    socket_adapter.emit("request_status")
    post_status_response = dict(status_response_history[-1]) if status_response_history else None
    post_sharing_status = _sharing_status_projection(flask_test_client)

    return {
        "driver_observed": dict(observed) if observed is not None else None,
        "driver_failure": {
            "verdict": failure.verdict,
            "reason": failure.reason,
            "observed": dict(failure.observed),
        }
        if failure is not None
        else None,
        "pre_status_response": pre_status_response,
        "post_status_response": post_status_response,
        "status_response_count": len(status_response_history),
        "pre_sharing_status_local_runtime": pre_sharing_status.get("local_runtime"),
        "post_sharing_status_local_runtime": post_sharing_status.get("local_runtime"),
    }


# ---------------------------------------------------------------------------
# Self-test: pure synthetic, zero real host, zero sandbox, zero network.
# ---------------------------------------------------------------------------


class _SelfTestSocketHost:
    """A minimal, entirely synthetic Socket.IO-test-client-shaped host used
    only by run_self_test(). Simulates the real host's observable behavior:
    status_response.game_started flips False -> True once "start_game" is
    received, and never depends on player-sharing local_runtime."""

    def __init__(self) -> None:
        self.game_started = False
        self._pending: list[dict[str, Any]] = []
        self.disconnected = False
        self.receipts_dir: Path | None = None

    def emit(self, name: str, *args: Any) -> None:
        if name == "request_status":
            self._pending.append(
                {
                    "name": "status_response",
                    "args": [
                        {
                            "message": "ok",
                            "is_processing": False,
                            "game_started": self.game_started,
                            "game_starting": False,
                        }
                    ],
                }
            )
            return
        if name == "start_game":
            self.game_started = True
            self._pending.append(
                {"name": "game_started", "args": [{"message": "Game started successfully"}]}
            )
            self._pending.append(
                {"name": "game_output", "args": [{"content": "self-test narration"}]}
            )
            return
        raise AssertionError("unexpected self-test emit: " + name)

    def get_received(self) -> list[dict[str, Any]]:
        pending = self._pending
        self._pending = []
        return pending

    def disconnect(self) -> None:
        self.disconnected = True


class _SelfTestFlaskClient:
    """A minimal, entirely synthetic Flask-test-client-shaped object proving
    HostApiLoopbackConnection's bridging logic without any real Flask app.
    Always reports local_runtime=False, matching the real
    web/extensions/opentunnel_sharing/service.py behavior while sharing is
    off -- the exact condition the old local_runtime rule relied on and the
    status_response rule does not."""

    class _Response:
        def __init__(self, status_code: int, body: bytes) -> None:
            self.status_code = status_code
            self._body = body

        def get_data(self) -> bytes:
            return self._body

    def get(self, path: str, *, headers: Mapping[str, str] | None = None) -> "_SelfTestFlaskClient._Response":
        del headers
        if path != SHARING_STATUS_PATH:
            raise AssertionError("unexpected self-test GET path: " + path)
        payload = {
            "ok": True,
            "status": {
                "state": "off",
                "checks": {"local_runtime": False},
            },
        }
        body = json.dumps(payload, ensure_ascii=True).encode("ascii")
        return self._Response(200, body)

    def post(self, *args: Any, **kwargs: Any) -> "_SelfTestFlaskClient._Response":
        raise AssertionError("self-test never issues a POST request")


class _SteppedClock:
    """A fake monotonic clock that advances by a fixed step on every read,
    so the driver's bounded poll loop terminates quickly without any real
    sleeping."""

    def __init__(self, *, start: float = 1_000.0, step: float = 0.3) -> None:
        self._value = start
        self._step = step

    def __call__(self) -> float:
        current = self._value
        self._value += self._step
        return current


def _write_self_test_ledger(sandbox_root: Path, run_id: str, owner_pid: int) -> None:
    """Self-test only: imports the gate module lazily, never at this
    script's module scope."""
    from scripts import n3_live_lifecycle_gate as gate

    ledger_path = gate._validate_provider_ledger_target(
        sandbox_root, run_id, must_not_exist=False
    )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "event": "header",
            "schema_version": 1,
            "budget": gate.PROVIDER_BUDGET,
            "run_id": run_id,
        },
        {
            "event": "activated",
            "schema_version": 1,
            "budget": gate.PROVIDER_BUDGET,
            "run_id": run_id,
            "transport_guard": "httpx-client-single-request",
            "pid": owner_pid,
        },
    ]
    ledger_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="ascii",
    )


def run_self_test() -> dict[str, Any]:
    """Prove this script's two adapters, and the real gate driver function
    run against them, without any real host, sandbox, or network. Imports
    the gate module lazily, never at this script's module scope."""
    import os
    from types import SimpleNamespace

    from scripts import n3_live_lifecycle_gate as gate

    run_id = "n3-l03-startup-wait-proof-self-test"
    sandbox_root = offline_proof.REPO_ROOT / "tmp" / run_id
    sandbox_root.mkdir(parents=True, exist_ok=True)
    usage_path = sandbox_root / "telemetry_log.jsonl"
    if usage_path.exists():
        usage_path.unlink()
    usage_path.touch()

    owner_pid = os.getpid()
    _write_self_test_ledger(sandbox_root, run_id, owner_pid)

    host = _SelfTestSocketHost()
    adapter = SocketIOEventAdapter(host)
    flask_client = _SelfTestFlaskClient()
    clock = _SteppedClock()

    def startup_input_validator(_sandbox_root: Path) -> tuple[dict[str, bool], Any]:
        return {"provider_free_startup_seed": True}, gate._read_usage_snapshot(sandbox_root)

    context = gate.RowContext(
        run_id,
        offline_proof.REPO_ROOT,
        sandbox_root,
        sandbox_root,
        sandbox_root,
        gate.HostApiClient(connection_factory=host_api_loopback_factory(flask_client)),
        SimpleNamespace(owner_pid=owner_pid, listener_pids=None),
        sandbox_root,
        host_socket_client_factory=lambda **_options: adapter,
        startup_input_validator=startup_input_validator,
        monotonic=clock,
        sleep=lambda _seconds: None,
        row_deadline_at=clock._value + 1.5,
    )

    report = drive_status_response_proof(context, adapter, flask_client)

    checks = {
        "pre_status_response_game_started_false": (
            report["pre_status_response"] is not None
            and report["pre_status_response"].get("game_started") is False
        ),
        "post_status_response_game_started_true": (
            report["post_status_response"] is not None
            and report["post_status_response"].get("game_started") is True
        ),
        "pre_sharing_status_local_runtime_false": (
            report["pre_sharing_status_local_runtime"] is False
        ),
        "post_sharing_status_local_runtime_false": (
            report["post_sharing_status_local_runtime"] is False
        ),
        "driver_observed_real_signals_but_did_not_pass": (
            report["driver_observed"] is None
            and report["driver_failure"] is not None
            and report["driver_failure"]["verdict"] == "FAIL"
            and report["driver_failure"]["reason"] == "startup_provider_task_receipt_missing"
        ),
        "adapter_disconnected_cleanly_by_driver": adapter.connected is False,
    }
    passed = all(checks.values())
    return {"verdict": "PASS" if passed else "FAIL", "checks": checks, "report": report}


# ---------------------------------------------------------------------------
# Real-host mode: parent process plus a fresh, gate-import-free worker.
# ---------------------------------------------------------------------------


def _emit_request_status_and_capture(client: Any) -> Optional[dict[str, Any]]:
    """Emit a real request_status through the given real Socket.IO test
    client and return the most recent real status_response payload."""
    client.emit("request_status")
    payload: Optional[dict[str, Any]] = None
    for event in client.get_received():
        if not isinstance(event, dict) or event.get("name") != "status_response":
            continue
        args = event.get("args")
        if isinstance(args, (list, tuple)) and args and isinstance(args[0], dict):
            payload = args[0]
    return payload


def observe_real_host(client: Any, web_module: Any) -> dict[str, Any]:
    """The observe_running_host hook passed to run_startup_diagnostic().
    Called by that function itself, with its own real Socket.IO test client
    and the real imported web module, strictly after startup narration has
    been observed and strictly before shutdown is queued -- i.e. while the
    real host is still running. Emits one real request_status and reads the
    real /api/player-sharing/status route from the same real host, through
    the real web module's own Flask app test client. Never creates a
    profile/identity, never writes outside the sandbox, and never imports
    scripts.n3_live_lifecycle_gate or any other repository module -- it uses
    only the client and web_module objects it is given."""
    status_response = _emit_request_status_and_capture(client)
    game_started = status_response.get("game_started") if isinstance(status_response, dict) else None
    app = getattr(web_module, "app", None)
    if app is not None:
        sharing_status = _sharing_status_projection(app.test_client())
    else:
        sharing_status = {
            "http_status": 0,
            "json_decoded": False,
            "ok": False,
            "status_present": False,
            "checks_present": False,
            "local_runtime": "app_unavailable",
        }
    local_runtime = sharing_status.get("local_runtime")
    return {
        "status_response_received": status_response is not None,
        "status_response_game_started": game_started is True,
        "sharing_status_observed": app is not None,
        "sharing_status_http_status": sharing_status.get("http_status", 0),
        "sharing_status_json_decoded": bool(sharing_status.get("json_decoded")),
        "sharing_status_ok": bool(sharing_status.get("ok")),
        "sharing_status_status_present": bool(sharing_status.get("status_present")),
        "sharing_status_checks_present": bool(sharing_status.get("checks_present")),
        "sharing_status_local_runtime": local_runtime if isinstance(local_runtime, (bool, str)) else "non_bool",
    }


def _compose_worker_result(diagnostic_report: Mapping[str, Any], diagnostic_output_file: Path) -> dict[str, Any]:
    """Build this proof's own small, strictly bounded verdict mapping from
    the unmodified startup diagnostic report. Only this bounded mapping is
    ever written to this proof's own result file; the full diagnostic
    report stays at diagnostic_output_file."""
    observation = diagnostic_report.get("observation")
    observation_failure = diagnostic_report.get("observation_failure")
    diagnostic_verdict = diagnostic_report.get("verdict")
    network_attempt_count = diagnostic_report.get("network_attempt_count")

    status_response_game_started_true = bool(
        isinstance(observation, dict)
        and observation.get("status_response_received") is True
        and observation.get("status_response_game_started") is True
    )
    sharing_local_runtime_value = (
        observation.get("sharing_status_local_runtime") if isinstance(observation, dict) else None
    )
    sharing_local_runtime_false = bool(
        isinstance(observation, dict)
        and observation.get("sharing_status_observed") is True
        and sharing_local_runtime_value is False
    )
    sharing_local_runtime_reason = (
        sharing_local_runtime_value if isinstance(sharing_local_runtime_value, str) else None
    )
    no_network_attempts = network_attempt_count == 0

    if diagnostic_verdict != "PASS":
        verdict = "BLOCKED"
        reason = "underlying startup diagnostic did not PASS"
    elif observation_failure is not None:
        verdict = "FAIL"
        reason = "observation hook failed (" + str(observation_failure) + ")"
    elif not status_response_game_started_true:
        verdict = "FAIL"
        reason = "real status_response did not report game_started true"
    elif not sharing_local_runtime_false:
        verdict = "FAIL"
        reason = (
            "real sharing status did not report local_runtime false ("
            + str(sharing_local_runtime_reason)
            + ")"
            if sharing_local_runtime_reason is not None
            else "real sharing status did not report local_runtime false"
        )
    elif not no_network_attempts:
        verdict = "FAIL"
        reason = "a provider or network attempt was counted during the proof"
    else:
        verdict = "PASS"
        reason = (
            "real status_response.game_started was true and real "
            "local_runtime stayed false"
        )

    try:
        diagnostic_report_path = str(
            diagnostic_output_file.resolve().relative_to(offline_proof.REPO_ROOT.resolve())
        )
    except ValueError:
        diagnostic_report_path = str(diagnostic_output_file)

    return {
        "verdict": verdict,
        "reason": reason,
        "diagnostic_verdict": diagnostic_verdict if isinstance(diagnostic_verdict, str) else None,
        "observation_failure": observation_failure if isinstance(observation_failure, str) else None,
        "status_response_game_started": status_response_game_started_true,
        "sharing_local_runtime_false": sharing_local_runtime_false,
        "sharing_local_runtime_reason": sharing_local_runtime_reason,
        "no_network_attempts": bool(no_network_attempts),
        "network_attempt_count": (
            network_attempt_count
            if isinstance(network_attempt_count, int) and not isinstance(network_attempt_count, bool)
            else None
        ),
        "diagnostic_report_path": diagnostic_report_path,
    }


def _validate_worker_result(data: Any) -> dict[str, Any]:
    """Strictly re-validate the worker's own bounded result mapping before
    this parent process trusts any of its fields: a fixed key allowlist, no
    missing or extra keys, and strict per-field types and bounds."""
    if not isinstance(data, dict):
        raise ValueError("worker result is not a JSON object")
    keys = set(data.keys())
    extra_keys = keys - _WORKER_RESULT_ALLOWED_KEYS
    if extra_keys:
        raise ValueError("worker result has unexpected keys")
    missing_keys = _WORKER_RESULT_ALLOWED_KEYS - keys
    if missing_keys:
        raise ValueError("worker result is missing required keys")

    verdict = data["verdict"]
    if verdict not in _WORKER_RESULT_VERDICTS:
        raise ValueError("worker result verdict is invalid")

    for field in _WORKER_RESULT_REQUIRED_STRING_FIELDS:
        value = data[field]
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_WORKER_RESULT_STRING_LENGTH
        ):
            raise ValueError("worker result " + field + " is invalid")

    for field in _WORKER_RESULT_OPTIONAL_STRING_FIELDS:
        value = data[field]
        if value is not None and (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_WORKER_RESULT_STRING_LENGTH
        ):
            raise ValueError("worker result " + field + " is invalid")

    for field in _WORKER_RESULT_BOOL_FIELDS:
        if not isinstance(data[field], bool):
            raise ValueError("worker result " + field + " is not a bool")

    network_attempt_count = data["network_attempt_count"]
    if network_attempt_count is not None and (
        isinstance(network_attempt_count, bool)
        or not isinstance(network_attempt_count, int)
        or network_attempt_count < 0
    ):
        raise ValueError("worker result network_attempt_count is invalid")

    return dict(data)


def _read_worker_result(output_file: Path) -> dict[str, Any]:
    """Read and strictly re-validate the worker's result file. Raises
    ValueError/OSError on any size, parse, or schema problem; never trusts
    the file beyond this bounded check."""
    if output_file.stat().st_size > MAX_PROOF_RESULT_BYTES:
        raise ValueError("startup wait proof result size bound exceeded")
    with open(output_file, "r", encoding="ascii") as stream:
        raw_result = json.load(stream)
    return _validate_worker_result(raw_result)


def _run_real_host_worker(
    *,
    sandbox_root: str | Path,
    run_id: str,
    output_dir: Optional[str | Path],
    startup_timeout: float,
) -> dict[str, Any]:
    """Entry point for the --worker subprocess. Runs in a fresh process that
    has never imported scripts.n3_live_lifecycle_gate or the repository's
    web/utils packages, calls the unmodified
    n3_start_game_offline_proof.run_startup_diagnostic() with only the
    observe_running_host hook, and writes this proof's own bounded result."""
    output_file = resolve_output_file(output_dir, run_id)
    diagnostic_output_file = output_file.parent / "startup_diagnostic.json"
    diagnostic_report = offline_proof.run_startup_diagnostic(
        sandbox_root=sandbox_root,
        run_id=run_id,
        output_dir=diagnostic_output_file,
        startup_timeout=startup_timeout,
        observe_running_host=observe_real_host,
        isolated_worker=True,
    )
    result = _compose_worker_result(diagnostic_report, diagnostic_output_file)
    offline_proof._atomic_write_report(output_file, result)
    return result


def run_real_host_proof(
    *,
    sandbox_root: str | Path = offline_proof.DEFAULT_SANDBOX,
    run_id: str = DEFAULT_RUN_ID,
    output_dir: Optional[str | Path] = None,
    startup_timeout: float = 30.0,
) -> dict[str, Any]:
    """Parent process for real-host mode: validate arguments, run the same
    guard self-test n3_start_game_offline_proof's own main() runs, launch a
    fresh --worker subprocess that has never imported repository web/utils
    packages, and strictly re-validate its bounded result before trusting
    or printing it. Never run this in a session barred from executing
    real-host mode."""
    output_file = resolve_output_file(output_dir, run_id)

    guard_self_test = offline_proof.run_guard_self_test()
    if guard_self_test["verdict"] != "PASS":
        return {
            "verdict": "BLOCKED",
            "reason": "provider and egress guard self-test failed",
        }

    if output_file.exists() or output_file.is_symlink():
        return {
            "verdict": "BLOCKED",
            "reason": "startup wait proof result path already exists; choose a new run ID",
        }

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--sandbox-root",
        str(sandbox_root),
        "--run-id",
        run_id,
        "--startup-timeout",
        str(startup_timeout),
    ]
    if output_dir is not None:
        command.extend(("--output-dir", str(output_dir)))

    try:
        child = subprocess.run(
            command,
            cwd=offline_proof.REPO_ROOT,
            env=offline_proof._startup_diagnostic_worker_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=startup_timeout + offline_proof.STARTUP_DIAGNOSTIC_SHUTDOWN_SECONDS + 10.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "verdict": "BLOCKED",
            "reason": "startup wait proof worker exceeded its process bound",
        }

    if not output_file.is_file() or output_file.is_symlink():
        return {
            "verdict": "BLOCKED",
            "reason": (
                "startup wait proof worker did not produce a result"
                if child.returncode == 0
                else "startup wait proof worker failed before reporting"
            ),
        }

    try:
        return _read_worker_result(output_file)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "verdict": "BLOCKED",
            "reason": "startup wait proof result failed re-validation",
        }


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sandbox-root", default=str(offline_proof.DEFAULT_SANDBOX))
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if args.self_test:
        result = run_self_test()
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if result["verdict"] == "PASS" else 1
    if args.worker:
        try:
            result = _run_real_host_worker(
                sandbox_root=args.sandbox_root,
                run_id=args.run_id,
                output_dir=args.output_dir,
                startup_timeout=args.startup_timeout,
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "verdict": "BLOCKED",
                        "reason": "startup wait proof worker failed (" + type(exc).__name__ + ")",
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if result["verdict"] == "PASS" else 1
    report = run_real_host_proof(
        sandbox_root=args.sandbox_root,
        run_id=args.run_id,
        output_dir=args.output_dir,
        startup_timeout=args.startup_timeout,
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
