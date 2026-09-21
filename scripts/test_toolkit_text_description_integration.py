# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free text-description adaptation integration suite
(task 5.5 of toolkit-llm-adaptation-runtime-unification).

This suite exercises the REAL text-description worker, seam, and publication
boundaries as one chain, with deterministic injected author/build/finisher/
reporting seams only at the provider and module-write boundaries:

  * successful adaptation handoff through the real seam and verified
    completion through the real staged publication transaction;
  * author-policy refusal, API-level refusal, invalid dossier, and
    non-build-ready dossier all terminate as explicit blocked adaptation
    outcomes before any staging reservation or ModuleBuilder work;
  * readiness/gate failure and publication/finisher failure (including
    rollback facts) terminate as blocked outcomes with bounded diagnostics
    and never report completion;
  * the REAL host worker ``simulate_build_process`` runs the same real
    seam/publication chain and emits exactly one adaptation-marked
    ``module_complete`` only after the verified publication transaction;
    every enabled failure emits only the bounded adaptation ``module_error``
    and never constructs the legacy direct ModuleBuilder;
  * byte-protected sentinels for the real ``modules/`` tree,
    ``modules/world_registry.json``, and ``modules/campaign.json`` are
    checked before and after every behavioral test, proving no direct module,
    registry, or campaign mutation;
  * source hash, attempt/job/revision identity, Python-owned rights,
    world-context provenance, dossier/proposal/workspace/staging references,
    and bounded failure diagnostics stay coherent across the transitions.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_text_description_integration/<uuid>/`` and are removed
