# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free rollback tests for the adaptation publication transaction."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import utils.toolkit_adaptation_campaign as campaign_sync
import utils.toolkit_adaptation_registry as registry
from utils.toolkit_adaptation_publication_transaction import (
    capture_adaptation_publication_snapshot,
    rollback_adaptation_publication,
)
import web.extensions.toolkit_module_finisher as finisher


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_SLUG = "Adapted_Rollback_Fixture"


def _write_json(path: Path, payload: object) -> None:
    """Write a temporary fixture payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _passing_gates() -> dict:
    """Return a complete Python-owned adaptation gate envelope."""
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


class AdaptationRollbackFixture(unittest.TestCase):
    """Keep every registry and campaign mutation inside a project-local temp root."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_rollback_",
        )
        self.root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.registry_path = self.root / "modules" / "world_registry.json"
        self.campaign_path = self.root / "modules" / "campaign.json"
        self.original_registry = {
            "worldName": "Rollback Fixture World",
            "registryVersion": "1.0.0",
            "modules": {},
            "areas": {},
            "themes": {"fixture": "preserve"},
            "isolatedModules": True,
        }
        _write_json(self.registry_path, self.original_registry)

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _create_staged_module(self) -> Path:
        module_dir = self.root / "adaptation-staging" / MODULE_SLUG
        _write_json(
            module_dir / "staging_metadata.json",
            {"status": "complete", "module_slug": MODULE_SLUG},
        )
        _write_json(
            module_dir / "module_context.json",
            {"module_id": MODULE_SLUG, "areas": {"ADP001": {}}},
        )
        _write_json(
            module_dir / "module_plot.json",
            {
                "mainObjective": "Recover the stolen lantern.",
                "plotPoints": [
                    {"id": "PP001", "description": "The lantern is missing."}
                ],
            },
        )
        _write_json(
            module_dir / "areas" / "ADP001.json",
            {
                "areaId": "ADP001",
                "areaName": "Lantern Market",
                "areaDescription": "A crowded market of awnings and bells.",
                "areaType": "settlement",
                "dangerLevel": "low",
                "recommendedLevel": 1,
                "climate": "temperate",
                "terrain": "urban",
                "areaConnectivity": [],
                "areaConnectivityId": [],
                "locations": [
                    {"locationId": "ADP001L01", "locationName": "Stall"}
                ],
            },
        )
        return module_dir

    def _capture(self, area_ids=None) -> dict:
        captured = capture_adaptation_publication_snapshot(
            MODULE_SLUG,
            registry_path=self.registry_path,
            campaign_path=self.campaign_path,
            area_ids=area_ids or [],
        )
        self.assertEqual(captured["status"], "success")
        return captured["snapshot"]

    def test_new_entries_and_partial_area_registration_are_removed(self) -> None:
        snapshot = self._capture(["ADP001", "ADP002"])
        mutated = deepcopy(self.original_registry)
        mutated["modules"][MODULE_SLUG] = {"moduleName": MODULE_SLUG}
        mutated["areas"]["ADP001"] = {"module": MODULE_SLUG}
        _write_json(self.registry_path, mutated)

        first = rollback_adaptation_publication(snapshot, failure_reason="verification")
        self.assertEqual(first["status"], "success")
        self.assertEqual(first["rollback_status"], "rolled_back")
        self.assertTrue(first["verified"])
        self.assertEqual(
            json.loads(self.registry_path.read_text(encoding="utf-8")),
            self.original_registry,
        )
        self.assertFalse(self.campaign_path.exists())

    def test_preexisting_module_area_and_campaign_entries_are_restored_exactly(self) -> None:
        original = deepcopy(self.original_registry)
        original["modules"][MODULE_SLUG] = {
            "moduleName": MODULE_SLUG,
            "areaCount": 2,
            "legacy": {"keep": True},
        }
        original["areas"]["ADP001"] = {
            "module": MODULE_SLUG,
            "areaName": "Prior Market",
        }
        original["areas"]["ADP002"] = {
            "module": MODULE_SLUG,
            "areaName": "Prior Road",
        }
        original["areas"]["OTHER"] = {"module": "Other_Module"}
        _write_json(self.registry_path, original)
        original_campaign = {
            "campaignName": "Rollback Campaign",
            "availableModules": ["Existing_Module", MODULE_SLUG],
            "currentModule": "Existing_Module",
            "unrelated": {"keep": "exactly"},
        }
        _write_json(self.campaign_path, original_campaign)

        snapshot = self._capture(["ADP001", "ADP002", "ADP003"])
        mutated_registry = deepcopy(original)
        mutated_registry["modules"][MODULE_SLUG] = {"moduleName": MODULE_SLUG}
        del mutated_registry["areas"]["ADP002"]
        mutated_registry["areas"]["ADP003"] = {"module": MODULE_SLUG}
        _write_json(self.registry_path, mutated_registry)
        mutated_campaign = deepcopy(original_campaign)
        mutated_campaign["availableModules"].append("Another_Module")
        _write_json(self.campaign_path, mutated_campaign)

        result = rollback_adaptation_publication(snapshot)

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            json.loads(self.registry_path.read_text(encoding="utf-8")), original
        )
        self.assertEqual(
            json.loads(self.campaign_path.read_text(encoding="utf-8")),
            original_campaign,
        )
        self.assertTrue(result["registry"]["changed"])
        self.assertTrue(result["campaign"]["changed"])

    def test_absent_campaign_file_is_removed_if_a_failed_step_created_it(self) -> None:
        snapshot = self._capture()
        _write_json(
            self.campaign_path,
            {"campaignName": "Unexpected", "availableModules": [MODULE_SLUG]},
        )

        result = rollback_adaptation_publication(snapshot)

        self.assertEqual(result["status"], "success")
        self.assertFalse(self.campaign_path.exists())

    def test_rollback_is_idempotent(self) -> None:
        snapshot = self._capture()
        mutated = deepcopy(self.original_registry)
        mutated["modules"][MODULE_SLUG] = {"moduleName": MODULE_SLUG}
        _write_json(self.registry_path, mutated)

        first = rollback_adaptation_publication(snapshot)
        second = rollback_adaptation_publication(snapshot)

        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "success")
        self.assertTrue(second["idempotent"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["registry"]["action"], "already_restored")

    def test_post_registration_verification_failure_cleans_new_entries(self) -> None:
        module_dir = self._create_staged_module()
        with patch.object(
            registry,
            "verify_adaptation_registry_entries",
            return_value=None,
        ):
            result = registry.integrate_adaptation_registry(
                MODULE_SLUG,
                module_dir,
                registry_path=self.registry_path,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "registry_post_write_verification_missing")
        self.assertEqual(result["rollback"]["status"], "success")
        persisted = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertNotIn(MODULE_SLUG, persisted["modules"])
        self.assertEqual(persisted["areas"], {})

    def test_campaign_sync_failure_restores_registry_and_campaign(self) -> None:
        module_dir = self._create_staged_module()
        original_campaign = {
            "campaignName": "Rollback Campaign",
            "availableModules": ["Existing_Module"],
            "currentModule": "Existing_Module",
        }
        _write_json(self.campaign_path, original_campaign)
        with patch.object(
            campaign_sync,
            "synchronize_adaptation_campaign_module",
            return_value={
                "status": "blocked",
                "reason": "campaign_post_write_verification_failed",
                "campaign_visibility_verified": False,
            },
        ):
            result = registry.integrate_adaptation_registry(
                MODULE_SLUG,
                module_dir,
                registry_path=self.registry_path,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "adaptation_campaign_sync_failed")
        self.assertEqual(result["rollback"]["status"], "success")
        self.assertEqual(
            json.loads(self.registry_path.read_text(encoding="utf-8")),
            self.original_registry,
        )
        self.assertEqual(
            json.loads(self.campaign_path.read_text(encoding="utf-8")),
            original_campaign,
        )

    def test_final_report_failure_returns_blocked_and_cleans_publication(self) -> None:
        module_dir = self._create_staged_module()
        original_campaign = {
            "campaignName": "Rollback Campaign",
            "availableModules": ["Existing_Module"],
        }
        _write_json(self.campaign_path, original_campaign)
        target = {
            "path": module_dir.relative_to(self.root).as_posix(),
            "module_slug": MODULE_SLUG,
        }
        summary = {
            "status": "success",
            "path": str(module_dir / "MODULE_SUMMARY.md"),
            "bytes": 256,
            "quality": {"valid": True},
        }
        persist_calls = []

        def fail_final_report(*args, **kwargs):
            persist_calls.append(True)
            return len(persist_calls) == 1

        with patch.object(
            finisher, "_run_module_summary_stage", return_value=summary
        ), patch.object(
            finisher,
            "_persist_adaptation_finishing_report",
            side_effect=fail_final_report,
        ):
            result = finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_gates(),
                adaptation_staging_target=target,
                adaptation_module_dir=str(module_dir),
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["terminal_status"], "blocked")
        self.assertEqual(result["publication_status"], "blocked")
        self.assertEqual(result["rollback"]["status"], "success")
        self.assertEqual(
            json.loads(self.registry_path.read_text(encoding="utf-8")),
            self.original_registry,
        )
        self.assertEqual(
            json.loads(self.campaign_path.read_text(encoding="utf-8")),
            original_campaign,
        )
        self.assertGreaterEqual(len(persist_calls), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
