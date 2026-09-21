# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - Toolkit Adaptation End-to-End Regression Suite
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free task 10.1 integration coverage for the LLM adaptation lane.
The suite uses bounded fixture inputs, injected provider clients, isolated
project-local temporary roots, and network tripwires. It never publishes to
the repository's real modules, registry, or campaign files.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config
import utils.toolkit_adaptation_auditor as auditor_runner_module
import utils.toolkit_adaptation_author as author_runner_module
import utils.toolkit_adaptation_revision as adaptation_revision
import utils.toolkit_adaptation_staging as adaptation_staging
import utils.homebrewery_adventure_writer as adventure_writer
import web.extensions.toolkit_module_finisher as module_finisher
from utils.toolkit_adaptation_artifacts import (
    ARTIFACT_KIND_ADAPTATION_DOSSIER,
    ARTIFACT_KIND_BUILD_RESULT,
    ARTIFACT_KIND_PUBLICATION_REPORT,
    BUILD_STATUS_PASSED,
    build_adaptation_artifact,
    get_adaptation_artifact_path,
    load_adaptation_artifact,
    persist_adaptation_artifact,
)
from utils.toolkit_adaptation_auditor import (
    ADAPTATION_AUDITOR_CONTRACT_VERSION,
    run_llm_adaptation_auditor,
)
from utils.toolkit_adaptation_authoring import run_adaptation_authoring
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LEGACY_ACCURATE_INGEST,
    BUILD_MODE_LLM_ADAPTATION,
    adaptation_enabled,
    is_legacy_accurate_ingest_build_mode,
    resolve_adaptation_routing,
)
from utils.toolkit_adaptation_dossier import (
    ADAPTATION_MODE_LLM,
    ADAPTATION_NOTICE,
    parse_adaptation_dossier,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_failure_packet import (
    build_adaptation_failure_packet,
    validate_adaptation_failure_packet,
)
from utils.toolkit_adaptation_gate_composer import (
    GATE_MECHANICAL_CLOSURE,
    GATE_READINESS,
    GATE_REPORT_AGREEMENT,
    GATE_SCHEMA,
    GATE_SEMANTIC_AUTHORITY,
    GATE_SEMANTIC_PROBES,
)
from utils.toolkit_adaptation_markdown_quality import (
    check_adaptation_markdown_quality,
)
from utils.toolkit_adaptation_provenance import (
    build_adaptation_provenance,
    load_adaptation_module_provenance,
    render_adaptation_provenance_markdown,
    validate_adaptation_provenance,
)
from utils.toolkit_adaptation_publication_transaction import (
    capture_adaptation_publication_snapshot,
    rollback_adaptation_publication,
)
from utils.toolkit_adaptation_source_context import build_adaptation_source_context
from utils.toolkit_adaptation_world_context import (
    WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE,
    WORLD_CONTEXT_SEED_STATUS_AVAILABLE,
    WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE,
    WORLD_CONTEXT_STATUS_AVAILABLE,
    WORLD_CONTEXT_STATUS_FALLBACK,
    build_world_context_provenance,
    build_world_narrative_context,
)
from utils.toolkit_report_agreement import compose_adaptation_report_agreement
from web.web_interface import resolve_adventure_markdown_download


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "scripts" / "fixtures"
DOSSIER_PATH = FIXTURE_DIR / "toolkit_adaptation_dossier_valid.json"
CATALOGUE_PATH = FIXTURE_DIR / "toolkit_adaptation_catalogue.md"
SOURCE_PATH = "scripts/fixtures/toolkit_adaptation_catalogue.md"
SOURCE_HASH = hashlib.sha256(CATALOGUE_PATH.read_bytes()).hexdigest()
MODULE_SLUG = "Lantern_Market_Adaptation"


def _write_json(path: Path, payload: object) -> None:
    """Write a bounded JSON fixture below the isolated test root."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_dossier() -> dict:
    """Load the repository fixture without embedding unbounded source text."""
    dossier = json.loads(DOSSIER_PATH.read_text(encoding="utf-8"))
    dossier["source_hash"] = SOURCE_HASH
    return dossier


def _blocked_provider(*args, **kwargs):
    """Fail immediately if an un-injected provider client is requested."""
    raise AssertionError("live provider client creation is forbidden in task 10.1")


def _blocked_network(*args, **kwargs):
    """Fail immediately if a real network operation is attempted."""
    raise AssertionError("live network access is forbidden in task 10.1")


class _FakeCompletions:
    """Deterministic injected provider seam used by author and auditor tests."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.response


class _FakeClient:
    """OpenAI-shaped fixture client with no network implementation."""

    def __init__(self, response):
        self.completions = _FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)


