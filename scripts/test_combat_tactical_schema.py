# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Schema, compatibility, and authored-data contracts for G5T fixtures."""

import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

from core.combat.enemy_resolution import validate_multiattack_declaration
from core.combat.tactical_contracts import validate_tactical_features
from scripts.combat_latency_fixtures import (
    build_g5t_commander_fixture,
    build_gate_profile,
)


ROOT = Path(__file__).resolve().parents[1]

EXISTING_GATE_PROFILE_SHA256 = {
    ("g5", 1): "220b3d78fa5ffe386b995fae757ed47f7d9b0eaa97606c1b2acd16cbd67c411b",
    ("g5", 4): "3f691a26a8bb241d2c3a828cf13c89d57f757ad8029783c851a98160f17694c1",
    ("g5r", 1): "2a920b99d6cda21a84a300a76427706dd67244c8ae32b570625eabf99e995f28",
    ("g5r", 4): "ead385c6dd9321ef9edf2fe44c19a3602c22edcfcf7108870927771aa07cc844",
}

CAPTURE_ARENA_SOURCE_SHA256 = {
    "modules/Capture_Arena/areas/CTR001_BU.json": "4293cc1b65c5e18d36e0cb2830cd4933b6c89bd89bcb8a9927d0e3dfe908f0ed",
    "modules/Capture_Arena/map_CTR001.json": "3c51ee61ae2d3bcd07658992078deb1556af765a12d0c6604f9e001b60defc09",
    "modules/Capture_Arena/module_context.json": "de7d9eede3be92e79a3097dc2cd2a259a52098f2d6b56c1ac7122dfe10aaca13",
    "modules/Capture_Arena/module_context_BU.json": "de7d9eede3be92e79a3097dc2cd2a259a52098f2d6b56c1ac7122dfe10aaca13",
    "modules/Capture_Arena/module_plot_BU.json": "09b5e8e03d4708946b892c1db08818b9975eb6181b5d70fc88f73dad2e8802b2",
    "modules/Capture_Arena/monsters/goblin.json": "fc3a7aa8341fc7745b4c85ea25d123184d03c25b3def4858b444af692f457b43",
}


def load_json(relative_path):
    with (ROOT / relative_path).open(encoding="utf-8") as source:
        return json.load(source)


def _legacy_encounter():
    return {
        "encounterId": "legacy-schema-sample",
        "encounterSummary": "Existing encounter without tactical fields.",
        "creatures": [
            {
                "name": "Goblin",
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": 10,
                "status": "alive",
                "conditions": [],
                "actions": {"actionType": "attack", "target": "Acheron"},
                "currentHitPoints": 7,
                "maxHitPoints": 7,
            }
        ],
    }


class CombatTacticalSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encounter_schema = load_json("schemas/encounter_schema.json")
        cls.location_schema = load_json("schemas/locationfile_schema.json")
        cls.monster_schema = load_json("schemas/mon_schema.json")
        cls.encounter_validator = Draft7Validator(cls.encounter_schema)
        cls.location_validator = Draft7Validator(cls.location_schema)
        cls.monster_validator = Draft7Validator(cls.monster_schema)

    def test_legacy_encounter_and_existing_module_areas_remain_valid(self):
        legacy = _legacy_encounter()
        self.assertEqual(list(self.encounter_validator.iter_errors(legacy)), [])
        for creature in legacy["creatures"]:
            for field in ("tactics", "defeatReason", "coverType", "coverFeatureId"):
                self.assertNotIn(field, creature)

        area_paths = (
            "modules/Capture_Arena/areas/CTR001_BU.json",
            "modules/The_Thornwood_Watch/areas/TW001_BU.json",
            "modules/Night_of_the_Restless_Dead/areas/NIG001_BU.json",
        )
        for relative_path in area_paths:
            with self.subTest(path=relative_path):
                self.assertEqual(
                    list(self.location_validator.iter_errors(load_json(relative_path))), []
                )

        # Runtime save snapshots are not required in a clean checkout. When
        # present, sample existing module encounters in addition to the stable
        # legacy payload above.
        encounter_paths = sorted(
            (ROOT / "modules").glob(
                "*/saved_games/*/modules/encounters/encounter_*.json"
            )
        )
        sampled_modules = set()
        for path in encounter_paths:
            module_name = path.relative_to(ROOT / "modules").parts[0]
            if module_name in sampled_modules:
                continue
            sampled_modules.add(module_name)
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual(
                    list(self.encounter_validator.iter_errors(load_json(str(path.relative_to(ROOT))))),
                    [],
                )
            if len(sampled_modules) == 2:
                break

    def test_defeat_reason_values_are_optional_and_enum_constrained(self):
        for reason in ("fled", "surrendered"):
            encounter = _legacy_encounter()
            encounter["creatures"][0]["defeatReason"] = reason
            self.assertEqual(list(self.encounter_validator.iter_errors(encounter)), [])

        invalid = _legacy_encounter()
        invalid["creatures"][0]["defeatReason"] = "killed"
        self.assertTrue(list(self.encounter_validator.iter_errors(invalid)))

    def test_tactics_values_are_enum_constrained(self):
        for tactics in ("rule", "commander"):
            encounter = _legacy_encounter()
            encounter["creatures"][0]["tactics"] = tactics
            self.assertEqual(list(self.encounter_validator.iter_errors(encounter)), [])

        invalid = _legacy_encounter()
        invalid["creatures"][0]["tactics"] = "tactician"
        self.assertTrue(list(self.encounter_validator.iter_errors(invalid)))

    def test_cover_state_is_optional_and_enum_constrained(self):
        for cover_type in ("half", "three_quarters"):
            encounter = _legacy_encounter()
            encounter["creatures"][0].update(
                {"coverType": cover_type, "coverFeatureId": "ca02-shield-racks"}
            )
            self.assertEqual(list(self.encounter_validator.iter_errors(encounter)), [])

        encounter = _legacy_encounter()
        encounter["creatures"][0]["coverType"] = "full"
        self.assertTrue(list(self.encounter_validator.iter_errors(encounter)))
        encounter["creatures"][0].update(
            {"coverType": "half", "coverFeatureId": 17}
        )
        self.assertTrue(list(self.encounter_validator.iter_errors(encounter)))

    def test_tactical_feature_schema_rejects_invalid_items(self):
        valid_feature = {
            "featureId": "ca02-shield-racks",
            "name": "Scarred Shield Racks",
            "kind": "cover",
            "coverType": "half",
            "usableBy": ["enemy"],
        }

        def area_with(feature):
            return {
                "areaId": "CTR001",
                "areaName": "Capture Arena",
                "locations": [
                    {
                        "locationId": "CA02",
                        "name": "Training Pit",
                        "description": "A sunken sand pit.",
                        "tacticalFeatures": [feature],
                    }
                ],
            }

        self.assertEqual(
            list(self.location_validator.iter_errors(area_with(valid_feature))), []
        )
        invalid_features = (
            {**valid_feature, "coverType": "full"},
            {**valid_feature, "usableBy": []},
            {**valid_feature, "usableBy": [""]},
            {**valid_feature, "featureId": ""},
            {**valid_feature, "unexpected": True},
        )
        for feature in invalid_features:
            with self.subTest(feature=feature):
                self.assertTrue(
                    list(self.location_validator.iter_errors(area_with(feature)))
                )

    def test_duplicate_feature_id_returns_one_bounded_error_code(self):
        features = [
            {"featureId": "ca02-shield-racks"},
            {"featureId": "ca02-shield-racks"},
            {"featureId": "another-feature"},
        ]
        self.assertEqual(validate_tactical_features(features), ["duplicate_feature_id"])
        self.assertEqual(validate_tactical_features([{"featureId": "unique"}]), [])
        self.assertEqual(validate_tactical_features(None), ["tactical_features_not_list"])

    def test_g5t_commander_fixtures_validate_and_declare_multiattack(self):
        for party_size, goblin_count in ((1, 2), (4, 2)):
            fixture = build_g5t_commander_fixture(party_size)
            encounter = fixture["encounter"]
            self.assertEqual(encounter["encounterId"], "g5t-commander-p%d" % party_size)
            self.assertEqual(list(self.encounter_validator.iter_errors(encounter)), [])

            captain_entry = next(
                creature
                for creature in encounter["creatures"]
                if creature.get("monsterType") == "Hobgoblin Captain"
            )
            self.assertIs(captain_entry["leader"], True)
            self.assertEqual(captain_entry["tactics"], "commander")
            self.assertEqual(
                sum(
                    creature.get("monsterType") == "Goblin"
                    for creature in encounter["creatures"]
                ),
                goblin_count,
            )

            captain = fixture["monster_definitions"]["Hobgoblin Captain"]
            goblin = fixture["monster_definitions"]["Goblin"]
            self.assertEqual(list(self.monster_validator.iter_errors(captain)), [])
            self.assertEqual(list(self.monster_validator.iter_errors(goblin)), [])
            self.assertEqual(validate_multiattack_declaration(captain), [])
            goblin_members = [
                creature
                for creature in encounter["creatures"]
                if creature.get("monsterType") == "Goblin"
            ]
            self.assertEqual(len(goblin_members), goblin_count)
            for _member in goblin_members:
                self.assertEqual(
                    goblin["multiattack"], [{"action": "Shortbow", "count": 1}]
                )
                self.assertEqual(validate_multiattack_declaration(goblin), [])
            shortbow = next(action for action in goblin["actions"]
                            if action["name"] == "Shortbow")
            self.assertEqual(shortbow["attackType"], "ranged")
            self.assertEqual(shortbow["range"], {"normal": 80, "long": 320})
            self.assertEqual(captain["armorClass"], 17)
            self.assertEqual(captain["hitPoints"], 39)
            self.assertEqual(captain["multiattack"], [{"action": "Javelin", "count": 2}])
            longsword = next(action for action in captain["actions"]
                             if action["name"] == "Longsword")
            self.assertEqual(longsword["attackType"], "melee")
            javelin = next(action for action in captain["actions"]
                           if action["name"] == "Javelin")
            self.assertEqual(javelin["attackType"], "ranged")
            self.assertEqual(javelin["range"], {"normal": 30, "long": 120})
            self.assertEqual(
                captain["_srd_attribution"],
                "Portions derived from SRD 5.2.1, CC BY 4.0",
            )

            area = fixture["training_pit_area"]
            self.assertEqual(list(self.location_validator.iter_errors(area)), [])
            feature = area["locations"][0]["tacticalFeatures"][0]
            self.assertEqual(feature["featureId"], "ca02-shield-racks")
            self.assertEqual(feature["coverType"], "half")
            self.assertEqual(feature["usableBy"], ["enemy"])
            self.assertEqual(
                validate_tactical_features(area["locations"][0]["tacticalFeatures"]), []
            )

    def test_existing_g5_and_g5r_profile_outputs_keep_their_hashes(self):
        for (gate, party_size), expected_hash in EXISTING_GATE_PROFILE_SHA256.items():
            profile = build_gate_profile(gate, "combat-smoke", party_size)
            encoded = json.dumps(
                profile,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            actual_hash = hashlib.sha256(encoded).hexdigest()
            with self.subTest(gate=gate, party_size=party_size):
                self.assertEqual(actual_hash, expected_hash)

    def test_capture_arena_canonical_fixture_inputs_are_byte_unchanged(self):
        for relative_path, expected_hash in CAPTURE_ARENA_SOURCE_SHA256.items():
            actual_hash = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
            with self.subTest(path=relative_path):
                self.assertEqual(actual_hash, expected_hash)


if __name__ == "__main__":
    unittest.main()
