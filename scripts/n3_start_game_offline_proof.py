# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Prove Capture_Arena start_game startup without provider or network access."""

from __future__ import annotations

import argparse
import asyncio
import builtins
import errno
import importlib
import ipaddress
import json
import logging
import math
import os
import queue
import re
import socket
import stat
import subprocess  # Bounded worker launch plus guarded host process tripwires.
import sys
import sysconfig
import tempfile
import threading
import time
import traceback
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import CodeType, ModuleType, SimpleNamespace, TracebackType
from typing import Any, Callable, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SANDBOX = Path("tmp/combat_capture")
DEFAULT_OUTPUT_PARENT = Path("tmp/router-rollout/v2-network/n3/start-game-proof")
DEFAULT_RUN_ID = "proof-20261113-a"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
MAX_HISTORY_FILES = 256
MAX_HISTORY_BYTES = 8 * 1024 * 1024
MAX_RECORDED_EGRESS = 100
MAX_EGRESS_STACK_FRAMES = 64
MAX_EGRESS_ORIGIN_FRAMES = 3
MAX_EGRESS_LIBRARY_PACKAGES = 3
MAX_FAILURE_ORIGIN_FRAMES = 5
MAX_FAILURE_ORIGIN_TRACEBACK_FRAMES = 64
MAX_FAILURE_ORIGIN_FILENAME_LENGTH = 4096
MAX_COUNTER = 1_000_000
MAX_DIAGNOSTIC_CALLS = 16
DEFAULT_DIAGNOSTIC_CALL_LIMIT = 8
STARTUP_DIAGNOSTIC_SHUTDOWN_SECONDS = 5.0
DIAGNOSTIC_TASKS = ("action_prediction", "dm_main")
DIAGNOSTIC_STUB_RESPONSES = {
    "action_prediction": '{"requires_actions": false, "reason": "offline diagnostic"}',
    "dm_main": (
        '{"narration":"The chamber is quiet, and the party is ready to begin.",'
        '"actions":[]}'
    ),
}
MAX_REASON_LENGTH = 200
MAX_BLOCKED_REASON_LENGTH = 160
MAX_INITIAL_REQUEST_MESSAGES = 10_000
MAX_INITIAL_REQUEST_CONTENT_CHARS = 10_000_000
MAX_INITIAL_REQUEST_CONTENT_PARTS = 1_000
MAX_STATIC_JSON_BYTES = 10 * 1024 * 1024
MAX_STATIC_TOTAL_BYTES = 64 * 1024 * 1024
MAX_STATIC_MODULES = 512
MAX_STATIC_AREA_FILES = 4096
MAX_REPORTED_MODULES = 512
MODULE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
EXPECTED_CAPTURE_MODULE = "Capture_Arena"
N3_LUNA_PROFILE = "n3-luna"
N3_LUNA_MODEL = "openai/gpt-6-luna"
N3_LUNA_MAX_COMPLETION_TOKENS = 2048
N3_LUNA_PROMPT_USD_PER_1K = 0.0001
N3_LUNA_COMPLETION_USD_PER_1K = 0.0005
N3_RUN_COST_CAP_USD = 0.05
N3_CUMULATIVE_COST_CAP_USD = 1.0
N3_LUNA_RATE_SOURCE = (
    "scripts/mise_en_scene/llm_staging_study3/sizing.py:21-29"
)
KNOWN_EXCHANGE_RATE_ORIGIN = (
    "utils/llm_usage_tracker.py:_resolve_exchange_rate"
)
EXCEPTION_CLASS_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
STARTUP_FAILURE_CATEGORIES = frozenset(
    {
        "none",
        "other",
        "setup_failed",
        "egress_blocked",
        "host_import_failed",
        "host_import_egress_blocked",
        "socketio_test_client_failed",
        "socketio_test_client_egress_blocked",
        "startup_event_failed",
        "startup_event_egress_blocked",
        "startup_output_failed",
        "startup_shutdown_failed",
        "provider_call_blocked",
        "process_launch_blocked",
        "router_call_blocked",
        "tripwire_blocked",
        "startup_handler_error",
    }
)
OBSERVATION_HOOK_FAILURE_REASONS = frozenset(
    {
        "observation_hook_raised",
        "observation_hook_invalid_return",
    }
)
MAX_OBSERVATION_ENTRIES = 16
MAX_OBSERVATION_KEY_LENGTH = 64
MAX_OBSERVATION_STRING_VALUE_LENGTH = 200
SAFE_MODEL_LABEL_PATTERN = re.compile(r"[A-Za-z0-9_.:/-]{1,128}\Z")
MODEL_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:\b(?:sk|pk|gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}\b|"
    r"\b[A-Za-z0-9_-]{40,}\b)"
)
SAFE_ORIGIN_PATH_PATTERN = re.compile(r"[A-Za-z0-9_./-]{1,180}\Z")
SAFE_ORIGIN_FUNCTION_PATTERN = re.compile(r"[A-Za-z0-9_<>,.-]{1,80}\Z")
SAFE_DNS_HOST_LABEL_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)
SENSITIVE_DIAGNOSTIC_PATTERN = re.compile(
    r"(?i)(?:\.env\b|\b(?:config(?:uration)?|environment|environ|"
    r"api[_ -]?key|secret|token|password|credential|authorization|bearer|"
    r"private[_ -]?key)\b)"
)
STARTUP_IMPORT_REPOSITORY_ORIGIN_ALLOWLIST = {
    identifier: identifier
    for identifier in (
        "main.py",
        "model_config.py",
        "web/web_interface.py",
        "web/shared_state.py",
        "web/output_markers.py",
        "web/extensions/live_chat_monitor.py",
        "web/extensions/streaming_events.py",
        "web/extensions/tabletop_socket_handlers.py",
        "web/routes/browser_settings_routes.py",
        "web/routes/character_sheet_routes.py",
        "web/routes/memory_routes.py",
        "web/routes/player_sharing_routes.py",
        "web/routes/tabletop_party_routes.py",
        "web/routes/toolkit_homebrew_routes.py",
        "web/routes/world_narrative_routes.py",
        "utils/provider_attempt_budget.py",
        "utils/llm_router.py",
        "utils/llm_runtime.py",
        "utils/ai_client_factory.py",
        "utils/version_checker.py",
        "utils/media_paths.py",
        "utils/repo_paths.py",
        "utils/web_boundary.py",
        "utils/redirect_debug_output.py",
        "utils/reset_campaign.py",
        "utils/pc_manager.py",
        "utils/npc_identity.py",
        "utils/module_media_generator_report.py",
        "utils/image_response_payload.py",
        "utils/enhanced_logger.py",
        "utils/toolkit_adaptation_output_safety.py",
        "utils/character_creation_audit.py",
        "utils/encoding_utils.py",
        "utils/session_cleanup.py",
        "utils/combat_summary_history.py",
        "utils/combat_latency_trace.py",
        "utils/player_stats.py",
        "utils/character_creator.py",
        "utils/save_roll_contract.py",
        "utils/location_path_finder.py",
        "utils/file_operations.py",
        "utils/module_path_manager.py",
        "utils/authoritative_state_packet.py",
        "utils/turn_time_sync.py",
        "utils/inventory_possession_authority.py",
        "utils/location_context_hygiene.py",
        "utils/tracked_transfer_runtime.py",
        "updates/update_character_info.py",
        "updates/plot_update.py",
        "updates/update_world_time.py",
        "core/toolkit/portrait_service.py",
        "core/memory/memory_db.py",
        "core/managers/status_manager.py",
        "core/managers/combat_manager.py",
        "core/combat/__init__.py",
        "core/combat/combat_manager.py",
        "core/managers/level_up_manager.py",
        "core/managers/location_manager.py",
        "core/managers/campaign_manager.py",
        "core/ai/conversation_utils.py",
        "core/ai/incremental_compression.py",
        "core/ai/action_handler.py",
        "core/ai/cumulative_summary.py",
        "core/ai/inventory_context_integration.py",
    )
}
STARTUP_IMPORT_PACKAGE_ORIGIN_ALLOWLIST = {
    identifier: "site-packages/" + identifier
    for identifier in (
        "flask/__init__.py",
        "flask/app.py",
        "flask_socketio/__init__.py",
        "socketio/__init__.py",
        "socketio/server.py",
        "engineio/__init__.py",
        "engineio/server.py",
        "werkzeug/__init__.py",
        "werkzeug/exceptions.py",
        "openai/__init__.py",
        "openai/_client.py",
        "httpx/__init__.py",
        "PIL/Image.py",
    )
}
FAILURE_ORIGIN_ALLOWED_IDENTIFIERS = frozenset(
    set(STARTUP_IMPORT_REPOSITORY_ORIGIN_ALLOWLIST.values())
    | set(STARTUP_IMPORT_PACKAGE_ORIGIN_ALLOWLIST.values())
)
PROOF_ORIGIN = "http://127.0.0.1:8360"
_MISSING_MODULE = object()
UPDATE_CHECK_NOTE = (
    "The product's read-only update check is triggered by Socket.IO connect; "
    "it is stubbed here and executes for real in live runs."
)

PROVIDER_ENVIRONMENT = {
    "NEQ_PROVIDER_ATTEMPT_BUDGET": "1",
}

SDK_PATCH_TARGETS = (
    ("openai.resources.chat.completions", "Completions", "create"),
    ("openai.resources.responses", "Responses", "create"),
    ("openai.resources.images", "Images", "generate"),
    ("openai.resources.images", "Images", "edit"),
    ("openai.resources.images", "Images", "create_variation"),
    ("openai.resources.audio.speech", "Speech", "create"),
    ("openai.resources.audio.transcriptions", "Transcriptions", "create"),
    ("openai.resources.audio.translations", "Translations", "create"),
    ("openai.resources.embeddings", "Embeddings", "create"),
    ("openai.resources.moderations", "Moderations", "create"),
)


class EgressBlocked(BaseException):
    """Fail-closed sentinel raised before a non-loopback operation proceeds."""


class ProviderCallBlocked(BaseException):
    """Fail-closed sentinel raised by every installed provider tripwire."""


class ProofSetupError(RuntimeError):
    """A bounded, reportable setup failure."""


def _sanitize_diagnostic_message(value: Any) -> str:
    """Return a short, ASCII diagnostic without paths or credential context."""
    try:
        message = str(value)[:4096]
    except BaseException:
        return "setup details redacted"
    if SENSITIVE_DIAGNOSTIC_PATTERN.search(message):
        return "setup details redacted"

    message = message.encode("ascii", errors="replace").decode("ascii")
    message = re.sub(r"(?i)\b(?:https?|ftp)://[^\s'\"<>]+", "url redacted", message)
    message = re.sub(
        r"['\"](?:(?:[A-Za-z]:)?[\\/]|\\\\)[^'\"]*['\"]",
        "path redacted",
        message,
    )
    message = re.sub(
        r"(?<![\w])(?:[A-Za-z]:[\\/]|\\\\|/)[^\s,;)'\"<>]+",
        "path redacted",
        message,
    )
    message = re.sub(
        r"(?<![\w])\.{1,2}[\\/][^\s,;)'\"<>]+",
        "path redacted",
        message,
    )
    message = re.sub(
        r"(?<![\w])(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+",
        "path redacted",
        message,
    )
    message = re.sub(
        r"(?i)\b(?:sk|pk|gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}\b",
        "value redacted",
        message,
    )
    message = re.sub(r"\b[A-Za-z0-9_-]{40,}\b", "value redacted", message)
    message = "".join(char if 32 <= ord(char) <= 126 else " " for char in message)
    message = re.sub(r"[^A-Za-z0-9 .,;:_()!?+-]", " ", message)
    message = " ".join(message.split())
    return message[: MAX_BLOCKED_REASON_LENGTH - 20] or "setup details redacted"


def _safe_blocked_reason(value: Any) -> str:
    """Normalize untrusted blocked diagnostics to the report contract."""
    text = value if isinstance(value, str) else ""
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*:\s*(.*)$", text, re.S)
    if match:
        exception_name, message = match.groups()
    else:
        exception_name, message = "RuntimeError", text
    if not EXCEPTION_CLASS_PATTERN.fullmatch(exception_name):
        exception_name = "Exception"
    sanitized = exception_name + ": " + _sanitize_diagnostic_message(message)
    return sanitized[:MAX_BLOCKED_REASON_LENGTH]


def _exception_blocked_reason(exc: BaseException) -> str:
    exception_name = type(exc).__name__
    if not EXCEPTION_CLASS_PATTERN.fullmatch(exception_name):
        exception_name = "Exception"
    try:
        message = str(exc)
    except BaseException:
        message = ""
    return _safe_blocked_reason(exception_name + ": " + message)


def _safe_exception_class(value: Any) -> Optional[str]:
    if isinstance(value, str) and EXCEPTION_CLASS_PATTERN.fullmatch(value):
        return value
    return None


def _contains_config_source_path(value: str) -> bool:
    return any(
        part.lower() == "config.py"
        for part in re.split(r"[\\/]", value)
    )


def _known_installed_package_roots() -> list[str]:
    """Return only this interpreter's configured package installation roots."""
    try:
        configured_paths = sysconfig.get_paths()
    except BaseException:
        return []

    roots: list[str] = []
    for key in ("purelib", "platlib"):
        value = configured_paths.get(key) if isinstance(configured_paths, dict) else None
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_FAILURE_ORIGIN_FILENAME_LENGTH
            or not value.isascii()
            or _contains_config_source_path(value)
        ):
            continue
        try:
            root = os.path.normpath(os.path.abspath(value))
        except (OSError, TypeError, ValueError):
            continue
        if root not in roots:
            roots.append(root)
    return roots


def _relative_python_source(
    filename: str, root: str
) -> Optional[str]:
    """Return a relative candidate solely for exact fixed-allowlist lookup."""
    try:
        candidate = os.path.normpath(os.path.abspath(filename))
        approved_root = os.path.normpath(os.path.abspath(root))
        if os.path.commonpath((candidate, approved_root)) != approved_root:
            return None
        relative = os.path.relpath(candidate, approved_root).replace(os.sep, "/")
    except (OSError, TypeError, ValueError):
        return None

    parts = relative.split("/")
    if (
        relative in ("", ".")
        or not relative.endswith(".py")
        or any(part in ("", ".", "..") for part in parts)
        or any(part.lower() == "config.py" for part in parts)
    ):
        return None
    if (
        len(relative) > 180
        or not SAFE_ORIGIN_PATH_PATTERN.fullmatch(relative)
        or MODEL_SECRET_VALUE_PATTERN.search(relative)
        or SENSITIVE_DIAGNOSTIC_PATTERN.search(relative)
    ):
        return None
    return relative


def _safe_exception_source_identifier(
    filename: Any,
    sandbox_root: Optional[Path],
    installed_roots: list[str],
) -> Optional[str]:
    """Recognize repository or configured-package Python code without opening it."""
    if (
        not isinstance(filename, str)
        or not filename
        or len(filename) > MAX_FAILURE_ORIGIN_FILENAME_LENGTH
        or not filename.isascii()
        or "\\" in filename
        or _contains_config_source_path(filename)
    ):
        return None

    for root in installed_roots:
        relative = _relative_python_source(filename, root)
        if relative is not None:
            source = STARTUP_IMPORT_PACKAGE_ORIGIN_ALLOWLIST.get(relative)
            if source is not None:
                return source

    roots: list[tuple[str, str]] = []
    if sandbox_root is not None:
        try:
            roots.append((os.fspath(sandbox_root), ""))
        except (TypeError, ValueError):
            pass
    try:
        roots.append((os.fspath(REPO_ROOT), ""))
    except (TypeError, ValueError):
        pass
    for root, _prefix in roots:
        relative = _relative_python_source(filename, root)
        source = (
            STARTUP_IMPORT_REPOSITORY_ORIGIN_ALLOWLIST.get(relative)
            if relative is not None
            else None
        )
        if source is not None:
            return source
    return None


def _exception_failure_origin(
    exc: BaseException, sandbox_root: Optional[Path]
) -> dict[str, Any]:
    """Extract bounded file/line origins without reading exception data or source."""
    unknown = {"status": "unknown", "frames": []}
    try:
        traceback_descriptor = BaseException.__dict__["__traceback__"]
        tb = traceback_descriptor.__get__(exc, type(exc))
    except BaseException:
        return unknown
    if not isinstance(tb, TracebackType):
        return unknown

    installed_roots = _known_installed_package_roots()
    frames: list[dict[str, Any]] = []
    saw_traceback = False
    rejected_frame = False
    inspected = 0
    while tb is not None and inspected < MAX_FAILURE_ORIGIN_TRACEBACK_FRAMES:
        if not isinstance(tb, TracebackType):
            rejected_frame = True
            break
        saw_traceback = True
        try:
            code = tb.tb_frame.f_code
            filename = code.co_filename if isinstance(code, CodeType) else None
            line_number = tb.tb_lineno
            source = _safe_exception_source_identifier(
                filename, sandbox_root, installed_roots
            )
        except BaseException:
            source = None
            line_number = None
        if (
            source is None
            or isinstance(line_number, bool)
            or not isinstance(line_number, int)
            or not 1 <= line_number <= MAX_COUNTER
        ):
            rejected_frame = True
        else:
            frame = {"source": source, "line": line_number}
            if frame not in frames:
                frames.append(frame)
                if len(frames) > MAX_FAILURE_ORIGIN_FRAMES:
                    del frames[0]
        try:
            tb = tb.tb_next
        except BaseException:
            tb = None
            rejected_frame = True
        inspected += 1

    if tb is not None:
        rejected_frame = True
    if frames:
        return {"status": "identified", "frames": frames}
    return {
        "status": "redacted" if saw_traceback or rejected_frame else "unknown",
        "frames": [],
    }


def _process_launch_refusal_origin(
    caller_frame: Any, sandbox_root: Optional[Path]
) -> dict[str, Any]:
    """Identify a process-launch caller only through the fixed source allowlist."""
    try:
        code = getattr(caller_frame, "f_code", None)
        filename = code.co_filename if isinstance(code, CodeType) else None
        line_number = getattr(caller_frame, "f_lineno", None)
        source = _safe_exception_source_identifier(
            filename, sandbox_root, _known_installed_package_roots()
        )
    except BaseException:
        source = None
        line_number = None

    if (
        source is None
        or isinstance(line_number, bool)
        or not isinstance(line_number, int)
        or not 1 <= line_number <= MAX_COUNTER
    ):
        return {"status": "redacted", "frames": []}

    return {
        "status": "identified",
        "frames": [{"source": source, "line": line_number}],
    }


class _ObservationClient:
    """The only object passed to an observe_running_host hook as its client
    argument. Exposes exactly emit() and get_received() -- nothing else, no
    disconnect/connect/queue access -- so a hook cannot do anything to the
    real Socket.IO test client beyond what request_status-style observation
    needs. Every event get_received() returns is also appended, unmodified,
    to a sink list owned by run_startup_diagnostic, so events the hook drains
    are not lost to the diagnostic's own later event scan."""

    def __init__(self, real_client: Any, drained_sink: list[Any]) -> None:
        self._real_client = real_client
        self._drained_sink = drained_sink

    def emit(self, name: str, *args: Any) -> Any:
        return self._real_client.emit(name, *args)

    def get_received(self) -> list[Any]:
        events = self._real_client.get_received()
        self._drained_sink.extend(events)
        return events


def _sanitize_observation_mapping(value: Any) -> Optional[dict[str, Any]]:
    """Bound an observation hook's return value to plain booleans, ints, and
    short ASCII strings only; reject anything else so an observation hook can
    never smuggle a payload, secret, or unbounded value into the report."""
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key, item in value.items():
        if len(result) >= MAX_OBSERVATION_ENTRIES:
            return None
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not (1 <= len(key) <= MAX_OBSERVATION_KEY_LENGTH)
        ):
            return None
        if isinstance(item, bool):
            result[key] = item
        elif isinstance(item, int):
            result[key] = int(item)
        elif isinstance(item, str):
            if not item.isascii() or len(item) > MAX_OBSERVATION_STRING_VALUE_LENGTH:
                return None
            result[key] = item
        else:
            return None
    return result


