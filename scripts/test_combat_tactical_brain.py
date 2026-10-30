# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Structured plan validation and rule-tier fallback contracts."""

import copy
import json
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

import model_config
import core.combat.enemy_batch_orchestrator as enemy_batch_orchestrator

from core.combat.enemy_batch_orchestrator import (
    EnemyBatchExecution,
    EnemyBatchFallback,
    EnemyBatchOrchestrationDependencies,
    _batch_id,
    try_execute_deterministic_enemy_batch,
)
from core.combat.enemy_narration import build_enemy_batch_template_narration
from core.combat.enemy_resolution import EnemyResolutionDecline, plan_enemy_batch
from core.combat.multi_pc.manager import MultiPCCombatManager
from core.combat.prompts import check_all_monsters_defeated
from core.combat.multi_pc.state import PCCombatState, PCStatus
from core.combat.multi_pc.turn_queue import Combatant, CombatantType
from core.combat.multi_pc.sync import apply_opening_batch_marker
from core.combat.persistence import CombatActionDependencies, process_combat_action_batch
from core.combat.turn import RoundTransitionDependencies

from core.combat.tactical_brain import (
    TACTICAL_DEFAULT_REASON_CODES,
    ValidatedTacticalPlan,
    build_perception_projection,
    build_standing_orders_messages,
    compile_standing_orders,
    parse_standing_orders_response,
    rule_default_tactical_plan,
    standing_orders_intent,
    validate_commander_plan,
)
from core.combat.tactical_prefetch import TacticalPrefetchResult
from scripts.combat_tactical_test_support import (
    ProviderFreeTestCase,
    actor_menu,
    build_g5t_scenario,
    build_menus,
    enemy,
    option,
    plan_with_defaults,
)


SCRATCH_ROOT = Path("tmp/router-rollout/g5t")
_DEFAULT_PLAN_RESPONSE = object()


