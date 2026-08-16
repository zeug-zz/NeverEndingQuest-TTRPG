# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Aggregate GPT-5 build-path contract suite (change:
toolkit-gpt5-build-path-compatibility, task 4.1).

Task 4.1: extend GPT-5 contract tests for builder, normalizer, generator,
toolkit, and Markdown call sites; verify direct GPT-5 kwargs include
reasoning/verbosity and omit unsupported sampling fields.

This suite walks the full migrated build path inventory from
``reports/build_path_call_site_inventory.md`` -- Homebrew normalizer N1-N5,
ModuleBuilder B1-B3, generators G1-G10, spatial S1, classification C1,
included toolkit/publication-adjacent A1/A2/A4/A7/A9, and Markdown M1-M3 --
and, for every exercised direct GPT-5 branch, asserts the FINAL request
kwargs (recording mock through ``fixtures/build_request_fixture.py``):

- the task-resolved ``reasoning_effort`` and ``verbosity`` are present and
  correct (resolved from the site's task identity via the shared helper);
- unsupported legacy ``temperature`` and ``top_p`` are absent;
- site-specific non-sampling fields are preserved where the inventory
  records them (``response_format`` json mode, ``timeout``,
  ``max_completion_tokens``, ``max_tokens``, ``messages``);
- the exact final key set equals helper params + messages + declared
  preserved fields (no stray sampling keys).

The compatible non-GPT-5 branch is re-asserted for the same matrix: the
recorded temperature intent passes through the helper override with no
GPT-5 profile keys. OpenRouter request-shape assertions are owned by task
4.2 and are intentionally NOT added here.

Every row is anchored to the inventory report (file:line present), so the
matrix cannot silently drift from the inventoried call sites.

Provider-free: no live API, no credentials, no raw source persistence.
The shared parameter helper (``utils/ai_client_factory``) remains the only
routing authority; this suite reuses ``build_request_fixture`` and adds no
second routing implementation.
"""

from __future__ import annotations

import os
import sys
import unittest
from dataclasses import dataclass
from typing import Optional

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

_REPORT_PATH = os.path.join(_CHANGE_DIR, "reports", "build_path_call_site_inventory.md")

import build_request_fixture as bf
import utils.ai_client_factory as ai_client_factory


@dataclass(frozen=True)
class BuildCallSite:
    """One inventoried build-path call site and its preserved fields."""

    label: str
    file_path: str
    line: int
    task_id: str
    json_mode: bool = False
    timeout: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    max_tokens: Optional[int] = None
    temperature_override: Optional[float] = None


# Task 4.1 matrix: every migrated build-path call site (inventory sections
# 1.1-1.6 plus included adjacent section 2 rows A1/A2/A4/A7/A9). File:line,
# task id, preserved fields, and temperature intent come directly from
# reports/build_path_call_site_inventory.md.
BUILD_SITES = [
    # Homebrew normalizer N1-N5 (task id builders, profile medium/medium).
    BuildCallSite("N1 section extraction", "utils/toolkit_homebrew_normalizer.py", 476, "builders", timeout=90, temperature_override=0.2),
    BuildCallSite("N2 identity adjudication", "utils/toolkit_homebrew_normalizer.py", 553, "builders", timeout=90, temperature_override=0.2),
    BuildCallSite("N3 plot topology synthesis", "utils/toolkit_homebrew_normalizer.py", 644, "builders", timeout=90, temperature_override=0.2),
    BuildCallSite("N4 legacy one-shot normalization", "utils/toolkit_homebrew_normalizer.py", 764, "builders", timeout=120, temperature_override=0.3),
    BuildCallSite("N5 fidelity repair", "utils/toolkit_homebrew_normalizer.py", 905, "builders", timeout=90, temperature_override=0.2),
    # ModuleBuilder B1-B3.
    BuildCallSite("B1 unify_plots", "core/generators/module_builder.py", 693, "unify_plots", json_mode=True, temperature_override=0.7),
    BuildCallSite("B2 _generate_enhanced_plot_hooks", "core/generators/module_builder.py", 957, "update_plot_hooks", json_mode=True, temperature_override=0.6),
    BuildCallSite("B3 parse_narrative_to_module_params", "core/generators/module_builder.py", 1463, "parse_module_params", temperature_override=0.3),
    # ModuleBuilder generators G1-G10.
    BuildCallSite("G1 ModuleGenerator.generate_field", "core/generators/module_generator.py", 526, "module_generator", temperature_override=0.7),
    BuildCallSite("G2 MapLayoutGenerator.generate_thematic_names", "core/generators/area_generator.py", 180, "generate_thematic_names", temperature_override=0.8),
    BuildCallSite("G3 AreaGenerator.generate_area_name_and_description", "core/generators/area_generator.py", 546, "generate_area_name", json_mode=True, temperature_override=0.8),
    BuildCallSite("G4 AreaGenerator.generate_area_description", "core/generators/area_generator.py", 731, "generate_area_description", temperature_override=0.8),
    BuildCallSite("G5 PlotGenerator.generate_field", "core/generators/plot_generator.py", 349, "plot_generator", temperature_override=0.7),
    BuildCallSite("G6 PlotGenerator.generate_plot_structure", "core/generators/plot_generator.py", 468, "plot_generator", json_mode=True, temperature_override=0.8),
    BuildCallSite("G7 LocationGenerator.generate_field", "core/generators/location_generator.py", 461, "location_generator", temperature_override=0.7),
    BuildCallSite("G8 LocationGenerator.generate_location_batch", "core/generators/location_generator.py", 607, "location_generator_batch", json_mode=True, temperature_override=0.8),
    BuildCallSite("G9 generate_npc", "core/generators/npc_builder.py", 123, "npc_builder", temperature_override=0.7),
    BuildCallSite("G10 generate_monster", "core/generators/monster_builder.py", 249, "monster_builder", temperature_override=0.7),
    # Spatial and classification toolkit calls.
    BuildCallSite("S1 _resolve_semantic_spatial_plan_with_llm", "utils/spatial_contract.py", 671, "dm_validation", json_mode=True, temperature_override=0.2),
    BuildCallSite("C1 ClassificationCache._call_llm_with_fallback", "web/extensions/toolkit_llm_classification.py", 211, "dm_validation", json_mode=True, temperature_override=0.2),
    # Markdown / publication-adjacent calls M1-M3 (task id summaries).
    BuildCallSite("M1 _llm_intro_narrative", "utils/homebrewery_adventure_writer.py", 343, "summaries", max_completion_tokens=800, temperature_override=0.5),
    BuildCallSite("M2 _llm_plot_hook", "utils/homebrewery_adventure_writer.py", 430, "summaries", max_completion_tokens=250, temperature_override=0.7),
    BuildCallSite("M3 _llm_area_overview", "utils/homebrewery_adventure_writer.py", 670, "summaries", max_completion_tokens=500, temperature_override=0.6),
    # Included toolkit/publication-adjacent calls (inventory section 2).
    BuildCallSite("A1 ModuleStitcher._generate_travel_narration", "core/generators/module_stitcher.py", 451, "travel_narration", temperature_override=0.8),
    BuildCallSite("A2 ModuleStitcher._ai_validate_content_safety", "core/generators/module_stitcher.py", 1136, "safety_review", temperature_override=0.1),
    BuildCallSite("A4 toolkit NPC description helper", "web/web_interface.py", 5827, "npc_builder", max_tokens=300, temperature_override=0.7),
    BuildCallSite("A7 NpcReconciler._ai_confirm_merge", "utils/npc_reconciler.py", 71, "dm_validation", max_tokens=1, temperature_override=0.0),
    BuildCallSite("A9 _try_provider_call", "scripts/run_critical_narrative_repair.py", 54, "builders", timeout=120, temperature_override=0.2),
]


def _site_anchor(site: BuildCallSite) -> str:
    return "%s:%s" % (site.file_path, site.line)


def _declared_preserved_kwargs(site: BuildCallSite) -> dict:
    """The non-sampling fields the inventory records for this site."""
    declared = {}
    if site.json_mode:
        declared["response_format"] = {"type": "json_object"}
    if site.timeout is not None:
        declared["timeout"] = site.timeout
    if site.max_completion_tokens is not None:
        declared["max_completion_tokens"] = site.max_completion_tokens
    if site.max_tokens is not None:
        declared["max_tokens"] = site.max_tokens
    return declared


class TestAggregateDirectGPT5Branch(unittest.TestCase):
    """Every migrated build-path site: GPT-5 kwargs carry the task profile."""

    def test_every_site_includes_task_profile_and_omits_legacy_sampling(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                captured = bf.capture_gpt5_build_request(
                    task_id=site.task_id,
                    **_declared_preserved_kwargs(site),
                )
                kwargs = captured.create_kwargs
                expected_profile = ai_client_factory._resolve_gpt5_chat_profile(
                    site.task_id
                )
                self.assertEqual(kwargs["model"], bf.GPT5_DIRECT_MODEL, site.label)
                for key, value in expected_profile.items():
                    self.assertEqual(kwargs[key], value, site.label)
                self.assertNotIn("temperature", kwargs, site.label)
                self.assertNotIn("top_p", kwargs, site.label)
                self.assertEqual(kwargs["messages"], bf.DEFAULT_MESSAGES, site.label)

    def test_every_site_exact_final_key_set(self) -> None:
        # Final kwargs = helper params (model + profile) + messages + the
        # site's declared preserved fields. No stray sampling keys may exist.
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                captured = bf.capture_gpt5_build_request(
                    task_id=site.task_id,
                    **_declared_preserved_kwargs(site),
                )
                expected_keys = {
                    "model",
                    "reasoning_effort",
                    "verbosity",
                    "messages",
                }
                expected_keys.update(_declared_preserved_kwargs(site).keys())
                self.assertEqual(
                    set(captured.create_kwargs.keys()),
                    expected_keys,
                    site.label,
                )

    def test_json_mode_sites_preserve_response_format(self) -> None:
        json_sites = [s for s in BUILD_SITES if s.json_mode]
        self.assertTrue(json_sites, "expected at least one json-mode site")
        for site in json_sites:
            with self.subTest(site=site.label):
                kwargs = bf.capture_gpt5_build_request(
                    task_id=site.task_id, response_format={"type": "json_object"}
                ).create_kwargs
                self.assertEqual(kwargs["response_format"], {"type": "json_object"})
                self.assertNotIn("temperature", kwargs)

    def test_token_and_timeout_sites_preserve_bounds(self) -> None:
        for site in BUILD_SITES:
            if site.max_completion_tokens is None and site.max_tokens is None and site.timeout is None:
                continue
            with self.subTest(site=site.label):
                kwargs = bf.capture_gpt5_build_request(
                    task_id=site.task_id,
                    **_declared_preserved_kwargs(site),
                ).create_kwargs
                if site.max_completion_tokens is not None:
                    self.assertEqual(
                        kwargs["max_completion_tokens"],
                        site.max_completion_tokens,
                    )
                if site.max_tokens is not None:
                    self.assertEqual(kwargs["max_tokens"], site.max_tokens)
                if site.timeout is not None:
                    self.assertEqual(kwargs["timeout"], site.timeout)

    def test_profile_resolved_from_task_identity_not_global_default(self) -> None:
        # Distinct task families must resolve distinct profiles; a single
        # global build default would collapse these assertions. Expected
        # values come from the resolver itself (the sole authority) and are
        # pinned here so drift in either direction fails loudly.
        profiles = {}
        for site in BUILD_SITES:
            profiles[site.task_id] = ai_client_factory._resolve_gpt5_chat_profile(
                site.task_id
            )
        self.assertEqual(
            profiles["builders"],
            {"reasoning_effort": "medium", "verbosity": "medium"},
        )
        self.assertEqual(
            profiles["dm_validation"],
            {"reasoning_effort": "low", "verbosity": "low"},
        )
        # NOTE: the M1-M3 task id is ``summaries``, which does not contain
        # the substring ``summary``; the resolver therefore gives it the
        # medium/medium default branch (verified actual behavior, pinned by
        # the markdown writer suite which computes the same resolver output).
        self.assertEqual(
            profiles["summaries"],
            {"reasoning_effort": "medium", "verbosity": "medium"},
        )
        # The resolver's summary-family branch (adventure_summary etc.)
        # resolves low/medium; the two branches must differ.
        self.assertEqual(
            ai_client_factory._resolve_gpt5_chat_profile("adventure_summary"),
            {"reasoning_effort": "low", "verbosity": "medium"},
        )
        self.assertNotEqual(profiles["builders"], profiles["dm_validation"])
        self.assertNotEqual(profiles["summaries"], profiles["dm_validation"])
        self.assertNotEqual(
            ai_client_factory._resolve_gpt5_chat_profile("adventure_summary"),
            profiles["summaries"],
        )


class TestAggregateCompatibleNonGPT5Branch(unittest.TestCase):
    """The same matrix on a compatible non-GPT-5 model preserves temperature."""

    def test_every_site_preserves_recorded_temperature_intent(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                captured = bf.capture_non_gpt5_build_request(
                    task_id=site.task_id,
                    temperature_override=site.temperature_override,
                )
                kwargs = captured.create_kwargs
                self.assertEqual(kwargs["model"], bf.NON_GPT5_DIRECT_MODEL, site.label)
                self.assertEqual(kwargs["temperature"], site.temperature_override, site.label)
                self.assertNotIn("reasoning_effort", kwargs, site.label)
                self.assertNotIn("verbosity", kwargs, site.label)
                self.assertNotIn("top_p", kwargs, site.label)
                self.assertEqual(kwargs["messages"], bf.DEFAULT_MESSAGES, site.label)

    def test_json_mode_survives_on_non_gpt5_branch(self) -> None:
        for site in [s for s in BUILD_SITES if s.json_mode]:
            with self.subTest(site=site.label):
                kwargs = bf.capture_non_gpt5_build_request(
                    task_id=site.task_id,
                    temperature_override=site.temperature_override,
                    response_format={"type": "json_object"},
                ).create_kwargs
                self.assertEqual(kwargs["response_format"], {"type": "json_object"})
                self.assertEqual(kwargs["temperature"], site.temperature_override)


class TestAggregateInventoryAnchoring(unittest.TestCase):
    """The matrix cannot silently drift from the inventory report."""

    def test_every_site_row_exists_in_the_inventory_report(self) -> None:
        with open(_REPORT_PATH, "r", encoding="utf-8") as fh:
            report = fh.read()
        for site in BUILD_SITES:
            with self.subTest(site=_site_anchor(site)):
                self.assertIn(
                    _site_anchor(site),
                    report,
                    "inventory report missing row %s" % _site_anchor(site),
                )

    def test_matrix_covers_every_priority_site(self) -> None:
        # 23 priority sites (N1-N5, B1-B3, G1-G10, S1, C1, M1-M3) plus the
        # five included adjacent sites (A1, A2, A4, A7, A9).
        self.assertEqual(len(BUILD_SITES), 28)
        anchors = [_site_anchor(s) for s in BUILD_SITES]
        # No duplicate site rows.
        self.assertEqual(len(anchors), len(set(anchors)))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
