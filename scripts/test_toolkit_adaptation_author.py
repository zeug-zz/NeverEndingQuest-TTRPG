# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the toolkit adaptation author runner."""

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_author import (
    ADAPTATION_AUTHOR_PROMPT_PATH,
    ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY,
    ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT,
    ADAPTATION_AUTHOR_RESPONSE_FORMAT_VERSION,
    ADAPTATION_AUTHOR_STRUCTURED_OUTPUT_NAME,
    ADAPTATION_AUTHOR_TASK_ID,
    DIAGNOSTIC_CODE_INVALID_PARAMS,
    DIAGNOSTIC_CODE_INVALID_PROVENANCE,
    DIAGNOSTIC_CODE_MARKDOWN_FENCE,
    DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
    DIAGNOSTIC_CODE_PROVIDER_FAILED,
    DIAGNOSTIC_CODE_PROVIDER_REFUSAL,
    OUTCOME_EXPLICIT_REFUSAL,
    OUTCOME_PARAMETER_RESOLUTION_FAILURE,
    OUTCOME_PROVIDER_FAILURE,
    OUTCOME_VALID,
    RUNNER_STATUS_INVALID_MODEL_RESPONSE,
    RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
    RUNNER_STATUS_PROVIDER_FAILED,
    RUNNER_STATUS_REFUSED,
    RUNNER_STATUS_SUCCESS,
    build_adaptation_author_messages,
    build_adaptation_author_response_format,
    parse_adaptation_author_response,
    run_llm_adaptation_author,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_REFUSED,
    ADAPTATION_DOSSIER_VERSION,
    load_adaptation_dossier_schema,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _response(content: Optional[str] = None, *, refusal: Optional[str] = None) -> Any:
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], model="gpt-5.6-luna", id="resp-test-1")


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


