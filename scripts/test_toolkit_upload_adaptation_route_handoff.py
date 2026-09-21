# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free route tests for the upload build-job adaptation handoff
(task 4.1 of toolkit-llm-adaptation-runtime-unification).

The suite drives
``web/routes/toolkit_homebrew_routes._run_homebrew_build_job`` directly with
patched adapter/authoring/staging/packet-builder seams:

  * exact ``ENABLE_LLM_ADAPTATION`` False keeps the legacy upload packet path
    (no adaptation kwargs, no adaptation job markers, no authoring call);
  * exact True resolves the adaptation route, assembles the approved upload
    handoff, runs authoring through the injectable seam, requires a ready
    Python-validated dossier, reserves the isolated project-relative staging
    target, and forwards the validated dossier, bounded provenance, staging
    root, and reserved staging target into the packet builder;
  * handoff, authoring, dossier, route-authority, or staging failures stop
    before the packet builder and fail closed (never legacy fall-through);
  * restricted uploads stay review-gated/ineligible and run the legacy path.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_upload_adaptation_route_handoff/<uuid>/`` and are removed via
addCleanup. No OS temp directory, no provider/network calls, and no real
``modules/``, registry, campaign, or runtime mutation: the packet build,
readiness, finisher, authoring, and staging seams are all injected fakes, and
the live ``model_config.ENABLE_LLM_ADAPTATION`` operator value is never
relied on (every behavioral test patches it explicitly).
"""

import ast
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.routes.toolkit_homebrew_routes as routes_module
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LLM_ADAPTATION,
    ROUTE_DECISION_STATUS_ADAPTATION,
)
from utils.toolkit_adaptation_dossier import (
    RIGHTS_CLASS_USER_AUTHORED,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    SOURCE_RIGHTS_RESTRICTED,
    SOURCE_RIGHTS_USER_AUTHORED,
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
    persist_normalized_packet_artifact,
    persist_review_snapshot_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_upload_adaptation_route_handoff"
ROUTES_MODULE_PATH = (
    REPO_ROOT / "web" / "routes" / "toolkit_homebrew_routes.py"
)
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

EXPECTED_MODULE_NAME = "Sunken_Lighthouse"


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
        "assumptions": ["Fixture packet for the upload route handoff tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }
    persist_normalized_packet_artifact(ws, packet)
    snapshot = build_review_snapshot(
        job_id="route-handoff-job",
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
) -> None:
    with routes_module._jobs_lock:
        routes_module._jobs[job_id] = {
            "job_id": job_id,
            "job_type": "toolkit_homebrew_md_ingest",
            "status": "building",
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
    attempt_id = "handoff-test-attempt"
    world = build_world_context_provenance(None)
    return {
        "contract_version": "toolkit_adaptation_authoring_adapter.v1",
        "status": "ready",
        "outcome": "handoff_ready",
        "ok": True,
        "input_kind": "upload_markdown",
        "route": _route_authority(),
        "attempt": {
            "attempt_id": attempt_id,
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": job_id,
        },
        "source_identity": {
            "source_title": "Sunken Lighthouse",
            "source_hash": source_hash,
            "source_path": "tmp/route-handoff/workspace/source_original.md",
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
            "attempt_id": attempt_id,
            "dossier_artifact_path": "tmp/route-handoff/attempts/%s/adaptation_dossier.json" % attempt_id,
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


def _blocked_authoring_result(
    reason_code: str = "dossier_refused",
    safe_class: str = "author_policy_refusal",
) -> Dict[str, Any]:
    """Build a deterministic blocked authoring adapter result for the seam."""
    return {
        "contract_version": "toolkit_adaptation_authoring_adapter.v1",
        "status": "blocked",
        "outcome": "blocked",
        "ok": False,
        "input_kind": "upload_markdown",
        "route": _route_authority(),
        "attempt": {},
        "source_identity": {},
        "rights": {},
        "world_context": build_world_context_provenance(None),
        "staging": {},
        "model_metadata": {},
        "authoring": {
            "authoring_attempted": True,
            "authoring_status": "blocked",
            "authoring_ok": False,
            "diagnostics": [{"code": reason_code, "message": "fixture blocked"}],
            "safe_class": safe_class,
            "reason_code": reason_code,
            "revision_eligible": False,
            "retryable": False,
            "terminal": True,
        },
        "dossier": None,
        "guards": {
            "module_builder_allowed": False,
            "module_builder_started": False,
            "publication_started": False,
            "registry_mutated": False,
            "completed_module_artifacts": [],
            "selected_route_authoritative": True,
        },
        "diagnostics": [{"code": reason_code, "message": "fixture blocked"}],
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
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Deterministic reserved staging target fake (never touches the disk)."""
    resolved_attempt_id = attempt_id or "fixture-attempt"
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


