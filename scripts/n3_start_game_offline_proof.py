# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Prove Capture_Arena start_game startup without provider or network access."""

from __future__ import annotations

import argparse
import importlib
import ipaddress
import json
import math
import os
import re
import socket
import stat
import sys
import tempfile
import threading
import time
import traceback
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional


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
MAX_COUNTER = 1_000_000
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
SAFE_MODEL_LABEL_PATTERN = re.compile(r"[A-Za-z0-9_.:/-]{1,128}\Z")
MODEL_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:\b(?:sk|pk|gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}\b|"
    r"\b[A-Za-z0-9_-]{40,}\b)"
)
SAFE_ORIGIN_PATH_PATTERN = re.compile(r"[A-Za-z0-9_./-]{1,180}\Z")
SAFE_ORIGIN_FUNCTION_PATTERN = re.compile(r"[A-Za-z0-9_<>,.-]{1,80}\Z")
SENSITIVE_DIAGNOSTIC_PATTERN = re.compile(
    r"(?i)(?:\.env\b|\b(?:config(?:uration)?|environment|environ|"
    r"api[_ -]?key|secret|token|password|credential|authorization|bearer|"
    r"private[_ -]?key)\b)"
)
PROOF_ORIGIN = "http://127.0.0.1:8360"
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


class ProviderCallRecorder:
    """Thread-safe counts for router and direct provider entry points."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.router_calls = 0
        self.provider_function_calls = 0
        self.update_check_calls = 0
        self.initial_narration_request: Optional[dict[str, Any]] = None

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
        normalized = str(host)
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
        parsed = int(port)
        return parsed if parsed <= 65535 else None
    return None


def _address_parts(address: Any) -> tuple[Any, Any]:
    if isinstance(address, tuple) and address:
        return address[0], address[1] if len(address) > 1 else None
    return address, None


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
    """Observe socket destinations and refuse every non-loopback operation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: list[dict[str, Any]] = []
        self._attempt_count = 0
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

    def _record_attribution(self, host: Any) -> None:
        project_frames, library_packages = _collect_egress_origin(
            traceback.extract_stack(limit=MAX_EGRESS_STACK_FRAMES),
            self._sandbox_root,
        )
        hostname = _hostname_class(host)
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

    def _record(self, host: Any, port: Any, record_loopback: bool) -> str:
        host_class = _host_class(host)
        if host_class == "non_loopback" or record_loopback:
            entry = {"host_class": host_class, "port": _safe_port(port)}
            with self._lock:
                self._attempt_count = min(self._attempt_count + 1, MAX_COUNTER)
                if len(self._attempts) < MAX_RECORDED_EGRESS:
                    self._attempts.append(entry)
        if host_class == "non_loopback":
            self._record_attribution(host)
            raise EgressBlocked("non-loopback destination refused")
        return host_class

    def _connect(self, sock: Any, address: Any, method_name: str) -> Any:
        original = self._originals[(socket.socket, method_name)]
        if getattr(sock, "family", None) == getattr(socket, "AF_UNIX", object()):
            return original(sock, address)
        host, port = _address_parts(address)
        self._record(host, port, record_loopback=True)
        return original(sock, address)

    def _create_connection(self, address: Any, *args: Any, **kwargs: Any) -> Any:
        original = self._originals[(socket, "create_connection")]
        host, port = _address_parts(address)
        self._record(host, port, record_loopback=True)
        return original(address, *args, **kwargs)

    def _getaddrinfo(
        self, host: Any, port: Any, *args: Any, **kwargs: Any
    ) -> Any:
        original = self._originals[(socket, "getaddrinfo")]
        self._record(host, port, record_loopback=False)
        return original(host, port, *args, **kwargs)

    def install(self) -> "EgressGuard":
        if self._active:
            return self
        self._socket_class = socket.socket
        targets = (
            (self._socket_class, "connect"),
            (self._socket_class, "connect_ex"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
        )
        for owner, name in targets:
            original = getattr(owner, name)
            self._originals[(owner, name)] = original

            if owner is socket.socket:
                def wrapper(*args: Any, _name: str = name, **kwargs: Any) -> Any:
                    return self._connect(*args, _name, **kwargs)
            elif name == "create_connection":
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return self._create_connection(*args, **kwargs)
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

    def set(self, owner: Any, name: str, value: Any) -> None:
        if not hasattr(owner, name):
            raise ProofSetupError("required provider tripwire target is unavailable")
        self._originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def restore(self) -> None:
        for owner, name, original in reversed(self._originals):
            setattr(owner, name, original)
        self._originals.clear()


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
        except EgressBlocked:
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
) -> None:
    def provider_tripwire(*args: Any, **kwargs: Any) -> None:
        recorder.block_provider_function(*args, **kwargs)

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
            patches.set(owner, method_name, provider_tripwire)


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

    report = build_preintegrate_report(
        stub_call_counts=recorder.stub_counts_snapshot(),
        egress_attempts=egress_guard.snapshot(),
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
        choices=("prove", "preintegrate"),
        default="prove",
        help=(
            "prove runs the start_game proof (default); preintegrate runs the "
            "offline module scan/integration. Run preintegrate and prove as "
            "separate process invocations."
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
