# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free checks for the ally-only combat perception projection."""

from __future__ import annotations

import json
import unittest

from core.combat.ally_controller import (
    AllyMenus,
    build_ally_perception_projection,
)
from scripts.combat_tactical_test_support import ProviderFreeTestCase
from scripts.test_combat_ally_menu import ally_scenario, build_menus


class CombatAllyPerceptionTests(ProviderFreeTestCase):
    def test_projection_uses_only_scheduled_allies_and_visible_legal_targets(self):
        scenario = ally_scenario(4)
        menus = build_menus(scenario)
        self.assertIsInstance(menus, AllyMenus)
        projection = build_ally_perception_projection(menus)
        self.assertEqual(projection["batch_id"], "ally-batch-1")
        self.assertEqual(
            {row["actor"] for row in projection["scheduled_allies"]},
            {"Mira", "Tovin"},
        )
        self.assertEqual(
            {row["name"] for row in projection["visible_enemies"]},
            {"Goblin", "Orc"},
        )
        encoded = json.dumps(projection, sort_keys=True)
        for forbidden in (
            "Hidden Wight",
            "HIDDEN CREATURE SECRET",
            "ENEMY PRIVATE TACTICS SECRET",
            "DO NOT SHARE ENEMY PLANS",
            "UNRELATED FULL ROSTER SECRET",
            "Unconscious Ally",
            "Dead Ally",
            "Defeated Ally",
            "Departed Ally",
            "Fled Ally",
            "MIRA PRIVATE PROFILE SECRET",
            "PRIVATE PROFILE STORY",
            "private_attack_note",
            "attackBonus",
            "damageDice",
            "damageBonus",
            "damageType",
            "enemy_private_plans",
            "module_roster",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, encoded)

    def test_directive_is_bounded_and_visible_only_to_its_named_ally(self):
        menus = build_menus(ally_scenario())
        projection = build_ally_perception_projection(
            menus,
            directives={
                "  mIrA  ": "  Guard\tPC 1\nthen hold.\x00 ",
                "Unknown Ally": "DO NOT PROJECT",
                "Tovin": "x" * 241,
            },
        )
        rows = {row["actor"]: row for row in projection["scheduled_allies"]}
        self.assertEqual(rows["Mira"]["directive"], "Guard PC 1 then hold.")
        self.assertNotIn("directive", rows["Tovin"])
        self.assertNotIn("Unknown Ally", json.dumps(projection))
        self.assertNotIn("DO NOT PROJECT", json.dumps(projection))
        self.assertNotIn("x" * 241, json.dumps(projection))

    def test_duplicate_normalized_directive_names_are_omitted_as_ambiguous(self):
        menus = build_menus(ally_scenario())
        projection = build_ally_perception_projection(
            menus,
            directives={"Mira": "first order", " mira ": "second order"},
        )
        mira = next(row for row in projection["scheduled_allies"] if row["actor"] == "Mira")
        self.assertNotIn("directive", mira)


if __name__ == "__main__":
    unittest.main()
