# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free checks for the loyal ally default and forbidden exits."""

from __future__ import annotations

import json
import unittest

from core.combat.ally_controller import (
    AllyMenus,
    build_ally_perception_projection,
    validate_ally_plan,
)
from scripts.combat_tactical_test_support import ProviderFreeTestCase
from scripts.test_combat_ally_menu import ally_scenario, build_menus


class CombatAllyLoyaltyTests(ProviderFreeTestCase):
    def test_current_allies_default_to_loyal_ignoring_profile_loyalty_fields(self):
        scenario = ally_scenario()
        scenario["profiles"]["Tovin"]["loyalty"] = "traitor"
        menus = build_menus(scenario)
        self.assertIsInstance(menus, AllyMenus)
        self.assertEqual(
            {menu.actor.name: menu.loyalty for menu in menus.actor_menus},
            {"Mira": "loyal", "Tovin": "loyal"},
        )
        projection = build_ally_perception_projection(menus)
        self.assertEqual(
            {row["actor"]: row["loyalty"] for row in projection["scheduled_allies"]},
            {"Mira": "loyal", "Tovin": "loyal"},
        )

    def test_menu_and_default_plan_have_no_flee_surrender_or_spatial_choices(self):
        menus = build_menus(ally_scenario())
        self.assertIsInstance(menus, AllyMenus)
        prohibited = {
            "flee",
            "surrender",
            "withdrawal_order",
            "commander_side_surrender",
            "Dodge",
            "dodge",
            "move_to_cover",
            "interpose_for_ally",
            "guard_ally",
        }
        self.assertTrue(all(option.kind == "attack" or option.kind == "take_cover"
                            for option in menus.all_options))
        self.assertFalse(prohibited.intersection(option.kind for option in menus.all_options))
        plan = validate_ally_plan(None, menus)
        self.assertTrue(all(choice.kind == "attack" for choice in plan.choices))
        self.assertTrue(all(choice.target is not None for choice in plan.choices))
        self.assertFalse(prohibited.intersection(choice.kind for choice in plan.choices))
        projection = json.dumps(build_ally_perception_projection(menus))
        for placeholder in prohibited:
            self.assertNotIn(placeholder, projection)

    def test_forged_flee_or_surrender_names_fall_back_to_a_legal_attack(self):
        menus = build_menus(ally_scenario())
        for forged_kind in ("flee", "surrender", "move_to_cover"):
            with self.subTest(forged_kind=forged_kind):
                plan = {"choices": [{
                    "actor": "Mira",
                    "option_ids": [forged_kind],
                }]}
                result = validate_ally_plan(plan, menus)
                mira = next(choice for choice in result.choices if choice.actor.name == "Mira")
                self.assertEqual(mira.kind, "attack")
                self.assertIsNotNone(mira.target)
                self.assertIsNotNone(mira.default_reason)
                self.assertEqual(
                    mira.option_ids,
                    (next(menu for menu in menus.actor_menus if menu.actor.name == "Mira").default_option_id,),
                )


if __name__ == "__main__":
    unittest.main()
