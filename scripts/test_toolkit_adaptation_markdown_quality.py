# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free regression tests for the adaptation Markdown quality contract.

Task 8.1: deterministic quality checks for UTF-8, title, headings, playable
content, adaptation notice, minimum size, and absence of raw JSON or error
text. Invalid summaries must block adaptation completion before any registry
call. Legacy accurate-ingest behavior must remain unchanged.

All tests use project-local temporary staging targets and patched writer
surfaces. No real module, world registry, or campaign state is mutated.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_module_finisher as finisher
from utils.toolkit_adaptation_dossier import ADAPTATION_NOTICE
from utils.toolkit_adaptation_markdown_quality import (
    ADAPTATION_MARKDOWN_QUALITY_CONTRACT,
    MIN_SUMMARY_BYTES,
    check_adaptation_markdown_quality,
    summarize_adaptation_markdown_quality,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASH = "c" * 64
VALID_FIXTURE = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_markdown_valid.md"
)


def _valid_markdown() -> str:
    """Return the valid adaptation fixture content."""
    return VALID_FIXTURE.read_text(encoding="utf-8")


def _body_without_title() -> str:
    """Return the valid fixture minus its H1 title line."""
    dropped = "# The Sunken Cartographer"
    kept = []
    for line in _valid_markdown().splitlines():
        if line.strip() == dropped:
            continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def _no_title_doc() -> str:
    """Return a readable document that contains no H1 heading at all."""
    return (
        "## Introduction\n\n"
        "The adventure premise: recover the last chart of the drowned city.\n\n"
        "## Locations\n\n"
        "### The Ledger Room\n\n"
        "### The Compass Chamber\n\n"
        "## Credits\n\n"
        "**Adapted for NEQ-TTRPG**\n\n"
    )


def _no_playable_doc() -> str:
    """Return a readable document without any location or area signal."""
    return (
        "# The Sunken Cartographer\n\n"
        "## Introduction\n\n"
        "The adventure premise: recover the last chart of the drowned city.\n\n"
        "# Plot Overview\n\n"
        "## PP001 -- The Drowned Invitation\n\n"
        "A sealed map case arrives at the flooded market.\n\n"
        "### The Compass Riddle\n\n"
        "The compass must align with the drowned stars.\n\n"
        "# Credits\n\n"
        "**Adapted for NEQ-TTRPG**\n\n"
    )


def _no_premise_doc() -> str:
    """Return a readable document with locations but no plot or premise."""
    return (
        "# The Sunken Cartographer\n\n"
        "# Locations\n\n"
        "## Area 1 -- The Drowned Archive\n\n"
        "### The Ledger Room\n\n"
        "### The Compass Chamber\n\n"
        "## Area 2 -- The Warden Shrine\n\n"
        "# Credits\n\n"
        "**Adapted for NEQ-TTRPG**\n\n"
    )


def _passing_adaptation_gates() -> dict:
    """Return the complete Python-owned pass envelope from task 4.2."""
    domains = (
        "schema",
        "readiness",
        "mechanical_closure",
        "semantic_authority",
        "semantic_probes",
    )
    gates = {
        domain: {"status": "pass", "effective_status": "pass"}
        for domain in domains
    }
    gates["report_agreement"] = {
        "status": "pass",
        "effective_status": "pass",
        "playable_publication_status": "pass",
        "agreement": {"playable_publication_status": "pass"},
    }
    return {
        "status": "pass",
        "playable_status": "pass",
        "candidate_eligible": True,
        "gates": gates,
        "publication": {
            "authority": "python",
            "attempted": False,
            "allowed": False,
        },
    }


