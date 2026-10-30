# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for the LLM router workstream.

While the tripwire is armed, a real provider constructor or network operation
raises immediately. Optional transport modules are imported before guards are
armed; that test-only setup separates import-time capability probes from the
actual provider-free execution under test.
"""

import contextlib
import copy
import ast
import http.client
import importlib
import inspect
import json
import socket
import subprocess
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Arm fatal process-wide SDK/network/write tripwires before importing any
# production owner. Per-test fake seams may be layered over these guards.
from scripts.core_chat_test_safety import arm_process_tripwires

PROCESS_TRIPWIRES = arm_process_tripwires()

import utils.llm_usage_tracker as usage_tracker_module


class _RouterTestTracker:
    def __init__(self) -> None:
        self.events: List[Any] = []

    def track(self, response: Any, context: Any = None) -> None:
        self.events.append((response, context))


ROUTER_TEST_TRACKER = _RouterTestTracker()
ROUTER_TEST_TRACKER_PATCH = mock.patch.object(
    usage_tracker_module,
    "get_global_tracker",
    return_value=ROUTER_TEST_TRACKER,
)
ROUTER_TEST_TRACKER_PATCH.start()


def _tripwire_failure(name: str) -> AssertionError:
    return AssertionError("provider tripwire: unexpected live operation: " + name)


class FakeProviderClient:
    """Small injected client shape for future provider-free router tests."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.chat = mock.Mock()
        self.chat.completions.create = self._create

    def _create(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(dict(kwargs))
        return {"choices": [{"message": {"content": "fake response"}}]}


class SequenceProviderClient:
    """Fake SDK client returning responses or raising supplied exceptions."""

    def __init__(self, outcomes: List[Any]) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._outcomes = list(outcomes)
        self.chat = mock.Mock()
        self.chat.completions.create = self._create

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def with_options(self, **kwargs: Any) -> "SequenceProviderClient":
        self.options = dict(kwargs)
        return self


def _response(content: Any) -> Dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


def _terminal_response(kind: str) -> Dict[str, Any]:
    message = {"content": "provider terminal payload", "refusal": None}
    finish_reason = "stop"
    if kind == "refusal":
        message["refusal"] = "provider refusal payload"
    elif kind == "content_filter":
        finish_reason = "content_filter"
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 4,
            "completion_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0},
            "cost": 0.0,
        },
    }


