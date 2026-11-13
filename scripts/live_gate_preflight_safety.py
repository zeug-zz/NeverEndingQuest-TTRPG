# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fail-closed, opt-in network guard and child-environment builder.

The guard is intended for provider-free live-gate preflight processes only. It
permits numeric loopback sockets and blocks DNS names other than a synthetic
localhost mapping. It does not start a host, listener, or sandbox.
"""

from __future__ import annotations

import contextvars
import hashlib
import ipaddress
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from collections.abc import Mapping
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Iterator, Sequence


ENABLE_GUARD_ENV = "NEQ_PREFLIGHT_NETWORK_GUARD"
ACTIVE_GUARD_ENV = "NEQ_PREFLIGHT_NETWORK_GUARD_ACTIVE"
SANITIZED_ENV = "NEQ_PREFLIGHT_ENV_SANITIZED"
STARTUP_GUARD_ENV = "NEQ_PREFLIGHT_STARTUP_GUARD_ACTIVE"
REQUIRE_STARTUP_GUARD_ENV = "NEQ_PREFLIGHT_STARTUP_GUARD_REQUIRED"
CONNECT_CANARY_ENV = "NEQ_PREFLIGHT_CONNECT_CANARY_DENIED"
SUBPROCESS_CANARY_ENV = "NEQ_PREFLIGHT_SUBPROCESS_CANARY_DENIED"
CANARY_REPORT_ENV = "NEQ_PREFLIGHT_STARTUP_CANARY_REPORT"
PROCESS_ROLE_ENV = "NEQ_PREFLIGHT_PROCESS_ROLE"
GUARD_DIRECTORY_ENV = "NEQ_PREFLIGHT_GUARD_DIRECTORY"
PROJECT_ROOT_ENV = "NEQ_PREFLIGHT_PROJECT_ROOT"
EXPECTED_PYTHON_ENV = "NEQ_PREFLIGHT_EXPECTED_PYTHON"
EXPECTED_PREFIX_ENV = "NEQ_PREFLIGHT_EXPECTED_PREFIX"
GUARD_EVENTS_PATH_ENV = "NEQ_PREFLIGHT_GUARD_EVENTS_PATH"
RUN_ID_ENV = "NEQ_PREFLIGHT_RUN_ID"
CANARY_SIGNAL_FD = 198
CANARY_REPORT_FD = 199
CANARY_SIGNAL = b"NEQ_PREFLIGHT_SITE_STARTUP_CANARY_V1\n"
GUARD_DIRECTORY = Path("scripts/live_gate_preflight_guard")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESS_ROLES = frozenset(("parent", "host"))
_SECRET_ENV_NAME = re.compile(
    r"(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)
_PROXY_ENV_NAME = re.compile(r"(?:^|_)PROXY$", re.IGNORECASE)
_SAFE_ENV_NAMES = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "PYTHONHASHSEED",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
)
_KNOWN_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
)
SANDBOX_PROVIDER_KEY_PLACEHOLDER = "preflight-stub-not-a-key"
_RUNTIME_INJECTED_ENV_NAMES = ("LC_CTYPE", "__CF_USER_TEXT_ENCODING")
GUARD_EVENT_ROOT = Path(
    "tmp/router-rollout/live-gate-preflight/profile-characterization"
)
GUARD_EVENT_MAX_COUNT = 4096
GUARD_EVENT_MAX_BYTES = 512_000
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

class NetworkGuardError(PermissionError):
    """Raised before a non-loopback network or DNS operation is attempted."""


class SafetyConfigurationError(ValueError):
    """Raised when the isolated preflight environment is not safe to use."""


class InvocationIdentityMismatch(SafetyConfigurationError):
    """Raised when declared and intended worker invocation identities differ."""

    def __init__(self, evidence: Mapping[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__("preflight invocation identity mismatch")


_GUARD_INSTALLED = False
_SUBPROCESS_GUARD_INSTALLED = False
_ORIGINAL_SOCKET_METHODS: dict[str, Any] = {}
_ORIGINAL_DNS_FUNCTIONS: dict[str, Any] = {}
_ORIGINAL_POPEN: Any = None
_GUARDED_SOCKET_METHODS: dict[str, Any] = {}
_GUARDED_DNS_FUNCTIONS: dict[str, Any] = {}
_GUARD_EVENTS: list[dict[str, Any]] = []
_GUARD_EVENT_SEQUENCE = 0
_GUARD_EVENT_OVERFLOW = False
_GUARD_EVENT_SINK: Path | None = None
_SUBPROCESS_AUTHORIZATION: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("neq_preflight_subprocess_authorization", default=None)
)


def _guard_event_target(address: Any) -> dict[str, Any]:
    host: Any = None
    port: Any = None
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if len(address) > 1:
            port = address[1]
    target_host: str | None = None
    target_host_sha256: str | None = None
    if isinstance(host, str) and host:
        raw_host = host.split("%", 1)[0]
        try:
            target_host = str(ipaddress.ip_address(raw_host))
        except ValueError:
            target_host_sha256 = hashlib.sha256(host.encode("utf-8")).hexdigest()
    else:
        target_host_sha256 = hashlib.sha256(b"<missing-host>").hexdigest()
    target_port = port if type(port) is int and 0 <= port <= 65535 else None
    return {
        "target_host": target_host,
        "target_port": target_port,
        "target_host_sha256": target_host_sha256,
    }


def _validate_guard_event_path(path: str | Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or _SAFE_RUN_ID.fullmatch(run_id) is None:
        raise SafetyConfigurationError("preflight guard-event run identity is invalid")
    root = PROJECT_ROOT.resolve(strict=True)
    expected = root / GUARD_EVENT_ROOT / run_id / "guard-events.jsonl"
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate != expected:
        raise SafetyConfigurationError("preflight guard-event path identity is invalid")
    cursor = root
    for part in expected.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SafetyConfigurationError(
                "preflight guard-event path traverses a symlink"
            )
    if not expected.parent.is_dir():
        raise SafetyConfigurationError("preflight guard-event directory is unavailable")
    return expected


def _write_guard_event(path: Path, event: Mapping[str, Any], *, create: bool) -> None:
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        get_uid = getattr(os, "getuid", None)
        current_uid = get_uid() if callable(get_uid) else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
        ):
            raise SafetyConfigurationError("preflight guard-event file is invalid")
        payload = json.dumps(
            dict(event), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii") + b"\n"
        if metadata.st_size + len(payload) > GUARD_EVENT_MAX_BYTES:
            raise SafetyConfigurationError("preflight guard-event capacity exceeded")
        if os.write(descriptor, payload) != len(payload):
            raise SafetyConfigurationError("preflight guard-event write was incomplete")
        os.fsync(descriptor)
    except OSError as exc:
        raise SafetyConfigurationError("preflight guard-event write failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _record_guard_event(
    event_type: str,
    *,
    operation: str | None = None,
    decision: str | None = None,
    address: Any = None,
    command_sha256: str | None = None,
    startup_command_sha256: str | None = None,
    interpreter: Mapping[str, str] | None = None,
    working_directory: str | None = None,
    child_pid: int | None = None,
    child_is_python: bool | None = None,
) -> dict[str, Any]:
    global _GUARD_EVENT_SEQUENCE, _GUARD_EVENT_OVERFLOW
    if len(_GUARD_EVENTS) >= GUARD_EVENT_MAX_COUNT:
        _GUARD_EVENT_OVERFLOW = True
        raise NetworkGuardError("preflight guard-event capacity exceeded")
    _GUARD_EVENT_SEQUENCE += 1
    target = (
        _guard_event_target(address)
        if event_type == "network_attempt"
        else {
            "target_host": None,
            "target_port": None,
            "target_host_sha256": None,
        }
    )
    event: dict[str, Any] = {
        "schema_version": 1,
        "sequence": _GUARD_EVENT_SEQUENCE,
        "event_type": event_type,
        "pid": os.getpid(),
        "process_group_id": os.getpgrp(),
        "process_role": os.environ.get(PROCESS_ROLE_ENV, ""),
        "run_id": os.environ.get(RUN_ID_ENV, ""),
        "observed_at_ns": time.time_ns(),
        "operation": operation,
        "decision": decision,
        **target,
        "command_sha256": command_sha256 or startup_command_sha256,
        "child_pid": child_pid,
        "child_is_python": child_is_python,
        "guard_active": True if event_type == "guard_startup" else None,
        "interpreter": dict(interpreter) if interpreter is not None else None,
        "working_directory": working_directory,
    }
    _GUARD_EVENTS.append(event)
    if _GUARD_EVENT_SINK is not None:
        try:
            _write_guard_event(_GUARD_EVENT_SINK, event, create=False)
        except SafetyConfigurationError as exc:
            _GUARD_EVENT_OVERFLOW = True
            raise NetworkGuardError("preflight guard-event persistence failed") from exc
    return event


def record_startup_guard_event() -> dict[str, Any]:
    """Record the guard's first per-process event before application entry."""
    command = current_invocation_command()
    command_sha256 = hashlib.sha256(
        json.dumps(command, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return _record_guard_event(
        "guard_startup",
        startup_command_sha256=command_sha256,
        interpreter={
            "executable": sys.executable,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        },
        working_directory=str(Path.cwd()),
    )


def guard_event_snapshot(*, run_id: str | None = None) -> dict[str, Any]:
    """Return a detached, run-bound snapshot of this process's guard events."""
    events = []
    for item in _GUARD_EVENTS:
        event = dict(item)
        if run_id is not None:
            event["run_id"] = run_id
        events.append(event)
    return {"events": events, "complete": not _GUARD_EVENT_OVERFLOW}


def configure_guard_event_sink(path: str | Path, *, run_id: str) -> Path:
    """Bind this process and future workers to one private per-run event journal."""
    global _GUARD_EVENT_SINK
    selected = _validate_guard_event_path(path, run_id)
    if _GUARD_EVENT_SINK is not None:
        if _GUARD_EVENT_SINK != selected:
            raise SafetyConfigurationError("preflight guard-event sink was already bound")
        return selected
    os.environ[RUN_ID_ENV] = run_id
    os.environ[GUARD_EVENTS_PATH_ENV] = str(selected)
    try:
        descriptor = os.open(
            selected,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise SafetyConfigurationError(
            "preflight guard-event journal is unavailable"
        ) from exc
    else:
        os.close(descriptor)
    _GUARD_EVENT_SINK = selected
    for original in _GUARD_EVENTS:
        event = dict(original)
        event["run_id"] = run_id
        try:
            _write_guard_event(selected, event, create=False)
        except SafetyConfigurationError as exc:
            raise SafetyConfigurationError(
                "preflight guard-event journal is incomplete"
            ) from exc
    return selected


def _bind_guard_event_sink_from_environment() -> None:
    """Attach a launched process to its already-created per-run journal."""
    global _GUARD_EVENT_SINK
    run_id = os.environ.get(RUN_ID_ENV)
    path = os.environ.get(GUARD_EVENTS_PATH_ENV)
    if run_id is None and path is None:
        return
    if run_id is None or path is None:
        raise SafetyConfigurationError("preflight guard-event identity is incomplete")
    selected = _validate_guard_event_path(path, run_id)
    if _GUARD_EVENT_SINK is not None and _GUARD_EVENT_SINK != selected:
        raise SafetyConfigurationError("preflight guard-event sink identity changed")
    try:
        descriptor = os.open(
            selected, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        )
        metadata = os.fstat(descriptor)
        get_uid = getattr(os, "getuid", None)
        current_uid = get_uid() if callable(get_uid) else None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (current_uid is not None and metadata.st_uid != current_uid)
        ):
            raise SafetyConfigurationError("preflight guard-event journal is invalid")
    except OSError as exc:
        raise SafetyConfigurationError("preflight guard-event journal is unavailable") from exc
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    _GUARD_EVENT_SINK = selected


def _guard_event_unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate guard-event key")
        result[key] = value
    return result


def read_guard_event_journal(
    path: str | Path, *, run_id: str
) -> tuple[list[dict[str, Any]], bytes]:
    """Read and validate a complete per-run guard journal without following links."""
    selected = _validate_guard_event_path(path, run_id)
    descriptor: int | None = None
    try:
        descriptor = os.open(selected, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > GUARD_EVENT_MAX_BYTES:
            raise SafetyConfigurationError("preflight guard-event journal is invalid")
        chunks: list[bytes] = []
        remaining = GUARD_EVENT_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64_000, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > GUARD_EVENT_MAX_BYTES or (raw and not raw.endswith(b"\n")):
            raise SafetyConfigurationError("preflight guard-event journal is incomplete")
        events: list[dict[str, Any]] = []
        for line in raw.splitlines():
            value = json.loads(
                line.decode("ascii"), object_pairs_hook=_guard_event_unique_object
            )
            if not isinstance(value, Mapping):
                raise SafetyConfigurationError("preflight guard-event entry is invalid")
            events.append(dict(value))
        if not validate_guard_event_records(events, expected_run_id=run_id):
            raise SafetyConfigurationError(
                "preflight guard-event journal failed validation"
            )
        return events, raw
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SafetyConfigurationError(
            "preflight guard-event journal cannot be read"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def validate_guard_event_records(
    events: Any,
    *,
    expected_run_id: str | None = None,
    expected_pid: int | None = None,
    require_startup_canaries: bool = False,
) -> bool:
    """Validate event schema, per-process order, and required startup canaries."""
    fields = {
        "schema_version",
        "sequence",
        "event_type",
        "pid",
        "process_group_id",
        "process_role",
        "run_id",
        "observed_at_ns",
        "operation",
        "decision",
        "target_host",
        "target_port",
        "target_host_sha256",
        "command_sha256",
        "child_pid",
        "child_is_python",
        "guard_active",
        "interpreter",
        "working_directory",
    }
    if not isinstance(events, list) or not events or len(events) > GUARD_EVENT_MAX_COUNT:
        return False
    by_pid: dict[int, list[Mapping[str, Any]]] = {}
    for event in events:
        if not isinstance(event, Mapping) or set(event) != fields:
            return False
        pid = event.get("pid")
        run_id = event.get("run_id")
        role = event.get("process_role")
        if (
            type(event.get("schema_version")) is not int
            or event.get("schema_version") != 1
            or type(event.get("sequence")) is not int
            or event.get("sequence") < 1
            or type(pid) is not int
            or pid <= 0
            or type(event.get("process_group_id")) is not int
            or event.get("process_group_id") <= 0
            or (expected_pid is not None and pid != expected_pid)
            or role not in PROCESS_ROLES
            or not isinstance(run_id, str)
            or (expected_run_id is not None and run_id != expected_run_id)
            or type(event.get("observed_at_ns")) is not int
            or event.get("observed_at_ns") <= 0
        ):
            return False
        event_type = event.get("event_type")
        if event_type == "guard_startup":
            interpreter = event.get("interpreter")
            if (
                event.get("guard_active") is not True
                or not isinstance(interpreter, Mapping)
                or set(interpreter) != {"executable", "prefix", "base_prefix"}
                or not all(isinstance(interpreter.get(key), str) for key in interpreter)
                or not isinstance(event.get("working_directory"), str)
                or not isinstance(event.get("command_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", event["command_sha256"]) is None
                or event.get("operation") is not None
                or event.get("decision") is not None
                or event.get("target_host") is not None
                or event.get("target_port") is not None
                or event.get("target_host_sha256") is not None
                or event.get("child_pid") is not None
                or event.get("child_is_python") is not None
            ):
                return False
        elif event_type == "network_attempt":
            target_host = event.get("target_host")
            target_hash = event.get("target_host_sha256")
            if (
                event.get("operation") not in (
                    "connect",
                    "connect_ex",
                    "bind",
                    "sendto",
                    "getaddrinfo",
                    "gethostbyname",
                    "gethostbyname_ex",
                    "gethostbyaddr",
                    "getnameinfo",
                )
                or event.get("decision") not in ("allowed", "denied")
                or (target_host is None) == (target_hash is None)
                or (target_host is not None and not isinstance(target_host, str))
                or (
                    target_hash is not None
                    and (
                        not isinstance(target_hash, str)
                        or re.fullmatch(r"[0-9a-f]{64}", target_hash) is None
                    )
                )
                or (
                    event.get("target_port") is not None
                    and (
                        type(event.get("target_port")) is not int
                        or not 0 <= event["target_port"] <= 65535
                    )
                )
                or event.get("command_sha256") is not None
                or event.get("guard_active") is not None
                or event.get("interpreter") is not None
                or event.get("working_directory") is not None
                or event.get("child_pid") is not None
                or event.get("child_is_python") is not None
            ):
                return False
        elif event_type == "subprocess_attempt":
            if (
                event.get("operation") != "Popen"
                or event.get("decision") not in ("allowed", "denied")
                or not isinstance(event.get("command_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", event["command_sha256"]) is None
                or event.get("target_host") is not None
                or event.get("target_port") is not None
                or event.get("target_host_sha256") is not None
                or event.get("guard_active") is not None
                or event.get("interpreter") is not None
                or event.get("working_directory") is not None
                or event.get("child_pid") is not None
                or event.get("child_is_python") is not None
            ):
                return False
        elif event_type == "subprocess_started":
            if (
                event.get("operation") != "Popen"
                or event.get("decision") != "started"
                or not isinstance(event.get("command_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", event["command_sha256"]) is None
                or type(event.get("child_pid")) is not int
                or event.get("child_pid") <= 0
                or type(event.get("child_is_python")) is not bool
                or event.get("target_host") is not None
                or event.get("target_port") is not None
                or event.get("target_host_sha256") is not None
                or event.get("guard_active") is not None
                or event.get("interpreter") is not None
                or event.get("working_directory") is not None
            ):
                return False
        else:
            return False
        by_pid.setdefault(pid, []).append(event)

    for process_events in by_pid.values():
        process_events.sort(key=lambda event: int(event["sequence"]))
        if [event["sequence"] for event in process_events] != list(
            range(1, len(process_events) + 1)
        ):
            return False
        startup_events = [
            event for event in process_events if event.get("event_type") == "guard_startup"
        ]
        if len(startup_events) != 1 or startup_events[0].get("sequence") != 1:
            return False
        if require_startup_canaries:
            denied_connect = any(
                event.get("event_type") == "network_attempt"
                and event.get("operation") == "connect"
                and event.get("decision") == "denied"
                and event.get("target_host") == "192.0.2.1"
                and event.get("target_port") == 8360
                for event in process_events
            )
            denied_subprocess = any(
                event.get("event_type") == "subprocess_attempt"
                and event.get("decision") == "denied"
                for event in process_events
            )
            if not denied_connect or not denied_subprocess:
                return False
    return True


class _GuardedPopen(subprocess.Popen):
    """Reject every child launch unless an exact, one-use authorization exists."""

    def __init__(self, args: Any, *positional: Any, **kwargs: Any) -> None:
        require_guard_active()
        authorization = _SUBPROCESS_AUTHORIZATION.get()
        command_tuple = _command_tuple(args)
        authorized = not (
            authorization is None
            or authorization.get("used") is True
            or command_tuple != authorization.get("command")
            or _path_text(kwargs.get("cwd")) != authorization.get("cwd")
            or kwargs.get("env") != authorization.get("env")
            or tuple(kwargs.get("pass_fds", ())) != authorization.get("pass_fds")
            or kwargs.get("close_fds", True) is not authorization.get("close_fds")
            or kwargs.get("shell", False) is not False
            or kwargs.get("executable") is not None
            or kwargs.get("preexec_fn") is not None
        )
        command_digest = hashlib.sha256(
            json.dumps(
                list(command_tuple) if command_tuple is not None else ["<invalid>"],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        _record_guard_event(
            "subprocess_attempt",
            operation="Popen",
            decision="allowed" if authorized else "denied",
            command_sha256=command_digest,
        )
        if not authorized:
            raise NetworkGuardError("unguarded or mismatched subprocess launch is denied")
        assert authorization is not None
        authorization["used"] = True
        super().__init__(args, *positional, **kwargs)
        expected_python = os.environ.get(EXPECTED_PYTHON_ENV)
        child_is_python = bool(
            command_tuple and expected_python and command_tuple[0] == expected_python
        )
        try:
            _record_guard_event(
                "subprocess_started",
                operation="Popen",
                decision="started",
                command_sha256=command_digest,
                child_pid=self.pid,
                child_is_python=child_is_python,
            )
        except BaseException:
            try:
                self.kill()
                self.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
            raise


def build_guarded_environment(
    source_environment: Mapping[str, str] | None = None,
    *,
    project_root: str | Path = PROJECT_ROOT,
    process_role: str = "parent",
    interpreter_root: str | Path | None = None,
    run_id: str | None = None,
    guard_events_path: str | Path | None = None,
) -> dict[str, str]:
    """Build a minimal environment without copying secrets or proxy values.

    Only a small allowlist of non-secret values is copied. Secret-looking
    variable names are retained as blank values, and all proxy variables are
    blanked without reading their values. The dedicated guard directory is the
    first PYTHONPATH entry, followed by the repository root.
    """
    root = Path(project_root).resolve(strict=True)
    runtime_root = (
        root if interpreter_root is None else Path(interpreter_root).resolve(strict=True)
    )
    guard_directory = root / GUARD_DIRECTORY
    if guard_directory.is_symlink() or not guard_directory.is_dir():
        raise SafetyConfigurationError("dedicated preflight guard directory is unavailable")
    if process_role not in PROCESS_ROLES:
        raise SafetyConfigurationError("preflight process role is invalid")
    source = os.environ if source_environment is None else source_environment
    result: dict[str, str] = {}
    for name in _SAFE_ENV_NAMES:
        if name in source:
            result[name] = str(source[name])
    result["PYTHONPATH"] = os.pathsep.join((str(guard_directory), str(root)))
    result["NEQ_OPEN_BROWSER"] = "0"
    result["TMPDIR"] = "tmp"
    result["TEMP"] = "tmp"
    result["TMP"] = "tmp"
    result[ENABLE_GUARD_ENV] = "1"
    result[REQUIRE_STARTUP_GUARD_ENV] = "1"
    result[GUARD_DIRECTORY_ENV] = str(guard_directory)
    result[PROJECT_ROOT_ENV] = str(root)
    result[EXPECTED_PYTHON_ENV] = str(runtime_root / ".venv" / "bin" / "python")
    result[EXPECTED_PREFIX_ENV] = str(runtime_root / ".venv")
    result[PROCESS_ROLE_ENV] = process_role
    if (run_id is None) != (guard_events_path is None):
        raise SafetyConfigurationError("preflight guard-event identity is incomplete")
    if run_id is not None and guard_events_path is not None:
        event_path = _validate_guard_event_path(guard_events_path, run_id)
        result[RUN_ID_ENV] = run_id
        result[GUARD_EVENTS_PATH_ENV] = str(event_path)

    for name in source:
        if _SECRET_ENV_NAME.search(name) or name in _KNOWN_PROVIDER_KEYS:
            result[name] = ""
        if _PROXY_ENV_NAME.search(name):
            result[name] = ""
    for name in _KNOWN_PROVIDER_KEYS:
        result[name] = ""
    return result


def sanitize_current_environment() -> None:
    """Blank secret and proxy variables in-place without reading their values."""
    for name in tuple(os.environ):
        if _SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name):
            os.environ[name] = ""
    for name in _KNOWN_PROVIDER_KEYS:
        os.environ[name] = ""
    os.environ[SANITIZED_ENV] = "1"


def sanitized_environment_snapshot(
    source_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy environment identity while never reading secret/proxy values."""
    source = os.environ if source_environment is None else source_environment
    snapshot: dict[str, str] = {}
    for name in source:
        if _SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name):
            snapshot[name] = ""
        else:
            snapshot[name] = str(source[name])
    for name in _KNOWN_PROVIDER_KEYS:
        snapshot[name] = ""
    return snapshot


def activate_preflight_safety() -> None:
    """Sanitize this process and install the deny guard, idempotently."""
    if _GUARD_INSTALLED:
        require_guard_active()
        install_subprocess_deny_guard()
        return
    os.environ.pop(ACTIVE_GUARD_ENV, None)
    os.environ.pop(SANITIZED_ENV, None)
    sanitize_current_environment()
    install_network_deny_guard()
    install_subprocess_deny_guard()
    _bind_guard_event_sink_from_environment()


def validate_sandbox_config_location(
    config_path: str | Path,
    *,
    sandbox_root: str | Path,
    project_root: str | Path,
) -> Path:
    """Require the config location to be the copied sandbox config, not config.py.

    This path-only check reads no configuration bytes. The later launcher must
    additionally require the copied file to exist and reject symlinks.
    """
    project = Path(project_root).resolve(strict=True)
    sandbox = Path(sandbox_root)
    config = Path(config_path)
    if sandbox.is_absolute() or config.is_absolute():
        raise SafetyConfigurationError("sandbox config paths must be project-relative")
    if ".." in sandbox.parts or ".." in config.parts:
        raise SafetyConfigurationError("sandbox config path traversal is forbidden")
    if sandbox != Path("tmp/combat_capture"):
        raise SafetyConfigurationError("sandbox root must be tmp/combat_capture")
    if config != sandbox / "config.py":
        raise SafetyConfigurationError("config path must be the copied sandbox config.py")

    tmp_root = project / "tmp"
    if tmp_root.is_symlink():
        raise SafetyConfigurationError("project tmp/ must not be a symlink")
    expected_root = project / sandbox
    expected_config = project / config
    if expected_root.is_symlink() or expected_config.is_symlink():
        raise SafetyConfigurationError("sandbox config path must not traverse symlinks")
    resolved_root = expected_root.resolve(strict=False)
    try:
        resolved_root.relative_to((project / "tmp").resolve(strict=False))
    except ValueError as exc:
        raise SafetyConfigurationError("sandbox root escapes project tmp/") from exc
    resolved_config = (project / config).resolve(strict=False)
    if resolved_config == project / "config.py":
        raise SafetyConfigurationError("real project config.py is forbidden")
    try:
        resolved_config.relative_to(resolved_root)
    except ValueError as exc:
        raise SafetyConfigurationError("sandbox config escapes the isolated copy") from exc
    return resolved_config


def validate_guarded_sandbox_path(
    sandbox_root: str | Path,
    *,
    project_root: str | Path,
) -> tuple[Path, Path]:
    """Validate a sandbox identity without modifying the capture copy."""
    project = Path(project_root).resolve(strict=True)
    raw_root = PurePosixPath(str(sandbox_root))
    if (
        raw_root.is_absolute()
        or ".." in raw_root.parts
        or "\\" in str(sandbox_root)
        or len(raw_root.parts) < 2
        or raw_root.parts[0] != "tmp"
    ):
        raise SafetyConfigurationError("sandbox root must be project-relative under tmp/")

    if raw_root.parts[0] != "tmp":
        raise SafetyConfigurationError("sandbox root must stay below project tmp/")
    guard_directory = project / GUARD_DIRECTORY
    if guard_directory.is_symlink() or not guard_directory.is_dir():
        raise SafetyConfigurationError("dedicated preflight guard directory is unavailable")
    return (GUARD_DIRECTORY / "sitecustomize.py", Path("scripts") / "sitecustomize.py")


def build_guarded_sandbox_environment(
    sandbox_root: str | Path,
    *,
    project_root: str | Path,
    source_environment: Mapping[str, str] | None = None,
    process_role: str = "host",
    interpreter_root: str | Path | None = None,
    run_id: str | None = None,
    guard_events_path: str | Path | None = None,
) -> dict[str, str]:
    """Build a guarded environment without touching any sandbox files."""
    validate_guarded_sandbox_path(sandbox_root, project_root=project_root)
    return build_guarded_environment(
        source_environment,
        project_root=project_root,
        process_role=process_role,
        interpreter_root=interpreter_root,
        run_id=run_id,
        guard_events_path=guard_events_path,
    )


def expected_guarded_pythonpath(project_root: str | Path = PROJECT_ROOT) -> str:
    """Return the exact dedicated-guard-then-repository-root path order."""
    root = Path(project_root).resolve(strict=True)
    return os.pathsep.join((str(root / GUARD_DIRECTORY), str(root)))


def install_subprocess_deny_guard() -> None:
    """Patch subprocess.Popen so only exact one-use authorized launches proceed."""
    global _SUBPROCESS_GUARD_INSTALLED, _ORIGINAL_POPEN
    if _SUBPROCESS_GUARD_INSTALLED:
        if subprocess.Popen is not _GuardedPopen:
            raise NetworkGuardError("preflight subprocess deny guard was replaced")
        return
    if subprocess.Popen is _GuardedPopen:
        _SUBPROCESS_GUARD_INSTALLED = True
        return
    _ORIGINAL_POPEN = subprocess.Popen
    subprocess.Popen = _GuardedPopen  # type: ignore[assignment]
    _SUBPROCESS_GUARD_INSTALLED = True


@contextmanager
def authorize_subprocess_launch(
    command: Sequence[str],
    *,
    cwd: str | Path | None,
    env: Mapping[str, str] | None,
    pass_fds: Sequence[int] = (),
    close_fds: bool = True,
) -> Iterator[None]:
    """Authorize one exact Popen call, including inherited descriptors."""
    require_guard_active()
    if not _SUBPROCESS_GUARD_INSTALLED or subprocess.Popen is not _GuardedPopen:
        raise NetworkGuardError("preflight subprocess deny guard is not active")
    command_tuple = _command_tuple(command)
    if command_tuple is None:
        raise NetworkGuardError("authorized subprocess command is invalid")
    descriptor_tuple = tuple(pass_fds)
    if (
        any(type(descriptor) is not int or descriptor < 0 for descriptor in descriptor_tuple)
        or len(set(descriptor_tuple)) != len(descriptor_tuple)
        or type(close_fds) is not bool
        or (descriptor_tuple and not close_fds)
        or (descriptor_tuple and os.name != "posix")
    ):
        raise NetworkGuardError("authorized subprocess descriptor policy is invalid")
    authorization = {
        "command": command_tuple,
        "cwd": _path_text(cwd),
        "env": None if env is None else dict(env),
        "pass_fds": descriptor_tuple,
        "close_fds": close_fds,
        "used": False,
    }
    if _SUBPROCESS_AUTHORIZATION.get() is not None:
        raise NetworkGuardError("nested subprocess authorization is denied")
    token = _SUBPROCESS_AUTHORIZATION.set(authorization)
    try:
        yield
        if authorization.get("used") is not True:
            raise NetworkGuardError("authorized subprocess launch was not consumed")
    finally:
        _SUBPROCESS_AUTHORIZATION.reset(token)


def run_guarded_subprocess(
    command: Sequence[str],
    *,
    cwd: str | Path | None,
    env: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run one locally authorized command through the guarded Popen boundary."""
    selected_env = None if env is None else dict(env)
    with authorize_subprocess_launch(command, cwd=cwd, env=selected_env):
        return subprocess.run(list(command), cwd=cwd, env=selected_env, **kwargs)


def run_startup_canaries(
    *,
    process_role: str | None = None,
    command: Sequence[str] | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Prove socket and exact-invocation subprocess denial before program entry."""
    require_guard_active()
    if not _SUBPROCESS_GUARD_INSTALLED or subprocess.Popen is not _GuardedPopen:
        raise NetworkGuardError("preflight subprocess deny guard is not active")
    selected_command = list(
        command if command is not None else current_invocation_command()
    )
    selected_cwd = os.fspath(cwd if cwd is not None else Path.cwd())
    selected_env = (
        sanitized_environment_snapshot() if env is None else dict(env)
    )
    if (
        not selected_command
        or any(
            not isinstance(part, str)
            or not part
            or _SECRET_ENV_NAME.search(part)
            for part in selected_command
        )
    ):
        raise NetworkGuardError("startup canary command identity is invalid")
    role = process_role or os.environ.get(PROCESS_ROLE_ENV, "")
    if role not in PROCESS_ROLES:
        raise NetworkGuardError("startup canary process role is invalid")

    try:
        socket.socket.connect(_CanarySocket(), ("192.0.2.1", 8360))
    except NetworkGuardError:
        connect_denied = True
    else:
        connect_denied = False

    subprocess_canary_command = [sys.executable, "-c", "pass"]
    subprocess_canary_environment = {
        "PATH": selected_env.get("PATH", ""),
        "PYTHONPATH": "",
        "PYTHONNOUSERSITE": "1",
    }
    try:
        canary_child = subprocess.Popen(
            subprocess_canary_command,
            cwd=selected_cwd,
            env=subprocess_canary_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except NetworkGuardError:
        subprocess_denied = True
    else:
        subprocess_denied = False
        try:
            canary_child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            canary_child.kill()
            canary_child.wait(timeout=2.0)
        raise NetworkGuardError("preflight subprocess deny guard allowed its canary")
    if not connect_denied or not subprocess_denied:
        raise NetworkGuardError("preflight startup canary did not fail closed")

    guard_events = guard_event_snapshot()
    if (
        guard_events["complete"] is not True
        or not validate_guard_event_records(
            guard_events["events"],
            expected_pid=os.getpid(),
            require_startup_canaries=True,
        )
    ):
        raise NetworkGuardError("preflight startup guard events are incomplete")

    interpreter = {
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    }
    if (
        interpreter["executable"] != os.environ.get(EXPECTED_PYTHON_ENV)
        or interpreter["prefix"] != os.environ.get(EXPECTED_PREFIX_ENV)
        or interpreter["prefix"] == interpreter["base_prefix"]
    ):
        raise NetworkGuardError("repository virtual-environment identity is invalid")
    command_digest = hashlib.sha256(
        json.dumps(selected_command, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    environment_digest = _startup_environment_digest(selected_env)
    return {
        "process_role": role,
        "pid": os.getpid(),
        "startup_observed_at_ns": time.time_ns(),
        "command": selected_command,
        "command_sha256": command_digest,
        "environment_sha256": environment_digest,
        "working_directory": selected_cwd,
        "guard_active": True,
        "non_loopback_connect_denied": connect_denied,
        "subprocess_launch_denied": subprocess_denied,
        "interpreter": interpreter,
        "guard_events_complete": True,
        "guard_events": guard_events["events"],
    }


def run_startup_process_canary(
    *,
    command: Sequence[str] | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Run an exact-invocation clone that exits from dedicated sitecustomize.

    The canary signal and report use inherited file descriptors so the command,
    environment, and working directory remain identical to the eventual launch.
    """
    require_startup_guard_active()
    if os.name != "posix":
        raise NetworkGuardError("sitecustomize canary descriptors require POSIX")
    if not _SUBPROCESS_GUARD_INSTALLED or subprocess.Popen is not _GuardedPopen:
        raise NetworkGuardError("preflight subprocess deny guard is not active")

    selected_command = list(command if command is not None else current_invocation_command())
    selected_cwd = os.fspath(cwd if cwd is not None else Path.cwd())
    selected_env = (
        _startup_environment_snapshot() if env is None else dict(env)
    )
    _validate_canary_launch(selected_command, selected_cwd, selected_env)

    signal_read = signal_write = report_read = report_write = -1
    process: subprocess.Popen[bytes] | None = None
    fixed_fds: list[int] = []
    try:
        for descriptor in (CANARY_SIGNAL_FD, CANARY_REPORT_FD):
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            raise NetworkGuardError("reserved startup-canary descriptor is already open")

        signal_read, signal_write = os.pipe()
        report_read, report_write = os.pipe()
        signal_read = _move_from_reserved_descriptor(signal_read)
        signal_write = _move_from_reserved_descriptor(signal_write)
        report_read = _move_from_reserved_descriptor(report_read)
        report_write = _move_from_reserved_descriptor(report_write)
        os.dup2(signal_read, CANARY_SIGNAL_FD, inheritable=True)
        fixed_fds.append(CANARY_SIGNAL_FD)
        os.dup2(report_write, CANARY_REPORT_FD, inheritable=True)
        fixed_fds.append(CANARY_REPORT_FD)
        os.close(signal_read)
        signal_read = -1
        os.close(report_write)
        report_write = -1
        _write_all(signal_write, CANARY_SIGNAL)
        os.close(signal_write)
        signal_write = -1

        inherited = (CANARY_SIGNAL_FD, CANARY_REPORT_FD)
        with authorize_subprocess_launch(
            selected_command,
            cwd=selected_cwd,
            env=selected_env,
            pass_fds=inherited,
            close_fds=True,
        ):
            process = subprocess.Popen(
                selected_command,
                cwd=selected_cwd,
                env=selected_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=inherited,
                start_new_session=True,
            )
        for descriptor in fixed_fds:
            os.close(descriptor)
        fixed_fds.clear()

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_group(process)
            raise NetworkGuardError("sitecustomize startup canary did not exit") from exc

        raw_report = _read_canary_report(report_read)
        if process.returncode != 0:
            raise NetworkGuardError("sitecustomize startup canary failed")
        try:
            report = json.loads(raw_report.decode("ascii"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise NetworkGuardError("sitecustomize startup canary report is invalid") from exc
        _validate_canary_report(
            report,
            process_role=selected_env.get(PROCESS_ROLE_ENV),
            command=selected_command,
            cwd=selected_cwd,
            env=selected_env,
            process_id=process.pid,
        )
        return dict(report)
    except OSError as exc:
        raise NetworkGuardError("sitecustomize startup canary launch failed") from exc
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_group(process)
        for descriptor in fixed_fds:
            try:
                os.close(descriptor)
            except OSError:
                pass
        for descriptor in (signal_read, signal_write, report_read, report_write):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _startup_environment_snapshot() -> dict[str, str]:
    module = sys.modules.get("scripts.sitecustomize")
    saved = getattr(module, "_STARTUP_ENVIRONMENT", None)
    if not isinstance(saved, Mapping):
        raise NetworkGuardError("preflight startup environment snapshot is unavailable")
    return {str(name): str(value) for name, value in saved.items()}


def _validate_canary_launch(
    command: Sequence[str], cwd: str, env: Mapping[str, str]
) -> None:
    role = env.get(PROCESS_ROLE_ENV)
    expected_python = env.get(EXPECTED_PYTHON_ENV)
    expected_prefix = env.get(EXPECTED_PREFIX_ENV)
    project_root = env.get(PROJECT_ROOT_ENV)
    guard_directory = env.get(GUARD_DIRECTORY_ENV)
    pythonpath = env.get("PYTHONPATH", "")
    run_id = env.get(RUN_ID_ENV)
    guard_events_path = env.get(GUARD_EVENTS_PATH_ENV)
    if (run_id is None) != (guard_events_path is None):
        raise NetworkGuardError("startup canary guard-event identity is incomplete")
    if run_id is not None and guard_events_path is not None:
        try:
            _validate_guard_event_path(guard_events_path, run_id)
        except SafetyConfigurationError as exc:
            raise NetworkGuardError("startup canary guard-event identity is invalid") from exc
    try:
        resolved_root = Path(project_root or "").resolve(strict=True)
        resolved_cwd = Path(cwd).resolve(strict=True)
        resolved_cwd.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError, TypeError):
        raise NetworkGuardError("startup canary launch identity is invalid") from None
    if (
        role not in PROCESS_ROLES
        or not isinstance(expected_python, str)
        or not expected_python
        or not isinstance(expected_prefix, str)
        or not expected_prefix
        or not isinstance(project_root, str)
        or not project_root
        or resolved_root != PROJECT_ROOT
        or expected_python != str(PROJECT_ROOT / ".venv" / "bin" / "python")
        or expected_prefix != str(PROJECT_ROOT / ".venv")
        or guard_directory != str(PROJECT_ROOT / GUARD_DIRECTORY)
        or pythonpath != os.pathsep.join((guard_directory, project_root))
        or not Path(guard_directory, "sitecustomize.py").is_file()
        or Path(guard_directory, "sitecustomize.py").is_symlink()
        or not Path(cwd).is_absolute()
        or not command
        or command[0] != expected_python
        or any(
            (_SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name)) and value
            for name, value in env.items()
        )
        or any(env.get(name, "") for name in _KNOWN_PROVIDER_KEYS)
    ):
        raise NetworkGuardError("startup canary launch identity is invalid")

    for argument in command[1:]:
        if argument in ("-m", "-c", "--") or not argument.startswith("-"):
            break
        if argument in ("-S", "-I", "-E", "--isolated", "--ignore-environment", "--no-site"):
            raise NetworkGuardError("startup canary command disables sitecustomize")
        if not argument.startswith("--") and any(flag in argument[1:] for flag in "SIE"):
            raise NetworkGuardError("startup canary command disables sitecustomize")


def _validate_canary_report(
    report: Any,
    *,
    process_role: Any,
    command: Sequence[str],
    cwd: str,
    env: Mapping[str, str],
    process_id: int,
) -> None:
    expected_environment_sha = _startup_canary_environment_digest(env)
    expected_command_sha = hashlib.sha256(
        json.dumps(list(command), ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    interpreter = report.get("interpreter") if isinstance(report, Mapping) else None
    guard_events = report.get("guard_events") if isinstance(report, Mapping) else None
    if (
        not isinstance(report, Mapping)
        or report.get("process_role") != process_role
        or type(report.get("pid")) is not int
        or report.get("pid") != process_id
        or type(report.get("startup_observed_at_ns")) is not int
        or report.get("startup_observed_at_ns") <= 0
        or report.get("command") != list(command)
        or report.get("command_sha256") != expected_command_sha
        or report.get("environment_sha256") != expected_environment_sha
        or report.get("working_directory") != str(Path(cwd))
        or report.get("guard_active") is not True
        or report.get("non_loopback_connect_denied") is not True
        or report.get("subprocess_launch_denied") is not True
        or not isinstance(interpreter, Mapping)
        or interpreter.get("executable") != env.get(EXPECTED_PYTHON_ENV)
        or interpreter.get("prefix") != env.get(EXPECTED_PREFIX_ENV)
        or not isinstance(interpreter.get("base_prefix"), str)
        or interpreter.get("base_prefix") == interpreter.get("prefix")
        or report.get("guard_events_complete") is not True
        or not validate_guard_event_records(
            guard_events,
            expected_run_id=env.get(RUN_ID_ENV) if env.get(RUN_ID_ENV) else None,
            expected_pid=process_id,
            require_startup_canaries=True,
        )
    ):
        raise NetworkGuardError("sitecustomize startup canary evidence is incomplete")


def _startup_environment_digest(env: Mapping[str, str]) -> str:
    normalized = {
        str(name): "" if _SECRET_ENV_NAME.search(str(name)) or _PROXY_ENV_NAME.search(str(name))
        else str(value)
        for name, value in env.items()
    }
    normalized.pop(ACTIVE_GUARD_ENV, None)
    normalized.pop(SANITIZED_ENV, None)
    normalized[ACTIVE_GUARD_ENV] = "1"
    normalized[SANITIZED_ENV] = "1"
    return hashlib.sha256(
        json.dumps(
            sorted(normalized.items()), ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()


def _startup_canary_environment_digest(
    env: Mapping[str, str],
    *,
    runtime_environment: Mapping[str, str] | None = None,
) -> str:
    """Bind caller environment plus exact locale/runtime values injected at startup.

    CPython's locale coercion and macOS process startup can add LC_CTYPE and
    __CF_USER_TEXT_ENCODING even when Popen receives an explicit environment.
    The target hashes those effective values; the controller incorporates its
    own observed values into the expected hash rather than dropping them.
    """
    effective_environment = {str(name): str(value) for name, value in env.items()}
    runtime = os.environ if runtime_environment is None else runtime_environment
    for name in _RUNTIME_INJECTED_ENV_NAMES:
        if name not in effective_environment and name in runtime:
            effective_environment[name] = str(runtime[name])
    return _startup_environment_digest(effective_environment)


def _read_canary_report(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = 65_536
    while remaining > 0:
        chunk = os.read(descriptor, min(4096, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if not raw.endswith(b"\n") or len(raw) > 65_536:
        raise NetworkGuardError("sitecustomize startup canary report is incomplete")
    return raw[:-1]


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short_write")
        offset += written


def _move_from_reserved_descriptor(descriptor: int) -> int:
    if descriptor not in (CANARY_SIGNAL_FD, CANARY_REPORT_FD):
        return descriptor
    replacement = os.dup(descriptor)
    while replacement in (CANARY_SIGNAL_FD, CANARY_REPORT_FD):
        next_replacement = os.dup(replacement)
        os.close(replacement)
        replacement = next_replacement
    os.close(descriptor)
    return replacement


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass


def current_invocation_command() -> list[str]:
    """Return the invoked command with Python's reported executable identity.

    CPython may rewrite ``sys.orig_argv[0]`` to the resolved framework binary
    when launched through a venv symlink. ``sys.executable`` retains the venv
    path that was invoked, so use it for argv[0] while preserving every caller
    argument exactly.
    """
    original = getattr(sys, "orig_argv", None)
    if isinstance(original, (list, tuple)) and original:
        return [sys.executable, *(str(argument) for argument in original[1:])]
    return [sys.executable, *sys.argv]


_INVOCATION_IDENTITY_KEYS = frozenset(
    ("command", "working_directory", "pythonpath")
)


def _normalize_invocation_identity(
    value: Any, *, label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _INVOCATION_IDENTITY_KEYS:
        raise SafetyConfigurationError(label + " invocation identity is invalid")
    command = value.get("command")
    working_directory = value.get("working_directory")
    pythonpath = value.get("pythonpath")
    if (
        not isinstance(command, (list, tuple))
        or not command
        or any(
            not isinstance(argument, str)
            or "\x00" in argument
            for argument in command
        )
        or not isinstance(working_directory, str)
        or not working_directory
        or "\x00" in working_directory
        or not isinstance(pythonpath, str)
        or "\x00" in pythonpath
    ):
        raise SafetyConfigurationError(label + " invocation identity is invalid")
    return {
        "command": list(command),
        "working_directory": working_directory,
        "pythonpath": pythonpath,
    }


def compare_invocation_identity(
    declared: Any, intended: Any
) -> dict[str, Any]:
    """Compare exact argv, cwd, and PYTHONPATH without exposing their values.

    Mismatch evidence contains only field names, argument/entry indexes, counts,
    and path-shape facts. It deliberately omits raw arguments and paths, which
    may contain credentials or machine-local details.
    """
    expected = _normalize_invocation_identity(declared, label="declared")
    observed = _normalize_invocation_identity(intended, label="intended")
    mismatches: list[dict[str, Any]] = []

    expected_command = expected["command"]
    observed_command = observed["command"]
    command_indexes = [
        index
        for index in range(max(len(expected_command), len(observed_command)))
        if index >= len(expected_command)
        or index >= len(observed_command)
        or expected_command[index] != observed_command[index]
    ]
    if command_indexes:
        mismatches.append(
            {
                "field": "command",
                "declared_argument_count": len(expected_command),
                "intended_argument_count": len(observed_command),
                "differing_argument_indexes": command_indexes,
            }
        )

    expected_cwd = expected["working_directory"]
    observed_cwd = observed["working_directory"]
    if expected_cwd != observed_cwd:
        mismatches.append(
            {
                "field": "working_directory",
                "declared_is_absolute": Path(expected_cwd).is_absolute(),
                "intended_is_absolute": Path(observed_cwd).is_absolute(),
                "declared_component_count": len(Path(expected_cwd).parts),
                "intended_component_count": len(Path(observed_cwd).parts),
            }
        )

    expected_pythonpath = expected["pythonpath"]
    observed_pythonpath = observed["pythonpath"]
    if expected_pythonpath != observed_pythonpath:
        expected_entries = expected_pythonpath.split(os.pathsep)
        observed_entries = observed_pythonpath.split(os.pathsep)
        path_indexes = [
            index
            for index in range(max(len(expected_entries), len(observed_entries)))
            if index >= len(expected_entries)
            or index >= len(observed_entries)
            or expected_entries[index] != observed_entries[index]
        ]
        mismatches.append(
            {
                "field": "pythonpath",
                "declared_entry_count": len(expected_entries),
                "intended_entry_count": len(observed_entries),
                "differing_entry_indexes": path_indexes,
            }
        )

    return {
        "schema_version": 1,
        "status": "blocked" if mismatches else "matched",
        "fields_compared": ["command", "working_directory", "pythonpath"],
        "mismatches": mismatches,
    }


def require_invocation_identity(
    declared: Any, intended: Any
) -> dict[str, Any]:
    """Require exact invocation identity and return secret-free evidence."""
    evidence = compare_invocation_identity(declared, intended)
    if evidence["mismatches"]:
        raise InvocationIdentityMismatch(evidence)
    return evidence


def run_after_invocation_identity(
    declared: Any,
    intended: Any,
    operation: Callable[[], Any],
) -> tuple[Any, dict[str, Any]]:
    """Run one side effect only after exact invocation identity is proven."""
    if not callable(operation):
        raise SafetyConfigurationError("preflight boundary operation is invalid")
    evidence = require_invocation_identity(declared, intended)
    return operation(), evidence


def current_invocation_identity() -> dict[str, Any]:
    """Return the current process identity used at seed/worker boundaries."""
    return {
        "command": current_invocation_command(),
        "working_directory": str(Path.cwd()),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
    }


def startup_invocation_identity() -> dict[str, Any]:
    """Return the invocation captured by the already-installed startup guard."""
    require_guard_active()
    if os.environ.get(STARTUP_GUARD_ENV) != "1":
        raise NetworkGuardError("preflight startup invocation identity is unavailable")
    try:
        report = json.loads(os.environ.get(CANARY_REPORT_ENV, ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise NetworkGuardError(
            "preflight startup invocation identity is invalid"
        ) from exc
    source_guard = sys.modules.get("scripts.sitecustomize")
    startup_environment = getattr(source_guard, "_STARTUP_ENVIRONMENT", None)
    if (
        not isinstance(report, Mapping)
        or not isinstance(startup_environment, Mapping)
        or not isinstance(report.get("command"), list)
        or not isinstance(report.get("working_directory"), str)
        or not isinstance(startup_environment.get("PYTHONPATH"), str)
    ):
        raise NetworkGuardError("preflight startup invocation identity is incomplete")
    identity = {
        "command": report["command"],
        "working_directory": report["working_directory"],
        "pythonpath": startup_environment["PYTHONPATH"],
    }
    try:
        _normalize_invocation_identity(identity, label="startup")
    except SafetyConfigurationError as exc:
        raise NetworkGuardError(
            "preflight startup invocation identity is invalid"
        ) from exc
    return identity


def require_current_invocation_matches_startup() -> dict[str, Any]:
    """Fail closed if argv, cwd, or PYTHONPATH changed after interpreter startup."""
    return require_invocation_identity(
        startup_invocation_identity(), current_invocation_identity()
    )


class _CanarySocket:
    family = socket.AF_INET


def _command_tuple(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if any(not isinstance(part, str) or not part for part in value):
        return None
    return tuple(value)


def _path_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return os.fspath(value)
    except TypeError:
        return None


def require_guard_active() -> None:
    """Fail closed unless this interpreter installed the network guard."""
    if (
        not _GUARD_INSTALLED
        or os.environ.get(ACTIVE_GUARD_ENV) != "1"
        or os.environ.get(SANITIZED_ENV) != "1"
    ):
        raise NetworkGuardError("preflight network guard is not active in this process")
    for name, guarded_method in _GUARDED_SOCKET_METHODS.items():
        if getattr(socket.socket, name, None) is not guarded_method:
            raise NetworkGuardError("preflight socket deny guard was replaced")
    for name, guarded_function in _GUARDED_DNS_FUNCTIONS.items():
        if getattr(socket, name, None) is not guarded_function:
            raise NetworkGuardError("preflight DNS deny guard was replaced")
    if (
        not _SUBPROCESS_GUARD_INSTALLED
        or subprocess.Popen is not _GuardedPopen
    ):
        raise NetworkGuardError("preflight subprocess deny guard is not active")


def require_sanitized_environment() -> None:
    """Require the characterization process to have no usable credentials or proxies."""
    if (
        os.environ.get(REQUIRE_STARTUP_GUARD_ENV) != "1"
        or os.environ.get(ENABLE_GUARD_ENV) != "1"
        or os.environ.get(SANITIZED_ENV) != "1"
    ):
        raise SafetyConfigurationError("preflight environment sanitization is not active")
    for name, value in os.environ.items():
        if (_SECRET_ENV_NAME.search(name) or _PROXY_ENV_NAME.search(name)) and value:
            raise SafetyConfigurationError("preflight environment contains a secret or proxy")
    if any(os.environ.get(name, "") for name in _KNOWN_PROVIDER_KEYS):
        raise SafetyConfigurationError("preflight provider key is not blank")


def _require_startup_guard_markers() -> Path:
    if (
        os.environ.get(REQUIRE_STARTUP_GUARD_ENV) != "1"
        or os.environ.get(ENABLE_GUARD_ENV) != "1"
        or os.environ.get(STARTUP_GUARD_ENV) != "1"
    ):
        raise NetworkGuardError("preflight startup guard was not installed by sitecustomize")
    if (
        os.environ.get(ACTIVE_GUARD_ENV) != "1"
        or os.environ.get(SANITIZED_ENV) != "1"
    ):
        raise NetworkGuardError("preflight startup guard markers are incomplete")

    startup_module = sys.modules.get("sitecustomize")
    startup_path = getattr(startup_module, "__file__", None)
    if not isinstance(startup_path, (str, os.PathLike)):
        raise NetworkGuardError("preflight sitecustomize origin is unavailable")
    try:
        return Path(startup_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise NetworkGuardError("preflight sitecustomize origin is unavailable") from exc


def require_startup_guard_active() -> None:
    """Require the deny guard to have been installed by sitecustomize."""
    _require_startup_guard_markers()
    require_guard_active()
    try:
        report = json.loads(os.environ.get(CANARY_REPORT_ENV, ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise NetworkGuardError("preflight startup canary report is unavailable") from exc
    if (
        os.environ.get(CONNECT_CANARY_ENV) != "1"
        or os.environ.get(SUBPROCESS_CANARY_ENV) != "1"
        or not isinstance(report, Mapping)
        or report.get("process_role") != os.environ.get(PROCESS_ROLE_ENV)
        or report.get("command") != current_invocation_command()
        or report.get("working_directory") != str(Path.cwd())
        or type(report.get("pid")) is not int
        or report.get("pid") != os.getpid()
        or type(report.get("startup_observed_at_ns")) is not int
        or report.get("startup_observed_at_ns") <= 0
        or report.get("interpreter")
        != {
            "executable": sys.executable,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        }
        or report.get("guard_active") is not True
        or report.get("non_loopback_connect_denied") is not True
        or report.get("subprocess_launch_denied") is not True
    ):
        raise NetworkGuardError("preflight startup canary did not fail closed")
    command_sha256 = hashlib.sha256(
        json.dumps(
            report.get("command"), ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()
    try:
        environment_sha256 = _startup_environment_digest(
            _startup_environment_snapshot()
        )
    except NetworkGuardError:
        raise NetworkGuardError("preflight startup environment snapshot is unavailable") from None
    if (
        report.get("command_sha256") != command_sha256
        or report.get("environment_sha256") != environment_sha256
    ):
        raise NetworkGuardError("preflight startup canary identity is invalid")


def require_startup_guard_from(
    expected_sitecustomize: str | Path,
    *,
    require_local_guard: bool = True,
) -> None:
    """Require the interpreter-started sitecustomize to match an exact file."""
    observed = _require_startup_guard_markers()
    try:
        expected = Path(expected_sitecustomize).resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as exc:
        raise NetworkGuardError("preflight sitecustomize origin is unavailable") from exc
    if observed != expected:
        raise NetworkGuardError("preflight sitecustomize origin differs from the sandbox")
    if require_local_guard:
        require_startup_guard_active()


def install_network_deny_guard() -> None:
    """Patch socket entry points to allow only numeric loopback addresses."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        require_guard_active()
        return

    _ORIGINAL_SOCKET_METHODS["connect"] = socket.socket.connect
    _ORIGINAL_SOCKET_METHODS["connect_ex"] = socket.socket.connect_ex
    _ORIGINAL_SOCKET_METHODS["bind"] = socket.socket.bind
    _ORIGINAL_SOCKET_METHODS["sendto"] = socket.socket.sendto
    _ORIGINAL_DNS_FUNCTIONS["getaddrinfo"] = socket.getaddrinfo
    _ORIGINAL_DNS_FUNCTIONS["gethostbyname"] = socket.gethostbyname
    _ORIGINAL_DNS_FUNCTIONS["gethostbyname_ex"] = socket.gethostbyname_ex
    _ORIGINAL_DNS_FUNCTIONS["gethostbyaddr"] = socket.gethostbyaddr
    _ORIGINAL_DNS_FUNCTIONS["getnameinfo"] = socket.getnameinfo

    original_connect = _ORIGINAL_SOCKET_METHODS["connect"]
    original_connect_ex = _ORIGINAL_SOCKET_METHODS["connect_ex"]
    original_bind = _ORIGINAL_SOCKET_METHODS["bind"]
    original_sendto = _ORIGINAL_SOCKET_METHODS["sendto"]
    original_getaddrinfo = _ORIGINAL_DNS_FUNCTIONS["getaddrinfo"]

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        try:
            _require_loopback_socket_address(sock.family, address)
        except NetworkGuardError:
            _record_guard_event(
                "network_attempt",
                operation="connect",
                decision="denied",
                address=address,
            )
            raise
        _record_guard_event(
            "network_attempt", operation="connect", decision="allowed", address=address
        )
        return original_connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: Any) -> int:
        try:
            _require_loopback_socket_address(sock.family, address)
        except NetworkGuardError:
            _record_guard_event(
                "network_attempt",
                operation="connect_ex",
                decision="denied",
                address=address,
            )
            raise
        _record_guard_event(
            "network_attempt",
            operation="connect_ex",
            decision="allowed",
            address=address,
        )
        return original_connect_ex(sock, address)

    def guarded_bind(sock: socket.socket, address: Any) -> Any:
        try:
            _require_loopback_socket_address(sock.family, address)
        except NetworkGuardError:
            _record_guard_event(
                "network_attempt", operation="bind", decision="denied", address=address
            )
            raise
        _record_guard_event(
            "network_attempt", operation="bind", decision="allowed", address=address
        )
        return original_bind(sock, address)

    def guarded_sendto(sock: socket.socket, *args: Any) -> int:
        if not args:
            _record_guard_event(
                "network_attempt",
                operation="sendto",
                decision="denied",
                address=None,
            )
            raise NetworkGuardError("socket sendto address is missing")
        try:
            _require_loopback_socket_address(sock.family, args[-1])
        except NetworkGuardError:
            _record_guard_event(
                "network_attempt",
                operation="sendto",
                decision="denied",
                address=args[-1],
            )
            raise
        _record_guard_event(
            "network_attempt",
            operation="sendto",
            decision="allowed",
            address=args[-1],
        )
        return original_sendto(sock, *args)

    def guarded_getaddrinfo(
        host: Any,
        port: Any,
        family: int = 0,
        socktype: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        if isinstance(host, str) and host.casefold() == "localhost":
            _record_guard_event(
                "network_attempt",
                operation="getaddrinfo",
                decision="allowed",
                address=(host, port),
            )
            return _localhost_addrinfo(port, family, socktype, proto, flags)
        if not _is_ip_loopback(host):
            _record_guard_event(
                "network_attempt",
                operation="getaddrinfo",
                decision="denied",
                address=(host, port),
            )
            raise NetworkGuardError("non-loopback DNS and network access are denied")
        results = original_getaddrinfo(host, port, family, socktype, proto, flags)
        if any(not _is_ip_loopback(item[4][0]) for item in results):
            _record_guard_event(
                "network_attempt",
                operation="getaddrinfo",
                decision="denied",
                address=(host, port),
            )
            raise NetworkGuardError("resolver returned a non-loopback address")
        _record_guard_event(
            "network_attempt",
            operation="getaddrinfo",
            decision="allowed",
            address=(host, port),
        )
        return results

    def guarded_gethostbyname(host: str) -> str:
        if isinstance(host, str) and host.casefold() == "localhost":
            _record_guard_event(
                "network_attempt",
                operation="gethostbyname",
                decision="allowed",
                address=(host, None),
            )
            return "127.0.0.1"
        try:
            address = ipaddress.IPv4Address(host)
        except (ipaddress.AddressValueError, TypeError):
            _record_guard_event(
                "network_attempt",
                operation="gethostbyname",
                decision="denied",
                address=(host, None),
            )
            raise NetworkGuardError("non-loopback DNS is denied") from None
        if not address.is_loopback:
            _record_guard_event(
                "network_attempt",
                operation="gethostbyname",
                decision="denied",
                address=(host, None),
            )
            raise NetworkGuardError("non-loopback DNS is denied")
        _record_guard_event(
            "network_attempt",
            operation="gethostbyname",
            decision="allowed",
            address=(host, None),
        )
        return str(address)

    def guarded_gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
        address = guarded_gethostbyname(host)
        return "localhost", [], [address]

    def guarded_gethostbyaddr(address: str) -> tuple[str, list[str], list[str]]:
        if not _is_ip_loopback(address):
            _record_guard_event(
                "network_attempt",
                operation="gethostbyaddr",
                decision="denied",
                address=(address, None),
            )
            raise NetworkGuardError("non-loopback reverse DNS is denied")
        _record_guard_event(
            "network_attempt",
            operation="gethostbyaddr",
            decision="allowed",
            address=(address, None),
        )
        return "localhost", [], [str(address)]

    def guarded_getnameinfo(address: Any, flags: int) -> tuple[str, str]:
        if not isinstance(address, tuple) or not address or not _is_ip_loopback(address[0]):
            _record_guard_event(
                "network_attempt",
                operation="getnameinfo",
                decision="denied",
                address=address,
            )
            raise NetworkGuardError("non-loopback reverse DNS is denied")
        if not flags & getattr(socket, "NI_NUMERICHOST", 0):
            _record_guard_event(
                "network_attempt",
                operation="getnameinfo",
                decision="denied",
                address=address,
            )
            raise NetworkGuardError("reverse DNS lookups are denied")
        numeric_flags = flags | getattr(socket, "NI_NUMERICSERV", 0)
        _record_guard_event(
            "network_attempt",
            operation="getnameinfo",
            decision="allowed",
            address=address,
        )
        return _ORIGINAL_DNS_FUNCTIONS["getnameinfo"](address, numeric_flags)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.socket.bind = guarded_bind  # type: ignore[method-assign]
    socket.socket.sendto = guarded_sendto  # type: ignore[method-assign]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = guarded_gethostbyname  # type: ignore[assignment]
    socket.gethostbyname_ex = guarded_gethostbyname_ex  # type: ignore[assignment]
    socket.gethostbyaddr = guarded_gethostbyaddr  # type: ignore[assignment]
    socket.getnameinfo = guarded_getnameinfo  # type: ignore[assignment]
    _GUARDED_SOCKET_METHODS.update(
        {
            "connect": guarded_connect,
            "connect_ex": guarded_connect_ex,
            "bind": guarded_bind,
            "sendto": guarded_sendto,
        }
    )
    _GUARDED_DNS_FUNCTIONS.update(
        {
            "getaddrinfo": guarded_getaddrinfo,
            "gethostbyname": guarded_gethostbyname,
            "gethostbyname_ex": guarded_gethostbyname_ex,
            "gethostbyaddr": guarded_gethostbyaddr,
            "getnameinfo": guarded_getnameinfo,
        }
    )
    _GUARD_INSTALLED = True
    os.environ[ACTIVE_GUARD_ENV] = "1"


def _require_loopback_socket_address(family: int, address: Any) -> None:
    if family not in (socket.AF_INET, socket.AF_INET6):
        raise NetworkGuardError("only IPv4 and IPv6 loopback sockets are permitted")
    if not isinstance(address, tuple) or not address or not _is_ip_loopback(address[0]):
        raise NetworkGuardError("only numeric loopback socket addresses are permitted")


def _is_ip_loopback(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _localhost_addrinfo(
    port: Any,
    family: int,
    socktype: int,
    proto: int,
    flags: int,
) -> list[tuple[Any, ...]]:
    del flags
    families = [socket.AF_INET, socket.AF_INET6]
    if family not in (0, socket.AF_UNSPEC):
        if family not in families:
            raise socket.gaierror(socket.EAI_FAMILY, "unsupported address family")
        families = [family]
    types = [socktype] if socktype else [socket.SOCK_STREAM, socket.SOCK_DGRAM]
    output: list[tuple[Any, ...]] = []
    for selected_family in families:
        for selected_type in types:
            selected_proto = proto
            if selected_proto == 0:
                if selected_type == socket.SOCK_STREAM:
                    selected_proto = socket.IPPROTO_TCP
                elif selected_type == socket.SOCK_DGRAM:
                    selected_proto = socket.IPPROTO_UDP
            if selected_family == socket.AF_INET:
                address = ("127.0.0.1", port)
            else:
                address = ("::1", port, 0, 0)
            output.append((selected_family, selected_type, selected_proto, "", address))
    return output
