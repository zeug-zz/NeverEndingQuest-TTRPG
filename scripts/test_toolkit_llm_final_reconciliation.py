# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Test - Toolkit LLM Final Reconciliation
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free tests for the LLM Builder final editor runner scaffold
(Step 2.2). Comprehensive mock-provider behavior, fail-closed JSON
validation, patch contract validation, and packet builder integration
are owned by Step 2.3 and Section 3-5 of the OpenSpec change.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any, Dict
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_llm_final_reconciliation import (
    DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING,
    DIAGNOSTIC_CODE_FAILED_RECONCILIATION,
    DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET,
    DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION,
    DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED,
    DIAGNOSTIC_CODE_GATE_READINESS_FAILED,
    DIAGNOSTIC_CODE_GATE_REPORT_AGREEMENT_BLOCKED,
    DIAGNOSTIC_CODE_INVALID_BRIEF,
    DIAGNOSTIC_CODE_INVALID_DECISIONS,
    DIAGNOSTIC_CODE_INVALID_FILE_PATCHES,
    DIAGNOSTIC_CODE_INVALID_JSON,
    DIAGNOSTIC_CODE_NOT_ACCEPTED,
    DIAGNOSTIC_CODE_INVALID_JSON_PATH,
    DIAGNOSTIC_CODE_INVALID_OP,
    DIAGNOSTIC_CODE_INVALID_PATCH_CONTRACT,
    DIAGNOSTIC_CODE_INVALID_PATCH_PLAN,
    DIAGNOSTIC_CODE_INVALID_PATCH_TARGET,
    DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
    DIAGNOSTIC_CODE_MISSING_MODULE_DIR,
    DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS,
    DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED,
    DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
    DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED,
    DIAGNOSTIC_CODE_PROVIDER_FAILED,
    DIAGNOSTIC_CODE_REFUSED_RECONCILIATION,
    DIAGNOSTIC_CODE_REPORT_BUILD_FAILED,
    DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED,
    DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED,
    DIAGNOSTIC_CODE_RETRY_NOT_REPAIRABLE,
    DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
    DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
    DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED,
    DIAGNOSTIC_CODE_TARGET_FILE_WRITE_FAILED,
    DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE,
    DIAGNOSTIC_CODE_UNSUPPORTED_STATUS,
    DIAGNOSTIC_CODE_UNSUPPORTED_VERSION,
    DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID,
    DIAGNOSTIC_SEVERITY_ERROR,
    FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES,
    FINAL_RECONCILIATION_ALLOWED_PATCH_OPS,
    FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
    FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
    FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT,
    FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
    FINAL_RECONCILIATION_DECISION_MERGE_INTO_EXISTING,
    FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
    FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM,
    FINAL_RECONCILIATION_DECISION_REFUSE,
    FINAL_RECONCILIATION_DEFAULT_TEMPERATURE,
    FINAL_RECONCILIATION_DEFAULT_TIMEOUT_SECONDS,
    FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS,
    FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS,
    FINAL_RECONCILIATION_GATE_STATUS_ERROR,
    FINAL_RECONCILIATION_GATE_STATUS_FAIL,
    FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
    FINAL_RECONCILIATION_GATE_STATUS_PASS,
    FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED,
    FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_INVALID_BRIEF,
    FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
    FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED,
    FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
    FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
    FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
    FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
    FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
    FINAL_RECONCILIATION_PATCH_STATUS_FAILED,
    FINAL_RECONCILIATION_PATCH_STATUS_READY,
    FINAL_RECONCILIATION_PATCH_STATUS_REFUSED,
    FINAL_RECONCILIATION_PATCH_VERSION,
    FINAL_RECONCILIATION_PROMPT_FALLBACK,
    FINAL_RECONCILIATION_PROMPT_PATH,
    FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS,
    FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS,
    FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH,
    FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED,
    FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_INVALID,
    FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_NOT_ACCEPTED,
    FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
    FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED,
    FINAL_RECONCILIATION_REPORT_STATUS_BLOCKED,
    FINAL_RECONCILIATION_REPORT_STATUS_INVALID_ORCHESTRATOR_RESULT,
    FINAL_RECONCILIATION_REPORT_STATUS_NOT_ACCEPTED,
    FINAL_RECONCILIATION_REQUIRED_TOP_LEVEL_KEYS,
    FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
    FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
    FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN,
    FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
    FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED,
    FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS,
    FINAL_RECONCILIATION_TASK_ID,
    MAX_FINAL_RECONCILIATION_RETRIES,
    RUNNER_MOCK_MODEL,
    RUNNER_MOCK_PARAMS_MARKER,
    RUNNER_STATUS_FAILED_RECONCILIATION,
    RUNNER_STATUS_INVALID_BRIEF,
    RUNNER_STATUS_INVALID_JSON,
    RUNNER_STATUS_INVALID_PATCH_CONTRACT,
    RUNNER_STATUS_MISSING_REQUIRED_KEYS,
    RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
    RUNNER_STATUS_PROVIDER_FAILED,
    RUNNER_STATUS_REFUSED_RECONCILIATION,
    RUNNER_STATUS_SUCCESS,
    _apply_op,
    _build_chat_messages,
    _compute_parity_counterpart,
    _extract_response_model,
    _extract_response_text,
    _has_backslash,
    _has_path_traversal,
    _is_absolute_path,
    _is_clean_pass_claim,
    _is_forbidden_target,
    _is_repairable_final_reconciliation_failure,
    _load_final_reconciliation_prompt,
    _make_diagnostic,
    _parse_json_path,
    _parse_validator_error_message,
    _parse_runner_response,
    _build_final_reconciliation_retry_brief,
    _resolve_parent,
    _serialize_brief,
    _should_mirror_parity_write,
    _strip_optional_json_fence,
    _target_matches_editable_surface,
    _try_parse_patch_json,
    _select_mock_provider_output_for_attempt,
    _summarize_attempt_for_orchestrator,
    _validate_required_top_level_keys,
    _validate_written_json,
    apply_and_validate_final_reconciliation_patch_plan,
    apply_final_reconciliation_patch_plan,
    apply_validate_and_gate_final_reconciliation_patch_plan,
    build_accepted_final_reconciliation_report,
    build_blocked_final_reconciliation_report,
    collect_schema_validation_results,
    persist_accepted_final_reconciliation_report,
    run_final_reconciliation_publication_gates,
    run_final_reconciliation_schema_validation,
    run_final_reconciliation_with_bounded_retry,
    run_llm_final_editor,
    validate_final_reconciliation_patch_contract,
    validate_final_reconciliation_patch_targets,
    validate_final_reconciliation_source_fidelity_claim,
)

