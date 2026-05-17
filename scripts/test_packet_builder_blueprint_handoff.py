# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
Tests for packet builder blueprint handoff (Phase 4, Section 7).

Verifies that:
- builder narrative reader prefers blueprint-derived narrative when available
- builder input includes blueprint metadata in source-blueprint mode
- build refuses when blueprint mode is required but not ready
- legacy fallback works for workspaces without blueprint artifacts
- fail-closed tests do not invoke real builder execution (test isolation)
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from utils.toolkit_homebrew_upload_contract import (
    get_workspace_files,
    persist_builder_blueprint_artifact,
    persist_builder_blueprint_report_artifact,
    persist_builder_narrative_artifact,
    persist_normalized_packet_artifact,
    persist_review_snapshot_artifact,
)
from web.extensions.toolkit_homebrew_packet_builder import (
    _read_builder_narrative,
    _classify_blueprint_handoff,
    run_toolkit_homebrew_packet_build,
)


def _setup_workspace(tmp: str) -> Path:
    ws = Path(tmp) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    # Create standard placeholder files
    get_workspace_files(ws)
    return ws


def _write_packet(ws: Path) -> None:
    packet = {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_hash": "abc123",
        "title": "Test Module",
        "locations": [],
        "npc_seeds": [],
    }
    persist_normalized_packet_artifact(ws, packet)


def _write_review_snapshot(ws: Path) -> None:
    snapshot = {
        "decision": "approve",
        "recorded_at": "2026-01-01T00:00:00Z",
        "job_id": "test_job",
        "packet_identity": {
            "source_hash": "abc123",
        },
    }
    persist_review_snapshot_artifact(ws, snapshot)


def _write_blueprint(ws: Path, status: str = "ready") -> None:
    bp = {
        "blueprint_version": "source_faithful_builder_blueprint.v1",
        "source_hash": "abc123",
        "blueprint_status": status,
        "module": {"title": "Test Module", "summary": "Test summary", "tone_profile": {}},
        "source_lock": {
            "canonical_names_locked": True,
            "invented_major_entities_forbidden": True,
        },
        "location_roster": [],
        "npc_roster": [],
        "plot_graph": [],
        "puzzle_graph": [],
    }
    persist_builder_blueprint_artifact(ws, bp)
    bp_report = {
        "blueprint_status": status,
        "fidelity_status": "clean",
    }
    persist_builder_blueprint_report_artifact(ws, bp_report)


def _write_blueprint_narrative(ws: Path) -> None:
    files = get_workspace_files(ws)
    files["builder_narrative"].write_text(
        "SOURCE-FAITHFUL BUILD LOCK\n- Canonical source names are LOCKED",
        encoding="utf-8",
    )


def _cleanup_module_dir(captured: Dict[str, Any]) -> None:
    """Remove module dir created by mock executors inside the repo."""
    output_dir = str(captured.get("input", {}).get("derived_builder_parameters", {}).get("output_directory", ""))
    if output_dir:
        md = Path(output_dir).resolve()
        if md.exists():
            import shutil
            shutil.rmtree(str(md))


def _write_source_graph_with_atoms(ws: Path) -> None:
    """Write source_graph.json with required atoms for build fidelity tests."""
    from utils.file_operations import safe_write_json
    files = get_workspace_files(ws)
    safe_write_json(str(files["source_graph"]), {
        "source_graph_version": "test.v1",
        "atoms": [
            {
                "type": "npc",
                "name": "Required NPC One",
                "source_atom_id": "npc_001",
                "criticality": "required",
            },
            {
                "type": "location",
                "name": "required_location",
                "source_atom_id": "loc_001",
                "criticality": "required",
            },
            {
                "type": "plot_beat",
                "name": "Required Plot Beat",
                "source_atom_id": "beat_001",
                "criticality": "required",
            },
        ],
    })