class TestAdaptationMarkdownQualityContract(unittest.TestCase):
    """Unit tests for each rule of the deterministic quality contract."""

    def test_valid_fixture_passes_all_checks(self):
        result = check_adaptation_markdown_quality(_valid_markdown())

        self.assertTrue(result["valid"])
        self.assertEqual(result["contract"], ADAPTATION_MARKDOWN_QUALITY_CONTRACT)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["reason"], "adaptation_markdown_quality_pass")
        self.assertGreater(result["bytes"], MIN_SUMMARY_BYTES)
        for check_name in (
            "utf8",
            "min_size",
            "title",
            "headings",
            "playable_content",
            "notice",
            "no_raw_json",
            "no_error_text",
        ):
            self.assertEqual(
                result["checks"][check_name]["status"], "pass", check_name
            )
        self.assertEqual(
            result["checks"]["notice"]["reason"],
            "summary_adaptation_notice_ok",
        )

    def test_valid_fixture_reports_module_slug(self):
        result = check_adaptation_markdown_quality(
            _valid_markdown(), module_slug="Sunken_Cartographer"
        )
        self.assertEqual(result["module_slug"], "Sunken_Cartographer")

    def test_non_text_input_fails_utf8(self):
        for bad in (None, 123, ["# Title"], b"# Title\n"):
            result = check_adaptation_markdown_quality(bad)
            self.assertFalse(result["valid"])
            self.assertEqual(result["reason"], "summary_not_text")
            self.assertEqual(result["failures"], ["utf8"])

    def test_lone_surrogate_fails_utf8(self):
        result = check_adaptation_markdown_quality(_valid_markdown() + "\ud800")
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "invalid_utf8")
        self.assertEqual(result["failures"], ["utf8"])

    def test_nul_byte_fails_utf8(self):
        result = check_adaptation_markdown_quality(_valid_markdown() + "\x00")
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "invalid_utf8")

    def test_empty_summary_fails_minimum_size(self):
        result = check_adaptation_markdown_quality("")
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "generated_content_too_short")
        self.assertIn("min_size", result["failures"])

    def test_too_short_summary_fails_minimum_size(self):
        result = check_adaptation_markdown_quality("# Hi\n\nShort.\n")
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "generated_content_too_short")
        self.assertIn("min_size", result["failures"])

    def test_custom_minimum_size_parameter(self):
        tiny = (
            "# A Tiny Adventure\n\n"
            "## Introduction\n\n"
            "The premise is small but complete.\n\n"
            "## Locations\n\n"
            "### One Room\n\n"
            "# Credits\n\n"
            "**Adapted for NEQ-TTRPG**\n"
        )
        small_result = check_adaptation_markdown_quality(tiny, min_bytes=10)
        large_result = check_adaptation_markdown_quality(tiny, min_bytes=10000)
        self.assertTrue(small_result["valid"])
        self.assertFalse(large_result["valid"])
        self.assertEqual(large_result["reason"], "generated_content_too_short")

    def test_missing_title_heading_fails(self):
        result = check_adaptation_markdown_quality(_no_title_doc())
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "summary_missing_title")
        self.assertIn("title", result["failures"])

    def test_placeholder_title_fails(self):
        for title in ("# Title", "# Untitled", "# Module Title", "# TBD"):
            doc = title + "\n\n" + _body_without_title()
            result = check_adaptation_markdown_quality(doc)
            self.assertFalse(result["valid"], title)
            self.assertEqual(
                result["reason"], "summary_title_not_meaningful", title
            )

    def test_insufficient_headings_fails(self):
        doc = (
            "# The Sunken Cartographer\n\n"
            "## Introduction\n\n"
            "The adventure premise: recover the last chart of the drowned "
            "city before the tide claims it forever.\n"
        )
        result = check_adaptation_markdown_quality(doc)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "summary_insufficient_headings")
        self.assertIn("headings", result["failures"])

    def test_missing_playable_locations_fails(self):
        result = check_adaptation_markdown_quality(_no_playable_doc())
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "summary_missing_playable_content")
        self.assertIn("playable_content", result["failures"])
        self.assertEqual(
            result["checks"]["playable_content"]["details"]["playable_locations"],
            0,
        )

    def test_missing_plot_premise_fails(self):
        result = check_adaptation_markdown_quality(_no_premise_doc())
        self.assertFalse(result["valid"])
        self.assertIn("playable_content", result["failures"])
        self.assertEqual(
            result["checks"]["playable_content"]["details"]["plot_premise"], 0
        )

    def test_missing_adaptation_notice_fails(self):
        doc = _valid_markdown().replace(
            "**Adapted for NEQ-TTRPG**", "**Adapted for NeverEndingQuest**"
        )
        result = check_adaptation_markdown_quality(doc)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "summary_missing_adaptation_notice")
        self.assertIn("notice", result["failures"])

    def test_custom_notice_parameter(self):
        doc = _valid_markdown().replace(
            "**Adapted for NEQ-TTRPG**", "**Adapted for NEQ**"
        )
        result = check_adaptation_markdown_quality(
            doc, notice="Adapted for NEQ"
        )
        self.assertTrue(result["valid"], result["failures"])
        strict_result = check_adaptation_markdown_quality(doc)
        self.assertFalse(strict_result["valid"])
        self.assertEqual(
            strict_result["reason"], "summary_missing_adaptation_notice"
        )

    def test_raw_json_dump_fails(self):
        dump = (
            "# The Sunken Cartographer\n\n"
            "## Introduction\n\n"
            "The adventure premise: recover the last chart.\n\n"
            "# Locations\n\n"
            "## Area 1 -- The Archive\n\n"
            "### The Ledger Room\n\n"
            "# Credits\n\n"
            "**Adapted for NEQ-TTRPG**\n\n"
            '{"title": "Sunken", "areas": ["A", "B"], "plot": "x", '
            '"npcs": "y", "rooms": "z"}\n'
        )
        result = check_adaptation_markdown_quality(dump)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "summary_contains_raw_json")
        self.assertIn("no_raw_json", result["failures"])

    def test_raw_json_array_dump_fails(self):
        dump = (
            "# The Sunken Cartographer\n\n"
            "## Introduction\n\n"
            "The adventure premise: recover the last chart.\n\n"
            "# Locations\n\n"
            "## Area 1 -- The Archive\n\n"
            "### The Ledger Room\n\n"
            "# Credits\n\n"
            "**Adapted for NEQ-TTRPG**\n\n"
            '[{"id": "a", "name": "x"}, {"id": "b", "name": "y"}, '
            '{"id": "c", "name": "z"}]\n'
        )
        result = check_adaptation_markdown_quality(dump)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "summary_contains_raw_json")

    def test_fenced_json_example_is_allowed(self):
        doc = _valid_markdown() + "\n```json\n{\"key\": \"value\"}\n```\n"
        result = check_adaptation_markdown_quality(doc)
        self.assertTrue(result["valid"], result["failures"])

    def test_traceback_text_fails(self):
        doc = (
            _valid_markdown()
            + "\nTraceback (most recent call last):\n"
            + '  File "/tmp/x.py", line 12, in main\n'
            + "ValueError: boom\n"
        )
        result = check_adaptation_markdown_quality(doc)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "summary_contains_error_text")
        self.assertIn("no_error_text", result["failures"])

    def test_provider_error_text_fails(self):
        for fragment in (
            "OpenAIError: rate limit exceeded",
            "ProviderError: upstream timeout",
            "Internal Server Error",
            "APIError: 429",
            "HTTPError: 503",
        ):
            result = check_adaptation_markdown_quality(
                _valid_markdown() + "\n\n" + fragment + "\n"
            )
            self.assertFalse(result["valid"], fragment)
            self.assertEqual(
                result["reason"], "summary_contains_error_text", fragment
            )

    def test_summarize_helpers(self):
        ok = check_adaptation_markdown_quality(_valid_markdown())
        bad = check_adaptation_markdown_quality("")
        self.assertEqual(
            summarize_adaptation_markdown_quality(ok),
            "adaptation_markdown_quality_pass",
        )
        summary = summarize_adaptation_markdown_quality(bad)
        self.assertIn("generated_content_too_short", summary)
        self.assertIn("min_size", summary)
        self.assertEqual(
            summarize_adaptation_markdown_quality(None),
            "adaptation_markdown_quality_unavailable",
        )


