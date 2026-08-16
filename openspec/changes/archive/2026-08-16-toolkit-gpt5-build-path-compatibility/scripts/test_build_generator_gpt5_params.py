# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider-free ModuleBuilder generator request-shape suite (change:
toolkit-gpt5-build-path-compatibility, task 2.2).

Runs every in-scope ModuleBuilder / generator Chat Completions call site
(B1 unify_plots, B2 _generate_enhanced_plot_hooks, B3
parse_narrative_to_module_params, G1-G10 generator calls) end-to-end with a
recording mock client and captures the FINAL kwargs of every create call.
Asserts, per provider branch:

- Direct GPT-5 family (gpt-5.6-luna): every create call preserves the
  resolved model and the task-resolved GPT-5 profile (reasoning_effort /
  verbosity), omits unsupported legacy temperature/top_p, and keeps
  messages plus any response_format json mode.
- Compatible non-GPT-5 (gpt-4.1-2025-04-14): every create call preserves
  the recorded creative temperature intent (the historical hardcoded
  temperature passed through the helper override) with no GPT-5 profile
  keys.
- OpenRouter: every create call keeps the configured model, the
  provider-specific thinking/request fields from get_model_config, and the
  recorded temperature intent, with no GPT-5 profile substitution.

Also adds a source contract that every in-scope create call in the seven
migrated files spreads ``**get_chat_completion_params(...)`` and that no
direct legacy sampling kwargs (``temperature=``, ``**...get("extra_body")``)
remain in those files.

Provider-free: no live API, no credentials, no raw source persistence.
Transient outputs (unify_plots module_plot.json) use
tempfile.TemporaryDirectory.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any, Callable, Dict, List
from unittest.mock import patch

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

# Synthetic model ids mirroring the fixture module (task 1.2). The model
# constants used by each call site are patched per branch so the tests are
# deterministic regardless of the current model_config assignment.
GPT5_DIRECT_MODEL = bf.GPT5_DIRECT_MODEL
NON_GPT5_DIRECT_MODEL = bf.NON_GPT5_DIRECT_MODEL

# Seven production files migrated in task 2.2 and their create-call counts.
MIGRATED_FILES = {
    "core/generators/module_builder.py": 3,
    "core/generators/module_generator.py": 1,
    "core/generators/area_generator.py": 3,
    "core/generators/plot_generator.py": 2,
    "core/generators/location_generator.py": 2,
    "core/generators/npc_builder.py": 1,
    "core/generators/monster_builder.py": 1,
}

_CREATE_RE = re.compile(r"\.chat\.completions\.create\(\s*$")
_HELPER_SPREAD_RE = re.compile(r"^\s*\*\*get_chat_completion_params\(\s*$")
_LEGACY_TEMP_RE = re.compile(r"\btemperature=")
_LEGACY_EXTRA_BODY_RE = re.compile(r"\*\*[^)]*get\(\"extra_body\"")
_TOP_P_RE = re.compile(r"\btop_p\b")

_UNIFIED_PLOT_PAYLOAD = {
    "plotTitle": "Test Plot",
    "mainObjective": "Complete the quest",
    "plotPoints": [],
    "activeQuests": [],
    "completedQuests": [],
    "failedQuests": [],
    "worldEvents": [],
    "dmNotes": [],
}

_PARAMS_PAYLOAD = {
    "module_name": "Test_Adventure",
    "num_areas": 3,
    "locations_per_area": 6,
    "level_range": {"min": 3, "max": 5},
    "adventure_type": "mixed",
    "plot_themes": "adventure,mystery",
}


class _FakeChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _RecCompletions:
    def __init__(self, payload):
        self.calls = []
        self._content = json.dumps(payload) if not isinstance(payload, str) else payload

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        return _FakeResponse(self._content)


class _RecClient:
    def __init__(self, payload):
        self.chat = type("Chat", (), {"completions": _RecCompletions(payload)})()


# --- per-site invocations ---------------------------------------------------

def _invoke_b1(client: Any) -> None:
    from core.generators.module_builder import ModuleBuilder, BuilderConfig

    with tempfile.TemporaryDirectory() as tmp:
        builder = object.__new__(ModuleBuilder)
        builder.config = BuilderConfig(output_directory=tmp, verbose=False)
        builder.module_data = {
            "moduleName": "Test Module",
            "moduleDescription": "A test module.",
        }
        builder.areas_data = {
            "AREA1": {
                "areaName": "A1",
                "areaType": "dungeon",
                "recommendedLevel": 1,
            }
        }
        builder.plots_data = {
            "AREA1": {"plotTitle": "T", "mainObjective": "O", "plotPoints": []}
        }
        builder.unify_plots()


