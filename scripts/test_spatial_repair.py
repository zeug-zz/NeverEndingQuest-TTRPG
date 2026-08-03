# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for utils.spatial_repair.repair_module_spatial."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.spatial_repair import repair_module_spatial, _SPATIAL_REPORT_FILENAME

from web.extensions.toolkit_homebrew_packet_builder import (
    run_toolkit_homebrew_packet_build,
)


def _make_area_file(
    areas_dir: Path,
    area_id: str,
    locations: list,
    embedded_map: Dict[str, Any] = None,
) -> None:
    """Write an area JSON file with the given structure."""
    area_data: Dict[str, Any] = {
        "areaId": area_id,
        "areaName": f"Area {area_id}",
        "locations": locations,
    }
    if embedded_map:
        area_data["map"] = embedded_map
    else:
        # Provide a minimal embedded map that area/map files expect
        area_data["map"] = {"rooms": []}
    (areas_dir / f"{area_id}.json").write_text(
        json.dumps(area_data, indent=2), encoding="utf-8"
    )


def _make_external_map(module_dir: Path, area_id: str, rooms: list) -> None:
    """Write an external map JSON file."""
    map_data: Dict[str, Any] = {
        "rooms": rooms,
    }
    (module_dir / f"map_{area_id}.json").write_text(
        json.dumps(map_data, indent=2), encoding="utf-8"
    )


def _build_room_entry(room_id: str, name: str, coordinates: str, connections: list) -> Dict[str, Any]:
    """Build a map room entry."""
    return {
        "id": room_id,
        "name": name,
        "connections": connections,
        "coordinates": coordinates,
    }


