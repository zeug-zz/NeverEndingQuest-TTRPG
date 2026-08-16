# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider-free build-path request fixtures (change:
toolkit-gpt5-build-path-compatibility, task 1.2).

Reusable, deterministic fixtures that capture the FINAL kwargs passed to a
mock ``client.chat.completions.create`` for the three provider branches of
the shared parameter helper ``get_chat_completion_params``:

- Direct GPT-5 family (e.g. gpt-5.6-luna): task profile
  (reasoning_effort/verbosity), legacy temperature/top_p omitted.
- Compatible non-GPT-5 direct model (e.g. gpt-4.1-2025-04-14): caller
  sampling behavior preserved, no GPT-5 profile keys.
- OpenRouter: configured model + provider-specific thinking/request fields +
  compatible temperature behavior, no GPT-5 profile substitution.

The fixtures simulate the post-migration call-site shape:

    client.chat.completions.create(
        **get_chat_completion_params(task_id, model, temperature_override=...),
        messages=..., ...)

Later call-site tests (tasks 2.x / 4.x) can reuse ``capture_create_call``
with the exact task id, model source, and sampling intent of a migrated
call site. The parameter helper (``utils/ai_client_factory``) remains the
single routing authority; this module adds no second routing helper and
changes no model assignments.

Provider-free: no live API, no credentials, no raw source persistence.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import utils.ai_client_factory as ai_client_factory

# Synthetic model ids used by the fixtures. They mirror the current direct
# OpenAI assignments without importing model_config constants, so the
# fixtures stay stable even if a future model swap changes the constants.
GPT5_DIRECT_MODEL = "gpt-5.6-luna"
NON_GPT5_DIRECT_MODEL = "gpt-4.1-2025-04-14"

DEFAULT_MESSAGES: List[Dict[str, str]] = [
    {"role": "user", "content": "fixture message"}
]


class FakeChatResponse:
    """Minimal stand-in for a Chat Completions response object."""

    def __init__(self) -> None:
        self.choices: List[Any] = []
        self.model: Optional[str] = None


class RecordingChatCompletions:
    """Records every create() call's final kwargs."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeChatResponse:
        self.calls.append(dict(kwargs))
        return FakeChatResponse()

    @property
    def last_call(self) -> Optional[Dict[str, Any]]:
        if not self.calls:
            return None
        return self.calls[-1]

    @property
    def call_count(self) -> int:
        return len(self.calls)


class ChatNamespace:
    """Mirrors the ``client.chat.completions`` attribute chain."""

    def __init__(self) -> None:
        self.completions = RecordingChatCompletions()


class RecordingClient:
    """Mock client whose chat.completions.create records final request kwargs."""

    def __init__(self) -> None:
        self.chat = ChatNamespace()

    @property
    def last_call(self) -> Optional[Dict[str, Any]]:
        return self.chat.completions.last_call

    @property
    def calls(self) -> List[Dict[str, Any]]:
        return self.chat.completions.calls


class CapturedRequest:
    """Pair of resolved helper params and the final kwargs the mock received."""

    def __init__(
        self, params: Dict[str, Any], create_kwargs: Dict[str, Any]
    ) -> None:
        self.params = params
        self.create_kwargs = create_kwargs

    def create_call_keys(self) -> set:
        return set(self.create_kwargs.keys())


@contextmanager
def forced_provider(provider_name: str, is_openrouter: bool):
    """Temporarily force _get_actual_provider to a deterministic provider."""
    original = ai_client_factory._get_actual_provider
    ai_client_factory._get_actual_provider = (
        lambda use_fallback=False: (provider_name, is_openrouter)
    )
    try:
        yield
    finally:
        ai_client_factory._get_actual_provider = original


def resolve_params(
    task_id: str,
    model: str,
    *,
    temperature_override: Optional[float] = None,
    retry_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the shared-helper request params for a task and model."""
    return ai_client_factory.get_chat_completion_params(
        task_id,
        model,
        temperature_override=temperature_override,
        retry_tier=retry_tier,
    )


def capture_create_call(
    task_id: str,
    model: str,
    *,
    temperature_override: Optional[float] = None,
    retry_tier: Optional[str] = None,
    provider: Optional[Tuple[str, bool]] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    **extra_create_kwargs: Any,
) -> CapturedRequest:
    """
    Simulate a migrated build call site: resolve params through the shared
    helper and spread them into the mock client's create call.

    Returns the resolved helper params AND the final kwargs the mock create
    call actually received (params + messages + any extra create kwargs).
    """
    if provider is None:
        provider = ("openai", False)
    provider_name, is_openrouter = provider
    client = RecordingClient()
    with forced_provider(provider_name, is_openrouter):
        params = resolve_params(
            task_id,
            model,
            temperature_override=temperature_override,
            retry_tier=retry_tier,
        )
        client.chat.completions.create(
            **params,
            messages=messages if messages is not None else DEFAULT_MESSAGES,
            **extra_create_kwargs,
        )
        captured = client.last_call or {}
    return CapturedRequest(params=params, create_kwargs=captured)


def capture_gpt5_build_request(
    task_id: str = "builders",
    model: str = GPT5_DIRECT_MODEL,
    **kwargs: Any,
) -> CapturedRequest:
    """Capture a direct-OpenAI GPT-5 family build request (provider-free)."""
    return capture_create_call(task_id, model, provider=("openai", False), **kwargs)


def capture_non_gpt5_build_request(
    task_id: str = "builders",
    model: str = NON_GPT5_DIRECT_MODEL,
    **kwargs: Any,
) -> CapturedRequest:
    """Capture a direct-OpenAI non-GPT-5 build request (provider-free)."""
    return capture_create_call(task_id, model, provider=("openai", False), **kwargs)


def capture_openrouter_build_request(
    task_id: str = "builders",
    model: str = GPT5_DIRECT_MODEL,
    **kwargs: Any,
) -> CapturedRequest:
    """Capture an OpenRouter build request (provider-free)."""
    return capture_create_call(task_id, model, provider=("openrouter", True), **kwargs)
