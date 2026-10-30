# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Shared lifecycle hooks for LLM runtime sessions."""

import copy
import math
import os
import re
import threading
from collections.abc import Mapping
from typing import Any, Callable, Optional


_G10_RECEIPT_SOURCE_IDS = frozenset({
    "utils/llm_router.py:llm_router.decide",
    "utils/llm_runtime.py:llm_runtime.call",
    "core/ai/adv_summary.py:adv_summary",
    "core/ai/cumulative_summary.py:cumulative_summary",
    "main.py:generate_module_summary",
    "core/memory/session_diary.py:_generate_rebuild_chapter_summary",
    "core/memory/session_diary.py:_generate_checkpoint_summary",
    "core/memory/players_diary.py:_generate_markdown_from_prompt",
    "core/memory/story_so_far_compiler.py:_generate_story_text_with_llm",
    "core/managers/campaign_manager.py:CampaignManager._generate_module_summary.summary",
    "core/managers/campaign_manager.py:CampaignManager._generate_module_summary.export_data",
    "utils/homebrewery_adventure_writer.py:_llm_intro_narrative",
    "utils/homebrewery_adventure_writer.py:_llm_plot_hook",
    "utils/homebrewery_adventure_writer.py:_llm_area_overview",
    "scripts/test_capture_g10.py:test_summary_producer",
    "tests/provider_free/test_llm_router.py:provider_free_test",
})
_G10_RECEIPT_ENDPOINTS = frozenset({"module_summary"})


def _valid_g10_source_id(value: Any) -> Optional[str]:
    if isinstance(value, str) and value in _G10_RECEIPT_SOURCE_IDS:
        return value
    return None


def _valid_g10_endpoint(value: Any) -> Optional[str]:
    if isinstance(value, str) and value in _G10_RECEIPT_ENDPOINTS:
        return value
    return None


