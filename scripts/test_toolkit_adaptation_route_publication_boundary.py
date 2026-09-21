# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free route-level publication-boundary verification
(task 6.4 of toolkit-llm-adaptation-runtime-unification).

The suite drives the REAL route entry points for BOTH input boundaries --
``web/routes/toolkit_homebrew_routes._run_homebrew_build_job`` for uploaded
adventures and ``web/extensions/toolkit_text_adaptation_worker
.run_text_description_adaptation_publication`` for text descriptions -- and
proves that no registry or campaign write can occur before every
pre-registration gate passes:

  * the staged build and ALL pre-registration gates (schema, readiness,
    mechanical/semantic validation, report agreement, Markdown quality) run
    before any registry integration;
  * registry integration is the final stateful publication step;
  * registry/module/area post-write verification happens before campaign
    synchronization;
  * campaign visibility is verified before completion;
  * for every injected pre-gate failure (readiness, schema, semantic,
    report agreement, Markdown quality) the registry/campaign stage calls are
    NOT made and the protected registry/campaign/module sentinels stay
    byte-identical;
  * successful paths report completion ONLY after the verified publication
    transaction (never from raw build success) and carry the exact
    registry-last / campaign-after-verification event order;
  * a post-write verification failure is never reported as success and rolls
    back the attempt's entries;
  * the legacy upload route (flag disabled) never engages the adaptation
    publication transaction.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_route_publication_boundary/<uuid>/`` and are removed
via addCleanup. No OS temp directory, no provider/network calls, and no real
``modules/``, registry, campaign, or runtime mutation: the module output and
the reserved staging targets stay inside the per-test scratch, the registry
and campaign files under the scratch ``modules/`` mirror are the only runtime
files touched, and real module/registry/campaign sentinels are byte-checked.
The real upload route seams (authoring result, staging reservation, packet
build, readiness gate) are injected fakes; the REAL shared finisher
transaction runs behind deterministic stage seams (captured Markdown stage,
chdir-scoped real registry stage, recorded campaign seam, injectable
post-write registry verification seam).
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.extensions.toolkit_module_finisher as finisher
import web.extensions.toolkit_text_adaptation_worker as text_worker
import web.routes.toolkit_homebrew_routes as routes_module
import utils.toolkit_adaptation_campaign as campaign_sync
import utils.toolkit_adaptation_registry as registry
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LLM_ADAPTATION,
    ROUTE_DECISION_STATUS_ADAPTATION,
)
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_adaptation_staging import create_adaptation_staging_target
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
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_route_publication_boundary"
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
ROUTES_MODULE_PATH = REPO_ROOT / "web" / "routes" / "toolkit_homebrew_routes.py"
MODULE_NAME = "Sunken_Lighthouse"
JOB_ID = "route-publication-boundary-job"
TEXT_JOB_ID = "route-publication-boundary-text-job"
ATTEMPT_NUMBER = 1
ATTEMPT_ID = "route-publication-boundary-attempt"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

EXPECTED_PUBLICATION_ORDER = [
    "schema",
    "readiness",
    "mechanical_closure",
    "semantic_authority",
    "semantic_probes",
    "report_agreement",
    "markdown",
    "registry",
]

# Pre-registration gate failure variants shared by both input routes.
# Each entry is (label, packet-build gates, seam summary override, expected
# finisher stage events). A blocked gate inside the gates envelope fails the
# finisher gate-order recheck before Markdown/registry; a failed Markdown
# summary fails after the Markdown stage and before registry.


def _blocked_gates_with(domain: str) -> Dict[str, Any]:
    gates = _passing_gates()
    gates["gates"][domain] = {
        "status": "blocked",
        "effective_status": "blocked",
        "blockers": ["route_publication_boundary_fixture"],
    }
    return gates


def _blocked_report_agreement_gates() -> Dict[str, Any]:
    gates = _passing_gates()
    gates["gates"]["report_agreement"] = {
        "status": "blocked",
        "effective_status": "blocked",
        "playable_publication_status": "blocked",
        "agreement": {"playable_publication_status": "blocked"},
    }
    return gates


def _failed_summary() -> Dict[str, Any]:
    return {
        "status": "failed",
        "reason": "summary_missing_markdown_heading",
        "quality": {"valid": False},
    }


def _pre_gate_variants() -> List[Tuple[str, Any, Any, List[str]]]:
    """Return the pre-registration gate failure variants lazily so fixture
    helpers are fully defined before use."""
    return [
        ("schema", _blocked_gates_with("schema"), None, []),
        (
            "semantic_authority",
            _blocked_gates_with("semantic_authority"),
            None,
            [],
        ),
        ("report_agreement", _blocked_report_agreement_gates(), None, []),
        ("markdown_quality", _passing_gates(), _failed_summary(), ["markdown"]),
    ]


