# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for encounter-scoped tactical cover and effective AC."""

from __future__ import annotations

import copy
from dataclasses import replace
from unittest import mock

from core.combat.cover import (
    cover_label,
    effective_ac,
    is_authorized_ranged_action,
)
from core.combat.enemy_batch_apply import (
    _PcFinalState,
    _build_encounter_projection,
    apply_enemy_batch,
)
from core.combat.enemy_batch_orchestrator import _apply_tactical_choices_to_ledger
from core.combat.enemy_narration import NarrationResult
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyCoverUpdate,
    EnemyDeparture,
    EnemyResolutionLedger,
    plan_enemy_batch,
)
from core.combat.multi_pc.manager import MultiPCCombatManager
from core.combat.multi_pc.state import PCCombatState, PCStatus
from core.combat.prompts import (
    CombatContextDependencies,
    CombatContextInputs,
    assemble_combat_context,
)
from core.combat.tactical_brain import (
    build_tactical_menus,
    validate_commander_plan,
)
from scripts.combat_tactical_test_support import (
    ProviderFreeTestCase,
    actor_menu,
    build_g5t_scenario,
    enemy,
    option,
    plan_with_defaults,
)


def _feature(
    feature_id: str = "PIT_COVER",
    cover_type: str = "half",
    usable_by: tuple[str, ...] = ("enemy",),
) -> dict:
    return {
        "featureId": feature_id,
        "name": "Shield racks",
        "kind": "cover",
        "coverType": cover_type,
        "usableBy": list(usable_by),
    }


def _scenario_plan(scenario: dict, *, active: bool, seed: str = "cover-test"):
    encounter_id = scenario["encounter"]["encounterId"]
    return plan_enemy_batch(
        encounter=scenario["encounter"],
        pc_states=scenario["pc_states"],
        monster_definitions=scenario["monster_definitions"],
        turn_order=scenario["turn_order"],
        batch_id=scenario["batch_id"],
        batch_kind=scenario["batch_kind"],
        fixture_seed=seed,
        enemy_turn_window=scenario.get("enemy_turn_window"),
        active_encounter_id=encounter_id if active else "completed-encounter",
        combat_in_progress=active,
        tactical_features=scenario.get("tactical_features"),
    )


def _scenario_menus(scenario: dict):
    encounter_id = scenario["encounter"]["encounterId"]
    return build_tactical_menus(
        encounter=scenario["encounter"],
        pc_states=scenario["pc_states"],
        monster_definitions=scenario["monster_definitions"],
        turn_order=scenario["turn_order"],
        batch_id=scenario["batch_id"],
        batch_kind=scenario["batch_kind"],
        fixture_seed=scenario["fixture_seed"],
        enemy_turn_window=scenario.get("enemy_turn_window"),
        tactical_features=scenario.get("tactical_features"),
        active_encounter_id=encounter_id,
        combat_in_progress=True,
    )