def _provider_response(content: str, model: str) -> SimpleNamespace:
    message = SimpleNamespace(content=content, refusal=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(
        choices=[choice],
        model=model,
        id="fixture-provider-response",
    )


def _world_inputs(with_seed: bool = True):
    campaign_model = {
        "campaign_id": "fixture-campaign",
        "version": 3,
        "summary": "A frontier world balances old pacts and new roads.",
        "tone": "mystery with resilient hope",
        "themes": ["broken pacts", "hidden roads"],
    }
    pressures = [
        {
            "thread_id": "thread-01",
            "thread_type": "mystery",
            "summary": "A sealed road is opening below the hills.",
            "priority": 80,
        }
    ]
    registry_context = {
        "worldName": "Fixture World",
        "registryVersion": "2.0.0",
        "modules": {},
    }
    seeds = []
    if with_seed:
        seeds.append(
            {
                "seed_id": "seed-01",
                "module_slug": MODULE_SLUG,
                "seed_type": "continuity",
                "content": {
                    "summary": "A missing shipment connects the market to the frontier.",
                    "hook": "A sealed lantern carries an unfamiliar crest.",
                },
            }
        )
    return campaign_model, pressures, registry_context, seeds


def _world_pack(with_seed: bool = True) -> dict:
    campaign_model, pressures, registry_context, seeds = _world_inputs(with_seed)
    return build_world_narrative_context(
        campaign_model,
        pressures,
        registry_context,
        seeds,
        selected_module=MODULE_SLUG,
        seed_version="fixture.v2" if with_seed else None,
    )


def _passing_gate_reports() -> dict:
    domains = {
        domain: {"status": "pass", "effective_status": "pass"}
        for domain in (
            GATE_SCHEMA,
            GATE_READINESS,
            GATE_MECHANICAL_CLOSURE,
            GATE_SEMANTIC_AUTHORITY,
            GATE_SEMANTIC_PROBES,
        )
    }
    domains[GATE_REPORT_AGREEMENT] = {
        "status": "pass",
        "effective_status": "pass",
        "playable_publication_status": "pass",
        "agreement": {"playable_publication_status": "pass"},
    }
    return {
        "status": "pass",
        "adaptation_status": "ready_for_publication",
        "playable_status": "pass",
        "candidate_eligible": True,
        "gates": domains,
        "publication": {
            "authority": "python",
            "attempted": False,
            "allowed": False,
        },
    }


class AdaptationIntegrationFixture(unittest.TestCase):
    """Shared isolated root and provider/network tripwires."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_task_10_1_",
        )
        self.root = Path(self.temp_dir.name)
        self.original_cwd = Path.cwd()
        os.chdir(self.root)
        self.workspace = self.root / "tmp" / "adaptation-artifacts"
        self.source_context = build_adaptation_source_context(
            CATALOGUE_PATH.read_text(encoding="utf-8"),
            source_path=SOURCE_PATH,
            source_hash=SOURCE_HASH,
            source_title="The Lantern Catalogue",
            profile_override="catalogue",
        )
        self.world_pack = _world_pack()
        self.protected_paths = (
            REPO_ROOT / "modules" / "world_registry.json",
            REPO_ROOT / "modules" / "campaign.json",
        )
        self.protected_before = {
            path: path.read_bytes() for path in self.protected_paths if path.exists()
        }

        self.tripwire_patchers = [
            patch.object(author_runner_module, "create_chat_client", side_effect=_blocked_provider),
            patch.object(auditor_runner_module, "create_chat_client", side_effect=_blocked_provider),
            patch("utils.ai_client_factory.create_chat_client", side_effect=_blocked_provider),
            patch.object(socket, "socket", side_effect=_blocked_network),
            patch.object(socket, "create_connection", side_effect=_blocked_network),
            patch.object(urllib.request, "urlopen", side_effect=_blocked_network),
            patch.object(http.client.HTTPConnection, "request", side_effect=_blocked_network),
            patch.object(http.client.HTTPSConnection, "request", side_effect=_blocked_network),
        ]
        for patcher in self.tripwire_patchers:
            patcher.start()

    def tearDown(self) -> None:
        try:
            for patcher in reversed(self.tripwire_patchers):
                patcher.stop()
        finally:
            os.chdir(self.original_cwd)
            self.assertEqual(
                self.protected_before,
                {
                    path: path.read_bytes()
                    for path in self.protected_before
                    if path.exists()
                },
            )
            self.temp_dir.cleanup()

    def _author(self) -> tuple[dict, _FakeClient]:
        dossier = _load_dossier()
        model = "provider-free-author"
        client = _FakeClient(_provider_response(json.dumps(dossier), model))
        result = run_adaptation_authoring(
            self.source_context,
            workspace=self.workspace,
            world_context=self.world_pack,
            job_id="task-10-1-author",
            attempt_number=1,
            source_format="markdown",
            rights_metadata={
                "rights_class": "user_authored",
                "rights_basis": "Operator attested that the uploaded source is user-authored.",
                "rights_review_required": False,
                "rights_review_status": "not_required",
            },
            model=model,
            provider="fixture",
            client=client,
            parameter_resolver=lambda task_id, requested_model: {
                "model": requested_model,
                "temperature": 0.2,
            },
            timeout_seconds=1,
        )
        return result, client

    def _provenance(self, author_result: dict) -> dict:
        attempt = dict(author_result["attempt_metadata"])
        attempt.update(
            {
                "source_path": SOURCE_PATH,
                "source_format": "markdown",
                "source_profile": "catalogue",
                "model_metadata": dict(author_result["model_metadata"]),
            }
        )
        return build_adaptation_provenance(
            dossier=author_result["dossier"],
            provenance=attempt,
            world_context=self.world_pack,
            module_slug=MODULE_SLUG,
        )

    def _write_module_fixture(self, module_dir: Path) -> None:
        """Create a small registry and Markdown-compatible staged module."""
        _write_json(
            module_dir / "module_context.json",
            {
                "module_id": MODULE_SLUG,
                "mainObjective": "Recover the missing lantern shipment.",
                "author": "NEQ-TTRPG fixture builder",
                "license": "Fair Source fixture",
                "areas": {"ADP001": {}},
                "npcs": {
                    "Mira Vell": {
                        "description": "A worried lantern keeper who asks for help.",
                        "role": "Lantern keeper",
                        "faction": "Market community",
                    }
                },
            },
        )
        _write_json(
            module_dir / "module_plot.json",
            {
                "mainObjective": "Recover the missing lantern shipment.",
                "plotPoints": [
                    {
                        "id": "PP001",
                        "name": "The Missing Shipment",
                        "description": "The market keeper asks the party to trace the missing shipment.",
                    },
                    {
                        "id": "PP002",
                        "name": "The Sealed Lantern",
                        "description": "The party chooses whether to negotiate or pursue the hidden buyer.",
                    },
                ],
            },
        )
        _write_json(
            module_dir / "areas" / "ADP001.json",
            {
                "areaId": "ADP001",
                "areaName": "Lantern Market",
                "areaDescription": "A covered market of glass, brass, and colored flame.",
                "areaType": "settlement",
                "dangerLevel": "low",
                "recommendedLevel": 1,
                "climate": "temperate",
                "terrain": "urban",
                "locations": [
                    {
                        "locationId": "ADP001L01",
                        "locationName": "Lantern Market Gate",
                        "description": "A crowded gate opens onto stalls and a worried keeper.",
                        "dmInstructions": "Let the party ask questions, inspect the empty crate, or follow the lantern trail.",
                        "connectivity": [],
                    },
                    {
                        "locationId": "ADP001L02",
                        "locationName": "Lanternwright Stall",
                        "description": "A narrow stall displays travel lights and one sealed black lantern.",
                        "dmInstructions": "Offer a negotiation, an investigation, or a careful chase through the market.",
                        "connectivity": ["ADP001L01"],
                    },
                ],
            },
        )

    def _prepare_candidate(self) -> dict:
        author_result, client = self._author()
        self.assertTrue(author_result["handoff_ready"], author_result)
        target = adaptation_staging.create_adaptation_staging_target(
            SOURCE_HASH,
            attempt_id=author_result["attempt_id"],
            attempt_number=1,
            revision_number=0,
            job_id="task-10-1-publication",
            source_path=SOURCE_PATH,
            module_slug=MODULE_SLUG,
            staging_root="tmp/adaptation-staging",
            repo_root=self.root,
        )
        module_dir = self.root / target["path"]
        self._write_module_fixture(module_dir)
        attempt_metadata = {
            **dict(author_result["attempt_metadata"]),
            "source_path": SOURCE_PATH,
            "source_format": "markdown",
            "source_profile": "catalogue",
        }
        gates = _passing_gate_reports()
        self.assertEqual(gates["status"], "pass", gates)
        provenance = self._provenance(author_result)
        completed_target = adaptation_staging.update_adaptation_staging_target(
            target,
            adaptation_staging.STAGING_STATE_COMPLETED,
            repo_root=self.root,
            output_hash="e" * 64,
        )
        build_artifact = build_adaptation_artifact(
            ARTIFACT_KIND_BUILD_RESULT,
            attempt_id=author_result["attempt_id"],
            source_title=author_result["dossier"]["source_title"],
            source_hash=SOURCE_HASH,
            source_path=SOURCE_PATH,
            attempt_number=1,
            revision_number=0,
            rights_class=author_result["dossier"]["rights_class"],
            rights_basis=author_result["dossier"]["rights_basis"],
            rights_review_required=author_result["dossier"]["rights_review_required"],
            rights_review_status=author_result["dossier"]["rights_review_status"],
            source_profile=author_result["dossier"]["source_profile"],
            source_format="markdown",
            model_metadata=provenance["model_metadata"],
            world_context_provenance=provenance["world_context_provenance"],
            status=BUILD_STATUS_PASSED,
            payload={
                "build_status": BUILD_STATUS_PASSED,
                "staging": {
                    "path": completed_target["path"],
                    "isolated": True,
                    "target_kind": "staging",
                },
                "gate_summary": {"status": "pass", "candidate_eligible": True},
                "module_artifacts": [],
                "module_slug": MODULE_SLUG,
                "output_hash": "e" * 64,
                "source_ref": {"path": SOURCE_PATH, "sha256": SOURCE_HASH},
            },
        )
        self.assertTrue(persist_adaptation_artifact(self.workspace, build_artifact))
        return {
            "author": author_result,
            "client": client,
            "target": completed_target,
            "module_dir": module_dir,
            "gates": gates,
            "provenance": provenance,
            "build_artifact": build_artifact,
        }

    def _publish_candidate(self) -> dict:
        candidate = self._prepare_candidate()
        registry_path = self.root / "modules" / "world_registry.json"
        campaign_path = self.root / "modules" / "campaign.json"
        _write_json(
            registry_path,
            {
                "worldName": "Fixture World",
                "registryVersion": "2.0.0",
                "modules": {},
                "areas": {},
            },
        )
        _write_json(
            campaign_path,
            {"active": True, "availableModules": []},
        )
        snapshot_result = capture_adaptation_publication_snapshot(
            MODULE_SLUG,
            registry_path=registry_path,
            campaign_path=campaign_path,
            area_ids=["ADP001"],
        )
        self.assertEqual(snapshot_result["status"], "success", snapshot_result)

        with patch.object(adventure_writer, "_llm_intro_narrative", return_value=None), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(adventure_writer, "_llm_area_overview", return_value=None):
            result = module_finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode=ADAPTATION_MODE_LLM,
                adaptation_gates=candidate["gates"],
                adaptation_staging_target=candidate["target"],
                adaptation_module_dir=str(candidate["module_dir"]),
                adaptation_provenance=candidate["provenance"],
                adaptation_artifact_workspace=str(self.workspace),
            )
        candidate.update(
            {
                "result": result,
                "registry_path": registry_path,
                "campaign_path": campaign_path,
                "snapshot": snapshot_result["snapshot"],
            }
        )
        return candidate


class TestAdaptationAuthorAndWorldBoundary(AdaptationIntegrationFixture):
    """Cover authoring, dossier validation, seed fallback, and isolation."""

    def test_provider_free_authoring_persists_valid_dossier_and_provenance(self):
        result, client = self._author()

        self.assertEqual(result["status"], "ready", result)
        self.assertTrue(result["handoff_ready"])
        self.assertFalse(result["completed"])
        self.assertFalse(result["registry_mutated"])
        self.assertEqual(len(client.completions.calls), 1)
        self.assertNotIn("api_key", json.dumps(client.completions.calls).lower())

        dossier_result = validate_adaptation_dossier(result["dossier"])
        self.assertTrue(dossier_result["valid"], dossier_result)
        self.assertTrue(dossier_result["build_ready"])
        self.assertTrue(parse_adaptation_dossier(json.dumps(result["dossier"]))["valid"])
        self.assertEqual(result["dossier"]["source_profile"], "catalogue")
        self.assertEqual(result["dossier"]["omitted_source_elements"][0]["source_ref"], "catalogue.sections.listings")

        dossier_artifact = load_adaptation_artifact(
            self.workspace,
            result["attempt_id"],
            ARTIFACT_KIND_ADAPTATION_DOSSIER,
        )
        self.assertIsNotNone(dossier_artifact)
        self.assertEqual(dossier_artifact["provenance"]["source_hash"], SOURCE_HASH)
        self.assertEqual(
            dossier_artifact["provenance"]["world_seed_version"],
            "fixture.v2",
        )
        self.assertFalse(
            dossier_artifact["provenance"]["world_context_provenance"]["canon_write_allowed"]
        )
        self.assertFalse((self.root / "modules").exists())

        provenance = self._provenance(result)
        validation = validate_adaptation_provenance(
            provenance,
            require_source_identity=True,
        )
        self.assertTrue(validation["valid"], validation)
        self.assertEqual(provenance["adaptation_notice"], ADAPTATION_NOTICE)
        self.assertEqual(provenance["source_fidelity_status"], "not_applicable")
        self.assertEqual(provenance["fidelity_claim"], "non_literal_adaptation")
        self.assertIn(ADAPTATION_NOTICE, render_adaptation_provenance_markdown(provenance))

    def test_world_seed_fallback_is_explicit_and_makes_no_grounding_claim(self):
        available = _world_pack(with_seed=True)
        self.assertEqual(available["status"], WORLD_CONTEXT_STATUS_AVAILABLE)
        self.assertEqual(available["world_seed_status"], WORLD_CONTEXT_SEED_STATUS_AVAILABLE)
        self.assertTrue(available["read_only"])
        self.assertTrue(available["provider_free"])
        self.assertRegex(available["world_seed_hash"], r"^[0-9a-f]{64}$")

        fallback = _world_pack(with_seed=False)
        self.assertEqual(fallback["status"], WORLD_CONTEXT_STATUS_FALLBACK)
        self.assertEqual(fallback["fallback_status"], WORLD_CONTEXT_FALLBACK_SEED_UNAVAILABLE)
        self.assertEqual(fallback["world_seed_status"], WORLD_CONTEXT_SEED_STATUS_UNAVAILABLE)
        fallback_provenance = build_world_context_provenance(fallback)
        self.assertIsNone(fallback_provenance["world_seed_version"])
        self.assertIsNone(fallback_provenance["world_seed_hash"])
        self.assertFalse(fallback_provenance["canon_write_allowed"])
        self.assertNotIn("approved_module_seeds", json.dumps(fallback_provenance))

    def test_disabled_rollout_keeps_legacy_route_isolated(self):
        # The operator rollout flag may be enabled in model_config.py.  This
        # test explicitly exercises the disabled compatibility contract rather
        # than asserting a deployment default.
        with patch.object(model_config, "ENABLE_LLM_ADAPTATION", False):
            self.assertFalse(adaptation_enabled())
            disabled = resolve_adaptation_routing(
                BUILD_MODE_LLM_ADAPTATION,
                enabled_override=False,
            )
            self.assertEqual(disabled["status"], "legacy")
            self.assertEqual(disabled["mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
            self.assertEqual(disabled["reason"], "disabled")

        legacy = resolve_adaptation_routing(
            "packet_workspace_v1",
            enabled_override=True,
        )
        self.assertEqual(legacy["status"], "legacy")
        self.assertEqual(legacy["mode"], BUILD_MODE_LEGACY_ACCURATE_INGEST)
        self.assertTrue(is_legacy_accurate_ingest_build_mode("packet_workspace_v1"))
        enabled = resolve_adaptation_routing(
            BUILD_MODE_LLM_ADAPTATION,
            enabled_override=True,
        )
        self.assertEqual(enabled["status"], "enabled")
        self.assertEqual(enabled["mode"], BUILD_MODE_LLM_ADAPTATION)

    def test_suite_is_executed_with_project_venv(self):
        expected = REPO_ROOT / ".venv" / "bin" / "python"
        self.assertEqual(
            Path(sys.executable),
            expected,
            "run adaptation regression suites with .venv/bin/python",
        )


class TestAdaptationRevisionBoundary(AdaptationIntegrationFixture):
    """Cover a bounded semantic revision and fresh staging without publication."""

    def test_revision_uses_fresh_target_and_keeps_registry_and_campaign_untouched(self):
        author_result, _ = self._author()
        initial_target = adaptation_staging.create_adaptation_staging_target(
            SOURCE_HASH,
            attempt_id=author_result["attempt_id"],
            attempt_number=1,
            revision_number=0,
            job_id="task-10-1-revision",
            source_path=SOURCE_PATH,
            module_slug=MODULE_SLUG,
            staging_root="tmp/adaptation-staging",
            repo_root=self.root,
        )
        initial_target = adaptation_staging.update_adaptation_staging_target(
            initial_target,
            adaptation_staging.STAGING_STATE_BUILDING,
            repo_root=self.root,
        )
        attempt_metadata = {
            "attempt_id": author_result["attempt_id"],
            "attempt_number": 1,
            "revision_number": 0,
            "stage": "build",
            "stage_id": initial_target["stage_id"],
            "source_title": "The Lantern Catalogue",
            "source_hash": SOURCE_HASH,
            "source_path": SOURCE_PATH,
            "source_profile": "catalogue",
            "source_format": "markdown",
            "adaptation_mode": ADAPTATION_MODE_LLM,
            "rights_class": "user_authored",
            "rights_basis": "Operator attested that the uploaded source is user-authored.",
            "rights_review_required": False,
            "rights_review_status": "not_required",
            "model_metadata": {"provider": "fixture", "model": "provider-free"},
        }
        failure_packet = build_adaptation_failure_packet(
            {
                "gates": {
                    GATE_SCHEMA: {"status": "pass"},
                    GATE_READINESS: {"status": "pass"},
                    GATE_MECHANICAL_CLOSURE: {"status": "pass"},
                    GATE_SEMANTIC_AUTHORITY: {
                        "status": "blocked",
                        "errors": ["one destination remains ambiguous"],
                    },
                    GATE_SEMANTIC_PROBES: {"status": "pass"},
                    GATE_REPORT_AGREEMENT: {"status": "pass"},
                }
            },
            attempt_metadata=attempt_metadata,
            staging_target=initial_target,
            source_context={
                "source_ref": {"path": SOURCE_PATH, "sha256": SOURCE_HASH}
            },
            module_summaries=[
                {
                    "module_slug": MODULE_SLUG,
                    "status": "blocked",
                    "summary": "A bounded staged candidate needs semantic revision.",
                }
            ],
            publication_goals=["schema", "readiness", "semantic_authority"],
            failure_classification={
                "failure_class": "semantic",
                "failure_group": "content",
                "classification_status": "revision_eligible",
                "code": "semantic_authority_blocked",
                "message": "A bounded semantic revision is allowed.",
                "semantic_revision_eligible": True,
                "consumes_semantic_revision_budget": True,
                "revision_budget": {
                    "current_revision": 0,
                    "max_revisions": 1,
                    "decision": "eligible",
                },
            },
            world_context_provenance=build_world_context_provenance(self.world_pack),
            repo_root=self.root,
        )
        self.assertTrue(validate_adaptation_failure_packet(failure_packet, repo_root=self.root)["valid"])

        auditor_calls = []
        build_calls = []
        dossier = author_result["dossier"]

        def auditor(request_packet, **kwargs):
            auditor_calls.append(copy.deepcopy(request_packet))
            packet_metadata = request_packet["attempt_metadata"]
            response = {
                "version": ADAPTATION_AUDITOR_CONTRACT_VERSION,
                "decision": "revise",
                "reason": "The catalogue adaptation can use one clearer canonical destination.",
                "attempt_id": packet_metadata["attempt_id"],
                "stage": packet_metadata["stage"],
                "revision_number": packet_metadata["revision_number"],
                "source_hash": packet_metadata["source_hash"],
                "model_metadata": copy.deepcopy(packet_metadata["model_metadata"]),
                "gate_evidence_refs": [],
                "revised_dossier": copy.deepcopy(dossier),
            }
            client = _FakeClient(
                _provider_response(json.dumps(response), "provider-free")
            )
            parsed = run_llm_adaptation_auditor(
                request_packet,
                client=client,
                model="provider-free",
                parameter_resolver=lambda task_id, model: {"model": model},
                timeout_seconds=1,
            )
            self.assertEqual(len(client.completions.calls), 1)
            return parsed

        def build_callback(staging_target, revised_dossier, directive, **kwargs):
            build_calls.append(
                {
                    "target": copy.deepcopy(staging_target),
                    "directive": copy.deepcopy(directive),
                }
            )
            stage = self.root / staging_target["path"]
            self._write_module_fixture(stage)
            return {"status": "success", "output_hash": "f" * 64}

        registry_path = self.root / "modules" / "world_registry.json"
        campaign_path = self.root / "modules" / "campaign.json"
        _write_json(registry_path, {"modules": {"Sentinel": {}}, "areas": {}})
        _write_json(campaign_path, {"active": True, "availableModules": ["Sentinel"]})
        sentinel_before = {
            registry_path: registry_path.read_bytes(),
            campaign_path: campaign_path.read_bytes(),
        }

        result = adaptation_revision.run_adaptation_final_revision(
            failure_packet,
            workspace=self.workspace,
            repo_root=self.root,
            staging_root="tmp/adaptation-staging",
            module_slug=MODULE_SLUG,
            current_dossier=dossier,
            max_revisions=1,
            auditor_runner=auditor,
            build_callback=build_callback,
        )

        self.assertEqual(result["status"], adaptation_revision.REVISION_STATUS_REVISION_PASSED, result)
        self.assertEqual(result["revision_number"], 1)
        self.assertEqual(len(auditor_calls), 1)
        self.assertEqual(len(build_calls), 1)
        self.assertEqual(build_calls[0]["target"]["revision_number"], 1)
        self.assertIn("revision_001", build_calls[0]["target"]["path"])
        self.assertNotEqual(build_calls[0]["target"]["path"], initial_target["path"])
        self.assertEqual(result["staging_target"]["completion_state"], "completed")
        self.assertTrue(result["revision_report_persisted"])
        self.assertTrue(result["build_result_persisted"])
        self.assertTrue(result["proposal_ledger_persisted"])
        self.assertEqual(
            sentinel_before,
            {
                registry_path: registry_path.read_bytes(),
                campaign_path: campaign_path.read_bytes(),
            },
        )

        cleanup = adaptation_staging.cleanup_adaptation_staging_target(
            result["staging_target"],
            repo_root=self.root,
        )
        self.assertEqual(cleanup["status"], "cleaned")
        self.assertFalse(self.root.joinpath(result["staging_target"]["path"]).exists())
        self.assertTrue(self.root.joinpath(initial_target["path"]).exists())


class TestAdaptationPublicationBoundary(AdaptationIntegrationFixture):
    """Cover gate ordering, Markdown/download, reports, registry, and rollback."""

    def test_publication_is_python_ordered_and_serves_persisted_markdown(self):
        candidate = self._publish_candidate()
        result = candidate["result"]
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(
            result["publication_order"],
            [
                "schema",
                "readiness",
                "mechanical_closure",
                "semantic_authority",
                "semantic_probes",
                "report_agreement",
                "markdown",
                "registry",
            ],
        )
        self.assertTrue(result["registry_is_final_stateful_publication"])
        self.assertTrue(result["python_authoritative"])
        self.assertEqual(result["stages"]["module_summary"]["status"], "success")
        self.assertTrue(result["stages"]["module_summary"]["quality"]["valid"])
        self.assertEqual(result["stages"]["registry"]["status"], "success")
        self.assertEqual(result["stages"]["campaign_sync"]["status"], "success")

        summary_path = candidate["module_dir"] / "MODULE_SUMMARY.md"
        summary = summary_path.read_text(encoding="utf-8")
        quality = check_adaptation_markdown_quality(summary, module_slug=MODULE_SLUG)
        self.assertTrue(quality["valid"], quality)
        self.assertIn(ADAPTATION_NOTICE, summary)
        self.assertIn(SOURCE_HASH, summary)
        self.assertIn("World seed provenance", summary)

        module_provenance = load_adaptation_module_provenance(candidate["module_dir"])
        self.assertIsNotNone(module_provenance)
        self.assertEqual(module_provenance["adaptation_notice"], ADAPTATION_NOTICE)
        self.assertEqual(module_provenance["source_fidelity_status"], "not_applicable")
        self.assertEqual(module_provenance["world_seed_version"], "fixture.v2")

        registry = json.loads(candidate["registry_path"].read_text(encoding="utf-8"))
        campaign = json.loads(candidate["campaign_path"].read_text(encoding="utf-8"))
        self.assertIn(MODULE_SLUG, registry["modules"])
        self.assertEqual(registry["areas"]["ADP001"]["module"], MODULE_SLUG)
        self.assertIn(MODULE_SLUG, campaign["availableModules"])

        published = load_adaptation_artifact(
            self.workspace,
            candidate["author"]["attempt_id"],
            ARTIFACT_KIND_PUBLICATION_REPORT,
        )
        self.assertIsNotNone(published)
        self.assertEqual(published["payload"]["publication_status"], "published")
        self.assertEqual(published["report_freshness"]["state"], "current")
        self.assertEqual(result["adaptation_report_agreement"]["status"], "pass")

        stale_build = copy.deepcopy(candidate["build_artifact"])
        stale_build["report_freshness"]["state"] = "stale"
        stale_build["report_freshness"]["authoritative"] = False
        stale_agreement = compose_adaptation_report_agreement(
            stale_build,
            published,
            expected_attempt_id=candidate["author"]["attempt_id"],
            expected_source_hash=SOURCE_HASH,
            expected_revision_number=0,
            require_publication=True,
        )
        self.assertEqual(stale_agreement["status"], "blocked")
        self.assertTrue(
            any("stale_report" in blocker for blocker in stale_agreement["blockers"])
        )

        download_root = self.root / "download-modules"
        download_module = download_root / MODULE_SLUG
        download_module.mkdir(parents=True, exist_ok=True)
        shutil.copy2(summary_path, download_module / "MODULE_SUMMARY.md")

        def forbidden_generator(module_name):
            raise AssertionError("persisted Markdown download invoked a generator")

        download = resolve_adventure_markdown_download(
            MODULE_SLUG,
            modules_root=download_root,
            generator=forbidden_generator,
        )
        self.assertEqual(download["kind"], "summary")
        self.assertEqual(download["source"], "persisted")
        self.assertEqual(download["content"], summary)
        self.assertEqual(download["filename"], MODULE_SLUG + "_adventure.md")

    def test_post_registration_rollback_removes_new_registry_and_campaign_entries(self):
        candidate = self._publish_candidate()
        registry_before_rollback = json.loads(
            candidate["registry_path"].read_text(encoding="utf-8")
        )
        self.assertIn(MODULE_SLUG, registry_before_rollback["modules"])

        rollback = rollback_adaptation_publication(
            candidate["snapshot"],
            failure_reason="final_report_fixture_failure",
        )
        self.assertEqual(rollback["status"], "success", rollback)
        self.assertTrue(rollback["verified"])
        self.assertTrue(rollback["changed"])
        self.assertFalse(rollback["idempotent"])

        registry_after = json.loads(
            candidate["registry_path"].read_text(encoding="utf-8")
        )
        campaign_after = json.loads(
            candidate["campaign_path"].read_text(encoding="utf-8")
        )
        self.assertNotIn(MODULE_SLUG, registry_after["modules"])
        self.assertNotIn("ADP001", registry_after["areas"])
        self.assertEqual(campaign_after["availableModules"], [])

        repeated = rollback_adaptation_publication(
            candidate["snapshot"],
            failure_reason="repeated_cleanup",
        )
        self.assertEqual(repeated["status"], "success", repeated)
        self.assertTrue(repeated["verified"])
        self.assertTrue(repeated["idempotent"])
        self.assertTrue(candidate["module_dir"].is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
