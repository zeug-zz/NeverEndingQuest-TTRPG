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
    _describe_blueprint_not_ready,
    run_toolkit_homebrew_packet_build,
    ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF,
    ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD,
)
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


if __name__ == "__main__":
    unittest.main()
