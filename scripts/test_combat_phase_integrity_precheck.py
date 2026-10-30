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

    def test_forbidden_actor_diagnostic_matches_attributed_action(self):
        from utils.combat_phase_integrity_precheck import (
            describe_forbidden_actor_rejection,
            validate_combat_phase_integrity_precheck,
        )

        response_json = _build_response(narration="Goblin Alpha attacks Acheron.")
        phase_state = _base_phase_state(forbidden_actors=["Goblin Alpha"])
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json, _build_encounter(), phase_state
        )
        self.assertFalse(valid)
        self.assertEqual(
            reason,
            "Combat phase integrity precheck failed: forbidden actor 'Goblin Alpha' attempted an explicit action in current phase.",
        )
        diagnostic = describe_forbidden_actor_rejection(response_json, phase_state)
        self.assertEqual(diagnostic["matched_name"], "Goblin Alpha")
        self.assertEqual(diagnostic["source_field"], "narration")
        self.assertEqual(diagnostic["matched_verb"], "attacks")
        self.assertEqual(diagnostic["window_excerpt"], "Goblin Alpha attacks Acheron.")

    def test_target_attack_roll_and_negated_action_do_not_attribute_actor(self):
        from utils.combat_phase_integrity_precheck import (
            describe_forbidden_actor_rejection,
            validate_combat_phase_integrity_precheck,
        )

        for narration in (
            "Kira attacks Goblin Alpha. Her attack roll is required.",
            "Goblin Alpha takes no action this turn. Pause for Vitreol attack roll.",
            "Kira does not attack Goblin Alpha.",
            "Kira targets Goblin Alpha, then strikes the adjacent guard.",
        ):
            with self.subTest(narration=narration):
                response_json = _build_response(narration=narration)
                phase_state = _base_phase_state(forbidden_actors=["Goblin Alpha"])
                valid, reason = validate_combat_phase_integrity_precheck(
                    response_json, _build_encounter(), phase_state
                )
                self.assertTrue(valid, reason)
                self.assertIsNone(
                    describe_forbidden_actor_rejection(response_json, phase_state)
                )

    def test_forbidden_actor_future_plan_and_enemy_phase_actions_remain_strict(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        for text in (
            "Have Goblin Alpha attack Acheron.",
            "Goblin Alpha attacks Acheron.",
        ):
            with self.subTest(text=text):
                valid, reason = validate_combat_phase_integrity_precheck(
                    _build_response(plan=text),
                    _build_encounter(),
                    _base_phase_state(
                        current_phase="ENEMY_PHASE", forbidden_actors=["Goblin Alpha"]
                    ),
                )
                self.assertFalse(valid)
                self.assertIn("forbidden actor", reason.lower())

        valid, reason = validate_combat_phase_integrity_precheck(
            _build_response(narration="Acheron attacks Goblin Scout."),
            _build_encounter(),
            _base_phase_state(
                current_phase="ENEMY_PHASE", forbidden_actors=["Acheron"]
            ),
        )
        self.assertFalse(valid)
        self.assertIn("forbidden actor", reason.lower())

    def test_character_update_target_name_is_not_treated_as_actor(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response_json = _build_response(
            actions=[
                {
                    "action": "updateCharacterInfo",
                    "parameters": {
                        "characterName": "Goblin Alpha",
                        "changes": "Kira's attack roll deals damage to Goblin Alpha.",
                    },
                },
                {
                    "action": "updateEncounter",
                    "parameters": {"changes": "Goblin Alpha takes damage and is defeated."},
                },
            ]
        )
        valid, reason = validate_combat_phase_integrity_precheck(
            response_json,
            _build_encounter(),
            _base_phase_state(forbidden_actors=["Goblin Alpha"]),
        )
        self.assertTrue(valid, reason)

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

    def test_trusted_complete_batch_intent_defers_prompt_only_with_actor_action_coverage(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response = _build_response(
            narration="Goblin Scout attacks Acheron. Acheron, what do you do?",
            actions=[{"action": "updateEncounter", "parameters": {"changes": "Goblin Scout attacks Acheron."}}],
        )
        phase = _base_phase_state(
            current_phase="ENEMY_PHASE", pending_enemies=["Goblin Scout"],
            full_enemy_batch_intent=True, forbidden_actors=[],
        )
        self.assertEqual(
            validate_combat_phase_integrity_precheck(response, _build_encounter(), phase),
            (True, ""),
        )

    def test_canonical_subject_boundaries_and_attack_outcomes_cover_only_actual_actors(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        phase = _base_phase_state(
            current_phase="ENEMY_PHASE", pending_enemies=["Goblin", "Blairen"],
            full_enemy_batch_intent=True, forbidden_actors=[], current_round=2,
        )
        valid_changes = (
            "Goblin takes 7 damage, HP 18->11. Blairen hits Goblin. Goblin misses Acheron. Acheron, what do you do?",
            "Goblin misses Acheron. Blairen's longsword attack against Goblin hits. Acheron, what do you do?",
            "Goblin: Attack[14] vs AC 12. Blairen hits Goblin. Acheron, what do you do?",
        )
        for changes in valid_changes:
            with self.subTest(changes=changes):
                response = _build_response(
                    narration=changes,
                    actions=[{"action": "updateEncounter", "parameters": {"changes": changes}}],
                    combat_round=2,
                )
                self.assertEqual(
                    validate_combat_phase_integrity_precheck(response, _build_encounter(), phase),
                    (True, ""),
                )

        false_attribution = (
            "Inactive Goblin attacks Acheron. Blairen hits Goblin. Acheron, what do you do?",
            "Fake Goblin attacks Acheron. Blairen hits Goblin. Acheron, what do you do?",
            "Goblin attacks Blairen. Acheron, what do you do?",
            "Goblin misses Acheron. Blairen acts. Acheron, what do you do?",
        )
        for narration in false_attribution:
            with self.subTest(narration=narration):
                response = _build_response(narration=narration, combat_round=2)
                valid, reason = validate_combat_phase_integrity_precheck(response, _build_encounter(), phase)
                self.assertFalse(valid)
                self.assertIn("before enemy batch completion", reason)

        goblin_only = dict(phase, pending_enemies=["Goblin"])
        exact_second_diagnostic = _build_response(
            narration=("Goblin takes 7 damage, HP 18->11. Goblin's scimitar attack "
                       "against Acheron misses. Acheron, what do you do?"),
            combat_round=2,
        )
        self.assertEqual(
            validate_combat_phase_integrity_precheck(exact_second_diagnostic, _build_encounter(), goblin_only),
            (True, ""),
        )
        underscore_actor = dict(goblin_only, pending_enemies=["Goblin_Scout"])
        underscore_response = _build_response(
            narration="gObLiN Scout misses Acheron. Acheron, what do you do?",
            combat_round=2,
        )
        self.assertEqual(
            validate_combat_phase_integrity_precheck(underscore_response, _build_encounter(), underscore_actor),
            (True, ""),
        )

    def test_batch_handoff_round_type_range_and_opening_marker_are_bounded(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        phase = _base_phase_state(
            current_phase="ENEMY_PHASE", pending_enemies=["Goblin Scout"],
            full_enemy_batch_intent=True, forbidden_actors=[], pc_phase_complete=True,
            current_round=2,
        )
        base = _build_response(
            narration="Goblin Scout misses Acheron. Acheron, what do you do?",
            combat_round=2,
        )
        self.assertEqual(validate_combat_phase_integrity_precheck(base, _build_encounter(), phase), (True, ""))
        legal_next = dict(base, combat_round=3)
        self.assertEqual(validate_combat_phase_integrity_precheck(legal_next, _build_encounter(), phase), (True, ""))

        for invalid_round in (-1, 4, "3", True, 2.0, None):
            response = dict(base)
            if invalid_round is None:
                response.pop("combat_round", None)
            else:
                response["combat_round"] = invalid_round
            with self.subTest(round=invalid_round):
                valid, reason = validate_combat_phase_integrity_precheck(response, _build_encounter(), phase)
                self.assertFalse(valid)
                self.assertIn("before enemy batch completion", reason)

        opening = dict(phase, opening_batch_pending=True)
        self.assertEqual(validate_combat_phase_integrity_precheck(base, _build_encounter(), opening), (True, ""))
        valid, reason = validate_combat_phase_integrity_precheck(legal_next, _build_encounter(), opening)
        self.assertFalse(valid)
        self.assertIn("before enemy batch completion", reason)

    def test_batch_intent_does_not_accept_candidate_claims_or_roster_and_victim_mentions(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        phase = _base_phase_state(
            current_phase="ENEMY_PHASE", pending_enemies=["Goblin Scout", "Goblin Archer"],
            full_enemy_batch_intent=True, forbidden_actors=[],
        )
        responses = (
            _build_response(narration="Goblin Scout attacks Acheron. Acheron, what do you do?",
                            actions=[{"action": "complete_enemy_batch", "parameters": {"complete": True}}]),
            _build_response(plan="Turn order: Goblin Scout, Goblin Archer. Enemy batch complete.",
                            narration="Acheron, what do you do?"),
            _build_response(narration="Goblin Scout attacks Goblin Archer. Acheron, what do you do?"),
        )
        for response in responses:
            with self.subTest(response=response):
                valid, reason = validate_combat_phase_integrity_precheck(response, _build_encounter(), phase)
                self.assertFalse(valid)
                self.assertIn("before enemy batch completion", reason)

    def test_legacy_or_noncanonical_intent_remains_strict_and_pc_action_guard_precedes_deferral(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        response = _build_response(narration="Acheron attacks Goblin Scout. Goblin Scout attacks Acheron. Acheron, what do you do?")
        for phase in (
            _base_phase_state(current_phase="ENEMY_PHASE", pending_enemies=["Goblin Scout"], forbidden_actors=[]),
            _base_phase_state(current_phase="ENEMY_PHASE", pending_enemies=["Goblin Scout"],
                              full_enemy_batch_intent=True, forbidden_actors=["Acheron"]),
        ):
            valid, reason = validate_combat_phase_integrity_precheck(response, _build_encounter(), phase)
            self.assertFalse(valid)
            expected = "forbidden actor" if "Acheron" in phase["forbidden_actors"] else "before enemy batch completion"
            self.assertIn(expected, reason)

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
