# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Source-contract verification for the build-path call site inventory
(change: toolkit-gpt5-build-path-compatibility, task 1.1).

Provider-free. Asserts, against repository source only:

1. The exact set of Chat Completions create-call line numbers in every
   in-scope file matches the inventory recorded in
   reports/build_path_call_site_inventory.md.
    2. No in-scope file other than the helper-routed set
    (utils/toolkit_homebrew_normalizer.py
   since task 2.1, the ModuleBuilder generator files since task 2.2,
   spatial/classification files since task 2.3, and
   utils/homebrewery_adventure_writer.py since task 3.1)
   imports get_chat_completion_params; i.e., every in-scope site is
   HELPER-routed in this baseline.
3. No in-scope file uses top_p sampling.
4. The inventory report contains a row for every asserted call site and no
   unexpected create-call lines exist in the in-scope file set.

Usage:
    .venv/bin/python openspec/changes/toolkit-gpt5-build-path-compatibility/scripts/test_build_call_site_inventory.py
    .venv/bin/python -m unittest openspec.changes.toolkit-gpt5-build-path-compatibility.scripts.test_build_call_site_inventory
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
_REPORT_PATH = os.path.join(_CHANGE_DIR, "reports", "build_path_call_site_inventory.md")

# Matches only real call statements (line ends with the opening paren).
# Docstring/comment mentions such as ``client.chat.completions.create(...)``
# are excluded by the end-of-line anchor.
_CREATE_RE = re.compile(r"\.chat\.completions\.create\(\s*$")
_HELPER_IMPORT_RE = re.compile(r"get_chat_completion_params")
_TOP_P_RE = re.compile(r"\btop_p\b")

