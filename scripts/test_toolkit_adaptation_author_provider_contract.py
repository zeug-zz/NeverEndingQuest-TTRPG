# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free author-provider contract tests (task 3.3 of
toolkit-llm-adaptation-runtime-unification).

The suite explicitly locks the seven named contract cases at the author
runner / parser / envelope / authoring boundaries without duplicating
production policy:

  1. valid user-authored metadata remains build-ready where appropriate;
  2. missing rights metadata is blocked safely before any provider work;
  3. restricted rights stay review-gated (pending/rejected never build-ready,
     approved may proceed, relabel is rejected);
  4. API-level refusal is a distinct refusal channel with bounded diagnostics;
  5. dossier ``status: refused`` is a distinct author-policy refusal channel;
  6. malformed structured output is ``invalid_model_response`` and never
     becomes build-ready;
  7. direct GPT-5 requests retain ``reasoning_effort``/``verbosity`` and omit
     legacy ``temperature``/``top_p`` while the Python parser stays the final
     schema and rights authority.

Every provider surface is injected through fake clients/resolvers/runners;
no network or provider call is ever made. Raw refusal text, credentials,
raw source, and repository absolute paths are never returned or persisted.
All fixtures reuse the repository dossier fixture
(``scripts/fixtures/toolkit_adaptation_dossier_valid.json``), and all
generated scratch lives under the project-local root
``tmp/toolkit_adaptation_author_provider_contract/<uuid>/`` removed via
addCleanup. No OS temp directory is used.
"""

import copy
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_author import (
    ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY,
    ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT,
    ADAPTATION_AUTHOR_TASK_ID,
    DIAGNOSTIC_CODE_INVALID_PROVENANCE,
    DIAGNOSTIC_CODE_MARKDOWN_FENCE,
    DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED,
    DIAGNOSTIC_CODE_PROVIDER_REFUSAL,
    OUTCOME_EXPLICIT_REFUSAL,
    OUTCOME_INVALID_MODEL_RESPONSE,
    OUTCOME_PARAMETER_RESOLUTION_FAILURE,
    OUTCOME_VALID,
    REASON_CATEGORY_API_REFUSAL,
    REASON_CATEGORY_AUTHOR_POLICY_REFUSAL,
    REASON_CATEGORY_DOSSIER_VALIDATION,
    REASON_CATEGORY_INVALID_MODEL_RESPONSE,
    REASON_CATEGORY_NONE,
    REASON_CATEGORY_PARAMETER_RESOLUTION,
    REASON_CATEGORY_RIGHTS_OR_PROVENANCE,
    REASON_CODE_DOSSIER_NOT_BUILD_READY,
    REASON_CODE_DOSSIER_REFUSED,
    REASON_CODE_INVALID_MODEL_RESPONSE,
    REASON_CODE_NONE,
    REASON_CODE_PARAM_RESOLUTION_FAILED,
    REASON_CODE_PROVIDER_API_REFUSAL,
    REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH,
    RUNNER_STATUS_INVALID_MODEL_RESPONSE,
    RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
    RUNNER_STATUS_REFUSED,
    RUNNER_STATUS_SUCCESS,
    parse_adaptation_author_response,
    run_llm_adaptation_author,
)
from utils.toolkit_adaptation_authoring import (
    AUTHORING_STATUS_BLOCKED,
    AUTHORING_STATUS_READY,
    DIAGNOSTIC_CODE_INVALID_RIGHTS,
    prepare_adaptation_authoring_preflight,
    run_adaptation_authoring,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_READY,
    ADAPTATION_DOSSIER_STATUS_REFUSED,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_APPROVED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
)
from utils.toolkit_adaptation_source_context import build_adaptation_source_context

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_author_provider_contract"
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
SOURCE_HASH = "a" * 64
SOURCE_PATH = "scripts/fixtures/toolkit_adaptation_catalogue.md"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

# Modules whose source must stay provider-free; scanned by the hygiene class.
PROVIDER_FREE_MODULES = (
    REPO_ROOT / "utils" / "toolkit_adaptation_author.py",
    REPO_ROOT / "utils" / "toolkit_adaptation_authoring.py",
    REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py",
)


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _response(content: Optional[str] = None, *, refusal: Optional[str] = None) -> Any:
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], model="gpt-5.6-luna", id="resp-provider-contract-1")


class FakeCompletions:
    def __init__(self, response: Any = None, error: Optional[Exception] = None) -> None:
        self.response = response
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response: Any = None, error: Optional[Exception] = None) -> None:
        self.completions = FakeCompletions(response=response, error=error)
        self.chat = SimpleNamespace(completions=self.completions)


def _user_authored_metadata(fixture: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "attempt_id": "attempt-provider-contract-1",
        "source_title": fixture["source_title"],
        "source_hash": fixture["source_hash"],
        "source_profile": fixture["source_profile"],
        "rights_class": fixture["rights_class"],
        "rights_basis": fixture["rights_basis"],
        "rights_review_required": fixture["rights_review_required"],
        "rights_review_status": fixture["rights_review_status"],
    }


def _source_context(fixture: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "source_title": fixture["source_title"],
        "source_profile_hint": "catalogue",
        "bounded_excerpt": "A catalogue of useful lanterns.",
    }


def _echo_dossier(
    attempt_metadata: Mapping[str, Any],
    *,
    rights_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a schema-valid ready dossier that echoes the Python-owned
    attempt identity, with an optional provider relabel for misbehavior
    tests."""
    dossier = copy.deepcopy(_load_fixture())
    dossier["source_hash"] = attempt_metadata["source_hash"]
    dossier["source_title"] = attempt_metadata["source_title"]
    dossier["source_profile"] = attempt_metadata["source_profile"]
    dossier["rights_class"] = attempt_metadata["rights_class"]
    dossier["rights_basis"] = attempt_metadata["rights_basis"]
    dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
    dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
    dossier["adaptation_mode"] = "llm_adaptation"
    if rights_override:
        dossier.update(copy.deepcopy(dict(rights_override)))
    return dossier


