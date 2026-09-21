# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Provider-free task 10.3 smoke for Jeremys Magic Shop adaptation routing."""

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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config
import utils.toolkit_adaptation_auditor as adaptation_auditor
import utils.toolkit_adaptation_gate_composer as adaptation_gate_composer
import utils.toolkit_adaptation_registry as adaptation_registry
import utils.toolkit_adaptation_campaign as adaptation_campaign
import utils.homebrewery_adventure_writer as adventure_writer
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
import web.extensions.toolkit_module_finisher as module_finisher
from web.extensions.toolkit_adaptation_runtime import adaptation_convergence_callback
from scripts.test_toolkit_adaptation_auditor import _base_response
from utils.file_operations import safe_write_json
from utils.toolkit_adaptation_artifacts import build_attempt_id
from utils.toolkit_adaptation_dossier import ADAPTATION_MODE_LLM
from utils.toolkit_adaptation_failure_packet import (
    build_adaptation_failure_packet,
    validate_adaptation_failure_packet,
)
from utils.toolkit_adaptation_revision import (
    REVISION_STATUS_FAILED,
    REVISION_STATUS_REVISION_PASSED,
    run_adaptation_final_revision,
)
from utils.toolkit_adaptation_world_context import build_world_context_provenance
from utils.toolkit_homebrew_upload_contract import (
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
)
from utils.toolkit_adaptation_provenance import build_adaptation_provenance


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "Local_Docs" / "modules" / "hombrew" / "modules" / "Jeremys Magic Shop.md"
SOURCE_REFERENCE = "Local_Docs/modules/hombrew/modules/Jeremys Magic Shop.md"
# Use a known structural/semantic gate-passing module only as a provider-free
# builder materialization fixture. The staged module is renamed and receives
# Jeremy's adaptation provenance before the real adaptation gates run.
BUILDER_FIXTURE = REPO_ROOT / "modules" / "Into_the_Deepvault"
MODULE_SLUG = "Jeremys_Magic_Shop"


def _blocked_provider(*args, **kwargs):
    """Fail immediately if an un-injected provider client is requested."""
    raise AssertionError("live provider client creation is forbidden in task 10.3")


def _blocked_network(*args, **kwargs):
    """Fail immediately if a real network operation is attempted."""
    raise AssertionError("live network access is forbidden in task 10.3")


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
        payload = copy.deepcopy(template)
        payload["name"] = name
        _write_json(target / "monsters" / f"{slug}.json", payload)


def _snapshot_tree(path: Path):
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


def _load_dossier(source_hash: str) -> dict:
    """Adapt the bounded catalogue fixture to the real Jeremy source hash."""
    fixture_path = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
    dossier = json.loads(fixture_path.read_text(encoding="utf-8"))
    dossier.update(
        {
            "source_title": "Jeremy's Magic Shop",
            "adapted_title": "Jeremy's Magic Shop",
            "source_hash": source_hash,
            "adaptation_notice": "Adapted for NEQ-TTRPG",
        }
    )
    return dossier


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not safe_write_json(str(path), payload, create_backup=False):
        raise AssertionError(f"fixture JSON write failed: {path}")


