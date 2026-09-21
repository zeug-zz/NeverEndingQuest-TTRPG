# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for extended author/authoring/adapter failure
diagnostics (task 3.2 of toolkit-llm-adaptation-runtime-unification).

The suite locks the safe, bounded reason classification at every adaptation
boundary:

  * the author runner and parser distinguish API refusal, author-policy
    refusal, quota, timeout, dependency, parameter resolution, invalid
    model response, rights/provenance contradiction, and dossier-validation
    outcomes via explicit ``safe_class``/``reason_code`` fields;
  * existing ``status``/``outcome``/``failure_class`` keys remain unchanged
    for callers and tests;
  * author outcomes never consume the semantic revision budget
    (``revision_eligible`` is always False on failure results);
  * raw provider/refusal text, credentials, full prompts, and unbounded
    response bodies are never persisted or returned;
  * authoring failure artifacts and adapter results carry the same bounded
    reason fields and stay contract-valid;
  * dossier ``status: refused`` stays distinguishable and never build-ready.

All fixtures and scratch live under the project-local scratch root
``tmp/toolkit_adaptation_failure_diagnostics/<uuid>/`` and are removed via
addCleanup. No OS temp directory, no network, and no provider calls are used.
"""

import copy
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_SOURCE_CONTEXT,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
    validate_adaptation_artifact,
)
from utils.toolkit_adaptation_author import (
    REASON_CATEGORY_API_REFUSAL,
    REASON_CATEGORY_AUTHOR_POLICY_REFUSAL,
    REASON_CATEGORY_DEPENDENCY,
    REASON_CATEGORY_DOSSIER_VALIDATION,
    REASON_CATEGORY_INVALID_MODEL_RESPONSE,
    REASON_CATEGORY_NONE,
    REASON_CATEGORY_PARAMETER_RESOLUTION,
    REASON_CATEGORY_PROVIDER_INFRASTRUCTURE,
    REASON_CATEGORY_QUOTA,
    REASON_CATEGORY_RIGHTS_OR_PROVENANCE,
    REASON_CATEGORY_TIMEOUT,
    REASON_CODE_AUTHOR_PROMPT_FAILED,
    REASON_CODE_DEPENDENCY_IMPORT_FAILED,
    REASON_CODE_DOSSIER_FAILED,
    REASON_CODE_DOSSIER_NOT_BUILD_READY,
    REASON_CODE_DOSSIER_REFUSED,
    REASON_CODE_DOSSIER_VALIDATION_FAILED,
    REASON_CODE_INVALID_MODEL_RESPONSE,
    REASON_CODE_INVALID_TIMEOUT,
    REASON_CODE_NONE,
    REASON_CODE_PARAM_RESOLUTION_FAILED,
    REASON_CODE_PROVIDER_API_REFUSAL,
    REASON_CODE_PROVIDER_CALL_FAILED,
    REASON_CODE_QUOTA_EXCEEDED,
    REASON_CODE_REQUEST_TIMEOUT,
    REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH,
    RUNNER_STATUS_INVALID_MODEL_RESPONSE,
    RUNNER_STATUS_PARAM_RESOLUTION_FAILED,
    RUNNER_STATUS_PROVIDER_FAILED,
    RUNNER_STATUS_REFUSED,
    RUNNER_STATUS_SUCCESS,
    parse_adaptation_author_response,
    run_llm_adaptation_author,
)
from utils.toolkit_adaptation_authoring import (
    AUTHORING_STATUS_BLOCKED,
    AUTHORING_STATUS_READY,
    run_adaptation_authoring,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_REFUSED,
    RIGHTS_CLASS_USER_AUTHORED,
)
from utils.toolkit_adaptation_source_context import build_adaptation_source_context
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    SOURCE_RIGHTS_USER_AUTHORED,
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
    persist_normalized_packet_artifact,
    persist_review_snapshot_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_failure_diagnostics"
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

PACKET_LOCATIONS = [
    {"name": "Keeper's Quarters", "location": "tower", "description": "Rusted spyglass."},
    {"name": "Flooded Stairs", "location": "stairs", "description": "Dark water."},
]


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _response(content: Optional[str] = None, *, refusal: Optional[str] = None) -> Any:
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], model="gpt-5.6-luna", id="resp-diagnostics-1")


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


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)


class TestAuthorRunnerReasonCategories(unittest.TestCase):
    """The author runner classifies each failure family with safe fields."""

    def setUp(self) -> None:
        self.fixture = _load_fixture()
        self.metadata = {
            "attempt_id": "attempt-diagnostics-1",
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

    def _run(self, *, response: Any = None, error: Optional[Exception] = None, resolver: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
        return run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=FakeClient(response=response, error=error),
            model="gpt-5.6-luna",
            parameter_resolver=resolver,
        )

    def test_api_refusal_channel_is_distinguishable(self) -> None:
        result = self._run(response=_response(refusal="provider secret should not leak"))

        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_API_REFUSAL)
        self.assertEqual(result["reason_code"], REASON_CODE_PROVIDER_API_REFUSAL)
        self.assertFalse(result["ok"])
        self.assertFalse(result["revision_eligible"])
        self.assertFalse(result["retryable"])
        self.assertTrue(result["terminal"])
        # Raw refusal text is discarded and never returned or persisted.
        self.assertNotIn("provider secret", json.dumps(result, sort_keys=True))

    def test_author_policy_refusal_dossier_is_distinguishable(self) -> None:
        payload = copy.deepcopy(self.fixture)
        payload["status"] = ADAPTATION_DOSSIER_STATUS_REFUSED
        result = self._run(response=_response(json.dumps(payload)))

        self.assertEqual(result["status"], RUNNER_STATUS_REFUSED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_AUTHOR_POLICY_REFUSAL)
        self.assertEqual(result["reason_code"], REASON_CODE_DOSSIER_REFUSED)
        self.assertFalse(result["ok"])
        self.assertFalse(result["revision_eligible"])
        # The refused dossier remains distinguishable and never build-ready:
        # the runner result is not ok and the dossier keeps its refused status.
        self.assertEqual(result["dossier_status"], ADAPTATION_DOSSIER_STATUS_REFUSED)
        self.assertEqual(result["dossier"]["status"], ADAPTATION_DOSSIER_STATUS_REFUSED)

    def test_quota_failure_is_distinguishable(self) -> None:
        result = self._run(error=RuntimeError("insufficient_quota exceeded for model"))

        self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_QUOTA)
        self.assertEqual(result["reason_code"], REASON_CODE_QUOTA_EXCEEDED)
        self.assertTrue(result["retryable"])
        self.assertFalse(result["terminal"])
        self.assertFalse(result["revision_eligible"])

    def test_timeout_failure_is_distinguishable(self) -> None:
        result = self._run(error=TimeoutError("request timed out"))

        self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_TIMEOUT)
        self.assertEqual(result["reason_code"], REASON_CODE_REQUEST_TIMEOUT)
        self.assertTrue(result["retryable"])
        self.assertFalse(result["terminal"])
        self.assertFalse(result["revision_eligible"])

    def test_dependency_import_failure_is_distinguishable(self) -> None:
        result = self._run(error=ModuleNotFoundError("no module named openai"))

        self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_DEPENDENCY)
        self.assertEqual(result["reason_code"], REASON_CODE_DEPENDENCY_IMPORT_FAILED)
        self.assertFalse(result["retryable"])
        self.assertTrue(result["terminal"])
        self.assertFalse(result["revision_eligible"])

    def test_connection_and_service_failures_map_to_provider_infrastructure(self) -> None:
        for message in ("connection refused by provider", "503 service unavailable"):
            with self.subTest(message=message):
                result = self._run(error=RuntimeError(message))
                self.assertEqual(result["status"], RUNNER_STATUS_PROVIDER_FAILED)
                self.assertEqual(
                    result["safe_class"], REASON_CATEGORY_PROVIDER_INFRASTRUCTURE
                )
                self.assertEqual(result["reason_code"], REASON_CODE_PROVIDER_CALL_FAILED)
                self.assertTrue(result["retryable"])
                self.assertFalse(result["revision_eligible"])

    def test_parameter_resolution_failure_is_distinguishable_without_provider_call(self) -> None:
        client = FakeClient(response=_response(json.dumps(self.fixture)))
        result = run_llm_adaptation_author(
            self.source_context,
            self.metadata,
            client=client,
            model="gpt-5.6-luna",
            parameter_resolver=lambda task_id, model: (_ for _ in ()).throw(
                RuntimeError("resolver secret must not leak")
            ),
        )

        self.assertEqual(result["status"], RUNNER_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_PARAMETER_RESOLUTION)
        self.assertEqual(result["reason_code"], REASON_CODE_PARAM_RESOLUTION_FAILED)
        self.assertFalse(result["revision_eligible"])
        self.assertFalse(result["retryable"])
        self.assertTrue(result["terminal"])
        self.assertEqual(client.completions.calls, [])
        self.assertNotIn("resolver secret", json.dumps(result, sort_keys=True))

    def test_invalid_model_response_is_distinguishable(self) -> None:
        result = self._run(response=_response("not-json-at-all"))

        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["reason_code"], REASON_CODE_INVALID_MODEL_RESPONSE)
        self.assertFalse(result["revision_eligible"])
        self.assertTrue(result["terminal"])

    def test_rights_provenance_contradiction_is_distinguishable(self) -> None:
        payload = copy.deepcopy(self.fixture)
        payload["source_hash"] = "b" * 64
        result = self._run(response=_response(json.dumps(payload)))

        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_RIGHTS_OR_PROVENANCE)
        self.assertEqual(result["reason_code"], REASON_CODE_RIGHTS_OR_PROVENANCE_MISMATCH)
        self.assertFalse(result["revision_eligible"])
        self.assertTrue(result["terminal"])

    def test_valid_response_carries_none_reason_markers(self) -> None:
        result = self._run(response=_response(json.dumps(self.fixture)))

        self.assertEqual(result["status"], RUNNER_STATUS_SUCCESS)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_NONE)
        self.assertEqual(result["reason_code"], REASON_CODE_NONE)
        self.assertFalse(result["revision_eligible"])
        self.assertFalse(result["retryable"])
        self.assertFalse(result["terminal"])

    def test_no_failure_category_consumes_revision_budget(self) -> None:
        cases = [
            _response(refusal="refused"),
            _response(json.dumps({**self.fixture, "status": ADAPTATION_DOSSIER_STATUS_REFUSED})),
            _response(json.dumps({**self.fixture, "source_hash": "c" * 64})),
            _response("not-json"),
            _response(json.dumps({**self.fixture, "status": "ready", "rights_review_required": True, "rights_review_status": "pending"})),
        ]
        errors = [RuntimeError("quota"), TimeoutError("timeout"), ModuleNotFoundError("missing")]
        for response in cases:
            with self.subTest(kind="response"):
                result = self._run(response=response)
                self.assertFalse(result["revision_eligible"])
        for error in errors:
            with self.subTest(kind="exception", error=type(error).__name__):
                result = self._run(error=error)
                self.assertFalse(result["revision_eligible"])


class TestAuthorParserReasonCategories(unittest.TestCase):
    """The parser distinguishes dossier validation from generic responses."""

    def setUp(self) -> None:
        fixture = _load_fixture()
        self.metadata = {
            "attempt_id": "attempt-parser-diag-1",
            "source_hash": fixture["source_hash"],
            "source_title": fixture["source_title"],
            "source_profile": fixture["source_profile"],
            "rights_class": fixture["rights_class"],
        }

    def test_schema_failure_maps_to_dossier_validation(self) -> None:
        payload = copy.deepcopy(_load_fixture())
        payload["status"] = "bogus_status"
        result = parse_adaptation_author_response(
            json.dumps(payload), attempt_metadata=self.metadata
        )

        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_DOSSIER_VALIDATION)
        self.assertEqual(result["reason_code"], REASON_CODE_DOSSIER_VALIDATION_FAILED)
        self.assertFalse(result["revision_eligible"])

    def test_valid_but_not_build_ready_maps_to_dossier_validation(self) -> None:
        payload = copy.deepcopy(_load_fixture())
        payload["rights_review_required"] = True
        payload["rights_review_status"] = "pending"
        result = parse_adaptation_author_response(
            json.dumps(payload), attempt_metadata=self.metadata
        )

        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_DOSSIER_VALIDATION)
        self.assertEqual(result["reason_code"], REASON_CODE_DOSSIER_NOT_BUILD_READY)
        self.assertFalse(result["ok"])
        self.assertFalse(result["revision_eligible"])

    def test_dossier_failed_status_maps_to_dossier_validation(self) -> None:
        payload = copy.deepcopy(_load_fixture())
        payload["status"] = "failed"
        result = parse_adaptation_author_response(
            json.dumps(payload), attempt_metadata=self.metadata
        )

        self.assertEqual(result["status"], RUNNER_STATUS_INVALID_MODEL_RESPONSE)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_DOSSIER_VALIDATION)
        self.assertEqual(result["reason_code"], REASON_CODE_DOSSIER_FAILED)
        self.assertFalse(result["revision_eligible"])

    def test_invalid_timeout_is_a_parameter_category(self) -> None:
        result = run_llm_adaptation_author(
            {"source_title": "t", "bounded_excerpt": "x"},
            self.metadata,
            client=FakeClient(response=_response(json.dumps(_load_fixture()))),
            model="gpt-5.6-luna",
            timeout_seconds=0,
        )

        self.assertEqual(result["status"], RUNNER_STATUS_PARAM_RESOLUTION_FAILED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_PARAMETER_RESOLUTION)
        self.assertEqual(result["reason_code"], REASON_CODE_INVALID_TIMEOUT)
        self.assertFalse(result["revision_eligible"])


class TestAuthoringFailureReasonPropagation(_ProjectLocalScratchMixin, unittest.TestCase):
    """Authoring results and failure artifacts carry the bounded reason fields."""

    def setUp(self) -> None:
        super().setUp()
        self.fixture = _load_fixture()
        self.context = build_adaptation_source_context(
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
        self.rights = {
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "rights_basis": "Operator attested that the source is user-authored.",
            "rights_review_required": False,
            "rights_review_status": "not_required",
        }
        self.workspace = self.scratch / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _run(self, *, runner: Any = None, **kwargs: Any) -> Dict[str, Any]:
        return run_adaptation_authoring(
            self.context,
            workspace=self.workspace,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            rights_metadata=self.rights,
            rights_class=self.rights["rights_class"],
            rights_basis=self.rights["rights_basis"],
            rights_review_required=False,
            rights_review_status="not_required",
            author_runner=runner,
            **kwargs,
        )

    def test_blocked_refusal_result_carries_safe_reason_and_artifact(self) -> None:
        def refused_runner(*args: Any, **kwargs: Any) -> Dict[str, Any]:
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

        result = self._run(runner=refused_runner)

        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertEqual(result["safe_class"], REASON_CATEGORY_AUTHOR_POLICY_REFUSAL)
        self.assertEqual(result["reason_code"], REASON_CODE_DOSSIER_REFUSED)
        self.assertFalse(result["revision_eligible"])
        self.assertFalse(result["retryable"])
        self.assertTrue(result["terminal"])
        self.assertTrue(result["failure_artifact_persisted"])
        artifact = load_adaptation_artifact(
            self.workspace, result["attempt_id"], ARTIFACT_KIND_FAILURE_REPORT
        )
        self.assertEqual(artifact["payload"]["safe_class"], REASON_CATEGORY_AUTHOR_POLICY_REFUSAL)
        self.assertEqual(artifact["payload"]["reason_code"], REASON_CODE_DOSSIER_REFUSED)
        self.assertFalse(artifact["payload"]["revision_eligible"])
        validation = validate_adaptation_artifact(artifact)
        self.assertTrue(validation.get("valid"), validation.get("diagnostics"))
        self.assertIsNone(
            load_adaptation_artifact(
                self.workspace, result["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
            )
        )

    def test_blocked_provider_timeout_result_is_retryable_and_terminal_false(self) -> None:
        # The real author runner returns a classified blocked result; the
        # authoring boundary forwards the timeout category and retry markers.
        def timeout_runner(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            return {
                "status": "provider_failed",
                "outcome": "provider_failure",
                "ok": False,
                "failure_class": "timeout",
                "diagnostics": [
                    {"code": "provider_failed", "message": "provider call failed (timeout)"}
                ],
                "dossier": None,
            }

        result = self._run(runner=timeout_runner)

        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_TIMEOUT)
        self.assertEqual(result["reason_code"], REASON_CODE_REQUEST_TIMEOUT)
        self.assertFalse(result["revision_eligible"])
        self.assertTrue(result["retryable"])
        self.assertFalse(result["terminal"])

    def test_raising_runner_maps_to_provider_infrastructure(self) -> None:
        def broken_runner(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise TimeoutError("request timed out")

        result = self._run(runner=broken_runner)

        self.assertEqual(result["status"], AUTHORING_STATUS_BLOCKED)
        self.assertEqual(result["safe_class"], REASON_CATEGORY_PROVIDER_INFRASTRUCTURE)
        self.assertEqual(result["reason_code"], REASON_CODE_PROVIDER_CALL_FAILED)
        self.assertFalse(result["revision_eligible"])

    def test_ready_result_carries_none_reason_markers(self) -> None:
        def ready_runner(source_context: Any, attempt_metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
            dossier = copy.deepcopy(self.fixture)
            dossier["source_hash"] = attempt_metadata["source_hash"]
            dossier["source_title"] = attempt_metadata["source_title"]
            dossier["source_profile"] = attempt_metadata["source_profile"]
            dossier["rights_class"] = attempt_metadata["rights_class"]
            dossier["rights_basis"] = attempt_metadata["rights_basis"]
            dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
            dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
            dossier["adaptation_mode"] = "llm_adaptation"
            return {
                "status": "success",
                "outcome": "valid",
                "ok": True,
                "failure_class": "none",
                "dossier": dossier,
                "diagnostics": [],
                "response_metadata": {"model": "mock-model"},
                "params_used": {"reasoning_effort": "medium"},
            }

        result = self._run(runner=ready_runner)

        self.assertEqual(result["status"], AUTHORING_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertEqual(result["safe_class"], REASON_CATEGORY_NONE)
        self.assertEqual(result["reason_code"], REASON_CODE_NONE)
        self.assertFalse(result["revision_eligible"])
        self.assertFalse(result["terminal"])
        self.assertTrue(result["dossier_artifact_persisted"])


def _packet(*, source_hash: str = FIXTURE_HASH, title: str = "Sunken Lighthouse") -> Dict[str, Any]:
    return {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_path": "uploads/fixture.md",
        "source_hash": source_hash,
        "title": title,
        "author": "",
        "description": "A bounded adventure about a sunken lighthouse.",
        "adventure_summary": "The keeper's quarters and the flooded stairs.",
        "module_tone": "haunted",
        "acts": [{"name": "Descent", "summary": "Into the dark."}],
        "locations": PACKET_LOCATIONS,
        "npc_seeds": [],
        "encounter_seeds": [],
        "assumptions": ["Fixture packet for the failure diagnostics tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }


def _make_workspace(scratch: Path, *, text: str = FIXTURE_TEXT) -> Path:
    workspace = scratch / "workspace"
    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
    files["source_original"].write_text(text, encoding="utf-8")
    packet = _packet()
    persist_normalized_packet_artifact(workspace, packet)
    snapshot = build_review_snapshot(
        job_id="job-diag-1",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    persist_review_snapshot_artifact(workspace, snapshot)
    return workspace


class _FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(self, *, refused: bool = False) -> None:
        self.refused = refused

    def __call__(
        self, source_context: Any, attempt_metadata: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
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
        dossier = copy.deepcopy(_load_fixture())
        dossier["source_hash"] = attempt_metadata["source_hash"]
        dossier["source_title"] = attempt_metadata["source_title"]
        dossier["source_profile"] = attempt_metadata["source_profile"]
        dossier["rights_class"] = attempt_metadata["rights_class"]
        dossier["rights_basis"] = attempt_metadata["rights_basis"]
        dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
        dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
        dossier["adaptation_mode"] = "llm_adaptation"
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-model", "request_id": "req-diag-1"},
            "params_used": {"reasoning_effort": "medium"},
        }


class TestAdapterFailureReasonPropagation(_ProjectLocalScratchMixin, unittest.TestCase):
    """Adapter results carry the bounded reason fields and stay contract-valid."""

    def _handoff(self) -> Dict[str, Any]:
        import web.extensions.toolkit_adaptation_runtime as runtime

        workspace = _make_workspace(self.scratch)
        return runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="approved_for_build",
            job_id="job-diag-1",
        )

    def test_adapter_blocked_result_carries_safe_reason_and_validates(self) -> None:
        import web.extensions.toolkit_adaptation_runtime as runtime

        handoff = self._handoff()
        blocked = runtime.run_upload_adaptation_authoring(
            handoff,
            author_runner=_FakeAuthorRunner(refused=True),
            model="mock-model",
        )

        self.assertEqual(blocked["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertEqual(
            blocked["authoring"]["safe_class"], REASON_CATEGORY_AUTHOR_POLICY_REFUSAL
        )
        self.assertEqual(blocked["authoring"]["reason_code"], REASON_CODE_DOSSIER_REFUSED)
        self.assertFalse(blocked["authoring"]["revision_eligible"])
        self.assertFalse(blocked["authoring"]["retryable"])
        self.assertTrue(blocked["authoring"]["terminal"])
        validation = runtime.validate_adaptation_authoring_result(blocked)
        self.assertTrue(validation["valid"], validation["diagnostics"])
        self.assertIsNone(blocked["dossier"])
        # A refused dossier is never build-ready and never reaches the builder.
        self.assertFalse(blocked["guards"]["module_builder_allowed"])

    def test_adapter_ready_result_carries_none_reason_and_validates(self) -> None:
        import web.extensions.toolkit_adaptation_runtime as runtime

        handoff = self._handoff()
        ready = runtime.run_upload_adaptation_authoring(
            handoff,
            author_runner=_FakeAuthorRunner(),
            model="mock-model",
        )

        self.assertEqual(ready["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(ready["authoring"]["safe_class"], REASON_CATEGORY_NONE)
        self.assertEqual(ready["authoring"]["reason_code"], REASON_CODE_NONE)
        self.assertFalse(ready["authoring"]["revision_eligible"])
        validation = runtime.validate_adaptation_authoring_result(ready)
        self.assertTrue(validation["valid"], validation["diagnostics"])


class TestDiagnosticLeakageBounds(unittest.TestCase):
    """Reports contain only allowlisted bounded identifiers and safe reasons."""

    def test_refusal_text_never_leaks_across_boundaries(self) -> None:
        fixture = _load_fixture()
        metadata = {
            "attempt_id": "attempt-leak-1",
            "source_title": fixture["source_title"],
            "source_hash": fixture["source_hash"],
            "source_profile": fixture["source_profile"],
            "rights_class": fixture["rights_class"],
        }
        source_context = {
            "source_title": fixture["source_title"],
            "bounded_excerpt": "A catalogue of useful lanterns.",
        }
        refusal_text = "the provider refused because of secret material"
        result = run_llm_adaptation_author(
            source_context,
            metadata,
            client=FakeClient(response=_response(refusal=refusal_text)),
            model="gpt-5.6-luna",
        )
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("secret material", encoded)
        self.assertNotIn(refusal_text, encoded)
        self.assertNotIn("sk-", encoded)
        self.assertTrue(encoded.isascii())
        # Only allowlisted identifiers are retained.
        self.assertEqual(result["task_id"], "toolkit_adaptation_author")
        self.assertEqual(result["attempt_id"], "attempt-leak-1")
        self.assertEqual(result["safe_class"], REASON_CATEGORY_API_REFUSAL)

    def test_credentials_and_raw_source_never_persisted_in_failure_artifact(self) -> None:
        scratch = SCRATCH_ROOT / str(uuid.uuid4())
        scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        workspace = scratch / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
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
        rights = {
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "rights_basis": "Operator attested user-authored.",
            "rights_review_required": False,
            "rights_review_status": "not_required",
        }

        def refusing_runner(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("api_key=sk-secret123 and raw source text must never leak")

        result = run_adaptation_authoring(
            context,
            workspace=workspace,
            source_title="The Lantern Catalogue",
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            rights_metadata=rights,
            rights_class=rights["rights_class"],
            rights_basis=rights["rights_basis"],
            rights_review_required=False,
            rights_review_status="not_required",
            author_runner=refusing_runner,
        )
        artifact = load_adaptation_artifact(
            workspace, result["attempt_id"], ARTIFACT_KIND_FAILURE_REPORT
        )
        encoded = json.dumps(artifact, sort_keys=True)
        self.assertNotIn("sk-secret123", encoded)
        self.assertNotIn("api_key=", encoded)
        self.assertNotIn("raw source text", encoded)
        self.assertNotIn(str(REPO_ROOT), encoded)
        self.assertEqual(artifact["payload"]["safe_class"], REASON_CATEGORY_PROVIDER_INFRASTRUCTURE)
        validation = validate_adaptation_artifact(artifact)
        self.assertTrue(validation.get("valid"), validation.get("diagnostics"))

    def test_runtime_modules_stay_provider_free(self) -> None:
        paths = [
            REPO_ROOT / "utils" / "toolkit_adaptation_author.py",
            REPO_ROOT / "utils" / "toolkit_adaptation_authoring.py",
            REPO_ROOT / "utils" / "toolkit_adaptation_artifacts.py",
            REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py",
        ]
        forbidden = (
            "tempfile",
            "socketio",
            "requests.get",
            "urllib.request",
            "start_build",
            "simulate_build_process",
            "web_interface",
        )
        for path in paths:
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(
                    token,
                    source,
                    f"{path.name} must not reference {token}",
                )
            self.assertTrue(source.isascii(), f"{path.name} must stay ASCII")


if __name__ == "__main__":
    unittest.main(verbosity=2)
