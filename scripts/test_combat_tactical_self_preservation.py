# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Flee, surrender, withdrawal, and departure menu contracts."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from core.combat.enemy_batch_apply import _build_encounter_projection
from core.combat.enemy_batch_orchestrator import complete_deterministic_enemy_batch_exit
from core.combat.enemy_resolution import EnemyDeparture, plan_enemy_batch
from core.combat.prompts import check_all_monsters_defeated
from core.combat.tactical_brain import validate_commander_plan
from scripts.combat_tactical_test_support import (
    ProviderFreeTestCase,
    actor_menu,
    build_g5t_scenario,
    build_menus,
    enemy,
    option,
    plan_with_defaults,
)


class CombatTacticalSelfPreservationTests(ProviderFreeTestCase):
    def test_terminal_deterministic_batch_uses_existing_exit_and_finalization_stages(self):
        calls = []
        updated_encounter = {"encounterId": "enc-2"}
        finalization = SimpleNamespace(dialogue_summary="summary", player_info={"name": "PC"})

        result = complete_deterministic_enemy_batch_exit(
            {"encounterId": "enc-1"},
            check_all_monsters_defeated=lambda _encounter: True,
            process_action_batch=lambda *args, **kwargs: (
                calls.append(("action_batch", args, kwargs))
                or SimpleNamespace(
                    encounter_data=updated_encounter,
                    is_combat_ending=True,
                    final_character_updates={"PC": []},
                )
            ),
            action_dependencies="action-dependencies",
            encounter_id="enc-1",
            conversation_history=[{"role": "user", "content": "Enemies turn."}],
            conversation_history_file="history.json",
            multi_pc_manager="manager",
            party_tracker_data={"worldConditions": {}},
            apply_final_character_updates=lambda updates, manager: calls.append(
                ("apply_updates", updates, manager)
            ),
            finalize_combat_session=lambda inputs, dependencies: (
                calls.append(("finalize", inputs, dependencies)) or finalization
            ),
            finalization_inputs="finalization-inputs",
            finalization_dependencies="finalization-dependencies",
        )

        self.assertIs(result.encounter_data, updated_encounter)
        self.assertIs(result.finalization, finalization)
        self.assertEqual([call[0] for call in calls], ["action_batch", "apply_updates", "finalize"])
        self.assertEqual(calls[0][1][0], [{"action": "exit"}])
        self.assertFalse(calls[0][2]["is_combat_ending"])

    def test_nonterminal_deterministic_batch_skips_exit_processing(self):
        action_batch = Mock()
        apply_updates = Mock()
        finalize = Mock()
        encounter = {"encounterId": "enc-1"}

        result = complete_deterministic_enemy_batch_exit(
            encounter,
            check_all_monsters_defeated=lambda _encounter: False,
            process_action_batch=action_batch,
            action_dependencies=None,
            encounter_id="enc-1",
            conversation_history=[],
            conversation_history_file="history.json",
            multi_pc_manager=None,
            party_tracker_data={},
            apply_final_character_updates=apply_updates,
            finalize_combat_session=finalize,
            finalization_inputs=None,
            finalization_dependencies=None,
        )

        self.assertIs(result.encounter_data, encounter)
        self.assertIsNone(result.finalization)
        action_batch.assert_not_called()
        apply_updates.assert_not_called()
        finalize.assert_not_called()

    def test_precommitted_terminal_batch_finalizes_without_reapplying_rewards(self):
        action_batch = Mock()
        apply_updates = Mock()
        finalization = SimpleNamespace(dialogue_summary="summary", player_info={})
        finalize = Mock(return_value=finalization)
        encounter = {"encounterId": "enc-1"}

        result = complete_deterministic_enemy_batch_exit(
            encounter,
            check_all_monsters_defeated=lambda _encounter: True,
            process_action_batch=action_batch,
            action_dependencies=None,
            encounter_id="enc-1",
            conversation_history=[],
            conversation_history_file="history.json",
            multi_pc_manager=None,
            party_tracker_data={},
            apply_final_character_updates=apply_updates,
            finalize_combat_session=finalize,
            finalization_inputs="finalization-inputs",
            finalization_dependencies="finalization-dependencies",
            precommitted_exit=True,
        )

        self.assertIs(result.encounter_data, encounter)
        self.assertIs(result.finalization, finalization)
        action_batch.assert_not_called()
        apply_updates.assert_not_called()
        finalize.assert_called_once_with(
            "finalization-inputs", "finalization-dependencies"
        )

    def test_departures_project_to_existing_defeated_exit_state(self):
        scenario = build_g5t_scenario(4)
        for creature in (
            item for item in scenario["encounter"]["creatures"]
            if item["type"] == "enemy"
        ):
            creature["currentHitPoints"] = (
                1 if creature["name"] == "Goblin Squad B"
                else max(1, creature["maxHitPoints"] // 2)
            )
        ledger = plan_enemy_batch(
            scenario["encounter"],
            scenario["pc_states"],
            scenario["monster_definitions"],
            scenario["turn_order"],
            scenario["batch_id"],
            batch_kind=scenario["batch_kind"],
            fixture_seed=scenario["fixture_seed"],
            enemy_turn_window=scenario["enemy_turn_window"],
            allow_near_death=True,
        )
        enemies = [
            item for item in scenario["encounter"]["creatures"]
            if item["type"] == "enemy"
        ]
        departure_ledger = replace(
            ledger,
            entries=(),
            departures=tuple(
                EnemyDeparture(
                    enemy=next(
                        item for item in ledger.bloodied
                        if item.enemy.name == creature["name"]
                    ).enemy,
                    reason="fled" if index < 2 else "surrendered",
                )
                for index, creature in enumerate(enemies)
            ),
        )

        projected = _build_encounter_projection(
            departure_ledger, scenario["encounter"], []
        )

        projected_enemies = [
            item for item in projected["creatures"] if item["type"] == "enemy"
        ]
        self.assertTrue(all(item["status"] == "defeated" for item in projected_enemies))
        self.assertEqual(
            [item["defeatReason"] for item in projected_enemies],
            ["fled", "fled", "surrendered"],
        )
        self.assertTrue(check_all_monsters_defeated(projected))

    def test_flee_is_unconditionally_issued_at_or_below_bloodied(self):
        scenario = build_g5t_scenario(1)
        goblin = enemy(scenario, "Goblin Squad A")
        for hp in (3, 2):
            with self.subTest(hp=hp):
                goblin["currentHitPoints"] = hp
                menus = build_menus(scenario)
                flee = option(actor_menu(menus, "Goblin Squad A"), "flee")
                self.assertIsNone(flee.conditional_on)

    def test_above_bloodied_flee_requires_issued_withdrawal_order(self):
        scenario = build_g5t_scenario(1)
        goblin = enemy(scenario, "Goblin Squad A")
        goblin["currentHitPoints"] = 4
        menus = build_menus(scenario)
        goblin_menu = actor_menu(menus, "Goblin Squad A")
        flee = option(goblin_menu, "flee")
        self.assertEqual(flee.conditional_on, "withdrawal_order")

        plan = plan_with_defaults(menus, {"Goblin Squad A": [flee.option_id]})
        result = validate_commander_plan(plan, menus)
        goblin_choice = next(choice for choice in result.choices if choice.actor.name == "Goblin Squad A")
        self.assertEqual(goblin_choice.kind, "attack")
        self.assertEqual(goblin_choice.default_reason, "INVALID_CHOICE")
        self.assertFalse(goblin_choice.no_attack)

    def test_withdrawal_order_authorizes_conditional_flee_and_consumes_action(self):
        scenario = build_g5t_scenario(1)
        enemy(scenario, "Goblin Squad A")["currentHitPoints"] = 4
        menus = build_menus(scenario)
        flee = option(actor_menu(menus, "Goblin Squad A"), "flee")
        withdrawal = next(
            item for item in menus.commander_options if item.kind == "withdrawal_order"
        )
        plan = plan_with_defaults(menus, {"Goblin Squad A": [flee.option_id]})
        plan["orders"] = [withdrawal.option_id]

        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor.name == "Goblin Squad A")
        self.assertTrue(result.withdrawal_order_issued)
        self.assertEqual(choice.kind, "flee")
        self.assertTrue(choice.action_consumed)
        self.assertTrue(choice.no_attack)
        self.assertTrue(choice.disengage)
        self.assertTrue(choice.no_opportunity_attacks)
        self.assertTrue(choice.leaves_at_turn_end)
        self.assertEqual(choice.defeat_reason, "fled")

    def test_bloodied_flee_also_consumes_action_and_has_no_attack(self):
        scenario = build_g5t_scenario(1)
        enemy(scenario, "Goblin Squad A")["currentHitPoints"] = 3
        menus = build_menus(scenario)
        flee = option(actor_menu(menus, "Goblin Squad A"), "flee")
        plan = plan_with_defaults(menus, {"Goblin Squad A": [flee.option_id]})

        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor.name == "Goblin Squad A")
        self.assertEqual(choice.kind, "flee")
        self.assertTrue(choice.action_consumed)
        self.assertTrue(choice.no_attack)
        self.assertTrue(choice.disengage)
        self.assertTrue(choice.no_opportunity_attacks)
        self.assertFalse(choice.option_ids == ())

    def test_fled_enemy_is_removed_from_later_actor_and_target_menus(self):
        scenario = build_g5t_scenario(4)
        enemy(scenario, "Goblin Squad A")["currentHitPoints"] = 3
        menus = build_menus(scenario)
        flee = option(actor_menu(menus, "Goblin Squad A"), "flee")
        plan = plan_with_defaults(menus, {"Goblin Squad A": [flee.option_id]})

        result = validate_commander_plan(plan, menus)
        remaining_actor_names = {item.actor.name for item in result.remaining_menus.actor_menus}
        remaining_target_names = {item.name for item in result.remaining_target_identities}
        self.assertNotIn("Goblin Squad A", remaining_actor_names)
        self.assertNotIn("Goblin Squad A", remaining_target_names)
        self.assertIn("Goblin Squad B", remaining_actor_names)
        self.assertIn("Goblin Squad B", remaining_target_names)

    def test_individual_surrender_is_only_issued_at_near_death(self):
        scenario = build_g5t_scenario(1)
        goblin = enemy(scenario, "Goblin Squad A")
        goblin["currentHitPoints"] = 2
        menu = actor_menu(build_menus(scenario), "Goblin Squad A")
        self.assertFalse(any(item.kind == "surrender" for item in menu.choices))

        goblin["currentHitPoints"] = 1
        menu = actor_menu(build_menus(scenario), "Goblin Squad A")
        surrender = option(menu, "surrender")
        self.assertIsNone(surrender.conditional_on)

    def test_individual_surrender_departure_does_not_remove_other_enemies(self):
        scenario = build_g5t_scenario(4)
        enemy(scenario, "Goblin Squad A")["currentHitPoints"] = 1
        menus = build_menus(scenario)
        surrender = option(actor_menu(menus, "Goblin Squad A"), "surrender")
        plan = plan_with_defaults(menus, {"Goblin Squad A": [surrender.option_id]})

        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor.name == "Goblin Squad A")
        self.assertEqual(choice.kind, "surrender")
        self.assertTrue(choice.action_consumed)
        self.assertTrue(choice.no_attack)
        self.assertTrue(choice.leaves_at_turn_end)
        self.assertEqual(choice.defeat_reason, "surrendered")
        self.assertIn("Goblin Squad A", {item.name for item in result.departed_creatures})
        self.assertNotIn("Goblin Squad B", {item.name for item in result.departed_creatures})

    def test_commander_can_flee_and_is_removed_as_next_batch_commander(self):
        scenario = build_g5t_scenario(1)
        menus = build_menus(scenario)
        captain_menu = actor_menu(menus, "Hobgoblin Captain")
        flee = option(captain_menu, "flee")
        self.assertEqual(flee.conditional_on, "withdrawal_order")
        withdrawal = next(item for item in menus.commander_options if item.kind == "withdrawal_order")
        plan = plan_with_defaults(menus, {"Hobgoblin Captain": [flee.option_id]})
        plan["orders"] = [withdrawal.option_id]

        result = validate_commander_plan(plan, menus)
        self.assertIsNone(result.remaining_menus.commander)
        self.assertNotIn(
            "Hobgoblin Captain",
            {item.actor.name for item in result.remaining_menus.actor_menus},
        )
        captain_choice = next(item for item in result.choices if item.actor.name == "Hobgoblin Captain")
        self.assertEqual(captain_choice.defeat_reason, "fled")

    def test_commander_can_surrender_individually_at_near_death(self):
        scenario = build_g5t_scenario(4)
        captain = enemy(scenario, "Hobgoblin Captain")
        captain["currentHitPoints"] = 9
        menus = build_menus(scenario)
        surrender = option(actor_menu(menus, "Hobgoblin Captain"), "surrender")
        plan = plan_with_defaults(menus, {"Hobgoblin Captain": [surrender.option_id]})

        result = validate_commander_plan(plan, menus)
        captain_choice = next(item for item in result.choices if item.actor.name == "Hobgoblin Captain")
        self.assertEqual(captain_choice.defeat_reason, "surrendered")
        self.assertEqual(
            [item.name for item in result.departed_creatures], ["Hobgoblin Captain"]
        )

    def test_commander_side_surrender_departs_all_living_side_members(self):
        scenario = build_g5t_scenario(4)
        enemy(scenario, "Goblin Squad B")["currentHitPoints"] = 1
        menus = build_menus(scenario)
        side_option = next(
            item for item in menus.commander_options
            if item.kind == "commander_side_surrender"
        )
        plan = plan_with_defaults(menus)
        plan["orders"] = [side_option.option_id]

        result = validate_commander_plan(plan, menus)
        self.assertTrue(result.side_surrender)
        self.assertEqual(
            {item.name for item in result.departed_creatures},
            {"Hobgoblin Captain", "Goblin Squad A", "Goblin Squad B"},
        )
        self.assertEqual(result.remaining_target_identities, ())
        self.assertEqual(result.remaining_menus.actor_menus, ())

    def test_duplicate_withdrawal_order_is_rejected_and_does_not_authorize_flee(self):
        scenario = build_g5t_scenario(1)
        enemy(scenario, "Goblin Squad A")["currentHitPoints"] = 4
        menus = build_menus(scenario)
        flee = option(actor_menu(menus, "Goblin Squad A"), "flee")
        withdrawal = next(item for item in menus.commander_options if item.kind == "withdrawal_order")
        plan = plan_with_defaults(menus, {"Goblin Squad A": [flee.option_id]})
        plan["orders"] = [withdrawal.option_id, withdrawal.option_id]

        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor.name == "Goblin Squad A")
        self.assertFalse(result.withdrawal_order_issued)
        self.assertEqual(choice.kind, "attack")
        self.assertEqual(choice.default_reason, "INVALID_CHOICE")
        self.assertIn("DUPLICATE_ID", result.rejected_reason_codes)


if __name__ == "__main__":
    unittest.main()