class JeremysMagicShopAdaptationSmoke(unittest.TestCase):
    """Run the real packet builder, deterministic gates, and finisher in isolation."""

    def setUp(self) -> None:
        (REPO_ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=str(REPO_ROOT / "tmp"),
            prefix="toolkit_adaptation_jeremys_magic_shop_",
        )
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        ensure_workspace_placeholders(self.workspace)
        self.files = get_workspace_files(self.workspace)
        self.source_hash = hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest()
        self.attempt_id = build_attempt_id(
            self.source_hash,
            1,
            "jeremys-magic-shop-task-10-3",
        )
        self.staging_root = f"tmp/{self.root.name}/staging"
        self.registry_path = self.root / "modules" / "world_registry.json"
        _write_json(
            self.registry_path,
            {
                "worldName": "Task 10.3 Fixture World",
                "registryVersion": "1.0.0",
                "modules": {},
                "areas": {},
                "themes": {},
                "isolatedModules": True,
            },
        )
        self.campaign_path = self.root / "modules" / "campaign.json"
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
            patch.object(adaptation_auditor, "create_chat_client", side_effect=_blocked_provider),
            patch("utils.ai_client_factory.create_chat_client", side_effect=_blocked_provider),
            patch.object(socket, "socket", side_effect=_blocked_network),
            patch.object(socket, "create_connection", side_effect=_blocked_network),
            patch.object(urllib.request, "urlopen", side_effect=_blocked_network),
            patch.object(http.client.HTTPConnection, "request", side_effect=_blocked_network),
            patch.object(http.client.HTTPSConnection, "request", side_effect=_blocked_network),
        ]
        for patcher in self.tripwire_patchers:
            patcher.start()

        self.files["source_original"].write_bytes(SOURCE_PATH.read_bytes())
        packet = {
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
        }
        _write_json(self.files["normalized_packet"], packet)
        _write_json(
            self.files["ui_review_snapshot"],
            build_review_snapshot(
                "jeremys-magic-shop-task-10-3",
                "approve",
                packet,
                "user_authored",
            ),
        )
        self.files["builder_narrative"].write_text(
            "Build a coherent shop-centered adaptation of Jeremy's Magic Shop.",
            encoding="utf-8",
        )
        self.dossier = _load_dossier(self.source_hash)
        self.provenance = {
            "attempt_id": self.attempt_id,
            "attempt_number": 1,
            "revision_number": 0,
            "source_path": SOURCE_REFERENCE,
            "source_format": "markdown",
            "dossier_artifact_path": "tmp/jeremys-magic-shop/adaptation_dossier.json",
            "model_metadata": {
                "provider": "fixture",
                "model": "provider-free-adaptation",
            },
            "world_context_provenance": build_world_context_provenance({}),
            "source_title": "Jeremy's Magic Shop",
            "source_hash": self.source_hash,
            "source_profile": "catalogue",
            "rights_class": "user_authored",
            "rights_basis": "Operator attested that the uploaded source is user-authored.",
            "rights_review_required": False,
            "rights_review_status": "not_required",
        }

    def tearDown(self) -> None:
        try:
            for patcher in reversed(self.tripwire_patchers):
                patcher.stop()
            for path, before in self.protected_real_state.items():
                self.assertEqual(before, path.read_bytes(), f"real protected artifact changed: {path}")
            self.assertEqual(
                self.protected_real_module,
                _snapshot_tree(self.real_module),
                f"real module changed: {self.real_module}",
            )
        finally:
            self.temp_dir.cleanup()

    def _builder_executor(self, builder_input: dict, progress_callback=None) -> None:
        """Materialize a known gate-passing module without invoking a provider."""
        self.assertEqual(builder_input["build_mode"], ADAPTATION_MODE_LLM)
        handoff = builder_input["llm_adaptation"]
        self.assertEqual(handoff["dossier"]["source_profile"], "catalogue")
        self.assertEqual(handoff["dossier"]["source_hash"], self.source_hash)
        target = (REPO_ROOT / builder_input["derived_builder_parameters"]["output_directory"]).resolve()
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

    def _run_initial_build(self) -> dict:
        """Run the real feature-flagged adaptation packet-builder path."""
        return packet_builder.run_toolkit_homebrew_packet_build(
            workspace=self.workspace,
            job_id="jeremys-magic-shop-task-10-3",
            builder_executor=self._builder_executor,
            adaptation_route=ADAPTATION_MODE_LLM,
            adaptation_dossier=self.dossier,
            adaptation_provenance=self.provenance,
            adaptation_staging_root=self.staging_root,
            adaptation_convergence_callback=adaptation_convergence_callback,
        )

    def _build_failure_packet(self, build_result: dict) -> dict:
        """Build the bounded Python-owned packet from the injected gate failure."""
        target = build_result["staging_target"]
        attempt = copy.deepcopy(self.provenance)
        attempt.update(
            {
                "stage": "adaptation_gates",
                "stage_id": target["stage_id"],
                "revision_number": 0,
            }
        )
        packet = build_adaptation_failure_packet(
            build_result["adaptation_gates"],
            attempt_metadata=attempt,
            staging_target=target,
            module_summaries=[
                {
                    "module_slug": MODULE_SLUG,
                    "module_title": "Jeremy's Magic Shop",
                    "status": build_result.get("status"),
                    "publishable_status": "blocked",
                    "summary": "Controlled semantic gate failure for task 10.3.",
                }
            ],
            source_context_refs=[
                {
                    "path": SOURCE_REFERENCE,
                    "sha256": self.source_hash,
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
            failure_classification={
                "failure_class": "semantic",
                "failure_group": "content",
                "classification_status": "revision_eligible",
                "code": "controlled_semantic_gate_failure",
                "message": "controlled semantic gate failure requires a bounded revision",
                "semantic_revision_eligible": True,
                "consumes_semantic_revision_budget": True,
                "revision_budget": {
                    "current_revision": 0,
                    "max_revisions": 1,
                    "decision": "eligible",
                },
            },
            module_dir=REPO_ROOT / build_result["output_directory"],
            world_context_provenance=self.provenance.get("world_context_provenance"),
            stage="adaptation_gates",
            revision_number=0,
            repo_root=REPO_ROOT,
        )
        validation = validate_adaptation_failure_packet(packet, repo_root=REPO_ROOT)
        self.assertTrue(validation["valid"], validation)
        return packet

    def _run_revision(self, packet: dict):
        """Run the bounded final revision through the real packet-builder seam."""
        auditor_packets = []
        revision_builds = []
        revised_dossier = copy.deepcopy(self.dossier)
        revised_dossier["adapted_title"] = "Jeremy's Lantern Market Adaptation"

        def auditor(failure_packet, **_kwargs):
            auditor_packets.append(copy.deepcopy(failure_packet))
            response = _base_response(failure_packet, "revise")
            response["revised_dossier"] = copy.deepcopy(revised_dossier)
            return {
                "status": "success",
                "decision": "revise",
                "ok": True,
                "response": response,
                "model_metadata": {
                    "provider": "fixture",
                    "model": "provider-free-task-10-3-auditor",
                },
            }

        def revision_builder(staging_target, dossier, directive, **kwargs):
            revision_builds.append(
                {
                    "target": copy.deepcopy(staging_target),
                    "dossier": copy.deepcopy(dossier),
                    "directive": copy.deepcopy(directive),
                    "attempt_metadata": copy.deepcopy(kwargs.get("attempt_metadata")),
                }
            )
            result = packet_builder.run_toolkit_homebrew_packet_build(
                workspace=self.workspace,
                job_id="jeremys-magic-shop-task-10-3-revision",
                builder_executor=self._builder_executor,
                adaptation_route=ADAPTATION_MODE_LLM,
                adaptation_dossier=dossier,
                adaptation_provenance=kwargs.get("attempt_metadata"),
                adaptation_staging_root=self.staging_root,
                adaptation_staging_target=staging_target,
                adaptation_convergence_callback=adaptation_convergence_callback,
            )
            if result.get("status") != "success":
                result["failure_class"] = "semantic"
                result["revision_eligible"] = True
                result["failure_classification"] = {
                    "failure_class": "semantic",
                    "message": "controlled semantic failure remains after revision",
                    "semantic_revision_eligible": True,
                    "revision_eligible": True,
                }
                result["gate_result"] = result.get("adaptation_gates", {}).get("gates", {})
            revision_builds[-1]["build_result"] = copy.deepcopy(result)
            return result

        result = run_adaptation_final_revision(
            packet,
            workspace=self.workspace,
            repo_root=REPO_ROOT,
            staging_root=self.staging_root,
            module_slug=MODULE_SLUG,
            build_callback=revision_builder,
            auditor_runner=auditor,
            current_dossier=self.dossier,
            max_revisions=1,
        )
        return result, auditor_packets, revision_builds

    def _assert_no_publication_side_effect(self, before_state) -> None:
        """Assert that failed attempts did not publish module or area entries."""
        self.assertEqual(
            before_state,
            {
                path: path.read_bytes() if path.exists() else None
                for path in (self.registry_path, self.campaign_path)
            },
        )
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertNotIn(MODULE_SLUG, registry.get("modules", {}))
        self.assertFalse(
            any(
                isinstance(area, dict) and area.get("module") == MODULE_SLUG
                for area in registry.get("areas", {}).values()
            )
        )
        self.assertFalse((REPO_ROOT / "modules" / MODULE_SLUG).exists())

    def test_feature_flagged_adaptation_validates_renders_and_registers(self) -> None:
        with patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", True), patch.object(
            module_finisher,
            "_run_registry_stage",
            side_effect=lambda module_slug, *, module_dir=None, adaptation=False: adaptation_registry.integrate_adaptation_registry(
                module_slug,
                module_dir,
                registry_path=self.registry_path,
            ),
        ), patch.object(
            module_finisher,
            "_run_adaptation_campaign_sync_stage",
            side_effect=lambda module_slug, **kwargs: adaptation_campaign.synchronize_adaptation_campaign_module(
                module_slug,
                registry_path=self.registry_path,
                campaign_path=self.campaign_path,
            ),
        ), patch.object(adventure_writer, "_llm_intro_narrative", return_value=None), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(adventure_writer, "_llm_area_overview", return_value=None):
            build_result = packet_builder.run_toolkit_homebrew_packet_build(
                workspace=self.workspace,
                job_id="jeremys-magic-shop-task-10-3",
                builder_executor=self._builder_executor,
                adaptation_route=ADAPTATION_MODE_LLM,
                adaptation_dossier=self.dossier,
                adaptation_provenance=self.provenance,
                adaptation_staging_root=self.staging_root,
                adaptation_convergence_callback=adaptation_convergence_callback,
            )

            self.assertEqual(build_result.get("status"), "success", build_result)
            self.assertEqual(
                build_result["adaptation_gates"]["playable_status"],
                "pass",
                build_result.get("adaptation_gates"),
            )
            self.assertEqual(
                build_result["adaptation_attempt_report"]["status"],
                "persisted",
            )

            module_dir = REPO_ROOT / build_result["output_directory"]
            finishing_result = module_finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode=ADAPTATION_MODE_LLM,
                adaptation_gates=build_result["adaptation_gates"],
                adaptation_staging_target=build_result["staging_target"],
                adaptation_module_dir=str(module_dir),
                adaptation_provenance=build_result.get("adaptation_provenance", self.provenance),
                adaptation_artifact_workspace=str(self.workspace),
            )

        self.assertEqual(finishing_result.get("status"), "success", finishing_result)
        self.assertEqual(finishing_result["stages"]["registry"]["status"], "success")
        self.assertEqual(finishing_result["stages"]["campaign_sync"]["status"], "deferred")
        summary_path = module_dir / "MODULE_SUMMARY.md"
        self.assertTrue(summary_path.exists())
        summary = summary_path.read_text(encoding="utf-8")
        self.assertIn("Jeremy", summary)
        self.assertIn("Adapted for NEQ-TTRPG", summary)
        self.assertIn(MODULE_SLUG, json.loads(self.registry_path.read_text(encoding="utf-8"))["modules"])
        build_payload = json.loads(
            self.files["build_result"].read_text(encoding="utf-8")
        )
        self.assertEqual(
            build_payload["model_metadata"]["model"],
            "provider-free-adaptation",
        )
        self.assertEqual(
            build_payload["adaptation_provenance"]["source_hash"],
            self.source_hash,
        )

    def test_semantic_failure_revision_rebuilds_fresh_and_publishes(self) -> None:
        """A controlled semantic failure is revised, rebuilt, gated, and published."""
        _write_json(
            self.campaign_path,
            {
                "campaignName": "Task 10.3 Campaign",
                "active": True,
                "availableModules": [],
            },
        )
        before_revision = {
            path: path.read_bytes() if path.exists() else None
            for path in (self.registry_path, self.campaign_path)
        }
        semantic_gate_paths = []
        original_semantic_gate = adaptation_gate_composer._run_semantic_authority_gate

        def controlled_semantic_gate(module_slug, module_dir, **_kwargs):
            semantic_gate_paths.append(Path(module_dir).resolve())
            if len(semantic_gate_paths) == 1:
                return {
                    "status": "blocked",
                    "errors": ["controlled semantic failure: ambiguous shop destination"],
                    "blockers": ["controlled semantic failure: ambiguous shop destination"],
                    "warnings": [],
                }
            return original_semantic_gate(module_slug, module_dir)

        with patch.object(
            model_config, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            packet_builder, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            adaptation_gate_composer,
            "_run_semantic_authority_gate",
            side_effect=controlled_semantic_gate,
        ):
            initial_result = self._run_initial_build()
            self.assertEqual(initial_result["status"], "blocked", initial_result)
            self.assertEqual(
                initial_result["adaptation_gates"]["gates"]["semantic_authority"]["status"],
                "blocked",
            )
            self.assertEqual(
                before_revision,
                {
                    path: path.read_bytes() if path.exists() else None
                    for path in (self.registry_path, self.campaign_path)
                },
            )
            failure_packet = self._build_failure_packet(initial_result)
            self.assertIn(
                "controlled semantic failure",
                json.dumps(failure_packet, ensure_ascii=True),
            )
            revision_result, auditor_packets, revision_builds = self._run_revision(
                failure_packet
            )

        self.assertEqual(revision_result["status"], REVISION_STATUS_REVISION_PASSED)
        self.assertEqual(revision_result["revision_number"], 1)
        self.assertEqual(len(auditor_packets), 1)
        self.assertEqual(auditor_packets[0]["revision_number"], 0)
        self.assertIn(
            "controlled semantic failure",
            json.dumps(auditor_packets[0], ensure_ascii=True),
        )
        self.assertEqual(len(revision_builds), 1)
        self.assertEqual(revision_builds[0]["target"]["revision_number"], 1)
        self.assertEqual(revision_builds[0]["attempt_metadata"]["revision_number"], 1)
        self.assertEqual(
            revision_builds[0]["dossier"]["adapted_title"],
            "Jeremy's Lantern Market Adaptation",
        )
        revision_gates = revision_builds[0]["build_result"]["adaptation_gates"]
        self.assertEqual(revision_gates["status"], "pass")
        self.assertEqual(revision_gates["playable_status"], "pass")
        self.assertTrue(revision_gates["candidate_eligible"])
        self.assertTrue(
            revision_gates["gates"]
            and all(
                gate.get("effective_status") == "pass"
                for gate in revision_gates["gates"].values()
            ),
            revision_gates,
        )
        self.assertEqual(len(semantic_gate_paths), 2)
        self.assertNotEqual(semantic_gate_paths[0], semantic_gate_paths[1])
        self.assertNotEqual(
            initial_result["staging_target"]["path"],
            revision_result["staging_target"]["path"],
        )
        self.assertEqual(
            json.loads(
                (REPO_ROOT / initial_result["staging_target"]["metadata_path"]).read_text(
                    encoding="utf-8"
                )
            )["completion_state"],
            "failed",
        )
        self.assertEqual(revision_result["staging_target"]["completion_state"], "completed")
        revised_module_dir = REPO_ROOT / revision_result["staging_target"]["path"]
        self.assertTrue((revised_module_dir / "module_context.json").exists())

        with patch.object(
            module_finisher,
            "_run_registry_stage",
            side_effect=lambda module_slug, *, module_dir=None, adaptation=False: adaptation_registry.integrate_adaptation_registry(
                module_slug,
                module_dir,
                registry_path=self.registry_path,
            ),
        ), patch.object(
            module_finisher,
            "_run_adaptation_campaign_sync_stage",
            side_effect=lambda module_slug, **kwargs: adaptation_campaign.synchronize_adaptation_campaign_module(
                module_slug,
                registry_path=self.registry_path,
                campaign_path=self.campaign_path,
            ),
        ), patch.object(
            adventure_writer, "_llm_intro_narrative", return_value=None
        ), patch.object(
            adventure_writer, "_llm_plot_hook", return_value=None
        ), patch.object(
            adventure_writer, "_llm_area_overview", return_value=None
        ):
            finishing_result = module_finisher.run_toolkit_module_postbuild_finishing(
                MODULE_SLUG,
                adaptation_mode=ADAPTATION_MODE_LLM,
                adaptation_gates=revision_builds[0]["build_result"]["adaptation_gates"],
                adaptation_staging_target=revision_result["staging_target"],
                adaptation_module_dir=str(revised_module_dir),
                adaptation_provenance=revision_builds[0]["build_result"].get(
                    "adaptation_provenance", self.provenance
                ),
                adaptation_artifact_workspace=str(self.workspace),
            )

        self.assertEqual(finishing_result["status"], "success", finishing_result)
        self.assertEqual(finishing_result["stages"]["registry"]["status"], "success")
        self.assertTrue(finishing_result["stages"]["registry"]["verification"]["verified"])
        self.assertEqual(finishing_result["stages"]["campaign_sync"]["status"], "success")
        self.assertTrue(finishing_result["stages"]["campaign_sync"]["campaign_visibility_verified"])
        self.assertIn(
            MODULE_SLUG,
            json.loads(self.registry_path.read_text(encoding="utf-8"))["modules"],
        )
        self.assertIn(
            MODULE_SLUG,
            json.loads(self.campaign_path.read_text(encoding="utf-8"))["availableModules"],
        )
        self.assertTrue((revised_module_dir / "MODULE_SUMMARY.md").exists())

    def test_semantic_failure_revision_exhaustion_has_no_publication_side_effect(self) -> None:
        """An exhausted semantic revision remains failed and unpublished."""
        _write_json(
            self.registry_path,
            {
                "worldName": "Task 10.3 Sentinel World",
                "registryVersion": "1.0.0",
                "modules": {"Existing_Module": {"moduleName": "Existing_Module"}},
                "areas": {"EXISTING": {"module": "Existing_Module"}},
                "themes": {},
                "isolatedModules": True,
            },
        )
        _write_json(
            self.campaign_path,
            {
                "campaignName": "Task 10.3 Sentinel Campaign",
                "active": True,
                "availableModules": ["Existing_Module"],
            },
        )
        before_failure = {
            path: path.read_bytes() if path.exists() else None
            for path in (self.registry_path, self.campaign_path)
        }
        semantic_gate_paths = []

        def always_fail_semantic_gate(module_slug, module_dir, **_kwargs):
            semantic_gate_paths.append(Path(module_dir).resolve())
            return {
                "status": "blocked",
                "errors": ["controlled semantic failure: destination remains ambiguous"],
                "blockers": ["controlled semantic failure: destination remains ambiguous"],
                "warnings": [],
            }

        with patch.object(
            packet_builder, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            adaptation_gate_composer,
            "_run_semantic_authority_gate",
            side_effect=always_fail_semantic_gate,
        ):
            initial_result = self._run_initial_build()
            self.assertEqual(initial_result["status"], "blocked", initial_result)
            failure_packet = self._build_failure_packet(initial_result)
            revision_result, auditor_packets, revision_builds = self._run_revision(
                failure_packet
            )

        self.assertEqual(revision_result["status"], REVISION_STATUS_FAILED)
        self.assertEqual(revision_result["outcome"], REVISION_STATUS_FAILED)
        self.assertEqual(
            revision_result["diagnostics"][0]["code"],
            "revision_budget_exhausted",
            revision_result.get("failure_classification"),
        )
        self.assertFalse(revision_result["published"])
        self.assertFalse(revision_result["registry_mutated"])
        self.assertFalse(revision_result["publication_started"])
        self.assertEqual(len(auditor_packets), 1)
        self.assertEqual(len(revision_builds), 1)
        self.assertEqual(len(semantic_gate_paths), 2)
        self.assertNotEqual(semantic_gate_paths[0], semantic_gate_paths[1])
        self.assertEqual(revision_result["staging_target"]["completion_state"], "failed")
        self._assert_no_publication_side_effect(before_failure)


if __name__ == "__main__":
    unittest.main(verbosity=2)
