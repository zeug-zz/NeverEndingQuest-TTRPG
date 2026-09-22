# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free, fixed combat fixtures for latency baseline tests."""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.ai.combat_compressor import CombatUserMessageCompressor
from core.managers.multi_pc_combat import MultiPCCombatManager
from utils.combat_latency_trace import (
    set_trace_context,
    trace_file_operation,
    trace_stage,
)
from utils.file_operations import safe_read_json, safe_write_json


PC_NAMES = ["Acheron", "Merisiel", "Kira", "Vitreol"]
ENEMY_NAMES = ["Goblin Alpha", "Goblin Beta"]
PC_INITIATIVES = {"Acheron": 20, "Merisiel": 18, "Kira": 16, "Vitreol": 14}
ENEMY_INITIATIVES = {"Goblin Alpha": 10, "Goblin Beta": 8}
ONE_PC_NAME = "Acheron"
ONE_PC_ENEMY_NAME = "Goblin"
ONE_PC_INITIATIVE = 18
ONE_PC_ENEMY_INITIATIVE = 10


def _character_payload(name: str, initiative: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "player",
        "character_type": "player",
        "hitPoints": 20,
        "maxHitPoints": 20,
        "armorClass": 14,
        "initiative": initiative,
        "status": "alive",
        "deathSaves": {"successes": 0, "failures": 0},
    }


def _encounter_payload() -> Dict[str, Any]:
    return {
        "id": "fixture_mp",
        "encounterId": "fixture_mp",
        "combat_round": 1,
        "initiativeMode": "two_group_phase1",
        "initiativeRolls": {"dmGroup": 12, "pcGroup": 18},
        "initiativeWinner": "pcGroup",
        "roundStartsWith": "pcGroup",
        "awaitingPcGroupRoll": False,
        "openingEnemyBatchPending": False,
        "creatures": [
            {
                "name": "Goblin Alpha",
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": ENEMY_INITIATIVES["Goblin Alpha"],
                "armorClass": 12,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "status": "alive",
            },
            {
                "name": "Goblin Beta",
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": ENEMY_INITIATIVES["Goblin Beta"],
                "armorClass": 12,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "status": "alive",
            },
        ],
    }


def _one_pc_encounter_payload() -> Dict[str, Any]:
    """Return the fixed one-PC, one-enemy encounter payload."""
    return {
        "id": "fixture_one_pc",
        "encounterId": "fixture_one_pc",
        "combat_round": 1,
        "initiativeMode": "one_pc_compatible",
        "initiativeRolls": {"dmGroup": 10, "pcGroup": 18},
        "initiativeWinner": "pcGroup",
        "roundStartsWith": "pcGroup",
        "awaitingPcGroupRoll": False,
        "openingEnemyBatchPending": False,
        "creatures": [
            {
                "name": ONE_PC_ENEMY_NAME,
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": ONE_PC_ENEMY_INITIATIVE,
                "armorClass": 12,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "status": "alive",
            }
        ],
    }


def _fixed_queue(manager: MultiPCCombatManager) -> None:
    """Replace random initiative results with the fixture's fixed values."""
    for combatant in manager._turns.turn_queue:
        if combatant.name in PC_INITIATIVES:
            combatant.initiative = PC_INITIATIVES[combatant.name]
        elif combatant.name in ENEMY_INITIATIVES:
            combatant.initiative = ENEMY_INITIATIVES[combatant.name]
    manager._turns.turn_queue.sort(key=lambda item: item.initiative, reverse=True)
    manager._turns.current_turn_index = 0


def _fixed_one_pc_queue(manager: MultiPCCombatManager) -> None:
    """Replace 1-PC party initiative results with the fixture's fixed values."""
    for combatant in manager._turns.turn_queue:
        if combatant.name == ONE_PC_NAME:
            combatant.initiative = ONE_PC_INITIATIVE
        elif combatant.name == ONE_PC_ENEMY_NAME:
            combatant.initiative = ONE_PC_ENEMY_INITIATIVE
    manager._turns.turn_queue.sort(key=lambda item: item.initiative, reverse=True)
    manager._turns.current_turn_index = 0


