# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
AI Client Factory - Multi-Provider AI Client Management
Provides unified interface for OpenAI, OpenRouter, and future providers
"""

import math
from typing import Optional, Dict, Any
import httpx
from openai import APITimeoutError, OpenAI
from utils.enhanced_logger import debug, info, warning, error
from utils.llm_transport_deadline import create_deadline_http_client
from utils.provider_log_safety import configure_provider_log_safety
from utils.provider_response_recovery import EmptyProviderResponseError

# Track fallback status to avoid spamming notifications
_fallback_status = {
    'has_triggered': False,
    'primary_provider': None,
    'fallback_provider': None,
    'last_error': None,
    'fallback_count': 0,
    'notification_emitted': False,
}

# TABLETOP MODE: GPT-5 chat parameter shim defaults.
GPT5_INCLUDE_LEGACY_TEMPERATURE = False


def _is_gpt5_model(model_name: Optional[str]) -> bool:
    """Return True for supported direct-OpenAI reasoning model families.

    Keep the preferred GPT-6 model explicit rather than treating every future
    ``gpt-6`` identifier as compatible with the GPT-5 parameter contract.
    """
    if not model_name:
        return False
    normalized_model = str(model_name).lower()
    return normalized_model.startswith("gpt-5") or normalized_model == "gpt-6-luna"


def _resolve_gpt5_chat_profile(
    task_id: str,
    retry_tier: Optional[str] = None,
) -> Dict[str, str]:
    """Resolve GPT-5 reasoning and verbosity settings for a task family."""
    normalized_task_id = (task_id or "default").lower()

    if "validation" in normalized_task_id or normalized_task_id in {"action_prediction", "updates"}:
        reasoning_effort = "low"
        verbosity = "low"
    elif "compression" in normalized_task_id:
        reasoning_effort = "low"
        verbosity = "low"
    elif (
        "summary" in normalized_task_id
        or "chronicle" in normalized_task_id
        or "diary" in normalized_task_id
    ):
        reasoning_effort = "low"
        verbosity = "medium"
    else:
        reasoning_effort = "medium"
        verbosity = "medium"

    if retry_tier in {"high", "retry"}:
        try:
            from model_config import GPT5_USE_HIGH_REASONING_ON_RETRY

            if retry_tier == "high" or GPT5_USE_HIGH_REASONING_ON_RETRY:
                reasoning_effort = "high"
        except ImportError:
            reasoning_effort = "high"

    return {
        "reasoning_effort": reasoning_effort,
        "verbosity": verbosity,
    }


class TaskSamplingPolicyError(ValueError):
    """Raised when a facade task has no valid sampling policy."""


def get_task_sampling_policy(task_id: str) -> Dict[str, Dict[str, Any]]:
    """Return a detached, validated family-sampling policy for a task."""
    try:
        from model_config import TASK_POLICY_SAMPLING
    except ImportError as exc:
        raise TaskSamplingPolicyError(
            "TASK_POLICY_SAMPLING is unavailable for task %r" % task_id
        ) from exc

    task_key = str(task_id or "")
    if not isinstance(TASK_POLICY_SAMPLING, dict):
        raise TaskSamplingPolicyError("TASK_POLICY_SAMPLING must be a mapping")
    policy = TASK_POLICY_SAMPLING.get(task_key)
    if not isinstance(policy, dict):
        raise TaskSamplingPolicyError(
            "Missing TASK_POLICY_SAMPLING policy for task %r" % task_key
        )

    reasoning = policy.get("reasoning")
    non_reasoning = policy.get("non_reasoning")
    if not isinstance(reasoning, dict) or reasoning.get("family") != "reasoning":
        raise TaskSamplingPolicyError(
            "TASK_POLICY_SAMPLING[%r] must define a reasoning-family entry" % task_key
        )
    if "temperature" in reasoning or "top_p" in reasoning:
        raise TaskSamplingPolicyError(
            "TASK_POLICY_SAMPLING[%r] reasoning entry must omit temperature and top_p"
            % task_key
        )
    if (
        not isinstance(non_reasoning, dict)
        or non_reasoning.get("family") != "non_reasoning"
    ):
        raise TaskSamplingPolicyError(
            "TASK_POLICY_SAMPLING[%r] must define a non-reasoning-family entry"
            % task_key
        )

    temperature = non_reasoning.get("temperature")
    try:
        temperature_is_finite = math.isfinite(float(temperature))
    except (OverflowError, TypeError, ValueError):
        temperature_is_finite = False
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not temperature_is_finite
    ):
        raise TaskSamplingPolicyError(
            "TASK_POLICY_SAMPLING[%r] non-reasoning entry requires numeric temperature"
            % task_key
        )
    top_p = non_reasoning.get("top_p")
    if "top_p" in non_reasoning:
        try:
            top_p_is_finite = math.isfinite(float(top_p))
        except (OverflowError, TypeError, ValueError):
            top_p_is_finite = False
        if (
            isinstance(top_p, bool)
            or not isinstance(top_p, (int, float))
            or not top_p_is_finite
        ):
            raise TaskSamplingPolicyError(
                "TASK_POLICY_SAMPLING[%r] top_p must be numeric when configured"
                % task_key
            )

    return {
        "reasoning": dict(reasoning),
        "non_reasoning": dict(non_reasoning),
    }


def _get_actual_provider(use_fallback: bool = False) -> tuple[str, bool]:
    """
    Single source of truth for determining which provider to actually use.
    
    This function resolves the split-brain issue where configuration says OpenRouter
    but runtime conditions (missing API key) require OpenAI fallback.
    
    Args:
        use_fallback: Force OpenAI regardless of configuration
        
    Returns:
        Tuple of (provider_name: str, is_openrouter: bool)
        - provider_name: "openrouter" or "openai"
        - is_openrouter: True if OpenRouter can actually be used
    """
    try:
        import config
        from model_config import LLM_PROVIDER, ENABLE_PROVIDER_FALLBACK
        
        # Check if fallback is forced
        if use_fallback or not ENABLE_PROVIDER_FALLBACK:
            return "openai", False
        
        # Check if OpenRouter is configured AND has API key
        if LLM_PROVIDER == "openrouter":
            api_key = getattr(config, 'OPENROUTER_API_KEY', '')
            if api_key:
                return "openrouter", True
            else:
                warning("OPENROUTER_API_KEY not set, falling back to OpenAI", 
                       category="ai_provider")
        
        return "openai", False
        
    except ImportError:
        # Safe fallback if imports fail
        return "openai", False


def create_chat_client(use_fallback: bool = False) -> OpenAI:
    """
    Create chat/LLM client based on configuration.
    
    Args:
        use_fallback: Force fallback to OpenAI (used internally after failures)
        
    Returns:
        OpenAI client configured for the selected provider
        
    Provider Selection Logic:
        1. If use_fallback=True or ENABLE_PROVIDER_FALLBACK=False -> OpenAI
        2. If LLM_PROVIDER="openrouter" and OPENROUTER_API_KEY set -> OpenRouter
        3. Otherwise -> OpenAI (safe default)
    """
    global _fallback_status

    # Keep provider transport logging safe at the shared factory boundary.
    # Logging policy failure must not alter provider selection or prevent the
    # existing client/fallback path from running.
    try:
        configure_provider_log_safety()
    except Exception:
        warning(
            "Provider log safety initialization degraded; continuing client creation",
            category="ai_provider",
        )
    
    # Use single source of truth for provider selection
    provider, is_openrouter = _get_actual_provider(use_fallback)
    
    try:
        import config
        from model_config import (
            API_CONNECT_TIMEOUT_SECONDS,
            API_TIMEOUT_SECONDS,
            OPENROUTER_BASE_URL,
            OPENROUTER_HTTP_REFERER,
            OPENROUTER_APP_TITLE,
        )
    except ImportError as e:
        error(f"Failed to import config: {e}")
        raise
    
    # Build one factory-owned wall-clock deadline across connect, headers, and
    # body reads; the HTTPX per-operation timeout alone can be extended by
    # keep-alive response chunks. Callers must not add parallel per-call bounds.
    client_timeout = httpx.Timeout(
        API_TIMEOUT_SECONDS,
        connect=API_CONNECT_TIMEOUT_SECONDS,
    )
    http_client = create_deadline_http_client(
        timeout=client_timeout,
        deadline_seconds=API_TIMEOUT_SECONDS,
    )

    # Create client with appropriate configuration
    if is_openrouter:
        api_key = getattr(config, 'OPENROUTER_API_KEY', '')
        debug("Creating OpenRouter client for chat", category="ai_provider")
        try:
            client = OpenAI(
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                timeout=client_timeout,
                http_client=http_client,
                default_headers={
                    "HTTP-Referer": OPENROUTER_HTTP_REFERER,
                    "X-Title": OPENROUTER_APP_TITLE
                }
            )
        except BaseException:
            http_client.close()
            raise

        # Track primary provider selection.  A forced fallback may occur after
        # a recorded OpenRouter failure; preserve that origin for the existing
        # once-per-session notification path.
        if not (use_fallback and _fallback_status.get('primary_provider')):
            _fallback_status['primary_provider'] = 'openrouter'
        _fallback_status['fallback_provider'] = 'openai'
        
    else:
        api_key = getattr(config, 'OPENAI_API_KEY', '')
        debug("Creating OpenAI client for chat", category="ai_provider")
        try:
            client = OpenAI(
                api_key=api_key,
                timeout=client_timeout,
                http_client=http_client,
            )
        except BaseException:
            http_client.close()
            raise
        if not (use_fallback and _fallback_status.get('primary_provider')):
            _fallback_status['primary_provider'] = 'openai'
        _fallback_status['fallback_provider'] = 'openai'

    # SDK transport child loggers may be created during construction. Reapply
    # the policy at this boundary without allowing logging setup to affect the
    # existing client path.
    try:
        configure_provider_log_safety()
    except Exception:
        warning(
            "Provider log safety post-construction degraded; continuing client creation",
            category="ai_provider",
        )
    
    return client


def get_chat_model_name() -> str:
    """
    Get the appropriate chat model name based on provider configuration.
    
    Returns:
        Model name string for use in API calls
    """
    try:
        import config
        from model_config import LLM_PROVIDER, OPENROUTER_CHAT_MODEL, DM_MAIN_MODEL
        
        provider = getattr(config, 'LLM_PROVIDER', 'openai')
        
        if provider == "openrouter" and getattr(config, 'OPENROUTER_API_KEY', ''):
            return OPENROUTER_CHAT_MODEL
        else:
            return DM_MAIN_MODEL
            
    except ImportError:
        # Safe fallback if imports fail
        return "gpt-4.1-2025-04-14"


def get_model_display_name() -> str:
    """
    Get human-readable model name for UI display.
    
    Returns:
        Display name string (e.g., "Kimi K2.5" or "GPT-4.1")
    """
    model = get_chat_model_name()
    
    # Map model IDs to display names
    display_names = {
        "moonshotai/kimi-k2.5": "Kimi K2.5",
        "anthropic/claude-3.5-sonnet": "Claude 3.5 Sonnet",
        "google/gemini-2.0-flash-exp": "Gemini 2.0 Flash",
        "openai/gpt-4.1-2025-04-14": "GPT-4.1",
        "gpt-4.1-2025-04-14": "GPT-4.1",
        "gpt-4.1-mini-2025-04-14": "GPT-4.1 Mini",
        "gpt-5.4-mini-2026-03-17": "GPT-5.4 Mini",
        "openai/gpt-5.4-mini-2026-03-17": "GPT-5.4 Mini",
        "gpt-5.6-luna": "GPT-5.6 Luna",
        "openai/gpt-5.6-luna": "GPT-5.6 Luna",
    }
    
    return display_names.get(model, model)


def handle_provider_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """
    Handle provider errors and determine if fallback should occur.
    
    Args:
        error: The exception that occurred
        context: Additional context about what operation failed
        
    Returns:
        Dict with error details and fallback recommendation
    """
    global _fallback_status
    
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # Check if this is a retryable error
    retryable_errors = [
        'rate limit', 'timeout', 'connection', '503', '502', '504',
        'overloaded', 'unavailable', 'internal server error', '429'
    ]
    
    # TABLETOP MODE: EmptyProviderResponseError is a fork-native retryable
    # class; existing substring classification is unchanged.
    should_fallback = (
        any(err in error_str for err in retryable_errors)
        or isinstance(error, EmptyProviderResponseError)
        # The OpenAI SDK normalizes httpx timeouts to APITimeoutError with the
        # message "Request timed out."; classify that exact transient type
        # without broadening APIConnectionError or other SDK failures.
        or isinstance(error, APITimeoutError)
    )
    
    result = {
        'error': str(error),
        'error_type': error_type,
        'context': context,
        'should_fallback': should_fallback,
        'fallback_message': None
    }
    
    if should_fallback and not _fallback_status['has_triggered']:
        _fallback_status['has_triggered'] = True
        _fallback_status['notification_emitted'] = False
        _fallback_status['last_error'] = str(error)
        _fallback_status['fallback_count'] += 1
        
        # Create user-friendly fallback message
        primary = _fallback_status.get('primary_provider', 'unknown')
        fallback = _fallback_status.get('fallback_provider', 'openai')
        
        if primary != fallback:
            result['fallback_message'] = (
                f"Primary AI provider ({primary}) temporarily unavailable. "
                f"Falling back to {fallback}. Your game will continue normally."
            )
            warning(
                f"Provider fallback triggered: {primary} -> {fallback}. "
                f"Error: {error}",
                category="ai_provider"
            )
    
    return result


def reset_fallback_status():
    """Reset fallback tracking (call at game start)."""
    global _fallback_status
    _fallback_status = {
        'has_triggered': False,
        'primary_provider': None,
        'fallback_provider': None,
        'last_error': None,
        'fallback_count': 0,
        'notification_emitted': False,
    }
    debug("Fallback status reset", category="ai_provider")


def get_fallback_notification() -> Optional[str]:
    """
    Get fallback notification message if one should be shown.
    
    Returns:
        Message string to display to user, or None if no notification needed
    """
    global _fallback_status
    
    if (
        _fallback_status['has_triggered']
        and not _fallback_status['notification_emitted']
        and _fallback_status['primary_provider'] != _fallback_status['fallback_provider']
    ):
        _fallback_status['notification_emitted'] = True
        return (
            f"[System] AI provider switched from {_fallback_status['primary_provider']} "
            f"to {_fallback_status['fallback_provider']} due to service issue. "
            f"Your game session continues normally."
        )
    
    return None


def finalize_chat_params(
    model: str,
    params: Optional[Dict[str, Any]] = None,
    temperature: Optional[float] = None,
    is_openrouter: bool = False,
    retry_tier: Optional[str] = None,
    *,
    task_id: str,
) -> Dict[str, Any]:
    """Assemble provider-safe chat completion kwargs.

    ``task_id`` and ``retry_tier`` are factory context only.  They select the
    direct-OpenAI reasoning policy, but are never forwarded to the SDK.  The
    profile parameter envelope is normalized here so callers can pass either
    the legacy nested ``extra_body`` shape or portable profile fields without
    leaking vendor-only fields to direct OpenAI.
    """
    reasoning_model = _is_gpt5_model(model)
    task_policy = None if reasoning_model else get_task_sampling_policy(task_id)
    selected_sampling = (
        task_policy["non_reasoning"]
        if task_policy is not None
        else None
    )
    source = dict(params or {})
    source.pop("model", None)
    source.pop("use_openrouter", None)
    source.pop("fallback_strategy", None)
    source.pop("task_id", None)
    source.pop("retry_tier", None)

    # ``max_tokens`` is the portable facade spelling.  Reasoning-family
    # OpenAI models require the newer completion-token field; OpenRouter and
    # legacy models retain the original spelling.  Do this once at the factory
    # boundary so callers cannot emit both fields or duplicate model kwargs.
    requested_max_tokens = source.pop("max_tokens", None)
    if requested_max_tokens is not None and "max_completion_tokens" not in source:
        source["max_completion_tokens" if _is_gpt5_model(model) else "max_tokens"] = requested_max_tokens

    supplied_extra_body = source.pop("extra_body", None)
    if isinstance(supplied_extra_body, dict):
        if set(supplied_extra_body) == {"extra_body"} and isinstance(
            supplied_extra_body.get("extra_body"), dict
        ):
            supplied_extra_body = supplied_extra_body["extra_body"]
    else:
        supplied_extra_body = {}

    # Portable extensions are carried by one SDK-compatible extra_body envelope.
    extra_body = dict(supplied_extra_body)
    for extension_key in (
        "provider",
        "reasoning",
        "reasoning_effort",
        "verbosity",
        "thinking",
        "plugins",
    ):
        extension_value = source.pop(extension_key, None)
        if extension_value is None:
            continue
        if extension_key == "plugins" and isinstance(extra_body.get("plugins"), list):
            existing_plugins = extra_body["plugins"]
            incoming_plugins = extension_value if isinstance(extension_value, list) else [extension_value]
            extra_body["plugins"] = existing_plugins + incoming_plugins
        elif (
            extension_key in {"provider", "reasoning"}
            and isinstance(extra_body.get(extension_key), dict)
            and isinstance(extension_value, dict)
        ):
            merged_extension = dict(extra_body[extension_key])
            merged_extension.update(extension_value)
            extra_body[extension_key] = merged_extension
        else:
            extra_body[extension_key] = extension_value

    if is_openrouter:
        source.pop("temperature", None)
        source.pop("top_p", None)
        result: Dict[str, Any] = {"model": model}
        result.update(source)
        if not reasoning_model:
            assert selected_sampling is not None
            result["temperature"] = selected_sampling["temperature"]
            if "top_p" in selected_sampling:
                result["top_p"] = selected_sampling["top_p"]
        if extra_body:
            result["extra_body"] = extra_body
        return result

    # TABLETOP MODE: Direct OpenAI must not receive OpenRouter routing lists or
    # provider/plugin/transform/thinking extensions.
    source.pop("models", None)
    source.pop("transforms", None)
    result = {"model": model}
    if _is_gpt5_model(model):
        source.pop("temperature", None)
        source.pop("top_p", None)
        result.update(source)
        result.update(_resolve_gpt5_chat_profile(task_id, retry_tier=retry_tier))
        # GPT-5-family APIs omit legacy sampling controls by default.  Ignore
        # any profile values rather than allowing them to override the policy.
        if GPT5_INCLUDE_LEGACY_TEMPERATURE and temperature is not None:
            result["temperature"] = temperature
        return result

    source.pop("temperature", None)
    source.pop("top_p", None)
    result.update(source)
    assert selected_sampling is not None
    result["temperature"] = selected_sampling["temperature"]
    if "top_p" in selected_sampling:
        result["top_p"] = selected_sampling["top_p"]
    return result


def get_provider_status() -> Dict[str, Any]:
    """
    Get current provider status for diagnostics.
    
    Returns:
        Dict with provider configuration and fallback status
    """
    global _fallback_status
    
    try:
        import config
        from model_config import LLM_PROVIDER, ENABLE_PROVIDER_FALLBACK
        
        current_provider = getattr(config, 'LLM_PROVIDER', 'openai')
        actual_provider = _fallback_status.get('primary_provider', current_provider)
        
        return {
            'configured_provider': current_provider,
            'active_provider': actual_provider,
            'model': get_chat_model_name(),
            'model_display': get_model_display_name(),
            'fallback_enabled': ENABLE_PROVIDER_FALLBACK,
            'fallback_triggered': _fallback_status['has_triggered'],
            'fallback_count': _fallback_status['fallback_count'],
            'last_error': _fallback_status['last_error']
        }
    except ImportError:
        return {
            'configured_provider': 'unknown',
            'active_provider': 'unknown',
            'model': 'unknown',
            'error': 'Failed to load configuration'
        }


# ============================================================================
# Future Provider Functions (Phase 2+ Stubs)
# ============================================================================

def create_image_client() -> OpenAI:
    """
    Create image generation client (Phase 2).
    Currently returns OpenAI client.
    """
    try:
        import config
        from model_config import IMAGE_PROVIDER
        
        if IMAGE_PROVIDER == "openrouter":
            # Future: Add OpenRouter image support
            warning("OpenRouter image generation not yet implemented, using OpenAI")
        
        return OpenAI(api_key=getattr(config, 'OPENAI_API_KEY', ''))
        
    except ImportError:
        return OpenAI(api_key="")


def create_tts_client() -> OpenAI:
    """
    Create TTS client (Phase 2).
    Currently returns OpenAI client.
    """
    try:
        import config
        from model_config import TTS_PROVIDER
        
        if TTS_PROVIDER == "openrouter":
            # Future: Add OpenRouter TTS support
            warning("OpenRouter TTS not yet implemented, using OpenAI")
        
        return OpenAI(api_key=getattr(config, 'OPENAI_API_KEY', ''))
        
    except ImportError:
        return OpenAI(api_key="")


def create_video_client():
    """
    Create video generation client (Phase 3).
    Returns None for now (no video generation currently implemented).
    """
    # Phase 3: Implement OpenRouter video generation
    # Models: HunyuanVideo, Wan 2.1, Mochi 1, LTXVideo
    return None


# ============================================================================
# PHASE 1B: Full OpenRouter Enablement - 3-Tier Model Configuration
# ============================================================================

def get_model_config(task_id: str, original_openai_model: Optional[str] = None) -> Dict[str, Any]:
    """
    Get complete model configuration for a task using 3-tier fallback system.
    
    TIER 1: Kimi K2.5 with Thinking Toggle (Primary)
      - thinking: enabled for complex tasks (upstream gpt-4.1-full equivalents)
      - thinking: disabled for simple tasks (upstream gpt-4.1-mini equivalents)
    
    TIER 2: Dual Model Strategy (Secondary Fallback)
      - Kimi K2.5 for full tasks, Gemini Flash for mini tasks
    
    TIER 3: OpenAI Upstream (Tertiary Fallback)
      - Uses original OpenAI model constants
      - Automatic fallback when OpenRouter fails
    
    Args:
        task_id: Task identifier (e.g., "dm_main", "combat_main", "summaries")
        original_openai_model: Original OpenAI model constant (for fallback)
        
    Returns:
        Dict containing:
        - model: Model ID string
        - temperature: Temperature setting
        - extra_body: Additional API parameters (for Kimi thinking mode)
        - use_openrouter: Boolean indicating if OpenRouter should be used
        - fallback_strategy: Strategy to use if this tier fails
    
    Usage:
        config = get_model_config("combat_main", COMBAT_MAIN_MODEL)
        response = client.chat.completions.create(
            model=config["model"],
            messages=messages,
            temperature=config["temperature"],
            **config.get("extra_body", {})
        )
    """
    # TABLETOP MODE: Legacy profile selection uses the canonical task-tier list.
    try:
        from model_config import (
            LLM_PROVIDER,
            OPENROUTER_STRATEGY,
            OPENROUTER_CHAT_MODEL,
            OPENROUTER_FULL_MODEL,
            OPENROUTER_MINI_MODEL,
            COMPLEX_TASKS,
            TASK_OVERRIDES,
            TASK_TEMPERATURES,
        )
    except ImportError:
        # Fallback if imports fail - use OpenAI defaults
        return {
            "model": original_openai_model or "gpt-4.1-2025-04-14",
            "temperature": 0.7,
            "extra_body": {},
            "use_openrouter": False,
            "fallback_strategy": None,
        }
    
    # CRITICAL FIX: Use single source of truth to determine actual provider
    # This prevents the split-brain issue where config says OpenRouter but
    # runtime conditions (missing API key) require OpenAI fallback
    provider, is_openrouter = _get_actual_provider()
    
    if not is_openrouter:
        return {
            "model": original_openai_model or "gpt-4.1-2025-04-14",
            "temperature": TASK_TEMPERATURES.get(task_id, 0.7),
            "extra_body": {},
            "use_openrouter": False,
            "fallback_strategy": None,
        }
    
    # Check for task-specific override (highest priority)
    if task_id in TASK_OVERRIDES:
        override = TASK_OVERRIDES[task_id]
        model = override.get("model", OPENROUTER_CHAT_MODEL)
        thinking = override.get("thinking")
        temp = override.get("temperature", TASK_TEMPERATURES.get(task_id, 0.7))
        
        extra_body = {}
        if thinking:
            extra_body = {"extra_body": {"thinking": {"type": thinking}}}
        
        return {
            "model": model,
            "temperature": temp,
            "extra_body": extra_body,
            "use_openrouter": True,
            "fallback_strategy": "dual_model",
        }
    
    # TIER 1: Kimi with thinking toggle (primary strategy)
    if OPENROUTER_STRATEGY == "kimi_thinking":
        # Determine if this is a complex task (thinking enabled) or simple task (thinking disabled)
        is_complex = task_id in COMPLEX_TASKS
        thinking_mode = "enabled" if is_complex else "disabled"
        
        # Set temperature based on thinking mode
        # Higher temp (1.0) for thinking mode, lower (0.6) for instant mode
        if task_id in TASK_TEMPERATURES:
            temperature = TASK_TEMPERATURES[task_id]
        else:
            temperature = 1.0 if thinking_mode == "enabled" else 0.6
        
        return {
            "model": OPENROUTER_CHAT_MODEL,
            "temperature": temperature,
            "extra_body": {"extra_body": {"thinking": {"type": thinking_mode}}},
            "use_openrouter": True,
            "fallback_strategy": "dual_model",
        }
    
    # TIER 2: Dual model strategy
    elif OPENROUTER_STRATEGY == "dual_model":
        is_complex = task_id in COMPLEX_TASKS
        model = OPENROUTER_FULL_MODEL if is_complex else OPENROUTER_MINI_MODEL
        temperature = TASK_TEMPERATURES.get(task_id, 0.7)
        
        return {
            "model": model,
            "temperature": temperature,
            "extra_body": {},
            "use_openrouter": True,
            "fallback_strategy": "openai",
        }
    
    # TIER 3: Single model strategy (use full model for everything)
    else:
        return {
            "model": OPENROUTER_CHAT_MODEL,
            "temperature": TASK_TEMPERATURES.get(task_id, 0.7),
            "extra_body": {},
            "use_openrouter": True,
            "fallback_strategy": "openai",
        }


def get_chat_completion_params(
    task_id: str,
    original_openai_model: Optional[str] = None,
    *,
    temperature_override: Optional[float] = None,
    retry_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """Return flat Chat Completions kwargs for the resolved model family."""
    model_config = get_model_config(task_id, original_openai_model)
    model = model_config.get("model", original_openai_model or "gpt-4.1-2025-04-14")
    temperature = temperature_override
    if temperature is None:
        temperature = model_config.get("temperature")
    return finalize_chat_params(
        model,
        params=model_config,
        temperature=temperature,
        is_openrouter=bool(model_config.get("use_openrouter")),
        retry_tier=retry_tier,
        task_id=task_id,
    )


# ============================================================================
