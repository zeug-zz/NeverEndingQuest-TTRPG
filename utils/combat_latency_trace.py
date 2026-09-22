# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Latency Trace - Bounded optional JSONL telemetry.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

"""Small, fail-open, provider-free writer for combat latency observations."""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union


DEFAULT_TRACE_PATH = Path("debug") / "combat_turn_trace.jsonl"
MAX_RECORD_BYTES = 8192
MAX_VALUE_CHARS = 512
_TRACE_LOCK = threading.Lock()
_TRACE_CONTEXT: Dict[str, Any] = {}


def trace_enabled() -> bool:
    """Return whether combat tracing is enabled, defaulting safely to False."""
    try:
        import model_config

        return bool(getattr(model_config, "ENABLE_COMBAT_TURN_TRACE", False))
    except Exception:
        return False


def _bounded_value(value: Any, depth: int = 0) -> Any:
    """Convert values to bounded JSON-compatible, ASCII-safe values."""
    if depth > 2:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_VALUE_CHARS]
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth + 1) for item in value[:32]]
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            result[str(key)[:80]] = _bounded_value(item, depth + 1)
        return result
    return str(value)[:MAX_VALUE_CHARS]


def normalize_trace_event(event_type: str, **fields: Any) -> Dict[str, Any]:
    """Build a bounded trace record without rejecting optional event fields."""
    record: Dict[str, Any] = {
        "schema_version": 1,
        "event_type": str(event_type)[:80],
    }
    for key, value in fields.items():
        record[str(key)[:80]] = _bounded_value(value)
    return record


def set_trace_context(**fields: Any) -> bool:
    """Replace the bounded context applied to subsequent trace records."""
    if not trace_enabled():
        return False
    try:
        bounded_context = {
            str(key)[:80]: _bounded_value(value)
            for key, value in list(fields.items())[:32]
        }
        with _TRACE_LOCK:
            _TRACE_CONTEXT.clear()
            _TRACE_CONTEXT.update(bounded_context)
        return True
    except Exception as error:
        _debug_trace_failure(error)
        return False


def _debug_trace_failure(error: Exception) -> None:
    """Best-effort diagnostic logging that can never affect the caller."""
    try:
        from utils.enhanced_logger import debug

        debug("Combat latency trace skipped: %s" % error, category="combat_latency")
    except Exception:
        pass


def emit_trace_event(
    event_type: str,
    path: Optional[Union[str, Path]] = None,
    **fields: Any,
) -> bool:
    """Append one bounded trace event and return whether it was written.

    The gate is deliberately checked before path handling, payload construction,
    clock access, directory creation, locking, or file access.
    """
    if not trace_enabled():
        return False

    try:
        destination = Path(path) if path is not None else DEFAULT_TRACE_PATH
        with _TRACE_LOCK:
            context = dict(_TRACE_CONTEXT)
        merged_fields = dict(context)
        merged_fields.update(fields)
        record = normalize_trace_event(event_type, **merged_fields)
        record["recorded_at_ms"] = int(time.time() * 1000)
        encoded = json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("ascii")) > MAX_RECORD_BYTES:
            record["fields_truncated"] = True
            encoded = json.dumps(
                normalize_trace_event(event_type, fields_truncated=True),
                ensure_ascii=True,
                separators=(",", ":"),
            )
        line = (encoded + "\n").encode("ascii")
        with _TRACE_LOCK:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("ab") as trace_file:
                trace_file.write(line)
        return True
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_stage(stage: str, started_at: float, **fields: Any) -> bool:
    """Emit an observed combat stage duration when tracing is enabled."""
    if not trace_enabled():
        return False
    try:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        return emit_trace_event("stage", stage=stage, elapsed_ms=elapsed_ms, **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_decision(
    decision_point: str,
    decision_source: str,
    started_at: float,
    provider_call_avoided: bool,
    **fields: Any,
) -> bool:
    """Emit an observed combat decision outcome without affecting routing."""
    if not trace_enabled():
        return False
    if decision_source not in ("deterministic", "llm_fallback", "jev"):
        try:
            from utils.enhanced_logger import debug

            debug(
                "Combat latency decision trace skipped: invalid source %s"
                % decision_source,
                category="combat_latency",
            )
        except Exception:
            pass
        return False
    try:
        elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
        event_fields: Dict[str, Any] = {
            "decision_point": decision_point,
            "decision_source": decision_source,
            "decision_latency_ms": elapsed_ms,
            "provider_call_avoided": bool(provider_call_avoided),
        }
        event_fields.update(fields)
        return emit_trace_event("decision", **event_fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_provider_call(site: str, started_at: float, response: Any = None) -> bool:
    """Emit provider latency and only the usage metadata actually available."""
    if not trace_enabled():
        return False
    try:
        fields: Dict[str, Any] = {
            "site": site,
            "elapsed_ms": (time.perf_counter() - started_at) * 1000.0,
        }
        usage = getattr(response, "usage", None)
        if usage is not None:
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage, name, None)
                if value is None and isinstance(usage, dict):
                    value = usage.get(name)
                if value is not None:
                    fields[name] = value
        return emit_trace_event("provider", **fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_compression_event(
    site: str,
    call_occurred: bool,
    cache_hit: bool,
    started_at: Optional[float] = None,
    **fields: Any,
) -> bool:
    """Emit an observed compression decision without changing compression policy."""
    if not trace_enabled():
        return False
    try:
        event_fields: Dict[str, Any] = {
            "site": site,
            "call_occurred": call_occurred,
            "cache_hit": cache_hit,
        }
        if started_at is not None:
            event_fields["elapsed_ms"] = (time.perf_counter() - started_at) * 1000.0
        event_fields.update(fields)
        return emit_trace_event("compression", **event_fields)
    except Exception as error:
        _debug_trace_failure(error)
        return False


def trace_file_operation(category: str, site: str) -> bool:
    """Emit an observed combat file operation."""
    if not trace_enabled():
        return False
    try:
        return emit_trace_event("file_operation", category=category, site=site)
    except Exception as error:
        _debug_trace_failure(error)
        return False
