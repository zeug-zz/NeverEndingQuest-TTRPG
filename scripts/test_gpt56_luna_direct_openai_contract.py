# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
GPT-5.6 Luna direct-OpenAI contract coverage.

Provider-free contract tests for the direct-OpenAI gpt-5.6-luna model swap:

- OpenRouter isolation: OPENROUTER_CHAT_MODEL / OPENROUTER_FULL_MODEL /
  OPENROUTER_MINI_MODEL keep their existing values (no Luna ID substituted
  into the OpenRouter path); the OpenRouter branch of
  get_chat_completion_params() retains the existing flat shape (model +
  task temperature + flattened `thinking` extra-body payload) with NO
  direct-OpenAI reasoning_effort/verbosity substitution.
- Task-2.4-edited call sites (updates/update_encounter.py,
  updates/plot_update.py) use the shared helper and do not reintroduce the
  old get_model_config request construction.
- Direct OpenAI model selection: every active GPT-5 runtime role constant
  and get_chat_model_name() resolve to the exact model ID gpt-5.6-luna,
  and no active role selects gpt-5.4-mini-2026-03-17.
- GPT-5-family parameter compatibility: dm_main and combat_main get medium
  reasoning + medium verbosity; validation, dm_validation,
  action_prediction, updates, and compression stay low reasoning + low
  verbosity; retry_tier="high" (and "retry") escalates reasoning to high
  while preserving the task verbosity.
- Legacy sampling omission: temperature and top_p are absent by default,
  temperature_override is not applied on the GPT-5 branch, and
  GPT5_INCLUDE_LEGACY_TEMPERATURE defaults to False.
- Display identity: get_model_display_name() returns "GPT-5.6 Luna" and the
  display mapping covers both gpt-5.6-luna and openai/gpt-5.6-luna.

All assertions are provider-free source/contract checks. No live API calls.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import utils.ai_client_factory as ai_client_factory


