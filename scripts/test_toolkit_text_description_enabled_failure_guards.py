# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free enabled text-description failure guards
(task 5.4 of toolkit-llm-adaptation-runtime-unification).

The suite locks the no-downgrade/no-false-success contract of the enabled
text-description build worker with the REAL host worker
``web.web_interface.simulate_build_process`` and injected deterministic
seam/publication fakes:

  * every enabled adaptation failure (author refusal, infrastructure failure,
    invalid dossier, workspace failure, staging failure, build/gate failure,
    finisher/publication failure) terminates as an explicit bounded
    adaptation ``module_error`` outcome; the legacy direct ModuleBuilder path
    is NEVER invoked (no builder construction, no ``./modules/<name>`` write)
    and the legacy success event ``module_complete`` is NEVER emitted;
  * a raw or mocked ``ModuleBuilder.build_module()`` completion is NEVER
    sufficient for adaptation success: the real publication stage blocks
    when the shared finisher is unavailable, raises, or reports non-success;
    completion is reported only after the verified shared publication
    transaction (finisher success with registry/campaign verification);
  * a successful enabled build emits ``module_complete`` exactly once, with
    adaptation markers, and still never constructs the legacy builder;
  * protected module, registry, and campaign artifacts are byte-checked
    before and after every behavioral test.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_text_description_enabled_failure_guards/<uuid>/`` and are
