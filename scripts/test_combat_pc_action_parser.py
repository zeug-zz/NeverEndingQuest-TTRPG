# SPDX-FileCopyrightText: 2026 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Tests for utils/combat_pc_action_parser.py - Conservative PC_PHASE NL parser.
"""

import os
import sys
import builtins
import io
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.core_chat_test_safety import TripwireFailure, arm_process_tripwires  # noqa: E402


# Arm fatal SDK, network, and outside-write guards before importing any owners.
PROCESS_TRIPWIRES = arm_process_tripwires()


class _PrivateRootReadDenied(BaseException):
    """Fatal sentinel for reads of private root configuration/runtime files."""


def _is_private_root_read(path):
    try:
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate.parent.resolve() == REPO_ROOT.resolve() and candidate.name in {
            "config.py",
            "party_tracker.json",
        }
    except (TypeError, ValueError, OSError):
        return False


def _arm_private_root_read_guard():
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    denials = []

    def check(path, operation):
        if _is_private_root_read(path):
            denials.append(operation)
            raise _PrivateRootReadDenied("private root read denied: " + operation)

    def guarded_open(path, mode="r", *args, **kwargs):
        check(path, "builtins.open")
        return real_open(path, mode, *args, **kwargs)

    def guarded_io_open(path, mode="r", *args, **kwargs):
        check(path, "io.open")
        return real_io_open(path, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        check(path, "os.open")
        return real_os_open(path, flags, *args, **kwargs)

    patches = [
        mock.patch("builtins.open", guarded_open),
        mock.patch("io.open", guarded_io_open),
        mock.patch("os.open", guarded_os_open),
    ]
    for patcher in patches:
        patcher.start()
    return patches, denials


PRIVATE_READ_PATCHES, PRIVATE_READ_DENIALS = _arm_private_root_read_guard()

# Keep configuration nonempty without opening the private root config.py.
import model_config  # noqa: E402

_DUMMY_CONFIG = types.ModuleType("config")
for _name in dir(model_config):
    if _name.isupper():
        setattr(_DUMMY_CONFIG, _name, getattr(model_config, _name))
_DUMMY_CONFIG.OPENAI_API_KEY = "DUMMY_OPENAI_KEY_FOR_PC_ACTION_PARSER_TEST"
_DUMMY_CONFIG.OPENROUTER_API_KEY = "DUMMY_OPENROUTER_KEY_FOR_PC_ACTION_PARSER_TEST"
sys.modules["config"] = _DUMMY_CONFIG

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
            "Cure Wounds using one 1st-level spell slot on Merisiel for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(result["kind"], "healing")
        self.assertEqual(result["target_name"], "Merisiel")
        self.assertEqual(result["parsed_heal_amount"], 8)
        self.assertEqual(len(result["character_updates"]), 2)  # heal + slot spend
        self.assertEqual(
            result["character_updates"][1]["ops"][0]["level"], "level1"
        )

    def test_mass_healing_word_does_not_fall_through_to_healing_word(self):
        result = parse_pc_phase_action(
            "Mass Healing Word on Merisiel for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertEqual(result["fallback_reason"], "heal_spell_mechanics_unsupported")
        self.assertEqual(result["character_updates"], [])
        self.assertIsNone(result["ledger_event"])

    def test_undeclared_slot_uses_lowest_available_at_or_above_spell_level(self):
        caster_state = deepcopy(FAKE_CASTING_STATE)
        caster_state["spellcasting"]["spellSlots"]["level1"]["current"] = 0
        caster_state["spellcasting"]["spellSlots"]["level2"]["current"] = 1
        with mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=lambda name: deepcopy(
                caster_state if name == "Acheron" else FAKE_HEAL_TARGET_STATE
            ),
        ):
            result = parse_pc_phase_action(
                "Healing Word on Merisiel for 5",
                SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
            )
        self.assertTrue(result["handled"])
        self.assertEqual(result["character_updates"][1]["ops"][0]["level"], "level2")

    def test_undeclared_slot_falls_back_when_no_eligible_slot_is_available(self):
        caster_state = deepcopy(FAKE_CASTING_STATE)
        for slot in caster_state["spellcasting"]["spellSlots"].values():
            slot["current"] = 0
        with mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=lambda name: deepcopy(
                caster_state if name == "Acheron" else FAKE_HEAL_TARGET_STATE
            ),
        ):
            result = parse_pc_phase_action(
                "Cure Wounds on Merisiel for 7",
                SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
            )
        self.assertFalse(result["handled"])
        self.assertEqual(result["fallback_reason"], "heal_slot_unavailable")
        self.assertEqual(result["character_updates"], [])

    def test_multiple_declared_slot_levels_fall_back(self):
        result = parse_pc_phase_action(
            "Healing Word using a 1st-level spell slot, or a 2nd-level spell slot, on Merisiel for 5",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertEqual(result["fallback_reason"], "heal_spell_slot_unresolved")
        self.assertEqual(result["character_updates"], [])

    def test_declared_healing_spell_rejects_below_minimum_slot_level(self):
        result = parse_pc_phase_action(
            "Cure Wounds using one 0th-level spell slot on Merisiel for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertEqual(
            result["fallback_reason"], "heal_spell_slot_level_mismatch"
        )
        self.assertEqual(result["character_updates"], [])

    def test_declared_healing_spell_requires_that_exact_slot_to_be_available(self):
        result = parse_pc_phase_action(
            "Healing Word using a 2nd-level spell slot on Merisiel for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertEqual(result["fallback_reason"], "heal_slot_unavailable")
        self.assertEqual(result["character_updates"], [])

    def test_declared_healing_spell_rejects_non_5e_slot_levels(self):
        caster_state = deepcopy(FAKE_CASTING_STATE)
        caster_state["spellcasting"]["spellSlots"]["level10"] = {
            "current": 1, "max": 1
        }
        with mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=lambda name: deepcopy(
                caster_state if name == "Acheron" else FAKE_HEAL_TARGET_STATE
            ),
        ):
            result = parse_pc_phase_action(
                "Healing Word using a 10th-level spell slot on Merisiel for 8",
                SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
            )
        self.assertFalse(result["handled"])
        self.assertEqual(
            result["fallback_reason"], "heal_spell_slot_level_mismatch"
        )
        self.assertEqual(result["character_updates"], [])

    def test_declared_single_target_spell_rejects_multiple_targets(self):
        result = parse_pc_phase_action(
            "Cure Wounds using one 1st-level spell slot on Merisiel and Kira for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertEqual(result["fallback_reason"], "heal_target_set_unsupported")
        self.assertEqual(result["character_updates"], [])

    def test_declared_healing_target_requires_exact_identity(self):
        result = parse_pc_phase_action(
            "Cure Wounds using one 1st-level spell slot on Merisiel's ally for 8",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertFalse(result["handled"])
        self.assertEqual(result["fallback_reason"], "heal_target_unresolved")
        self.assertEqual(result["character_updates"], [])

    def test_upcast_healing_word_spends_the_declared_slot_level(self):
        caster_state = deepcopy(FAKE_CASTING_STATE)
        caster_state["spellcasting"]["spellSlots"]["level2"]["current"] = 1
        with mock.patch(
            "utils.combat_pc_action_parser.get_character_state",
            side_effect=lambda name: deepcopy(
                caster_state if name == "Acheron" else FAKE_HEAL_TARGET_STATE
            ),
        ):
            result = parse_pc_phase_action(
                "Healing Word using a 2nd-level spell slot on Merisiel for 8",
                SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
            )
        self.assertTrue(result["handled"])
        self.assertEqual(result["character_updates"][1]["ops"][0]["level"], "level2")

    def test_heal_no_spell_keyword_no_slot_spend(self):
        result = parse_pc_phase_action(
            "heal merisiel for 5",
            SAMPLE_ENCOUNTER, SAMPLE_PARTY, "Acheron"
        )
        self.assertTrue(result["handled"])
        self.assertEqual(len(result["character_updates"]), 1)  # just healing, no slot

    def test_heal_unclear_amount_falls_back(self):
        result = parse_pc_phase_action(
            "Cure Wounds using one 1st-level spell slot on Merisiel",
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
                "Cure Wounds using one 1st-level spell slot on Dead Merisiel for 8",
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
                "Cure Wounds using one 1st-level spell slot on Merisiel for 8",
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

    @staticmethod
    def _character_updater_dependency(return_value):
        """Inject only the updater called by the real apply orchestration."""
        module = types.ModuleType("updates.update_character_info")
        module.update_character_info = mock.Mock(return_value=return_value)
        return module, module.update_character_info

    @staticmethod
    def _encounter_updater_dependency(return_value):
        """Inject only the encounter persistence function called by orchestration."""
        module = types.ModuleType("updates.update_encounter")
        module.update_encounter = mock.Mock(return_value=return_value)
        return module, module.update_encounter

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

        updater_module, mock_update_character = self._character_updater_dependency(False)
        encounter_module, mock_update_encounter = self._encounter_updater_dependency(True)
        with mock.patch.dict(sys.modules, {
            "updates.update_character_info": updater_module,
            "updates.update_encounter": encounter_module,
        }):
            ok = apply_pc_phase_parse_result(result, manager, SAMPLE_ENCOUNTER, "ENC-1", "Acheron")

        self.assertFalse(ok)
        mock_update_character.assert_called_once_with(
            "Merisiel", "Healed for 8 HP", ops=[{"op": "hp_delta", "delta": 8}]
        )
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

        updater_module, mock_update_character = self._character_updater_dependency(True)
        encounter_module, mock_update_encounter = self._encounter_updater_dependency(False)
        with mock.patch.dict(sys.modules, {
            "updates.update_character_info": updater_module,
            "updates.update_encounter": encounter_module,
        }):
            ok = apply_pc_phase_parse_result(result, manager, SAMPLE_ENCOUNTER, "ENC-1", "Acheron")

        self.assertFalse(ok)
        mock_update_encounter.assert_called_once()
        mock_update_character.assert_not_called()
        manager.record_pc_phase_event.assert_not_called()


class TestGuardedHarness(unittest.TestCase):
    def test_private_root_reads_are_denied_and_tripwires_untouched(self):
        for filename in ("config.py", "party_tracker.json"):
            private_path = REPO_ROOT / filename
            for operation in (
                lambda path=private_path: builtins.open(path, "r"),
                lambda path=private_path: io.open(path, "r"),
                lambda path=private_path: os.open(path, os.O_RDONLY),
            ):
                with self.assertRaises(_PrivateRootReadDenied):
                    operation()

        self.assertEqual(
            PRIVATE_READ_DENIALS,
            [
                "builtins.open", "io.open", "os.open",
                "builtins.open", "io.open", "os.open",
            ],
        )
        PROCESS_TRIPWIRES.assert_untouched(self)


class TestFeatureFlagConfig(unittest.TestCase):
    """Test that the canary feature flag is enabled in model_config."""

    def test_flag_present_and_enabled_for_canary(self):
        import model_config
        self.assertTrue(hasattr(model_config, "COMBAT_PC_PHASE_NL_FAST_PATH"))
        self.assertTrue(model_config.COMBAT_PC_PHASE_NL_FAST_PATH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