class EffectiveArmorClassTests(ProviderFreeTestCase):
    def test_cover_bonus_is_two_or_five_and_never_stacks(self):
        half = _feature("HALF", "half")
        three_quarters = _feature("THREE_QUARTERS", "three_quarters")
        self.assertEqual(effective_ac(
            14, "half", cover_feature_id="HALF", encounter_id="e1",
            active_encounter_id="e1", combat_in_progress=True,
            tactical_features=[half], combatant_kind="enemy",
        ), 16)
        self.assertEqual(effective_ac(
            14, "three_quarters", cover_feature_id="THREE_QUARTERS",
            encounter_id="e1", active_encounter_id="e1",
            combat_in_progress=True, tactical_features=[three_quarters],
            combatant_kind="enemy",
        ), 19)
        self.assertEqual(effective_ac(
            14, "half", cover_feature_id="HALF", encounter_id="e1",
            active_encounter_id="e1", combat_in_progress=True,
            tactical_features=[half, half], combatant_kind="enemy",
        ), 14)
        self.assertEqual(cover_label("half"), "half cover")
        self.assertEqual(cover_label("three_quarters"), "three-quarters cover")
        self.assertIsNone(cover_label("full"))

    def test_stale_malformed_wrong_kind_and_inactive_references_are_inert(self):
        valid = _feature()
        cases = (
            {"cover_feature_id": "MISSING", "cover_type": "half",
             "active_encounter_id": "e1", "combat_in_progress": True,
             "tactical_features": [valid], "combatant_kind": "enemy"},
            {"cover_feature_id": "PIT_COVER", "cover_type": "three_quarters",
             "active_encounter_id": "e1", "combat_in_progress": True,
             "tactical_features": [valid], "combatant_kind": "enemy"},
            {"cover_feature_id": "PIT_COVER", "cover_type": "half",
             "active_encounter_id": "old", "combat_in_progress": True,
             "tactical_features": [valid], "combatant_kind": "enemy"},
            {"cover_feature_id": "PIT_COVER", "cover_type": "half",
             "active_encounter_id": "e1", "combat_in_progress": False,
             "tactical_features": [valid], "combatant_kind": "enemy"},
            {"cover_feature_id": "PIT_COVER", "cover_type": "half",
             "active_encounter_id": "e1", "combat_in_progress": True,
             "tactical_features": [valid], "combatant_kind": "player"},
            {"cover_feature_id": "PIT_COVER", "cover_type": "half",
             "active_encounter_id": "e1", "combat_in_progress": True,
             "tactical_features": [dict(valid, usableBy=[])],
             "combatant_kind": "enemy"},
            {"cover_feature_id": "PIT_COVER", "cover_type": "half",
             "active_encounter_id": "e1", "combat_in_progress": True,
             "tactical_features": "malformed", "combatant_kind": "enemy"},
        )
        for values in cases:
            with self.subTest(values=values):
                self.assertEqual(effective_ac(
                    14,
                    values.pop("cover_type"),
                    encounter_id="e1",
                    **values,
                ), 14)

    def test_explicit_attack_metadata_precedes_weapon_name(self):
        for weapon in (
            "shortbow", "longbow", "light crossbow", "heavy crossbow",
            "hand crossbow", "sling", "dart",
        ):
            with self.subTest(weapon=weapon):
                self.assertTrue(is_authorized_ranged_action(weapon))
        self.assertTrue(is_authorized_ranged_action(
            "Scimitar", {"attackType": "ranged"}
        ))
        self.assertFalse(is_authorized_ranged_action(
            "Shortbow", {"attackType": "melee"}
        ))
        self.assertFalse(is_authorized_ranged_action("javelin"))
        self.assertTrue(is_authorized_ranged_action(
            "Javelin", {
                "attackType": "ranged",
                "range": {"normal": 30, "long": 120},
            }
        ))
        self.assertFalse(is_authorized_ranged_action("Longbow or dagger"))
        self.assertFalse(is_authorized_ranged_action("unknown weapon"))

    def test_resolver_uses_cover_at_the_hit_boundary_only_for_active_encounter(self):
        scenario = build_g5t_scenario(1)
        pc = next(
            row for row in scenario["encounter"]["creatures"]
            if row["type"] == "player"
        )
        pc.update(coverType="half", coverFeatureId="PC_SHIELD_RACKS")
        scenario["tactical_features"] = [
            _feature("PC_SHIELD_RACKS", "half", ("player",))
        ]
        scenario["enemy_turn_window"] = [
            {"name": "Goblin Squad A", "kind": "enemy"}
        ]

        active = None
        inactive = None
        for index in range(1000):
            seed = "cover-boundary-%d" % index
            candidate = _scenario_plan(scenario, active=True, seed=seed)
            self.assertNotIsInstance(candidate, type(None))
            entry = next(
                item for item in candidate.entries
                if item.actor.name == "Goblin Squad A"
            )
            if entry.d20 == 10:
                active = candidate
                inactive = _scenario_plan(scenario, active=False, seed=seed)
                break

        self.assertIsNotNone(active)
        self.assertIsNotNone(inactive)
        active_entry = next(
            item for item in active.entries if item.actor.name == "Goblin Squad A"
        )
        inactive_entry = next(
            item for item in inactive.entries if item.actor.name == "Goblin Squad A"
        )
        self.assertEqual(active_entry.armor_class, 16)
        self.assertEqual(inactive_entry.armor_class, 14)
        self.assertEqual(active_entry.d20, inactive_entry.d20)
        self.assertFalse(active_entry.hit)
        self.assertTrue(inactive_entry.hit)


