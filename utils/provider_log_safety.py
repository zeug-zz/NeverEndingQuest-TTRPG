# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Defensive logging policy for third-party AI provider transports.

This module deliberately has no provider SDK dependency.  It suppresses
transport DEBUG records and sanitizes provider-shaped records that are allowed
through at WARNING or ERROR level.  The policy changes logging records only;
it never changes provider request objects.
"""

import logging
import math
import re
import threading
from typing import Any, Dict, Iterable, Optional


_PROVIDER_LOGGERS = ("openai", "httpx", "httpcore")
_SENSITIVE_FIELDS = {
    "messages",
    "json_data",
    "json",
    "request",
    "request_body",
    "request_content",
    "body",
    "response",
    "response_body",
    "response_content",
    "authorization",
    "api_key",
    "apikey",
    "bearer",
    "credential",
    "credentials",
    "token",
    "password",
    "secret",
}
_SAFE_FIELDS = {
    "provider",
    "model",
    "event",
    "stage",
    "status",
    "elapsed",
    "elapsed_ms",
    "retry",
    "retry_count",
    "fallback",
    "request_id",
}
_REDACTED = "[REDACTED]"
_PAYLOAD_MARKER = "[PROVIDER_PAYLOAD_REDACTED]"
_CONFIG_LOCK = threading.RLock()
_FILTER_MARKER = "_neq_provider_log_safety_filter"
_ADAPTATION_RECORD_MARKER = "_neq_adaptation_record_sanitized"
_SAFE_DIAGNOSTIC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
_SAFE_DIAGNOSTIC_LOGGER = "NeverEndingQuest.provider_diagnostics"


def _is_provider_logger(name: str) -> bool:
    return any(name == root or name.startswith(root + ".") for root in _PROVIDER_LOGGERS)


def _bounded_safe_value(value: Any) -> Any:
    """Keep diagnostics small and scalar without exposing arbitrary payloads."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value if not isinstance(value, str) else value[:120]
        return text
    return _REDACTED


def _safe_diagnostic_identifier(value: Any, default: str = "unknown") -> str:
    """Return an allowlisted diagnostic identifier, never arbitrary text."""
    if not isinstance(value, str):
        return default
    candidate = value.strip()[:96]
    return candidate if _SAFE_DIAGNOSTIC_RE.fullmatch(candidate) else default


