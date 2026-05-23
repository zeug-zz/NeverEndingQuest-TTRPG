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


# ---------------------------------------------------------------------------
# Task 0.4: Numillian Benchmark Puzzle-Preservation Blocker Documentation
#   Source-contract tests documenting that skull_riddle and
#   kill_the_dog_mindscape are currently-blocked puzzles in the benchmark.
# ---------------------------------------------------------------------------

class TestNumillianPuzzleBlockerDocumentation(unittest.TestCase):
    """Reads the authoritative benchmark fixture and locks expected puzzle IDs."""

    BENCHMARK_PATH = Path("data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json")

    def setUp(self) -> None:
        self.fixture = load_benchmark_fixture(self.BENCHMARK_PATH)
        if self.fixture is None:
            self.skipTest("Numillian benchmark fixture not found")

    def test_benchmark_fixture_loads(self):
        """The authoritative Numillian benchmark fixture must load without error."""
        self.assertIsNotNone(self.fixture)
        self.assertEqual(self.fixture["module_slug"], "The_Hidden_City_of_Numillian")

    def test_puzzle_preservation_section_exists(self):
        """Benchmark fixture must have puzzle_preservation expectations."""
        puzzle_exp = self.fixture.get("expectations", {}).get("puzzle_preservation", {})
        self.assertIn("required_puzzles", puzzle_exp)
        self.assertIn("total_source_puzzles", puzzle_exp)

    def test_skull_riddle_is_required(self):
        """skull_riddle is a required puzzle that must be preserved."""
        required = self.fixture["expectations"]["puzzle_preservation"]["required_puzzles"]
        self.assertIn(
            "skull_riddle", required,
            "skull_riddle (First Trial skull riddle) must be in required_puzzles",
        )

    def test_kill_the_dog_mindscape_is_required(self):
        """kill_the_dog_mindscape is a required puzzle that must be preserved."""
        required = self.fixture["expectations"]["puzzle_preservation"]["required_puzzles"]
        self.assertIn(
            "kill_the_dog_mindscape", required,
            "kill_the_dog_mindscape (False Third Trial) must be in required_puzzles",
        )

    def test_flooding_room_is_required(self):
        """flooding_room is a required puzzle that must be preserved."""
        required = self.fixture["expectations"]["puzzle_preservation"]["required_puzzles"]
        self.assertIn("flooding_room", required)

    def test_three_required_puzzles_total(self):
        """Benchmark expects exactly 3 source puzzles."""
        required = self.fixture["expectations"]["puzzle_preservation"]["required_puzzles"]
        total = self.fixture["expectations"]["puzzle_preservation"]["total_source_puzzles"]
        self.assertEqual(len(required), total)
        self.assertEqual(total, 3)

    def test_puzzle_pass_threshold_is_1_0(self):
        """Pass threshold for puzzle preservation must be 1.0 (all three required)."""
        thresholds = self.fixture.get("publication_thresholds", {}).get("pass", {})
        puzzle_threshold = thresholds.get("puzzle_preservation", 0)
        self.assertEqual(
            puzzle_threshold, 1.0,
            "puzzle_preservation pass threshold must be 1.0",
        )

    def test_current_benchmark_report_shows_puzzle_blockers(self):
        """SOURCE-CONTRACT: Current benchmark report shows puzzle_blocked status.

        After the production rebuild, the accurate_ingest_benchmark_report.json
        shows puzzle_preservation as blocked with 1/3 found.
        """
        report_path = Path(
            "modules/The_Hidden_City_of_Numillian/accurate_ingest_benchmark_report.json"
        )
        if not report_path.exists():
            self.skipTest("Numillian benchmark report not found (rebuild may not have run)")
        try:
            import json
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            self.skipTest("Numillian benchmark report could not be parsed")
        puzzle_cats = [
            c for c in data.get("category_results", [])
            if c.get("category") == "puzzle_preservation"
        ]
        if not puzzle_cats:
            self.skipTest("No puzzle_preservation category in benchmark report")
        puzzle = puzzle_cats[0]
        self.assertEqual(puzzle["status"], "pass")
        self.assertIn("skull_riddle", puzzle.get("details", {}).get("matched", []))
        self.assertIn("kill_the_dog_mindscape", puzzle.get("details", {}).get("matched", []))
        self.assertEqual(puzzle.get("details", {}).get("missing", []), [])


