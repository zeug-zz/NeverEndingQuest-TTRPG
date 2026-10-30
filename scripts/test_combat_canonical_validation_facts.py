# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Guarded canonical non-PC fact projection and validation-payload tests."""

import ast
import copy
import json
import math
import os
import unittest
from unittest.mock import patch

from scripts.test_combat_truth_pack import _deny_test_writes
from scripts.test_combat_validation_stage import (
    _dependencies,
    validate_combat_response,
)
from scripts.test_llm_router import ProviderTripwire


COMBAT_MANAGER_PATH = os.path.join("core", "combat", "combat_manager.py")


def _load_actual_builder(case):
    with ProviderTripwire() as provider_tripwire, _deny_test_writes():
        with open(COMBAT_MANAGER_PATH, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                    and item.name == "_build_canonical_non_pc_attack_facts")
        namespace = {"math": math, "os": os}
        exec(compile(ast.Module(body=[node], type_ignores=[]), COMBAT_MANAGER_PATH, "exec"), namespace)
        provider_tripwire.assert_untouched(case)
    return namespace["_build_canonical_non_pc_attack_facts"]


class CanonicalValidationFactsTests(unittest.TestCase):
    def test_actual_source_projection_reaches_actual_fake_validation_payload(self):
        with ProviderTripwire() as provider_tripwire, _deny_test_writes():
            builder = _load_actual_builder(self)
            source_records = {
                "modules/demo/monsters/Goblin.json": {
                    "name": "Goblin",
                    "actions": [
                        {"name": "Scimitar", "attackBonus": 4, "damageDice": "1d6",
                         "damageBonus": 2, "damageType": "slashing", "type": "melee"},
                        {"name": "Shortbow", "attackBonus": 4, "damageDice": "1d6",
                         "damageBonus": 2, "damageType": "piercing", "type": "ranged"},
                    ],
                },
                "modules/demo/monsters/Troll.json": {"name": "Troll", "actions": "broken"},
                "modules/demo/monsters/BadNumbers.json": {
                    "name": "BadNumbers",
                    "actions": [
                        {"name": "String bonus", "attackBonus": "+4", "damageBonus": 2},
                        {"name": "NaN damage", "attackBonus": 4, "damageBonus": math.nan},
                        {"name": "Object damage", "attackBonus": 4, "damageBonus": {"value": 2}},
                    ],
                },
            }

            class FakePathManager:
                def __init__(self, module):
                    self.module = module

                def get_monster_path(self, name):
                    return f"modules/demo/monsters/{name}.json"

                def get_character_path(self, name):
                    return f"modules/demo/characters/{name}.json"

            def fake_load(path):
                if path == "party_tracker.json":
                    return {"module": "Demo"}
                return source_records.get(path)

            def fake_npc_loader(name, path_manager):
                if name == "Blairen":
                    return {"name": "Blairen", "attacksAndSpellcasting": [{
                        "name": "Longsword", "attackBonus": 3, "damageDice": "1d8",
                        "damageBonus": 1, "damageType": "slashing", "type": "melee",
                    }]}, "Blairen"
                if name == "Stale Ally":
                    return {"name": "Other Ally", "attacksAndSpellcasting": [{"attackBonus": 99}]}, "Other_Ally"
                return None, None

            pc_names = ("Acheron", "Merisiel", "Kira", "Vitreol")
            responses = []
            for party_size in (1, 4):
                creatures = [{"name": name, "type": "player"} for name in pc_names[:party_size]]
                creatures.extend([
                    {"name": "Blairen", "type": "npc", "status": "alive"},
                    {"name": "Goblin Instance", "type": "enemy", "monsterType": "Goblin", "status": "alive"},
                    {"name": "Missing Goblin", "type": "enemy", "monsterType": "Missing", "status": "alive"},
                    {"name": "Stale Ally", "type": "npc", "status": "alive"},
                    {"name": "Malformed Troll", "type": "enemy", "monsterType": "Troll", "status": "alive"},
                    {"name": "Malformed Numbers", "type": "enemy", "monsterType": "BadNumbers", "status": "alive"},
                    {"name": "Inactive Goblin", "type": "enemy", "monsterType": "Goblin", "status": "defeated", "currentHitPoints": 0},
                ])
                encounter = {"encounterId": f"fixture-{party_size}", "creatures": creatures}
                response = {"plan": "Blairen +99, Goblin +99", "actions": []}
                before = copy.deepcopy((encounter, response, source_records))
                deps, calls = _dependencies()
                deps = __import__("dataclasses").replace(
                    deps,
                    canonical_attack_facts_builder=lambda current, b=builder: b(
                        current, path_manager_factory=FakePathManager,
                        safe_json_loader=fake_load, npc_loader=fake_npc_loader,
                    ),
                )
                self.assertIs(validate_combat_response(
                    json.dumps(response), encounter, "attack", dependencies=deps), True)
                payload = calls["provider"][0]["messages"]
                marker_index = next(i for i, message in enumerate(payload)
                                    if "=== CANONICAL NON-PC ATTACK/STAT FACTS" in message["content"])
                facts = json.loads(payload[marker_index + 1]["content"])
                by_name = {entry["actor"]["name"]: entry for entry in facts}
                blairen_facts = by_name["Blairen"]["attackFacts"]
                goblin_facts = by_name["Goblin Instance"]["attackFacts"]
                self.assertEqual(blairen_facts["sourceField"], "attacksAndSpellcasting")
                self.assertEqual(blairen_facts["attacksAndSpellcasting"][0]["attackBonus"], 3)
                self.assertEqual(blairen_facts["attacksAndSpellcasting"][0]["damageBonus"], 1)
                self.assertEqual(goblin_facts["sourceField"], "actions")
                self.assertEqual(goblin_facts["actions"][0]["attackBonus"], 4)
                self.assertEqual(goblin_facts["actions"][0]["damageBonus"], 2)
                self.assertEqual(goblin_facts["actions"][1]["attackBonus"], 4)
                self.assertEqual(goblin_facts["actions"][1]["damageBonus"], 2)
                self.assertNotIn("attacksAndSpellcasting", goblin_facts)
                self.assertEqual(by_name["Missing Goblin"]["canonicalSource"]["status"], "unknown")
                self.assertIsNone(by_name["Missing Goblin"]["attackFacts"]["attackBonus"])
                self.assertEqual(by_name["Stale Ally"]["canonicalSource"]["status"], "stale_or_mismatched")
                self.assertEqual(by_name["Malformed Troll"]["attackFacts"]["fieldStatus"]["actions"], "unknown_malformed")
                bad_numbers = by_name["Malformed Numbers"]["attackFacts"]
                self.assertEqual(bad_numbers["fieldStatus"]["attackBonus"], "unknown_malformed")
                self.assertEqual(bad_numbers["fieldStatus"]["damageBonus"], "unknown_malformed")
                self.assertEqual(bad_numbers["actions"][0]["fieldStatus"]["attackBonus"], "unknown_malformed")
                self.assertNotIn("attackBonus", bad_numbers["actions"][0])
                self.assertEqual(bad_numbers["actions"][1]["fieldStatus"]["damageBonus"], "unknown_malformed")
                self.assertNotIn("damageBonus", bad_numbers["actions"][1])
                self.assertEqual(bad_numbers["actions"][2]["fieldStatus"]["damageBonus"], "unknown_malformed")
                self.assertNotIn("damageBonus", bad_numbers["actions"][2])
                self.assertFalse(by_name["Inactive Goblin"]["actor"]["eligible"])
                self.assertEqual(by_name["Inactive Goblin"]["attackFacts"]["actions"][0]["attackBonus"], 4)
                self.assertEqual((encounter, response, source_records), before)
                self.assertEqual(FakePathManager("demo").module, "demo")
                self.assertEqual(len(facts), 7)
                provider_tripwire.assert_untouched(self)

    def test_empty_or_invalid_source_facts_are_explicitly_unknown(self):
        with ProviderTripwire() as provider_tripwire, _deny_test_writes():
            builder = _load_actual_builder(self)
            class Paths:
                def __init__(self, module):
                    pass
                def get_monster_path(self, name):
                    return "tmp/missing-monster.json"
            facts = builder(
                {"creatures": [{"name": "No Source", "type": "enemy", "monsterType": "Absent"}]},
                path_manager_factory=Paths,
                safe_json_loader=lambda path: {"module": "Demo"} if path == "party_tracker.json" else None,
                npc_loader=lambda *args: (None, None),
            )
            self.assertEqual(facts[0]["canonicalSource"]["status"], "unknown")
            self.assertTrue(all(value == "unknown_missing" for value in facts[0]["attackFacts"]["fieldStatus"].values()))
            provider_tripwire.assert_untouched(self)

    def test_party_tracker_read_failure_leaves_module_provenance_unknown(self):
        with ProviderTripwire() as provider_tripwire, _deny_test_writes():
            builder = _load_actual_builder(self)

            class Paths:
                def __init__(self, module):
                    self.module = module
                def get_monster_path(self, name):
                    return "tmp/unavailable.json"

            def fail_load(_path):
                raise OSError("fixture source unavailable")

            facts = builder(
                {"creatures": [{"name": "Goblin", "type": "enemy", "monsterType": "Goblin"}]},
                path_manager_factory=Paths, safe_json_loader=fail_load,
                npc_loader=lambda *args: (None, None),
            )
            self.assertEqual(facts[0]["canonicalSource"]["module"], "unknown")
            self.assertEqual(facts[0]["canonicalSource"]["status"], "unknown")
            self.assertEqual(facts[0]["attackFacts"]["sourceField"], "actions")
            provider_tripwire.assert_untouched(self)


if __name__ == "__main__":
    unittest.main()
