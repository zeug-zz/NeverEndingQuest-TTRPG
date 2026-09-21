# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free task 9.2 tests for adaptation report correlation."""

from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_module_finisher as finisher
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_BUILD_RESULT,
    ARTIFACT_KIND_PUBLICATION_REPORT,
    BUILD_STATUS_PASSED,
    PUBLICATION_STATUS_PENDING,
    PUBLICATION_STATUS_PUBLISHED,
    build_build_result_artifact,
    build_publication_report_artifact,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
    persist_adaptation_artifact,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
from utils.toolkit_report_agreement import (
    compose_adaptation_report_agreement,
    compose_adaptation_report_identity_agreement,
)
from utils.toolkit_adaptation_publication_convergence import (
    run_adaptation_publication_convergence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASH = "d" * 64


def _passing_gates() -> dict:
    domains = (
        "schema",
        "readiness",
        "mechanical_closure",
        "semantic_authority",
        "semantic_probes",
        "report_agreement",
    )
    gates = {
        domain: {"status": "pass", "effective_status": "pass"}
        for domain in domains
    }
    gates["report_agreement"].update(
        {
            "playable_publication_status": "pass",
            "agreement": {"playable_publication_status": "pass"},
        }
    )
    return {
        "status": "pass",
        "playable_status": "pass",
        "candidate_eligible": True,
        "gates": gates,
    }


class AdaptationReportAgreementFixture(unittest.TestCase):
    """Exercise stable identity, freshness, and finisher persistence."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_report_agreement_",
        )
        self.root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.target = create_adaptation_staging_target(
            SOURCE_HASH,
            job_id="report-agreement",
            attempt_number=1,
            revision_number=0,
            module_slug="Adaptation_Report_Fixture",
            staging_root="tmp/adaptation-staging",
            repo_root=self.root,
        )
        self.module_dir = self.root / self.target["path"]
        self.workspace = self.root / "tmp" / "adaptation-artifacts"
        self.provenance = {
            "source_title": "The Lantern Catalogue",
            "source_hash": SOURCE_HASH,
            "source_path": "user_uploads/lantern_catalogue.md",
            "rights_classification": "user_authored",
            "rights_basis": "fixture source",
            "rights_review_required": False,
            "rights_review_status": "not_required",
            "attempt_id": self.target["attempt_id"],
            "attempt_number": 1,
            "revision_number": 0,
            "model_metadata": {"provider": "fixture", "model": "provider_free"},
        }
        attempt = build_build_result_artifact(
            attempt_id=self.target["attempt_id"],
            source_title=self.provenance["source_title"],
            source_hash=SOURCE_HASH,
            source_path=self.provenance["source_path"],
            staging_path=self.target["path"],
            build_status=BUILD_STATUS_PASSED,
            module_slug="Adaptation_Report_Fixture",
            revision_number=0,
        )
        self.assertTrue(persist_adaptation_artifact(self.workspace, attempt))

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _publication(self, source_hash: str = SOURCE_HASH, status: str = PUBLICATION_STATUS_PUBLISHED):
        return build_publication_report_artifact(
            attempt_id=self.target["attempt_id"],
            source_title=self.provenance["source_title"],
            source_hash=source_hash,
            source_path=self.provenance["source_path"],
            readiness_evidence={
                "schema": {"status": "pass"},
                "readiness": {"status": "pass"},
                "report_agreement": {"status": "pass"},
            },
            registry_evidence={
                "status": "pass" if status == PUBLICATION_STATUS_PUBLISHED else "not_run",
                "verified": status == PUBLICATION_STATUS_PUBLISHED,
            },
            publication_status=status,
            published_at="2026-08-04T12:00:00Z"
            if status == PUBLICATION_STATUS_PUBLISHED
            else None,
        )

    def test_current_correlated_reports_agree(self):
        publication = self._publication()
        agreement = compose_adaptation_report_agreement(
            load_adaptation_artifact(
                self.workspace,
                self.target["attempt_id"],
                ARTIFACT_KIND_BUILD_RESULT,
            ),
            publication,
            expected_attempt_id=self.target["attempt_id"],
            expected_source_hash=SOURCE_HASH,
            expected_revision_number=0,
            require_publication=True,
            completion_claim={
                "status": "success",
                "adaptation_mode": "llm_adaptation",
                "report_freshness": {"state": "current"},
            },
        )
        self.assertEqual(agreement["status"], "pass", agreement)
        self.assertTrue(agreement["published_claim_verified"])

    def test_stale_attempt_report_blocks_completion(self):
        attempt_path = get_adaptation_artifact_path(
            self.workspace, self.target["attempt_id"], ARTIFACT_KIND_BUILD_RESULT
        )
        attempt = load_adaptation_artifact(
            self.workspace, self.target["attempt_id"], ARTIFACT_KIND_BUILD_RESULT
        )
        self.assertIsNotNone(attempt)
        stale_attempt = copy.deepcopy(attempt)
        stale_attempt["report_freshness"]["state"] = "stale"
        stale_attempt["report_freshness"]["authoritative"] = False
        attempt_path.unlink()
        self.assertTrue(persist_adaptation_artifact(self.workspace, stale_attempt))

        agreement = compose_adaptation_report_agreement(
            stale_attempt,
            self._publication(),
            expected_attempt_id=self.target["attempt_id"],
            expected_source_hash=SOURCE_HASH,
            expected_revision_number=0,
            require_publication=True,
        )
        self.assertEqual(agreement["status"], "blocked")
        self.assertIn("stale_report:attempt:stale", agreement["blockers"])

    def test_source_mismatch_blocks_completion(self):
        agreement = compose_adaptation_report_agreement(
            load_adaptation_artifact(
                self.workspace,
                self.target["attempt_id"],
                ARTIFACT_KIND_BUILD_RESULT,
            ),
            self._publication(source_hash="e" * 64),
            expected_attempt_id=self.target["attempt_id"],
            expected_source_hash=SOURCE_HASH,
            expected_revision_number=0,
            require_publication=True,
        )
        self.assertEqual(agreement["status"], "blocked")
        self.assertTrue(
            any("source_hash_mismatch" in blocker for blocker in agreement["blockers"])
        )

    def test_adaptation_status_keeps_source_fidelity_informational(self):
        from utils.toolkit_report_agreement import compose_report_agreement

        agreement = compose_report_agreement(
            source_fidelity_status="not_applicable",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
            source_fidelity_mode="llm_adaptation",
        )
        self.assertEqual(agreement["playable_publication_status"], "pass")
        self.assertEqual(agreement["publishable_status"], "pass")
        self.assertEqual(agreement["source_fidelity_status"], "not_applicable")

        blocked = compose_report_agreement(
            source_fidelity_status="not_applicable",
            validation_status="blocked",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
            source_fidelity_mode="llm_adaptation",
        )
        self.assertEqual(blocked["playable_publication_status"], "blocked")

    def test_finisher_persists_publication_report_and_agreement(self):
        with patch.object(
            finisher,
            "_run_adaptation_provenance_stage",
            return_value={"status": "success", "reason": "fixture"},
        ), patch.object(
            finisher,
            "_run_module_summary_stage",
            return_value={"status": "success", "quality": {"valid": True}},
        ), patch.object(
            finisher,
            "_run_registry_stage",
            return_value={
                "status": "success",
                "integration_attempted": True,
                "verified": True,
                "campaign_sync": {
                    "status": "deferred",
                    "reason": "no_active_campaign",
                    "campaign_visibility_verified": False,
                },
            },
        ):
            result = finisher.run_toolkit_module_postbuild_finishing(
                "Adaptation_Report_Fixture",
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_gates(),
                adaptation_staging_target=self.target,
                adaptation_module_dir=str(self.module_dir),
                adaptation_provenance=self.provenance,
                adaptation_artifact_workspace=str(self.workspace),
            )

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(
            result["adaptation_report_agreement"]["status"], "pass", result
        )
        publication = load_adaptation_artifact(
            self.workspace,
            self.target["attempt_id"],
            ARTIFACT_KIND_PUBLICATION_REPORT,
        )
        self.assertIsNotNone(publication)
        self.assertEqual(
            publication["payload"]["publication_status"], PUBLICATION_STATUS_PUBLISHED
        )
        self.assertEqual(publication["provenance"]["source_hash"], SOURCE_HASH)
        self.assertEqual(
            publication["report_freshness"]["state"], "current"
        )

    def test_current_attempt_identity_is_shared_by_all_adaptation_reports(self):
        """The production callback/convergence seam feeds one report identity."""
        callback_reports = []

        def callback(context):
            result = {
                "status": "success",
                "reason_code": "no_repairable_blocker",
                "attempt_id": context["attempt_id"],
                "attempt_number": context["attempt_number"],
                "revision_number": context["revision_number"],
                "source_hash": context["source_hash"],
                "staging_identity": dict(context["staging_identity"]),
            }
            callback_reports.append(result)
            return result

        convergence = run_adaptation_publication_convergence(
            str(self.module_dir),
            mode="llm_adaptation",
            attempt_id=self.target["attempt_id"],
            attempt_number=self.target["attempt_number"],
            revision_number=self.target["revision_number"],
            source_hash=SOURCE_HASH,
            provider_callback=callback,
            repo_root=self.root,
        )
        self.assertEqual(convergence["status"], "ready", convergence)
        self.assertEqual(len(callback_reports), 1)
        convergence_report = dict(
            convergence,
            staging_identity={
                "path": self.target["path"],
                "output_directory": self.target["path"],
            },
            report_freshness={"state": "current", "authoritative": True},
        )
        identity = {
            "attempt_id": self.target["attempt_id"],
            "attempt_number": self.target["attempt_number"],
            "revision_number": self.target["revision_number"],
            "source_hash": SOURCE_HASH,
            "staging_path": self.target["path"],
        }
        reports = {
            "callback": callback_reports[0],
            "convergence": convergence_report,
        }
        for label in ("validation", "readiness", "semantic", "gameplay", "publication"):
            reports[label] = {
                **identity,
                "report_freshness": {"state": "current", "authoritative": True},
            }

        agreement = compose_adaptation_report_identity_agreement(
            reports, expected_identity=identity
        )
        self.assertEqual(agreement["status"], "pass", agreement)
        self.assertTrue(agreement["publication_allowed"])
        self.assertEqual(set(agreement["report_identities"]), set(reports))
        self.assertEqual(
            agreement["current_identity"]["staging_path"], self.target["path"]
        )
        self.assertNotIn("provider_payload", str(agreement))

    def test_any_report_identity_mismatch_blocks_publication(self):
        identity = {
            "attempt_id": self.target["attempt_id"],
            "attempt_number": self.target["attempt_number"],
            "revision_number": self.target["revision_number"],
            "source_hash": SOURCE_HASH,
            "staging_path": self.target["path"],
        }
        reports = {
            label: {
                **identity,
                "report_freshness": {"state": "current", "authoritative": True},
            }
            for label in (
                "callback",
                "convergence",
                "validation",
                "readiness",
                "semantic",
                "gameplay",
                "publication",
            )
        }
        for label, field, value in (
            ("callback", "attempt_id", "stale-callback"),
            ("convergence", "attempt_number", 2),
            ("validation", "revision_number", 1),
            ("readiness", "source_hash", "e" * 64),
            ("semantic", "staging_path", "tmp/adaptation-staging/other/revision_000"),
            ("gameplay", "attempt_id", "other-gameplay"),
            ("publication", "revision_number", 9),
        ):
            with self.subTest(label=label, field=field):
                mismatched = copy.deepcopy(reports)
                mismatched[label][field] = value
                agreement = compose_adaptation_report_identity_agreement(
                    mismatched, expected_identity=identity
                )
                self.assertEqual(agreement["status"], "blocked", agreement)
                self.assertFalse(agreement["publication_allowed"])
                self.assertIn(
                    "identity_mismatch:%s:%s" % (label, field),
                    agreement["blockers"],
                )

        stale = copy.deepcopy(reports)
        stale["readiness"]["report_freshness"] = {
            "state": "stale",
            "authoritative": False,
        }
        agreement = compose_adaptation_report_identity_agreement(
            stale, expected_identity=identity
        )
        self.assertEqual(agreement["status"], "blocked", agreement)
        self.assertFalse(agreement["publication_allowed"])
        self.assertIn("readiness", agreement["stale_reports"])
        self.assertIn("stale_report:readiness", agreement["blockers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
