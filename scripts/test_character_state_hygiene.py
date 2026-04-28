# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Regression tests for deterministic character life-state hygiene."""

import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


from utils.character_state_hygiene import normalize_life_state_fields, is_mechanically_dead


class TestCharacterStateHygiene(unittest.TestCase):
    def test_positive_hp_clears_stale_unconscious_state(self):
        character_data = {
            "name": "Lidda Underbough",
            "hitPoints": 9,
            "maxHitPoints": 9,
            "status": "unconscious",
            "condition": "unconscious",
            "condition_affected": ["unconscious", "poisoned"],
            "deathSaves": {"successes": 2, "failures": 1},
        }

        normalized = normalize_life_state_fields(character_data)

        self.assertEqual(normalized["status"], "alive")
        self.assertEqual(normalized["condition"], "poisoned")
        self.assertEqual(normalized["condition_affected"], ["poisoned"])
        self.assertEqual(normalized["deathSaves"], {"successes": 0, "failures": 0})

    def test_zero_hp_enforces_unconscious_state_until_dead(self):
        character_data = {
            "name": "Lidda Underbough",
            "hitPoints": 0,
            "maxHitPoints": 9,
            "status": "alive",
            "condition": "none",
            "condition_affected": [],
            "deathSaves": {"successes": 0, "failures": 1},
        }

        normalized = normalize_life_state_fields(character_data)

        self.assertEqual(normalized["status"], "unconscious")
        self.assertEqual(normalized["condition"], "unconscious")
        self.assertIn("unconscious", normalized["condition_affected"])

    def test_three_failures_enforce_dead_state(self):
        character_data = {
            "name": "Lidda Underbough",
            "hitPoints": 0,
            "maxHitPoints": 9,
            "status": "unconscious",
            "condition": "unconscious",
            "condition_affected": ["unconscious"],
            "deathSaves": {"successes": 1, "failures": 3},
        }

        normalized = normalize_life_state_fields(character_data)

        self.assertEqual(normalized["status"], "dead")
        self.assertEqual(normalized["condition"], "none")
        self.assertEqual(normalized["condition_affected"], [])


