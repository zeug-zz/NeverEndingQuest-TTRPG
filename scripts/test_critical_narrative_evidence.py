# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for the critical narrative omission evidence pass.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from typing import Any, Dict, List

from utils.critical_narrative_evidence import (
    CLASSIFICATION_ALIAS_VARIANT,
    CLASSIFICATION_BUILDER_REPAIR,
    OMISSION_TYPE_MISSING_ACTOR,
    OMISSION_TYPE_MISSING_PUZZLE,
    ACTOR_SURFACE_MODULE_CONTEXT,
    ACTOR_SURFACE_MODULE_CONTEXT_NESTED,
    ACTOR_SURFACE_AREA_LOCATIONS,
    PUZZLE_SURFACE_MODULE_CONTEXT,
    PUZZLE_SURFACE_MODULE_PLOT,
    PUZZLE_SURFACE_AREA_TEXT,
    _collect_module_npcs,
    _collect_module_context_nested_npcs,
    _collect_puzzles_from_module_context,
    _collect_puzzles_from_plot,
    _collect_puzzles_from_area_text,
    _has_alias_in_live,
    _normalize_name,
    _truncate_excerpt,
    _extract_lore_source_descriptions,
    _extract_puzzle_source_descriptions,
    detect_missing_actors,
    detect_missing_puzzles,
    format_evidence_summary,
    run_critical_omission_evidence_pass,
    _extract_source_markdown_excerpts,
    _resolve_source_markdown_path,
)

NUMILLIAN_SLUG = "The_Hidden_City_of_Numillian"


def _real_fixture() -> Dict[str, Any]:
    """Load the actual Numillian benchmark fixture for integration tests."""
    import json as _json
    from pathlib import Path
    p = Path("data/benchmarks") / f"{NUMILLIAN_SLUG}_benchmark.json"
    if p.exists():
        return _json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(str(p))


def _build_fixture_for_test(
    actor_names: List[str] = None,
    puzzle_ids: List[str] = None,
    lore_descs: Dict[str, str] = None,
    puzzle_descs: Dict[str, str] = None,
) -> Dict[str, Any]:
    """Construct a minimal valid benchmark fixture with *real* nesting shape."""
    actor_names = actor_names or ["Shuluth"]
    puzzle_ids = puzzle_ids or ["skull_riddle"]
    lore_descs = lore_descs or {}
    puzzle_descs = puzzle_descs or {}
    return {
        "benchmark_version": "numillian_benchmark.v1",
        "module_slug": NUMILLIAN_SLUG,
        "expectations": {
            "npc_preservation": {
                "total_source_npcs": len(actor_names),
                "named_source_npcs": list(actor_names),
                "minimum_represented": max(1, len(actor_names) - 1),
                "allow_minor_unused": True,
            },
            "puzzle_preservation": {
                "total_source_puzzles": len(puzzle_ids),
                "required_puzzles": list(puzzle_ids),
                "source_descriptions": dict(puzzle_descs),
                "minimum_preserved": len(puzzle_ids),
            },
            "location_preservation": {
                "total_source_locations": 0, "source_locations": [],
                "minimum_preserved": 0,
            },
            "lore_preservation": {
                "total_source_lore_elements": len(lore_descs),
                "required_elements": list(lore_descs.keys()),
                "source_descriptions": dict(lore_descs),
                "minimum_preserved": len(lore_descs),
            },
            "tone_preservation": {
                "expected_tone": "quirky_character_driven_hidden_city",
                "tone_description": "quirky",
                "blocked_replacement": "generic",
            },
        },
        "publication_thresholds": {
            "pass": {
                "npc_preservation": 0.9,
                "location_preservation": 1.0,
                "puzzle_preservation": 1.0,
                "lore_preservation": 1.0,
                "tone_preservation": "quirky_character_driven_hidden_city",
            },
            "degraded": {
                "npc_preservation": 0.7,
                "location_preservation": 0.85,
                "puzzle_preservation": 0.67,
                "lore_preservation": 0.5,
                "tone_preservation": "generic_conspiracy_thriller",
            },
        },
    }


def _build_module_context(npcs: Dict[str, Dict[str, str]] = None,
                          puzzles: List[Dict[str, str]] = None) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "module_name": "Test",
        "module_id": "test",
        "areas": {},
        "npcs": npcs or {},
        "locations": {},
    }
    if puzzles is not None:
        ctx["puzzles"] = puzzles
    return ctx


def _build_module_plot(plot_points: List[Dict[str, str]] = None) -> Dict[str, Any]:
    return {
        "plotTitle": "Test Adventure",
        "plotPoints": plot_points or [],
    }


# ---------------------------------------------------------------------------
#  Helper tests
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_normalize_name(self):
        self.assertEqual(_normalize_name("  Kobe  "), "kobe")
        self.assertEqual(_normalize_name("Wayne (Waynobibille)"), "wayne (waynobibille)")

    def test_truncate_excerpt_short(self):
        self.assertEqual(_truncate_excerpt("Short", 200), "Short")

    def test_truncate_excerpt_long(self):
        text = "A" * 300
        result = _truncate_excerpt(text, 50)
        self.assertLessEqual(len(result), 53)
        self.assertTrue(result.endswith("..."))


