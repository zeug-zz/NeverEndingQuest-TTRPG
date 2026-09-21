# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free both-input staging/publication transaction verification
(task 6.2 of toolkit-llm-adaptation-runtime-unification).

The suite drives the REAL upload boundary (``build_upload_adaptation_handoff``
+ ``run_upload_adaptation_authoring`` + the route provenance builder + a real
reserved staging target) and the REAL text-description boundary (the task 5.1
seam with scratch-redirected workspace/staging builders) through the completed
shared publication transaction and proves, for BOTH inputs:

  * initial adaptation staging is isolated and project-relative, never
    overwrites an existing registered module or a prior attempt, and is
    reserved exactly once;
  * semantic/revision rebuilds receive a DISTINCT fresh staging target,
    preserve the prior attempt and staging metadata for diagnostics/rollback,
    and never overwrite ``revision_000``;
  * the shared gate order is explicit and identical: staged build ->
    schema/readiness/mechanical/semantic/report-agreement -> Markdown quality
    -> registry integration as the final stateful publication -> post-write
    registry/area verification -> campaign synchronization/visibility ->
    completion, reported only after verification;
  * no registry or campaign mutation occurs before every pre-registration
    gate passes; pre-gate failures remain blocked/failed;
  * a post-registration verification or campaign failure triggers targeted
    rollback that restores/removes ONLY entries created by the failed attempt,
    preserves unrelated sentinel entries, records rollback diagnostics, and
    never reports success;
  * legacy/default transaction and payload behavior is preserved and
    adaptation-only staging/report metadata never leaks to the legacy route.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_both_inputs_transaction/<uuid>/`` and are removed via