class TacticalCoverProjectionTests(ProviderFreeTestCase):
    def test_ranged_attack_plus_cover_persists_and_next_pc_attack_uses_bonus(self):
        for cover_type, expected_ac, label in (
            ("half", 17, "half cover"),
            ("three_quarters", 20, "three-quarters cover"),
        ):
            with self.subTest(cover_type=cover_type):
                scenario = build_g5t_scenario(1)
                feature = _feature("RANGED_COMBO_" + cover_type, cover_type)
                scenario["tactical_features"] = [feature]
                actor = enemy(scenario, "Goblin Squad A")
                menus = _scenario_menus(scenario)
                menu = actor_menu(menus, actor["name"])
                attack = menu.attack_slots[0][0]
                cover = option(
                    menu, "take_cover", feature_id=feature["featureId"]
                )
                plan = validate_commander_plan(
                    plan_with_defaults(menus, {
                        actor["name"]: [attack.option_id, cover.option_id],
                    }),
                    menus,
                )
                choice = next(item for item in plan.choices if item.actor == menu.actor)
                self.assertIsNone(choice.default_reason)
                ledger = _scenario_plan(scenario, active=True)
                projected_ledger = _apply_tactical_choices_to_ledger(
                    ledger, plan, menus
                )
                self.assertIsNotNone(projected_ledger)
                self.assertTrue(any(
                    entry.actor == menu.actor for entry in projected_ledger.entries
                ))
                projection = _build_encounter_projection(
                    projected_ledger, scenario["encounter"], []
                )
                projected_actor = enemy({"encounter": projection}, actor["name"])
                self.assertEqual(projected_actor["coverFeatureId"], feature["featureId"])
                self.assertEqual(projected_actor["coverType"], cover_type)

                pc = scenario["pc_states"]["Acheron"]
                manager = MultiPCCombatManager()
                manager._state.pc_states["Acheron"] = PCCombatState(
                    character_name="Acheron",
                    current_hp=pc["hitPoints"],
                    max_hp=pc["maxHitPoints"],
                    ac=pc["armorClass"],
                    status=PCStatus.READY,
                )
                manager._state.current_pc_name = "Acheron"
                manager.initialize_turn_queue(projection)
                with mock.patch(
                    "core.combat.multi_pc.manager.COMBAT_FAST_DETERMINISTIC_NARRATION",
                    True,
                ), mock.patch("core.combat.multi_pc.manager.trace_decision"):
                    response = manager.handle_combat_command(
                        "/att Goblin Squad A 16",
                        projection,
                        actor_name="Acheron",
                        active_encounter_id=projection["encounterId"],
                        tactical_features=[feature],
                    )
                self.assertIn("vs AC %d (%s)" % (expected_ac, label), response[0])

    def test_legal_cover_choice_replaces_or_retains_selected_feature(self):
        for selected_type in ("same", "replacement"):
            with self.subTest(selected_type=selected_type):
                scenario = build_g5t_scenario(1)
                actor = enemy(scenario, "Goblin Squad A")
                existing = scenario["tactical_features"][0]
                actor.update(
                    coverFeatureId=existing["featureId"],
                    coverType=existing["coverType"],
                )
                replacement = _feature("PIT_COVER_ALT", "three_quarters")
                scenario["tactical_features"].append(replacement)
                menus = _scenario_menus(scenario)
                selected = existing if selected_type == "same" else replacement
                selected_option = option(
                    actor_menu(menus, actor["name"]),
                    "take_cover",
                    feature_id=selected["featureId"],
                )
                plan = validate_commander_plan(
                    plan_with_defaults(menus, {
                        actor["name"]: [selected_option.option_id]
                    }),
                    menus,
                )
                ledger = _scenario_plan(scenario, active=True)
                projected_ledger = _apply_tactical_choices_to_ledger(
                    ledger, plan, menus
                )
                projection = _build_encounter_projection(
                    projected_ledger, scenario["encounter"], []
                )
                projected_actor = enemy(
                    {"encounter": projection}, actor["name"]
                )
                self.assertEqual(
                    projected_actor["coverFeatureId"], selected["featureId"]
                )
                self.assertEqual(projected_actor["coverType"], selected["coverType"])
                self.assertFalse(any(
                    entry.actor == CombatantIdentity(actor["name"], "enemy")
                    for entry in projected_ledger.entries
                ))

    def test_hold_and_ranged_attack_retain_cover_while_melee_clears_it(self):
        for behavior in ("hold", "ranged", "melee"):
            with self.subTest(behavior=behavior):
                scenario = build_g5t_scenario(1)
                actor = enemy(scenario, "Goblin Squad A")
                feature = scenario["tactical_features"][0]
                actor.update(
                    coverFeatureId=feature["featureId"],
                    coverType=feature["coverType"],
                )
                if behavior == "hold":
                    menus = _scenario_menus(scenario)
                    hold = option(actor_menu(menus, actor["name"]), "hold")
                    plan = validate_commander_plan(
                        plan_with_defaults(menus, {
                            actor["name"]: [hold.option_id]
                        }),
                        menus,
                    )
                    ledger = _scenario_plan(scenario, active=True)
                    projected_ledger = _apply_tactical_choices_to_ledger(
                        ledger, plan, menus
                    )
                else:
                    ledger = _scenario_plan(scenario, active=True)
                    if behavior in ("ranged", "melee"):
                        ledger = replace(
                            ledger,
                            entries=tuple(
                                replace(
                                    entry,
                                    action_is_ranged=(behavior == "ranged"),
                                )
                                if entry.actor.name == actor["name"] else entry
                                for entry in ledger.entries
                            ),
                        )
                    projected_ledger = _apply_tactical_choices_to_ledger(
                        ledger, None, None
                    )
                projection = _build_encounter_projection(
                    projected_ledger, scenario["encounter"], []
                )
                projected_actor = enemy(
                    {"encounter": projection}, actor["name"]
                )
                if behavior == "melee":
                    self.assertNotIn("coverFeatureId", projected_actor)
                    self.assertNotIn("coverType", projected_actor)
                else:
                    self.assertEqual(
                        projected_actor["coverFeatureId"], feature["featureId"]
                    )
                    self.assertEqual(projected_actor["coverType"], feature["coverType"])

    def test_departure_defeat_and_death_clear_cover_in_final_projection(self):
        for reason in ("fled", "surrendered"):
            scenario = build_g5t_scenario(1)
            actor = enemy(scenario, "Goblin Squad A")
            feature = scenario["tactical_features"][0]
            actor.update(
                coverFeatureId=feature["featureId"], coverType=feature["coverType"]
            )
            ledger = _scenario_plan(scenario, active=True)
            ledger = replace(
                ledger,
                departures=(EnemyDeparture(
                    CombatantIdentity(actor["name"], "enemy"), reason
                ),),
            )
            projected_ledger = _apply_tactical_choices_to_ledger(
                ledger, None, None
            )
            projection = _build_encounter_projection(
                projected_ledger, scenario["encounter"], []
            )
            projected_actor = enemy({"encounter": projection}, actor["name"])
            self.assertEqual(projected_actor["status"], "defeated")
            self.assertEqual(projected_actor["defeatReason"], reason)
            self.assertNotIn("coverFeatureId", projected_actor)
            self.assertNotIn("coverType", projected_actor)

        for status, hp in (("defeated", 7), ("dead", 0), ("alive", 0)):
            scenario = build_g5t_scenario(1)
            actor = enemy(scenario, "Goblin Squad A")
            feature = scenario["tactical_features"][0]
            ledger = _scenario_plan(scenario, active=True)
            actor.update(
                coverFeatureId=feature["featureId"],
                coverType=feature["coverType"],
                status=status,
                currentHitPoints=hp,
            )
            projection = _build_encounter_projection(
                ledger, scenario["encounter"], []
            )
            projected_actor = enemy({"encounter": projection}, actor["name"])
            self.assertNotIn("coverFeatureId", projected_actor)
            self.assertNotIn("coverType", projected_actor)

    def test_cover_projection_adds_no_extra_persistence_write(self):
        identity = CombatantIdentity("Goblin", "enemy")
        update = EnemyCoverUpdate(identity, "RACKS", "half")
        ledger = EnemyResolutionLedger(
            encounter_id="cover-write",
            round_number=1,
            batch_id="cover-write-batch",
            batch_kind="enemy_phase",
            seed=1,
            entries=(),
            bloodied=(),
            cover_updates=(update,),
        )
        encounter = {
            "encounterId": "cover-write",
            "combat_round": 1,
            "combat_phase": "PC_PHASE",
            "creatures": [{
                "name": "Goblin", "type": "enemy", "status": "alive",
                "currentHitPoints": 7, "maxHitPoints": 7,
            }],
        }
        writes = []

        class Paths:
            def get_encounter_path_from_id(self, encounter_id):
                return "encounter:" + encounter_id

            def get_character_path(self, character_name):
                return "character:" + character_name

        result = apply_enemy_batch(
            ledger,
            NarrationResult("The goblin braces behind the racks.", "template"),
            user_input_text="Enemies turn.",
            turn_id="00000000-0000-4000-8000-000000000022",
            conversation_history=[],
            conversation_history_file="history",
            encounter_projection=encounter,
            path_manager=Paths(),
            read_json=lambda _path: copy.deepcopy(encounter),
            write_json=lambda path, payload: writes.append((path, copy.deepcopy(payload))) or True,
        )
        self.assertEqual(result.write_count, 2)
        self.assertEqual(len(writes), 2)
        self.assertEqual(
            result.encounter_projection["creatures"][0]["coverFeatureId"], "RACKS"
        )
        self.assertEqual(result.encounter_projection["creatures"][0]["coverType"], "half")
        self.assertEqual(writes[-1][1]["creatures"][0]["coverFeatureId"], "RACKS")


