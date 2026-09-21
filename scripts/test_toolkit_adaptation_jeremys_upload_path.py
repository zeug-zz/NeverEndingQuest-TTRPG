# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Task 7.1 upload-job-path smoke for Jeremys Magic Shop adaptation.

This suite runs the Jeremys Magic Shop Markdown source through the ACTUAL
Toolkit upload job path (``web/routes/toolkit_homebrew_routes
._run_homebrew_build_job``) with a deterministic injected author provider
and verifies, end to end:

  * catalogue adaptation is accepted through the upload intake/review/build
    path: the real route decision resolution, the real upload handoff
    (``build_upload_adaptation_handoff``), the REAL authoring adapter
    (``run_upload_adaptation_authoring`` with an injected deterministic
    author runner standing in for the live provider), and the REAL packet
    builder (``run_toolkit_homebrew_packet_build`` with an injected
    deterministic module executor) produce a Python-validated build-ready
    dossier and a staged module;
  * the staged build reaches the existing readiness/publication gates: the
    real adaptation gate composer runs inside the packet build (schema,
    readiness, mechanical closure, semantic authority, semantic probes,
    report agreement all ``pass``), the route readiness gate is the required
    pre-finisher gate, and the shared finisher rechecks the gate order before
    Markdown/registry/campaign;
  * a readable persisted ``MODULE_SUMMARY.md`` carries the exact
    ``Adapted for NEQ-TTRPG`` notice plus expected module content, generated
    by the REAL Homebrewery renderer (only the three LLM writer seams are
    pinned to the deterministic fallback) and validated by the REAL
    ``check_adaptation_markdown_quality`` contract;
  * readiness/publication reports and registry module/area entries persist
    with post-write verification, registry-last ordering, and provenance
    (source hash, rights class, model metadata, world-context status);
  * explicit no-active-campaign handling is safe and visible: module and
    registry publication succeeds when no active campaign is configured
    (missing file, and an explicit inactive campaign), while campaign
    synchronization reports ``deferred`` / ``no_active_campaign`` with
    ``campaign_visibility_verified=False`` and never reports false campaign
    success or fails the module publication contract;
  * bounded provenance/source-hash/source-kind/rights/model/world-context
    metadata is preserved and no raw provider response or credential text
    leaks into persisted artifacts.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_jeremys_upload_path/<uuid>/`` and are removed via
addCleanup. The module output and reserved staging targets stay inside the
per-test scratch, the registry/campaign files under the scratch ``modules/``
mirror are the only runtime files touched, and real module/registry/campaign/
source sentinels are byte-checked. No provider/network calls occur: the
author provider and module executor are injected deterministic fakes, the
route readiness gate is a deterministic seam (the real workspace readiness
gate resolves ``modules/<slug>`` from the process cwd and would otherwise
need a live module tree there), the registry stage runs the REAL adaptation
registry transaction inside a scratch-scoped chdir, and network/SDK/socket
tripwires fail loudly if anything attempts a live call. The live operator
``model_config.ENABLE_LLM_ADAPTATION`` value is never relied on; every
behavioral test patches it explicitly.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import shutil
import socket
import sys
import unittest
import urllib.request
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import utils.homebrewery_adventure_writer as adventure_writer
import utils.toolkit_adaptation_auditor as adaptation_auditor
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
import web.extensions.toolkit_module_finisher as finisher
import web.routes.toolkit_homebrew_routes as routes_module
from utils.toolkit_adaptation_config import BUILD_MODE_LLM_ADAPTATION
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


SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_jeremys_upload_path"
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
SOURCE_PATH = (
    REPO_ROOT / "Local_Docs" / "modules" / "hombrew" / "modules"
    / "Jeremys Magic Shop.md"
)
SOURCE_REFERENCE = "Local_Docs/modules/hombrew/modules/Jeremys Magic Shop.md"
# Known gate-passing module used only as a provider-free builder
# materialization fixture. The staged module is renamed and receives
# Jeremy's adaptation provenance before the real adaptation gates run.
BUILDER_FIXTURE = REPO_ROOT / "modules" / "Into_the_Deepvault"
MODULE_SLUG = "Jeremys_Magic_Shop"

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

