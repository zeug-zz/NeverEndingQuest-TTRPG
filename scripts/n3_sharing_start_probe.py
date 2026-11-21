# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free N3 sharing-start probe (DIAGNOSIS ONLY, never gate evidence).

Overseer rulings neq-n3-attempt13-sharing-start-20261117 item 3 and
neq-n3-pr170-merged-probe-20261118 item 3.

Design (b): the probe builds the PRODUCTION PlayerSharingService composition
(create_production_player_sharing_service: the real listener on 8370, the real
installed opentunnel companion, real identity bootstrap, real profile route
table, real `opentunnel status` command and `_parse_companion_status`, real
cleanup) and injects ONLY the local_runtime_check callable as true.

Why not a real host (design a): the host's local_runtime check is
`game_thread.is_alive()`. A real managed host can only get a live game thread
by running start_game, which needs the model router; stubbing the router in a
managed child host needs code injection into the child (not available through
ManagedHostHarness without product or gate changes). The in-process offline
proof (n3_start_game_offline_proof) stubs the router in-process but does not
produce a managed host with sharing routes. The product check is therefore not
weakened or bypassed: it is simply answered by the caller, exactly as the host
answers it. The failure surface under test (companion start, readiness/status
parse, route binding, origin bind, cleanup) never reads the local runtime
beyond that first gate, so it is identical.

Every artifact carries diagnosis_only=true and a distinct n3p- id; nothing is
written to the gate evidence tree and the booking lock is only verified.
"""

from __future__ import annotations

import argparse
import dataclasses
import errno
import hashlib
import ipaddress
import json
import os
import re
import shlex
import socket
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping, Sequence

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.n3_lifecycle_gate as preflight_gate
import scripts.n3_live_lifecycle_gate as gate
from web.extensions.opentunnel_sharing.identity_bootstrap import (
    DefaultCommandRunner,
    DefaultIdentityObserver,
    RunResult,
)
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    MAX_UNIX_SOCKET_PATH,
    companion_environment,
    prepare_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_BASE = gate.EVIDENCE_BASE / "probe"
PROBE_ID_PATTERN = re.compile(r"n3p-[a-z0-9][a-z0-9-]{0,38}\Z")
READY_DEADLINE_SECONDS = 150.0
LOAD_ONE_MINUTE_LIMIT = 10.0
LOAD_FIVE_MINUTE_LIMIT = 20.0
CENSUS_SETTLE_SECONDS = 10.0
VERDICT_NAME = "verdict.json"
DESIGN = "b"
LOCAL_RUNTIME_BASIS = "injected_true"
PROVIDER_MODULE_ROOTS = frozenset({"openai", "anthropic", "litellm"})
EXIT_CODES = {"PASS": 0, "FAIL": 1, "BLOCKED_DIRTY": 2, "REFUSED": 3}

_HOSTNAME_PATTERN = re.compile(r"(?i)\b[a-z0-9][a-z0-9.-]*\.opentunnel\.xyz\b")
_TUNNEL_ID_PATTERN = re.compile(r"(?i)(tunnel[_ -]?id\s*[:=]\s*)[^\s,;]+")
_URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")
_PUBLIC_ASSET_PATTERN = re.compile(
    rb"/static/player/([A-Za-z0-9._-]{1,128})(?=[?#\"'\s])"
)
_PUBLIC_ERROR_CODE_PATTERN = re.compile(r"[a-z_]{1,64}\Z")
PUBLIC_GET_TIMEOUT_SECONDS = min(gate.PUBLIC_CLIENT_TIMEOUT_SECONDS, 15.0)


class ProbeRefused(RuntimeError):
    """A precondition failed; nothing was started."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ProbeArguments:
    probe_id: str
    sha: str
    booking_id: str

    @property
    def state_run_id(self) -> str:
        """Stand-in gate-shaped id used only for the owned state-root id8."""
        return "n3-" + self.probe_id


@dataclass(slots=True)
class ProbeDependencies:
    root: Path
    gate_dependencies: gate.LiveGateDependencies
    service_factory: Callable[["ProbeConfig"], object]
    process_table: gate.ProcessTable
    port_inspector: preflight_gate.PortInspector
    companion_runner: Callable[[Sequence[str], Mapping[str, str], float], RunResult]
    identity_observer_factory: Callable[[object, Path], object]
    state_base_provider: Callable[[], Path]
    public_requester: Callable[
        [str, int, str, str, Mapping[str, str], bytes | None, float],
        gate.PublicHttpResponse,
    ] | None = None
    getloadavg: Callable[[], tuple[float, float, float]] = os.getloadavg
    utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    ready_deadline_seconds: float = READY_DEADLINE_SECONDS
    census_settle_seconds: float = CENSUS_SETTLE_SECONDS
    install_egress_guard: bool = True


@dataclass(frozen=True, slots=True)
class ProbeConfig:
    sandbox_root: Path
    state_root: Path
    player_build_root: Path


# --------------------------------------------------------------------------
# Redaction helpers
# --------------------------------------------------------------------------


def _scrub_text(text: str, secrets: Sequence[str]) -> str:
    selected = text
    for item in secrets:
        if isinstance(item, str) and len(item) >= 3:
            selected = selected.replace(item, "[REDACTED]")
    selected = _TUNNEL_ID_PATTERN.sub(lambda m: m.group(1) + "[REDACTED]", selected)
    selected = _URL_PATTERN.sub("[REDACTED_URL]", selected)
    selected = _HOSTNAME_PATTERN.sub("[REDACTED_HOST]", selected)
    return selected


def _scrub_tree(value: object, secrets: Sequence[str]) -> object:
    if isinstance(value, str):
        return _scrub_text(value, secrets)
    if isinstance(value, Mapping):
        return {
            str(key)[:80]: _scrub_tree(child, secrets) for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_tree(item, secrets) for item in value]
    if value is None or type(value) in {bool, int, float}:
        return value
    return None


# --------------------------------------------------------------------------
# In-process egress guard (the companion is a separate child process)
# --------------------------------------------------------------------------


def _is_loopback_address(address: object) -> bool:
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX path
    if isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if host in ("localhost", ""):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    return False


