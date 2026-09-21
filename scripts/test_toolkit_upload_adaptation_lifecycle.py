# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free upload lifecycle and adaptation metadata-attachment tests
(task 4.3 of toolkit-llm-adaptation-runtime-unification).

The suite drives
``web/routes/toolkit_homebrew_routes._run_homebrew_build_job`` directly with
patched adapter/authoring/staging/packet-build/readiness/finisher seams and
verifies that the existing upload lifecycle stays intact while adaptation
metadata and reports remain attached and identity-consistent through every
job transition:

  * stage-order and metadata continuity for an enabled adaptation build
    (building -> build_completed -> readiness -> ready_for_finishing ->
    finishing -> publishability_audit -> completed/adaptation_completed);
  * the finishing-only continuation (retry-from-finishing style) reattaches
    the captured adaptation build handoff so the finisher keeps identity,
    gates, staging, and provenance;
  * the legacy rebuild/overwrite-confirmation path keeps its exact payload
    behavior and gains no adaptation keys;
  * a successful adaptation build never reports success before the readiness
    and publication verification gates complete, and failures leave no
    misleading registry/campaign state;
  * Python-owned rights, route authority, source identity, and world-context
    provenance are never relabeled or dropped by downstream transitions.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_upload_adaptation_lifecycle/<uuid>/`` and are removed via
