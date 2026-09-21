# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Hostis-shaped adaptation monster integration coverage.

This fixture keeps the failure shape bounded: a rich staged module contains
authored context, plot, areas, maps, summary, metadata, and validation
artifacts while location monster lists mix canonical adversaries with NPC,
ally, and prose entries.  The test drives the normal packet-builder ordering
through normalization, final closure, and the adaptation gate seam without
touching a live module or invoking a provider.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from jsonschema import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.extensions.toolkit_homebrew_packet_builder as packet_builder
from core.generators.module_generator import ModuleGenerator, validate_module_structure
from utils.file_operations import safe_read_json, safe_write_json
from utils.monster_reference_closure import ensure_monster_reference_closure
from utils.toolkit_adaptation_config import BUILD_MODE_LLM_ADAPTATION
from utils.toolkit_adaptation_monster_guardrail import (
    normalize_adaptation_module_monsters,
)
from utils.toolkit_adaptation_staging import cleanup_adaptation_staging_target
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
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_monster_guardrail_integration"
MODULE_SLUG = "Hostis_Humanis_Generis"
SOURCE_TEXT = "Hostis-shaped fixture source with authored adversary evidence."
SOURCE_HASH = hashlib.sha256(SOURCE_TEXT.encode("utf-8")).hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    """Write bounded text through a project-local atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, payload: Any) -> None:
    """Use the repository atomic JSON writer for fixture artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not safe_write_json(str(path), payload, create_backup=False):
        raise AssertionError("fixture JSON write failed: " + str(path))


def _load_json(path: Path) -> Dict[str, Any]:
    payload = safe_read_json(str(path))
    if not isinstance(payload, dict):
        raise AssertionError("fixture JSON was not an object: " + str(path))
    return payload