def build_mp_fixture() -> Dict[str, Any]:
    """Create a sandboxed four-PC fixture and initialize the real manager."""
    tempdir = tempfile.TemporaryDirectory()
    sandbox = Path(tempdir.name)
    previous_cwd = os.getcwd()
    try:
        os.chdir(sandbox)
        (sandbox / "characters").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "fixture_module" / "areas").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "encounters").mkdir(parents=True, exist_ok=True)

        party = {
            "partyMembers": list(PC_NAMES),
            "active_character": PC_NAMES[0],
            "module": "fixture_module",
            "worldConditions": {"activeCombatEncounter": "fixture_mp"},
        }
        safe_write_json("party_tracker.json", party)
        for name in PC_NAMES:
            safe_write_json(
                str(Path("characters") / (name.lower() + ".json")),
                _character_payload(name, PC_INITIATIVES[name]),
            )
        encounter = _encounter_payload()
        safe_write_json("modules/encounters/encounter_fixture_mp.json", encounter)

        manager = MultiPCCombatManager()
        manager.initialize_from_party(party)
        manager.initialize_turn_queue(encounter)
        _fixed_queue(manager)
        trace_path = sandbox / "debug" / "combat_turn_trace.jsonl"
        return {
            "tempdir": tempdir,
            "sandbox": sandbox,
            "manager": manager,
            "encounter": encounter,
            "party": party,
            "trace_path": trace_path,
            "enemy_batches": 0,
            "rounds_completed": 0,
            "command_script": build_command_script(),
        }
    except Exception:
        tempdir.cleanup()
        raise
    finally:
        os.chdir(previous_cwd)


def build_one_pc_fixture() -> Dict[str, Any]:
    """Create a sandboxed one-PC fixture using the minimum-party command path."""
    tempdir = tempfile.TemporaryDirectory()
    sandbox = Path(tempdir.name)
    previous_cwd = os.getcwd()
    try:
        os.chdir(sandbox)
        (sandbox / "characters").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "fixture_module" / "areas").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "encounters").mkdir(parents=True, exist_ok=True)

        party = {
            "partyMembers": [ONE_PC_NAME],
            "active_character": ONE_PC_NAME,
            "module": "fixture_module",
            "worldConditions": {"activeCombatEncounter": "fixture_one_pc"},
        }
        safe_write_json("party_tracker.json", party)
        safe_write_json(
            str(Path("characters") / "acheron.json"),
            _character_payload(ONE_PC_NAME, ONE_PC_INITIATIVE),
        )
        encounter = _one_pc_encounter_payload()
        safe_write_json("modules/encounters/encounter_fixture_one_pc.json", encounter)

        manager = MultiPCCombatManager()
        manager.initialize_from_party(party)
        manager.initialize_turn_queue(encounter)
        _fixed_one_pc_queue(manager)
        trace_path = sandbox / "debug" / "combat_turn_trace.jsonl"
        return {
            "tempdir": tempdir,
            "sandbox": sandbox,
            "manager": manager,
            "encounter": encounter,
            "party": party,
            "trace_path": trace_path,
            "rounds_completed": 0,
            "command_script": build_one_pc_command_script(),
        }
    except Exception:
        tempdir.cleanup()
        raise
    finally:
        os.chdir(previous_cwd)


def build_command_script() -> List[str]:
    """Return the fixed ordered input script used by the MP fixture."""
    commands = ["/init 18"]
    for round_number in range(1, 4):
        for name in PC_NAMES:
            commands.extend(
                [
                    f"{name}: /att Goblin Alpha 20 training blade",
                    f"{name}: /dmg 1 round {round_number}",
                ]
            )
        if round_number == 1:
            commands.append("/end (enemy batch trigger)")
    return commands


def build_one_pc_command_script() -> List[str]:
    """Return the fixed one-round 1-PC party command sequence."""
    return [
        "%s: /att %s 20 training blade" % (ONE_PC_NAME, ONE_PC_ENEMY_NAME),
        "%s: /dmg 1 round 1" % ONE_PC_NAME,
        "/end (enemy phase completion)",
    ]


