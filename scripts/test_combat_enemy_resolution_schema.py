# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Schema and helper contracts for deterministic enemy resolution."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

from core.combat.enemy_resolution import (
    count_encounter_leaders,
    validate_multiattack_declaration,
)


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path):
    with (ROOT / relative_path).open(encoding="utf-8") as source:
        return json.load(source)


class CombatEnemyResolutionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.monster_schema = load_json("schemas/mon_schema.json")
        cls.encounter_schema = load_json("schemas/encounter_schema.json")
        cls.goblin = load_json("modules/Capture_Arena/monsters/goblin.json")

    def test_legacy_goblin_and_valid_multiattack_are_valid(self):
        validator = Draft7Validator(self.monster_schema)
        self.assertEqual(list(validator.iter_errors(self.goblin)), [])
        declared = copy.deepcopy(self.goblin)
        declared["multiattack"] = [{"action": "Scimitar", "count": 2}]
        self.assertEqual(list(validator.iter_errors(declared)), [])

    def test_invalid_multiattack_shapes_are_rejected(self):
        validator = Draft7Validator(self.monster_schema)
        invalid_items = [
            {"action": "Scimitar", "count": 0},
            {"action": "Scimitar", "count": "2"},
            {"action": "Scimitar", "count": 2, "extra": True},
            {"count": 2},
        ]
        for item in invalid_items:
            with self.subTest(item=item):
                monster = copy.deepcopy(self.goblin)
                monster["multiattack"] = [item]
                self.assertTrue(list(validator.iter_errors(monster)))

    def test_encounter_leader_is_optional_boolean(self):
        validator = Draft7Validator(self.encounter_schema)
        encounter = {
            "encounterId": "test",
            "encounterSummary": "Test encounter",
            "creatures": [{
                "name": "Goblin",
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": 10,
                "status": "alive",
                "conditions": [],
                "actions": {"actionType": "attack", "target": "PC"},
                "currentHitPoints": 7,
                "maxHitPoints": 7,
            }],
        }
        self.assertEqual(list(validator.iter_errors(encounter)), [])
        encounter["creatures"][0]["leader"] = True
        self.assertEqual(list(validator.iter_errors(encounter)), [])
        encounter["creatures"][0]["leader"] = "yes"
        self.assertTrue(list(validator.iter_errors(encounter)))

    def test_multiattack_helper_error_codes(self):
        self.assertEqual(validate_multiattack_declaration({"actions": []}), [])
        self.assertEqual(
            validate_multiattack_declaration({"multiattack": "Scimitar"}),
            ["multiattack_not_list"],
        )
        base = {"actions": [{"name": "Scimitar"}]}
        cases = [
            ([None], "multiattack_item_not_object"),
            ([{"action": "Scimitar", "count": 1, "extra": 1}], "multiattack_item_extra_keys"),
            ([{"action": "", "count": 1}], "multiattack_action_invalid"),
            ([{"action": "Missing", "count": 1}], "multiattack_action_unknown"),
            ([{"action": "Scimitar", "count": 0}], "multiattack_count_invalid"),
        ]
        for declaration, error_code in cases:
            with self.subTest(error_code=error_code):
                monster = {**base, "multiattack": declaration}
                self.assertIn(error_code, validate_multiattack_declaration(monster))

        duplicate_action = {
            "actions": [{"name": "Scimitar"}, {"name": "Scimitar"}],
            "multiattack": [{"action": "Scimitar", "count": 1}],
        }
        self.assertEqual(
            validate_multiattack_declaration(duplicate_action),
            ["multiattack_action_ambiguous"],
        )
        boolean_count = {
            **base,
            "multiattack": [{"action": "Scimitar", "count": True}],
        }
        self.assertEqual(
            validate_multiattack_declaration(boolean_count),
            ["multiattack_count_invalid"],
        )

    def test_count_encounter_leaders(self):
        self.assertEqual(count_encounter_leaders({"creatures": []}), 0)
        self.assertEqual(
            count_encounter_leaders({"creatures": [{"leader": True}]}), 1
        )
        self.assertEqual(
            count_encounter_leaders({
                "creatures": [{"leader": True}, {"leader": True}, {"leader": "yes"}]
            }),
            2,
        )


if __name__ == "__main__":
    unittest.main()