_CREDENTIAL_TOKENS = (
    "api_key",
    "apikey",
    "x-api-key",
    "authorization",
    "bearer ",
    "openai_api_key",
)
# Real provider-key shapes only: a sk- prefix followed by a key body would be
# a credential; bare "sk-" substrings inside ordinary prose are not.
_CREDENTIAL_KEY_RE = __import__("re").compile(r"sk-[A-Za-z0-9_-]{8,}")


def _write_json(path: Path, payload: object) -> None:
    """Write a scratch fixture JSON file deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _complete_fixture_monster_refs(target: Path) -> None:
    """Make the copied provider-free fixture schema-sufficient for its refs."""
    template = json.loads(
        (target / "monsters" / "forged_sentry.json").read_text(encoding="utf-8")
    )
    refs = {
        "smuggler": "Smuggler",
        "market_lookout": "Market lookout",
        "animated_tools": "animated tools",
        "ashen_wraiths": "ashen wraiths",
        "animated_forge_tools": "animated forge tools",
    }
    for slug, name in refs.items():
        payload = deepcopy(template)
        payload["name"] = name
        _write_json(target / "monsters" / f"{slug}.json", payload)


def _snapshot_tree(path: Path) -> Optional[str]:
    """Return a deterministic digest for a protected file or directory."""
    if not path.exists():
        return None
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or not child.is_file():
            continue
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(child.read_bytes())
    return digest.hexdigest()


@contextlib.contextmanager
def _chdir(path: Path) -> Any:
    """Temporarily change the process working directory."""
    original = Path.cwd()
    import os

    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


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
    """Deterministic injectable author provider (never touches a service).

    Records the bounded source context and attempt metadata it receives so
    the test can prove the catalogue profile, Python-owned rights, and source
    identity reached the provider boundary without raw source leakage.
    """

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.calls: List[Tuple[Any, Optional[Dict[str, Any]], Dict[str, Any]]] = []
        self.dossier_builder = dossier_builder

    def __call__(
        self,
        source_context: Any,
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append(
            (deepcopy(source_context), deepcopy(dict(attempt_metadata or {})), dict(kwargs))
        )
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
                "model": "provider-free-jeremys-author",
                "request_id": "req-jeremys-7-1",
            },
            "params_used": {"reasoning_effort": "medium"},
        }


class _JeremysUploadScratchMixin:
    """Provide a unique project-local scratch root and real sentinels."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.staging_root = (
            "tmp/toolkit_adaptation_jeremys_upload_path"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.registry_path = self.scratch / "modules" / "world_registry.json"
        self.campaign_path = self.scratch / "modules" / "campaign.json"
        self.original_registry: Dict[str, Any] = {
            "worldName": "Jeremys Upload Path Fixture World",
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
        self.workspace = self.scratch / "workspace"
        self.source_hash = hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest()
        self.author_runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        self.readiness_calls: List[Dict[str, Any]] = []
        self.registry_stage_calls: List[Dict[str, Any]] = []
        self.job_ids: List[str] = []
        self.addCleanup(self._clear_jobs)

        self.real_registry = REPO_ROOT / "modules" / "world_registry.json"
        self.real_campaign = REPO_ROOT / "modules" / "campaign.json"
        self.real_module = REPO_ROOT / "modules" / MODULE_SLUG
        self.protected_real_state = {
            path: path.read_bytes()
            for path in (self.real_registry, self.real_campaign, SOURCE_PATH)
            if path.exists()
        }
        self.protected_real_module = _snapshot_tree(self.real_module)

        self.tripwire_patchers = [
            patch.object(
                adaptation_auditor, "create_chat_client", side_effect=self._blocked_provider
            ),
            patch(
                "utils.ai_client_factory.create_chat_client",
                side_effect=self._blocked_provider,
            ),
            patch.object(socket, "socket", side_effect=self._blocked_network),
            patch.object(socket, "create_connection", side_effect=self._blocked_network),
            patch.object(urllib.request, "urlopen", side_effect=self._blocked_network),
            patch.object(http.client.HTTPConnection, "request", side_effect=self._blocked_network),
            patch.object(http.client.HTTPSConnection, "request", side_effect=self._blocked_network),
        ]
        for patcher in self.tripwire_patchers:
            patcher.start()
        self.addCleanup(self._stop_tripwires)

    def _stop_tripwires(self) -> None:
        for patcher in reversed(self.tripwire_patchers):
            patcher.stop()

    @staticmethod
    def _blocked_provider(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live provider client creation is forbidden in task 7.1")

    @staticmethod
    def _blocked_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network access is forbidden in task 7.1")

    def _clear_jobs(self) -> None:
        with routes_module._jobs_lock:
            for job_id in self.job_ids:
                routes_module._jobs.pop(job_id, None)
            routes_module._active_job_id = None

    def _snapshot_job(self, job_id: str) -> Dict[str, Any]:
        with routes_module._jobs_lock:
            job = routes_module._jobs.get(job_id)
            return dict(job) if job is not None else {}

    def _make_workspace(self) -> Path:
        """Create the approved upload workspace from the real Jeremy source."""
        ensure_workspace_placeholders(self.workspace)
        files = get_workspace_files(self.workspace)
        packet: Dict[str, Any] = {
            "packet_version": "v1",
            "normalization_state": "normalized",
            "source_hash": self.source_hash,
            "source_path": SOURCE_REFERENCE,
            "title": "Jeremy's Magic Shop",
            "author": "Jeremy",
            "description": "A magical item catalogue adapted into a playable shop mystery.",
            "adventure_summary": "The shop's black lantern shipment has attracted a dangerous buyer.",
            "module_tone": "playful magical commerce with a thread of mystery",
            "acts": [{"name": "The Missing Lantern"}],
            "locations": ["Jeremy's Shop", "Back Room"],
            "connectivity_hints": [],
            "encounter_seeds": ["A hidden buyer tries to remove the black lantern."],
            "npc_seeds": ["Jeremy, an eccentric magic shopkeeper"],
            "monster_refs": [],
            "plot_progression": ["Inspect the catalogue and trace the missing lantern."],
            "continuity_hints": [],
            "media_hints": [],
            "assumptions": ["The catalogue is suitable for a generic-fantasy shop adaptation."],
            "warnings": ["This is a non-literal adaptation, not a source-fidelity import."],
            "source_profile": "catalogue",
            "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
        }
        persist_normalized_packet_artifact(self.workspace, packet)
        snapshot = build_review_snapshot(
            job_id="jeremys-magic-shop-upload-7-1",
            decision=REVIEW_DECISION_APPROVE,
            packet=packet,
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
        )
        persist_review_snapshot_artifact(self.workspace, snapshot)
        files["source_original"].write_bytes(SOURCE_PATH.read_bytes())
        # Placeholder reports required by the real finisher-entry validator.
        for name in ("build_result", "readiness_validation_report", "readiness_audit_report"):
            files[name].write_text("{}", encoding="utf-8")
        return self.workspace

    def _register_job(self, job_id: str) -> None:
        with routes_module._jobs_lock:
            routes_module._jobs[job_id] = {
                "job_id": job_id,
                "job_type": "toolkit_homebrew_md_ingest",
                "status": "approved_for_build",
                "stage": "build",
                "pipeline_status": "building",
                "artifact_workspace": str(self.workspace),
                "source_kind": "markdown",
                "source_filename": "Jeremys Magic Shop.md",
                "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
                "review_decision": REVIEW_DECISION_APPROVE,
                "expected_module_name": MODULE_SLUG,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }

    def _staging_into_scratch(self, source_hash: str, **kwargs: Any) -> Dict[str, Any]:
        kwargs.pop("staging_root", None)
        from utils.toolkit_adaptation_staging import create_adaptation_staging_target

        return create_adaptation_staging_target(
            source_hash,
            staging_root=self.staging_root,
            **kwargs,
        )

    def _builder_executor(
        self, builder_input: Dict[str, Any], progress_callback: Optional[Any] = None
    ) -> None:
        """Materialize a known gate-passing module without a provider."""
        self.assertEqual(builder_input["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        handoff = builder_input["llm_adaptation"]
        self.assertEqual(handoff["dossier"]["source_profile"], "catalogue")
        self.assertEqual(handoff["dossier"]["source_hash"], self.source_hash)
        target = (
            REPO_ROOT / builder_input["derived_builder_parameters"]["output_directory"]
        ).resolve()
        target.relative_to((REPO_ROOT / "tmp").resolve())
        shutil.copytree(BUILDER_FIXTURE, target, dirs_exist_ok=True)
        _complete_fixture_monster_refs(target)
        # Do not carry the fixture module's stale publication report into the
        # fresh adaptation candidate; the adaptation finisher owns a new one.
        (target / "toolkit_build_report.json").unlink(missing_ok=True)
        context_path = target / "module_context.json"
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["module_id"] = MODULE_SLUG
        context["module_name"] = "Jeremy's Magic Shop"
        context_areas = context.setdefault("areas", {})
        for area_path in sorted((target / "areas").glob("*.json")):
            if area_path.name.endswith("_BU.json"):
                continue
            context_areas.setdefault(area_path.stem, {})
        _write_json(context_path, context)
        if progress_callback:
            progress_callback("build", "Provider-free Jeremy catalogue adaptation materialized")

    def _readiness_fake(
        self, artifact_workspace: Any, job_id: str, state_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Deterministic route readiness gate seam (pre-finisher gate)."""
        self.readiness_calls.append({"workspace": str(artifact_workspace), "job_id": job_id})
        if state_callback:
            state_callback(
                "ready_for_finishing",
                {"status": "ready_for_finishing", "module_name": MODULE_SLUG},
            )
        return {"status": "ready_for_finishing", "module_name": MODULE_SLUG}

    def _registry_stage_into_scratch(
        self,
        module_slug: str,
        *,
        module_dir: Any = None,
        adaptation: bool = False,
        real_registry_stage: Callable[..., Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Run the REAL registry transaction inside the scratch modules mirror."""
        self.registry_stage_calls.append(
            {
                "module_slug": module_slug,
                "module_dir": str(module_dir),
                "adaptation": adaptation,
            }
        )
        if real_registry_stage is None:
            raise AssertionError("real registry stage was not captured before patching")
        with _chdir(self.scratch):
            return real_registry_stage(
                module_slug, module_dir=module_dir, adaptation=adaptation
            )

    def _run_upload_job(self, job_id: str) -> Dict[str, Any]:
        """Run the REAL upload route ``_run_homebrew_build_job`` end to end."""
        workspace = self._make_workspace()
        self._register_job(job_id)
        self.job_ids.append(job_id)
        real_authoring = routes_module.run_upload_adaptation_authoring
        # Capture the real registry stage BEFORE patching so the scratch
        # wrapper can delegate to it without recursion.
        real_registry_stage = finisher._run_registry_stage

        def _authoring_with_runner(handoff: Any, **kwargs: Any) -> Dict[str, Any]:
            return real_authoring(
                handoff,
                workspace=kwargs.get("workspace"),
                author_runner=self.author_runner,
            )

        def _registry_into_scratch(
            module_slug: str, *, module_dir: Any = None, adaptation: bool = False
        ) -> Dict[str, Any]:
            return self._registry_stage_into_scratch(
                module_slug,
                module_dir=module_dir,
                adaptation=adaptation,
                real_registry_stage=real_registry_stage,
            )

        with patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", True), patch.object(
            packet_builder, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            routes_module,
            "create_adaptation_staging_target",
            side_effect=self._staging_into_scratch,
        ), patch.object(
            routes_module, "run_upload_adaptation_authoring", side_effect=_authoring_with_runner
        ), patch.object(
            packet_builder, "_execute_module_builder", side_effect=self._builder_executor
        ), patch.object(
            routes_module, "_run_homebrew_readiness_gate", side_effect=self._readiness_fake
        ), patch.object(
            finisher, "_run_registry_stage", side_effect=_registry_into_scratch
        ), patch.object(adventure_writer, "_llm_intro_narrative", return_value=None), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(
            adventure_writer, "_llm_area_overview", return_value=None
        ):
            routes_module._run_homebrew_build_job(job_id)
        return self._snapshot_job(job_id)

    def _real_module_sentinels(self) -> Dict[str, Any]:
        """Snapshot real modules/ listing plus registry/campaign/source bytes."""
        modules_dir = REPO_ROOT / "modules"
        listing: List[str] = []
        if modules_dir.exists():
            listing = sorted(
                str(p.relative_to(REPO_ROOT))
                for p in modules_dir.rglob("*")
                if p.is_file()
            )
        return {
            "listing": listing,
            "registry_bytes": (
                self.real_registry.read_bytes() if self.real_registry.exists() else None
            ),
            "campaign_bytes": (
                self.real_campaign.read_bytes() if self.real_campaign.exists() else None
            ),
            "source_bytes": SOURCE_PATH.read_bytes(),
            "module_digest": self.protected_real_module,
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
        self.assertEqual(
            self.real_registry.read_bytes() if self.real_registry.exists() else None,
            snapshot["registry_bytes"],
        )
        self.assertEqual(
            self.real_campaign.read_bytes() if self.real_campaign.exists() else None,
            snapshot["campaign_bytes"],
        )
        self.assertEqual(SOURCE_PATH.read_bytes(), snapshot["source_bytes"])
        self.assertEqual(self.protected_real_module, _snapshot_tree(self.real_module))

    def _assert_published_success(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Shared assertions for a verified publication under the real route."""
        self.assertEqual(job.get("status"), "adaptation_completed", job)
        self.assertEqual(job.get("adaptation_mode"), "llm_adaptation")
        result = job.get("result") or {}
        self.assertEqual(result.get("status"), "success", result)
        self.assertEqual(result.get("ready_status"), "pass")
        self.assertEqual(result.get("publishable_status"), "pass")
        self.assertEqual(result.get("publication_order"), EXPECTED_PUBLICATION_ORDER)
        self.assertTrue(result.get("registry_is_final_stateful_publication"))
        stages = result.get("stages") or {}
        registry_stage = stages.get("registry") or {}
        self.assertEqual(registry_stage.get("status"), "success")
        self.assertIs(registry_stage.get("integration_attempted"), True)
        verification = registry_stage.get("verification") or {}
        self.assertIs(verification.get("verified"), True)
        self.assertIs(verification.get("module_verified"), True)
        self.assertIs(verification.get("areas_verified"), True)
        return result


class TestJeremysUploadJobPathNoActiveCampaign(
    _JeremysUploadScratchMixin, unittest.TestCase
):
    """Jeremys Magic Shop through the real upload job path with NO campaign
    file configured: registry publication succeeds and campaign
    synchronization reports the explicit deferred no-active-campaign outcome
    without false campaign success."""

    def test_catalogue_adaptation_publishes_with_explicit_no_active_campaign(
        self,
    ) -> None:
        self.assertFalse(self.campaign_path.exists())
        sentinels = self._real_module_sentinels()
        job_id = "jeremys-magic-shop-upload-7-1"
        job = self._run_upload_job(job_id)
        result = self._assert_published_success(job)

        # Explicit no-active-campaign handling: module/registry publication
        # succeeded, campaign sync reports deferred/no_active_campaign and
        # never claims campaign visibility or writes a campaign file.
        stages = result.get("stages") or {}
        campaign_stage = stages.get("campaign_sync") or {}
        self.assertEqual(campaign_stage.get("status"), "deferred")
        self.assertEqual(campaign_stage.get("reason"), "no_active_campaign")
        self.assertIs(campaign_stage.get("campaign_visibility_verified"), False)
        self.assertFalse(self.campaign_path.exists(), "no campaign file may be created")

        # The readiness gate is a real pre-finisher gate on the route.
        self.assertEqual(len(self.readiness_calls), 1)

        # The real packet-builder result was persisted into the workspace:
        # catalogue dossier accepted, all adaptation gates pass, attempt
        # report persisted, provenance surface attached.
        files = get_workspace_files(self.workspace)
        build_payload = json.loads(files["build_result"].read_text(encoding="utf-8"))
        self.assertEqual(build_payload.get("status"), "success", build_payload)
        self.assertEqual(build_payload.get("module_name"), MODULE_SLUG)
        self.assertEqual(build_payload["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        gates = build_payload.get("adaptation_gates") or {}
        self.assertEqual(gates.get("playable_status"), "pass", gates)
        for domain in (
            "schema",
            "readiness",
            "mechanical_closure",
            "semantic_authority",
            "semantic_probes",
            "report_agreement",
        ):
            self.assertEqual(
                (gates.get("gates") or {}).get(domain, {}).get("effective_status"),
                "pass",
                domain,
            )
        attempt_report = build_payload.get("adaptation_attempt_report") or {}
        self.assertEqual(attempt_report.get("status"), "persisted")
        self.assertEqual(attempt_report.get("source_hash"), self.source_hash)
        provenance = build_payload.get("adaptation_provenance") or {}
        self.assertEqual(str(provenance.get("source_hash") or "").lower(), self.source_hash)
        staging_target = build_payload.get("staging_target") or {}
        self.assertTrue(
            str(staging_target.get("path") or "").startswith("tmp/toolkit_adaptation_jeremys_upload_path"),
            staging_target,
        )
        module_dir = REPO_ROOT / build_payload["output_directory"]
        self.assertTrue((module_dir / "module_context.json").exists())

        # Readable persisted MODULE_SUMMARY.md with the adaptation notice and
        # expected module content, under the real quality contract, with no
        # credential leakage.
        summary_path = module_dir / "MODULE_SUMMARY.md"
        self.assertTrue(summary_path.exists())
        summary = summary_path.read_text(encoding="utf-8")
        self.assertGreater(len(summary), 500)
        self.assertIn("Adapted for NEQ-TTRPG", summary)
        self.assertIn("Jeremy", summary)
        lowered = summary.lower()
        for token in _CREDENTIAL_TOKENS:
            self.assertNotIn(token.lower(), lowered, "credential token leaked into summary")
        self.assertIsNone(
            _CREDENTIAL_KEY_RE.search(summary),
            "provider key shape leaked into summary",
        )

        # Provenance and fidelity surfaces persisted on the staged module.
        context = json.loads((module_dir / "module_context.json").read_text(encoding="utf-8"))
        context_prov = context.get("adaptation_provenance") or {}
        self.assertEqual(str(context_prov.get("source_hash") or "").lower(), self.source_hash)
        self.assertEqual(context_prov.get("rights_class"), "user_authored")
        self.assertEqual(context.get("adaptation_notice"), "Adapted for NEQ-TTRPG")
        world = context_prov.get("world_context_provenance") or {}
        self.assertEqual(world.get("fallback_status"), "seed_data_unavailable")
        self.assertIs(world.get("read_only"), True)
        self.assertTrue((module_dir / "source_fidelity_report.json").exists())
        fidelity = json.loads(
            (module_dir / "source_fidelity_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(str(fidelity.get("source_hash") or "").lower(), self.source_hash)

        # Authoring ran exactly once with the bounded catalogue source
        # context and Python-owned rights; the dossier artifact persisted.
        self.assertEqual(len(self.author_runner.calls), 1)
        source_context, attempt_metadata, _kwargs = self.author_runner.calls[0]
        self.assertEqual(source_context.get("source_profile"), "catalogue")
        self.assertEqual(attempt_metadata.get("source_profile"), "catalogue")
        self.assertEqual(attempt_metadata.get("rights_class"), "user_authored")
        self.assertEqual(attempt_metadata.get("source_hash"), self.source_hash)
        serialized_context = json.dumps(source_context, ensure_ascii=True)
        # The provider boundary receives only the bounded source context: no
        # credential tokens and a bounded serialized size (never the full
        # 79 KB raw source).
        for token in _CREDENTIAL_TOKENS:
            self.assertNotIn(token, serialized_context, "credential token leaked into source context")
        self.assertIsNone(_CREDENTIAL_KEY_RE.search(serialized_context))
        self.assertLess(len(serialized_context), 20_000)
        dossier_artifacts = list(
            (self.workspace / "adaptation_attempts").rglob("adaptation_dossier.json")
        )
        self.assertEqual(len(dossier_artifacts), 1)
        persisted_dossier = json.loads(dossier_artifacts[0].read_text(encoding="utf-8"))
        self.assertEqual(
            str((persisted_dossier.get("provenance") or {}).get("source_hash") or "").lower(),
            self.source_hash,
        )
        self.assertEqual(
            str((persisted_dossier.get("payload") or {}).get("source_hash") or "").lower(),
            self.source_hash,
        )

        # Registry-last: the scratch mirror received the module and areas,
        # and the registry stage ran after the readiness gate and after the
        # finisher's pre-registration gates (gate composer result above).
        self.assertEqual(len(self.registry_stage_calls), 1)
        persisted_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        module_entry = persisted_registry["modules"].get(MODULE_SLUG)
        self.assertIsInstance(module_entry, dict)
        self.assertEqual(module_entry.get("moduleName"), MODULE_SLUG)
        area_entries = [
            area for area in persisted_registry.get("areas", {}).values()
            if isinstance(area, dict) and area.get("module") == MODULE_SLUG
        ]
        self.assertTrue(area_entries, "no adapted area entries in the registry")
        self.assertFalse((REPO_ROOT / "modules" / MODULE_SLUG).exists())

        self._assert_real_sentinels_unchanged(sentinels)


class TestJeremysUploadJobPathInactiveCampaign(
    _JeremysUploadScratchMixin, unittest.TestCase
):
    """A campaign file with explicit inactive state is an explicit
    no-active-campaign outcome: publication succeeds, availability is not
    appended, and the campaign file is never falsely reported as synced."""

    def test_inactive_campaign_is_explicit_no_active_campaign(self) -> None:
        original_campaign: Dict[str, Any] = {
            "campaignName": "Fixture Campaign",
            "availableModules": ["Sentinel_Module"],
            "active": False,
            "currentModule": "Sentinel_Module",
        }
        _write_json(self.campaign_path, original_campaign)
        sentinels = self._real_module_sentinels()
        campaign_before = self.campaign_path.read_bytes()
        job = self._run_upload_job("jeremys-magic-shop-upload-7-1-inactive")
        result = self._assert_published_success(job)

        stages = result.get("stages") or {}
        campaign_stage = stages.get("campaign_sync") or {}
        self.assertEqual(campaign_stage.get("status"), "deferred")
        self.assertEqual(campaign_stage.get("reason"), "no_active_campaign")
        self.assertIs(campaign_stage.get("campaign_visibility_verified"), False)

        # The inactive campaign file was not modified (no availability
        # append) and no false campaign success was reported.
        self.assertEqual(self.campaign_path.read_bytes(), campaign_before)
        persisted_campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted_campaign["availableModules"], ["Sentinel_Module"])
        self.assertIs(persisted_campaign["active"], False)

        # Registry publication itself succeeded and is verified.
        persisted_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        self.assertIn(MODULE_SLUG, persisted_registry["modules"])
        summary = (
            REPO_ROOT
            / self._load_build_payload()["output_directory"]
            / "MODULE_SUMMARY.md"
        )
        self.assertTrue(summary.exists())
        self.assertIn("Adapted for NEQ-TTRPG", summary.read_text(encoding="utf-8"))

        self._assert_real_sentinels_unchanged(sentinels)

    def _load_build_payload(self) -> Dict[str, Any]:
        files = get_workspace_files(self.workspace)
        return json.loads(files["build_result"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