addCleanup. No OS temp directory, no provider/network calls, and no real
``modules/``, registry, campaign, or runtime mutation: the packet build,
readiness, finisher, authoring, rebuild-prep, and staging seams are all
injected fakes, and the live ``model_config.ENABLE_LLM_ADAPTATION`` operator
value is never relied on (every behavioral test patches it explicitly).
"""

import ast
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.routes.toolkit_homebrew_routes as routes_module
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LLM_ADAPTATION,
    ROUTE_DECISION_STATUS_ADAPTATION,
)
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_adaptation_world_context import build_world_context_provenance
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
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_upload_adaptation_lifecycle"
ROUTES_MODULE_PATH = REPO_ROOT / "web" / "routes" / "toolkit_homebrew_routes.py"
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
REGISTRY_SENTINEL = REPO_ROOT / "modules" / "world_registry.json"
CAMPAIGN_SENTINEL = REPO_ROOT / "modules" / "campaign.json"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

EXPECTED_MODULE_NAME = "Sunken_Lighthouse"
ATTEMPT_ID = "lifecycle-test-attempt"

_READINESS_TRANSITION = "ready_for_finishing"


def _load_fixture_dossier() -> Dict[str, Any]:
    with FIXTURE_DOSSIER_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _make_workspace(scratch: Path, source_hash: str) -> Path:
    """Create an approved upload workspace inside the scratch root."""
    ws = scratch / "workspace"
    ensure_workspace_placeholders(ws)
    files = get_workspace_files(ws)
    packet: Dict[str, Any] = {
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
        "locations": [
            {
                "name": "Keeper's Quarters",
                "location": "tower",
                "description": "Rusted spyglass.",
            }
        ],
        "npc_seeds": [
            {"name": "Keeper Elowen", "role": "witness", "description": "Haunted keeper."}
        ],
        "encounter_seeds": [
            {"name": "Drowned Bell Guard", "description": "Undead guardian."}
        ],
        "assumptions": ["Fixture packet for the upload lifecycle tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }
    persist_normalized_packet_artifact(ws, packet)
    snapshot = build_review_snapshot(
        job_id="lifecycle-job",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    persist_review_snapshot_artifact(ws, snapshot)
    files["source_original"].write_text(FIXTURE_TEXT, encoding="utf-8")
    # Placeholder reports required by the real finisher-entry validator when a
    # test lets the packet build return success.
    for name in ("build_result", "readiness_validation_report", "readiness_audit_report"):
        files[name].write_text("{}", encoding="utf-8")
    return ws


def _register_job(
    job_id: str,
    workspace: Path,
    *,
    source_kind: str = "markdown",
    rights_class: str = SOURCE_RIGHTS_USER_AUTHORED,
    expected_module_name: str = EXPECTED_MODULE_NAME,
    status: str = "building",
) -> None:
    with routes_module._jobs_lock:
        routes_module._jobs[job_id] = {
            "job_id": job_id,
            "job_type": "toolkit_homebrew_md_ingest",
            "status": status,
            "stage": "build",
            "pipeline_status": "building",
            "artifact_workspace": str(workspace),
            "source_kind": source_kind,
            "source_filename": "fixture.md",
            "source_rights_class": rights_class,
            "review_decision": REVIEW_DECISION_APPROVE,
            "expected_module_name": expected_module_name,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }


def _route_authority() -> Dict[str, Any]:
    return {
        "selected_route": BUILD_MODE_LLM_ADAPTATION,
        "fallback_allowed": False,
        "route_authority": "adaptation_selected_authoritative",
        "adaptation_artifacts_required": True,
    }


def _ready_authoring_result(job_id: str, source_hash: str) -> Dict[str, Any]:
    """Build a deterministic ready authoring adapter result for the seam."""
    dossier = _load_fixture_dossier()
    dossier["source_hash"] = source_hash
    dossier["source_title"] = "Sunken Lighthouse"
    dossier["source_profile"] = dossier.get("source_profile") or "unknown"
    dossier["rights_class"] = RIGHTS_CLASS_USER_AUTHORED
    dossier["rights_basis"] = "user_authored_uploaded_adventure"
    dossier["rights_review_required"] = False
    dossier["rights_review_status"] = "not_required"
    dossier["adaptation_mode"] = BUILD_MODE_LLM_ADAPTATION
    world = build_world_context_provenance(None)
    return {
        "contract_version": "toolkit_adaptation_authoring_adapter.v1",
        "status": "ready",
        "outcome": "handoff_ready",
        "ok": True,
        "input_kind": "upload_markdown",
        "route": _route_authority(),
        "attempt": {
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": job_id,
        },
        "source_identity": {
            "source_title": "Sunken Lighthouse",
            "source_hash": source_hash,
            "source_path": "tmp/lifecycle/workspace/source_original.md",
        },
        "rights": {
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "rights_basis": "user_authored_uploaded_adventure",
            "rights_review_required": False,
            "rights_review_status": "not_required",
            "python_owned": True,
            "provider_may_change": False,
        },
        "world_context": world,
        "staging": {"reserved": False, "isolated": True},
        "model_metadata": {"provider": "openai", "model": "gpt-5.6-luna"},
        "authoring": {
            "authoring_attempted": True,
            "authoring_status": "ready",
            "authoring_ok": True,
            "attempt_id": ATTEMPT_ID,
            "dossier_artifact_path": "tmp/lifecycle/attempts/%s/adaptation_dossier.json" % ATTEMPT_ID,
            "dossier_artifact_persisted": True,
            "failure_artifact_path": None,
            "failure_artifact_persisted": False,
            "proposal_ledger_path": None,
            "proposal_ledger_persisted": False,
            "proposal_status": None,
            "proposal_count": 0,
            "idempotent_replay": False,
            "diagnostics": [],
            "safe_class": "none",
            "reason_code": "none",
            "revision_eligible": False,
            "retryable": False,
            "terminal": False,
        },
        "dossier": dossier,
        "guards": {
            "module_builder_allowed": True,
            "module_builder_started": False,
            "publication_started": False,
            "registry_mutated": False,
            "completed_module_artifacts": [],
            "selected_route_authoritative": True,
        },
        "diagnostics": [],
    }


def _fake_staging_target(
    source_hash: str,
    *,
    attempt_id: Optional[str] = None,
    attempt_number: int = 1,
    revision_number: int = 0,
    job_id: str = "",
    source_path: str = "",
    module_slug: str = "",
    staging_root: str = "tmp/adaptation-staging",
) -> Dict[str, Any]:
    """Deterministic reserved staging target fake (never touches the disk)."""
    resolved_attempt_id = attempt_id or ATTEMPT_ID
    relative_path = "%s/%s/revision_%03d" % (
        staging_root,
        resolved_attempt_id,
        revision_number,
    )
    return {
        "contract_version": "toolkit_adaptation_staging.v1",
        "target_kind": "staging",
        "stage_id": "%s:revision_%03d" % (resolved_attempt_id, revision_number),
        "attempt_id": resolved_attempt_id,
        "attempt_number": attempt_number,
        "revision_number": revision_number,
        "source_hash": source_hash,
        "source_path": source_path,
        "module_slug": module_slug,
        "staging_root": staging_root,
        "path": relative_path,
        "output_directory": relative_path,
        "completion_state": "reserved",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "metadata_path": relative_path + "/staging_metadata.json",
    }


def _adaptation_build_result(
    job_id: str, workspace: Path, source_hash: str
) -> Dict[str, Any]:
    """Deterministic successful packet-build result with adaptation handoff."""
    return {
        "status": "success",
        "stage": "build",
        "job_id": job_id,
        "module_name": EXPECTED_MODULE_NAME,
        "output_directory": str(workspace / "staged"),
        "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
        "adaptation_gates": {
            "status": "pass",
            "playable_status": "pass",
            "candidate_eligible": True,
            "gate_status": "pass",
        },
        "staging_target": _fake_staging_target(
            source_hash,
            attempt_id=ATTEMPT_ID,
            module_slug=EXPECTED_MODULE_NAME,
            job_id=job_id,
        ),
        "adaptation_provenance": {
            "contract_version": "toolkit_adaptation_provenance.v1",
            "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
            "adaptation_status": "adapted",
            "source_hash": source_hash,
            "source_title": "Sunken Lighthouse",
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "rights_basis": "user_authored_uploaded_adventure",
            "rights_review_required": False,
            "rights_review_status": "not_required",
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "revision_number": 0,
            "world_context_provenance": build_world_context_provenance(None),
            "model_metadata": {"provider": "openai", "model": "gpt-5.6-luna"},
        },
        "adaptation_artifact_workspace": str(workspace),
    }


class _FakePacketBuild:
    """Records packet-builder kwargs and returns a configurable result."""

    def __init__(self, result: Optional[Dict[str, Any]] = None) -> None:
        self.result = result
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, workspace: Any, job_id: str, **kwargs: Any) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "workspace": str(workspace),
            "job_id": job_id,
        }
        record.update(dict(kwargs))
        self.calls.append(record)
        if self.result is not None:
            return dict(self.result)
        return {
            "status": "failed",
            "stage": "build",
            "error": "fixture_stop",
            "job_id": job_id,
        }


class _FakeReadiness:
    """Readiness gate fake with a configurable outcome status."""

    def __init__(self, status: str = _READINESS_TRANSITION) -> None:
        self.status = status

    def __call__(
        self, artifact_workspace: Any, job_id: str, state_callback: Any = None
    ) -> Dict[str, Any]:
        if state_callback:
            state_callback(
                self.status,
                {"status": self.status, "module_name": EXPECTED_MODULE_NAME},
            )
        return {
            "status": self.status,
            "module_name": EXPECTED_MODULE_NAME,
        }


class _FakeFinisher:
    """Finisher fake with adaptation publication verification."""

    def __init__(self, result: Optional[Dict[str, Any]] = None) -> None:
        self.result = result
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def _default_result(self, module_slug: str) -> Dict[str, Any]:
        return {
            "status": "completed",
            "ready_status": "pass",
            "publishable_status": "pass",
            "module_name": module_slug,
            "publication_status": "completed",
            "terminal_status": "completed",
            "registry": {"status": "completed", "verified": True},
            "campaign_sync": {"status": "deferred"},
            "registry_verified": True,
            "python_authoritative": True,
            "llm_publication_override": False,
        }

    def __call__(
        self, module_slug: str, build_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        self.calls.append((module_slug, dict(build_result or {})))
        if self.result is not None:
            return dict(self.result)
        return self._default_result(module_slug)


class _FakeRebuildPrep:
    """Rebuild-prep fake returning success and recording calls."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, module_name: str, overwrite_policy: str) -> Dict[str, Any]:
        self.calls.append({"module_name": module_name, "overwrite_policy": overwrite_policy})
        return {
            "status": "success",
            "module_name": module_name,
            "overwrite_policy": overwrite_policy,
            "backup_dir": "tmp/lifecycle/backup/%s" % module_name,
        }


