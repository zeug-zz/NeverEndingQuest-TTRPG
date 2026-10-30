# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-neutral LLM router facade.

Profile resolution and request orchestration live here.  Provider clients and
provider-specific parameter policy remain owned by ``ai_client_factory``.
"""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Optional

from utils import ai_client_factory
from utils.openrouter_transport_fault_injection import (
    maybe_inject_openrouter_transport_failure,
)
from utils.provider_response_recovery import (
    CLASS_CONTENT_FILTER,
    CLASS_EMPTY_TRANSIENT,
    CLASS_REFUSAL,
    EMPTY_RESPONSE_RETRY_LIMIT,
    EmptyProviderResponseError,
    classify_chat_completion,
)


class GameLLMError(RuntimeError):
    """Base error for router-level LLM failures."""


class GameLLMTerminalError(GameLLMError):
    """Typed, payload-free terminal provider outcome for caller boundaries."""

    TERMINAL_KINDS = frozenset({"quota", "refusal", "content_filter"})

    def __init__(self, terminal_kind: str):
        if terminal_kind not in self.TERMINAL_KINDS:
            raise ValueError("unsupported terminal LLM outcome")
        self.terminal_kind = terminal_kind
        super().__init__("LLM provider returned a terminal outcome: " + terminal_kind)


class LLMJSONError(GameLLMError):
    """Raised when a bounded structured-output retry budget is exhausted."""


_UNKNOWN_MODEL = "unknown"
_UNKNOWN_PROVIDER = "unknown"
_AUTO_ROUTER_COST_TIERS = frozenset({"low", "medium", "high", "xhigh", "max"})
_USAGE_LOCK = threading.Lock()


@dataclass(frozen=True)
class RouterReceipt:
    """Immutable metadata for one router transport event.

    The observer receives this value separately from trusted raw response
    access. Error events never expose exception objects or messages; only the
    safe exception class name is included. ``transport_retry`` means an SDK
    invocation after an earlier invocation in this facade call, not a reasoning
    policy. ``retry_tier`` records the independent caller policy hint.
    """

    kind: str
    call_id: Optional[str]
    attempt_id: Optional[str]
    attempt_number: Optional[int]
    task: str
    tier: str
    profile: str
    transport_retry: bool
    retry_tier: Optional[str]
    fallback: bool
    transport_provider: str
    observed_upstream_provider: str
    requested_model: str
    resolved_model: str
    prompt_tokens: Optional[int]
    cached_tokens: Optional[int]
    completion_tokens: Optional[int]
    usage_complete: bool
    provider_reported_cost_usd: Optional[float]
    cost_usd: Optional[float]
    cost_provenance: str
    cost_complete: bool
    error_type: Optional[str]
    elapsed_ms: Optional[float]
    stats_snapshot: Mapping[str, Any]


def _freeze(value: Any) -> Any:
    """Recursively detach and freeze receipt snapshot values."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _notify(observer: Optional[Callable[[RouterReceipt, Any], Any]], receipt: RouterReceipt, raw: Any) -> None:
    """Invoke a per-call observer without allowing ordinary failures to escape."""
    if observer is None:
        return
    try:
        observer(receipt, raw)
    except Exception:
        # Telemetry is best effort and cannot alter call semantics.
        return


def _new_usage_stats() -> Dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "cached_tokens": 0,
        "completion_tokens": 0,
        "total_cost_usd": 0.0,
        "calls": 0,
        "errors": 0,
        "fallbacks": 0,
        "transport_attempts": 0,
        "unpriced_calls": 0,
        "cost_complete": True,
        "by_task": {},
        "by_model": {},
        "diagnostics": [],
    }


def _new_usage_bucket() -> Dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "cached_tokens": 0,
        "completion_tokens": 0,
        "total_cost_usd": 0.0,
        "calls": 0,
    }


_usage_stats = _new_usage_stats()


def _read_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _nonnegative_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _token_count(value: Any) -> int:
    number = _nonnegative_number(value)
    if number is None:
        return 0
    return int(number)


def _usage_counts(response: Any) -> tuple[int, int, int, Any, bool]:
    usage = _read_value(response, "usage")
    if usage is None:
        return 0, 0, 0, None, False
    prompt = _token_count(_read_value(usage, "prompt_tokens", 0))
    completion = _token_count(_read_value(usage, "completion_tokens", 0))
    details = _read_value(usage, "prompt_tokens_details")
    cached = _token_count(_read_value(details, "cached_tokens", 0))
    if cached > prompt:
        cached = prompt
    return prompt, cached, completion, _read_value(usage, "cost"), True


def _verified_rates(profile: Mapping[str, Any], actual_model: str) -> Optional[Dict[str, float]]:
    """Return rates only when the configured model and response model agree."""
    configured_model = str(profile.get("model") or "")
    if not actual_model or actual_model == _UNKNOWN_MODEL or configured_model != actual_model:
        return None
    raw = profile.get("price_per_1k")
    if not isinstance(raw, Mapping):
        return None
    prompt = _nonnegative_number(raw.get("prompt"))
    completion = _nonnegative_number(raw.get("completion"))
    if prompt is None or completion is None:
        return None
    cache = _nonnegative_number(raw.get("cache_read"))
    return {"prompt": prompt, "completion": completion, "cache_read": prompt if cache is None else cache}


