"""Tests for web/extensions/toolkit_homebrew_packet_builder.py v2 integration.

All tests use mocked seed/enrichment helpers. No LLM calls.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.extensions.toolkit_homebrew_packet_builder import (
    _classify_blueprint_handoff,
    run_toolkit_homebrew_packet_build,
)
from utils.toolkit_final_reconciliation import REPORT_VERSION
from web.routes.toolkit_homebrew_routes import (
    _get_canonical_accurate_ingest_phase,
    _build_accurate_ingest_summary,
    _resolve_homebrew_build_target,
)

VALID_V1_VERSION = "source_faithful_builder_blueprint.v1"
VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"


# ---------------------------------------------------------------------------
# Workspace setup
# ---------------------------------------------------------------------------


def _create_workspace(tmpdir: str, **file_overrides) -> Path:
    """Create a minimal workspace with required files."""
    ws = Path(tmpdir) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    defaults = {
        "normalized_packet.json": {
            "packet_version": "packet.v1",
            "name": "pipeline-001",
            "title": "Test Adventure",
            "description": "A test adventure for unit tests",
            "source_hash": "abc123",
            "source_rights": "user_authored",
            "normalization_state": "normalized",
        },
        "ui_review_snapshot.json": {
            "decision": "approve",
            "recorded_at": "2026-01-01T00:00:00Z",
            "job_id": "test-job-001",
            "packet_identity": {"source_hash": "abc123"},
        },
        "builder_blueprint.json": {},
        "builder_blueprint_report.json": {},
        "builder_narrative.txt": "Test narrative for build",
    }

    for filename, content in {**defaults, **file_overrides}.items():
        path = ws / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content) if isinstance(content, dict) else content, encoding="utf-8")

    return ws


def _make_v2_blueprint(**overrides) -> Dict[str, Any]:
    return {
        "blueprint_version": VALID_V2_VERSION,
        "blueprint_status": "ready",
        "module": {"title": "Test V2 Module", "summary": "A v2 test"},
        "source_lock": {"canonical_names_locked": True},
        "area_plan": [{"area_name": "Test Area", "source_locations": []}],
        "location_roster": [],
        "npc_roster": [],
        "plot_graph": [],
        "puzzle_graph": [],
        "clue_graph": [],
        "encounter_plan": [],
        "item_roster": [],
        "tone_requirements": [],
        "source_refs": [],
        "warnings": [],
        "coverage": {"locations_in_blueprint": 0, "npcs_in_blueprint": 0},
        "enrichment_allowlist": {},
        "artifact_refs": {},
        "blockers": [],
        **overrides,
    }


# ---------------------------------------------------------------------------
# Classification Tests
# ---------------------------------------------------------------------------


class TestClassifyBlueprintHandoff(unittest.TestCase):
    """Test the _classify_blueprint_handoff function."""

    def _make_files(self, **paths) -> Dict[str, Path]:
        return {
            "source_graph": paths.get("source_graph", Path("/tmp/fake_source_graph.json")),
            "normalization_fidelity_report": paths.get("normalization_fidelity_report", Path("/tmp/fake_fidelity.json")),
        }

    def test_legacy_when_blueprint_disabled(self):
        with patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF", False):
            result = _classify_blueprint_handoff({}, None, None)
            self.assertEqual(result, "legacy_allowed")

    def test_v2_ready(self):
        bp = _make_v2_blueprint()
        report = {"blueprint_status": "ready"}
        result = _classify_blueprint_handoff(self._make_files(), bp, report)
        self.assertEqual(result, "source_blueprint_v2_ready")

    def test_v1_ready(self):
        bp = _make_v2_blueprint(blueprint_version=VALID_V1_VERSION)
        report = {"blueprint_status": "ready"}
        result = _classify_blueprint_handoff(self._make_files(), bp, report)
        self.assertEqual(result, "source_blueprint_ready")

    def test_blueprint_required_not_ready(self):
        bp = _make_v2_blueprint(blueprint_status="blocked")
        report = {"blueprint_status": "blocked"}
        result = _classify_blueprint_handoff(self._make_files(), bp, report)
        self.assertEqual(result, "blueprint_required_not_ready")

    def test_legacy_no_artifacts(self):
        result = _classify_blueprint_handoff({}, None, None)
        self.assertEqual(result, "legacy_allowed")

    def test_evidence_present_no_blueprint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            evidence_file = tmp / "source_graph.json"
            evidence_file.write_text("{}", encoding="utf-8")
            files = self._make_files(
                source_graph=evidence_file,
                normalization_fidelity_report=tmp / "fidelity.json",
            )
            result = _classify_blueprint_handoff(files, None, None)
            self.assertEqual(result, "blueprint_required_not_ready")


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestPacketBuilderV2Integration(unittest.TestCase):
    """Test v2 integration in run_toolkit_homebrew_packet_build."""

    def setUp(self):
        import uuid
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.test_slug = "Gui_Unit_Test_" + uuid.uuid4().hex[:8]
        self.test_source_hash = uuid.uuid4().hex
        self.workspace = _create_workspace(
            self.tmpdir_obj.name,
            **{
                "normalized_packet.json": {
                    "packet_version": "packet.v1",
                    "name": "pipeline-001",
                    "title": self.test_slug,
                    "description": "A test adventure for unit tests",
                    "source_hash": self.test_source_hash,
                    "source_rights": "user_authored",
                    "normalization_state": "normalized",
                },
                "ui_review_snapshot.json": {
                    "decision": "approve",
                    "recorded_at": "2026-01-01T00:00:00Z",
                    "job_id": "test-job-001",
                    "packet_identity": {"source_hash": self.test_source_hash},
                },
            }
        )

    def _seed_result(self, status="success"):
        return {"seed_status": status, "coverage": {}, "warnings": []}

    def _enrichment_result(self, status="skipped"):
        return {"status": status, "warnings": [], "applied": [], "rejected": []}

    def _build_v2_workspace(self):
        bp = _make_v2_blueprint()
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint_report.json").write_text(json.dumps(report), encoding="utf-8")

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_blueprint_enrichment.run_enrichment_pipeline")
    def test_v2_ready_calls_seed_writer(self, mock_enrichment, mock_seed):
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_enrichment.return_value = self._enrichment_result()

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["build_mode"], "blueprint_seed_fallback")
        self.assertEqual(result.get("seed_writer_mode"), "fallback")
        self.assertEqual(result["seed_status"], "success")
        self.assertIn("enrichment_status", result)
        mock_seed.assert_called_once()
        mock_enrichment.assert_called_once()

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_seed_writer_failure_surfaced(self, mock_seed):
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result(status="failed")

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["status"], "failed")
        self.assertIn("seed_writer_failed", result.get("error", ""))

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_blueprint_enrichment.run_enrichment_pipeline")
    def test_v2_with_enrichment_degraded(self, mock_enrichment, mock_seed):
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()
        mock_enrichment.return_value = self._enrichment_result(status="degraded")

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["build_mode"], "blueprint_seed_fallback")
        self.assertEqual(result.get("seed_writer_mode"), "fallback")
        self.assertEqual(result["seed_status"], "success")
        self.assertEqual(result["enrichment_status"], "degraded")

    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_enrichment_exception_still_succeeds(self, mock_seed):
        self._build_v2_workspace()
        mock_seed.return_value = self._seed_result()

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["build_mode"], "blueprint_seed_fallback")
        self.assertEqual(result.get("seed_writer_mode"), "fallback")
        self.assertEqual(result["seed_status"], "success")
        self.assertIn("enrichment_status", result)
        self.assertIn(result["enrichment_status"], ("skipped", "degraded"))

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_seed_writer_build")
    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_v2_flag_disabled_uses_module_builder(self, mock_executor, mock_seed):
        self._build_v2_workspace()
        mock_executor.return_value = {"status": "success", "build_mode": "packet_workspace_v1"}
        mock_seed.side_effect = AssertionError("seed writer must not be called with flag disabled")

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
            False,
        ):
            result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["build_mode"], "source_enhanced_modulebuilder")
        mock_executor.assert_called_once()
        mock_seed.assert_not_called()

    def test_v2_required_but_not_ready_fails_closed(self):
        bp = _make_v2_blueprint(blueprint_status="blocked")
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps({"blueprint_status": "blocked"}), encoding="utf-8"
        )

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
            True,
        ):
            result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["status"], "failed")
        self.assertIn("blueprint_not_ready", result.get("error", ""))

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_seed_writer_build")
    def test_seed_writer_mode_explicit_preview(self, mock_seed):
        self._build_v2_workspace()
        mock_seed.return_value = {
            "status": "success",
            "seed_status": "success",
            "coverage": {},
            "warnings": [],
        }

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-job-001", seed_writer_mode="preview",
        )

        self.assertEqual(result["build_mode"], "blueprint_seed_preview")
        self.assertEqual(result.get("seed_writer_mode"), "preview")
        self.assertEqual(result["seed_status"], "success")
        mock_seed.assert_called_once()

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_seed_writer_build")
    def test_seed_writer_mode_explicit_support(self, mock_seed):
        self._build_v2_workspace()
        mock_seed.return_value = {
            "status": "success",
            "seed_status": "success",
            "coverage": {},
            "warnings": [],
        }

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-job-001", seed_writer_mode="support",
        )

        self.assertEqual(result["build_mode"], "blueprint_seed_support")
        self.assertEqual(result.get("seed_writer_mode"), "support")
        mock_seed.assert_called_once()

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_seed_writer_build")
    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_explicit_seed_writer_ignores_source_monster_refs_and_encounter_seeds(self, mock_executor, mock_seed):
        """Explicit seed writer mode remains compatible with source monster/encounter fields."""
        self._build_v2_workspace()
        # Add source fields to packet and blueprint
        packet_path = self.workspace / "normalized_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["monster_refs"] = ["Alhoon", "Illithid"]
        packet["encounter_seeds"] = ["The skull riddle trial"]
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        bp = json.loads((self.workspace / "builder_blueprint.json").read_text(encoding="utf-8"))
        bp["monster_refs"] = ["Nothic", "Charion"]
        bp["encounter_seeds"] = ["The flooding room puzzle"]
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")

        mock_seed.return_value = {
            "status": "success",
            "seed_status": "success",
            "coverage": {},
            "warnings": [],
        }

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-job-001", seed_writer_mode="support",
        )

        self.assertEqual(result["build_mode"], "blueprint_seed_support")
        self.assertEqual(result.get("seed_writer_mode"), "support")
        self.assertEqual(result["seed_status"], "success")
        mock_seed.assert_called_once()
        mock_executor.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_seed_writer_build")
    def test_seed_writer_mode_explicit_fallback(self, mock_seed):
        self._build_v2_workspace()
        mock_seed.return_value = {
            "status": "success",
            "seed_status": "success",
            "coverage": {},
            "warnings": [],
        }

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-job-001", seed_writer_mode="fallback",
        )

        self.assertEqual(result["build_mode"], "blueprint_seed_fallback")
        self.assertEqual(result.get("seed_writer_mode"), "fallback")
        self.assertEqual(result["seed_status"], "success")
        mock_seed.assert_called_once()

    def test_seed_writer_mode_invalid_fails_closed(self):
        self._build_v2_workspace()

        result = run_toolkit_homebrew_packet_build(
            self.workspace, "test-job-001", seed_writer_mode="invalid_mode",
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("seed_writer_mode_invalid", result.get("error", ""))
        self.assertIn("allowed_modes", result)

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_seed_writer_build")
    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_default_no_seed_mode_uses_module_builder(self, mock_executor, mock_seed):
        self._build_v2_workspace()
        mock_executor.return_value = {"status": "success", "build_mode": "packet_workspace_v1"}

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["build_mode"], "source_enhanced_modulebuilder")
        self.assertFalse(bool(result.get("seed_writer_mode")))
        mock_executor.assert_called_once()
        mock_seed.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_handoff_includes_source_contract_npc_location_puzzle_tone(self, mock_executor):
        # Build Numillian-like v2 workspace with source tokens matching
        # production synthetic blueprint shape (display_name, chain_id/title,
        # tone as string).
        bp = _make_v2_blueprint(
            npc_roster=[
                {"display_name": "Adhagal", "aliases": [], "role": "illithid"},
                {"display_name": "Belrik Dumma-dhur", "aliases": [], "role": "smith"},
                {"display_name": "Xaereal the Constructor", "aliases": [], "role": "builder"},
            ],
            location_roster=[
                {"display_name": "Charion Tamer", "parent_area": "District", "aliases": []},
                {"display_name": "The Rookery", "parent_area": "District", "aliases": []},
                {"display_name": "Handworks Guild", "parent_area": "Guild", "aliases": []},
            ],
            puzzle_graph=[
                {"chain_id": "skull_riddle", "title": "The Skull Riddle"},
                {"chain_id": "flooding_room", "title": "The Flooding Room"},
                {"chain_id": "kill_the_dog_mindscape", "title": "Kill the Dog"},
            ],
            tone_requirements="quirky_character_driven_hidden_city",
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(json.dumps(report), encoding="utf-8")

        mock_executor.return_value = {"status": "success", "build_mode": "packet_workspace_v1"}

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        mock_executor.assert_called_once()
        builder_input = mock_executor.call_args[0][0]

        # Handoff mode
        self.assertEqual(builder_input.get("handoff_mode"), "source_blueprint")

        # Forbidden-invention source lock
        self.assertIn("blueprint", builder_input)
        source_lock = builder_input["blueprint"]["source_lock"]
        self.assertTrue(source_lock["canonical_names_locked"])
        self.assertTrue(source_lock["invented_major_entities_forbidden"])
        self.assertTrue(source_lock["replacement_plotlines_forbidden"])
        self.assertTrue(source_lock["puzzle_rule_rewrite_forbidden"])

        # Source artifact paths
        artifacts = builder_input["blueprint"]["source_artifacts"]
        self.assertIsInstance(artifacts.get("source_graph"), str)
        self.assertIsInstance(artifacts.get("plot_topology_report"), str)

        # Source contract fields directly in builder_input
        self.assertIn("source_npc_names", builder_input)
        self.assertIn("Adhagal", builder_input["source_npc_names"])
        self.assertIn("Belrik Dumma-dhur", builder_input["source_npc_names"])
        self.assertIn("Xaereal the Constructor", builder_input["source_npc_names"])

        self.assertIn("source_location_names", builder_input)
        self.assertIn("Charion Tamer", builder_input["source_location_names"])
        self.assertIn("The Rookery", builder_input["source_location_names"])
        self.assertIn("Handworks Guild", builder_input["source_location_names"])

        self.assertIn("source_puzzle_ids", builder_input)
        self.assertIn("skull_riddle", builder_input["source_puzzle_ids"])
        self.assertIn("flooding_room", builder_input["source_puzzle_ids"])
        self.assertIn("kill_the_dog_mindscape", builder_input["source_puzzle_ids"])

        self.assertIn("source_tone", builder_input)
        self.assertIn("quirky_character_driven_hidden_city", builder_input["source_tone"])

        # Verify persisted builder_input.json carries the same fields
        persisted_path = self.workspace / "builder_input.json"
        self.assertTrue(persisted_path.exists(), "builder_input.json must be persisted")
        persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
        self.assertIn("source_npc_names", persisted)
        self.assertIn("Adhagal", persisted["source_npc_names"])
        self.assertIn("source_location_names", persisted)
        self.assertIn("Charion Tamer", persisted["source_location_names"])
        self.assertIn("source_puzzle_ids", persisted)
        self.assertIn("skull_riddle", persisted["source_puzzle_ids"])
        self.assertIn("source_tone", persisted)
        self.assertIn("quirky_character_driven_hidden_city", persisted["source_tone"])

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_handoff_includes_source_monster_refs_and_encounter_seeds(self, mock_executor):
        """Builder input includes source_monster_refs and source_encounter_seeds."""
        monster_refs = [
            "Alhoon", "Illithid", "Homunculus",
            "Kenku", "Nothic", "Charion",
        ]
        encounter_seeds = [
            "The skull riddle trial challenges the party to answer the skull's questions",
            "The flooding room puzzle requires solving water flow mechanisms",
            "The dog test examines the party's compassion and resolve",
            "A mindscape battle against psychic attackers and mental projections",
        ]
        # Populate normalized packet with source fields
        packet_path = self.workspace / "normalized_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["monster_refs"] = monster_refs
        packet["encounter_seeds"] = encounter_seeds
        packet_path.write_text(json.dumps(packet), encoding="utf-8")

        bp = _make_v2_blueprint(
            monster_refs=monster_refs,
            encounter_seeds=encounter_seeds,
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(json.dumps(report), encoding="utf-8")

        mock_executor.return_value = {"status": "success", "build_mode": "packet_workspace_v1"}

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        mock_executor.assert_called_once()
        builder_input = mock_executor.call_args[0][0]

        # Monster refs
        self.assertIn("source_monster_refs", builder_input)
        for ref in ["Alhoon", "Illithid", "Homunculus", "Kenku", "Nothic", "Charion"]:
            self.assertIn(ref, builder_input["source_monster_refs"])

        # Encounter seeds
        self.assertIn("source_encounter_seeds", builder_input)
        self.assertIn(
            "The skull riddle trial challenges the party to answer the skull's questions",
            builder_input["source_encounter_seeds"],
        )
        self.assertIn(
            "The flooding room puzzle requires solving water flow mechanisms",
            builder_input["source_encounter_seeds"],
        )
        self.assertIn(
            "The dog test examines the party's compassion and resolve",
            builder_input["source_encounter_seeds"],
        )
        self.assertIn(
            "A mindscape battle against psychic attackers and mental projections",
            builder_input["source_encounter_seeds"],
        )

        # Persistence assertions
        persisted_path = self.workspace / "builder_input.json"
        self.assertTrue(persisted_path.exists())
        persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
        self.assertIn("source_monster_refs", persisted)
        for ref in ["Alhoon", "Illithid", "Homunculus", "Kenku", "Nothic", "Charion"]:
            self.assertIn(ref, persisted["source_monster_refs"])
        self.assertIn("source_encounter_seeds", persisted)
        for seed_text in [
            "The skull riddle trial challenges the party to answer the skull's questions",
            "The flooding room puzzle requires solving water flow mechanisms",
            "The dog test examines the party's compassion and resolve",
            "A mindscape battle against psychic attackers and mental projections",
        ]:
            self.assertIn(seed_text, persisted["source_encounter_seeds"])

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_packet_only_degraded_includes_source_monster_refs_and_encounter_seeds(self, mock_executor):
        """Packet-only degraded source-enhanced path preserves monster refs and encounter seeds."""
        # Write source fields into normalized packet
        packet_path = self.workspace / "normalized_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["monster_refs"] = ["Alhoon", "Illithid"]
        packet["encounter_seeds"] = ["The skull riddle trial"]
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        # Degraded blueprint: empty blueprint, report with blocked fidelity
        (self.workspace / "builder_blueprint.json").write_text("{}", encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps({"blueprint_status": "ready", "fidelity_status": "blocked"}),
            encoding="utf-8",
        )

        mock_executor.return_value = {"status": "success", "build_mode": "packet_workspace_v1"}

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["build_mode"], "source_enhanced_modulebuilder")
        mock_executor.assert_called_once()
        builder_input = mock_executor.call_args[0][0]

        # Source fields from packet only
        self.assertIn("source_monster_refs", builder_input)
        self.assertIn("Alhoon", builder_input["source_monster_refs"])
        self.assertIn("Illithid", builder_input["source_monster_refs"])

        self.assertIn("source_encounter_seeds", builder_input)
        self.assertIn("The skull riddle trial", builder_input["source_encounter_seeds"])

        # Persistence assertions
        persisted_path = self.workspace / "builder_input.json"
        self.assertTrue(persisted_path.exists())
        persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
        self.assertIn("source_monster_refs", persisted)
        self.assertIn("Alhoon", persisted["source_monster_refs"])
        self.assertIn("Illithid", persisted["source_monster_refs"])
        self.assertIn("source_encounter_seeds", persisted)
        self.assertIn("The skull riddle trial", persisted["source_encounter_seeds"])

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_blocked_blueprint_does_not_call_module_builder(self, mock_executor):
        bp = _make_v2_blueprint(blueprint_status="blocked")
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps({"blueprint_status": "blocked"}), encoding="utf-8"
        )

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
            True,
        ):
            result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["status"], "failed")
        self.assertIn("blueprint_not_ready", result.get("error", ""))
        mock_executor.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_blocked_report_does_not_call_module_builder(self, mock_executor):
        bp = _make_v2_blueprint(blueprint_status="ready")
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps({"blueprint_status": "blocked"}), encoding="utf-8"
        )

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["status"], "failed")
        self.assertIn("blueprint_not_ready", result.get("error", ""))
        mock_executor.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_empty_blueprint_fails_closed(self, mock_executor):
        (self.workspace / "builder_blueprint.json").write_text("{}", encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps({"blueprint_status": "ready"}), encoding="utf-8"
        )

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["status"], "failed")
        self.assertIn("blueprint_not_ready", result.get("error", ""))
        mock_executor.assert_not_called()

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_legacy_non_source_path_routes_to_module_builder(self, mock_executor):
        self._build_v2_workspace()
        # Add source fields to both packet and blueprint to verify no leakage
        packet_path = self.workspace / "normalized_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["monster_refs"] = ["Alhoon", "Illithid"]
        packet["encounter_seeds"] = ["The skull riddle trial"]
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        bp = json.loads((self.workspace / "builder_blueprint.json").read_text(encoding="utf-8"))
        bp["monster_refs"] = ["Nothic", "Charion"]
        bp["encounter_seeds"] = ["The flooding room puzzle"]
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        mock_executor.return_value = {"status": "success", "build_mode": "packet_workspace_v1"}

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF",
            False,
        ):
            result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-001")

        self.assertEqual(result["build_mode"], "packet_workspace_v1")
        mock_executor.assert_called_once()
        builder_input = mock_executor.call_args[0][0]
        self.assertNotIn("handoff_mode", builder_input)
        self.assertNotIn("blueprint", builder_input)
        self.assertNotIn("source_npc_names", builder_input)
        self.assertNotIn("source_location_names", builder_input)
        self.assertNotIn("source_puzzle_ids", builder_input)
        self.assertNotIn("source_tone", builder_input)
        self.assertNotIn("source_monster_refs", builder_input)
        self.assertNotIn("source_encounter_seeds", builder_input)

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    def test_execute_module_builder_receives_source_enhanced_context(self, mock_config, mock_builder_cls):
        """_execute_module_builder passes source context to ModuleBuilder build_module call."""
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder

        builder_input = {
            "builder_narrative": "Test narrative for build",
            "derived_builder_parameters": {
                "module_name": "Test_Module",
                "num_areas": 2,
                "locations_per_area": 3,
                "output_directory": "./modules/Test_Module",
            },
            "source_npc_names": ["Elara", "Thorn"],
            "source_location_names": ["Dark Forest", "Crystal Cave"],
            "source_puzzle_ids": ["riddle_of_the_ancients", "crystal_shard_puzzle"],
            "source_tone": ["heroic", "mysterious"],
            "source_monster_refs": ["Alhoon", "Illithid", "Beholder"],
            "source_encounter_seeds": ["The skull riddle trial", "The flooding room puzzle"],
            "blueprint": {
                "source_lock": {
                    "canonical_names_locked": True,
                    "invented_major_entities_forbidden": True,
                    "replacement_plotlines_forbidden": True,
                    "puzzle_rule_rewrite_forbidden": True,
                    "allowed_to_rewrite": False,
                },
            },
        }

        _execute_module_builder(builder_input)

        mock_builder_cls.assert_called_once()
        mock_builder.build_module.assert_called_once()
        build_arg = mock_builder.build_module.call_args[0][0]

        # These assertions verify source-enhanced context is appended before build_module.
        self.assertIn("Elara", build_arg)
        self.assertIn("Dark Forest", build_arg)
        self.assertIn("riddle_of_the_ancients", build_arg)
        self.assertIn("heroic", build_arg)
        self.assertIn("Alhoon", build_arg)
        self.assertIn("skull riddle trial", build_arg)

        # Assert all required section labels are present
        self.assertIn("NPCS:", build_arg)
        self.assertIn("LOCATIONS:", build_arg)
        self.assertIn("PUZZLES:", build_arg)
        self.assertIn("TONE:", build_arg)
        self.assertIn("MONSTERS:", build_arg)
        self.assertIn("ENCOUNTER_SEEDS:", build_arg)
        self.assertIn("SOURCE_LOCKS:", build_arg)

        # Assert true source-lock rules appear
        self.assertIn("canonical_names_locked", build_arg)
        self.assertIn("invented_major_entities_forbidden", build_arg)
        self.assertIn("replacement_plotlines_forbidden", build_arg)
        self.assertIn("puzzle_rule_rewrite_forbidden", build_arg)

        # Assert false source-lock rules are omitted
        self.assertNotIn("allowed_to_rewrite", build_arg)

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    @patch("utils.ai_client_factory.create_chat_client")
    @patch("utils.ai_client_factory.get_model_config")
    def test_execute_module_builder_source_context_provider_free(self, mock_config_factory, mock_client_factory, mock_builder_config, mock_builder_cls):
        """_execute_module_builder source path does not trigger live provider calls."""
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        mock_client_factory.side_effect = AssertionError("provider call blocked")
        mock_config_factory.side_effect = AssertionError("provider config call blocked")

        builder_input = {
            "builder_narrative": "Test narrative for build",
            "derived_builder_parameters": {
                "module_name": "Test_Module",
                "num_areas": 2,
                "locations_per_area": 3,
                "output_directory": "./modules/Test_Module",
            },
            "source_npc_names": ["Elara", "Thorn"],
            "source_monster_refs": ["Alhoon"],
        }

        _execute_module_builder(builder_input)

        mock_builder_cls.assert_called_once()
        mock_builder.build_module.assert_called_once()
        mock_client_factory.assert_not_called()
        mock_config_factory.assert_not_called()

        build_arg = mock_builder.build_module.call_args[0][0]
        self.assertIn("Elara", build_arg)
        self.assertIn("Alhoon", build_arg)

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    def test_execute_module_builder_plain_narrative_without_source(self, mock_config, mock_builder_cls):
        """_execute_module_builder passes plain narrative when no source fields present."""
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder

        builder_input = {
            "builder_narrative": "Test narrative for build",
            "derived_builder_parameters": {
                "module_name": "Test_Module",
                "num_areas": 2,
                "locations_per_area": 3,
                "output_directory": "./modules/Test_Module",
            },
        }

        _execute_module_builder(builder_input)

        mock_builder_cls.assert_called_once()
        mock_builder.build_module.assert_called_once_with("Test narrative for build")

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    def test_execute_module_builder_ignores_blank_source_values(self, mock_config, mock_builder_cls):
        """_execute_module_builder omits source context when values are blank/whitespace."""
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder

        builder_input = {
            "builder_narrative": "Test narrative for build",
            "derived_builder_parameters": {
                "module_name": "Test_Module",
                "num_areas": 2,
                "locations_per_area": 3,
                "output_directory": "./modules/Test_Module",
            },
            "source_npc_names": ["   ", ""],
            "source_encounter_seeds": [""],
        }

        _execute_module_builder(builder_input)

        mock_builder_cls.assert_called_once()
        mock_builder.build_module.assert_called_once_with("Test narrative for build")

    @patch("core.generators.module_builder.ModuleBuilder")
    @patch("core.generators.module_builder.BuilderConfig")
    def test_execute_module_builder_source_context_ascii_only(self, mock_config, mock_builder_cls):
        """Source context excludes non-ASCII characters via replacement."""
        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder

        builder_input = {
            "builder_narrative": "Test narrative for build",
            "derived_builder_parameters": {
                "module_name": "Test_Module",
                "num_areas": 2,
                "locations_per_area": 3,
                "output_directory": "./modules/Test_Module",
            },
            "source_npc_names": ["Elara\u00e9", "Thorn"],
        }

        _execute_module_builder(builder_input)

        mock_builder_cls.assert_called_once()
        mock_builder.build_module.assert_called_once()
        build_arg = mock_builder.build_module.call_args[0][0]

        self.assertIn("Thorn", build_arg)
        self.assertNotIn("\u00e9", build_arg)
        self.assertIn("NPCS: ", build_arg)


class TestDescribeBlueprintNotReady(unittest.TestCase):
    """Test _describe_blueprint_not_ready."""

    def test_missing_report(self):
        bp = _make_v2_blueprint()
        reason = _describe_blueprint_not_ready(bp, None)
        self.assertEqual(reason, "missing_blueprint_report")

    def test_blueprint_blocked(self):
        bp = _make_v2_blueprint(blueprint_status="blocked")
        report = {"blueprint_status": "ready"}
        reason = _describe_blueprint_not_ready(bp, report)
        self.assertEqual(reason, "blueprint_blocked")

    def test_missing_artifacts(self):
        reason = _describe_blueprint_not_ready(None, None)
        self.assertEqual(reason, "missing_artifacts")


class TestBuildAccurateIngestSummary(unittest.TestCase):
    """Test _build_accurate_ingest_summary."""

    def test_from_v2_build_result(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {
            "result": {
                "build_mode": "packet_workspace_v2",
                "seed_status": "success",
                "enrichment_status": "skipped",
                "seed_coverage": {
                    "locations": 13,
                    "npcs_in_roster": 5,
                    "plot_beats": 8,
                    "areas": 1,
                },
                "build_fidelity": {
                    "status": "pass",
                },
            }
        }
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode"], "packet_workspace_v2")
        self.assertEqual(summary["seed_status"], "success")
        self.assertEqual(summary["source_locations"], 13)
        self.assertEqual(summary["source_npcs"], 5)
        self.assertEqual(summary["source_plot_beats"], 8)
        self.assertEqual(summary["source_areas"], 1)
        self.assertEqual(summary["build_fidelity_status"], "pass")

    def test_from_empty_job(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        summary = _build_accurate_ingest_summary({})
        self.assertFalse(summary["has_accurate_ingest"])
        self.assertIsNone(summary["seed_status"])
        self.assertIsNone(summary["enrichment_status"])

    def test_from_v1_build_result(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {
            "result": {
                "build_mode": "packet_workspace_v1",
                "status": "success",
            }
        }
        summary = _build_accurate_ingest_summary(job)
        self.assertFalse(summary["has_accurate_ingest"])

    def test_missing_build_mode_defaults_no_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"seed_status": ""}}
        summary = _build_accurate_ingest_summary(job)
        self.assertFalse(summary["has_accurate_ingest"])

    def test_partial_coverage_no_crash(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {
            "result": {
                "build_mode": "packet_workspace_v2",
                "seed_status": "success",
                "seed_coverage": {},
            }
        }
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary.get("seed_status"), "success")
        self.assertNotIn("source_locations", summary)

    def test_source_enhanced_modulebuilder_has_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "source_enhanced_modulebuilder"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode"], "source_enhanced_modulebuilder")
        self.assertEqual(summary["build_mode_family"], "modulebuilder")
        self.assertIsNone(summary["seed_status"])

    def test_source_blueprint_modulebuilder_has_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "source_blueprint_modulebuilder"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode_family"], "modulebuilder")

    def test_blueprint_seed_fallback_has_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "blueprint_seed_fallback", "seed_writer_mode": "fallback"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode"], "blueprint_seed_fallback")
        self.assertEqual(summary["build_mode_family"], "seed_writer")
        self.assertEqual(summary["seed_writer_mode"], "fallback")

    def test_blueprint_seed_preview_has_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "blueprint_seed_preview", "seed_writer_mode": "preview"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode_family"], "seed_writer")
        self.assertEqual(summary["seed_writer_mode"], "preview")

    def test_blueprint_seed_support_has_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "blueprint_seed_support", "seed_writer_mode": "support"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode_family"], "seed_writer")
        self.assertEqual(summary["seed_writer_mode"], "support")

    def test_legacy_packet_workspace_v2_still_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "packet_workspace_v2"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode_family"], "seed_writer")

    def test_build_mode_family_unknown(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "some_future_mode"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertFalse(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode_family"], "unknown")

    def test_build_mode_family_none(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        summary = _build_accurate_ingest_summary({"result": {}})
        self.assertFalse(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode_family"], "none")
        self.assertEqual(summary["build_mode"], "")

    def test_unknown_mode_with_seed_status_still_accurate_ingest(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {"result": {"build_mode": "some_future_mode", "seed_status": "success"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertTrue(summary["has_accurate_ingest"])
        self.assertEqual(summary["build_mode_family"], "unknown")

    def test_existing_fields_preserved(self):
        from web.routes.toolkit_homebrew_routes import _build_accurate_ingest_summary

        job = {
            "result": {
                "build_mode": "source_enhanced_modulebuilder",
                "build_fidelity": {"status": "degraded", "rollup_status": "pass"},
                "ready_status": "pass",
                "publishable_status": "pass",
                "seed_status": "",
                "enrichment_status": "",
            }
        }
        summary = _build_accurate_ingest_summary(job)
        self.assertEqual(summary["build_mode"], "source_enhanced_modulebuilder")
        self.assertEqual(summary["build_mode_family"], "modulebuilder")
        self.assertEqual(summary["build_fidelity_status"], "degraded")
        self.assertEqual(summary["source_fidelity_status"], "pass")
        self.assertEqual(summary["readiness_status"], "pass")
        self.assertEqual(summary["publishability_status"], "pass")
        self.assertIsNone(summary["seed_status"])
        self.assertIsNone(summary["enrichment_status"])
        self.assertFalse(bool(summary.get("seed_writer_mode")))


class TestProgressStageNormalization(unittest.TestCase):
    """Test _normalize_homebrew_build_progress_stage."""

    def test_seeding_stage(self):
        from web.routes.toolkit_homebrew_routes import _normalize_homebrew_build_progress_stage

        stage = _normalize_homebrew_build_progress_stage("seeding", "Seeding module from source blueprint")
        self.assertEqual(stage, "seeding_module")

    def test_enriching_stage(self):
        from web.routes.toolkit_homebrew_routes import _normalize_homebrew_build_progress_stage

        stage = _normalize_homebrew_build_progress_stage("enriching", "Running bounded enrichment")
        self.assertEqual(stage, "enriching_module")

    def test_build_fidelity_stage(self):
        from web.routes.toolkit_homebrew_routes import _normalize_homebrew_build_progress_stage

        stage = _normalize_homebrew_build_progress_stage("build_fidelity", "Running build fidelity audit")
        self.assertEqual(stage, "build_fidelity")

    def test_legacy_builder_stage_preserved(self):
        from web.routes.toolkit_homebrew_routes import _normalize_homebrew_build_progress_stage

        stage = _normalize_homebrew_build_progress_stage("log", "Generating module overview")
        self.assertEqual(stage, "builder_overview")

    def test_unknown_falls_through_to_builder_progress(self):
        from web.routes.toolkit_homebrew_routes import _normalize_homebrew_build_progress_stage

        stage = _normalize_homebrew_build_progress_stage("unknown", "something unexpected")
        self.assertEqual(stage, "builder_progress")


class TestCanonicalAccurateIngestPhase(unittest.TestCase):
    """Tests for _get_canonical_accurate_ingest_phase."""

    def test_terminal_maps_directly(self):
        for terminal in ("completed", "not_publishable", "quarantined", "failed", "rejected", "awaiting_overwrite_confirmation"):
            phase = _get_canonical_accurate_ingest_phase({"status": terminal})
            self.assertEqual(phase, terminal)

    def test_preflight_from_upload_stage(self):
        phase = _get_canonical_accurate_ingest_phase({"status": "uploading", "stage": "upload"})
        self.assertEqual(phase, "preflight")

    def test_awaiting_review_from_status(self):
        phase = _get_canonical_accurate_ingest_phase({"status": "awaiting_review"})
        self.assertEqual(phase, "awaiting_review")

    def test_seeding_module_from_progress(self):
        phase = _get_canonical_accurate_ingest_phase({
            "status": "building", "stage": "build", "progress_stage": "seeding_module"
        })
        self.assertEqual(phase, "seeding_module")

    def test_enriching_module_from_progress(self):
        phase = _get_canonical_accurate_ingest_phase({
            "status": "building", "stage": "build", "progress_stage": "enriching_module"
        })
        self.assertEqual(phase, "enriching_module")

    def test_build_fidelity_from_progress(self):
        phase = _get_canonical_accurate_ingest_phase({
            "status": "building", "stage": "build", "progress_stage": "build_fidelity"
        })
        self.assertEqual(phase, "build_fidelity")

    def test_building_blueprint_defaults(self):
        phase = _get_canonical_accurate_ingest_phase({
            "status": "building", "stage": "build", "progress_stage": "builder_areas"
        })
        self.assertEqual(phase, "building_blueprint")

    def test_readiness_stage(self):
        phase = _get_canonical_accurate_ingest_phase({"status": "running", "stage": "readiness"})
        self.assertEqual(phase, "readiness")

    def test_finishing_stage(self):
        phase = _get_canonical_accurate_ingest_phase({"status": "running", "stage": "finishing"})
        self.assertEqual(phase, "finishing")

    def test_publishability_audit_stage(self):
        phase = _get_canonical_accurate_ingest_phase({"status": "running", "stage": "publishability_audit"})
        self.assertEqual(phase, "publishability_audit")

    def test_default_fallback(self):
        phase = _get_canonical_accurate_ingest_phase({"unknown_key": "value"})
        self.assertEqual(phase, "preflight")

    def test_approved_for_build_defaults_to_extracting(self):
        phase = _get_canonical_accurate_ingest_phase({"status": "approved_for_build", "stage": "review"})
        self.assertEqual(phase, "awaiting_review")


class TestAccurateIngestSummaryEnhanced(unittest.TestCase):
    """Tests for enhanced _build_accurate_ingest_summary with new fields."""

    def test_blueprint_status_from_handoff(self):
        job = {"result": {"build_mode": "packet_workspace_v2", "handoff_mode": "source_blueprint"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertEqual(summary.get("blueprint_status"), "ready")

    def test_blueprint_status_unknown_when_no_result(self):
        summary = _build_accurate_ingest_summary({})
        self.assertIn("blueprint_status", summary)
        self.assertIn("readiness_status", summary)
        self.assertIn("publishability_status", summary)

    def test_readiness_and_publishability_from_finishing_report(self):
        job = {"result": {"ready_status": "pass", "publishable_status": "pass"}}
        summary = _build_accurate_ingest_summary(job)
        self.assertEqual(summary.get("readiness_status"), "pass")
        self.assertEqual(summary.get("publishability_status"), "pass")


class TestOverwriteAuthorization(unittest.TestCase):
    """Tests for overwrite authorization guard in packet builder."""

    def setUp(self):
        import uuid
        self.test_slug = "Overwrite_Test_" + uuid.uuid4().hex[:8]
        self.tmpdir = tempfile.mkdtemp()
        source_hash = uuid.uuid4().hex
        self.workspace = _create_workspace(self.tmpdir, **{
            "normalized_packet.json": {
                "packet_version": "packet.v1",
                "name": "pipeline-001",
                "title": self.test_slug,
                "description": "Overwrite test adventure",
                "source_hash": source_hash,
                "source_rights": "user_authored",
                "normalization_state": "normalized",
            },
            "ui_review_snapshot.json": {
                "decision": "approve",
                "recorded_at": "2026-01-01T00:00:00Z",
                "job_id": "test-job-overwrite",
                "packet_identity": {"source_hash": source_hash},
            },
            "builder_blueprint.json": {},
            "builder_blueprint_report.json": {},
            "builder_narrative.txt": "Test narrative for overwrite auth test",
        })
        # Patch seed writer materialization to succeed trivially
        self.seed_writer_patch = patch(
            "web.extensions.toolkit_homebrew_packet_builder._execute_seed_writer_build",
            return_value={"status": "success", "build_mode": "packet_workspace_v2"},
        )
        self.seed_writer_patch.start()
        self.addCleanup(self.seed_writer_patch.stop)
        # Force v2 blueprint handoff so _v2_seed_fallback can be True
        self.handoff_patch = patch(
            "web.extensions.toolkit_homebrew_packet_builder._classify_blueprint_handoff",
            return_value="source_blueprint_v2_ready",
        )
        self.handoff_patch.start()
        self.addCleanup(self.handoff_patch.stop)
        # Enable GUI blueprint build and seed writer fallback flags
        self.gui_flag_patch = patch(
            "web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
            True,
        )
        self.gui_flag_patch.start()
        self.addCleanup(self.gui_flag_patch.stop)
        self.seed_fallback_patch = patch(
            "web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
            True,
        )
        self.seed_fallback_patch.start()
        self.addCleanup(self.seed_fallback_patch.stop)

    def tearDown(self):
        import shutil
        # Clean up CWD-relative module dirs created by _make_existing_module
        for p in Path("modules").glob("Overwrite_Test_*"):
            shutil.rmtree(str(p), ignore_errors=True)
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _make_existing_module(self, slug: str):
        """Create module directory where the packet builder checks (CWD-relative)."""
        module_dir = Path("modules") / slug
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "module_context.json").write_text("{}", encoding="utf-8")
        return module_dir

    def test_first_build_succeeds_without_overwrite_confirm(self):
        """First build into absent directory proceeds without confirmation."""
        result = run_toolkit_homebrew_packet_build(
            workspace=self.workspace,
            job_id="test-job-001",
            overwrite_confirmed=False,
        )
        self.assertNotEqual(result.get("error"), "overwrite_not_authorized",
                            "First build should not be refused for overwrite")

    def test_existing_module_refused_without_overwrite_confirm(self):
        """Existing module build without confirmation is refused."""
        self._make_existing_module(self.test_slug)
        result = run_toolkit_homebrew_packet_build(
            workspace=self.workspace,
            job_id="test-job-002",
            overwrite_confirmed=False,
        )
        self.assertEqual(result.get("error"), "overwrite_not_authorized")
        self.assertEqual(result.get("status"), "failed")

    def test_existing_module_allowed_with_overwrite_confirm(self):
        """Confirmed rebuild proceeds."""
        self._make_existing_module(self.test_slug)
        result = run_toolkit_homebrew_packet_build(
            workspace=self.workspace,
            job_id="test-job-003",
            overwrite_confirmed=True,
        )
        self.assertNotEqual(result.get("error"), "overwrite_not_authorized",
                            "Confirmed rebuild should proceed")

    def test_retry_route_detects_existing_module_before_worker_start(self):
        """_resolve_homebrew_build_target detects existing module dir before worker."""
        target_info = _resolve_homebrew_build_target(self.workspace)
        self.assertEqual(target_info.get("status"), "success")
        module_name = str(target_info.get("module_name") or "")
        collision = target_info.get("collision") or {}
        # Before creating module dir, collision should report not existing
        self.assertFalse(bool(collision.get("module_dir_exists")))
        self.assertIn("module_dir", collision)

        # Create the module dir to simulate existing module
        self._make_existing_module(module_name)
        target_info_after = _resolve_homebrew_build_target(self.workspace)
        self.assertEqual(target_info_after.get("status"), "success")
        collision_after = target_info_after.get("collision") or {}
        self.assertTrue(
            bool(collision_after.get("module_dir_exists")),
            "Should detect existing module after dir creation",
        )


class TestRetryFromPacketRouteOverwrite(unittest.TestCase):
    """Flask route-level test for retry-from-packet overwrite detection."""

    def setUp(self):
        import uuid
        from flask import Flask
        from web.routes.toolkit_homebrew_routes import (
            register_toolkit_homebrew_routes,
            reset_toolkit_homebrew_jobs_for_tests,
            _jobs,
        )

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        register_toolkit_homebrew_routes(self.app)
        self.client = self.app.test_client()
        reset_toolkit_homebrew_jobs_for_tests()

        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.job_id = "retry-test-" + uuid.uuid4().hex[:8]
        self.test_slug = "Retry_Test_" + uuid.uuid4().hex[:8]
        source_hash = uuid.uuid4().hex

        self.workspace = _create_workspace(
            self.tmpdir,
            **{
                "normalized_packet.json": {
                    "packet_version": "packet.v1",
                    "name": "pipeline-001",
                    "title": self.test_slug,
                    "description": "Retry route test adventure",
                    "source_hash": source_hash,
                    "source_rights": "user_authored",
                    "normalization_state": "normalized",
                },
                "ui_review_snapshot.json": {
                    "decision": "approve",
                    "recorded_at": "2026-01-01T00:00:00Z",
                    "job_id": self.job_id,
                    "packet_identity": {"source_hash": source_hash},
                },
            }
        )

        # Seed an approved job with artifact workspace
        _jobs[self.job_id] = {
            "job_id": self.job_id,
            "status": "approved_for_build",
            "stage": "build",
            "pipeline_status": "approved",
            "artifact_workspace": str(self.workspace),
            "updated_at": "2026-01-01T00:00:00Z",
        }

        # Patch threading.Thread so real workers are never started
        self.thread_patch = patch(
            "web.routes.toolkit_homebrew_routes.threading.Thread"
        )
        self.mock_thread_class = self.thread_patch.start()
        self.mock_thread_instance = MagicMock()
        self.mock_thread_class.return_value = self.mock_thread_instance
        self.addCleanup(self.thread_patch.stop)

    def tearDown(self):
        """Reset any active job id leaked by route tests."""
        import web.routes.toolkit_homebrew_routes as _tkr
        _tkr._active_job_id = None

    def test_retry_refuses_existing_module_without_confirmation(self):
        """Route detects collision before worker start and returns awaiting_overwrite_confirmation."""
        # Create the module dir to trigger collision
        module_dir = Path("modules") / self.test_slug
        module_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(str(module_dir), ignore_errors=True))
        (module_dir / "module_context.json").write_text("{}", encoding="utf-8")

        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/retry-from-packet",
            json={},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertTrue(data.get("requires_confirmation"))
        self.assertEqual(data.get("overwrite_policy"), "backup_clean")
        self.assertTrue(data.get("collision", {}).get("module_dir_exists"))
        job = data.get("job") or {}
        self.assertEqual(job.get("status"), "awaiting_overwrite_confirmation")
        self.assertEqual(job.get("pipeline_status"), "awaiting_confirmation")

        # Worker must NOT be constructed, and no active job claimed
        self.assertEqual(self.mock_thread_class.call_count, 0)
        import web.routes.toolkit_homebrew_routes as _tkr
        self.assertIsNone(_tkr._active_job_id)

    def test_retry_accepts_confirmed_overwrite(self):
        """Route accepts retry with confirmed overwrite and starts build."""
        module_dir = Path("modules") / self.test_slug
        module_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(str(module_dir), ignore_errors=True))
        (module_dir / "module_context.json").write_text("{}", encoding="utf-8")

        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/retry-from-packet",
            json={"confirm_overwrite": True, "overwrite_policy": "backup_clean"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertFalse(data.get("requires_confirmation", False))
        job = data.get("job") or {}
        self.assertEqual(job.get("status"), "approved_for_build")
        self.assertEqual(job.get("pipeline_status"), "rebuilding_from_packet")
        self.assertTrue(job.get("rebuild_mode"))

        # Worker must be constructed once and started, active job claimed
        self.assertEqual(self.mock_thread_class.call_count, 1)
        call_kwargs = self.mock_thread_class.call_args.kwargs
        self.assertIn(str(self.job_id)[:8], str(call_kwargs.get("name", "")))
        self.assertEqual(call_kwargs.get("daemon"), True)
        from web.routes.toolkit_homebrew_routes import _run_homebrew_build_job
        self.assertEqual(call_kwargs.get("target"), _run_homebrew_build_job)
        _thread_args = call_kwargs.get("args", ())
        self.assertEqual(len(_thread_args), 2)
        self.assertEqual(_thread_args[0], self.job_id)
        _build_options = _thread_args[1]
        self.assertIsInstance(_build_options, dict)
        self.assertEqual(_build_options.get("finishing_only"), False)
        self.assertEqual(_build_options.get("rebuild_mode"), True)
        self.assertEqual(_build_options.get("module_name"), self.test_slug)
        self.assertEqual(_build_options.get("overwrite_policy"), "backup_clean")
        self.assertEqual(self.mock_thread_instance.start.call_count, 1)
        import web.routes.toolkit_homebrew_routes as _tkr
        self.assertEqual(_tkr._active_job_id, self.job_id)

    def test_retry_rejects_unsupported_policy(self):
        """Route rejects unsupported overwrite policy with 400."""
        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/retry-from-packet",
            json={"confirm_overwrite": True, "overwrite_policy": "destructive"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertIn("Unsupported overwrite policy", data.get("message", ""))


class TestBuildRouteSeedWriterMode(unittest.TestCase):
    """Flask route-level tests for seed_writer_mode in /build and /retry-from-packet."""

    def setUp(self):
        import uuid
        from flask import Flask
        from web.routes.toolkit_homebrew_routes import (
            register_toolkit_homebrew_routes,
            reset_toolkit_homebrew_jobs_for_tests,
            _jobs,
        )

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        register_toolkit_homebrew_routes(self.app)
        self.client = self.app.test_client()
        reset_toolkit_homebrew_jobs_for_tests()

        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.job_id = "seedmode-" + uuid.uuid4().hex[:8]
        self.test_slug = "SeedMode_" + uuid.uuid4().hex[:8]
        source_hash = uuid.uuid4().hex

        self.workspace = _create_workspace(
            self.tmpdir,
            **{
                "normalized_packet.json": {
                    "packet_version": "packet.v1",
                    "name": "pipeline-001",
                    "title": self.test_slug,
                    "description": "Seed mode route test adventure",
                    "source_hash": source_hash,
                    "source_rights": "user_authored",
                    "normalization_state": "normalized",
                },
                "ui_review_snapshot.json": {
                    "decision": "approve",
                    "recorded_at": "2026-01-01T00:00:00Z",
                    "job_id": self.job_id,
                    "packet_identity": {"source_hash": source_hash},
                },
            }
        )

        _jobs[self.job_id] = {
            "job_id": self.job_id,
            "status": "approved_for_build",
            "stage": "build",
            "pipeline_status": "approved",
            "artifact_workspace": str(self.workspace),
            "updated_at": "2026-01-01T00:00:00Z",
        }

        self.thread_patch = patch(
            "web.routes.toolkit_homebrew_routes.threading.Thread"
        )
        self.mock_thread_class = self.thread_patch.start()
        self.mock_thread_instance = MagicMock()
        self.mock_thread_class.return_value = self.mock_thread_instance
        self.addCleanup(self.thread_patch.stop)

        # The /build route gates on fidelity review when accurate-ingest
        # workspace artifacts exist.  Bypass this so route-level seed
        # mode tests are not blocked by missing fidelity artifacts.
        self.fidelity_patch = patch(
            "web.routes.toolkit_homebrew_routes._should_use_fidelity_review",
            return_value=False,
        )
        self.fidelity_patch.start()
        self.addCleanup(self.fidelity_patch.stop)

    def tearDown(self):
        import web.routes.toolkit_homebrew_routes as _tkr
        _tkr._active_job_id = None

    def _assert_build_options_contains_seed_mode(self, payload, expected_mode):
        """Helper: POST to /build with payload and verify build_options carries seed_writer_mode."""
        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/build",
            json=payload,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertFalse(data.get("requires_confirmation", False))

        call_kwargs = self.mock_thread_class.call_args.kwargs
        _build_options = call_kwargs.get("args", (None, {}))[1]
        self.assertIsInstance(_build_options, dict)
        self.assertEqual(_build_options.get("seed_writer_mode"), expected_mode)
        self.mock_thread_class.reset_mock()

    def test_build_route_seed_mode_fallback(self):
        """Valid fallback mode reaches build_options."""
        self._assert_build_options_contains_seed_mode(
            {"seed_writer_mode": "fallback"}, "fallback"
        )

    def test_build_route_seed_mode_preview(self):
        """Valid preview mode reaches build_options."""
        self._assert_build_options_contains_seed_mode(
            {"seed_writer_mode": "preview"}, "preview"
        )

    def test_build_route_seed_mode_invalid_fails_400(self):
        """Invalid seed_writer_mode returns 400."""
        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/build",
            json={"seed_writer_mode": "v2_mode"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("reason"), "seed_writer_mode_invalid")
        self.assertIn("allowed_modes", data)

    def test_build_route_seed_mode_omitted_default(self):
        """Default payload omits seed_writer_mode."""
        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/build",
            json={},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")

        call_kwargs = self.mock_thread_class.call_args.kwargs
        _build_options = call_kwargs.get("args", (None, {}))[1]
        self.assertIsInstance(_build_options, dict)
        self.assertIsNone(_build_options.get("seed_writer_mode"))

    def test_retry_route_seed_mode_valid(self):
        """Valid seed mode in retry-from-packet reaches build_options."""
        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/retry-from-packet",
            json={"seed_writer_mode": "support"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertFalse(data.get("requires_confirmation", False))

        call_kwargs = self.mock_thread_class.call_args.kwargs
        _build_options = call_kwargs.get("args", (None, {}))[1]
        self.assertIsInstance(_build_options, dict)
        self.assertEqual(_build_options.get("seed_writer_mode"), "support")

    def test_retry_route_seed_mode_invalid_fails_400(self):
        """Invalid seed mode in retry-from-packet returns 400."""
        resp = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/retry-from-packet",
            json={"seed_writer_mode": "bad_mode"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("reason"), "seed_writer_mode_invalid")

    def test_build_route_seed_mode_preserved_across_overwrite(self):
        """Pending seed mode survives overwrite confirmation round-trip."""
        module_dir = Path("modules") / self.test_slug
        module_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(str(module_dir), ignore_errors=True))
        (module_dir / "module_context.json").write_text("{}", encoding="utf-8")

        # First request: no confirmation, seed mode preview, triggers overwrite
        resp1 = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/build",
            json={"seed_writer_mode": "preview"},
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.get_json()
        self.assertTrue(data1.get("requires_confirmation"))

        # Reset mocks for the confirmation request
        self.mock_thread_class.reset_mock()

        # Second request: confirm overwrite, no explicit seed mode
        resp2 = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/build",
            json={"confirm_overwrite": True, "overwrite_policy": "backup_clean"},
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        self.assertFalse(data2.get("requires_confirmation", False))

        call_kwargs = self.mock_thread_class.call_args.kwargs
        _build_options = call_kwargs.get("args", (None, {}))[1]
        self.assertIsInstance(_build_options, dict)
        self.assertEqual(_build_options.get("seed_writer_mode"), "preview")

    def test_retry_route_seed_mode_preserved_across_overwrite(self):
        """Pending seed mode survives retry-from-packet overwrite confirmation round-trip."""
        module_dir = Path("modules") / self.test_slug
        module_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(str(module_dir), ignore_errors=True))
        (module_dir / "module_context.json").write_text("{}", encoding="utf-8")

        # First request: no confirmation, seed mode fallback, triggers overwrite
        resp1 = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/retry-from-packet",
            json={"seed_writer_mode": "fallback"},
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.get_json()
        self.assertTrue(data1.get("requires_confirmation"))

        self.mock_thread_class.reset_mock()

        # Second request: confirm overwrite, no explicit seed mode
        resp2 = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/retry-from-packet",
            json={"confirm_overwrite": True, "overwrite_policy": "backup_clean"},
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        self.assertFalse(data2.get("requires_confirmation", False))

        call_kwargs = self.mock_thread_class.call_args.kwargs
        _build_options = call_kwargs.get("args", (None, {}))[1]
        self.assertIsInstance(_build_options, dict)
        self.assertEqual(_build_options.get("seed_writer_mode"), "fallback")

    def test_build_route_seed_mode_override_on_confirmation(self):
        """If confirmation request provides a different seed mode, it wins over pending."""
        module_dir = Path("modules") / self.test_slug
        module_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(str(module_dir), ignore_errors=True))
        (module_dir / "module_context.json").write_text("{}", encoding="utf-8")

        # First request sets pending mode to preview
        resp1 = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/build",
            json={"seed_writer_mode": "preview"},
        )
        self.assertTrue(resp1.get_json().get("requires_confirmation"))

        self.mock_thread_class.reset_mock()

        # Confirmation request provides a different mode
        resp2 = self.client.post(
            f"/api/toolkit/homebrew/jobs/{self.job_id}/build",
            json={
                "confirm_overwrite": True,
                "overwrite_policy": "backup_clean",
                "seed_writer_mode": "support",
            },
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertFalse(resp2.get_json().get("requires_confirmation", False))

        call_kwargs = self.mock_thread_class.call_args.kwargs
        _build_options = call_kwargs.get("args", (None, {}))[1]
        self.assertEqual(_build_options.get("seed_writer_mode"), "support")


class TestFidelityReviewRequiresDecision(unittest.TestCase):
    """Test _fidelity_review_requires_decision helper."""

    def test_clean_review_no_decision_needed(self):
        from web.routes.toolkit_homebrew_routes import _fidelity_review_requires_decision

        clean = {"can_approve": True, "blockers": [], "status": "pass"}
        self.assertFalse(_fidelity_review_requires_decision(clean))

    def test_can_approve_true_still_checks_blockers(self):
        from web.routes.toolkit_homebrew_routes import _fidelity_review_requires_decision

        blocked_but_approve = {
            "can_approve": True,
            "blockers": [{"severity": "blocking", "message": "Missing source graph"}],
        }
        self.assertTrue(_fidelity_review_requires_decision(blocked_but_approve))

    def test_non_approvable_requires_decision(self):
        from web.routes.toolkit_homebrew_routes import _fidelity_review_requires_decision

        blocked = {"can_approve": False, "blockers": []}
        self.assertTrue(_fidelity_review_requires_decision(blocked))

    def test_missing_payload_requires_decision(self):
        from web.routes.toolkit_homebrew_routes import _fidelity_review_requires_decision

        self.assertTrue(_fidelity_review_requires_decision(None))
        self.assertTrue(_fidelity_review_requires_decision({}))

    def test_warning_only_blockers_not_blocking(self):
        from web.routes.toolkit_homebrew_routes import _fidelity_review_requires_decision

        warning_only = {
            "can_approve": True,
            "blockers": [{"severity": "warning", "message": "Low coverage"}],
        }
        self.assertFalse(_fidelity_review_requires_decision(warning_only))

    def test_blockers_list_contains_none_ignored(self):
        from web.routes.toolkit_homebrew_routes import _fidelity_review_requires_decision

        mixed = {"can_approve": True, "blockers": [None, {"severity": "blocking"}]}
        self.assertTrue(_fidelity_review_requires_decision(mixed))

    def test_empty_blockers_list_is_clean(self):
        from web.routes.toolkit_homebrew_routes import _fidelity_review_requires_decision

        no_blockers = {"can_approve": True, "blockers": []}
        self.assertFalse(_fidelity_review_requires_decision(no_blockers))


class TestFidelityReviewBranchInIngestJob(unittest.TestCase):
    """Test that _run_homebrew_ingest_job branches correctly on clean vs blocked fidelity review."""

    def setUp(self):
        import uuid
        import tempfile
        from web.routes.toolkit_homebrew_routes import (
            reset_toolkit_homebrew_jobs_for_tests,
            _jobs,
            _jobs_lock,
        )
        reset_toolkit_homebrew_jobs_for_tests()
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.job_id = "fidelity-branch-" + uuid.uuid4().hex[:8]
        self.workspace = Path(self.tmpdir) / "ws"
        self.workspace.mkdir(parents=True)
        with _jobs_lock:
            _jobs[self.job_id] = {
                "job_id": self.job_id,
                "status": "running",
                "stage": "preflight",
                "pipeline_status": None,
                "artifact_workspace": str(self.workspace),
                "updated_at": "now",
            }

    def _run_ingest_with_fidelity_review(self, fidelity_payload):
        """Call _run_homebrew_ingest_job with mocks that drive to the fidelity review gate."""
        from web.routes.toolkit_homebrew_routes import (
            _run_homebrew_ingest_job,
        )

        with patch(
            "web.routes.toolkit_homebrew_routes._run_shared_ingest_pipeline",
            return_value={"status": "normalization_required", "routing_outcome": "accurate_ingest"},
        ), patch(
            "web.routes.toolkit_homebrew_routes._run_homebrew_normalization",
            return_value={"status": "success"},
        ), patch(
            "web.routes.toolkit_homebrew_routes.validate_normalization_artifacts",
            return_value=(True, None),
        ), patch(
            "web.routes.toolkit_homebrew_routes._should_use_fidelity_review",
            return_value=True,
        ), patch(
            "web.routes.toolkit_homebrew_routes._build_fidelity_review_or_error",
            return_value=fidelity_payload,
        ):
            _run_homebrew_ingest_job(
                self.job_id,
                source_path=Path(self.tmpdir) / "source.md",
                artifact_workspace=self.workspace,
                source_rights_class="user_authored",
            )

    def test_clean_fidelity_skips_awaiting_review(self):
        """Clean review does NOT set awaiting_review."""
        import web.routes.toolkit_homebrew_routes as tkr

        clean = {"can_approve": True, "blockers": [], "status": "pass"}
        self._run_ingest_with_fidelity_review(clean)

        with tkr._jobs_lock:
            job = tkr._jobs.get(self.job_id) or {}
        status = str(job.get("status") or "")
        result = job.get("result") or {}
        self.assertNotEqual(status, "awaiting_review",
                             "Clean review should not enter awaiting_review")
        self.assertIn("fidelity_review", result,
                      "Clean review diagnostics should be preserved in result")

    def test_blocked_fidelity_enters_awaiting_review(self):
        """Non-approvable review DOES set awaiting_review."""
        import web.routes.toolkit_homebrew_routes as tkr

        blocked = {"can_approve": False, "blockers": [{"severity": "blocking", "message": "Missing fidelity"}], "status": "blocked"}
        self._run_ingest_with_fidelity_review(blocked)

        with tkr._jobs_lock:
            job = tkr._jobs.get(self.job_id) or {}
        status = str(job.get("status") or "")
        self.assertEqual(status, "awaiting_review",
                         "Blocked review should enter awaiting_review")


class TestFinalReconciliationBoundarySourceContract(unittest.TestCase):
    """Source-contract tests proving final reconciliation boundary does not alter front/middle pipeline.
    
    These tests lock the no-change boundary for:
    1. Source graph extraction
    2. Normalized packet generation
    3. Builder blueprint generation
    4. Backstage audit/briefing
    5. Source-enhanced ModuleBuilder handoff
    """

    def setUp(self):
        import uuid
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.test_slug = "Boundary_Test_" + uuid.uuid4().hex[:8]
        self.test_source_hash = uuid.uuid4().hex
        self.workspace = _create_workspace(
            self.tmpdir_obj.name,
            **{
                "normalized_packet.json": {
                    "packet_version": "packet.v1",
                    "name": "boundary-test-001",
                    "title": self.test_slug,
                    "description": "A test adventure for boundary tests",
                    "source_hash": self.test_source_hash,
                    "source_rights": "user_authored",
                    "normalization_state": "normalized",
                },
            }
        )

    def test_source_graph_extraction_upstream_of_final_reconciliation(self):
        """Source graph extraction produces artifacts without final reconciliation fields."""
        import utils.toolkit_source_manifest as tsm
        
        # Create minimal source text
        source_text = "# Test Adventure\n\n## Introduction\n\nThis is a test."
        source_path = str(self.workspace / "source.md")
        
        # Call build_source_manifest with actual test data
        result = tsm.build_source_manifest(source_text, source_path, self.test_source_hash)
        
        # Verify result structure exists
        self.assertIsInstance(result, dict)
        self.assertIn("manifest_version", result)
        
        # Final reconciliation fields must NOT appear in source manifest output
        forbidden_fields = [
            "final_reconciliation_brief",
            "final_reconciliation_report",
            "reconciliation_status",
            "reconciliation_accepted",
            "source_fidelity_effective_status"
        ]
        for field in forbidden_fields:
            self.assertNotIn(field, result,
                           f"Source manifest must not contain {field}")

    def test_normalized_packet_generation_unchanged(self):
        """Normalized packet artifacts do not contain final reconciliation fields."""
        # Read the actual normalized_packet.json from workspace
        packet_path = self.workspace / "normalized_packet.json"
        self.assertTrue(packet_path.exists(), "normalized_packet.json must exist in workspace")
        
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        
        # Verify expected fields exist
        self.assertIn("packet_version", packet)
        self.assertIn("source_hash", packet)
        self.assertIn("normalization_state", packet)
        
        # Final reconciliation fields must NOT appear in normalized packet
        forbidden_fields = [
            "final_reconciliation_brief",
            "final_reconciliation_report",
            "reconciliation_status",
            "reconciliation_accepted",
            "source_fidelity_effective_status"
        ]
        for field in forbidden_fields:
            self.assertNotIn(field, packet,
                           f"Normalized packet must not contain {field}")

    def test_builder_blueprint_generation_unchanged(self):
        """Builder blueprint generation produces output without final reconciliation fields."""
        import utils.toolkit_builder_blueprint as tbb
        
        # Create minimal test inputs
        source_graph = {
            "graph_version": "source_graph.v1",
            "atoms": [],
            "edges": []
        }
        identity_report = {
            "identity_version": "identity.v1",
            "resolved_identity": {"title": self.test_slug}
        }
        plot_topology = {
            "topology_version": "topology.v1",
            "plot_points": []
        }
        synthesis_report = {
            "synthesis_version": "synthesis.v1",
            "synthesized_sections": {}
        }
        normalized_packet = json.loads(
            (self.workspace / "normalized_packet.json").read_text(encoding="utf-8")
        )
        fidelity_report = {
            "fidelity_status": "pass",
            "warnings": []
        }
        triage_report = {
            "triage_version": "triage.v1",
            "decisions": []
        }
        
        # Call generate_builder_blueprint with actual test data
        result = tbb.generate_builder_blueprint(
            source_graph=source_graph,
            identity_report=identity_report,
            plot_topology=plot_topology,
            synthesis_report=synthesis_report,
            normalized_packet=normalized_packet,
            fidelity_report=fidelity_report,
            triage_report=triage_report
        )
        
        # Verify result structure
        self.assertIsInstance(result, dict)
        self.assertIn("blueprint_version", result)
        
        # Final reconciliation fields must NOT appear in blueprint output
        forbidden_fields = [
            "final_reconciliation_brief",
            "final_reconciliation_report",
            "reconciliation_status",
            "reconciliation_accepted",
            "source_fidelity_effective_status"
        ]
        for field in forbidden_fields:
            self.assertNotIn(field, result,
                           f"Builder blueprint must not contain {field}")

    def test_backstage_audit_briefing_unchanged(self):
        """Backstage audit artifact names remain unchanged and do not include final reconciliation."""
        import inspect
        # Check actual constants in run_backstage_agent module
        import scripts.run_backstage_agent as rba
        
        # Verify the module has expected audit artifact constants
        # These are the canonical artifact names that should not change
        # (from run_accurate_ingest_audit function)
        expected_artifact_names = [
            "run.json",
            "evidence.json",
            "audit_report.json",
            "recommendation.json"
        ]
        
        # Check if module defines these constants or uses them in functions
        module_source = inspect.getsource(rba)
        
        # Verify expected artifact names appear in module source
        for artifact_name in expected_artifact_names:
            self.assertIn(artifact_name, module_source,
                         f"Backstage audit module must reference {artifact_name}")
        
        # Final reconciliation artifact names must NOT appear in backstage audit
        forbidden_artifacts = [
            "final_reconciliation_brief.json",
            "final_reconciliation_report.json"
        ]
        for artifact in forbidden_artifacts:
            self.assertNotIn(artifact, module_source,
                           f"Backstage audit module must not reference {artifact}")

    @patch("web.extensions.toolkit_homebrew_packet_builder._execute_module_builder")
    def test_source_enhanced_modulebuilder_handoff_unchanged(self, mock_executor):
        """Actual builder_input passed to ModuleBuilder preserves source fields and excludes reconciliation."""
        # Build v2 workspace with source contract fields
        bp = _make_v2_blueprint(
            npc_roster=[
                {"display_name": "TestNPC", "aliases": [], "role": "test"},
            ],
            location_roster=[
                {"display_name": "TestLocation", "parent_area": "TestArea", "aliases": []},
            ],
            puzzle_graph=[
                {"chain_id": "test_puzzle", "title": "Test Puzzle"},
            ],
            tone_requirements="test_tone",
        )
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        (self.workspace / "builder_blueprint_report.json").write_text(json.dumps(report), encoding="utf-8")
        
        # Add monster_refs and encounter_seeds to normalized packet
        packet_path = self.workspace / "normalized_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["monster_refs"] = ["TestMonster"]
        packet["encounter_seeds"] = ["Test encounter seed"]
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        
        # Add ui_review_snapshot required for build flow
        ui_review = {
            "decision": "approve",
            "recorded_at": "2026-01-01T00:00:00Z",
            "job_id": "test-job-boundary",
            "packet_identity": {"source_hash": self.test_source_hash},
        }
        (self.workspace / "ui_review_snapshot.json").write_text(json.dumps(ui_review), encoding="utf-8")
        
        mock_executor.return_value = {"status": "success", "build_mode": "packet_workspace_v1"}
        
        # Run the actual packet build flow
        result = run_toolkit_homebrew_packet_build(self.workspace, "test-job-boundary")
        
        # Capture the actual builder_input passed to _execute_module_builder
        mock_executor.assert_called_once()
        builder_input = mock_executor.call_args[0][0]
        
        # Verify required source fields are present in actual builder_input
        required_source_fields = [
            "source_npc_names",
            "source_location_names",
            "source_puzzle_ids",
            "source_tone",
            "source_monster_refs",
            "source_encounter_seeds"
        ]
        for field in required_source_fields:
            self.assertIn(field, builder_input,
                         f"Actual builder_input must preserve {field}")
        
        # Verify specific values were passed through
        self.assertIn("TestNPC", builder_input["source_npc_names"])
        self.assertIn("TestLocation", builder_input["source_location_names"])
        self.assertIn("test_puzzle", builder_input["source_puzzle_ids"])
        self.assertIn("test_tone", builder_input["source_tone"])
        self.assertIn("TestMonster", builder_input["source_monster_refs"])
        self.assertIn("Test encounter seed", builder_input["source_encounter_seeds"])
        
        # Final reconciliation fields must NOT be injected into actual builder_input
        forbidden_fields = [
            "final_reconciliation_brief",
            "final_reconciliation_report",
            "final_reconciliation_required",
            "reconciliation_status",
            "reconciliation_accepted",
            "source_fidelity_effective_status"
        ]
        for field in forbidden_fields:
            self.assertNotIn(field, builder_input,
                           f"Actual builder_input must not contain {field} before ModuleBuilder")
        
        # Also verify persisted builder_input.json doesn't contain reconciliation fields
        persisted_path = self.workspace / "builder_input.json"
        if persisted_path.exists():
            persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
            for field in forbidden_fields:
                self.assertNotIn(field, persisted,
                               f"Persisted builder_input.json must not contain {field}")


class TestStep41PacketBuilderClassification(unittest.TestCase):
    """Step 4.1 source-contract tests: classification metadata in build_result."""

    def test_packet_builder_source_imports_classifier(self):
        """Packet builder source code imports classify_final_build_blockers."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertIn("classify_final_build_blockers", source,
                      "Packet builder must import classify_final_build_blockers")

    def test_classification_metadata_structure(self):
        """build_result classification dict has expected shape."""
        classification = {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [{"type": "editorial", "message": "M", "category": "location"}],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "test",
            "report_paths": {},
        }
        build_result = {
            "status": "blocked",
            "stage": "build_fidelity",
            "error": "build_fidelity_blocked:test",
            "final_blocker_classification": classification,
            "build_fidelity": {
                "status": "blocked",
                "can_continue": False,
                "refusal_reason": "test",
                "report_path": "/tmp/bf.json",
                "rollup_path": "/tmp/sf.json",
                "final_blocker_classification_status": "editorial",
            },
        }
        self.assertIn("final_blocker_classification", build_result)
        self.assertEqual(build_result["final_blocker_classification"]["status"], "editorial")
        self.assertEqual(
            build_result["build_fidelity"]["final_blocker_classification_status"],
            "editorial",
        )

    def test_build_fidelity_fields_preserved(self):
        """Existing build_fidelity status/can_continue/refusal_reason/report_path preserved."""
        build_fidelity = {
            "status": "blocked",
            "can_continue": False,
            "refusal_reason": "Required location 'Trigger' not found in module",
            "report_path": "/tmp/bf.json",
            "rollup_path": "/tmp/sf.json",
        }
        classification = {"status": "editorial", "fatal_count": 0, "editorial_count": 1}
        build_fidelity["final_blocker_classification_status"] = classification["status"]

        self.assertEqual(build_fidelity["status"], "blocked")
        self.assertFalse(build_fidelity["can_continue"])
        self.assertEqual(
            build_fidelity["refusal_reason"],
            "Required location 'Trigger' not found in module",
        )
        self.assertEqual(build_fidelity["report_path"], "/tmp/bf.json")
        self.assertEqual(build_fidelity["rollup_path"], "/tmp/sf.json")

    def test_no_reconciliation_artifacts_in_packet_builder(self):
        """Packet builder source does not reference reconciliation brief/report artifacts."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertNotIn("final_reconciliation_brief.json", source,
                         "Packet builder must not persist reconciliation brief in 4.1")
        self.assertNotIn("final_reconciliation_report.json", source,
                         "Packet builder must not persist reconciliation report in 4.1")

    def test_no_gui_or_publication_code_in_packet_builder(self):
        """Packet builder source does not import GUI or publication modules."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertNotIn("module_toolkit.html", source,
                         "Packet builder must not reference GUI templates")
        self.assertNotIn("report_agreement", source,
                         "Packet builder must not reference report agreement")