class HostisAdaptationIntegrationFixture(unittest.TestCase):
    """Rich staged artifacts survive the adaptation monster seam."""

    def setUp(self) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = SCRATCH_ROOT / str(uuid.uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    @property
    def staging_root(self) -> str:
        """Return a unique project-relative staging root for this test."""
        return "tmp/toolkit_adaptation_monster_guardrail_integration/" + self.root.name + "/staging"

    def _dossier(self, adversaries: List[str]) -> Dict[str, Any]:
        fixture_path = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
        dossier = json.loads(fixture_path.read_text(encoding="utf-8"))
        dossier.update(
            {
                "source_title": "Hostis Humanis Generis",
                "adapted_title": MODULE_SLUG,
                "source_hash": SOURCE_HASH,
                "encounter_seeds": [
                    {
                        "name": "Salt Quay Ambush",
                        "setup": "A hostile landing party tests the quay defenses.",
                        "stakes": "The ferrymaster and the sealed cargo are at risk.",
                        "adversaries": adversaries,
                        "resolution_paths": [
                            "Defend the quay and preserve the cargo.",
                            "Negotiate with the hostile landing party.",
                        ],
                        "location": "Salt Quay",
                        "source_basis": "canonical adversary evidence in the source notes",
                    }
                ],
                "npc_seeds": [
                    {
                        "name": "Sister Mara",
                        "role": "helpful ferrymaster ally",
                        "purpose": "Provides a safe route through the quay.",
                        "disposition": "Helpful but wary",
                    }
                ],
            }
        )
        return dossier

    def _packet_workspace(self, title: str) -> Path:
        workspace = self.root / "workspace"
        ensure_workspace_placeholders(workspace)
        files = get_workspace_files(workspace)
        packet = {
            "packet_version": "v1",
            "normalization_state": "normalized",
            "source_path": "fixtures/hostis-shaped.md",
            "source_hash": SOURCE_HASH,
            "title": title,
            "author": "fixture",
            "description": "A rich Hostis-shaped adaptation fixture.",
            "adventure_summary": "The party protects a salt quay and follows canonical adversary evidence.",
            "module_tone": "grim maritime mystery",
            "acts": [{"name": "The Quay", "summary": "Defend the crossing."}],
            "locations": [{"name": "Salt Quay", "location": "quay", "description": "A wet stone landing."}],
            "npc_seeds": [{"name": "Sister Mara", "role": "ferrymaster ally"}],
            "encounter_seeds": [{"name": "Salt Quay Ambush", "description": "Canonical adversary evidence."}],
            "assumptions": ["Bounded provider-free integration fixture."],
            "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
        }
        persist_normalized_packet_artifact(workspace, packet)
        snapshot = build_review_snapshot(
            job_id="hostis-monster-fixture",
            decision=REVIEW_DECISION_APPROVE,
            packet=packet,
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
        )
        persist_review_snapshot_artifact(workspace, snapshot)
        _atomic_text(files["source_original"], SOURCE_TEXT)
        _atomic_text(files["builder_narrative"], "Build the rich Hostis-shaped staged module.")
        return workspace

    def _write_rich_staged_module(self, module_dir: Path) -> Dict[str, Any]:
        """Write a bounded rich artifact set matching the Hostis failure shape."""
        context = {
            "module_id": MODULE_SLUG,
            "title": "Hostis Humanis Generis",
            "mainObjective": "Keep the salt crossing open while exposing the hostile landing party.",
            "npcs": {"Sister Mara": {"role": "ferrymaster", "faction": "Quay Wardens"}},
            "areas": {"H001": {"name": "Salt Quay"}},
        }
        plot = {
            "mainObjective": context["mainObjective"],
            "plotPoints": [
                {"id": "PP001", "name": "The Quay Warning", "description": "Mara warns of a landing party."},
                {"id": "PP002", "name": "The Hostile Landing", "description": "The party chooses defense or negotiation."},
            ],
        }
        location = {
            "locationId": "H001L01",
            "locationName": "Salt Quay",
            "description": "Rain darkens the stone quay while cargo bells ring below the old watchtower.",
            "dmInstructions": "Keep the ferrymaster's warning and the cargo dilemma visible.",
            "npcs": ["Sister Mara"],
            "monsters": [
                {"name": "Three ash-stained goblins guarding the quay", "description": "They move between tarps and wet crates."},
                {"name": "A bandit lookout in a salt-stained cloak", "description": "The lookout signals from the bell tower."},
                "NPC Sister Mara the ferrymaster",
                "Allied dock workers carrying lanterns",
            ],
            "connectivity": [],
        }
        area = {
            "areaId": "H001",
            "areaName": "Salt Quay",
            "areaDescription": "A stormbound landing with a watchtower and a guarded cargo road.",
            "locations": [location],
        }
        map_payload = {"mapId": "H001", "areaId": "H001", "locations": ["H001L01"]}
        metadata = {"module_slug": MODULE_SLUG, "artifact_shape": "hostis_rich_fixture", "version": 1}
        validation = {"status": "pending", "module_slug": MODULE_SLUG, "rich_artifacts": True}
        artifacts = {
            "module_context.json": context,
            "module_context_BU.json": context,
            "module_plot.json": plot,
            "module_plot_BU.json": plot,
            "areas/H001.json": area,
            "areas/H001_BU.json": area,
            "map_H001.json": map_payload,
            "map_H001_BU.json": map_payload,
            "module_metadata.json": metadata,
            "validation_report.json": validation,
            "validation_report_BU.json": validation,
        }
        for relative, payload in artifacts.items():
            _write_json(module_dir / relative, payload)
        _atomic_text(
            module_dir / "MODULE_SUMMARY.md",
            "# Hostis Humanis Generis\n\nA rich staged summary with authored quay guidance.\n",
        )
        _write_json(
            module_dir / "monsters" / "goblin.json",
            {"name": "Goblin", "size": "Small", "alignment": "neutral evil", "armorClass": 15},
        )
        _write_json(
            module_dir / "monsters" / "bandit.json",
            {"name": "Bandit", "size": "Medium", "alignment": "any non-lawful", "armorClass": 12},
        )
        return {relative: payload for relative, payload in artifacts.items()}

    def _adaptation_provenance(self) -> Dict[str, Any]:
        return {
            "attempt_id": "adapt-001-024638ae9cb1e12ac9e1f2ac",
            "attempt_number": 1,
            "revision_number": 0,
            "source_path": "fixtures/hostis-shaped.md",
            "source_format": "markdown",
            "source_profile": "hostis_failure_shape",
            "source_hash": SOURCE_HASH,
            "model_metadata": {"provider": "fixture", "model": "provider-free"},
        }

    def test_module_generator_validation_report_stays_in_explicit_staging(self):
        """Explicit output validation must not derive a live module path."""
        staging = self.root / "generator-staging"
        staging.mkdir()
        module_data = {
            "moduleName": "Hostis Humanis Generis",
            "moduleDescription": "fixture",
            "moduleMetadata": {},
            "moduleConflicts": [],
            "mainPlot": {
                "mainObjective": "fixture",
                "antagonist": "fixture",
                "plotStages": [],
            },
            "factions": [],
            "worldMap": [],
            "timelineEvents": [],
        }
        with patch(
            "core.generators.module_generator.validate_module_structure",
            return_value=["Missing required directory: monsters"],
        ), patch(
            "core.generators.module_generator.save_json_safely",
            wraps=lambda path, payload: safe_write_json(path, payload, create_backup=False),
        ):
            ModuleGenerator().generate_module(
                "fixture",
                custom_values=module_data,
                output_directory=str(staging),
            )

        self.assertTrue((staging / "validation_report.json").is_file())
        self.assertFalse((REPO_ROOT / "modules" / "Hostis Humanis Generis").exists())
        self.assertFalse((REPO_ROOT / "modules" / "Hostis_Humanis_Generis" / "validation_report.json").exists())

    def test_missing_explicit_output_directory_fails_without_live_fallback(self):
        """Missing staging output is reported and never redirected to modules."""
        missing = self.root / "missing-staging"
        issues = validate_module_structure("Hostis Humanis Generis", str(missing))
        self.assertTrue(issues)
        self.assertIn("Missing explicit output directory", issues[0])
        self.assertFalse((REPO_ROOT / "modules" / "Hostis_Humanis_Generis" / "validation_report.json").exists())

    def test_generate_module_rejects_unsafe_or_unavailable_explicit_targets_before_write(self):
        """Explicit target failures never create validation reports or directories."""
        module_data = {
            "moduleName": "Hostis Humanis Generis",
            "moduleDescription": "fixture",
            "moduleMetadata": {},
            "moduleConflicts": [],
            "mainPlot": {"mainObjective": "fixture", "antagonist": "fixture", "plotStages": []},
            "factions": [],
            "worldMap": [],
            "timelineEvents": [],
        }
        targets = [
            REPO_ROOT / "modules" / "Hostis Humanis Generis",
            REPO_ROOT.parent / ("neq-adaptation-outside-" + self.root.name),
            self.root / "missing-explicit-target",
        ]
        for target in targets:
            with self.subTest(target=str(target)):
                self.assertFalse(target.exists())
                with self.assertRaises(ValueError):
                    ModuleGenerator().generate_module(
                        "fixture",
                        custom_values=copy.deepcopy(module_data),
                        output_directory=str(target),
                    )
                self.assertFalse(target.exists())

    def test_adaptation_save_requires_explicit_target_and_never_claims_closure(self):
        """Adaptation saves fail before legacy path creation or synthetic success."""
        generator = object.__new__(ModuleGenerator)
        generator.adaptation_mode = True
        module_data = {"moduleName": "Adaptation Guardrail Fixture"}
        with self.assertRaises(ValueError):
            generator.save_module(module_data)
        self.assertFalse(
            (REPO_ROOT / "modules" / "Adaptation_Guardrail_Fixture").exists()
        )

    def test_legacy_validation_without_output_directory_keeps_module_destination(self):
        """Omitting output_directory retains the legacy module-derived contract."""
        with patch("core.generators.module_generator.os.path.isdir", return_value=False) as isdir:
            issues = validate_module_structure("Legacy Fixture")
        self.assertIn("modules/Legacy_Fixture", issues[0])
        isdir.assert_called()

    def test_rich_hostis_artifacts_survive_normalization_and_reach_gates(self):
        """Canonical refs survive while rich artifacts reach adaptation gates."""
        workspace = self._packet_workspace(MODULE_SLUG)
        dossier = self._dossier(["Goblin", "Bandit"])
        captured: List[Dict[str, Any]] = []
        gate_calls: List[Dict[str, Any]] = []
        expected: Dict[str, Any] = {}

        def builder_executor(builder_input: Dict[str, Any], **_kwargs: Any) -> None:
            module_dir = REPO_ROOT / builder_input["staging_target"]["path"]
            expected.update(self._write_rich_staged_module(module_dir))

        def gate_composer(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            gate_calls.append({"args": args, "kwargs": kwargs})
            module_dir = Path(kwargs["module_dir"])
            self.assertTrue((module_dir / "module_context.json").is_file())
            self.assertTrue((module_dir / "MODULE_SUMMARY.md").is_file())
            return {
                "status": "pass",
                "playable_status": "pass",
                "candidate_eligible": True,
                "python_authoritative": True,
                "publication": {"authority": "python", "attempted": False, "allowed": False},
                "errors": [],
            }

        def capture_executor(builder_input: Dict[str, Any], **kwargs: Any) -> None:
            captured.append(copy.deepcopy(builder_input))
            builder_executor(builder_input, **kwargs)

        with patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", True), \
            patch("utils.spatial_repair.repair_module_spatial", return_value={"status": "pass"}), \
            patch("utils.calendar_normalization.normalize_party_calendar", return_value={"status": "pass"}), \
            patch("utils.toolkit_adaptation_gate_composer.run_adaptation_gate_composer", side_effect=gate_composer):
            result = packet_builder.run_toolkit_homebrew_packet_build(
                workspace,
                "hostis-monster-fixture",
                builder_executor=capture_executor,
                adaptation_route=BUILD_MODE_LLM_ADAPTATION,
                adaptation_dossier=dossier,
                adaptation_provenance=self._adaptation_provenance(),
                adaptation_staging_root=self.staging_root,
                adaptation_convergence_callback=lambda _context: {"status": "success"},
            )

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(len(captured), 1)
        self.assertEqual(len(gate_calls), 1)
        staging_dir = REPO_ROOT / result["staging_target"]["path"]

        normalized_area = _load_json(staging_dir / "areas/H001.json")
        monsters = normalized_area["locations"][0]["monsters"]
        self.assertEqual([entry["name"] for entry in monsters], ["Goblin", "Bandit"])
        self.assertIn("ash stained guarding the quay", normalized_area["locations"][0]["dmInstructions"])
        self.assertIn("NPC Sister Mara", normalized_area["locations"][0]["dmInstructions"])
        self.assertIn("Allied dock workers", normalized_area["locations"][0]["dmInstructions"])
        self.assertNotIn("Sister Mara", json.dumps(monsters))
        self.assertNotIn("dock workers", json.dumps(monsters))

        for relative, payload in expected.items():
            if relative == "areas/H001.json":
                self.assertEqual(
                    _load_json(staging_dir / relative)["locations"][0]["description"],
                    payload["locations"][0]["description"],
                )
            elif relative == "module_context.json":
                actual_context = _load_json(staging_dir / relative)
                actual_context.pop("continuity", None)
                actual_context.pop("continuity_enrichment", None)
                expected_context = copy.deepcopy(payload)
                expected_context.pop("continuity", None)
                expected_context.pop("continuity_enrichment", None)
                self.assertEqual(actual_context, expected_context)
            else:
                self.assertEqual(_load_json(staging_dir / relative), payload)
        self.assertIn("rich staged summary", (staging_dir / "MODULE_SUMMARY.md").read_text(encoding="utf-8"))

        closure = result["monster_closure"]
        self.assertEqual(closure["required"], 2)
        self.assertEqual(closure["unresolved"], 0)
        self.assertEqual(closure["generated"], 0)
        self.assertEqual(result["adaptation_monster_guardrail"]["unresolved_refs"], [])
        self.assertEqual(result["adaptation_monster_normalization"]["status"], "pass")
        self.assertTrue((staging_dir / "monster_closure_report.json").is_file())
        self.assertTrue((workspace / "build_result.json").is_file())

    def test_route_level_canonical_generation_uses_bounded_context_and_schema(self):
        """Enabled adaptation generation stays canonical and staging-only."""
        workspace = self._packet_workspace("Goblin Adaptation")
        dossier = self._dossier(["Goblin"])
        captured_context: List[Dict[str, Any]] = []
        callback_context: List[Dict[str, Any]] = []

        def builder_executor(builder_input: Dict[str, Any], **_kwargs: Any) -> None:
            module_dir = REPO_ROOT / builder_input["staging_target"]["path"]
            self._write_rich_staged_module(module_dir)
            area_path = module_dir / "areas" / "H001.json"
            area = _load_json(area_path)
            area["locations"][0]["monsters"] = [
                area["locations"][0]["monsters"][0]
            ]
            _write_json(area_path, area)
            # Force the approved Goblin through the opt-in generation seam;
            # Bandit remains a reusable authored artifact for the same fixture.
            (module_dir / "monsters" / "goblin.json").unlink()

        generated_payload = {
            "name": "Goblin",
            "size": "Small",
            "type": "Humanoid",
            "alignment": "neutral evil",
            "armorClass": 15,
            "hitPoints": 7,
            "maxHitPoints": 7,
            "speed": 30,
            "abilities": {
                "strength": 8,
                "dexterity": 14,
                "constitution": 10,
                "intelligence": 10,
                "wisdom": 8,
                "charisma": 8,
            },
            "savingThrows": [],
            "skills": {"stealth": 6},
            "damageVulnerabilities": [],
            "damageResistances": [],
            "damageImmunities": [],
            "conditionImmunities": [],
            "senses": {"darkvision": 60, "passivePerception": 9},
            "languages": "Common, Goblin",
            "challengeRating": 0.25,
            "specialAbilities": [],
            "actions": [],
            "legendaryActions": [],
            "condition": "Alive",
        }

        def bounded_builder(command: List[str], **_kwargs: Any) -> subprocess.CompletedProcess:
            self.assertNotIn("--module", command)
            context_path = Path(command[command.index("--context-file") + 1])
            context = json.loads(context_path.read_text(encoding="utf-8"))
            captured_context.append(context)
            output_directory = Path(command[command.index("--output-directory") + 1])
            output_path = output_directory / "monsters" / "goblin.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(generated_payload), encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        def convergence_callback(context: Dict[str, Any]) -> Dict[str, Any]:
            callback_context.append(copy.deepcopy(context))
            return {"status": "success"}

        with patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", True), \
            patch("model_config.ENABLE_LLM_ADAPTATION_CANONICAL_MONSTER_GENERATION", True), \
            patch("utils.toolkit_adaptation_monster_guardrail.subprocess.run", side_effect=bounded_builder) as provider, \
            patch("utils.spatial_repair.repair_module_spatial", return_value={"status": "pass"}), \
            patch("utils.calendar_normalization.normalize_party_calendar", return_value={"status": "pass"}), \
            patch("utils.toolkit_adaptation_gate_composer.run_adaptation_gate_composer", return_value={
                "status": "pass",
                "playable_status": "pass",
                "candidate_eligible": True,
                "python_authoritative": True,
                "publication": {"authority": "python", "attempted": False, "allowed": False},
                "errors": [],
            }):
            result = packet_builder.run_toolkit_homebrew_packet_build(
                workspace,
                "goblin-generation-route",
                builder_executor=builder_executor,
                adaptation_route=BUILD_MODE_LLM_ADAPTATION,
                adaptation_dossier=dossier,
                adaptation_provenance=self._adaptation_provenance(),
                adaptation_staging_root=self.staging_root,
                adaptation_convergence_callback=convergence_callback,
            )

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        provider.assert_called_once()
        self.assertEqual(len(captured_context), 1)
        generation_context = captured_context[0]
        self.assertEqual(generation_context["approved_identities"], ["Goblin"])
        self.assertEqual(generation_context["encounter_evidence"][0]["location"], "Salt Quay")
        self.assertIn("canonical adversary evidence", generation_context["encounter_evidence"][0]["source_basis"])
        self.assertIn("5e SRD-compatible", generation_context["srd_exemplar_guidance"])
        self.assertLessEqual(len(json.dumps(generation_context)), 4000)
        self.assertEqual(len(callback_context), 1)
        self.assertLessEqual(len(json.dumps(callback_context[0])), 32000)

        staging_dir = REPO_ROOT / result["staging_target"]["path"]
        generated_path = staging_dir / "monsters" / "goblin.json"
        self.assertEqual(generated_path.name, "goblin.json")
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
        self.assertEqual(generated["name"], "Goblin")
        self.assertLessEqual(generated["armorClass"], 30)
        self.assertLessEqual(generated["hitPoints"], 500)
        validate(instance=generated, schema=json.loads((REPO_ROOT / "schemas" / "mon_schema.json").read_text(encoding="utf-8")))
        self.assertEqual(result["adaptation_monster_guardrail"]["monsters_generated"], 1)
        self.assertEqual(result["adaptation_monster_guardrail"]["unresolved_refs"], [])
        self.assertEqual(result["adaptation_monster_guardrail"]["resolution_diagnostics"][0]["ref"], "Goblin")
        cleanup_adaptation_staging_target(result["staging_target"], repo_root=REPO_ROOT)

    def test_unresolved_canonical_reference_fails_closed_without_blind_generation(self):
        """Final adaptation closure observes unresolved canonical refs only."""
        staging = self.root / "unresolved-staging"
        self._write_rich_staged_module(staging)
        area_path = staging / "areas/H001.json"
        area = _load_json(area_path)
        area["locations"][0]["monsters"] = [{"name": "Canonical Missing"}]
        _write_json(area_path, area)
        normalized = normalize_adaptation_module_monsters(
            staging,
            self._dossier(["Canonical Missing"]),
            canonical_vocabulary=["Canonical Missing"],
        )
        self.assertEqual(normalized["status"], "pass")
        self.assertEqual(normalized["normalized_refs"], ["Canonical Missing"])

        with patch("utils.monster_reference_closure.subprocess.run") as run:
            closure = ensure_monster_reference_closure(
                MODULE_SLUG,
                str(staging),
                allow_generation=False,
            )
        run.assert_not_called()
        self.assertEqual(closure["unresolved"], 1)
        self.assertEqual(closure["generated"], 0)
        self.assertIn("canonical_missing", closure["details"]["unresolved"][0]["slug"])

    def test_packet_builder_generation_context_is_reference_scoped(self):
        """The packet seam supplies approved identities and bounded evidence."""
        dossier = self._dossier(["Goblin"])
        dossier["encounter_seeds"][0]["setup"] = "Goblin guards the salt quay."
        context = packet_builder._adaptation_generation_context(
            {"dossier": dossier}, ["Goblin"]
        )
        self.assertEqual(context["approved_identities"], ["Goblin"])
        self.assertEqual(context["encounter_evidence"][0]["location"], "Salt Quay")
        self.assertIn("Goblin", context["encounter_evidence"][0]["approved_identities"])
        self.assertIn("SRD", context["srd_exemplar_guidance"])
        self.assertNotIn("provider_payload", json.dumps(context))
        self.assertNotIn("choose an identity", json.dumps(context).lower())

    def test_packet_builder_passes_explicit_generation_policy_through(self):
        """Packet integration keeps generation opt-in and state-gated."""
        source = inspect.getsource(packet_builder._run_toolkit_homebrew_packet_build)
        self.assertIn("allow_canonical_monster_generation", source)
        self.assertIn("_explicit_generation_opt_in", source)
        self.assertIn("STAGING_STATE_BUILDING", source)
        self.assertIn("generation_opt_in=_explicit_generation_opt_in", source)
        self.assertIn("allow_generation=_allow_adaptation_generation", source)
        self.assertIn("_adaptation_staging_target.get(\"completion_state\")", source)
        self.assertIn("== STAGING_STATE_BUILDING", source)
        self.assertIn("_approved_canonical_identities", source)
        self.assertIn('"approved_identities": list(_approved_canonical_identities)', source)
        self.assertIn("approved_canonical_refs=_approved_canonical_identities", source)
        self.assertIn("STAGING_STATE_FAILED", inspect.getsource(packet_builder))
        self.assertIn("STAGING_STATE_COMPLETED", inspect.getsource(packet_builder))


if __name__ == "__main__":
    unittest.main(verbosity=2)
