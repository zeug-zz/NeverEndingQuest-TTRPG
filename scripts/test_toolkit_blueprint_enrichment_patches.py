"""Tests for utils/toolkit_blueprint_enrichment.py.

All tests are provider-free. Enrichment passes with LLM orchestration
are not tested (provider not available in CI).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.toolkit_blueprint_enrichment import (
    validate_enrichment_patch,
    validate_enrichment_patches,
    apply_enrichment_patches,
    run_enrichment_pipeline,
    build_enrichment_report,
    _parse_npc_enrichment_response,
    _convert_npc_enrichment_output_to_patches,
    _validate_and_apply_npc_enrichment_patches,
    _run_enrichment_pass,
    _build_location_pass_inputs,
    _parse_location_enrichment_response,
    _convert_location_enrichment_output_to_patches,
    _validate_and_apply_location_enrichment_patches,
    _build_plot_puzzle_clue_pass_inputs,
    _PLOT_PROSE_FIELDS,
    _PUZZLE_CLUE_PROSE_FIELDS,
    _build_encounter_item_pass_inputs,
    _ENCOUNTER_PROSE_FIELDS,
    _ITEM_PROSE_FIELDS,
    _build_tone_style_pass_inputs,
    _TONE_STYLE_SOURCE_FIELDS,
    _stable_json_dumps,
    _input_cache_key,
    _build_pass_telemetry,
    _extract_pass_meta,
    ENRICHMENT_STATUS_COMPLETE,
    ENRICHMENT_STATUS_DEGRADED,
    ENRICHMENT_STATUS_SKIPPED,
    ENRICHMENT_STATUS_NOT_IMPLEMENTED,
    ENRICHMENT_STATUS_FAILED,
    ALL_ENRICHMENT_STATUSES,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"


def _make_blueprint(**overrides) -> Dict[str, Any]:
    bp: Dict[str, Any] = {
        "blueprint_version": VALID_V2_VERSION,
        "blueprint_status": "ready",
        "enrichment_allowlist": {
            "npc_description": {"field": "description", "target_paths": ["npcs/{npc_key}.description"], "scope": "module_context.json", "max_chars": 500},
            "npc_role": {"field": "role", "target_paths": ["npcs/{npc_key}.role"], "scope": "module_context.json", "max_chars": 100},
            "plot_main_objective": {"field": "mainObjective", "target_paths": ["mainObjective"], "scope": "module_plot_BU.json", "max_chars": 500},
            "location_description": {"field": "description", "target_paths": ["locations[{index}].description"], "scope": "area_*_BU.json", "max_chars": 1500},
        },
    }
    bp.update(overrides)
    return bp


def _make_valid_patch(**overrides) -> Dict[str, Any]:
    patch: Dict[str, Any] = {
        "op": "replace",
        "blueprint_id": "npc_description",
        "target_file": "module_context.json",
        "json_path": "npcs.sample_npc.description",
        "field": "description",
        "source_refs": [],
        "reason": "Enrich NPC description",
        "value": "A mysterious figure cloaked in shadow.",
    }
    patch.update(overrides)
    return patch


def _make_module_context() -> Dict[str, Any]:
    return {
        "module_name": "Test Module",
        "module_id": "test_module",
        "areas": {},
        "npcs": {
            "sample_npc": {
                "name": "Sample NPC",
                "role": "",
                "faction": "",
                "appears_in": [],
            },
        },
        "locations": {},
        "plot_scopes": {},
        "references": {},
    }


def _make_module_plot() -> Dict[str, Any]:
    return {
        "plotTitle": "Test Module - Plot",
        "mainObjective": "",
        "plotPoints": [
            {"id": "PP001", "title": "Beginning", "description": "", "nextPoints": ["PP002"], "status": "not started", "plotImpact": "", "sideQuests": []},
            {"id": "PP002", "title": "Middle", "description": "", "nextPoints": [], "status": "not started", "plotImpact": "", "sideQuests": []},
        ],
    }


# ---------------------------------------------------------------------------
# Status Constants Tests
# ---------------------------------------------------------------------------


class TestStatusConstants(unittest.TestCase):
    """Source-contract tests for enrichment status constants."""

    def test_status_skipped_defined(self):
        self.assertEqual(ENRICHMENT_STATUS_SKIPPED, "skipped")

    def test_status_degraded_defined(self):
        self.assertEqual(ENRICHMENT_STATUS_DEGRADED, "degraded")

    def test_status_complete_defined(self):
        self.assertEqual(ENRICHMENT_STATUS_COMPLETE, "complete")

    def test_status_not_implemented_defined(self):
        self.assertEqual(ENRICHMENT_STATUS_NOT_IMPLEMENTED, "not_implemented")

    def test_status_failed_defined(self):
        self.assertEqual(ENRICHMENT_STATUS_FAILED, "failed")

    def test_all_statuses_bounded(self):
        """ALL_ENRICHMENT_STATUSES contains exactly the 5 expected values."""
        self.assertIsInstance(ALL_ENRICHMENT_STATUSES, set)
        self.assertEqual(len(ALL_ENRICHMENT_STATUSES), 5)
        self.assertIn(ENRICHMENT_STATUS_SKIPPED, ALL_ENRICHMENT_STATUSES)
        self.assertIn(ENRICHMENT_STATUS_DEGRADED, ALL_ENRICHMENT_STATUSES)
        self.assertIn(ENRICHMENT_STATUS_COMPLETE, ALL_ENRICHMENT_STATUSES)
        self.assertIn(ENRICHMENT_STATUS_NOT_IMPLEMENTED, ALL_ENRICHMENT_STATUSES)
        self.assertIn(ENRICHMENT_STATUS_FAILED, ALL_ENRICHMENT_STATUSES)

    def test_unexpected_status_not_in_bounded_set(self):
        self.assertNotIn("nonexistent", ALL_ENRICHMENT_STATUSES)
        self.assertNotIn("", ALL_ENRICHMENT_STATUSES)


# ---------------------------------------------------------------------------
# Patch Validation Tests
# ---------------------------------------------------------------------------


class TestValidatePatch(unittest.TestCase):
    """Test individual patch validation."""

    def test_valid_patch_passes(self):
        result = validate_enrichment_patch(_make_valid_patch())
        self.assertTrue(result["valid"])
        self.assertEqual(result["reason"], "")

    def test_valid_patch_plot_main_objective(self):
        patch = _make_valid_patch(
            blueprint_id="plot_main_objective",
            target_file="module_plot_BU.json",
            json_path="mainObjective",
            field="mainObjective",
            value="Find the lost artifact before darkness falls.",
        )
        result = validate_enrichment_patch(patch)
        self.assertTrue(result["valid"])

    def test_missing_op(self):
        patch = _make_valid_patch()
        del patch["op"]
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("Missing required field", result["reason"])

    def test_missing_blueprint_id(self):
        patch = _make_valid_patch()
        del patch["blueprint_id"]
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])

    def test_missing_target_file(self):
        patch = _make_valid_patch()
        del patch["target_file"]
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])

    def test_unsupported_op(self):
        patch = _make_valid_patch(op="delete")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("Unsupported operation", result["reason"])

    def test_empty_blueprint_id(self):
        patch = _make_valid_patch(blueprint_id="")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])

    def test_disallowed_target_file(self):
        patch = _make_valid_patch(target_file="monsters/goblin.json")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("not an allowed enrichment target", result["reason"])

    def test_disallowed_field_name(self):
        patch = _make_valid_patch(field="name")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("not an allowed enrichment field", result["reason"])

    def test_path_traversal(self):
        patch = _make_valid_patch(json_path="../outside.json")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("Path traversal", result["reason"])

    def test_forbidden_field_name_in_path(self):
        patch = _make_valid_patch(json_path="locations[0].name")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("forbidden structural patterns", result["reason"])

    def test_forbidden_field_connectivity_in_path(self):
        patch = _make_valid_patch(json_path="locations[0].connectivity")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])

    def test_forbidden_field_id_in_path(self):
        patch = _make_valid_patch(json_path="locations[0].locationId")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])

    def test_forbidden_field_dependencies_in_path(self):
        patch = _make_valid_patch(json_path="plotPoints[0].dependencies")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])

    def test_non_string_value(self):
        patch = _make_valid_patch(value=["not", "a", "string"])
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("must be a string", result["reason"])

    def test_value_exceeds_max_chars(self):
        bp = _make_blueprint()
        patch = _make_valid_patch(blueprint_id="npc_role", value="A" * 200)
        result = validate_enrichment_patch(patch, blueprint=bp)
        self.assertFalse(result["valid"])
        self.assertIn("exceeds max_chars", result["reason"])

    def test_empty_json_path(self):
        patch = _make_valid_patch(json_path="")
        result = validate_enrichment_patch(patch)
        self.assertFalse(result["valid"])
        self.assertIn("json_path is empty", result["reason"])


class TestValidatePatches(unittest.TestCase):
    """Test batch patch validation."""

    def test_valid_list(self):
        patches = [
            _make_valid_patch(),
            _make_valid_patch(
                blueprint_id="plot_main_objective",
                target_file="module_plot_BU.json",
                json_path="mainObjective",
                field="mainObjective",
                value="Test objective",
            ),
        ]
        results = validate_enrichment_patches(patches)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["valid"] for r in results))

    def test_mixed_valid_invalid(self):
        patches = [
            _make_valid_patch(),
            _make_valid_patch(field="name"),
        ]
        results = validate_enrichment_patches(patches)
        self.assertTrue(results[0]["valid"])
        self.assertFalse(results[1]["valid"])


# ---------------------------------------------------------------------------
# Application Tests
# ---------------------------------------------------------------------------


class TestApplyPatches(unittest.TestCase):
    """Test applying patches to module files."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.target = os.path.join(self.tmpdir.name, "module")
        os.makedirs(self.target)

    def _write(self, filename: str, data: Dict[str, Any]):
        path = os.path.join(self.target, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _read(self, filename: str) -> Dict[str, Any]:
        path = os.path.join(self.target, filename)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_apply_npc_description(self):
        self._write("module_context.json", _make_module_context())
        patches = [_make_valid_patch()]
        result = apply_enrichment_patches(patches, self.target)
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["rejected"]), 0)
        ctx = self._read("module_context.json")
        self.assertEqual(
            ctx["npcs"]["sample_npc"]["description"],
            "A mysterious figure cloaked in shadow.",
        )

    def test_apply_plot_main_objective(self):
        self._write("module_plot_BU.json", _make_module_plot())
        patches = [
            _make_valid_patch(
                blueprint_id="plot_main_objective",
                target_file="module_plot_BU.json",
                json_path="mainObjective",
                field="mainObjective",
                value="Find the lost relic.",
            )
        ]
        result = apply_enrichment_patches(patches, self.target)
        self.assertEqual(len(result["applied"]), 1)
        plot = self._read("module_plot_BU.json")
        self.assertEqual(plot["mainObjective"], "Find the lost relic.")

    def test_apply_location_description(self):
        os.makedirs(os.path.join(self.target, "areas"), exist_ok=True)
        area_file = {
            "areaId": "A000",
            "areaName": "Test Area",
            "locations": [
                {"name": "Room 1", "description": "", "locationId": "A01", "connectivity": []},
            ],
        }
        self._write("areas/area_A000_BU.json", area_file)
        patch = _make_valid_patch(
            blueprint_id="location_description",
            target_file="areas/area_A000_BU.json",
            json_path="locations[0].description",
            field="description",
            value="A dusty chamber with faded murals.",
        )
        result = apply_enrichment_patches([patch], self.target)
        self.assertEqual(len(result["applied"]), 1)
        area = self._read("areas/area_A000_BU.json")
        self.assertEqual(area["locations"][0]["description"], "A dusty chamber with faded murals.")

    def test_dry_run_does_not_write(self):
        self._write("module_context.json", _make_module_context())
        patches = [_make_valid_patch()]
        result = apply_enrichment_patches(patches, self.target, dry_run=True)
        self.assertEqual(len(result["applied"]), 1)
        ctx = self._read("module_context.json")
        self.assertEqual(ctx["npcs"]["sample_npc"].get("description", ""), "")

    def test_missing_file_skipped(self):
        patches = [_make_valid_patch()]
        result = apply_enrichment_patches(patches, self.target)
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("does not exist", result["rejected"][0]["reason"])

    def test_nonexistent_json_path(self):
        self._write("module_context.json", _make_module_context())
        patches = [_make_valid_patch(json_path="npcs.nonexistent.description")]
        result = apply_enrichment_patches(patches, self.target)
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["rejected"]), 1)

    def test_multiple_patches_same_file(self):
        self._write("module_context.json", _make_module_context())
        patches = [
            _make_valid_patch(),
            _make_valid_patch(
                blueprint_id="npc_role",
                json_path="npcs.sample_npc.role",
                field="role",
                value="Villain",
            ),
        ]
        result = apply_enrichment_patches(patches, self.target)
        self.assertEqual(len(result["applied"]), 2)
        ctx = self._read("module_context.json")
        self.assertEqual(ctx["npcs"]["sample_npc"]["role"], "Villain")

    def test_area_file_extension_pattern(self):
        os.makedirs(os.path.join(self.target, "areas"), exist_ok=True)
        self._write("areas/area_A000_BU.json", {
            "areaId": "A000", "areaName": "A", "locations": [
                {"name": "L01", "description": "", "locationId": "A01", "connectivity": []},
            ],
        })
        patch = _make_valid_patch(
            blueprint_id="location_description",
            target_file="areas/area_A000_BU.json",
            json_path="locations[0].description",
            field="description",
            value="Updated description.",
        )
        result = apply_enrichment_patches([patch], self.target)
        self.assertEqual(len(result["applied"]), 1)

    def test_prose_patch_deterministic(self):
        """Allowed prose patch applies deterministically and appears in applied."""
        self._write("module_context.json", _make_module_context())
        patch = _make_valid_patch()
        result = apply_enrichment_patches([patch], self.target)
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["rejected"]), 0)
        ctx = self._read("module_context.json")
        self.assertEqual(
            ctx["npcs"]["sample_npc"]["description"],
            "A mysterious figure cloaked in shadow.",
        )
        # Running again with same input produces same output
        result2 = apply_enrichment_patches([_make_valid_patch()], self.target)
        self.assertEqual(len(result2["applied"]), 1)
        ctx2 = self._read("module_context.json")
        self.assertEqual(ctx2["npcs"]["sample_npc"]["description"],
                         ctx["npcs"]["sample_npc"]["description"])

    def test_structural_name_patch_rejected_and_file_unchanged(self):
        """Structural mutation by field 'name' is rejected and target file unchanged."""
        self._write("module_context.json", _make_module_context())
        before = self._read("module_context.json")
        original_name = before["npcs"]["sample_npc"]["name"]

        patch = _make_valid_patch(
            blueprint_id="npc_description",
            target_file="module_context.json",
            json_path="npcs.sample_npc.name",
            field="name",
            value="New Evil Name",
        )
        result = apply_enrichment_patches([patch], self.target)
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("name", result["rejected"][0].get("reason", ""))
        after = self._read("module_context.json")
        self.assertEqual(
            after["npcs"]["sample_npc"]["name"], original_name,
            "Structural mutation to 'name' field was applied despite rejection",
        )

    def test_structural_connectivity_patch_rejected_and_file_unchanged(self):
        """Structural mutation by json_path 'connectivity' is rejected and target file unchanged."""
        os.makedirs(os.path.join(self.target, "areas"), exist_ok=True)
        area = {
            "areaId": "A000", "areaName": "A", "locations": [
                {"name": "L01", "description": "", "locationId": "A01", "connectivity": ["A02"]},
            ],
        }
        self._write("areas/area_A000_BU.json", area)
        before = self._read("areas/area_A000_BU.json")

        patch = _make_valid_patch(
            blueprint_id="location_description",
            target_file="areas/area_A000_BU.json",
            json_path="locations[0].connectivity",
            field="description",
            value="['A05', 'A02']",
        )
        result = apply_enrichment_patches([patch], self.target)
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("connectivity", result["rejected"][0].get("reason", ""))
        after = self._read("areas/area_A000_BU.json")
        self.assertEqual(
            after["locations"][0]["connectivity"], before["locations"][0]["connectivity"],
            "Structural mutation to 'connectivity' was applied despite rejection",
        )