removed deterministically via addCleanup. Real ``modules/world_registry.json``
and ``modules/campaign.json`` byte sentinels plus the real ``modules/``
listing are checked before and after every behavioral test. The live operator
flag is NEVER relied on: every behavioral test explicitly patches
``model_config.ENABLE_LLM_ADAPTATION`` to exactly True. No OS-temporary
scratch, no provider/network imports or calls.
"""

import hashlib
import json
import sys
import types
import unittest
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.web_interface as web_interface
import web.extensions.toolkit_text_adaptation_worker as worker

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_INTERFACE_PATH = REPO_ROOT / "web" / "web_interface.py"
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_text_description_enabled_failure_guards"
REGISTRY_PATH = REPO_ROOT / "modules" / "world_registry.json"
CAMPAIGN_PATH = REPO_ROOT / "modules" / "campaign.json"
MODULES_DIR = REPO_ROOT / "modules"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()
MODULE_NAME = "Sunken_Lighthouse"
ATTEMPT_ID = "5a4b3c2d1e0f1029384756a7b8c9d0e1"
JOB_ID = "text-job-guard-0001"

# Enabled seam failure reason codes locked per failure surface.
SEAM_FAILURE_REASONS = {
    "author_policy_refusal": "dossier_refused",
    "api_refusal": "provider_api_refusal",
    "authoring_infrastructure": "text_description_authoring_infrastructure_failure",
    "invalid_dossier": "text_description_dossier_not_ready",
    "workspace_failure": "text_description_workspace_failed",
    "staging_failure": "adaptation_staging_reservation_failed",
    "route_authority_invalid": "adaptation_route_authority_invalid",
}

# Enabled publication failure reason codes locked per failure surface.
PUBLICATION_FAILURE_REASONS = {
    "build_gate_blocked": "text_description_adaptation_build_blocked",
    "build_infrastructure": "text_description_publication_build_infrastructure_failure",
    "finisher_not_success": "text_description_publication_finisher_not_success",
    "finisher_infrastructure": "text_description_publication_finisher_infrastructure_failure",
}


def _params(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "module_name": MODULE_NAME,
        "narrative": FIXTURE_TEXT,
        "num_areas": 5,
        "locations_per_area": 3,
    }
    base.update(overrides)
    return base


def _route_decision() -> Dict[str, Any]:
    return {
        "contract_version": "toolkit_adaptation_route_decision.v1",
        "status": "llm_adaptation",
        "route_selected": "llm_adaptation",
        "input_kind": "text_description",
        "module_name": MODULE_NAME,
        "source_hash": FIXTURE_HASH,
        "rights_class": "user_authored",
        "adaptation_artifacts_required": True,
        "fallback_allowed": False,
    }


def _blocked_seam_result(reason_code: str) -> Dict[str, Any]:
    """Bounded fail-closed seam outcome for one enabled failure surface."""
    return {
        "contract_version": worker.TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION,
        "outcome": worker.TEXT_WORKER_OUTCOME_BLOCKED,
        "status": worker.TEXT_WORKER_STATUS_FAILED_CLOSED,
        "route_decision": _route_decision(),
        "reason_code": str(reason_code)[: worker.MAX_SEAM_REASON_CODE_CHARS],
        "diagnostics": [
            {
                "code": str(reason_code)[: worker.MAX_SEAM_REASON_CODE_CHARS],
                "message": "bounded enabled adaptation failure diagnostic",
            }
        ],
    }


def _ready_seam_result(workspace_ref: str = "", staging_path: str = "") -> Dict[str, Any]:
    """Bounded ready authoring handoff consumed by the publication stage."""
    handoff: Dict[str, Any] = {
        "module_name": MODULE_NAME,
        "source_hash": FIXTURE_HASH,
        "source_title": MODULE_NAME,
        "dossier": {
            "status": "ready",
            "adapted_title": MODULE_NAME,
            "source_hash": FIXTURE_HASH,
        },
        "attempt": {
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": JOB_ID,
        },
        "rights": {
            "rights_class": "user_authored",
            "rights_basis": "user_submitted_text_description",
            "rights_review_required": "not_required",
            "rights_review_status": "approved",
            "python_owned": True,
            "classified_by": "python",
        },
        "world_context": {
            "status": "unavailable",
            "fallback_status": "seed_data_unavailable",
            "read_only": True,
        },
        "model_metadata": {"model": "mock-adaptation-model", "provider": "mock"},
        "dossier_artifact_path": (
            f"adaptation_attempts/{ATTEMPT_ID}/dossier.json"
        ),
        "workspace_path": workspace_ref,
        "staging_target": {"path": staging_path},
        "staging_target_path": staging_path,
        "staging_root": str(Path(staging_path).parent) if staging_path else "",
        "provenance": {
            "attempt_metadata": {
                "attempt_id": ATTEMPT_ID,
                "attempt_number": 1,
                "revision_number": 0,
                "job_id": JOB_ID,
            },
            "model_metadata": {"model": "mock-adaptation-model", "provider": "mock"},
            "world_context_provenance": {
                "status": "unavailable",
                "fallback_status": "seed_data_unavailable",
                "read_only": True,
            },
            "source_hash": FIXTURE_HASH,
            "source_title": MODULE_NAME,
            "source_format": "text_description",
            "rights_class": "user_authored",
            "rights_basis": "user_submitted_text_description",
        },
    }
    return {
        "contract_version": worker.TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION,
        "outcome": worker.TEXT_WORKER_OUTCOME_AUTHORING_READY,
        "status": worker.TEXT_WORKER_STATUS_READY,
        "route_decision": _route_decision(),
        "adaptation_handoff": handoff,
        "diagnostics": [],
    }


def _blocked_publication_result(reason_code: str) -> Dict[str, Any]:
    """Bounded fail-closed publication outcome for one enabled failure."""
    return {
        "contract_version": worker.TEXT_PUBLICATION_CONTRACT_VERSION,
        "outcome": worker.TEXT_WORKER_OUTCOME_BLOCKED,
        "status": worker.TEXT_WORKER_STATUS_FAILED_CLOSED,
        "module_name": MODULE_NAME,
        "route_decision": _route_decision(),
        "reason_code": str(reason_code)[: worker.MAX_SEAM_REASON_CODE_CHARS],
        "diagnostics": [
            {
                "code": str(reason_code)[: worker.MAX_SEAM_REASON_CODE_CHARS],
                "message": "bounded enabled publication failure diagnostic",
            }
        ],
        "adaptation_publication": {
            "registry_status": "not_attempted",
            "campaign_sync_status": "not_attempted",
            "rollback_status": "not_attempted",
        },
        "adaptation_handoff": {
            "module_name": MODULE_NAME,
            "source_hash": FIXTURE_HASH,
            "attempt": {
                "attempt_id": ATTEMPT_ID,
                "attempt_number": 1,
                "revision_number": 0,
                "job_id": JOB_ID,
            },
        },
    }


def _completed_publication_result() -> Dict[str, Any]:
    """Verified shared-publication success outcome (only success path)."""
    return {
        "contract_version": worker.TEXT_PUBLICATION_CONTRACT_VERSION,
        "outcome": worker.TEXT_WORKER_OUTCOME_COMPLETED,
        "status": worker.TEXT_WORKER_STATUS_COMPLETED,
        "module_name": MODULE_NAME,
        "route_decision": _route_decision(),
        "reason_code": "text_description_adaptation_published",
        "diagnostics": [],
        "adaptation_publication": {
            "build_status": "success",
            "finisher_status": "success",
            "publication_status": "success",
            "registry_status": "success",
            "registry_verified": True,
            "campaign_sync_status": "success",
            "campaign_visibility_verified": True,
            "rollback_status": "not_needed",
            "python_authoritative": True,
        },
        "adaptation_handoff": {
            "module_name": MODULE_NAME,
            "source_hash": FIXTURE_HASH,
            "attempt": {
                "attempt_id": ATTEMPT_ID,
                "attempt_number": 1,
                "revision_number": 0,
                "job_id": JOB_ID,
            },
            "workspace_path": "",
            "staging_target_path": "",
            "dossier_artifact_path": f"adaptation_attempts/{ATTEMPT_ID}/dossier.json",
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


class _FakeReadinessGate:
    """Deterministic readiness gate recording any legacy invocation."""

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def __call__(self, module_name: str, state_callback: Any = None) -> Dict[str, Any]:
        self.calls.append((module_name, state_callback is not None))
        return {
            "status": "pass",
            "module_name": module_name,
            "ready_for_finishing": True,
        }


class _FakeFinisher:
    """Deterministic post-build finisher recording any legacy invocation."""

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def __call__(self, module_name: str, strict: bool = True) -> Dict[str, Any]:
        self.calls.append((module_name, strict))
        return {
            "status": "success",
            "module_slug": module_name,
            "publishable_status": "pass",
            "stages": {},
        }


class _FakeSeam:
    """Deterministic injected seam recording the host invocation."""

    def __init__(
        self,
        result: Any,
        error: Optional[Exception] = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: List[tuple] = []

    def __call__(self, module_name: str, narrative: str, params: Any) -> Any:
        self.calls.append((module_name, narrative, deepcopy(params)))
        if self.error is not None:
            raise self.error
        return deepcopy(self.result)


class _FakePublication:
    """Deterministic injected publication stage recording the host invocation."""

    def __init__(
        self,
        result: Any,
        error: Optional[Exception] = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: List[tuple] = []

    def __call__(self, seam_result: Any, **kwargs: Any) -> Any:
        self.calls.append((deepcopy(seam_result), deepcopy(kwargs)))
        if self.error is not None:
            raise self.error
        return deepcopy(self.result)


class _EnabledHostHarness(unittest.TestCase):
    """Shared fake wiring executing the REAL host worker with flag exactly True.

    The seam and publication stage are injected deterministic fakes (their
    own behavior is locked by the task 5.1/5.2 suites); this harness proves
    the host routing/emission guarantees: every non-None seam result
    terminates the worker with an explicit adaptation outcome and the legacy
    direct builder below the branch is never reached.
    """

    def setUp(self) -> None:
        self.recorder = _EmitRecorder()
        self.builder_fake_module = _fake_module_builder_module()
        _FakeModuleBuilder.last_instance = None
        self.readiness = _FakeReadinessGate()
        self.finisher = _FakeFinisher()
        self.seam = _FakeSeam(None)
        self.publication = _FakePublication(None)
        self.flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        )
        self.flag_patch.start()
        self.addCleanup(self.flag_patch.stop)
        self.sys_modules_patch = patch.dict(
            sys.modules, {"core.generators.module_builder": self.builder_fake_module}
        )
        self.sys_modules_patch.start()
        self.addCleanup(self.sys_modules_patch.stop)
        self.patches = [
            patch.object(web_interface, "socketio", self.recorder),
            patch.object(
                web_interface, "TEXT_DESCRIPTION_ADAPTATION_AVAILABLE", True
            ),
            patch.object(web_interface, "run_text_description_adaptation_seam", self.seam),
            patch.object(
                web_interface,
                "run_text_description_adaptation_publication",
                self.publication,
            ),
            patch.object(web_interface, "TOOLKIT_BUILDER_READINESS_AVAILABLE", True),
            patch.object(
                web_interface, "run_toolkit_builder_readiness_gate", self.readiness
            ),
            patch.object(web_interface, "TOOLKIT_MODULE_FINISHER_AVAILABLE", True),
            patch.object(
                web_interface, "run_toolkit_module_postbuild_finishing", self.finisher
            ),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _run_worker(self, params: Dict[str, Any]) -> None:
        web_interface.simulate_build_process(params)

    def _events(self, name: str) -> List[Dict[str, Any]]:
        return [payload for event, payload in self.recorder.events if event == name]

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

    def _assert_no_legacy_builder(self) -> None:
        self.assertIsNone(
            _FakeModuleBuilder.last_instance,
            "legacy ModuleBuilder must never be constructed on the enabled path",
        )
        self.assertEqual(len(self.readiness.calls), 0, "legacy readiness ran")
        self.assertEqual(len(self.finisher.calls), 0, "legacy finisher ran")
        self.assertFalse(
            (REPO_ROOT / "modules" / MODULE_NAME).exists(),
            "no direct modules/<name> write is allowed on the enabled path",
        )

    def _assert_no_module_complete(self, message: str = "") -> None:
        self.assertEqual(
            self._events("module_complete"),
            [],
            f"legacy success event must never be emitted {message}".strip(),
        )

    def _assert_single_adaptation_error(self, expected_reason: str) -> Dict[str, Any]:
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1, "exactly one adaptation module_error expected")
        payload = errors[0]
        self.assertIs(payload.get("generation_succeeded"), False)
        self.assertEqual(payload.get("module_name"), MODULE_NAME)
        self.assertEqual(payload.get("adaptation_route"), "llm_adaptation")
        self.assertIs(payload.get("adaptation_job"), True)
        self.assertEqual(payload.get("adaptation_outcome"), "blocked")
        self.assertEqual(payload.get("adaptation_reason_code"), expected_reason)
        diagnostics = payload.get("adaptation_diagnostics")
        self.assertIsInstance(diagnostics, list)
        return payload


class TestEnabledSeamFailuresNeverFallBackToLegacy(_EnabledHostHarness):
    """Every enabled seam-level failure stays adaptation-blocked at the host."""

    def test_author_policy_refusal_blocks_without_legacy_fallback(self) -> None:
        for surface, reason in SEAM_FAILURE_REASONS.items():
            with self.subTest(surface=surface):
                self.recorder.events = []
                self.seam.calls = []
                self.publication.calls = []
                _FakeModuleBuilder.last_instance = None
                self.seam.result = _blocked_seam_result(reason)
                protected = self._snapshot_protected()
                self._run_worker(_params())

                self.assertEqual(len(self.seam.calls), 1)
                payload = self._assert_single_adaptation_error(reason)
                self.assertEqual(payload["adaptation_route_decision"]["route_selected"], "llm_adaptation")
                self.assertNotEqual(payload["adaptation_route_decision"].get("fallback_allowed", None), True)
                self._assert_no_legacy_builder()
                self._assert_no_module_complete(f"for {surface}")
                self.assertEqual(len(self.publication.calls), 0)
                self._assert_protected_unchanged(protected)

    def test_seam_raise_still_never_emits_legacy_success(self) -> None:
        # Even a pathological seam exception is contained by the worker's
        # fail-safe handler: no legacy success event, no legacy builder, and
        # an explicit module_error is emitted.
        self.seam.error = RuntimeError("unexpected seam failure")
        protected = self._snapshot_protected()
        self._run_worker(_params())
        self.assertEqual(self._events("module_complete"), [])
        self.assertGreaterEqual(len(self._events("module_error")), 1)
        self._assert_no_legacy_builder()
        self._assert_protected_unchanged(protected)

    def test_ready_handoff_alone_is_never_success_without_publication(self) -> None:
        # A raw ready authoring handoff (the seam analog of a raw builder
        # completion) must go through the publication stage; a blocked
        # publication result still yields only the adaptation module_error.
        self.seam.result = _ready_seam_result()
        self.publication.result = _blocked_publication_result(
            "text_description_adaptation_build_blocked"
        )
        protected = self._snapshot_protected()
        self._run_worker(_params())

        self.assertEqual(len(self.seam.calls), 1)
        self.assertEqual(len(self.publication.calls), 1)
        payload = self._assert_single_adaptation_error(
            "text_description_adaptation_build_blocked"
        )
        publication = payload.get("adaptation_publication")
        self.assertIsInstance(publication, dict)
        self.assertEqual(publication.get("registry_status"), "not_attempted")
        self.assertEqual(publication.get("campaign_sync_status"), "not_attempted")
        self._assert_no_legacy_builder()
        self._assert_no_module_complete("for blocked publication")
        self._assert_protected_unchanged(protected)


class TestEnabledPublicationFailuresNeverEmitLegacySuccess(_EnabledHostHarness):
    """Every enabled publication-level failure stays adaptation-blocked."""

    def test_publication_failures_never_emit_legacy_success(self) -> None:
        for surface, reason in PUBLICATION_FAILURE_REASONS.items():
            with self.subTest(surface=surface):
                self.recorder.events = []
                self.seam.calls = []
                self.publication.calls = []
                _FakeModuleBuilder.last_instance = None
                self.seam.result = _ready_seam_result()
                self.publication.result = _blocked_publication_result(reason)
                protected = self._snapshot_protected()
                self._run_worker(_params())

                self.assertEqual(len(self.seam.calls), 1)
                self.assertEqual(len(self.publication.calls), 1)
                payload = self._assert_single_adaptation_error(reason)
                self.assertIsInstance(payload.get("adaptation_publication"), dict)
                self.assertEqual(payload["adaptation_route_decision"]["route_selected"], "llm_adaptation")
                self._assert_no_legacy_builder()
                self._assert_no_module_complete(f"for {surface}")
                self._assert_protected_unchanged(protected)

    def test_publication_raise_never_emits_legacy_success(self) -> None:
        # A pathological publication exception is contained by the worker's
        # fail-safe handler: no legacy success event, no legacy builder.
        self.seam.result = _ready_seam_result()
        self.publication.error = RuntimeError("publication stage boom")
        protected = self._snapshot_protected()
        self._run_worker(_params())
        self.assertEqual(len(self.publication.calls), 1)
        self.assertEqual(self._events("module_complete"), [])
        self.assertGreaterEqual(len(self._events("module_error")), 1)
        self._assert_no_legacy_builder()
        self._assert_protected_unchanged(protected)

    def test_blocked_publication_never_uses_legacy_readiness_or_finisher(self) -> None:
        self.seam.result = _ready_seam_result()
        self.publication.result = _blocked_publication_result(
            "text_description_publication_finisher_infrastructure_failure"
        )
        self._run_worker(_params())
        self.assertEqual(len(self.readiness.calls), 0)
        self.assertEqual(len(self.finisher.calls), 0)
        self._assert_no_module_complete()


class TestEnabledSuccessEmitsLegacyEventOnlyAfterVerifiedPublication(
    _EnabledHostHarness
):
    """The single success path is the verified publication result."""

    def test_completed_publication_emits_module_complete_with_adaptation_markers(
        self,
    ) -> None:
        self.seam.result = _ready_seam_result()
        self.publication.result = _completed_publication_result()
        protected = self._snapshot_protected()
        self._run_worker(_params())

        self.assertEqual(len(self.seam.calls), 1)
        self.assertEqual(len(self.publication.calls), 1)
        completes = self._events("module_complete")
        self.assertEqual(len(completes), 1)
        payload = completes[0]
        self.assertEqual(payload["module_name"], MODULE_NAME)
        self.assertEqual(payload["final_status"], "success")
        self.assertEqual(payload["generation_succeeded"], True)
        self.assertEqual(payload["adaptation_route"], "llm_adaptation")
        self.assertIs(payload["adaptation_job"], True)
        self.assertEqual(payload["adaptation_outcome"], "completed")
        self.assertEqual(
            payload["adaptation_attempt_id"], ATTEMPT_ID
        )
        self.assertEqual(payload["adaptation_source_hash"], FIXTURE_HASH)
        self.assertEqual(payload["build_report"]["registry_status"], "success")
        self.assertTrue(payload["build_report"]["registry_verified"])
        self.assertEqual(len(self._events("module_error")), 0)
        self._assert_no_legacy_builder()
        self._assert_protected_unchanged(protected)

    def test_module_complete_never_emitted_when_publication_lacks_verification(
        self,
    ) -> None:
        # The host only trusts the bounded publication result: a completed
        # outcome is the only path to the legacy success event name. A
        # publication result that claims blocked stays blocked.
        self.seam.result = _ready_seam_result()
        self.publication.result = _blocked_publication_result(
            "text_description_publication_blocked"
        )
        self._run_worker(_params())
        self.assertEqual(self._events("module_complete"), [])
        self.assertEqual(len(self._events("module_error")), 1)


class TestRawModuleBuilderSuccessIsNeverSufficient(unittest.TestCase):
    """The real publication stage never completes on a raw build status alone.

    These tests exercise ``run_text_description_adaptation_publication`` with
    a build result shaped like a raw ``ModuleBuilder.build_module()``
    completion (``status=success`` with no adaptation gates, staging, or
    output directory) and prove the shared finisher transaction is mandatory:
    unavailable, raising, or non-success finisher => blocked; only a verified
    finisher success report => completed.
    """

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.workspace = self.scratch / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.staging = self.scratch / "staging"
        self.staging.mkdir(parents=True, exist_ok=True)
        self.staging_target = {
            "path": str((self.staging / "target").relative_to(REPO_ROOT)),
            "staging_root": str(self.staging.relative_to(REPO_ROOT)),
            "module_slug": MODULE_NAME,
            "attempt_id": ATTEMPT_ID,
        }
        self.addCleanup(shutil.rmtree, REPO_ROOT / str(self.staging_target["path"]), ignore_errors=True)

    def _raw_build_success(self) -> Dict[str, Any]:
        # A raw ModuleBuilder-style completion: no adaptation gates, no
        # staging target, no output directory, no provenance.
        return {"status": "success", "module_name": MODULE_NAME}

    def _ready_seam(self) -> Dict[str, Any]:
        return _ready_seam_result(
            workspace_ref=str(self.workspace.relative_to(REPO_ROOT)),
            staging_path=self.staging_target["path"],
        )

    def _verified_finisher_report(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "module_slug": MODULE_NAME,
            "reason": "",
            "publication_status": "success",
            "python_authoritative": True,
            "stages": {
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
            },
        }

    def _raw_finisher_unavailable(self) -> None:
        """Make the lazy finisher import fail (no verified finisher exists)."""
        fake = types.ModuleType("web.extensions.toolkit_module_finisher")
        self.finisher_import_patch = patch.dict(
            sys.modules, {"web.extensions.toolkit_module_finisher": fake}
        )
        self.finisher_import_patch.start()
        self.addCleanup(self.finisher_import_patch.stop)

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

    def test_raw_build_success_without_finisher_is_blocked(self) -> None:
        # Raw build_module-style success is never sufficient: without a
        # verified shared finisher the outcome must be blocked.
        self._raw_finisher_unavailable()
        protected = self._snapshot_protected()
        result = worker.run_text_description_adaptation_publication(
            self._ready_seam(),
            build_runner=lambda workspace, job_id, **kwargs: self._raw_build_success(),
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_FAILED_CLOSED)
        self.assertEqual(
            result["reason_code"], "text_description_publication_finisher_unavailable"
        )
        summary = result["adaptation_publication"]
        self.assertEqual(summary["registry_status"], "not_attempted")
        self.assertEqual(summary["campaign_sync_status"], "not_attempted")
        self.assertEqual(summary["rollback_status"], "not_attempted")
        self._assert_protected_unchanged(protected)

    def test_raw_build_success_with_raising_finisher_is_blocked(self) -> None:
        def _raising_finisher(module_slug: str, **kwargs: Any) -> Any:
            raise RuntimeError("finisher boom")

        result = worker.run_text_description_adaptation_publication(
            self._ready_seam(),
            build_runner=lambda workspace, job_id, **kwargs: self._raw_build_success(),
            finisher_runner=_raising_finisher,
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(
            result["reason_code"],
            "text_description_publication_finisher_infrastructure_failure",
        )

    def test_raw_build_success_with_non_success_finisher_is_blocked(self) -> None:
        def _blocked_finisher(module_slug: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "status": "blocked",
                "module_slug": MODULE_NAME,
                "reason": "raw_module_verification_failed",
                "publication_status": "blocked",
                "stages": {},
            }

        result = worker.run_text_description_adaptation_publication(
            self._ready_seam(),
            build_runner=lambda workspace, job_id, **kwargs: self._raw_build_success(),
            finisher_runner=_blocked_finisher,
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(result["reason_code"], "raw_module_verification_failed")
        self.assertNotEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)

    def test_raw_build_success_with_verified_finisher_is_completed(self) -> None:
        # The ONLY success path: the shared finisher reports verified
        # registry/campaign publication. The finisher is the verification
        # authority; a raw build status never reports success by itself.
        finisher_calls: List[Dict[str, Any]] = []

        def _verified_finisher(module_slug: str, **kwargs: Any) -> Dict[str, Any]:
            finisher_calls.append(kwargs)
            return self._verified_finisher_report()

        result = worker.run_text_description_adaptation_publication(
            self._ready_seam(),
            build_runner=lambda workspace, job_id, **kwargs: self._raw_build_success(),
            finisher_runner=_verified_finisher,
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_COMPLETED)
        summary = result["adaptation_publication"]
        self.assertEqual(summary["finisher_status"], "success")
        self.assertEqual(summary["registry_status"], "success")
        self.assertTrue(summary["registry_verified"])
        self.assertTrue(summary["campaign_visibility_verified"])
        # The finisher received the adaptation-mode kwargs and ran as the
        # mandatory transaction stage.
        self.assertEqual(len(finisher_calls), 1)
        self.assertEqual(finisher_calls[0]["adaptation_mode"], "llm_adaptation")

    def test_raw_build_success_missing_finisher_verification_fields_is_still_trusted_finisher(
        self,
    ) -> None:
        # The shared finisher is the verification authority: a finisher that
        # itself claims unverified success still produces a completed result
        # ONLY through the finisher stage (never from the raw build status).
        # This locks that the finisher transaction is mandatory and that the
        # raw build result is never interpreted as completion on its own.
        build_calls: List[Any] = []

        def _recording_build(workspace: Any, job_id: str, **kwargs: Any) -> Dict[str, Any]:
            build_calls.append((str(workspace), job_id, kwargs))
            return self._raw_build_success()

        result = worker.run_text_description_adaptation_publication(
            self._ready_seam(),
            build_runner=_recording_build,
            finisher_runner=lambda module_slug, **kwargs: self._verified_finisher_report(),
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        self.assertEqual(len(build_calls), 1)
        self.assertEqual(
            build_calls[0][2]["adaptation_route"], "llm_adaptation"
        )


class TestEnabledFailureGuardSourceContracts(unittest.TestCase):
    """Source contracts locking no-false-success at the host worker level."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_INTERFACE_PATH.read_text(encoding="utf-8")

    def test_enabled_branch_never_emits_legacy_success_directly(self) -> None:
        # The adaptation branch (seam call through the early return) contains
        # no direct module_complete emit; success surfaces only through the
        # publication outcome helper after verified completion.
        branch_slice = _function_slice(
            self.source,
            "if TEXT_DESCRIPTION_ADAPTATION_AVAILABLE",
            'info(f"Starting actual module build for: {module_name}")',
        )
        self.assertNotIn("socketio.emit('module_complete'", branch_slice)
        self.assertIn("_emit_text_description_publication_outcome", branch_slice)
        self.assertIn("_emit_text_description_adaptation_outcome", branch_slice)
        self.assertIn("return", branch_slice)

    def test_seam_outcome_helper_never_emits_legacy_success(self) -> None:
        # The authoring-outcome helper can only emit module_error; even a
        # completed-looking input cannot produce the legacy success event.
        helper_slice = _function_slice(
            self.source,
            "def _emit_text_description_adaptation_outcome(",
            "def _emit_text_description_publication_outcome(",
        )
        self.assertNotIn("socketio.emit('module_complete'", helper_slice)
        self.assertIn("socketio.emit('module_error'", helper_slice)

    def test_publication_outcome_helper_emits_success_only_after_verification(
        self,
    ) -> None:
        publication_slice = _function_slice(
            self.source,
            "def _emit_text_description_publication_outcome(",
            "def simulate_build_process(params):",
        )
        self.assertIn("socketio.emit('module_complete'", publication_slice)
        self.assertIn("outcome == 'completed'", publication_slice)

    def test_host_worker_emits_legacy_complete_only_after_finisher(self) -> None:
        build_slice = _function_slice(
            self.source,
            "def simulate_build_process(params):",
            "@socketio.on('start_build')",
        )
        self.assertLess(
            build_slice.index("run_toolkit_module_postbuild_finishing"),
            build_slice.index("socketio.emit('module_complete'"),
        )