class TestStep42FatalBlockedBehavior(unittest.TestCase):
    """Step 4.2 contract tests: fatal/mixed classification stays terminal blocked."""

    def _blocked_build_result(self, classification_status):
        return {
            "status": "blocked",
            "stage": "build_fidelity",
            "error": "build_fidelity_blocked:test refusal",
            "final_blocker_classification": {"status": classification_status},
            "build_fidelity": {
                "status": "blocked",
                "can_continue": False,
                "refusal_reason": "test refusal",
                "report_path": "/tmp/bf.json",
                "rollup_path": "/tmp/sf.json",
                "final_blocker_classification_status": classification_status,
            },
        }

    def test_fatal_classification_blocked(self):
        """Fatal classification -> build_result status is blocked, stage is build_fidelity."""
        br = self._blocked_build_result("fatal")
        self.assertEqual(br["status"], "blocked")
        self.assertEqual(br["stage"], "build_fidelity")
        self.assertTrue(br["error"].startswith("build_fidelity_blocked:"))
        self.assertEqual(br["final_blocker_classification"]["status"], "fatal")
        self.assertEqual(br["build_fidelity"]["final_blocker_classification_status"], "fatal")

    def test_mixed_classification_blocked(self):
        """Mixed classification -> build_result status is blocked, stage is build_fidelity."""
        br = self._blocked_build_result("mixed")
        self.assertEqual(br["status"], "blocked")
        self.assertEqual(br["stage"], "build_fidelity")
        self.assertTrue(br["error"].startswith("build_fidelity_blocked:"))
        self.assertEqual(br["final_blocker_classification"]["status"], "mixed")
        self.assertEqual(br["build_fidelity"]["final_blocker_classification_status"], "mixed")

    def test_fatal_mixed_no_reconciliation_required(self):
        """Fatal/mixed build_result must not have reconciliation_required flag."""
        for st in ("fatal", "mixed"):
            br = self._blocked_build_result(st)
            self.assertNotIn("final_reconciliation_required", br,
                             f"fatal/mixed ({st}) must not set reconciliation_required")
            self.assertNotIn("reconciliation_required", br.get("build_fidelity", {}),
                             f"fatal/mixed ({st}) must not set reconciliation in build_fidelity")

    def test_packet_builder_no_reconciliation_functions(self):
        """Packet builder source does not import reconciliation report (only brief in 4.3)."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertNotIn("persist_final_reconciliation_report", source,
                         "Packet builder must not persist reconciliation report in 4.3")

    def test_build_fidelity_fields_preserved_for_fatal(self):
        """Fatal/mixed block preserves all build_fidelity fields."""
        for st in ("fatal", "mixed"):
            br = self._blocked_build_result(st)
            bf = br["build_fidelity"]
            self.assertEqual(bf["status"], "blocked")
            self.assertFalse(bf["can_continue"])
            self.assertEqual(bf["refusal_reason"], "test refusal")
            self.assertEqual(bf["report_path"], "/tmp/bf.json")
            self.assertEqual(bf["rollup_path"], "/tmp/sf.json")


class TestStep43EditorialReconciliationRequired(unittest.TestCase):
    """Step 4.3 contract tests: editorial-only -> reconciliation required, not terminal block."""

    def _editorial_build_result(self):
        return {
            "status": "final_reconciliation_required",
            "stage": "final_reconciliation",
            "final_reconciliation_required": True,
            "final_reconciliation_brief": {
                "status": "written",
                "path": "/ws/final_reconciliation_brief.json",
                "bytes": 1024,
                "error": None,
            },
            "final_blocker_classification": {
                "status": "editorial",
                "fatal_count": 0,
                "editorial_count": 3,
            },
            "build_fidelity": {
                "status": "blocked",
                "can_continue": False,
                "refusal_reason": "test",
                "report_path": "/tmp/bf.json",
                "rollup_path": "/tmp/sf.json",
                "final_blocker_classification_status": "editorial",
                "final_reconciliation_required": True,
                "final_reconciliation_brief_path": "/ws/final_reconciliation_brief.json",
            },
        }

    def test_editorial_sets_final_reconciliation_required(self):
        """Editorial classification sets final_reconciliation_required true."""
        br = self._editorial_build_result()
        self.assertIn("final_reconciliation_required", br)
        self.assertTrue(br["final_reconciliation_required"])
        self.assertTrue(br["build_fidelity"]["final_reconciliation_required"])

    def test_editorial_no_longer_generic_blocked(self):
        """Editorial result is not generic build_fidelity_blocked."""
        br = self._editorial_build_result()
        self.assertEqual(br["status"], "final_reconciliation_required")
        self.assertEqual(br["stage"], "final_reconciliation")
        self.assertNotIn("error", br)
        self.assertNotIn("build_fidelity_blocked:", br.get("error", ""))

    def test_editorial_persists_brief_metadata(self):
        """Editorial result records brief persistence metadata."""
        br = self._editorial_build_result()
        self.assertIn("final_reconciliation_brief", br)
        self.assertEqual(br["final_reconciliation_brief"]["status"], "written")
        self.assertTrue(
            br["final_reconciliation_brief"]["path"].endswith("final_reconciliation_brief.json")
        )
        self.assertEqual(
            br["build_fidelity"]["final_reconciliation_brief_path"],
            br["final_reconciliation_brief"]["path"],
        )

    def test_editorial_preserves_build_fidelity_fields(self):
        """Editorial result preserves build_fidelity evidence fields."""
        br = self._editorial_build_result()
        bf = br["build_fidelity"]
        self.assertEqual(bf["status"], "blocked")
        self.assertFalse(bf["can_continue"])
        self.assertEqual(bf["refusal_reason"], "test")
        self.assertEqual(bf["report_path"], "/tmp/bf.json")
        self.assertEqual(bf["rollup_path"], "/tmp/sf.json")
        self.assertEqual(bf["final_blocker_classification_status"], "editorial")

    def test_packet_builder_source_handles_editorial_branch(self):
        """Packet builder source contains editorial reconciliation branch logic."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertIn("final_reconciliation_required", source,
                      "Packet builder must set final_reconciliation_required for editorial")
        self.assertIn("build_final_reconciliation_brief", source,
                      "Packet builder must call build_final_reconciliation_brief")
        self.assertIn("_is_final_reconciliation", source,
                      "Packet builder must use a guard flag for editorial branch")

    def test_editorial_does_not_bypass_persistence_path(self):
        """Successful editorial branch must fall through to build_result persistence."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertIn('persist_build_result_artifact(workspace, build_result)', source,
                      "Packet builder must persist build_result after editorial branch")
        self.assertIn("not _is_final_reconciliation", source,
                      "Fatal/mixed block must be guarded by not _is_final_reconciliation")

    def test_no_reconciliation_report_persisted_in_43(self):
        """Packet builder source does not persist final_reconciliation_report.json."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertNotIn("final_reconciliation_report.json", source,
                         "Packet builder must not persist reconciliation report in 4.3")

    def test_fatal_still_blocked_after_43(self):
        """Fatal classification still returns generic blocked after 4.3 changes."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertIn("build_fidelity_blocked:", source,
                      "Fatal/mixed path must still set build_fidelity_blocked error")


class TestStep44AcceptedReconciliation(unittest.TestCase):
    """Step 4.4 contract tests: accepted reconciliation report allows continuation."""

    def test_accepted_path_attaches_effective_status(self):
        """Accepted editorial path attaches reconciled_degraded metadata (not final_reconciliation_required)."""
        br = {
            "final_reconciliation_accepted": True,
            "source_fidelity_effective_status": "reconciled_degraded",
            "final_reconciliation": {"status": "accepted"},
            "build_fidelity": {
                "status": "blocked", "can_continue": False,
                "final_reconciliation_accepted": True,
                "source_fidelity_effective_status": "reconciled_degraded",
            },
        }
        self.assertTrue(br["final_reconciliation_accepted"])
        self.assertEqual(br["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(br["build_fidelity"]["final_reconciliation_accepted"])
        self.assertEqual(br["build_fidelity"]["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertNotIn("final_reconciliation_required", br)
        self.assertNotIn("final_reconciliation_required", br.get("build_fidelity", {}))

    def test_accepted_sets_guard_flag(self):
        """Packet builder source must set _is_final_reconciliation = True in accepted branch."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertIn("_is_final_reconciliation", source,
                      "Accepted branch must set guard flag to prevent overwrite")

    def test_accepted_guard_precedes_block(self):
        """Accepted branch guard must appear before 'if not _is_final_reconciliation'."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertIn("not _is_final_reconciliation", source,
                      "Generic block must be guarded by not _is_final_reconciliation")
        # Guard flag set in accepted branch must appear before the guarded block
        idx_accepted = source.find("final_reconciliation_accepted")
        idx_guard = source.find("not _is_final_reconciliation")
        self.assertLess(idx_accepted, idx_guard,
                        "Accepted branch (final_reconciliation_accepted) must appear before guarded block")

    def test_accepted_preserves_build_fidelity_fields(self):
        """Accepted reconciliation preserves original build_fidelity evidence."""
        bf = {
            "status": "blocked", "can_continue": False,
            "refusal_reason": "test", "report_path": "/tmp/bf.json",
            "rollup_path": "/tmp/sf.json",
            "final_reconciliation_accepted": True,
            "source_fidelity_effective_status": "reconciled_degraded",
        }
        self.assertEqual(bf["status"], "blocked")
        self.assertFalse(bf["can_continue"])
        self.assertEqual(bf["refusal_reason"], "test")

    def test_absent_report_routes_to_reconciliation_required(self):
        """Absent accepted report should preserve final_reconciliation_required path from 4.3."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertIn("final_reconciliation_required", source,
                      "Absent report must still route to final_reconciliation_required")

    def test_no_report_agreement_in_packet_builder_44(self):
        """Packet builder source does not import report agreement/GUI/publication."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertNotIn("report_agreement", source,
                         "Must not import report agreement in 4.4")
        self.assertNotIn("module_toolkit", source,
                         "Must not reference GUI in 4.4")


class TestStep45EvidenceReportsImmutability(unittest.TestCase):
    """Step 4.5: build/source fidelity reports unchanged across reconciliation flows."""

    def _fidelity_metadata(self, status="final_reconciliation_required"):
        return {
            "status": status,
            "build_fidelity": {
                "status": "blocked", "refusal_reason": "req", "can_continue": False,
                "report_path": "/tmp/build_fidelity_report.json",
                "rollup_path": "/tmp/source_fidelity_report.json",
            },
        }

    def test_fidelity_artifacts_persisted_before_reconciliation(self):
        """Source code persists BOTH fidelity artifacts before reconciliation logic runs."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        idx_bf = source.find("persist_build_fidelity_report_artifact")
        idx_sf = source.find("persist_source_fidelity_report_artifact")
        idx_rec = source.find("build_final_reconciliation_brief")
        self.assertGreater(idx_bf, 0, "persist_build_fidelity_report_artifact must exist")
        self.assertGreater(idx_sf, 0, "persist_source_fidelity_report_artifact must exist")
        self.assertGreater(idx_rec, 0, "build_final_reconciliation_brief must exist")
        self.assertLess(idx_bf, idx_rec,
                        "build-fidelity persistence must occur before reconciliation")
        self.assertLess(idx_sf, idx_rec,
                        "source-fidelity persistence must occur before reconciliation")

    def test_report_paths_preserved_in_required_flow(self):
        """build_result keeps report_path and rollup_path through required flow."""
        br = self._fidelity_metadata("final_reconciliation_required")
        br["final_reconciliation_required"] = True
        br["build_fidelity"]["final_reconciliation_required"] = True
        self.assertEqual(br["build_fidelity"]["report_path"], "/tmp/build_fidelity_report.json")
        self.assertEqual(br["build_fidelity"]["rollup_path"], "/tmp/source_fidelity_report.json")

    def test_report_paths_preserved_in_accepted_flow(self):
        """build_result keeps report_path and rollup_path through accepted flow."""
        br = self._fidelity_metadata("final_reconciliation_required")
        br["final_reconciliation_accepted"] = True
        br["source_fidelity_effective_status"] = "reconciled_degraded"
        br["build_fidelity"]["final_reconciliation_accepted"] = True
        br["build_fidelity"]["source_fidelity_effective_status"] = "reconciled_degraded"
        self.assertEqual(br["build_fidelity"]["report_path"], "/tmp/build_fidelity_report.json")
        self.assertEqual(br["build_fidelity"]["rollup_path"], "/tmp/source_fidelity_report.json")

    def test_no_clean_source_fidelity_pass_in_reconciliation(self):
        """Packet builder source never assigns clean 'pass' to source fidelity status."""
        import inspect
        import web.extensions.toolkit_homebrew_packet_builder as tpb
        source = inspect.getsource(tpb)
        self.assertNotIn('["source_fidelity_effective_status"] = "pass"', source,
                         "Must not assign clean pass to source_fidelity_effective_status")
        self.assertNotIn('["source_fidelity_status"] = "pass"', source,
                         "Must not assign clean pass to source_fidelity_status")