def _invoke_b2(client: Any) -> None:
    from core.generators.module_builder import ModuleBuilder

    builder = object.__new__(ModuleBuilder)
    builder._generate_enhanced_plot_hooks(
        "AREA1",
        {
            "areaName": "A1",
            "locations": [{"locationId": "R01", "plotHooks": ["hook"]}],
        },
        [{"id": "PP001", "title": "T", "description": "D"}],
        [],
        client,
    )


def _invoke_b3(client: Any) -> None:
    from core.generators.module_builder import parse_narrative_to_module_params

    parse_narrative_to_module_params("A heroic adventure in the dark woods.")


def _invoke_g1(client: Any) -> None:
    from core.generators.module_generator import ModuleGenerator

    ModuleGenerator().generate_field("moduleName", {"type": "string"}, {})


def _invoke_g2(client: Any) -> None:
    from core.generators.area_generator import MapLayoutGenerator

    MapLayoutGenerator().generate_thematic_names(
        [{"id": "L001", "type": "entrance", "connections": []}],
        {
            "module_name": "Test Module",
            "area_name": "Dark Forest",
            "area_type": "wilderness",
            "theme": "haunted",
        },
    )


def _invoke_g3(client: Any) -> None:
    from core.generators.area_generator import AreaConfig, AreaGenerator

    AreaGenerator().generate_area_name_and_description(
        "Old Lighthouse", AreaConfig()
    )


def _invoke_g4(client: Any) -> None:
    from core.generators.area_generator import AreaConfig, AreaGenerator

    AreaGenerator().generate_area_description("Shipwreck Coast", AreaConfig())


def _invoke_g5(client: Any) -> None:
    from core.generators.plot_generator import PlotGenerator

    PlotGenerator().generate_field("moduleDescription", {"type": "string"}, {})


def _invoke_g6(client: Any) -> None:
    from core.generators.plot_generator import PlotGenerator

    PlotGenerator().generate_plot_structure(2, {})


def _invoke_g7(client: Any) -> None:
    from core.generators.location_generator import LocationGenerator

    LocationGenerator().generate_field("description", {"type": "string"}, {})


def _invoke_g8(client: Any) -> None:
    from core.generators.location_generator import LocationGenerator

    LocationGenerator().generate_location_batch(
        {}, {}, {}, [{"locationId": "R01"}]
    )


def _invoke_g9(client: Any) -> None:
    from core.generators.npc_builder import generate_npc

    generate_npc("Test NPC", {})


def _invoke_g10(client: Any) -> None:
    from core.generators.monster_builder import generate_monster

    generate_monster("Goblin", {}, party_level=1)


@dataclass
class BuildSite:
    """One migrated B/G call site and how to exercise it provider-free."""

    label: str
    task_id: str
    create_patch_target: str
    model_patch_targets: List[str]
    temperature: float
    json_mode: bool
    invoke: Callable[[Any], None]
    payload: Any