class _InProcessEgressGuard:
    """Refuse and count non-loopback connects made inside the probe process."""

    def __init__(self) -> None:
        self.refusals = 0
        self._lock = threading.Lock()
        self._original_connect = None
        self._original_connect_ex = None
        self._modules_before: frozenset[str] = frozenset()
        self._allowed_destinations: set[tuple[str, int]] = set()

    def __enter__(self) -> "_InProcessEgressGuard":
        self._modules_before = frozenset(sys.modules)
        self._original_connect = socket.socket.connect
        self._original_connect_ex = socket.socket.connect_ex
        guard = self
        original_connect = self._original_connect
        original_connect_ex = self._original_connect_ex

        def guarded_connect(sock: socket.socket, address: object) -> None:
            if not _is_loopback_address(address) and not guard._is_allowed_destination(
                address
            ):
                guard._refuse()
                raise OSError(errno.ENETUNREACH, "egress refused")
            return original_connect(sock, address)

        def guarded_connect_ex(sock: socket.socket, address: object) -> int:
            if not _is_loopback_address(address) and not guard._is_allowed_destination(
                address
            ):
                guard._refuse()
                return errno.ENETUNREACH
            return original_connect_ex(sock, address)

        socket.socket.connect = guarded_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._original_connect is not None:
            socket.socket.connect = self._original_connect  # type: ignore[method-assign]
        if self._original_connect_ex is not None:
            socket.socket.connect_ex = self._original_connect_ex  # type: ignore[method-assign]
        with self._lock:
            self._allowed_destinations.clear()

    def _refuse(self) -> None:
        with self._lock:
            self.refusals = min(self.refusals + 1, 1_000_000)

    def _is_allowed_destination(self, address: object) -> bool:
        if not isinstance(address, tuple) or len(address) < 2:
            return False
        host, port = address[0], address[1]
        if not isinstance(host, str) or type(port) is not int:
            return False
        try:
            parsed = ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            return False
        with self._lock:
            return (str(parsed), port) in self._allowed_destinations

    @contextmanager
    def allow_public_https(self, hostname: str, port: int):
        """Permit only resolved public IPs for the issued HTTPS origin."""
        try:
            rows = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except OSError:
            raise gate.PublicClientError("public_transport_unavailable") from None
        destinations: set[tuple[str, int]] = set()
        for row in rows:
            address = row[4]
            if not isinstance(address, tuple) or len(address) < 2:
                continue
            host, selected_port = address[0], address[1]
            if not isinstance(host, str) or type(selected_port) is not int:
                continue
            try:
                parsed = ipaddress.ip_address(host.split("%", 1)[0])
            except ValueError:
                continue
            if parsed.is_global and selected_port == port:
                destinations.add((str(parsed), selected_port))
        if not destinations:
            self._refuse()
            raise gate.PublicClientError("public_transport_unavailable")
        with self._lock:
            self._allowed_destinations.update(destinations)
        try:
            yield
        finally:
            with self._lock:
                self._allowed_destinations.difference_update(destinations)

    def provider_modules_loaded(self) -> int:
        new = frozenset(sys.modules) - self._modules_before
        return sum(1 for name in new if name.split(".", 1)[0] in PROVIDER_MODULE_ROOTS)


class _NullGuard:
    refusals = 0

    def __enter__(self) -> "_NullGuard":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def provider_modules_loaded(self) -> int:
        return 0


# --------------------------------------------------------------------------
# Preconditions
# --------------------------------------------------------------------------


def _marker_for(sandbox: Path) -> str:
    normalized = Path(os.path.abspath(os.fspath(sandbox)))
    return "neq-" + hashlib.sha256(os.fsencode(normalized)).hexdigest()[:32]


def _lock_directory(identity: preflight_gate.WorkspaceIdentity) -> Path:
    return identity.git_common_dir / "neq-coordination" / "live-window.lock"


def _read_lock(lock_dir: Path, booking_id: str, now: datetime) -> str:
    """Read-only lock check; returns a fingerprint for the unchanged proof."""
    try:
        dir_info = lock_dir.lstat()
        holder = lock_dir / "holder.json"
        holder_info = holder.lstat()
    except OSError:
        raise ProbeRefused("lock_missing") from None
    import stat as _stat

    if (
        _stat.S_ISLNK(dir_info.st_mode)
        or not _stat.S_ISDIR(dir_info.st_mode)
        or _stat.S_ISLNK(holder_info.st_mode)
        or not _stat.S_ISREG(holder_info.st_mode)
        or holder_info.st_size < 1
        or holder_info.st_size > gate.MAX_LOCK_BYTES
    ):
        raise ProbeRefused("lock_record_invalid")
    try:
        raw = holder.read_bytes()
        lines = raw.decode("utf-8").splitlines()
        if len(lines) != 1:
            raise ValueError("line_count")
        record = json.loads(lines[0])
    except (OSError, UnicodeError, ValueError):
        raise ProbeRefused("lock_record_invalid") from None
    if not isinstance(record, dict):
        raise ProbeRefused("lock_record_invalid")
    if record.get("booking_id") != booking_id:
        raise ProbeRefused("lock_booking_mismatch")
    if "window_start" in record or "window_end" in record:
        try:
            start = gate._parse_aware_datetime(record.get("window_start"))
            end = gate._parse_aware_datetime(record.get("window_end"))
        except Exception:
            raise ProbeRefused("lock_window_invalid") from None
        if not start <= now < end:
            raise ProbeRefused("lock_window_expired")
    return "%s:%d:%d:%d" % (
        hashlib.sha256(raw).hexdigest(),
        dir_info.st_ino,
        holder_info.st_ino,
        holder_info.st_mtime_ns,
    )


def _opentunnel_processes(records: Sequence[gate.ProcessRecord]) -> int:
    count = 0
    for record in records:
        try:
            tokens = shlex.split(record.command)
        except ValueError:
            tokens = record.command.split()
        if not tokens:
            continue
        if Path(tokens[0]).name == "opentunnel" or any(
            "/runtime/opentunnel/" in token and Path(token).name == "opentunnel"
            for token in tokens
        ):
            count += 1
    return count


def _descendant_count(records: Sequence[gate.ProcessRecord], root_pid: int) -> int:
    children: dict[int, list[int]] = {}
    for record in records:
        children.setdefault(record.parent_pid, []).append(record.pid)
    seen: set[int] = set()
    stack = list(children.get(root_pid, ()))
    while stack:
        pid = stack.pop()
        if pid in seen or pid == root_pid:
            continue
        seen.add(pid)
        stack.extend(children.get(pid, ()))
    return len(seen)


