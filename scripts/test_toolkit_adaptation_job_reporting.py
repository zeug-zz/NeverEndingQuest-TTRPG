# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free task 9.1 tests for adaptation job reporting and GUI routing."""

from pathlib import Path
import json
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from web.extensions.toolkit_adaptation_job_reporting import (  # noqa: E402
    ADAPTATION_JOB_STATUS_BLOCKED,
    ADAPTATION_JOB_STATUS_COMPLETED,
    ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED,
    ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED,
    ADAPTATION_JOB_STATUS_REVISION_REQUIRED,
    ADAPTATION_OUTCOME_BLOCKED,
    ADAPTATION_OUTCOME_COMPLETED,
    ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE,
    ADAPTATION_OUTCOME_REVISION_EXHAUSTED,
    ADAPTATION_OUTCOME_SEMANTIC_REVISION,
    build_adaptation_job_status,
    normalize_adaptation_progress_stage,
    sanitize_adaptation_job_for_public,
)
from web.extensions.toolkit_homebrew_packet_builder import (  # noqa: E402
    _adaptation_failure_classification,
    _adaptation_revision_projection,
    _apply_adaptation_continuation_failure,
)
from web.routes.toolkit_homebrew_routes import (  # noqa: E402
    _get_canonical_accurate_ingest_phase,
    _refresh_adaptation_job_state,
)


def _adaptation_job(status: str, result: dict, **fields: object) -> dict:
    return {
        "job_id": "adaptation-job-001",
        "status": status,
        "stage": fields.pop("stage", "build"),
        "pipeline_status": fields.pop("pipeline_status", status),
        "adaptation_mode": "llm_adaptation",
        "result": {"adaptation_mode": "llm_adaptation", **result},
        **fields,
    }


class TestAdaptationPhaseMapping(unittest.TestCase):
    def test_progress_text_maps_to_adaptation_phases(self) -> None:
        cases = {
            ("log", "Authoring adaptation dossier"): "adaptation_authoring",
            ("log", "Running semantic adaptation audit"): "adaptation_semantic_audit",
            ("log", "Building revised adaptation in fresh staging"): "adaptation_revision_build",
            ("log", "Checking readable MODULE_SUMMARY.md"): "adaptation_markdown",
            ("log", "Verifying registry publication"): "adaptation_registry",
            ("log", "Rolling back failed publication"): "adaptation_rollback",
        }
        for signals, expected in cases.items():
            with self.subTest(signals=signals):
                self.assertEqual(normalize_adaptation_progress_stage(*signals), expected)

    def test_route_dispatches_adaptation_without_changing_legacy_phase(self) -> None:
        adaptation_phase = _get_canonical_accurate_ingest_phase(
            {
                "status": "building",
                "stage": "authoring",
                "adaptation_mode": "llm_adaptation",
            }
        )
        self.assertEqual(adaptation_phase, "adaptation_authoring")

        legacy_phase = _get_canonical_accurate_ingest_phase(
            {
                "status": "building",
                "stage": "build",
                "progress_stage": "builder_areas",
            }
        )
        self.assertEqual(legacy_phase, "building_blueprint")


