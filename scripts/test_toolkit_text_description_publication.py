# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the text-description staged publication transaction
(task 5.2 of toolkit-llm-adaptation-runtime-unification).

The suite locks the shared publication stage of the enabled text-description
build worker:

  * a ready task 5.1 authoring handoff is consumed and routed through the SAME
    ordered transaction used by uploaded adventures: staged packet/build
    output, schema/mechanical/readiness gates, semantic/report agreement,
    Markdown quality/summary, registry as the final stateful publication,
    campaign synchronization, post-write verification, and targeted rollback
    on failure;
  * completion is reported ONLY after the shared publication verification;
    every pre-publication or publication failure returns an explicit blocked
    outcome without registry or active-campaign mutation;
  * the finisher receives the same adaptation kwargs the upload job path
    forwards (adaptation_mode, adaptation_gates, adaptation_staging_target,
    adaptation_module_dir, adaptation_provenance, adaptation_artifact_
    workspace), so no second transaction is invented;
  * adaptation metadata and reports stay attached across the text job
    lifecycle (route decision, attempt/job/revision/source hash, Python-owned
    rights, world-context provenance, model/dossier/staging references, and
    bounded publication/rollback diagnostics);
  * protected module, registry, and campaign artifacts are never mutated by
    this stage (the packet builder and finisher run only through injected
    deterministic fakes; no module, registry, or campaign write is performed
    by the worker function itself).

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_text_description_publication/<uuid>/`` and are removed
deterministically via addCleanup. Real ``modules/world_registry.json`` and
``modules/campaign.json`` byte sentinels are checked before and after every
behavioral test. No OS-temporary scratch, no provider/network imports or
calls.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_text_adaptation_worker as worker
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_adaptation_staging import (
    DEFAULT_ADAPTATION_STAGING_ROOT,
    create_adaptation_staging_target,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_text_description_publication"
WORKER_MODULE_PATH = (
    REPO_ROOT / "web" / "extensions" / "toolkit_text_adaptation_worker.py"
)
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
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
ATTEMPT_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
JOB_ID = "text-job-0001"


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dossier() -> Dict[str, Any]:
    dossier = deepcopy(_load_fixture())
    dossier["source_hash"] = FIXTURE_HASH
    dossier["source_title"] = MODULE_NAME
    dossier["source_profile"] = "user_submitted_text_description"
    dossier["rights_class"] = RIGHTS_CLASS_USER_AUTHORED
    dossier["rights_basis"] = "user_submitted_text_description"
    dossier["rights_review_required"] = "not_required"
    dossier["rights_review_status"] = "approved"
    dossier["adaptation_mode"] = "llm_adaptation"
    return dossier


def _provenance(dossier_artifact_path: str) -> Dict[str, Any]:
    return {
        "attempt_metadata": {
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": JOB_ID,
        },
        "model_metadata": {"model": "gpt-5.6-luna", "provider": "openai"},
        "world_context_provenance": {
            "status": "unavailable",
            "fallback_status": "seed_data_unavailable",
            "read_only": True,
        },
        "source_hash": FIXTURE_HASH,
        "source_title": MODULE_NAME,
        "source_path": "",
        "source_format": "text_description",
        "dossier_artifact_path": dossier_artifact_path,
        "rights_class": RIGHTS_CLASS_USER_AUTHORED,
        "rights_basis": "user_submitted_text_description",
        "rights_review_required": "not_required",
        "rights_review_status": "approved",
    }


def _ready_seam_result(
    workspace_path: str,
    staging_target: Dict[str, Any],
    dossier_artifact_path: str = "adaptation_attempts/a1b2c3d4e5f60718293a4b5c6d7e8f90/dossier.json",
) -> Dict[str, Any]:
    provenance = _provenance(dossier_artifact_path)
    handoff: Dict[str, Any] = {
        "module_name": MODULE_NAME,
        "source_hash": FIXTURE_HASH,
        "source_title": MODULE_NAME,
        "dossier": _dossier(),
        "attempt": {
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": JOB_ID,
        },
        "rights": {
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
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
        "model_metadata": {"model": "gpt-5.6-luna", "provider": "openai"},
        "dossier_artifact_path": dossier_artifact_path,
        "workspace_path": workspace_path,
        "staging_target": dict(staging_target),
        "staging_target_path": str(staging_target.get("path") or ""),
        "staging_root": str(staging_target.get("staging_root") or ""),
        "provenance": provenance,
    }
    return {
        "contract_version": worker.TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION,
        "outcome": worker.TEXT_WORKER_OUTCOME_AUTHORING_READY,
        "status": worker.TEXT_WORKER_STATUS_READY,
        "route_decision": {
            "contract_version": "toolkit_adaptation_route_decision.v1",
            "status": "llm_adaptation",
            "route_selected": "llm_adaptation",
            "input_kind": "text_description",
            "module_name": MODULE_NAME,
            "source_hash": FIXTURE_HASH,
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "adaptation_artifacts_required": True,
            "fallback_allowed": False,
        },
        "adaptation_handoff": handoff,
        "diagnostics": [],
    }


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
        "adaptation_provenance": _provenance(
            "adaptation_attempts/a1b2c3d4e5f60718293a4b5c6d7e8f90/dossier.json"
        ),
        "adaptation_artifact_workspace": workspace_path,
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
        return deepcopy(self.result)


class _ProgressRecorder:
    def __init__(self) -> None:
        self.phases: list = []

    def __call__(self, phase: str, message: str) -> bool:
        self.phases.append(str(phase))
        return True


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


class _ProjectLocalScratchMixin:
    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.workspace = self.scratch / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def _workspace_ref(self) -> str:
        """Return the project-relative attempt workspace reference (task 2.2)."""
        return str(self.workspace.relative_to(REPO_ROOT))

    def _reserve_staging_target(self) -> Dict[str, Any]:
        relative_staging_root = str(
            (self.scratch / "staging").relative_to(REPO_ROOT)
        )
        target = create_adaptation_staging_target(
            FIXTURE_HASH,
            attempt_id=ATTEMPT_ID,
            attempt_number=1,
            revision_number=0,
            job_id=JOB_ID,
            source_path="",
            module_slug=MODULE_NAME,
            staging_root=relative_staging_root,
        )
        self.addCleanup(
            shutil.rmtree, REPO_ROOT / str(target["path"]), ignore_errors=True
        )
        return target


class TestPublicationHandoffValidation(_ProjectLocalScratchMixin, unittest.TestCase):
    """Invalid/missing ready handoffs fail closed before any runner call."""

    def test_non_mapping_result_is_blocked(self) -> None:
        result = worker.run_text_description_adaptation_publication(None)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(
            result["reason_code"], "text_description_publication_handoff_invalid"
        )
        self.assertEqual(result["adaptation_publication"]["registry_status"], "not_attempted")
        self.assertEqual(result["adaptation_publication"]["campaign_sync_status"], "not_attempted")

    def test_blocked_seam_result_is_blocked_without_handoff(self) -> None:
        seam_result = {
            "contract_version": worker.TEXT_DESCRIPTION_WORKER_SEAM_CONTRACT_VERSION,
            "outcome": worker.TEXT_WORKER_OUTCOME_BLOCKED,
            "status": worker.TEXT_WORKER_STATUS_FAILED_CLOSED,
            "reason_code": "adaptation_route_authority_invalid",
            "diagnostics": [],
            "route_decision": {"status": "llm_adaptation"},
        }
        result = worker.run_text_description_adaptation_publication(seam_result)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(
            result["reason_code"], "text_description_publication_handoff_invalid"
        )

    def test_missing_handoff_fields_fail_closed(self) -> None:
        base = _ready_seam_result(
            self._workspace_ref(), self._reserve_staging_target()
        )
        handoff = base["adaptation_handoff"]
        for field, expected_code in (
            ("dossier", "text_description_publication_dossier_missing"),
            ("staging_target", "text_description_publication_staging_missing"),
            ("module_name", "text_description_publication_handoff_invalid"),
            ("workspace_path", "text_description_publication_handoff_invalid"),
        ):
            with self.subTest(field=field):
                broken = deepcopy(base)
                del broken["adaptation_handoff"][field]
                result = worker.run_text_description_adaptation_publication(broken)
                self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
                self.assertEqual(result["reason_code"], expected_code)
                self.assertEqual(
                    result["adaptation_publication"]["registry_status"], "not_attempted"
                )

    def test_empty_staging_target_path_is_blocked(self) -> None:
        base = _ready_seam_result(
            self._workspace_ref(), self._reserve_staging_target()
        )
        broken = deepcopy(base)
        broken["adaptation_handoff"]["staging_target"] = {"path": ""}
        broken["adaptation_handoff"]["staging_target_path"] = ""
        result = worker.run_text_description_adaptation_publication(broken)
        self.assertEqual(
            result["reason_code"], "text_description_publication_staging_missing"
        )

    def test_absolute_workspace_path_is_blocked(self) -> None:
        base = _ready_seam_result(
            self._workspace_ref(), self._reserve_staging_target()
        )
        broken = deepcopy(base)
        broken["adaptation_handoff"]["workspace_path"] = "/etc/passwd"
        result = worker.run_text_description_adaptation_publication(broken)
        self.assertEqual(
            result["reason_code"], "text_description_publication_workspace_invalid"
        )

    def test_ready_handoff_result_validates_round_trip(self) -> None:
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self._reserve_staging_target()),
            build_runner=_FakeBuildRunner({"status": "failed"}),
        )
        self.assertTrue(worker.validate_text_description_publication_result(result)["valid"])


