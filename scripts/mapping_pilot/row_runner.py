# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Thin, injected orchestration for one frozen mapping-pilot row."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from scripts.mapping_pilot.execution import (
    DEFAULT_EXECUTION_ROOT,
    ExecutionLedgerError,
    assert_row_start_allowed,
    cap_snapshot,
    check_provider_request,
    execute_booked_operation,
    get_reserve_assignment,
    mark_content_review_started,
    record_pre_content_classification,
    reconcile_attempt_count,
    record_row_event,
    require_valid_booking,
    set_slot_status,
)
from scripts.mapping_pilot.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    create_evidence_bundle,
    load_turn_packet_evidence,
)
from scripts.mapping_pilot.fixtures import FIXTURE_FILES
from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    PROJECT_ROOT,
    verify_manifest,
)
from scripts.mapping_pilot.scoring import (
    MATRIX_ATTEMPT_CAP,
    MATRIX_WALL_TIME_CAP_SECONDS,
    ROW_ATTEMPT_CAP,
    ROW_WALL_TIME_CAP_SECONDS,
    score_row,
)


# Keep row bundles outside the strict ledger/runtime scan beneath the SP3 gate.
DEFAULT_ROW_EVIDENCE_ROOT = DEFAULT_EVIDENCE_ROOT / "row-bundles"
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_ROW_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_LIFECYCLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SAFE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECORD_NAME = re.compile(r"^record-[0-9]{8}\.json$")
_MOVEMENT_RECORD_NAME = re.compile(r"^record-[0-9]{6}\.json$")
# Research-only CaptureSession scope: python-engineio exposes this decoder
# bound on Payload as a process-global class attribute (default 16).
# The localhost:8360 mapping-pilot client uses the fixed bounded limit 64.
_SOCKET_PAYLOAD_DECODE_DEFAULT = 16
_SOCKET_PAYLOAD_DECODE_LIMIT = 64
_SOCKET_PAYLOAD_DECODE_SOURCE = "engineio.payload.Payload.max_decode_packets"
_SOCKET_PAYLOAD_DECODE_LOCK = threading.Lock()
_ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE: Optional["_SocketPayloadDecodeScope"] = None
_SOCKET_DISCONNECT_REASONS = {
    "client disconnect": "client_disconnect",
    "server disconnect": "server_disconnect",
    "transport error": "transport_error",
    "ping timeout": "ping_timeout",
}
_MAPPING_MODULE = "Mapping_Pilot_Arena"
_REQUEST_GUARD_BOOTSTRAP = '''\
import importlib
import importlib.abc
import importlib.machinery
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time

_CONTEXT_TEXT = os.environ.get("NEQ_MAPPING_PILOT_REQUEST_GUARD_CONTEXT", "")
try:
    _CONTEXT = json.loads(_CONTEXT_TEXT)
except (TypeError, ValueError):
    _CONTEXT = None
_REQUEST_LOCK = threading.RLock()
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_ROW_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_LIFECYCLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _reject_source_symlinks(path):
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeError("mapping-pilot request guard source path is unsafe")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise RuntimeError("mapping-pilot request guard source path is unsafe")


def _validated_context():
    required = {
        "run_id",
        "row_id",
        "row_run_id",
        "lifecycle_id",
        "ledger_root",
        "live_started_monotonic",
    }
    if not isinstance(_CONTEXT, dict) or set(_CONTEXT) != required:
        raise RuntimeError("mapping-pilot request guard context is unavailable")
    for key in ("run_id", "row_id"):
        if not isinstance(_CONTEXT[key], str) or not _SAFE_TOKEN.fullmatch(_CONTEXT[key]):
            raise RuntimeError("mapping-pilot request guard identity is invalid")
    if (
        not isinstance(_CONTEXT["row_run_id"], str)
        or not _SAFE_ROW_RUN_ID.fullmatch(_CONTEXT["row_run_id"])
    ):
        raise RuntimeError("mapping-pilot request guard identity is invalid")
    if (
        not isinstance(_CONTEXT["lifecycle_id"], str)
        or not _SAFE_LIFECYCLE_ID.fullmatch(_CONTEXT["lifecycle_id"])
    ):
        raise RuntimeError("mapping-pilot request guard lifecycle identity is invalid")

    ledger_text = _CONTEXT["ledger_root"]
    ledger_parts = ledger_text.split("/") if isinstance(ledger_text, str) else []
    if (
        not ledger_parts
        or "\\\\" in ledger_text
        or ledger_parts[0] != "tmp"
        or any(part in ("", ".", "..") for part in ledger_parts)
    ):
        raise RuntimeError("mapping-pilot request guard ledger root is unsafe")

    started = _CONTEXT["live_started_monotonic"]
    if (
        isinstance(started, bool)
        or not isinstance(started, (int, float))
        or started < 0
        or not math.isfinite(float(started))
    ):
        raise RuntimeError("mapping-pilot request guard live start is invalid")
    return ledger_parts


def _load_parent_execution():
    ledger_parts = _validated_context()
    source_path = Path(__file__)
    _reject_source_symlinks(source_path)
    try:
        source_path = source_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("mapping-pilot request guard source is unavailable") from exc

    suffix = tuple(
        ledger_parts
        + [
            _CONTEXT["run_id"],
            "runtime",
            _CONTEXT["row_run_id"],
            "sitecustomize.py",
        ]
    )
    if source_path.parts[-len(suffix):] != suffix:
        raise RuntimeError("mapping-pilot request guard source identity is invalid")
    project_root = source_path
    for _part in suffix:
        project_root = project_root.parent
    try:
        project_root = project_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("mapping-pilot owning repository is unavailable") from exc
    if not project_root.is_dir():
        raise RuntimeError("mapping-pilot owning repository is unavailable")

    execution_path = project_root / "scripts" / "mapping_pilot" / "execution.py"
    manifest_path = project_root / "scripts" / "mapping_pilot" / "manifest.py"
    for source in (execution_path, manifest_path):
        _reject_source_symlinks(source)
        try:
            if source.resolve(strict=True) != source or not source.is_file():
                raise RuntimeError("mapping-pilot parent guard source is unavailable")
        except (OSError, RuntimeError) as exc:
            raise RuntimeError("mapping-pilot parent guard source is unavailable") from exc

    root_text = str(project_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        execution = importlib.import_module("scripts.mapping_pilot.execution")
        manifest = importlib.import_module("scripts.mapping_pilot.manifest")
        loaded_execution = Path(execution.__file__).resolve(strict=True)
        loaded_manifest = Path(manifest.__file__).resolve(strict=True)
        loaded_project_root = Path(execution.PROJECT_ROOT).resolve(strict=True)
        manifest_project_root = Path(manifest.PROJECT_ROOT).resolve(strict=True)
        prereg_root = Path(execution.DEFAULT_PREREG_ROOT).resolve(strict=True)
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError) as exc:
        raise RuntimeError("mapping-pilot parent execution guard is unavailable") from exc
    if (
        loaded_execution != execution_path
        or loaded_manifest != manifest_path
        or loaded_project_root != project_root
        or manifest_project_root != project_root
        or prereg_root != project_root / "plans" / "v2-mapping-pilot-prereg"
    ):
        raise RuntimeError("mapping-pilot execution guard did not load from its owning repository")
    return execution


def _load_parent_server(execution):
    project_root = Path(execution.PROJECT_ROOT).resolve(strict=True)
    server_path = project_root / "scripts" / "mapping_pilot" / "server.py"
    _reject_source_symlinks(server_path)
    try:
        if server_path.resolve(strict=True) != server_path or not server_path.is_file():
            raise RuntimeError("mapping-pilot parent receipt observer is unavailable")
        server = importlib.import_module("scripts.mapping_pilot.server")
        loaded_server = Path(server.__file__).resolve(strict=True)
        server_project_root = Path(server.PROJECT_ROOT).resolve(strict=True)
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError) as exc:
        raise RuntimeError("mapping-pilot parent receipt observer is unavailable") from exc
    if loaded_server != server_path or server_project_root != project_root:
        raise RuntimeError("mapping-pilot receipt observer did not load from its owning repository")
    return server


try:
    _EXECUTION = _load_parent_execution()
    _SERVER = _load_parent_server(_EXECUTION)
except Exception as exc:
    raise SystemExit("mapping-pilot request guard initialization failed") from exc


class _GuardStop(BaseException):
    pass


class _GuardedCompletions:
    def __init__(self, target):
        self._target = target

    def __getattr__(self, name):
        value = getattr(self._target, name)
        return self._create if name == "create" else value

    def _create(self, *args, **kwargs):
        with _REQUEST_LOCK:
            result = _EXECUTION.authorize_provider_attempt(
                _CONTEXT["run_id"],
                _CONTEXT["row_id"],
                _CONTEXT["row_run_id"],
                live_started_monotonic=_CONTEXT["live_started_monotonic"],
                monotonic_now=time.monotonic(),
                ledger_root=_CONTEXT["ledger_root"],
            )
            if not result.get("allowed"):
                raise _GuardStop("mapping-pilot request guard refused")
        return self._target.create(*args, **kwargs)


class _GuardedChat:
    def __init__(self, target):
        self._target = target
        self._completions = _GuardedCompletions(target.completions)

    def __getattr__(self, name):
        return self._completions if name == "completions" else getattr(self._target, name)


class _GuardedClient:
    def __init__(self, target):
        self._target = target
        self._chat = _GuardedChat(target.chat)

    def __getattr__(self, name):
        return self._chat if name == "chat" else getattr(self._target, name)


class _RouterLoader:
    def __init__(self, loader):
        self._loader = loader

    def create_module(self, spec):
        creator = getattr(self._loader, "create_module", None)
        return creator(spec) if callable(creator) else None

    def exec_module(self, module):
        self._loader.exec_module(module)
        if not isinstance(_CONTEXT, dict):
            raise RuntimeError("mapping-pilot request guard context is unavailable")
        required = (
            "run_id",
            "row_id",
            "row_run_id",
            "lifecycle_id",
            "ledger_root",
            "live_started_monotonic",
        )
        if any(key not in _CONTEXT for key in required):
            raise RuntimeError("mapping-pilot request guard context is incomplete")
        router_type = getattr(module, "LLMRouter", None)
        if (
            router_type is None
            or not callable(getattr(router_type, "_request_kwargs", None))
            or not callable(getattr(router_type, "_disable_sdk_retries", None))
        ):
            raise RuntimeError("mapping-pilot LLM router type is unavailable")
        original_kwargs = router_type._request_kwargs
        original_disable = router_type._disable_sdk_retries

        def guarded_kwargs(instance, *args, **kwargs):
            result = original_kwargs(instance, *args, **kwargs)
            decision = _EXECUTION.check_provider_request(
                _CONTEXT["run_id"],
                _CONTEXT["row_id"],
                _CONTEXT["row_run_id"],
                live_started_monotonic=_CONTEXT["live_started_monotonic"],
                monotonic_now=time.monotonic(),
                ledger_root=_CONTEXT["ledger_root"],
            )
            if not decision.get("allowed"):
                raise _GuardStop("mapping-pilot request guard refused")
            return result

        def guarded_disable(client):
            return _GuardedClient(original_disable(client))

        router_type._request_kwargs = guarded_kwargs
        router_type._disable_sdk_retries = staticmethod(guarded_disable)
        try:
            _SERVER.install_router_receipt_observer(
                "tmp/combat_capture",
                _CONTEXT["row_run_id"],
                _CONTEXT["lifecycle_id"],
                router_module=module,
            )
        except Exception as exc:
            raise SystemExit(
                "mapping-pilot child receipt observer initialization failed"
            ) from exc


class _RouterFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "utils.llm_router":
            return None
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None and spec.loader is not None:
            spec.loader = _RouterLoader(spec.loader)
        return spec


if not isinstance(_CONTEXT, dict):
    raise RuntimeError("mapping-pilot request guard context is unavailable")
sys.meta_path.insert(0, _RouterFinder())
'''
_FIXTURE_PATHS = {
    fixture_id: path for fixture_id, path in FIXTURE_FILES.items()
}


class RowExecutionError(RuntimeError):
    """Raised when a row cannot safely enter its booked execution boundary."""