def _assert_round_invariants(fixture: Dict[str, Any], round_number: int) -> None:
    manager = fixture["manager"]
    pc_names = list(manager.pc_states.keys())
    assert len(pc_names) == 4, "MP fixture round %d: expected four PCs" % round_number
    assert len({_name.lower() for _name in pc_names}) == 4, (
        "MP fixture round %d: duplicate PC roster" % round_number
    )
    assert manager.combat_phase == "ENEMY_PHASE", (
        "MP fixture round %d: PC phase did not complete" % round_number
    )
    queue_names = [combatant.name for combatant in manager._turns.turn_queue]
    for name in PC_NAMES + ENEMY_NAMES:
        assert queue_names.count(name) == 1, (
            "MP fixture round %d: queue actor mismatch for %s" % (round_number, name)
        )


def _exercise_compression_instrumentation(fixture: Dict[str, Any]) -> None:
    """Exercise the production compressor cache and trace hooks without a provider."""
    compressor = CombatUserMessageCompressor(
        cache_file=str(fixture["sandbox"] / "modules" / "conversation_history" / "fixture-cache.json")
    )
    compressor.combat_compressor.compress = lambda content: "fixture-compressed"
    first = compressor.compress_message((0, "fixture combat message"))
    second = compressor.compress_message((0, "fixture combat message"))
    assert first[1] == "fixture-compressed" and first[2] is False, (
        "MP fixture: compression miss did not call the stub"
    )
    assert second[1] == "fixture-compressed" and second[2] is True, (
        "MP fixture: compression hit did not use the cache"
    )


