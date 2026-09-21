# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free output boundary for the explicit adaptation lane.

The boundary is deliberately opt-in.  It provides projections for the output
surfaces that later adaptation wiring can use, without changing provider
requests or legacy logging when no :class:`AdaptationOutputSafety` scope is
active.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import threading
from typing import Any, Callable, Dict, Mapping, Optional, TextIO


ADAPTATION_MODE = "llm_adaptation"
SAFETY_CONTRACT_VERSION = "toolkit_adaptation_output_safety.v1"
MAX_MESSAGE_CHARS = 240
MAX_CODE_CHARS = 120
MAX_STAGE_CHARS = 120
MAX_EVENT_CHARS = 2_000
MAX_DIAGNOSTIC_CHARS = 240
MAX_TAIL_CHARS = 1_200
MAX_ATTEMPT = 1_000_000
MAX_REVISION = 100
MAX_COUNT = 2_000_000_000

ADAPTATION_PHASES = frozenset(
    {
        "adaptation_preflight", "adaptation_source_context", "adaptation_authoring",
        "adaptation_staging", "adaptation_build", "adaptation_validation",
        "adaptation_readiness", "adaptation_semantic_audit", "adaptation_revision",
        "adaptation_revision_build", "adaptation_report", "adaptation_markdown",
        "adaptation_registry", "adaptation_campaign_sync", "adaptation_rollback",
        "adaptation_completed", "adaptation_revision_exhausted",
        "adaptation_infrastructure_failed", "adaptation_blocked",
    }
)
ADAPTATION_STATUSES = frozenset(
    {"queued", "running", "in_progress", "pass", "completed", "blocked", "failed", "error", "degraded"}
)
_DEFAULT_STAGE = "adaptation_build"
_DEFAULT_STATUS = "running"
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,_:/()@+'\[\]-]{0,239}$")
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp|var|private|opt|etc)/|\\\\)")
_CREDENTIAL = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|credential|password|secret|token|private[_ -]?key)\s*[:=]?\s*[^\s,;]+"
)
_SENSITIVE_WORD = re.compile(
    r"(?i)(?:full[_ -]?(?:source|prompt|response)|source[_ -]?(?:context|content|text)|"
    r"provider[_ -]?(?:payload|response)|request[_ -]?body|response[_ -]?body|headers?|"
    r"(?:stdout|stderr)(?:[_ -]?(?:tail|line|output|sentinel|marker))?|"
    r"lock[_ -]?(?:path|file|sentinel|marker)?)"
)
_SENTINEL_WORD = re.compile(r"(?i)(?:source|prompt|provider|response)[_-]?(?:sentinel|fixture|payload|context|text|body)")
_KEY_TOKEN = re.compile(r"(?i)\b(?:sk|rk|pk|key)[_-][a-z0-9][a-z0-9._-]{5,}")
_REDACTION = "[REDACTED]"
_SUPPRESSED = "unsafe diagnostic suppressed"
_ACTIVE_SCOPE: contextvars.ContextVar[Optional["AdaptationOutputSafety"]] = contextvars.ContextVar(
    "neq_adaptation_output_safety", default=None
)
# ContextVars intentionally do not cross ``threading.Thread`` boundaries.
# Adaptation packet builds can create provider/application loggers in worker
# threads, so keep a process-local, identity-based scope registry as the
# emission fallback.  It is only populated by the explicit adaptation scope;
# legacy callers therefore retain their existing logging behavior.
_GLOBAL_SCOPE_LOCK = threading.RLock()
_GLOBAL_SCOPES = []
_RECORD_FACTORY_MARKER = "_neq_adaptation_output_safety_factory"
_PROVIDER_LOG_ROOTS = ("openai", "httpx", "httpcore")
_PROVIDER_FIELD_NAMES = frozenset(
    {
        "messages", "json", "json_data", "request", "request_body",
        "request_content", "response", "response_body", "response_content",
        "headers", "authorization", "api_key", "apikey", "bearer",
        "credential", "credentials", "token", "password", "secret",
        "request_id", "payload", "raw",
    }
)
_PROVIDER_TEXT_MARKERS = re.compile(
    r"(?i)(?:authorization|bearer|request[_ -]?(?:body|content)|response[_ -]?(?:body|content)|"
    r"json[_ -]?data|prompt|source[_ -]?(?:context|content|text)|provider[_ -]?(?:payload|response)|"
    r"request[_ -]?id|headers?)"
)
_ADAPTATION_RECORD_FIELDS = frozenset(
    {
        "phase", "status", "code", "count", "percentage", "attempt", "revision",
    }
)
_LOG_RECORD_FIELDS = frozenset(logging.LogRecord(None, 0, "", 0, "", (), None).__dict__)


