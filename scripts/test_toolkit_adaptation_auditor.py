# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contract tests for the final semantic adaptation auditor."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_auditor import (
    ADAPTATION_AUDITOR_CONTRACT_VERSION,
    ADAPTATION_AUDITOR_PROMPT_PATH,
    ADAPTATION_AUDITOR_RESPONSE_SCHEMA_PATH,
    ADAPTATION_AUDITOR_TASK_ID,
    AUDITOR_DECISION_FAILED,
    AUDITOR_DECISION_REFUSE,
    AUDITOR_DECISION_REVISE,
    AUDITOR_STATUS_INVALID_MODEL_RESPONSE,
    AUDITOR_STATUS_PARAM_RESOLUTION_FAILED,
    AUDITOR_STATUS_PROVIDER_FAILED,
    AUDITOR_STATUS_REFUSED,
    AUDITOR_STATUS_SUCCESS,
    DIAGNOSTIC_CODE_AUDITOR_NOT_AUTHORIZED,
    DIAGNOSTIC_CODE_DOSSIER_INVALID,
    DIAGNOSTIC_CODE_EVIDENCE_MISMATCH,
    DIAGNOSTIC_CODE_MARKDOWN_FENCE,
    DIAGNOSTIC_CODE_METADATA_MISMATCH,
    DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN,
    DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE,
    DIAGNOSTIC_CODE_UNSUPPORTED_DECISION,
    build_adaptation_auditor_messages,
    load_adaptation_auditor_schema,
    parse_adaptation_auditor_response,
    run_llm_adaptation_auditor,
)
from utils.toolkit_adaptation_failure_packet import build_adaptation_failure_packet


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
SOURCE_HASH = "c" * 64


def _attempt_metadata() -> Dict[str, Any]:
    return {
        "attempt_id": "adapt-001-auditor",
        "attempt_number": 1,
        "revision_number": 0,
        "stage": "build",
        "stage_id": "adapt-001-auditor:revision_000",
        "source_title": "Fixture Catalogue",
        "source_hash": SOURCE_HASH,
        "source_path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
        "source_profile": "catalogue",
        "source_format": "markdown",
        "adaptation_mode": "llm_adaptation",
        "rights_class": "user_authored",
        "rights_basis": "operator supplied source",
        "rights_review_required": False,
        "rights_review_status": "not_required",
        "model_metadata": {
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "parameter_profile": "toolkit_adaptation_semantic_auditor",
        },
        "source_context_artifact_path": "tmp/adaptation_attempts/adapt-001-auditor/source_context.json",
    }


def _staging_target() -> Dict[str, Any]:
    return {
        "stage_id": "adapt-001-auditor:revision_000",
        "path": "tmp/adaptation-staging/adapt-001-auditor/revision_000",
        "output_directory": "tmp/adaptation-staging/adapt-001-auditor/revision_000",
        "target_kind": "staging",
        "completion_state": "building",
        "attempt_id": "adapt-001-auditor",
        "attempt_number": 1,
        "revision_number": 0,
        "source_hash": SOURCE_HASH,
    }


def _gate_results() -> Dict[str, Any]:
    return {
        "gates": {
            "schema": {
                "status": "pass",
                "evidence_ref": {
                    "path": "tmp/reports/validation_report.json",
                    "sha256": SOURCE_HASH,
                },
            },
            "readiness": {"status": "pass"},
            "mechanical_closure": {"status": "pass"},
            "semantic_authority": {
                "status": "blocked",
                "blocking_errors": ["destination is ambiguous"],
                "evidence_ref": {
                    "path": "tmp/reports/semantic_authority_report.json",
                    "sha256": SOURCE_HASH,
                },
            },
            "semantic_probes": {"status": "pass"},
            "report_agreement": {"status": "pass"},
        }
    }