class TestPublicationStagedBuildGate(
    _ProjectLocalScratchMixin, _ProtectedArtifactMixin, unittest.TestCase
):
    """Staged build/gate failures block before the finisher and publication."""

    def test_blocked_build_status_never_reaches_finisher(self) -> None:
        before = self._snapshot_protected()
        fake_finisher = _FakeFinisherRunner(_success_finisher_report())
        fake_build = _FakeBuildRunner(
            {
                "status": "blocked",
                "stage": "adaptation_gates",
                "error": "adaptation_gates_blocked",
                "adaptation_gates": {
                    "status": "blocked",
                    "playable_status": "blocked",
                },
            }
        )
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self._reserve_staging_target()),
            build_runner=fake_build,
            finisher_runner=fake_finisher,
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
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
        self._assert_protected_unchanged(before)

    def test_build_infrastructure_failure_is_blocked(self) -> None:
        before = self._snapshot_protected()
        fake_finisher = _FakeFinisherRunner(_success_finisher_report())
        fake_build = _FakeBuildRunner(None, error=RuntimeError("boom"))
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self._reserve_staging_target()),
            build_runner=fake_build,
            finisher_runner=fake_finisher,
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(
            result["reason_code"],
            "text_description_publication_build_infrastructure_failure",
        )
        self.assertEqual(len(fake_finisher.calls), 0)
        self._assert_protected_unchanged(before)

    def test_non_mapping_build_result_is_blocked(self) -> None:
        fake_build = _FakeBuildRunner(None)
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self._reserve_staging_target()),
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(_success_finisher_report()),
        )
        self.assertEqual(
            result["reason_code"], "text_description_publication_build_result_missing"
        )

    def test_progress_stops_at_build_phase_on_gate_failure(self) -> None:
        recorder = _ProgressRecorder()
        fake_build = _FakeBuildRunner({"status": "failed", "stage": "build"})
        worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self._reserve_staging_target()),
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(_success_finisher_report()),
            progress_callback=recorder,
        )
        self.assertIn("adaptation_build", recorder.phases)
        self.assertNotIn("adaptation_readiness", recorder.phases)
        self.assertNotIn("adaptation_completed", recorder.phases)


