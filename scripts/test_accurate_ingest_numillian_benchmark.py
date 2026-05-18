#!/usr/bin/env python3
"""Tests for accurate-ingest benchmark fixture, runner, and gate composition."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from utils.toolkit_source_fidelity_benchmark import (
    STATUS_PASS, STATUS_DEGRADED, STATUS_BLOCKED, STATUS_UNKNOWN,
    worst_status, validate_benchmark_fixture, load_benchmark_fixture,
    make_score_result, derive_category_status, compute_aggregate_status,
    build_aggregate_result,
)
from utils.toolkit_publication_gate_composer import (
    compose_publication_gate, compose_publishability_from_report,
)


# ---------------------------------------------------------------------------
# Section A: Benchmark Fixture Schema and Validation
# ---------------------------------------------------------------------------

class TestBenchmarkFixtureValidation(unittest.TestCase):
    """Tests for validate_benchmark_fixture() and load_benchmark_fixture()."""

    def make_valid_fixture(self) -> Dict[str, Any]:
        return {
            "benchmark_version": "test.v1",
            "module_slug": "TestModule",
            "expectations": {
                "npc_preservation": {},
                "location_preservation": {},
                "puzzle_preservation": {},
                "lore_preservation": {},
                "tone_preservation": {},
            },
            "publication_thresholds": {
                "pass": {
                    "npc_preservation": 1.0,
                    "location_preservation": 1.0,
                    "puzzle_preservation": 1.0,
                    "lore_preservation": 1.0,
                    "tone_preservation": "quirky",
                },
                "degraded": {
                    "npc_preservation": 0.85,
                    "location_preservation": 0.85,
                    "puzzle_preservation": 0.67,
                    "lore_preservation": 0.5,
                    "tone_preservation": "generic",
                },
            },
        }

    def test_valid_fixture_passes(self):
        errors = validate_benchmark_fixture(self.make_valid_fixture())
        self.assertEqual(errors, [])

    def test_missing_top_level_keys(self):
        fixture = {}
        errors = validate_benchmark_fixture(fixture)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("benchmark_version" in e for e in errors))

    def test_missing_expectation_categories(self):
        fixture = self.make_valid_fixture()
        del fixture["expectations"]["npc_preservation"]
        errors = validate_benchmark_fixture(fixture)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("npc_preservation" in e for e in errors))

    def test_pass_threshold_gte_degraded(self):
        fixture = self.make_valid_fixture()
        fixture["publication_thresholds"]["pass"]["npc_preservation"] = 0.5
        fixture["publication_thresholds"]["degraded"]["npc_preservation"] = 0.9
        errors = validate_benchmark_fixture(fixture)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("must be >= degraded" in e for e in errors))

    def test_load_missing_file_returns_none(self):
        result = load_benchmark_fixture(Path("/nonexistent/benchmark.json"))
        self.assertIsNone(result)

    def test_load_valid_file(self):
        fixture = self.make_valid_fixture()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(fixture, f)
            p = f.name
        result = load_benchmark_fixture(Path(p))
        self.assertIsNotNone(result)
        self.assertEqual(result["benchmark_version"], "test.v1")
        Path(p).unlink(missing_ok=True)

    def test_load_invalid_json_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            p = f.name
        result = load_benchmark_fixture(Path(p))
        self.assertIsNone(result)
        Path(p).unlink(missing_ok=True)

    def test_numeric_threshold_in_range(self):
        fixture = self.make_valid_fixture()
        fixture["publication_thresholds"]["pass"]["npc_preservation"] = 2.0
        errors = validate_benchmark_fixture(fixture)
        self.assertGreater(len(errors), 0)


# ---------------------------------------------------------------------------
# Section B: Source Fidelity Scoring Primitives
# ---------------------------------------------------------------------------

class TestWorstStatus(unittest.TestCase):
    def test_blocked_wins(self):
        self.assertEqual(worst_status(STATUS_PASS, STATUS_BLOCKED), STATUS_BLOCKED)
        self.assertEqual(worst_status(STATUS_DEGRADED, STATUS_BLOCKED), STATUS_BLOCKED)
        self.assertEqual(worst_status(STATUS_PASS, STATUS_BLOCKED, STATUS_DEGRADED), STATUS_BLOCKED)

    def test_degraded_over_pass(self):
        self.assertEqual(worst_status(STATUS_PASS, STATUS_DEGRADED), STATUS_DEGRADED)

    def test_pass_over_unknown(self):
        self.assertEqual(worst_status(STATUS_UNKNOWN, STATUS_PASS), STATUS_PASS)

    def test_empty_returns_unknown(self):
        self.assertEqual(worst_status(), STATUS_UNKNOWN)

    def test_all_same(self):
        self.assertEqual(worst_status(STATUS_PASS, STATUS_PASS, STATUS_PASS), STATUS_PASS)

    def test_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            worst_status("invalid")


class TestDeriveCategoryStatus(unittest.TestCase):
    def test_numeric_pass(self):
        self.assertEqual(derive_category_status(1.0, 0.9, 0.7, "npc"), STATUS_PASS)
        self.assertEqual(derive_category_status(0.9, 0.9, 0.7, "npc"), STATUS_PASS)

    def test_numeric_degraded(self):
        self.assertEqual(derive_category_status(0.85, 0.9, 0.7, "npc"), STATUS_DEGRADED)
        self.assertEqual(derive_category_status(0.7, 0.9, 0.7, "npc"), STATUS_DEGRADED)

    def test_numeric_blocked(self):
        self.assertEqual(derive_category_status(0.5, 0.9, 0.7, "npc"), STATUS_BLOCKED)

    def test_numeric_unknown_on_none(self):
        self.assertEqual(derive_category_status(None, 0.9, 0.7, "npc"), STATUS_UNKNOWN)

    def test_tone_exact_match_pass(self):
        self.assertEqual(derive_category_status("quirky", "quirky", "generic", "tone_preservation"), STATUS_PASS)

    def test_tone_blocked_replacement(self):
        self.assertEqual(derive_category_status("generic", "quirky", "generic", "tone_preservation"), STATUS_BLOCKED)

    def test_tone_neither_pass_nor_blocked(self):
        self.assertEqual(derive_category_status("other_style", "quirky", "generic", "tone_preservation"), STATUS_DEGRADED)


class TestScoreResultPrimitives(unittest.TestCase):
    def test_make_score_result_shape(self):
        r = make_score_result("test_category", STATUS_PASS, score=1.0, expected=1.0, actual="5/5")
        self.assertEqual(r["category"], "test_category")
        self.assertEqual(r["status"], STATUS_PASS)
        self.assertEqual(r["score"], 1.0)
        self.assertEqual(r["details"], {})

    def test_compute_aggregate_all_pass(self):
        results = [
            make_score_result("a", STATUS_PASS),
            make_score_result("b", STATUS_PASS),
        ]
        self.assertEqual(compute_aggregate_status(results), STATUS_PASS)

    def test_aggregate_worst_wins(self):
        results = [
            make_score_result("a", STATUS_PASS),
            make_score_result("b", STATUS_BLOCKED),
            make_score_result("c", STATUS_DEGRADED),
        ]
        self.assertEqual(compute_aggregate_status(results), STATUS_BLOCKED)

    def test_empty_aggregate_unknown(self):
        self.assertEqual(compute_aggregate_status([]), STATUS_UNKNOWN)

    def test_build_aggregate_result_shape(self):
        results = [make_score_result("a", STATUS_DEGRADED)]
        ar = build_aggregate_result(results)
        self.assertEqual(ar["source_fidelity_status"], STATUS_DEGRADED)
        self.assertTrue(ar["degraded"])
        self.assertFalse(ar["passed"])
        self.assertEqual(len(ar["category_results"]), 1)


# ---------------------------------------------------------------------------
# Section C: Publication Gate Composition
# ---------------------------------------------------------------------------

class TestPublicationGateComposition(unittest.TestCase):
    def test_all_pass(self):
        r = compose_publication_gate("pass", "pass", "pass")
        self.assertEqual(r["final_status"], STATUS_PASS)
        self.assertTrue(r["publishable"])

    def test_fidelity_degraded_warning(self):
        r = compose_publication_gate("pass", "pass", "degraded")
        self.assertEqual(r["final_status"], STATUS_DEGRADED)
        self.assertGreater(len(r["warnings"]), 0)

    def test_fidelity_blocked(self):
        r = compose_publication_gate("pass", "pass", "blocked")
        self.assertEqual(r["final_status"], STATUS_BLOCKED)
        self.assertGreater(len(r["blockers"]), 0)

    def test_ready_fail_blocked(self):
        r = compose_publication_gate("fail", "pass", "pass")
        self.assertEqual(r["final_status"], STATUS_BLOCKED)

    def test_publishable_fail_blocked(self):
        r = compose_publication_gate("pass", "fail", "pass")
        self.assertEqual(r["final_status"], STATUS_BLOCKED)

    def test_fidelity_unknown_non_blocking(self):
        r = compose_publication_gate("pass", "pass", "unknown")
        self.assertEqual(r["final_status"], STATUS_PASS)
        self.assertEqual(len(r["blockers"]), 0)

    def test_feature_flag_disabled_treats_blocked_as_unknown(self):
        r = compose_publication_gate("pass", "pass", "blocked", enable_fidelity_flag=False)
        self.assertEqual(r["final_status"], STATUS_PASS)
        self.assertEqual(r["source_fidelity_status_effective"], STATUS_UNKNOWN)

    def test_waiver_accepted_for_degraded(self):
        r = compose_publication_gate("pass", "pass", "degraded", waiver_active=True)
        self.assertTrue(r["waiver_applied"])
        self.assertEqual(r["final_status"], STATUS_PASS)

    def test_waiver_does_not_override_blocked_fidelity(self):
        r = compose_publication_gate("pass", "pass", "blocked", waiver_active=True)
        self.assertEqual(r["final_status"], STATUS_BLOCKED)
        self.assertFalse(r["waiver_applied"])

    def test_waiver_does_not_override_readiness_fail(self):
        r = compose_publication_gate("fail", "pass", "degraded", waiver_active=True)
        self.assertEqual(r["final_status"], STATUS_BLOCKED)

    def test_compose_publishability_from_report_shape(self):
        r = compose_publishability_from_report("pass", "pass", "blocked")
        self.assertIn("source_fidelity_status", r)
        self.assertIn("source_fidelity_blockers", r)
        self.assertIn("source_fidelity_warnings", r)
        self.assertIn("final_publishable_status", r)
        self.assertEqual(r["final_publishable_status"], "blocked")

    def test_status_from_boolean(self):
        from utils.toolkit_publication_gate_composer import status_from_boolean
        self.assertEqual(status_from_boolean(True), "pass")
        self.assertEqual(status_from_boolean(False), "fail")


# ---------------------------------------------------------------------------
# Section D: Feature Flag Integration
# ---------------------------------------------------------------------------

class TestFeatureFlagIntegration(unittest.TestCase):
    def test_flag_disabled_fidelity_becomes_unknown(self):
        """When enable_fidelity_flag=False, blocked fidelity is treated as unknown."""
        r = compose_publication_gate("pass", "pass", "blocked", enable_fidelity_flag=False)
        self.assertEqual(r["source_fidelity_status_effective"], STATUS_UNKNOWN)
        self.assertEqual(r["final_status"], STATUS_PASS)

    def test_flag_enabled_fidelity_active(self):
        r = compose_publication_gate("pass", "pass", "blocked", enable_fidelity_flag=True)
        self.assertEqual(r["source_fidelity_status_effective"], STATUS_BLOCKED)
        self.assertEqual(r["final_status"], STATUS_BLOCKED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