class TestAdaptationTerminalOutcomes(unittest.TestCase):
    def test_raw_publication_continuation_failure_uses_terminal_fallback(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "blocked",
                {
                    "status": "blocked",
                    "stage": "adaptation_publication_continuation",
                    "error": "adaptation_publication_inputs_disagree",
                    "adaptation_convergence": {
                        "status": "ready",
                        "reason_code": "callback_success",
                    },
                    "adaptation_publication_continuation": {
                        "allowed": False,
                        "blockers": [
                            "attempt_report_identity_mismatch",
                            "semantic_authority_identity_mismatch",
                        ],
                    },
                },
                stage="build_fidelity",
            )
        )
        self.assertEqual(report["failure_code"], "adaptation_publication_inputs_disagree")
        self.assertEqual(report["failed_stage"], "adaptation_publication_continuation")
        self.assertEqual(report["failure_class"], "publication")
        self.assertEqual(report["failure_surface"], "publication")
        self.assertEqual(report["retry_diagnostics"]["status"], "not_retryable")
        diagnostics = report["failure_diagnostics"]
        self.assertTrue(diagnostics)
        diagnostic_text = json.dumps(diagnostics, sort_keys=True)
        for marker in (
            "adaptation_publication_inputs_disagree",
            "attempt_report_identity_mismatch",
            "semantic_authority_identity_mismatch",
        ):
            self.assertIn(marker, diagnostic_text)
        self.assertNotIn("callback_success", diagnostic_text)

    def test_blocked_publication_continuation_projects_concrete_failure(self) -> None:
        result = {"status": "success", "stage": "build_fidelity"}
        _apply_adaptation_continuation_failure(
            result,
            {
                "allowed": False,
                "status": "blocked",
                "reason_code": "publication_inputs_disagree",
                "blockers": ["gate_result_identity_mismatch", "convergence_not_ready"],
            },
            error_code="adaptation_publication_inputs_disagree",
        )
        self.assertEqual(result["failure_code"], "adaptation_publication_inputs_disagree")
        self.assertEqual(result["failed_stage"], "adaptation_publication_continuation")
        self.assertEqual(result["failure_class"], "publication")
        self.assertEqual(result["failure_domain"], "publication")
        self.assertFalse(result["revision_eligible"])
        self.assertFalse(result["next_revision_eligible"])
        self.assertTrue(result["failure_diagnostics"])
        self.assertLessEqual(len(result["failure_diagnostics"]), 12)
        projection = _adaptation_revision_projection(result)
        self.assertEqual(projection["failure_code"], result["failure_code"])
        self.assertEqual(projection["failed_stage"], result["failed_stage"])
        self.assertFalse(projection["next_revision_eligible"])
        report = build_adaptation_job_status(
            _adaptation_job(
                "blocked",
                {
                    **result,
                    "adaptation_convergence": {
                        "status": "success",
                        "reason_code": "callback_success",
                    },
                },
                stage="build_fidelity",
            )
        )
        self.assertEqual(report["failure_code"], "adaptation_publication_inputs_disagree")
        self.assertEqual(report["retry_diagnostics"]["status"], "not_retryable")
        self.assertTrue(report["failure_diagnostics"])

    def test_continuation_exception_cannot_project_callback_success(self) -> None:
        job = _adaptation_job(
            "blocked",
            {
                "status": "blocked",
                "stage": "adaptation_publication_continuation",
                "error": "adaptation_publication_continuation_exception",
                "failure_code": "adaptation_publication_continuation_exception",
                "failure_class": "publication",
                "failure_group": "publication",
                "failure_domain": "publication",
                "failed_stage": "adaptation_publication_continuation",
                "revision_eligible": False,
                "semantic_revision_eligible": False,
                "next_revision_eligible": False,
                "failure_diagnostics": [
                    {"code": "adaptation_publication_continuation_exception", "message": "ValueError"}
                ],
                "adaptation_convergence": {
                    "status": "success",
                    "reason_code": "callback_success",
                },
            },
            stage="build_fidelity",
        )
        report = build_adaptation_job_status(job)
        self.assertEqual(report["failure_code"], "adaptation_publication_continuation_exception")
        self.assertEqual(report["failure_class"], "publication")
        self.assertEqual(report["retry_diagnostics"]["failed_stage"], "adaptation_publication_continuation")
        self.assertFalse(report["revision_eligible"])
        self.assertFalse(report["next_revision_eligible"])
        self.assertTrue(report["failure_diagnostics"])
        self.assertNotEqual(report["failure_code"], "callback_success")

    def test_route_projects_terminal_status_into_adaptation_job_state(self) -> None:
        job = _adaptation_job(
            "blocked",
            {
                "failure_classification": {
                    "failure_class": "semantic",
                    "failure_group": "content",
                    "code": "semantic_gate_failed",
                    "semantic_revision_eligible": True,
                    "consumes_semantic_revision_budget": True,
                    "revision_budget": {
                        "current_revision": 0,
                        "max_revisions": 1,
                        "remaining_before_failure": 1,
                    },
                }
            },
            stage="adaptation_semantic_audit",
        )
        _refresh_adaptation_job_state(job)
        self.assertEqual(job["status"], ADAPTATION_JOB_STATUS_REVISION_REQUIRED)
        self.assertEqual(job["adaptation_phase"], "adaptation_revision")
        self.assertEqual(job["adaptation_retry_diagnostics"]["status"], "available")

    def test_infrastructure_failure_does_not_consume_revision_budget(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "failed",
                {
                    "failure_classification": {
                        "failure_class": "timeout",
                        "failure_group": "infrastructure",
                        "code": "provider_timeout",
                        "revision_number": 0,
                        "max_revisions": 1,
                    }
                },
                stage="authoring",
            )
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED)
        self.assertTrue(report["terminal"])
        self.assertEqual(report["retry_diagnostics"]["status"], "not_consumed")
        self.assertFalse(report["retry_diagnostics"]["semantic_revision_budget_consumed"])

    def test_semantic_failure_exposes_bounded_revision_retry(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "blocked",
                {
                    "failure_classification": {
                        "failure_class": "semantic",
                        "failure_group": "content",
                        "code": "semantic_gate_failed",
                        "semantic_revision_eligible": True,
                        "consumes_semantic_revision_budget": False,
                        "revision_budget": {
                            "current_revision": 0,
                            "max_revisions": 1,
                            "remaining_before_failure": 1,
                            "decision": "eligible",
                        },
                    }
                },
                stage="adaptation_semantic_audit",
            )
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_SEMANTIC_REVISION)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_REVISION_REQUIRED)
        self.assertEqual(report["retry_diagnostics"]["status"], "available")
        self.assertFalse(report["retry_diagnostics"]["semantic_revision_budget_consumed"])
        self.assertTrue(report["raw_provider_payload_exposed"] is False)

    def test_revision_exhaustion_is_distinct_from_semantic_retry(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "failed",
                {
                    "failure_classification": {
                        "failure_class": "semantic",
                        "failure_group": "content",
                        "code": "revision_budget_exhausted",
                        "semantic_revision_eligible": False,
                        "revision_budget": {
                            "current_revision": 1,
                            "max_revisions": 1,
                            "remaining_before_failure": 0,
                            "decision": "exhausted",
                        },
                    }
                },
                stage="revision_build",
            )
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_REVISION_EXHAUSTED)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED)
        self.assertEqual(report["retry_diagnostics"]["status"], "exhausted")

    def test_publication_and_rollback_failure_are_blocked(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "failed",
                {
                    "failure_classification": {
                        "failure_class": "publication",
                        "failure_group": "publication",
                        "code": "registry_verification_failed",
                    },
                    "stages": {
                        "registry": {"status": "blocked"},
                        "publication_rollback": {"status": "success"},
                    },
                },
                stage="registry",
            )
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_BLOCKED)
        self.assertEqual(report["failure_surface"], "publication")
        self.assertTrue(report["terminal"])

    def test_completed_requires_verified_python_publication(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "completed",
                {
                    "status": "success",
                    "publication_status": "completed",
                    "terminal_status": "completed",
                    "python_authoritative": True,
                    "llm_publication_override": False,
                    "stages": {
                        "registry": {"status": "success", "verified": True},
                        "campaign_sync": {"status": "deferred"},
                    },
                },
            )
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_COMPLETED)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_COMPLETED)
        self.assertEqual(report["phase"], "adaptation_completed")

        unverifiable = build_adaptation_job_status(
            _adaptation_job("completed", {"status": "success"})
        )
        self.assertEqual(unverifiable["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(unverifiable["failure_surface"], "completion_verification")

    def test_blocked_readiness_gate_maps_to_adaptation_blocked(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "repair_budget_exhausted",
                {"status": "repair_budget_exhausted", "module_name": "Fixture"},
                stage="readiness",
            )
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_BLOCKED)
        self.assertEqual(report["failure_surface"], "readiness")
        self.assertTrue(report["terminal"])
        self.assertEqual(report["retry_diagnostics"]["status"], "not_retryable")
        self.assertFalse(report["retry_diagnostics"]["semantic_revision_budget_consumed"])

    def test_refusal_channels_map_to_bounded_blocked_never_infrastructure(self) -> None:
        api_refusal = build_adaptation_job_status(
            _adaptation_job(
                "failed",
                {
                    "failure_classification": {
                        "failure_class": "rights",
                        "failure_group": "validation",
                        "code": "provider_api_refusal",
                        "revision_eligible": False,
                        "semantic_revision_eligible": False,
                    }
                },
                stage="authoring",
            )
        )
        self.assertEqual(api_refusal["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(api_refusal["job_status"], ADAPTATION_JOB_STATUS_BLOCKED)
        self.assertEqual(api_refusal["failure_surface"], "policy")
        self.assertEqual(api_refusal["failure_code"], "provider_api_refusal")
        self.assertEqual(
            api_refusal["retry_diagnostics"]["status"], "not_retryable"
        )
        self.assertFalse(
            api_refusal["retry_diagnostics"]["semantic_revision_budget_consumed"]
        )

        policy_refusal = build_adaptation_job_status(
            _adaptation_job(
                "failed",
                {
                    "failure_classification": {
                        "failure_class": "refusal",
                        "failure_group": "validation",
                        "code": "dossier_refused",
                        "revision_eligible": False,
                    }
                },
                stage="authoring",
            )
        )
        self.assertEqual(policy_refusal["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(policy_refusal["job_status"], ADAPTATION_JOB_STATUS_BLOCKED)
        self.assertEqual(policy_refusal["failure_surface"], "policy")

    def test_rollback_and_verification_failure_classes_map_to_blocked(self) -> None:
        for failure_class in ("rollback", "verification"):
            with self.subTest(failure_class=failure_class):
                report = build_adaptation_job_status(
                    _adaptation_job(
                        "failed",
                        {
                            "failure_classification": {
                                "failure_class": failure_class,
                                "failure_group": "publication",
                                "code": "%s_failed" % failure_class,
                            },
                            "stages": {
                                "registry": {"status": "blocked", "verified": False},
                                "publication_rollback": {"status": "rolled_back"},
                            },
                        },
                        stage="registry",
                    )
                )
                self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_BLOCKED)
                self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_BLOCKED)
                self.assertEqual(report["failure_surface"], "publication")
                self.assertTrue(report["terminal"])
                self.assertNotEqual(
                    report["job_status"], ADAPTATION_JOB_STATUS_COMPLETED
                )


class TestAdaptationMonsterFailureStatusProjection(unittest.TestCase):
    """Concrete monster failures reach status without provider payload leakage."""

    _RAW_PROVIDER_MARKERS = (
        '"provider_payload":',
        "api_key=sk-reporting-secret",
        "raw adaptation prompt",
        "full provider response",
        "complete exception payload",
    )

    @classmethod
    def _status_for_failure(cls, failure_result: dict):
        classification = _adaptation_failure_classification(
            failure_result,
            adaptation_handoff={
                "provenance": {
                    "attempt_id": "adaptation-reporting-fixture",
                    "revision_number": 0,
                }
            },
        )
        if classification is None:
            raise AssertionError("failure result did not produce a classification")

        result = dict(failure_result)
        result["failure_classification"] = classification
        result["raw_provider_payload"] = {
            "api_key": "sk-reporting-secret",
            "raw_prompt": "raw adaptation prompt",
            "raw_response": "full provider response",
            "exception": "complete exception payload",
        }
        job = _adaptation_job(
            result.get("status", "blocked"),
            result,
            stage=result.get("stage", "build"),
        )
        return job, classification, build_adaptation_job_status(job)

    def test_guardrail_unresolved_and_ambiguous_codes_are_projected(self) -> None:
        cases = (
            "unresolved_monster_reference",
            "ambiguous_canonical_match",
        )
        for reason in cases:
            with self.subTest(reason=reason):
                job, classification, report = self._status_for_failure(
                    {
                        "status": "blocked",
                        "stage": "adaptation_monster_guardrail",
                        "error": "adaptation_monster_guardrail_unresolved",
                        "revision_eligible": True,
                        "max_revisions": 1,
                        "adaptation_monster_guardrail": {
                            "status": "blocked",
                            "unresolved_diagnostics": [
                                {
                                    "reason": reason,
                                    "message": "api_key=sk-reporting-secret raw_prompt=raw adaptation prompt",
                                }
                            ],
                        },
                    }
                )
                self.assertEqual(classification["code"], reason)
                self.assertEqual(classification["stage"], "adaptation_monster_guardrail")
                self.assertEqual(report["failure_code"], reason)
                self.assertEqual(report["failure_class"], "semantic")
                self.assertEqual(report["stage"], "adaptation_revision")
                self.assertEqual(report["retry_diagnostics"]["code"], reason)
                self.assertEqual(
                    report["retry_diagnostics"]["failure_group"], "content"
                )
                self.assertEqual(report["retry_diagnostics"]["status"], "available")
                self.assertTrue(report["next_revision_eligible"])
                self.assertTrue(report["retry_diagnostics"]["diagnostics_bounded"])
                self._assert_provider_payload_hidden(job, report)

    def test_terminal_amphail_monster_blocker_is_not_revision_available(self) -> None:
        """Terminal non-eligible closure data stays blocked and bounded."""
        job, classification, report = self._status_for_failure(
            {
                "status": "blocked",
                "stage": "adaptation_monster_guardrail",
                "error": "adaptation_monster_guardrail_unresolved",
                "revision_eligible": False,
                "semantic_revision_eligible": False,
                "terminal": True,
                "revision_budget": {
                    "current_revision": 0,
                    "max_revisions": 1,
                    "remaining_before_failure": 1,
                    "decision": "explicit_opt_in_required",
                },
                "adaptation_monster_guardrail": {
                    "status": "blocked",
                    "unresolved_diagnostics": [
                        {"reason": "unresolved_monster_reference"}
                    ],
                },
            }
        )

        self.assertEqual(classification["code"], "unresolved_monster_reference")
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_BLOCKED)
        self.assertEqual(report["failure_code"], "unresolved_monster_reference")
        self.assertEqual(report["stage"], "adaptation_blocked")
        self.assertEqual(report["retry_diagnostics"]["status"], "not_retryable")
        self.assertEqual(report["retry_diagnostics"]["decision"], "blocked")
        self.assertFalse(
            report["retry_diagnostics"]["semantic_revision_budget_consumed"]
        )
        self.assertNotEqual(report["outcome"], ADAPTATION_OUTCOME_SEMANTIC_REVISION)
        self.assertFalse(report["raw_provider_payload_exposed"])
        self._assert_provider_payload_hidden(job, report)

    def test_convergence_next_revision_marker_restores_eligible_retry(self) -> None:
        """Post-gate convergence eligibility overrides an intermediate false."""
        job = _adaptation_job(
            "blocked",
            {
                "failure_classification": {
                    "failure_class": "semantic",
                    "failure_group": "content",
                    "code": "semantic_gate_failed",
                    "revision_eligible": False,
                    "semantic_revision_eligible": False,
                    "terminal": True,
                    "revision_budget": {
                        "current_revision": 0,
                        "max_revisions": 1,
                        "remaining_before_failure": 1,
                        "decision": "explicit_opt_in_required",
                    },
                },
                "adaptation_convergence": {
                    "status": "blocked",
                    "next_revision_eligible": True,
                },
            },
            stage="adaptation_gates",
        )

        report = build_adaptation_job_status(job)
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_SEMANTIC_REVISION)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_REVISION_REQUIRED)
        self.assertEqual(report["retry_diagnostics"]["status"], "available")
        self.assertEqual(report["retry_diagnostics"]["remaining_revisions"], 1)
        self.assertFalse(
            report["retry_diagnostics"]["semantic_revision_budget_consumed"]
        )

    def test_materialization_timeout_code_is_projected_as_infrastructure_failure(self) -> None:
        job, classification, report = self._status_for_failure(
            {
                "status": "blocked",
                "stage": "adaptation_monster_guardrail",
                "error": "adaptation_monster_guardrail_unresolved",
                "adaptation_monster_guardrail": {
                    "status": "degraded",
                    "resolution_diagnostics": [
                        {
                            "reason": "generation_timeout",
                            "message": "complete exception payload",
                        }
                    ],
                },
            }
        )
        self.assertEqual(classification["code"], "generation_timeout")
        self.assertEqual(classification["failure_class"], "timeout")
        self.assertEqual(classification["stage"], "adaptation_monster_guardrail")
        self.assertEqual(report["failure_code"], "generation_timeout")
        self.assertEqual(report["failure_class"], "timeout")
        self.assertEqual(report["stage"], "adaptation_infrastructure_failed")
        self.assertEqual(report["failure_surface"], "infrastructure")
        self.assertTrue(report["retry_diagnostics"]["diagnostics_bounded"])
        self._assert_provider_payload_hidden(job, report)

    def test_closure_unresolved_code_is_projected_as_terminal_guardrail_failure(self) -> None:
        job, classification, report = self._status_for_failure(
            {
                "status": "blocked",
                "stage": "monster_closure",
                "error": "monster_closure_unresolved:1 unresolved monster reference",
                "exception": "complete exception payload",
                "revision_eligible": True,
                "max_revisions": 1,
            }
        )
        self.assertEqual(classification["code"], "monster_closure_unresolved")
        self.assertEqual(classification["failure_class"], "semantic")
        self.assertEqual(classification["stage"], "monster_closure")
        self.assertEqual(report["failure_code"], "monster_closure_unresolved")
        self.assertEqual(report["failure_class"], "semantic")
        self.assertEqual(report["stage"], "adaptation_revision")
        self.assertEqual(report["retry_diagnostics"]["code"], "monster_closure_unresolved")
        self.assertEqual(report["retry_diagnostics"]["status"], "available")
        self.assertTrue(report["next_revision_eligible"])
        self.assertTrue(report["retry_diagnostics"]["diagnostics_bounded"])
        self._assert_provider_payload_hidden(job, report)

    def _assert_provider_payload_hidden(self, job: dict, report: dict) -> None:
        serialized_report = json.dumps(report, sort_keys=True)
        for marker in self._RAW_PROVIDER_MARKERS:
            self.assertNotIn(marker, serialized_report)
        self.assertFalse(report["raw_provider_payload_exposed"])

        public = sanitize_adaptation_job_for_public(job)
        serialized_public = json.dumps(public, sort_keys=True)
        for marker in self._RAW_PROVIDER_MARKERS:
            self.assertNotIn(marker, serialized_public)
        self.assertFalse(public["result"]["raw_provider_payload_exposed"])