class TestPublicationSharedTransaction(
    _ProjectLocalScratchMixin, _ProtectedArtifactMixin, unittest.TestCase
):
    """Ready handoff routes through the same transaction as uploaded adventures."""

    def _run_success(self, build_result: Optional[Dict[str, Any]] = None):
        fake_finisher = _FakeFinisherRunner(_success_finisher_report())
        if build_result is None:
            build_result = _success_build_result(
                self.staging_target, self._workspace_ref()
            )
        fake_build = _FakeBuildRunner(build_result)
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self.staging_target),
            build_runner=fake_build,
            finisher_runner=fake_finisher,
        )
        return result, fake_build, fake_finisher

    def setUp(self) -> None:
        super().setUp()
        self.staging_target = self._reserve_staging_target()

    def test_full_success_reports_completed_after_verification(self) -> None:
        before = self._snapshot_protected()
        result, fake_build, fake_finisher = self._run_success()
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        self.assertEqual(result["status"], worker.TEXT_WORKER_STATUS_COMPLETED)
        self.assertEqual(result["reason_code"], "text_description_adaptation_published")
        self.assertEqual(result["module_name"], MODULE_NAME)
        summary = result["adaptation_publication"]
        self.assertEqual(summary["build_status"], "success")
        self.assertEqual(summary["finisher_status"], "success")
        self.assertEqual(summary["gate_playable_status"], "pass")
        self.assertEqual(summary["registry_status"], "success")
        self.assertTrue(summary["registry_verified"])
        self.assertEqual(summary["campaign_sync_status"], "success")
        self.assertTrue(summary["campaign_visibility_verified"])
        self.assertEqual(summary["rollback_status"], "not_needed")
        self.assertTrue(summary["python_authoritative"])
        self.assertEqual(len(fake_build.calls), 1)
        self.assertEqual(len(fake_finisher.calls), 1)
        self._assert_protected_unchanged(before)

    def test_packet_build_receives_upload_handoff_kwargs(self) -> None:
        _, fake_build, _ = self._run_success()
        _workspace, _job_id, kwargs = fake_build.calls[0]
        self.assertEqual(_job_id, JOB_ID)
        self.assertEqual(kwargs["adaptation_route"], "llm_adaptation")
        self.assertEqual(kwargs["adaptation_dossier"]["source_hash"], FIXTURE_HASH)
        self.assertEqual(
            kwargs["adaptation_provenance"]["source_hash"], FIXTURE_HASH
        )
        self.assertEqual(
            kwargs["adaptation_staging_target"]["path"],
            self.staging_target["path"],
        )
        self.assertEqual(kwargs["adaptation_staging_root"], self.staging_target["staging_root"])

    def test_finisher_receives_the_upload_finisher_kwargs(self) -> None:
        _, _, fake_finisher = self._run_success()
        module_slug, kwargs = fake_finisher.calls[0]
        self.assertEqual(module_slug, MODULE_NAME)
        self.assertEqual(kwargs["strict"], True)
        self.assertEqual(kwargs["adaptation_mode"], "llm_adaptation")
        self.assertEqual(kwargs["adaptation_gates"]["playable_status"], "pass")
        self.assertEqual(
            kwargs["adaptation_staging_target"]["path"],
            self.staging_target["path"],
        )
        self.assertEqual(
            kwargs["adaptation_module_dir"], self.staging_target["path"]
        )
        self.assertEqual(
            kwargs["adaptation_provenance"]["source_hash"], FIXTURE_HASH
        )
        self.assertEqual(kwargs["adaptation_artifact_workspace"], self._workspace_ref())
        # Exactly the kwargs _run_homebrew_finisher forwards for uploads.
        self.assertEqual(
            sorted(
                k
                for k in kwargs
                if k.startswith("adaptation_")
            ),
            [
                "adaptation_artifact_workspace",
                "adaptation_gates",
                "adaptation_mode",
                "adaptation_module_dir",
                "adaptation_provenance",
                "adaptation_staging_target",
            ],
        )

    def test_metadata_continuity_through_completion(self) -> None:
        result, _, _ = self._run_success()
        handoff = result["adaptation_handoff"]
        self.assertEqual(handoff["module_name"], MODULE_NAME)
        self.assertEqual(handoff["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff["attempt"]["attempt_id"], ATTEMPT_ID)
        self.assertEqual(handoff["attempt"]["job_id"], JOB_ID)
        self.assertEqual(handoff["attempt"]["revision_number"], 0)
        self.assertEqual(
            handoff["rights"]["rights_class"], RIGHTS_CLASS_USER_AUTHORED
        )
        self.assertEqual(
            handoff["world_context"]["fallback_status"], "seed_data_unavailable"
        )
        self.assertEqual(
            handoff["staging_target_path"], self.staging_target["path"]
        )
        self.assertIn("dossier_artifact_path", handoff)
        route = result["route_decision"]
        self.assertEqual(route["status"], "llm_adaptation")
        self.assertEqual(route["source_hash"], FIXTURE_HASH)
        self.assertFalse(route.get("fallback_allowed"))
        # Host emission contract fields are present.
        self.assertEqual(handoff["attempt"]["attempt_id"], ATTEMPT_ID)
        self.assertEqual(handoff["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff["workspace_path"], self._workspace_ref())
        self.assertEqual(handoff["staging_target_path"], self.staging_target["path"])
        self.assertTrue(worker.validate_text_description_publication_result(result)["valid"])

    def test_progress_phases_cover_the_shared_transaction(self) -> None:
        recorder = _ProgressRecorder()
        fake_build = _FakeBuildRunner(
            _success_build_result(self.staging_target, self._workspace_ref())
        )
        worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self.staging_target),
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(_success_finisher_report()),
            progress_callback=recorder,
        )
        self.assertIn("adaptation_build", recorder.phases)
        self.assertIn("adaptation_readiness", recorder.phases)
        self.assertIn("adaptation_completed", recorder.phases)

    def test_progress_callback_exceptions_never_block_publication(self) -> None:
        def _exploding(phase: str, message: str) -> bool:
            raise RuntimeError("progress boom")

        result, _, _ = self._run_success()
        fake_build = _FakeBuildRunner(
            _success_build_result(self.staging_target, self._workspace_ref())
        )
        result2 = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self.staging_target),
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(_success_finisher_report()),
            progress_callback=_exploding,
        )
        self.assertEqual(result2["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_COMPLETED)


class TestPublicationFinisherFailures(
    _ProjectLocalScratchMixin, _ProtectedArtifactMixin, unittest.TestCase
):
    """Post-build publication failures stay blocked with rollback facts."""

    def setUp(self) -> None:
        super().setUp()
        self.staging_target = self._reserve_staging_target()

    def test_finisher_blocked_carries_registry_campaign_rollback_facts(self) -> None:
        before = self._snapshot_protected()
        fake_build = _FakeBuildRunner(
            _success_build_result(self.staging_target, self._workspace_ref())
        )
        fake_finisher = _FakeFinisherRunner(_failed_finisher_report())
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self.staging_target),
            build_runner=fake_build,
            finisher_runner=fake_finisher,
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
        self._assert_protected_unchanged(before)

    def test_finisher_infrastructure_failure_is_blocked(self) -> None:
        fake_build = _FakeBuildRunner(
            _success_build_result(self.staging_target, self._workspace_ref())
        )
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self.staging_target),
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(None, error=RuntimeError("boom")),
        )
        self.assertEqual(result["outcome"], worker.TEXT_WORKER_OUTCOME_BLOCKED)
        self.assertEqual(
            result["reason_code"],
            "text_description_publication_finisher_infrastructure_failure",
        )

    def test_non_mapping_finisher_report_is_blocked(self) -> None:
        fake_build = _FakeBuildRunner(
            _success_build_result(self.staging_target, self._workspace_ref())
        )
        result = worker.run_text_description_adaptation_publication(
            _ready_seam_result(self._workspace_ref(), self.staging_target),
            build_runner=fake_build,
            finisher_runner=_FakeFinisherRunner(None),
        )
        self.assertEqual(
            result["reason_code"], "text_description_publication_finisher_result_missing"
        )