def _response_cost(
    profile: Mapping[str, Any], response: Any
) -> tuple[str, int, int, int, Optional[float], Optional[float], str, bool]:
    actual_model = str(_read_value(response, "model", "") or _UNKNOWN_MODEL)
    prompt, cached, completion, reported_cost, _usage_present = _usage_counts(response)
    actual_cost = _nonnegative_number(reported_cost)
    rates = _verified_rates(profile, actual_model)
    # TABLETOP MODE: Keep stats and receipts on one strict usage-completeness
    # rule; partial token details cannot support a verified estimate.
    usage_complete = _receipt_usage(response)[4]
    if actual_cost is not None:
        cost: Optional[float] = actual_cost
        provenance = "actual"
        priced = True
    elif usage_complete and rates is not None:
        fresh = max(prompt - cached, 0)
        cost = (fresh * rates["prompt"] + cached * rates["cache_read"] + completion * rates["completion"]) / 1000.0
        provenance = "estimated"
        priced = True
    else:
        cost = None
        provenance = "unpriced"
        priced = False
    return actual_model, prompt, cached, completion, actual_cost, cost, provenance, priced


def _observed_token(value: Any) -> Optional[int]:
    number = _nonnegative_number(value)
    return None if number is None else int(number)


def _receipt_usage(response: Any) -> tuple[
    Optional[int], Optional[int], Optional[int], Optional[float], bool
]:
    """Read only token facts explicitly present in a response, without zero fill."""
    usage = _read_value(response, "usage")
    if usage is None:
        return None, None, None, None, False
    prompt = _observed_token(_read_value(usage, "prompt_tokens"))
    completion = _observed_token(_read_value(usage, "completion_tokens"))
    details = _read_value(usage, "prompt_tokens_details")
    cached = _observed_token(_read_value(details, "cached_tokens")) if details is not None else None
    reported = _nonnegative_number(_read_value(usage, "cost"))
    return prompt, cached, completion, reported, all(
        token is not None for token in (prompt, cached, completion)
    )


def _observed_upstream_provider(response: Any) -> str:
    provider = _read_value(response, "provider")
    if provider is None:
        metadata = _read_value(response, "metadata")
        provider = _read_value(metadata, "provider") if metadata is not None else None
    return str(provider).strip() if provider else _UNKNOWN_PROVIDER


def _record_response(task: str, requested_model: str, profile: Mapping[str, Any], response: Any) -> None:
    actual_model, prompt, cached, completion, _, cost, provenance, priced = _response_cost(profile, response)
    _prompt, _cached, _completion, reported_cost, usage_complete = _receipt_usage(response)
    recorded_cost = cost if cost is not None else 0.0

    model_bucket = actual_model if actual_model else _UNKNOWN_MODEL
    provider = str(profile.get("provider_name") or _UNKNOWN_PROVIDER)
    detail = {
        "task": str(task),
        "requested_model": str(requested_model or _UNKNOWN_MODEL),
        "resolved_model": model_bucket,
        "provider": provider,
        "observed_upstream_provider": _observed_upstream_provider(response),
        "provider_reported_cost_usd": reported_cost,
        "cost_usd": cost,
        "provenance": provenance,
        "cost_provenance": provenance,
        "cost_complete": priced,
        "usage_complete": usage_complete,
    }
    with _USAGE_LOCK:
        by_task = _usage_stats["by_task"].setdefault(str(task), _new_usage_bucket())
        by_model = _usage_stats["by_model"].setdefault(model_bucket, _new_usage_bucket())
        for bucket in (by_task, by_model):
            bucket["prompt_tokens"] += prompt
            bucket["cached_tokens"] += cached
            bucket["completion_tokens"] += completion
            bucket["calls"] += 1
            bucket["total_cost_usd"] += recorded_cost
        _usage_stats["prompt_tokens"] += prompt
        _usage_stats["cached_tokens"] += cached
        _usage_stats["completion_tokens"] += completion
        _usage_stats["calls"] += 1
        _usage_stats["total_cost_usd"] += recorded_cost
        if not priced:
            _usage_stats["unpriced_calls"] += 1
            _usage_stats["cost_complete"] = False
        _usage_stats["diagnostics"].append(detail)


def _record_error(task: str, profile: Mapping[str, Any], error: Exception, *, fallback: bool = False) -> None:
    detail = {
        "task": str(task),
        "requested_model": str(profile.get("model") or _UNKNOWN_MODEL),
        # No provider response exists on an error, so there is no resolved
        # actual model to report.  Keep the submitted request in requested_model.
        "resolved_model": _UNKNOWN_MODEL,
        "provider": str(profile.get("provider_name") or _UNKNOWN_PROVIDER),
        "provenance": "error",
        "error_type": type(error).__name__,
    }
    with _USAGE_LOCK:
        _usage_stats["errors"] += 1
        if fallback:
            _usage_stats["fallbacks"] += 1
        _usage_stats["diagnostics"].append(detail)


