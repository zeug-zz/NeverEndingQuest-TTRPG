# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Task 7.3 semantic-failure runtime tests for BOTH actual adaptation entry
paths (toolkit-llm-adaptation-runtime-unification).

The suite injects a deterministic semantic gate failure at the boundary after
authoring/build handoff but before stateful publication, through the ACTUAL
runtime entry paths:

  * the ACTUAL upload job path ``web/routes/toolkit_homebrew_routes
    ._run_homebrew_build_job`` (Jeremys Magic Shop source, equivalent to task
    7.1), and
  * the ACTUAL text-description Socket.IO worker
    ``web.web_interface.simulate_build_process`` (Sunken Lighthouse concept,
    equivalent to task 7.2).

For each path it verifies BOTH scenarios:

  * Scenario A (recovery): the first semantic failure creates a bounded
    revision-required outcome (job terminal ``adaptation_revision_required`` /
    blocked worker outcome), consumes no more than the allowed semantic
    revision budget, preserves the prior attempt identity, and a FRESH
    revision rebuild through the repository's REAL revision machinery
    (``run_adaptation_final_revision`` with the real packet builder and the
    real rebuild-directive contract) succeeds through the normal staged
    transaction and ONLY THEN publishes/finishes: exactly-once verified
    completion, registry-last ordering, report/Markdown/provenance identity,
    no legacy fallback.
  * Scenario B (exhaustion): the semantic failure persists through the allowed
    revision budget. The real revision runner terminates with
    ``revision_budget_exhausted`` and the real job-reporting contract maps the
    exhausted signal to the terminal ``adaptation_revision_exhausted`` job
    status. Protected real ``modules/`` listing, ``modules/world_registry.json``,
    ``modules/campaign.json``, and catalog/publication state stay
    byte-for-byte unchanged; no ``module_complete``, no ``adaptation_completed``,
    no registry/campaign mutation, no false success; diagnostics stay bounded
    and no raw source/provider/credential text leaks.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_semantic_failure_runtime/<uuid>/`` and are removed via
addCleanup. Attempt workspaces and reserved staging targets (initial and
revision) are project-relative, isolated, distinct per attempt/revision, never
under ``modules/<name>``, and failed attempts never become registry/campaign
publication. The registry/campaign files under the scratch ``modules/`` mirror
are the only runtime files touched. Real module/registry/campaign/source
sentinels are byte-checked. The live operator ``model_config.ENABLE_LLM_ADAPTATION``
value is never relied on (every behavioral test patches it explicitly).
Network/SDK/socket tripwires fail loudly if anything attempts a live call.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import shutil
import socket
import sys
import types
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
import utils.toolkit_adaptation_campaign as campaign_sync
import utils.toolkit_adaptation_gate_composer as gate_composer
import utils.toolkit_adaptation_registry as adaptation_registry
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
from web.extensions.toolkit_adaptation_runtime import adaptation_convergence_callback
import web.extensions.toolkit_module_finisher as finisher
import web.extensions.toolkit_text_adaptation_worker as worker
import web.routes.toolkit_homebrew_routes as routes_module
import web.web_interface as web_interface
from utils.toolkit_adaptation_auditor import ADAPTATION_AUDITOR_CONTRACT_VERSION
from utils.toolkit_adaptation_config import BUILD_MODE_LLM_ADAPTATION
from utils.toolkit_adaptation_failure_packet import (
    build_adaptation_failure_packet,
    validate_adaptation_failure_packet,
)
from utils.toolkit_adaptation_revision import (
    REVISION_STATUS_FAILED,
    REVISION_STATUS_REVISION_PASSED,
    run_adaptation_final_revision,
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
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_semantic_failure_runtime"
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
# Known gate-passing module used only as a provider-free builder
# materialization fixture; the staged module is renamed and receives the
# adaptation provenance before the real adaptation gates run.  Keep this on a
# standalone semantic-authority pass fixture so the isolated copy does not
# depend on handoff targets in other module directories.
BUILDER_FIXTURE = REPO_ROOT / "modules" / "The_Pumpkin_Kings_Curse"

UPLOAD_SOURCE_PATH = (
    REPO_ROOT / "Local_Docs" / "modules" / "hombrew" / "modules"
    / "Jeremys Magic Shop.md"
)
UPLOAD_SOURCE_REFERENCE = (
    "Local_Docs/modules/hombrew/modules/Jeremys Magic Shop.md"
)
UPLOAD_MODULE_SLUG = "Jeremys_Magic_Shop"
UPLOAD_MODULE_TITLE = "Jeremy's Magic Shop"

TEXT_MODULE_NAME = "Sunken_Lighthouse"
TEXT_MODULE_TITLE = "Sunken Lighthouse"
TEXT_FIXTURE = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
    "The bell chamber hides a corroded bronze key.\n"
    "A spectral keeper guards the light; the party must decide.\n"
)
TEXT_FIXTURE_HASH = hashlib.sha256(TEXT_FIXTURE.encode("utf-8")).hexdigest()

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
_CREDENTIAL_KEY_RE = __import__("re").compile(r"sk-[A-Za-z0-9_-]{8,}")
# Capture the REAL semantic authority gate before any test patch redirects it,
# so deterministic seams can delegate to the real gate without recursion.
_REAL_SEMANTIC_GATE = gate_composer._run_semantic_authority_gate


def _write_json(path: Path, payload: object) -> None:
    """Write a scratch fixture JSON file deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def _evidence_refs(packet: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Echo the packet's bounded gate evidence references (auditor contract)."""
    refs: List[Dict[str, Any]] = []
    seen = set()
    for collection_name in ("gate_statuses", "gate_findings"):
        for item in packet.get(collection_name, []):
            reference = item.get("evidence_ref") if isinstance(item, dict) else None
            if not isinstance(reference, dict):
                continue
            key = json.dumps(reference, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen.add(key)
                refs.append(deepcopy(reference))
    return sorted(refs, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))


class FakeAuthorRunner:
    """Deterministic injectable author provider (never touches a service)."""

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
                "model": "provider-free-semantic-failure-author",
                "request_id": "req-semantic-failure-7-3",
            },
            "params_used": {"reasoning_effort": "medium"},
        }


class _GuardedModuleBuilder:
    """ModuleBuilder fake that FAILS if the legacy direct path is reached."""

    last_instance: Optional["_GuardedModuleBuilder"] = None

    def __init__(self, config: Any) -> None:
        _GuardedModuleBuilder.last_instance = self
        raise AssertionError(
            "legacy ModuleBuilder must never be constructed on the adaptation path"
        )


class _FakeBuilderConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.module_name = kwargs.get("module_name")
        self.num_areas = kwargs.get("num_areas")
        self.locations_per_area = kwargs.get("locations_per_area")
        self.output_directory = kwargs.get("output_directory")
        self.verbose = kwargs.get("verbose")


def _fake_builder_module(builder_class: type) -> types.ModuleType:
    fake = types.ModuleType("core.generators.module_builder")
    fake.ModuleBuilder = builder_class
    fake.BuilderConfig = _FakeBuilderConfig
    return fake


class _EmitRecorder:
    """Records socketio.emit calls in order."""

    def __init__(self) -> None:
        self.events: List[Tuple[str, Any]] = []

    def emit(self, event: str, payload: Any) -> None:
        self.events.append((str(event), deepcopy(payload)))