class _FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(
        self,
        *,
        rights_override: Optional[Mapping[str, Any]] = None,
        refused: bool = False,
    ) -> None:
        self.calls: List[tuple] = []
        self.rights_override = rights_override
        self.refused = refused

    def __call__(
        self, source_context: Any, attempt_metadata: Optional[Mapping[str, Any]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        self.calls.append(
            (
                deepcopy(dict(source_context)) if isinstance(source_context, dict) else source_context,
                deepcopy(dict(attempt_metadata or {})),
                dict(kwargs),
            )
        )
        if self.refused:
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": "refusal",
                "diagnostics": [
                    {"code": "dossier_refused", "message": "adaptation author refused the source"}
                ],
                "dossier": None,
            }
        dossier = _echo_dossier(
            dict(attempt_metadata or {}), rights_override=self.rights_override
        )
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-provider-1"},
            "params_used": {"reasoning_effort": "medium"},
        }


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        # The scratch root is always project-local, never an OS temp path.
        self.assertTrue(str(self.scratch).startswith(str(REPO_ROOT / "tmp")))


class TestValidUserAuthoredMetadata(unittest.TestCase):
    """Case 1: valid user-authored metadata stays build-ready where allowed."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = _user_authored_metadata(self.fixture)
        self.source_context = _source_context(self.fixture)

    def test_runner_accepts_valid_user_authored_dossier(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-5.6-luna",
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["outcome"], OUTCOME_VALID)
        self.assertTrue(result["ok"])
        self.assertEqual(result["safe_class"], REASON_CATEGORY_NONE)
        self.assertEqual(result["reason_code"], REASON_CODE_NONE)
        # The dossier echoes the Python-owned rights metadata exactly.
        for field in (
            "rights_class",
            "rights_basis",
            "rights_review_required",
            "rights_review_status",
        ):
            self.assertEqual(result["dossier"][field], self.metadata[field], field)
        self.assertEqual(result["dossier"]["status"], ADAPTATION_DOSSIER_STATUS_READY)
        self.assertFalse(result["revision_eligible"])

    def test_parser_confirms_python_rights_authority(self) -> None:
        result = parse_adaptation_author_response(
            json.dumps(self.fixture), attempt_metadata=self.metadata
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dossier_validation"]["build_ready"])
        for field in (
            "rights_class",
            "rights_review_required",
            "rights_review_status",
        ):
            self.assertEqual(result["dossier"][field], self.metadata[field], field)

    def test_python_parser_remains_final_authority(self) -> None:
        # Provider schema compliance is not build success: a schema-valid
        # dossier with the wrong source identity still fails the parser.
        payload = copy.deepcopy(self.fixture)
        payload["source_hash"] = "b" * 64
        result = parse_adaptation_author_response(
            json.dumps(payload), attempt_metadata=self.metadata
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertFalse(result["ok"])
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PROVENANCE, codes)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_RIGHTS_OR_PROVENANCE)
        self.assertEqual(result["reason_code"], REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH)

    def test_runner_leaves_no_raw_source_or_credentials_in_result(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-5.6-luna",
        )
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("bounded_excerpt", encoded)
        self.assertNotIn("sk-", encoded)
        self.assertNotIn("api_key", encoded)
        self.assertTrue(encoded.isascii())


class TestMissingRightsMetadata(_ProjectLocalScratchMixin, unittest.TestCase):
    """Case 2: missing rights metadata is blocked safely before provider work."""

    def test_envelope_missing_rights_fails_closed(self) -> None:
        import web.extensions.toolkit_adaptation_runtime as runtime

        envelope = runtime.build_adaptation_runtime_envelope(
            "upload_markdown",
            source_text=FIXTURE_TEXT,
            source_title="Sunken Lighthouse",
            source_hash=FIXTURE_HASH,
        )
        self.assertEqual(envelope["status"], runtime.ENVELOPE_STATUS_INVALID)
        codes = {item["code"] for item in envelope["diagnostics"]}
        self.assertIn("rights_class_invalid", codes)
        self.assertIn("rights_basis_missing", codes)
        self.assertNotIn("provider_rights_override_rejected", codes)

    def test_authoring_missing_rights_blocks_before_runner(self) -> None:
        context = build_adaptation_source_context(
            source_summary={
                "source_title": "The Lantern Catalogue",
                "summary": "A bounded catalogue source.",
                "source_hash": SOURCE_HASH,
                "source_path": SOURCE_PATH,
            },
            source_path=SOURCE_PATH,
            source_hash=SOURCE_HASH,
            source_title="The Lantern Catalogue",
            profile_override="catalogue",
        )
        runner = _FakeAuthorRunner()
        workspace = self.scratch / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        result = run_adaptation_authoring(
            context,
            workspace=workspace,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            author_runner=runner,
        )
        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_INVALID_RIGHTS, codes)
        # No provider work happens and no dossier is produced.
        self.assertEqual(runner.calls, [])
        self.assertIsNone(result["dossier"])
        self.assertFalse(result["module_builder_allowed"])
        self.assertFalse(result["module_builder_started"])
        # The preflight is blocked before an attempt identity exists, so no
        # failure artifact can be keyed to an attempt; the bounded diagnostics
        # are retained on the blocked result itself.
        self.assertFalse(result["failure_artifact_persisted"])
        self.assertIn("invalid_rights_metadata", {item["code"] for item in result["diagnostics"]})

    def test_preflight_missing_rights_is_blocked(self) -> None:
        context = build_adaptation_source_context(
            source_summary={
                "source_title": "The Lantern Catalogue",
                "summary": "A bounded catalogue source.",
                "source_hash": SOURCE_HASH,
                "source_path": SOURCE_PATH,
            },
            source_path=SOURCE_PATH,
            source_hash=SOURCE_HASH,
            source_title="The Lantern Catalogue",
            profile_override="catalogue",
        )
        preflight = prepare_adaptation_authoring_preflight(
            context,
            workspace=self.scratch / "workspace",
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
        )
        self.assertFalse(preflight["ok"])
        self.assertEqual(preflight["status"], AUTHORING_STATUS_BLOCKED)
        codes = {item["code"] for item in preflight["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_INVALID_RIGHTS, codes)
        self.assertFalse(preflight["module_builder_allowed"])


class TestRestrictedRightsGating(_ProjectLocalScratchMixin, unittest.TestCase):
    """Case 3: restricted rights stay review-gated at every boundary."""

    def _context(self) -> Dict[str, Any]:
        return build_adaptation_source_context(
            source_summary={
                "source_title": "The Lantern Catalogue",
                "summary": "A bounded catalogue source.",
                "source_hash": SOURCE_HASH,
                "source_path": SOURCE_PATH,
            },
            source_path=SOURCE_PATH,
            source_hash=SOURCE_HASH,
            source_title="The Lantern Catalogue",
            profile_override="catalogue",
        )

    def _author(
        self,
        *,
        rights_class: str,
        review_required: bool,
        review_status: str,
        rights_override: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        workspace = self.scratch / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return run_adaptation_authoring(
            self._context(),
            workspace=workspace,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            rights_class=rights_class,
            rights_basis="Third-party copyright restricted source.",
            rights_review_required=review_required,
            rights_review_status=review_status,
            author_runner=_FakeAuthorRunner(rights_override=rights_override),
        )

    def test_restricted_pending_never_build_ready(self) -> None:
        result = self._author(
            rights_class=RIGHTS_CLASS_RESTRICTED,
            review_required=True,
            review_status=RIGHTS_REVIEW_PENDING,
        )
        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("dossier_not_build_ready", codes)
        self.assertIsNone(result["dossier"])
        self.assertFalse(result["module_builder_allowed"])
        self.assertFalse(result["module_builder_started"])
        self.assertEqual(result["safe_class"], REASON_CATEGORY_DOSSIER_VALIDATION)
        self.assertEqual(result["reason_code"], REASON_CODE_DOSSIER_NOT_BUILD_READY)

    def test_restricted_approved_may_proceed(self) -> None:
        result = self._author(
            rights_class=RIGHTS_CLASS_RESTRICTED,
            review_required=True,
            review_status=RIGHTS_REVIEW_APPROVED,
        )
        self.assertEqual(result["status"], AUTHORING_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertEqual(result["dossier"]["rights_class"], RIGHTS_CLASS_RESTRICTED)
        self.assertEqual(result["dossier"]["rights_review_status"], RIGHTS_REVIEW_APPROVED)
        self.assertFalse(result["module_builder_allowed"] is True and result["completed"])

    def test_restricted_relabel_to_user_authored_is_rejected(self) -> None:
        result = self._author(
            rights_class=RIGHTS_CLASS_RESTRICTED,
            review_required=True,
            review_status=RIGHTS_REVIEW_PENDING,
            rights_override={
                "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                "rights_review_required": False,
                "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
            },
        )
        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_INVALID_PROVENANCE, codes)
        self.assertFalse(result["module_builder_allowed"])


class TestApiLevelRefusal(unittest.TestCase):
    """Case 4: API-level refusal is a distinct bounded refusal channel."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = _user_authored_metadata(self.fixture)
        self.source_context = _source_context(self.fixture)

    def test_api_refusal_channel_is_bounded_and_explicit(self) -> None:
        client = FakeClient(response=_response(refusal="provider secret material must never leak"))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-5.6-luna",
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED)
        self.assertEqual(result["outcome"], OUTCOME_EXPLICIT_REFUSAL)
        self.assertFalse(result["ok"])
        self.assertEqual(result["safe_class"], REASON_CATEGORY_API_REFUSAL)
        self.assertEqual(result["reason_code"], REASON_CODE_PROVIDER_API_REFUSAL)
        self.assertIsNone(result["dossier"])
        self.assertIsNone(result["dossier_status"])
        self.assertTrue(result["terminal"])
        self.assertFalse(result["revision_eligible"])
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_PROVIDER_REFUSAL, codes)
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("secret material", encoded)
        self.assertNotIn("sk-", encoded)

    def test_api_refusal_never_build_ready(self) -> None:
        client = FakeClient(response=_response(refusal="no"))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-5.6-luna",
        )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        self.assertEqual(result["error"], "provider_refused")