deterministically via addCleanup. The live operator flag is NEVER relied on:
every behavioral test explicitly patches ``model_config.ENABLE_LLM_ADAPTATION``
to exactly True. No OS-temporary scratch, no provider/network imports or calls.
"""

import hashlib
import json
import shutil
import sys
import types
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.extensions.toolkit_text_adaptation_worker as worker
import web.web_interface as web_interface
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    load_adaptation_artifact,
)
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_adaptation_proposals import get_adaptation_proposal_path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_text_description_integration"
WEB_INTERFACE_PATH = REPO_ROOT / "web" / "web_interface.py"
REGISTRY_PATH = REPO_ROOT / "modules" / "world_registry.json"
CAMPAIGN_PATH = REPO_ROOT / "modules" / "campaign.json"
MODULES_DIR = REPO_ROOT / "modules"
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()
MODULE_NAME = "Sunken_Lighthouse"
JOB_ID = "text-integration-job-0001"


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


def _params(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "module_name": MODULE_NAME,
        "narrative": FIXTURE_TEXT,
        "num_areas": 5,
        "locations_per_area": 3,
    }
    base.update(overrides)
    return base


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        error: Optional[Exception] = None,
        refused: bool = False,
        api_refusal: bool = False,
        invalid_dossier: bool = False,
        non_build_ready: bool = False,
    ) -> None:
        self.calls: list = []
        self.dossier_builder = dossier_builder
        self.error = error
        self.refused = refused
        self.api_refusal = api_refusal
        self.invalid_dossier = invalid_dossier
        self.non_build_ready = non_build_ready

    def __call__(
        self,
        source_context: Any,
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append((deepcopy(dict(attempt_metadata or {})), dict(kwargs)))
        if self.error is not None:
            raise self.error
        if self.api_refusal:
            # API-level refusal channel (distinct from author-policy refusal).
            return {
                "status": "refused",
                "outcome": "provider_refusal",
                "ok": False,
                "failure_class": "refusal",
                "safe_class": "api_refusal",
                "reason_code": "provider_api_refusal",
                "diagnostics": [
                    {
                        "code": "provider_api_refusal",
                        "message": "the provider refused the adaptation request",
                    }
                ],
                "dossier": None,
            }
        if self.refused:
            # Author-policy refusal channel.
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": "refusal",
                "diagnostics": [
                    {
                        "code": "dossier_refused",
                        "message": "adaptation author refused the source",
                    }
                ],
                "dossier": None,
            }
        dossier = (
            self.dossier_builder(dict(attempt_metadata or {}))
            if self.dossier_builder
            else None
        )
        if self.invalid_dossier:
            # Schema-invalid dossier (not a dossier at all).
            return {
                "status": "success",
                "outcome": "valid",
                "ok": True,
                "failure_class": "none",
                "dossier": {"status": "ready", "adapted_title": "not a real dossier"},
                "diagnostics": [],
            }
        if self.non_build_ready:
            # Schema-valid but non-build-ready dossier (status=failed).
            broken = deepcopy(dossier)
            broken["status"] = "failed"
            return {
                "status": "success",
                "outcome": "valid",
                "ok": True,
                "failure_class": "none",
                "dossier": broken,
                "diagnostics": [],
            }
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-integration-1"},
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


class _FakeBuildRunner:
    """Deterministic packet-builder fake recording kwargs."""

    def __init__(
        self,
        result: Any,
        error: Optional[Exception] = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list = []

    def __call__(self, workspace: Path, job_id: str, **kwargs: Any) -> Any:
        self.calls.append((str(workspace), job_id, deepcopy(kwargs)))
        if self.error is not None:
            raise self.error
        if callable(self.result):
            return deepcopy(self.result(workspace, job_id, kwargs))
        return deepcopy(self.result)


class _FakeFinisherRunner:
    """Deterministic adaptation-finisher fake recording kwargs."""

    def __init__(self, result: Any, error: Optional[Exception] = None) -> None:
        self.result = result
        self.error = error
        self.calls: list = []

    def __call__(self, module_slug: str, **kwargs: Any) -> Any:
        self.calls.append((module_slug, deepcopy(kwargs)))
        if self.error is not None:
            raise self.error
        if callable(self.result):
            return deepcopy(self.result(module_slug, kwargs))
        return deepcopy(self.result)


class _ProgressRecorder:
    def __init__(self) -> None:
        self.phases: list = []

    def __call__(self, phase: str, message: str) -> bool:
        self.phases.append(str(phase))
        return True


def _success_build_result(
    staging_target: Dict[str, Any], workspace_path: str
) -> Dict[str, Any]:
    return {
        "status": "success",
        "stage": "build_completed",
        "job_id": JOB_ID,
        "module_name": MODULE_NAME,
        "adaptation_mode": "llm_adaptation",
        "build_mode": "llm_adaptation",
        "adaptation_gates": {
            "status": "pass",
            "playable_status": "pass",
            "python_authoritative": True,
            "gates": {
                "schema": {"status": "pass", "effective_status": "pass"},
                "readiness": {"status": "pass", "effective_status": "pass"},
                "mechanical_closure": {"status": "pass", "effective_status": "pass"},
                "semantic_authority": {"status": "pass", "effective_status": "pass"},
                "semantic_probes": {"status": "pass", "effective_status": "pass"},
                "report_agreement": {"status": "pass", "effective_status": "pass"},
            },
        },
        "staging_target": dict(staging_target),
        "output_directory": str(staging_target.get("path") or ""),
        "adaptation_provenance": {
            "attempt_metadata": {
                "attempt_id": staging_target.get("attempt_id"),
                "attempt_number": 1,
                "revision_number": 0,
                "job_id": JOB_ID,
            },
            "source_hash": FIXTURE_HASH,
            "source_title": MODULE_NAME,
            "source_format": "text_description",
        },
        "adaptation_artifact_workspace": workspace_path,
    }


def _blocked_gate_build_result() -> Dict[str, Any]:
    return {
        "status": "blocked",
        "stage": "adaptation_gates",
        "error": "readiness_gate_blocked",
        "adaptation_gates": {
            "status": "blocked",
            "playable_status": "blocked",
            "gates": {
                "readiness": {"status": "blocked", "effective_status": "blocked"}
            },
        },
    }


def _success_finisher_report() -> Dict[str, Any]:
    return {
        "status": "success",
        "module_slug": MODULE_NAME,
        "reason": "",
        "publication_status": "success",
        "python_authoritative": True,
        "stages": {
            "adaptation_gate_order": {"status": "success"},
            "report_agreement": {"status": "pass"},
            "module_summary": {"status": "success"},
            "markdown": {"status": "success"},
            "pre_registry_report": {"status": "pending_registry"},
            "registry": {
                "status": "success",
                "verified": True,
                "integration_attempted": True,
                "reason": "adaptation_registry_integrated_and_verified",
            },
            "campaign_sync": {
                "status": "success",
                "campaign_visibility_verified": True,
            },
        },
        "rollback": {
            "status": "not_needed",
            "attempted": False,
            "verified": True,
            "reason": "publication_transaction_pending_final_report",
        },
    }


def _failed_finisher_report() -> Dict[str, Any]:
    return {
        "status": "blocked",
        "module_slug": MODULE_NAME,
        "reason": "adaptation_campaign_sync_failed",
        "publication_status": "blocked",
        "python_authoritative": True,
        "stages": {
            "registry": {
                "status": "success",
                "verified": True,
                "integration_attempted": True,
                "reason": "adaptation_registry_integrated_and_verified",
            },
            "campaign_sync": {
                "status": "blocked",
                "campaign_visibility_verified": False,
                "reason": "campaign_sync_exception",
            },
            "publication_rollback": {
                "status": "success",
                "verified": True,
                "reason": "pre_transaction_state_restored",
            },
        },
        "rollback": {
            "status": "success",
            "attempted": True,
            "verified": True,
            "reason": "adaptation_publication_rolled_back",
        },
    }


class _EmitRecorder:
    """Records socketio.emit calls in order."""

    def __init__(self) -> None:
        self.events: List[tuple] = []

    def emit(self, event: str, payload: Any) -> None:
        self.events.append((str(event), deepcopy(payload)))


class _FakeBuilderConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.module_name = kwargs.get("module_name")
        self.num_areas = kwargs.get("num_areas")
        self.locations_per_area = kwargs.get("locations_per_area")
        self.output_directory = kwargs.get("output_directory")
        self.verbose = kwargs.get("verbose")


class _FakeModuleBuilder:
    """Deterministic ModuleBuilder fake: records any direct legacy invocation."""

    last_instance: Optional["_FakeModuleBuilder"] = None

    def __init__(self, config: Any) -> None:
        _FakeModuleBuilder.last_instance = self
        self.config = config
        self.build_calls: List[str] = []

    def build_module(self, narrative: Any) -> None:
        self.build_calls.append(str(narrative))


def _fake_module_builder_module() -> types.ModuleType:
    fake = types.ModuleType("core.generators.module_builder")
    fake.ModuleBuilder = _FakeModuleBuilder
    fake.BuilderConfig = _FakeBuilderConfig
    return fake


_REAL_WORKSPACE_BUILDER = worker.build_text_description_attempt_workspace
_REAL_STAGING_CREATOR = worker.create_adaptation_staging_target


class _ProjectLocalScratchMixin:
    """Project-local scratch plus real workspace/staging redirection."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.workspaces_root = (
            "tmp/toolkit_text_description_integration"
            + "/"
            + self.scratch.name
            + "/workspaces"
        )
        self.staging_root = (
            "tmp/toolkit_text_description_integration"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.workspace_calls: list = []
        self.staging_calls: list = []
        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", False
        )
        self._flag_patch.start()
        self.addCleanup(self._stop_flag_patch)

    def _stop_flag_patch(self) -> None:
        self._flag_patch.stop()

    def _enable_adaptation(self) -> None:
        """Set the operator flag to exactly True for one test."""
        self._flag_patch.stop()
        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        )
        self._flag_patch.start()

    def _real_build_into_scratch(self, module_name: str, concept: Any, **kwargs: Any) -> Dict[str, Any]:
        """Wrap the real workspace builder so scratch stays project-local."""
        self.workspace_calls.append(module_name)
        return _REAL_WORKSPACE_BUILDER(
            module_name,
            concept,
            workspace_root=self.workspaces_root,
            staging_root=self.staging_root,
            **kwargs,
        )

    def _real_staging_into_scratch(self, source_hash: str, **kwargs: Any) -> Dict[str, Any]:
        """Wrap the real staging reservation so scratch stays project-local."""
        kwargs.pop("staging_root", None)
        target = _REAL_STAGING_CREATOR(
            source_hash,
            staging_root=self.staging_root,
            **kwargs,
        )
        self.staging_calls.append(dict(target))
        return target

    def _run_seam(self, runner: Optional[FakeAuthorRunner] = None, **seam_kwargs: Any) -> Optional[Dict[str, Any]]:
        """Run the REAL seam with the real workspace/staging builders redirected."""
        with patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=self._real_build_into_scratch,
        ), patch.object(
            worker,
            "create_adaptation_staging_target",
            side_effect=self._real_staging_into_scratch,
        ):
            return worker.run_text_description_adaptation_seam(
                MODULE_NAME,
                FIXTURE_TEXT,
                None,
                author_runner=runner,
                model="mock-adaptation-model",
                **seam_kwargs,
            )

    def _ready_seam_result(self, runner: Optional[FakeAuthorRunner] = None) -> Dict[str, Any]:
        """Real seam ready handoff (authoring_ready_pending_publication)."""
        result = self._run_seam(runner)
        self.assertIsNotNone(result)
        self.assertEqual(
            result["outcome"], worker.TEXT_WORKER_OUTCOME_AUTHORING_READY
        )
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_READY)
        return result

    def _handoff(self, seam_result: Dict[str, Any]) -> Dict[str, Any]:
        handoff = seam_result["adaptation_handoff"]
        self.assertIsInstance(handoff, dict)
        return handoff

    def _run_publication(
        self,
        seam_result: Dict[str, Any],
        *,
        build_runner: Any = None,
        finisher_runner: Any = None,
        progress_callback: Optional[Callable[[str, str], bool]] = None,
    ) -> Dict[str, Any]:
        """Run the REAL staged publication transaction with injected runners."""
        return worker.run_text_description_adaptation_publication(
            seam_result,
            build_runner=build_runner,
            finisher_runner=finisher_runner,
            progress_callback=progress_callback,
        )