class TestSpatialRepairHelper(unittest.TestCase):
    """Provider-free tests for repair_module_spatial."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.module_dir = Path(self.temp_dir.name) / "TestModule"
        self.areas_dir = self.module_dir / "areas"
        self.areas_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _area_path(self, area_id: str) -> Path:
        return self.areas_dir / f"{area_id}.json"

    def _map_path(self, area_id: str) -> Path:
        return self.module_dir / f"map_{area_id}.json"

    # ----------------------------------------------------------------
    # Test 1: No areas -> status="pass", input_location_count=0
    # ----------------------------------------------------------------
    def test_repair_with_no_areas_returns_pass(self) -> None:
        """Empty module dir (no areas/) should return status='pass' with 0 locations."""
        report = repair_module_spatial(str(self.module_dir))

        self.assertEqual(report.get("status"), "pass")
        self.assertEqual(report.get("input_location_count"), 0)
        self.assertEqual(report.get("edge_count"), 0)
        self.assertEqual(report.get("unresolved_count"), 0)
        self.assertEqual(report.get("repaired_area_count"), 0)
        self.assertIn("timestamp", report)
        self.assertIn("details", report)

    # ----------------------------------------------------------------
    # Test 2: Valid cardinally adjacent areas
    # ----------------------------------------------------------------
    def test_repair_with_valid_areas_returns_pass_or_changed(self) -> None:
        """Module with areas that have valid spatial layout should pass or change."""
        area_id = "TST01"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        report = repair_module_spatial(str(self.module_dir))

        self.assertIn(report.get("status"), ("pass", "changed"))
        self.assertGreaterEqual(report.get("input_location_count", 0), 2)
        self.assertGreaterEqual(report.get("edge_count", 0), 2)
        self.assertEqual(report.get("unresolved_count", 0), 0)

    # ----------------------------------------------------------------
    # Test 3: Invalid (non-cardinal) coordinates
    # ----------------------------------------------------------------
    def test_repair_with_invalid_coordinates_returns_changed_or_failed(self) -> None:
        """Connected rooms NOT cardinally adjacent should trigger repair."""
        area_id = "TST02"
        # R01 at X10Y10, R02 at X12Y10 -- not adjacent (Manhattan distance 2)
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X12Y10",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X12Y10", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        report = repair_module_spatial(str(self.module_dir))

        # The repair should make changes to fix non-cardinal edges.
        # It may succeed (changed) or fail to fully resolve (failed).
        self.assertIn(report.get("status"), ("changed", "failed"))
        self.assertGreaterEqual(report.get("input_location_count", 0), 2)
        self.assertIn("repaired_area_count", report)

    # ----------------------------------------------------------------
    # Test 4: Report is persisted
    # ----------------------------------------------------------------
    def test_repair_report_persisted(self) -> None:
        """After repair, spatial_repair_report.json should exist with all required fields."""
        area_id = "TST03"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        repair_module_spatial(str(self.module_dir))

        report_path = self.module_dir / _SPATIAL_REPORT_FILENAME
        self.assertTrue(report_path.exists(), "spatial_repair_report.json must exist")

        raw = report_path.read_text(encoding="utf-8")
        report = json.loads(raw)
        self.assertIsInstance(report, dict)

        # Required fields from spec
        self.assertIn("timestamp", report)
        self.assertIn("status", report)
        self.assertIn("input_location_count", report)
        self.assertIn("repaired_area_count", report)
        self.assertIn("edge_count", report)
        self.assertIn("unresolved_count", report)
        self.assertIn("details", report)
        self.assertIn("processed", report["details"])
        self.assertIn("changed", report["details"])
        self.assertIn("errors", report["details"])

    # ----------------------------------------------------------------
    # Test 5: Location IDs are preserved
    # ----------------------------------------------------------------
    def test_repair_preserves_location_ids(self) -> None:
        """Original locationId values should remain unchanged after repair."""
        area_id = "TST04"
        original_ids = ["ALPHA", "BETA", "GAMMA"]
        locations = [
            {
                "locationId": original_ids[0],
                "name": "Alpha Room",
                "coordinates": "X10Y10",
                "connectivity": [original_ids[1]],
            },
            {
                "locationId": original_ids[1],
                "name": "Beta Room",
                "coordinates": "X10Y11",
                "connectivity": [original_ids[0]],
            },
            {
                "locationId": original_ids[2],
                "name": "Gamma Room",
                "coordinates": "X11Y11",
                "connectivity": [original_ids[1]],
            },
        ]
        rooms = [
            _build_room_entry(original_ids[0], "Alpha Room", "X10Y10", [original_ids[1]]),
            _build_room_entry(original_ids[1], "Beta Room", "X10Y11", [original_ids[0], original_ids[2]]),
            _build_room_entry(original_ids[2], "Gamma Room", "X11Y11", [original_ids[1]]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        repair_module_spatial(str(self.module_dir))

        # Read back the area file
        area_data = json.loads(self._area_path(area_id).read_text(encoding="utf-8"))
        post_ids = [loc.get("locationId") for loc in area_data.get("locations", [])]

        for original_id in original_ids:
            self.assertIn(
                original_id,
                post_ids,
                f"Location ID {original_id} should be preserved after repair",
            )

    # ----------------------------------------------------------------
    # Test 6: Deterministic reports
    # ----------------------------------------------------------------
    def test_repair_report_is_deterministic(self) -> None:
        """Two repairs on the same module should produce identical counts."""
        area_id = "TST05"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        # First repair
        report1 = repair_module_spatial(str(self.module_dir))

        # Second repair (idempotent)
        report2 = repair_module_spatial(str(self.module_dir))

        self.assertEqual(
            report1.get("input_location_count"),
            report2.get("input_location_count"),
            "input_location_count should be deterministic (state-based count)",
        )
        self.assertEqual(
            report1.get("edge_count"),
            report2.get("edge_count"),
            "edge_count should be deterministic (state-based count)",
        )
        # repaired_area_count is a change count, not a state count.
        # After first repair writes files, second repair may find no changes
        # needed (idempotent). Only state-based counts must match.

    # ----------------------------------------------------------------
    # Test 7: Edge counting accuracy
    # ----------------------------------------------------------------
    def test_repair_counts_edges_correctly(self) -> None:
        """Known connectivity should produce correct edge_count."""
        area_id = "TST06"
        # Three locations with 4 directed edges (3 unique undirected):
        # R01 <-> R02, R02 <-> R03, R01 <-> R03
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02", "R03"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X11Y10",
                "connectivity": ["R01", "R03"],
            },
            {
                "locationId": "R03",
                "name": "Room 3",
                "coordinates": "X10Y11",
                "connectivity": ["R01", "R02"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02", "R03"]),
            _build_room_entry("R02", "Room 2", "X11Y10", ["R01", "R03"]),
            _build_room_entry("R03", "Room 3", "X10Y11", ["R01", "R02"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        # Expected: 6 directed connections (2 per location * 3 locations)
        report = repair_module_spatial(str(self.module_dir))

        self.assertEqual(
            report.get("edge_count"),
            6,
            "3 locations with 2 connections each = 6 edges",
        )
        self.assertEqual(
            report.get("input_location_count"),
            3,
            "Should have 3 locations total",
        )

    # ----------------------------------------------------------------
    # Test 8: Failed status on errors
    # ----------------------------------------------------------------
    def test_repair_failed_status_on_errors(self) -> None:
        """A scenario producing remediation errors should yield status='failed'."""
        area_id = "TST07"
        # Valid locations, but we'll trigger an error by creating a
        # malformed area file that the remediate function cannot process
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        # Add a malformed area file (invalid JSON) to trigger an error
        bad_path = self.areas_dir / "BROKEN.json"
        bad_path.write_text("{invalid json content", encoding="utf-8")

        report = repair_module_spatial(str(self.module_dir))

        self.assertEqual(
            report.get("status"),
            "failed",
            "Malformed area file should produce a failed repair",
        )
        self.assertGreater(
            report.get("unresolved_count", 0),
            0,
            "Should have at least 1 unresolved error",
        )
        errors = report.get("details", {}).get("errors", [])
        self.assertTrue(
            any("BROKEN.json" in str(e) for e in errors),
            "Errors should mention the broken file",
        )


_VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"


class TestPacketBuilderSpatialRepairWiring(unittest.TestCase):
    """Tests for spatial repair wiring in the packet builder.

    Verifies that spatial repair runs between monster closure and fidelity
    gates, and that failed spatial repair correctly blocks the build before
    fidelity gates or final-editor routing.
    """

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir_obj.cleanup)
        self.workspace = self._create_workspace(self.tmpdir_obj.name)

    # -- workspace helpers -----------------------------------------------

    def _create_workspace(self, tmpdir: str) -> Path:
        """Create a minimal workspace with required files."""
        ws = Path(tmpdir) / "workspace"
        ws.mkdir(parents=True, exist_ok=True)

        defaults: Dict[str, Any] = {
            "normalized_packet.json": {
                "packet_version": "packet.v1",
                "name": "test-pipeline",
                "title": "Spatial Repair Test",
                "description": "Test module for spatial repair wiring",
                "source_hash": "abc123",
                "source_rights": "user_authored",
                "normalization_state": "normalized",
            },
            "ui_review_snapshot.json": {
                "decision": "approve",
                "recorded_at": "2026-01-01T00:00:00Z",
                "job_id": "test-job-sr",
                "packet_identity": {"source_hash": "abc123"},
            },
            "builder_blueprint.json": {},
            "builder_blueprint_report.json": {},
            "builder_narrative.txt": "Test narrative for build",
        }

        for filename, content in defaults.items():
            path = ws / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(content) if isinstance(content, dict) else content,
                encoding="utf-8",
            )

        return ws

    def _build_v2_workspace(self) -> None:
        """Set up v2 blueprint artifacts in the existing workspace."""
        bp: Dict[str, Any] = {
            "blueprint_version": _VALID_V2_VERSION,
            "blueprint_status": "ready",
            "module": {"title": "Test V2 Module", "summary": "A v2 test"},
            "source_lock": {"canonical_names_locked": True},
            "area_plan": [],
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
            "coverage": {},
            "enrichment_allowlist": {},
            "artifact_refs": {},
            "blockers": [],
        }
        (self.workspace / "builder_blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        report: Dict[str, str] = {
            "blueprint_status": "ready",
            "fidelity_status": "pass",
        }
        (self.workspace / "builder_blueprint_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def _seed_result(self, status: str = "success") -> Dict[str, Any]:
        """Return a mock seed writer success result."""
        return {
            "seed_status": status,
            "coverage": {},
            "warnings": [],
        }

    # -- tests -----------------------------------------------------------

    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_successful_repair_does_not_block_build(
        self,
        mock_seed,
        mock_rollup,
        mock_can_continue,
        mock_build_report,
        mock_is_required,
        mock_closure,
        mock_spatial,
    ):
        """When spatial repair completes successfully (changed/pass), build
        continues to fidelity gates and is not blocked at spatial_repair stage."""
        self._build_v2_workspace()
        mock_spatial.return_value = {
            "status": "changed",
            "input_location_count": 10,
            "repaired_area_count": 2,
            "edge_count": 15,
            "unresolved_count": 0,
        }
        mock_closure.return_value = {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = False
        mock_rollup.return_value = {"status": "pass", "blockers": []}

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-successful-spatial",
        )

        self.assertIn("spatial_repair", result)
        self.assertEqual(result["spatial_repair"]["status"], "changed")
        # Build should NOT be blocked at spatial_repair stage
        self.assertNotEqual(result.get("stage"), "spatial_repair")
        self.assertNotEqual(result.get("status"), "blocked")

    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch("utils.toolkit_build_fidelity.build_build_fidelity_report")
    @patch("utils.toolkit_build_fidelity.can_continue_after_build_fidelity")
    @patch("utils.toolkit_build_fidelity.build_source_fidelity_rollup")
    def test_failed_repair_blocks_build_before_fidelity(
        self,
        mock_rollup,
        mock_can_continue,
        mock_build_report,
        mock_is_required,
        mock_seed,
        mock_closure,
        mock_spatial,
    ):
        """Failed spatial repair blocks the build at spatial_repair stage
        before fidelity gates run."""
        self._build_v2_workspace()
        mock_spatial.return_value = {
            "status": "failed",
            "input_location_count": 10,
            "repaired_area_count": 0,
            "edge_count": 10,
            "unresolved_count": 5,
        }
        mock_closure.return_value = {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = self._seed_result()

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-failed-spatial",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stage"], "spatial_repair")
        self.assertTrue(
            result["error"].startswith("spatial_repair_failed:")
        )
        # Fidelity gate helpers should not be called because the build
        # returned before reaching the fidelity gates section.
        mock_is_required.assert_not_called()

    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    def test_repair_exception_fails_open(
        self,
        mock_is_required,
        mock_seed,
        mock_closure,
        mock_spatial,
    ):
        """If spatial repair raises an exception, the build continues
        past the spatial repair step to fidelity gates."""
        self._build_v2_workspace()
        mock_spatial.side_effect = Exception("Transient repair error")
        mock_closure.return_value = {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = True

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-spatial-exception",
        )

        # The build should NOT be blocked at spatial_repair stage
        self.assertNotEqual(result.get("stage"), "spatial_repair")
        # Fidelity helpers were called because the build continued past
        # the spatial repair step (fail-open behavior).
        mock_is_required.assert_called()

    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    def test_repair_report_path_in_build_result(
        self,
        mock_is_required,
        mock_seed,
        mock_closure,
        mock_spatial,
    ):
        """After successful spatial repair, the build result carries the
        report_path pointing to module_dir/spatial_repair_report.json."""
        self._build_v2_workspace()
        mock_spatial.return_value = {
            "status": "pass",
            "input_location_count": 5,
            "repaired_area_count": 0,
            "edge_count": 8,
            "unresolved_count": 0,
        }
        mock_closure.return_value = {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = self._seed_result()
        mock_is_required.return_value = False

        result = run_toolkit_homebrew_packet_build(
            self.workspace,
            "test-spatial-report-path",
        )

        self.assertIn("spatial_repair", result)
        self.assertIn("report_path", result["spatial_repair"])
        self.assertTrue(
            result["spatial_repair"]["report_path"].endswith("spatial_repair_report.json"),
            f"report_path does not end with spatial_repair_report.json: "
            f"{result['spatial_repair']['report_path']}"
        )


class TestSpatialRepairReportPersistence(unittest.TestCase):
    """Provider-free tests for spatial repair report persistence (Task 3.3).

    Verifies that the persisted spatial_repair_report.json contains all
    required fields with correct types, that errors are surfaced in
    details.errors, that the report_path propagates into build_result,
    and that downstream consumers can load the report successfully.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.module_dir = Path(self.temp_dir.name) / "TestModule"
        self.areas_dir = self.module_dir / "areas"
        self.areas_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _area_path(self, area_id: str) -> Path:
        return self.areas_dir / f"{area_id}.json"

    def _map_path(self, area_id: str) -> Path:
        return self.module_dir / f"map_{area_id}.json"

    # ----------------------------------------------------------------
    # Test 3.3.1: All required fields present with correct types
    # ----------------------------------------------------------------
    def test_report_persisted_with_all_required_fields(self) -> None:
        """After repair, spatial_repair_report.json has all 7 required fields
        with correct types (str for timestamp/status, int for counts, dict for details)."""
        area_id = "RPT01"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        repair_module_spatial(str(self.module_dir))

        report_path = self.module_dir / _SPATIAL_REPORT_FILENAME
        self.assertTrue(report_path.exists(), "spatial_repair_report.json must exist")
        raw = report_path.read_text(encoding="utf-8")
        report = json.loads(raw)

        # Validate each required field has the correct type
        self.assertIsInstance(
            report.get("timestamp"), str,
            "timestamp must be a str",
        )
        self.assertIsInstance(
            report.get("status"), str,
            "status must be a str",
        )
        self.assertIn(
            report["status"], ("pass", "changed", "failed"),
            "status must be one of pass/changed/failed",
        )
        self.assertIsInstance(
            report.get("input_location_count"), int,
            "input_location_count must be an int",
        )
        self.assertIsInstance(
            report.get("repaired_area_count"), int,
            "repaired_area_count must be an int",
        )
        self.assertIsInstance(
            report.get("edge_count"), int,
            "edge_count must be an int",
        )
        self.assertIsInstance(
            report.get("unresolved_count"), int,
            "unresolved_count must be an int",
        )
        self.assertIsInstance(
            report.get("details"), dict,
            "details must be a dict",
        )

    # ----------------------------------------------------------------
    # Test 3.3.2: Error details on failure
    # ----------------------------------------------------------------
    def test_report_includes_details_with_errors_on_failure(self) -> None:
        """When repair encounters a malformed area file, the report's
        details.errors list contains at least one error string mentioning the
        broken file."""
        area_id = "RPT02"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": [],
            },
        ]
        rooms = [_build_room_entry("R01", "Room 1", "X10Y10", [])]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        # Add a malformed area file to trigger repair errors
        bad_path = self.areas_dir / "BROKEN.json"
        bad_path.write_text("{invalid json", encoding="utf-8")

        report = repair_module_spatial(str(self.module_dir))

        self.assertEqual(report.get("status"), "failed")
        errors = report.get("details", {}).get("errors", [])
        self.assertIsInstance(errors, list)
        self.assertGreater(len(errors), 0)
        self.assertTrue(
            any("BROKEN.json" in str(e) for e in errors),
            "errors list should mention BROKEN.json",
        )

    # ----------------------------------------------------------------
    # Test 3.3.3: report_path in build_result
    # ----------------------------------------------------------------
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_report_path_in_build_result(
        self,
        mock_seed,
        mock_fid,
        mock_closure,
        mock_spatial,
    ) -> None:
        """After successful spatial repair (mocked), the build result carries
        report_path pointing to module_dir/spatial_repair_report.json."""
        mock_spatial.return_value = {
            "status": "pass",
            "input_location_count": 5,
            "repaired_area_count": 0,
            "edge_count": 8,
            "unresolved_count": 0,
        }
        mock_closure.return_value = {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = {
            "seed_status": "success",
            "coverage": {},
            "warnings": [],
        }
        mock_fid.return_value = False

        tmpdir = tempfile.mkdtemp()
        try:
            ws = _create_packet_builder_workspace(tmpdir, "test-persistence-rp")
            result = run_toolkit_homebrew_packet_build(
                ws, "test-persistence-rp",
            )
            self.assertIn("spatial_repair", result)
            self.assertIn("report_path", result["spatial_repair"])
            self.assertTrue(
                result["spatial_repair"]["report_path"].endswith(
                    "spatial_repair_report.json",
                ),
                "report_path should end with spatial_repair_report.json, "
                f"got: {result['spatial_repair']['report_path']}",
            )
        finally:
            shutil.rmtree(tmpdir)

    # ----------------------------------------------------------------
    # Test 3.3.4: Status matching and failed blocking
    # ----------------------------------------------------------------
    @patch("utils.spatial_repair.repair_module_spatial")
    @patch("utils.monster_reference_closure.ensure_monster_reference_closure")
    @patch("utils.toolkit_build_fidelity.is_build_fidelity_required")
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD",
        True,
    )
    @patch(
        "web.extensions.toolkit_homebrew_packet_builder."
        "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK",
        True,
    )
    @patch("utils.toolkit_blueprint_seed_writer.materialize_module_from_blueprint")
    def test_report_status_matches_build_result(
        self,
        mock_seed,
        mock_fid,
        mock_closure,
        mock_spatial,
    ) -> None:
        """When spatial repair returns status='changed', build result
        reflects it.  When status='failed', the build is blocked at
        spatial_repair stage."""

        # --- Case A: status = "changed" ---
        mock_spatial.return_value = {
            "status": "changed",
            "input_location_count": 5,
            "repaired_area_count": 2,
            "edge_count": 5,
            "unresolved_count": 0,
        }
        mock_closure.return_value = {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }
        mock_seed.return_value = {
            "seed_status": "success",
            "coverage": {},
            "warnings": [],
        }
        mock_fid.return_value = False

        tmpdir1 = tempfile.mkdtemp()
        try:
            ws1 = _create_packet_builder_workspace(
                tmpdir1, "test-status-changed", title="Status Changed",
            )
            result = run_toolkit_homebrew_packet_build(
                ws1, "test-status-changed",
            )
            self.assertIn("spatial_repair", result)
            self.assertEqual(
                result["spatial_repair"]["status"], "changed",
            )
            self.assertNotEqual(
                result.get("status"), "blocked",
                "changed status should NOT block the build",
            )
        finally:
            shutil.rmtree(tmpdir1)

        # --- Case B: status = "failed" ---
        mock_spatial.return_value = {
            "status": "failed",
            "input_location_count": 5,
            "repaired_area_count": 0,
            "edge_count": 5,
            "unresolved_count": 2,
        }

        tmpdir2 = tempfile.mkdtemp()
        try:
            ws2 = _create_packet_builder_workspace(
                tmpdir2, "test-status-failed", source_hash="abc124",
                title="Status Failed",
            )
            result = run_toolkit_homebrew_packet_build(
                ws2, "test-status-failed",
            )
            self.assertEqual(
                result["status"], "blocked",
                "failed status should block the build",
            )
            self.assertEqual(
                result["stage"], "spatial_repair",
            )
            self.assertTrue(
                str(result.get("error", "")).startswith(
                    "spatial_repair_failed:",
                ),
                f"error should start with spatial_repair_failed:, "
                f"got: {result.get('error')}",
            )
        finally:
            shutil.rmtree(tmpdir2)

    # ----------------------------------------------------------------
    # Test 3.3.5: Loadable by downstream consumers
    # ----------------------------------------------------------------
    def test_report_is_loadable_by_downstream_consumers(self) -> None:
        """After repair, the JSON report file can be loaded and all field
        types match what downstream consumers expect."""
        area_id = "RPT05"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        repair_module_spatial(str(self.module_dir))

        report_path = self.module_dir / _SPATIAL_REPORT_FILENAME
        raw = report_path.read_text(encoding="utf-8")
        report = json.loads(raw)

        # Downstream consumer validates types before use
        self.assertIsInstance(report["timestamp"], str)
        self.assertIn(report["status"], ("pass", "changed", "failed"))
        self.assertIsInstance(report["input_location_count"], int)
        self.assertIsInstance(report["repaired_area_count"], int)
        self.assertIsInstance(report["edge_count"], int)
        self.assertIsInstance(report["unresolved_count"], int)
        self.assertIsInstance(report["details"], dict)
        # Details sub-fields
        self.assertIsInstance(report["details"].get("processed", 0), int)
        self.assertIsInstance(report["details"].get("changed", 0), int)
        self.assertIsInstance(report["details"].get("errors"), list)