class _SocketPayloadDecodeScope:
    """Own the bounded Engine.IO decoder override for one capture session."""

    def __init__(self, payload_type: Any, original_bound: int) -> None:
        self._payload_type = payload_type
        self.original_bound = original_bound
        self.active_bound = _SOCKET_PAYLOAD_DECODE_LIMIT
        self.after_bound: Optional[int] = None
        self.released = False

    @classmethod
    def acquire(cls) -> "_SocketPayloadDecodeScope":
        global _ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE

        with _SOCKET_PAYLOAD_DECODE_LOCK:
            if _ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE is not None:
                raise RowExecutionError(
                    "another mapping-pilot SocketScriptDriver owns the Engine.IO decoder bound"
                )
            try:
                payload_type = importlib.import_module("engineio.payload").Payload
            except (ImportError, AttributeError) as exc:
                raise RowExecutionError(
                    "python-engineio Payload decoder is unavailable"
                ) from exc
            original_bound = getattr(payload_type, "max_decode_packets", None)
            if (
                type(original_bound) is not int
                or original_bound != _SOCKET_PAYLOAD_DECODE_DEFAULT
            ):
                raise RowExecutionError(
                    "Engine.IO decoder bound changed; expected the library default of 16"
                )

            scope = cls(payload_type, original_bound)
            try:
                setattr(
                    payload_type,
                    "max_decode_packets",
                    _SOCKET_PAYLOAD_DECODE_LIMIT,
                )
            except BaseException as exc:
                try:
                    setattr(payload_type, "max_decode_packets", original_bound)
                finally:
                    _ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE = None
                raise RowExecutionError(
                    "could not apply the bounded Engine.IO decoder limit"
                ) from exc
            _ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE = scope
            return scope

    def release(self) -> None:
        """Restore the captured default after the Engine.IO read loop exits."""
        global _ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE

        with _SOCKET_PAYLOAD_DECODE_LOCK:
            if self.released:
                return
            if _ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE is not self:
                raise RowExecutionError(
                    "mapping-pilot Engine.IO decoder ownership was lost"
                )

            current_bound = getattr(
                self._payload_type, "max_decode_packets", None
            )
            restore_error: Optional[BaseException] = None
            try:
                setattr(
                    self._payload_type,
                    "max_decode_packets",
                    self.original_bound,
                )
            except BaseException as exc:
                restore_error = exc
            self.after_bound = getattr(
                self._payload_type, "max_decode_packets", None
            )
            if self.after_bound == self.original_bound:
                self.released = True
                _ACTIVE_SOCKET_PAYLOAD_DECODE_SCOPE = None
            if restore_error is not None:
                raise RowExecutionError(
                    "could not restore the Engine.IO decoder default"
                ) from restore_error
            if not self.released:
                raise RowExecutionError(
                    "Engine.IO decoder default was not restored after capture"
                )
            if current_bound != self.active_bound:
                raise RowExecutionError(
                    "Engine.IO decoder bound changed during the capture session; "
                    "the original default was restored"
                )

    def metadata(self) -> dict[str, Any]:
        return {
            "source": _SOCKET_PAYLOAD_DECODE_SOURCE,
            "before": self.original_bound,
            "active": self.active_bound,
            "after": self.after_bound,
            "restored": self.released and self.after_bound == self.original_bound,
        }