class _LifecycleScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.job_ids: List[str] = []
        self.addCleanup(self._clear_jobs)

    def _clear_jobs(self) -> None:
        with routes_module._jobs_lock:
            for job_id in self.job_ids:
                routes_module._jobs.pop(job_id, None)
            routes_module._active_job_id = None

    def _snapshot_job(self, job_id: str) -> Dict[str, Any]:
        with routes_module._jobs_lock:
            job = routes_module._jobs.get(job_id)
            return dict(job) if job is not None else {}

    def _run_build(self, job_id: str, build_options: Optional[Dict[str, Any]] = None) -> None:
        routes_module._run_homebrew_build_job(job_id, dict(build_options or {}))

    def _capture_transitions(
        self, job_id: str
    ) -> Tuple[List[Tuple[str, Dict[str, Any]]], Any]:
        """Wrap ``_set_job_state`` to record (status, snapshot) per transition.

        Returns ``(captured, original)`` so callers can restore the seam when
        a test needs to run a second build over the same job.
        """
        captured: List[Tuple[str, Dict[str, Any]]] = []
        original = routes_module._set_job_state

        def _wrapped(target_job_id: str, status: str, **fields: Any) -> None:
            result = original(target_job_id, status, **fields)
            with routes_module._jobs_lock:
                job = routes_module._jobs.get(target_job_id)
                captured.append((status, dict(job) if job is not None else {}))
            return result

        patch.object(routes_module, "_set_job_state", side_effect=_wrapped).start()
        return captured, original


def _assert_adaptation_markers(job: Dict[str, Any]) -> None:
    """Assert the bounded adaptation marker set is present and attached."""
    assert job.get("adaptation_job") is True
    assert job.get("adaptation_mode") == BUILD_MODE_LLM_ADAPTATION
    decision = job.get("adaptation_route_decision") or {}
    assert decision.get("status") == ROUTE_DECISION_STATUS_ADAPTATION
    assert job.get("adaptation_attempt_id") == ATTEMPT_ID
    assert job.get("adaptation_source_hash") == FIXTURE_HASH
    assert job.get("adaptation_source_kind") == "upload_markdown"
    world = job.get("adaptation_world_context") or {}
    assert "world_seed_status" in world
    assert world.get("read_only") is True
    staging = job.get("adaptation_staging_target") or {}
    assert staging.get("completion_state") == "reserved"


