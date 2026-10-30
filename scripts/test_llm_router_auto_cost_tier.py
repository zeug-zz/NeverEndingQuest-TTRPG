# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for task-specific OpenRouter Auto cost tiers."""

from __future__ import annotations

import contextlib
import copy
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, Iterator, List, Sequence, Tuple
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.test_llm_router import ProviderTripwire, SequenceProviderClient


def _response(content: str) -> Dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


class TestAutoRouterCostTier(unittest.TestCase):
    """Use fake clients to verify Auto-only tier policy and request merging."""

    @contextlib.contextmanager
    def _configured_router(
        self,
        providers: Sequence[Tuple[str, bool]],
        clients: Sequence[Any],
        *,
        cost_tiers: Dict[str, Any] | None = None,
        profile_plugins: List[Dict[str, Any]] | None = None,
    ) -> Iterator[Tuple[Any, Any, Any]]:
        import model_config as config
        import utils.ai_client_factory as factory
        from utils.llm_router import llm

        profiles = copy.deepcopy(config.MODEL_PROFILES)
        for tier in ("complex", "simple"):
            profiles["production-auto"][tier]["model"] = "openrouter/auto"
            profiles["production-auto"][tier]["params"] = {}
        if profile_plugins is not None:
            profiles["production-auto"]["complex"]["params"]["plugins"] = copy.deepcopy(
                profile_plugins
            )
            profiles["production-auto"]["simple"]["params"]["plugins"] = copy.deepcopy(
                profile_plugins
            )
        overrides = copy.deepcopy(config.TASK_OVERRIDES)
        tiers = copy.deepcopy(
            config.AUTO_ROUTER_TASK_COST_TIERS if cost_tiers is None else cost_tiers
        )

        with contextlib.ExitStack() as stack:
            stack.enter_context(ProviderTripwire())
            stack.enter_context(mock.patch.object(config, "ACTIVE_PROFILE", "production-auto"))
            stack.enter_context(mock.patch.object(config, "MODEL_PROFILES", profiles))
            stack.enter_context(mock.patch.object(config, "TASK_OVERRIDES", overrides))
            stack.enter_context(mock.patch.object(config, "AUTO_ROUTER_TASK_COST_TIERS", tiers))
            get_provider = stack.enter_context(
                mock.patch.object(factory, "_get_actual_provider", side_effect=list(providers))
            )
            create_client = stack.enter_context(
                mock.patch.object(factory, "create_chat_client", side_effect=list(clients))
            )
            yield llm, get_provider, create_client

    @staticmethod
    def _plugins(client: SequenceProviderClient) -> List[Dict[str, Any]]:
        return client.calls[0].get("extra_body", {}).get("plugins", [])

    def test_configured_validator_auto_request_has_one_medium_plugin(self) -> None:
        client = SequenceProviderClient([_response("validator response")])
        with self._configured_router([("openrouter", True)], [client]) as (llm, _provider, _create):
            self.assertEqual(llm.call("dm_validation", []), "validator response")

        auto_plugins = [plugin for plugin in self._plugins(client) if plugin.get("id") == "auto-router"]
        self.assertEqual(auto_plugins, [{"id": "auto-router", "cost_tier": "medium"}])

    def test_other_non_validator_auto_request_keeps_implicit_default(self) -> None:
        client = SequenceProviderClient([_response("narration")])
        with self._configured_router([("openrouter", True)], [client]) as (llm, _provider, _create):
            self.assertEqual(llm.call("action_prediction", []), "narration")

        self.assertFalse(
            [plugin for plugin in self._plugins(client) if plugin.get("id") == "auto-router"]
        )

    def test_dm_main_auto_uses_medium_for_both_json_contract_modes(self) -> None:
        for json_contract in (False, True):
            with self.subTest(json_contract=json_contract):
                client = SequenceProviderClient([_response("narration")])
                with self._configured_router(
                    [("openrouter", True)], [client]
                ) as (llm, _provider, _create):
                    self.assertEqual(
                        llm.call("dm_main", [], json_contract=json_contract),
                        "narration",
                    )

                self.assertEqual(
                    client.calls[0]["model"], "openrouter/auto"
                )
                self.assertEqual(
                    [plugin for plugin in self._plugins(client) if plugin.get("id") == "auto-router"],
                    [{"id": "auto-router", "cost_tier": "medium"}],
                )

    def test_dm_main_direct_primary_has_no_auto_router_plugin(self) -> None:
        client = SequenceProviderClient([_response("direct narration")])
        with self._configured_router([("openai", False)], [client]) as (llm, _provider, _create):
            self.assertEqual(llm.call("dm_main", [], json_contract=True), "direct narration")

        self.assertNotIn("plugins", client.calls[0].get("extra_body", {}))

    def test_dm_main_fallback_has_no_auto_router_plugin(self) -> None:
        primary = SequenceProviderClient([RuntimeError("503 service unavailable")])
        fallback = SequenceProviderClient([_response("direct fallback")])
        with self._configured_router(
            [("openrouter", True), ("openai", False)], [primary, fallback]
        ) as (llm, _provider, _create):
            self.assertEqual(llm.call("dm_main", [], json_contract=True), "direct fallback")

        self.assertEqual(
            [plugin for plugin in self._plugins(primary) if plugin.get("id") == "auto-router"],
            [{"id": "auto-router", "cost_tier": "medium"}],
        )
        self.assertNotIn("plugins", fallback.calls[0].get("extra_body", {}))

    def test_validator_fallback_to_direct_openai_has_no_plugin(self) -> None:
        primary = SequenceProviderClient([RuntimeError("503 service unavailable")])
        fallback = SequenceProviderClient([_response("direct fallback")])
        with self._configured_router(
            [("openrouter", True), ("openai", False)], [primary, fallback]
        ) as (llm, _provider, _create):
            self.assertEqual(llm.call("dm_validation", []), "direct fallback")

        self.assertEqual(
            [plugin for plugin in self._plugins(primary) if plugin.get("id") == "auto-router"],
            [{"id": "auto-router", "cost_tier": "medium"}],
        )
        self.assertNotIn("plugins", fallback.calls[0].get("extra_body", {}))

    def test_invalid_configured_tier_fails_before_client_or_provider_resolution(self) -> None:
        with self._configured_router(
            [("openrouter", True)],
            [SequenceProviderClient([_response("unused")])],
            cost_tiers={"dm_validation": "ultra"},
        ) as (llm, get_provider, create_client):
            with self.assertRaisesRegex(ValueError, "invalid Auto Router cost tier"):
                llm.call("dm_validation", [])

        get_provider.assert_not_called()
        create_client.assert_not_called()

    def test_profile_and_request_plugins_merge_with_one_generated_entry(self) -> None:
        client = SequenceProviderClient([_response("validator response")])
        profile_plugins = [{"id": "profile-plugin"}]
        request_plugins = [{"id": "request-plugin"}]
        with self._configured_router(
            [("openrouter", True)], [client], profile_plugins=profile_plugins
        ) as (llm, _provider, _create):
            llm.call("dm_validation", [], plugins=request_plugins)

        plugins = self._plugins(client)
        self.assertEqual(
            plugins,
            profile_plugins
            + request_plugins
            + [{"id": "auto-router", "cost_tier": "medium"}],
        )

    def test_caller_auto_router_plugin_is_preserved_without_generated_duplicate(self) -> None:
        client = SequenceProviderClient([_response("validator response")])
        caller_plugin = {"id": "auto-router", "cost_tier": "high"}
        with self._configured_router([("openrouter", True)], [client]) as (llm, _provider, _create):
            llm.call("dm_validation", [], plugins=[{"id": "request-plugin"}, caller_plugin])

        plugins = self._plugins(client)
        self.assertEqual(
            [plugin for plugin in plugins if plugin.get("id") == "auto-router"],
            [caller_plugin],
        )

    def test_configured_tier_inventory_contains_only_response_validator_tasks(self) -> None:
        import model_config

        expected = {
            "dm_validation",
            "combat_validation",
            "validation",
            "character_validator",
            "safety_review",
            "toolkit_adaptation_semantic_auditor",
        }
        self.assertEqual(set(model_config.AUTO_ROUTER_TASK_COST_TIERS), expected | {"dm_main"})
        self.assertEqual(set(model_config.AUTO_ROUTER_TASK_COST_TIERS.values()), {"medium"})


if __name__ == "__main__":
    unittest.main()