class _ProtectedArtifactMixin:
    """Byte-snapshot module/registry/campaign protected artifacts."""

    def _snapshot_protected(self) -> Dict[str, Any]:
        def _bytes(path: Path) -> Optional[bytes]:
            try:
                return path.read_bytes()
            except FileNotFoundError:
                return None

        return {
            "registry": _bytes(REGISTRY_PATH),
            "campaign": _bytes(CAMPAIGN_PATH),
            "modules_entries": sorted(
                str(entry.relative_to(MODULES_DIR)) for entry in MODULES_DIR.iterdir()
            ),
        }

    def _assert_protected_unchanged(self, before: Dict[str, Any]) -> None:
        after = self._snapshot_protected()
        self.assertEqual(after["registry"], before["registry"], "registry mutated")
        self.assertEqual(after["campaign"], before["campaign"], "campaign mutated")
        self.assertEqual(
            after["modules_entries"], before["modules_entries"], "modules tree mutated"
        )
        self.assertFalse(
            (MODULES_DIR / MODULE_NAME).exists(),
            "no direct modules/<name> write is allowed on the enabled path",
        )


class _BoundedDiagnosticsMixin:
    """Assert bounded failure diagnostics on blocked outcomes."""

    def _assert_bounded_diagnostics(self, diagnostics: Any) -> None:
        self.assertIsInstance(diagnostics, list)
        self.assertLessEqual(len(diagnostics), worker.MAX_SEAM_DIAGNOSTICS)
        for item in diagnostics:
            self.assertIsInstance(item, dict)
            self.assertTrue(str(item.get("code") or ""))
            self.assertLessEqual(
                len(str(item.get("message") or "")),
                worker.MAX_SEAM_DIAGNOSTIC_CHARS,
            )