def _bounded_int(value: Any, maximum: int) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, min(value, maximum))


def _safe_token(value: Any, default: str, *, limit: int = MAX_CODE_CHARS) -> str:
    if not isinstance(value, str):
        return default
    candidate = "_".join(value.strip().lower().split())[:limit]
    return candidate if _SAFE_TOKEN.fullmatch(candidate) else default


def sanitize_message(value: Any, limit: int = MAX_MESSAGE_CHARS) -> str:
    """Return a deterministic ASCII diagnostic, never a raw payload."""
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return ""
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    if not text:
        return ""
    if _ABSOLUTE_PATH.search(text) or _SENSITIVE_WORD.search(text) or _SENTINEL_WORD.search(text):
        return _SUPPRESSED
    text = _CREDENTIAL.sub(_REDACTION, text)
    text = _KEY_TOKEN.sub(_REDACTION, text)
    text = text.encode("ascii", "replace").decode("ascii")
    if not _SAFE_TEXT.fullmatch(text):
        return _SUPPRESSED
    if len(text) > limit:
        text = text[: max(0, limit - 12)].rstrip() + " [truncated]"
    return text


def redact_diagnostic_text(value: Any, limit: int = MAX_DIAGNOSTIC_CHARS) -> str:
    """Return a bounded diagnostic projection, never an exception/payload dump.

    This helper is intentionally stricter than ordinary status text.  It is
    used at persistence boundaries where callers may pass exception objects,
    provider failures, or subprocess output.  Structured values are replaced
    rather than stringified, and sensitive-looking text is reduced to one
    stable marker so equivalent failures remain deterministic.
    """
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return ""
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    if not text:
        return ""
    safe = sanitize_message(text, limit=limit)
    return safe or _SUPPRESSED


def project_diagnostic_tail(value: Any, *, stream: str = "stdout", limit: int = MAX_TAIL_CHARS) -> str:
    """Project a raw stdout/stderr tail into a bounded safe diagnostic.

    Tails are compatibility fields, not debugging storage.  Keep only safe
    line projections and replace unsafe lines with a stable code; never copy
    the original tail wholesale.
    """
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple, set)):
        return "unsafe diagnostic suppressed"
    lines = str(value).splitlines() or [str(value)]
    projected = []
    for line in lines[-64:]:
        safe = redact_diagnostic_text(line, MAX_DIAGNOSTIC_CHARS)
        if safe:
            projected.append(safe)
    result = " | ".join(projected)
    if len(result) > limit:
        result = result[: max(0, limit - 12)].rstrip() + " [truncated]"
    return result


def project_persisted_diagnostic(payload: Any) -> Dict[str, Any]:
    """Build the canonical safe projection for persisted adaptation errors."""
    data = payload if isinstance(payload, Mapping) else {}
    event = project_diagnostic(data)
    for key in ("stdout_tail", "stderr_tail"):
        if key in data:
            event[key] = project_diagnostic_tail(data.get(key), stream=key[:-5])
    for key in ("exception", "provider_failure", "provider_error", "error"):
        if key in data and data.get(key) not in (None, ""):
            safe = redact_diagnostic_text(data.get(key))
            if safe:
                event[key] = safe
    event["raw_provider_payload_exposed"] = False
    encoded = json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_EVENT_CHARS:
        for key in ("stdout_tail", "stderr_tail", "exception", "provider_failure", "provider_error", "error"):
            if key in event:
                event[key] = _SUPPRESSED
    return event