def _packet(*, failure_class: str = "semantic", eligible: bool = True) -> Dict[str, Any]:
    return build_adaptation_failure_packet(
        _gate_results(),
        attempt_metadata=_attempt_metadata(),
        staging_target=_staging_target(),
        source_context={
            "source_ref": {
                "path": "scripts/fixtures/toolkit_adaptation_catalogue.md",
                "sha256": SOURCE_HASH,
                "text": "raw source must not be copied",
            },
            "manifest_ref": {
                "path": "tmp/reports/source_manifest.json",
                "sha256": SOURCE_HASH,
            },
        },
        module_summaries=[
            {
                "module_slug": "Fixture_Catalogue",
                "module_title": "Fixture Shop",
                "status": "blocked",
                "ready_status": "pass",
                "publishable_status": "blocked",
                "summary": "A bounded current-candidate summary.",
                "area_count": 1,
            }
        ],
        publication_goals=["schema", "readiness", "semantic_authority", "semantic_probes"],
        failure_classification={
            "failure_class": failure_class,
            "failure_group": "content" if failure_class in {"semantic", "mechanical"} else "infrastructure",
            "classification_status": "revision_eligible" if eligible else "terminal",
            "code": "semantic_authority_blocked",
            "message": "semantic gate requires a bounded revision",
            "semantic_revision_eligible": eligible,
            "consumes_semantic_revision_budget": eligible,
            "revision_budget": {
                "current_revision": 0,
                "max_revisions": 1,
                "decision": "eligible" if eligible else "terminal_failure",
            },
        },
    )


def _evidence_refs(packet: Dict[str, Any]) -> list:
    refs = []
    seen = set()
    for collection_name in ("gate_statuses", "gate_findings"):
        for item in packet.get(collection_name, []):
            reference = item.get("evidence_ref") if isinstance(item, dict) else None
            if not isinstance(reference, dict):
                continue
            key = json.dumps(reference, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                refs.append(copy.deepcopy(reference))
                seen.add(key)
    return sorted(refs, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))


def _base_response(packet: Dict[str, Any], decision: str) -> Dict[str, Any]:
    attempt = packet["attempt_metadata"]
    return {
        "version": ADAPTATION_AUDITOR_CONTRACT_VERSION,
        "decision": decision,
        "reason": "The semantic correction is bounded and can be reviewed by Python.",
        "attempt_id": attempt["attempt_id"],
        "stage": attempt["stage"],
        "revision_number": attempt["revision_number"],
        "source_hash": attempt["source_hash"],
        "model_metadata": copy.deepcopy(attempt["model_metadata"]),
        "gate_evidence_refs": _evidence_refs(packet),
    }


def _dossier() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        dossier = json.load(handle)
    dossier["source_title"] = "Fixture Catalogue"
    dossier["source_hash"] = SOURCE_HASH
    dossier["rights_class"] = "user_authored"
    dossier["rights_basis"] = "operator supplied source"
    dossier["rights_review_required"] = False
    dossier["rights_review_status"] = "not_required"
    return dossier


def _raw(response: Dict[str, Any]) -> str:
    return json.dumps(response, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _provider_response(content: Optional[str] = None, *, refusal: Optional[str] = None) -> Any:
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], model="gpt-5.6-luna", id="auditor-response-1")


class FakeCompletions:
    def __init__(self, response: Any = None, error: Optional[Exception] = None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response: Any = None, error: Optional[Exception] = None) -> None:
        self.completions = FakeCompletions(response=response, error=error)
        self.chat = SimpleNamespace(completions=self.completions)