addCleanup. No OS temp directory, no provider/network calls, no live
model_config dependency (flags patched explicitly), and no real
``modules/``, registry, campaign, or runtime mutation: the module output and
the reserved staging targets stay inside the per-test scratch, the registry
and campaign files under the scratch ``modules/`` mirror are the only runtime
files touched, and real module/registry/campaign sentinels are byte-checked.
Deterministic injected author/build/finisher/registry/campaign seams are used
(FakeAuthorRunner, captured summary stage, chdir-scoped real registry stage,
recorded campaign seam).
"""

from __future__ import annotations

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
from typing import Any, Callable, Dict, List, Mapping, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
import web.extensions.toolkit_text_adaptation_worker as text_worker
import web.extensions.toolkit_module_finisher as finisher
import web.routes.toolkit_homebrew_routes as routes_module
import utils.toolkit_adaptation_campaign as campaign_sync
import utils.toolkit_adaptation_registry as registry
from utils.toolkit_adaptation_dossier import RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_adaptation_staging import (
    STAGING_STATE_COMPLETED,
    STAGING_STATE_RESERVED,
    AdaptationStagingTargetExistsError,
    create_adaptation_staging_target,
    update_adaptation_staging_target,
)
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
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_both_inputs_transaction"
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
MODULE_NAME = "Sunken_Lighthouse"
JOB_ID = "both-inputs-transaction-job"
TEXT_JOB_ID = "both-inputs-transaction-text-job"
ATTEMPT_NUMBER = 1

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
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-both-inputs-6-2"},
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


def _make_upload_workspace(scratch: Path, source_hash: str) -> Path:
    """Create an approved upload workspace inside the scratch root."""
    workspace = scratch / "workspace"
    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
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
        "assumptions": ["Fixture packet for the task 6.2 transaction tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }
    persist_normalized_packet_artifact(workspace, packet)
    snapshot = build_review_snapshot(
        job_id=JOB_ID,
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    persist_review_snapshot_artifact(workspace, snapshot)
    files["source_original"].write_text(FIXTURE_TEXT, encoding="utf-8")
    files["builder_narrative"].write_text(
        "Build a lighthouse-centered adaptation.", encoding="utf-8"
    )
    return workspace


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


class _TransactionScratchMixin:
    """Provide a unique project-local scratch root removed after each test."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.staging_root = (
            "tmp/toolkit_adaptation_both_inputs_transaction"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.workspaces_root = (
            "tmp/toolkit_adaptation_both_inputs_transaction"
            + "/"
            + self.scratch.name
            + "/workspaces"
        )
        self.registry_path = self.scratch / "modules" / "world_registry.json"
        self.campaign_path = self.scratch / "modules" / "campaign.json"
        self.original_registry: Dict[str, Any] = {
            "worldName": "Both Inputs Fixture World",
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
            "campaignName": "Both Inputs Fixture Campaign",
            "availableModules": ["Sentinel_Module"],
            "active": True,
            "currentModule": "Sentinel_Module",
        }
        _write_json(self.campaign_path, self.original_campaign)

    def _reserve_staging(
        self,
        source_hash: str,
        *,
        attempt_id: str,
        revision_number: int,
        module_slug: str = MODULE_NAME,
        job_id: str = JOB_ID,
        source_path: str = "",
    ) -> Dict[str, Any]:
        return create_adaptation_staging_target(
            source_hash,
            attempt_id=attempt_id,
            attempt_number=ATTEMPT_NUMBER,
            revision_number=revision_number,
            job_id=job_id,
            source_path=source_path,
            module_slug=module_slug,
            staging_root=self.staging_root,
        )

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
            sorted(str(p.relative_to(REPO_ROOT)) for p in modules_dir.rglob("*") if p.is_file())
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

    def _upload_context(self) -> Dict[str, Any]:
        """Assemble the REAL upload envelope with a reserved staging target
        and deterministic staged module output."""
        workspace = _make_upload_workspace(self.scratch, FIXTURE_HASH)
        runtime = __import__(
            "web.extensions.toolkit_adaptation_runtime",
            fromlist=[
                "build_upload_adaptation_handoff",
                "run_upload_adaptation_authoring",
            ],
        )
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="approved_for_build",
            job_id=JOB_ID,
            attempt_number=ATTEMPT_NUMBER,
        )
        self.assertEqual(handoff.get("status"), "ready", handoff.get("diagnostics"))
        authoring = runtime.run_upload_adaptation_authoring(
            handoff,
            workspace=workspace,
            author_runner=FakeAuthorRunner(dossier_builder=_dossier_for_attempt),
            model="mock-adaptation-model",
        )
        self.assertTrue(authoring.get("ok"), authoring.get("diagnostics"))
        provenance = routes_module._build_adaptation_route_provenance(authoring)
        attempt_id = str(authoring["attempt"]["attempt_id"])
        dossier_artifact_path = str(
            authoring.get("authoring", {}).get("dossier_artifact_path") or ""
        )
        source_path = str(authoring.get("source_identity", {}).get("source_path") or "")
        target = self._reserve_staging(
            FIXTURE_HASH,
            attempt_id=attempt_id,
            revision_number=0,
            source_path=source_path,
        )
        module_dir = REPO_ROOT / target["path"]
        _write_staged_module(module_dir, MODULE_NAME)
        return {
            "input_kind": "upload",
            "workspace": workspace,
            "artifact_workspace": str(workspace),
            "dossier": authoring["dossier"],
            "provenance": provenance,
            "attempt_id": attempt_id,
            "dossier_artifact_path": dossier_artifact_path,
            "staging_target": target,
            "module_dir": module_dir,
        }

    def _text_context(self) -> Dict[str, Any]:
        """Run the REAL task 5.1 seam with scratch-redirected workspace and
        staging builders plus an injected author runner."""
        real_workspace_builder = text_worker.build_text_description_attempt_workspace
        real_staging_creator = text_worker.create_adaptation_staging_target

        def _build_ws_into_scratch(module_name, concept, **kw):
            return real_workspace_builder(
                module_name,
                concept,
                workspace_root=self.workspaces_root,
                staging_root=self.staging_root,
                **kw,
            )

        def _create_staging_into_scratch(source_hash, **kw):
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
        handoff = seam_result["adaptation_handoff"]
        target = handoff["staging_target"]
        module_dir = REPO_ROOT / target["path"]
        _write_staged_module(module_dir, MODULE_NAME)
        return {
            "input_kind": "text",
            "seam_result": seam_result,
            "handoff": handoff,
            "artifact_workspace": str(handoff.get("workspace_path") or ""),
            "dossier": handoff["dossier"],
            "provenance": handoff["provenance"],
            "attempt_id": str(handoff["provenance"]["attempt_metadata"]["attempt_id"]),
            "dossier_artifact_path": str(handoff.get("dossier_artifact_path") or ""),
            "staging_target": target,
            "module_dir": module_dir,
        }

    def _persist_attempt_report(self, context: Dict[str, Any]) -> None:
        """Persist the current build artifact required by the finisher."""
        build_result: Dict[str, Any] = {
            "status": "success",
            "stage": "build",
            "module_name": MODULE_NAME,
            "adaptation_gates": _passing_gates(),
        }
        packet_builder._persist_adaptation_attempt_report(
            workspace=Path(context["artifact_workspace"]),
            job_id=context.get("job_id") or TEXT_JOB_ID,
            build_result=build_result,
            adaptation_handoff={
                "provenance": context["provenance"],
                "dossier": context["dossier"],
            },
            staging_target=context["staging_target"],
            build_started_at=None,
            overwrite=True,
        )
        self.assertEqual(
            build_result.get("adaptation_attempt_report", {}).get("status"),
            "persisted",
        )

    def _both_contexts(self) -> List[Dict[str, Any]]:
        return [self._upload_context(), self._text_context()]

    def _run_finisher(
        self,
        context: Dict[str, Any],
        *,
        gates: Optional[Dict[str, Any]] = None,
        summary: Optional[Dict[str, Any]] = None,
        verify_seam: Optional[Dict[str, Any]] = None,
        campaign_seam: Optional[Callable[..., Dict[str, Any]]] = None,
    ) -> Any:
        """Run the REAL adaptation finisher with deterministic injected seams.

        The summary stage is captured (the real one calls the LLM). The real
        registry stage runs under a scratch-scoped chdir so its derived
        ``modules/world_registry.json`` path resolves inside the per-test
        scratch mirror and never touches the real runtime registry. The
        campaign seam records and delegates to the real synchronizer.
        """
        events: List[str] = []
        self._persist_attempt_report(context)
        real_registry_stage = finisher._run_registry_stage
        real_campaign_sync = campaign_sync.synchronize_adaptation_campaign_module

        def _summary(module_slug, module_dir, **kwargs):
            events.append("markdown")
            if summary is not None:
                return summary
            return {
                "status": "success",
                "path": str(Path(module_dir) / "MODULE_SUMMARY.md"),
                "bytes": 256,
                "quality": {"valid": True, "reason": "readable_markdown"},
            }

        def _registry(module_slug, *, module_dir=None, adaptation=False):
            events.append("registry")
            with _chdir(self.scratch):
                return real_registry_stage(
                    module_slug, module_dir=module_dir, adaptation=adaptation
                )

        def _campaign(slug, **kwargs):
            events.append("campaign")
            if campaign_seam is not None:
                return campaign_seam(slug, **kwargs)
            return real_campaign_sync(slug, **kwargs)

        patchers = [
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
        ]
        if verify_seam is not None:
            patchers.append(
                patch.object(
                    registry,
                    "verify_adaptation_registry_entries",
                    return_value=verify_seam,
                )
            )
        for patcher in patchers:
            patcher.start()
        try:
            result = finisher.run_toolkit_module_postbuild_finishing(
                MODULE_NAME,
                adaptation_mode="llm_adaptation",
                adaptation_gates=gates if gates is not None else _passing_gates(),
                adaptation_staging_target=context["staging_target"],
                adaptation_module_dir=context["staging_target"]["path"],
                adaptation_provenance=context["provenance"],
                adaptation_artifact_workspace=context["artifact_workspace"],
            )
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
        return result, events

    def _reset_publication_state(self) -> None:
        """Restore the scratch registry/campaign mirror to the original
        pre-attempt state between sequential both-input subtests."""
        _write_json(self.registry_path, deepcopy(self.original_registry))
        _write_json(self.campaign_path, deepcopy(self.original_campaign))

    def _assert_initial_target_isolated(self, target: Dict[str, Any]) -> None:
        path = str(target["path"])
        self.assertTrue(path.startswith(self.staging_root + "/"))
        self.assertNotIn("modules/", path)
        self.assertFalse(Path(path).is_absolute())
        self.assertEqual(target["revision_number"], 0)
        target_dir = REPO_ROOT / path
        self.assertTrue(target_dir.is_dir())
        marker = json.loads(
            (target_dir / "staging_metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(marker["completion_state"], STAGING_STATE_RESERVED)
        self.assertEqual(marker["stage_id"], target["stage_id"])

    def _assert_dossier_artifact_retained(self, context: Dict[str, Any]) -> None:
        artifact_path = context["dossier_artifact_path"]
        if not artifact_path:
            return
        self.assertTrue(
            (REPO_ROOT / artifact_path).is_file(),
            "prior attempt dossier artifact must be retained",
        )


class TestBothInputsInitialStagingIsolation(
    _TransactionScratchMixin, unittest.TestCase
):
    """Initial adaptation staging is isolated, project-relative, and exclusive
    for BOTH input paths."""

    def test_upload_initial_staging_isolated_and_never_reused(self) -> None:
        sentinels = self._real_module_sentinels()
        context = self._upload_context()
        self._assert_initial_target_isolated(context["staging_target"])
        self._assert_dossier_artifact_retained(context)
        # The same attempt+revision can never be reserved a second time.
        with self.assertRaises(AdaptationStagingTargetExistsError):
            self._reserve_staging(
                FIXTURE_HASH,
                attempt_id=context["attempt_id"],
                revision_number=0,
            )
        # No real module directory was created or overwritten.
        self._assert_real_sentinels_unchanged(sentinels)

    def test_text_initial_staging_isolated_and_repeat_attempt_fails_closed(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        context = self._text_context()
        self._assert_initial_target_isolated(context["staging_target"])
        self._assert_dossier_artifact_retained(context)
        target_dir = REPO_ROOT / context["staging_target"]["path"]
        marker_before = (target_dir / "staging_metadata.json").read_bytes()

        # A repeated initial attempt for the same job fails closed at the
        # staging reservation boundary and never overwrites revision_000.
        real_workspace_builder = text_worker.build_text_description_attempt_workspace
        real_staging_creator = text_worker.create_adaptation_staging_target

        def _build_ws_into_scratch(module_name, concept, **kw):
            return real_workspace_builder(
                module_name,
                concept,
                workspace_root=self.workspaces_root,
                staging_root=self.staging_root,
                **kw,
            )

        def _create_staging_into_scratch(source_hash, **kw):
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
            repeat = text_worker.run_text_description_adaptation_seam(
                MODULE_NAME,
                FIXTURE_TEXT,
                {"job_id": TEXT_JOB_ID},
                author_runner=FakeAuthorRunner(dossier_builder=_dossier_for_attempt),
                model="mock-adaptation-model",
            )
        self.assertIsNotNone(repeat)
        self.assertEqual(repeat["outcome"], "blocked")
        reason = str(repeat.get("reason_code") or "")
        # The repeated initial attempt fails closed at the first exclusive
        # boundary (attempt workspace or staging reservation); either way the
        # prior attempt is never overwritten.
        self.assertTrue(
            "staging_reservation_failed" in reason
            or "workspace_failed" in reason
            or "workspace_exists" in reason,
            reason,
        )
        self.assertEqual(
            (target_dir / "staging_metadata.json").read_bytes(), marker_before
        )
        self._assert_real_sentinels_unchanged(sentinels)

    def test_initial_staging_never_overwrites_an_existing_registered_module(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        # Pre-register the module in the scratch registry mirror and place a
        # sentinel live module directory next to it.
        pre_registered = deepcopy(self.original_registry)
        pre_registered["modules"][MODULE_NAME] = {
            "moduleName": MODULE_NAME,
            "areaCount": 99,
            "legacy": "preserve",
        }
        _write_json(self.registry_path, pre_registered)
        live_module_dir = self.scratch / "modules" / MODULE_NAME
        live_module_dir.mkdir(parents=True, exist_ok=True)
        live_sentinel = live_module_dir / "module_context.json"
        live_sentinel.write_text('{"legacy": "preserve-me"}', encoding="utf-8")

        for context in self._both_contexts():
            with self.subTest(input_kind=context["input_kind"]):
                result, events = self._run_finisher(context)
                # A registered module conflict is a fail-closed publication
                # outcome, never success.
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(
                    result["stages"]["registry"]["reason"],
                    "registry_module_conflict",
                )
                self.assertEqual(result["stages"]["registry"]["integration_attempted"], False)
                self.assertNotIn("campaign", events)
                # The pre-existing registry entry is preserved (JSON value
                # equality; the transaction re-serializes on restore).
                self.assertEqual(
                    json.loads(self.registry_path.read_text(encoding="utf-8")),
                    pre_registered,
                )
                # The live module directory is untouched by the staged attempt.
                self.assertEqual(
                    live_sentinel.read_bytes(), b'{"legacy": "preserve-me"}'
                )
                # The staged output stays in the isolated staging target.
                self.assertTrue(
                    (context["module_dir"] / "module_context.json").is_file()
                )
        self._assert_real_sentinels_unchanged(sentinels)


class TestBothInputsRevisionStagingIsolation(
    _TransactionScratchMixin, unittest.TestCase
):
    """Semantic/revision rebuilds receive a distinct fresh staging target and
    preserve the prior attempt/staging metadata for BOTH input paths."""

    def test_upload_revision_fresh_target_preserves_prior_metadata(self) -> None:
        sentinels = self._real_module_sentinels()
        context = self._upload_context()
        target_zero = context["staging_target"]
        path_zero = str(target_zero["path"])
        update_adaptation_staging_target(target_zero, STAGING_STATE_COMPLETED)

        target_one = self._reserve_staging(
            FIXTURE_HASH,
            attempt_id=context["attempt_id"],
            revision_number=1,
            source_path=str(target_zero.get("source_path") or ""),
        )
        path_one = str(target_one["path"])

        self.assertNotEqual(path_zero, path_one)
        self.assertIn("revision_000", path_zero)
        self.assertIn("revision_001", path_one)
        for path in (path_zero, path_one):
            self.assertTrue(path.startswith(self.staging_root + "/"))
            self.assertNotIn("modules/", path)

        attempt_dir = REPO_ROOT / path_zero
        attempt_dir = attempt_dir.parent
        self.assertTrue((attempt_dir / "revision_000").is_dir())
        self.assertTrue((attempt_dir / "revision_001").is_dir())
        prior_state = json.loads(
            (attempt_dir / "revision_000" / "staging_metadata.json").read_text(
                encoding="utf-8"
            )
        )["completion_state"]
        fresh_state = json.loads(
            (attempt_dir / "revision_001" / "staging_metadata.json").read_text(
                encoding="utf-8"
            )
        )["completion_state"]
        self.assertEqual(prior_state, STAGING_STATE_COMPLETED)
        self.assertEqual(fresh_state, STAGING_STATE_RESERVED)
        # Revision 0 can never be re-reserved.
        with self.assertRaises(AdaptationStagingTargetExistsError):
            self._reserve_staging(
                FIXTURE_HASH,
                attempt_id=context["attempt_id"],
                revision_number=0,
            )
        self._assert_dossier_artifact_retained(context)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_text_revision_fresh_target_preserves_prior_metadata(self) -> None:
        sentinels = self._real_module_sentinels()
        context = self._text_context()
        target_zero = context["staging_target"]
        path_zero = str(target_zero["path"])
        update_adaptation_staging_target(target_zero, STAGING_STATE_COMPLETED)

        # The semantic-revision rebuild reuses the same attempt identity and
        # reserves a DISTINCT fresh revision target through the shared helper
        # (exactly the call the seam makes with revision_number from the
        # attempt metadata).
        target_one = create_adaptation_staging_target(
            FIXTURE_HASH,
            attempt_id=context["attempt_id"],
            attempt_number=ATTEMPT_NUMBER,
            revision_number=1,
            job_id=TEXT_JOB_ID,
            module_slug=MODULE_NAME,
            staging_root=self.staging_root,
        )
        path_one = str(target_one["path"])

        self.assertNotEqual(path_zero, path_one)
        self.assertIn("revision_000", path_zero)
        self.assertIn("revision_001", path_one)
        for path in (path_zero, path_one):
            self.assertTrue(path.startswith(self.staging_root + "/"))
            self.assertNotIn("modules/", path)

        attempt_dir = (REPO_ROOT / path_zero).parent
        self.assertTrue((attempt_dir / "revision_000").is_dir())
        self.assertTrue((attempt_dir / "revision_001").is_dir())
        prior_state = json.loads(
            (attempt_dir / "revision_000" / "staging_metadata.json").read_text(
                encoding="utf-8"
            )
        )["completion_state"]
        self.assertEqual(prior_state, STAGING_STATE_COMPLETED)
        self.assertEqual(
            json.loads(
                (attempt_dir / "revision_001" / "staging_metadata.json").read_text(
                    encoding="utf-8"
                )
            )["completion_state"],
            STAGING_STATE_RESERVED,
        )
        with self.assertRaises(AdaptationStagingTargetExistsError):
            create_adaptation_staging_target(
                FIXTURE_HASH,
                attempt_id=context["attempt_id"],
                attempt_number=ATTEMPT_NUMBER,
                revision_number=0,
                job_id=TEXT_JOB_ID,
                module_slug=MODULE_NAME,
                staging_root=self.staging_root,
            )
        self._assert_dossier_artifact_retained(context)
        self._assert_real_sentinels_unchanged(sentinels)


class TestBothInputsSharedPublicationTransaction(
    _TransactionScratchMixin, unittest.TestCase
):
    """The completed registry-last publication transaction is explicit and
    identical for BOTH input paths, with post-write verification and campaign
    synchronization before completion."""

    def test_shared_gate_order_identical_registry_last_for_both_inputs(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        for context in self._both_contexts():
            with self.subTest(input_kind=context["input_kind"]):
                self._reset_publication_state()
                result, events = self._run_finisher(context)
                self.assertEqual(result["status"], "success", result.get("reason"))
                self.assertEqual(
                    events, ["markdown", "registry", "campaign"], "shared stage order"
                )
                self.assertEqual(
                    result["publication_order"], EXPECTED_PUBLICATION_ORDER
                )
                self.assertTrue(result["registry_is_final_stateful_publication"])
                registry_stage = result["stages"]["registry"]
                self.assertEqual(registry_stage["status"], "success")
                self.assertIs(registry_stage["verified"], True)
                self.assertIs(registry_stage["integration_attempted"], True)
                self.assertEqual(
                    registry_stage["reason"],
                    "adaptation_registry_integrated_and_verified",
                )
                campaign_stage = result["stages"]["campaign_sync"]
                self.assertEqual(campaign_stage["status"], "success")
                self.assertIs(campaign_stage["campaign_visibility_verified"], True)
                self.assertEqual(
                    result["stages"]["registry"]["rollback"]["status"],
                    "not_needed",
                )

                # Registry integration happened inside the scratch mirror with
                # post-write verification of module and area entries.
                persisted = json.loads(
                    self.registry_path.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    persisted["modules"]["Sentinel_Module"],
                    self.original_registry["modules"]["Sentinel_Module"],
                )
                self.assertEqual(
                    persisted["areas"]["SNT001"],
                    self.original_registry["areas"]["SNT001"],
                )
                module_entry = persisted["modules"][MODULE_NAME]
                self.assertEqual(module_entry["moduleName"], MODULE_NAME)
                self.assertEqual(module_entry["areaCount"], 1)
                self.assertEqual(
                    persisted["areas"]["ADP001"]["module"], MODULE_NAME
                )
                # Campaign synchronization appended only this module and kept
                # the unrelated sentinel module.
                campaign = json.loads(
                    self.campaign_path.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    campaign["availableModules"],
                    ["Sentinel_Module", MODULE_NAME],
                )
                self.assertEqual(campaign["currentModule"], "Sentinel_Module")
        self._assert_real_sentinels_unchanged(sentinels)

    def test_no_registry_or_campaign_mutation_before_pre_registration_gates(
        self,
    ) -> None:
        sentinels = self._real_module_sentinels()
        registry_before = self.registry_path.read_bytes()
        campaign_before = self.campaign_path.read_bytes()

        blocked_gates = _passing_gates()
        blocked_gates["gates"]["semantic_authority"] = {
            "status": "blocked",
            "effective_status": "blocked",
            "blockers": ["ambiguous destination"],
        }
        failed_summary = {
            "status": "failed",
            "reason": "summary_missing_markdown_heading",
            "quality": {"valid": False},
        }
        failures = [
            ("semantic_gate", {"gates": blocked_gates}, []),
            ("markdown_quality", {"summary": failed_summary}, ["markdown"]),
        ]
        for context in self._both_contexts():
            for label, kwargs, expected_events in failures:
                with self.subTest(
                    input_kind=context["input_kind"], failure=label
                ):
                    result, events = self._run_finisher(context, **kwargs)
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(events, expected_events)
                    self.assertEqual(
                        result["stages"]["registry"]["status"], "not_attempted"
                    )
                    self.assertEqual(
                        result["stages"].get("campaign_sync", {}).get("status"),
                        None,
                    )
                    # No registry or campaign mutation occurred before the
                    # gates passed.
                    self.assertEqual(self.registry_path.read_bytes(), registry_before)
                    self.assertEqual(self.campaign_path.read_bytes(), campaign_before)
        self._assert_real_sentinels_unchanged(sentinels)


class TestBothInputsPostRegistrationTargetedRollback(
    _TransactionScratchMixin, unittest.TestCase
):
    """Post-registration verification/campaign failures roll back ONLY the
    failed attempt's entries, preserve unrelated sentinels, record rollback
    diagnostics, and never report success -- for BOTH input paths."""

    _BLOCKED_VERIFICATION: Dict[str, Any] = {
        "status": "blocked",
        "verified": False,
        "module_verified": False,
        "areas_verified": False,
        "module_slug": MODULE_NAME,
        "verified_area_ids": [],
        "mismatches": [{"field": "module", "reason": "missing"}],
    }

    def test_post_write_verification_failure_targeted_rollback(self) -> None:
        sentinels = self._real_module_sentinels()
        for context in self._both_contexts():
            with self.subTest(input_kind=context["input_kind"]):
                result, events = self._run_finisher(
                    context, verify_seam=self._BLOCKED_VERIFICATION
                )
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["publication_status"], "blocked")
                self.assertNotIn("campaign", events)
                registry_stage = result["stages"]["registry"]
                self.assertEqual(
                    registry_stage["reason"],
                    "registry_post_write_verification_failed",
                )
                self.assertIs(registry_stage["integration_attempted"], True)
                rollback = registry_stage["rollback"]
                self.assertEqual(rollback["status"], "success")
                self.assertIs(rollback["attempted"], True)
                self.assertIs(rollback["verified"], True)
                # Only the failed attempt's entries were removed; the
                # unrelated sentinel entries are preserved (JSON value
                # equality; the transaction re-serializes on restore).
                self.assertEqual(
                    json.loads(self.registry_path.read_text(encoding="utf-8")),
                    self.original_registry,
                )
                self.assertEqual(
                    json.loads(self.campaign_path.read_text(encoding="utf-8")),
                    self.original_campaign,
                )
        self._assert_real_sentinels_unchanged(sentinels)

    def test_campaign_sync_failure_targeted_rollback(self) -> None:
        sentinels = self._real_module_sentinels()

        def _fail_campaign_after_write(slug, **kwargs):
            # Simulate a campaign write that then fails post-write
            # verification: the module was appended, then the failure fires.
            payload = json.loads(self.campaign_path.read_text(encoding="utf-8"))
            if slug not in payload["availableModules"]:
                payload["availableModules"] = list(payload["availableModules"]) + [slug]
            _write_json(self.campaign_path, payload)
            return {
                "status": "blocked",
                "reason": "campaign_post_write_verification_failed",
                "campaign_visibility_verified": False,
            }

        for context in self._both_contexts():
            with self.subTest(input_kind=context["input_kind"]):
                result, events = self._run_finisher(
                    context, campaign_seam=_fail_campaign_after_write
                )
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["publication_status"], "blocked")
                self.assertEqual(
                    result["reason"], "adaptation_campaign_sync_failed"
                )
                self.assertEqual(
                    events, ["markdown", "registry", "campaign"]
                )
                registry_stage = result["stages"]["registry"]
                self.assertEqual(
                    registry_stage["reason"], "adaptation_campaign_sync_failed"
                )
                rollback = registry_stage["rollback"]
                self.assertEqual(rollback["status"], "success")
                self.assertIs(rollback["verified"], True)
                # Registry AND campaign were restored to the pre-attempt
                # state; the sentinel campaign module is preserved and the
                # failed attempt's availability entry was removed.
                self.assertEqual(
                    json.loads(self.registry_path.read_text(encoding="utf-8")),
                    self.original_registry,
                )
                self.assertEqual(
                    json.loads(self.campaign_path.read_text(encoding="utf-8")),
                    self.original_campaign,
                )
        self._assert_real_sentinels_unchanged(sentinels)


class TestBothInputsTransactionHygiene(unittest.TestCase):
    """Changed files follow SPDX/ASCII rules, stay OS-temp free, and keep
    legacy/default payload behavior isolated."""

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
        self.assertIn("toolkit_adaptation_both_inputs_transaction", own_source)

    def test_legacy_finisher_payload_stays_adaptation_free(self) -> None:
        # A legacy (non-adaptation) invocation never enters the adaptation
        # transaction and never gains adaptation-only staging/report fields.
        result = finisher.run_toolkit_module_postbuild_finishing(
            "No_Such_Legacy_Module", strict=False
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["module_slug"], "No_Such_Legacy_Module")
        self.assertIn("Module directory not found", result["reason"])
        for legacy_key in ("module_dir", "stages"):
            self.assertIn(legacy_key, result)
        for adaptation_key in (
            "adaptation_mode",
            "publication_order",
            "registry_is_final_stateful_publication",
            "adaptation_provenance",
            "adaptation_gates",
            "staging_target",
            "rollback",
        ):
            self.assertNotIn(adaptation_key, result)


if __name__ == "__main__":
    unittest.main()
