# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for builder blueprint fidelity precheck gate (Phase 4, Section 2).

Verifies that:
- clean/repaired fidelity allows blueprint generation
- blocked/failed fidelity refuses blueprint generation
- missing source artifacts refuse blueprint generation
- degraded with blockers refuses; degraded without blockers allows
- blueprint report persists refusal status
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from utils.toolkit_builder_blueprint import (
    STATUS_BLOCKED_BY_FIDELITY,
    STATUS_MISSING_ARTIFACTS,
    STATUS_READY,
    build_builder_blueprint_report,
    evaluate_blueprint_fidelity_precheck,
    load_phase2_artifacts,
)


def _make_source_graph(npc_count: int = 5, loc_count: int = 3) -> dict:
    atoms = []
    for i in range(npc_count):
        atoms.append({"id": f"npc_{i}", "name": f"NPC_{i}", "type": "npc",
                       "criticality": "required", "source_refs": [{"excerpt": f"NPC {i} source"}]})
    for i in range(loc_count):
        atoms.append({"id": f"loc_{i}", "name": f"Location_{i}", "type": "location",
                       "criticality": "required", "source_refs": [{"excerpt": f"Location {i} source"}]})
    return {"atoms": atoms}


def _make_packet(title: str = "Test Module") -> dict:
    return {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_hash": "abc123",
        "title": title,
        "locations": [],
        "npc_seeds": [],
    }


def _make_fidelity_report(status: str, blocking: bool = False) -> dict:
    findings = []
    if blocking:
        findings.append({
            "finding_id": "block_001",
            "source_atom_id": "npc_0",
            "category": "missing",
            "severity": "blocking",
            "repairable": True,
            "expected": "NPC_0",
            "actual": "",
        })
    return {
        "status": status,
        "findings": findings,
    }


class TestBlueprintFidelityPrecheck(unittest.TestCase):

    def test_clean_fidelity_allows_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("clean"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_repaired_fidelity_allows_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("repaired"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_blocked_fidelity_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("blocked"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_BLOCKED_BY_FIDELITY)

    def test_failed_fidelity_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("failed"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_BLOCKED_BY_FIDELITY)

    def test_missing_source_graph_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=None,
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("clean"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_MISSING_ARTIFACTS)

    def test_missing_packet_refuses_generation(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=None,
            fidelity_report=_make_fidelity_report("clean"),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_MISSING_ARTIFACTS)

    def test_degraded_with_blocking_findings_refuses(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("degraded", blocking=True),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "refused")
        self.assertEqual(result["refusal_reason"], STATUS_BLOCKED_BY_FIDELITY)

    def test_degraded_without_blockers_allows(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=_make_fidelity_report("degraded", blocking=False),
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_fidelity_report_rollup_reads_from_normalization_report(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=None,
            normalization_report={"fidelity": {"status": "clean"}},
        )
        self.assertEqual(result["precheck_status"], "allowed")

    def test_unknown_fidelity_status_allows_if_no_blockers(self):
        result = evaluate_blueprint_fidelity_precheck(
            source_graph=_make_source_graph(),
            normalized_packet=_make_packet(),
            fidelity_report=None,
            normalization_report=None,
        )
        self.assertEqual(result["precheck_status"], "allowed")


class TestLoadPhase2Artifacts(unittest.TestCase):

    def test_returns_none_for_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {
                "source_graph": Path(tmp) / "missing.json",
            }
            artifacts = load_phase2_artifacts(files)
            self.assertIsNone(artifacts["source_graph"])

    def test_loads_existing_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_graph.json"
            path.write_text(json.dumps({"atoms": [{"id": "test"}]}))
            files = {"source_graph": path}
            artifacts = load_phase2_artifacts(files)
            self.assertIsNotNone(artifacts["source_graph"])
            self.assertEqual(artifacts["source_graph"]["atoms"][0]["id"], "test")


class TestBlueprintReportBuilder(unittest.TestCase):

    def test_report_contains_input_artifact_status(self):
        artifacts = {
            "source_graph": _make_source_graph(),
            "identity_resolution_report": {"canonical_identities": [{"display_name": "Test"}]},
            "plot_topology_report": {},
            "normalized_packet": _make_packet(),
            "normalization_fidelity_report": _make_fidelity_report("clean"),
            "normalization_report": None,
            "source_graph_synthesis_report": None,
        }
        precheck = {"precheck_status": "allowed", "fidelity_status": "clean", "blocking_findings": [], "detail": "", "refusal_reason": ""}
        report = build_builder_blueprint_report("ready", artifacts, precheck)
        self.assertEqual(report["blueprint_status"], "ready")
        self.assertTrue(report["input_artifacts"]["source_graph_present"])
        self.assertTrue(report["input_artifacts"]["identity_resolution_present"])

    def test_report_refusal_has_reason(self):
        artifacts = {"source_graph": None}
        precheck = {"precheck_status": "refused", "refusal_reason": "missing_artifacts", "fidelity_status": "unknown", "blocking_findings": [], "detail": "missing source_graph"}
        report = build_builder_blueprint_report("missing_artifacts", artifacts, precheck)
        self.assertEqual(report["refusal_reason"], "missing_artifacts")


if __name__ == "__main__":
    unittest.main()
