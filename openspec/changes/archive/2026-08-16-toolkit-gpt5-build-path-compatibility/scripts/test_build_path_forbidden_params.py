# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Source-contract suite for forbidden legacy sampling parameters (change:
toolkit-gpt5-build-path-compatibility, task 3.2).

Task 3.2 audit: every priority build-path Chat Completions create block
(in-scope sites N1-N5, B1-B3, G1-G10, S1, C1, M1-M3) and the traced
included adjacent build/publication blocks (A1, A2, A4, A7, A9) must not
emit unsupported direct GPT-5 legacy sampling kwargs. Provider-free.

Asserts, against repository source only:

1. No create block in the priority or traced-included-adjacent set contains
   ``top_p``, a direct ``temperature=`` kwarg, or a direct
   ``**...get("extra_body")`` spread. Sampling intent may only flow through
   the shared helper boundary (``get_chat_completion_params``), either as an
   inline ``**get_chat_completion_params(...)`` spread.
    or as a pre-resolved ``params = get_chat_completion_params(...)`` object
    spread with ``**params`` where applicable.
2. The only direct ``temperature=`` kwargs in the traced adjacent file set
   are the two explicitly excluded interactive blocks (web_interface A5
   portrait prompt generation at 4767 and A6 promote_to_bestiary at 2535);
   those blocks are NOT in the priority set and are asserted to retain
   their legacy shape so the exclusion boundary stays observable.
3. Whole-file ``top_p`` absence holds for every priority and traced included
   adjacent file (no hidden top_p outside the create blocks).
4. Final GPT-5 request kwargs captured through the fixture for every
   distinct priority task id omit ``temperature``/``top_p`` and carry the
   task-resolved reasoning/verbosity profile (helper boundary end-to-end).

