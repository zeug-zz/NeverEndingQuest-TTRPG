# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free model-profile benchmark harness.

    The default path is deliberately synthetic. It exercises the router through
    the factory seam with bundled, production-shaped fixtures and never reads an
    API key or opens a provider connection. Live comparison is explicit opt-in
    and bounded to the four bundled fixtures.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


FIXTURES: List[Dict[str, Any]] = [
    {
        "name": "narrator_dm_note_world_turn",
        "task": "dm_main",
        "json_output": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "AUTHORITATIVE DM NOTE: location_id=RO01; location=West Gate; "
                    "world_time=18:20; Acheron HP=21/21 AC=16 conditions=None; "
                    "Lidda HP=9/12 AC=14 conditions=Prone; active_character=Acheron."
                ),
            },
            {"role": "user", "content": "The party studies the sealed gate."},
        ],
        "content": "The sealed gate answers with a low, patient hum.",
        "prompt_tokens": 116,
        "cached_tokens": 18,
        "completion_tokens": 22,
        "cost": 0.00031,
    },
    {
        "name": "combat_batch_validation",
        "task": "combat_validation",
        "json_output": True,
        "messages": [
            {"role": "system", "content": "Validate one enemy batch and its PC damage."},
            {"role": "user", "content": "Goblin hits Acheron; return structured operations."},
        ],
        "content": '{"status":"ok","operations":[{"actor":"Goblin","target":"Acheron","hp_delta":-6}]}',
        "prompt_tokens": 164,
        "cached_tokens": 64,
        "completion_tokens": 31,
        "cost": 0.00044,
    },
    {
        "name": "encounter_json_update",
        "task": "encounter_update",
        "json_output": True,
        "messages": [
            {"role": "system", "content": "Apply an encounter JSON update."},
            {"role": "user", "content": "Set the bandit's hit points to 7."},
        ],
        "content": '{"encounterId":"synthetic-encounter","changes":{"Bandit":{"hitPoints":7}}}',
        "prompt_tokens": 92,
        "cached_tokens": 0,
        "completion_tokens": 19,
        "cost": 0.00022,
    },
    {
        "name": "summary_compression",
        "task": "compression",
        "json_output": False,
        "messages": [
            {"role": "system", "content": "Compress the recent world turn without changing facts."},
            {"role": "user", "content": "The party crossed the courtyard and marked the east door."},
        ],
        "content": "The party crossed the courtyard and marked the east door.",
        "prompt_tokens": 128,
        "cached_tokens": 48,
        "completion_tokens": 14,
        "cost": 0.00018,
    },
]

# JSON retries allow up to three response attempts; a transient provider error
# may add one more transport attempt for a fixture.  These are bounds, not a
# claim that each fixture makes one request or that a run makes exactly four.
LIVE_FIXTURE_COUNT = len(FIXTURES)
MAX_TRANSPORT_ATTEMPTS_PER_FIXTURE = 4
MAX_TRANSPORT_ATTEMPTS_PER_CANDIDATE = (
    LIVE_FIXTURE_COUNT * MAX_TRANSPORT_ATTEMPTS_PER_FIXTURE
)


class SyntheticProviderClient:
    """Minimal injected SDK-shaped transport; it cannot perform I/O."""

    def __init__(self, candidate: str, fixtures: Iterable[Mapping[str, Any]]) -> None:
        self.candidate = candidate
        self.fixtures = list(fixtures)
        self.calls: List[Dict[str, Any]] = []

        class _Chat:
            pass

        self.chat = _Chat()
        self.chat.completions = _Chat()
        self.chat.completions.create = self.create

    def with_options(self, **_options: Any) -> "SyntheticProviderClient":
        return self

    def create(self, **kwargs: Any) -> Dict[str, Any]:
        index = len(self.calls)
        fixture = self.fixtures[index]
        self.calls.append(copy.deepcopy(kwargs))
        actual_model = (
            "synthetic/" + self.candidate
            if self.candidate != "openai/fallback"
            else self.fallback_model
        )
        return {
            "model": actual_model,
            "choices": [{"message": {"content": fixture["content"]}}],
            "usage": {
                "prompt_tokens": fixture["prompt_tokens"],
                "completion_tokens": fixture["completion_tokens"],
                "prompt_tokens_details": {"cached_tokens": fixture["cached_tokens"]},
                "cost": fixture["cost"],
            },
        }


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@contextlib.contextmanager
def _preserve_router_state() -> Any:
    """Preserve module-level router statistics across success and failure."""
    import utils.llm_router as router_module

    with router_module._USAGE_LOCK:
        saved_stats = copy.deepcopy(router_module._usage_stats)
    try:
        yield router_module
    finally:
        with router_module._USAGE_LOCK:
            router_module._usage_stats = saved_stats


@contextlib.contextmanager
def _candidate_config(profile: str) -> Any:
    """Select one candidate without leaking config or task overrides."""
    import model_config as config

    original_active = config.ACTIVE_PROFILE
    original_overrides = copy.deepcopy(config.TASK_OVERRIDES)
    selected_overrides = copy.deepcopy(original_overrides)
    for fixture in FIXTURES:
        selected_overrides.pop(fixture["task"], None)
    try:
        config.ACTIVE_PROFILE = profile
        config.TASK_OVERRIDES = selected_overrides
        yield config
    finally:
        config.ACTIVE_PROFILE = original_active
        config.TASK_OVERRIDES = original_overrides