class PromptAndPlayerAttackCoverTests(ProviderFreeTestCase):
    def _prompt_result(self, active_encounter_id):
        encounter = {
            "encounterId": "prompt-cover",
            "combat_round": 1,
            "preroll_cache": {"round": 1, "rolls": "cached"},
            "creatures": [
                {
                    "name": "Acheron", "type": "player", "initiative": 20,
                    "currentHitPoints": 20, "maxHitPoints": 20,
                    "armorClass": 14, "status": "alive",
                },
                {
                    "name": "Goblin", "type": "enemy", "initiative": 10,
                    "currentHitPoints": 7, "maxHitPoints": 7,
                    "armorClass": 15, "status": "alive",
                    "coverFeatureId": "PIT_COVER", "coverType": "half",
                },
            ],
        }
        feature = _feature("PIT_COVER", "half")

        class Paths:
            def get_character_path(self, name):
                return "fixture-character:" + name

        class Manager:
            current_pc_name = "Acheron"
            combat_phase = "PC_PHASE"
            pc_phase_complete = False

            def format_initiative_tracker(self, _encounter):
                return (
                    "[>] Acheron\n```json\n"
                    '{"player_name":"Acheron","process_until":"PC_PHASE",'
                    '"turn_window":[]}\n```'
                )

            def get_current_actor(self):
                return type("Actor", (), {"name": "Acheron"})()

            def get_required_response_prompt(self):
                return "Continue the PC phase."

            def get_remaining_enemies_for_round(self):
                return ["Goblin"]

            def format_party_turn_summary(self):
                return "party summary"

            def format_pc_context_for_prompt(self, name):
                return "PC context: " + name

        dependencies = CombatContextDependencies(
            normalize_character_name=lambda name: name,
            safe_json_load=lambda _path: {
                "hitPoints": 20, "maxHitPoints": 20, "status": "alive",
                "condition": "none", "condition_affected": [],
                "spellcasting": {},
            },
            load_npc_with_fuzzy_match=lambda *_args, **_kwargs: (None, None),
            collect_authoritative_combat_roster=lambda data, **_kwargs: [
                {"name": row["name"], "type": row["type"]}
                for row in data["creatures"]
            ],
            generate_prerolls=lambda *_args, **_kwargs: "unused",
            save_json_file=lambda *_args: None,
            module_path_manager_factory=lambda *_args, **_kwargs: None,
            file_exists=lambda _path: False,
            logger_debug=lambda *_args, **_kwargs: None,
            logger_error=lambda *_args, **_kwargs: None,
            emit=lambda _value: None,
            random_int=lambda _low, _high: 1000,
            fallback_initiative_tracker=lambda *_args: None,
        )
        inputs = CombatContextInputs(
            encounter_data=encounter,
            multi_pc_manager=Manager(),
            party_tracker_data={
                "partyMembers": ["Acheron"], "active_character": "Acheron",
                "partyNPCs": [], "module": "Fixture",
                "worldConditions": {
                    "activeCombatEncounter": active_encounter_id,
                },
            },
            player_info={"name": "Acheron", "spellcasting": {}},
            player_name_display="Acheron",
            current_hp=20,
            max_hp=20,
            pre_context_player_data=None,
            path_manager=Paths(),
            json_file_path="unused",
            conversation_history=[],
            user_input_text="Hold position.",
            location_info={"tacticalFeatures": [feature]},
        )
        return assemble_combat_context(inputs, dependencies)

    def test_llm_context_shows_effective_ac_but_keeps_base_ac_values(self):
        active = self._prompt_result("prompt-cover")
        inactive = self._prompt_result("previous-encounter")
        self.assertIn(
            "Goblin: 17 (effective AC; base 15, half cover)",
            active.armor_class_block,
        )
        self.assertEqual(active.armor_class_values["Goblin"], 15)
        self.assertIn("Goblin: 15\n", inactive.armor_class_block)
        self.assertNotIn("effective AC", inactive.armor_class_block)

    def test_pc_attack_hit_and_miss_use_active_effective_ac_in_output_and_ledger(self):
        encounter = {
            "encounterId": "pc-cover",
            "creatures": [
                {
                    "name": "Acheron", "type": "player", "initiative": 20,
                    "currentHitPoints": 20, "maxHitPoints": 20,
                    "armorClass": 14, "status": "alive",
                },
                {
                    "name": "Goblin", "type": "enemy", "initiative": 10,
                    "currentHitPoints": 7, "maxHitPoints": 7,
                    "armorClass": 15, "status": "alive",
                    "coverFeatureId": "PIT_COVER", "coverType": "half",
                },
            ],
        }
        feature = _feature("PIT_COVER", "half")
        manager = MultiPCCombatManager()
        manager._state.pc_states["Acheron"] = PCCombatState(
            character_name="Acheron", current_hp=20, max_hp=20, ac=14,
            status=PCStatus.READY,
        )
        manager._state.current_pc_name = "Acheron"
        manager.initialize_turn_queue(encounter)

        with mock.patch(
            "core.combat.multi_pc.manager.COMBAT_FAST_DETERMINISTIC_NARRATION",
            True,
        ), mock.patch("core.combat.multi_pc.manager.trace_decision"):
            miss = manager.handle_combat_command(
                "/att Goblin 16", encounter, actor_name="Acheron",
                active_encounter_id="pc-cover", tactical_features=[feature],
            )
            hit = manager.handle_combat_command(
                "/att Goblin 17", encounter, actor_name="Acheron",
                active_encounter_id="pc-cover", tactical_features=[feature],
            )

        self.assertIn("Miss.", miss[0])
        self.assertIn("vs AC 17 (half cover)", miss[0])
        self.assertIn("Hit!", hit[0])
        self.assertIn("vs AC 17 (half cover)", hit[0])
        self.assertEqual(manager.pc_phase_event_ledger[0]["facts"]["ac"], 17)
        self.assertEqual(manager.pc_phase_event_ledger[0]["facts"]["cover"], "half cover")

        stale = manager.handle_combat_command(
            "/att Goblin 16", encounter, actor_name="Acheron",
            active_encounter_id="completed-encounter", tactical_features=[feature],
        )
        self.assertIn("Hit!", stale[0])
        self.assertIn("vs AC 15", stale[0])
        self.assertNotIn("half cover", stale[0])


