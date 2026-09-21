# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free both-input persisted artifact and Markdown verification
(task 6.3 of toolkit-llm-adaptation-runtime-unification).

The suite drives the REAL upload boundary (``build_upload_adaptation_handoff``
+ ``run_upload_adaptation_authoring`` + the route provenance builder + a real
reserved staging target, for BOTH markdown and pdf upload source kinds) and
the REAL text-description boundary (the task 5.1 seam with scratch-redirected
workspace/staging builders) through the REAL shared finisher transaction with
the REAL Homebrewery Markdown renderer (only the three writer LLM seams are
patched to return ``None`` so the deterministic fallback renderer runs) and
the REAL attempt-report writer from the packet builder.  After a successful
publication it inspects the ACTUAL PERSISTED artifacts -- not in-memory return
values -- and proves, for BOTH input types:

  * ``MODULE_SUMMARY.md`` is persisted in the staged module directory, is
    valid/readable (the same ``check_adaptation_markdown_quality`` contract
    the finisher enforces), contains the exact ``Adapted for NEQ-TTRPG``
    notice, preserves expected module content (plot, area, location), and
    carries no raw provider output or credential text;
  * the persisted module provenance (``module_context.json``) and
    ``source_fidelity_report.json`` retain the source hash, Python-owned
    rights class/basis/review state, model/provider metadata without
    credentials, attempt/job/revision identity, canonical bounded
    world-context provenance (explicit ``seed_data_unavailable`` fallback
    when unavailable; available seed provenance when a bounded pack is
    supplied), adaptation route/mode, and adaptation notice;
  * the module build report (``toolkit_build_report.json``) and the
    attempt-scoped artifacts (source context, dossier, proposal ledger,
    build result/attempt report, publication report) retain the same identity
    fields with no drop or relabel across the input boundary;
  * upload Markdown, upload PDF, and text-description artifacts use their
    correct source-kind identity (``upload_markdown`` / ``upload_pdf`` /
    ``text_description``) and the same artifact contract;
  * legacy/default artifacts remain free of adaptation-only metadata.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_both_inputs_persisted_artifacts/<uuid>/`` and are
