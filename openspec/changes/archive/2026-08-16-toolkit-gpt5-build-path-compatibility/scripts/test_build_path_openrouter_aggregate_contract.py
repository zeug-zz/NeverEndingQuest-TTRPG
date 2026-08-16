# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Aggregate OpenRouter build-path contract suite (change:
toolkit-gpt5-build-path-compatibility, task 4.2).

Task 4.2: add OpenRouter regression assertions for model IDs,
thinking/request fields, and compatible temperature behavior; verify no
OpenRouter request-shape regression.

This suite walks the SAME full migrated build path matrix as the task 4.1
aggregate suite (``test_build_path_gpt5_aggregate_contract.py``) -- Homebrew
normalizer N1-N5, ModuleBuilder B1-B3, generators G1-G10, spatial S1,
classification C1, included toolkit/publication-adjacent A1/A2/A4/A7/A9, and
Markdown M1-M3 -- and, for every exercised OpenRouter branch, asserts the
FINAL request kwargs (recording mock through
``fixtures/build_request_fixture.py``):

- the configured OpenRouter model id for the site's task/model source is
  preserved (resolved via ``get_model_config`` under the OpenRouter
  provider, the single parameter authority);
- the provider-specific thinking/request fields from ``get_model_config``
  (``extra_body`` / ``thinking`` shape) are preserved verbatim;
- compatible temperature behavior: the recorded temperature override wins
  when the site declares one, and the model_config task temperature is used
  otherwise;
- GPT-5-only ``reasoning_effort``/``verbosity`` and legacy ``top_p`` are
  never emitted on the OpenRouter branch;
- the exact final key set equals helper params + messages + declared
  preserved fields (no stray sampling keys);
- task identity stays stable across direct OpenAI and OpenRouter branches:
  the same task id drives both, and the OpenRouter model differs from the
  direct-OpenAI models (no cross-branch model or profile leak).

A dedicated no-change baseline pins the current OpenRouter model id and
thinking-toggle request shape so any future model assignment or request-shape
drift fails loudly.

The matrix is imported from the task 4.1 aggregate suite (single source of
truth anchored to ``reports/build_path_call_site_inventory.md``), so the two
aggregate suites cannot drift apart. The shared parameter helper
(``utils/ai_client_factory``) remains the only routing authority; this suite
adds no second routing implementation and changes no model assignments.

