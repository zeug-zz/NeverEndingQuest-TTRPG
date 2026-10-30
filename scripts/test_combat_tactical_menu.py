# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded menu-construction contracts for commander tactical planning."""

import copy
import unittest

from core.combat.enemy_resolution import EnemyResolutionLedger, plan_enemy_batch
from core.combat.tactical_brain import (
    MAX_LEGAL_TARGETS,
    TacticalMenuBuildFailure,
    build_tactical_menus,
    validate_commander_plan,
)
from scripts import combat_latency_fixtures
from scripts.combat_tactical_test_support import (
    ProviderFreeTestCase,
    actor_menu,
    build_g5t_scenario,
    build_menus,
    enemy,
    option,
    plan_with_defaults,
)


class CombatTacticalMenuTests(ProviderFreeTestCase):
    def test_g5t_party_shapes_get_only_scheduled_enemy_menus(self):
        for party_size, enemy_count in ((1, 3), (4, 3)):
            with self.subTest(party_size=party_size):
                scenario = build_g5t_scenario(party_size)
                menus = build_menus(scenario)
                self.assertEqual(len(menus.actor_menus), enemy_count)
                self.assertEqual(menus.commander.name, "Hobgoblin Captain")
                self.assertTrue(all(menu.actor.kind == "enemy" for menu in menus.actor_menus))
                self.assertEqual(
                    [menu.actor.name for menu in menus.actor_menus],
                    [row["name"] for row in scenario["enemy_turn_window"]],
                )

    def test_attack_slots_and_rule_defaults_match_the_resolver_ledger(self):
        scenario = build_g5t_scenario(4)
        resolver_inputs = {
            key: value
            for key, value in scenario.items()
            if key not in {"tactical_features"}
        }
        ledger = plan_enemy_batch(**resolver_inputs)
        self.assertIsInstance(ledger, EnemyResolutionLedger)
        menus = build_menus(scenario)

        for menu in menus.actor_menus:
            entries = [entry for entry in ledger.entries if entry.actor == menu.actor]
            self.assertEqual(len(menu.attack_slots), len(entries))
            self.assertEqual(len(menu.default_option_ids), len(entries))
            for entry, slot, default_id in zip(
                entries, menu.attack_slots, menu.default_option_ids
            ):
                selected_default = next(
                    item for item in slot if item.option_id == default_id
                )
                self.assertEqual(selected_default.target, entry.target)
                self.assertEqual(selected_default.action_name, entry.action_name)

    def test_ids_are_opaque_stable_strings_and_unique_within_batch(self):
        scenario = build_g5t_scenario(4)
        menus = build_menus(scenario)
        repeated = build_menus(scenario)
        ids = [item.option_id for item in menus.all_options]
        self.assertTrue(all(item.startswith("opt_") for item in ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [item.option_id for item in repeated.all_options])
        self.assertNotIn("Goblin Squad A", " ".join(ids))
        self.assertNotIn("Longsword", " ".join(ids))

    def test_attack_targets_are_exactly_resolver_legal_targets(self):
        scenario = build_g5t_scenario(4)
        menus = build_menus(scenario)
        legal = set(menus.legal_targets)
        self.assertEqual(len(legal), 4)
        for menu in menus.actor_menus:
            for slot in menu.attack_slots:
                self.assertEqual({item.target for item in slot}, legal)
                self.assertTrue(all(item.target.kind == "player" for item in slot))

    def test_only_explicit_enemy_usable_cover_is_issued(self):
        scenario = build_g5t_scenario(1)
        captain_menu = actor_menu(build_menus(scenario), "Hobgoblin Captain")
        cover = option(
            captain_menu,
            "take_cover",
            feature_id=combat_latency_fixtures.G5T_TRAINING_PIT_FEATURE_ID,
        )
        self.assertEqual(cover.cover_type, "half")
        self.assertEqual(cover.feature_name, "Scarred Shield Racks")

        scenario["tactical_features"] = [
            {
                "featureId": "player-only-cover",
                "name": "Player Barricade",
                "kind": "cover",
                "coverType": "three_quarters",
                "usableBy": ["player"],
            }
        ]
        player_only_menu = actor_menu(build_menus(scenario), "Hobgoblin Captain")
        self.assertFalse(any(item.kind == "take_cover" for item in player_only_menu.choices))

    def test_malformed_or_duplicate_cover_data_fails_closed_for_cover_options(self):
        scenario = build_g5t_scenario(1)
        feature = copy.deepcopy(scenario["tactical_features"][0])
        scenario["tactical_features"] = [feature, copy.deepcopy(feature)]
        menus = build_menus(scenario)
        self.assertFalse(any(
            item.kind == "take_cover"
            for menu in menus.actor_menus
            for item in menu.choices
        ))

        scenario["tactical_features"] = [{**feature, "coverType": "full"}]
        menus = build_menus(scenario)
        self.assertFalse(any(
            item.kind == "take_cover"
            for menu in menus.actor_menus
            for item in menu.choices
        ))

    def test_flee_and_surrender_options_follow_inclusive_hp_boundaries(self):
        scenario = build_g5t_scenario(1)
        goblin = enemy(scenario, "Goblin Squad A")

        for hp, expected_flee_condition, expected_surrender in (
            (4, "withdrawal_order", False),
            (3, None, False),
            (1, None, True),
        ):
            with self.subTest(hp=hp):
                goblin["currentHitPoints"] = hp
                menus = build_menus(scenario)
                goblin_menu = actor_menu(menus, "Goblin Squad A")
                flee = option(goblin_menu, "flee")
                self.assertEqual(flee.conditional_on, expected_flee_condition)
                self.assertEqual(
                    any(item.kind == "surrender" for item in goblin_menu.choices),
                    expected_surrender,
                )

    def test_commander_orders_are_only_issued_when_boundary_requires_them(self):
        scenario = build_g5t_scenario(1)
        menus = build_menus(scenario)
        self.assertTrue(any(item.kind == "withdrawal_order" for item in menus.commander_options))
        self.assertFalse(any(
            item.kind == "commander_side_surrender" for item in menus.commander_options
        ))

        enemy(scenario, "Goblin Squad A")["currentHitPoints"] = 1
        menus = build_menus(scenario)
        self.assertTrue(any(
            item.kind == "commander_side_surrender" for item in menus.commander_options
        ))

        for creature in scenario["encounter"]["creatures"]:
            if creature["type"] == "enemy":
                creature["currentHitPoints"] = creature["maxHitPoints"] // 2
        menus = build_menus(scenario)
        self.assertFalse(any(item.kind == "withdrawal_order" for item in menus.commander_options))

    def test_lone_near_death_commander_has_both_legal_surrender_paths(self):
        scenario = build_g5t_scenario(1)
        captain = enemy(scenario, "Hobgoblin Captain")
        captain["currentHitPoints"] = 9
        for name in ("Goblin Squad A", "Goblin Squad B"):
            goblin = enemy(scenario, name)
            goblin.update({
                "currentHitPoints": 3,
                "status": "defeated",
                "defeatReason": "fled",
            })
        scenario["enemy_turn_window"] = [{
            "name": "Hobgoblin Captain",
            "kind": "enemy",
        }]

        menus = build_menus(scenario)
        self.assertEqual(
            [menu.actor.name for menu in menus.actor_menus],
            ["Hobgoblin Captain"],
        )
        captain_menu = actor_menu(menus, "Hobgoblin Captain")
        self.assertEqual(len(captain_menu.attack_slots), 2)
        individual_surrender = option(captain_menu, "surrender")
        side_surrender = next(
            item for item in menus.commander_options
            if item.kind == "commander_side_surrender"
        )
        self.assertFalse(any(
            item.kind == "withdrawal_order" for item in menus.commander_options
        ))

        individual_plan = plan_with_defaults(
            menus,
            {"Hobgoblin Captain": [individual_surrender.option_id]},
        )
        individual_result = validate_commander_plan(individual_plan, menus)
        self.assertEqual(individual_result.status, "accepted")
        self.assertEqual(individual_result.choices[0].kind, "surrender")
        self.assertEqual(individual_result.choices[0].defeat_reason, "surrendered")

        side_plan = plan_with_defaults(menus)
        side_plan["orders"] = [side_surrender.option_id]
        side_result = validate_commander_plan(side_plan, menus)
        self.assertEqual(side_result.status, "accepted")
        self.assertTrue(side_result.side_surrender)
        self.assertEqual(
            [identity.name for identity in side_result.departed_creatures],
            ["Hobgoblin Captain"],
        )

    def test_menu_bounds_reject_more_than_maximum_legal_targets(self):
        scenario = build_g5t_scenario(4)
        self.assertEqual(MAX_LEGAL_TARGETS, 32)
        for index in range(29):
            name = "Extra Tactical PC %02d" % index
            initiative = 5 - index
            state = combat_latency_fixtures._character_payload(name, initiative)
            scenario["pc_states"][name] = state
            scenario["encounter"]["creatures"].append({
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
        scenario["turn_order"] = [
            {"name": creature["name"], "kind": creature["type"]}
            for creature in sorted(
                scenario["encounter"]["creatures"],
                key=lambda row: row["initiative"],
                reverse=True,
            )
        ]
        result = build_menus(scenario)
        self.assertIsInstance(result, TacticalMenuBuildFailure)
        self.assertEqual(result.reason_code, "menu_limit_exceeded")

    def test_missing_or_ambiguous_commander_does_not_issue_a_menu(self):
        scenario = build_g5t_scenario(1)
        enemy(scenario, "Hobgoblin Captain").pop("tactics")
        result = build_menus(scenario)
        self.assertIsInstance(result, TacticalMenuBuildFailure)
        self.assertEqual(result.reason_code, "commander_unavailable")

        scenario = build_g5t_scenario(1)
        goblin = enemy(scenario, "Goblin Squad A")
        goblin.update({"leader": True, "tactics": "commander"})
        result = build_menus(scenario)
        self.assertIsInstance(result, TacticalMenuBuildFailure)
        self.assertEqual(result.reason_code, "commander_ambiguous")


if __name__ == "__main__":
    unittest.main()
