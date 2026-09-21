# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the adaptation monster guardrail foundation."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_monster_guardrail import (
    ADAPTATION_MONSTER_GUARDRAIL_VERSION,
    _adaptation_identity_variants,
    _bind_adaptation_encounters,
    _encounter_contexts,
    _generate_canonical_monster_in_staging,
    build_effective_adaptation_guardrail_input,
    build_adaptation_canonical_monster_registry,
    build_adaptation_monster_guardrail_report,
    extract_adaptation_adversaries,
    materialize_adaptation_monsters,
    normalize_adaptation_module_monsters,
    normalize_adaptation_location_monsters,
)
from utils.toolkit_adaptation_staging import (
    create_adaptation_staging_target,
    validate_adaptation_staging_target,
)
from utils.monster_reference_closure import ensure_monster_reference_closure
from web.extensions.toolkit_homebrew_packet_builder import (
    _apply_adaptation_fidelity_boundary,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
TEST_ROOT = REPO_ROOT / "tmp" / "adaptation_monster_guardrail_test"


def _load_fixture():
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestAdaptationMonsterGuardrail(unittest.TestCase):
    """The foundation extracts bounded source adversaries and binds them."""

    def tearDown(self):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def test_adaptation_identity_variants_preserve_amphail_labels(self):
        plural = _adaptation_identity_variants("Memory-thief impersonations")
        qualified = _adaptation_identity_variants("Two slime spawn")

        self.assertEqual(plural["raw_label"], "Memory-thief impersonations")
        self.assertEqual(
            plural["variants"],
            ["memory thief impersonations", "memory thief impersonation"],
        )
        self.assertEqual(qualified["raw_label"], "Two slime spawn")
        self.assertEqual(qualified["quantity_value"], 2)
        self.assertEqual(
            qualified["variants"],
            ["two slime spawn", "slime spawn", "slime spawns"],
        )

    def test_canonical_registry_preserves_raw_identity_and_cave_guardian_alias(self):
        dossier = {
            "adaptation_mode": "llm_adaptation",
            "encounter_seeds": [{
                "id": "K06",
                "adversaries": ["Cave guardians"],
                "location": "K06",
            }],
        }
        registry = build_adaptation_canonical_monster_registry(
            dossier,
            approved_canonical_identities=["Cave Guardian"],
        )
        self.assertEqual(registry["status"], "pass")
        self.assertEqual(registry["approved_identities"], ["Cave Guardian"])
        entry = registry["entries"][0]
        self.assertIn("Cave guardians", entry["raw_references"])
        self.assertIn("Cave guardians", entry["aliases"])
        self.assertEqual(entry["canonical_slug"], "cave_guardian")

    def test_canonical_registry_tracks_locations_encounters_and_quantity_separately(self):
        dossier = {
            "adaptation_mode": "llm_adaptation",
            "encounter_seeds": [{
                "id": "K10",
                "adversaries": ["Cave Guardian"],
            }],
        }
        areas = [{
            "areaId": "K",
            "locations": [{
                "locationId": "RTR001",
                "monsters": [{"name": "2 Cave guardians", "quantity": {"min": 2, "max": 2}}],
            }],
        }]
        registry = build_adaptation_canonical_monster_registry(
            dossier, areas=areas, approved_canonical_identities=["Cave Guardian"]
        )
        entry = registry["entries"][0]
        self.assertEqual(entry["affected_location_ids"], ["RTR001"])
        self.assertEqual(entry["encounter_references"], ["K10"])
        self.assertEqual(entry["quantity_evidence"][0]["quantity"], {"min": 2, "max": 2})
        self.assertNotIn("2", entry["canonical_identity"])
        self.assertNotIn("2", entry["canonical_slug"])

    def test_canonical_registry_order_is_deterministic_and_artifacts_are_provenance(self):
        root = TEST_ROOT / "staging"
        (root / "monsters").mkdir(parents=True, exist_ok=True)
        for name in ("zeta", "alpha"):
            (root / "monsters" / f"{name}.json").write_text(
                json.dumps({"name": name.title(), "size": "M", "alignment": "N", "armorClass": 10}),
                encoding="utf-8",
            )
        dossier = {"adaptation_mode": "llm_adaptation", "encounter_seeds": []}
        first = build_adaptation_canonical_monster_registry(dossier, staging_root=root)
        second = build_adaptation_canonical_monster_registry(dossier, staging_root=root)
        self.assertEqual(first, second)
        self.assertEqual(first["approved_identities"], ["Alpha", "Zeta"])
        self.assertTrue(first["entries"][0]["reusable_artifacts"])

    def test_canonical_registry_filters_unapproved_source_candidates(self):
        dossier = {
            "adaptation_mode": "llm_adaptation",
            "encounter_seeds": [{"adversaries": ["Approved Beast"]}],
        }
        registry = build_adaptation_canonical_monster_registry(
            dossier,
            source_packet={"monster_refs": ["Invented Beast"]},
            approved_canonical_identities=["Approved Beast"],
        )
        self.assertEqual(registry["approved_identities"], ["Approved Beast"])
        self.assertNotIn("Invented Beast", registry["approved_identities"])

    def test_canonical_registry_isolated_from_legacy_routes(self):
        registry = build_adaptation_canonical_monster_registry(
            {"adaptation_mode": "source_blueprint_modulebuilder", "encounter_seeds": []}
        )
        self.assertEqual(registry["status"], "skipped")
        self.assertEqual(registry["entries"], [])
        self.assertEqual(registry["diagnostics"][0]["code"], "legacy_route_isolated")

    def test_adaptation_identity_variants_handle_ordinary_singular_plural_forms(self):
        self.assertEqual(
            _adaptation_identity_variants("Goblin"),
            {
                "raw_label": "Goblin",
                "raw_key": "goblin",
                "quantity_prefix": "",
                "quantity_value": None,
                "variants": ["goblin", "goblins"],
            },
        )
        self.assertEqual(
            _adaptation_identity_variants("Memory-thief impersonations")["variants"],
            ["memory thief impersonations", "memory thief impersonation"],
        )

    def test_adaptation_identity_variants_do_not_classify_broad_or_custom_names(self):
        for label in ("Guardian", "Ooze", "Vey's Hired Scout"):
            result = _adaptation_identity_variants(label)
            self.assertEqual(result["raw_label"], label)
            self.assertTrue(result["variants"])
            self.assertNotIn("npc", result)
            self.assertNotIn("classification", result)

    def test_adaptation_identity_variants_are_deterministic_and_bounded(self):
        label = "3 " + ("very descriptive " * 100) + "spawn"
        first = _adaptation_identity_variants(label)
        second = _adaptation_identity_variants(label)

        self.assertEqual(first, second)
        self.assertLessEqual(len(first["raw_label"]), 163)
        self.assertLessEqual(len(first["variants"]), 4)
        self.assertLessEqual(len(first["quantity_prefix"]), 32)

    def test_extracts_ordered_deduplicated_adversaries(self):
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = [
            "  Smuggler ",
            "Market lookout",
            "smuggler",
        ]
        self.assertEqual(
            extract_adaptation_adversaries(dossier),
            ["Smuggler", "Market lookout"],
        )

    def test_literal_fidelity_is_informational_for_adaptation(self):
        """Editorial literal mismatches retain evidence without editor routing."""
        workspace = TEST_ROOT / "fidelity_workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        fidelity = {
            "status": "blocked",
            "blockers": [{
                "category": "location",
                "message": "Required location 'Premise and Overview' not found in module",
                "source_atom_id": "atom-heading-1",
            }],
            "warnings": [],
            "coverage": {"location": {"found": 0, "total": 1}},
        }
        classification = {
            "status": "editorial",
            "fatal_count": 0,
            "editorial_count": 1,
            "warnings": [],
        }
        provenance = {
            "contract_version": "toolkit_adaptation_provenance.v1",
            "adaptation_mode": "llm_adaptation",
            "adaptation_notice": "This module is an original adaptation.",
            "adaptation_status": "adapted",
            "source_fidelity_status": "not_applicable",
            "literal_source_fidelity": "not_applicable",
            "fidelity_claim": "non_literal_adaptation",
            "source_hash": "a" * 64,
        }
        with patch(
            "utils.toolkit_adaptation_provenance.validate_adaptation_provenance",
            return_value={"valid": True, "diagnostics": []},
        ):
            result = _apply_adaptation_fidelity_boundary(
                workspace=workspace,
                fidelity_report=fidelity,
                classification=classification,
                adaptation_provenance=provenance,
                staging_target={"path": str(workspace)},
                module_slug="Adapted_Module",
            )
        self.assertTrue(result["eligible"])
        self.assertEqual(result["reason"], "adaptation_literal_fidelity_informational")
        self.assertEqual(result["literal_blocker_count"], 1)
        self.assertTrue((workspace / "source_fidelity_report.json").is_file())

    def test_fatal_fidelity_classification_remains_terminal(self):
        result = _apply_adaptation_fidelity_boundary(
            workspace=TEST_ROOT / "fatal_workspace",
            fidelity_report={"status": "blocked", "blockers": []},
            classification={
                "status": "fatal",
                "fatal_count": 1,
                "editorial_count": 0,
                "warnings": [],
            },
            adaptation_provenance={"adaptation_mode": "llm_adaptation"},
            staging_target={},
            module_slug="Adapted_Module",
        )
        self.assertFalse(result["eligible"])
        self.assertIn(
            result["reason"],
            {
                "adaptation_provenance_invalid",
                "adaptation_fidelity_classification_not_editorial_only",
            },
        )

    def test_source_packet_reconciles_missing_dossier_adversary_without_mutation(self):
        dossier = _load_fixture()
        original = copy.deepcopy(dossier)
        source_packet = {
            "source_hash": dossier["source_hash"],
            "adversaries": ["Simon Vey's Hired Scout"],
        }

        result = build_effective_adaptation_guardrail_input(
            dossier,
            source_packet=source_packet,
        )

        effective = result["effective_dossier"]
        adversaries = effective["encounter_seeds"][0]["adversaries"]
        self.assertEqual(adversaries[:2], original["encounter_seeds"][0]["adversaries"])
        self.assertEqual(adversaries[-1], "Simon Vey's Hired Scout")
        self.assertTrue(result["reconciliation_report"]["source_reconciled"])
        appended = result["reconciliation_report"]["appended_adversaries"][0]
        self.assertTrue(appended["source_reconciled"])
        self.assertEqual(appended["source_field"], "normalized_packet.adversaries[0]")
        self.assertEqual(dossier, original)
        self.assertEqual(effective["source_hash"], original["source_hash"])
        self.assertEqual(effective["rights_class"], original["rights_class"])

    def test_normalized_packet_monster_refs_are_advisory_only(self):
        dossier = _load_fixture()
        original = copy.deepcopy(dossier)
        result = build_effective_adaptation_guardrail_input(
            dossier,
            source_packet={
                "source_hash": dossier["source_hash"],
                "monster_refs": [
                    "Oblex",
                    "Night hag",
                    "Granny Asspimple",
                    "Commoner",
                ],
            },
        )

        report = result["reconciliation_report"]
        self.assertFalse(report["source_reconciled"])
        self.assertEqual(result["effective_dossier"], original)
        ignored = report["ignored_source_candidates"]
        self.assertEqual([entry["name"] for entry in ignored], [
            "Oblex", "Night hag", "Granny Asspimple", "Commoner"
        ])
        self.assertTrue(all(
            entry["reason"] == "advisory_source_candidate_not_authoritative"
            and entry["source_field"].startswith("normalized_packet.monster_refs[")
            for entry in ignored
        ))

    def test_source_custom_adversary_reaches_bounded_generation_not_owner(self):
        staging = TEST_ROOT / "source_reconciled_staging"
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = []
        source_packet = {
            "source_hash": dossier["source_hash"],
            "adversaries": ["Simon Vey's Hired Scout"],
        }
        effective = build_effective_adaptation_guardrail_input(
            dossier,
            source_packet=source_packet,
        )["effective_guardrail_input"]
        commands = []

        def fake_builder(command, **_kwargs):
            commands.append(command)
            output_directory = Path(command[command.index("--output-directory") + 1])
            output_path = output_directory / "monsters" / "simon_veys_hired_scout.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "name": "Simon Vey's Hired Scout",
                        "size": "Medium",
                        "alignment": "neutral",
                        "armorClass": 13,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            report = build_adaptation_monster_guardrail_report(
                effective,
                module_dir=staging,
                staging_root=staging,
                compendium_lookup={},
                allow_generation=True,
                generation_opt_in=True,
                monster_builder_path=builder,
                generation_timeout_seconds=5,
            )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["monsters_generated"], 1)
        self.assertEqual(commands[0][2], "Simon Vey's Hired Scout")
        self.assertNotEqual(commands[0][2], "Simon Vey")

    def test_unsupported_source_prose_is_not_promoted(self):
        dossier = _load_fixture()
        source_packet = {
            "source_hash": dossier["source_hash"],
            "encounter_seeds": [
                "Simon Vey's Hired Scout appears near the quay",
            ],
        }

        result = build_effective_adaptation_guardrail_input(
            dossier,
            source_packet=source_packet,
        )

        self.assertFalse(result["reconciliation_report"]["source_reconciled"])
        self.assertEqual(
            result["effective_dossier"]["encounter_seeds"],
            dossier["encounter_seeds"],
        )

    def test_legacy_dossier_does_not_use_source_reconciliation(self):
        dossier = _load_fixture()
        dossier["adaptation_mode"] = "legacy"
        source_packet = {
            "source_hash": dossier["source_hash"],
            "monster_refs": ["Should Not Be Added"],
        }

        result = build_effective_adaptation_guardrail_input(
            dossier,
            source_packet=source_packet,
        )

        self.assertFalse(result["reconciliation_report"]["source_reconciled"])
        self.assertEqual(result["effective_dossier"], dossier)

    def test_report_reuses_artifact_and_binds_encounter(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        (TEST_ROOT / "monsters").mkdir()
        (TEST_ROOT / "monsters" / "smuggler.json").write_text(
            json.dumps(
                {"size": "Medium", "alignment": "neutral", "armorClass": 12}
            ),
            encoding="utf-8",
        )
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Smuggler"]

        report = build_adaptation_monster_guardrail_report(dossier, TEST_ROOT)

        self.assertEqual(report["version"], ADAPTATION_MONSTER_GUARDRAIL_VERSION)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["monsters_reused"], 1)
        self.assertEqual(report["encounters_bound"], 1)
        self.assertEqual(report["unresolved_refs"], [])
        self.assertTrue(report["resolution_diagnostics"][0]["schema_sufficient"])

    def test_amphail_alias_shape_binds_all_four_seeds(self):
        """Quantity and plural aliases bind to canonical resolution entries."""
        seeds = [
            {"name": "Memory theft", "adversaries": ["Memory-thief impersonation", "Slime spawn"]},
            {"name": "Impersonation", "adversaries": ["Memory-thief impersonations", "Slime spawn"]},
            {"name": "Town edge", "adversaries": ["Two slime spawn", "Town impersonation"]},
            {"name": "Colony", "adversaries": ["Memory-eating slime colony", "Slime spawn"]},
        ]
        resolution_log = [
            {"ref": "Memory-thief impersonation", "canonical_slug": "memory_thief_impersonation", "status": "reused", "artifact_path": "memory.json"},
            {"ref": "Slime spawn", "canonical_slug": "slime_spawn", "status": "reused", "artifact_path": "slime.json"},
            {"ref": "Town impersonation", "canonical_slug": "town_impersonation", "status": "reused", "artifact_path": "town.json"},
            {"ref": "Memory-eating slime colony", "canonical_slug": "memory_eating_slime_colony", "status": "reused", "artifact_path": "colony.json"},
        ]

        result = _bind_adaptation_encounters(seeds, resolution_log)

        self.assertEqual(result["seeds_bound"], 4)
        self.assertEqual(result["seeds_unresolved"], 0)
        self.assertEqual(result["seeds_unbound"], 0)
        self.assertEqual([binding["status"] for binding in result["bindings"]], ["bound"] * 4)

    def test_amphail_context_lookup_uses_folded_identity(self):
        seeds = [{
            "name": "Amphail gate",
            "location": "North road",
            "adversaries": ["Two slime spawn"],
        }]

        contexts = _encounter_contexts(seeds, "Slime Spawn")

        self.assertEqual(contexts[0]["name"], "Amphail gate")
        self.assertEqual(contexts[0]["location"], "North road")

    def test_mixed_resolved_and_unresolved_seed_remains_fail_closed(self):
        seeds = [{"adversaries": ["Slime spawn", "Memory-thief impersonations"]}]
        resolution_log = [
            {"ref": "Slime spawn", "canonical_slug": "slime_spawn", "status": "reused", "artifact_path": "slime.json"},
            {"ref": "Memory-thief impersonations", "canonical_slug": "memory_thief_impersonation", "status": "unresolved", "artifact_path": None},
        ]

        result = _bind_adaptation_encounters(seeds, resolution_log)

        self.assertEqual(result["bindings"][0]["status"], "unresolved")
        self.assertEqual(result["seeds_bound"], 0)
        self.assertEqual(result["seeds_unresolved"], 1)
        self.assertEqual(result["bindings"][0]["unresolved_refs"], ["Memory-thief impersonations"])

    def test_scene_hazard_labels_are_excluded_without_generation(self):
        staging = TEST_ROOT / "scene_only"
        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["False villager", "False villagers", "Glyph ward", "Cave hazards"],
                encounter_seeds=[{
                    "name": "Ward scene",
                    "adversaries": ["False villagers", "Glyph ward", "Cave hazards"],
                }],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=TEST_ROOT / "missing_builder.py",
            )

        run.assert_not_called()
        self.assertEqual(result["monsters_unresolved"], 0)
        self.assertEqual(result["unresolved_refs"], [])
        self.assertEqual(result["monsters_excluded"], 4)
        self.assertEqual(result["encounters_scene_resolved"], 1)
        self.assertEqual(
            {entry["reason"] for entry in result["resolution_log"]},
            {"non_monster_scene_entity"},
        )
        self.assertEqual(result["encounters_unbound"], 0)
        self.assertEqual(result["encounter_bindings"][0]["status"], "scene_resolved")

    def test_existing_artifact_precedes_scene_label_exclusion(self):
        staging = TEST_ROOT / "scene_reusable"
        self._write_monster(
            staging,
            "false_villager",
            {"name": "False Villager", "size": "Medium", "alignment": "neutral", "armorClass": 10},
        )
        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["False Villager"],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=TEST_ROOT / "missing_builder.py",
            )

        run.assert_not_called()
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_excluded"], 0)
        self.assertEqual(result["unresolved_refs"], [])

    def test_descriptive_reusable_root_precedes_scene_label_exclusion(self):
        staging = TEST_ROOT / "descriptive_scene_reusable"
        reusable = TEST_ROOT / "reusable_root"
        source = self._write_monster(
            reusable,
            "2_false_villagers_at_gate",
            {
                "name": "False Villagers",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 11,
            },
        )
        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["False Villagers"],
                reusable_module_dirs=[reusable],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=TEST_ROOT / "missing_builder.py",
            )

        run.assert_not_called()
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_excluded"], 0)
        self.assertEqual(result["resolution_log"][0]["source"], "module_scan[0]")
        self.assertTrue(source.is_file())

    def test_compendium_scene_label_precedes_exclusion(self):
        result = materialize_adaptation_monsters(
            TEST_ROOT / "compendium_scene",
            ["Glyph ward"],
            compendium_lookup={
                "Glyph ward": {
                    "name": "Glyph Ward",
                    "size": "Small",
                    "alignment": "unaligned",
                    "armorClass": 15,
                }
            },
            allow_generation=False,
        )

        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_excluded"], 0)
        self.assertEqual(result["unresolved_refs"], [])

    def test_approved_memory_eating_ooze_remains_generatable(self):
        staging = TEST_ROOT / "ooze"
        builder = TEST_ROOT / "ooze_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")

        def fake_builder(command, **_kwargs):
            output_directory = Path(command[command.index("--output-directory") + 1])
            target = output_directory / "monsters" / "memory_eating_ooze.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({
                "name": "Memory-eating Ooze",
                "size": "Medium",
                "alignment": "unaligned",
                "armorClass": 12,
            }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Memory-eating Ooze"],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=builder,
            )

        run.assert_called_once()
        self.assertEqual(result["monsters_generated"], 1)
        self.assertEqual(result["monsters_excluded"], 0)
        self.assertEqual(result["unresolved_refs"], [])

    def test_unresolved_canonical_identity_remains_fail_closed(self):
        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                TEST_ROOT / "unresolved_canonical",
                ["Canonical Missing Beast"],
                compendium_lookup={},
                allow_generation=False,
            )

        run.assert_not_called()
        self.assertEqual(result["monsters_unresolved"], 1)
        self.assertEqual(result["unresolved_refs"], ["Canonical Missing Beast"])
        self.assertEqual(result["non_monster_refs"], [])

    def test_report_generates_canonical_monster_in_fresh_staging(self):
        staging = TEST_ROOT / "fresh_staging"
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Generated Beast"]

        def fake_builder(command, **_kwargs):
            self.assertNotIn("--module", command)
            output_directory = Path(
                command[command.index("--output-directory") + 1]
            )
            output_path = output_directory / "monsters" / "generated_beast.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {"name": "Generated Beast", "size": "Medium", "alignment": "neutral", "armorClass": 13}
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ) as run:
            report = build_adaptation_monster_guardrail_report(
                dossier,
                module_dir=staging,
                staging_root=staging,
                compendium_lookup={},
                allow_generation=True,
                generation_opt_in=True,
                monster_builder_path=builder,
                generation_timeout_seconds=5,
            )

        run.assert_called_once()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["monsters_generated"], 1)
        self.assertEqual(report["monsters_unresolved"], 0)
        self.assertTrue((staging / "monsters" / "generated_beast.json").is_file())

    def test_report_disabled_generation_blocks_fresh_staging_without_subprocess(self):
        staging = TEST_ROOT / "disabled_staging"
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Missing Beast"]

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            report = build_adaptation_monster_guardrail_report(
                dossier,
                module_dir=staging,
                staging_root=staging,
                compendium_lookup={},
                allow_generation=False,
                monster_builder_path=builder,
            )

        run.assert_not_called()

    def test_wrapper_reusable_root_descends_to_contained_staging_module(self):
        wrapper = TEST_ROOT / "gate_target"
        module_root = wrapper / "hostis-gate-verification" / "revision_000"
        monster_path = module_root / "monsters" / "goblin.json"
        monster_path.parent.mkdir(parents=True, exist_ok=True)
        (module_root / "staging_metadata.json").write_text("{}", encoding="utf-8")
        monster_path.write_text(
            json.dumps({"name": "Goblin", "size": "Small", "alignment": "neutral", "armorClass": 15}),
            encoding="utf-8",
        )
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Goblin"]
        report = materialize_adaptation_monsters(
            TEST_ROOT / "staging",
            ["Goblin"],
            dossier["encounter_seeds"],
            reusable_module_dirs=[wrapper],
            compendium_lookup={},
        )
        self.assertEqual(report["monsters_reused"], 1)
        self.assertEqual(report["monsters_unresolved"], 0)
        self.assertIn("hostis-gate-verification", report["resolution_log"][0]["source_path"])

    def test_symlinked_reusable_root_and_nested_directory_are_not_followed(self):
        """Reusable discovery must not escape through supplied symlinks."""
        wrapper = TEST_ROOT / "symlink_wrapper"
        outside = TEST_ROOT / "outside_module"
        outside_monster = self._write_monster(
            outside,
            "escaped_beast",
            {"name": "Escaped Beast", "size": "Medium", "alignment": "neutral", "armorClass": 13},
        )
        wrapper.mkdir(parents=True, exist_ok=True)
        os.symlink(outside, wrapper / "linked_module")

        staging = TEST_ROOT / "symlink_staging"
        report = materialize_adaptation_monsters(
            staging,
            ["Escaped Beast"],
            reusable_module_dirs=[wrapper],
            compendium_lookup={},
        )

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["unresolved_refs"], ["Escaped Beast"])
        self.assertFalse((staging / "monsters" / "escaped_beast.json").exists())
        self.assertTrue(outside_monster.is_file())

        supplied_symlink = TEST_ROOT / "supplied_root_link"
        os.symlink(outside, supplied_symlink)
        report = materialize_adaptation_monsters(
            TEST_ROOT / "symlink_root_staging",
            ["Escaped Beast"],
            reusable_module_dirs=[supplied_symlink],
            compendium_lookup={},
        )
        self.assertEqual(report["status"], "degraded")
        self.assertFalse(
            (TEST_ROOT / "symlink_root_staging" / "monsters" / "escaped_beast.json").exists()
        )

    def test_unmarked_nested_monster_directory_is_rejected_but_marked_root_is_found(self):
        """Nested discovery requires a recognized module or staging marker."""
        wrapper = TEST_ROOT / "marker_wrapper"
        unmarked = wrapper / "unmarked" / "monsters"
        unmarked.mkdir(parents=True, exist_ok=True)
        self._write_monster(
            wrapper / "unmarked",
            "marker_beast",
            {"name": "Marker Beast", "size": "Medium", "alignment": "neutral", "armorClass": 12},
        )
        marked = wrapper / "marked" / "revision_000"
        marked.mkdir(parents=True, exist_ok=True)
        (marked / "staging_metadata.json").write_text("{}", encoding="utf-8")
        self._write_monster(
            marked,
            "marker_beast",
            {"name": "Marker Beast", "size": "Medium", "alignment": "neutral", "armorClass": 14},
        )

        report = materialize_adaptation_monsters(
            TEST_ROOT / "marker_staging",
            ["Marker Beast"],
            reusable_module_dirs=[wrapper],
            compendium_lookup={},
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["monsters_reused"], 1)
        self.assertIn("marked", report["resolution_log"][0]["source_path"])
        self.assertEqual(
            json.loads((TEST_ROOT / "marker_staging" / "monsters" / "marker_beast.json").read_text(encoding="utf-8"))["armorClass"],
            14,
        )

    def test_missing_artifact_diagnostic_has_no_required_fields(self):
        report = materialize_adaptation_monsters(
            TEST_ROOT / "missing-diagnostic",
            ["Missing Beast"],
            [{"adversaries": ["Missing Beast"]}],
            compendium_lookup={},
        )
        unresolved = report["resolution_log"][0]
        self.assertEqual(unresolved["reason"], "file_not_found")
        self.assertEqual(unresolved["missing_required_fields"], [])

    def test_generation_policy_requires_explicit_opt_in_when_requested(self):
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Missing Beast"]
        report = build_adaptation_monster_guardrail_report(
            dossier,
            TEST_ROOT / "policy",
            compendium_lookup={},
            allow_generation=True,
            generation_opt_in=False,
        )
        self.assertFalse(report["generation_policy"]["enabled"])
        self.assertEqual(report["generation_policy"]["reason"], "explicit_opt_in_missing_or_invalid")
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["unresolved_refs"], ["Missing Beast"])
        self.assertEqual(report["monsters_generated"], 0)
        self.assertFalse(report["generation_policy"]["explicit_opt_in"])
        self.assertIsNone(report["generation_policy"]["timeout_seconds"])

    def test_generation_policy_enabled_reports_bounded_timeout(self):
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Policy Beast"]
        builder = TEST_ROOT / "policy_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")

        def fake_builder(command, **_kwargs):
            output = Path(command[command.index("--output-directory") + 1]) / "monsters" / "policy_beast.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"name": "Policy Beast", "size": "Medium", "alignment": "neutral", "armorClass": 13}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("utils.toolkit_adaptation_monster_guardrail.subprocess.run", side_effect=fake_builder):
            report = build_adaptation_monster_guardrail_report(
                dossier,
                TEST_ROOT / "enabled_policy",
                compendium_lookup={},
                allow_generation=True,
                generation_opt_in=True,
                monster_builder_path=builder,
                generation_timeout_seconds=9999,
            )
        self.assertTrue(report["generation_policy"]["enabled"])
        self.assertEqual(report["generation_policy"]["reason"], "explicit_opt_in")
        self.assertTrue(report["generation_policy"]["explicit_opt_in"])
        self.assertEqual(report["generation_policy"]["timeout_seconds"], 600.0)

    def test_missing_artifact_has_bounded_reason_and_encounter_context(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        dossier = _load_fixture()
        dossier["encounter_seeds"][0].update(
            {
                "name": "Gatehouse watch",
                "location": "North Gate",
                "source_basis": "chapter 2 adversary list",
                "adversaries": ["Missing Beast"],
            }
        )

        report = build_adaptation_monster_guardrail_report(dossier, TEST_ROOT)

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["unresolved_refs"], ["Missing Beast"])
        diagnostic = report["unresolved_diagnostics"][0]
        self.assertEqual(diagnostic["ref"], "Missing Beast")
        self.assertEqual(diagnostic["reason"], "file_not_found")
        self.assertFalse(diagnostic["schema_sufficient"])
        self.assertTrue(diagnostic["artifact_path"].endswith("missing_beast.json"))
        context = diagnostic["encounter_context"][0]
        self.assertEqual(context["encounter_index"], 0)
        self.assertEqual(context["name"], "Gatehouse watch")
        self.assertEqual(context["location"], "North Gate")
        self.assertEqual(context["source_basis"], "chapter 2 adversary list")

    def test_incomplete_artifact_reports_required_fields_without_substitution(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        (TEST_ROOT / "monsters").mkdir()
        (TEST_ROOT / "monsters" / "incomplete_beast.json").write_text(
            json.dumps({"size": "Large", "alignment": None}),
            encoding="utf-8",
        )
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Incomplete Beast"]

        report = build_adaptation_monster_guardrail_report(dossier, TEST_ROOT)

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["unresolved_refs"], ["Incomplete Beast"])
        diagnostic = report["unresolved_diagnostics"][0]
        self.assertEqual(diagnostic["ref"], "Incomplete Beast")
        self.assertEqual(diagnostic["reason"], "missing_required_fields")
        self.assertEqual(
            diagnostic["missing_required_fields"], ["alignment", "armorClass"]
        )
        self.assertFalse(diagnostic["schema_sufficient"])
        self.assertNotIn("canonical_name", diagnostic)
        self.assertNotIn("replacement", json.dumps(diagnostic, sort_keys=True))

    def test_malformed_optional_input_fails_open_without_payload_copy(self):
        report = build_adaptation_monster_guardrail_report(
            {"encounter_seeds": "not-a-list", "provider_payload": "secret"},
            TEST_ROOT,
        )

        self.assertEqual(report["status"], "skipped")
        self.assertTrue(report["diagnostics"])
        self.assertNotIn("secret", json.dumps(report, sort_keys=True))
        self.assertNotIn("provider_payload", report)

    def test_report_preserves_raw_and_canonical_identity_provenance(self):
        staging = TEST_ROOT / "provenance_staging"
        self._write_monster(
            staging,
            "slime_spawn",
            {
                "name": "Slime Spawn",
                "size": "Medium",
                "alignment": "unaligned",
                "armorClass": 10,
            },
        )
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Two slime spawn"]

        report = build_adaptation_monster_guardrail_report(dossier, staging)

        self.assertEqual(report["status"], "pass")
        resolution = report["resolution_diagnostics"][0]
        self.assertEqual(resolution["raw_reference"], "Two slime spawn")
        self.assertEqual(resolution["canonical_identity"], "slime_spawn")
        self.assertEqual(resolution["canonical_name"], "slime spawn")
        self.assertEqual(resolution["selected_resolution_variant"], "folded_canonical")
        self.assertEqual(resolution["resolution_source"], "staging_folded")
        self.assertIn("two slime spawn", resolution["identity_variants"])
        self.assertIn("slime spawn", resolution["identity_variants"])

    def test_report_diagnostics_are_bounded_ascii_and_provider_payload_free(self):
        staging = TEST_ROOT / "diagnostic_safety_staging"
        dossier = _load_fixture()
        dossier["encounter_seeds"][0].update(
            {
                "name": "Gate 8",
                "adversaries": ["Two Missing Beasts"],
                "provider_payload": {
                    "prompt": "do not copy this",
                    "raw_response": "secret response",
                },
            }
        )

        report = build_adaptation_monster_guardrail_report(dossier, staging)
        serialized = json.dumps(report, sort_keys=True)

        self.assertNotIn("provider_payload", serialized)
        self.assertNotIn("raw_response", serialized)
        self.assertNotIn("secret response", serialized)
        self.assertTrue(serialized.isascii())
        for diagnostic in report["resolution_diagnostics"] + report["unresolved_diagnostics"]:
            self.assertLessEqual(len(diagnostic.get("raw_reference", "")), 160)
            self.assertLessEqual(len(diagnostic.get("canonical_identity", "")), 160)
            for value in diagnostic.values():
                if isinstance(value, str):
                    self.assertTrue(value.isascii())

    def test_normalizes_quantity_and_descriptive_creature_phrase(self):
        result = normalize_adaptation_location_monsters(
            [
                {
                    "name": "Three shadowy goblins guarding the gate",
                    "quantity": {"min": 1, "max": 3},
                    "description": "They avoid the torchlight.",
                }
            ],
            ["Goblin"],
            source_location="Gatehouse",
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["normalized_refs"], ["Goblin"])
        normalized = result["normalized_monsters"][0]
        self.assertEqual(normalized["name"], "Goblin")
        self.assertEqual(normalized["quantity"], {"min": 1, "max": 3})
        self.assertIn("shadowy", normalized["descriptive_prose"])
        self.assertIn("guarding the gate", normalized["descriptive_prose"])
        self.assertIn("avoid the torchlight", normalized["descriptive_prose"])
        self.assertEqual(normalized["original_text"], "Three shadowy goblins guarding the gate")
        self.assertEqual(normalized["source_location"], "Gatehouse")

    def test_registry_driven_amphail_normalization_preserves_quantity_and_prose(self):
        staging = TEST_ROOT / "amphail_registry_staging"
        self._write_monster(
            staging,
            "cave_guardian",
            {
                "name": "Cave Guardian",
                "size": "Medium",
                "alignment": "unaligned",
                "armorClass": 14,
            },
        )
        dossier = {
            "adaptation_mode": "llm_adaptation",
            "encounter_seeds": [
                {"id": "K06", "adversaries": ["Cave guardians"]},
                {"id": "K08", "adversaries": ["Cave Guardian"]},
                {"id": "K10", "adversaries": ["2 Cave guardians"]},
            ],
        }
        registry = build_adaptation_canonical_monster_registry(
            dossier,
            staging_root=staging,
            approved_canonical_identities=["Cave Guardian"],
        )
        k06 = normalize_adaptation_location_monsters(
            [{"name": "Cave guardians", "quantity": {"min": 1, "max": 1}}],
            [],
            canonical_registry=registry,
            source_location="K06",
        )
        k08 = normalize_adaptation_location_monsters(
            [{
                "name": "Cave Guardian",
                "quantity": {"min": 1, "max": 1},
                "description": "Two slime-coated chairs flank the guardian.",
            }],
            [],
            canonical_registry=registry,
            source_location="K08",
        )
        k10 = normalize_adaptation_location_monsters(
            [{"name": "2 Cave guardians"}],
            [],
            canonical_registry=registry,
            source_location="K10",
        )
        self.assertEqual(k06["normalized_refs"], ["Cave Guardian"])
        self.assertEqual(k06["normalized_monsters"][0]["quantity"], {"min": 1, "max": 1})
        self.assertEqual(k08["normalized_monsters"][0]["quantity"], {"min": 1, "max": 1})
        self.assertIn("two slime-coated chairs", k08["normalized_monsters"][0]["descriptive_prose"].lower())
        self.assertEqual(k08["contradiction_diagnostics"][0]["code"], "quantity_prose_contradiction")
        self.assertEqual(k10["normalized_monsters"][0]["quantity"], {"min": 2, "max": 2})

        materialized = materialize_adaptation_monsters(
            staging,
            ["Cave guardians"],
            dossier["encounter_seeds"],
            canonical_registry=registry,
            reusable_module_dirs=[staging],
        )
        self.assertEqual(materialized["status"], "pass")
        self.assertTrue((staging / "monsters" / "cave_guardian.json").is_file())
        self.assertFalse((staging / "monsters" / "cave_guardians.json").exists())
        self.assertEqual(materialized["resolution_log"][0]["ref"], "Cave guardians")
        self.assertEqual(materialized["resolution_log"][0]["canonical_slug"], "cave_guardian")

    def test_embedded_quantity_prefers_unambiguous_creature_after_owner(self):
        result = normalize_adaptation_location_monsters(
            ["Vask's 2 grimlock attendants"],
            ["Vask", "Grimlock"],
            source_location="Salt Quay",
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["normalized_refs"], ["Grimlock"])
        normalized = result["normalized_monsters"][0]
        self.assertEqual(normalized["name"], "Grimlock")
        self.assertEqual(normalized["quantity"], {"min": 2, "max": 2})
        self.assertIn("vask", normalized["descriptive_prose"])
        self.assertIn("attendants", normalized["descriptive_prose"])
        self.assertEqual(result["unresolved_entries"], [])

    def test_named_custom_adversary_does_not_map_to_possessive_owner(self):
        result = normalize_adaptation_location_monsters(
            ["Simon Vey's Hired Scout"],
            ["Simon Vey"],
            source_location="Salt Quay",
        )

        self.assertEqual(result["normalized_monsters"], [])
        self.assertEqual(result["unresolved_entries"][0]["classification"], "unresolved_prose")
        self.assertEqual(result["unresolved_entries"][0]["original_text"], "Simon Vey's Hired Scout")

    def test_excludes_npc_and_ally_entries_without_materialization_identity(self):
        result = normalize_adaptation_location_monsters(
            ["NPC Mira the healer", "Allied workers at the mill"],
            ["Goblin"],
            known_npcs=["Mira the healer"],
        )

        self.assertEqual(result["normalized_monsters"], [])
        self.assertEqual(len(result["excluded_entries"]), 2)
        classifications = {entry["classification"] for entry in result["excluded_entries"]}
        self.assertIn("npc", classifications)
        self.assertIn("ally", classifications)
        self.assertEqual(result["unresolved_entries"], [])

    def test_ambiguous_phrase_is_diagnosed_without_substitution(self):
        result = normalize_adaptation_location_monsters(
            ["A figure resembling a goblin or kobold"],
            ["Goblin", "Kobold"],
            source_location="Ruined camp",
        )

        self.assertEqual(result["normalized_monsters"], [])
        self.assertEqual(len(result["unresolved_entries"]), 1)
        unresolved = result["unresolved_entries"][0]
        self.assertEqual(unresolved["classification"], "ambiguous")
        self.assertIn("goblin or kobold", unresolved["original_text"])
        self.assertEqual(unresolved["source_location"], "Ruined camp")

    def test_staged_module_normalization_removes_raw_prose_before_closure(self):
        staging = TEST_ROOT / "staged_module"
        area_path = staging / "areas" / "A001.json"
        area_path.parent.mkdir(parents=True, exist_ok=True)
        area_path.write_text(
            json.dumps(
                {
                    "areaId": "A001",
                    "locations": [
                        {
                            "locationId": "A01",
                            "name": "Gatehouse",
                            "description": "A guarded gate.",
                            "monsters": [
                                {"name": "Three shadowy goblins guarding the gate"},
                                "NPC Mira the healer",
                                "A figure resembling a goblin or kobold",
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        dossier = _load_fixture()
        dossier["npc_seeds"] = [{"name": "Mira", "role": "healer"}]
        dossier["encounter_seeds"][0]["adversaries"] = ["Goblin"]

        report = normalize_adaptation_module_monsters(
            staging,
            dossier,
            canonical_vocabulary=["Goblin", "Kobold"],
        )

        normalized_area = json.loads(area_path.read_text(encoding="utf-8"))
        monsters = normalized_area["locations"][0]["monsters"]
        self.assertEqual([entry["name"] for entry in monsters], ["Goblin"])
        guidance = normalized_area["locations"][0]["dmInstructions"]
        self.assertIn("NPC Mira the healer", guidance)
        self.assertIn("goblin or kobold", guidance)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(len(report["excluded_entries"]), 1)
        self.assertEqual(len(report["unresolved_entries"]), 1)
        self.assertTrue(report["files_changed"])

    def test_bounds_and_ascii_output_are_deterministic(self):
        entries = ["Goblin " + str(index) for index in range(140)]
        result = normalize_adaptation_location_monsters(entries, ["Goblin"])
        encoded = json.dumps(result, sort_keys=True).encode("ascii")

        self.assertLessEqual(result["entries_seen"], 128)
        self.assertLessEqual(len(result["unresolved_entries"]), 128)
        self.assertLessEqual(len(encoded), 50000)
        self.assertNotIn("?", encoded.decode("ascii")[:20])

    def _write_monster(self, root, name, payload):
        path = root / "monsters" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _snapshot_tree(self, root):
        """Snapshot a project-local module-like tree without mutating it."""
        if not root.exists() and not root.is_symlink():
            return {}
        snapshot = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            elif path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                snapshot[relative] = ("file", digest)
            elif path.is_dir():
                snapshot[relative] = ("directory",)
        return snapshot

    def _make_live_module_like_tree(self):
        """Create a disposable live-module-shaped source tree for isolation tests."""
        live_module = TEST_ROOT / "modules" / "Adapted_Live_Module"
        self._write_monster(
            live_module,
            "existing_beast",
            {"size": "Medium", "alignment": "neutral", "armorClass": 13},
        )
        (live_module / "module_context.json").write_text(
            json.dumps({"title": "Untouched adaptation module"}),
            encoding="utf-8",
        )
        (live_module / "sentinel.txt").write_text(
            "live module must remain byte-for-byte unchanged",
            encoding="utf-8",
        )
        return live_module

    def test_materialization_reuses_schema_sufficient_staging_artifact(self):
        staging = TEST_ROOT / "staging"
        target = self._write_monster(
            staging,
            "staging_beast",
            {"size": "Medium", "alignment": "neutral", "armorClass": 12},
        )

        result = materialize_adaptation_monsters(staging, ["Staging Beast"])

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["resolution_log"][0]["source"], "staging")
        self.assertEqual(Path(result["artifact_paths"][0]), target)

    def test_materialization_reuses_reusable_artifact_into_staging(self):
        staging = TEST_ROOT / "staging"
        source_module = TEST_ROOT / "source_module"
        source = self._write_monster(
            source_module,
            "module_beast",
            {"size": "Large", "alignment": "evil", "armorClass": 15},
        )

        result = materialize_adaptation_monsters(
            staging,
            ["Module Beast"],
            reusable_module_dirs=[source_module],
        )

        staged = staging / "monsters" / "module_beast.json"
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["resolution_log"][0]["source"], "reusable")
        self.assertTrue(staged.is_file())
        self.assertEqual(json.loads(staged.read_text(encoding="utf-8")), json.loads(source.read_text(encoding="utf-8")))

    def test_materialization_exact_plural_artifact_precedes_folded_singular(self):
        staging = TEST_ROOT / "staging"
        source_module = TEST_ROOT / "source_module"
        exact = self._write_monster(
            source_module,
            "memory_thief_impersonations",
            {
                "name": "Memory-thief impersonations",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 14,
            },
        )
        self._write_monster(
            source_module,
            "memory_thief_impersonation",
            {
                "name": "Memory-thief impersonation",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 12,
            },
        )

        result = materialize_adaptation_monsters(
            staging,
            ["Memory-thief impersonations"],
            reusable_module_dirs=[source_module],
            compendium_lookup={},
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["resolution_log"][0]["source"], "reusable")
        self.assertEqual(
            json.loads(
                (staging / "monsters" / "memory_thief_impersonations.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads(exact.read_text(encoding="utf-8")),
        )
        self.assertFalse(
            (staging / "monsters" / "memory_thief_impersonation.json").exists()
        )

    def test_materialization_duplicate_folded_refs_generate_one_canonical_artifact(self):
        staging = TEST_ROOT / "staging"
        builder = TEST_ROOT / "builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# deterministic builder seam\n", encoding="utf-8")
        commands = []

        def fake_builder(command, **_kwargs):
            commands.append(command)
            output = (
                Path(command[command.index("--output-directory") + 1])
                / "monsters"
                / "slime_spawn.json"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "name": "Slime Spawn",
                        "size": "Medium",
                        "alignment": "unaligned",
                        "armorClass": 10,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                ["Two slime spawn", "Slime Spawn"],
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=["Slime Spawn"],
                monster_builder_path=builder,
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_planned"], 1)
        self.assertEqual(result["monsters_generated"], 1)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][2], "Slime Spawn")
        self.assertTrue((staging / "monsters" / "slime_spawn.json").is_file())
        self.assertFalse(
            (staging / "monsters" / "two_slime_spawn.json").exists()
        )

    def test_amphail_labels_generate_singular_payloads_and_bind_four_seeds(self):
        """The exact Amphail aliases converge before generation and binding."""
        staging = TEST_ROOT / "amphail_generation_staging"
        builder = TEST_ROOT / "amphail_generation_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        commands = []
        payloads = {
            "Memory Thief Impersonation": "memory_thief_impersonation",
            "Slime Spawn": "slime_spawn",
        }

        def fake_builder(command, **_kwargs):
            commands.append(command)
            name = command[2]
            output = (
                Path(command[command.index("--output-directory") + 1])
                / "monsters"
                / f"{payloads[name]}.json"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "name": name,
                        "size": "Medium",
                        "alignment": "neutral",
                        "armorClass": 12,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        seeds = [
            {"name": "Memory theft", "adversaries": ["Memory-thief impersonations"]},
            {"name": "Slime attack", "adversaries": ["Two slime spawn"]},
            {"name": "Impersonation", "adversaries": ["Memory-thief impersonation"]},
            {"name": "Slime aftermath", "adversaries": ["Slime spawn"]},
        ]
        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                ["Memory-thief impersonations", "Two slime spawn"],
                encounter_seeds=seeds,
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=[
                    "Memory-thief impersonations",
                    "Two slime spawn",
                ],
                monster_builder_path=builder,
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_planned"], 2)
        self.assertEqual(result["monsters_generated"], 2)
        self.assertEqual(result["monsters_unresolved"], 0)
        self.assertEqual(result["encounters_planned"], 4)
        self.assertEqual(result["encounters_bound"], 4)
        self.assertEqual(result["encounters_unbound"], 0)
        self.assertEqual(
            sorted(command[2] for command in commands),
            ["Memory Thief Impersonation", "Slime Spawn"],
        )
        monster_files = sorted(path.name for path in (staging / "monsters").glob("*.json"))
        self.assertEqual(
            monster_files,
            ["memory_thief_impersonation.json", "slime_spawn.json"],
        )
        self.assertEqual(
            [json.loads((staging / "monsters" / name).read_text(encoding="utf-8"))["name"]
             for name in monster_files],
            ["Memory Thief Impersonation", "Slime Spawn"],
        )

    def test_amphail_exact_reusable_aliases_precede_folded_lookup_and_generation(self):
        """Exact raw artifacts win without creating folded duplicates."""
        staging = TEST_ROOT / "amphail_exact_staging"
        reusable = TEST_ROOT / "amphail_exact_source"
        self._write_monster(
            reusable,
            "memory_thief_impersonations",
            {
                "name": "Memory-thief impersonations",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 14,
            },
        )
        self._write_monster(
            reusable,
            "two_slime_spawn",
            {
                "name": "Two slime spawn",
                "size": "Medium",
                "alignment": "unaligned",
                "armorClass": 10,
            },
        )
        self._write_monster(
            reusable,
            "memory_thief_impersonation",
            {
                "name": "Memory-thief impersonation",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 8,
            },
        )
        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Memory-thief impersonations", "Two slime spawn"],
                reusable_module_dirs=[reusable],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=TEST_ROOT / "must_not_run.py",
            )

        run.assert_not_called()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 2)
        self.assertEqual(
            sorted(path.name for path in (staging / "monsters").glob("*.json")),
            ["memory_thief_impersonations.json", "two_slime_spawn.json"],
        )
        self.assertEqual(
            json.loads(
                (staging / "monsters" / "memory_thief_impersonations.json").read_text(
                    encoding="utf-8"
                )
            )["armorClass"],
            14,
        )
        self.assertEqual(
            json.loads(
                (staging / "monsters" / "two_slime_spawn.json").read_text(
                    encoding="utf-8"
                )
            )["name"],
            "Two slime spawn",
        )
        self.assertFalse(
            (staging / "monsters" / "memory_thief_impersonation.json").exists()
        )
        self.assertFalse((staging / "monsters" / "slime_spawn.json").exists())

    def test_custom_and_broad_names_remain_distinct_during_generation(self):
        """Bounded folding does not merge custom or broad source identities."""
        staging = TEST_ROOT / "custom_identity_staging"
        builder = TEST_ROOT / "custom_identity_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        names = ["Guardian", "Ooze", "Vey's Hired Scout"]
        slugs = {
            "Guardian": "guardian",
            "Ooze": "ooze",
            "Vey's Hired Scout": "veys_hired_scout",
        }

        def fake_builder(command, **_kwargs):
            name = command[2]
            output = Path(command[command.index("--output-directory") + 1]) / "monsters"
            output.mkdir(parents=True, exist_ok=True)
            output.joinpath(f"{slugs[name]}.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "size": "Medium",
                        "alignment": "neutral",
                        "armorClass": 11,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                names,
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=names,
                monster_builder_path=builder,
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_generated"], 3)
        self.assertEqual(result["unresolved_refs"], [])
        self.assertEqual(
            sorted(path.name for path in (staging / "monsters").glob("*.json")),
            ["guardian.json", "ooze.json", "veys_hired_scout.json"],
        )

    def test_folded_descriptive_payload_reuse_accepts_singular_payload(self):
        staging = TEST_ROOT / "folded_descriptive_staging"
        reusable = TEST_ROOT / "folded_descriptive_source"
        source = self._write_monster(
            reusable,
            "2_memory_thief_impersonations_at_gate",
            {
                "name": "Memory-thief impersonation",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 14,
            },
        )

        result = materialize_adaptation_monsters(
            staging,
            ["Memory-thief impersonations"],
            reusable_module_dirs=[reusable],
            compendium_lookup={},
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["resolution_log"][0]["reason"], "reused_payload_name_match")
        self.assertEqual(
            json.loads((staging / "monsters" / "memory_thief_impersonation.json").read_text(encoding="utf-8")),
            json.loads(source.read_text(encoding="utf-8")),
        )

    def test_folded_generation_uses_approved_canonical_identity_name(self):
        staging = TEST_ROOT / "folded_generation_staging"
        builder = TEST_ROOT / "folded_generation_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        commands = []

        def fake_builder(command, **_kwargs):
            commands.append(command)
            output = Path(command[command.index("--output-directory") + 1]) / "monsters" / "memory_thief_impersonation.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({
                "name": "Memory Thief Impersonation",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 14,
            }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                ["Memory-thief impersonations"],
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=["Memory-thief impersonations"],
                monster_builder_path=builder,
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(commands[0][2], "Memory Thief Impersonation")
        self.assertEqual(result["monsters_generated"], 1)

    def test_folded_generation_rejects_schema_sufficient_substitution(self):
        staging = TEST_ROOT / "substitution_staging"
        builder = TEST_ROOT / "substitution_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")

        def fake_builder(command, **_kwargs):
            output = Path(command[command.index("--output-directory") + 1]) / "monsters" / "memory_thief_impersonation.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({
                "name": "Substituted Beast",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 14,
            }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                ["Memory-thief impersonations"],
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=["Memory-thief impersonations"],
                monster_builder_path=builder,
            )

        self.assertEqual(result["monsters_unresolved"], 1)
        self.assertEqual(result["unresolved_refs"], ["Memory-thief impersonations"])
        self.assertFalse((staging / "monsters" / "memory_thief_impersonation.json").exists())
        self.assertIn(
            "generation_identity_mismatch",
            {attempt["reason"] for attempt in result["resolution_log"][0]["attempts"]},
        )

    def test_materialization_checks_all_reusable_roots_before_budget(self):
        """An exact match in a later supplied root is never skipped."""
        staging = TEST_ROOT / "staging"
        roots = []
        for index in range(20):
            root = TEST_ROOT / f"root_{index:02d}"
            (root / "monsters").mkdir(parents=True, exist_ok=True)
            roots.append(root)
        source = self._write_monster(
            roots[-1],
            "late_exact_beast",
            {"name": "Late Exact Beast", "size": "Medium", "alignment": "neutral", "armorClass": 12},
        )
        result = materialize_adaptation_monsters(
            staging, ["Late Exact Beast"], reusable_module_dirs=roots, compendium_lookup={}
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertIn("[19]", result["resolution_log"][0]["source"])
        self.assertEqual(
            json.loads((staging / "monsters" / "late_exact_beast.json").read_text(encoding="utf-8")),
            json.loads(source.read_text(encoding="utf-8")),
        )

    def test_active_revision_contains_generated_artifacts_and_preserves_all_state_roots(self):
        """Generation and reuse remain inside the active revision boundary."""
        staging_target = create_adaptation_staging_target(
            "a" * 64,
            job_id="containment-fixture",
            source_path="scripts/fixtures/toolkit_adaptation_catalogue.md",
            module_slug="Containment_Fixture",
            staging_root="tmp/adaptation_monster_guardrail_test/active-staging",
            repo_root=REPO_ROOT,
        )
        staging = REPO_ROOT / staging_target["path"]
        earlier_root = TEST_ROOT / "reusable_earlier"
        later_root = TEST_ROOT / "reusable_later"
        self._write_monster(
            earlier_root,
            "late_reuse_beast",
            {"name": "Late Reuse Beast", "size": "Medium"},
        )
        reusable = self._write_monster(
            later_root,
            "late_reuse_beast",
            {
                "name": "Late Reuse Beast",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 14,
            },
        )
        live_module = self._make_live_module_like_tree()
        registry = TEST_ROOT / "modules" / "world_registry.json"
        campaign = TEST_ROOT / "modules" / "campaign.json"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text('{"modules": {"Existing": {"status": "published"}}}', encoding="utf-8")
        campaign.write_text('{"availableModules": ["Existing"]}', encoding="utf-8")
        protected = (live_module, registry, campaign)
        before = {
            path: self._snapshot_tree(path) if path.is_dir() else path.read_bytes()
            for path in protected
        }
        roots_before = {
            root: self._snapshot_tree(root)
            for root in (earlier_root, later_root)
        }
        builder = TEST_ROOT / "containment_builder.py"
        builder.write_text("# provider-free generation seam\n", encoding="utf-8")

        def fake_builder(command, **_kwargs):
            output_directory = Path(command[command.index("--output-directory") + 1])
            output = output_directory / "monsters" / "generated_contained_beast.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({
                    "name": "Generated Contained Beast",
                    "size": "Medium",
                    "alignment": "neutral",
                    "armorClass": 13,
                }),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                ["Late Reuse Beast", "Generated Contained Beast"],
                reusable_module_dirs=[earlier_root, later_root],
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=["Late Reuse Beast", "Generated Contained Beast"],
                monster_builder_path=builder,
                generation_context={
                    "approved_identities": ["Generated Contained Beast"],
                    "source_reference_ids": ["encounter-001"],
                },
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_generated"], 1)
        self.assertEqual(result["resolution_log"][0]["source"], "reusable[1]")
        self.assertTrue(reusable.is_file())
        self.assertEqual(
            {root: self._snapshot_tree(root) for root in (earlier_root, later_root)},
            roots_before,
        )
        for artifact in result["artifact_paths"]:
            artifact_path = Path(artifact)
            self.assertTrue(artifact_path.is_absolute())
            artifact_path.resolve().relative_to(staging.resolve())
            self.assertLessEqual(len(artifact), 320)
        self.assertTrue((staging / "monsters" / "late_reuse_beast.json").is_file())
        self.assertTrue((staging / "monsters" / "generated_contained_beast.json").is_file())
        validate_adaptation_staging_target(
            staging_target,
            source_hash="a" * 64,
            module_slug="Containment_Fixture",
            repo_root=REPO_ROOT,
        )
        for path, snapshot in before.items():
            current = self._snapshot_tree(path) if path.is_dir() else path.read_bytes()
            self.assertEqual(current, snapshot)
        self.assertFalse((REPO_ROOT / "modules" / "Containment_Fixture").exists())

    def test_materialization_checks_late_descriptive_root_before_generation(self):
        """A descriptive payload match is found in every supplied root."""
        staging = TEST_ROOT / "staging"
        roots = []
        for index in range(36):
            root = TEST_ROOT / f"descriptive_root_{index:02d}"
            (root / "monsters").mkdir(parents=True, exist_ok=True)
            roots.append(root)
        source = roots[-1] / "monsters" / "quantity_and_scene_description.json"
        source.write_text(
            json.dumps({
                "name": "Late Descriptive Beast",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 12,
            }),
            encoding="utf-8",
        )
        result = materialize_adaptation_monsters(
            staging,
            ["Late Descriptive Beast"],
            reusable_module_dirs=roots,
            compendium_lookup={},
            allow_generation=False,
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(
            json.loads((staging / "monsters" / "late_descriptive_beast.json").read_text(encoding="utf-8"))["name"],
            "Late Descriptive Beast",
        )

    def test_generation_rejects_unapproved_identity_and_substitution(self):
        staging = TEST_ROOT / "staging"
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# deterministic provider seam\n", encoding="utf-8")

        def fake_builder(command, **_kwargs):
            output = Path(command[command.index("--output-directory") + 1]) / "monsters" / "unapproved_beast.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({
                "name": "Substituted Beast",
                "size": "Medium",
                "alignment": "neutral",
                "armorClass": 12,
            }), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("utils.toolkit_adaptation_monster_guardrail.subprocess.run", side_effect=fake_builder) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Unapproved Beast"],
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=[],
                monster_builder_path=builder,
            )
        run.assert_not_called()
        self.assertEqual(result["status"], "degraded")
        self.assertIn("Unapproved Beast", result["unresolved_refs"])
        self.assertFalse((staging / "monsters" / "unapproved_beast.json").exists())

        with patch("utils.toolkit_adaptation_monster_guardrail.subprocess.run", side_effect=fake_builder):
            result = materialize_adaptation_monsters(
                TEST_ROOT / "substitution_staging",
                ["Unapproved Beast"],
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=["Unapproved Beast"],
                monster_builder_path=builder,
            )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["resolution_log"][0]["reason"], "generation_identity_mismatch")
        self.assertFalse((TEST_ROOT / "substitution_staging" / "monsters" / "unapproved_beast.json").exists())

    def test_generation_requires_requested_identity_in_python_approved_set(self):
        """An opt-in cannot authorize an identity absent from the approved set."""
        staging = TEST_ROOT / "approved_identity_staging"
        builder = TEST_ROOT / "approved_identity_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# deterministic provider seam\n", encoding="utf-8")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Requested Beast"],
                compendium_lookup={},
                allow_generation=True,
                approved_canonical_identities=["Other Beast"],
                monster_builder_path=builder,
            )

        run.assert_not_called()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["unresolved_refs"], ["Requested Beast"])
        self.assertEqual(
            result["resolution_log"][0]["attempts"][-1]["reason"],
            "identity_not_approved",
        )
        self.assertFalse(
            (staging / "monsters" / "requested_beast.json").exists()
        )

    def test_generation_rejects_malformed_and_incomplete_outputs(self):
        """Non-object and schema-insufficient generation never become artifacts."""
        builder = TEST_ROOT / "malformed_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        cases = {
            "non_object": [],
            "incomplete": {"name": "Rejected Beast", "size": "Medium"},
        }

        for case_name, payload in cases.items():
            with self.subTest(case_name=case_name):
                staging = TEST_ROOT / f"malformed_{case_name}"

                def fake_builder(command, payload=payload, **_kwargs):
                    output = (
                        Path(command[command.index("--output-directory") + 1])
                        / "monsters"
                        / "rejected_beast.json"
                    )
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(json.dumps(payload), encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, "", "")

                with patch(
                    "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
                    side_effect=fake_builder,
                ):
                    result = materialize_adaptation_monsters(
                        staging,
                        ["Rejected Beast"],
                        compendium_lookup={},
                        allow_generation=True,
                        approved_canonical_identities=["Rejected Beast"],
                        monster_builder_path=builder,
                    )

                self.assertEqual(result["status"], "degraded")
                self.assertEqual(result["monsters_generated"], 0)
                self.assertEqual(result["unresolved_refs"], ["Rejected Beast"])
                self.assertIn(
                    result["resolution_log"][0]["reason"],
                    {"generation_invalid_payload", "generation_incomplete_schema"},
                )
                self.assertFalse(
                    (staging / "monsters" / "rejected_beast.json").exists(),
                    "rejected output must not remain accepted in staging",
                )

    def test_generation_rejects_output_path_escape_before_builder_invocation(self):
        """Absolute and parent-traversal target paths fail closed pre-write."""
        builder = TEST_ROOT / "path_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        staging = TEST_ROOT / "path_staging"
        outside = TEST_ROOT / "outside.json"

        for unsafe_path in (outside, staging / ".." / "outside.json"):
            with self.subTest(unsafe_path=str(unsafe_path)):
                with patch(
                    "utils.toolkit_adaptation_monster_guardrail._monster_candidate_path",
                    return_value=str(unsafe_path),
                ), patch(
                    "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
                ) as run:
                    ok, reason, _missing = _generate_canonical_monster_in_staging(
                        "Path Beast",
                        "path_beast",
                        str(staging),
                        monster_builder_path=builder,
                    )

                self.assertFalse(ok)
                self.assertEqual(reason, "generation_target_outside_staging")
                run.assert_not_called()
                self.assertFalse(outside.exists())

    def test_generation_subprocess_output_is_not_projected_into_materialization(self):
        """Captured child streams never enter the adaptation result envelope."""
        staging = TEST_ROOT / "output_safety_staging"
        builder = TEST_ROOT / "output_safety_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        sentinel = "RAW_AI_RESPONSE_SENTINEL source prompt authorization"

        def fake_builder(command, **_kwargs):
            self.assertIn("--adaptation-safe-output", command)
            output = Path(command[command.index("--output-directory") + 1]) / "monsters" / "safe_beast.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({"name": "Safe Beast", "size": "Medium", "alignment": "neutral", "armorClass": 12}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, sentinel, sentinel)

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                ["Safe Beast"],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=builder,
            )

        self.assertEqual(result["status"], "pass")
        self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

    def test_generation_nonzero_exit_keeps_bounded_code_only(self):
        """Process failure remains actionable without persisting child output."""
        staging = TEST_ROOT / "nonzero_output_safety_staging"
        builder = TEST_ROOT / "nonzero_output_safety_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        sentinel = "RAW_STDERR_SENTINEL_FULL_PROVIDER_BODY"

        def fake_builder(command, **_kwargs):
            return subprocess.CompletedProcess(command, 17, sentinel, sentinel)

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            result = materialize_adaptation_monsters(
                staging,
                ["Exit Beast"],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=builder,
            )

        self.assertEqual(result["status"], "degraded")
        self.assertIn("generation_nonzero_exit", json.dumps(result, sort_keys=True))
        self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

    def test_invalid_generation_opt_in_never_invokes_generation_seam(self):
        """Missing, false, truthy-string, and numeric opt-ins remain blocked."""
        dossier = _load_fixture()
        dossier["encounter_seeds"][0]["adversaries"] = ["Opt In Beast"]
        invalid_values = (None, False, "true", "1", 0, 1, 1.0, [], {})
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                with patch(
                    "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
                ) as run:
                    report = build_adaptation_monster_guardrail_report(
                        dossier,
                        TEST_ROOT / f"opt_in_{repr(value).replace(' ', '_')}",
                        compendium_lookup={},
                        allow_generation=True,
                        generation_opt_in=value,
                        monster_builder_path=TEST_ROOT / "missing_builder.py",
                    )

                run.assert_not_called()
                self.assertEqual(report["status"], "degraded")
                self.assertEqual(report["monsters_generated"], 0)
                self.assertEqual(report["unresolved_refs"], ["Opt In Beast"])
                self.assertFalse(report["generation_policy"]["enabled"])

    def test_generation_context_is_bounded_and_identity_scoped(self):
        staging = TEST_ROOT / "context_staging"
        builder = TEST_ROOT / "context_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        captured = {}

        def fake_builder(command, **_kwargs):
            context_path = Path(command[command.index("--context-file") + 1])
            captured.update(json.loads(context_path.read_text(encoding="utf-8")))
            output = Path(command[command.index("--output-directory") + 1]) / "monsters" / "context_beast.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"name": "Context Beast", "size": "Medium", "alignment": "neutral", "armorClass": 12}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("utils.toolkit_adaptation_monster_guardrail.subprocess.run", side_effect=fake_builder):
            result = materialize_adaptation_monsters(
                staging,
                ["Context Beast"],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=builder,
                generation_context={
                    "approved_identities": ["Context Beast"],
                    "encounter_evidence": [{"location": "Salt Quay", "role": "guard", "stakes": "cargo"}],
                    "srd_exemplar_guidance": "Use bounded 5e SRD mechanics; do not classify prose or add identities.",
                },
            )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(captured["approved_identities"], ["Context Beast"])
        self.assertEqual(captured["encounter_evidence"][0]["location"], "Salt Quay")
        self.assertIn("SRD", captured["srd_exemplar_guidance"])

    def test_materialization_reuses_descriptive_source_filename_without_generation(self):
        """Payload-name fallback reuses only the explicitly supplied source module."""
        staging = TEST_ROOT / "staging"
        source_module = TEST_ROOT / "hostis_source"
        descriptive = source_module / "monsters" / (
            "2_darkmantles_hiding_among_the_broken_stones.json"
        )
        descriptive.parent.mkdir(parents=True, exist_ok=True)
        descriptive.write_text(
            json.dumps(
                {
                    "name": "Darkmantle",
                    "size": "Small",
                    "alignment": "unaligned",
                    "armorClass": 11,
                }
            ),
            encoding="utf-8",
        )
        unrelated = TEST_ROOT / "unrelated_module" / "monsters"
        unrelated.mkdir(parents=True, exist_ok=True)
        (unrelated / "darkmantle_in_another_module.json").write_text(
            json.dumps(
                {
                    "name": "Darkmantle",
                    "size": "Small",
                    "alignment": "evil",
                    "armorClass": 99,
                }
            ),
            encoding="utf-8",
        )

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run, patch(
            "utils.toolkit_adaptation_monster_guardrail.find_reusable_monster_path"
        ) as unrelated_lookup:
            result = materialize_adaptation_monsters(
                staging,
                ["Darkmantle"],
                source_module_dir=source_module,
                source_module_name="Hostis_Humanis_Generis",
                compendium_lookup={},
                allow_generation=False,
            )

        run.assert_not_called()
        unrelated_lookup.assert_not_called()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_unresolved"], 0)
        resolution = result["resolution_log"][0]
        self.assertEqual(resolution["source"], "module_scan")
        self.assertEqual(resolution["reason"], "reused_payload_name_match")
        staged = staging / "monsters" / "darkmantle.json"
        self.assertEqual(json.loads(staged.read_text(encoding="utf-8")), json.loads(descriptive.read_text(encoding="utf-8")))

    def test_materialization_rejects_incomplete_descriptive_source_without_generation(self):
        """An incomplete descriptive artifact remains unresolved fail-closed."""
        staging = TEST_ROOT / "staging"
        source_module = TEST_ROOT / "hostis_source"
        descriptive = source_module / "monsters" / "darkmantle_hidden.json"
        descriptive.parent.mkdir(parents=True, exist_ok=True)
        descriptive.write_text(
            json.dumps(
                {
                    "name": "Darkmantle",
                    "size": "Small",
                    "alignment": "unaligned",
                }
            ),
            encoding="utf-8",
        )

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Darkmantle"],
                source_module_dir=source_module,
                compendium_lookup={},
                allow_generation=False,
            )

        run.assert_not_called()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["unresolved_refs"], ["Darkmantle"])
        self.assertEqual(result["monsters_generated"], 0)
        scan_rejection = next(
            attempt
            for attempt in result["resolution_log"][0]["attempts"]
            if attempt.get("source") == "module_scan"
        )
        self.assertEqual(scan_rejection["reason"], "missing_required_fields")
        self.assertIn("armorClass", scan_rejection["missing_required_fields"])

    def test_materialization_reuses_compendium_artifact_into_staging(self):
        staging = TEST_ROOT / "staging"
        compendium = TEST_ROOT / "compendium.json"
        compendium.parent.mkdir(parents=True, exist_ok=True)
        compendium.write_text(
            json.dumps(
                {
                    "monsters": [
                        {
                            "name": "Compendium Beast",
                            "size": "Small",
                            "alignment": "neutral",
                            "armorClass": 11,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = materialize_adaptation_monsters(
            staging,
            ["Compendium Beast"],
            compendium_path=compendium,
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["resolution_log"][0]["source"], "compendium")
        self.assertTrue((staging / "monsters" / "compendium_beast.json").is_file())

    def test_materialization_rejects_schema_incomplete_sources(self):
        staging = TEST_ROOT / "staging"
        source_module = TEST_ROOT / "source_module"
        compendium = TEST_ROOT / "compendium.json"
        incomplete = {"size": "Medium", "alignment": None}
        self._write_monster(staging, "incomplete_beast", incomplete)
        self._write_monster(source_module, "incomplete_beast", incomplete)
        compendium.parent.mkdir(parents=True, exist_ok=True)
        compendium.write_text(
            json.dumps({"monsters": [{"name": "Incomplete Beast", **incomplete}]}),
            encoding="utf-8",
        )

        result = materialize_adaptation_monsters(
            staging,
            ["Incomplete Beast"],
            source_module_dir=source_module,
            compendium_path=compendium,
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["unresolved_refs"], ["Incomplete Beast"])
        diagnostic = result["resolution_log"][0]
        self.assertEqual(diagnostic["reason"], "missing_required_fields")
        self.assertIn("armorClass", diagnostic["missing_required_fields"])
        self.assertFalse(diagnostic["schema_sufficient"])

    def test_materialization_never_writes_source_module(self):
        staging = TEST_ROOT / "staging"
        live_module = TEST_ROOT / "modules" / "Live Module"
        source = self._write_monster(
            live_module,
            "live_beast",
            {"size": "Medium", "alignment": "neutral", "armorClass": 13},
        )
        before = sorted(path.relative_to(live_module).as_posix() for path in live_module.rglob("*"))

        result = materialize_adaptation_monsters(
            staging,
            ["Live Beast"],
            source_module_dir=live_module,
        )

        after = sorted(path.relative_to(live_module).as_posix() for path in live_module.rglob("*"))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(before, after)
        self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["armorClass"], 13)
        self.assertTrue((staging / "monsters" / "live_beast.json").is_file())

    def test_opt_in_generation_writes_and_verifies_staging_only(self):
        staging = TEST_ROOT / "staging"
        live_module = TEST_ROOT / "modules" / "Live Module"
        live_module.mkdir(parents=True, exist_ok=True)
        sentinel = live_module / "sentinel.txt"
        sentinel.write_text("untouched", encoding="utf-8")
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")

        def fake_builder(command, **_kwargs):
            self.assertNotIn("--module", command)
            output_directory = Path(command[command.index("--output-directory") + 1])
            output_path = output_directory / "monsters" / "generated_beast.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {"name": "Generated Beast", "size": "Medium", "alignment": "neutral", "armorClass": 13}
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Generated Beast"],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=builder,
            )

        run.assert_called_once()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_generated"], 1)
        self.assertEqual(result["monsters_unresolved"], 0)
        self.assertEqual(
            result["resolution_log"][0]["source"],
            "generated",
        )
        self.assertTrue((staging / "monsters" / "generated_beast.json").is_file())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
        self.assertFalse((live_module / "monsters").exists())

    def test_compendium_reuse_precedes_custom_only_bounded_generation(self):
        staging = TEST_ROOT / "staging"
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")
        custom_name = "Simon Vey's Hired Scout"

        def fake_builder(command, **_kwargs):
            self.assertEqual(command[2], custom_name)
            self.assertNotEqual(command[2], "Simon Vey")
            output_directory = Path(
                command[command.index("--output-directory") + 1]
            )
            output_path = output_directory / "monsters" / "simon_veys_hired_scout.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "name": custom_name,
                        "size": "Medium",
                        "alignment": "neutral",
                        "armorClass": 13,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Grimlock", custom_name],
                compendium_lookup={
                    "Grimlock": {
                        "name": "Grimlock",
                        "size": "Medium",
                        "alignment": "neutral evil",
                        "armorClass": 11,
                    }
                },
                allow_generation=True,
                monster_builder_path=builder,
            )

        run.assert_called_once()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["monsters_reused"], 1)
        self.assertEqual(result["monsters_generated"], 1)
        self.assertEqual(result["monsters_unresolved"], 0)
        self.assertEqual(
            result["resolution_log"][0]["source"],
            "compendium",
        )
        self.assertEqual(
            result["resolution_log"][1]["source"],
            "generated",
        )
        self.assertTrue(
            (staging / "monsters" / "grimlock.json").is_file()
        )
        custom_artifact = staging / "monsters" / "simon_veys_hired_scout.json"
        self.assertTrue(custom_artifact.is_file())
        custom_payload = json.loads(custom_artifact.read_text(encoding="utf-8"))
        self.assertEqual(custom_payload["name"], custom_name)
        self.assertEqual(custom_payload["armorClass"], 13)

    def test_possessive_materialization_agrees_with_final_closure(self):
        """Generated possessive identities resolve in the no-generation pass."""
        staging = TEST_ROOT / "possessive_closure_staging"
        area_path = staging / "areas" / "A001.json"
        area_path.parent.mkdir(parents=True, exist_ok=True)
        custom_name = "Simon Vey's Hired Scout"
        area_path.write_text(
            json.dumps(
                {
                    "areaId": "A001",
                    "locations": [
                        {
                            "locationId": "A001L01",
                            "name": "Salt Quay",
                            "monsters": [{"name": custom_name}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        builder = TEST_ROOT / "possessive_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")

        def fake_builder(command, **_kwargs):
            output_directory = Path(
                command[command.index("--output-directory") + 1]
            )
            output_path = output_directory / "monsters" / "simon_veys_hired_scout.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "name": custom_name,
                        "size": "Medium",
                        "alignment": "neutral",
                        "armorClass": 13,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run",
            side_effect=fake_builder,
        ):
            materialization = materialize_adaptation_monsters(
                staging,
                [custom_name],
                compendium_lookup={},
                allow_generation=True,
                monster_builder_path=builder,
            )

        self.assertEqual(materialization["status"], "pass")
        self.assertEqual(materialization["monsters_generated"], 1)
        self.assertTrue(
            (staging / "monsters" / "simon_veys_hired_scout.json").is_file()
        )

        closure = ensure_monster_reference_closure(
            "possessive_adaptation",
            str(staging),
            allow_generation=False,
        )
        self.assertEqual(closure["required"], 1)
        self.assertEqual(closure["generated"], 0)
        self.assertEqual(closure["unresolved"], 0)

    def test_generation_disabled_stays_unresolved_without_subprocess(self):
        staging = TEST_ROOT / "staging"
        with patch(
            "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
        ) as run:
            result = materialize_adaptation_monsters(
                staging,
                ["Generation Disabled Beast"],
                compendium_lookup={},
            )

        run.assert_not_called()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["monsters_generated"], 0)
        self.assertEqual(result["unresolved_refs"], ["Generation Disabled Beast"])

    def test_generation_failures_remain_bounded_unresolved_diagnostics(self):
        staging = TEST_ROOT / "staging"
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")

        failure_cases = {
            "timeout": subprocess.TimeoutExpired(["fake"], 1),
            "nonzero": subprocess.CompletedProcess(["fake"], 7, "", "provider output"),
            "missing": subprocess.CompletedProcess(["fake"], 0, "", ""),
        }
        for expected_reason, side_effect in failure_cases.items():
            with self.subTest(expected_reason=expected_reason):
                patcher = patch(
                    "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
                )
                mocked_run = patcher.start()
                if isinstance(side_effect, BaseException):
                    mocked_run.side_effect = side_effect
                else:
                    mocked_run.return_value = side_effect
                try:
                    result = materialize_adaptation_monsters(
                        staging,
                        ["Failed Beast"],
                        compendium_lookup={},
                        allow_generation=True,
                        monster_builder_path=builder,
                    )
                finally:
                    patcher.stop()
                self.assertEqual(result["status"], "degraded")
                self.assertEqual(result["unresolved_refs"], ["Failed Beast"])
                attempt = result["resolution_log"][0]["attempts"][-1]
                expected_generation_reason = {
                    "timeout": "generation_timeout",
                    "nonzero": "generation_nonzero_exit",
                    "missing": "generation_missing_output",
                }[expected_reason]
                self.assertEqual(attempt["reason"], expected_generation_reason)
                self.assertLessEqual(len(json.dumps(result)), 50000)

    def test_failed_generation_preserves_live_module_snapshot(self):
        """Failed canonical attempts never create or alter live module files."""
        live_module = self._make_live_module_like_tree()
        before = self._snapshot_tree(live_module)
        builder = TEST_ROOT / "fake_builder.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        builder.write_text("# provider-free fake builder\n", encoding="utf-8")

        failure_cases = {
            "timeout": subprocess.TimeoutExpired(["fake"], 1),
            "nonzero": subprocess.CompletedProcess(["fake"], 7, "", "failed"),
            "missing": subprocess.CompletedProcess(["fake"], 0, "", ""),
        }
        expected_reasons = {
            "timeout": "generation_timeout",
            "nonzero": "generation_nonzero_exit",
            "missing": "generation_missing_output",
        }

        for case_name, side_effect in failure_cases.items():
            with self.subTest(case_name=case_name):
                staging = TEST_ROOT / "failed_attempts" / case_name
                with patch(
                    "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
                ) as run:
                    if isinstance(side_effect, BaseException):
                        run.side_effect = side_effect
                    else:
                        run.return_value = side_effect
                    result = materialize_adaptation_monsters(
                        staging,
                        ["Failed Beast"],
                        source_module_dir=live_module,
                        compendium_lookup={},
                        allow_generation=True,
                        monster_builder_path=builder,
                    )

                self.assertEqual(result["status"], "degraded")
                self.assertEqual(result["unresolved_refs"], ["Failed Beast"])
                attempt = result["resolution_log"][0]["attempts"][-1]
                self.assertEqual(attempt["reason"], expected_reasons[case_name])
                command = run.call_args.args[0]
                self.assertNotIn("--module", command)
                output_directory = Path(
                    command[command.index("--output-directory") + 1]
                )
                self.assertEqual(output_directory, staging.resolve())
                self.assertEqual(self._snapshot_tree(live_module), before)
                self.assertFalse(
                    (live_module / "monsters" / "failed_beast.json").exists()
                )

    def test_invalid_staging_conditions_preserve_live_module_snapshot(self):
        """Invalid staging roots fail closed without touching the live tree."""
        live_module = self._make_live_module_like_tree()
        before = self._snapshot_tree(live_module)
        invalid_cases = []

        invalid_cases.append(("missing_root", None, "staging_root_missing"))

        file_root = TEST_ROOT / "invalid_staging_file"
        file_root.write_text("not a directory", encoding="utf-8")
        invalid_cases.append(("file_root", file_root, "staging_directory_unavailable"))

        symlink_target = TEST_ROOT / "valid_staging_target"
        symlink_target.mkdir(parents=True, exist_ok=True)
        symlink_root = TEST_ROOT / "invalid_staging_symlink"
        os.symlink(symlink_target, symlink_root)
        invalid_cases.append(("symlink_root", symlink_root, "invalid_staging_root"))

        linked_monsters = TEST_ROOT / "linked_monsters"
        linked_monsters.mkdir(parents=True, exist_ok=True)
        monsters_link_root = TEST_ROOT / "invalid_monsters_link"
        monsters_link_root.mkdir(parents=True, exist_ok=True)
        os.symlink(linked_monsters, monsters_link_root / "monsters")
        invalid_cases.append(
            (
                "monsters_symlink",
                monsters_link_root,
                "staging_directory_unavailable",
            )
        )

        target_link_root = TEST_ROOT / "invalid_target_link"
        target_link_root.mkdir(parents=True, exist_ok=True)
        (target_link_root / "monsters").mkdir(parents=True, exist_ok=True)
        os.symlink(
            live_module / "monsters" / "existing_beast.json",
            target_link_root / "monsters" / "invalid_beast.json",
        )
        invalid_cases.append(
            ("target_symlink", target_link_root, "generation_target_outside_staging")
        )

        for case_name, staging, expected_reason in invalid_cases:
            with self.subTest(case_name=case_name):
                with patch(
                    "utils.toolkit_adaptation_monster_guardrail.subprocess.run"
                ) as run:
                    result = materialize_adaptation_monsters(
                        staging,
                        ["Invalid Beast"],
                        source_module_dir=live_module,
                        compendium_lookup={},
                        allow_generation=True,
                        monster_builder_path=TEST_ROOT / "missing_builder.py",
                    )

                self.assertEqual(result["status"], "degraded")
                self.assertEqual(result["unresolved_refs"], ["Invalid Beast"])
                if case_name == "target_symlink":
                    reason = result["resolution_log"][0]["attempts"][-1]["reason"]
                else:
                    reason = result["diagnostics"][0]["code"]
                self.assertEqual(reason, expected_reason)
                run.assert_not_called()
                self.assertEqual(self._snapshot_tree(live_module), before)
                self.assertFalse(
                    (live_module / "monsters" / "invalid_beast.json").exists()
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