def _make_executor_with_minimal_module(ws: Path, captured: Dict[str, Any]) -> Any:
    """Create a mock executor that also creates a minimal module dir at the expected path.

    The module dir content is deliberately incomplete (missing required NPCs/locations
    declared in _write_source_graph_with_atoms), so the build fidelity gate will block.
    """
    def _executor(builder_input, **kwargs):
        captured["input"] = builder_input
        from utils.file_operations import safe_write_json
        files = get_workspace_files(ws)
        safe_write_json(str(files["build_result"]), {
            "status": "success",
            "build_mode": "packet_workspace_v1",
        })
        output_dir_str = str(builder_input.get("derived_builder_parameters", {}).get("output_directory", ""))
        if output_dir_str:
            module_dir = Path(output_dir_str).resolve()
            module_dir.mkdir(parents=True, exist_ok=True)
            areas_dir = module_dir / "areas"
            areas_dir.mkdir(exist_ok=True)
            safe_write_json(str(areas_dir / "TA001.json"), {
                "areaId": "TA001",
                "areaName": "Test Area",
                "locations": [
                    {"locationId": "TL01", "name": "Unrelated Room"},
                ],
            })
    return _executor


def _write_accurate_ingest_evidence(ws: Path) -> None:
    """Write source_graph.json as accurate-ingest evidence for blueprint-required tests."""
    from utils.file_operations import safe_write_json
    files = get_workspace_files(ws)
    safe_write_json(str(files["source_graph"]), {
        "source_graph_version": "test.v1",
        "atoms": [],
    })


def _make_mock_executor(ws: Path, captured: Dict[str, Any]) -> Any:
    """Create a mock executor that captures builder_input and writes a success build_result.
    
    Also creates a minimal module dir so the build fidelity gate (if active) does not
    block on a missing directory when blueprint rosters are empty.
    """
    def mock_executor(builder_input, **kwargs):
        captured["input"] = builder_input
        from utils.file_operations import safe_write_json
        files = get_workspace_files(ws)
        safe_write_json(str(files["build_result"]), {
            "status": "success",
            "build_mode": "packet_workspace_v1",
        })
        output_dir_str = str(builder_input.get("derived_builder_parameters", {}).get("output_directory", ""))
        if output_dir_str:
            module_dir = Path(output_dir_str).resolve()
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "areas").mkdir(exist_ok=True)
    return mock_executor


class TestClassifyBlueprintHandoff(unittest.TestCase):
    """Unit tests for _classify_blueprint_handoff helper."""

    def test_no_blueprint_enabled_returns_legacy(self):
        ws = _setup_workspace(tempfile.mkdtemp())
        files = get_workspace_files(ws)
        result = _classify_blueprint_handoff(files, None, None)
        self.assertEqual(result, "legacy_allowed")

    def test_ready_blueprint_returns_source_blueprint_ready(self):
        ws = _setup_workspace(tempfile.mkdtemp())
        files = get_workspace_files(ws)
        _write_blueprint(ws, status="ready")
        bp = {"blueprint_status": "ready"}
        bp_report = {"blueprint_status": "ready", "fidelity_status": "clean"}
        result = _classify_blueprint_handoff(files, bp, bp_report)
        self.assertEqual(result, "source_blueprint_ready")

    def test_blocked_blueprint_returns_required_not_ready(self):
        ws = _setup_workspace(tempfile.mkdtemp())
        files = get_workspace_files(ws)
        bp = {"blueprint_status": "blocked_by_fidelity"}
        bp_report = {"blueprint_status": "blocked_by_fidelity", "fidelity_status": "blocked"}
        result = _classify_blueprint_handoff(files, bp, bp_report)
        self.assertEqual(result, "blueprint_required_not_ready")

    def test_ready_report_without_blueprint_returns_required_not_ready(self):
        ws = _setup_workspace(tempfile.mkdtemp())
        files = get_workspace_files(ws)
        bp_report = {"blueprint_status": "ready", "fidelity_status": "clean"}
        result = _classify_blueprint_handoff(files, None, bp_report)
        self.assertEqual(result, "blueprint_required_not_ready")

    def test_ready_blueprint_without_report_returns_required_not_ready(self):
        ws = _setup_workspace(tempfile.mkdtemp())
        files = get_workspace_files(ws)
        bp = {"blueprint_status": "ready"}
        result = _classify_blueprint_handoff(files, bp, None)
        self.assertEqual(result, "blueprint_required_not_ready")

    def test_accurate_ingest_evidence_without_blueprint_returns_required_not_ready(self):
        ws = _setup_workspace(tempfile.mkdtemp())
        files = get_workspace_files(ws)
        _write_accurate_ingest_evidence(ws)
        # Re-read files to reflect new file on disk
        files = get_workspace_files(ws)
        result = _classify_blueprint_handoff(files, None, None)
        self.assertEqual(result, "blueprint_required_not_ready")

    def test_no_accurate_ingest_evidence_returns_legacy(self):
        ws = _setup_workspace(tempfile.mkdtemp())
        files = get_workspace_files(ws)
        result = _classify_blueprint_handoff(files, None, None)
        self.assertEqual(result, "legacy_allowed")