def _read(relative_path: str) -> str:
    with open(os.path.join(REPO_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


class TestOpenRouterConstantsUnchanged(unittest.TestCase):
    """OpenRouter model IDs must keep their existing values after the swap."""

    def test_openrouter_chat_model_unchanged(self) -> None:
        import model_config

        self.assertEqual(model_config.OPENROUTER_CHAT_MODEL, "moonshotai/kimi-k2.5")

    def test_openrouter_full_model_unchanged(self) -> None:
        import model_config

        self.assertEqual(model_config.OPENROUTER_FULL_MODEL, "moonshotai/kimi-k2.5")

    def test_openrouter_mini_model_unchanged(self) -> None:
        import model_config

        self.assertEqual(model_config.OPENROUTER_MINI_MODEL, "google/gemini-2.0-flash-exp")

    def test_no_luna_id_substituted_into_openrouter_constants(self) -> None:
        import model_config

        openrouter_ids = {
            model_config.OPENROUTER_CHAT_MODEL,
            model_config.OPENROUTER_FULL_MODEL,
            model_config.OPENROUTER_MINI_MODEL,
        }
        self.assertNotIn("gpt-5.6-luna", openrouter_ids)
        self.assertFalse(any("gpt-5.6-luna" in str(m) for m in openrouter_ids))


class TestOpenRouterBranchFlatShape(unittest.TestCase):
    """OpenRouter branch of the shared helper keeps model + temperature + `thinking`."""

    def setUp(self) -> None:
        self._actual_provider = ai_client_factory._get_actual_provider
        ai_client_factory._get_actual_provider = lambda use_fallback=False: ("openrouter", True)

    def tearDown(self) -> None:
        ai_client_factory._get_actual_provider = self._actual_provider

    def test_encounter_update_openrouter_flat_shape_preserved(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "encounter_update",
            "gpt-5.6-luna",
            temperature_override=0.7,
        )

        self.assertEqual(
            params,
            {
                "model": "moonshotai/kimi-k2.5",
                "temperature": 0.7,
                "thinking": {"type": "disabled"},
            },
        )

    def test_plot_update_openrouter_flat_shape_preserved(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "plot_update",
            "gpt-5.6-luna",
            temperature_override=0.7,
        )

        self.assertEqual(
            params,
            {
                "model": "moonshotai/kimi-k2.5",
                "temperature": 0.7,
                "thinking": {"type": "disabled"},
            },
        )

    def test_thinking_enabled_task_keeps_enabled_payload(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main",
            "gpt-5.6-luna",
            temperature_override=0.7,
        )

        self.assertEqual(
            params,
            {
                "model": "moonshotai/kimi-k2.5",
                "temperature": 0.7,
                "thinking": {"type": "enabled"},
            },
        )

    def test_openrouter_branch_has_no_direct_openai_substitution(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "combat_main",
            "gpt-5.6-luna",
            temperature_override=0.7,
        )

        self.assertNotIn("reasoning_effort", params)
        self.assertNotIn("verbosity", params)
        self.assertIn("thinking", params)
        self.assertEqual(params["model"], "moonshotai/kimi-k2.5")

    def test_openrouter_branch_respects_temperature_override(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "encounter_update",
            "gpt-5.6-luna",
            temperature_override=0.3,
        )

        self.assertEqual(params["temperature"], 0.3)


class TestEditedCallsiteHelperRouting(unittest.TestCase):
    """Task-2.4 edited call sites stay on the shared helper, no get_model_config."""

    @classmethod
    def setUpClass(cls):
        cls.encounter_source = _read("updates/update_encounter.py")
        cls.plot_source = _read("updates/plot_update.py")

    def test_update_encounter_uses_shared_helper(self) -> None:
        self.assertIn("get_chat_completion_params", self.encounter_source)
        self.assertIn("**get_chat_completion_params(", self.encounter_source)
        self.assertIn("temperature_override=TEMPERATURE", self.encounter_source)

    def test_update_encounter_no_get_model_config_request_construction(self) -> None:
        self.assertNotIn("get_model_config", self.encounter_source)
        self.assertNotIn('model=config["model"]', self.encounter_source)
        self.assertNotIn('**config.get("extra_body", {})', self.encounter_source)

    def test_plot_update_uses_shared_helper(self) -> None:
        self.assertIn("get_chat_completion_params", self.plot_source)
        self.assertIn("**get_chat_completion_params(", self.plot_source)
        self.assertIn("temperature_override=TEMPERATURE", self.plot_source)

    def test_plot_update_no_get_model_config_request_construction(self) -> None:
        self.assertNotIn("get_model_config", self.plot_source)
        self.assertNotIn('model=config["model"]', self.plot_source)
        self.assertNotIn('**config.get("extra_body", {})', self.plot_source)


# Active direct-OpenAI GPT-5 runtime role constants in model_config.py.
# Every role that previously selected GPT-5.4 Mini must now resolve to
# gpt-5.6-luna, and no active selector branch may silently fall back to
# gpt-5.4-mini-2026-03-17.
_ACTIVE_GPT5_ROLE_NAMES = (
    "DM_MAIN_MODEL",
    "DM_SUMMARIZATION_MODEL",
    "DM_VALIDATION_MODEL",
    "ACTION_PREDICTION_MODEL",
    "COMBAT_MAIN_MODEL",
    "COMBAT_DIALOGUE_SUMMARY_MODEL",
    "NPC_BUILDER_MODEL",
    "ADVENTURE_SUMMARY_MODEL",
    "CHARACTER_VALIDATOR_MODEL",
    "PLOT_UPDATE_MODEL",
    "PLAYER_INFO_UPDATE_MODEL",
    "NPC_INFO_UPDATE_MODEL",
    "MONSTER_BUILDER_MODEL",
    "ENCOUNTER_UPDATE_MODEL",
    "LEVEL_UP_MODEL",
    "TRANSITION_VALIDATOR_MODEL",
    "DM_MINI_MODEL",
    "DM_FULL_MODEL",
    "GPT5_MINI_MODEL",
    "GPT5_FULL_MODEL",
    "NARRATIVE_COMPRESSION_MODEL",
    "LOCATION_COMPRESSION_MODEL",
)


class TestDirectOpenAIModelSelection(unittest.TestCase):
    """Every active direct-OpenAI GPT-5 runtime role resolves to gpt-5.6-luna."""

    def test_active_gpt5_role_constants_select_luna(self) -> None:
        import model_config

        for role_name in _ACTIVE_GPT5_ROLE_NAMES:
            self.assertEqual(
                getattr(model_config, role_name),
                "gpt-5.6-luna",
                msg=f"role {role_name} must select gpt-5.6-luna",
            )

    def test_no_active_gpt5_role_selects_gpt54_mini(self) -> None:
        import model_config

        for role_name in _ACTIVE_GPT5_ROLE_NAMES:
            self.assertNotIn(
                "gpt-5.4-mini",
                str(getattr(model_config, role_name)),
                msg=f"role {role_name} must not select gpt-5.4-mini-2026-03-17",
            )

    def test_get_chat_model_name_selects_luna(self) -> None:
        self.assertEqual(ai_client_factory.get_chat_model_name(), "gpt-5.6-luna")

    def test_luna_is_recognized_as_gpt5_family(self) -> None:
        self.assertTrue(ai_client_factory._is_gpt5_model("gpt-5.6-luna"))


class TestDirectOpenAIMediumNarratorCombatProfile(unittest.TestCase):
    """Main narration and combat tasks use medium reasoning and verbosity."""

    def test_dm_main_medium_reasoning_medium_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params("dm_main", "gpt-5.6-luna")
        self.assertEqual(params["model"], "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")

    def test_combat_main_medium_reasoning_medium_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params("combat_main", "gpt-5.6-luna")
        self.assertEqual(params["model"], "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")

    def test_medium_profile_flows_from_configured_model_constant(self) -> None:
        import model_config

        params = ai_client_factory.get_chat_completion_params("dm_main", model_config.DM_MAIN_MODEL)
        self.assertEqual(params["model"], "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "medium")
        self.assertEqual(params["verbosity"], "medium")


class TestDirectOpenAILowEffortProfiles(unittest.TestCase):
    """Validation, action prediction, updates, and compression stay low/low."""

    def test_validation_low_reasoning_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params("validation", "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "low")
        self.assertEqual(params["verbosity"], "low")

    def test_dm_validation_low_reasoning_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params("dm_validation", "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "low")
        self.assertEqual(params["verbosity"], "low")

    def test_action_prediction_low_reasoning_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params("action_prediction", "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "low")
        self.assertEqual(params["verbosity"], "low")

    def test_updates_low_reasoning_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params("updates", "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "low")
        self.assertEqual(params["verbosity"], "low")

    def test_compression_low_reasoning_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params("compression", "gpt-5.6-luna")
        self.assertEqual(params["reasoning_effort"], "low")
        self.assertEqual(params["verbosity"], "low")


class TestDirectOpenAIRetryEscalation(unittest.TestCase):
    """High retry tier escalates reasoning while preserving task verbosity."""

    def test_dm_main_high_retry_keeps_medium_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main", "gpt-5.6-luna", retry_tier="high"
        )
        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["verbosity"], "medium")

    def test_combat_main_high_retry_keeps_medium_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "combat_main", "gpt-5.6-luna", retry_tier="high"
        )
        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["verbosity"], "medium")

    def test_validation_high_retry_keeps_low_verbosity(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "validation", "gpt-5.6-luna", retry_tier="high"
        )
        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["verbosity"], "low")

    def test_retry_alias_escalates_reasoning(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main", "gpt-5.6-luna", retry_tier="retry"
        )
        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["verbosity"], "medium")


class TestLunaDisplayIdentity(unittest.TestCase):
    """Human-readable model identity identifies GPT-5.6 Luna."""

    def test_get_model_display_name_identifies_luna(self) -> None:
        self.assertEqual(ai_client_factory.get_model_display_name(), "GPT-5.6 Luna")

    def test_display_name_maps_luna_when_chat_model_forced(self) -> None:
        original = ai_client_factory.get_chat_model_name
        ai_client_factory.get_chat_model_name = lambda: "gpt-5.6-luna"
        try:
            self.assertEqual(ai_client_factory.get_model_display_name(), "GPT-5.6 Luna")
        finally:
            ai_client_factory.get_chat_model_name = original

    def test_display_mapping_contains_both_luna_id_forms(self) -> None:
        source = _read("utils/ai_client_factory.py")
        self.assertIn('"gpt-5.6-luna": "GPT-5.6 Luna"', source)
        self.assertIn('"openai/gpt-5.6-luna": "GPT-5.6 Luna"', source)


class TestLunaLegacySamplingOmission(unittest.TestCase):
    """GPT-5.6 Luna requests omit legacy temperature/top_p by default."""

    def test_dm_main_omits_temperature_and_top_p_by_default(self) -> None:
        params = ai_client_factory.get_chat_completion_params("dm_main", "gpt-5.6-luna")
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_combat_main_omits_temperature_and_top_p_by_default(self) -> None:
        params = ai_client_factory.get_chat_completion_params("combat_main", "gpt-5.6-luna")
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_validation_omits_temperature_and_top_p_by_default(self) -> None:
        params = ai_client_factory.get_chat_completion_params("validation", "gpt-5.6-luna")
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_high_retry_request_omits_temperature_and_top_p(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main", "gpt-5.6-luna", retry_tier="high"
        )
        self.assertNotIn("temperature", params)
        self.assertNotIn("top_p", params)

    def test_temperature_override_not_applied_on_gpt5_branch(self) -> None:
        params = ai_client_factory.get_chat_completion_params(
            "dm_main", "gpt-5.6-luna", temperature_override=0.7
        )
        self.assertNotIn("temperature", params)

    def test_legacy_temperature_flag_defaults_to_off(self) -> None:
        self.assertFalse(ai_client_factory.GPT5_INCLUDE_LEGACY_TEMPERATURE)

    def test_gpt5_profile_shape_contains_only_expected_keys(self) -> None:
        params = ai_client_factory.get_chat_completion_params("dm_main", "gpt-5.6-luna")
        self.assertEqual(set(params.keys()), {"model", "reasoning_effort", "verbosity"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
