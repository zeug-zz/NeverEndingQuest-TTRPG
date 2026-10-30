# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Validation Stage Tests
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.

Provider-free tests for the extracted combat validation stage.
"""

import builtins
import ast
import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
import sys
import types
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from scripts.test_llm_router import ProviderTripwire


def _guarded_validation_import():
    with ProviderTripwire() as tripwire, _deny_test_writes():
        module = importlib.import_module("core.combat.validation")
        for guard in tripwire.guards.values():
            guard.assert_not_called()
    return module.CombatValidationDependencies, module.validate_combat_response


class ExternalWriteDenied(BaseException):
    """Fatal sentinel preventing test-only imports from writing runtime files."""


class _deny_test_writes:
    """Fatal filesystem write tripwire used before loading test-selected code."""

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

        def deny_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise ExternalWriteDenied(f"outside-write tripwire: {file}")
            return real_open(file, mode, *args, **kwargs)

        def deny_io_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise ExternalWriteDenied(f"outside-write tripwire: {file}")
            return real_io_open(file, mode, *args, **kwargs)

        def deny_os_open(file, flags, *args, **kwargs):
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            if flags & write_flags:
                raise ExternalWriteDenied(f"outside-write tripwire: {file}")
            return real_os_open(file, flags, *args, **kwargs)

        self.stack.enter_context(patch("builtins.open", side_effect=deny_open))
        self.stack.enter_context(patch("io.open", side_effect=deny_io_open))
        self.stack.enter_context(patch("os.open", side_effect=deny_os_open))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


CombatValidationDependencies, validate_combat_response = _guarded_validation_import()


def _provider_result(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])


def _dependencies(*, completions=None, phase=(True, ""), compression=(False, "fixture_uncompressed"),
                  history=None, files=None, usage_error=False, log_error=False):
    calls = {"provider": [], "usage": [], "api_log": [], "trace": [], "mkdir": [], "open": [], "debug": []}
    files = files if files is not None else {}

    def create(**kwargs):
        calls["provider"].append(kwargs)
        if completions:
            item = completions.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return _provider_result('{"valid":true,"feedback":{}}')

    def llm_call(task, messages, **kwargs):
        request = {"task": task, "messages": messages, **kwargs}
        calls["provider"].append(request)
        if completions:
            item = completions.pop(0)
            if isinstance(item, Exception):
                raise item
            raw_response = item
        else:
            raw_response = _provider_result('{"valid":true,"feedback":{}}')
        if kwargs.get("observer") is not None:
            kwargs["observer"](
                SimpleNamespace(kind="response", call_id="fixture-call", attempt_id=str(len(calls["provider"]))),
                raw_response,
            )
        return raw_response.choices[0].message.content

    def receipt_observer_factory(**options):
        calls.setdefault("observer_options", []).append(options)
        def observe(_receipt, response):
            calls["trace"].append(("combat_validation", response))
            try:
                api_log("combat_validation", options["messages"], response,
                        metadata=options["legacy_context"])
            except Exception:
                pass
            if options["track_usage"]:
                try:
                    usage(response)
                except Exception:
                    pass
        return observe

    def open_file(path, mode="r", **kwargs):
        calls["open"].append((path, mode))
        stream = io.StringIO()
        files[path] = stream
        return stream

    def precheck(*args, **kwargs):
        return phase

    def usage(result):
        calls["usage"].append(result)
        if usage_error:
            raise RuntimeError("usage unavailable")

    def api_log(*args, **kwargs):
        calls["api_log"].append((args, kwargs))
        if log_error:
            raise RuntimeError("log unavailable")

    deps = CombatValidationDependencies(
        parse_json_safely=lambda value: json.loads(value) if _is_json(value) else None,
        phase_precheck=precheck, replay_precheck=lambda *a, **k: (True, ""),
        narration_precheck=lambda *a, **k: (True, ""), enemy_boundary_precheck=lambda *a, **k: (True, ""),
        truth_pack_builder=lambda *a: [], canonical_attack_facts_builder=lambda *a: [],
        read_prompt=lambda path: "frozen prompt:" + path,
        compressed_combat=True, compression_enabled=True, compression_threshold_chars=1,
        compression_decision=lambda **kwargs: compression,
        telemetry_builder=lambda **kwargs: kwargs,
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        validation_model="fixture-model", completion_params=lambda *a, **k: {"model": "fixture-model"},
        trace_provider_call=lambda *a: calls["trace"].append(a),
        sanitize_for_logging=lambda value: str(value),
        debug=lambda *a, **k: calls["debug"].append((a, k)),
        warning=lambda *a, **k: None,
        emit_console=lambda value: None, usage_tracking_available=True, track_usage=usage,
        log_api_call=api_log, export_open=open_file, makedirs=lambda *a, **k: calls["mkdir"].append((a, k)),
        now=lambda: SimpleNamespace(strftime=lambda fmt: "20261015_120000_123"),
        format_log_timestamp=lambda fmt: "2026-10-15 12:00:00", perf_counter=lambda: 1.0,
        llm_call=llm_call,
        receipt_observer_factory=receipt_observer_factory,
    )
    return deps, calls


def _is_json(value):
    try:
        json.loads(value)
        return True
    except (TypeError, ValueError):
        return False


def _extract_authoritative_phase_block(messages):
    heading = "=== AUTHORITATIVE COMBAT PHASE STATE (PYTHON; NOT CANDIDATE CLAIMS) ==="
    index = next(i for i, message in enumerate(messages) if message.get("content") == heading)
    return index, json.loads(messages[index + 1]["content"])


def _initiative_tracker_text(turn_window):
    return "```json\n" + json.dumps({"turn_window": turn_window}) + "\n```"


class CombatValidationStageTests(unittest.TestCase):
    def setUp(self):
        self.tripwire = ProviderTripwire()
        self.tripwire.__enter__()
        self.addCleanup(lambda: self.tripwire.__exit__(None, None, None))

    def tearDown(self):
        self.tripwire.assert_untouched(self)

    def _run(self, deps, history=None, manager=None, response='{"actions":[]}'):
        return validate_combat_response(
            response, {"encounterId": "FIXTURE", "creatures": []}, "hold position",
            conversation_history=history, multi_pc_manager=manager, dependencies=deps,
        )

    def test_success_uses_injected_fake_client_and_side_effect_seams(self):
        deps, calls = _dependencies(log_error=True, usage_error=True)
        self.assertIs(self._run(deps), True)
        self.assertEqual(len(calls["provider"]), 1)
        self.assertEqual(calls["provider"][0]["task"], "combat_validation")
        self.assertIs(calls["provider"][0]["json_output"], False)
        self.assertEqual(calls["provider"][0]["temperature"], 0.3)
        self.assertNotIn("timeout", calls["provider"][0])
        self.assertNotIn("model", calls["provider"][0])
        self.assertEqual(len(calls["usage"]), 1)
        self.assertEqual(len(calls["api_log"]), 1)
        self.assertEqual(calls["open"], [])
        self.assertEqual(calls["mkdir"], [])
        self.assertEqual(len(calls["trace"]), 1)

    def test_deterministic_phase_rejection_skips_provider(self):
        deps, calls = _dependencies(phase=(False, "forbidden actor"))
        class Manager:
            combat_phase = "PC_PHASE"
            pc_phase_complete = False
            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return []
            def get_remaining_enemies_for_round(self): return []
        result = self._run(deps, manager=Manager(), response='{"combat_round":1,"actions":[]}')
        self.assertIn("forbidden actor", result)
        self.assertEqual(calls["provider"], [])
        self.assertEqual(calls["open"], [])
        self.assertEqual(calls.get("observer_options", []), [])

    def test_enemy_routing_rejection_trace_is_gated_bounded_and_uses_actual_candidate(self):
        from utils import combat_latency_trace

        response_obj = {"actions": [{"action": "updateEncounter", "parameters": {
            "changes": "Blairen strikes Goblin Alpha; " + "x" * 700,
            "ops": [{"op": "hp_delta", "creature": "Goblin Alpha", "delta": -4,
                     "unselected": "do not capture"}],
        }}]}
        response = json.dumps(response_obj)
        calls = []
        deps, stage_calls = _dependencies()
        deps = replace(deps, enemy_boundary_precheck=lambda *_: (False, "exact routing rejection"))
        real_gate = combat_latency_trace.trace_enabled
        real_observer = combat_latency_trace.trace_combat_observation
        try:
            combat_latency_trace.trace_enabled = lambda: False
            combat_latency_trace.trace_combat_observation = lambda *a, **k: calls.append((a, k))
            result = self._run(deps, response=response)
            self.assertIn("exact routing rejection", result)
            self.assertEqual(calls, [])
            self.assertEqual(stage_calls["open"], [])
            self.assertEqual(stage_calls["provider"], [])

            combat_latency_trace.trace_enabled = lambda: True
            result = self._run(deps, response=response)
            self.assertIn("exact routing rejection", result)

            long_deps, _ = _dependencies()
            long_deps = replace(long_deps, enemy_boundary_precheck=lambda *_: (False, "R" * 900))
            self._run(long_deps, response=response)

            oversized_candidate = {"actions": [{"action": "updateEncounter", "parameters": {
                "changes": "C" * 900,
                "ops": [{"op": "hp_delta", "creature": "T" * 400, "target": "T" * 400,
                         "delta": -1, "ignored": "I" * 1000} for _ in range(10)],
            }} for _ in range(6)]}
            bounded_deps, _ = _dependencies()
            bounded_deps = replace(bounded_deps, enemy_boundary_precheck=lambda *_: (False, "B" * 900))
            self._run(bounded_deps, response=json.dumps(oversized_candidate))
        finally:
            combat_latency_trace.trace_enabled = real_gate
            combat_latency_trace.trace_combat_observation = real_observer
        self.assertEqual(len(calls), 3)
        args, fields = calls[0]
        self.assertEqual(args, ("enemy_routing_precheck_reject",))
        self.assertEqual(fields["reason"], "exact routing rejection")
        self.assertEqual(fields["changes"][0]["changes"], response_obj["actions"][0]["parameters"]["changes"][:96])
        self.assertEqual(fields["operation_0_action_index"], 0)
        self.assertEqual(fields["operation_0_index"], 0)
        self.assertEqual(fields["operation_0_operation"], "hp_delta")
        self.assertEqual(fields["operation_0_creature"], "Goblin Alpha")
        self.assertEqual(fields["operation_0_delta"], -4)
        self.assertNotIn("unselected", json.dumps(fields))
        record = combat_latency_trace.normalize_trace_event("combat_observation", **fields)
        self.assertLessEqual(len(json.dumps(record, ensure_ascii=True).encode("ascii")), 8192)
        self.assertEqual(response, json.dumps(response_obj))

        long_fields = calls[1][1]
        self.assertEqual(long_fields["reason"], "R" * 128)
        self.assertEqual(long_fields["reason_chars"], 900)
        self.assertEqual(long_fields["reason_truncated"], 772)
        long_record = combat_latency_trace.normalize_trace_event("combat_observation", **long_fields)
        self.assertLessEqual(len(json.dumps(long_record, ensure_ascii=True).encode("ascii")), 8192)
        bounded_fields = calls[2][1]
        self.assertEqual(bounded_fields["captured_action_count"], 4)
        self.assertEqual(bounded_fields["changes_truncated"], 2)
        self.assertEqual(bounded_fields["operations_truncated"], 56)
        self.assertTrue(all(len(item["changes"]) == 96 and item["changes_truncated"] == 804
                            for item in bounded_fields["changes"]))
        self.assertEqual(sum(key.endswith("_operation") for key in bounded_fields), 4)
        self.assertTrue(all(len(value) <= 16 for key, value in bounded_fields.items()
                            if key.startswith("operation_") and isinstance(value, str)))
        bounded_record = combat_latency_trace.normalize_trace_event("combat_observation", **bounded_fields)
        self.assertLessEqual(len(json.dumps(bounded_record, ensure_ascii=True).encode("ascii")), 8192)

    def test_exact_enemies_turn_batch_reaches_full_semantic_validation_and_honors_false(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        class Manager:
            combat_phase = "ENEMY_PHASE"
            pc_phase_complete = True

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return []
            def get_remaining_enemies_for_round(self): return ["Goblin", "Blairen"]
            def format_initiative_tracker(self, encounter_data):
                return _initiative_tracker_text(["Goblin", "Blairen"])

        diagnostic_changes = (
            "Goblin takes 7 damage, HP 18->11. Blairen hits Goblin. "
            "Goblin misses Acheron. Acheron, what do you do?"
        )
        candidate = {
            "combat_round": 1,
            "plan": diagnostic_changes,
            "narration": diagnostic_changes,
            "actions": [{"action": "updateEncounter", "parameters": {
                "changes": diagnostic_changes,
                "ops": [{"op": "hp_delta", "creature": "Goblin", "delta": -1}],
            }}],
        }
        deps, calls = _dependencies(completions=[_provider_result(json.dumps({
            "valid": False,
            "feedback": {"positive": "", "negative": "Skipped enemy action", "recommendation": "retry"},
        }))])
        deps = replace(deps, phase_precheck=validate_combat_phase_integrity_precheck)
        result = validate_combat_response(
            json.dumps(candidate),
            {"combat_round": 1, "creatures": [
                {"name": "Acheron", "type": "player"},
                {"name": "Goblin", "type": "enemy", "currentHitPoints": 18},
            ]},
            "Enemies turn.", multi_pc_manager=Manager(), dependencies=deps,
        )
        self.assertIn("Skipped enemy action", result)
        self.assertEqual(len(calls["provider"]), 1)

    def test_batch_handoff_requires_exact_input_and_complete_actor_coverage_before_provider(self):
        from utils.combat_phase_integrity_precheck import validate_combat_phase_integrity_precheck

        class Manager:
            combat_phase = "ENEMY_PHASE"
            pc_phase_complete = True

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return []
            def get_remaining_enemies_for_round(self): return ["Goblin", "Blairen"]
            def format_initiative_tracker(self, encounter_data):
                return _initiative_tracker_text(["Goblin", "Blairen"])

        partial = {"combat_round": 1, "narration": "Goblin attacks Acheron. Acheron, what do you do?",
                   "complete_enemy_batch": True, "full_enemy_batch_intent": True, "actions": []}
        for user_input in ("Enemies turn. ", "continue"):
            deps, calls = _dependencies()
            deps = replace(deps, phase_precheck=validate_combat_phase_integrity_precheck)
            result = validate_combat_response(
                json.dumps(partial), {"combat_round": 1, "creatures": []}, user_input,
                multi_pc_manager=Manager(), dependencies=deps,
            )
            self.assertIn("before enemy batch completion", result)
            self.assertEqual(calls["provider"], [])

        exact_but_partial, calls = _dependencies()
        exact_but_partial = replace(exact_but_partial, phase_precheck=validate_combat_phase_integrity_precheck)
        result = validate_combat_response(
            json.dumps(partial), {"combat_round": 1, "creatures": []}, "Enemies turn.",
            multi_pc_manager=Manager(), dependencies=exact_but_partial,
        )
        self.assertIn("before enemy batch completion", result)
        self.assertEqual(calls["provider"], [])

        complete_text = "Goblin attacks Acheron. Blairen hits Goblin. Acheron, what do you do?"
        for invalid_round in (-1, 3, 999, "1", True, 1.0):
            candidate = {"combat_round": invalid_round, "narration": complete_text}
            deps, calls = _dependencies()
            deps = replace(deps, phase_precheck=validate_combat_phase_integrity_precheck)
            result = validate_combat_response(
                json.dumps(candidate), {"combat_round": 1, "creatures": []}, "Enemies turn.",
                multi_pc_manager=Manager(), dependencies=deps,
            )
            self.assertIn("before enemy batch completion", result)
            self.assertEqual(calls["provider"], [])

    def test_authoritative_phase_block_describes_exact_enemy_batch_and_calls_provider_once(self):
        class Manager:
            combat_phase = "ENEMY_PHASE"
            pc_phase_complete = True
            current_pc_name = "Acheron"

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return ["Acheron"]
            def get_remaining_enemies_for_round(self): return ["Goblin"]
            def format_initiative_tracker(self, encounter_data):
                return _initiative_tracker_text(["Goblin"])

        candidate = {"combat_round": 2, "actions": []}
        deps, calls = _dependencies()
        encounter = {"combat_round": 2, "openingEnemyBatchPending": True, "creatures": []}
        result = validate_combat_response(
            json.dumps(candidate), encounter, "Enemies turn.",
            multi_pc_manager=Manager(), dependencies=deps,
        )

        self.assertIs(result, True)
        self.assertEqual(len(calls["provider"]), 1)
        messages = calls["provider"][0]["messages"]
        block_index, block = _extract_authoritative_phase_block(messages)
        self.assertEqual(block, {
            "phase": "ENEMY_PHASE",
            "round": 2,
            "forbidden_actors": ["Acheron"],
            "pending_enemies": ["Goblin"],
            "current_turn_window": ["Goblin"],
            "pc_phase_complete": True,
            "opening_batch_pending": True,
            "full_enemy_batch_intent": True,
        })
        self.assertEqual(messages[block_index + 1]["content"], json.dumps(
            block, sort_keys=True, indent=4, ensure_ascii=True
        ))
        self.assertEqual(messages[block_index]["role"], "system")
        self.assertEqual(messages[block_index + 1]["role"], "system")
        candidate_index = next(i for i, message in enumerate(messages)
                               if message.get("role") == "assistant"
                               and message.get("content") == json.dumps(candidate))
        self.assertLess(block_index, candidate_index)

    def test_candidate_phase_and_round_claims_do_not_change_authoritative_block(self):
        class Manager:
            combat_phase = "ENEMY_PHASE"
            pc_phase_complete = True

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return ["Acheron"]
            def get_remaining_enemies_for_round(self): return ["Goblin"]
            def format_initiative_tracker(self, encounter_data):
                return _initiative_tracker_text(["Goblin"])

        candidate = {
            "combat_round": 1,
            "phase": "PC_PHASE",
            "current_phase": "PC_PHASE",
            "pending_enemies": ["Fake Goblin"],
            "current_turn_window": ["Acheron"],
            "full_enemy_batch_intent": False,
            "actions": [],
        }
        deps, calls = _dependencies()
        result = validate_combat_response(
            json.dumps(candidate), {"combat_round": 2, "creatures": []}, "Enemies turn.",
            multi_pc_manager=Manager(), dependencies=deps,
        )

        self.assertIs(result, True)
        self.assertEqual(len(calls["provider"]), 1)
        messages = calls["provider"][0]["messages"]
        _index, block = _extract_authoritative_phase_block(messages)
        self.assertEqual(block["phase"], "ENEMY_PHASE")
        self.assertEqual(block["round"], 2)
        self.assertEqual(block["pending_enemies"], ["Goblin"])
        self.assertEqual(block["current_turn_window"], ["Goblin"])
        self.assertIs(block["full_enemy_batch_intent"], True)
        self.assertEqual(messages[-1]["content"], json.dumps(candidate))

    def test_phase_precheck_receives_the_same_state_used_for_authoritative_context(self):
        class Manager:
            combat_phase = "ENEMY_PHASE"
            pc_phase_complete = True

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return ["Acheron"]
            def get_remaining_enemies_for_round(self): return ["Goblin"]
            def format_initiative_tracker(self, encounter_data):
                return _initiative_tracker_text(["Goblin"])

        precheck_calls = []

        def phase_precheck(response_json, encounter_data, *, phase_state=None):
            precheck_calls.append(copy.deepcopy(phase_state))
            return True, ""

        deps, calls = _dependencies()
        deps = replace(deps, phase_precheck=phase_precheck)
        result = validate_combat_response(
            '{"combat_round":2,"actions":[]}', {"combat_round": 2, "creatures": []},
            "Enemies turn.", multi_pc_manager=Manager(), dependencies=deps,
        )

        self.assertIs(result, True)
        self.assertEqual(len(precheck_calls), 1)
        self.assertEqual(precheck_calls[0], {
            "current_phase": "ENEMY_PHASE",
            "forbidden_actors": ["Acheron"],
            "pending_enemies": ["Goblin"],
            "pc_phase_complete": True,
            "current_round": 2,
            "opening_batch_pending": False,
            "full_enemy_batch_intent": True,
        })
        self.assertEqual(len(calls["provider"]), 1)
        _index, block = _extract_authoritative_phase_block(calls["provider"][0]["messages"])
        self.assertEqual(block["phase"], precheck_calls[0]["current_phase"])
        self.assertEqual(block["round"], precheck_calls[0]["current_round"])
        self.assertEqual(block["forbidden_actors"], precheck_calls[0]["forbidden_actors"])
        self.assertEqual(block["pending_enemies"], precheck_calls[0]["pending_enemies"])
        self.assertEqual(block["pc_phase_complete"], precheck_calls[0]["pc_phase_complete"])
        self.assertEqual(block["opening_batch_pending"], precheck_calls[0]["opening_batch_pending"])
        self.assertEqual(block["full_enemy_batch_intent"], precheck_calls[0]["full_enemy_batch_intent"])

    def test_pc_phase_block_includes_forbidden_actors_and_active_pc_window(self):
        class Manager:
            combat_phase = "PC_PHASE"
            pc_phase_complete = False
            current_pc_name = "Acheron"

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return ["Goblin", "Blairen"]
            def get_remaining_enemies_for_round(self): return ["Goblin"]
            def format_initiative_tracker(self, encounter_data):
                return _initiative_tracker_text(["Acheron"])

        deps, calls = _dependencies()
        result = validate_combat_response(
            '{"combat_round":3,"actions":[]}', {"combat_round": 3, "creatures": []},
            "hold position", multi_pc_manager=Manager(), dependencies=deps,
        )

        self.assertIs(result, True)
        self.assertEqual(len(calls["provider"]), 1)
        _index, block = _extract_authoritative_phase_block(calls["provider"][0]["messages"])
        self.assertEqual(block["forbidden_actors"], ["Goblin", "Blairen"])
        self.assertEqual(block["current_turn_window"], ["Acheron"])
        self.assertIs(block["full_enemy_batch_intent"], False)

    def test_pc_phase_window_uses_tracker_json_not_stale_public_pc_and_tracker_is_read_only(self):
        from core.combat.multi_pc.manager import MultiPCCombatManager
        from core.combat.multi_pc.state import PCCombatState, PCStatus
        from core.combat.multi_pc.turn_queue import Combatant, CombatantType

        class PreInitiativeManager(MultiPCCombatManager):
            @property
            def current_pc_name(self):
                return "Vitreol"

        manager = PreInitiativeManager()
        party_names = ["Acheron", "Merisiel", "Kira", "Vitreol"]
        manager._state.pc_states = {
            name: PCCombatState(
                character_name=name,
                status=PCStatus.READY,
                current_hp=20,
                max_hp=20,
            )
            for name in party_names
        }
        manager._state.current_pc_name = "Acheron"
        manager._state.current_round = 1
        manager._turns.turn_queue = [
            Combatant(
                name=name,
                type=CombatantType.PC,
                initiative=20 - index,
                hp=20,
                max_hp=20,
                ac=10,
            )
            for index, name in enumerate(party_names)
        ] + [Combatant(
            name="Goblin",
            type=CombatantType.ENEMY,
            initiative=10,
            hp=7,
            max_hp=7,
            ac=15,
        )]
        manager._turns.current_turn_index = 0
        manager._turns.pc_phase_complete = False

        def state_snapshot():
            return copy.deepcopy({
                "pc_states": manager._state.pc_states,
                "current_pc_name": manager._state.current_pc_name,
                "current_round": manager._state.current_round,
                "turn_queue": manager._turns.turn_queue,
                "current_turn_index": manager._turns.current_turn_index,
                "pc_phase_complete": manager._turns.pc_phase_complete,
                "enemy_phase_complete": manager._turns.enemy_phase_complete,
            })

        original_formatter = manager.format_initiative_tracker
        tracker_state_observations = []

        def observed_formatter(encounter_data):
            before = state_snapshot()
            tracker_text = original_formatter(encounter_data)
            after = state_snapshot()
            tracker_state_observations.append((before, after))
            return tracker_text

        manager.format_initiative_tracker = observed_formatter
        before_validation = state_snapshot()
        self.assertEqual(manager.current_pc_name, "Vitreol")

        deps, calls = _dependencies()
        result = validate_combat_response(
            '{"combat_round":1,"actions":[]}',
            {"combat_round": 1, "creatures": []},
            "hold position", multi_pc_manager=manager, dependencies=deps,
        )

        self.assertIs(result, True)
        self.assertEqual(len(calls["provider"]), 1)
        self.assertEqual(len(tracker_state_observations), 1)
        tracker_before, tracker_after = tracker_state_observations[0]
        self.assertEqual(tracker_before, tracker_after)
        self.assertEqual(before_validation, state_snapshot())
        _index, block = _extract_authoritative_phase_block(calls["provider"][0]["messages"])
        self.assertEqual(block["current_turn_window"], ["Acheron"])

    def test_unparseable_tracker_omits_turn_window_without_guessing(self):
        class Manager:
            combat_phase = "PC_PHASE"
            pc_phase_complete = False
            current_pc_name = "Vitreol"

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return ["Goblin"]
            def get_remaining_enemies_for_round(self): return ["Goblin"]
            def format_initiative_tracker(self, encounter_data):
                return "```json\nnot valid json\n```"

        deps, calls = _dependencies()
        result = validate_combat_response(
            '{"combat_round":1,"actions":[]}',
            {"combat_round": 1, "creatures": []},
            "hold position", multi_pc_manager=Manager(), dependencies=deps,
        )

        self.assertIs(result, True)
        self.assertEqual(len(calls["provider"]), 1)
        _index, block = _extract_authoritative_phase_block(calls["provider"][0]["messages"])
        self.assertNotIn("current_turn_window", block)
        self.assertEqual(block["forbidden_actors"], ["Goblin"])
        self.assertEqual(block["pending_enemies"], ["Goblin"])

    def test_phase_derivation_failure_omits_block_and_validation_proceeds(self):
        class Manager:
            combat_phase = "PC_PHASE"
            pc_phase_complete = False

            def get_available_pcs(self): return []
            # get_forbidden_actors intentionally missing to fail derivation.

        deps, calls = _dependencies()
        result = validate_combat_response(
            '{"combat_round":1,"actions":[]}', {"combat_round": 1, "creatures": []},
            "hold position", multi_pc_manager=Manager(), dependencies=deps,
        )

        self.assertIs(result, True)
        self.assertEqual(len(calls["provider"]), 1)
        messages = calls["provider"][0]["messages"]
        self.assertFalse(any("AUTHORITATIVE COMBAT PHASE STATE" in message.get("content", "")
                             for message in messages))
        self.assertTrue(any("phase-integrity precheck failed open" in args[0].lower()
                            for args, _kwargs in calls["debug"] if args))

    def test_authoritative_phase_actor_lists_and_serialization_are_bounded(self):
        class Manager:
            combat_phase = "E" * 100
            pc_phase_complete = True

            def get_available_pcs(self): return []
            def get_forbidden_actors(self): return ["F" * 100 + str(i) for i in range(20)]
            def get_remaining_enemies_for_round(self): return ["G" * 100 + str(i) for i in range(20)]
            def format_initiative_tracker(self, encounter_data):
                return _initiative_tracker_text(["T" * 100 + str(i) for i in range(20)])

        deps, calls = _dependencies()
        result = validate_combat_response(
            '{"combat_round":1,"actions":[]}', {"combat_round": 1, "creatures": []},
            "Enemies turn.", multi_pc_manager=Manager(), dependencies=deps,
        )

        self.assertIs(result, True)
        _index, block = _extract_authoritative_phase_block(calls["provider"][0]["messages"])
        block_text = json.dumps(block, sort_keys=True, indent=4, ensure_ascii=True)
        self.assertLessEqual(len(block_text), 8192)
        self.assertLessEqual(len(block["forbidden_actors"]), 16)
        self.assertLessEqual(len(block["pending_enemies"]), 16)
        self.assertTrue(all(len(name) <= 64 for name in block["forbidden_actors"] + block["pending_enemies"]))
        self.assertEqual(len(block["phase"]), 64)

    def test_ops_only_ammunition_truth_uses_committed_ammo_and_explicit_container_context(self):
        with _deny_test_writes():
            with open(os.path.join("core", "combat", "combat_manager.py"), "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            helper_names = {
                "_is_combat_inventory_or_ammo_change",
                "_extract_touched_character_updates_from_response_json",
                "_build_compact_combat_truth_pack",
            }
            selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in helper_names]
            helper_ns = {}
            exec(compile(ast.Module(body=selected, type_ignores=[]), "core/combat/combat_manager.py", "exec"), helper_ns)

        record = {"name": "Acheron", "hitPoints": 20, "maxHitPoints": 20,
                  "condition_affected": [], "spellSlots": {}, "deathSaves": {},
                  "ammunition": [{"name": "crossbow bolts", "quantity": 3}],
                  "equipment": [{"item_name": "crossbow bolts", "quantity": 1}],
                  "currency": {"gold": 0, "silver": 0, "copper": 0}}
        state_before = copy.deepcopy(record)
        fake_pc_manager = types.ModuleType("utils.pc_manager")
        fake_pc_manager.get_character_state = lambda name: record if name == "Acheron" else None
        encounter = {"encounterId": "ops-ammo", "creatures": [{"name": "Acheron", "type": "player"}]}
        candidate = {"actions": [{"action": "updateCharacterInfo", "parameters": {
            "characterName": "Acheron", "ops": [{"op": "inventory_remove", "item": "crossbow bolts",
                                                          "quantity": 99, "container": "ammunition"}]}}]}
        deps, calls = _dependencies()
        deps = replace(deps, truth_pack_builder=helper_ns["_build_compact_combat_truth_pack"],
                       compression_decision=lambda **kwargs: (False, "fixture_uncompressed"))
        with patch.dict(sys.modules, {"utils.pc_manager": fake_pc_manager}):
            result = self._run(deps, response=json.dumps(candidate))
        self.assertIs(result, True)
        messages = calls["provider"][0]["messages"]
        truth_index = next(i for i, message in enumerate(messages)
                           if message.get("content") == "=== COMMITTED PYTHON COMBATANT STATE (AUTHORITATIVE; NOT CANDIDATE OPERATIONS) ===")
        truth_pack = json.loads(messages[truth_index + 1]["content"])
        self.assertEqual(truth_pack[0]["characterName"], "Acheron")
        self.assertEqual(truth_pack[0]["inventory"], {"currency": {"gold": 0, "silver": 0, "copper": 0},
                                                       "ammunition": [{"name": "crossbow bolts", "quantity": 3}]})
        self.assertNotIn("99", messages[truth_index + 1]["content"])
        self.assertIn("=== INVENTORY OPERATION AUTHORITY ===", messages[truth_index + 2]["content"])
        self.assertEqual(record, state_before)
        self.assertEqual(candidate["actions"][0]["parameters"]["characterName"], "Acheron")

        name_only_selector = {"actions": [{"action": "updateCharacterInfo", "parameters": {
            "characterName": "Acheron", "ops": [{"op": "inventory_remove", "item": "crossbow bolts",
                                                          "quantity": 1}]}}]}
        with patch.dict(sys.modules, {"utils.pc_manager": fake_pc_manager}):
            default_pack = helper_ns["_build_compact_combat_truth_pack"](name_only_selector, encounter)
        self.assertEqual(default_pack[0]["inventory"]["equipment"], [{"name": "crossbow bolts", "quantity": 1}])
        self.assertNotIn("ammunition", default_pack[0]["inventory"])

    def test_inventory_remove_keeps_existing_explicit_ammo_and_wrong_default_mechanics(self):
        with _deny_test_writes(), patch("utils.ai_client_factory.create_chat_client", return_value=SimpleNamespace()):
            from updates.update_character_info import _apply_character_ops_deterministic

        committed = {"ammunition": [{"name": "crossbow bolts", "quantity": 3}], "equipment": []}
        applied, updated, error, _unsupported = _apply_character_ops_deterministic(
            committed, [{"op": "inventory_remove", "item": "crossbow bolts", "quantity": 1,
                         "container": "ammunition"}],
        )
        self.assertTrue(applied, error)
        self.assertEqual(updated["ammunition"][0]["quantity"], 2)

        unchanged = copy.deepcopy(committed)
        applied, defaulted, error, _unsupported = _apply_character_ops_deterministic(
            committed, [{"op": "inventory_remove", "item": "crossbow bolts", "quantity": 1}],
        )
        self.assertFalse(applied)
        self.assertEqual(defaulted, unchanged)
        self.assertIn("cannot remove equipment not present", error)

    def test_deterministic_truncation_route_receives_validation_context(self):
        deps, calls = _dependencies(compression=(True, "threshold_reached"))
        history = [{"role": "user", "content": "x" * 1301} if i == 2 else
                   ({"role": "user", "content": f"turn {i}"} if i % 2 == 0 else
                    {"role": "assistant", "content": f"reply {i}"}) for i in range(15)]
        self.assertTrue(self._run(deps, history=history))
        self.assertEqual(len(calls["provider"]), 1)
        payload = calls["provider"][0]["messages"]
        self.assertTrue(any("with compression" in m["content"] for m in payload if m["role"] == "system"))
        truncated = next(message["content"] for message in payload
                         if message["role"] == "user" and message["content"].startswith("x"))
        self.assertEqual(truncated, "x" * 1200 + " [truncated]")
        self.assertEqual(sum("[truncated]" in message.get("content", "") for message in payload), 1)
        self.assertIn({"role": "user", "content": "turn 10"}, payload)
        self.assertIn({"role": "user", "content": "turn 12"}, payload)

    def test_actual_validation_payload_labels_candidate_and_committed_state(self):
        with _deny_test_writes():
            with open(os.path.join("core", "combat", "combat_manager.py"), "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            helper_names = {
                "_is_combat_inventory_or_ammo_change",
                "_extract_touched_character_updates_from_response_json",
                "_build_compact_combat_truth_pack",
            }
            selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in helper_names]
            helper_ns = {}
            exec(compile(ast.Module(body=selected, type_ignores=[]), "core/combat/combat_manager.py", "exec"), helper_ns)
            from utils.combat_phase_integrity_precheck import validate_already_applied_enemy_replay_precheck
            parity_path = os.path.join("scripts", "test_combat_decomposition_contract.py")
            with open(parity_path, "r", encoding="utf-8") as parity_file:
                parity_tree = ast.parse(parity_file.read())
            hashes_assignment = next(node for node in parity_tree.body
                                     if isinstance(node, ast.Assign)
                                     and any(isinstance(target, ast.Name)
                                             and target.id == "STATIC_PROMPT_HASHES"
                                             for target in node.targets))
            static_prompt_hashes = ast.literal_eval(hashes_assignment.value)
            for relative_path, expected_hash in static_prompt_hashes.items():
                with open(relative_path, "rb") as prompt_file:
                    self.assertEqual(hashlib.sha256(prompt_file.read()).hexdigest(), expected_hash)

            pc_names = ("Acheron", "Merisiel", "Kira", "Vitreol")
            creatures = [{"name": name, "type": "player"} for name in pc_names]
            creatures += [{"name": "Blairen", "type": "npc"},
                          {"name": "Goblin", "type": "enemy", "currentHitPoints": 20, "status": "alive"}]
            encounter = {"encounterId": "fixture-four-pc", "combat_round": 2,
                         "creatures": creatures}
            records = {name.lower(): {
                "name": name, "hitPoints": 20, "maxHitPoints": 20,
                "condition_affected": [], "spellSlots": {}, "deathSaves": {},
                "ammunition": [{"name": "arrow", "quantity": 3}],
                "equipment": [{"item_name": "longsword", "quantity": 1}],
                "currency": {"gold": 2, "silver": 1, "copper": 0},
            } for name in (*pc_names, "Blairen")}
            state_before = copy.deepcopy(records)
            fake_pc_manager = types.ModuleType("utils.pc_manager")
            fake_pc_manager.get_character_state = lambda name: records.get(name.lower())
            fake_candidate = {
                "actions": [
                    {"action": "updateCharacterInfo", "parameters": {
                        "characterName": "Acheron", "changes": "HP 20->12; ALREADY_APPLIED"}},
                    {"action": "updateCharacterInfo", "parameters": {
                        "characterName": "Blairen", "changes": "HP 20->12; ALREADY_APPLIED"}},
                    {"action": "updateCharacterInfo", "parameters": {
                        "characterName": "Acheron", "changes": "Ammunition 3->99"}},
                ]
            }
            # An actual updateCharacterInfo ops-only payload remains candidate-only.
            ops_only = {"actions": [{"action": "updateCharacterInfo", "parameters": {
                "characterName": "Acheron", "ops": [{"op": "hp_delta", "delta": -8}]}}]}
            with patch.dict(sys.modules, {"utils.pc_manager": fake_pc_manager}):
                ops_pack = helper_ns["_build_compact_combat_truth_pack"](ops_only, encounter)
            self.assertEqual(ops_pack[0]["hp"], 20)
            self.assertNotIn("touchedChanges", ops_pack[0])

            candidate_json = json.dumps(fake_candidate, separators=(",", ":"))
            candidate_before = copy.deepcopy(fake_candidate)
            encounter_before = copy.deepcopy(encounter)
            history = [{"role": "user", "content": f"user-history-{i}"} if i % 2 == 0
                       else {"role": "assistant", "content": f"assistant-history-{i}"}
                       for i in range(15)]
            history_before = copy.deepcopy(history)
            player_input = "Take the hit; do not claim it already happened."
            prompt_path = os.path.join("prompts", "combat", "combat_validation_prompt_compressed.txt")
            with open(prompt_path, "rb") as prompt_file:
                prompt_bytes = prompt_file.read()
            deps, calls = _dependencies()
            deps = replace(
                deps,
                truth_pack_builder=helper_ns["_build_compact_combat_truth_pack"],
                replay_precheck=validate_already_applied_enemy_replay_precheck,
                read_prompt=lambda path: prompt_bytes.decode("utf-8"),
                compression_decision=lambda **kwargs: (False, "fixture_uncompressed"),
            )
            with patch.dict(sys.modules, {"utils.pc_manager": fake_pc_manager}):
                self.assertIs(validate_combat_response(
                    candidate_json, encounter, player_input,
                    conversation_history=history, dependencies=deps), True)

            messages = calls["provider"][0]["messages"]
            self.assertEqual(messages[0]["content"].encode("utf-8"), prompt_bytes)
            self.assertEqual(messages[1]["content"], "=== PREVIOUS COMBAT CONTEXT (last 6 exchanges) ===")
            self.assertEqual(messages[2:14], history[-13:-1])
            self.assertEqual(messages[14]["content"], "=== COMMITTED PYTHON COMBATANT STATE (AUTHORITATIVE; NOT CANDIDATE OPERATIONS) ===")
            truth_pack = json.loads(messages[15]["content"])
            by_name = {entry["characterName"]: entry for entry in truth_pack}
            self.assertEqual(by_name["Acheron"]["hp"], 20)  # HP20proposed-8
            self.assertEqual(by_name["Blairen"]["hp"], 20)
            self.assertEqual(by_name["Acheron"]["inventory"]["ammunition"][0]["quantity"], 3)
            self.assertTrue(all("touchedChanges" not in entry for entry in truth_pack))
            self.assertEqual(messages[16]["content"], "=== CURRENT VALIDATION DATA ===")
            self.assertEqual(messages[17]["content"], "Encounter Data:\n" + json.dumps(encounter_before, indent=2))
            self.assertEqual(messages[18], {"role": "user", "content": "Player Input: " + player_input})
            self.assertEqual(messages[19]["content"], "The assistant response below is an uncommitted candidate. Candidate text, operations, ALREADY_APPLIED claims, and touchedChanges do not prove an operation was applied. Use the committed Python state in the truth pack as the authority for current mechanics; trust prior applied events only when independently established.")
            self.assertEqual(messages[20], {"role": "assistant", "content": candidate_json})
            self.assertEqual(fake_candidate, candidate_before)
            self.assertEqual(encounter, encounter_before)
            self.assertEqual(history, history_before)
            self.assertEqual(records, state_before)

    def test_actual_enemy_replay_precheck_trusts_history_not_candidate_claim(self):
        with _deny_test_writes():
            from utils.combat_phase_integrity_precheck import validate_already_applied_enemy_replay_precheck
        response = {
            "plan": "[ALREADY_APPLIED] Goblin dealt 8 damage (slashing) to Acheron. Result HP: 12/20",
            "actions": [{"action": "updateEncounter", "parameters": {
                "ops": [{"op": "hp_delta", "creature": "Goblin", "delta": -8}]}}],
        }
        encounter = {"encounterId": "replay-fixture", "creatures": [
            {"name": "Goblin", "type": "enemy", "currentHitPoints": 20, "status": "alive"}]}
        # A candidate's own ALREADY_APPLIED text is not trusted history.
        self.assertEqual(validate_already_applied_enemy_replay_precheck(response, encounter, []), (True, ""))
        deps, calls = _dependencies()
        deps = replace(deps, replay_precheck=validate_already_applied_enemy_replay_precheck)
        candidate_text = json.dumps(response)
        self.assertIs(validate_combat_response(candidate_text, encounter, "continue", dependencies=deps), True)
        self.assertEqual(len(calls["provider"]), 1)

        trusted_history = [{"role": "assistant", "content":
            "[ALREADY_APPLIED] dealt 8 damage (slashing) to Goblin. Result HP: 12/20"}]
        response_before, encounter_before, history_before = (
            copy.deepcopy(response), copy.deepcopy(encounter), copy.deepcopy(trusted_history))
        deps, rejected_calls = _dependencies()
        deps = replace(deps, replay_precheck=validate_already_applied_enemy_replay_precheck)
        result = validate_combat_response(
            candidate_text, encounter, "continue", conversation_history=trusted_history, dependencies=deps)
        self.assertIn("duplicate enemy hp_delta re-applied the same committed damage", result)
        self.assertEqual(rejected_calls["provider"], [])
        self.assertEqual(response, response_before)
        self.assertEqual(encounter, encounter_before)
        self.assertEqual(trusted_history, history_before)

    def test_invalid_provider_json_retries_then_accepts_valid_response(self):
        deps, calls = _dependencies(completions=[_provider_result("not-json"), _provider_result('{"valid":true,"feedback":{}}')])
        self.assertIs(self._run(deps), True)
        self.assertEqual(len(calls["provider"]), 2)

    def test_five_malformed_provider_responses_keep_nonterminal_exhaustion_fail_open(self):
        deps, calls = _dependencies(completions=[_provider_result("not-json") for _ in range(5)])
        self.assertIs(self._run(deps), True)
        self.assertEqual(len(calls["provider"]), 5)
        self.assertEqual(len(calls["api_log"]), 5)
        self.assertEqual(len(calls["usage"]), 5)

    def test_api_errors_keep_existing_five_attempt_exhaustion_fallback(self):
        deps, calls = _dependencies(completions=[RuntimeError("fixture API error") for _ in range(5)])
        self.assertIs(self._run(deps), True)
        self.assertLessEqual(len(calls["provider"]), 5)
        self.assertEqual(calls["open"], [])

    def test_inner_retry_exhaustion_keeps_five_ordered_attempts(self):
        deps, calls = _dependencies(completions=[RuntimeError(f"provider error {attempt}") for attempt in range(5)])
        self.assertIs(self._run(deps), True)
        self.assertLessEqual(len(calls["provider"]), 5)
        self.assertEqual([call["messages"][0]["content"] for call in calls["provider"]], [
            "frozen prompt:combat/combat_validation_prompt_compressed.txt"
        ] * 5)
        self.assertEqual(len(calls["api_log"]), 0)
        self.assertEqual(
            [entry[0][0] for entry in calls["debug"] if "Validation error -" in entry[0][0]],
            [f"VALIDATION: Validation error - provider error {attempt}" for attempt in range(5)],
        )

    def test_validation_rejection_returns_full_feedback_without_provider_retry(self):
        deps, calls = _dependencies(completions=[_provider_result(json.dumps({"valid": False, "feedback": {
            "positive": "good", "negative": "HP mismatch", "recommendation": "fix HP"}}))])
        result = self._run(deps)
        self.assertIn("HP mismatch", result)
        self.assertEqual(len(calls["provider"]), 1)

    def test_legacy_validation_wrapper_uses_currently_patched_owner_bindings(self):
        bootstrap_client = SimpleNamespace()
        provider_calls = []

        def fake_create(**kwargs):
            provider_calls.append(kwargs)
            raise AssertionError("validation precheck should stop before provider call")

        patched_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
        real_open = builtins.open

        def deny_write(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise ExternalWriteDenied(f"blocked import-time write: {file}")
            return real_open(file, mode, *args, **kwargs)

        with patch("utils.ai_client_factory.create_chat_client", return_value=bootstrap_client), \
             patch("os.makedirs", return_value=None), \
             patch("builtins.open", side_effect=deny_write):
            owner = importlib.import_module("core.combat.combat_manager")

        phase_calls = []

        def patched_phase_precheck(*args, **kwargs):
            phase_calls.append((args, kwargs))
            return False, "patched phase guard"

        class Manager:
            combat_phase = "PC_PHASE"
            pc_phase_complete = False

            def get_available_pcs(self):
                return []

            def get_forbidden_actors(self):
                return []

            def get_remaining_enemies_for_round(self):
                return []

        with patch.object(owner, "client", patched_client), \
             patch.object(owner, "parse_json_safely", json.loads), \
             patch.object(owner, "validate_combat_phase_integrity_precheck", patched_phase_precheck):
            result = owner.validate_combat_response(
                '{"combat_round":2,"actions":[]}',
                {"combat_round":2,"creatures":[]},
                "hold position",
                conversation_history=[],
                multi_pc_manager=Manager(),
            )

        self.assertIn("patched phase guard", result)
        self.assertEqual(len(phase_calls), 1)
        self.assertEqual(provider_calls, [])

    def test_real_facade_and_receipt_adapter_drive_actual_validator(self):
        import utils.ai_client_factory as factory
        import utils.llm_router as router_module
        from utils.llm_runtime import make_legacy_receipt_observer
        from utils.llm_router import GameLLMTerminalError

        class FakeSDKClient:
            def __init__(self, scripted, events):
                self.scripted = list(scripted)
                self.events = events
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def with_options(self, **kwargs):
                self.events.append(("client_options", kwargs))
                return self

            def create(self, **kwargs):
                self.events.append(("sdk", kwargs))
                item = self.scripted.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        def sdk_response(text, *, refusal=None, finish_reason="stop"):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=text, refusal=refusal),
                    finish_reason=finish_reason,
                )],
                model="fixture-resolved",
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2, total_tokens=6),
            )

        def run(script):
            events, sdk_events, facade_calls = [], [], []
            tracker = SimpleNamespace(track=lambda raw, metadata: events.append(("usage", raw, metadata)))
            observer_factory = lambda **kwargs: make_legacy_receipt_observer(
                **kwargs,
                tracker_getter=lambda: tracker,
                api_logger=lambda endpoint, messages, raw, metadata: events.append(("api", endpoint, messages, raw, metadata)),
                trace_gate=lambda: True,
                trace_writer=lambda kind, **fields: events.append(("trace", kind, fields)),
            )
            client = FakeSDKClient(script, sdk_events)
            deps, _ = _dependencies()

            def actual_facade(task, messages, **kwargs):
                facade_calls.append({"task": task, "messages": copy.deepcopy(messages), **kwargs})
                return router_module.llm.call(task, messages, **kwargs)

            deps = replace(deps, llm_call=actual_facade, receipt_observer_factory=observer_factory,
                           usage_tracking_available=True)
            with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
                 patch.object(factory, "create_chat_client", return_value=client):
                result = self._run(deps)
            return result, facade_calls, sdk_events, events

        result, facade_calls, sdk_events, events = run([sdk_response('  {"valid":true,"feedback":{}}  ')])
        self.assertIs(result, True)
        self.assertEqual(len(facade_calls), 1)
        self.assertEqual(facade_calls[0]["task"], "combat_validation")
        self.assertIs(facade_calls[0]["json_output"], False)
        self.assertEqual(facade_calls[0]["temperature"], 0.3)
        self.assertNotIn("timeout", facade_calls[0])
        self.assertEqual(len([event for event in sdk_events if event[0] == "sdk"]), 1)
        self.assertEqual([event[0] for event in events], ["trace", "api", "usage"])
        self.assertEqual(events[1][1], "combat_validation")
        self.assertEqual(events[1][2], facade_calls[0]["messages"])
        self.assertEqual(events[1][4]["attempt"], 1)
        self.assertEqual(events[1][4]["temperature"], 0.3)
        self.assertEqual(events[1][4]["requested_model"], events[0][2]["requested_model"])
        self.assertEqual(events[1][4]["resolved_model"], "fixture-resolved")
        self.assertEqual(events[2][2]["task"], "combat_validation")

        for terminal_kind, scripted in (
            ("quota", [RuntimeError("insufficient_quota")]),
            ("refusal", [sdk_response(None, refusal="refused")]),
            ("content_filter", [sdk_response(None, finish_reason="content_filter")]),
        ):
            with self.subTest(terminal=terminal_kind):
                events, sdk_events, facade_calls = [], [], []
                client = FakeSDKClient(scripted, sdk_events)
                deps, _ = _dependencies()
                tracker = SimpleNamespace(track=lambda raw, metadata: events.append(("usage", raw, metadata)))
                deps = replace(
                    deps,
                    llm_call=lambda task, messages, **kwargs: router_module.llm.call(task, messages, **kwargs),
                    receipt_observer_factory=lambda **kwargs: make_legacy_receipt_observer(
                        **kwargs,
                        tracker_getter=lambda: tracker,
                        api_logger=lambda *a, **k: events.append(("api", a, k)),
                        trace_gate=lambda: True,
                        trace_writer=lambda name, **fields: events.append(("trace", name, fields)),
                    ),
                    usage_tracking_available=True,
                )
                with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
                     patch.object(factory, "create_chat_client", return_value=client) as make_client:
                    with self.assertRaises(GameLLMTerminalError) as caught:
                        self._run(deps)
                self.assertEqual(caught.exception.terminal_kind, terminal_kind)
                self.assertEqual(len([event for event in sdk_events if event[0] == "sdk"]), 1)
                self.assertEqual(make_client.call_count, 1)
                if terminal_kind == "quota":
                    self.assertFalse(any(event[0] in ("api", "usage") for event in events))
                    self.assertEqual([event[0] for event in events], ["trace"])
                else:
                    self.assertEqual([event[0] for event in events], ["trace", "api", "usage"])

        late_sdk_events, late_events = [], []
        late_client = FakeSDKClient(
            [sdk_response("not-json"), RuntimeError("insufficient_quota")], late_sdk_events
        )
        late_deps, _ = _dependencies()
        late_tracker = SimpleNamespace(track=lambda raw, metadata: late_events.append(("usage", raw, metadata)))
        late_deps = replace(
            late_deps,
            llm_call=lambda task, messages, **kwargs: router_module.llm.call(task, messages, **kwargs),
            receipt_observer_factory=lambda **kwargs: make_legacy_receipt_observer(
                **kwargs,
                tracker_getter=lambda: late_tracker,
                api_logger=lambda *a, **k: late_events.append(("api", a, k)),
                trace_gate=lambda: True,
                trace_writer=lambda name, **fields: late_events.append(("trace", name, fields)),
            ),
            usage_tracking_available=True,
        )
        with patch.object(factory, "_get_actual_provider", return_value=("openai", False)), \
             patch.object(factory, "create_chat_client", return_value=late_client):
            with self.assertRaises(GameLLMTerminalError):
                self._run(late_deps)
        self.assertEqual(len([event for event in late_sdk_events if event[0] == "sdk"]), 2)
        self.assertEqual([event[0] for event in late_events], ["trace", "api", "usage", "trace"])


if __name__ == "__main__":
    unittest.main()
