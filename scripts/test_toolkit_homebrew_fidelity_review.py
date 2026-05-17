#!/usr/bin/env python3
"""Regression tests for toolkit Homebrew fidelity review helper."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from web.extensions.toolkit_homebrew_fidelity_review import (  # noqa: E402
    build_fidelity_review_payload,
    can_approve_fidelity_review,
    is_accurate_ingest_workspace,
)
from utils.toolkit_homebrew_upload_contract import get_workspace_files  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ToolkitHomebrewFidelityReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.files = get_workspace_files(self.workspace)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_base_accurate_workspace(
        self,
        *,
        fidelity_report: dict,
        blueprint_report: dict,
        normalization_report: dict | None = None,
        repair_report: dict | None = None,
        repair_index: dict | None = None,
        malformed_required_key: str | None = None,
        malformed_required_text: str = "{not-json}",
    ) -> None:
        _write_json(
            self.files["source_graph"],
            {
                "atoms": [
                    {"type": "npc", "name": "Caretaker Noll"},
                    {"type": "location", "name": "Ruined Gate"},
                    {"type": "plot_beat", "label": "Enter the crypt"},
                    {"type": "puzzle", "label": "Hidden switch"},
                    {"type": "clue", "label": "Ash on the altar"},
                    {"type": "encounter", "label": "Skeleton patrol"},
                    {"type": "item", "label": "Rust key"},
                    {"type": "tone_marker", "label": "gothic"},
                ]
            },
        )
        _write_json(self.files["identity_resolution_report"], {"decisions": [{"type": "npc"}]})
        _write_json(
            self.files["plot_topology_report"],
            {"plot_beats": ["Enter the crypt"], "puzzle_chains": [], "assumptions": [], "unresolved": []},
        )
        _write_json(self.files["source_graph_synthesis_report"], {"status": "ready"})
        _write_json(self.files["normalization_fidelity_report"], fidelity_report)
        if normalization_report is not None:
            _write_json(self.files["normalization_report"], normalization_report)
        _write_json(
            self.files["normalization_repair_report"],
            repair_report
            or {
                "status": "complete",
                "summary": {"repair_status": "complete", "repair_attempts": 0},
            },
        )
        _write_json(
            self.files["packet_repair_attempts_index"],
            repair_index or {"total_attempts": 0, "entries": []},
        )
        _write_json(self.files["builder_blueprint"], {"title": "Example"})
        if malformed_required_key:
            _write_text(self.files[malformed_required_key], malformed_required_text)
        else:
            _write_json(self.files["builder_blueprint_report"], blueprint_report)

    def test_is_accurate_ingest_workspace_distinguishes_legacy_and_accurate(self) -> None:
        self.assertFalse(is_accurate_ingest_workspace(self.workspace))

        self._write_base_accurate_workspace(
            fidelity_report={"status": "clean", "summary": {}},
            normalization_report={"status": "ready"},
            blueprint_report={"blueprint_status": "ready", "source_coverage": {}, "blueprint_coverage": {}},
        )
        self.assertTrue(is_accurate_ingest_workspace(self.workspace))

    def test_build_fidelity_review_payload_clean_is_approvable(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={
                "status": "clean",
                "summary": {
                    "status": "clean",
                    "blocking_count": 0,
                    "warning_count": 0,
                    "info_count": 0,
                    "covered_required": 8,
                    "total_required": 8,
                },
                "findings": [],
            },
            normalization_report={"status": "ready"},
            repair_report={"status": "complete", "summary": {"repair_status": "complete", "repair_attempts": 0}},
            repair_index={"total_attempts": 0, "entries": []},
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "clean",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["mode"], "accurate_ingest")
        self.assertEqual(payload["status"], "clean")
        self.assertTrue(payload["can_approve"])
        self.assertEqual(payload["coverage"]["required"]["covered_required"], 8)
        self.assertEqual(payload["coverage"]["source_atoms"]["npc"], 1)
        self.assertEqual(payload["blueprint"]["status"], "ready")
        self.assertEqual(can_approve_fidelity_review(payload), (True, ""))

    def test_build_fidelity_review_payload_repaired_is_approvable(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={
                "status": "degraded",
                "summary": {
                    "status": "degraded",
                    "blocking_count": 0,
                    "warning_count": 1,
                    "info_count": 0,
                    "covered_required": 6,
                    "total_required": 8,
                },
                "findings": [
                    {"severity": "warning", "category": "coverage", "message": "One optional clue missing"}
                ],
            },
            normalization_report={"status": "ready"},
            repair_report={"status": "repaired", "summary": {"repair_status": "repaired", "repair_attempts": 2}},
            repair_index={
                "total_attempts": 2,
                "entries": [
                    {"attempt": 1, "status": "failed"},
                    {"attempt": 2, "status": "repaired"},
                ],
            },
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "repaired",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["status"], "repaired")
        self.assertEqual(payload["repair"]["attempt_count"], 2)
        self.assertEqual(payload["repair"]["latest_status"], "repaired")
        self.assertTrue(payload["can_approve"])

    def test_build_fidelity_review_payload_degraded_without_blockers_is_degraded(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={
                "status": "degraded",
                "summary": {
                    "status": "degraded",
                    "blocking_count": 0,
                    "warning_count": 2,
                    "info_count": 0,
                    "covered_required": 6,
                    "total_required": 8,
                },
                "findings": [
                    {"severity": "warning", "category": "coverage", "message": "Optional clue missing"},
                    {"severity": "warning", "category": "coverage", "message": "Optional plot branch missing"},
                ],
            },
            normalization_report={"status": "ready"},
            repair_report={"status": "complete", "summary": {"repair_status": "complete", "repair_attempts": 0}},
            repair_index={"total_attempts": 0, "entries": []},
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "degraded",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["status"], "degraded")
        self.assertTrue(payload["can_approve"])
        self.assertEqual(payload["blockers"], [])
        self.assertEqual(len(payload["warnings"]), 2)

    def test_build_fidelity_review_payload_blocked_is_not_approvable(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={
                "status": "blocked",
                "reason": "blocking_fidelity_findings",
                "summary": {
                    "status": "blocked",
                    "blocking_count": 2,
                    "warning_count": 0,
                    "info_count": 0,
                    "covered_required": 4,
                    "total_required": 8,
                },
                "findings": [
                    {"severity": "blocking", "category": "location", "message": "Missing keyed location", "path": "locations/3"},
                    {"severity": "blocking", "category": "npc", "message": "Missing required NPC", "path": "npcs/2"},
                ],
            },
            normalization_report={"status": "ready"},
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "blocked",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["can_approve"])
        self.assertEqual(len(payload["blockers"]), 2)
        self.assertEqual(can_approve_fidelity_review(payload)[0], False)

    def test_build_fidelity_review_payload_failed_from_malformed_fidelity_is_not_approvable(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={
                "status": "failed",
                "reason": "malformed_fidelity_report",
                "summary": {
                    "status": "failed",
                    "blocking_count": 1,
                    "warning_count": 0,
                    "info_count": 0,
                    "covered_required": 4,
                    "total_required": 8,
                },
                "findings": [
                    {"severity": "blocking", "category": "report", "message": "Malformed fidelity record"}
                ],
            },
            normalization_report={"status": "ready"},
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "failed",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["can_approve"])
        self.assertEqual(can_approve_fidelity_review(payload), (False, "malformed_fidelity_report"))

    def test_build_fidelity_review_payload_missing_required_artifact_blocks_review(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={"status": "clean", "summary": {"status": "clean"}},
            normalization_report=None,
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "clean",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["status"], "missing")
        self.assertFalse(payload["can_approve"])
        self.assertIn("normalization_report", payload["refusal_reason"])

    def test_build_fidelity_review_payload_malformed_required_artifact_blocks_review(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={"status": "clean", "summary": {"status": "clean"}},
            normalization_report={"status": "ready"},
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "clean",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
            malformed_required_key="builder_blueprint_report",
            malformed_required_text="{not-json}",
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["can_approve"])
        self.assertIn("builder_blueprint_report", payload["refusal_reason"])

    def test_build_fidelity_review_payload_legacy_workspace_is_legacy(self) -> None:
        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["mode"], "legacy")
        self.assertEqual(payload["status"], "legacy")
        self.assertTrue(payload["can_approve"])
        self.assertFalse(payload["can_reject"])

    def test_blockers_and_warnings_are_bounded_and_path_annotated(self) -> None:
        findings = []
        for i in range(10):
            findings.append(
                {"severity": "blocking", "category": "npc", "message": f"Blocking {i}", "path": f"npc/{i}"}
            )
        for i in range(10):
            findings.append(
                {"severity": "warning", "category": "coverage", "message": f"Warning {i}", "path": f"cov/{i}"}
            )

        self._write_base_accurate_workspace(
            fidelity_report={
                "status": "blocked",
                "summary": {"status": "blocked", "blocking_count": 10, "warning_count": 10, "info_count": 0, "covered_required": 4, "total_required": 8},
                "findings": findings,
            },
            normalization_report={"status": "ready"},
            blueprint_report={
                "blueprint_status": "ready",
                "fidelity_status": "blocked",
                "refusal_reason": "",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(len(payload["blockers"]), 6)
        self.assertEqual(len(payload["warnings"]), 6)
        self.assertIn("artifact_path", payload["blockers"][0])
        self.assertIn("artifact_path", payload["warnings"][0])

    def test_can_approve_rejects_blueprint_not_ready(self) -> None:
        self._write_base_accurate_workspace(
            fidelity_report={"status": "clean", "summary": {"status": "clean", "blocking_count": 0, "warning_count": 0, "info_count": 0, "covered_required": 8, "total_required": 8}, "findings": []},
            normalization_report={"status": "ready"},
            blueprint_report={
                "blueprint_status": "pending",
                "fidelity_status": "clean",
                "refusal_reason": "blueprint_not_ready",
                "source_coverage": {"location_candidates": 2, "npc_candidates": 1, "canonical_identities": 1, "plot_beats": 1, "puzzle_chains": 1},
                "blueprint_coverage": {"locations_in_blueprint": 2, "npcs_in_blueprint": 1},
                "warnings": [],
            },
        )

        payload = build_fidelity_review_payload(self.workspace)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(can_approve_fidelity_review(payload), (False, "blueprint_not_ready"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
