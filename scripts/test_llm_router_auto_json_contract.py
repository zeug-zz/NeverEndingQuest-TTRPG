# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free tests for per-call Auto JSON-contract signaling."""

import contextlib
import copy
import inspect
import sys
import unittest
from pathlib import Path
from typing import Any, Iterator, List, Sequence, Tuple
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.test_llm_router import ProviderTripwire, SequenceProviderClient


def _response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class TestAutoJsonContract(unittest.TestCase):
    """Signal JSON mode only for eligible Auto attempts, without parsing content."""

    @contextlib.contextmanager
    def _configured_router(
        self,
        providers: Sequence[Tuple[str, bool]],
        clients: Sequence[Any],
    ) -> Iterator[Tuple[Any, Any]]:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"
            profiles["production-auto"][tier]["params"] = {}
        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        overrides["dm_main"] = {"profile": "production-auto"}

        with contextlib.ExitStack() as stack:
            stack.enter_context(ProviderTripwire())
            stack.enter_context(mock.patch.object(config, "ACTIVE_PROFILE", "production-auto"))
            stack.enter_context(mock.patch.object(config, "MODEL_PROFILES", profiles))
            stack.enter_context(mock.patch.object(config, "TASK_OVERRIDES", overrides))
            stack.enter_context(
                mock.patch.object(factory, "_get_actual_provider", side_effect=list(providers))
            )
            create_client = stack.enter_context(
                mock.patch.object(factory, "create_chat_client", side_effect=list(clients))
            )
            yield llm, create_client

    def test_json_contract_is_keyword_only_and_defaults_false(self) -> None:
        from utils.llm_router import llm

        parameter = inspect.signature(llm.call).parameters["json_contract"]
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, False)

    def test_auto_json_contract_requests_json_mode_and_returns_raw_text(self) -> None:
        client = SequenceProviderClient([_response("not valid JSON, returned untouched")])
        with self._configured_router([("openrouter", True)], [client]) as (llm, _create):
            result = llm.call("dm_main", [], json_contract=True)

        self.assertEqual(result, "not valid JSON, returned untouched")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["model"], "openrouter/auto")
        self.assertEqual(client.calls[0]["response_format"], {"type": "json_object"})

    def test_auto_json_contract_preserves_provider_and_plugin_sdk_fields(self) -> None:
        import model_config as config

        provider_preferences = {"order": ["preferred-provider"], "allow_fallbacks": False}
        profile_plugin = {"id": "auto-router", "cost_tier": "high"}
        caller_plugin = {"id": "caller-plugin"}
        client = SequenceProviderClient([_response("{}")])
        with self._configured_router([("openrouter", True)], [client]) as (llm, _create):
            for tier in ("complex", "simple"):
                tier_profile = config.MODEL_PROFILES["production-auto"][tier]
                tier_profile["provider"] = copy.deepcopy(provider_preferences)
                tier_profile["params"]["plugins"] = [copy.deepcopy(profile_plugin)]

            llm.call("dm_main", [], json_contract=True, plugins=[caller_plugin])

        request = client.calls[0]
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["extra_body"]["provider"], provider_preferences)
        self.assertEqual(len(request["extra_body"]["plugins"]), 2)
        self.assertIn(profile_plugin, request["extra_body"]["plugins"])
        self.assertIn(caller_plugin, request["extra_body"]["plugins"])

    def test_direct_openai_json_contract_does_not_add_response_format(self) -> None:
        client = SequenceProviderClient([_response("direct text")])
        with self._configured_router([("openai", False)], [client]) as (llm, _create):
            result = llm.call("dm_main", [], json_contract=True)

        self.assertEqual(result, "direct text")
        self.assertEqual(client.calls[0]["model"], "gpt-6-luna")
        self.assertNotIn("response_format", client.calls[0])

    def test_unmarked_auto_request_does_not_add_response_format(self) -> None:
        client = SequenceProviderClient([_response("plain text")])
        with self._configured_router([("openrouter", True)], [client]) as (llm, _create):
            result = llm.call("dm_main", [])

        self.assertEqual(result, "plain text")
        self.assertNotIn("response_format", client.calls[0])

    def test_caller_supplied_response_format_is_preserved(self) -> None:
        caller_format = {
            "type": "json_schema",
            "json_schema": {"name": "caller_contract", "schema": {"type": "object"}},
        }
        client = SequenceProviderClient([_response("{}")])
        with self._configured_router([("openrouter", True)], [client]) as (llm, _create):
            llm.call("dm_main", [], json_contract=True, response_format=caller_format)

        self.assertEqual(client.calls[0]["response_format"], caller_format)

    def test_auto_to_direct_fallback_does_not_carry_router_added_json_mode(self) -> None:
        import model_config as config

        provider_preferences = {"order": ["auto-only-provider"], "allow_fallbacks": False}
        auto_plugin = {"id": "auto-router", "cost_tier": "high"}
        primary = SequenceProviderClient([RuntimeError("503 service unavailable")])
        fallback = SequenceProviderClient([_response("fallback text")])
        with self._configured_router(
            [("openrouter", True), ("openai", False)], [primary, fallback]
        ) as (llm, create_client):
            for tier in ("complex", "simple"):
                tier_profile = config.MODEL_PROFILES["production-auto"][tier]
                tier_profile["provider"] = copy.deepcopy(provider_preferences)
                tier_profile["params"]["plugins"] = [copy.deepcopy(auto_plugin)]

            result = llm.call("dm_main", [], json_contract=True)

        self.assertEqual(result, "fallback text")
        self.assertEqual(primary.calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(primary.calls[0]["extra_body"]["provider"], provider_preferences)
        self.assertIn(auto_plugin, primary.calls[0]["extra_body"]["plugins"])
        self.assertNotIn("response_format", fallback.calls[0])
        self.assertNotIn("extra_body", fallback.calls[0])
        self.assertNotIn("provider", fallback.calls[0])
        self.assertNotIn("plugins", fallback.calls[0])
        self.assertEqual(create_client.call_args_list[1], mock.call(use_fallback=True))

    def test_non_boolean_signal_is_rejected_before_provider_construction(self) -> None:
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        with ProviderTripwire(), mock.patch.object(factory, "create_chat_client") as create_client:
            for invalid_value in (1, "true", None):
                with self.subTest(invalid_value=invalid_value):
                    with self.assertRaisesRegex(TypeError, "json_contract must be a bool"):
                        llm.call("dm_main", [], json_contract=invalid_value)

        create_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