def _safe_failure_origin(value: Any) -> Optional[dict[str, Any]]:
    """Revalidate the bounded source/line-only report representation."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return {"status": "redacted", "frames": []}

    status = value.get("status")
    if status not in ("identified", "redacted", "unknown"):
        status = "redacted"
    raw_frames = value.get("frames")
    frames: list[dict[str, Any]] = []
    if isinstance(raw_frames, (list, tuple)):
        for frame in raw_frames[:MAX_FAILURE_ORIGIN_FRAMES]:
            if not isinstance(frame, dict):
                continue
            source = frame.get("source")
            line_number = frame.get("line")
            if (
                not isinstance(source, str)
                or not source.isascii()
                or len(source) > 180
                or not SAFE_ORIGIN_PATH_PATTERN.fullmatch(source)
                or source not in FAILURE_ORIGIN_ALLOWED_IDENTIFIERS
                or MODEL_SECRET_VALUE_PATTERN.search(source)
                or SENSITIVE_DIAGNOSTIC_PATTERN.search(source)
                or not source.endswith(".py")
                or source.startswith("/")
                or "\\" in source
                or ".." in source.split("/")
                or any(
                    part.lower() == "config.py"
                    for part in source.split("/")
                )
                or isinstance(line_number, bool)
                or not isinstance(line_number, int)
                or not 1 <= line_number <= MAX_COUNTER
            ):
                continue
            frames.append({"source": source, "line": line_number})

    if frames and status == "unknown":
        status = "redacted"
    elif not frames and status == "identified":
        status = "redacted"
    return {"status": status, "frames": frames}


def _startup_failure_category(
    exception_class: Optional[str],
    stage: str,
    recorder_failure: Optional[str] = None,
) -> str:
    """Map an exception and fixed diagnostic stage to a closed category."""
    if exception_class in (
        "EgressBlocked",
        "ConnectionRefusedError",
        "gaierror",
    ):
        if stage == "host_import":
            return "host_import_egress_blocked"
        if stage == "socketio_test_client":
            return "socketio_test_client_egress_blocked"
        if stage == "startup_event":
            return "startup_event_egress_blocked"
        return "egress_blocked"
    if exception_class == "ProviderCallBlocked":
        if recorder_failure == "native child-process launch was attempted":
            return "process_launch_blocked"
        if recorder_failure == "provider SDK entry point was attempted":
            return "provider_call_blocked"
        if recorder_failure in {
            "router call blocked by offline proof",
            "unexpected startup router entry point",
            "unrecognized startup router task",
            "extra startup router call",
            "startup router call order was not observed",
            "router/provider diagnostic call bound exceeded",
        }:
            return "router_call_blocked"
        return "tripwire_blocked"
    stage_categories = {
        "host_import": "host_import_failed",
        "socketio_test_client": "socketio_test_client_failed",
        "startup_event": "startup_event_failed",
        "startup_output": "startup_output_failed",
        "startup_shutdown": "startup_shutdown_failed",
    }
    if exception_class is not None:
        return stage_categories.get(stage, "setup_failed")
    return "none"


class ProviderCallRecorder:
    """Thread-safe counts for router and direct provider entry points."""

    def __init__(
        self,
        *,
        diagnostic_mode: bool = False,
        diagnostic_call_limit: int = DEFAULT_DIAGNOSTIC_CALL_LIMIT,
    ) -> None:
        if not 2 <= diagnostic_call_limit <= MAX_DIAGNOSTIC_CALLS:
            raise ValueError("diagnostic call limit is outside the supported bound")
        self._lock = threading.Lock()
        self.diagnostic_mode = diagnostic_mode
        self.diagnostic_call_limit = diagnostic_call_limit
        self.router_calls = 0
        self.provider_function_calls = 0
        self.update_check_calls = 0
        self.initial_narration_request: Optional[dict[str, Any]] = None
        self._diagnostic_call_events: list[dict[str, Any]] = []
        self._diagnostic_stub_call_counts = {task: 0 for task in DIAGNOSTIC_TASKS}
        self._diagnostic_failure: Optional[str] = None
        self._process_launch_refusal: Optional[dict[str, Any]] = None
        self._diagnostic_overflow = False

    def record_initial_narration_request(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        capture_site: str,
        model_config: Any,
    ) -> None:
        request = _initial_narration_request(
            args,
            kwargs,
            capture_site=capture_site,
            model_config=model_config,
        )
        if request is None:
            return
        with self._lock:
            if self.initial_narration_request is None:
                self.initial_narration_request = request

    def block_router_call(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        with self._lock:
            self.router_calls = min(self.router_calls + 1, MAX_COUNTER)
        raise ProviderCallBlocked("router call blocked by offline proof")

    def diagnostic_router_call(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        model_config: Any,
        sandbox_root: Path,
        caller_frame: Any,
        bound_method: bool = False,
        allow_stub: bool = True,
    ) -> str:
        """Record a router entry and stub only the two bounded startup tasks."""
        argument_offset = 1 if bound_method else 0
        call_args = args[argument_offset:]
        task_value = kwargs.get("task")
        if task_value is None and call_args:
            task_value = call_args[0]
        task_candidate = _safe_model_label(task_value)
        task = task_candidate if task_candidate in DIAGNOSTIC_TASKS else "unknown"
        profile_value = kwargs.get(
            "profile", kwargs.get("profile_name", kwargs.get("model_profile"))
        )
        profile = _diagnostic_profile_label(model_config, task, profile_value)
        event = _diagnostic_call_event(
            task=task,
            profile=profile,
            caller_frame=caller_frame,
            sandbox_root=sandbox_root,
        )

        failure: Optional[str] = None
        with self._lock:
            self.router_calls = min(self.router_calls + 1, MAX_COUNTER)
            if len(self._diagnostic_call_events) >= self.diagnostic_call_limit:
                self._diagnostic_overflow = True
                failure = "router/provider diagnostic call bound exceeded"
            else:
                event["sequence"] = len(self._diagnostic_call_events) + 1
                self._diagnostic_call_events.append(event)
                if not allow_stub:
                    failure = "unexpected startup router entry point"
                elif task not in DIAGNOSTIC_STUB_RESPONSES:
                    failure = "unrecognized startup router task"
                elif self._diagnostic_stub_call_counts[task] != 0:
                    failure = "extra startup router call"
                elif task == "dm_main" and self._diagnostic_stub_call_counts[
                    "action_prediction"
                ] != 1:
                    failure = "startup router call order was not observed"
                elif task == "action_prediction" and self._diagnostic_stub_call_counts[
                    "dm_main"
                ] != 0:
                    failure = "startup router call order was not observed"
                else:
                    self._diagnostic_stub_call_counts[task] += 1
            if failure is not None and self._diagnostic_failure is None:
                self._diagnostic_failure = failure

        if failure is not None:
            raise ProviderCallBlocked(failure)
        return DIAGNOSTIC_STUB_RESPONSES[task]

    def block_diagnostic_provider_call(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        sandbox_root: Path,
        caller_frame: Any,
    ) -> None:
        """Record a direct SDK entry without retaining request payload fields."""
        task = _safe_model_label(kwargs.get("task")) or "unknown"
        profile = _safe_model_label(
            kwargs.get("profile", kwargs.get("profile_name"))
        ) or "unknown"
        event = _diagnostic_call_event(
            task=task,
            profile=profile,
            caller_frame=caller_frame,
            sandbox_root=sandbox_root,
        )
        with self._lock:
            self.provider_function_calls = min(
                self.provider_function_calls + 1, MAX_COUNTER
            )
            if len(self._diagnostic_call_events) < self.diagnostic_call_limit:
                event["sequence"] = len(self._diagnostic_call_events) + 1
                self._diagnostic_call_events.append(event)
            else:
                self._diagnostic_overflow = True
            if self._diagnostic_failure is None:
                self._diagnostic_failure = "provider SDK entry point was attempted"
        del args
        raise ProviderCallBlocked("provider SDK call blocked by offline diagnostic")

    def block_diagnostic_process_launch(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        caller_frame: Any,
        sandbox_root: Optional[Path],
    ) -> None:
        """Refuse native child-process creation without retaining arguments."""
        del args, kwargs
        origin = _process_launch_refusal_origin(caller_frame, sandbox_root)
        with self._lock:
            if self._diagnostic_failure is None:
                self._diagnostic_failure = "native child-process launch was attempted"
            if self._process_launch_refusal is None:
                self._process_launch_refusal = origin
        raise ProviderCallBlocked("native child-process launch blocked")

    def process_launch_refusal_snapshot(self) -> Optional[dict[str, Any]]:
        with self._lock:
            if self._process_launch_refusal is None:
                return None
            return {
                "status": self._process_launch_refusal["status"],
                "frames": [
                    dict(frame)
                    for frame in self._process_launch_refusal["frames"]
                ],
            }

    def diagnostic_snapshot(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, int], Optional[str], bool]:
        with self._lock:
            return (
                [dict(event) for event in self._diagnostic_call_events],
                dict(self._diagnostic_stub_call_counts),
                self._diagnostic_failure,
                self._diagnostic_overflow,
            )

    def block_provider_function(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        with self._lock:
            self.provider_function_calls = min(
                self.provider_function_calls + 1, MAX_COUNTER
            )
        raise ProviderCallBlocked("provider function blocked by offline proof")

    def record_update_check(self) -> None:
        with self._lock:
            self.update_check_calls = min(self.update_check_calls + 1, MAX_COUNTER)

    def snapshot(self) -> tuple[int, int, int]:
        with self._lock:
            return (
                self.router_calls,
                self.provider_function_calls,
                self.update_check_calls,
            )

    def initial_request_snapshot(self) -> Optional[dict[str, Any]]:
        with self._lock:
            if self.initial_narration_request is None:
                return None
            return dict(self.initial_narration_request)


class PreintegrateCallRecorder(ProviderCallRecorder):
    """Allow only the two named ModuleStitcher integration call sites."""

    _TASK_SITES = {
        "safety_review": "module_stitcher.safety_review",
        "travel_narration": "module_stitcher.travel_narration",
    }
    _STUB_RESPONSES = {
        "safety_review": '{"safe": true, "reason": "offline"}',
        "travel_narration": (
            '{"travelNarration":"The party follows a quiet road toward a new region.",'
            '"dmGuidance":"Present this as a concise offline transition."}'
        ),
    }

    def __init__(self) -> None:
        super().__init__()
        self.stub_call_counts = {
            "module_stitcher.safety_review": 0,
            "module_stitcher.travel_narration": 0,
        }

    def module_stitcher_call(self, *args: Any, **kwargs: Any) -> str:
        task = kwargs.get("task")
        if task is None and args:
            task = args[0]
        site = self._TASK_SITES.get(task) if isinstance(task, str) else None
        if site is None:
            self.block_router_call(*args, **kwargs)
        with self._lock:
            self.stub_call_counts[site] = min(
                self.stub_call_counts[site] + 1, MAX_COUNTER
            )
        return self._STUB_RESPONSES[task]

    def stub_counts_snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self.stub_call_counts)


def _host_class(host: Any) -> str:
    if isinstance(host, bytes):
        try:
            normalized = host.decode("ascii")
        except UnicodeDecodeError:
            return "non_loopback"
    elif host is None:
        return "non_loopback"
    else:
        try:
            normalized = str(host)
        except BaseException:
            return "non_loopback"
    normalized = normalized.strip().strip("[]").rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return "loopback"
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return "non_loopback"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return "loopback" if address.ipv4_mapped.is_loopback else "non_loopback"
    return "loopback" if address.is_loopback else "non_loopback"


def _safe_port(port: Any) -> Optional[int]:
    if isinstance(port, bool):
        return None
    if isinstance(port, int):
        return port if 0 <= port <= 65535 else None
    if isinstance(port, str) and port.isascii() and port.isdecimal():
        if len(port) > 5:
            return None
        try:
            parsed = int(port)
        except ValueError:
            return None
        return parsed if parsed <= 65535 else None
    return None


def _safe_refusal_hostname(host: Any) -> Optional[str]:
    """Return an exact, bounded hostname/IP literal without URL or secret data."""
    if isinstance(host, bytes):
        try:
            value = host.decode("ascii")
        except UnicodeDecodeError:
            return None
    elif isinstance(host, str):
        value = host
    else:
        return None
    if (
        not value
        or value.lower() == "unavailable"
        or len(value) > 253
        or not value.isascii()
        or value != value.strip()
        or MODEL_SECRET_VALUE_PATTERN.search(value)
        or SENSITIVE_DIAGNOSTIC_PATTERN.search(value)
    ):
        return None

    candidate = (
        value[1:-1]
        if value.startswith("[") and value.endswith("]")
        else value
    )
    try:
        ipaddress.ip_address(candidate)
        return value
    except ValueError:
        pass

    hostname = candidate[:-1] if candidate.endswith(".") else candidate
    if not hostname or len(hostname) > 253:
        return None
    if any(
        not SAFE_DNS_HOST_LABEL_PATTERN.fullmatch(label)
        for label in hostname.split(".")
    ):
        return None
    return value


def _connection_refused_error() -> ConnectionRefusedError:
    return ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")


def _name_resolution_refused_error() -> socket.gaierror:
    return socket.gaierror(
        getattr(socket, "EAI_NONAME", -2), "Name or service not known"
    )


def _address_parts(address: Any) -> tuple[Any, Any]:
    if isinstance(address, tuple) and address:
        return address[0], address[1] if len(address) > 1 else None
    return address, None


def _is_ipv6_loopback_ephemeral_bind(sock: Any, address: Any) -> bool:
    if getattr(sock, "family", None) != getattr(socket, "AF_INET6", None):
        return False
    host, port = _address_parts(address)
    if _safe_port(port) != 0:
        return False
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    try:
        parsed_host = ipaddress.ip_address(host.strip().strip("[]"))
    except ValueError:
        return False
    return (
        isinstance(parsed_host, ipaddress.IPv6Address)
        and parsed_host == ipaddress.IPv6Address("::1")
    )


def _hostname_class(host: Any) -> str:
    if isinstance(host, bytes):
        try:
            normalized = host.decode("ascii")
        except UnicodeDecodeError:
            return "other"
    elif isinstance(host, str):
        normalized = host
    else:
        return "other"
    normalized = normalized.strip().strip("[]").rstrip(".").lower()
    for domain, label in (
        ("githubusercontent.com", "githubusercontent"),
        ("github.com", "github"),
        ("openrouter.ai", "openrouter"),
        ("openai.com", "openai"),
    ):
        if normalized == domain or normalized.endswith("." + domain):
            return label
    return "other"


def _third_party_package_name(filename: Path) -> Optional[str]:
    package_index: Optional[int] = None
    for index, part in enumerate(filename.parts):
        if part in ("site-packages", "dist-packages"):
            package_index = index + 1
    if package_index is None or package_index >= len(filename.parts):
        return None
    package = filename.parts[package_index]
    if package.endswith((".dist-info", ".egg-info")):
        return None
    if package.endswith(".py") and package_index == len(filename.parts) - 1:
        package = package[:-3]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", package):
        return None
    return package


def _collect_egress_origin(
    frames: list[Any], sandbox_root: Optional[Path]
) -> tuple[list[str], list[str]]:
    project_frames: list[str] = []
    library_packages: list[str] = []
    if sandbox_root is None:
        return project_frames, library_packages
    try:
        sandbox = sandbox_root.resolve(strict=False)
    except OSError:
        return project_frames, library_packages

    for frame in reversed(frames[-MAX_EGRESS_STACK_FRAMES:]):
        filename_value = getattr(frame, "filename", None)
        function_value = getattr(frame, "name", None)
        if not isinstance(filename_value, str) or not isinstance(function_value, str):
            continue
        try:
            filename = Path(filename_value).resolve(strict=False)
        except OSError:
            continue
        try:
            relative = filename.relative_to(sandbox)
        except ValueError:
            package = _third_party_package_name(filename)
            if package and package not in library_packages:
                library_packages.append(package)
                library_packages = library_packages[:MAX_EGRESS_LIBRARY_PACKAGES]
            continue
        relative_name = relative.as_posix()
        if (
            relative_name
            and SAFE_ORIGIN_PATH_PATTERN.fullmatch(relative_name)
            and SAFE_ORIGIN_FUNCTION_PATTERN.fullmatch(function_value)
        ):
            entry = relative_name + ":" + function_value
            if entry not in project_frames:
                project_frames.append(entry)
                project_frames = project_frames[:MAX_EGRESS_ORIGIN_FRAMES]
    return project_frames, library_packages


def _thread_name_class() -> str:
    try:
        current = threading.current_thread()
        if current is threading.main_thread():
            return "main"
        if isinstance(getattr(current, "name", None), str):
            return "background"
    except Exception:
        pass
    return "other"


def _safe_model_label(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    label = value.strip()
    if (
        len(label) <= 128
        and SAFE_MODEL_LABEL_PATTERN.fullmatch(label)
        and not MODEL_SECRET_VALUE_PATTERN.search(label)
    ):
        return label
    return None


def _project_relative_call_site(caller_frame: Any, sandbox_root: Path) -> str:
    """Resolve the nearest project frame without retaining an absolute path."""
    frame = caller_frame
    proof_path = Path(__file__).resolve(strict=False)
    while frame is not None:
        filename_value = getattr(getattr(frame, "f_code", None), "co_filename", None)
        line_number = getattr(frame, "f_lineno", None)
        if isinstance(filename_value, str):
            try:
                filename = Path(filename_value).resolve(strict=False)
            except OSError:
                filename = None
            if filename is not None and filename != proof_path:
                relative_name: Optional[str] = None
                for root in (sandbox_root, REPO_ROOT):
                    try:
                        relative_name = filename.relative_to(root.resolve(strict=False)).as_posix()
                        break
                    except ValueError:
                        continue
                if (
                    relative_name
                    and SAFE_ORIGIN_PATH_PATTERN.fullmatch(relative_name)
                    and isinstance(line_number, int)
                    and not isinstance(line_number, bool)
                    and 1 <= line_number <= MAX_COUNTER
                ):
                    return relative_name + ":" + str(line_number)
        frame = getattr(frame, "f_back", None)
    return "unknown:0"


def _diagnostic_call_event(
    *, task: Any, profile: Any, caller_frame: Any, sandbox_root: Path
) -> dict[str, Any]:
    """Build the exact payload-only-free event schema used by diagnostics."""
    return {
        "task": _safe_model_label(task) or "unknown",
        "profile": _safe_model_label(profile) or "unknown",
        "call_site": _project_relative_call_site(caller_frame, sandbox_root),
        "thread_id": threading.get_ident(),
        "thread_class": _thread_name_class(),
    }


def _diagnostic_profile_label(
    model_config: Any, task: str, explicit_profile: Any
) -> str:
    profiles = getattr(model_config, "MODEL_PROFILES", {})
    configured_names = {
        safe_name
        for name in profiles
        if (safe_name := _safe_model_label(name)) is not None
    } if isinstance(profiles, dict) else set()
    explicit = _safe_model_label(explicit_profile)
    if explicit in configured_names:
        return explicit
    task_overrides = getattr(model_config, "TASK_OVERRIDES", {})
    if isinstance(task_overrides, dict):
        task_override = task_overrides.get(task, {})
        if isinstance(task_override, dict):
            profile = _safe_model_label(task_override.get("profile"))
            if profile in configured_names:
                return profile
    active = _safe_model_label(getattr(model_config, "ACTIVE_PROFILE", None))
    return active if active in configured_names else "unknown"


def _safe_diagnostic_call_events(values: Any) -> tuple[list[dict[str, Any]], bool]:
    """Sanitize diagnostic calls and reject malformed, unordered observations."""
    if not isinstance(values, (list, tuple)):
        return [], False
    safe_events: list[dict[str, Any]] = []
    valid = len(values) <= MAX_DIAGNOSTIC_CALLS
    expected_sequence = 1
    for value in values[:MAX_DIAGNOSTIC_CALLS]:
        if not isinstance(value, dict):
            valid = False
            continue
        task = _safe_model_label(value.get("task")) or "unknown"
        profile = _safe_model_label(value.get("profile")) or "unknown"
        if task == "unknown" or profile == "unknown":
            valid = False
        call_site = value.get("call_site")
        thread_id = value.get("thread_id")
        thread_class = value.get("thread_class")
        sequence = value.get("sequence")
        safe_call_site = "unknown:0"
        if isinstance(call_site, str) and ":" in call_site:
            path, line_value = call_site.rsplit(":", 1)
            path_parts = Path(path).parts
            if (
                not path.startswith("/")
                and ".." not in path_parts
                and "\\" not in path
                and SAFE_ORIGIN_PATH_PATTERN.fullmatch(path)
                and path.endswith(".py")
                and 1 <= len(line_value) <= 7
                and line_value.isascii()
                and line_value.isdecimal()
                and 1 <= int(line_value) <= MAX_COUNTER
            ):
                safe_call_site = path + ":" + line_value
            else:
                valid = False
        else:
            valid = False
        if (
            isinstance(thread_id, bool)
            or not isinstance(thread_id, int)
            or not 0 < thread_id <= (1 << 64) - 1
        ):
            thread_id = 0
            valid = False
        if thread_class not in ("main", "background", "other"):
            thread_class = "other"
            valid = False
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence != expected_sequence
        ):
            valid = False
            sequence = expected_sequence
        safe_events.append(
            {
                "task": task,
                "profile": profile,
                "call_site": safe_call_site,
                "thread_id": thread_id,
                "thread_class": thread_class,
                "sequence": sequence,
            }
        )
        expected_sequence += 1
    return safe_events, valid


def _offline_diagnostic_config_module() -> ModuleType:
    """Supply safe startup defaults without importing or reading config.py."""
    module = ModuleType("config")
    safe_values = {
        "OPENAI_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "WEB_PORT": 8360,
        "WEB_HOST": "127.0.0.1",
        "WEB_CORS_ALLOWED_ORIGINS": [PROOF_ORIGIN],
        "DM_MAIN_MODEL": "offline-diagnostic",
        "PLAYER_INFO_UPDATE_MODEL": "offline-diagnostic",
        "NPC_INFO_UPDATE_MODEL": "offline-diagnostic",
        "COMBAT_MAIN_MODEL": "offline-diagnostic",
        "COMBAT_DIALOGUE_SUMMARY_MODEL": "offline-diagnostic",
        "DM_SUMMARIZATION_MODEL": "offline-diagnostic",
        "DM_VALIDATION_MODEL": "offline-diagnostic",
        "DM_MINI_MODEL": "offline-diagnostic",
        "DM_FULL_MODEL": "offline-diagnostic",
        "GPT5_MINI_MODEL": "offline-diagnostic",
        "GPT5_FULL_MODEL": "offline-diagnostic",
        "LEVEL_UP_MODEL": "offline-diagnostic",
        "ENABLE_INTELLIGENT_ROUTING": False,
        "MAX_VALIDATION_RETRIES": 0,
        "USE_GPT5_MODELS": False,
        "GPT5_USE_HIGH_REASONING_ON_RETRY": False,
        "MULTIPLAYER_MODE": False,
        "DEBUG_STATUS_SYNC": False,
    }
    module.__dict__.update(safe_values)
    module.__file__ = "<offline-diagnostic-config>"
    return module


class _DiscardingTextStream:
    """Text stream that drops application prompts, output, and diagnostics."""

    encoding = "ascii"
    errors = "replace"

    def write(self, value: Any) -> int:
        return len(value) if isinstance(value, str) else 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def __enter__(self) -> "_DiscardingTextStream":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        del exc_type, exc, tb
        self.flush()

    def writelines(self, values: Any) -> None:
        for value in values:
            self.write(value)


class _OfflineDiagnosticClient:
    """Inert replacement for the import-time legacy provider client."""

    def __init__(self, recorder: ProviderCallRecorder, sandbox_root: Path) -> None:
        self._recorder = recorder
        self._sandbox_root = sandbox_root

    def __getattr__(self, name: str) -> Any:
        del name
        self._recorder.block_diagnostic_provider_call(
            (),
            {"task": "unknown"},
            sandbox_root=self._sandbox_root,
            caller_frame=sys._getframe(1),
        )


def _startup_diagnostic_worker_environment() -> dict[str, str]:
    """Build a credential-free child environment from a minimal allowlist."""
    environment: dict[str, str] = {}
    for name in ("LANG", "LC_ALL", "LC_CTYPE"):
        value = os.environ.get(name)
        if isinstance(value, str) and value:
            environment[name] = value
    environment["PATH"] = ""
    environment["PYTHONPATH"] = str(REPO_ROOT)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["NEQ_OPEN_BROWSER"] = "0"
    return environment


def _is_sensitive_diagnostic_log_path(path_value: Any, sandbox_root: Path) -> bool:
    if not isinstance(path_value, (str, bytes, os.PathLike)):
        return False
    try:
        value = os.fsdecode(os.fspath(path_value))
        candidate = os.path.abspath(
            value if os.path.isabs(value) else os.path.join(sandbox_root, value)
        )
    except (OSError, TypeError, ValueError):
        return False
    temporary_conversation = os.path.abspath(
        os.path.join(tempfile.gettempdir(), "temp_conversation_for_api.json")
    )
    if candidate == temporary_conversation:
        return True
    try:
        relative = Path(candidate).relative_to(sandbox_root)
    except ValueError:
        return False
    if (
        relative.parts[:2] == ("debug", "quality_control")
        and relative.name in ("model_selection.jsonl", "model_results.jsonl")
    ):
        return True
    return False


def _is_nonempty_narration_payload(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("type") != "narration":
        return False
    content = value.get("content")
    return isinstance(content, str) and bool(content.strip())


def _startup_diagnostic_report(
    *,
    call_events: Any,
    stub_call_counts: Any,
    router_calls: Any,
    provider_calls: Any,
    network_attempts: Any,
    ledger_reservations: Any,
    ledger_valid: bool,
    startup_output_delivered: bool,
    game_started: bool,
    startup_thread_stopped: bool,
    diagnostic_failure: Optional[str],
    call_overflow: bool,
    router_call_guard: bool,
    router_decide_guard: bool,
    sdk_tripwire_count: int,
    egress_guard_active: bool,
    process_launch_guard: bool = False,
    host_imports_verified: bool = False,
    startup_boundary_guard_active: bool = False,
    egress_attributions: Any = None,
    egress_refusals: Any = None,
    egress_refusal_count: Any = None,
    failure_exception_class: Optional[str] = None,
    failure_category: Optional[str] = None,
    failure_origin: Any = None,
    process_launch_refusal: Any = None,
    observation: Optional[Mapping[str, object]] = None,
    observation_failure: Optional[str] = None,
) -> dict[str, Any]:
    """Build a payload-free, bounded report for the actual start_game path."""
    safe_events, event_schema_valid = _safe_diagnostic_call_events(call_events)
    safe_stub_counts = {
        task: _bounded_count(
            stub_call_counts.get(task, 0)
            if isinstance(stub_call_counts, dict)
            else 0
        )
        for task in DIAGNOSTIC_TASKS
    }
    safe_router_calls = _bounded_count(router_calls)
    safe_provider_calls = _bounded_count(provider_calls)
    safe_network_attempts = _bounded_count(network_attempts)
    safe_egress_refusals, refusal_events_valid = _safe_egress_refusals(
        egress_refusals
    )
    refusal_coverage_complete = bool(
        refusal_events_valid
        and _bounded_count(egress_refusal_count) == safe_network_attempts
        and len(safe_egress_refusals) == safe_network_attempts
    )
    safe_failure_class = _safe_exception_class(failure_exception_class)
    safe_failure_category = (
        failure_category
        if isinstance(failure_category, str)
        and failure_category in STARTUP_FAILURE_CATEGORIES
        else ("other" if diagnostic_failure else "none")
    )
    safe_ledger_reservations = (
        _bounded_count(ledger_reservations)
        if ledger_reservations is not None
        else None
    )
    coverage_established = bool(
        router_call_guard
        and router_decide_guard
        and isinstance(sdk_tripwire_count, int)
        and not isinstance(sdk_tripwire_count, bool)
        and sdk_tripwire_count >= 1
        and egress_guard_active
        and process_launch_guard
        and host_imports_verified
        and startup_boundary_guard_active
        and event_schema_valid
        and refusal_coverage_complete
        and not call_overflow
    )
    expected_call_sequence = [
        {"task": "action_prediction", "sequence": 1},
        {"task": "dm_main", "sequence": 2},
    ]
    observed_call_sequence = [
        {"task": event["task"], "sequence": event["sequence"]}
        for event in safe_events
    ]
    expected_stubs = {"action_prediction": 1, "dm_main": 1}
    clean_calls = (
        observed_call_sequence == expected_call_sequence
        and safe_stub_counts == expected_stubs
        and safe_router_calls == 2
        and safe_provider_calls == 0
        and diagnostic_failure is None
    )
    safe_observation_failure = (
        observation_failure
        if isinstance(observation_failure, str)
        and observation_failure in OBSERVATION_HOOK_FAILURE_REASONS
        else (None if observation_failure is None else "observation_hook_failed")
    )
    passed = bool(
        coverage_established
        and startup_output_delivered
        and game_started
        and startup_thread_stopped
        and clean_calls
        and safe_network_attempts == 0
        and safe_ledger_reservations == 0
        and ledger_valid
        and safe_observation_failure is None
    )

    if passed:
        reason = "startup narration delivered with bounded offline router stubs"
    elif safe_observation_failure is not None:
        reason = "observation hook failed (" + safe_observation_failure + ")"
    elif not coverage_established:
        if not host_imports_verified:
            reason = "complete real sandbox host imports were not verified"
        elif not process_launch_guard:
            reason = "native process-launch tripwire coverage was not established"
        elif not startup_boundary_guard_active:
            reason = "startup boundary guards were not fully installed"
        else:
            reason = "router/provider/network tripwire coverage was not established"
    elif safe_network_attempts:
        reason = "network attempt was blocked by the offline diagnostic"
    elif safe_provider_calls:
        reason = "direct provider SDK call was blocked by the offline diagnostic"
    elif diagnostic_failure:
        reason = diagnostic_failure[:MAX_REASON_LENGTH]
    elif not startup_output_delivered:
        reason = "startup narration output was not delivered within the bound"
    elif not game_started:
        reason = "start_game did not report successful startup"
    elif not startup_thread_stopped:
        reason = "startup runtime did not stop after the diagnostic shutdown input"
    elif not clean_calls:
        reason = "startup router call sequence was incomplete or unexpected"
    elif safe_ledger_reservations != 0 or not ledger_valid:
        reason = "provider attempt ledger was not verified empty"
    else:
        reason = "startup diagnostic did not establish a safe pass"

    return {
        "verdict": "PASS" if passed else "BLOCKED",
        "reason": reason[:MAX_REASON_LENGTH],
        "startup_output_delivered": bool(startup_output_delivered),
        "game_started": bool(game_started),
        "startup_thread_stopped": bool(startup_thread_stopped),
        "coverage_established": coverage_established,
        "call_trace": safe_events,
        "stub_call_counts": safe_stub_counts,
        "router_call_count": safe_router_calls,
        "provider_call_count": safe_provider_calls,
        "network_attempt_count": safe_network_attempts,
        "egress_refusals": safe_egress_refusals,
        "egress_refusal_coverage_complete": refusal_coverage_complete,
        "network_attempt_attributions": _safe_egress_attributions(
            egress_attributions
        ),
        "failure_exception_class": safe_failure_class,
        "failure_category": safe_failure_category,
        "failure_origin": _safe_failure_origin(failure_origin),
        "process_launch_refusal": _safe_failure_origin(process_launch_refusal),
        "ledger_reservation_count": safe_ledger_reservations,
        "ledger_valid": bool(ledger_valid),
        "tripwire_coverage": {
            "router_call": bool(router_call_guard),
            "router_decide": bool(router_decide_guard),
            "sdk_method_count": min(max(sdk_tripwire_count, 0), len(SDK_PATCH_TARGETS)),
            "socket_egress": bool(egress_guard_active),
            "process_launch": bool(process_launch_guard),
            "real_host_imports": bool(host_imports_verified),
            "startup_boundaries": bool(startup_boundary_guard_active),
        },
        "observation": _sanitize_observation_mapping(observation),
        "observation_failure": safe_observation_failure,
    }


def _safe_price_per_1k(value: Any) -> Optional[dict[str, float]]:
    if not isinstance(value, dict):
        return None
    result: dict[str, float] = {}
    for key in ("prompt", "completion", "cache_read"):
        amount = value.get(key)
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        try:
            normalized = float(amount)
        except (OverflowError, TypeError, ValueError):
            continue
        if math.isfinite(normalized) and 0 <= normalized <= 1_000_000:
            result[key] = round(normalized, 8)
    return result or None


def _profile_request_labels(
    model_config: Any,
    task_name: str,
    model_tier: Optional[str],
    argument_profile: Any,
) -> dict[str, Any]:
    active_profile = _safe_model_label(
        getattr(model_config, "ACTIVE_PROFILE", None)
    )
    profiles = getattr(model_config, "MODEL_PROFILES", {})
    if not isinstance(profiles, dict):
        profiles = {}
    overrides = getattr(model_config, "TASK_OVERRIDES", {})
    if not isinstance(overrides, dict):
        overrides = {}
    task_override = overrides.get(task_name, {})
    if not isinstance(task_override, dict):
        task_override = {}

    argument_profile_name = _safe_model_label(argument_profile)
    configured_profile_name = _safe_model_label(task_override.get("profile"))
    profile_name = configured_profile_name or active_profile
    profile = profiles.get(profile_name, {}) if profile_name else {}
    if not isinstance(profile, dict):
        profile = {}

    task_tiers = getattr(model_config, "AUTO_ROUTER_TASK_COST_TIERS", {})
    if not isinstance(task_tiers, dict):
        task_tiers = {}
    task_tier = task_tiers.get(task_name)
    if task_tier not in ("low", "medium", "high", "xhigh", "max"):
        task_tier = None

    explicit_model = _safe_model_label(task_override.get("model"))
    if explicit_model in profiles:
        explicit_model = None
    tier_names = [model_tier] if model_tier in ("simple", "complex") else [
        "simple",
        "complex",
    ]
    configured_provider = getattr(model_config, "LLM_PROVIDER", None)
    if configured_provider not in ("openrouter", "openai"):
        configured_provider = None
    model_options: list[dict[str, Any]] = []
    for tier_name in tier_names:
        tier_data = profile.get(tier_name, {})
        if not isinstance(tier_data, dict):
            tier_data = {}
        model_id = explicit_model or _safe_model_label(tier_data.get("model"))
        if model_id is None:
            continue
        provider_preferences = tier_data.get("provider", {})
        if not isinstance(provider_preferences, dict):
            provider_preferences = {}
        params = tier_data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        completion_cap = params.get(
            "max_completion_tokens", params.get("max_tokens")
        )
        if (
            not isinstance(completion_cap, int)
            or isinstance(completion_cap, bool)
            or not 1 <= completion_cap <= 1_000_000
        ):
            completion_cap = None
        model_options.append(
            {
                "tier": tier_name,
                "model_id": model_id,
                "price_per_1k": (
                    None
                    if explicit_model
                    else _safe_price_per_1k(tier_data.get("price_per_1k"))
                ),
                "provider_allow_fallbacks": (
                    provider_preferences.get("allow_fallbacks")
                    if isinstance(provider_preferences.get("allow_fallbacks"), bool)
                    else None
                ),
                "max_completion_tokens": completion_cap,
            }
        )

    return {
        "active_profile": active_profile,
        "profile_name": profile_name,
        "argument_profile": argument_profile_name,
        "configured_provider": configured_provider,
        "task_tier": task_tier,
        "model_tier": model_tier if model_tier in ("simple", "complex") else None,
        "profile_models": model_options[:2],
    }


def _message_content_size(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, (list, tuple)):
        return {
            "message_count": None,
            "message_count_truncated": False,
            "content_characters": None,
            "content_characters_truncated": False,
            "estimated_tokens": None,
        }
    actual_count = len(messages)
    message_count = min(actual_count, MAX_INITIAL_REQUEST_MESSAGES)
    total_characters = 0
    content_truncated = actual_count > MAX_INITIAL_REQUEST_MESSAGES
    visited_parts = 0
    for message in messages[:message_count]:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        content_values: list[str] = []
        if isinstance(content, str):
            content_values.append(content)
        elif isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str):
                content_values.append(text)
        elif isinstance(content, (list, tuple)):
            for part in content[:MAX_INITIAL_REQUEST_CONTENT_PARTS]:
                visited_parts += 1
                if visited_parts > MAX_INITIAL_REQUEST_CONTENT_PARTS:
                    content_truncated = True
                    break
                if isinstance(part, str):
                    content_values.append(part)
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    content_values.append(part["text"])
            if len(content) > MAX_INITIAL_REQUEST_CONTENT_PARTS:
                content_truncated = True
        for text in content_values:
            remaining = MAX_INITIAL_REQUEST_CONTENT_CHARS - total_characters
            if len(text) > remaining:
                total_characters = MAX_INITIAL_REQUEST_CONTENT_CHARS
                content_truncated = True
                break
            total_characters += len(text)
        if total_characters >= MAX_INITIAL_REQUEST_CONTENT_CHARS:
            content_truncated = True
            break
    return {
        "message_count": message_count,
        "message_count_truncated": actual_count > MAX_INITIAL_REQUEST_MESSAGES,
        "content_characters": total_characters,
        "content_characters_truncated": content_truncated,
        "estimated_tokens": (total_characters + 3) // 4,
    }


def _initial_narration_request(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    capture_site: str,
    model_config: Any,
) -> Optional[dict[str, Any]]:
    if capture_site == "get_ai_response":
        task_name = _safe_model_label(kwargs.get("task")) or "dm_main"
        messages = kwargs.get("conversation_history")
        if messages is None and args:
            messages = args[0]
    else:
        task_value = kwargs.get("task")
        if task_value is None and args:
            task_value = args[0]
        task_name = _safe_model_label(task_value)
        if task_name != "dm_main":
            return None
        messages = kwargs.get("messages")
        if messages is None and len(args) > 1:
            messages = args[1]
    if task_name != "dm_main":
        return None

    model_tier = kwargs.get("model_tier")
    profile_value = kwargs.get(
        "profile", kwargs.get("profile_name", kwargs.get("model_profile"))
    )
    return {
        "capture_site": capture_site,
        "task": task_name,
        **_message_content_size(messages),
        **_profile_request_labels(
            model_config,
            task_name,
            model_tier if isinstance(model_tier, str) else None,
            profile_value,
        ),
    }


def _safe_initial_narration_request(value: Any) -> Optional[dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    capture_site = value.get("capture_site")
    if capture_site not in ("get_ai_response", "llm_router"):
        capture_site = None
    model_count_fields = (
        "message_count",
        "content_characters",
        "estimated_tokens",
    )
    safe: dict[str, Any] = {
        "capture_site": capture_site,
        "task": "dm_main" if value.get("task") == "dm_main" else None,
        "message_count_truncated": bool(value.get("message_count_truncated")),
        "content_characters_truncated": bool(
            value.get("content_characters_truncated")
        ),
        "active_profile": _safe_model_label(value.get("active_profile")),
        "profile_name": _safe_model_label(value.get("profile_name")),
        "argument_profile": _safe_model_label(value.get("argument_profile")),
        "configured_provider": value.get("configured_provider")
        if value.get("configured_provider") in ("openrouter", "openai")
        else None,
        "task_tier": value.get("task_tier")
        if value.get("task_tier") in ("low", "medium", "high", "xhigh", "max")
        else None,
        "model_tier": value.get("model_tier")
        if value.get("model_tier") in ("simple", "complex")
        else None,
    }
    count_limits = {
        "message_count": MAX_INITIAL_REQUEST_MESSAGES,
        "content_characters": MAX_INITIAL_REQUEST_CONTENT_CHARS,
        "estimated_tokens": (MAX_INITIAL_REQUEST_CONTENT_CHARS + 3) // 4,
    }
    for key in model_count_fields:
        count = value.get(key)
        safe[key] = (
            min(count, count_limits[key])
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0
            else None
        )
    options = value.get("profile_models")
    safe_options: list[dict[str, Any]] = []
    if isinstance(options, (list, tuple)):
        for option in options[:2]:
            if not isinstance(option, dict):
                continue
            tier = option.get("tier")
            model_id = _safe_model_label(option.get("model_id"))
            if tier not in ("simple", "complex") or model_id is None:
                continue
            safe_options.append(
                {
                    "tier": tier,
                    "model_id": model_id,
                    "price_per_1k": _safe_price_per_1k(
                        option.get("price_per_1k")
                    ),
                    "provider_allow_fallbacks": (
                        option.get("provider_allow_fallbacks")
                        if isinstance(option.get("provider_allow_fallbacks"), bool)
                        else None
                    ),
                    "max_completion_tokens": (
                        option.get("max_completion_tokens")
                        if isinstance(option.get("max_completion_tokens"), int)
                        and not isinstance(option.get("max_completion_tokens"), bool)
                        and 1 <= option.get("max_completion_tokens") <= 1_000_000
                        else None
                    ),
                }
            )
    safe["profile_models"] = safe_options
    return safe


def _route_pin_from_request(
    request: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not isinstance(request, dict) or request.get("task") != "dm_main":
        return None
    options = request.get("profile_models")
    if not isinstance(options, list) or not options:
        return None
    model_ids = sorted(
        {
            option["model_id"]
            for option in options
            if isinstance(option, dict) and isinstance(option.get("model_id"), str)
        }
    )
    if not model_ids:
        return None
    caps = [
        option.get("max_completion_tokens")
        for option in options
        if isinstance(option, dict)
    ]
    valid_caps = [cap for cap in caps if isinstance(cap, int) and not isinstance(cap, bool)]
    fallback_values = [
        option.get("provider_allow_fallbacks")
        for option in options
        if isinstance(option, dict)
    ]
    fallback_setting = (
        fallback_values[0]
        if fallback_values and all(value is fallback_values[0] for value in fallback_values)
        else None
    )
    priced = all(
        isinstance(option, dict)
        and isinstance(option.get("price_per_1k"), dict)
        and all(
            isinstance(option["price_per_1k"].get(key), (int, float))
            for key in ("prompt", "completion")
        )
        for option in options
    )
    historical_rates = all(
        isinstance(option, dict)
        and isinstance(option.get("price_per_1k"), dict)
        and option["price_per_1k"].get("prompt") == N3_LUNA_PROMPT_USD_PER_1K
        and option["price_per_1k"].get("completion")
        == N3_LUNA_COMPLETION_USD_PER_1K
        for option in options
    )
    profile_name = request.get("profile_name")
    model_id = model_ids[0] if len(model_ids) == 1 else None
    n3_luna = bool(
        profile_name == N3_LUNA_PROFILE
        and model_id == N3_LUNA_MODEL
        and request.get("configured_provider") == "openrouter"
        and fallback_setting is False
        and valid_caps
        and max(valid_caps) == N3_LUNA_MAX_COMPLETION_TOKENS
        and priced
        and historical_rates
    )
    return {
        "task": "dm_main",
        "provider": request.get("configured_provider"),
        "profile": profile_name,
        "model_tier": request.get("model_tier"),
        "model_id": model_id,
        "model_ids": model_ids[:2],
        "allow_fallbacks": fallback_setting,
        "max_completion_tokens": max(valid_caps) if valid_caps else None,
        "priced": priced,
        "historical_rates": historical_rates,
        "n3_luna": n3_luna,
    }


def _estimate_cost_usd_upper_bound(
    request: Optional[dict[str, Any]],
) -> Optional[float]:
    safe_request = _safe_initial_narration_request(request)
    if safe_request is None:
        return None
    if (
        safe_request.get("message_count_truncated")
        or safe_request.get("content_characters_truncated")
    ):
        return None
    input_tokens = safe_request.get("estimated_tokens")
    options = safe_request.get("profile_models")
    if (
        not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or not isinstance(options, list)
        or not options
    ):
        return None
    estimates: list[Decimal] = []
    for option in options:
        if not isinstance(option, dict):
            return None
        rates = option.get("price_per_1k")
        completion_cap = option.get("max_completion_tokens")
        if (
            not isinstance(rates, dict)
            or not isinstance(completion_cap, int)
            or isinstance(completion_cap, bool)
            or not all(
                isinstance(rates.get(key), (int, float))
                and not isinstance(rates.get(key), bool)
                for key in ("prompt", "completion")
            )
        ):
            return None
        try:
            prompt_cost = (
                Decimal(input_tokens)
                * Decimal(str(rates["prompt"]))
                / Decimal(1000)
            )
            completion_cost = (
                Decimal(completion_cap)
                * Decimal(str(rates["completion"]))
                / Decimal(1000)
            )
        except (InvalidOperation, ValueError):
            return None
        estimates.append(prompt_cost + completion_cost)
    return round(float(max(estimates)), 8) if estimates else None


def _cost_estimate_assumptions(
    route_pin: Optional[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "rate_source": N3_LUNA_RATE_SOURCE,
        "rate_classification": "historical_estimate_not_live_quote",
        "prompt_usd_per_1k_tokens": N3_LUNA_PROMPT_USD_PER_1K,
        "completion_usd_per_1k_tokens": N3_LUNA_COMPLETION_USD_PER_1K,
        "input_token_estimator": (
            "ceil(content_characters / 4); not a tokenizer or guaranteed upper bound"
        ),
        "completion_token_cap": (
            route_pin.get("max_completion_tokens") if route_pin else None
        ),
        "completion_token_cap_source": "sandbox profile params.max_tokens",
        "cache_discount_applied": False,
        "per_run_cost_cap_usd": N3_RUN_COST_CAP_USD,
        "cumulative_n3_narration_spend_cap_usd": N3_CUMULATIVE_COST_CAP_USD,
        "actual_cost_source": "provider receipt",
        "application_fallback_policy": (
            "ENABLE_PROVIDER_FALLBACK is unchanged; fallback costs are not estimated"
        ),
        "offline_proof_makes_provider_calls": False,
    }


def _expected_startup_narration_intercept(
    request: Optional[dict[str, Any]], router_calls: int, provider_calls: int
) -> bool:
    return bool(
        isinstance(request, dict)
        and request.get("task") == "dm_main"
        and request.get("capture_site") in ("get_ai_response", "llm_router")
        and router_calls + provider_calls == 1
        and (router_calls, provider_calls) in ((1, 0), (0, 1))
    )


class EgressGuard:
    """Deny non-loopback operations before transport using ordinary socket errors."""

    def __init__(self, *, deny_loopback: bool = False) -> None:
        self._lock = threading.Lock()
        self._deny_loopback = deny_loopback
        self._attempts: list[dict[str, Any]] = []
        self._attempt_count = 0
        self._refusals: list[dict[str, Any]] = []
        self._refusal_count = 0
        self._sandbox_root: Optional[Path] = None
        self._attributions: dict[
            tuple[tuple[str, ...], tuple[str, ...], str], dict[str, Any]
        ] = {}
        self._originals: dict[tuple[Any, str], Any] = {}
        self._wrappers: dict[tuple[Any, str], Any] = {}
        self._socket_class: Any = None
        self._active = False

    def set_sandbox_root(self, sandbox_root: Path) -> None:
        self._sandbox_root = sandbox_root

    def _record_attribution(
        self, host: Any, thread_class: Optional[str] = None
    ) -> None:
        project_frames, library_packages = _collect_egress_origin(
            traceback.extract_stack(limit=MAX_EGRESS_STACK_FRAMES),
            self._sandbox_root,
        )
        hostname = _hostname_class(host)
        if thread_class not in ("main", "background", "other"):
            thread_class = _thread_name_class()
        key = (tuple(project_frames), tuple(library_packages), hostname)
        with self._lock:
            attribution = self._attributions.get(key)
            if attribution is None:
                if len(self._attributions) >= MAX_RECORDED_EGRESS:
                    return
                attribution = {
                    "origin": {
                        "project_frames": list(project_frames),
                        "library_packages": list(library_packages),
                    },
                    "hostname_class": hostname,
                    "thread_classes": [],
                    "count": 0,
                }
                self._attributions[key] = attribution
            if thread_class not in attribution["thread_classes"]:
                attribution["thread_classes"].append(thread_class)
                attribution["thread_classes"].sort()
            attribution["count"] = min(attribution["count"] + 1, MAX_COUNTER)

    def _record_refusal(
        self, host: Any, port: Any, caller_frame: Any
    ) -> str:
        """Retain one safe destination and source record for each refusal."""
        safe_hostname = _safe_refusal_hostname(host) or "unavailable"
        safe_port: Any = _safe_port(port)
        if safe_port is None:
            safe_port = "unavailable"
        try:
            thread_id: Any = threading.get_ident()
            if (
                isinstance(thread_id, bool)
                or not isinstance(thread_id, int)
                or not 0 < thread_id <= (1 << 64) - 1
            ):
                thread_id = "unavailable"
        except BaseException:
            thread_id = "unavailable"
        try:
            thread_class: Any = _thread_name_class()
            if thread_class not in ("main", "background", "other"):
                thread_class = "unavailable"
        except BaseException:
            thread_class = "unavailable"
        try:
            call_site: Any = _project_relative_call_site(
                caller_frame, self._sandbox_root or REPO_ROOT
            )
            if call_site == "unknown:0":
                call_site = "unavailable"
        except BaseException:
            call_site = "unavailable"
        event = {
            "hostname": safe_hostname,
            "port": safe_port,
            "thread_id": thread_id,
            "thread_class": thread_class,
            "call_site": call_site,
        }
        with self._lock:
            self._refusal_count = min(self._refusal_count + 1, MAX_COUNTER)
            if len(self._refusals) < MAX_RECORDED_EGRESS:
                event["sequence"] = self._refusal_count
                self._refusals.append(event)
        return (
            thread_class
            if thread_class in ("main", "background", "other")
            else "other"
        )

    def _record(self, host: Any, port: Any, record_loopback: bool) -> str:
        safe_hostname = _safe_refusal_hostname(host)
        safe_port = _safe_port(port)
        port_unavailable = port is None or safe_port is None
        host_class = (
            _host_class(host)
            if safe_hostname is not None and not port_unavailable
            else "non_loopback"
        )
        refused = host_class == "non_loopback" or (
            host_class == "loopback" and self._deny_loopback
        )
        if (
            host_class == "non_loopback"
            or record_loopback
            or self._deny_loopback
        ):
            entry = {"host_class": host_class, "port": safe_port}
            with self._lock:
                self._attempt_count = min(self._attempt_count + 1, MAX_COUNTER)
                if len(self._attempts) < MAX_RECORDED_EGRESS:
                    self._attempts.append(entry)
        if refused:
            thread_class = self._record_refusal(
                safe_hostname, port, sys._getframe(1)
            )
            try:
                self._record_attribution(host, thread_class)
            except BaseException:
                # Refusal must never depend on successful diagnostic attribution.
                pass
        if host_class == "loopback" and self._deny_loopback:
            raise EgressBlocked("network destination refused")
        return host_class

    def _connect(self, sock: Any, address: Any, method_name: str) -> Any:
        original = self._originals[(socket.socket, method_name)]
        if getattr(sock, "family", None) == getattr(socket, "AF_UNIX", object()):
            if self._deny_loopback:
                self._record(None, None, record_loopback=True)
                raise EgressBlocked("unix socket destination refused")
            return original(sock, address)
        host, port = _address_parts(address)
        host_class = self._record(host, port, record_loopback=True)
        if host_class == "non_loopback":
            raise _connection_refused_error()
        return original(sock, address)

    def _send(
        self,
        sock: Any,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        original = self._originals[(socket.socket, method_name)]
        family = getattr(sock, "family", None)
        if self._deny_loopback:
            self._record(None, None, record_loopback=True)
            raise EgressBlocked("socket send destination refused")
        elif method_name in ("sendto", "sendmsg"):
            address = kwargs.get("address")
            if address is None and method_name == "sendto" and len(args) > 1:
                address = args[-1]
            elif address is None and method_name == "sendmsg" and len(args) > 3:
                address = args[3]
            if address is not None and family != getattr(socket, "AF_UNIX", object()):
                host, port = _address_parts(address)
                host_class = self._record(host, port, record_loopback=False)
                if host_class == "non_loopback":
                    raise _connection_refused_error()
        return original(sock, *args, **kwargs)

    def _bind(self, sock: Any, address: Any, method_name: str) -> Any:
        original = self._originals[(socket.socket, method_name)]
        if self._deny_loopback:
            host, port = _address_parts(address)
            try:
                host_class = self._record(host, port, record_loopback=True)
            except EgressBlocked:
                if _is_ipv6_loopback_ephemeral_bind(sock, address):
                    raise PermissionError(
                        errno.EPERM, "socket bind destination refused"
                    ) from None
                raise
            if host_class == "non_loopback":
                raise EgressBlocked("socket bind destination refused")
        return original(sock, address)

    def _listen(self, sock: Any, backlog: Any) -> Any:
        original = self._originals[(socket.socket, "listen")]
        if self._deny_loopback:
            self._record(None, None, record_loopback=True)
            raise EgressBlocked("socket listener refused")
        return original(sock, backlog)

    def _create_connection(self, address: Any, *args: Any, **kwargs: Any) -> Any:
        original = self._originals[(socket, "create_connection")]
        host, port = _address_parts(address)
        host_class = self._record(host, port, record_loopback=True)
        if host_class == "non_loopback":
            raise _connection_refused_error()
        return original(address, *args, **kwargs)

    def _record_name_lookup(self, host: Any, port: Any) -> None:
        try:
            host_class = self._record(host, port, record_loopback=False)
        except EgressBlocked:
            raise _name_resolution_refused_error() from None
        if host_class == "non_loopback":
            raise _name_resolution_refused_error()

    def _getaddrinfo(
        self, host: Any, port: Any, *args: Any, **kwargs: Any
    ) -> Any:
        original = self._originals[(socket, "getaddrinfo")]
        self._record_name_lookup(host, port)
        return original(host, port, *args, **kwargs)

    def _resolve_name(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        original = self._originals[(socket, method_name)]
        host = args[0] if args else kwargs.get("host", kwargs.get("hostname"))
        self._record_name_lookup(host, None)
        return original(*args, **kwargs)

    def _getnameinfo(self, address: Any, *args: Any, **kwargs: Any) -> Any:
        original = self._originals[(socket, "getnameinfo")]
        host, port = _address_parts(address)
        self._record_name_lookup(host, port)
        return original(address, *args, **kwargs)

    def install(self) -> "EgressGuard":
        if self._active:
            return self
        self._socket_class = socket.socket
        targets = (
            (self._socket_class, "connect"),
            (self._socket_class, "connect_ex"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
        ) + tuple(
            (socket, name)
            for name in (
                "gethostbyname",
                "gethostbyname_ex",
                "gethostbyaddr",
                "getfqdn",
                "getnameinfo",
            )
            if callable(getattr(socket, name, None))
        )
        if self._deny_loopback:
            targets += tuple(
                (self._socket_class, name)
                for name in (
                    "send",
                    "sendall",
                    "sendto",
                    "sendmsg",
                    "sendfile",
                    "bind",
                    "listen",
                )
                if callable(getattr(self._socket_class, name, None))
            )
        for owner, name in targets:
            original = getattr(owner, name)
            self._originals[(owner, name)] = original

            if owner is socket.socket:
                if name in ("connect", "connect_ex"):
                    def wrapper(*args: Any, _name: str = name, **kwargs: Any) -> Any:
                        return self._connect(*args, _name, **kwargs)
                elif name == "bind":
                    def wrapper(*args: Any, _name: str = name, **kwargs: Any) -> Any:
                        if len(args) < 2:
                            raise EgressBlocked("socket bind destination refused")
                        return self._bind(args[0], args[1], _name)
                elif name == "listen":
                    def wrapper(*args: Any, **kwargs: Any) -> Any:
                        if not args:
                            raise EgressBlocked("socket listener refused")
                        backlog = args[1] if len(args) > 1 else kwargs.get("backlog", 0)
                        return self._listen(args[0], backlog)
                else:
                    def wrapper(*args: Any, _name: str = name, **kwargs: Any) -> Any:
                        if not args:
                            raise EgressBlocked("socket send destination refused")
                        return self._send(args[0], _name, *args[1:], **kwargs)
            elif name == "create_connection":
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return self._create_connection(*args, **kwargs)
            elif name == "getnameinfo":
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    if not args:
                        raise EgressBlocked("socket name resolution refused")
                    return self._getnameinfo(args[0], *args[1:], **kwargs)
            elif name in (
                "gethostbyname",
                "gethostbyname_ex",
                "gethostbyaddr",
                "getfqdn",
            ):
                def wrapper(*args: Any, _name: str = name, **kwargs: Any) -> Any:
                    return self._resolve_name(_name, *args, **kwargs)
            else:
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return self._getaddrinfo(*args, **kwargs)

            self._wrappers[(owner, name)] = wrapper
            setattr(owner, name, wrapper)
        self._active = True
        return self

    def is_active(self) -> bool:
        return (
            self._active
            and socket.socket is self._socket_class
            and all(
                getattr(owner, name) is wrapper
                for (owner, name), wrapper in self._wrappers.items()
            )
        )

    def assert_active(self) -> None:
        if not self.is_active():
            raise ProofSetupError("socket egress guard was replaced")

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._attempts]

    def attribution_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            result = [
                {
                    "origin": {
                        "project_frames": list(value["origin"]["project_frames"]),
                        "library_packages": list(
                            value["origin"]["library_packages"]
                        ),
                    },
                    "hostname_class": value["hostname_class"],
                    "thread_classes": list(value["thread_classes"]),
                    "count": value["count"],
                }
                for value in self._attributions.values()
            ]
        result.sort(
            key=lambda item: (
                item["hostname_class"],
                tuple(item["origin"]["project_frames"]),
                tuple(item["origin"]["library_packages"]),
            )
        )
        return result

    def refusal_snapshot(self) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            return [dict(item) for item in self._refusals], self._refusal_count

    def attempt_count(self) -> int:
        with self._lock:
            return self._attempt_count

    def restore(self) -> None:
        for (owner, name), original in reversed(tuple(self._originals.items())):
            wrapper = self._wrappers[(owner, name)]
            if getattr(owner, name, None) is wrapper:
                setattr(owner, name, original)
        self._active = False

    def __enter__(self) -> "EgressGuard":
        return self.install()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        del exc_type, exc, tb
        self.restore()


class AttributePatches:
    """Restore only the exact attributes patched by this proof run."""

    def __init__(self) -> None:
        self._originals: list[tuple[Any, str, Any]] = []
        self._installed: list[tuple[Any, str, Any]] = []

    def set(self, owner: Any, name: str, value: Any) -> None:
        if not hasattr(owner, name):
            raise ProofSetupError("required provider tripwire target is unavailable")
        self._originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)
        self._installed.append((owner, name, value))

    def assert_active(self) -> None:
        if any(getattr(owner, name, None) is not value for owner, name, value in self._installed):
            raise ProofSetupError("provider entry-point tripwire was replaced")

    def targets_active(self, targets: Any) -> bool:
        """Check exact guard targets without coupling unrelated patches."""
        requested = tuple(targets)
        if not requested:
            return False
        installed = {
            (id(owner), name): value
            for owner, name, value in self._installed
        }
        return all(
            (id(owner), name) in installed
            and getattr(owner, name, None) is installed[(id(owner), name)]
            for owner, name in requested
        )

    def restore(self) -> None:
        for owner, name, original in reversed(self._originals):
            setattr(owner, name, original)
        self._originals.clear()
        self._installed.clear()


def run_guard_self_test() -> dict[str, Any]:
    """Prove both fail-closed tripwires without importing the host application."""
    recorder = ProviderCallRecorder()
    guard = EgressGuard()
    patches = AttributePatches()
    provider_detected = False
    update_check_detected = False
    egress_detected = False
    with guard:
        guard.assert_active()

        class FakeProvider:
            def call(self, *args: Any, **kwargs: Any) -> None:
                del args, kwargs

        fake_provider = FakeProvider()

        def fake_call(*args: Any, **kwargs: Any) -> None:
            recorder.block_provider_function(*args, **kwargs)

        patches.set(fake_provider, "call", fake_call)
        try:
            fake_provider.call("fake-task", [])
        except ProviderCallBlocked:
            provider_detected = True

        class FakeVersionChecker:
            def get_latest_remote_version(self, *args: Any, **kwargs: Any) -> Optional[str]:
                del args, kwargs
                return "not-stubbed"

        fake_version_checker = FakeVersionChecker()

        def update_check_stub(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            recorder.record_update_check()
            return None

        patches.set(
            fake_version_checker,
            "get_latest_remote_version",
            update_check_stub,
        )
        update_check_detected = (
            fake_version_checker.get_latest_remote_version("owner/repo", "main")
            is None
        )

        class FakeSocket:
            family = socket.AF_INET

        try:
            socket.socket.connect(FakeSocket(), ("203.0.113.19", 443))
        except ConnectionRefusedError:
            egress_detected = True
        finally:
            patches.restore()

    router_count, provider_count, update_check_count = recorder.snapshot()
    attempt_list = guard.snapshot()
    passed = (
        provider_detected
        and update_check_detected
        and egress_detected
        and router_count == 0
        and provider_count == 1
        and update_check_count == 1
        and attempt_list == [{"host_class": "non_loopback", "port": 443}]
    )
    return {
        "verdict": "PASS" if passed else "FAIL",
        "provider_stub_detected": provider_detected,
        "update_check_stub_detected": update_check_detected,
        "non_version_egress_detected": egress_detected,
        "egress_guard_detected": egress_detected,
    }


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run ID is invalid")
    return run_id


def _absolute_lexical_path(value: str | Path, base: Path) -> Path:
    path = Path(value)
    if any(part == ".." for part in path.parts):
        raise ValueError("path traversal is not allowed")
    return path if path.is_absolute() else base / path


def _reject_symlink_components(path: Path, approved_root: Path) -> None:
    try:
        relative = path.relative_to(approved_root)
    except ValueError as exc:
        raise ValueError("path is outside the approved root") from exc
    current = approved_root
    if current.is_symlink():
        raise ValueError("approved path root is a symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("path contains a symlink")


def validate_sandbox_root(
    sandbox_root: str | Path = DEFAULT_SANDBOX,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Require a real directory below this repository's tmp directory."""
    repo = repo_root.resolve(strict=True)
    tmp_root = repo / "tmp"
    if not tmp_root.is_dir() or tmp_root.is_symlink():
        raise ValueError("repository tmp directory is unavailable")
    candidate = _absolute_lexical_path(sandbox_root, repo)
    if candidate.is_symlink():
        raise ValueError("sandbox root must not be a symlink")
    _reject_symlink_components(candidate, tmp_root)
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("sandbox root must be an existing directory")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(tmp_root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("sandbox root must be below repository tmp") from exc
    return resolved


def resolve_output_file(
    output_dir: Optional[str | Path], run_id: str, repo_root: Path = REPO_ROOT
) -> Path:
    """Resolve a report file under repository tmp; the default is proof.json."""
    safe_run_id = validate_run_id(run_id)
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
    candidate = _absolute_lexical_path(supplied, repo)
    _reject_symlink_components(candidate, tmp_root)
    try:
        candidate.resolve(strict=False).relative_to(tmp_root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("proof output must be below repository tmp") from exc
    return candidate


def resolve_preintegrate_output_file(
    output_dir: Optional[str | Path],
    run_id: str,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Resolve preintegrate.json alongside proof.json under repository tmp."""
    safe_run_id = validate_run_id(run_id)
    repo = repo_root.resolve(strict=True)
    tmp_root = repo / "tmp"
    if not tmp_root.is_dir() or tmp_root.is_symlink():
        raise ValueError("repository tmp directory is unavailable")
    if output_dir is None:
        supplied = DEFAULT_OUTPUT_PARENT / safe_run_id / "preintegrate.json"
    else:
        requested = Path(output_dir)
        directory = requested.parent if requested.suffix.lower() == ".json" else requested
        supplied = directory / "preintegrate.json"
    candidate = _absolute_lexical_path(supplied, repo)
    _reject_symlink_components(candidate, tmp_root)
    try:
        candidate.resolve(strict=False).relative_to(tmp_root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("preintegrate output must be below repository tmp") from exc
    return candidate


def resolve_startup_diagnostic_output_file(
    output_dir: Optional[str | Path],
    run_id: str,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Resolve the private startup trace report under repository tmp."""
    safe_run_id = validate_run_id(run_id)
    repo = repo_root.resolve(strict=True)
    tmp_root = repo / "tmp"
    if not tmp_root.is_dir() or tmp_root.is_symlink():
        raise ValueError("repository tmp directory is unavailable")
    if output_dir is None:
        supplied = DEFAULT_OUTPUT_PARENT / safe_run_id / "startup-diagnostic.json"
    else:
        requested = Path(output_dir)
        supplied = (
            requested
            if requested.suffix.lower() == ".json"
            else requested / "startup-diagnostic.json"
        )
    candidate = _absolute_lexical_path(supplied, repo)
    _reject_symlink_components(candidate, tmp_root)
    try:
        candidate.resolve(strict=False).relative_to(tmp_root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("startup diagnostic output must be below repository tmp") from exc
    return candidate


def count_conversation_history(sandbox_root: Path) -> tuple[int, int]:
    """Count JSON message rows without returning or logging conversation text."""
    modules_dir = sandbox_root / "modules"
    history_dir = sandbox_root / "modules" / "conversation_history"
    if modules_dir.is_symlink():
        raise ProofSetupError("conversation history parent directory is unsafe")
    if history_dir.is_symlink():
        raise ProofSetupError("conversation history directory is unsafe")
    if not history_dir.exists():
        return 0, 0
    if history_dir.is_symlink() or not history_dir.is_dir():
        raise ProofSetupError("conversation history directory is unsafe")
    try:
        history_dir.resolve(strict=True).relative_to(sandbox_root)
    except (OSError, ValueError) as exc:
        raise ProofSetupError("conversation history directory escapes the sandbox") from exc
    files = sorted(history_dir.glob("*.json"))
    if len(files) > MAX_HISTORY_FILES:
        raise ProofSetupError("conversation history file bound exceeded")
    total_bytes = 0
    message_count = 0
    user_count = 0
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ProofSetupError("conversation history file is unsafe")
        total_bytes += path.stat().st_size
        if total_bytes > MAX_HISTORY_BYTES:
            raise ProofSetupError("conversation history size bound exceeded")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        messages: Any = payload if isinstance(payload, list) else None
        if isinstance(payload, dict):
            for key in ("conversation_history", "messages", "history"):
                value = payload.get(key)
                if isinstance(value, list):
                    messages = value
                    break
        if not isinstance(messages, list):
            continue
        message_count += len(messages)
        user_count += sum(
            isinstance(message, dict) and message.get("role") == "user"
            for message in messages
        )
    if message_count > MAX_COUNTER or user_count > MAX_COUNTER:
        raise ProofSetupError("conversation history count bound exceeded")
    return message_count, user_count


def _static_seed_failure() -> dict[str, bool]:
    return {
        "registry_has_no_unregistered_modules": False,
        "no_active_combat": False,
        "no_history_user_messages": False,
        "provider_free_startup_seed": False,
    }


def _checked_lstat(root: Path, path: Path) -> Optional[os.stat_result]:
    """Inspect a sandbox path without following any in-sandbox symlink."""
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ProofSetupError("seed input escaped the sandbox") from exc
    if root.is_symlink() or not root.is_dir():
        raise ProofSetupError("sandbox root is unsafe")
    current = root
    info: Optional[os.stat_result] = None
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise ProofSetupError("seed input contains a symlink")
    return info


def _read_static_json(
    root: Path,
    path: Path,
    max_file_bytes: int,
    total_bytes: list[int],
) -> Any:
    info = _checked_lstat(root, path)
    if info is None or not stat.S_ISREG(info.st_mode):
        raise ProofSetupError("required seed JSON file is unavailable")
    if info.st_size > max_file_bytes:
        raise ProofSetupError("seed JSON file size bound exceeded")
    try:
        with open(path, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
            ):
                raise ProofSetupError("seed JSON file changed during inspection")
            raw = stream.read(max_file_bytes + 1)
    except OSError as exc:
        raise ProofSetupError("seed JSON file could not be read") from exc
    if len(raw) > max_file_bytes:
        raise ProofSetupError("seed JSON file size bound exceeded")
    total_bytes[0] += len(raw)
    if total_bytes[0] > MAX_STATIC_TOTAL_BYTES:
        raise ProofSetupError("seed JSON total size bound exceeded")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofSetupError("seed JSON is malformed") from exc


def _is_skipped_area_filename(filename: str) -> bool:
    return (
        filename.startswith("module_")
        or filename.startswith("party_")
        or filename.startswith("campaign_")
        or filename.startswith("map_")
        or filename.startswith("plot_")
        or filename.endswith("_BU.json")
    )


def _inspect_capture_seed(
    sandbox_root: Path, *, allow_missing_registry: bool = False
) -> dict[str, Any]:
    """Read bounded canonical seed inputs and mirror ModuleStitcher discovery."""
    root = validate_sandbox_root(sandbox_root)
    if root.is_symlink() or not root.is_dir():
        raise ProofSetupError("sandbox root is unsafe")
    total_bytes = [0]
    modules_dir = root / "modules"
    modules_info = _checked_lstat(root, modules_dir)
    if modules_info is None or not stat.S_ISDIR(modules_info.st_mode):
        raise ProofSetupError("modules directory is unavailable")

    registry_path = modules_dir / "world_registry.json"
    registry_info = _checked_lstat(root, registry_path)
    if registry_info is None:
        if not allow_missing_registry:
            raise ProofSetupError("world registry is unavailable after integration")
        registry = {"modules": []}
    else:
        registry = _read_static_json(
            root,
            registry_path,
            MAX_STATIC_JSON_BYTES,
            total_bytes,
        )
    if not isinstance(registry, dict) or "modules" not in registry:
        raise ProofSetupError("world registry shape is malformed")
    registered_value = registry.get("modules")
    if isinstance(registered_value, dict):
        registered_modules = list(registered_value.keys())
    elif isinstance(registered_value, list):
        registered_modules = list(registered_value)
    else:
        raise ProofSetupError("world registry module list is malformed")
    if len(registered_modules) > MAX_STATIC_MODULES or any(
        not isinstance(name, str) for name in registered_modules
    ):
        raise ProofSetupError("world registry module count or names are invalid")
    registered_set = set(registered_modules)

    party_tracker = _read_static_json(
        root,
        root / "party_tracker.json",
        MAX_STATIC_JSON_BYTES,
        total_bytes,
    )
    if not isinstance(party_tracker, dict):
        raise ProofSetupError("party tracker shape is malformed")
    world_conditions = party_tracker.get("worldConditions", {})
    if not isinstance(world_conditions, dict):
        raise ProofSetupError("party tracker world conditions are malformed")
    active_combat_encounter = world_conditions.get("activeCombatEncounter")

    detected_modules: list[str] = []
    module_entries = sorted(modules_dir.iterdir(), key=lambda path: path.name)
    if len(module_entries) > MAX_STATIC_MODULES + 64:
        raise ProofSetupError("module directory entry bound exceeded")
    area_file_count = 0
    for module_path in module_entries:
        module_name = module_path.name
        if module_name.startswith(".") or module_name in (
            "campaign_archives",
            "campaign_summaries",
        ):
            continue
        module_info = _checked_lstat(root, module_path)
        if module_info is None:
            raise ProofSetupError("module directory changed during inspection")
        if not stat.S_ISDIR(module_info.st_mode):
            continue
        areas_path = module_path / "areas"
        areas_info = _checked_lstat(root, areas_path)
        if areas_info is None:
            continue
        if not stat.S_ISDIR(areas_info.st_mode):
            raise ProofSetupError("module areas path is malformed")
        area_entries = sorted(areas_path.iterdir(), key=lambda path: path.name)
        area_found = False
        for area_path in area_entries:
            filename = area_path.name
            if not filename.endswith(".json") or _is_skipped_area_filename(filename):
                continue
            area_file_count += 1
            if area_file_count > MAX_STATIC_AREA_FILES:
                raise ProofSetupError("module area file bound exceeded")
            area_payload = _read_static_json(
                root,
                area_path,
                MAX_STATIC_JSON_BYTES,
                total_bytes,
            )
            if (
                isinstance(area_payload, dict)
                and area_payload
                and "areaId" in area_payload
                and "areaName" in area_payload
                and "locations" in area_payload
            ):
                area_found = True
        if area_found and module_name not in registered_set:
            detected_modules.append(module_name)
            if len(detected_modules) > MAX_STATIC_MODULES:
                raise ProofSetupError("new module count bound exceeded")

    history_dir = modules_dir / "conversation_history"
    history_info = _checked_lstat(root, history_dir)
    user_messages = 0
    if history_info is not None:
        if not stat.S_ISDIR(history_info.st_mode):
            raise ProofSetupError("conversation history directory is malformed")
        history_files = sorted(history_dir.glob("*.json"))
        if len(history_files) > MAX_HISTORY_FILES:
            raise ProofSetupError("conversation history file bound exceeded")
        for history_path in history_files:
            payload = _read_static_json(
                root,
                history_path,
                MAX_STATIC_JSON_BYTES,
                total_bytes,
            )
            messages: Any = payload if isinstance(payload, list) else None
            if isinstance(payload, dict):
                for key in ("conversation_history", "messages", "history"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        messages = value
                        break
            if not isinstance(messages, list):
                raise ProofSetupError("conversation history shape is malformed")
            user_messages += sum(
                isinstance(message, dict) and message.get("role") == "user"
                for message in messages
            )
            if user_messages > MAX_COUNTER:
                raise ProofSetupError("conversation history count bound exceeded")

    checks = {
        "registry_has_no_unregistered_modules": not detected_modules,
        "no_active_combat": not bool(active_combat_encounter),
        "no_history_user_messages": user_messages == 0,
        "provider_free_startup_seed": (
            not detected_modules
            and not bool(active_combat_encounter)
            and user_messages == 0
        ),
    }
    return {
        "checks": checks,
        "registered_modules": registered_modules,
        "detect_new_modules_after": detected_modules,
        "active_combat_encounter_after": active_combat_encounter,
    }


def _normalize_registry_for_integration(
    sandbox_root: Path,
    registry_writer: Callable[[Any, str], Any],
) -> None:
    """Convert legacy list membership to the mapping the product mutates."""
    root = validate_sandbox_root(sandbox_root)
    registry_path = root / "modules" / "world_registry.json"
    if _checked_lstat(root, registry_path) is None:
        # The product's ModuleStitcher creates its default registry on scan.
        return
    registry = _read_static_json(
        root, registry_path, MAX_STATIC_JSON_BYTES, [0]
    )
    if not isinstance(registry, dict):
        raise ProofSetupError("world registry shape is malformed")
    modules = registry.get("modules")
    if isinstance(modules, dict):
        if len(modules) > MAX_STATIC_MODULES:
            raise ProofSetupError("world registry module count bound exceeded")
        return
    if not isinstance(modules, list) or any(
        not isinstance(name, str) for name in modules
    ):
        raise ProofSetupError("world registry module list is malformed")
    if len(modules) > MAX_STATIC_MODULES:
        raise ProofSetupError("world registry module count bound exceeded")
    registry["modules"] = {name: {} for name in modules}
    if registry_writer(registry, str(registry_path)) is False:
        raise ProofSetupError("world registry could not be normalized for integration")


def check_capture_seed_provider_free(sandbox_root: Path) -> dict[str, bool]:
    """Check a capture seed without importing host code or exposing its content."""
    try:
        return _inspect_capture_seed(
            Path(sandbox_root), allow_missing_registry=True
        )["checks"]
    except (OSError, ValueError, ProofSetupError):
        return _static_seed_failure()


def _bounded_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, MAX_COUNTER))


def _safe_egress_attributions(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, (list, tuple)):
        return []
    grouped: dict[
        tuple[tuple[str, ...], tuple[str, ...], str], dict[str, Any]
    ] = {}
    allowed_hostname_classes = {
        "github",
        "githubusercontent",
        "openrouter",
        "openai",
        "other",
    }
    allowed_thread_classes = {"main", "background", "other"}
    for item in values[:MAX_RECORDED_EGRESS]:
        if not isinstance(item, dict):
            continue
        origin = item.get("origin")
        if not isinstance(origin, dict):
            continue
        raw_frames = origin.get("project_frames")
        raw_libraries = origin.get("library_packages")
        if not isinstance(raw_frames, (list, tuple)) or not isinstance(
            raw_libraries, (list, tuple)
        ):
            continue
        safe_frames: list[str] = []
        for value in raw_frames[:MAX_EGRESS_ORIGIN_FRAMES]:
            if not isinstance(value, str) or ":" not in value:
                continue
            path, function = value.rsplit(":", 1)
            path_parts = Path(path).parts
            if (
                path.startswith("/")
                or ".." in path_parts
                or not SAFE_ORIGIN_PATH_PATTERN.fullmatch(path)
                or not SAFE_ORIGIN_FUNCTION_PATTERN.fullmatch(function)
            ):
                continue
            safe_frames.append(path + ":" + function)
        safe_libraries: list[str] = []
        for value in raw_libraries[:MAX_EGRESS_LIBRARY_PACKAGES]:
            if (
                isinstance(value, str)
                and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value)
                and value not in safe_libraries
            ):
                safe_libraries.append(value)
        hostname_class = item.get("hostname_class")
        if (
            not isinstance(hostname_class, str)
            or hostname_class not in allowed_hostname_classes
        ):
            continue
        raw_threads = item.get("thread_classes")
        safe_threads = sorted(
            {
                value
                for value in raw_threads
                if isinstance(value, str) and value in allowed_thread_classes
            }
        ) if isinstance(raw_threads, (list, tuple)) else []
        if not safe_threads:
            safe_threads = ["other"]
        count = _bounded_count(item.get("count"))
        if count == 0:
            continue
        key = (tuple(safe_frames), tuple(safe_libraries), hostname_class)
        attribution = grouped.get(key)
        if attribution is None:
            if len(grouped) >= MAX_RECORDED_EGRESS:
                continue
            attribution = {
                "origin": {
                    "project_frames": list(safe_frames),
                    "library_packages": list(safe_libraries),
                },
                "hostname_class": hostname_class,
                "thread_classes": [],
                "count": 0,
            }
            grouped[key] = attribution
        attribution["thread_classes"] = sorted(
            set(attribution["thread_classes"]) | set(safe_threads)
        )
        attribution["count"] = min(attribution["count"] + count, MAX_COUNTER)
    result = list(grouped.values())
    result.sort(
        key=lambda item: (
            item["hostname_class"],
            tuple(item["origin"]["project_frames"]),
            tuple(item["origin"]["library_packages"]),
        )
    )
    return result


def _safe_egress_refusals(
    values: Any,
) -> tuple[list[dict[str, Any]], bool]:
    """Sanitize per-refusal evidence and report whether every field is present."""
    if not isinstance(values, (list, tuple)):
        return [], False
    safe_events: list[dict[str, Any]] = []
    valid = len(values) <= MAX_RECORDED_EGRESS
    for index, value in enumerate(values[:MAX_RECORDED_EGRESS], start=1):
        event_valid = isinstance(value, dict)
        if not isinstance(value, dict):
            value = {}

        hostname = _safe_refusal_hostname(value.get("hostname"))
        if hostname is None:
            hostname = "unavailable"
            event_valid = False

        raw_port = value.get("port")
        port = _safe_port(raw_port)
        if port is None:
            port = "unavailable"
            event_valid = False

        thread_id = value.get("thread_id")
        if (
            isinstance(thread_id, bool)
            or not isinstance(thread_id, int)
            or not 0 < thread_id <= (1 << 64) - 1
        ):
            thread_id = "unavailable"
            event_valid = False

        thread_class = value.get("thread_class")
        if thread_class not in ("main", "background", "other"):
            thread_class = "unavailable"
            event_valid = False

        call_site = value.get("call_site")
        safe_call_site = "unavailable"
        if isinstance(call_site, str) and ":" in call_site:
            path, line_value = call_site.rsplit(":", 1)
            path_parts = Path(path).parts
            if (
                not path.startswith("/")
                and ".." not in path_parts
                and "\\" not in path
                and SAFE_ORIGIN_PATH_PATTERN.fullmatch(path)
                and path.endswith(".py")
                and line_value.isascii()
                and line_value.isdecimal()
                and 1 <= len(line_value) <= 7
                and 1 <= int(line_value) <= MAX_COUNTER
            ):
                safe_call_site = path + ":" + line_value
            else:
                event_valid = False
        else:
            event_valid = False

        sequence = value.get("sequence")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence != index
        ):
            sequence = index
            event_valid = False
        safe_events.append(
            {
                "hostname": hostname,
                "port": port,
                "thread_id": thread_id,
                "thread_class": thread_class,
                "call_site": safe_call_site,
                "sequence": sequence,
            }
        )
        valid = valid and event_valid
    return safe_events, valid


def _known_startup_egress_contacts(
    attributions: list[dict[str, Any]], enabled: bool
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    count = sum(
        _bounded_count(attribution.get("count"))
        for attribution in attributions
        if isinstance(attribution, dict)
        and attribution.get("hostname_class") == "other"
        and isinstance(attribution.get("origin"), dict)
        and KNOWN_EXCHANGE_RATE_ORIGIN
        in attribution["origin"].get("project_frames", [])
    )
    if not count:
        return []
    return [{"name": KNOWN_EXCHANGE_RATE_ORIGIN, "count": count}]


def _startup_egress_is_allowlisted(
    egress_attempts: list[dict[str, Any]],
    attributions: list[dict[str, Any]],
) -> bool:
    attributed_count = 0
    for attribution in attributions:
        if not isinstance(attribution, dict):
            return False
        origin = attribution.get("origin")
        frames = origin.get("project_frames") if isinstance(origin, dict) else None
        if (
            not isinstance(frames, list)
            or KNOWN_EXCHANGE_RATE_ORIGIN not in frames
            or attribution.get("hostname_class") != "other"
        ):
            return False
        count = attribution.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            return False
        attributed_count += count
    return attributed_count == len(egress_attempts)


def build_report(
    *,
    sandbox_path_class: str,
    conversation_history_message_count: int,
    conversation_history_user_message_count: int,
    game_thread_alive: bool,
    seconds_to_alive: Optional[float],
    router_calls: int,
    provider_function_calls: int,
    egress_attempts: list[dict[str, Any]],
    ledger_reservations: Optional[int],
    observed_events: dict[str, int],
    update_check_calls: int = 0,
    blocked_reason: Optional[str] = None,
    ledger_valid: bool = True,
    egress_attributions: Optional[list[dict[str, Any]]] = None,
    egress_refusals: Optional[list[dict[str, Any]]] = None,
    egress_refusal_count: Optional[int] = None,
    initial_narration_request: Optional[dict[str, Any]] = None,
    expect_startup_narration: bool = False,
    require_priced_route: bool = False,
) -> dict[str, Any]:
    safe_egress: list[dict[str, Any]] = []
    for attempt in egress_attempts[:MAX_RECORDED_EGRESS]:
        if not isinstance(attempt, dict):
            continue
        host_class = attempt.get("host_class")
        if host_class not in ("loopback", "non_loopback"):
            continue
        safe_egress.append(
            {"host_class": host_class, "port": _safe_port(attempt.get("port"))}
        )
    safe_events = {
        name: _bounded_count(observed_events.get(name, 0))
        for name in ("game_output", "status_update")
    }
    safe_egress_attributions = _safe_egress_attributions(
        egress_attributions or []
    )
    safe_egress_refusals, refusal_events_valid = _safe_egress_refusals(
        egress_refusals if egress_refusals is not None else []
    )
    non_loopback_attempt_count = sum(
        1
        for attempt in safe_egress
        if attempt["host_class"] == "non_loopback"
    )
    recorded_refusal_count = (
        _bounded_count(egress_refusal_count)
        if egress_refusal_count is not None
        else non_loopback_attempt_count
    )
    egress_attempts_valid = (
        isinstance(egress_attempts, (list, tuple))
        and len(safe_egress) == min(len(egress_attempts), MAX_RECORDED_EGRESS)
    )
    refusal_coverage_complete = bool(
        egress_attempts_valid
        and refusal_events_valid
        and recorded_refusal_count == non_loopback_attempt_count
        and len(safe_egress_refusals) == recorded_refusal_count
    )
    known_product_contacts = _known_startup_egress_contacts(
        safe_egress_attributions, expect_startup_narration
    )
    safe_initial_request = _safe_initial_narration_request(
        initial_narration_request
    )
    route_pin = _route_pin_from_request(safe_initial_request)
    estimated_cost = _estimate_cost_usd_upper_bound(
        initial_narration_request
    )
    startup_narration_intercepted = _expected_startup_narration_intercept(
        safe_initial_request, router_calls, provider_function_calls
    )
    report: dict[str, Any] = {
        "sandbox_path_class": "repository_tmp/combat_capture"
        if sandbox_path_class == "repository_tmp/combat_capture"
        else "repository_tmp/other",
        "conversation_history_message_count": _bounded_count(
            conversation_history_message_count
        ),
        "conversation_history_user_message_count": _bounded_count(
            conversation_history_user_message_count
        ),
        "game_thread_alive": bool(game_thread_alive),
        "seconds_to_alive": (
            round(seconds_to_alive, 3)
            if isinstance(seconds_to_alive, (int, float))
            and not isinstance(seconds_to_alive, bool)
            and 0 <= seconds_to_alive <= 300
            else None
        ),
        "router_calls": _bounded_count(router_calls),
        "provider_function_calls": _bounded_count(provider_function_calls),
        "egress_attempts": safe_egress,
        "egress_attributions": safe_egress_attributions,
        "egress_refusals": safe_egress_refusals,
        "egress_refusal_coverage_complete": refusal_coverage_complete,
        "known_product_contacts": known_product_contacts,
        "initial_narration_request": safe_initial_request,
        "route_pin": route_pin,
        "estimated_cost_usd_upper_bound": estimated_cost,
        "cost_estimate_assumptions": _cost_estimate_assumptions(route_pin),
        "startup_narration_expected": bool(expect_startup_narration),
        "startup_narration_intercepted": startup_narration_intercepted,
        "require_priced_route": bool(require_priced_route),
        "ledger_reservations": (
            _bounded_count(ledger_reservations)
            if ledger_reservations is not None
            else None
        ),
        "update_check_calls": _bounded_count(update_check_calls),
        "observed_events": safe_events,
        "notes": UPDATE_CHECK_NOTE
        + (
            " Startup narration is counted by an offline tripwire and is not sent to a provider."
            if expect_startup_narration and startup_narration_intercepted
            else ""
        ),
    }
    safe_blocked_reason = (
        _safe_blocked_reason(blocked_reason) if blocked_reason else None
    )
    if safe_blocked_reason is not None:
        report["blocked_reason"] = safe_blocked_reason

    failures: list[str] = []
    if not refusal_coverage_complete:
        failures.append("egress refusal attribution incomplete")
    if not report["game_thread_alive"]:
        failures.append("game thread was not observed alive")
    if expect_startup_narration:
        if safe_initial_request is None:
            failures.append("startup narration request was not observed")
        elif not startup_narration_intercepted:
            failures.append("startup narration was not intercepted exactly once")
    else:
        if report["router_calls"]:
            failures.append("router call detected")
        if report["provider_function_calls"]:
            failures.append("provider function call detected")
    if require_priced_route:
        if not route_pin or not route_pin.get("n3_luna"):
            failures.append("priced n3-luna dm_main route was not resolved")
        if estimated_cost is None:
            failures.append("priced route cost estimate is unavailable")
        elif estimated_cost > N3_RUN_COST_CAP_USD:
            failures.append("estimated run cost exceeds the USD 0.05 cap")
    if expect_startup_narration:
        if not _startup_egress_is_allowlisted(
            report["egress_attempts"], report["egress_attributions"]
        ):
            failures.append("unexpected egress origin")
    elif report["egress_attempts"]:
        failures.append("socket attempt detected")
    if report["ledger_reservations"] != 0 or not ledger_valid:
        failures.append("provider ledger reservation or read failure")

    if safe_blocked_reason:
        report["verdict"] = "BLOCKED"
        report["reason"] = safe_blocked_reason[:MAX_REASON_LENGTH]
    elif failures:
        report["verdict"] = "FAIL"
        report["reason"] = "; ".join(failures)[:MAX_REASON_LENGTH]
    else:
        report["verdict"] = "PASS"
        report["reason"] = "offline start_game proof checks passed"
    return report


def _safe_report_names(values: Any) -> tuple[list[str], bool]:
    if not isinstance(values, (list, tuple)):
        return [], False
    safe_names: list[str] = []
    valid = len(values) <= MAX_REPORTED_MODULES
    for value in values[:MAX_REPORTED_MODULES]:
        if isinstance(value, str) and MODULE_NAME_PATTERN.fullmatch(value):
            safe_names.append(value)
        else:
            valid = False
    return sorted(set(safe_names)), valid


def build_preintegrate_report(
    *,
    stub_call_counts: dict[str, int],
    egress_attempts: list[dict[str, Any]],
    egress_refusals: Optional[list[dict[str, Any]]] = None,
    egress_refusal_count: Optional[int] = None,
    registered_modules: list[str],
    detect_new_modules_after: list[str],
    active_combat_encounter_after: Any,
    seed_checks: dict[str, bool],
    router_calls: int,
    provider_function_calls: int,
    update_check_calls: int,
    ledger_reservations: Optional[int],
    ledger_valid: bool,
    blocked: bool = False,
    blocked_reason: Optional[str] = None,
    inspection_failure_reason: Optional[str] = None,
) -> dict[str, Any]:
    safe_stubs = {
        site: _bounded_count(stub_call_counts.get(site, 0))
        for site in (
            "module_stitcher.safety_review",
            "module_stitcher.travel_narration",
        )
    }
    safe_egress: list[dict[str, Any]] = []
    for attempt in egress_attempts[:MAX_RECORDED_EGRESS]:
        if not isinstance(attempt, dict):
            continue
        host_class = attempt.get("host_class")
        if host_class in ("loopback", "non_loopback"):
            safe_egress.append(
                {"host_class": host_class, "port": _safe_port(attempt.get("port"))}
            )
    safe_egress_refusals, refusal_events_valid = _safe_egress_refusals(
        egress_refusals if egress_refusals is not None else []
    )
    non_loopback_attempt_count = sum(
        1
        for attempt in safe_egress
        if attempt["host_class"] == "non_loopback"
    )
    recorded_refusal_count = (
        _bounded_count(egress_refusal_count)
        if egress_refusal_count is not None
        else non_loopback_attempt_count
    )
    egress_attempts_valid = (
        isinstance(egress_attempts, (list, tuple))
        and len(safe_egress) == min(len(egress_attempts), MAX_RECORDED_EGRESS)
    )
    refusal_coverage_complete = bool(
        egress_attempts_valid
        and refusal_events_valid
        and recorded_refusal_count == non_loopback_attempt_count
        and len(safe_egress_refusals) == recorded_refusal_count
    )
    safe_registered, registered_names_valid = _safe_report_names(registered_modules)
    safe_detected, detected_names_valid = _safe_report_names(
        detect_new_modules_after
    )
    if not detected_names_valid and not safe_detected:
        safe_detected = ["unavailable"]
    active_value = (
        "unknown"
        if isinstance(active_combat_encounter_after, str)
        and active_combat_encounter_after == "unknown"
        else "present"
        if bool(active_combat_encounter_after)
        else ""
    )
    safe_checks = {
        name: bool(seed_checks.get(name, False))
        for name in (
            "registry_has_no_unregistered_modules",
            "no_active_combat",
            "no_history_user_messages",
            "provider_free_startup_seed",
        )
    }
    ledger_count_valid = (
        ledger_valid
        and isinstance(ledger_reservations, int)
        and not isinstance(ledger_reservations, bool)
        and 0 <= ledger_reservations <= MAX_COUNTER
    )
    safe_ledger_reservations = (
        ledger_reservations if ledger_count_valid else None
    )
    safe_router_calls = _bounded_count(router_calls)
    safe_provider_calls = _bounded_count(provider_function_calls)
    safe_update_calls = _bounded_count(update_check_calls)

    report: dict[str, Any] = {
        "stub_call_counts": safe_stubs,
        "egress_attempts": safe_egress,
        "egress_refusals": safe_egress_refusals,
        "egress_refusal_coverage_complete": refusal_coverage_complete,
        "registered_modules": safe_registered,
        "detect_new_modules_after": safe_detected,
        "active_combat_encounter_after": active_value,
        "seed_checks": safe_checks,
        "router_calls": safe_router_calls,
        "provider_function_calls": safe_provider_calls,
        "update_check_calls": safe_update_calls,
        "ledger_reservations": safe_ledger_reservations,
        "ledger_valid": bool(ledger_count_valid),
    }
    safe_blocked_reason = (
        _safe_blocked_reason(blocked_reason)
        if blocked_reason
        else "RuntimeError: setup blocked; details unavailable"
        if blocked
        else None
    )
    if safe_blocked_reason is not None:
        report["blocked_reason"] = safe_blocked_reason
    failures: list[str] = []
    if not refusal_coverage_complete:
        failures.append("egress refusal attribution incomplete")
    if inspection_failure_reason:
        failures.append(_safe_blocked_reason(inspection_failure_reason))
    if not all(safe_checks.values()):
        failures.append("startup seed checks failed")
    if safe_detected or not detected_names_valid:
        failures.append("new modules remain or could not be inspected")
    if active_value != "":
        failures.append("active combat encounter is present or unknown")
    if safe_egress:
        failures.append("socket attempt detected")
    if safe_router_calls or safe_provider_calls:
        failures.append("uncovered provider call detected")
    if safe_ledger_reservations != 0:
        failures.append("provider ledger reservation or read failure")
    if not registered_names_valid:
        failures.append("registered module names could not be safely reported")
    if EXPECTED_CAPTURE_MODULE not in safe_registered:
        failures.append("Capture_Arena is not registered after integration")

    if blocked:
        report["verdict"] = "BLOCKED"
        report["reason"] = "offline preintegration setup did not complete"
    elif failures:
        report["verdict"] = "FAIL"
        report["reason"] = "; ".join(failures)[:MAX_REASON_LENGTH]
    else:
        report["verdict"] = "PASS"
        report["reason"] = "offline module preintegration checks passed"
    return report


def _install_sdk_tripwires(
    importer: Callable[[str], Any],
    patches: AttributePatches,
    recorder: ProviderCallRecorder,
    *,
    diagnostic_mode: bool = False,
    sandbox_root: Optional[Path] = None,
    tracked_targets: Optional[list[tuple[Any, str]]] = None,
) -> int:
    patched_count = 0
    chat_completion_patched = False

    seen_modules: dict[str, Any] = {}
    for module_name, class_name, method_name in SDK_PATCH_TARGETS:
        try:
            module = seen_modules.get(module_name)
            if module is None:
                module = importer(module_name)
                seen_modules[module_name] = module
        except ImportError:
            continue
        owner = getattr(module, class_name, None)
        if owner is not None and callable(getattr(owner, method_name, None)):
            def provider_tripwire(*args: Any, **kwargs: Any) -> None:
                if diagnostic_mode:
                    if sandbox_root is None:
                        raise ProofSetupError("diagnostic SDK tripwire root is unavailable")
                    recorder.block_diagnostic_provider_call(
                        args,
                        kwargs,
                        sandbox_root=sandbox_root,
                        caller_frame=sys._getframe(1),
                    )
                recorder.block_provider_function(*args, **kwargs)

            patches.set(owner, method_name, provider_tripwire)
            if tracked_targets is not None:
                tracked_targets.append((owner, method_name))
            patched_count += 1
            if (module_name, class_name, method_name) == (
                "openai.resources.chat.completions",
                "Completions",
                "create",
            ):
                chat_completion_patched = True
    if diagnostic_mode and not chat_completion_patched:
        raise ProofSetupError("OpenAI chat completion tripwire coverage is unavailable")
    return patched_count


def _install_process_launch_tripwires(
    patches: AttributePatches,
    recorder: ProviderCallRecorder,
    sandbox_root: Optional[Path],
) -> tuple[tuple[Any, str], ...]:
    """Block Python-level child-process and process-replacement APIs."""
    def process_tripwire(*args: Any, **kwargs: Any) -> None:
        recorder.block_diagnostic_process_launch(
            args,
            kwargs,
            caller_frame=sys._getframe(1),
            sandbox_root=sandbox_root,
        )

    targets: list[tuple[Any, str]] = [
        (subprocess, "Popen"),
        (subprocess, "run"),
        (subprocess, "call"),
        (subprocess, "check_call"),
        (subprocess, "check_output"),
        (os, "system"),
        (os, "popen"),
    ]
    targets.extend(
        (os, name)
        for name in dir(os)
        if name.startswith(("exec", "spawn", "posix_spawn"))
        and callable(getattr(os, name, None))
    )
    targets.extend(
        (asyncio, name)
        for name in ("create_subprocess_exec", "create_subprocess_shell")
        if callable(getattr(asyncio, name, None))
    )
    unique_targets: list[tuple[Any, str]] = []
    seen: set[tuple[int, str]] = set()
    for owner, name in targets:
        key = (id(owner), name)
        if key not in seen and callable(getattr(owner, name, None)):
            seen.add(key)
            unique_targets.append((owner, name))

    required = ((subprocess, "Popen"), (subprocess, "run"), (os, "system"))
    if any(not callable(getattr(owner, name, None)) for owner, name in required):
        raise ProofSetupError("native process-launch tripwire coverage is unavailable")
    for owner, name in unique_targets:
        patches.set(owner, name, process_tripwire)
    return tuple(unique_targets)


def _ledger_reservation_count(ledger_path: Path) -> int:
    if not ledger_path.is_file() or ledger_path.is_symlink():
        raise ProofSetupError("provider ledger is unavailable")
    if ledger_path.stat().st_size > 1024 * 1024:
        raise ProofSetupError("provider ledger size bound exceeded")
    count = 0
    with open(ledger_path, "r", encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line_number > 10000:
                raise ProofSetupError("provider ledger record bound exceeded")
            record = json.loads(line)
            if isinstance(record, dict) and record.get("event") == "reservation":
                count += 1
    if count > MAX_COUNTER:
        raise ProofSetupError("provider ledger count bound exceeded")
    return count


def _ledger_identity(path: Path) -> Optional[tuple[int, int]]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if path.is_symlink() or not path.is_file():
        raise ProofSetupError("provider ledger path is unsafe")
    return info.st_dev, info.st_ino


def _remove_owned_ledger(
    path: Path,
    created_by_tool: bool,
    identity: Optional[tuple[int, int]],
    sandbox_root: Path,
) -> None:
    if not created_by_tool or identity is None:
        return
    try:
        _reject_symlink_components(path, sandbox_root)
        current = path.lstat()
    except (FileNotFoundError, ValueError):
        return
    if (
        not path.is_symlink()
        and path.is_file()
        and (current.st_dev, current.st_ino) == identity
    ):
        path.unlink()


def _history_path_class(sandbox_root: Path, repo_root: Path = REPO_ROOT) -> str:
    expected = (repo_root / "tmp" / "combat_capture").resolve(strict=False)
    return (
        "repository_tmp/combat_capture"
        if sandbox_root == expected
        else "repository_tmp/other"
    )


def _assert_module_from_sandbox(module: Any, sandbox_root: Path) -> None:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise ProofSetupError("host module origin is unavailable")
    try:
        Path(module_file).resolve(strict=True).relative_to(sandbox_root)
    except (OSError, ValueError) as exc:
        raise ProofSetupError("host module did not load from the sandbox") from exc


def _optional_model_config_from_sandbox(
    importer: Callable[[str], Any], sandbox_root: Path
) -> Any:
    """Load only sandbox model labels; never inspect config.py or secrets."""
    try:
        module = importer("model_config")
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            return None
        Path(module_file).resolve(strict=True).relative_to(sandbox_root)
        return module
    except Exception:
        return None


def _drain_client_events(
    client: Any, event_counts: dict[str, int], state: dict[str, bool]
) -> None:
    received = client.get_received()
    for event in received:
        if not isinstance(event, dict):
            continue
        name = event.get("name")
        if name in event_counts:
            event_counts[name] = min(event_counts[name] + 1, MAX_COUNTER)
        elif name == "error":
            state["handler_error"] = True
        elif name == "game_started":
            state["game_started"] = True


def _runtime_alive(web_module: Any) -> bool:
    accessor = getattr(web_module, "_player_sharing_runtime_available", None)
    if callable(accessor):
        return bool(accessor())
    thread = getattr(web_module, "game_thread", None)
    return bool(thread is not None and thread.is_alive())


def _atomic_write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    payload.encode("ascii")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".n3-start-game-proof-", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def run_proof(
    *,
    sandbox_root: str | Path = DEFAULT_SANDBOX,
    run_id: str = DEFAULT_RUN_ID,
    output_dir: Optional[str | Path] = None,
    startup_timeout: float = 30.0,
    settle_seconds: float = 20.0,
    host_importer: Optional[Callable[[str], Any]] = None,
    preserve_runtime_guards: bool = False,
    expect_startup_narration: bool = False,
    require_priced_route: bool = False,
) -> dict[str, Any]:
    """Run the Socket.IO handler in the sandbox and write a bounded report."""
    report_path = resolve_output_file(output_dir, run_id)
    safe_run_id = validate_run_id(run_id)
    if not 0 < startup_timeout <= 120 or not 0 <= settle_seconds <= 120:
        raise ValueError("startup and settle windows must be bounded")

    history_messages = 0
    history_users = 0
    router_calls = 0
    provider_calls = 0
    ledger_reservations: Optional[int] = None
    ledger_valid = False
    event_counts = {"game_output": 0, "status_update": 0}
    blocked_reason: Optional[str] = None
    alive_seen = False
    alive_at_seconds: Optional[float] = None
    runtime_alive_at_end = False
    egress_guard = EgressGuard()
    recorder = ProviderCallRecorder()
    patches = AttributePatches()
    importer = host_importer or importlib.import_module
    original_cwd = Path.cwd()
    original_sys_path = list(sys.path)
    original_streams = (sys.stdout, sys.stderr, sys.stdin)
    env_names = (
        "NEQ_OPEN_BROWSER",
        "NEQ_PROVIDER_ATTEMPT_BUDGET",
        "NEQ_PROVIDER_ATTEMPT_LEDGER",
        "NEQ_PROVIDER_ATTEMPT_RUN_ID",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    sandbox: Optional[Path] = None
    web_module: Any = None
    client: Any = None
    ledger_path: Optional[Path] = None
    ledger_created_by_tool = False
    ledger_identity: Optional[tuple[int, int]] = None
    cleanup_guards = True
    context_changed = False

    try:
        sandbox = validate_sandbox_root(sandbox_root)
        egress_guard.set_sandbox_root(sandbox)
        history_messages, history_users = count_conversation_history(sandbox)
        required_sources = (
            "main.py",
            "web/web_interface.py",
            "utils/llm_router.py",
            "utils/provider_attempt_budget.py",
            "utils/version_checker.py",
        )
        if any(not (sandbox / relative).is_file() for relative in required_sources):
            raise ProofSetupError("sandbox host source inventory is incomplete")

        ledger_directory = sandbox / "tmp" / "n2"
        try:
            _reject_symlink_components(ledger_directory, sandbox)
        except ValueError as exc:
            raise ProofSetupError("sandbox provider ledger directory is unsafe") from exc
        ledger_directory.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_directory / ("provider-attempt-ledger-" + safe_run_id + ".jsonl")
        if ledger_path.exists() or ledger_path.is_symlink():
            raise ProofSetupError("provider ledger path already exists")

        os.environ["NEQ_OPEN_BROWSER"] = "0"
        os.environ.update(PROVIDER_ENVIRONMENT)
        os.environ["NEQ_PROVIDER_ATTEMPT_LEDGER"] = str(ledger_path)
        os.environ["NEQ_PROVIDER_ATTEMPT_RUN_ID"] = safe_run_id
        os.chdir(sandbox)
        sys.path.insert(0, str(sandbox))
        context_changed = True

        egress_guard.install()
        egress_guard.assert_active()

        # Explicit activation proves the configured sandbox-local ledger is accepted.
        budget_module = importer("utils.provider_attempt_budget")
        activate = getattr(budget_module, "activate_provider_attempt_budget", None)
        if not callable(activate):
            raise ProofSetupError("provider attempt budget activation is unavailable")
        active_path = activate()
        if active_path is None or Path(active_path).resolve(strict=False) != ledger_path:
            raise ProofSetupError("provider attempt budget did not activate the requested ledger")
        _assert_module_from_sandbox(budget_module, sandbox)
        ledger_identity = _ledger_identity(ledger_path)
        ledger_created_by_tool = ledger_identity is not None

        # The tripwires are installed before web.web_interface is imported.
        router_module = importer("utils.llm_router")
        _assert_module_from_sandbox(router_module, sandbox)
        router = getattr(router_module, "llm", None)
        if router is None or not callable(getattr(router, "call", None)):
            raise ProofSetupError("LLM router call entry point is unavailable")
        model_config_module = _optional_model_config_from_sandbox(importer, sandbox)

        def router_tripwire(*args: Any, **kwargs: Any) -> None:
            recorder.record_initial_narration_request(
                args,
                kwargs,
                capture_site="llm_router",
                model_config=model_config_module,
            )
            recorder.block_router_call(*args, **kwargs)

        patches.set(router, "call", router_tripwire)
        _install_sdk_tripwires(importer, patches, recorder)

        version_module = importer("utils.version_checker")
        _assert_module_from_sandbox(version_module, sandbox)
        if not callable(getattr(version_module, "get_latest_remote_version", None)):
            raise ProofSetupError("version update check entry point is unavailable")

        def update_check_stub(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            recorder.record_update_check()
            return None

        patches.set(version_module, "get_latest_remote_version", update_check_stub)

        web_module = importer("web.web_interface")
        _assert_module_from_sandbox(web_module, sandbox)
        main_module = getattr(web_module, "dm_main", None)
        if main_module is None:
            raise ProofSetupError("web interface main module is unavailable")
        _assert_module_from_sandbox(main_module, sandbox)
        if not callable(getattr(main_module, "get_ai_response", None)):
            raise ProofSetupError("main AI response entry point is unavailable")

        def main_response_tripwire(*args: Any, **kwargs: Any) -> None:
            recorder.record_initial_narration_request(
                args,
                kwargs,
                capture_site="get_ai_response",
                model_config=model_config_module,
            )
            recorder.block_provider_function(*args, **kwargs)

        patches.set(main_module, "get_ai_response", main_response_tripwire)
        egress_guard.assert_active()

        socketio = getattr(web_module, "socketio", None)
        app = getattr(web_module, "app", None)
        if socketio is None or app is None or not callable(
            getattr(socketio, "test_client", None)
        ):
            raise ProofSetupError("in-process Socket.IO test client is unavailable")
        client = socketio.test_client(
            app,
            headers={"Origin": PROOF_ORIGIN},
        )
        if not client:
            raise ProofSetupError("Socket.IO test client could not connect")

        event_state = {"handler_error": False, "game_started": False}
        started_at = time.monotonic()
        try:
            client.emit("start_game")
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            observed_request = recorder.initial_request_snapshot()
            observed_router_calls, observed_provider_calls, _ = recorder.snapshot()
            if not (
                expect_startup_narration
                and isinstance(exc, ProviderCallBlocked)
                and _expected_startup_narration_intercept(
                    observed_request,
                    observed_router_calls,
                    observed_provider_calls,
                )
            ):
                blocked_reason = _exception_blocked_reason(exc)

        if blocked_reason is None:
            try:
                _drain_client_events(client, event_counts, event_state)
            except Exception:
                event_state["handler_error"] = True

        deadline = started_at + startup_timeout
        while blocked_reason is None and not alive_seen:
            try:
                alive_now = _runtime_alive(web_module)
            except Exception:
                alive_now = False
            if alive_now:
                alive_seen = True
                alive_at_seconds = time.monotonic() - started_at
                break
            try:
                _drain_client_events(client, event_counts, event_state)
            except Exception:
                event_state["handler_error"] = True
            if event_state["handler_error"] and not event_state["game_started"]:
                blocked_reason = (
                    "RuntimeError: start_game handler reported an error before thread startup"
                )
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.02, remaining))

        if blocked_reason is None and not alive_seen:
            # Continue observing after the start deadline; this remains bounded.
            settle_deadline = time.monotonic() + settle_seconds
            while time.monotonic() < settle_deadline:
                try:
                    _drain_client_events(client, event_counts, event_state)
                    if _runtime_alive(web_module):
                        alive_seen = True
                        alive_at_seconds = time.monotonic() - started_at
                except Exception:
                    pass
                time.sleep(min(0.02, max(0.0, settle_deadline - time.monotonic())))
        elif blocked_reason is None and alive_seen:
            settle_deadline = time.monotonic() + settle_seconds
            while time.monotonic() < settle_deadline:
                try:
                    _drain_client_events(client, event_counts, event_state)
                    _runtime_alive(web_module)
                except Exception:
                    pass
                time.sleep(min(0.02, max(0.0, settle_deadline - time.monotonic())))

        try:
            runtime_alive_at_end = _runtime_alive(web_module)
        except Exception:
            runtime_alive_at_end = False
        egress_guard.assert_active()
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        if blocked_reason is None:
            blocked_reason = _exception_blocked_reason(exc)
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
        router_calls, provider_calls, update_check_calls = recorder.snapshot()
        if ledger_path is not None:
            try:
                ledger_reservations = _ledger_reservation_count(ledger_path)
                ledger_valid = True
            except Exception:
                ledger_valid = False

        keep_runtime_guards = bool(
            preserve_runtime_guards and runtime_alive_at_end and web_module is not None
        )
        cleanup_guards = not keep_runtime_guards
        if ledger_path is not None and (
            not runtime_alive_at_end or keep_runtime_guards
        ):
            try:
                _remove_owned_ledger(
                    ledger_path,
                    ledger_created_by_tool,
                    ledger_identity,
                    sandbox if sandbox is not None else ledger_path.parents[2],
                )
            except OSError:
                ledger_valid = False
        if cleanup_guards:
            patches.restore()
            egress_guard.restore()
            for name, previous in original_env.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
            if context_changed:
                os.chdir(original_cwd)
                sys.path[:] = original_sys_path
            sys.stdout, sys.stderr, sys.stdin = original_streams

    egress_refusals, egress_refusal_count = egress_guard.refusal_snapshot()
    report = build_report(
        sandbox_path_class=(
            _history_path_class(sandbox)
            if sandbox is not None
            else "repository_tmp/other"
        ),
        conversation_history_message_count=history_messages,
        conversation_history_user_message_count=history_users,
        game_thread_alive=alive_seen,
        seconds_to_alive=alive_at_seconds,
        router_calls=router_calls,
        provider_function_calls=provider_calls,
        update_check_calls=update_check_calls,
        egress_attempts=egress_guard.snapshot(),
        egress_attributions=egress_guard.attribution_snapshot(),
        egress_refusals=egress_refusals,
        egress_refusal_count=egress_refusal_count,
        initial_narration_request=recorder.initial_request_snapshot(),
        ledger_reservations=ledger_reservations,
        observed_events=event_counts,
        blocked_reason=blocked_reason,
        ledger_valid=ledger_valid,
        expect_startup_narration=expect_startup_narration,
        require_priced_route=require_priced_route,
    )
    _atomic_write_report(report_path, report)
    return report


def run_startup_diagnostic(
    *,
    sandbox_root: str | Path = DEFAULT_SANDBOX,
    run_id: str = DEFAULT_RUN_ID,
    output_dir: Optional[str | Path] = None,
    startup_timeout: float = 30.0,
    diagnostic_call_limit: int = DEFAULT_DIAGNOSTIC_CALL_LIMIT,
    isolated_worker: bool = False,
    host_importer: Optional[Callable[[str], Any]] = None,
    observe_running_host: Optional[Callable[[Any, Any], Mapping[str, object]]] = None,
) -> dict[str, Any]:
    """Trace bounded router calls through the real Socket.IO start_game path.

    The two expected startup requests receive fixed local responses. Any other
    router task, extra call, direct SDK request, or socket operation is blocked.
    Application output is discarded; only a non-empty narration event's
    delivery is observed.

    observe_running_host, when given, is called exactly once with an
    _ObservationClient facade (emit() and get_received() only, backed by the
    real Socket.IO test client) and the real web module, after startup
    narration has been delivered and before the diagnostic's own shutdown
    input is queued. Any event the hook drains via get_received() is also
    recorded and replayed into this function's own later event scan, so a
    hook that calls get_received() can never cause this function to miss the
    game_started/game_output events it still needs to see. The hook's bounded
    (booleans/ints/short ASCII strings only) returned mapping is attached to
    the report under "observation"; any exception or non-mapping return is
    recorded under "observation_failure" and fails the report closed. Leaving
    it unset (the default) leaves this function's behavior unchanged.
    """
    report_path = resolve_startup_diagnostic_output_file(output_dir, run_id)
    safe_run_id = validate_run_id(run_id)
    if report_path.exists() or report_path.is_symlink():
        raise ProofSetupError("startup diagnostic report path already exists")
    if not 0 < startup_timeout <= 120:
        raise ValueError("startup diagnostic timeout must be bounded")
    if not 2 <= diagnostic_call_limit <= MAX_DIAGNOSTIC_CALLS:
        raise ValueError("startup diagnostic call limit is outside the supported bound")

    recorder = ProviderCallRecorder(
        diagnostic_mode=True,
        diagnostic_call_limit=diagnostic_call_limit,
    )
    egress_guard = EgressGuard(deny_loopback=True)
    patches = AttributePatches()
    importer = importlib.import_module if host_importer is None else host_importer
    real_host_importer = host_importer is None
    host_imports_verified = False
    original_cwd = Path.cwd()
    original_sys_path = list(sys.path)
    original_streams = (sys.stdout, sys.stderr, sys.stdin)
    original_config = sys.modules.get("config", _MISSING_MODULE)
    original_thread_ids = {
        thread.ident for thread in threading.enumerate() if thread.ident is not None
    }
    env_names = (
        "NEQ_OPEN_BROWSER",
        "NEQ_PROVIDER_ATTEMPT_BUDGET",
        "NEQ_PROVIDER_ATTEMPT_LEDGER",
        "NEQ_PROVIDER_ATTEMPT_RUN_ID",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    sandbox: Optional[Path] = None
    web_module: Any = None
    client: Any = None
    ledger_path: Optional[Path] = None
    ledger_created_by_tool = False
    ledger_identity: Optional[tuple[int, int]] = None
    ledger_reservations: Optional[int] = None
    ledger_valid = False
    patches_active = False
    router_call_target: Optional[tuple[Any, str]] = None
    router_decide_target: Optional[tuple[Any, str]] = None
    router_call_guard = False
    router_decide_guard = False
    sdk_tripwire_targets: list[tuple[Any, str]] = []
    sdk_tripwire_count = 0
    egress_guard_active = False
    process_launch_targets: tuple[tuple[Any, str], ...] = ()
    process_launch_guard = False
    startup_output_sent = threading.Event()
    output_pump_done = threading.Event()
    emit_completed = threading.Event()
    emit_failure: Optional[str] = None
    output_pump_failure: Optional[str] = None
    output_pump_deadline: Optional[float] = None
    startup_thread_stopped = False
    game_started = False
    startup_output_delivered = False
    shutdown_sent = False
    blocked_reason: Optional[str] = None
    failure_exception_class: Optional[str] = None
    failure_category = "none"
    observation: Optional[Mapping[str, object]] = None
    observation_failure: Optional[str] = None
    hook_drained_events: list[Any] = []
    failure_origin: Optional[dict[str, Any]] = None
    diagnostic_stage = "sandbox_setup"
    emit_thread: Optional[threading.Thread] = None
    cleanup_context = True
    context_changed = False
    runtime_alive = False
    new_live_threads = False

    try:
        sandbox = validate_sandbox_root(sandbox_root)
        egress_guard.set_sandbox_root(sandbox)
        required_sources = (
            "main.py",
            "web/web_interface.py",
            "utils/llm_router.py",
            "utils/ai_client_factory.py",
            "utils/provider_attempt_budget.py",
            "utils/version_checker.py",
            "model_config.py",
        )
        if any(not (sandbox / relative).is_file() for relative in required_sources):
            raise ProofSetupError("sandbox host source inventory is incomplete")

        ledger_directory = sandbox / "tmp" / "n2"
        try:
            _reject_symlink_components(ledger_directory, sandbox)
        except ValueError as exc:
            raise ProofSetupError("sandbox provider ledger directory is unsafe") from exc
        ledger_directory.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_directory / (
            "provider-attempt-ledger-startup-diagnostic-" + safe_run_id + ".jsonl"
        )
        if ledger_path.exists() or ledger_path.is_symlink():
            raise ProofSetupError("provider ledger path already exists")

        os.environ["NEQ_OPEN_BROWSER"] = "0"
        os.environ.update(PROVIDER_ENVIRONMENT)
        os.environ["NEQ_PROVIDER_ATTEMPT_LEDGER"] = str(ledger_path)
        os.environ["NEQ_PROVIDER_ATTEMPT_RUN_ID"] = safe_run_id
        os.chdir(sandbox)
        sys.path.insert(0, str(sandbox))
        sys.stdout = _DiscardingTextStream()
        sys.stderr = _DiscardingTextStream()
        sys.modules["config"] = _offline_diagnostic_config_module()
        context_changed = True

        egress_guard.install()
        egress_guard.assert_active()
        egress_guard_active = True
        # urllib3's IPv6 capability probe binds to ::1:0 during import. The
        # diagnostic needs no IPv6 capability discovery; disable only this
        # import-time probe while the egress guard remains fully active.
        patches.set(socket, "has_ipv6", False)
        process_launch_targets = _install_process_launch_tripwires(
            patches, recorder, sandbox
        )

        diagnostic_stage = "provider_budget_setup"
        budget_module = importer("utils.provider_attempt_budget")
        _assert_module_from_sandbox(budget_module, sandbox)
        activate = getattr(budget_module, "activate_provider_attempt_budget", None)
        if not callable(activate):
            raise ProofSetupError("provider attempt budget activation is unavailable")
        active_path = activate()
        if active_path is None or Path(active_path).resolve(strict=False) != ledger_path:
            raise ProofSetupError("provider attempt budget did not activate the requested ledger")
        ledger_identity = _ledger_identity(ledger_path)
        ledger_created_by_tool = ledger_identity is not None

        diagnostic_stage = "router_setup"
        router_module = importer("utils.llm_router")
        _assert_module_from_sandbox(router_module, sandbox)
        router = getattr(router_module, "llm", None)
        model_config_module = _optional_model_config_from_sandbox(importer, sandbox)
        if router is None or model_config_module is None:
            raise ProofSetupError("sandbox router or model profile is unavailable")
        if not callable(getattr(router, "call", None)):
            raise ProofSetupError("LLM router call entry point is unavailable")
        if not callable(getattr(router, "decide", None)):
            raise ProofSetupError("LLM router decide entry point is unavailable")

        def router_call_tripwire(*args: Any, **kwargs: Any) -> str:
            return recorder.diagnostic_router_call(
                args,
                kwargs,
                model_config=model_config_module,
                sandbox_root=sandbox,
                caller_frame=sys._getframe(1),
                bound_method=False,
            )

        def router_decide_tripwire(*args: Any, **kwargs: Any) -> str:
            return recorder.diagnostic_router_call(
                args,
                kwargs,
                model_config=model_config_module,
                sandbox_root=sandbox,
                caller_frame=sys._getframe(1),
                bound_method=False,
                allow_stub=False,
            )

        patches.set(router, "call", router_call_tripwire)
        patches.set(router, "decide", router_decide_tripwire)
        router_call_target = (router, "call")
        router_decide_target = (router, "decide")
        diagnostic_stage = "sdk_tripwire_setup"
        sdk_tripwire_count = _install_sdk_tripwires(
            importer,
            patches,
            recorder,
            diagnostic_mode=True,
            sandbox_root=sandbox,
            tracked_targets=sdk_tripwire_targets,
        )

        diagnostic_stage = "client_factory_setup"
        factory_module = importer("utils.ai_client_factory")
        _assert_module_from_sandbox(factory_module, sandbox)
        if not callable(getattr(factory_module, "create_chat_client", None)):
            raise ProofSetupError("legacy provider client factory is unavailable")

        def offline_chat_client_factory(*args: Any, **kwargs: Any) -> _OfflineDiagnosticClient:
            del args, kwargs
            return _OfflineDiagnosticClient(recorder, sandbox)

        def blocked_provider_factory(*args: Any, **kwargs: Any) -> None:
            recorder.block_diagnostic_provider_call(
                args,
                kwargs,
                sandbox_root=sandbox,
                caller_frame=sys._getframe(1),
            )

        patches.set(factory_module, "create_chat_client", offline_chat_client_factory)
        for factory_name in (
            "create_image_client",
            "create_tts_client",
            "create_video_client",
        ):
            if callable(getattr(factory_module, factory_name, None)):
                patches.set(factory_module, factory_name, blocked_provider_factory)

        diagnostic_stage = "version_check_setup"
        version_module = importer("utils.version_checker")
        _assert_module_from_sandbox(version_module, sandbox)
        if not callable(getattr(version_module, "_run_git_command", None)):
            raise ProofSetupError("version git metadata probe entry point is unavailable")
        if not callable(getattr(version_module, "get_latest_remote_version", None)):
            raise ProofSetupError("version update check entry point is unavailable")

        def git_metadata_probe_stub(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            return None

        def update_check_stub(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            recorder.record_update_check()
            return None

        patches.set(version_module, "_run_git_command", git_metadata_probe_stub)
        patches.set(version_module, "get_latest_remote_version", update_check_stub)

        diagnostic_stage = "host_import"
        web_module = importer("web.web_interface")
        _assert_module_from_sandbox(web_module, sandbox)
        main_module = getattr(web_module, "dm_main", None)
        if main_module is None:
            raise ProofSetupError("web interface main module is unavailable")
        _assert_module_from_sandbox(main_module, sandbox)
        host_imports_verified = real_host_importer
        if not callable(getattr(main_module, "get_ai_response", None)):
            raise ProofSetupError("main AI response entry point is unavailable")
        if not callable(getattr(main_module, "save_conversation_history", None)):
            raise ProofSetupError("conversation-history persistence boundary is unavailable")
        if not callable(getattr(web_module, "add_to_message_cache", None)):
            raise ProofSetupError("narration cache persistence boundary is unavailable")

        socketio = getattr(web_module, "socketio", None)
        app = getattr(web_module, "app", None)
        user_input_queue = getattr(web_module, "user_input_queue", None)
        game_output_queue = getattr(web_module, "game_output_queue", None)
        output_pump = getattr(web_module, "send_output_to_clients", None)
        original_emit = getattr(socketio, "emit", None) if socketio is not None else None
        if (
            socketio is None
            or app is None
            or user_input_queue is None
            or game_output_queue is None
            or not callable(getattr(game_output_queue, "get", None))
            or not callable(output_pump)
            or not callable(original_emit)
            or not callable(getattr(socketio, "test_client", None))
            or not callable(getattr(user_input_queue, "put", None))
        ):
            raise ProofSetupError("in-process Socket.IO startup surface is unavailable")

        def observe_socket_emit(*args: Any, **kwargs: Any) -> Any:
            event_name = args[0] if args else kwargs.get("event")
            payload = args[1] if len(args) > 1 else kwargs.get("data")
            result = original_emit(*args, **kwargs)
            if event_name == "game_output" and _is_nonempty_narration_payload(payload):
                startup_output_sent.set()
            return result

        def discard_conversation_history(history: Any) -> None:
            del history

        def discard_message_cache(message: Any) -> None:
            del message

        original_open = builtins.open

        def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            mode = args[0] if args else kwargs.get("mode", "r")
            if (
                isinstance(mode, str)
                and any(flag in mode for flag in ("w", "a", "x", "+"))
                and _is_sensitive_diagnostic_log_path(file, sandbox)
            ):
                return _DiscardingTextStream()
            return original_open(file, *args, **kwargs)

        def discard_log_record(logger: Any, record: Any) -> None:
            del logger, record

        def bounded_output_pump() -> None:
            nonlocal output_pump_failure
            try:
                while True:
                    deadline = output_pump_deadline
                    if deadline is None:
                        deadline = time.monotonic() + startup_timeout
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return
                    try:
                        payload = game_output_queue.get(timeout=min(0.05, remaining))
                    except queue.Empty:
                        continue
                    socketio.emit("game_output", payload)
                    if _is_nonempty_narration_payload(payload):
                        return
            except BaseException as exc:
                name = type(exc).__name__
                output_pump_failure = (
                    name if EXCEPTION_CLASS_PATTERN.fullmatch(name) else "Exception"
                )
            finally:
                output_pump_done.set()

        diagnostic_stage = "startup_boundary_setup"
        patches.set(socketio, "emit", observe_socket_emit)
        patches.set(web_module, "send_output_to_clients", bounded_output_pump)
        patches.set(main_module, "save_conversation_history", discard_conversation_history)
        patches.set(web_module, "add_to_message_cache", discard_message_cache)
        patches.set(builtins, "open", guarded_open)
        patches.set(logging.Logger, "handle", discard_log_record)
        patches_active = True
        patches.assert_active()
        egress_guard.assert_active()

        diagnostic_stage = "socketio_test_client"
        client = socketio.test_client(app, headers={"Origin": PROOF_ORIGIN})
        if not client:
            raise ProofSetupError("Socket.IO test client could not connect")

        def emit_start_game() -> None:
            nonlocal emit_failure
            try:
                client.emit("start_game")
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    emit_failure = type(exc).__name__
                else:
                    name = type(exc).__name__
                    emit_failure = (
                        name if EXCEPTION_CLASS_PATTERN.fullmatch(name) else "Exception"
                    )
            finally:
                emit_completed.set()

        diagnostic_stage = "startup_event"
        started_at = time.monotonic()
        startup_deadline = started_at + startup_timeout
        output_pump_deadline = startup_deadline
        emit_thread = threading.Thread(
            target=emit_start_game,
            name="n3-start-game-diagnostic",
            daemon=True,
        )
        emit_thread.start()
        while time.monotonic() < startup_deadline:
            patches.assert_active()
            egress_guard.assert_active()
            if startup_output_sent.is_set():
                break
            time.sleep(min(0.01, max(0.0, startup_deadline - time.monotonic())))

        if startup_output_sent.is_set():
            if observe_running_host is not None:
                diagnostic_stage = "startup_observation"
                observation_client = _ObservationClient(client, hook_drained_events)
                try:
                    raw_observation = observe_running_host(observation_client, web_module)
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    observation_failure = "observation_hook_raised"
                else:
                    sanitized_observation = _sanitize_observation_mapping(
                        raw_observation
                    )
                    if sanitized_observation is None:
                        observation_failure = "observation_hook_invalid_return"
                    else:
                        observation = sanitized_observation
                diagnostic_stage = "startup_event"
            diagnostic_stage = "startup_shutdown"
            try:
                user_input_queue.put("/quit")
                shutdown_sent = True
            except BaseException:
                blocked_reason = "diagnostic shutdown input could not be queued"

        shutdown_deadline = time.monotonic() + STARTUP_DIAGNOSTIC_SHUTDOWN_SECONDS
        while time.monotonic() < shutdown_deadline:
            if (
                shutdown_sent
                and emit_completed.is_set()
                and output_pump_done.is_set()
                and not _runtime_alive(web_module)
            ):
                startup_thread_stopped = True
                break
            time.sleep(min(0.01, max(0.0, shutdown_deadline - time.monotonic())))
        if emit_thread is not None:
            emit_thread.join(timeout=0.1)

        game_started = False
        client_narration_delivered = False
        try:
            for event in list(hook_drained_events) + client.get_received():
                if not isinstance(event, dict):
                    continue
                event_name = event.get("name")
                if event_name == "game_started":
                    game_started = True
                elif event_name == "error":
                    if blocked_reason is None:
                        failure_category = "startup_handler_error"
                        blocked_reason = "start_game handler reported an error"
                elif event_name == "game_output":
                    event_args = event.get("args")
                    if isinstance(event_args, (list, tuple)):
                        client_narration_delivered = client_narration_delivered or any(
                            _is_nonempty_narration_payload(payload)
                            for payload in event_args
                        )
        except BaseException:
            if blocked_reason is None:
                failure_category = "startup_output_failed"
                blocked_reason = "startup output delivery could not be verified"
        startup_output_delivered = bool(
            startup_output_sent.is_set() and client_narration_delivered
        )

        try:
            patches.assert_active()
        except ProofSetupError:
            patches_active = False
        try:
            egress_guard.assert_active()
        except ProofSetupError:
            egress_guard_active = False
        if emit_failure and blocked_reason is None:
            failure_exception_class = _safe_exception_class(emit_failure)
            _, _, recorder_failure, _ = recorder.diagnostic_snapshot()
            failure_category = _startup_failure_category(
                failure_exception_class,
                "startup_event",
                recorder_failure,
            )
            blocked_reason = "start_game event failed (" + emit_failure + ")"
        if output_pump_failure and blocked_reason is None:
            failure_exception_class = _safe_exception_class(output_pump_failure)
            failure_category = _startup_failure_category(
                failure_exception_class, "startup_output"
            )
            blocked_reason = "startup output transport failed (" + output_pump_failure + ")"
        if not startup_output_delivered and blocked_reason is None:
            failure_category = "startup_output_failed"
            blocked_reason = "startup narration output was not delivered within the bound"
        if startup_output_delivered and not shutdown_sent and blocked_reason is None:
            failure_category = "startup_shutdown_failed"
            blocked_reason = "diagnostic shutdown input was not queued"
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        if diagnostic_stage == "host_import":
            failure_origin = _exception_failure_origin(exc, sandbox)
        name = type(exc).__name__
        safe_name = name if EXCEPTION_CLASS_PATTERN.fullmatch(name) else "Exception"
        failure_exception_class = _safe_exception_class(name)
        _, _, recorder_failure, _ = recorder.diagnostic_snapshot()
        failure_category = _startup_failure_category(
            failure_exception_class,
            diagnostic_stage,
            recorder_failure,
        )
        blocked_reason = "startup diagnostic setup or runtime failed (" + safe_name + ")"
    finally:
        if client is not None:
            try:
                client.disconnect()
            except BaseException:
                pass
        try:
            ledger_reservations = (
                _ledger_reservation_count(ledger_path)
                if ledger_path is not None
                else None
            )
            ledger_valid = ledger_reservations is not None
        except BaseException:
            ledger_valid = False

        try:
            runtime_alive = _runtime_alive(web_module) if web_module is not None else False
        except BaseException:
            runtime_alive = True
        new_live_threads = any(
            thread.is_alive()
            and thread.ident not in original_thread_ids
            and thread is not threading.current_thread()
            for thread in threading.enumerate()
        )
        cleanup_context = not (runtime_alive or new_live_threads)

        if patches_active:
            try:
                patches.assert_active()
            except ProofSetupError:
                patches_active = False
        router_call_guard = bool(
            router_call_target
            and patches.targets_active((router_call_target,))
        )
        router_decide_guard = bool(
            router_decide_target
            and patches.targets_active((router_decide_target,))
        )
        process_launch_guard = bool(
            len(process_launch_targets) >= 3
            and patches.targets_active(process_launch_targets)
        )
        sdk_tripwire_count = sum(
            patches.targets_active((target,)) for target in sdk_tripwire_targets
        )
        if sdk_tripwire_targets and not patches.targets_active(
            (sdk_tripwire_targets[0],)
        ):
            sdk_tripwire_count = 0

        if ledger_path is not None:
            try:
                _remove_owned_ledger(
                    ledger_path,
                    ledger_created_by_tool,
                    ledger_identity,
                    sandbox if sandbox is not None else ledger_path.parents[2],
                )
            except OSError:
                ledger_valid = False
        if cleanup_context:
            patches.restore()
            egress_guard.restore()
            for name, previous in original_env.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
            if original_config is _MISSING_MODULE:
                sys.modules.pop("config", None)
            else:
                sys.modules["config"] = original_config
            if context_changed:
                os.chdir(original_cwd)
                sys.path[:] = original_sys_path
            sys.stdout, sys.stderr, sys.stdin = original_streams

    call_events, stub_counts, recorder_failure, call_overflow = (
        recorder.diagnostic_snapshot()
    )
    router_calls, provider_calls, _ = recorder.snapshot()
    network_attempts = egress_guard.attempt_count()
    egress_refusals, egress_refusal_count = egress_guard.refusal_snapshot()
    if failure_category == "none" and recorder_failure:
        failure_exception_class = "ProviderCallBlocked"
        failure_category = _startup_failure_category(
            failure_exception_class,
            "startup_event",
            recorder_failure,
        )
    if failure_category == "none" and network_attempts:
        failure_category = "egress_blocked"
    report = _startup_diagnostic_report(
        call_events=call_events,
        stub_call_counts=stub_counts,
        router_calls=router_calls,
        provider_calls=provider_calls,
        network_attempts=network_attempts,
        ledger_reservations=ledger_reservations,
        ledger_valid=ledger_valid,
        startup_output_delivered=startup_output_delivered,
        game_started=game_started,
        startup_thread_stopped=startup_thread_stopped,
        diagnostic_failure=recorder_failure or blocked_reason,
        call_overflow=call_overflow,
        router_call_guard=router_call_guard,
        router_decide_guard=router_decide_guard,
        sdk_tripwire_count=sdk_tripwire_count,
        egress_guard_active=egress_guard_active,
        process_launch_guard=process_launch_guard,
        host_imports_verified=host_imports_verified,
        startup_boundary_guard_active=patches_active,
        egress_attributions=egress_guard.attribution_snapshot(),
        egress_refusals=egress_refusals,
        egress_refusal_count=egress_refusal_count,
        failure_exception_class=failure_exception_class,
        failure_category=failure_category,
        failure_origin=failure_origin,
        process_launch_refusal=recorder.process_launch_refusal_snapshot(),
        observation=observation,
        observation_failure=observation_failure,
    )
    if runtime_alive or (new_live_threads and not isolated_worker):
        report["verdict"] = "BLOCKED"
        report["reason"] = (
            "startup game thread remained active after the diagnostic shutdown"
            if runtime_alive
            else "startup diagnostic retained guarded background threads"
        )
    _atomic_write_report(report_path, report)
    return report


def run_preintegrate(
    *,
    sandbox_root: str | Path = DEFAULT_SANDBOX,
    run_id: str = DEFAULT_RUN_ID,
    output_dir: Optional[str | Path] = None,
    host_importer: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """Integrate newly detected modules offline in a fresh host process."""
    report_path = resolve_preintegrate_output_file(output_dir, run_id)
    safe_run_id = validate_run_id(run_id)
    recorder = PreintegrateCallRecorder()
    egress_guard = EgressGuard()
    patches = AttributePatches()
    importer = host_importer or importlib.import_module
    original_cwd = Path.cwd()
    original_sys_path = list(sys.path)
    env_names = (
        "NEQ_OPEN_BROWSER",
        "NEQ_PROVIDER_ATTEMPT_BUDGET",
        "NEQ_PROVIDER_ATTEMPT_LEDGER",
        "NEQ_PROVIDER_ATTEMPT_RUN_ID",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    sandbox: Optional[Path] = None
    ledger_path: Optional[Path] = None
    ledger_created_by_tool = False
    ledger_identity: Optional[tuple[int, int]] = None
    ledger_reservations: Optional[int] = None
    ledger_valid = False
    context_changed = False
    integration_completed = False
    blocked = False
    blocked_reason: Optional[str] = None
    inspection_failure_reason: Optional[str] = None
    seed_checks = _static_seed_failure()
    registered_modules: list[str] = []
    detected_modules = ["unavailable"]
    active_combat_encounter: Any = "unknown"

    try:
        sandbox = validate_sandbox_root(sandbox_root)
        required_sources = (
            "main.py",
            "core/generators/module_stitcher.py",
            "core/managers/campaign_manager.py",
            "utils/llm_router.py",
            "utils/provider_attempt_budget.py",
            "utils/version_checker.py",
        )
        if any(not (sandbox / relative).is_file() for relative in required_sources):
            raise ProofSetupError("sandbox host source inventory is incomplete")

        ledger_directory = sandbox / "tmp" / "n2"
        try:
            _reject_symlink_components(ledger_directory, sandbox)
        except ValueError as exc:
            raise ProofSetupError("sandbox provider ledger directory is unsafe") from exc
        ledger_directory.mkdir(parents=True, exist_ok=True)
        candidate_ledger_path = ledger_directory / (
            "provider-attempt-ledger-" + safe_run_id + ".jsonl"
        )
        if candidate_ledger_path.exists() or candidate_ledger_path.is_symlink():
            raise ProofSetupError("provider ledger path already exists")
        ledger_path = candidate_ledger_path

        os.environ["NEQ_OPEN_BROWSER"] = "0"
        os.environ.update(PROVIDER_ENVIRONMENT)
        os.environ["NEQ_PROVIDER_ATTEMPT_LEDGER"] = str(ledger_path)
        os.environ["NEQ_PROVIDER_ATTEMPT_RUN_ID"] = safe_run_id
        os.chdir(sandbox)
        sys.path.insert(0, str(sandbox))
        context_changed = True

        egress_guard.install()
        egress_guard.assert_active()

        budget_module = importer("utils.provider_attempt_budget")
        activate = getattr(budget_module, "activate_provider_attempt_budget", None)
        if not callable(activate):
            raise ProofSetupError("provider attempt budget activation is unavailable")
        active_path = activate()
        if active_path is None or Path(active_path).resolve(strict=False) != ledger_path:
            raise ProofSetupError("provider attempt budget did not activate the requested ledger")
        _assert_module_from_sandbox(budget_module, sandbox)
        ledger_identity = _ledger_identity(ledger_path)
        ledger_created_by_tool = ledger_identity is not None

        router_module = importer("utils.llm_router")
        _assert_module_from_sandbox(router_module, sandbox)
        router = getattr(router_module, "llm", None)
        if router is None or not callable(getattr(router, "call", None)):
            raise ProofSetupError("LLM router call entry point is unavailable")

        def router_tripwire(*args: Any, **kwargs: Any) -> None:
            recorder.block_router_call(*args, **kwargs)

        patches.set(router, "call", router_tripwire)
        _install_sdk_tripwires(importer, patches, recorder)

        version_module = importer("utils.version_checker")
        _assert_module_from_sandbox(version_module, sandbox)
        if not callable(getattr(version_module, "get_latest_remote_version", None)):
            raise ProofSetupError("version update check entry point is unavailable")

        def update_check_stub(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            recorder.record_update_check()
            return None

        patches.set(version_module, "get_latest_remote_version", update_check_stub)

        web_module = importer("web.web_interface")
        _assert_module_from_sandbox(web_module, sandbox)
        main_module = getattr(web_module, "dm_main", None)
        if main_module is None:
            raise ProofSetupError("web interface main module is unavailable")
        _assert_module_from_sandbox(main_module, sandbox)
        if not callable(getattr(main_module, "get_ai_response", None)):
            raise ProofSetupError("main AI response entry point is unavailable")

        def main_response_tripwire(*args: Any, **kwargs: Any) -> None:
            recorder.block_provider_function(*args, **kwargs)

        patches.set(main_module, "get_ai_response", main_response_tripwire)

        campaign_module = importer("core.managers.campaign_manager")
        _assert_module_from_sandbox(campaign_module, sandbox)
        campaign_manager_class = getattr(campaign_module, "CampaignManager", None)
        if campaign_manager_class is None:
            raise ProofSetupError("CampaignManager is unavailable")
        if getattr(campaign_manager_class, "_module_scan_attempted", None) is not False:
            raise ProofSetupError(
                "CampaignManager module scan was attempted during host import"
            )

        stitcher_module = importer("core.generators.module_stitcher")
        _assert_module_from_sandbox(stitcher_module, sandbox)
        stitcher_router = getattr(stitcher_module, "llm", None)
        if stitcher_router is None or not callable(
            getattr(stitcher_router, "call", None)
        ):
            raise ProofSetupError("ModuleStitcher LLM call entry point is unavailable")
        patches.set(
            stitcher_module,
            "llm",
            SimpleNamespace(call=recorder.module_stitcher_call),
        )
        registry_writer = getattr(stitcher_module, "safe_json_dump", None)
        if not callable(registry_writer):
            raise ProofSetupError("ModuleStitcher registry writer is unavailable")
        _normalize_registry_for_integration(sandbox, registry_writer)

        egress_guard.assert_active()
        campaign_manager_class()
        if getattr(campaign_manager_class, "_module_scan_attempted", None) is not True:
            raise ProofSetupError("CampaignManager did not attempt its startup module scan")
        integration_completed = True

        egress_guard.assert_active()
        try:
            inspected = _inspect_capture_seed(sandbox)
            seed_checks = inspected["checks"]
            registered_modules = inspected["registered_modules"]
            detected_modules = inspected["detect_new_modules_after"]
            active_combat_encounter = inspected["active_combat_encounter_after"]
        except (OSError, ValueError, ProofSetupError) as exc:
            if (
                isinstance(exc, ProofSetupError)
                and str(exc) == "world registry is unavailable after integration"
            ):
                inspection_failure_reason = _exception_blocked_reason(exc)
            else:
                blocked = True
                blocked_reason = _exception_blocked_reason(exc)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, (EgressBlocked, ProviderCallBlocked)):
            blocked = False
        else:
            blocked = True
            if blocked_reason is None:
                blocked_reason = _exception_blocked_reason(exc)
    finally:
        router_calls, provider_calls, update_check_calls = recorder.snapshot()
        if ledger_path is not None:
            try:
                ledger_reservations = _ledger_reservation_count(ledger_path)
                ledger_valid = True
            except Exception:
                ledger_valid = False
            try:
                _remove_owned_ledger(
                    ledger_path,
                    ledger_created_by_tool,
                    ledger_identity,
                    sandbox if sandbox is not None else ledger_path.parents[2],
                )
            except OSError:
                ledger_valid = False
        patches.restore()
        egress_guard.restore()
        for name, previous in original_env.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        if context_changed:
            os.chdir(original_cwd)
            sys.path[:] = original_sys_path

    if (
        not integration_completed
        and not blocked
        and not router_calls
        and not provider_calls
        and not egress_guard.snapshot()
    ):
        blocked = True
        blocked_reason = blocked_reason or (
            "RuntimeError: module integration did not complete"
        )

    egress_refusals, egress_refusal_count = egress_guard.refusal_snapshot()
    report = build_preintegrate_report(
        stub_call_counts=recorder.stub_counts_snapshot(),
        egress_attempts=egress_guard.snapshot(),
        egress_refusals=egress_refusals,
        egress_refusal_count=egress_refusal_count,
        registered_modules=registered_modules,
        detect_new_modules_after=detected_modules,
        active_combat_encounter_after=active_combat_encounter,
        seed_checks=seed_checks,
        router_calls=router_calls,
        provider_function_calls=provider_calls,
        update_check_calls=update_check_calls,
        ledger_reservations=ledger_reservations,
        ledger_valid=ledger_valid,
        blocked=blocked,
        blocked_reason=blocked_reason,
        inspection_failure_reason=inspection_failure_reason,
    )
    _atomic_write_report(report_path, report)
    return report


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Run these as separate process invocations, in this order:\n"
            "  PYTHONPATH=. .venv/bin/python scripts/n3_start_game_offline_proof.py --mode preintegrate\n"
            "  PYTHONPATH=. .venv/bin/python scripts/n3_start_game_offline_proof.py --mode prove\n"
            "  For the N3 pinned narration check, add --expect-startup-narration --require-priced-route."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=(
            "prove",
            "preintegrate",
            "startup-diagnostic",
        ),
        default="prove",
        help=(
            "prove runs the start_game proof (default); preintegrate runs the "
            "offline module scan/integration; startup-diagnostic traces the actual "
            "start_game path with bounded offline router stubs. Run preintegrate "
            "and prove as separate process invocations."
        ),
    )
    parser.add_argument("--sandbox-root", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--output-dir",
        help=(
            "report directory or JSON path (default directory: "
            "tmp/router-rollout/v2-network/n3/start-game-proof/<run-id>/); "
            "prove writes proof.json and preintegrate writes preintegrate.json"
        ),
    )
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--settle-seconds", type=float, default=20.0)
    parser.add_argument(
        "--diagnostic-call-limit",
        type=int,
        default=DEFAULT_DIAGNOSTIC_CALL_LIMIT,
        help="maximum router/provider observations for startup-diagnostic (2-16)",
    )
    parser.add_argument(
        "--diagnostic-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--expect-startup-narration",
        action="store_true",
        help="require one startup dm_main narration request, intercepted before provider use",
    )
    parser.add_argument(
        "--require-priced-route",
        action="store_true",
        help="require a priced n3-luna dm_main route and an estimate within the USD 0.05 run cap",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "preintegrate" and (
        args.expect_startup_narration or args.require_priced_route
    ):
        parser.error("startup narration route expectations apply only with --mode prove")
    if args.mode == "startup-diagnostic" and (
        args.expect_startup_narration or args.require_priced_route
    ):
        parser.error("startup narration route expectations cannot be combined with the diagnostic")
    if args.diagnostic_worker and args.mode != "startup-diagnostic":
        parser.error("--diagnostic-worker requires --mode startup-diagnostic")
    if not 2 <= args.diagnostic_call_limit <= MAX_DIAGNOSTIC_CALLS:
        parser.error("--diagnostic-call-limit must be between 2 and 16")
    if args.self_test and (args.expect_startup_narration or args.require_priced_route):
        parser.error("startup narration route expectations cannot be combined with --self-test")
    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if args.self_test:
        result = run_guard_self_test()
        sys.__stdout__.write(
            json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n"
        )
        return 0 if result["verdict"] == "PASS" else 1

    self_test = run_guard_self_test()
    if self_test["verdict"] != "PASS":
        sys.__stdout__.write(
            json.dumps(
                {
                    "verdict": "BLOCKED",
                    "reason": "provider and egress guard self-test failed",
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            + "\n"
        )
        return 1
    try:
        if args.mode == "preintegrate":
            report = run_preintegrate(
                sandbox_root=args.sandbox_root,
                run_id=args.run_id,
                output_dir=args.output_dir,
            )
        elif args.mode == "startup-diagnostic":
            report_path = resolve_startup_diagnostic_output_file(
                args.output_dir, args.run_id
            )
            if report_path.exists() or report_path.is_symlink():
                raise ProofSetupError(
                    "startup diagnostic report path already exists; choose a new run ID"
                )
            if args.diagnostic_worker:
                report = run_startup_diagnostic(
                    sandbox_root=args.sandbox_root,
                    run_id=args.run_id,
                    output_dir=args.output_dir,
                    startup_timeout=args.startup_timeout,
                    diagnostic_call_limit=args.diagnostic_call_limit,
                    isolated_worker=True,
                )
            else:
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--mode",
                    "startup-diagnostic",
                    "--diagnostic-worker",
                    "--sandbox-root",
                    str(args.sandbox_root),
                    "--run-id",
                    args.run_id,
                    "--startup-timeout",
                    str(args.startup_timeout),
                    "--diagnostic-call-limit",
                    str(args.diagnostic_call_limit),
                ]
                if args.output_dir is not None:
                    command.extend(("--output-dir", str(args.output_dir)))
                try:
                    child = subprocess.run(
                        command,
                        cwd=REPO_ROOT,
                        env=_startup_diagnostic_worker_environment(),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=(
                            args.startup_timeout
                            + STARTUP_DIAGNOSTIC_SHUTDOWN_SECONDS
                            + 10.0
                        ),
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    report = _startup_diagnostic_report(
                        call_events=[],
                        stub_call_counts={},
                        router_calls=0,
                        provider_calls=0,
                        network_attempts=0,
                        ledger_reservations=None,
                        ledger_valid=False,
                        startup_output_delivered=False,
                        game_started=False,
                        startup_thread_stopped=False,
                        diagnostic_failure="startup diagnostic worker exceeded its process bound",
                        call_overflow=False,
                        router_call_guard=False,
                        router_decide_guard=False,
                        sdk_tripwire_count=0,
                        egress_guard_active=False,
                    )
                    _atomic_write_report(report_path, report)
                else:
                    if not report_path.is_file() or report_path.is_symlink():
                        report = _startup_diagnostic_report(
                            call_events=[],
                            stub_call_counts={},
                            router_calls=0,
                            provider_calls=0,
                            network_attempts=0,
                            ledger_reservations=None,
                            ledger_valid=False,
                            startup_output_delivered=False,
                            game_started=False,
                            startup_thread_stopped=False,
                            diagnostic_failure=(
                                "startup diagnostic worker did not produce a report"
                                if child.returncode == 0
                                else "startup diagnostic worker failed before reporting"
                            ),
                            call_overflow=False,
                            router_call_guard=False,
                            router_decide_guard=False,
                            sdk_tripwire_count=0,
                            egress_guard_active=False,
                        )
                        _atomic_write_report(report_path, report)
                    else:
                        if report_path.stat().st_size > 1024 * 1024:
                            raise ProofSetupError("startup diagnostic report size bound exceeded")
                        with open(report_path, "r", encoding="ascii") as stream:
                            report = json.load(stream)
                        if not isinstance(report, dict) or report.get("verdict") not in (
                            "PASS",
                            "BLOCKED",
                        ) or (
                            report.get("verdict") == "PASS"
                            and report.get("egress_refusal_coverage_complete") is not True
                        ):
                            raise ProofSetupError("startup diagnostic report is invalid")
        else:
            report = run_proof(
                sandbox_root=args.sandbox_root,
                run_id=args.run_id,
                output_dir=args.output_dir,
                startup_timeout=args.startup_timeout,
                settle_seconds=args.settle_seconds,
                preserve_runtime_guards=True,
                expect_startup_narration=args.expect_startup_narration,
                require_priced_route=args.require_priced_route,
            )
    except Exception as exc:
        sys.__stdout__.write(
            json.dumps(
                {
                    "verdict": "BLOCKED",
                    "reason": "offline report could not be written (" + type(exc).__name__ + ")",
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            + "\n"
        )
        return 1
    sys.__stdout__.write(
        json.dumps(
            {"verdict": report["verdict"], "reason": report["reason"]},
            ensure_ascii=True,
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
