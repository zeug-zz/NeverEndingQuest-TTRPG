# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the bounded G7 Capture_Arena tooling."""

import ast
import copy
import hashlib
import itertools
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.combat.prompts import (
    InitialCombatStateDependencies,
    InitialCombatStateInputs,
    prepare_initial_combat_state,
)
from core.combat import preroll_determinism
from core.generators.generate_prerolls import generate_prerolls
from scripts import capture_drive
from scripts import capture_evidence
from scripts import combat_latency_fixtures as fixtures
from scripts import seed_combat_capture


def _reachable_initiative_rolls(names, pc_modifiers, enemy_initiatives):
    """Represent every distinct queue order reachable from legal d20 rolls."""
    representatives = {}
    for rolls in itertools.product(range(1, 21), repeat=len(names)):
        actors = [
            (name, "pc", rolls[index] + pc_modifiers[name])
            for index, name in enumerate(names)
        ]
        actors.extend(
            (name, "enemy", initiative)
            for name, initiative in enemy_initiatives.items()
        )
        actors.sort(key=lambda row: row[2], reverse=True)
        signature = tuple((name, kind) for name, kind, _ in actors)
        representatives.setdefault(signature, rolls)
    return representatives


class G7FixtureTests(unittest.TestCase):
    def test_party_specific_boundaries_and_turn_inputs_are_fixed(self):
        self.assertNotIn("after_character_write:2", fixtures.g7_commit_boundaries(1, "normal"))
        self.assertNotIn("after_character_write:2", fixtures.g7_commit_boundaries(4, "enemy_batch"))
        self.assertIn("after_character_write:2", fixtures.g7_commit_boundaries(4, "normal"))

        p1_normal = fixtures.build_gate_profile(
            "g7", "turn-commit", 1, path="normal",
            boundary="before_first_character_write", phase="interrupt",
        )
        p4_batch = fixtures.build_gate_profile(
            "g7", "turn-commit", 4, path="enemy_batch",
            boundary="before_first_character_write", phase="interrupt",
        )
        p4_normal_second_write = fixtures.build_gate_profile(
            "g7", "turn-commit", 4, path="normal",
            boundary="after_character_write:2", phase="interrupt",
        )
        p4_batch_fixture = fixtures.build_g7_turn_commit_fixture(4, "enemy_batch")
        self.assertIn("Bless", p1_normal["seed"]["input"])
        self.assertEqual(p4_batch["seed"]["input"], "/end")
        self.assertEqual(p4_batch_fixture["encounter"]["combat_phase"], "PC_PHASE")
        self.assertEqual(p4_batch_fixture["encounter_id"], "turn_commit_p4_130")
        self.assertEqual(p4_normal_second_write["boundary"], "after_character_write:2")
        self.assertIsNone(p4_batch["seed"]["expected_changed_characters"])
        self.assertFalse(p4_batch["seed"]["tactical_brain"])
        self.assertFalse(p4_batch["seed"]["tactical_prefetch"])
        with self.assertRaisesRegex(ValueError, "unsupported G7 boundary"):
            fixtures.build_gate_profile(
                "g7", "turn-commit", 4, path="enemy_batch",
                boundary="after_character_write:2", phase="interrupt",
            )

    def test_enemy_batch_seed_hits_one_pc_for_every_reachable_runtime_order(self):
        from core.combat.enemy_batch_orchestrator import _batch_id, _turn_order
        from core.combat.enemy_resolution import EnemyResolutionLedger, plan_enemy_batch

        reference = {
            "module": "Capture_Arena",
            "area_id": "CTR001",
            "area_name": "Capture Arena",
            "start_location_id": "CA01",
            "start_location_name": "Waystone Gate",
        }
        goblin_path = (
            seed_combat_capture.PROJECT_ROOT
            / "modules" / "Capture_Arena" / "monsters" / "goblin.json"
        )
        goblin = json.loads(goblin_path.read_text(encoding="utf-8"))
        for party_size in (1, 4):
            boundary = "after_character_write:1"
            profile = fixtures.build_gate_profile(
                "g7", "turn-commit", party_size, phase="interrupt",
                path="enemy_batch", boundary=boundary,
            )
            party_names = (
                [fixtures.ONE_PC_NAME] if party_size == 1 else list(fixtures.PC_NAMES)
            )
            seeded = {}
            encounter_id = seed_combat_capture._seed_party(
                reference,
                party_names,
                party_size,
                profile,
                writer=lambda path, payload: seeded.__setitem__(
                    path, copy.deepcopy(payload)
                ),
            )
            self.assertEqual(encounter_id, profile["seed"]["encounter_id"])
            encounter_path = next(
                path for path in seeded if path.startswith("modules/encounters/")
            )
            encounter = copy.deepcopy(seeded[encounter_path])
            pc_states = {
                name: seeded[seed_combat_capture._capture_character_path(name)]
                for name in party_names
            }
            enemy_count = sum(
                creature.get("type") == "enemy"
                for creature in encounter["creatures"]
            )
            pc_modifiers = (
                {fixtures.ONE_PC_NAME: fixtures.ONE_PC_INITIATIVE}
                if party_size == 1 else fixtures.PC_INITIATIVES
            )
            enemy_initiatives = (
                {"Goblin": fixtures.ONE_PC_ENEMY_INITIATIVE}
                if party_size == 1 else fixtures.ENEMY_INITIATIVES
            )
            expected_orders = _reachable_initiative_rolls(
                party_names, pc_modifiers, enemy_initiatives
            )
            self.assertEqual(
                {row["name"]: row["initiative"] for row in encounter["creatures"]
                 if row.get("type") == "enemy"},
                enemy_initiatives,
            )
            self.assertEqual(
                {name: pc_states[name]["initiative"] for name in party_names},
                pc_modifiers,
            )

            with tempfile.TemporaryDirectory(
                prefix="capture-g7-planner-",
                dir=str(capture_evidence.G7_RUN_ROOT),
            ) as scratch:
                sandbox = Path(scratch)
                for relative_path, payload in seeded.items():
                    destination = sandbox / relative_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(payload), encoding="utf-8")

                previous_cwd = os.getcwd()
                try:
                    os.chdir(sandbox)
                    observed_targets = set()
                    observed_signatures = set()
                    manager = fixtures._make_mp_manager()
                    manager.initialize_from_party(seeded["party_tracker.json"])
                    path_manager = SimpleNamespace(
                        get_character_path=lambda name: "characters/%s.json" %
                        name.lower().replace(" ", "_")
                    )
                    fixture_seed = profile["seed"]["preroll_seed"]
                    with patch.object(
                        preroll_determinism.model_config,
                        "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED",
                        True,
                    ), patch.dict(
                        os.environ,
                        {
                            preroll_determinism.PREROLL_SEED_ENV: str(fixture_seed),
                        },
                    ), patch.object(
                        preroll_determinism.turn_fault_injection,
                        "_resolved_runtime_root",
                        return_value=Path("tmp/combat_capture"),
                    ), patch.object(
                        preroll_determinism.turn_fault_injection,
                        "_is_isolated_capture_root",
                        return_value=True,
                    ):
                        preroll_generator, preroll_random_int = (
                            preroll_determinism.build_preroll_dependencies(
                                generate_prerolls, random.randint
                            )
                        )
                        initialized = prepare_initial_combat_state(
                            InitialCombatStateInputs(
                                encounter_data=encounter,
                                player_info=copy.deepcopy(pc_states[party_names[0]]),
                                path_manager=path_manager,
                                multi_pc_manager=manager,
                                party_tracker_data=seeded["party_tracker.json"],
                                json_file_path=encounter_path,
                            ),
                            InitialCombatStateDependencies(
                                normalize_character_name=lambda name: name.lower().replace(" ", "_"),
                                safe_json_load=lambda path: copy.deepcopy(seeded.get(path)),
                                load_npc_with_fuzzy_match=lambda *_args: (None, None),
                                collect_authoritative_combat_roster=lambda data, **_kwargs: [
                                    {"name": row.get("name"), "type": row.get("type")}
                                    for row in data.get("creatures", [])
                                ],
                                generate_prerolls=preroll_generator,
                                save_json=lambda path, payload: seeded.__setitem__(
                                    path, copy.deepcopy(payload)
                                ),
                                random_int=preroll_random_int,
                                debug=lambda *_args, **_kwargs: None,
                                error=lambda *_args, **_kwargs: None,
                            ),
                        )
                    encounter = initialized.encounter_data
                    self.assertIn("preroll_cache", encounter)
                    self.assertEqual(encounter["preroll_cache"]["round"], 1)
                    for expected_signature, pc_rolls in expected_orders.items():
                        random_results = list(pc_rolls) + [1] * enemy_count
                        with patch(
                            "core.combat.multi_pc.manager._get_tabletop_debug",
                            return_value=None,
                        ), patch(
                            "core.combat.multi_pc.turn_queue.random.randint",
                            side_effect=random_results,
                        ):
                            manager.initialize_turn_queue(encounter)

                        turn_order = _turn_order(manager)
                        observed_order = tuple(
                            (combatant.name, combatant.kind) for combatant in turn_order
                        )
                        self.assertEqual(observed_order, expected_signature)
                        observed_signatures.add(observed_order)
                        enemy_window = manager.get_remaining_enemies_for_round()
                        self.assertEqual(enemy_window, [name for name, kind in observed_order
                                                        if kind == "enemy"])
                        result = plan_enemy_batch(
                            encounter,
                            pc_states,
                            {"Goblin": goblin},
                            turn_order,
                            batch_id=_batch_id(encounter_id, 1),
                            batch_kind="enemy_phase",
                            fixture_seed=None,
                            enemy_turn_window=[{"name": name} for name in enemy_window],
                            active_encounter_id=encounter_id,
                            combat_in_progress=True,
                        )
                        self.assertIsInstance(result, EnemyResolutionLedger, repr(result))
                        changed_characters = {
                            entry.target.name
                            for entry in result.entries
                            if entry.hit and entry.damage_total > 0
                        }
                        self.assertTrue(
                            changed_characters,
                            "party_size=%d order=%r entries=%r" % (
                                party_size,
                                observed_order,
                                [
                                    (entry.actor.name, entry.target.name, entry.d20,
                                     entry.attack_total, entry.armor_class,
                                     entry.hit, entry.damage_total)
                                    for entry in result.entries
                                ],
                            ),
                        )
                        self.assertEqual(len(changed_characters), 1)
                        observed_targets.update(changed_characters)
                    self.assertEqual(observed_signatures, set(expected_orders))
                    if party_size == 1:
                        self.assertEqual(observed_targets, {fixtures.ONE_PC_NAME})
                    else:
                        self.assertGreater(len(observed_targets), 1)
                finally:
                    os.chdir(previous_cwd)

    def test_enemy_batch_fixture_keeps_legal_initiative_and_seed_contract(self):
        p1_normal = fixtures.build_g7_turn_commit_fixture(1, "normal")
        p1_batch = fixtures.build_g7_turn_commit_fixture(1, "enemy_batch")
        p4_normal = fixtures.build_g7_turn_commit_fixture(4, "normal")
        p4_batch = fixtures.build_g7_turn_commit_fixture(4, "enemy_batch")
        self.assertIsNone(p1_normal["preroll_seed"])
        self.assertIsNone(p4_normal["preroll_seed"])
        self.assertEqual(p1_batch["preroll_seed"], fixtures.G7_ENEMY_BATCH_PREROLL_SEED)
        self.assertEqual(p4_batch["preroll_seed"], fixtures.G7_ENEMY_BATCH_PREROLL_SEED)
        self.assertEqual(fixtures.G7_ENEMY_BATCH_PREROLL_SEED, 1)
        self.assertEqual(p1_normal["encounter_id"], "turn_commit_p1_001")
        self.assertEqual(p1_batch["encounter_id"], "turn_commit_p1_002")
        self.assertEqual(p4_normal["encounter_id"], "turn_commit_p4_002")
        self.assertEqual(p4_batch["encounter_id"], "turn_commit_p4_130")
        self.assertEqual(p1_normal["pc_armor_class"], 14)
        self.assertEqual(p1_batch["pc_armor_class"], 8)
        self.assertEqual(p1_batch["character_overrides"]["Acheron"]["abilities"]["dexterity"], 6)
        self.assertEqual(p4_normal["pc_armor_class"], 14)
        self.assertEqual(p4_batch["pc_armor_class"], 6)
        self.assertTrue(all(
            p4_batch["character_overrides"][name]["abilities"]["dexterity"] == 3
            for name in fixtures.PC_NAMES
        ))
        self.assertEqual(
            [row["initiative"] for row in p4_normal["encounter"]["creatures"]
             if row.get("type") == "enemy"],
            [10, 8],
        )
        self.assertEqual(
            {
                row["name"]: row["initiative"]
                for row in p4_normal["encounter"]["creatures"]
                if row.get("type") == "player"
            },
            fixtures.PC_INITIATIVES,
        )
        self.assertNotIn("initiative", p4_normal["character_overrides"]["Acheron"])
        self.assertEqual(
            p4_normal["character_overrides"]["Merisiel"],
            {"hitPoints": 20, "maxHitPoints": 30},
        )
        self.assertEqual(
            {row["name"]: row["initiative"] for row in p4_batch["encounter"]["creatures"]
             if row.get("type") == "player"},
            fixtures.PC_INITIATIVES,
        )
        self.assertEqual(
            [row["initiative"] for row in p4_batch["encounter"]["creatures"]
             if row.get("type") == "enemy"],
            [10, 8],
        )
        self.assertTrue(all("initiative" not in p4_batch["character_overrides"].get(name, {})
                            for name in fixtures.PC_NAMES))

    def test_p4_normal_fixture_uses_a_legal_persisted_multi_target_action(self):
        p1_normal = fixtures.build_g7_turn_commit_fixture(1, "normal")
        p4_normal = fixtures.build_g7_turn_commit_fixture(4, "normal")

        self.assertIn("Bless", p1_normal["normal_input"])
        self.assertEqual(p1_normal["expected_changed_characters"], ["Acheron"])
        self.assertIn("Mass Healing Word", p4_normal["normal_input"])
        self.assertNotIn("Bless", p4_normal["normal_input"])
        self.assertEqual(
            p4_normal["expected_changed_characters"], ["Acheron", "Merisiel", "Kira"]
        )
        self.assertGreaterEqual(len(p4_normal["expected_changed_characters"]), 2)

        caster = p4_normal["character_overrides"]["Acheron"]
        self.assertEqual((caster["class"], caster["level"]), ("Cleric", 5))
        self.assertIn("Mass Healing Word", caster["spellcasting"]["spells"]["level3"])
        self.assertIn("Mass Healing Word", caster["spellcasting"]["preparedSpells"])
        self.assertEqual(caster["spellcasting"]["spellSlots"]["level3"]["current"], 2)
        spell = json.loads(Path("data/spell_repository.json").read_text(encoding="utf-8"))[
            "mass_healing_word"
        ]
        self.assertEqual((spell["level"], spell["range"]), (3, "60 feet"))
        self.assertIn("Cleric", spell["classes"])
        for name in p4_normal["expected_changed_characters"]:
            with self.subTest(character=name):
                override = p4_normal["character_overrides"][name]
                self.assertEqual((override["hitPoints"], override["maxHitPoints"]), (20, 30))

        profile = fixtures.build_gate_profile(
            "g7", "turn-commit", 4, path="normal",
            boundary="before_first_character_write", phase="interrupt",
        )
        seeded = {}
        seed_combat_capture._seed_party(
            {
                "module": "Capture_Arena",
                "area_id": "CTR001",
                "area_name": "Capture Arena",
                "start_location_id": "CA01",
                "start_location_name": "Waystone Gate",
            },
            list(fixtures.PC_NAMES),
            4,
            profile,
            writer=lambda path, payload: seeded.__setitem__(
                path, copy.deepcopy(payload)
            ),
        )
        for name in p4_normal["expected_changed_characters"]:
            with self.subTest(persisted_character=name):
                character = seeded[seed_combat_capture._capture_character_path(name)]
                self.assertEqual((character["hitPoints"], character["maxHitPoints"]), (20, 30))
        self.assertEqual(
            seeded["characters/acheron.json"]["spellcasting"]["spellSlots"]["level3"]["current"],
            2,
        )