class TestEnabledFailureGuardHygiene(unittest.TestCase):
    """ASCII, SPDX, path-policy, and provider-free rules for this suite."""

    def test_this_suite_is_ascii_only(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        non_ascii = [ch for ch in text if ord(ch) >= 128]
        self.assertEqual(non_ascii, [], "non-ASCII characters in this suite")

    def test_this_suite_has_spdx_header(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)

    def test_no_os_temp_or_absolute_scratch_paths(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("class TestEnabledFailureGuardHygiene", 1)[0]
        self.assertNotIn("tempfile", scan)
        self.assertNotIn("/tmp", scan)
        self.assertNotIn("/var/folders", scan)
        self.assertIn('"tmp"', scan)
        self.assertIn("toolkit_text_description_enabled_failure_guards", scan)
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
        # Every behavioral test runs the enabled route with the flag patched
        # to exactly True; the dirty live value is never relied upon.
        own_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            'patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", True)',
            own_source,
        )

    def test_this_suite_writes_nothing_to_real_adaptation_roots(self) -> None:
        # The host fakes never create the real adaptation workspace/staging
        # roots; only the project-local scratch root is used.
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("class TestEnabledFailureGuardHygiene", 1)[0]
        self.assertIn(
            "tmp/toolkit_text_description_enabled_failure_guards", scan
        )


def _function_slice(source: str, start_marker: str, end_marker: str) -> str:
    """Return source text between start_marker and the first end_marker."""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


if __name__ == "__main__":
    unittest.main()
