# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free rights-contract tests for the shared adaptation runtime
(task 2.4 of toolkit-llm-adaptation-runtime-unification).

The suite locks the Python-owned rights contract across the runtime
adapters in web/extensions/toolkit_adaptation_runtime.py:

  * text descriptions default to Python-owned ``user_authored`` rights with a
    non-pending/non-required review state and an explicit Python basis;
  * upload handoffs retain the supplied ``user_authored``,
    ``licensed_or_project_owned``, or restricted rights class and review state
    exactly (subject only to documented normalization/validation);
  * restricted or review-pending uploads remain review-gated: an injected
    provider/dossier saying different rights fields can never make them
    build-ready;
  * provider rights override/contradiction produces bounded
    failure/refusal/blocked diagnostics and never mutates Python-owned rights
    or silently downgrades to legacy;
  * final dossier identity preservation: a ready adapter result and its
    persisted dossier artifact carry exactly the Python-owned rights fields.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_rights_contract/<uuid>/`` and are removed
deterministically via addCleanup. No OS temp directory is used, no provider or
network call is made, and no modules/, registry, campaign, or runtime state is
touched.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_adaptation_runtime as runtime
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_FAILURE_REPORT,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
)
from utils.toolkit_adaptation_dossier import (
    RIGHTS_CLASS_LICENSED,
    RIGHTS_CLASS_RESTRICTED,
    RIGHTS_CLASS_USER_AUTHORED,
    RIGHTS_REVIEW_APPROVED,
    RIGHTS_REVIEW_NOT_REQUIRED,
    RIGHTS_REVIEW_PENDING,
    RIGHTS_REVIEW_REJECTED,
)
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    SOURCE_RIGHTS_LICENSED,
    SOURCE_RIGHTS_RESTRICTED,
    SOURCE_RIGHTS_USER_AUTHORED,
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
    persist_normalized_packet_artifact,
    persist_review_snapshot_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_rights_contract"
RUNTIME_MODULE_PATH = (
    REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py"
)
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

PACKET_LOCATIONS = [
    {"name": "Keeper's Quarters", "location": "tower", "description": "Rusted spyglass."},
]