class TestAdaptationPublicBoundary(unittest.TestCase):
    def test_public_job_redacts_provider_payload_and_source_content(self) -> None:
        job = _adaptation_job(
            "failed",
            {
                "failure_classification": {
                    "failure_class": "timeout",
                    "failure_group": "infrastructure",
                    "code": "provider_timeout",
                },
                "error": "api_key=secret-value raw_prompt=do not expose",
                "raw_source": "full source text must not be returned",
            },
            source_path="scripts/fixtures/private_source.md",
            artifact_workspace="tmp/private-workspace",
        )
        public = sanitize_adaptation_job_for_public(job)
        serialized = repr(public)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("do not expose", serialized)
        self.assertNotIn("full source text", serialized)
        self.assertNotIn("artifact_workspace", public)
        self.assertNotIn("source_path", public)
        self.assertFalse(public["result"]["raw_provider_payload_exposed"])

    def test_legacy_public_boundary_is_unchanged(self) -> None:
        legacy = {"status": "building", "stage": "build", "result": {"status": "success"}}
        self.assertEqual(sanitize_adaptation_job_for_public(legacy), legacy)


class TestMediaOnlyHandoffReportingRuntime(unittest.TestCase):
    """Media-only gate debt stays bounded and cannot consume revision state."""

    _RAW_SENTINELS = (
        "api_key=sk-media-handoff-secret",
        "raw provider prompt sentinel",
        "private source excerpt sentinel",
        "full provider response sentinel",
    )

    def test_media_only_handoff_does_not_route_to_semantic_revision(self) -> None:
        """Project a current media-only gate result through the job contract."""
        job = _adaptation_job(
            "readiness_failed",
            {
                "status": "blocked",
                "stage": "adaptation_readiness",
                "adaptation_gate": {
                    "status": "pass",
                    "playable_status": "pass",
                    "gates": {
                        "gameplay": {
                            "status": "pass",
                            "effective_status": "pass",
                            "manual_handoff_only": True,
                            "reason": "toolkit_structural_media_handoff_only",
                            "exit_code": 1,
                            "structural_media_debt_count": 2,
                            "structural_media_debt_slugs": ["goblin", "orc"],
                        }
                    },
                },
                "failure_classification": {
                    "failure_class": "mechanical",
                    "failure_group": "readiness",
                    "code": "media_handoff_manual",
                    "revision_eligible": False,
                    "semantic_revision_eligible": False,
                    "consumes_semantic_revision_budget": False,
                    "revision_budget": {
                        "current_revision": 0,
                        "max_revisions": 1,
                        "remaining_before_failure": 1,
                        "decision": "not_applicable",
                    },
                },
                "raw_provider_payload": {
                    "credential": self._RAW_SENTINELS[0],
                    "prompt": self._RAW_SENTINELS[1],
                    "source": self._RAW_SENTINELS[2],
                    "response": self._RAW_SENTINELS[3],
                },
            },
            stage="adaptation_readiness",
        )

        report = build_adaptation_job_status(job)
        self.assertNotEqual(report["outcome"], ADAPTATION_OUTCOME_SEMANTIC_REVISION)
        self.assertEqual(report["failure_surface"], "readiness")
        self.assertFalse(report["revision_eligible"])
        self.assertFalse(report["semantic_revision_eligible"])
        self.assertFalse(report["retry_diagnostics"]["semantic_revision_budget_consumed"])
        self.assertFalse(report["raw_provider_payload_exposed"])

        public = sanitize_adaptation_job_for_public(job)
        self.assertNotEqual(public["result"]["outcome"], ADAPTATION_OUTCOME_SEMANTIC_REVISION)
        self.assertFalse(public["result"]["raw_provider_payload_exposed"])
        serialized = json.dumps({"report": report, "public": public}, sort_keys=True)
        for sentinel in self._RAW_SENTINELS:
            self.assertNotIn(sentinel, serialized)

    def test_media_only_reporting_does_not_mutate_isolated_runtime_state(self) -> None:
        """Reporting projection leaves module and publication state byte-identical."""
        import tempfile

        with tempfile.TemporaryDirectory(
            prefix="adaptation-media-handoff-", dir=str(REPO_ROOT / "tmp")
        ) as scratch:
            root = Path(scratch)
            protected = {
                "module": root / "modules" / "Amphail_Adaptation" / "module_context.json",
                "registry": root / "modules" / "world_registry.json",
                "campaign": root / "modules" / "campaign.json",
                "runtime": root / "data" / "runtime" / "adaptation_state.json",
            }
            protected["module"].parent.mkdir(parents=True)
            protected["registry"].parent.mkdir(parents=True, exist_ok=True)
            protected["runtime"].parent.mkdir(parents=True, exist_ok=True)
            protected["module"].write_bytes(
                b'{"module": "amphail", "state": "staged"}\n'
            )
            protected["registry"].write_bytes(b'{"worlds": []}\n')
            protected["campaign"].write_bytes(b'{"campaign": "unchanged"}\n')
            protected["runtime"].write_bytes(b'{"runtime": "unchanged"}\n')
            before = {
                label: path.read_bytes()
                for label, path in protected.items()
            }

            job = _adaptation_job(
                "blocked",
                {
                    "status": "blocked",
                    "stage": "adaptation_readiness",
                    "adaptation_gate": {
                        "status": "pass",
                        "manual_handoff_only": True,
                        "reason": "toolkit_structural_media_handoff_only",
                        "raw_gameplay_exit_code": 1,
                        "structural_media_debt_count": 2,
                        "structural_media_debt_slugs": ["goblin", "orc"],
                    },
                    "failure_classification": {
                        "failure_class": "mechanical",
                        "code": "media_handoff_manual",
                        "revision_eligible": False,
                        "consumes_semantic_revision_budget": False,
                    },
                    "raw_provider_payload": {
                        "credential": self._RAW_SENTINELS[0],
                        "source": self._RAW_SENTINELS[2],
                    },
                },
            )
            _refresh_adaptation_job_state(job)
            report = build_adaptation_job_status(job)
            self.assertNotEqual(report["outcome"], ADAPTATION_OUTCOME_SEMANTIC_REVISION)
            self.assertFalse(report["retry_diagnostics"]["semantic_revision_budget_consumed"])
            self.assertFalse(report["raw_provider_payload_exposed"])
            self.assertEqual(
                before,
                {label: path.read_bytes() for label, path in protected.items()},
            )


