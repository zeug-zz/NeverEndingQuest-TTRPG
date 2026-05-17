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


def _write_accurate_ingest_evidence(ws: Path) -> None:
    """Write source_graph.json as accurate-ingest evidence for blueprint-required tests."""
    from utils.file_operations import safe_write_json
    files = get_workspace_files(ws)
    safe_write_json(str(files["source_graph"]), {
        "source_graph_version": "test.v1",
        "atoms": [],
    })


def _make_mock_executor(ws: Path, captured: Dict[str, Any]) -> Any:
    """Create a mock executor that captures builder_input and writes a success build_result."""
    def mock_executor(builder_input, **kwargs):
        captured["input"] = builder_input
        from utils.file_operations import safe_write_json
        files = get_workspace_files(ws)
        safe_write_json(str(files["build_result"]), {
            "status": "success",
            "build_mode": "packet_workspace_v1",
        })
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

            result = run_toolkit_homebrew_packet_build(
                ws, "test_job", builder_executor=mock_executor,
            )
            self.assertEqual(result["status"], "success")
            self.assertIn("handoff_mode", captured.get("input", {}))
            self.assertEqual(captured["input"]["handoff_mode"], "source_blueprint")

    def test_builder_input_includes_source_lock_in_blueprint_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            _write_packet(ws)
            _write_review_snapshot(ws)
            _write_blueprint(ws, status="ready")
            _write_blueprint_narrative(ws)

            captured = {}
            mock_executor = _make_mock_executor(ws, captured)

            run_toolkit_homebrew_packet_build(ws, "test_job", builder_executor=mock_executor)
            bp_meta = captured["input"].get("blueprint", {})
            source_lock = bp_meta.get("source_lock", {})
            self.assertTrue(source_lock.get("canonical_names_locked"))
            self.assertTrue(source_lock.get("invented_major_entities_forbidden"))

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

            result = run_toolkit_homebrew_packet_build(
                ws, "test_job", builder_executor=mock_executor,
            )
            self.assertEqual(result["status"], "success")

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

            run_toolkit_homebrew_packet_build(ws, "test_job", builder_executor=mock_executor)
            builder_input = captured.get("input", {})
            bp_meta = builder_input.get("blueprint", {})
            self.assertFalse(bp_meta, "Legacy workspace must not contain blueprint metadata")


if __name__ == "__main__":
    unittest.main()