class TestReadBuilderNarrative(unittest.TestCase):

    def test_prefers_blueprint_narrative_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_blueprint_narrative(ws)
            files = get_workspace_files(ws)
            bp = {"blueprint_status": "ready"}

            result = _read_builder_narrative(files, {}, blueprint=bp)
            self.assertEqual(result["source"], "blueprint_narrative")
            self.assertIn("SOURCE-FAITHFUL BUILD LOCK", result["narrative"])

    def test_falls_back_to_workspace_narrative_without_blueprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            files = get_workspace_files(ws)
            files["builder_narrative"].write_text("Legacy narrative", encoding="utf-8")

            result = _read_builder_narrative(files, {})
            self.assertEqual(result["source"], "workspace_builder_narrative")
            self.assertEqual(result["narrative"], "Legacy narrative")

    def test_falls_back_to_packet_fallback_when_no_narrative(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            files = get_workspace_files(ws)
            packet = {"title": "Test Module", "description": "A test module"}

            result = _read_builder_narrative(files, packet)
            self.assertEqual(result["source"], "packet_fallback")
            self.assertIn("Test Module", result["narrative"])


class TestBuildExecutionBlueprintHandoff(unittest.TestCase):
    """Full build-flow tests with mocked executors for isolation.

    All success-path tests use injected mock executors.
    Fail-closed tests use raising executors to prove no real builder code is called.
    """

    def test_build_refuses_blocked_blueprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            _write_blueprint(ws, status="blocked_by_fidelity")

            def _raising(*args, **kwargs):
                raise RuntimeError("TEST GUARD: executor should not be called")

            result = run_toolkit_homebrew_packet_build(
                ws, "test_job", builder_executor=_raising,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("blueprint_not_ready", result.get("error", ""))

    def test_build_refuses_missing_blueprint_with_accurate_ingest_evidence(self):
        """Accurate-ingest workspace with source_graph but no blueprint fails closed."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            _write_accurate_ingest_evidence(ws)

            executor_called = False

            def _raising(*args, **kwargs):
                nonlocal executor_called
                executor_called = True
                raise RuntimeError("TEST GUARD: executor should not be called")

            result = run_toolkit_homebrew_packet_build(
                ws, "test_job", builder_executor=_raising,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("blueprint_not_ready", result.get("error", ""))
            self.assertFalse(executor_called, "Executor must not be invoked for failing blueprint handoff")

    def test_build_refuses_ready_report_without_blueprint_before_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            persist_builder_blueprint_report_artifact(ws, {
                "blueprint_status": "ready",
                "fidelity_status": "clean",
            })

            executor_called = False

            def _raising(*args, **kwargs):
                nonlocal executor_called
                executor_called = True
                raise RuntimeError("TEST GUARD: executor should not be called")

            result = run_toolkit_homebrew_packet_build(
                ws, "test_job", builder_executor=_raising,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("blueprint_not_ready:missing_blueprint", result.get("error", ""))
            self.assertFalse(executor_called, "Executor must not be invoked when blueprint artifact is missing")

    def test_build_refuses_ready_blueprint_without_report_before_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            persist_builder_blueprint_artifact(ws, {
                "blueprint_version": "source_faithful_builder_blueprint.v1",
                "blueprint_status": "ready",
                "source_hash": "abc123",
            })

            executor_called = False

            def _raising(*args, **kwargs):
                nonlocal executor_called
                executor_called = True
                raise RuntimeError("TEST GUARD: executor should not be called")

            result = run_toolkit_homebrew_packet_build(
                ws, "test_job", builder_executor=_raising,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("blueprint_not_ready:missing_blueprint_report", result.get("error", ""))
            self.assertFalse(executor_called, "Executor must not be invoked when blueprint report is missing")

    def test_builder_input_includes_blueprint_metadata_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            _write_blueprint(ws, status="ready")
            _write_blueprint_narrative(ws)

            captured = {}
            mock_executor = _make_mock_executor(ws, captured)
            try:
                result = run_toolkit_homebrew_packet_build(
                    ws, "test_job", builder_executor=mock_executor,
                )
                self.assertEqual(result["status"], "success")
                self.assertIn("handoff_mode", captured.get("input", {}))
                self.assertEqual(captured["input"]["handoff_mode"], "source_blueprint")
            finally:
                _cleanup_module_dir(captured)

    def test_builder_input_includes_source_lock_in_blueprint_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            _write_blueprint(ws, status="ready")
            _write_blueprint_narrative(ws)

            captured = {}
            mock_executor = _make_mock_executor(ws, captured)
            try:
                run_toolkit_homebrew_packet_build(ws, "test_job", builder_executor=mock_executor)
                bp_meta = captured["input"].get("blueprint", {})
                source_lock = bp_meta.get("source_lock", {})
                self.assertTrue(source_lock.get("canonical_names_locked"))
                self.assertTrue(source_lock.get("invented_major_entities_forbidden"))
            finally:
                _cleanup_module_dir(captured)

    def test_legacy_workspace_without_blueprint_succeeds(self):
        """Legacy workspace without blueprint or accurate-ingest evidence succeeds via legacy path."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            files = get_workspace_files(ws)
            files["builder_narrative"].write_text("Legacy narrative text", encoding="utf-8")

            captured = {}
            mock_executor = _make_mock_executor(ws, captured)
            try:
                result = run_toolkit_homebrew_packet_build(
                    ws, "test_job", builder_executor=mock_executor,
                )
                self.assertEqual(result["status"], "success")
            finally:
                _cleanup_module_dir(captured)

    def test_blueprint_ready_does_not_set_false_handoff_in_legacy_mode(self):
        """Legacy workspace should not get source-blueprint handoff metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            files = get_workspace_files(ws)
            files["builder_narrative"].write_text("Legacy narrative text", encoding="utf-8")

            captured = {}
            mock_executor = _make_mock_executor(ws, captured)
            try:
                run_toolkit_homebrew_packet_build(ws, "test_job", builder_executor=mock_executor)
                builder_input = captured.get("input", {})
                bp_meta = builder_input.get("blueprint", {})
                self.assertFalse(bp_meta, "Legacy workspace must not contain blueprint metadata")
            finally:
                _cleanup_module_dir(captured)


    def test_build_fidelity_blocked_persists_result(self):
        """Blocked build fidelity produces persisted build_result.json."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            # Need a ready blueprint so blueprint handoff does not block before fidelity.
            _write_blueprint(ws, status="ready")
            _write_blueprint_narrative(ws)
            _write_source_graph_with_atoms(ws)

            captured: Dict[str, Any] = {}
            executor = _make_executor_with_minimal_module(ws, captured)
            try:
                result = run_toolkit_homebrew_packet_build(
                    ws, "test_job", builder_executor=executor,
                )

                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["stage"], "build_fidelity")
                self.assertIn("build_fidelity", result)
                self.assertFalse(result["build_fidelity"]["can_continue"])
                self.assertIn("refusal_reason", result["build_fidelity"])

                # Persisted build_result.json
                files = get_workspace_files(ws)
                persisted = json.loads(files["build_result"].read_text(encoding="utf-8"))
                self.assertEqual(persisted["status"], "blocked")
                self.assertEqual(persisted["stage"], "build_fidelity")
                self.assertIn("build_fidelity", persisted)
                self.assertFalse(persisted["build_fidelity"]["can_continue"])
            finally:
                _cleanup_module_dir(captured)


    def test_build_success_includes_enrichment_plan(self):
        """Successful build includes narrative enrichment plan metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            captured: Dict[str, Any] = {}
            mock_executor = _make_mock_executor(ws, captured)
            try:
                result = run_toolkit_homebrew_packet_build(
                    ws, "test_job", builder_executor=mock_executor,
                )
                self.assertEqual(result["status"], "success")
                nep = result.get("narrative_enrichment_plan") or {}
                self.assertEqual(nep.get("profile"), "none")
                self.assertEqual(nep.get("status"), "skipped")
                self.assertIn("blocker_count", nep)
                self.assertIn("warning_count", nep)
                # Verify plan artifact was persisted
                files = get_workspace_files(ws)
                nep_path = files.get("narrative_enrichment_plan")
                self.assertTrue(nep_path.exists(), "narrative_enrichment_plan.json should exist")
                import json
                persisted = json.loads(nep_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted.get("profile"), "none")
                self.assertEqual(persisted.get("can_apply"), False)
                self.assertEqual(persisted.get("auto_apply"), False)
            finally:
                _cleanup_module_dir(captured)


if __name__ == "__main__":
    unittest.main()