class ProviderTripwire(contextlib.AbstractContextManager):
    """Fail-closed guards for provider construction and network I/O.

    The guards cover the shared factory seam, the OpenAI SDK constructor, HTTP
    and URL helpers, socket creation, optional requests/httpx transports, and
    optional Socket.IO connection surfaces. Constructor patching is separate
    from network patching so future tests can explicitly inject a fake client.
    """

    def __init__(self) -> None:
        self._patchers: List[Any] = []
        self.guards: Dict[str, mock.Mock] = {}

    def _arm(self, name: str, target: str) -> None:
        try:
            patcher = mock.patch(target, side_effect=_tripwire_failure(name))
            self.guards[name] = patcher.start()
            self._patchers.append(patcher)
        except (ImportError, AttributeError):
            # Optional transports are not required for the provider-free suite.
            return

    @staticmethod
    def _preload_optional_transports() -> None:
        """Load optional transport modules before socket guards are armed.

        Some optional libraries probe socket capabilities while importing. This
        is not an HTTP request or provider construction, but it must happen
        before the tripwire records execution calls.
        """
        for module_name in ("requests", "urllib3", "httpx", "socketio", "engineio", "openai"):
            try:
                importlib.import_module(module_name)
            except ImportError:
                continue

    def __enter__(self) -> "ProviderTripwire":
        self._preload_optional_transports()
        self._arm("openai.OpenAI", "openai.OpenAI")
        self._arm("factory.OpenAI", "utils.ai_client_factory.OpenAI")
        self._arm("urllib.request.urlopen", "urllib.request.urlopen")
        self._arm("urllib.request.urlretrieve", "urllib.request.urlretrieve")
        self._arm("http.client.HTTPConnection.request", "http.client.HTTPConnection.request")
        self._arm("http.client.HTTPSConnection.request", "http.client.HTTPSConnection.request")
        self._arm("http.client.HTTPConnection.connect", "http.client.HTTPConnection.connect")
        self._arm("http.client.HTTPSConnection.connect", "http.client.HTTPSConnection.connect")
        self._arm("socket.socket", "socket.socket")
        self._arm("socket.create_connection", "socket.create_connection")
        self._arm("requests.request", "requests.request")
        self._arm("requests.get", "requests.get")
        self._arm("requests.post", "requests.post")
        self._arm("requests.sessions.Session.request", "requests.sessions.Session.request")
        self._arm("httpx.Client.request", "httpx.Client.request")
        self._arm("httpx.Client.send", "httpx.Client.send")
        self._arm("httpx.AsyncClient.request", "httpx.AsyncClient.request")
        self._arm("httpx.AsyncClient.send", "httpx.AsyncClient.send")
        self._arm("socketio.Client.connect", "socketio.Client.connect")
        return self

    @contextlib.contextmanager
    def allow_fake_provider(self, fake_client: Any) -> Iterator[Any]:
        """Replace provider constructors with an explicitly injected fake."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("openai.OpenAI", return_value=fake_client))
            try:
                stack.enter_context(
                    mock.patch("utils.ai_client_factory.OpenAI", return_value=fake_client)
                )
            except (ImportError, AttributeError):
                pass
            yield fake_client

    def assert_untouched(self, case: unittest.TestCase) -> None:
        for name, guard in self.guards.items():
            with case.subTest(tripwire=name):
                guard.assert_not_called()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        for patcher in reversed(self._patchers):
            patcher.stop()
        return False


class TestProviderFreeFoundation(unittest.TestCase):
    """Self-tests proving the tripwire fails closed and permits fake seams."""

    def test_real_provider_constructor_is_blocked(self) -> None:
        with ProviderTripwire():
            openai = importlib.import_module("openai")
            with self.assertRaisesRegex(AssertionError, "provider tripwire"):
                openai.OpenAI(api_key="never-read")

    def test_network_surfaces_are_blocked(self) -> None:
        with ProviderTripwire() as tripwire:
            with self.assertRaisesRegex(AssertionError, "provider tripwire"):
                urllib.request.urlopen("https://example.invalid")
            with self.assertRaisesRegex(AssertionError, "provider tripwire"):
                socket.create_connection(("example.invalid", 443))
            tripwire.guards["urllib.request.urlopen"].assert_called_once()
            tripwire.guards["socket.create_connection"].assert_called_once()

    def test_http_constructor_paths_are_blocked_before_connection(self) -> None:
        with ProviderTripwire():
            with self.assertRaisesRegex(AssertionError, "provider tripwire"):
                http.client.HTTPSConnection("example.invalid").connect()

    def test_fake_provider_constructor_is_explicitly_allowed(self) -> None:
        fake = FakeProviderClient()
        with ProviderTripwire() as tripwire:
            with tripwire.allow_fake_provider(fake):
                openai = importlib.import_module("openai")
                client = openai.OpenAI(api_key="fake-only")
                response = client.chat.completions.create(model="fake", messages=[])

        self.assertIs(client, fake)
        self.assertEqual(response["choices"][0]["message"]["content"], "fake response")
        self.assertEqual(len(fake.calls), 1)

    def test_fake_transport_never_needs_a_key_or_network(self) -> None:
        fake = FakeProviderClient()
        with ProviderTripwire() as tripwire:
            with tripwire.allow_fake_provider(fake):
                fake.chat.completions.create(
                    model="fake", messages=[{"role": "user", "content": "hi"}]
                )
            tripwire.assert_untouched(self)


def tearDownModule() -> None:
    """Fail the process if any process-wide fatal guard was reached."""
    ROUTER_TEST_TRACKER_PATCH.stop()
    PROCESS_TRIPWIRES.assert_untouched(unittest.TestCase())


class TestModelProfileConfigContracts(unittest.TestCase):
    """Provider-free tests for the model_config data contract only.

    These tests intentionally do not implement profile resolution. Resolver
    behavior belongs to the later router task and will consume these config
    contracts without duplicating its logic here.
    """

    @contextlib.contextmanager
    def _restored_config(self, config: Any, **overrides: Any) -> Iterator[Any]:
        originals = {name: getattr(config, name) for name in overrides}
        try:
            for name, value in overrides.items():
                setattr(config, name, value)
            yield config
        finally:
            for name, value in originals.items():
                setattr(config, name, value)

    def test_independent_narrator_combat_and_titan_overrides(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            overrides = copy.deepcopy(config.TASK_OVERRIDES)
            overrides.update(
                {
                    "dm_main": {"profile": "titan-auto"},
                    "combat_main": {"model": "vendor/combat-model"},
                    "titan_cycle": {"profile": "production-auto"},
                }
            )
            with self._restored_config(config, TASK_OVERRIDES=overrides):
                self.assertEqual(config.TASK_OVERRIDES["dm_main"]["profile"], "titan-auto")
                self.assertEqual(
                    config.TASK_OVERRIDES["combat_main"]["model"],
                    "vendor/combat-model",
                )
                self.assertEqual(
                    config.TASK_OVERRIDES["titan_cycle"]["profile"],
                    "production-auto",
                )
                self.assertNotEqual(
                    config.TASK_OVERRIDES["dm_main"], config.TASK_OVERRIDES["combat_main"]
                )

    def test_auto_defaults_are_concrete_for_unknown_or_missing_profiles(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            self.assertIs(config.DEFAULT_PROFILE, config.MODEL_PROFILES["production-auto"])
            for tier_name in ("complex", "simple"):
                with self.subTest(tier=tier_name):
                    tier = config.DEFAULT_PROFILE[tier_name]
                    self.assertEqual(tier["model"], "openrouter/auto")
                    self.assertEqual(tier["params"], {})
                    self.assertEqual(tier["provider"], {})
                    self.assertEqual(tier["price_per_1k"], {})

            incomplete_profile = {"complex": {}, "simple": {}}
            self.assertEqual(
                config.DEFAULT_PROFILE["complex"]["model"],
                "openrouter/auto",
            )
            self.assertNotIn("model", incomplete_profile["complex"])
            self.assertEqual(config.DEFAULT_PROFILE, config.MODEL_PROFILES["production-auto"])

    def test_both_fallback_tiers_use_gpt_6_luna(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            self.assertEqual(config.OPENAI_FALLBACK_MODEL, "gpt-6-luna")
            fallback = config.MODEL_PROFILES["openai/fallback"]
            self.assertEqual(fallback["complex"]["model"], "gpt-6-luna")
            self.assertEqual(fallback["simple"]["model"], "gpt-6-luna")

    def test_vendor_overrides_are_isolated_from_direct_openai_config(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            overrides = copy.deepcopy(config.TASK_OVERRIDES)
            overrides["dm_main"] = {
                "model": "vendor/narrator-model",
                "provider": {"order": ["vendor"]},
            }
            with self._restored_config(config, TASK_OVERRIDES=overrides):
                self.assertEqual(
                    config.TASK_OVERRIDES["dm_main"]["model"], "vendor/narrator-model"
                )
                self.assertEqual(
                    config.MODEL_PROFILES["openai/fallback"]["complex"]["model"],
                    config.OPENAI_FALLBACK_MODEL,
                )
                self.assertEqual(
                    config.MODEL_PROFILES["openai/fallback"]["complex"]["provider"], {}
                )
                self.assertEqual(config.LLM_PROVIDER, "openrouter")

    def test_optional_auto_router_settings_are_portable_config(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            profiles = copy.deepcopy(config.MODEL_PROFILES)
            profiles["production-auto"]["complex"]["params"] = {
                "plugins": [
                    {
                        "id": "auto-router",
                        "cost_tier": "low",
                        "allowed_models": ["vendor/model-a"],
                    }
                ]
            }
            with self._restored_config(config, MODEL_PROFILES=profiles):
                params = config.MODEL_PROFILES["production-auto"]["complex"]["params"]
                self.assertEqual(params["plugins"][0]["id"], "auto-router")
                self.assertEqual(params["plugins"][0]["cost_tier"], "low")
                self.assertEqual(params["plugins"][0]["allowed_models"], ["vendor/model-a"])
                self.assertEqual(config.MODEL_PROFILES["openai/fallback"]["complex"]["params"], {})

    def test_complex_tasks_is_the_canonical_selection_set(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            self.assertEqual(
                config.COMPLEX_TASKS,
                [
                    "dm_main",
                    "dm_validation",
                    "combat_main",
                    "action_prediction",
                    "character_validator",
                    "npc_builder",
                    "monster_builder",
                    "level_up",
                    "dm_full",
                    "location_compression",
                ],
            )


class TestFactoryExtraBodyContracts(unittest.TestCase):
    """Lock the SDK-compatible extra_body envelope at the factory seam."""

    @contextlib.contextmanager
    def _openrouter_posture(self) -> Iterator[Any]:
        import utils.ai_client_factory as factory

        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            yield factory

    def test_strategy_path_nests_thinking_under_extra_body(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            with mock.patch.object(config, "OPENROUTER_STRATEGY", "kimi_thinking"):
                with self._openrouter_posture() as factory:
                    result = factory.get_model_config("dm_main", "gpt-6-luna")

            self.assertEqual(
                result["extra_body"],
                {"extra_body": {"thinking": {"type": "enabled"}}},
            )
            self.assertNotIn("thinking", result["extra_body"])

    def test_override_path_uses_the_same_nested_shape(self) -> None:
        with ProviderTripwire():
            config = importlib.import_module("model_config")
            overrides = copy.deepcopy(config.TASK_OVERRIDES)
            overrides["dm_main"] = {"thinking": "disabled"}
            with mock.patch.object(config, "TASK_OVERRIDES", overrides):
                with self._openrouter_posture() as factory:
                    result = factory.get_model_config("dm_main", "gpt-6-luna")

            self.assertEqual(
                result["extra_body"],
                {"extra_body": {"thinking": {"type": "disabled"}}},
            )
            self.assertNotIn("thinking", result["extra_body"])

    def test_direct_openai_path_returns_empty_extra_body(self) -> None:
        with ProviderTripwire():
            import utils.ai_client_factory as factory

            with mock.patch.object(
                factory, "_get_actual_provider", return_value=("openai", False)
            ):
                result = factory.get_model_config("dm_main", "gpt-6-luna")
                params = factory.get_chat_completion_params("dm_main", "gpt-6-luna")

            self.assertEqual(result["extra_body"], {})
            self.assertNotIn("thinking", params)
            self.assertNotIn("extra_body", params)


class TestFactoryChatParamFinalization(unittest.TestCase):
    """Provider-free task-family and provider-isolation contracts."""

    def test_gpt6_luna_task_family_policy_and_sampling_omission(self) -> None:
        import utils.ai_client_factory as factory

        expected = {
            "dm_main": ("medium", "medium"),
            "dm_validation": ("low", "low"),
            "compression": ("low", "low"),
            "summaries": ("medium", "medium"),
        }
        with ProviderTripwire():
            for task_id, (reasoning, verbosity) in expected.items():
                with self.subTest(task_id=task_id):
                    result = factory.finalize_chat_params(
                        "gpt-6-luna",
                        params={
                            "temperature": 0.7,
                            "top_p": 0.2,
                            "max_completion_tokens": 64,
                            "response_format": {"type": "json_object"},
                        },
                        temperature=0.4,
                        task_id=task_id,
                    )
                    self.assertEqual(result["reasoning_effort"], reasoning)
                    self.assertEqual(result["verbosity"], verbosity)
                    self.assertNotIn("temperature", result)
                    self.assertNotIn("top_p", result)
                    self.assertEqual(result["max_completion_tokens"], 64)
                    self.assertEqual(result["response_format"], {"type": "json_object"})

    def test_legacy_gpt5_and_preferred_model_have_same_task_policy(self) -> None:
        import utils.ai_client_factory as factory

        baseline = {
            "dm_main": ("medium", "medium"),
            "dm_validation": ("low", "low"),
            "compression": ("low", "low"),
            "summaries": ("medium", "medium"),
        }
        with ProviderTripwire():
            for task_id, expected in baseline.items():
                with self.subTest(task_id=task_id):
                    legacy = factory.finalize_chat_params(
                        "gpt-5.6-luna", task_id=task_id
                    )
                    preferred = factory.finalize_chat_params(
                        "gpt-6-luna", task_id=task_id
                    )
                    self.assertEqual(
                        (legacy["reasoning_effort"], legacy["verbosity"]), expected
                    )
                    self.assertEqual(
                        (preferred["reasoning_effort"], preferred["verbosity"]), expected
                    )

    def test_summary_task_has_distinct_policy(self) -> None:
        import utils.ai_client_factory as factory

        with ProviderTripwire():
            result = factory.finalize_chat_params("gpt-6-luna", task_id="summary")

        self.assertEqual(result["reasoning_effort"], "low")
        self.assertEqual(result["verbosity"], "medium")

    def test_high_retry_matches_legacy_task_family_policy(self) -> None:
        import utils.ai_client_factory as factory

        with ProviderTripwire():
            for task_id, verbosity in (("combat_main", "medium"), ("dm_validation", "low")):
                with self.subTest(task_id=task_id):
                    result = factory.finalize_chat_params(
                        "gpt-6-luna", retry_tier="high", task_id=task_id
                    )
                    self.assertEqual(result["reasoning_effort"], "high")
                    self.assertEqual(result["verbosity"], verbosity)
                    self.assertNotIn("retry_tier", result)
                    self.assertNotIn("task_id", result)

    def test_openrouter_merges_portable_extensions_under_extra_body(self) -> None:
        import utils.ai_client_factory as factory

        params = {
            "temperature": 0.2,
            "provider": {"order": ["vendor-a"]},
            "reasoning": {"effort": "medium"},
            "plugins": [{"id": "auto-router", "allowed_models": ["vendor-b"]}],
            "extra_body": {
                "extra_body": {
                    "provider": {"allow_fallbacks": True},
                    "plugins": [{"id": "cache-control"}],
                }
            },
        }
        with ProviderTripwire():
            result = factory.finalize_chat_params(
                "openrouter/auto",
                params=params,
                temperature=0.7,
                is_openrouter=True,
                retry_tier="high",
                task_id="dm_main",
            )

        self.assertEqual(result["temperature"], 0.7)
        self.assertEqual(
            result["extra_body"],
            {
                "provider": {"allow_fallbacks": True, "order": ["vendor-a"]},
                "reasoning": {"effort": "medium"},
                "plugins": [
                    {"id": "cache-control"},
                    {"id": "auto-router", "allowed_models": ["vendor-b"]},
                ],
            },
        )
        self.assertNotIn("reasoning_effort", result)
        self.assertNotIn("verbosity", result)
        self.assertNotIn("provider", result)
        self.assertNotIn("task_id", result)
        self.assertNotIn("retry_tier", result)

    def test_openrouter_kwargs_fit_sdk_signature_and_preserve_ordinary_params(self) -> None:
        import utils.ai_client_factory as factory
        from openai.resources.chat.completions import Completions

        signature = inspect.signature(Completions.create)
        params = {
            "messages": [{"role": "user", "content": "hello"}],
            "max_completion_tokens": 64,
            "response_format": {"type": "json_object"},
            "provider": {"order": ["vendor-a"]},
            "reasoning": {"effort": "low"},
            "plugins": [{"id": "auto-router"}],
        }
        with ProviderTripwire():
            result = factory.finalize_chat_params(
                "openrouter/auto",
                params=params,
                temperature=0.2,
                is_openrouter=True,
                task_id="dm_main",
            )

        self.assertTrue(set(result).issubset(set(signature.parameters)))
        self.assertEqual(result["max_completion_tokens"], 64)
        self.assertEqual(result["response_format"], {"type": "json_object"})
        self.assertEqual(
            result["extra_body"],
            {
                "provider": {"order": ["vendor-a"]},
                "reasoning": {"effort": "low"},
                "plugins": [{"id": "auto-router"}],
            },
        )

    def test_direct_openai_strips_portable_extensions_for_nonreasoning_model(self) -> None:
        import utils.ai_client_factory as factory

        with ProviderTripwire():
            result = factory.finalize_chat_params(
                "gpt-4.1-2025-04-14",
                params={
                    "provider": {"order": ["vendor-a"]},
                    "reasoning": {"effort": "high"},
                    "thinking": {"type": "enabled"},
                    "plugins": [{"id": "auto-router"}],
                    "max_completion_tokens": 64,
                },
                temperature=0.3,
                task_id="dm_main",
                retry_tier="high",
            )

        self.assertEqual(result["temperature"], 0.7)
        self.assertEqual(result["max_completion_tokens"], 64)
        for key in ("provider", "reasoning", "thinking", "plugins", "extra_body", "task_id", "retry_tier"):
            self.assertNotIn(key, result)

    def test_direct_openai_strips_vendor_extensions_and_context(self) -> None:
        import utils.ai_client_factory as factory

        with ProviderTripwire():
            result = factory.finalize_chat_params(
                "gpt-6-luna",
                params={
                    "provider": {"order": ["vendor-a"]},
                    "plugins": [{"id": "auto-router"}],
                    "extra_body": {"extra_body": {"thinking": {"type": "enabled"}}},
                },
                retry_tier="retry",
                task_id="dm_validation",
            )

        self.assertEqual(result["reasoning_effort"], "high")
        self.assertEqual(result["verbosity"], "low")
        self.assertNotIn("provider", result)
        self.assertNotIn("plugins", result)
        self.assertNotIn("extra_body", result)
        self.assertNotIn("thinking", result)
        self.assertNotIn("task_id", result)
        self.assertNotIn("retry_tier", result)


class TestFactoryClientTimeoutContracts(unittest.TestCase):
    """Verify factory-owned client bounds without constructing a real client."""

    def _capture_client_kwargs(self, is_openrouter: bool) -> Dict[str, Any]:
        import utils.ai_client_factory as factory

        captured: Dict[str, Any] = {}

        def fake_constructor(**kwargs: Any) -> FakeProviderClient:
            captured.update(kwargs)
            return FakeProviderClient()

        with ProviderTripwire():
            with mock.patch.object(factory, "_get_actual_provider") as provider:
                provider.return_value = (
                    "openrouter" if is_openrouter else "openai",
                    is_openrouter,
                )
                with mock.patch.object(
                    factory,
                    "create_deadline_http_client",
                    return_value=object(),
                ):
                    with mock.patch.object(
                        factory, "OpenAI", side_effect=fake_constructor
                    ):
                        factory.create_chat_client()
        return captured

    def test_openai_client_has_total_and_connect_timeout(self) -> None:
        kwargs = self._capture_client_kwargs(False)
        timeout = kwargs["timeout"]
        config = importlib.import_module("model_config")
        self.assertEqual(
            (timeout.read, timeout.write, timeout.pool),
            (config.API_TIMEOUT_SECONDS,) * 3,
        )
        self.assertEqual(timeout.connect, config.API_CONNECT_TIMEOUT_SECONDS)

    def test_openrouter_client_has_timeout_and_preserves_transport_settings(self) -> None:
        kwargs = self._capture_client_kwargs(True)
        timeout = kwargs["timeout"]
        config = importlib.import_module("model_config")
        self.assertEqual(
            (timeout.read, timeout.write, timeout.pool),
            (config.API_TIMEOUT_SECONDS,) * 3,
        )
        self.assertEqual(timeout.connect, config.API_CONNECT_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(
            kwargs["default_headers"],
            {
                "HTTP-Referer": "https://github.com/zeug/NeverEndingQuest",
                "X-Title": "NeverEndingQuest AI DM",
            },
        )


class TestRouterProfileResolution(unittest.TestCase):
    """Deferred runtime resolution contracts for the profile resolver."""

    @contextlib.contextmanager
    def _config_overrides(self, config: Any, **overrides: Any) -> Iterator[Any]:
        originals = {name: getattr(config, name) for name in overrides}
        try:
            for name, value in overrides.items():
                setattr(config, name, value)
            yield config
        finally:
            for name, value in originals.items():
                setattr(config, name, value)

    @contextlib.contextmanager
    def _router(self, *, provider: str = "openrouter") -> Iterator[Any]:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        with mock.patch.object(
            factory,
            "_get_actual_provider",
            return_value=(provider, provider == "openrouter"),
        ):
            yield llm

    def test_unknown_active_profile_uses_concrete_auto_default(self) -> None:
        import model_config as config

        with ProviderTripwire(), self._config_overrides(config, ACTIVE_PROFILE="missing-profile"):
            with self._router() as router:
                resolved = router.resolve_profile("dm_main")

        self.assertEqual(resolved["profile"], "production-auto")
        self.assertEqual(resolved["model"], "openrouter/auto")
        self.assertNotEqual(resolved["model"], "missing-profile")

    def test_unknown_task_profile_and_incomplete_tier_degrade_safely(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["broken"] = {"complex": {"model": None}, "simple": {}}
        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        overrides["broken_task"] = {"profile": "broken"}
        with ProviderTripwire(), self._config_overrides(
            config, MODEL_PROFILES=profiles, TASK_OVERRIDES=overrides
        ):
            with self._router() as router:
                resolved = router.resolve_profile("broken_task")

        self.assertEqual(resolved["profile"], "broken")
        self.assertEqual(resolved["model"], "openrouter/auto")
        self.assertEqual(resolved["params"], {})
        self.assertEqual(resolved["provider"], {})
        self.assertEqual(resolved["price_per_1k"], {})

    def test_detached_default_mapping_wins_over_arbitrary_first_profile(self) -> None:
        import model_config as config

        default_profile = {
            "complex": {"model": "openrouter/auto"},
            "simple": {"model": "openrouter/auto"},
        }
        profiles = {
            "vendor-first": {
                "complex": {"model": "vendor/first"},
                "simple": {"model": "vendor/first"},
            }
        }
        with ProviderTripwire(), self._config_overrides(
            config,
            MODEL_PROFILES=profiles,
            DEFAULT_PROFILE=default_profile,
            ACTIVE_PROFILE="missing",
        ):
            with self._router() as router:
                resolved = router.resolve_profile("dm_main")

        self.assertEqual(resolved["profile"], "default")
        self.assertEqual(resolved["model"], "openrouter/auto")

    def test_empty_and_profile_label_model_overrides_use_auto(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        overrides["empty_model"] = {"model": ""}
        overrides["label_model"] = {"model": "titan-auto"}
        with ProviderTripwire(), self._config_overrides(
            config, MODEL_PROFILES=profiles, TASK_OVERRIDES=overrides
        ):
            with self._router() as router:
                empty = router.resolve_profile("empty_model")
                label = router.resolve_profile("label_model")

        self.assertEqual(empty["model"], "openrouter/auto")
        self.assertEqual(label["model"], "openrouter/auto")
        self.assertEqual(empty["params"], {})
        self.assertEqual(label["params"], {})

    def test_fallback_preserves_configured_price_rates_without_vendor_fields(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        rates = {"prompt": 0.002, "completion": 0.004}
        profiles["openai/fallback"]["complex"] = {
            "model": "stale/model",
            "params": {"plugins": [{"id": "auto-router"}]},
            "provider": {"order": ["vendor"]},
            "price_per_1k": rates,
        }
        with ProviderTripwire(), self._config_overrides(config, MODEL_PROFILES=profiles):
            with self._router(provider="openai") as router:
                resolved = router.resolve_profile("dm_main")

        self.assertEqual(resolved["model"], config.OPENAI_FALLBACK_MODEL)
        self.assertEqual(resolved["price_per_1k"], rates)
        self.assertEqual(resolved["params"], {})
        self.assertEqual(resolved["provider"], {})

    def test_task_profile_overrides_are_independent_including_titan(self) -> None:
        import model_config as config

        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        overrides.update({"dm_main": {"profile": "titan-auto"}, "combat_main": {"model": "vendor/combat"}})
        with ProviderTripwire(), self._config_overrides(config, TASK_OVERRIDES=overrides):
            with self._router() as router:
                narrator = router.resolve_profile("dm_main")
                combat = router.resolve_profile("combat_main")
                titan = router.resolve_profile("titan_cycle")

        self.assertEqual(narrator["profile"], "titan-auto")
        self.assertEqual(narrator["model"], "openrouter/auto")
        self.assertEqual(combat["model"], "vendor/combat")
        self.assertEqual(titan["profile"], "titan-auto")
        self.assertNotEqual(narrator["profile"], "production-auto")

    def test_complexity_selects_complex_or_simple_tier(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"]["model"] = "vendor/complex"
        profiles["production-auto"]["simple"]["model"] = "vendor/simple"
        with ProviderTripwire(), self._config_overrides(config, MODEL_PROFILES=profiles):
            with self._router() as router:
                complex_result = router.resolve_profile("dm_main")
                simple_result = router.resolve_profile("summaries")

        self.assertEqual(complex_result["tier"], "complex")
        self.assertEqual(complex_result["model"], "vendor/complex")
        self.assertEqual(simple_result["tier"], "simple")
        self.assertEqual(simple_result["model"], "vendor/simple")

    def test_direct_openai_ignores_task_vendor_and_plugins(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"]["params"] = {
            "plugins": [{"id": "auto-router", "allowed_models": ["vendor/x"]}]
        }
        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        overrides["dm_main"] = {"profile": "titan-auto", "model": "vendor/narrator"}
        with ProviderTripwire(), self._config_overrides(
            config, MODEL_PROFILES=profiles, TASK_OVERRIDES=overrides
        ):
            with self._router(provider="openai") as router:
                resolved = router.resolve_profile("dm_main")

        self.assertFalse(resolved["is_openrouter"])
        self.assertEqual(resolved["model"], config.OPENAI_FALLBACK_MODEL)
        self.assertEqual(resolved["provider"], {})
        self.assertEqual(resolved["params"], {})
        self.assertEqual(resolved["price_per_1k"], {})

    def test_fallback_uses_current_model_not_cached_profile_literal(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["openai/fallback"]["complex"]["model"] = "stale/model"
        with ProviderTripwire(), self._config_overrides(
            config, MODEL_PROFILES=profiles, OPENAI_FALLBACK_MODEL="configured/current"
        ):
            with self._router(provider="openai") as router:
                resolved = router.resolve_profile("dm_main", use_fallback=True)

        self.assertEqual(resolved["model"], "configured/current")
        self.assertEqual(resolved["profile"], "openai/fallback")

    def test_missing_fallback_constant_uses_approved_safe_model(self) -> None:
        import model_config as config

        with ProviderTripwire(), mock.patch.object(config, "OPENAI_FALLBACK_MODEL", None):
            with self._router(provider="openai") as router:
                resolved = router.resolve_profile("dm_main")

        self.assertEqual(resolved["model"], "gpt-6-luna")

    def test_explicit_model_does_not_inherit_profile_params_or_pricing(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"]["params"] = {"plugins": [{"id": "auto-router"}]}
        profiles["production-auto"]["complex"]["provider"] = {"order": ["vendor"]}
        profiles["production-auto"]["complex"]["price_per_1k"] = {"prompt": 9.0}
        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        overrides["dm_main"] = {"model": "vendor/explicit"}
        with ProviderTripwire(), self._config_overrides(
            config, MODEL_PROFILES=profiles, TASK_OVERRIDES=overrides
        ):
            with self._router() as router:
                resolved = router.resolve_profile("dm_main")

        self.assertTrue(resolved["explicit_model"])
        self.assertEqual(resolved["model"], "vendor/explicit")
        self.assertEqual(resolved["params"], {})
        self.assertEqual(resolved["provider"], {})
        self.assertEqual(resolved["price_per_1k"], {})

    def test_optional_auto_router_plugin_is_preserved_without_mutation(self) -> None:
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        plugin = {"id": "auto-router", "cost_tier": "low", "allowed_models": ["vendor/a"]}
        profiles["production-auto"]["complex"]["params"] = {"plugins": [plugin]}
        original = copy.deepcopy(profiles)
        with ProviderTripwire(), self._config_overrides(config, MODEL_PROFILES=profiles):
            with self._router() as router:
                resolved = router.resolve_profile("dm_main")

        self.assertEqual(resolved["params"], {"plugins": [plugin]})
        self.assertEqual(profiles, original)
        resolved["params"]["plugins"][0]["allowed_models"].append("vendor/b")
        self.assertEqual(profiles, original)


class TestRouterCallContract(unittest.TestCase):
    """Provider-free transport and facade behavior for task 4.2."""

    def _call_with(self, primary: SequenceProviderClient, *fallback: SequenceProviderClient, **call_kwargs: Any) -> Any:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        clients = [primary, *fallback]
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", side_effect=clients):
                return llm.call("dm_main", [{"role": "user", "content": "hello"}], **call_kwargs)

    def test_text_and_dictionary_contracts(self) -> None:
        with ProviderTripwire():
            text = self._call_with(SequenceProviderClient([_response("hello")]))
            obj = self._call_with(SequenceProviderClient([_response('{"ok": true}')]), json_output=True)
        self.assertEqual(text, "hello")
        self.assertEqual(obj, {"ok": True})

    def test_direct_openai_approved_model_policy_and_return_shapes(self) -> None:
        """Exercise both direct-OpenAI tiers through captured fake SDK kwargs."""
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        messages = [{"role": "user", "content": "immutable prompt"}]
        original_messages = copy.deepcopy(messages)
        original_overrides = copy.deepcopy(config.TASK_OVERRIDES)
        original_profiles = copy.deepcopy(config.MODEL_PROFILES)
        hostile_overrides = copy.deepcopy(config.TASK_OVERRIDES)
        hostile_overrides.update(
            {
                "dm_main": {
                    "profile": "titan-auto",
                    "model": "vendor/narrator",
                    "provider": {"order": ["vendor-narrator"]},
                },
                "summaries": {
                    "profile": "production-auto",
                    "model": "vendor/summary",
                    "plugins": [{"id": "vendor-plugin"}],
                },
            }
        )
        hostile_profiles = copy.deepcopy(config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            hostile_profiles["openai/fallback"][tier] = {
                "model": "vendor/stale-profile-model",
                "params": {
                    "provider": {"order": ["vendor-profile"]},
                    "plugins": [{"id": "vendor-profile-plugin"}],
                    "thinking": {"type": "enabled"},
                },
                "provider": {"order": ["vendor-profile"]},
                "price_per_1k": {"prompt": 99.0, "completion": 99.0},
            }

        text_client = SequenceProviderClient([_response("direct text")])
        dict_client = SequenceProviderClient([_response('{"kind": "dictionary"}')])
        retry_client = SequenceProviderClient([_response("high retry")])
        hostile_kwargs = {
            "provider": {"order": ["vendor-kwarg"]},
            "plugins": [{"id": "vendor-kwarg-plugin"}],
            "reasoning": {"effort": "high"},
            "thinking": {"type": "enabled"},
            "extra_body": {"extra_body": {"provider": {"order": ["vendor-extra"]}}},
            "top_p": 0.01,
        }

        with ProviderTripwire():
            with mock.patch.object(config, "TASK_OVERRIDES", hostile_overrides):
                with mock.patch.object(config, "MODEL_PROFILES", hostile_profiles):
                    with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
                        with mock.patch.object(
                            factory,
                            "create_chat_client",
                            side_effect=[text_client, dict_client, retry_client],
                        ):
                            text = llm.call("dm_main", messages, **hostile_kwargs)
                            parsed = llm.call(
                                "summaries", messages, json_output=True, **hostile_kwargs
                            )
                            retried = llm.call(
                                "dm_validation",
                                messages,
                                retry_tier="high",
                                **hostile_kwargs,
                            )

        self.assertEqual(text, "direct text")
        self.assertEqual(parsed, {"kind": "dictionary"})
        self.assertEqual(retried, "high retry")
        for client, expected_policy in (
            (text_client, ("medium", "medium")),
            (dict_client, ("medium", "medium")),
            (retry_client, ("high", "low")),
        ):
            self.assertEqual(len(client.calls), 1)
            request = client.calls[0]
            self.assertEqual(request["model"], "gpt-6-luna")
            self.assertEqual(
                (request["reasoning_effort"], request["verbosity"]), expected_policy
            )
            self.assertEqual(request["messages"], original_messages)
            self.assertNotIn("provider", request)
            self.assertNotIn("plugins", request)
            self.assertNotIn("reasoning", request)
            self.assertNotIn("thinking", request)
            self.assertNotIn("extra_body", request)
            self.assertNotIn("temperature", request)
            self.assertNotIn("top_p", request)
            self.assertNotIn("task_id", request)
            self.assertNotIn("retry_tier", request)

        self.assertEqual(messages, original_messages)
        self.assertEqual(config.TASK_OVERRIDES, original_overrides)
        self.assertEqual(config.MODEL_PROFILES, original_profiles)

    def test_direct_openai_uses_alternate_configured_fallback_for_both_tiers(self) -> None:
        """The approved model is configurable without admitting vendor profile data."""
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        complex_client = SequenceProviderClient([_response("complex")])
        simple_client = SequenceProviderClient([_response("simple")])
        with ProviderTripwire():
            with mock.patch.object(config, "OPENAI_FALLBACK_MODEL", "configured-direct-model"):
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
                    with mock.patch.object(
                        factory,
                        "create_chat_client",
                        side_effect=[complex_client, simple_client],
                    ):
                        self.assertEqual(llm.call("dm_main", []), "complex")
                        self.assertEqual(llm.call("summaries", []), "simple")

        self.assertEqual(complex_client.calls[0]["model"], "configured-direct-model")
        self.assertEqual(simple_client.calls[0]["model"], "configured-direct-model")

    def test_quota_wins_over_transient_classification(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMTerminalError, llm

        for json_output in (False, True):
            with self.subTest(json_output=json_output):
                primary = SequenceProviderClient(
                    [RuntimeError("quota exceeded: rate limit 429")]
                )
                with mock.patch.object(
                    factory, "_get_actual_provider", return_value=("openrouter", True)
                ):
                    with mock.patch.object(
                        factory, "create_chat_client", return_value=primary
                    ) as create_client:
                        with self.assertRaises(GameLLMTerminalError) as raised:
                            llm.call("dm_main", [], json_output=json_output)
                self.assertEqual(len(primary.calls), 1)
                self.assertEqual(create_client.call_count, 1)
                self.assertEqual(raised.exception.terminal_kind, "quota")

    def test_refusal_and_filter_are_terminal_for_text_and_json_calls(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMError, GameLLMTerminalError, llm

        for kind in ("refusal", "content_filter"):
            for json_output in (False, True):
                with self.subTest(kind=kind, json_output=json_output):
                    llm.reset_usage_stats()
                    response = _terminal_response(kind)
                    primary = SequenceProviderClient([response])
                    receipts = []
                    with mock.patch.object(
                        factory, "_get_actual_provider", return_value=("openrouter", True)
                    ):
                        with mock.patch.object(
                            factory, "create_chat_client", return_value=primary
                        ) as create_client:
                            with self.assertRaises(GameLLMTerminalError) as raised:
                                llm.call(
                                    "dm_main",
                                    [{"role": "user", "content": "PRIVATE_PROMPT_SENTINEL"}],
                                    json_output=json_output,
                                    observer=lambda receipt, raw: receipts.append((receipt, raw)),
                                )

                    self.assertIsInstance(raised.exception, GameLLMError)
                    self.assertEqual(raised.exception.terminal_kind, kind)
                    self.assertNotIn("provider terminal payload", str(raised.exception))
                    self.assertEqual(len(primary.calls), 1)
                    self.assertEqual(create_client.call_count, 1)
                    self.assertEqual(len(receipts), 1)
                    receipt, observed_raw = receipts[0]
                    self.assertEqual(receipt.kind, "response")
                    self.assertIs(observed_raw, response)
                    self.assertEqual(receipt.attempt_number, 1)
                    self.assertEqual(receipt.prompt_tokens, 4)
                    self.assertEqual(receipt.completion_tokens, 0)
                    self.assertEqual(receipt.provider_reported_cost_usd, 0.0)
                    self.assertEqual(receipt.cost_usd, 0.0)
                    self.assertEqual(receipt.cost_provenance, "actual")
                    self.assertEqual(receipt.resolved_model, "unknown")
                    self.assertNotIn("PRIVATE_PROMPT_SENTINEL", repr(receipt))
                    self.assertNotIn("provider refusal payload", repr(receipt))
                    stats = llm.get_usage_stats()
                    self.assertEqual(stats["calls"], 1)
                    self.assertEqual(stats["transport_attempts"], 1)
                    self.assertEqual(stats["total_cost_usd"], 0.0)

    def test_quota_constructor_and_nested_fallback_constructor_are_typed(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMTerminalError, llm

        for nested in (False, True):
            with self.subTest(nested=nested):
                llm.reset_usage_stats()
                receipts = []
                quota_error = RuntimeError("quota: private provider body")
                if nested:
                    primary = SequenceProviderClient([RuntimeError("503")])
                    create_outcomes = [primary, quota_error]
                else:
                    create_outcomes = [quota_error]
                with mock.patch.object(
                    factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]
                ):
                    with mock.patch.object(
                        factory, "create_chat_client", side_effect=create_outcomes
                    ) as create_client:
                        with self.assertRaises(GameLLMTerminalError) as raised:
                            llm.call(
                                "dm_main", [],
                                observer=lambda receipt, raw: receipts.append((receipt, raw)),
                            )

                self.assertEqual(raised.exception.terminal_kind, "quota")
                self.assertNotIn("private provider body", str(raised.exception))
                self.assertEqual(len(receipts), 1 if not nested else 2)
                constructor_receipts = [r for r, _ in receipts if r.kind == "constructor_error"]
                self.assertEqual(len(constructor_receipts), 1)
                self.assertIsNone(constructor_receipts[0].attempt_number)
                self.assertEqual(constructor_receipts[0].prompt_tokens, None)
                self.assertEqual(constructor_receipts[0].cost_usd, None)
                self.assertEqual(create_client.call_count, 1 if not nested else 2)
                stats = llm.get_usage_stats()
                self.assertEqual(stats["transport_attempts"], 0 if not nested else 1)
                self.assertEqual(stats["calls"], 0)
                self.assertEqual(stats["total_cost_usd"], 0.0)
                self.assertEqual(stats["errors"], 1 if not nested else 2)

    def test_terminal_error_raised_by_observer_is_isolated_as_callback_failure(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMTerminalError, llm

        client = SequenceProviderClient([_response("ordinary success")])

        def observer(receipt: Any, raw: Any) -> None:
            raise GameLLMTerminalError("refusal")

        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", return_value=client):
                self.assertEqual(llm.call("dm_main", [], observer=observer), "ordinary success")

    def test_transient_errors_use_one_direct_openai_fallback(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        for message in ("timeout", "connection reset", "429", "502", "503", "504"):
            with self.subTest(message=message):
                primary = SequenceProviderClient([RuntimeError(message)])
                fallback = SequenceProviderClient([_response("fallback")])
                with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
                    with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]) as create:
                        self.assertEqual(llm.call("dm_main", []), "fallback")
                self.assertEqual(create.call_args_list[1], mock.call(use_fallback=True))
                self.assertEqual(len(fallback.calls), 1)

    def test_fallback_exhaustion_and_unclassified_errors_reraise(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        primary = SequenceProviderClient([RuntimeError("unavailable")])
        fallback = SequenceProviderClient([RuntimeError("503")])
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]):
                with self.assertRaisesRegex(RuntimeError, "503"):
                    llm.call("dm_main", [])

        unknown = RuntimeError("bad request")
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", return_value=SequenceProviderClient([unknown])):
                with self.assertRaises(RuntimeError) as raised:
                    llm.call("dm_main", [])
        self.assertIs(raised.exception, unknown)

    def test_json_retries_fresh_attempts_and_rejects_nonobjects(self) -> None:
        primary = SequenceProviderClient([_response("not json"), _response("[]"), _response('{"ok": 1}')])
        with ProviderTripwire():
            result = self._call_with(primary, json_output=True)
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(len(primary.calls), 3)
        self.assertEqual(primary.calls[0]["messages"], primary.calls[1]["messages"])

    def test_profile_provider_is_carried_into_openrouter_extra_body(self) -> None:
        import model_config as config
        from utils.llm_router import llm

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"]["provider"] = {"order": ["vendor-a"]}
        client = SequenceProviderClient([_response("ok")])
        with mock.patch.object(config, "MODEL_PROFILES", profiles):
            with mock.patch("utils.ai_client_factory._get_actual_provider", return_value=("openrouter", True)):
                with mock.patch("utils.ai_client_factory.create_chat_client", return_value=client):
                    self.assertEqual(llm.call("dm_main", []), "ok")
        self.assertEqual(client.calls[0]["extra_body"]["provider"], {"order": ["vendor-a"]})

    def test_late_fallback_shares_three_json_response_attempt_budget(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import LLMJSONError, llm

        primary = SequenceProviderClient([_response("bad"), _response("[]"), RuntimeError("503")])
        fallback = SequenceProviderClient([_response('{"ok": true}')])
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]):
                self.assertEqual(llm.call("dm_main", [], json_output=True), {"ok": True})
        self.assertEqual(len(primary.calls), 3)
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual(sum((len(primary.calls), len(fallback.calls))), 4)

        exhausted_fallback = SequenceProviderClient([_response("bad"), _response("bad")])
        primary = SequenceProviderClient([_response("bad"), RuntimeError("timeout")])
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, exhausted_fallback]):
                with self.assertRaisesRegex(LLMJSONError, "task dm_main"):
                    llm.call("dm_main", [], json_output=True)
        self.assertEqual(len(primary.calls) + len(exhausted_fallback.calls), 4)

    def test_json_exhaustion_raises_json_error_and_dict_content_is_valid(self) -> None:
        from utils.llm_router import LLMJSONError

        exhausted = SequenceProviderClient([_response("bad"), _response("bad"), _response("bad")])
        with self.assertRaises(LLMJSONError):
            self._call_with(exhausted, json_output=True)
        self.assertEqual(len(exhausted.calls), 3)
        self.assertEqual(
            self._call_with(SequenceProviderClient([_response({"already": "object"})]), json_output=True),
            {"already": "object"},
        )

    def test_kwargs_are_detached_and_factory_policy_shapes_token_bound(self) -> None:
        import utils.ai_client_factory as factory

        messages = [{"role": "user", "content": "hello"}]
        extensions = {"provider": {"order": ["vendor"]}}
        original = copy.deepcopy(extensions)
        client = SequenceProviderClient([_response("ok")])
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", return_value=client):
                from utils.llm_router import llm
                self.assertEqual(llm.call("dm_validation", messages, max_tokens=32, **extensions), "ok")
        self.assertEqual(extensions, original)
        self.assertEqual(client.calls[0]["max_completion_tokens"], 32)
        self.assertNotIn("max_tokens", client.calls[0])
        self.assertNotIn("retry_tier", client.calls[0])
        self.assertNotIn("provider", client.calls[0])

    def test_high_retry_reaches_factory_and_fallback_extensions_stay_isolated(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        primary = SequenceProviderClient([RuntimeError("timeout")])
        fallback = SequenceProviderClient([_response("ok")])
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]):
                with mock.patch.object(factory, "finalize_chat_params", wraps=factory.finalize_chat_params) as finalize:
                    self.assertEqual(llm.call("combat_main", [], retry_tier="high", provider={"order": ["x"]}), "ok")
        self.assertEqual(finalize.call_args_list[0].kwargs["retry_tier"], "high")
        self.assertNotIn("provider", fallback.calls[0])

    def test_real_factory_notification_preserves_original_provider_once(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        factory.reset_fallback_status()
        primary = SequenceProviderClient([RuntimeError("timeout")])
        fallback = SequenceProviderClient([_response("ok")])
        with mock.patch.object(
            factory,
            "_get_actual_provider",
            side_effect=[
                ("openrouter", True),
                ("openrouter", True),
                ("openai", False),
                ("openai", False),
            ],
        ):
            with mock.patch.object(
                factory,
                "create_deadline_http_client",
                return_value=object(),
            ):
                with mock.patch.object(
                    factory, "OpenAI", side_effect=[primary, fallback]
                ):
                    self.assertEqual(llm.call("dm_main", []), "ok")
        notification = factory.get_fallback_notification()
        self.assertIsNotNone(notification)
        self.assertIn("openrouter", notification.lower())
        self.assertIsNone(factory.get_fallback_notification())
        self.assertEqual(factory._fallback_status["fallback_count"], 1)
        self.assertEqual(factory._fallback_status["primary_provider"], "openrouter")
        self.assertEqual(fallback.options, {"max_retries": 0})

        factory.reset_fallback_status()
        factory._fallback_status["primary_provider"] = "openrouter"
        factory._fallback_status["fallback_provider"] = "openai"
        factory.handle_provider_error(RuntimeError("timeout"), context="dm_main")
        self.assertIsNotNone(factory.get_fallback_notification())

    def test_quota_during_client_construction_names_task_and_model(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMTerminalError, llm

        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(
                factory, "create_chat_client", side_effect=RuntimeError("quota exceeded")
            ):
                with self.assertRaises(GameLLMTerminalError) as raised:
                    llm.call("dm_main", [])
        self.assertEqual(raised.exception.terminal_kind, "quota")

    def test_quota_during_fallback_construction_names_task_and_model(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMTerminalError, llm

        primary = SequenceProviderClient([RuntimeError("timeout")])
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(
                factory, "create_chat_client", side_effect=[primary, RuntimeError("billing quota")]
            ):
                with self.assertRaises(GameLLMTerminalError) as raised:
                    llm.call("dm_main", [])
        self.assertEqual(raised.exception.terminal_kind, "quota")


class TestRouterUsageAccounting(unittest.TestCase):
    """Provider-free contracts for one-response, cache-aware accounting."""

    def setUp(self) -> None:
        from utils.llm_router import reset_usage_stats
        reset_usage_stats()

    @staticmethod
    def _response(model: Any = None, cost: Any = None, *, prompt: int = 10, cached: int = 0, completion: int = 5) -> Dict[str, Any]:
        usage: Dict[str, Any] = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        }
        if cost is not None:
            usage["cost"] = cost
        response: Dict[str, Any] = {"choices": [{"message": {"content": "ok"}}], "usage": usage}
        if model is not None:
            response["model"] = model
        return response

    def _call(self, response: Dict[str, Any], *, rates: Optional[Dict[str, float]] = None) -> Any:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"]["model"] = "vendor/model"
        profiles["production-auto"]["complex"]["price_per_1k"] = rates or {}
        client = SequenceProviderClient([response])
        with mock.patch.object(config, "MODEL_PROFILES", profiles):
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                with mock.patch.object(factory, "create_chat_client", return_value=client):
                    return llm.call("dm_main", [])

    def _fallback_call(self, primary: SequenceProviderClient, fallback: Any) -> Any:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"]["model"] = "openrouter/auto"
        with mock.patch.object(config, "MODEL_PROFILES", profiles):
            with mock.patch.object(
                factory,
                "_get_actual_provider",
                side_effect=[("openrouter", True), ("openai", False)],
            ):
                with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]):
                    return llm.call("dm_main", [])

    def test_actual_zero_cost_is_complete_and_counted_once(self) -> None:
        self._call(self._response("vendor/model", 0.0))
        from utils.llm_router import get_usage_stats
        stats = get_usage_stats()
        self.assertEqual(stats["calls"], 1)
        self.assertEqual(stats["total_cost_usd"], 0.0)
        self.assertTrue(stats["cost_complete"])

    def test_quota_and_unclassified_errors_do_not_count_fallback(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMError, get_usage_stats, llm

        for message in ("quota exceeded", "bad request"):
            with self.subTest(message=message):
                self.setUp()
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                    with mock.patch.object(factory, "create_chat_client", side_effect=RuntimeError(message)):
                        with self.assertRaises((GameLLMError, RuntimeError)):
                            llm.call("dm_main", [])
                stats = get_usage_stats()
                self.assertEqual(stats["fallbacks"], 0)
                self.assertEqual(stats["errors"], 1)

    def test_successful_fallback_counts_one_switch_and_one_primary_error(self) -> None:
        primary = SequenceProviderClient([RuntimeError("timeout")])
        fallback = SequenceProviderClient([self._response("gpt-6-luna", 0.01)])
        self._fallback_call(primary, fallback)
        from utils.llm_router import get_usage_stats
        stats = get_usage_stats()
        self.assertEqual((stats["fallbacks"], stats["errors"], stats["calls"]), (1, 1, 1))
        response_diag = [item for item in stats["diagnostics"] if item["provenance"] == "actual"][0]
        self.assertEqual(response_diag["requested_model"], "gpt-6-luna")

    def test_failed_fallback_constructor_records_second_error(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats

        primary = SequenceProviderClient([RuntimeError("503")])
        with mock.patch.object(
            factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]
        ):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, RuntimeError("constructor failed")]):
                with self.assertRaisesRegex(RuntimeError, "constructor failed"):
                    from utils.llm_router import llm
                    llm.call("dm_main", [])
        stats = get_usage_stats()
        self.assertEqual((stats["fallbacks"], stats["errors"], stats["calls"]), (1, 2, 0))

    def test_invalid_json_responses_are_each_counted_once(self) -> None:
        from utils.llm_router import LLMJSONError, get_usage_stats, llm
        import utils.ai_client_factory as factory

        client = SequenceProviderClient([
            self._response("vendor/model", 0.01),
            self._response("vendor/model", 0.02),
            self._response("vendor/model", 0.03),
        ])
        for response in client._outcomes:
            response["choices"][0]["message"]["content"] = "not json"
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
            with mock.patch.object(factory, "create_chat_client", return_value=client):
                with self.assertRaises(LLMJSONError):
                    llm.call("dm_main", [], json_output=True)
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["errors"]), (3, 3))
        self.assertEqual(stats["total_cost_usd"], 0.06)

    def test_invalid_or_missing_cost_uses_compatible_rates_only(self) -> None:
        rates = {"prompt": 2.0, "completion": 4.0, "cache_read": 1.0}
        for invalid in (None, True, float("nan"), float("inf"), -1.0):
            with self.subTest(cost=invalid):
                self.setUp()
                response = self._response("vendor/model", invalid, prompt=10, cached=4, completion=5)
                if invalid is None:
                    response["usage"].pop("cost", None)
                self._call(response, rates=rates)
                from utils.llm_router import get_usage_stats
                stats = get_usage_stats()
                self.assertEqual(stats["total_cost_usd"], 0.036)
                self.assertEqual(stats["diagnostics"][0]["provenance"], "estimated")

    def test_missing_cache_rate_uses_prompt_rate(self) -> None:
        self._call(
            self._response("vendor/model", None, prompt=10, cached=4, completion=5),
            rates={"prompt": 2.0, "completion": 4.0},
        )
        from utils.llm_router import get_usage_stats
        self.assertEqual(get_usage_stats()["total_cost_usd"], 0.04)

    def test_invalid_cost_values_preserve_tokens_and_mark_unpriced(self) -> None:
        from utils.llm_router import get_usage_stats

        for invalid in (None, True, float("nan"), float("inf"), -1.0):
            with self.subTest(cost=invalid):
                self.setUp()
                response = self._response(None, invalid, prompt=10, cached=4, completion=5)
                if invalid is None:
                    response["usage"].pop("cost", None)
                self._call(response)
                stats = get_usage_stats()
                self.assertEqual((stats["prompt_tokens"], stats["cached_tokens"], stats["completion_tokens"]), (10, 4, 5))
                self.assertEqual((stats["unpriced_calls"], stats["cost_complete"]), (1, False))

    def test_auto_unknown_model_is_unpriced_and_unknown_bucket(self) -> None:
        self._call(self._response(None, None), rates={"prompt": 1.0, "completion": 1.0})
        from utils.llm_router import get_usage_stats
        stats = get_usage_stats()
        self.assertIn("unknown", stats["by_model"])
        self.assertEqual(stats["unpriced_calls"], 1)
        self.assertFalse(stats["cost_complete"])

        self.setUp()
        self._call(self._response("vendor/resolved", 0.01))
        diagnostic = get_usage_stats()["diagnostics"][0]
        self.assertEqual(diagnostic["requested_model"], "vendor/model")
        self.assertEqual(diagnostic["resolved_model"], "vendor/resolved")

    def test_missing_usage_does_not_fail_or_inflate_tokens(self) -> None:
        response = {"choices": [{"message": {"content": "ok"}}], "model": "vendor/model"}
        self._call(response, rates={"prompt": 1.0, "completion": 1.0})
        from utils.llm_router import get_usage_stats
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["prompt_tokens"], stats["completion_tokens"]), (1, 0, 0))
        self.assertEqual(stats["unpriced_calls"], 1)

    def test_snapshot_is_detached_reset_and_concurrent(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm, reset_usage_stats

        clients = [SequenceProviderClient([self._response("openrouter/auto", 0.01)]) for _ in range(20)]

        def run(client: SequenceProviderClient) -> None:
            llm.call("dm_main", [{"role": "user", "content": "concurrent"}])

        threads = [threading.Thread(target=run, args=(client,)) for client in clients]
        clients_iter = iter(clients)
        clients_lock = threading.Lock()
        def next_client() -> SequenceProviderClient:
            with clients_lock:
                return next(clients_iter)
        with ProviderTripwire() as tripwire:
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                with mock.patch.object(factory, "create_chat_client", side_effect=next_client):
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
            tripwire.assert_untouched(self)
        snapshot = get_usage_stats()
        self.assertEqual(snapshot["calls"], 20)
        snapshot["by_task"]["dm_main"]["calls"] = 0
        self.assertEqual(get_usage_stats()["by_task"]["dm_main"]["calls"], 20)
        reset_usage_stats()
        self.assertEqual(get_usage_stats()["calls"], 0)


class TestRouterReceiptObserverAndTier(unittest.TestCase):
    """Provider-free contracts for optional per-call receipts and route hints."""

    def setUp(self) -> None:
        from utils.llm_router import reset_usage_stats
        reset_usage_stats()

    def test_keyword_only_signature_and_tier_hint_is_not_forwarded(self) -> None:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import LLMRouter

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"]["model"] = "vendor/complex"
        profiles["production-auto"]["simple"]["model"] = "vendor/simple"
        client = SequenceProviderClient([_response("chosen")])
        signature = inspect.signature(LLMRouter.call)
        self.assertEqual(signature.parameters["observer"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(signature.parameters["model_tier"].kind, inspect.Parameter.KEYWORD_ONLY)

        with ProviderTripwire():
            with mock.patch.object(config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                    with mock.patch.object(factory, "create_chat_client", return_value=client):
                        self.assertEqual(LLMRouter().call("summaries", [], model_tier="complex"), "chosen")
        self.assertEqual(client.calls[0]["model"], "vendor/complex")
        self.assertNotIn("model_tier", client.calls[0])

    def test_invalid_tier_fails_before_provider_resolution_or_construction(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import LLMRouter

        with mock.patch.object(factory, "_get_actual_provider", side_effect=AssertionError("resolved")):
            with mock.patch.object(factory, "create_chat_client", side_effect=AssertionError("constructed")):
                with self.assertRaisesRegex(ValueError, "model_tier"):
                    LLMRouter().call("dm_main", [], model_tier="arbitrary/model")

    def test_explicit_task_model_override_wins_over_tier_hint(self) -> None:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import LLMRouter

        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        overrides["dm_main"] = {"model": "vendor/explicit"}
        client = SequenceProviderClient([_response("ok")])
        with mock.patch.object(config, "TASK_OVERRIDES", overrides):
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                with mock.patch.object(factory, "create_chat_client", return_value=client):
                    self.assertEqual(LLMRouter().call("dm_main", [], model_tier="simple"), "ok")
        self.assertEqual(client.calls[0]["model"], "vendor/explicit")

    def test_receipt_provenance_retry_fallback_and_raw_mutation_isolation(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        primary = SequenceProviderClient([_response("unused"), RuntimeError("timeout")])
        fallback_response = {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "model": "resolved/upstream",
            "provider": "upstream-x",
            "usage": {
                "prompt_tokens": 10, "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 2}, "cost": 0.0,
            },
        }
        fallback = SequenceProviderClient([fallback_response])
        receipts = []
        raw_values = []

        def observe(event: Any, raw: Any) -> None:
            receipts.append(event)
            raw_values.append(raw)
            if isinstance(raw, dict):
                raw["choices"][0]["message"]["content"] = "mutated"

        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]):
                result = llm.call("dm_main", [], json_output=True, retry_tier="high", observer=observe)

        self.assertEqual(result, {"ok": True})
        self.assertEqual([event.kind for event in receipts], ["response", "transport_error", "response"])
        self.assertEqual(len({event.call_id for event in receipts}), 1)
        self.assertEqual(len({event.attempt_id for event in receipts}), 3)
        self.assertEqual([event.attempt_number for event in receipts], [1, 2, 3])
        self.assertEqual([event.transport_retry for event in receipts], [False, True, True])
        self.assertEqual([event.retry_tier for event in receipts], ["high", "high", "high"])
        self.assertNotIn("retry_tier", primary.calls[0])
        self.assertNotIn("retry_tier", fallback.calls[0])
        self.assertEqual([event.fallback for event in receipts], [False, False, True])
        self.assertEqual(receipts[0].transport_provider, "openrouter")
        self.assertEqual(receipts[-1].transport_provider, "openai")
        self.assertEqual(receipts[-1].observed_upstream_provider, "upstream-x")
        self.assertEqual(receipts[-1].requested_model, "gpt-6-luna")
        self.assertEqual(receipts[-1].resolved_model, "resolved/upstream")
        self.assertEqual(receipts[-1].provider_reported_cost_usd, 0.0)
        self.assertEqual(receipts[-1].cost_usd, 0.0)
        self.assertEqual(receipts[-1].cost_provenance, "actual")
        self.assertEqual(receipts[-1].prompt_tokens, 10)
        self.assertEqual(receipts[-1].cached_tokens, 2)
        self.assertEqual(receipts[-1].completion_tokens, 3)
        self.assertTrue(receipts[-1].cost_complete)
        self.assertIsNone(receipts[1].provider_reported_cost_usd)
        self.assertEqual(receipts[1].cost_provenance, "error")
        self.assertEqual(receipts[1].error_type, "RuntimeError")
        self.assertIsNone(raw_values[1])
        self.assertEqual(receipts[0].observed_upstream_provider, "unknown")
        self.assertEqual(receipts[0].cost_provenance, "unpriced")
        self.assertEqual(raw_values[-1]["choices"][0]["message"]["content"], "mutated")
        self.assertEqual(receipts[-1].stats_snapshot["calls"], 2)
        with self.assertRaises(TypeError):
            receipts[-1].stats_snapshot["calls"] = 100

    def test_receipt_estimate_and_malformed_response_are_observed_once(self) -> None:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMError, llm

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"].update(
            {"model": "vendor/model", "price_per_1k": {"prompt": 2.0, "completion": 4.0}}
        )
        estimated = {
            "choices": [{"message": {"content": "priced"}}],
            "model": "vendor/model",
            "usage": {
                "prompt_tokens": 10, "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        }
        client = SequenceProviderClient([estimated])
        receipts = []
        with mock.patch.object(config, "MODEL_PROFILES", profiles):
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                with mock.patch.object(factory, "create_chat_client", return_value=client):
                    self.assertEqual(llm.call("dm_main", [], observer=lambda event, raw: receipts.append(event)), "priced")
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0].cost_provenance, "estimated")
        self.assertTrue(receipts[0].usage_complete)
        self.assertIsNone(receipts[0].provider_reported_cost_usd)
        self.assertAlmostEqual(receipts[0].cost_usd, 0.04)

        malformed_client = SequenceProviderClient([{"usage": {"prompt_tokens": 2}}])
        malformed_receipts = []
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", return_value=malformed_client):
                with self.assertRaises(GameLLMError):
                    llm.call("dm_main", [], observer=lambda event, raw: malformed_receipts.append(event))
        self.assertEqual(len(malformed_receipts), 1)
        self.assertEqual(malformed_receipts[0].kind, "response")
        self.assertEqual(malformed_receipts[0].attempt_number, 1)
        self.assertEqual(malformed_receipts[0].prompt_tokens, 2)

    def test_missing_partial_cached_and_mismatched_usage_are_unknown(self) -> None:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["production-auto"]["complex"].update(
            {"model": "vendor/model", "price_per_1k": {"prompt": 2.0, "completion": 4.0}}
        )
        responses = [
            {"choices": [{"message": {"content": "no usage"}}], "model": "vendor/model"},
            {"choices": [{"message": {"content": "partial"}}], "model": "vendor/model",
             "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            {"choices": [{"message": {"content": "mismatch"}}], "model": "resolved-other",
             "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                       "prompt_tokens_details": {"cached_tokens": 0}}},
            {"choices": [{"message": {"content": "actual zero"}}], "model": "vendor/model",
             "usage": {"cost": 0.0}},
        ]
        receipts = []
        clients = [SequenceProviderClient([response]) for response in responses]
        with mock.patch.object(config, "MODEL_PROFILES", profiles):
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                with mock.patch.object(factory, "create_chat_client", side_effect=clients):
                    for _ in responses:
                        llm.call("dm_main", [], observer=lambda event, raw: receipts.append(event))
        self.assertEqual(len(receipts), 4)
        self.assertFalse(receipts[0].usage_complete)
        self.assertIsNone(receipts[0].prompt_tokens)
        self.assertIsNone(receipts[0].cached_tokens)
        self.assertIsNone(receipts[0].completion_tokens)
        self.assertFalse(receipts[1].usage_complete)
        self.assertEqual(receipts[1].prompt_tokens, 10)
        self.assertIsNone(receipts[1].cached_tokens)
        self.assertEqual(receipts[1].completion_tokens, 5)
        self.assertTrue(receipts[2].usage_complete)
        for receipt in receipts[:3]:
            self.assertIsNone(receipt.cost_usd)
            self.assertEqual(receipt.cost_provenance, "unpriced")
        self.assertEqual(receipts[3].provider_reported_cost_usd, 0.0)
        self.assertEqual(receipts[3].cost_usd, 0.0)
        self.assertEqual(receipts[3].cost_provenance, "actual")
        self.assertFalse(receipts[3].usage_complete)

    def test_observer_exception_isolated_and_absence_is_accounted(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm

        client = SequenceProviderClient([_response("stable")])
        before_events = len(ROUTER_TEST_TRACKER.events)
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", return_value=client) as create:
                self.assertEqual(llm.call("dm_main", []), "stable")
                create.assert_called_once_with()
        self.assertEqual(len(ROUTER_TEST_TRACKER.events), before_events + 1)
        self.assertTrue(ROUTER_TEST_TRACKER.events[-1][1]["attempt_id"])

        client = SequenceProviderClient([_response("stable")])
        def broken_observer(event: Any, raw: Any) -> None:
            raise RuntimeError("observer failure")
        before = get_usage_stats()["calls"]
        before_events = len(ROUTER_TEST_TRACKER.events)
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", return_value=client):
                self.assertEqual(llm.call("dm_main", [], observer=broken_observer), "stable")
        self.assertEqual(get_usage_stats()["calls"], before + 1)
        self.assertEqual(len(ROUTER_TEST_TRACKER.events), before_events + 1)
        self.assertEqual(client.options, {"max_retries": 0})
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", return_value=SequenceProviderClient([_response("done")])):
                with self.assertRaises(KeyboardInterrupt):
                    llm.call("dm_main", [], observer=lambda event, raw: (_ for _ in ()).throw(KeyboardInterrupt()))

    def test_constructor_failure_receipt_has_no_attempt_identity_or_usage(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm

        events = []
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", side_effect=RuntimeError("construct failed")):
                with self.assertRaisesRegex(RuntimeError, "construct failed"):
                    llm.call("dm_main", [], observer=lambda event, raw: events.append((event, raw)))
        self.assertEqual(len(events), 1)
        event, raw = events[0]
        self.assertEqual(event.kind, "constructor_error")
        self.assertIsNone(event.attempt_id)
        self.assertIsNone(event.attempt_number)
        self.assertIsNone(raw)
        self.assertEqual(event.error_type, "RuntimeError")
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["transport_attempts"]), (0, 0))
        self.assertEqual(stats["errors"], 1)

    def test_sdk_error_then_fallback_constructor_failure_has_distinct_receipts(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm

        primary = SequenceProviderClient([RuntimeError("timeout")])
        events = []
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, RuntimeError("private detail")]):
                with self.assertRaisesRegex(RuntimeError, "private detail"):
                    llm.call("dm_main", [], observer=lambda event, raw: events.append((event, raw)))
        self.assertEqual([event.kind for event, _ in events], ["transport_error", "constructor_error"])
        self.assertIsNone(events[0][1])
        self.assertEqual(events[0][0].attempt_number, 1)
        self.assertFalse(hasattr(events[0][0], "error"))
        self.assertIsNone(events[1][1])
        self.assertIsNone(events[1][0].attempt_id)
        self.assertIsNone(events[1][0].attempt_number)
        self.assertTrue(events[1][0].fallback)
        self.assertEqual(events[1][0].error_type, "RuntimeError")
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["transport_attempts"]), (0, 1))
        self.assertEqual((stats["errors"], stats["fallbacks"]), (2, 1))

    def test_disable_sdk_retries_failure_is_constructor_event_not_attempt(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import LLMRouter, get_usage_stats

        class BadOptionsClient:
            def with_options(self, **kwargs: Any) -> Any:
                raise RuntimeError("options failed")
        events = []
        with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
            with mock.patch.object(factory, "create_chat_client", return_value=BadOptionsClient()):
                with self.assertRaisesRegex(RuntimeError, "options failed"):
                    LLMRouter().call("dm_main", [], observer=lambda event, raw: events.append((event, raw)))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0].kind, "constructor_error")
        self.assertIsNone(events[0][0].attempt_id)
        self.assertIsNone(events[0][0].attempt_number)
        self.assertIsNone(events[0][1])
        self.assertEqual(get_usage_stats()["transport_attempts"], 0)

    def test_concurrent_calls_have_independent_call_and_attempt_ids(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        barrier = threading.Barrier(16)
        class ConcurrentClient:
            def __init__(self) -> None:
                self.chat = mock.Mock()
                def create(**kwargs: Any) -> Any:
                    barrier.wait(timeout=10)
                    return _response("parallel")
                self.chat.completions.create = create
            def with_options(self, **kwargs: Any) -> "ConcurrentClient":
                return self

        events = []
        events_lock = threading.Lock()
        callbacks_outside_lock = []
        def observe(event: Any, raw: Any) -> None:
            import utils.llm_router as router_module
            acquired = router_module._USAGE_LOCK.acquire(blocking=False)
            callbacks_outside_lock.append(acquired)
            if acquired:
                router_module._USAGE_LOCK.release()
            with events_lock:
                events.append(event)
        def run() -> None:
            self.assertEqual(llm.call("dm_main", [{"role": "user", "content": "parallel"}], observer=observe), "parallel")

        threads = [threading.Thread(target=run) for _ in range(16)]
        # Install shared patches once around the whole concurrent window. Patching
        # and unpatching from each worker races and could expose a real factory.
        with ProviderTripwire() as tripwire:
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False)):
                with mock.patch.object(factory, "create_chat_client", side_effect=lambda: ConcurrentClient()):
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
            tripwire.assert_untouched(self)
        self.assertEqual(len(events), 16)
        self.assertEqual(len({event.call_id for event in events}), 16)
        self.assertEqual(len({event.attempt_id for event in events}), 16)
        self.assertEqual({event.attempt_number for event in events}, {1})
        self.assertEqual(callbacks_outside_lock, [True] * 16)


class TestRouterEmptyResponseRecovery(unittest.TestCase):
    """Auto-default and explicit empty recovery with one shared fallback budget."""

    def setUp(self) -> None:
        from utils.llm_router import reset_usage_stats
        reset_usage_stats()

    @staticmethod
    def _fallback_status() -> Dict[str, Any]:
        return {
            "has_triggered": False,
            "primary_provider": "openrouter",
            "fallback_provider": "openai",
            "last_error": None,
            "fallback_count": 0,
            "notification_emitted": False,
        }

    def test_direct_default_is_off_and_explicit_auto_recovery_falls_back_once(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm

        empty = _response("")
        direct_empty = _response(None)
        default_client = SequenceProviderClient([direct_empty])
        primary = SequenceProviderClient([empty, _response(None), _response("")])
        fallback_response = _response("fallback success")
        fallback = SequenceProviderClient([fallback_response])
        receipts = []
        with ProviderTripwire():
            with mock.patch.object(factory, "_fallback_status", self._fallback_status()):
                with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openai", False), ("openrouter", True), ("openai", False)]):
                    with mock.patch.object(factory, "create_chat_client", side_effect=[default_client, primary, fallback]) as create:
                        self.assertIsNone(llm.call("dm_main", []))
                        self.assertEqual(llm.call(
                            "dm_main", [], empty_retry_limit=2,
                            observer=lambda event, raw: receipts.append((event, raw)),
                        ), "fallback success")
                self.assertIsNotNone(factory.get_fallback_notification())
                self.assertIsNone(factory.get_fallback_notification())

        self.assertEqual(len(default_client.calls), 1)
        self.assertEqual(len(primary.calls), 3)
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual(create.call_count, 3)
        opted_receipts = receipts
        self.assertEqual([event.kind for event, _ in opted_receipts], ["response"] * 4)
        self.assertEqual([event.fallback for event, _ in opted_receipts], [False, False, False, True])
        self.assertEqual([event.attempt_number for event, _ in opted_receipts], [1, 2, 3, 4])
        self.assertEqual(len({id(raw) for _, raw in opted_receipts}), 4)
        stats = get_usage_stats()
        self.assertEqual(stats["calls"], 5)
        self.assertEqual(stats["transport_attempts"], 5)
        self.assertEqual(stats["fallbacks"], 1)

    def test_auto_text_empty_response_retries_by_default_for_non_main_task(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm

        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"
        empty_response = _response(None)
        recovered_response = _response("summary recovered")
        primary = SequenceProviderClient([empty_response, recovered_response])
        receipts = []
        with ProviderTripwire():
            with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                    with mock.patch.object(factory, "create_chat_client", return_value=primary):
                        result = llm.call(
                            "summaries", [], observer=lambda event, raw: receipts.append((event, raw))
                        )

        self.assertEqual(result, "summary recovered")
        self.assertEqual(len(primary.calls), 2)
        self.assertEqual([event.kind for event, _ in receipts], ["response", "response"])
        self.assertEqual([event.attempt_number for event, _ in receipts], [1, 2])
        self.assertEqual([raw for _, raw in receipts], [empty_response, recovered_response])
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["transport_attempts"]), (2, 2))

    def test_auto_json_empty_response_retries_by_default(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"
        primary = SequenceProviderClient([_response(None), _response('{"ok": true}')])
        receipts = []
        with ProviderTripwire():
            with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                    with mock.patch.object(factory, "create_chat_client", return_value=primary):
                        result = llm.call(
                            "summaries",
                            [],
                            json_output=True,
                            observer=lambda event, raw: receipts.append((event, raw)),
                        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(primary.calls), 2)
        self.assertEqual([event.kind for event, _ in receipts], ["response", "response"])
        self.assertEqual([event.attempt_number for event, _ in receipts], [1, 2])

    def test_auto_empty_exhaustion_falls_back_once_and_fallback_can_succeed(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm

        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"
        primary_responses = [_response(None), _response(""), _response(None)]
        fallback_response = _response("fallback summary")
        primary = SequenceProviderClient(primary_responses)
        fallback = SequenceProviderClient([fallback_response])
        receipts = []
        with ProviderTripwire():
            with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_fallback_status", self._fallback_status()):
                    with mock.patch.object(
                        factory,
                        "_get_actual_provider",
                        side_effect=[("openrouter", True), ("openai", False)],
                    ):
                        with mock.patch.object(
                            factory, "create_chat_client", side_effect=[primary, fallback]
                        ) as create:
                            result = llm.call(
                                "summaries",
                                [],
                                observer=lambda event, raw: receipts.append((event, raw)),
                            )

        self.assertEqual(result, "fallback summary")
        self.assertEqual(create.call_count, 2)
        self.assertEqual(len(primary.calls), 3)
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual([event.kind for event, _ in receipts], ["response"] * 4)
        self.assertEqual([event.fallback for event, _ in receipts], [False] * 3 + [True])
        self.assertEqual([raw for _, raw in receipts], primary_responses + [fallback_response])
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["transport_attempts"]), (4, 4))
        self.assertEqual(stats["fallbacks"], 1)

    def test_auto_empty_exhaustion_on_both_providers_is_capped_at_six(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.provider_response_recovery import EmptyProviderResponseError
        from utils.llm_router import get_usage_stats, llm

        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"

        for json_output in (False, True):
            with self.subTest(json_output=json_output):
                self.setUp()
                primary_responses = [_response(None) for _ in range(3)]
                fallback_responses = [_response(None) for _ in range(3)]
                primary = SequenceProviderClient(primary_responses)
                fallback = SequenceProviderClient(fallback_responses)
                receipts = []
                with ProviderTripwire():
                    with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                        with mock.patch.object(factory, "_fallback_status", self._fallback_status()):
                            with mock.patch.object(
                                factory,
                                "_get_actual_provider",
                                side_effect=[("openrouter", True), ("openai", False)],
                            ):
                                with mock.patch.object(
                                    factory, "create_chat_client", side_effect=[primary, fallback]
                                ) as create:
                                    with self.assertRaises(EmptyProviderResponseError):
                                        llm.call(
                                            "summaries",
                                            [],
                                            json_output=json_output,
                                            observer=lambda event, raw: receipts.append((event, raw)),
                                        )

                invocation_count = len(primary.calls) + len(fallback.calls)
                self.assertEqual(invocation_count, 6)
                self.assertLessEqual(invocation_count, 6)
                self.assertEqual(create.call_count, 2)
                self.assertEqual(len(receipts), 6)
                self.assertEqual([event.kind for event, _ in receipts], ["response"] * 6)
                self.assertEqual([event.attempt_number for event, _ in receipts], list(range(1, 7)))
                self.assertEqual([event.fallback for event, _ in receipts], [False] * 3 + [True] * 3)
                stats = get_usage_stats()
                self.assertEqual((stats["calls"], stats["transport_attempts"]), (6, 6))
                self.assertEqual(stats["fallbacks"], 1)

    def test_explicit_empty_retry_limit_overrides_auto_default(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"
        primary = SequenceProviderClient([_response(None)])
        fallback = SequenceProviderClient([_response("explicit override fallback")])
        with ProviderTripwire():
            with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_fallback_status", self._fallback_status()):
                    with mock.patch.object(
                        factory,
                        "_get_actual_provider",
                        side_effect=[("openrouter", True), ("openai", False)],
                    ):
                        with mock.patch.object(
                            factory, "create_chat_client", side_effect=[primary, fallback]
                        ):
                            result = llm.call("dm_main", [], empty_retry_limit=0)

        self.assertEqual(result, "explicit override fallback")
        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(len(fallback.calls), 1)

    def test_auto_transport_fallback_resets_default_empty_response_bound(self) -> None:
        import model_config
        import utils.ai_client_factory as factory
        from utils.llm_router import get_usage_stats, llm

        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"
        primary_responses = [_response(None), RuntimeError("503")]
        fallback_responses = [
            _response(None),
            _response(""),
            _response("fallback recovered after transport error"),
        ]
        primary = SequenceProviderClient(primary_responses)
        fallback = SequenceProviderClient(fallback_responses)
        receipts = []
        with ProviderTripwire():
            with mock.patch.object(model_config, "MODEL_PROFILES", profiles):
                with mock.patch.object(factory, "_fallback_status", self._fallback_status()):
                    with mock.patch.object(
                        factory,
                        "_get_actual_provider",
                        side_effect=[("openrouter", True), ("openai", False)],
                    ):
                        with mock.patch.object(
                            factory, "create_chat_client", side_effect=[primary, fallback]
                        ) as create:
                            result = llm.call(
                                "summaries",
                                [],
                                observer=lambda event, raw: receipts.append((event, raw)),
                            )

        invocation_count = len(primary.calls) + len(fallback.calls)
        self.assertEqual(result, "fallback recovered after transport error")
        self.assertEqual(len(primary.calls), 2)
        self.assertEqual(len(fallback.calls), 3)
        self.assertLessEqual(invocation_count, 6)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(
            [event.kind for event, _ in receipts],
            ["response", "transport_error", "response", "response", "response"],
        )
        self.assertEqual(
            [event.fallback for event, _ in receipts],
            [False, False, True, True, True],
        )
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["transport_attempts"]), (4, 5))
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["fallbacks"], 1)

    def test_three_empty_responses_per_provider_exhaust_at_six_with_once_only_receipts(self) -> None:
        import utils.ai_client_factory as factory
        from utils.provider_response_recovery import EmptyProviderResponseError
        from utils.llm_router import get_usage_stats, llm

        primary_responses = [_response("") for _ in range(3)]
        fallback_responses = [_response(None) for _ in range(3)]
        primary = SequenceProviderClient(primary_responses)
        fallback = SequenceProviderClient(fallback_responses)
        receipts = []
        with mock.patch.object(factory, "_fallback_status", self._fallback_status()):
            with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
                with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]) as create:
                    with self.assertRaises(EmptyProviderResponseError):
                        llm.call(
                            "dm_main", [], empty_retry_limit=2,
                            observer=lambda event, raw: receipts.append((event, raw)),
                        )
            self.assertIsNotNone(factory.get_fallback_notification())
            self.assertIsNone(factory.get_fallback_notification())
        self.assertEqual(len(primary.calls), 3)
        self.assertEqual(len(fallback.calls), 3)
        self.assertEqual(len(primary.calls) + len(fallback.calls), 6)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(len(receipts), 6)
        self.assertEqual([event.kind for event, _ in receipts], ["response"] * 6)
        self.assertEqual([event.attempt_number for event, _ in receipts], [1, 2, 3, 4, 5, 6])
        self.assertEqual([event.fallback for event, _ in receipts], [False] * 3 + [True] * 3)
        self.assertEqual([raw for _, raw in receipts], primary_responses + fallback_responses)
        stats = get_usage_stats()
        self.assertEqual((stats["calls"], stats["transport_attempts"]), (6, 6))
        self.assertEqual(stats["fallbacks"], 1)

    def test_denied_factory_recovery_exhausts_preferred_without_fallback_client(self) -> None:
        import utils.ai_client_factory as factory
        from utils.provider_response_recovery import EmptyProviderResponseError
        from utils.llm_router import get_usage_stats, llm

        primary = SequenceProviderClient([_response("") for _ in range(3)])
        receipts = []
        denied = {"should_fallback": False, "fallback_message": None}
        with mock.patch.object(factory, "_fallback_status", self._fallback_status()):
            with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                with mock.patch.object(factory, "create_chat_client", return_value=primary) as create:
                    with mock.patch.object(factory, "handle_provider_error", return_value=denied) as recover:
                        with self.assertRaises(EmptyProviderResponseError) as raised:
                            llm.call(
                                "dm_main", [], empty_retry_limit=2,
                                observer=lambda event, raw: receipts.append((event, raw)),
                            )
        create.assert_called_once_with()
        recover.assert_called_once()
        error = recover.call_args.args[0]
        self.assertIsInstance(error, EmptyProviderResponseError)
        self.assertEqual(error.attempts, 3)
        self.assertEqual(recover.call_args.kwargs["context"], "dm_main")
        self.assertIsInstance(raised.exception, EmptyProviderResponseError)
        self.assertEqual(len(primary.calls), 3)
        self.assertEqual([event.kind for event, _ in receipts], ["response"] * 3)
        stats = get_usage_stats()
        self.assertEqual((stats["transport_attempts"], stats["calls"], stats["fallbacks"]), (3, 3, 0))

    def test_transport_and_constructor_failures_share_fallback_ceiling(self) -> None:
        import utils.ai_client_factory as factory
        from utils.provider_response_recovery import EmptyProviderResponseError
        from utils.llm_router import get_usage_stats, llm

        primary = SequenceProviderClient([_response(""), _response(""), RuntimeError("503")])
        fallback = SequenceProviderClient([_response(""), _response(""), _response("")])
        receipts = []
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]) as create:
                with self.assertRaises(EmptyProviderResponseError):
                    llm.call("dm_main", [], empty_retry_limit=2, observer=lambda event, raw: receipts.append((event, raw)))
        self.assertEqual(len(primary.calls), 3)
        self.assertEqual(len(primary.calls) + len(fallback.calls), 6)
        self.assertEqual(create.call_count, 2)
        self.assertEqual([event.kind for event, _ in receipts], ["response"] * 2 + ["transport_error"] + ["response"] * 3)
        self.assertEqual(sum(event.fallback for event, _ in receipts), 3)
        stats = get_usage_stats()
        self.assertEqual(stats["transport_attempts"], 6)
        self.assertEqual(stats["calls"], 5)
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["fallbacks"], 1)

        # A preferred constructor failure is pre-attempt and may consume only
        # the one fallback transition; fallback exhaustion remains bounded.
        self.setUp()
        fallback = SequenceProviderClient([_response("") for _ in range(3)])
        events = []
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[RuntimeError("503"), fallback]) as create:
                with self.assertRaises(EmptyProviderResponseError):
                    llm.call("dm_main", [], empty_retry_limit=2, observer=lambda event, raw: events.append((event, raw)))
        self.assertEqual(len(fallback.calls), 3)
        self.assertEqual(create.call_count, 2)
        self.assertEqual([event.kind for event, _ in events], ["constructor_error"] + ["response"] * 3)
        stats = get_usage_stats()
        self.assertEqual((stats["transport_attempts"], stats["calls"], stats["errors"]), (3, 3, 1))
        self.assertEqual(stats["fallbacks"], 1)

    def test_terminal_outcomes_stop_immediately_with_one_response_accounted(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMTerminalError, get_usage_stats, llm

        cases = [
            (_terminal_response("refusal"), None, "refusal"),
            (_terminal_response("content_filter"), None, "content_filter"),
            (None, RuntimeError("quota exceeded"), "quota"),
        ]
        for response, error, kind in cases:
            with self.subTest(kind=kind):
                self.setUp()
                primary = SequenceProviderClient([error if error is not None else response])
                receipts = []
                with mock.patch.object(factory, "_get_actual_provider", return_value=("openrouter", True)):
                    with mock.patch.object(factory, "create_chat_client", return_value=primary) as create:
                        with self.assertRaises(GameLLMTerminalError) as raised:
                            llm.call("dm_main", [], empty_retry_limit=2, observer=lambda event, raw: receipts.append((event, raw)))
                self.assertEqual(raised.exception.terminal_kind, kind)
                self.assertEqual(len(primary.calls), 1)
                create.assert_called_once_with()
                self.assertEqual(len(receipts), 1)
                self.assertEqual(receipts[0][0].kind, "transport_error" if error else "response")
                stats = get_usage_stats()
                self.assertEqual(stats["transport_attempts"], 1)
                self.assertEqual(stats["calls"], 0 if error else 1)

    def test_policy_validation_precedes_client_creation_and_forbids_json(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import LLMRouter

        invalid_values = (True, False, -1, 3, 1.0, float("nan"), float("inf"), "2")
        with mock.patch.object(factory, "_get_actual_provider", side_effect=AssertionError("provider resolved")):
            with mock.patch.object(factory, "create_chat_client", side_effect=AssertionError("client created")):
                for value in invalid_values:
                    with self.subTest(value=value):
                        with self.assertRaises(ValueError):
                            LLMRouter().call("dm_main", [], empty_retry_limit=value)
                with self.assertRaisesRegex(ValueError, "json_output"):
                    LLMRouter().call("dm_main", [], json_output=True, empty_retry_limit=2)
                with self.assertRaisesRegex(ValueError, "dm_main"):
                    LLMRouter().call("combat_main", [], empty_retry_limit=2)


class TestRouterDecideGate(unittest.TestCase):
    """Keep the deferred decisions primitive provider-free and production-isolated."""

    @staticmethod
    def _production_python_sources() -> Iterator[tuple[Path, str]]:
        tracked = subprocess.check_output(
            ["git", "ls-files", "--", "*.py"],
            cwd=REPO_ROOT,
            text=True,
        ).splitlines()
        excluded_files = {
            "utils/ai_client_factory.py",
            "utils/llm_router.py",
        }
        for relative in tracked:
            path = Path(relative)
            normalized = path.as_posix()
            if normalized in excluded_files:
                continue
            if path.parts and path.parts[0] in {"scripts", "openspec", "tmp"}:
                continue
            # Worktree is authoritative: skip tracked files deleted but not yet committed.
            if not (REPO_ROOT / path).is_file():
                continue
            yield path, (REPO_ROOT / path).read_text(encoding="utf-8")

    @staticmethod
    def _attribute_chain(node: ast.AST) -> List[str]:
        parts: List[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return list(reversed(parts))

    def test_decide_is_gated_without_client_or_usage_changes(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import GameLLMError, get_usage_stats, llm

        before = get_usage_stats()
        with ProviderTripwire() as tripwire:
            with mock.patch.object(
                factory,
                "create_chat_client",
                side_effect=AssertionError("decide must not create a client"),
            ) as create_client:
                with self.assertRaisesRegex(
                    GameLLMError,
                    r"status=unavailable.*pending decomposition gate",
                ):
                    llm.decide(
                        task="jev_decision",
                        state={"scene": "test"},
                        questions={"next": "?"},
                    )
                create_client.assert_not_called()
            tripwire.assert_untouched(self)
        self.assertEqual(get_usage_stats(), before)

    def test_production_sources_do_not_call_router_decide(self) -> None:
        violations: List[str] = []
        for path, source in self._production_python_sources():
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    chain = self._attribute_chain(node.func)
                    if len(chain) >= 2 and chain[-1] == "decide":
                        violations.append(f"{path}:{node.lineno}: {'.'.join(chain)}")

        self.assertEqual(violations, [], "production router decisions found: " + repr(violations))


class TestSyntheticBenchmarkHarness(unittest.TestCase):
    """Verify the default benchmark without weakening network tripwires."""

    def _load_harness(self) -> Any:
        return importlib.import_module("scripts.benchmark_model_profiles")

    def _stats_snapshot(self) -> Dict[str, Any]:
        import utils.llm_router as router_module

        with router_module._USAGE_LOCK:
            return copy.deepcopy(router_module._usage_stats)

    def test_default_harness_runs_all_candidates_without_provider_or_network(self) -> None:
        benchmark = self._load_harness()
        with ProviderTripwire() as tripwire:
            report = benchmark.build_report("production-auto")
            tripwire.assert_untouched(self)

        self.assertTrue(report["synthetic"])
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["api_key_read"], False)
        self.assertEqual(
            set(report["candidates"]),
            {"production-auto", "titan-auto", "openai/fallback"},
        )
        for candidate in report["candidates"].values():
            self.assertEqual(candidate["request_count"], 4)
            self.assertEqual(candidate["provider_client_constructors"], 0)

    def test_harness_emits_selected_tier_models_and_fixture_task_shapes(self) -> None:
        benchmark = self._load_harness()
        import model_config as config

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        profiles["titan-auto"]["complex"]["model"] = "synthetic/titan-complex"
        profiles["titan-auto"]["simple"]["model"] = "synthetic/titan-simple"
        with mock.patch.object(config, "MODEL_PROFILES", profiles):
            report = benchmark.build_report("titan-auto")

        titan = report["candidates"]["titan-auto"]
        self.assertEqual(
            titan["sdk_models"],
            [
                "synthetic/titan-complex",
                "synthetic/titan-simple",
                "synthetic/titan-simple",
                "synthetic/titan-simple",
            ],
        )
        self.assertEqual(titan["fixtures"][1]["task"], "combat_validation")
        self.assertEqual(
            report["candidates"]["openai/fallback"]["sdk_models"],
            [config.OPENAI_FALLBACK_MODEL] * 4,
        )

    def test_harness_restores_config_and_stats_on_success_and_exception(self) -> None:
        benchmark = self._load_harness()
        import model_config as config

        import utils.llm_router as router_module

        original_active = config.ACTIVE_PROFILE
        original_overrides = copy.deepcopy(config.TASK_OVERRIDES)
        with router_module._USAGE_LOCK:
            original_stats = copy.deepcopy(router_module._usage_stats)
            router_module._usage_stats["calls"] = 73
        expected_stats = copy.deepcopy(router_module._usage_stats)

        benchmark.build_report("titan-auto")
        self.assertEqual(config.ACTIVE_PROFILE, original_active)
        self.assertEqual(config.TASK_OVERRIDES, original_overrides)
        self.assertEqual(self._stats_snapshot(), expected_stats)

        with mock.patch.object(
            benchmark.SyntheticProviderClient,
            "create",
            side_effect=RuntimeError("synthetic harness failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic harness failure"):
                benchmark.build_report("production-auto")
        self.assertEqual(config.ACTIVE_PROFILE, original_active)
        self.assertEqual(config.TASK_OVERRIDES, original_overrides)
        self.assertEqual(self._stats_snapshot(), expected_stats)

    def test_harness_stdout_is_one_parseable_json_document(self) -> None:
        script = REPO_ROOT / "scripts" / "benchmark_model_profiles.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--profile", "production-auto"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        parsed = json.loads(completed.stdout)
        self.assertEqual(parsed["status"], "synthetic")
        self.assertEqual(parsed["candidates"]["production-auto"]["request_count"], 4)
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