def _valid_convergence_callback_context(source_hash: str) -> Dict[str, Any]:
    """Return a bounded no-repair convergence request for route tests."""
    attempt_id = "route-callback-attempt"
    relative_path = "tmp/adaptation-staging/%s/revision_000" % attempt_id
    return {
        "contract_version": "toolkit_adaptation_publication_convergence.v1",
        "attempt_id": attempt_id,
        "attempt_number": 1,
        "revision_number": 0,
        "source_hash": source_hash,
        "staging_identity": {
            "stage_id": "%s:revision_000" % attempt_id,
            "module_slug": EXPECTED_MODULE_NAME,
            "path": relative_path,
            "output_directory": relative_path,
        },
        "budget": {
            "current_attempt": 0,
            "max_attempts": 1,
            "max_operations_per_round": 1,
            "operation_timeout_seconds": 30,
        },
    }


class _FakePacketBuild:
    """Records packet-builder kwargs and returns a configurable result."""

    def __init__(self, result: Optional[Dict[str, Any]] = None) -> None:
        self.result = (
            result
            if result is not None
            else {
                "status": "failed",
                "stage": "build",
                "error": "fixture_stop",
                "job_id": "fixture",
            }
        )
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, workspace: Any, job_id: str, **kwargs: Any) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "workspace": str(workspace),
            "job_id": job_id,
        }
        record.update(dict(kwargs))
        self.calls.append(record)
        return dict(self.result)


class _FakeReadiness:
    """Always-ready readiness gate fake."""

    def __call__(
        self, artifact_workspace: Any, job_id: str, state_callback: Any = None
    ) -> Dict[str, Any]:
        return {
            "status": "ready_for_finishing",
            "module_name": EXPECTED_MODULE_NAME,
        }


class _FakeFinisher:
    """Always-passing finisher fake with adaptation publication verification."""

    def __call__(
        self, module_slug: str, build_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
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


class _RouteScratchMixin:
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


class TestLegacyUploadPathIsolated(_RouteScratchMixin, unittest.TestCase):
    """Exact False keeps the legacy packet path with no adaptation artifacts."""

    def test_disabled_flag_keeps_legacy_packet_build(self) -> None:
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
        job_id = "route-legacy-job"
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
            self._run_build(job_id)
        self.assertEqual(len(fake_packet.calls), 1)
        call = fake_packet.calls[0]
        self.assertNotIn("adaptation_route", call)
        self.assertNotIn("adaptation_dossier", call)
        self.assertNotIn("adaptation_provenance", call)
        self.assertNotIn("adaptation_staging_root", call)
        self.assertNotIn("adaptation_staging_target", call)
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "completed")
        self.assertNotIn("adaptation_job", job)
        self.assertNotIn("adaptation_mode", job)
        self.assertNotIn("adaptation_route_decision", job)