class TestAuditorContract(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _packet()

    def test_prompt_and_schema_are_ascii_and_versioned(self) -> None:
        prompt = ADAPTATION_AUDITOR_PROMPT_PATH.read_text(encoding="utf-8")
        prompt.encode("ascii")
        self.assertIn("revise", prompt)
        self.assertIn("refuse", prompt)
        self.assertIn("failed", prompt)
        self.assertIn(ADAPTATION_AUDITOR_CONTRACT_VERSION, prompt)
        schema = load_adaptation_auditor_schema()
        self.assertEqual(schema["$id"].rsplit("/", 1)[-1], "toolkit_adaptation_auditor.v1.json")
        json.dumps(schema, ensure_ascii=True).encode("ascii")

    def test_message_builder_consumes_only_bounded_packet(self) -> None:
        packet = copy.deepcopy(self.packet)
        packet["failure_classification"]["consumes_semantic_revision_budget"] = False
        messages = build_adaptation_auditor_messages(packet)
        self.assertEqual(messages[0]["content"], ADAPTATION_AUDITOR_PROMPT_PATH.read_text(encoding="utf-8"))
        self.assertTrue(messages[1]["content"].startswith("ADAPTATION_FAILURE_PACKET:\n"))
        self.assertNotIn("raw source must not be copied", messages[1]["content"])
        self.assertNotIn("api_key", messages[1]["content"])

    def test_revise_with_schema_valid_dossier_is_accepted(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        response["revised_dossier"] = _dossier()
        result = parse_adaptation_auditor_response(_raw(response), self.packet)
        self.assertTrue(result["valid"])
        self.assertEqual(result["decision"], AUDITOR_DECISION_REVISE)
        self.assertEqual(result["source_hash"], SOURCE_HASH)
        self.assertEqual(result["gate_evidence_refs"], _evidence_refs(self.packet))

    def test_revise_with_bounded_rebuild_directive_is_accepted(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        response["rebuild_directive"] = {
            "action": "fresh_build",
            "target": "staging",
            "basis": "revised_dossier",
            "guidance": ["Reframe the ambiguous destination as one canonical playable location."],
        }
        result = parse_adaptation_auditor_response(_raw(response), self.packet)
        self.assertTrue(result["valid"])
        self.assertEqual(result["decision"], AUDITOR_DECISION_REVISE)

    def test_refuse_has_no_change_payload(self) -> None:
        result = parse_adaptation_auditor_response(_raw(_base_response(self.packet, AUDITOR_DECISION_REFUSE)), self.packet)
        self.assertTrue(result["valid"])
        self.assertEqual(result["decision"], AUDITOR_DECISION_REFUSE)
        self.assertFalse(result["ok"])

    def test_failed_has_bounded_classified_failure(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_FAILED)
        response["failure"] = {
            "class": "semantic",
            "status": "failed",
            "code": "insufficient_semantic_evidence",
            "message": "The bounded evidence does not support a safe adaptation revision.",
        }
        result = parse_adaptation_auditor_response(_raw(response), self.packet)
        self.assertTrue(result["valid"])
        self.assertEqual(result["decision"], AUDITOR_DECISION_FAILED)


class TestAuditorRejections(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _packet()

    def _parse(self, response: Dict[str, Any]) -> Dict[str, Any]:
        return parse_adaptation_auditor_response(_raw(response), self.packet)

    def test_pass_success_and_unknown_decisions_are_rejected(self) -> None:
        for value in ("pass", "success", "unknown"):
            with self.subTest(value=value):
                response = _base_response(self.packet, value)
                result = self._parse(response)
                self.assertFalse(result["valid"])
                self.assertIn(DIAGNOSTIC_CODE_UNSUPPORTED_DECISION, {item["code"] for item in result["diagnostics"]})

    def test_malformed_prose_and_markdown_wrappers_are_rejected(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        for raw in ("not json", "Here is the JSON: " + _raw(response), "```json\n" + _raw(response) + "\n```"):
            with self.subTest(raw=raw[:12]):
                result = parse_adaptation_auditor_response(raw, self.packet)
                self.assertFalse(result["valid"])
        fenced = "```json\n" + _raw(response) + "\n```"
        fenced_result = parse_adaptation_auditor_response(fenced, self.packet)
        self.assertIn(DIAGNOSTIC_CODE_MARKDOWN_FENCE, {item["code"] for item in fenced_result["diagnostics"]})

    def test_extra_fields_and_patch_payloads_are_rejected(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        response["file_patches"] = []
        result = self._parse(response)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN if any(item["code"] == DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN for item in result["diagnostics"]) else "unexpected_field", {item["code"] for item in result["diagnostics"]})

        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        response["rebuild_directive"] = {
            "action": "fresh_build",
            "target": "staging",
            "basis": "revised_dossier",
            "guidance": ["safe"],
            "target_path": "modules/Unsafe",
        }
        result = self._parse(response)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_PAYLOAD_FORBIDDEN, {item["code"] for item in result["diagnostics"]})

    def test_metadata_and_gate_evidence_must_be_preserved(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        response["source_hash"] = "d" * 64
        result = self._parse(response)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_METADATA_MISMATCH, {item["code"] for item in result["diagnostics"]})

        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        response["gate_evidence_refs"] = []
        result = self._parse(response)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_EVIDENCE_MISMATCH, {item["code"] for item in result["diagnostics"]})

    def test_revise_requires_exactly_one_safe_payload(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        result = self._parse(response)
        self.assertFalse(result["valid"])

        response["revised_dossier"] = _dossier()
        response["rebuild_directive"] = {
            "action": "fresh_build",
            "target": "staging",
            "basis": "revised_dossier",
            "guidance": ["safe"],
        }
        result = self._parse(response)
        self.assertFalse(result["valid"])

        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        response["revised_dossier"] = _dossier()
        response["failure"] = {
            "class": "semantic",
            "status": "failed",
            "code": "unsafe",
            "message": "not allowed with revise",
        }
        result = self._parse(response)
        self.assertFalse(result["valid"])

    def test_refuse_and_failed_reject_executable_payloads(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        response["rebuild_directive"] = {
            "action": "fresh_build",
            "target": "staging",
            "basis": "revised_dossier",
            "guidance": ["safe"],
        }
        result = self._parse(response)
        self.assertFalse(result["valid"])

        response = _base_response(self.packet, AUDITOR_DECISION_FAILED)
        response["failure"] = {
            "class": "semantic",
            "status": "failed",
            "code": "failed",
            "message": "failed",
        }
        response["revised_dossier"] = _dossier()
        result = self._parse(response)
        self.assertFalse(result["valid"])

    def test_invalid_dossier_and_provenance_drift_are_rejected(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        dossier = _dossier()
        dossier.pop("areas")
        response["revised_dossier"] = dossier
        result = self._parse(response)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_DOSSIER_INVALID, {item["code"] for item in result["diagnostics"]})

        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        dossier = _dossier()
        dossier["source_hash"] = "d" * 64
        response["revised_dossier"] = dossier
        result = self._parse(response)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_METADATA_MISMATCH, {item["code"] for item in result["diagnostics"]})

    def test_credentials_raw_payloads_and_overlong_content_are_rejected(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        response["reason"] = "api_key=sk-secret"
        result = self._parse(response)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["code"] == "unsafe_content" for item in result["diagnostics"]))

        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        response["reason"] = "x" * 801
        result = self._parse(response)
        self.assertFalse(result["valid"])

        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        response["gate_evidence_refs"] = _evidence_refs(self.packet) * 100
        result = self._parse(response)
        self.assertFalse(result["valid"])

        raw = "{" + ("\"x\":\"y\", " * 40_000) + "\"decision\":\"refuse\"}"
        result = parse_adaptation_auditor_response(raw, self.packet)
        self.assertFalse(result["valid"])
        self.assertIn(DIAGNOSTIC_CODE_RESPONSE_TOO_LARGE, {item["code"] for item in result["diagnostics"]})

    def test_infrastructure_rights_and_publication_failures_are_not_authorized(self) -> None:
        for failure_class in ("provider", "rights", "publication"):
            with self.subTest(failure_class=failure_class):
                packet = _packet(failure_class=failure_class, eligible=False)
                result = run_llm_adaptation_auditor(
                    packet,
                    client=FakeClient(response=_provider_response("should not be called")),
                    parameter_resolver=lambda task_id, model: {"model": model},
                )
                self.assertEqual(result["decision"], AUDITOR_DECISION_FAILED if result["status"] == "invalid_input" else AUDITOR_DECISION_REFUSE)
                if result["status"] != "invalid_input":
                    self.assertEqual(result["status"], AUDITOR_STATUS_REFUSED)


class TestAuditorRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _packet()

    def test_runner_revise_is_provider_free_with_injected_client(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REVISE)
        response["rebuild_directive"] = {
            "action": "fresh_build",
            "target": "staging",
            "basis": "revised_dossier",
            "guidance": ["Use the canonical destination identity from the semantic gate evidence."],
        }
        client = FakeClient(response=_provider_response(_raw(response)))
        result = run_llm_adaptation_auditor(
            self.packet,
            client=client,
            model="gpt-4.1-test",
            parameter_resolver=lambda task_id, model: {"model": model, "temperature": 0.2},
        )
        self.assertEqual(result["status"], AUDITOR_STATUS_SUCCESS)
        self.assertEqual(result["decision"], AUDITOR_DECISION_REVISE)
        self.assertTrue(result["ok"])
        self.assertEqual(len(client.completions.calls), 1)
        self.assertEqual(client.completions.calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(client.completions.calls[0]["model"], "gpt-4.1-test")
        self.assertNotIn("raw_response_text", result)

    def test_runner_uses_gpt5_compatibility_parameters(self) -> None:
        response = _base_response(self.packet, AUDITOR_DECISION_REFUSE)
        client = FakeClient(response=_provider_response(_raw(response)))
        result = run_llm_adaptation_auditor(
            self.packet,
            client=client,
            model="gpt-5.6-luna",
        )
        self.assertEqual(result["status"], AUDITOR_STATUS_REFUSED)
        request = client.completions.calls[0]
        self.assertIn("reasoning_effort", request)
        self.assertIn("verbosity", request)
        self.assertNotIn("temperature", request)
        self.assertNotIn("top_p", request)

    def test_runner_provider_and_parameter_failures_are_failed_outcomes(self) -> None:
        provider_result = run_llm_adaptation_auditor(
            self.packet,
            client=FakeClient(error=TimeoutError("provider secret api_key=hidden")),
            parameter_resolver=lambda task_id, model: {"model": model},
        )
        self.assertEqual(provider_result["status"], AUDITOR_STATUS_PROVIDER_FAILED)
        self.assertEqual(provider_result["decision"], AUDITOR_DECISION_FAILED)
        self.assertNotIn("hidden", json.dumps(provider_result, sort_keys=True))

        parameter_result = run_llm_adaptation_auditor(
            self.packet,
            client=FakeClient(response=_provider_response("unused")),
            parameter_resolver=lambda task_id, model: (_ for _ in ()).throw(RuntimeError("api_key=hidden")),
        )
        self.assertEqual(parameter_result["status"], AUDITOR_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertEqual(parameter_result["decision"], AUDITOR_DECISION_FAILED)
        self.assertEqual(parameter_result["response"]["decision"], AUDITOR_DECISION_FAILED)
        self.assertNotIn("hidden", json.dumps(parameter_result, sort_keys=True))

    def test_runner_provider_refusal_is_a_safe_refuse(self) -> None:
        result = run_llm_adaptation_auditor(
            self.packet,
            client=FakeClient(response=_provider_response(refusal="do not expose provider details")),
            parameter_resolver=lambda task_id, model: {"model": model},
        )
        self.assertEqual(result["status"], AUDITOR_STATUS_REFUSED)
        self.assertEqual(result["decision"], AUDITOR_DECISION_REFUSE)
        self.assertNotIn("provider details", json.dumps(result, sort_keys=True))

    def test_runner_does_not_call_provider_for_ineligible_packet(self) -> None:
        client = FakeClient(response=_provider_response("should not be called"))
        result = run_llm_adaptation_auditor(
            _packet(failure_class="mechanical", eligible=False),
            client=client,
            parameter_resolver=lambda task_id, model: {"model": model},
        )
        self.assertEqual(result["status"], AUDITOR_STATUS_REFUSED)
        self.assertEqual(result["decision"], AUDITOR_DECISION_REFUSE)
        self.assertEqual(client.completions.calls, [])
        self.assertIn(DIAGNOSTIC_CODE_AUDITOR_NOT_AUTHORIZED, {item["code"] for item in result["diagnostics"]})

    def test_runner_rejects_invalid_model_response_as_failed(self) -> None:
        client = FakeClient(response=_provider_response("pass"))
        result = run_llm_adaptation_auditor(
            self.packet,
            client=client,
            parameter_resolver=lambda task_id, model: {"model": model},
        )
        self.assertEqual(result["status"], AUDITOR_STATUS_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["decision"], AUDITOR_DECISION_FAILED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
