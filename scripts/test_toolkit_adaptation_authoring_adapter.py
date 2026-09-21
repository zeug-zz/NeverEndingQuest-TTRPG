# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the shared adaptation authoring adapter
(task 2.3 of toolkit-llm-adaptation-runtime-unification).

The suite locks the Python-owned authoring adapter entry points in
web/extensions/toolkit_adaptation_runtime.py:

  * a ready upload handoff and a ready text-description attempt workspace
    both route through the existing ``run_adaptation_authoring()`` exactly
    once per attempt via an injectable author runner/client seam;
  * Python-owned attempt metadata, source identity/context, rights metadata,
    world-context provenance, and staging/workspace references reach
    authoring, and the returned dossier is Python-parsed/validated and
    persisted atomically through the existing adaptation artifact helpers;
  * authoring failure (refusal, provider failure, invalid response, dossier
    validation failure) returns an explicit blocked result before any
    ModuleBuilder or publication call and leaves no completed module,
    registry, or campaign side effect;
  * a selected adaptation attempt never silently downgrades to legacy;
  * no credentials, raw source, full prompts, or unbounded provider text are
    exposed in results/artifacts.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_authoring_adapter/<uuid>/`` and are removed
deterministically via addCleanup. No OS temp directory is used. The adapter
never invokes ModuleBuilder, never touches modules/, the registry, campaign,
or runtime state.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_adaptation_runtime as runtime
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_SOURCE_CONTEXT,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
)
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
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
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_authoring_adapter"
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
    {"name": "Flooded Stairs", "location": "stairs", "description": "Dark water."},
]


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dossier_for_attempt(attempt_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Build a schema-valid dossier whose Python-owned identity matches the
    attempt metadata produced by the authoring preflight."""
    dossier = deepcopy(_load_fixture())
    dossier["source_hash"] = attempt_metadata["source_hash"]
    dossier["source_title"] = attempt_metadata["source_title"]
    dossier["source_profile"] = attempt_metadata["source_profile"]
    dossier["rights_class"] = attempt_metadata["rights_class"]
    dossier["rights_basis"] = attempt_metadata["rights_basis"]
    dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
    dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
    dossier["adaptation_mode"] = "llm_adaptation"
    return dossier


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        error: Optional[Exception] = None,
        refused: bool = False,
        failure_class: Optional[str] = None,
        ok_result: Optional[Dict[str, Any]] = None,
        invalid_dossier: bool = False,
    ) -> None:
        self.calls: List[tuple] = []
        self.dossier_builder = dossier_builder
        self.error = error
        self.refused = refused
        self.failure_class = failure_class
        self.ok_result = ok_result
        self.invalid_dossier = invalid_dossier

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
        if self.error is not None:
            raise self.error
        if self.ok_result is not None:
            return deepcopy(self.ok_result)
        if self.refused:
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": self.failure_class or "refusal",
                "diagnostics": [
                    {"code": "dossier_refused", "message": "adaptation author refused the source"}
                ],
                "dossier": None,
            }
        if self.invalid_dossier:
            return {
                "status": "success",
                "outcome": "valid",
                "ok": True,
                "failure_class": "none",
                "dossier": {"status": "ready", "adapted_title": "not a real dossier"},
                "diagnostics": [],
            }
        dossier = self.dossier_builder(dict(attempt_metadata or {})) if self.dossier_builder else None
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-adapter-1"},
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


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
        "assumptions": ["Fixture packet for the authoring adapter tests."],
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
        job_id="job-1",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    persist_review_snapshot_artifact(workspace, snapshot)
    return workspace


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def _assert_no_module_side_effects(self) -> None:
        """No completed module, registry, or campaign artifact anywhere."""
        modules_dir = self.scratch / "modules"
        self.assertFalse(modules_dir.exists())
        for sentinel in ("world_registry.json", "campaign.json"):
            self.assertFalse(
                (self.scratch / sentinel).exists(),
                f"{sentinel} must not be created by authoring",
            )
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())


class TestUploadAuthoringAdapter(_ProjectLocalScratchMixin, unittest.TestCase):
    """Approved upload handoffs route through authoring with atomic artifacts."""

    def _ready_handoff(self, **overrides: Any) -> Dict[str, Any]:
        workspace = _make_workspace(self.scratch)
        options: Dict[str, Any] = {
            "source_kind": "markdown",
            "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
            "review_state": "approved_for_build",
            "job_id": "job-1",
        }
        options.update(overrides)
        handoff = runtime.build_upload_adaptation_handoff(workspace, **options)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        return handoff

    def _run(self, handoff: Dict[str, Any], runner: FakeAuthorRunner, **kwargs: Any) -> Dict[str, Any]:
        return runtime.run_upload_adaptation_authoring(
            handoff,
            author_runner=runner,
            model="mock-adaptation-model",
            **kwargs,
        )

    def test_upload_ready_authoring_persists_dossier_atomically(self) -> None:
        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(handoff, runner)

        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertEqual(result["outcome"], runtime.AUTHORING_ADAPTER_OUTCOME_HANDOFF_READY)
        self.assertEqual(result["input_kind"], runtime.INPUT_KIND_UPLOAD_MARKDOWN)
        self.assertIsNotNone(result["dossier"])
        self.assertTrue(result["authoring"]["authoring_attempted"])
        self.assertEqual(result["authoring"]["authoring_status"], "ready")
        self.assertTrue(result["authoring"]["dossier_artifact_persisted"])
        self.assertEqual(len(runner.calls), 1)

        attempt_id = result["attempt"]["attempt_id"]
        workspace = _make_workspace(self.scratch)
        self.assertTrue(
            get_adaptation_artifact_path(workspace, attempt_id, ARTIFACT_KIND_SOURCE_CONTEXT).exists()
        )
        self.assertTrue(
            get_adaptation_artifact_path(
                workspace, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
            ).exists()
        )
        dossier_artifact = load_adaptation_artifact(
            workspace, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)
        self.assertEqual(dossier_artifact["payload"], result["dossier"])
        self.assertEqual(dossier_artifact["provenance"]["source_hash"], FIXTURE_HASH)
        self.assertEqual(dossier_artifact["provenance"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(dossier_artifact["provenance"]["adaptation_mode"], "llm_adaptation")

    def test_upload_attempt_metadata_and_rights_reach_authoring(self) -> None:
        handoff = self._ready_handoff(job_id="job-7")
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)

        _, attempt_metadata, kwargs = runner.calls[0]
        self.assertEqual(attempt_metadata["source_hash"], FIXTURE_HASH)
        self.assertEqual(attempt_metadata["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(attempt_metadata["job_id"], "job-7")
        self.assertEqual(kwargs["model"], "mock-adaptation-model")
        self.assertNotIn("raw_source", kwargs)
        self.assertNotIn("credentials", kwargs)

    def test_upload_authoring_runs_exactly_once_per_attempt(self) -> None:
        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        first = self._run(handoff, runner)
        self.assertEqual(first["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(len(runner.calls), 1)

        replay = self._run(handoff, runner)
        self.assertEqual(replay["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(replay["ok"])
        self.assertTrue(replay["authoring"]["idempotent_replay"])
        self.assertEqual(len(runner.calls), 1)

    def test_upload_author_refusal_blocks_with_failure_artifact(self) -> None:
        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
        result = self._run(handoff, runner)

        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["dossier"])
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertFalse(result["guards"]["module_builder_started"])
        self.assertFalse(result["guards"]["publication_started"])
        self.assertFalse(result["guards"]["registry_mutated"])
        self.assertEqual(result["guards"]["completed_module_artifacts"], [])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        self.assertEqual(len(runner.calls), 1)
        attempt_id = result["attempt"]["attempt_id"]
        self.assertTrue(
            get_adaptation_artifact_path(
                _make_workspace(self.scratch), attempt_id, ARTIFACT_KIND_FAILURE_REPORT
            ).exists()
        )
        self._assert_no_module_side_effects()

    def test_upload_provider_failure_blocks_before_builder(self) -> None:
        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(
            dossier_builder=_dossier_for_attempt, error=RuntimeError("provider unavailable")
        )
        result = self._run(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertFalse(result["guards"]["module_builder_started"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        self.assertIsNone(result["dossier"])
        self._assert_no_module_side_effects()

    def test_upload_invalid_dossier_blocks_with_bounded_diagnostics(self) -> None:
        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(invalid_dossier=True)
        result = self._run(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        codes = [item["code"] for item in result["authoring"]["diagnostics"]]
        self.assertTrue(codes)
        self._assert_no_module_side_effects()

    def test_upload_failed_closed_handoff_blocks_before_authoring(self) -> None:
        handoff = runtime.build_upload_adaptation_handoff(
            _make_workspace(self.scratch),
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="awaiting_review",
            job_id="job-1",
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["authoring"]["authoring_attempted"])
        self.assertEqual(runner.calls, [])
        codes = [item["code"] for item in result["diagnostics"]]
        self.assertIn("upload_not_approved", codes)
        self._assert_no_module_side_effects()

    def test_upload_sentinel_module_and_registry_are_untouched(self) -> None:
        module_dir = self.scratch / "modules" / "Existing_Module"
        module_dir.mkdir(parents=True, exist_ok=True)
        context_path = module_dir / "module_context.json"
        registry_path = self.scratch / "modules" / "world_registry.json"
        campaign_path = self.scratch / "campaign.json"
        context_path.write_text('{"module": "existing"}', encoding="utf-8")
        registry_path.write_text('{"modules": ["Existing_Module"]}', encoding="utf-8")
        campaign_path.write_text('{"active": true}', encoding="utf-8")
        before = {
            path: path.read_bytes() for path in (context_path, registry_path, campaign_path)
        }

        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
        result = self._run(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(
            sorted(str(p.relative_to(self.scratch / "modules")) for p in (self.scratch / "modules").rglob("*") if p.is_file()),
            ["Existing_Module/module_context.json", "world_registry.json"],
        )

    def test_upload_result_never_downgrades_route(self) -> None:
        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
        result = self._run(handoff, runner)
        route = result["route"]
        self.assertEqual(route["selected_route"], "llm_adaptation")
        self.assertIs(route["fallback_allowed"], False)
        self.assertEqual(route["route_authority"], "adaptation_selected_authoritative")
        self.assertIs(route["adaptation_artifacts_required"], True)
        self.assertIs(result["guards"]["selected_route_authoritative"], True)

    def test_upload_uses_handoff_workspace_reference(self) -> None:
        handoff = self._ready_handoff()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(handoff, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        # Artifacts land inside the upload workspace recorded by the handoff.
        attempt_id = result["attempt"]["attempt_id"]
        self.assertTrue(
            get_adaptation_artifact_path(
                _make_workspace(self.scratch), attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
            ).exists()
        )


class TestTextDescriptionAuthoringAdapter(_ProjectLocalScratchMixin, unittest.TestCase):
    """Ready text-description workspaces route through authoring with parity."""

    def _ready_manifest(self, **overrides: Any) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "module_name": "Sunken_Lighthouse",
            "concept": FIXTURE_TEXT,
            "job_id": "text-job-1",
            "workspace_root": "tmp/toolkit_adaptation_authoring_adapter"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
        }
        options.update(overrides)
        manifest = runtime.build_text_description_attempt_workspace(**options)
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        return manifest

    def _run(self, manifest: Dict[str, Any], runner: FakeAuthorRunner, **kwargs: Any) -> Dict[str, Any]:
        return runtime.run_text_description_adaptation_authoring(
            manifest,
            author_runner=runner,
            model="mock-adaptation-model",
            **kwargs,
        )

    def test_text_ready_authoring_persists_dossier_atomically(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(manifest, runner)

        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertTrue(result["ok"])
        self.assertEqual(result["input_kind"], runtime.INPUT_KIND_TEXT_DESCRIPTION)
        self.assertEqual(result["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertIs(result["rights"]["python_owned"], True)
        self.assertIs(result["rights"]["provider_may_change"], False)
        self.assertIsNotNone(result["dossier"])
        self.assertEqual(result["authoring"]["authoring_status"], "ready")
        self.assertEqual(len(runner.calls), 1)

        attempt_id = result["attempt"]["attempt_id"]
        workspace_path = REPO_ROOT.joinpath(*Path(manifest["workspace"]["path"]).parts)
        self.assertTrue(
            get_adaptation_artifact_path(workspace_path, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER).exists()
        )
        dossier_artifact = load_adaptation_artifact(
            workspace_path, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)
        self.assertEqual(dossier_artifact["payload"], result["dossier"])
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_text_author_refusal_blocks_without_direct_module_write(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
        result = self._run(manifest, runner)

        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertFalse(result["guards"]["module_builder_allowed"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_text_invalid_dossier_blocks(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(invalid_dossier=True)
        result = self._run(manifest, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(result["dossier"])
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_text_failed_closed_manifest_blocks_before_authoring(self) -> None:
        manifest = runtime.build_text_description_attempt_workspace(
            "Sunken_Lighthouse",
            "",
            job_id="text-job-1",
            workspace_root="tmp/toolkit_adaptation_authoring_adapter"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
        )
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED)
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(manifest, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertFalse(result["authoring"]["authoring_attempted"])
        self.assertEqual(runner.calls, [])
        codes = [item["code"] for item in result["diagnostics"]]
        self.assertIn("concept_empty", codes)

    def test_text_authoring_exactly_once_and_replay(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        first = self._run(manifest, runner)
        self.assertEqual(first["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(len(runner.calls), 1)

        replay = self._run(manifest, runner)
        self.assertEqual(replay["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertTrue(replay["authoring"]["idempotent_replay"])
        self.assertEqual(len(runner.calls), 1)

    def test_text_staging_target_never_under_modules(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        result = self._run(manifest, runner)
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        staging = manifest["output"]
        self.assertIs(staging["published_to_modules"], False)
        self.assertIs(staging["direct_module_write_required"], False)
        self.assertFalse(staging["staging_target_path"].startswith("modules/"))
        self.assertNotIn("modules/", result["staging"].get("staging_root", ""))


class TestAdapterContractAndHygiene(_ProjectLocalScratchMixin, unittest.TestCase):
    """The adapter result validates, serializes deterministically, and stays safe."""

    def _ready_upload_result(self) -> Dict[str, Any]:
        workspace = _make_workspace(self.scratch)
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="approved_for_build",
            job_id="job-1",
        )
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        return runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )

    def test_ready_result_validates_and_round_trips(self) -> None:
        result = self._ready_upload_result()
        validation = runtime.validate_adaptation_authoring_result(result)
        self.assertTrue(validation["valid"], validation["diagnostics"])
        self.assertEqual(validation["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        parsed = json.loads(runtime.serialize_adaptation_authoring_result(result))
        self.assertEqual(parsed["contract_version"], runtime.AUTHORING_ADAPTER_CONTRACT_VERSION)
        self.assertEqual(parsed["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        # Serialization is deterministic and attempt identity is stable.
        self.assertEqual(
            runtime.serialize_adaptation_authoring_result(result),
            runtime.serialize_adaptation_authoring_result(result),
        )
        from utils.toolkit_adaptation_artifacts import build_attempt_id

        self.assertEqual(
            result["attempt"]["attempt_id"],
            build_attempt_id(FIXTURE_HASH, 1, "job-1"),
        )

    def test_tampered_route_downgrade_rejected(self) -> None:
        result = self._ready_upload_result()
        tampered = dict(result)
        tampered["route"] = dict(result["route"])
        tampered["route"]["fallback_allowed"] = True
        validation = runtime.validate_adaptation_authoring_result(tampered)
        self.assertFalse(validation["valid"])
        self.assertIn("route_fallback_allowed_invalid", validation["diagnostics"])

    def test_tampered_builder_started_rejected(self) -> None:
        result = self._ready_upload_result()
        tampered = dict(result)
        tampered["guards"] = dict(result["guards"])
        tampered["guards"]["module_builder_started"] = True
        validation = runtime.validate_adaptation_authoring_result(tampered)
        self.assertFalse(validation["valid"])
        self.assertIn("module_builder_started_invalid", validation["diagnostics"])

    def test_ready_result_requires_dossier_artifact(self) -> None:
        result = self._ready_upload_result()
        tampered = dict(result)
        tampered["authoring"] = dict(result["authoring"])
        tampered["authoring"]["dossier_artifact_persisted"] = False
        validation = runtime.validate_adaptation_authoring_result(tampered)
        self.assertFalse(validation["valid"])
        self.assertIn("dossier_artifact_not_persisted", validation["diagnostics"])

    def test_blocked_result_with_dossier_rejected(self) -> None:
        workspace = _make_workspace(self.scratch)
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="awaiting_review",
            job_id="job-1",
        )
        blocked = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=FakeAuthorRunner(), model="mock-adaptation-model"
        )
        self.assertEqual(blocked["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertIsNone(blocked["dossier"])
        tampered = dict(blocked)
        tampered["dossier"] = _load_fixture()
        validation = runtime.validate_adaptation_authoring_result(tampered)
        self.assertFalse(validation["valid"])
        self.assertIn("blocked_result_has_dossier", validation["diagnostics"])

    def test_no_credential_or_raw_source_leakage(self) -> None:
        result = self._ready_upload_result()
        encoded = runtime.serialize_adaptation_authoring_result(result)
        lowered = encoded.lower()
        for pattern in ("sk-", "bearer ", "api_key", "authorization", "password", "secret"):
            self.assertNotIn(pattern, lowered)
        for key in ("raw_source", "raw_markdown", "raw_pdf", "full_source", "source_text"):
            self.assertNotIn('"' + key + '"', encoded)
        self.assertNotIn(str(REPO_ROOT), encoded)

    def test_blocked_result_keeps_only_bounded_diagnostics(self) -> None:
        workspace = _make_workspace(self.scratch)
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="approved_for_build",
            job_id="job-1",
        )
        runner = FakeAuthorRunner(refused=True)
        blocked = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        for item in blocked["authoring"]["diagnostics"]:
            self.assertLessEqual(len(item.get("message", "")), 320)
        self.assertLessEqual(len(blocked["authoring"]["diagnostics"]), 12)
        validation = runtime.validate_adaptation_authoring_result(blocked)
        self.assertTrue(validation["valid"], validation["diagnostics"])

    def test_runtime_module_has_no_builder_or_provider_imports(self) -> None:
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        # No ModuleBuilder import, instantiation, or invocation is allowed; the
        # adapter only routes to the completed authoring contract. Prose
        # references to "ModuleBuilder" in docstrings are permitted, so the
        # scan targets call/import shapes and host lifecycle tokens.
        for token in (
            "from core.generators.module_builder",
            "import module_builder",
            "ModuleBuilder(",
            "module_builder.build_module",
            "module_builder.run",
            "simulate_build_process",
            "start_build",
            "web_interface",
            "world_registry.json",
            "campaign.json",
            "tempfile",
            "/tmp",
            "socketio",
            "requests.",
            "urllib",
            "from openai",
            "import openai",
            "http.client",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_ascii_only_source(self) -> None:
        for path in (RUNTIME_MODULE_PATH, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            non_ascii = [char for char in text if ord(char) > 127]
            self.assertEqual(non_ascii, [], f"non-ASCII characters in {path}")

    def test_public_api_exported(self) -> None:
        for name in (
            "AUTHORING_ADAPTER_CONTRACT_VERSION",
            "AUTHORING_ADAPTER_STATUS_READY",
            "AUTHORING_ADAPTER_STATUS_BLOCKED",
            "AUTHORING_ADAPTER_OUTCOME_HANDOFF_READY",
            "AUTHORING_ADAPTER_OUTCOME_BLOCKED",
            "MAX_ADAPTER_RESULT_SERIALIZED_CHARS",
            "run_upload_adaptation_authoring",
            "run_text_description_adaptation_authoring",
            "serialize_adaptation_authoring_result",
            "validate_adaptation_authoring_result",
            "author_upload_adaptation",
            "author_text_description_adaptation",
        ):
            self.assertIn(name, runtime.__all__)

    def test_aliases_discoverable(self) -> None:
        self.assertIs(runtime.author_upload_adaptation, runtime.run_upload_adaptation_authoring)
        self.assertIs(runtime.run_upload_authoring, runtime.run_upload_adaptation_authoring)
        self.assertIs(
            runtime.author_text_description_adaptation,
            runtime.run_text_description_adaptation_authoring,
        )
        self.assertIs(runtime.run_text_authoring, runtime.run_text_description_adaptation_authoring)


if __name__ == "__main__":
    unittest.main()
