# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for Python-issued allied-NPC action menus."""

from __future__ import annotations

import copy
import json
import unittest

from core.combat.ally_controller import (
    AllyMenuBuildFailure,
    AllyMenus,
    build_ally_menus,
    select_active_allies,
    validate_ally_plan,
)
from scripts.combat_tactical_test_support import ProviderFreeTestCase


def _attack(name: str, attack_type: str) -> dict:
    return {
        "name": name,
        "attackBonus": 5,
        "damageDice": "1d8",
        "damageBonus": 3,
        "damageType": "piercing" if attack_type == "ranged" else "slashing",
        "type": attack_type,
        "private_attack_note": "must not be projected",
    }


def ally_scenario(party_size: int = 1) -> dict:
    """Return a small 1-PC or 4-PC encounter with active and inactive NPCs."""
    creatures = []
    for index in range(party_size):
        creatures.append({
            "name": "PC %d" % (index + 1),
            "type": "player",
            "status": "alive",
            "currentHitPoints": 20,
            "maxHitPoints": 20,
        })
    creatures.extend([
        {
            "name": "Mira",
            "type": "npc",
            "status": "alive",
            "currentHitPoints": 12,
            "maxHitPoints": 18,
            "loyalty": "disloyal",
            "private_npc_note": "MIRA PRIVATE PROFILE SECRET",
        },
        {
            "name": "Tovin",
            "type": "npc",
            "status": "active",
            "currentHitPoints": 9,
            "maxHitPoints": 12,
        },
        {
            "name": "Unconscious Ally",
            "type": "npc",
            "status": "unconscious",
            "currentHitPoints": 0,
            "maxHitPoints": 10,
        },
        {
            "name": "Dead Ally",
            "type": "npc",
            "status": "dead",
            "currentHitPoints": 0,
            "maxHitPoints": 10,
        },
        {
            "name": "Defeated Ally",
            "type": "npc",
            "status": "defeated",
            "currentHitPoints": 1,
            "maxHitPoints": 10,
        },
        {
            "name": "Departed Ally",
            "type": "npc",
            "status": "departed",
            "currentHitPoints": 5,
            "maxHitPoints": 10,
        },
        {
            "name": "Fled Ally",
            "type": "npc",
            "status": "alive",
            "defeatReason": "fled",
            "currentHitPoints": 5,
            "maxHitPoints": 10,
        },
        {
            "name": "Goblin",
            "type": "enemy",
            "status": "alive",
            "currentHitPoints": 7,
            "maxHitPoints": 7,
            "enemy_private_plan": "ENEMY PRIVATE TACTICS SECRET",
        },
        {
            "name": "Orc",
            "type": "enemy",
            "status": "alive",
            "currentHitPoints": 15,
            "maxHitPoints": 15,
        },
        {
            "name": "Hidden Wight",
            "type": "enemy",
            "status": "alive",
            "currentHitPoints": 20,
            "maxHitPoints": 20,
            "hidden": True,
            "secret": "HIDDEN CREATURE SECRET",
        },
    ])
    turn_order = [
        {"name": creature["name"], "kind": creature["type"]}
        for creature in creatures
    ]
    return {
        "encounter": {
            "encounterId": "ally-menu-test",
            "creatures": creatures,
            "module_roster": ["UNRELATED FULL ROSTER SECRET"],
            "enemy_private_plans": {"secret": "DO NOT SHARE ENEMY PLANS"},
        },
        "turn_order": turn_order,
        "profiles": {
            "Mira": {
                "name": "Mira",
                "loyalty": "disloyal",
                "backstory": "PRIVATE PROFILE STORY",
                "attacksAndSpellcasting": [
                    _attack("Longbow", "ranged"),
                    _attack("Dagger", "melee"),
                    {"name": "Sleep", "type": "spell"},
                    {"name": "Malformed Attack", "type": "attack", "attackBonus": "bad"},
                ],
            },
            "Tovin": {
                "name": "Tovin",
                "attacksAndSpellcasting": [_attack("Longsword", "melee")],
            },
        },
        "features": [
            {
                "featureId": "npc-rack-cover",
                "name": "Shield Racks",
                "kind": "cover",
                "coverType": "half",
                "usableBy": ["npc"],
            },
            {
                "featureId": "enemy-only-cover",
                "name": "Enemy Cover",
                "kind": "cover",
                "coverType": "three_quarters",
                "usableBy": ["enemy"],
            },
            {
                "featureId": "player-only-cover",
                "name": "Player Cover",
                "kind": "cover",
                "coverType": "half",
                "usableBy": ["player"],
            },
            {
                "featureId": "cover-with-extra-data",
                "name": "Invalid Cover",
                "kind": "cover",
                "coverType": "half",
                "usableBy": ["npc"],
                "enemy_only_secret": "NOT A CONTRACT FIELD",
            },
        ],
    }


