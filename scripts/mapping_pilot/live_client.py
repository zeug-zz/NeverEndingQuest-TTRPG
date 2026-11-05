# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Lazy, receipt-safe router adapter for the D1 cartographer."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, MutableSequence
from typing import Any, Optional, Protocol


ROUTER_TASK = "location_generator"
_UNKNOWN = "unknown"
_AUTO_MODEL = "openrouter/auto"
_EXPECTED_PROFILE = "production-auto"
_EXPECTED_PROVIDER = "openrouter"
_TERMINAL_KINDS = frozenset({"quota", "refusal", "content_filter"})
_MISSING = object()
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9._:/@+ -]{1,200}$")


class RouterLike(Protocol):
    """The provider-free part of the existing router boundary."""

    def resolve_profile(self, task: str) -> Mapping[str, Any]:
        """Resolve a task without constructing a provider client."""

    def call(
        self,
        task: str,
        messages: Any,
        json_output: bool = False,
        *,
        observer: Optional[Callable[[Any, Any], Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke the configured router and optionally observe receipts."""


class LiveClientPreflightError(RuntimeError):
    """Raised when D1 cannot use the required production-auto route."""

    def __init__(self, observed_profile: str, reason: str) -> None:
        self.observed_profile = observed_profile
        self.reason = reason
        super().__init__(
            "mapping-pilot live client requires production-auto; "
            "observed profile=%s reason=%s" % (observed_profile, reason)
        )


def create_live_client(
    receipts: MutableSequence[dict[str, Any]],
    *,
    router: Optional[RouterLike] = None,
) -> Callable[[str], str]:
    """Return the cartographer's ``Callable[[str], str]`` live client.

    Router imports and route resolution are deferred until this factory is
    called. The route preflight is read-only; it does not construct a provider
    client or make a request. Receipt records contain a closed allowlist and a
    prompt hash only; the prompt and observer's raw response are never kept.
    """
    if not callable(getattr(receipts, "append", None)):
        raise TypeError("receipt sink must support append")
    if router is None:
        from utils.llm_router import llm

        router = llm

    _preflight(router)
    invocation_index = 0

    def client(prompt: str) -> str:
        nonlocal invocation_index
        if not isinstance(prompt, str):
            raise TypeError("cartographer prompt must be text")

        invocation_index += 1
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        try:
            resolved_profile = _preflight(router)
        except LiveClientPreflightError as exc:
            receipts.append(
                _empty_receipt(
                    invocation_index=invocation_index,
                    prompt_sha256=prompt_sha256,
                    profile=exc.observed_profile,
                    kind="preflight_error",
                    error_type=type(exc).__name__,
                )
            )
            raise

        invocation_receipts: list[dict[str, Any]] = []

        def observe(receipt: Any, _raw_response: Any) -> None:
            record = _receipt_metadata(
                receipt,
                invocation_index=invocation_index,
                prompt_sha256=prompt_sha256,
            )
            invocation_receipts.append(record)
            receipts.append(record)

        try:
            response = router.call(
                task=ROUTER_TASK,
                messages=[{"role": "user", "content": prompt}],
                json_output=True,
                observer=observe,
            )
        except Exception as exc:
            terminal_kind = _terminal_kind(exc)
            if invocation_receipts:
                record = invocation_receipts[-1]
                if record["error_type"] in (None, _UNKNOWN):
                    record["error_type"] = _exception_type(exc)
                record["terminal_kind"] = terminal_kind
            else:
                error_record = _empty_receipt(
                    invocation_index=invocation_index,
                    prompt_sha256=prompt_sha256,
                    profile=_text(resolved_profile.get("profile")),
                    kind="call_error",
                    error_type=_exception_type(exc),
                )
                error_record.update(
                    {
                        "transport_provider": _text(
                            resolved_profile.get("provider_name")
                        ),
                        "requested_model": _text(resolved_profile.get("model")),
                        "terminal_kind": terminal_kind,
                    }
                )
                receipts.append(error_record)
            raise

        try:
            if not isinstance(response, Mapping):
                raise TypeError("router result is not a JSON object")
            return json.dumps(
                dict(response),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except Exception as exc:
            if invocation_receipts:
                record = invocation_receipts[-1]
                if record["error_type"] in (None, _UNKNOWN):
                    record["error_type"] = _exception_type(exc)
            else:
                receipts.append(
                    _empty_receipt(
                        invocation_index=invocation_index,
                        prompt_sha256=prompt_sha256,
                        profile=_text(resolved_profile.get("profile")),
                        kind="serialization_error",
                        error_type=_exception_type(exc),
                    )
                )
            raise ValueError("router result is not a serializable JSON object") from None

    return client


def _preflight(router: RouterLike) -> Mapping[str, Any]:
    """Resolve and require the unpinned production-auto route."""
    try:
        profile = router.resolve_profile(ROUTER_TASK)
    except Exception:
        raise LiveClientPreflightError(_UNKNOWN, "profile_resolution_failed") from None

    if not isinstance(profile, Mapping):
        raise LiveClientPreflightError(_UNKNOWN, "profile_unavailable")

    observed_profile = _text(profile.get("profile"))
    reason = None
    if observed_profile != _EXPECTED_PROFILE:
        reason = "profile_mismatch"
    elif profile.get("model") != _AUTO_MODEL:
        reason = "model_not_auto"
    elif profile.get("provider_name") != _EXPECTED_PROVIDER:
        reason = "provider_mismatch"
    elif profile.get("is_openrouter") is not True:
        reason = "provider_not_openrouter"
    elif profile.get("explicit_model") is not False:
        reason = "model_override_present"

    if reason is not None:
        raise LiveClientPreflightError(observed_profile, reason)
    return profile


def _receipt_metadata(
    receipt: Any,
    *,
    invocation_index: int,
    prompt_sha256: str,
) -> dict[str, Any]:
    """Project one RouterReceipt onto the adapter's fixed metadata allowlist."""
    resolved_model = _read_field(receipt, "resolved_model")
    return {
        "invocation_index": invocation_index,
        "prompt_sha256": prompt_sha256,
        "kind": _text(_read_field(receipt, "kind")),
        "call_id": _identifier(_read_field(receipt, "call_id")),
        "attempt_id": _identifier(_read_field(receipt, "attempt_id")),
        "attempt_index": _positive_integer(_read_field(receipt, "attempt_number")),
        "task": _text(_read_field(receipt, "task")),
        "tier": _text(_read_field(receipt, "tier")),
        "profile": _text(_read_field(receipt, "profile")),
        "transport_retry": _optional_boolean(
            _read_field(receipt, "transport_retry")
        ),
        "retry_tier": _optional_text(_read_field(receipt, "retry_tier")),
        "fallback": _optional_boolean(_read_field(receipt, "fallback")),
        "transport_provider": _text(
            _read_field(receipt, "transport_provider")
        ),
        "observed_upstream_provider": _text(
            _read_field(receipt, "observed_upstream_provider")
        ),
        "requested_model": _text(_read_field(receipt, "requested_model")),
        "resolved_model": _resolved_model_text(resolved_model),
        "prompt_tokens": _nonnegative_integer(
            _read_field(receipt, "prompt_tokens")
        ),
        "cached_tokens": _nonnegative_integer(
            _read_field(receipt, "cached_tokens")
        ),
        "completion_tokens": _nonnegative_integer(
            _read_field(receipt, "completion_tokens")
        ),
        "usage_complete": _optional_boolean(
            _read_field(receipt, "usage_complete")
        ),
        "provider_reported_cost_usd": _nonnegative_number(
            _read_field(receipt, "provider_reported_cost_usd")
        ),
        "cost_usd": _nonnegative_number(_read_field(receipt, "cost_usd")),
        "cost_provenance": _text(_read_field(receipt, "cost_provenance")),
        "cost_complete": _optional_boolean(
            _read_field(receipt, "cost_complete")
        ),
        "error_type": _optional_text(_read_field(receipt, "error_type")),
        "terminal_kind": None,
        "elapsed_ms": _nonnegative_number(_read_field(receipt, "elapsed_ms")),
    }


def _empty_receipt(
    *,
    invocation_index: int,
    prompt_sha256: str,
    profile: str,
    kind: str,
    error_type: str,
) -> dict[str, Any]:
    """Create a safe call-level record when no router receipt was observed."""
    return {
        "invocation_index": invocation_index,
        "prompt_sha256": prompt_sha256,
        "kind": kind,
        "call_id": None,
        "attempt_id": None,
        "attempt_index": None,
        "task": ROUTER_TASK,
        "tier": _UNKNOWN,
        "profile": profile,
        "transport_retry": None,
        "retry_tier": None,
        "fallback": None,
        "transport_provider": _UNKNOWN,
        "observed_upstream_provider": _UNKNOWN,
        "requested_model": _UNKNOWN,
        "resolved_model": _UNKNOWN,
        "prompt_tokens": None,
        "cached_tokens": None,
        "completion_tokens": None,
        "usage_complete": None,
        "provider_reported_cost_usd": None,
        "cost_usd": None,
        "cost_provenance": _UNKNOWN,
        "cost_complete": None,
        "error_type": error_type,
        "terminal_kind": None,
        "elapsed_ms": None,
    }


def _read_field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, _MISSING)
    try:
        return getattr(value, name)
    except Exception:
        return _MISSING


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return _UNKNOWN
    normalized = value.strip()
    if not normalized or not _SAFE_LABEL.fullmatch(normalized):
        return _UNKNOWN
    if normalized.lower() == _UNKNOWN:
        return _UNKNOWN
    return normalized


def _optional_text(value: Any) -> Any:
    if value is _MISSING:
        return _UNKNOWN
    if value is None:
        return None
    return _text(value)


def _resolved_model_text(value: Any) -> str:
    model = _text(value)
    if model.lower() in ("", _UNKNOWN, _AUTO_MODEL):
        return _UNKNOWN
    return model


def _identifier(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    if not value.isascii() or not value.isprintable():
        return None
    return value


def _positive_integer(value: Any) -> Optional[int]:
    if type(value) is not int or value < 1:
        return None
    return value


def _nonnegative_integer(value: Any) -> Optional[int]:
    if type(value) is not int or value < 0:
        return None
    return value


def _optional_boolean(value: Any) -> Any:
    if value is _MISSING:
        return _UNKNOWN
    if value is None:
        return None
    if type(value) is bool:
        return value
    return _UNKNOWN


def _nonnegative_number(value: Any) -> Optional[float | int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _exception_type(error: Exception) -> str:
    name = type(error).__name__
    if name.isascii() and name.isidentifier() and len(name) <= 80:
        return name
    return "unknown"


def _terminal_kind(error: Exception) -> Optional[str]:
    try:
        value = getattr(error, "terminal_kind", None)
    except Exception:
        return None
    return value if isinstance(value, str) and value in _TERMINAL_KINDS else None


__all__ = [
    "LiveClientPreflightError",
    "ROUTER_TASK",
    "RouterLike",
    "create_live_client",
]
