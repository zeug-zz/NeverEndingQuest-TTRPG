# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for task 2.5 of toolkit-llm-adaptation-runtime-unification:
bounded world-context provenance flows into both input adapters and attempt
reports, with an explicit unavailable fallback status, and no raw campaign,
registry, pressure, or seed payload ever reaches the provider.

The suite locks:

  * both input adapters (upload handoff and text-description workspace) pass
    the canonical read-only world-context provenance into authoring through
    the injectable runner/client seam, for available, unavailable, and broken
    world-context providers;
  * adapter results and persisted attempt reports (source-context artifact,
    dossier artifact, failure report) carry the world-context provenance with
    an explicit ``seed_data_unavailable`` (or equivalent) fallback when the
    world context is unavailable, and never claim world-seed grounding they
    do not have;
  * provider-facing author messages contain only bounded provenance scalars
    (status/version/hash/selected-module/read-only labels); raw campaign
    model, registry entries, pressure lists, and seed content are absent;
  * blocked adapter results carry canonical unavailable provenance instead of
    an empty mapping, so every report surface stays canonical;
  * deterministic hashes/status preservation and bounded diagnostics;
  * no provider/network/OS-temp usage and project-local scratch only.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_world_context_handoff/<uuid>/`` and are removed
deterministically via addCleanup. No OS temp directory is used. The adapters
never invoke ModuleBuilder, never touch modules/, the registry, campaign, or
runtime state.
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_adaptation_runtime as runtime
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_FAILURE_REPORT,
    ARTIFACT_KIND_SOURCE_CONTEXT,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
)
from utils.toolkit_adaptation_author import build_adaptation_author_messages
from utils.toolkit_adaptation_world_context import (
    WORLD_CONTEXT_PROVENANCE_VERSION,
    build_world_context_provenance,
    build_world_narrative_context,
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
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_world_context_handoff"
RUNTIME_MODULE_PATH = REPO_ROOT / "web" / "extensions" / "toolkit_adaptation_runtime.py"
AUTHOR_MODULE_PATH = REPO_ROOT / "utils" / "toolkit_adaptation_author.py"
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

# Raw world-state values that MUST never reach the provider. Each marker is
# unique prose or a structural key from the campaign model, pressure list,
# registry, or approved seeds used by the fixtures below.
CAMPAIGN_TITLE = "The Sunken World"
CAMPAIGN_SUMMARY = "Secret campaign summary that must never reach the provider."
PRESSURE_SUMMARY = "The tide rises and the drowned city wakes."
REGISTRY_SUMMARY = "Registry module summary that must never reach the provider."
SEED_SUMMARY = "Approved seed narrative that must never reach the provider."
SEED_HOOK = "A bell rings beneath the waves."
SEED_PRESSURE = "The drowned city surfaces in three days."
RAW_WORLD_KEYS = (
    "campaign_model",
    "active_pressures",
    "registry_context",
    "approved_module_seeds",
    "component_status",
    "source_kinds",
)

CAMPAIGN_MODEL = {
    "campaign_id": "camp-1",
    "title": CAMPAIGN_TITLE,
    "summary": CAMPAIGN_SUMMARY,
    "tone": "haunted",
    "themes": ["drowning", "secrets"],
}
PRESSURES = [{"id": "p1", "summary": PRESSURE_SUMMARY, "turns_remaining": 3}]
REGISTRY = {
    "modules": {
        "Lantern_Market": {
            "title": "Lantern Market",
            "summary": REGISTRY_SUMMARY,
            "slug": "Lantern_Market",
        }
    }
}
SEEDS = [
    {
        "module_slug": "Lantern_Market",
        "seed_type": "world_seed",
        "approved": True,
        "status": "approved",
        "content": {
            "summary": SEED_SUMMARY,
            "hook": SEED_HOOK,
            "pressure": SEED_PRESSURE,
        },
    }
]

SELECTED_MODULE = "Lantern_Market"
SEED_VERSION = "fixture.v2"

FORBIDDEN_MARKERS = (
    CAMPAIGN_TITLE,
    CAMPAIGN_SUMMARY,
    PRESSURE_SUMMARY,
    REGISTRY_SUMMARY,
    SEED_SUMMARY,
    SEED_HOOK,
    SEED_PRESSURE,
) + RAW_WORLD_KEYS


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_pack() -> Dict[str, Any]:
    """Build a bounded world-narrative pack containing raw campaign, pressure,
    registry, and seed content that must never cross the provider boundary."""
    return build_world_narrative_context(
        CAMPAIGN_MODEL,
        PRESSURES,
        REGISTRY,
        SEEDS,
        selected_module=SELECTED_MODULE,
        seed_version=SEED_VERSION,
    )


def _dossier_for_attempt(attempt_metadata: Dict[str, Any]) -> Dict[str, Any]:
    dossier = deepcopy(_load_fixture())
    dossier["source_hash"] = attempt_metadata["source_hash"]
    dossier["source_title"] = attempt_metadata["source_title"]
    dossier["source_profile"] = attempt_metadata["source_profile"]
    dossier["rights_class"] = attempt_metadata["rights_class"]
    dossier["rights_basis"] = attempt_metadata["rights_basis"]
    dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
    dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
    dossier["adaptation_mode"] = "llm_adaptation"
    return dossier


def _scan_forbidden(text: str) -> List[str]:
    """Return every raw world marker present in a serialized payload."""
    return [marker for marker in FORBIDDEN_MARKERS if marker in text]


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider).

    Captures the source context, Python-owned attempt metadata, and kwargs
    (including the world-context provenance) exactly as the real runner would
    receive them, and rebuilds the provider-facing author messages so the
    leakage scan runs against the true request boundary.
    """

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = _dossier_for_attempt,
        refused: bool = False,
    ) -> None:
        self.calls: List[tuple] = []
        self.messages: List[List[Dict[str, str]]] = []
        self.dossier_builder = dossier_builder
        self.refused = refused

    def __call__(
        self, source_context: Any, attempt_metadata: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        self.calls.append(
            (
                deepcopy(dict(source_context)) if isinstance(source_context, dict) else source_context,
                deepcopy(dict(attempt_metadata or {})),
                dict(kwargs),
            )
        )
        world_provenance = build_world_context_provenance(
            kwargs.get("world_context") if isinstance(kwargs.get("world_context"), dict) else None
        )
        metadata = dict(attempt_metadata or {})
        self.messages.append(
            build_adaptation_author_messages(
                source_context,
                metadata,
                world_context=world_provenance,
            )
        )
        if self.refused:
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": "refusal",
                "diagnostics": [{"code": "dossier_refused", "message": "adaptation author refused"}],
                "dossier": None,
            }
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": self.dossier_builder(dict(attempt_metadata or {})),
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-wc-1"},
        }


def _packet(*, source_hash: str = FIXTURE_HASH, title: str = "Sunken Lighthouse") -> Dict[str, Any]:
    return {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_path": "uploads/fixture.md",
        "source_hash": source_hash,
        "title": title,
        "author": "",
        "description": "A bounded adventure about a sunken lighthouse.",
        "adventure_summary": "The keeper's quarters and the flooded stairs.",
        "module_tone": "haunted",
        "acts": [{"name": "Descent", "summary": "Into the dark."}],
        "locations": [
            {"name": "Keeper's Quarters", "location": "tower", "description": "Rusted spyglass."}
        ],
        "npc_seeds": [],
        "encounter_seeds": [],
        "assumptions": ["Fixture packet for the world-context handoff tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }


def _make_workspace(scratch: Path, *, text: str = FIXTURE_TEXT) -> Path:
    workspace = scratch / "workspace"
    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
    files["source_original"].write_text(text, encoding="utf-8")
    packet = _packet()
    persist_normalized_packet_artifact(workspace, packet)
    snapshot = build_review_snapshot(
        job_id="job-1",
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    persist_review_snapshot_artifact(workspace, snapshot)
    return workspace


class _ProjectLocalScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def _assert_no_module_side_effects(self) -> None:
        modules_dir = self.scratch / "modules"
        self.assertFalse(modules_dir.exists())
        for sentinel in ("world_registry.json", "campaign.json"):
            self.assertFalse(
                (self.scratch / sentinel).exists(),
                f"{sentinel} must not be created by the adapters",
            )
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def _ready_handoff(self, *, world_context: Any = None, provider: Any = None) -> tuple:
        workspace = _make_workspace(self.scratch)
        options: Dict[str, Any] = {
            "source_kind": "markdown",
            "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
            "review_state": "approved_for_build",
            "job_id": "job-1",
        }
        if world_context is not None:
            options["world_context"] = world_context
        if provider is not None:
            options["world_context_provider"] = provider
        handoff = runtime.build_upload_adaptation_handoff(workspace, **options)
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_READY)
        return handoff, workspace

    def _ready_manifest(self, *, world_context: Any = None, provider: Any = None) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "module_name": "Sunken_Lighthouse",
            "concept": FIXTURE_TEXT,
            "job_id": "text-job-1",
            "workspace_root": "tmp/toolkit_adaptation_world_context_handoff"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
        }
        if world_context is not None:
            options["world_context"] = world_context
        if provider is not None:
            options["world_context_provider"] = provider
        manifest = runtime.build_text_description_attempt_workspace(**options)
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_READY)
        return manifest

    def _workspace_path(self, manifest: Dict[str, Any]) -> Path:
        return REPO_ROOT.joinpath(*Path(manifest["workspace"]["path"]).parts)


class TestUploadWorldContextHandoff(_ProjectLocalScratchMixin, unittest.TestCase):
    """The upload adapter passes canonical provenance into authoring."""

    def test_available_world_context_reaches_runner_and_result(self) -> None:
        pack = _build_pack()
        provenance = build_world_context_provenance(pack)
        handoff, workspace = self._ready_handoff(world_context=pack)
        self.assertEqual(handoff["world_context_evidence"], "supplied_context")
        self.assertEqual(handoff["world_context"], provenance)

        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(len(runner.calls), 1)

        _, attempt_metadata, kwargs = runner.calls[0]
        received = kwargs.get("world_context")
        self.assertEqual(received, provenance)
        self.assertIs(received["read_only"], True)
        self.assertIs(received["provider_free"], True)
        self.assertFalse(received["canon_write_allowed"])
        self.assertFalse(received["registry_write_allowed"])
        self.assertEqual(received["context_status"], "available")
        self.assertEqual(received["fallback_status"], "none")
        self.assertEqual(received["world_seed_status"], "available")
        self.assertEqual(received["world_seed_hash"], provenance["world_seed_hash"])
        self.assertEqual(received["selected_module"], SELECTED_MODULE)
        # Attempt metadata carries only scalar provenance labels.
        self.assertEqual(attempt_metadata["world_seed_status"], "available")
        self.assertEqual(attempt_metadata["world_context_status"], "available")
        self.assertEqual(attempt_metadata["world_context_read_only"], True)

        self.assertEqual(result["world_context"], provenance)
        self.assertEqual(result["authoring"]["authoring_status"], "ready")
        self._assert_no_module_side_effects()

    def test_available_world_context_reaches_persisted_attempt_reports(self) -> None:
        pack = _build_pack()
        provenance = build_world_context_provenance(pack)
        handoff, workspace = self._ready_handoff(world_context=pack)
        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        attempt_id = result["attempt"]["attempt_id"]

        source_artifact = load_adaptation_artifact(workspace, attempt_id, ARTIFACT_KIND_SOURCE_CONTEXT)
        self.assertIsNotNone(source_artifact)
        self.assertEqual(
            source_artifact["provenance"]["world_context_provenance"], provenance
        )
        dossier_artifact = load_adaptation_artifact(
            workspace, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)
        self.assertEqual(
            dossier_artifact["provenance"]["world_context_provenance"], provenance
        )
        self.assertEqual(
            dossier_artifact["provenance"]["world_context_status"], "available"
        )
        self.assertEqual(
            dossier_artifact["provenance"]["world_seed_status"], "available"
        )
        self.assertEqual(dossier_artifact["payload"], result["dossier"])

    def test_unavailable_world_context_is_explicit_fallback(self) -> None:
        handoff, workspace = self._ready_handoff()
        self.assertEqual(handoff["world_context_evidence"], "unavailable")
        fallback = build_world_context_provenance(None)
        self.assertEqual(handoff["world_context"], fallback)
        self.assertEqual(fallback["context_status"], "unavailable")
        self.assertEqual(fallback["world_seed_status"], "unavailable")
        self.assertEqual(fallback["fallback_status"], "seed_data_unavailable")
        self.assertIsNone(fallback["world_seed_hash"])
        self.assertIsNone(fallback["world_seed_version"])

        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        _, attempt_metadata, kwargs = runner.calls[0]
        received = kwargs["world_context"]
        self.assertEqual(received, fallback)
        # No world-seed grounding can be claimed when unavailable.
        self.assertEqual(attempt_metadata["world_seed_status"], "unavailable")
        self.assertNotIn("world_seed_hash", attempt_metadata)
        self.assertEqual(result["world_context"], fallback)

        attempt_id = result["attempt"]["attempt_id"]
        dossier_artifact = load_adaptation_artifact(
            workspace, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertEqual(
            dossier_artifact["provenance"]["world_context_provenance"]["fallback_status"],
            "seed_data_unavailable",
        )
        self._assert_no_module_side_effects()

    def test_broken_world_provider_falls_back_and_authoring_proceeds(self) -> None:
        class BrokenProvider:
            def build(self) -> Dict[str, Any]:
                raise RuntimeError("world context provider unavailable")

        handoff, workspace = self._ready_handoff(provider=BrokenProvider())
        self.assertEqual(handoff["world_context_evidence"], "provider_failed")
        codes = [item["code"] for item in handoff["diagnostics"]]
        self.assertIn("world_context_unavailable", codes)
        fallback = build_world_context_provenance(None)
        self.assertEqual(handoff["world_context"], fallback)

        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(result["world_context"], fallback)
        _, attempt_metadata, kwargs = runner.calls[0]
        self.assertEqual(kwargs["world_context"], fallback)
        self.assertEqual(attempt_metadata["world_seed_status"], "unavailable")
        self._assert_no_module_side_effects()

    def test_provenance_is_deterministic_across_rebuilds(self) -> None:
        first = build_world_context_provenance(_build_pack())
        second = build_world_context_provenance(_build_pack())
        self.assertEqual(first, second)
        handoff, _ = self._ready_handoff(world_context=_build_pack())
        self.assertEqual(handoff["world_context"], first)
        self.assertEqual(
            runtime.validate_adaptation_runtime_envelope(handoff["envelope"])["valid"],
            True,
        )

    def test_provenance_has_no_raw_pack_structural_keys(self) -> None:
        provenance = build_world_context_provenance(_build_pack())
        self.assertEqual(
            provenance["provenance_version"], WORLD_CONTEXT_PROVENANCE_VERSION
        )
        self.assertIs(provenance["read_only"], True)
        self.assertIs(provenance["raw_context_included"], False)
        serialized = json.dumps(provenance, sort_keys=True)
        for key in RAW_WORLD_KEYS:
            self.assertNotIn(key, serialized)
        self.assertNotIn(CAMPAIGN_SUMMARY, serialized)
        self.assertNotIn(SEED_SUMMARY, serialized)


class TestTextWorldContextHandoff(_ProjectLocalScratchMixin, unittest.TestCase):
    """The text-description adapter passes canonical provenance with parity."""

    def test_available_world_context_reaches_runner_and_result(self) -> None:
        pack = _build_pack()
        provenance = build_world_context_provenance(pack)
        manifest = self._ready_manifest(world_context=pack)
        self.assertEqual(manifest["world_context_evidence"], "supplied_context")
        self.assertEqual(manifest["world_context"], provenance)
        self.assertEqual(manifest["world_context_status"], "available")

        runner = FakeAuthorRunner()
        result = runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(len(runner.calls), 1)
        _, attempt_metadata, kwargs = runner.calls[0]
        self.assertEqual(kwargs["world_context"], provenance)
        self.assertEqual(attempt_metadata["world_context_status"], "available")
        self.assertEqual(attempt_metadata["world_seed_status"], "available")
        self.assertEqual(result["world_context"], provenance)

        attempt_id = result["attempt"]["attempt_id"]
        workspace_path = self._workspace_path(manifest)
        dossier_artifact = load_adaptation_artifact(
            workspace_path, attempt_id, ARTIFACT_KIND_ADAPTATION_DOSSIER
        )
        self.assertIsNotNone(dossier_artifact)
        self.assertEqual(
            dossier_artifact["provenance"]["world_context_provenance"], provenance
        )
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_unavailable_world_context_is_explicit_fallback(self) -> None:
        manifest = self._ready_manifest()
        fallback = build_world_context_provenance(None)
        self.assertEqual(manifest["world_context"], fallback)
        self.assertEqual(manifest["world_context_evidence"], "unavailable")
        self.assertEqual(manifest["world_context_status"], "unavailable")
        self.assertEqual(manifest["world_context_fallback_status"], "seed_data_unavailable")

        runner = FakeAuthorRunner()
        result = runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        _, attempt_metadata, kwargs = runner.calls[0]
        self.assertEqual(kwargs["world_context"], fallback)
        self.assertEqual(attempt_metadata["world_seed_status"], "unavailable")
        self.assertNotIn("world_seed_hash", attempt_metadata)
        self.assertEqual(result["world_context"], fallback)
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())

    def test_broken_world_provider_falls_back_and_authoring_proceeds(self) -> None:
        class BrokenProvider:
            def build(self) -> Dict[str, Any]:
                raise RuntimeError("world context provider unavailable")

        manifest = self._ready_manifest(provider=BrokenProvider())
        self.assertEqual(manifest["world_context_evidence"], "provider_failed")
        self.assertEqual(manifest["world_context_fallback_status"], "seed_data_unavailable")
        fallback = build_world_context_provenance(None)

        runner = FakeAuthorRunner()
        result = runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        _, attempt_metadata, kwargs = runner.calls[0]
        self.assertEqual(kwargs["world_context"], fallback)
        self.assertEqual(attempt_metadata["world_seed_status"], "unavailable")
        self.assertEqual(result["world_context"], fallback)
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())


class TestProviderBoundaryLeakageScan(_ProjectLocalScratchMixin, unittest.TestCase):
    """No raw campaign, registry, pressure, or seed payload reaches the provider."""

    def _capture(self, runner: FakeAuthorRunner) -> str:
        # Scan the provider-facing input payload (user message content) only.
        # The static system prompt is a contract file that documents field
        # names and must not be treated as provider-supplied data.
        return "\n".join(
            json.dumps(message.get("content", ""), sort_keys=True)
            for message in runner.messages[-1]
            if message.get("role") == "user"
        )

    def _user_payload(self, runner: FakeAuthorRunner) -> Dict[str, Any]:
        user_content = next(
            message.get("content", "")
            for message in runner.messages[-1]
            if message.get("role") == "user"
        )
        return json.loads(user_content.split("ADAPTATION_AUTHOR_INPUT:\n", 1)[1])

    def test_upload_provider_messages_carry_scalars_only(self) -> None:
        pack = _build_pack()
        handoff, _ = self._ready_handoff(world_context=pack)
        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        serialized = self._capture(runner)
        self.assertEqual(_scan_forbidden(serialized), [])
        # The only pack-derived identity allowed is the bounded scalar label.
        self.assertIn(SELECTED_MODULE, serialized)
        self.assertIn("world_context_provenance", serialized)
        self.assertIn("world_seed_status", serialized)
        self.assertIn("read_only", serialized)

    def test_text_provider_messages_carry_scalars_only(self) -> None:
        pack = _build_pack()
        manifest = self._ready_manifest(world_context=pack)
        runner = FakeAuthorRunner()
        result = runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        serialized = self._capture(runner)
        self.assertEqual(_scan_forbidden(serialized), [])
        self.assertIn(SELECTED_MODULE, serialized)

    def test_unavailable_provider_messages_claim_no_seed_grounding(self) -> None:
        handoff, _ = self._ready_handoff()
        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        serialized = self._capture(runner)
        self.assertEqual(_scan_forbidden(serialized), [])
        # Explicit fallback status, and no seed identity at all: the canonical
        # provenance key exists but carries no hash value when unavailable.
        self.assertIn("seed_data_unavailable", serialized)
        self.assertIn("world_seed_status", serialized)
        self.assertIn("unavailable", serialized)
        world_provenance = self._user_payload(runner)["world_context_provenance"]
        self.assertEqual(world_provenance["world_seed_status"], "unavailable")
        self.assertIsNone(world_provenance["world_seed_hash"])
        self.assertIsNone(world_provenance["world_seed_version"])
        self.assertEqual(world_provenance["fallback_status"], "seed_data_unavailable")
        self.assertIs(world_provenance["read_only"], True)
    def test_attempt_metadata_and_kwargs_are_scalar_only(self) -> None:
        pack = _build_pack()
        handoff, _ = self._ready_handoff(world_context=pack)
        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        _, attempt_metadata, kwargs = runner.calls[0]
        for payload in (
            json.dumps(attempt_metadata, sort_keys=True),
            json.dumps(kwargs, sort_keys=True),
        ):
            self.assertEqual(_scan_forbidden(payload), [])
            self.assertNotIn(SEED_HOOK, payload)
            self.assertNotIn(CAMPAIGN_TITLE, payload)

    def test_serialized_adapter_result_is_scalar_only(self) -> None:
        pack = _build_pack()
        handoff, _ = self._ready_handoff(world_context=pack)
        runner = FakeAuthorRunner()
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        serialized = runtime.serialize_adaptation_authoring_result(result)
        self.assertEqual(_scan_forbidden(serialized), [])
        self.assertIn(SELECTED_MODULE, serialized)
        # Round trip stays valid and canonical.
        validated = runtime.validate_adaptation_authoring_result(
            json.loads(serialized)
        )
        self.assertTrue(validated["valid"], validated["diagnostics"])


class TestPersistedAttemptReports(_ProjectLocalScratchMixin, unittest.TestCase):
    """Persisted failure reports carry provenance and never claim grounding."""

    def test_failure_report_carries_available_provenance(self) -> None:
        pack = _build_pack()
        provenance = build_world_context_provenance(pack)
        handoff, workspace = self._ready_handoff(world_context=pack)
        runner = FakeAuthorRunner(refused=True)
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        attempt_id = result["attempt"]["attempt_id"]

        failure_artifact = load_adaptation_artifact(
            workspace, attempt_id, ARTIFACT_KIND_FAILURE_REPORT
        )
        self.assertIsNotNone(failure_artifact)
        self.assertEqual(
            failure_artifact["provenance"]["world_context_provenance"], provenance
        )
        self.assertEqual(
            failure_artifact["provenance"]["world_context_status"], "available"
        )
        self.assertEqual(_scan_forbidden(json.dumps(failure_artifact, sort_keys=True)), [])
        self._assert_no_module_side_effects()

    def test_failure_report_carries_unavailable_fallback(self) -> None:
        handoff, workspace = self._ready_handoff()
        runner = FakeAuthorRunner(refused=True)
        result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        attempt_id = result["attempt"]["attempt_id"]
        failure_artifact = load_adaptation_artifact(
            workspace, attempt_id, ARTIFACT_KIND_FAILURE_REPORT
        )
        self.assertIsNotNone(failure_artifact)
        report_provenance = failure_artifact["provenance"]["world_context_provenance"]
        self.assertEqual(report_provenance["fallback_status"], "seed_data_unavailable")
        self.assertEqual(report_provenance["world_seed_status"], "unavailable")
        self.assertIsNone(report_provenance["world_seed_hash"])
        self.assertEqual(
            failure_artifact["provenance"]["world_context_status"], "unavailable"
        )
        self.assertEqual(_scan_forbidden(json.dumps(failure_artifact, sort_keys=True)), [])
        self._assert_no_module_side_effects()

    def test_text_failure_report_carries_fallback_provenance(self) -> None:
        manifest = self._ready_manifest()
        runner = FakeAuthorRunner(refused=True)
        result = runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=runner, model="mock-adaptation-model"
        )
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertTrue(result["authoring"]["failure_artifact_persisted"])
        attempt_id = result["attempt"]["attempt_id"]
        workspace_path = self._workspace_path(manifest)
        failure_artifact = load_adaptation_artifact(
            workspace_path, attempt_id, ARTIFACT_KIND_FAILURE_REPORT
        )
        self.assertIsNotNone(failure_artifact)
        report_provenance = failure_artifact["provenance"]["world_context_provenance"]
        self.assertEqual(report_provenance["fallback_status"], "seed_data_unavailable")
        self.assertEqual(report_provenance["world_seed_status"], "unavailable")
        self.assertFalse((REPO_ROOT / "modules" / "Sunken_Lighthouse").exists())


class TestBlockedAdapterFallbackProvenance(_ProjectLocalScratchMixin, unittest.TestCase):
    """Blocked adapter results carry canonical unavailable provenance."""

    def test_failed_closed_upload_handoff_block_carries_fallback(self) -> None:
        workspace = _make_workspace(self.scratch)
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="awaiting_review",
            job_id="job-1",
        )
        self.assertEqual(handoff["status"], runtime.HANDOFF_STATUS_FAILED_CLOSED)
        result = runtime.run_upload_adaptation_authoring(handoff, model="mock-adaptation-model")
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertEqual(result["world_context"], build_world_context_provenance(None))
        self.assertEqual(result["world_context"]["fallback_status"], "seed_data_unavailable")

    def test_invalid_envelope_block_carries_fallback(self) -> None:
        handoff, _ = self._ready_handoff()
        tampered = deepcopy(handoff)
        tampered["envelope"] = {"contract_version": "bogus", "status": "invalid"}
        result = runtime.run_upload_adaptation_authoring(tampered, model="mock-adaptation-model")
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertEqual(result["world_context"], build_world_context_provenance(None))
        codes = [item["code"] for item in result["diagnostics"]]
        self.assertIn("envelope_invalid", codes)

    def test_failed_closed_text_manifest_block_carries_fallback(self) -> None:
        manifest = runtime.build_text_description_attempt_workspace(
            "Sunken_Lighthouse",
            "",
            job_id="text-job-1",
            workspace_root="tmp/toolkit_adaptation_world_context_handoff"
            + "/"
            + self.scratch.name
            + "/text_workspaces",
        )
        self.assertEqual(manifest["status"], runtime.TEXT_DESCRIPTION_WORKSPACE_STATUS_FAILED_CLOSED)
        result = runtime.run_text_description_adaptation_authoring(manifest, model="mock-adaptation-model")
        self.assertEqual(result["status"], runtime.AUTHORING_ADAPTER_STATUS_BLOCKED)
        self.assertEqual(result["world_context"], build_world_context_provenance(None))
        self.assertEqual(result["world_context"]["fallback_status"], "seed_data_unavailable")

    def test_blocked_result_round_trip_is_canonical(self) -> None:
        workspace = _make_workspace(self.scratch)
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="awaiting_review",
            job_id="job-1",
        )
        result = runtime.run_upload_adaptation_authoring(handoff, model="mock-adaptation-model")
        validated = runtime.validate_adaptation_authoring_result(
            json.loads(runtime.serialize_adaptation_authoring_result(result))
        )
        # Blocked results must still carry canonical world-context provenance.
        self.assertNotIn("world_context_missing", validated["diagnostics"])
        self.assertNotIn("world_context_not_canonical", validated["diagnostics"])


class TestNoProviderNetworkAndHygiene(_ProjectLocalScratchMixin, unittest.TestCase):
    """The runtime boundary never touches providers, network, or OS temp."""

    FORBIDDEN_TOKENS = (
        "tempfile",
        "/tmp",
        "socketio",
        "start_build",
        "simulate_build_process",
        "web_interface",
        "world_registry.json",
        "campaign.json",
        "requests.get",
        "urllib.request",
        "OpenAI(",
    )

    def test_runtime_module_has_no_provider_network_or_os_temp_tokens(self) -> None:
        source = RUNTIME_MODULE_PATH.read_text(encoding="utf-8")
        found = [token for token in self.FORBIDDEN_TOKENS if token in source]
        self.assertEqual(found, [])

    def test_author_module_has_no_os_temp_or_network_tokens(self) -> None:
        source = AUTHOR_MODULE_PATH.read_text(encoding="utf-8")
        found = [
            token
            for token in ("tempfile", "/tmp", "requests.", "urllib.request", "socketio")
            if token in source
        ]
        self.assertEqual(found, [])

    def test_injected_runner_is_used_for_both_input_paths(self) -> None:
        pack = _build_pack()
        handoff, _ = self._ready_handoff(world_context=pack)
        upload_runner = FakeAuthorRunner()
        upload_result = runtime.run_upload_adaptation_authoring(
            handoff, author_runner=upload_runner, model="mock-adaptation-model"
        )
        self.assertEqual(upload_result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(len(upload_runner.calls), 1)

        manifest = self._ready_manifest(world_context=pack)
        text_runner = FakeAuthorRunner()
        text_result = runtime.run_text_description_adaptation_authoring(
            manifest, author_runner=text_runner, model="mock-adaptation-model"
        )
        self.assertEqual(text_result["status"], runtime.AUTHORING_ADAPTER_STATUS_READY)
        self.assertEqual(len(text_runner.calls), 1)

    def test_changed_files_are_ascii_only(self) -> None:
        for path in (RUNTIME_MODULE_PATH, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.isascii(), f"non-ASCII content in {path}")

    def test_test_file_has_spdx_header(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# SPDX-FileCopyrightText: 2024 MoonlightByte"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