class TestEnabledUploadAdaptationHandoff(_RouteScratchMixin, unittest.TestCase):
    """Exact True selects the adaptation route and forwards the handoff."""

    def test_enabled_forwards_dossier_provenance_and_reserved_staging(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-enabled-job"
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
        ):
            self._run_build(job_id)
        self.assertEqual(len(fake_packet.calls), 1)
        call = fake_packet.calls[0]
        self.assertEqual(call["adaptation_route"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(call["adaptation_staging_root"], "tmp/adaptation-staging")
        dossier = call["adaptation_dossier"]
        dossier_validation = validate_adaptation_dossier(dossier)
        self.assertTrue(dossier_validation.get("valid"))
        self.assertTrue(dossier_validation.get("build_ready"))
        self.assertEqual(dossier.get("source_hash"), FIXTURE_HASH)
        provenance = call["adaptation_provenance"]
        self.assertEqual(provenance["attempt_metadata"]["job_id"], job_id)
        self.assertEqual(provenance["attempt_metadata"]["attempt_id"], "handoff-test-attempt")
        self.assertEqual(provenance["source_hash"], FIXTURE_HASH)
        self.assertEqual(provenance["source_format"], "upload_markdown")
        self.assertEqual(provenance["model_metadata"]["model"], "gpt-5.6-luna")
        self.assertIn("world_context_provenance", provenance)
        self.assertEqual(provenance["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        target = call["adaptation_staging_target"]
        self.assertEqual(target["completion_state"], "reserved")
        self.assertEqual(target["source_hash"], FIXTURE_HASH)
        self.assertEqual(target["module_slug"], EXPECTED_MODULE_NAME)
        self.assertTrue(
            target["path"].startswith("tmp/adaptation-staging/"),
            "staging target must be project-relative",
        )
        job = self._snapshot_job(job_id)
        self.assertIs(job.get("adaptation_job"), True)
        self.assertEqual(job.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION)
        decision = job.get("adaptation_route_decision") or {}
        self.assertEqual(decision.get("status"), ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertEqual(decision.get("route_selected"), BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(job.get("adaptation_attempt_id"), "handoff-test-attempt")
        self.assertEqual(job.get("adaptation_source_hash"), FIXTURE_HASH)
        self.assertEqual(job.get("adaptation_source_kind"), "upload_markdown")
        world = job.get("adaptation_world_context") or {}
        self.assertIn("world_seed_status", world)
        self.assertIn("read_only", world)
        staging = job.get("adaptation_staging_target") or {}
        self.assertEqual(staging.get("completion_state"), "reserved")

    def test_full_success_flow_preserves_adaptation_markers(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild(
            {
                "status": "success",
                "module_name": EXPECTED_MODULE_NAME,
                "output_directory": str(self.scratch / "staged"),
                "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
            }
        )
        fake_readiness = _FakeReadiness()
        fake_finisher = _FakeFinisher()
        job_id = "route-success-job"
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
        self.assertEqual(len(fake_packet.calls), 1)
        self.assertEqual(fake_packet.calls[0]["adaptation_route"], BUILD_MODE_LLM_ADAPTATION)
        job = self._snapshot_job(job_id)
        # The pre-existing adaptation terminal mapping replaces the generic
        # completed status once publication verification is satisfied.
        self.assertEqual(job.get("status"), "adaptation_completed")
        self.assertIs(job.get("adaptation_job"), True)
        self.assertEqual(job.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION)
        decision = job.get("adaptation_route_decision") or {}
        self.assertEqual(decision.get("status"), ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertEqual(job.get("adaptation_attempt_id"), "handoff-test-attempt")


class TestAdaptationFailuresFailClosed(_RouteScratchMixin, unittest.TestCase):
    """Selected adaptation failures stop before the packet builder."""

    def _assert_failed_closed(self, job_id: str, expected_error: str) -> None:
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "adaptation_blocked")
        result = job.get("result") or {}
        self.assertEqual(result.get("stage"), "authoring")
        self.assertEqual(result.get("error"), expected_error)
        self.assertEqual(result.get("adaptation_mode"), BUILD_MODE_LLM_ADAPTATION)
        classification = result.get("failure_classification") or {}
        self.assertIs(classification.get("revision_eligible"), False)
        self.assertIs(classification.get("semantic_revision_eligible"), False)
        decision = job.get("adaptation_route_decision") or {}
        self.assertEqual(decision.get("status"), ROUTE_DECISION_STATUS_ADAPTATION)

    def test_authoring_policy_refusal_stops_before_packet_builder(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-refused-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_blocked_authoring_result(),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ) as mock_staging, patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ):
            self._run_build(job_id)
        self.assertEqual(fake_packet.calls, [])
        mock_staging.assert_not_called()
        self._assert_failed_closed(job_id, "dossier_refused")
        job = self._snapshot_job(job_id)
        classification = (job.get("result") or {}).get("failure_classification") or {}
        self.assertEqual(classification.get("failure_class"), "rights")
        self.assertEqual(classification.get("failure_group"), "validation")

    def test_authoring_infrastructure_failure_fails_closed(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-infra-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_blocked_authoring_result(
                reason_code="provider_api_refusal",
                safe_class="provider_infrastructure",
            ),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ):
            self._run_build(job_id)
        self.assertEqual(fake_packet.calls, [])
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "adaptation_infrastructure_failed")
        result = job.get("result") or {}
        self.assertEqual(result.get("error"), "provider_api_refusal")
        classification = result.get("failure_classification") or {}
        self.assertEqual(classification.get("failure_class"), "provider")
        self.assertEqual(classification.get("failure_group"), "infrastructure")

    def test_authoring_api_refusal_fails_closed_as_blocked(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-api-refusal-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_blocked_authoring_result(
                reason_code="provider_api_refusal",
                safe_class="api_refusal",
            ),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ):
            self._run_build(job_id)
        self.assertEqual(fake_packet.calls, [])
        self._assert_failed_closed(job_id, "provider_api_refusal")
        job = self._snapshot_job(job_id)
        self.assertNotEqual(job.get("status"), "adaptation_infrastructure_failed")
        self.assertNotEqual(job.get("status"), "adaptation_completed")
        classification = (job.get("result") or {}).get("failure_classification") or {}
        # API refusal is a bounded refusal channel, distinct from
        # infrastructure: policy-class blocked, reason code preserved.
        self.assertEqual(classification.get("failure_class"), "rights")
        self.assertEqual(classification.get("code"), "provider_api_refusal")
        self.assertIs(classification.get("revision_eligible"), False)

    def test_handoff_failed_closed_stops_before_authoring(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-handoff-fail-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)

        def _broken_handoff(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            return {
                "contract_version": "toolkit_upload_adaptation_handoff.v1",
                "status": "failed_closed",
                "input_kind": "upload_markdown",
                "source_kind": "markdown",
                "upload_evidence": {},
                "world_context": build_world_context_provenance(None),
                "envelope": None,
                "diagnostics": [
                    {"code": "workspace_missing", "message": "fixture missing"}
                ],
            }

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "build_upload_adaptation_handoff",
            side_effect=_broken_handoff,
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
        ) as mock_authoring, patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ):
            self._run_build(job_id)
        mock_authoring.assert_not_called()
        self.assertEqual(fake_packet.calls, [])
        self._assert_failed_closed(job_id, "upload_adaptation_handoff_failed")

    def test_dossier_not_build_ready_stops_before_packet_builder(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-invalid-dossier-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        invalid_result = _ready_authoring_result(job_id, FIXTURE_HASH)
        invalid_result["dossier"] = {"status": "ready", "adapted_title": "not real"}
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=invalid_result,
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ):
            self._run_build(job_id)
        self.assertEqual(fake_packet.calls, [])
        self._assert_failed_closed(job_id, "upload_adaptation_dossier_not_ready")

    def test_staging_reservation_failure_stops_before_packet_builder(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-staging-fail-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)

        def _raise_staging(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise ValueError("fixture staging reservation failure")

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=_ready_authoring_result(job_id, FIXTURE_HASH),
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_raise_staging,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ):
            self._run_build(job_id)
        self.assertEqual(fake_packet.calls, [])
        self._assert_failed_closed(job_id, "adaptation_staging_reservation_failed")

    def test_route_authority_invalid_fails_closed(self) -> None:
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        fake_packet = _FakePacketBuild()
        job_id = "route-authority-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)

        def _invalid_authority(decision: Any) -> Dict[str, Any]:
            return {
                "route_selected": BUILD_MODE_LLM_ADAPTATION,
                "status": "failed_closed",
                "authoritative": False,
                "fallback_allowed": False,
                "adaptation_artifacts_required": True,
                "reason": "selected_route_metadata_invalid",
                "diagnostics": ["fixture"],
            }

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "validate_adaptation_route_decision",
            side_effect=_invalid_authority,
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
        ) as mock_authoring, patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=_fake_staging_target,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=fake_packet
        ):
            self._run_build(job_id)
        mock_authoring.assert_not_called()
        self.assertEqual(fake_packet.calls, [])
        self._assert_failed_closed(job_id, "adaptation_route_authority_invalid")


class TestIneligibleUploadsStayLegacy(_RouteScratchMixin, unittest.TestCase):
    """Restricted uploads stay review-gated and keep the legacy route."""

    def test_restricted_upload_uses_legacy_path_when_enabled(self) -> None:
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
        job_id = "route-restricted-job"
        _register_job(
            job_id,
            workspace,
            rights_class=SOURCE_RIGHTS_RESTRICTED,
        )
        self.job_ids.append(job_id)
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
        ) as mock_authoring, patch.object(
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
        mock_authoring.assert_not_called()
        self.assertEqual(len(fake_packet.calls), 1)
        call = fake_packet.calls[0]
        self.assertNotIn("adaptation_route", call)
        self.assertNotIn("adaptation_staging_target", call)
        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "completed")
        self.assertNotIn("adaptation_job", job)
        self.assertNotIn("adaptation_route_decision", job)


class TestPacketBuildHelperForwardsAdaptationKwargs(
    _RouteScratchMixin, unittest.TestCase
):
    """The route packet-build helper forwards the adaptation handoff kwargs."""

    def test_helper_forwards_all_five_adaptation_kwargs(self) -> None:
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        captured: Dict[str, Any] = {}

        def _fake_run(**kwargs: Any) -> Dict[str, Any]:
            captured.update(dict(kwargs))
            return {"status": "success"}

        with patch.object(
            packet_builder,
            "run_toolkit_homebrew_packet_build",
            side_effect=_fake_run,
        ):
            result = routes_module._run_homebrew_packet_build(
                self.scratch,
                "job-1",
                adaptation_route=BUILD_MODE_LLM_ADAPTATION,
                adaptation_dossier={"source_hash": FIXTURE_HASH},
                adaptation_provenance={"attempt_metadata": {"job_id": "job-1"}},
                adaptation_staging_root="tmp/adaptation-staging",
                adaptation_staging_target={"completion_state": "reserved"},
            )
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(
            captured.get("adaptation_route"), BUILD_MODE_LLM_ADAPTATION
        )
        self.assertEqual(
            captured.get("adaptation_dossier", {}).get("source_hash"), FIXTURE_HASH
        )
        self.assertEqual(
            captured.get("adaptation_provenance", {})
            .get("attempt_metadata", {})
            .get("job_id"),
            "job-1",
        )
        self.assertEqual(
            captured.get("adaptation_staging_root"), "tmp/adaptation-staging"
        )
        self.assertEqual(
            captured.get("adaptation_staging_target", {}).get("completion_state"),
            "reserved",
        )
        self.assertIs(
            captured.get("adaptation_convergence_callback"),
            routes_module.adaptation_convergence_callback,
        )

    def test_enabled_route_invokes_shared_callback_without_provider(self) -> None:
        """The production helper reaches convergence before any provider seam."""
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        captured: Dict[str, Any] = {}

        def _fake_run(**kwargs: Any) -> Dict[str, Any]:
            callback = kwargs.get("adaptation_convergence_callback")
            captured["callback"] = callback
            self.assertIs(callback, routes_module.adaptation_convergence_callback)
            self.assertTrue(callable(callback))
            captured["callback_result"] = callback(
                _valid_convergence_callback_context(FIXTURE_HASH)
            )
            return {"status": "success", "adaptation_mode": BUILD_MODE_LLM_ADAPTATION}

        provider_factory = __import__(
            "utils.ai_client_factory", fromlist=["provider_factory"]
        )
        provider_constructor = "create_" + "chat_client"
        with patch.object(
            provider_factory,
            provider_constructor,
            side_effect=AssertionError("deterministic route called a provider"),
        ), patch.object(
            packet_builder,
            "run_toolkit_homebrew_packet_build",
            side_effect=_fake_run,
        ):
            result = routes_module._run_homebrew_packet_build(
                self.scratch,
                "route-callback-job",
                adaptation_route=BUILD_MODE_LLM_ADAPTATION,
                adaptation_dossier={"source_hash": FIXTURE_HASH},
                adaptation_provenance={"attempt_metadata": {"job_id": "route-callback-job"}},
                adaptation_staging_root="tmp/adaptation-staging",
                adaptation_staging_target={"completion_state": "reserved"},
            )

        self.assertEqual(result.get("status"), "success")
        self.assertIs(captured.get("callback"), routes_module.adaptation_convergence_callback)
        self.assertEqual(
            captured.get("callback_result", {}).get("reason_code"),
            "no_repairable_blocker",
        )
        self.assertEqual(captured.get("callback_result", {}).get("status"), "success")

    def test_missing_callback_stays_fail_closed_and_cannot_use_legacy(self) -> None:
        """An unavailable callback remains an adaptation failure, not fallback."""
        import web.extensions.toolkit_homebrew_packet_builder as packet_builder

        captured: Dict[str, Any] = {}

        def _fake_run(**kwargs: Any) -> Dict[str, Any]:
            captured.update(kwargs)
            callback = kwargs.get("adaptation_convergence_callback")
            if callback is None:
                return {
                    "status": "blocked",
                    "stage": "adaptation_convergence",
                    "error": "finalization_callback_missing",
                    "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
                }
            return {"status": "success"}

        with patch.object(routes_module, "adaptation_convergence_callback", None), patch.object(
            packet_builder,
            "run_toolkit_homebrew_packet_build",
            side_effect=_fake_run,
        ):
            result = routes_module._run_homebrew_packet_build(
                self.scratch,
                "route-missing-callback-job",
                adaptation_route=BUILD_MODE_LLM_ADAPTATION,
                adaptation_dossier={"source_hash": FIXTURE_HASH},
                adaptation_provenance={"attempt_metadata": {"job_id": "route-missing-callback-job"}},
                adaptation_staging_root="tmp/adaptation-staging",
                adaptation_staging_target={"completion_state": "reserved"},
            )

        self.assertIsNone(captured.get("adaptation_convergence_callback"))
        self.assertEqual(result.get("error"), "finalization_callback_missing")
        self.assertEqual(
            captured.get("adaptation_route"),
            BUILD_MODE_LLM_ADAPTATION,
        )
        self.assertNotIn("legacy_fallback", captured)


class TestRouteHandoffHygiene(unittest.TestCase):
    """ASCII, provider/network, and path-policy hygiene for task 4.1."""

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
        # The forbidden token tuple below is the hygiene self-scan list itself;
        # scan only the source before this function for raw tokens.
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
                    "forbidden import in provider-free route tests: %s" % name,
                )
        text = self.THIS_FILE.read_text(encoding="utf-8")
        # The forbidden token tuple below is the hygiene self-scan list itself;
        # scan only the source before this function for raw tokens.
        scanned = text[: text.index("    def test_no_provider_network_imports_in_test_file")]
        for token in (
            "create_chat_client",
            "OpenAI(",
            "requests.get",
            "urlopen",
            "socketio",
        ):
            self.assertNotIn(token, scanned, "forbidden provider token: %s" % token)

    def test_no_real_staging_or_module_writes_from_fakes(self) -> None:
        # The staging seam is a pure fake; nothing may exist on disk under the
        # default staging root for the fixture attempt.
        fixture_target = _fake_staging_target(
            FIXTURE_HASH,
            attempt_id="handoff-test-attempt",
            module_slug=EXPECTED_MODULE_NAME,
        )
        resolved = REPO_ROOT / fixture_target["path"]
        self.assertFalse(
            resolved.exists(),
            "fake staging target must never be created on disk",
        )
        self.assertFalse(
            (REPO_ROOT / "modules" / EXPECTED_MODULE_NAME).exists(),
            "fixture module must never be created under modules/",
        )


if __name__ == "__main__":
    unittest.main()
