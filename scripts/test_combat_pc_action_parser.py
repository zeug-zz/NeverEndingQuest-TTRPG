# SPDX-FileCopyrightText: 2026 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Tests for utils/combat_pc_action_parser.py - Conservative PC_PHASE NL parser.
"""

import os
import sys
import unittest
from copy import deepcopy
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.combat_pc_action_parser import apply_pc_phase_parse_result, parse_pc_phase_action


SAMPLE_ENCOUNTER = {
    "creatures": [
        {"name": "Goblin", "type": "enemy", "armorClass": 15,
         "currentHitPoints": 7, "maxHitPoints": 7, "status": "alive"},
        {"name": "Orc", "type": "enemy", "armorClass": 13,
         "currentHitPoints": 15, "maxHitPoints": 15, "status": "alive"},
        {"name": "Scout Kira", "type": "npc", "armorClass": 14,
         "currentHitPoints": 25, "maxHitPoints": 25, "status": "alive"},
    ]
}

SAMPLE_PARTY = {
    "partyMembers": ["Acheron", "Merisiel"],
    "active_character": "Acheron",
}

FAKE_CASTING_STATE = {
    "hitPoints": 18,
    "maxHitPoints": 20,
    "status": "alive",
    "deathSaves": {"successes": 0, "failures": 0},
    "spellcasting": {
        "spellSlots": {
            "level1": {"current": 2, "max": 2},
            "level2": {"current": 0, "max": 1},
            "level3": {"current": 1, "max": 1},
        }
    },
}

FAKE_HEAL_TARGET_STATE = {
    "hitPoints": 6,
    "maxHitPoints": 20,
    "status": "alive",
    "deathSaves": {"successes": 0, "failures": 0},
}

FAKE_DEAD_TARGET_STATE = {
    "hitPoints": 0,
    "maxHitPoints": 20,
    "status": "dead",
    "deathSaves": {"successes": 0, "failures": 3},
}


def fake_get_character_state(character_name):
    mapping = {
        "Acheron": FAKE_CASTING_STATE,
        "Merisiel": FAKE_HEAL_TARGET_STATE,
        "Dead Merisiel": FAKE_DEAD_TARGET_STATE,
    }
    data = mapping.get(character_name)
    return deepcopy(data) if data is not None else None


class TestTargetResolution(unittest.TestCase):
    """Test target candidate building and matching."""

    def test_unique_exact_match(self):
        result = parse_pc_phase_action("attack Goblin roll 18", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron")
        self.assertTrue(result["handled"])
        self.assertEqual(result["target_name"], "Goblin")

    def test_unique_fuzzy_match_substring(self):
        result = parse_pc_phase_action("shoot Scout roll 10", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron")
        self.assertTrue(result["handled"])
        self.assertEqual(result["target_name"], "Scout Kira")

    def test_ambiguous_target_fallback(self):
        """No target at all should fall back."""
        result = parse_pc_phase_action("attack with roll 18", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron")
        self.assertFalse(result["handled"])
        self.assertIn("unclear_target", result["fallback_reason"])


class TestWeaponAttack(unittest.TestCase):
    """Test 2.1-2.6: Weapon attack parsing."""

    def test_attack_miss_detected(self):
        result = parse_pc_phase_action(
            "attack goblin roll 9 with axe", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "weapon_attack_miss")
        self.assertEqual(result["target_name"], "Goblin")
        self.assertEqual(result["parsed_attack_roll"], 9)
        self.assertIsNotNone(result["mechanical_feedback"])
        self.assertIn("[skipTTS]", result["mechanical_feedback"])
        self.assertIsNotNone(result["spoken_narration"])
        self.assertNotIn("[skipTTS]", result["spoken_narration"])
        self.assertIsNotNone(result["log_msg"])
        self.assertIn("MISSED", result["log_msg"])

    def test_attack_hit_detected(self):
        result = parse_pc_phase_action(
            "hit goblin with roll 18", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "weapon_attack_hit")
        self.assertEqual(result["parsed_attack_roll"], 18)
        self.assertIsNotNone(result["mechanical_feedback"])
        self.assertIn("[prefill:/dmg ]", result["mechanical_feedback"])
        self.assertIn("Hit!", result["mechanical_feedback"])

    def test_attack_hit_with_weapon_flavor(self):
        result = parse_pc_phase_action(
            "stab the goblin with longsword roll 16", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["weapon_name"], "longsword")

    def test_attack_with_damage_in_text_falls_back(self):
        """When the user also includes damage numbers, fall back to be conservative."""
        result = parse_pc_phase_action(
            "attack orc roll 14 for 8 damage", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertIn("damage_not_supported", result["fallback_reason"])

    def test_attack_missing_roll_falls_back(self):
        result = parse_pc_phase_action(
            "attack goblin with sword", SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertEqual(result["fallback_reason"], "unrecognized_action")


class TestMagicMissile(unittest.TestCase):
    """Test 3.1-3.6: Magic Missile parsing."""

    def setUp(self):
        self._state_patch = mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=fake_get_character_state,
        )
        self._state_patch.start()

    def tearDown(self):
        self._state_patch.stop()

    def test_mm_single_target_explicit(self):
        result = parse_pc_phase_action(
            "Magic Missile, 5 to Goblin",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "magic_missile")
        self.assertEqual(len(result["encounter_ops"]), 1)
        self.assertEqual(len(result["character_updates"]), 1)
        self.assertEqual(result["character_updates"][0]["characterName"], "Acheron")
        self.assertEqual(result["character_updates"][0]["ops"][0]["op"], "spell_slot_delta")
        self.assertEqual(result["encounter_ops"][0]["creature"], "Goblin")
        self.assertEqual(result["encounter_ops"][0]["delta"], -5)

    def test_mm_multiple_targets(self):
        result = parse_pc_phase_action(
            "Magic Missile, 3 to Goblin, 2 to Orc",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(len(result["encounter_ops"]), 2)
        self.assertEqual(len(result["character_updates"]), 1)

    def test_mm_unclear_allocation_falls_back(self):
        result = parse_pc_phase_action(
            "I cast Magic Missile at the goblin",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertIn("unclear_allocation", result["fallback_reason"])

    def test_mm_ambiguous_target_falls_back(self):
        result = parse_pc_phase_action(
            "Magic Missile, 3 to nobody",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertIn("ambiguous_target", result["fallback_reason"])

    def test_mm_unavailable_slot_falls_back(self):
        with mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            return_value={"spellcasting": {"spellSlots": {"level1": {"current": 0, "max": 1}}}},
        ):
            result = parse_pc_phase_action(
                "Magic Missile, 5 to Goblin",
                SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
            )
        self.assertFalse(result["handled"])
        self.assertIn("mm_slot_unavailable", result["fallback_reason"])


class TestHealing(unittest.TestCase):
    """Test 4.1-4.5: Healing parsing."""

    def setUp(self):
        self._state_patch = mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=fake_get_character_state,
        )
        self._state_patch.start()

    def tearDown(self):
        self._state_patch.stop()

    def test_heal_explicit_amount_and_target(self):
        result = parse_pc_phase_action(
            "Cure Wounds on Merisiel for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "healing")
        self.assertEqual(result["target_name"], "Merisiel")
        self.assertEqual(result["parsed_heal_amount"], 8)
        self.assertEqual(len(result["character_updates"]), 2)  # heal + slot spend

    def test_heal_no_spell_keyword_no_slot_spend(self):
        result = parse_pc_phase_action(
            "heal merisiel for 5",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(len(result["character_updates"]), 1)  # just healing, no slot

    def test_heal_unclear_amount_falls_back(self):
        result = parse_pc_phase_action(
            "Cure Wounds on Merisiel",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertIn("unclear_amount", result["fallback_reason"])

    def test_heal_unclear_target_falls_back(self):
        result = parse_pc_phase_action(
            "heal for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertIn("unclear_target", result["fallback_reason"])

    def test_heal_dead_target_rejected(self):
        with mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=lambda name: deepcopy(FAKE_DEAD_TARGET_STATE) if name == "Dead Merisiel" else deepcopy(FAKE_CASTING_STATE),
        ):
            result = parse_pc_phase_action(
                "Cure Wounds on Dead Merisiel for 8",
                {"creatures": [{"name": "Dead Merisiel", "type": "npc", "status": "unknown", "currentHitPoints": 0, "maxHitPoints": 20, "armorClass": 10}]},
                SAMPLE_PARTY,
                "Acheron",
            )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "healing_dead_rejected")
        self.assertIn("dead_target", result["fallback_reason"])

    def test_heal_unavailable_slot_falls_back(self):
        with mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=lambda name: deepcopy({
                "hitPoints": 18,
                "maxHitPoints": 20,
                "status": "alive",
                "deathSaves": {"successes": 0, "failures": 0},
                "spellcasting": {"spellSlots": {"level1": {"current": 0, "max": 1}}},
            }) if name == "Acheron" else deepcopy(FAKE_HEAL_TARGET_STATE),
        ):
            result = parse_pc_phase_action(
                "Cure Wounds on Merisiel for 8",
                SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
            )
        self.assertFalse(result["handled"])
        self.assertIn("heal_slot_unavailable", result["fallback_reason"])


class TestMovement(unittest.TestCase):
    """Test 4.5: Movement-only parsing."""

    def test_movement_simple(self):
        result = parse_pc_phase_action(
            "move behind the pillar",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "movement")
        self.assertIsNotNone(result["spoken_narration"])

    def test_movement_without_forbidden_keywords(self):
        result = parse_pc_phase_action(
            "retreat behind the shield wall",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Merisiel"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "movement")

    def test_movement_with_attack_keyword_falls_back(self):
        result = parse_pc_phase_action(
            "move and attack the goblin",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])


class TestFallback(unittest.TestCase):
    """Test fallback behavior for unrecognized or empty input."""

    def test_empty_input(self):
        result = parse_pc_phase_action("", SAMPLE_ENCOUNTER, SAMPLE_PARTY)
        self.assertFalse(result["handled"])

    def test_unrecognized_action(self):
        result = parse_pc_phase_action(
            "I cast a complicated spell with vague effects",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])

    def test_parse_result_has_expected_keys(self):
        result = parse_pc_phase_action("goblin", SAMPLE_ENCOUNTER, SAMPLE_PARTY)
        for key in ("handled", "kind", "mechanical_feedback", "spoken_narration",
                    "log_msg", "fallback_reason", "encounter_ops", "character_updates"):
            self.assertIn(key, result)


class TestApplyParseResultFailures(unittest.TestCase):
    """Test that apply failures do not claim success."""

    def test_character_update_failure_returns_false(self):
        result = {
            "handled": True,
            "kind": "healing",
            "target_name": "Merisiel",
            "changes_text": "Merisiel healed for 8 HP",
            "character_updates": [
                {
                    "characterName": "Merisiel",
                    "ops": [{"op": "hp_delta", "delta": 8}],
                    "changes": "Healed for 8 HP",
                }
            ],
            "encounter_ops": [],
            "ledger_event": {"kind": "spell_healing", "facts": {"amount": 8, "slots_spent": 1}},
            "spoken_narration": "Dungeon Master: healing text",
        }
        manager = mock.Mock()
        manager.find_target.return_value = {"name": "Merisiel"}
        manager.record_pc_phase_event = mock.Mock()

        with mock.patch("updates.update_character_info.update_character_info", return_value=False) as mock_update_character, mock.patch(
            "updates.update_encounter.update_encounter"
        ) as mock_update_encounter:
            ok = apply_pc_phase_parse_result(result, manager, SAMPLE_ENCOUNTER, "ENC-1", "Acheron")

        self.assertFalse(ok)
        mock_update_character.assert_called_once()
        mock_update_encounter.assert_not_called()
        manager.record_pc_phase_event.assert_not_called()

    def test_encounter_update_failure_returns_false(self):
        result = {
            "handled": True,
            "kind": "magic_missile",
            "target_name": "Goblin",
            "changes_text": "Goblin takes 5 force damage.",
            "character_updates": [],
            "encounter_ops": [{"op": "hp_delta", "creature": "Goblin", "delta": -5}],
            "ledger_event": {"kind": "spell_damage", "facts": {"damage_per_dart": [5], "targets": "Goblin", "total_damage": 5}},
            "spoken_narration": "Dungeon Master: magic text",
        }
        manager = mock.Mock()
        manager.find_target.return_value = {"name": "Goblin"}
        manager.record_pc_phase_event = mock.Mock()

        with mock.patch("updates.update_encounter.update_encounter", return_value=False) as mock_update_encounter, mock.patch(
            "updates.update_character_info.update_character_info"
        ) as mock_update_character:
            ok = apply_pc_phase_parse_result(result, manager, SAMPLE_ENCOUNTER, "ENC-1", "Acheron")

        self.assertFalse(ok)
        mock_update_encounter.assert_called_once()
        mock_update_character.assert_not_called()
        manager.record_pc_phase_event.assert_not_called()


class TestFeatureFlagConfig(unittest.TestCase):
    """Test that the feature flag exists in model_config."""

    def test_flag_present(self):
        import model_config
        self.assertTrue(hasattr(model_config, "COMBAT_PC_PHASE_NL_FAST_PATH"))
        # Default should be False (conservative)
        self.assertFalse(model_config.COMBAT_PC_PHASE_NL_FAST_PATH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
