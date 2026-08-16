# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider-free request-branch contract suite (change:
toolkit-gpt5-build-path-compatibility, task 1.2).

Verifies the build-path request fixtures in
``fixtures/build_request_fixture.py`` capture the FINAL kwargs passed to a
mock ``client.chat.completions.create`` for all three provider branches of
the shared parameter helper:

- Direct GPT-5 family (gpt-5.6-luna): the captured request contains the
  task-resolved reasoning_effort/verbosity profile and omits unsupported
  legacy temperature/top_p (temperature_override is not applied).
- Compatible non-GPT-5 (gpt-4.1-2025-04-14): the captured request preserves
  caller sampling behavior (temperature_override and task temperature) with
  no GPT-5 profile keys.
- OpenRouter: the captured request keeps the configured model, the
  provider-specific thinking/request fields from get_model_config, and
  compatible temperature behavior, with no GPT-5 profile substitution.

Also verifies determinism and reusability of the fixtures: repeated captures
are identical, the mock client records every create call, provider forcing
is restored after capture, and the captured kwargs equal the resolved helper
params spread into the create call plus messages/extra kwargs.

Provider-free: no live API, no credentials, no raw source persistence.
"""

from __future__ import annotations

import os
import sys
import unittest

def _find_repo_root():
    candidate = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(candidate, "openspec")) and os.path.isfile(
            os.path.join(candidate, "config_template.py")
        ):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            raise RuntimeError("Unable to locate NeverEndingQuest repository root")
        candidate = parent


_REPO_ROOT = _find_repo_root()
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_CHANGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES_DIR = os.path.join(_CHANGE_DIR, "fixtures")
if _FIXTURES_DIR not in sys.path:
    sys.path.insert(0, _FIXTURES_DIR)

import build_request_fixture as bf
import utils.ai_client_factory as ai_client_factory

# Representative build-path task ids from reports/build_path_call_site_inventory.md.
_INVENTORY_TASK_IDS = [
    "builders",              # N1-N5 normalizer
    "unify_plots",           # B1
    "update_plot_hooks",     # B2
    "parse_module_params",   # B3
    "module_generator",      # G1
    "generate_thematic_names",  # G2
    "generate_area_name",    # G3
    "generate_area_description",  # G4
    "plot_generator",        # G5/G6
    "location_generator",    # G7
    "location_generator_batch",  # G8
    "npc_builder",           # G9
    "monster_builder",       # G10
    "dm_validation",         # S1/C1
    "summaries",             # M1-M3 target profile
]


class TestDirectGPT5RequestFixture(unittest.TestCase):
    """Direct GPT-5 build requests carry the task profile and omit legacy sampling."""

    def test_builder_task_captures_medium_profile(self) -> None:
        captured = bf.capture_gpt5_build_request("builders")
        kwargs = captured.create_kwargs
        self.assertEqual(kwargs["model"], bf.GPT5_DIRECT_MODEL)
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertEqual(kwargs["verbosity"], "medium")
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)
        self.assertEqual(kwargs["messages"], bf.DEFAULT_MESSAGES)
        self.assertEqual(
            set(kwargs.keys()),
            {"model", "reasoning_effort", "verbosity", "messages"},
        )

    def test_generator_task_captures_medium_profile(self) -> None:
        kwargs = bf.capture_gpt5_build_request("module_generator").create_kwargs
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertEqual(kwargs["verbosity"], "medium")

    def test_validation_task_captures_low_profile(self) -> None:
        kwargs = bf.capture_gpt5_build_request("dm_validation").create_kwargs
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["verbosity"], "low")

    def test_summary_task_captures_low_medium_profile(self) -> None:
        kwargs = bf.capture_gpt5_build_request("adventure_summary").create_kwargs
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["verbosity"], "medium")

    def test_profile_matches_task_resolver_for_every_inventory_task(self) -> None:
        for task_id in _INVENTORY_TASK_IDS:
            with self.subTest(task_id=task_id):
                kwargs = bf.capture_gpt5_build_request(task_id).create_kwargs
                expected = ai_client_factory._resolve_gpt5_chat_profile(task_id)
                for key, value in expected.items():
                    self.assertEqual(kwargs[key], value)

    def test_temperature_override_not_applied_on_gpt5_branch(self) -> None:
        captured = bf.capture_gpt5_build_request(
            "builders", temperature_override=0.7
        )
        self.assertNotIn("temperature", captured.create_kwargs)
        self.assertNotIn("top_p", captured.create_kwargs)

    def test_retry_tier_high_escalates_reasoning_preserves_verbosity(self) -> None:
        kwargs = bf.capture_gpt5_build_request(
            "builders", retry_tier="high"
        ).create_kwargs
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertEqual(kwargs["verbosity"], "medium")
        self.assertNotIn("temperature", kwargs)

    def test_extra_create_kwargs_survive_alongside_helper_params(self) -> None:
        captured = bf.capture_gpt5_build_request(
            "builders", max_completion_tokens=500
        )
        self.assertEqual(captured.create_kwargs["max_completion_tokens"], 500)


class TestCompatibleNonGPT5RequestFixture(unittest.TestCase):
    """Non-GPT-5 direct requests preserve caller sampling behavior."""

    def test_preserves_caller_sampling_override(self) -> None:
        captured = bf.capture_non_gpt5_build_request(
            "builders", temperature_override=0.42
        )
        kwargs = captured.create_kwargs
        self.assertEqual(kwargs["model"], bf.NON_GPT5_DIRECT_MODEL)
        self.assertEqual(kwargs["temperature"], 0.42)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("verbosity", kwargs)

    def test_uses_task_temperature_without_override(self) -> None:
        captured = bf.capture_non_gpt5_build_request("builders")
        expected = ai_client_factory.get_model_config(
            "builders", bf.NON_GPT5_DIRECT_MODEL
        )["temperature"]
        self.assertEqual(captured.create_kwargs["temperature"], expected)

    def test_model_preserved_for_any_task(self) -> None:
        for task_id in _INVENTORY_TASK_IDS[:5]:
            with self.subTest(task_id=task_id):
                captured = bf.capture_non_gpt5_build_request(task_id)
                self.assertEqual(
                    captured.create_kwargs["model"], bf.NON_GPT5_DIRECT_MODEL
                )
                self.assertNotIn("reasoning_effort", captured.create_kwargs)


class TestOpenRouterRequestFixture(unittest.TestCase):
    """OpenRouter requests keep configured model, thinking fields, and temperature."""

    @staticmethod
    def _expected_config(task_id: str, model: str) -> dict:
        with bf.forced_provider("openrouter", True):
            return ai_client_factory.get_model_config(task_id, model)

    def test_configured_model_preserved(self) -> None:
        captured = bf.capture_openrouter_build_request("builders")
        expected = self._expected_config("builders", bf.GPT5_DIRECT_MODEL)
        self.assertEqual(captured.create_kwargs["model"], expected["model"])

    def test_provider_thinking_fields_preserved_for_builders(self) -> None:
        captured = bf.capture_openrouter_build_request("builders")
        expected = self._expected_config("builders", bf.GPT5_DIRECT_MODEL)
        for key, value in (expected.get("extra_body") or {}).items():
            self.assertEqual(
                captured.create_kwargs.get(key),
                value,
                "OpenRouter extra_body field %s must be preserved" % key,
            )

    def test_provider_thinking_fields_preserved_for_thinking_task(self) -> None:
        captured = bf.capture_openrouter_build_request("npc_builder")
        expected = self._expected_config("npc_builder", bf.GPT5_DIRECT_MODEL)
        for key, value in (expected.get("extra_body") or {}).items():
            self.assertEqual(
                captured.create_kwargs.get(key),
                value,
                "OpenRouter extra_body field %s must be preserved" % key,
            )

    def test_temperature_override_respected(self) -> None:
        captured = bf.capture_openrouter_build_request(
            "builders", temperature_override=0.3
        )
        self.assertEqual(captured.create_kwargs["temperature"], 0.3)

    def test_default_temperature_matches_config(self) -> None:
        captured = bf.capture_openrouter_build_request("builders")
        expected = self._expected_config("builders", bf.GPT5_DIRECT_MODEL)
        self.assertEqual(captured.create_kwargs["temperature"], expected["temperature"])

    def test_no_gpt5_profile_substitution_on_openrouter_branch(self) -> None:
        captured = bf.capture_openrouter_build_request("builders")
        self.assertNotIn("reasoning_effort", captured.create_kwargs)
        self.assertNotIn("verbosity", captured.create_kwargs)


class TestFixtureCaptureAndReusability(unittest.TestCase):
    """The fixtures are deterministic, complete, and reusable."""

    def test_create_kwargs_are_the_final_request(self) -> None:
        captured = bf.capture_gpt5_build_request(
            "builders", max_completion_tokens=800
        )
        expected = dict(captured.params)
        expected["messages"] = bf.DEFAULT_MESSAGES
        expected["max_completion_tokens"] = 800
        self.assertEqual(captured.create_kwargs, expected)

    def test_repeat_capture_is_deterministic(self) -> None:
        first = bf.capture_gpt5_build_request("builders")
        second = bf.capture_gpt5_build_request("builders")
        self.assertEqual(first.params, second.params)
        self.assertEqual(first.create_kwargs, second.create_kwargs)
        self.assertEqual(first.create_call_keys(), second.create_call_keys())

    def test_recording_client_accumulates_every_call(self) -> None:
        client = bf.RecordingClient()
        client.chat.completions.create(model="a", messages=bf.DEFAULT_MESSAGES)
        client.chat.completions.create(model="b", messages=bf.DEFAULT_MESSAGES)
        self.assertEqual(client.chat.completions.call_count, 2)
        self.assertEqual(client.calls[0]["model"], "a")
        self.assertEqual(client.calls[1]["model"], "b")
        self.assertEqual(client.last_call["model"], "b")

    def test_provider_forcing_restored_after_capture(self) -> None:
        original = ai_client_factory._get_actual_provider
        try:
            bf.capture_openrouter_build_request("builders")
            bf.capture_gpt5_build_request("builders")
            self.assertIs(ai_client_factory._get_actual_provider, original)
        finally:
            ai_client_factory._get_actual_provider = original

    def test_fixture_reusable_across_tasks_and_branches(self) -> None:
        gpt5 = bf.capture_gpt5_build_request("unify_plots").create_kwargs
        legacy = bf.capture_non_gpt5_build_request("unify_plots").create_kwargs
        router = bf.capture_openrouter_build_request("unify_plots").create_kwargs
        self.assertIn("reasoning_effort", gpt5)
        self.assertNotIn("reasoning_effort", legacy)
        self.assertNotIn("reasoning_effort", router)
        self.assertEqual(gpt5["model"], bf.GPT5_DIRECT_MODEL)
        self.assertEqual(legacy["model"], bf.NON_GPT5_DIRECT_MODEL)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