Provider-free: no live API, no credentials, no raw source persistence.
"""

from __future__ import annotations

import os
import re
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

_TOP_P_RE = re.compile(r"\btop_p\b")
_DIRECT_TEMP_KWARG_RE = re.compile(r"\btemperature=")
_DIRECT_EXTRA_BODY_SPREAD_RE = re.compile(r"\*\*[^)]*\.get\(\"extra_body\"")

# Maximum number of lines scanned after a create line to bound the block
# window. All create blocks in the inventory close within a few lines; the
# window only needs to catch direct kwargs at the top of the block.
_BLOCK_WINDOW_LINES = 15

# Priority in-scope create blocks (file -> 1-based create-call lines), taken
# from reports/build_path_call_site_inventory.md sections 1.1-1.7.
PRIORITY_CREATE_LINES = {
    "utils/toolkit_homebrew_normalizer.py": [476, 553, 644, 764, 905],
    "core/generators/module_builder.py": [693, 957, 1463],
    "core/generators/module_generator.py": [526],
    "core/generators/area_generator.py": [180, 546, 731],
    "core/generators/plot_generator.py": [349, 468],
    "core/generators/location_generator.py": [461, 607],
    "core/generators/npc_builder.py": [123],
    "core/generators/monster_builder.py": [249],
    "utils/spatial_contract.py": [671],
    "web/extensions/toolkit_llm_classification.py": [211],
    "utils/homebrewery_adventure_writer.py": [343, 430, 670],
}

# Traced included adjacent build/publication blocks (inventory section 2,
# migrated task 2.3 / 3.1). A4's create call lives at 5827 in web_interface.
INCLUDED_ADJACENT_CREATE_LINES = {
    "core/generators/module_stitcher.py": [451, 1136],
    "web/web_interface.py": [5827],
    "utils/npc_reconciler.py": [71],
    "scripts/run_critical_narrative_repair.py": [54],
}

# Excluded interactive blocks that retain direct legacy temperature by
# explicit call-graph exclusion (inventory section 2: A5, A6). File ->
# create-call lines; their windows are expected to contain direct
# ``temperature=`` and are deliberately NOT part of the priority set.
EXCLUDED_DIRECT_TEMPERATURE_BLOCKS = {
    "web/web_interface.py": [2530, 4762],
}

PRE_RESOLVED_PARAMS_FILES = set()

# Distinct priority task ids (helper boundary end-to-end kwargs capture).
PRIORITY_TASK_IDS = [
    "builders",  # N1-N5, A9
    "unify_plots",  # B1
    "update_plot_hooks",  # B2
    "parse_module_params",  # B3
    "module_generator",  # G1
    "generate_thematic_names",  # G2
    "generate_area_name",  # G3
    "generate_area_description",  # G4
    "plot_generator",  # G5, G6
    "location_generator",  # G7
    "location_generator_batch",  # G8
    "npc_builder",  # G9, A4
    "monster_builder",  # G10
    "dm_validation",  # S1, C1, A7
    "summaries",  # M1-M3
    "travel_narration",  # A1
    "safety_review",  # A2
]


def _read_lines(rel_path: str) -> list:
    full = os.path.join(_REPO_ROOT, rel_path)
    with open(full, "r", encoding="utf-8") as fh:
        return fh.read().splitlines()


def _block_window(rel_path: str, create_line: int) -> str:
    """Return the bounded source window following a create call."""
    lines = _read_lines(rel_path)
    start = max(create_line - 1, 0)
    end = min(start + _BLOCK_WINDOW_LINES, len(lines))
    return "\n".join(lines[start:end])


class TestPriorityBlocksForbidLegacySampling(unittest.TestCase):
    """No priority create block emits top_p / direct temperature / extra_body."""

    def test_no_forbidden_kwargs_in_priority_blocks(self) -> None:
        for rel_path, lines in sorted(PRIORITY_CREATE_LINES.items()):
            for create_line in lines:
                window = _block_window(rel_path, create_line)
                with self.subTest(block="%s:%s" % (rel_path, create_line)):
                    self.assertFalse(
                        _TOP_P_RE.search(window),
                        "priority block %s:%s must not use top_p" % (rel_path, create_line),
                    )
                    self.assertFalse(
                        _DIRECT_TEMP_KWARG_RE.search(window),
                        "priority block %s:%s must not pass temperature= directly"
                        % (rel_path, create_line),
                    )
                    self.assertFalse(
                        _DIRECT_EXTRA_BODY_SPREAD_RE.search(window),
                        "priority block %s:%s must not spread config extra_body directly"
                        % (rel_path, create_line),
                    )

    def test_no_forbidden_kwargs_in_included_adjacent_blocks(self) -> None:
        for rel_path, lines in sorted(INCLUDED_ADJACENT_CREATE_LINES.items()):
            for create_line in lines:
                window = _block_window(rel_path, create_line)
                with self.subTest(block="%s:%s" % (rel_path, create_line)):
                    self.assertFalse(
                        _TOP_P_RE.search(window),
                        "included adjacent block %s:%s must not use top_p"
                        % (rel_path, create_line),
                    )
                    self.assertFalse(
                        _DIRECT_TEMP_KWARG_RE.search(window),
                        "included adjacent block %s:%s must not pass temperature= directly"
                        % (rel_path, create_line),
                    )
                    self.assertFalse(
                        _DIRECT_EXTRA_BODY_SPREAD_RE.search(window),
                        "included adjacent block %s:%s must not spread config extra_body directly"
                        % (rel_path, create_line),
                    )

    def test_every_priority_block_routes_through_shared_helper(self) -> None:
        for rel_path, lines in sorted(PRIORITY_CREATE_LINES.items()):
            source = "\n".join(_read_lines(rel_path))
            uses_pre_resolved = rel_path in PRE_RESOLVED_PARAMS_FILES
            for create_line in lines:
                window = _block_window(rel_path, create_line)
                with self.subTest(block="%s:%s" % (rel_path, create_line)):
                    if uses_pre_resolved:
                        self.assertIn(
                            "**params",
                            window,
                            "pre-resolved block %s:%s must spread **params"
                            % (rel_path, create_line),
                        )
                        self.assertIn(
                            "params = get_chat_completion_params(",
                            source,
                            "%s must resolve params via the shared helper"
                            % rel_path,
                        )
                    else:
                        self.assertIn(
                            "**get_chat_completion_params(",
                            window,
                            "priority block %s:%s must spread the shared helper"
                            % (rel_path, create_line),
                        )

    def test_included_adjacent_blocks_route_through_shared_helper(self) -> None:
        for rel_path, lines in sorted(INCLUDED_ADJACENT_CREATE_LINES.items()):
            for create_line in lines:
                window = _block_window(rel_path, create_line)
                with self.subTest(block="%s:%s" % (rel_path, create_line)):
                    self.assertIn(
                        "**get_chat_completion_params(",
                        window,
                        "included adjacent block %s:%s must spread the shared helper"
                        % (rel_path, create_line),
                    )


class TestExcludedInteractiveBlocksKeepLegacyShape(unittest.TestCase):
    """The only direct temperature in the traced set stays at the excluded sites."""

    def test_excluded_blocks_retain_direct_temperature(self) -> None:
        for rel_path, lines in sorted(EXCLUDED_DIRECT_TEMPERATURE_BLOCKS.items()):
            for create_line in lines:
                window = _block_window(rel_path, create_line)
                with self.subTest(block="%s:%s" % (rel_path, create_line)):
                    self.assertTrue(
                        _DIRECT_TEMP_KWARG_RE.search(window),
                        "excluded interactive block %s:%s must retain its direct "
                        "temperature= (call-graph exclusion boundary)"
                        % (rel_path, create_line),
                    )

    def test_excluded_blocks_are_not_in_priority_set(self) -> None:
        for rel_path, lines in EXCLUDED_DIRECT_TEMPERATURE_BLOCKS.items():
            for create_line in lines:
                with self.subTest(block="%s:%s" % (rel_path, create_line)):
                    self.assertNotIn(
                        create_line,
                        PRIORITY_CREATE_LINES.get(rel_path, []),
                        "excluded block %s:%s must not be in the priority set"
                        % (rel_path, create_line),
                    )
                    self.assertNotIn(
                        create_line,
                        INCLUDED_ADJACENT_CREATE_LINES.get(rel_path, []),
                        "excluded block %s:%s must not be in the included adjacent set"
                        % (rel_path, create_line),
                    )


class TestWholeFileTopPAbsence(unittest.TestCase):
    """No top_p anywhere in priority or traced included adjacent files."""

    def test_no_top_p_in_priority_files(self) -> None:
        for rel_path in sorted(PRIORITY_CREATE_LINES):
            with self.subTest(file=rel_path):
                self.assertFalse(
                    any(_TOP_P_RE.search(line) for line in _read_lines(rel_path)),
                    "%s must not use top_p" % rel_path,
                )

    def test_no_top_p_in_included_adjacent_files(self) -> None:
        for rel_path in sorted(INCLUDED_ADJACENT_CREATE_LINES):
            with self.subTest(file=rel_path):
                self.assertFalse(
                    any(_TOP_P_RE.search(line) for line in _read_lines(rel_path)),
                    "%s must not use top_p" % rel_path,
                )


class TestHelperBoundaryEndToEndKwargs(unittest.TestCase):
    """Final GPT-5 kwargs per priority task id omit temperature/top_p."""

    def test_gpt5_final_kwargs_omit_legacy_sampling(self) -> None:
        for task_id in PRIORITY_TASK_IDS:
            with self.subTest(task_id=task_id):
                captured = bf.capture_gpt5_build_request(task_id=task_id)
                kwargs = captured.create_kwargs
                self.assertNotIn("temperature", kwargs, task_id)
                self.assertNotIn("top_p", kwargs, task_id)
                expected_profile = ai_client_factory._resolve_gpt5_chat_profile(task_id)
                for key, value in expected_profile.items():
                    self.assertEqual(kwargs.get(key), value, task_id)
                self.assertIn("messages", kwargs, task_id)

    def test_non_gpt5_final_kwargs_preserve_temperature_intent(self) -> None:
        for task_id in PRIORITY_TASK_IDS:
            with self.subTest(task_id=task_id):
                captured = bf.capture_non_gpt5_build_request(
                    task_id=task_id, temperature_override=0.7
                )
                kwargs = captured.create_kwargs
                self.assertEqual(kwargs.get("temperature"), 0.7, task_id)
                self.assertNotIn("top_p", kwargs, task_id)
                self.assertNotIn("reasoning_effort", kwargs, task_id)
                self.assertNotIn("verbosity", kwargs, task_id)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