class TestStageTransitionMetadataContinuity(_LifecycleScratchMixin, unittest.TestCase):
    """Adaptation metadata stays attached and identity-consistent through every
    stage transition of the enabled upload build."""

    def test_markers_survive_and_identity_is_consistent(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            _adaptation_build_result("route-lifecycle-job", workspace, FIXTURE_HASH)
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher()
        job_id = "route-lifecycle-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_ready_authoring_result(job_id, FIXTURE_HASH),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            captured, _original = self._capture_transitions(job_id)
            self._run_build(job_id)

        self.assertGreaterEqual(len(captured), 7)
        raw_statuses = [status for status, _snapshot in captured]
        # The existing lifecycle order is preserved for adaptation jobs.
        self.assertIn("building", raw_statuses)
        self.assertIn("build_completed", raw_statuses)
        self.assertIn("ready_for_finishing", raw_statuses)
        self.assertIn("finishing", raw_statuses)
        self.assertIn("publishability_audit", raw_statuses)
        self.assertIn("completed", raw_statuses)
        order_indexes = [
            raw_statuses.index("building"),
            raw_statuses.index("build_completed"),
            raw_statuses.index("ready_for_finishing"),
            raw_statuses.index("finishing"),
            raw_statuses.index("publishability_audit"),
            raw_statuses.index("completed"),
        ]
        self.assertEqual(order_indexes, sorted(order_indexes))

        for _status, snapshot in captured:
            _assert_adaptation_markers(snapshot)

        # Identity consistency: the route decision and source identity are the
        # same object content at every transition (no-downgrade, no relabel).
        first_decision = dict(captured[0][1]["adaptation_route_decision"])
        first_world = dict(captured[0][1]["adaptation_world_context"])
        first_staging = dict(captured[0][1]["adaptation_staging_target"])
        for _status, snapshot in captured[1:]:
            self.assertEqual(snapshot["adaptation_route_decision"], first_decision)
            self.assertEqual(snapshot["adaptation_source_hash"], FIXTURE_HASH)
            self.assertEqual(snapshot["adaptation_world_context"], first_world)
            self.assertEqual(
                snapshot["adaptation_staging_target"].get("path"),
                first_staging.get("path"),
            )
            decision_rights = (snapshot["adaptation_route_decision"] or {}).get(
                "rights"
            ) or {}
            self.assertEqual(
                decision_rights.get("rights_class"), RIGHTS_CLASS_USER_AUTHORED
            )

        # The build handoff is captured from the successful build and retained.
        build_snapshot = next(
            snapshot
            for status, snapshot in captured
            if status == "build_completed"
        )
        handoff = build_snapshot.get("adaptation_build_handoff") or {}
        self.assertEqual(handoff.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION)
        self.assertIn("adaptation_gates", handoff)
        self.assertIn("adaptation_staging_target", handoff)
        self.assertIn("adaptation_provenance", handoff)
        self.assertIn("adaptation_module_dir", handoff)
        self.assertIn("adaptation_artifact_workspace", handoff)

        # Terminal state is the pre-existing adaptation completion mapping and
        # only appears after the finisher publication verification passed.
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "adaptation_completed")
        self.assertEqual(fake_finisher.calls[0][0], EXPECTED_MODULE_NAME)

    def test_legacy_flow_keeps_stage_order_without_adaptation_keys(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            {
                "status": "success",
                "module_name": EXPECTED_MODULE_NAME,
                "output_directory": str(self.scratch / "staged"),
            }
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher()
        job_id = "route-legacy-lifecycle-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", False
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            captured, _original = self._capture_transitions(job_id)
            self._run_build(job_id)

        raw_statuses = [status for status, _snapshot in captured]
        self.assertIn("build_completed", raw_statuses)
        self.assertIn("ready_for_finishing", raw_statuses)
        self.assertIn("completed", raw_statuses)
        for _status, snapshot in captured:
            for key in (
                "adaptation_job",
                "adaptation_mode",
                "adaptation_route_decision",
                "adaptation_attempt_id",
                "adaptation_build_handoff",
            ):
                self.assertNotIn(key, snapshot)
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "completed")


