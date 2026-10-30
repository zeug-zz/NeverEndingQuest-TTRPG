# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free planning tests for deterministic enemy attack batches."""

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from scripts import combat_latency_fixtures as latency_fixtures
from core.combat.enemy_resolution import (
    DECLINE_REASON_CODES,
    CombatantIdentity,
    EnemyResolutionDecline,
    EnemyResolutionLedger,
    derive_enemy_batch_seed,
    plan_enemy_batch,
)


ROOT = Path(__file__).resolve().parents[1]


def _load_goblin():
    return json.loads(
        (ROOT / "modules/Capture_Arena/monsters/goblin.json").read_text(
            encoding="utf-8"
        )
    )


class _FakeRandom:
    def __init__(self, values):
        self.values = list(values)

    def randint(self, low, high):
        if not self.values:
            raise AssertionError("fake RNG exhausted")
        value = self.values.pop(0)
        if not low <= value <= high:
            raise AssertionError("fake RNG value outside requested range")
        return value


class CombatEnemyResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.goblin = _load_goblin()

    def _scenario(self, party_size=1):
        if party_size == 1:
            encounter = copy.deepcopy(latency_fixtures._one_pc_encounter_payload())
            party_names = [latency_fixtures.ONE_PC_NAME]
            initiatives = latency_fixtures.PC_INITIATIVES
            enemy_window = [
                {"name": latency_fixtures.ONE_PC_ENEMY_NAME, "kind": "enemy"}
            ]
        else:
            encounter = copy.deepcopy(latency_fixtures._encounter_payload())
            party_names = list(latency_fixtures.PC_NAMES)
            initiatives = latency_fixtures.PC_INITIATIVES
            enemy_window = [
                {"name": name, "kind": "enemy"}
                for name in latency_fixtures.ENEMY_NAMES
            ]

        pc_states = {}
        for name in party_names:
            initiative = (
                latency_fixtures.ONE_PC_INITIATIVE
                if party_size == 1
                else initiatives[name]
            )
            state = latency_fixtures._character_payload(name, initiative)
            pc_states[name] = state
            encounter["creatures"].append({
                "name": name,
                "type": "player",
                "initiative": initiative,
                "status": "alive",
                "conditions": [],
                "actions": {"actionType": "", "target": ""},
                "currentHitPoints": state["hitPoints"],
                "maxHitPoints": state["maxHitPoints"],
                "armorClass": state["armorClass"],
            })

        turn_order = [
            {"name": creature["name"], "kind": creature["type"]}
            for creature in sorted(
                encounter["creatures"],
                key=lambda item: item["initiative"],
                reverse=True,
            )
        ]
        return {
            "encounter": encounter,
            "pc_states": pc_states,
            "monster_definitions": {"Goblin": copy.deepcopy(self.goblin)},
            "turn_order": turn_order,
            "batch_id": "enemy-batch-1",
            "batch_kind": "enemy_phase",
            "fixture_seed": "capture-seed-1",
            "enemy_turn_window": enemy_window,
        }

    @staticmethod
    def _plan(args):
        return plan_enemy_batch(**args)

    @staticmethod
    def _enemy(encounter, name=None):
        for creature in encounter["creatures"]:
            if creature.get("type") == "enemy" and (
                name is None or creature.get("name") == name
            ):
                return creature
        raise AssertionError("enemy not found")

    def _with_fake_rng(self, args, rolls):
        fake = _FakeRandom(rolls)
        with mock.patch("core.combat.enemy_resolution.random.Random", return_value=fake):
            return self._plan(args)

    def test_identical_state_and_seed_produce_identical_immutable_ledger(self):
        args = self._scenario()
        first = self._plan(copy.deepcopy(args))
        second = self._plan(copy.deepcopy(args))
        self.assertIsInstance(first, EnemyResolutionLedger)
        self.assertEqual(first, second)
        self.assertTrue(first.entries)
        self.assertIsInstance(first.entries, tuple)
        self.assertIsInstance(first.entries[0].damage_dice_rolls, tuple)
        with self.assertRaises((AttributeError, TypeError)):
            first.entries[0].damage_total = 999

    def test_batch_identity_participates_in_seed_derivation(self):
        args = self._scenario()
        first = self._plan(args)
        args["batch_id"] = "enemy-batch-2"
        second = self._plan(args)
        self.assertIsInstance(first, EnemyResolutionLedger)
        self.assertIsInstance(second, EnemyResolutionLedger)
        self.assertNotEqual(first.seed, second.seed)
        self.assertEqual(
            derive_enemy_batch_seed(
                {"z": 1, "a": 2}, encounter_id="e", round_number=1,
                batch_id="b", batch_kind="end", fixture_seed=4,
            ),
            derive_enemy_batch_seed(
                {"a": 2, "z": 1}, encounter_id="e", round_number=1,
                batch_id="b", batch_kind="end", fixture_seed=4,
            ),
        )

    def test_planning_performs_no_file_writes_and_does_not_mutate_inputs(self):
        args = self._scenario(party_size=4)
        before = copy.deepcopy(args)
        with mock.patch("builtins.open", side_effect=AssertionError("file open")), \
                mock.patch("os.replace", side_effect=AssertionError("file replace")):
            result = self._plan(args)
        self.assertIsInstance(result, EnemyResolutionLedger)
        self.assertEqual(args, before)

    def test_kind_qualified_identity_keeps_same_name_combatants_distinct(self):
        args = self._scenario()
        enemy = self._enemy(args["encounter"])
        enemy["name"] = "Acheron"
        args["enemy_turn_window"] = [{"name": "Acheron", "kind": "enemy"}]
        args["turn_order"] = [
            {"name": "Acheron", "kind": "player"},
            {"name": "Acheron", "kind": "enemy"},
        ]
        result = self._plan(args)
        self.assertIsInstance(result, EnemyResolutionLedger)
        self.assertEqual(result.entries[0].actor, CombatantIdentity("Acheron", "enemy"))
        self.assertEqual(result.entries[0].target, CombatantIdentity("Acheron", "player"))
        self.assertNotEqual(result.entries[0].actor, result.entries[0].target)

    def test_nat1_nat20_critical_and_exact_ac_boundary(self):
        # A natural 1 misses even with an attack total above AC.
        args = self._scenario()
        args["monster_definitions"]["Goblin"]["actions"][0]["attackBonus"] = 100
        nat_one = self._with_fake_rng(args, [1])
        self.assertIsInstance(nat_one, EnemyResolutionLedger)
        self.assertFalse(nat_one.entries[0].hit)
        self.assertFalse(nat_one.entries[0].critical)
        self.assertEqual(nat_one.entries[0].damage_dice_rolls, ())

        # Natural 20 doubles dice, but adds the flat bonus only once.
        args = self._scenario()
        critical = self._with_fake_rng(args, [20, 2, 3])
        self.assertIsInstance(critical, EnemyResolutionLedger)
        entry = critical.entries[0]
        self.assertTrue(entry.hit)
        self.assertTrue(entry.critical)
        self.assertEqual(entry.damage_dice_rolls, (2, 3))
        self.assertEqual(entry.damage_total, 7)  # 2 + 3 + one flat +2

        # 10 + 4 equals Acheron's AC 14, so the ordinary attack hits.
        boundary = self._with_fake_rng(self._scenario(), [10, 4])
        self.assertIsInstance(boundary, EnemyResolutionLedger)
        self.assertEqual(boundary.entries[0].attack_total, boundary.entries[0].armor_class)
        self.assertTrue(boundary.entries[0].hit)
        below = self._with_fake_rng(self._scenario(), [9])
        self.assertIsInstance(below, EnemyResolutionLedger)
        self.assertFalse(below.entries[0].hit)

    def test_multiattack_executes_explicit_declaration_in_order(self):
        args = self._scenario()
        args["monster_definitions"]["Goblin"]["multiattack"] = [
            {"action": "Shortbow", "count": 1},
            {"action": "Scimitar", "count": 2},
        ]
        result = self._with_fake_rng(args, [10, 1, 10, 2, 10, 3])
        self.assertIsInstance(result, EnemyResolutionLedger)
        self.assertEqual(
            [entry.action_name for entry in result.entries],
            ["Shortbow", "Scimitar", "Scimitar"],
        )
        self.assertEqual(len(result.entries), 3)

    def test_target_rotation_continues_after_previous_target_and_wraps(self):
        args = self._scenario(party_size=4)
        args["monster_definitions"]["Goblin"]["multiattack"] = [
            {"action": "Scimitar", "count": 3},
        ]
        args["enemy_turn_window"] = [{"name": "Goblin Alpha", "kind": "enemy"}]
        result = self._with_fake_rng(args, [10, 1] * 3)
        self.assertIsInstance(result, EnemyResolutionLedger)
        self.assertEqual(
            [entry.target.name for entry in result.entries],
            ["Acheron", "Merisiel", "Kira"],
        )

    def test_target_rotation_skips_only_dead_or_defeated_pcs(self):
        args = self._scenario(party_size=4)
        args["pc_states"]["Acheron"]["hitPoints"] = 0
        args["pc_states"]["Acheron"]["status"] = "dead"
        args["enemy_turn_window"] = [{"name": "Goblin Alpha", "kind": "enemy"}]
        result = self._with_fake_rng(args, [10, 1])
        self.assertIsInstance(result, EnemyResolutionLedger)
        self.assertEqual(result.entries[0].target.name, "Merisiel")

    def test_zero_hp_unconscious_and_death_save_targets_decline(self):
        cases = (
            (0, "alive", {"successes": 0, "failures": 0}),
            (0, "unconscious", {"successes": 0, "failures": 0}),
            (0, "unconscious", {"successes": 1, "failures": 0}),
        )
        for hp, status, death_saves in cases:
            with self.subTest(hp=hp, status=status, death_saves=death_saves):
                args = self._scenario()
                args["pc_states"]["Acheron"].update({
                    "hitPoints": hp,
                    "status": status,
                    "deathSaves": death_saves,
                })
                result = self._plan(args)
                self.assertEqual(result, EnemyResolutionDecline("downed_target", "enemy-batch-1"))

    def test_damage_that_reduces_pc_to_zero_projects_unconscious_without_death_save_mutation(self):
        args = self._scenario()
        args["pc_states"]["Acheron"]["hitPoints"] = 2
        result = self._with_fake_rng(args, [20, 6, 6])
        self.assertIsInstance(result, EnemyResolutionLedger)
        entry = result.entries[0]
        self.assertEqual(entry.target_hp_before, 2)
        self.assertEqual(entry.target_hp_after, 0)
        self.assertEqual(entry.target_status_after, "unconscious")

    def test_fixture_one_pc_and_four_pc_shapes_are_supported(self):
        one_pc = self._plan(self._scenario(party_size=1))
        four_pc = self._plan(self._scenario(party_size=4))
        self.assertIsInstance(one_pc, EnemyResolutionLedger)
        self.assertEqual(one_pc.entries[0].actor.name, "Goblin")
        self.assertEqual(one_pc.entries[0].target.name, "Acheron")
        self.assertIsInstance(four_pc, EnemyResolutionLedger)
        self.assertEqual(
            [entry.actor.name for entry in four_pc.entries],
            ["Goblin Alpha", "Goblin Beta"],
        )

    def test_bloodied_only_enemy_remains_supported(self):
        args = self._scenario()
        self._enemy(args["encounter"])["currentHitPoints"] = 10
        result = self._plan(args)
        self.assertIsInstance(result, EnemyResolutionLedger)
        self.assertEqual(result.bloodied[0].enemy.name, "Goblin")
        self.assertTrue(result.bloodied[0].bloodied)

    def test_typed_mitigation_only_declines_matching_damage_type(self):
        for field in (
            "damageResistances",
            "damageImmunities",
            "damageVulnerabilities",
        ):
            with self.subTest(field=field):
                args = self._scenario()
                args["monster_definitions"]["Goblin"]["multiattack"] = [
                    {"action": "Shortbow", "count": 1},
                ]
                args["pc_states"]["Acheron"][field] = ["slashing"]
                result = self._plan(args)
                self.assertIsInstance(result, EnemyResolutionLedger)
                self.assertEqual(result.entries[0].damage_type, "piercing")

                args["pc_states"]["Acheron"][field] = ["piercing"]
                result = self._plan(args)
                self.assertEqual(
                    result,
                    EnemyResolutionDecline("damage_mitigation", "enemy-batch-1"),
                )

    def test_scheduled_enemy_at_quarter_hp_declines_but_above_threshold_does_not(self):
        args = self._scenario()
        self._enemy(args["encounter"])["currentHitPoints"] = 5
        self.assertEqual(self._plan(args).reason_code, "near_death_enemy")
        args = self._scenario()
        self._enemy(args["encounter"])["currentHitPoints"] = 6
        self.assertIsInstance(self._plan(args), EnemyResolutionLedger)

    def test_declines_every_allowlisted_reason(self):
        def malformed_input(args):
            args["pc_states"] = None

        def malformed_encounter(args):
            args["encounter"]["creatures"] = None

        def invalid_batch_identity(args):
            args["batch_id"] = ""

        def malformed_turn_order(args):
            args["turn_order"] = []

        def ambiguous_identity(args):
            enemy = self._enemy(args["encounter"])
            enemy["name"] = "Acheron"
            args["turn_order"] = [
                {"name": "Acheron", "kind": "player"},
                {"name": "Acheron", "kind": "enemy"},
            ]
            args["enemy_turn_window"] = ["Acheron"]

        def unknown_actor(args):
            args["enemy_turn_window"] = [{"name": "Missing", "kind": "enemy"}]

        def npc_actor_in_window(args):
            args["encounter"]["creatures"].append({
                "name": "Ally", "type": "npc", "initiative": 12,
                "status": "alive", "currentHitPoints": 10, "maxHitPoints": 10,
                "conditions": [],
            })
            args["turn_order"].insert(1, {"name": "Ally", "kind": "npc"})
            args["enemy_turn_window"] = [{"name": "Ally", "kind": "npc"}]

        def unsupported_actor_kind(args):
            args["enemy_turn_window"] = [{"name": "Acheron", "kind": "player"}]

        def multiple_leaders(args):
            self._enemy(args["encounter"])["leader"] = True
            args["encounter"]["creatures"].append({
                "name": "Other Leader", "type": "enemy", "monsterType": "Goblin",
                "initiative": 1, "status": "alive", "currentHitPoints": 20,
                "maxHitPoints": 20, "leader": True,
            })

        def leader_down(args):
            enemy = self._enemy(args["encounter"])
            enemy.update({"leader": True, "status": "defeated", "currentHitPoints": 0})

        def near_death_enemy(args):
            self._enemy(args["encounter"])["currentHitPoints"] = 5

        def unknown_target(args):
            del args["pc_states"]["Acheron"]

        def no_eligible_target(args):
            args["turn_order"] = [{"name": "Goblin", "kind": "enemy"}]

        def downed_target(args):
            args["pc_states"]["Acheron"].update({"hitPoints": 0, "status": "unconscious"})

        def unsupported_target_state(args):
            args["pc_states"]["Acheron"]["condition_affected"] = ["prone"]

        def damage_mitigation(args):
            args["pc_states"]["Acheron"]["damageResistances"] = ["slashing"]

        def unsupported_condition(args):
            self._enemy(args["encounter"])["conditions"] = ["poisoned"]

        def advantage_or_disadvantage(args):
            args["monster_definitions"]["Goblin"]["actions"][0]["advantage"] = True

        def missing_monster_definition(args):
            args["monster_definitions"] = {}

        def malformed_monster_definition(args):
            args["monster_definitions"]["Goblin"] = {"actions": "not-a-list"}

        def malformed_multiattack(args):
            args["monster_definitions"]["Goblin"]["multiattack"] = []

        def unknown_action(args):
            args["monster_definitions"]["Goblin"]["multiattack"] = [
                {"action": "Unknown Strike", "count": 1},
            ]

        def ambiguous_action(args):
            goblin = args["monster_definitions"]["Goblin"]
            goblin["actions"].append(copy.deepcopy(goblin["actions"][0]))
            goblin["multiattack"] = [{"action": "Scimitar", "count": 1}]

        def bare_multiattack(args):
            args["monster_definitions"]["Goblin"]["actions"].append({
                "name": "Multiattack", "description": "Makes two attacks."
            })

        def unsupported_num_attacks(args):
            self._enemy(args["encounter"])["numAttacks"] = 2

        def category_action(category):
            def mutate(args):
                args["monster_definitions"]["Goblin"]["actions"] = [
                    {"name": category.title(), "type": category}
                ]
            return mutate

        def unsupported_action(args):
            args["monster_definitions"]["Goblin"]["actions"] = [
                {"name": "Guard Position", "description": "A defensive choice."}
            ]

        def missing_attack_stats(args):
            args["monster_definitions"]["Goblin"]["actions"] = [
                {"name": "Scimitar", "attackBonus": 4}
            ]

        def malformed_attack_stats(args):
            action = args["monster_definitions"]["Goblin"]["actions"][0]
            action["attackBonus"] = "four"

        def unsupported_damage_dice(args):
            args["monster_definitions"]["Goblin"]["actions"][0]["damageDice"] = "1d6+2"

        def missing_target_ac(args):
            del args["pc_states"]["Acheron"]["armorClass"]

        def malformed_pc_state(args):
            args["pc_states"]["Acheron"] = 42

        cases = {
            "malformed_input": malformed_input,
            "malformed_encounter": malformed_encounter,
            "invalid_batch_identity": invalid_batch_identity,
            "malformed_turn_order": malformed_turn_order,
            "ambiguous_identity": ambiguous_identity,
            "unknown_actor": unknown_actor,
            "npc_actor_in_window": npc_actor_in_window,
            "unsupported_actor_kind": unsupported_actor_kind,
            "multiple_leaders": multiple_leaders,
            "leader_down": leader_down,
            "near_death_enemy": near_death_enemy,
            "unknown_target": unknown_target,
            "no_eligible_target": no_eligible_target,
            "downed_target": downed_target,
            "unsupported_target_state": unsupported_target_state,
            "damage_mitigation": damage_mitigation,
            "unsupported_condition": unsupported_condition,
            "advantage_or_disadvantage": advantage_or_disadvantage,
            "missing_monster_definition": missing_monster_definition,
            "malformed_monster_definition": malformed_monster_definition,
            "malformed_multiattack": malformed_multiattack,
            "unknown_action": unknown_action,
            "ambiguous_action": ambiguous_action,
            "bare_multiattack": bare_multiattack,
            "unsupported_num_attacks": unsupported_num_attacks,
            "unsupported_spell": category_action("spell"),
            "unsupported_save": category_action("save"),
            "unsupported_special_action": category_action("special"),
            "unsupported_legendary_action": category_action("legendary"),
            "unsupported_reaction": category_action("reaction"),
            "unsupported_action": unsupported_action,
            "missing_attack_stats": missing_attack_stats,
            "malformed_attack_stats": malformed_attack_stats,
            "unsupported_damage_dice": unsupported_damage_dice,
            "missing_target_ac": missing_target_ac,
            "malformed_pc_state": malformed_pc_state,
        }
        self.assertEqual(set(cases), set(DECLINE_REASON_CODES))
        for expected_code, mutate in cases.items():
            with self.subTest(reason_code=expected_code):
                args = self._scenario()
                mutate(args)
                result = self._plan(args)
                self.assertIsInstance(result, EnemyResolutionDecline)
                self.assertEqual(result.reason_code, expected_code)
                expected_batch_id = "" if expected_code == "invalid_batch_identity" else "enemy-batch-1"
                self.assertEqual(result.batch_id, expected_batch_id)

    def test_scheduled_save_spell_condition_special_and_reaction_decline(self):
        categories = {
            "spell": "unsupported_spell",
            "save": "unsupported_save",
            "condition": "unsupported_condition",
            "special": "unsupported_special_action",
            "legendary": "unsupported_legendary_action",
            "reaction": "unsupported_reaction",
        }
        for category, expected in categories.items():
            with self.subTest(category=category):
                args = self._scenario()
                args["enemy_turn_window"] = [{
                    "name": "Goblin",
                    "kind": "enemy",
                    "scheduled_action_kind": category,
                }]
                result = self._plan(args)
                self.assertEqual(result.reason_code, expected)


if __name__ == "__main__":
    unittest.main()