def run_mp_fixture(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Run three fixed rounds through the real multi-PC combat APIs."""
    manager = fixture["manager"]
    encounter = fixture["encounter"]
    previous_cwd = os.getcwd()
    try:
        os.chdir(fixture["sandbox"])
        set_trace_context(mode="mp", fixture="combat_latency_baseline")
        trace_file_operation("read", "fixture_encounter_load")
        assert safe_read_json("modules/encounters/encounter_fixture_mp.json") is not None
        _exercise_compression_instrumentation(fixture)

        for round_number in range(1, 4):
            started_at = time.perf_counter()
            for name in PC_NAMES:
                feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
                    "/att Goblin Alpha 20 training blade", encounter, actor_name=name
                )
                assert skip_llm and feedback, "round %d: attack fast path failed" % round_number
                feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
                    "/dmg 1 round %d" % round_number, encounter, actor_name=name
                )
                assert skip_llm and feedback, "round %d: damage fast path failed" % round_number
                phase_complete = manager.complete_pc_turn(name)
                expected_complete = name == PC_NAMES[-1]
                assert phase_complete == expected_complete, (
                    "round %d: unexpected PC phase completion for %s" % (round_number, name)
                )

            _assert_round_invariants(fixture, round_number)
            trace_stage("fixture_round_%d" % round_number, started_at, mode="mp")
            if round_number == 1:
                enemy_batch = manager.get_remaining_enemies_for_round()
                assert enemy_batch == ENEMY_NAMES, "MP fixture: unexpected enemy batch"
                fixture["enemy_batches"] += 1
                manager._turns.enemy_phase_complete = True
                assert manager.pc_phase_complete and manager._turns.enemy_phase_complete, (
                    "MP fixture round 1: enemy batch phase flags are incoherent"
                )
            else:
                assert manager.pc_phase_complete and not manager._turns.enemy_phase_complete, (
                    "MP fixture round %d: untriggered enemy phase flags are incoherent" % round_number
                )
            fixture["rounds_completed"] += 1
            if round_number < 3:
                manager.start_new_round()

        assert fixture["rounds_completed"] == 3, "MP fixture: expected three rounds"
        assert fixture["enemy_batches"] == 1, "MP fixture: expected one enemy batch"
        assert manager.pc_phase_complete and not manager._turns.enemy_phase_complete, (
            "MP fixture: final phase flags are incoherent"
        )
        return {
            "pc_names": list(manager.pc_states.keys()),
            "queue_names": [combatant.name for combatant in manager._turns.turn_queue],
            "rounds_completed": fixture["rounds_completed"],
            "enemy_batches": fixture["enemy_batches"],
        }
    finally:
        os.chdir(previous_cwd)


def run_one_pc_fixture(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Run exactly one round through the minimum-party tabletop command APIs."""
    manager = fixture["manager"]
    encounter = fixture["encounter"]
    previous_cwd = os.getcwd()
    try:
        os.chdir(fixture["sandbox"])
        set_trace_context(mode="one_pc", fixture="combat_latency_baseline")
        trace_file_operation("read", "fixture_one_pc_encounter_load")
        assert safe_read_json("modules/encounters/encounter_fixture_one_pc.json") is not None

        started_at = time.perf_counter()
        feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
            "/att %s 20 training blade" % ONE_PC_ENEMY_NAME,
            encounter,
            actor_name=ONE_PC_NAME,
        )
        assert skip_llm and feedback, "1-PC party fixture round 1: attack fast path failed"
        feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
            "/dmg 1 round 1",
            encounter,
            actor_name=ONE_PC_NAME,
        )
        assert skip_llm and feedback, "1-PC party fixture round 1: damage fast path failed"
        assert manager.complete_pc_turn(ONE_PC_NAME), (
            "1-PC party fixture round 1: PC phase did not complete"
        )
        assert manager.combat_phase == "ENEMY_PHASE", (
            "1-PC party fixture round 1: phase did not enter enemy phase"
        )
        enemy_batch = manager.get_remaining_enemies_for_round()
        assert enemy_batch == [ONE_PC_ENEMY_NAME], "1-PC party fixture: unexpected enemy batch"
        manager._turns.enemy_phase_complete = True
        assert manager.pc_phase_complete and manager._turns.enemy_phase_complete, (
            "1-PC party fixture round 1: phase flags are incoherent"
        )
        trace_stage("fixture_one_pc_round_1", started_at, mode="one_pc")

        queue_names = [combatant.name for combatant in manager._turns.turn_queue]
        assert queue_names.count(ONE_PC_NAME) == 1, "1-PC party fixture: PC roster mismatch"
        assert queue_names.count(ONE_PC_ENEMY_NAME) == 1, "1-PC party fixture: enemy roster mismatch"
        fixture["rounds_completed"] += 1
        assert fixture["rounds_completed"] == 1, "1-PC party fixture: expected one round"
        return {
            "mode": "one_pc",
            "pc_names": list(manager.pc_states.keys()),
            "enemy_names": enemy_batch,
            "queue_names": queue_names,
            "rounds_completed": fixture["rounds_completed"],
            "pc_phase_complete": manager.pc_phase_complete,
            "enemy_phase_complete": manager._turns.enemy_phase_complete,
        }
    finally:
        os.chdir(previous_cwd)


def print_live_script() -> None:
    """Print the ordered input script for a manual live combat run."""
    for index, command in enumerate(build_command_script(), 1):
        print("%02d. %s" % (index, command))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider-free combat latency fixtures")
    parser.add_argument("--print-script", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--one-pc-self-check", action="store_true")
    args = parser.parse_args()
    if args.print_script:
        print_live_script()
    if args.self_check:
        fixture = build_mp_fixture()
        try:
            result = run_mp_fixture(fixture)
            print("PASS: MP fixture rounds=%d enemy_batches=%d PCs=%d" % (
                result["rounds_completed"], result["enemy_batches"], len(result["pc_names"])
            ))
        finally:
            fixture["tempdir"].cleanup()
    if args.one_pc_self_check:
        fixture = build_one_pc_fixture()
        try:
            result = run_one_pc_fixture(fixture)
            print("PASS: 1-PC party fixture rounds=%d PCs=%d" % (
                result["rounds_completed"], len(result["pc_names"])
            ))
        finally:
            fixture["tempdir"].cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