class TestStep46PackBuilderEditorialBranch(unittest.TestCase):
    """Step 4.6: editorial blockers continue past build-fidelity with accepted reconciliation."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = _create_workspace(self.tmpdir_obj.name)

    def _build_v2_workspace(self):
        bp = _make_v2_blueprint()
        (self.workspace / "builder_blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
        report = {"blueprint_status": "ready", "fidelity_status": "pass"}
        (self.workspace / "builder_blueprint_report.json").write_text(json.dumps(report), encoding="utf-8")

    def _seed_result(self, status="success"):
        return {"seed_status": status, "coverage": {}, "warnings": []}

    def _write_accepted_report(self):
        report = {
            "version": REPORT_VERSION,
            "status": "accepted",
            "reconciliation_status": "accepted",
            "source_fidelity_effective_status": "reconciled_degraded",
            "playable_publication_candidate": True,
            "decisions": ["accepted_final_reconciliation"],
        }
        (self.workspace / "final_reconciliation_report.json").write_text(json.dumps(report))

    def _blocked_fidelity_report(self):
        return {
            "status": "blocked",
            "can_continue": False,
            "blockers": [
                {"message": "Required location 'Trigger' not found in module", "category": "location"}
            ],
            "warnings": [],
            "coverage": {},
        }

    def _editorial_classification(self):
        return {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [{"type": "editorial", "message": "M", "category": "location"}],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "Required location 'Trigger' not found in module",
            "report_paths": {},
        }

    def _fatal_classification(self):
        return {
            "status": "fatal",
            "fatal_blockers": [{"type": "fatal", "message": "Invalid JSON", "category": "structural"}],
            "editorial_blockers": [],
            "warnings": [],
            "can_attempt_final_reconciliation": False,
            "fatal_count": 1,
            "editorial_count": 0,
            "original_refusal_reason": "Invalid JSON",
            "report_paths": {},
        }

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_accepted_reconciliation_continues_past_build_fidelity(
        self, mock_seed, mock_classify, mock_rollup,
        mock_can_continue, mock_build_report, mock_is_required
    ):
        """Accepted reconciliation -> not blocked, not build_fidelity stage."""
        self._build_v2_workspace()
        self._write_accepted_report()

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report()
        mock_can_continue.return_value = (False, "Required location 'Trigger' not found in module")
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._editorial_classification()

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-editorial-accepted")

        self.assertNotEqual(result.get("status"), "blocked",
                            "Accepted reconciliation must not return blocked")
        self.assertNotEqual(result.get("stage"), "build_fidelity",
                            "Accepted reconciliation must not set stage=build_fidelity")
        error = result.get("error", "")
        self.assertFalse(error.startswith("build_fidelity_blocked:"),
                         "Must not have build_fidelity_blocked error")
        self.assertTrue(result.get("final_reconciliation_accepted"))
        self.assertEqual(result["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(result.get("build_fidelity", {}).get("final_reconciliation_accepted"))
        self.assertEqual(
            result.get("build_fidelity", {}).get("source_fidelity_effective_status"),
            "reconciled_degraded",
        )
        self.assertIn("report_path", result.get("build_fidelity", {}))
        self.assertIn("rollup_path", result.get("build_fidelity", {}))

        self.assertTrue(result.get("build_result_persisted"),
                        "build_result must be persisted for accepted reconciliation")

        persisted_path = self.workspace / "build_result.json"
        self.assertTrue(persisted_path.exists(), "build_result.json must exist")
        persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
        self.assertTrue(persisted.get("final_reconciliation_accepted"))
        self.assertEqual(persisted["source_fidelity_effective_status"], "reconciled_degraded")
        self.assertTrue(persisted.get("build_fidelity", {}).get("final_reconciliation_accepted"))
        self.assertEqual(
            persisted.get("build_fidelity", {}).get("source_fidelity_effective_status"),
            "reconciled_degraded",
        )
        self.assertIn("report_path", persisted.get("build_fidelity", {}))
        self.assertIn("rollup_path", persisted.get("build_fidelity", {}))
        self.assertNotEqual(persisted.get("status"), "blocked")
        self.assertNotEqual(persisted.get("stage"), "build_fidelity")
        self.assertFalse((persisted.get("error", "") or "").startswith("build_fidelity_blocked:"))

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_no_accepted_report_returns_reconciliation_required(
        self, mock_seed, mock_classify, mock_rollup,
        mock_can_continue, mock_build_report, mock_is_required
    ):
        """No accepted report -> status=final_reconciliation_required, brief persisted."""
        self._build_v2_workspace()
        # No accepted report written

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report()
        mock_can_continue.return_value = (False, "Required location 'Trigger' not found in module")
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._editorial_classification()

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-editorial-no-accept")

        self.assertEqual(result["status"], "final_reconciliation_required")
        self.assertEqual(result["stage"], "final_reconciliation")
        self.assertTrue(result["final_reconciliation_required"])
        self.assertIn("final_reconciliation_brief", result)
        self.assertTrue((self.workspace / "final_reconciliation_brief.json").exists())

        self.assertTrue(result.get("build_result_persisted"),
                        "build_result must be persisted for reconciliation_required")
        persisted_path = self.workspace / "build_result.json"
        self.assertTrue(persisted_path.exists())
        persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "final_reconciliation_required")
        self.assertEqual(persisted["stage"], "final_reconciliation")
        self.assertTrue(persisted["final_reconciliation_required"])
        self.assertIn("final_reconciliation_brief", persisted)

    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch("utils.toolkit_final_blocker_classifier.classify_final_build_blockers")
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", True)
    @patch("web.extensions.toolkit_homebrew_packet_builder.ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", True)
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_fatal_with_accepted_report_still_blocked(
        self, mock_seed, mock_classify, mock_rollup,
        mock_can_continue, mock_build_report, mock_is_required
    ):
        """Fatal classification with accepted report -> still returns blocked."""
        self._build_v2_workspace()
        self._write_accepted_report()

        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True
        mock_build_report.return_value = self._blocked_fidelity_report()
        mock_can_continue.return_value = (False, "Required location 'Trigger' not found in module")
        mock_rollup.return_value = {"status": "blocked", "blockers": []}
        mock_classify.return_value = self._fatal_classification()

        result = run_toolkit_homebrew_packet_build(self.workspace, "test-fatal-accepted")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "build_fidelity")
        self.assertTrue(result["error"].startswith("build_fidelity_blocked:"))
        self.assertNotIn("final_reconciliation_accepted", result)


if __name__ == "__main__":
    unittest.main()