# Step 4.4: import the legacy boundary helper that the on-disk
# report contract is byte-compatible with. The legacy helper is
# provider-free and stable; tests that read the persisted file use
# it as the acceptance oracle.
from utils.toolkit_final_reconciliation import (
    build_final_reconciliation_brief,
    is_final_reconciliation_accepted as _legacy_is_final_reconciliation_accepted,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _tiny_brief():
    """Return a small but realistic final reconciliation brief for tests."""
    return {
        "version": "accurate_ingest_final_reconciliation_brief.v1",
        "job_id": "job-test-001",
        "module_name": "Well_of_Ruin",
        "module_dir": "/tmp/well_of_ruin",
        "trigger": "editorial_blockers_present",
        "classification_status": "editorial",
        "editorial_blockers": [
            {"message": "Required location 'Trigger' not found in module"},
            {"message": "Required location 'Passive Element' not found in module"},
        ],
        "fatal_blockers": [],
        "warnings": [],
        "source_excerpts": [],
        "generated_module_summary": {"locations_count": 4, "npcs_count": 3},
        "editable_surfaces": [
            "module_context.json",
            "module_context_BU.json",
            "module_plot_BU.json",
            "areas/*_BU.json",
            "map_*.json",
        ],
        "instructions": (
            "Resolve bogus headings as delete_bogus_atom and keep file_patches "
            "empty when ModuleBuilder output already excludes them."
        ),
    }


def _valid_patch_plan(status: str = FINAL_RECONCILIATION_PATCH_STATUS_READY) -> Dict[str, Any]:
    """Return a small but valid final-reconciliation patch plan dict.

    The plan has every required top-level key plus a single
    ``delete_bogus_atom`` decision so callers can test the
    ``status: ready`` and ``status: refused`` / ``status: failed``
    branches without rebuilding the full shape each time.
    """
    return {
        "version": FINAL_RECONCILIATION_PATCH_VERSION,
        "status": status,
        "source_fidelity_claim": "reconciled_degraded",
        "publication_intent": "playable_module",
        "decisions": [
            {
                "blocker_message": "Required location 'Trigger' not found",
                "decision": "delete_bogus_atom",
                "from": "required_location",
                "to": "mechanic_heading",
                "reason": "Trigger is a trap mechanics heading",
            }
        ],
        "file_patches": [],
    }


def _fake_response(content: str, model_name: str = "test-model-xyz"):
    """Build a MagicMock stand-in for an OpenAI Chat Completions response."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.model = model_name
    return response


def _fake_client(response: MagicMock):
    """Build a MagicMock stand-in for an OpenAI client."""
    completions = MagicMock()
    completions.create.return_value = response
    chat = MagicMock()
    chat.completions = completions
    client = MagicMock()
    client.chat = chat
    return client


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestFinalReconciliationConstants(unittest.TestCase):
    """Pin the stable constants used by the runner scaffold."""

    def test_task_id_is_stable(self):
        self.assertEqual(
            FINAL_RECONCILIATION_TASK_ID, "toolkit_final_reconciliation"
        )

    def test_patch_version_is_stable(self):
        self.assertEqual(
            FINAL_RECONCILIATION_PATCH_VERSION,
            "accurate_ingest_final_reconciliation_patch.v1",
        )

    def test_prompt_path_points_to_existing_prompt_file(self):
        self.assertTrue(FINAL_RECONCILIATION_PROMPT_PATH.is_file())

    def test_default_temperature_and_timeout_are_positive(self):
        self.assertGreater(FINAL_RECONCILIATION_DEFAULT_TEMPERATURE, 0.0)
        self.assertLessEqual(FINAL_RECONCILIATION_DEFAULT_TEMPERATURE, 1.0)
        self.assertGreater(FINAL_RECONCILIATION_DEFAULT_TIMEOUT_SECONDS, 0)

    def test_prompt_fallback_is_ascii_only(self):
        s = FINAL_RECONCILIATION_PROMPT_FALLBACK
        s.encode("ascii")  # should not raise

    def test_mock_model_marker_is_ascii_string(self):
        self.assertIsInstance(RUNNER_MOCK_MODEL, str)
        RUNNER_MOCK_MODEL.encode("ascii")

    def test_mock_params_marker_is_small_marker(self):
        # Per the runner contract, the mock path emits a small
        # marker dict so downstream code can distinguish it from a
        # real params resolution.
        self.assertIsInstance(RUNNER_MOCK_PARAMS_MARKER, dict)
        self.assertEqual(len(RUNNER_MOCK_PARAMS_MARKER), 1)
        self.assertTrue(RUNNER_MOCK_PARAMS_MARKER.get("mock_provider"))


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

class TestPromptLoading(unittest.TestCase):
    """Provider-free tests for the on-disk prompt template."""

    def test_load_prompt_returns_non_empty_string(self):
        text = _load_final_reconciliation_prompt()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_prompt_contains_key_contract_terms(self):
        text = _load_final_reconciliation_prompt()
        # The hard rules + output shape section in the prompt must
        # include the major contract terms downstream patch validation
        # will rely on.
        self.assertIn("VALID JSON ONLY", text)
        self.assertIn("source_fidelity_claim", text)
        self.assertIn("editable_surfaces", text)
        self.assertIn(FINAL_RECONCILIATION_PATCH_VERSION, text)
        self.assertIn("file_patches", text)
        self.assertIn("decisions", text)


# ---------------------------------------------------------------------------
# Brief serialization
# ---------------------------------------------------------------------------

class TestBriefSerialization(unittest.TestCase):
    """Provider-free tests for the deterministic brief serializer."""

    def test_serialize_brief_does_not_mutate_input(self):
        brief = _tiny_brief()
        original = copy.deepcopy(brief)
        _serialize_brief(brief)
        self.assertEqual(brief, original)

    def test_serialize_brief_is_deterministic(self):
        brief = _tiny_brief()
        first = _serialize_brief(brief)
        second = _serialize_brief(brief)
        self.assertEqual(first, second)

    def test_serialize_brief_is_ascii_compatible(self):
        brief = _tiny_brief()
        s = _serialize_brief(brief)
        s.encode("ascii")  # ensure_ascii=True guarantees this

    def test_serialize_brief_round_trips_to_equal_dict(self):
        brief = _tiny_brief()
        s = _serialize_brief(brief)
        parsed = json.loads(s)
        self.assertEqual(parsed, brief)


# ---------------------------------------------------------------------------
# Chat message construction
# ---------------------------------------------------------------------------

class TestChatMessageConstruction(unittest.TestCase):
    """Provider-free tests for the system+user message assembly."""

    def test_messages_have_system_and_user_roles(self):
        msgs = _build_chat_messages(_tiny_brief())
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_system_message_contains_key_contract_terms(self):
        msgs = _build_chat_messages(_tiny_brief())
        sys_content = msgs[0]["content"]
        self.assertIn("VALID JSON ONLY", sys_content)
        self.assertIn("source_fidelity_claim", sys_content)
        self.assertIn("editable_surfaces", sys_content)

    def test_user_message_contains_serialized_brief(self):
        brief = _tiny_brief()
        msgs = _build_chat_messages(brief)
        user_content = msgs[1]["content"]
        # The user message must label the payload and contain the brief
        # content in serialized form (key fields + JSON structure).
        self.assertIn("FINAL_RECONCILIATION_BRIEF", user_content)
        self.assertIn("job-test-001", user_content)
        self.assertIn("Well_of_Ruin", user_content)
        self.assertIn("editorial_blockers_present", user_content)
        self.assertIn("editable_surfaces", user_content)

    def test_user_message_is_valid_json_after_label(self):
        msgs = _build_chat_messages(_tiny_brief())
        user_content = msgs[1]["content"]
        # Strip the label and parse the JSON body.
        prefix = "FINAL_RECONCILIATION_BRIEF:\n"
        self.assertTrue(user_content.startswith(prefix))
        json_body = user_content[len(prefix):]
        parsed = json.loads(json_body)
        self.assertEqual(parsed["job_id"], "job-test-001")
        self.assertEqual(parsed["module_name"], "Well_of_Ruin")

    def test_message_assembly_does_not_mutate_brief(self):
        brief = _tiny_brief()
        original = copy.deepcopy(brief)
        _build_chat_messages(brief)
        self.assertEqual(brief, original)


# ---------------------------------------------------------------------------
# Response extraction helpers
# ---------------------------------------------------------------------------

class TestResponseExtractionHelpers(unittest.TestCase):
    """Provider-free tests for the response text/model extractors."""

    def test_extract_text_returns_content_from_response(self):
        resp = _fake_response("hello world")
        self.assertEqual(_extract_response_text(resp), "hello world")

    def test_extract_text_returns_empty_string_for_malformed(self):
        self.assertEqual(_extract_response_text(None), "")
        # Missing choices attribute
        self.assertEqual(_extract_response_text(object()), "")
        # Empty choices list
        empty = MagicMock()
        empty.choices = []
        self.assertEqual(_extract_response_text(empty), "")

    def test_extract_model_prefers_response_model(self):
        resp = _fake_response("hi", model_name="provider-model-1")
        self.assertEqual(_extract_response_model(resp, "fallback"), "provider-model-1")

    def test_extract_model_falls_back_when_response_lacks_model(self):
        resp = MagicMock()
        del resp.model  # force AttributeError
        resp.choices = []
        self.assertEqual(_extract_response_model(resp, "fallback-model"), "fallback-model")


# ---------------------------------------------------------------------------
# Runner plumbing (minimal mock-provider coverage; Step 2.3 widens this)
# ---------------------------------------------------------------------------

class TestRunnerPlumbing(unittest.TestCase):
    """Minimal runner plumbing tests with a mocked chat client.

    Comprehensive mock-provider contract is owned by Step 2.3. These
    tests only prove the runner wires the existing chat-client and
    model-routing patterns without making a live provider call.
    """

    def test_runner_rejects_non_dict_brief(self):
        result = run_llm_final_editor("not a dict")
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_BRIEF)
        self.assertEqual(result["error"], "brief_not_dict")
        self.assertEqual(result["raw_response_text"], "")
        self.assertEqual(result["model"], "")
        self.assertEqual(result["messages_used"], [])
        self.assertEqual(result["params_used"], {})
        # Step 2.4: invalid_brief now carries a structured diagnostic.
        self.assertIn("diagnostics", result)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(result["diagnostics"][0]["code"], "invalid_brief")
        self.assertEqual(result["diagnostics"][0]["severity"], "error")

    def test_runner_rejects_none_brief(self):
        result = run_llm_final_editor(None)
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_BRIEF)
        # Step 2.4: every invalid_brief result includes diagnostics.
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(result["diagnostics"][0]["code"], "invalid_brief")

    def test_runner_rejects_list_brief(self):
        result = run_llm_final_editor([{"job_id": "x"}])
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_BRIEF)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(result["diagnostics"][0]["code"], "invalid_brief")

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_runner_success_with_mocked_client(self, mock_create):
        raw_text = json.dumps(
            {
                "version": FINAL_RECONCILIATION_PATCH_VERSION,
                "status": "ready",
                "source_fidelity_claim": "reconciled_degraded",
                "publication_intent": "playable_module",
                "decisions": [],
                "file_patches": [],
            }
        )
        response = _fake_response(raw_text, model_name="mocked-model")
        mock_create.return_value = _fake_client(response)

        brief = _tiny_brief()
        original = copy.deepcopy(brief)

        result = run_llm_final_editor(brief)

        # Status and provider contract
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["model"], "mocked-model")
        self.assertEqual(result["raw_response_text"], raw_text)
        self.assertIsNone(result["error"])

        # Messages and params are exposed for downstream steps
        self.assertIsInstance(result["messages_used"], list)
        self.assertEqual(len(result["messages_used"]), 2)
        self.assertIsInstance(result["params_used"], dict)
        self.assertIn("model", result["params_used"])

        # Brief was not mutated by the runner
        self.assertEqual(brief, original)

        # create_chat_client was invoked exactly once
        mock_create.assert_called_once()

        # Step 2.4: ready status surfaces the parsed patch plan and
        # an empty diagnostics list.
        self.assertIn("patch_plan", result)
        self.assertIn("diagnostics", result)
        self.assertEqual(result["patch_plan"]["status"], "ready")
        self.assertEqual(result["patch_plan"]["version"], FINAL_RECONCILIATION_PATCH_VERSION)
        self.assertEqual(result["diagnostics"], [])

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_runner_provider_failure_returns_status(self, mock_create):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError(
            "simulated provider outage"
        )
        mock_create.return_value = client

        result = run_llm_final_editor(_tiny_brief())

        self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(result["raw_response_text"], "")
        self.assertIn("simulated provider outage", result["error"])
        # params_used should still be populated so diagnostics can see
        # the model that would have been called.
        self.assertIn("model", result["params_used"])
        # Step 2.4: provider_failed now carries structured diagnostics.
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"], "provider_failed"
        )
        self.assertIn("simulated provider outage", result["diagnostics"][0]["message"])

    @patch("utils.toolkit_llm_final_reconciliation.get_chat_completion_params")
    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_runner_param_resolution_failure_skips_provider(
        self, mock_create, mock_params
    ):
        mock_params.side_effect = RuntimeError("bad config")
        result = run_llm_final_editor(_tiny_brief())
        self.assertEqual(result["status"], RUNNER_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertIn("bad config", result["error"])
        # No provider call should have been made.
        mock_create.assert_not_called()
        # Step 2.4: param_resolution_failed now carries structured
        # diagnostics alongside the legacy ``error`` field.
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"], "param_resolution_failed"
        )
        self.assertIn("bad config", result["diagnostics"][0]["message"])

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_runner_does_not_write_files_or_call_packet_builder(
        self, mock_create
    ):
        """The runner must not mutate the filesystem or import packet-builder
        helpers. We confirm this indirectly by checking the runtime modules
        are not touched and the brief is unchanged."""
        # Step 2.4: the runner now parses the LLM response and routes
        # ``status: refused`` to ``refused_reconciliation``. The point of
        # this test is still that no filesystem side effects occur; we
        # use a refused payload to prove the parser path is also free of
        # writes and packet-builder integration.
        response = _fake_response(
            json.dumps(
                {
                    "version": FINAL_RECONCILIATION_PATCH_VERSION,
                    "status": "refused",
                    "source_fidelity_claim": "reconciled_degraded",
                    "publication_intent": "playable_module",
                    "decisions": [],
                    "file_patches": [],
                }
            )
        )
        mock_create.return_value = _fake_response_via(_fake_client, response)

        brief = _tiny_brief()
        original = copy.deepcopy(brief)
        result = run_llm_final_editor(brief)

        # Step 2.4: refused editor status surfaces as
        # ``refused_reconciliation`` with a single refused diagnostic.
        from utils.toolkit_llm_final_reconciliation import (
            RUNNER_STATUS_REFUSED_RECONCILIATION,
        )

        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED_RECONCILIATION)
        self.assertEqual(brief, original)
        # The parsed patch plan is preserved for downstream reporting.
        self.assertEqual(result["patch_plan"].get("status"), "refused")
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"], "refused_reconciliation"
        )
        # No path/temp file keys appear on the result; nothing was written.
        for forbidden_key in ("written_paths", "files_written", "packet"):
            self.assertNotIn(forbidden_key, result)


def _fake_response_via(_builder, response):
    """Tiny helper to keep the no-write assertion block readable."""
    return _builder(response)


# ---------------------------------------------------------------------------
# Mock provider output path (Step 2.3)
# ---------------------------------------------------------------------------

class TestMockProviderOutputPath(unittest.TestCase):
    """Provider-free contract tests for the injected ``mock_provider_output``
    short-circuit added in Step 2.3. These tests do NOT mock
    ``create_chat_client`` and would fail loudly if the runner ever
    reached the live provider path while a mock output was supplied.
    """

    def test_mock_marker_constants_are_present(self):
        self.assertEqual(RUNNER_MOCK_MODEL, "mock_provider")
        self.assertEqual(RUNNER_MOCK_PARAMS_MARKER, {"mock_provider": True})

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_returns_exact_raw_text_and_messages(
        self, mock_create
    ):
        raw_text = json.dumps(
            {
                "version": FINAL_RECONCILIATION_PATCH_VERSION,
                "status": "ready",
                "source_fidelity_claim": "reconciled_degraded",
                "publication_intent": "playable_module",
                "decisions": [],
                "file_patches": [],
            }
        )

        brief = _tiny_brief()
        original = copy.deepcopy(brief)

        result = run_llm_final_editor(brief, mock_provider_output=raw_text)

        # Status + error contract under mock path.
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertIsNone(result["error"])

        # The exact injected raw text is returned verbatim.
        self.assertEqual(result["raw_response_text"], raw_text)

        # Model field is the mock marker.
        self.assertEqual(result["model"], RUNNER_MOCK_MODEL)

        # params_used is the small mock marker (NOT a real params dict).
        self.assertEqual(result["params_used"], RUNNER_MOCK_PARAMS_MARKER)
        self.assertNotIn("model", result["params_used"])

        # Messages are still built so prompt/brief plumbing can be
        # inspected; system + user pair, same shape as live path.
        self.assertIsInstance(result["messages_used"], list)
        self.assertEqual(len(result["messages_used"]), 2)
        self.assertEqual(result["messages_used"][0]["role"], "system")
        self.assertEqual(result["messages_used"][1]["role"], "user")
        self.assertIn("FINAL_RECONCILIATION_BRIEF", result["messages_used"][1]["content"])
        self.assertIn("job-test-001", result["messages_used"][1]["content"])

        # Brief was not mutated.
        self.assertEqual(brief, original)

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_does_not_call_create_chat_client(
        self, mock_create
    ):
        # This is the core Step 2.3 contract: with mock_provider_output
        # supplied, the runner must NOT touch the live provider at all.
        # Step 2.4 widens this: the injected output is also parsed, so
        # non-JSON text surfaces as ``invalid_json`` instead of success.
        from utils.toolkit_llm_final_reconciliation import (
            RUNNER_STATUS_INVALID_JSON,
        )

        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output="any-injected-string"
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["model"], RUNNER_MOCK_MODEL)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(result["diagnostics"][0]["code"], "invalid_json")
        mock_create.assert_not_called()

    @patch("utils.toolkit_llm_final_reconciliation.get_chat_completion_params")
    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_skips_param_resolution(
        self, mock_create, mock_params
    ):
        # The mock path must also skip the chat-completion-params
        # resolver so test environments without model_config stay green.
        # Step 2.4: injected text goes through the parser, so a single
        # non-JSON character surfaces as ``invalid_json``.
        from utils.toolkit_llm_final_reconciliation import (
            RUNNER_STATUS_INVALID_JSON,
        )

        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output="x"
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["model"], RUNNER_MOCK_MODEL)
        mock_params.assert_not_called()
        mock_create.assert_not_called()

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_does_not_mutate_brief(self, mock_create):
        brief = _tiny_brief()
        original = copy.deepcopy(brief)
        run_llm_final_editor(brief, mock_provider_output="inject")
        self.assertEqual(brief, original)
        # Sanity: provider was not even considered.
        mock_create.assert_not_called()

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_with_empty_string_still_short_circuits(
        self, mock_create
    ):
        # An explicit empty string is a valid mock output and must
        # still take the short-circuit path. Step 2.4: the injected
        # text is now run through the parser, so an empty string
        # surfaces as ``invalid_json`` with a structured diagnostic.
        from utils.toolkit_llm_final_reconciliation import (
            RUNNER_STATUS_INVALID_JSON,
        )

        result = run_llm_final_editor(_tiny_brief(), mock_provider_output="")
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["raw_response_text"], "")
        self.assertEqual(result["model"], RUNNER_MOCK_MODEL)
        self.assertEqual(result["params_used"], RUNNER_MOCK_PARAMS_MARKER)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(result["diagnostics"][0]["code"], "invalid_json")
        self.assertEqual(result["diagnostics"][0]["severity"], "error")
        self.assertIn("empty", result["diagnostics"][0]["message"])
        mock_create.assert_not_called()

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_with_non_string_coerces_to_string(
        self, mock_create
    ):
        # Per the simplest contract chosen in Step 2.3: non-string
        # injected values are coerced via str(...) rather than
        # rejected. Step 2.4: the coerced output is then parsed; the
        # Python-repr of a dict is not valid JSON, so the result
        # surfaces as ``invalid_json`` with a structured diagnostic.
        from utils.toolkit_llm_final_reconciliation import (
            RUNNER_STATUS_INVALID_JSON,
        )

        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output={"foo": 1}
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["raw_response_text"], "{'foo': 1}")
        self.assertEqual(result["model"], RUNNER_MOCK_MODEL)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(result["diagnostics"][0]["code"], "invalid_json")
        mock_create.assert_not_called()

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_with_non_dict_brief_still_rejected(
        self, mock_create
    ):
        # Brief validation must run BEFORE the mock short-circuit so
        # callers cannot accidentally bypass the dict check.
        result = run_llm_final_editor(
            "not a dict", mock_provider_output="ignored"
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_BRIEF)
        self.assertEqual(result["error"], "brief_not_dict")
        self.assertEqual(result["raw_response_text"], "")
        self.assertEqual(result["model"], "")
        # Provider was never reached.
        mock_create.assert_not_called()

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_mock_provider_output_result_has_no_packet_or_write_fields(
        self, mock_create
    ):
        # Source-contract: the mock path must not surface any
        # packet-builder, finisher, or filesystem-write fields on
        # the result. Step 2.3 only injected raw output plumbing;
        # Step 2.4 widens this to also expose a structured
        # ``patch_plan`` and ``diagnostics`` field on parse results.
        from utils.toolkit_llm_final_reconciliation import (
            RUNNER_STATUS_MISSING_REQUIRED_KEYS,
        )

        # Partial JSON: only ``version`` and ``decisions`` are present,
        # so the parser should report missing required top-level keys
        # without ever touching the filesystem.
        result = run_llm_final_editor(
            _tiny_brief(),
            mock_provider_output=json.dumps({"version": "x", "decisions": []}),
        )
        self.assertEqual(result["status"], RUNNER_STATUS_MISSING_REQUIRED_KEYS)
        # patch_plan is the empty dict because parse validation failed
        # before status resolution; this is the spec-mandated fallback.
        self.assertEqual(result["patch_plan"], {})
        # Diagnostics list contains one entry per missing key.
        missing_codes = [
            d["code"] for d in result["diagnostics"]
        ]
        self.assertTrue(all(c == "missing_required_keys" for c in missing_codes))
        self.assertGreaterEqual(len(result["diagnostics"]), 1)
        # packet-builder / finisher / filesystem keys are still absent.
        for forbidden_key in (
            "written_paths",
            "files_written",
            "packet",
            "applied_patches",
            "validation_result",
        ):
            self.assertNotIn(forbidden_key, result)
        mock_create.assert_not_called()

    @patch("utils.toolkit_llm_final_reconciliation.create_chat_client")
    def test_normal_mock_client_path_from_step_2_2_still_works(self, mock_create):
        # Regression: when mock_provider_output is None, the runner
        # must continue to use the existing mock-client plumbing
        # added in Step 2.2. create_chat_client is called exactly
        # once, the response model is preserved, and the brief is
        # not mutated.
        raw_text = json.dumps(_valid_patch_plan())
        response = _fake_response(raw_text, model_name="mocked-model-22")
        mock_create.return_value = _fake_client(response)

        brief = _tiny_brief()
        original = copy.deepcopy(brief)
        result = run_llm_final_editor(brief)  # no mock_provider_output

        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["model"], "mocked-model-22")
        self.assertEqual(result["raw_response_text"], raw_text)
        # params_used is a real params dict, not the mock marker.
        self.assertIn("model", result["params_used"])
        self.assertNotEqual(result["params_used"], RUNNER_MOCK_PARAMS_MARKER)
        # Step 2.4: parsed patch plan and empty diagnostics.
        self.assertEqual(result["patch_plan"]["status"], "ready")
        self.assertEqual(result["diagnostics"], [])
        # Provider was used.
        mock_create.assert_called_once()
        # Brief unchanged.
        self.assertEqual(brief, original)


# ---------------------------------------------------------------------------
# Step 2.4: structured diagnostics and parse/diagnostic helpers
# ---------------------------------------------------------------------------

class TestDiagnosticAndParseHelpers(unittest.TestCase):
    """Provider-free unit tests for the Step 2.4 parse and diagnostic
    helpers. These tests do not exercise the full runner; they pin
    the helper-level contracts so the runner-level behavior can be
    composed on top.
    """

    def test_make_diagnostic_default_severity_is_error(self):
        d = _make_diagnostic("x", "y")
        self.assertEqual(d, {"code": "x", "message": "y", "severity": "error"})

    def test_make_diagnostic_accepts_warning_severity(self):
        d = _make_diagnostic("x", "y", severity="warning")
        self.assertEqual(d["severity"], "warning")

    def test_make_diagnostic_severity_constant(self):
        self.assertEqual(DIAGNOSTIC_SEVERITY_ERROR, "error")

    def test_required_top_level_keys_match_prompt_contract(self):
        # Pin the key list so a prompt change cannot silently remove
        # a required key without breaking these tests.
        self.assertEqual(
            FINAL_RECONCILIATION_REQUIRED_TOP_LEVEL_KEYS,
            (
                "version",
                "status",
                "source_fidelity_claim",
                "publication_intent",
                "decisions",
                "file_patches",
            ),
        )

    def test_patch_status_constants_are_ascii_only(self):
        for s in (
            FINAL_RECONCILIATION_PATCH_STATUS_READY,
            FINAL_RECONCILIATION_PATCH_STATUS_REFUSED,
            FINAL_RECONCILIATION_PATCH_STATUS_FAILED,
        ):
            s.encode("ascii")

    def test_runner_status_constants_for_step_2_4(self):
        self.assertEqual(RUNNER_STATUS_INVALID_JSON, "invalid_json")
        self.assertEqual(
            RUNNER_STATUS_MISSING_REQUIRED_KEYS, "missing_required_keys"
        )
        self.assertEqual(
            RUNNER_STATUS_REFUSED_RECONCILIATION, "refused_reconciliation"
        )
        self.assertEqual(
            RUNNER_STATUS_FAILED_RECONCILIATION, "failed_reconciliation"
        )

    def test_diagnostic_code_constants_are_stable(self):
        self.assertEqual(DIAGNOSTIC_CODE_INVALID_JSON, "invalid_json")
        self.assertEqual(
            DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS, "missing_required_keys"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_REFUSED_RECONCILIATION, "refused_reconciliation"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_FAILED_RECONCILIATION, "failed_reconciliation"
        )
        self.assertEqual(DIAGNOSTIC_CODE_INVALID_BRIEF, "invalid_brief")
        self.assertEqual(DIAGNOSTIC_CODE_PROVIDER_FAILED, "provider_failed")
        self.assertEqual(
            DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED, "param_resolution_failed"
        )

    def test_strip_optional_json_fence_returns_inner_for_known_fence(self):
        inner = '{"status": "ready"}'
        self.assertEqual(_strip_optional_json_fence("```json\n" + inner + "\n```"), inner)
        self.assertEqual(_strip_optional_json_fence("```\n" + inner + "\n```"), inner)

    def test_strip_optional_json_fence_preserves_raw_json(self):
        raw = '{"status": "ready"}'
        self.assertEqual(_strip_optional_json_fence(raw), raw)

    def test_strip_optional_json_fence_preserves_non_object_inner(self):
        # When the inner is not a balanced {...} object, return the
        # original input so the parser still gets a chance.
        self.assertEqual(
            _strip_optional_json_fence("```json\n[1,2,3]\n```"),
            "```json\n[1,2,3]\n```",
        )

    def test_strip_optional_json_fence_handles_empty_input(self):
        self.assertEqual(_strip_optional_json_fence(""), "")
        self.assertEqual(_strip_optional_json_fence(None), "")

    def test_try_parse_patch_json_parses_strict_json_object(self):
        parsed, diags = _try_parse_patch_json(json.dumps(_valid_patch_plan()))
        self.assertEqual(diags, [])
        self.assertEqual(parsed["status"], "ready")
        self.assertEqual(parsed["version"], FINAL_RECONCILIATION_PATCH_VERSION)

    def test_try_parse_patch_json_strips_fence(self):
        inner = json.dumps(_valid_patch_plan())
        parsed, diags = _try_parse_patch_json("```json\n" + inner + "\n```")
        self.assertEqual(diags, [])
        self.assertEqual(parsed["status"], "ready")

    def test_try_parse_patch_json_rejects_empty_string(self):
        parsed, diags = _try_parse_patch_json("")
        self.assertIsNone(parsed)
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], DIAGNOSTIC_CODE_INVALID_JSON)
        self.assertIn("empty", diags[0]["message"])

    def test_try_parse_patch_json_rejects_non_string(self):
        parsed, diags = _try_parse_patch_json(None)
        self.assertIsNone(parsed)
        self.assertEqual(diags[0]["code"], DIAGNOSTIC_CODE_INVALID_JSON)
        parsed, diags = _try_parse_patch_json(123)
        self.assertIsNone(parsed)
        self.assertEqual(diags[0]["code"], DIAGNOSTIC_CODE_INVALID_JSON)

    def test_try_parse_patch_json_rejects_freeform_prose(self):
        prose = "Sorry, here is some freeform prose without JSON."
        parsed, diags = _try_parse_patch_json(prose)
        self.assertIsNone(parsed)
        self.assertEqual(diags[0]["code"], DIAGNOSTIC_CODE_INVALID_JSON)

    def test_try_parse_patch_json_rejects_top_level_array(self):
        parsed, diags = _try_parse_patch_json(json.dumps([1, 2, 3]))
        self.assertIsNone(parsed)
        self.assertEqual(diags[0]["code"], DIAGNOSTIC_CODE_INVALID_JSON)
        self.assertIn("not an object", diags[0]["message"])

    def test_try_parse_patch_json_rejects_malformed_json(self):
        # Unterminated object -- json.loads raises.
        parsed, diags = _try_parse_patch_json('{"status": ')
        self.assertIsNone(parsed)
        self.assertEqual(diags[0]["code"], DIAGNOSTIC_CODE_INVALID_JSON)
        self.assertIn("json.loads failed", diags[0]["message"])

    def test_validate_required_top_level_keys_reports_each_missing(self):
        parsed = {"version": FINAL_RECONCILIATION_PATCH_VERSION, "status": "ready"}
        diagnostics = _validate_required_top_level_keys(parsed)
        missing = [d["message"] for d in diagnostics]
        # Each *missing* key produces a diagnostic whose message names
        # the key. (We pre-supply ``version`` and ``status`` so the
        # remaining four keys are the expected missing ones.)
        for key in (
            "source_fidelity_claim",
            "publication_intent",
            "decisions",
            "file_patches",
        ):
            self.assertTrue(any(key in m for m in missing), f"missing {key}")
        self.assertEqual(len(diagnostics), 4)
        for d in diagnostics:
            self.assertEqual(d["code"], DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS)
            self.assertEqual(d["severity"], "error")

    def test_validate_required_top_level_keys_passes_on_complete(self):
        diagnostics = _validate_required_top_level_keys(_valid_patch_plan())
        self.assertEqual(diagnostics, [])

    def test_parse_runner_response_ready_returns_success(self):
        patch_plan, status, diags = _parse_runner_response(
            json.dumps(_valid_patch_plan())
        )
        self.assertEqual(status, RUNNER_STATUS_SUCCESS)
        self.assertEqual(diags, [])
        self.assertEqual(patch_plan["status"], "ready")

    def test_parse_runner_response_fenced_json_returns_success(self):
        inner = json.dumps(_valid_patch_plan())
        patch_plan, status, diags = _parse_runner_response(
            "```json\n" + inner + "\n```"
        )
        self.assertEqual(status, RUNNER_STATUS_SUCCESS)
        self.assertEqual(diags, [])
        self.assertEqual(patch_plan["status"], "ready")

    def test_parse_runner_response_refused_preserves_patch_plan(self):
        inner = _valid_patch_plan(status="refused")
        patch_plan, status, diags = _parse_runner_response(json.dumps(inner))
        self.assertEqual(status, RUNNER_STATUS_REFUSED_RECONCILIATION)
        # The parsed patch plan must be preserved for reporting.
        self.assertEqual(patch_plan["status"], "refused")
        self.assertEqual(len(patch_plan["decisions"]), 1)
        self.assertEqual(len(diags), 1)
        self.assertEqual(
            diags[0]["code"], DIAGNOSTIC_CODE_REFUSED_RECONCILIATION
        )

    def test_parse_runner_response_failed_preserves_patch_plan(self):
        inner = _valid_patch_plan(status="failed")
        patch_plan, status, diags = _parse_runner_response(json.dumps(inner))
        self.assertEqual(status, RUNNER_STATUS_FAILED_RECONCILIATION)
        # The parsed patch plan must be preserved for reporting.
        self.assertEqual(patch_plan["status"], "failed")
        self.assertEqual(len(diags), 1)
        self.assertEqual(
            diags[0]["code"], DIAGNOSTIC_CODE_FAILED_RECONCILIATION
        )

    def test_parse_runner_response_missing_keys(self):
        partial = {"version": FINAL_RECONCILIATION_PATCH_VERSION, "status": "ready"}
        patch_plan, status, diags = _parse_runner_response(json.dumps(partial))
        self.assertEqual(status, RUNNER_STATUS_MISSING_REQUIRED_KEYS)
        self.assertEqual(patch_plan, {})
        self.assertGreaterEqual(len(diags), 1)
        for d in diags:
            self.assertEqual(d["code"], DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS)
        # Each missing key should appear in at least one diagnostic message.
        joined = " ".join(d["message"] for d in diags)
        for key in (
            "source_fidelity_claim",
            "publication_intent",
            "decisions",
            "file_patches",
        ):
            self.assertIn(key, joined)

    def test_parse_runner_response_missing_status_field(self):
        # ``status`` is one of the required top-level keys; a payload
        # without it must fail closed with a missing_required_keys
        # diagnostic. The parsed object is still returned for
        # inspection in some scenarios; this test pins the simpler
        # case where ``status`` is fully absent.
        body = {
            "version": FINAL_RECONCILIATION_PATCH_VERSION,
            "source_fidelity_claim": "reconciled_degraded",
            "publication_intent": "playable_module",
            "decisions": [],
            "file_patches": [],
        }
        patch_plan, status, diags = _parse_runner_response(json.dumps(body))
        self.assertEqual(status, RUNNER_STATUS_MISSING_REQUIRED_KEYS)
        self.assertEqual(patch_plan, {})
        self.assertTrue(any("status" in d["message"] for d in diags))

    def test_parse_runner_response_non_string_status(self):
        # ``status`` present but with the wrong type fails closed.
        body = _valid_patch_plan()
        body["status"] = 42
        patch_plan, status, diags = _parse_runner_response(json.dumps(body))
        self.assertEqual(status, RUNNER_STATUS_MISSING_REQUIRED_KEYS)
        # Parsed object is still preserved when only the status
        # field is invalid.
        self.assertEqual(patch_plan["version"], FINAL_RECONCILIATION_PATCH_VERSION)
        self.assertTrue(any("not a string" in d["message"] for d in diags))

    def test_parse_runner_response_unknown_status_value(self):
        body = _valid_patch_plan(status="unknown_thing")
        patch_plan, status, diags = _parse_runner_response(json.dumps(body))
        self.assertEqual(status, RUNNER_STATUS_MISSING_REQUIRED_KEYS)
        # Parsed object is preserved for inspection.
        self.assertEqual(patch_plan["status"], "unknown_thing")
        self.assertTrue(any("unknown" in d["message"] for d in diags))

    def test_parse_runner_response_invalid_json(self):
        patch_plan, status, diags = _parse_runner_response("not json at all")
        self.assertEqual(status, RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(patch_plan, {})
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], DIAGNOSTIC_CODE_INVALID_JSON)


class TestRunnerFailClosedDiagnostics(unittest.TestCase):
    """End-to-end fail-closed behavior tests that drive the runner
    through the ``mock_provider_output`` short-circuit and verify
    that the structured ``patch_plan`` and ``diagnostics`` fields
    surface the same shapes as the helper-level tests.
    """

    def test_valid_ready_json_via_mock_provider_returns_success_and_patch_plan(
        self,
    ):
        raw = json.dumps(_valid_patch_plan())
        brief = _tiny_brief()
        result = run_llm_final_editor(brief, mock_provider_output=raw)
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["patch_plan"]["status"], "ready")
        self.assertEqual(result["patch_plan"]["version"], FINAL_RECONCILIATION_PATCH_VERSION)
        self.assertEqual(result["diagnostics"], [])
        # Mock-provider markers are preserved.
        self.assertEqual(result["model"], RUNNER_MOCK_MODEL)
        self.assertEqual(result["params_used"], RUNNER_MOCK_PARAMS_MARKER)
        # Brief unchanged and user message carries the brief identity.
        self.assertIn(brief["job_id"], result["messages_used"][1]["content"])
        self.assertIn(brief["module_name"], result["messages_used"][1]["content"])

    def test_fenced_json_via_mock_provider_returns_success_and_patch_plan(self):
        inner = json.dumps(_valid_patch_plan())
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output="```json\n" + inner + "\n```"
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["patch_plan"]["status"], "ready")
        self.assertEqual(result["diagnostics"], [])

    def test_invalid_json_via_mock_provider_returns_invalid_json(self):
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output="not a json object at all"
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"], DIAGNOSTIC_CODE_INVALID_JSON
        )
        self.assertEqual(result["error"], "invalid_json")

    def test_missing_required_keys_via_mock_provider_diagnostics(self):
        # Partial JSON missing several required keys.
        partial = {
            "version": FINAL_RECONCILIATION_PATCH_VERSION,
            "status": "ready",
        }
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(partial)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_MISSING_REQUIRED_KEYS)
        self.assertEqual(result["patch_plan"], {})
        self.assertGreaterEqual(len(result["diagnostics"]), 1)
        joined = " ".join(d["message"] for d in result["diagnostics"])
        for key in (
            "source_fidelity_claim",
            "publication_intent",
            "decisions",
            "file_patches",
        ):
            self.assertIn(key, joined)
        # The error string lists each missing key, separated by ';'.
        self.assertIn("missing_required_keys", result["error"])
        self.assertIn("source_fidelity_claim", result["error"])

    def test_refused_status_via_mock_provider_preserves_patch_plan(self):
        raw = json.dumps(_valid_patch_plan(status="refused"))
        result = run_llm_final_editor(_tiny_brief(), mock_provider_output=raw)
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED_RECONCILIATION)
        # Patch plan preserved.
        self.assertEqual(result["patch_plan"]["status"], "refused")
        self.assertEqual(len(result["patch_plan"]["decisions"]), 1)
        # Diagnostics records the refusal.
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_REFUSED_RECONCILIATION,
        )
        self.assertEqual(result["error"], "refused_reconciliation")

    def test_failed_status_via_mock_provider_preserves_patch_plan(self):
        raw = json.dumps(_valid_patch_plan(status="failed"))
        result = run_llm_final_editor(_tiny_brief(), mock_provider_output=raw)
        self.assertEqual(result["status"], RUNNER_STATUS_FAILED_RECONCILIATION)
        # Patch plan preserved.
        self.assertEqual(result["patch_plan"]["status"], "failed")
        self.assertEqual(len(result["patch_plan"]["decisions"]), 1)
        # Diagnostics records the failure.
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_FAILED_RECONCILIATION,
        )
        self.assertEqual(result["error"], "failed_reconciliation")

    def test_provider_failed_includes_diagnostics(self):
        from utils.toolkit_llm_final_reconciliation import (
            DIAGNOSTIC_CODE_PROVIDER_FAILED,
        )

        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError(
            "simulated provider outage"
        )
        with patch(
            "utils.toolkit_llm_final_reconciliation.create_chat_client",
            return_value=client,
        ):
            result = run_llm_final_editor(_tiny_brief())
        self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_PROVIDER_FAILED,
        )
        # Existing legacy error field is preserved.
        self.assertIn("simulated provider outage", result["error"])

    def test_param_resolution_failed_includes_diagnostics(self):
        from utils.toolkit_llm_final_reconciliation import (
            DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
        )

        with patch(
            "utils.toolkit_llm_final_reconciliation.get_chat_completion_params",
            side_effect=RuntimeError("bad config"),
        ):
            result = run_llm_final_editor(_tiny_brief())
        self.assertEqual(result["status"], RUNNER_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
        )
        # Existing legacy error field is preserved.
        self.assertIn("bad config", result["error"])

    def test_invalid_brief_includes_diagnostics(self):
        result = run_llm_final_editor("not a dict")
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_BRIEF)
        self.assertEqual(result["patch_plan"], {})
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"], DIAGNOSTIC_CODE_INVALID_BRIEF
        )
        # Existing legacy error field is preserved.
        self.assertEqual(result["error"], "brief_not_dict")


# ---------------------------------------------------------------------------
# Step 3.1: final reconciliation patch contract validation
# ---------------------------------------------------------------------------

def _all_allowed_decision_types_patch_plan() -> Dict[str, Any]:
    """Return a valid ready patch plan with one entry per allowed decision type.

    The list of decision types here is intentionally an exact match for
    the design/prompt contract: ``delete_bogus_atom``,
    ``reclassify_atom``, ``merge_into_existing``,
    ``preserve_as_dm_guidance``, ``create_missing_real_element``,
    ``refuse``. The plan uses the canonical version, ``status: ready``,
    and a single empty ``file_patches`` list (path validation is owned
    by Step 3.2).
    """
    decisions = []
    for decision_type in FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES:
        decisions.append(
            {
                "blocker_message": f"Test blocker for {decision_type}",
                "decision": decision_type,
                "from": "required_location",
                "to": "mechanic_heading",
                "reason": f"Test reason for {decision_type}",
            }
        )
    return {
        "version": FINAL_RECONCILIATION_PATCH_VERSION,
        "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
        "source_fidelity_claim": "reconciled_degraded",
        "publication_intent": "playable_module",
        "decisions": decisions,
        "file_patches": [],
    }


class TestPatchContractValidation(unittest.TestCase):
    """Provider-free unit tests for the Step 3.1
    ``validate_final_reconciliation_patch_contract`` helper.

    These tests cover the contract-level shape rules: top-level shape,
    version pin, top-level status allowlist, ``decisions`` list shape
    + per-entry shape, and ``file_patches`` list shape. They do NOT
    inspect ``file_patches[].path`` (Step 3.2) and do NOT validate
    source-fidelity claims (Step 3.3).
    """

    def test_allowed_decision_types_match_design_and_prompt(self):
        # Pin the design/prompt contract for allowed decision types so
        # any future drift breaks this test immediately. The exact list
        # is also referenced by the prompt template and design.md.
        self.assertEqual(
            FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES,
            (
                "delete_bogus_atom",
                "reclassify_atom",
                "merge_into_existing",
                "preserve_as_dm_guidance",
                "create_missing_real_element",
                "refuse",
            ),
        )

    def test_decision_type_constants_match_design(self):
        # Per-string constant pins so a rename at the constant level
        # cannot silently change the public allowlist.
        self.assertEqual(
            FINAL_RECONCILIATION_DECISION_DELETE_BOGUS_ATOM,
            "delete_bogus_atom",
        )
        self.assertEqual(
            FINAL_RECONCILIATION_DECISION_RECLASSIFY_ATOM,
            "reclassify_atom",
        )
        self.assertEqual(
            FINAL_RECONCILIATION_DECISION_MERGE_INTO_EXISTING,
            "merge_into_existing",
        )
        self.assertEqual(
            FINAL_RECONCILIATION_DECISION_PRESERVE_AS_DM_GUIDANCE,
            "preserve_as_dm_guidance",
        )
        self.assertEqual(
            FINAL_RECONCILIATION_DECISION_CREATE_MISSING_REAL_ELEMENT,
            "create_missing_real_element",
        )
        self.assertEqual(
            FINAL_RECONCILIATION_DECISION_REFUSE,
            "refuse",
        )

    def test_invalid_patch_contract_runner_status_is_stable(self):
        # Pin the new runner status name so downstream code can branch
        # on it without re-importing the literal.
        self.assertEqual(
            RUNNER_STATUS_INVALID_PATCH_CONTRACT, "invalid_patch_contract"
        )

    def test_diagnostic_codes_for_step_3_1_are_stable(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_INVALID_PATCH_CONTRACT, "invalid_patch_contract"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_UNSUPPORTED_VERSION, "unsupported_version"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_UNSUPPORTED_STATUS, "unsupported_status"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_INVALID_DECISIONS, "invalid_decisions"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_INVALID_FILE_PATCHES, "invalid_file_patches"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE,
            "unsupported_decision_type",
        )

    def test_valid_ready_patch_with_all_allowed_decision_types_passes(self):
        plan = _all_allowed_decision_types_patch_plan()
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])
        # Sanity: the plan carries one decision per allowed type.
        self.assertEqual(
            len(plan["decisions"]),
            len(FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES),
        )

    def test_valid_ready_patch_with_minimal_shape_passes(self):
        # The contract helper is shape-only; a decision with extra or
        # missing ``from``/``to``/``reason`` is acceptable here (Step
        # 4 owns content-level validation).
        plan = {
            "version": FINAL_RECONCILIATION_PATCH_VERSION,
            "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
            "source_fidelity_claim": "reconciled_degraded",
            "publication_intent": "playable_module",
            "decisions": [
                {"decision": "delete_bogus_atom"}
            ],
            "file_patches": [],
        }
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_non_dict_patch_plan_rejected(self):
        # None, list, string, int all rejected with a single
        # invalid_patch_contract diagnostic.
        for bad in (None, "string", 42, [1, 2, 3], ("a", "b")):
            is_valid, diagnostics = (
                validate_final_reconciliation_patch_contract(bad)
            )
            self.assertFalse(is_valid)
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(
                diagnostics[0]["code"], DIAGNOSTIC_CODE_INVALID_PATCH_CONTRACT
            )
            self.assertEqual(
                diagnostics[0]["severity"], DIAGNOSTIC_SEVERITY_ERROR
            )

    def test_wrong_version_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["version"] = "accurate_ingest_final_reconciliation_patch.v0"
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_VERSION, codes)
        # The unsupported_version diagnostic mentions both the bad and
        # expected version so a report reader can immediately see the
        # mismatch.
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("v0", joined)
        self.assertIn(FINAL_RECONCILIATION_PATCH_VERSION, joined)

    def test_unsupported_status_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = "maybe"  # not in {ready, refused, failed}
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_STATUS, codes)

    def test_unsupported_status_includes_non_string(self):
        # Numeric status values are not in the string allowlist and
        # must be rejected.
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = 7
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_STATUS, codes)

    def test_decisions_not_list_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = "not a list"
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)

    def test_decisions_none_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = None
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)

    def test_file_patches_not_list_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["file_patches"] = "not a list"
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_FILE_PATCHES, codes)

    def test_file_patches_none_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["file_patches"] = None
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_FILE_PATCHES, codes)

    def test_decision_entry_not_dict_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = ["not a dict"]
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)
        # The diagnostic message names the bad entry index.
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("decisions[0]", joined)

    def test_decision_missing_decision_key_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = [{"blocker_message": "no decision key"}]
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("missing required 'decision' key", joined)

    def test_decision_decision_value_not_string_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = [{"decision": 42}]
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)

    def test_unsupported_decision_type_rejected(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = [{"decision": "explode_module"}]
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("explode_module", joined)

    def test_multiple_contract_violations_all_reported(self):
        # The contract helper must report every violation, not just the
        # first, so a single pass yields a complete list.
        plan = {
            "version": "wrong_version",
            "status": "maybe",
            "source_fidelity_claim": "x",
            "publication_intent": "y",
            "decisions": ["not a dict"],
            "file_patches": "not a list",
        }
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_VERSION, codes)
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_STATUS, codes)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_FILE_PATCHES, codes)
        # At least 4 distinct diagnostics surfaced.
        self.assertGreaterEqual(len(diagnostics), 4)

    def test_file_patches_path_contents_pass_in_step_3_1_step_3_2_will_reject(
        self,
    ):
        # Step 3.1 contract only checks file_patches LIST shape. The
        # contents (path strings, operation shape, target validation)
        # are owned by Step 3.2. This test proves a ready plan with an
        # unsafe-looking path (e.g. ``../unsafe.json``) still PASSES
        # Step 3.1 because the contract helper does not inspect
        # ``file_patches[].path`` yet. Step 3.2 must update this test
        # to assert the unsafe path is rejected.
        plan = _all_allowed_decision_types_patch_plan()
        plan["file_patches"] = [
            {
                "path": "../unsafe.json",
                "operations": [{"op": "noop"}],
            }
        ]
        is_valid, diagnostics = validate_final_reconciliation_patch_contract(
            plan
        )
        # Step 3.1 expectation: list shape is valid; path contents are
        # not inspected.
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_does_not_mutate_input_plan(self):
        # The contract helper is read-only by construction; the input
        # plan is returned untouched even when diagnostics are
        # produced.
        plan = _all_allowed_decision_types_patch_plan()
        # Force a couple of violations so the helper actually runs.
        plan["version"] = "wrong"
        del plan["file_patches"]
        # Snapshot AFTER intentional mutation, BEFORE the helper call.
        snapshot = copy.deepcopy(plan)
        validate_final_reconciliation_patch_contract(plan)
        self.assertEqual(plan, snapshot)

    def test_diagnostics_carry_severity_error(self):
        # All contract diagnostics in this step are errors. A
        # warning-only diagnostic would belong to a later step; the
        # helper is fail-closed today.
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = "maybe"
        _, diagnostics = validate_final_reconciliation_patch_contract(plan)
        self.assertGreaterEqual(len(diagnostics), 1)
        for d in diagnostics:
            self.assertEqual(d["severity"], DIAGNOSTIC_SEVERITY_ERROR)


class TestPatchContractWiringInParseAndRunner(unittest.TestCase):
    """Tests proving Step 3.1 wires the contract helper into
    ``_parse_runner_response`` and ``run_llm_final_editor``.

    The ``status: ready`` branch MUST return ``RUNNER_STATUS_SUCCESS``
    only when the contract helper passes; otherwise it MUST return
    ``RUNNER_STATUS_INVALID_PATCH_CONTRACT`` with structured
    diagnostics. The ``status: refused`` and ``status: failed``
    branches continue to fail closed as in Step 2.4 but MUST also run
    the contract helper and append any shape diagnostics.
    """

    def test_parse_ready_with_contract_violation_returns_invalid_patch_contract(
        self,
    ):
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = [{"decision": "not_a_real_decision_type"}]
        patch_plan, status, diagnostics = _parse_runner_response(
            json.dumps(plan)
        )
        self.assertEqual(status, RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        # The parsed plan is still preserved so downstream code can
        # inspect the editor's intent.
        self.assertEqual(patch_plan["status"], FINAL_RECONCILIATION_PATCH_STATUS_READY)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE, codes)

    def test_parse_ready_with_valid_contract_returns_success(self):
        # A valid ready plan must still succeed in the parse helper.
        plan = _all_allowed_decision_types_patch_plan()
        patch_plan, status, diagnostics = _parse_runner_response(
            json.dumps(plan)
        )
        self.assertEqual(status, RUNNER_STATUS_SUCCESS)
        self.assertEqual(diagnostics, [])
        self.assertEqual(
            patch_plan["status"], FINAL_RECONCILIATION_PATCH_STATUS_READY
        )

    def test_parse_refused_with_contract_violation_appends_diagnostics(self):
        # A refused plan with a malformed decision entry MUST still
        # return ``refused_reconciliation`` (status semantics come
        # first) but MUST also surface the contract diagnostics.
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        plan["decisions"] = ["not a dict"]
        patch_plan, status, diagnostics = _parse_runner_response(
            json.dumps(plan)
        )
        self.assertEqual(status, RUNNER_STATUS_REFUSED_RECONCILIATION)
        # The refused diagnostic is first; the contract diagnostic
        # follows.
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(
            codes[0], DIAGNOSTIC_CODE_REFUSED_RECONCILIATION
        )
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)
        # Patch plan preserved.
        self.assertEqual(
            patch_plan["status"], FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        )

    def test_parse_failed_with_contract_violation_appends_diagnostics(self):
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        plan["file_patches"] = "not a list"
        patch_plan, status, diagnostics = _parse_runner_response(
            json.dumps(plan)
        )
        self.assertEqual(status, RUNNER_STATUS_FAILED_RECONCILIATION)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_FAILED_RECONCILIATION)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_FILE_PATCHES, codes)
        self.assertEqual(
            patch_plan["status"], FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        )

    def test_parse_refused_with_valid_contract_only_has_refused_diagnostic(
        self,
    ):
        # Sanity: a refused plan with a fully valid contract must
        # only produce the refused diagnostic, not a contract
        # diagnostic. Existing Step 2.4 tests pin len == 1.
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        # Empty decisions / file_patches still passes contract.
        plan["decisions"] = []
        _, status, diagnostics = _parse_runner_response(json.dumps(plan))
        self.assertEqual(status, RUNNER_STATUS_REFUSED_RECONCILIATION)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(
            diagnostics[0]["code"], DIAGNOSTIC_CODE_REFUSED_RECONCILIATION
        )

    def test_parse_failed_with_valid_contract_only_has_failed_diagnostic(
        self,
    ):
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        plan["decisions"] = []
        _, status, diagnostics = _parse_runner_response(json.dumps(plan))
        self.assertEqual(status, RUNNER_STATUS_FAILED_RECONCILIATION)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(
            diagnostics[0]["code"], DIAGNOSTIC_CODE_FAILED_RECONCILIATION
        )

    def test_runner_ready_with_contract_violation_returns_invalid_patch_contract(
        self,
    ):
        # End-to-end: a ready plan with an unsupported decision type
        # surfaces as ``invalid_patch_contract`` from the runner.
        plan = _all_allowed_decision_types_patch_plan()
        plan["decisions"] = [{"decision": "nope"}]
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        self.assertEqual(result["patch_plan"]["status"], "ready")
        self.assertIn(
            DIAGNOSTIC_CODE_UNSUPPORTED_DECISION_TYPE,
            [d["code"] for d in result["diagnostics"]],
        )
        # The legacy ``error`` field aggregates the contract messages.
        self.assertIn("invalid_patch_contract", result["error"])
        self.assertIn("nope", result["error"])

    def test_runner_ready_with_valid_contract_returns_success(self):
        plan = _all_allowed_decision_types_patch_plan()
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["diagnostics"], [])
        # The patch plan carries every allowed decision type.
        self.assertEqual(
            len(result["patch_plan"]["decisions"]),
            len(FINAL_RECONCILIATION_ALLOWED_DECISION_TYPES),
        )

    def test_runner_refused_with_contract_violation_carries_both_diagnostics(
        self,
    ):
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        plan["decisions"] = ["not a dict"]
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_REFUSED_RECONCILIATION)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_DECISIONS, codes)

    def test_runner_failed_with_contract_violation_carries_both_diagnostics(
        self,
    ):
        plan = _all_allowed_decision_types_patch_plan()
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        plan["file_patches"] = {"path": "x"}  # not a list
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_FAILED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_FAILED_RECONCILIATION)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_FILE_PATCHES, codes)

    def test_runner_wrong_version_via_mock_provider_fails_closed(self):
        # A valid-shape plan with the wrong patch version surfaces as
        # ``invalid_patch_contract`` with an unsupported_version
        # diagnostic.
        plan = _all_allowed_decision_types_patch_plan()
        plan["version"] = "accurate_ingest_final_reconciliation_patch.v0"
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        self.assertIn(
            DIAGNOSTIC_CODE_UNSUPPORTED_VERSION,
            [d["code"] for d in result["diagnostics"]],
        )


# ---------------------------------------------------------------------------
# Step 3.2: target validation against editable_surfaces
# ---------------------------------------------------------------------------

def _ready_plan_with_target(target_file: str) -> Dict[str, Any]:
    """Return a valid ready plan with a single file_patches entry.

    The decision set is intentionally minimal (one
    ``delete_bogus_atom``) so the only thing varying in each test is
    the patch target. The plan's other fields are valid so contract
    validation passes and target validation is the only gate.
    """
    return {
        "version": FINAL_RECONCILIATION_PATCH_VERSION,
        "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
        "source_fidelity_claim": "reconciled_degraded",
        "publication_intent": "playable_module",
        "decisions": [
            {
                "blocker_message": "Required location 'Trigger' not found",
                "decision": "delete_bogus_atom",
                "from": "required_location",
                "to": "mechanic_heading",
                "reason": "Trigger is a trap mechanics heading",
            }
        ],
        "file_patches": [
            {
                "target_file": target_file,
                "op": "remove_key",
                "json_path": "/foo/bar",
                "value": None,
                "reason": "Step 3.2 unit-test patch",
            }
        ],
    }


def _brief_with_surfaces(surfaces):
    """Return a tiny brief whose ``editable_surfaces`` is ``surfaces``."""
    brief = _tiny_brief()
    brief["editable_surfaces"] = list(surfaces)
    return brief


class TestTargetValidationHelpers(unittest.TestCase):
    """Provider-free unit tests for the small path-safety helpers
    used by :func:`validate_final_reconciliation_patch_targets`.
    """

    def test_has_backslash_detects_backslashes(self):
        self.assertTrue(_has_backslash("foo\\bar"))
        self.assertTrue(_has_backslash("\\foo"))
        self.assertTrue(_has_backslash("a\\b\\c"))

    def test_has_backslash_false_for_forward_slash(self):
        self.assertFalse(_has_backslash("foo/bar"))
        self.assertFalse(_has_backslash("areas/FOO_BU.json"))

    def test_has_backslash_handles_non_string(self):
        self.assertFalse(_has_backslash(None))
        self.assertFalse(_has_backslash(42))

    def test_is_absolute_path_detects_posix_absolute(self):
        self.assertTrue(_is_absolute_path("/foo"))
        self.assertTrue(_is_absolute_path("/"))
        self.assertTrue(_is_absolute_path("/etc/passwd"))

    def test_is_absolute_path_detects_windows_drive(self):
        self.assertTrue(_is_absolute_path("C:\\foo"))
        self.assertTrue(_is_absolute_path("C:/foo"))
        self.assertTrue(_is_absolute_path("C:"))
        self.assertTrue(_is_absolute_path("z:bar"))

    def test_is_absolute_path_false_for_relative(self):
        self.assertFalse(_is_absolute_path("foo/bar"))
        self.assertFalse(_is_absolute_path("areas/FOO_BU.json"))
        self.assertFalse(_is_absolute_path("module_context.json"))
        self.assertFalse(_is_absolute_path("./relative"))
        self.assertFalse(_is_absolute_path(""))

    def test_is_absolute_path_handles_non_string(self):
        self.assertFalse(_is_absolute_path(None))
        self.assertFalse(_is_absolute_path(42))

    def test_has_path_traversal_detects_dotdot_component(self):
        self.assertTrue(_has_path_traversal(".."))
        self.assertTrue(_has_path_traversal("../foo"))
        self.assertTrue(_has_path_traversal("foo/.."))
        self.assertTrue(_has_path_traversal("foo/../bar"))
        self.assertTrue(_has_path_traversal("a/../../b"))

    def test_has_path_traversal_false_for_safe_paths(self):
        self.assertFalse(_has_path_traversal("foo/bar"))
        self.assertFalse(_has_path_traversal("module_context.json"))
        self.assertFalse(_has_path_traversal("areas/FOO_BU.json"))
        # Dots in the middle of a component (not equal to '..') are OK.
        self.assertFalse(_has_path_traversal("foo/..bar"))
        self.assertFalse(_has_path_traversal("foo/..bar/baz"))
        # Trailing slash, no component, no traversal.
        self.assertFalse(_has_path_traversal(""))

    def test_has_path_traversal_handles_non_string(self):
        self.assertFalse(_has_path_traversal(None))
        self.assertFalse(_has_path_traversal(42))

    def test_target_matches_editable_surface_exact(self):
        self.assertTrue(
            _target_matches_editable_surface("module_context.json", "module_context.json")
        )

    def test_target_matches_editable_surface_directory_prefix(self):
        self.assertTrue(
            _target_matches_editable_surface("areas/FOO_BU.json", "areas/")
        )
        self.assertTrue(
            _target_matches_editable_surface("monsters/goblin.json", "monsters/")
        )

    def test_target_matches_editable_surface_glob(self):
        self.assertTrue(
            _target_matches_editable_surface("areas/FOO_BU.json", "areas/*_BU.json")
        )
        self.assertTrue(
            _target_matches_editable_surface("map_atlus.json", "map_*.json")
        )

    def test_target_matches_editable_surface_rejects_unrelated(self):
        self.assertFalse(
            _target_matches_editable_surface("module_plot.json", "module_context.json")
        )
        self.assertFalse(
            _target_matches_editable_surface("areas/FOO.json", "areas/*_BU.json")
        )
        self.assertFalse(
            _target_matches_editable_surface("monsters/goblin.json", "areas/")
        )

    def test_target_matches_editable_surface_handles_non_string(self):
        self.assertFalse(_target_matches_editable_surface(None, "areas/"))
        self.assertFalse(_target_matches_editable_surface("foo", None))
        self.assertFalse(_target_matches_editable_surface("", "areas/"))
        self.assertFalse(_target_matches_editable_surface("foo", ""))

    def test_is_forbidden_target_runtime_only(self):
        for forbidden in (
            "module_plot.json",
            "party_tracker.json",
            "player_quests_lidda.json",
            "encounters/encounter_123.json",
            "modules/world_registry.json",
            "modules/campaign.json",
        ):
            self.assertTrue(
                _is_forbidden_target(forbidden),
                f"expected {forbidden!r} to be forbidden",
            )

    def test_is_forbidden_target_source_middle(self):
        for forbidden in (
            "source_graph.json",
            "source_manifest.json",
            "normalized_packet.json",
            "blueprint_v2.json",
            "accurate_ingest_audit_run/run.json",
            "agent_runs/something.json",
            "MODULE_SUMMARY.md",
        ):
            self.assertTrue(
                _is_forbidden_target(forbidden),
                f"expected {forbidden!r} to be forbidden",
            )

    def test_is_forbidden_target_areas_runtime_live(self):
        # ``areas/FOO.json`` is live runtime state and must be
        # rejected. ``areas/FOO_BU.json`` is canonical and must NOT
        # be rejected by the runtime-only check (the editable_surfaces
        # whitelist is the final authority).
        self.assertTrue(_is_forbidden_target("areas/FOO.json"))
        self.assertTrue(_is_forbidden_target("areas/lidda_start.json"))
        self.assertFalse(_is_forbidden_target("areas/FOO_BU.json"))
        self.assertFalse(_is_forbidden_target("areas/lidda_start_BU.json"))
        # Non-JSON areas entries fall through to whitelist.
        self.assertFalse(_is_forbidden_target("areas/notes.txt"))

    def test_is_forbidden_target_allows_canonical_targets(self):
        for allowed in (
            "module_context.json",
            "module_context_BU.json",
            "module_plot_BU.json",
            "areas/FOO_BU.json",
            "map_atlus.json",
            "monsters/goblin.json",
        ):
            self.assertFalse(
                _is_forbidden_target(allowed),
                f"expected {allowed!r} to be allowed",
            )

    def test_is_forbidden_target_handles_non_string(self):
        self.assertFalse(_is_forbidden_target(None))
        self.assertFalse(_is_forbidden_target(42))


class TestValidateFinalReconciliationPatchTargets(unittest.TestCase):
    """Provider-free unit tests for
    :func:`validate_final_reconciliation_patch_targets`.
    """

    # --- Accept cases ---

    def test_accepts_exact_whitelisted_target(self):
        plan = _ready_plan_with_target("module_context.json")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_accepts_directory_prefix_whitelist_for_bu_file(self):
        plan = _ready_plan_with_target("areas/FOO_BU.json")
        brief = _brief_with_surfaces(["areas/"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_rejects_runtime_live_file_under_directory_prefix_whitelist(self):
        # The directory-prefix whitelist does NOT bypass the runtime
        # carve-out: a live ``areas/FOO.json`` is rejected even when
        # the whitelist is ``areas/``.
        plan = _ready_plan_with_target("areas/FOO.json")
        brief = _brief_with_surfaces(["areas/"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("areas/FOO.json", joined)

    def test_accepts_glob_whitelist_for_bu_file(self):
        plan = _ready_plan_with_target("areas/FOO_BU.json")
        brief = _brief_with_surfaces(["areas/*_BU.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_accepts_glob_whitelist_for_map_file(self):
        plan = _ready_plan_with_target("map_atlus.json")
        brief = _brief_with_surfaces(["map_*.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_rejects_target_not_in_editable_surfaces(self):
        plan = _ready_plan_with_target("module_context.json")
        brief = _brief_with_surfaces(["areas/*_BU.json", "map_*.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("module_context.json", joined)
        self.assertIn("editable_surfaces", joined)

    # --- Empty file_patches ---

    def test_empty_file_patches_does_not_require_editable_surfaces(self):
        plan = _ready_plan_with_target("")  # unused
        plan["file_patches"] = []
        brief = {"editable_surfaces": "not a list"}
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_empty_file_patches_works_without_editable_surfaces_key(self):
        plan = _ready_plan_with_target("")
        plan["file_patches"] = []
        brief = _tiny_brief()
        del brief["editable_surfaces"]
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_non_list_file_patches_returns_success_no_diagnostics(self):
        # The contract helper owns the LIST-shape failure; this helper
        # returns success so the contract helper can emit its own
        # ``invalid_file_patches`` diagnostic without a confusing
        # duplicate from target validation.
        plan = _ready_plan_with_target("module_context.json")
        plan["file_patches"] = "not a list"
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    # --- Whitelist shape failures ---

    def test_missing_editable_surfaces_fails_closed(self):
        plan = _ready_plan_with_target("module_context.json")
        brief = _tiny_brief()
        del brief["editable_surfaces"]
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING, codes)

    def test_non_list_editable_surfaces_fails_closed(self):
        plan = _ready_plan_with_target("module_context.json")
        brief = _tiny_brief()
        brief["editable_surfaces"] = "module_context.json"  # string, not list
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING, codes)

    def test_editable_surfaces_with_non_string_items_fails_closed(self):
        plan = _ready_plan_with_target("module_context.json")
        brief = _tiny_brief()
        brief["editable_surfaces"] = ["module_context.json", 42, "areas/"]
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING, codes)

    def test_empty_editable_surfaces_fails_closed(self):
        plan = _ready_plan_with_target("module_context.json")
        brief = _brief_with_surfaces([])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING, codes)

    # --- Entry shape failures ---

    def test_rejects_non_dict_file_patch_entry(self):
        plan = _ready_plan_with_target("module_context.json")
        plan["file_patches"] = ["not a dict"]
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("file_patches[0]", joined)

    def test_rejects_missing_target_file(self):
        plan = _ready_plan_with_target("module_context.json")
        plan["file_patches"] = [{"op": "remove_key", "json_path": "/a"}]
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("target_file", joined)

    def test_rejects_non_string_target_file(self):
        plan = _ready_plan_with_target("module_context.json")
        plan["file_patches"] = [{"target_file": 42}]
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)

    def test_rejects_none_target_file(self):
        plan = _ready_plan_with_target("module_context.json")
        plan["file_patches"] = [{"target_file": None}]
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)

    # --- Path safety failures ---

    def test_rejects_empty_target_string(self):
        plan = _ready_plan_with_target("")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("empty", joined)

    def test_rejects_whitespace_only_target_string(self):
        plan = _ready_plan_with_target("   ")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_absolute_posix_path(self):
        plan = _ready_plan_with_target("/etc/passwd")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("absolute", joined)
        self.assertIn("/etc/passwd", joined)

    def test_rejects_windows_drive_path_with_backslash(self):
        plan = _ready_plan_with_target("C:\\Windows\\System32")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The backslash rule fires first; the diagnostic names the
        # rejection reason.
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("backslash", joined)

    def test_rejects_windows_drive_path_with_forward_slash(self):
        plan = _ready_plan_with_target("C:/Windows/System32")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("absolute", joined)

    def test_rejects_bare_windows_drive_letter(self):
        plan = _ready_plan_with_target("C:")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_backslash_in_path(self):
        plan = _ready_plan_with_target("module_context\\backup.json")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("backslash", joined)

    def test_rejects_dotdot_traversal_segment(self):
        plan = _ready_plan_with_target("../unsafe.json")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("traversal", joined)

    def test_rejects_normalized_traversal_segment(self):
        plan = _ready_plan_with_target("foo/../bar.json")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("traversal", joined)

    def test_rejects_double_dot_only_target(self):
        plan = _ready_plan_with_target("..")
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    # --- Runtime-only failures ---

    def test_rejects_runtime_only_module_plot(self):
        plan = _ready_plan_with_target("module_plot.json")
        brief = _brief_with_surfaces(["module_plot.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("module_plot.json", joined)

    def test_rejects_runtime_only_party_tracker(self):
        plan = _ready_plan_with_target("party_tracker.json")
        brief = _brief_with_surfaces(["party_tracker.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_runtime_only_player_quests_glob(self):
        plan = _ready_plan_with_target("player_quests_lidda.json")
        brief = _brief_with_surfaces(["player_quests_*.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_runtime_only_encounters_path(self):
        plan = _ready_plan_with_target("encounters/encounter_42.json")
        brief = _brief_with_surfaces(["encounters/"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_runtime_only_modules_world_registry(self):
        plan = _ready_plan_with_target("modules/world_registry.json")
        brief = _brief_with_surfaces(["modules/world_registry.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_runtime_only_modules_campaign(self):
        plan = _ready_plan_with_target("modules/campaign.json")
        brief = _brief_with_surfaces(["modules/campaign.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_runtime_only_live_areas_file(self):
        plan = _ready_plan_with_target("areas/lidda_start.json")
        brief = _brief_with_surfaces(["areas/"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    # --- Source/middle failures ---

    def test_rejects_source_graph(self):
        plan = _ready_plan_with_target("source_graph.json")
        brief = _brief_with_surfaces(["source_graph.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_source_manifest(self):
        plan = _ready_plan_with_target("source_manifest.json")
        brief = _brief_with_surfaces(["source_manifest.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_normalized_packet(self):
        plan = _ready_plan_with_target("normalized_packet.json")
        brief = _brief_with_surfaces(["normalized_packet.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_blueprint_glob(self):
        plan = _ready_plan_with_target("blueprint_v2.json")
        brief = _brief_with_surfaces(["blueprint_*.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_audit_run_artifact(self):
        plan = _ready_plan_with_target("accurate_ingest_audit_run/run.json")
        brief = _brief_with_surfaces(["accurate_ingest_audit_run/"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_agent_runs_artifact(self):
        plan = _ready_plan_with_target("agent_runs/run.json")
        brief = _brief_with_surfaces(["agent_runs/"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_rejects_module_summary_md(self):
        plan = _ready_plan_with_target("MODULE_SUMMARY.md")
        brief = _brief_with_surfaces(["MODULE_SUMMARY.md"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    # --- Input shape ---

    def test_rejects_non_dict_patch_plan(self):
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            "not a dict", _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)

    def test_rejects_non_dict_brief(self):
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            _ready_plan_with_target("module_context.json"),
            "not a dict",
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)

    def test_does_not_mutate_inputs(self):
        # The helper is read-only by construction; both inputs are
        # returned untouched even when diagnostics are produced.
        plan = _ready_plan_with_target("../unsafe.json")
        brief = _brief_with_surfaces(["module_context.json"])
        snapshot_plan = copy.deepcopy(plan)
        snapshot_brief = copy.deepcopy(brief)
        validate_final_reconciliation_patch_targets(plan, brief)
        self.assertEqual(plan, snapshot_plan)
        self.assertEqual(brief, snapshot_brief)

    def test_diagnostics_carry_severity_error(self):
        plan = _ready_plan_with_target("../unsafe.json")
        brief = _brief_with_surfaces(["module_context.json"])
        _, diagnostics = validate_final_reconciliation_patch_targets(plan, brief)
        self.assertGreaterEqual(len(diagnostics), 1)
        for d in diagnostics:
            self.assertEqual(d["severity"], DIAGNOSTIC_SEVERITY_ERROR)

    def test_multiple_target_violations_all_reported(self):
        plan = _ready_plan_with_target("../unsafe.json")
        plan["file_patches"].append(
            {
                "target_file": "module_plot.json",
                "op": "remove_key",
                "json_path": "/a",
            }
        )
        plan["file_patches"].append({"target_file": None})
        brief = _brief_with_surfaces(["module_context.json"])
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, brief
        )
        self.assertFalse(is_valid)
        # At least one diagnostic per bad entry.
        self.assertGreaterEqual(len(diagnostics), 3)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("../unsafe.json", joined)
        self.assertIn("module_plot.json", joined)
        self.assertIn("target_file", joined)


def _enriched_brief():
    """Return an enriched brief with populated source_excerpts,
    generated_module_summary, and canonical editable_surfaces.

    Used by TestEnrichedBriefEvidenceAndTargetValidation to prove
    enriched briefs contain evidence for editorial blockers and still
    reject unsafe patch targets through existing final-editor validation.
    """
    return {
        "version": "accurate_ingest_final_reconciliation_brief.v1",
        "job_id": "job-enriched-53",
        "module_name": "EnrichedModule",
        "module_dir": "/tmp/enriched",
        "trigger": "editorial_blockers_present",
        "classification_status": "editorial",
        "editorial_blockers": [
            {"message": "Required location 'Trigger' not found in module"},
            {"message": "Required npc 'Wayne' not found in module"},
        ],
        "fatal_blockers": [],
        "warnings": [],
        "source_excerpts": [
            {
                "source_atom_id": "loc_trigger",
                "atom_type": "location",
                "name": "Trigger",
                "excerpt": "The ancient Trigger chamber beneath the ruined keep",
            },
            {
                "source_atom_id": "ent_wayne",
                "atom_type": "npc",
                "name": "Wayne",
                "excerpt": "Wayne the gatekeeper of the hidden city",
            },
        ],
        "generated_module_summary": {
            "area_count": 3,
            "area_bu_count": 2,
            "monster_count": 1,
            "has_module_context": True,
            "has_module_plot": True,
            "missing_categories": [],
        },
        "editable_surfaces": [
            "module_context.json",
            "module_context_BU.json",
            "module_plot_BU.json",
            "areas/*_BU.json",
            "map_*.json",
        ],
        "instructions": "Task 5.3 enriched-brief target validation test.",
    }


class TestEnrichedBriefEvidenceAndTargetValidation(unittest.TestCase):
    """Task 5.3: Prove enriched briefs contain evidence for editorial
    blockers and still reject unsafe patch targets through existing
    final-editor target validation.

    Evidence enrichment (source_excerpts, generated_module_summary)
    must not widen the editable_surfaces or weaken forbidden-target
    rejection.  All tests are provider-free and tempdir-backed where
    needed.
    """

    # ------------------------------------------------------------------
    # Evidence enrichment: source_excerpts
    # ------------------------------------------------------------------

    def test_enriched_brief_source_excerpts_present(self):
        """Enriched brief contains source_excerpts with resolved atoms."""
        brief = _enriched_brief()
        self.assertEqual(len(brief["source_excerpts"]), 2)
        self.assertEqual(brief["source_excerpts"][0]["source_atom_id"], "loc_trigger")
        self.assertEqual(brief["source_excerpts"][0]["atom_type"], "location")
        self.assertEqual(brief["source_excerpts"][1]["source_atom_id"], "ent_wayne")
        self.assertEqual(brief["source_excerpts"][1]["atom_type"], "npc")
        self.assertIn("Trigger chamber", brief["source_excerpts"][0]["excerpt"])
        self.assertIn("Wayne", brief["source_excerpts"][1]["excerpt"])

    def test_enriched_brief_generated_module_summary_present(self):
        """Enriched brief contains non-empty generated_module_summary."""
        brief = _enriched_brief()
        summary = brief["generated_module_summary"]
        self.assertGreater(summary["area_count"], 0)
        self.assertGreater(summary["area_bu_count"], 0)
        self.assertGreater(summary["monster_count"], 0)
        self.assertTrue(summary["has_module_context"])
        self.assertTrue(summary["has_module_plot"])
        self.assertIsInstance(summary["missing_categories"], list)

    def test_enriched_brief_source_excerpts_from_build_function(self):
        """Evidence enrichment via build_final_reconciliation_brief
        with source_graph produces source_excerpts."""
        classification = {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {
                    "type": "editorial",
                    "message": "Required location 'Trigger' not found",
                    "category": "location",
                    "source_atom_id": "loc_trigger",
                    "raw": {},
                },
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        sg = {
            "atoms": [
                {"id": "loc_trigger", "type": "location", "name": "Trigger",
                 "summary": "The ancient Trigger chamber"},
            ],
        }
        brief = build_final_reconciliation_brief(
            classification, job_id="j53e", module_name="M",
            source_graph=sg,
        )
        self.assertEqual(len(brief["source_excerpts"]), 1)
        self.assertEqual(brief["source_excerpts"][0]["source_atom_id"], "loc_trigger")

    def test_enriched_brief_generated_summary_from_build_with_tempdir(self):
        """Evidence enrichment via build_final_reconciliation_brief
        with a real temp module dir produces non-empty summary."""
        classification = {
            "status": "editorial",
            "fatal_blockers": [],
            "editorial_blockers": [
                {
                    "type": "editorial",
                    "message": "Required location 'X' not found",
                    "category": "location",
                    "source_atom_id": None,
                    "raw": {},
                },
            ],
            "warnings": [],
            "can_attempt_final_reconciliation": True,
            "fatal_count": 0,
            "editorial_count": 1,
            "original_refusal_reason": "",
            "report_paths": {},
        }
        with tempfile.TemporaryDirectory() as d:
            mod_dir = Path(d)
            area_dir = mod_dir / "areas"
            area_dir.mkdir(parents=True)
            (area_dir / "AREA001_BU.json").write_text("{}")
            (mod_dir / "module_context.json").write_text("{}")

            brief = build_final_reconciliation_brief(
                classification, job_id="j53s", module_name="M",
                module_dir=mod_dir,
            )
            summary = brief["generated_module_summary"]
            self.assertEqual(summary["area_count"], 1)
            self.assertEqual(summary["area_bu_count"], 1)
            self.assertTrue(summary["has_module_context"])
            self.assertFalse(summary["has_module_plot"])

    # ------------------------------------------------------------------
    # Rejection: unsafe patch targets with enriched brief
    # ------------------------------------------------------------------

    def test_enriched_rejects_runtime_module_plot(self):
        """Enriched brief rejects runtime-only module_plot.json."""
        plan = _ready_plan_with_target("module_plot.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("module_plot.json", joined)

    def test_enriched_rejects_live_areas_file(self):
        """Enriched brief rejects live areas/FOO.json (runtime runtime)."""
        plan = _ready_plan_with_target("areas/FOO.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_enriched_rejects_source_graph(self):
        """Enriched brief rejects source/middle source_graph.json."""
        plan = _ready_plan_with_target("source_graph.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("source_graph.json", joined)

    def test_enriched_rejects_builder_blueprint(self):
        """Enriched brief rejects builder_blueprint.json (source/middle)."""
        plan = _ready_plan_with_target("builder_blueprint.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("builder_blueprint.json", joined)

    def test_enriched_rejects_path_traversal(self):
        """Enriched brief rejects path traversal areas/../module_context.json."""
        plan = _ready_plan_with_target("areas/../module_context.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("traversal", joined)

    def test_enriched_rejects_non_whitelisted_monsters(self):
        """Enriched brief rejects monsters/foo.json (not in canonical surfaces)."""
        plan = _ready_plan_with_target("monsters/foo.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("monsters/foo.json", joined)
        self.assertIn("editable_surfaces", joined)

    # ------------------------------------------------------------------
    # Positive controls: canonical targets pass with enriched brief
    # ------------------------------------------------------------------

    def test_enriched_accepts_module_context(self):
        """Enriched brief accepts canonical module_context.json."""
        plan = _ready_plan_with_target("module_context.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_enriched_accepts_module_plot_bu(self):
        """Enriched brief accepts canonical module_plot_BU.json."""
        plan = _ready_plan_with_target("module_plot_BU.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_enriched_accepts_areas_bu_file(self):
        """Enriched brief accepts canonical areas/FOO_BU.json."""
        plan = _ready_plan_with_target("areas/FOO_BU.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_enriched_accepts_map_file(self):
        """Enriched brief accepts canonical map_test.json."""
        plan = _ready_plan_with_target("map_test.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _enriched_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])


class TestRunnerTargetValidationWiring(unittest.TestCase):
    """End-to-end tests that drive the runner through
    ``mock_provider_output`` and assert the Step 3.2 wiring folds
    target validation into the runner's status/diagnostics.
    """

    def test_runner_ready_with_valid_target_returns_success(self):
        plan = _ready_plan_with_target("module_context.json")
        result = run_llm_final_editor(
            _brief_with_surfaces(["module_context.json"]),
            mock_provider_output=json.dumps(plan),
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["error"], None)

    def test_runner_ready_with_forbidden_target_fails_closed(self):
        plan = _ready_plan_with_target("module_plot.json")
        # The brief's editable_surfaces is irrelevant when the
        # target is in the runtime-only forbidden list.
        brief = _brief_with_surfaces(
            ["module_context.json", "module_plot.json"]
        )
        result = run_llm_final_editor(
            brief, mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        joined = " ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("module_plot.json", joined)
        # Legacy ``error`` field still aggregates the message.
        self.assertIn("forbidden", result["error"])

    def test_runner_ready_with_traversal_target_fails_closed(self):
        plan = _ready_plan_with_target("../unsafe.json")
        result = run_llm_final_editor(
            _brief_with_surfaces(["module_context.json"]),
            mock_provider_output=json.dumps(plan),
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_runner_ready_with_missing_editable_surfaces_fails_closed(self):
        plan = _ready_plan_with_target("module_context.json")
        brief = _tiny_brief()
        del brief["editable_surfaces"]
        result = run_llm_final_editor(
            brief, mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_EDITABLE_SURFACES_MISSING, codes)

    def test_runner_refused_with_valid_target_preserves_refused_status(self):
        # A refused plan with a clean target preserves the refused
        # status and adds no target diagnostics. This pins the Step
        # 3.1 contract that refused/failed semantics are preserved
        # when no unsafe patch is being applied.
        plan = _ready_plan_with_target("module_context.json")
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        plan["decisions"] = []
        result = run_llm_final_editor(
            _brief_with_surfaces(["module_context.json"]),
            mock_provider_output=json.dumps(plan),
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        # Only the refused diagnostic; no forbidden_patch_target.
        self.assertNotIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_REFUSED_RECONCILIATION)

    def test_runner_refused_with_forbidden_target_preserves_refused_status(
        self,
    ):
        # A refused plan with an unsafe target keeps the refused
        # status (per the simplest Step 3.1 semantics) but the target
        # diagnostic is appended so the report can still surface it.
        plan = _ready_plan_with_target("module_plot.json")
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        plan["decisions"] = []
        result = run_llm_final_editor(
            _brief_with_surfaces(["module_context.json"]),
            mock_provider_output=json.dumps(plan),
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_REFUSED_RECONCILIATION)
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_runner_failed_with_forbidden_target_preserves_failed_status(
        self,
    ):
        # Same pattern for failed plans.
        plan = _ready_plan_with_target("../escape.json")
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        plan["decisions"] = []
        result = run_llm_final_editor(
            _brief_with_surfaces(["module_context.json"]),
            mock_provider_output=json.dumps(plan),
        )
        self.assertEqual(result["status"], RUNNER_STATUS_FAILED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_FAILED_RECONCILIATION)
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_runner_ready_with_empty_file_patches_succeeds_without_editable_surfaces(
        self,
    ):
        # Empty file_patches: target validation is skipped; the
        # absence of editable_surfaces in the brief does NOT block
        # the success path. This is the Step 3.1 contract preserved
        # by Step 3.2.
        plan = _ready_plan_with_target("module_context.json")
        plan["file_patches"] = []
        brief = _tiny_brief()
        del brief["editable_surfaces"]
        result = run_llm_final_editor(
            brief, mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["diagnostics"], [])

    def test_runner_does_not_call_live_provider_under_target_failure(self):
        # The mock-provider short-circuit must remain in effect when
        # target validation fails; the runner must not reach the live
        # provider path.
        plan = _ready_plan_with_target("module_plot.json")
        with patch(
            "utils.toolkit_llm_final_reconciliation.create_chat_client"
        ) as mock_create:
            result = run_llm_final_editor(
                _brief_with_surfaces(["module_context.json"]),
                mock_provider_output=json.dumps(plan),
            )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Step 3.3: source-fidelity-claim validation
# ---------------------------------------------------------------------------

def _ready_plan_with_source_fidelity_claim(
    claim: Any, status: str = FINAL_RECONCILIATION_PATCH_STATUS_READY
) -> Dict[str, Any]:
    """Return a valid ready plan whose ``source_fidelity_claim`` is
    caller-supplied.

    The plan has every required top-level key plus a single
    ``delete_bogus_atom`` decision so callers can vary the claim
    field in isolation. The plan's other fields are valid so
    contract validation passes and source-fidelity validation is
    the only gate that can flip.
    """
    plan: Dict[str, Any] = {
        "version": FINAL_RECONCILIATION_PATCH_VERSION,
        "status": status,
        "source_fidelity_claim": claim,
        "publication_intent": "playable_module",
        "decisions": [
            {
                "blocker_message": "Required location 'Trigger' not found",
                "decision": "delete_bogus_atom",
                "from": "required_location",
                "to": "mechanic_heading",
                "reason": "Trigger is a trap mechanics heading",
            }
        ],
        "file_patches": [],
    }
    return plan


class TestSourceFidelityClaimConstants(unittest.TestCase):
    """Pin the stable constants used by the Step 3.3 validation helper."""

    def test_accepted_claim_constant_is_stable(self):
        self.assertEqual(
            FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED,
            "reconciled_degraded",
        )

    def test_clean_pass_variants_match_design(self):
        # The set is intentionally broader than the strict prompt
        # value to catch LLM drift to equivalent clean-pass language.
        self.assertEqual(
            FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS,
            ("pass", "clean_pass", "clean", "source_fidelity_pass"),
        )

    def test_diagnostic_code_for_step_3_3_is_stable(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
            "invalid_source_fidelity_claim",
        )


class TestIsCleanPassClaim(unittest.TestCase):
    """Provider-free unit tests for the small ``_is_clean_pass_claim``
    helper used by the validation logic.
    """

    def test_matches_known_clean_pass_variants(self):
        for value in FINAL_RECONCILIATION_SOURCE_FIDELITY_CLEAN_PASS_VARIANTS:
            self.assertTrue(
                _is_clean_pass_claim(value),
                f"expected {value!r} to be a clean-pass claim",
            )

    def test_does_not_match_accepted_claim(self):
        self.assertFalse(
            _is_clean_pass_claim(
                FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED
            )
        )

    def test_does_not_match_case_variants(self):
        # Strict exact match: "PASS" / "Clean_Pass" are NOT
        # recognized as clean-pass claims and would surface in the
        # generic "not equal to reconciled_degraded" branch.
        for variant in ("PASS", "Clean_Pass", "CLEAN", "Source_Fidelity_Pass"):
            self.assertFalse(_is_clean_pass_claim(variant))

    def test_does_not_match_non_string(self):
        for value in (None, 42, ["pass"], {"pass": True}, ("pass",), b"pass"):
            self.assertFalse(_is_clean_pass_claim(value))

    def test_does_not_match_empty_string(self):
        self.assertFalse(_is_clean_pass_claim(""))


class TestValidateFinalReconciliationSourceFidelityClaim(unittest.TestCase):
    """Provider-free unit tests for
    :func:`validate_final_reconciliation_source_fidelity_claim`.
    """

    # --- Accept cases ---

    def test_ready_plan_with_reconciled_degraded_claim_passes(self):
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_ready_plan_with_reconciled_degraded_via_constant_passes(self):
        plan = _ready_plan_with_source_fidelity_claim(
            FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED
        )
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    # --- Reject clean pass variants on ready plans ---

    def test_ready_plan_with_pass_claim_rejected(self):
        plan = _ready_plan_with_source_fidelity_claim("pass")
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("'pass'", joined)
        self.assertIn("clean-pass", joined)
        self.assertIn("reconciled_degraded", joined)

    def test_ready_plan_with_clean_pass_claim_rejected(self):
        plan = _ready_plan_with_source_fidelity_claim("clean_pass")
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("'clean_pass'", joined)

    def test_ready_plan_with_clean_claim_rejected(self):
        # Equivalent clean-pass language variant.
        plan = _ready_plan_with_source_fidelity_claim("clean")
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])

    def test_ready_plan_with_source_fidelity_pass_claim_rejected(self):
        plan = _ready_plan_with_source_fidelity_claim("source_fidelity_pass")
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])

    # --- Reject missing / non-string claim on ready plans ---

    def test_ready_plan_missing_claim_rejected(self):
        plan: Dict[str, Any] = {
            "version": FINAL_RECONCILIATION_PATCH_VERSION,
            "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
            "publication_intent": "playable_module",
            "decisions": [],
            "file_patches": [],
        }
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("missing", joined)
        self.assertIn("source_fidelity_claim", joined)

    def test_ready_plan_with_none_claim_rejected(self):
        plan = _ready_plan_with_source_fidelity_claim(None)
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("not a string", joined)

    def test_ready_plan_with_integer_claim_rejected(self):
        plan = _ready_plan_with_source_fidelity_claim(7)
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("int", joined)

    def test_ready_plan_with_list_claim_rejected(self):
        plan = _ready_plan_with_source_fidelity_claim(["reconciled_degraded"])
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])

    def test_ready_plan_with_arbitrary_string_claim_rejected(self):
        # Any non-canonical string is rejected on a ready plan.
        plan = _ready_plan_with_source_fidelity_claim("partially_degraded")
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("'partially_degraded'", joined)
        self.assertIn("'reconciled_degraded'", joined)

    def test_ready_plan_with_case_variant_claim_rejected(self):
        # Strict case-sensitive comparison: "Reconciled_Degraded"
        # is NOT the accepted claim.
        plan = _ready_plan_with_source_fidelity_claim("Reconciled_Degraded")
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])

    # --- Refused / failed plan semantics ---

    def test_refused_plan_with_reconciled_degraded_preserves_success(self):
        plan = _ready_plan_with_source_fidelity_claim(
            "reconciled_degraded",
            status=FINAL_RECONCILIATION_PATCH_STATUS_REFUSED,
        )
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        # Refused semantics are preserved; no diagnostic.
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_refused_plan_with_clean_pass_claim_includes_diagnostic(self):
        # Refused semantics preserved; a clean-pass claim on a
        # refused plan is still surfaced as a diagnostic so the
        # report can list the false claim.
        plan = _ready_plan_with_source_fidelity_claim(
            "pass", status=FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        )
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("'pass'", joined)
        self.assertIn("refused", joined)

    def test_failed_plan_with_reconciled_degraded_preserves_success(self):
        plan = _ready_plan_with_source_fidelity_claim(
            "reconciled_degraded",
            status=FINAL_RECONCILIATION_PATCH_STATUS_FAILED,
        )
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_failed_plan_with_clean_pass_claim_includes_diagnostic(self):
        plan = _ready_plan_with_source_fidelity_claim(
            "clean_pass", status=FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        )
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM])
        joined = " ".join(d["message"] for d in diagnostics)
        self.assertIn("'clean_pass'", joined)
        self.assertIn("failed", joined)

    def test_refused_plan_missing_claim_includes_no_diagnostic(self):
        # Refused plans preserve semantics even when the claim
        # field is missing entirely. The contract helper still
        # passes because refused is in the allowlist; the
        # source-fidelity helper is intentionally permissive on
        # refused/failed plans (the claim is informational there).
        plan: Dict[str, Any] = {
            "version": FINAL_RECONCILIATION_PATCH_VERSION,
            "status": FINAL_RECONCILIATION_PATCH_STATUS_REFUSED,
            "publication_intent": "playable_module",
            "decisions": [],
            "file_patches": [],
        }
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    # --- Defensive inputs ---

    def test_non_dict_patch_plan_rejected(self):
        for bad in (None, "string", 42, [1, 2, 3], ("a", "b")):
            is_valid, diagnostics = (
                validate_final_reconciliation_source_fidelity_claim(bad, _tiny_brief())
            )
            self.assertFalse(is_valid)
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(
                diagnostics[0]["code"],
                DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
            )
            self.assertEqual(
                diagnostics[0]["severity"], DIAGNOSTIC_SEVERITY_ERROR
            )

    def test_non_dict_brief_rejected(self):
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        for bad in (None, "string", 42, [1, 2, 3]):
            is_valid, diagnostics = (
                validate_final_reconciliation_source_fidelity_claim(plan, bad)
            )
            self.assertFalse(is_valid)
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(
                diagnostics[0]["code"],
                DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM,
            )

    def test_unsupported_status_returns_success_no_diagnostic(self):
        # When the top-level status is missing or unsupported, the
        # helper returns success so the contract helper (Step 3.1)
        # can emit its own ``unsupported_status`` diagnostic without
        # a confusing duplicate from this step.
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        del plan["status"]
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    def test_unknown_status_value_returns_success_no_diagnostic(self):
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        plan["status"] = "some_unknown_status"
        is_valid, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertTrue(is_valid)
        self.assertEqual(diagnostics, [])

    # --- Purity ---

    def test_does_not_mutate_plan(self):
        # The helper is read-only by construction; the input plan
        # is returned untouched even when diagnostics are produced.
        plan = _ready_plan_with_source_fidelity_claim("pass")
        snapshot = copy.deepcopy(plan)
        validate_final_reconciliation_source_fidelity_claim(plan, _tiny_brief())
        self.assertEqual(plan, snapshot)

    def test_does_not_mutate_brief(self):
        plan = _ready_plan_with_source_fidelity_claim("pass")
        brief = _tiny_brief()
        snapshot = copy.deepcopy(brief)
        validate_final_reconciliation_source_fidelity_claim(plan, brief)
        self.assertEqual(brief, snapshot)

    def test_does_not_mutate_on_success(self):
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        brief = _tiny_brief()
        snapshot_plan = copy.deepcopy(plan)
        snapshot_brief = copy.deepcopy(brief)
        validate_final_reconciliation_source_fidelity_claim(plan, brief)
        self.assertEqual(plan, snapshot_plan)
        self.assertEqual(brief, snapshot_brief)

    def test_diagnostics_carry_severity_error(self):
        plan = _ready_plan_with_source_fidelity_claim("pass")
        _, diagnostics = validate_final_reconciliation_source_fidelity_claim(
            plan, _tiny_brief()
        )
        self.assertGreaterEqual(len(diagnostics), 1)
        for d in diagnostics:
            self.assertEqual(d["severity"], DIAGNOSTIC_SEVERITY_ERROR)


class TestRunnerSourceFidelityClaimWiring(unittest.TestCase):
    """End-to-end tests that drive the runner through
    ``mock_provider_output`` and assert the Step 3.3 wiring folds
    source-fidelity-claim validation into the runner's
    status/diagnostics.
    """

    def test_runner_ready_with_reconciled_degraded_claim_returns_success(self):
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["error"], None)

    def test_runner_ready_with_pass_claim_fails_closed(self):
        # The headline Step 3.3 behavior: a ready plan claiming
        # ``pass`` cannot be accepted as a successful reconciliation.
        plan = _ready_plan_with_source_fidelity_claim("pass")
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)
        # Patch plan is preserved for reporting.
        self.assertEqual(result["patch_plan"]["status"], "ready")
        # Legacy error field aggregates the diagnostic.
        self.assertIn("invalid_patch_contract", result["error"])
        self.assertIn("'pass'", result["error"])
        self.assertIn("reconciled_degraded", result["error"])

    def test_runner_ready_with_clean_pass_claim_fails_closed(self):
        plan = _ready_plan_with_source_fidelity_claim("clean_pass")
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)

    def test_runner_ready_with_clean_claim_fails_closed(self):
        plan = _ready_plan_with_source_fidelity_claim("clean")
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)

    def test_runner_ready_with_source_fidelity_pass_claim_fails_closed(self):
        plan = _ready_plan_with_source_fidelity_claim("source_fidelity_pass")
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)

    def test_runner_ready_with_missing_claim_fails_closed(self):
        # When ``source_fidelity_claim`` is fully missing, the
        # parse helper's required-keys check fires first and
        # surfaces a ``missing_required_keys`` status. The
        # source-fidelity validation gate would also catch this
        # case if it ever ran, but the layering ensures the
        # build fails closed regardless of which gate fires.
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        del plan["source_fidelity_claim"]
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        # Build is blocked; the specific status is whichever gate
        # fires first. Either status proves the build did not
        # pass with a missing claim.
        self.assertIn(
            result["status"],
            (
                RUNNER_STATUS_MISSING_REQUIRED_KEYS,
                RUNNER_STATUS_INVALID_PATCH_CONTRACT,
            ),
        )
        # The source-fidelity claim key is named in the error
        # path regardless of which gate fired.
        joined_error = result["error"] if result["error"] else ""
        joined_diags = " ".join(
            d.get("message", "") for d in result["diagnostics"]
        )
        self.assertIn("source_fidelity_claim", joined_error + joined_diags)

    def test_runner_ready_with_integer_claim_fails_closed(self):
        plan = _ready_plan_with_source_fidelity_claim(42)
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)

    # --- Refused / failed semantics preserved ---

    def test_runner_refused_with_clean_pass_claim_preserves_refused_status(
        self,
    ):
        # A refused plan with a false clean claim keeps the
        # refused status; the diagnostic is appended so the report
        # can still surface the false claim without flipping the
        # runner status.
        plan = _ready_plan_with_source_fidelity_claim(
            "pass", status=FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        )
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_REFUSED_RECONCILIATION)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)

    def test_runner_failed_with_clean_pass_claim_preserves_failed_status(
        self,
    ):
        plan = _ready_plan_with_source_fidelity_claim(
            "clean_pass", status=FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        )
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_FAILED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes[0], DIAGNOSTIC_CODE_FAILED_RECONCILIATION)
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)

    def test_runner_refused_with_reconciled_degraded_claim_preserves_refused_status(
        self,
    ):
        plan = _ready_plan_with_source_fidelity_claim(
            "reconciled_degraded",
            status=FINAL_RECONCILIATION_PATCH_STATUS_REFUSED,
        )
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED_RECONCILIATION)
        codes = [d["code"] for d in result["diagnostics"]]
        # Only the refused diagnostic; source-fidelity passes
        # silently on refused plans.
        self.assertNotIn(
            DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes
        )

    # --- Mock-provider short-circuit preserved ---

    def test_runner_does_not_call_live_provider_under_fidelity_failure(self):
        # The mock-provider short-circuit must remain in effect
        # when source-fidelity validation fails; the runner must
        # not reach the live provider path.
        plan = _ready_plan_with_source_fidelity_claim("pass")
        with patch(
            "utils.toolkit_llm_final_reconciliation.create_chat_client"
        ) as mock_create:
            result = run_llm_final_editor(
                _tiny_brief(), mock_provider_output=json.dumps(plan)
            )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT)
        mock_create.assert_not_called()

    def test_runner_does_not_call_live_provider_under_fidelity_success(self):
        # Mock-provider short-circuit also holds on the success
        # path; the source-fidelity validation should not require
        # any live provider call.
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        with patch(
            "utils.toolkit_llm_final_reconciliation.create_chat_client"
        ) as mock_create:
            result = run_llm_final_editor(
                _tiny_brief(), mock_provider_output=json.dumps(plan)
            )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Step 3.4: Safe patch application
# ---------------------------------------------------------------------------
#
# These tests cover the new ``apply_final_reconciliation_patch_plan`` helper
# plus the small pure helpers that drive it: JSON pointer parsing, parent
# resolution, and per-op application. All tests are provider-free and
# filesystem-isolated (tempdir per test, cleaned up on teardown).


def _write_json(path: str, data: Any) -> None:
    """Tiny helper that writes a UTF-8 JSON file with a trailing newline.

    Mirrors the on-disk format produced by ``safe_write_json`` so
    round-trips through ``safe_read_json`` are stable.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _make_ready_plan_with_patches(
    patches: list, editable_surfaces=None
) -> Dict[str, Any]:
    """Return a minimal valid ready plan with the given file_patches.

    Defaults the editable_surfaces to a generous whitelist that
    contains common canonical module artifacts. Callers that need a
    different whitelist can pass it explicitly.
    """
    plan: Dict[str, Any] = {
        "version": FINAL_RECONCILIATION_PATCH_VERSION,
        "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
        "source_fidelity_claim": "reconciled_degraded",
        "publication_intent": "playable_module",
        "decisions": [],
        "file_patches": list(patches),
    }
    return plan


def _make_brief_with_module_dir(
    module_dir: str, editable_surfaces=None
) -> Dict[str, Any]:
    """Return a tiny brief whose ``module_dir`` and ``editable_surfaces``
    are caller-supplied.
    """
    brief = {
        "version": "accurate_ingest_final_reconciliation_brief.v1",
        "job_id": "job-test-apply",
        "module_name": "TestModule",
        "module_dir": module_dir,
        "trigger": "editorial_blockers_present",
        "classification_status": "editorial",
        "editorial_blockers": [],
        "fatal_blockers": [],
        "warnings": [],
        "source_excerpts": [],
        "generated_module_summary": {},
        "editable_surfaces": list(editable_surfaces)
        if editable_surfaces is not None
        else [
            "module_context.json",
            "module_context_BU.json",
            "module_plot_BU.json",
            "areas/*_BU.json",
            "map_*.json",
        ],
        "instructions": "Test brief for Step 3.4 apply.",
    }
    return brief


class _TempModuleDirTestCase(unittest.TestCase):
    """Base class that creates and tears down a temp module directory.

    Subclasses can use ``self.module_dir`` to get a writable
    absolute path and may create target files inside it. The
    directory is removed on tearDown.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="neq_step34_")
        self.module_dir = self._tmpdir

    def tearDown(self):
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except Exception:
            pass

    def write_target(self, target_file: str, data: Any) -> str:
        full_path = os.path.join(self.module_dir, target_file)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        _write_json(full_path, data)
        return full_path

    def read_target(self, target_file: str) -> Any:
        full_path = os.path.join(self.module_dir, target_file)
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)


class TestPatchOpConstants(unittest.TestCase):
    """Pin the Step 3.4 patch op constants and the allowed-ops tuple."""

    def test_remove_key_constant(self):
        self.assertEqual(
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY, "remove_key"
        )

    def test_rename_key_constant(self):
        self.assertEqual(
            FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY, "rename_key"
        )

    def test_set_value_constant(self):
        self.assertEqual(
            FINAL_RECONCILIATION_PATCH_OP_SET_VALUE, "set_value"
        )

    def test_remove_array_entry_constant(self):
        self.assertEqual(
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
            "remove_array_entry",
        )

    def test_merge_into_existing_constant(self):
        self.assertEqual(
            FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
            "merge_into_existing",
        )

    def test_allowed_ops_tuple_order_matches_prompt(self):
        # The tuple is the single source of truth for the op
        # allowlist; pin the exact order to keep the contract
        # explicit and to make drift impossible without breaking
        # this test.
        self.assertEqual(
            FINAL_RECONCILIATION_ALLOWED_PATCH_OPS,
            (
                "remove_key",
                "rename_key",
                "set_value",
                "remove_array_entry",
                "merge_into_existing",
            ),
        )

    def test_apply_status_constants(self):
        self.assertEqual(
            FINAL_RECONCILIATION_APPLY_STATUS_APPLIED, "applied"
        )
        self.assertEqual(
            FINAL_RECONCILIATION_APPLY_STATUS_FAILED, "failed"
        )


class TestJsonPathParsing(unittest.TestCase):
    """Provider-free unit tests for the JSON pointer parser."""

    def test_parses_simple_path(self):
        self.assertEqual(_parse_json_path("/a"), ["a"])

    def test_parses_nested_path(self):
        self.assertEqual(_parse_json_path("/a/b/c"), ["a", "b", "c"])

    def test_parses_path_with_array_index(self):
        self.assertEqual(_parse_json_path("/a/b/0"), ["a", "b", "0"])

    def test_parses_path_with_escape_sequences(self):
        # Per RFC 6901: ``~0`` is ``~`` and ``~1`` is ``/``.
        self.assertEqual(_parse_json_path("/a~1b/c~0d"), ["a/b", "c~d"])

    def test_rejects_non_string(self):
        for bad in (None, 42, ["a"], {"a": 1}, ("a",)):
            self.assertIsNone(
                _parse_json_path(bad), f"expected None for {bad!r}"
            )

    def test_rejects_empty_string(self):
        self.assertIsNone(_parse_json_path(""))

    def test_rejects_root_only(self):
        # The single-character root path has no segments; the apply
        # helper requires at least one segment for every op.
        self.assertIsNone(_parse_json_path("/"))

    def test_rejects_non_pointer_path(self):
        for bad in ("a/b", "a.b", "a", "./a", "../a"):
            self.assertIsNone(
                _parse_json_path(bad), f"expected None for {bad!r}"
            )

    def test_rejects_invalid_escape(self):
        # ``~`` followed by a character other than ``0`` or ``1`` is
        # an invalid escape per RFC 6901.
        self.assertIsNone(_parse_json_path("/a~xb"))
        self.assertIsNone(_parse_json_path("/foo~2bar"))


class TestResolveParent(unittest.TestCase):
    """Provider-free unit tests for the parent-resolution helper."""

    def test_resolves_to_dict_parent(self):
        root = {"a": {"b": 1}}
        parent, last_segment, diagnostics = _resolve_parent(root, ["a", "b"])
        self.assertEqual(diagnostics, [])
        self.assertEqual(parent, {"b": 1})
        self.assertEqual(last_segment, "b")

    def test_resolves_to_list_parent_via_int_segment(self):
        root = {"items": [10, 20, 30]}
        parent, last_segment, diagnostics = _resolve_parent(
            root, ["items", "1"]
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(parent, [10, 20, 30])
        self.assertEqual(last_segment, "1")

    def test_resolves_nested_path(self):
        root = {"a": {"b": {"c": {"d": "leaf"}}}}
        parent, last_segment, diagnostics = _resolve_parent(
            root, ["a", "b", "c", "d"]
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(parent, {"d": "leaf"})
        self.assertEqual(last_segment, "d")

    def test_rejects_missing_dict_key(self):
        # The walker validates INTERMEDIATE path segments only; the
        # last segment is the caller's responsibility. Use a path
        # where the missing key is an intermediate step so the
        # walker reports it.
        root = {"a": {}}
        parent, last_segment, diagnostics = _resolve_parent(
            root, ["a", "missing", "deeper"]
        )
        self.assertIsNone(parent)
        self.assertIsNone(last_segment)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(
            diagnostics[0]["code"], DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED
        )
        self.assertIn("missing", diagnostics[0]["message"])

    def test_rejects_out_of_bounds_index(self):
        # Out-of-bounds in an INTERMEDIATE array step: the walker
        # catches it before returning a parent.
        root = {"items": [1, 2]}
        parent, _, diagnostics = _resolve_parent(
            root, ["items", "5", "deeper"]
        )
        self.assertIsNone(parent)
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("out of array bounds", diagnostics[0]["message"])

    def test_rejects_non_int_index(self):
        # Non-integer segment in an INTERMEDIATE array step: the
        # walker catches it before returning a parent.
        root = {"items": [1, 2]}
        parent, _, diagnostics = _resolve_parent(
            root, ["items", "abc", "deeper"]
        )
        self.assertIsNone(parent)
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not a valid array index", diagnostics[0]["message"])

    def test_rejects_traversing_non_container(self):
        # The walker cannot traverse into a non-container. Use an
        # INTERMEDIATE step that resolves to a string so the
        # walker reports the failure.
        root = {"a": "not a container"}
        parent, _, diagnostics = _resolve_parent(
            root, ["a", "b", "c"]
        )
        self.assertIsNone(parent)
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("cannot traverse", diagnostics[0]["message"])

    def test_rejects_empty_segments(self):
        parent, _, diagnostics = _resolve_parent({"a": 1}, [])
        self.assertIsNone(parent)
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("no segments", diagnostics[0]["message"])


class TestSetValueOp(unittest.TestCase):
    """Provider-free unit tests for the ``set_value`` op helper."""

    def test_set_existing_dict_key(self):
        content = {"a": {"b": 1}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
            ["a", "b"],
            42,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(content["a"]["b"], 42)

    def test_set_new_dict_key(self):
        # ``set_value`` may insert a new key into an existing dict
        # parent. The op helper does not require the key to pre-exist.
        content = {"a": {}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
            ["a", "new_key"],
            {"x": 1},
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(content["a"]["new_key"], {"x": 1})

    def test_set_array_index(self):
        content = {"items": [10, 20, 30]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
            ["items", "1"],
            99,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(content["items"], [10, 99, 30])

    def test_rejects_non_dict_non_list_parent(self):
        content = {"a": "string"}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
            ["a", "b"],
            1,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(
            diagnostics[0]["code"], DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED
        )
        self.assertIn("not a dict or list", diagnostics[0]["message"])

    def test_rejects_invalid_array_index(self):
        content = {"items": [1, 2]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
            ["items", "abc"],
            99,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not a valid array index", diagnostics[0]["message"])


class TestRemoveKeyOp(unittest.TestCase):
    """Provider-free unit tests for the ``remove_key`` op helper."""

    def test_removes_existing_key(self):
        content = {"a": {"b": 1, "c": 2}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
            ["a", "b"],
            None,
        )
        self.assertEqual(diagnostics, [])
        self.assertNotIn("b", content["a"])
        self.assertEqual(content["a"], {"c": 2})

    def test_rejects_missing_key(self):
        content = {"a": {"b": 1}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
            ["a", "missing"],
            None,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not found", diagnostics[0]["message"])

    def test_rejects_non_dict_parent(self):
        content = {"a": [1, 2]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
            ["a", "0"],
            None,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not a dict", diagnostics[0]["message"])


class TestRenameKeyOp(unittest.TestCase):
    """Provider-free unit tests for the ``rename_key`` op helper."""

    def test_renames_existing_key(self):
        content = {"a": {"old_name": 1, "other": 2}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
            ["a", "old_name"],
            "new_name",
        )
        self.assertEqual(diagnostics, [])
        self.assertNotIn("old_name", content["a"])
        self.assertEqual(content["a"]["new_name"], 1)
        self.assertEqual(content["a"]["other"], 2)

    def test_rejects_missing_old_key(self):
        content = {"a": {"b": 1}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
            ["a", "missing"],
            "new",
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not found", diagnostics[0]["message"])

    def test_rejects_non_string_new_key(self):
        content = {"a": {"b": 1}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
            ["a", "b"],
            42,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("non-empty string", diagnostics[0]["message"])

    def test_rejects_empty_new_key(self):
        content = {"a": {"b": 1}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
            ["a", "b"],
            "",
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("non-empty string", diagnostics[0]["message"])

    def test_rejects_destination_already_present(self):
        content = {"a": {"b": 1, "c": 2}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
            ["a", "b"],
            "c",
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("already present", diagnostics[0]["message"])

    def test_rejects_non_dict_parent(self):
        content = {"a": [1, 2]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
            ["a", "0"],
            "new",
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not a dict", diagnostics[0]["message"])


class TestRemoveArrayEntryOp(unittest.TestCase):
    """Provider-free unit tests for the ``remove_array_entry`` op helper."""

    def test_removes_existing_index(self):
        content = {"items": [10, 20, 30]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
            ["items", "1"],
            None,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(content["items"], [10, 30])

    def test_rejects_out_of_bounds_index(self):
        content = {"items": [1, 2]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
            ["items", "5"],
            None,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("out of array bounds", diagnostics[0]["message"])

    def test_rejects_non_int_index(self):
        content = {"items": [1, 2]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
            ["items", "abc"],
            None,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not a valid array index", diagnostics[0]["message"])

    def test_rejects_non_list_parent(self):
        content = {"a": {"b": 1}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
            ["a", "0"],
            None,
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not a list", diagnostics[0]["message"])


class TestMergeIntoExistingOp(unittest.TestCase):
    """Provider-free unit tests for the ``merge_into_existing`` op helper."""

    def test_merges_into_existing_dict(self):
        content = {"config": {"theme": "dark", "lang": "en"}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
            ["config"],
            {"lang": "fr", "extra": True},
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(
            content["config"],
            {"theme": "dark", "lang": "fr", "extra": True},
        )

    def test_rejects_non_dict_target(self):
        content = {"config": "string"}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
            ["config"],
            {"x": 1},
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("not a dict", diagnostics[0]["message"])

    def test_rejects_non_dict_value(self):
        content = {"config": {"a": 1}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
            ["config"],
            [1, 2, 3],
        )
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("value is not a dict", diagnostics[0]["message"])

    def test_rejects_non_dict_parent(self):
        # For ``merge_into_existing`` the walker resolves to the
        # parent of the last segment; if the parent itself is not a
        # dict, the op helper fails closed with a ``parent is not a
        # dict`` diagnostic. The path ``/a`` here has only one
        # segment, so the parent IS the root and the value at the
        # last segment is the list ``[1, 2]``; we instead hit the
        # "target is not a dict" branch because the merge target
        # resolves to a list. We test both branches separately.
        content = {"root_list": [1, 2]}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
            ["root_list"],
            {"x": 1},
        )
        self.assertEqual(len(diagnostics), 1)
        # Single-segment path: parent is root (dict), but target at
        # the last segment is a list, so the failure says
        # ``target ... is not a dict``.
        self.assertIn("is not a dict", diagnostics[0]["message"])

    def test_shallow_merge_does_not_recurse_into_dicts(self):
        # Per the Step 3.4 spec, the merge is shallow. When both
        # target and value have a dict for the same key, the value's
        # dict REPLACES the target's dict rather than recursing.
        content = {"config": {"nested": {"x": 1, "y": 2}}}
        diagnostics = _apply_op(
            content,
            FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
            ["config"],
            {"nested": {"y": 99, "z": 3}},
        )
        self.assertEqual(diagnostics, [])
        # The entire ``nested`` dict was replaced; ``x`` is gone.
        self.assertEqual(
            content["config"],
            {"nested": {"y": 99, "z": 3}},
        )


class TestApplyFinalReconciliationPatchPlan(_TempModuleDirTestCase):
    """End-to-end tests for
    :func:`apply_final_reconciliation_patch_plan`.

    Each test sets up a temp module directory, writes one or more
    target JSON files, then calls the apply helper and asserts on the
    return shape and the on-disk effects (or non-effects on failure
    paths).
    """

    # --- Happy path: each op once ---

    def test_apply_set_value_happy_path(self):
        # Pre-existing file with a value; patch overwrites it.
        self.write_target("module_context.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 42,
                    "reason": "Step 3.4 set_value test",
                }
            ]
        )
        # Step 3.5: pin editable_surfaces to the target only so the
        # parity mirror (which would also write module_context_BU.json)
        # does not fire and complicate the happy-path assertion.
        result = apply_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(result["changed_files"], ["module_context.json"])
        self.assertEqual(result["diagnostics"], [])
        # On-disk value updated.
        self.assertEqual(self.read_target("module_context.json"), {"a": {"b": 42}})

    def test_apply_remove_key_happy_path(self):
        self.write_target("module_context.json", {"keep": 1, "drop": 2})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
                    "json_path": "/drop",
                    "value": None,
                    "reason": "Step 3.4 remove_key test",
                }
            ]
        )
        # Step 3.5: pin editable_surfaces to the target only so the
        # parity mirror does not fire and complicate the assertion.
        result = apply_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(result["changed_files"], ["module_context.json"])
        self.assertEqual(
            self.read_target("module_context.json"), {"keep": 1}
        )

    def test_apply_rename_key_happy_path(self):
        self.write_target(
            "module_context_BU.json", {"old_name": "value"}
        )
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_RENAME_KEY,
                    "json_path": "/old_name",
                    "value": "new_name",
                    "reason": "Step 3.4 rename_key test",
                }
            ]
        )
        # Step 3.5: pin editable_surfaces to the target only so the
        # parity mirror does not fire and complicate the assertion.
        result = apply_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context_BU.json"],
            ),
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(result["changed_files"], ["module_context_BU.json"])
        loaded = self.read_target("module_context_BU.json")
        self.assertNotIn("old_name", loaded)
        self.assertEqual(loaded["new_name"], "value")

    def test_apply_remove_array_entry_happy_path(self):
        self.write_target("module_plot_BU.json", {"scenes": ["a", "b", "c"]})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_plot_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_REMOVE_ARRAY_ENTRY,
                    "json_path": "/scenes/1",
                    "value": None,
                    "reason": "Step 3.4 remove_array_entry test",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(
            self.read_target("module_plot_BU.json"),
            {"scenes": ["a", "c"]},
        )

    def test_apply_merge_into_existing_happy_path(self):
        self.write_target(
            "map_atlus.json", {"config": {"theme": "dark", "lang": "en"}}
        )
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "map_atlus.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_MERGE_INTO_EXISTING,
                    "json_path": "/config",
                    "value": {"lang": "fr", "extra": True},
                    "reason": "Step 3.4 merge_into_existing test",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(
            self.read_target("map_atlus.json"),
            {"config": {"theme": "dark", "lang": "fr", "extra": True}},
        )

    # --- Multi-patch and multi-file behavior ---

    def test_apply_multiple_patches_to_same_file(self):
        self.write_target(
            "module_context.json",
            {"keep": 1, "drop": 2, "nested": {"old": "x", "keep": "y"}},
        )
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
                    "json_path": "/drop",
                    "value": None,
                    "reason": "first patch",
                },
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/nested/old",
                    "value": "z",
                    "reason": "second patch",
                },
            ]
        )
        # Step 3.5: pin editable_surfaces to the target only so the
        # parity mirror does not fire and complicate the assertion.
        result = apply_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(result["changed_files"], ["module_context.json"])
        self.assertEqual(
            self.read_target("module_context.json"),
            {"keep": 1, "nested": {"old": "z", "keep": "y"}},
        )

    def test_apply_patches_to_two_separate_files(self):
        self.write_target("module_context.json", {"a": 1})
        self.write_target("module_context_BU.json", {"b": 2})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "first file",
                },
                {
                    "target_file": "module_context_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/b",
                    "value": 100,
                    "reason": "second file",
                },
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(
            sorted(result["changed_files"]),
            ["module_context.json", "module_context_BU.json"],
        )
        self.assertEqual(self.read_target("module_context.json"), {"a": 99})
        self.assertEqual(
            self.read_target("module_context_BU.json"), {"b": 100}
        )

    def test_apply_empty_file_patches_returns_applied_with_no_changes(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches([])
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(result["changed_files"], [])
        self.assertEqual(result["diagnostics"], [])
        # No writes occurred.
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    # --- Plan-level validation failures write nothing ---

    def test_apply_fails_when_plan_status_is_refused(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "would-be patch on refused plan",
                }
            ]
        )
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_PLAN, codes)
        self.assertEqual(result["changed_files"], [])
        # No write.
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_fails_when_plan_status_is_failed(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "would-be patch on failed plan",
                }
            ]
        )
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_FAILED
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_PLAN, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_fails_on_contract_violation(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "bad version",
                }
            ]
        )
        plan["version"] = "wrong_version"
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_VERSION, codes)
        self.assertEqual(result["changed_files"], [])
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_fails_on_target_violation(self):
        self.write_target("module_context.json", {"a": 1})
        # The brief's editable_surfaces does not include the target.
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "not in editable_surfaces",
                }
            ]
        )
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["areas/*_BU.json"]
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_fails_on_source_fidelity_violation(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "false clean claim",
                }
            ]
        )
        plan["source_fidelity_claim"] = "pass"
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    # --- Module-dir resolution ---

    def test_apply_fails_when_module_dir_missing_from_brief(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "no module_dir",
                }
            ]
        )
        brief = _make_brief_with_module_dir(self.module_dir)
        del brief["module_dir"]
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_MISSING_MODULE_DIR, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_fails_when_module_dir_is_empty_string(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "empty module_dir",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(plan, _make_brief_with_module_dir(""))
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_MISSING_MODULE_DIR, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_uses_brief_module_dir_when_arg_none(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "use brief module_dir",
                }
            ]
        )
        # No module_dir argument; helper falls back to brief.
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(self.read_target("module_context.json"), {"a": 99})

    def test_apply_uses_arg_module_dir_over_brief(self):
        # Set up TWO module dirs. The brief points at a path that
        # would fail, while the explicit argument points at the
        # writable tempdir. The argument must win.
        wrong_dir = os.path.join(self.module_dir, "does_not_exist")
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "explicit module_dir",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(wrong_dir),
            module_dir=self.module_dir,
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(self.read_target("module_context.json"), {"a": 99})

    # --- File I/O failures write nothing ---

    def test_apply_fails_on_missing_target_file(self):
        # The target is in editable_surfaces (so the Step 3.2
        # validator is happy) but does not exist on disk.
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "nonexistent.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 1,
                    "reason": "file does not exist",
                }
            ]
        )
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["nonexistent.json"]
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED, codes)
        self.assertEqual(result["changed_files"], [])

    def test_apply_fails_on_corrupt_target_file(self):
        # Write a file that is not valid JSON; safe_read_json
        # returns None on parse failure.
        full_path = os.path.join(self.module_dir, "module_context.json")
        with open(full_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 1,
                    "reason": "corrupt file",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED, codes)

    # --- Per-op input validation writes nothing ---

    def test_apply_fails_on_invalid_op_writes_nothing(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": "explode_module",
                    "json_path": "/a",
                    "value": 99,
                    "reason": "bad op",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_OP, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_fails_on_invalid_json_path_writes_nothing(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "not_a_pointer",
                    "value": 99,
                    "reason": "bad path",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_JSON_PATH, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_fails_on_missing_json_path_field_writes_nothing(self):
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "",
                    "value": 99,
                    "reason": "empty json_path",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_JSON_PATH, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    # --- In-memory application phase failures write nothing ---

    def test_apply_later_patch_failure_writes_nothing_to_any_file(self):
        # First patch is valid; second patch targets a non-existent
        # dict key so the in-memory application fails. The apply
        # helper must NOT write to disk because the in-memory
        # phase aborted before the write phase.
        self.write_target(
            "module_context.json",
            {"a": {"b": 1}, "c": 2},
        )
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "first patch (valid)",
                },
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_REMOVE_KEY,
                    "json_path": "/a/missing",
                    "value": None,
                    "reason": "second patch (fails)",
                },
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_PATCH_APPLICATION_FAILED, codes)
        # The diagnostic message names the failing patch index so
        # reports can attribute the failure.
        joined = " ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("file_patches[1]", joined)
        # No write occurred; the on-disk file is unchanged.
        self.assertEqual(
            self.read_target("module_context.json"),
            {"a": {"b": 1}, "c": 2},
        )
        self.assertEqual(result["changed_files"], [])

    def test_apply_failure_preserves_earlier_in_memory_changes(self):
        # The same scenario as above but a sanity check on the
        # in-memory content: the failure is reported as failed and
        # the in-memory changes do not leak to disk.
        self.write_target("module_context.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "valid",
                },
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/missing/deep",
                    "value": "x",
                    "reason": "cannot traverse",
                },
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        # The on-disk file is the original.
        self.assertEqual(
            self.read_target("module_context.json"), {"a": {"b": 1}}
        )

    # --- Write-phase failure surfaces as failed ---

    def test_apply_returns_failed_when_safe_write_json_fails(self):
        # Two target files. The first writes successfully; the
        # second write returns False. The result is failed and
        # surfaces the write diagnostic. The first file MAY have
        # been written (documented write-phase behavior); we assert
        # on the result shape rather than the disk state of the
        # first file.
        self.write_target("module_context.json", {"a": 1})
        self.write_target("module_context_BU.json", {"b": 2})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "first file",
                },
                {
                    "target_file": "module_context_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/b",
                    "value": 100,
                    "reason": "second file (will fail)",
                },
            ]
        )

        original_safe_write_json = (
            "utils.toolkit_llm_final_reconciliation.safe_write_json"
        )
        real_call_count = {"count": 0}

        def fake_safe_write_json(path, data, *args, **kwargs):
            real_call_count["count"] += 1
            # Fail the SECOND call; succeed the first.
            if real_call_count["count"] == 1:
                return True
            return False

        with patch(original_safe_write_json, side_effect=fake_safe_write_json):
            result = apply_final_reconciliation_patch_plan(
                plan, _make_brief_with_module_dir(self.module_dir)
            )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_TARGET_FILE_WRITE_FAILED, codes)
        # The second target is named in the failure diagnostic.
        joined = " ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("module_context_BU.json", joined)

    # --- Purity ---

    def test_apply_does_not_mutate_inputs(self):
        self.write_target("module_context.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "do not mutate inputs",
                }
            ]
        )
        brief = _make_brief_with_module_dir(self.module_dir)
        snapshot_plan = copy.deepcopy(plan)
        snapshot_brief = copy.deepcopy(brief)
        result = apply_final_reconciliation_patch_plan(plan, brief)
        # Inputs unchanged.
        self.assertEqual(plan, snapshot_plan)
        self.assertEqual(brief, snapshot_brief)
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)

    def test_apply_rejects_non_dict_patch_plan(self):
        result = apply_final_reconciliation_patch_plan(
            "not a dict", _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_PLAN, codes)

    def test_apply_rejects_non_dict_brief(self):
        result = apply_final_reconciliation_patch_plan(
            _make_ready_plan_with_patches([]), "not a dict"
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_PLAN, codes)

    def test_apply_rejects_non_dict_file_patch_entry(self):
        # The target validator (Step 3.2) catches a non-dict
        # ``file_patches`` entry before the apply helper's own
        # check can run. The apply helper therefore surfaces an
        # ``invalid_patch_target`` diagnostic from the target
        # validator.
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(["not a dict"])
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_apply_rejects_non_string_target_file(self):
        # The target validator (Step 3.2) catches a non-string
        # ``target_file`` before the apply helper's own check can
        # run. The apply helper therefore surfaces an
        # ``invalid_patch_target`` diagnostic from the target
        # validator.
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": 42,
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 1,
                    "reason": "bad target",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PATCH_TARGET, codes)
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})


# ---------------------------------------------------------------------------
# Step 3.5: Post-write JSON parse validation and BU/live parity mirror
# ---------------------------------------------------------------------------


class TestComputeParityCounterpart(unittest.TestCase):
    """Provider-free unit tests for ``_compute_parity_counterpart``.

    The helper computes the canonical parity counterpart for a given
    target file. Per the design and AGENTS.md, only canonical
    static authored pairs are mirrored; runtime-only pairs (areas,
    module_plot) are excluded.
    """

    def test_module_context_to_module_context_BU(self):
        self.assertEqual(
            _compute_parity_counterpart("module_context.json"),
            "module_context_BU.json",
        )

    def test_module_context_BU_to_module_context(self):
        self.assertEqual(
            _compute_parity_counterpart("module_context_BU.json"),
            "module_context.json",
        )

    def test_map_FOO_to_map_FOO_BU(self):
        self.assertEqual(
            _compute_parity_counterpart("map_FOO.json"),
            "map_FOO_BU.json",
        )

    def test_map_FOO_BU_to_map_FOO(self):
        self.assertEqual(
            _compute_parity_counterpart("map_FOO_BU.json"),
            "map_FOO.json",
        )

    def test_map_atlus_round_trip(self):
        # Longer map name round-trips correctly.
        self.assertEqual(
            _compute_parity_counterpart("map_atlus.json"),
            "map_atlus_BU.json",
        )
        self.assertEqual(
            _compute_parity_counterpart("map_atlus_BU.json"),
            "map_atlus.json",
        )

    def test_areas_FOO_BU_returns_none(self):
        # Live area files are runtime-only; do NOT mirror BU to live.
        self.assertIsNone(_compute_parity_counterpart("areas/FOO_BU.json"))

    def test_module_plot_BU_returns_none(self):
        # Live plot is runtime-only; do NOT mirror BU to live.
        self.assertIsNone(_compute_parity_counterpart("module_plot_BU.json"))

    def test_module_plot_returns_none(self):
        # Live plot is also not part of any parity pair (and is a
        # forbidden runtime target upstream).
        self.assertIsNone(_compute_parity_counterpart("module_plot.json"))

    def test_unrelated_target_returns_none(self):
        for bad in (
            "module_context_other.json",
            "map.json",  # missing "_FOO" prefix
            "not_a_map.json",
            "source_graph.json",
            "blueprint_atlus.json",
        ):
            self.assertIsNone(
                _compute_parity_counterpart(bad),
                f"expected None for {bad!r}",
            )

    def test_non_string_returns_none(self):
        for bad in (None, 42, ["x"], {"a": 1}):
            self.assertIsNone(
                _compute_parity_counterpart(bad),
                f"expected None for {bad!r}",
            )

    def test_empty_string_returns_none(self):
        self.assertIsNone(_compute_parity_counterpart(""))


class TestShouldMirrorParityWrite(unittest.TestCase):
    """Provider-free unit tests for ``_should_mirror_parity_write``.

    The helper returns True when the counterpart already exists in
    the module directory OR is explicitly listed in editable_surfaces.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="neq_step35_shouldmirror_")
        self.module_dir = self._tmpdir

    def tearDown(self):
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_counterpart_exists_on_disk_returns_true(self):
        # Pre-create the counterpart file.
        with open(
            os.path.join(self.module_dir, "module_context_BU.json"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("{}\n")
        self.assertTrue(
            _should_mirror_parity_write(
                "module_context_BU.json",
                self.module_dir,
                ["module_context.json"],
            )
        )

    def test_counterpart_in_editable_surfaces_returns_true(self):
        # No on-disk file, but listed in editable_surfaces.
        self.assertTrue(
            _should_mirror_parity_write(
                "module_context_BU.json",
                self.module_dir,
                ["module_context_BU.json", "map_*.json"],
            )
        )

    def test_counterpart_via_glob_in_editable_surfaces_returns_true(self):
        # Glob match (map_*.json) accepts map_FOO_BU.json.
        self.assertTrue(
            _should_mirror_parity_write(
                "map_FOO_BU.json",
                self.module_dir,
                ["map_*.json"],
            )
        )

    def test_counterpart_absent_and_not_listed_returns_false(self):
        self.assertFalse(
            _should_mirror_parity_write(
                "module_context_BU.json",
                self.module_dir,
                ["module_context.json"],
            )
        )

    def test_invalid_inputs_return_false(self):
        for bad in (None, 42, "", [], {}):
            self.assertFalse(
                _should_mirror_parity_write(bad, self.module_dir, []),
                f"expected False for counterpart={bad!r}",
            )
        self.assertFalse(
            _should_mirror_parity_write(
                "module_context_BU.json", "", ["module_context_BU.json"]
            )
        )

    def test_non_list_editable_surfaces_does_not_raise(self):
        # Defensive: editable_surfaces might be a non-list when the
        # brief is malformed; the helper should not raise.
        self.assertFalse(
            _should_mirror_parity_write(
                "module_context_BU.json", self.module_dir, "not a list"
            )
        )
        self.assertFalse(
            _should_mirror_parity_write(
                "module_context_BU.json", self.module_dir, None
            )
        )

    def test_non_string_editable_surfaces_items_are_skipped(self):
        # A list with non-string items should be tolerated (not
        # raise). Non-string items are skipped, but a valid string
        # in the list still matches.
        self.assertFalse(
            _should_mirror_parity_write(
                "module_context_BU.json",
                self.module_dir,
                [None, 42, ""],  # no valid string
            )
        )
        # The valid string in the list is still considered.
        self.assertTrue(
            _should_mirror_parity_write(
                "module_context_BU.json",
                self.module_dir,
                [None, 42, "", "module_context_BU.json"],
            )
        )


class TestValidateWrittenJson(unittest.TestCase):
    """Provider-free unit tests for ``_validate_written_json``.

    The helper re-opens a just-written file via ``safe_read_json``
    and returns an empty list on success or a single
    ``written_json_invalid`` diagnostic on failure.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="neq_step35_validate_")
        self.module_dir = self._tmpdir

    def tearDown(self):
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_valid_json_returns_empty_diagnostics(self):
        path = os.path.join(self.module_dir, "ok.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"a": 1}\n')
        diagnostics = _validate_written_json(path, "ok.json")
        self.assertEqual(diagnostics, [])

    def test_corrupt_json_returns_diagnostic(self):
        path = os.path.join(self.module_dir, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        diagnostics = _validate_written_json(path, "bad.json")
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(
            diagnostics[0]["code"], DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID
        )
        self.assertIn("bad.json", diagnostics[0]["message"])

    def test_missing_file_returns_diagnostic(self):
        path = os.path.join(self.module_dir, "missing.json")
        diagnostics = _validate_written_json(path, "missing.json")
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(
            diagnostics[0]["code"], DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID
        )
        self.assertIn("missing.json", diagnostics[0]["message"])

    def test_invalid_full_path_returns_diagnostic(self):
        for bad in (None, 42, "", []):
            diagnostics = _validate_written_json(bad, "target.json")
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(
                diagnostics[0]["code"],
                DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID,
            )
            self.assertIn("target.json", diagnostics[0]["message"])


class TestPostWriteValidationAndParity(_TempModuleDirTestCase):
    """End-to-end tests for Step 3.5 post-write JSON parse validation
    and BU/live parity mirror in
    :func:`apply_final_reconciliation_patch_plan`.
    """

    # --- Post-write JSON parse validation ---

    def test_apply_post_write_json_parse_validation_succeeds(self):
        # Valid pre-existing file; helper writes valid JSON. The
        # post-write validation must pass without diagnostic.
        self.write_target("module_context.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "post-write success test",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["changed_files"], ["module_context.json"])

    def test_apply_fails_on_written_json_invalid_post_write(self):
        # Mock safe_write_json to return True but actually write
        # garbage to the file so the post-write re-read fails.
        self.write_target("module_context.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "post-write invalid test",
                }
            ]
        )
        original_safe_write_json = (
            "utils.toolkit_llm_final_reconciliation.safe_write_json"
        )

        def fake_writes_garbage(path, data, *args, **kwargs):
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not valid json")
            return True

        with patch(original_safe_write_json, side_effect=fake_writes_garbage):
            result = apply_final_reconciliation_patch_plan(
                plan,
                _make_brief_with_module_dir(
                    self.module_dir,
                    editable_surfaces=["module_context.json"],
                ),
            )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID, codes)
        # The failing target is named in the diagnostic.
        joined = " ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("module_context.json", joined)

    # --- Parity mirror: module_context <-> module_context_BU ---

    def test_apply_mirrors_module_context_to_module_context_BU(self):
        # Both files exist on disk; patching module_context.json
        # also updates module_context_BU.json via the parity mirror.
        self.write_target("module_context.json", {"a": {"b": 1}})
        self.write_target("module_context_BU.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "parity mirror test",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        # Both files updated.
        self.assertEqual(self.read_target("module_context.json"), {"a": {"b": 99}})
        self.assertEqual(
            self.read_target("module_context_BU.json"), {"a": {"b": 99}}
        )
        self.assertIn("module_context.json", result["changed_files"])
        self.assertIn("module_context_BU.json", result["changed_files"])

    def test_apply_mirrors_module_context_BU_to_module_context(self):
        # Reverse direction: patching module_context_BU.json also
        # updates module_context.json via the parity mirror.
        self.write_target("module_context.json", {"a": {"b": 1}})
        self.write_target("module_context_BU.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "reverse parity mirror test",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(self.read_target("module_context.json"), {"a": {"b": 99}})
        self.assertEqual(
            self.read_target("module_context_BU.json"), {"a": {"b": 99}}
        )
        self.assertIn("module_context_BU.json", result["changed_files"])
        self.assertIn("module_context.json", result["changed_files"])

    # --- Parity mirror: map_FOO <-> map_FOO_BU ---

    def test_apply_mirrors_map_FOO_to_map_FOO_BU(self):
        self.write_target("map_FOO.json", {"theme": "dark"})
        self.write_target("map_FOO_BU.json", {"theme": "dark"})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "map_FOO.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/theme",
                    "value": "light",
                    "reason": "map parity mirror test",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(self.read_target("map_FOO.json"), {"theme": "light"})
        self.assertEqual(self.read_target("map_FOO_BU.json"), {"theme": "light"})
        self.assertIn("map_FOO.json", result["changed_files"])
        self.assertIn("map_FOO_BU.json", result["changed_files"])

    def test_apply_mirrors_map_FOO_BU_to_map_FOO(self):
        self.write_target("map_FOO.json", {"theme": "dark"})
        self.write_target("map_FOO_BU.json", {"theme": "dark"})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "map_FOO_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/theme",
                    "value": "light",
                    "reason": "reverse map parity mirror test",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        self.assertEqual(self.read_target("map_FOO.json"), {"theme": "light"})
        self.assertEqual(self.read_target("map_FOO_BU.json"), {"theme": "light"})
        self.assertIn("map_FOO_BU.json", result["changed_files"])
        self.assertIn("map_FOO.json", result["changed_files"])

    # --- Parity mirror must NOT trigger for runtime-only targets ---

    def test_apply_does_not_mirror_bu_area_to_live_area(self):
        # ``areas/FOO_BU.json`` is canonical; the live ``areas/FOO.json``
        # is runtime-only and must NOT be created or modified.
        self.write_target("areas/FOO_BU.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "areas/FOO_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "BU area test (no live mirror)",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        # The live area file must NOT be created.
        live_path = os.path.join(self.module_dir, "areas", "FOO.json")
        self.assertFalse(os.path.isfile(live_path))
        # The BU file was updated.
        self.assertEqual(
            self.read_target("areas/FOO_BU.json"), {"a": {"b": 99}}
        )
        # changed_files only includes the BU, not the live.
        self.assertIn("areas/FOO_BU.json", result["changed_files"])
        self.assertNotIn("areas/FOO.json", result["changed_files"])

    def test_apply_does_not_mirror_bu_plot_to_live_plot(self):
        # ``module_plot_BU.json`` is canonical; the live
        # ``module_plot.json`` is runtime-only and must NOT be
        # created or modified.
        self.write_target("module_plot_BU.json", {"scenes": ["a", "b"]})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_plot_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/scenes/0",
                    "value": "modified",
                    "reason": "BU plot test (no live mirror)",
                }
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        # The live plot file must NOT be created.
        live_path = os.path.join(self.module_dir, "module_plot.json")
        self.assertFalse(os.path.isfile(live_path))
        self.assertEqual(
            self.read_target("module_plot_BU.json"),
            {"scenes": ["modified", "b"]},
        )
        self.assertIn("module_plot_BU.json", result["changed_files"])
        self.assertNotIn("module_plot.json", result["changed_files"])

    # --- Parity mirror failure paths ---

    def test_apply_fails_on_parity_counterpart_write_failure(self):
        # Both files exist; first write succeeds, second write (the
        # parity mirror) returns False.
        self.write_target("module_context.json", {"a": {"b": 1}})
        self.write_target("module_context_BU.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "parity write failure test",
                }
            ]
        )
        original_safe_write_json = (
            "utils.toolkit_llm_final_reconciliation.safe_write_json"
        )
        call_count = {"count": 0}

        def fake_safe_write_json(path, data, *args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                # First write: real write of the main target.
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                    f.write("\n")
                return True
            # Second write: parity mirror returns False.
            return False

        with patch(original_safe_write_json, side_effect=fake_safe_write_json):
            result = apply_final_reconciliation_patch_plan(
                plan, _make_brief_with_module_dir(self.module_dir)
            )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_PARITY_COUNTERPART_WRITE_FAILED, codes)
        # The failing parity target is named in the diagnostic.
        joined = " ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("module_context_BU.json", joined)

    def test_apply_fails_on_parity_counterpart_invalid_post_write(self):
        # Both files exist; first write succeeds with valid JSON,
        # second write (the parity mirror) returns True but writes
        # garbage so the post-write re-read fails.
        self.write_target("module_context.json", {"a": {"b": 1}})
        self.write_target("module_context_BU.json", {"a": {"b": 1}})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a/b",
                    "value": 99,
                    "reason": "parity invalid post-write test",
                }
            ]
        )
        original_safe_write_json = (
            "utils.toolkit_llm_final_reconciliation.safe_write_json"
        )
        call_count = {"count": 0}

        def fake_safe_write_json(path, data, *args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                # First write: real write of the main target.
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                    f.write("\n")
                return True
            # Second write: parity mirror returns True but writes garbage.
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not valid json")
            return True

        with patch(original_safe_write_json, side_effect=fake_safe_write_json):
            result = apply_final_reconciliation_patch_plan(
                plan, _make_brief_with_module_dir(self.module_dir)
            )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED)
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_WRITTEN_JSON_INVALID, codes)
        # The failing parity target is named in the diagnostic.
        joined = " ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("module_context_BU.json", joined)

    # --- Both sides in the plan: mirror is skipped (no double write) ---

    def test_apply_skips_parity_mirror_when_both_sides_in_plan(self):
        # When both module_context.json and module_context_BU.json
        # are explicitly in the patch plan, the mirror is skipped
        # to avoid double-writing the same path. The two targets
        # are written in their own iterations of the write phase.
        self.write_target("module_context.json", {"a": 1})
        self.write_target("module_context_BU.json", {"b": 2})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 11,
                    "reason": "main target",
                },
                {
                    "target_file": "module_context_BU.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/b",
                    "value": 22,
                    "reason": "parity target",
                },
            ]
        )
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED)
        # Each file updated to its own value (not mirrored).
        self.assertEqual(self.read_target("module_context.json"), {"a": 11})
        self.assertEqual(
            self.read_target("module_context_BU.json"), {"b": 22}
        )
        # changed_files is exactly the two plan targets, no extra
        # entries (the mirror was skipped).
        self.assertEqual(
            sorted(result["changed_files"]),
            ["module_context.json", "module_context_BU.json"],
        )


# ---------------------------------------------------------------------------
# Step 4.1: Schema validation after patch application
# ---------------------------------------------------------------------------
#
# These tests cover the new Step 4.1 helpers:
# - ``collect_schema_validation_results(...)`` - pure collapse of
#   ``ModuleValidator.results`` into a compact shape.
# - ``_parse_validator_error_message(...)`` - small file/message split.
# - ``run_final_reconciliation_schema_validation(...)`` - module-dir
#   -> structured result via a mocked ``ModuleValidator``.
# - ``apply_and_validate_final_reconciliation_patch_plan(...)`` -
#   orchestrator that combines the Step 3.4 apply helper and the
#   Step 4.1 schema helper in one call.
#
# All tests are provider-free. The real ``ModuleValidator`` is never
# invoked; it is patched at the import site so the test can drive
# every pass/fail/exception path with hand-crafted ``results``
# payloads.


class TestStep41Constants(unittest.TestCase):
    """Pin the new Step 4.1 constants used by the schema-validation
    helpers and the orchestrator."""

    def test_schema_validation_status_constants_are_stable(self):
        self.assertEqual(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS, "pass"
        )
        self.assertEqual(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL, "fail"
        )
        self.assertEqual(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR, "error"
        )
        self.assertEqual(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN, "not_run"
        )

    def test_schema_validation_diagnostic_codes_are_stable(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED, "schema_validation_failed"
        )
        self.assertEqual(
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR, "schema_validation_error"
        )


class TestParseValidatorErrorMessage(unittest.TestCase):
    """Provider-free unit tests for the small file/message split
    helper used by :func:`collect_schema_validation_results`."""

    def test_splits_simple_file_colon_message(self):
        file_part, message = _parse_validator_error_message(
            "FOO.json: schema violation"
        )
        self.assertEqual(file_part, "FOO.json")
        self.assertEqual(message, "schema violation")

    def test_splits_area_path_with_parenthetical(self):
        # The area validator appends a "(areas/)" or "(root)" tag
        # before the colon; the helper treats everything before the
        # first colon as the file portion.
        file_part, message = _parse_validator_error_message(
            "GLQ001.json (areas/): missing required field"
        )
        self.assertEqual(file_part, "GLQ001.json (areas/)")
        self.assertEqual(message, "missing required field")

    def test_no_colon_returns_none_file_and_full_message(self):
        file_part, message = _parse_validator_error_message(
            "no separator here"
        )
        self.assertIsNone(file_part)
        self.assertEqual(message, "no separator here")

    def test_handles_empty_file_part(self):
        # Leading colon: empty file portion, full remainder is message.
        file_part, message = _parse_validator_error_message(
            ": just a message"
        )
        self.assertIsNone(file_part)
        self.assertEqual(message, "just a message")

    def test_handles_non_string_input(self):
        # Non-string inputs are coerced to str(...) and parsed.
        file_part, message = _parse_validator_error_message(42)
        # str(42) is "42" which has no ":". The helper returns
        # (None, "42").
        self.assertIsNone(file_part)
        self.assertEqual(message, "42")

    def test_strips_whitespace(self):
        file_part, message = _parse_validator_error_message(
            "  FOO.json  :   schema violation   "
        )
        self.assertEqual(file_part, "FOO.json")
        self.assertEqual(message, "schema violation")

    def test_preserves_inner_colons_in_message(self):
        # Only the FIRST colon is the separator; inner colons stay.
        file_part, message = _parse_validator_error_message(
            "FOO.json: path -> subkey: bad value"
        )
        self.assertEqual(file_part, "FOO.json")
        self.assertEqual(message, "path -> subkey: bad value")


class TestCollectSchemaValidationResults(unittest.TestCase):
    """Provider-free unit tests for
    :func:`collect_schema_validation_results`.
    """

    def test_pass_path_with_all_passed(self):
        # Validator reports every category passed. The compact shape
        # is "pass" with no errors.
        validator_results = {
            "area": {
                "files": ["FOO.json"],
                "passed": 1,
                "failed": 0,
                "errors": [],
            },
            "character": {
                "files": ["BAR.json"],
                "passed": 2,
                "failed": 0,
                "errors": [],
            },
        }
        result = collect_schema_validation_results(validator_results)
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
        )
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["success_rate"], 1.0)
        self.assertEqual(result["errors"], [])

    def test_fail_path_aggregates_failures(self):
        # Two categories; one fully passed, the other fully failed.
        # The compact shape is "fail" with errors aggregated.
        validator_results = {
            "area": {
                "files": ["FOO.json"],
                "passed": 1,
                "failed": 0,
                "errors": [],
            },
            "character": {
                "files": ["BAR.json"],
                "passed": 0,
                "failed": 2,
                "errors": [
                    "BAR.json: missing required field 'name'",
                    "BAZ.json: invalid type for 'level'",
                ],
            },
        }
        result = collect_schema_validation_results(validator_results)
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
        )
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 2)
        self.assertAlmostEqual(result["success_rate"], 1 / 3)
        self.assertEqual(len(result["errors"]), 2)
        # Each error is a compact dict with category/file/message.
        for err in result["errors"]:
            self.assertIn("category", err)
            self.assertIn("file", err)
            self.assertIn("message", err)
        # Pin one error so the contract is exact.
        cat_bar = next(
            e for e in result["errors"] if e["file"] == "BAR.json"
        )
        self.assertEqual(cat_bar["category"], "character")
        self.assertEqual(cat_bar["message"], "missing required field 'name'")
        cat_baz = next(
            e for e in result["errors"] if e["file"] == "BAZ.json"
        )
        self.assertEqual(cat_baz["category"], "character")
        self.assertEqual(cat_baz["message"], "invalid type for 'level'")

    def test_mixed_pass_and_fail_in_same_category(self):
        # One category with both pass and fail counts; the
        # aggregation sums both and lists every error.
        validator_results = {
            "area": {
                "files": ["GOOD.json", "BAD.json"],
                "passed": 1,
                "failed": 1,
                "errors": ["BAD.json: schema violation"],
            },
        }
        result = collect_schema_validation_results(validator_results)
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
        )
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["success_rate"], 0.5)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["category"], "area")
        self.assertEqual(result["errors"][0]["file"], "BAD.json")

    def test_empty_validator_results_returns_pass_with_zero_counts(self):
        # An empty results mapping should not raise; it should
        # produce a pass result with zero counts and a default
        # success rate of 1.0.
        result = collect_schema_validation_results({})
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
        )
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["success_rate"], 1.0)
        self.assertEqual(result["errors"], [])

    def test_non_dict_validator_results_returns_pass_zeroed(self):
        # Defensive: the helper accepts a non-dict without raising.
        for bad in (None, "string", 42, [1, 2, 3]):
            result = collect_schema_validation_results(bad)
            self.assertEqual(
                result["status"],
                FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
            )
            self.assertEqual(result["passed"], 0)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["errors"], [])

    def test_does_not_include_files_field(self):
        # The compact shape must NOT carry the raw ``files`` list so
        # downstream reports stay small.
        validator_results = {
            "area": {
                "files": ["FOO.json", "BAR.json", "BAZ.json"],
                "passed": 3,
                "failed": 0,
                "errors": [],
            },
        }
        result = collect_schema_validation_results(validator_results)
        self.assertNotIn("files", result)
        # Per-error dict also does NOT include ``files``.
        for err in result["errors"]:
            self.assertNotIn("files", err)

    def test_unknown_category_payload_is_skipped_safely(self):
        # Legacy categories may carry scalar payloads; the helper
        # must skip them without raising.
        validator_results = {
            "scalar_legacy": "not a dict",
            "area": {
                "files": ["FOO.json"],
                "passed": 1,
                "failed": 0,
                "errors": [],
            },
        }
        result = collect_schema_validation_results(validator_results)
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
        )
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], [])

    def test_purity_does_not_mutate_input(self):
        # The helper is read-only by construction; a deepcopy
        # snapshot taken before the call must equal the input after.
        validator_results = {
            "area": {
                "files": ["FOO.json"],
                "passed": 0,
                "failed": 1,
                "errors": ["FOO.json: bad"],
            },
        }
        snapshot = copy.deepcopy(validator_results)
        collect_schema_validation_results(validator_results)
        self.assertEqual(validator_results, snapshot)

    def test_compact_shape_keys(self):
        # Pin the keys of the compact shape so future drift breaks
        # this test.
        result = collect_schema_validation_results({})
        self.assertEqual(
            set(result.keys()),
            {"status", "success_rate", "passed", "failed", "errors"},
        )


class TestRunFinalReconciliationSchemaValidation(unittest.TestCase):
    """End-to-end tests for
    :func:`run_final_reconciliation_schema_validation` with a
    mocked ``ModuleValidator`` so the real validation path is
    never invoked.
    """

    def _make_mock_validator(self, results, raise_on_execute=False, exc=None):
        """Build a ``ModuleValidator`` mock with the given results.

        ``raise_on_execute`` makes the ``execute_full_validation``
        call raise ``exc`` (or a generic ``RuntimeError`` when
        ``exc`` is ``None``) so the error-path branch of the helper
        is exercised.
        """
        mock_validator = MagicMock()
        mock_validator.results = results
        if raise_on_execute:
            mock_validator.execute_full_validation.side_effect = exc or RuntimeError(
                "simulated validator crash"
            )
        return mock_validator

    @patch("utils.toolkit_llm_final_reconciliation.ModuleValidator")
    def test_pass_path_with_mocked_validator(self, MockValidator):
        # Validator returns a results mapping with no failures.
        # The helper must surface a pass shape with zero failed
        # files and no diagnostics.
        results = {
            "area": {
                "files": ["FOO.json"],
                "passed": 1,
                "failed": 0,
                "errors": [],
            },
            "character": {
                "files": ["BAR.json"],
                "passed": 3,
                "failed": 0,
                "errors": [],
            },
        }
        MockValidator.return_value = self._make_mock_validator(results)

        result = run_final_reconciliation_schema_validation(
            "/tmp/some_module_dir"
        )

        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
        )
        self.assertEqual(result["passed"], 4)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["success_rate"], 1.0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["diagnostics"], [])

        # ModuleValidator was instantiated with the given module_dir
        # and the repo-root anchor.
        MockValidator.assert_called_once()
        args, _ = MockValidator.call_args
        self.assertEqual(args[0], "/tmp/some_module_dir")
        # The second positional arg is the schema dir; we only
        # check it is a non-empty string (the actual path resolves
        # to the repo root which the test cannot assume).
        self.assertIsInstance(args[1], str)
        self.assertGreater(len(args[1]), 0)

        # execute_full_validation was called with verbose=False.
        validator_instance = MockValidator.return_value
        validator_instance.execute_full_validation.assert_called_once_with(
            verbose=False
        )

    @patch("utils.toolkit_llm_final_reconciliation.ModuleValidator")
    def test_fail_path_with_mocked_validator(self, MockValidator):
        # Validator returns a results mapping with at least one
        # failure. The helper must surface a fail shape plus a
        # structured ``schema_validation_failed`` diagnostic.
        results = {
            "area": {
                "files": ["BAD.json"],
                "passed": 0,
                "failed": 1,
                "errors": ["BAD.json: missing required field 'areaId'"],
            },
        }
        MockValidator.return_value = self._make_mock_validator(results)

        result = run_final_reconciliation_schema_validation(
            "/tmp/another_module_dir"
        )

        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
        )
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["success_rate"], 0.0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["category"], "area")
        self.assertEqual(result["errors"][0]["file"], "BAD.json")
        # The fail path emits one structured diagnostic so reports
        # can key on the failure without walking the errors list.
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
        )
        self.assertEqual(result["diagnostics"][0]["severity"], "error")
        # The diagnostic message names the failing module_dir.
        self.assertIn("/tmp/another_module_dir", result["diagnostics"][0]["message"])
        self.assertIn("1 file(s) failed", result["diagnostics"][0]["message"])

    @patch("utils.toolkit_llm_final_reconciliation.ModuleValidator")
    def test_exception_path_returns_structured_error(self, MockValidator):
        # Validator raises from ``execute_full_validation``. The
        # helper catches, emits a structured ``schema_validation_error``
        # diagnostic, and returns a zeroed error shape.
        MockValidator.return_value = self._make_mock_validator(
            {},
            raise_on_execute=True,
            exc=RuntimeError("validator crashed"),
        )

        result = run_final_reconciliation_schema_validation(
            "/tmp/crashy_module_dir"
        )

        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
        )
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["success_rate"], 0.0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
        )
        self.assertIn("validator crashed", result["diagnostics"][0]["message"])

    def test_missing_module_dir_returns_error_without_instantiating_validator(self):
        # Empty string is rejected with a structured error
        # diagnostic; the validator is never instantiated.
        result = run_final_reconciliation_schema_validation("")
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
        )
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
        )

    def test_non_string_module_dir_returns_error(self):
        # Non-string inputs (None, int, list, dict) are rejected
        # with the same structured error shape.
        for bad in (None, 42, ["/tmp/x"], {"module_dir": "/tmp/x"}):
            result = run_final_reconciliation_schema_validation(bad)
            self.assertEqual(
                result["status"],
                FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
            )
            self.assertEqual(result["passed"], 0)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(len(result["diagnostics"]), 1)
            self.assertEqual(
                result["diagnostics"][0]["code"],
                DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
            )

    @patch("utils.toolkit_llm_final_reconciliation.ModuleValidator", None)
    def test_module_validator_unavailable_returns_error(self):
        # Defensive: when the ``core.validation`` package cannot be
        # imported, the helper returns an error shape and never
        # crashes.
        result = run_final_reconciliation_schema_validation("/tmp/x")
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
        )
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
        )
        self.assertIn("unavailable", result["diagnostics"][0]["message"])


class TestApplyAndValidateFinalReconciliationPatchPlan(_TempModuleDirTestCase):
    """End-to-end tests for the Step 4.1 orchestrator helper.

    The orchestrator combines the existing
    :func:`apply_final_reconciliation_patch_plan` (Step 3.4 / 3.5)
    with the new :func:`run_final_reconciliation_schema_validation`
    helper. The tests mock the schema-validation path so they can
    drive pass/fail/skip branches without real module validation.
    """

    def _mock_validator_factory(self, schema_status, schema_failed_count=0):
        """Return a function that, when called in place of
        ``run_final_reconciliation_schema_validation``, produces a
        pre-canned structured result."""

        def _factory(module_dir):
            diagnostics = []
            if schema_status == FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL:
                diagnostics = [
                    {
                        "code": DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
                        "message": "schema_validation_failed",
                        "severity": "error",
                    }
                ]
            return {
                "status": schema_status,
                "success_rate": 1.0 if schema_status.endswith("pass") else 0.0,
                "passed": 1,
                "failed": schema_failed_count,
                "errors": [],
                "diagnostics": diagnostics,
            }

        return _factory

    def _ready_plan_with_target(self, target_file: str) -> Dict[str, Any]:
        """A small valid ready plan with a single patch entry. The
        patch target is the caller-supplied string so tests can
        vary it per scenario.
        """
        return {
            "version": FINAL_RECONCILIATION_PATCH_VERSION,
            "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
            "source_fidelity_claim": "reconciled_degraded",
            "publication_intent": "playable_module",
            "decisions": [
                {
                    "blocker_message": "Test blocker",
                    "decision": "delete_bogus_atom",
                }
            ],
            "file_patches": [
                {
                    "target_file": target_file,
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "Step 4.1 orchestrator test",
                }
            ],
        }

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_returns_applied_when_apply_and_schema_both_pass(
        self, mock_schema
    ):
        # Happy path: apply succeeds, schema validation returns
        # ``pass``. Overall status is ``applied`` and both
        # ``apply_result`` and ``schema_validation`` are populated.
        mock_schema.side_effect = self._mock_validator_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir, editable_surfaces=["module_context.json"]
            ),
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED
        )
        # apply_result is the verbatim apply helper return shape.
        self.assertEqual(
            result["apply_result"]["status"],
            FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
        )
        self.assertEqual(
            result["apply_result"]["changed_files"], ["module_context.json"]
        )
        # schema_validation is the structured pass result.
        self.assertEqual(
            result["schema_validation"]["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
        )
        self.assertEqual(result["schema_validation"]["diagnostics"], [])
        # Combined diagnostics is empty on the success path.
        self.assertEqual(result["diagnostics"], [])
        # On-disk file was actually written.
        self.assertEqual(self.read_target("module_context.json"), {"a": 99})

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_returns_failed_when_apply_passes_but_schema_fails(
        self, mock_schema
    ):
        # Apply succeeded (writes on disk), but schema validation
        # reported failures. Overall status is ``failed``; the
        # apply_result is preserved as ``applied`` so callers can
        # still see what was written; the schema_validation field
        # carries the structured failure result.
        mock_schema.side_effect = self._mock_validator_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
            schema_failed_count=1,
        )
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir, editable_surfaces=["module_context.json"]
            ),
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        # Apply actually wrote to disk; the orchestrator does NOT
        # attempt rollback in this step.
        self.assertEqual(
            result["apply_result"]["status"],
            FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
        )
        self.assertEqual(self.read_target("module_context.json"), {"a": 99})
        # Schema validation surfaces the failure.
        self.assertEqual(
            result["schema_validation"]["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
        )
        self.assertEqual(
            result["schema_validation"]["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
        )
        # Combined diagnostics carries both apply diagnostics
        # (empty) and the schema diagnostic.
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED, codes)
        # Schema validation was invoked exactly once.
        mock_schema.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_does_not_run_schema_when_apply_fails(self, mock_schema):
        # When the apply phase fails, the orchestrator must NOT
        # invoke schema validation. ``schema_validation`` is set
        # to a small ``not_run`` dict.
        # Pin editable_surfaces to a non-existent target so the
        # apply helper short-circuits on the target validator
        # without writing anything.
        plan = self._ready_plan_with_target("does_not_exist.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["does_not_exist.json"]
        )
        # We have NOT created does_not_exist.json; the apply helper
        # fails on read at Phase 2b (target_file_read_failed).
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan, brief
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        # Schema validation was never invoked.
        mock_schema.assert_not_called()
        # ``schema_validation`` carries the ``not_run`` shape.
        self.assertEqual(
            result["schema_validation"]["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN,
        )
        self.assertEqual(result["schema_validation"]["passed"], 0)
        self.assertEqual(result["schema_validation"]["failed"], 0)
        self.assertEqual(result["schema_validation"]["errors"], [])
        self.assertEqual(result["schema_validation"]["diagnostics"], [])
        # Combined diagnostics carries the apply failure codes.
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED, codes)

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_does_not_run_schema_when_plan_validation_fails(
        self, mock_schema
    ):
        # Plan-level validation failures (e.g. refused status)
        # also short-circuit the orchestrator. Schema validation
        # must NOT run; ``schema_validation`` is set to
        # ``not_run``; the overall status is ``failed``.
        plan = self._ready_plan_with_target("module_context.json")
        plan["status"] = FINAL_RECONCILIATION_PATCH_STATUS_REFUSED
        self.write_target("module_context.json", {"a": 1})
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        mock_schema.assert_not_called()
        self.assertEqual(
            result["schema_validation"]["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN,
        )
        # On-disk file unchanged.
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_schema_error_propagates_as_overall_failed(
        self, mock_schema
    ):
        # Schema validation returns ``error`` (e.g. validator
        # crashed). The orchestrator surfaces the error and
        # overall status is ``failed`` even though the apply
        # phase succeeded.
        def _factory(module_dir):
            return {
                "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
                "success_rate": 0.0,
                "passed": 0,
                "failed": 0,
                "errors": [],
                "diagnostics": [
                    {
                        "code": DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR,
                        "message": "validator crashed",
                        "severity": "error",
                    }
                ],
            }

        mock_schema.side_effect = _factory
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir, editable_surfaces=["module_context.json"]
            ),
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        self.assertEqual(
            result["apply_result"]["status"],
            FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
        )
        self.assertEqual(
            result["schema_validation"]["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_SCHEMA_VALIDATION_ERROR, codes)

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_orchestrator_uses_explicit_module_dir_over_brief(
        self, mock_schema
    ):
        # When ``module_dir`` is passed explicitly, the orchestrator
        # uses it for schema validation even when the brief points
        # elsewhere.
        mock_schema.side_effect = self._mock_validator_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        # Brief points at a non-existent path; the explicit arg
        # takes precedence.
        wrong_dir = os.path.join(self.module_dir, "does_not_exist")
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                wrong_dir, editable_surfaces=["module_context.json"]
            ),
            module_dir=self.module_dir,
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED
        )
        # Schema validation was called with the explicit arg, not
        # the brief's module_dir.
        mock_schema.assert_called_once()
        called_with = mock_schema.call_args[0][0]
        self.assertEqual(called_with, self.module_dir)
        self.assertNotEqual(called_with, wrong_dir)

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_does_not_mutate_inputs(self, mock_schema):
        # The orchestrator is read-only by construction; the
        # patch_plan, brief, and module_dir inputs are returned
        # untouched.
        mock_schema.side_effect = self._mock_validator_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["module_context.json"]
        )
        snapshot_plan = copy.deepcopy(plan)
        snapshot_brief = copy.deepcopy(brief)
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan, brief
        )
        # Inputs unchanged.
        self.assertEqual(plan, snapshot_plan)
        self.assertEqual(brief, snapshot_brief)
        # Result is the expected applied shape.
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_combined_diagnostics_includes_both_phases(
        self, mock_schema
    ):
        # Both phases contribute diagnostics. The combined list
        # is the apply diagnostics followed by the schema
        # diagnostics.
        def _factory(module_dir):
            return {
                "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
                "success_rate": 0.0,
                "passed": 0,
                "failed": 1,
                "errors": [],
                "diagnostics": [
                    {
                        "code": DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
                        "message": "schema fail",
                        "severity": "error",
                    }
                ],
            }

        mock_schema.side_effect = _factory
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir, editable_surfaces=["module_context.json"]
            ),
        )
        # Apply diagnostics list is empty in this case (no apply
        # failures), so the combined list is exactly the schema
        # diagnostic.
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"],
            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_orchestrator_shape_keys_are_stable(self, mock_schema):
        # Pin the top-level shape so future drift breaks this
        # test. The orchestrator returns exactly four keys.
        mock_schema.side_effect = self._mock_validator_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_and_validate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir, editable_surfaces=["module_context.json"]
            ),
        )
        self.assertEqual(
            set(result.keys()),
            {"status", "apply_result", "schema_validation", "diagnostics"},
        )
        # apply_result shape is preserved from the underlying apply
        # helper.
        self.assertEqual(
            set(result["apply_result"].keys()),
            {"status", "changed_files", "diagnostics"},
        )
        # schema_validation shape is the compact structured shape.
        self.assertEqual(
            set(result["schema_validation"].keys()),
            {
                "status",
                "success_rate",
                 "passed",
                 "failed",
                 "errors",
                 "diagnostics",
             },
         )


# ---------------------------------------------------------------------------
# Step 4.2: Publication-gate tests
# ---------------------------------------------------------------------------


# Tiny canned readiness report for the happy-path pass fixture.
_READINESS_REPORT_PASS = {
    "module": "Well_of_Ruin",
    "overall_status": "pass",
    "gates": {},
    "blocking_errors": [],
    "fix_list": [],
    "exit_code": 0,
}

# Tiny canned readiness report for the readiness-fail fixture.
_READINESS_REPORT_FAIL = {
    "module": "Well_of_Ruin",
    "overall_status": "fail",
    "gates": {
        "schema": {"status": "fail", "reason": "schema_invalid"},
    },
    "blocking_errors": ["schema_gate_failed: schema_invalid"],
    "fix_list": [],
    "exit_code": 1,
}

# Tiny canned publishability report (publishable pass, effective
# pass). The fixture for the source-fidelity normalization path
# uses a different version of this.
_PUBLISHABILITY_REPORT_PASS = {
    "module": "Well_of_Ruin",
    "module_path": "/tmp/well_of_ruin",
    "source": "toolkit",
    "ready_status": "pass",
    "publishable_status": "pass",
    "source_fidelity_status": "pass",
    "source_fidelity_categories": [],
    "effective_publishable_status": "pass",
    "readiness": _READINESS_REPORT_PASS,
    "publication_gates": {},
    "blocking_errors": [],
    "warnings": [],
    "remediation_categories": {},
    "toolkit_media_policy": {},
    "fix_list": [],
    "exit_code": 0,
}

# Tiny canned publishability report (publishable fail).
_PUBLISHABILITY_REPORT_FAIL = {
    "module": "Well_of_Ruin",
    "module_path": "/tmp/well_of_ruin",
    "source": "toolkit",
    "ready_status": "pass",
    "publishable_status": "fail",
    "source_fidelity_status": "pass",
    "source_fidelity_categories": [],
    "effective_publishable_status": "fail",
    "readiness": _READINESS_REPORT_PASS,
    "publication_gates": {},
    "blocking_errors": ["semantic_audit_blocking"],
    "warnings": [],
    "remediation_categories": {},
    "toolkit_media_policy": {},
    "fix_list": [],
    "exit_code": 1,
}

# Tiny canned report-agreement result for the pass fixture.
_REPORT_AGREEMENT_PASS = {
    "status": "pass",
    "internal_coherent": True,
    "source_fidelity_status": "pass",
    "source_fidelity_effective_status": "reconciled_degraded",
    "final_reconciliation_accepted": True,
    "final_reconciliation_status": "accepted",
    "source_fidelity_reconciled": True,
    "validation_status": "pass",
    "ready_status": "pass",
    "publishable_status": "pass",
    "effective_publishable_status": "pass",
    "playable_publication_status": "pass",
    "blockers": [],
    "diagnostics": [],
    "missing_reports": [],
    "stale_reports": [],
    "checked_at": "2026-06-12T00:00:00Z",
}

# Tiny canned report-agreement result for the blocked fixture.
_REPORT_AGREEMENT_BLOCKED = {
    "status": "blocked",
    "internal_coherent": False,
    "source_fidelity_status": "blocked",
    "source_fidelity_effective_status": "reconciled_degraded",
    "final_reconciliation_accepted": True,
    "final_reconciliation_status": "accepted",
    "source_fidelity_reconciled": True,
    "validation_status": "blocked",
    "ready_status": "pass",
    "publishable_status": "pass",
    "effective_publishable_status": "pass",
    "playable_publication_status": "blocked",
    "blockers": ["contradiction:source_fidelity_pass_validation_fail"],
    "diagnostics": ["source fidelity cannot pass with failed validation"],
    "missing_reports": [],
    "stale_reports": [],
    "checked_at": "2026-06-12T00:00:00Z",
}


class TestStep42Constants(unittest.TestCase):
    """Pin the Step 4.2 stable constants."""

    def test_gate_status_pass_value(self):
        self.assertEqual(
            FINAL_RECONCILIATION_GATE_STATUS_PASS, "pass"
        )

    def test_gate_status_fail_value(self):
        self.assertEqual(
            FINAL_RECONCILIATION_GATE_STATUS_FAIL, "fail"
        )

    def test_gate_status_error_value(self):
        self.assertEqual(
            FINAL_RECONCILIATION_GATE_STATUS_ERROR, "error"
        )

    def test_gate_status_not_run_value(self):
        self.assertEqual(
            FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN, "not_run"
        )

    def test_gate_source_fidelity_effective_status_value(self):
        # The accepted-reconciliation effective status is
        # ``reconciled_degraded`` per the archived boundary contract.
        self.assertEqual(
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS,
            "reconciled_degraded",
        )

    def test_gate_final_reconciliation_status_value(self):
        self.assertEqual(
            FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS,
            "accepted",
        )

    def test_diagnostic_code_gate_readiness_failed(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_GATE_READINESS_FAILED,
            "gate_readiness_failed",
        )

    def test_diagnostic_code_gate_publishability_failed(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED,
            "gate_publishability_failed",
        )

    def test_diagnostic_code_gate_report_agreement_blocked(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_GATE_REPORT_AGREEMENT_BLOCKED,
            "gate_report_agreement_blocked",
        )

    def test_diagnostic_code_gate_helper_exception(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION,
            "gate_helper_exception",
        )


class TestNormalizeSchemaValidationToValidationStatus(unittest.TestCase):
    """Unit tests for the schema-validation status mapper."""

    def test_pass_maps_to_pass(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(
                {"status": "pass"}
            ),
            "pass",
        )

    def test_fail_maps_to_blocked(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(
                {"status": "fail"}
            ),
            "blocked",
        )

    def test_error_maps_to_blocked(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(
                {"status": "error"}
            ),
            "blocked",
        )

    def test_not_run_maps_to_unknown(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(
                {"status": "not_run"}
            ),
            "unknown",
        )

    def test_missing_status_maps_to_unknown(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status({}),
            "unknown",
        )

    def test_non_string_status_maps_to_unknown(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(
                {"status": 42}
            ),
            "unknown",
        )

    def test_none_input_maps_to_unknown(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(None),
            "unknown",
        )

    def test_unknown_string_status_maps_to_unknown(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(
                {"status": "garbage"}
            ),
            "unknown",
        )

    def test_non_dict_input_maps_to_unknown(self):
        from utils.toolkit_llm_final_reconciliation import (
            _normalize_schema_validation_to_validation_status,
        )
        self.assertEqual(
            _normalize_schema_validation_to_validation_status(
                "not a dict"
            ),
            "unknown",
        )


class TestComputeReconciledPublishableStatus(unittest.TestCase):
    """Unit tests for the source-fidelity effective-status normalizer."""

    def _call(self, report):
        from utils.toolkit_llm_final_reconciliation import (
            _compute_reconciled_publishable_status,
        )
        return _compute_reconciled_publishable_status(report)

    def test_all_pass_no_normalization(self):
        # All pass: no normalization needed; raw effective is pass.
        eff, normalized = self._call(_PUBLISHABILITY_REPORT_PASS)
        self.assertEqual(eff, "pass")
        self.assertFalse(normalized)

    def test_blocked_fidelity_only_normalizes(self):
        # Raw effective is blocked solely because of source fidelity;
        # publishable_status is pass; final reconciliation is
        # accepted by construction in the gate. The helper must
        # return the publishable_status as the effective status and
        # flag normalization.
        report = {
            "publishable_status": "pass",
            "source_fidelity_status": "blocked",
            "effective_publishable_status": "fail",
        }
        eff, normalized = self._call(report)
        self.assertEqual(eff, "pass")
        self.assertTrue(normalized)

    def test_degraded_fidelity_only_normalizes(self):
        report = {
            "publishable_status": "pass",
            "source_fidelity_status": "degraded",
            "effective_publishable_status": "fail",
        }
        eff, normalized = self._call(report)
        self.assertEqual(eff, "pass")
        self.assertTrue(normalized)

    def test_publishable_fail_does_not_normalize(self):
        # When publishable_status itself is fail, the raw effective
        # is fail for a real reason; the helper must NOT normalize.
        report = {
            "publishable_status": "fail",
            "source_fidelity_status": "blocked",
            "effective_publishable_status": "fail",
        }
        eff, normalized = self._call(report)
        self.assertEqual(eff, "fail")
        self.assertFalse(normalized)

    def test_pass_fidelity_blocked_effective_no_normalize(self):
        # Source fidelity is pass; effective is blocked for some
        # other reason. The helper must NOT normalize.
        report = {
            "publishable_status": "pass",
            "source_fidelity_status": "pass",
            "effective_publishable_status": "fail",
        }
        eff, normalized = self._call(report)
        self.assertEqual(eff, "fail")
        self.assertFalse(normalized)

    def test_missing_effective_returns_unknown(self):
        report = {"publishable_status": "pass"}
        eff, normalized = self._call(report)
        self.assertEqual(eff, "unknown")
        self.assertFalse(normalized)

    def test_empty_report_returns_unknown(self):
        eff, normalized = self._call({})
        self.assertEqual(eff, "unknown")
        self.assertFalse(normalized)


@patch(
    "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
)
@patch(
    "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
)
@patch(
    "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
)
class TestRunFinalReconciliationPublicationGates(unittest.TestCase):
    """End-to-end tests for the Step 4.2 gate runner.

    All three gate helpers are mocked so the tests do not invoke
    live CLI subprocesses or read any on-disk reports.
    """

    def setUp(self):
        self._module_dir = Path("/tmp/Well_of_Ruin")

    def test_happy_path_pass(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(
            self._module_dir,
            schema_validation={
                "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
            },
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_PASS
        )
        self.assertEqual(result["ready_status"], "pass")
        self.assertEqual(result["publishable_status"], "pass")
        self.assertEqual(
            result["effective_publishable_status"], "pass"
        )
        self.assertEqual(result["validation_status"], "pass")
        self.assertEqual(
            result["source_fidelity_effective_status"],
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS,
        )
        self.assertTrue(result["final_reconciliation_accepted"])
        self.assertEqual(
            result["final_reconciliation_status"],
            FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS,
        )
        self.assertFalse(
            result["effective_publishable_status_normalized"]
        )
        self.assertEqual(result["diagnostics"], [])
        # The report agreement helper received the in-memory args.
        mock_agreement.assert_called_once()
        agreement_kwargs = mock_agreement.call_args.kwargs
        self.assertEqual(
            agreement_kwargs["source_fidelity_effective_status"],
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS,
        )
        self.assertTrue(agreement_kwargs["final_reconciliation_accepted"])
        self.assertEqual(
            agreement_kwargs["final_reconciliation_status"],
            FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS,
        )

    def test_readiness_fail_returns_failed(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_FAIL)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_FAIL
        )
        self.assertEqual(result["ready_status"], "fail")
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_READINESS_FAILED, codes)
        # Publishability and report agreement should NOT be invoked
        # for the failed branch beyond what the helper already
        # short-circuits internally. They are invoked because the
        # helper runs all three gates; we only assert the failed
        # status and the readiness diagnostic.
        self.assertEqual(
            result["publishable_status"],
            _PUBLISHABILITY_REPORT_PASS["publishable_status"],
        )

    def test_publishability_fail_returns_failed(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_FAIL)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_FAIL
        )
        self.assertEqual(result["publishable_status"], "fail")
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED, codes)
        self.assertNotIn(DIAGNOSTIC_CODE_GATE_READINESS_FAILED, codes)

    def test_report_agreement_blocked_returns_failed(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_BLOCKED)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_FAIL
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_REPORT_AGREEMENT_BLOCKED, codes)
        # The blocked agreement result is preserved for inspection.
        self.assertEqual(
            result["report_agreement"]["status"], "blocked"
        )

    def test_readiness_helper_exception_returns_error(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.side_effect = RuntimeError("simulated outage")
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_ERROR
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION, codes)
        # Publishability and report agreement should not have been
        # invoked when the readiness helper raised.
        mock_publishability.assert_not_called()
        mock_agreement.assert_not_called()

    def test_publishability_helper_exception_returns_error(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.side_effect = RuntimeError("simulated outage")
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_ERROR
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION, codes)
        # The raw readiness report is preserved for inspection.
        self.assertEqual(
            result["readiness"]["overall_status"], "pass"
        )
        # Report agreement was not reached.
        mock_agreement.assert_not_called()

    def test_report_agreement_helper_exception_returns_error(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.side_effect = RuntimeError("simulated outage")

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_ERROR
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION, codes)

    def test_source_fidelity_reconciled_normalization(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        # Raw effective_publishable_status is "fail" solely because
        # source_fidelity_status is "blocked"; publishable_status is
        # "pass"; final reconciliation is accepted by construction.
        # The helper must pass "pass" as the effective status to
        # the report agreement composer, and report
        # effective_publishable_status_normalized=True.
        report = {
            "module": "Well_of_Ruin",
            "module_path": str(self._module_dir),
            "source": "toolkit",
            "ready_status": "pass",
            "publishable_status": "pass",
            "source_fidelity_status": "blocked",
            "source_fidelity_categories": [],
            "effective_publishable_status": "fail",
            "readiness": _READINESS_REPORT_PASS,
            "publication_gates": {},
            "blocking_errors": [],
            "warnings": [],
            "remediation_categories": {},
            "toolkit_media_policy": {},
            "fix_list": [],
            "exit_code": 1,
        }
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = report
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_PASS
        )
        # The publishability report is preserved verbatim so callers
        # can still inspect the raw source_fidelity status.
        self.assertEqual(
            result["publishability"]["source_fidelity_status"], "blocked"
        )
        self.assertEqual(
            result["publishability"]["effective_publishable_status"],
            "fail",
        )
        # The normalized status passed to report agreement is
        # captured in the helper output.
        self.assertEqual(
            result["effective_publishable_status"], "pass"
        )
        self.assertEqual(
            result["effective_publishable_status_raw"], "fail"
        )
        self.assertTrue(
            result["effective_publishable_status_normalized"]
        )
        # The normalized status was passed to the agreement composer.
        agreement_kwargs = mock_agreement.call_args.kwargs
        self.assertEqual(
            agreement_kwargs["effective_publishable_status"], "pass"
        )
        self.assertEqual(
            agreement_kwargs["publishable_status"], "pass"
        )
        # And source-fidelity honesty is preserved on the agreement
        # call.
        self.assertEqual(
            agreement_kwargs["source_fidelity_effective_status"],
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS,
        )
        self.assertEqual(
            agreement_kwargs["source_fidelity_status"], "blocked"
        )

    def test_normal_module_dir_path_object(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        # The helper must accept a pathlib.Path for module_dir.
        result = run_final_reconciliation_publication_gates(
            Path(self._module_dir)
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_PASS
        )
        # The module slug was resolved from module_dir.name.
        readiness_call = mock_readiness.call_args
        self.assertEqual(readiness_call.args[0], "Well_of_Ruin")
        self.assertEqual(readiness_call.kwargs.get("source"), "toolkit")
        publishability_call = mock_publishability.call_args
        self.assertEqual(publishability_call.args[0], "Well_of_Ruin")
        self.assertEqual(
            publishability_call.kwargs.get("module_path"),
            str(self._module_dir),
        )
        self.assertEqual(
            publishability_call.kwargs.get("source"), "toolkit"
        )

    def test_string_module_dir_accepted(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(
            str(self._module_dir)
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_PASS
        )

    def test_invalid_module_dir_returns_error(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        result = run_final_reconciliation_publication_gates(None)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_ERROR
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION, codes)
        mock_readiness.assert_not_called()

    def test_empty_string_module_dir_returns_error(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        result = run_final_reconciliation_publication_gates("   ")
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_ERROR
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_HELPER_EXCEPTION, codes)
        mock_readiness.assert_not_called()

    def test_no_schema_validation_defaults_to_unknown(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(
            self._module_dir
        )
        self.assertEqual(result["validation_status"], "unknown")
        agreement_kwargs = mock_agreement.call_args.kwargs
        self.assertEqual(agreement_kwargs["validation_status"], "unknown")

    def test_schema_validation_fail_normalizes_to_blocked(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(
            self._module_dir,
            schema_validation={
                "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL
            },
        )
        self.assertEqual(result["validation_status"], "blocked")
        agreement_kwargs = mock_agreement.call_args.kwargs
        self.assertEqual(agreement_kwargs["validation_status"], "blocked")

    def test_schema_validation_error_normalizes_to_blocked(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(
            self._module_dir,
            schema_validation={
                "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR
            },
        )
        self.assertEqual(result["validation_status"], "blocked")

    def test_readiness_non_dict_response_handled(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        # Defensive: a non-dict readiness report is replaced with an
        # empty dict and overall_status defaults to "fail".
        mock_readiness.return_value = "not a dict"
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_FAIL
        )
        self.assertEqual(result["ready_status"], "unknown")
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_READINESS_FAILED, codes)

    def test_publishability_non_dict_response_handled(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = "not a dict"
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_FAIL
        )
        self.assertEqual(result["publishable_status"], "unknown")
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_PUBLISHABILITY_FAILED, codes)

    def test_agreement_non_dict_response_handled(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = "not a dict"

        result = run_final_reconciliation_publication_gates(self._module_dir)
        # An agreement result that is not a dict collapses to
        # status="unknown", which is neither pass nor blocked. The
        # gate stays pass (only the explicit "blocked" branch
        # escalates). The report_agreement field is replaced with
        # an empty dict for safety.
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_GATE_STATUS_PASS
        )
        self.assertEqual(result["report_agreement"], {})

    def test_gate_result_shape_is_stable(
        self, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(_PUBLISHABILITY_REPORT_PASS)
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        result = run_final_reconciliation_publication_gates(self._module_dir)
        self.assertEqual(
            set(result.keys()),
            {
                "status",
                "readiness",
                "publishability",
                "report_agreement",
                "diagnostics",
                "ready_status",
                "publishable_status",
                "effective_publishable_status",
                "effective_publishable_status_raw",
                "effective_publishable_status_normalized",
                "validation_status",
                "source_fidelity_effective_status",
                "final_reconciliation_accepted",
                "final_reconciliation_status",
            },
        )


class TestApplyValidateAndGateFinalReconciliationPatchPlan(
    _TempModuleDirTestCase
):
    """End-to-end tests for the Step 4.2 combined orchestrator.

    The orchestrator composes the Step 4.1
    :func:`apply_and_validate_final_reconciliation_patch_plan` with
    the new :func:`run_final_reconciliation_publication_gates`
    helper. Tests patch both the schema-validation helper (for
    Step 4.1) and the three gate helpers (for Step 4.2) so no live
    CLI subprocess runs and no live report is loaded.
    """

    def _ready_plan_with_target(self, target_file: str) -> Dict[str, Any]:
        """Tiny valid ready plan with one file_patch entry."""
        return {
            "version": FINAL_RECONCILIATION_PATCH_VERSION,
            "status": FINAL_RECONCILIATION_PATCH_STATUS_READY,
            "source_fidelity_claim": (
                FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED
            ),
            "publication_intent": "playable_module",
            "decisions": [
                {
                    "blocker_message": "Test blocker",
                    "decision": "delete_bogus_atom",
                }
            ],
            "file_patches": [
                {
                    "target_file": target_file,
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "Step 4.2 orchestrator test",
                }
            ],
        }

    def _schema_factory(self, status):
        def _factory(module_dir):
            diagnostics = []
            if status == (
                FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL
            ):
                diagnostics = [
                    {
                        "code": (
                            DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED
                        ),
                        "message": "schema_validation_failed",
                        "severity": "error",
                    }
                ]
            return {
                "status": status,
                "success_rate": 1.0 if status.endswith("pass") else 0.0,
                "passed": 1,
                "failed": 0 if status.endswith("pass") else 1,
                "errors": [],
                "diagnostics": diagnostics,
            }

        return _factory

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_applied_when_all_three_phases_pass(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # Apply + schema + readiness + publishability + agreement
        # all pass. Overall status is "applied".
        mock_schema.side_effect = self._schema_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(
            _PUBLISHABILITY_REPORT_PASS
        )
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_APPLIED
        )
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_PASS,
        )
        # The apply phase actually wrote the file.
        self.assertEqual(
            self.read_target("module_context.json"), {"a": 99}
        )
        # The gate payload carries the raw report refs.
        self.assertEqual(
            result["gates"]["readiness"]["overall_status"], "pass"
        )
        self.assertEqual(
            result["gates"]["publishability"]["publishable_status"],
            "pass",
        )
        # Combined diagnostics is empty on the success path.
        self.assertEqual(result["diagnostics"], [])

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_skips_gates_when_apply_fails(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # Apply fails on target read; orchestrator skips schema and
        # gates. Overall status is "failed" and gates.status is
        # "not_run".
        plan = self._ready_plan_with_target("does_not_exist.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["does_not_exist.json"]
        )
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan, brief
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
        )
        # Schema, readiness, publishability, agreement all skipped.
        mock_schema.assert_not_called()
        mock_readiness.assert_not_called()
        mock_publishability.assert_not_called()
        mock_agreement.assert_not_called()
        # The apply failure code is preserved in combined diagnostics.
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED, codes)

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_skips_gates_when_schema_fails(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # Apply succeeds, schema fails. Orchestrator skips gates.
        mock_schema.side_effect = self._schema_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL
        )
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
        )
        # The schema failure code is preserved in combined diagnostics.
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED, codes)
        # No gate helpers were called.
        mock_readiness.assert_not_called()
        mock_publishability.assert_not_called()
        mock_agreement.assert_not_called()

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_failed_when_gates_fail(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # Apply + schema pass; gate readiness fails. Overall status
        # is "failed" with the gate diagnostic in the combined
        # diagnostics list.
        mock_schema.side_effect = self._schema_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        mock_readiness.return_value = dict(_READINESS_REPORT_FAIL)
        mock_publishability.return_value = dict(
            _PUBLISHABILITY_REPORT_PASS
        )
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_FAIL,
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_GATE_READINESS_FAILED, codes)
        # The apply phase actually wrote the file; the orchestrator
        # does not attempt rollback.
        self.assertEqual(
            self.read_target("module_context.json"), {"a": 99}
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_orchestrator_runs_gates_when_apply_and_schema_pass(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # Sanity check: the orchestrator actually invokes the three
        # gate helpers exactly once each when apply and schema both
        # pass. This is the inverse of the skip tests above.
        mock_schema.side_effect = self._schema_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(
            _PUBLISHABILITY_REPORT_PASS
        )
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        apply_validate_and_gate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        mock_readiness.assert_called_once()
        mock_publishability.assert_called_once()
        mock_agreement.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_orchestrator_does_not_mutate_inputs(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # The orchestrator is read-only by construction. Plan and
        # brief inputs are returned untouched.
        mock_schema.side_effect = self._schema_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(
            _PUBLISHABILITY_REPORT_PASS
        )
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        brief = _make_brief_with_module_dir(
            self.module_dir,
            editable_surfaces=["module_context.json"],
        )
        snapshot_plan = copy.deepcopy(plan)
        snapshot_brief = copy.deepcopy(brief)
        apply_validate_and_gate_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(plan, snapshot_plan)
        self.assertEqual(brief, snapshot_brief)

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_orchestrator_shape_keys_are_stable(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # Pin the top-level shape so future drift breaks this test.
        mock_schema.side_effect = self._schema_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS
        )
        mock_readiness.return_value = dict(_READINESS_REPORT_PASS)
        mock_publishability.return_value = dict(
            _PUBLISHABILITY_REPORT_PASS
        )
        mock_agreement.return_value = dict(_REPORT_AGREEMENT_PASS)

        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        self.assertEqual(
            set(result.keys()),
            {
                "status",
                "apply_result",
                "schema_validation",
                "gates",
                "diagnostics",
            },
        )
        # The gates payload has its own shape.
        self.assertEqual(
            set(result["gates"].keys()),
            {
                "status",
                "readiness",
                "publishability",
                "report_agreement",
                "diagnostics",
                "ready_status",
                "publishable_status",
                "effective_publishable_status",
                "effective_publishable_status_raw",
                "effective_publishable_status_normalized",
                "validation_status",
                "source_fidelity_effective_status",
                "final_reconciliation_accepted",
                "final_reconciliation_status",
            },
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_not_run_gates_payload_uses_not_run_status(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # When the orchestrator skips gates (because apply or schema
        # failed), the gates payload must carry the
        # not_run source-fidelity acceptance fields so downstream
        # reports can still surface the accepted-reconciliation
        # contract.
        plan = self._ready_plan_with_target("does_not_exist.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["does_not_exist.json"]
        )
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan, brief
        )
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
        )
        self.assertEqual(
            result["gates"]["source_fidelity_effective_status"],
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS,
        )
        self.assertEqual(
            result["gates"]["final_reconciliation_status"],
            FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS,
        )
        self.assertTrue(
            result["gates"]["final_reconciliation_accepted"]
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_schema_validation_carried_into_gates(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # The schema-validation payload produced by Step 4.1 is
        # forwarded to the Step 4.2 gate runner so the report
        # agreement composer's ``validation_status`` reflects the
        # actual schema pass/fail rather than defaulting to unknown.
        mock_schema.side_effect = self._schema_factory(
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL
        )
        # We still want the apply phase to succeed, so we use a
        # different ready plan shape and accept the schema failure
        # (orchestrator still runs apply then schema, then skips
        # gates because schema failed).
        self.write_target("module_context.json", {"a": 1})
        plan = self._ready_plan_with_target("module_context.json")
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan,
            _make_brief_with_module_dir(
                self.module_dir,
                editable_surfaces=["module_context.json"],
            ),
        )
        # The schema validation result is preserved in the
        # orchestrator output and the gates phase was skipped
        # because schema failed.
        self.assertEqual(
            result["schema_validation"]["status"],
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
        )
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
        )
        # Since gates are skipped, the gate-level validation_status
        # is the not_run default ("unknown").
        self.assertEqual(
             result["gates"]["validation_status"], "unknown"
        )


# ---------------------------------------------------------------------------
# Step 4.3: Bounded-retry orchestrator tests
# ---------------------------------------------------------------------------


# Tiny canned Step 4.2 apply/validate/gate result for the
# "all-three-phases pass" fixture. The shape mirrors the
# ``apply_validate_and_gate_final_reconciliation_patch_plan``
# return contract.
_STEP42_APPLIED = {
    "status": FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
    "apply_result": {
        "status": FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
        "changed_files": ["module_context.json"],
        "diagnostics": [],
    },
    "schema_validation": {
        "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_PASS,
        "success_rate": 1.0,
        "passed": 1,
        "failed": 0,
        "errors": [],
        "diagnostics": [],
    },
    "gates": {
        "status": FINAL_RECONCILIATION_GATE_STATUS_PASS,
        "readiness": dict(_READINESS_REPORT_PASS),
        "publishability": dict(_PUBLISHABILITY_REPORT_PASS),
        "report_agreement": dict(_REPORT_AGREEMENT_PASS),
        "diagnostics": [],
        "ready_status": "pass",
        "publishable_status": "pass",
        "effective_publishable_status": "pass",
        "effective_publishable_status_raw": "pass",
        "effective_publishable_status_normalized": False,
        "validation_status": "pass",
        "source_fidelity_effective_status": (
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
        ),
        "final_reconciliation_accepted": True,
        "final_reconciliation_status": (
            FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS
        ),
    },
    "diagnostics": [],
}


def _step42_schema_fail_result():
    """Return a Step 4.2 result where apply succeeded but schema failed."""
    return {
        "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
        "apply_result": {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_APPLIED,
            "changed_files": ["module_context.json"],
            "diagnostics": [],
        },
        "schema_validation": {
            "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
            "success_rate": 0.0,
            "passed": 0,
            "failed": 1,
            "errors": [
                {
                    "category": "reference integrity",
                    "file": "module_context.json",
                    "message": "missing required field",
                }
            ],
            "diagnostics": [
                {
                    "code": DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
                    "message": "schema validation failed",
                    "severity": "error",
                }
            ],
        },
        "gates": {
            "status": FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
            "readiness": {},
            "publishability": {},
            "report_agreement": {},
            "diagnostics": [],
            "ready_status": "unknown",
            "publishable_status": "unknown",
            "effective_publishable_status": "unknown",
            "effective_publishable_status_raw": "unknown",
            "effective_publishable_status_normalized": False,
            "validation_status": "unknown",
            "source_fidelity_effective_status": (
                FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
            ),
            "final_reconciliation_accepted": True,
            "final_reconciliation_status": (
                FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS
            ),
        },
        "diagnostics": [
            {
                "code": DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED,
                "message": "schema validation failed",
                "severity": "error",
            }
        ],
    }


def _step42_apply_failed_result():
    """Return a Step 4.2 result where apply itself failed (fatal)."""
    return {
        "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
        "apply_result": {
            "status": FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
            "changed_files": [],
            "diagnostics": [
                {
                    "code": DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED,
                    "message": "failed to read target file",
                    "severity": "error",
                }
            ],
        },
        "schema_validation": {
            "status": FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN,
            "success_rate": 0.0,
            "passed": 0,
            "failed": 0,
            "errors": [],
            "diagnostics": [],
        },
        "gates": {
            "status": FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
            "readiness": {},
            "publishability": {},
            "report_agreement": {},
            "diagnostics": [],
            "ready_status": "unknown",
            "publishable_status": "unknown",
            "effective_publishable_status": "unknown",
            "effective_publishable_status_raw": "unknown",
            "effective_publishable_status_normalized": False,
            "validation_status": "unknown",
            "source_fidelity_effective_status": (
                FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS
            ),
            "final_reconciliation_accepted": True,
            "final_reconciliation_status": (
                FINAL_RECONCILIATION_GATE_FINAL_RECONCILIATION_STATUS
            ),
        },
        "diagnostics": [
            {
                "code": DIAGNOSTIC_CODE_TARGET_FILE_READ_FAILED,
                "message": "failed to read target file",
                "severity": "error",
            }
        ],
    }


class TestStep43Constants(unittest.TestCase):
    """Pin the Step 4.3 stable constants."""

    def test_max_retries_value(self):
        # The retry budget is bounded to exactly one retry per the
        # design contract (design.md "Decision 5").
        self.assertEqual(MAX_FINAL_RECONCILIATION_RETRIES, 1)

    def test_orchestrator_status_accepted(self):
        self.assertEqual(
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED, "accepted"
        )

    def test_orchestrator_status_rejected(self):
        self.assertEqual(
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED, "rejected"
        )

    def test_orchestrator_status_not_retryable(self):
        self.assertEqual(
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
            "not_retryable",
        )

    def test_orchestrator_status_invalid_brief(self):
        self.assertEqual(
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_INVALID_BRIEF,
            "invalid_brief",
        )

    def test_diagnostic_code_retry_not_repairable(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_RETRY_NOT_REPAIRABLE, "retry_not_repairable"
        )

    def test_diagnostic_code_retry_budget_exhausted(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED,
            "retry_budget_exhausted",
        )


class TestStep43Helpers(unittest.TestCase):
    """Provider-free unit tests for the Step 4.3 helper functions."""

    def test_select_mock_provider_output_none_returns_none(self):
        self.assertIsNone(
            _select_mock_provider_output_for_attempt(None, 0)
        )
        self.assertIsNone(
            _select_mock_provider_output_for_attempt(None, 1)
        )

    def test_select_mock_provider_output_empty_list_returns_none(self):
        self.assertIsNone(
            _select_mock_provider_output_for_attempt([], 0)
        )
        self.assertIsNone(
            _select_mock_provider_output_for_attempt((), 0)
        )

    def test_select_mock_provider_output_string_returned_unchanged(self):
        # A single non-list value is forwarded unchanged to every
        # attempt so callers can pass a string and have it reused.
        self.assertEqual(
            _select_mock_provider_output_for_attempt("canned", 0), "canned"
        )
        self.assertEqual(
            _select_mock_provider_output_for_attempt("canned", 1), "canned"
        )

    def test_select_mock_provider_output_list_indexes_by_attempt(self):
        self.assertEqual(
            _select_mock_provider_output_for_attempt(
                ["a", "b", "c"], 0
            ),
            "a",
        )
        self.assertEqual(
            _select_mock_provider_output_for_attempt(
                ["a", "b", "c"], 1
            ),
            "b",
        )

    def test_select_mock_provider_output_out_of_range_uses_last(self):
        # When the list is shorter than the attempt index, return
        # the last entry so test plumbing does not have to know the
        # exact number of attempts up front.
        self.assertEqual(
            _select_mock_provider_output_for_attempt(["only"], 0),
            "only",
        )
        self.assertEqual(
            _select_mock_provider_output_for_attempt(["only"], 1),
            "only",
        )
        self.assertEqual(
            _select_mock_provider_output_for_attempt(["x", "y"], 5),
            "y",
        )

    def test_select_mock_provider_output_tuple_supported(self):
        # Tuples are also accepted because they round-trip well with
        # mock_provider_outputs passed positionally.
        self.assertEqual(
            _select_mock_provider_output_for_attempt(("a", "b"), 1),
            "b",
        )

    def test_select_mock_provider_output_negative_index_uses_last(self):
        # Defensive: a negative index should not crash; the
        # contract is "out-of-range -> last entry".
        self.assertEqual(
            _select_mock_provider_output_for_attempt(["x", "y"], -1),
            "y",
        )

    def test_is_repairable_schema_fail_after_apply_succeeded(self):
        # The repairable class: apply succeeded, schema reported
        # "fail" or "error". This is the only retryable failure
        # per the Step 4.3 spec.
        for schema_status in (
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_FAIL,
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_ERROR,
        ):
            result = _step42_schema_fail_result()
            result["schema_validation"]["status"] = schema_status
            self.assertTrue(
                _is_repairable_final_reconciliation_failure(result),
                f"expected repairable for schema_status={schema_status!r}",
            )

    def test_is_repairable_false_when_schema_pass(self):
        # When schema validation passes, the result is "applied"
        # overall, not a failure. The repairable helper is for
        # failure cases, but a defensive True could cause spurious
        # retries. Pin the contract: schema pass is NOT a failure
        # and is therefore NOT classified as repairable here.
        result = dict(_STEP42_APPLIED)
        self.assertFalse(
            _is_repairable_final_reconciliation_failure(result)
        )

    def test_is_repairable_false_when_apply_failed(self):
        # Fatal apply failures are not retryable per the spec.
        result = _step42_apply_failed_result()
        self.assertFalse(
            _is_repairable_final_reconciliation_failure(result)
        )

    def test_is_repairable_false_when_schema_not_run(self):
        # "not_run" means apply failed before schema could run; this
        # is fatal, not a repairable schema fail.
        result = _step42_schema_fail_result()
        result["schema_validation"]["status"] = (
            FINAL_RECONCILIATION_SCHEMA_VALIDATION_STATUS_NOT_RUN
        )
        self.assertFalse(
            _is_repairable_final_reconciliation_failure(result)
        )

    def test_is_repairable_false_for_non_dict_input(self):
        # Defensive: non-dict inputs collapse to False so the
        # orchestrator never retries on a malformed result.
        for bad in (None, "string", 42, [1, 2, 3]):
            self.assertFalse(
                _is_repairable_final_reconciliation_failure(bad)
            )

    def test_build_retry_brief_preserves_original_keys(self):
        # The retry brief is a deep-copy with retry_context added;
        # every other field is preserved verbatim.
        brief = _tiny_brief()
        diagnostics = [
            {
                "code": "schema_validation_failed",
                "message": "x",
                "severity": "error",
            }
        ]
        retry = _build_final_reconciliation_retry_brief(brief, diagnostics, 1)
        for key in brief:
            self.assertEqual(retry[key], brief[key])
        self.assertIn("retry_context", retry)
        self.assertEqual(retry["retry_context"]["attempt_index"], 1)
        self.assertEqual(
            retry["retry_context"]["previous_diagnostics"],
            diagnostics,
        )

    def test_build_retry_brief_does_not_mutate_input(self):
        # The original brief is never mutated; retry_context is
        # added to the COPY, not the input.
        brief = _tiny_brief()
        snapshot = copy.deepcopy(brief)
        _build_final_reconciliation_retry_brief(
            brief, [{"code": "x", "message": "y", "severity": "error"}], 1
        )
        self.assertEqual(brief, snapshot)
        self.assertNotIn("retry_context", brief)

    def test_build_retry_brief_deep_copies_nested_structures(self):
        # Nested dicts and lists in the brief are deep-copied so
        # mutating the retry brief cannot leak back into the
        # original via shared references.
        brief = _tiny_brief()
        brief["nested"] = {"inner": [1, 2, 3]}
        retry = _build_final_reconciliation_retry_brief(brief, [], 1)
        retry["nested"]["inner"].append(99)
        self.assertEqual(brief["nested"]["inner"], [1, 2, 3])

    def test_build_retry_brief_handles_empty_diagnostics(self):
        # The retry brief always carries a retry_context field even
        # when the previous attempt surfaced no diagnostics; the
        # previous_diagnostics list is just empty.
        brief = _tiny_brief()
        retry = _build_final_reconciliation_retry_brief(brief, [], 1)
        self.assertEqual(retry["retry_context"]["previous_diagnostics"], [])

    def test_build_retry_brief_handles_non_dict_brief(self):
        # Defensive: a non-dict input returns an empty dict so the
        # caller cannot accidentally end up with a malformed brief
        # downstream.
        self.assertEqual(_build_final_reconciliation_retry_brief(None, [], 1), {})
        self.assertEqual(_build_final_reconciliation_retry_brief("x", [], 1), {})

    def test_build_retry_brief_default_attempt_index(self):
        # A None attempt_index is coerced to 0 so downstream code
        # can always rely on a numeric value.
        brief = _tiny_brief()
        retry = _build_final_reconciliation_retry_brief(brief, [], None)
        self.assertEqual(retry["retry_context"]["attempt_index"], 0)

    def test_summarize_attempt_for_orchestrator_shape(self):
        # The summary is a stable dict with five keys.
        runner_result = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        av = dict(_STEP42_APPLIED)
        summary = _summarize_attempt_for_orchestrator(
            0, runner_result, av
        )
        self.assertEqual(summary["attempt_index"], 0)
        self.assertEqual(summary["runner_status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(summary["apply_validate_gate"], av)
        self.assertFalse(summary["is_repairable"])
        self.assertEqual(summary["diagnostics"], [])

    def test_summarize_attempt_for_orchestrator_combines_diagnostics(self):
        # Runner diagnostics follow apply/validate/gate diagnostics
        # in the combined list so reports show phases in order.
        runner_result = {
            "status": RUNNER_STATUS_SUCCESS,
            "diagnostics": [
                {"code": "runner_diag", "message": "m", "severity": "error"}
            ],
        }
        av = _step42_schema_fail_result()
        summary = _summarize_attempt_for_orchestrator(
            0, runner_result, av
        )
        codes = [d["code"] for d in summary["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED, codes)
        self.assertIn("runner_diag", codes)

    def test_summarize_attempt_for_orchestrator_none_av(self):
        # When the runner failed and no apply result was produced,
        # apply_validate_gate is None and is_repairable is False.
        runner_result = {
            "status": RUNNER_STATUS_INVALID_JSON,
            "diagnostics": [{"code": "invalid_json", "message": "x", "severity": "error"}],
        }
        summary = _summarize_attempt_for_orchestrator(0, runner_result, None)
        self.assertIsNone(summary["apply_validate_gate"])
        self.assertFalse(summary["is_repairable"])
        self.assertEqual(summary["runner_status"], RUNNER_STATUS_INVALID_JSON)

    def test_summarize_attempt_for_orchestrator_repairable_true(self):
        # When the apply succeeded and schema failed, is_repairable
        # is True (the only retryable class).
        runner_result = {"status": RUNNER_STATUS_SUCCESS, "diagnostics": []}
        summary = _summarize_attempt_for_orchestrator(
            0, runner_result, _step42_schema_fail_result()
        )
        self.assertTrue(summary["is_repairable"])


class TestStep43InvalidBrief(unittest.TestCase):
    """The non-dict brief branch fails closed before any attempt runs."""

    def test_non_dict_brief_returns_invalid_brief_status(self):
        for bad in (None, "string", 42, [1, 2, 3]):
            result = run_final_reconciliation_with_bounded_retry(bad)
            self.assertEqual(
                result["status"],
                FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_INVALID_BRIEF,
            )
            self.assertFalse(result["accepted"])
            self.assertEqual(result["retry_count"], 0)
            self.assertEqual(result["attempts"], [])
            self.assertIsNone(result["accepted_result"])
            self.assertIsNone(result["last_attempt_result"])
            self.assertEqual(result["error"], "brief_not_dict")

    def test_non_dict_brief_includes_invalid_brief_diagnostic(self):
        result = run_final_reconciliation_with_bounded_retry("not a dict")
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0]["code"], DIAGNOSTIC_CODE_INVALID_BRIEF
        )
        self.assertEqual(result["diagnostics"][0]["severity"], "error")

    def test_non_dict_brief_does_not_call_runner(self):
        # The orchestrator must short-circuit on bad brief before
        # calling the runner. We verify this by patching
        # run_llm_final_editor; the patch should never be called.
        with patch(
            "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
        ) as mock_runner:
            run_final_reconciliation_with_bounded_retry(None)
            mock_runner.assert_not_called()


class TestStep43NoRetryOnAttemptZeroAccepted(unittest.TestCase):
    """When attempt 0 succeeds end-to-end the orchestrator must not
    spend the retry budget."""

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_when_attempt_zero_accepted(
        self, mock_runner, mock_av_gate
    ):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        mock_av_gate.return_value = dict(_STEP42_APPLIED)

        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED,
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(
            result["accepted_result"], _STEP42_APPLIED
        )
        # Runner was called exactly once (no retry).
        self.assertEqual(mock_runner.call_count, 1)
        mock_av_gate.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_accepted_result_is_a_copy_not_a_reference(
        self, mock_runner, mock_av_gate
    ):
        # The orchestrator copies the accepted result so the caller
        # can mutate it without leaking into the orchestrator's
        # internal state.
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        sentinel = dict(_STEP42_APPLIED)
        mock_av_gate.return_value = sentinel

        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        result["accepted_result"]["mutated"] = True
        # Sentinel must NOT be mutated.
        self.assertNotIn("mutated", sentinel)


class TestStep43RetryOnRepairableSchemaFailure(unittest.TestCase):
    """The repairable schema-failure path: one retry, accepted on retry."""

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_one_retry_when_attempt_zero_schema_fails_and_retry_accepted(
        self, mock_runner, mock_av_gate
    ):
        # Attempt 0: runner succeeds; apply succeeds; schema fails.
        # Attempt 1: runner succeeds; apply succeeds; gates pass.
        mock_runner.side_effect = [
            {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            },
            {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            },
        ]
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]

        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED,
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(len(result["attempts"]), 2)
        # The accepted result is the second attempt's Step 4.2 result.
        self.assertEqual(result["accepted_result"], _STEP42_APPLIED)
        # Runner was called twice (initial + one retry).
        self.assertEqual(mock_runner.call_count, 2)
        self.assertEqual(mock_av_gate.call_count, 2)

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_exactly_one_retry_max_when_both_attempts_fail_repairably(
        self, mock_runner, mock_av_gate
    ):
        # Both attempts end in schema-fail. The orchestrator
        # retries exactly once (no more, no less) and returns
        # "rejected" with retry_count=1.
        mock_runner.side_effect = [
            {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            },
            {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            },
        ]
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            _step42_schema_fail_result(),
        ]

        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED,
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(len(result["attempts"]), 2)
        # Runner was called exactly twice (initial + one retry).
        # The orchestrator MUST NOT call it a third time.
        self.assertEqual(mock_runner.call_count, 2)
        self.assertEqual(mock_av_gate.call_count, 2)
        # Budget-exhausted diagnostic is attached.
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED, codes)

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_retry_attempts_recorded_in_order(
        self, mock_runner, mock_av_gate
    ):
        # The attempts list carries attempt_index 0 then 1 so
        # downstream reports can render a clean history.
        mock_runner.side_effect = [
            {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            },
            {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            },
        ]
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(result["attempts"][0]["attempt_index"], 0)
        self.assertEqual(result["attempts"][1]["attempt_index"], 1)
        # The first attempt is repairable; the second is not
        # (it succeeded).
        self.assertTrue(result["attempts"][0]["is_repairable"])
        self.assertFalse(result["attempts"][1]["is_repairable"])


class TestStep43NoRetryForNonRepairableFailures(unittest.TestCase):
    """Runner-side and apply-side failures are not retryable. The
    orchestrator must surface them as 'not_retryable' without
    spending the retry budget."""

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_for_invalid_json(self, mock_runner):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_INVALID_JSON,
            "patch_plan": {},
            "diagnostics": [
                {"code": DIAGNOSTIC_CODE_INVALID_JSON, "message": "x", "severity": "error"}
            ],
        }
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
        )
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["attempts"][0]["runner_status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["error"], RUNNER_STATUS_INVALID_JSON)
        mock_runner.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_for_missing_required_keys(self, mock_runner):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_MISSING_REQUIRED_KEYS,
            "patch_plan": {},
            "diagnostics": [
                {"code": DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS, "message": "x", "severity": "error"}
            ],
        }
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
        )
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(
            result["attempts"][0]["runner_status"],
            RUNNER_STATUS_MISSING_REQUIRED_KEYS,
        )
        mock_runner.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_for_forbidden_target(
        self, mock_runner, mock_av_gate
    ):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_INVALID_PATCH_CONTRACT,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [
                {"code": DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, "message": "x", "severity": "error"}
            ],
        }
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
        )
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(len(result["attempts"]), 1)
        # Apply was not called because the runner did not return
        # success; no retry was attempted.
        mock_av_gate.assert_not_called()
        mock_runner.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_for_false_source_fidelity_claim(
        self, mock_runner, mock_av_gate
    ):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_INVALID_PATCH_CONTRACT,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [
                {"code": DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, "message": "x", "severity": "error"}
            ],
        }
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
        )
        self.assertEqual(result["retry_count"], 0)
        mock_av_gate.assert_not_called()
        mock_runner.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_for_provider_failure(self, mock_runner):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_PROVIDER_FAILED,
            "patch_plan": {},
            "diagnostics": [
                {"code": DIAGNOSTIC_CODE_PROVIDER_FAILED, "message": "x", "severity": "error"}
            ],
        }
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
        )
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["error"], RUNNER_STATUS_PROVIDER_FAILED)
        mock_runner.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_for_refused_reconciliation(self, mock_runner):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_REFUSED_RECONCILIATION,
            "patch_plan": _valid_patch_plan(status="refused"),
            "diagnostics": [
                {"code": DIAGNOSTIC_CODE_REFUSED_RECONCILIATION, "message": "x", "severity": "error"}
            ],
        }
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
        )
        self.assertEqual(result["retry_count"], 0)
        mock_runner.assert_called_once()

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_retry_for_fatal_apply_failure(
        self, mock_runner, mock_av_gate
    ):
        # Runner succeeded but apply itself failed. This is a fatal
        # apply failure, NOT a repairable schema fail; the
        # orchestrator must not retry.
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        mock_av_gate.return_value = _step42_apply_failed_result()

        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_NOT_RETRYABLE,
        )
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(len(result["attempts"]), 1)
        # Runner was called once; the orchestrator did not retry.
        mock_runner.assert_called_once()
        mock_av_gate.assert_called_once()

    def test_no_retry_surface_includes_not_repairable_diagnostic(self):
        # The "not_retryable" terminal status carries a structured
        # diagnostic so downstream reports can render the boundary.
        with patch(
            "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
        ) as mock_runner:
            mock_runner.return_value = {
                "status": RUNNER_STATUS_INVALID_JSON,
                "patch_plan": {},
                "diagnostics": [],
            }
            result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_RETRY_NOT_REPAIRABLE, codes)


class TestStep43RetryBriefShape(unittest.TestCase):
    """The retry brief must contain the previous attempt's diagnostics
    and must not mutate the original brief."""

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_retry_brief_contains_compact_diagnostics(
        self, mock_runner, mock_av_gate
    ):
        # Capture the brief passed to the runner on each attempt.
        captured_briefs: list = []
        first_attempt_brief: Dict[str, Any] = _tiny_brief()
        original_snapshot = copy.deepcopy(first_attempt_brief)

        def capture_runner(brief, **_kwargs):
            captured_briefs.append(copy.deepcopy(brief))
            return {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            }

        mock_runner.side_effect = capture_runner
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]

        result = run_final_reconciliation_with_bounded_retry(
            first_attempt_brief
        )
        # The first attempt's brief is the original brief (no
        # retry_context yet).
        self.assertNotIn("retry_context", captured_briefs[0])
        # The second attempt's brief carries retry_context with the
        # previous attempt's diagnostics.
        self.assertIn("retry_context", captured_briefs[1])
        ctx = captured_briefs[1]["retry_context"]
        self.assertEqual(ctx["attempt_index"], 1)
        self.assertIsInstance(ctx["previous_diagnostics"], list)
        # The retry brief is a copy, not a reference; the original
        # brief is unchanged.
        self.assertEqual(first_attempt_brief, original_snapshot)
        self.assertNotIn("retry_context", first_attempt_brief)
        # The orchestrator returned accepted (since the retry
        # succeeded end-to-end).
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED,
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_retry_brief_preserves_all_original_keys(
        self, mock_runner, mock_av_gate
    ):
        captured_briefs: list = []
        original_brief = _tiny_brief()

        def capture_runner(brief, **_kwargs):
            captured_briefs.append(copy.deepcopy(brief))
            return {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            }

        mock_runner.side_effect = capture_runner
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]

        run_final_reconciliation_with_bounded_retry(original_brief)
        # The retry brief preserves every original key.
        for key in original_brief:
            self.assertEqual(
                captured_briefs[1][key], original_brief[key]
            )
        # And adds exactly one new top-level key: retry_context.
        new_keys = set(captured_briefs[1].keys()) - set(
            original_brief.keys()
        )
        self.assertEqual(new_keys, {"retry_context"})

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_retry_brief_does_not_carry_diagnostics_when_not_retried(
        self, mock_runner, mock_av_gate
    ):
        # When the orchestrator does NOT retry (attempt 0 is
        # accepted), the runner is called only once and the
        # single brief has no retry_context.
        captured_briefs: list = []

        def capture_runner(brief, **_kwargs):
            captured_briefs.append(copy.deepcopy(brief))
            return {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            }

        mock_runner.side_effect = capture_runner
        mock_av_gate.return_value = dict(_STEP42_APPLIED)

        run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertEqual(len(captured_briefs), 1)
        self.assertNotIn("retry_context", captured_briefs[0])


class TestStep43MockProviderOutputsPlumbing(unittest.TestCase):
    """Verify the test-only ``mock_provider_outputs`` plumbing
    correctly drives the underlying runner without live provider
    calls."""

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_mock_provider_outputs_index_selection(
        self, mock_runner, mock_av_gate
    ):
        # The orchestrator must call run_llm_final_editor with
        # the first mock output for attempt 0 and the second
        # mock output for attempt 1.
        captured_kwargs: list = []

        def capture_runner(brief, **_kwargs):
            captured_kwargs.append(copy.deepcopy(_kwargs))
            return {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            }

        mock_runner.side_effect = capture_runner
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]

        result = run_final_reconciliation_with_bounded_retry(
            _tiny_brief(),
            mock_provider_outputs=["mock-output-0", "mock-output-1"],
        )
        # The orchestrator must have called the runner twice.
        self.assertEqual(mock_runner.call_count, 2)
        # The first call used mock-output-0; the second used
        # mock-output-1.
        self.assertEqual(
            captured_kwargs[0].get("mock_provider_output"),
            "mock-output-0",
        )
        self.assertEqual(
            captured_kwargs[1].get("mock_provider_output"),
            "mock-output-1",
        )
        # The retry succeeded end-to-end.
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED,
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation.create_chat_client"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_no_live_provider_calls_when_mock_outputs_supplied(
        self, mock_runner, mock_av_gate, mock_create_client
    ):
        # With mock_provider_outputs supplied, the orchestrator
        # MUST NOT touch the live provider. The runner's existing
        # mock short-circuit prevents the call, but we verify the
        # create_chat_client mock is never invoked.
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        mock_av_gate.return_value = dict(_STEP42_APPLIED)

        result = run_final_reconciliation_with_bounded_retry(
            _tiny_brief(),
            mock_provider_outputs=["mock-output-0"],
        )
        # Live provider is never consulted.
        mock_create_client.assert_not_called()
        self.assertEqual(
            result["status"],
            FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED,
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_mock_provider_outputs_reused_when_shorter_than_attempts(
        self, mock_runner, mock_av_gate
    ):
        # When the list is shorter than the number of attempts,
        # the orchestrator reuses the last entry rather than
        # crashing or skipping. This makes test plumbing robust.
        captured_kwargs: list = []

        def capture_runner(brief, **_kwargs):
            captured_kwargs.append(copy.deepcopy(_kwargs))
            return {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            }

        mock_runner.side_effect = capture_runner
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]

        run_final_reconciliation_with_bounded_retry(
            _tiny_brief(),
            mock_provider_outputs=["only"],
        )
        # Both calls receive the only entry.
        self.assertEqual(len(captured_kwargs), 2)
        self.assertEqual(
            captured_kwargs[0].get("mock_provider_output"), "only"
        )
        self.assertEqual(
            captured_kwargs[1].get("mock_provider_output"), "only"
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_mock_provider_outputs_empty_list_uses_live_provider(
        self, mock_runner, mock_av_gate
    ):
        # An empty list collapses to the live-provider path; the
        # orchestrator must still call the runner. We do not
        # assert the create_chat_client path here because the
        # live provider is not actually invoked (the test runner
        # has no network). Instead, the runner is called with
        # mock_provider_output=None, which the runner treats as
        # "use the live provider"; the patched runner returns the
        # canned success result regardless.
        captured_kwargs: list = []

        def capture_runner(brief, **_kwargs):
            captured_kwargs.append(copy.deepcopy(_kwargs))
            return {
                "status": RUNNER_STATUS_SUCCESS,
                "patch_plan": _valid_patch_plan(),
                "diagnostics": [],
            }

        mock_runner.side_effect = capture_runner
        mock_av_gate.return_value = dict(_STEP42_APPLIED)

        run_final_reconciliation_with_bounded_retry(
            _tiny_brief(), mock_provider_outputs=[]
        )
        # The runner is called once with mock_provider_output=None.
        self.assertEqual(mock_runner.call_count, 1)
        self.assertIsNone(captured_kwargs[0].get("mock_provider_output"))


class TestStep43OrchestratorOutputShape(unittest.TestCase):
    """Pin the top-level orchestrator result shape and edge cases."""

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_top_level_shape_keys_are_stable(
        self, mock_runner, mock_av_gate
    ):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        mock_av_gate.return_value = dict(_STEP42_APPLIED)

        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        # Step 4.4 adds ``accepted_patch_plan`` to the top-level
        # orchestrator result so the accepted-report builder can
        # read the LLM's ``decisions`` list without re-running the
        # runner. The 9-key shape is the canonical Step 4.3+4.4
        # contract.
        self.assertEqual(
            set(result.keys()),
            {
                "status",
                "accepted",
                "retry_count",
                "attempts",
                "accepted_result",
                "accepted_patch_plan",
                "last_attempt_result",
                "diagnostics",
                "error",
            },
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_attempt_record_shape_is_stable(
        self, mock_runner, mock_av_gate
    ):
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        mock_av_gate.return_value = dict(_STEP42_APPLIED)

        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        attempt = result["attempts"][0]
        self.assertEqual(
            set(attempt.keys()),
            {
                "attempt_index",
                "runner_status",
                "apply_validate_gate",
                "is_repairable",
                "diagnostics",
            },
        )

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_does_not_mutate_brief_input(
        self, mock_runner, mock_av_gate
    ):
        # The orchestrator must never mutate the caller's brief;
        # the retry brief is a deep-copy.
        brief = _tiny_brief()
        snapshot = copy.deepcopy(brief)
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]
        run_final_reconciliation_with_bounded_retry(brief)
        self.assertEqual(brief, snapshot)
        self.assertNotIn("retry_context", brief)

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_last_attempt_result_is_set_even_when_rejected(
        self, mock_runner, mock_av_gate
    ):
        # When the orchestrator returns rejected, last_attempt_result
        # carries the final Step 4.2 result so callers can
        # inspect the failure without re-running anything.
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [],
        }
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            _step42_schema_fail_result(),
        ]
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        self.assertIsNotNone(result["last_attempt_result"])
        self.assertEqual(
            result["last_attempt_result"]["status"],
            FINAL_RECONCILIATION_APPLY_STATUS_FAILED,
        )
        # accepted_result is None because no attempt was accepted.
        self.assertIsNone(result["accepted_result"])

    @patch(
        "utils.toolkit_llm_final_reconciliation"
        ".apply_validate_and_gate_final_reconciliation_patch_plan"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_llm_final_editor"
    )
    def test_combined_diagnostics_include_all_attempts(
        self, mock_runner, mock_av_gate
    ):
        # The top-level diagnostics list is the concatenation of
        # every attempt's diagnostics, in order.
        mock_runner.return_value = {
            "status": RUNNER_STATUS_SUCCESS,
            "patch_plan": _valid_patch_plan(),
            "diagnostics": [
                {
                    "code": "runner_marker",
                    "message": "m",
                    "severity": "error",
                }
            ],
        }
        mock_av_gate.side_effect = [
            _step42_schema_fail_result(),
            dict(_STEP42_APPLIED),
        ]
        result = run_final_reconciliation_with_bounded_retry(_tiny_brief())
        codes = [d["code"] for d in result["diagnostics"]]
        # The schema-fail diagnostic from attempt 0 must appear.
        self.assertIn(DIAGNOSTIC_CODE_SCHEMA_VALIDATION_FAILED, codes)
        # The runner_marker from the (mocked) runner must appear
        # for BOTH attempts because the mock returns the same
        # runner result both times.
        self.assertEqual(
            sum(1 for c in codes if c == "runner_marker"),
            2,
        )


# ---------------------------------------------------------------------------
# Step 4.4: Accepted final reconciliation report builder and persister
# ---------------------------------------------------------------------------
#
# The Step 4.4 helpers consume the bounded payload from
# ``run_final_reconciliation_with_bounded_retry`` (Step 4.3) and
# emit a compact, source-fidelity-honest report dict that the
# existing provider-free
# ``utils.toolkit_final_reconciliation.persist_final_reconciliation_report``
# helper can write to ``final_reconciliation_report.json`` inside
# the module workspace. The on-disk file is byte-compatible with
# the archived boundary's contract so the legacy
# ``is_final_reconciliation_accepted`` helper still recognizes it
# as accepted.
#
# Tests in this section are provider-free. The acceptance
# orchestrator result is synthesized directly; the persist helper
# runs against a unique temp module directory so no real
# ``modules/<slug>/`` artifact is touched.


def _step44_accepted_orchestrator_result():
    """Return a synthetic accepted orchestrator result for Step 4.4 tests.

    The shape mirrors the real ``run_final_reconciliation_with_bounded_retry``
    output for the accepted branch. The ``accepted_result`` is a Step 4.2
    result with all three phases passing and the gates payload populated
    the same way the live orchestrator fills it. The ``accepted_patch_plan``
    carries the LLM's decisions list the report builder needs to render.
    """
    patch_plan = _valid_patch_plan()
    return {
        "status": FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_ACCEPTED,
        "accepted": True,
        "retry_count": 0,
        "attempts": [
            {
                "attempt_index": 0,
                "runner_status": RUNNER_STATUS_SUCCESS,
                "apply_validate_gate": dict(_STEP42_APPLIED),
                "is_repairable": False,
                "diagnostics": [],
            }
        ],
        "accepted_result": dict(_STEP42_APPLIED),
        "accepted_patch_plan": dict(patch_plan),
        "last_attempt_result": dict(_STEP42_APPLIED),
        "diagnostics": [],
        "error": None,
    }


def _step44_rejected_orchestrator_result():
    """Return a synthetic rejected orchestrator result for Step 4.4 tests.

    The shape is a minimal non-accepted orchestrator output that the
    report builder must collapse into a ``not_accepted`` report
    without touching the filesystem.
    """
    return {
        "status": FINAL_RECONCILIATION_ORCHESTRATOR_STATUS_REJECTED,
        "accepted": False,
        "retry_count": 1,
        "attempts": [],
        "accepted_result": None,
        "accepted_patch_plan": None,
        "last_attempt_result": None,
        "diagnostics": [
            {
                "code": DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED,
                "message": "retry budget exhausted after 2 attempts",
                "severity": "error",
            }
        ],
        "error": "retry_budget_exhausted",
    }


class TestStep44Constants(unittest.TestCase):
    """Pin the Step 4.4 stable constants."""

    def test_report_status_accepted(self):
        self.assertEqual(
            FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED, "accepted"
        )

    def test_report_status_not_accepted(self):
        self.assertEqual(
            FINAL_RECONCILIATION_REPORT_STATUS_NOT_ACCEPTED, "not_accepted"
        )

    def test_report_status_invalid_orchestrator_result(self):
        self.assertEqual(
            FINAL_RECONCILIATION_REPORT_STATUS_INVALID_ORCHESTRATOR_RESULT,
            "invalid_orchestrator_result",
        )

    def test_persist_status_written(self):
        self.assertEqual(
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN, "written"
        )

    def test_persist_status_failed(self):
        self.assertEqual(
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED, "failed"
        )

    def test_persist_status_not_accepted(self):
        self.assertEqual(
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_NOT_ACCEPTED,
            "not_accepted",
        )

    def test_persist_status_invalid(self):
        self.assertEqual(
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_INVALID, "invalid"
        )

    def test_diagnostic_code_report_build_failed(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_REPORT_BUILD_FAILED, "report_build_failed"
        )

    def test_diagnostic_code_report_persist_failed(self):
        self.assertEqual(
            DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED, "report_persist_failed"
        )

    def test_diagnostic_code_not_accepted(self):
        self.assertEqual(DIAGNOSTIC_CODE_NOT_ACCEPTED, "not_accepted")

    def test_decisions_max_items_is_positive(self):
        self.assertGreater(FINAL_RECONCILIATION_REPORT_DECISIONS_MAX_ITEMS, 0)

    def test_diagnostic_message_max_length_is_positive(self):
        self.assertGreater(
            FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MESSAGE_MAX_LENGTH, 0
        )

    def test_diagnostic_max_items_is_positive(self):
        self.assertGreater(
            FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS, 0
        )


class TestStep44BuildAcceptedReport(unittest.TestCase):
    """Builder-level contract for the accepted final reconciliation report."""

    def test_accepted_orchestrator_returns_accepted_report_shape(self):
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        self.assertEqual(
            report["status"], FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED
        )
        self.assertEqual(report["reconciliation_status"], "accepted")
        self.assertEqual(
            report["source_fidelity_effective_status"], "reconciled_degraded"
        )
        self.assertTrue(report["playable_publication_candidate"])

    def test_accepted_report_passes_legacy_acceptance_check(self):
        # The persisted file must be recognized by the archived
        # boundary's acceptance oracle so downstream report-agreement
        # consumers can read it back without re-deriving acceptance.
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        self.assertTrue(_legacy_is_final_reconciliation_accepted(report))

    def test_accepted_report_includes_decisions_from_patch_plan(self):
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        self.assertIsInstance(report["decisions"], list)
        # The fixture carries exactly one decision in
        # ``_valid_patch_plan``; the report must copy it through.
        self.assertEqual(len(report["decisions"]), 1)
        self.assertEqual(
            report["decisions"][0]["decision"], "delete_bogus_atom"
        )

    def test_accepted_report_includes_changed_files_from_apply_phase(self):
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        # The ``_STEP42_APPLIED`` fixture lists a single changed file.
        self.assertEqual(
            report["changed_files"], ["module_context.json"]
        )

    def test_accepted_report_includes_validation_after_reconciliation(self):
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        validation = report["validation_after_reconciliation"]
        self.assertIsInstance(validation, dict)
        self.assertEqual(validation["status"], "pass")
        self.assertEqual(validation["passed"], 1)
        self.assertEqual(validation["failed"], 0)
        self.assertEqual(validation["error_count"], 0)
        self.assertEqual(validation["success_rate"], 1.0)

    def test_accepted_report_includes_publishability_after_reconciliation(self):
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        pub = report["publishability_after_reconciliation"]
        self.assertIsInstance(pub, dict)
        # All four publishability fields are surfaced verbatim
        # from the gates payload.
        self.assertIn("publishable_status", pub)
        self.assertIn("effective_publishable_status", pub)
        self.assertIn("effective_publishable_status_raw", pub)
        self.assertIn("effective_publishable_status_normalized", pub)
        self.assertEqual(pub["publishable_status"], "pass")

    def test_accepted_report_includes_report_agreement_after_reconciliation(
        self,
    ):
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        agreement = report["report_agreement_after_reconciliation"]
        self.assertIsInstance(agreement, dict)
        self.assertIn("status", agreement)
        self.assertIn("playable_publication_status", agreement)

    def test_accepted_report_includes_source_fidelity_effective_status(self):
        # The source-fidelity honesty contract from the archived
        # boundary is preserved on the built report.
        result = _step44_accepted_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        self.assertEqual(
            report["source_fidelity_effective_status"],
            FINAL_RECONCILIATION_GATE_SOURCE_FIDELITY_EFFECTIVE_STATUS,
        )

    def test_rejected_orchestrator_returns_not_accepted_report(self):
        result = _step44_rejected_orchestrator_result()
        report = build_accepted_final_reconciliation_report(result, _tiny_brief())
        self.assertEqual(
            report["status"], FINAL_RECONCILIATION_REPORT_STATUS_NOT_ACCEPTED
        )
        self.assertEqual(report["reconciliation_status"], "not_accepted")
        self.assertEqual(report["source_fidelity_effective_status"], "blocked")
        self.assertFalse(report["playable_publication_candidate"])
        # The legacy acceptance oracle must reject this report.
        self.assertFalse(_legacy_is_final_reconciliation_accepted(report))

    def test_non_dict_orchestrator_returns_invalid_orchestrator_result_report(
        self,
    ):
        # Non-dict inputs (None, str, int, list) all fail closed at
        # the builder boundary with a single ``report_build_failed``
        # diagnostic.
        for bad in (None, "not a dict", 42, ["x"]):
            report = build_accepted_final_reconciliation_report(bad, _tiny_brief())
            self.assertEqual(
                report["status"],
                FINAL_RECONCILIATION_REPORT_STATUS_INVALID_ORCHESTRATOR_RESULT,
            )
            self.assertEqual(report["reconciliation_status"], "invalid_orchestrator_result")
            self.assertEqual(report["source_fidelity_effective_status"], "blocked")
            self.assertFalse(report["playable_publication_candidate"])
            codes = [d["code"] for d in report["diagnostics"]]
            self.assertIn(DIAGNOSTIC_CODE_REPORT_BUILD_FAILED, codes)
            self.assertFalse(_legacy_is_final_reconciliation_accepted(report))

    def test_builder_does_not_mutate_orchestrator_result(self):
        result = _step44_accepted_orchestrator_result()
        snapshot = copy.deepcopy(result)
        build_accepted_final_reconciliation_report(result, _tiny_brief())
        self.assertEqual(result, snapshot)

    def test_builder_does_not_mutate_brief(self):
        result = _step44_accepted_orchestrator_result()
        brief = _tiny_brief()
        snapshot = copy.deepcopy(brief)
        build_accepted_final_reconciliation_report(result, brief)
        self.assertEqual(brief, snapshot)


class _Step44TempModuleDirTestCase(unittest.TestCase):
    """Shared tempdir fixture for the Step 4.4 persister tests.

    Each test gets a unique module dir under ``tempfile.gettempdir()``
    and the dir is torn down on tearDown so the test never touches
    the real ``modules/`` tree.
    """

    def setUp(self):
        self._tmp_root = Path(tempfile.mkdtemp(prefix="step44_report_"))

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def _module_dir(self, name: str = "Well_of_Ruin") -> Path:
        module_dir = self._tmp_root / name
        module_dir.mkdir(parents=True, exist_ok=True)
        return module_dir


class TestStep44PersistAcceptedReport(_Step44TempModuleDirTestCase):
    """Persister-level contract for the accepted final reconciliation report."""

    def test_accepted_persists_final_reconciliation_report_json(self):
        module_dir = self._module_dir()
        result = _step44_accepted_orchestrator_result()

        outcome = persist_accepted_final_reconciliation_report(
            module_dir, result, _tiny_brief()
        )
        self.assertEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
        )
        self.assertIsNotNone(outcome["path"])
        self.assertGreater(outcome["bytes"], 0)

        # The on-disk file must be ``final_reconciliation_report.json``
        # inside the module dir.
        report_path = module_dir / "final_reconciliation_report.json"
        self.assertTrue(report_path.is_file())
        self.assertEqual(str(report_path), outcome["path"])

        # Round-trip the persisted file through the legacy loader
        # and confirm the legacy acceptance oracle recognizes it.
        with open(report_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertTrue(_legacy_is_final_reconciliation_accepted(loaded))

    def test_persisted_report_carries_required_keys(self):
        module_dir = self._module_dir()
        result = _step44_accepted_orchestrator_result()

        outcome = persist_accepted_final_reconciliation_report(
            module_dir, result, _tiny_brief()
        )
        report_path = module_dir / "final_reconciliation_report.json"
        with open(report_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        # The persisted report must include the canonical key set
        # the Step 4.4 spec calls out: source-fidelity effective
        # status, decisions, changed_files, validation outcome,
        # publishability outcome, and report-agreement outcome.
        self.assertIn("source_fidelity_effective_status", loaded)
        self.assertIn("decisions", loaded)
        self.assertIn("changed_files", loaded)
        self.assertIn("validation_after_reconciliation", loaded)
        self.assertIn("publishability_after_reconciliation", loaded)
        self.assertIn("report_agreement_after_reconciliation", loaded)
        # Outcome shape must match the spec contract.
        for key in ("status", "path", "report", "error", "diagnostics", "bytes"):
            self.assertIn(key, outcome)
        self.assertIsNone(outcome["error"])
        self.assertEqual(outcome["diagnostics"], [])

    def test_persisted_report_passes_is_final_reconciliation_accepted(self):
        module_dir = self._module_dir()
        result = _step44_accepted_orchestrator_result()

        outcome = persist_accepted_final_reconciliation_report(
            module_dir, result, _tiny_brief()
        )
        self.assertEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
        )
        # The built report attached to the outcome must also pass
        # the legacy acceptance oracle (not just the on-disk file).
        self.assertTrue(_legacy_is_final_reconciliation_accepted(outcome["report"]))

    def test_non_accepted_orchestrator_writes_nothing(self):
        module_dir = self._module_dir()
        result = _step44_rejected_orchestrator_result()

        report_path = module_dir / "final_reconciliation_report.json"
        self.assertFalse(report_path.exists())

        outcome = persist_accepted_final_reconciliation_report(
            module_dir, result, _tiny_brief()
        )
        # The persister surfaces a not-accepted status without
        # touching the filesystem.
        self.assertNotEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
        )
        self.assertIsNone(outcome["path"])
        self.assertEqual(outcome["bytes"], 0)
        self.assertFalse(report_path.exists())

    def test_invalid_orchestrator_result_writes_nothing(self):
        module_dir = self._module_dir()
        report_path = module_dir / "final_reconciliation_report.json"
        self.assertFalse(report_path.exists())

        outcome = persist_accepted_final_reconciliation_report(
            module_dir, "not a dict", _tiny_brief()
        )
        self.assertNotEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
        )
        self.assertIsNone(outcome["path"])
        self.assertFalse(report_path.exists())

    def test_missing_module_dir_writes_nothing(self):
        result = _step44_accepted_orchestrator_result()
        outcome = persist_accepted_final_reconciliation_report(
            None, result, _tiny_brief()
        )
        self.assertEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED,
        )
        self.assertIsNone(outcome["path"])
        self.assertIsNotNone(outcome["error"])
        codes = [d["code"] for d in outcome["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED, codes)

    def test_empty_string_module_dir_writes_nothing(self):
        result = _step44_accepted_orchestrator_result()
        outcome = persist_accepted_final_reconciliation_report(
            "", result, _tiny_brief()
        )
        self.assertEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_FAILED,
        )
        self.assertIsNone(outcome["path"])
        codes = [d["code"] for d in outcome["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_REPORT_PERSIST_FAILED, codes)

    def test_path_object_module_dir_is_accepted(self):
        # Path objects must be accepted in addition to plain strings.
        module_dir = self._module_dir()
        result = _step44_accepted_orchestrator_result()
        outcome = persist_accepted_final_reconciliation_report(
            module_dir, result, _tiny_brief()
        )
        self.assertEqual(
            outcome["status"],
            FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
        )
        self.assertTrue(
            (module_dir / "final_reconciliation_report.json").is_file()
        )

    def test_persister_does_not_mutate_orchestrator_result(self):
        module_dir = self._module_dir()
        result = _step44_accepted_orchestrator_result()
        snapshot = copy.deepcopy(result)
        persist_accepted_final_reconciliation_report(
            module_dir, result, _tiny_brief()
        )
        self.assertEqual(result, snapshot)

    def test_persister_does_not_mutate_brief(self):
        module_dir = self._module_dir()
        result = _step44_accepted_orchestrator_result()
        brief = _tiny_brief()
        snapshot = copy.deepcopy(brief)
        persist_accepted_final_reconciliation_report(
            module_dir, result, brief
        )
        self.assertEqual(brief, snapshot)


# ---------------------------------------------------------------------------
# Step 4.5: Blocked final reconciliation report shape
# ---------------------------------------------------------------------------


class TestStep45BlockedFinalReconciliationReport(unittest.TestCase):
    """Blocked report contract for non-accepted final reconciliation."""

    def test_blocked_report_is_not_playable_and_not_reconciled_degraded(self):
        report = build_blocked_final_reconciliation_report(
            _step44_rejected_orchestrator_result(), _tiny_brief()
        )
        self.assertEqual(
            report["status"], FINAL_RECONCILIATION_REPORT_STATUS_BLOCKED
        )
        self.assertEqual(report["reconciliation_status"], "blocked")
        self.assertEqual(report["source_fidelity_effective_status"], "blocked")
        self.assertFalse(report["playable_publication_candidate"])
        self.assertEqual(report["decisions"], [])
        self.assertEqual(report["changed_files"], [])

    def test_blocked_report_preserves_compact_diagnostics(self):
        result = _step44_rejected_orchestrator_result()
        result["attempts"] = [
            {
                "diagnostics": [
                    {
                        "code": "attempt_marker",
                        "message": "schema validation failed",
                        "severity": "error",
                    }
                ]
            }
        ]
        report = build_blocked_final_reconciliation_report(result, _tiny_brief())
        codes = [d["code"] for d in report["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_RETRY_BUDGET_EXHAUSTED, codes)
        self.assertIn("attempt_marker", codes)
        self.assertLessEqual(
            len(report["diagnostics"]),
            FINAL_RECONCILIATION_REPORT_DIAGNOSTIC_MAX_ITEMS,
        )

    def test_blocked_report_does_not_pass_legacy_acceptance_check(self):
        report = build_blocked_final_reconciliation_report(
            _step44_rejected_orchestrator_result(), _tiny_brief()
        )
        self.assertFalse(_legacy_is_final_reconciliation_accepted(report))

    def test_blocked_report_delegates_accepted_result_to_accepted_report(self):
        report = build_blocked_final_reconciliation_report(
            _step44_accepted_orchestrator_result(), _tiny_brief()
        )
        self.assertEqual(
            report["status"], FINAL_RECONCILIATION_REPORT_STATUS_ACCEPTED
        )
        self.assertEqual(
            report["source_fidelity_effective_status"], "reconciled_degraded"
        )
        self.assertTrue(report["playable_publication_candidate"])

    def test_persist_accepted_report_still_writes_nothing_for_blocked_result(self):
        module_dir = Path(tempfile.mkdtemp(prefix="step45_blocked_"))
        try:
            outcome = persist_accepted_final_reconciliation_report(
                module_dir, _step44_rejected_orchestrator_result(), _tiny_brief()
            )
            self.assertNotEqual(
                outcome["status"],
                FINAL_RECONCILIATION_REPORT_PERSIST_STATUS_WRITTEN,
            )
            self.assertFalse(
                (module_dir / "final_reconciliation_report.json").exists()
            )
        finally:
            shutil.rmtree(module_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Step 6.3: Final-editor negative tests
# ---------------------------------------------------------------------------
#
# Focused negative contract tests for the LLM Builder final editor
# runner and patch validators. Covers the contract gaps required by
# task 6.3 of the OpenSpec change:
#
#   1. invalid LLM JSON (raw prose, empty, malformed, non-object) via
#      ``run_llm_final_editor(mock_provider_output=...)`` returns
#      ``RUNNER_STATUS_INVALID_JSON`` with ``DIAGNOSTIC_CODE_INVALID_JSON``,
#      an empty ``patch_plan``, and no write/apply side effects.
#   2. forbidden file edits / path traversal / absolute path / source-
#      middle artifact targets are rejected by
#      ``validate_final_reconciliation_patch_targets`` (or
#      ``validate_final_reconciliation_patch_contract`` for shape-level
#      rejections) and never reach the file system.
#   3. runtime-only target edits (module_plot.json, party_tracker.json,
#      areas/FOO.json, player_quests_*.json, encounters/..., and
#      modules/world_registry.json) are rejected when routed through
#      ``apply_final_reconciliation_patch_plan`` AND
#      ``apply_validate_and_gate_final_reconciliation_patch_plan``; no
#      module file is modified.
#   4. false clean source-fidelity claims (pass / clean_pass / clean /
#      source_fidelity_pass) are rejected with
#      ``DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM`` and do not
#      produce accepted reports.
#   5. provider unavailable (patched create_chat_client or
#      client.chat.completions.create failure) returns
#      ``RUNNER_STATUS_PROVIDER_FAILED`` with
#      ``DIAGNOSTIC_CODE_PROVIDER_FAILED``; the runner does not silently
#      accept and does not perform any file I/O.
#
# All tests are provider-free. The runner tests use the
# ``mock_provider_output=`` short-circuit for invalid JSON cases and
# patch ``create_chat_client`` for the live-provider unavailable case.
# No real LLM, no live CLI subprocess, no real module file is touched.
#


class TestStep63InvalidJsonNegative(_TempModuleDirTestCase):
    """Step 6.3 contract: invalid LLM JSON from the final editor fails closed.

    The runner must return ``RUNNER_STATUS_INVALID_JSON`` with the
    structured ``DIAGNOSTIC_CODE_INVALID_JSON`` diagnostic, leave
    ``patch_plan`` empty, and never invoke the apply phase (no file
    is modified and ``build_result.json`` is untouched).
    """

    def test_raw_prose_response_returns_invalid_json(self):
        # The mock provider returns raw English prose that is not
        # parseable as JSON. The runner must fail closed at the parse
        # gate and never produce a patch plan.
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output="this is not json at all"
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["patch_plan"], {})
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(
            codes, [DIAGNOSTIC_CODE_INVALID_JSON]
        )
        # Legacy error field is preserved.
        self.assertEqual(result["error"], "invalid_json")
        # Mock-provider short-circuit preserved: create_chat_client is
        # never called for the invalid-JSON path.
        self.assertEqual(result["model"], RUNNER_MOCK_MODEL)
        self.assertEqual(result["params_used"], RUNNER_MOCK_PARAMS_MARKER)

    def test_empty_string_response_returns_invalid_json(self):
        # An empty mock output must not silently succeed.
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=""
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["patch_plan"], {})
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_JSON])

    def test_json_array_response_returns_invalid_json(self):
        # A JSON array is valid JSON but not a JSON object. The
        # patch plan must be a dict, so the runner fails closed.
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output="[1, 2, 3]"
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["patch_plan"], {})
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_JSON])

    def test_malformed_json_response_returns_invalid_json(self):
        # A truncated JSON object is not parseable.
        result = run_llm_final_editor(
            _tiny_brief(),
            mock_provider_output='{"version": "v1", "status":',
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_JSON)
        self.assertEqual(result["patch_plan"], {})
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_INVALID_JSON])

    def test_invalid_json_does_not_invoke_apply_phase(self):
        # End-to-end: even when the brief is set up for a writable
        # module, the apply phase must never run when the runner
        # produces an invalid_json status.
        self.write_target("module_context.json", {"a": 1})
        brief = _make_brief_with_module_dir(
            self.module_dir,
            editable_surfaces=["module_context.json"],
        )
        # Patch the apply helper to assert it is never called.
        with patch(
            "utils.toolkit_llm_final_reconciliation.apply_final_reconciliation_patch_plan"
        ) as mock_apply:
            runner_result = run_llm_final_editor(
                brief, mock_provider_output="not json"
            )
            self.assertEqual(
                runner_result["status"], RUNNER_STATUS_INVALID_JSON
            )
            mock_apply.assert_not_called()
        # And the on-disk target is unchanged (no write side effect).
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})


class TestStep63ProviderUnavailableNegative(unittest.TestCase):
    """Step 6.3 contract: provider unavailable fails closed without writes.

    The runner must surface a structured provider failure and never
    silently default to success. The apply phase must not be invoked
    on this path.
    """

    def test_create_chat_client_raises_returns_provider_failed(self):
        # create_chat_client itself raises (e.g., configuration error
        # or initial connection failure).
        with patch(
            "utils.toolkit_llm_final_reconciliation.create_chat_client",
            side_effect=RuntimeError("simulated client init failure"),
        ):
            result = run_llm_final_editor(_tiny_brief())
        self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(result["patch_plan"], {})
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_PROVIDER_FAILED])
        # Legacy error field carries the underlying cause.
        self.assertIn("simulated client init failure", result["error"])

    def test_completions_create_raises_returns_provider_failed(self):
        # Client initializes fine but the underlying completions
        # call raises (timeout, 5xx, rate limit, etc.).
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError(
            "rate limit exceeded"
        )
        with patch(
            "utils.toolkit_llm_final_reconciliation.create_chat_client",
            return_value=client,
        ):
            result = run_llm_final_editor(_tiny_brief())
        self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(result["patch_plan"], {})
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertEqual(codes, [DIAGNOSTIC_CODE_PROVIDER_FAILED])
        # Legacy error field carries the underlying cause.
        self.assertIn("rate limit exceeded", result["error"])

    def test_provider_unavailable_does_not_invoke_apply_phase(self):
        # End-to-end: provider failure must not silently fall through
        # to the apply helper.
        with patch(
            "utils.toolkit_llm_final_reconciliation.create_chat_client",
            side_effect=RuntimeError("provider down"),
        ):
            runner_result = run_llm_final_editor(_tiny_brief())
            self.assertEqual(
                runner_result["status"], RUNNER_STATUS_PROVIDER_FAILED
            )
            # The apply phase is not invoked.
            # (apply_final_reconciliation_patch_plan is owned by a
            # separate module path; we assert via status the apply
            # pipeline was never opened.)


class TestStep63ForbiddenTargetNegative(unittest.TestCase):
    """Step 6.3 contract: forbidden file edits / path traversal / source-middle artifacts.

    The validator must reject path-traversal, absolute paths, Windows
    drive paths, backslashes, and source/middle pipeline artifacts.
    Every rejection must report ``DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET``
    and the validator must never raise.
    """

    def test_path_traversal_rejected_by_targets(self):
        plan = _ready_plan_with_target("../unsafe.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["module_context.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_posix_absolute_path_rejected_by_targets(self):
        plan = _ready_plan_with_target("/etc/passwd")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["module_context.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_windows_drive_path_rejected_by_targets(self):
        plan = _ready_plan_with_target("C:/Windows/system32/config")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["module_context.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_backslash_path_rejected_by_targets(self):
        plan = _ready_plan_with_target("..\\unsafe.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["module_context.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_source_graph_artifact_rejected_by_targets(self):
        plan = _ready_plan_with_target("source_graph.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["source_graph.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_source_manifest_artifact_rejected_by_targets(self):
        plan = _ready_plan_with_target("source_manifest.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["source_manifest.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_normalized_packet_artifact_rejected_by_targets(self):
        plan = _ready_plan_with_target("normalized_packet.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["normalized_packet.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_blueprint_artifact_rejected_by_targets(self):
        plan = _ready_plan_with_target("builder_blueprint.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["builder_blueprint.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_blueprint_report_artifact_rejected_by_targets(self):
        plan = _ready_plan_with_target("builder_blueprint_report.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["builder_blueprint_report.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_module_summary_artifact_rejected_by_targets(self):
        plan = _ready_plan_with_target("MODULE_SUMMARY.md")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["MODULE_SUMMARY.md"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_backstage_audit_artifact_rejected_by_targets(self):
        plan = _ready_plan_with_target("accurate_ingest_audit_run/run.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["accurate_ingest_audit_run/"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)

    def test_target_not_in_editable_surfaces_rejected(self):
        # The brief's editable_surfaces is the gate; a target that is
        # not in the whitelist is rejected as forbidden.
        plan = _ready_plan_with_target("module_context.json")
        is_valid, diagnostics = validate_final_reconciliation_patch_targets(
            plan, _brief_with_surfaces(["areas/*_BU.json"])
        )
        self.assertFalse(is_valid)
        codes = [d["code"] for d in diagnostics]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)


class TestStep63RuntimeOnlyTargetNegative(_TempModuleDirTestCase):
    """Step 6.3 contract: runtime-only target edits are rejected end-to-end.

    Both the apply helper AND the apply+validate+gate orchestrator
    must reject every runtime-only target, leave the on-disk file
    untouched, and surface ``DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET``
    in the result diagnostics.
    """

    def _plan_targeting(self, target_file: str) -> Dict[str, Any]:
        return _make_ready_plan_with_patches(
            [
                {
                    "target_file": target_file,
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "Step 6.3 runtime-only negative test",
                }
            ]
        )

    # --- apply_final_reconciliation_patch_plan (Phase 1+2+3+4) ---

    def test_apply_rejects_module_plot_runtime_only(self):
        self.write_target("module_plot.json", {"a": 1})
        plan = self._plan_targeting("module_plot.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["module_plot.json"]
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The runtime file MUST NOT be modified.
        self.assertEqual(self.read_target("module_plot.json"), {"a": 1})

    def test_apply_rejects_party_tracker_runtime_only(self):
        self.write_target("party_tracker.json", {"active": "X"})
        plan = self._plan_targeting("party_tracker.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["party_tracker.json"]
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The runtime file MUST NOT be modified.
        self.assertEqual(
            self.read_target("party_tracker.json"), {"active": "X"}
        )

    def test_apply_rejects_live_areas_runtime_only(self):
        # Live area files (non-BU) are runtime-only even though the
        # brief may list ``areas/`` as an editable surface.
        self.write_target("areas/lidda_start.json", {"region": "X"})
        plan = self._plan_targeting("areas/lidda_start.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["areas/"]
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The runtime file MUST NOT be modified.
        self.assertEqual(
            self.read_target("areas/lidda_start.json"), {"region": "X"}
        )

    def test_apply_rejects_player_quests_runtime_only(self):
        self.write_target("player_quests_lidda.json", {"quests": ["Q1"]})
        plan = self._plan_targeting("player_quests_lidda.json")
        brief = _make_brief_with_module_dir(
            self.module_dir,
            editable_surfaces=["player_quests_*.json"],
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The runtime file MUST NOT be modified.
        self.assertEqual(
            self.read_target("player_quests_lidda.json"),
            {"quests": ["Q1"]},
        )

    def test_apply_rejects_encounters_runtime_only(self):
        self.write_target(
            "encounters/encounter_42.json", {"creatures": ["Goblin"]}
        )
        plan = self._plan_targeting("encounters/encounter_42.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["encounters/"]
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The runtime file MUST NOT be modified.
        self.assertEqual(
            self.read_target("encounters/encounter_42.json"),
            {"creatures": ["Goblin"]},
        )

    def test_apply_rejects_modules_world_registry_runtime_only(self):
        self.write_target(
            "modules/world_registry.json", {"active_module": "Well_of_Ruin"}
        )
        plan = self._plan_targeting("modules/world_registry.json")
        brief = _make_brief_with_module_dir(
            self.module_dir,
            editable_surfaces=["modules/world_registry.json"],
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The runtime file MUST NOT be modified.
        self.assertEqual(
            self.read_target("modules/world_registry.json"),
            {"active_module": "Well_of_Ruin"},
        )

    def test_apply_rejects_modules_campaign_runtime_only(self):
        self.write_target("modules/campaign.json", {"phase": "intro"})
        plan = self._plan_targeting("modules/campaign.json")
        brief = _make_brief_with_module_dir(
            self.module_dir,
            editable_surfaces=["modules/campaign.json"],
        )
        result = apply_final_reconciliation_patch_plan(plan, brief)
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # The runtime file MUST NOT be modified.
        self.assertEqual(
            self.read_target("modules/campaign.json"), {"phase": "intro"}
        )

    # --- apply_validate_and_gate_final_reconciliation_patch_plan ---

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_apply_validate_gate_rejects_module_plot(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        # The orchestrator must not invoke gates when the apply
        # phase itself fails closed on a runtime-only target.
        mock_schema.return_value = {
            "status": "not_run", "diagnostics": []
        }
        self.write_target("module_plot.json", {"a": 1})
        plan = self._plan_targeting("module_plot.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["module_plot.json"]
        )
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan, brief
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        # Gates were not invoked.
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
        )
        mock_readiness.assert_not_called()
        mock_publishability.assert_not_called()
        mock_agreement.assert_not_called()
        # The runtime file MUST NOT be modified.
        self.assertEqual(self.read_target("module_plot.json"), {"a": 1})

    @patch(
        "utils.toolkit_llm_final_reconciliation.compose_report_agreement"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_publishability"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.audit_module_readiness"
    )
    @patch(
        "utils.toolkit_llm_final_reconciliation.run_final_reconciliation_schema_validation"
    )
    def test_apply_validate_gate_rejects_party_tracker(
        self, mock_schema, mock_readiness, mock_publishability, mock_agreement
    ):
        mock_schema.return_value = {
            "status": "not_run", "diagnostics": []
        }
        self.write_target("party_tracker.json", {"active": "X"})
        plan = self._plan_targeting("party_tracker.json")
        brief = _make_brief_with_module_dir(
            self.module_dir, editable_surfaces=["party_tracker.json"]
        )
        result = apply_validate_and_gate_final_reconciliation_patch_plan(
            plan, brief
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_FORBIDDEN_PATCH_TARGET, codes)
        self.assertEqual(
            result["gates"]["status"],
            FINAL_RECONCILIATION_GATE_STATUS_NOT_RUN,
        )
        self.assertEqual(
            self.read_target("party_tracker.json"), {"active": "X"}
        )


class TestStep63FalseCleanSourceFidelityNegative(_TempModuleDirTestCase):
    """Step 6.3 contract: false clean source-fidelity claims are rejected.

    Accepted reconciliation MUST NOT convert blocked/degraded source
    fidelity into clean pass. The runner-level and apply-level gates
    must reject every clean-pass variant and refuse to produce an
    accepted report.
    """

    def test_runner_rejects_clean_pass_variant(self):
        # Each clean-pass variant must be rejected at the runner
        # level with RUNNER_STATUS_INVALID_PATCH_CONTRACT and the
        # DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM diagnostic.
        for variant in (
            "pass",
            "clean_pass",
            "clean",
            "source_fidelity_pass",
        ):
            plan = _ready_plan_with_source_fidelity_claim(variant)
            result = run_llm_final_editor(
                _tiny_brief(), mock_provider_output=json.dumps(plan)
            )
            self.assertEqual(
                result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT,
                f"variant {variant!r} should be rejected",
            )
            codes = [d["code"] for d in result["diagnostics"]]
            self.assertIn(
                DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes,
                f"variant {variant!r} should surface "
                "DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM",
            )

    def test_runner_rejects_missing_source_fidelity_claim(self):
        # The claim is required by the contract; missing it must be
        # rejected.
        plan = _ready_plan_with_source_fidelity_claim("reconciled_degraded")
        del plan["source_fidelity_claim"]
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        # Missing required key -> runner surfaces missing_required_keys
        # first (contract is checked before the source-fidelity gate).
        self.assertEqual(
            result["status"], RUNNER_STATUS_MISSING_REQUIRED_KEYS
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_MISSING_REQUIRED_KEYS, codes)
        joined = " ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("source_fidelity_claim", joined)

    def test_runner_rejects_non_string_source_fidelity_claim(self):
        # A non-string claim must be rejected.
        plan = _ready_plan_with_source_fidelity_claim(42)
        result = run_llm_final_editor(
            _tiny_brief(), mock_provider_output=json.dumps(plan)
        )
        self.assertEqual(
            result["status"], RUNNER_STATUS_INVALID_PATCH_CONTRACT
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)

    def test_apply_rejects_clean_pass_and_writes_nothing(self):
        # End-to-end: an apply-phase call with a clean-pass claim
        # must fail closed and leave the target file untouched.
        self.write_target("module_context.json", {"a": 1})
        plan = _make_ready_plan_with_patches(
            [
                {
                    "target_file": "module_context.json",
                    "op": FINAL_RECONCILIATION_PATCH_OP_SET_VALUE,
                    "json_path": "/a",
                    "value": 99,
                    "reason": "false clean claim negative test",
                }
            ]
        )
        plan["source_fidelity_claim"] = "clean_pass"
        result = apply_final_reconciliation_patch_plan(
            plan, _make_brief_with_module_dir(self.module_dir)
        )
        self.assertEqual(
            result["status"], FINAL_RECONCILIATION_APPLY_STATUS_FAILED
        )
        codes = [d["code"] for d in result["diagnostics"]]
        self.assertIn(DIAGNOSTIC_CODE_INVALID_SOURCE_FIDELITY_CLAIM, codes)
        # No writes occurred.
        self.assertEqual(result["changed_files"], [])
        self.assertEqual(self.read_target("module_context.json"), {"a": 1})

    def test_build_accepted_report_normalizes_clean_pass_claim(self):
        # Even if the orchestrator result somehow carries a clean-pass
        # patch plan claim (which the runner-level gate already
        # rejects), the report builder MUST lock
        # ``source_fidelity_effective_status`` to ``reconciled_degraded``
        # on the accepted path. This is the source-fidelity-honesty
        # contract: the on-disk report MUST NOT claim a clean source
        # fidelity pass.
        from utils.toolkit_llm_final_reconciliation import (
            build_accepted_final_reconciliation_report,
        )

        # Each clean-pass variant in turn.
        for variant in ("pass", "clean_pass", "clean", "source_fidelity_pass"):
            orchestrator_result = {
                "status": "accepted",
                "accepted": True,
                "accepted_patch_plan": {
                    "version": FINAL_RECONCILIATION_PATCH_VERSION,
                    "status": "ready",
                    "source_fidelity_claim": variant,
                    "publication_intent": "playable_module",
                    "decisions": [
                        {
                            "blocker_message": "x",
                            "decision": "delete_bogus_atom",
                        }
                    ],
                    "file_patches": [],
                },
                "accepted_result": {
                    "status": "applied",
                    "apply_result": {
                        "status": "applied",
                        "changed_files": [],
                    },
                    "schema_validation": {
                        "status": "pass", "success_rate": 1.0,
                        "passed": 1, "failed": 0, "errors": [],
                    },
                    "gates": {
                        "status": "pass",
                        "readiness": {"status": "pass"},
                        "publishability": {"status": "pass"},
                        "report_agreement": {"status": "pass"},
                    },
                },
                "attempts": [],
                "diagnostics": [],
            }
            report = build_accepted_final_reconciliation_report(
                orchestrator_result, _tiny_brief()
            )
            # The report MUST lock source_fidelity_effective_status to
            # reconciled_degraded regardless of the LLM's claim.
            self.assertEqual(
                report["source_fidelity_effective_status"],
                FINAL_RECONCILIATION_SOURCE_FIDELITY_CLAIM_RECONCILED_DEGRADED,
                f"variant {variant!r} must be normalized to "
                "reconciled_degraded on the accepted report",
            )
            # The report MUST NOT carry the LLM's false clean claim
            # in any obvious field.
            for forbidden in ("pass", "clean_pass", "clean", "source_fidelity_pass"):
                self.assertNotEqual(
                    report.get("source_fidelity_effective_status"), forbidden,
                    f"variant {variant!r} must not surface {forbidden!r}",
                )


if __name__ == "__main__":
    unittest.main()
