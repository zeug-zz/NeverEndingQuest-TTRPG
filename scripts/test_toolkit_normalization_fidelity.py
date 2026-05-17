#!/usr/bin/env python3
"""Regression tests for normalization fidelity audit and repair loop."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_normalization_fidelity import (
    DEFAULT_MAX_REPAIR_ATTEMPTS,
    FIDELITY_REPORT_VERSION,
    apply_repair_operations,
    build_fidelity_summary_for_report,
    build_repair_attempt_artifact,
    make_finding,
    run_normalization_fidelity_audit,
    validate_repair_operations,
)
from utils.toolkit_homebrew_upload_contract import (
    ensure_workspace_placeholders,
    persist_normalization_fidelity_artifact,
    persist_normalization_repair_artifact,
    persist_packet_repair_attempt_artifact,
    persist_packet_repair_attempts_index,
)


# ---- Helpers ----
def _source_graph_with_atoms(atoms):
    return {"atoms": atoms}


def _identity_report():
    return {"canonical_identities": [], "ambiguous_identities": []}


def _plot_topology():
    return {
        "plot_beats": [],
        "puzzle_chains": [],
        "clue_dependencies": [],
        "trials": [],
        "endings": [],
        "assumptions": [],
        "unresolved": [],
    }


def _packet():
    return {
        "title": "Test",
        "locations": [],
        "npc_seeds": [],
        "monster_refs": [],
        "plot_progression": [],
        "connectivity_hints": [],
        "warnings": [],
        "assumptions": [],
        "confidence_notes": {},
    }


# ---- Fidelity audit tests ----

class TestFidelityAudit(unittest.TestCase):
    """Task 1.x: Fidelity audit contract tests."""

    def test_covered_required_atoms_report_clean(self):
        packet = _packet()
        packet["npc_seeds"] = [{"name": "Wayne", "role": "Innkeeper"}]
        packet["locations"] = [{"name": "Brooksteps Inn"}]
        sg = _source_graph_with_atoms([
            {"id": "n1", "type": "npc", "name": "Wayne", "criticality": "required", "source_refs": []},
            {"id": "l1", "type": "location", "name": "Brooksteps Inn", "criticality": "required", "source_refs": []},
        ])

        report = run_normalization_fidelity_audit(
            source_graph=sg, normalized_packet=packet,
            identity_report=_identity_report(), plot_topology=_plot_topology(),
        )
        self.assertEqual(report["status"], "clean")
        self.assertEqual(report["summary"]["covered_required"], 2)
        self.assertEqual(report["summary"]["blocking_count"], 0)

    def test_missing_required_npc_reported_blocking(self):
        packet = _packet()
        sg = _source_graph_with_atoms([
            {"id": "n1", "type": "npc", "name": "Wayne", "criticality": "required", "source_refs": []},
        ])

        report = run_normalization_fidelity_audit(
            source_graph=sg, normalized_packet=packet,
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["summary"]["blocking_count"], 1)
        findings = report["findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "missing")
        self.assertEqual(findings[0]["severity"], "blocking")

    def test_missing_source_graph_reports_skipped(self):
        report = run_normalization_fidelity_audit(
            source_graph=None, normalized_packet=_packet(),
        )
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["summary"]["status"], "skipped")

    def test_missing_packet_reports_failed(self):
        sg = _source_graph_with_atoms([
            {"id": "n1", "type": "npc", "name": "Wayne", "criticality": "required", "source_refs": []},
        ])
        report = run_normalization_fidelity_audit(
            source_graph=sg, normalized_packet=None,
        )
        self.assertEqual(report["status"], "failed")

    def test_unsupported_npc_addition_warned(self):
        packet = _packet()
        packet["npc_seeds"] = [{"name": "Invented NPC"}]
        sg = _source_graph_with_atoms([
            {"id": "n1", "type": "npc", "name": "Wayne", "criticality": "required", "source_refs": []},
        ])
        report = run_normalization_fidelity_audit(
            source_graph=sg, normalized_packet=packet,
        )
        # Missing required NPC is blocking + unsupported addition is warning
        unsupported = [f for f in report["findings"] if f["category"] == "unsupported"]
        self.assertGreaterEqual(len(unsupported), 1)

    def test_identity_alias_resolution(self):
        packet = _packet()
        packet["npc_seeds"] = [{"name": "Wayne"}]
        sg = _source_graph_with_atoms([
            {"id": "n1", "type": "npc", "name": "Wayne the Innkeeper", "criticality": "required", "source_refs": []},
        ])
        identity = {
            "canonical_identities": [
                {"display_name": "wayne the innkeeper", "aliases": ["wayne"]},
            ],
            "ambiguous_identities": [],
        }
        report = run_normalization_fidelity_audit(
            source_graph=sg, normalized_packet=packet, identity_report=identity,
        )
        self.assertEqual(report["summary"]["blocking_count"], 0)
        self.assertEqual(report["summary"]["covered_required"], 1)

    def test_topology_beat_coverage(self):
        packet = _packet()
        sg = _source_graph_with_atoms([
            {"id": "p1", "type": "plot_beat", "name": "Enter the Crypt", "criticality": "required", "source_refs": []},
        ])
        topology = _plot_topology()
        topology["plot_beats"] = [{"label": "Enter the Crypt"}, {"label": "Ending"}]
        report = run_normalization_fidelity_audit(
            source_graph=sg, normalized_packet=packet, plot_topology=topology,
        )
        # Missing required plot beat is blocking
        missing = [f for f in report["findings"] if f["category"] == "missing"]
        self.assertGreaterEqual(len(missing), 1)


# ---- Repair patch model tests ----

class TestRepairPatchModel(unittest.TestCase):
    """Task 2.x: Repair patch model contract tests."""

    def test_accept_valid_add_npc_seed_with_source_refs(self):
        ops = [{
            "op": "add_npc_seed",
            "source_atom_id": "n1",
            "target_path": "npc_seeds",
            "value": {"name": "Wayne", "role": "Innkeeper"},
            "source_refs": [{"line_start": 1, "excerpt": "Wayne the innkeeper"}],
        }]
        fid_findings = [make_finding("missing", "blocking", source_atom_id="n1", repairable=True)]
        accepted, rejected = validate_repair_operations(ops, fid_findings)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 0)

    def test_reject_op_missing_source_evidence(self):
        ops = [{"op": "add_npc_seed", "target_path": "npc_seeds", "value": {"name": "X"}}]
        fid_findings = [make_finding("missing", "blocking", source_atom_id="n1", repairable=True)]
        accepted, rejected = validate_repair_operations(ops, fid_findings)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("missing_source_evidence", rejected[0]["reason"])

    def test_reject_unsupported_op_type(self):
        ops = [{"op": "delete_location", "source_atom_id": "n1", "source_refs": [{"line_start": 1}]}]
        fid_findings = [make_finding("missing", "blocking", source_atom_id="n1", repairable=True)]
        accepted, rejected = validate_repair_operations(ops, fid_findings)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("unsupported_or_destructive_op", rejected[0]["reason"])

    def test_apply_add_npc_seed(self):
        packet = _packet()
        ops = [{"op": "add_npc_seed", "value": {"name": "Wayne", "role": "Innkeeper"}}]
        repaired = apply_repair_operations(packet, ops)
        self.assertEqual(len(repaired["npc_seeds"]), 1)
        self.assertEqual(repaired["npc_seeds"][0]["name"], "Wayne")

    def test_apply_add_location(self):
        packet = _packet()
        ops = [{"op": "add_location", "value": {"name": "Brooksteps Inn", "summary": "Cozy"}}]
        repaired = apply_repair_operations(packet, ops)
        self.assertEqual(len(repaired["locations"]), 1)

    def test_apply_add_monster_ref(self):
        packet = _packet()
        ops = [{"op": "add_monster_ref", "value": "Skeleton"}]
        repaired = apply_repair_operations(packet, ops)
        self.assertEqual(len(repaired["monster_refs"]), 1)

    def test_apply_add_assumption(self):
        packet = _packet()
        ops = [{"op": "add_assumption", "value": "Inferred from source tone"}]
        repaired = apply_repair_operations(packet, ops)
        self.assertEqual(len(repaired["assumptions"]), 1)


# ---- Repair loop tests ----

class TestRepairLoop(unittest.TestCase):
    """Task 3.x: Repair loop contract tests."""

    def test_build_repair_attempt_artifact_shape(self):
        artifact = build_repair_attempt_artifact(
            1, "prompt", "output", [], [], [], True, "clean",
        )
        self.assertIn("repair_attempt_version", artifact)
        self.assertEqual(artifact["attempt"], 1)
        self.assertTrue(artifact["applied"])
        self.assertEqual(artifact["status"], "clean")

    def test_repair_attempt_artifact_respects_max_chars(self):
        long_str = "x" * 5000
        artifact = build_repair_attempt_artifact(
            1, long_str, long_str, [], [], [], False, "failed", "reason",
        )
        self.assertLessEqual(len(artifact["repair_prompt"]), 2000)
        self.assertLessEqual(len(artifact["model_output_preview"]), 2000)


# ---- Reporting tests ----

class TestFidelityReporting(unittest.TestCase):
    """Task 5.x: Fidelity reporting contract tests."""

    def test_build_fidelity_summary_for_report(self):
        audit = {
            "status": "degraded",
            "summary": {
                "status": "degraded",
                "blocking_count": 0,
                "warning_count": 3,
                "covered_required": 10,
                "total_required": 13,
            },
        }
        summary = build_fidelity_summary_for_report(audit)
        self.assertEqual(summary["fidelity_status"], "degraded")
        self.assertEqual(summary["fidelity_warning_count"], 3)
        self.assertEqual(summary["fidelity_covered_required"], 10)
        self.assertEqual(summary["fidelity_total_required"], 13)

    def test_fidelity_summary_defaults_for_empty_audit(self):
        summary = build_fidelity_summary_for_report({})
        self.assertEqual(summary["fidelity_status"], "unknown")


# ---- Persistence tests ----

class TestFidelityPersistence(unittest.TestCase):
    """Task 1.4 / 3.3: Artifact persistence contract tests."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        ensure_workspace_placeholders(self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persist_fidelity_report(self):
        report = {
            "fidelity_report_version": FIDELITY_REPORT_VERSION,
            "status": "clean",
            "findings": [],
            "summary": {"status": "clean"},
        }
        ok = persist_normalization_fidelity_artifact(self.workspace, report)
        self.assertTrue(ok)
        path = self.workspace / "normalization_fidelity_report.json"
        self.assertTrue(path.exists())

    def test_persist_repair_artifact(self):
        ok = persist_normalization_repair_artifact(
            self.workspace, {"repair_report_version": "1", "summary": {}},
        )
        self.assertTrue(ok)
        self.assertTrue((self.workspace / "normalization_repair_report.json").exists())

    def test_persist_repair_attempt(self):
        ok = persist_packet_repair_attempt_artifact(
            self.workspace, 1, build_repair_attempt_artifact(1, "", "", [], [], [], True, "clean"),
        )
        self.assertTrue(ok)
        path = self.workspace / "packet_repair_attempts" / "attempt_1.json"
        self.assertTrue(path.exists())

    def test_persist_repair_attempts_index(self):
        ok = persist_packet_repair_attempts_index(
            self.workspace,
            {"index_version": "1", "total_attempts": 1, "entries": []},
        )
        self.assertTrue(ok)
        self.assertTrue((self.workspace / "packet_repair_attempts" / "index.json").exists())

    def test_finding_ids_are_stable(self):
        f1 = make_finding("missing", "blocking", source_atom_id="n1", packet_path="npc_seeds")
        f2 = make_finding("missing", "blocking", source_atom_id="n1", packet_path="npc_seeds")
        self.assertEqual(f1["finding_id"], f2["finding_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