class TestFinishingOnlyContinuationPreservesHandoff(
    _LifecycleScratchMixin, unittest.TestCase
):
    """The finishing-only continuation reattaches the adaptation handoff."""

    def test_isolated_continuation_reattaches_handoff(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_finisher = _FakeFinisher()
        job_id = "route-continuation-job"
        _register_job(
            job_id,
            workspace,
            expected_module_name=EXPECTED_MODULE_NAME,
            status="ready_for_finishing",
        )
        with routes_module._jobs_lock:
            job = routes_module._jobs[job_id]
            job["status"] = "ready_for_finishing"
            job["stage"] = "finishing"
            job["pipeline_status"] = "retry_from_finishing"
            job["result"] = {
                "status": "ready_for_finishing",
                "module_name": EXPECTED_MODULE_NAME,
                "stages": {},
            }
            job["adaptation_job"] = True
            job["adaptation_mode"] = BUILD_MODE_LLM_ADAPTATION
            job["adaptation_route_decision"] = {
                "status": ROUTE_DECISION_STATUS_ADAPTATION,
                "route_selected": BUILD_MODE_LLM_ADAPTATION,
                "rights": {
                    "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                    "rights_basis": "user_authored_uploaded_adventure",
                    "rights_review_required": False,
                    "rights_review_status": "not_required",
                    "python_owned": True,
                    "classified_by": "python",
                },
            }
            job["adaptation_attempt_id"] = ATTEMPT_ID
            job["adaptation_source_hash"] = FIXTURE_HASH
            job["adaptation_source_kind"] = "upload_markdown"
            job["adaptation_world_context"] = build_world_context_provenance(None)
            job["adaptation_staging_target"] = _fake_staging_target(
                FIXTURE_HASH, attempt_id=ATTEMPT_ID, module_slug=EXPECTED_MODULE_NAME
            )
            job["adaptation_build_handoff"] = {
                "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
                "adaptation_gates": {
                    "status": "pass",
                    "playable_status": "pass",
                    "candidate_eligible": True,
                },
                "adaptation_staging_target": _fake_staging_target(
                    FIXTURE_HASH, attempt_id=ATTEMPT_ID, module_slug=EXPECTED_MODULE_NAME
                ),
                "adaptation_module_dir": str(self.scratch / "staged"),
                "adaptation_provenance": {
                    "contract_version": "toolkit_adaptation_provenance.v1",
                    "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
                    "source_hash": FIXTURE_HASH,
                    "attempt_id": ATTEMPT_ID,
                    "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                },
                "adaptation_artifact_workspace": str(workspace),
            }
            self.job_ids.append(job_id)

        with patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(
                job_id,
                {
                    "finishing_only": True,
                    "rebuild_mode": False,
                    "module_name": EXPECTED_MODULE_NAME,
                },
            )

        self.assertEqual(len(fake_finisher.calls), 1)
        _module_slug, finisher_input = fake_finisher.calls[0]
        self.assertEqual(finisher_input.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(
            finisher_input.get("output_directory"), str(self.scratch / "staged")
        )
        self.assertIn("adaptation_gates", finisher_input)
        self.assertIn("staging_target", finisher_input)
        self.assertIn("adaptation_provenance", finisher_input)
        self.assertEqual(
            (finisher_input.get("adaptation_provenance") or {}).get("attempt_id"),
            ATTEMPT_ID,
        )
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "adaptation_completed")
        _assert_adaptation_markers(job)

    def test_continuation_after_full_flow_keeps_handoff(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            _adaptation_build_result("route-retry-job", workspace, FIXTURE_HASH)
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher()
        job_id = "route-retry-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_ready_authoring_result(job_id, FIXTURE_HASH),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(job_id)

        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "adaptation_completed")
        handoff = job.get("adaptation_build_handoff") or {}
        self.assertEqual(handoff.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION)
        self.assertIn("adaptation_provenance", handoff)

        # The retry route resets the job to ready_for_finishing before the
        # finishing-only continuation; simulate that transition.
        with routes_module._jobs_lock:
            routes_module._jobs[job_id]["status"] = "ready_for_finishing"
            routes_module._jobs[job_id]["stage"] = "finishing"
            routes_module._jobs[job_id]["pipeline_status"] = "retry_from_finishing"

        continuation_finisher = _FakeFinisher()
        with patch.object(
            routes_module,
            "_run_homebrew_finisher",
            side_effect=continuation_finisher,
        ):
            self._run_build(
                job_id,
                {
                    "finishing_only": True,
                    "rebuild_mode": False,
                    "module_name": "",
                },
            )

        self.assertEqual(len(continuation_finisher.calls), 1)
        _module_slug, finisher_input = continuation_finisher.calls[0]
        self.assertEqual(
            finisher_input.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION
        )
        self.assertIn("adaptation_gates", finisher_input)
        self.assertIn("staging_target", finisher_input)
        self.assertIn("adaptation_provenance", finisher_input)
        self.assertIn("output_directory", finisher_input)
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "adaptation_completed")
        _assert_adaptation_markers(job)

    def test_legacy_continuation_receives_unmodified_result(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_finisher = _FakeFinisher()
        job_id = "route-legacy-continuation-job"
        _register_job(
            job_id,
            workspace,
            expected_module_name=EXPECTED_MODULE_NAME,
            status="ready_for_finishing",
        )
        with routes_module._jobs_lock:
            job = routes_module._jobs[job_id]
            job["status"] = "ready_for_finishing"
            job["stage"] = "finishing"
            job["pipeline_status"] = "retry_from_finishing"
            job["result"] = {
                "status": "ready_for_finishing",
                "module_name": EXPECTED_MODULE_NAME,
                "stages": {},
            }
            self.job_ids.append(job_id)

        with patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(
                job_id,
                {
                    "finishing_only": True,
                    "rebuild_mode": False,
                    "module_name": EXPECTED_MODULE_NAME,
                },
            )

        self.assertEqual(len(fake_finisher.calls), 1)
        _module_slug, finisher_input = fake_finisher.calls[0]
        for key in (
            "adaptation_mode",
            "adaptation_gates",
            "staging_target",
            "adaptation_provenance",
            "output_directory",
        ):
            self.assertNotIn(key, finisher_input)
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "completed")
        self.assertNotIn("adaptation_job", job)
        self.assertNotIn("adaptation_build_handoff", job)


class TestLegacyOverwriteRebuildTransitionPreserved(
    _LifecycleScratchMixin, unittest.TestCase
):
    """The overwrite-confirmation and rebuild stages keep legacy behavior."""

    def test_legacy_rebuild_path_keeps_payload_and_gains_no_adaptation_keys(
        self,
    ) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_rebuild = _FakeRebuildPrep()
        fake_packet = _FakePacketBuild(
            {
                "status": "success",
                "module_name": EXPECTED_MODULE_NAME,
                "output_directory": str(self.scratch / "staged"),
            }
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher()
        job_id = "route-overwrite-job"
        _register_job(job_id, workspace, status="approved_for_build")
        self.job_ids.append(job_id)

        # Simulate the start-build overwrite-confirmation transition (route
        # writes these fields additively under the job lock).
        with routes_module._jobs_lock:
            job = routes_module._jobs[job_id]
            job["status"] = "awaiting_overwrite_confirmation"
            job["stage"] = "build"
            job["pipeline_status"] = "awaiting_confirmation"
            job["rebuild_mode"] = True
            job["rebuild_collision"] = {"module_dir_exists": True, "module_dir": ""}
            job["expected_module_name"] = EXPECTED_MODULE_NAME
            job["overwrite_policy"] = "backup_clean"

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
        ) as mock_authoring, patch.object(
            routes_module,
            "_prepare_homebrew_rebuild_target",
            side_effect=fake_rebuild,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(
                job_id,
                {
                    "finishing_only": False,
                    "rebuild_mode": True,
                    "module_name": EXPECTED_MODULE_NAME,
                    "module_dir": str(self.scratch / "modules" / EXPECTED_MODULE_NAME),
                    "overwrite_policy": "backup_clean",
                },
            )

        # Rebuild preparation ran; adaptation authoring never ran; the packet
        # builder ran with overwrite_confirmed for the rebuild.
        self.assertEqual(len(fake_rebuild.calls), 1)
        self.assertEqual(
            fake_rebuild.calls[0]["module_name"], EXPECTED_MODULE_NAME
        )
        self.assertEqual(fake_rebuild.calls[0]["overwrite_policy"], "backup_clean")
        mock_authoring.assert_not_called()
        self.assertEqual(len(fake_packet.calls), 1)
        self.assertIs(fake_packet.calls[0]["overwrite_confirmed"], True)
        call = fake_packet.calls[0]
        for key in (
            "adaptation_route",
            "adaptation_dossier",
            "adaptation_provenance",
            "adaptation_staging_root",
            "adaptation_staging_target",
        ):
            self.assertNotIn(key, call)

        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "completed")
        for key in (
            "adaptation_job",
            "adaptation_mode",
            "adaptation_route_decision",
            "adaptation_attempt_id",
            "adaptation_build_handoff",
        ):
            self.assertNotIn(key, job)
        self.assertIs(job.get("rebuild_mode"), True)

    def test_overwrite_transition_is_additive_to_existing_markers(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        job_id = "route-overwrite-markers-job"
        _register_job(job_id, workspace, status="approved_for_build")
        self.job_ids.append(job_id)
        with routes_module._jobs_lock:
            job = routes_module._jobs[job_id]
            job["adaptation_job"] = True
            job["adaptation_mode"] = BUILD_MODE_LLM_ADAPTATION
            job["adaptation_route_decision"] = {
                "status": ROUTE_DECISION_STATUS_ADAPTATION,
                "route_selected": BUILD_MODE_LLM_ADAPTATION,
                "rights": {
                    "rights_class": RIGHTS_CLASS_USER_AUTHORED,
                    "rights_basis": "user_authored_uploaded_adventure",
                    "rights_review_required": False,
                    "rights_review_status": "not_required",
                    "python_owned": True,
                    "classified_by": "python",
                },
            }
            job["adaptation_attempt_id"] = ATTEMPT_ID
            job["adaptation_source_hash"] = FIXTURE_HASH
            job["adaptation_source_kind"] = "upload_markdown"
            job["adaptation_world_context"] = build_world_context_provenance(None)
            job["adaptation_staging_target"] = _fake_staging_target(
                FIXTURE_HASH, attempt_id=ATTEMPT_ID, module_slug=EXPECTED_MODULE_NAME
            )
            job["status"] = "awaiting_overwrite_confirmation"
            job["stage"] = "build"
            job["pipeline_status"] = "awaiting_confirmation"
            job["rebuild_mode"] = True
            job["rebuild_collision"] = {"module_dir_exists": True, "module_dir": ""}
            job["expected_module_name"] = EXPECTED_MODULE_NAME

        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "awaiting_overwrite_confirmation")
        self.assertIs(job.get("rebuild_mode"), True)
        # The transition did not drop or relabel the attached metadata.
        _assert_adaptation_markers(job)
        decision_rights = (job.get("adaptation_route_decision") or {}).get(
            "rights"
        ) or {}
        self.assertEqual(decision_rights.get("rights_class"), RIGHTS_CLASS_USER_AUTHORED)


class TestPublicationGateOrderAndFailureState(
    _LifecycleScratchMixin, unittest.TestCase
):
    """A successful build never reports success before gates complete, and
    failures leave no misleading registry/campaign state."""

    def _snapshot_sentinels(self) -> Dict[str, Any]:
        def _bytes(path: Path) -> Optional[bytes]:
            try:
                return path.read_bytes()
            except OSError:
                return None

        return {
            "registry": _bytes(REGISTRY_SENTINEL),
            "campaign": _bytes(CAMPAIGN_SENTINEL),
            "module_dir_exists": (REPO_ROOT / "modules" / EXPECTED_MODULE_NAME).exists(),
        }

    def _assert_sentinels_unchanged(
        self, before: Dict[str, Any], job: Dict[str, Any]
    ) -> None:
        def _bytes(path: Path) -> Optional[bytes]:
            try:
                return path.read_bytes()
            except OSError:
                return None

        self.assertEqual(_bytes(REGISTRY_SENTINEL), before["registry"])
        self.assertEqual(_bytes(CAMPAIGN_SENTINEL), before["campaign"])
        self.assertFalse(
            (REPO_ROOT / "modules" / EXPECTED_MODULE_NAME).exists(),
            "fixture module must never be created under modules/",
        )
        staging = job.get("adaptation_staging_target") or {}
        self.assertFalse(
            (REPO_ROOT / str(staging.get("path") or "")).exists(),
            "fake staging target must never be created on disk",
        )

    def test_not_publishable_finisher_never_reports_completed(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            _adaptation_build_result("route-gate-job", workspace, FIXTURE_HASH)
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher(
            {
                "status": "blocked",
                "ready_status": "pass",
                "publishable_status": "fail",
                "module_name": EXPECTED_MODULE_NAME,
                "publication_status": "blocked",
                "terminal_status": "blocked",
                "registry": {"status": "not_attempted", "verified": False},
                "campaign_sync": {"status": "not_attempted"},
                "registry_verified": False,
                "python_authoritative": True,
                "llm_publication_override": False,
            }
        )
        job_id = "route-gate-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        sentinels_before = self._snapshot_sentinels()

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_ready_authoring_result(job_id, FIXTURE_HASH),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(job_id)

        job = self._snapshot_job(job_id)
        # not_publishable keeps the pre-existing adaptation blocked mapping;
        # the job never reports adaptation_completed.
        self.assertEqual(job.get("status"), "adaptation_blocked")
        self.assertEqual(job.get("adaptation_outcome"), "blocked")
        self.assertNotEqual(job.get("status"), "adaptation_completed")
        _assert_adaptation_markers(job)
        self._assert_sentinels_unchanged(sentinels_before, job)
        # Readiness stage ran before the blocked finisher outcome.
        self.assertEqual(job.get("stage"), "finishing")
        self.assertEqual(job.get("pipeline_status"), "blocked")

    def test_finisher_failure_keeps_adaptation_blocked_terminal(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            _adaptation_build_result("route-fail-job", workspace, FIXTURE_HASH)
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher(
            {
                "status": "failed",
                "ready_status": "fail",
                "publishable_status": "fail",
                "module_name": EXPECTED_MODULE_NAME,
            }
        )
        job_id = "route-fail-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        sentinels_before = self._snapshot_sentinels()

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_ready_authoring_result(job_id, FIXTURE_HASH),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(job_id)

        job = self._snapshot_job(job_id)
        # finishing_failed maps through the pre-existing adaptation reporting
        # to the bounded blocked terminal; never adaptation_completed.
        self.assertEqual(job.get("status"), "adaptation_blocked")
        self.assertEqual(job.get("adaptation_outcome"), "blocked")
        self.assertNotEqual(job.get("status"), "adaptation_completed")
        self.assertEqual(job.get("stage"), "finishing")
        self.assertEqual(job.get("pipeline_status"), "failed")
        _assert_adaptation_markers(job)
        self._assert_sentinels_unchanged(sentinels_before, job)

    def test_blocked_readiness_gate_never_reports_completed(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            _adaptation_build_result("route-readiness-gate-job", workspace, FIXTURE_HASH)
        )
        fake_readiness = _FakeReadiness("repair_budget_exhausted")
        fake_finisher = _FakeFinisher()
        job_id = "route-readiness-gate-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        sentinels_before = self._snapshot_sentinels()

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_ready_authoring_result(job_id, FIXTURE_HASH),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(job_id)

        self.assertEqual(fake_finisher.calls, [])
        job = self._snapshot_job(job_id)
        # A blocked readiness gate is an explicit non-success outcome for the
        # adaptation job: bounded blocked terminal, never completed.
        self.assertEqual(job.get("status"), "adaptation_blocked")
        self.assertEqual(job.get("adaptation_outcome"), "blocked")
        self.assertEqual(job.get("adaptation_failure_surface"), "readiness")
        self.assertNotEqual(job.get("status"), "adaptation_completed")
        _assert_adaptation_markers(job)
        self._assert_sentinels_unchanged(sentinels_before, job)
        self.assertEqual(job.get("stage"), "readiness")

    def test_handoff_fields_reach_the_finisher_in_initial_flow(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            _adaptation_build_result("route-report-job", workspace, FIXTURE_HASH)
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher()
        job_id = "route-report-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_ready_authoring_result(job_id, FIXTURE_HASH),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=fake_readiness
        ), patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=fake_finisher
        ):
            self._run_build(job_id)

        self.assertEqual(len(fake_finisher.calls), 1)
        _module_slug, finisher_input = fake_finisher.calls[0]
        self.assertEqual(
            finisher_input.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION
        )
        self.assertIn("adaptation_gates", finisher_input)
        self.assertIn("staging_target", finisher_input)
        self.assertIn("adaptation_provenance", finisher_input)
        self.assertIn("output_directory", finisher_input)
        self.assertIn("adaptation_artifact_workspace", finisher_input)
        provenance = finisher_input.get("adaptation_provenance") or {}
        self.assertEqual(provenance.get("attempt_id"), ATTEMPT_ID)
        self.assertEqual(provenance.get("source_hash"), FIXTURE_HASH)
        self.assertEqual(provenance.get("rights_class"), RIGHTS_CLASS_USER_AUTHORED)

        # The retained report result carries the adaptation mode and the job
        # keeps every marker and the bounded build handoff.
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "adaptation_completed")
        report = job.get("result") or {}
        self.assertEqual(report.get("publication_status"), "completed")
        self.assertIs(report.get("python_authoritative"), True)
        self.assertIs(report.get("llm_publication_override"), False)
        handoff = job.get("adaptation_build_handoff") or {}
        self.assertEqual(handoff.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION)
        self.assertIn("adaptation_provenance", handoff)


class TestLifecycleHygiene(unittest.TestCase):
    """ASCII, provider/network, and path-policy hygiene for task 4.3."""

    THIS_FILE = Path(__file__).resolve()

    def test_changed_files_are_ascii_only(self) -> None:
        for path in (self.THIS_FILE, ROUTES_MODULE_PATH):
            text = path.read_text(encoding="utf-8")
            self.assertTrue(
                all(ord(ch) < 128 for ch in text),
                "non-ASCII characters found in %s" % path.name,
            )

    def test_new_test_file_has_spdx_header(self) -> None:
        text = self.THIS_FILE.read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)

    def test_no_os_temp_or_absolute_scratch_paths(self) -> None:
        text = self.THIS_FILE.read_text(encoding="utf-8")
        scanned = text[: text.index("    def test_no_os_temp_or_absolute_scratch_paths")]
        for token in ("tempfile", "/tmp/", "/var/folders", "TemporaryDirectory"):
            self.assertNotIn(token, scanned, "forbidden OS-temp token: %s" % token)

    def test_no_provider_network_imports_in_test_file(self) -> None:
        tree = ast.parse(self.THIS_FILE.read_text(encoding="utf-8"))
        imported: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for name in imported:
            for forbidden in (
                "openai",
                "httpx",
                "requests",
                "urllib",
                "http.client",
                "socketio",
                "flask",
                "tempfile",
            ):
                self.assertNotIn(
                    forbidden,
                    name,
                    "forbidden import in provider-free lifecycle tests: %s" % name,
                )
        text = self.THIS_FILE.read_text(encoding="utf-8")
        scanned = text[: text.index("    def test_no_provider_network_imports_in_test_file")]
        for token in (
            "create_chat_client",
            "OpenAI(",
            "requests.get",
            "urlopen",
            "socketio",
        ):
            self.assertNotIn(token, scanned, "forbidden provider token: %s" % token)

    def test_fixture_staging_target_never_created_on_disk(self) -> None:
        fixture_target = _fake_staging_target(
            FIXTURE_HASH, attempt_id=ATTEMPT_ID, module_slug=EXPECTED_MODULE_NAME
        )
        resolved = REPO_ROOT / fixture_target["path"]
        self.assertFalse(
            resolved.exists(),
            "fixture staging target must never be created on disk",
        )
        self.assertFalse(
            (REPO_ROOT / "modules" / EXPECTED_MODULE_NAME).exists(),
            "fixture module must never be created under modules/",
        )


if __name__ == "__main__":
    unittest.main()
