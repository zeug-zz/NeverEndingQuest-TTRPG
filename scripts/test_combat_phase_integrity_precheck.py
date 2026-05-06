# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest - combat phase integrity precheck Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0
"""

import os
import sys
import unittest
from typing import Any, Dict, Optional


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _build_encounter(hostiles_alive: bool = True, include_creatures: bool = True) -> Dict[str, Any]:
    if not include_creatures:
        return {}
    status = "alive" if hostiles_alive else "defeated"
    hp = 12 if hostiles_alive else 0
    return {
        "id": "L05-E1",
        "creatures": [
            {
                "name": "Goblin Scout",
                "type": "enemy",
                "status": status,
                "currentHitPoints": hp,
            }
        ],
    }


def _base_phase_state(**overrides: Any) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "current_phase": "PC_PHASE",
        "forbidden_actors": ["Goblin Scout"],
        "pending_enemies": [],
        "pc_phase_complete": True,
        "current_round": 2,
    }
    state.update(overrides)
    return state


def _build_response(
    plan: str = "",
    narration: str = "",
    actions: Optional[list] = None,
    combat_round: int = 2,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan": plan,
        "narration": narration,
        "actions": actions or [],
        "combat_round": combat_round,
    }
    return payload


def _build_already_applied_history(target: str = "Goblin Scout", amount: int = 12, result_hp: int = 0, max_hp: int = 12) -> list:
    return [
        {
            "role": "user",
            "content": (
                f"[ALREADY_APPLIED] [System: Acheron dealt {amount} damage (spear) to {target}. "
                f"Result HP: {result_hp}/{max_hp}.]"
            ),
        }
    ]


class TestCombatPhaseIntegrityPrecheck(unittest.TestCase):
    """Deterministic phase-integrity checks and fail-open behavior."""

    def test_forbidden_actor_action_fails(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(plan="Goblin Scout attacks Acheron with a spear.")
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(current_phase="PC_PHASE", forbidden_actors=["Goblin Scout"]),
        )
        self.assertFalse(valid)
        self.assertIn("forbidden actor", reason.lower())

    def test_forbidden_actor_guard_fail_open_when_list_missing(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(plan="Goblin Scout attacks Acheron with a spear.")
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            {"current_phase": "PC_PHASE"},
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_mid_enemy_batch_stop_fails(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(
            narration="The goblin nocks another arrow. Acheron, what do you do?"
        )
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(current_phase="ENEMY_PHASE", pending_enemies=["Goblin Scout"]),
        )
        self.assertFalse(valid)
        self.assertIn("enemy_phase", reason.lower())

    def test_mid_enemy_batch_guard_passes_when_no_turn_prompt(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(narration="Goblin Scout fires another arrow at Acheron.")
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(current_phase="ENEMY_PHASE", pending_enemies=["Goblin Scout"]),
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_exit_while_hostiles_remain_fails(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "exit",
                    "parameters": {"encounterId": "L05-E1", "reason": "All enemies defeated"},
                }
            ]
        )
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(),
        )
        self.assertFalse(valid)
        self.assertIn("living hostiles remain", reason.lower())

    def test_exit_guard_passes_when_hostiles_defeated(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "exit",
                    "parameters": {"encounterId": "L05-E1", "reason": "All enemies defeated"},
                }
            ]
        )
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=False),
            _base_phase_state(),
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_exit_guard_allows_same_response_final_defeat_ops(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "updateEncounter",
                    "parameters": {
                        "encounterId": "L05-E1",
                        "changes": "Goblin Scout takes 12 damage (HP 12->0) and is now dead.",
                        "ops": [
                            {"op": "hp_delta", "creature": "Goblin Scout", "delta": -12},
                            {"op": "set_status", "creature": "Goblin Scout", "status": "dead"},
                        ],
                    },
                },
                {"action": "exit", "parameters": {"encounterId": "L05-E1", "reason": "All enemies defeated"}},
            ]
        )
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(),
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_exit_guard_rejects_when_simulation_is_indeterminate(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "updateEncounter",
                    "parameters": {
                        "encounterId": "L05-E1",
                        "changes": "Goblin Scout takes damage and is defeated.",
                        "ops": [
                            {"op": "set_hp", "creature": "Goblin Scout", "hp": "eight"},
                        ],
                    },
                },
                {"action": "exit", "parameters": {"encounterId": "L05-E1", "reason": "All enemies defeated"}},
            ]
        )
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(),
        )
        self.assertFalse(valid)
        self.assertIn("exact supported enemy hp_delta, set_hp, or set_status ops", reason.lower())

    def test_exit_guard_fail_open_when_encounter_not_authoritative(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "exit",
                    "parameters": {"encounterId": "L05-E1", "reason": "All enemies defeated"},
                }
            ]
        )
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(include_creatures=False),
            _base_phase_state(),
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_already_applied_duplicate_enemy_hp_delta_is_rejected(self):
        from utils.combat_phase_integrity_precheck import validate_already_applied_enemy_replay_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "updateEncounter",
                    "parameters": {
                        "encounterId": "L05-E1",
                        "changes": "Goblin Scout takes 12 damage (HP 12->0) and is now dead.",
                        "ops": [
                            {"op": "hp_delta", "creature": "Goblin Scout", "delta": -12},
                        ],
                    },
                }
            ]
        )
        valid, reason = validate_already_applied_enemy_replay_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _build_already_applied_history(amount=12, result_hp=0),
        )
        self.assertFalse(valid)
        self.assertIn("duplicate enemy hp_delta", reason.lower())

    def test_already_applied_distinct_new_damage_still_valid(self):
        from utils.combat_phase_integrity_precheck import validate_already_applied_enemy_replay_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "updateEncounter",
                    "parameters": {
                        "encounterId": "L05-E1",
                        "changes": "Goblin Scout takes 5 damage (HP 12->7).",
                        "ops": [
                            {"op": "hp_delta", "creature": "Goblin Scout", "delta": -5},
                        ],
                    },
                }
            ]
        )
        valid, reason = validate_already_applied_enemy_replay_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _build_already_applied_history(amount=12, result_hp=0),
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_round_increment_before_pc_phase_complete_fails(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(combat_round=3)
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(current_round=2, pc_phase_complete=False),
        )
        self.assertFalse(valid)
        self.assertIn("combat_round advanced", reason.lower())

    def test_round_increment_guard_passes_when_pc_phase_complete(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(combat_round=3)
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            _base_phase_state(current_round=2, pc_phase_complete=True),
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_round_increment_guard_fail_open_when_state_missing(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(combat_round=3)
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(hostiles_alive=True),
            {"current_phase": "ENEMY_PHASE"},
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