BUILD_SITES = [
    BuildSite(
        "B1 unify_plots",
        "unify_plots",
        "utils.ai_client_factory.create_chat_client",
        ["config.DM_MAIN_MODEL"],
        0.7,
        True,
        _invoke_b1,
        _UNIFIED_PLOT_PAYLOAD,
    ),
    BuildSite(
        "B2 _generate_enhanced_plot_hooks",
        "update_plot_hooks",
        "utils.ai_client_factory.create_chat_client",
        ["config.DM_MAIN_MODEL"],
        0.6,
        True,
        _invoke_b2,
        {"plotHookUpdates": []},
    ),
    BuildSite(
        "B3 parse_narrative_to_module_params",
        "parse_module_params",
        "utils.ai_client_factory.create_chat_client",
        ["config.DM_SUMMARIZATION_MODEL"],
        0.3,
        False,
        _invoke_b3,
        _PARAMS_PAYLOAD,
    ),
    BuildSite(
        "G1 ModuleGenerator.generate_field",
        "module_generator",
        "core.generators.module_generator.create_chat_client",
        ["core.generators.module_generator.DM_MAIN_MODEL"],
        0.7,
        False,
        _invoke_g1,
        "test",
    ),
    BuildSite(
        "G2 MapLayoutGenerator.generate_thematic_names",
        "generate_thematic_names",
        "core.generators.area_generator.create_chat_client",
        ["core.generators.area_generator.DM_MAIN_MODEL"],
        0.8,
        False,
        _invoke_g2,
        ["Entrance Hall"],
    ),
    BuildSite(
        "G3 AreaGenerator.generate_area_name_and_description",
        "generate_area_name",
        "core.generators.area_generator.create_chat_client",
        ["core.generators.area_generator.DM_MAIN_MODEL"],
        0.8,
        True,
        _invoke_g3,
        {"refinedName": "Shipwreck Coast", "description": "A wild shore."},
    ),
    BuildSite(
        "G4 AreaGenerator.generate_area_description",
        "generate_area_description",
        "core.generators.area_generator.create_chat_client",
        ["core.generators.area_generator.DM_MAIN_MODEL"],
        0.8,
        False,
        _invoke_g4,
        "A wild, windswept shore.",
    ),
    BuildSite(
        "G5 PlotGenerator.generate_field",
        "plot_generator",
        "core.generators.plot_generator.create_chat_client",
        ["core.generators.plot_generator.DM_MAIN_MODEL"],
        0.7,
        False,
        _invoke_g5,
        "test",
    ),
    BuildSite(
        "G6 PlotGenerator.generate_plot_structure",
        "plot_generator",
        "core.generators.plot_generator.create_chat_client",
        ["core.generators.plot_generator.DM_MAIN_MODEL"],
        0.8,
        True,
        _invoke_g6,
        {"plotPoints": []},
    ),
    BuildSite(
        "G7 LocationGenerator.generate_field",
        "location_generator",
        "core.generators.location_generator.create_chat_client",
        ["core.generators.location_generator.DM_MAIN_MODEL"],
        0.7,
        False,
        _invoke_g7,
        "test",
    ),
    BuildSite(
        "G8 LocationGenerator.generate_location_batch",
        "location_generator_batch",
        "core.generators.location_generator.create_chat_client",
        ["core.generators.location_generator.DM_MAIN_MODEL"],
        0.8,
        True,
        _invoke_g8,
        {"locations": []},
    ),
    BuildSite(
        "G9 generate_npc",
        "npc_builder",
        "core.generators.npc_builder.create_chat_client",
        ["core.generators.npc_builder.NPC_BUILDER_MODEL"],
        0.7,
        False,
        _invoke_g9,
        {},
    ),
    BuildSite(
        "G10 generate_monster",
        "monster_builder",
        "core.generators.monster_builder.create_chat_client",
        ["config.MONSTER_BUILDER_MODEL"],
        0.7,
        False,
        _invoke_g10,
        {},
    ),
]


def _run_site(site: BuildSite, model_value: str, provider):
    """Run one site with a recording client; return the captured create kwargs."""
    client = _RecClient(site.payload)
    with bf.forced_provider(provider[0], provider[1]), ExitStack() as stack:
        stack.enter_context(patch(site.create_patch_target, return_value=client))
        for target in site.model_patch_targets:
            stack.enter_context(patch(target, model_value))
        site.invoke(client)
    return client.chat.completions.calls


