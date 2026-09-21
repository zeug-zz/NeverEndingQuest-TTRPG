# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider Response Recovery - Bounded Empty Chat Completion Recovery

Classifies Chat Completions responses into explicit failure classes and
retries only empty transient completions within a bounded limit. Every
attempt forwards identical messages, timeout, and resolved request
parameters.

This module owns request-execution recovery only:
- It never constructs provider clients (client construction stays in
  utils.ai_client_factory).
- It never imports runtime configuration (config / model_config) at module
  import time.
- It never mutates model configuration, parameter resolution, or any global
  state.

Diagnostics are bounded, ASCII-only, and payload-free: they never log prompt
text, raw provider payloads, request bodies, or credentials, and a logging
failure never alters request behavior.
"""

from collections.abc import Mapping as _MappingABC
from typing import Any, Dict, Mapping, Optional

from utils.enhanced_logger import debug, warning

# Bounded retry count for empty transient completions (retries, not total
# attempts: the helper issues at most EMPTY_RESPONSE_RETRY_LIMIT + 1 calls).
EMPTY_RESPONSE_RETRY_LIMIT = 2

CLASS_OK = "ok"
CLASS_EMPTY_TRANSIENT = "empty_transient"
CLASS_REFUSAL = "refusal"
CLASS_CONTENT_FILTER = "content_filter"

_DIAGNOSTIC_CONTEXT_LIMIT = 120
_LOG_CATEGORY = "ai_provider"

__all__ = [
    "EMPTY_RESPONSE_RETRY_LIMIT",
    "EmptyProviderResponseError",
    "classify_chat_completion",
    "request_chat_completion_with_recovery",
]


def _to_ascii_text(value: Any, limit: int = _DIAGNOSTIC_CONTEXT_LIMIT) -> str:
    """Return a bounded, ASCII-only text form of a diagnostic value."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = str(value)
        except Exception:
            return ""
    try:
        text = text.encode("ascii", "replace").decode("ascii")
    except Exception:
        return ""
    if limit > 0 and len(text) > limit:
        text = text[:limit]
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert a value to int without raising."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_context_suffix(context: str) -> str:
    """Format an optional bounded context suffix for diagnostics."""
    return f", context={context}" if context else ""


def _safe_debug(message: str) -> None:
    """Emit a bounded debug diagnostic; a logging failure is fail-open."""
    try:
        debug(message, category=_LOG_CATEGORY)
    except Exception:
        pass


def _safe_warning(message: str) -> None:
    """Emit a bounded warning diagnostic; a logging failure is fail-open."""
    try:
        warning(message, category=_LOG_CATEGORY)
    except Exception:
        pass


class EmptyProviderResponseError(Exception):
    """Raised after the bounded empty-response retry is exhausted.

    Attributes:
        attempts: Total number of request attempts made.
        context: Bounded ASCII context label for the call site/stage.
    """

    def __init__(self, attempts: Any = 0, context: Any = ""):
        self.attempts = _safe_int(attempts, 0)
        self.context = _to_ascii_text(context)
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        message = (
            "Provider returned empty transient completions after "
            f"{self.attempts} attempt(s)"
        )
        return message + _format_context_suffix(self.context)