Provider-free: no live API, no credentials, no raw source persistence, no
runtime artifact mutation. Production call sites are not imported or invoked.
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
_SCRIPTS_DIR = os.path.join(_CHANGE_DIR, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
_FIXTURES_DIR = os.path.join(_CHANGE_DIR, "fixtures")
if _FIXTURES_DIR not in sys.path:
    sys.path.insert(0, _FIXTURES_DIR)

import build_request_fixture as bf
import model_config
import utils.ai_client_factory as ai_client_factory

# Reuse the task 4.1 matrix verbatim: every row is anchored to
# reports/build_path_call_site_inventory.md by the 4.1 suite. Importing the
# module only defines the matrix and helpers (no tests run on import).
from test_build_path_gpt5_aggregate_contract import (  # noqa: E402
    BUILD_SITES,
    _declared_preserved_kwargs,
    _site_anchor,
)

# A9's model source is the factory model-name resolver, not a fixed constant
# (inventory section 2, scripts/run_critical_narrative_repair.py:54).
A9_ANCHOR = "scripts/run_critical_narrative_repair.py:54"

# Model source per inventoried site: the exact constant/expression each
# migrated call site passes to the shared helper as its original OpenAI
# model (inventory sections 1.1-1.6 and section 2). The helper resolves the
# OpenRouter model id from the task id via get_model_config, and the tests
# pass these real constants so the simulation mirrors production exactly.
MODEL_SOURCE_BY_ANCHOR = {
    # Homebrew normalizer N1-N5 (task id builders).
    "utils/toolkit_homebrew_normalizer.py:476": model_config.DM_MAIN_MODEL,
    "utils/toolkit_homebrew_normalizer.py:553": model_config.DM_MAIN_MODEL,
    "utils/toolkit_homebrew_normalizer.py:644": model_config.DM_MAIN_MODEL,
    "utils/toolkit_homebrew_normalizer.py:764": model_config.DM_MAIN_MODEL,
    "utils/toolkit_homebrew_normalizer.py:905": model_config.DM_MAIN_MODEL,
    # ModuleBuilder B1-B3.
    "core/generators/module_builder.py:693": model_config.DM_MAIN_MODEL,
    "core/generators/module_builder.py:957": model_config.DM_MAIN_MODEL,
    "core/generators/module_builder.py:1463": model_config.DM_SUMMARIZATION_MODEL,
    # ModuleBuilder generators G1-G10.
    "core/generators/module_generator.py:526": model_config.DM_MAIN_MODEL,
    "core/generators/area_generator.py:180": model_config.DM_MAIN_MODEL,
    "core/generators/area_generator.py:546": model_config.DM_MAIN_MODEL,
    "core/generators/area_generator.py:731": model_config.DM_MAIN_MODEL,
    "core/generators/plot_generator.py:349": model_config.DM_MAIN_MODEL,
    "core/generators/plot_generator.py:468": model_config.DM_MAIN_MODEL,
    "core/generators/location_generator.py:461": model_config.DM_MAIN_MODEL,
    "core/generators/location_generator.py:607": model_config.DM_MAIN_MODEL,
    "core/generators/npc_builder.py:123": model_config.NPC_BUILDER_MODEL,
    "core/generators/monster_builder.py:249": model_config.MONSTER_BUILDER_MODEL,
    # Spatial and classification toolkit calls.
    "utils/spatial_contract.py:671": model_config.DM_VALIDATION_MODEL,
    "web/extensions/toolkit_llm_classification.py:211": model_config.DM_VALIDATION_MODEL,
    # Markdown / publication-adjacent calls M1-M3 (task id summaries).
    "utils/homebrewery_adventure_writer.py:343": model_config.DM_SUMMARIZATION_MODEL,
    "utils/homebrewery_adventure_writer.py:430": model_config.DM_SUMMARIZATION_MODEL,
    "utils/homebrewery_adventure_writer.py:670": model_config.DM_SUMMARIZATION_MODEL,
    # Included toolkit/publication-adjacent calls (inventory section 2).
    "core/generators/module_stitcher.py:451": model_config.DM_SUMMARIZATION_MODEL,
    "core/generators/module_stitcher.py:1136": model_config.DM_SUMMARIZATION_MODEL,
    "web/web_interface.py:5827": model_config.NPC_BUILDER_MODEL,
    "utils/npc_reconciler.py:71": model_config.DM_MINI_MODEL,
}


def _model_source_for(site) -> str:
    """The exact model source the inventoried call site passes to the helper."""
    anchor = _site_anchor(site)
    if anchor == A9_ANCHOR:
        return ai_client_factory.get_chat_model_name()
    return MODEL_SOURCE_BY_ANCHOR[anchor]


def _expected_openrouter_config(site) -> dict:
    """get_model_config resolution under the OpenRouter provider (authority)."""
    with bf.forced_provider("openrouter", True):
        return ai_client_factory.get_model_config(site.task_id, _model_source_for(site))


def _capture_openrouter(site) -> bf.CapturedRequest:
    """Simulate the migrated call site under OpenRouter with its declared fields."""
    return bf.capture_openrouter_build_request(
        task_id=site.task_id,
        model=_model_source_for(site),
        temperature_override=site.temperature_override,
        **_declared_preserved_kwargs(site),
    )


class TestOpenRouterAggregateBranch(unittest.TestCase):
    """Every migrated build-path site: OpenRouter request shape preserved."""

    def test_every_site_preserves_configured_openrouter_model_id(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                kwargs = _capture_openrouter(site).create_kwargs
                expected = _expected_openrouter_config(site)
                self.assertEqual(
                    kwargs["model"],
                    expected["model"],
                    "%s must keep the configured OpenRouter model id" % site.label,
                )
                # No direct-OpenAI model id may leak into an OpenRouter request.
                self.assertNotEqual(kwargs["model"], bf.GPT5_DIRECT_MODEL, site.label)
                self.assertNotEqual(
                    kwargs["model"], bf.NON_GPT5_DIRECT_MODEL, site.label
                )

    def test_every_site_preserves_provider_thinking_and_request_fields(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                kwargs = _capture_openrouter(site).create_kwargs
                expected = _expected_openrouter_config(site)
                provider_fields = expected.get("extra_body") or {}
                self.assertTrue(
                    provider_fields,
                    "OpenRouter config for %s must carry provider request fields"
                    % site.label,
                )
                for key, value in provider_fields.items():
                    self.assertEqual(
                        kwargs.get(key),
                        value,
                        "%s: OpenRouter request field %s must be preserved"
                        % (site.label, key),
                    )

    def test_every_site_preserves_recorded_temperature_override(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                kwargs = _capture_openrouter(site).create_kwargs
                # OpenRouter supports temperature: the site's recorded
                # creative intent must win (helper override), unlike the
                # direct GPT-5 branch where it is omitted entirely.
                self.assertEqual(
                    kwargs["temperature"],
                    site.temperature_override,
                    site.label,
                )

    def test_every_site_omits_gpt5_only_and_legacy_sampling_fields(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                kwargs = _capture_openrouter(site).create_kwargs
                self.assertNotIn("reasoning_effort", kwargs, site.label)
                self.assertNotIn("verbosity", kwargs, site.label)
                self.assertNotIn("top_p", kwargs, site.label)
                self.assertEqual(kwargs["messages"], bf.DEFAULT_MESSAGES, site.label)

    def test_every_site_exact_final_key_set(self) -> None:
        # Final kwargs = helper params (model + temperature + provider
        # request fields) + messages + the site's declared preserved fields.
        # No stray sampling keys may exist.
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                captured = _capture_openrouter(site)
                expected_keys = set(captured.params.keys())
                expected_keys.add("messages")
                expected_keys.update(_declared_preserved_kwargs(site).keys())
                self.assertEqual(
                    set(captured.create_kwargs.keys()),
                    expected_keys,
                    site.label,
                )
                self.assertNotIn("top_p", captured.create_kwargs, site.label)

    def test_json_mode_and_token_timeout_bounds_survive_openrouter(self) -> None:
        for site in BUILD_SITES:
            if (
                not site.json_mode
                and site.max_completion_tokens is None
                and site.max_tokens is None
                and site.timeout is None
            ):
                continue
            with self.subTest(site=site.label):
                kwargs = _capture_openrouter(site).create_kwargs
                if site.json_mode:
                    self.assertEqual(
                        kwargs["response_format"], {"type": "json_object"}
                    )
                if site.max_completion_tokens is not None:
                    self.assertEqual(
                        kwargs["max_completion_tokens"], site.max_completion_tokens
                    )
                if site.max_tokens is not None:
                    self.assertEqual(kwargs["max_tokens"], site.max_tokens)
                if site.timeout is not None:
                    self.assertEqual(kwargs["timeout"], site.timeout)


class TestOpenRouterTaskIdentityAndNoChangeBaseline(unittest.TestCase):
    """Task identity is stable across branches; current shape is pinned."""

    def test_task_identity_stable_across_direct_and_openrouter_branches(self) -> None:
        # The same task id drives both branches; only provider-supported
        # fields differ (GPT-5 profile on direct, thinking fields on
        # OpenRouter) and each branch keeps its own model id.
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                gpt5_kwargs = bf.capture_gpt5_build_request(
                    task_id=site.task_id
                ).create_kwargs
                router_kwargs = _capture_openrouter(site).create_kwargs
                self.assertEqual(gpt5_kwargs["model"], bf.GPT5_DIRECT_MODEL, site.label)
                self.assertIn("reasoning_effort", gpt5_kwargs, site.label)
                self.assertNotIn("reasoning_effort", router_kwargs, site.label)
                self.assertNotIn("verbosity", router_kwargs, site.label)
                self.assertNotEqual(
                    router_kwargs["model"],
                    gpt5_kwargs["model"],
                    "%s: OpenRouter model must not switch to the direct model"
                    % site.label,
                )

    def test_openrouter_model_ids_are_unchanged(self) -> None:
        # No-change baseline: the current configured OpenRouter model id and
        # strategy are pinned so a future assignment change fails loudly.
        self.assertEqual(
            model_config.OPENROUTER_CHAT_MODEL,
            "moonshotai/kimi-k2.5",
            "OpenRouter chat model id must not change",
        )
        self.assertEqual(
            model_config.OPENROUTER_STRATEGY,
            "kimi_thinking",
            "OpenRouter strategy must not change",
        )
        # Every site resolves the configured OpenRouter chat model id (the
        # task override table is empty in the current configuration).
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                self.assertEqual(
                    _expected_openrouter_config(site)["model"],
                    model_config.OPENROUTER_CHAT_MODEL,
                    site.label,
                )

    @unittest.skipUnless(
        model_config.OPENROUTER_STRATEGY == "kimi_thinking",
        "thinking-toggle request shape is kimi_thinking-specific",
    )
    def test_thinking_shape_follows_configured_task_list(self) -> None:
        # The current request shape toggles thinking from the configured
        # THINKING_ENABLED_TASKS list: enabled for listed tasks, disabled
        # otherwise. Pinned per site so drift fails loudly.
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                kwargs = _capture_openrouter(site).create_kwargs
                expected_type = (
                    "enabled"
                    if site.task_id in model_config.THINKING_ENABLED_TASKS
                    else "disabled"
                )
                self.assertEqual(
                    kwargs["thinking"],
                    {"type": expected_type},
                    site.label,
                )

    def test_temperature_default_falls_back_to_configured_task_temperature(self) -> None:
        # Without an override the OpenRouter branch keeps the model_config
        # task temperature (compatible default behavior).
        for task_id, model in (
            ("builders", model_config.DM_MAIN_MODEL),
            ("dm_validation", model_config.DM_VALIDATION_MODEL),
            ("npc_builder", model_config.NPC_BUILDER_MODEL),
            ("monster_builder", model_config.MONSTER_BUILDER_MODEL),
            ("summaries", model_config.DM_SUMMARIZATION_MODEL),
            ("unify_plots", model_config.DM_MAIN_MODEL),
        ):
            with self.subTest(task_id=task_id):
                captured = bf.capture_openrouter_build_request(
                    task_id=task_id, model=model
                )
                with bf.forced_provider("openrouter", True):
                    expected_temperature = ai_client_factory.get_model_config(
                        task_id, model
                    )["temperature"]
                self.assertEqual(
                    captured.create_kwargs["temperature"], expected_temperature
                )


class TestOpenRouterAggregateMatrixCoverage(unittest.TestCase):
    """The aggregate OpenRouter matrix covers the full build path inventory."""

    def test_matrix_covers_every_priority_and_included_site(self) -> None:
        # 23 priority sites (N1-N5, B1-B3, G1-G10, S1, C1, M1-M3) plus the
        # five included adjacent sites (A1, A2, A4, A7, A9), matching the
        # task 4.1 aggregate suite.
        self.assertEqual(len(BUILD_SITES), 28)
        anchors = [_site_anchor(s) for s in BUILD_SITES]
        self.assertEqual(len(anchors), len(set(anchors)))

    def test_every_site_has_a_model_source_and_temperature_intent(self) -> None:
        covered_anchors = set(MODEL_SOURCE_BY_ANCHOR.keys()) | {A9_ANCHOR}
        site_anchors = {_site_anchor(s) for s in BUILD_SITES}
        self.assertEqual(covered_anchors, site_anchors)
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                self.assertIsNotNone(_model_source_for(site), site.label)
                self.assertIsNotNone(
                    site.temperature_override,
                    "%s must declare its temperature intent" % site.label,
                )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
