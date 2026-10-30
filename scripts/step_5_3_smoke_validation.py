#!/usr/bin/env python3
"""Behavioral smoke checks for initiative phase markers and roster integrity."""

import os
import sys
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.combat.multi_pc import sync as combat_sync
from core.combat.turn import (
    RoundTransitionDependencies,
    handle_group_initiative_gate,
    stage_combat_turn_snapshot,
)


def _transition_dependencies(logs, marker):
    return RoundTransitionDependencies(
        apply_opening_batch_marker=marker,
        sync_available=True,
        save_json=lambda *_args: None,
        compress_old_rounds=lambda history, *_args, **_kwargs: history,
        log_debug=lambda message, **_kwargs: logs.append(message),
        log_info=lambda *_args, **_kwargs: None,
        log_warning=lambda *_args, **_kwargs: None,
        bind_history=lambda _history: None,
    )


def test_dmgroup_start_scenario():
    """A DM opening batch stays in the opening round, then returns to PCs."""
    print("\nSCENARIO A: dmGroup start")
    encounter = {
        "encounterId": "smoke-dm",
        "combat_round": 1,
        "initiativeRolls": {"dmGroup": 15},
        "creatures": [
            {"name": "Acheron", "type": "player"},
            {"name": "Merisiel", "type": "player"},
            {"name": "Goblin_1", "type": "enemy"},
        ],
    }
    marker_calls = []

    def apply_marker(data, side):
        marker_calls.append((data, side))
        return combat_sync.apply_opening_batch_marker(data, side)

    gate = handle_group_initiative_gate(
        "/init 12",
        encounter,
        object(),
        {"active_character": "Acheron"},
        apply_opening_batch_marker=apply_marker,
        sync_available=True,
    )
    encounter.update(gate["encounter_updates"])
    logs = []
    completed = stage_combat_turn_snapshot(
        encounter,
        [{"role": "user", "content": "Enemies turn."}],
        phase_before="ENEMY_PHASE",
        phase_after="ENEMY_PHASE",
        enemy_batch_completed=True,
        opening_batch_pending_before=encounter["openingEnemyBatchPending"],
        dependencies=_transition_dependencies(logs, apply_marker),
    )
    passed = (
        gate["winner"] == "dmGroup"
        and gate["needs_enemy_injection"] is True
        and gate["marker_enabled"] is True
        and len(marker_calls) == 1
        and marker_calls[0][1] == "dmGroup"
        and completed.encounter_data["combat_round"] == 1
        and completed.encounter_data["combat_phase"] == "PC_PHASE"
        and completed.encounter_data["openingEnemyBatchPending"] is False
        and encounter["openingEnemyBatchPending"] is True
    )
    print("  %s opening marker set -> enemy batch -> staged marker clear -> PC_PHASE" % (
        "[PASS]" if passed else "[FAIL]"
    ))
    return passed


def test_pcgroup_start_scenario():
    """A PC initiative win clears the marker and does not inject an enemy batch."""
    print("\nSCENARIO B: pcGroup start")
    encounter = {
        "encounterId": "smoke-pc",
        "combat_round": 1,
        "initiativeRolls": {"dmGroup": 10},
        "creatures": [
            {"name": "Acheron", "type": "player"},
            {"name": "Merisiel", "type": "player"},
            {"name": "Orc_1", "type": "enemy"},
        ],
    }
    marker_calls = []

    def apply_marker(data, side):
        marker_calls.append((data, side))
        return combat_sync.apply_opening_batch_marker(data, side)

    gate = handle_group_initiative_gate(
        "/init 18",
        encounter,
        object(),
        {"active_character": "Acheron"},
        apply_opening_batch_marker=apply_marker,
        sync_available=True,
    )
    encounter.update(gate["encounter_updates"])
    passed = (
        gate["winner"] == "pcGroup"
        and gate["needs_enemy_injection"] is False
        and gate["marker_enabled"] is False
        and marker_calls == [(encounter, "pcGroup")]
    )
    passed = passed and encounter["openingEnemyBatchPending"] is False
    passed = passed and encounter["roundStartsWith"] == "pcGroup"
    print("  %s no opening enemy batch; marker clear and PC start" % (
        "[PASS]" if passed else "[FAIL]"
    ))
    return passed


def test_roster_integrity_both_scenarios():
    """Exercise the package-owned additive roster normalizer without file I/O."""
    print("\nROSTER INTEGRITY: package-owned normalizer")
    encounter = {
        "creatures": [
            {"name": "Acheron", "type": "player"},
            {"name": "Goblin_1", "type": "enemy"},
        ],
    }
    party_tracker = {
        "partyMembers": [{"name": "Acheron"}, {"name": "Merisiel"}],
    }

    class Paths:
        def get_character_path(self, name):
            return "fixture-character:" + name

    def load_character(_path):
        return {
            "name": "Merisiel",
            "hitPoints": 16,
            "maxHitPoints": 16,
            "armorClass": 15,
            "status": "alive",
        }

    with patch.object(combat_sync, "safe_json_load", side_effect=load_character), \
            patch.object(combat_sync.random, "randint", return_value=12):
        encounter, changed = combat_sync.normalize_multi_pc_roster(
            encounter, party_tracker, Paths()
        )
        encounter, changed_again = combat_sync.normalize_multi_pc_roster(
            encounter, party_tracker, Paths()
        )

    players = [row["name"] for row in encounter["creatures"] if row.get("type") == "player"]
    passed = (
        changed is True
        and changed_again is False
        and players == ["Acheron", "Merisiel"]
        and len(players) == len(set(players))
        and sum(row.get("type") == "enemy" for row in encounter["creatures"]) == 1
    )
    print("  %s every party member appears once; non-PC roster preserved" % (
        "[PASS]" if passed else "[FAIL]"
    ))
    return passed


if __name__ == "__main__":
    print("Step 5.3 Smoke Validation: Initiative Phase Scenarios")
    results = [
        ("dmGroup Start", test_dmgroup_start_scenario()),
        ("pcGroup Start", test_pcgroup_start_scenario()),
        ("Roster Integrity", test_roster_integrity_both_scenarios()),
    ]
    all_passed = all(passed for _, passed in results)
    for name, passed in results:
        print("  %s: %s" % (name, "PASS" if passed else "FAIL"))
    print("OVERALL: %s" % ("PASS" if all_passed else "FAIL"))
    sys.exit(0 if all_passed else 1)
