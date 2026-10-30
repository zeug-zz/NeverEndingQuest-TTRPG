# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for G5 fixture identity and trace attribution."""

from __future__ import annotations

import json
import hashlib
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import the capture owners through the existing guarded fixture harness. That
# harness arms filesystem/network tripwires before loading capture/runtime code.
from scripts import test_capture_drive as guarded_capture_import

capture_drive = guarded_capture_import.capture_drive
capture_evidence = guarded_capture_import.capture_evidence
fixtures = guarded_capture_import.fixtures
combat_latency_trace = guarded_capture_import.combat_latency_trace

from core.combat.turn import (
    CombatRetryDependencies,
    CombatRetryInputs,
    run_combat_provider_retry_stage,
)


def _driver_windows(party_size, action_ms=10000.0, batch_ms=120000.0):
    fixture = fixtures.build_gate_profile("g5", "combat-smoke", party_size)["fixture"]
    cursor = 2000.0
    rows = []
    for step in fixture["steps"]:
        duration = batch_ms if step["unit_type"] == "batch" else action_ms
        rows.append({"step": step["index"], "unit_type": step["unit_type"],
                     "unit_id": step["unit_id"], "round": step["round"],
                     "start_epoch_ms": cursor, "end_epoch_ms": cursor + duration})
        cursor += duration + 1000.0
    return {"status": "captured", "startup": {"start_epoch_ms": 0.0,
            "end_epoch_ms": rows[0]["start_epoch_ms"]},
            "steps": rows, "teardown": {"start_epoch_ms": rows[-1]["end_epoch_ms"],
                                          "end_epoch_ms": cursor}}


def _run_retry_trace_case(responses, validation_results, *, integrity_results=None,
                          multiple_results=None):
    legacy_contexts = []
    remaining_responses = list(responses)
    remaining_validation = list(validation_results)
    remaining_integrity = list(integrity_results or [True] * len(responses))
    remaining_multiple = list(multiple_results or [False] * len(responses))

    def observer_factory(**kwargs):
        legacy_contexts.append(kwargs["legacy_context"])
        return lambda *_args, **_kwargs: None

    def llm_call(_task, _messages, **_kwargs):
        return remaining_responses.pop(0)

    def valid_json(value):
        try:
            return isinstance(json.loads(value), dict)
        except (TypeError, ValueError):
            return False

    dependencies = CombatRetryDependencies(
        client=object(),
        use_gpt5_models=False,
        gpt5_mini_model="fixture-mini",
        gpt5_high_reasoning_on_retry=True,
        combat_main_model="fixture-main",
        get_completion_params=lambda _role, model, **kwargs: {"model": model, **kwargs},
        get_temperature=lambda *_args, **_kwargs: 0.2,
        perf_counter=lambda: 1.0,
        trace_stage=lambda *_args, **_kwargs: None,
        trace_provider_call=lambda *_args, **_kwargs: None,
        export_open=lambda *_args, **_kwargs: None,
        makedirs=lambda *_args, **_kwargs: None,
        emit=lambda *_args, **_kwargs: None,
        debug=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        usage_tracking_available=False,
        track_usage=lambda *_args, **_kwargs: None,
        is_valid_json=valid_json,
        check_multiple_update_encounter=lambda _actions: remaining_multiple.pop(0),
        make_multiple_update_feedback=lambda _parsed: "multiple update correction",
        validate_combatant_integrity=lambda *_args, **_kwargs: remaining_integrity.pop(0),
        validate_combat_response=lambda *_args, **_kwargs: remaining_validation.pop(0),
        update_status=lambda *_args, **_kwargs: None,
        debug_dumps_enabled=lambda: False,
        llm_call=llm_call,
        receipt_observer_factory=observer_factory,
    )
    inputs = CombatRetryInputs(
        conversation_history=[{"role": "system", "content": "seed"},
                              {"role": "user", "content": "attack"}],
        initial_conversation_length=2,
        encounter_data={"encounterId": "fixture", "creatures": []},
        party_tracker_data={"partyMembers": ["Acheron"]},
        multi_pc_manager=None,
        user_input_text="attack",
        max_retries=len(responses),
    )
    result = run_combat_provider_retry_stage(inputs, dependencies)
    return result, legacy_contexts