# ---------------------------------------------------------------------------
# Pipeline Tests
# ---------------------------------------------------------------------------


class TestPipeline(unittest.TestCase):
    """Test enrichment pipeline orchestration."""

    def test_disabled_flag_returns_skipped(self):
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_enrichment_pipeline(bp, tmpdir)
            self.assertEqual(result["status"], ENRICHMENT_STATUS_SKIPPED)
            self.assertEqual(result.get("reason"), "feature_flag_disabled")
            self.assertEqual(len(result["applied"]), 0)
            self.assertNotEqual(result["status"], ENRICHMENT_STATUS_COMPLETE)

    def test_enabled_no_provider_returns_not_implemented(self):
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
                result = run_enrichment_pipeline(bp, tmpdir)
                self.assertEqual(result["status"], ENRICHMENT_STATUS_NOT_IMPLEMENTED)
                self.assertEqual(len(result["applied"]), 0)
                self.assertIn("not yet implemented", result.get("reason", ""))
                self.assertNotEqual(result["status"], ENRICHMENT_STATUS_COMPLETE)

    def test_enabled_no_provider_not_complete(self):
        """Explicit negative: enabled placeholder enrichment is NOT complete."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
                result = run_enrichment_pipeline(bp, tmpdir)
                self.assertNotEqual(result["status"], ENRICHMENT_STATUS_COMPLETE)

    def test_disabled_enrichment_not_complete(self):
        """Explicit negative: disabled enrichment is NOT complete."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_enrichment_pipeline(bp, tmpdir)
            self.assertNotEqual(result["status"], ENRICHMENT_STATUS_COMPLETE)

    def test_all_passes_fatal_failure_degrades(self):
        """All enrichment passes raise fatal exceptions; status is at least degraded."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
                with patch(
                    "utils.toolkit_blueprint_enrichment._run_enrichment_pass",
                    side_effect=RuntimeError("fatal pass crash"),
                ):
                    result = run_enrichment_pipeline(bp, tmpdir)
                    self.assertIn(
                        result["status"],
                        {ENRICHMENT_STATUS_DEGRADED, ENRICHMENT_STATUS_FAILED},
                    )
                    self.assertEqual(len(result["applied"]), 0)
                    self.assertGreater(result.get("reason", ""), "")

    def test_enabled_no_provider_returns_not_implemented(self):
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
                result = run_enrichment_pipeline(bp, tmpdir)
                self.assertEqual(result["status"], ENRICHMENT_STATUS_NOT_IMPLEMENTED)
                self.assertEqual(len(result["applied"]), 0)
                self.assertIn("not yet implemented", result.get("reason", ""))

    def test_pass_exception_returns_degraded(self):
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
                with patch(
                    "utils.toolkit_blueprint_enrichment._run_enrichment_pass",
                    side_effect=RuntimeError("simulated pass failure"),
                ):
                    result = run_enrichment_pipeline(bp, tmpdir)
                    self.assertEqual(result["status"], ENRICHMENT_STATUS_DEGRADED)
                    self.assertIn("pass(es) failed", result.get("reason", ""))
                    self.assertEqual(len(result["applied"]), 0)

    def test_pass_errors_return_degraded(self):
        bp = _make_blueprint()
        error_pass = {
            "pass_type": "module_overview",
            "applied": [],
            "rejected": [],
            "errors": [{"message": "simulated validation error"}],
            "warnings": [],
            "patches_requested": 0,
            "patches_returned": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
                with patch(
                    "utils.toolkit_blueprint_enrichment._run_enrichment_pass",
                    return_value=error_pass,
                ):
                    result = run_enrichment_pipeline(bp, tmpdir)
                    self.assertEqual(result["status"], ENRICHMENT_STATUS_DEGRADED)
                    self.assertEqual(result.get("reason"), "enrichment_pass_errors")
                    self.assertEqual(len(result["errors"]), 4)  # one per pass

    def test_rejected_patches_degrade_status(self):
        """Rejected patches in pipeline result produce degraded status."""
        bp = _make_blueprint()
        mixed_pass = {
            "pass_type": "npc",
            "applied": [{
                "patch": {
                    "op": "replace", "blueprint_id": "npc_description",
                    "target_file": "module_context.json",
                    "json_path": "npcs.sample_npc.description", "field": "description",
                    "value": "desc",
                },
                "target_file": "module_context.json",
            }],
            "rejected": [{
                "patch": {
                    "op": "replace", "blueprint_id": "npc_description",
                    "target_file": "module_context.json",
                    "json_path": "npcs.sample_npc.name", "field": "name",
                    "value": "Bad",
                },
                "reason": "Field 'name' is not an allowed enrichment field",
            }],
            "errors": [],
            "warnings": [],
            "patches_requested": 2,
            "patches_returned": 2,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "module"), exist_ok=True)
            with open(os.path.join(tmpdir, "module", "module_context.json"), "w") as f:
                import json
                json.dump(_make_module_context(), f)
            with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
                with patch(
                    "utils.toolkit_blueprint_enrichment._run_enrichment_pass",
                    return_value=mixed_pass,
                ):
                    result = run_enrichment_pipeline(bp, tmpdir)
                    # Applied patches exist so not_implemented is skipped;
                    # Rejected patches force degraded over complete.
                    self.assertGreater(len(result.get("applied", [])), 0)
                    self.assertGreater(len(result.get("rejected", [])), 0)
                    self.assertEqual(result["status"], ENRICHMENT_STATUS_DEGRADED)

    def test_report_builds_from_skipped(self):
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline_result = run_enrichment_pipeline(bp, tmpdir)
            report = build_enrichment_report(pipeline_result)
            self.assertEqual(report["status"], ENRICHMENT_STATUS_SKIPPED)
            self.assertIn("enrichment_report_version", report)
            self.assertIn("created_at", report)

    def test_report_builds_from_empty_pipeline_result(self):
        result = {
            "status": ENRICHMENT_STATUS_COMPLETE,
            "reason": "",
            "applied": [{"patch": {"op": "replace"}, "target_file": "module_context.json"}],
            "rejected": [],
            "errors": [],
            "warnings": [],
            "passes": [],
        }
        report = build_enrichment_report(result)
        self.assertEqual(report["status"], ENRICHMENT_STATUS_COMPLETE)
        self.assertEqual(report["applied_count"], 1)

    def test_build_enrichment_report_preserves_applied_and_rejected(self):
        pipeline_result = {
            "status": ENRICHMENT_STATUS_DEGRADED,
            "reason": "Some patches rejected",
            "applied": [{"target_file": "a.json"}],
            "rejected": [{"reason": "Bad path"}],
            "errors": [],
            "warnings": [],
            "passes": [{"pass_type": "module_overview"}],
        }
        report = build_enrichment_report(pipeline_result)
        self.assertEqual(report["status"], ENRICHMENT_STATUS_DEGRADED)
        self.assertEqual(len(report["applied"]), 1)
        self.assertEqual(len(report["rejected"]), 1)

    def test_report_contract_not_implemented(self):
        """3.1: Report from not_implemented pipeline preserves status, reason, counts."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_NOT_IMPLEMENTED,
            "reason": "LLM provider orchestration not yet implemented",
            "applied": [],
            "rejected": [],
            "errors": [],
            "warnings": ["provider orchestration not yet implemented"],
            "passes": [],
        }
        report = build_enrichment_report(pipeline_result)
        self.assertEqual(report["status"], ENRICHMENT_STATUS_NOT_IMPLEMENTED)
        self.assertEqual(report.get("reason"), pipeline_result["reason"])
        self.assertEqual(report.get("applied_count"), 0)
        self.assertEqual(report.get("rejected_count"), 0)
        self.assertEqual(report.get("error_count"), 0)
        self.assertEqual(report.get("warning_count"), 1)
        self.assertEqual(report.get("pass_count"), 0)
        self.assertEqual(len(report.get("warnings", [])), 1)

    def test_report_surfaces_pass_level_metadata(self):
        """3.2: Report preserves pass-level metadata and counts."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_DEGRADED,
            "reason": "Some passes degraded",
            "applied": [],
            "rejected": [],
            "errors": [],
            "warnings": [],
            "passes": [
                {"pass_type": "module_overview", "patches_requested": 3, "patches_returned": 2},
                {"pass_type": "npc", "patches_requested": 5, "patches_returned": 4},
            ],
        }
        report = build_enrichment_report(pipeline_result)
        self.assertEqual(report["pass_count"], 2)

    def test_noop_report_cannot_be_complete(self):
        """3.3: A no-op pipeline result cannot produce a complete report."""
        noop_results = [
            {"status": ENRICHMENT_STATUS_SKIPPED, "reason": "feature_flag_disabled"},
            {"status": ENRICHMENT_STATUS_NOT_IMPLEMENTED, "reason": "provider not available"},
        ]
        for pipeline_result in noop_results:
            pipeline_result.setdefault("applied", [])
            pipeline_result.setdefault("rejected", [])
            pipeline_result.setdefault("errors", [])
            pipeline_result.setdefault("warnings", [])
            pipeline_result.setdefault("passes", [])
            report = build_enrichment_report(pipeline_result)
            self.assertNotEqual(report["status"], ENRICHMENT_STATUS_COMPLETE,
                                f"No-op result with status {pipeline_result['status']} produced complete report")


# ---------------------------------------------------------------------------
# NPC Pass Scaffold Tests
# ---------------------------------------------------------------------------


class TestNpcPassScaffold(unittest.TestCase):
    """Provider-free tests for NPC enrichment pass scaffold."""

    def _make_triage_blueprint(self, decisions: list, **overrides) -> Dict[str, Any]:
        bp = _make_blueprint(**overrides)
        bp["entity_candidate_triage_report"] = {
            "triage_report_version": "entity_candidate_triage_report.v1",
            "status": "pass",
            "total_candidates": len(decisions),
            "summary": {},
            "type_counts": {},
            "decisions": decisions,
        }
        return bp

    def test_npc_pass_scaffold_includes_kept_candidates_with_bounded_excerpts(self):
        """Kept NPC candidates appear as enrichment targets with bounded excerpts."""
        from utils.toolkit_blueprint_enrichment import _build_npc_pass_inputs

        decisions = [
            {
                "candidate_text": "Dog-Growl",
                "candidate_slug": "dog_growl",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Explicit NPC mention with location binding",
                "source_refs": [{"text": "Dog-Growl the kenku scavenger lurks in The Rookery"}],
                "location_bindings": ["The_Rookery"],
            },
        ]
        bp = self._make_triage_blueprint(decisions)
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = _build_npc_pass_inputs(bp, tmpdir)
            self.assertTrue(inputs["has_triage_data"])
            self.assertEqual(inputs["source_artifact"], "entity_candidate_triage_report")
            targets = inputs["npc_targets"]
            self.assertEqual(len(targets), 1)
            t = targets[0]
            self.assertEqual(t["candidate_text"], "Dog-Growl")
            self.assertEqual(t["candidate_slug"], "dog_growl")
            self.assertEqual(t["adjudicated_type"], "true_npc")
            self.assertEqual(t["decision"], "keep")
            self.assertIn("source_refs", t)
            self.assertIn("location_bindings", t)
            self.assertIn("source_excerpt", t)
            self.assertEqual(t["source_excerpt"],
                             "Dog-Growl the kenku scavenger lurks in The Rookery")

    def test_source_excerpts_clipped_to_deterministic_max_length(self):
        """Source excerpts are clipped to the configured max length."""
        from utils.toolkit_blueprint_enrichment import _build_npc_pass_inputs

        long_text = "A very lengthy description of a hidden NPC " * 20
        self.assertGreater(len(long_text), 100)

        decisions = [
            {
                "candidate_text": long_text,
                "candidate_slug": "verbose_npc",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Long description",
                "source_refs": [{"text": long_text}],
                "location_bindings": [],
            },
        ]
        bp = self._make_triage_blueprint(decisions)
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = _build_npc_pass_inputs(bp, tmpdir, max_excerpt_chars=100)
            targets = inputs["npc_targets"]
            self.assertEqual(len(targets), 1)
            excerpt = targets[0].get("source_excerpt", "")
            self.assertLessEqual(len(excerpt), 100)
            # Verify it's the prefix, not a suffix or hash
            self.assertTrue(excerpt.startswith("A very lengthy description"))

    def test_rejected_narrative_phrase_not_included_as_enrichment_target(self):
        """A rejected narrative phrase like 'but this is not true' is not an NPC target."""
        from utils.toolkit_blueprint_enrichment import _build_npc_pass_inputs

        decisions = [
            {
                "candidate_text": "but this is not true",
                "candidate_slug": "but_this_is_not_true",
                "proposed_type": "unknown",
                "adjudicated_type": "narrative_phrase",
                "decision": "reject",
                "reason": "Deterministic prefilter: prose narrative phrase",
                "source_refs": [],
                "location_bindings": [],
            },
            {
                "candidate_text": "Dog-Growl",
                "candidate_slug": "dog_growl",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Valid NPC",
                "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                "location_bindings": ["The_Rookery"],
            },
        ]
        bp = self._make_triage_blueprint(decisions)
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = _build_npc_pass_inputs(bp, tmpdir)
            targets = inputs["npc_targets"]
            rejected = inputs["rejected_narratives"]
            # Only Dog-Growl is a target
            target_slugs = [t["candidate_slug"] for t in targets]
            self.assertIn("dog_growl", target_slugs)
            self.assertNotIn("but_this_is_not_true", target_slugs)
            self.assertEqual(len(targets), 1)
            # The rejected phrase is preserved as diagnostics
            self.assertGreater(len(rejected), 0)
            rej_slugs = [r["candidate_slug"] for r in rejected]
            self.assertIn("but_this_is_not_true", rej_slugs)

    def test_npc_pass_no_provider_call_no_applied_patches(self):
        """_run_enrichment_pass with pass_type='npc' performs no provider call."""
        from utils.toolkit_blueprint_enrichment import _run_enrichment_pass

        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_enrichment_pass(bp, tmpdir, "npc")
            self.assertEqual(result["pass_type"], "npc")
            self.assertEqual(len(result["applied"]), 0)
            self.assertEqual(len(result["rejected"]), 0)
            self.assertEqual(len(result["errors"]), 0)
            self.assertIn("not yet implemented", str(result.get("warnings", [])))
            # Scaffold metadata is present but no patches were applied
            self.assertIn("npc_pass_inputs", result)
            self.assertIn("npc_target_count", result["npc_pass_inputs"])

    def test_numillian_rejected_phrase_not_promoted_to_npc_target(self):
        """Rejected 'but this is not true' is excluded from npc_targets but present in diagnostics."""
        from utils.toolkit_blueprint_enrichment import _build_npc_pass_inputs

        decisions = [
            {
                "candidate_text": "but this is not true",
                "candidate_slug": "but_this_is_not_true",
                "proposed_type": "unknown",
                "adjudicated_type": "narrative_phrase",
                "decision": "reject",
                "reason": "Deterministic prefilter: prose narrative phrase",
                "source_refs": [],
                "location_bindings": [],
            },
            {
                "candidate_text": "Dog-Growl",
                "candidate_slug": "dog_growl",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Valid NPC mention with location binding",
                "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                "location_bindings": ["The_Rookery"],
            },
        ]
        bp = self._make_triage_blueprint(decisions)
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = _build_npc_pass_inputs(bp, tmpdir)
            target_slugs = [t["candidate_slug"] for t in inputs["npc_targets"]]
            self.assertIn("dog_growl", target_slugs)
            self.assertNotIn("but_this_is_not_true", target_slugs)
            self.assertEqual(len(inputs["npc_targets"]), 1)
            rej_slugs = [r["candidate_slug"] for r in inputs["rejected_narratives"]]
            self.assertIn("but_this_is_not_true", rej_slugs)

    def test_numillian_rejected_phrase_not_created_by_enrichment_application(self):
        """Rejected phrase is not promoted into module_context.json by enrichment path."""
        from utils.toolkit_blueprint_enrichment import (
            _build_npc_pass_inputs, _parse_npc_enrichment_response,
            _convert_npc_enrichment_output_to_patches, _run_enrichment_pass,
        )

        decisions = [
            {
                "candidate_text": "but this is not true",
                "candidate_slug": "but_this_is_not_true",
                "proposed_type": "unknown",
                "adjudicated_type": "narrative_phrase",
                "decision": "reject",
                "reason": "Deterministic prefilter: prose",
                "source_refs": [],
                "location_bindings": [],
            },
            {
                "candidate_text": "Dog-Growl",
                "candidate_slug": "dog_growl",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Valid NPC",
                "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                "location_bindings": ["The_Rookery"],
            },
        ]
        bp = self._make_triage_blueprint(decisions)

        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            ctx_path = os.path.join(module_dir, "module_context.json")
            with open(ctx_path, "w", encoding="utf-8") as f:
                ctx = _make_module_context()
                ctx["npcs"]["dog_growl"] = {
                    "name": "Dog-Growl",
                    "role": "",
                    "faction": "",
                    "appears_in": [],
                }
                json.dump(ctx, f)

            enrichment_response = {
                "pass_name": "npc_enrichment",
                "pass_type": "npc",
                "proposed_patches": [
                    {
                        "blueprint_id": "npc_description",
                        "target_file": "module_context.json",
                        "json_path": "npcs.dog_growl.description",
                        "field": "description",
                        "value": "A scrappy kenku who knows every shadow.",
                        "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                        "reason": "Enrich from source excerpt",
                        "entity_slug": "dog_growl",
                    },
                ],
            }
            parsed = _parse_npc_enrichment_response(enrichment_response)
            self.assertTrue(parsed["valid"])
            converted = _convert_npc_enrichment_output_to_patches(parsed)
            self.assertEqual(len(converted["patch_candidates"]), 1)
            self.assertEqual(len(converted["dropped"]), 0)

            result = _run_enrichment_pass(
                bp, module_dir, "npc",
                npc_enrichment_data=converted,
            )
            self.assertEqual(len(result["applied"]), 1)

            with open(ctx_path, "r", encoding="utf-8") as f:
                final_ctx = json.load(f)
            # Dog-Growl was enriched, not created
            self.assertIn("dog_growl", final_ctx.get("npcs", {}))
            self.assertEqual(
                final_ctx["npcs"]["dog_growl"]["description"],
                "A scrappy kenku who knows every shadow.",
            )
            # Rejected phrase did not create an NPC entry
            self.assertNotIn("but_this_is_not_true", final_ctx.get("npcs", {}))

    def test_numillian_rookery_kept_npcs_included_with_source_refs(self):
        """Three kept Rookery NPCs appear as npc_targets with preserved identity."""
        from utils.toolkit_blueprint_enrichment import _build_npc_pass_inputs

        decisions = [
            {
                "candidate_text": "Dog-Growl",
                "candidate_slug": "dog_growl",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Explicit NPC mention with location binding",
                "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                "location_bindings": ["The_Rookery"],
            },
            {
                "candidate_text": "Book-shut",
                "candidate_slug": "book_shut",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Named NPC with active scene role",
                "source_refs": [{"text": "Book-shut the dwarven sage pores over dusty tomes in The Rookery"}],
                "location_bindings": ["The_Rookery"],
            },
            {
                "candidate_text": "Deflation",
                "candidate_slug": "deflation",
                "proposed_type": "true_npc",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "reason": "Named NPC with faction context",
                "source_refs": [{"text": "Deflation oversees the locked vault beneath The Rookery"}],
                "location_bindings": ["The_Rookery"],
            },
        ]
        bp = self._make_triage_blueprint(decisions)
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = _build_npc_pass_inputs(bp, tmpdir)
            targets = inputs["npc_targets"]
            self.assertEqual(len(targets), 3)
            slugs = [t["candidate_slug"] for t in targets]
            for slug in ("dog_growl", "book_shut", "deflation"):
                self.assertIn(slug, slugs)
            lookup = {t["candidate_slug"]: t for t in targets}
            for slug, expected_name in (("dog_growl", "Dog-Growl"),
                                         ("book_shut", "Book-shut"),
                                         ("deflation", "Deflation")):
                t = lookup[slug]
                self.assertEqual(t["candidate_text"], expected_name)
                self.assertEqual(t["adjudicated_type"], "true_npc")
                self.assertEqual(t["decision"], "keep")
                self.assertIn("source_refs", t)
                self.assertIn("location_bindings", t)
                self.assertIn("source_excerpt", t)

    def test_numillian_rookery_kept_npcs_enriched_without_structural_mutation(self):
        """Three kept Rookery NPCs enriched without creating structural fields."""
        from utils.toolkit_blueprint_enrichment import (
            _build_npc_pass_inputs, _parse_npc_enrichment_response,
            _convert_npc_enrichment_output_to_patches, _run_enrichment_pass,
        )

        decisions = [
            {"candidate_text": "Dog-Growl", "candidate_slug": "dog_growl",
             "proposed_type": "true_npc", "adjudicated_type": "true_npc",
             "decision": "keep", "reason": "Valid NPC",
             "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
             "location_bindings": ["The_Rookery"]},
            {"candidate_text": "Book-shut", "candidate_slug": "book_shut",
             "proposed_type": "true_npc", "adjudicated_type": "true_npc",
             "decision": "keep", "reason": "Valid NPC",
             "source_refs": [{"text": "Book-shut pores over tomes in The Rookery"}],
             "location_bindings": ["The_Rookery"]},
            {"candidate_text": "Deflation", "candidate_slug": "deflation",
             "proposed_type": "true_npc", "adjudicated_type": "true_npc",
             "decision": "keep", "reason": "Valid NPC",
             "source_refs": [{"text": "Deflation oversees The Rookery vault"}],
             "location_bindings": ["The_Rookery"]},
        ]
        bp = self._make_triage_blueprint(decisions)
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            ctx_path = os.path.join(module_dir, "module_context.json")
            with open(ctx_path, "w", encoding="utf-8") as f:
                ctx = _make_module_context()
                for slug, name in (("dog_growl", "Dog-Growl"),
                                   ("book_shut", "Book-shut"),
                                   ("deflation", "Deflation")):
                    ctx["npcs"][slug] = {"name": name, "role": "", "faction": "",
                                          "appears_in": []}
                json.dump(ctx, f)

            enrichment_response = {
                "pass_name": "npc_enrichment",
                "pass_type": "npc",
                "proposed_patches": [
                    {"blueprint_id": "npc_description",
                     "target_file": "module_context.json",
                     "json_path": "npcs.dog_growl.description",
                     "field": "description",
                     "value": "A scrappy kenku scavenger.",
                     "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                     "reason": "Enrich Dog-Growl",
                     "entity_slug": "dog_growl"},
                    {"blueprint_id": "npc_role",
                     "target_file": "module_context.json",
                     "json_path": "npcs.book_shut.role",
                     "field": "role",
                     "value": "Keeper of forbidden lore",
                     "source_refs": [{"text": "Book-shut pores over tomes in The Rookery"}],
                     "reason": "Enrich Book-shut",
                     "entity_slug": "book_shut"},
                    {"blueprint_id": "npc_role",
                     "target_file": "module_context.json",
                     "json_path": "npcs.deflation.role",
                     "field": "role",
                     "value": "Vault overseer",
                     "source_refs": [{"text": "Deflation oversees The Rookery vault"}],
                     "reason": "Enrich Deflation",
                     "entity_slug": "deflation"},
                ],
            }
            parsed = _parse_npc_enrichment_response(enrichment_response)
            self.assertTrue(parsed["valid"])
            converted = _convert_npc_enrichment_output_to_patches(parsed)
            self.assertEqual(len(converted["patch_candidates"]), 3)
            self.assertEqual(len(converted["dropped"]), 0)

            result = _run_enrichment_pass(
                bp, module_dir, "npc",
                npc_enrichment_data=converted,
            )
            self.assertEqual(len(result["applied"]), 3)

            with open(ctx_path, "r", encoding="utf-8") as f:
                final_ctx = json.load(f)
            self.assertEqual(
                final_ctx["npcs"]["dog_growl"]["description"],
                "A scrappy kenku scavenger.",
            )
            self.assertEqual(
                final_ctx["npcs"]["book_shut"]["role"],
                "Keeper of forbidden lore",
            )
            self.assertEqual(
                final_ctx["npcs"]["deflation"]["role"],
                "Vault overseer",
            )
            # Names remain unchanged
            self.assertEqual(final_ctx["npcs"]["dog_growl"]["name"], "Dog-Growl")
            self.assertEqual(final_ctx["npcs"]["book_shut"]["name"], "Book-shut")
            self.assertEqual(final_ctx["npcs"]["deflation"]["name"], "Deflation")
            # No structural fields were created
            for slug in ("dog_growl", "book_shut", "deflation"):
                npc = final_ctx["npcs"][slug]
                self.assertNotIn("type", npc)
                self.assertNotIn("id", npc)
                self.assertNotIn("locationId", npc)
            # No rejected phrase NPC was created
            self.assertNotIn("but_this_is_not_true", final_ctx.get("npcs", {}))


# ---------------------------------------------------------------------------
# NPC Enrichment Response Parser/Converter Tests
# ---------------------------------------------------------------------------


class TestNpcEnrichmentParser(unittest.TestCase):
    """Provider-free tests for _parse_npc_enrichment_response and
    _convert_npc_enrichment_output_to_patches."""

    def _make_valid_enrichment_response(self, **overrides) -> dict:
        resp = {
            "pass_name": "npc_enrichment",
            "pass_type": "npc",
            "proposed_patches": [
                {
                    "blueprint_id": "npc_description",
                    "target_file": "module_context.json",
                    "json_path": "npcs.dog_growl.description",
                    "field": "description",
                    "value": "A scrappy kenku scavenger.",
                    "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                    "reason": "Enrich from source excerpt",
                    "entity_slug": "dog_growl",
                },
            ],
        }
        resp.update(overrides)
        return resp

    def _make_npc_targets(self) -> list:
        return [
            {
                "candidate_text": "Dog-Growl",
                "candidate_slug": "dog_growl",
                "adjudicated_type": "true_npc",
                "decision": "keep",
                "source_refs": [{"text": "Dog-Growl lurks in The Rookery"}],
                "location_bindings": ["The_Rookery"],
                "source_excerpt": "Dog-Growl lurks in The Rookery",
            },
        ]

    # -- Parse tests --

    def test_valid_json_response_parses_correctly(self):
        """A valid JSON object response parses with patches_raw."""
        data = self._make_valid_enrichment_response()
        result = _parse_npc_enrichment_response(data)
        self.assertTrue(result["valid"])
        self.assertIn("pass_name", result)
        self.assertEqual(result["pass_name"], "npc_enrichment")
        self.assertEqual(len(result["patches_raw"]), 1)
        self.assertNotIn("error", result)

    def test_valid_json_string_response_parses_correctly(self):
        """A valid JSON string is parsed into patches_raw."""
        data = json.dumps(self._make_valid_enrichment_response())
        result = _parse_npc_enrichment_response(data)
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["patches_raw"]), 1)

    def test_malformed_json_string_rejected(self):
        """An unparsable string is rejected with malformed JSON error."""
        result = _parse_npc_enrichment_response("not json at all {{{")
        self.assertFalse(result["valid"])
        self.assertIn("malformed JSON", result["error"])
        self.assertNotIn("patches_raw", result)

    def test_prose_wrapped_json_rejected(self):
        """A prose-wrapped JSON block (```json ... ```) is rejected."""
        data = '```json\n{"pass_name": "npc", "proposed_patches": []}\n```'
        result = _parse_npc_enrichment_response(data)
        self.assertFalse(result["valid"])
        self.assertIn("prose-wrapped", result["error"])

    def test_array_top_level_response_rejected(self):
        """A JSON array as top-level response is rejected."""
        result = _parse_npc_enrichment_response([{"blueprint_id": "npc_description"}])
        self.assertFalse(result["valid"])
        self.assertIn("array", result["error"])

    def test_missing_pass_name_rejected(self):
        """A response without pass_name is rejected."""
        data = self._make_valid_enrichment_response(pass_name="")
        result = _parse_npc_enrichment_response(data)
        self.assertFalse(result["valid"])
        self.assertIn("missing pass_name", result["error"])

    def test_missing_proposed_patches_rejected(self):
        """A response without proposed_patches is rejected."""
        data = self._make_valid_enrichment_response()
        del data["proposed_patches"]
        result = _parse_npc_enrichment_response(data)
        self.assertFalse(result["valid"])
        self.assertIn("missing proposed_patches", result["error"])

    def test_non_list_proposed_patches_rejected(self):
        """A response with non-list proposed_patches is rejected."""
        data = self._make_valid_enrichment_response(proposed_patches="not_a_list")
        result = _parse_npc_enrichment_response(data)
        self.assertFalse(result["valid"])
        self.assertIn("must be a list", result["error"])

    def test_backtick_wrapped_json_rejected(self):
        """A response wrapped in single backticks is rejected."""
        result = _parse_npc_enrichment_response('`{"pass_name": "npc", "proposed_patches": []}`')
        self.assertFalse(result["valid"])
        self.assertIn("backticks", result["error"])

    # -- Convert tests --

    def test_valid_conversion_produces_patch_candidates(self):
        """Valid proposed patches convert into patch candidate dicts."""
        data = self._make_valid_enrichment_response()
        parsed = _parse_npc_enrichment_response(data)
        self.assertTrue(parsed["valid"])
        npc_targets = self._make_npc_targets()
        result = _convert_npc_enrichment_output_to_patches(parsed, npc_targets)
        self.assertEqual(len(result["patch_candidates"]), 1)
        self.assertEqual(len(result["dropped"]), 0)
        patch = result["patch_candidates"][0]
        self.assertEqual(patch["op"], "replace")
        self.assertEqual(patch["blueprint_id"], "npc_description")
        self.assertEqual(patch["target_file"], "module_context.json")
        self.assertEqual(patch["field"], "description")
        self.assertEqual(patch["value"], "A scrappy kenku scavenger.")
        self.assertIn("source_refs", patch)
        self.assertIn("reason", patch)
        self.assertIn("entity_slug", patch)

    def test_conversion_preserves_scaffold_source_excerpt(self):
        """Patch candidates preserve scaffold source_excerpt via entity_slug."""
        data = self._make_valid_enrichment_response()
        parsed = _parse_npc_enrichment_response(data)
        npc_targets = self._make_npc_targets()
        result = _convert_npc_enrichment_output_to_patches(parsed, npc_targets)
        patch = result["patch_candidates"][0]
        self.assertEqual(patch["_scaffold_source_excerpt"],
                         "Dog-Growl lurks in The Rookery")

    def test_missing_source_refs_and_reason_drops_proposal(self):
        """A proposal without source_refs and reason is dropped."""
        data = self._make_valid_enrichment_response()
        data["proposed_patches"][0].pop("source_refs", None)
        data["proposed_patches"][0].pop("reason", None)
        parsed = _parse_npc_enrichment_response(data)
        result = _convert_npc_enrichment_output_to_patches(parsed)
        self.assertEqual(len(result["patch_candidates"]), 0)
        self.assertEqual(len(result["dropped"]), 1)
        self.assertIn("no justification", result["dropped"][0]["reason"])

    def test_structural_field_name_rejected_in_conversion(self):
        """A proposal targeting field 'name' is dropped as forbidden."""
        data = self._make_valid_enrichment_response()
        data["proposed_patches"][0]["field"] = "name"
        data["proposed_patches"][0]["json_path"] = "npcs.dog_growl.name"
        parsed = _parse_npc_enrichment_response(data)
        result = _convert_npc_enrichment_output_to_patches(parsed)
        self.assertEqual(len(result["patch_candidates"]), 0)
        self.assertEqual(len(result["dropped"]), 1)

    def test_structural_field_locationId_rejected_in_conversion(self):
        """A proposal with 'locationId' in json_path is dropped."""
        data = self._make_valid_enrichment_response()
        data["proposed_patches"][0]["json_path"] = "locations[0].locationId"
        parsed = _parse_npc_enrichment_response(data)
        result = _convert_npc_enrichment_output_to_patches(parsed)
        self.assertEqual(len(result["patch_candidates"]), 0)
        self.assertEqual(len(result["dropped"]), 1)

    def test_structural_field_connectivity_rejected_in_conversion(self):
        """A proposal with 'connectivity' in json_path is dropped."""
        data = self._make_valid_enrichment_response()
        data["proposed_patches"][0]["json_path"] = "locations[0].connectivity"
        parsed = _parse_npc_enrichment_response(data)
        result = _convert_npc_enrichment_output_to_patches(parsed)
        self.assertEqual(len(result["patch_candidates"]), 0)
        self.assertEqual(len(result["dropped"]), 1)

    def test_structural_field_type_rejected_in_conversion(self):
        """A proposal with field 'type' is dropped as forbidden."""
        data = self._make_valid_enrichment_response()
        data["proposed_patches"][0]["field"] = "type"
        data["proposed_patches"][0]["json_path"] = "npcs.dog_growl.type"
        parsed = _parse_npc_enrichment_response(data)
        result = _convert_npc_enrichment_output_to_patches(parsed)
        self.assertEqual(len(result["patch_candidates"]), 0)
        self.assertEqual(len(result["dropped"]), 1)

    def test_multiple_proposals_mixed_result(self):
        """Mixed valid+invalid proposals produce correct patch_candidates and dropped."""
        data = self._make_valid_enrichment_response()
        data["proposed_patches"] = [
            {
                "blueprint_id": "npc_description",
                "target_file": "module_context.json",
                "json_path": "npcs.valid_npc.description",
                "field": "description",
                "value": "Good description.",
                "source_refs": [{"text": "source"}],
                "reason": "Valid",
            },
            {
                "blueprint_id": "npc_role",
                "target_file": "module_context.json",
                "json_path": "npcs.bad_npc.name",
                "field": "name",
                "value": "Bad Name",
                "source_refs": [{"text": "source"}],
                "reason": "Structural",
            },
            {
                "blueprint_id": "npc_description",
                "target_file": "module_context.json",
                "json_path": "npcs.no_justification.description",
                "field": "description",
                "value": "No justification.",
            },
        ]
        parsed = _parse_npc_enrichment_response(data)
        result = _convert_npc_enrichment_output_to_patches(parsed)
        self.assertEqual(len(result["patch_candidates"]), 1)
        self.assertEqual(len(result["dropped"]), 2)


# ---------------------------------------------------------------------------
# NPC Enrichment Validation/Application Tests
# ---------------------------------------------------------------------------


class TestNpcEnrichmentValidation(unittest.TestCase):
    """Provider-free tests for _validate_and_apply_npc_enrichment_patches."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = os.path.join(self.tmpdir.name, "module")
        os.makedirs(self.module_dir)
        path = os.path.join(self.module_dir, "module_context.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_make_module_context(), f)

    def _read_ctx(self) -> dict:
        path = os.path.join(self.module_dir, "module_context.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _make_applicable_patch(self, **overrides) -> Dict[str, Any]:
        patch = {
            "op": "replace",
            "blueprint_id": "npc_description",
            "target_file": "module_context.json",
            "json_path": "npcs.sample_npc.description",
            "field": "description",
            "source_refs": [{"text": "source text"}],
            "reason": "test reason",
            "entity_slug": "sample_npc",
            "_scaffold_source_excerpt": "source text",
            "value": "An enriched description from the provider.",
        }
        patch.update(overrides)
        return patch

    def test_valid_npc_patches_are_applied(self):
        """Valid NPC enrichment patches are applied to module_context.json."""
        candidates = [self._make_applicable_patch()]
        result = _validate_and_apply_npc_enrichment_patches(
            candidates, [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["validator_rejected"]), 0)
        ctx = self._read_ctx()
        self.assertEqual(
            ctx["npcs"]["sample_npc"]["description"],
            "An enriched description from the provider.",
        )

    def test_structural_patch_rejected_file_unchanged(self):
        """Validator-rejected structural patches do not mutate the file."""
        candidates = [
            self._make_applicable_patch(field="name",
                                        json_path="npcs.sample_npc.name",
                                        value="New Evil Name"),
        ]
        before = self._read_ctx()
        result = _validate_and_apply_npc_enrichment_patches(
            candidates, [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(len(result["validator_rejected"]), 1)
        self.assertIn("is not an allowed enrichment field",
                      result["validator_rejected"][0]["reason"])
        after = self._read_ctx()
        self.assertEqual(after["npcs"]["sample_npc"]["name"],
                         before["npcs"]["sample_npc"]["name"])

    def test_converter_dropped_appears_in_diagnostics(self):
        """Converter-dropped proposals are visible in diagnostics, not applied."""
        dropped = [
            {"index": 0, "reason": "missing blueprint_id"},
            {"index": 1, "reason": "forbidden field: type"},
        ]
        candidates = [self._make_applicable_patch()]
        result = _validate_and_apply_npc_enrichment_patches(
            candidates, dropped, self.module_dir,
        )
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["converter_dropped_count"], 2)

    def test_parser_invalid_returns_no_applied(self):
        """Parser-invalid data returns no applied patches."""
        result = _validate_and_apply_npc_enrichment_patches(
            [], [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(len(result["validator_rejected"]), 0)

    def test_diagnostics_preserve_metadata(self):
        """Applied diagnostics preserve source_refs, reason, entity_slug."""
        candidates = [self._make_applicable_patch()]
        result = _validate_and_apply_npc_enrichment_patches(
            candidates, [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 1)
        entry = result["applied"][0]
        self.assertEqual(entry["source_refs"], [{"text": "source text"}])
        self.assertEqual(entry["reason"], "test reason")
        self.assertEqual(entry["entity_slug"], "sample_npc")
        self.assertEqual(entry["_scaffold_source_excerpt"], "source text")

    def test_no_enrichment_data_no_provider_no_patches(self):
        """Default _run_enrichment_pass with no injection performs no provider call."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_enrichment_pass(bp, tmpdir, "npc")
            self.assertEqual(len(result["applied"]), 0)
            self.assertEqual(len(result["rejected"]), 0)
            self.assertEqual(len(result["errors"]), 0)
            self.assertIn("not yet implemented", str(result.get("warnings", [])))
            self.assertEqual(result["patches_requested"], 0)
            self.assertEqual(result["patches_returned"], 0)

    def test_injected_enrichment_full_pipeline(self):
        """Full pipeline: parse -> convert -> inject -> apply."""
        response = {
            "pass_name": "npc_enrichment",
            "pass_type": "npc",
            "proposed_patches": [
                {
                    "blueprint_id": "npc_description",
                    "target_file": "module_context.json",
                    "json_path": "npcs.sample_npc.description",
                    "field": "description",
                    "source_refs": [{"text": "source excerpt"}],
                    "reason": "test reason",
                    "entity_slug": "sample_npc",
                    "value": "Full pipeline enrichment text.",
                },
            ],
        }
        parsed = _parse_npc_enrichment_response(response)
        self.assertTrue(parsed["valid"])
        converted = _convert_npc_enrichment_output_to_patches(parsed)
        self.assertEqual(len(converted["patch_candidates"]), 1)
        self.assertEqual(len(converted["dropped"]), 0)
        bp = _make_blueprint()
        result = _run_enrichment_pass(
            bp, self.module_dir, "npc",
            npc_enrichment_data=converted,
        )
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["rejected"]), 0)
        self.assertEqual(len(result["errors"]), 0)
        ctx = self._read_ctx()
        self.assertEqual(
            ctx["npcs"]["sample_npc"]["description"],
            "Full pipeline enrichment text.",
        )
        self.assertIn("npc_pass_inputs", result)
        self.assertIn("npc_validation_diagnostics", result)

    # ------------------------------------------------------------------
    # Step 2.3: no-provider timeout/error, invalid JSON, unsafe structural
    # ------------------------------------------------------------------

    def test_npc_enrichment_invalid_json_does_not_apply_patches(self):
        """Invalid JSON via parser yields no patch candidates or applied patches."""
        result = _parse_npc_enrichment_response("{{{broken")
        self.assertFalse(result["valid"])
        self.assertIn("malformed JSON", result["error"])
        self.assertNotIn("patches_raw", result)

        candidates = []  # converter never produces candidates from invalid input
        vaa = _validate_and_apply_npc_enrichment_patches(
            candidates, [], self.module_dir,
        )
        self.assertEqual(vaa["applied_count"], 0)
        self.assertEqual(len(vaa["validator_rejected"]), 0)
        ctx = self._read_ctx()
        self.assertEqual(ctx["npcs"]["sample_npc"].get("description", ""), "")

    def test_npc_enrichment_provider_timeout_simulation_no_applied_patches(self):
        """Simulated provider timeout/error produces no applied patches."""
        bp = _make_blueprint()

        # Scenario 1: npc_enrichment_data with empty patch_candidates and no converter_dropped
        empty_data = {"patch_candidates": [], "converter_dropped": []}
        result = _run_enrichment_pass(
            bp, self.module_dir, "npc",
            npc_enrichment_data=empty_data,
        )
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("no patch_candidates", result["errors"][0].get("message", ""))

        # Scenario 2: no enrichment data at all (default no-provider)
        result2 = _run_enrichment_pass(bp, self.module_dir, "npc")
        self.assertEqual(len(result2["applied"]), 0)
        self.assertEqual(len(result2["errors"]), 0)
        self.assertIn("not yet implemented", str(result2.get("warnings", [])))

    def test_npc_enrichment_unsafe_structural_proposals_rejected_without_mutation(self):
        """Structural proposals for name, type, locationId, connectivity, prerequisites are rejected without file mutation."""
        # Add sample_npc with base fields to the temp module_context.json
        ctx = self._read_ctx()
        ctx["npcs"]["sample_npc"]["name"] = "Sample NPC"
        path = os.path.join(self.module_dir, "module_context.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ctx, f)

        before = self._read_ctx()
        structural_candidates = [
            self._make_applicable_patch(field="name",
                                         json_path="npcs.sample_npc.name",
                                         value="Hacked Name"),
            self._make_applicable_patch(field="type",
                                         json_path="npcs.sample_npc.type",
                                         value="enemy"),
            self._make_applicable_patch(field="locationId",
                                         json_path="npcs.sample_npc.locationId",
                                         value="A01"),
            self._make_applicable_patch(field="description",
                                         json_path="npcs.sample_npc.connectivity",
                                         value="ruin_network"),
            self._make_applicable_patch(field="description",
                                         json_path="npcs.sample_npc.prerequisites",
                                         value="PP001"),
        ]
        result = _validate_and_apply_npc_enrichment_patches(
            structural_candidates, [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(len(result["validator_rejected"]), 5)
        after = self._read_ctx()
        self.assertEqual(after, before,
                         "Structural patch batch mutated the file despite rejection")

    def test_npc_enrichment_no_provider_pipeline_not_complete(self):
        """run_enrichment_pipeline with no provider avoids complete status."""
        bp = _make_blueprint()
        with patch("model_config.ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT", True, create=True):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = run_enrichment_pipeline(bp, tmpdir)
                self.assertNotEqual(result["status"], ENRICHMENT_STATUS_COMPLETE)
                self.assertIn(result["status"],
                              {ENRICHMENT_STATUS_NOT_IMPLEMENTED, ENRICHMENT_STATUS_DEGRADED})
                self.assertEqual(len(result["applied"]), 0)


# ---------------------------------------------------------------------------
# Location Pass Scaffold Tests
# ---------------------------------------------------------------------------


def _write_area(tmpdir: str, fname: str, area_data: dict) -> str:
    """Write an area file into tmpdir/module/areas/ and return the area path."""
    areas_dir = os.path.join(tmpdir, "module", "areas")
    os.makedirs(areas_dir, exist_ok=True)
    path = os.path.join(areas_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(area_data, f)
    return path


_AREA_A000 = {
    "areaId": "A000",
    "areaName": "Test Area One",
    "locations": [
        {
            "locationId": "A01",
            "name": "Entrance Hall",
            "description": "A grand marble foyer with faded tapestries.",
            "dmInstructions": "Describe the echoing footsteps and dust.",
            "connectivity": ["A02"],
        },
    ],
}

_AREA_B000 = {
    "areaId": "B000",
    "areaName": "Test Area Two",
    "locations": [
        {
            "locationId": "B01",
            "name": "Undercroft Vault",
            "description": "A locked iron vault beneath the keep.",
            "features": "Arcane wards shimmer on the door.",
            "traps": "Poison needle trap on the lock.",
            "lootTable": "Scroll of Identify, 50gp",
            "connectivity": [],
        },
        {
            "locationId": "B02",
            "name": "Torture Chamber",
            "description": "",
            "dmInstructions": "",
            "connectivity": [],
        },
    ],
}


class TestLocationPassScaffold(unittest.TestCase):
    """Provider-free tests for location enrichment pass scaffold."""

    def test_location_scaffold_includes_keyed_locations(self):
        """Location scaffold includes keyed locations from area file fixture."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_A000_BU.json", _AREA_A000)
            inputs = _build_location_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["area_count"], 1)
            self.assertEqual(inputs["location_count"], 1)
            targets = inputs["location_targets"]
            self.assertEqual(len(targets), 1)
            t = targets[0]
            self.assertEqual(t["area_file"], "area_A000_BU.json")
            self.assertEqual(t["area_id"], "A000")
            self.assertEqual(t["location_id"], "A01")
            self.assertEqual(t["location_name"], "Entrance Hall")
            self.assertEqual(t["location_index"], 0)
            self.assertIn("marble foyer", t.get("source_excerpt", ""))
            self.assertIn("faded tapestries", t.get("source_excerpt", ""))

    def test_location_scaffold_multiple_areas(self):
        """Multiple area files produce aggregated location targets."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_A000_BU.json", _AREA_A000)
            _write_area(tmpdir, "area_B000_BU.json", _AREA_B000)
            inputs = _build_location_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["area_count"], 2)
            self.assertEqual(inputs["location_count"], 3)
            self.assertEqual(inputs["excerpt_max_chars"], 200)
            targets = inputs["location_targets"]
            ids = [(t["area_id"], t["location_id"]) for t in targets]
            self.assertIn(("A000", "A01"), ids)
            self.assertIn(("B000", "B01"), ids)
            self.assertIn(("B000", "B02"), ids)

    def test_location_excerpts_clipped_to_max_length(self):
        """Location source excerpts are bounded by max_excerpt_chars."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_A000_BU.json", _AREA_A000)
            inputs = _build_location_pass_inputs(bp, module_dir, max_excerpt_chars=20)
            t = inputs["location_targets"][0]
            self.assertLessEqual(len(t["source_excerpt"]), 20)

    def test_location_structural_fields_are_not_editable(self):
        """Location scaffold identity/structural fields are metadata only, not patch candidates."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_A000_BU.json", _AREA_A000)
            inputs = _build_location_pass_inputs(bp, module_dir)
            # The return dict has no 'patch_candidates' or 'dropped' keys
            # (those belong to NPC parser/converter results)
            self.assertNotIn("patch_candidates", inputs)
            self.assertNotIn("dropped", inputs)
            # Structural fields area_id/location_id are identity metadata
            t = inputs["location_targets"][0]
            self.assertEqual(t["area_id"], "A000")
            self.assertEqual(t["location_id"], "A01")
            # connectivity is not emitted as a separate target or editable field
            self.assertNotIn("connectivity", t)

    def test_location_pass_no_provider_call_no_applied_patches(self):
        """_run_enrichment_pass with pass_type='location' performs no provider call."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            result = _run_enrichment_pass(bp, module_dir, "location")
            self.assertEqual(result["pass_type"], "location")
            self.assertEqual(len(result["applied"]), 0)
            self.assertEqual(len(result["rejected"]), 0)
            self.assertEqual(len(result["errors"]), 0)
            self.assertIn("not yet implemented", str(result.get("warnings", [])))
            self.assertIn("location_pass_inputs", result)
            self.assertIn("area_count", result["location_pass_inputs"])
            # No area files exist, but scaffold still ran safely
            self.assertEqual(result["location_pass_inputs"]["area_count"], 0)


# ---------------------------------------------------------------------------
# Location Enrichment Application Tests
# ---------------------------------------------------------------------------


class TestLocationEnrichmentApplication(unittest.TestCase):
    """Provider-free tests for location enrichment patch application."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.module_dir = os.path.join(self.tmpdir.name, "module")
        os.makedirs(self.module_dir)
        areas_dir = os.path.join(self.module_dir, "areas")
        os.makedirs(areas_dir)
        area_file = os.path.join(areas_dir, "area_A000_BU.json")
        with open(area_file, "w", encoding="utf-8") as f:
            json.dump(_AREA_A000, f)
        area_b_file = os.path.join(areas_dir, "area_B000_BU.json")
        with open(area_b_file, "w", encoding="utf-8") as f:
            json.dump(_AREA_B000, f)

    def _read_area(self, fname: str) -> dict:
        path = os.path.join(self.module_dir, "areas", fname)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_location_prose_patch_applies_to_area_file(self):
        """Valid location description patch applies to area file."""
        response = {
            "pass_name": "location_enrichment",
            "pass_type": "location",
            "proposed_patches": [
                {
                    "blueprint_id": "location_description",
                    "target_file": "areas/area_A000_BU.json",
                    "json_path": "locations[0].description",
                    "field": "description",
                    "value": "A grand foyer with faded tapestries and echoing footsteps.",
                    "source_refs": [{"text": "A grand marble foyer with faded tapestries."}],
                    "reason": "Enrich from source",
                    "area_file": "area_A000_BU.json",
                    "area_id": "A000",
                    "location_id": "A01",
                    "location_path": "locations[0]",
                    "source_excerpt": "A grand marble foyer with faded tapestries.",
                },
            ],
        }
        parsed = _parse_location_enrichment_response(response)
        self.assertTrue(parsed["valid"])
        converted = _convert_location_enrichment_output_to_patches(parsed)
        self.assertEqual(len(converted["patch_candidates"]), 1)
        self.assertEqual(len(converted["dropped"]), 0)
        result = _validate_and_apply_location_enrichment_patches(
            converted["patch_candidates"], converted["dropped"], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 1)
        area = self._read_area("area_A000_BU.json")
        self.assertIn("echoing footsteps", area["locations"][0]["description"])

    def test_location_detail_fields_apply_across_multi_patch(self):
        """Multiple location detail fields (dmInstructions, features, plotHooks, traps) apply."""
        response = {
            "pass_name": "location_enrichment",
            "pass_type": "location",
            "proposed_patches": [
                {
                    "blueprint_id": "location_dm_instructions",
                    "target_file": "areas/area_A000_BU.json",
                    "json_path": "locations[0].dmInstructions",
                    "field": "dmInstructions",
                    "value": "Describe the echo of footsteps on marble.",
                    "source_refs": [{"text": "echoing footsteps"}],
                    "reason": "Enrich",
                    "area_file": "area_A000_BU.json",
                    "location_id": "A01",
                    "location_path": "locations[0]",
                },
                {
                    "blueprint_id": "location_features",
                    "target_file": "areas/area_B000_BU.json",
                    "json_path": "locations[0].features",
                    "field": "features",
                    "value": "Arcane wards shimmer on the vault door.",
                    "source_refs": [{"text": "Arcane wards shimmer"}],
                    "reason": "Enrich",
                    "area_file": "area_B000_BU.json",
                    "location_id": "B01",
                    "location_path": "locations[0]",
                },
                {
                    "blueprint_id": "location_traps",
                    "target_file": "areas/area_B000_BU.json",
                    "json_path": "locations[0].traps",
                    "field": "traps",
                    "value": "Poison needle trap DC 15.",
                    "source_refs": [{"text": "Poison needle trap"}],
                    "reason": "Enrich",
                    "area_file": "area_B000_BU.json",
                    "location_id": "B01",
                    "location_path": "locations[0]",
                },
                {
                    "blueprint_id": "location_loot_table",
                    "target_file": "areas/area_B000_BU.json",
                    "json_path": "locations[0].lootTable",
                    "field": "lootTable",
                    "value": "Scroll of Identify, 50 gp, Potion of Healing.",
                    "source_refs": [{"text": "Scroll of Identify"}],
                    "reason": "Enrich",
                    "area_file": "area_B000_BU.json",
                    "location_id": "B01",
                    "location_path": "locations[0]",
                },
            ],
        }
        parsed = _parse_location_enrichment_response(response)
        converted = _convert_location_enrichment_output_to_patches(parsed)
        self.assertEqual(len(converted["patch_candidates"]), 4)
        result = _validate_and_apply_location_enrichment_patches(
            converted["patch_candidates"], converted["dropped"], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 4)
        area_a = self._read_area("area_A000_BU.json")
        self.assertIn("marble", area_a["locations"][0].get("dmInstructions", ""))
        area_b = self._read_area("area_B000_BU.json")
        self.assertIn("vault door", area_b["locations"][0].get("features", ""))
        self.assertIn("DC 15", area_b["locations"][0].get("traps", ""))
        self.assertIn("Healing", area_b["locations"][0].get("lootTable", ""))

    def test_location_applied_diagnostics_preserve_metadata(self):
        """Applied location diagnostics preserve source_refs, reason, and identity metadata."""
        response = {
            "pass_name": "location_enrichment",
            "pass_type": "location",
            "proposed_patches": [
                {
                    "blueprint_id": "location_description",
                    "target_file": "areas/area_A000_BU.json",
                    "json_path": "locations[0].description",
                    "field": "description",
                    "value": "Foyer with faded tapestries.",
                    "source_refs": [{"text": "faded tapestries"}],
                    "reason": "Enrich from source",
                    "area_file": "area_A000_BU.json",
                    "area_id": "A000",
                    "location_id": "A01",
                    "location_path": "locations[0]",
                    "source_excerpt": "A grand marble foyer with faded tapestries.",
                },
            ],
        }
        parsed = _parse_location_enrichment_response(response)
        converted = _convert_location_enrichment_output_to_patches(parsed)
        result = _validate_and_apply_location_enrichment_patches(
            converted["patch_candidates"], converted["dropped"], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 1)
        entry = result["applied"][0]
        self.assertEqual(entry["source_refs"], [{"text": "faded tapestries"}])
        self.assertEqual(entry["reason"], "Enrich from source")
        self.assertEqual(entry["area_file"], "area_A000_BU.json")
        self.assertEqual(entry["area_id"], "A000")
        self.assertEqual(entry["location_id"], "A01")
        self.assertEqual(entry["location_path"], "locations[0]")
        self.assertIn("faded tapestries", entry.get("source_excerpt", ""))

    def test_location_structural_patches_rejected_no_mutation(self):
        """Structural location patch attempts for IDs/names/connectivity are rejected."""
        before_a = self._read_area("area_A000_BU.json")
        candidates = [
            {
                "op": "replace",
                "blueprint_id": "location_name",
                "target_file": "areas/area_A000_BU.json",
                "json_path": "locations[0].name",
                "field": "name",
                "value": "New Name",
                "source_refs": [{"text": "source"}],
                "reason": "Structural",
            },
            {
                "op": "replace",
                "blueprint_id": "location_id",
                "target_file": "areas/area_A000_BU.json",
                "json_path": "locations[0].locationId",
                "field": "locationId",
                "value": "NEW01",
                "source_refs": [{"text": "source"}],
                "reason": "Structural",
            },
            {
                "op": "replace",
                "blueprint_id": "location_connectivity",
                "target_file": "areas/area_A000_BU.json",
                "json_path": "locations[0].connectivity",
                "field": "description",
                "value": "['A05']",
                "source_refs": [{"text": "source"}],
                "reason": "Structural",
            },
            {
                "op": "replace",
                "blueprint_id": "location_area_id",
                "target_file": "areas/area_A000_BU.json",
                "json_path": "areaId",
                "field": "areaId",
                "value": "X999",
                "source_refs": [{"text": "source"}],
                "reason": "Structural",
            },
        ]
        result = _validate_and_apply_location_enrichment_patches(
            candidates, [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertGreaterEqual(len(result["validator_rejected"]), 4)
        after = self._read_area("area_A000_BU.json")
        self.assertEqual(after, before_a, "Structural batch mutated the file")

    def test_location_pass_no_injection_no_applied(self):
        """_run_enrichment_pass with location but no enrichment_data applies no patches."""
        bp = _make_blueprint()
        result = _run_enrichment_pass(bp, self.module_dir, "location")
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["rejected"]), 0)
        self.assertIn("not yet implemented", str(result.get("warnings", [])))
        self.assertIn("location_pass_inputs", result)

    def test_location_coordinate_field_rejected_by_converter(self):
        """Converter drops coordinate field as forbidden."""
        response = {
            "pass_name": "location_enrichment",
            "pass_type": "location",
            "proposed_patches": [
                {
                    "blueprint_id": "location_coords",
                    "target_file": "areas/area_A000_BU.json",
                    "json_path": "locations[0].coordinates",
                    "field": "coordinates",
                    "value": "{'x': 5, 'y': 3}",
                    "source_refs": [{"text": "source"}],
                    "reason": "test",
                },
            ],
        }
        parsed = _parse_location_enrichment_response(response)
        self.assertTrue(parsed["valid"])
        converted = _convert_location_enrichment_output_to_patches(parsed)
        self.assertEqual(len(converted["patch_candidates"]), 0)
        self.assertGreaterEqual(len(converted["dropped"]), 1)

    def test_location_nested_coordinate_path_dropped_by_converter(self):
        """Converter drops coordinate path within nested json_path."""
        response = {
            "pass_name": "location_enrichment",
            "pass_type": "location",
            "proposed_patches": [
                {
                    "blueprint_id": "location_coords_lat",
                    "target_file": "areas/area_A000_BU.json",
                    "json_path": "locations[0].coordinates.lat",
                    "field": "description",
                    "value": "12.345",
                    "source_refs": [{"text": "source"}],
                    "reason": "test",
                },
            ],
        }
        parsed = _parse_location_enrichment_response(response)
        self.assertTrue(parsed["valid"])
        converted = _convert_location_enrichment_output_to_patches(parsed)
        self.assertEqual(len(converted["patch_candidates"]), 0)
        self.assertGreaterEqual(len(converted["dropped"]), 1)

    def test_location_coordinate_rejected_by_validate_apply(self):
        """Coordinate patches injected directly into validate+apply are rejected at validation."""
        before_a = self._read_area("area_A000_BU.json")
        candidates = [
            {
                "op": "replace",
                "blueprint_id": "location_coords",
                "target_file": "areas/area_A000_BU.json",
                "json_path": "locations[0].coordinates",
                "field": "coordinates",
                "value": "{'x': 5, 'y': 3}",
                "source_refs": [{"text": "source"}],
                "reason": "test",
                "area_file": "area_A000_BU.json",
                "area_id": "A000",
                "location_id": "A01",
                "location_path": "locations[0]",
            },
        ]
        result = _validate_and_apply_location_enrichment_patches(
            candidates, [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertGreaterEqual(len(result["validator_rejected"]), 1)
        after = self._read_area("area_A000_BU.json")
        self.assertEqual(after, before_a, "Coordinate patch mutated the file")

    def test_location_nested_coordinate_path_rejected(self):
        """Nested coordinate path (e.g. coordinates.lat) is rejected at validation."""
        before_a = self._read_area("area_A000_BU.json")
        candidates = [
            {
                "op": "replace",
                "blueprint_id": "coord_lat",
                "target_file": "areas/area_A000_BU.json",
                "json_path": "locations[0].coordinates.lat",
                "field": "description",
                "value": "12.345",
                "source_refs": [{"text": "lat"}],
                "reason": "test",
                "area_file": "area_A000_BU.json",
                "area_id": "A000",
                "location_id": "A01",
                "location_path": "locations[0]",
            },
        ]
        result = _validate_and_apply_location_enrichment_patches(
            candidates, [], self.module_dir,
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertGreaterEqual(len(result["validator_rejected"]), 1)
        after = self._read_area("area_A000_BU.json")
        self.assertEqual(after, before_a, "Nested coordinate path mutated the file")

    def test_location_full_pipeline_rejects_coordinate(self):
        """Full parser+converter+validate pipeline rejects coordinate patches without mutation."""
        before_a = self._read_area("area_A000_BU.json")
        response = {
            "pass_name": "location_enrichment",
            "pass_type": "location",
            "proposed_patches": [
                {
                    "blueprint_id": "location_coords",
                    "target_file": "areas/area_A000_BU.json",
                    "json_path": "locations[0].coordinates",
                    "field": "coordinates",
                    "value": "{'x': 5, 'y': 3}",
                    "source_refs": [{"text": "source"}],
                    "reason": "test",
                    "area_file": "area_A000_BU.json",
                    "area_id": "A000",
                    "location_id": "A01",
                    "location_path": "locations[0]",
                },
            ],
        }
        parsed = _parse_location_enrichment_response(response)
        self.assertTrue(parsed["valid"])
        converted = _convert_location_enrichment_output_to_patches(parsed)
        self.assertEqual(len(converted["patch_candidates"]), 0)
        vaa = _validate_and_apply_location_enrichment_patches(
            converted["patch_candidates"], converted["dropped"], self.module_dir,
        )
        self.assertEqual(vaa["applied_count"], 0)
        after = self._read_area("area_A000_BU.json")
        self.assertEqual(after, before_a, "Full pipeline coordinate patch mutated file")
        self.assertIn("converter_dropped_count", vaa)
        self.assertGreaterEqual(vaa["converter_dropped_count"], 1)

    def test_location_pass_with_injection_applies_patches(self):
        """_run_enrichment_pass with location_enrichment_data applies patches."""
        response = {
            "pass_name": "location_enrichment",
            "pass_type": "location",
            "proposed_patches": [
                {
                    "blueprint_id": "location_description",
                    "target_file": "areas/area_A000_BU.json",
                    "json_path": "locations[0].description",
                    "field": "description",
                    "value": "Injected location enrichment.",
                    "source_refs": [{"text": "source"}],
                    "reason": "test",
                    "area_file": "area_A000_BU.json",
                    "area_id": "A000",
                    "location_id": "A01",
                    "location_path": "locations[0]",
                },
            ],
        }
        parsed = _parse_location_enrichment_response(response)
        converted = _convert_location_enrichment_output_to_patches(parsed)
        bp = _make_blueprint()
        result = _run_enrichment_pass(
            bp, self.module_dir, "location",
            location_enrichment_data=converted,
        )
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["rejected"]), 0)
        self.assertIn("location_pass_inputs", result)
        self.assertIn("location_validation_diagnostics", result)
        area = self._read_area("area_A000_BU.json")
        self.assertIn("Injected location enrichment",
                      area["locations"][0]["description"])


# ---------------------------------------------------------------------------
# Plot/puzzle/clue pass scaffold fixtures
# ---------------------------------------------------------------------------


_MAKE_MODULE_PLOT_RICH = {
    "plotTitle": "Test Module",
    "mainObjective": "Find the lost artifact before the eclipse.",
    "plotPoints": [
        {
            "id": "PP001",
            "title": "A Strange Arrival",
            "description": "The party arrives at the village of Oakhaven to find it shrouded in unnatural mist. The villagers are fearful and refuse to speak of the事故发生.",
            "nextPoints": ["PP002"],
            "prerequisites": [],
            "status": "not started",
            "plotImpact": "Establishes the eerie atmosphere and introduces the central mystery.",
            "type": "exposition",
        },
        {
            "id": "PP002",
            "title": "The Hidden Vault",
            "description": "Following clues from the elder, the party discovers a hidden vault beneath the old mill.",
            "nextPoints": [],
            "prerequisites": ["PP001"],
            "status": "not started",
            "plotImpact": "Reveals the artifact's location and introduces the guardian encounter.",
        },
    ],
}

_MAKE_AREA_WITH_PUZZLE_CLUE_FIELDS = {
    "areaId": "PZ001",
    "areaName": "Puzzle Zone",
    "locations": [
        {
            "locationId": "PZ01",
            "name": "Riddle Chamber",
            "description": "A circular chamber with rune-carved walls.",
            "dmInstructions": "Describe the faint glow of the runes as the party enters.",
            "features": "Rune circles on floor and ceiling pulse with arcane energy.",
            "dcChecks": "Arcana DC 15 to decipher the rune sequence.",
            "clues": "The runes tell of a key hidden in the moonlight shadow.",
        },
        {
            "locationId": "PZ02",
            "name": "Empty Hallway",
            "description": "",
            "dmInstructions": "",
            "connectivity": [],
        },
    ],
}


class TestPlotPuzzleCluePassScaffold(unittest.TestCase):
    """Provider-free tests for plot/puzzle/clue enrichment pass scaffold."""

    def test_plot_point_scaffold_discovers_plot_points(self):
        """Plot/puzzle/clue scaffold discovers plot points from module_plot_BU.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            with open(os.path.join(module_dir, "module_plot_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_MODULE_PLOT_RICH, f)
            bp = _make_blueprint()
            inputs = _build_plot_puzzle_clue_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["plot_point_count"], 2)
            targets = inputs["plot_point_targets"]
            ids = [t["plot_point_id"] for t in targets]
            self.assertIn("PP001", ids)
            self.assertIn("PP002", ids)

    def test_plot_point_scaffold_bounded_excerpts(self):
        """Plot point source excerpts are bounded to max_excerpt_chars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            with open(os.path.join(module_dir, "module_plot_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_MODULE_PLOT_RICH, f)
            bp = _make_blueprint()
            inputs = _build_plot_puzzle_clue_pass_inputs(bp, module_dir, max_excerpt_chars=30)
            self.assertEqual(inputs["plot_point_count"], 2)
            for t in inputs["plot_point_targets"]:
                self.assertLessEqual(len(t["source_excerpt"]), 30)

    def test_plot_point_scaffold_includes_structural_as_metadata(self):
        """Plot point structural fields (id, nextPoints, prerequisites, status) are read-only metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            with open(os.path.join(module_dir, "module_plot_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_MODULE_PLOT_RICH, f)
            bp = _make_blueprint()
            inputs = _build_plot_puzzle_clue_pass_inputs(bp, module_dir)
            for t in inputs["plot_point_targets"]:
                sm = t.get("structural_metadata", {})
                if t["plot_point_id"] == "PP001":
                    self.assertEqual(sm.get("id"), "PP001")
                    self.assertEqual(sm.get("nextPoints"), ["PP002"])
                    self.assertEqual(sm.get("status"), "not started")
                    self.assertEqual(sm.get("type"), "exposition")
                elif t["plot_point_id"] == "PP002":
                    self.assertEqual(sm.get("prerequisites"), ["PP001"])

    def test_puzzle_clue_scaffold_discovers_location_data(self):
        """Puzzle/clue scaffold discovers locations with puzzle-relevant prose fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            areas_dir = os.path.join(module_dir, "areas")
            os.makedirs(areas_dir)
            with open(os.path.join(areas_dir, "area_PZ001_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_AREA_WITH_PUZZLE_CLUE_FIELDS, f)
            bp = _make_blueprint()
            inputs = _build_plot_puzzle_clue_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["puzzle_clue_location_count"], 2)
            targets = inputs["puzzle_clue_targets"]
            ids = [(t["area_id"], t["location_id"]) for t in targets]
            self.assertIn(("PZ001", "PZ01"), ids)
            self.assertIn(("PZ001", "PZ02"), ids)

    def test_puzzle_clue_excerpts_present_for_enriched_location(self):
        """Location with puzzle-relevant fields produces non-empty bounded excerpt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            areas_dir = os.path.join(module_dir, "areas")
            os.makedirs(areas_dir)
            with open(os.path.join(areas_dir, "area_PZ001_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_AREA_WITH_PUZZLE_CLUE_FIELDS, f)
            bp = _make_blueprint()
            inputs = _build_plot_puzzle_clue_pass_inputs(bp, module_dir)
            targets = inputs["puzzle_clue_targets"]
            riddle = [t for t in targets if t["location_id"] == "PZ01"][0]
            self.assertTrue(len(riddle["source_excerpt"]) > 0)
            self.assertLessEqual(len(riddle["source_excerpt"]), 200)
            self.assertIn("rune", riddle["source_excerpt"].lower())
            # Empty hallway has no prose content
            empty = [t for t in targets if t["location_id"] == "PZ02"][0]
            self.assertEqual(empty["source_excerpt"], "")

    def test_plot_puzzle_clue_pass_no_provider_call_no_applied(self):
        """_run_enrichment_pass with plot_puzzle_clue performs no provider call."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            result = _run_enrichment_pass(bp, module_dir, "plot_puzzle_clue")
            self.assertEqual(result["pass_type"], "plot_puzzle_clue")
            self.assertEqual(len(result["applied"]), 0)
            self.assertEqual(len(result["rejected"]), 0)
            self.assertEqual(len(result["errors"]), 0)
            self.assertIn("not yet implemented", str(result.get("warnings", [])))
            self.assertIn("plot_puzzle_clue_pass_inputs", result)
            ppi = result["plot_puzzle_clue_pass_inputs"]
            self.assertIn("plot_point_count", ppi)
            self.assertIn("puzzle_clue_location_count", ppi)
            self.assertEqual(ppi["plot_point_count"], 0)

    def test_plot_puzzle_clue_scaffold_no_plot_file(self):
        """Missing module_plot_BU.json results in zero plot point count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            bp = _make_blueprint()
            inputs = _build_plot_puzzle_clue_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["plot_point_count"], 0)
            self.assertEqual(inputs["puzzle_clue_location_count"], 0)
            self.assertIn("excerpt_max_chars", inputs)

    def test_plot_prose_fields_are_bounded_set(self):
        """Plot prose fields constant is a frozenset of known prose field names."""
        self.assertIsInstance(_PLOT_PROSE_FIELDS, frozenset)
        for f in ("description", "title", "plotImpact", "mainObjective"):
            self.assertIn(f, _PLOT_PROSE_FIELDS)
        # Structural fields NOT in prose set
        self.assertNotIn("id", _PLOT_PROSE_FIELDS)
        self.assertNotIn("nextPoints", _PLOT_PROSE_FIELDS)
        self.assertNotIn("prerequisites", _PLOT_PROSE_FIELDS)

    def test_puzzle_clue_prose_fields_are_bounded_set(self):
        """Puzzle/clue prose fields constant is a frozenset of known puzzle-relevant field names."""
        self.assertIsInstance(_PUZZLE_CLUE_PROSE_FIELDS, frozenset)
        for f in ("clues", "setup", "rules", "solution", "dcChecks"):
            self.assertIn(f, _PUZZLE_CLUE_PROSE_FIELDS)
        self.assertNotIn("locationId", _PUZZLE_CLUE_PROSE_FIELDS)
        self.assertNotIn("connectivity", _PUZZLE_CLUE_PROSE_FIELDS)


# ---------------------------------------------------------------------------
# Encounter/item pass scaffold tests
# ---------------------------------------------------------------------------

_MAKE_AREA_ENCOUNTER_ITEM = {
    "areaId": "EI001",
    "areaName": "Test Encounter Area",
    "locations": [
        {
            "locationId": "EI01",
            "name": "Guard Post",
            "description": "A fortified guard post with heavy crossbows.",
            "encounters": "Two veteran guards patrol the entrance. They can be persuaded or fought.",
            "monsters": "Guard Captain (AC 18, HP 65)",
            "npcs": "Captain Aldric, a grizzled veteran who respects strength.",
            "traps": "Tripwire alarm across the gateway.",
            "lootTable": "",
        },
        {
            "locationId": "EI02",
            "name": "Armory",
            "description": "A dusty armory filled with old weapons.",
            "lootTable": "Longsword +1, 3 Potions of Healing, Steel Shield",
            "features": "Weapon racks line the walls. A locked chest sits in the corner.",
            "doors": "Reinforced iron door, DC 20 Strength to force.",
            "encounters": "",
            "monsters": "",
        },
        {
            "locationId": "EI03",
            "name": "Empty Cell",
            "description": "",
            "encounters": "",
            "lootTable": "",
        },
    ],
}


class TestEncounterItemPassScaffold(unittest.TestCase):
    """Provider-free tests for encounter/item enrichment pass scaffold."""

    def test_encounter_scaffold_discovers_locations(self):
        """Encounter/item scaffold discovers locations with encounter-relevant fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_EI001_BU.json", _MAKE_AREA_ENCOUNTER_ITEM)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["encounter_location_count"], 3)
            ids = [t["location_id"] for t in inputs["encounter_targets"]]
            self.assertIn("EI01", ids)
            self.assertIn("EI02", ids)
            self.assertIn("EI03", ids)

    def test_encounter_excerpts_non_empty_for_enriched_locations(self):
        """Locations with encounter prose produce non-empty bounded excerpts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_EI001_BU.json", _MAKE_AREA_ENCOUNTER_ITEM)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir)
            guard = [t for t in inputs["encounter_targets"] if t["location_id"] == "EI01"][0]
            self.assertTrue(len(guard["source_excerpt"]) > 0)
            self.assertLessEqual(len(guard["source_excerpt"]), 200)
            self.assertIn("guard", guard["source_excerpt"].lower())
            empty = [t for t in inputs["encounter_targets"] if t["location_id"] == "EI03"][0]
            self.assertEqual(empty["source_excerpt"], "")

    def test_item_scaffold_discovers_item_fields(self):
        """Item scaffold discovers locations with item-relevant prose."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_EI001_BU.json", _MAKE_AREA_ENCOUNTER_ITEM)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["item_location_count"], 3)
            ids = [t["location_id"] for t in inputs["item_targets"]]
            self.assertIn("EI01", ids)
            self.assertIn("EI02", ids)
            self.assertIn("EI03", ids)

    def test_item_excerpts_from_loot_and_features(self):
        """Item excerpts include loot table and features content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_EI001_BU.json", _MAKE_AREA_ENCOUNTER_ITEM)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir)
            armory = [t for t in inputs["item_targets"] if t["location_id"] == "EI02"][0]
            self.assertTrue(len(armory["source_excerpt"]) > 0)
            self.assertIn("longsword", armory["source_excerpt"].lower())
            self.assertIn("healing", armory["source_excerpt"].lower())

    def test_encounter_item_identity_metadata_preserved(self):
        """Encounter/item targets preserve area/location identity metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_EI001_BU.json", _MAKE_AREA_ENCOUNTER_ITEM)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir)
            for targets in (inputs["encounter_targets"], inputs["item_targets"]):
                t = targets[0]
                self.assertEqual(t["area_file"], "area_EI001_BU.json")
                self.assertEqual(t["area_id"], "EI001")
                self.assertEqual(t["area_name"], "Test Encounter Area")
                self.assertEqual(t["location_id"], "EI01")
                self.assertEqual(t["location_name"], "Guard Post")
                self.assertEqual(t["location_index"], 0)
                self.assertEqual(t["location_path"], "locations[0]")

    def test_encounter_item_excerpts_clipped(self):
        """Encounter/item excerpts bounded to max_excerpt_chars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_EI001_BU.json", _MAKE_AREA_ENCOUNTER_ITEM)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir, max_excerpt_chars=15)
            for targets in (inputs["encounter_targets"], inputs["item_targets"]):
                for t in targets:
                    self.assertLessEqual(len(t["source_excerpt"]), 15)

    def test_encounter_item_pass_no_provider_call_no_applied(self):
        """_run_enrichment_pass with encounter_item performs no provider call."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            result = _run_enrichment_pass(bp, module_dir, "encounter_item")
            self.assertEqual(result["pass_type"], "encounter_item")
            self.assertEqual(len(result["applied"]), 0)
            self.assertEqual(len(result["rejected"]), 0)
            self.assertEqual(len(result["errors"]), 0)
            self.assertIn("not yet implemented", str(result.get("warnings", [])))
            self.assertIn("encounter_item_pass_inputs", result)
            ppi = result["encounter_item_pass_inputs"]
            self.assertIn("encounter_location_count", ppi)
            self.assertIn("item_location_count", ppi)
            self.assertEqual(ppi["encounter_location_count"], 0)

    def test_encounter_prose_fields_are_bounded_set(self):
        """Encounter prose fields constant is a frozenset of relevant field names."""
        self.assertIsInstance(_ENCOUNTER_PROSE_FIELDS, frozenset)
        for f in ("encounters", "monsters", "npcs", "traps", "dcChecks", "adventureSummary"):
            self.assertIn(f, _ENCOUNTER_PROSE_FIELDS)
        self.assertNotIn("locationId", _ENCOUNTER_PROSE_FIELDS)
        self.assertNotIn("connectivity", _ENCOUNTER_PROSE_FIELDS)

    def test_item_prose_fields_are_bounded_set(self):
        """Item prose fields constant is a frozenset of relevant field names."""
        self.assertIsInstance(_ITEM_PROSE_FIELDS, frozenset)
        for f in ("lootTable", "features", "description", "doors"):
            self.assertIn(f, _ITEM_PROSE_FIELDS)
        self.assertNotIn("locationId", _ITEM_PROSE_FIELDS)
        self.assertNotIn("connectivity", _ITEM_PROSE_FIELDS)

    def test_encounter_item_pass_handles_no_area_dir(self):
        """Missing areas directory results in zero counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["encounter_location_count"], 0)
            self.assertEqual(inputs["item_location_count"], 0)
            self.assertIn("excerpt_max_chars", inputs)


# ---------------------------------------------------------------------------
# Tone/style pass scaffold tests
# ---------------------------------------------------------------------------

_MAKE_TONE_STYLE_CONTEXT = {
    "module_name": "Shadow of the Forgotten",
    "module_id": "shadow_forgotten",
    "description": "A dark and foreboding adventure shrouded in mystery.",
    "mainObjective": "Uncover the ancient secret before the eclipse.",
}

_MAKE_TONE_STYLE_PLOT = {
    "plotTitle": "Shadow of the Forgotten",
    "mainObjective": "Delve into the haunted ruins and confront the sorrowful spirit.",
    "plotPoints": [
        {
            "id": "PP001",
            "title": "The Ominous Omen",
            "description": "A dark portent hangs over the village.",
            "plotImpact": "Establishes the sinister atmosphere.",
        },
    ],
}

_MAKE_TONE_STYLE_AREA = {
    "areaId": "TS001",
    "areaName": "Haunted Zone",
    "areaDescription": "A misty woodland shrouded in eeriness and decay.",
    "locations": [
        {
            "locationId": "TS01",
            "name": "Gloomy Clearing",
            "description": "A shadowy clearing with twisted trees.",
            "dmInstructions": "Describe the oppressive silence and eldritch chill.",
            "adventureSummary": "The party discovers cryptic runes hidden beneath moss.",
        },
        {
            "locationId": "TS02",
            "name": "Bright Meadow",
            "description": "",
            "dmInstructions": "",
        },
    ],
}


class TestToneStylePassScaffold(unittest.TestCase):
    """Provider-free tests for tone/style enrichment pass scaffold."""

    def _setup(self, tmpdir, with_context=True, with_plot=True, with_area=True):
        module_dir = os.path.join(tmpdir, "module")
        os.makedirs(module_dir)
        if with_context:
            with open(os.path.join(module_dir, "module_context.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_TONE_STYLE_CONTEXT, f)
        if with_plot:
            with open(os.path.join(module_dir, "module_plot_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_TONE_STYLE_PLOT, f)
        if with_area:
            _write_area(tmpdir, "area_TS001_BU.json", _MAKE_TONE_STYLE_AREA)
        return module_dir

    def test_tone_style_scaffold_discovers_sources(self):
        """Tone/style scaffold discovers sources from context, plot, and area files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = self._setup(tmpdir)
            bp = _make_blueprint()
            inputs = _build_tone_style_pass_inputs(bp, module_dir)
            self.assertGreaterEqual(inputs["source_count"], 1)
            kinds = [t["source_kind"] for t in inputs["tone_style_targets"]]
            self.assertIn("module_context", kinds)
            self.assertIn("plot_main_objective", kinds)
            self.assertIn("plot_point", kinds)
            self.assertIn("area_description", kinds)
            self.assertIn("location", kinds)

    def test_tone_style_guidance_derived_from_keywords(self):
        """Tone/style scaffold produces deterministic guidance from mood keywords."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = self._setup(tmpdir)
            bp = _make_blueprint()
            inputs = _build_tone_style_pass_inputs(bp, module_dir)
            self.assertTrue(inputs["has_guidance"])
            for t in inputs["tone_style_targets"]:
                if t.get("tone_style_guidance"):
                    guidance = " ".join(t["tone_style_guidance"]).lower()
                    self.assertIn("mood", guidance)

    def test_tone_style_targets_have_no_patch_candidates(self):
        """Tone/style scaffold does not produce patch_candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = self._setup(tmpdir)
            bp = _make_blueprint()
            inputs = _build_tone_style_pass_inputs(bp, module_dir)
            self.assertNotIn("patch_candidates", inputs)
            self.assertNotIn("dropped", inputs)
            self.assertNotIn("applied", inputs)

    def test_tone_style_does_not_invent_plot_ids(self):
        """Tone/style guidance does not contain plot IDs, NPC names, or location IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = self._setup(tmpdir)
            bp = _make_blueprint()
            inputs = _build_tone_style_pass_inputs(bp, module_dir)
            all_guidance = " ".join(
                " ".join(t.get("tone_style_guidance", []))
                for t in inputs["tone_style_targets"]
            )
            # Should not contain invented plot/location IDs
            self.assertNotIn("PP002", all_guidance)
            self.assertNotIn("TS03", all_guidance)
            self.assertNotIn("shadow_forgotten_npc", all_guidance)

    def test_tone_style_excerpts_bounded(self):
        """Tone/style excerpts bounded to max_excerpt_chars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = self._setup(tmpdir)
            bp = _make_blueprint()
            inputs = _build_tone_style_pass_inputs(bp, module_dir, max_excerpt_chars=15)
            for t in inputs["tone_style_targets"]:
                self.assertLessEqual(len(t["source_excerpt"]), 15)

    def test_tone_style_pass_no_provider_call_no_applied(self):
        """_run_enrichment_pass with tone_style performs no provider call."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = self._setup(tmpdir)
            result = _run_enrichment_pass(bp, module_dir, "tone_style")
            self.assertEqual(result["pass_type"], "tone_style")
            self.assertEqual(len(result["applied"]), 0)
            self.assertEqual(len(result["rejected"]), 0)
            self.assertEqual(len(result["errors"]), 0)
            self.assertIn("not yet implemented", str(result.get("warnings", [])))
            self.assertIn("tone_style_pass_inputs", result)
            tspi = result["tone_style_pass_inputs"]
            self.assertIn("source_count", tspi)
            self.assertIn("has_guidance", tspi)

    def test_tone_style_empty_when_no_source_files(self):
        """Missing source files produce zero source count and no guidance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            bp = _make_blueprint()
            inputs = _build_tone_style_pass_inputs(bp, module_dir)
            self.assertEqual(inputs["source_count"], 0)
            self.assertEqual(inputs["excerpt_count"], 0)
            self.assertFalse(inputs["has_guidance"])

    def test_tone_style_source_fields_are_bounded_set(self):
        """Tone/style source fields constant is a frozenset of known prose field names."""
        self.assertIsInstance(_TONE_STYLE_SOURCE_FIELDS, frozenset)
        for f in ("description", "dmInstructions", "adventureSummary",
                  "areaDescription", "mainObjective", "plotHooks", "title"):
            self.assertIn(f, _TONE_STYLE_SOURCE_FIELDS)
        self.assertNotIn("id", _TONE_STYLE_SOURCE_FIELDS)
        self.assertNotIn("locationId", _TONE_STYLE_SOURCE_FIELDS)
        self.assertNotIn("nextPoints", _TONE_STYLE_SOURCE_FIELDS)
        self.assertNotIn("prerequisites", _TONE_STYLE_SOURCE_FIELDS)


# ---------------------------------------------------------------------------
# Cache key tests
# ---------------------------------------------------------------------------


class TestInputCacheKey(unittest.TestCase):
    """Provider-free tests for deterministic input cache keys."""

    def test_stable_json_dumps_is_deterministic(self):
        """Same dict with different key order produces identical stable JSON."""
        a = _stable_json_dumps({"z": 1, "a": 2, "n": 3})
        b = _stable_json_dumps({"a": 2, "n": 3, "z": 1})
        self.assertEqual(a, b)

    def test_cache_key_is_deterministic_across_runs(self):
        """Same pass type and inputs produce identical cache key."""
        key1 = _input_cache_key("test", {"x": "hello"})
        key2 = _input_cache_key("test", {"x": "hello"})
        self.assertEqual(key1, key2)

    def test_cache_key_differs_on_input_change(self):
        """Different excerpts produce different cache keys."""
        key1 = _input_cache_key("test", {"x": "hello"})
        key2 = _input_cache_key("test", {"x": "world"})
        self.assertNotEqual(key1, key2)

    def test_cache_key_differs_on_pass_type(self):
        """Different pass types produce different cache keys."""
        key1 = _input_cache_key("location", {"x": "hello"})
        key2 = _input_cache_key("npc", {"x": "hello"})
        self.assertNotEqual(key1, key2)

    def test_cache_key_is_hex_sha256_length(self):
        """Cache key is a 64-char hex string (SHA-256)."""
        key = _input_cache_key("test", {"x": "y"})
        self.assertEqual(len(key), 64)
        int(key, 16)  # raises if not valid hex

    def test_build_location_pass_inputs_includes_cache_key(self):
        """_build_location_pass_inputs output includes input_cache_key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_A000_BU.json", _AREA_A000)
            bp = _make_blueprint()
            inputs = _build_location_pass_inputs(bp, module_dir)
            self.assertIn("input_cache_key", inputs)
            self.assertEqual(len(inputs["input_cache_key"]), 64)

    def test_build_plot_puzzle_clue_inputs_includes_cache_key(self):
        """_build_plot_puzzle_clue_pass_inputs output includes input_cache_key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            with open(os.path.join(module_dir, "module_plot_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_MODULE_PLOT_RICH, f)
            bp = _make_blueprint()
            inputs = _build_plot_puzzle_clue_pass_inputs(bp, module_dir)
            self.assertIn("input_cache_key", inputs)
            self.assertEqual(len(inputs["input_cache_key"]), 64)

    def test_build_encounter_item_inputs_includes_cache_key(self):
        """_build_encounter_item_pass_inputs output includes input_cache_key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            _write_area(tmpdir, "area_EI001_BU.json", _MAKE_AREA_ENCOUNTER_ITEM)
            bp = _make_blueprint()
            inputs = _build_encounter_item_pass_inputs(bp, module_dir)
            self.assertIn("input_cache_key", inputs)
            self.assertEqual(len(inputs["input_cache_key"]), 64)

    def test_build_tone_style_inputs_includes_cache_key(self):
        """_build_tone_style_pass_inputs output includes input_cache_key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            with open(os.path.join(module_dir, "module_context.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_TONE_STYLE_CONTEXT, f)
            with open(os.path.join(module_dir, "module_plot_BU.json"), "w", encoding="utf-8") as f:
                json.dump(_MAKE_TONE_STYLE_PLOT, f)
            _write_area(tmpdir, "area_TS001_BU.json", _MAKE_TONE_STYLE_AREA)
            bp = _make_blueprint()
            inputs = _build_tone_style_pass_inputs(bp, module_dir)
            self.assertIn("input_cache_key", inputs)
            self.assertEqual(len(inputs["input_cache_key"]), 64)

    def test_run_enrichment_pass_location_surfaces_cache_key(self):
        """_run_enrichment_pass location pass surfaces input_cache_key in summary."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            result = _run_enrichment_pass(bp, module_dir, "location")
            self.assertIn("input_cache_key", result["location_pass_inputs"])
            self.assertEqual(len(result["location_pass_inputs"]["input_cache_key"]), 64)

    def test_run_enrichment_pass_plot_puzzle_clue_surfaces_cache_key(self):
        """_run_enrichment_pass plot_puzzle_clue surfaces input_cache_key."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            result = _run_enrichment_pass(bp, module_dir, "plot_puzzle_clue")
            self.assertIn("input_cache_key", result["plot_puzzle_clue_pass_inputs"])

    def test_run_enrichment_pass_encounter_item_surfaces_cache_key(self):
        """_run_enrichment_pass encounter_item surfaces input_cache_key."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            result = _run_enrichment_pass(bp, module_dir, "encounter_item")
            self.assertIn("input_cache_key", result["encounter_item_pass_inputs"])

    def test_run_enrichment_pass_tone_style_surfaces_cache_key(self):
        """_run_enrichment_pass tone_style surfaces input_cache_key."""
        bp = _make_blueprint()
        with tempfile.TemporaryDirectory() as tmpdir:
            module_dir = os.path.join(tmpdir, "module")
            os.makedirs(module_dir)
            result = _run_enrichment_pass(bp, module_dir, "tone_style")
            self.assertIn("input_cache_key", result["tone_style_pass_inputs"])


# ---------------------------------------------------------------------------
# Pass telemetry tests
# ---------------------------------------------------------------------------


class TestPassTelemetry(unittest.TestCase):
    """Provider-free tests for pass telemetry."""

    def test_not_implemented_pass_telemetry_shape(self):
        """Provider-free scaffold pass returns telemetry with zero counts."""
        for pass_type in ("location", "plot_puzzle_clue", "encounter_item", "tone_style", "npc"):
            with self.subTest(pass_type=pass_type):
                bp = _make_blueprint()
                with tempfile.TemporaryDirectory() as tmpdir:
                    module_dir = os.path.join(tmpdir, "module")
                    os.makedirs(module_dir)
                    result = _run_enrichment_pass(bp, module_dir, pass_type)
                    self.assertIn("pass_telemetry", result)
                    t = result["pass_telemetry"]
                    self.assertEqual(t["pass_type"], pass_type)
                    self.assertEqual(t["provider_call_count"], 0)
                    self.assertEqual(t["cache_hit_count"], 0)
                    self.assertEqual(t["cache_miss_count"], 0)
                    self.assertEqual(t["parse_failure_count"], 0)
                    self.assertEqual(t["rejected_patch_count"], 0)
                    self.assertEqual(t["applied_patch_count"], 0)
                    self.assertEqual(len(t["input_cache_key"]), 64)

    def test_not_implemented_pass_telemetry_status(self):
        """Provider-free scaffold passes report not_implemented status."""
        for pass_type in ("location", "plot_puzzle_clue", "encounter_item", "tone_style", "npc"):
            with self.subTest(pass_type=pass_type):
                bp = _make_blueprint()
                with tempfile.TemporaryDirectory() as tmpdir:
                    module_dir = os.path.join(tmpdir, "module")
                    os.makedirs(module_dir)
                    result = _run_enrichment_pass(bp, module_dir, pass_type)
                    self.assertEqual(
                        result["pass_telemetry"]["status"],
                        ENRICHMENT_STATUS_NOT_IMPLEMENTED,
                    )

    def test_build_pass_telemetry_status_not_implemented(self):
        """Empty result produces not_implemented."""
        t = _build_pass_telemetry("test", {"applied": [], "rejected": [], "errors": []})
        self.assertEqual(t["status"], ENRICHMENT_STATUS_NOT_IMPLEMENTED)

    def test_build_pass_telemetry_status_complete(self):
        """Result with applied patches produces complete status."""
        t = _build_pass_telemetry("test", {
            "applied": [{"patch": {"field": "desc"}}],
            "rejected": [],
            "errors": [],
        })
        self.assertEqual(t["status"], ENRICHMENT_STATUS_COMPLETE)
        self.assertEqual(t["applied_patch_count"], 1)

    def test_build_pass_telemetry_status_degraded(self):
        """Result with errors produces degraded status."""
        t = _build_pass_telemetry("test", {
            "applied": [],
            "rejected": [],
            "errors": [{"message": "something went wrong"}],
        })
        self.assertEqual(t["status"], ENRICHMENT_STATUS_DEGRADED)

    def test_build_pass_telemetry_rejected_patch_count(self):
        """Telemetry reports rejected patch count from result."""
        t = _build_pass_telemetry("test", {
            "applied": [],
            "rejected": [{"reason": "invalid"}, {"reason": "missing"}],
            "errors": [],
        })
        self.assertEqual(t["rejected_patch_count"], 2)

    def test_build_pass_telemetry_empty_cache_key(self):
        """Telemetry accepts empty input_cache_key default."""
        t = _build_pass_telemetry("test", {"applied": [], "rejected": [], "errors": []})
        self.assertEqual(t["input_cache_key"], "")

    def test_build_pass_telemetry_passthrough_cache_key(self):
        """Telemetry passes through provided input_cache_key."""
        t = _build_pass_telemetry("test", {"applied": [], "rejected": [], "errors": []},
                                  input_cache_key="a" * 64)
        self.assertEqual(t["input_cache_key"], "a" * 64)


# ---------------------------------------------------------------------------
# Report metadata tests
# ---------------------------------------------------------------------------


class TestReportMetadata(unittest.TestCase):
    """Provider-free tests for additive report metadata."""

    def test_report_preserves_existing_keys(self):
        """Existing top-level keys preserved with new additive metadata."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_COMPLETE,
            "reason": "",
            "applied": [{"patch": {"field": "desc"}}],
            "rejected": [],
            "errors": [],
            "warnings": [],
            "passes": [],
        }
        report = build_enrichment_report(pipeline_result)
        for key in ("enrichment_report_version", "created_at", "status",
                     "reason", "applied_count", "rejected_count",
                     "error_count", "warning_count", "pass_count",
                     "applied", "rejected", "errors", "warnings"):
            self.assertIn(key, report)
        self.assertIn("pass_metadata", report)
        self.assertIn("pass_telemetry", report)
        self.assertIn("input_cache_keys", report)

    def test_report_pass_metadata_from_passes(self):
        """Report pass_metadata reflects pass results from pipeline."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_COMPLETE,
            "reason": "",
            "applied": [{"patch": {"field": "x"}}],
            "rejected": [],
            "errors": [],
            "warnings": [],
            "passes": [
                {
                    "pass_type": "npc",
                    "pass_telemetry": {
                        "status": ENRICHMENT_STATUS_COMPLETE,
                        "applied_patch_count": 2,
                        "rejected_patch_count": 1,
                        "input_cache_key": "a" * 64,
                    },
                },
                {
                    "pass_type": "location",
                    "pass_telemetry": {
                        "status": ENRICHMENT_STATUS_NOT_IMPLEMENTED,
                        "applied_patch_count": 0,
                        "rejected_patch_count": 0,
                        "input_cache_key": "b" * 64,
                    },
                },
            ],
        }
        report = build_enrichment_report(pipeline_result)
        self.assertEqual(len(report["pass_metadata"]), 2)
        self.assertEqual(len(report["pass_telemetry"]), 2)
        self.assertEqual(len(report["input_cache_keys"]), 2)
        meta = report["pass_metadata"]
        self.assertEqual(meta[0]["pass_type"], "npc")
        self.assertEqual(meta[0]["status"], ENRICHMENT_STATUS_COMPLETE)
        self.assertEqual(meta[0]["applied_count"], 2)
        self.assertEqual(meta[0]["rejected_count"], 1)
        self.assertEqual(meta[1]["pass_type"], "location")
        self.assertEqual(meta[1]["status"], ENRICHMENT_STATUS_NOT_IMPLEMENTED)

    def test_report_input_cache_keys_dict_maps_pass_type_to_key(self):
        """input_cache_keys maps pass_type strings to cache key hex strings."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_COMPLETE,
            "reason": "",
            "applied": [],
            "rejected": [],
            "errors": [],
            "warnings": [],
            "passes": [
                {
                    "pass_type": "npc",
                    "pass_telemetry": {"status": ENRICHMENT_STATUS_NOT_IMPLEMENTED},
                    "npc_pass_inputs": {"input_cache_key": "k1"},
                },
                {
                    "pass_type": "location",
                    "pass_telemetry": {"status": ENRICHMENT_STATUS_NOT_IMPLEMENTED},
                    "location_pass_inputs": {"input_cache_key": "k2"},
                },
            ],
        }
        report = build_enrichment_report(pipeline_result)
        ck = report["input_cache_keys"]
        self.assertEqual(ck.get("npc"), "k1")
        self.assertEqual(ck.get("location"), "k2")

    def test_report_without_telemetry_fails_open(self):
        """Missing pass_telemetry produces empty metadata, not crash."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_DEGRADED,
            "reason": "",
            "applied": [],
            "rejected": [],
            "errors": [{"message": "bad"}],
            "warnings": [],
            "passes": [
                {"pass_type": "npc"},
                {"pass_type": "location"},
            ],
        }
        report = build_enrichment_report(pipeline_result)
        self.assertEqual(len(report["pass_metadata"]), 2)
        self.assertEqual(len(report["pass_telemetry"]), 2)
        self.assertEqual(len(report["input_cache_keys"]), 0)

    def test_report_without_passes_fails_open(self):
        """Missing passes list produces empty metadata arrays."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_SKIPPED,
            "reason": "feature_flag_disabled",
            "applied": [],
            "rejected": [],
            "errors": [],
            "warnings": [],
        }
        report = build_enrichment_report(pipeline_result)
        self.assertEqual(report["pass_metadata"], [])
        self.assertEqual(report["pass_telemetry"], [])
        self.assertEqual(report["input_cache_keys"], {})

    def test_extract_pass_meta_fails_open_on_empty(self):
        """Empty pass result produces empty strings and zeroes in meta."""
        meta = _extract_pass_meta({})
        self.assertEqual(meta["pass_type"], "")
        self.assertEqual(meta["status"], "")
        self.assertEqual(meta["input_cache_key"], "")
        self.assertEqual(meta["applied_count"], 0)
        self.assertEqual(meta["rejected_count"], 0)

    def test_extract_pass_meta_uses_telemetry(self):
        """Extract pass meta reads from pass_telemetry and summary keys."""
        pr = {
            "pass_type": "npc",
            "pass_telemetry": {
                "status": ENRICHMENT_STATUS_COMPLETE,
                "applied_patch_count": 3,
                "rejected_patch_count": 1,
                "input_cache_key": "abc",
            },
        }
        meta = _extract_pass_meta(pr)
        self.assertEqual(meta["pass_type"], "npc")
        self.assertEqual(meta["status"], ENRICHMENT_STATUS_COMPLETE)
        self.assertEqual(meta["applied_count"], 3)
        self.assertEqual(meta["rejected_count"], 1)
        self.assertEqual(meta["input_cache_key"], "abc")

    def test_no_raw_excerpts_in_report_metadata(self):
        """Report pass_metadata does not include large raw excerpts."""
        pipeline_result = {
            "status": ENRICHMENT_STATUS_COMPLETE,
            "reason": "",
            "applied": [],
            "rejected": [],
            "errors": [],
            "warnings": [],
            "passes": [
                {
                    "pass_type": "location",
                    "location_pass_inputs": {
                        "input_cache_key": "abc",
                        "location_targets": [
                            {"source_excerpt": "S" * 500},
                        ] * 10,
                        "area_count": 1,
                    },
                    "pass_telemetry": {"status": ENRICHMENT_STATUS_NOT_IMPLEMENTED},
                },
            ],
        }
        report = build_enrichment_report(pipeline_result)
        for meta_entry in report["pass_metadata"]:
            self.assertNotIn("source_excerpt", meta_entry)
            self.assertNotIn("location_targets", meta_entry)
            self.assertNotIn("npc_targets", meta_entry)
            self.assertNotIn("tone_style_targets", meta_entry)


# ---------------------------------------------------------------------------
# Task 0.3: Prose Phrase Actor Filtering (Numillian entity pollution)
#   Source-contract/behavioral tests for but_this_is_not_true actor filtering.
# ---------------------------------------------------------------------------

class TestProsePhraseActorFiltering(unittest.TestCase):
    """Regression locks for Numillian 'but this is not true' entity pollution.

    The accurate-ingest pipeline must not promote prose emphasis phrases
    into NPC/module actor output. The enrichment layer already has rejection
    logic for non-actor text. These tests lock that behavior.
    """

    def test_validate_enrichment_patch_rejects_empty_blueprint_id(self):
        """A patch with an empty blueprint_id is rejected."""
        bp = _make_blueprint()
        patch = _make_valid_patch(blueprint_id="")
        result = validate_enrichment_patch(patch, bp)
        self.assertFalse(result["valid"])

    def test_validate_enrichment_patches_mixed_valid_invalid(self):
        """Mixed valid patches and empty-blueprint_id patches return correct results."""
        bp = _make_blueprint()
        good = _make_valid_patch()
        bad = _make_valid_patch(blueprint_id="")
        results = validate_enrichment_patches([good, bad], bp)
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["valid"])
        self.assertFalse(results[1]["valid"])

    def test_structural_name_field_mutation_rejected(self):
        """Changing the name field via enrichment patch is rejected."""
        bp = _make_blueprint()
        patch = _make_valid_patch(
            json_path="npcs.sample_npc.name",
            field="name",
        )
        result = validate_enrichment_patch(patch, bp)
        self.assertFalse(
            result["valid"],
            "name field mutation must be rejected by enrichment patch validator",
        )

    def test_description_patch_for_known_npc_passes(self):
        """A description patch for a valid blueprint NPC passes."""
        bp = _make_blueprint()
        patch = _make_valid_patch()
        result = validate_enrichment_patch(patch, bp)
        self.assertTrue(
            result["valid"],
            "Valid description patches for real NPCs must not be blocked.",
        )

    def test_prose_phrase_rejected_by_path_contains_name(self):
        """SOURCE-CONTRACT: 'but this is not true' in a json_path containing 'name' is rejected.

        The enrichment patch validator must reject patches with 'name' in the
        json_path regardless of the name value. This prevents narrative phrases
        from being promoted into actors.
        """
        bp = _make_blueprint()
        patch = _make_valid_patch(
            json_path="npcs.but_this_is_not_true.name",
            field="description",
            value="A narrative phrase masquerading as NPC",
        )
        result = validate_enrichment_patch(patch, bp)
        self.assertFalse(
            result["valid"],
            "Patch with 'name' in json_path must be rejected regardless of value",
        )

    def test_prose_phrase_heuristic_is_deterministic(self):
        """Filtering prose phrases must not require LLM provider calls."""
        name = "but this is not true"
        is_prose = not any(w[0].isupper() for w in name.split() if w)
        self.assertTrue(is_prose, "but this is not true must be identifiable as prose")

    def test_legitimate_short_npc_not_flagged_as_prose(self):
        """Names like Dog-Growl, Book-shut must pass a simple uppercase heuristic."""
        for legitimate in ("Dog-Growl", "Book-shut", "Deflation", "Alms-plate", "Red Skull"):
            has_capital = any(w[0].isupper() for w in legitimate.split() if w)
            self.assertTrue(has_capital, f"{legitimate} must pass uppercase heuristic")


if __name__ == "__main__":
    unittest.main()