class CombatTacticalBrainTests(ProviderFreeTestCase):
    def test_standing_orders_compile_first_currently_legal_clause(self):
        scenario = build_g5t_scenario(1)
        menus = build_menus(scenario)
        orders = {"actors": [], "commander_clauses": []}
        for menu in menus.actor_menus:
            if menu.actor.name == "Goblin Squad A":
                clauses = [
                    {
                        "when": "always",
                        "do": {
                            "kind": "attack",
                            "target": {"name": "Off-scene Wight", "kind": "enemy"},
                        },
                    },
                    {
                        "when": "always",
                        "do": {
                            "kind": "attack",
                            "target": {"name": "Acheron", "kind": "player"},
                            "action": "Shortbow",
                        },
                    },
                    {"when": "always", "do": {"kind": "hold"}},
                ]
            else:
                clauses = [{"when": "always", "do": {"kind": "hold"}}]
            orders["actors"].append({
                "actor": {"name": menu.actor.name, "kind": "enemy"},
                "clauses": clauses,
            })

        candidate = compile_standing_orders(orders, menus, scenario["encounter"])
        self.assertIsNotNone(candidate)
        validated = validate_commander_plan(candidate, menus)
        self.assertEqual(validated.status, "accepted")
        goblin_menu = actor_menu(menus, "Goblin Squad A")
        goblin_choice = next(
            choice for choice in validated.choices
            if choice.actor.name == "Goblin Squad A"
        )
        self.assertEqual(len(goblin_choice.option_ids), 1)
        selected = next(
            option for option in goblin_menu.attack_slots[0]
            if option.option_id == goblin_choice.option_ids[0]
        )
        self.assertEqual(selected.target.name, "Acheron")
        self.assertEqual(selected.action_name, "Shortbow")

    def test_standing_orders_unmappable_clauses_default_through_tactical_plan(self):
        scenario = build_g5t_scenario(1)
        menus = build_menus(scenario)
        orders = {
            "actors": [{
                "actor": {"name": menu.actor.name, "kind": "enemy"},
                "clauses": [{
                    "when": "always",
                    "do": {
                        "kind": "attack",
                        "target": {"name": "Off-scene Wight", "kind": "enemy"},
                    },
                }],
            } for menu in menus.actor_menus],
            "commander_clauses": [{
                "when": "always", "do": "side_surrender",
            }],
        }
        candidate = compile_standing_orders(orders, menus, scenario["encounter"])
        self.assertEqual(candidate, {"choices": [], "orders": []})
        compiled = validate_commander_plan(candidate, menus)
        self.assertEqual(compiled.status, "rejected_all")
        self.assertEqual(
            {choice.default_reason for choice in compiled.choices},
            {"MISSING_CHOICE"},
        )
        unavailable = rule_default_tactical_plan(
            menus, "STANDING_ORDERS_UNAVAILABLE"
        )
        self.assertTrue(all(
            choice.default_reason == "STANDING_ORDERS_UNAVAILABLE"
            and choice.option_ids == menu.default_option_ids
            for choice, menu in zip(unavailable.choices, menus.actor_menus)
        ))

    def test_standing_orders_use_current_state_conditions_and_legal_commander_options(self):
        scenario = build_g5t_scenario(1)
        captain = enemy(scenario, "Hobgoblin Captain")
        captain["currentHitPoints"] = max(1, captain["maxHitPoints"] // 4)
        menus = build_menus(scenario)
        orders = {
            "actors": [{
                "actor": {"name": menu.actor.name, "kind": "enemy"},
                "clauses": [{"when": "self_bloodied", "do": {"kind": "hold"}}],
            } for menu in menus.actor_menus],
            "commander_clauses": [
                {"when": "always", "do": "withdrawal_order"},
                {"when": "self_near_death", "do": "side_surrender"},
            ],
        }
        candidate = compile_standing_orders(orders, menus, scenario["encounter"])
        self.assertEqual(len(candidate["orders"]), 1)
        self.assertTrue(menus.commander_options)
        self.assertEqual(
            next(choice for choice in validate_commander_plan(candidate, menus).choices
                 if choice.actor.name == "Hobgoblin Captain").kind,
            "hold",
        )

    def test_valid_plan_accepts_only_issued_default_attack_ids(self):
        menus = build_menus(build_g5t_scenario(4))
        plan = plan_with_defaults(menus)
        result = validate_commander_plan(plan, menus)
        self.assertIsInstance(result, ValidatedTacticalPlan)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(len(result.choices), len(menus.actor_menus))
        self.assertTrue(all(choice.kind == "attack" for choice in result.choices))
        self.assertTrue(all(choice.default_reason is None for choice in result.choices))

    def test_valid_two_javelin_attack_slot_plan_is_accepted(self):
        menus = build_menus(build_g5t_scenario(1))
        captain = actor_menu(menus, "Hobgoblin Captain")
        self.assertEqual(len(captain.attack_slots), 2)
        self.assertTrue(all(
            slot[0].action_name == "Javelin" and slot[0].attack_is_ranged is True
            for slot in captain.attack_slots
        ))

        result = validate_commander_plan(plan_with_defaults(menus), menus)
        choice = next(item for item in result.choices if item.actor == captain.actor)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(choice.option_ids, captain.default_option_ids)
        self.assertIsNone(choice.default_reason)

    def test_attack_projection_marks_only_ranged_options_cover_compatible(self):
        scenario = build_g5t_scenario(1)
        menus = build_menus(scenario)
        projection = build_perception_projection(menus, scenario["pc_states"])
        captain_row = next(
            row for row in projection["eligible_actors"]
            if row["actor"] == "Hobgoblin Captain"
        )
        self.assertTrue(all(
            option["cover_compatible"] is True
            for slot in captain_row["attack_slots"] for option in slot
        ))

        scenario["monster_definitions"]["Hobgoblin Captain"]["multiattack"] = [
            {"action": "Longsword", "count": 2}
        ]
        melee_menus = build_menus(scenario)
        melee_projection = build_perception_projection(
            melee_menus, scenario["pc_states"]
        )
        melee_row = next(
            row for row in melee_projection["eligible_actors"]
            if row["actor"] == "Hobgoblin Captain"
        )
        self.assertTrue(all(
            option["cover_compatible"] is False
            for slot in melee_row["attack_slots"] for option in slot
        ))

    def test_ranged_attack_and_cover_are_accepted_in_one_actor_choice(self):
        menus = build_menus(build_g5t_scenario(1))
        goblin = actor_menu(menus, "Goblin Squad A")
        attack = goblin.attack_slots[0][0]
        cover = next(item for item in goblin.choices if item.kind == "take_cover")
        self.assertTrue(attack.attack_is_ranged)

        result = validate_commander_plan(
            plan_with_defaults(menus, {
                goblin.actor.name: [attack.option_id, cover.option_id],
            }),
            menus,
        )
        choice = next(item for item in result.choices if item.actor == goblin.actor)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(choice.kind, "attack")
        self.assertEqual(choice.option_ids, (attack.option_id,))
        self.assertEqual(choice.cover_option_id, cover.option_id)
        self.assertEqual(choice.cover_feature_id, cover.feature_id)
        self.assertFalse(choice.no_attack)

    def test_melee_attack_plus_cover_defaults_actor(self):
        scenario = build_g5t_scenario(1)
        scenario["monster_definitions"]["Hobgoblin Captain"]["multiattack"] = [
            {"action": "Longsword", "count": 2}
        ]
        menus = build_menus(scenario)
        captain = actor_menu(menus, "Hobgoblin Captain")
        cover = next(item for item in captain.choices if item.kind == "take_cover")
        self.assertTrue(all(
            slot[0].attack_is_ranged is False for slot in captain.attack_slots
        ))

        result = validate_commander_plan(
            plan_with_defaults(menus, {
                captain.actor.name: [
                    *captain.default_option_ids,
                    cover.option_id,
                ],
            }),
            menus,
        )
        choice = next(item for item in result.choices if item.actor == captain.actor)
        self.assertEqual(result.status, "partially_defaulted")
        self.assertEqual(choice.default_reason, "INVALID_CHOICE")
        self.assertEqual(choice.option_ids, captain.default_option_ids)
        self.assertIsNone(choice.cover_option_id)

    def test_p1_plan_shape_accepts_cover_with_ranged_options(self):
        menus = build_menus(build_g5t_scenario(1))
        overrides = {}
        for name in ("Hobgoblin Captain", "Goblin Squad A", "Goblin Squad B"):
            menu = actor_menu(menus, name)
            cover = next(item for item in menu.choices if item.kind == "take_cover")
            overrides[name] = [
                *(slot[0].option_id for slot in menu.attack_slots),
                cover.option_id,
            ]
        self.assertEqual(
            [len(overrides[name]) for name in (
                "Hobgoblin Captain", "Goblin Squad A", "Goblin Squad B"
            )],
            [3, 2, 2],
        )

        result = validate_commander_plan(plan_with_defaults(menus, overrides), menus)
        self.assertEqual(result.status, "accepted")
        by_name = {choice.actor.name: choice for choice in result.choices}
        for name in ("Hobgoblin Captain", "Goblin Squad A", "Goblin Squad B"):
            self.assertIsNone(by_name[name].default_reason)
            self.assertIsNotNone(by_name[name].cover_option_id)

    def test_two_cover_options_in_one_actor_choice_are_rejected(self):
        scenario = build_g5t_scenario(1)
        second_feature = dict(scenario["tactical_features"][0])
        second_feature.update(featureId="PIT_COVER_SECOND", name="Second cover")
        scenario["tactical_features"].append(second_feature)
        menus = build_menus(scenario)
        goblin = actor_menu(menus, "Goblin Squad A")
        covers = [item for item in goblin.choices if item.kind == "take_cover"]
        self.assertEqual(len(covers), 2)

        result = validate_commander_plan(
            plan_with_defaults(menus, {
                goblin.actor.name: [
                    goblin.attack_slots[0][0].option_id,
                    covers[0].option_id,
                    covers[1].option_id,
                ],
            }),
            menus,
        )
        choice = next(item for item in result.choices if item.actor == goblin.actor)
        self.assertEqual(choice.default_reason, "INVALID_CHOICE")
        self.assertEqual(choice.option_ids, goblin.default_option_ids)
        self.assertIsNone(choice.cover_option_id)

    def test_issued_option_from_wrong_attack_slot_defaults_only_that_slot(self):
        menus = build_menus(build_g5t_scenario(4))
        captain = actor_menu(menus, "Hobgoblin Captain")
        self.assertEqual(len(captain.attack_slots), 2)
        selected_first = captain.attack_slots[0][0].option_id
        wrong_slot_option = next(
            option for option in captain.attack_slots[0]
            if option.option_id != selected_first
        )
        selected_ids = [selected_first, wrong_slot_option.option_id]
        plan = plan_with_defaults(menus)
        captain_row = next(
            row for row in plan["choices"] if row["actor"] == captain.actor.name
        )
        captain_row["option_ids"] = selected_ids

        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor == captain.actor)
        self.assertEqual(result.status, "partially_defaulted")
        self.assertEqual(choice.option_ids, (
            selected_ids[0], captain.default_option_ids[1]
        ))
        self.assertEqual(choice.default_reason, "INVALID_CHOICE")
        self.assertTrue(all(
            item.default_reason is None
            for item in result.choices if item.actor != captain.actor
        ))

    def test_numeric_or_free_form_whole_plan_defaults_every_actor(self):
        menus = build_menus(build_g5t_scenario(1))
        for raw in (7, 3.5, "attack Goblin Squad A", None):
            with self.subTest(raw=raw):
                result = validate_commander_plan(raw, menus)
                self.assertEqual(result.status, "rejected_all")
                self.assertEqual(
                    {choice.default_reason for choice in result.choices},
                    {"INVALID_CHOICE"},
                )
                self.assertEqual(
                    [choice.option_ids for choice in result.choices],
                    [menu.default_option_ids for menu in menus.actor_menus],
                )

    def test_numeric_mechanics_and_free_form_action_rows_default_actor(self):
        menus = build_menus(build_g5t_scenario(1))
        captain = actor_menu(menus, "Hobgoblin Captain")
        invalid_rows = (
            {"actor": captain.actor.name, "option_ids": [1]},
            {"actor": captain.actor.name, "action": "attack Goblin"},
            {"actor": captain.actor.name, "option_ids": ["flee"]},
            {"actor": captain.actor.name, "option_ids": [captain.default_option_ids[0]], "damage": 99},
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                result = validate_commander_plan({"choices": [row]}, menus)
                choice = next(
                    item for item in result.choices
                    if item.actor.name == captain.actor.name
                )
                self.assertEqual(choice.kind, "attack")
                self.assertEqual(choice.default_reason, "INVALID_CHOICE")
                self.assertTrue(choice.option_ids)

    def test_missing_actor_choice_uses_ledger_rule_choice_and_reason(self):
        menus = build_menus(build_g5t_scenario(1))
        plan = {"choices": [], "orders": []}
        result = validate_commander_plan(plan, menus)
        self.assertEqual(result.status, "rejected_all")
        for choice, menu in zip(result.choices, menus.actor_menus):
            self.assertEqual(choice.default_reason, "MISSING_CHOICE")
            self.assertEqual(choice.option_ids, menu.default_option_ids)

    def test_unknown_actor_is_rejected_without_widening_known_actor_choices(self):
        menus = build_menus(build_g5t_scenario(1))
        plan = plan_with_defaults(menus)
        plan["choices"].append({
            "actor": "Off-scene Wight",
            "option_ids": ["opt_000000000000000000000000"],
        })
        result = validate_commander_plan(plan, menus)
        self.assertEqual(result.status, "partially_defaulted")
        self.assertIn("UNKNOWN_ACTOR", result.rejected_reason_codes)
        self.assertTrue(all(choice.default_reason is None for choice in result.choices))

    def test_unissued_option_defaults_only_the_affected_actor(self):
        menus = build_menus(build_g5t_scenario(1))
        captain = actor_menu(menus, "Hobgoblin Captain")
        plan = plan_with_defaults(menus, {
            captain.actor.name: ["opt_000000000000000000000000"],
        })
        result = validate_commander_plan(plan, menus)
        captain_choice = next(
            item for item in result.choices if item.actor == captain.actor
        )
        self.assertEqual(captain_choice.default_reason, "UNISSUED_ID")
        self.assertEqual(captain_choice.option_ids, captain.default_option_ids)
        self.assertTrue(all(
            item.default_reason is None
            for item in result.choices if item.actor != captain.actor
        ))

    def test_unissued_multiattack_id_defaults_the_whole_actor(self):
        menus = build_menus(build_g5t_scenario(4))
        captain = actor_menu(menus, "Hobgoblin Captain")
        plan = plan_with_defaults(menus, {
            captain.actor.name: [
                captain.attack_slots[0][0].option_id,
                "opt_000000000000000000000000",
            ],
        })
        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor == captain.actor)
        self.assertEqual(choice.default_reason, "UNISSUED_ID")
        self.assertEqual(choice.option_ids, captain.default_option_ids)

    def test_duplicate_option_ids_default_with_bounded_duplicate_reason(self):
        menus = build_menus(build_g5t_scenario(1))
        captain = actor_menu(menus, "Hobgoblin Captain")
        plan = plan_with_defaults(menus, {
            captain.actor.name: [captain.default_option_ids[0]] * 2,
        })
        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor == captain.actor)
        self.assertEqual(choice.default_reason, "DUPLICATE_ID")
        self.assertEqual(choice.option_ids, captain.default_option_ids)

    def test_duplicate_actor_rows_default_that_actor_once(self):
        menus = build_menus(build_g5t_scenario(1))
        captain = actor_menu(menus, "Hobgoblin Captain")
        plan = plan_with_defaults(menus)
        plan["choices"].extend([
            {"actor": captain.actor.name, "option_ids": list(captain.default_option_ids)},
            {"actor": captain.actor.name, "option_ids": list(captain.default_option_ids)},
        ])
        result = validate_commander_plan(plan, menus)
        choice = next(item for item in result.choices if item.actor == captain.actor)
        self.assertEqual(choice.default_reason, "DUPLICATE_ID")
        self.assertEqual(sum(item.actor == captain.actor for item in result.choices), 1)

    def test_malformed_known_actor_row_gets_invalid_choice_not_missing_choice(self):
        menus = build_menus(build_g5t_scenario(1))
        captain = actor_menu(menus, "Hobgoblin Captain")
        result = validate_commander_plan({
            "choices": [{
                "actor": captain.actor.name,
                "option_ids": list(captain.default_option_ids),
                "target": "unissued target",
            }]
        }, menus)
        choice = next(item for item in result.choices if item.actor == captain.actor)
        self.assertEqual(choice.default_reason, "INVALID_CHOICE")

    def test_duplicate_json_keys_and_nonfinite_json_are_rejected(self):
        menus = build_menus(build_g5t_scenario(1))
        for payload in (
            '{"choices": [], "choices": []}',
            '{"choices": NaN}',
        ):
            with self.subTest(payload=payload):
                result = validate_commander_plan(payload, menus)
                self.assertTrue(all(
                    item.default_reason == "INVALID_CHOICE" for item in result.choices
                ))

    def test_unknown_top_level_fields_cannot_supply_mechanics(self):
        menus = build_menus(build_g5t_scenario(1))
        result = validate_commander_plan({
            "choices": [],
            "damage": 1000,
            "target": "Hidden NPC",
        }, menus)
        self.assertEqual(
            {item.default_reason for item in result.choices}, {"INVALID_CHOICE"}
        )
        self.assertIn("INVALID_CHOICE", result.rejected_reason_codes)

    def test_each_invalid_actor_choice_has_one_bounded_default_reason(self):
        menus = build_menus(build_g5t_scenario(4))
        plan = {"choices": [
            {"actor": menus.actor_menus[0].actor.name, "option_ids": [1]},
            {
                "actor": menus.actor_menus[1].actor.name,
                "option_ids": ["opt_000000000000000000000000"],
            },
        ]}
        result = validate_commander_plan(plan, menus)
        self.assertEqual(
            [choice.default_reason for choice in result.choices],
            ["INVALID_CHOICE", "UNISSUED_ID"]
            + ["MISSING_CHOICE"] * (len(menus.actor_menus) - 2),
        )
        self.assertTrue(all(
            choice.default_reason is None or choice.default_reason in TACTICAL_DEFAULT_REASON_CODES
            for choice in result.choices
        ))

    def test_plan_and_choice_results_are_immutable(self):
        menus = build_menus(build_g5t_scenario(1))
        result = validate_commander_plan(plan_with_defaults(menus), menus)
        with self.assertRaises(FrozenInstanceError):
            result.status = "rejected_all"
        with self.assertRaises(FrozenInstanceError):
            result.choices[0].kind = "flee"
        with self.assertRaises(TypeError):
            result.choices[0].option_ids[0] = "opt_mutation"

    def test_extra_context_cannot_add_options_or_identities(self):
        menus = build_menus(build_g5t_scenario(1))
        result = validate_commander_plan(
            plan_with_defaults(menus),
            menus,
            hidden_roster=["Off-scene Wight"],
            proposed_damage=999,
        )
        self.assertEqual(result.status, "accepted")
        self.assertNotIn("Off-scene Wight", {
            choice.actor.name for choice in result.choices
        })

    def test_invalid_choice_status_is_rejected_all_when_no_actor_choice_survives(self):
        menus = build_menus(build_g5t_scenario(1))
        captain = actor_menu(menus, "Hobgoblin Captain")
        goblin = actor_menu(menus, "Goblin Squad A")
        result = validate_commander_plan({
            "choices": [
                {
                    "actor": captain.actor.name,
                    "option_ids": ["opt_000000000000000000000000"],
                },
                {
                    "actor": goblin.actor.name,
                    "option_ids": ["opt_000000000000000000000001"],
                },
                {
                    "actor": actor_menu(menus, "Goblin Squad B").actor.name,
                    "option_ids": ["opt_000000000000000000000002"],
                },
            ]
        }, menus)
        self.assertEqual(result.status, "rejected_all")
        self.assertEqual(
            {choice.default_reason for choice in result.choices}, {"UNISSUED_ID"}
        )