def _g10_receipt_trace_active() -> bool:
    return (
        os.environ.get("NEQ_G10_RECEIPT_TRACE") == "1"
        and bool(os.environ.get("NEQ_G5_CAPTURE_RUN_ID"))
    )


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _valid_token_count(value: Any) -> Optional[int]:
    """Return a genuine non-negative integral SDK count, without zero-fill."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _valid_cost(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _legacy_tracker_view(receipt: Any, raw_response: Any) -> dict:
    """Build detached tracker data while retaining partial receipt token facts."""
    usage = _value(raw_response, "usage")
    if usage is None:
        return {"usage": None}

    counts = {}
    for field in ("prompt_tokens", "completion_tokens"):
        value = _valid_token_count(getattr(receipt, field, None))
        if value is None:
            value = _valid_token_count(_value(usage, field))
        if value is not None:
            counts[field] = value

    total_tokens = _valid_token_count(_value(usage, "total_tokens"))
    if total_tokens is None and counts:
        total_tokens = sum(counts.values())
    if total_tokens is not None:
        counts["total_tokens"] = total_tokens

    if not counts:
        return {"usage": None}

    actual_cost = _valid_cost(getattr(receipt, "provider_reported_cost_usd", None))
    if actual_cost is None:
        actual_cost = _valid_cost(_value(raw_response, "cost"))
    if actual_cost is None:
        actual_cost = _valid_cost(_value(usage, "cost"))
    if actual_cost is not None:
        counts["cost"] = actual_cost
    return {"usage": counts}


def _observer_metadata(receipt: Any, legacy_context: Any, raw_response: Any = None) -> dict:
    """Merge copied caller labels with receipt-owned accounting facts."""
    caller = {}
    if isinstance(legacy_context, Mapping):
        try:
            caller = copy.deepcopy(dict(legacy_context))
        except Exception:
            caller = {}
    if "model" in caller:
        caller["legacy_context_model"] = caller.pop("model")
    metadata = caller
    trusted = {
        "call_id": getattr(receipt, "call_id", None),
        "attempt_id": getattr(receipt, "attempt_id", None),
        "attempt_number": getattr(receipt, "attempt_number", None),
        "task": getattr(receipt, "task", None),
        "tier": getattr(receipt, "tier", None),
        "profile": getattr(receipt, "profile", None),
        "provider": getattr(receipt, "transport_provider", None),
        "observed_upstream_provider": getattr(receipt, "observed_upstream_provider", None),
        "requested_model": getattr(receipt, "requested_model", None),
        "resolved_model": getattr(receipt, "resolved_model", None),
        "retry": getattr(receipt, "transport_retry", None),
        "retry_tier": getattr(receipt, "retry_tier", None),
        "fallback": getattr(receipt, "fallback", None),
        "cost_usd": getattr(receipt, "cost_usd", None),
        "provider_reported_cost_usd": getattr(receipt, "provider_reported_cost_usd", None),
        "cost_provenance": getattr(receipt, "cost_provenance", None),
        "cost_complete": getattr(receipt, "cost_complete", None),
        "usage_complete": getattr(receipt, "usage_complete", None),
        "error_type": getattr(receipt, "error_type", None),
    }
    for field in ("prompt_tokens", "cached_tokens", "completion_tokens"):
        value = getattr(receipt, field, None)
        if value is not None:
            trusted[field] = value
    reported_cost = _valid_cost(trusted["provider_reported_cost_usd"])
    if reported_cost is None and raw_response is not None:
        reported_cost = _valid_cost(_value(raw_response, "cost"))
        if reported_cost is None:
            reported_cost = _valid_cost(_value(_value(raw_response, "usage"), "cost"))
    if reported_cost is not None:
        trusted["provider_reported_cost_usd"] = reported_cost
        trusted["cost_usd"] = reported_cost
        trusted["cost_provenance"] = "actual"
        trusted["cost_complete"] = True
    metadata.update(trusted)
    return metadata


def make_legacy_receipt_observer(
    *,
    endpoint_name: Optional[str] = None,
    messages: Any = None,
    legacy_context: Any = None,
    trace_site: Optional[str] = None,
    tracker_getter: Optional[Callable[[], Any]] = None,
    api_logger: Optional[Callable[..., Any]] = None,
    trace_writer: Optional[Callable[..., Any]] = None,
    trace_gate: Optional[Callable[[], bool]] = None,
    g10_source_id: Optional[str] = None,
    g10_endpoint: Optional[str] = None,
    track_usage: bool = True,
    api_log_before_tracker: bool = False,
) -> Callable[[Any, Any], None]:
    """Create the per-call adapter for legacy consumers of router receipts.

    Pass this callback as ``observer=`` to ``llm.call``. ``endpoint_name`` and
    ``messages`` opt in the legacy ``log_api_call(endpoint_name, messages,
    response, metadata=None)`` consumer; omit them when the producer has no
    matching legacy API-log event. ``trace_site`` opts into the existing
    combat provider trace gate/writer. ``legacy_context`` is copied at factory
    time and preserves producer labels such as endpoint, function, and purpose.
    ``g10_source_id`` is an allowlisted static identifier used only by the G10
    sandbox receipt trace. A separately allowlisted endpoint may be carried
    from an explicit ``endpoint_name``. Receipt-owned facts override colliding
    caller values.
    Tracker, logger, and
    trace dependencies are imported/resolved lazily only when applicable.
    ``track_usage=False`` disables only tracker resolution/delivery. The
    ``api_log_before_tracker`` option preserves legacy producers whose logger
    historically ran before their tracker; trace remains first.

    Receipts are deduplicated per SDK attempt. Each consumer receives detached
    data, and failures in one ordinary consumer do not suppress the others.
    Router error receipts never become successful usage events.
    """
    if messages is not None:
        try:
            captured_messages = copy.deepcopy(messages)
        except Exception:
            captured_messages = messages
    else:
        captured_messages = None
    try:
        captured_legacy_context = copy.deepcopy(legacy_context)
    except Exception:
        captured_legacy_context = None
    trusted_g10_source_id = _valid_g10_source_id(g10_source_id)
    trusted_g10_endpoint = _valid_g10_endpoint(g10_endpoint) or _valid_g10_endpoint(endpoint_name)

    seen_events = set()
    seen_lock = threading.Lock()

    def observer(receipt: Any, raw_response: Any) -> None:
        kind = getattr(receipt, "kind", None)
        attempt_id = getattr(receipt, "attempt_id", None)
        call_id = getattr(receipt, "call_id", None)
        fallback = bool(getattr(receipt, "fallback", False))
        if kind in ("constructor_error", "constructor_failure"):
            dedupe_key = ("constructor", call_id, kind, fallback)
        elif attempt_id is not None:
            dedupe_key = ("attempt", attempt_id)
        else:
            return
        with seen_lock:
            if dedupe_key in seen_events:
                return
            seen_events.add(dedupe_key)

        metadata = _observer_metadata(receipt, captured_legacy_context, raw_response)
        is_response = kind == "response"
        is_sdk_attempt = kind in ("response", "transport_error")
        is_constructor_error = kind in ("constructor_error", "constructor_failure")
        metadata["usage_available"] = (
            is_response and _value(raw_response, "usage") is not None
        )
        if is_response and raw_response is None and metadata["provider_reported_cost_usd"] is None:
            metadata["cost_usd"] = None
            metadata["cost_provenance"] = "unpriced"
            metadata["cost_complete"] = False
            metadata["usage_complete"] = False

        # Materialize all inputs before a consumer can mutate its copy.
        if is_response:
            tracker_response = _legacy_tracker_view(receipt, raw_response)
            try:
                logger_response = copy.deepcopy(raw_response) if raw_response is not None else None
            except Exception:
                logger_response = raw_response
            try:
                logger_messages = copy.deepcopy(captured_messages)
            except Exception:
                logger_messages = captured_messages
        else:
            tracker_response = logger_response = logger_messages = None

        trace_event = None
        trace_writer_to_use = None
        trace_fields = None
        if trace_site is not None and (is_sdk_attempt or is_constructor_error):
            try:
                if trace_gate is None or trace_writer is None:
                    from utils import combat_latency_trace

                    trace_enabled = trace_gate() if trace_gate is not None else combat_latency_trace.trace_enabled()
                    trace_writer_to_use = trace_writer or combat_latency_trace.emit_trace_event
                else:
                    trace_enabled = trace_gate()
                    trace_writer_to_use = trace_writer
                if trace_enabled:
                    trace_context_fields = {}
                    for label in (
                        "endpoint", "function", "purpose", "legacy_context_model",
                        "retry_cause", "batch_id", "request_kind", "request_site",
                    ):
                        if label not in metadata:
                            continue
                        value = metadata[label]
                        if label == "batch_id" and (
                            not isinstance(value, str)
                            or re.fullmatch(r"enemy:r[0-9]{1,73}", value) is None
                        ):
                            continue
                        if label == "request_kind" and (
                            not isinstance(value, str)
                            or value not in {"initial", "replan"}
                        ):
                            continue
                        if label == "request_site" and value != "combat_tactical_prefetch":
                            continue
                        trace_context_fields[label] = value
                    if is_constructor_error:
                        trace_event = "combat_observation"
                        trace_fields = {
                            "observation": "llm_client_construction_error",
                            "site": trace_site,
                            "call_id": metadata["call_id"],
                            "task": metadata["task"],
                            "provider": metadata["provider"],
                            "requested_model": metadata["requested_model"],
                            "fallback": metadata["fallback"],
                            "error_type": metadata["error_type"],
                        }
                        trace_fields.update(trace_context_fields)
                    else:
                        trace_event = "provider"
                        actual_model = metadata["resolved_model"] or "unknown"
                        trace_fields = {
                            "site": trace_site,
                            "call_id": metadata["call_id"],
                            "attempt_id": attempt_id,
                            "attempt_number": metadata["attempt_number"],
                            "task": metadata["task"],
                            "provider": metadata["provider"],
                            "observed_upstream_provider": metadata["observed_upstream_provider"],
                            "model": actual_model,
                            "requested_model": metadata["requested_model"],
                            "resolved_model": actual_model,
                            "retry": metadata["retry"],
                            "retry_tier": metadata["retry_tier"],
                            "fallback": metadata["fallback"],
                            "prompt_tokens": metadata.get("prompt_tokens"),
                            "cached_tokens": metadata.get("cached_tokens"),
                            "completion_tokens": metadata.get("completion_tokens"),
                            "cost_usd": metadata["cost_usd"],
                            "provider_reported_cost_usd": metadata["provider_reported_cost_usd"],
                            "cost_provenance": metadata["cost_provenance"],
                            "cost_complete": metadata["cost_complete"],
                            "usage_complete": metadata["usage_complete"],
                            "usage_available": metadata["usage_available"],
                            "outcome": kind,
                            "error_type": metadata["error_type"],
                        }
                        sdk_total_tokens = _value(
                            _value(raw_response, "usage"), "total_tokens"
                        )
                        if _valid_token_count(sdk_total_tokens) is not None:
                            trace_fields["sdk_total_tokens"] = sdk_total_tokens
                        trace_fields.update(trace_context_fields)
                        elapsed_ms = getattr(receipt, "elapsed_ms", None)
                        if elapsed_ms is not None:
                            trace_fields["elapsed_ms"] = elapsed_ms
            except Exception:
                trace_event = None

        if trace_fields is not None and _g10_receipt_trace_active():
            if trusted_g10_source_id is not None:
                trace_fields["source_id"] = trusted_g10_source_id
            elif trusted_g10_endpoint is not None:
                trace_fields["endpoint"] = trusted_g10_endpoint

        # Existing common combat call sites emit trace, then tracker, then API log.
        if trace_event is not None:
            try:
                trace_writer_to_use(trace_event, **trace_fields)
            except Exception:
                pass

        def track_response() -> None:
            if not (is_response and track_usage):
                return
            try:
                if tracker_getter is None:
                    from utils.llm_usage_tracker import get_global_tracker

                    tracker = get_global_tracker()
                else:
                    tracker = tracker_getter()
                tracker.track(tracker_response, copy.deepcopy(metadata))
            except Exception:
                pass

        def log_response() -> None:
            if not (is_response and endpoint_name is not None and captured_messages is not None):
                return
            try:
                if api_logger is None:
                    from utils.api_logger import log_api_call

                    logger = log_api_call
                else:
                    logger = api_logger
                logger(endpoint_name, logger_messages, logger_response, metadata=copy.deepcopy(metadata))
            except Exception:
                pass

        if api_log_before_tracker:
            log_response()
            track_response()
        else:
            track_response()
            log_response()

    # The facade uses these private ownership hints to avoid installing a
    # second tracker or provider-trace delivery beside an explicit adapter.
    observer._llm_tracks_usage = bool(track_usage)
    observer._llm_traces_provider = trace_site is not None
    observer._llm_api_log_before_tracker = bool(api_log_before_tracker)
    if _g10_receipt_trace_active():
        if trusted_g10_source_id is not None:
            observer._llm_g10_source_id = trusted_g10_source_id
        if trusted_g10_endpoint is not None:
            observer._llm_g10_endpoint = trusted_g10_endpoint
    return observer


def begin_llm_session() -> None:
    """Reset router-local stats and factory fallback state for a new launch."""
    from utils import llm_router
    from utils.ai_client_factory import reset_fallback_status

    llm_router.reset_usage_stats()
    reset_fallback_status()
