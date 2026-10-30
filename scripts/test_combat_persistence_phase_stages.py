# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for extracted combat apply and phase substeps."""

import ast
import builtins
import contextlib
import copy
import inspect
import io
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.combat.persistence import (
    CharacterUpdateDependencies,
    CombatActionDependencies,
    apply_final_character_updates,
    process_combat_action_batch,
    queue_final_character_update,
    sync_multi_pc_character_state,
)
from core.combat import persistence as persistence_owner
from core.combat.turn import (
    RoundTransitionDependencies,
    complete_opening_enemy_batch,
    handle_group_initiative_gate,
    stage_combat_turn_snapshot,
    sync_committed_combat_turn,
)
from scripts.test_llm_router import ProviderTripwire


class GuardDenied(BaseException):
    """Non-catchable-by-Exception sentinel for forbidden fixture writes."""


def _deny(*args, **kwargs):
    raise GuardDenied("filesystem mutation denied by stage test")


@contextlib.contextmanager
def _guarded_stage_execution():
    """Deny real provider/network and all filesystem mutation during fixtures."""
    with contextlib.ExitStack() as stack:
        tripwire = stack.enter_context(ProviderTripwire())
        for owner, name in (
            (builtins, "open"),
            (io, "open"),
            (os, "remove"),
            (os, "unlink"),
            (os, "rename"),
            (os, "replace"),
            (os, "mkdir"),
            (os, "makedirs"),
            (os, "rmdir"),
            (Path, "write_text"),
            (Path, "write_bytes"),
            (Path, "touch"),
            (Path, "mkdir"),
            (Path, "unlink"),
            (Path, "rename"),
            (Path, "replace"),
            (shutil, "rmtree"),
            (shutil, "copyfile"),
        ):
            stack.enter_context(patch.object(owner, name, side_effect=_deny))
        yield tripwire


class FakeActor:
    def __init__(self, name, actor_type):
        self.name = name
        self.type = actor_type


class FakeManager:
    def __init__(self, events, current_actor=None, state=None):
        self.events = events
        self.current_actor = current_actor
        self.pc_states = state or {}
        self.current_pc_name = None
        self.pc_phase_complete = True
        self.current_round = 1

    def start_new_round(self):
        self.events.append("manager:start_new_round")
        self.current_round += 1

    def get_current_actor(self):
        return self.current_actor

    def advance_turn(self):
        self.events.append("manager:advance_turn")
        self.current_actor = FakeActor("PC-2", "pc")
        return self.current_actor