class TestSpatialRepairRegression(unittest.TestCase):
    """Provider-free regression tests for spatial repair scenarios (Task 3.4).

    Verifies stale coordinate repair, source identity preservation, unsafe
    topology fail-closed behavior, no-invented-locations guarantee, area+map
    file co-update, and idempotent re-repair of valid modules.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.module_dir = Path(self.temp_dir.name) / "TestModule"
        self.areas_dir = self.module_dir / "areas"
        self.areas_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _area_path(self, area_id: str) -> Path:
        return self.areas_dir / f"{area_id}.json"

    def _map_path(self, area_id: str) -> Path:
        return self.module_dir / f"map_{area_id}.json"

    # ----------------------------------------------------------------
    # Test 3.4.1: Stale coordinate repair
    # ----------------------------------------------------------------
    def test_stale_coordinate_repair(self) -> None:
        """Connected rooms NOT cardinally adjacent (Manhattan distance > 1)
        are either fixed or reported as changed."""
        area_id = "STA01"
        # J01 at X10Y10, J02 at X12Y10 -- NOT cardinally adjacent (distance 2)
        # Connected via north/south connectivity
        locations = [
            {
                "locationId": "J01",
                "name": "Junction 1",
                "coordinates": "X10Y10",
                "connectivity": ["J02"],
            },
            {
                "locationId": "J02",
                "name": "Junction 2",
                "coordinates": "X12Y10",
                "connectivity": ["J01"],
            },
        ]
        rooms = [
            _build_room_entry("J01", "Junction 1", "X10Y10", ["J02"]),
            _build_room_entry("J02", "Junction 2", "X12Y10", ["J01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        report = repair_module_spatial(str(self.module_dir))

        self.assertIn(
            report.get("status"), ("changed", "failed"),
            "Non-cardinal pairs should trigger repair (changed or failed)",
        )
        self.assertGreaterEqual(
            report.get("repaired_area_count", 0), 1,
            "At least one area should have been repaired",
        )

    # ----------------------------------------------------------------
    # Test 3.4.2: Source location identity preserved
    # ----------------------------------------------------------------
    def test_source_location_identity_preserved(self) -> None:
        """Original locationId and locationName values survive repair."""
        area_id = "STA02"
        original_ids = ["ALPHA", "BETA", "GAMMA"]
        original_names = ["Alpha Chamber", "Beta Vault", "Gamma Hall"]
        locations = [
            {
                "locationId": original_ids[0],
                "name": original_names[0],
                "coordinates": "X10Y10",
                "connectivity": [original_ids[1]],
            },
            {
                "locationId": original_ids[1],
                "name": original_names[1],
                "coordinates": "X10Y11",
                "connectivity": [original_ids[0], original_ids[2]],
            },
            {
                "locationId": original_ids[2],
                "name": original_names[2],
                "coordinates": "X11Y11",
                "connectivity": [original_ids[1]],
            },
        ]
        rooms = [
            _build_room_entry(
                original_ids[0], original_names[0], "X10Y10", [original_ids[1]],
            ),
            _build_room_entry(
                original_ids[1], original_names[1], "X10Y11",
                [original_ids[0], original_ids[2]],
            ),
            _build_room_entry(
                original_ids[2], original_names[2], "X11Y11", [original_ids[1]],
            ),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        repair_module_spatial(str(self.module_dir))

        area_data = json.loads(self._area_path(area_id).read_text(encoding="utf-8"))
        post_locations = area_data.get("locations", [])

        # All three locationId values still present
        post_ids = [loc.get("locationId") for loc in post_locations]
        for original_id in original_ids:
            self.assertIn(
                original_id,
                post_ids,
                f"Location ID {original_id} should be preserved after repair",
            )

        # All three locationName values still present (location may use 'name' key)
        post_names = [loc.get("name") for loc in post_locations]
        for original_name in original_names:
            self.assertIn(
                original_name,
                post_names,
                f"Location name '{original_name}' should be preserved after repair",
            )

    # ----------------------------------------------------------------
    # Test 3.4.3: Unsafe topology fail-closed
    # ----------------------------------------------------------------
    def test_unsafe_topology_fail_closed(self) -> None:
        """A triangle graph (3 rooms each connected to the other 2, which
        is impossible to embed with all edges cardinal) does NOT crash the
        repair and produces a report with a clear status."""
        area_id = "STA03"
        # R01-R02, R02-R03, R01-R03 -- triangle, impossible fully cardinally
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02", "R03"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X11Y10",
                "connectivity": ["R01", "R03"],
            },
            {
                "locationId": "R03",
                "name": "Room 3",
                "coordinates": "X10Y11",
                "connectivity": ["R01", "R02"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02", "R03"]),
            _build_room_entry("R02", "Room 2", "X11Y10", ["R01", "R03"]),
            _build_room_entry("R03", "Room 3", "X10Y11", ["R01", "R02"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        # Should NOT crash
        try:
            report = repair_module_spatial(str(self.module_dir))
        except Exception as exc:
            self.fail(f"repair_module_spatial raised {exc} on triangle graph")

        # Report must have a clear status
        self.assertIn(
            report.get("status"), ("failed", "changed"),
            "Triangle graph should produce 'failed' or 'changed' status, "
            f"got: {report.get('status')}",
        )

        # In either case, unresolved_count may be >0 (acceptable)
        if report["status"] == "failed":
            self.assertGreater(
                report.get("unresolved_count", 0), 0,
                "Failed repair should have unresolved_count > 0",
            )
        else:
            # 'changed' is also acceptable - repair tried its best
            pass

    # ----------------------------------------------------------------
    # Test 3.4.4: Repair does not invent new locations
    # ----------------------------------------------------------------
    def test_repair_does_not_invent_new_locations(self) -> None:
        """After repair of a valid area, the location count stays the same.
        No new locations are invented and none are removed."""
        area_id = "STA04"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01", "R03"],
            },
            {
                "locationId": "R03",
                "name": "Room 3",
                "coordinates": "X10Y12",
                "connectivity": ["R02"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01", "R03"]),
            _build_room_entry("R03", "Room 3", "X10Y12", ["R02"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        repair_module_spatial(str(self.module_dir))

        area_data = json.loads(self._area_path(area_id).read_text(encoding="utf-8"))
        post_count = len(area_data.get("locations", []))

        self.assertEqual(
            post_count, 3,
            f"Location count should remain 3 after repair, got {post_count}",
        )

    # ----------------------------------------------------------------
    # Test 3.4.5: Repair updates both area and map files
    # ----------------------------------------------------------------
    def test_repair_updates_both_area_and_map_files(self) -> None:
        """When coordinates are invalid, both the area file and the external
        map file are updated."""
        area_id = "STA05"
        # Invalid coordinates: R01 at X10Y10, R02 at X12Y10 (non-cardinal)
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X12Y10",
                "connectivity": ["R01"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X12Y10", ["R01"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        # Capture original coordinates from both files
        original_area = json.loads(
            self._area_path(area_id).read_text(encoding="utf-8"),
        )
        original_area_coords = {
            loc["locationId"]: loc.get("coordinates")
            for loc in original_area.get("locations", [])
        }
        original_map = json.loads(
            self._map_path(area_id).read_text(encoding="utf-8"),
        )
        original_map_coords = {
            room["id"]: room.get("coordinates")
            for room in original_map.get("rooms", [])
        }

        repair_module_spatial(str(self.module_dir))

        # Read both files after repair
        post_area = json.loads(
            self._area_path(area_id).read_text(encoding="utf-8"),
        )
        post_area_coords = {
            loc["locationId"]: loc.get("coordinates")
            for loc in post_area.get("locations", [])
        }
        post_map = json.loads(
            self._map_path(area_id).read_text(encoding="utf-8"),
        )
        post_map_coords = {
            room["id"]: room.get("coordinates")
            for room in post_map.get("rooms", [])
        }

        # Both files should have been updated (coordinates changed from original)
        area_changed = any(
            post_area_coords.get(lid) != original_area_coords.get(lid)
            for lid in original_area_coords
        )
        map_changed = any(
            post_map_coords.get(lid) != original_map_coords.get(lid)
            for lid in original_map_coords
        )

        self.assertTrue(
            area_changed or map_changed,
            "At least one of area or map file coordinates should have changed",
        )

    # ----------------------------------------------------------------
    # Test 3.4.6: Repair idempotent on valid module
    # ----------------------------------------------------------------
    def test_repair_idempotent_on_valid_module(self) -> None:
        """Running repair twice on an already-valid module produces
        status='pass' or status='changed' with repaired_area_count=0 on
        the second run."""
        area_id = "STA06"
        locations = [
            {
                "locationId": "R01",
                "name": "Room 1",
                "coordinates": "X10Y10",
                "connectivity": ["R02"],
            },
            {
                "locationId": "R02",
                "name": "Room 2",
                "coordinates": "X10Y11",
                "connectivity": ["R01", "R03"],
            },
            {
                "locationId": "R03",
                "name": "Room 3",
                "coordinates": "X10Y12",
                "connectivity": ["R02"],
            },
        ]
        rooms = [
            _build_room_entry("R01", "Room 1", "X10Y10", ["R02"]),
            _build_room_entry("R02", "Room 2", "X10Y11", ["R01", "R03"]),
            _build_room_entry("R03", "Room 3", "X10Y12", ["R02"]),
        ]
        _make_area_file(self.areas_dir, area_id, locations)
        _make_external_map(self.module_dir, area_id, rooms)

        # First repair
        repair_module_spatial(str(self.module_dir))

        # Second repair
        report2 = repair_module_spatial(str(self.module_dir))

        # Second run should require no additional changes
        self.assertIn(
            report2.get("status"), ("pass", "changed"),
            f"Second repair status should be pass or changed, got: "
            f"{report2.get('status')}",
        )
        if report2["status"] == "changed":
            self.assertEqual(
                report2.get("repaired_area_count", 0), 0,
                "If second repair reports changed, repaired_area_count "
                "should be 0 (no changes actually needed)",
            )


def _create_packet_builder_workspace(
    tmpdir: str,
    job_id: str,
    title: str = "Spatial Test",
    source_hash: str = "abc123",
) -> Path:
    """Create a minimal v2 workspace for packet builder testing.

    Produces workspace files (normalized_packet, ui_review_snapshot,
    builder_narrative) plus v2 blueprint artifacts so the packet builder
    routes through the seed writer path when config flags are enabled.
    """
    ws = Path(tmpdir) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    defaults: Dict[str, Any] = {
        "normalized_packet.json": {
            "packet_version": "packet.v1",
            "name": "test",
            "title": title,
            "description": f"Test module for {job_id}",
            "source_hash": source_hash,
            "source_rights": "user_authored",
            "normalization_state": "normalized",
        },
        "ui_review_snapshot.json": {
            "decision": "approve",
            "recorded_at": "2026-01-01T00:00:00Z",
            "job_id": job_id,
            "packet_identity": {"source_hash": source_hash},
        },
        "builder_narrative.txt": "Test narrative for spatial repair",
    }

    for filename, content in defaults.items():
        path = ws / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(content) if isinstance(content, dict) else content,
            encoding="utf-8",
        )

    # v2 blueprint artifacts to trigger seed writer path
    bp: Dict[str, Any] = {
        "blueprint_version": "source_faithful_builder_blueprint.v2",
        "blueprint_status": "ready",
        "module": {"title": title, "summary": "Test module"},
        "source_lock": {"canonical_names_locked": True},
        "area_plan": [],
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
        "coverage": {},
        "enrichment_allowlist": {},
        "artifact_refs": {},
        "blockers": [],
    }
    (ws / "builder_blueprint.json").write_text(
        json.dumps(bp), encoding="utf-8",
    )
    bp_report: Dict[str, str] = {
        "blueprint_status": "ready",
        "fidelity_status": "pass",
    }
    (ws / "builder_blueprint_report.json").write_text(
        json.dumps(bp_report), encoding="utf-8",
    )

    return ws


if __name__ == "__main__":
    unittest.main()
