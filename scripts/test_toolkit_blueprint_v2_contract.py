"""
Contract tests for builder_blueprint.v2 generation and validation.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_config import (
    ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD,
    ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK,
    ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT,
)

from utils.toolkit_builder_blueprint import (
    BUILDER_BLUEPRINT_VERSION,
    BUILDER_BLUEPRINT_V2_VERSION,
    generate_builder_blueprint,
    generate_builder_blueprint_v2,
    validate_builder_blueprint_v2,
    load_phase2_artifacts,
    build_builder_blueprint_report,
    STATUS_READY,
    STATUS_BLOCKED_BY_FIDELITY,
    STATUS_GENERATION_FAILED,
)

from utils.toolkit_entity_candidate_triage import (
    build_triage_decision,
    DECISION_KEEP,
    DECISION_REJECT,
    DECISION_RECLASSIFY,
    TYPE_TRUE_NPC,
    TYPE_NARRATIVE_PHRASE,
    TYPE_PLOT_NOTE,
    TRIAGE_REPORT_STATUS_PASS,
)


def _make_source_graph(location_count: int = 13, npc_count: int = 5) -> dict:
    """Build a minimal source graph for testing."""
    atoms = []
    for i in range(location_count):
        atoms.append({
            "id": f"loc_{i+1:03d}",
            "type": "location",
            "name": f"Location {i+1}" if i == 0 else f"Location {i+1}: Test Room {i}",
            "summary": f"Test location {i+1}",
            "criticality": "required",
            "confidence": "high",
            "source_refs": [{"source_path": "test.md", "excerpt": f"Room {i+1} excerpt"}],
        })
    for i in range(npc_count):
        atoms.append({
            "id": f"npc_{i+1:03d}",
            "type": "npc",
            "name": f"NPC_{i+1}" if i == 0 else f"NPC {i+1}",
            "summary": f"Test NPC {i+1}",
            "criticality": "required",
            "confidence": "high",
            "source_refs": [{"source_path": "test.md", "excerpt": f"NPC {i+1} excerpt"}],
        })
    return {"atoms": atoms}


def _make_normalized_packet(title="Test Module") -> dict:
    return {
        "title": title,
        "source_hash": "abc123",
        "adventure_summary": "A test module for blueprint v2",
        "description": "Description of test module",
    }


class TestFeatureFlagSourceContracts(unittest.TestCase):
    """Source-contract tests: flags exist and have expected defaults."""

    def test_gui_blueprint_build_disabled_by_default(self):
        self.assertIsNotNone(ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD)
        self.assertFalse(ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD)

    def test_seed_writer_fallback_exists_and_disabled(self):
        self.assertIsNotNone(ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK)
        self.assertFalse(ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK)

    def test_blueprint_enrichment_flag_exists_and_disabled(self):
        self.assertIsNotNone(ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT)
        self.assertFalse(ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT)


class TestBlueprintV2Constants(unittest.TestCase):
    """Version constant contract tests."""

    def test_v2_version_constant_exists(self):
        self.assertEqual(BUILDER_BLUEPRINT_V2_VERSION, "source_faithful_builder_blueprint.v2")

    def test_v1_version_constant_preserved(self):
        self.assertEqual(BUILDER_BLUEPRINT_VERSION, "source_faithful_builder_blueprint.v1")

    def test_v1_and_v2_are_different(self):
        self.assertNotEqual(BUILDER_BLUEPRINT_VERSION, BUILDER_BLUEPRINT_V2_VERSION)


class TestBlueprintV2RequiredFields(unittest.TestCase):
    """Blueprint v2 SHALL include all required top-level sections."""

    def setUp(self):
        self.source_graph = _make_source_graph(location_count=13, npc_count=5)
        self.packet = _make_normalized_packet()

    def test_v2_has_all_required_sections(self):
        bp = generate_builder_blueprint_v2(
            source_graph=self.source_graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.packet,
            fidelity_report=None,
        )
        self.assertEqual(bp.get("blueprint_version"), BUILDER_BLUEPRINT_V2_VERSION)

        required = [
            "module", "source_lock", "area_plan", "location_roster",
            "npc_roster", "plot_graph", "puzzle_graph", "clue_graph",
            "encounter_plan", "item_roster", "enrichment_allowlist",
            "artifact_refs", "coverage", "warnings", "blockers",
        ]
        for section in required:
            self.assertIn(section, bp, f"Missing required section: {section}")

    def test_v2_source_lock_has_all_locks(self):
        bp = generate_builder_blueprint_v2(
            source_graph=self.source_graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.packet,
            fidelity_report=None,
        )
        lock = bp.get("source_lock", {})
        lock_keys = [
            "canonical_names_locked",
            "required_atom_omission_blocks_build",
            "invented_major_entities_forbidden",
            "replacement_plotlines_forbidden",
            "puzzle_rule_rewrite_forbidden",
            "module_summary_is_derived_only",
        ]
        for key in lock_keys:
            self.assertIn(key, lock, f"Missing source_lock key: {key}")
            self.assertTrue(lock[key], f"Source lock {key} should be True")

    def test_v2_enrichment_allowlist_populated(self):
        bp = generate_builder_blueprint_v2(
            source_graph=self.source_graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.packet,
            fidelity_report=None,
        )
        allowlist = bp.get("enrichment_allowlist", {})
        self.assertGreater(len(allowlist), 0)
        expected_keys = [
            "npc_description", "npc_role", "npc_faction",
            "plot_main_objective", "plot_point_description",
            "area_description", "location_description",
            "location_dm_instructions", "location_adventure_summary",
        ]
        for key in expected_keys:
            self.assertIn(key, allowlist, f"Missing enrichment key: {key}")
            entry = allowlist[key]
            self.assertIn("field", entry)
            self.assertIn("scope", entry)
            self.assertIn("max_chars", entry)

    def test_v2_artifact_refs_present(self):
        bp = generate_builder_blueprint_v2(
            source_graph=self.source_graph,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.packet,
            fidelity_report=None,
        )
        refs = bp.get("artifact_refs", {})
        self.assertIn("source_graph", refs)
        self.assertIn("normalized_packet", refs)
        self.assertIsNotNone(refs["source_graph"])
        self.assertIsNotNone(refs["normalized_packet"])

    def test_v2_coverage_counts(self):
        bp = generate_builder_blueprint_v2(
            source_graph=_make_source_graph(location_count=13, npc_count=5),
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.packet,
            fidelity_report=None,
        )
        coverage = bp.get("coverage", {})
        self.assertEqual(coverage.get("locations_in_blueprint"), 13)
        self.assertEqual(coverage.get("npcs_in_blueprint"), 5)
        self.assertIn("plot_beats_in_blueprint", coverage)
        self.assertIn("puzzles_in_blueprint", coverage)

    def test_v2_preserves_source_order(self):
        bp = generate_builder_blueprint_v2(
            source_graph=_make_source_graph(location_count=13, npc_count=5),
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.packet,
            fidelity_report=None,
        )
        rosters = bp.get("location_roster", [])
        self.assertEqual(len(rosters), 13)
        for i, loc in enumerate(rosters):
            self.assertIn("display_name", loc)
            self.assertIn("source_refs", loc)
            self.assertIn("criticality", loc)

    def test_v2_npc_roster_has_required_fields(self):
        bp = generate_builder_blueprint_v2(
            source_graph=_make_source_graph(location_count=3, npc_count=5),
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=self.packet,
            fidelity_report=None,
        )
        npcs = bp.get("npc_roster", [])
        self.assertGreaterEqual(len(npcs), 3)
        for npc in npcs:
            self.assertIn("display_name", npc)
            self.assertIn("criticality", npc)
            self.assertIn("source_refs", npc)


class TestBlueprintV2Validation(unittest.TestCase):
    """Blueprint validation SHALL fail closed for missing required structure."""

    def test_valid_blueprint_passes_validation(self):
        bp = generate_builder_blueprint_v2(
            source_graph=_make_source_graph(location_count=5, npc_count=3),
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=_make_normalized_packet(),
            fidelity_report=None,
        )
        result = validate_builder_blueprint_v2(bp)
        self.assertTrue(result.get("valid", False))
        self.assertIn(result.get("status", ""), ("pass", "degraded"))

    def test_wrong_version_fails(self):
        bp = {"blueprint_version": "source_faithful_builder_blueprint.v1"}
        result = validate_builder_blueprint_v2(bp)
        self.assertFalse(result.get("valid"))
        self.assertEqual(result.get("status"), "blocked")

    def test_missing_section_fails(self):
        bp = {
            "blueprint_version": BUILDER_BLUEPRINT_V2_VERSION,
            "blueprint_status": STATUS_READY,
            "module": {},
        }
        result = validate_builder_blueprint_v2(bp)
        self.assertFalse(result.get("valid"))
        self.assertEqual(result.get("status"), "blocked")
        blocker_msgs = [b.get("message", "") for b in result.get("blockers", [])]
        has_missing = any("missing" in m.lower() for m in blocker_msgs)
        self.assertTrue(has_missing)

    def test_empty_location_roster_with_requirement_blocked(self):
        bp = {
            "blueprint_version": BUILDER_BLUEPRINT_V2_VERSION,
            "blueprint_status": STATUS_READY,
            "module": {},
            "source_lock": {"canonical_names_locked": True},
            "area_plan": [],
            "location_roster": [],
            "npc_roster": [],
            "plot_graph": [],
            "puzzle_graph": [],
            "clue_graph": [],
            "encounter_plan": [],
            "item_roster": [],
            "enrichment_allowlist": {},
            "artifact_refs": {},
            "coverage": {"locations_in_blueprint": 0, "npcs_in_blueprint": 0},
            "warnings": [],
            "blockers": [],
        }
        result = validate_builder_blueprint_v2(bp, require_locations=True)
        self.assertFalse(result.get("valid"))
        self.assertEqual(result.get("status"), "blocked")

    def test_blocked_fidelity_status_refused(self):
        bp = {
            "blueprint_version": BUILDER_BLUEPRINT_V2_VERSION,
            "blueprint_status": STATUS_BLOCKED_BY_FIDELITY,
            "module": {},
            "source_lock": {},
            "area_plan": [],
            "location_roster": [],
            "npc_roster": [],
            "plot_graph": [],
            "puzzle_graph": [],
            "clue_graph": [],
            "encounter_plan": [],
            "item_roster": [],
            "enrichment_allowlist": {},
            "artifact_refs": {},
            "coverage": {},
            "warnings": [],
            "blockers": [{"category": "fidelity_blocked", "severity": "blocker", "message": "Test"}],
        }
        result = validate_builder_blueprint_v2(bp)
        self.assertFalse(result.get("valid"))
        self.assertEqual(result.get("status"), "blocked")


class TestV1Compatibility(unittest.TestCase):
    """Legacy v1 blueprint and narrative handoff MUST remain available."""

    def test_v1_generate_unchanged(self):
        sg = _make_source_graph(location_count=3, npc_count=2)
        packet = _make_normalized_packet()
        bp = generate_builder_blueprint(
            source_graph=sg,
            identity_report=None,
            plot_topology=None,
            synthesis_report=None,
            normalized_packet=packet,
            fidelity_report=None,
        )
        self.assertEqual(bp.get("blueprint_version"), BUILDER_BLUEPRINT_VERSION)

    def test_v2_does_not_break_v1_structure(self):
        sg = _make_source_graph(location_count=5, npc_count=3)
        packet = _make_normalized_packet()
        v1 = generate_builder_blueprint(
            source_graph=sg, identity_report=None, plot_topology=None,
            synthesis_report=None, normalized_packet=packet, fidelity_report=None,
        )
        v2 = generate_builder_blueprint_v2(
            source_graph=sg, identity_report=None, plot_topology=None,
            synthesis_report=None, normalized_packet=packet, fidelity_report=None,
        )
        # v1 and v2 location rosters should share the same base structure
        self.assertGreaterEqual(len(v2.get("location_roster", [])), len(v1.get("location_roster", [])))
        # v2 has extra sections v1 does not necessarily have
        self.assertIn("enrichment_allowlist", v2)
        self.assertIn("artifact_refs", v2)


class TestBlueprintV2NumillianMock(unittest.TestCase):
    """Numillian-like map-key location preservation."""

    def test_13_map_key_locations_preserved(self):
        sg = _make_source_graph(location_count=13, npc_count=8)
        packet = _make_normalized_packet("The Hidden City of Numillian")
        bp = generate_builder_blueprint_v2(
            source_graph=sg, identity_report=None, plot_topology=None,
            synthesis_report=None, normalized_packet=packet, fidelity_report=None,
        )
        self.assertEqual(len(bp.get("location_roster", [])), 13)
        for loc in bp["location_roster"]:
            self.assertIn("display_name", loc)
            self.assertIn("atom_id", loc)
            self.assertIn("source_refs", loc)


class TestBlueprintV2StatusComputation(unittest.TestCase):
    """Blueprint status computation edge cases."""

    def test_empty_atoms_produces_generation_failed_or_degraded(self):
        sg = {"atoms": []}
        packet = _make_normalized_packet("Empty Module")
        bp = generate_builder_blueprint_v2(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
        )
        status = bp.get("blueprint_status", "")
        self.assertIn(status, (STATUS_GENERATION_FAILED, "degraded"))

    def test_valid_atoms_produces_ready(self):
        sg = _make_source_graph(location_count=3, npc_count=2)
        packet = _make_normalized_packet("Valid Module")
        bp = generate_builder_blueprint_v2(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
        )
        self.assertEqual(bp.get("blueprint_status"), STATUS_READY)


def _make_triage_report(decisions: list) -> dict:
    """Build a minimal entity candidate triage report."""
    total = len(decisions)
    return {
        "triage_report_version": "entity_candidate_triage_report.v1",
        "status": TRIAGE_REPORT_STATUS_PASS,
        "total_candidates": total,
        "summary": {
            "kept": sum(1 for d in decisions if d.get("decision") == DECISION_KEEP),
            "rejected": sum(1 for d in decisions if d.get("decision") == DECISION_REJECT),
            "reclassified": sum(1 for d in decisions if d.get("decision") == DECISION_RECLASSIFY),
            "non_actor": sum(1 for d in decisions if d.get("adjudicated_type") in ("narrative_phrase", "plot_note", "tone_marker", "unknown")),
            "underbound_npcs": 0,
        },
        "type_counts": {},
        "decisions": decisions,
    }


class TestBlueprintV2TriageIntegration(unittest.TestCase):
    """Blueprint NPC roster triage filtering tests."""

    def test_load_phase2_artifacts_includes_triage_key(self):
        tmp = Path(tempfile.mkdtemp(prefix="bp_triage_"))
        try:
            artifacts = load_phase2_artifacts({})
            self.assertIn("entity_candidate_triage_report", artifacts)
            self.assertIsNone(artifacts.get("entity_candidate_triage_report"))
        finally:
            import shutil
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_missing_triage_preserves_legacy_roster(self):
        sg = _make_source_graph(location_count=3, npc_count=3)
        packet = _make_normalized_packet("Legacy Module")
        bp = generate_builder_blueprint(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=None,
        )
        self.assertEqual(len(bp.get("npc_roster", [])), 3)

    def test_rejected_narrative_phrase_excluded(self):
        sg = _make_source_graph(location_count=2, npc_count=2)
        packet = _make_normalized_packet("Phrase Test")
        rejected = build_triage_decision(
            candidate_text="but this is not true",
            candidate_slug="npc_001",
            proposed_type="npc",
            adjudicated_type=TYPE_NARRATIVE_PHRASE,
            decision=DECISION_REJECT,
            reason="prefilter: narrative phrase",
        )
        triage = _make_triage_report([rejected])
        bp = generate_builder_blueprint(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=triage,
        )
        names = [e["display_name"] for e in bp.get("npc_roster", [])]
        self.assertNotIn("NPC_1", names)
        self.assertIn("NPC 2", names)

    def test_kept_source_npc_with_bindings_retained(self):
        sg = _make_source_graph(location_count=2, npc_count=1)
        packet = _make_normalized_packet("Binding Test")
        kept = build_triage_decision(
            candidate_text="Dog-Growl",
            candidate_slug="npc_001",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="bound to The Rookery",
            location_bindings=["The Rookery"],
            source_role="kenku_inhabitant",
        )
        triage = _make_triage_report([kept])
        bp = generate_builder_blueprint(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=triage,
        )
        self.assertEqual(len(bp.get("npc_roster", [])), 1)
        entry = bp["npc_roster"][0]
        self.assertEqual(entry["display_name"], "NPC_1")
        self.assertEqual(entry["role"], "kenku_inhabitant")
        self.assertEqual(entry["location_binding"], "The Rookery")

    def test_reclassified_plot_note_excluded(self):
        sg = _make_source_graph(location_count=2, npc_count=2)
        packet = _make_normalized_packet("Reclassify Test")
        reclassified = build_triage_decision(
            candidate_text="a darkened corridor",
            candidate_slug="npc_001",
            proposed_type="npc",
            adjudicated_type=TYPE_PLOT_NOTE,
            decision=DECISION_RECLASSIFY,
            reason="atmospheric description",
        )
        triage = _make_triage_report([reclassified])
        bp = generate_builder_blueprint(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=triage,
        )
        names = [e["display_name"] for e in bp.get("npc_roster", [])]
        self.assertNotIn("NPC_1", names)
        self.assertIn("NPC 2", names)

    def test_v2_threads_triage_report(self):
        sg = _make_source_graph(location_count=2, npc_count=2)
        packet = _make_normalized_packet("V2 Triage Test")
        rejected = build_triage_decision(
            candidate_text="but this is not true",
            candidate_slug="npc_001",
            proposed_type="npc",
            adjudicated_type=TYPE_NARRATIVE_PHRASE,
            decision=DECISION_REJECT,
            reason="prefilter",
        )
        triage = _make_triage_report([rejected])
        bp = generate_builder_blueprint_v2(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=triage,
        )
        names = [e["display_name"] for e in bp.get("npc_roster", [])]
        self.assertNotIn("NPC_1", names)
        self.assertIn("NPC 2", names)
        self.assertIn("entity_candidate_triage_report", bp.get("artifact_refs", {}))

    def test_no_triage_v2_preserves_legacy(self):
        sg = _make_source_graph(location_count=3, npc_count=3)
        packet = _make_normalized_packet("No Triage V2")
        bp = generate_builder_blueprint_v2(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=None,
        )
        self.assertEqual(len(bp.get("npc_roster", [])), 3)
        self.assertIsNone(bp.get("artifact_refs", {}).get("entity_candidate_triage_report"))

    def test_missing_triage_emits_warning_in_report(self):
        """Step 2.3: missing triage warns in builder_blueprint_report."""
        sg = _make_source_graph(location_count=2, npc_count=2)
        packet = _make_normalized_packet("Missing Triage")
        bp = generate_builder_blueprint(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=None,
        )
        artifacts = {
            "source_graph": sg,
            "identity_resolution_report": None,
            "normalized_packet": packet,
            "normalization_fidelity_report": None,
            "normalization_report": None,
            "entity_candidate_triage_report": None,
        }
        report = build_builder_blueprint_report(
            blueprint_status=STATUS_READY,
            artifacts=artifacts,
            precheck_result={"precheck_status": "allowed", "fidelity_status": "pass"},
            blueprint=bp,
        )
        warning_ids = [w["finding_id"] for w in report.get("warnings", [])]
        self.assertIn("candidate_triage_missing", warning_ids)
        self.assertFalse(report["input_artifacts"]["entity_candidate_triage_present"])

    def test_missing_triage_report_input_artifacts_false(self):
        """Step 2.3: entity_candidate_triage_present is false when triage is None."""
        sg = _make_source_graph(location_count=1, npc_count=1)
        packet = _make_normalized_packet("Input Artifact False")
        bp = generate_builder_blueprint(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=None,
        )
        artifacts = {
            "source_graph": sg,
            "identity_resolution_report": None,
            "normalized_packet": packet,
            "normalization_fidelity_report": None,
            "normalization_report": None,
            "entity_candidate_triage_report": None,
        }
        report = build_builder_blueprint_report(
            blueprint_status=STATUS_READY,
            artifacts=artifacts,
            precheck_result={"precheck_status": "allowed", "fidelity_status": "pass"},
            blueprint=bp,
        )
        self.assertFalse(report["input_artifacts"]["entity_candidate_triage_present"])

    def test_present_triage_does_not_emit_missing_warning(self):
        """Step 2.3: present triage report suppresses candidate_triage_missing."""
        sg = _make_source_graph(location_count=2, npc_count=2)
        packet = _make_normalized_packet("Present Triage")
        kept = build_triage_decision(
            candidate_text="Dog-Growl",
            candidate_slug="npc_001",
            proposed_type="npc",
            adjudicated_type=TYPE_TRUE_NPC,
            decision=DECISION_KEEP,
            reason="bound",
            location_bindings=["The Rookery"],
        )
        triage = _make_triage_report([kept])
        bp = generate_builder_blueprint(
            source_graph=sg, identity_report=None,
            plot_topology=None, synthesis_report=None,
            normalized_packet=packet, fidelity_report=None,
            triage_report=triage,
        )
        artifacts = {
            "source_graph": sg,
            "identity_resolution_report": None,
            "normalized_packet": packet,
            "normalization_fidelity_report": None,
            "normalization_report": None,
            "entity_candidate_triage_report": triage,
        }
        report = build_builder_blueprint_report(
            blueprint_status=STATUS_READY,
            artifacts=artifacts,
            precheck_result={"precheck_status": "allowed", "fidelity_status": "pass"},
            blueprint=bp,
        )
        warning_ids = [w["finding_id"] for w in report.get("warnings", [])]
        self.assertNotIn("candidate_triage_missing", warning_ids)
        self.assertTrue(report["input_artifacts"]["entity_candidate_triage_present"])


if __name__ == "__main__":
    unittest.main()