class CombatTacticalOrchestrationTests(ProviderFreeTestCase):
    """Exercise the synchronous plan boundary with only an injected router."""

    def _execute(
        self,
        *,
        party_size=1,
        commander=True,
        plan_response=_DEFAULT_PLAN_RESPONSE,
        enemy_hp_overrides=None,
    ):
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        scratch = tempfile.mkdtemp(prefix="tactical-orchestration-", dir=SCRATCH_ROOT)
        try:
            scenario = build_g5t_scenario(party_size)
            encounter = scenario["encounter"]
            encounter_id = encounter["encounterId"]
            for name, hit_points in (enemy_hp_overrides or {}).items():
                enemy(scenario, name)["currentHitPoints"] = hit_points
            encounter.update({
                "combat_round": 1,
                "roundStartsWith": "dmGroup",
                "openingEnemyBatchPending": True,
                "initiativeMode": "two_group_phase1",
                "initiativeRolls": {"dmGroup": 11, "pcGroup": 17},
                "initiativeWinner": "pcGroup",
                "awaitingPcGroupRoll": False,
            })
            for creature in encounter["creatures"]:
                if creature.get("type") == "player":
                    creature["currentHitPoints"] = 200
                    creature["maxHitPoints"] = 200
                    state = scenario["pc_states"][creature["name"]]
                    state["hitPoints"] = 200
                    state["maxHitPoints"] = 200
            if not commander:
                captain = next(
                    row for row in encounter["creatures"]
                    if row.get("name") == "Hobgoblin Captain"
                )
                captain["tactics"] = "rule"

            class PathManager:
                def get_character_path(self, name):
                    return str(
                        Path(scratch) / "characters"
                        / ("_".join(name.lower().split()) + ".json")
                    )

                def get_encounter_path_from_id(self, resolved_id):
                    return str(
                        Path(scratch) / "encounters"
                        / ("encounter_" + resolved_id + ".json")
                    )

            path_manager = PathManager()
            manager = MultiPCCombatManager()
            manager.current_round = 1
            manager.pc_phase_complete = True
            queue_by_name = {}
            for creature in encounter["creatures"]:
                name = creature["name"]
                kind = {
                    "player": CombatantType.PC,
                    "enemy": CombatantType.ENEMY,
                    "npc": CombatantType.NPC,
                }[creature["type"]]
                queue_by_name[name] = Combatant(
                    name=name,
                    type=kind,
                    initiative=creature["initiative"],
                    hp=creature["currentHitPoints"],
                    max_hp=creature["maxHitPoints"],
                    ac=creature["armorClass"],
                    status=creature.get("status", "alive"),
                )
                if kind == CombatantType.PC:
                    state = scenario["pc_states"][name]
                    manager._state.pc_states[name] = PCCombatState(
                        character_name=name,
                        status=PCStatus.READY,
                        current_hp=state["hitPoints"],
                        max_hp=state["maxHitPoints"],
                        ac=state["armorClass"],
                    )
            manager._turns.turn_queue = [
                queue_by_name[identity["name"]]
                for identity in scenario["turn_order"]
            ]

            scenario_for_menus = dict(scenario)
            scenario_for_menus.update({
                "batch_id": _batch_id(encounter_id, 1),
                "batch_kind": "enemy_phase",
                "fixture_seed": None,
                "turn_order": [
                    {"name": item.name, "kind": item.type.value}
                    for item in manager._turns.turn_queue
                ],
                "enemy_turn_window": [
                    {"name": name}
                    for name in manager.get_remaining_enemies_for_round()
                ],
            })
            menus = build_menus(scenario_for_menus) if commander else None

            characters = {
                path_manager.get_character_path(name): copy.deepcopy(state)
                for name, state in scenario["pc_states"].items()
            }
            encounter_path = path_manager.get_encounter_path_from_id(encounter_id)
            persisted_encounter = copy.deepcopy(encounter)
            persisted = {}
            writes = []
            llm_calls = []
            resolver_calls = []
            observer_requests = []
            published = []
            published_ids = []
            planned = {"ledger": None}

            def read_json(path):
                if path == encounter_path:
                    return copy.deepcopy(persisted_encounter)
                value = characters.get(path)
                return copy.deepcopy(value) if value is not None else None

            def write_json(path, payload):
                nonlocal persisted_encounter
                copied = copy.deepcopy(payload)
                writes.append((Path(path).name, copied))
                persisted[Path(path).name] = copied
                if path == encounter_path:
                    persisted_encounter = copied
                else:
                    characters[path] = copied
                return True

            def plan(*args, **kwargs):
                resolver_calls.append(dict(kwargs))
                result = plan_enemy_batch(*args, **kwargs)
                planned["ledger"] = result
                return result

            def llm_call(task, messages, **kwargs):
                is_plan = "max_tokens" in kwargs
                llm_calls.append({
                    "task": task,
                    "kind": "plan" if is_plan else "narration",
                    "kwargs": dict(kwargs),
                    "messages": messages,
                })
                if is_plan:
                    if isinstance(plan_response, BaseException):
                        raise plan_response
                    if plan_response is _DEFAULT_PLAN_RESPONSE:
                        return json.dumps(plan_with_defaults(menus))
                    if callable(plan_response):
                        return json.dumps(plan_response(menus))
                    return plan_response
                ledger = planned["ledger"]
                if ledger is None:
                    raise AssertionError("narration should not run without a resolver ledger")
                return build_enemy_batch_template_narration(ledger)

            def observer_factory(**kwargs):
                observer_requests.append(dict(kwargs))
                return lambda *_args, **_observer_kwargs: None

            transition_dependencies = RoundTransitionDependencies(
                apply_opening_batch_marker=apply_opening_batch_marker,
                sync_available=True,
                save_json=lambda _path, _payload: True,
                compress_old_rounds=lambda history, _round, keep_recent_rounds=1: history,
                log_debug=lambda *_args, **_kwargs: None,
                log_info=lambda *_args, **_kwargs: None,
                log_warning=lambda *_args, **_kwargs: None,
                bind_history=lambda _history: None,
            )

            def publish_narration(text, *, applied_id):
                published.append(text)
                published_ids.append(applied_id)

            dependencies = EnemyBatchOrchestrationDependencies(
                read_json=read_json,
                write_json=write_json,
                round_transition_dependencies=transition_dependencies,
                llm_call=llm_call,
                receipt_observer_factory=observer_factory,
                publish_narration=publish_narration,
                usage_tracking_available=False,
                combat_main_model="provider-free-test-model",
                plan=plan,
                validate_character=lambda _name, _payload: True,
            )
            history = [
                {"role": "system", "content": "authoritative combat context"},
                {
                    "role": "user",
                    "content": "Enemies turn.",
                    "turn_id": "11111111-2222-4333-8444-555555555555",
                },
            ]
            result = try_execute_deterministic_enemy_batch(
                encounter,
                history,
                "Enemies turn.",
                initial_conversation_length=len(history),
                encounter_id=encounter_id,
                conversation_history_file=str(
                    Path(scratch) / "combat_conversation_history.json"
                ),
                path_manager=path_manager,
                multi_pc_manager=manager,
                monster_definitions=scenario["monster_definitions"],
                scene_context={
                    "location": {
                        "name": "Training Pit",
                        "tacticalFeatures": scenario["tactical_features"],
                    },
                    "round": 1,
                },
                dependencies=dependencies,
                party_tracker_data={
                    "partyMembers": list(scenario["pc_states"]),
                    "partyNPCs": [],
                },
            )
            return {
                "result": result,
                "llm_calls": llm_calls,
                "resolver_calls": resolver_calls,
                "observer_requests": observer_requests,
                "published": published,
                "published_ids": published_ids,
                "writes": writes,
                "persisted": persisted,
                "menus": menus,
                "scenario": scenario,
                "manager": manager,
            }
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_commander_batch_uses_one_plan_and_one_narration_request(self):
        decision_calls = []
        observations = []
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch("utils.combat_latency_trace.trace_enabled", return_value=True), \
                mock.patch(
                    "utils.combat_latency_trace.trace_enemy_batch_decision",
                    side_effect=lambda *args, **kwargs: decision_calls.append((args, kwargs)) or True,
                ), \
                mock.patch(
                    "utils.combat_latency_trace.trace_combat_observation",
                    side_effect=lambda observation, **fields: observations.append(
                        {"observation": observation, **fields}
                    ) or True,
                ):
            run = self._execute()

        self.assertIsInstance(run["result"], EnemyBatchExecution)
        self.assertEqual([call["task"] for call in run["llm_calls"]], [
            "combat_main", "combat_main",
        ])
        self.assertEqual([call["kind"] for call in run["llm_calls"]], ["plan", "narration"])
        self.assertEqual(run["llm_calls"][0]["kwargs"]["json_output"], False)
        self.assertEqual(run["llm_calls"][0]["kwargs"]["max_tokens"], 1200)
        narration_payload = json.loads(run["llm_calls"][1]["messages"][1]["content"])
        self.assertEqual(
            len(narration_payload["tactical_plan_intent"]),
            len(run["menus"].actor_menus),
        )
        self.assertTrue(all(
            row["intent"] == "attack"
            for row in narration_payload["tactical_plan_intent"]
        ))
        self.assertEqual(len(run["resolver_calls"]), 1)
        self.assertEqual(len(decision_calls), 1)
        self.assertEqual(decision_calls[0][1]["decision_source"], "llm_tactical")
        plan_events = [
            event for event in observations
            if event["observation"] == "combat_tactical_plan_result"
        ]
        self.assertEqual(len(plan_events), 1)
        self.assertEqual(plan_events[0]["tactical_plan_outcome"], "accepted")
        plan_observers = [
            request for request in run["observer_requests"]
            if request["legacy_context"].get("purpose") == "combat_enemy_batch_commander_plan"
        ]
        self.assertEqual(len(plan_observers), 1)
        self.assertEqual(plan_observers[0]["trace_site"], "combat_main")

    def test_rejected_plan_diagnostic_is_bounded_server_logging(self):
        response = json.dumps({"choices": [], "unexpected": "x" * 2000})
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(enemy_batch_orchestrator, "debug") as debug_log:
            run = self._execute(plan_response=response)

        self.assertIsInstance(run["result"], EnemyBatchExecution)
        debug_log.assert_called_once()
        message = debug_log.call_args.args[0]
        self.assertIn("COMMANDER_PLAN_REJECTED", message)
        self.assertIn("status=rejected_all", message)
        self.assertIn("default_reasons=INVALID_CHOICE", message)
        self.assertLessEqual(len(message.split(" plan=", 1)[1]), 1000)
        self.assertEqual(debug_log.call_args.kwargs["category"], "combat_events")

    def test_rule_only_batch_skips_plan_and_malformed_plan_keeps_rule_ledger(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            rule_only = self._execute(commander=False)
            malformed = self._execute(plan_response="attack squad")

        self.assertEqual([call["kind"] for call in rule_only["llm_calls"]], ["narration"])
        self.assertEqual(len(rule_only["resolver_calls"]), 1)
        self.assertEqual([call["kind"] for call in malformed["llm_calls"]], ["plan", "narration"])
        self.assertEqual(len(malformed["resolver_calls"]), 1)
        self.assertEqual(
            [(entry.actor.name, entry.target.name) for entry in rule_only["result"].ledger.entries],
            [(entry.actor.name, entry.target.name) for entry in malformed["result"].ledger.entries],
        )

    def test_terminal_plan_error_propagates_without_narration(self):
        class GameLLMTerminalError(RuntimeError):
            pass

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            with self.assertRaises(GameLLMTerminalError):
                self._execute(plan_response=GameLLMTerminalError("terminal router failure"))

    def test_disabled_brain_preserves_rule_outputs_and_disabled_resolver_is_inert(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            malformed = self._execute(plan_response="attack squad")

        brain_off_observations = []
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", False), \
                mock.patch.object(
                    enemy_batch_orchestrator,
                    "build_tactical_menus",
                    wraps=enemy_batch_orchestrator.build_tactical_menus,
                ) as menu_builder, \
                mock.patch(
                    "utils.combat_latency_trace.trace_combat_observation",
                    side_effect=lambda observation, **fields: brain_off_observations.append(
                        {"observation": observation, **fields}
                    ) or True,
                ):
            brain_off = self._execute()
            menu_builder.assert_not_called()

        self.assertEqual([call["kind"] for call in brain_off["llm_calls"]], ["narration"])
        self.assertEqual(malformed["result"].ledger, brain_off["result"].ledger)

        def without_commit_timestamps(value):
            if isinstance(value, dict):
                return {
                    key: without_commit_timestamps(item)
                    for key, item in value.items()
                    if key != "commit_timestamp"
                }
            if isinstance(value, list):
                return [without_commit_timestamps(item) for item in value]
            if isinstance(value, tuple):
                return tuple(without_commit_timestamps(item) for item in value)
            return value

        self.assertEqual(
            (
                malformed["result"].application.conversation_history,
                without_commit_timestamps(
                    malformed["result"].application.encounter_projection
                ),
                malformed["result"].application.changed_pc_names,
                malformed["result"].application.write_count,
                malformed["result"].application.exit_completed,
            ),
            (
                brain_off["result"].application.conversation_history,
                without_commit_timestamps(
                    brain_off["result"].application.encounter_projection
                ),
                brain_off["result"].application.changed_pc_names,
                brain_off["result"].application.write_count,
                brain_off["result"].application.exit_completed,
            ),
        )
        self.assertEqual(
            without_commit_timestamps(malformed["writes"]),
            without_commit_timestamps(brain_off["writes"]),
        )
        self.assertFalse(any(
            event["observation"] == "combat_tactical_plan_result"
            for event in brain_off_observations
        ))

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", False), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            resolver_off = self._execute()
        self.assertIsNone(resolver_off["result"])
        self.assertEqual(resolver_off["llm_calls"], [])
        self.assertEqual(resolver_off["resolver_calls"], [])
        self.assertEqual(resolver_off["writes"], [])

    def test_validated_attack_targets_drive_only_the_selected_actors(self):
        target_names = ("Vitreol", "Acheron")

        def commander_plan(menus):
            captain = actor_menu(menus, "Hobgoblin Captain")
            selected_ids = []
            for slot, target_name in zip(captain.attack_slots, target_names):
                selected = next(
                    item for item in slot
                    if item.target is not None and item.target.name == target_name
                )
                selected_ids.append(selected.option_id)
            return plan_with_defaults(menus, {captain.actor.name: selected_ids})

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            selected = self._execute(party_size=4, plan_response=commander_plan)
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", False):
            rule_tier = self._execute(party_size=4)

        self.assertEqual(len(selected["resolver_calls"]), 2)
        self.assertNotIn("attack_target_overrides", selected["resolver_calls"][0])
        self.assertIn("attack_target_overrides", selected["resolver_calls"][1])
        captain_targets = [
            entry.target.name for entry in selected["result"].ledger.entries
            if entry.actor.name == "Hobgoblin Captain"
        ]
        self.assertEqual(captain_targets, list(target_names))
        selected_goblin_entries = [
            entry for entry in selected["result"].ledger.entries
            if entry.actor.name.startswith("Goblin Squad")
        ]
        rule_goblin_entries = [
            entry for entry in rule_tier["result"].ledger.entries
            if entry.actor.name.startswith("Goblin Squad")
        ]
        self.assertEqual(
            [
                (entry.actor.name, entry.target.name, entry.action_name, entry.d20,
                 entry.hit, entry.damage_total)
                for entry in selected_goblin_entries
            ],
            [
                (entry.actor.name, entry.target.name, entry.action_name, entry.d20,
                 entry.hit, entry.damage_total)
                for entry in rule_goblin_entries
            ],
        )

    def test_flee_is_applied_in_final_projection_and_uses_two_plus_n_writes(self):
        def captain_flees(menus):
            captain = actor_menu(menus, "Hobgoblin Captain")
            flee = option(captain, "flee")
            withdrawal = next(
                item for item in menus.commander_options
                if item.kind == "withdrawal_order"
            )
            plan = plan_with_defaults(menus, {captain.actor.name: [flee.option_id]})
            plan["orders"] = [withdrawal.option_id]
            return plan

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            run = self._execute(party_size=4, plan_response=captain_flees)

        result = run["result"]
        self.assertIsInstance(result, EnemyBatchExecution)
        captain = next(
            row for row in result.encounter_data["creatures"]
            if row.get("name") == "Hobgoblin Captain"
        )
        self.assertEqual(captain["status"], "defeated")
        self.assertEqual(captain["defeatReason"], "fled")
        self.assertNotIn("Hobgoblin Captain", run["manager"].get_remaining_enemies_for_round())
        self.assertFalse(any(
            entry.actor.name == "Hobgoblin Captain" for entry in result.ledger.entries
        ))
        self.assertEqual(
            result.application.write_count,
            2 + len(result.application.changed_pc_names),
        )
        self.assertEqual(len(run["writes"]), result.application.write_count)
        self.assertEqual(len(run["resolver_calls"]), 2)
        narration_payload = json.loads(next(
            call["messages"][1]["content"] for call in run["llm_calls"]
            if call["kind"] == "narration"
        ))
        self.assertIn(
            {"name": "Hobgoblin Captain", "reason": "fled"},
            narration_payload["authoritative_ledger"]["departures"],
        )
        captain_intent = next(
            row for row in narration_payload["tactical_plan_intent"]
            if row["actor"] == "Hobgoblin Captain"
        )
        self.assertEqual(captain_intent["intent"], "flee")
        self.assertEqual(captain_intent["defeat_reason"], "fled")

        next_batch = plan_enemy_batch(
            result.encounter_data,
            run["scenario"]["pc_states"],
            run["scenario"]["monster_definitions"],
            run["scenario"]["turn_order"],
            "g5t-commander-next-batch",
            enemy_turn_window=run["scenario"]["enemy_turn_window"],
        )
        self.assertIsInstance(next_batch, EnemyResolutionDecline)
        self.assertEqual(next_batch.reason_code, "leader_down")

    def test_side_surrender_is_atomic_and_enters_existing_combat_exit_gate(self):
        def side_surrenders(menus):
            side_option = next(
                item for item in menus.commander_options
                if item.kind == "commander_side_surrender"
            )
            plan = plan_with_defaults(menus)
            plan["orders"] = [side_option.option_id]
            return plan

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            run = self._execute(
                party_size=1,
                plan_response=side_surrenders,
                enemy_hp_overrides={"Goblin Squad A": 1},
            )

        result = run["result"]
        self.assertIsInstance(result, EnemyBatchExecution)
        self.assertEqual(result.ledger.entries, ())
        self.assertEqual(
            {item.reason for item in result.ledger.departures}, {"surrendered"}
        )
        enemies = [
            row for row in result.encounter_data["creatures"]
            if row.get("type") == "enemy"
        ]
        self.assertTrue(all(row["status"] == "defeated" for row in enemies))
        self.assertTrue(all(row["defeatReason"] == "surrendered" for row in enemies))
        self.assertEqual(run["manager"].get_remaining_enemies_for_round(), [])
        self.assertTrue(check_all_monsters_defeated(result.encounter_data))
        self.assertEqual(result.application.write_count, 2)
        self.assertEqual(len(run["writes"]), 2)
        self.assertEqual(len(run["resolver_calls"]), 1)

    def test_individual_near_death_surrender_persists_and_leaves_batch(self):
        def one_surrenders(menus):
            surrender = option(actor_menu(menus, "Goblin Squad A"), "surrender")
            return plan_with_defaults(
                menus, {"Goblin Squad A": [surrender.option_id]}
            )

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            run = self._execute(
                party_size=1,
                plan_response=one_surrenders,
                enemy_hp_overrides={"Goblin Squad A": 1},
            )

        result = run["result"]
        self.assertIsInstance(result, EnemyBatchExecution)
        goblin = next(
            row for row in result.encounter_data["creatures"]
            if row.get("name") == "Goblin Squad A"
        )
        self.assertEqual(goblin["status"], "defeated")
        self.assertEqual(goblin["defeatReason"], "surrendered")
        self.assertNotIn("Goblin Squad A", run["manager"].get_remaining_enemies_for_round())
        self.assertNotIn(
            "Goblin Squad A", [entry.actor.name for entry in result.ledger.entries]
        )
        self.assertEqual(
            [(item.enemy.name, item.reason) for item in result.ledger.departures],
            [("Goblin Squad A", "surrendered")],
        )
        self.assertEqual(
            result.application.write_count,
            2 + len(result.application.changed_pc_names),
        )

    def test_all_individual_flights_trigger_existing_combat_exit_gate(self):
        scenario = build_g5t_scenario(1)
        bloodied_hp = {
            row["name"]: max(1, row["maxHitPoints"] // 2)
            for row in scenario["encounter"]["creatures"]
            if row["type"] == "enemy"
        }

        def all_flee(menus):
            choices = {
                menu.actor.name: [option(menu, "flee").option_id]
                for menu in menus.actor_menus
            }
            return plan_with_defaults(menus, choices)

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            run = self._execute(
                party_size=1,
                plan_response=all_flee,
                enemy_hp_overrides=bloodied_hp,
            )

        result = run["result"]
        self.assertIsInstance(result, EnemyBatchExecution)
        self.assertEqual(result.ledger.entries, ())
        self.assertEqual(
            {item.reason for item in result.ledger.departures}, {"fled"}
        )
        self.assertTrue(check_all_monsters_defeated(result.encounter_data))
        self.assertEqual(result.application.write_count, 2)

        xp_calls = []
        queued_names = []
        final_updates = {}

        def queue_xp_update(updates, name, changes=None, ops=None):
            queued_names.append(name)
            updates.setdefault(name, []).append({"changes": changes, "ops": ops})

        auto_exit = process_combat_action_batch(
            [{"action": "exit"}],
            result.encounter_data,
            final_updates,
            encounter_id=result.ledger.encounter_id,
            conversation_history=[],
            conversation_history_file="tmp/router-rollout/g5t/auto-exit-history.json",
            multi_pc_manager=None,
            party_tracker_data={},
            is_combat_ending=False,
            dependencies=CombatActionDependencies(
                queue_character_update=queue_xp_update,
                update_encounter=lambda *_args, **_kwargs: None,
                normalize_encounter_status=lambda value: value,
                sync_non_pc_queue_state=lambda *_args: False,
                log_info=lambda *_args, **_kwargs: None,
                log_debug=lambda *_args, **_kwargs: None,
                log_error=lambda *_args, **_kwargs: None,
                log_warning=lambda *_args, **_kwargs: None,
                calculate_xp=lambda: (xp_calls.append("called") or ("100 XP", 100)),
                save_json=lambda *_args, **_kwargs: True,
                active_character_update_available=False,
                emit_combat_event=lambda *_args, **_kwargs: None,
                get_current_actor=lambda *_args: None,
                advance_turn=lambda *_args: None,
                get_pc_state=lambda *_args: None,
                pc_acted_status=None,
                npc_combatant_type=None,
                pc_combatant_type=None,
                check_all_monsters_defeated=check_all_monsters_defeated,
            ),
        )

        self.assertTrue(auto_exit.is_combat_ending)
        self.assertEqual(xp_calls, ["called"])
        self.assertEqual(queued_names, ["Acheron"])
        combat_manager_source = Path("core/combat/combat_manager.py").read_text(
            encoding="utf-8"
        )
        deterministic_exit_branch = combat_manager_source.split(
            "if isinstance(deterministic_batch, EnemyBatchExecution):", 1
        )[1].split("retry_result = run_combat_provider_retry_stage", 1)[0]
        orchestrator_source = Path(
            "core/combat/enemy_batch_orchestrator.py"
        ).read_text(encoding="utf-8")
        # The 4c exit path is delegated so the combat owner retains one action-batch call site.
        self.assertIn("complete_deterministic_enemy_batch_exit(", deterministic_exit_branch)
        self.assertIn("check_all_monsters_defeated(encounter_data)", orchestrator_source)
        self.assertIn("exit_batch = process_action_batch(", orchestrator_source)

    def test_rule_tier_near_death_still_uses_4b_fallback(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True):
            run = self._execute(
                commander=False,
                enemy_hp_overrides={"Goblin Squad A": 1},
            )

        self.assertIsInstance(run["result"], EnemyBatchFallback)
        self.assertEqual(run["result"].reason_code, "near_death_enemy")
        self.assertEqual(run["llm_calls"], [])
        self.assertEqual(run["writes"], [])


if __name__ == "__main__":
    unittest.main()
