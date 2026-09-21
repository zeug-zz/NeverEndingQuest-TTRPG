# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free regression coverage for adaptation diagnostic persistence."""

from __future__ import annotations

import json
import unittest

from utils.toolkit_adaptation_output_safety import (
    project_diagnostic_tail,
    project_persisted_diagnostic,
)
from utils.toolkit_adaptation_failure_packet import build_adaptation_failure_packet
from web.extensions.toolkit_adaptation_job_reporting import build_adaptation_job_status


SENSITIVE = (
    "SOURCE_SENTINEL",
    "PROMPT_SENTINEL",
    "PROVIDER_RESPONSE_SENTINEL",
    "request_body=full-body",
    "authorization=Bearer secret-token",
    "api_key=sk_live_secret123",
    "/Users/private/project/lock",
)


class AdaptationDiagnosticRedactionTest(unittest.TestCase):
    def test_adaptation_matrix_keeps_bounded_envelope_identity_and_codes(self) -> None:
        identity = {
            "attempt_id": "adapt-001-matrix",
            "attempt_number": 2,
            "revision_number": 1,
        }
        cases = (
            ({**identity, "adaptation_mode": "llm_adaptation", "status": "failed"}, "adaptation_failed"),
            ({**identity, "adaptation_mode": "llm_adaptation", "status": "blocked", "stage": "adaptation_preflight"}, "adaptation_blocked"),
            ({**identity, "adaptation_mode": "llm_adaptation", "status": "failed", "failure_classification": {"failure_class": "refusal", "code": "provider_refused", "stage": "adaptation_authoring"}}, "provider_refused"),
            ({**identity, "adaptation_mode": "llm_adaptation", "status": "failed", "failure_classification": {"failure_class": "timeout", "code": "provider_timeout", "stage": "adaptation_build"}}, "provider_timeout"),
            ({**identity, "adaptation_mode": "llm_adaptation", "status": "running", "stage": "adaptation_build"}, "adaptation_status_unclassified"),
        )
        for job, expected_code in cases:
            report = build_adaptation_job_status(job)
            self.assertTrue(report["is_adaptation"])
            self.assertEqual(report["failure_code"], expected_code)
            self.assertFalse(report["raw_provider_payload_exposed"])
            self.assertEqual(report["attempt_id"], identity["attempt_id"])
            self.assertEqual(report["attempt_number"], identity["attempt_number"])
            self.assertEqual(report["revision_number"], identity["revision_number"])
            public = build_adaptation_job_status(job)
            encoded = json.dumps(public, ensure_ascii=True, sort_keys=True)
            self.assertTrue(encoded.isascii())
            self.assertLessEqual(len(encoded), 20_000)

    def test_tail_and_exception_projection_is_bounded_repeatable_and_safe(self) -> None:
        raw = "\n".join(SENSITIVE) + "\n" + ("safe diagnostic " * 500)
        first = project_persisted_diagnostic(
            {
                "phase": "adaptation_validation",
                "status": "blocked",
                "code": "provider_call_failed",
                "stdout_tail": raw,
                "stderr_tail": raw,
                "exception": RuntimeError(raw),
                "provider_failure": raw,
            }
        )
        second = project_persisted_diagnostic(
            {
                "phase": "adaptation_validation",
                "status": "blocked",
                "code": "provider_call_failed",
                "stdout_tail": raw,
                "stderr_tail": raw,
                "exception": RuntimeError(raw),
                "provider_failure": raw,
            }
        )
        self.assertEqual(first, second)
        encoded = json.dumps(first, ensure_ascii=True, sort_keys=True)
        self.assertTrue(encoded.isascii())
        self.assertLessEqual(len(encoded), 2000)
        self.assertFalse(first["raw_provider_payload_exposed"])
        self.assertEqual(first["code"], "provider_call_failed")
        for marker in SENSITIVE:
            self.assertNotIn(marker, encoded)

    def test_safe_tail_preserves_bounded_status_but_not_raw_tail(self) -> None:
        result = project_diagnostic_tail("stage complete\nSOURCE_SENTINEL", limit=80)
        self.assertIn("stage complete", result)
        self.assertNotIn("SOURCE_SENTINEL", result)
        self.assertLessEqual(len(result), 80)

    def test_failure_packet_redacts_classification_message_and_marks_payload_private(self) -> None:
        packet = build_adaptation_failure_packet(
            {
                "schema": {"status": "blocked", "errors": ["schema_failed"]},
                "failure_classification": {
                    "failure_class": "provider",
                    "code": "provider_call_failed",
                    "stage": "adaptation_build",
                    "message": "SOURCE_SENTINEL authorization=Bearer secret-token",
                    "diagnostics": [
                        {"code": "provider_call_failed", "message": "PROMPT_SENTINEL /Users/private/lock"}
                    ],
                },
            },
            attempt_metadata={
                "attempt_id": "adapt-001",
                "attempt_number": 1,
                "revision_number": 0,
                "stage": "adaptation_build",
                "source_hash": "a" * 64,
                "source_path": "data/source.md",
                "adaptation_mode": "llm_adaptation",
                "rights_class": "owned",
                "rights_basis": "owned",
                "rights_review_required": False,
                "rights_review_status": "not_required",
                "model_metadata": {"provider": "provider-free", "model": "test"},
            },
            staging_target={"path": "tmp/staging", "reference_only": True},
        )
        encoded = json.dumps(packet, ensure_ascii=True, sort_keys=True)
        self.assertFalse(packet["raw_provider_payload_exposed"])
        self.assertEqual(packet["failure_code"], "provider_call_failed")
        for marker in SENSITIVE:
            self.assertNotIn(marker, encoded)

    def test_job_report_keeps_failure_code_and_redacts_provider_diagnostic(self) -> None:
        job = {
            "adaptation_mode": "llm_adaptation",
            "status": "blocked",
            "stage": "adaptation_build",
            "failure_classification": {
                "failure_class": "provider",
                "code": "provider_call_failed",
                "diagnostics": [{"code": "provider_call_failed", "message": SENSITIVE[0]}],
                "exception": SENSITIVE[5],
            },
        }
        report = build_adaptation_job_status(job)
        encoded = json.dumps(report, ensure_ascii=True, sort_keys=True)
        self.assertEqual(report["failure_code"], "provider_call_failed")
        self.assertFalse(report["raw_provider_payload_exposed"])
        self.assertNotIn(SENSITIVE[0], encoded)
        self.assertNotIn(SENSITIVE[5], encoded)


if __name__ == "__main__":
    unittest.main()
