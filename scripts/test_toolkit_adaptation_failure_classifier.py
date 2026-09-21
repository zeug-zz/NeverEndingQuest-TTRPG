# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for toolkit adaptation failure classification."""

import inspect
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import toolkit_adaptation_failure_classifier as classifier
from utils.toolkit_adaptation_failure_classifier import (
    CLASSIFICATION_STATUS_BLOCKED,
    CLASSIFICATION_STATUS_REVISION_ELIGIBLE,
    CLASSIFICATION_STATUS_TERMINAL,
    FAILURE_CLASS_DEPENDENCY,
    FAILURE_CLASS_FILE,
    FAILURE_CLASS_MECHANICAL,
    FAILURE_CLASS_PROVIDER,
    FAILURE_CLASS_PUBLICATION,
    FAILURE_CLASS_QUOTA,
    FAILURE_CLASS_RIGHTS,
    FAILURE_CLASS_SEMANTIC,
    FAILURE_CLASS_TIMEOUT,
    FAILURE_CLASS_UNKNOWN,
    FAILURE_GROUP_CONTENT,
    FAILURE_GROUP_INFRASTRUCTURE,
    FAILURE_GROUP_POLICY,
    FAILURE_GROUP_PUBLICATION,
    classify_adaptation_failure,
    is_infrastructure_failure,
    should_consume_semantic_revision_budget,
)


class TestAdaptationFailureClasses(unittest.TestCase):
    """Every bounded failure class maps to a stable group."""

    def test_representative_failure_classes(self) -> None:
        cases = (
            ({"status": "provider_failed"}, FAILURE_CLASS_PROVIDER),
            ({"error": "file not found: source.md"}, FAILURE_CLASS_FILE),
            ({"failure_class": "dependency"}, FAILURE_CLASS_DEPENDENCY),
            ({"failure_class": "quota"}, FAILURE_CLASS_QUOTA),
            (TimeoutError("request timed out"), FAILURE_CLASS_TIMEOUT),
            (
                {
                    "rights_review_required": True,
                    "rights_review_status": "pending",
                },
                FAILURE_CLASS_RIGHTS,
            ),
            ({"gate": "schema"}, FAILURE_CLASS_MECHANICAL),
            ({"gate": "semantic_authority"}, FAILURE_CLASS_SEMANTIC),
            ({"publication_status": "failed"}, FAILURE_CLASS_PUBLICATION),
        )
        expected_groups = {
            FAILURE_CLASS_PROVIDER: FAILURE_GROUP_INFRASTRUCTURE,
            FAILURE_CLASS_FILE: FAILURE_GROUP_INFRASTRUCTURE,
            FAILURE_CLASS_DEPENDENCY: FAILURE_GROUP_INFRASTRUCTURE,
            FAILURE_CLASS_QUOTA: FAILURE_GROUP_INFRASTRUCTURE,
            FAILURE_CLASS_TIMEOUT: FAILURE_GROUP_INFRASTRUCTURE,
            FAILURE_CLASS_RIGHTS: FAILURE_GROUP_POLICY,
            FAILURE_CLASS_MECHANICAL: FAILURE_GROUP_CONTENT,
            FAILURE_CLASS_SEMANTIC: FAILURE_GROUP_CONTENT,
            FAILURE_CLASS_PUBLICATION: FAILURE_GROUP_PUBLICATION,
        }
        for raw_failure, expected_class in cases:
            with self.subTest(expected_class=expected_class):
                result = classify_adaptation_failure(raw_failure)
                self.assertEqual(result["failure_class"], expected_class)
                self.assertEqual(result["failure_group"], expected_groups[expected_class])
                self.assertFalse(result["publication_allowed"])

    def test_unknown_and_ambiguous_fail_closed(self) -> None:
        for raw_failure in (
            {"status": "failed", "message": "something unexpected happened"},
            {"failure_class": "not_a_contract_class"},
            None,
        ):
            with self.subTest(raw_failure=raw_failure):
                result = classify_adaptation_failure(raw_failure)
                self.assertEqual(result["failure_class"], FAILURE_CLASS_UNKNOWN)
                self.assertEqual(result["classification_status"], CLASSIFICATION_STATUS_TERMINAL)
                self.assertTrue(result["terminal"])
                self.assertFalse(result["consumes_semantic_revision_budget"])

    def test_provider_quota_and_timeout_take_precedence_over_generic_provider(self) -> None:
        quota = classify_adaptation_failure(
            {
                "failure_class": "provider",
                "status": "provider_failed",
                "error": "429 quota exceeded",
            }
        )
        timeout = classify_adaptation_failure(
            {
                "failure_class": "provider",
                "status": "provider_failed",
                "error": "request timed out while waiting for provider",
            }
        )
        self.assertEqual(quota["failure_class"], FAILURE_CLASS_QUOTA)
        self.assertEqual(timeout["failure_class"], FAILURE_CLASS_TIMEOUT)
        self.assertTrue(is_infrastructure_failure(quota))
        self.assertTrue(is_infrastructure_failure(timeout))