class TestCharacterStateHygieneSourceContracts(unittest.TestCase):
    def test_pc_manager_normalizes_loaded_character_state(self):
        with open(os.path.join(REPO_ROOT, "utils", "pc_manager.py"), "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn("normalize_life_state_fields", content)

    def test_combat_manager_normalizes_prompt_character_state(self):
        with open(os.path.join(REPO_ROOT, "core", "managers", "combat_manager.py"), "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn("char_data = normalize_life_state_fields(dict(char_data))", content)
        self.assertIn("player_data = normalize_life_state_fields(player_data)", content)


class TestRestDeadSkipContract(unittest.TestCase):
    """Source-contract: rest handler skips mechanically dead characters."""

    def test_rest_dead_skip_guard_exists(self):
        with open(os.path.join(REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("is_mechanically_dead", content)
        self.assertIn('"skip_reason": "dead"', content)

    def test_rest_dead_skip_no_mutation(self):
        """Verifies the guard returns structured result without calling update_character_info."""
        with open(os.path.join(REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("skipped", content)
        self.assertIn("skip_reason", content)


class TestDmNoteDeadVisibilityContract(unittest.TestCase):
    """Source-contract: DM Note shows dead-state status."""

    def test_full_stats_has_dead_tag(self):
        with open(os.path.join(REPO_ROOT, "utils", "multi_pc_dm_note.py"), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("[DEAD]", content)

    def test_full_stats_has_death_saves(self):
        with open(os.path.join(REPO_ROOT, "utils", "multi_pc_dm_note.py"), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("Death Saves:", content)

    def test_condensed_has_dead_tag(self):
        with open(os.path.join(REPO_ROOT, "utils", "multi_pc_dm_note.py"), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("[DEAD]", content)


class TestSyncDeathSaveDeadAuthorityContract(unittest.TestCase):
    """Source-contract: _sync_death_save_state uses is_mechanically_dead."""

    def test_sync_death_save_imports_is_mechanically_dead(self):
        with open(os.path.join(REPO_ROOT, "updates", "update_character_info.py"), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("from utils.character_state_hygiene import is_mechanically_dead", content)

    def test_sync_death_save_checks_dead_first(self):
        with open(os.path.join(REPO_ROOT, "updates", "update_character_info.py"), "r", encoding="utf-8") as handle:
            content = handle.read()
        # In _sync_death_save_state, the dead check must come before the positive-HP check
        # Find the function body and verify ordering
        func_start = content.find("def _sync_death_save_state")
        func_body = content[func_start:func_start + 1500]
        dead_check_pos = func_body.find("is_mechanically_dead")
        hp_check_pos = func_body.find("if current_hp > 0")
        self.assertGreater(dead_check_pos, -1, "is_mechanically_dead check not found")
        self.assertGreater(hp_check_pos, -1, "current_hp check not found")
        self.assertLess(dead_check_pos, hp_check_pos,
                        "is_mechanically_dead check must precede current_hp > 0 check")


class TestDeadMechanicalAuthority(unittest.TestCase):
    """Dead-state stickiness: positive HP cannot revive a mechanically dead character."""

    def test_explicitly_dead_with_positive_hp_stays_dead(self):
        """Task 1.4: status='dead' wins over current_hp > 0."""
        character_data = {
            "name": "Vitreol",
            "hitPoints": 42,
            "maxHitPoints": 42,
            "status": "dead",
            "condition": "unconscious",
            "condition_affected": ["unconscious", "poisoned"],
            "deathSaves": {"successes": 0, "failures": 3},
        }

        normalized = normalize_life_state_fields(character_data)

        self.assertEqual(normalized["status"], "dead")
        self.assertEqual(normalized["hitPoints"], 0, "Dead characters must have HP clamped to 0")
        self.assertEqual(normalized["condition"], "none")
        self.assertEqual(normalized["condition_affected"], [])
        self.assertEqual(normalized["deathSaves"]["failures"], 3)

    def test_three_death_save_failures_with_positive_hp_stays_dead(self):
        """Task 1.4: 3 failed death saves wins over current_hp > 0."""
        character_data = {
            "name": "Anselara",
            "hitPoints": 20,
            "maxHitPoints": 30,
            "status": "unconscious",
            "condition": "unconscious",
            "condition_affected": ["unconscious"],
            "deathSaves": {"successes": 0, "failures": 3},
        }

        normalized = normalize_life_state_fields(character_data)

        self.assertEqual(normalized["status"], "dead")
        self.assertEqual(normalized["hitPoints"], 0, "Dead characters must have HP clamped to 0")
        self.assertEqual(normalized["condition"], "none")
        self.assertEqual(normalized["condition_affected"], [])
        self.assertEqual(normalized["deathSaves"]["failures"], 3)

    def test_is_mechanically_dead_returns_true_for_dead_status(self):
        """is_mechanically_dead returns True when status='dead'."""
        data = {"status": "dead", "deathSaves": {"successes": 0, "failures": 0}}
        self.assertTrue(is_mechanically_dead(data))

    def test_is_mechanically_dead_returns_true_for_three_failures(self):
        """is_mechanically_dead returns True when failures >= 3."""
        data = {"status": "unconscious", "deathSaves": {"successes": 0, "failures": 3}}
        self.assertTrue(is_mechanically_dead(data))

    def test_is_mechanically_dead_returns_false_for_alive(self):
        """is_mechanically_dead returns False for a normal alive character."""
        data = {"status": "alive", "deathSaves": {"successes": 1, "failures": 1}}
        self.assertFalse(is_mechanically_dead(data))

    def test_stale_unconscious_repair_preserved_for_living_positive_hp(self):
        """Task 1.5: Non-dead unconscious character with HP > 0 is normalized to alive."""
        character_data = {
            "name": "Lidda Underbough",
            "hitPoints": 9,
            "maxHitPoints": 9,
            "status": "unconscious",
            "condition": "unconscious",
            "condition_affected": ["unconscious", "poisoned"],
            "deathSaves": {"successes": 2, "failures": 1},
        }

        normalized = normalize_life_state_fields(character_data)

        self.assertEqual(normalized["status"], "alive")
        self.assertEqual(normalized["condition"], "poisoned")
        self.assertEqual(normalized["condition_affected"], ["poisoned"])
        self.assertEqual(normalized["deathSaves"], {"successes": 0, "failures": 0})


class TestResurrectCharacterContract(unittest.TestCase):
    """Task 1.3: resurrectCharacter action dispatch and contract."""

    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_action_constant_exists(self):
        with open(os.path.join(self.REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('ACTION_RESURRECT = "resurrectCharacter"', content)

    def test_dispatch_block_exists(self):
        with open(os.path.join(self.REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("ACTION_RESURRECT", content)
        self.assertIn("_process_resurrect_character", content)

    def test_handler_function_has_required_params(self):
        with open(os.path.join(self.REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('"character"', content)
        self.assertIn('required', content)

    def test_handler_references_is_mechanically_dead(self):
        with open(os.path.join(self.REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("is_mechanically_dead", content)

    def test_prompt_compressed_mentions_resurrect_character(self):
        with open(os.path.join(self.REPO_ROOT, "prompts", "system_prompt_compressed.txt"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("resurrectCharacter", content)

    def test_prompt_full_mentions_resurrect_character(self):
        with open(os.path.join(self.REPO_ROOT, "prompts", "system_prompt.txt"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("resurrectCharacter", content)

    def test_compressed_validation_prompt_has_action_available(self):
        with open(os.path.join(self.REPO_ROOT, "prompts", "validation", "validation_prompt_compressed.txt"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("action_available", content)

    def test_full_validation_prompt_mentions_resurrect_character(self):
        with open(os.path.join(self.REPO_ROOT, "prompts", "validation", "validation_prompt.txt"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("resurrectCharacter", content)

    # === Patch 1 and 2 contract locks ===

    def test_update_text_includes_explicit_hit_points(self):
        """Patch 1: hitPoints value is included in the LLM prose update text."""
        with open(os.path.join(self.REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("{hit_points}", content)
        self.assertIn("hit points via", content)

    def test_handler_persists_supernatural_metadata(self):
        """Patch 2: _supernatural_metadata is written to character file after resurrection."""
        with open(os.path.join(self.REPO_ROOT, "core", "ai", "action_handler.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_supernatural_metadata", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
