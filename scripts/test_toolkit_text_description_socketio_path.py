# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Task 7.2 actual text-description Socket.IO build-path smoke for adaptation.

This suite submits a representative bounded text concept through the ACTUAL
Toolkit Socket.IO build worker (``web.web_interface.simulate_build_process``,
the thread target of ``@socketio.on('start_build')``) with a deterministic
injected author provider, and verifies the enabled path produces the SAME
staged publication/report contract as the upload path (task 7.1):

  * the real worker resolves the Python-owned ``text_description`` adaptation
    route when the operator flag is exactly True, builds the bounded
    project-relative attempt workspace, and invokes the REAL shared seam
    (``run_text_description_adaptation_seam``) and REAL shared publication
    transaction (``run_text_description_adaptation_publication``) with an
    injected deterministic author runner and the REAL packet builder
    (``run_toolkit_homebrew_packet_build`` with an injected deterministic
    module executor) plus the REAL adaptation finisher
    (``run_toolkit_module_postbuild_finishing`` with the REAL registry
    transaction redirected into a scratch-scoped chdir);
  * authoring runs exactly once BEFORE any ModuleBuilder/module write, the
    legacy direct builder is never constructed, and the staged module is
    written only to the reserved project-relative staging target under
    scratch;
  * the same ordered transaction as upload runs: staged packet build and
    shared schema/mechanical/readiness/semantic/report gates, Markdown
    generation with quality validation, registry integration as the final
    stateful publication with post-write verification, campaign sync with
    explicit no-active-campaign handling, and a completed outcome ONLY after
    the finisher verifies publication;
  * the persisted/report contract matches upload expectations: adaptation
    route/mode, source kind/hash identity, Python-owned user_authored rights,
    attempt/job identity, world-context provenance with
    ``seed_data_unavailable``/read-only, dossier/proposal/workspace/staging
    references, ``MODULE_SUMMARY.md`` with the ``Adapted for NEQ-TTRPG``
    notice, ``toolkit_build_report.json`` with the upload publication order
    and ``registry_is_final_stateful_publication``, registry module/area
    verification, bounded terminal/progress payloads;
  * no false completion (an author-policy refusal through the same actual
    path emits a blocked adaptation outcome and never success), no raw
    source/provider/credential leakage, and no real repository module/
    registry/campaign mutation;
  * the legacy text-description Socket.IO path is preserved when adaptation
    is disabled (flag False -> the real worker falls through to the legacy
    direct builder with its exact legacy completion payload).

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_text_description_socketio_path/<uuid>/`` and are removed via
addCleanup. The attempt workspace and reserved staging targets stay inside
the per-test scratch (real builders are redirected through the documented
workspace_root/staging_root kwargs), the registry/campaign files under the
scratch ``modules/`` mirror are the only runtime files touched, and real
module/registry/campaign sentinels are byte-checked. The live operator
``model_config.ENABLE_LLM_ADAPTATION`` value is never relied on; every
behavioral test patches it explicitly. Network/SDK/socket tripwires fail
loudly if anything attempts a live call.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import re
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
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
import web.extensions.toolkit_module_finisher as finisher
import web.extensions.toolkit_text_adaptation_worker as worker
import web.web_interface as web_interface
from utils.toolkit_adaptation_config import BUILD_MODE_LLM_ADAPTATION
from utils.toolkit_adaptation_publication_convergence import (
    CONVERGENCE_CONTRACT_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_text_description_socketio_path"
WEB_INTERFACE_PATH = REPO_ROOT / "web" / "web_interface.py"
REGISTRY_PATH = REPO_ROOT / "modules" / "world_registry.json"
CAMPAIGN_PATH = REPO_ROOT / "modules" / "campaign.json"
MODULES_DIR = REPO_ROOT / "modules"
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
# Known publication-ready module used only as a provider-free builder
# materialization fixture. The staged module is renamed and receives the text
# adaptation provenance before the real adaptation gates run. Thornwood is
# selected because its authored NPC/location authority is coherent with the
# semantic publication gate; the dossier encounter identities are added below
# inside the staging tree.
BUILDER_FIXTURE = REPO_ROOT / "modules" / "The_Thornwood_Watch"
MODULE_NAME = "Sunken_Lighthouse"
MODULE_TITLE = "Sunken Lighthouse"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
    "The bell chamber hides a corroded bronze key.\n"
    "A spectral keeper guards the light; the party must decide.\n"
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
_CREDENTIAL_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{8,}")

# Capture the REAL builders before any test patches redirect them.
_REAL_WORKSPACE_BUILDER = worker.build_text_description_attempt_workspace
_REAL_STAGING_CREATOR = worker.create_adaptation_staging_target


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
    attempt metadata produced by the text authoring preflight."""
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
    the test can prove Python-owned rights, source identity, and bounded
    source context reached the provider boundary without raw source leakage.
    """

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        refused: bool = False,
    ) -> None:
        self.calls: List[Tuple[Any, Optional[Dict[str, Any]], Dict[str, Any]]] = []
        self.dossier_builder = dossier_builder
        self.refused = refused

    def __call__(
        self,
        source_context: Any,
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append(
            (deepcopy(source_context), deepcopy(dict(attempt_metadata or {})), dict(kwargs))
        )
        if self.refused:
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": "refusal",
                "safe_class": "author_policy_refusal",
                "reason_code": "dossier_refused",
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
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {
                "model": "provider-free-text-author",
                "request_id": "req-text-7-2",
            },
            "params_used": {"reasoning_effort": "medium"},
        }