class TestTextIntegrationSuccessChain(
    _ProjectLocalScratchMixin, _ProtectedArtifactMixin, unittest.TestCase
):
    """Real seam -> real publication -> verified completion."""

    def test_success_chain_reaches_verified_completion_only_after_publication(
        self,
    ) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        progress = _ProgressRecorder()
        seam_result = self._ready_seam_result(runner)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(len(self.staging_calls), 1)
        handoff = self._handoff(seam_result)

        fake_build = _FakeBuildRunner(
            _success_build_result(handoff["staging_target"], handoff["workspace_path"])
        )
        fake_finisher = _FakeFinisherRunner(_success_finisher_report())
        publication = self._run_publication(
            seam_result,
            build_runner=fake_build,
            finisher_runner=fake_finisher,
            progress_callback=progress,
        )

        # Completed ONLY after the verified shared finisher report.
        self.assertEqual(publication["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        self.assertEqual(publication["status"], worker.TEXT_WORKER_STATUS_COMPLETED)
        self.assertEqual(publication["reason_code"], "text_description_adaptation_published")
        self.assertEqual(publication["module_name"], MODULE_NAME)
        summary = publication["adaptation_publication"]
        self.assertEqual(summary["build_status"], "success")
        self.assertEqual(summary["finisher_status"], "success")
        self.assertEqual(summary["gate_playable_status"], "pass")
        self.assertEqual(summary["registry_status"], "success")
        self.assertTrue(summary["registry_verified"])
        self.assertEqual(summary["campaign_sync_status"], "success")
        self.assertTrue(summary["campaign_visibility_verified"])
        self.assertEqual(summary["rollback_status"], "not_needed")
        self.assertTrue(summary["python_authoritative"])
        self.assertIn("adaptation_build", progress.phases)
        self.assertIn("adaptation_readiness", progress.phases)
        self.assertIn("adaptation_completed", progress.phases)

        # The shared upload handoff kwargs reached the packet build boundary.
        self.assertEqual(len(fake_build.calls), 1)
        _workspace, _job_id, build_kwargs = fake_build.calls[0]
        self.assertEqual(build_kwargs["adaptation_route"], "llm_adaptation")
        self.assertEqual(
            build_kwargs["adaptation_dossier"]["source_hash"], FIXTURE_HASH
        )
        self.assertEqual(
            build_kwargs["adaptation_staging_target"]["path"],
            handoff["staging_target"]["path"],
        )
        # The finisher received exactly the upload finisher kwargs.
        self.assertEqual(len(fake_finisher.calls), 1)
        _module_slug, finisher_kwargs = fake_finisher.calls[0]
        self.assertEqual(finisher_kwargs["strict"], True)
        self.assertEqual(finisher_kwargs["adaptation_mode"], "llm_adaptation")
        self.assertEqual(
            finisher_kwargs["adaptation_gates"]["playable_status"], "pass"
        )
        self.assertEqual(
            finisher_kwargs["adaptation_module_dir"], handoff["staging_target"]["path"]
        )
        self.assertEqual(
            finisher_kwargs["adaptation_artifact_workspace"], handoff["workspace_path"]
        )
        self.assertEqual(
            finisher_kwargs["adaptation_provenance"]["source_hash"], FIXTURE_HASH
        )

        self.assertTrue(worker.validate_text_description_publication_result(publication)["valid"])
        self._assert_protected_unchanged(before)

    def test_identity_and_references_stay_coherent_through_completion(self) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        seam_result = self._ready_seam_result(runner)
        handoff = self._handoff(seam_result)

        # Source hash: seam route authority -> handoff -> publication identity.
        self.assertEqual(
            seam_result["route_decision"]["route_selected"], "llm_adaptation"
        )
        self.assertIs(
            seam_result["route_decision"]["fallback_allowed"], False
        )
        self.assertEqual(handoff["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff["source_title"], MODULE_NAME)
        attempt = handoff["attempt"]
        self.assertTrue(attempt["attempt_id"])
        self.assertEqual(attempt["attempt_number"], 1)
        self.assertEqual(attempt["revision_number"], 0)
        # Python-owned rights survive the authoring boundary.
        self.assertEqual(handoff["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertIs(handoff["rights"]["python_owned"], True)
        self.assertIs(handoff["rights"]["provider_may_change"], False)
        # Canonical bounded world-context provenance with explicit fallback.
        self.assertEqual(
            handoff["world_context"]["fallback_status"], "seed_data_unavailable"
        )
        self.assertIs(handoff["world_context"]["read_only"], True)
        self.assertIs(handoff["world_context"]["raw_context_included"], False)

        # Dossier/proposal artifacts were persisted inside the attempt workspace.
        workspace_abs = REPO_ROOT.joinpath(*Path(handoff["workspace_path"]).parts)
        dossier_artifact = load_adaptation_artifact(
            workspace_abs, attempt["attempt_id"], ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)
        self.assertEqual(
            dossier_artifact.get("provenance", {}).get("source_hash"),
            FIXTURE_HASH,
        )
        proposal_path = get_adaptation_proposal_path(
            workspace_abs, attempt["attempt_id"], 0
        )
        self.assertTrue(proposal_path.exists(), "proposal ledger must be persisted")
        # References stay project-relative and never under modules/.
        self.assertNotIn("modules/", handoff["workspace_path"])
        self.assertNotIn("modules/", handoff["staging_target_path"])
        self.assertTrue(handoff["dossier_artifact_path"].endswith("dossier.json"))
        self.assertEqual(
            seam_result["route_decision"]["fallback_allowed"], False
        )

        # The same identity survives the publication transition.
        fake_build = _FakeBuildRunner(
            _success_build_result(handoff["staging_target"], handoff["workspace_path"])
        )
        publication = self._run_publication(
            seam_result,
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(_success_finisher_report()),
        )
        self.assertEqual(publication["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        identity = publication["adaptation_handoff"]
        self.assertEqual(identity["source_hash"], FIXTURE_HASH)
        self.assertEqual(identity["module_name"], MODULE_NAME)
        self.assertEqual(identity["attempt"]["attempt_id"], attempt["attempt_id"])
        self.assertEqual(identity["attempt"]["attempt_number"], 1)
        self.assertEqual(identity["attempt"]["revision_number"], 0)
        self.assertEqual(
            identity["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        self.assertEqual(
            identity["world_context"]["fallback_status"], "seed_data_unavailable"
        )
        self.assertEqual(
            identity["workspace_path"], handoff["workspace_path"]
        )
        self.assertEqual(
            identity["staging_target_path"], handoff["staging_target"]["path"]
        )
        self.assertEqual(publication["diagnostics"], [])
        self._assert_protected_unchanged(before)


class TestTextIntegrationAuthoringFailureChains(
    _ProjectLocalScratchMixin,
    _ProtectedArtifactMixin,
    _BoundedDiagnosticsMixin,
    unittest.TestCase,
):
    """Selected adaptation authoring failures fail closed before staging."""

    def test_author_policy_refusal_blocks_before_staging(self) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt, refused=True)
        result = self._run_seam(runner)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_FAILED_CLOSED)
        self.assertEqual(result["reason_code"], "dossier_refused")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(len(self.staging_calls), 0)
        self.assertEqual(
            result["route_decision"]["route_selected"], "llm_adaptation"
        )
        self.assertIs(result["route_decision"]["fallback_allowed"], False)
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)

    def test_api_refusal_is_a_distinct_blocked_channel(self) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(
            dossier_builder=_dossier_for_attempt, api_refusal=True
        )
        result = self._run_seam(runner)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["reason_code"], "provider_api_refusal")
        self.assertNotEqual(result["reason_code"], "dossier_refused")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(len(self.staging_calls), 0)
        self.assertIs(result["route_decision"]["fallback_allowed"], False)
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)

    def test_invalid_dossier_blocks_before_staging(self) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(invalid_dossier=True)
        result = self._run_seam(runner)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["reason_code"], "dossier_validation_failed")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(len(self.staging_calls), 0)
        self.assertIs(result["route_decision"]["fallback_allowed"], False)
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)

    def test_non_build_ready_dossier_blocks_before_staging(self) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(
            dossier_builder=_dossier_for_attempt, non_build_ready=True
        )
        result = self._run_seam(runner)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["reason_code"], "dossier_failed")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(len(self.staging_calls), 0)
        self.assertIs(result["route_decision"]["fallback_allowed"], False)
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)

    def test_authoring_infrastructure_failure_blocks(self) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(
            dossier_builder=_dossier_for_attempt,
            error=RuntimeError("provider timeout"),
        )
        result = self._run_seam(runner)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(
            result["reason_code"], "text_description_authoring_infrastructure_failure"
        )
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(len(self.staging_calls), 0)
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)