def _check_preconditions(
    arguments: ProbeArguments, deps: ProbeDependencies
) -> SimpleNamespace:
    if PROBE_ID_PATTERN.fullmatch(arguments.probe_id) is None:
        raise ProbeRefused("probe_id_invalid")
    gate_arguments = gate.RunArguments(
        run_id=arguments.state_run_id,
        sha=arguments.sha,
        booking_id=arguments.booking_id,
        preflight_report="-",
    )
    try:
        identity, platform_key = gate.check_workspace_identity(
            deps.gate_dependencies, gate_arguments
        )
    except gate.GateError as exc:
        raise ProbeRefused(exc.reason) from None
    lock_fingerprint = _read_lock(
        _lock_directory(identity), arguments.booking_id, deps.utc_now()
    )

    try:
        one, five, _fifteen = deps.getloadavg()
    except OSError:
        raise ProbeRefused("load_unavailable") from None
    if not (
        type(one) in (int, float)
        and type(five) in (int, float)
        and one < LOAD_ONE_MINUTE_LIMIT
        and five < LOAD_FIVE_MINUTE_LIMIT
    ):
        raise ProbeRefused("load_gate_failed")

    for port in (gate.HOST_PORT, gate.PLAYER_PORT):
        try:
            observation = deps.port_inspector.inspect(port)
        except Exception:
            raise ProbeRefused("port_observation_unavailable") from None
        if not gate._port_is_free(observation, port):
            raise ProbeRefused("port_not_free")
    try:
        records = deps.process_table.snapshot()
    except Exception:
        raise ProbeRefused("process_table_unavailable") from None
    if _opentunnel_processes(records):
        raise ProbeRefused("opentunnel_process_exists")

    try:
        sandbox = deps.gate_dependencies.sandbox_validator(deps.root)
        companion = deps.gate_dependencies.companion_verifier(sandbox, platform_key)
    except gate.GateError as exc:
        raise ProbeRefused(exc.reason) from None
    except Exception:
        raise ProbeRefused("sandbox_unavailable") from None

    try:
        base = Path(os.path.abspath(os.fspath(deps.state_base_provider())))
        state_root = base / "neq-n3g" / gate._state_root_id8(arguments.state_run_id)
        socket_path = (
            state_root / "neq" / "opentunnel" / DEFAULT_PROFILE / "run"
            / (DEFAULT_PROFILE + ".sock")
        )
        if len(os.fsencode(os.fspath(socket_path))) >= MAX_UNIX_SOCKET_PATH:
            raise ProbeRefused("state_root_too_long")
        gate._validate_state_root_candidate(deps.root, base, state_root)
    except ProbeRefused:
        raise
    except gate.GateError as exc:
        raise ProbeRefused(exc.reason) from None
    except Exception:
        raise ProbeRefused("gate_state_root_invalid") from None

    evidence_dir = deps.root / PROBE_BASE / arguments.probe_id
    if evidence_dir.exists() or evidence_dir.is_symlink():
        raise ProbeRefused("probe_evidence_exists")
    return SimpleNamespace(
        identity=identity,
        platform_key=platform_key,
        sandbox=sandbox,
        companion_path=Path(companion["path"]),
        state_root=state_root,
        evidence_dir=evidence_dir,
        lock_dir=_lock_directory(identity),
        lock_fingerprint=lock_fingerprint,
    )


# --------------------------------------------------------------------------
# Production composition
# --------------------------------------------------------------------------


def build_production_service(config: ProbeConfig) -> object:
    """The production composition with ONLY local_runtime_check injected true."""
    from web.extensions.opentunnel_sharing.service import (
        create_production_player_sharing_service,
    )
    from web.extensions.player.gateway import UnavailablePlayerGateway

    return create_production_player_sharing_service(
        UnavailablePlayerGateway(),
        lambda: True,  # local_runtime: injected_true (see module docstring)
        install_root=config.sandbox_root,
        state_root=config.state_root,
        player_build_root=config.player_build_root,
        web_port=gate.HOST_PORT,
    )


def _validate_public_response(response: object) -> gate.PublicHttpResponse:
    if (
        not isinstance(response, gate.PublicHttpResponse)
        or type(response.status) is not int
        or not 100 <= response.status <= 599
        or not isinstance(response.headers, tuple)
        or not isinstance(response.body, bytes)
        or len(response.body) > gate.MAX_PUBLIC_RESPONSE_BYTES
        or len(response.headers) > 128
        or any(
            not isinstance(name, str)
            or not isinstance(value, str)
            or len(name) > 256
            or len(value) > 8192
            for name, value in response.headers
        )
    ):
        raise gate.PublicClientError("public_response_invalid")
    return response


def _public_get(
    client: gate.PublicUrlClient,
    origin: gate.PublicOrigin,
    path: str,
    guard: _InProcessEgressGuard | _NullGuard,
    *,
    injected_requester: bool,
) -> gate.PublicHttpResponse:
    """GET only the shell or one strictly formed player-asset path."""
    if path != "/" and re.fullmatch(
        r"/static/player/[A-Za-z0-9._-]{1,128}", path
    ) is None:
        raise gate.PublicClientError("public_request_invalid")
    network_scope = (
        guard.allow_public_https(origin.hostname, origin.port)
        if not injected_requester and isinstance(guard, _InProcessEgressGuard)
        else nullcontext()
    )
    with network_scope:
        if path == "/":
            return client.request("GET", "/")
        try:
            response = client._requester(
                origin.hostname,
                origin.port,
                "GET",
                path,
                {"Host": origin.authority},
                None,
                client._timeout,
            )
        except gate.PublicClientError:
            raise
        except Exception:
            raise gate.PublicClientError("public_transport_unavailable") from None
    return _validate_public_response(response)


def _content_type_class(response: gate.PublicHttpResponse) -> str:
    values = response.values("content-type")
    if len(values) != 1:
        return "missing" if not values else "invalid"
    media_type = values[0].split(";", 1)[0].strip().casefold()
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    if media_type in {
        "application/javascript",
        "text/javascript",
        "application/ecmascript",
        "text/ecmascript",
    }:
        return "javascript"
    if media_type == "text/css":
        return "css"
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("font/"):
        return "font"
    if media_type.startswith("text/"):
        return "text"
    if "/" in media_type:
        return "other"
    return "invalid"


def _public_error_code(response: gate.PublicHttpResponse) -> str | None:
    try:
        payload = json.loads(
            response.body.decode("utf-8"),
            object_pairs_hook=gate._unique_object,
            parse_constant=gate._reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"error"}
        or not isinstance(payload["error"], str)
        or _PUBLIC_ERROR_CODE_PATTERN.fullmatch(payload["error"]) is None
    ):
        return None
    return payload["error"]


def _is_login_shell(body: bytes) -> bool:
    from web.extensions.player.assets import PRELOGIN_CSRF_PLACEHOLDER

    normalized = body.lstrip().lower()
    return (
        bool(normalized)
        and b"<html" in normalized
        and b'name="csrf_token"' in body
        and PRELOGIN_CSRF_PLACEHOLDER not in body
    )