class CombatG5FixtureTests(unittest.TestCase):
    def test_fixed_p1_and_p4_metadata_hashes_the_exact_driver_step_list(self):
        expected = {
            1: {"nominal_label": "1 PC x 1 round", "scripted_step_count": 3, "actions": 2},
            4: {"nominal_label": "4 PCs x 3 rounds + 1 enemy batch",
                "scripted_step_count": 26, "actions": 24},
        }
        for party_size, facts in expected.items():
            with self.subTest(party_size=party_size):
                profile = fixtures.build_gate_profile("g5", "combat-smoke", party_size)
                metadata = profile["fixture"]
                script = (fixtures.build_one_pc_command_script() if party_size == 1
                          else fixtures.build_command_script())
                expected_hash = hashlib.sha256(
                    json.dumps(script, separators=(",", ":"), ensure_ascii=True).encode("ascii")
                ).hexdigest()
                self.assertEqual(metadata["nominal_label"], facts["nominal_label"])
                self.assertEqual(metadata["script_source"],
                                 "build_one_pc_command_script" if party_size == 1 else
                                 "build_command_script")
                self.assertEqual(metadata["scripted_step_count"], facts["scripted_step_count"])
                self.assertEqual(metadata["steps_sha256"], expected_hash)
                self.assertEqual(len(metadata["work_units"]["actions"]), facts["actions"])
                self.assertEqual(len(metadata["work_units"]["batches"]), 1)
                self.assertEqual(len(metadata["work_units"]["controls"]), 1 if party_size == 4 else 0)
                self.assertRegex(metadata["steps_sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(metadata["measurement_method"]["id"], "g5-driver-window-work-quiet-v2")
                self.assertTrue(all("input" not in step for step in metadata["steps"]))
                self.assertNotIn("rounds", metadata)
                self.assertNotIn("enemy_batches", metadata)
                self.assertNotIn("sentinel prompt text", json.dumps(metadata))

    def test_g5_driver_sends_the_existing_p1_and_p4_scripts_unchanged(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                session = object.__new__(capture_drive.CaptureSession)
                session.party = party_size
                session.current_character = "Acheron"
                sent = []
                session.send_turn = lambda label, text, character: sent.append(
                    (label, text, character)
                )
                session.combat_ended = lambda: False
                session.log = lambda *_args, **_kwargs: None

                capture_drive.CaptureSession.run_g5_scenario(session)

                expected = [(row["label"], row["input"], row["character"])
                            for row in fixtures.build_g5_script_steps(party_size)]
                self.assertEqual(sent, expected)
                source_script = (fixtures.build_one_pc_command_script() if party_size == 1
                                 else fixtures.build_command_script())
                self.assertEqual(len(sent), len(source_script))
                if party_size == 4:
                    self.assertEqual(sent[0][1], "/init 18")
                    self.assertEqual(len([row for row in sent if row[1] == "/end"]), 1)

    def test_g3_and_g4_profile_contracts_do_not_gain_g5_metadata(self):
        for gate in ("g3", "g4"):
            profile = fixtures.build_gate_profile(gate, "combat-smoke", 1)
            self.assertNotIn("fixture", profile)
            self.assertEqual(profile, fixtures.build_gate_profile(gate, "combat-smoke", 1))
        self.assertEqual(capture_drive.build_parser().parse_args(["--party", "1"]).gate, "g3")


class CombatG5TraceTests(unittest.TestCase):
    def test_work_unit_ids_are_bounded_and_contain_no_action_text(self):
        pc = combat_latency_trace.build_work_unit_trace_context(2, "PC_PHASE", "Acheron")
        batch = combat_latency_trace.build_work_unit_trace_context(2, "ENEMY_PHASE", "sentinel prompt text")
        self.assertEqual(pc, {"action_id": "pc:r2:acheron"})
        self.assertEqual(batch, {"batch_id": "enemy:r2"})
        self.assertLessEqual(len(pc["action_id"]), 80)
        self.assertNotIn("sentinel", json.dumps(batch))
        self.assertEqual(combat_latency_trace.build_work_unit_trace_context(
            10 ** 100, "PC_PHASE", "Acheron"), {})

    def test_fast_pc_command_trace_uses_input_actor_after_mid_round_switch(self):
        manager = guarded_capture_import.MultiPCCombatManager()
        manager._state.pc_states = {
            "Acheron": guarded_capture_import.PCCombatState(
                "Acheron", current_hp=231, max_hp=231, ac=15,
            ),
            "Merisiel": guarded_capture_import.PCCombatState(
                "Merisiel", current_hp=40, max_hp=40, ac=16,
            ),
        }
        # The turn-loop context was established while Acheron was current, but
        # this command carries Merisiel's explicit actor identity.
        manager._state.current_pc_name = "Acheron"
        manager._state.current_round = 2
        manager._turns.turn_queue = [
            guarded_capture_import.Combatant(
                "Goblin Squad A", guarded_capture_import.CombatantType.ENEMY,
                10, 20, 20, 15,
            ),
        ]
        encounter = {
            "encounterId": "trace-actor-switch",
            "combat_round": 2,
            "creatures": [{
                "name": "Goblin Squad A", "type": "enemy", "status": "alive",
                "currentHitPoints": 20, "maxHitPoints": 20, "armorClass": 15,
            }],
        }
        prior_context = dict(combat_latency_trace._TRACE_CONTEXT)
        scratch = tempfile.TemporaryDirectory(
            prefix="pc-command-trace-", dir="tmp/router-rollout/g5t"
        )
        self.addCleanup(scratch.cleanup)
        trace_path = pathlib.Path(scratch.name) / "trace.jsonl"
        self.addCleanup(
            lambda: (combat_latency_trace._TRACE_CONTEXT.clear(),
                     combat_latency_trace._TRACE_CONTEXT.update(prior_context))
        )

        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
            result = manager.handle_combat_command(
                "/att Goblin Squad A 20 training blade",
                encounter,
                actor_name="Merisiel",
                active_encounter_id="trace-actor-switch",
            )

        self.assertTrue(result[0])
        rows = [
            json.loads(line)
            for line in trace_path.read_text(encoding="ascii").splitlines()
        ]
        fast_path_rows = [
            row for row in rows
            if row.get("decision_point") == "combat_command_fast_path"
        ]
        self.assertTrue(fast_path_rows)
        self.assertTrue(all(row.get("action_id") == "pc:r2:merisiel"
                            for row in fast_path_rows))

    def test_enemy_batch_decisions_use_bounded_outcomes_and_reasons(self):
        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_decision", return_value=True) as writer:
            self.assertTrue(combat_latency_trace.trace_enemy_batch_decision(
                "resolver_supported", "ledger_supported", "enemy:r1", 1.0
            ))
            self.assertTrue(combat_latency_trace.trace_enemy_batch_decision(
                "whole_batch_fallback", "round_transition_unsupported", "enemy:r2", 1.0
            ))
            self.assertTrue(combat_latency_trace.trace_enemy_batch_decision(
                "resolver_disabled", "resolver_disabled", "enemy:r3", 1.0
            ))
            self.assertFalse(combat_latency_trace.trace_enemy_batch_decision(
                "unsupported_outcome", "ledger_supported", "enemy:r4", 1.0
            ))
            self.assertFalse(combat_latency_trace.trace_enemy_batch_decision(
                "whole_batch_fallback", "free form reason", "enemy:r4", 1.0
            ))
            self.assertFalse(combat_latency_trace.trace_enemy_batch_decision(
                "whole_batch_fallback", "ledger_supported", "enemy:r_4", 1.0
            ))

        self.assertEqual(writer.call_count, 3)
        calls = [call.args + (call.kwargs,) for call in writer.call_args_list]
        self.assertEqual(calls[0][0:2], ("enemy_batch_resolution", "deterministic"))
        self.assertTrue(calls[0][3]["provider_call_avoided"])
        self.assertEqual(calls[0][3]["decision_outcome"], "resolver_supported")
        self.assertEqual(calls[1][1], "llm_fallback")
        self.assertFalse(calls[1][3]["provider_call_avoided"])
        self.assertEqual(calls[2][3]["decision_outcome"], "resolver_disabled")

    def test_resolver_decision_and_parity_observations_replace_stale_pc_action_id(self):
        prior_context = dict(combat_latency_trace._TRACE_CONTEXT)
        scratch = tempfile.TemporaryDirectory(prefix="resolver-context-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        target = pathlib.Path(scratch.name) / "trace.jsonl"
        try:
            with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                    patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", target):
                combat_latency_trace.set_trace_context(
                    mode="mp", phase="PC_PHASE", combat_round=1,
                    action_id="pc:r1:acheron",
                )
                self.assertTrue(combat_latency_trace.trace_enemy_batch_decision(
                    "resolver_supported", "ledger_supported", "enemy:r1", 1.0,
                    logical_turn=1,
                ))
                self.assertTrue(combat_latency_trace.trace_combat_observation(
                    "combat_batch_narration_result", batch_id="enemy:r1",
                    logical_turn=1, source="llm",
                ))
            rows = [json.loads(line) for line in target.read_text(encoding="ascii").splitlines()]
            self.assertEqual(len(rows), 2)
            for event in rows:
                self.assertEqual(event["batch_id"], "enemy:r1")
                self.assertEqual(event["mode"], "mp")
                self.assertNotIn("action_id", event)
            self.assertEqual(rows[0]["event_type"], "decision")
            self.assertEqual(rows[1]["observation"], "combat_batch_narration_result")
        finally:
            with combat_latency_trace._TRACE_LOCK:
                combat_latency_trace._TRACE_CONTEXT.clear()
                combat_latency_trace._TRACE_CONTEXT.update(prior_context)

    def test_enemy_batch_trace_gate_and_writer_exceptions_are_fail_open(self):
        with patch.object(combat_latency_trace, "trace_enabled", return_value=False), \
                patch.object(combat_latency_trace, "emit_trace_event") as writer:
            self.assertFalse(combat_latency_trace.trace_enemy_batch_decision(
                "resolver_supported", "ledger_supported", "enemy:r1", 1.0
            ))
            self.assertFalse(combat_latency_trace.trace_batch_file_write(
                "enemy:r1", "character", "characters/acheron.json"
            ))
            writer.assert_not_called()

        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "emit_trace_event", side_effect=OSError("trace unavailable")):
            self.assertFalse(combat_latency_trace.trace_batch_file_write(
                "enemy:r1", "character", "characters/acheron.json"
            ))

    def test_validator_rejection_is_the_only_retry_cause_attributed(self):
        valid_response = '{"narration":"The goblin advances.","actions":[]}'
        result, contexts = _run_retry_trace_case(
            [valid_response, valid_response], ["validator rejected", True]
        )
        self.assertTrue(result.valid_response)
        self.assertEqual(len(contexts), 2)
        self.assertNotIn("retry_cause", contexts[0])
        self.assertEqual(contexts[1].get("retry_cause"), "validator_rejection")

        _, json_contexts = _run_retry_trace_case(
            ["not-json", valid_response], [True]
        )
        self.assertEqual(len(json_contexts), 2)
        self.assertTrue(all("retry_cause" not in context for context in json_contexts))

        _, integrity_contexts = _run_retry_trace_case(
            [valid_response, valid_response], [True], integrity_results=["bad actor", True]
        )
        self.assertEqual(len(integrity_contexts), 2)
        self.assertTrue(all("retry_cause" not in context for context in integrity_contexts))

    def test_g5_environment_run_id_is_added_to_existing_trace_events_only(self):
        prior_context = dict(combat_latency_trace._TRACE_CONTEXT)
        scratch = tempfile.TemporaryDirectory(prefix="g5-trace-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        target = pathlib.Path(scratch.name) / "trace.jsonl"
        try:
            with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                    patch.dict(os.environ, {"NEQ_G5_CAPTURE_RUN_ID": "run-g5-unit_01"}):
                combat_latency_trace.set_trace_context()
                self.assertTrue(combat_latency_trace.emit_trace_event("stage", path=target, stage="turn_start"))
                row = json.loads(target.read_text(encoding="ascii"))
                self.assertEqual(row["run_id"], "run-g5-unit_01")
            with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                    patch.dict(os.environ, {"NEQ_G5_CAPTURE_RUN_ID": ""}):
                self.assertTrue(combat_latency_trace.emit_trace_event("stage", path=target, stage="turn_end"))
                ordinary_row = json.loads(target.read_text(encoding="ascii").splitlines()[1])
                self.assertNotIn("run_id", ordinary_row)
        finally:
            with combat_latency_trace._TRACE_LOCK:
                combat_latency_trace._TRACE_CONTEXT.clear()
                combat_latency_trace._TRACE_CONTEXT.update(prior_context)

    def test_oversized_g5_trace_fallback_keeps_run_and_work_unit_identity(self):
        prior_context = dict(combat_latency_trace._TRACE_CONTEXT)
        scratch = tempfile.TemporaryDirectory(prefix="g5-trace-bound-", dir="tmp")
        self.addCleanup(scratch.cleanup)
        target = pathlib.Path(scratch.name) / "trace.jsonl"
        try:
            with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                    patch.dict(os.environ, {"NEQ_G5_CAPTURE_RUN_ID": "run-g5-bounded"}):
                combat_latency_trace.set_trace_context(action_id="pc:r2:acheron")
                large_fields = {"field_%02d" % index: "x" * 512 for index in range(32)}
                self.assertTrue(combat_latency_trace.emit_trace_event(
                    "provider", path=target, **large_fields
                ))
                encoded = target.read_bytes()
                row = json.loads(encoded.decode("ascii"))
                self.assertLessEqual(len(encoded), combat_latency_trace.MAX_RECORD_BYTES)
                self.assertTrue(row["fields_truncated"])
                self.assertEqual(row["run_id"], "run-g5-bounded")
                self.assertEqual(row["action_id"], "pc:r2:acheron")
        finally:
            with combat_latency_trace._TRACE_LOCK:
                combat_latency_trace._TRACE_CONTEXT.clear()
                combat_latency_trace._TRACE_CONTEXT.update(prior_context)

    def test_provider_and_write_counts_group_by_action_or_enemy_batch(self):
        windows = _driver_windows(1)
        action_1 = windows["steps"][0]
        batch = windows["steps"][2]
        events = [
            {"event_type": "provider", "run_id": "run-g5", "action_id": "pc:r1:acheron",
             "recorded_at_ms": action_1["start_epoch_ms"] + 100,
             "provider": "openai", "resolved_model": "gpt-6-luna", "task": "combat_main",
             "prompt_text": "sentinel prompt text"},
            {"event_type": "file_operation", "run_id": "run-g5", "action_id": "pc:r1:acheron",
             "recorded_at_ms": action_1["start_epoch_ms"] + 200,
             "category": "write", "site": "encounter_save"},
            {"event_type": "provider", "run_id": "run-g5", "batch_id": "enemy:r1",
             "recorded_at_ms": batch["start_epoch_ms"] + 100,
             "provider": "openai", "resolved_model": "gpt-6-luna", "task": "combat_main"},
            {"event_type": "file_operation", "run_id": "run-g5", "batch_id": "enemy:r1",
             "recorded_at_ms": batch["start_epoch_ms"] + 200,
             "category": "write", "site": "encounter_save"},
            {"event_type": "stage", "run_id": "run-g5", "prompt_text": "sentinel prompt text"},
        ]
        events[-1]["recorded_at_ms"] = 1000.0
        projection = capture_evidence.project_g5_trace(events, "run-g5", trace_windows=windows)
        self.assertEqual(projection["status"], "PASS")
        self.assertEqual(projection["counts"]["provider_calls"], 2)
        self.assertEqual(projection["counts"]["file_writes"], 2)
        by_id = {row["id"]: row for row in projection["work_units"]}
        self.assertEqual(by_id["action-step-001"]["provider_calls"], 1)
        self.assertEqual(by_id["action-step-001"]["file_writes"], 1)
        self.assertEqual(by_id["batch-step-003"]["provider_calls"], 1)
        self.assertEqual(by_id["batch-step-003"]["file_writes"], 1)
        self.assertEqual(projection["observed_rounds"], [1])
        self.assertEqual(projection["observed_enemy_batches"], ["batch-step-003"])
        self.assertEqual(projection["counts"]["startup_provider_calls"], 0)
        self.assertEqual(projection["window_buckets"][0]["bucket"], "startup")
        self.assertNotIn("sentinel prompt text", json.dumps(projection))

    def test_g5_live_shape_attributes_enemy_batch_by_driver_window_not_runtime_phase(self):
        windows = _driver_windows(4, action_ms=10.0, batch_ms=120000.0)
        batch_window = next(row for row in windows["steps"] if row["unit_type"] == "batch")
        action_windows = [row for row in windows["steps"] if row["unit_type"] == "action"][:2]
        events = [{"event_type": "provider", "run_id": "run-g5", "recorded_at_ms": 1000.0,
                   "provider": "openai", "resolved_model": "gpt-6-luna", "task": "combat_main"}]
        for index in range(10):
            events.append({"event_type": "provider", "run_id": "run-g5",
                           "recorded_at_ms": batch_window["start_epoch_ms"] + 1000 + index * 1000,
                           "phase": "PC_PHASE", "combat_round": 2,
                           "action_id": "pc:r2:acheron", "provider": "openai",
                           "resolved_model": "gpt-6-luna", "task": "combat_main"})
        for step in action_windows:
            events.append({"event_type": "decision", "run_id": "run-g5",
                           "recorded_at_ms": step["start_epoch_ms"] + 1,
                           "phase": "PC_PHASE", "action_id": "pc:r1:acheron",
                           "decision_point": "combat_command_fast_path"})
        projection = capture_evidence.project_g5_trace(events, "run-g5", trace_windows=windows)
        by_id = {row["id"]: row for row in projection["work_units"]}
        self.assertEqual(projection["status"], "PASS")
        self.assertEqual(projection["counts"]["startup_provider_calls"], 1)
        self.assertEqual(by_id[action_windows[0]["unit_id"]]["provider_calls"], 0)
        self.assertEqual(by_id[action_windows[1]["unit_id"]]["provider_calls"], 0)
        self.assertEqual(by_id[batch_window["unit_id"]]["provider_calls"], 10)
        self.assertNotIn("pc:r2:acheron", {row["id"] for row in projection["work_units"]})
        batch_receipts = [row for row in projection["provider_receipts"]
                          if row["work_unit_id"] == batch_window["unit_id"]]
        self.assertEqual(len(batch_receipts), 10)
        self.assertTrue(all(row.get("runtime_action_id") == "pc:r2:acheron"
                            for row in batch_receipts))
        self.assertGreater(batch_window["end_epoch_ms"] - batch_window["start_epoch_ms"], 115000.0)

    def test_legacy_compression_provider_counts_in_its_driver_window_without_core_identity(self):
        windows = _driver_windows(4, batch_ms=40000.0)
        batch_window = next(row for row in windows["steps"] if row["unit_type"] == "batch")
        events = [{
            "event_type": "provider", "schema_version": 1, "run_id": "run-g5",
            "site": "combat_compression", "mode": "mp", "combat_round": 1,
            "phase": "PC_PHASE", "action_id": "pc:r1:vitreol",
            "elapsed_ms": 4994.07, "prompt_tokens": 2680,
            "completion_tokens": 473, "total_tokens": 3153,
            "recorded_at_ms": batch_window["start_epoch_ms"] + 4999.934,
        }]

        projection = capture_evidence.project_g5_trace(events, "run-g5", trace_windows=windows)
        by_id = {row["id"]: row for row in projection["work_units"]}
        batch = by_id[batch_window["unit_id"]]
        self.assertEqual(projection["status"], "PASS")
        self.assertEqual(projection["counts"]["provider_calls"], 1)
        self.assertEqual(projection["counts"]["legacy_provider_observations"], 1)
        self.assertEqual(batch["provider_calls"], 1)
        self.assertEqual(batch["legacy_provider_calls"], 1)
        self.assertEqual(batch["legacy_provider_elapsed_ms"], 4994.07)
        self.assertEqual(batch["round"], 1)
        self.assertEqual(projection["work_units"][0]["provider_calls"], 0)
        self.assertEqual(projection["provider_receipts"][0]["classification"],
                         "known_unmigrated_compression_observation")
        self.assertEqual(projection["provider_receipts"][0]["identity_status"],
                         "no_router_attempt_identity")
        self.assertEqual(projection["provider_receipts"][0]["runtime_action_id"],
                         "pc:r1:vitreol")

    def test_router_compression_provider_keeps_the_same_g5_batch_call_count(self):
        windows = _driver_windows(4, batch_ms=40000.0)
        batch_window = next(row for row in windows["steps"] if row["unit_type"] == "batch")
        recorded_at_ms = batch_window["start_epoch_ms"] + 4999.934
        legacy = {
            "event_type": "provider", "schema_version": 1, "run_id": "run-g5",
            "site": "combat_compression", "mode": "mp", "combat_round": 1,
            "phase": "PC_PHASE", "action_id": "pc:r1:vitreol",
            "elapsed_ms": 4994.07, "prompt_tokens": 2680,
            "completion_tokens": 473, "total_tokens": 3153,
            "recorded_at_ms": recorded_at_ms,
        }
        router_receipt = {
            "event_type": "provider", "schema_version": 1, "run_id": "run-g5",
            "site": "combat_compression", "mode": "mp", "combat_round": 1,
            "phase": "PC_PHASE", "action_id": "pc:r1:vitreol",
            "call_id": "compression-call-1", "attempt_id": "compression-attempt-1",
            "attempt_number": 1, "task": "compression", "provider": "openai",
            "requested_model": "gpt-6-luna", "resolved_model": "gpt-6-luna",
            "retry": False, "fallback": False, "usage_available": True,
            "usage_complete": True, "outcome": "response", "error_type": None,
            "elapsed_ms": 4994.07, "prompt_tokens": 2680,
            "completion_tokens": 473, "recorded_at_ms": recorded_at_ms,
        }

        legacy_projection = capture_evidence.project_g5_trace(
            [legacy], "run-g5", trace_windows=windows
        )
        router_projection = capture_evidence.project_g5_trace(
            [router_receipt], "run-g5", trace_windows=windows
        )
        legacy_batch = next(row for row in legacy_projection["work_units"]
                            if row["type"] == "batch")
        router_batch = next(row for row in router_projection["work_units"]
                            if row["type"] == "batch")
        self.assertEqual(legacy_projection["status"], "PASS")
        self.assertEqual(router_projection["status"], "PASS")
        self.assertEqual(legacy_projection["counts"]["provider_calls"],
                         router_projection["counts"]["provider_calls"])
        self.assertEqual(legacy_batch["provider_calls"], router_batch["provider_calls"])
        self.assertEqual(router_batch["provider_calls"], 1)
        self.assertEqual(legacy_batch["legacy_provider_calls"], 1)
        self.assertEqual(router_batch["legacy_provider_calls"], 0)
        self.assertNotIn("classification", router_projection["provider_receipts"][0])
        self.assertEqual(router_projection["provider_receipts"][0]["site"],
                         "combat_compression")

    def test_only_unplaced_provider_or_write_inside_measured_span_blocks(self):
        windows = _driver_windows(1, action_ms=1000.0, batch_ms=1000.0)
        between = windows["steps"][0]["end_epoch_ms"] + 10
        external = [
            {"event_type": "provider", "run_id": "run-g5", "recorded_at_ms": 500.0},
            {"event_type": "provider", "run_id": "run-g5", "recorded_at_ms": between},
            {"event_type": "file_operation", "run_id": "run-g5", "recorded_at_ms": between,
             "category": "write"},
            {"event_type": "provider", "run_id": "run-g5",
             "recorded_at_ms": windows["teardown"]["end_epoch_ms"] + 100},
        ]
        projection = capture_evidence.project_g5_trace(external, "run-g5", trace_windows=windows)
        self.assertEqual(projection["status"], "BLOCKED")
        self.assertIn("provider_or_file_write_unattributed_inside_measured_span", projection["reason"])
        self.assertEqual(projection["counts"]["startup_provider_calls"], 1)
        self.assertEqual(projection["counts"]["between_step_provider_calls"], 1)
        self.assertEqual(projection["counts"]["teardown_provider_calls"], 1)

    def test_run_id_mismatch_is_retained_unattributed_and_only_measured_work_blocks(self):
        windows = _driver_windows(1)
        outside = capture_evidence.project_g5_trace(
            [{"event_type": "stage", "run_id": "other-run", "recorded_at_ms": 1000.0}],
            "run-g5", trace_windows=windows,
        )
        self.assertEqual(outside["status"], "PASS")
        self.assertEqual(outside["run_id_mismatches"], 1)
        self.assertEqual(outside["unattributed_record_count"], 1)
        self.assertEqual(outside["assignments"][0]["bucket"], "unattributed")

        projection = capture_evidence.project_g5_trace(
            [{"event_type": "provider", "run_id": "other-run",
              "recorded_at_ms": windows["steps"][0]["start_epoch_ms"] + 1}],
            "run-g5", trace_windows=windows,
        )
        self.assertEqual(projection["status"], "BLOCKED")
        self.assertIn("provider_or_file_write_unattributed_inside_measured_span", projection["reason"])
        self.assertEqual(projection["counts"]["provider_calls"], 1)

    def test_configured_identity_uses_sandbox_ast_literals_and_resolves_aliases(self):
        pathlib.Path("tmp/router-rollout/g5").mkdir(parents=True, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(dir="tmp/router-rollout/g5", prefix="identity-ast-")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        (root / "model_config.py").write_text(
            'LLM_PROVIDER = "openai"\nOPENAI_FALLBACK_MODEL = "gpt-6-luna"\n'
            'COMBAT_MAIN_MODEL = OPENAI_FALLBACK_MODEL\n',
            encoding="ascii",
        )
        identity = capture_evidence.read_sandbox_model_config_identity(root)
        self.assertEqual(identity["status"], "ok")
        self.assertEqual(identity["configured_provider"], "openai")
        self.assertEqual(identity["configured_model"], "gpt-6-luna")
        self.assertEqual(identity["provenance"], "sandbox model_config.py AST literals")
        self.assertRegex(identity["model_config_sha256"], r"^[0-9a-f]{64}$")

        (root / "model_config.py").write_text(
            'LLM_PROVIDER = "openai"\nCOMBAT_MAIN_MODEL = __import__("os").getcwd()\n',
            encoding="ascii",
        )
        rejected = capture_evidence.read_sandbox_model_config_identity(root)
        self.assertEqual(rejected["status"], "unknown")
        self.assertIsNone(rejected["configured_model"])

    def test_trace_projection_blocks_oversized_work_unit_identifiers(self):
        windows = _driver_windows(1)
        projection = capture_evidence.project_g5_trace(
            [{"event_type": "provider", "run_id": "run-g5",
              "recorded_at_ms": windows["steps"][0]["start_epoch_ms"] + 1,
              "action_id": "pc:r" + ("1" * 74) + ":acheron"}],
            "run-g5",
            trace_windows=windows,
        )
        self.assertEqual(projection["status"], "PASS")
        self.assertEqual(projection["work_units"][0]["id"], "action-step-001")
        self.assertNotIn("runtime_action_id", projection["provider_receipts"][0])

    def test_receipts_keep_work_and_quiet_times_distinct_and_unavailable_is_null(self):
        measured = capture_drive._g5_timing_values(
            10.0,
            [{"ts": 10.5, "monotonic_ts": 25.5}],
            [{"ts": 10.1, "is_processing": True}, {"ts": 10.5, "is_processing": False}],
            True,
            12.0,
        )
        self.assertEqual(measured["work_only_ms"], 500.0)
        self.assertEqual(measured["quiet_window_elapsed_ms"], 2000.0)
        self.assertNotEqual(measured["work_only_ms"], measured["quiet_window_elapsed_ms"])

        unavailable = capture_drive._g5_timing_values(10.0, [], [], False, None)
        self.assertIsNone(unavailable["work_only_ms"])
        self.assertEqual(unavailable["work_only_reason"], "backend_output_or_processing_idle_not_observed")
        self.assertIsNone(unavailable["quiet_window_elapsed_ms"])
        self.assertEqual(unavailable["quiet_window_reason"], "quiet_window_not_observed")

    def test_capture_metadata_records_source_provider_model_seed_and_method_slots(self):
        profile = fixtures.build_gate_profile("g5", "combat-smoke", 1)
        metadata = capture_evidence.build_g5_capture_metadata(
            profile, "run-g5-p1", {"head": "abc123", "relevant_source_sha256": {"core/combat/turn.py": "deadbeef"}},
            "seed-identity",
        )
        identity = metadata["identity"]
        self.assertEqual(identity["run_id"], "run-g5-p1")
        self.assertEqual(identity["source_head"], "abc123")
        self.assertRegex(identity["source_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(identity["seed_id"], "seed-identity")
        self.assertEqual(identity["provider"], "unknown")
        self.assertEqual(identity["model"], "unknown")
        self.assertIsNone(identity["configured_provider"])
        self.assertIsNone(identity["configured_model"])
        self.assertEqual(identity["measurement_method"]["id"], "g5-driver-window-work-quiet-v2")


if __name__ == "__main__":
    unittest.main()