def _write_json(path: Path, payload: object) -> None:
    """Write a scratch fixture JSON file atomically enough for tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _passing_gates() -> Dict[str, Any]:
    """Return the complete Python-owned pass envelope (finisher contract)."""
    domains = (
        "schema",
        "readiness",
        "mechanical_closure",
        "semantic_authority",
        "semantic_probes",
    )
    gates = {
        domain: {"status": "pass", "effective_status": "pass"}
        for domain in domains
    }
    gates["report_agreement"] = {
        "status": "pass",
        "effective_status": "pass",
        "playable_publication_status": "pass",
        "agreement": {"playable_publication_status": "pass"},
    }
    return {
        "status": "pass",
        "playable_status": "pass",
        "candidate_eligible": True,
        "gates": gates,
        "publication": {
            "authority": "python",
            "attempted": False,
            "allowed": False,
        },
    }


def _load_fixture_dossier() -> Dict[str, Any]:
    """Load the repository's validated build-ready dossier fixture."""
    with FIXTURE_DOSSIER_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dossier_for_attempt(attempt_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Build a schema-valid dossier whose Python-owned identity matches the
    attempt metadata produced by the authoring preflight."""
    dossier = deepcopy(_load_fixture_dossier())
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
    ) -> None:
        self.calls: list = []
        self.dossier_builder = dossier_builder

    def __call__(
        self,
        source_context: Any,
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append((deepcopy(dict(attempt_metadata or {})), dict(kwargs)))
        dossier = (
            self.dossier_builder(dict(attempt_metadata or {}))
            if self.dossier_builder
            else None
        )
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {
                "model": "mock-adaptation-model",
                "request_id": "req-route-publication-boundary-6-4",
            },
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


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
        "assumptions": ["Fixture packet for the route publication boundary tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }
    persist_normalized_packet_artifact(ws, packet)
    snapshot = build_review_snapshot(
        job_id=JOB_ID,
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
    expected_module_name: str = MODULE_NAME,
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


def _ready_authoring_result(
    job_id: str, source_hash: str, attempt_id: str = ATTEMPT_ID
) -> Dict[str, Any]:
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
            "attempt_id": attempt_id,
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": job_id,
        },
        "source_identity": {
            "source_title": "Sunken Lighthouse",
            "source_hash": source_hash,
            "source_path": "tmp/route-publication-boundary/workspace/source_original.md",
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
            "dossier_artifact_path": "tmp/route-publication-boundary/attempts/%s/adaptation_dossier.json" % attempt_id,
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


def _rights_basis_mismatch_authoring_result(job_id: str) -> Dict[str, Any]:
    """Build a production-shaped blocked authoring adapter result for a
    provider dossier that paraphrases the Python-owned ``rights_basis``.

    Python owns the canonical upload token ``user_authored_uploaded_adventure``;
    the injected provider dossier replaces it with explanatory prose, so the
    adapter result is blocked with the bounded ``rights_or_provenance_mismatch``
    reason naming ``rights_basis``.
    """
    dossier = _load_fixture_dossier()
    dossier["source_hash"] = FIXTURE_HASH
    dossier["source_title"] = "Sunken Lighthouse"
    dossier["source_profile"] = dossier.get("source_profile") or "unknown"
    dossier["rights_class"] = RIGHTS_CLASS_USER_AUTHORED
    dossier["rights_basis"] = (
        "The operator attested that the uploaded source is user-authored."
    )
    dossier["rights_review_required"] = False
    dossier["rights_review_status"] = "not_required"
    dossier["adaptation_mode"] = BUILD_MODE_LLM_ADAPTATION
    mismatch_diagnostic = {
        "code": "rights_or_provenance_mismatch",
        "message": "provider changed Python-owned provenance metadata on rights_basis",
        "path": "rights_basis",
    }
    return {
        "contract_version": "toolkit_adaptation_authoring_adapter.v1",
        "status": "blocked",
        "outcome": "blocked",
        "ok": False,
        "input_kind": "upload_markdown",
        "route": _route_authority(),
        "attempt": {
            "attempt_id": "rights-basis-mismatch-attempt",
            "attempt_number": 1,
            "revision_number": 0,
            "job_id": job_id,
        },
        "source_identity": {
            "source_title": "Sunken Lighthouse",
            "source_hash": FIXTURE_HASH,
            "source_path": "tmp/route-publication-boundary/workspace/source_original.md",
        },
        "rights": {
            "rights_class": RIGHTS_CLASS_USER_AUTHORED,
            "rights_basis": "user_authored_uploaded_adventure",
            "rights_review_required": False,
            "rights_review_status": "not_required",
            "python_owned": True,
            "provider_may_change": False,
        },
        "world_context": build_world_context_provenance(None),
        "staging": {},
        "model_metadata": {"provider": "openai", "model": "gpt-5.6-luna"},
        "authoring": {
            "authoring_attempted": True,
            "authoring_status": "blocked",
            "authoring_ok": False,
            "attempt_id": "rights-basis-mismatch-attempt",
            "diagnostics": [deepcopy(mismatch_diagnostic)],
            "safe_class": "rights_or_provenance",
            "reason_code": "rights_or_provenance_mismatch",
            "revision_eligible": False,
            "retryable": False,
            "terminal": True,
        },
        "dossier": dossier,
        "guards": {
            "module_builder_allowed": False,
            "module_builder_started": False,
            "publication_started": False,
            "registry_mutated": False,
            "completed_module_artifacts": [],
            "selected_route_authoritative": True,
        },
        "diagnostics": [deepcopy(mismatch_diagnostic)],
    }


def _write_staged_module(module_dir: Path, module_slug: str) -> None:
    """Write the deterministic staged module output consumed by the finisher.

    Mirrors the schema-lite staged fixture used by the completed scaffold
    rollback tests so the real registry entry builder and provenance stage can
    consume it without any provider work.
    """
    _write_json(
        module_dir / "module_context.json",
        {"module_id": module_slug, "areas": {"ADP001": {}}},
    )
    _write_json(
        module_dir / "module_plot.json",
        {
            "mainObjective": "Recover the drowned bell.",
            "plotPoints": [
                {"id": "PP001", "description": "The bell is missing."}
            ],
        },
    )
    _write_json(
        module_dir / "areas" / "ADP001.json",
        {
            "areaId": "ADP001",
            "areaName": "Drowned Bell Chamber",
            "areaDescription": "A flooded stone chamber with a broken bell.",
            "areaType": "dungeon",
            "dangerLevel": "medium",
            "recommendedLevel": 1,
            "climate": "temperate",
            "terrain": "underdark",
            "areaConnectivity": [],
            "areaConnectivityId": [],
            "locations": [
                {"locationId": "ADP001L01", "locationName": "Bell Pit"}
            ],
        },
    )


@contextlib.contextmanager
def _chdir(path: Path) -> Any:
    """Temporarily change the process working directory."""
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


_PASSING_VERIFICATION: Dict[str, Any] = {
    "status": "success",
    "verified": True,
    "module_verified": True,
    "areas_verified": True,
    "module_slug": MODULE_NAME,
    "verified_area_ids": ["ADP001"],
    "mismatches": [],
}

_BLOCKED_VERIFICATION: Dict[str, Any] = {
    "status": "blocked",
    "verified": False,
    "module_verified": False,
    "areas_verified": False,
    "module_slug": MODULE_NAME,
    "verified_area_ids": [],
    "mismatches": [{"field": "module", "reason": "missing"}],
}


class _StagedBuildFake:
    """Route-level staged build fake shared by both input boundaries.

    Echoes the reserved adaptation staging target received through the
    adaptation packet kwargs, writes the deterministic staged module into that
    target, and returns the bounded adaptation build result (mode, gates,
    staging target, provenance, artifact workspace). The result shape is
    exactly the one ``_run_homebrew_finisher`` and the text publication stage
    consume for the shared finisher transaction.
    """

    def __init__(
        self, gates: Optional[Dict[str, Any]] = None
    ) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.gates = gates

    def __call__(
        self, workspace: Any, job_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        record: Dict[str, Any] = {"workspace": str(workspace), "job_id": job_id}
        record.update(dict(kwargs))
        self.calls.append(record)
        target = kwargs.get("adaptation_staging_target")
        if not isinstance(target, Mapping) or not str(
            target.get("path") or ""
        ).strip():
            return {
                "status": "failed",
                "stage": "build",
                "error": "fixture_staging_target_missing",
                "job_id": job_id,
            }
        module_dir = REPO_ROOT / str(target["path"])
        _write_staged_module(module_dir, MODULE_NAME)
        result: Dict[str, Any] = {
            "status": "success",
            "stage": "build",
            "job_id": job_id,
            "module_name": MODULE_NAME,
            "output_directory": str(target["path"]),
            "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
            "adaptation_gates": (
                deepcopy(self.gates)
                if self.gates is not None
                else _passing_gates()
            ),
            "staging_target": dict(target),
            "adaptation_provenance": (
                dict(kwargs["adaptation_provenance"])
                if isinstance(kwargs.get("adaptation_provenance"), Mapping)
                else {}
            ),
            "adaptation_artifact_workspace": str(workspace),
        }
        # The real packet builder persists the Python-owned build-result
        # artifact before the finisher's report-agreement boundary; mirror
        # that so the real finisher transaction can consume the attempt
        # workspace exactly like a live adaptation build.
        try:
            from web.extensions.toolkit_homebrew_packet_builder import (
                _persist_adaptation_attempt_report,
            )

            _persist_adaptation_attempt_report(
                workspace=Path(str(workspace)),
                job_id=job_id,
                build_result=result,
                adaptation_handoff={
                    "dossier": (
                        dict(kwargs["adaptation_dossier"])
                        if isinstance(kwargs.get("adaptation_dossier"), Mapping)
                        else {}
                    ),
                    "provenance": result["adaptation_provenance"],
                },
                staging_target=dict(target),
                build_started_at=None,
            )
        except Exception:
            # The staged-build fixture must never fail the route because the
            # optional attempt-report persistence helper is unavailable; the
            # publication-boundary assertions below remain authoritative.
            pass
        return result


class _FakeReadiness:
    """Readiness gate fake with a configurable outcome status."""

    def __init__(self, status: str = "ready_for_finishing") -> None:
        self.status = status

    def __call__(
        self, artifact_workspace: Any, job_id: str, state_callback: Any = None
    ) -> Dict[str, Any]:
        if state_callback:
            state_callback(
                self.status,
                {"status": self.status, "module_name": MODULE_NAME},
            )
        return {"status": self.status, "module_name": MODULE_NAME}


class _FinisherSeams:
    """Deterministic seams over the REAL shared adaptation finisher.

    Records the exact stage call order (``markdown`` -> ``registry`` ->
    ``campaign``) and the post-write registry verification calls. The
    Markdown stage is captured (the real one calls the LLM); the real registry
    stage runs under a scratch-scoped chdir so its derived
    ``modules/world_registry.json`` path resolves inside the per-test scratch
    mirror and never touches the real runtime registry. The campaign seam
    records and delegates to the real synchronizer, and the registry
    post-write verification seam is injectable.
    """

    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch
        self.events: List[str] = []
        self.verify_calls: List[Dict[str, Any]] = []
        self.verify_result: Optional[Dict[str, Any]] = None
        self.summary_result: Optional[Dict[str, Any]] = None
        self._patchers: List[Any] = []

    def __enter__(self) -> "_FinisherSeams":
        real_registry_stage = finisher._run_registry_stage
        real_campaign_sync = campaign_sync.synchronize_adaptation_campaign_module
        real_verify = registry.verify_adaptation_registry_entries

        def _summary(module_slug: str, module_dir: Any, **kwargs: Any) -> Dict[str, Any]:
            self.events.append("markdown")
            if self.summary_result is not None:
                return dict(self.summary_result)
            return {
                "status": "success",
                "path": str(Path(module_dir) / "MODULE_SUMMARY.md"),
                "bytes": 256,
                "quality": {"valid": True, "reason": "readable_markdown"},
            }

        def _registry(
            module_slug: str, *, module_dir: Any = None, adaptation: bool = False
        ) -> Dict[str, Any]:
            self.events.append("registry")
            with _chdir(self.scratch):
                return real_registry_stage(
                    module_slug, module_dir=module_dir, adaptation=adaptation
                )

        def _campaign(slug: str, **kwargs: Any) -> Dict[str, Any]:
            self.events.append("campaign")
            return real_campaign_sync(slug, **kwargs)

        def _verify(registry_path: Any, expected: Any) -> Dict[str, Any]:
            self.verify_calls.append({"registry_path": str(registry_path)})
            if self.verify_result is not None:
                return dict(self.verify_result)
            return real_verify(registry_path, expected)

        self._patchers = [
            patch.object(
                finisher, "_run_module_summary_stage", side_effect=_summary
            ),
            patch.object(
                finisher, "_run_registry_stage", side_effect=_registry
            ),
            patch.object(
                campaign_sync,
                "synchronize_adaptation_campaign_module",
                side_effect=_campaign,
            ),
            patch.object(
                registry,
                "verify_adaptation_registry_entries",
                side_effect=_verify,
            ),
        ]
        for patcher in self._patchers:
            patcher.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers = []


class _RoutePublicationScratchMixin:
    """Provide a unique project-local scratch root removed after each test."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.staging_root = (
            "tmp/toolkit_adaptation_route_publication_boundary"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.workspaces_root = (
            "tmp/toolkit_adaptation_route_publication_boundary"
            + "/"
            + self.scratch.name
            + "/workspaces"
        )
        self.registry_path = self.scratch / "modules" / "world_registry.json"
        self.campaign_path = self.scratch / "modules" / "campaign.json"
        self.original_registry: Dict[str, Any] = {
            "worldName": "Route Boundary Fixture World",
            "registryVersion": "1.0.0",
            "modules": {
                "Sentinel_Module": {"moduleName": "Sentinel_Module", "areaCount": 1},
            },
            "areas": {
                "SNT001": {"module": "Sentinel_Module", "areaName": "Sentinel Hall"},
            },
            "themes": {"fixture": "preserve"},
            "isolatedModules": True,
        }
        _write_json(self.registry_path, self.original_registry)
        self.original_campaign: Dict[str, Any] = {
            "campaignName": "Route Boundary Fixture Campaign",
            "availableModules": ["Sentinel_Module"],
            "active": True,
            "currentModule": "Sentinel_Module",
        }
        _write_json(self.campaign_path, self.original_campaign)
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

    def _real_module_sentinels(self) -> Dict[str, Any]:
        """Snapshot real modules/ listing plus registry/campaign bytes."""
        modules_dir = REPO_ROOT / "modules"
        listing: list = []
        if modules_dir.exists():
            listing = sorted(
                str(p.relative_to(REPO_ROOT))
                for p in modules_dir.rglob("*")
                if p.is_file()
            )
        registry_path = REPO_ROOT / "modules" / "world_registry.json"
        campaign_path = REPO_ROOT / "modules" / "campaign.json"
        registry_bytes = registry_path.read_bytes() if registry_path.exists() else None
        campaign_bytes = campaign_path.read_bytes() if campaign_path.exists() else None
        return {
            "listing": listing,
            "registry_bytes": registry_bytes,
            "campaign_bytes": campaign_bytes,
        }

    def _assert_real_sentinels_unchanged(self, snapshot: Dict[str, Any]) -> None:
        modules_dir = REPO_ROOT / "modules"
        listing = (
            sorted(
                str(p.relative_to(REPO_ROOT))
                for p in modules_dir.rglob("*")
                if p.is_file()
            )
            if modules_dir.exists()
            else []
        )
        self.assertEqual(listing, snapshot["listing"])
        registry_path = REPO_ROOT / "modules" / "world_registry.json"
        campaign_path = REPO_ROOT / "modules" / "campaign.json"
        self.assertEqual(
            registry_path.read_bytes() if registry_path.exists() else None,
            snapshot["registry_bytes"],
        )
        self.assertEqual(
            campaign_path.read_bytes() if campaign_path.exists() else None,
            snapshot["campaign_bytes"],
        )
        self.assertFalse((REPO_ROOT / "modules" / MODULE_NAME).exists())

    def _scratch_publication_bytes(self) -> Tuple[bytes, bytes]:
        return (
            self.registry_path.read_bytes(),
            self.campaign_path.read_bytes(),
        )

    def _assert_no_scratch_registry_campaign_mutation(
        self, before: Tuple[bytes, bytes]
    ) -> None:
        self.assertEqual(self.registry_path.read_bytes(), before[0])
        self.assertEqual(self.campaign_path.read_bytes(), before[1])

    def _staging_into_scratch(self, source_hash: str, **kwargs: Any) -> Dict[str, Any]:
        kwargs.pop("staging_root", None)
        return create_adaptation_staging_target(
            source_hash,
            staging_root=self.staging_root,
            **kwargs,
        )

    def _run_upload_route(
        self,
        job_id: str,
        *,
        readiness_status: str = "ready_for_finishing",
        gates: Optional[Dict[str, Any]] = None,
        seams: Optional[_FinisherSeams] = None,
        attempt_id: str = ATTEMPT_ID,
        authoring_result: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], _StagedBuildFake, _FinisherSeams]:
        """Run the REAL upload route ``_run_homebrew_build_job`` with the REAL
        shared finisher behind deterministic seams."""
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        packet_fake = _StagedBuildFake(gates=gates)
        readiness_fake = _FakeReadiness(status=readiness_status)
        seams_obj = seams if seams is not None else _FinisherSeams(self.scratch)
        authoring_payload = (
            authoring_result
            if authoring_result is not None
            else _ready_authoring_result(job_id, FIXTURE_HASH, attempt_id=attempt_id)
        )
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "run_upload_adaptation_authoring",
            return_value=authoring_payload,
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=self._staging_into_scratch,
        ), patch.object(
            routes_module, "_run_homebrew_packet_build", side_effect=packet_fake
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=readiness_fake
        ), seams_obj:
            routes_module._run_homebrew_build_job(job_id)
        return self._snapshot_job(job_id), packet_fake, seams_obj

    def _run_text_route(
        self,
        *,
        gates: Optional[Dict[str, Any]] = None,
        seams: Optional[_FinisherSeams] = None,
        job_id: str = TEXT_JOB_ID,
    ) -> Tuple[Dict[str, Any], _StagedBuildFake, _FinisherSeams]:
        """Run the REAL text-description publication entry point with the REAL
        shared finisher behind deterministic seams and the real task 5.1 seam
        with scratch-redirected workspace/staging builders."""
        real_workspace_builder = text_worker.build_text_description_attempt_workspace
        real_staging_creator = text_worker.create_adaptation_staging_target

        def _build_ws_into_scratch(module_name: str, concept: Any, **kw: Any) -> Any:
            return real_workspace_builder(
                module_name,
                concept,
                workspace_root=self.workspaces_root,
                staging_root=self.staging_root,
                **kw,
            )

        def _create_staging_into_scratch(source_hash: str, **kw: Any) -> Any:
            kw.pop("staging_root", None)
            return real_staging_creator(
                source_hash,
                staging_root=self.staging_root,
                **kw,
            )

        seams_obj = seams if seams is not None else _FinisherSeams(self.scratch)
        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            text_worker,
            "build_text_description_attempt_workspace",
            side_effect=_build_ws_into_scratch,
        ), patch.object(
            text_worker,
            "create_adaptation_staging_target",
            side_effect=_create_staging_into_scratch,
        ):
            seam_result = text_worker.run_text_description_adaptation_seam(
                MODULE_NAME,
                FIXTURE_TEXT,
                {"job_id": job_id},
                author_runner=FakeAuthorRunner(dossier_builder=_dossier_for_attempt),
                model="mock-adaptation-model",
            )
        self.assertIsNotNone(seam_result)
        self.assertEqual(
            seam_result["outcome"], "authoring_ready_pending_publication"
        )
        build_fake = _StagedBuildFake(gates=gates)
        with seams_obj:
            publication_result = text_worker.run_text_description_adaptation_publication(
                seam_result,
                build_runner=build_fake,
                finisher_runner=finisher.run_toolkit_module_postbuild_finishing,
            )
        return publication_result, build_fake, seams_obj

    def _assert_pre_gate_blocked_upload(
        self,
        job: Dict[str, Any],
        seams: _FinisherSeams,
        expected_events: List[str],
    ) -> None:
        """Shared assertions for an upload-route pre-gate failure."""
        self.assertEqual(job.get("status"), "adaptation_blocked")
        self.assertEqual(seams.events, expected_events)
        self.assertEqual(seams.verify_calls, [])
        result = job.get("result") or {}
        registry_stage = (result.get("stages") or {}).get("registry") or {}
        self.assertEqual(registry_stage.get("status"), "not_attempted")
        campaign_stage = (result.get("stages") or {}).get("campaign_sync") or {}
        self.assertNotEqual(
            campaign_stage.get("status"), "success",
            "campaign must never report success before pre-registration gates pass",
        )

    def _assert_pre_gate_blocked_text(
        self,
        publication_result: Dict[str, Any],
        seams: _FinisherSeams,
        expected_events: List[str],
    ) -> None:
        """Shared assertions for a text-route pre-gate failure."""
        self.assertEqual(publication_result.get("outcome"), "blocked")
        self.assertEqual(publication_result.get("status"), "failed_closed")
        self.assertEqual(seams.events, expected_events)
        self.assertEqual(seams.verify_calls, [])
        publication = publication_result.get("adaptation_publication") or {}
        self.assertEqual(publication.get("registry_status"), "not_attempted")
        self.assertEqual(publication.get("campaign_sync_status"), "not_attempted")
        self.assertEqual(publication.get("rollback_status"), "not_attempted")