def _run_candidate(profile: str) -> Dict[str, Any]:
    import utils.ai_client_factory as factory
    from utils.llm_router import llm
    import model_config as config

    client = SyntheticProviderClient(profile, FIXTURES)
    client.fallback_model = str(config.OPENAI_FALLBACK_MODEL)
    timings: List[float] = []
    valid_json = 0
    json_cases = 0
    results: List[Dict[str, Any]] = []
    provider = "openai" if profile == "openai/fallback" else "openrouter"

    with _preserve_router_state():
        try:
            llm.reset_usage_stats()
            # Redirect incidental logger output so stdout remains one JSON document.
            with _candidate_config(profile):
                if profile == "openai/fallback":
                    expected_models = [str(config.OPENAI_FALLBACK_MODEL)] * len(FIXTURES)
                else:
                    complex_tasks = set(getattr(config, "COMPLEX_TASKS", ()))
                    profile_data = config.MODEL_PROFILES[profile]
                    expected_models = []
                    for fixture in FIXTURES:
                        tier_name = "complex" if fixture["task"] in complex_tasks else "simple"
                        tier_data = profile_data.get(tier_name, {})
                        expected_models.append(str(tier_data.get("model") or "openrouter/auto"))
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with mock.patch.object(
                        factory,
                        "_get_actual_provider",
                        return_value=(provider, provider == "openrouter"),
                    ):
                        with mock.patch.object(factory, "create_chat_client", return_value=client):
                            for fixture in FIXTURES:
                                started = time.perf_counter()
                                value = llm.call(
                                    fixture["task"],
                                    copy.deepcopy(fixture["messages"]),
                                    json_output=fixture["json_output"],
                                    max_tokens=128,
                                )
                                timings.append((time.perf_counter() - started) * 1000.0)
                                if fixture["json_output"]:
                                    json_cases += 1
                                    if isinstance(value, dict):
                                        valid_json += 1
                                results.append(
                                    {
                                        "fixture": fixture["name"],
                                        "task": fixture["task"],
                                        "json_valid": (
                                            isinstance(value, dict)
                                            if fixture["json_output"]
                                            else None
                                        ),
                                    }
                                )

                    usage = llm.get_usage_stats()

            emitted_models = [call.get("model") for call in client.calls]
            if emitted_models != expected_models:
                raise AssertionError(
                    f"synthetic candidate {profile} emitted models {emitted_models!r}; "
                    f"expected {expected_models!r}"
                )

            request_count = int(usage["transport_attempts"])
            elapsed_seconds = max(sum(timings) / 1000.0, 0.000001)
            prompt_tokens = usage["prompt_tokens"]
            cached_tokens = usage["cached_tokens"]
            total_cost = usage["total_cost_usd"]
            return {
                "profile": profile,
                "provider_mode": provider,
                "fixtures": results,
                "fixture_count": len(FIXTURES),
                "request_count": request_count,
                "successful_response_count": int(usage["calls"]),
                "provider_client_constructors": 0,
                "sdk_models": emitted_models,
                "metrics": {
                    "json_validity_rate": valid_json / json_cases if json_cases else 1.0,
                    "latency_ms": {
                        "p50": _percentile(timings, 0.50),
                        "p90": _percentile(timings, 0.90),
                    },
                    "throughput_calls_per_second": request_count / elapsed_seconds,
                    "throughput_completion_tokens_per_second": usage["completion_tokens"] / elapsed_seconds,
                    "prompt_tokens": prompt_tokens,
                    "cached_tokens": cached_tokens,
                    "completion_tokens": usage["completion_tokens"],
                    "cache_read_rate": cached_tokens / prompt_tokens if prompt_tokens else 0.0,
                    "cost_usd": total_cost,
                    "cost_per_call_usd": total_cost / request_count if request_count else 0.0,
                },
                "usage": usage,
            }
        finally:
            # The surrounding context restores the exact caller snapshot.
            llm.reset_usage_stats()


def build_report(profile: str) -> Dict[str, Any]:
    candidates = ("production-auto", "titan-auto", "openai/fallback")
    return {
        "schema": "neq.synthetic_model_profile_benchmark.v1",
        "status": "synthetic",
        "synthetic": True,
        "measurement_scope": "provider_free_fake_transport",
        "live_quality_or_cost_claim": False,
        "network_requests": 0,
        "api_key_read": False,
        "fixtures": [fixture["name"] for fixture in FIXTURES],
        "selected_profile": profile,
        "candidates": {candidate: _run_candidate(candidate) for candidate in candidates},
    }


def _live_cost_summary(usage: Mapping[str, Any]) -> Dict[str, Any]:
    """Expose known cost without treating missing Auto pricing as free."""
    known_subtotal = float(usage.get("total_cost_usd", 0.0) or 0.0)
    complete = bool(usage.get("cost_complete", False))
    return {
        "known_cost_subtotal_usd": known_subtotal,
        "full_cost_usd": known_subtotal if complete else None,
        "cost_complete": complete,
        "unpriced_calls": int(usage.get("unpriced_calls", 0) or 0),
    }