class _EmitRecorder:
    """Records socketio.emit calls in order."""

    def __init__(self) -> None:
        self.events: List[Tuple[str, Any]] = []

    def emit(self, event: str, payload: Any) -> None:
        self.events.append((str(event), deepcopy(payload)))


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


class _LegacyModuleBuilder:
    """Deterministic ModuleBuilder fake recording the direct invocation."""

    last_instance: Optional["_LegacyModuleBuilder"] = None

    def __init__(self, config: Any) -> None:
        _LegacyModuleBuilder.last_instance = self
        self.config = config
        self.progress_callback = None
        self.per_area_locations = None
        self.build_calls: List[str] = []

    def build_module(self, narrative: Any) -> None:
        self.build_calls.append(str(narrative))
        if self.progress_callback is not None:
            try:
                self.progress_callback("saving", "Saving generated module files...")
            except Exception:
                pass


def _fake_builder_module(builder_class: type) -> types.ModuleType:
    fake = types.ModuleType("core.generators.module_builder")
    fake.ModuleBuilder = builder_class
    fake.BuilderConfig = _FakeBuilderConfig
    return fake


class _FakeReadinessGate:
    """Deterministic readiness gate for the legacy path only."""

    def __init__(self) -> None:
        self.result = {
            "status": "pass",
            "module_name": MODULE_NAME,
            "ready_for_finishing": True,
        }

    def __call__(self, module_name: str, state_callback: Any = None) -> Dict[str, Any]:
        if state_callback is not None:
            state_callback("validating", {"audit": {"ok": True, "module": module_name}})
        return dict(self.result)


class _FakeFinisher:
    """Deterministic post-build finisher for the legacy path only."""

    def __init__(self) -> None:
        self.result = {
            "status": "success",
            "module_slug": MODULE_NAME,
            "publishable_status": "pass",
            "stages": {},
        }

    def __call__(self, module_name: str, strict: bool = True) -> Dict[str, Any]:
        return dict(self.result)


def _params(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "module_name": MODULE_NAME,
        "narrative": FIXTURE_TEXT,
        "num_areas": 5,
        "locations_per_area": 3,
    }
    base.update(overrides)
    return base