class TestPlotTopologyReportAccess(unittest.TestCase):
    """Source-contract: plot_topology_report.json is loadable in rebuild path."""

    def test_plot_topology_report_key_exists(self):
        """get_workspace_files includes 'plot_topology_report' with .json path."""
        from utils.toolkit_homebrew_upload_contract import get_workspace_files
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            files = get_workspace_files(Path(tmp) / "ws")
        self.assertIn("plot_topology_report", files)
        self.assertTrue(str(files["plot_topology_report"]).endswith(".json"))

    def test_load_plot_topology_report_returns_empty_for_absent(self):
        """load_json_artifact on an absent plot_topology_report returns empty dict."""
        from utils.toolkit_homebrew_upload_contract import load_json_artifact
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plot_topology_report.json"
        result = load_json_artifact(path)
        self.assertEqual(result, {})


class TestSyntheticPuzzleSourceSelection(unittest.TestCase):
    """Source-contract: puzzle source selection in synthetic blueprint path."""

    def test_topology_puzzle_chains_preferred_over_packet(self):
        from scripts.rebuild_numillian_accurate_ingest import _get_synthetic_puzzle_source_candidates

        topology = {"puzzle_chains": [{"id": "skull_riddle"}], "trials": [{"id": "kill_the_dog_mindscape"}]}
        packet = {"puzzles": [{"name": "flooding_room"}]}
        result = _get_synthetic_puzzle_source_candidates(packet, plot_topology_report=topology)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "skull_riddle")

    def test_topology_trials_fallback_when_no_puzzle_chains(self):
        from scripts.rebuild_numillian_accurate_ingest import _get_synthetic_puzzle_source_candidates

        topology = {"trials": [{"id": "kill_the_dog_mindscape"}]}
        packet = {}
        result = _get_synthetic_puzzle_source_candidates(packet, plot_topology_report=topology)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "kill_the_dog_mindscape")

    def test_packet_fallback_when_no_topology(self):
        from scripts.rebuild_numillian_accurate_ingest import _get_synthetic_puzzle_source_candidates

        packet = {"puzzle_chains": [{"id": "skull_riddle"}]}
        result = _get_synthetic_puzzle_source_candidates(packet)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "skull_riddle")

    def test_empty_when_no_sources(self):
        from scripts.rebuild_numillian_accurate_ingest import _get_synthetic_puzzle_source_candidates

        result = _get_synthetic_puzzle_source_candidates({})
        self.assertEqual(result, [])

    def test_packet_puzzle_keys_priority(self):
        from scripts.rebuild_numillian_accurate_ingest import _get_synthetic_puzzle_source_candidates

        packet = {"puzzle_chains": [{"id": "from_puzzle_chains"}]}
        result = _get_synthetic_puzzle_source_candidates(packet)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "from_puzzle_chains")


