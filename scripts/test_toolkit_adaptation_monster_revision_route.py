# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Provider-free regression tests for the initial monster revision route."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from web.extensions.toolkit_homebrew_packet_builder import (
    _route_adaptation_monster_revision,
)


class MonsterRevisionRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("tmp") / "toolkit_adaptation_monster_revision_route"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.calls = []
        self.source_hash = "a" * 64
        self.handoff = {"provenance": {
            "attempt_id": "adapt-amphail",
            "attempt_number": 1,
            "revision_number": 0,
            "source_hash": self.source_hash,
            "source_path": "scripts/fixtures/amphail.md",
        }}

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _callback(self, context):
        self.calls.append(context)
        identity = {
            key: context["convergence_context"][key]
            for key in ("attempt_id", "attempt_number", "revision_number", "source_hash")
        }
        return {
            "contract_version": "adaptation_finalization_proposal.v1",
            "operation": "resolve_monster_reference",
            "identity": identity,
            "target": {
                "reference_key": "cave_guardians",
                "canonical_identity": "Cave Guardian",
            },
            "source_references": ["K08"],
            "confidence": 0.95,
            "resolution_code": "plural_group_label",
        }

    def test_initial_failure_reaches_fresh_bounded_route(self) -> None:
        old_target = {
            "path": "tmp/adaptation-staging/adapt-amphail/revision_000",
            "attempt_id": "adapt-amphail",
            "attempt_number": 1,
            "revision_number": 0,
            "source_hash": self.source_hash,
        }
        report = {
            "unresolved_refs": ["cave_guardians"],
            "approved_monster_identities": ["Cave Guardian"],
            "quantity_evidence": [{"location_id": "K06", "quantity": {"min": 1, "max": 1}}],
            "contradiction_diagnostics": [{
                "source_location": "K08",
                "code": "quantity_prose_contradiction",
                "message": "scene prose and quantity differ",
            }],
        }
        result = _route_adaptation_monster_revision(
            build_result={"status": "blocked"},
            guardrail_report=report,
            classification={
                "failure_class": "semantic",
                "code": "monster_closure_unresolved",
                "revision_eligible": True,
                "semantic_revision_eligible": True,
                "revision_budget": {
                    "current_revision": 0,
                    "max_revisions": 1,
                    "remaining_before_failure": 1,
                },
            },
            adaptation_handoff=self.handoff,
            staging_target=old_target,
            workspace=self.root,
            job_id="amphail-job",
            staging_root="tmp/toolkit_adaptation_monster_revision_route/staging",
            module_slug="Amphail",
            revision_callback=self._callback,
        )
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["error"], "adaptation_revision_required")
        self.assertEqual(result["revision_budget"]["remaining_revisions"], 1)
        self.assertIn("revision_001", result["adaptation_revision"]["report_path"])
        packet = self.calls[0]["failure_packet"]
        self.assertEqual(packet["monster_content_failure"]["unresolved_reference"]["normalized"], "cave_guardians")
        self.assertEqual(packet["monster_content_failure"]["scene_evidence"][0]["location_id"], "K08")
        self.assertNotEqual(result["adaptation_revision"]["attempt_id"], old_target["attempt_id"] + ":revision_000")
        self.assertFalse((self.root / "modules").exists())

    def test_ineligible_failure_does_not_call_route(self) -> None:
        result = _route_adaptation_monster_revision(
            build_result={"status": "blocked"},
            guardrail_report={"unresolved_refs": ["invented"]},
            classification={"failure_class": "file", "revision_eligible": False, "revision_budget": {"max_revisions": 1}},
            adaptation_handoff=self.handoff,
            staging_target={"revision_number": 0},
            workspace=self.root,
            job_id="amphail-job",
            staging_root="tmp/toolkit_adaptation_monster_revision_route/staging",
            module_slug="Amphail",
            revision_callback=self._callback,
        )
        self.assertIsNone(result)
        self.assertEqual(self.calls, [])

    def test_accepted_monster_operation_reenters_full_pipeline(self) -> None:
        old_target = {
            "path": "tmp/adaptation-staging/adapt-amphail/revision_000",
            "attempt_id": "adapt-amphail",
            "attempt_number": 1,
            "revision_number": 0,
            "source_hash": self.source_hash,
        }
        stages = []
        report = {
            "unresolved_refs": ["cave_guardians"],
            "approved_monster_identities": ["Cave Guardian"],
            "source_reference_ids": ["K08"],
        }

        def rerun(target, operation):
            stages.extend(["normalization", "materialization", "closure", "spatial", "semantic", "readiness", "gameplay", "report_agreement", "markdown", "registry", "campaign", "rollback"])
            self.assertEqual(target["revision_number"], 1)
            self.assertEqual(operation["target"]["canonical_identity"], "Cave Guardian")
            return {
                "status": "success",
                "staging_target": dict(target),
                "publication_attempted": False,
            }

        result = _route_adaptation_monster_revision(
            build_result={"status": "blocked"},
            guardrail_report=report,
            classification={
                "failure_class": "semantic",
                "code": "monster_closure_unresolved",
                "revision_eligible": True,
                "semantic_revision_eligible": True,
                "revision_budget": {
                    "current_revision": 0,
                    "max_revisions": 1,
                    "remaining_before_failure": 1,
                },
            },
            adaptation_handoff=self.handoff,
            staging_target=old_target,
            workspace=self.root,
            job_id="amphail-job",
            staging_root="tmp/toolkit_adaptation_monster_revision_route/staging",
            module_slug="Amphail",
            revision_callback=self._callback,
            rerun_callback=rerun,
        )
        self.assertEqual(result["status"], "success", result)
        self.assertTrue(result["adaptation_revision"]["full_pipeline_rerun"])
        self.assertEqual(result["adaptation_revision"]["pre_revision_status"], "adaptation_revision_required")
        self.assertEqual(result["adaptation_revision"]["staging_target"]["revision_number"], 1)
        self.assertEqual(stages[0], "normalization")
        self.assertEqual(stages[-1], "rollback")
        self.assertNotEqual(result["adaptation_revision"]["prior_staging_target"]["path"], result["staging_target"]["path"])

    def test_failed_rerun_reports_exhaustion_only_after_budget(self) -> None:
        old_target = {
            "path": "tmp/adaptation-staging/adapt-amphail/revision_000",
            "attempt_id": "adapt-amphail",
            "attempt_number": 1,
            "revision_number": 0,
            "source_hash": self.source_hash,
        }
        result = _route_adaptation_monster_revision(
            build_result={"status": "blocked"},
            guardrail_report={"unresolved_refs": ["cave_guardians"], "approved_monster_identities": ["Cave Guardian"], "source_reference_ids": ["K08"]},
            classification={
                "failure_class": "semantic",
                "code": "monster_closure_unresolved",
                "revision_eligible": True,
                "semantic_revision_eligible": True,
                "revision_budget": {"current_revision": 0, "max_revisions": 1, "remaining_before_failure": 1},
            },
            adaptation_handoff=self.handoff,
            staging_target=old_target,
            workspace=self.root,
            job_id="amphail-job",
            staging_root="tmp/toolkit_adaptation_monster_revision_route/staging",
            module_slug="Amphail",
            revision_callback=self._callback,
            rerun_callback=lambda target, operation: {"status": "blocked", "staging_target": dict(target)},
        )
        self.assertEqual(result["error"], "adaptation_revision_exhausted")
        self.assertFalse(result["next_revision_eligible"])
        self.assertEqual(result["revision_budget"]["remaining_revisions"], 0)


if __name__ == "__main__":
    unittest.main()