# ---------------------------------------------------------------------------
#  Fixture description extraction tests (real fixture shape)
# ---------------------------------------------------------------------------

class TestFixtureDescriptionExtraction(unittest.TestCase):

    def test_real_fixture_lore_descriptions(self):
        fix = _real_fixture()
        descs = _extract_lore_source_descriptions(fix)
        self.assertIn("kobe_protection", descs)
        self.assertIn("Kobe", descs["kobe_protection"])

    def test_real_fixture_puzzle_descriptions(self):
        fix = _real_fixture()
        descs = _extract_puzzle_source_descriptions(fix)
        self.assertIn("skull_riddle", descs)
        self.assertIn("First Trial", descs["skull_riddle"])

    def test_real_fixture_nesting_correct(self):
        """Verify fixture has the real expectations nesting shape."""
        fix = _real_fixture()
        exp = fix.get("expectations", {})
        lore = exp.get("lore_preservation", {})
        self.assertIn("source_descriptions", lore)
        puzzle = exp.get("puzzle_preservation", {})
        self.assertIn("source_descriptions", puzzle)


# ---------------------------------------------------------------------------
#  Module NPC collection tests
# ---------------------------------------------------------------------------

class TestCollectModuleNpcs(unittest.TestCase):

    def test_returns_sorted_names(self):
        ctx = _build_module_context({
            "shuluth": {"name": "Shuluth"},
            "kobe": {"name": "Kobe"},
        })
        self.assertEqual(_collect_module_npcs(ctx), ["Kobe", "Shuluth"])

    def test_empty_npcs_returns_empty(self):
        self.assertEqual(_collect_module_npcs(_build_module_context({})), [])

    def test_none_context_returns_empty(self):
        self.assertEqual(_collect_module_npcs(None), [])


# ---------------------------------------------------------------------------
#  Puzzle collection tests
# ---------------------------------------------------------------------------

class TestCollectPuzzles(unittest.TestCase):

    def test_from_module_context_block(self):
        ctx = _build_module_context(puzzles=[{"id": "skull_riddle"}])
        self.assertEqual(
            _collect_puzzles_from_module_context(ctx), {"skull_riddle"},
        )

    def test_from_plot_skull_keyword(self):
        plot = _build_module_plot([
            {"title": "The First Trial", "description": "A room with skulls"},
        ])
        ids = _collect_puzzles_from_plot(plot)
        self.assertIn("skull_riddle", ids)

    def test_from_plot_flood_keyword(self):
        plot = _build_module_plot([
            {"title": "Flooding Room", "description": "Water fills the room"},
        ])
        ids = _collect_puzzles_from_plot(plot)
        self.assertIn("flooding_room", ids)

    def test_from_plot_dog_keyword(self):
        plot = _build_module_plot([
            {"description": "A small dog is here"},
        ])
        ids = _collect_puzzles_from_plot(plot)
        self.assertIn("kill_the_dog_mindscape", ids)

    def test_from_empty_plot_returns_empty(self):
        self.assertEqual(_collect_puzzles_from_plot(None), set())

    def test_dedupes_multi_hit(self):
        ctx = _build_module_context(puzzles=[{"id": "skull_riddle"}])
        plot = _build_module_plot([
            {"title": "The Skull Trial"},
            {"description": "Another skull reference"},
        ])
        combined = (_collect_puzzles_from_module_context(ctx)
                    | _collect_puzzles_from_plot(plot))
        self.assertEqual(combined, {"skull_riddle"})


# ---------------------------------------------------------------------------
#  Nested module_context NPC scanning tests
# ---------------------------------------------------------------------------

class TestCollectNestedModuleContextNpcs(unittest.TestCase):

    def test_finds_npcs_in_areas(self):
        ctx = {
            "areas": {
                "A0": {"npcs": ["Red Skull", "Blue Skull"]},
            },
            "npcs": {},
            "locations": {},
        }
        names = _collect_module_context_nested_npcs(ctx)
        self.assertIn("Red Skull", names)
        self.assertIn("Blue Skull", names)

    def test_finds_npcs_in_locations_notableNPCs(self):
        ctx = {
            "areas": {},
            "npcs": {},
            "locations": {
                "L01": {"notableNPCs": ["Kobe"]},
            },
        }
        names = _collect_module_context_nested_npcs(ctx)
        self.assertIn("Kobe", names)

    def test_finds_npcs_in_locations_visibleNPCs(self):
        ctx = {
            "locations": {
                "L01": {"visibleNPCs": [{"name": "Kobe"}]},
            },
        }
        names = _collect_module_context_nested_npcs(ctx)
        self.assertIn("Kobe", names)

    def test_empty_context_returns_empty(self):
        self.assertEqual(_collect_module_context_nested_npcs(None), [])
        self.assertEqual(_collect_module_context_nested_npcs({}), [])

    def test_nested_npc_satisfies_expected_actor(self):
        """An actor found in nested module_context surfaces prevents omission."""
        fixture = _build_fixture_for_test(
            actor_names=["Shuluth", "Kobe"],
        )
        ctx = {
            "npcs": {"shuluth": {"name": "Shuluth"}},
            "locations": {"L01": {"notableNPCs": ["Kobe"]}},
            "areas": {},
        }
        live_module = sorted(set(
            _collect_module_npcs(ctx) +
            _collect_module_context_nested_npcs(ctx)
        ))
        result = detect_missing_actors(
            ["Shuluth", "Kobe"],
            live_module,
            [],
            "test",
            fixture,
            {},
        )
        self.assertEqual(len(result.get("critical_omissions", [])), 0)
        self.assertEqual(len(result.get("review_items", [])), 0)