class TestPublicationContractRoundTrip(unittest.TestCase):
    """Result contract validation and tamper rejection."""

    def test_tamper_rejection(self) -> None:
        completed = {
            "contract_version": worker.TEXT_PUBLICATION_CONTRACT_VERSION,
            "outcome": worker.TEXT_WORKER_OUTCOME_COMPLETED,
            "status": worker.TEXT_WORKER_STATUS_COMPLETED,
            "module_name": MODULE_NAME,
            "route_decision": {},
            "adaptation_handoff": {"attempt": {"attempt_id": ATTEMPT_ID}},
            "adaptation_publication": {"finisher_status": "success"},
            "reason_code": "text_description_adaptation_published",
            "diagnostics": [],
        }
        self.assertTrue(worker.validate_text_description_publication_result(completed)["valid"])
        for mutation in (
            {"contract_version": "other"},
            {"outcome": "blocked"},
            {"status": "ready"},
            {"module_name": "../escape"},
            {"adaptation_publication": None},
            {"adaptation_handoff": None},
            {"reason_code": ""},
        ):
            with self.subTest(mutation=mutation):
                tampered = deepcopy(completed)
                for key, value in mutation.items():
                    tampered[key] = value
                self.assertFalse(
                    worker.validate_text_description_publication_result(tampered)["valid"]
                )