class PrerollDeterminismTests(unittest.TestCase):
    @staticmethod
    def _encounter():
        return {
            "current_round": 1,
            "creatures": [
                {"name": "Acheron", "type": "player"},
                {
                    "name": "Goblin",
                    "type": "enemy",
                    "numAttacks": 1,
                    "attacks": [{"name": "Scimitar"}],
                },
            ],
        }

    def test_disabled_seam_preserves_production_dependencies_without_path_lookup(self):
        global_random_state = random.getstate()
        with (
            patch.object(
                preroll_determinism.model_config,
                "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED",
                False,
            ),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_resolved_runtime_root",
            ) as root_lookup,
            patch.dict(os.environ, {preroll_determinism.PREROLL_SEED_ENV: "17"}),
        ):
            generator, random_int = preroll_determinism.build_preroll_dependencies(
                generate_prerolls, random.randint
            )

        self.assertIs(generator, generate_prerolls)
        self.assertIs(random_int, random.randint)
        root_lookup.assert_not_called()
        self.assertEqual(random.getstate(), global_random_state)

    def test_missing_seed_does_not_resolve_or_install_a_local_rng(self):
        with (
            patch.object(
                preroll_determinism.model_config,
                "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED",
                True,
            ),
            patch.dict(os.environ, {}, clear=False),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_resolved_runtime_root",
            ) as root_lookup,
        ):
            os.environ.pop(preroll_determinism.PREROLL_SEED_ENV, None)
            generator, random_int = preroll_determinism.build_preroll_dependencies(
                generate_prerolls, random.randint
            )

        self.assertIs(generator, generate_prerolls)
        self.assertIs(random_int, random.randint)
        root_lookup.assert_not_called()

    def test_valid_capture_seed_repeats_prerolls_without_mutating_global_random(self):
        global_random_state = random.getstate()
        with (
            patch.object(
                preroll_determinism.model_config,
                "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED",
                True,
            ),
            patch.dict(os.environ, {preroll_determinism.PREROLL_SEED_ENV: "17"}),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_resolved_runtime_root",
                return_value=Path("tmp/combat_capture"),
            ),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_is_isolated_capture_root",
                return_value=True,
            ) as isolated_root,
        ):
            first_generator, first_random_int = preroll_determinism.build_preroll_dependencies(
                generate_prerolls, random.randint
            )
            first = (
                first_generator(self._encounter(), round_num=1),
                first_random_int(1000, 9999),
            )
            second_generator, second_random_int = preroll_determinism.build_preroll_dependencies(
                generate_prerolls, random.randint
            )
            second = (
                second_generator(self._encounter(), round_num=1),
                second_random_int(1000, 9999),
            )

        self.assertEqual(first, second)
        self.assertEqual(isolated_root.call_count, 2)
        self.assertEqual(random.getstate(), global_random_state)

    def test_invalid_seed_or_unisolated_root_falls_back_to_production_dependencies(self):
        with (
            patch.object(
                preroll_determinism.model_config,
                "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED",
                True,
            ),
            patch.object(preroll_determinism, "_log_rejection"),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_resolved_runtime_root",
                return_value=Path("/repo"),
            ),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_is_isolated_capture_root",
                return_value=True,
            ),
        ):
            for invalid_seed in ("", "-1", "+17", "1.5", "x" * 21, str(1 << 64)):
                with self.subTest(seed=invalid_seed), patch.dict(
                    os.environ, {preroll_determinism.PREROLL_SEED_ENV: invalid_seed}
                ):
                    generator, random_int = preroll_determinism.build_preroll_dependencies(
                        generate_prerolls, random.randint
                    )
                    self.assertIs(generator, generate_prerolls)
                    self.assertIs(random_int, random.randint)

        with (
            patch.object(
                preroll_determinism.model_config,
                "COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED",
                True,
            ),
            patch.dict(os.environ, {preroll_determinism.PREROLL_SEED_ENV: "17"}),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_resolved_runtime_root",
                return_value=Path("/repo"),
            ),
            patch.object(
                preroll_determinism.turn_fault_injection,
                "_is_isolated_capture_root",
                return_value=False,
            ),
            patch.object(preroll_determinism, "_log_rejection"),
        ):
            generator, random_int = preroll_determinism.build_preroll_dependencies(
                generate_prerolls, random.randint
            )
        self.assertIs(generator, generate_prerolls)
        self.assertIs(random_int, random.randint)

    def test_combat_manager_wires_seeded_preroll_dependencies_to_both_paths(self):
        source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        owner = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_run_combat_simulation_internal"
        )
        initial_state_call = next(
            node for node in ast.walk(owner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "prepare_initial_combat_state"
        )
        initial_dependencies = next(
            argument for argument in initial_state_call.args
            if isinstance(argument, ast.Call)
            and isinstance(argument.func, ast.Name)
            and argument.func.id == "InitialCombatStateDependencies"
        )
        initial_keywords = {keyword.arg: keyword.value for keyword in initial_dependencies.keywords}
        self.assertEqual(
            ast.dump(initial_keywords["generate_prerolls"]),
            ast.dump(ast.Name(id="preroll_generator", ctx=ast.Load())),
        )
        self.assertEqual(
            ast.dump(initial_keywords["random_int"]),
            ast.dump(ast.Name(id="preroll_random_int", ctx=ast.Load())),
        )

        normal_dependencies_call = next(
            node for node in ast.walk(owner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_build_normal_turn_dependencies"
        )
        self.assertEqual(
            [ast.dump(argument) for argument in normal_dependencies_call.args[-2:]],
            [
                ast.dump(ast.Name(id="preroll_generator", ctx=ast.Load())),
                ast.dump(ast.Name(id="preroll_random_int", ctx=ast.Load())),
            ],
        )

    def test_complete_and_replay_require_none_boundary_and_bound_steps(self):
        complete = fixtures.build_gate_profile(
            "g7", "turn-commit", 1, path="normal", boundary="none", phase="complete"
        )
        replay = fixtures.build_gate_profile(
            "g7", "turn-commit", 1, path="normal", boundary="none", phase="replay"
        )
        self.assertEqual(complete["max_steps"], 1)
        self.assertEqual(replay["max_steps"], 0)
        with self.assertRaises(ValueError):
            fixtures.build_gate_profile(
                "g7", "turn-commit", 1, path="normal",
                boundary="after_character_write:2", phase="interrupt",
            )
        with self.assertRaises(ValueError):
            fixtures.build_gate_profile(
                "g7", "turn-commit", 1, path="normal",
                boundary="before_first_character_write", phase="replay",
            )

    def test_enemy_batch_manifest_target_is_one_rostered_pc(self):
        manifest = {"character_effects": [{"character_name": "Merisiel"}]}
        self.assertEqual(capture_evidence._g7_enemy_batch_manifest_target(
            manifest, list(fixtures.PC_NAMES)
        ), "Merisiel")
        self.assertIsNone(capture_evidence._g7_enemy_batch_manifest_target(
            {"character_effects": [
                {"character_name": "Merisiel"}, {"character_name": "Kira"},
            ]}, list(fixtures.PC_NAMES)
        ))
        self.assertIsNone(capture_evidence._g7_enemy_batch_manifest_target(
            {"character_effects": [{"character_name": "Unrostered PC"}]},
            list(fixtures.PC_NAMES),
        ))

    def test_g7_model_config_patch_sets_only_sandbox_literals(self):
        with tempfile.TemporaryDirectory(
                prefix="capture-g7-model-config-", dir=str(capture_evidence.G7_RUN_ROOT)) as scratch:
            sandbox = Path(scratch)
            config_path = sandbox / "model_config.py"
            config_path.write_bytes((capture_evidence.PROJECT_ROOT / "model_config.py").read_bytes())
            with patch.object(seed_combat_capture, "SANDBOX_ROOT", sandbox):
                seed_combat_capture._patch_sandbox_model_config("g7")
            identity = capture_evidence.read_sandbox_g7_identity(sandbox)
            self.assertEqual(identity["status"], "ok")
            self.assertEqual(identity["flags"], identity["expected"])


class G7DriverTests(unittest.TestCase):
    @staticmethod
    def _session(party_size=1):
        args = SimpleNamespace(
            url="http://localhost:8360", party=party_size,
            transcript="tmp/g7-provider-free-test.log", gate="g7",
        )
        return capture_drive.CaptureSession(args)

    def test_g7_phases_choose_input_or_retained_observation(self):
        session = self._session()
        with patch.object(session, "set_active_character", return_value=True) as set_active, \
                patch.object(session, "_send_g7_interrupt_input", return_value=True) as interrupt, \
                patch.object(session, "send_turn") as send_turn:
            interrupt_profile = fixtures.build_gate_profile(
                "g7", "turn-commit", 1, path="normal",
                boundary="before_first_character_write", phase="interrupt",
            )
            session.run_g7_scenario(interrupt_profile)
            interrupt.assert_called_once()
            set_active.assert_called_once_with("Acheron")
            send_turn.assert_not_called()

        session = self._session()
        with patch.object(session, "set_active_character", return_value=True) as set_active, \
                patch.object(session, "send_turn") as send_turn:
            profile = fixtures.build_gate_profile(
                "g7", "turn-commit", 1, path="normal", boundary="none", phase="complete"
            )
            session.run_g7_scenario(profile)
            send_turn.assert_called_once_with("G7 completed turn", profile["seed"]["input"], "Acheron")
            set_active.assert_called_once_with("Acheron")

        session = self._session()
        with patch.object(session, "set_active_character") as set_active, \
                patch.object(session, "send_turn") as send_turn:
            profile = fixtures.build_gate_profile(
                "g7", "turn-commit", 1, path="normal", boundary="none", phase="replay"
            )
            session.run_g7_scenario(profile)
            set_active.assert_not_called()
            send_turn.assert_not_called()

    def test_g7_cli_accepts_interrupt_profile_without_starting_transport(self):
        args = capture_drive.build_parser().parse_args([
            "--gate", "g7", "--party", "4", "--scenario", "turn-commit",
            "--path", "normal", "--boundary", "after_character_write:2",
            "--phase", "interrupt",
        ])
        self.assertEqual((args.gate, args.party, args.path, args.boundary, args.phase),
                         ("g7", 4, "normal", "after_character_write:2", "interrupt"))

    def test_g7_enemy_batch_uses_dm_end_without_a_pc_identity(self):
        session = self._session(party_size=4)
        with patch.object(session, "set_active_character") as set_active, \
                patch.object(session, "_send_g7_interrupt_input", return_value=True) as interrupt, \
                patch.object(session, "send_turn") as send_turn:
            interrupt_profile = fixtures.build_gate_profile(
                "g7", "turn-commit", 4, path="enemy_batch",
                boundary="after_character_write:1", phase="interrupt",
            )
            session.run_g7_scenario(interrupt_profile)
            set_active.assert_not_called()
            interrupt.assert_called_once_with("/end", None, "after_character_write:1")
            send_turn.assert_not_called()

        session = self._session(party_size=1)
        with patch.object(session, "set_active_character") as set_active, \
                patch.object(session, "send_turn") as send_turn:
            complete_profile = fixtures.build_gate_profile(
                "g7", "turn-commit", 1, path="enemy_batch", boundary="none",
                phase="complete",
            )
            session.run_g7_scenario(complete_profile)
            set_active.assert_not_called()
            send_turn.assert_called_once_with("G7 completed turn", "/end", None)

    def test_g7_interrupt_marker_wait_uses_bounded_180_second_timeout(self):
        profile = fixtures.build_gate_profile(
            "g7", "turn-commit", 1, path="normal",
            boundary="before_first_character_write", phase="interrupt",
        )
        self.assertEqual(
            profile["lifecycle_stop_timeout_seconds"],
            fixtures.G7_LIFECYCLE_STOP_TIMEOUT_SECONDS,
        )
        self.assertEqual(profile["lifecycle_stop_timeout_seconds"], 180)

        session = self._session()
        session.capture_profile = profile
        session.args.server_log = "tmp/router-rollout/g7/lifecycle-stop/server.log"
        session.args.state_root = "tmp/router-rollout/g7/lifecycle-stop/state"
        session.args.run_dir = "tmp/router-rollout/g7/lifecycle-stop/run"
        session.args.trace_src = "tmp/router-rollout/g7/lifecycle-stop/trace.jsonl"
        session.args.selected_encounter_id = "turn_commit_p1_001"
        now = [100.0]
        sleep_durations = []

        def advance_clock(duration):
            sleep_durations.append(duration)
            now[0] += duration

        with (
            patch.object(session, "emit"),
            patch.object(session, "output_count", return_value=0),
            patch.object(capture_evidence, "trace_byte_offset", return_value=0),
            patch.object(capture_evidence, "write_step_snapshot"),
            patch.object(capture_evidence, "_safe_read_bytes", return_value=(b"", None)),
            patch.object(capture_drive.time, "monotonic", side_effect=lambda: now[0]),
            patch.object(capture_drive.time, "sleep", side_effect=advance_clock),
        ):
            with self.assertRaisesRegex(
                capture_drive.DriverConnectionError,
                "within 180.0s",
            ):
                session._send_g7_interrupt_input(
                    profile["seed"]["input"], "Acheron", profile["boundary"]
                )

        self.assertEqual(session.g7_expected_stop["status"], "missing")
        self.assertTrue(session.g7_expected_stop["wait_timed_out"])
        self.assertEqual(session.g7_expected_stop["wait_timeout_seconds"], 180)
        self.assertAlmostEqual(sum(sleep_durations), 180.0, places=6)

class G7EvidenceTests(unittest.TestCase):
    def test_recovery_expects_all_manifest_markers_after_partial_interrupt(self):
        effects = [
            {"character_name": "Acheron"},
            {"character_name": "Kira"},
        ]
        self.assertEqual(
            capture_evidence._g7_expected_marker_names(
                "interrupt", "before_first_character_write", effects, False
            ),
            [],
        )
        self.assertEqual(
            capture_evidence._g7_expected_marker_names(
                "interrupt", "after_character_write:1", effects, False
            ),
            ["acheron"],
        )
        for boundary in (
            "before_first_character_write",
            "after_character_write:1",
        ):
            with self.subTest(phase="recover", boundary=boundary):
                self.assertEqual(
                    capture_evidence._g7_expected_marker_names(
                        "recover", boundary, effects, False
                    ),
                    ["acheron", "kira"],
                )

    def test_recovery_provider_policy_follows_receipt_durability_boundaries(self):
        applied_id = "sha256:" + "a" * 64
        pending = {"records": {"selected_encounter": {"turn_receipts": []}}}
        committed = {"records": {"selected_encounter": {
            "turn_receipts": [{"applied_id": applied_id}],
        }}}
        pre_receipt_boundaries = (
            "before_first_character_write",
            "after_character_write:1",
            "after_character_write:2",
        )
        for boundary in pre_receipt_boundaries:
            with self.subTest(boundary=boundary):
                self.assertTrue(capture_evidence._g7_recovery_requires_zero_providers(
                    "recover", boundary, pending, applied_id
                ))

        self.assertTrue(capture_evidence._g7_recovery_requires_zero_providers(
            "recover", "after_encounter_write", pending, applied_id
        ))
        self.assertFalse(capture_evidence._g7_recovery_requires_zero_providers(
            "recover", "after_encounter_write", committed, applied_id
        ))
        for boundary in (
                "after_phase_sync", "during_success_publication",
                "after_success_publication", "none"):
            with self.subTest(boundary=boundary):
                self.assertFalse(capture_evidence._g7_recovery_requires_zero_providers(
                    "recover", boundary, committed, applied_id
                ))
        self.assertFalse(capture_evidence._g7_recovery_requires_zero_providers(
            "replay", "none", pending, applied_id
        ))

    def test_post_commit_resume_provider_is_allowed_but_turn_regeneration_fails(self):
        applied_id = "sha256:" + "b" * 64
        before = {"records": {"selected_encounter": {
            "turn_receipts": [{"applied_id": applied_id}],
        }}}
        commit_manifest = {
            "turn_id": "00000000-0000-4000-8000-000000000001",
            "path": "normal",
            "receipt": {"combat_round": 2},
        }
        expected_profile = {"fixture": {"party_names": ["Acheron"]}}
        reengage = {"event_type": "provider", "site": "combat_reengage"}
        for phase, boundary in (("recover", "after_phase_sync"), ("replay", "none")):
            with self.subTest(phase=phase, boundary=boundary):
                self.assertEqual(capture_evidence._g7_recovery_provider_failures(
                    phase=phase,
                    boundary=boundary,
                    before=before,
                    applied_id=applied_id,
                    commit_manifest=commit_manifest,
                    expected_profile=expected_profile,
                    provider_rows=[reengage],
                    provider_count=1,
                ), [])

        recovered_turn_call = {
            "event_type": "provider",
            "site": "combat_main",
            "action_id": "pc:r2:acheron",
        }
        self.assertEqual(capture_evidence._g7_recovery_provider_failures(
            phase="recover",
            boundary="after_phase_sync",
            before=before,
            applied_id=applied_id,
            commit_manifest=commit_manifest,
            expected_profile=expected_profile,
            provider_rows=[recovered_turn_call],
            provider_count=1,
        ), ["g7_recovery_trace_contains_recovered_turn_provider_event"])

        pending = {"records": {"selected_encounter": {"turn_receipts": []}}}
        failures = capture_evidence._g7_recovery_provider_failures(
            phase="recover",
            boundary="after_character_write:1",
            before=pending,
            applied_id=applied_id,
            commit_manifest=commit_manifest,
            expected_profile=expected_profile,
            provider_rows=[reengage],
            provider_count=1,
        )
        self.assertEqual(failures, [
            "g7_recovery_provider_count_not_zero",
            "g7_recovery_trace_contains_provider_events",
        ])

        enemy_manifest = dict(commit_manifest, path="enemy_batch")
        enemy_turn_call = {
            "event_type": "provider",
            "site": "combat_main",
            "batch_id": "enemy:r2",
        }
        self.assertEqual(capture_evidence._g7_recovery_provider_failures(
            phase="replay",
            boundary="none",
            before=before,
            applied_id=applied_id,
            commit_manifest=enemy_manifest,
            expected_profile=expected_profile,
            provider_rows=[enemy_turn_call],
            provider_count=1,
        ), ["g7_recovery_trace_contains_recovered_turn_provider_event"])

    def test_required_matrix_is_closed_and_reports_exact_missing_keys(self):
        required = capture_evidence.required_g7_matrix_keys()
        self.assertEqual(len(required), 58)
        self.assertNotIn("turn-commit:normal:after_character_write:2:interrupt:p1", required)
        self.assertIn("turn-commit:normal:after_character_write:2:interrupt:p4", required)
        self.assertNotIn("turn-commit:enemy_batch:after_character_write:2:interrupt:p4", required)
        self.assertNotIn("turn-commit:enemy_batch:after_character_write:2:recover:p4", required)
        result = capture_evidence.evaluate_g7_matrix([])
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertEqual(result["primary_verdict"], "PENDING")
        self.assertEqual(result["missing_required_keys"], sorted(required))

    def test_enemy_batch_recovery_uses_interrupt_manifest_target_and_rejects_extra_changes(self):
        encounter_id = "turn_commit_p4_130"
        applied_id = "sha256:" + "a" * 64
        manifest = {
            "turn_id": "00000000-0000-4000-8000-000000000001",
            "applied_id": applied_id,
            "encounter_id": encounter_id,
            "path": "enemy_batch",
            "character_effects": [{"character_name": "Merisiel"}],
        }

        def snapshot(merisiel_hp=30, merisiel_marker=None, extra_kira_damage=False,
                     receipts=None):
            records = {
                "selected_encounter": {"turn_receipts": list(receipts or [])},
                "characters/acheron.json": {"name": "Acheron", "hitPoints": 30},
                "characters/merisiel.json": {
                    "name": "Merisiel", "hitPoints": merisiel_hp,
                    "last_combat_applied_id": merisiel_marker,
                },
                "characters/kira.json": {
                    "name": "Kira", "hitPoints": 25 if extra_kira_damage else 30,
                },
                "characters/vitreol.json": {"name": "Vitreol", "hitPoints": 30},
            }
            return {"records": records, "mechanical_projection": {"same": True}}

        initial = snapshot()
        interrupt_after = snapshot(merisiel_hp=25, merisiel_marker=applied_id)
        recovered = snapshot(
            merisiel_hp=25, merisiel_marker=applied_id,
            receipts=[{"applied_id": applied_id}],
        )
        interrupt_key = "turn-commit:enemy_batch:after_character_write:1:interrupt:p4"
        recover_key = "turn-commit:enemy_batch:after_character_write:1:recover:p4"
        interrupt_dir = capture_evidence.G7_RUN_ROOT / "provider-free-interrupt"
        recover_dir = capture_evidence.G7_RUN_ROOT / "provider-free-recover"

        def make_rows(recovery_snapshot, recovery_manifest=None):
            return {
                interrupt_dir.name: {
                    "matrix_key": interrupt_key,
                    "evaluation": {
                        "problems": [], "failures": [],
                        "selected_manifest": manifest,
                        "before_snapshot": initial,
                        "after_snapshot": interrupt_after,
                    },
                },
                recover_dir.name: {
                    "matrix_key": recover_key,
                    "evaluation": {
                        "problems": [], "failures": [],
                        "selected_manifest": recovery_manifest or manifest,
                        "before_snapshot": interrupt_after,
                        "after_snapshot": recovery_snapshot,
                    },
                },
            }

        good_rows = make_rows(recovered)
        with patch.object(
            capture_evidence, "_evaluate_g7_run",
            side_effect=lambda path: good_rows[path.name],
        ):
            good = capture_evidence.evaluate_g7_matrix([interrupt_dir, recover_dir])
        self.assertEqual(good["pair_failures"], [])

        extra_change_rows = make_rows(snapshot(
            merisiel_hp=25, merisiel_marker=applied_id, extra_kira_damage=True,
            receipts=[{"applied_id": applied_id}],
        ))
        with patch.object(
            capture_evidence, "_evaluate_g7_run",
            side_effect=lambda path: extra_change_rows[path.name],
        ):
            extra_change = capture_evidence.evaluate_g7_matrix([interrupt_dir, recover_dir])
        self.assertIn(
            "%s|%s:enemy_batch_character_changes_not_single_manifest_target" %
            (interrupt_key, recover_key),
            extra_change["pair_failures"],
        )

        wrong_target_manifest = dict(manifest, character_effects=[{"character_name": "Kira"}])
        wrong_target_rows = make_rows(recovered, wrong_target_manifest)
        with patch.object(
            capture_evidence, "_evaluate_g7_run",
            side_effect=lambda path: wrong_target_rows[path.name],
        ):
            wrong_target = capture_evidence.evaluate_g7_matrix([interrupt_dir, recover_dir])
        self.assertIn(
            "%s|%s:enemy_batch_expected_pc_not_preserved" %
            (interrupt_key, recover_key),
            wrong_target["pair_failures"],
        )

    def test_synthetic_bundle_is_never_ready_or_a_primary_verdict(self):
        profile = fixtures.build_gate_profile(
            "g7", "turn-commit", 1, path="normal",
            boundary="before_first_character_write", phase="interrupt",
        )
        contract = {key: profile.get(key) for key in
                    ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
        contract.update({"gate": "g7", "path": "normal",
                        "boundary": "before_first_character_write"})
        manifest = {
            "gate": "g7", "evidence_kind": "synthetic", "live_eligible": False,
            "scenario": {"id": "turn-commit", "phase": "interrupt",
                          "profile_contract": contract,
                          "sha256": hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()},
            "party": {"size": 1}, "transport": {"client_source": "constructor_injected"},
            "sandbox_runtime": {"port": 8360, "trace_gate": {"status": "ok", "enabled": True}},
            "configuration": {"g7_runtime": {"status": "ok"}},
            "counts": {"steps_sent": 1, "step_attempts": 1},
            "g7": {"expected_stop": {"declared": True}},
        }
        row = capture_evidence.evaluate_g7_bundle(manifest, {}, capture_evidence.G7_RUN_ROOT)
        self.assertNotEqual(row["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(row["primary_verdict"], "PENDING")
        self.assertIn("synthetic_or_ineligible_evidence", row["problems"])

    def test_synthetic_full_key_set_cannot_reach_review_ready(self):
        required = capture_evidence.required_g7_matrix_keys()
        run_dirs = [capture_evidence.G7_RUN_ROOT / ("synthetic-row-%02d" % index)
                    for index in range(len(required))]
        fake_rows = iter(required)

        def synthetic_run(path):
            return {
                "run_dir": str(path), "matrix_key": next(fake_rows),
                "manifest": {"evidence_kind": "synthetic", "live_eligible": False},
                "evaluation": {"automated_status": "BLOCKED", "failures": [],
                               "problems": ["synthetic_or_ineligible_evidence"],
                               "selected_manifest": None},
            }

        with patch.object(capture_evidence, "_evaluate_g7_run", side_effect=synthetic_run):
            result = capture_evidence.evaluate_g7_matrix(run_dirs)
        self.assertNotEqual(result["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertEqual(result["primary_verdict"], "PENDING")
        self.assertEqual(result["synthetic_keys"], sorted(required))

    def test_direct_cli_reports_exact_missing_matrix_without_a_primary_verdict(self):
        capture_evidence.G7_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
                prefix="g7-missing-row-", dir=str(capture_evidence.G7_RUN_ROOT)) as scratch:
            completed = subprocess.run(
                [sys.executable, str(capture_evidence.PROJECT_ROOT / "scripts" / "capture_evidence.py"),
                 "--gate", "g7", "--run-dir", scratch],
                cwd=str(capture_evidence.PROJECT_ROOT), check=False,
                capture_output=True, text=True,
            )
        report = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["automated_status"], "BLOCKED")
        self.assertEqual(report["primary_verdict"], "PENDING")
        self.assertEqual(report["missing_required_keys"],
                         sorted(capture_evidence.required_g7_matrix_keys()))
        self.assertEqual(len(report["invalid_run_bundles"]), 1)


if __name__ == "__main__":
    unittest.main()