class TestUploadRoutePreGatePublicationBoundary(
    _RoutePublicationScratchMixin, unittest.TestCase
):
    """The upload route cannot reach registry or campaign before the
    readiness gate and every pre-registration gate passes."""

    def test_readiness_gate_failure_stops_before_finisher_registry_campaign(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        scratch_before = self._scratch_publication_bytes()
        job, packet_fake, seams = self._run_upload_route(
            "route-readiness-blocked-job",
            readiness_status="repair_budget_exhausted",
        )
        # The readiness gate is a pre-registration gate: the finisher (and
        # therefore Markdown/registry/campaign) is never reached.
        self.assertEqual(job.get("status"), "adaptation_blocked")
        self.assertEqual(job.get("adaptation_failure_surface"), "readiness")
        self.assertEqual(seams.events, [])
        self.assertEqual(seams.verify_calls, [])
        self.assertEqual(len(packet_fake.calls), 1)
        self._assert_no_scratch_registry_campaign_mutation(scratch_before)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_pre_registration_gate_failures_never_reach_registry_or_campaign(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        for label, gates, summary, expected_events in _pre_gate_variants():
            with self.subTest(input_kind="upload", failure=label):
                scratch_before = self._scratch_publication_bytes()
                seams = _FinisherSeams(self.scratch)
                seams.summary_result = summary
                variant_slug = label.replace("_", "-")
                job, _packet_fake, seams = self._run_upload_route(
                    "route-pregate-%s-job" % variant_slug,
                    gates=gates,
                    seams=seams,
                    attempt_id="route-pregate-%s-attempt" % variant_slug,
                )
                self._assert_pre_gate_blocked_upload(job, seams, expected_events)
                self._assert_no_scratch_registry_campaign_mutation(scratch_before)
                self._assert_real_sentinels_unchanged(sentinels)


class TestUploadRouteRightsBasisMismatchBoundary(
    _RoutePublicationScratchMixin, unittest.TestCase
):
    """A provider dossier that paraphrases the Python-owned rights_basis is
    rejected with the structured rights/provenance mismatch before any
    ModuleBuilder or publication invocation. The mismatch never consumes
    semantic revision budget, never selects legacy fallback, and never mutates
    module, registry, or campaign sentinels."""

    def test_rights_basis_paraphrase_stops_before_builder_and_publication(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        scratch_before = self._scratch_publication_bytes()
        seams = _FinisherSeams(self.scratch)
        job_id = "route-rights-basis-mismatch-job"
        job, packet_fake, seams = self._run_upload_route(
            job_id,
            seams=seams,
            attempt_id="rights-basis-mismatch-attempt",
            authoring_result=_rights_basis_mismatch_authoring_result(job_id),
        )

        # The route records the structured rights/provenance mismatch and
        # terminates before any ModuleBuilder or publication invocation.
        self.assertEqual(job.get("status"), "adaptation_blocked")
        self.assertEqual(job.get("adaptation_failure_surface"), "policy")
        result = job.get("result") or {}
        self.assertEqual(result.get("stage"), "authoring")
        self.assertEqual(result.get("error"), "rights_or_provenance_mismatch")
        classification = result.get("failure_classification") or {}
        self.assertEqual(classification.get("failure_class"), "rights")
        self.assertEqual(classification.get("failure_group"), "validation")
        self.assertEqual(
            classification.get("code"), "rights_or_provenance_mismatch"
        )
        self.assertIs(classification.get("revision_eligible"), False)
        self.assertIs(classification.get("semantic_revision_eligible"), False)
        diagnostics = result.get("diagnostics") or []
        self.assertTrue(
            any(
                isinstance(item, Mapping)
                and item.get("code") == "rights_or_provenance_mismatch"
                and "rights_basis" in str(item.get("message") or "")
                for item in diagnostics
            ),
            f"mismatch diagnostic naming rights_basis missing: {diagnostics!r}",
        )

        # ModuleBuilder (packet build) and every finisher stage were never
        # invoked.
        self.assertEqual(packet_fake.calls, [])
        self.assertEqual(seams.events, [])
        self.assertEqual(seams.verify_calls, [])

        # The selected adaptation route remains authoritative; no legacy
        # fallback was chosen and no legacy build ran.
        decision = job.get("adaptation_route_decision") or {}
        self.assertEqual(decision.get("status"), ROUTE_DECISION_STATUS_ADAPTATION)
        self.assertEqual(
            decision.get("route_selected"), BUILD_MODE_LLM_ADAPTATION
        )
        self.assertIs(decision.get("fallback_allowed"), False)

        # Sentinel module, registry, and campaign artifacts are unchanged.
        self._assert_no_scratch_registry_campaign_mutation(scratch_before)
        self._assert_real_sentinels_unchanged(sentinels)


class TestUploadRouteSuccessPublicationOrdering(
    _RoutePublicationScratchMixin, unittest.TestCase
):
    """Successful upload publication is registry-last with campaign after
    post-write verification, and never reports success before verification."""

    def test_success_registry_last_campaign_after_post_write_verification(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        seams = _FinisherSeams(self.scratch)
        seams.verify_result = _PASSING_VERIFICATION
        job, packet_fake, seams = self._run_upload_route(
            "route-upload-success-job", seams=seams
        )
        # Completion only after the verified publication transaction.
        self.assertEqual(job.get("status"), "adaptation_completed")
        self.assertEqual(
            seams.events, ["markdown", "registry", "campaign"], "stage order"
        )
        # Registry post-write verification happened BEFORE campaign sync.
        self.assertEqual(len(seams.verify_calls), 1)
        self.assertLess(
            seams.events.index("registry"), seams.events.index("campaign")
        )
        result = job.get("result") or {}
        self.assertEqual(result.get("publication_order"), EXPECTED_PUBLICATION_ORDER)
        self.assertTrue(result.get("registry_is_final_stateful_publication"))
        registry_stage = (result.get("stages") or {}).get("registry") or {}
        self.assertEqual(registry_stage.get("status"), "success")
        self.assertIs(registry_stage.get("verified"), True)
        self.assertIs(registry_stage.get("integration_attempted"), True)
        campaign_stage = (result.get("stages") or {}).get("campaign_sync") or {}
        self.assertEqual(campaign_stage.get("status"), "success")
        self.assertIs(campaign_stage.get("campaign_visibility_verified"), True)
        # The scratch registry mirror actually received the module and the
        # campaign received the availability append after verification.
        persisted_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            persisted_registry["modules"]["Sentinel_Module"],
            self.original_registry["modules"]["Sentinel_Module"],
        )
        self.assertEqual(
            persisted_registry["modules"][MODULE_NAME]["moduleName"], MODULE_NAME
        )
        campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        self.assertEqual(
            campaign["availableModules"], ["Sentinel_Module", MODULE_NAME]
        )
        self.assertEqual(len(packet_fake.calls), 1)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_post_write_verification_failure_no_false_success_and_rollback(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        seams = _FinisherSeams(self.scratch)
        seams.verify_result = _BLOCKED_VERIFICATION
        job, _packet_fake, seams = self._run_upload_route(
            "route-upload-verify-failed-job", seams=seams
        )
        # The raw build success is never a route success: verification failed,
        # so the job is blocked, campaign was never called, and the attempt's
        # entries were rolled back.
        self.assertEqual(job.get("status"), "adaptation_blocked")
        self.assertEqual(seams.events, ["markdown", "registry"])
        self.assertNotIn("campaign", seams.events)
        self.assertEqual(len(seams.verify_calls), 1)
        result = job.get("result") or {}
        registry_stage = (result.get("stages") or {}).get("registry") or {}
        self.assertEqual(
            registry_stage.get("reason"), "registry_post_write_verification_failed"
        )
        rollback = registry_stage.get("rollback") or {}
        self.assertEqual(rollback.get("status"), "success")
        self.assertIs(rollback.get("verified"), True)
        # The failed attempt's entries were removed; sentinels are preserved.
        self.assertEqual(
            json.loads(self.registry_path.read_text(encoding="utf-8")),
            self.original_registry,
        )
        self.assertEqual(
            json.loads(self.campaign_path.read_text(encoding="utf-8")),
            self.original_campaign,
        )
        self._assert_real_sentinels_unchanged(sentinels)


class TestTextRoutePreGatePublicationBoundary(
    _RoutePublicationScratchMixin, unittest.TestCase
):
    """The text-description route cannot reach registry or campaign before
    the staged build and every pre-registration gate passes."""

    def test_build_readiness_blocked_never_invokes_finisher(self) -> None:
        sentinels = self._real_module_sentinels()
        scratch_before = self._scratch_publication_bytes()
        seams = _FinisherSeams(self.scratch)

        def _blocked_build(workspace_path: Any, job_id: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "status": "blocked",
                "stage": "readiness",
                "error": "repair_budget_exhausted",
                "job_id": job_id,
            }

        def _finisher_tripwire(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "the finisher must never run before the staged build gates pass"
            )

        with seams:
            publication_result = text_worker.run_text_description_adaptation_publication(
                self._text_seam_result(),
                build_runner=_blocked_build,
                finisher_runner=_finisher_tripwire,
            )
        self.assertEqual(publication_result.get("outcome"), "blocked")
        self.assertEqual(
            publication_result.get("reason_code"),
            "text_description_adaptation_build_blocked",
        )
        self.assertEqual(seams.events, [])
        self.assertEqual(seams.verify_calls, [])
        self._assert_no_scratch_registry_campaign_mutation(scratch_before)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_pre_registration_gate_failures_never_reach_registry_or_campaign(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        for label, gates, summary, expected_events in _pre_gate_variants():
            with self.subTest(input_kind="text_description", failure=label):
                scratch_before = self._scratch_publication_bytes()
                seams = _FinisherSeams(self.scratch)
                seams.summary_result = summary
                publication_result, _build_fake, seams = self._run_text_route(
                    gates=gates,
                    seams=seams,
                    job_id="route-text-pregate-%s-job" % label.replace("_", "-"),
                )
                self._assert_pre_gate_blocked_text(
                    publication_result, seams, expected_events
                )
                self._assert_no_scratch_registry_campaign_mutation(scratch_before)
                self._assert_real_sentinels_unchanged(sentinels)

    def _text_seam_result(self) -> Dict[str, Any]:
        """Build a ready task 5.1 seam result with scratch-redirected
        workspace/staging builders (no publication side effects)."""
        real_workspace_builder = text_worker.build_text_description_attempt_workspace
        real_staging_creator = text_worker.create_adaptation_staging_target

        def _build_ws_into_scratch(module_name: str, concept: Any, **kw: Any) -> Any:
            return real_workspace_builder(
                module_name,
                concept,
                workspace_root=self.workspaces_root,
                staging_root=self.staging_root,
                **kw,
            )

        def _create_staging_into_scratch(source_hash: str, **kw: Any) -> Any:
            kw.pop("staging_root", None)
            return real_staging_creator(
                source_hash,
                staging_root=self.staging_root,
                **kw,
            )

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            text_worker,
            "build_text_description_attempt_workspace",
            side_effect=_build_ws_into_scratch,
        ), patch.object(
            text_worker,
            "create_adaptation_staging_target",
            side_effect=_create_staging_into_scratch,
        ):
            seam_result = text_worker.run_text_description_adaptation_seam(
                MODULE_NAME,
                FIXTURE_TEXT,
                {"job_id": TEXT_JOB_ID},
                author_runner=FakeAuthorRunner(dossier_builder=_dossier_for_attempt),
                model="mock-adaptation-model",
            )
        self.assertIsNotNone(seam_result)
        self.assertEqual(
            seam_result["outcome"], "authoring_ready_pending_publication"
        )
        return seam_result


class TestTextRouteSuccessPublicationOrdering(
    _RoutePublicationScratchMixin, unittest.TestCase
):
    """Successful text publication is registry-last with campaign after
    post-write verification, and never reports success before verification."""

    def test_success_registry_last_campaign_after_post_write_verification(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        seams = _FinisherSeams(self.scratch)
        seams.verify_result = _PASSING_VERIFICATION
        publication_result, build_fake, seams = self._run_text_route(seams=seams)
        # Completion only after the verified finisher transaction.
        self.assertEqual(publication_result.get("outcome"), "completed")
        self.assertEqual(publication_result.get("status"), "completed")
        self.assertEqual(
            seams.events, ["markdown", "registry", "campaign"], "stage order"
        )
        self.assertEqual(len(seams.verify_calls), 1)
        self.assertLess(
            seams.events.index("registry"), seams.events.index("campaign")
        )
        publication = publication_result.get("adaptation_publication") or {}
        self.assertEqual(publication.get("registry_status"), "success")
        self.assertIs(publication.get("registry_verified"), True)
        self.assertEqual(publication.get("campaign_sync_status"), "success")
        self.assertIs(publication.get("campaign_visibility_verified"), True)
        self.assertIs(publication.get("python_authoritative"), True)
        # The shared transaction actually wrote the scratch mirror.
        persisted_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            persisted_registry["modules"][MODULE_NAME]["moduleName"], MODULE_NAME
        )
        campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        self.assertEqual(
            campaign["availableModules"], ["Sentinel_Module", MODULE_NAME]
        )
        self.assertEqual(len(build_fake.calls), 1)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_post_write_verification_failure_no_false_success_and_rollback(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        seams = _FinisherSeams(self.scratch)
        seams.verify_result = _BLOCKED_VERIFICATION
        publication_result, _build_fake, seams = self._run_text_route(seams=seams)
        # The staged build success is never a route success: verification
        # failed, so the attempt is blocked, campaign was never called, and
        # the attempt's entries were rolled back.
        self.assertEqual(publication_result.get("outcome"), "blocked")
        self.assertEqual(seams.events, ["markdown", "registry"])
        self.assertNotIn("campaign", seams.events)
        self.assertEqual(len(seams.verify_calls), 1)
        publication = publication_result.get("adaptation_publication") or {}
        self.assertEqual(publication.get("registry_status"), "blocked")
        self.assertIs(publication.get("registry_verified"), False)
        self.assertEqual(
            json.loads(self.registry_path.read_text(encoding="utf-8")),
            self.original_registry,
        )
        self.assertEqual(
            json.loads(self.campaign_path.read_text(encoding="utf-8")),
            self.original_campaign,
        )
        self._assert_real_sentinels_unchanged(sentinels)


class TestUploadRouteLegacyIsolation(
    _RoutePublicationScratchMixin, unittest.TestCase
):
    """A disabled (legacy) upload job never engages the adaptation
    publication transaction at the route level."""

    def test_legacy_disabled_job_never_engages_adaptation_publication(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        scratch_before = self._scratch_publication_bytes()
        workspace = _make_workspace(self.scratch, FIXTURE_HASH)
        job_id = "route-legacy-isolation-job"
        _register_job(job_id, workspace)
        self.job_ids.append(job_id)
        recorded: List[Dict[str, Any]] = []

        def _fake_finisher(module_slug: str, build_result: Any = None) -> Dict[str, Any]:
            recorded.append(dict(build_result or {}))
            return {
                "status": "completed",
                "ready_status": "pass",
                "publishable_status": "pass",
                "module_name": module_slug,
            }

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", False
        ), patch.object(
            routes_module, "_run_homebrew_packet_build"
        ) as packet_fake, patch.object(
            routes_module, "_run_homebrew_readiness_gate"
        ) as readiness_fake, patch.object(
            routes_module, "_run_homebrew_finisher", side_effect=_fake_finisher
        ):
            packet_fake.return_value = {
                "status": "success",
                "module_name": MODULE_NAME,
                "output_directory": str(self.scratch / "staged"),
            }
            readiness_fake.return_value = {
                "status": "ready_for_finishing",
                "module_name": MODULE_NAME,
            }
            routes_module._run_homebrew_build_job(job_id)

        job = self._snapshot_job(job_id)
        self.assertEqual(job.get("status"), "completed")
        self.assertEqual(len(recorded), 1)
        # The legacy finisher input carries no adaptation publication fields.
        for key in (
            "adaptation_mode",
            "adaptation_gates",
            "staging_target",
            "adaptation_provenance",
        ):
            self.assertNotIn(key, recorded[0])
        for key in (
            "adaptation_job",
            "adaptation_mode",
            "adaptation_route_decision",
            "adaptation_attempt_id",
            "adaptation_build_handoff",
        ):
            self.assertNotIn(key, job)
        self._assert_no_scratch_registry_campaign_mutation(scratch_before)
        self._assert_real_sentinels_unchanged(sentinels)


class TestRoutePublicationBoundaryHygiene(unittest.TestCase):
    """Changed files follow SPDX/ASCII rules, stay OS-temp free, use
    project-relative scratch only, and never import provider/network code."""

    def test_own_file_is_ascii_and_spdx(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)
        non_ascii = [ch for ch in text if ord(ch) >= 128]
        self.assertEqual(non_ascii, [])

    def test_no_os_temp_or_absolute_scratch_paths(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("def test_no_os_temp_or_absolute_scratch_paths", 1)[0]
        for token in ("tempfile", "TemporaryDirectory", "/tmp", "/var/folders"):
            with self.subTest(token=token):
                self.assertNotIn(token, scan)

    def test_scratch_is_project_relative(self) -> None:
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))
        own_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "toolkit_adaptation_route_publication_boundary", own_source
        )

    def test_no_provider_network_or_host_imports(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("def test_no_provider_network_or_host_imports", 1)[0]
        module = ast.parse(scan, filename="route_publication_boundary_test.py")
        forbidden_roots = {
            "openai",
            "httpx",
            "requests",
            "urllib",
            "socket",
            "socketio",
            "flask",
            "tempfile",
        }
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = str(alias.name or "").split(".")[0]
                    self.assertNotIn(
                        root,
                        forbidden_roots,
                        "provider/network/host import in route boundary test",
                    )
            elif isinstance(node, ast.ImportFrom):
                root = str(node.module or "").split(".")[0]
                self.assertNotIn(
                    root,
                    forbidden_roots,
                    "provider/network/host import in route boundary test",
                )


if __name__ == "__main__":
    unittest.main()