class CoverPersistenceAndNewEncounterTests(ProviderFreeTestCase):
    def test_new_encounter_builder_does_not_copy_completed_cover_fields(self):
        from core.generators import combat_builder

        class Paths:
            def get_character_path(self, name):
                return "character:" + name

        player = {
            "name": "Acheron", "hitPoints": 20, "maxHitPoints": 20,
            "armorClass": 14, "status": "alive", "condition_affected": [],
        }
        monster = {
            "monster_data": {"name": "Goblin", "hitPoints": 7, "armorClass": 15},
            "canonical_monster_type": "Goblin", "display_name": "Goblin",
        }
        with (
            mock.patch.object(combat_builder, "get_current_location", return_value="CA02"),
            mock.patch.object(combat_builder, "get_next_encounter_number", return_value=4),
            mock.patch.object(combat_builder, "ModulePathManager", return_value=Paths()),
            mock.patch.object(combat_builder, "backup_player_file"),
            mock.patch.object(combat_builder, "load_json", return_value=player),
            mock.patch.object(combat_builder, "format_type_name", side_effect=lambda name: name),
            mock.patch.object(combat_builder, "load_or_create_monster", return_value=monster),
            mock.patch("utils.encoding_utils.safe_json_load", return_value={
                "module": "Capture_Arena", "partyMembers": [],
            }),
        ):
            fresh = combat_builder.generate_encounter({
                "player": "Acheron", "monsters": ["Goblin"],
            })
        self.assertIsNotNone(fresh)
        self.assertTrue(fresh["creatures"])
        self.assertTrue(all(
            "coverType" not in row and "coverFeatureId" not in row
            for row in fresh["creatures"]
        ))