def _active() -> Optional["AdaptationOutputSafety"]:
    scoped = _ACTIVE_SCOPE.get()
    if scoped is not None:
        return scoped
    with _GLOBAL_SCOPE_LOCK:
        return _GLOBAL_SCOPES[-1] if _GLOBAL_SCOPES else None


def _is_provider_shaped_record(record: logging.LogRecord, message: str = "") -> bool:
    name = getattr(record, "name", "")
    if any(name == root or name.startswith(root + ".") for root in _PROVIDER_LOG_ROOTS):
        return True
    if _PROVIDER_FIELD_NAMES.intersection(record.__dict__):
        return True
    return bool(_PROVIDER_TEXT_MARKERS.search(message or ""))


def _sanitize_adaptation_record(record: logging.LogRecord) -> logging.LogRecord:
    """Sanitize a record at creation/format time, including late ``extra`` fields."""
    scope = _active()
    if scope is None:
        return record
    if getattr(record, "_neq_adaptation_record_sanitized", False):
        return record

    try:
        original_message = logging.LogRecord.getMessage(record)
    except Exception:
        original_message = ""
    provider_shaped = _is_provider_shaped_record(record, original_message)
    if provider_shaped:
        event = project_safe_event(
            phase=getattr(record, "phase", scope.phase),
            status=getattr(record, "status", scope.status),
            code="provider_payload_suppressed",
            message=None,
            event_type="adaptation_log",
        )
    else:
        event = project_safe_event(
            phase=getattr(record, "phase", scope.phase),
            status=getattr(record, "status", scope.status),
            code="application_log",
            message=original_message,
            event_type="adaptation_log",
        )
    record.msg = json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    record.args = ()
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    # A formatter may request pathname/filename or arbitrary ``extra`` fields.
    # Replace those values too, before any late handler gets the record.
    record.pathname = "<adaptation>"
    record.filename = "<adaptation>"
    record.module = "<adaptation>"
    record.funcName = "<adaptation>"
    for field in tuple(record.__dict__):
        if field in _LOG_RECORD_FIELDS or field in _ADAPTATION_RECORD_FIELDS:
            continue
        if field.startswith("_"):
            continue
        record.__dict__[field] = _REDACTION
    record._neq_adaptation_record_sanitized = True
    return record


class _AdaptationLogRecord(logging.LogRecord):
    """LogRecord wrapper that sanitizes after ``Logger.makeRecord`` adds extras."""

    def __init__(self, original: logging.LogRecord) -> None:
        self.__dict__.update(original.__dict__)

    def getMessage(self) -> str:
        _sanitize_adaptation_record(self)
        return logging.LogRecord.getMessage(self)