class _StatusParseCounter:
    """Count (never record) outcomes of the real status parser and command."""

    def __init__(self) -> None:
        self.parse_calls = 0
        self.parse_ok = 0
        self.parse_rejected = 0
        self.status_commands = 0
        self._patches: list[tuple[object, str, object]] = []

    def __enter__(self) -> "_StatusParseCounter":
        try:
            import web.extensions.opentunnel_sharing.service as service_module
        except Exception:
            return self
        counter = self
        original_parse = service_module._parse_companion_status
        original_run = service_module._ProductionComposition._run_route_status

        def counted_parse(output: str, profile: str) -> str | None:
            result = original_parse(output, profile)
            counter.parse_calls += 1
            if result is None:
                counter.parse_rejected += 1
            else:
                counter.parse_ok += 1
            return result

        def counted_run(composition: object, *args: object, **kwargs: object) -> object:
            counter.status_commands += 1
            return original_run(composition, *args, **kwargs)

        self._patches = [
            (service_module, "_parse_companion_status", original_parse),
            (service_module._ProductionComposition, "_run_route_status", original_run),
        ]
        service_module._parse_companion_status = counted_parse
        service_module._ProductionComposition._run_route_status = counted_run
        return self

    def __exit__(self, *_exc: object) -> None:
        for target, name, original in self._patches:
            setattr(target, name, original)
        self._patches = []

    def as_counts(self) -> dict[str, int]:
        return {
            "status_commands": self.status_commands,
            "parse_calls": self.parse_calls,
            "parse_ok": self.parse_ok,
            "parse_rejected": self.parse_rejected,
        }


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def _state_value(snapshot: object) -> tuple[str, str]:
    lifecycle = getattr(snapshot, "lifecycle", None)
    state = getattr(lifecycle, "state", None)
    reason = getattr(lifecycle, "reason", None)
    return (
        str(getattr(state, "value", state)),
        str(getattr(reason, "value", reason)),
    )


def _capture_start_failure(
    service: object, evidence_dir: Path, probe_id: str, secrets: Sequence[str]
) -> dict[str, object]:
    observation: dict[str, object] = {"written": False, "reason": "not_retained"}
    try:
        reader = getattr(service, "start_failure_diagnostics", None)
        value = reader() if callable(reader) else None
        if isinstance(value, dict) and isinstance(value.get("detail"), Mapping):
            payload = _scrub_tree(
                {
                    "schema": 1,
                    "diagnosis_only": True,
                    "probe_id": probe_id,
                    "summary": value.get("summary"),
                    "detail": value.get("detail"),
                },
                secrets,
            )
            size = gate._write_private_json(
                evidence_dir / gate.START_FAILURE_EVIDENCE_NAME, payload
            )
            observation = {"written": True, "bytes": size}
    except (OSError, TypeError, ValueError, AttributeError):
        observation = {"written": False, "reason": "capture_error"}
    return observation