class TestMigratedSiteSourceContract(unittest.TestCase):
    """Every B/G create call spreads the shared helper; no legacy sampling remains."""

    def _source(self, rel_path: str) -> List[str]:
        full = os.path.join(_REPO_ROOT, rel_path)
        with open(full, "r", encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_every_create_call_spreads_the_helper(self) -> None:
        for rel_path, expected_count in sorted(MIGRATED_FILES.items()):
            lines = self._source(rel_path)
            create_lines = [
                idx
                for idx, line in enumerate(lines)
                if _CREATE_RE.search(line)
            ]
            self.assertEqual(
                len(create_lines),
                expected_count,
                "%s create-call count drifted" % rel_path,
            )
            for idx in create_lines:
                with self.subTest(file=rel_path, line=idx + 1):
                    self.assertTrue(
                        _HELPER_SPREAD_RE.search(lines[idx + 1]),
                        "%s:%s must spread **get_chat_completion_params("
                        % (rel_path, idx + 1),
                    )

    def test_no_direct_legacy_sampling_kwargs_remain(self) -> None:
        for rel_path in sorted(MIGRATED_FILES):
            src = "\n".join(self._source(rel_path))
            with self.subTest(file=rel_path):
                self.assertFalse(
                    _LEGACY_TEMP_RE.search(src),
                    "%s must not pass temperature= directly" % rel_path,
                )
                self.assertFalse(
                    _LEGACY_EXTRA_BODY_RE.search(src),
                    "%s must not spread config extra_body directly" % rel_path,
                )
                self.assertFalse(
                    _TOP_P_RE.search(src),
                    "%s must not use top_p" % rel_path,
                )

    def test_helper_imported_in_every_migrated_file(self) -> None:
        for rel_path in sorted(MIGRATED_FILES):
            with self.subTest(file=rel_path):
                self.assertIn(
                    "get_chat_completion_params",
                    "\n".join(self._source(rel_path)),
                    "%s must import the shared helper" % rel_path,
                )


class TestDirectGPT5GeneratorRequests(unittest.TestCase):
    """Direct GPT-5 build calls carry the task profile and omit legacy sampling."""

    def test_all_sites_omit_legacy_sampling_and_keep_profile(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                calls = _run_site(site, GPT5_DIRECT_MODEL, ("openai", False))
                self.assertEqual(len(calls), 1, site.label)
                kwargs = calls[0]
                expected_profile = ai_client_factory._resolve_gpt5_chat_profile(
                    site.task_id
                )
                self.assertEqual(kwargs["model"], GPT5_DIRECT_MODEL, site.label)
                for key, value in expected_profile.items():
                    self.assertEqual(kwargs[key], value, site.label)
                self.assertNotIn("temperature", kwargs, site.label)
                self.assertNotIn("top_p", kwargs, site.label)
                self.assertIn("messages", kwargs, site.label)
                if site.json_mode:
                    self.assertEqual(
                        kwargs.get("response_format"),
                        {"type": "json_object"},
                        site.label,
                    )

    def test_b3_profile_matches_task_resolver(self) -> None:
        site = next(s for s in BUILD_SITES if s.label.startswith("B3"))
        kwargs = _run_site(site, GPT5_DIRECT_MODEL, ("openai", False))[0]
        expected = ai_client_factory._resolve_gpt5_chat_profile(site.task_id)
        for key, value in expected.items():
            self.assertEqual(kwargs[key], value)


class TestCompatibleNonGPT5GeneratorRequests(unittest.TestCase):
    """Non-GPT-5 direct build calls preserve the recorded temperature intent."""

    def test_all_sites_preserve_temperature_intent(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                calls = _run_site(
                    site, NON_GPT5_DIRECT_MODEL, ("openai", False)
                )
                self.assertEqual(len(calls), 1, site.label)
                kwargs = calls[0]
                self.assertEqual(kwargs["model"], NON_GPT5_DIRECT_MODEL, site.label)
                self.assertEqual(
                    kwargs.get("temperature"),
                    site.temperature,
                    site.label,
                )
                self.assertNotIn("reasoning_effort", kwargs, site.label)
                self.assertNotIn("verbosity", kwargs, site.label)
                self.assertNotIn("top_p", kwargs, site.label)
                if site.json_mode:
                    self.assertEqual(
                        kwargs.get("response_format"),
                        {"type": "json_object"},
                        site.label,
                    )


class TestOpenRouterGeneratorRequests(unittest.TestCase):
    """OpenRouter build calls keep model, thinking fields, and temperature."""

    @staticmethod
    def _expected_config(task_id: str, model: str) -> dict:
        with bf.forced_provider("openrouter", True):
            return ai_client_factory.get_model_config(task_id, model)

    def test_all_sites_preserve_openrouter_request_shape(self) -> None:
        for site in BUILD_SITES:
            with self.subTest(site=site.label):
                expected = self._expected_config(site.task_id, GPT5_DIRECT_MODEL)
                calls = _run_site(
                    site, GPT5_DIRECT_MODEL, ("openrouter", True)
                )
                self.assertEqual(len(calls), 1, site.label)
                kwargs = calls[0]
                self.assertEqual(kwargs["model"], expected["model"], site.label)
                self.assertEqual(
                    kwargs.get("temperature"),
                    site.temperature,
                    site.label,
                )
                for key, value in (expected.get("extra_body") or {}).items():
                    self.assertEqual(
                        kwargs.get(key),
                        value,
                        "%s OpenRouter extra_body field %s must be preserved"
                        % (site.label, key),
                    )
                self.assertNotIn("reasoning_effort", kwargs, site.label)
                self.assertNotIn("verbosity", kwargs, site.label)
                if site.json_mode:
                    self.assertEqual(
                        kwargs.get("response_format"),
                        {"type": "json_object"},
                        site.label,
                    )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