class TestAdaptationTemplateContracts(unittest.TestCase):
    def test_template_has_distinct_adaptation_outcome_surfaces(self) -> None:
        source = (REPO_ROOT / "web" / "templates" / "module_toolkit.html").read_text(
            encoding="utf-8"
        )
        for text in (
            "isToolkitAdaptationJob",
            "renderToolkitAdaptationJobStatus",
            "Semantic revision/retry is available",
            "Adaptation infrastructure failure",
            "Adaptation publication is blocked",
            "Adaptation completed after Python-owned publication",
            "raw_provider_payload_exposed: false",
        ):
            self.assertIn(text, source)

    def test_route_exposes_adaptation_summary_without_removing_legacy_phase(self) -> None:
        source = (REPO_ROOT / "web" / "routes" / "toolkit_homebrew_routes.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("adaptation_public_response_fields", source)
        self.assertIn("accurate_ingest_phase", source)
        self.assertIn("_get_canonical_adaptation_phase", source)
        self.assertIn("_refresh_adaptation_job_state", source)

    def test_template_maps_adaptation_activity_groups_and_preserves_redaction(self) -> None:
        source = (REPO_ROOT / "web" / "templates" / "module_toolkit.html").read_text(
            encoding="utf-8"
        )
        resolver_start = source.index("function resolveHomebrewAdaptationActivityGroup")
        resolver_end = source.index(
            "// Initialize module builder elements",
            resolver_start,
        )
        resolver = source[resolver_start:resolver_end]

        phase_groups = {
            "adaptation_source_context_authoring_staging": (
                "adaptation_preflight",
                "adaptation_source_context",
                "adaptation_authoring",
                "adaptation_staging",
            ),
            "adaptation_build_revision": (
                "adaptation_build",
                "adaptation_revision",
                "adaptation_revision_build",
            ),
            "validation_readiness_deterministic_repair": (
                "adaptation_validation",
                "adaptation_readiness",
            ),
            "semantic_audit": ("adaptation_semantic_audit",),
            "finishing_publication": (
                "adaptation_report",
                "adaptation_markdown",
            ),
            "registry_campaign_rollback": (
                "adaptation_registry",
                "adaptation_campaign_sync",
                "adaptation_rollback",
            ),
        }
        for group, phases in phase_groups.items():
            with self.subTest(group=group):
                self.assertIn(f"return '{group}';", resolver)
                for phase in phases:
                    self.assertIn(f"'{phase}'", resolver)

        self.assertIn("if (terminal === true)", resolver)
        self.assertIn("return '';", resolver)
        self.assertIn(
            "outcomeName !== 'in_progress' && outcomeName !== 'semantic_revision'",
            resolver,
        )
        self.assertIn("return 'unknown';", resolver)

        renderer_start = source.index("function renderToolkitAdaptationJobStatus")
        renderer_end = source.index(
            "async function pollToolkitHomebrewJob",
            renderer_start,
        )
        renderer = source[renderer_start:renderer_end]
        activity_hook_start = renderer.index("const activityGroup =")
        activity_hook_end = renderer.index("const messages =", activity_hook_start)
        activity_hook = renderer[activity_hook_start:activity_hook_end]
        self.assertIn(
            "resolveHomebrewAdaptationActivityGroup(phase, outcome, terminal)",
            activity_hook,
        )
        self.assertIn("updateHomebrewUploadActivityGroup(activityGroup)", activity_hook)
        self.assertIn("clearHomebrewActivity()", activity_hook)
        for forbidden in (
            "status_text",
            "source_path",
            "provider",
            "raw_provider_payload",
            "JSON.stringify",
        ):
            self.assertNotIn(forbidden, activity_hook)

        for contract_marker in (
            "const outcome =",
            "const phase =",
            "const retry =",
            "const publication =",
            "renderHomebrewUploadStatus(kind, message, details)",
            "raw_provider_payload_exposed: false",
        ):
            self.assertIn(contract_marker, renderer)


class TestRevisionDecisionAgreement(unittest.TestCase):
    """Task 9.2 regression coverage for terminal revision decisions."""

    def _report(self, failure_class: str, **fields: object) -> dict:
        result = {
            "status": "failed",
            "failure_class": failure_class,
            "revision_eligible": True,
            "semantic_revision_eligible": True,
            "next_revision_eligible": True,
            "revision_budget": {
                "current_revision": 0,
                "max_revisions": 1,
                "remaining_revisions": 1,
                "decision": "eligible",
            },
            **fields,
        }
        return build_adaptation_job_status(_adaptation_job("failed", result))

    def test_infrastructure_failure_ignores_stale_revision_marker(self) -> None:
        report = self._report("provider", failure_code="provider_timeout")
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_INFRASTRUCTURE_FAILURE)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_INFRASTRUCTURE_FAILED)
        self.assertEqual(report["retry_diagnostics"]["status"], "not_consumed")
        self.assertFalse(report["next_revision_eligible"])

    def test_rights_failure_remains_blocked(self) -> None:
        report = self._report("rights", failure_code="rights_review_required")
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(report["retry_diagnostics"]["status"], "not_retryable")
        self.assertFalse(report["next_revision_eligible"])

    def test_publication_failure_remains_blocked(self) -> None:
        report = self._report(
            "publication",
            failure_code="registry_write_failed",
            stage="registry",
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(report["failure_surface"], "publication")
        self.assertFalse(report["retry_diagnostics"]["retryable"])

    def test_monster_guardrail_failure_remains_blocked(self) -> None:
        report = self._report(
            "mechanical",
            failure_code="monster_closure_unresolved",
            stage="adaptation_monster_guardrail",
            failure_domain="monster_materialization",
            failure_kind="hard",
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_BLOCKED)
        self.assertEqual(report["failure_surface"], "validation")
        self.assertFalse(report["next_revision_eligible"])
        self.assertFalse(report["retry_diagnostics"]["retryable"])

    def test_semantic_content_failure_remains_revision_available(self) -> None:
        report = self._report(
            "semantic",
            failure_code="location_semantic_mismatch",
            failure_domain="semantic_authority",
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_SEMANTIC_REVISION)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_REVISION_REQUIRED)
        self.assertEqual(report["retry_diagnostics"]["status"], "available")
        self.assertTrue(report["next_revision_eligible"])

    def test_exhaustion_clears_retryable_projection(self) -> None:
        report = build_adaptation_job_status(
            _adaptation_job(
                "failed",
                {
                    "status": "failed",
                    "failure_class": "semantic",
                    "failure_code": "location_semantic_mismatch",
                    "next_revision_eligible": False,
                    "revision_eligible": False,
                    "semantic_revision_eligible": False,
                    "revision_budget": {
                        "current_revision": 1,
                        "max_revisions": 1,
                        "remaining_revisions": 0,
                        "decision": "exhausted",
                    },
                    "failure_diagnostics": [
                        {"code": "location_semantic_mismatch", "message": "bounded"}
                    ],
                },
            )
        )
        self.assertEqual(report["outcome"], ADAPTATION_OUTCOME_REVISION_EXHAUSTED)
        self.assertEqual(report["job_status"], ADAPTATION_JOB_STATUS_REVISION_EXHAUSTED)
        self.assertFalse(report["next_revision_eligible"])
        self.assertFalse(report["retry_diagnostics"]["retryable"])
        self.assertEqual(report["retry_diagnostics"]["status"], "exhausted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