class _SemanticFailureRuntimeMixin:
    """Shared scratch, real sentinels, seams, and tripwires for task 7.3."""

    module_slug = ""
    module_title = ""
    job_id = ""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._cleanup_scratch_root)
        self.staging_root = (
            "tmp/toolkit_adaptation_semantic_failure_runtime"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.workspaces_root = (
            "tmp/toolkit_adaptation_semantic_failure_runtime"
            + "/"
            + self.scratch.name
            + "/workspaces"
        )
        self.registry_path = self.scratch / "modules" / "world_registry.json"
        self.campaign_path = self.scratch / "modules" / "campaign.json"
        self.original_registry: Dict[str, Any] = {
            "worldName": "Semantic Failure Fixture World",
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
        self.original_registry_bytes = self.registry_path.read_bytes()
        self.original_campaign: Dict[str, Any] = {
            "campaignName": "Semantic Failure Fixture Campaign",
            "availableModules": ["Sentinel_Module"],
            "active": True,
            "currentModule": "Sentinel_Module",
        }
        _write_json(self.campaign_path, self.original_campaign)
        self.original_campaign_bytes = self.campaign_path.read_bytes()

        self.author_runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        self.recorder = _EmitRecorder()
        self.semantic_gate_calls: List[Path] = []
        self.monster_closure_calls: List[Path] = []
        self.revision_build_calls: List[Dict[str, Any]] = []
        self.auditor_calls: List[Dict[str, Any]] = []
        self.finisher_calls: List[str] = []
        self.last_build_results: List[Dict[str, Any]] = []
        self.job_ids: List[str] = []
        self.addCleanup(self._clear_jobs)

        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", False
        )
        self._flag_patch.start()
        self.addCleanup(self._stop_flag_patch)

        self.real_registry = REPO_ROOT / "modules" / "world_registry.json"
        self.real_campaign = REPO_ROOT / "modules" / "campaign.json"
        self.real_module = REPO_ROOT / "modules" / self.module_slug
        self.protected_real_state = {
            path: (path.read_bytes() if path.exists() else None)
            for path in (self.real_registry, self.real_campaign)
        }
        self.protected_real_module = _snapshot_tree(self.real_module)

        self.tripwire_patchers = [
            patch.object(
                adaptation_auditor,
                "create_chat_client",
                side_effect=self._blocked_provider,
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

    def _stop_flag_patch(self) -> None:
        self._flag_patch.stop()

    def _enable_adaptation(self) -> None:
        self._flag_patch.stop()
        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        )
        self._flag_patch.start()

    def _stop_tripwires(self) -> None:
        for patcher in reversed(self.tripwire_patchers):
            patcher.stop()

    @staticmethod
    def _blocked_provider(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live provider client creation is forbidden in task 7.3")

    @staticmethod
    def _blocked_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network access is forbidden in task 7.3")

    def _clear_jobs(self) -> None:
        with routes_module._jobs_lock:
            for job_id in self.job_ids:
                routes_module._jobs.pop(job_id, None)
            routes_module._active_job_id = None

    def _cleanup_scratch_root(self) -> None:
        """Remove the per-test scratch and the empty suite scratch root."""
        shutil.rmtree(self.scratch, ignore_errors=True)
        try:
            if SCRATCH_ROOT.exists() and not any(SCRATCH_ROOT.iterdir()):
                SCRATCH_ROOT.rmdir()
        except OSError:
            pass

    def _snapshot_job(self, job_id: str) -> Dict[str, Any]:
        with routes_module._jobs_lock:
            job = routes_module._jobs.get(job_id)
            return dict(job) if job is not None else {}

    # -- deterministic semantic gate seam ----------------------------------

    def _semantic_gate_fail_once(
        self, module_slug: str, module_dir: Any, **_: Any
    ) -> Dict[str, Any]:
        """Block the FIRST semantic authority gate call, then delegate to the
        real gate. Deterministic injection at the boundary after authoring and
        build handoff but before stateful publication."""
        self.semantic_gate_calls.append(Path(module_dir).resolve())
        if len(self.semantic_gate_calls) == 1:
            return {
                "status": "blocked",
                "errors": ["controlled semantic failure: ambiguous shop destination"],
                "blockers": ["controlled semantic failure: ambiguous shop destination"],
                "warnings": [],
            }
        return _REAL_SEMANTIC_GATE(module_slug, module_dir)

    def _semantic_gate_always_fail(
        self, module_slug: str, module_dir: Any, **_: Any
    ) -> Dict[str, Any]:
        """Block EVERY semantic authority gate call (persistent failure)."""
        self.semantic_gate_calls.append(Path(module_dir).resolve())
        return {
            "status": "blocked",
            "errors": ["controlled semantic failure: destination remains ambiguous"],
            "blockers": ["controlled semantic failure: destination remains ambiguous"],
            "warnings": [],
        }

    def _monster_closure_success(
        self, module_name: str, module_dir: Any, **_: Any
    ) -> Dict[str, Any]:
        """Keep semantic-failure tests past the provider-free closure stage."""
        self.monster_closure_calls.append(Path(module_dir).resolve())
        return {
            "required": 0,
            "existing_before": 0,
            "generated": 0,
            "unresolved": 0,
            "ambiguous_npc_like": [],
        }

    # -- scratch redirect seams ----------------------------------------------

    def _staging_into_scratch(self, source_hash: str, **kwargs: Any) -> Dict[str, Any]:
        kwargs.pop("staging_root", None)
        from utils.toolkit_adaptation_staging import create_adaptation_staging_target

        return create_adaptation_staging_target(
            source_hash,
            staging_root=self.staging_root,
            **kwargs,
        )

    def _registry_stage_into_scratch(
        self,
        module_slug: str,
        *,
        module_dir: Any = None,
        adaptation: bool = False,
        real_registry_stage: Callable[..., Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Run the REAL registry transaction inside the scratch modules mirror."""
        if real_registry_stage is None:
            raise AssertionError("real registry stage was not captured before patching")
        with _chdir(self.scratch):
            return real_registry_stage(
                module_slug, module_dir=module_dir, adaptation=adaptation
            )

    # -- builder executor ----------------------------------------------------

    def _builder_executor(
        self, builder_input: Dict[str, Any], progress_callback: Optional[Any] = None
    ) -> None:
        """Materialize a known gate-passing module without a provider."""
        self.assertEqual(builder_input["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        target = (
            REPO_ROOT / builder_input["derived_builder_parameters"]["output_directory"]
        ).resolve()
        target.relative_to((REPO_ROOT / "tmp").resolve())
        shutil.copytree(BUILDER_FIXTURE, target, dirs_exist_ok=True)
        (target / "toolkit_build_report.json").unlink(missing_ok=True)
        # Keep the copied provider-free fixture schema-sufficient for the
        # adaptation gate's referenced-monster scan.  The source fixture uses
        # plural filenames while the normalized staging references are the
        # singular identities; this is test-only closure materialization.
        for source_name, target_name in (
            ("pumpkin_stalkers.json", "pumpkin_stalker.json"),
            ("swarm_of_field_rats.json", "swarm_of_field_rat.json"),
        ):
            source_path = target / "monsters" / source_name
            target_path = target / "monsters" / target_name
            if source_path.is_file() and not target_path.exists():
                shutil.copyfile(source_path, target_path)
        context_path = target / "module_context.json"
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["module_id"] = self.module_slug
        context["module_name"] = self.module_title
        existing_context_areas = context.get("areas")
        existing_context_areas = (
            existing_context_areas if isinstance(existing_context_areas, Mapping) else {}
        )
        live_area_stems = [
            area_path.stem
            for area_path in sorted((target / "areas").glob("*.json"))
            if not area_path.name.endswith("_BU.json")
        ]
        # Keep the production registry/finisher contract strict while making
        # this copied provider-free fixture internally canonical.  Stale
        # context-only keys must not survive into the isolated gate run.
        context["areas"] = {
            stem: deepcopy(existing_context_areas.get(stem, {}))
            for stem in live_area_stems
        }
        _write_json(context_path, context)
        if progress_callback:
            progress_callback(
                "build",
                "Provider-free adaptation materialized into staging",
            )

    # -- real-state sentinels -----------------------------------------------

    def _snapshot_real_state(self) -> Dict[str, Any]:
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
            "module_digest": self.protected_real_module,
        }

    def _assert_real_state_unchanged(self, snapshot: Dict[str, Any]) -> None:
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
        self.assertEqual(listing, snapshot["listing"], "real modules tree mutated")
        self.assertEqual(
            self.real_registry.read_bytes() if self.real_registry.exists() else None,
            snapshot["registry_bytes"],
            "real registry mutated",
        )
        self.assertEqual(
            self.real_campaign.read_bytes() if self.real_campaign.exists() else None,
            snapshot["campaign_bytes"],
            "real campaign mutated",
        )
        self.assertEqual(self.protected_real_module, _snapshot_tree(self.real_module))
        self.assertFalse(
            self.real_module.exists(),
            "no direct modules/<name> write on the adaptation path",
        )

    def _assert_scratch_publication_unchanged(self) -> None:
        self.assertEqual(self.registry_path.read_bytes(), self.original_registry_bytes)
        self.assertEqual(self.campaign_path.read_bytes(), self.original_campaign_bytes)

    def _assert_no_leakage(self, text: str, label: str) -> None:
        lowered = text.lower()
        for token in _CREDENTIAL_TOKENS:
            self.assertNotIn(
                token.lower(), lowered, f"credential token leaked into {label}"
            )
        self.assertIsNone(
            _CREDENTIAL_KEY_RE.search(text),
            f"provider key shape leaked into {label}",
        )

    # -- failure packet + revision machinery --------------------------------

    def _attempt_metadata_from_provenance(
        self,
        provenance: Mapping[str, Any],
        dossier: Mapping[str, Any],
        *,
        source_path: str,
        stage: str = "adaptation_gates",
    ) -> Dict[str, Any]:
        """Assemble deterministic attempt metadata from a provenance envelope.

        Both provenance shapes are accepted: the canonical flat envelope
        (``attempt_id`` at top level, produced by ``build_adaptation_provenance``
        on blocked build results) and the route/text nested envelope
        (``attempt_metadata`` mapping from the authoring handoff).
        """
        nested = provenance.get("attempt_metadata")
        nested = nested if isinstance(nested, Mapping) else {}
        attempt_id = str(
            nested.get("attempt_id") or provenance.get("attempt_id") or ""
        )
        attempt_number = nested.get("attempt_number")
        if attempt_number is None:
            attempt_number = provenance.get("attempt_number")
        revision_number = nested.get("revision_number")
        if revision_number is None:
            revision_number = provenance.get("revision_number")
        return {
            "attempt_id": attempt_id,
            "attempt_number": int(attempt_number or 1),
            "revision_number": int(revision_number or 0),
            "job_id": nested.get("job_id") or provenance.get("job_id") or "",
            "stage": stage,
            "source_title": dossier.get("source_title")
            or provenance.get("source_title")
            or "",
            "source_hash": str(
                nested.get("source_hash")
                or provenance.get("source_hash")
                or dossier.get("source_hash")
                or ""
            ).lower(),
            "source_path": source_path,
            "source_profile": dossier.get("source_profile") or "unknown",
            "source_format": str(
                provenance.get("source_format") or "markdown"
            ),
            "adaptation_mode": "llm_adaptation",
            "rights_class": dossier.get("rights_class")
            or provenance.get("rights_class")
            or "user_authored",
            "rights_basis": dossier.get("rights_basis")
            or provenance.get("rights_basis")
            or "user_authored_uploaded_adventure",
            "rights_review_required": bool(
                dossier.get("rights_review_required") is True
                or provenance.get("rights_review_required") is True
            ),
            "rights_review_status": dossier.get("rights_review_status")
            or provenance.get("rights_review_status")
            or "not_required",
            "model_metadata": {
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "parameter_profile": "toolkit_adaptation_semantic_auditor",
            },
        }

    def _build_failure_packet(
        self,
        build_result: Dict[str, Any],
        provenance: Mapping[str, Any],
        dossier: Mapping[str, Any],
        *,
        source_path: str,
    ) -> Dict[str, Any]:
        """Build the REAL bounded failure packet from a gate-blocked build."""
        gates = build_result.get("adaptation_gates")
        gates = gates if isinstance(gates, Mapping) else {}
        classification = gates.get("failure_classification")
        classification = (
            deepcopy(classification) if isinstance(classification, Mapping) else {}
        )
        # Python-owned opt-in: the real classifier requires an explicit
        # revision marker plus a remaining bounded budget before a semantic
        # failure may consume one revision. The real gate classification is
        # terminal by default, so the bounded packet must carry the explicit
        # non-terminal opt-in markers (completed scaffold revision contract,
        # failure packet v1).
        classification["classification_status"] = "revision_eligible"
        classification["semantic_revision_eligible"] = True
        classification["revision_eligible"] = True
        classification["consumes_semantic_revision_budget"] = True
        classification["terminal"] = False
        classification["retryable"] = True
        classification["blocked"] = False
        classification.setdefault("failure_class", "semantic")
        classification["revision_budget"] = {
            "current_revision": 0,
            "max_revisions": 1,
            "remaining_before_failure": 1,
            "explicit_opt_in": True,
            "decision": "eligible",
        }
        staging_target = build_result.get("staging_target")
        staging_target = (
            staging_target if isinstance(staging_target, Mapping) else {}
        )
        attempt_metadata = self._attempt_metadata_from_provenance(
            provenance,
            dossier,
            source_path=source_path,
        )
        packet = build_adaptation_failure_packet(
            gates,
            attempt_metadata=attempt_metadata,
            staging_target=staging_target,
            module_dir=(
                REPO_ROOT / staging_target["path"] if staging_target.get("path") else None
            ),
            source_context_refs=[
                {
                    "path": source_path,
                    "sha256": attempt_metadata["source_hash"],
                    "role": "source",
                }
            ],
            publication_goals=[
                "schema",
                "readiness",
                "mechanical_closure",
                "semantic_authority",
                "semantic_probes",
                "report_agreement",
                "markdown_quality",
                "registry_verification",
            ],
            failure_classification=classification,
            world_context_provenance=provenance.get("world_context_provenance"),
            stage="adaptation_gates",
            revision_number=0,
            repo_root=REPO_ROOT,
        )
        return packet

    def _auditor(self, failure_packet: Dict[str, Any], **_: Any) -> Dict[str, Any]:
        """Deterministic real-contract auditor: always requests a fresh
        revision with a Python-validated revised dossier."""
        self.auditor_calls.append(deepcopy(failure_packet))
        attempt = failure_packet.get("attempt_metadata") or {}
        refs = _evidence_refs(failure_packet)
        revised_dossier = deepcopy(self.dossier)
        revised_dossier["adapted_title"] = (
            self.module_title + " (Fresh Revision)"
        )
        response = {
            "version": ADAPTATION_AUDITOR_CONTRACT_VERSION,
            "decision": "revise",
            "reason": (
                "The controlled semantic failure is bounded and can be resolved "
                "by a fresh staged revision."
            ),
            "attempt_id": attempt.get("attempt_id"),
            "stage": attempt.get("stage"),
            "revision_number": attempt.get("revision_number"),
            "source_hash": attempt.get("source_hash"),
            "model_metadata": deepcopy(attempt.get("model_metadata") or {}),
            "gate_evidence_refs": refs,
            "revised_dossier": revised_dossier,
        }
        return {
            "status": "success",
            "decision": "revise",
            "ok": True,
            "response": response,
            "model_metadata": {
                "provider": "fixture",
                "model": "provider-free-semantic-failure-auditor",
            },
        }

    def _revision_builder(
        self,
        staging_target: Dict[str, Any],
        dossier: Dict[str, Any],
        directive: Dict[str, Any],
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Fresh-revision rebuild through the REAL packet builder."""
        self.revision_build_calls.append(
            {
                "target": deepcopy(staging_target),
                "dossier": deepcopy(dossier),
                "directive": deepcopy(directive),
                "attempt_metadata": deepcopy(dict(attempt_metadata or {})),
            }
        )
        result = packet_builder.run_toolkit_homebrew_packet_build(
            workspace=self.workspace,
            job_id=self.job_id + "-revision",
            builder_executor=self._builder_executor,
            adaptation_route=BUILD_MODE_LLM_ADAPTATION,
            adaptation_dossier=dossier,
            adaptation_provenance=dict(attempt_metadata or {}),
            adaptation_staging_root=self.staging_root,
            adaptation_staging_target=staging_target,
            adaptation_convergence_callback=adaptation_convergence_callback,
        )
        if result.get("status") != "success":
            # Expose the Python-owned gate facts to the real revision
            # classifier (completed scaffold contract: the callback may carry
            # gate_results / failure facts for the bounded next revision).
            # The classification is a fresh bounded opt-in record: the real
            # classifier re-derives terminal/eligible/exhausted from the
            # revision number and budget, so no stale terminal markers from
            # the first attempt may leak in.
            gates = result.get("adaptation_gates")
            gates = gates if isinstance(gates, Mapping) else {}
            raw_classification = gates.get("failure_classification")
            raw_classification = (
                raw_classification if isinstance(raw_classification, Mapping) else {}
            )
            result["failure_class"] = "semantic"
            result["revision_eligible"] = True
            result["failure_classification"] = {
                "failure_class": "semantic",
                "failure_group": "content",
                "classification_status": "revision_eligible",
                "code": "controlled_semantic_gate_failure",
                "message": (
                    raw_classification.get("message")
                    or "semantic gate remains blocked after revision"
                ),
                "semantic_revision_eligible": True,
                "revision_eligible": True,
                "consumes_semantic_revision_budget": True,
            }
            result["gate_result"] = deepcopy(gates.get("gates") or {})
        self.last_build_results.append(deepcopy(result))
        return result

    def _run_revision(
        self,
        failure_packet: Dict[str, Any],
        *,
        workspace: Path,
        module_slug: str,
        semantic_seam: Optional[Callable[[str, Any], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run the REAL bounded final revision through the REAL packet builder."""
        patchers = [
            patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", True),
            patch(
                "utils.toolkit_adaptation_monster_guardrail.build_adaptation_monster_guardrail_report",
                return_value={
                    "version": "toolkit_adaptation_monster_guardrail.v1",
                    "report_version": "toolkit_adaptation_monster_guardrail.v1",
                    "status": "pass",
                    "monsters_unresolved": 0,
                    "encounters_unresolved": 0,
                    "encounters_unbound": 0,
                    "unresolved_refs": [],
                },
            ),
            patch(
                "utils.monster_reference_closure.ensure_monster_reference_closure",
                side_effect=self._monster_closure_success,
            ),
            patch.object(
                gate_composer,
                "collect_referenced_monsters",
                return_value=[],
            ),
            patch.object(
                gate_composer,
                "collect_existing_monster_slugs",
                return_value=[],
            ),
        ]
        if semantic_seam is not None:
            patchers.append(
                patch.object(
                    gate_composer,
                    "_run_semantic_authority_gate",
                    side_effect=semantic_seam,
                )
            )
        for patcher in patchers:
            patcher.start()
        try:
            return run_adaptation_final_revision(
                failure_packet,
                workspace=workspace,
                repo_root=REPO_ROOT,
                staging_root=self.staging_root,
                module_slug=module_slug,
                build_callback=self._revision_builder,
                auditor_runner=self._auditor,
                current_dossier=self.dossier,
                max_revisions=1,
            )
        finally:
            for patcher in reversed(patchers):
                patcher.stop()

    # -- real finisher transaction ------------------------------------------

    def _run_revision_finisher(
        self,
        revision_result: Dict[str, Any],
        revision_build_result: Dict[str, Any],
        *,
        provenance: Mapping[str, Any],
        workspace: Path,
        module_slug: str,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Run the REAL shared finisher transaction on the fresh revision.

        The REAL Homebrewery Markdown stage runs (only the three LLM writer
        seams are pinned to the deterministic fallback) so the persisted
        ``MODULE_SUMMARY.md`` carries the fresh revision identity.
        """
        events: List[str] = []
        real_registry_stage = finisher._run_registry_stage
        real_campaign_sync = campaign_sync.synchronize_adaptation_campaign_module
        real_summary_stage = finisher._run_module_summary_stage

        def _summary(module_slug_arg: str, module_dir: Any, **kwargs: Any) -> Dict[str, Any]:
            events.append("markdown")
            return real_summary_stage(module_slug_arg, module_dir, **kwargs)

        def _registry(module_slug: str, *, module_dir: Any = None, adaptation: bool = False) -> Dict[str, Any]:
            events.append("registry")
            return self._registry_stage_into_scratch(
                module_slug,
                module_dir=module_dir,
                adaptation=adaptation,
                real_registry_stage=real_registry_stage,
            )

        def _campaign(slug: str, **kwargs: Any) -> Dict[str, Any]:
            events.append("campaign")
            return real_campaign_sync(slug, **kwargs)

        patchers = [
            patch.object(
                finisher, "_run_module_summary_stage", side_effect=_summary
            ),
            patch.object(finisher, "_run_registry_stage", side_effect=_registry),
            patch.object(
                campaign_sync,
                "synchronize_adaptation_campaign_module",
                side_effect=_campaign,
            ),
            patch.object(adventure_writer, "_llm_intro_narrative", return_value=None),
            patch.object(adventure_writer, "_llm_plot_hook", return_value=None),
            patch.object(adventure_writer, "_llm_area_overview", return_value=None),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            result = finisher.run_toolkit_module_postbuild_finishing(
                module_slug,
                strict=True,
                adaptation_mode=BUILD_MODE_LLM_ADAPTATION,
                adaptation_gates=revision_build_result.get("adaptation_gates"),
                adaptation_staging_target=revision_result["staging_target"],
                adaptation_module_dir=revision_result["staging_target"]["path"],
                adaptation_provenance=provenance,
                adaptation_artifact_workspace=str(workspace),
            )
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
        self.finisher_calls.append(module_slug)
        return result, events

    def _load_persisted_dossier(self, workspace: Path, attempt_id: str) -> Dict[str, Any]:
        """Load the REAL persisted authoring dossier for the attempt.

        The blocked build result does not echo the dossier; the attempt-scoped
        ``adaptation_dossier.json`` artifact is the Python-owned identity
        source (payload first, per the artifact contract)."""
        artifact = workspace / "adaptation_attempts" / attempt_id / "adaptation_dossier.json"
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        dossier = payload.get("payload") if isinstance(payload, Mapping) else None
        if isinstance(dossier, Mapping) and dossier:
            return deepcopy(dossier)
        return payload

    def _assert_revision_artifacts_retained(
        self,
        revision_result: Dict[str, Any],
        workspace: Path,
        attempt_id: str,
    ) -> None:
        """Prior attempt dossier artifact plus fresh revision build artifacts
        are retained on the shared workspace; the fresh target is isolated."""
        attempt_dir = workspace / "adaptation_attempts" / attempt_id
        self.assertTrue((attempt_dir / "adaptation_dossier.json").is_file())
        revision_build_path = (
            attempt_dir / "revisions" / "revision_001" / "build_result.json"
        )
        self.assertTrue(
            revision_build_path.is_file(),
            "fresh revision build artifact must be persisted",
        )
        target_path = str(revision_result["staging_target"]["path"])
        self.assertTrue(target_path.startswith(self.staging_root + "/"))
        self.assertNotIn("modules/", target_path)
        self.assertFalse(Path(target_path).is_absolute())
        self.assertEqual(revision_result["staging_target"]["revision_number"], 1)
        self.assertIn("revision_001", target_path)
        self.assertNotIn("revision_000", target_path)

    def _assert_build_result_projection(
        self,
        workspace: Path,
        attempt_id: str,
        revision_number: int,
        *,
        next_revision_eligible: bool,
        remaining_revisions: int,
    ) -> None:
        """Assert persisted artifact fields agree with runtime projections."""
        relative_dir = workspace / "adaptation_attempts" / attempt_id
        artifact_path = relative_dir / "build_result.json"
        if revision_number:
            artifact_path = relative_dir / "revisions" / f"revision_{revision_number:03d}" / "build_result.json"
        self.assertTrue(artifact_path.is_file(), str(artifact_path))
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        payload = artifact.get("payload") or {}
        projection = (payload.get("gate_summary") or {}).get("revision_projection") or {}
        self.assertEqual(artifact.get("attempt_id"), attempt_id)
        self.assertEqual(artifact.get("revision_number"), revision_number)
        self.assertEqual(projection.get("next_revision_eligible"), next_revision_eligible)
        self.assertEqual(projection.get("revision_eligible"), next_revision_eligible)
        self.assertEqual(projection.get("remaining_revisions"), remaining_revisions)
        self.assertEqual(projection.get("max_revisions"), 1)
        self.assertEqual(payload.get("staging", {}).get("isolated"), True)
        serialized = json.dumps(artifact, ensure_ascii=True, default=str)
        self.assertNotIn(os.sep + "tmp" + os.sep, serialized)
        self._assert_no_leakage(serialized, "persisted build result")

    def _assert_verified_finisher_success(
        self, result: Dict[str, Any], events: List[str]
    ) -> None:
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
        self.assertIs(registry_stage["integration_attempted"], True)
        self.assertIs(registry_stage["verified"], True)
        verification = registry_stage.get("verification") or {}
        self.assertIs(verification.get("module_verified"), True)
        self.assertIs(verification.get("areas_verified"), True)
        campaign_stage = result["stages"]["campaign_sync"]
        self.assertEqual(campaign_stage["status"], "success")
        self.assertIs(campaign_stage["campaign_visibility_verified"], True)


class TestUploadPathSemanticFailureRevisionRecovery(
    _SemanticFailureRuntimeMixin, unittest.TestCase
):
    """Scenario A on the ACTUAL upload job path: a first semantic failure is a
    bounded revision-required outcome; a fresh revision rebuild through the
    REAL revision machinery and REAL shared finisher publishes exactly once
    with registry-last ordering and full provenance identity."""

    module_slug = UPLOAD_MODULE_SLUG
    module_title = UPLOAD_MODULE_TITLE
    job_id = "semantic-failure-upload-job"

    def _make_workspace(self) -> Path:
        workspace = self.scratch / "workspace"
        ensure_workspace_placeholders(workspace)
        files = get_workspace_files(workspace)
        self.source_hash = hashlib.sha256(UPLOAD_SOURCE_PATH.read_bytes()).hexdigest()
        packet: Dict[str, Any] = {
            "packet_version": "v1",
            "normalization_state": "normalized",
            "source_hash": self.source_hash,
            "source_path": UPLOAD_SOURCE_REFERENCE,
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
        persist_normalized_packet_artifact(workspace, packet)
        snapshot = build_review_snapshot(
            job_id=self.job_id,
            decision=REVIEW_DECISION_APPROVE,
            packet=packet,
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
        )
        persist_review_snapshot_artifact(workspace, snapshot)
        files["source_original"].write_bytes(UPLOAD_SOURCE_PATH.read_bytes())
        for name in ("build_result", "readiness_validation_report", "readiness_audit_report"):
            files[name].write_text("{}", encoding="utf-8")
        return workspace

    def _register_job(self) -> None:
        with routes_module._jobs_lock:
            routes_module._jobs[self.job_id] = {
                "job_id": self.job_id,
                "job_type": "toolkit_homebrew_md_ingest",
                "status": "approved_for_build",
                "stage": "build",
                "pipeline_status": "building",
                "artifact_workspace": str(self.workspace),
                "source_kind": "markdown",
                "source_filename": "Jeremys Magic Shop.md",
                "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
                "review_decision": REVIEW_DECISION_APPROVE,
                "expected_module_name": UPLOAD_MODULE_SLUG,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        self.job_ids.append(self.job_id)

    def _run_route_initial(
        self, semantic_seam: Callable[[str, Any], Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Run the ACTUAL upload route ``_run_homebrew_build_job`` with the
        injected semantic gate failure."""
        self.workspace = self._make_workspace()
        self._register_job()
        real_authoring = routes_module.run_upload_adaptation_authoring

        def _authoring_with_runner(handoff: Any, **kwargs: Any) -> Dict[str, Any]:
            return real_authoring(
                handoff,
                workspace=kwargs.get("workspace"),
                author_runner=self.author_runner,
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
            __import__(
                "utils.toolkit_adaptation_monster_guardrail",
                fromlist=["build_adaptation_monster_guardrail_report"],
            ),
            "build_adaptation_monster_guardrail_report",
            return_value={
                "version": "toolkit_adaptation_monster_guardrail.v1",
                "report_version": "toolkit_adaptation_monster_guardrail.v1",
                "status": "pass",
                "monsters_unresolved": 0,
                "encounters_unresolved": 0,
                 "encounters_unbound": 0,
                 "unresolved_refs": [],
             },
         ), patch.object(
             __import__(
                 "utils.monster_reference_closure",
                 fromlist=["ensure_monster_reference_closure"],
             ),
             "ensure_monster_reference_closure",
             side_effect=self._monster_closure_success,
         ), patch.object(
             gate_composer,
             "collect_referenced_monsters",
             return_value=[],
         ), patch.object(
             gate_composer,
             "collect_existing_monster_slugs",
             return_value=[],
         ), patch.object(
             gate_composer,
             "_run_semantic_authority_gate",
             side_effect=semantic_seam,
        ):
            routes_module._run_homebrew_build_job(self.job_id)
        return self._snapshot_job(self.job_id)

    def test_first_semantic_failure_is_revision_required_then_fresh_revision_publishes(
        self,
    ) -> None:
        sentinels = self._snapshot_real_state()
        self._enable_adaptation()
        job = self._run_route_initial(self._semantic_gate_fail_once)

        # --- First semantic failure: bounded revision-required outcome ------
        self.assertEqual(job.get("status"), "adaptation_revision_required", job)
        self.assertEqual(job.get("adaptation_outcome"), "semantic_revision")
        self.assertIs(job.get("adaptation_terminal"), True)
        self.assertEqual(job.get("adaptation_failure_surface"), "semantic_revision")
        retry = job.get("adaptation_retry_diagnostics") or {}
        self.assertEqual(retry.get("status"), "available")
        self.assertEqual(retry.get("remaining_revisions"), 1)
        self.assertEqual(retry.get("max_revisions"), 1)
        self.assertIs(retry.get("semantic_revision_budget_consumed"), False)
        self.assertIsNotNone(job.get("adaptation_attempt_id"))
        attempt_id = str(job["adaptation_attempt_id"])
        self.assertEqual(job.get("adaptation_source_hash"), self.source_hash)
        result = job.get("result") or {}
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("stage"), "adaptation_gates")
        self.assertEqual(result.get("error"), "adaptation_gates_blocked")
        gates = result.get("adaptation_gates") or {}
        self.assertEqual(gates.get("playable_status"), "blocked")
        self.assertEqual(
            (gates.get("gates") or {}).get("semantic_authority", {}).get("status"),
            "blocked",
        )
        self._assert_build_result_projection(
            self.workspace,
            attempt_id,
            0,
            next_revision_eligible=True,
            remaining_revisions=1,
        )
        # Never a completion: no adaptation_completed, no publication side
        # effect on the real repo or the scratch mirror.
        self.assertNotEqual(job.get("status"), "adaptation_completed")
        self.assertEqual(job.get("stage"), "build_fidelity")
        self.assertEqual(self.author_runner.calls and len(self.author_runner.calls), 1)
        self.assertEqual(len(self.semantic_gate_calls), 1)
        # Bounded diagnostics, no raw source or credential leakage.
        self.assertLess(len(job.get("adaptation_status_text") or ""), 320)
        self._assert_no_leakage(json.dumps(job, default=str), "revision-required job")
        self.assertLess(
            len(json.dumps(job, ensure_ascii=True, default=str)), 60_000,
            "job must stay bounded (no raw source)",
        )
        self._assert_scratch_publication_unchanged()
        self._assert_real_state_unchanged(sentinels)

        # --- Fresh revision rebuild through the REAL revision machinery -----
        provenance = result.get("adaptation_provenance") or {}
        # The blocked build result does not echo the dossier; the persisted
        # attempt dossier artifact is the Python-owned identity source.
        self.dossier = self._load_persisted_dossier(
            self.workspace, str(job["adaptation_attempt_id"])
        )
        failure_packet = self._build_failure_packet(
            result,
            provenance,
            self.dossier,
            source_path=str(provenance.get("source_path") or UPLOAD_SOURCE_REFERENCE),
        )
        validation = validate_adaptation_failure_packet(
            failure_packet, repo_root=REPO_ROOT
        )
        self.assertTrue(validation["valid"], validation.get("diagnostics"))
        self.assertEqual(len(self.auditor_calls), 0)
        revision_result = self._run_revision(
            failure_packet,
            workspace=self.workspace,
            module_slug=UPLOAD_MODULE_SLUG,
            semantic_seam=self._semantic_gate_fail_once,
        )

        # Exactly one bounded revision was consumed and passed.
        self.assertEqual(
            revision_result["status"],
            REVISION_STATUS_REVISION_PASSED,
            {
                "diagnostics": revision_result.get("diagnostics"),
                "auditor_decision": revision_result.get("auditor_decision"),
                "failure_classification": revision_result.get("failure_classification"),
            },
        )
        self.assertEqual(revision_result["revision_number"], 1)
        self.assertEqual(revision_result["max_revisions"], 1)
        self.assertTrue(revision_result["semantic_revision_budget_consumed"])
        self.assertEqual(len(self.auditor_calls), 1)
        self.assertEqual(self.auditor_calls[0]["revision_number"], 0)
        self.assertEqual(len(self.revision_build_calls), 1)
        self.assertEqual(
            self.revision_build_calls[0]["target"]["revision_number"], 1
        )
        self.assertEqual(
            self.revision_build_calls[0]["attempt_metadata"]["revision_number"], 1
        )
        self.assertEqual(
            self.revision_build_calls[0]["attempt_metadata"]["attempt_id"], attempt_id
        )
        # Fresh staging target is distinct, isolated, project-relative.
        self._assert_revision_artifacts_retained(
            revision_result, self.workspace, attempt_id
        )
        revised_module_dir = REPO_ROOT / revision_result["staging_target"]["path"]
        self.assertTrue((revised_module_dir / "module_context.json").is_file())
        # The revised build passed every real adaptation gate.
        revision_build = self.last_build_results[-1]
        revision_gates = revision_build.get("adaptation_gates") or {}
        self.assertEqual(revision_gates.get("playable_status"), "pass")
        self.assertEqual(len(self.semantic_gate_calls), 2)
        self.assertNotEqual(
            self.semantic_gate_calls[0], self.semantic_gate_calls[1]
        )
        self._assert_scratch_publication_unchanged()
        self._assert_real_state_unchanged(sentinels)

        # --- ONLY NOW the normal staged transaction publishes --------------
        revision_provenance = revision_build.get("adaptation_provenance") or {}
        self.assertEqual(
            str(revision_provenance.get("source_hash") or "").lower(),
            self.source_hash,
        )
        finishing, events = self._run_revision_finisher(
            revision_result,
            revision_build,
            provenance=revision_provenance or provenance,
            workspace=self.workspace,
            module_slug=UPLOAD_MODULE_SLUG,
        )
        self._assert_verified_finisher_success(finishing, events)
        self.assertEqual(len(self.finisher_calls), 1, "exactly-once completion")
        self.assertEqual(self.finisher_calls[0], UPLOAD_MODULE_SLUG)

        # Registry-last: the scratch mirror received module + areas, campaign
        # availability appended, sentinel entries preserved.
        persisted_registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted_registry["modules"]["Sentinel_Module"],
            self.original_registry["modules"]["Sentinel_Module"],
        )
        module_entry = persisted_registry["modules"][UPLOAD_MODULE_SLUG]
        self.assertIsInstance(module_entry, dict)
        self.assertEqual(module_entry.get("moduleName"), UPLOAD_MODULE_SLUG)
        self.assertTrue(
            any(
                isinstance(area, dict) and area.get("module") == UPLOAD_MODULE_SLUG
                for area in persisted_registry.get("areas", {}).values()
            )
        )
        campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        self.assertEqual(
            campaign["availableModules"], ["Sentinel_Module", UPLOAD_MODULE_SLUG]
        )

        # Report/Markdown/provenance identity on the revised module.
        summary_path = revised_module_dir / "MODULE_SUMMARY.md"
        self.assertTrue(summary_path.exists())
        summary = summary_path.read_text(encoding="utf-8")
        self.assertGreater(len(summary), 500)
        self.assertIn("Adapted for NEQ-TTRPG", summary)
        self._assert_no_leakage(summary, "MODULE_SUMMARY.md")
        context = json.loads(
            (revised_module_dir / "module_context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(context.get("adaptation_notice"), "Adapted for NEQ-TTRPG")
        context_prov = context.get("adaptation_provenance") or {}
        self.assertEqual(str(context_prov.get("source_hash") or "").lower(), self.source_hash)
        self.assertEqual(context_prov.get("rights_class"), "user_authored")
        report_path = revised_module_dir / "toolkit_build_report.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report.get("status"), "success")
        self.assertEqual(report.get("publication_order"), EXPECTED_PUBLICATION_ORDER)
        self.assertIs(report.get("registry_is_final_stateful_publication"), True)
        self._assert_no_leakage(json.dumps(report), "toolkit_build_report.json")

        # No legacy fallback anywhere: the prior failed attempt never became
        # publication and the final module lives only in the scratch staging.
        self.assertFalse((REPO_ROOT / "modules" / UPLOAD_MODULE_SLUG).exists())
        self._assert_real_state_unchanged(sentinels)


class TestUploadPathSemanticFailureExhaustion(
    _SemanticFailureRuntimeMixin, unittest.TestCase
):
    """Scenario B on the ACTUAL upload job path: a persistent semantic failure
    exhausts the bounded revision budget, maps to the terminal
    ``adaptation_revision_exhausted`` job status, and leaves no module,
    registry, or campaign publication side effect."""

    module_slug = UPLOAD_MODULE_SLUG
    module_title = UPLOAD_MODULE_TITLE
    job_id = "semantic-failure-upload-exhaust-job"

    def _make_workspace(self) -> Path:
        workspace = self.scratch / "workspace"
        ensure_workspace_placeholders(workspace)
        files = get_workspace_files(workspace)
        self.source_hash = hashlib.sha256(UPLOAD_SOURCE_PATH.read_bytes()).hexdigest()
        packet: Dict[str, Any] = {
            "packet_version": "v1",
            "normalization_state": "normalized",
            "source_hash": self.source_hash,
            "source_path": UPLOAD_SOURCE_REFERENCE,
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
        persist_normalized_packet_artifact(workspace, packet)
        snapshot = build_review_snapshot(
            job_id=self.job_id,
            decision=REVIEW_DECISION_APPROVE,
            packet=packet,
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
        )
        persist_review_snapshot_artifact(workspace, snapshot)
        files["source_original"].write_bytes(UPLOAD_SOURCE_PATH.read_bytes())
        for name in ("build_result", "readiness_validation_report", "readiness_audit_report"):
            files[name].write_text("{}", encoding="utf-8")
        return workspace

    def _register_job(self) -> None:
        with routes_module._jobs_lock:
            routes_module._jobs[self.job_id] = {
                "job_id": self.job_id,
                "job_type": "toolkit_homebrew_md_ingest",
                "status": "approved_for_build",
                "stage": "build",
                "pipeline_status": "building",
                "artifact_workspace": str(self.workspace),
                "source_kind": "markdown",
                "source_filename": "Jeremys Magic Shop.md",
                "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
                "review_decision": REVIEW_DECISION_APPROVE,
                "expected_module_name": UPLOAD_MODULE_SLUG,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        self.job_ids.append(self.job_id)

    def test_persistent_semantic_failure_exhausts_revision_without_side_effects(
        self,
    ) -> None:
        sentinels = self._snapshot_real_state()
        self._enable_adaptation()
        self.workspace = self._make_workspace()
        self._register_job()
        real_authoring = routes_module.run_upload_adaptation_authoring

        def _authoring_with_runner(handoff: Any, **kwargs: Any) -> Dict[str, Any]:
            return real_authoring(
                handoff,
                workspace=kwargs.get("workspace"),
                author_runner=self.author_runner,
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
            __import__(
                "utils.toolkit_adaptation_monster_guardrail",
                fromlist=["build_adaptation_monster_guardrail_report"],
            ),
            "build_adaptation_monster_guardrail_report",
            return_value={
                "version": "toolkit_adaptation_monster_guardrail.v1",
                "report_version": "toolkit_adaptation_monster_guardrail.v1",
                "status": "pass",
                "monsters_unresolved": 0,
                "encounters_unresolved": 0,
                 "encounters_unbound": 0,
                 "unresolved_refs": [],
             },
         ), patch.object(
             __import__(
                 "utils.monster_reference_closure",
                 fromlist=["ensure_monster_reference_closure"],
             ),
             "ensure_monster_reference_closure",
             side_effect=self._monster_closure_success,
         ), patch.object(
             gate_composer,
             "collect_referenced_monsters",
             return_value=[],
         ), patch.object(
             gate_composer,
             "collect_existing_monster_slugs",
             return_value=[],
         ), patch.object(
             gate_composer,
             "_run_semantic_authority_gate",
             side_effect=self._semantic_gate_always_fail,
        ):
            routes_module._run_homebrew_build_job(self.job_id)
        job = self._snapshot_job(self.job_id)

        # First failure is the bounded revision-required outcome.
        self.assertEqual(job.get("status"), "adaptation_revision_required")
        self.assertEqual(job.get("adaptation_outcome"), "semantic_revision")
        self.assertIsNotNone(job.get("adaptation_attempt_id"))
        attempt_id = str(job["adaptation_attempt_id"])
        result = job.get("result") or {}
        provenance = result.get("adaptation_provenance") or {}
        self.dossier = self._load_persisted_dossier(self.workspace, attempt_id)
        failure_packet = self._build_failure_packet(
            result,
            provenance,
            self.dossier,
            source_path=str(provenance.get("source_path") or UPLOAD_SOURCE_REFERENCE),
        )
        validation = validate_adaptation_failure_packet(
            failure_packet, repo_root=REPO_ROOT
        )
        self.assertTrue(validation["valid"], validation.get("diagnostics"))

        # The persistent semantic failure exhausts the bounded budget.
        revision_result = self._run_revision(
            failure_packet,
            workspace=self.workspace,
            module_slug=UPLOAD_MODULE_SLUG,
            semantic_seam=self._semantic_gate_always_fail,
        )
        self.assertEqual(revision_result["status"], REVISION_STATUS_FAILED)
        self.assertEqual(revision_result["outcome"], REVISION_STATUS_FAILED)
        self.assertEqual(
            revision_result["diagnostics"][0]["code"],
            "revision_budget_exhausted",
            revision_result.get("failure_classification"),
        )
        self.assertEqual(revision_result["revision_number"], 1)
        self.assertEqual(len(self.auditor_calls), 1)
        self.assertEqual(len(self.revision_build_calls), 1)
        self.assertFalse(revision_result["published"])
        self.assertFalse(revision_result["registry_mutated"])
        self.assertFalse(revision_result["publication_started"])
        self._assert_build_result_projection(
            self.workspace,
            attempt_id,
            1,
            next_revision_eligible=False,
            remaining_revisions=0,
        )
        self.assertEqual(
            revision_result["staging_target"]["completion_state"], "failed"
        )
        self.assertEqual(len(self.semantic_gate_calls), 2)
        self.assertNotEqual(
            self.semantic_gate_calls[0], self.semantic_gate_calls[1]
        )
        self._assert_no_leakage(json.dumps(revision_result, default=str), "revision result")

        # The REAL job-reporting contract maps the exhausted signal to the
        # terminal adaptation_revision_exhausted status; never completed.
        with routes_module._jobs_lock:
            routes_module._jobs[self.job_id]["revision_result"] = dict(revision_result)
            routes_module._jobs[self.job_id]["result"] = dict(revision_result)
            routes_module._refresh_adaptation_job_state(routes_module._jobs[self.job_id])
        exhausted_job = self._snapshot_job(self.job_id)
        self.assertEqual(
            exhausted_job.get("status"), "adaptation_revision_exhausted"
        )
        self.assertEqual(exhausted_job.get("adaptation_outcome"), "revision_exhausted")
        self.assertIs(exhausted_job.get("adaptation_terminal"), True)
        self.assertEqual(
            exhausted_job.get("adaptation_failure_surface"), "semantic_revision"
        )
        retry = exhausted_job.get("adaptation_retry_diagnostics") or {}
        self.assertEqual(retry.get("status"), "exhausted")
        self.assertEqual(retry.get("remaining_revisions"), 0)
        self.assertNotEqual(exhausted_job.get("status"), "adaptation_completed")
        self.assertLess(len(exhausted_job.get("adaptation_status_text") or ""), 320)

        # No module_complete, no adaptation_completed, no registry/campaign
        # mutation, no false success, bounded diagnostics, no leakage.
        self.assertEqual(self.finisher_calls, [])
        self._assert_scratch_publication_unchanged()
        self.assertFalse((REPO_ROOT / "modules" / UPLOAD_MODULE_SLUG).exists())
        self._assert_no_leakage(json.dumps(exhausted_job, default=str), "exhausted job")
        self.assertLess(len(json.dumps(exhausted_job, ensure_ascii=True, default=str)), 60_000)
        self._assert_real_state_unchanged(sentinels)


class TestTextPathSemanticFailureRevisionRecovery(
    _SemanticFailureRuntimeMixin, unittest.TestCase
):
    """Scenario A on the ACTUAL text-description Socket.IO worker: the first
    semantic failure emits a blocked adaptation outcome (never module_complete);
    a fresh revision rebuild through the REAL revision machinery and REAL
    shared finisher publishes exactly once with registry-last ordering."""

    module_slug = TEXT_MODULE_NAME
    module_title = TEXT_MODULE_TITLE
    job_id = "semantic-failure-text-job"

    def _params(self, **overrides: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "module_name": TEXT_MODULE_NAME,
            "narrative": TEXT_FIXTURE,
            "num_areas": 5,
            "locations_per_area": 3,
        }
        base.update(overrides)
        return base

    def _real_seam(self, module_name: str, narrative: str, params: Any) -> Any:
        """Host seam wrapper: REAL worker seam with the injected author runner."""
        return worker.run_text_description_adaptation_seam(
            module_name,
            narrative,
            params,
            author_runner=self.author_runner,
            model="provider-free-semantic-failure-author",
        )

    def _real_publication(self, seam_result: Any, **kwargs: Any) -> Any:
        """Host publication wrapper: REAL shared transaction with the REAL
        packet builder and REAL adaptation finisher (recording the raw build
        result for the failure packet)."""
        return worker.run_text_description_adaptation_publication(
            seam_result,
            build_runner=self._recording_build_runner,
            finisher_runner=finisher.run_toolkit_module_postbuild_finishing,
            **kwargs,
        )

    def _recording_build_runner(
        self, workspace: Any, job_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        result = packet_builder.run_toolkit_homebrew_packet_build(
            workspace, job_id, **kwargs
        )
        self.last_build_results.append(deepcopy(result))
        return result

    def _run_worker(
        self,
        semantic_seam: Callable[[str, Any], Dict[str, Any]],
        *,
        job_id: str,
    ) -> None:
        """Run the ACTUAL Socket.IO worker on the enabled adaptation path."""
        real_workspace_builder = worker.build_text_description_attempt_workspace
        real_staging_creator = worker.create_adaptation_staging_target

        def _build_ws_into_scratch(module_name: str, concept: Any, **kw: Any) -> Dict[str, Any]:
            return real_workspace_builder(
                module_name,
                concept,
                workspace_root=self.workspaces_root,
                staging_root=self.staging_root,
                **kw,
            )

        def _create_staging_into_scratch(source_hash: str, **kw: Any) -> Dict[str, Any]:
            kw.pop("staging_root", None)
            return real_staging_creator(
                source_hash,
                staging_root=self.staging_root,
                **kw,
            )

        real_registry_stage = finisher._run_registry_stage

        def _registry_into_scratch(
            module_slug: str, *, module_dir: Any = None, adaptation: bool = False
        ) -> Dict[str, Any]:
            return self._registry_stage_into_scratch(
                module_slug,
                module_dir=module_dir,
                adaptation=adaptation,
                real_registry_stage=real_registry_stage,
            )

        sys.modules["core.generators.module_builder"] = _fake_builder_module(
            _GuardedModuleBuilder
        )
        self.addCleanup(
            lambda: sys.modules.pop("core.generators.module_builder", None)
        )
        with patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", True), patch.object(
            packet_builder, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=_build_ws_into_scratch,
        ), patch.object(
            worker,
            "create_adaptation_staging_target",
            side_effect=_create_staging_into_scratch,
        ), patch.object(
            web_interface, "socketio", self.recorder
        ), patch.object(
            web_interface, "TEXT_DESCRIPTION_ADAPTATION_AVAILABLE", True
        ), patch.object(
            web_interface,
            "run_text_description_adaptation_seam",
            side_effect=self._real_seam,
        ), patch.object(
            web_interface,
            "run_text_description_adaptation_publication",
            side_effect=self._real_publication,
        ), patch.object(
            packet_builder, "_execute_module_builder", side_effect=self._builder_executor
        ), patch.object(
            __import__(
                "utils.toolkit_adaptation_monster_guardrail",
                fromlist=["build_adaptation_monster_guardrail_report"],
            ),
            "build_adaptation_monster_guardrail_report",
            return_value={
                "version": "toolkit_adaptation_monster_guardrail.v1",
                "report_version": "toolkit_adaptation_monster_guardrail.v1",
                "status": "pass",
                "monsters_unresolved": 0,
                "encounters_unresolved": 0,
                 "encounters_unbound": 0,
                 "unresolved_refs": [],
             },
         ), patch.object(
             __import__(
                 "utils.monster_reference_closure",
                 fromlist=["ensure_monster_reference_closure"],
             ),
             "ensure_monster_reference_closure",
             side_effect=self._monster_closure_success,
         ), patch.object(
             gate_composer,
             "collect_referenced_monsters",
             return_value=[],
         ), patch.object(
             gate_composer,
             "collect_existing_monster_slugs",
             return_value=[],
         ), patch.object(
             finisher, "_run_registry_stage", side_effect=_registry_into_scratch
        ), patch.object(adventure_writer, "_llm_intro_narrative", return_value=None), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(
            adventure_writer, "_llm_area_overview", return_value=None
        ), patch.object(
            gate_composer,
            "_run_semantic_authority_gate",
            side_effect=semantic_seam,
        ):
            web_interface.simulate_build_process(
                self._params(job_id=job_id)
            )

    def _events(self, name: str) -> List[Dict[str, Any]]:
        return [payload for event, payload in self.recorder.events if event == name]

    def test_worker_semantic_failure_then_fresh_revision_publishes(self) -> None:
        sentinels = self._snapshot_real_state()
        self._enable_adaptation()

        # --- First worker run: bounded blocked adaptation outcome -----------
        self._run_worker(self._semantic_gate_fail_once, job_id=self.job_id)
        self.assertEqual(self._events("module_complete"), [])
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(payload["adaptation_route"], "llm_adaptation")
        self.assertIs(payload["adaptation_job"], True)
        self.assertEqual(payload["adaptation_outcome"], "blocked")
        self.assertIs(payload["generation_succeeded"], False)
        self.assertTrue(payload["adaptation_reason_code"])
        self.assertIsNone(
            _GuardedModuleBuilder.last_instance,
            "legacy ModuleBuilder must never be constructed on the enabled path",
        )
        self.assertEqual(len(self.author_runner.calls), 1)
        self.assertEqual(len(self.semantic_gate_calls), 1)
        self.assertEqual(self.finisher_calls, [])
        self._assert_scratch_publication_unchanged()
        self._assert_no_leakage(json.dumps(payload), "module_error payload")
        self._assert_real_state_unchanged(sentinels)

        # The blocked build result is the REAL gate-blocked packet result.
        self.assertEqual(len(self.last_build_results), 1)
        blocked_build = self.last_build_results[0]
        self.assertEqual(blocked_build.get("status"), "blocked")
        self.assertEqual(blocked_build.get("stage"), "adaptation_gates")
        gates = blocked_build.get("adaptation_gates") or {}
        self.assertEqual(gates.get("playable_status"), "blocked")
        self.assertEqual(
            (gates.get("gates") or {}).get("semantic_authority", {}).get("status"),
            "blocked",
        )
        provenance = blocked_build.get("adaptation_provenance") or {}
        attempt = provenance.get("attempt_metadata")
        attempt = attempt if isinstance(attempt, Mapping) else {}
        attempt_id = str(
            attempt.get("attempt_id") or provenance.get("attempt_id") or ""
        )
        self.assertTrue(attempt_id)
        # The seam workspace is the shared project-relative attempt workspace.
        workspace_path = str(
            (self._events("module_error")[0].get("adaptation_workspace_path") or "")
            or (self.last_build_results[0].get("adaptation_artifact_workspace") or "")
        )
        self.assertTrue(workspace_path)
        workspace = REPO_ROOT.joinpath(*Path(workspace_path).parts)
        self.assertTrue(workspace.is_dir())
        self.assertTrue(str(workspace).startswith(str(REPO_ROOT / "tmp")))
        self._assert_build_result_projection(
            workspace,
            attempt_id,
            0,
            next_revision_eligible=True,
            remaining_revisions=1,
        )

        # --- Fresh revision rebuild through the REAL revision machinery -----
        self.workspace = workspace
        self.dossier = self._load_persisted_dossier(workspace, attempt_id)
        failure_packet = self._build_failure_packet(
            blocked_build,
            provenance,
            self.dossier,
            source_path=str(provenance.get("source_path") or ""),
        )
        validation = validate_adaptation_failure_packet(
            failure_packet, repo_root=REPO_ROOT
        )
        self.assertTrue(validation["valid"], validation.get("diagnostics"))
        revision_result = self._run_revision(
            failure_packet,
            workspace=workspace,
            module_slug=TEXT_MODULE_NAME,
            semantic_seam=self._semantic_gate_fail_once,
        )
        self.assertEqual(revision_result["status"], REVISION_STATUS_REVISION_PASSED)
        self.assertEqual(revision_result["revision_number"], 1)
        self.assertEqual(len(self.auditor_calls), 1)
        self.assertEqual(len(self.revision_build_calls), 1)
        self.assertEqual(
            self.revision_build_calls[0]["attempt_metadata"]["attempt_id"], attempt_id
        )
        self.assertEqual(
            self.revision_build_calls[0]["attempt_metadata"]["revision_number"], 1
        )
        self._assert_revision_artifacts_retained(revision_result, workspace, attempt_id)
        revision_build = self.last_build_results[-1]
        revision_gates = revision_build.get("adaptation_gates") or {}
        self.assertEqual(revision_gates.get("playable_status"), "pass")
        self.assertEqual(len(self.semantic_gate_calls), 2)
        self.assertNotEqual(
            self.semantic_gate_calls[0], self.semantic_gate_calls[1]
        )
        self._assert_scratch_publication_unchanged()
        self._assert_real_state_unchanged(sentinels)

        # --- ONLY NOW the normal staged transaction publishes --------------
        revision_provenance = revision_build.get("adaptation_provenance") or {}
        self.assertEqual(
            str(revision_provenance.get("source_hash") or "").lower(),
            TEXT_FIXTURE_HASH,
        )
        finishing, events = self._run_revision_finisher(
            revision_result,
            revision_build,
            provenance=revision_provenance or provenance,
            workspace=workspace,
            module_slug=TEXT_MODULE_NAME,
        )
        self._assert_verified_finisher_success(finishing, events)
        self.assertEqual(len(self.finisher_calls), 1, "exactly-once completion")
        self.assertEqual(self.finisher_calls[0], TEXT_MODULE_NAME)
        self.assertEqual(self._events("module_complete"), [], "no worker-level false success")

        persisted_registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted_registry["modules"]["Sentinel_Module"],
            self.original_registry["modules"]["Sentinel_Module"],
        )
        self.assertEqual(
            persisted_registry["modules"][TEXT_MODULE_NAME]["moduleName"],
            TEXT_MODULE_NAME,
        )
        campaign = json.loads(self.campaign_path.read_text(encoding="utf-8"))
        self.assertEqual(
            campaign["availableModules"], ["Sentinel_Module", TEXT_MODULE_NAME]
        )
        revised_module_dir = REPO_ROOT / revision_result["staging_target"]["path"]
        summary_path = revised_module_dir / "MODULE_SUMMARY.md"
        self.assertTrue(summary_path.exists())
        summary = summary_path.read_text(encoding="utf-8")
        self.assertGreater(len(summary), 500)
        self.assertIn("Adapted for NEQ-TTRPG", summary)
        self._assert_no_leakage(summary, "MODULE_SUMMARY.md")
        context = json.loads(
            (revised_module_dir / "module_context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(context.get("adaptation_notice"), "Adapted for NEQ-TTRPG")
        context_prov = context.get("adaptation_provenance") or {}
        self.assertEqual(
            str(context_prov.get("source_hash") or "").lower(), TEXT_FIXTURE_HASH
        )
        self.assertEqual(context_prov.get("rights_class"), "user_authored")
        report_path = revised_module_dir / "toolkit_build_report.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report.get("publication_order"), EXPECTED_PUBLICATION_ORDER)
        self.assertIs(report.get("registry_is_final_stateful_publication"), True)
        self._assert_no_leakage(json.dumps(report), "toolkit_build_report.json")
        self.assertFalse((REPO_ROOT / "modules" / TEXT_MODULE_NAME).exists())
        self._assert_real_state_unchanged(sentinels)


class TestTextPathSemanticFailureExhaustion(
    _SemanticFailureRuntimeMixin, unittest.TestCase
):
    """Scenario B on the ACTUAL text-description Socket.IO worker: a persistent
    semantic failure emits a blocked adaptation outcome and the real revision
    machinery exhausts the bounded budget with zero publication side effect."""

    module_slug = TEXT_MODULE_NAME
    module_title = TEXT_MODULE_TITLE
    job_id = "semantic-failure-text-exhaust-job"

    def _params(self, **overrides: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "module_name": TEXT_MODULE_NAME,
            "narrative": TEXT_FIXTURE,
            "num_areas": 5,
            "locations_per_area": 3,
        }
        base.update(overrides)
        return base

    def _real_seam(self, module_name: str, narrative: str, params: Any) -> Any:
        return worker.run_text_description_adaptation_seam(
            module_name,
            narrative,
            params,
            author_runner=self.author_runner,
            model="provider-free-semantic-failure-author",
        )

    def _real_publication(self, seam_result: Any, **kwargs: Any) -> Any:
        return worker.run_text_description_adaptation_publication(
            seam_result,
            build_runner=self._recording_build_runner,
            finisher_runner=finisher.run_toolkit_module_postbuild_finishing,
            **kwargs,
        )

    def _recording_build_runner(
        self, workspace: Any, job_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        result = packet_builder.run_toolkit_homebrew_packet_build(
            workspace, job_id, **kwargs
        )
        self.last_build_results.append(deepcopy(result))
        return result

    def _events(self, name: str) -> List[Dict[str, Any]]:
        return [payload for event, payload in self.recorder.events if event == name]

    def test_worker_persistent_semantic_failure_exhausts_revision(self) -> None:
        sentinels = self._snapshot_real_state()
        self._enable_adaptation()
        real_workspace_builder = worker.build_text_description_attempt_workspace
        real_staging_creator = worker.create_adaptation_staging_target

        def _build_ws_into_scratch(module_name: str, concept: Any, **kw: Any) -> Dict[str, Any]:
            return real_workspace_builder(
                module_name,
                concept,
                workspace_root=self.workspaces_root,
                staging_root=self.staging_root,
                **kw,
            )

        def _create_staging_into_scratch(source_hash: str, **kw: Any) -> Dict[str, Any]:
            kw.pop("staging_root", None)
            return real_staging_creator(
                source_hash,
                staging_root=self.staging_root,
                **kw,
            )

        real_registry_stage = finisher._run_registry_stage

        def _registry_into_scratch(
            module_slug: str, *, module_dir: Any = None, adaptation: bool = False
        ) -> Dict[str, Any]:
            return self._registry_stage_into_scratch(
                module_slug,
                module_dir=module_dir,
                adaptation=adaptation,
                real_registry_stage=real_registry_stage,
            )

        sys.modules["core.generators.module_builder"] = _fake_builder_module(
            _GuardedModuleBuilder
        )
        self.addCleanup(
            lambda: sys.modules.pop("core.generators.module_builder", None)
        )
        with patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", True), patch.object(
            packet_builder, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=_build_ws_into_scratch,
        ), patch.object(
            worker,
            "create_adaptation_staging_target",
            side_effect=_create_staging_into_scratch,
        ), patch.object(
            web_interface, "socketio", self.recorder
        ), patch.object(
            web_interface, "TEXT_DESCRIPTION_ADAPTATION_AVAILABLE", True
        ), patch.object(
            web_interface,
            "run_text_description_adaptation_seam",
            side_effect=self._real_seam,
        ), patch.object(
            web_interface,
            "run_text_description_adaptation_publication",
            side_effect=self._real_publication,
        ), patch.object(
            packet_builder, "_execute_module_builder", side_effect=self._builder_executor
        ), patch.object(
            __import__(
                "utils.toolkit_adaptation_monster_guardrail",
                fromlist=["build_adaptation_monster_guardrail_report"],
            ),
            "build_adaptation_monster_guardrail_report",
            return_value={
                "version": "toolkit_adaptation_monster_guardrail.v1",
                "report_version": "toolkit_adaptation_monster_guardrail.v1",
                "status": "pass",
                "monsters_unresolved": 0,
                "encounters_unresolved": 0,
                 "encounters_unbound": 0,
                 "unresolved_refs": [],
             },
         ), patch.object(
             __import__(
                 "utils.monster_reference_closure",
                 fromlist=["ensure_monster_reference_closure"],
             ),
             "ensure_monster_reference_closure",
             side_effect=self._monster_closure_success,
         ), patch.object(
             gate_composer,
             "collect_referenced_monsters",
             return_value=[],
         ), patch.object(
             gate_composer,
             "collect_existing_monster_slugs",
             return_value=[],
         ), patch.object(
             finisher, "_run_registry_stage", side_effect=_registry_into_scratch
        ), patch.object(adventure_writer, "_llm_intro_narrative", return_value=None), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(
            adventure_writer, "_llm_area_overview", return_value=None
        ), patch.object(
            gate_composer,
            "_run_semantic_authority_gate",
            side_effect=self._semantic_gate_always_fail,
        ):
            web_interface.simulate_build_process(self._params())

        # Bounded blocked outcome: one module_error, never module_complete.
        self.assertEqual(self._events("module_complete"), [])
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(payload["adaptation_outcome"], "blocked")
        self.assertIs(payload["generation_succeeded"], False)
        self.assertIsNone(
            _GuardedModuleBuilder.last_instance,
            "legacy ModuleBuilder must never be constructed on the enabled path",
        )
        self.assertEqual(len(self.author_runner.calls), 1)
        self.assertEqual(len(self.semantic_gate_calls), 1)
        self.assertEqual(self.finisher_calls, [])
        self._assert_no_leakage(json.dumps(payload), "module_error payload")
        self._assert_scratch_publication_unchanged()
        self._assert_real_state_unchanged(sentinels)

        # The real revision machinery exhausts the bounded budget.
        blocked_build = self.last_build_results[0]
        provenance = blocked_build.get("adaptation_provenance") or {}
        attempt = provenance.get("attempt_metadata")
        attempt = attempt if isinstance(attempt, Mapping) else {}
        attempt_id = str(
            attempt.get("attempt_id") or provenance.get("attempt_id") or ""
        )
        self.assertTrue(attempt_id)
        workspace_path = str(
            payload.get("adaptation_workspace_path")
            or blocked_build.get("adaptation_artifact_workspace")
            or ""
        )
        workspace = REPO_ROOT.joinpath(*Path(workspace_path).parts)
        self.workspace = workspace
        self.dossier = self._load_persisted_dossier(workspace, attempt_id)
        failure_packet = self._build_failure_packet(
            blocked_build,
            provenance,
            self.dossier,
            source_path=str(provenance.get("source_path") or ""),
        )
        validation = validate_adaptation_failure_packet(
            failure_packet, repo_root=REPO_ROOT
        )
        self.assertTrue(validation["valid"], validation.get("diagnostics"))
        revision_result = self._run_revision(
            failure_packet,
            workspace=workspace,
            module_slug=TEXT_MODULE_NAME,
            semantic_seam=self._semantic_gate_always_fail,
        )
        self.assertEqual(revision_result["status"], REVISION_STATUS_FAILED)
        self.assertEqual(revision_result["outcome"], REVISION_STATUS_FAILED)
        self.assertEqual(
            revision_result["diagnostics"][0]["code"], "revision_budget_exhausted"
        )
        self.assertEqual(revision_result["revision_number"], 1)
        self.assertEqual(len(self.auditor_calls), 1)
        self.assertEqual(len(self.revision_build_calls), 1)
        self.assertFalse(revision_result["published"])
        self.assertFalse(revision_result["registry_mutated"])
        self.assertFalse(revision_result["publication_started"])
        self._assert_build_result_projection(
            workspace,
            attempt_id,
            1,
            next_revision_eligible=False,
            remaining_revisions=0,
        )
        self.assertEqual(
            revision_result["staging_target"]["completion_state"], "failed"
        )
        self.assertEqual(len(self.semantic_gate_calls), 2)
        self._assert_no_leakage(json.dumps(revision_result, default=str), "revision result")

        # The real job-reporting contract maps the exhausted signal to the
        # terminal adaptation_revision_exhausted status (same contract the
        # upload route uses), never adaptation_completed.
        job_payload = {
            "adaptation_job": True,
            "adaptation_mode": "llm_adaptation",
            "status": "failed",
            "revision_result": dict(revision_result),
            "result": dict(revision_result),
        }
        summary = __import__(
            "web.extensions.toolkit_adaptation_job_reporting",
            fromlist=["build_adaptation_job_status"],
        ).build_adaptation_job_status(job_payload)
        self.assertEqual(summary["job_status"], "adaptation_revision_exhausted")
        self.assertEqual(summary["outcome"], "revision_exhausted")
        self.assertIs(summary["terminal"], True)
        self.assertEqual(summary["failure_surface"], "semantic_revision")
        self.assertEqual(summary["retry_diagnostics"]["status"], "exhausted")
        self.assertEqual(summary["retry_diagnostics"]["remaining_revisions"], 0)
        self.assertNotEqual(summary["job_status"], "adaptation_completed")
        self.assertIs(summary["raw_provider_payload_exposed"], False)

        self.assertEqual(self.finisher_calls, [])
        self._assert_scratch_publication_unchanged()
        self.assertFalse((REPO_ROOT / "modules" / TEXT_MODULE_NAME).exists())
        self._assert_real_state_unchanged(sentinels)


class TestSemanticFailureRuntimeHygiene(unittest.TestCase):
    """Provider-free, path-policy, and contract hygiene for this suite."""

    def test_this_suite_is_ascii_only_with_spdx_header(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText: 2024 MoonlightByte", source)
        non_ascii = [ch for ch in source if ord(ch) > 127]
        self.assertEqual(non_ascii, [])

    def test_no_os_temp_or_absolute_scratch_paths(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        scan = source.split("class TestSemanticFailureRuntimeHygiene", 1)[0]
        import_lines = [
            line.strip()
            for line in scan.splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        imports = "\n".join(import_lines)
        self.assertNotIn("import tempfile", imports)
        self.assertNotIn("from tempfile", imports)
        self.assertNotIn("/tmp", scan)
        self.assertNotIn("/var/folders", scan)
        self.assertIn('"tmp"', scan)
        self.assertIn("toolkit_adaptation_semantic_failure_runtime", scan)
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))

    def test_this_suite_never_imports_provider_or_socket_modules(self) -> None:
        import_lines = [
            line.strip()
            for line in Path(__file__).read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        imports = "\n".join(import_lines)
        for token in (
            "import openai",
            "from openai",
            "import socketio",
            "from socketio",
            "import requests",
            "import urllib3",
            "import httpx",
            "import tempfile",
            "import aiohttp",
            "import websockets",
        ):
            self.assertNotIn(token, imports)

    def test_flag_is_patched_not_reliant_on_live_value(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn('patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", True)', source)
        self.assertIn('patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", True)', source)

    def test_both_real_entry_paths_and_real_revision_machinery_invoked(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("routes_module._run_homebrew_build_job(self.job_id)", source)
        self.assertIn("web_interface.simulate_build_process(", source)
        self.assertIn("run_adaptation_final_revision(", source)
        self.assertIn("packet_builder.run_toolkit_homebrew_packet_build(", source)
        self.assertIn("finisher.run_toolkit_module_postbuild_finishing(", source)
        self.assertIn("finisher._run_registry_stage", source)
        self.assertIn("gate_composer._run_semantic_authority_gate", source)
        self.assertIn("validate_adaptation_failure_packet(", source)
        self.assertIn("build_adaptation_failure_packet(", source)
        self.assertIn("_GuardedModuleBuilder", source)

    def test_protected_real_state_checked_in_every_behavioral_class(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("self._assert_real_state_unchanged(sentinels)", source)
        self.assertIn("_snapshot_real_state", source)
        self.assertIn("_assert_scratch_publication_unchanged", source)

    def test_workspaces_and_staging_are_project_relative_never_under_modules(
        self,
    ) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("self.assertNotIn(\"modules/\", target_path)", source)
        self.assertIn("assertFalse(Path(target_path).is_absolute())", source)
        self.assertIn("staging_root", source)
        self.assertIn("workspaces_root", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
