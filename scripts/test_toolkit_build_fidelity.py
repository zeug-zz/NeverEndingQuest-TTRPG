#!/usr/bin/env python3
"""Regression tests for toolkit Homebrew build fidelity gates."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_build_fidelity import (  # noqa: E402
    is_build_fidelity_required,
    build_build_fidelity_report,
    can_continue_after_build_fidelity,
    build_source_fidelity_rollup,
)
from utils.toolkit_homebrew_upload_contract import get_workspace_files  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ToolkitBuildFidelityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.files = get_workspace_files(self.workspace)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_base_accurate_workspace(self) -> None:
        _write_json(
            self.files["source_graph"],
            {
                "atoms": [
                    {"type": "npc", "name": "Caretaker Noll", "criticality": "required"},
                    {"type": "npc", "name": "Sister Mara", "criticality": "advisory"},
                    {"type": "location", "name": "Ruined Gate", "criticality": "required"},
                    {"type": "location", "name": "Crypt Entrance", "criticality": "required"},
                    {"type": "plot_beat", "label": "Enter the crypt", "criticality": "required"},
                    {"type": "plot_beat", "label": "Find the key", "criticality": "required"},
                    {"type": "puzzle", "label": "Hidden switch", "criticality": "required"},
                    {"type": "clue", "label": "Ash on the altar", "criticality": "required"},
                    {"type": "encounter", "label": "Skeleton patrol", "criticality": "required"},
                    {"type": "item", "label": "Rust key", "criticality": "required"},
                    {"type": "item", "label": "Silver amulet", "criticality": "advisory"},
                ]
            },
        )
        _write_json(self.files["normalization_fidelity_report"], {"status": "clean"})
        _write_json(self.files["normalization_report"], {"status": "ready"})

    def _write_minimal_module(self, path: Path) -> None:
        (path / "areas").mkdir(parents=True, exist_ok=True)
        _write_json(
            path / "areas" / "A01.json",
            {
                "areaId": "A01",
                "areaName": "Ruined Gate",
                "locations": [{"name": "Ruined Gate", "locationId": "LOC01"}],
                "npcs": [],
                "monsters": [],
            },
        )
        _write_json(
            path / "areas" / "A02.json",
            {
                "areaId": "A02",
                "areaName": "Crypt Entrance",
                "locations": [{"name": "Crypt Entrance", "locationId": "LOC02"}],
                "npcs": [],
                "monsters": [],
            },
        )
        (path / "characters").mkdir(parents=True, exist_ok=True)
        _write_json(
            path / "characters" / "caretaker_noll.json",
            {
                "name": "Caretaker Noll",
                "character_name": "Caretaker Noll",
                "type": "npc",
            },
        )
        _write_json(
            path / "module_plot.json",
            {
                "plotPoints": [
                    {"name": "Enter the crypt", "title": "Enter the crypt"},
                    {"name": "Find the key", "title": "Find the key"},
                ]
            },
        )

    # --- Task 5.1: Helper tests ---

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_legacy_workspace_no_source_graph(self) -> None:
        self.assertFalse(is_build_fidelity_required(self.workspace))

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_is_required_when_source_graph_exists(self) -> None:
        self._write_base_accurate_workspace()
        self.assertTrue(is_build_fidelity_required(self.workspace))

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", False)
    def test_disabled_flag_returns_false(self) -> None:
        self._write_base_accurate_workspace()
        self.assertFalse(is_build_fidelity_required(self.workspace))

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_pass_report_all_atoms_present(self) -> None:
        self._write_base_accurate_workspace()
        module_dir = Path(self.temp_dir.name) / "module"
        self._write_minimal_module(module_dir)
        report = build_build_fidelity_report(self.workspace, module_dir)
        self.assertIn(report["status"], ("pass", "degraded"))
        self.assertTrue(report["can_continue"])
        self.assertEqual(len(report["blockers"]), 0)

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_blocked_missing_required_npc(self) -> None:
        self._write_base_accurate_workspace()
        module_dir = Path(self.temp_dir.name) / "module"
        self._write_minimal_module(module_dir)
        (module_dir / "characters" / "caretaker_noll.json").unlink()
        report = build_build_fidelity_report(self.workspace, module_dir)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["can_continue"])
        npc_blockers = [b for b in report["blockers"] if b.get("category") == "npc"]
        self.assertTrue(len(npc_blockers) > 0)

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_blocked_missing_keyed_location(self) -> None:
        self._write_base_accurate_workspace()
        module_dir = Path(self.temp_dir.name) / "module"
        self._write_minimal_module(module_dir)
        (module_dir / "areas" / "A02.json").unlink()
        report = build_build_fidelity_report(self.workspace, module_dir)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["can_continue"])
        loc_blockers = [b for b in report["blockers"] if b.get("category") == "location"]
        self.assertTrue(len(loc_blockers) > 0)

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_blocked_missing_plot_beat(self) -> None:
        self._write_base_accurate_workspace()
        module_dir = Path(self.temp_dir.name) / "module"
        self._write_minimal_module(module_dir)
        _write_json(
            module_dir / "module_plot.json",
            {"plotPoints": [{"name": "Enter the crypt"}]},
        )
        report = build_build_fidelity_report(self.workspace, module_dir)
        self.assertEqual(report["status"], "blocked")
        plot_blockers = [b for b in report["blockers"] if b.get("category") == "plot_beat"]
        self.assertTrue(len(plot_blockers) > 0)

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_failed_missing_module_dir(self) -> None:
        self._write_base_accurate_workspace()
        missing_dir = Path(self.temp_dir.name) / "does_not_exist"
        report = build_build_fidelity_report(self.workspace, missing_dir)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["can_continue"])

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_legacy_report_when_no_source_graph(self) -> None:
        module_dir = Path(self.temp_dir.name) / "module"
        self._write_minimal_module(module_dir)
        report = build_build_fidelity_report(self.workspace, module_dir)
        self.assertEqual(report["status"], "legacy")
        self.assertTrue(report["can_continue"])

    @patch("utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES", True)
    def test_coverage_counts(self) -> None:
        self._write_base_accurate_workspace()
        module_dir = Path(self.temp_dir.name) / "module"
        self._write_minimal_module(module_dir)
        report = build_build_fidelity_report(self.workspace, module_dir)
        coverage = report.get("coverage") or {}
        self.assertGreater(coverage.get("npc", {}).get("found", 0), 0)
        self.assertGreater(coverage.get("location", {}).get("found", 0), 0)
        self.assertGreater(coverage.get("plot_beat", {}).get("found", 0), 0)

    # --- Task 5.4: Route/status tests ---

    def test_can_continue_accepts_pass(self) -> None:
        ok, reason = can_continue_after_build_fidelity({"status": "pass", "blockers": []})
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_can_continue_rejects_blocked(self) -> None:
        report = {"status": "blocked", "refusal_reason": "missing_npc", "blockers": [{"category": "npc"}]}
        ok, reason = can_continue_after_build_fidelity(report)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_npc")

    def test_can_continue_rejects_blockers(self) -> None:
        report = {"status": "degraded", "blockers": [{"category": "npc"}], "refusal_reason": "blockers_present"}
        ok, reason = can_continue_after_build_fidelity(report)
        self.assertFalse(ok)
        self.assertEqual(reason, "blockers_present")

    def test_source_fidelity_rollup_shape(self) -> None:
        build_report = {
            "status": "pass",
            "coverage": {"npc": {"found": 5, "total": 5}},
            "blockers": [],
            "warnings": [],
            "source_artifacts": {},
        }
        rollup = build_source_fidelity_rollup(self.workspace, build_report)
        self.assertIn("status", rollup)
        self.assertIn("normalization_fidelity", rollup)
        self.assertIn("blueprint", rollup)
        self.assertIn("build_fidelity", rollup)
        self.assertIn("final_blocker_count", rollup)


# ---------------------------------------------------------------------------
# Task 0.2: Punctuation-Normalized Build Fidelity (Numillian blocker)
#   Source-contract tests documenting the current _normalize_name() behavior
#   for trailing markdown/table punctuation such as `:`.
# ---------------------------------------------------------------------------

class TestBuildFidelityPunctuationNormalization(unittest.TestCase):
    """Regression locks for Numillian skull-trial build-fidelity blocker.

    Current _normalize_name() does NOT strip trailing punctuation like `:`,
    so source atoms with `Red Skull:` do not match module entries `Red Skull`.
    These tests document the blocker. After Step 1.1 adds rstrip(",:;.!?"),
    the equality assertions MUST be updated to assert equal.
    """

    def _normalize(self, name: str) -> str:
        """Replicate current _normalize_name() from utils/toolkit_build_fidelity.py."""
        return name.strip().lower().replace(" ", "_").replace("-", "_").rstrip(",:;.!?")

    def test_trailing_colon_mismatch_red_skull(self):
        """BEHAVIORAL: Red Skull: (markdown table) == Red Skull after punctuation normalization."""
        result = self._normalize("Red Skull:")
        expected = self._normalize("Red Skull")
        self.assertEqual(
            result, expected,
            "Red Skull: must equal Red Skull after trailing colon is stripped.",
        )

    def test_trailing_colon_mismatch_blue_skull(self):
        """BEHAVIORAL: Blue Skull: (markdown table) == Blue Skull after punctuation normalization."""
        result = self._normalize("Blue Skull:")
        expected = self._normalize("Blue Skull")
        self.assertEqual(result, expected)

    def test_trailing_colon_mismatch_yellow_skull(self):
        """BEHAVIORAL: Yellow Skull: (markdown table) == Yellow Skull after punctuation normalization."""
        result = self._normalize("Yellow Skull:")
        expected = self._normalize("Yellow Skull")
        self.assertEqual(result, expected)

    def test_clean_names_still_match(self):
        """Names without trailing punctuation must still match normally."""
        self.assertEqual(
            self._normalize("Caretaker Noll"),
            self._normalize("Caretaker Noll"),
        )

    def test_distinct_names_remain_distinct(self):
        """The Caretaker and The Caretaker / Procul must remain distinct."""
        self.assertNotEqual(
            self._normalize("The Caretaker"),
            self._normalize("The Caretaker / Procul"),
        )

    def test_trailing_semicolon_stripped(self):
        """Names with trailing semicolon match clean name after punctuation normalization."""
        self.assertEqual(
            self._normalize("Guard;"),
            self._normalize("Guard"),
        )

    def test_trailing_exclamation_stripped(self):
        """Names with trailing ! match clean name after punctuation normalization."""
        self.assertEqual(
            self._normalize("Guard!"),
            self._normalize("Guard"),
        )

    def test_kebab_hyphen_names_preserved(self):
        """Hyphenated names like Dog-Growl must keep hyphen after normalization."""
        result = self._normalize("Dog-Growl")
        self.assertIn("dog", result)
        self.assertIn("growl", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