def _identity_teardown(
    arguments: ProbeArguments,
    deps: ProbeDependencies,
    prepared: SimpleNamespace,
    marker: str,
) -> str:
    """Delete the remote identity and verify absence; returns the census value."""
    try:
        profile = prepare_profile(
            prepared.state_root,
            install_marker=marker,
            profile=DEFAULT_PROFILE,
            create=False,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return "not_verified"
    if profile.state != "ready" or profile.layout is None:
        return "never_initialized" if profile.state == "absent" else "not_verified"
    layout = profile.layout
    environment = companion_environment(layout)
    companion = str(prepared.companion_path)

    def run(*argv: str) -> RunResult | None:
        try:
            result = deps.companion_runner(
                (companion, "--profile", layout.profile) + tuple(argv),
                dict(environment),
                30.0,
            )
        except Exception:
            return None
        return result if isinstance(result, RunResult) else None

    before = run("status")
    absent_before = (
        before is not None
        and not before.timed_out
        and not before.output_truncated
        and gate._identity_absent_status(before.bounded_output) is True
    )
    if not absent_before:
        delete = run("delete", "--yes")
        if delete is None or delete.timed_out or delete.returncode != 0:
            return "not_verified"
    after = run("status")
    if after is None or after.timed_out or after.output_truncated:
        return "not_verified"
    if gate._identity_absent_status(after.bounded_output) is not True:
        return "not_verified"
    try:
        observer = deps.identity_observer_factory(layout, prepared.companion_path)
        observations = gate._identity_cleanup_observations(observer, DEFAULT_PROFILE)
    except Exception:
        return "not_verified"
    if observations is None or any(item["state"] != "absent" for item in observations):
        return "not_verified"
    return "verified_absent"


def _census(
    arguments: ProbeArguments,
    deps: ProbeDependencies,
    prepared: SimpleNamespace,
    identity_state: str,
    state_cleanup_ok: bool,
) -> dict[str, object]:
    census: dict[str, object] = {
        "identity": identity_state,
        "state_root_removed": bool(state_cleanup_ok),
        "ports_free": False,
        "opentunnel_processes": -1,
        "descendant_processes": -1,
        "booking_lock_unchanged": False,
    }
    deadline = deps.monotonic() + deps.census_settle_seconds
    while True:
        try:
            records = deps.process_table.snapshot()
            census["opentunnel_processes"] = _opentunnel_processes(records)
            census["descendant_processes"] = _descendant_count(records, os.getpid())
        except Exception:
            census["opentunnel_processes"] = -1
            census["descendant_processes"] = -1
        try:
            census["ports_free"] = bool(gate._ports_are_free(deps.port_inspector))
        except Exception:
            census["ports_free"] = False
        settled = (
            census["opentunnel_processes"] == 0
            and census["descendant_processes"] == 0
            and census["ports_free"] is True
        )
        if settled or deps.monotonic() >= deadline:
            break
        deps.sleep(0.25)
    try:
        census["booking_lock_unchanged"] = (
            _read_lock(prepared.lock_dir, arguments.booking_id, deps.utc_now())
            == prepared.lock_fingerprint
        )
    except ProbeRefused:
        census["booking_lock_unchanged"] = False
    census["clean"] = bool(
        census["identity"] in {"verified_absent", "never_initialized"}
        and census["state_root_removed"] is True
        and census["ports_free"] is True
        and census["opentunnel_processes"] == 0
        and census["descendant_processes"] == 0
        and census["booking_lock_unchanged"] is True
    )
    return census


def _write_evidence(
    prepared: SimpleNamespace, verdict: dict[str, object], secrets: Sequence[str]
) -> bool:
    safe = _scrub_tree(gate.redact_live_evidence(verdict, secrets), secrets)
    try:
        gate._write_private_json(prepared.evidence_dir / VERDICT_NAME, safe)
        return bool(gate._write_sha256sums(prepared.evidence_dir))
    except (OSError, TypeError, ValueError):
        return False


def run_probe(
    arguments: ProbeArguments, deps: ProbeDependencies
) -> tuple[dict[str, object], int]:
    try:
        prepared = _check_preconditions(arguments, deps)
    except ProbeRefused as exc:
        refusal = {
            "diagnosis_only": True,
            "probe_id": arguments.probe_id,
            "verdict": "REFUSED",
            "reason": exc.reason,
        }
        return refusal, EXIT_CODES["REFUSED"]

    secrets: list[str] = []
    steps: list[dict[str, object]] = []
    public_get_without_origin: dict[str, object] = {
        "shell_status": None,
        "asset_status": None,
        "shell_references_asset": False,
        "origin_header_sent": False,
    }
    verdict: dict[str, object] = {
        "schema": 1,
        "diagnosis_only": True,
        "probe_id": arguments.probe_id,
        "sha": arguments.sha,
        "booking_id": arguments.booking_id,
        "design": DESIGN,
        "local_runtime": LOCAL_RUNTIME_BASIS,
        "reached_sharing_ready": False,
        "steps": steps,
    }
    failure: str | None = None
    service: object | None = None
    owned = SimpleNamespace(
        state_root=prepared.state_root,
        _state_root_identity=None,
        _state_parent_identity=None,
        _state_parent_created=False,
    )
    marker = _marker_for(prepared.sandbox)
    counter = _StatusParseCounter()
    guard = _InProcessEgressGuard() if deps.install_egress_guard else _NullGuard()
    started_monotonic = deps.monotonic()
    ready_reached = False
    stop_ok = False
    identity_state = "not_verified"
    state_cleanup_ok = False
    final_status: object | None = None
    diagnostics_observation: dict[str, object] | None = None

    def step(
        name: str, begun: float, outcome: str, **details: object
    ) -> None:
        record: dict[str, object] = {
            "name": name,
            "elapsed_seconds": round(max(0.0, deps.monotonic() - begun), 2),
            "outcome": outcome,
        }
        record.update(details)
        steps.append(record)

    try:
        prepared.evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(prepared.evidence_dir, 0o700)
        with guard, counter:
            try:
                begun = deps.monotonic()
                owned._state_parent_created = gate._create_private_state_tree(
                    prepared.state_root
                )
                owned._state_root_identity = gate._private_state_tree_identity(
                    prepared.state_root
                )
                owned._state_parent_identity = gate._private_state_parent_identity(
                    prepared.state_root.parent
                )
                step("create_owned_state_root", begun, "ok")

                config = ProbeConfig(
                    sandbox_root=prepared.sandbox,
                    state_root=prepared.state_root,
                    player_build_root=prepared.sandbox / "web" / "frontend" / "dist",
                )
                service = deps.service_factory(config)

                begun = deps.monotonic()
                init = service.initialize_identity(facilitator_confirmed=True)
                init_ok = bool(init.ok) and init.reason == "identity_initialized"
                step("initialize_identity", begun, "ok" if init_ok else init.reason)
                if not init_ok:
                    raise _ProbeStepFailed("identity_initialization_failed")

                begun = deps.monotonic()
                issued = service.issue_access()
                if not issued.ok or issued.credential is None:
                    step("issue_access", begun, "failed")
                    raise _ProbeStepFailed("credential_issuance_failed")
                try:
                    secrets.append(issued.credential.reveal())
                except Exception:
                    pass
                step("issue_access", begun, "ok")

                begun = deps.monotonic()
                holder: dict[str, object] = {}

                def start_worker() -> None:
                    try:
                        holder["result"] = service.start()
                    except Exception as exc:
                        holder["error"] = type(exc).__name__

                worker = threading.Thread(
                    target=start_worker, name="n3p-start", daemon=True
                )
                worker.start()
                worker.join(deps.ready_deadline_seconds)
                if worker.is_alive():
                    step("start_sharing", begun, "deadline_exceeded")
                    try:
                        service.stop()
                    except Exception:
                        pass
                    worker.join(30.0)
                    raise _ProbeStepFailed("start_deadline_exceeded")
                result = holder.get("result")
                if result is None:
                    step("start_sharing", begun, str(holder.get("error", "raised")))
                    raise _ProbeStepFailed("start_raised")
                state, reason = _state_value(result.status)
                final_status = result.status
                step("start_sharing", begun, "ok" if result.ok else result.reason)

                begun = deps.monotonic()
                poll_deadline = begun + max(
                    5.0, deps.ready_deadline_seconds - (begun - started_monotonic)
                )
                while True:
                    final_status = service.status()
                    state, reason = _state_value(final_status)
                    if state == "ready" or deps.monotonic() >= poll_deadline:
                        break
                    if not result.ok:
                        break
                    deps.sleep(0.25)
                ready_reached = bool(result.ok) and state == "ready" and reason == "ready"
                step("poll_status", begun, "ready" if ready_reached else state)
                if not ready_reached:
                    raise _ProbeStepFailed("sharing_start_not_ready")

                begun = deps.monotonic()
                try:
                    invitation_result = service.copy_invitation()
                    invitation_url = getattr(invitation_result, "invitation", None)
                    invitation_ok = (
                        bool(getattr(invitation_result, "ok", False))
                        and isinstance(invitation_url, str)
                    )
                except Exception:
                    invitation_url = None
                    invitation_ok = False
                if isinstance(invitation_url, str):
                    secrets.append(invitation_url)
                if not invitation_ok:
                    step("copy_invitation", begun, "failed")
                    begun = deps.monotonic()
                    step(
                        "public_shell_get",
                        begun,
                        "failed",
                        status=None,
                        content_type_class="unknown",
                        body_bytes=0,
                        asset_id_length=None,
                        shell_references_asset=False,
                    )
                    raise _ProbeStepFailed("public_shell_get_failed")

                client = gate.PublicUrlClient(
                    requester=deps.public_requester,
                    timeout_seconds=PUBLIC_GET_TIMEOUT_SECONDS,
                )
                try:
                    origin = client.bind_invitation(invitation_url)
                except gate.PublicClientError:
                    step("copy_invitation", begun, "invalid")
                    begun = deps.monotonic()
                    step(
                        "public_shell_get",
                        begun,
                        "failed",
                        status=None,
                        content_type_class="unknown",
                        body_bytes=0,
                        asset_id_length=None,
                        shell_references_asset=False,
                    )
                    raise _ProbeStepFailed("public_shell_get_failed") from None
                secrets.extend(
                    value
                    for value in (
                        origin.origin,
                        origin.authority,
                        origin.hostname,
                    )
                    if value
                )
                step("copy_invitation", begun, "ok")

                begun = deps.monotonic()
                try:
                    shell = _public_get(
                        client,
                        origin,
                        "/",
                        guard,
                        injected_requester=deps.public_requester is not None,
                    )
                except Exception:
                    step(
                        "public_shell_get",
                        begun,
                        "failed",
                        status=None,
                        content_type_class="unknown",
                        body_bytes=0,
                        asset_id_length=None,
                        shell_references_asset=False,
                    )
                    raise _ProbeStepFailed("public_shell_get_failed") from None
                shell_type = _content_type_class(shell)
                asset_match = _PUBLIC_ASSET_PATTERN.search(shell.body)
                shell_references_asset = asset_match is not None
                asset_id_length = (
                    len(asset_match.group(1)) if asset_match is not None else None
                )
                public_get_without_origin["shell_status"] = shell.status
                public_get_without_origin[
                    "shell_references_asset"
                ] = shell_references_asset
                shell_observation: dict[str, object] = {
                    "status": shell.status,
                    "content_type_class": shell_type,
                    "body_bytes": len(shell.body),
                    "asset_id_length": asset_id_length,
                    "shell_references_asset": shell_references_asset,
                }
                if shell.status != 200:
                    error_code = _public_error_code(shell)
                    if error_code is not None:
                        shell_observation["error_code"] = error_code
                    step("public_shell_get", begun, "failed", **shell_observation)
                    raise _ProbeStepFailed("public_shell_get_failed")
                if (
                    shell_type != "html"
                    or not shell.body.strip()
                    or not _is_login_shell(shell.body)
                ):
                    step("public_shell_get", begun, "failed", **shell_observation)
                    raise _ProbeStepFailed("public_shell_get_failed")
                if asset_match is None:
                    step("public_shell_get", begun, "failed", **shell_observation)
                    raise _ProbeStepFailed("public_shell_asset_missing")
                step("public_shell_get", begun, "ok", **shell_observation)

                asset_id = asset_match.group(1).decode("ascii")
                asset_path = "/static/player/" + asset_id
                begun = deps.monotonic()
                try:
                    asset = _public_get(
                        client,
                        origin,
                        asset_path,
                        guard,
                        injected_requester=deps.public_requester is not None,
                    )
                except Exception:
                    step(
                        "public_asset_get",
                        begun,
                        "failed",
                        status=None,
                        content_type_class="unknown",
                        body_bytes=0,
                        asset_id_length=len(asset_id),
                        shell_references_asset=True,
                    )
                    raise _ProbeStepFailed("public_asset_get_failed") from None
                asset_type = _content_type_class(asset)
                public_get_without_origin["asset_status"] = asset.status
                asset_observation: dict[str, object] = {
                    "status": asset.status,
                    "content_type_class": asset_type,
                    "body_bytes": len(asset.body),
                    "asset_id_length": len(asset_id),
                    "shell_references_asset": True,
                }
                if asset.status != 200:
                    error_code = _public_error_code(asset)
                    if error_code is not None:
                        asset_observation["error_code"] = error_code
                    step("public_asset_get", begun, "failed", **asset_observation)
                    raise _ProbeStepFailed("public_asset_get_failed")
                if not asset.body:
                    step("public_asset_get", begun, "failed", **asset_observation)
                    raise _ProbeStepFailed("public_asset_get_failed")
                step("public_asset_get", begun, "ok", **asset_observation)
            except _ProbeStepFailed as exc:
                failure = exc.reason
            except Exception as exc:
                failure = "probe_exception_" + type(exc).__name__
            finally:
                if service is not None:
                    if failure is not None:
                        diagnostics_observation = _capture_start_failure(
                            service, prepared.evidence_dir, arguments.probe_id, secrets
                        )
                    try:
                        begun = deps.monotonic()
                        stopped = service.stop()
                        stop_ok = bool(stopped.ok)
                        step("stop_sharing", begun, "ok" if stop_ok else stopped.reason)
                    except Exception:
                        step("stop_sharing", deps.monotonic(), "raised")
                    try:
                        final_after = service.status()
                        if final_status is None:
                            final_status = final_after
                    except Exception:
                        pass
                    try:
                        service.shutdown()
                    except Exception:
                        pass
                begun = deps.monotonic()
                identity_state = (
                    _identity_teardown(arguments, deps, prepared, marker)
                    if owned._state_root_identity is not None
                    else "never_initialized"
                )
                step("identity_teardown", begun, identity_state)
        if failure is None and not stop_ok:
            failure = "stop_sharing_failed"
    except OSError:
        failure = failure or "probe_setup_failed"
    finally:
        cleanup = None
        if owned._state_root_identity is not None:
            cleanup = gate._cleanup_driver_state_root(
                owned, run_id=arguments.state_run_id, repository_root=deps.root
            )
        elif not prepared.state_root.exists():
            cleanup = (True, False)
        state_cleanup_ok = bool(cleanup is not None and cleanup[0])

    census = _census(arguments, deps, prepared, identity_state, state_cleanup_ok)

    dispatch = guard.refusals + guard.provider_modules_loaded()
    counters = {
        "companion_launches": int(getattr(final_status, "companion_launches", 0) or 0),
        "identity_up_invocations": int(
            getattr(final_status, "identity_up_invocations", 0) or 0
        ),
    }
    final_state, final_reason = (
        _state_value(final_status) if final_status is not None else ("unknown", "unknown")
    )
    if dispatch != 0 and failure is None:
        failure = "provider_dispatch_attempts_nonzero"
    if counters["identity_up_invocations"] > 1 and failure is None:
        failure = "relay_tunnel_creation_bound_exceeded"
    if failure is None and ready_reached is not True:
        failure = "sharing_start_not_ready"
    if failure is None and public_get_without_origin["shell_status"] != 200:
        failure = "public_shell_get_failed"
    if failure is None and public_get_without_origin["asset_status"] != 200:
        failure = "public_asset_get_failed"
    if (
        failure is None
        and public_get_without_origin["shell_references_asset"] is not True
    ):
        failure = "public_shell_asset_missing"

    if census["clean"] is not True:
        outcome = "BLOCKED_DIRTY"
        reason_code = "census_not_clean"
    elif failure is not None:
        outcome = "FAIL"
        reason_code = failure
    else:
        outcome = "PASS"
        reason_code = "sharing_ready_reached_and_cleaned_up"

    verdict.update(
        {
            "verdict": outcome,
            "reason": reason_code,
            "reached_sharing_ready": ready_reached,
            "public_get_without_origin": public_get_without_origin,
            "final_sharing_state": final_state,
            "final_sharing_reason": final_reason,
            "companion_counters": counters,
            "provider_dispatch_attempts": dispatch,
            "provider_attempt_ledger": {
                "dispatch_attempts": dispatch,
                "egress_refusals": guard.refusals,
                "provider_modules_loaded": guard.provider_modules_loaded(),
            },
            "relay_creations_max": counters["identity_up_invocations"],
            "status_parse": counter.as_counts(),
            "census": census,
            "total_elapsed_seconds": round(
                max(0.0, deps.monotonic() - started_monotonic), 2
            ),
        }
    )
    if diagnostics_observation is not None:
        verdict["start_failure_diagnostics"] = diagnostics_observation
    if not _write_evidence(prepared, verdict, secrets) and outcome == "PASS":
        verdict["verdict"] = "FAIL"
        verdict["reason"] = "evidence_write_failed"
        outcome = "FAIL"
    return verdict, EXIT_CODES[outcome]


class _ProbeStepFailed(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------
# Defaults, selftest and CLI
# --------------------------------------------------------------------------


def default_dependencies(root: Path = REPO_ROOT) -> ProbeDependencies:
    return ProbeDependencies(
        root=root,
        gate_dependencies=gate._default_dependencies(root),
        service_factory=build_production_service,
        process_table=gate.SystemProcessTable(),
        port_inspector=preflight_gate.SystemPortInspector(),
        companion_runner=DefaultCommandRunner(),
        identity_observer_factory=lambda layout, path: DefaultIdentityObserver(
            layout, path
        ),
        state_base_provider=gate._default_state_cache_base,
    )


class FakeIssuedValue:
    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value


class FakeSharingService:
    """Offline stand-in for PlayerSharingService; no network, no processes."""

    def __init__(
        self,
        config: ProbeConfig,
        *,
        fail_start: bool = False,
        issued_value: str = "probe-fake-issued-value",
        invitation: str = "https://probe-relay.example.invalid",
        diagnostics: dict[str, object] | None = None,
        provider_hook: Callable[[], None] | None = None,
        identity_up: int = 1,
    ) -> None:
        self._config = config
        self._fail_start = fail_start
        self._issued_value = issued_value
        self._invitation = invitation
        self._diagnostics = diagnostics
        self._provider_hook = provider_hook
        self._identity_up = identity_up
        self._state = ("off", "off")
        self._initialized = False
        self.calls: list[str] = []

    def _status(self) -> SimpleNamespace:
        return SimpleNamespace(
            lifecycle=SimpleNamespace(state=self._state[0], reason=self._state[1]),
            companion_launches=1 if self._state[0] != "off" else 0,
            identity_up_invocations=self._identity_up if self._initialized else 0,
        )

    def _result(self, ok: bool, reason: str) -> SimpleNamespace:
        return SimpleNamespace(
            ok=ok, reason=reason, status=self._status(), credential=None
        )

    def status(self) -> SimpleNamespace:
        return self._status()

    def initialize_identity(self, *, facilitator_confirmed: bool) -> SimpleNamespace:
        self.calls.append("initialize_identity")
        prepare_profile(
            self._config.state_root,
            install_marker=_marker_for(self._config.sandbox_root),
            profile=DEFAULT_PROFILE,
            create=True,
        )
        self._initialized = True
        return self._result(True, "identity_initialized")

    def issue_access(self) -> SimpleNamespace:
        self.calls.append("issue_access")
        return SimpleNamespace(
            ok=True,
            reason="issued",
            status=self._status(),
            credential=FakeIssuedValue(self._issued_value),
        )

    def copy_invitation(self) -> SimpleNamespace:
        self.calls.append("copy_invitation")
        return SimpleNamespace(
            ok=self._state == ("ready", "ready"),
            reason="invitation_ready",
            invitation=self._invitation,
        )

    def start(self) -> SimpleNamespace:
        self.calls.append("start")
        if self._provider_hook is not None:
            self._provider_hook()
        if self._fail_start:
            self._state = ("failed", "companion_failed")
            return self._result(False, "companion_failed")
        self._state = ("ready", "ready")
        return self._result(True, "ready")

    def stop(self) -> SimpleNamespace:
        self.calls.append("stop")
        self._state = ("off", "off")
        return self._result(True, "stopped")

    def shutdown(self) -> SimpleNamespace:
        self.calls.append("shutdown")
        return self._result(True, "stopped")

    def start_failure_diagnostics(self) -> dict[str, object] | None:
        return self._diagnostics if self._fail_start else None


class _FakePorts:
    def __init__(self) -> None:
        self.busy: set[int] = set()

    def inspect(self, port: int) -> preflight_gate.PortObservation:
        if port in self.busy:
            return preflight_gate.PortObservation(port, "occupied", (999,))
        return preflight_gate.PortObservation(port, "free")


class _FakeProcesses:
    def __init__(self) -> None:
        self.records: tuple[gate.ProcessRecord, ...] = ()

    def snapshot(self) -> tuple[gate.ProcessRecord, ...]:
        return self.records


class _FakeObserver:
    def __init__(self, state: str = "absent") -> None:
        self._state = state

    def service_manager_entries(self, _profile: str) -> object:
        return gate.Observation(self._state, "fake", 0)

    def profile_processes(self, _profile: str) -> object:
        return gate.Observation(self._state, "fake", 0)

    def helper_processes(self) -> object:
        return gate.Observation(self._state, "fake", 0)


class _FakeCompanionRunner:
    def __init__(self, *, delete_removes: bool = True) -> None:
        self.delete_removes = delete_removes
        self.deleted = False
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, argv: Sequence[str], _environment: Mapping[str, str], _timeout: float
    ) -> RunResult:
        self.calls.append(tuple(argv[3:]))
        command = argv[3]
        if command == "delete":
            self.deleted = self.delete_removes
            return RunResult(0, "")
        if self.deleted:
            return RunResult(0, "Service: stopped\nNo tunnel exists for this profile\n")
        return RunResult(
            0,
            "Hostname: planted-host.opentunnel.xyz\nTunnel ID: planted-tunnel-0001\n"
            "Service: stopped\n",
        )


class _FakePublicRequester:
    """Ordered public HTTP responses; no socket or network access."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str, str, dict[str, str], bytes | None, float]] = []
        self.responses: list[gate.PublicHttpResponse | Exception] = [
            gate.PublicHttpResponse(
                200,
                (("Content-Type", "text/html; charset=utf-8"),),
                (
                    b'<!doctype html><html><body><form><input name="csrf_token" '
                    b'value="planted-value-0042-planted-value-0042"></form>'
                    b'<script src="/static/player/planted-asset-01.js"></script>'
                    b"</body></html>"
                ),
            ),
            gate.PublicHttpResponse(
                200,
                (("Content-Type", "application/javascript"),),
                b"window.probe = true;",
            ),
        ]

    def __call__(
        self,
        hostname: str,
        port: int,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> gate.PublicHttpResponse:
        self.calls.append(
            (hostname, port, method, path, dict(headers), body, timeout)
        )
        if not self.responses:
            raise RuntimeError("fake_public_responses_exhausted")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@dataclass(slots=True)
class FakeContext:
    deps: ProbeDependencies
    arguments: ProbeArguments
    ports: _FakePorts
    processes: _FakeProcesses
    runner: _FakeCompanionRunner
    scratch: Path
    state_base: Path
    patches: list
    services: list
    public_requester: _FakePublicRequester

    def close(self) -> None:
        import shutil

        for patcher in reversed(self.patches):
            patcher.stop()
        for target in (self.state_base, self.scratch):
            if target.exists() and not target.is_symlink():
                shutil.rmtree(target)


def build_fake_dependencies(
    scratch: Path,
    *,
    probe_id: str = "n3p-selftest",
    sha: str = "a" * 40,
    booking_id: str = "probe-booking-1",
    service_kwargs: Mapping[str, object] | None = None,
    write_lock: bool = True,
    lock_booking_id: str | None = None,
    runner: _FakeCompanionRunner | None = None,
    observer_state: str = "absent",
    identity_sha: str | None = None,
) -> FakeContext:
    """All-fake dependencies; the only real parts are paths and state helpers."""
    from unittest import mock

    import web.extensions.opentunnel_sharing.profile_state as profile_state_module

    root = scratch / "root"
    common = root / ".git"
    common.mkdir(parents=True)
    if write_lock:
        lock_dir = common / "neq-coordination" / "live-window.lock"
        lock_dir.mkdir(parents=True)
        (lock_dir / "holder.json").write_text(
            json.dumps({"booking_id": lock_booking_id or booking_id}) + "\n",
            encoding="ascii",
        )
    state_base: Path | None = None
    for suffix in "0123456789abcdef":
        candidate = REPO_ROOT / "tmp" / ("s" + suffix)
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        state_base = candidate
        break
    if state_base is None:
        raise RuntimeError("no short state base available")
    patches = [
        mock.patch.object(profile_state_module, "_REPOSITORY_ROOT", root / "protected"),
        mock.patch.object(profile_state_module, "_INSTALL_ROOT", root / "protected"),
    ]
    for patcher in patches:
        patcher.start()
    identity = preflight_gate.WorkspaceIdentity(
        git_sha=identity_sha or sha,
        worktree_clean=True,
        platform_key="darwin-arm64",
        git_common_dir=common,
        source_files_sha256="0" * 64,
        dependency_lock_sha256="0" * 64,
        route_contract_sha256="0" * 64,
        identity_freeze_sha256="0" * 64,
    )
    ports = _FakePorts()
    processes = _FakeProcesses()
    selected_runner = runner or _FakeCompanionRunner()
    public_requester = _FakePublicRequester()
    services: list = []

    def make_service(config: ProbeConfig) -> FakeSharingService:
        service = FakeSharingService(config, **dict(service_kwargs or {}))
        services.append(service)
        return service

    gate_deps = gate.LiveGateDependencies(
        root=root,
        identity_reader=lambda _root: identity,
        port_inspector=ports,
        preflight_reader=gate.load_preflight_report,
        companion_verifier=lambda sandbox, platform: {
            "path": sandbox / "runtime" / "opentunnel" / "opentunnel",
            "sha256": "0" * 64,
            "platform": platform,
        },
        sandbox_validator=lambda r: r / gate.CAPTURE_RELATIVE,
        host_factory=lambda *_args: None,
        api_factory=lambda: None,
    )
    deps = ProbeDependencies(
        root=root,
        gate_dependencies=gate_deps,
        service_factory=make_service,
        process_table=processes,
        port_inspector=ports,
        companion_runner=selected_runner,
        identity_observer_factory=lambda _layout, _path: _FakeObserver(observer_state),
        state_base_provider=lambda: state_base,
        public_requester=public_requester,
        getloadavg=lambda: (1.0, 2.0, 3.0),
        utc_now=lambda: datetime.now(timezone.utc),
        sleep=lambda _seconds: None,
        ready_deadline_seconds=5.0,
        census_settle_seconds=0.0,
        install_egress_guard=True,
    )
    return FakeContext(
        deps=deps,
        arguments=ProbeArguments(probe_id, sha, booking_id),
        ports=ports,
        processes=processes,
        runner=selected_runner,
        scratch=scratch,
        state_base=state_base,
        patches=patches,
        services=services,
        public_requester=public_requester,
    )


def selftest() -> int:
    """Run the happy and failing flows against fakes; no network."""
    import shutil

    results: list[tuple[str, bool]] = []
    scratch_parent = REPO_ROOT / "tmp" / "n3-diag"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    for name, kwargs, expected in (
        ("happy", {}, ("PASS", 0)),
        (
            "failing_start",
            {
                "fail_start": True,
                "diagnostics": {
                    "summary": {"reason": "companion_failed"},
                    "detail": {"note": "x"},
                },
            },
            ("FAIL", 1),
        ),
        ("public_shell_failure", {}, ("FAIL", 1)),
    ):
        scratch = scratch_parent / ("selftest-%s-%d" % (name, os.getpid()))
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir()
        context = build_fake_dependencies(
            scratch,
            probe_id="n3p-selftest-" + name.replace("_", "-"),
            service_kwargs=kwargs,
        )
        try:
            if name == "public_shell_failure":
                context.public_requester.responses = [
                    gate.PublicHttpResponse(
                        403,
                        (("Content-Type", "application/json"),),
                        b'{"error":"request_rejected"}',
                    )
                ]
            verdict, code = run_probe(context.arguments, context.deps)
            ok = (verdict.get("verdict"), code) == expected and verdict.get(
                "diagnosis_only"
            ) is True
            step_names = [item["name"] for item in verdict.get("steps", [])]
            if name == "happy":
                ok = ok and (
                    verdict.get("public_get_without_origin", {}).get(
                        "shell_status"
                    )
                    == 200
                    and verdict.get("public_get_without_origin", {}).get(
                        "asset_status"
                    )
                    == 200
                    and "public_shell_get" in step_names
                    and "public_asset_get" in step_names
                )
                detail = " public_shell_get=200 public_asset_get=200"
            elif name == "public_shell_failure":
                ok = ok and (
                    verdict.get("reason") == "public_shell_get_failed"
                    and verdict.get("public_get_without_origin", {}).get(
                        "shell_status"
                    )
                    == 403
                    and "public_shell_get" in step_names
                    and "stop_sharing" in step_names
                )
                detail = " public_shell_get=403"
            else:
                detail = ""
            results.append((name + detail, ok))
        finally:
            context.close()
    for name, ok in results:
        print("[%s] selftest %s" % ("PASS" if ok else "FAIL", name))
    return 0 if all(ok for _name, ok in results) else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the live provider-free probe")
    run.add_argument("--probe-id", required=True)
    run.add_argument("--sha", required=True)
    run.add_argument("--booking-id", required=True)
    sub.add_parser("selftest", help="offline flow against fakes; no network")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "selftest":
        return selftest()
    arguments = ProbeArguments(args.probe_id, args.sha, args.booking_id)
    verdict, code = run_probe(arguments, default_dependencies())
    print(json.dumps(verdict, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
