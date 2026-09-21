# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for adaptation campaign availability synchronization."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import utils.toolkit_adaptation_campaign as campaign_sync
import web.extensions.toolkit_module_finisher as finisher


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_SLUG = "Adapted_Campaign_Fixture"


def _write_json(path: Path, payload: object) -> None:
    """Write a fixture JSON file inside the project-local temporary root."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _passing_gates() -> dict:
    """Return the complete Python-owned adaptation gate envelope."""
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


class AdaptationCampaignFixture(unittest.TestCase):
    """Use only project-local temporary registry, campaign, and staging data."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_campaign_",
        )
        self.root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.registry_path = self.root / "modules" / "world_registry.json"
        self.campaign_path = self.root / "modules" / "campaign.json"
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
        self._create_staged_module()

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _create_staged_module(self) -> None:
        self.module_dir = self.root / "tmp" / "adaptation-staging" / MODULE_SLUG
        self.module_dir.mkdir(parents=True, exist_ok=True)
        (self.module_dir / "staging_metadata.json").write_text(
            "{}", encoding="utf-8"
        )
        _write_json(
            self.module_dir / "module_context.json",
            {
                "module_id": MODULE_SLUG,
                "areas": {"ADP001": {}},
            },
        )
        _write_json(
            self.module_dir / "module_plot.json",
            {
                "mainObjective": "Recover the stolen lantern.",
                "plotPoints": [
                    {"id": "PP001", "description": "The lantern is missing."}
                ],
            },
        )
        _write_json(
            self.module_dir / "areas" / "ADP001.json",
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

    def _write_campaign(self, payload: object) -> None:
        _write_json(self.campaign_path, payload)

    def _seed_registry_module(self) -> None:
        """Represent a previously verified registry publication."""
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        registry["modules"][MODULE_SLUG] = {
            "moduleName": MODULE_SLUG,
            "areaCount": 1,
        }
        _write_json(self.registry_path, registry)

    def _target(self) -> dict:
        return {
            "path": self.module_dir.relative_to(self.root).as_posix(),
            "module_slug": MODULE_SLUG,
        }

    def _summary(self) -> dict:
        return {
            "status": "success",
            "path": str(self.module_dir / "MODULE_SUMMARY.md"),
            "bytes": 256,
            "quality": {"valid": True, "reason": "readable_markdown"},
        }

    def test_active_campaign_is_written_and_verified_after_registry_publication(
        self,
    ) -> None:
        self._write_campaign(
            {
                "campaignName": "Fixture Campaign",
                "currentModule": "Existing_Module",
                "availableModules": ["Existing_Module"],
                "worldState": {"keepOwnership": False},
                "unrelatedSentinel": "preserve-me",
            }
        )

        with patch.object(
            finisher, "_run_module_summary_stage", return_value=self._summary()
        ):
            result = finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_gates(),
                adaptation_staging_target=self._target(),
                adaptation_module_dir=str(self.module_dir),
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["stages"]["registry"]["status"], "success")
        sync_result = result["stages"]["campaign_sync"]
        self.assertEqual(sync_result["status"], "success")
        self.assertTrue(sync_result["campaign_visibility_verified"])
        self.assertTrue(sync_result["verification"]["visible"])
        self.assertEqual(
            result["stages"]["registry"]["campaign_sync"]["status"],
            "success",
        )

        persisted = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        self.assertIn(MODULE_SLUG, persisted["availableModules"])
        self.assertEqual(persisted["currentModule"], "Existing_Module")
        self.assertEqual(persisted["worldState"], {"keepOwnership": False})
        self.assertEqual(persisted["unrelatedSentinel"], "preserve-me")

    def test_no_active_campaign_is_explicitly_deferred_without_failing_publication(
        self,
    ) -> None:
        with patch.object(
            finisher, "_run_module_summary_stage", return_value=self._summary()
        ):
            result = finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_gates(),
                adaptation_staging_target=self._target(),
                adaptation_module_dir=str(self.module_dir),
            )

        self.assertEqual(result["status"], "success")
        sync_result = result["stages"]["campaign_sync"]
        self.assertEqual(sync_result["status"], "deferred")
        self.assertEqual(sync_result["reason"], "no_active_campaign")
        self.assertFalse(sync_result["campaign_visibility_verified"])
        self.assertFalse(self.campaign_path.exists())
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertIn(MODULE_SLUG, registry["modules"])

    def test_malformed_campaign_fails_without_claiming_visibility(self) -> None:
        self._write_campaign(
            {
                "campaignName": "Fixture Campaign",
                "availableModules": "not-a-list",
            }
        )

        with patch.object(
            finisher, "_run_module_summary_stage", return_value=self._summary()
        ):
            result = finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_gates(),
                adaptation_staging_target=self._target(),
                adaptation_module_dir=str(self.module_dir),
            )

        self.assertEqual(result["status"], "blocked")
        sync_result = result["stages"]["campaign_sync"]
        self.assertEqual(sync_result["status"], "blocked")
        self.assertEqual(
            sync_result["reason"], "campaign_available_modules_malformed"
        )
        self.assertFalse(sync_result["campaign_visibility_verified"])
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertNotIn(MODULE_SLUG, registry["modules"])
        self.assertEqual(result["stages"]["registry"]["rollback"]["status"], "success")

    def test_missing_required_campaign_fails_closed(self) -> None:
        result = campaign_sync.synchronize_adaptation_campaign_module(
            MODULE_SLUG,
            campaign_path=self.campaign_path,
            registry_path=self.registry_path,
            require_active_campaign=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "campaign_missing")
        self.assertFalse(result["campaign_visibility_verified"])
        self.assertFalse(self.campaign_path.exists())

    def test_campaign_write_failure_and_unverifiable_write_fail_closed(self) -> None:
        self._seed_registry_module()
        self._write_campaign(
            {
                "campaignName": "Fixture Campaign",
                "availableModules": [],
            }
        )

        with patch.object(campaign_sync, "safe_write_json", return_value=False):
            write_failed = campaign_sync.synchronize_adaptation_campaign_module(
                MODULE_SLUG,
                campaign_path=self.campaign_path,
                registry_path=self.registry_path,
            )
        self.assertEqual(write_failed["status"], "blocked")
        self.assertEqual(write_failed["reason"], "campaign_write_failed")
        self.assertFalse(write_failed["campaign_visibility_verified"])

        with patch.object(campaign_sync, "safe_write_json", return_value=True):
            unverifiable = campaign_sync.synchronize_adaptation_campaign_module(
                MODULE_SLUG,
                campaign_path=self.campaign_path,
                registry_path=self.registry_path,
            )
        self.assertEqual(unverifiable["status"], "blocked")
        self.assertEqual(
            unverifiable["reason"], "campaign_post_write_verification_failed"
        )
        self.assertFalse(unverifiable["campaign_visibility_verified"])

    def test_legacy_registry_dispatch_does_not_run_campaign_sync(self) -> None:
        with patch.object(
            finisher, "_run_adaptation_campaign_sync_stage"
        ) as campaign_stage, patch(
            "core.generators.module_stitcher.ModuleStitcher"
        ) as stitcher, patch(
            "scripts.homebrew_registry_guard.verify_present",
            side_effect=[{"present": False}, {"present": False}],
        ):
            stitcher.return_value.integrate_module.return_value = False
            result = finisher._run_registry_stage(MODULE_SLUG)

        campaign_stage.assert_not_called()
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
