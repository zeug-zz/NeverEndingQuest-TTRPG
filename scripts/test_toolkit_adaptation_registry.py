# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free tests for adaptation registry integration and verification."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import utils.toolkit_adaptation_registry as registry
import web.extensions.toolkit_module_finisher as finisher


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_SLUG = "Adapted_Registry_Fixture"


def _write_json(path: Path, payload: object) -> None:
    """Write a temporary fixture JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _passing_gates() -> dict:
    """Return the task 7.1 adaptation gate envelope."""
    domains = (
        "schema",
        "readiness",
        "mechanical_closure",
        "semantic_authority",
        "semantic_probes",
    )
    gates = {
        domain: {"status": "pass", "effective_status": "pass"}
        for domain in domains
    }
    gates["report_agreement"] = {
        "status": "pass",
        "effective_status": "pass",
        "playable_publication_status": "pass",
        "agreement": {"playable_publication_status": "pass"},
    }
    return {
        "status": "pass",
        "playable_status": "pass",
        "candidate_eligible": True,
        "gates": gates,
    }


class AdaptationRegistryFixture(unittest.TestCase):
    """Use only a project-local temporary registry and staged module."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_registry_",
        )
        self.root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.registry_path = self.root / "modules" / "world_registry.json"
        _write_json(
            self.registry_path,
            {
                "worldName": "Fixture World",
                "registryVersion": "1.0.0",
                "modules": {},
                "areas": {},
                "themes": {},
                "isolatedModules": True,
            },
        )
        self.module_dir = self.root / "adaptation-staging" / MODULE_SLUG
        self._create_module()

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _create_module(self) -> None:
        self.module_dir.mkdir(parents=True, exist_ok=True)
        (self.module_dir / "staging_metadata.json").write_text(
            "{}", encoding="utf-8"
        )
        _write_json(
            self.module_dir / "module_plot.json",
            {
                "mainObjective": "Recover the stolen lantern.",
                "plotPoints": [
                    {"id": "PP001", "description": "The lantern is missing."},
                    {"id": "PP002", "description": "The market keeper knows a clue."},
                ],
            },
        )
        _write_json(
            self.module_dir / "module_context.json",
            {
                "module_id": MODULE_SLUG,
                "areas": {"ADP001": {}, "ADP002": {}},
                "travelNarration": {
                    "travelNarration": "The road bends toward a busy market.",
                    "dmGuidance": "Keep the arrival brisk and curious.",
                }
            },
        )
        area_payloads = {
            "ADP001": {
                "areaId": "ADP001",
                "areaName": "Lantern Market",
                "areaDescription": "A crowded market of awnings and bells.",
                "areaType": "settlement",
                "dangerLevel": "low",
                "recommendedLevel": 1,
                "climate": "temperate",
                "terrain": "urban",
                "areaConnectivity": ["Old Road"],
                "areaConnectivityId": ["ADP002"],
                "locations": [{"locationId": "ADP001L01", "locationName": "Stall"}],
            },
            "ADP002": {
                "areaId": "ADP002",
                "areaName": "Old Road",
                "areaDescription": "A quiet road beyond the market.",
                "areaType": "road",
                "dangerLevel": "medium",
                "recommendedLevel": 2,
                "climate": "temperate",
                "terrain": "road",
                "areaConnectivity": ["Lantern Market"],
                "areaConnectivityId": ["ADP001"],
                "locations": [
                    {"locationId": "ADP002L01", "locationName": "Milestone"},
                    {"locationId": "ADP002L02", "locationName": "Bridge"},
                ],
            },
        }
        for area_id, payload in area_payloads.items():
            _write_json(self.module_dir / "areas" / f"{area_id}.json", payload)

    def _integrate(self) -> dict:
        return registry.integrate_adaptation_registry(
            MODULE_SLUG,
            self.module_dir,
            registry_path=self.registry_path,
        )

    def test_module_and_area_entries_are_created_and_verified(self) -> None:
        result = self._integrate()

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["verified"])
        self.assertEqual(result["expected_area_ids"], ["ADP001", "ADP002"])
        persisted = json.loads(self.registry_path.read_text(encoding="utf-8"))
        module_entry = persisted["modules"][MODULE_SLUG]
        self.assertEqual(module_entry["moduleName"], MODULE_SLUG)
        self.assertEqual(module_entry["areaCount"], 2)
        self.assertEqual(module_entry["levelRange"], {"min": 1, "max": 2})
        self.assertEqual(
            persisted["areas"]["ADP001"]["areaName"], "Lantern Market"
        )
        self.assertEqual(persisted["areas"]["ADP002"]["module"], MODULE_SLUG)
        self.assertTrue(result["verification"]["module_verified"])
        self.assertTrue(result["verification"]["areas_verified"])

    def test_post_write_verification_matches_exact_content_metadata(self) -> None:
        entries_result = registry.build_adaptation_registry_entries(
            MODULE_SLUG,
            self.module_dir,
            added_date="2026-08-04T00:00:00Z",
        )
        self.assertEqual(entries_result["status"], "success")
        entries = entries_result["entries"]
        persisted = {
            "modules": {MODULE_SLUG: deepcopy(entries["module_entry"])},
            "areas": deepcopy(entries["area_entries"]),
            "lastUpdated": entries["registry_last_updated"],
        }
        _write_json(self.registry_path, persisted)

        verified = registry.verify_adaptation_registry_entries(
            self.registry_path, entries
        )
        self.assertEqual(verified["status"], "success")
        self.assertTrue(verified["verified"])

        persisted["modules"][MODULE_SLUG]["areaCount"] = 9
        _write_json(self.registry_path, persisted)
        rejected_module = registry.verify_adaptation_registry_entries(
            self.registry_path, entries
        )
        self.assertEqual(rejected_module["status"], "blocked")
        self.assertTrue(
            any(
                mismatch.get("field") == "module.areaCount"
                for mismatch in rejected_module["mismatches"]
            )
        )

        persisted["modules"][MODULE_SLUG]["areaCount"] = 2
        persisted["areas"]["ADP001"]["areaName"] = "Wrong Market"
        _write_json(self.registry_path, persisted)
        rejected = registry.verify_adaptation_registry_entries(
            self.registry_path, entries
        )
        self.assertEqual(rejected["status"], "blocked")
        self.assertFalse(rejected["verified"])
        self.assertTrue(
            any(
                mismatch.get("field") == "areas.ADP001.areaName"
                for mismatch in rejected["mismatches"]
            )
        )

    def test_missing_verification_is_blocked(self) -> None:
        with patch.object(
            registry, "verify_adaptation_registry_entries", return_value=None
        ):
            result = self._integrate()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "registry_post_write_verification_missing")
        self.assertNotEqual(result["status"], "success")
        self.assertEqual(result["rollback"]["status"], "success")
        persisted = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["modules"], {})
        self.assertEqual(persisted["areas"], {})

    def test_failed_verification_is_blocked(self) -> None:
        with patch.object(
            registry,
            "verify_adaptation_registry_entries",
            return_value={"status": "blocked", "verified": False},
        ):
            result = self._integrate()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "registry_post_write_verification_failed")
        self.assertFalse(result["verification"]["verified"])

    def test_registry_write_failure_is_blocked_without_entries(self) -> None:
        with patch.object(registry, "safe_write_json", return_value=False):
            result = self._integrate()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "registry_write_failed")
        persisted = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["modules"], {})
        self.assertEqual(persisted["areas"], {})

    def test_malformed_registry_output_is_blocked_after_write(self) -> None:
        def corrupt_write(path: str, payload: object) -> bool:
            Path(path).write_text(
                json.dumps({"modules": [], "areas": {}}),
                encoding="utf-8",
            )
            return True

        with patch.object(registry, "safe_write_json", side_effect=corrupt_write):
            result = self._integrate()

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "registry_post_write_verification_failed")
        self.assertEqual(
            result["verification"]["reason"], "registry_modules_malformed"
        )

    def test_missing_or_malformed_area_blocks_before_registry_write(self) -> None:
        shutil.rmtree(self.module_dir / "areas")
        missing_result = self._integrate()
        self.assertEqual(missing_result["status"], "blocked")
        self.assertIn("area", missing_result["reason"])

        self._create_module()
        (self.module_dir / "areas" / "ADP001.json").write_text(
            "{not-json", encoding="utf-8"
        )
        malformed_result = self._integrate()
        self.assertEqual(malformed_result["status"], "blocked")
        persisted = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["modules"], {})

    def test_malformed_registry_blocks_before_registry_write(self) -> None:
        _write_json(
            self.registry_path,
            {"modules": [], "areas": {}, "registryVersion": "1.0.0"},
        )
        result = self._integrate()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("registry_modules_malformed", result["reason"])

    def test_context_area_gap_blocks_registry_integration(self) -> None:
        context_path = self.module_dir / "module_context.json"
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["areas"]["ADP003"] = {}
        _write_json(context_path, context)

        result = self._integrate()

        self.assertEqual(result["status"], "blocked")
        self.assertIn("module_context_area_entries_missing", result["reason"])

    def test_finisher_never_reports_success_on_failed_registry_verification(self) -> None:
        target = {
            "path": self.module_dir.relative_to(self.root).as_posix(),
            "module_slug": MODULE_SLUG,
        }
        summary = {
            "status": "success",
            "path": str(self.module_dir / "MODULE_SUMMARY.md"),
            "bytes": 256,
            "quality": {"valid": True},
        }
        with patch.object(finisher, "_run_module_summary_stage", return_value=summary), patch.object(
            registry,
            "verify_adaptation_registry_entries",
            return_value={"status": "blocked", "verified": False},
        ):
            result = finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_gates(),
                adaptation_staging_target=target,
                adaptation_module_dir=str(self.module_dir),
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stages"]["registry"]["status"], "blocked")
        self.assertEqual(result["publishable_status"], "fail")
        self.assertNotEqual(result["status"], "success")
        self.assertEqual(result["publication_status"], "blocked")
        self.assertEqual(result["stages"]["registry"]["rollback"]["status"], "success")


class TestAdaptationLegacyIsolation(unittest.TestCase):
    """Ensure the strict helper is only selected by adaptation routing."""

    def test_legacy_registry_stage_does_not_call_adaptation_helper(self) -> None:
        with patch.object(registry, "integrate_adaptation_registry") as adaptation, patch(
            "core.generators.module_stitcher.ModuleStitcher"
        ) as stitcher, patch(
            "scripts.homebrew_registry_guard.verify_present",
            side_effect=[{"present": False}, {"present": False}],
        ):
            stitcher.return_value.integrate_module.return_value = False
            result = finisher._run_registry_stage("Legacy_Registry_Fixture")

        adaptation.assert_not_called()
        self.assertEqual(result["status"], "failed")

    def test_adaptation_registry_stage_uses_strict_helper(self) -> None:
        module_dir = Path("tmp/adaptation-registry-dispatch")
        with patch.object(
            registry,
            "integrate_adaptation_registry",
            return_value={"status": "success"},
        ) as adaptation:
            result = finisher._run_registry_stage(
                "Adapted_Registry_Fixture",
                module_dir=module_dir,
                adaptation=True,
            )

        self.assertEqual(result["status"], "success")
        adaptation.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