class TestPublicationHygiene(unittest.TestCase):
    """Source and path hygiene for the publication stage."""

    def test_worker_module_remains_ascii_and_spdx(self) -> None:
        source = WORKER_MODULE_PATH.read_text(encoding="utf-8")
        try:
            source.encode("ascii")
        except UnicodeEncodeError as exc:
            self.fail(f"non-ASCII bytes in worker module: {exc}")
        self.assertIn("SPDX-FileCopyrightText", source)
        self.assertIn("TEXT_PUBLICATION_CONTRACT_VERSION", source)
        self.assertIn("run_text_description_adaptation_publication", source)
        self.assertIn("validate_text_description_publication_result", source)

    def test_worker_module_uses_lazy_transaction_imports_only(self) -> None:
        source = WORKER_MODULE_PATH.read_text(encoding="utf-8")
        # The publication function must import the shared transaction helpers
        # lazily inside the function body; the module top-level never imports
        # the packet builder or finisher (authoring stays side-effect free).
        import re

        top = source.split("def run_text_description_adaptation_publication(")[0]
        self.assertNotIn("toolkit_homebrew_packet_builder", top)
        self.assertNotIn("toolkit_module_finisher", top)
        function_body = source.split("def run_text_description_adaptation_publication(")[1]
        self.assertIn("from web.extensions.toolkit_homebrew_packet_builder import", function_body)
        self.assertIn("from web.extensions.toolkit_module_finisher import", function_body)

    def test_this_suite_uses_only_project_local_scratch(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        scan_source = source.split("class TestPublicationHygiene", 1)[0]
        self.assertNotIn("tempfile", scan_source)
        self.assertNotIn("/tmp", scan_source)
        self.assertIn("tmp/toolkit_text_description_publication", scan_source)

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


if __name__ == "__main__":
    unittest.main()
