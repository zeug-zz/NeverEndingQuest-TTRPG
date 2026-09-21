# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for adaptation-aware source-fidelity reporting."""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_gate_composer import (
    GATE_MECHANICAL_CLOSURE,
    GATE_READINESS,
    GATE_REPORT_AGREEMENT,
    GATE_SCHEMA,
    GATE_SEMANTIC_AUTHORITY,
    GATE_SEMANTIC_PROBES,
    compose_adaptation_gate_result,
    run_adaptation_gate_composer,
)
from utils.toolkit_adaptation_source_fidelity import (
    ADAPTATION_MODE_LLM,
    ADAPTATION_SOURCE_FIDELITY_STATUS,
    build_adaptation_source_fidelity_report,
    evaluate_adaptation_source_fidelity,
    validate_adaptation_source_fidelity_report,
)
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
from utils.toolkit_publication_gate_composer import compose_publication_gate
from utils.toolkit_report_agreement import (
    compose_report_agreement,
    compose_report_agreement_from_module_dir,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "tmp" / "toolkit_adaptation_source_fidelity_contract"
SOURCE_HASH = "c" * 64


def _passing_reports():
    return {
        GATE_SCHEMA: {"status": "pass", "exit_code": 0},
        GATE_READINESS: {"status": "pass"},
        GATE_MECHANICAL_CLOSURE: {"status": "pass"},
        GATE_SEMANTIC_AUTHORITY: {"status": "pass"},
        GATE_SEMANTIC_PROBES: {"status": "pass"},
        GATE_REPORT_AGREEMENT: {
            "status": "pass",
            "playable_publication_status": "pass",
        },
    }


class TestAdaptationSourceFidelityReport(unittest.TestCase):
    def setUp(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)

    def _target(self, job_id: str = "source-fidelity"):
        return create_adaptation_staging_target(
            SOURCE_HASH,
            job_id=job_id,
            attempt_number=1,
            revision_number=0,
            module_slug="Source_Fidelity_Fixture",
            staging_root="tmp/toolkit_adaptation_source_fidelity_contract/staging",
            repo_root=REPO_ROOT,
        )

    def _patch_runners(self):
        import utils.toolkit_adaptation_gate_composer as composer

        return [
            patch.object(composer, "_run_schema_gate", return_value={"status": "pass"}),
            patch.object(composer, "_run_gameplay_gate", return_value={"status": "pass"}),
            patch.object(composer, "_run_continuity_gate", return_value={"status": "pass"}),
            patch.object(composer, "_run_mechanical_closure_gate", return_value={"status": "pass"}),
            patch.object(composer, "_run_semantic_authority_gate", return_value={"status": "pass"}),
            patch.object(composer, "_run_semantic_probe_gate", return_value={"status": "pass"}),
        ]

    def test_literal_mismatch_is_informational_with_bounded_provenance(self):
        report = build_adaptation_source_fidelity_report(
            source_fidelity_evidence={
                "source_fidelity_status": "blocked",
                "categories": [
                    {
                        "category": "location_preservation",
                        "status": "blocked",
                        "message": "Source location was intentionally reframed.",
                    }
                ],
                "report_freshness": {"state": "current"},
            },
            attempt_metadata={
                "attempt_id": "attempt-source-fidelity",
                "attempt_number": 1,
                "revision_number": 0,
                "source_hash": SOURCE_HASH,
                "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
                "source_format": "markdown",
            },
            staging_target={"stage_id": "stage-source-fidelity"},
            module_slug="Source_Fidelity_Fixture",
            checked_at="2026-08-04T00:00:00Z",
        )

        self.assertEqual(report["source_fidelity_status"], ADAPTATION_SOURCE_FIDELITY_STATUS)
        self.assertTrue(report["informational"])
        self.assertFalse(report["literal_source_fidelity_required"])
        self.assertEqual(report["report_agreement"]["status"], "pass_through")
        self.assertFalse(report["report_agreement"]["blocking"])
        self.assertTrue(report["literal_mismatch_evidence"])
        self.assertEqual(report["provenance"]["attempt_id"], "attempt-source-fidelity")
        self.assertEqual(report["provenance"]["stage_id"], "stage-source-fidelity")
        self.assertEqual(report["checked_at"], "2026-08-04T00:00:00Z")
        self.assertTrue(validate_adaptation_source_fidelity_report(report)["valid"])

    def test_adaptation_evaluation_distinguishes_not_applicable_from_unknown(self):
        not_applicable = evaluate_adaptation_source_fidelity(
            source_fidelity_evidence="blocked",
            checked_at="2026-08-04T00:00:00Z",
        )
        unknown = evaluate_adaptation_source_fidelity(
            source_fidelity_evidence="unknown",
            checked_at="2026-08-04T00:00:00Z",
        )

        self.assertEqual(not_applicable["source_fidelity_status"], "not_applicable")
        self.assertEqual(not_applicable["effective_status"], "pass_through")
        self.assertEqual(
            not_applicable["report"]["evidence"]["source_fidelity_status"],
            "blocked",
        )
        self.assertEqual(unknown["source_fidelity_status"], "not_applicable")
        self.assertEqual(
            unknown["report"]["evidence"]["source_fidelity_status"], "unknown"
        )
        self.assertNotEqual(
            not_applicable["report"]["evidence"]["source_fidelity_status"],
            unknown["report"]["evidence"]["source_fidelity_status"],
        )

    def test_mixed_adaptation_failures_still_block(self):
        target = self._target("mixed-adaptation-failures")
        source_report = build_adaptation_source_fidelity_report(
            source_fidelity_evidence={
                "source_fidelity_status": "blocked",
                "categories": [{"category": "npc_preservation", "status": "blocked"}],
            },
            staging_target=target,
            module_slug="Source_Fidelity_Fixture",
            checked_at="2026-08-04T00:00:00Z",
        )
        reports = _passing_reports()
        reports[GATE_SCHEMA] = {
            "status": "blocked",
            "errors": ["schema validation failed"],
        }
        reports[GATE_REPORT_AGREEMENT] = {
            "status": "pass",
            "playable_publication_status": "pass",
            "source_fidelity_status": "not_applicable",
            "source_fidelity_report": source_report,
        }

        result = compose_adaptation_gate_result(
            reports,
            staging_target=target,
            module_dir=REPO_ROOT / target["path"],
            repo_root=REPO_ROOT,
        )

        self.assertEqual(result["source_fidelity_status"], "not_applicable")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["playable_status"], "blocked")
        self.assertTrue(any("schema" in item for item in result["errors"]))
        self.assertFalse(result["candidate_eligible"])

    def test_malformed_source_report_blocks_adaptation_report_agreement(self):
        target = self._target("malformed-source-report")
        module_dir = REPO_ROOT / target["path"]
        (module_dir / "source_fidelity_report.json").write_text(
            "{malformed", encoding="utf-8"
        )
        patches = self._patch_runners()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = run_adaptation_gate_composer(
                target,
                module_dir=module_dir,
                repo_root=REPO_ROOT,
            )

        report_gate = result["gates"][GATE_REPORT_AGREEMENT]
        self.assertEqual(result["source_fidelity_status"], "not_applicable")
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(
            any("source_fidelity_report_malformed" in item for item in report_gate["blockers"])
        )

    def test_stale_source_report_cannot_be_hidden_by_not_applicable(self):
        target = self._target("stale-source-report")
        module_dir = REPO_ROOT / target["path"]
        (module_dir / "source_fidelity_report.json").write_text(
            '{"source_fidelity_status":"blocked",'
            '"report_freshness":{"state":"stale"}}',
            encoding="utf-8",
        )
        patches = self._patch_runners()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = run_adaptation_gate_composer(
                target,
                module_dir=module_dir,
                repo_root=REPO_ROOT,
            )

        report_gate = result["gates"][GATE_REPORT_AGREEMENT]
        self.assertEqual(result["source_fidelity_status"], "not_applicable")
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(
            any("source_fidelity_evidence_stale" in item for item in report_gate["blockers"])
        )
        self.assertEqual(
            result["source_fidelity_report"]["evidence"]["freshness_state"],
            "stale",
        )

    def test_report_is_deterministic_when_checked_at_is_fixed(self):
        kwargs = {
            "source_fidelity_evidence": {
                "source_fidelity_status": "degraded",
                "category_results": [
                    {"category": "tone_preservation", "status": "degraded"}
                ],
            },
            "attempt_metadata": {
                "attempt_id": "attempt-deterministic",
                "source_hash": SOURCE_HASH,
                "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
            },
            "staging_target": {"stage_id": "stage-deterministic"},
            "module_slug": "Source_Fidelity_Fixture",
            "checked_at": "2026-08-04T00:00:00Z",
        }
        first = build_adaptation_source_fidelity_report(**kwargs)
        second = build_adaptation_source_fidelity_report(**kwargs)
        self.assertEqual(first, second)

    def test_report_agreement_accepts_current_adaptation_report_only(self):
        (WORKSPACE / "validation_report.json").write_text(
            '{"status":"pass"}', encoding="utf-8"
        )
        (WORKSPACE / "source_fidelity_report.json").write_text(
            '{"source_fidelity_status":"not_applicable",'
            '"adaptation_mode":"llm_adaptation",'
            '"report_freshness":{"state":"current"}}',
            encoding="utf-8",
        )
        (WORKSPACE / "toolkit_build_report.json").write_text(
            '{"status":"pass","ready_status":"pass",'
            '"publishable_status":"pass",'
            '"effective_publishable_status":"pass"}',
            encoding="utf-8",
        )
        result = compose_report_agreement_from_module_dir(WORKSPACE)
        self.assertEqual(result["source_fidelity_status"], "not_applicable")
        self.assertEqual(result["source_fidelity_mode"], ADAPTATION_MODE_LLM)
        self.assertEqual(result["playable_publication_status"], "pass")

        (WORKSPACE / "source_fidelity_report.json").write_text(
            '{"source_fidelity_status":"not_applicable",'
            '"adaptation_mode":"llm_adaptation",'
            '"report_freshness":{"state":"stale"}}',
            encoding="utf-8",
        )
        stale = compose_report_agreement_from_module_dir(WORKSPACE)
        self.assertEqual(stale["playable_publication_status"], "blocked")
        self.assertIn("source_fidelity", stale["stale_reports"])

    def test_legacy_fidelity_statuses_remain_separate(self):
        blocked = compose_publication_gate("pass", "pass", "blocked")
        degraded = compose_publication_gate("pass", "pass", "degraded")
        legacy_not_applicable = compose_publication_gate(
            "pass", "pass", "not_applicable"
        )
        adaptation_not_applicable = compose_publication_gate(
            "pass",
            "pass",
            "not_applicable",
            source_fidelity_mode=ADAPTATION_MODE_LLM,
        )

        self.assertTrue(blocked["blocked"])
        self.assertTrue(degraded["degraded"])
        self.assertTrue(legacy_not_applicable["blocked"])
        self.assertTrue(adaptation_not_applicable["publishable"])
        self.assertEqual(
            adaptation_not_applicable["source_fidelity_status_effective"],
            "not_applicable",
        )

        legacy_agreement = compose_report_agreement(
            source_fidelity_status="blocked",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
        )
        adaptation_agreement = compose_report_agreement(
            source_fidelity_status="not_applicable",
            validation_status="pass",
            ready_status="pass",
            publishable_status="pass",
            effective_publishable_status="pass",
            toolkit_top_level_status="pass",
            source_fidelity_mode=ADAPTATION_MODE_LLM,
        )
        self.assertEqual(legacy_agreement["playable_publication_status"], "blocked")
        self.assertEqual(adaptation_agreement["source_fidelity_status"], "not_applicable")
        self.assertEqual(adaptation_agreement["playable_publication_status"], "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