def _record_fallback_switch(
    task: str,
    from_profile: Mapping[str, Any],
    to_profile: Mapping[str, Any],
) -> None:
    """Count a fallback only after classification has committed to switching."""
    detail = {
        "task": str(task),
        "requested_model": str(to_profile.get("model") or _UNKNOWN_MODEL),
        "resolved_model": _UNKNOWN_MODEL,
        "provider": str(to_profile.get("provider_name") or _UNKNOWN_PROVIDER),
        "provenance": "fallback_switch",
        "from_provider": str(from_profile.get("provider_name") or _UNKNOWN_PROVIDER),
    }
    with _USAGE_LOCK:
        _usage_stats["fallbacks"] += 1
        _usage_stats["diagnostics"].append(detail)


def get_usage_stats() -> Dict[str, Any]:
    with _USAGE_LOCK:
        snapshot = copy.deepcopy(_usage_stats)
    snapshot["total_cost_usd"] = round(float(snapshot["total_cost_usd"]), 12)
    for bucket_map in (snapshot["by_task"], snapshot["by_model"]):
        for bucket in bucket_map.values():
            bucket["total_cost_usd"] = round(float(bucket["total_cost_usd"]), 12)
    return snapshot


def reset_usage_stats() -> None:
    global _usage_stats
    with _USAGE_LOCK:
        _usage_stats = _new_usage_stats()


def _mapping(value: Any) -> Dict[str, Any]:
    """Return a detached mapping or an empty mapping for malformed config."""
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    return {}


def _profile_selection(config: Any, requested: Any) -> tuple[str, Dict[str, Any]]:
    """Resolve a profile name, preserving a detached concrete default."""
    profiles = getattr(config, "MODEL_PROFILES", {})
    if not isinstance(profiles, Mapping):
        profiles = {}

    default = getattr(config, "DEFAULT_PROFILE", "production-auto")
    requested_name = str(requested or "")
    if requested_name in profiles:
        return requested_name, _mapping(profiles[requested_name])

    if isinstance(default, Mapping):
        for name, profile in profiles.items():
            if profile is default or profile == default:
                return str(name), _mapping(profile)
        # DEFAULT_PROFILE is itself the concrete source of truth.  Do not
        # replace it with whichever profile happens to be first in the map.
        return "default", _mapping(default)
    else:
        default_name = str(default or "production-auto")

    if default_name in profiles:
        return default_name, _mapping(profiles[default_name])
    return "default", {}


def _is_profile_label(value: Any, profiles: Mapping[str, Any]) -> bool:
    return isinstance(value, str) and value.strip() in profiles


def _tier_name(config: Any, task: str) -> str:
    # TABLETOP MODE: Runtime tier selection has one canonical config source.
    complex_tasks = getattr(config, "COMPLEX_TASKS", ())
    try:
        return "complex" if task in complex_tasks else "simple"
    except TypeError:
        return "simple"