removed via addCleanup.  No OS temp directory, no provider/network calls
(the writer LLM seams and the author runner are injected), no live
model_config dependency (flags patched explicitly), and no real ``modules/``,
registry, campaign, or runtime mutation: the module output and staging targets
stay inside the per-test scratch, the registry and campaign files under the
scratch ``modules/`` mirror are the only runtime files touched, and real
module/registry/campaign sentinels are byte-checked after every full run.
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
import utils.homebrewery_adventure_writer as adventure_writer
import utils.toolkit_adaptation_campaign as campaign_sync
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
import web.extensions.toolkit_module_finisher as finisher
import web.extensions.toolkit_text_adaptation_worker as text_worker
import web.routes.toolkit_homebrew_routes as routes_module
from utils.toolkit_adaptation_dossier import ADAPTATION_NOTICE, RIGHTS_CLASS_USER_AUTHORED
from utils.toolkit_adaptation_markdown_quality import (
    check_adaptation_markdown_quality,
)
from utils.toolkit_adaptation_provenance import (
    load_adaptation_module_provenance,
    validate_adaptation_provenance,
)
from utils.toolkit_adaptation_staging import (
    STAGING_STATE_COMPLETED,
    create_adaptation_staging_target,
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
SCRATCH_ROOT = (
    REPO_ROOT / "tmp" / "toolkit_adaptation_both_inputs_persisted_artifacts"
)
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
MODULE_NAME = "Sunken_Lighthouse"
JOB_ID = "persisted-artifacts-job"
JOB_ID_PDF = "persisted-artifacts-pdf-job"
TEXT_JOB_ID = "persisted-artifacts-text-job"
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

# Credential/raw-provider tokens that must never appear in persisted artifacts
# or in the rendered Markdown.  Quoted-key forms are used so the legitimate
# bounded ``"kind": "raw_source_excerpt"`` reference label inside the source
# context artifact is not mistaken for a raw-source payload field.
_LEAK_TOKENS = (
    '"api_key"',
    '"apikey"',
    "authorization",
    "bearer ",
    '"password"',
    '"secret"',
    '"credential"',
    '"sk-"',
    '"OPENAI_API_KEY"',
    "response_metadata",
    '"raw_source"',
    '"source_content"',
    "provider_response",
)

# Expected rights basis per input boundary (Python-owned defaults).
RIGHTS_BASIS_UPLOAD = "user_authored_uploaded_adventure"
RIGHTS_BASIS_TEXT = "user_submitted_text_description"

# Expected input-kind identity persisted into the build attempt metadata.
SOURCE_FORMAT_UPLOAD_MARKDOWN = "upload_markdown"
SOURCE_FORMAT_UPLOAD_PDF = "upload_pdf"
SOURCE_FORMAT_TEXT = "text_description"

MODEL_NAME = "mock-adaptation-model"


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
    for key in (
        "source_hash",
        "source_title",
        "source_profile",
        "rights_class",
        "rights_basis",
        "rights_review_required",
        "rights_review_status",
    ):
        if key in attempt_metadata:
            dossier[key] = attempt_metadata[key]
    dossier["adaptation_mode"] = "llm_adaptation"
    return dossier


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __call__(
        self,
        source_context: Any,
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": _dossier_for_attempt(dict(attempt_metadata or {})),
            "diagnostics": [],
            "response_metadata": {
                "model": MODEL_NAME,
                "request_id": "req-persisted-artifacts-6-3",
            },
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


def _make_upload_workspace(
    scratch: Path, source_hash: str, workspace_name: str = "workspace"
) -> Path:
    """Create an approved upload workspace inside the scratch root."""
    workspace = scratch / workspace_name
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
        "assumptions": ["Fixture packet for the task 6.3 artifact tests."],
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
    """Write the deterministic staged module output consumed by the finisher
    and the real Homebrewery renderer."""
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


def _available_world_context_pack() -> Dict[str, Any]:
    """Return a bounded available world-context pack (scalar provenance only,
    never raw campaign/registry/seed payload)."""
    return {
        "world_seed_status": "available",
        "world_seed_version": "seed-v1",
        "world_seed_hash": hashlib.sha256(b"seed").hexdigest(),
        "context_status": "available",
        "context_version": "world-context.v1",
        "context_hash": hashlib.sha256(b"context").hexdigest(),
        "selected_module": "Sentinel_Module",
    }


class _ArtifactScratchMixin:
    """Provide a unique project-local scratch root removed after each test."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.staging_root = (
            "tmp/toolkit_adaptation_both_inputs_persisted_artifacts"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.workspaces_root = (
            "tmp/toolkit_adaptation_both_inputs_persisted_artifacts"
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

    # ------------------------------------------------------------------
    # Real input boundaries
    # ------------------------------------------------------------------

    def _upload_context(
        self,
        source_kind: str = "markdown",
        world_context: Any = None,
    ) -> Dict[str, Any]:
        """Assemble the REAL upload envelope with a reserved staging target,
        persisted attempt artifacts, and deterministic staged module output.

        Each source kind uses its own job identity and workspace directory so
        repeated contexts inside one test never collide on the deterministic
        attempt identity or its exclusive artifact paths.
        """
        job_id = JOB_ID if source_kind != "pdf" else JOB_ID_PDF
        workspace_name = f"workspace_{source_kind}"
        workspace = _make_upload_workspace(
            self.scratch, FIXTURE_HASH, workspace_name=workspace_name
        )
        runtime = __import__(
            "web.extensions.toolkit_adaptation_runtime",
            fromlist=[
                "build_upload_adaptation_handoff",
                "run_upload_adaptation_authoring",
            ],
        )
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind=source_kind,
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="approved_for_build",
            job_id=job_id,
            attempt_number=ATTEMPT_NUMBER,
            world_context=world_context,
        )
        self.assertEqual(handoff.get("status"), "ready", handoff.get("diagnostics"))
        authoring = runtime.run_upload_adaptation_authoring(
            handoff,
            workspace=workspace,
            author_runner=FakeAuthorRunner(),
            model=MODEL_NAME,
        )
        self.assertTrue(authoring.get("ok"), authoring.get("diagnostics"))
        provenance = routes_module._build_adaptation_route_provenance(authoring)
        attempt_id = str(authoring["attempt"]["attempt_id"])
        source_path = str(authoring.get("source_identity", {}).get("source_path") or "")
        target = create_adaptation_staging_target(
            FIXTURE_HASH,
            attempt_id=attempt_id,
            attempt_number=ATTEMPT_NUMBER,
            revision_number=0,
            job_id=job_id,
            source_path=source_path,
            module_slug=MODULE_NAME,
            staging_root=self.staging_root,
        )
        module_dir = REPO_ROOT / target["path"]
        _write_staged_module(module_dir, MODULE_NAME)
        context: Dict[str, Any] = {
            "input_kind": "upload",
            "source_kind": source_kind,
            "job_id": job_id,
            "workspace": workspace,
            "artifact_workspace": str(workspace),
            "dossier": authoring["dossier"],
            "provenance": provenance,
            "attempt_id": attempt_id,
            "dossier_artifact_path": str(
                authoring.get("authoring", {}).get("dossier_artifact_path") or ""
            ),
            "staging_target": target,
            "module_dir": module_dir,
        }
        self._persist_attempt_report(context)
        return context

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
                author_runner=FakeAuthorRunner(),
                model=MODEL_NAME,
            )
        self.assertIsNotNone(seam_result)
        self.assertEqual(
            seam_result["outcome"], "authoring_ready_pending_publication"
        )
        handoff = seam_result["adaptation_handoff"]
        target = handoff["staging_target"]
        module_dir = REPO_ROOT / target["path"]
        _write_staged_module(module_dir, MODULE_NAME)
        context: Dict[str, Any] = {
            "input_kind": "text",
            "source_kind": "text_description",
            "seam_result": seam_result,
            "handoff": handoff,
            "artifact_workspace": str(handoff.get("workspace_path") or ""),
            "dossier": handoff["dossier"],
            "provenance": handoff["provenance"],
            "attempt_id": str(
                handoff["provenance"]["attempt_metadata"]["attempt_id"]
            ),
            "dossier_artifact_path": str(handoff.get("dossier_artifact_path") or ""),
            "staging_target": target,
            "module_dir": module_dir,
        }
        self._persist_attempt_report(context)
        return context

    # ------------------------------------------------------------------
    # Real attempt-report persistence (packet-builder helper)
    # ------------------------------------------------------------------

    def _persist_attempt_report(self, context: Dict[str, Any]) -> None:
        """Persist the Python-owned build attempt report via the REAL packet
        builder helper so the finisher's report-agreement branch passes and
        the attempt artifact exists on disk."""
        build_result: Dict[str, Any] = {
            "status": "success",
            "stage": "build",
            "module_name": MODULE_NAME,
            "adaptation_gates": _passing_gates(),
        }
        handoff = {
            "provenance": context["provenance"],
            "dossier": context["dossier"],
        }
        packet_builder._persist_adaptation_attempt_report(
            workspace=Path(context["artifact_workspace"]),
            job_id=(
                TEXT_JOB_ID
                if context["input_kind"] == "text"
                else context["job_id"]
            ),
            build_result=build_result,
            adaptation_handoff=handoff,
            staging_target=context["staging_target"],
            build_started_at=None,
        )
        self.assertEqual(
            build_result.get("adaptation_attempt_report", {}).get("status"),
            "persisted",
        )

    # ------------------------------------------------------------------
    # Real shared finisher transaction
    # ------------------------------------------------------------------

    def _reset_publication_state(self) -> None:
        """Restore the scratch registry/campaign mirror to the original
        pre-attempt state between sequential contexts in one test."""
        _write_json(self.registry_path, deepcopy(self.original_registry))
        _write_json(self.campaign_path, deepcopy(self.original_campaign))

    def _run_finisher(self, context: Dict[str, Any]) -> Any:
        """Run the REAL adaptation finisher with deterministic injected seams.

        The REAL Homebrewery Markdown renderer runs (only its three LLM seams
        return ``None`` so the deterministic fallback output is produced and
        the real quality contract is enforced on the persisted summary).  The
        provenance stage and report persistence are REAL.  The registry stage
        runs under a scratch-scoped chdir so its derived
        ``modules/world_registry.json`` path resolves inside the per-test
        scratch mirror and never touches the real runtime registry; the
        campaign seam records and delegates to the real synchronizer.
        """
        self._reset_publication_state()
        events: List[str] = []
        real_registry_stage = finisher._run_registry_stage
        real_campaign_sync = campaign_sync.synchronize_adaptation_campaign_module

        def _registry(module_slug, *, module_dir=None, adaptation=False):
            events.append("registry")
            with _chdir(self.scratch):
                return real_registry_stage(
                    module_slug, module_dir=module_dir, adaptation=adaptation
                )

        def _campaign(slug, **kwargs):
            events.append("campaign")
            return real_campaign_sync(slug, **kwargs)

        patchers = [
            patch.object(
                adventure_writer, "_llm_intro_narrative", return_value=None
            ),
            patch.object(adventure_writer, "_llm_plot_hook", return_value=None),
            patch.object(adventure_writer, "_llm_area_overview", return_value=None),
            patch.object(
                finisher, "_run_registry_stage", side_effect=_registry
            ),
            patch.object(
                campaign_sync,
                "synchronize_adaptation_campaign_module",
                side_effect=_campaign,
            ),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            result = finisher.run_toolkit_module_postbuild_finishing(
                MODULE_NAME,
                adaptation_mode="llm_adaptation",
                adaptation_gates=_passing_gates(),
                adaptation_staging_target=context["staging_target"],
                adaptation_module_dir=context["staging_target"]["path"],
                adaptation_provenance=context["provenance"],
                adaptation_artifact_workspace=context["artifact_workspace"],
            )
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
        self.assertEqual(result["status"], "success", result.get("reason"))
        self.assertEqual(events, ["registry", "campaign"])
        return result

    # ------------------------------------------------------------------
    # Real-artifact inspection helpers
    # ------------------------------------------------------------------

    def _attempt_artifact_dir(self, context: Dict[str, Any]) -> Path:
        return (
            Path(context["artifact_workspace"])
            / "adaptation_attempts"
            / context["attempt_id"]
        )

    def _load_artifact(self, context: Dict[str, Any], kind: str) -> Dict[str, Any]:
        path = self._attempt_artifact_dir(context) / f"{kind}.json"
        self.assertTrue(path.is_file(), f"missing persisted artifact {kind}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        return payload

    def _persisted_module_provenance(self, context: Dict[str, Any]) -> Dict[str, Any]:
        module_dir = context["module_dir"]
        context_payload = json.loads(
            (module_dir / "module_context.json").read_text(encoding="utf-8")
        )
        provenance = context_payload.get("adaptation_provenance")
        self.assertIsInstance(provenance, dict)
        self.assertEqual(
            provenance.get("adaptation_notice"), ADAPTATION_NOTICE
        )
        # The canonical envelope must survive its own validator and reload.
        validation = validate_adaptation_provenance(provenance)
        self.assertEqual(validation.get("valid"), True, validation.get("diagnostics"))
        reloaded = load_adaptation_module_provenance(module_dir)
        self.assertEqual(reloaded.get("source_hash"), FIXTURE_HASH)
        return provenance

    def _assert_summary_artifact(self, context: Dict[str, Any]) -> Dict[str, Any]:
        module_dir = context["module_dir"]
        summary_path = module_dir / "MODULE_SUMMARY.md"
        self.assertTrue(summary_path.is_file())
        markdown = summary_path.read_text(encoding="utf-8")
        quality = check_adaptation_markdown_quality(
            markdown, module_slug=MODULE_NAME
        )
        self.assertEqual(quality.get("valid"), True, quality.get("failures"))
        # The persisted summary is the verbatim download artifact, so it must
        # carry the exact adaptation notice and preserve module content.
        self.assertIn(ADAPTATION_NOTICE, markdown)
        self.assertIn("Sunken Lighthouse", markdown)
        self.assertIn("Drowned Bell Chamber", markdown)
        self.assertIn("The bell is missing.", markdown)
        self.assertIn("A flooded stone chamber with a broken bell.", markdown)
        for token in _LEAK_TOKENS:
            self.assertNotIn(token, markdown)
        return {"markdown": markdown, "quality": quality}

    def _assert_no_leaks_in_artifacts(self, context: Dict[str, Any]) -> None:
        """Scan every persisted JSON artifact for credential/raw-source text."""
        attempt_dir = self._attempt_artifact_dir(context)
        for path in sorted(attempt_dir.rglob("*.json")):
            text = path.read_text(encoding="utf-8")
            for token in _LEAK_TOKENS:
                self.assertNotIn(
                    token.lower(),
                    text.lower(),
                    f"leak token {token!r} in {path.name}",
                )
        module_dir = context["module_dir"]
        for filename in (
            "module_context.json",
            "module_plot.json",
            "source_fidelity_report.json",
            "toolkit_build_report.json",
        ):
            text = (module_dir / filename).read_text(encoding="utf-8")
            for token in _LEAK_TOKENS:
                self.assertNotIn(token.lower(), text.lower())

    def _assert_attempt_identity_fields(
        self, context: Dict[str, Any], payload: Mapping[str, Any]
    ) -> None:
        """A persisted artifact must retain the shared identity fields."""
        self.assertEqual(payload.get("attempt_id"), context["attempt_id"])
        self.assertEqual(payload.get("attempt_number"), ATTEMPT_NUMBER)
        self.assertEqual(payload.get("revision_number"), 0)
        provenance = payload.get("provenance")
        self.assertIsInstance(provenance, Mapping)
        self.assertEqual(provenance.get("source_hash"), FIXTURE_HASH)
        self.assertEqual(provenance.get("rights_class"), RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(provenance.get("rights_review_required"), False)
        self.assertEqual(provenance.get("rights_review_status"), "not_required")
        self.assertEqual(provenance.get("adaptation_mode"), "llm_adaptation")

    def _assert_world_context_fallback(
        self, context: Dict[str, Any], provenance: Mapping[str, Any]
    ) -> None:
        world = provenance.get("world_context_provenance")
        self.assertIsInstance(world, Mapping)
        self.assertEqual(world.get("world_seed_status"), "unavailable")
        self.assertEqual(world.get("fallback_status"), "seed_data_unavailable")
        self.assertIs(world.get("read_only"), True)
        self.assertEqual(
            provenance.get("world_context_status"), "unavailable"
        )
        self.assertIsNone(provenance.get("world_seed_hash"))

    def _assert_expected_source_kind(self, context: Dict[str, Any]) -> str:
        """Return and verify the persisted input-kind identity for the context."""
        expected = {
            "markdown": SOURCE_FORMAT_UPLOAD_MARKDOWN,
            "pdf": SOURCE_FORMAT_UPLOAD_PDF,
            "text_description": SOURCE_FORMAT_TEXT,
        }[context["source_kind"]]
        build_artifact = self._load_artifact(context, "build_result")
        metadata = build_artifact.get("metadata")
        self.assertIsInstance(metadata, Mapping)
        self.assertEqual(metadata.get("source_format"), expected)
        self.assertEqual(
            build_artifact.get("provenance", {}).get("source_hash"),
            FIXTURE_HASH,
        )
        # Upload sources resolve to the workspace source original; the text
        # description resolves to its bounded concept copy.  Both are
        # project-relative and never the raw provider payload.
        source_path = str(
            build_artifact.get("provenance", {}).get("source_path") or ""
        )
        self.assertTrue(source_path.endswith("source_original.md"))
        self.assertNotIn("modules/", source_path)
        return expected

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


class TestPersistedMarkdownBothInputs(_ArtifactScratchMixin, unittest.TestCase):
    """The persisted MODULE_SUMMARY.md is valid/readable, carries the exact
    adaptation notice, preserves module content, and leaks nothing -- for
    upload Markdown, upload PDF, and text-description inputs."""

    def _run_summary_check(self, context: Dict[str, Any]) -> None:
        sentinels = self._real_module_sentinels()
        result = self._run_finisher(context)
        summary = self._assert_summary_artifact(context)
        self.assertIn("markdown", result["stages"])
        self.assertIs(
            result["stages"]["markdown"]["quality"]["valid"], True
        )
        # The registry/campaign mirrors were updated by the real transaction.
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            registry["modules"][MODULE_NAME]["moduleName"], MODULE_NAME
        )
        campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        self.assertIn(MODULE_NAME, campaign["availableModules"])
        self._assert_no_leaks_in_artifacts(context)
        self._assert_real_sentinels_unchanged(sentinels)
        self.assertEqual(summary["quality"]["reason"], "adaptation_markdown_quality_pass")

    def test_upload_markdown_summary_persisted_readable_with_notice(self) -> None:
        self._run_summary_check(self._upload_context(source_kind="markdown"))

    def test_upload_pdf_summary_persisted_readable_with_notice(self) -> None:
        self._run_summary_check(self._upload_context(source_kind="pdf"))

    def test_text_summary_persisted_readable_with_notice(self) -> None:
        self._run_summary_check(self._text_context())

    def test_legacy_rendered_markdown_has_no_adaptation_notice(self) -> None:
        """Legacy rendering (no adaptation_notice, no provenance) must not
        carry the adaptation notice or provenance metadata."""
        module_dir = REPO_ROOT / self.staging_root
        scratch_module = module_dir / MODULE_NAME
        scratch_module.mkdir(parents=True, exist_ok=True)
        _write_staged_module(scratch_module, MODULE_NAME)
        with patch.object(
            adventure_writer, "_llm_intro_narrative", return_value=None
        ), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(
            adventure_writer, "_llm_area_overview", return_value=None
        ):
            markdown = adventure_writer.generate_homebrewery_adventure(
                MODULE_NAME, module_dir=scratch_module
            )
        self.assertNotIn("Adapted for NEQ-TTRPG", markdown)
        self.assertNotIn("**Model metadata:**", markdown)
        self.assertNotIn("**Adaptation mode:**", markdown)


class TestPersistedProvenanceBothInputs(_ArtifactScratchMixin, unittest.TestCase):
    """Provenance identity is persisted consistently for upload Markdown,
    upload PDF, and text-description inputs."""

    def _run_identity_check(self, context: Dict[str, Any]) -> None:
        sentinels = self._real_module_sentinels()
        result = self._run_finisher(context)

        # --- module provenance (module_context.json) ---------------------
        provenance = self._persisted_module_provenance(context)
        self.assertEqual(provenance.get("contract_version"), "toolkit_adaptation_provenance.v1")
        self.assertEqual(provenance.get("adaptation_mode"), "llm_adaptation")
        self.assertEqual(provenance.get("adaptation_status"), "adapted")
        self.assertEqual(provenance.get("adaptation_notice"), ADAPTATION_NOTICE)
        self.assertEqual(provenance.get("source_hash"), FIXTURE_HASH)
        self.assertEqual(provenance.get("rights_class"), RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(provenance.get("rights_classification"), RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(provenance.get("rights_classification_source"), "supplied")
        self.assertEqual(provenance.get("rights_review_required"), False)
        self.assertEqual(provenance.get("rights_review_status"), "not_required")
        expected_basis = (
            RIGHTS_BASIS_UPLOAD
            if context["input_kind"] == "upload"
            else RIGHTS_BASIS_TEXT
        )
        self.assertEqual(provenance.get("rights_basis"), expected_basis)
        self.assertEqual(provenance.get("attempt_id"), context["attempt_id"])
        self.assertEqual(provenance.get("attempt_number"), ATTEMPT_NUMBER)
        self.assertEqual(provenance.get("revision_number"), 0)
        # Model metadata is present, bounded, and credential-free.
        model_metadata = provenance.get("model_metadata")
        self.assertIsInstance(model_metadata, Mapping)
        self.assertEqual(model_metadata.get("model"), MODEL_NAME)
        for token in _LEAK_TOKENS:
            self.assertNotIn(
                token.lower(),
                json.dumps(model_metadata).lower(),
            )
        self._assert_world_context_fallback(context, provenance)

        # --- source_fidelity_report.json ---------------------------------
        fidelity = json.loads(
            (context["module_dir"] / "source_fidelity_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(fidelity.get("source_hash"), FIXTURE_HASH)
        self.assertEqual(fidelity.get("adaptation_mode"), "llm_adaptation")
        self.assertEqual(fidelity.get("source_fidelity_status"), "not_applicable")
        self.assertEqual(fidelity.get("source_fidelity_mode"), "llm_adaptation")
        freshness = fidelity.get("report_freshness")
        self.assertIsInstance(freshness, Mapping)
        self.assertEqual(freshness.get("attempt_id"), context["attempt_id"])
        self.assertEqual(freshness.get("authoritative"), True)
        self.assertEqual(freshness.get("stage"), "adaptation_provenance")
        self.assertEqual(
            fidelity.get("adaptation_provenance", {}).get("source_hash"),
            FIXTURE_HASH,
        )

        # --- toolkit_build_report.json (module report) -------------------
        report = json.loads(
            (context["module_dir"] / "toolkit_build_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report.get("status"), "success")
        self.assertEqual(report.get("publication_status"), "completed")
        self.assertEqual(report.get("adaptation_mode"), "llm_adaptation")
        self.assertEqual(report.get("python_authoritative"), True)
        self.assertEqual(report.get("llm_publication_override"), False)
        self.assertIs(report.get("registry_is_final_stateful_publication"), True)
        self.assertEqual(report.get("publication_order"), EXPECTED_PUBLICATION_ORDER)
        self.assertEqual(
            report.get("source_reference", {}).get("sha256"), FIXTURE_HASH
        )
        self.assertEqual(report.get("campaign_visibility_verified"), True)
        report_freshness = report.get("report_freshness")
        self.assertEqual(report_freshness.get("attempt_id"), context["attempt_id"])
        self.assertEqual(report_freshness.get("source_hash"), FIXTURE_HASH)
        self.assertEqual(
            (report.get("adaptation_report_agreement") or {}).get("status"),
            "pass",
        )
        self.assertEqual(
            report.get("publication_report", {}).get("status"), "persisted"
        )
        self.assertEqual(
            report.get("attempt_report", {}).get("status"), "referenced"
        )
        self.assertIs(report["stages"]["registry"]["verified"], True)
        self.assertIs(
            report["stages"]["campaign_sync"]["campaign_visibility_verified"],
            True,
        )
        self.assertEqual(
            report["stages"]["markdown"]["quality"]["valid"], True
        )
        # The report is a public surface: no credentials or raw source.
        for token in _LEAK_TOKENS:
            self.assertNotIn(token.lower(), json.dumps(report).lower())

        # --- attempt-scoped artifacts ------------------------------------
        dossier = self._load_artifact(context, "adaptation_dossier")
        dossier_payload = dossier.get("payload")
        self.assertIsInstance(dossier_payload, Mapping)
        self.assertEqual(dossier_payload.get("source_hash"), FIXTURE_HASH)
        self.assertEqual(dossier_payload.get("rights_class"), RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(dossier_payload.get("rights_review_status"), "not_required")
        self.assertEqual(dossier_payload.get("adaptation_mode"), "llm_adaptation")
        self.assertEqual(dossier_payload.get("adaptation_notice"), ADAPTATION_NOTICE)
        self._assert_attempt_identity_fields(context, dossier)

        build_artifact = self._load_artifact(context, "build_result")
        build_payload = build_artifact.get("payload")
        self.assertEqual(
            build_payload.get("source_ref", {}).get("sha256"), FIXTURE_HASH
        )
        self.assertEqual(
            build_payload.get("staging", {}).get("isolated"), True
        )
        self.assertEqual(
            build_artifact.get("metadata", {}).get("job_id"),
            TEXT_JOB_ID if context["input_kind"] == "text" else context["job_id"],
        )
        self._assert_attempt_identity_fields(context, build_artifact)

        publication = self._load_artifact(context, "publication_report")
        self.assertEqual(
            publication.get("payload", {}).get("publication_status"), "published"
        )
        self.assertEqual(
            publication.get("payload", {}).get("registry_evidence", {}).get("verified"),
            True,
        )
        module_refs = publication.get("payload", {}).get("module_artifact_refs")
        self.assertIsInstance(module_refs, list)
        self.assertTrue(
            any(str(ref.get("path", "")).endswith("MODULE_SUMMARY.md") for ref in module_refs),
            "publication artifact must reference the persisted summary",
        )
        self.assertEqual(
            publication.get("payload", {}).get("campaign_evidence", {}).get(
                "campaign_visibility_verified"
            ),
            True,
        )
        self._assert_attempt_identity_fields(context, publication)

        # proposal ledger retained with attempt identity, no credentials
        proposals = self._load_artifact(context, "world_narrative_proposals")
        self.assertEqual(proposals.get("attempt_id"), context["attempt_id"])
        self.assertIn("proposals", proposals)

        # staging metadata retained with source/attempt identity
        staging_metadata = json.loads(
            (
                REPO_ROOT / context["staging_target"]["path"] / "staging_metadata.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(staging_metadata.get("attempt_id"), context["attempt_id"])
        self.assertEqual(staging_metadata.get("revision_number"), 0)

        # --- source-kind identity ----------------------------------------
        self._assert_expected_source_kind(context)

        # --- every persisted artifact passes the leak scan ---------------
        self._assert_no_leaks_in_artifacts(context)
        self._assert_real_sentinels_unchanged(sentinels)
        self.assertEqual(result["stages"]["registry"]["status"], "success")

    def test_upload_markdown_provenance_identity_persisted(self) -> None:
        self._run_identity_check(self._upload_context(source_kind="markdown"))

    def test_upload_pdf_provenance_identity_persisted(self) -> None:
        self._run_identity_check(self._upload_context(source_kind="pdf"))

    def test_text_provenance_identity_persisted(self) -> None:
        self._run_identity_check(self._text_context())

    def test_upload_available_world_context_provenance_persisted(self) -> None:
        """When a bounded world-context pack is supplied, the persisted
        provenance carries the available seed identity -- and only scalar
        provenance, never raw seed/campaign payload."""
        sentinels = self._real_module_sentinels()
        pack = _available_world_context_pack()
        context = self._upload_context(source_kind="markdown", world_context=pack)
        self._run_finisher(context)
        provenance = self._persisted_module_provenance(context)
        world = provenance.get("world_context_provenance")
        self.assertEqual(world.get("world_seed_status"), "available")
        self.assertEqual(world.get("world_seed_hash"), pack["world_seed_hash"])
        # The canonical provenance normalizes the bounded module label; only
        # the scalar label survives, never a raw seed/campaign payload.
        self.assertEqual(
            str(world.get("selected_module")).lower(), "sentinel_module"
        )
        self.assertIs(world.get("read_only"), True)
        self.assertEqual(provenance.get("world_seed_status"), "available")
        self.assertEqual(
            str(provenance.get("world_context_selected_module")).lower(),
            "sentinel_module",
        )
        # Only the bounded pack scalars may reach persisted artifacts; any
        # would-be raw payload is absent by construction.
        self.assertEqual(
            provenance.get("world_context_provenance", {}).get("raw_context_included"),
            False,
        )
        self._assert_no_leaks_in_artifacts(context)
        self._assert_real_sentinels_unchanged(sentinels)

    def test_upload_and_text_unavailable_fallback_persisted(self) -> None:
        """Both input types persist the canonical unavailable world-context
        fallback status (no world-seed grounding is ever claimed)."""
        for context in (
            self._upload_context(source_kind="markdown"),
            self._text_context(),
        ):
            with self.subTest(input_kind=context["input_kind"]):
                self._run_finisher(context)
                provenance = self._persisted_module_provenance(context)
                self._assert_world_context_fallback(context, provenance)
                world = provenance.get("world_context_provenance")
                self.assertIsNone(world.get("selected_module"))
                self.assertIsNone(world.get("world_seed_hash"))


class TestPersistedArtifactContractParity(_ArtifactScratchMixin, unittest.TestCase):
    """Upload Markdown, upload PDF, and text-description artifacts use the
    same artifact contract and retain identical identity fields; legacy
    artifacts stay free of adaptation metadata."""

    def test_artifact_contract_identical_across_inputs(self) -> None:
        upload = self._upload_context(source_kind="markdown")
        text = self._text_context()
        for context in (upload, text):
            with self.subTest(input_kind=context["input_kind"]):
                self._run_finisher(context)
                attempt_dir = self._attempt_artifact_dir(context)
                kinds = sorted(p.name for p in attempt_dir.glob("*.json"))
                self.assertEqual(
                    kinds,
                    [
                        "adaptation_dossier.json",
                        "build_result.json",
                        "publication_report.json",
                        "source_context.json",
                        "world_narrative_proposals.json",
                    ],
                )
                # Module-facing artifact set is identical for both inputs.
                module_dir = context["module_dir"]
                for filename in (
                    "MODULE_SUMMARY.md",
                    "module_context.json",
                    "source_fidelity_report.json",
                    "toolkit_build_report.json",
                ):
                    self.assertTrue(
                        (module_dir / filename).is_file(), filename
                    )

    def test_identity_fields_consistent_across_all_persisted_artifacts(
        self,
    ) -> None:
        """No required identity field is dropped or relabeled between the
        dossier, build result, publication artifact, and module provenance --
        for both input boundaries."""
        for context in (
            self._upload_context(source_kind="markdown"),
            self._upload_context(source_kind="pdf"),
            self._text_context(),
        ):
            with self.subTest(input_kind=context["input_kind"]):
                self._run_finisher(context)
                provenance = self._persisted_module_provenance(context)
                dossier = self._load_artifact(context, "adaptation_dossier")
                build_artifact = self._load_artifact(context, "build_result")
                publication = self._load_artifact(context, "publication_report")

                dossier_prov = dossier.get("provenance")
                build_prov = build_artifact.get("provenance")
                publication_prov = publication.get("provenance")
                module_world = provenance.get("world_context_provenance")

                # Attempt identity lives at the artifact top level (the
                # nested provenance block carries source/rights/world/model
                # identity only).
                for artifact in (dossier, build_artifact, publication):
                    self.assertEqual(
                        artifact.get("attempt_id"), context["attempt_id"]
                    )
                    self.assertEqual(artifact.get("revision_number"), 0)

                for artifact_prov in (
                    dossier_prov,
                    build_prov,
                    publication_prov,
                ):
                    self.assertIsInstance(artifact_prov, Mapping)
                    self.assertEqual(
                        artifact_prov.get("source_hash"), FIXTURE_HASH
                    )
                    self.assertEqual(
                        artifact_prov.get("rights_class"),
                        RIGHTS_CLASS_USER_AUTHORED,
                    )
                    self.assertEqual(
                        artifact_prov.get("rights_review_required"), False
                    )
                    self.assertEqual(
                        artifact_prov.get("rights_review_status"), "not_required"
                    )
                    self.assertEqual(
                        artifact_prov.get("adaptation_mode"), "llm_adaptation"
                    )
                    # World-context provenance must be byte-identical to the
                    # module provenance canonical envelope.
                    self.assertEqual(
                        artifact_prov.get("world_context_provenance"),
                        module_world,
                    )
                    # Model metadata is present without credentials.
                    model = artifact_prov.get("model_metadata")
                    self.assertIsInstance(model, Mapping)
                    self.assertEqual(model.get("model"), MODEL_NAME)
                    for token in _LEAK_TOKENS:
                        self.assertNotIn(
                            token.lower(), json.dumps(model).lower()
                        )

                # The dossier payload itself echoes the Python-owned rights.
                self.assertEqual(
                    dossier.get("payload", {}).get("rights_class"),
                    RIGHTS_CLASS_USER_AUTHORED,
                )

                # Source-kind identity is preserved per input boundary.
                self._assert_expected_source_kind(context)
                self._assert_no_leaks_in_artifacts(context)

    def test_legacy_artifacts_stay_adaptation_free(self) -> None:
        """A legacy (non-adaptation) finisher invocation never gains
        adaptation-only metadata."""
        result = finisher.run_toolkit_module_postbuild_finishing(
            "No_Such_Legacy_Module", strict=False
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["module_slug"], "No_Such_Legacy_Module")
        for adaptation_key in (
            "adaptation_mode",
            "publication_order",
            "registry_is_final_stateful_publication",
            "adaptation_provenance",
            "adaptation_gates",
            "staging_target",
            "rollback",
            "python_authoritative",
        ):
            self.assertNotIn(adaptation_key, result)

        # A legacy staged module_context.json carries no provenance surface.
        module_dir = REPO_ROOT / self.staging_root
        scratch_module = module_dir / "Legacy_Probe"
        scratch_module.mkdir(parents=True, exist_ok=True)
        _write_staged_module(scratch_module, "Legacy_Probe")
        context_payload = json.loads(
            (scratch_module / "module_context.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("adaptation_provenance", context_payload)
        for adaptation_key in (
            "adaptation_mode",
            "adaptation_status",
            "adaptation_notice",
            "source_hash",
            "rights_class",
        ):
            self.assertNotIn(adaptation_key, context_payload)


class TestPersistedArtifactsHygiene(unittest.TestCase):
    """Changed files follow SPDX/ASCII rules, stay OS-temp free, keep scratch
    project-relative, and never touch real module/registry/campaign state."""

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
        self.assertIn("toolkit_adaptation_both_inputs_persisted_artifacts", own_source)

    def test_no_provider_or_network_imports(self) -> None:
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("def test_no_provider_or_network_imports", 1)[0]
        for token in ("import openai", "from openai", "requests.get", "urllib.request",
                      "socketio.Server", "httpx"):
            with self.subTest(token=token):
                self.assertNotIn(token, scan)


if __name__ == "__main__":
    unittest.main()