class TestBuildSyntheticPuzzleGraph(unittest.TestCase):
    """Source-contract: _build_synthetic_puzzle_graph converts raw sources to puzzle entries."""

    def test_handles_string_candidates(self):
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_puzzle_graph

        packet = {"puzzle_chains": ["skull_riddle", "flooding_room"]}
        result = _build_synthetic_puzzle_graph(packet)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["title"], "skull_riddle")
        self.assertEqual(result[1]["title"], "flooding_room")
        self.assertIn("chain_id", result[0])
        self.assertNotIn("setup", result[0])

    def test_dict_candidates_preserve_source_fields(self):
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_puzzle_graph

        topology = {
            "puzzle_chains": [
                {"id": "skull_riddle", "title": "The Skull Riddle", "rules": "Answer each skull's riddle to pass."}
            ]
        }
        result = _build_synthetic_puzzle_graph({}, plot_topology_report=topology)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chain_id"], "skull_riddle")
        self.assertEqual(result[0]["title"], "The Skull Riddle")
        self.assertEqual(result[0]["rules"], "Answer each skull's riddle to pass.")

    def test_topology_trials_populate_entries(self):
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_puzzle_graph

        topology = {
            "trials": [
                {"id": "kill_the_dog_mindscape", "name": "The False Third Trial", "setup": "A mindscape of the false third trial"}
            ]
        }
        result = _build_synthetic_puzzle_graph({}, plot_topology_report=topology)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chain_id"], "kill_the_dog_mindscape")
        self.assertEqual(result[0]["title"], "The False Third Trial")
        self.assertEqual(result[0]["setup"], "A mindscape of the false third trial")

    def test_topology_takes_precedence_over_packet(self):
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_puzzle_graph

        topology = {"puzzle_chains": [{"id": "skull_riddle", "title": "The Skull Riddle"}]}
        packet = {"puzzles": [{"name": "flooding_room"}]}
        result = _build_synthetic_puzzle_graph(packet, plot_topology_report=topology)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chain_id"], "skull_riddle")

    def test_does_not_invent_absent_fields(self):
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_puzzle_graph

        packet = {"puzzle_chains": [{"id": "skull_riddle"}]}
        result = _build_synthetic_puzzle_graph(packet)
        for key in ("setup", "rules", "solution", "failure_consequences"):
            self.assertNotIn(key, result[0])

    def test_coverage_matches_puzzle_graph_length(self):
        """coverage.puzzles_in_blueprint matches len(puzzle_graph) after Step 2.4."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        packet = {"puzzle_chains": ["skull_riddle", "flooding_room"]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash")
        self.assertEqual(bp["coverage"]["puzzles_in_blueprint"], 2)

    def test_coverage_zero_when_no_puzzles(self):
        """coverage.puzzles_in_blueprint is 0 when puzzle_graph is empty."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet({}, "test_hash")
        self.assertEqual(bp["coverage"]["puzzles_in_blueprint"], 0)

    def test_empty_when_no_sources(self):
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_puzzle_graph

        result = _build_synthetic_puzzle_graph({})
        self.assertEqual(result, [])

    def test_empty_when_topology_and_packet_both_absent(self):
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_puzzle_graph

        topology = {"puzzle_chains": []}
        result = _build_synthetic_puzzle_graph({}, plot_topology_report=topology)
        self.assertEqual(result, [])

    def test_missing_puzzle_warning_when_empty(self):
        """Empty puzzle_graph appends missing-puzzle warning."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet({}, "test_hash")
        self.assertEqual(bp["puzzle_graph"], [])
        self.assertGreaterEqual(len(bp["warnings"]), 2)
        self.assertTrue(
            any("Synthetic blueprint has no puzzle_graph entries from topology or packet sources" in w["message"]
                for w in bp["warnings"]),
        )

    def test_no_missing_puzzle_warning_when_populated(self):
        """Non-empty puzzle_graph does not produce warning."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet({"puzzle_chains": ["skull_riddle"]}, "test_hash")
        self.assertGreater(len(bp["puzzle_graph"]), 0)
        for w in bp["warnings"]:
            self.assertNotIn("no puzzle_graph entries from topology or packet sources", w["message"])

    def test_fidelity_blocked_warning_always_present(self):
        """The fidelity-blocked warning appears in every synthetic blueprint."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet({}, "test_hash")
        self.assertTrue(
            any("fidelity blocked" in w["message"] for w in bp["warnings"]),
        )


class TestEntityCandidateTriageReportAccess(unittest.TestCase):
    """Source-contract: entity_candidate_triage_report is loadable in rebuild path."""

    def test_triage_report_key_exists(self):
        """get_workspace_files includes 'entity_candidate_triage_report' with .json path."""
        from utils.toolkit_homebrew_upload_contract import get_workspace_files
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            files = get_workspace_files(Path(tmp) / "ws")
        self.assertIn("entity_candidate_triage_report", files)
        self.assertTrue(str(files["entity_candidate_triage_report"]).endswith(".json"))

    def test_load_triage_report_returns_empty_for_absent(self):
        """load_json_artifact on an absent entity_candidate_triage_report returns empty dict."""
        from utils.toolkit_homebrew_upload_contract import load_json_artifact
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entity_candidate_triage_report.json"
        result = load_json_artifact(path)
        self.assertEqual(result, {})

    def test_rebuild_script_has_triage_report_load(self):
        """Source of rebuild_numillian contains the triage report load."""
        source_path = Path("scripts/rebuild_numillian_accurate_ingest.py")
        content = source_path.read_text(encoding="utf-8")
        self.assertIn("entity_candidate_triage_report", content)
        self.assertIn("files[\"entity_candidate_triage_report\"]", content)


class TestTriageExclusion(unittest.TestCase):
    """Source-contract: triage-rejected/non-actor NPC seeds are excluded from roster."""

    def test_rejected_phrase_excluded(self):
        """but this is not true (rejected, narrative_phrase) is excluded."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {
            "decisions": [
                {"candidate_slug": "but_this_is_not_true", "candidate_text": "but this is not true",
                 "decision": "reject", "adjudicated_type": "narrative_phrase", "reason": "prefilter"},
            ]
        }
        packet = {"npc_seeds": [
            {"name": "But This Is Not True", "role": "kenku", "faction": ""},
            {"name": "Dog-Growl", "role": "kenku", "faction": ""},
        ]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Dog-Growl", names)
        self.assertNotIn("But This Is Not True", names)

    def test_narrative_phrase_type_excluded(self):
        """adjudicated_type narrative_phrase without reject decision is excluded."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {
            "decisions": [
                {"candidate_slug": "but_this_is_not_true", "candidate_text": "but this is not true",
                 "decision": "keep", "adjudicated_type": "narrative_phrase", "reason": "erred"},
            ]
        }
        packet = {"npc_seeds": [{"name": "But This Is Not True"}, {"name": "Valid NPC"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Valid NPC", names)
        self.assertNotIn("But This Is Not True", names)

    def test_non_actor_types_excluded(self):
        """plot_note, tone_marker, unknown types are excluded."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "some_plot_note", "decision": "keep", "adjudicated_type": "plot_note", "reason": "note"},
            {"candidate_slug": "tone_marker_x", "decision": "keep", "adjudicated_type": "tone_marker", "reason": "tone"},
            {"candidate_slug": "unknown_candidate", "decision": "keep", "adjudicated_type": "unknown", "reason": "?"},
        ]}
        packet = {"npc_seeds": [
            {"name": "some_plot_note"}, {"name": "tone_marker_x"},
            {"name": "unknown_candidate"}, {"name": "Real NPC"},
        ]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertNotIn("some_plot_note", names)
        self.assertNotIn("tone_marker_x", names)
        self.assertNotIn("unknown_candidate", names)
        self.assertIn("Real NPC", names)

    def test_true_npc_kept(self):
        """A true_npc with keep decision remains in roster."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "dog_growl", "decision": "keep", "adjudicated_type": "true_npc", "reason": "matched"},
        ]}
        packet = {"npc_seeds": [{"name": "Dog-Growl", "role": "kenku"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Dog-Growl", names)

    def test_empty_triage_no_exclusion(self):
        """Missing/empty triage report preserves all NPCs."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        packet = {"npc_seeds": [{"name": "Alice"}, {"name": "Bob"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash")
        self.assertEqual(len(bp["npc_roster"]), 2)

    def test_none_triage_no_exclusion(self):
        """None triage report preserves all NPCs."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        packet = {"npc_seeds": [{"name": "Alice"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=None)
        self.assertEqual(len(bp["npc_roster"]), 1)

    def test_slug_matching_normalized(self):
        """Slug matching handles spaces, hyphens, case."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "but_this_is_not_true", "decision": "reject", "adjudicated_type": "narrative_phrase", "reason": "prefilter"},
        ]}
        packet = {"npc_seeds": [{"name": "But-this-is-not-true"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        self.assertEqual(len(bp["npc_roster"]), 0)


class TestPrefilterFallback(unittest.TestCase):
    """Source-contract: deterministic prefilter applies when no triage decision exists."""

    def test_prefilter_excludes_lowercase_prose_name(self):
        """No triage decision -- lowercase prose-like name is excluded by prefilter."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        packet = {"npc_seeds": [
            {"name": "but this is not true"},
            {"name": "Dog-Growl"},
        ]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash")
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Dog-Growl", names)
        self.assertNotIn("but this is not true", names)

    def test_explicit_triage_keep_overrides_prefilter(self):
        """Explicit keep/true_npc decision prevents prefilter exclusion."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "but_this_is_not_true", "candidate_text": "but this is not true",
             "decision": "keep", "adjudicated_type": "true_npc", "reason": "manual"},
        ]}
        packet = {"npc_seeds": [{"name": "but this is not true"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("but this is not true", names)

    def test_uppercase_proper_name_passes_prefilter(self):
        """Uppercase proper-name NPC remains included when no triage decision exists."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        packet = {"npc_seeds": [{"name": "Dog-Growl"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash")
        self.assertEqual(len(bp["npc_roster"]), 1)
        self.assertEqual(bp["npc_roster"][0]["display_name"], "Dog-Growl")

    def test_step32_behavior_preserved_alongside_prefilter(self):
        """Rejected triage still excludes even if prefilter would not catch uppercase name."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "but_this_is_not_true", "candidate_text": "but this is not true",
             "decision": "reject", "adjudicated_type": "narrative_phrase", "reason": "prefilter"},
        ]}
        packet = {"npc_seeds": [
            {"name": "But This Is Not True"},
            {"name": "Dog-Growl"},
        ]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Dog-Growl", names)
        self.assertNotIn("But This Is Not True", names)


class TestFilteredMetadataRecords(unittest.TestCase):
    """Source-contract: filtered NPC candidate metadata is recorded for auditability."""

    def test_triage_excluded_appears_in_filtered_candidates(self):
        """Triage-excluded candidate has filter_source == 'triage'."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "but_this_is_not_true", "candidate_text": "but this is not true",
             "decision": "reject", "adjudicated_type": "narrative_phrase", "reason": "prefilter"},
        ]}
        packet = {"npc_seeds": [{"name": "But This Is Not True"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        self.assertEqual(len(bp["filtered_npc_candidates"]), 1)
        rec = bp["filtered_npc_candidates"][0]
        self.assertEqual(rec["filter_source"], "triage")
        self.assertEqual(rec["candidate_slug"], "but_this_is_not_true")

    def test_prefilter_excluded_appears_in_filtered_candidates(self):
        """Prefilter-excluded candidate has filter_source == 'prefilter'."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        packet = {"npc_seeds": [{"name": "but this is not true"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash")
        self.assertGreaterEqual(len(bp["filtered_npc_candidates"]), 1)
        rec = next((r for r in bp["filtered_npc_candidates"] if r["candidate_slug"] == "but_this_is_not_true"), None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["filter_source"], "prefilter")

    def test_kept_npc_not_in_filtered_candidates(self):
        """A kept true NPC does not appear in filtered metadata."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "dog_growl", "candidate_text": "Dog-Growl",
             "decision": "keep", "adjudicated_type": "true_npc", "reason": "matched"},
        ]}
        packet = {"npc_seeds": [{"name": "Dog-Growl", "role": "kenku"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        slugs = [r["candidate_slug"] for r in bp["filtered_npc_candidates"]]
        self.assertNotIn("dog_growl", slugs)

    def test_warning_summary_when_candidates_filtered(self):
        """Warning summary appears when filtered metadata is non-empty."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "but_this_is_not_true", "candidate_text": "but this is not true",
             "decision": "reject", "adjudicated_type": "narrative_phrase", "reason": "test"},
        ]}
        packet = {"npc_seeds": [{"name": "But This Is Not True"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash", entity_candidate_triage_report=triage)
        filter_warnings = [w for w in bp["warnings"] if w.get("filtered_count") is not None]
        self.assertGreaterEqual(len(filter_warnings), 1)
        self.assertIn("triage/prefilter", filter_warnings[0]["message"])

    def test_no_warning_when_no_candidates_filtered(self):
        """No warning summary appears when no candidates are filtered."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        packet = {"npc_seeds": [{"name": "Valid Npc"}]}
        bp = _build_synthetic_blueprint_from_packet(packet, "test_hash")
        filter_warnings = [w for w in bp["warnings"] if w.get("filtered_count") is not None]
        self.assertEqual(len(filter_warnings), 0)


class TestLegitimateNpcsUnaffected(unittest.TestCase):
    """Source-contract: Dog-Growl, Book-shut, Deflation, Alms-plate are NOT filtered."""

    def _seeds_with_names(self, names):
        return {"npc_seeds": [{"name": n} for n in names]}

    def test_dog_growl_not_filtered_without_triage(self):
        """Dog-Growl appears in npc_roster when no triage decision exists."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet(self._seeds_with_names(["Dog-Growl"]), "test_hash")
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Dog-Growl", names)

    def test_book_shut_not_filtered_without_triage(self):
        """Book-shut appears in npc_roster when no triage decision exists."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet(self._seeds_with_names(["Book-shut"]), "test_hash")
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Book-shut", names)

    def test_deflation_not_filtered_without_triage(self):
        """Deflation appears in npc_roster when no triage decision exists."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet(self._seeds_with_names(["Deflation"]), "test_hash")
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Deflation", names)

    def test_alms_plate_not_filtered_without_triage(self):
        """Alms-plate appears in npc_roster when no triage decision exists."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet(self._seeds_with_names(["Alms-plate"]), "test_hash")
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Alms-plate", names)

    def test_all_four_in_roster_together(self):
        """All four NPCs appear together when no triage decisions exist."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet(
            self._seeds_with_names(["Dog-Growl", "Book-shut", "Deflation", "Alms-plate"]), "test_hash")
        names = [n["display_name"] for n in bp["npc_roster"]]
        for n in ("Dog-Growl", "Book-shut", "Deflation", "Alms-plate"):
            self.assertIn(n, names)

    def test_none_in_filtered_candidates(self):
        """None of the four appear in filtered_npc_candidates without triage."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        bp = _build_synthetic_blueprint_from_packet(
            self._seeds_with_names(["Dog-Growl", "Book-shut", "Deflation", "Alms-plate"]), "test_hash")
        filtered_slugs = [r["candidate_slug"] for r in bp["filtered_npc_candidates"]]
        for slug in ("dog_growl", "book_shut", "deflation", "alms_plate"):
            self.assertNotIn(slug, filtered_slugs)

    def test_not_filtered_by_explicit_keep_triage(self):
        """Explicit keep/true_npc triage does not filter."""
        from scripts.rebuild_numillian_accurate_ingest import _build_synthetic_blueprint_from_packet

        triage = {"decisions": [
            {"candidate_slug": "dog_growl", "candidate_text": "Dog-Growl",
             "decision": "keep", "adjudicated_type": "true_npc", "reason": "matched"},
        ]}
        bp = _build_synthetic_blueprint_from_packet(
            self._seeds_with_names(["Dog-Growl", "Book-shut"]), "test_hash",
            entity_candidate_triage_report=triage)
        names = [n["display_name"] for n in bp["npc_roster"]]
        self.assertIn("Dog-Growl", names)


class TestNumillianArtifactSourcePhraseClean(unittest.TestCase):
    """Source-contract: but this is not true does not appear in final module artifacts."""

    def test_not_in_module_context(self):
        """but this is not true absent from module_context.json."""
        import json
        with open("modules/The_Hidden_City_of_Numillian/module_context.json") as f:
            content = json.dumps(json.load(f))
        self.assertNotIn("but_this_is_not_true", content)
        self.assertNotIn("but this is not true", content)

    def test_not_in_benchmark_report(self):
        """but this is not true absent from benchmark report."""
        import json
        with open("modules/The_Hidden_City_of_Numillian/accurate_ingest_benchmark_report.json") as f:
            content = json.dumps(json.load(f))
        self.assertNotIn("but_this_is_not_true", content)
        self.assertNotIn("but this is not true", content)

    def test_not_in_area_files(self):
        """but this is not true absent from all generated area files."""
        from pathlib import Path
        area_dir = Path("modules/The_Hidden_City_of_Numillian/areas")
        if not area_dir.exists():
            self.skipTest("No area files to check")
        for af in sorted(area_dir.glob("*.json")):
            content = af.read_text()
            self.assertNotIn("but_this_is_not_true", content,
                             msg=f"Found in {af.name}")
            self.assertNotIn("but this is not true", content,
                             msg=f"Found in {af.name}")

    def test_builder_blueprint_only_in_filtered_not_roster(self):
        """but_this_is_not_true appears only in filtered_npc_candidates, not npc_roster."""
        import json
        path = "modules/ingest/workspaces/The_Hidden_City_of_Numillian_replacement_proof_9ab641d95aed/builder_blueprint.json"
        with open(path) as f:
            bp = json.load(f)
        filtered_slugs = [f.get("candidate_slug") for f in bp.get("filtered_npc_candidates", [])]
        roster_display = [n["display_name"] for n in bp.get("npc_roster", [])]
        self.assertIn("but_this_is_not_true", filtered_slugs)
        self.assertNotIn("but this is not true", roster_display)


if __name__ == "__main__":
    unittest.main(verbosity=2)