# File -> exact create-call line numbers (1-based), as recorded in the
# inventory report. Must match the repository exactly; update only when the
# inventory is intentionally refreshed.
IN_SCOPE_CREATE_LINES = {
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

# The only priority in-scope files allowed to import the shared helper: the
# already helper-routed reference, the normalizer (task 2.1), the ModuleBuilder
# generator set (task 2.2), spatial/classification (task 2.3), and the
# Markdown writer (task 3.1).
HELPER_ROUTED_FILES = {
    "utils/toolkit_homebrew_normalizer.py",
    "core/generators/module_builder.py",
    "core/generators/module_generator.py",
    "core/generators/area_generator.py",
    "core/generators/plot_generator.py",
    "core/generators/location_generator.py",
    "core/generators/npc_builder.py",
    "core/generators/monster_builder.py",
    "utils/spatial_contract.py",
    "web/extensions/toolkit_llm_classification.py",
    "utils/homebrewery_adventure_writer.py",
}

# Adjacent observed sites (section 2 of the report) are checked for
# presence only, not for exact line parity: their line numbers are
# informative and may drift outside the priority sweep.
ADJACENT_SITES = {
    "core/generators/module_stitcher.py": [451, 1136],
    "core/generators/location_summarizer.py": [534],
    "web/web_interface.py": [2530, 4762, 5827],
    "utils/npc_reconciler.py": [71],
    "utils/npc_name_canonicalizer.py": [126],
    "scripts/run_critical_narrative_repair.py": [54],
}

# Adjacent calls proven to run in build/publication or toolkit asset paths and
# migrated in task 2.3. These are checked at the individual call site because
# web/web_interface.py also contains excluded interactive calls.
ADJACENT_HELPER_ROUTED_SITES = {
    "core/generators/module_stitcher.py": [451, 1136],
    "web/web_interface.py": [5827],
    "utils/npc_reconciler.py": [71],
    "scripts/run_critical_narrative_repair.py": [54],
}

# Adjacent calls intentionally left DIRECT because call-graph tracing showed
# runtime-only or purely interactive ownership. A8 has no build/publication
# caller; its only caller is companion-memory runtime code.
ADJACENT_EXCLUDED_SITES = {
    "core/generators/location_summarizer.py": [534],
    "web/web_interface.py": [2530, 4762],
    "utils/npc_name_canonicalizer.py": [126],
}

# In-scope files that must contain NO create call (provider-free helpers).
PROVIDER_FREE_FILES = [
    "utils/toolkit_blueprint_enrichment.py",
    "utils/toolkit_blueprint_seed_writer.py",
    "utils/toolkit_build_fidelity.py",
    "utils/toolkit_builder_blueprint.py",
    "utils/toolkit_entity_candidate_triage.py",
    "utils/toolkit_final_blocker_classifier.py",
    "utils/toolkit_final_reconciliation.py",
    "utils/toolkit_homebrew_pdf_adapter.py",
    "utils/toolkit_homebrew_upload_contract.py",
    "utils/toolkit_narrative_enrichment_plan.py",
    "utils/toolkit_normalization_fidelity.py",
    "utils/toolkit_publication_gate_composer.py",
    "utils/toolkit_report_agreement.py",
    "utils/toolkit_source_extraction.py",
    "utils/toolkit_source_fidelity_benchmark.py",
    "utils/toolkit_source_graph_synthesis.py",
    "utils/toolkit_source_manifest.py",
    "web/extensions/toolkit_homebrew_fidelity_review.py",
    "web/extensions/toolkit_homebrew_packet_builder.py",
    "web/extensions/toolkit_homebrew_readiness_gate.py",
    "web/extensions/toolkit_homebrew_rebuild_guard.py",
    "web/extensions/toolkit_module_finisher.py",
]


def _read_lines(rel_path: str) -> list:
    full = os.path.join(_REPO_ROOT, rel_path)
    with open(full, "r", encoding="utf-8") as fh:
        return fh.read().splitlines()


def _create_line_numbers(rel_path: str) -> list:
    return [
        idx + 1
        for idx, line in enumerate(_read_lines(rel_path))
        if _CREATE_RE.search(line)
    ]


class TestBuildCallSiteInventory(unittest.TestCase):
    """Assert the inventory matches the repository source exactly."""

    def test_in_scope_create_lines_match_exactly(self) -> None:
        for rel_path, expected in sorted(IN_SCOPE_CREATE_LINES.items()):
            with self.subTest(file=rel_path):
                actual = _create_line_numbers(rel_path)
                self.assertEqual(
                    actual,
                    expected,
                    "create-call lines differ from the inventory for %s" % rel_path,
                )

    def test_in_scope_files_do_not_import_helper(self) -> None:
        for rel_path in sorted(IN_SCOPE_CREATE_LINES):
            if rel_path in HELPER_ROUTED_FILES:
                continue
            with self.subTest(file=rel_path):
                self.assertFalse(
                    any(_HELPER_IMPORT_RE.search(line) for line in _read_lines(rel_path)),
                    "%s must remain DIRECT in this baseline (no get_chat_completion_params)" % rel_path,
                )

    def test_helper_routed_reference_uses_helper(self) -> None:
        for rel_path in sorted(HELPER_ROUTED_FILES):
            with self.subTest(file=rel_path):
                src = "\n".join(_read_lines(rel_path))
                self.assertIn("get_chat_completion_params(", src)
                self.assertIn(".chat.completions.create(", src)

    def test_no_top_p_in_in_scope_files(self) -> None:
        for rel_path in sorted(IN_SCOPE_CREATE_LINES):
            with self.subTest(file=rel_path):
                self.assertFalse(
                    any(_TOP_P_RE.search(line) for line in _read_lines(rel_path)),
                    "%s must not use top_p" % rel_path,
                )

    def test_provider_free_files_have_no_create_calls(self) -> None:
        for rel_path in PROVIDER_FREE_FILES:
            with self.subTest(file=rel_path):
                self.assertEqual(
                    _create_line_numbers(rel_path),
                    [],
                    "%s must remain provider-free (no create calls)" % rel_path,
                )

    def test_adjacent_sites_still_present(self) -> None:
        for rel_path, lines in sorted(ADJACENT_SITES.items()):
            actual = _create_line_numbers(rel_path)
            with self.subTest(file=rel_path):
                for line in lines:
                    self.assertIn(
                        line,
                        actual,
                        "adjacent create site %s:%s missing" % (rel_path, line),
                    )

    def test_adjacent_site_routing_decisions_match_scope(self) -> None:
        for rel_path, lines in sorted(ADJACENT_HELPER_ROUTED_SITES.items()):
            source = _read_lines(rel_path)
            for line in lines:
                with self.subTest(site="%s:%s" % (rel_path, line)):
                    window = source[line:line + 8]
                    self.assertTrue(
                        any("get_chat_completion_params(" in item for item in window),
                        "included adjacent site %s:%s must use the shared helper"
                        % (rel_path, line),
                    )

        for rel_path, lines in sorted(ADJACENT_EXCLUDED_SITES.items()):
            source = _read_lines(rel_path)
            for line in lines:
                with self.subTest(site="%s:%s" % (rel_path, line)):
                    window = source[line:line + 8]
                    self.assertFalse(
                        any("get_chat_completion_params(" in item for item in window),
                        "excluded adjacent site %s:%s must remain DIRECT"
                        % (rel_path, line),
                    )

    def test_inventory_report_lists_every_in_scope_site(self) -> None:
        with open(_REPORT_PATH, "r", encoding="utf-8") as fh:
            report = fh.read()
        for rel_path, lines in sorted(IN_SCOPE_CREATE_LINES.items()):
            for line in lines:
                with self.subTest(site="%s:%s" % (rel_path, line)):
                    self.assertIn(
                        "%s:%s" % (rel_path, line),
                        report,
                        "inventory report missing row %s:%s" % (rel_path, line),
                    )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestBuildCallSiteInventory)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