class TestAdaptationMarkdownWriterNotice(unittest.TestCase):
    """Verify the renderer emits the exact notice only in adaptation mode."""

    MINIMAL_DATA = {
        "module_slug": "Test_Module",
        "display_name": "Test Module",
        "author": "",
        "license": "",
        "npcs": {},
        "plot_points": [],
        "areas": [],
        "monsters": [],
        "maps": [],
        "_cross_area_edges": [],
        "main_objective": "A test premise.",
    }

    def _render(self, adaptation_notice: bool) -> str:
        import utils.homebrewery_adventure_writer as writer

        with patch.object(
            writer, "load_module_data", return_value=dict(self.MINIMAL_DATA)
        ), patch.object(writer, "_llm_intro_narrative", return_value=None), patch.object(
            writer, "_llm_plot_hook", return_value=None
        ), patch.object(
            writer, "_llm_area_overview", return_value=None
        ):
            return writer.generate_homebrewery_adventure(
                "Test_Module",
                adaptation_notice=adaptation_notice,
            )

    def test_adaptation_mode_emits_exact_notice_and_passes_quality(self):
        markdown = self._render(adaptation_notice=True)
        self.assertIn(ADAPTATION_NOTICE, markdown)
        result = check_adaptation_markdown_quality(markdown)
        self.assertTrue(result["valid"], result["failures"])

    def test_legacy_mode_omits_adaptation_notice(self):
        markdown = self._render(adaptation_notice=False)
        self.assertNotIn(ADAPTATION_NOTICE, markdown)