def _install_adaptation_record_factory() -> None:
    """Install one inert-outside-scope factory for late handlers and extras."""
    current = logging.getLogRecordFactory()
    if getattr(current, _RECORD_FACTORY_MARKER, False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = _AdaptationLogRecord(current(*args, **kwargs))
        # Sanitize immediately, rather than waiting for a formatter.  This
        # covers late root/application handlers and custom handlers that read
        # ``record.msg`` directly, including records made on worker threads.
        if _active() is not None:
            _sanitize_adaptation_record(record)
        return record

    setattr(factory, _RECORD_FACTORY_MARKER, True)
    logging.setLogRecordFactory(factory)


def is_adaptation_output_active() -> bool:
    """Return whether the current execution context opted into the boundary."""
    return _active() is not None


def project_safe_event(
    *,
    phase: Any = None,
    status: Any = None,
    code: Any = None,
    message: Any = None,
    count: Any = None,
    percentage: Any = None,
    attempt: Any = None,
    revision: Any = None,
    event_type: str = "adaptation_status",
) -> Dict[str, Any]:
    """Build the canonical bounded event used by all adaptation projections."""
    safe_phase = _safe_token(phase, _DEFAULT_STAGE)
    if safe_phase not in ADAPTATION_PHASES:
        safe_phase = _DEFAULT_STAGE
    safe_status = _safe_token(status, _DEFAULT_STATUS)
    if safe_status not in ADAPTATION_STATUSES:
        safe_status = _DEFAULT_STATUS
    safe_code = _safe_token(code, "unclassified")
    event: Dict[str, Any] = {
        "contract_version": SAFETY_CONTRACT_VERSION,
        "event_type": _safe_token(event_type, "adaptation_status"),
        "phase": safe_phase,
        "status": safe_status,
        "code": safe_code,
    }
    safe_message = sanitize_message(message)
    if safe_message:
        event["message"] = safe_message
    safe_count = _bounded_int(count, MAX_COUNT)
    if safe_count is not None:
        event["count"] = safe_count
    if isinstance(percentage, (int, float)) and not isinstance(percentage, bool):
        event["percentage"] = max(0.0, min(float(percentage), 100.0))
    safe_attempt = _bounded_int(attempt, MAX_ATTEMPT)
    if safe_attempt is not None:
        event["attempt"] = safe_attempt
    safe_revision = _bounded_int(revision, MAX_REVISION)
    if safe_revision is not None:
        event["revision"] = safe_revision
    event["raw_provider_payload_exposed"] = False
    encoded = json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_EVENT_CHARS:
        event.pop("message", None)
        event["message"] = _SUPPRESSED
    return event


def project_progress(payload: Any) -> Dict[str, Any]:
    """Project a callback payload into the canonical safe progress event."""
    data = payload if isinstance(payload, Mapping) else {}
    return project_safe_event(
        phase=data.get("phase", data.get("stage")), status=data.get("status"),
        code=data.get("code", data.get("failure_code", data.get("reason_code"))),
        message=data.get("message", data.get("progress_message")), count=data.get("count"),
        percentage=data.get("percentage"), attempt=data.get("attempt", data.get("attempt_number")),
        revision=data.get("revision", data.get("revision_number")),
        event_type="adaptation_progress",
    )


def project_gui_payload(payload: Any) -> Dict[str, Any]:
    """Return the safe GUI/progress projection, including no arbitrary keys."""
    event = project_progress(payload)
    event["raw_provider_payload_exposed"] = False
    return event


def project_diagnostic(payload: Any) -> Dict[str, Any]:
    """Return a safe persisted diagnostic projection (never a raw tail)."""
    event = project_progress(payload)
    event["event_type"] = "adaptation_diagnostic"
    return event


def sanitize_line(line: Any, *, stream: str = "stdout") -> Optional[Dict[str, Any]]:
    """Convert one captured line to a safe event; inactive scopes pass through."""
    scope = _active()
    if scope is None:
        return None
    return project_safe_event(
        phase=scope.phase, status=scope.status, code="captured_output_suppressed",
        message=line, event_type="adaptation_" + ("stderr" if stream == "stderr" else "stdout"),
    )


def emit_adaptation_telemetry(
    *,
    phase: Any = "adaptation_build",
    status: Any = "running",
    code: Any = "generator_progress",
    message: Any = None,
    count: Any = None,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Emit one bounded generator event without exposing generator payloads.

    ``force`` is used by explicit adaptation generator paths when a caller has
    selected adaptation mode but has not installed stream redirection.  The
    legacy path never calls this helper, so its diagnostics remain unchanged.
    """
    scope = _active()
    if scope is not None:
        return scope.emit(
            project_safe_event(
                phase=phase, status=status, code=code, message=message, count=count
            )
        )
    if not force:
        return None
    event = project_safe_event(
        phase=phase, status=status, code=code, message=message, count=count
    )
    print(json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return event


class AdaptationOutputSafetyFilter(logging.Filter):
    """Sanitize a log record only while an adaptation scope is active."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _active() is None:
            return True
        _sanitize_adaptation_record(record)
        return True


class _SafeStream:
    def __init__(self, target: TextIO, stream: str, scope: "AdaptationOutputSafety") -> None:
        self._target, self._stream, self._scope = target, stream, scope

    def write(self, value: str) -> int:
        if value and value.strip():
            safe = self._scope.emit(sanitize_line(value, stream=self._stream))
            self._target.write(json.dumps(safe, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
        return len(value)

    def flush(self) -> None:
        self._target.flush()


class AdaptationOutputSafety:
    """Explicit, nestable adaptation-only output scope.

    ``progress_callback`` receives only canonical safe events.  Stream
    redirection is opt-in so merely constructing the context cannot affect
    existing workers or legacy CLI diagnostics.
    """

    def __init__(
        self, *, phase: Any = None, status: Any = None, progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        gui_callback: Optional[Callable[[Dict[str, Any]], Any]] = None, redirect_streams: bool = False,
    ) -> None:
        self.phase = project_safe_event(phase=phase, status=status)["phase"]
        self.status = project_safe_event(phase=phase, status=status)["status"]
        self.progress_callback = progress_callback
        self.gui_callback = gui_callback
        self.redirect_streams = redirect_streams
        self._token = None
        self._stdout = self._stderr = None

    def __enter__(self) -> "AdaptationOutputSafety":
        self._token = _ACTIVE_SCOPE.set(self)
        with _GLOBAL_SCOPE_LOCK:
            _GLOBAL_SCOPES.append(self)
        _install_adaptation_record_factory()
        self._logger_filter = AdaptationOutputSafetyFilter()
        self._filtered_handlers = []
        # Handler filters are scoped to this context.  This keeps legacy
        # logging untouched while preventing existing application/provider
        # handlers from receiving raw adaptation records.
        try:
            root = logging.getLogger()
            for handler in list(root.handlers):
                handler.addFilter(self._logger_filter)
                self._filtered_handlers.append(handler)
        except Exception:
            self._filtered_handlers = []
        if self.redirect_streams:
            self._stdout, self._stderr = sys.stdout, sys.stderr
            sys.stdout = _SafeStream(self._stdout, "stdout", self)  # type: ignore[assignment]
            sys.stderr = _SafeStream(self._stderr, "stderr", self)  # type: ignore[assignment]
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._stdout is not None:
            sys.stdout, sys.stderr = self._stdout, self._stderr
        for handler in getattr(self, "_filtered_handlers", []):
            try:
                handler.removeFilter(self._logger_filter)
            except Exception:
                pass
        with _GLOBAL_SCOPE_LOCK:
            # Remove by identity so nested scopes and an out-of-order cleanup
            # cannot accidentally deactivate another active adaptation build.
            for index in range(len(_GLOBAL_SCOPES) - 1, -1, -1):
                if _GLOBAL_SCOPES[index] is self:
                    del _GLOBAL_SCOPES[index]
                    break
        if self._token is not None:
            _ACTIVE_SCOPE.reset(self._token)

    def emit(self, event: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        safe = project_progress(event or {})
        for callback in (self.progress_callback, self.gui_callback):
            if callback is not None:
                try:
                    callback(dict(safe))
                except Exception:
                    pass
        return safe

    def diagnostic(self, payload: Any) -> Dict[str, Any]:
        return project_diagnostic(payload)


__all__ = [
    "ADAPTATION_PHASES", "ADAPTATION_STATUSES", "AdaptationOutputSafety",
    "AdaptationOutputSafetyFilter", "is_adaptation_output_active",
    "project_diagnostic", "project_diagnostic_tail", "project_gui_payload", "project_persisted_diagnostic", "project_progress",
    "project_safe_event", "sanitize_line", "sanitize_message",
    "redact_diagnostic_text",
    "emit_adaptation_telemetry",
]