class TestTextIntegrationReadinessAndPublicationFailureChains(
    _ProjectLocalScratchMixin,
    _ProtectedArtifactMixin,
    _BoundedDiagnosticsMixin,
    unittest.TestCase,
):
    """A ready authoring handoff never reports success before verified
    publication; readiness and finisher failures block with rollback facts."""

    def test_readiness_gate_failure_blocks_before_finisher_and_publication(
        self,
    ) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        progress = _ProgressRecorder()
        seam_result = self._ready_seam_result(runner)
        handoff = self._handoff(seam_result)
        fake_finisher = _FakeFinisherRunner(_success_finisher_report())
        result = self._run_publication(
            seam_result,
            build_runner=_FakeBuildRunner(_blocked_gate_build_result()),
            finisher_runner=fake_finisher,
            progress_callback=progress,
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_FAILED_CLOSED)
        self.assertEqual(
            result["reason_code"], "text_description_adaptation_build_blocked"
        )
        self.assertEqual(len(fake_finisher.calls), 0)
        summary = result["adaptation_publication"]
        self.assertEqual(summary["build_status"], "blocked")
        self.assertEqual(summary["gate_playable_status"], "blocked")
        self.assertEqual(summary["registry_status"], "not_attempted")
        self.assertEqual(summary["campaign_sync_status"], "not_attempted")
        self.assertEqual(summary["rollback_status"], "not_attempted")
        self.assertIn("adaptation_build", progress.phases)
        self.assertNotIn("adaptation_readiness", progress.phases)
        self.assertNotIn("adaptation_completed", progress.phases)
        # Identity stays coherent on the blocked outcome.
        identity = result["adaptation_handoff"]
        self.assertEqual(identity["source_hash"], FIXTURE_HASH)
        self.assertEqual(identity["attempt"]["attempt_id"], handoff["attempt"]["attempt_id"])
        self.assertEqual(
            identity["staging_target_path"], handoff["staging_target"]["path"]
        )
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)

    def test_finisher_failure_blocks_with_registry_campaign_rollback_facts(
        self,
    ) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        seam_result = self._ready_seam_result(runner)
        handoff = self._handoff(seam_result)
        fake_build = _FakeBuildRunner(
            _success_build_result(handoff["staging_target"], handoff["workspace_path"])
        )
        result = self._run_publication(
            seam_result,
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(_failed_finisher_report()),
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_FAILED_CLOSED)
        self.assertEqual(result["reason_code"], "adaptation_campaign_sync_failed")
        summary = result["adaptation_publication"]
        self.assertEqual(summary["finisher_status"], "blocked")
        self.assertEqual(summary["registry_status"], "success")
        self.assertTrue(summary["registry_verified"])
        self.assertEqual(summary["campaign_sync_status"], "blocked")
        self.assertFalse(summary["campaign_visibility_verified"])
        self.assertEqual(summary["rollback_status"], "success")
        self.assertTrue(summary["rollback_verified"])
        self.assertNotEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)

    def test_finisher_infrastructure_failure_blocks(self) -> None:
        self._enable_adaptation()
        before = self._snapshot_protected()
        runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        seam_result = self._ready_seam_result(runner)
        handoff = self._handoff(seam_result)
        fake_build = _FakeBuildRunner(
            _success_build_result(handoff["staging_target"], handoff["workspace_path"])
        )
        result = self._run_publication(
            seam_result,
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(None, error=RuntimeError("boom")),
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(
            result["reason_code"],
            "text_description_publication_finisher_infrastructure_failure",
        )
        self.assertEqual(
            result["adaptation_publication"]["registry_status"], "not_attempted"
        )
        self.assertNotEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        self._assert_bounded_diagnostics(result["diagnostics"])
        self._assert_protected_unchanged(before)


class _EnabledHostIntegrationHarness(
    _ProjectLocalScratchMixin, unittest.TestCase
):
    """Runs the REAL host worker with the REAL seam and REAL publication.

    Only the provider/network/module-write boundaries are injected: the author
    runner at the seam, and the packet-build/finisher runners at the
    publication stage. The host routing and emission guarantees are therefore
    exercised end to end (host branch -> real seam -> real authoring adapter ->
    real publication transaction -> host emission).
    """

    def setUp(self) -> None:
        super().setUp()
        self._enable_adaptation()
        self.recorder = _EmitRecorder()
        self.builder_fake_module = _fake_module_builder_module()
        _FakeModuleBuilder.last_instance = None
        self.runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        self.build_runner = _FakeBuildRunner(_blocked_gate_build_result())
        self.finisher_runner = _FakeFinisherRunner(_success_finisher_report())

        self.sys_modules_patch = patch.dict(
            sys.modules, {"core.generators.module_builder": self.builder_fake_module}
        )
        self.sys_modules_patch.start()
        self.addCleanup(self.sys_modules_patch.stop)

        self.worker_patches = [
            patch.object(
                worker,
                "build_text_description_attempt_workspace",
                side_effect=self._real_build_into_scratch,
            ),
            patch.object(
                worker,
                "create_adaptation_staging_target",
                side_effect=self._real_staging_into_scratch,
            ),
        ]
        for p in self.worker_patches:
            p.start()
            self.addCleanup(p.stop)

        def _real_seam(module_name: str, narrative: str, params: Any) -> Any:
            return worker.run_text_description_adaptation_seam(
                module_name,
                narrative,
                params,
                author_runner=self.runner,
                model="mock-adaptation-model",
            )

        def _real_publication(seam_result: Any, **kwargs: Any) -> Any:
            return worker.run_text_description_adaptation_publication(
                seam_result,
                build_runner=self.build_runner,
                finisher_runner=self.finisher_runner,
                **kwargs,
            )

        self.host_patches = [
            patch.object(web_interface, "socketio", self.recorder),
            patch.object(web_interface, "TEXT_DESCRIPTION_ADAPTATION_AVAILABLE", True),
            patch.object(web_interface, "run_text_description_adaptation_seam", _real_seam),
            patch.object(
                web_interface,
                "run_text_description_adaptation_publication",
                _real_publication,
            ),
        ]
        for p in self.host_patches:
            p.start()
            self.addCleanup(p.stop)

    def _run_worker(self, params: Dict[str, Any]) -> None:
        web_interface.simulate_build_process(params)

    def _events(self, name: str) -> List[Dict[str, Any]]:
        return [payload for event, payload in self.recorder.events if event == name]

    def _assert_no_legacy_builder(self) -> None:
        self.assertIsNone(
            _FakeModuleBuilder.last_instance,
            "legacy ModuleBuilder must never be constructed on the enabled path",
        )
        self.assertFalse(
            (MODULES_DIR / MODULE_NAME).exists(),
            "no direct modules/<name> write is allowed on the enabled path",
        )


class TestTextIntegrationHostWorkerChain(
    _EnabledHostIntegrationHarness,
    _ProtectedArtifactMixin,
    _BoundedDiagnosticsMixin,
):
    """Real host worker end-to-end routing and emission guarantees."""

    def _dynamic_success_build(self) -> Tuple[Any, List[Dict[str, Any]]]:
        calls: List[Dict[str, Any]] = []

        def _build(workspace: Any, job_id: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
            calls.append(
                {
                    "workspace": str(workspace),
                    "job_id": str(job_id),
                    "kwargs": deepcopy(kwargs),
                }
            )
            staging_target = kwargs.get("adaptation_staging_target") or {}
            return _success_build_result(staging_target, str(workspace))

        return _build, calls

    def test_host_success_emits_exactly_one_adaptation_marked_completion(
        self,
    ) -> None:
        before = self._snapshot_protected()
        build_fn, build_calls = self._dynamic_success_build()
        self.build_runner = _FakeBuildRunner(build_fn)
        self.finisher_runner = _FakeFinisherRunner(_success_finisher_report())
        self._run_worker(_params())

        self.assertEqual(len(self.runner.calls), 1)
        completes = self._events("module_complete")
        self.assertEqual(len(completes), 1, "exactly one completion expected")
        payload = completes[0]
        self.assertEqual(payload["module_name"], MODULE_NAME)
        self.assertEqual(payload["final_status"], "success")
        self.assertIs(payload["generation_succeeded"], True)
        self.assertEqual(payload["adaptation_route"], "llm_adaptation")
        self.assertIs(payload["adaptation_job"], True)
        self.assertEqual(payload["adaptation_outcome"], "completed")
        self.assertEqual(payload["adaptation_source_hash"], FIXTURE_HASH)
        self.assertTrue(payload["adaptation_attempt_id"])
        self.assertIs(
            payload["adaptation_route_decision"]["fallback_allowed"], False
        )
        report = payload["build_report"]
        self.assertEqual(report["registry_status"], "success")
        self.assertTrue(report["registry_verified"])
        self.assertEqual(report["campaign_sync_status"], "success")
        self.assertEqual(self._events("module_error"), [])
        # The real publication transaction ran with the upload handoff kwargs.
        self.assertEqual(len(build_calls), 1)
        self.assertEqual(build_calls[0]["kwargs"]["adaptation_route"], "llm_adaptation")
        self.assertEqual(
            build_calls[0]["kwargs"]["adaptation_dossier"]["source_hash"],
            FIXTURE_HASH,
        )
        self.assertEqual(len(self.finisher_runner.calls), 1)
        self.assertEqual(
            self.finisher_runner.calls[0][1]["adaptation_mode"], "llm_adaptation"
        )
        self._assert_no_legacy_builder()
        self._assert_protected_unchanged(before)

    def test_host_author_refusal_emits_blocked_adaptation_error_never_success(
        self,
    ) -> None:
        before = self._snapshot_protected()
        self.runner = FakeAuthorRunner(
            dossier_builder=_dossier_for_attempt, refused=True
        )
        self._run_worker(_params())

        self.assertEqual(self._events("module_complete"), [])
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertIs(payload.get("generation_succeeded"), False)
        self.assertEqual(payload.get("module_name"), MODULE_NAME)
        self.assertEqual(payload.get("adaptation_route"), "llm_adaptation")
        self.assertIs(payload.get("adaptation_job"), True)
        self.assertEqual(payload.get("adaptation_outcome"), "blocked")
        self.assertEqual(payload.get("adaptation_reason_code"), "dossier_refused")
        self.assertIs(
            payload.get("adaptation_route_decision", {}).get("fallback_allowed"),
            False,
        )
        self._assert_bounded_diagnostics(payload.get("adaptation_diagnostics") or [])
        self._assert_no_legacy_builder()
        self._assert_protected_unchanged(before)

    def test_host_publication_failure_never_emits_success(self) -> None:
        before = self._snapshot_protected()
        # Ready authoring handoff but blocked readiness/gate build result.
        self.build_runner = _FakeBuildRunner(_blocked_gate_build_result())
        self._run_worker(_params())

        self.assertEqual(self._events("module_complete"), [])
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(payload.get("adaptation_outcome"), "blocked")
        self.assertEqual(
            payload.get("adaptation_reason_code"),
            "text_description_adaptation_build_blocked",
        )
        publication = payload.get("adaptation_publication") or {}
        self.assertEqual(publication.get("registry_status"), "not_attempted")
        self.assertEqual(publication.get("campaign_sync_status"), "not_attempted")
        self.assertEqual(publication.get("rollback_status"), "not_attempted")
        self.assertEqual(len(self.finisher_runner.calls), 0)
        self._assert_bounded_diagnostics(payload.get("adaptation_diagnostics") or [])
        self._assert_no_legacy_builder()
        self._assert_protected_unchanged(before)


class TestTextIntegrationHygiene(unittest.TestCase):
    """ASCII, SPDX, path-policy, provider-free, and boundary honesty rules."""

    def test_this_suite_is_ascii_only_with_spdx_header(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        non_ascii = [ch for ch in text if ord(ch) >= 128]
        self.assertEqual(non_ascii, [], "non-ASCII characters in this suite")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)

    def test_no_os_temp_or_absolute_scratch_paths(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("class TestTextIntegrationHygiene", 1)[0]
        self.assertNotIn("tempfile", scan)
        self.assertNotIn("/tmp", scan)
        self.assertNotIn("/var/folders", scan)
        self.assertIn("tmp/toolkit_text_description_integration", scan)
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))

    def test_this_suite_never_imports_provider_modules(self) -> None:
        import_lines = [
            line.strip()
            for line in Path(__file__).read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        imports = "\n".join(import_lines)
        for token in (
            "import openai",
            "import httpx",
            "import requests",
            "import socketio",
            "import urllib",
            "import http",
            "import socket",
            "import aiohttp",
            "import websockets",
            "import tempfile",
            "from openai",
            "from requests",
            "from socketio",
        ):
            self.assertNotIn(token, imports)

    def test_flag_is_patched_to_exactly_true_in_behavioral_tests(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            'patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", True)',
            own_source,
        )

    def test_suite_exercises_real_seam_and_publication_boundaries(self) -> None:
        # This suite is the integration layer: it must call the REAL seam and
        # REAL publication functions directly (with injected seams only at the
        # provider/module-write boundaries), never re-fake the worker stages.
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("class TestTextIntegrationHygiene", 1)[0]
        self.assertIn("worker.run_text_description_adaptation_seam(", scan)
        self.assertIn(
            "worker.run_text_description_adaptation_publication(", scan
        )
        self.assertIn("web_interface.simulate_build_process(params)", scan)
        # The real workspace/staging builders are redirected into scratch.
        self.assertIn("_REAL_WORKSPACE_BUILDER(", scan)
        self.assertIn("_REAL_STAGING_CREATOR(", scan)

    def test_protected_artifact_sentinels_checked_in_every_behavioral_class(
        self,
    ) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("class TestTextIntegrationHygiene", 1)[0]
        for class_name in (
            "TestTextIntegrationSuccessChain",
            "TestTextIntegrationAuthoringFailureChains",
            "TestTextIntegrationReadinessAndPublicationFailureChains",
            "TestTextIntegrationHostWorkerChain",
        ):
            self.assertIn(class_name, scan)
        # Every behavioral class snapshots and asserts protected artifacts.
        self.assertGreaterEqual(scan.count("_assert_protected_unchanged(before)"), 11)
        self.assertGreaterEqual(scan.count("_snapshot_protected()"), 2)


if __name__ == "__main__":
    unittest.main()
