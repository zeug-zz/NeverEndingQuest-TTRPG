# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Focused task 4.3 tests for adaptation artifact freshness and identity."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.extensions import toolkit_module_finisher as finisher
from web.extensions import toolkit_text_adaptation_worker as worker
from web.extensions.toolkit_adaptation_job_reporting import (
    build_adaptation_job_status,
    validate_adaptation_artifact_current,
)


SOURCE_HASH = "a" * 64
ATTEMPT_ID = "adaptation-current-attempt"
REVISION_NUMBER = 1


def _handoff() -> dict:
    return {
        "source_hash": SOURCE_HASH,
        "attempt": {
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "revision_number": REVISION_NUMBER,
        },
        "provenance": {
            "attempt_id": ATTEMPT_ID,
            "revision_number": REVISION_NUMBER,
            "source_hash": SOURCE_HASH,
            "source_path": "source/adventure.md",
        },
        "staging_target": {
            "attempt_id": ATTEMPT_ID,
            "revision_number": REVISION_NUMBER,
            "source_hash": SOURCE_HASH,
            "source_path": "source/adventure.md",
        },
    }


def _build_result(
    *, attempt_id: str = ATTEMPT_ID, revision_number: int = REVISION_NUMBER
) -> dict:
    return {
        "status": "success",
        "adaptation_provenance": {
            "attempt_id": attempt_id,
            "revision_number": revision_number,
            "source_hash": SOURCE_HASH,
            "source_path": "source/adventure.md",
        },
        "staging_target": {
            "attempt_id": attempt_id,
            "revision_number": revision_number,
            "source_hash": SOURCE_HASH,
            "source_path": "source/adventure.md",
        },
    }


class TestAdaptationStaleArtifacts(unittest.TestCase):
    def test_current_artifact_is_accepted(self) -> None:
        result = worker._validate_current_build_result(_build_result(), _handoff())
        self.assertEqual(result["status"], "pass", result)

    def test_prior_attempt_artifact_is_rejected(self) -> None:
        result = worker._validate_current_build_result(
            _build_result(attempt_id="adaptation-prior-attempt"), _handoff()
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "adaptation_build_result_stale")
        self.assertIn("attempt_id_mismatch", result["diagnostics"][0])

    def test_prior_revision_artifact_is_rejected(self) -> None:
        result = worker._validate_current_build_result(
            _build_result(revision_number=0), _handoff()
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "adaptation_build_result_stale")
        self.assertIn("revision_number_mismatch", result["diagnostics"][0])

    def test_missing_current_artifact_blocks_finishing(self) -> None:
        result = finisher._validate_adaptation_finishing_artifacts(
            adaptation_gates={"status": "pass"},
            staging_target=_handoff()["staging_target"],
            adaptation_provenance=_handoff()["provenance"],
            artifact_workspace=None,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            result["reason_code"], "adaptation_current_build_artifact_missing"
        )

    def test_freshness_and_identity_helper_never_accepts_stale_state(self) -> None:
        stale = _build_result()
        stale["report_freshness"] = {"state": "stale", "authoritative": False}
        result = validate_adaptation_artifact_current(
            stale,
            expected_attempt_id=ATTEMPT_ID,
            expected_revision_number=REVISION_NUMBER,
            expected_source_hash=SOURCE_HASH,
            label="build_result",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("freshness_stale", result["diagnostics"][0])

    def test_status_projection_surfaces_current_artifact_reason(self) -> None:
        report = build_adaptation_job_status(
            {
                "status": "blocked",
                "adaptation_mode": "llm_adaptation",
                "result": {
                    "status": "blocked",
                    "reason": "adaptation_current_build_artifact_missing",
                },
            }
        )
        self.assertEqual(report["failure_code"], "adaptation_current_build_artifact_missing")
        self.assertFalse(report["raw_provider_payload_exposed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