def _safe_request_id(value: Any) -> str:
    """Keep only provider request identifiers, not request metadata."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip()[:96]
    return candidate if _SAFE_REQUEST_ID_RE.fullmatch(candidate) else ""


def build_provider_diagnostic(
    *,
    provider: Any,
    model: Any,
    stage: Any,
    status: Any,
    elapsed_ms: Any = None,
    retry: Any = False,
    fallback: Any = False,
    request_id: Any = None,
) -> Dict[str, Any]:
    """Build a bounded provider event without accepting payload-like values.

    This is deliberately an event-shaped helper rather than an exception or
    request serializer.  Invalid free-form values become ``unknown`` (or are
    omitted for optional fields), so callers cannot accidentally put prompts,
    source excerpts, credentials, or provider bodies into diagnostics.
    """
    safe_elapsed = 0
    if isinstance(elapsed_ms, (int, float)) and not isinstance(elapsed_ms, bool):
        if math.isfinite(float(elapsed_ms)):
            safe_elapsed = max(0, min(int(elapsed_ms), 86_400_000))
    diagnostic: Dict[str, Any] = {
        "event": "provider_diagnostic",
        "provider": _safe_diagnostic_identifier(provider),
        "model": _safe_diagnostic_identifier(model),
        "stage": _safe_diagnostic_identifier(stage),
        "status": _safe_diagnostic_identifier(status),
        "elapsed_ms": safe_elapsed,
        "retry": bool(retry) if isinstance(retry, bool) else False,
        "fallback": bool(fallback) if isinstance(fallback, bool) else False,
    }
    safe_id = _safe_request_id(request_id)
    if safe_id:
        diagnostic["request_id"] = safe_id
    return diagnostic


def log_provider_diagnostic(
    diagnostic: Dict[str, Any],
    *,
    logger: Optional[logging.Logger] = None,
    level: int = logging.INFO,
) -> Dict[str, Any]:
    """Log only a previously bounded provider diagnostic event.

    The message is static and the event is rebuilt through the allowlisted
    shape before logging.  In particular, this helper never accepts or logs
    exception text, request data, or response data.
    """
    if not isinstance(diagnostic, dict):
        diagnostic = {}
    safe = build_provider_diagnostic(
        provider=diagnostic.get("provider"),
        model=diagnostic.get("model"),
        stage=diagnostic.get("stage"),
        status=diagnostic.get("status"),
        elapsed_ms=diagnostic.get("elapsed_ms"),
        retry=diagnostic.get("retry"),
        fallback=diagnostic.get("fallback"),
        request_id=diagnostic.get("request_id"),
    )
    target = logger or logging.getLogger(_SAFE_DIAGNOSTIC_LOGGER)
    target.log(level, "Provider diagnostic event", extra=safe)
    return safe


def sanitize_provider_log_record(record: logging.LogRecord) -> logging.LogRecord:
    """Sanitize a provider-shaped record in place and return it.

    Mutating the ``LogRecord`` is intentional and safe.  Values held by a
    provider request object are not traversed or modified; only logging data
    copied into the record is replaced.

    Adaptation output records are already canonical safe projections.  They
    can pass through a late provider/root handler filter after the adaptation
    record factory has run, so preserve that projection rather than replacing
    its bounded event code with the generic provider redaction marker.
    """
    if getattr(record, _ADAPTATION_RECORD_MARKER, False):
        return record
    if not _is_provider_logger(record.name):
        return record

    safe_values: Dict[str, Any] = {}
    for field in _SAFE_FIELDS:
        if field in record.__dict__:
            safe_values[field] = _bounded_safe_value(record.__dict__[field])

    record.msg = _PAYLOAD_MARKER
    record.args = ()
    for field in _SENSITIVE_FIELDS:
        if field in record.__dict__:
            record.__dict__[field] = _REDACTED

    # Remove arbitrary provider payload extras while retaining bounded
    # operational metadata.  Standard LogRecord fields are never removed.
    for field in tuple(record.__dict__):
        if field.startswith("_") or field in _SAFE_FIELDS:
            continue
        if field in _SENSITIVE_FIELDS or field in {"raw", "payload", "data", "headers"}:
            record.__dict__[field] = _REDACTED

    for field, value in safe_values.items():
        setattr(record, field, value)
    return record


class ProviderLogRedactionFilter(logging.Filter):
    """Logging filter that sanitizes records from provider logger paths."""

    def filter(self, record: logging.LogRecord) -> bool:
        sanitize_provider_log_record(record)
        return True


def _iter_provider_loggers() -> Iterable[logging.Logger]:
    manager = logging.Logger.manager
    names = set(_PROVIDER_LOGGERS)
    names.update(
        name for name in manager.loggerDict
        if _is_provider_logger(name)
    )
    for name in sorted(names):
        yield logging.getLogger(name)


def _install_filter_once(target: Any, redaction_filter: ProviderLogRedactionFilter) -> None:
    filters = getattr(target, "filters", ())
    if not any(getattr(item, _FILTER_MARKER, False) for item in filters):
        setattr(redaction_filter, _FILTER_MARKER, True)
        target.addFilter(redaction_filter)


def configure_provider_log_safety() -> bool:
    """Apply the provider logging policy once, safely and idempotently.

    Provider transport loggers retain warnings and errors but do not emit
    DEBUG or INFO payload records.  Existing handlers are also filtered so a
    directly attached child handler receives sanitized records.
    """
    with _CONFIG_LOCK:
        redaction_filter = ProviderLogRedactionFilter()
        for logger in _iter_provider_loggers():
            logger.setLevel(logging.WARNING)
            _install_filter_once(logger, redaction_filter)
            for handler in tuple(logger.handlers):
                _install_filter_once(handler, redaction_filter)

        # Root handlers receive propagated provider records.  The filter is a
        # no-op for non-provider records, preserving application categories.
        root = logging.getLogger()
        for handler in tuple(root.handlers):
            _install_filter_once(handler, redaction_filter)
    return True


__all__ = [
    "ProviderLogRedactionFilter",
    "build_provider_diagnostic",
    "configure_provider_log_safety",
    "log_provider_diagnostic",
    "sanitize_provider_log_record",
]
