# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for task 3.3 adaptation staging targets."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_staging import (
    AdaptationStagingError,
    AdaptationStagingTargetExistsError,
    STAGING_STATE_BUILDING,
    STAGING_STATE_COMPLETED,
    STAGING_STATE_FAILED,
    cleanup_adaptation_staging_target,
    create_adaptation_staging_target,
    update_adaptation_staging_target,
    validate_adaptation_staging_target,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "tmp" / "toolkit_adaptation_staging_contract"
SOURCE_HASH = "a" * 64


class TestAdaptationStagingContract(unittest.TestCase):
    """Staging reservations are isolated, deterministic, and fail closed."""

    def setUp(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)

    def _create(self, **overrides):
        values = {
            "source_hash": SOURCE_HASH,
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": "staging-fixture",
            "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
            "module_slug": "Lantern_Market",
            "staging_root": "tmp/adaptation-staging",
            "repo_root": WORKSPACE,
        }
        values.update(overrides)
        return create_adaptation_staging_target(**values)

    def test_initial_and_revised_targets_are_fresh_and_linked(self) -> None:
        initial = self._create()
        revised = self._create(
            attempt_id=initial["attempt_id"],
            revision_number=1,
        )

        self.assertNotEqual(initial["path"], revised["path"])
        self.assertIn(initial["attempt_id"], initial["path"])
        self.assertIn("revision_000", initial["path"])
        self.assertIn("revision_001", revised["path"])
        self.assertEqual(initial["source_hash"], revised["source_hash"])
        self.assertEqual(initial["attempt_id"], revised["attempt_id"])
        self.assertEqual(initial["revision_number"], 0)
        self.assertEqual(revised["revision_number"], 1)
        self.assertEqual(initial["completion_state"], "reserved")
        self.assertTrue((WORKSPACE / initial["path"] / "staging_metadata.json").exists())
        self.assertTrue((WORKSPACE / revised["path"] / "staging_metadata.json").exists())

    def test_path_traversal_absolute_and_live_root_targets_are_rejected(self) -> None:
        for unsafe_root in (
            "../outside",
            "tmp/../modules",
            "/private/staging",
            "C:/staging",
            "modules/adaptation-staging",
            "characters/adaptation-staging",
        ):
            with self.subTest(unsafe_root=unsafe_root):
                with self.assertRaises(AdaptationStagingError):
                    self._create(staging_root=unsafe_root)

    def test_duplicate_and_stale_targets_are_never_reused(self) -> None:
        initial = self._create()
        with self.assertRaises(AdaptationStagingTargetExistsError):
            self._create()

        marker = WORKSPACE / initial["path"] / "staging_metadata.json"
        marker.unlink()
        with self.assertRaises(AdaptationStagingTargetExistsError):
            self._create()

        revised = self._create(
            attempt_id=initial["attempt_id"],
            revision_number=1,
        )
        self.assertTrue((WORKSPACE / initial["path"]).exists())
        self.assertTrue((WORKSPACE / revised["path"]).exists())

    def test_failed_build_state_and_cleanup_cannot_touch_registered_module(self) -> None:
        module_dir = WORKSPACE / "modules" / "Registered_Module"
        module_dir.mkdir(parents=True, exist_ok=True)
        module_file = module_dir / "module_context.json"
        registry_file = WORKSPACE / "modules" / "world_registry.json"
        campaign_file = WORKSPACE / "modules" / "campaign.json"
        module_file.write_text('{"status":"published"}', encoding="utf-8")
        registry_file.write_text('{"modules":["Registered_Module"]}', encoding="utf-8")
        campaign_file.write_text('{"available_modules":[]}', encoding="utf-8")
        before = {
            path: path.read_bytes()
            for path in (module_file, registry_file, campaign_file)
        }

        target = self._create(module_slug="New_Adaptation")
        stage_file = WORKSPACE / target["path"] / "partial.json"
        stage_file.write_text('{"partial":true}', encoding="utf-8")
        failed = update_adaptation_staging_target(
            target,
            STAGING_STATE_FAILED,
            repo_root=WORKSPACE,
            error="provider-free fixture failure",
        )
        self.assertEqual(failed["completion_state"], STAGING_STATE_FAILED)
        cleanup_result = cleanup_adaptation_staging_target(failed, repo_root=WORKSPACE)
        self.assertEqual(cleanup_result["status"], "cleaned")
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse((WORKSPACE / "modules" / "New_Adaptation").exists())

    def test_cleanup_is_scoped_and_safe_for_partial_targets(self) -> None:
        target = self._create()
        stage_dir = WORKSPACE / target["path"]
        (stage_dir / "areas").mkdir()
        (stage_dir / "areas" / "partial.json").write_text("{}", encoding="utf-8")

        result = cleanup_adaptation_staging_target(target, repo_root=WORKSPACE)
        self.assertEqual(result["status"], "cleaned")
        self.assertFalse(stage_dir.exists())
        self.assertTrue((WORKSPACE / "tmp" / "adaptation-staging").exists())
        second = cleanup_adaptation_staging_target(target, repo_root=WORKSPACE)
        self.assertEqual(second["status"], "not_found")

    def test_state_updates_require_matching_reserved_target(self) -> None:
        target = self._create()
        building = update_adaptation_staging_target(
            target,
            STAGING_STATE_BUILDING,
            repo_root=WORKSPACE,
        )
        self.assertEqual(building["completion_state"], STAGING_STATE_BUILDING)
        completed = update_adaptation_staging_target(
            building,
            STAGING_STATE_COMPLETED,
            repo_root=WORKSPACE,
            output_hash=SOURCE_HASH,
        )
        self.assertEqual(completed["completion_state"], STAGING_STATE_COMPLETED)
        self.assertEqual(completed["output_hash"], SOURCE_HASH)
        with self.assertRaises(AdaptationStagingError):
            validate_adaptation_staging_target(
                completed,
                source_hash=SOURCE_HASH,
                module_slug="Lantern_Market",
                repo_root=WORKSPACE,
            )

    def test_packet_builder_routes_only_explicit_adaptation_to_staging(self) -> None:
        from web.extensions.toolkit_homebrew_packet_builder import (
            _execute_module_builder,
        )

        target = create_adaptation_staging_target(
            SOURCE_HASH,
            job_id="builder-target-fixture",
            source_path="scripts/fixtures/toolkit_adaptation_catalogue.md",
            module_slug="Lantern_Market",
            staging_root="tmp/toolkit_adaptation_staging_builder_target",
            repo_root=REPO_ROOT,
        )
        builder_input = {
            "build_mode": "llm_adaptation",
            "builder_narrative": "Build the staged adaptation.",
            "derived_builder_parameters": {
                "module_name": "Lantern_Market",
                "num_areas": 1,
                "locations_per_area": 3,
                "output_directory": "modules/Lantern_Market",
            },
            "staging_target": target,
            "llm_adaptation": {"dossier": {}, "provenance": {}},
        }
        with patch("core.generators.module_builder.ModuleBuilder") as builder_cls:
            builder_cls.return_value.build_module.return_value = None
            # This source-level plumbing check uses a mocked builder; dossier
            # validation is covered by the adaptation handoff suite.
            with patch(
                "web.extensions.toolkit_homebrew_packet_builder.build_llm_adaptation_handoff",
                return_value=builder_input["llm_adaptation"],
            ):
                _execute_module_builder(builder_input)

        self.assertEqual(builder_cls.call_args.args[0].output_directory, target["path"])
        cleanup_adaptation_staging_target(target, repo_root=REPO_ROOT)

    def test_failed_packet_build_preserves_existing_registered_module(self) -> None:
        from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM
        from web.extensions.toolkit_homebrew_packet_builder import (
            run_toolkit_homebrew_packet_build,
        )

        fixture_path = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
        dossier = json.loads(fixture_path.read_text(encoding="utf-8"))
        packet_workspace = WORKSPACE / "packet_workspace"
        packet_workspace.mkdir(parents=True, exist_ok=True)
        (packet_workspace / "normalized_packet.json").write_text(
            json.dumps(
                {
                    "packet_version": "packet.v1",
                    "name": "existing-module-failure-fixture",
                    "title": "Keep of Doom",
                    "description": "A failed adaptation must remain staged.",
                    "source_hash": dossier["source_hash"],
                    "source_rights": "user_authored",
                    "normalization_state": "normalized",
                }
            ),
            encoding="utf-8",
        )
        (packet_workspace / "ui_review_snapshot.json").write_text(
            json.dumps(
                {
                    "decision": "approve",
                    "recorded_at": "2026-01-01T00:00:00Z",
                    "job_id": "failed-existing-module",
                    "packet_identity": {"source_hash": dossier["source_hash"]},
                }
            ),
            encoding="utf-8",
        )
        (packet_workspace / "builder_narrative.txt").write_text(
            "Build the failed adaptation fixture.",
            encoding="utf-8",
        )

        module_dir = REPO_ROOT / "modules" / "Keep_of_Doom"
        self.assertTrue(module_dir.exists())
        protected_paths = [
            module_dir / "module_context.json",
            module_dir / "module_context_BU.json",
            REPO_ROOT / "modules" / "world_registry.json",
            REPO_ROOT / "modules" / "campaign.json",
        ]
        protected_before = {
            path: path.read_bytes() for path in protected_paths if path.exists()
        }

        def fail_after_partial_write(builder_input):
            stage_dir = REPO_ROOT / builder_input["derived_builder_parameters"]["output_directory"]
            stage_dir.mkdir(parents=True, exist_ok=True)
            (stage_dir / "partial.json").write_text("{}", encoding="utf-8")
            raise RuntimeError("provider-free build failure")

        with patch(
            "web.extensions.toolkit_homebrew_packet_builder.ENABLE_LLM_ADAPTATION",
            True,
        ), patch(
            "utils.monster_reference_closure.ensure_monster_reference_closure",
            return_value={"required": 0, "existing_before": 0, "generated": 0, "unresolved": 0},
        ), patch(
            "utils.spatial_repair.repair_module_spatial",
            return_value={"status": "pass", "input_location_count": 0},
        ), patch(
            "utils.calendar_normalization.normalize_party_calendar",
            return_value={"status": "pass"},
        ):
            result = run_toolkit_homebrew_packet_build(
                packet_workspace,
                "failed-existing-module",
                builder_executor=fail_after_partial_write,
                adaptation_route=ADAPTATION_MODE_LLM,
                adaptation_dossier=dossier,
                adaptation_staging_root="tmp/toolkit_adaptation_staging_failure",
            )

        self.assertNotEqual(result.get("status"), "success")
        self.assertEqual(
            result.get("staging_target", {}).get("completion_state"),
            STAGING_STATE_FAILED,
        )
        self.assertEqual(
            protected_before,
            {path: path.read_bytes() for path in protected_before},
        )
        staging_target = result.get("staging_target")
        self.assertIsInstance(staging_target, dict)
        cleanup_adaptation_staging_target(staging_target, repo_root=REPO_ROOT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