class TestDossierStatusRefused(unittest.TestCase):
    """Case 5: dossier ``status: refused`` is a distinct author-policy refusal."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = _user_authored_metadata(self.fixture)
        self.source_context = _source_context(self.fixture)

    def test_dossier_refused_preserves_refusal_and_warnings(self) -> None:
        payload = copy.deepcopy(self.fixture)
        payload["status"] = ADAPTATION_DOSSIER_STATUS_REFUSED
        payload["warnings"] = ["Rights review required before adaptation."]
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=FakeClient(response=_response(json.dumps(payload))),
            model="gpt-5.6-luna",
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_AUTHOR_POLICY_REFUSAL)
        self.assertEqual(result["reason_code"], REASON_CODE_DOSSIER_REFUSED)
        self.assertEqual(result["dossier_status"], ADAPTATION_DOSSIER_STATUS_REFUSED)
        # The refused dossier is preserved for diagnostics but never build-ready.
        self.assertEqual(result["dossier"]["status"], ADAPTATION_DOSSIER_STATUS_REFUSED)
        self.assertIn("Rights review required", result["dossier"]["warnings"][0])
        self.assertFalse(result["ok"])
        self.assertTrue(result["terminal"])
        self.assertFalse(result["revision_eligible"])

    def test_api_refusal_and_dossier_refusal_are_distinct(self) -> None:
        api_result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=FakeClient(response=_response(refusal="no")),
            model="gpt-5.6-luna",
        )
        payload = copy.deepcopy(self.fixture)
        payload["status"] = ADAPTATION_DOSSIER_STATUS_REFUSED
        dossier_result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=FakeClient(response=_response(json.dumps(payload))),
            model="gpt-5.6-luna",
        )
        # Same runner status, different refusal channel and diagnostics.
        self.assertEqual(api_result["status"], RUNNER_STATUS_REFUSED)
        self.assertEqual(dossier_result["status"], RUNNER_STATUS_REFUSED)
        self.assertNotEqual(api_result["safe_class"], dossier_result["safe_class"])
        self.assertEqual(api_result["safe_class"], REASON_CATEGORY_API_REFUSAL)
        self.assertEqual(dossier_result["safe_class"], REASON_CATEGORY_AUTHOR_POLICY_REFUSAL)
        self.assertIsNone(api_result["dossier"])
        self.assertIsNotNone(dossier_result["dossier"])
        self.assertNotEqual(api_result["reason_code"], dossier_result["reason_code"])

    def test_parser_refused_never_becomes_build_ready(self) -> None:
        payload = copy.deepcopy(self.fixture)
        payload["status"] = ADAPTATION_DOSSIER_STATUS_REFUSED
        result = parse_adaptation_author_response(
            json.dumps(payload), attempt_metadata=self.metadata
        )
        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED)
        self.assertFalse(result["ok"])
        self.assertIs(result["dossier_validation"].get("build_ready"), False)


class TestMalformedStructuredOutput(unittest.TestCase):
    """Case 6: malformed structured output is invalid_model_response."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = _user_authored_metadata(self.fixture)
        self.source_context = _source_context(self.fixture)

    def _run(self, content: Any) -> Dict[str, Any]:
        return run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=FakeClient(response=_response(content)),
            model="gpt-5.6-luna",
        )

    def test_not_json_is_invalid_model_response_and_never_build_ready(self) -> None:
        result = self._run("not-json-at-all")
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["outcome"], OUTCOME_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["reason_code"], REASON_CODE_INVALID_MODEL_RESPONSE)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        self.assertTrue(result["terminal"])
        self.assertFalse(result["revision_eligible"])

    def test_markdown_fence_is_invalid_model_response(self) -> None:
        fenced = "```json\n" + json.dumps(self.fixture) + "\n```"
        result = self._run(fenced)
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_MARKDOWN_FENCE, codes)
        self.assertIsNone(result["dossier"])

    def test_non_ascii_response_is_invalid_model_response(self) -> None:
        result = self._run('{"status": "ready", "source_title": "\u00e9lan"}')
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("non_ascii_response", codes)
        self.assertIsNone(result["dossier"])

    def test_decoded_mapping_cannot_bypass_raw_json_boundary(self) -> None:
        result = parse_adaptation_author_response(
            _load_fixture(), attempt_metadata=self.metadata
        )
        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertIsNone(result["dossier"])

    def test_malformed_output_never_reaches_staging_or_publication(self) -> None:
        # The author runner performs no file, staging, registry, or campaign
        # writes; a malformed response must simply stop before any build work.
        result = self._run("not-json-at-all")
        self.assertIsNone(result.get("staging_target_path"))
        self.assertIsNone(result.get("published_to_modules"))
        self.assertFalse(result["ok"])
        # And the bounded diagnostic payload contains no raw response text.
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("not-json-at-all", encoded)
        self.assertTrue(encoded.isascii())