@dataclass(frozen=True)
class RowRunnerHooks:
    """Injected process, socket, evidence, and scoring boundaries."""

    seed: Callable[[Mapping[str, Any]], Any]
    start_server: Callable[[Mapping[str, Any], str, str, Path], Any]
    wait_server_ready: Callable[[Any, float], bool]
    stop_server: Callable[[Any], Any]
    driver_factory: Callable[..., Any]
    load_packet_evidence: Callable[[str, Sequence[str]], Mapping[str, Any]]
    load_router_receipts: Callable[[str], Mapping[str, Any]]
    state_hasher: Callable[[str], Mapping[str, Any]]
    write_step_context: Callable[[str, Mapping[str, Any]], Any]
    evidence_writer: Callable[..., Path]
    scorer: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    check_evaluator: Optional[Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = None
    pre_content_classifier: Optional[
        Callable[[Mapping[str, Any]], Optional[Mapping[str, Any]]]
    ] = None
    source_identity: Optional[Callable[[], Mapping[str, Any]]] = None
    monotonic: Callable[[], float] = __import__("time").monotonic
    wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


@dataclass
class _OwnedServer:
    process: Any
    log_handle: Any
    log_path: Path


class SocketScriptDriver:
    """Narrow mapping-pilot script adapter over the existing CaptureSession."""

    def __init__(
        self,
        *,
        party_size: int,
        transcript_path: Path,
        runtime_root: str,
        session_factory: Any = None,
    ) -> None:
        if session_factory is None:
            capture_drive = importlib.import_module("scripts.capture_drive")
            session_factory = capture_drive.CaptureSession
        args = argparse.Namespace(
            url="http://127.0.0.1:8360",
            party=party_size,
            transcript=str(transcript_path),
            trace_src=None,
            trace_dst=None,
            start_timeout=90.0,
            turn_timeout=90.0,
            turn_quiet_seconds=1.0,
            settle_seconds=0.2,
            init_roll=13,
            state_root=runtime_root,
            run_dir=None,
            gate="g3",
        )
        self.session = session_factory(args)
        self.transcript_path = transcript_path
        self._decode_bound_scope: Optional[_SocketPayloadDecodeScope] = None
        self._start_attempted = False
        self._closed = False
        self._driver_close_requested = False
        self._disconnect_observation = {
            "observed": False,
            "reason": "not_observed",
            "initiator": "none",
        }
        self._disconnect_monotonic: Optional[float] = None
        self._install_disconnect_observer()

    def _install_disconnect_observer(self) -> None:
        """Retain only an allowlisted Socket.IO disconnect reason category."""
        original = getattr(self.session, "_on_disconnect", None)
        if not callable(original):
            return

        def observe_disconnect(*args: Any, **kwargs: Any) -> Any:
            if not self._disconnect_observation["observed"]:
                reason = args[0] if args else None
                category = (
                    _SOCKET_DISCONNECT_REASONS.get(reason.strip().casefold(), "other")
                    if isinstance(reason, str)
                    else "missing"
                    if reason is None
                    else "other"
                )
                self._disconnect_observation = {
                    "observed": True,
                    "reason": category,
                    "initiator": (
                        "driver_close" if self._driver_close_requested else "socket_callback"
                    ),
                }
                self._disconnect_monotonic = time.monotonic()
            return original(*args, **kwargs)

        self.session._on_disconnect = observe_disconnect

    def socket_lifecycle_metadata(
        self,
        *,
        live_started_monotonic: Optional[float],
    ) -> dict[str, Any]:
        """Return bounded Socket.IO disconnect diagnostics."""
        disconnect_elapsed: Optional[float] = None
        if (
            isinstance(live_started_monotonic, (int, float))
            and not isinstance(live_started_monotonic, bool)
            and isinstance(self._disconnect_monotonic, (int, float))
            and self._disconnect_monotonic >= live_started_monotonic
        ):
            disconnect_elapsed = round(
                self._disconnect_monotonic - live_started_monotonic, 3
            )

        return {
            "socket_disconnect_observed": self._disconnect_observation["observed"],
            "socket_disconnect_reason": self._disconnect_observation["reason"],
            "socket_disconnect_initiator": self._disconnect_observation["initiator"],
            "socket_disconnect_after_launch_seconds": disconnect_elapsed,
            "socket_payload_decode_bound": (
                self._decode_bound_scope.metadata()
                if self._decode_bound_scope is not None
                else {
                    "source": _SOCKET_PAYLOAD_DECODE_SOURCE,
                    "before": None,
                    "active": None,
                    "after": None,
                    "restored": False,
                }
            ),
        }

    def start(self) -> Mapping[str, Any]:
        if self._start_attempted or self._closed:
            raise RowExecutionError("SocketScriptDriver sessions are single-use")
        self._start_attempted = True
        try:
            self._decode_bound_scope = _SocketPayloadDecodeScope.acquire()
            self.session.open_transcript()
            self.session.connect()
            ready = self.session.start_session(require_ready_quiet=True)
            return {"ready": ready, "readiness": self.session.start_readiness}
        except BaseException as start_error:
            try:
                self.close()
            except BaseException as close_error:
                add_note = getattr(start_error, "add_note", None)
                if callable(add_note):
                    add_note(
                        "SocketScriptDriver cleanup also failed: %s"
                        % type(close_error).__name__
                    )
            raise

    def set_active_character(self, character: str) -> bool:
        return bool(self.session.set_active_character(character))

    def send_turn(
        self,
        step_id: str,
        utterance: str,
        character: str,
    ) -> Mapping[str, Any]:
        start_index = self.session.output_count()
        result = self.session.send_turn(step_id, utterance, character)
        outputs = list(self.session.game_outputs[start_index:])
        response_text = "\n".join(
            str(row.get("payload", {}).get("content", ""))
            for row in outputs
            if isinstance(row, Mapping) and isinstance(row.get("payload"), Mapping)
        )
        return {
            "completed": not result.timed_out,
            "timed_out": result.timed_out,
            "backend_output_count": result.backend_output_count,
            "game_output_count": result.new_game_outputs,
            "elapsed_seconds": result.elapsed_seconds,
            "output_text": response_text,
        }

    def _wait_for_read_loop_exit(self) -> None:
        """Join the existing Engine.IO reader before restoring its class bound."""
        socket_client = getattr(self.session, "socket", None)
        engineio_client = getattr(socket_client, "eio", None)
        if engineio_client is None:
            return
        read_task = getattr(engineio_client, "read_loop_task", None)
        if read_task is None:
            if getattr(engineio_client, "state", None) == "connected":
                raise RowExecutionError(
                    "Engine.IO is connected but its read-loop task cannot be verified"
                )
            return

        is_alive = getattr(read_task, "is_alive", None)
        if not callable(is_alive):
            is_alive = getattr(read_task, "isAlive", None)
        if not callable(is_alive):
            raise RowExecutionError(
                "Engine.IO read-loop liveness cannot be verified before decoder restore"
            )
        if is_alive():
            join = getattr(read_task, "join", None)
            if not callable(join):
                raise RowExecutionError(
                    "active Engine.IO read loop cannot be joined before decoder restore"
                )
            join()
        if is_alive():
            raise RowExecutionError(
                "Engine.IO read loop remains active; decoder restore is unsafe"
            )

    def close(self) -> None:
        if self._closed:
            return
        self._driver_close_requested = True
        errors: list[BaseException] = []
        try:
            self.session.disconnect()
        except BaseException as exc:
            errors.append(exc)

        read_loop_stopped = False
        try:
            self._wait_for_read_loop_exit()
            read_loop_stopped = True
        except BaseException as exc:
            errors.append(exc)

        try:
            self.session.close_transcript()
        except BaseException as exc:
            errors.append(exc)

        scope = self._decode_bound_scope
        if scope is not None:
            if read_loop_stopped:
                try:
                    scope.release()
                except BaseException as exc:
                    errors.append(exc)
            else:
                errors.append(
                    RowExecutionError(
                        "Engine.IO read loop did not stop; decoder bound remains owned"
                    )
                )

        if read_loop_stopped and (
            scope is None or scope.released
        ):
            self._closed = True
        if errors:
            primary_error = errors[0]
            add_note = getattr(primary_error, "add_note", None)
            if callable(add_note):
                for extra_error in errors[1:]:
                    add_note(
                        "Additional SocketScriptDriver cleanup failure: %s"
                        % type(extra_error).__name__
                    )
            raise primary_error


def _socket_worker_lifecycle_snapshot(
    driver: Any,
    server: Any,
    live_started_monotonic: Optional[float],
) -> dict[str, Any]:
    """Capture allowlisted transport and worker state before owned teardown."""
    if isinstance(driver, SocketScriptDriver):
        result = driver.socket_lifecycle_metadata(
            live_started_monotonic=live_started_monotonic
        )
    else:
        result = {
            "socket_disconnect_observed": False,
            "socket_disconnect_reason": "not_observed",
            "socket_disconnect_initiator": "none",
            "socket_disconnect_after_launch_seconds": None,
            "socket_payload_decode_bound": {
                "source": _SOCKET_PAYLOAD_DECODE_SOURCE,
                "before": None,
                "active": None,
                "after": None,
                "restored": False,
            },
        }

    worker_state = "unknown"
    worker_return_code: Optional[int] = None
    process = getattr(server, "process", None)
    poll = getattr(process, "poll", None)
    if callable(poll):
        try:
            process_result = poll()
        except Exception:
            process_result = "unknown"
        if process_result is None:
            worker_state = "running"
        elif isinstance(process_result, int) and not isinstance(process_result, bool):
            worker_state = "exited"
            worker_return_code = process_result
    result["worker_state_at_capture"] = worker_state
    result["worker_return_code_at_capture"] = worker_return_code
    return result


def execute_row(
    run_id: str,
    row_id: str,
    *,
    row_run_id: Optional[str] = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    evidence_root: str | Path = DEFAULT_ROW_EVIDENCE_ROOT,
    prereg_root: Optional[str | Path] = None,
    runtime_root: str = "tmp/combat_capture",
    hooks: Optional[RowRunnerHooks] = None,
) -> dict[str, Any]:
    """Seed, drive, capture, score, and preserve one booked frozen row.

    The function refuses unbooked seeding and launch. Every side-effecting
    dependency is injectable so contract tests never start a server or contact a
    provider. Attempt counters and completed live intervals are persisted in the
    matrix ledger and checked before every router transport attempt.
    """
    _validate_token(run_id, "run_id")
    _validate_token(row_id, "row_id")
    reserve_assignment = get_reserve_assignment(
        run_id, row_id, ledger_root=ledger_root
    )
    if reserve_assignment is not None:
        assigned_run_id = reserve_assignment["replacement_run_id"]
        if row_run_id is not None and row_run_id != assigned_run_id:
            raise RowExecutionError("row_run_id does not match the activated reserve assignment")
        selected_run_id = assigned_run_id
    else:
        selected_run_id = row_run_id or uuid.uuid4().hex
    if not isinstance(selected_run_id, str) or not _SAFE_ROW_RUN_ID.fullmatch(selected_run_id):
        raise RowExecutionError("row_run_id must be a safe lifecycle token")
    if hooks is None:
        hooks = default_row_runner_hooks()
    try:
        assert_row_start_allowed(
            run_id,
            row_id,
            row_run_id=selected_run_id,
            ledger_root=ledger_root,
        )
    except ExecutionLedgerError as exc:
        raise RowExecutionError(str(exc)) from exc
    row, script, fixture_id = _resolve_frozen_row(
        row_id,
        prereg_root,
        reserve_assignment=reserve_assignment,
    )
    party_size = row["party"]
    row_identity = {
        "row_id": row_id,
        "fixture_id": fixture_id,
        "script_id": script["script_id"],
        "scenario_id": script["script_id"],
        "arm": row["arm"],
        "party": "P%d" % party_size,
        "seed": row["fixed_seed"],
        "block": row["block"],
        "repeat": row["repeat"],
        "run_order": row["run_order"],
    }
    if reserve_assignment is not None:
        row_identity.update(
            {
                "replacement_for": reserve_assignment["source_row_id"],
                "source_row_run_id": reserve_assignment["source_row_run_id"],
                "reserve_slot_id": row_id,
            }
        )
    runtime_directory = _row_runtime_directory(
        ledger_root, run_id, selected_run_id
    )
    require_valid_booking(run_id, ledger_root=ledger_root, now=hooks.wall_clock())
    _ensure_tmp_directory(runtime_directory)
    if runtime_directory.exists():
        raise RowExecutionError("row runtime directory already exists; reuse is refused")
    runtime_directory.mkdir(parents=True, exist_ok=False)

    lifecycle_ids: list[str] = []
    server_handles: list[Any] = []
    drivers: list[Any] = []
    active_driver: Any = None
    active_server: Any = None
    lifecycle_events: list[dict[str, Any]] = []
    expected_checks: list[dict[str, Any]] = []
    turn_results: list[dict[str, Any]] = []
    error_types: list[str] = []
    pre_content_classification: Optional[dict[str, Any]] = None
    classification_ok = True
    seeded = False
    driver_exit_code = 1
    lifecycle_ok = True
    teardown_ok = True
    live_started: Optional[float] = None
    live_finished: Optional[float] = None
    last_segment_stop: Optional[tuple[Optional[float], str]] = None
    cap_stop: Optional[dict[str, Any]] = None
    state_before: dict[str, Any] = {"status": "missing"}
    state_after: dict[str, Any] = {"status": "missing"}
    lifecycle_checkpoint: dict[str, Any] = {"status": "not_applicable"}
    zone_ledger: Any = None
    observed_movement_steps: set[str] = set()
    start_timestamps: list[str] = []
    teardown_timestamp: Optional[str] = None
    seed_started_at: Optional[str] = None
    seed_finished_at: Optional[str] = None
    evidence_finalized_at: Optional[str] = None
    scored_at: Optional[str] = None
    content_review_started_at: Optional[str] = None
    raw_live_evidence_path: Optional[str] = None
    startup_receipt_cursor = 0
    restart_receipt_cursor: Optional[int] = None
    restart_lifecycle_id: Optional[str] = None

    def timestamp() -> str:
        return _timestamp(hooks.wall_clock())

    def phase_context(step_id: str, phase: str, expected: bool) -> None:
        hooks.write_step_context(
            runtime_root,
            {
                "row_run_id": selected_run_id,
                "step_id": step_id,
                "phase": phase,
                "provider_call_expected": expected,
            },
        )

    def preserve_raw_live_evidence() -> None:
        nonlocal raw_live_evidence_path
        if raw_live_evidence_path is not None:
            return
        try:
            receipt_snapshot = hooks.load_router_receipts(selected_run_id)
        except Exception as exc:
            error_types.append(type(exc).__name__)
            receipt_snapshot = {"evidence_status": "missing", "records": []}
        packet_snapshot = _try_packet_evidence(
            hooks.load_packet_evidence,
            runtime_root,
            lifecycle_ids,
            row_identity["arm"],
            error_types,
        )
        state_snapshot = _try_state_hash(hooks.state_hasher, runtime_root, error_types)
        raw_path = runtime_directory / "raw_live_evidence.json"
        payload = {
            "row": row_identity,
            "timestamps": {
                "seed_started_at": seed_started_at,
                "seed_completed_at": seed_finished_at,
                "launch_timestamps": list(start_timestamps),
                "captured_before_teardown_at": timestamp(),
            },
            "socket_worker_lifecycle": _socket_worker_lifecycle_snapshot(
                drivers[-1] if drivers else active_driver,
                active_server,
                live_started,
            ),
            "router_receipts": (
                dict(receipt_snapshot)
                if isinstance(receipt_snapshot, Mapping)
                else {"evidence_status": "missing", "records": []}
            ),
            "exact_packets": packet_snapshot,
            "state_snapshot": state_snapshot,
            "transcript": _combined_transcript(drivers, runtime_directory),
        }
        from utils.file_operations import safe_write_json

        if not safe_write_json(
            str(raw_path),
            payload,
            create_backup=False,
            acquire_lock=True,
            json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
        ):
            error_types.append("RawLiveEvidenceWriteFailed")
            return
        raw_live_evidence_path = raw_path.as_posix()

    def reconcile_receipt_attempts() -> bool:
        try:
            snapshot = hooks.load_router_receipts(selected_run_id)
        except Exception as exc:
            error_types.append(type(exc).__name__)
            return False
        records = _receipt_snapshot_records(snapshot, selected_run_id, lifecycle_ids)
        if records is None:
            error_types.append("RouterReceiptsUnavailableDuringReconciliation")
            return False
        try:
            reconcile_attempt_count(
                run_id,
                row_id,
                selected_run_id,
                len(_attempt_ids(records)),
                ledger_root=ledger_root,
                now=hooks.wall_clock(),
            )
        except Exception as exc:
            error_types.append(type(exc).__name__)
            return False
        return True

    def request_guard() -> dict[str, Any]:
        return check_provider_request(
            run_id,
            row_id,
            selected_run_id,
            live_started_monotonic=live_started,
            monotonic_now=hooks.monotonic(),
            ledger_root=ledger_root,
            now=hooks.wall_clock(),
        )

    def stop_current() -> None:
        nonlocal active_driver, active_server, live_finished, teardown_timestamp
        nonlocal teardown_ok, last_segment_stop
        if active_driver is not None:
            try:
                active_driver.close()
            except Exception as exc:
                error_types.append(type(exc).__name__)
            drivers.append(active_driver)
            active_driver = None
        if live_started is not None:
            preserve_raw_live_evidence()
        if active_server is not None:
            stopped = False
            try:
                hooks.stop_server(active_server)
                stopped = True
            except Exception as exc:
                error_types.append(type(exc).__name__)
                teardown_ok = False
            active_server = None
            if stopped and live_started is not None:
                live_finished = _monotonic_measurement(hooks.monotonic())
                teardown_timestamp = timestamp()
                last_segment_stop = None
                try:
                    record_row_event(
                        run_id,
                        row_id,
                        selected_run_id,
                        "teardown_completed",
                        event_timestamp=teardown_timestamp,
                        live_elapsed_seconds=_elapsed_measurement(
                            live_started, live_finished
                        ),
                        ledger_root=ledger_root,
                        now=hooks.wall_clock(),
                    )
                except Exception as exc:
                    error_types.append(type(exc).__name__)
            elif not stopped:
                error_types.append("ServerTeardownIncomplete")
        elif live_started is not None and last_segment_stop is not None:
            live_finished, teardown_timestamp = last_segment_stop
            try:
                record_row_event(
                    run_id,
                    row_id,
                    selected_run_id,
                    "teardown_completed",
                    event_timestamp=teardown_timestamp,
                    live_elapsed_seconds=_elapsed_measurement(
                        live_started, live_finished
                    ),
                    ledger_root=ledger_root,
                    now=hooks.wall_clock(),
                )
            except Exception as exc:
                error_types.append(type(exc).__name__)

    try:
        def seed_booked(_booking: Mapping[str, Any]) -> Any:
            nonlocal seed_started_at
            seed_started_at = timestamp()
            record_row_event(
                run_id,
                row_id,
                selected_run_id,
                "seed_started",
                event_timestamp=seed_started_at,
                ledger_root=ledger_root,
                now=hooks.wall_clock(),
            )
            return hooks.seed(row_identity)

        seed_result = execute_booked_operation(
            run_id,
            "seed",
            seed_booked,
            ledger_root=ledger_root,
            now=hooks.wall_clock(),
        )
        seed_finished_at = timestamp()
        record_row_event(
            run_id,
            row_id,
            selected_run_id,
            "seed_completed",
            event_timestamp=seed_finished_at,
            ledger_root=ledger_root,
            now=hooks.wall_clock(),
        )
        if _result_exit_code(seed_result) != 0:
            error_types.append("SeederFailed")
        else:
            seeded = True
            state_before = _try_state_hash(hooks.state_hasher, runtime_root, error_types)
            if fixture_id == "combat_stage_tavern_zones":
                try:
                    from scripts.mapping_pilot.zone_ledger import initialize_zone_ledger

                    zone_ledger = initialize_zone_ledger(party_size, prereg_root)
                except Exception as exc:
                    error_types.append(type(exc).__name__)

            segment_number = 1
            current_step = "startup"
            lifecycle_id = _lifecycle_id(selected_run_id, segment_number)
            lifecycle_ids.append(lifecycle_id)
            phase_context(current_step, "lifecycle_control", False)
            launch_monotonic = _monotonic_measurement(hooks.monotonic())
            launch_timestamp = timestamp()
            server_identity = _server_identity(
                row_identity,
                run_id=run_id,
                row_id=row_id,
                row_run_id=selected_run_id,
                lifecycle_id=lifecycle_id,
                ledger_root=ledger_root,
                runtime_directory=runtime_directory,
                live_started_monotonic=launch_monotonic,
            )
            active_server = execute_booked_operation(
                run_id,
                "launch",
                lambda _booking: hooks.start_server(
                    server_identity,
                    selected_run_id,
                    lifecycle_id,
                    runtime_directory / ("server-segment-%02d.log" % segment_number),
                ),
                ledger_root=ledger_root,
                now=hooks.wall_clock(),
            )
            server_handles.append(active_server)
            live_started = launch_monotonic
            start_timestamps.append(launch_timestamp)
            record_row_event(
                run_id,
                row_id,
                selected_run_id,
                "sandbox_launched",
                event_timestamp=launch_timestamp,
                ledger_root=ledger_root,
                now=hooks.wall_clock(),
            )
            if not hooks.wait_server_ready(active_server, 30.0):
                error_types.append("ServerNotReady")
                raise _StopDriving
            active_driver = hooks.driver_factory(
                party_size=party_size,
                transcript_path=runtime_directory / ("transcript-segment-%02d.txt" % segment_number),
                runtime_root=runtime_root,
            )
            readiness = active_driver.start()
            if not _driver_ready(readiness):
                error_types.append("DriverNotReady")
                raise _StopDriving

            initial_receipts = hooks.load_router_receipts(selected_run_id)
            startup_records = _receipt_snapshot_records(
                initial_receipts, selected_run_id, lifecycle_ids
            )
            if startup_records is None:
                error_types.append("RouterReceiptsUnavailable")
                raise _StopDriving
            if _server_receipt_failure_seen(active_server):
                error_types.append("RouterReceiptWriteFailed")
                raise _StopDriving
            if not _receipts_have_expected_attribution(
                startup_records, "lifecycle_control", expected=False
            ):
                error_types.append("UnexpectedStartupProviderCall")
                raise _StopDriving
            if _count_unexpected_attempts(startup_records):
                error_types.append("UnexpectedStartupProviderCall")
            startup_receipt_cursor = _max_sequence(startup_records)
            if not reconcile_receipt_attempts():
                raise _StopDriving

            expected_steps = script["turns"]
            if len(expected_steps) != script["model_bearing_turn_count"]:
                error_types.append("ScriptTurnCountMismatch")
                raise _StopDriving

            for step in expected_steps:
                step_id = step["id"]
                phase_context(step_id, "lifecycle_control", False)
                if step.get("fixture_control_before_turn"):
                    _apply_fixture_control(
                        step["fixture_control_before_turn"], zone_ledger
                    )
                if step.get("pre_turn_control"):
                    if not _apply_pre_turn_control(
                        active_driver, step["pre_turn_control"], party_size
                    ):
                        error_types.append("ActiveCharacterSwitchFailed")
                        expected_checks.append(
                            _delivery_check(step_id, "active_character_switch", False)
                        )
                        raise _StopDriving

                if not turn_results:
                    pre_model_snapshot = hooks.load_router_receipts(selected_run_id)
                    pre_model_records = _receipt_snapshot_records(
                        pre_model_snapshot, selected_run_id, lifecycle_ids
                    )
                    if pre_model_records is None:
                        error_types.append("RouterReceiptsUnavailableBeforeFirstTurn")
                        raise _StopDriving
                    pre_model_receipt_write_failed = _server_receipt_failure_seen(
                        active_server
                    )
                    pre_model_lifecycle = [
                        record
                        for record in pre_model_records
                        if record["sequence"] > startup_receipt_cursor
                    ]
                    pre_model_attribution_valid = _receipts_have_expected_attribution(
                        pre_model_lifecycle,
                        "lifecycle_control",
                        expected=False,
                    )
                    if pre_model_receipt_write_failed:
                        error_types.append("RouterReceiptWriteFailed")
                    if not pre_model_attribution_valid or pre_model_receipt_write_failed:
                        error_types.append("UnexpectedPreModelProviderCall")
                        raise _StopDriving
                    if _count_unexpected_attempts(pre_model_lifecycle):
                        error_types.append("UnexpectedPreModelProviderCall")
                    if not reconcile_receipt_attempts():
                        raise _StopDriving

                actor = step.get("actor")
                character = actor.get("party_%d" % party_size) if isinstance(actor, Mapping) else None
                if not isinstance(character, str) or not character.strip():
                    error_types.append("ScriptActorMissing")
                    raise _StopDriving
                if step_id == "E4-08":
                    if (
                        lifecycle_checkpoint.get("resume_integrity_verified") is not True
                        or restart_receipt_cursor is None
                        or restart_lifecycle_id is None
                    ):
                        lifecycle_ok = False
                        error_types.append("LifecycleResumeVerificationFailed")
                        raise _StopDriving
                    pre_e4_08_snapshot = hooks.load_router_receipts(selected_run_id)
                    pre_e4_08_records = _receipt_snapshot_records(
                        pre_e4_08_snapshot, selected_run_id, lifecycle_ids
                    )
                    recent_restart_records = (
                        [
                            record
                            for record in pre_e4_08_records
                            if record["lifecycle_id"] == restart_lifecycle_id
                            or record["sequence"] > restart_receipt_cursor
                        ]
                        if pre_e4_08_records is not None
                        else []
                    )
                    resumed_state_check = _try_state_hash(
                        hooks.state_hasher, runtime_root, error_types
                    )
                    state_matches_before_e4_08 = (
                        resumed_state_check.get("status") == "recorded"
                        and resumed_state_check.get("sha256")
                        == lifecycle_checkpoint.get("saved_state_sha256")
                    )
                    receipts_valid_before_e4_08 = (
                        pre_e4_08_records is not None
                        and _receipt_evidence_status(pre_e4_08_snapshot) == "recorded"
                        and not _server_receipt_failure_seen(active_server)
                        and _receipts_have_expected_attribution(
                            recent_restart_records,
                            "lifecycle_control",
                            expected=False,
                        )
                    )
                    post_restart_unexpected = (
                        _count_unexpected_attempts(recent_restart_records)
                        if receipts_valid_before_e4_08
                        else lifecycle_checkpoint.get(
                            "provider_call_expected_false_observed", 0
                        )
                    )
                    resume_integrity_verified = (
                        state_matches_before_e4_08 and receipts_valid_before_e4_08
                    )
                    lifecycle_checkpoint.update(
                        {
                            "status": (
                                "verified"
                                if resume_integrity_verified
                                and post_restart_unexpected == 0
                                else "degraded"
                                if resume_integrity_verified
                                else "blocked"
                            ),
                            "resume_integrity_verified": resume_integrity_verified,
                            "resumed_state_sha256": resumed_state_check.get("sha256"),
                            "state_hash_matches": state_matches_before_e4_08,
                            "receipt_evidence_status": _receipt_evidence_status(
                                pre_e4_08_snapshot
                            ),
                            "post_restart_receipt_count": len(recent_restart_records),
                            "provider_call_expected_false_observed": post_restart_unexpected,
                            "receipt_write_failed": _server_receipt_failure_seen(
                                active_server
                            ),
                            "e4_08_sent": False,
                        }
                    )
                    lifecycle_check = next(
                        (
                            check
                            for check in expected_checks
                            if check.get("check_id") == "E4-07-lifecycle"
                        ),
                        None,
                    )
                    if lifecycle_check is None:
                        lifecycle_check = _lifecycle_check(
                            "E4-07", lifecycle_checkpoint, False
                        )
                        expected_checks.append(lifecycle_check)
                    lifecycle_check["observed"] = dict(lifecycle_checkpoint)
                    lifecycle_check["passed"] = (
                        lifecycle_checkpoint["status"] == "verified"
                    )
                    if not resume_integrity_verified:
                        lifecycle_ok = False
                        error_types.append("LifecycleResumeVerificationFailed")
                        raise _StopDriving
                    if post_restart_unexpected:
                        lifecycle_ok = False
                        if "UnexpectedRestartProviderCall" not in error_types:
                            error_types.append("UnexpectedRestartProviderCall")
                    if not reconcile_receipt_attempts():
                        raise _StopDriving
                request_decision = request_guard()
                if not request_decision.get("allowed"):
                    cap_stop = request_decision
                    error_types.append("PreRequestGuardRefused")
                    raise _StopDriving
                phase_context(step_id, "model_bearing_turn", True)
                if step_id == "E4-08":
                    lifecycle_checkpoint["e4_08_sent"] = True
                turn = active_driver.send_turn(step_id, step["utterance"], character)
                normalized_turn = _normalize_turn_result(turn)
                normalized_turn["step_id"] = step_id
                normalized_turn["character"] = character
                turn_results.append(normalized_turn)
                phase_context(step_id, "lifecycle_control", False)
                if not reconcile_receipt_attempts():
                    raise _StopDriving
                post_turn_guard = request_guard()
                if not post_turn_guard.get("allowed"):
                    cap_stop = post_turn_guard
                    error_types.append("LiveCapReached")
                    raise _StopDriving
                if normalized_turn.get("completed") is not True or normalized_turn.get("timed_out") is True:
                    error_types.append("TurnEvidenceIncomplete")
                    raise _StopDriving

                after_control = step.get("after_turn_control")
                if isinstance(after_control, Mapping):
                    fixture_event = after_control.get("fixture_event")
                    if fixture_event:
                        _apply_fixture_control(
                            {"fixture_event": fixture_event}, zone_ledger
                        )
                    lifecycle = after_control.get("lifecycle")
                    if lifecycle:
                        if (
                            not _is_required_lifecycle(lifecycle, step_id)
                            or after_control.get("reseed") is not False
                            or after_control.get("provider_call") is not False
                        ):
                            error_types.append("UnsupportedLifecycleControl")
                            lifecycle_ok = False
                            raise _StopDriving
                        saved_state = _try_state_hash(
                            hooks.state_hasher, runtime_root, error_types
                        )
                        saved_state_sha256 = saved_state.get("sha256")
                        if (
                            saved_state.get("status") != "recorded"
                            or not isinstance(saved_state_sha256, str)
                            or _SAFE_SHA256.fullmatch(saved_state_sha256) is None
                        ):
                            lifecycle_ok = False
                            lifecycle_checkpoint = {
                                "status": "blocked",
                                "resume_integrity_verified": False,
                                "saved_state_sha256": saved_state_sha256,
                                "resume_checkpoint_missing": True,
                                "reseed": False,
                                "e4_08_sent": False,
                            }
                            error_types.append("ResumeCheckpointUnavailable")
                            raise _StopDriving
                        receipts_before_restart = hooks.load_router_receipts(
                            selected_run_id
                        )
                        records_before_restart = _receipt_snapshot_records(
                            receipts_before_restart, selected_run_id, lifecycle_ids
                        )
                        if records_before_restart is None:
                            error_types.append("RouterReceiptsUnavailableBeforeRestart")
                            raise _StopDriving
                        receipt_cursor = _max_sequence(records_before_restart)
                        restart_receipt_cursor = receipt_cursor
                        old_driver = active_driver
                        old_driver.close()
                        drivers.append(old_driver)
                        active_driver = None
                        hooks.stop_server(active_server)
                        active_server = None
                        last_segment_stop = (
                            _monotonic_measurement(hooks.monotonic()),
                            timestamp(),
                        )
                        lifecycle_events.append(
                            {"event": "stop_only_owned_8360_server", "step_id": step_id}
                        )
                        segment_number += 1
                        lifecycle_id = _lifecycle_id(selected_run_id, segment_number)
                        lifecycle_ids.append(lifecycle_id)
                        restart_lifecycle_id = lifecycle_id
                        phase_context(step_id, "lifecycle_control", False)
                        launch_monotonic = _monotonic_measurement(
                            hooks.monotonic()
                        )
                        launch_timestamp = timestamp()
                        server_identity = _server_identity(
                            row_identity,
                            run_id=run_id,
                            row_id=row_id,
                            row_run_id=selected_run_id,
                            lifecycle_id=lifecycle_id,
                            ledger_root=ledger_root,
                            runtime_directory=runtime_directory,
                            live_started_monotonic=live_started,
                            resume_checkpoint_sha256=saved_state_sha256,
                        )
                        active_server = execute_booked_operation(
                            run_id,
                            "launch",
                            lambda _booking: hooks.start_server(
                                server_identity,
                                selected_run_id,
                                lifecycle_id,
                                runtime_directory
                                / ("server-segment-%02d.log" % segment_number),
                            ),
                            ledger_root=ledger_root,
                            now=hooks.wall_clock(),
                        )
                        server_handles.append(active_server)
                        start_timestamps.append(launch_timestamp)
                        record_row_event(
                            run_id,
                            row_id,
                            selected_run_id,
                            "sandbox_launched",
                            event_timestamp=launch_timestamp,
                            ledger_root=ledger_root,
                            now=hooks.wall_clock(),
                        )
                        last_segment_stop = None
                        server_ready = hooks.wait_server_ready(active_server, 30.0)
                        if server_ready:
                            active_driver = hooks.driver_factory(
                                party_size=party_size,
                                transcript_path=runtime_directory
                                / ("transcript-segment-%02d.txt" % segment_number),
                                runtime_root=runtime_root,
                            )
                            restart_readiness = active_driver.start()
                        else:
                            restart_readiness = {"ready": False}
                        receipts_after_restart = hooks.load_router_receipts(
                            selected_run_id
                        )
                        all_post_restart_records = _receipt_snapshot_records(
                            receipts_after_restart, selected_run_id, lifecycle_ids
                        )
                        post_restart_records = (
                            [
                                record
                                for record in all_post_restart_records
                                if record["lifecycle_id"] == lifecycle_id
                                or record["sequence"] > receipt_cursor
                            ]
                            if all_post_restart_records is not None
                            else []
                        )
                        receipt_write_failed = _server_receipt_failure_seen(
                            active_server
                        )
                        unexpected_post_restart = _count_unexpected_attempts(
                            post_restart_records
                        )
                        resumed_state = _try_state_hash(
                            hooks.state_hasher, runtime_root, error_types
                        )
                        state_matches = (
                            saved_state.get("status") == "recorded"
                            and resumed_state.get("status") == "recorded"
                            and saved_state.get("sha256")
                            == resumed_state.get("sha256")
                        )
                        receipts_recorded = (
                            _receipt_evidence_status(receipts_after_restart) == "recorded"
                            and all_post_restart_records is not None
                            and not receipt_write_failed
                        )
                        restart_ready = server_ready and _driver_ready(
                            restart_readiness
                        )
                        post_restart_attribution = _receipts_have_expected_attribution(
                            post_restart_records,
                            "lifecycle_control",
                            expected=False,
                        )
                        resume_integrity_verified = (
                            state_matches
                            and receipts_recorded
                            and restart_ready
                            and post_restart_attribution
                        )
                        lifecycle_checkpoint = {
                            "status": (
                                "verified"
                                if resume_integrity_verified
                                and unexpected_post_restart == 0
                                else "degraded"
                                if resume_integrity_verified
                                else "blocked"
                            ),
                            "resume_integrity_verified": resume_integrity_verified,
                            "saved_state_sha256": saved_state.get("sha256"),
                            "resumed_state_sha256": resumed_state.get("sha256"),
                            "state_hash_matches": state_matches,
                            "server_ready": restart_ready,
                            "receipt_evidence_status": _receipt_evidence_status(
                                receipts_after_restart
                            ),
                            "receipt_cursor_before_restart": receipt_cursor,
                            "post_restart_receipt_count": len(post_restart_records),
                            "receipt_write_failed": receipt_write_failed,
                            "provider_call_expected_false_observed": unexpected_post_restart,
                            "reseed": False,
                            "e4_08_sent": False,
                        }
                        lifecycle_events.extend(
                            [
                                {
                                    "event": "restart_same_sandbox_without_reseed",
                                    "step_id": step_id,
                                },
                                {"event": "resume_saved_state", "step_id": step_id},
                            ]
                        )
                        if not resume_integrity_verified:
                            lifecycle_ok = False
                            error_types.append("LifecycleResumeVerificationFailed")
                            expected_checks.append(
                                _lifecycle_check(step_id, lifecycle_checkpoint, False)
                            )
                            raise _StopDriving
                        if unexpected_post_restart:
                            lifecycle_ok = False
                            error_types.append("UnexpectedRestartProviderCall")
                        expected_checks.append(
                            _lifecycle_check(
                                step_id,
                                lifecycle_checkpoint,
                                unexpected_post_restart == 0,
                            )
                        )
            driver_exit_code = 0
    except _StopDriving:
        driver_exit_code = 1
    except Exception as exc:
        if isinstance(exc, (ExecutionLedgerError,)) and not seeded:
            # A missing booking is a refusal before the row starts, not a row run.
            raise
        error_types.append(type(exc).__name__)
        driver_exit_code = 1
    finally:
        stop_current()

    if seeded:
        state_after = _try_state_hash(hooks.state_hasher, runtime_root, error_types)
    elapsed_live = _elapsed_measurement(live_started, live_finished)
    if seed_started_at is not None:
        reconcile_receipt_attempts()
    if seeded:
        try:
            final_receipts = hooks.load_router_receipts(selected_run_id)
        except Exception as exc:
            error_types.append(type(exc).__name__)
            final_receipts = {"evidence_status": "degraded", "records": []}
    else:
        final_receipts = {"evidence_status": "missing", "records": []}
    final_record_value = (
        final_receipts.get("records")
        if isinstance(final_receipts, Mapping)
        else []
    )
    receipt_records = _valid_receipt_records(final_record_value)
    attempt_ids = _attempt_ids(receipt_records)
    model_records = _model_attempt_records(receipt_records)
    model_attempts = _attempt_ids(model_records)
    cap_counts = _cap_counts(run_id, row_id, ledger_root)
    cap_counts["raw_live_evidence_path"] = raw_live_evidence_path
    if cap_stop is None and isinstance(cap_counts.get("cap_stop"), Mapping):
        cap_stop = dict(cap_counts["cap_stop"])
    ledger_attempts = cap_counts["row_attempts"]
    provider_false = _count_unexpected_attempts(receipt_records)
    receipt_status = _receipt_evidence_status(final_receipts)
    if receipt_status not in ("recorded", "degraded"):
        receipt_status = "missing"
    if ledger_attempts != "unknown" and ledger_attempts != len(attempt_ids):
        receipt_status = "degraded"
    if any(
        record.get("attribution_status") != "recorded"
        or record.get("attribution") not in ("model_bearing_turn", "lifecycle_control")
        or type(record.get("provider_call_expected")) is not bool
        for record in receipt_records
    ):
        receipt_status = "degraded"
    if _receipt_snapshot_records(
        final_receipts, selected_run_id, lifecycle_ids
    ) is None and receipt_status == "recorded":
        receipt_status = "degraded"
    if any(_server_receipt_failure_seen(server) for server in server_handles):
        receipt_status = "degraded"
        error_types.append("RouterReceiptWriteFailed")
    receipt_sequences = [record.get("sequence") for record in receipt_records]
    if (
        any(
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            for sequence in receipt_sequences
        )
        or len(set(receipt_sequences)) != len(receipt_sequences)
    ):
        receipt_status = "degraded"
    if any(
        record.get("row_run_id") != selected_run_id
        or record.get("lifecycle_id") not in lifecycle_ids
        for record in receipt_records
    ):
        receipt_status = "degraded"
    expected_step_ids = {step["id"] for step in script["turns"]}
    observed_model_steps = {
        record.get("script_step_id")
        for record in model_records
        if isinstance(record.get("script_step_id"), str)
    }
    if any(
        record.get("attribution") == "model_bearing_turn"
        and record.get("script_step_id") not in expected_step_ids
        for record in model_records
    ):
        receipt_status = "degraded"
    if driver_exit_code == 0 and not expected_step_ids.issubset(observed_model_steps):
        receipt_status = "degraded"
        error_types.append("ModelTurnReceiptMissing")

    fallback_classification_reason = "no_classifier"
    if hooks.pre_content_classifier is not None:
        provider_status_codes = sorted(
            {
                str(value)
                for record in receipt_records
                for value in (record.get("http_status_code"), record.get("status_code"))
                if isinstance(value, int)
                and not isinstance(value, bool)
                and 100 <= value <= 599
            }
        )
        pre_content_context = {
            "row": dict(row_identity),
            "driver_exit_code": driver_exit_code,
            "error_types": sorted(set(error_types)),
            "lifecycle_ok": lifecycle_ok,
            "teardown_ok": teardown_ok,
            "cap_stop": (
                {
                    "reasons": list(cap_stop.get("reasons", [])),
                    "actual_counts": dict(cap_stop.get("actual_counts", {})),
                }
                if isinstance(cap_stop, Mapping)
                else None
            ),
            "turn_count": len(turn_results),
            "completed_turn_count": sum(
                1 for turn in turn_results if turn.get("completed") is True
            ),
            "expected_turn_count": len(script["turns"]),
            "router_receipt_status": receipt_status,
            "router_receipt_count": len(receipt_records),
            "provider_error_types": sorted(
                {
                    str(record["error_type"])
                    for record in receipt_records
                    if isinstance(record.get("error_type"), str)
                    and record["error_type"]
                }
            ),
            "provider_status_codes": provider_status_codes,
            "artifact_presence": {
                "raw_live_evidence": raw_live_evidence_path is not None,
                "server_logs": [
                    bool(
                        isinstance(getattr(server, "log_path", None), (str, Path))
                        and Path(getattr(server, "log_path")).is_file()
                    )
                    for server in server_handles
                ],
                "transcript_files": [
                    bool(
                        isinstance(getattr(driver, "transcript_path", None), (str, Path))
                        and Path(getattr(driver, "transcript_path")).is_file()
                    )
                    for driver in drivers
                ],
            },
            "evidence_sources": [
                Path(getattr(server, "log_path")).as_posix()
                for server in server_handles
                if isinstance(getattr(server, "log_path", None), (str, Path))
            ],
        }
        try:
            decision = hooks.pre_content_classifier(pre_content_context)
            if decision is not None:
                if not isinstance(decision, Mapping) or set(decision) != {
                    "classification",
                    "reason",
                    "evidence",
                }:
                    raise RowExecutionError("pre-content classifier result fields are invalid")
                classification_ledger = record_pre_content_classification(
                    run_id,
                    row_id,
                    selected_run_id,
                    decision["classification"],
                    reason=decision["reason"],
                    evidence=decision["evidence"],
                    ledger_root=ledger_root,
                    now=hooks.wall_clock(),
                )
                classified_slot = next(
                    slot
                    for slot in classification_ledger["slots"]
                    if slot["row_id"] == row_id
                )
                pre_content_classification = dict(
                    classified_slot["pre_content_classification"]
                )
        except Exception as exc:
            fallback_classification_reason = type(exc).__name__
            error_types.append(fallback_classification_reason)

    if pre_content_classification is None:
        try:
            classification_ledger = record_pre_content_classification(
                run_id,
                row_id,
                selected_run_id,
                "UNRESOLVED",
                reason=fallback_classification_reason,
                evidence=[],
                ledger_root=ledger_root,
                now=hooks.wall_clock(),
            )
            classified_slot = next(
                slot
                for slot in classification_ledger["slots"]
                if slot["row_id"] == row_id
            )
            pre_content_classification = dict(
                classified_slot["pre_content_classification"]
            )
        except Exception as exc:
            classification_ok = False
            error_types.append(type(exc).__name__)

    try:
        review_ledger = mark_content_review_started(
            run_id,
            row_id,
            selected_run_id,
            ledger_root=ledger_root,
            now=hooks.wall_clock(),
        )
        reviewed_slot = next(
            slot for slot in review_ledger["slots"] if slot["row_id"] == row_id
        )
        content_review_started_at = reviewed_slot["content_review_started_at"]
    except Exception as exc:
        classification_ok = False
        error_types.append(type(exc).__name__)

    cap_counts["pre_content_classification"] = pre_content_classification
    cap_counts["content_review_started_at"] = content_review_started_at

    turns_by_step = {
        turn.get("step_id"): turn
        for turn in turn_results
        if isinstance(turn.get("step_id"), str)
    }
    for step in script["turns"]:
        turn = turns_by_step.get(step["id"])
        if turn is None:
            continue
        expected_checks.append(_delivery_check(step["id"], "socket_turn", turn))
        expected_checks.extend(
            _evaluate_expected_checks(step, turn, hooks.check_evaluator)
        )
        if zone_ledger is not None:
            actor = step.get("actor")
            character = (
                actor.get("party_%d" % party_size)
                if isinstance(actor, Mapping)
                else None
            )
            _apply_movement_for_step(
                zone_ledger,
                runtime_root,
                selected_run_id,
                step,
                character,
                party_size,
                observed_movement_steps,
                prereg_root,
            )

    packet_evidence = _try_packet_evidence(
        hooks.load_packet_evidence, runtime_root, lifecycle_ids, row_identity["arm"], error_types
    )
    packet_status = packet_evidence.get("evidence_status")

    if zone_ledger is not None:
        zone_trace: Any = json.loads(_serialize_zone_ledger(zone_ledger))
        zone_observations = list(zone_ledger.observations)
    else:
        zone_trace = {"status": "not_applicable", "reason": "noncombat fixture"}
        zone_observations = []

    for step in script["turns"]:
        if step.get("expected_checks") and not any(
            check.get("check_id", "").startswith(step["id"] + "-")
            for check in expected_checks
        ):
            expected_checks.extend(
                _evaluate_expected_checks(step, {}, hooks.check_evaluator)
            )
        if step.get("expected_hint") and step["id"] not in observed_movement_steps:
            # A missing adapter observation remains explicitly missing in the
            # shadow ledger; it is not inferred from narration.
            if zone_ledger is not None:
                _apply_movement_for_step(
                    zone_ledger,
                    runtime_root,
                    selected_run_id,
                    step,
                    _script_character(step, party_size),
                    party_size,
                    observed_movement_steps,
                    prereg_root,
                )

    if not expected_checks:
        expected_checks.append(
            {
                "check_id": "row-evidence",
                "expected": "Frozen row script and required evidence are present.",
                "observed": "no scripted checks were available",
                "passed": False,
            }
        )

    model_turns = _model_turns(script["turns"], model_records)
    provider_calls = [_provider_call(record) for record in model_records]
    score_input = {
        "row_id": row_id,
        "arm": row_identity["arm"],
        "block": row_identity["block"],
        "party": row_identity["party"],
        "script": script["script_id"],
        "repeat": row_identity["repeat"],
        "completed": driver_exit_code == 0 and len(turn_results) == len(script["turns"]),
        # Frozen attempt accounting includes lifecycle-control receipts. Only
        # model-bearing records feed model_turns and provider_calls below.
        "attempt_count": (
            ledger_attempts if isinstance(ledger_attempts, int) else None
        ),
        "elapsed_seconds": (
            cap_counts["row_elapsed_seconds"]
            if isinstance(cap_counts["row_elapsed_seconds"], (int, float))
            else None
        ),
        "assistant_turns": len(turn_results),
        "zone_ledger_observations": json.dumps(
            zone_observations, ensure_ascii=True, sort_keys=True, allow_nan=False
        ),
        "model_turns": model_turns,
        "provider_calls": provider_calls,
    }
    try:
        score_output: Mapping[str, Any] = hooks.scorer(score_input)
        scoring_artifact: Mapping[str, Any] = {
            "status": "recorded",
            "score": dict(score_output),
            "attempt_accounting": {
                "actual_attempts_including_lifecycle_control": len(attempt_ids),
                "model_bearing_attempts": len(model_attempts),
                "lifecycle_control_attempts": max(0, len(attempt_ids) - len(model_attempts)),
                "provider_call_expected_false_observed": provider_false,
            },
        }
    except Exception as exc:
        error_types.append(type(exc).__name__)
        scoring_artifact = {"status": "missing", "error_type": type(exc).__name__}
    scored_at = timestamp()
    record_row_event(
        run_id,
        row_id,
        selected_run_id,
        "scored",
        event_timestamp=scored_at,
        ledger_root=ledger_root,
        now=hooks.wall_clock(),
    )

    source = _source_identity(hooks)
    input_paths = {
        "fixture": _FIXTURE_PATHS[fixture_id],
        "script": row["script"],
        "scenario": row["script"],
    }
    route_identity = _route_identity(model_records)
    provenance = {
        "source_identity": source,
        "input_paths": input_paths,
        "route_identity": route_identity,
        "evidence_kind": "live",
    }
    checks_complete = bool(expected_checks) and all(
        check.get("passed") is True for check in expected_checks
    )
    assertion_failures = [
        check
        for check in expected_checks
        if check.get("check_kind") == "assertion"
        and check.get("passed") is False
        and check.get("observed") != "not_evaluated; see transcript"
    ]
    evidence_complete = (
        packet_status in ("recorded", "not_applicable")
        and receipt_status == "recorded"
        and _receipt_evidence_status(final_receipts) == "recorded"
        and provider_false == 0
        and state_before.get("status") == "recorded"
        and state_after.get("status") == "recorded"
        and lifecycle_ok
        and teardown_ok
        and classification_ok
        and scoring_artifact.get("status") == "recorded"
        and (live_started is None or raw_live_evidence_path is not None)
    )
    caps_known_and_below = _caps_known_and_below(cap_counts)
    if assertion_failures:
        verdict = "FAIL"
    elif (
        driver_exit_code == 0
        and len(turn_results) == len(script["turns"])
        and checks_complete
        and evidence_complete
        and caps_known_and_below
    ):
        verdict = "PASS"
    else:
        verdict = "BLOCKED"

    transcript = _combined_transcript(drivers, runtime_directory)
    state_snapshots = {
        "status": "recorded" if state_before.get("status") == "recorded" else "missing",
        "before": state_before,
        "after": state_after,
        "lifecycle_checkpoint": lifecycle_checkpoint,
        "timestamps": {
            "seed_started_at": seed_started_at,
            "seed_completed_at": seed_finished_at,
            "launch_timestamps": start_timestamps,
            "teardown_completed_at": teardown_timestamp,
            "evidence_finalized_at": evidence_finalized_at,
            "scored_at": scored_at,
            "live_elapsed_seconds": elapsed_live if elapsed_live is not None else "unknown",
        },
        "raw_live_evidence_path": raw_live_evidence_path,
    }
    logs = _operational_log(
        row_identity,
        driver_exit_code,
        error_types,
        lifecycle_events,
        len(attempt_ids),
        provider_false,
    )
    artifacts = {
        "exact_packets": packet_evidence,
        "transcript": transcript,
        "state_snapshots": state_snapshots,
        "zone_trace": zone_trace,
        "expected_observed_checks": expected_checks,
        "cap_counts": cap_counts,
        "logs": logs,
        "router_receipts": {
            "evidence_status": receipt_status,
            "records": receipt_records,
            "attempt_count": len(attempt_ids),
            "provider_call_expected_false_observed": provider_false,
            "startup_provider_call_expected_false_observed": _count_unexpected_attempts(
                [
                    record
                    for record in receipt_records
                    if record.get("script_step_id") == "startup"
                    or record.get("attribution") == "lifecycle_control"
                    and record.get("script_step_id") in (None, "startup")
                ]
            ),
            "post_restart_before_e4_08_provider_call_expected_false_observed": lifecycle_checkpoint.get(
                "provider_call_expected_false_observed", 0
            ),
        },
        "scoring": scoring_artifact,
    }
    evidence_finalized_at = timestamp()
    state_snapshots["timestamps"]["evidence_finalized_at"] = evidence_finalized_at
    cap_counts["lifecycle_timestamps"] = {
        "seed_started_at": seed_started_at,
        "seed_completed_at": seed_finished_at,
        "launch_timestamps": list(start_timestamps),
        "teardown_completed_at": teardown_timestamp,
        "evidence_finalized_at": evidence_finalized_at,
        "scored_at": scored_at,
    }
    bundle_path = hooks.evidence_writer(
        "sp3",
        selected_run_id,
        row=row_identity,
        provenance=provenance,
        artifacts=artifacts,
        verdict=verdict,
        base_root=evidence_root,
        prereg_root=prereg_root,
    )
    record_row_event(
        run_id,
        row_id,
        selected_run_id,
        "evidence_finalized",
        event_timestamp=evidence_finalized_at,
        ledger_root=ledger_root,
        now=hooks.wall_clock(),
    )
    status_reason = (
        "live cap stopped further work: %s"
        % ",".join(cap_stop.get("reasons", []))
        if isinstance(cap_stop, Mapping)
        else
        "row completed with required evidence"
        if verdict == "PASS"
        else "row evidence degraded or execution incomplete"
        if verdict == "BLOCKED"
        else "one or more preregistered assertions failed"
    )
    set_slot_status(
        run_id,
        row_id,
        verdict,
        reason=status_reason,
        evidence_path=(Path(bundle_path).as_posix()),
        ledger_root=ledger_root,
        now=hooks.wall_clock(),
    )
    return {
        "row_id": row_id,
        "row_run_id": selected_run_id,
        "fixture_id": fixture_id,
        "script_id": script["script_id"],
        "party": row_identity["party"],
        "seed": row_identity["seed"],
        "driver_exit_code": driver_exit_code,
        "verdict": verdict,
        "evidence_path": Path(bundle_path).as_posix(),
        "router_attempt_count": len(attempt_ids),
        "ledger_attempt_count": ledger_attempts,
        "cap_counts": cap_counts,
        "cap_stop": cap_stop or cap_counts.get("cap_stop"),
        "pre_content_classification": pre_content_classification,
        "provider_call_expected_false_observed": provider_false,
        "lifecycle_checkpoint": lifecycle_checkpoint,
        "scoring": scoring_artifact,
    }


class _StopDriving(Exception):
    """Internal fail-stop used after preserving the current row evidence."""


def default_row_runner_hooks() -> RowRunnerHooks:
    """Build production collaborators; callers must invoke them only when booked."""
    return RowRunnerHooks(
        seed=_seed_sandbox,
        start_server=_start_owned_server,
        wait_server_ready=_wait_owned_server_ready,
        stop_server=_stop_owned_server,
        driver_factory=_make_socket_driver,
        load_packet_evidence=_load_packet_evidence,
        load_router_receipts=_load_router_receipts,
        state_hasher=hash_canonical_sandbox_state,
        write_step_context=_write_step_context,
        evidence_writer=create_evidence_bundle,
        scorer=score_row,
        source_identity=_git_source_identity,
    )


def hash_canonical_sandbox_state(
    runtime_root: str = "tmp/combat_capture",
) -> dict[str, Any]:
    """Hash only the canonical pilot state files required by E4-07 resume."""
    root = _resolve_sandbox_root(runtime_root)
    candidates: list[Path] = [root / "party_tracker.json"]
    characters = root / "characters"
    areas = root / "modules" / _MAPPING_MODULE / "areas"
    for directory in (characters, areas):
        _reject_symlink_components(root, directory)
        if not directory.is_dir():
            raise RowExecutionError("canonical sandbox state directory is missing")
        candidates.extend(sorted(directory.glob("*.json"), key=lambda path: path.name))
    module_plot = root / "modules" / _MAPPING_MODULE / "module_plot.json"
    if module_plot.exists() or module_plot.is_symlink():
        candidates.append(module_plot)
    encounters = root / "encounters"
    if encounters.exists() or encounters.is_symlink():
        _reject_symlink_components(root, encounters)
        if not encounters.is_dir():
            raise RowExecutionError("canonical sandbox encounter state is unsafe")
        candidates.extend(sorted(encounters.glob("*.json"), key=lambda path: path.name))
    if not any(path.parent == characters for path in candidates):
        raise RowExecutionError("canonical sandbox character state is missing")
    if not any(path.parent == areas for path in candidates):
        raise RowExecutionError("canonical sandbox area state is missing")

    files: dict[str, str] = {}
    for path in sorted(set(candidates), key=lambda item: item.relative_to(root).as_posix()):
        _reject_symlink_components(root, path)
        if not path.is_file():
            raise RowExecutionError("canonical sandbox state file is missing")
        relative = path.relative_to(root).as_posix()
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical = json.dumps(files, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {
        "status": "recorded",
        "sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "files": files,
    }


def _resolve_frozen_row(
    row_id: str,
    prereg_root: Optional[str | Path],
    *,
    reserve_assignment: Optional[Mapping[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    root = Path(prereg_root) if prereg_root is not None else DEFAULT_PREREG_ROOT
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    verified = verify_manifest(root)
    if "counterbalance.json" not in verified:
        raise RowExecutionError("counterbalance is not covered by the frozen manifest")
    counterbalance = _read_json(root / "counterbalance.json")
    rows = counterbalance.get("rows") if isinstance(counterbalance, Mapping) else None
    matches = [row for row in rows or [] if isinstance(row, Mapping) and row.get("row_id") == row_id]
    if len(matches) != 1:
        raise RowExecutionError("row ID is not unique in the frozen counterbalance")
    row = dict(matches[0])
    if row.get("row_type") == "replacement_only":
        if not isinstance(reserve_assignment, Mapping):
            raise RowExecutionError("reserve row has no activated replacement assignment")
        source_row_id = reserve_assignment.get("source_row_id")
        source_rows = [
            item
            for item in rows or []
            if isinstance(item, Mapping) and item.get("row_id") == source_row_id
        ]
        if len(source_rows) != 1 or source_row_id == row_id:
            raise RowExecutionError("reserve source row identity is invalid")
        inherited_cell = reserve_assignment.get("inherited_cell")
        if not isinstance(inherited_cell, Mapping):
            raise RowExecutionError("reserve inherited cell is unavailable")
        reserve_seed = row.get("fixed_seed")
        row.update(dict(inherited_cell))
        row["row_id"] = row_id
        row["fixed_seed"] = reserve_seed
        row["replacement_for"] = source_row_id
        row["source_row_run_id"] = reserve_assignment.get("source_row_run_id")
        row["replacement_run_id"] = reserve_assignment.get("replacement_run_id")
        row["row_type"] = "replacement_only"
    elif reserve_assignment is not None:
        raise RowExecutionError("planned row cannot use a reserve assignment")
    script_path = row.get("script")
    if not isinstance(script_path, str) or script_path not in verified:
        raise RowExecutionError("frozen row script is unavailable or unverified")
    script = _read_json(root.joinpath(*PurePosixPath(script_path).parts))
    if (
        not isinstance(script, Mapping)
        or not isinstance(script.get("script_id"), str)
        or not isinstance(script.get("fixture_ids"), list)
        or not script["fixture_ids"]
        or not isinstance(script.get("turns"), list)
        or type(script.get("model_bearing_turn_count")) is not int
    ):
        raise RowExecutionError("frozen row script is malformed")
    fixture_ids = script["fixture_ids"]
    if (
        any(not isinstance(item, str) or item not in _FIXTURE_PATHS for item in fixture_ids)
        or len(set(fixture_ids)) != len(fixture_ids)
    ):
        raise RowExecutionError("frozen row script names an unsupported fixture")
    if len(fixture_ids) == 1:
        fixture_id = fixture_ids[0]
    elif (
        script["script_id"] == "landscape_e2_e3"
        and fixture_ids == ["landscape_village", "transition_tower_approach"]
    ):
        fixture_id = "landscape_village"
    else:
        raise RowExecutionError("frozen row script has an unsupported fixture layout")
    if (
        type(row.get("party")) is not int
        or row.get("party") not in (1, 4)
        or row.get("arm") not in ("A", "B", "D")
    ):
        raise RowExecutionError("frozen row party or arm is invalid")
    if row.get("fixed_seed") is None or type(row.get("fixed_seed")) is not int:
        raise RowExecutionError("frozen row seed is invalid")
    return row, dict(script), fixture_id


def _seed_sandbox(row: Mapping[str, Any]) -> subprocess.CompletedProcess[str]:
    party = int(str(row["party"])[1:])
    command = [
        str(_venv_python()),
        "scripts/seed_combat_capture.py",
        "--prepare",
        "--party",
        str(party),
        "--mapping-pilot-fixture",
        str(row["fixture_id"]),
        "--mapping-pilot-arm",
        str(row["arm"]),
        "--mapping-pilot-seed",
        str(row["seed"]),
    ]
    return subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _start_owned_server(
    row: Mapping[str, Any], row_run_id: str, lifecycle_id: str, log_path: Path
) -> _OwnedServer:
    request_guard_environment = _request_guard_environment(row)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("xb")
    command = [
        str(_venv_python()),
        "-m",
        "scripts.mapping_pilot.server",
        "--arm",
        str(row["arm"]),
        "--fixture-id",
        str(row["fixture_id"]),
        "--party-size",
        str(str(row["party"])[1:]),
        "--row-run-id",
        row_run_id,
        "--lifecycle-id",
        lifecycle_id,
        "--runtime-root",
        "tmp/combat_capture",
    ]
    resume_checkpoint_sha256 = row.get("resume_checkpoint_sha256")
    if resume_checkpoint_sha256 is not None:
        if (
            not isinstance(resume_checkpoint_sha256, str)
            or _SAFE_SHA256.fullmatch(resume_checkpoint_sha256) is None
        ):
            log_handle.close()
            raise RowExecutionError("mapping-pilot resume checkpoint is invalid")
        command.extend(
            ["--resume", "--resume-checkpoint-sha256", resume_checkpoint_sha256]
        )
    environment = os.environ.copy()
    environment["NEQ_OPEN_BROWSER"] = "0"
    environment.update(request_guard_environment)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    except Exception:
        log_handle.close()
        raise
    return _OwnedServer(process, log_handle, log_path)


def _request_guard_environment(row: Mapping[str, Any]) -> dict[str, str]:
    context = row.get("_request_guard_context")
    directory_value = row.get("_request_guard_directory")
    if not isinstance(context, Mapping) or not isinstance(directory_value, str):
        raise RowExecutionError("mapping-pilot request guard context is unavailable")
    required = (
        "run_id",
        "row_id",
        "row_run_id",
        "lifecycle_id",
        "ledger_root",
        "live_started_monotonic",
    )
    if set(context) != set(required):
        raise RowExecutionError("mapping-pilot request guard context is incomplete")
    for key in ("run_id", "row_id", "row_run_id"):
        if not isinstance(context[key], str) or not _SAFE_TOKEN.fullmatch(context[key]):
            raise RowExecutionError("mapping-pilot request guard identity is invalid")
    if not _SAFE_ROW_RUN_ID.fullmatch(context["row_run_id"]):
        raise RowExecutionError("mapping-pilot request guard row-run identity is invalid")
    if (
        not isinstance(context["lifecycle_id"], str)
        or not _SAFE_LIFECYCLE_ID.fullmatch(context["lifecycle_id"])
    ):
        raise RowExecutionError("mapping-pilot request guard lifecycle identity is invalid")
    ledger_root_text = context["ledger_root"]
    ledger_parts = (
        ledger_root_text.split("/")
        if isinstance(ledger_root_text, str)
        else []
    )
    if (
        not ledger_parts
        or "\\" in ledger_root_text
        or ledger_parts[0] != "tmp"
        or any(part in ("", ".", "..") for part in ledger_parts)
    ):
        raise RowExecutionError("mapping-pilot request guard ledger path is invalid")
    ledger_root = Path(*ledger_parts)
    started = context["live_started_monotonic"]
    if (
        isinstance(started, bool)
        or not isinstance(started, (int, float))
        or not math.isfinite(float(started))
        or started < 0
    ):
        raise RowExecutionError("mapping-pilot live start measurement is invalid")

    expected_directory = (
        ledger_root
        / context["run_id"]
        / "runtime"
        / context["row_run_id"]
    )
    relative_directory = Path(directory_value)
    if (
        "\\" in directory_value
        or relative_directory.is_absolute()
        or any(part in ("", ".", "..") for part in directory_value.split("/"))
        or relative_directory.as_posix() != directory_value
        or relative_directory != expected_directory
    ):
        raise RowExecutionError("mapping-pilot request guard directory is invalid")

    try:
        source_project_root = Path(__file__).resolve(strict=True).parents[2]
        configured_project_root = Path(PROJECT_ROOT).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RowExecutionError("mapping-pilot owning repository is unavailable") from exc
    if configured_project_root != source_project_root:
        raise RowExecutionError("mapping-pilot owning repository identity is invalid")
    absolute_directory = source_project_root / relative_directory
    _reject_symlink_components(source_project_root, absolute_directory)
    try:
        absolute_directory.resolve(strict=True).relative_to(
            (source_project_root / "tmp").resolve(strict=True)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise RowExecutionError("mapping-pilot request guard directory escaped tmp") from exc
    if not absolute_directory.is_dir():
        raise RowExecutionError("mapping-pilot request guard directory is unavailable")
    bootstrap_path = absolute_directory / "sitecustomize.py"
    _reject_symlink_components(source_project_root, bootstrap_path)
    if bootstrap_path.exists():
        if not bootstrap_path.is_file() or bootstrap_path.read_text(encoding="ascii") != _REQUEST_GUARD_BOOTSTRAP:
            raise RowExecutionError("mapping-pilot request guard bootstrap was modified")
    else:
        try:
            with bootstrap_path.open("x", encoding="ascii", newline="\n") as handle:
                handle.write(_REQUEST_GUARD_BOOTSTRAP)
        except OSError as exc:
            raise RowExecutionError("mapping-pilot request guard bootstrap could not be written") from exc

    current_python_path = os.environ.get("PYTHONPATH", "")
    python_path_entries = [
        entry
        for entry in current_python_path.split(os.pathsep)
        if entry and entry != str(absolute_directory)
    ]
    environment = {
        "NEQ_MAPPING_PILOT_REQUEST_GUARD_CONTEXT": json.dumps(
            dict(context),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        "PYTHONPATH": os.pathsep.join([str(absolute_directory), *python_path_entries]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return environment


def _wait_owned_server_ready(server: _OwnedServer, timeout_seconds: float) -> bool:
    """Wait for the owned worker's 8360 listener before opening the capture client."""
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
    ):
        return False
    deadline = time.monotonic() + float(timeout_seconds)
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", 8360), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _stop_owned_server(server: _OwnedServer) -> int:
    """Stop exactly the process this row runner created; never kill by port."""
    process = server.process
    try:
        if process.poll() is None:
            process.terminate()
            try:
                return_code = process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=5.0)
        else:
            return_code = process.returncode
        return int(return_code if return_code is not None else 1)
    finally:
        try:
            server.log_handle.flush()
        finally:
            server.log_handle.close()


def _make_socket_driver(
    *, party_size: int, transcript_path: Path, runtime_root: str
) -> SocketScriptDriver:
    return SocketScriptDriver(
        party_size=party_size,
        transcript_path=transcript_path,
        runtime_root=runtime_root,
    )


def _load_packet_evidence(
    runtime_root: str, lifecycle_ids: Sequence[str]
) -> Mapping[str, Any]:
    if not lifecycle_ids:
        return {"evidence_status": "missing", "records": []}
    if len(set(lifecycle_ids)) != len(lifecycle_ids):
        return {"evidence_status": "degraded", "records": []}
    arm_a_noops: list[Mapping[str, Any]] = []
    records: list[Mapping[str, Any]] = []
    statuses: list[str] = []
    for lifecycle_id in lifecycle_ids:
        directory = (
            Path(runtime_root)
            / "mapping_pilot"
            / "turn_packet_evidence"
            / lifecycle_id
        )
        try:
            result = load_turn_packet_evidence(directory)
        except Exception:
            return {"evidence_status": "degraded", "records": []}
        statuses.append(str(result.get("evidence_status", "missing")))
        for record in result.get("records", []):
            if isinstance(record, Mapping) and record.get("event_type") == "arm_a_noop":
                arm_a_noops.append(record)
            elif isinstance(record, Mapping):
                records.append(dict(record))
    if arm_a_noops:
        if len(arm_a_noops) != len(lifecycle_ids) or records:
            return {"evidence_status": "degraded", "records": []}
        return {
            "evidence_status": "not_applicable",
            "records": [
                {
                    "event_type": "arm_a_noop",
                    "adapter_installed": False,
                    "evidence_status": "recorded",
                    "lifecycle_ids": list(lifecycle_ids),
                }
            ],
        }
    status = (
        "degraded"
        if "degraded" in statuses
        else "missing"
        if any(value != "recorded" for value in statuses)
        else "recorded"
    )
    return {"evidence_status": status, "records": records}


def _load_router_receipts(row_run_id: str) -> Mapping[str, Any]:
    root = _resolve_sandbox_root("tmp/combat_capture")
    directory = root / "mapping_pilot" / "router_receipts" / row_run_id
    _reject_symlink_components(root, directory)
    if not directory.is_dir():
        return {"evidence_status": "missing", "records": []}
    records: list[dict[str, Any]] = []
    for entry in sorted(directory.iterdir(), key=lambda path: path.name):
        if not _RECORD_NAME.fullmatch(entry.name):
            continue
        if entry.is_symlink() or not entry.is_file():
            raise RowExecutionError("router receipt record is unsafe")
        record = _read_json(entry)
        if not isinstance(record, Mapping):
            raise RowExecutionError("router receipt record is malformed")
        records.append(dict(record))
    return {"evidence_status": "recorded", "records": records}


def _write_step_context(runtime_root: str, record: Mapping[str, Any]) -> None:
    root = _resolve_sandbox_root(runtime_root)
    target = root / "mapping_pilot" / "current_script_step.json"
    _reject_symlink_components(root, target)
    from utils.file_operations import safe_write_json

    if not safe_write_json(
        str(target),
        dict(record),
        create_backup=False,
        acquire_lock=True,
        json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
    ):
        raise RowExecutionError("script-step context write failed")


def _git_source_identity() -> Mapping[str, Any]:
    def run(arguments: Sequence[str]) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    head = run(("rev-parse", "HEAD"))
    branch = run(("branch", "--show-current")) or "detached-" + head[:12]
    dirty = bool(run(("status", "--porcelain", "--untracked-files=all")))
    return {
        "git_head_sha": head,
        "branch": branch,
        "dirty": dirty,
        "worktree": str(PROJECT_ROOT.resolve()),
    }


def _cap_counts(
    run_id: str,
    row_id: str,
    ledger_root: str | Path,
) -> dict[str, Any]:
    snapshot = cap_snapshot(run_id, row_id, ledger_root=ledger_root)
    booking = snapshot["booking"]
    return {
        "row_attempts": snapshot["row_attempts"],
        "row_elapsed_seconds": snapshot["row_elapsed_seconds"],
        "matrix_attempts": snapshot["matrix_attempts"],
        "matrix_elapsed_seconds": snapshot["matrix_elapsed_seconds"],
        "cap_stop": snapshot["cap_stop"],
        "booking_timestamps": booking,
        "booked_window_elapsed_seconds": (
            booking["booked_window_elapsed_seconds"]
            if isinstance(booking, Mapping)
            and booking.get("booked_window_elapsed_seconds") is not None
            else "unknown"
        ),
        "caps": {
            "row_attempts": ROW_ATTEMPT_CAP,
            "row_wall_time_seconds": ROW_WALL_TIME_CAP_SECONDS,
            "matrix_attempts": MATRIX_ATTEMPT_CAP,
            "matrix_wall_time_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
        },
    }


def _source_identity(hooks: RowRunnerHooks) -> Mapping[str, Any]:
    value = hooks.source_identity() if hooks.source_identity is not None else _git_source_identity()
    if not isinstance(value, Mapping):
        raise RowExecutionError("source identity is unavailable")
    return dict(value)


def _route_identity(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    requested: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    for record in records:
        requested.append(
            {
                "call_id": record.get("call_id"),
                "model": record.get("requested_model"),
                "provider": record.get("transport"),
                "fallback": record.get("fallback"),
            }
        )
        resolved.append(
            {
                "call_id": record.get("call_id"),
                "model": record.get("resolved_model"),
                "provider": record.get("provider") or record.get("transport"),
                "fallback": record.get("fallback"),
            }
        )
    return {"requested": requested, "resolved": resolved}


def _provider_call(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "requested_model": record.get("requested_model"),
        "resolved_model": record.get("resolved_model"),
        "transport": record.get("transport"),
        "provider": record.get("provider"),
        "observed_upstream_provider": record.get("provider"),
        "fallback": record.get("fallback"),
    }


def _model_turns(
    steps: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for step in steps:
        step_id = step.get("id")
        selected = [
            record
            for record in records
            if record.get("attribution") == "model_bearing_turn"
            and record.get("script_step_id") == step_id
            and record.get("attempt_id")
        ]
        output.append(
            {
                "input_tokens": _sum_optional(selected, "prompt_units"),
                "output_tokens": _sum_optional(selected, "completion_units"),
                "latency_seconds": _sum_optional(selected, "elapsed_ms", divisor=1000.0),
                "cost_usd": _sum_optional(selected, "cost_usd"),
                "classifier_calls": [],
            }
        )
    return output


def _sum_optional(
    records: Sequence[Mapping[str, Any]], field: str, *, divisor: float = 1.0
) -> Optional[float | int]:
    if not records or any(
        not isinstance(record.get(field), (int, float))
        or isinstance(record.get(field), bool)
        or not math.isfinite(float(record[field]))
        for record in records
    ):
        return None
    total = sum(float(record[field]) for record in records) / divisor
    if total.is_integer():
        return int(total)
    return total


def _resolve_route_records(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return _model_attempt_records(records)


def _model_attempt_records(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    selected: dict[str, Mapping[str, Any]] = {}
    for record in records:
        attempt_id = record.get("attempt_id")
        if (
            record.get("attribution") != "model_bearing_turn"
            or record.get("attribution_status") != "recorded"
            or record.get("provider_call_expected") is not True
            or not isinstance(attempt_id, str)
            or not attempt_id
        ):
            continue
        selected.setdefault(attempt_id, record)
    return list(selected.values())


def _attempt_ids(records: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        record["attempt_id"]
        for record in records
        if isinstance(record.get("attempt_id"), str) and record.get("attempt_id")
    }


def _count_unexpected_attempts(records: Any) -> int:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return 0
    unexpected = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or record.get("provider_call_expected") is not False:
            continue
        unexpected.add(_receipt_event_key(record, index))
    return len(unexpected)


def _receipt_event_key(record: Mapping[str, Any], index: int) -> tuple[str, Any]:
    attempt_id = record.get("attempt_id")
    if isinstance(attempt_id, str) and attempt_id:
        return ("attempt", attempt_id)
    sequence = record.get("sequence")
    if isinstance(sequence, int) and not isinstance(sequence, bool):
        return ("sequence", sequence)
    return ("record", index)


def _receipts_have_expected_attribution(
    records: Sequence[Mapping[str, Any]], attribution: str, *, expected: bool
) -> bool:
    return all(
        record.get("attribution") == attribution
        and record.get("attribution_status") == "recorded"
        and record.get("provider_call_expected") is expected
        for record in records
    )


def _receipt_evidence_status(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "missing"
    status = value.get("evidence_status")
    return status if isinstance(status, str) else "missing"


def _receipt_snapshot_records(
    snapshot: Any, row_run_id: str, lifecycle_ids: Sequence[str]
) -> Optional[list[dict[str, Any]]]:
    if (
        not isinstance(snapshot, Mapping)
        or snapshot.get("evidence_status") != "recorded"
        or not isinstance(snapshot.get("records"), list)
    ):
        return None
    records: list[dict[str, Any]] = []
    seen_sequences: set[int] = set()
    for value in snapshot["records"]:
        if not isinstance(value, Mapping):
            return None
        record = dict(value)
        sequence = record.get("sequence")
        kind = record.get("kind")
        attribution = record.get("attribution")
        expected = record.get("provider_call_expected")
        step_id = record.get("script_step_id")
        attempt_id = record.get("attempt_id")
        valid_attempt_id = (
            isinstance(attempt_id, str)
            and bool(attempt_id.strip())
            and not any(ord(character) < 32 for character in attempt_id)
            and len(attempt_id) <= 160
        )
        if (
            record.get("event_type") != "router_receipt"
            or not isinstance(kind, str)
            or not kind.strip()
            or record.get("row_run_id") != row_run_id
            or record.get("lifecycle_id") not in lifecycle_ids
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or sequence in seen_sequences
            or record.get("attribution_status") != "recorded"
            or type(expected) is not bool
            or not isinstance(step_id, str)
            or not _SAFE_TOKEN.fullmatch(step_id)
            or (
                not valid_attempt_id
                and not (kind == "constructor_error" and attempt_id is None)
            )
        ):
            return None
        if attribution == "model_bearing_turn":
            if expected is not True:
                return None
        elif attribution == "lifecycle_control":
            if expected is not False:
                return None
        else:
            return None
        seen_sequences.add(sequence)
        records.append(record)
    return records


def _server_receipt_failure_seen(server: Any) -> bool:
    log_path = getattr(server, "log_path", None)
    if not isinstance(log_path, (str, Path)):
        return False
    path = Path(log_path)
    if not path.exists():
        return True
    try:
        return "mapping_pilot_router_receipt_write_failed" in path.read_text(
            encoding="ascii", errors="replace"
        )
    except OSError:
        return True


def _valid_receipt_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(record) for record in value if isinstance(record, Mapping)]


def _max_sequence(records: Any) -> int:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return 0
    values = [
        record.get("sequence")
        for record in records
        if isinstance(record, Mapping)
        and isinstance(record.get("sequence"), int)
        and not isinstance(record.get("sequence"), bool)
    ]
    return max(values, default=0)


def _try_packet_evidence(
    loader: Callable[[str, Sequence[str]], Mapping[str, Any]],
    runtime_root: str,
    lifecycle_ids: Sequence[str],
    arm: str,
    errors: list[str],
) -> dict[str, Any]:
    try:
        result = loader(runtime_root, lifecycle_ids)
        if not isinstance(result, Mapping):
            raise ValueError("packet evidence result is not an object")
        records = result.get("records")
        if not isinstance(records, list):
            raise ValueError("packet evidence records are unavailable")
        status = result.get("evidence_status")
        if arm == "A" and status == "not_applicable":
            return {"evidence_status": status, "records": [dict(row) for row in records]}
        if status not in ("recorded", "degraded", "missing"):
            status = "missing"
        return {"evidence_status": status, "records": [dict(row) for row in records]}
    except Exception as exc:
        errors.append(type(exc).__name__)
        return {"evidence_status": "degraded", "records": []}


def _try_state_hash(
    hasher: Callable[[str], Mapping[str, Any]], runtime_root: str, errors: list[str]
) -> dict[str, Any]:
    try:
        result = hasher(runtime_root)
        if (
            not isinstance(result, Mapping)
            or result.get("status") != "recorded"
            or not isinstance(result.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", result["sha256"])
            or not isinstance(result.get("files"), Mapping)
        ):
            raise ValueError("canonical state hash is malformed")
        return dict(result)
    except Exception as exc:
        errors.append(type(exc).__name__)
        return {"status": "missing", "error_type": type(exc).__name__}


def _evaluate_expected_checks(
    step: Mapping[str, Any],
    turn: Mapping[str, Any],
    evaluator: Optional[Callable[[Mapping[str, Any], Mapping[str, Any]], Any]],
) -> list[dict[str, Any]]:
    expected = step.get("expected_checks")
    if not isinstance(expected, list):
        return []
    observations: Any = None
    if evaluator is not None:
        observations = evaluator(step, turn)
    output: list[dict[str, Any]] = []
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        observations = []
    for index, check in enumerate(expected, start=1):
        observed = observations[index - 1] if index <= len(observations) else None
        if isinstance(observed, Mapping):
            observed_value = observed.get("observed", "not_evaluated; see transcript")
            passed = observed.get("passed") is True
        else:
            observed_value = "not_evaluated; see transcript"
            passed = False
        output.append(
            {
                "check_id": "%s-%02d" % (step.get("id", "step"), index),
                "check_kind": "assertion",
                "expected": check.get("assertion", "frozen assertion"),
                "observed": observed_value,
                "passed": passed,
            }
        )
    return output


def _delivery_check(step_id: str, name: str, turn: Any) -> dict[str, Any]:
    if isinstance(turn, Mapping):
        complete = turn.get("completed") is True
        not_timed_out = turn.get("timed_out") is not True
        output_count = turn.get("backend_output_count", 0)
        passed = complete and not_timed_out and isinstance(output_count, int) and output_count > 0
        observed = {
            "completed": complete,
            "timed_out": turn.get("timed_out"),
            "backend_output_count": output_count,
        }
    else:
        passed = bool(turn)
        observed = "completed" if passed else "not_completed"
    return {
        "check_id": "%s-%s" % (step_id, name),
        "check_kind": "delivery",
        "expected": "A completed socket turn has at least one backend output and no timeout.",
        "observed": observed,
        "passed": passed,
    }


def _lifecycle_check(step_id: str, checkpoint: Mapping[str, Any], passed: bool) -> dict[str, Any]:
    return {
        "check_id": "%s-lifecycle" % step_id,
        "check_kind": "lifecycle",
        "expected": "Saved canonical state hash matches after owned-server restart; no provider call occurs before E4-08.",
        "observed": dict(checkpoint),
        "passed": passed,
    }


def _normalize_turn_result(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {
        "completed": getattr(value, "timed_out", True) is False,
        "timed_out": getattr(value, "timed_out", None),
        "backend_output_count": getattr(value, "backend_output_count", 0),
        "game_output_count": getattr(value, "new_game_outputs", 0),
        "elapsed_seconds": getattr(value, "elapsed_seconds", None),
    }


def _driver_ready(value: Any) -> bool:
    if isinstance(value, Mapping):
        return value.get("ready") is True
    return value is True


def _apply_pre_turn_control(
    driver: Any, control: Mapping[str, Any], party_size: int
) -> bool:
    action = control.get("party_%d" % party_size)
    if action is None:
        return True
    if not isinstance(action, str) or not action.startswith("set_active_pc:"):
        return False
    character = action.split(":", 1)[1]
    if not character.strip() or character != character.strip():
        return False
    return bool(driver.set_active_character(character))


def _apply_fixture_control(control: Mapping[str, Any], ledger: Any) -> None:
    event = control.get("fixture_event")
    if event is None:
        event = control.get("event")
    if event is None:
        return
    if event not in (
        "resolve_one_deterministic_enemy_phase_before_round_2",
        "resolve_one_deterministic_enemy_phase_for_K3",
    ):
        raise RowExecutionError("unsupported frozen fixture control")
    if ledger is None:
        raise RowExecutionError("combat fixture control has no shadow zone ledger")
    from scripts.mapping_pilot.zone_ledger import resolve_enemy_phase

    resolve_enemy_phase(ledger)


def _apply_movement_for_step(
    ledger: Any,
    runtime_root: str,
    row_run_id: str,
    step: Mapping[str, Any],
    character: Optional[str],
    party_size: int,
    seen: set[str],
    prereg_root: Optional[str | Path],
) -> None:
    step_id = step.get("id")
    if not isinstance(step_id, str) or step_id in seen:
        return
    from scripts.mapping_pilot.adapter import MovementHintObservation
    from scripts.mapping_pilot.zone_ledger import (
        classify_movement_parse_outcome,
        load_script_intended_move,
        observe_parsed_movement_hint,
    )

    records = _read_movement_records(runtime_root, row_run_id)
    matching = [record for record in records if record.get("step_id") == step_id]
    actor_id = _actor_id_for_name(ledger, character)
    if actor_id is None:
        ledger.observations.append(
            {
                "kind": "movement_hint",
                "actor_id": "unknown",
                "status": "invalid",
                "reason": "active_actor_unmapped",
                "movement_mode": "standard",
                "hint": None,
                "path": [],
                "steps": None,
                "applied_to_shadow": False,
            }
        )
        seen.add(step_id)
        return
    if matching:
        record = matching[-1]
        status = record.get("status")
        if status not in ("valid", "missing", "invalid"):
            status = "invalid"
        hint = record.get("hint") if isinstance(record.get("hint"), Mapping) else None
        reason = record.get("reason") if isinstance(record.get("reason"), str) else None
        observation = MovementHintObservation(status, dict(hint) if hint is not None else None, reason)
    else:
        observation = MovementHintObservation("missing")
    observe_parsed_movement_hint(ledger, actor_id, observation)
    if step.get("expected_hint"):
        intended = load_script_intended_move(step_id, party_size, prereg_root)
        classify_movement_parse_outcome(ledger, intended, observation)
    seen.add(step_id)


def _read_movement_records(runtime_root: str, row_run_id: str) -> list[dict[str, Any]]:
    root = _resolve_sandbox_root(runtime_root)
    directory = root / "mapping_pilot" / "movement_observations" / row_run_id
    _reject_symlink_components(root, directory)
    if not directory.is_dir():
        return []
    output: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not _MOVEMENT_RECORD_NAME.fullmatch(path.name):
            continue
        if path.is_symlink() or not path.is_file():
            raise RowExecutionError("movement observation path is unsafe")
        value = _read_json(path)
        if isinstance(value, Mapping):
            output.append(dict(value))
    return output


def _actor_id_for_name(ledger: Any, character: Optional[str]) -> Optional[str]:
    if not isinstance(character, str):
        return None
    matches = [
        actor_id
        for actor_id, actor_name in ledger.actor_names.items()
        if actor_name == character
    ]
    return matches[0] if len(matches) == 1 else None


def _script_character(step: Mapping[str, Any], party_size: int) -> Optional[str]:
    actor = step.get("actor")
    return actor.get("party_%d" % party_size) if isinstance(actor, Mapping) else None


def _serialize_zone_ledger(ledger: Any) -> str:
    from scripts.mapping_pilot.zone_ledger import serialize_ledger

    return serialize_ledger(ledger)


def _is_required_lifecycle(value: Any, step_id: str) -> bool:
    return (
        step_id == "E4-07"
        and value
        == [
            "save_sandbox_state",
            "stop_only_owned_8360_server",
            "restart_same_sandbox_without_reseed",
            "resume_saved_state",
        ]
    )


def _combined_transcript(drivers: Sequence[Any], runtime_directory: Path) -> str:
    sections: list[str] = []
    for index, driver in enumerate(drivers, start=1):
        path = getattr(driver, "transcript_path", None)
        if isinstance(path, (str, Path)) and Path(path).is_file():
            try:
                content = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                content = "[segment %d transcript unavailable]" % index
        else:
            value = getattr(driver, "transcript", "")
            content = value if isinstance(value, str) else ""
        if content.strip():
            sections.append("[segment %d]\n%s" % (index, content.strip()))
    if not sections:
        return "[missing] no driver transcript was captured for this row"
    return "\n\n".join(sections)


def _operational_log(
    row: Mapping[str, Any],
    exit_code: int,
    errors: Sequence[str],
    lifecycle_events: Sequence[Mapping[str, Any]],
    attempts: int,
    provider_false: int,
) -> str:
    lines = [
        "mapping-pilot row=%s fixture=%s script=%s party=%s seed=%s"
        % (
            row["row_id"],
            row["fixture_id"],
            row["script_id"],
            row["party"],
            row["seed"],
        ),
        "driver_exit_code=%d router_attempt_count=%d provider_call_expected_false_observed=%d"
        % (exit_code, attempts, provider_false),
        "lifecycle_event_count=%d" % len(lifecycle_events),
    ]
    lines.extend("error_type=%s" % error for error in errors)
    return "\n".join(lines) + "\n"


def _monotonic_measurement(value: Any) -> Optional[float]:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        return None
    return float(value)


def _elapsed_measurement(
    started: Optional[float], finished: Optional[float]
) -> Optional[float]:
    start_value = _monotonic_measurement(started)
    finish_value = _monotonic_measurement(finished)
    if start_value is None or finish_value is None or finish_value < start_value:
        return None
    return finish_value - start_value


def _caps_known_and_below(value: Mapping[str, Any]) -> bool:
    limits = {
        "row_attempts": ROW_ATTEMPT_CAP,
        "row_elapsed_seconds": ROW_WALL_TIME_CAP_SECONDS,
        "matrix_attempts": MATRIX_ATTEMPT_CAP,
        "matrix_elapsed_seconds": MATRIX_WALL_TIME_CAP_SECONDS,
    }
    for name, limit in limits.items():
        item = value.get(name)
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            or item >= limit
        ):
            return False
    return True


def _row_runtime_directory(
    ledger_root: str | Path, run_id: str, row_run_id: str
) -> Path:
    root = Path(ledger_root)
    if (
        "\\" in str(ledger_root)
        or root.is_absolute()
        or not root.parts
        or root.parts[0] != "tmp"
        or any(part in ("", ".", "..") for part in str(ledger_root).split("/"))
    ):
        raise RowExecutionError("mapping-pilot ledger root is invalid")
    return root / run_id / "runtime" / row_run_id


def _server_identity(
    row: Mapping[str, Any],
    *,
    run_id: str,
    row_id: str,
    row_run_id: str,
    lifecycle_id: str,
    ledger_root: str | Path,
    runtime_directory: Path,
    live_started_monotonic: Optional[float],
    resume_checkpoint_sha256: Optional[str] = None,
) -> dict[str, Any]:
    if (
        isinstance(live_started_monotonic, bool)
        or not isinstance(live_started_monotonic, (int, float))
        or not math.isfinite(float(live_started_monotonic))
        or live_started_monotonic < 0
    ):
        raise RowExecutionError("mapping-pilot live start measurement is unknown")
    if not isinstance(lifecycle_id, str) or not _SAFE_LIFECYCLE_ID.fullmatch(lifecycle_id):
        raise RowExecutionError("mapping-pilot lifecycle ID is invalid")
    identity = dict(row)
    identity["_request_guard_context"] = {
        "run_id": run_id,
        "row_id": row_id,
        "row_run_id": row_run_id,
        "lifecycle_id": lifecycle_id,
        "ledger_root": Path(ledger_root).as_posix(),
        "live_started_monotonic": float(live_started_monotonic),
    }
    identity["_request_guard_directory"] = runtime_directory.as_posix()
    if resume_checkpoint_sha256 is not None:
        if (
            not isinstance(resume_checkpoint_sha256, str)
            or _SAFE_SHA256.fullmatch(resume_checkpoint_sha256) is None
        ):
            raise RowExecutionError("mapping-pilot resume checkpoint is invalid")
        identity["resume_checkpoint_sha256"] = resume_checkpoint_sha256
    return identity


def _ensure_tmp_directory(path: Path) -> None:
    absolute = PROJECT_ROOT / path
    _reject_symlink_components(PROJECT_ROOT, absolute)
    (PROJECT_ROOT / "tmp").mkdir(exist_ok=True)
    absolute.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(PROJECT_ROOT, absolute)
    try:
        absolute.resolve(strict=False).relative_to((PROJECT_ROOT / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise RowExecutionError("row runtime path escaped project tmp") from exc


def _resolve_sandbox_root(runtime_root: str) -> Path:
    raw = Path(runtime_root)
    if raw.is_absolute() or ".." in raw.parts or raw.as_posix() != "tmp/combat_capture":
        raise RowExecutionError("runtime root must be tmp/combat_capture")
    root = PROJECT_ROOT / raw
    _reject_symlink_components(PROJECT_ROOT, root)
    try:
        resolved = root.resolve(strict=True)
        resolved.relative_to((PROJECT_ROOT / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise RowExecutionError("mapping-pilot sandbox is unavailable") from exc
    if not resolved.is_dir():
        raise RowExecutionError("mapping-pilot sandbox is unavailable")
    return resolved


def _reject_symlink_components(root: Path, path: Path) -> None:
    try:
        absolute = path if path.is_absolute() else root / path
        absolute.relative_to(root)
    except ValueError as exc:
        raise RowExecutionError("mapping-pilot path escaped its root") from exc
    current = root
    if root.is_symlink():
        raise RowExecutionError("mapping-pilot root is a symlink")
    for part in absolute.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise RowExecutionError("mapping-pilot path traverses a symlink")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RowExecutionError("mapping-pilot JSON input is invalid") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value: %s" % value)


def _result_exit_code(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    result = getattr(value, "returncode", None)
    if isinstance(result, int) and not isinstance(result, bool):
        return result
    return 0


def _lifecycle_id(row_run_id: str, segment: int) -> str:
    value = "%s-s%d" % (row_run_id, segment)
    if len(value) > 80 or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise RowExecutionError("lifecycle ID is invalid")
    return value


def _venv_python() -> Path:
    python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RowExecutionError("repository virtual environment is unavailable")
    return python


def _validate_token(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise RowExecutionError("%s must be a safe path token" % label)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RowExecutionError("row timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