class CombatPersistencePhaseStageTests(unittest.TestCase):
    def test_trace_off_skips_encounter_projection_without_mutating_context(self):
        with _guarded_stage_execution() as tripwire:
            encounter = {"encounterId": "fixture", "creatures": [
                {"name": "Goblin", "type": "enemy", "currentHitPoints": 20},
            ]}
            original = copy.deepcopy(encounter)
            calls = []
            dependencies = CombatActionDependencies(
                queue_character_update=Mock(),
                update_encounter=lambda *_args, **_kwargs: (calls.append("updater") or encounter),
                normalize_encounter_status=lambda data: data,
                sync_non_pc_queue_state=Mock(), log_info=Mock(), log_debug=Mock(),
                log_error=Mock(), log_warning=Mock(), calculate_xp=lambda: ("", 0),
                save_json=Mock(), active_character_update_available=False,
                emit_combat_event=Mock(), get_current_actor=Mock(), advance_turn=Mock(),
                get_pc_state=Mock(), pc_acted_status="acted", npc_combatant_type="npc",
                pc_combatant_type="pc", check_all_monsters_defeated=lambda _data: False,
            )
            with patch.object(persistence_owner, "trace_enabled", return_value=False), \
                    patch.object(persistence_owner, "_bounded_encounter_hp_projection",
                                 side_effect=AssertionError("trace-off projection called")):
                result = process_combat_action_batch(
                    [{"action": "updateEncounter", "parameters": {"changes": "metadata"}}],
                    encounter, {}, encounter_id="fixture", conversation_history=[],
                    conversation_history_file="history.json", multi_pc_manager=None,
                    party_tracker_data={}, is_combat_ending=False, dependencies=dependencies,
                )
            self.assertEqual(calls, ["updater"])
            self.assertEqual(encounter, original)
            self.assertEqual(result.encounter_data, original)
            tripwire.assert_untouched(self)

    def test_named_pc_schema_and_actual_hp_apply_are_traced(self):
        with _guarded_stage_execution() as tripwire:
            from scripts import combat_latency_fixtures as fixtures
            record = fixtures.build_capture_character_payload("Acheron", 18)
            self.assertEqual((record["hitPoints"], record["maxHitPoints"], record["armorClass"],
                              record["initiative"], record["deathSaves"]),
                             (20, 20, 14, 18, {"successes": 0, "failures": 0}))
            self.assertEqual(record["experience_points"], 0)

            state = {"name": "Acheron", "hitPoints": 20, "maxHitPoints": 20}
            trace = []

            def persist(_name, _changes, ops=None):
                self.assertEqual(ops, [{"op": "hp_delta", "delta": -8}])
                state["hitPoints"] += ops[0]["delta"]
                return True

            with patch.object(persistence_owner, "trace_enabled", return_value=True), \
                    patch.object(persistence_owner, "trace_combat_observation",
                                 side_effect=lambda event, **fields: trace.append((event, fields))):
                apply_final_character_updates(
                    {"Acheron": [{"changes": "", "ops": [{"op": "hp_delta", "delta": -8}]}]},
                    object(),
                    CharacterUpdateDependencies(
                        update_character_info=persist, normalize_character_name=lambda name: name.lower(),
                        safe_json_load=lambda _path: dict(state),
                        sync_character_state=lambda manager, name: sync_multi_pc_character_state(
                            manager, name, CharacterUpdateDependencies(
                                persist, lambda value: value.lower(), lambda _path: dict(state),
                                lambda _manager, _name: None, Mock(), Mock(), Mock(),
                            )),
                        log_info=Mock(), log_debug=Mock(), log_error=Mock(),
                    ),
                )
            result = next(fields for event, fields in trace if event == "combat_apply_result")
            persisted = next(fields for event, fields in trace if event == "combat_apply_persisted_state")
            self.assertTrue(result["applied"])
            self.assertEqual((persisted["persisted_state"]["hitPoints"], state["hitPoints"]), (12, 12))
            tripwire.assert_untouched(self)

    def test_initiative_tie_selects_dm_group_and_opens_marker(self):
        encounter = {"initiativeRolls": {"dmGroup": 10}}
        calls = []
        result = handle_group_initiative_gate(
            "/init 10",
            encounter,
            FakeManager([]),
            {"partyMembers": ["Acheron"]},
            apply_opening_batch_marker=lambda data, winner: (calls.append((data, winner)), True)[1],
            sync_available=True,
        )
        self.assertEqual(result["winner"], "dmGroup")
        self.assertTrue(result["needs_enemy_injection"])
        self.assertEqual(calls, [(encounter, "dmGroup")])

    def test_round_transition_stages_code_owned_round_without_runtime_mutation(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size), _guarded_stage_execution() as tripwire:
                events = []
                encounter = {
                    "combat_round": 1,
                    "roundStartsWith": "dmGroup",
                    "openingEnemyBatchPending": False,
                }
                history = [{"role": "user", "content": "turn"}, {"role": "assistant", "content": "reply"}]
                manager = FakeManager(events) if party_size == 4 else None

                def marker(data, side):
                    events.append(f"marker:{side}")
                    data["openingEnemyBatchPending"] = side == "dmGroup"
                    return side == "dmGroup"

                def save(path, value):
                    events.append(f"save:{path}")

                def compress(messages, round_num, *, keep_recent_rounds):
                    events.append(f"compress:{round_num}:{keep_recent_rounds}")
                    return messages[:1]

                def bind_history(messages):
                    events.append("bind_history")

                result = stage_combat_turn_snapshot(
                    encounter,
                    history,
                    phase_before="ENEMY_PHASE",
                    phase_after="ENEMY_PHASE",
                    enemy_batch_completed=True,
                    opening_batch_pending_before=False,
                    dependencies=RoundTransitionDependencies(
                        marker, party_size == 4, save, compress, Mock(), Mock(), Mock(), bind_history
                    ),
                )
                self.assertEqual(result.encounter_data["combat_round"], 2)
                self.assertEqual(result.encounter_data["current_round"], 2)
                self.assertEqual(result.encounter_data["combat_phase"], "ENEMY_PHASE")
                self.assertTrue(result.encounter_data["openingEnemyBatchPending"])
                self.assertTrue(result.round_advanced)
                self.assertEqual(result.conversation_history, history[:1])
                self.assertEqual(encounter["combat_round"], 1)
                expected_events = (
                    ["marker:dmGroup", "compress:2:1", "bind_history"]
                    if party_size == 4 else ["compress:2:1", "bind_history"]
                )
                self.assertEqual(events, expected_events)
                if manager is not None:
                    self.assertEqual(manager.current_round, 1)
                    self.assertTrue(manager.pc_phase_complete)
                tripwire.assert_untouched(self)

    def test_opening_batch_stays_in_round_and_stages_pc_phase(self):
        with _guarded_stage_execution() as tripwire:
            events = []
            encounter = {
                "combat_round": 3,
                "roundStartsWith": "dmGroup",
                "openingEnemyBatchPending": True,
            }
            result = stage_combat_turn_snapshot(
                encounter,
                [],
                phase_before="ENEMY_PHASE",
                phase_after="ENEMY_PHASE",
                enemy_batch_completed=True,
                opening_batch_pending_before=True,
                dependencies=RoundTransitionDependencies(
                    lambda *_args: False, True, lambda *_args: True,
                    lambda history, *_args, **_kwargs: history,
                    Mock(), Mock(), Mock(), Mock(),
                ),
            )
            self.assertEqual(result.encounter_data["combat_round"], 3)
            self.assertEqual(result.encounter_data["combat_phase"], "PC_PHASE")
            self.assertFalse(result.encounter_data["openingEnemyBatchPending"])
            self.assertFalse(result.round_advanced)
            self.assertEqual(events, [])
            tripwire.assert_untouched(self)

    def test_actions_apply_enemy_immediately_queue_characters_then_phase_then_final_updates(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size), _guarded_stage_execution() as tripwire:
                events = []
                manager = FakeManager(events, current_actor=FakeActor("Scout", "npc")) if party_size == 4 else None
                encounter = {"creatures": [{"name": "Acheron", "type": "player"}, {"name": "Goblin", "type": "enemy", "currentHitPoints": 4}], "openingEnemyBatchPending": True}
                history = []
                party = {"active_character": "Acheron"}
                updates = {}
                forwarded = []

                def save(path, value):
                    events.append("save:" + path)

                def update_encounter(update_id, changes, ops=None):
                    events.append("apply:encounter")
                    forwarded.append((update_id, changes, ops))
                    return {"creatures": [{"name": "Acheron", "type": "player"}, {"name": "Goblin", "type": "enemy", "currentHitPoints": 2}], "openingEnemyBatchPending": True}

                deps = CombatActionDependencies(
                    queue_character_update=lambda *args: (events.append("queue:character"), queue_final_character_update(*args)),
                    update_encounter=update_encounter,
                    normalize_encounter_status=lambda data: (events.append("normalize:encounter"), data)[1],
                    sync_non_pc_queue_state=lambda _manager, _data: (events.append("sync:roster"), True)[1],
                    log_info=Mock(), log_debug=Mock(), log_error=Mock(), log_warning=Mock(),
                    calculate_xp=lambda: ("Acheron gains XP", 10), save_json=save,
                    active_character_update_available=False, emit_combat_event=Mock(),
                    get_current_actor=lambda current: current.get_current_actor(),
                    advance_turn=lambda current: current.advance_turn(),
                    get_pc_state=lambda current, name: current.pc_states.get(name),
                    pc_acted_status="acted", npc_combatant_type="npc", pc_combatant_type="pc",
                    check_all_monsters_defeated=lambda data: any(c.get("type") == "enemy" and c.get("currentHitPoints") == 0 for c in data["creatures"]),
                )
                result = process_combat_action_batch(
                    [
                        {"action": "updateCharacterInfo", "parameters": {"characterName": "Acheron", "ops": [{"op": "hp_delta", "delta": -2}]}},
                        {"action": "updateCharacterInfo", "parameters": {"characterName": "Acheron", "changes": "used one arrow"}},
                        {"action": "updateEncounter", "parameters": {"changes": "Goblin takes 2 damage", "ops": [{"op": "hp_delta", "delta": -2}]}},
                    ], encounter, updates, encounter_id="fixture", conversation_history=history,
                    conversation_history_file="history.json", multi_pc_manager=manager,
                    party_tracker_data=party, is_combat_ending=False, dependencies=deps,
                )
                self.assertFalse(result.is_combat_ending)
                self.assertEqual(events[0], "queue:character")
                self.assertLess(events.index("queue:character"), events.index("apply:encounter"))
                self.assertLess(events.index("apply:encounter"), events.index("normalize:encounter"))
                if party_size == 4:
                    self.assertLess(events.index("normalize:encounter"), events.index("sync:roster"))
                else:
                    self.assertNotIn("sync:roster", events)
                self.assertEqual(forwarded, [("fixture", "Goblin takes 2 damage", [{"op": "hp_delta", "delta": -2}])])
                self.assertIn("Acheron", result.final_character_updates)
                if party_size == 4:
                    self.assertEqual(events.count("manager:advance_turn"), 1)
                    self.assertIn("save:party_tracker.json", events)
                else:
                    self.assertNotIn("manager:advance_turn", events)

                complete_opening_enemy_batch(
                    result.encounter_data, manager, encounter_id="fixture", save_json=save, debug=Mock()
                )
                events.append("phase:postbatch-done")
                apply_final_character_updates(
                    result.final_character_updates,
                    None,
                    CharacterUpdateDependencies(
                        update_character_info=lambda name, changes, **kwargs: (events.append("commit:" + ("ops" if kwargs.get("ops") else "prose")), True)[1],
                        normalize_character_name=lambda name: name.lower(),
                        safe_json_load=lambda path: None,
                        sync_character_state=Mock(),
                        log_info=Mock(), log_debug=Mock(), log_error=Mock(),
                    ),
                )
                self.assertLess(events.index("phase:postbatch-done"), events.index("commit:ops"))
                self.assertLess(events.index("commit:ops"), events.index("commit:prose"))
                tripwire.assert_untouched(self)

    def test_acted_pc_bookkeeping_advances_turn_once_after_its_action(self):
        with _guarded_stage_execution() as tripwire:
            events = []
            state = type("State", (), {"status": "acted"})()
            manager = FakeManager(events, current_actor=FakeActor("Acheron", "pc"), state={"Acheron": state})
            manager.current_pc_name = "Acheron"
            deps = CombatActionDependencies(
                queue_character_update=lambda *args: queue_final_character_update(*args),
                update_encounter=Mock(), normalize_encounter_status=lambda data: data,
                sync_non_pc_queue_state=Mock(), log_info=Mock(), log_debug=Mock(), log_error=Mock(), log_warning=Mock(),
                calculate_xp=lambda: ("", 0), save_json=lambda path, value: events.append("save:" + path),
                active_character_update_available=False, emit_combat_event=Mock(),
                get_current_actor=lambda current: current.get_current_actor(),
                advance_turn=lambda current: current.advance_turn(),
                get_pc_state=lambda current, name: current.pc_states.get(name),
                pc_acted_status="acted", npc_combatant_type="npc", pc_combatant_type="pc",
                check_all_monsters_defeated=lambda data: False,
            )
            process_combat_action_batch(
                [{"action": "updateCharacterInfo", "parameters": {"characterName": "Acheron", "changes": "moves"}}],
                {"creatures": []}, {}, encounter_id="fixture", conversation_history=[],
                conversation_history_file="history.json", multi_pc_manager=manager,
                party_tracker_data={"active_character": "Acheron"}, is_combat_ending=False, dependencies=deps,
            )
            self.assertEqual(events, ["manager:advance_turn", "save:party_tracker.json"])
            tripwire.assert_untouched(self)

    def test_failed_immediate_enemy_apply_logs_and_later_character_action_still_runs(self):
        with _guarded_stage_execution() as tripwire:
            events = []
            errors = []
            dependencies = CombatActionDependencies(
                queue_character_update=lambda *args: (events.append("queue:character"), queue_final_character_update(*args)),
                update_encounter=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fixture update failure")),
                normalize_encounter_status=lambda data: data,
                sync_non_pc_queue_state=Mock(), log_info=Mock(), log_debug=Mock(),
                log_error=lambda message, **kwargs: (events.append("log:encounter-error"), errors.append(message)),
                log_warning=Mock(), calculate_xp=lambda: ("", 0),
                save_json=lambda path, value: events.append("save:" + path),
                active_character_update_available=False, emit_combat_event=Mock(),
                get_current_actor=Mock(), advance_turn=Mock(), get_pc_state=Mock(),
                pc_acted_status="acted", npc_combatant_type="npc", pc_combatant_type="pc",
                check_all_monsters_defeated=lambda data: False,
            )
            result = process_combat_action_batch(
                [
                    {"action": "updateEncounter", "parameters": {"changes": "enemy takes damage", "ops": [{"op": "hp_delta", "delta": -3}]}},
                    {"action": "updateCharacterInfo", "parameters": {"characterName": "Acheron", "ops": [{"op": "hp_delta", "delta": -1}]}},
                ],
                {"creatures": [{"name": "Goblin", "type": "enemy", "currentHitPoints": 4}]},
                {}, encounter_id="fixture", conversation_history=[],
                conversation_history_file="history.json", multi_pc_manager=None,
                party_tracker_data={}, is_combat_ending=False, dependencies=dependencies,
            )
            self.assertEqual(events, ["log:encounter-error", "queue:character"])
            self.assertEqual(len(errors), 1)
            self.assertIn("Acheron", result.final_character_updates)
            self.assertEqual(result.encounter_data["creatures"][0]["currentHitPoints"], 4)
            tripwire.assert_untouched(self)

    def test_exit_queues_xp_and_saves_history_at_the_existing_action_point(self):
        with _guarded_stage_execution() as tripwire:
            events = []
            queued = {}
            history = []
            deps = CombatActionDependencies(
                queue_character_update=lambda *args: (events.append("queue:xp"), queue_final_character_update(*args)),
                update_encounter=Mock(), normalize_encounter_status=lambda data: data,
                sync_non_pc_queue_state=Mock(), log_info=Mock(), log_debug=Mock(), log_error=Mock(), log_warning=Mock(),
                calculate_xp=lambda: ("party awarded XP", 25),
                save_json=lambda path, value: events.append("save:" + path),
                active_character_update_available=False, emit_combat_event=Mock(),
                get_current_actor=Mock(), advance_turn=Mock(), get_pc_state=Mock(),
                pc_acted_status="acted", npc_combatant_type="npc", pc_combatant_type="pc",
                check_all_monsters_defeated=lambda data: False,
            )
            result = process_combat_action_batch(
                [{"action": "exit", "parameters": {}}],
                {"creatures": [{"name": "Acheron", "type": "player"}]},
                queued, encounter_id="exit-fixture", conversation_history=history,
                conversation_history_file="history.json", multi_pc_manager=None,
                party_tracker_data={}, is_combat_ending=True, dependencies=deps,
            )
            self.assertTrue(result.is_combat_ending)
            self.assertEqual(history, [{"role": "user", "content": "XP Awarded: party awarded XP"}])
            self.assertEqual(events, ["save:history.json", "queue:xp"])
            self.assertEqual(queued["Acheron"][0]["changes"], "awarded 25 experience points")
            tripwire.assert_untouched(self)

    def test_failed_ops_commit_continues_to_prose_fallback(self):
        with _guarded_stage_execution() as tripwire:
            calls = []
            logs = []
            apply_final_character_updates(
                {"Acheron": [
                    {"changes": "deterministic update", "ops": [{"op": "unsupported"}]},
                    {"changes": "spent arrow", "ops": None},
                ]},
                None,
                CharacterUpdateDependencies(
                    update_character_info=lambda name, changes, **kwargs: (calls.append((changes, kwargs.get("ops"))), False)[1],
                    normalize_character_name=lambda name: name.lower(), safe_json_load=lambda path: None,
                    sync_character_state=Mock(), log_info=Mock(), log_debug=Mock(),
                    log_error=lambda message, **kwargs: logs.append(message),
                ),
            )
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "deterministic update")
            self.assertIn("Following the turn's events", calls[1][0])
            self.assertTrue(logs)
            tripwire.assert_untouched(self)

    def test_owner_publishes_only_after_commit_and_runtime_sync(self):
        source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_run_combat_simulation_internal")
        combat_loop = next(node for node in ast.walk(function) if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True)
        call_lines = {}
        for node in ast.walk(combat_loop):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {"stage_combat_turn_snapshot", "process_combat_action_batch", "_commit_normal_combat_turn", "sync_committed_combat_turn"}:
                    call_lines[node.func.id] = node.lineno
                if isinstance(node.func, ast.Name) and node.func.id == "publish_combat_narration":
                    call_lines["narration_publication"] = node.lineno
                    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                    self.assertIsInstance(keywords.get("emit"), ast.Name)
                    self.assertEqual(keywords["emit"].id, "print")
                    flush = keywords.get("flush")
                    self.assertIsInstance(flush, ast.Attribute)
                    self.assertEqual(flush.attr, "flush")
                    self.assertEqual(ast.unparse(flush.value), "sys.stdout")
        self.assertLess(call_lines["process_combat_action_batch"], call_lines["stage_combat_turn_snapshot"])
        self.assertLess(call_lines["stage_combat_turn_snapshot"], call_lines["_commit_normal_combat_turn"])
        self.assertLess(call_lines["_commit_normal_combat_turn"], call_lines["sync_committed_combat_turn"])
        self.assertLess(call_lines["sync_committed_combat_turn"], call_lines["narration_publication"])
        publish_keywords = {keyword.arg: keyword.value for keyword in next(
            node for node in ast.walk(combat_loop)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "publish_combat_narration"
        ).keywords}
        self.assertIsInstance(publish_keywords.get("applied_id"), ast.Attribute)
        self.assertEqual(publish_keywords["applied_id"].attr, "applied_id")

    def test_real_owner_stage_calls_bind_to_current_helper_signatures(self):
        source = Path("core/combat/combat_manager.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        owner = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_run_combat_simulation_internal"
        )
        signatures = {
            "stage_combat_turn_snapshot": inspect.signature(stage_combat_turn_snapshot),
            "process_combat_action_batch": inspect.signature(process_combat_action_batch),
            "sync_committed_combat_turn": inspect.signature(sync_committed_combat_turn),
        }
        calls = {name: [] for name in signatures}
        for node in ast.walk(owner):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in signatures:
                calls[node.func.id].append(node)
        for name, signature in signatures.items():
            self.assertEqual(len(calls[name]), 1, f"owner should call {name} once")
            call_node = calls[name][0]
            keyword_values = {keyword.arg: None for keyword in call_node.keywords if keyword.arg is not None}
            signature.bind(*([None] * len(call_node.args)), **keyword_values)

        character_update_owner = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_apply_final_character_updates"
        )
        apply_calls = [
            node for node in ast.walk(character_update_owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "apply_final_character_updates"
        ]
        self.assertEqual(len(apply_calls), 1)
        apply_signature = inspect.signature(apply_final_character_updates)
        apply_signature.bind(*([None] * len(apply_calls[0].args)), **{kw.arg: None for kw in apply_calls[0].keywords if kw.arg})

        sync_owner = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_sync_multi_pc_character_state"
        )
        sync_calls = [
            node for node in ast.walk(sync_owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sync_multi_pc_character_state"
        ]
        self.assertEqual(len(sync_calls), 1)
        inspect.signature(sync_multi_pc_character_state).bind(*([None] * len(sync_calls[0].args)), **{kw.arg: None for kw in sync_calls[0].keywords if kw.arg})

        apply_dependencies = next(
            node for node in ast.walk(character_update_owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "CharacterUpdateDependencies"
        )
        bindings = {keyword.arg: keyword.value for keyword in apply_dependencies.keywords}
        inspect.signature(CharacterUpdateDependencies).bind(**{field: None for field in bindings})
        for field, name in (
            ("update_character_info", "update_character_info"),
            ("normalize_character_name", "normalize_character_name"),
            ("safe_json_load", "safe_json_load"),
            ("sync_character_state", "_sync_multi_pc_character_state"),
            ("log_info", "info"), ("log_debug", "debug"), ("log_error", "error"),
        ):
            self.assertIsInstance(bindings[field], ast.Name)
            self.assertEqual(bindings[field].id, name)

        queue_owner = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_queue_final_character_update"
        )
        queue_calls = [
            node for node in ast.walk(queue_owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "queue_final_character_update"
        ]
        self.assertEqual(len(queue_calls), 1)
        inspect.signature(queue_final_character_update).bind(*([None] * len(queue_calls[0].args)), **{kw.arg: None for kw in queue_calls[0].keywords if kw.arg})

        dependency_signatures = {
            "RoundTransitionDependencies": inspect.signature(RoundTransitionDependencies),
            "CombatActionDependencies": inspect.signature(CombatActionDependencies),
        }
        for name, signature in dependency_signatures.items():
            calls_for_type = [
                node for node in ast.walk(owner)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
            ]
            self.assertEqual(len(calls_for_type), 1, f"owner should construct {name} once")
            call_node = calls_for_type[0]
            keyword_values = {keyword.arg: None for keyword in call_node.keywords if keyword.arg is not None}
            signature.bind(*([None] * len(call_node.args)), **keyword_values)

        retry_call_line = next(
            node.lineno for node in ast.walk(owner)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_combat_provider_retry_stage"
        )
        round_call_line = calls["stage_combat_turn_snapshot"][0].lineno
        action_call_line = calls["process_combat_action_batch"][0].lineno
        self.assertLess(retry_call_line, round_call_line)
        self.assertLess(action_call_line, round_call_line)
        self.assertLess(round_call_line, calls["sync_committed_combat_turn"][0].lineno)

        action_dependencies = next(
            call for call in ast.walk(owner)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "CombatActionDependencies"
        )
        xp_binding = next(keyword.value for keyword in action_dependencies.keywords if keyword.arg == "calculate_xp")
        self.assertIsInstance(xp_binding, ast.Name)
        self.assertEqual(xp_binding.id, "calculate_xp")
        from utils.xp import main as xp_main
        inspect.signature(xp_main).bind()

    def test_write_guards_raise_baseexception_outside_project_scratch(self):
        with patch.object(builtins, "open", side_effect=_deny), patch.object(os, "remove", side_effect=_deny):
            with self.assertRaises(GuardDenied):
                open("characters/not-a-fixture.json", "w")
            with self.assertRaises(GuardDenied):
                os.remove("characters/not-a-fixture.json")


if __name__ == "__main__":
    unittest.main()