class TestAdaptationAuthorRunner(unittest.TestCase):
    """The runner is deterministic under an injected client and resolver."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = {
            "attempt_id": "attempt-test-1",
            "source_title": self.fixture["source_title"],
            "source_hash": self.fixture["source_hash"],
            "source_profile": self.fixture["source_profile"],
            "rights_class": self.fixture["rights_class"],
        }
        self.source_context = {
            "source_title": self.fixture["source_title"],
            "source_profile_hint": "catalogue",
            "bounded_excerpt": "A catalogue of useful lanterns.",
        }

    def test_valid_response_uses_dossier_parser_and_keeps_provider_payload_private(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="mock-adaptation-model",
            parameter_resolver=lambda task_id, model: {
                "model": model,
                "temperature": 0.2,
            },
        )

        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["outcome"], OUTCOME_VALID)
        self.assertTrue(result["ok"])
        self.assertEqual(result["dossier"]["source_hash"], self.fixture["source_hash"])
        self.assertEqual(result["attempt_id"], "attempt-test-1")
        self.assertEqual(result["provider"], "injected")
        self.assertNotIn("raw_response", result)
        self.assertNotIn("raw_response_text", result)
        self.assertNotIn("secret", json.dumps(result, sort_keys=True))

        self.assertEqual(len(client.completions.calls), 1)
        request = client.completions.calls[0]
        self.assertEqual(
            request["response_format"]["type"],
            ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT,
        )
        json_schema = request["response_format"]["json_schema"]
        self.assertEqual(json_schema["name"], ADAPTATION_AUTHOR_STRUCTURED_OUTPUT_NAME)
        self.assertTrue(json_schema["strict"])
        self.assertEqual(
            json_schema["schema"]["$id"],
            load_adaptation_dossier_schema()["$id"],
        )
        self.assertIn("messages", request)
        self.assertEqual(request["messages"][0]["content"], ADAPTATION_AUTHOR_PROMPT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(request["model"], "mock-adaptation-model")
        self.assertEqual(result["request"]["response_format"], ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT)
        self.assertTrue(result["request"]["response_format_strict"])
        self.assertEqual(result["request"]["response_schema"], ADAPTATION_DOSSIER_VERSION)

    def test_default_compatibility_helper_omits_legacy_gpt5_sampling_fields(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-5.6-luna",
        )

        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        request = client.completions.calls[0]
        self.assertIn("reasoning_effort", request)
        self.assertIn("verbosity", request)
        self.assertNotIn("temperature", request)
        self.assertNotIn("top_p", request)
        self.assertEqual(
            request["response_format"]["type"],
            ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT,
        )
        self.assertTrue(request["response_format"]["json_schema"]["strict"])

    def test_invalid_fenced_or_prose_response_fails_closed(self) -> None:
        fenced = "```json\n" + json.dumps(self.fixture) + "\n```"
        client = FakeClient(response=_response(fenced))
        result = run_llm_adaptation_author(self.source_context, self.metadata, client=client)

        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertFalse(result["ok"])
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_MARKDOWN_FENCE, codes)

    def test_invalid_provenance_is_rejected_after_schema_validation(self) -> None:
        payload = copy.deepcopy(self.fixture)
        payload["source_hash"] = "b" * 64
        client = FakeClient(response=_response(json.dumps(payload)))
        result = run_llm_adaptation_author(self.source_context, self.metadata, client=client)

        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertIn(
            DIAGNOSTIC_CODE_INVALID_PROVENANCE,
            {item["code"] for item in result["diagnostics"]},
        )

    def test_dossier_refusal_is_distinguished_from_invalid_json(self) -> None:
        payload = copy.deepcopy(self.fixture)
        payload["status"] = ADAPTATION_DOSSIER_STATUS_REFUSED
        client = FakeClient(response=_response(json.dumps(payload)))
        result = run_llm_adaptation_author(self.source_context, self.metadata, client=client)

        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED)
        self.assertEqual(result["outcome"], OUTCOME_EXPLICIT_REFUSAL)
        self.assertFalse(result["ok"])

    def test_provider_refusal_field_is_bounded_and_explicit(self) -> None:
        client = FakeClient(response=_response(refusal="provider secret should not leak"))
        result = run_llm_adaptation_author(self.source_context, self.metadata, client=client)

        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED)
        self.assertEqual(result["outcome"], OUTCOME_EXPLICIT_REFUSAL)
        self.assertIn(
            DIAGNOSTIC_CODE_PROVIDER_REFUSAL,
            {item["code"] for item in result["diagnostics"]},
        )
        self.assertNotIn("provider secret", json.dumps(result, sort_keys=True))

    def test_timeout_and_quota_provider_failures_are_classified(self) -> None:
        for error, expected_class in (
            (TimeoutError("request timed out"), "timeout"),
            (RuntimeError("quota exceeded"), "quota"),
        ):
            with self.subTest(expected_class=expected_class):
                client = FakeClient(error=error)
                result = run_llm_adaptation_author(
                    self.source_context,
                    self.metadata,
                    client=client,
                    model="gpt-5.6-luna",
                )
                self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
                self.assertEqual(result["outcome"], OUTCOME_PROVIDER_FAILURE)
                self.assertEqual(result["failure_class"], expected_class)
                self.assertIn(
                    DIAGNOSTIC_CODE_PROVIDER_FAILED,
                    {item["code"] for item in result["diagnostics"]},
                )

    def test_parameter_resolution_failure_does_not_create_client_or_call_provider(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))

        def failing_resolver(task_id: str, model: str) -> Dict[str, Any]:
            raise RuntimeError("api_key=must-not-appear")

        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            parameter_resolver=failing_resolver,
        )

        self.assertEqual(result["status"], RUNNER_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertEqual(result["outcome"], OUTCOME_PARAMETER_RESOLUTION_FAILURE)
        self.assertIn(
            DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
            {item["code"] for item in result["diagnostics"]},
        )
        self.assertEqual(client.completions.calls, [])
        self.assertNotIn("api_key", json.dumps(result, sort_keys=True))

    def test_parameter_resolver_and_model_are_injected_deterministically(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        calls = []

        def resolver(task_id: str, model: str) -> Dict[str, Any]:
            calls.append((task_id, model))
            return {"model": model, "temperature": 0.3}

        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-4.1-test",
            parameter_resolver=resolver,
        )

        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(calls, [(ADAPTATION_AUTHOR_TASK_ID, "gpt-4.1-test")])
        self.assertEqual(client.completions.calls[0]["temperature"], 0.3)
        self.assertNotIn("reasoning_effort", client.completions.calls[0])


class TestAdaptationAuthorParser(unittest.TestCase):
    """The parser is strict and does not accept decoded provider mappings."""

    def setUp(self) -> None:
        fixture = _load_fixture()
        self.metadata = {
            "attempt_id": "attempt-parser-1",
            "source_hash": fixture["source_hash"],
            "source_title": fixture["source_title"],
            "source_profile": fixture["source_profile"],
            "rights_class": fixture["rights_class"],
        }

    def test_parser_requires_raw_json_text(self) -> None:
        result = parse_adaptation_author_response({}, attempt_metadata=self.metadata)
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)

    def test_parser_rejects_decoded_mapping_even_when_schema_valid(self) -> None:
        # A provider-decoded mapping must never bypass the raw-JSON boundary,
        # even when its shape is a fully valid ready dossier.
        result = parse_adaptation_author_response(
            _load_fixture(),
            attempt_metadata=self.metadata,
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertIsNone(result["dossier"])

    def test_message_builder_uses_prompt_file_and_bounds_context(self) -> None:
        messages = build_adaptation_author_messages(
            {f"excerpt_{index}": "x" * 1200 for index in range(32)},
            self.metadata,
        )
        self.assertEqual(messages[0]["content"], ADAPTATION_AUTHOR_PROMPT_PATH.read_text(encoding="utf-8"))
        self.assertLessEqual(len(messages[1]["content"]), 26000)
        self.assertIn("bounded_truncation", messages[1]["content"])

    def test_message_builder_passes_seed_identity_but_not_world_payload(self) -> None:
        world_context = {
            "context_version": "toolkit_adaptation_world_context.v1",
            "context_status": "available",
            "fallback_status": "none",
            "world_seed_status": "available",
            "world_seed_version": "fixture.v2",
            "world_seed_hash": "d" * 64,
            "context_hash": "e" * 64,
            "read_only": True,
            "provider_free": True,
            "campaign_model": {"summary": "must not be sent"},
            "active_pressures": [{"summary": "must not be sent"}],
            "approved_module_seeds": [{"content": {"summary": "must not be sent"}}],
        }
        source_context = {
            "source_title": self.metadata["source_title"],
            "source_profile_hint": "catalogue",
            "bounded_excerpt": "A catalogue of useful lanterns.",
        }
        messages = build_adaptation_author_messages(
            source_context,
            self.metadata,
            world_context=world_context,
        )
        request = messages[1]["content"]
        self.assertIn('"world_seed_version":"fixture.v2"', request)
        self.assertIn('"world_seed_hash":"' + ("d" * 64) + '"', request)
        self.assertIn('"context_hash":"' + ("e" * 64) + '"', request)
        self.assertNotIn("must not be sent", request)
        self.assertNotIn("approved_module_seeds", request)


class TestAdaptationAuthorStructuredOutputContract(unittest.TestCase):
    """The author request uses a strict GPT-family structured-output contract."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = {
            "attempt_id": "attempt-strict-1",
            "source_title": self.fixture["source_title"],
            "source_hash": self.fixture["source_hash"],
            "source_profile": self.fixture["source_profile"],
            "rights_class": self.fixture["rights_class"],
        }
        self.source_context = {
            "source_title": self.fixture["source_title"],
            "source_profile_hint": "catalogue",
            "bounded_excerpt": "A catalogue of useful lanterns.",
        }

    def _assert_strict_object_nodes(self, node: Any) -> None:
        """Every object with properties is fully required and closed."""
        if isinstance(node, Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping):
                self.assertEqual(node.get("additionalProperties"), False)
                self.assertEqual(node.get("required"), sorted(properties.keys()))
            for key in ("properties", "definitions", "$defs"):
                value = node.get(key)
                if isinstance(value, Mapping):
                    for child in value.values():
                        self._assert_strict_object_nodes(child)
            items = node.get("items")
            if isinstance(items, (Mapping, list)):
                self._assert_strict_object_nodes(items)
        elif isinstance(node, list):
            for item in node:
                self._assert_strict_object_nodes(item)

    def test_strict_response_format_uses_dossier_schema_identity(self) -> None:
        response_format = build_adaptation_author_response_format("openai")
        self.assertEqual(response_format["type"], ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT)
        json_schema = response_format["json_schema"]
        self.assertEqual(json_schema["name"], ADAPTATION_AUTHOR_STRUCTURED_OUTPUT_NAME)
        self.assertTrue(json_schema["strict"])
        schema = json_schema["schema"]
        dossier_schema = load_adaptation_dossier_schema()
        self.assertEqual(schema["$id"], dossier_schema["$id"])
        self.assertIn(ADAPTATION_DOSSIER_VERSION, schema["$id"])
        # The strict derivation only expands the required set; it never drops
        # an authored required field.
        dossier_required = set(dossier_schema["required"])
        strict_required = set(schema["required"])
        self.assertTrue(dossier_required <= strict_required)
        self.assertEqual(
            strict_required - dossier_required,
            {"puzzle_or_trial_seeds"},
        )
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["additionalProperties"], False)
        # Draft-07 meta marker is stripped from the provider copy.
        self.assertNotIn("$schema", schema)

    def test_strict_response_format_marks_every_object_property_required(self) -> None:
        response_format = build_adaptation_author_response_format("openai")
        self._assert_strict_object_nodes(response_format["json_schema"]["schema"])

    def test_response_format_is_deterministic_ascii_and_bounded(self) -> None:
        first = build_adaptation_author_response_format("openai")
        second = build_adaptation_author_response_format("injected")
        self.assertEqual(first, second)
        serialized = json.dumps(
            first,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertTrue(serialized.isascii())
        self.assertLess(len(serialized), 60000)

    def test_openrouter_profile_uses_documented_json_object_fallback(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="moonshotai/kimi-k2.5",
            parameter_resolver=lambda task_id, model: {"model": model},
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        request = client.completions.calls[0]
        self.assertEqual(
            request["response_format"],
            {"type": ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY},
        )
        self.assertEqual(
            result["request"]["response_format"],
            ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY,
        )
        self.assertFalse(result["request"]["response_format_strict"])
        self.assertIsNone(result["request"]["response_schema"])

    def test_resolver_reserved_keys_remain_rejected_under_strict_contract(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            parameter_resolver=lambda task_id, model: {
                "model": model,
                "response_format": {"type": "json_object"},
            },
        )
        self.assertEqual(result["status"], RUNNER_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertEqual(client.completions.calls, [])

    def test_response_format_build_failure_fails_closed_without_provider_call(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        with patch(
            "utils.toolkit_adaptation_author.build_adaptation_author_response_format",
            side_effect=ValueError("schema identity must never leak"),
        ):
            result = run_llm_adaptation_author(
                self.source_context,
                self.metadata,
                client=client,
                parameter_resolver=lambda task_id, model: {"model": model},
            )
        self.assertEqual(result["status"], RUNNER_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertIn(
            DIAGNOSTIC_CODE_INVALID_PARAMS,
            {item["code"] for item in result["diagnostics"]},
        )
        self.assertEqual(client.completions.calls, [])
        self.assertNotIn("schema identity must never leak", json.dumps(result, sort_keys=True))

    def test_schema_compliant_response_still_requires_parser_identity(self) -> None:
        # Provider schema compliance is not build success: a schema-valid
        # dossier with the wrong source identity still fails the Python parser.
        payload = copy.deepcopy(self.fixture)
        payload["source_hash"] = "c" * 64
        client = FakeClient(response=_response(json.dumps(payload)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            parameter_resolver=lambda task_id, model: {"model": model},
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertIn(
            DIAGNOSTIC_CODE_INVALID_PROVENANCE,
            {item["code"] for item in result["diagnostics"]},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