class TestAdaptationMarkdownPublicationIsolation(unittest.TestCase):
    """Stage and finisher integration: strict contract blocks registry calls."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_markdown_quality_",
        )
        self.root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.target = create_adaptation_staging_target(
            SOURCE_HASH,
            job_id="markdown-quality",
            attempt_number=1,
            revision_number=0,
            module_slug="Adaptation_Markdown_Fixture",
            staging_root="tmp/adaptation-staging",
            repo_root=self.root,
        )
        self.module_dir = self.root / self.target["path"]

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _run_finisher(self, markdown: str, registry=None):
        registry_side_effect = registry if registry is not None else {}
        with patch(
            "utils.homebrewery_adventure_writer.generate_homebrewery_adventure",
            return_value=markdown,
        ) as generator, patch.object(
            finisher, "_run_registry_stage", return_value=registry_side_effect
        ) as registry_stage:
            result = finisher.run_toolkit_module_postbuild_finishing(
                "Adaptation_Markdown_Fixture",
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_adaptation_gates(),
                adaptation_staging_target=self.target,
                adaptation_module_dir=str(self.module_dir),
            )
        return result, generator, registry_stage

    def test_invalid_markdown_blocks_completion_before_registry(self):
        invalid = (
            _valid_markdown()
            + "\nTraceback (most recent call last):\n"
            + '  File "/x/y.py", line 12, in main\n'
            + "ValueError: boom\n"
        )
        result, generator, registry_stage = self._run_finisher(invalid)
        generator.assert_called_once()
        registry_stage.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "adaptation_markdown_quality_failed")
        self.assertEqual(
            result["stages"]["registry"]["status"], "not_attempted"
        )
        self.assertEqual(
            result["stages"]["registry"]["reason"],
            "markdown_quality_check_failed",
        )
        self.assertEqual(
            result["stages"]["module_summary"]["quality"]["reason"],
            "summary_contains_error_text",
        )
        self.assertFalse(
            (self.module_dir / "MODULE_SUMMARY.md").exists(),
            "invalid summary must not be persisted",
        )

    def test_missing_markdown_blocks_completion_before_registry(self):
        result, generator, registry_stage = self._run_finisher("")
        registry_stage.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "adaptation_markdown_quality_failed")
        self.assertEqual(
            result["stages"]["registry"]["reason"],
            "markdown_quality_check_failed",
        )

    def test_valid_markdown_reaches_registry(self):
        result, generator, registry_stage = self._run_finisher(
            _valid_markdown(),
            registry={
                "status": "success",
                "integration_attempted": True,
                "verified": True,
            },
        )
        generator.assert_called_once()
        registry_stage.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["stages"]["registry"]["status"], "success")
        self.assertTrue(
            (self.module_dir / "MODULE_SUMMARY.md").exists(),
            "valid summary must be persisted",
        )
        persisted = (self.module_dir / "MODULE_SUMMARY.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(ADAPTATION_NOTICE, persisted)

    def test_adaptation_summary_stage_uses_strict_contract(self):
        with patch(
            "utils.homebrewery_adventure_writer.generate_homebrewery_adventure",
            return_value=_valid_markdown(),
        ):
            stage = finisher._run_module_summary_stage(
                "Adaptation_Markdown_Fixture",
                self.module_dir,
                adaptation_mode=True,
            )
        self.assertEqual(stage["status"], "success")
        self.assertEqual(
            stage["quality"]["contract"], ADAPTATION_MARKDOWN_QUALITY_CONTRACT
        )
        self.assertTrue(stage["quality"]["valid"])

    def test_legacy_summary_stage_never_invokes_strict_checker(self):
        with patch(
            "utils.homebrewery_adventure_writer.generate_homebrewery_adventure",
            return_value="Traceback (most recent call last): boom\n",
        ) as generator, patch.object(
            finisher, "check_adaptation_markdown_quality"
        ) as strict_checker:
            stage = finisher._run_module_summary_stage(
                "Legacy_Markdown_Fixture",
                self.module_dir,
                adaptation_mode=False,
            )
        generator.assert_called_once()
        strict_checker.assert_not_called()
        self.assertEqual(stage["status"], "degraded")
        self.assertEqual(stage["reason"], "generated_content_too_short")
        self.assertNotIn("contract", stage["quality"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
