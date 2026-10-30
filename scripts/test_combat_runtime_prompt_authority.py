# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - Combat Runtime Prompt Authority Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Source-contract tests for compressed combat prompt runtime authority.
"""

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCombatRuntimePromptAuthority(unittest.TestCase):
    """Ensure multi-PC combat runtime paths use compressed prompt sources."""

    @classmethod
    def setUpClass(cls):
        combat_manager_path = os.path.join(
            REPO_ROOT,
            "core",
            "combat",
            "combat_manager.py",
        )

        with open(combat_manager_path, "r", encoding="utf-8") as file_handle:
            cls.combat_manager_source = file_handle.read()
        bootstrap_path = os.path.join(REPO_ROOT, "core", "combat", "bootstrap.py")
        with open(bootstrap_path, "r", encoding="utf-8") as file_handle:
            cls.bootstrap_source = file_handle.read()
        turn_path = os.path.join(REPO_ROOT, "core", "combat", "turn.py")
        with open(turn_path, "r", encoding="utf-8") as file_handle:
            cls.turn_source = file_handle.read()
        validation_path = os.path.join(REPO_ROOT, "core", "combat", "validation.py")
        with open(validation_path, "r", encoding="utf-8") as file_handle:
            cls.validation_source = file_handle.read()

    def test_multipc_simulation_uses_compressed_prompt_path(self):
        self.assertTrue(
            'prompt_file = "combat/combat_sim_prompt_multipc_compressed.txt"'
            in self.bootstrap_source,
            msg="Multi-PC sim runtime should assign compressed prompt path directly.",
        )

    def test_multipc_simulation_does_not_assign_uncompressed_prompt_path(self):
        self.assertFalse(
            'prompt_file = "combat/combat_sim_prompt_multipc.txt"'
            in self.bootstrap_source,
            msg="Multi-PC sim runtime should not assign uncompressed prompt path as live authority.",
        )

    def test_multipc_validation_uses_compressed_prompt_path(self):
        self.assertTrue(
            "validation_prompt = read_prompt_from_file('combat/combat_validation_prompt_multipc_compressed.txt')"
            in self.validation_source,
            msg="Multi-PC validation runtime should load compressed validator prompt.",
        )

    def test_multipc_validation_does_not_load_uncompressed_prompt_path(self):
        self.assertFalse(
            "validation_prompt = read_prompt_from_file('combat/combat_validation_prompt_multipc.txt')"
            in self.validation_source,
            msg="Multi-PC validation runtime should not load uncompressed validator prompt as live authority.",
        )

    def test_single_player_simulation_default_path_remains_original(self):
        self.assertTrue(
            'prompt_file = "combat/combat_sim_prompt.txt"' in self.bootstrap_source,
            msg="Single-player sim path should retain original default prompt file path.",
        )

    def test_single_player_validation_retains_toggle_based_paths(self):
        self.assertTrue(
            "validation_prompt = read_prompt_from_file('combat/combat_validation_prompt_compressed.txt')"
            in self.validation_source,
            msg="Single-player validation should retain compressed-path toggle branch.",
        )
        self.assertTrue(
            "validation_prompt = read_prompt_from_file('combat/combat_validation_prompt.txt')"
            in self.validation_source,
            msg="Single-player validation should retain uncompressed-path toggle branch.",
        )
        self.assertTrue(
            "elif USE_COMPRESSED_COMBAT:" in self.validation_source,
            msg="Single-player validation should retain USE_COMPRESSED_COMBAT toggle gate.",
        )

    def test_tabletop_phase_sync_touchpoints_remain_present(self):
        self.assertTrue(
            "multi_pc_manager.get_remaining_enemies_for_round()"
            in self.validation_source,
            msg="Pending-enemy phase sync touchpoint should remain present.",
        )

    def test_round_start_dm_group_stages_marker_through_sync_dependency(self):
        from core.combat.turn import RoundTransitionDependencies, stage_combat_turn_snapshot

        encounter = {
            "combat_round": 1,
            "roundStartsWith": "dmGroup",
            "openingEnemyBatchPending": False,
            "combat_phase": "ENEMY_PHASE",
        }
        calls = []
        logs = []

        def apply_marker(projection, starts_with):
            projection["openingEnemyBatchPending"] = starts_with == "dmGroup"
            calls.append((projection, starts_with))
            return projection["openingEnemyBatchPending"]

        result = stage_combat_turn_snapshot(
            encounter,
            [{"role": "user", "content": "Enemies turn."}],
            phase_before="ENEMY_PHASE",
            phase_after="ENEMY_PHASE",
            enemy_batch_completed=True,
            opening_batch_pending_before=False,
            dependencies=RoundTransitionDependencies(
                apply_opening_batch_marker=apply_marker,
                sync_available=True,
                save_json=lambda *_args: self.fail("Staging must not persist encounter state"),
                compress_old_rounds=lambda history, *_args, **_kwargs: history,
                log_debug=lambda message, **kwargs: logs.append((message, kwargs)),
                log_info=lambda *_args, **_kwargs: None,
                log_warning=lambda *_args, **_kwargs: None,
                bind_history=lambda _history: None,
            ),
        )

        self.assertEqual(result.encounter_data["combat_round"], 2)
        self.assertEqual(result.encounter_data["combat_phase"], "ENEMY_PHASE")
        self.assertTrue(result.encounter_data["openingEnemyBatchPending"])
        self.assertEqual(calls, [(result.encounter_data, "dmGroup")])
        self.assertEqual(encounter["combat_round"], 1)
        self.assertFalse(encounter["openingEnemyBatchPending"])
        self.assertEqual(
            [message for message, _kwargs in logs if message.startswith(("PHASE_MARKER:", "STATE_CHANGE:"))],
            [
                "STATE_CHANGE: Applied roundStartsWith=dmGroup -> ENEMY_PHASE start",
                "PHASE_MARKER: Set openingEnemyBatchPending=True via round-start dmGroup path",
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