class TestGpt5ParameterIsolation(unittest.TestCase):
    """Case 7: direct GPT-5 requests keep reasoning/verbosity, omit legacy
    sampling, and stay on the strict structured-output contract."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = _user_authored_metadata(self.fixture)
        self.source_context = _source_context(self.fixture)

    def test_direct_gpt5_request_keeps_reasoning_and_omits_legacy_sampling(self) -> None:
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
            request["response_format"]["type"], ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT
        )
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertEqual(result["request"]["response_format"], ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT)
        # The bounded request metadata records the parameter keys actually
        # sent to the provider without legacy sampling fields.
        parameter_keys = set(result["request"]["parameter_keys"])
        self.assertIn("reasoning_effort", parameter_keys)
        self.assertIn("verbosity", parameter_keys)
        self.assertNotIn("temperature", parameter_keys)
        self.assertNotIn("top_p", parameter_keys)

    def test_resolver_reserved_keys_remain_rejected(self) -> None:
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
        self.assertEqual(result["outcome"], OUTCOME_PARAMETER_RESOLUTION_FAILURE)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_PARAMETER_RESOLUTION)
        self.assertEqual(result["reason_code"], REASON_CODE_PARAM_RESOLUTION_FAILED)
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn(DIAGNOSTIC_CODE_PARAM_RESOLUTION_FAILED, codes)
        self.assertEqual(client.completions.calls, [])
        self.assertFalse(result["revision_eligible"])

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
            request["response_format"], {"type": ADAPTATION_AUTHOR_RESPONSE_FORMAT_LEGACY}
        )
        self.assertFalse(result["request"]["response_format_strict"])

    def test_parameter_isolation_is_independent_of_resolver_injection(self) -> None:
        # An injected resolver still flows through the same strict response
        # format contract and the same reserved-key guard.
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-5.6-luna",
            parameter_resolver=lambda task_id, model: {
                "model": model,
                "reasoning_effort": "high",
                "verbosity": "low",
            },
        )
        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        request = client.completions.calls[0]
        self.assertEqual(request["reasoning_effort"], "high")
        self.assertEqual(request["verbosity"], "low")
        self.assertNotIn("temperature", request)
        self.assertNotIn("top_p", request)
        self.assertEqual(
            request["response_format"]["type"], ADAPTATION_AUTHOR_RESPONSE_FORMAT_STRICT
        )


class TestProviderContractHygiene(unittest.TestCase):
    """Bounded secrets/raw-source checks and provider-free path hygiene."""

    def test_refusal_and_malformed_results_never_leak_secrets_or_raw_source(self) -> None:
        fixture = _load_fixture()
        metadata = _user_authored_metadata(fixture)
        source_context = _source_context(fixture)
        results: List[Dict[str, Any]] = [
            run_llm_adaptation_author(
                source_context,
                metadata,
                client=FakeClient(response=_response(refusal="api_key=sk-secret123 refused")),
                model="gpt-5.6-luna",
            ),
            run_llm_adaptation_author(
                source_context,
                metadata,
                client=FakeClient(response=_response("not-json at all")),
                model="gpt-5.6-luna",
            ),
            run_llm_adaptation_author(
                source_context,
                metadata,
                client=FakeClient(
                    response=_response(
                        json.dumps({**copy.deepcopy(fixture), "status": ADAPTATION_DOSSIER_STATUS_REFUSED})
                    )
                ),
                model="gpt-5.6-luna",
            ),
        ]
        for result in results:
            encoded = json.dumps(result, sort_keys=True)
            self.assertNotIn("sk-secret123", encoded)
            self.assertNotIn("api_key=", encoded)
            self.assertNotIn("not-json at all", encoded)
            self.assertNotIn(str(REPO_ROOT), encoded)
            self.assertTrue(encoded.isascii())

    def test_runtime_author_and_authoring_modules_stay_provider_free(self) -> None:
        forbidden = (
            "tempfile",
            "/tmp",
            "socketio",
            "requests.get",
            "urllib.request",
            "start_build",
            "simulate_build_process",
            "web_interface",
        )
        for path in PROVIDER_FREE_MODULES:
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(
                    token,
                    source,
                    f"{path.name} must not reference {token}",
                )
            self.assertTrue(source.isascii(), f"{path.name} must stay ASCII")

    def test_ascii_only_and_spdx_header(self) -> None:
        test_source = Path(__file__).read_text(encoding="utf-8")
        non_ascii = [char for char in test_source if ord(char) > 127]
        self.assertEqual(non_ascii, [], "non-ASCII characters in the test file")
        header = test_source[:160]
        self.assertIn("SPDX-FileCopyrightText", header)
        self.assertIn("SPDX-License-Identifier", header)

    def test_scratch_stays_project_local(self) -> None:
        scratch = SCRATCH_ROOT / str(uuid.uuid4())
        scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertTrue(str(scratch).startswith(str(REPO_ROOT / "tmp")))
        # The OS absolute temp root is never used as scratch.
        self.assertFalse(str(scratch).startswith("/tmp/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