def _run_live_candidate(profile: str, *, direct_openai_reference: bool = False) -> Dict[str, Any]:
    """Run one real candidate over exactly the four bundled fixtures.

    The factory is the configuration authority. This function never reads,
    copies, or logs credentials. The reference uses direct OpenAI posture.
    """
    import utils.ai_client_factory as factory
    from utils.llm_router import llm

    if not direct_openai_reference:
        provider_name, is_openrouter = factory._get_actual_provider()
        if provider_name != "openrouter" or not is_openrouter:
            raise RuntimeError(
                "live benchmark requires configured OpenRouter provider; no live request was sent"
            )

    timings: List[float] = []
    results: List[Dict[str, Any]] = []
    with _preserve_router_state():
        llm.reset_usage_stats()
        with _candidate_config(profile):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                provider_context = (
                    mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False))
                    if direct_openai_reference
                    else contextlib.nullcontext()
                )
                with provider_context:
                    for fixture in FIXTURES:
                        started = time.perf_counter()
                        value = llm.call(
                            fixture["task"],
                            copy.deepcopy(fixture["messages"]),
                            json_output=fixture["json_output"],
                            max_tokens=128,
                        )
                        if not direct_openai_reference:
                            live_usage = llm.get_usage_stats()
                            if live_usage.get("fallbacks"):
                                raise RuntimeError(
                                    "live benchmark OpenRouter call fell back to direct OpenAI"
                                )
                        timings.append((time.perf_counter() - started) * 1000.0)
                        results.append(
                            {
                                "fixture": fixture["name"],
                                "task": fixture["task"],
                                "json_valid": (
                                    isinstance(value, dict) if fixture["json_output"] else None
                                ),
                            }
                        )
                usage = llm.get_usage_stats()
        resolved_models = sorted(
            {
                str(item.get("resolved_model"))
                for item in usage.get("diagnostics", [])
                if item.get("provenance") in {"actual", "estimated", "unpriced"}
            }
        )
        requested_models = sorted(
            {
                str(item.get("requested_model"))
                for item in usage.get("diagnostics", [])
                if item.get("provenance") in {"actual", "estimated", "unpriced"}
            }
        )
        request_count = int(usage["transport_attempts"])
        elapsed_seconds = max(sum(timings) / 1000.0, 0.000001)
        return {
            "profile": "openai/fallback" if direct_openai_reference else profile,
            "provider_mode": "openai" if direct_openai_reference else "openrouter",
            "synthetic": False,
            "fixtures": results,
            "fixture_count": len(FIXTURES),
            "request_count": request_count,
            "successful_response_count": int(usage["calls"]),
            "latency_ms": {
                "p50": _percentile(timings, 0.50),
                "p90": _percentile(timings, 0.90),
                "samples": timings,
            },
            "throughput_calls_per_second": request_count / elapsed_seconds,
            "usage": usage,
            "actual_models": resolved_models,
            "requested_models": requested_models,
            "cost": _live_cost_summary(usage),
        }


def build_live_report(profile: str) -> Dict[str, Any]:
    """Build an explicit live comparison without repeating owner acceptance."""
    if profile == "openai/fallback":
        raise ValueError("--live requires an OpenRouter profile, not openai/fallback")
    import utils.ai_client_factory as factory

    # Resolve through the factory before creating any client. Missing config
    # therefore fails closed without an accidental direct-OpenAI request.
    provider_name, is_openrouter = factory._get_actual_provider()
    if provider_name != "openrouter" or not is_openrouter:
        raise RuntimeError(
            "live benchmark requires configured OpenRouter provider; set provider configuration before using --live"
        )
    selected = _run_live_candidate(profile)
    reference = _run_live_candidate(profile, direct_openai_reference=True)
    return {
        "schema": "neq.live_model_profile_benchmark.v1",
        "status": "live",
        "synthetic": False,
        "measurement_scope": "four_bundled_fixtures_per_candidate",
        "fixture_count_per_candidate": LIVE_FIXTURE_COUNT,
        "max_transport_attempts_per_fixture": MAX_TRANSPORT_ATTEMPTS_PER_FIXTURE,
        "max_transport_attempts_per_candidate": MAX_TRANSPORT_ATTEMPTS_PER_CANDIDATE,
        "network_requests": selected["request_count"] + reference["request_count"],
        "api_key_read": False,
        "selected_profile": profile,
        "openrouter_candidate": selected,
        "direct_openai_reference": reference,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the provider-free model-profile benchmark.")
    parser.add_argument(
        "--profile",
        default="production-auto",
        choices=("production-auto", "titan-auto", "openai/fallback"),
        help="Profile candidate to exercise with the injected fake transport.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Opt in to four real calls for the selected OpenRouter profile and direct-OpenAI reference.",
    )
    args = parser.parse_args()
    try:
        report = build_live_report(args.profile) if args.live else build_report(args.profile)
    except (RuntimeError, ValueError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