class TestRevisionBudgetContract(unittest.TestCase):
    """Infrastructure and policy failures never spend semantic revisions."""

    def test_infrastructure_classes_never_consume_budget_even_when_marked(self) -> None:
        failures = (
            {"failure_class": "provider"},
            {"failure_class": "file"},
            {"failure_class": "dependency"},
            {"failure_class": "quota"},
            {"failure_class": "timeout"},
        )
        for raw_failure in failures:
            with self.subTest(raw_failure=raw_failure):
                result = classify_adaptation_failure(
                    raw_failure,
                    revision_eligible=True,
                    revision_number=0,
                    max_revisions=1,
                )
                self.assertFalse(result["semantic_revision_eligible"])
                self.assertFalse(result["consumes_semantic_revision_budget"])
                self.assertEqual(result["revision_budget"]["decision"], "not_applicable")

    def test_rights_and_publication_failures_fail_closed(self) -> None:
        for raw_failure in (
            {"failure_class": "rights", "rights_review_status": "pending"},
            {"failure_class": "publication", "publication_status": "failed"},
        ):
            with self.subTest(raw_failure=raw_failure):
                result = classify_adaptation_failure(
                    raw_failure,
                    revision_eligible=True,
                )
                self.assertEqual(result["classification_status"], CLASSIFICATION_STATUS_TERMINAL)
                self.assertTrue(result["terminal"])
                self.assertFalse(result["retryable"])
                self.assertFalse(should_consume_semantic_revision_budget(result))

    def test_mechanical_and_semantic_require_explicit_revision_opt_in(self) -> None:
        for failure_class in (FAILURE_CLASS_MECHANICAL, FAILURE_CLASS_SEMANTIC):
            blocked = classify_adaptation_failure(
                {"failure_class": failure_class},
                revision_number=0,
                max_revisions=1,
            )
            eligible = classify_adaptation_failure(
                {"failure_class": failure_class},
                revision_number=0,
                max_revisions=1,
                revision_eligible=True,
            )
            self.assertEqual(blocked["classification_status"], CLASSIFICATION_STATUS_BLOCKED)
            self.assertFalse(blocked["consumes_semantic_revision_budget"])
            self.assertEqual(eligible["classification_status"], CLASSIFICATION_STATUS_REVISION_ELIGIBLE)
            self.assertTrue(eligible["semantic_revision_eligible"])
            self.assertFalse(eligible["consumes_semantic_revision_budget"])
            self.assertFalse(should_consume_semantic_revision_budget(eligible))

    def test_revision_budget_exhaustion_is_terminal(self) -> None:
        result = classify_adaptation_failure(
            {"failure_class": "semantic", "revision_eligible": True},
            revision_number=1,
            max_revisions=1,
        )
        self.assertFalse(result["consumes_semantic_revision_budget"])
        self.assertEqual(result["revision_budget"]["decision"], "exhausted")
        self.assertEqual(result["classification_status"], CLASSIFICATION_STATUS_TERMINAL)
        self.assertTrue(result["terminal"])


class TestAdaptationFailureNormalization(unittest.TestCase):
    """Classification metadata is bounded, redacted, and deterministic."""

    def test_attempt_revision_stage_domain_and_status_are_preserved(self) -> None:
        result = classify_adaptation_failure(
            {
                "failure_class": "semantic",
                "message": "semantic gate failed",
                "retryable": True,
                "terminal": False,
            },
            attempt_metadata={
                "attempt_id": "adapt-001-test",
                "revision_number": 0,
            },
            stage="build",
            domain="semantic_authority",
            revision_eligible=True,
        )
        self.assertEqual(result["attempt_id"], "adapt-001-test")
        self.assertEqual(result["revision_number"], 0)
        self.assertEqual(result["stage"], "build")
        self.assertEqual(result["domain"], "semantic_authority")
        self.assertTrue(result["retryable"])
        self.assertFalse(result["terminal"])

    def test_credentials_prompts_and_provider_payloads_are_not_retained(self) -> None:
        raw_failure = {
            "failure_class": "provider",
            "message": "api_key=sk-super-secret-value raw_prompt=do not retain this",
            "raw_response": "provider response " + ("x" * 10000),
            "response": "full provider response should not be copied",
        }
        result = classify_adaptation_failure(raw_failure)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("sk-super-secret-value", serialized)
        self.assertNotIn("do not retain this", serialized)
        self.assertNotIn("full provider response", serialized)
        self.assertFalse(result["raw_input_retained"])
        self.assertLessEqual(len(result["message"]), classifier.MAX_MESSAGE_CHARS + 3)

    def test_output_is_deterministic_and_provider_free(self) -> None:
        raw_failure = {
            "failure_class": "semantic",
            "message": "semantic gate failed",
            "diagnostics": [
                {"code": "semantic_gate_failed", "message": "bounded detail"}
            ],
        }
        first = classify_adaptation_failure(
            raw_failure,
            attempt_id="adapt-001-deterministic",
            stage="build",
            domain="semantic_authority",
            revision_eligible=True,
        )
        second = classify_adaptation_failure(
            raw_failure,
            attempt_id="adapt-001-deterministic",
            stage="build",
            domain="semantic_authority",
            revision_eligible=True,
        )
        self.assertEqual(first, second)
        source = inspect.getsource(classifier)
        self.assertNotIn("create_chat_client", source)
        self.assertNotIn("requests.", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
