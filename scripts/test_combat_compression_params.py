# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Provider-free facade and factory-profile contract for combat compression."""

import builtins
import copy
import http.client
import importlib
import logging.handlers
import os
import socket
import sys
import unittest
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeFacade:
    def __init__(self, outcome):
        self.calls = []
        self.outcome = outcome

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _FakeProviderClient:
    def __init__(self, response):
        self.calls = []
        self.response = response
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create_completion)
        )

    def _create_completion(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return {"choices": [{"message": {"content": self.response}}]}

    def with_options(self, **_kwargs):
        return self


class CombatCompressionParamsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Arm network and filesystem tripwires before importing application or
        # SDK modules. Read access remains available for ordinary imports.
        cls._guarders = []
        for target in (
            "socket.socket",
            "socket.create_connection",
            "urllib.request.urlopen",
            "http.client.HTTPConnection.request",
            "http.client.HTTPSConnection.request",
            "http.client.HTTPConnection.connect",
            "http.client.HTTPSConnection.connect",
        ):
            patcher = mock.patch(target, side_effect=AssertionError("network tripwire"))
            patcher.start()
            cls._guarders.append(patcher)

        real_open = builtins.open

        def deny_write_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                raise AssertionError("filesystem write tripwire")
            return real_open(file, mode, *args, **kwargs)

        patcher = mock.patch("builtins.open", side_effect=deny_write_open)
        patcher.start()
        cls._guarders.append(patcher)
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        real_os_open = os.open

        def deny_os_write_open(path, flags, *args, **kwargs):
            if flags & write_flags:
                raise AssertionError("filesystem write tripwire")
            return real_os_open(path, flags, *args, **kwargs)

        patcher = mock.patch("os.open", side_effect=deny_os_write_open)
        patcher.start()
        cls._guarders.append(patcher)
        for method in ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "replace"):
            patcher = mock.patch.object(
                Path, method, side_effect=AssertionError("filesystem write tripwire")
            )
            patcher.start()
            cls._guarders.append(patcher)
        patcher = mock.patch.object(
            logging.handlers,
            "RotatingFileHandler",
            side_effect=lambda *args, **kwargs: logging.NullHandler(),
        )
        patcher.start()
        cls._guarders.append(patcher)

        openai = importlib.import_module("openai")
        cls._sdk_guard = mock.patch.object(
            openai, "OpenAI", side_effect=AssertionError("SDK constructor tripwire")
        )
        cls._sdk_guard.start()

        cls.engine = importlib.import_module("core.ai.combat_compression_engine")
        cls.factory = importlib.import_module("utils.ai_client_factory")
        cls.router = importlib.import_module("utils.llm_router")

    @classmethod
    def tearDownClass(cls):
        cls._sdk_guard.stop()
        for patcher in reversed(cls._guarders):
            patcher.stop()

    def _compress(self, outcome="@T=CS/v2\n@ROUND=1"):
        facade = _FakeFacade(outcome)
        original = "a combat input whose source text must remain unchanged"
        with mock.patch.object(self.engine, "USAGE_TRACKING_AVAILABLE", False), mock.patch.object(
            self.router.llm, "call", side_effect=facade
        ), mock.patch.object(
            self.factory,
            "create_chat_client",
            side_effect=AssertionError("combat compressor constructed a provider client"),
        ) as create_client, mock.patch("builtins.print"):
            compressor = self.engine.CombatCompressor(enable_caching=False)
            result = compressor.compress(original)
        create_client.assert_not_called()
        return original, result, facade.calls

    def _compress_with_router(self, *, provider="openai", config_overrides=None):
        import model_config

        client = _FakeProviderClient("@T=CS/v2\n@ROUND=1")
        original = "a combat input whose source text must remain unchanged"
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    self.factory,
                    "_get_actual_provider",
                    return_value=(provider, provider == "openrouter"),
                )
            )
            create_client = stack.enter_context(
                mock.patch.object(self.factory, "create_chat_client", return_value=client)
            )
            stack.enter_context(
                mock.patch.object(self.engine, "USAGE_TRACKING_AVAILABLE", False)
            )
            stack.enter_context(
                mock.patch.object(self.engine, "make_legacy_receipt_observer", return_value=None)
            )
            stack.enter_context(mock.patch("builtins.print"))
            for name, value in (config_overrides or {}).items():
                stack.enter_context(mock.patch.object(model_config, name, value))

            compressor = self.engine.CombatCompressor(enable_caching=False)
            result = compressor.compress(original)

        return original, result, client, create_client

    def test_luna_real_request_uses_low_profile_without_sampling_controls(self):
        original, result, client, create_client = self._compress_with_router()

        self.assertEqual(result, "@T=CS/v2\n@ROUND=1")
        self.assertEqual(len(client.calls), 1)
        request = client.calls[0]
        self.assertEqual(request["model"], "gpt-6-luna")
        self.assertEqual(request["reasoning_effort"], "low")
        self.assertEqual(request["verbosity"], "low")
        self.assertNotIn("temperature", request)
        self.assertNotIn("top_p", request)
        self.assertEqual(
            request["messages"],
            [
                {"role": "system", "content": self.engine.COMBAT_COMPRESSION_PROMPT},
                {"role": "user", "content": original},
            ],
        )
        create_client.assert_called_once_with()

    def test_legacy_gpt5_request_uses_legacy_sampling_omission_policy(self):
        with mock.patch.object(self.factory, "GPT5_INCLUDE_LEGACY_TEMPERATURE", False):
            original, result, client, create_client = self._compress_with_router(
                config_overrides={"OPENAI_FALLBACK_MODEL": "gpt-5.6-luna"}
            )

        self.assertEqual(result, "@T=CS/v2\n@ROUND=1")
        self.assertEqual(len(client.calls), 1)
        request = client.calls[0]
        self.assertEqual(request["model"], "gpt-5.6-luna")
        self.assertEqual(
            (request["reasoning_effort"], request["verbosity"]), ("low", "low")
        )
        self.assertNotIn("temperature", request)
        self.assertNotIn("top_p", request)
        self.assertEqual(request["messages"][1]["content"], original)
        create_client.assert_called_once_with()

    def test_nonreasoning_legacy_model_records_facade_temperature_policy(self):
        import model_config

        legacy_model = "gpt-4.1-2025-04-14"
        with mock.patch.object(
            model_config, "OPENAI_FALLBACK_MODEL", legacy_model
        ), mock.patch.object(
            self.factory, "_get_actual_provider", return_value=("openai", False)
        ):
            previous_factory_params = self.factory.get_chat_completion_params(
                "compression", legacy_model
            )

        original, result, client, create_client = self._compress_with_router(
            config_overrides={"OPENAI_FALLBACK_MODEL": legacy_model}
        )

        self.assertEqual(result, "@T=CS/v2\n@ROUND=1")
        self.assertEqual(len(client.calls), 1)
        request = client.calls[0]
        self.assertEqual(request["model"], legacy_model)
        self.assertEqual(previous_factory_params["temperature"], 0.3)
        self.assertEqual(request["temperature"], 0.3)
        self.assertEqual(request["top_p"], 1.0)
        self.assertNotIn("reasoning_effort", request)
        self.assertNotIn("verbosity", request)
        self.assertEqual(request["messages"][1]["content"], original)
        create_client.assert_called_once_with()

    def test_openrouter_profile_uses_factory_envelope_without_gpt_only_fields(self):
        import model_config

        profile_name = "g6-compression-openrouter-test"
        profile_tier = {
            "model": "openrouter/auto",
            "params": {
                "temperature": 0.3,
                "thinking": {"type": "disabled"},
                "plugins": [{"id": "cache-control"}],
            },
            "provider": {"order": ["vendor-a"]},
            "price_per_1k": {},
        }
        profiles = copy.deepcopy(model_config.MODEL_PROFILES)
        profiles[profile_name] = {
            "complex": copy.deepcopy(profile_tier),
            "simple": copy.deepcopy(profile_tier),
        }
        overrides = copy.deepcopy(model_config.TASK_OVERRIDES)
        overrides["compression"] = {"profile": profile_name}

        original, result, client, create_client = self._compress_with_router(
            provider="openrouter",
            config_overrides={"MODEL_PROFILES": profiles, "TASK_OVERRIDES": overrides},
        )

        self.assertEqual(result, "@T=CS/v2\n@ROUND=1")
        self.assertEqual(len(client.calls), 1)
        request = client.calls[0]
        self.assertEqual(request["model"], "openrouter/auto")
        self.assertEqual(request["temperature"], 0.3)
        self.assertEqual(
            request["extra_body"],
            {
                "provider": {"order": ["vendor-a"]},
                "thinking": {"type": "disabled"},
                "plugins": [{"id": "cache-control"}],
            },
        )
        self.assertEqual(request["top_p"], 1.0)
        for key in ("reasoning_effort", "verbosity"):
            self.assertNotIn(key, request)
        self.assertEqual(request["messages"][1]["content"], original)
        create_client.assert_called_once_with()

    def test_facade_request_uses_compression_profile_without_caller_sampling_controls(self):
        import model_config

        original, result, calls = self._compress()
        self.assertEqual(result, "@T=CS/v2\n@ROUND=1")
        self.assertEqual(len(calls), 1)
        request = calls[0]
        self.assertEqual(request["task"], "compression")
        self.assertIs(request["json_output"], False)
        self.assertEqual(
            request["messages"],
            [
                {"role": "system", "content": self.engine.COMBAT_COMPRESSION_PROMPT},
                {"role": "user", "content": original},
            ],
        )
        self.assertFalse(
            {"model", "temperature", "top_p", "client", "timeout"}.intersection(request)
        )
        profile = self.router.llm.resolve_profile("compression")
        self.assertEqual(profile["provider_name"], "openrouter")
        self.assertEqual(profile["model"], "openrouter/auto")
        finalized = self.router.llm._request_kwargs(
            profile,
            request["messages"],
            auto_router_cost_tier=self.router.llm._auto_router_task_cost_tier("compression"),
            json_output=False,
            temperature=None,
            max_tokens=None,
            retry_tier=None,
            json_contract=False,
            extra_kwargs={},
        )
        self.assertEqual(finalized["model"], "openrouter/auto")
        self.assertNotIn("reasoning_effort", finalized)
        self.assertNotIn("verbosity", finalized)
        self.assertEqual(finalized["temperature"], 0.3)
        self.assertEqual(finalized["top_p"], 1.0)

    def test_error_returns_original_after_exactly_one_facade_attempt(self):
        original, result, calls = self._compress(RuntimeError("simulated API rejection"))
        self.assertEqual(result, original)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["task"], "compression")
        self.assertIs(calls[0]["json_output"], False)
        self.assertEqual(calls[0]["messages"][1]["content"], original)
        self.assertFalse(
            {"model", "temperature", "top_p", "client", "timeout"}.intersection(calls[0])
        )


if __name__ == "__main__":
    unittest.main()