def build_menus(scenario: dict, *, features=None, legal_targets=None):
    return build_ally_menus(
        scenario["encounter"],
        "ally-batch-1",
        npc_profiles=scenario["profiles"],
        scheduled_allies=scenario["turn_order"],
        turn_order=scenario["turn_order"],
        legal_targets=legal_targets,
        tactical_features=scenario["features"] if features is None else features,
    )


def _actor_menu(menus: AllyMenus, name: str):
    return next(menu for menu in menus.actor_menus if menu.actor.name == name)


class CombatAllyMenuTests(ProviderFreeTestCase):
    def test_active_allies_are_only_active_encounter_npcs_for_one_and_four_pcs(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                scenario = ally_scenario(party_size)
                allies = select_active_allies(
                    scenario["encounter"], scenario["turn_order"]
                )
                self.assertEqual([item.name for item in allies], ["Mira", "Tovin"])
                menus = build_menus(scenario)
                self.assertIsInstance(menus, AllyMenus)
                self.assertEqual(
                    [menu.actor.name for menu in menus.actor_menus],
                    ["Mira", "Tovin"],
                )
                self.assertTrue(all(menu.actor.kind == "npc" for menu in menus.actor_menus))

    def test_attack_menus_are_opaque_bounded_and_use_only_live_visible_enemy_targets(self):
        scenario = ally_scenario(4)
        before = copy.deepcopy(scenario)
        menus = build_menus(scenario)
        self.assertIsInstance(menus, AllyMenus)
        self.assertEqual(scenario, before)
        self.assertEqual([target.name for target in menus.legal_targets], ["Goblin", "Orc"])

        mira = _actor_menu(menus, "Mira")
        self.assertEqual(
            {(option.attack.name, option.target.name) for option in mira.attack_options},
            {
                ("Longbow", "Goblin"),
                ("Longbow", "Orc"),
                ("Dagger", "Goblin"),
                ("Dagger", "Orc"),
            },
        )
        self.assertTrue(all(option.option_id.startswith("opt_") for option in menus.all_options))
        ids = [option.option_id for option in menus.all_options]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [option.option_id for option in build_menus(scenario).all_options])
        self.assertTrue(all(len(option.option_id) == 28 for option in menus.all_options))
        self.assertNotIn("Longbow", " ".join(ids))
        self.assertNotIn("Goblin", " ".join(ids))

    def test_authored_cover_is_offered_only_for_npc_usable_contract_rows(self):
        scenario = ally_scenario()
        menus = build_menus(scenario)
        for actor in menus.actor_menus:
            self.assertEqual(
                [(option.feature_id, option.cover_type) for option in actor.cover_options],
                [("npc-rack-cover", "half")],
            )

        valid_feature = scenario["features"][0]
        duplicate = build_menus(scenario, features=[valid_feature, copy.deepcopy(valid_feature)])
        self.assertIsInstance(duplicate, AllyMenus)
        self.assertTrue(all(not menu.cover_options for menu in duplicate.actor_menus))
        invalid = build_menus(scenario, features=[{
            **valid_feature,
            "coverType": "full",
        }])
        self.assertTrue(all(not menu.cover_options for menu in invalid.actor_menus))

    def test_explicit_target_restriction_intersects_the_python_legal_target_set(self):
        scenario = ally_scenario()
        menus = build_menus(
            scenario,
            legal_targets=[{"name": "Orc", "type": "enemy"}, {"name": "PC 1", "type": "player"}],
        )
        self.assertIsInstance(menus, AllyMenus)
        self.assertEqual([target.name for target in menus.legal_targets], ["Orc"])
        self.assertTrue(all(
            option.target.name == "Orc"
            for menu in menus.actor_menus
            for option in menu.attack_options
        ))

    def test_missing_invalid_duplicate_and_future_placeholder_choices_default(self):
        menus = build_menus(ally_scenario())
        self.assertIsInstance(menus, AllyMenus)

        for malformed in (None, "not-json", [], 5, {"unknown": []}):
            with self.subTest(malformed=malformed):
                malformed_result = validate_ally_plan(malformed, menus)
                self.assertTrue(all(
                    choice.default_reason == "INVALID_PLAN"
                    for choice in malformed_result.choices
                ))

        missing = validate_ally_plan({"choices": []}, menus)
        self.assertEqual(missing.status, "rejected_all")
        self.assertEqual(
            {choice.default_reason for choice in missing.choices}, {"MISSING_CHOICE"}
        )
        for raw_ids, expected_reason in (
            (["not-an-option-id"], "INVALID_PLAN"),
            (["opt_000000000000000000000000"], "UNISSUED_ID"),
            (["opt_000000000000000000000000", "opt_000000000000000000000000"], "DUPLICATE_ID"),
            (["move_to_cover"], "INVALID_PLAN"),
            (["guard_ally"], "INVALID_PLAN"),
            (["interpose_for_ally"], "INVALID_PLAN"),
        ):
            with self.subTest(raw_ids=raw_ids):
                plan = {"choices": [{"actor": "Mira", "option_ids": raw_ids}]}
                result = validate_ally_plan(plan, menus)
                mira = next(choice for choice in result.choices if choice.actor.name == "Mira")
                self.assertEqual(mira.default_reason, expected_reason)
                self.assertEqual(mira.option_ids, (_actor_menu(menus, "Mira").default_option_id,))

        duplicate_actor = validate_ally_plan({"choices": [
            {"actor": "Mira", "option_ids": [_actor_menu(menus, "Mira").default_option_id]},
            {"actor": "Mira", "option_ids": [_actor_menu(menus, "Mira").default_option_id]},
        ]}, menus)
        self.assertEqual(
            next(choice for choice in duplicate_actor.choices if choice.actor.name == "Mira").default_reason,
            "DUPLICATE_ACTOR",
        )

    def test_ranged_attack_may_pair_with_authored_cover_but_melee_may_not(self):
        menus = build_menus(ally_scenario())
        mira = _actor_menu(menus, "Mira")
        tovin = _actor_menu(menus, "Tovin")
        cover_id = mira.cover_options[0].option_id
        ranged = next(option for option in mira.attack_options if option.attack.name == "Longbow")
        plan = {"choices": [
            {"actor": "Mira", "option_ids": [ranged.option_id, cover_id]},
            {"actor": "Tovin", "option_ids": [tovin.attack_options[0].option_id]},
        ]}
        accepted = validate_ally_plan(plan, menus)
        mira_choice = next(choice for choice in accepted.choices if choice.actor.name == "Mira")
        self.assertIsNone(mira_choice.default_reason)
        self.assertEqual(mira_choice.cover_feature_id, "npc-rack-cover")

        melee = next(option for option in mira.attack_options if option.attack.name == "Dagger")
        rejected = validate_ally_plan({"choices": [
            {"actor": "Mira", "option_ids": [melee.option_id, cover_id]},
        ]}, menus)
        rejected_mira = next(choice for choice in rejected.choices if choice.actor.name == "Mira")
        self.assertEqual(rejected_mira.default_reason, "INVALID_PLAN")

    def test_malformed_input_and_missing_legal_attack_fail_closed(self):
        bad_batch = build_ally_menus(ally_scenario()["encounter"], "")
        self.assertIsInstance(bad_batch, AllyMenuBuildFailure)
        no_actions = ally_scenario()
        no_actions["profiles"]["Mira"]["attacksAndSpellcasting"] = []
        result = build_menus(no_actions)
        self.assertIsInstance(result, AllyMenuBuildFailure)
        self.assertEqual(result.reason_code, "no_legal_attack")


if __name__ == "__main__":
    unittest.main()