def _get_field(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field defensively from attribute-style or mapping-style objects."""
    if obj is None:
        return default
    try:
        value = getattr(obj, name, None)
    except Exception:
        value = None
    if value is not None:
        return value
    try:
        if isinstance(obj, _MappingABC):
            return obj.get(name, default)
    except Exception:
        return default
    return default


def _select_choice(choices: Any) -> Any:
    """Select the first choice defensively; None when no usable choice exists."""
    if choices is None or isinstance(choices, (str, bytes)):
        return None
    try:
        length = len(choices)
    except Exception:
        return None
    if not isinstance(length, int) or length <= 0:
        return None
    try:
        return choices[0]
    except Exception:
        return None


def classify_chat_completion(response: Any) -> str:
    """Classify a Chat Completions response into an explicit failure class.

    Returns one of: "ok", "empty_transient", "refusal", "content_filter".

    The classification is fully defensive and never raises for None, empty,
    or unusual response shapes. Refusal is evaluated before content so a
    refusal marker is never hidden by missing text, and a content-filter
    finish reason is evaluated before the blank-content fallback.
    """
    choices = _get_field(response, "choices")
    choice = _select_choice(choices)
    if choice is None:
        return CLASS_EMPTY_TRANSIENT

    message = _get_field(choice, "message")
    if message is None:
        return CLASS_EMPTY_TRANSIENT

    refusal = _get_field(message, "refusal")
    if isinstance(refusal, str) and refusal.strip():
        return CLASS_REFUSAL

    finish_reason = _get_field(choice, "finish_reason")
    if isinstance(finish_reason, str) and finish_reason.strip().lower() == CLASS_CONTENT_FILTER:
        return CLASS_CONTENT_FILTER

    content = _get_field(message, "content")
    if content is None:
        return CLASS_EMPTY_TRANSIENT
    if isinstance(content, str):
        if not content.strip():
            return CLASS_EMPTY_TRANSIENT
        return CLASS_OK
    if isinstance(content, (list, tuple, set, frozenset, dict)):
        if len(content) == 0:
            return CLASS_EMPTY_TRANSIENT
        return CLASS_OK
    return CLASS_OK


def _resolve_retry_limit(retry_limit: Optional[int]) -> int:
    """Resolve the retry limit; negative or invalid values clamp to 0."""
    if retry_limit is None:
        return EMPTY_RESPONSE_RETRY_LIMIT
    try:
        value = int(retry_limit)
    except (TypeError, ValueError):
        return 0
    if value < 0:
        return 0
    return value


def request_chat_completion_with_recovery(
    client: Any,
    *,
    messages: Any,
    timeout: Any,
    request_params: Optional[Mapping[str, Any]] = None,
    context: str = "",
    retry_limit: Optional[int] = None,
) -> Any:
    """Issue a Chat Completions request with bounded empty-completion recovery.

    Retries only responses classified as empty transient, forwarding the exact
    same messages, timeout, and resolved request parameters on every attempt.
    Responses classified as ok, refusal, or content_filter are returned
    unchanged without retry. Provider exceptions from the request call
    propagate unchanged; existing call-site error handling owns them.

    Args:
        client: Prepared provider client (never constructed here).
        messages: Chat messages forwarded verbatim on every attempt.
        timeout: Per-request timeout forwarded verbatim on every attempt.
        request_params: Resolved Chat Completions kwargs forwarded verbatim.
        context: Bounded stage/call-site label for ASCII diagnostics.
        retry_limit: Retry count override; negative/invalid clamps to 0.

    Returns:
        The first response classified as ok, refusal, or content_filter.

    Raises:
        EmptyProviderResponseError: When every attempt through the bounded
            retry limit returned an empty transient completion.
    """
    resolved_limit = _resolve_retry_limit(retry_limit)
    params: Dict[str, Any] = dict(request_params) if request_params else {}
    stage = _to_ascii_text(context)
    suffix = _format_context_suffix(stage)
    attempt = 0

    while True:
        attempt += 1
        response = client.chat.completions.create(
            messages=messages,
            timeout=timeout,
            **params,
        )

        classification = classify_chat_completion(response)

        if classification != CLASS_EMPTY_TRANSIENT:
            if classification != CLASS_OK:
                _safe_debug(
                    f"Provider response classified as {classification} "
                    f"(attempt {attempt}{suffix})"
                )
            return response

        if attempt > resolved_limit:
            _safe_warning(
                "Empty transient provider completion persisted through the "
                f"retry bound ({attempt} attempt(s), limit {resolved_limit}"
                f"{suffix})"
            )
            raise EmptyProviderResponseError(attempts=attempt, context=stage)

        _safe_debug(
            f"Empty transient provider completion on attempt {attempt}; "
            f"retrying (limit {resolved_limit}{suffix})"
        )