class _TextSocketIoScratchMixin:
    """Provide a unique project-local scratch root and real sentinels."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.workspaces_root = (
            "tmp/toolkit_text_description_socketio_path"
            + "/"
            + self.scratch.name
            + "/workspaces"
        )
        self.staging_root = (
            "tmp/toolkit_text_description_socketio_path"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.registry_path = self.scratch / "modules" / "world_registry.json"
        self.campaign_path = self.scratch / "modules" / "campaign.json"
        self.original_registry: Dict[str, Any] = {
            "worldName": "Text SocketIO Path Fixture World",
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

        self.recorder = _EmitRecorder()
        self.author_runner = FakeAuthorRunner(dossier_builder=_dossier_for_attempt)
        self.convergence_calls: List[Dict[str, Any]] = []
        self.convergence_results: List[Dict[str, Any]] = []
        self.provider_attempted = False
        self.production_convergence_callback = worker.adaptation_convergence_callback
        self.workspace_calls: List[str] = []
        self.staging_calls: List[Dict[str, Any]] = []
        self.registry_stage_calls: List[Dict[str, Any]] = []

        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", False
        )
        self._flag_patch.start()
        self.addCleanup(self._stop_flag_patch)

        self.real_registry = REGISTRY_PATH
        self.real_campaign = CAMPAIGN_PATH
        self.real_module = MODULES_DIR / MODULE_NAME
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
        """Set the operator flag to exactly True for one test."""
        self._flag_patch.stop()
        self._flag_patch = patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        )
        self._flag_patch.start()

    def _stop_tripwires(self) -> None:
        for patcher in reversed(self.tripwire_patchers):
            patcher.stop()

    def _blocked_provider(self, *args: Any, **kwargs: Any) -> Any:
        self.provider_attempted = True
        raise AssertionError("live provider client creation is forbidden in task 7.2")

    @staticmethod
    def _blocked_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network access is forbidden in task 7.2")

    # -- scratch redirect seams --------------------------------------------

    def _real_build_into_scratch(
        self, module_name: str, concept: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        """Wrap the real workspace builder so scratch stays project-local."""
        self.workspace_calls.append(module_name)
        return _REAL_WORKSPACE_BUILDER(
            module_name,
            concept,
            workspace_root=self.workspaces_root,
            staging_root=self.staging_root,
            **kwargs,
        )

    def _real_staging_into_scratch(
        self, source_hash: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Wrap the real staging reservation so scratch stays project-local."""
        kwargs.pop("staging_root", None)
        target = _REAL_STAGING_CREATOR(
            source_hash,
            staging_root=self.staging_root,
            **kwargs,
        )
        self.staging_calls.append(dict(target))
        return target

    def _real_registry_stage_into_scratch(
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

    # -- real worker wiring -------------------------------------------------

    def _real_seam(self, module_name: str, narrative: str, params: Any) -> Any:
        """Host seam wrapper: REAL worker seam with the injected author runner."""
        return worker.run_text_description_adaptation_seam(
            module_name,
            narrative,
            params,
            author_runner=self.author_runner,
            model="provider-free-text-author",
        )

    def _real_publication(self, seam_result: Any, **kwargs: Any) -> Any:
        """Host publication wrapper: REAL shared transaction with the REAL
        packet builder and REAL adaptation finisher."""

        def _recording_packet_builder(*args: Any, **build_kwargs: Any) -> Any:
            self.assertIs(
                build_kwargs.get("adaptation_convergence_callback"),
                worker.adaptation_convergence_callback,
            )
            return packet_builder.run_toolkit_homebrew_packet_build(
                *args, **build_kwargs
            )

        return worker.run_text_description_adaptation_publication(
            seam_result,
            build_runner=_recording_packet_builder,
            finisher_runner=finisher.run_toolkit_module_postbuild_finishing,
            **kwargs,
        )

    def _recording_convergence_callback(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        """Record the shared callback invocation while preserving production behavior."""
        self.convergence_calls.append(deepcopy(dict(context)))
        result = self.production_convergence_callback(context)
        self.convergence_results.append(deepcopy(result))
        return result

    def _builder_executor(
        self, builder_input: Dict[str, Any], progress_callback: Optional[Any] = None
    ) -> None:
        """Materialize a known gate-passing module without a provider."""
        self.assertEqual(builder_input["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        handoff = builder_input["llm_adaptation"]
        self.assertEqual(
            str((handoff["dossier"].get("source_hash") or "").lower()),
            FIXTURE_HASH,
        )
        target = (
            REPO_ROOT / builder_input["derived_builder_parameters"]["output_directory"]
        ).resolve()
        target.relative_to((REPO_ROOT / "tmp").resolve())
        shutil.copytree(BUILDER_FIXTURE, target, dirs_exist_ok=True)
        # Do not carry the fixture module's stale publication report into the
        # fresh adaptation candidate; the adaptation finisher owns a new one.
        (target / "toolkit_build_report.json").unlink(missing_ok=True)
        context_path = target / "module_context.json"
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["module_id"] = MODULE_NAME
        context["module_name"] = MODULE_TITLE
        context_areas = context.setdefault("areas", {})
        for area_path in sorted((target / "areas").glob("*.json")):
            if area_path.name.endswith("_BU.json"):
                continue
            context_areas.setdefault(area_path.stem, {})

        # The valid dossier carries these exact encounter identities.  Keep
        # the provider-free success fixture coherent with that dossier by
        # materializing schema-sufficient, staging-local copies of an
        # existing valid monster artifact.  This exercises the real
        # reuse-first/approved-identity guardrail without changing live
        # modules or enabling canonical generation.
        source_monsters = sorted((target / "monsters").glob("*.json"))
        if not source_monsters:
            raise AssertionError("builder fixture has no monster artifacts")
        source_monster = source_monsters[0]
        monster_template = json.loads(source_monster.read_text(encoding="utf-8"))
        for monster_name, monster_filename in (
            ("Smuggler", "smuggler.json"),
            ("Market lookout", "market_lookout.json"),
        ):
            monster = dict(monster_template)
            monster["name"] = monster_name
            _write_json(target / "monsters" / monster_filename, monster)
        # Normalize every copied monster artifact to the same schema-sufficient
        # staging-local template.  This prevents unrelated authored fixture
        # deficiencies from masking the guardrail assertions while preserving
        # each existing identity used by the copied area/context data.
        for monster_path in sorted((target / "monsters").glob("*.json")):
            existing = json.loads(monster_path.read_text(encoding="utf-8"))
            monster = dict(monster_template)
            monster["name"] = str(
                existing.get("name")
                or monster_path.stem.replace("_", " ").title()
            )
            _write_json(monster_path, monster)

        def _remove_unrelated_scene_refs(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: _remove_unrelated_scene_refs(item)
                    for key, item in value.items()
                    if key not in {
                        "npcs",
                        "monsters",
                        "creatures",
                        "visibleHostiles",
                    }
                }
            if isinstance(value, list):
                return [_remove_unrelated_scene_refs(item) for item in value]
            return value

        # Keep the copied module's structural fixture but remove unrelated
        # authored scene references.  The dossier encounter plus the exact
        # staging-local artifacts above are the only adversaries this success
        # scenario is intended to exercise.
        context = _remove_unrelated_scene_refs(context)
        continuity = context.get("continuity")
        if isinstance(continuity, dict):
            continuity["cross_module_refs"] = []
        for area_path in sorted((target / "areas").glob("*.json")):
            if area_path.name.endswith("_BU.json"):
                continue
            area = json.loads(area_path.read_text(encoding="utf-8"))
            _write_json(area_path, _remove_unrelated_scene_refs(area))
        _write_json(context_path, context)
        if progress_callback:
            progress_callback(
                "build", "Provider-free text adaptation materialized into staging"
            )

    def _run_worker_enabled(
        self, params: Dict[str, Any], *, missing_convergence_callback: bool = False
    ) -> None:
        """Run the ACTUAL Socket.IO worker on the enabled adaptation path.

        The host seam/publication attributes are wrapped to the REAL worker
        functions (injecting the deterministic author runner and the REAL
        packet builder/finisher), and every write boundary is redirected into
        the per-test scratch.
        """
        real_registry_stage = finisher._run_registry_stage

        def _registry_into_scratch(
            module_slug: str, *, module_dir: Any = None, adaptation: bool = False
        ) -> Dict[str, Any]:
            return self._real_registry_stage_into_scratch(
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
        convergence_patch = (
            patch.object(worker, "adaptation_convergence_callback", None)
            if missing_convergence_callback
            else patch.object(
                worker,
                "adaptation_convergence_callback",
                side_effect=self._recording_convergence_callback,
            )
        )
        with convergence_patch, patch.object(model_config_module, "ENABLE_LLM_ADAPTATION", True), patch.object(
            packet_builder, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            worker,
            "build_text_description_attempt_workspace",
            side_effect=self._real_build_into_scratch,
        ), patch.object(
            worker,
            "create_adaptation_staging_target",
            side_effect=self._real_staging_into_scratch,
        ), patch.object(
            web_interface,
            "socketio",
            self.recorder,
        ), patch.object(
            web_interface,
            "TEXT_DESCRIPTION_ADAPTATION_AVAILABLE",
            True,
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
            finisher, "_run_registry_stage", side_effect=_registry_into_scratch
        ), patch.object(adventure_writer, "_llm_intro_narrative", return_value=None), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(
            adventure_writer, "_llm_area_overview", return_value=None
        ):
            web_interface.simulate_build_process(params)

    # -- event inspection helpers ------------------------------------------

    def _events(self, name: str) -> List[Dict[str, Any]]:
        return [payload for event, payload in self.recorder.events if event == name]

    def _progress_stage_names(self) -> List[str]:
        return [
            str(payload.get("stage_name") or "")
            for event, payload in self.recorder.events
            if event == "module_progress"
        ]

    # -- protected real-state helpers --------------------------------------

    def _snapshot_real_state(self) -> Dict[str, Any]:
        modules_dir = MODULES_DIR
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
        modules_dir = MODULES_DIR
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
        self.assertFalse(self.real_module.exists(), "no direct modules/<name> write")

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


class TestTextSocketIoAdaptationEnabledPath(
    _TextSocketIoScratchMixin, unittest.TestCase
):
    """The ACTUAL text-description Socket.IO worker with adaptation enabled
    produces the same verified staged publication contract as the upload
    path (task 7.1) and never touches the legacy builder or real state."""

    def test_actual_socketio_worker_reaches_verified_adaptation_completion(
        self,
    ) -> None:
        sentinels = self._snapshot_real_state()
        self._run_worker_enabled(_params())

        # Exactly one verified completion, zero errors, and the real seam +
        # real publication transaction ran (authoring before ModuleBuilder).
        completes = self._events("module_complete")
        self.assertEqual(len(completes), 1, "exactly one completion expected")
        self.assertEqual(self._events("module_error"), [])
        self.assertIn(
            "Adaptation Publication", self._progress_stage_names(), "stage 13 progress"
        )
        self.assertIsNone(
            _GuardedModuleBuilder.last_instance,
            "legacy ModuleBuilder must never be constructed on the enabled path",
        )
        self.assertEqual(len(self.author_runner.calls), 1, "authoring exactly once")
        self.assertEqual(len(self.workspace_calls), 1)
        self.assertEqual(len(self.staging_calls), 1)
        self.assertEqual(len(self.registry_stage_calls), 1)
        self.assertEqual(len(self.convergence_calls), 1)
        self.assertEqual(len(self.convergence_results), 1)
        callback_context = self.convergence_calls[0]
        self.assertEqual(callback_context["contract_version"], CONVERGENCE_CONTRACT_VERSION)
        self.assertEqual(callback_context["source_hash"], FIXTURE_HASH)
        self.assertEqual(
            callback_context["staging_identity"]["output_directory"],
            callback_context["staging_identity"]["path"],
        )
        self.assertEqual(self.convergence_results[0]["status"], "success")
        self.assertEqual(
            self.convergence_results[0]["reason_code"], "no_repairable_blocker"
        )
        self.assertFalse(self.provider_attempted, "deterministic convergence called a provider")

        payload = completes[0]
        self.assertEqual(payload["module_name"], MODULE_NAME)
        self.assertEqual(payload["final_status"], "success")
        self.assertIs(payload["generation_succeeded"], True)
        self.assertEqual(payload["adaptation_route"], "llm_adaptation")
        self.assertIs(payload["adaptation_job"], True)
        self.assertEqual(payload["adaptation_outcome"], "completed")
        self.assertEqual(payload["adaptation_source_hash"], FIXTURE_HASH)
        self.assertTrue(payload["adaptation_attempt_id"])
        self.assertTrue(payload["adaptation_workspace_path"])
        self.assertTrue(payload["adaptation_staging_target_path"])
        route_decision = payload["adaptation_route_decision"]
        self.assertEqual(route_decision["route_selected"], "llm_adaptation")
        self.assertIs(route_decision["fallback_allowed"], False)

        # Bounded publication summary mirrors the upload contract: gates
        # pass, registry verified, campaign explicitly deferred (no active
        # campaign), Python authoritative.
        report = payload["build_report"]
        self.assertEqual(report["build_status"], "success")
        self.assertEqual(report["finisher_status"], "success")
        self.assertEqual(report["gate_playable_status"], "pass")
        self.assertIn("schema", report.get("gate_domains", []))
        self.assertEqual(report["registry_status"], "success")
        self.assertIs(report["registry_verified"], True)
        self.assertEqual(report["campaign_sync_status"], "deferred")
        self.assertIs(report["campaign_visibility_verified"], False)
        self.assertIs(report["python_authoritative"], True)
        self._assert_no_leakage(json.dumps(payload), "module_complete payload")

        # The real packet build persisted the workspace contract: build mode,
        # all adaptation gates pass, attempt report persisted, provenance and
        # the reserved scratch staging target.
        workspace = REPO_ROOT.joinpath(
            *Path(payload["adaptation_workspace_path"]).parts
        )
        self.assertTrue(workspace.is_dir())
        build_result = json.loads(
            (workspace / "build_result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(build_result.get("status"), "success", build_result)
        self.assertEqual(build_result.get("module_name"), MODULE_NAME)
        self.assertEqual(build_result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        gates = build_result.get("adaptation_gates") or {}
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
        attempt_report = build_result.get("adaptation_attempt_report") or {}
        self.assertEqual(attempt_report.get("status"), "persisted")
        self.assertEqual(attempt_report.get("source_hash"), FIXTURE_HASH)
        provenance = build_result.get("adaptation_provenance") or {}
        self.assertEqual(str(provenance.get("source_hash") or "").lower(), FIXTURE_HASH)
        staging_target = build_result.get("staging_target") or {}
        self.assertTrue(
            str(staging_target.get("path") or "").startswith(
                "tmp/toolkit_text_description_socketio_path"
            ),
            staging_target,
        )
        builder_input = json.loads(
            (workspace / "builder_input.json").read_text(encoding="utf-8")
        )
        self.assertEqual(builder_input["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(
            builder_input["llm_adaptation"]["dossier"]["source_hash"], FIXTURE_HASH
        )
        dossier_artifacts = list(
            (workspace / "adaptation_attempts").rglob("adaptation_dossier.json")
        )
        self.assertEqual(len(dossier_artifacts), 1)
        persisted_dossier = json.loads(dossier_artifacts[0].read_text(encoding="utf-8"))
        self.assertEqual(
            str((persisted_dossier.get("payload") or {}).get("source_hash") or "").lower(),
            FIXTURE_HASH,
        )
        self.assertEqual(
            str((persisted_dossier.get("provenance") or {}).get("source_hash") or "").lower(),
            FIXTURE_HASH,
        )

        # The staged module (inside scratch staging) carries the same
        # provenance/notice surfaces as the upload path.
        module_dir = REPO_ROOT / build_result["output_directory"]
        self.assertTrue(module_dir.is_dir())
        self.assertTrue(
            str(module_dir).startswith(str(REPO_ROOT / "tmp")),
            "staged module must live under project scratch",
        )
        self.assertTrue((module_dir / "module_context.json").exists())
        context = json.loads(
            (module_dir / "module_context.json").read_text(encoding="utf-8")
        )
        self.assertEqual(context.get("adaptation_notice"), "Adapted for NEQ-TTRPG")
        context_prov = context.get("adaptation_provenance") or {}
        self.assertEqual(
            str(context_prov.get("source_hash") or "").lower(), FIXTURE_HASH
        )
        self.assertEqual(context_prov.get("rights_class"), "user_authored")
        world = context_prov.get("world_context_provenance") or {}
        self.assertEqual(world.get("fallback_status"), "seed_data_unavailable")
        self.assertIs(world.get("read_only"), True)
        self.assertTrue((module_dir / "source_fidelity_report.json").exists())

        # Readable persisted MODULE_SUMMARY.md with the adaptation notice.
        summary_path = module_dir / "MODULE_SUMMARY.md"
        self.assertTrue(summary_path.exists())
        summary = summary_path.read_text(encoding="utf-8")
        self.assertGreater(len(summary), 500)
        self.assertIn("Adapted for NEQ-TTRPG", summary)
        self._assert_no_leakage(summary, "MODULE_SUMMARY.md")

        # The finisher report matches the upload contract exactly: same
        # publication order, registry as the final stateful publication with
        # post-write verification, campaign deferred/no_active_campaign.
        report_path = module_dir / "toolkit_build_report.json"
        self.assertTrue(report_path.exists())
        finisher_report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(finisher_report.get("status"), "success", finisher_report)
        self.assertEqual(finisher_report.get("publication_status"), "completed")
        self.assertEqual(
            finisher_report.get("publication_order"), EXPECTED_PUBLICATION_ORDER
        )
        self.assertIs(
            finisher_report.get("registry_is_final_stateful_publication"), True
        )
        self.assertIs(finisher_report.get("python_authoritative"), True)
        self.assertEqual(finisher_report.get("ready_status"), "pass")
        self.assertEqual(finisher_report.get("publishable_status"), "pass")
        finisher_stages = finisher_report.get("stages") or {}
        registry_stage = finisher_stages.get("registry") or {}
        self.assertEqual(registry_stage.get("status"), "success")
        self.assertIs(registry_stage.get("integration_attempted"), True)
        verification = registry_stage.get("verification") or {}
        self.assertIs(verification.get("verified"), True)
        self.assertIs(verification.get("module_verified"), True)
        self.assertIs(verification.get("areas_verified"), True)
        campaign_stage = finisher_stages.get("campaign_sync") or {}
        self.assertEqual(campaign_stage.get("status"), "deferred")
        self.assertEqual(campaign_stage.get("reason"), "no_active_campaign")
        self.assertIs(campaign_stage.get("campaign_visibility_verified"), False)
        self._assert_no_leakage(
            json.dumps(finisher_report), "toolkit_build_report.json"
        )

        # Registry-last: the scratch mirror received module + areas and no
        # campaign file was created (explicit no-active-campaign handling).
        persisted_registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        module_entry = persisted_registry["modules"].get(MODULE_NAME)
        self.assertIsInstance(module_entry, dict)
        self.assertEqual(module_entry.get("moduleName"), MODULE_NAME)
        area_entries = [
            area
            for area in persisted_registry.get("areas", {}).values()
            if isinstance(area, dict) and area.get("module") == MODULE_NAME
        ]
        self.assertTrue(area_entries, "no adapted area entries in the registry")
        self.assertFalse(self.campaign_path.exists(), "no campaign file may be created")

        # Authoring received only the bounded source context with Python-owned
        # rights and the stable source identity; no raw source or credential
        # leakage into the provider boundary.
        source_context, attempt_metadata, _kwargs = self.author_runner.calls[0]
        self.assertEqual(attempt_metadata.get("source_hash"), FIXTURE_HASH)
        self.assertEqual(attempt_metadata.get("rights_class"), "user_authored")
        serialized_context = json.dumps(source_context, ensure_ascii=True)
        self._assert_no_leakage(serialized_context, "author source context")
        self.assertLess(
            len(serialized_context), 20_000, "provider boundary must stay bounded"
        )

        self._assert_real_state_unchanged(sentinels)

    def test_actual_socketio_worker_author_refusal_never_reports_success(
        self,
    ) -> None:
        sentinels = self._snapshot_real_state()
        self.author_runner = FakeAuthorRunner(refused=True)
        self._run_worker_enabled(_params())

        # The enabled path fails closed: a blocked adaptation outcome, no
        # completion, no legacy builder, no module, no registry/campaign
        # mutation.
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
        self.assertEqual(len(self.registry_stage_calls), 0)
        # No publication boundary was reached: the scratch registry mirror is
        # byte-unchanged and no campaign file was created.
        self.assertEqual(self.registry_path.read_bytes(), self.original_registry_bytes)
        self.assertFalse(self.campaign_path.exists())
        self._assert_real_state_unchanged(sentinels)

    def test_actual_socketio_worker_missing_callback_fails_closed_without_legacy_fallback(
        self,
    ) -> None:
        """A selected text adaptation route cannot downgrade when convergence is unavailable."""
        sentinels = self._snapshot_real_state()
        self._run_worker_enabled(_params(), missing_convergence_callback=True)

        self.assertEqual(self._events("module_complete"), [])
        errors = self._events("module_error")
        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(payload["adaptation_route"], "llm_adaptation")
        self.assertIs(payload["adaptation_job"], True)
        self.assertEqual(payload["adaptation_outcome"], "blocked")
        self.assertIs(payload["generation_succeeded"], False)
        self.assertIsNone(_GuardedModuleBuilder.last_instance)
        self.assertEqual(self.convergence_calls, [])
        self.assertEqual(self.registry_stage_calls, [])
        self.assertFalse(self.provider_attempted)
        self.assertEqual(self.registry_path.read_bytes(), self.original_registry_bytes)
        self.assertFalse(self.campaign_path.exists())
        self._assert_real_state_unchanged(sentinels)


class TestTextSocketIoLegacyPreserved(_TextSocketIoScratchMixin, unittest.TestCase):
    """When adaptation is disabled the ACTUAL Socket.IO worker preserves the
    legacy direct-builder path with its exact legacy completion contract."""

    def _run_worker_legacy(self, params: Dict[str, Any]) -> None:
        sys.modules["core.generators.module_builder"] = _fake_builder_module(
            _LegacyModuleBuilder
        )
        self.addCleanup(
            lambda: sys.modules.pop("core.generators.module_builder", None)
        )
        with patch.object(web_interface, "socketio", self.recorder), patch.object(
            web_interface, "TOOLKIT_BUILDER_READINESS_AVAILABLE", True
        ), patch.object(
            web_interface,
            "run_toolkit_builder_readiness_gate",
            _FakeReadinessGate(),
        ), patch.object(
            web_interface, "TOOLKIT_MODULE_FINISHER_AVAILABLE", True
        ), patch.object(
            web_interface,
            "run_toolkit_module_postbuild_finishing",
            _FakeFinisher(),
        ):
            web_interface.simulate_build_process(params)

    def test_legacy_flag_false_keeps_legacy_direct_builder_contract(self) -> None:
        sentinels = self._snapshot_real_state()
        self._run_worker_legacy(_params())

        # The legacy builder was constructed and the exact legacy completion
        # payload was emitted with no adaptation fields and no errors.
        self.assertIsNotNone(_LegacyModuleBuilder.last_instance)
        self.assertEqual(len(_LegacyModuleBuilder.last_instance.build_calls), 1)
        self.assertEqual(self._events("module_error"), [])
        completes = self._events("module_complete")
        self.assertEqual(len(completes), 1)
        payload = completes[0]
        self.assertEqual(payload["module_name"], MODULE_NAME)
        self.assertEqual(payload["final_status"], "success")
        self.assertEqual(payload["post_build_status"], "success")
        self.assertEqual(payload["ready_status"], "pass")
        self.assertEqual(payload["publishable_status"], "pass")
        for key in payload:
            self.assertNotIn(
                "adaptation", str(key).lower(), f"adaptation key leaked: {key}"
            )
        # No adaptation progress stage was emitted and the scratch registry
        # mirror was never touched by the legacy path.
        self.assertNotIn("Adaptation Publication", self._progress_stage_names())
        self.assertEqual(self.registry_path.read_bytes(), self.original_registry_bytes)
        self.assertFalse(self.campaign_path.exists())
        self._assert_real_state_unchanged(sentinels)


class TestTextSocketIoHygiene(unittest.TestCase):
    """Provider-free, path-policy, and contract hygiene for this suite."""

    def test_this_suite_is_ascii_only_with_spdx_header(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText: 2024 MoonlightByte", source)
        non_ascii = [ch for ch in source if ord(ch) > 127]
        self.assertEqual(non_ascii, [])

    def test_no_os_temp_or_absolute_scratch_paths(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        scan = source.split("class TestTextSocketIoHygiene", 1)[0]
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
        self.assertIn("toolkit_text_description_socketio_path", scan)
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

    def test_direct_builder_template_progress_and_activity_contract(self) -> None:
        source = (REPO_ROOT / "web" / "templates" / "module_toolkit.html").read_text(
            encoding="utf-8"
        )
        progress_start = source.index("socket.on('module_progress'")
        progress_end = source.index("socket.on('module_complete'", progress_start)
        progress = source[progress_start:progress_end]

        for marker in (
            "updateHomebrewActivity(",
            "'module_progress'",
            "'direct_builder_publication'",
            "getHomebrewActivityMessages('direct_builder_publication')",
            "Math.round(data.percentage || 0)",
            "progressBar.style.width",
            "progressPercentage.textContent",
            "progressStages.forEach",
            "index < data.stage",
            "index === data.stage",
            "data.stage_name",
        ):
            self.assertIn(marker, progress)

        activity_hook = progress[
            progress.index("updateHomebrewActivity(") : progress.index(
                "const percentage"
            )
        ]
        for forbidden_pattern in (
            r"\bdata\.",
            r"\bpayload\.",
            "source_filename",
            "provider",
            "raw_provider_payload",
            "JSON.stringify",
        ):
            self.assertNotRegex(activity_hook, forbidden_pattern)

        for event in ("module_complete", "module_error", "build_cancelled"):
            self.assertRegex(
                source,
                re.compile(
                    rf"socket\.on\('{event}'.*?clearHomebrewActivity\(\)",
                    re.DOTALL,
                ),
            )

        for legacy_marker in (
            "request_module_list",
            "showError(message)",
            "resetBuilderUI()",
        ):
            self.assertIn(legacy_marker, source)

    def test_suite_exercises_real_worker_seam_and_real_transaction(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("web_interface.simulate_build_process(params)", source)
        self.assertIn("worker.run_text_description_adaptation_seam(", source)
        self.assertIn("worker.run_text_description_adaptation_publication(", source)
        self.assertIn("packet_builder.run_toolkit_homebrew_packet_build", source)
        self.assertIn("finisher.run_toolkit_module_postbuild_finishing", source)
        self.assertIn("finisher._run_registry_stage", source)
        self.assertIn("_GuardedModuleBuilder", source)

    def test_protected_real_state_checked_in_every_behavioral_class(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("self._assert_real_state_unchanged(sentinels)", source)
        self.assertIn("_snapshot_real_state", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