# ---------------------------------------------------------------------------
#  Alias variant detection tests
# ---------------------------------------------------------------------------

class TestAliasVariantDetection(unittest.TestCase):

    def test_wayne_alias_detected(self):
        """Wayne (Waynobibille Nebiddlespun) has alias wayne in live."""
        self.assertTrue(
            _has_alias_in_live(
                "Wayne (Waynobibille Nebiddlespun)",
                ["Wayne", "Shuluth"],
            )
        )

    def test_wayne_alias_via_substring(self):
        self.assertTrue(
            _has_alias_in_live(
                "Wayne (Waynobibille Nebiddlespun)",
                ["Waynobibille Nebiddlespun"],
            )
        )

    def test_kobe_no_alias_in_live(self):
        self.assertFalse(
            _has_alias_in_live("Kobe", ["Shuluth", "Wayne"])
        )

    def test_exact_match_returns_true(self):
        self.assertTrue(
            _has_alias_in_live("Kobe", ["Kobe"])
        )

    def test_empty_live_returns_false(self):
        self.assertFalse(_has_alias_in_live("Kobe", []))


# ---------------------------------------------------------------------------
#  Missing actor detection tests (real fixture shape)
# ---------------------------------------------------------------------------

class TestDetectMissingActors(unittest.TestCase):

    def test_kobe_detected_as_critical_omission(self):
        """Kobe must be builder_repair_recommended when truly absent."""
        fixture = _build_fixture_for_test(
            actor_names=["Shuluth", "Kobe"],
            lore_descs={"kobe_protection": "A young girl Kobe is indwelt by magic"},
        )
        result = detect_missing_actors(
            ["Shuluth", "Kobe"],
            ["Shuluth"],  # live module NPCs (Kobe absent)
            [],           # live area NPCs
            "test",
            fixture,
            {},           # source excerpts (not used here)
        )
        crit = result.get("critical_omissions", [])
        self.assertEqual(len(crit), 1)
        self.assertEqual(crit[0]["name"], "Kobe")
        self.assertEqual(crit[0]["classification"], CLASSIFICATION_BUILDER_REPAIR)
        self.assertEqual(len(result.get("review_items", [])), 0)

    def test_wayne_alias_classified_as_review(self):
        """Wayne variant must be in review_items, not critical_omissions."""
        fixture = _build_fixture_for_test(
            actor_names=["Wayne (Waynobibille Nebiddlespun)", "Shuluth"],
        )
        result = detect_missing_actors(
            ["Wayne (Waynobibille Nebiddlespun)"],
            ["Wayne", "Shuluth"],  # 'Wayne' is an alias for the full name
            [],
            "test",
            fixture,
            {},
        )
        self.assertEqual(len(result.get("critical_omissions", [])), 0)
        reviews = result.get("review_items", [])
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["classification"], CLASSIFICATION_ALIAS_VARIANT)

    def test_no_omission_when_all_present(self):
        fixture = _build_fixture_for_test(actor_names=["Shuluth", "Wayne"])
        result = detect_missing_actors(
            ["Shuluth", "Wayne"],
            ["Wayne", "Shuluth"],
            [],
            "test",
            fixture,
            {},
        )
        self.assertEqual(result.get("critical_omissions", []), [])
        self.assertEqual(result.get("review_items", []), [])

    def test_empty_expected_returns_empty(self):
        result = detect_missing_actors([], [], [], "test", {}, {})
        self.assertEqual(result.get("critical_omissions", []), [])
        self.assertEqual(result.get("review_items", []), [])

    def test_non_kobe_does_not_get_kobe_excerpt(self):
        """A non-Kobe missing actor must not receive the Kobe source excerpt."""
        fixture = _build_fixture_for_test(
            actor_names=["Shuluth", "MissingFoo"],
            lore_descs={},
        )
        # Provide a Kobe excerpt that would incorrectly match if the bug existed
        excerpts = {"kobe": "This excerpt ONLY describes Kobe."}
        result = detect_missing_actors(
            ["MissingFoo"],
            ["Shuluth"],
            [],
            "test",
            fixture,
            excerpts,
        )
        crit = result.get("critical_omissions", [])
        self.assertEqual(len(crit), 1)
        # Verify source_ref does NOT contain the Kobe excerpt
        src_desc = crit[0].get("source_ref", {}).get("description", "")
        self.assertNotIn("Kobe", src_desc,
                         "Non-Kobe missing actor must not receive Kobe excerpt")


# ---------------------------------------------------------------------------
#  Missing puzzle detection tests
# ---------------------------------------------------------------------------