class LLMRouter:
    """Resolve task/profile/model data without creating a provider client."""

    @staticmethod
    def _auto_router_task_cost_tier(task_id: str) -> Optional[str]:
        """Return a validated task-specific Auto Router tier, if configured."""
        import model_config as config

        configured_tiers = getattr(config, "AUTO_ROUTER_TASK_COST_TIERS", {})
        if not isinstance(configured_tiers, Mapping):
            raise ValueError("AUTO_ROUTER_TASK_COST_TIERS must be a mapping")
        if task_id not in configured_tiers:
            return None
        cost_tier = configured_tiers[task_id]
        if not isinstance(cost_tier, str) or cost_tier not in _AUTO_ROUTER_COST_TIERS:
            raise ValueError(
                "invalid Auto Router cost tier for task "
                + task_id
                + "; expected one of low, medium, high, xhigh, max"
            )
        return cost_tier

    def resolve_profile(
        self,
        task: str,
        *,
        use_fallback: bool = False,
        model_tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve a task into a detached, provider-safe profile description.

        Configuration is imported and read on every invocation so tests and
        future runtime configuration changes do not depend on cached literals.
        ``use_fallback`` is the explicit transport-failure path and always
        resolves the direct-OpenAI fallback model from current configuration.
        """
        import model_config as config

        task_id = str(task or "default")
        provider_name, is_openrouter = ai_client_factory._get_actual_provider(
            use_fallback=use_fallback
        )
        overrides = getattr(config, "TASK_OVERRIDES", {})
        override = _mapping(overrides.get(task_id)) if isinstance(overrides, Mapping) else {}

        tier = model_tier if model_tier is not None else _tier_name(config, task_id)
        profiles = getattr(config, "MODEL_PROFILES", {})
        if not isinstance(profiles, Mapping):
            profiles = {}

        if is_openrouter:
            selected_name, profile = _profile_selection(
                config,
                override.get("profile") if override.get("profile") is not None
                else getattr(config, "ACTIVE_PROFILE", "production-auto"),
            )
        else:
            # The fallback profile is a semantic boundary, even if a malformed
            # test configuration omits its data block.
            selected_name = "openai/fallback"
            profile = _mapping(profiles.get(selected_name))

        tier_data = _mapping(profile.get(tier))

        if not is_openrouter:
            # Do not trust a stale profile literal: the fallback model is a
            # live configuration value and is authoritative for both tiers.
            model = str(getattr(config, "OPENAI_FALLBACK_MODEL", "") or "")
            if not model:
                model = "gpt-6-luna"
            explicit_model = False
            params: Dict[str, Any] = {}
            provider_preferences: Dict[str, Any] = {}
            price_per_1k = _mapping(tier_data.get("price_per_1k"))
        elif "model" in override:
            # An explicit model is independent of the selected profile's
            # parameters, provider preferences, and pricing estimate.
            override_model = override.get("model")
            if (
                not isinstance(override_model, str)
                or not override_model.strip()
                or _is_profile_label(override_model, profiles)
            ):
                model = "openrouter/auto"
            else:
                model = override_model.strip()
            explicit_model = True
            params = {}
            provider_preferences = {}
            price_per_1k = {}
        else:
            model = str(tier_data.get("model") or "openrouter/auto")
            params = _mapping(tier_data.get("params"))
            provider_preferences = _mapping(tier_data.get("provider"))
            price_per_1k = _mapping(tier_data.get("price_per_1k"))
            explicit_model = False
            if not model or _is_profile_label(model, profiles):
                model = "openrouter/auto"

        return {
            "task": task_id,
            "tier": tier,
            "profile": selected_name,
            "provider_name": provider_name,
            "actual_provider": provider_name,
            "is_openrouter": bool(is_openrouter),
            "model": model,
            "params": params,
            "provider": provider_preferences,
            "provider_preferences": provider_preferences,
            "price_per_1k": price_per_1k,
            "explicit_model": explicit_model,
        }

    def get_usage_stats(self) -> Dict[str, Any]:
        """Return a detached, lock-consistent usage snapshot."""
        return get_usage_stats()

    def reset_usage_stats(self) -> None:
        """Reset router-local usage accounting without touching other trackers."""
        reset_usage_stats()

    def decide(self, task: str, state: Any, questions: Any = None, **kwargs: Any) -> Any:
        """Reject the gated decisions primitive until decomposition is approved."""
        raise GameLLMError(
            "LLM decisions primitive status=unavailable; pending decomposition gate."
        )

    @staticmethod
    def _content(response: Any) -> Any:
        """Extract message content from SDK objects and provider-free dicts."""
        choices = response.get("choices") if isinstance(response, Mapping) else getattr(response, "choices", None)
        if not choices:
            raise GameLLMError("LLM provider returned no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else getattr(first, "message", None)
        if message is None:
            raise GameLLMError("LLM provider returned no message")
        if isinstance(message, Mapping):
            return message.get("content")
        return getattr(message, "content", None)

    @staticmethod
    def _quota_error(error: Exception) -> bool:
        # TABLETOP MODE: Provider quota/billing outcomes are terminal even when
        # the SDK exposes the signal only as structured status/body metadata.
        status_code = _read_value(error, "status_code")
        if status_code == 402 or str(status_code) == "402":
            return True

        def evidence(value: Any, depth: int = 0) -> str:
            if depth >= 4:
                return ""
            if isinstance(value, Mapping):
                return " ".join(
                    evidence(value.get(key), depth + 1)
                    for key in ("code", "type", "message", "detail", "error", "body")
                    if key in value
                )
            if isinstance(value, (list, tuple)):
                return " ".join(evidence(item, depth + 1) for item in value[:16])
            if isinstance(value, (str, int, float)):
                return str(value)
            return ""

        evidence_values = [str(error)]
        for attribute in ("code", "type", "message", "body"):
            value = getattr(error, attribute, None)
            if value is not None:
                evidence_values.append(evidence(value))
        text = " ".join(evidence_values).lower()
        return any(
            marker in text
            for marker in (
                "quota",
                "billing",
                "payment",
                "insufficient_quota",
                "usage limit",
                "usage-limit",
                "account balance",
                "account-balance",
            )
        )

    @staticmethod
    def _json_object(content: Any) -> Dict[str, Any]:
        if isinstance(content, Mapping):
            return copy.deepcopy(dict(content))
        if not isinstance(content, str):
            raise LLMJSONError("LLM provider returned non-object JSON content")
        try:
            value = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise LLMJSONError("LLM provider returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise LLMJSONError("LLM provider returned non-object JSON")
        return value

    def _request_kwargs(
        self,
        profile: Mapping[str, Any],
        messages: Any,
        *,
        auto_router_cost_tier: Optional[str],
        json_output: bool,
        json_contract: bool,
        temperature: Optional[float],
        max_tokens: Optional[int],
        retry_tier: Optional[str],
        extra_kwargs: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Build detached SDK kwargs through the factory finalizer."""
        params = copy.deepcopy(dict(profile.get("params") or {}))
        profile_plugins = params.get("plugins")
        request_plugins = extra_kwargs.get("plugins")
        has_plugins = "plugins" in params or "plugins" in extra_kwargs

        def plugin_entries(value: Any) -> list[Any]:
            if isinstance(value, list):
                return copy.deepcopy(value)
            if value is None:
                return []
            return [copy.deepcopy(value)]

        merged_plugins = plugin_entries(profile_plugins) + plugin_entries(request_plugins)
        caller_auto_plugins = [
            plugin
            for plugin in plugin_entries(request_plugins)
            if isinstance(plugin, Mapping) and plugin.get("id") == "auto-router"
        ]
        configured_auto_plugins = [
            plugin
            for plugin in plugin_entries(profile_plugins)
            if isinstance(plugin, Mapping) and plugin.get("id") == "auto-router"
        ]
        preserved_auto_plugin = (
            caller_auto_plugins[0]
            if caller_auto_plugins
            else configured_auto_plugins[0]
            if configured_auto_plugins
            else None
        )
        merged_plugins = [
            plugin
            for plugin in merged_plugins
            if not (isinstance(plugin, Mapping) and plugin.get("id") == "auto-router")
        ]
        model = str(profile.get("model") or "")
        if preserved_auto_plugin is not None:
            merged_plugins.append(preserved_auto_plugin)
            has_plugins = True
        elif model == "openrouter/auto" and auto_router_cost_tier is not None:
            merged_plugins.append(
                {"id": "auto-router", "cost_tier": auto_router_cost_tier}
            )
            has_plugins = True

        configured_provider = profile.get("provider")
        if isinstance(configured_provider, Mapping):
            params["provider"] = copy.deepcopy(dict(configured_provider))
        params.update(copy.deepcopy(dict(extra_kwargs)))
        if has_plugins:
            params["plugins"] = merged_plugins
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if json_output and "response_format" not in params:
            params["response_format"] = {"type": "json_object"}
        if (
            json_contract
            and str(profile.get("model") or "") == "openrouter/auto"
            and "response_format" not in params
        ):
            params["response_format"] = {"type": "json_object"}
        finalized = ai_client_factory.finalize_chat_params(
            str(profile.get("model") or ""),
            params=params,
            temperature=temperature,
            is_openrouter=bool(profile.get("is_openrouter")),
            retry_tier=retry_tier,
            task_id=str(profile.get("task") or "default"),
        )
        finalized["messages"] = copy.deepcopy(messages)
        return finalized

    @staticmethod
    def _disable_sdk_retries(client: Any) -> Any:
        """Disable SDK-internal retries without imposing a competing timeout."""
        with_options = getattr(client, "with_options", None)
        if callable(with_options):
            return with_options(max_retries=0)
        return client

    @staticmethod
    def _fallback_profile_or_raise(
        error: Exception,
        task_id: str,
        provider_name: str,
        fallback_used: bool,
    ) -> bool:
        """Classify client construction failures and enforce one fallback."""
        if LLMRouter._quota_error(error):
            raise GameLLMTerminalError("quota") from error
        recovery = ai_client_factory.handle_provider_error(error, context=task_id)
        if recovery.get("should_fallback") and not fallback_used:
            return True
        raise error

    @staticmethod
    def _receipt(
        *,
        kind: str,
        call_id: Optional[str],
        attempt_id: Optional[str],
        attempt_number: Optional[int],
        task: str,
        profile: Mapping[str, Any],
        fallback: bool,
        started_at: Optional[float],
        retry_tier: Optional[str],
        error_type: Optional[str] = None,
        response: Any = None,
    ) -> RouterReceipt:
        requested = str(profile.get("model") or _UNKNOWN_MODEL)
        if response is None:
            actual_model = _UNKNOWN_MODEL
            prompt = cached = completion = None
            reported_cost = cost = None
            provenance = "error"
            priced = False
            usage_complete = False
            upstream = _UNKNOWN_PROVIDER
        else:
            (actual_model, _prompt, _cached, _completion, _reported_cost,
             cost, provenance, priced) = _response_cost(profile, response)
            prompt, cached, completion, reported_cost, usage_complete = _receipt_usage(response)
            upstream = _observed_upstream_provider(response)
        elapsed = None if started_at is None else max((time.monotonic() - started_at) * 1000.0, 0.0)
        return RouterReceipt(
            kind=kind,
            call_id=call_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            task=task,
            tier=str(profile.get("tier") or "unknown"),
            profile=str(profile.get("profile") or "default"),
            transport_retry=bool(attempt_number and attempt_number > 1),
            retry_tier=retry_tier,
            fallback=fallback,
            transport_provider=str(profile.get("provider_name") or _UNKNOWN_PROVIDER),
            observed_upstream_provider=upstream,
            requested_model=requested,
            resolved_model=actual_model,
            prompt_tokens=prompt,
            cached_tokens=cached,
            completion_tokens=completion,
            usage_complete=usage_complete,
            provider_reported_cost_usd=reported_cost,
            cost_usd=cost,
            cost_provenance=provenance,
            cost_complete=priced,
            error_type=error_type,
            elapsed_ms=elapsed,
            stats_snapshot=_freeze(get_usage_stats()),
        )

    def _emit_receipt(
        self,
        observer: Optional[Callable[[RouterReceipt, Any], Any]],
        raw: Any,
        **receipt_fields: Any,
    ) -> None:
        if observer is None:
            return
        _notify(observer, self._receipt(**receipt_fields), raw)

    @staticmethod
    def _receipt_observer(
        observer: Optional[Callable[[RouterReceipt, Any], Any]],
        g10_source_id: Optional[str] = None,
    ) -> Optional[Callable[[RouterReceipt, Any], Any]]:
        """Ensure receipt accounting, adding capture-only trace coverage."""
        from utils.llm_runtime import make_legacy_receipt_observer

        def observer_flag(name: str) -> bool:
            try:
                return bool(getattr(observer, name, False))
            except Exception:
                return False

        tracks_usage = observer_flag("_llm_tracks_usage")
        traces_provider = observer_flag("_llm_traces_provider")
        trace_site = None
        observer_g10_source_id = None
        g10_endpoint = None
        if (
            not traces_provider
            and os.environ.get("NEQ_G10_RECEIPT_TRACE") == "1"
            and os.environ.get("NEQ_G5_CAPTURE_RUN_ID")
        ):
            # G10 opts in only inside its owned capture process. Requiring the
            # existing run identity keeps ordinary calls and G5 goldens intact.
            trace_site = "llm_router"
            try:
                observer_g10_source_id = getattr(observer, "_llm_g10_source_id", None)
                g10_endpoint = getattr(observer, "_llm_g10_endpoint", None)
            except Exception:
                observer_g10_source_id = None
                g10_endpoint = None

        if trace_site is None:
            g10_source_id = None
        elif g10_source_id is None:
            g10_source_id = observer_g10_source_id

        needs_accounting = observer is None or not tracks_usage
        if not needs_accounting and trace_site is None:
            return observer

        automatic_observer_kwargs = {
            "track_usage": needs_accounting,
            "trace_site": trace_site,
        }
        if g10_source_id is not None:
            automatic_observer_kwargs["g10_source_id"] = g10_source_id
        if g10_endpoint is not None:
            automatic_observer_kwargs["g10_endpoint"] = g10_endpoint
        automatic_observer = make_legacy_receipt_observer(**automatic_observer_kwargs)
        if observer is None:
            return automatic_observer

        api_log_before_tracker = observer_flag("_llm_api_log_before_tracker")

        def combined_observer(receipt: RouterReceipt, raw: Any) -> None:
            if api_log_before_tracker and not tracks_usage:
                try:
                    observer(receipt, raw)
                finally:
                    automatic_observer(receipt, raw)
            else:
                automatic_observer(receipt, raw)
                observer(receipt, raw)

        return combined_observer

    def call(
        self,
        task: str,
        messages: Any,
        json_output: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        retry_tier: Optional[str] = None,
        *,
        observer: Optional[Callable[[RouterReceipt, Any], Any]] = None,
        model_tier: Optional[str] = None,
        empty_retry_limit: Optional[int] = None,
        json_contract: bool = False,
        g10_source_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Call the selected provider and account each response receipt once.

        ``g10_source_id`` is a capture-only allowlisted label; it is never sent
        to the provider and is ignored outside an identified G10 trace.
        """
        if model_tier not in (None, "simple", "complex"):
            raise ValueError("model_tier must be 'simple', 'complex', or None")
        if type(json_contract) is not bool:
            raise TypeError("json_contract must be a bool")
        task_id = str(task or "default")
        # Tier configuration is validated before profile/client construction,
        # so invalid settings cannot create a provider client or reach transport.
        auto_router_cost_tier = self._auto_router_task_cost_tier(task_id)
        # Validate task policy before profile/client construction so a missing
        # configuration cannot create a provider client or reach transport.
        ai_client_factory.get_task_sampling_policy(task_id)
        if empty_retry_limit is not None:
            if (
                type(empty_retry_limit) is not int
                or not 0 <= empty_retry_limit <= EMPTY_RESPONSE_RETRY_LIMIT
            ):
                raise ValueError("empty_retry_limit must be an integer from 0 to 2")
            if json_output:
                raise ValueError("empty-response recovery is not supported with json_output=True")
            if task_id != "dm_main":
                raise ValueError("empty-response recovery is only supported for dm_main text calls")
        observer = self._receipt_observer(observer, g10_source_id=g10_source_id)
        call_id = uuid.uuid4().hex
        attempt_number = 0
        primary_profile = self.resolve_profile(task_id, model_tier=model_tier)
        effective_empty_retry_limit = empty_retry_limit
        if (
            effective_empty_retry_limit is None
            and primary_profile.get("model") == "openrouter/auto"
        ):
            # Auto can resolve to a reasoning-only model for any task. Keep
            # this default tied to the requested model in the resolved profile,
            # not just the configured transport provider.
            effective_empty_retry_limit = EMPTY_RESPONSE_RETRY_LIMIT
        fallback_used = False
        profile = primary_profile
        empty_responses_for_provider = 0
        sdk_invocations = 0
        sdk_invocation_limit = (
            2 * (effective_empty_retry_limit + 1)
            if effective_empty_retry_limit is not None
            else None
        )
        try:
            client = self._disable_sdk_retries(ai_client_factory.create_chat_client())
        except Exception as exc:
            _record_error(task_id, profile, exc)
            self._emit_receipt(observer, None,
                kind="constructor_error", call_id=call_id, attempt_id=None,
                attempt_number=None, task=task_id, profile=profile,
                fallback=False, started_at=None, retry_tier=retry_tier,
                error_type=type(exc).__name__,
            )
            if not self._fallback_profile_or_raise(
                exc,
                task_id,
                str(profile.get("provider_name") or _UNKNOWN_PROVIDER),
                fallback_used,
            ):
                raise
            fallback_used = True
            previous_profile = profile
            profile = self.resolve_profile(task_id, use_fallback=True, model_tier=model_tier)
            _record_fallback_switch(task_id, previous_profile, profile)
            try:
                client = self._disable_sdk_retries(
                    ai_client_factory.create_chat_client(use_fallback=True)
                )
            except Exception as fallback_error:
                _record_error(task_id, profile, fallback_error)
                self._emit_receipt(observer, None,
                    kind="constructor_error", call_id=call_id, attempt_id=None,
                    attempt_number=None, task=task_id, profile=profile,
                    fallback=True, started_at=None, retry_tier=retry_tier,
                    error_type=type(fallback_error).__name__,
                )
                if self._quota_error(fallback_error):
                    raise GameLLMTerminalError("quota") from fallback_error
                raise

        response_attempts = 0
        while True:
            # Parameter assembly is deliberately outside the transport try block:
            # programming/content errors are not provider failures.
            request_kwargs = self._request_kwargs(
                profile,
                messages,
                auto_router_cost_tier=auto_router_cost_tier,
                json_output=json_output,
                json_contract=json_contract,
                temperature=temperature,
                max_tokens=max_tokens,
                retry_tier=retry_tier,
                extra_kwargs=kwargs,
            )
            attempt_id: Optional[str] = None
            started_at: Optional[float] = None
            sdk_attempt_started = False
            if sdk_invocation_limit is not None and sdk_invocations >= sdk_invocation_limit:
                raise EmptyProviderResponseError(
                    attempts=empty_responses_for_provider,
                    context=task_id,
                )
            try:
                client = self._disable_sdk_retries(client)
                # Count only an attempted provider completion. Client
                # construction and response parsing are not transports.
                attempt_number += 1
                attempt_id = uuid.uuid4().hex
                started_at = time.monotonic()
                with _USAGE_LOCK:
                    _usage_stats["transport_attempts"] += 1
                sdk_attempt_started = True
                sdk_invocations += 1
                maybe_inject_openrouter_transport_failure(
                    str(profile.get("provider_name") or _UNKNOWN_PROVIDER)
                )
                response = client.chat.completions.create(**request_kwargs)
            except Exception as exc:
                _record_error(task_id, profile, exc)
                self._emit_receipt(observer, None,
                    kind="transport_error" if sdk_attempt_started else "constructor_error",
                    call_id=call_id, attempt_id=attempt_id,
                    attempt_number=attempt_number if sdk_attempt_started else None,
                    task=task_id, profile=profile,
                    fallback=fallback_used, started_at=started_at,
                    retry_tier=retry_tier, error_type=type(exc).__name__,
                )
                if self._quota_error(exc):
                    raise GameLLMTerminalError("quota") from exc
                recovery = ai_client_factory.handle_provider_error(exc, context=task_id)
                if recovery.get("should_fallback") and not fallback_used:
                    fallback_used = True
                    previous_profile = profile
                    profile = self.resolve_profile(task_id, use_fallback=True, model_tier=model_tier)
                    _record_fallback_switch(task_id, previous_profile, profile)
                    if effective_empty_retry_limit is not None:
                        empty_responses_for_provider = 0
                    try:
                        client = self._disable_sdk_retries(
                            ai_client_factory.create_chat_client(use_fallback=True)
                        )
                    except Exception as fallback_error:
                        _record_error(task_id, profile, fallback_error)
                        self._emit_receipt(observer, None,
                            kind="constructor_error", call_id=call_id,
                            attempt_id=None, attempt_number=None, task=task_id,
                            profile=profile, fallback=True, started_at=None,
                            retry_tier=retry_tier,
                            error_type=type(fallback_error).__name__,
                        )
                        if self._quota_error(fallback_error):
                            raise GameLLMTerminalError("quota") from fallback_error
                        raise
                    continue
                raise

            # Count the provider response before parsing. Invalid structured
            # output is still a received, potentially billable response.
            _record_response(task_id, str(profile.get("model") or _UNKNOWN_MODEL), profile, response)
            # Parse a detached response before exposing the original SDK object
            # to trusted observers. A callback can mutate raw, but cannot
            # rewrite the materialized caller result or accounting snapshot.
            try:
                materialized_response = copy.deepcopy(response)
            except Exception:
                materialized_response = response
            response_class = classify_chat_completion(materialized_response)
            if (
                effective_empty_retry_limit is not None
                and response_class == CLASS_EMPTY_TRANSIENT
            ):
                empty_responses_for_provider += 1
                self._emit_receipt(observer, response,
                    kind="response", call_id=call_id, attempt_id=attempt_id,
                    attempt_number=attempt_number, task=task_id, profile=profile,
                    fallback=fallback_used, started_at=started_at,
                    retry_tier=retry_tier, response=response,
                )
                if empty_responses_for_provider <= effective_empty_retry_limit:
                    continue
                exhaustion_error = EmptyProviderResponseError(
                    attempts=empty_responses_for_provider,
                    context=task_id,
                )
                if not fallback_used:
                    recovery = ai_client_factory.handle_provider_error(
                        exhaustion_error,
                        context=task_id,
                    )
                    if recovery.get("should_fallback"):
                        fallback_used = True
                        previous_profile = profile
                        profile = self.resolve_profile(
                            task_id, use_fallback=True, model_tier=model_tier
                        )
                        _record_fallback_switch(task_id, previous_profile, profile)
                        empty_responses_for_provider = 0
                        try:
                            client = self._disable_sdk_retries(
                                ai_client_factory.create_chat_client(use_fallback=True)
                            )
                        except Exception as fallback_error:
                            _record_error(task_id, profile, fallback_error)
                            self._emit_receipt(observer, None,
                                kind="constructor_error", call_id=call_id,
                                attempt_id=None, attempt_number=None, task=task_id,
                                profile=profile, fallback=True, started_at=None,
                                retry_tier=retry_tier,
                                error_type=type(fallback_error).__name__,
                            )
                            if self._quota_error(fallback_error):
                                raise GameLLMTerminalError("quota") from fallback_error
                            raise
                        continue
                raise exhaustion_error
            if response_class in (CLASS_REFUSAL, CLASS_CONTENT_FILTER):
                terminal_kind = (
                    "refusal" if response_class == CLASS_REFUSAL else "content_filter"
                )
                self._emit_receipt(observer, response,
                    kind="response", call_id=call_id, attempt_id=attempt_id,
                    attempt_number=attempt_number, task=task_id, profile=profile,
                    fallback=fallback_used, started_at=started_at,
                    retry_tier=retry_tier, response=response,
                )
                raise GameLLMTerminalError(terminal_kind)
            try:
                content = self._content(materialized_response)
            except Exception:
                self._emit_receipt(observer, response,
                    kind="response", call_id=call_id, attempt_id=attempt_id,
                    attempt_number=attempt_number, task=task_id, profile=profile,
                    fallback=fallback_used, started_at=started_at,
                    retry_tier=retry_tier, response=response,
                )
                raise
            if not json_output:
                result = copy.deepcopy(content)
                self._emit_receipt(observer, response,
                    kind="response", call_id=call_id, attempt_id=attempt_id,
                    attempt_number=attempt_number, task=task_id, profile=profile,
                    fallback=fallback_used, started_at=started_at,
                    retry_tier=retry_tier, response=response,
                )
                return result
            response_attempts += 1
            try:
                result = self._json_object(content)
            except LLMJSONError as exc:
                # The response was already accounted for above; this is an
                # error diagnostic for the malformed payload, not another call.
                _record_error(task_id, profile, exc)
                self._emit_receipt(observer, response,
                    kind="response", call_id=call_id, attempt_id=attempt_id,
                    attempt_number=attempt_number, task=task_id, profile=profile,
                    fallback=fallback_used, started_at=started_at,
                    retry_tier=retry_tier, response=response,
                )
                if response_attempts >= 3:
                    raise LLMJSONError(
                        f"LLM JSON response exhausted retries for task {task_id}"
                    ) from exc
                continue
            self._emit_receipt(observer, response,
                kind="response", call_id=call_id, attempt_id=attempt_id,
                attempt_number=attempt_number, task=task_id, profile=profile,
                fallback=fallback_used, started_at=started_at,
                retry_tier=retry_tier, response=response,
            )
            return result

llm = LLMRouter()


# Module-level aliases keep session accounting easy to consume without
# coupling later runtime migrations to the singleton implementation.
def usage_stats_snapshot() -> Dict[str, Any]:
    return get_usage_stats()


__all__ = [
    "GameLLMError",
    "GameLLMTerminalError",
    "LLMJSONError",
    "LLMRouter",
    "get_usage_stats",
    "reset_usage_stats",
    "usage_stats_snapshot",
    "llm",
]