# The four Python-owned rights fields that a ready dossier must echo exactly.
RIGHTS_IDENTITY_FIELDS = (
    "rights_class",
    "rights_basis",
    "rights_review_required",
    "rights_review_status",
)


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dossier_for_attempt(
    attempt_metadata: Dict[str, Any],
    *,
    rights_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a schema-valid dossier whose Python-owned identity matches the
    attempt metadata, with an optional rights relabel for provider-misbehavior
    tests."""
    dossier = deepcopy(_load_fixture())
    dossier["source_hash"] = attempt_metadata["source_hash"]
    dossier["source_title"] = attempt_metadata["source_title"]
    dossier["source_profile"] = attempt_metadata["source_profile"]
    dossier["rights_class"] = attempt_metadata["rights_class"]
    dossier["rights_basis"] = attempt_metadata["rights_basis"]
    dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
    dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
    dossier["adaptation_mode"] = "llm_adaptation"
    if rights_override:
        dossier.update(deepcopy(rights_override))
    return dossier


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        refused: bool = False,
    ) -> None:
        self.calls: List[tuple] = []
        self.dossier_builder = dossier_builder
        self.refused = refused

    def __call__(
        self, source_context: Any, attempt_metadata: Optional[Dict[str, Any]] = None, **kwargs: Any
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
        dossier = self.dossier_builder(dict(attempt_metadata or {})) if self.dossier_builder else None
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-rights-1"},
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


def _packet(*, source_hash: str = FIXTURE_HASH, rights: str = SOURCE_RIGHTS_USER_AUTHORED) -> Dict[str, Any]:
    return {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_path": "uploads/fixture.md",
        "source_hash": source_hash,
        "title": "Sunken Lighthouse",
        "author": "",
        "description": "A bounded adventure about a sunken lighthouse.",
        "adventure_summary": "The keeper's quarters and the flooded stairs.",
        "module_tone": "haunted",
        "acts": [{"name": "Descent", "summary": "Into the dark."}],
        "locations": PACKET_LOCATIONS,
        "npc_seeds": [],
        "encounter_seeds": [],
        "assumptions": ["Fixture packet for the rights contract tests."],
        "source_rights_class": rights,
    }


def _make_workspace(scratch: Path, *, rights: str = SOURCE_RIGHTS_USER_AUTHORED) -> Path:
    workspace = scratch / "workspace"
    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
    files["source_original"].write_text(FIXTURE_TEXT, encoding="utf-8")
    packet = _packet(rights=rights)
    persist_normalized_packet_artifact(workspace, packet)
    snapshot = build_review_snapshot(
        job_id="job-1",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=rights,
    )
    persist_review_snapshot_artifact(workspace, snapshot)
    return workspace


def _handoff(workspace: Path, *, rights: str, **overrides: Any) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "source_kind": "markdown",
        "source_rights_class": rights,
        "review_state": "approved_for_build",
        "job_id": "job-1",
    }
    options.update(overrides)
    return runtime.build_upload_adaptation_handoff(workspace, **options)


def _diagnostic_codes(payload: Any) -> List[str]:
    result: List[str] = []
    items = payload.get("diagnostics") if isinstance(payload, Mapping) else payload
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping):
                result.append(str(item.get("code") or ""))
            elif item is not None:
                result.append(str(item))
    return [code for code in result if code]


def _all_diagnostic_codes(result: Dict[str, Any]) -> List[str]:
    return (
        _diagnostic_codes(result)
        + _diagnostic_codes(result.get("authoring"))
        + _diagnostic_codes(result.get("envelope"))
    )


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def _assert_no_module_side_effects(self) -> None:
        modules_dir = self.scratch / "modules"
        self.assertFalse(modules_dir.exists())
        for sentinel in ("world_registry.json", "campaign.json"):
            self.assertFalse((self.scratch / sentinel).exists())
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def _assert_rights_preserved(self, result: Dict[str, Any], expected: Dict[str, Any]) -> None:
        rights = result.get("rights")
        self.assertIsInstance(rights, dict)
        for field in RIGHTS_IDENTITY_FIELDS:
            self.assertEqual(rights.get(field), expected.get(field), field)
        self.assertIs(rights.get("python_owned"), True)
        self.assertIs(rights.get("provider_may_change"), False)


class TestTextDescriptionRightsContract(_ProjectLocalScratchMixin, unittest.TestCase):
    """Text descriptions default to Python-owned user_authored rights."""

    def _ready_manifest(self, **overrides: Any) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "module_name": "Sunken_Lighthouse",
            "concept": FIXTURE_TEXT,
            "job_id": "text-job-1",
            "workspace_root": "tmp/toolkit_adaptation_rights_contract"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
        }
        options.update(overrides)
        manifest = runtime.build_text_description_attempt_workspace(**options)
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        return manifest

    def _run(self, manifest: Dict[str, Any], runner: FakeAuthorRunner) -> Dict[str, Any]:
        return runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=runner, model="mock-adaptation-model"
        )

    def test_text_default_rights_are_python_owned_user_authored(self) -> None:
        manifest = self._ready_manifest()
        rights = manifest["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(rights["rights_basis"], runtime.TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS)
        self.assertIs(rights["rights_review_required"], False)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_NOT_REQUIRED)
        self.assertIs(rights["python_owned"], True)
        self.assertEqual(rights["classified_by"], runtime.TEXT_DESCRIPTION_CLASSIFIED_BY)
        self.assertIs(rights["provider_may_change"], False)

        envelope_rights = manifest["envelope"]["rights"]
        self.assertEqual(envelope_rights["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertIs(envelope_rights["rights_review_required"], False)
        self.assertEqual(envelope_rights["rights_review_status"], RIGHTS_REVIEW_NOT_REQUIRED)
        self.assertEqual(
            manifest["packet_metadata"]["source_rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        self.assertEqual(
            manifest["packet_metadata"]["classified_by"], runtime.TEXT_DESCRIPTION_CLASSIFIED_BY
        )

    def test_text_authoring_request_carries_python_owned_rights(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(manifest, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)

        _, attempt_metadata, kwargs = runner.calls[0]
        self.assertEqual(attempt_metadata["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(attempt_metadata["rights_basis"], runtime.TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS)
        self.assertIs(attempt_metadata["rights_review_required"], False)
        self.assertEqual(attempt_metadata["rights_review_status"], RIGHTS_REVIEW_NOT_REQUIRED)
        self.assertNotIn("raw_source", kwargs)
        self.assertNotIn("credentials", kwargs)

    def test_text_ready_dossier_preserves_python_rights_identity(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(manifest, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self._assert_rights_preserved(result, manifest["rights"])
        for field in RIGHTS_IDENTITY_FIELDS:
            self.assertEqual(result["dossier"].get(field), manifest["rights"].get(field), field)

    def test_text_provider_metadata_override_fails_closed(self) -> None:
        manifest = runtime.build_text_description_attempt_workspace(
            "Sunken_Lighthouse",
            FIXTURE_TEXT,
            job_id="text-job-1",
            workspace_root="tmp/toolkit_adaptation_rights_contract"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
            provider_metadata={
                "rights_class": RIGHTS_CLASS_RESTRICTED,
                "rights_basis": "provider relabel attempt",
                "rights_review_required": True,
                "rights_review_status": RIGHTS_REVIEW_PENDING,
            },
        )
        self.assertEqual(
            manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED
        )
        self.assertIsNone(manifest["envelope"])
        codes = _diagnostic_codes(manifest)
        self.assertIn("provider_rights_override_rejected", codes)

    def test_text_provider_dossier_relabel_blocked(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(
            dossier_builder=lambda metadata: _dossier_for_attempt(
                metadata,
                rights_override={
                    "rights_class": RIGHTS_CLASS_LICENSED,
                    "rights_basis": "provider relabel attempt",
                },
            )
        )
        result = self._run(manifest, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertFalse(result["guards"]["module_builder_started"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        codes = _all_diagnostic_codes(result)
        self.assertIn("invalid_provenance", codes)
        self._assert_no_module_side_effects()

    def test_text_provider_dossier_restricted_relabel_blocked(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(
            dossier_builder=lambda metadata: _dossier_for_attempt(
                metadata,
                rights_override={
                    "rights_class": RIGHTS_CLASS_RESTRICTED,
                    "rights_review_required": True,
                    "rights_review_status": RIGHTS_REVIEW_PENDING,
                },
            )
        )
        result = self._run(manifest, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        codes = _all_diagnostic_codes(result)
        self.assertIn("invalid_provenance", codes)
        self._assert_no_module_side_effects()

    def test_text_rights_basis_is_exact_user_submitted_text_description(self) -> None:
        # The Python-owned text-description basis is the exact canonical token,
        # not a prose explanation and not any other constant.
        self.assertEqual(
            runtime.TEXT_DESCRIPTION_DEFAULT_RIGHTS_BASIS,
            "user_submitted_text_description",
        )
        manifest = self._ready_manifest()
        self.assertEqual(
            manifest["rights"]["rights_basis"], "user_submitted_text_description"
        )
        self.assertEqual(
            manifest["envelope"]["rights"]["rights_basis"],
            "user_submitted_text_description",
        )

    def test_text_provider_dossier_rights_basis_paraphrase_blocked(self) -> None:
        # A provider dossier that replaces the Python-owned canonical token
        # with prose is rejected as a rights/provenance mismatch on
        # rights_basis: all other identity fields match, only rights_basis
        # differs, so the bounded reason is rights_or_provenance_mismatch.
        manifest = self._ready_manifest()
        provided: Dict[str, Any] = {}

        def _paraphrasing_builder(metadata: Dict[str, Any]) -> Dict[str, Any]:
            dossier = _dossier_for_attempt(
                metadata,
                rights_override={
                    "rights_basis": "The user submitted this text description themselves."
                },
            )
            provided["dossier"] = dossier
            return dossier

        runner = FakeAuthorRunner(dossier_builder=_paraphrasing_builder)
        result = self._run(manifest, runner)

        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertFalse(result["guards"]["module_builder_started"])
        self.assertFalse(result["guards"]["publication_started"])
        self.assertFalse(result["guards"]["registry_mutated"])
        self.assertEqual(
            result["authoring"]["reason_code"], "rights_or_provenance_mismatch"
        )
        self.assertEqual(result["authoring"]["safe_class"], "rights_or_provenance")
        # The mismatch never consumes the semantic revision budget; the
        # provider-retry flag at the authoring boundary is out of scope here.
        self.assertFalse(result["authoring"]["revision_eligible"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        # The provider dossier itself was the only thing paraphrased; every
        # other Python-owned identity field still matched the manifest.
        dossier = provided.get("dossier") or {}
        self.assertEqual(
            dossier.get("rights_basis"), "The user submitted this text description themselves."
        )
        self.assertNotEqual(
            dossier.get("rights_basis"), manifest["rights"]["rights_basis"]
        )
        self.assertEqual(
            dossier.get("rights_class"), manifest["rights"]["rights_class"]
        )
        self.assertEqual(
            dossier.get("rights_review_status"),
            manifest["rights"]["rights_review_status"],
        )
        self._assert_no_module_side_effects()


class TestUploadRightsPreservation(_ProjectLocalScratchMixin, unittest.TestCase):
    """Each supplied upload rights class and review state is retained exactly."""

    def test_user_authored_upload_preserved(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_USER_AUTHORED)
        handoff = _handoff(workspace, rights=SOURCE_RIGHTS_USER_AUTHORED)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        rights = handoff["envelope"]["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(rights["rights_basis"], "user_authored_uploaded_adventure")
        self.assertIs(rights["rights_review_required"], False)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_NOT_REQUIRED)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_licensed_upload_preserved(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_LICENSED)
        handoff = _handoff(workspace, rights=SOURCE_RIGHTS_LICENSED)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        rights = handoff["envelope"]["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_LICENSED)
        self.assertEqual(rights["rights_basis"], "licensed_or_project_owned_upload")
        self.assertIs(rights["rights_review_required"], False)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_NOT_REQUIRED)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_restricted_upload_defaults_to_pending_review(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_RESTRICTED)
        handoff = _handoff(workspace, rights=SOURCE_RIGHTS_RESTRICTED)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        rights = handoff["envelope"]["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_RESTRICTED)
        self.assertEqual(rights["rights_basis"], "third_party_copyright_restricted_upload")
        self.assertIs(rights["rights_review_required"], True)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_PENDING)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_restricted_upload_explicit_approved_review_preserved(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_RESTRICTED)
        handoff = _handoff(
            workspace,
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_APPROVED,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        rights = handoff["envelope"]["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_RESTRICTED)
        self.assertIs(rights["rights_review_required"], True)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_APPROVED)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_restricted_upload_explicit_rejected_review_preserved(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_RESTRICTED)
        handoff = _handoff(
            workspace,
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_REJECTED,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        rights = handoff["envelope"]["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_RESTRICTED)
        self.assertIs(rights["rights_review_required"], True)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_REJECTED)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_supplied_review_state_preserved_exactly(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_LICENSED)
        handoff = _handoff(
            workspace,
            rights=SOURCE_RIGHTS_LICENSED,
            rights_review_required=True,
            rights_review_status=RIGHTS_REVIEW_APPROVED,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        rights = handoff["envelope"]["rights"]
        self.assertEqual(rights["rights_class"], RIGHTS_CLASS_LICENSED)
        self.assertIs(rights["rights_review_required"], True)
        self.assertEqual(rights["rights_review_status"], RIGHTS_REVIEW_APPROVED)
        self.assertTrue(handoff["upload_evidence"]["source_rights_preserved"])

    def test_upload_rights_contradiction_fails_closed(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_RESTRICTED)
        handoff = _handoff(
            workspace,
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_required=False,
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        self.assertIsNone(handoff["envelope"])
        codes = _diagnostic_codes(handoff)
        self.assertIn("rights_review_contradiction", codes)


class TestProviderRelabelAndReviewGating(_ProjectLocalScratchMixin, unittest.TestCase):
    """Provider/dossier output can never relabel Python-owned rights or make a
    review-gated upload build-ready."""

    def _ready_handoff(self, *, rights: str, **overrides: Any) -> Dict[str, Any]:
        workspace = _make_workspace(self.scratch, rights=rights)
        handoff = _handoff(workspace, rights=rights, **overrides)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        return handoff

    def _run_upload(self, handoff: Dict[str, Any], runner: FakeAuthorRunner) -> Dict[str, Any]:
        return runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )

    def test_upload_provider_metadata_override_rejected(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_USER_AUTHORED)
        handoff = _handoff(
            workspace,
            rights=SOURCE_RIGHTS_USER_AUTHORED,
            provider_metadata={
                "rights_class": RIGHTS_CLASS_RESTRICTED,
                "rights_basis": "provider relabel attempt",
                "rights_review_required": True,
                "rights_review_status": RIGHTS_REVIEW_PENDING,
            },
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        self.assertIsNone(handoff["envelope"])
        codes = _diagnostic_codes(handoff)
        self.assertIn("provider_rights_override_rejected", codes)

    def test_upload_provider_metadata_echo_allowed(self) -> None:
        workspace = _make_workspace(self.scratch, rights=SOURCE_RIGHTS_USER_AUTHORED)
        handoff = _handoff(
            workspace,
            rights=SOURCE_RIGHTS_USER_AUTHORED,
            provider_metadata={
                "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                "rights_basis": "user_authored_uploaded_adventure",
                "rights_review_required": False,
                "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
            },
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        self.assertEqual(
            handoff["envelope"]["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        codes = _diagnostic_codes(handoff)
        self.assertNotIn("provider_rights_override_rejected", codes)

    def test_restricted_pending_upload_cannot_become_build_ready(self) -> None:
        handoff = self._ready_handoff(
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_PENDING,
        )
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run_upload(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertFalse(result["guards"]["module_builder_started"])
        codes = _all_diagnostic_codes(result)
        self.assertIn("dossier_not_build_ready", codes)
        self._assert_no_module_side_effects()

    def test_restricted_pending_upload_relabel_to_user_authored_blocked(self) -> None:
        handoff = self._ready_handoff(
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_PENDING,
        )
        runner = FakeAuthorRunner(
            dossier_builder=lambda metadata: _dossier_for_attempt(
                metadata,
                rights_override={
                    "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                    "rights_basis": "provider relabel attempt",
                    "rights_review_required": False,
                    "rights_review_status": RIGHTS_REVIEW_NOT_REQUIRED,
                },
            )
        )
        result = self._run_upload(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        codes = _all_diagnostic_codes(result)
        self.assertIn("invalid_provenance", codes)
        self._assert_no_module_side_effects()

    def test_restricted_rejected_upload_cannot_become_build_ready(self) -> None:
        handoff = self._ready_handoff(
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_REJECTED,
        )
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run_upload(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        # A rejected-review dossier is never build-ready; the echo is blocked
        # with bounded diagnostics rather than invalid_provenance.
        codes = _all_diagnostic_codes(result)
        self.assertIn("dossier_not_build_ready", codes)
        self._assert_no_module_side_effects()

    def test_restricted_approved_upload_ready_dossier_echoes_review(self) -> None:
        handoff = self._ready_handoff(
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_APPROVED,
        )
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run_upload(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertTrue(result["ok"])
        self._assert_rights_preserved(result, handoff["envelope"]["rights"])
        for field in RIGHTS_IDENTITY_FIELDS:
            self.assertEqual(result["dossier"].get(field), handoff["envelope"]["rights"].get(field), field)

    def test_restricted_approved_upload_review_downgrade_blocked(self) -> None:
        handoff = self._ready_handoff(
            rights=SOURCE_RIGHTS_RESTRICTED,
            rights_review_status=RIGHTS_REVIEW_APPROVED,
        )
        runner = FakeAuthorRunner(
            dossier_builder=lambda metadata: _dossier_for_attempt(
                metadata,
                rights_override={"rights_review_status": RIGHTS_REVIEW_PENDING},
            )
        )
        result = self._run_upload(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        # A pending-review dossier is never build-ready; the review downgrade
        # is blocked with bounded diagnostics rather than invalid_provenance.
        codes = _all_diagnostic_codes(result)
        self.assertIn("dossier_not_build_ready", codes)
        self._assert_no_module_side_effects()

    def test_licensed_upload_provider_relabel_blocked(self) -> None:
        handoff = self._ready_handoff(rights=SOURCE_RIGHTS_LICENSED)
        runner = FakeAuthorRunner(
            dossier_builder=lambda metadata: _dossier_for_attempt(
                metadata,
                rights_override={
                    "rights_class": RIGHTS_CLASS_RESTRICTED,
                    "rights_review_required": True,
                    "rights_review_status": RIGHTS_REVIEW_PENDING,
                },
            )
        )
        result = self._run_upload(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        codes = _all_diagnostic_codes(result)
        self.assertIn("invalid_provenance", codes)
        self._assert_no_module_side_effects()


class TestFinalDossierIdentityPreservation(_ProjectLocalScratchMixin, unittest.TestCase):
    """A ready result and its persisted dossier artifact keep the Python rights
    identity exactly; the adapter contract validator enforces it."""

    def _ready_upload_result(self, *, rights: str = SOURCE_RIGHTS_USER_AUTHORED) -> Dict[str, Any]:
        workspace = _make_workspace(self.scratch, rights=rights)
        handoff = _handoff(workspace, rights=rights)
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        return result

    def test_ready_result_validates_with_rights_identity(self) -> None:
        result = self._ready_upload_result()
        validation = runtime.validate_adaptation_authoring_result(result)
        self.assertTrue(validation["valid"], validation["diagnostics"])
        self.assertEqual(validation["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)

    def test_validator_rejects_relabeled_dossier_rights(self) -> None:
        result = self._ready_upload_result()
        tampered = deepcopy(result)
        tampered["dossier"] = deepcopy(result["dossier"])
        tampered["dossier"]["rights_class"] = RIGHTS_CLASS_RESTRICTED
        tampered["dossier"]["rights_basis"] = "provider relabel attempt"
        tampered["dossier"]["rights_review_required"] = True
        tampered["dossier"]["rights_review_status"] = RIGHTS_REVIEW_PENDING
        validation = runtime.validate_adaptation_authoring_result(tampered)
        self.assertFalse(validation["valid"])
        self.assertIn("dossier_rights_identity_mismatch", validation["diagnostics"])
        self.assertIn("dossier_not_build_ready", validation["diagnostics"])

    def test_validator_rejects_review_downgrade_in_dossier(self) -> None:
        result = self._ready_upload_result()
        tampered = deepcopy(result)
        tampered["dossier"] = deepcopy(result["dossier"])
        tampered["dossier"]["rights_review_status"] = RIGHTS_REVIEW_PENDING
        validation = runtime.validate_adaptation_authoring_result(tampered)
        self.assertFalse(validation["valid"])
        self.assertIn("dossier_rights_identity_mismatch", validation["diagnostics"])

    def test_persisted_dossier_artifact_keeps_rights_identity(self) -> None:
        result = self._ready_upload_result()
        workspace = self.scratch / "workspace"
        attempt_id = result["attempt"]["attempt_id"]
        dossier_artifact = load_adaptation_artifact(
            workspace, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)
        for field in RIGHTS_IDENTITY_FIELDS:
            self.assertEqual(
                dossier_artifact["payload"].get(field), result["rights"].get(field), field
            )
            self.assertEqual(
                dossier_artifact["provenance"].get(field), result["rights"].get(field), field
            )
        self.assertEqual(
            dossier_artifact["provenance"]["adaptation_mode"], "llm_adaptation"
        )

    def test_text_persisted_dossier_artifact_keeps_rights_identity(self) -> None:
        manifest = runtime.build_text_description_attempt_workspace(
            "Sunken_Lighthouse",
            FIXTURE_TEXT,
            job_id="text-job-1",
            workspace_root="tmp/toolkit_adaptation_rights_contract"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
        )
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        workspace_path = REPO_ROOT.joinpath(*Path(manifest["workspace"]["path"]).parts)
        dossier_artifact = load_adaptation_artifact(
            workspace_path, result["attempt"]["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)
        for field in RIGHTS_IDENTITY_FIELDS:
            self.assertEqual(
                dossier_artifact["payload"].get(field), manifest["rights"].get(field), field
            )
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_failure_artifact_path_recorded_for_relabel_block(self) -> None:
        handoff = self._ready_handoff(rights=SOURCE_RIGHTS_LICENSED)
        runner = FakeAuthorRunner(
            dossier_builder=lambda metadata: _dossier_for_attempt(
                metadata,
                rights_override={"rights_class": RIGHTS_CLASS_RESTRICTED},
            )
        )
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        attempt_id = result["attempt"]["attempt_id"]
        self.assertTrue(
            get_adaptation_artifact_path(
                self.scratch / "workspace", attempt_id, ARTIFACT_KIND_FAILURE_REPORT
            ).exists()
        )

    def _ready_handoff(self, *, rights: str, **overrides: Any) -> Dict[str, Any]:
        workspace = _make_workspace(self.scratch, rights=rights)
        handoff = _handoff(workspace, rights=rights, **overrides)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        return handoff


class TestRightsContractHygiene(_ProjectLocalScratchMixin, unittest.TestCase):
    """Provider-free, path-safe, ASCII-only source hygiene."""

    def test_no_provider_or_network_tripwires(self) -> None:
        # The runtime module must never import or invoke provider, host, or
        # network surfaces. The test file itself legitimately lists these
        # tokens inside this self-scan, so only the module is scanned.
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        for token in (
            "tempfile",
            "/tmp",
            "socketio",
            "requests.",
            "urllib",
            "from openai",
            "import openai",
            "http.client",
            "run_web",
            "web_interface",
            "world_registry.json",
            "campaign.json",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_ascii_only_source(self) -> None:
        for path in (RUNTIME_MODULE_PATH, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            non_ascii = [char for char in text if ord(char) > 127]
            self.assertEqual(non_ascii, [], f"non-ASCII characters in {path}")

    def test_spdx_header_present(self) -> None:
        header = Path(__file__).read_text(encoding="utf-8")[:120]
        self.assertIn("SPDX-FileCopyrightText", header)
        self.assertIn("SPDX-License-Identifier", header)


if __name__ == "__main__":
    unittest.main()