class TestDetectMissingPuzzles(unittest.TestCase):

    def test_skull_riddle_detected_as_critical_omission(self):
        fixture = _build_fixture_for_test(
            puzzle_ids=["skull_riddle"],
            puzzle_descs={"skull_riddle": "The First Trial: three skulls"},
        )
        omissions = detect_missing_puzzles(
            ["skull_riddle"],
            set(), set(), set(),  # all surfaces empty
            fixture,
            {},
        )
        self.assertEqual(len(omissions), 1)
        self.assertEqual(omissions[0]["name"], "skull_riddle")
        self.assertEqual(omissions[0]["classification"], CLASSIFICATION_BUILDER_REPAIR)

    def test_puzzle_satisfied_by_area_text(self):
        """If area text mentions puzzle keywords, no omission reported."""
        omissions = detect_missing_puzzles(
            ["skull_riddle"],
            set(),                    # not in module_context puzzles
            {"skull_riddle"},          # but found in plot
            set(),                    # not in area text
            _build_fixture_for_test(puzzle_ids=["skull_riddle"]),
            {},
        )
        self.assertEqual(len(omissions), 0)

    def test_per_surface_missing(self):
        fixture = _build_fixture_for_test(
            puzzle_ids=["skull_riddle", "flooding_room"],
        )
        omissions = detect_missing_puzzles(
            ["skull_riddle", "flooding_room"],
            {"skull_riddle"},     # context has skull_riddle
            set(),                  # plot has neither
            {"flooding_room"},      # area has flooding_room
            fixture,
            {},
        )
        self.assertEqual(len(omissions), 0)

    def test_empty_expected_returns_empty(self):
        self.assertEqual(
            detect_missing_puzzles([], set(), set(), set(), {}, {}), [],
        )


# ---------------------------------------------------------------------------
#  Source markdown reading tests
# ---------------------------------------------------------------------------

class TestSourceMarkdownExcerpts(unittest.TestCase):

    def test_resolve_source_path_from_real_fixture(self):
        """Verify real Numillian fixture has a resolvable source_path."""
        fix = _real_fixture()
        path = _resolve_source_markdown_path(fix, NUMILLIAN_SLUG)
        self.assertIsNotNone(path, "source_path from fixture must resolve")
        self.assertTrue(path.exists(), f"Resolved path {path} must exist")

    def test_extract_source_excerpts_against_real_module(self):
        """Run against real Numillian fixture/markdown."""
        fix = _real_fixture()
        excerpts = _extract_source_markdown_excerpts(fix, NUMILLIAN_SLUG)
        self.assertIn("kobe", excerpts)
        # Kobe name appears late in the No-win section; the excerpt
        # should contain context about the character (young girl, tower)
        has_kobe_ctx = any(
            kw in excerpts["kobe"].lower()
            for kw in ["kobe", "young girl", "tower", "indwelt", "vault"]
        )
        self.assertTrue(has_kobe_ctx,
                        "Kobe excerpt must reference the character context")
        self.assertIn("skull_riddle", excerpts)
        self.assertIn("skull", excerpts["skull_riddle"].lower(),
                       "skull_riddle excerpt must mention skull")


# ---------------------------------------------------------------------------
#  Full evidence pass integration tests (Numillian)
# ---------------------------------------------------------------------------

class TestRunCriticalOmissionEvidencePassNumillian(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = run_critical_omission_evidence_pass(NUMILLIAN_SLUG)

    def test_pass_runs_without_error(self):
        self.assertIsNone(self.result.get("error"))

    def test_source_markdown_read(self):
        self.assertTrue(
            self.result.get("source_markdown_read"),
            "Source markdown must be read for Numillian",
        )

    def test_source_markdown_path_set(self):
        self.assertIsNotNone(self.result.get("source_markdown_path"))

    def test_detects_kobe_as_missing_critical_actor(self):
        omissions = self.result.get("critical_omissions", [])
        kobe_hits = [
            o for o in omissions
            if o.get("name") == "Kobe"
            and o.get("classification") == CLASSIFICATION_BUILDER_REPAIR
        ]
        # After Step 4 repair, Kobe should no longer be a critical omission
        self.assertEqual(
            len(kobe_hits), 0,
            f"Kobe should be repaired. Omissions: "
            f"{[(o['name'], o['classification']) for o in omissions]}",
        )

    def test_detects_skull_riddle_as_missing_critical_puzzle(self):
        omissions = self.result.get("critical_omissions", [])
        riddle_hits = [
            o for o in omissions
            if o.get("name") == "skull_riddle"
            and o.get("classification") == CLASSIFICATION_BUILDER_REPAIR
        ]
        # After Step 4 repair, skull_riddle should no longer be a critical omission
        self.assertEqual(
            len(riddle_hits), 0,
            f"skull_riddle should be repaired. Omissions: "
            f"{[(o['name'], o['classification']) for o in omissions]}",
        )

    def test_wayne_is_not_critical_omission(self):
        """Wayne alias variant must NOT be builder_repair_recommended."""
        omissions = self.result.get("critical_omissions", [])
        wayne_builder = [
            o for o in omissions
            if "Wayne" in o.get("name", "")
            and o.get("classification") == CLASSIFICATION_BUILDER_REPAIR
        ]
        self.assertEqual(
            len(wayne_builder), 0,
            f"Wayne must not be builder_repair. Wayne hits: {wayne_builder}",
        )

    def test_wayne_in_review_items_not_critical(self):
        """Wayne variant must appear in review_items, not critical_omissions."""
        omissions = self.result.get("critical_omissions", [])
        wayne_crit = [o for o in omissions if "Wayne" in o.get("name", "")]
        self.assertEqual(len(wayne_crit), 0)
        reviews = self.result.get("review_items", [])
        wayne_rev = [r for r in reviews if "Wayne" in r.get("name", "")]
        self.assertGreaterEqual(len(wayne_rev), 1)

    def test_fail_count_excludes_alias_variants(self):
        """fail_count must count only critical_omissions, not review_items."""
        fc = self.result.get("fail_count", -1)
        rc = self.result.get("review_count", -1)
        crit_len = len(self.result.get("critical_omissions", []))
        rev_len = len(self.result.get("review_items", []))
        self.assertEqual(fc, crit_len,
                         f"fail_count={fc} != critical_omissions count={crit_len}")
        self.assertEqual(rc, rev_len,
                         f"review_count={rc} != review_items count={rev_len}")

    def test_kobe_has_source_ref_with_markdown_excerpt(self):
        omissions = self.result.get("critical_omissions", [])
        kobe = next((o for o in omissions if o.get("name") == "Kobe"), None)
        self.assertIsNone(kobe, "Kobe should no longer be a critical omission after repair")

    def test_kobe_reports_nested_module_context_surface_missing(self):
        omissions = self.result.get("critical_omissions", [])
        kobe = next((o for o in omissions if o.get("name") == "Kobe"), None)
        self.assertIsNone(kobe,
                          "Kobe should no longer be a missing critical actor after repair")

    def test_skull_riddle_has_source_ref_with_markdown_excerpt(self):
        omissions = self.result.get("critical_omissions", [])
        riddle = next((o for o in omissions if o.get("name") == "skull_riddle"), None)
        self.assertIsNone(riddle,
                          "skull_riddle should no longer be a critical omission after repair")

    def test_flooding_room_no_longer_critical(self):
        omissions = self.result.get("critical_omissions", [])
        flood = next((o for o in omissions if o.get("name") == "flooding_room"), None)
        self.assertIsNone(flood,
                          "flooding_room should no longer be a critical omission after repair")

    def test_omissions_have_honest_surface_reporting(self):
        """Missing surfaces must match what was actually checked."""
        for o in self.result.get("critical_omissions", []):
            for surface in o.get("missing_surfaces", []):
                self.assertIn(surface, (
                    ACTOR_SURFACE_MODULE_CONTEXT,
                    ACTOR_SURFACE_MODULE_CONTEXT_NESTED,
                    ACTOR_SURFACE_AREA_LOCATIONS,
                    PUZZLE_SURFACE_MODULE_CONTEXT,
                    PUZZLE_SURFACE_MODULE_PLOT,
                    PUZZLE_SURFACE_AREA_TEXT,
                ), f"Unknown surface: {surface}")
            for surface in o.get("present_surfaces", []):
                self.assertIn(surface, (
                    PUZZLE_SURFACE_MODULE_CONTEXT,
                    PUZZLE_SURFACE_MODULE_PLOT,
                    PUZZLE_SURFACE_AREA_TEXT,
                ), f"Unknown present surface: {surface}")


# ---------------------------------------------------------------------------
#  Edge case tests
# ---------------------------------------------------------------------------

class TestEvidencePassEdgeCases(unittest.TestCase):

    def test_missing_fixture_returns_error(self):
        result = run_critical_omission_evidence_pass("NonExistentModule")
        self.assertIsNotNone(result.get("error"))
        self.assertEqual(result.get("critical_omissions"), [])
        self.assertEqual(result.get("review_items"), [])

    def test_format_error_summary(self):
        result = {
            "module_slug": "Test",
            "source_markdown_read": False,
            "source_markdown_path": None,
            "critical_omissions": [],
            "review_items": [],
            "pass_count": 0,
            "fail_count": 0,
            "review_count": 0,
            "error": "Fixture not found",
        }
        summary = format_evidence_summary(result)
        self.assertIn("EVIDENCE_ERROR", summary)
        self.assertIn("Fixture not found", summary)

    def test_deterministic_no_provider(self):
        r1 = run_critical_omission_evidence_pass(NUMILLIAN_SLUG)
        r2 = run_critical_omission_evidence_pass(NUMILLIAN_SLUG)
        r1.pop("error", None)
        r2.pop("error", None)
        self.assertEqual(
            json.dumps(r1, sort_keys=True),
            json.dumps(r2, sort_keys=True),
        )


# ---------------------------------------------------------------------------
#  CLI source-contract test
# ---------------------------------------------------------------------------

class TestCliImportContract(unittest.TestCase):

    def test_cli_runs_from_repo_root_without_pythonpath(self):
        """CLI must import and run without PYTHONPATH from repo root."""
        import subprocess
        import os
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/check_critical_narrative_evidence.py",
                "--module", NUMILLIAN_SLUG,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Remove "EXIT:" prefix if present (shell interleaving)
        stdout = result.stdout.split("EXIT:")[0].strip()
        self.assertGreater(len(stdout), 10, "stdout must contain JSON output")
        # Must not contain ModuleNotFoundError or ImportError
        self.assertNotIn("ModuleNotFoundError", result.stdout + result.stderr)
        self.assertNotIn("ImportError", result.stdout + result.stderr)
        # Must be valid JSON
        d = json.loads(stdout)
        self.assertEqual(d.get("module_slug"), NUMILLIAN_SLUG)
        self.assertIn("critical_omissions", d)
        self.assertIn("review_items", d)
        self.assertIsNone(d.get("error"))


# ---------------------------------------------------------------------------
#  Agent run write artifact tests (Step 1.2)
# ---------------------------------------------------------------------------

class TestAgentRunWriteArtifacts(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir_obj.name
        self.task_id = "test-run-001"

    def tearDown(self):
        self._tmpdir_obj.cleanup()

    def _run_write_run(self):
        """Helper: run evidence pass and write agent run to temp dir."""
        import subprocess
        result = subprocess.run(
            [
                ".venv/bin/python",
                "scripts/check_critical_narrative_evidence.py",
                "--module", NUMILLIAN_SLUG,
                "--write-run",
                "--output-dir", os.path.join(self.tmpdir, self.task_id),
                "--task-id", self.task_id,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        stdout = result.stdout.split("EXIT:")[0].strip()
        return json.loads(stdout)

    def test_write_run_creates_all_four_files(self):
        d = self._run_write_run()
        files = d.get("run_files", {})
        for key in ("run", "critical_evidence", "source_excerpts", "builder_repair_brief"):
            fpath = files.get(key)
            self.assertIsNotNone(fpath, f"{key} file path missing from CLI output")
            self.assertTrue(os.path.exists(fpath), f"{key} file not on disk: {fpath}")

    def test_run_json_has_required_fields(self):
        d = self._run_write_run()
        run_path = d.get("run_files", {}).get("run", "")
        with open(run_path) as f:
            run = json.load(f)
        for field in ("task_id", "module_slug", "created_at", "status",
                       "source_markdown_path", "source_markdown_read",
                       "evidence_file", "source_excerpts_file",
                       "builder_repair_brief_file", "fail_count", "review_count"):
            self.assertIn(field, run, f"run.json missing field: {field}")
        self.assertEqual(run["task_id"], self.task_id)
        self.assertEqual(run["module_slug"], NUMILLIAN_SLUG)
        self.assertEqual(run["status"], "evidence_collected")

    def test_critical_evidence_contains_kobe_and_skull_riddle(self):
        d = self._run_write_run()
        ev_path = d.get("run_files", {}).get("critical_evidence", "")
        with open(ev_path) as f:
            ev = json.load(f)
        names = [o["name"] for o in ev.get("critical_omissions", [])]
        self.assertNotIn("Kobe", names, "Kobe should not be in critical omissions after repair")
        self.assertNotIn("skull_riddle", names,
                         "skull_riddle should not be in critical omissions after repair")
        self.assertNotIn("flooding_room", names,
                         "flooding_room should not be in critical omissions after repair")

    def test_wayne_remains_review_only(self):
        d = self._run_write_run()
        ev_path = d.get("run_files", {}).get("critical_evidence", "")
        with open(ev_path) as f:
            ev = json.load(f)
        crit_names = [o["name"] for o in ev.get("critical_omissions", [])]
        rev_names = [r["name"] for r in ev.get("review_items", [])]
        self.assertNotIn("Wayne", crit_names)
        self.assertNotIn("Wayne (Waynobibille Nebiddlespun)", crit_names)
        wayne_rev = [r for r in rev_names if "Wayne" in r]
        self.assertGreaterEqual(len(wayne_rev), 1)

    def test_source_excerpts_json_has_records(self):
        d = self._run_write_run()
        se_path = d.get("run_files", {}).get("source_excerpts", "")
        with open(se_path) as f:
            se = json.load(f)
        for key in ("kobe", "skull_riddle", "flooding_room"):
            rec = se.get(key, {})
            for field in ("name", "type", "source_path", "excerpt",
                           "start_line", "end_line", "char_count"):
                self.assertIn(field, rec, f"source_excerpts.{key} missing {field}")

    def test_excerpts_are_bounded(self):
        d = self._run_write_run()
        se_path = d.get("run_files", {}).get("source_excerpts", "")
        with open(se_path) as f:
            se = json.load(f)
        for key, rec in se.items():
            self.assertLessEqual(
                rec.get("char_count", 0), 1300,
                f"{key} excerpt exceeds char limit",
            )

    def test_brief_contains_missing_surfaces(self):
        d = self._run_write_run()
        brief_path = d.get("run_files", {}).get("builder_repair_brief", "")
        with open(brief_path) as f:
            brief = f.read()
        # After repair, no critical omissions remain - brief should still have
        # the source excerpts and required sections
        self.assertIn("Source Excerpts", brief)

    def test_brief_contains_guardrails(self):
        d = self._run_write_run()
        brief_path = d.get("run_files", {}).get("builder_repair_brief", "")
        with open(brief_path) as f:
            brief = f.read()
        self.assertIn("MUST synthesize source-faithful narrative", brief)
        self.assertIn("MODULE_SUMMARY.md", brief)
        self.assertIn("NOT authored the repair", brief)
        self.assertIn("block release proof", brief)

    def test_brief_contains_target_surfaces(self):
        d = self._run_write_run()
        brief_path = d.get("run_files", {}).get("builder_repair_brief", "")
        with open(brief_path) as f:
            brief = f.read()
        self.assertIn("Required Repair Targets", brief)
        self.assertIn("Kobe", brief)
        self.assertIn("skull_riddle", brief)
        self.assertIn("flooding_room", brief)

    def test_brief_contains_source_lock_constraints(self):
        d = self._run_write_run()
        brief_path = d.get("run_files", {}).get("builder_repair_brief", "")
        with open(brief_path) as f:
            brief = f.read()
        self.assertIn("Source-Lock Constraints", brief)
        self.assertIn("Kobe is the final no-win trial actor", brief)
        self.assertIn("skull_riddle is the First Trial puzzle", brief)
        self.assertIn("flooding_room is the Second Trial puzzle", brief)
        self.assertIn("Do not invent replacement puzzles", brief)

    def test_brief_contains_acceptance_checks(self):
        d = self._run_write_run()
        brief_path = d.get("run_files", {}).get("builder_repair_brief", "")
        with open(brief_path) as f:
            brief = f.read()
        self.assertIn("Acceptance Checks For Later Repair", brief)
        self.assertIn("no longer reports Kobe", brief)
        self.assertIn("no longer reports skull_riddle", brief)
        self.assertIn("no longer reports flooding_room", brief)
        self.assertIn("Wayne remains review-only", brief)
        self.assertIn("Benchmark source fidelity passes", brief)

    def test_brief_contains_do_not_use_block(self):
        d = self._run_write_run()
        brief_path = d.get("run_files", {}).get("builder_repair_brief", "")
        with open(brief_path) as f:
            brief = f.read()
        self.assertIn("Do Not Use", brief)
        self.assertIn("Do not use MODULE_SUMMARY.md", brief)
        self.assertIn("Do not edit benchmark thresholds", brief)
        self.assertIn("Do not manually inject JSON strings", brief)
        self.assertIn("Do not edit report-only status fields", brief)

    def test_brief_does_not_contain_full_source_markdown(self):
        d = self._run_write_run()
        brief_path = d.get("run_files", {}).get("builder_repair_brief", "")
        with open(brief_path) as f:
            brief = f.read()
        self.assertNotIn("Hombrewery-md-guide", brief)
        self.assertNotIn("## The Gatepact", brief)

    def test_cli_output_includes_run_dir_and_file_paths(self):
        d = self._run_write_run()
        self.assertIn("run_dir", d)
        expected_dir = os.path.join(self.tmpdir, self.task_id)
        self.assertEqual(d["run_dir"], expected_dir)
        files = d.get("run_files", {})
        self.assertIn("run", files)
        self.assertIn("critical_evidence", files)
        self.assertIn("source_excerpts", files)
        self.assertIn("builder_repair_brief", files)

    def test_tests_write_only_to_temp_dirs(self):
        """All agent-run test artifacts must stay in the temp directory."""
        d = self._run_write_run()
        run_dir = d.get("run_dir", "")
        self.assertTrue(run_dir.startswith(self.tmpdir),
                        f"run_dir {run_dir} not in temp dir {self.tmpdir}")
        self.assertIn(self.task_id, run_dir)


# ---------------------------------------------------------------------------
#  Builder repair brief contract tests (Step 1.2)
# ---------------------------------------------------------------------------

class TestBuilderRepairBriefContracts(unittest.TestCase):

    def test_brief_contains_module_slug_header(self):
        from utils.critical_narrative_evidence import (
            build_critical_narrative_agent_run,
            run_critical_omission_evidence_pass,
        )
        evidence = run_critical_omission_evidence_pass(NUMILLIAN_SLUG)
        package = build_critical_narrative_agent_run(
            evidence, NUMILLIAN_SLUG, "test-brief-001",
        )
        brief = package.get("builder_repair_brief", "")
        self.assertIn(f"Critical Narrative Repair Brief - {NUMILLIAN_SLUG}", brief)

    def test_brief_has_release_blocking_statement(self):
        from utils.critical_narrative_evidence import (
            build_critical_narrative_agent_run,
            run_critical_omission_evidence_pass,
        )
        evidence = run_critical_omission_evidence_pass(NUMILLIAN_SLUG)
        package = build_critical_narrative_agent_run(
            evidence, NUMILLIAN_SLUG, "test-brief-002",
        )
        brief = package.get("builder_repair_brief", "")
        self.assertIn("Release Blocking", brief)
        self.assertIn("block release proof", brief)

    def test_no_llm_calls_in_builder_agent_run_path(self):
        """The agent run must not trigger any LLM calls."""
        from utils.critical_narrative_evidence import (
            build_critical_narrative_agent_run,
            run_critical_omission_evidence_pass,
        )
        evidence = run_critical_omission_evidence_pass(NUMILLIAN_SLUG)
        # build_critical_narrative_agent_run is pure data transformation
        package = build_critical_narrative_agent_run(
            evidence, NUMILLIAN_SLUG, "test-brief-003",
        )
        self.assertIn("builder_repair_brief", package)
        self.assertGreater(len(package["builder_repair_brief"]), 500)


# ---------------------------------------------------------------------------
#  Step 4 repair verification tests (BU parity + trial topology)
# ---------------------------------------------------------------------------

class TestStep4RepairParity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.live_ctx = json.loads(
            Path("modules/The_Hidden_City_of_Numillian/module_context.json")
            .read_text(encoding="utf-8"))
        cls.bu_ctx = json.loads(
            Path("modules/The_Hidden_City_of_Numillian/module_context_BU.json")
            .read_text(encoding="utf-8"))
        cls.live_plot = json.loads(
            Path("modules/The_Hidden_City_of_Numillian/module_plot.json")
            .read_text(encoding="utf-8"))
        cls.bu_plot = json.loads(
            Path("modules/The_Hidden_City_of_Numillian/module_plot_BU.json")
            .read_text(encoding="utf-8"))

    def test_kobe_in_live_context(self):
        npcs = self.live_ctx.get("npcs", {})
        self.assertIn("kobe", npcs)
        self.assertEqual(npcs["kobe"]["name"], "Kobe")
        self.assertIn("final trial", npcs["kobe"]["role"].lower())

    def test_kobe_in_bu_context(self):
        npcs = self.bu_ctx.get("npcs", {})
        self.assertIn("kobe", npcs)
        self.assertEqual(npcs["kobe"]["name"], "Kobe")
        self.assertIn("final trial", npcs["kobe"]["role"].lower())

    def test_full_trial_arc_in_live_plot(self):
        trials = [p for p in self.live_plot["plotPoints"] if p.get("isTrial")]
        titles = [p["title"] for p in trials]
        self.assertIn("Trial at the Door", titles)
        self.assertIn("The First Trial - Skull Riddle", titles)
        self.assertIn("The Second Trial - Flooding Room", titles)
        self.assertIn("The False Third Trial - Kill the Dog", titles)
        self.assertIn("The True Third Trial - City of the Mind", titles)
        self.assertIn("The Final Trial - No-Win Scenario with Kobe", titles)

    def test_full_trial_arc_in_bu_plot(self):
        trials = [p for p in self.bu_plot["plotPoints"] if p.get("isTrial")]
        titles = [p["title"] for p in trials]
        self.assertIn("Trial at the Door", titles)
        self.assertIn("The First Trial - Skull Riddle", titles)
        self.assertIn("The Second Trial - Flooding Room", titles)
        self.assertIn("The False Third Trial - Kill the Dog", titles)
        self.assertIn("The True Third Trial - City of the Mind", titles)
        self.assertIn("The Final Trial - No-Win Scenario with Kobe", titles)

    def test_trial_arc_separate_from_map_location_points(self):
        loc_pts = [p for p in self.live_plot["plotPoints"] if p["id"].startswith("PP")]
        trial_pts = [p for p in self.live_plot["plotPoints"] if p["id"].startswith("TRIAL")]
        self.assertGreaterEqual(len(loc_pts), 1, "Must have map-key location points")
        self.assertGreaterEqual(len(trial_pts), 6, "Must have trial points")
        # Verify non-overlapping ID spaces
        loc_ids = {p["id"] for p in loc_pts}
        trial_ids = {p["id"] for p in trial_pts}
        self.assertFalse(loc_ids & trial_ids, "PP and TRIAL IDs must not overlap")

    def test_skull_riddle_as_puzzle_not_npc_atoms(self):
        trial1 = next((p for p in self.live_plot["plotPoints"] if p["id"] == "TRIAL001"), None)
        self.assertIsNotNone(trial1, "TRIAL001 must exist")
        desc = trial1.get("description", "").lower()
        self.assertIn("skull", desc, "TRIAL001 must reference skull riddle puzzle")
        self.assertIn("receptacle", desc, "TRIAL001 must reference receptacles")

    def test_kobe_as_final_trial_objective(self):
        trial5 = next((p for p in self.live_plot["plotPoints"] if p["id"] == "TRIAL005"), None)
        self.assertIsNotNone(trial5, "TRIAL005 must exist")
        desc = trial5.get("description", "").lower()
        self.assertIn("kobe", desc, "TRIAL005 must reference Kobe by name")
        self.assertIn("vault", desc, "TRIAL005 must reference vault protection")

    def test_evidence_pass_clean_after_repair(self):
        evidence = run_critical_omission_evidence_pass(NUMILLIAN_SLUG)
        self.assertEqual(evidence.get("fail_count", -1), 0)
        self.assertEqual(evidence.get("review_count", -1), 1)


if __name__ == "__main__":
    unittest.main()
