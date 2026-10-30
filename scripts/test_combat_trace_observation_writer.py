# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Real-writer regression tests for combat observation output routing."""

import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import model_config
from core.combat.persistence import (
    CharacterUpdateDependencies,
    apply_final_character_updates,
    process_combat_action_batch,
    queue_final_character_update,
    sync_multi_pc_character_state,
)
from core.combat.enemy_batch_apply import apply_enemy_batch
from core.combat.enemy_narration import NarrationResult
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyAttackLedgerEntry,
    EnemyResolutionLedger,
)
from scripts import capture_evidence
from scripts.combat_latency_fixtures import build_capture_character_payload
from utils import combat_latency_trace
from utils.llm_runtime import make_legacy_receipt_observer


def _enemy_batch_apply_fixture(root):
    actor = CombatantIdentity(name="Goblin", kind="enemy")
    target = CombatantIdentity(name="Acheron", kind="player")
    ledger = EnemyResolutionLedger(
        encounter_id="fixture",
        round_number=1,
        batch_id="batch-fixture-r1-enemy_phase",
        batch_kind="enemy_phase",
        seed=7,
        entries=(EnemyAttackLedgerEntry(
            actor=actor,
            action_name="Scimitar",
            target=target,
            d20=12,
            attack_total=18,
            armor_class=15,
            hit=True,
            critical=False,
            damage_dice_rolls=(5,),
            damage_total=5,
            damage_type="slashing",
            target_hp_before=20,
            target_hp_after=15,
            target_status_after="alive",
        ),),
        bloodied=(),
    )
    narration = NarrationResult("Goblin cuts Acheron.", "template")
    history = [{"role": "system", "content": "seed"}]
    encounter = {
        "encounterId": "fixture",
        "combat_round": 1,
        "combat_phase": "PC_PHASE",
        "creatures": [
            {"name": "Acheron", "type": "player", "currentHitPoints": 20, "status": "alive"},
            {"name": "Goblin", "type": "enemy", "currentHitPoints": 9, "status": "alive"},
        ],
    }

    class PathManager:
        def get_character_path(self, name):
            return str(root / "characters" / (name.lower() + ".json"))

        def get_encounter_path_from_id(self, encounter_id):
            return str(root / "encounters" / (encounter_id + ".json"))

    writes = []

    def read_json(path):
        if str(path).endswith("encounters/fixture.json"):
            return copy.deepcopy(encounter)
        return {"name": "Acheron", "hitPoints": 20, "status": "alive"}

    def write_json(path, payload):
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="ascii")
        writes.append(str(target_path))
        return True

    arguments = {
        "ledger": ledger,
        "narration": narration,
        "user_input_text": "Enemies turn.",
        "turn_id": "00000000-0000-4000-8000-000000000021",
        "conversation_history": history,
        "conversation_history_file": str(root / "history.json"),
        "encounter_projection": encounter,
        "path_manager": PathManager(),
        "read_json": read_json,
        "write_json": write_json,
        "validate_character": lambda _name, _payload: True,
    }
    return arguments, writes


class CombatObservationWriterTests(unittest.TestCase):
    def test_encounter_hp_projection_uses_real_batch_writer_and_checker(self):
        with tempfile.TemporaryDirectory(prefix="combat-hp-ledger-", dir="tmp") as directory:
            root = Path(directory)
            before_encounter = {"encounterId": "fixture", "creatures": [
                {"name": "Acheron", "type": "player", "currentHitPoints": 20},
                {"name": "Goblin", "type": "enemy", "currentHitPoints": 20},
                {"name": "Blairen", "type": "npc", "currentHitPoints": 12},
            ]}
            callback_order = []

            def updater(_encounter_id, _changes, ops=None):
                callback_order.append("updater")
                before_encounter["creatures"][1]["currentHitPoints"] = 18
                before_encounter["encounterSummary"] = "metadata changed"
                return {"encounterId": "fixture", "creatures": [
                    {"name": "Acheron", "type": "player", "currentHitPoints": 20},
                    {"name": "Goblin", "type": "enemy", "currentHitPoints": 20},
                    {"name": "Blairen", "type": "npc", "currentHitPoints": 12},
                ], "encounterSummary": "metadata changed"}

            deps = SimpleNamespace(
                update_encounter=updater,
                log_info=lambda *_args, **_kwargs: callback_order.append("log"),
                normalize_encounter_status=lambda value: value,
                sync_non_pc_queue_state=lambda *_args: False,
                check_all_monsters_defeated=lambda _value: False,
                queue_character_update=queue_final_character_update,
                log_debug=lambda *_args, **_kwargs: None,
                log_error=lambda *_args, **_kwargs: None,
                log_warning=lambda *_args, **_kwargs: None,
                calculate_xp=lambda: ("", 0), save_json=lambda *_args: None,
                active_character_update_available=False, emit_combat_event=lambda *_args: None,
                get_current_actor=lambda *_args: None, advance_turn=lambda *_args: None,
                get_pc_state=lambda *_args: None, pc_acted_status="acted",
                npc_combatant_type="npc", pc_combatant_type="pc",
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                    updates = {}
                    process_combat_action_batch(
                        [
                            {"action": "updateEncounter", "parameters": {"changes": "metadata"}},
                            {"action": "updateCharacterInfo", "parameters": {
                                "characterName": "Acheron", "ops": [{"op": "hp_delta", "delta": -7}]}},
                            {"action": "updateNpcInfo", "parameters": {
                                "npcName": "Blairen", "ops": [{"op": "hp_delta", "delta": -3}]}},
                        ],
                        before_encounter, updates, encounter_id="fixture", conversation_history=[],
                        conversation_history_file="history.json", multi_pc_manager=None,
                        party_tracker_data={}, is_combat_ending=False, dependencies=deps,
                    )
                    apply_final_character_updates(
                        updates, None, CharacterUpdateDependencies(
                            update_character_info=lambda *_args, **_kwargs: True,
                            normalize_character_name=lambda name: name.lower(),
                            safe_json_load=lambda _path: None, sync_character_state=lambda *_args: None,
                            log_info=lambda *_args, **_kwargs: None,
                            log_debug=lambda *_args, **_kwargs: None,
                            log_error=lambda *_args, **_kwargs: None,
                        ),
                    )
                    trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                    apply_span_end = trace_path.stat().st_size
                    combat_latency_trace.emit_trace_event(
                        "decision", decision_point="combat_command_fast_path",
                        decision_source="deterministic", provider_call_avoided=True,
                    )
                trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                records, errors = capture_evidence.parse_trace_positions(trace_path)
                self.assertEqual(errors, [])
                event = next(row for row in records if row.get("observation") == "combat_apply_result")
                self.assertEqual(event["hp_before_source"], "preloaded_context")
                self.assertEqual(event["hp_after_source"], "returned_persisted_state")
                self.assertEqual(event["hp_before"], '[["Acheron",20],["Goblin",20],["Blairen",12]]')
                self.assertEqual(event["hp_after"], event["hp_before"])
                self.assertEqual(callback_order.count("updater"), 1)
                self.assertTrue(callback_order.index("log") < callback_order.index("updater"))

                def snapshot(label, goblin_hp):
                    return {"label": label, "records": {
                        "party_tracker.json": {"status": "ok", "partyMembers": ["Acheron"],
                                                "active_character": "Acheron"},
                        "selected_encounter": {"status": "ok", "encounterId": "fixture", "creatures": [
                            {"name": "Acheron", "type": "player", "status": "alive", "currentHitPoints": 20},
                            {"name": "Goblin", "type": "enemy", "status": "alive", "currentHitPoints": goblin_hp},
                            {"name": "Blairen", "type": "npc", "status": "alive", "currentHitPoints": 12},
                        ]},
                        "characters/acheron.json": {"read_status": "ok", "name": "Acheron", "hitPoints": 20},
                        "characters/blairen.json": {"read_status": "ok", "name": "Blairen", "hitPoints": 12},
                    }, "observation": {}}

                before, after_apply = snapshot("before", 20), snapshot("after-apply", 20)
                for creature in after_apply["records"]["selected_encounter"]["creatures"]:
                    if creature["name"] == "Acheron":
                        creature["currentHitPoints"] = 13
                    elif creature["name"] == "Blairen":
                        creature["currentHitPoints"] = 9
                after_apply["records"]["characters/acheron.json"]["hitPoints"] = 13
                after_apply["records"]["characters/blairen.json"]["hitPoints"] = 9
                after = snapshot("after", 18)
                after["records"]["selected_encounter"]["creatures"][0]["currentHitPoints"] = 13
                after["records"]["selected_encounter"]["creatures"][2]["currentHitPoints"] = 9
                after["records"]["characters/acheron.json"]["hitPoints"] = 13
                after["records"]["characters/blairen.json"]["hitPoints"] = 9
                size = trace_path.stat().st_size
                steps = [
                    {"before": {**before, "observation": {
                         "runtimeTrace": {"status": "captured", "offset_bytes": 0}}},
                     "after": {**after_apply, "observation": {
                         "runtimeTrace": {"status": "captured", "offset_bytes": apply_span_end}}}},
                    {"before": {**after_apply, "observation": {
                         "runtimeTrace": {"status": "captured", "offset_bytes": apply_span_end},
                         "input": "/dmg 2", "character": "Acheron"}},
                     "after": {**after, "observation": {
                         "runtimeTrace": {"status": "captured", "offset_bytes": size}}}},
                ]
                checks = capture_evidence.observed_checks(
                    {"scenario_id": "combat-smoke", "party_size": 1}, before, after, {}, steps, records
                )
                ledger = next(row for row in checks if row["id"] == "hp_delta_snapshot_reconciliation")
                self.assertEqual(ledger["status"], "PASS", ledger)
                invalid_events = [
                    dict(event, hp_after='[["Acheron",20],["Goblin",19]]'),
                    dict(event, hp_before=None),
                    dict(event, hp_before_status="invalid"),
                    dict(event, hp_before='[["Goblin",20],["Goblin",20]]', hp_before_count=2),
                    dict(event, hp_after_source="preloaded_context"),
                    dict(event, hp_before_truncated=True),
                    dict(event, target="other-encounter"),
                ]
                for invalid_event in invalid_events:
                    with self.subTest(invalid_event=invalid_event):
                        candidate_events = [invalid_event if row is event else row for row in records]
                        blocked = capture_evidence.observed_checks(
                            {"scenario_id": "combat-smoke", "party_size": 1},
                            before, after, {}, steps, candidate_events,
                        )
                        self.assertEqual(next(row for row in blocked if row["id"] ==
                                              "hp_delta_snapshot_reconciliation")["status"], "BLOCKED")
                failed = capture_evidence.observed_checks(
                    {"scenario_id": "combat-smoke", "party_size": 1}, before, after, {},
                    steps, [dict(row, applied=False, failure="false_return") if row is event else row
                            for row in records],
                )
                self.assertEqual(next(row for row in failed if row["id"] ==
                                      "mechanical_apply_outcomes")["status"], "FAIL")
            finally:
                os.chdir(previous_cwd)

    def test_observation_path_metadata_cannot_redirect_real_writer(self):
        with tempfile.TemporaryDirectory(prefix="combat-trace-routing-", dir="tmp") as directory:
            root = Path(directory)
            (root / "characters").mkdir()
            character_path = root / "characters" / "acheron.json"
            character_bytes = (
                json.dumps(build_capture_character_payload("Acheron", 18), ensure_ascii=True)
                + "\n"
            ).encode("ascii")
            character_path.write_bytes(character_bytes)
            metadata_targets = (
                "StateFile.json",
                "stdout",
                "data/memory.db",
                "redirect.jsonl",
            )

            class Manager:
                def __init__(self):
                    self.synced = None

                def sync_pc_persistent_state(self, name, state):
                    self.synced = (name, state)

            manager = Manager()
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                    sync_multi_pc_character_state(
                        manager,
                        "Acheron",
                        CharacterUpdateDependencies(
                            update_character_info=lambda *_args, **_kwargs: True,
                            normalize_character_name=lambda name: name.lower(),
                            safe_json_load=lambda path: json.loads(Path(path).read_text(encoding="ascii")),
                            sync_character_state=lambda *_args: None,
                            log_info=lambda *_args, **_kwargs: None,
                            log_debug=lambda *_args, **_kwargs: None,
                            log_error=lambda *_args, **_kwargs: None,
                        ),
                    )
                    # Exercise legacy ``path`` metadata against file, stdout, and
                    # database-shaped targets through the real writer.
                    for index, target in enumerate(metadata_targets):
                        metadata_fields = {
                            "state_path": "characters/acheron.json",
                            "path": target,
                        }
                        if index == 0:
                            metadata_fields["legacy_path_metadata"] = "existing provenance"
                        self.assertTrue(
                            combat_latency_trace.trace_combat_observation(
                                "path_metadata_regression",
                                **metadata_fields,
                            )
                        )

                trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                records = [
                    json.loads(line)
                    for line in trace_path.read_text(encoding="ascii").splitlines()
                ]
                persisted = records[0]
                self.assertEqual(persisted["state_path"], "characters/acheron.json")
                self.assertEqual(persisted["persisted_state"]["name"], "Acheron")
                metadata = records[1:]
                self.assertEqual(len(metadata), len(metadata_targets))
                self.assertEqual(metadata[0]["legacy_path_metadata"], "existing provenance")
                self.assertEqual(metadata[0]["legacy_path_metadata_2"], metadata_targets[0])
                self.assertEqual(
                    [record["legacy_path_metadata"] for record in metadata[1:]],
                    list(metadata_targets[1:]),
                )
                self.assertTrue(
                    all(record["state_path"] == "characters/acheron.json" for record in metadata)
                )
                self.assertEqual(character_path.read_bytes(), character_bytes)
                self.assertEqual(manager.synced[0], "Acheron")
                self.assertTrue(all(not (root / target).exists() for target in metadata_targets))
                self.assertEqual(
                    {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
                     and "pycache" not in path.parts},
                    {"characters/acheron.json", "debug/combat_turn_trace.jsonl"},
                )
            finally:
                os.chdir(previous_cwd)

    def test_actual_validation_rejection_writes_flat_operation_evidence_with_real_writer(self):
        from dataclasses import replace
        from scripts.test_combat_validation_stage import _dependencies
        from core.combat.validation import validate_combat_response

        with tempfile.TemporaryDirectory(prefix="combat-validation-writer-", dir="tmp") as directory:
            root = Path(directory)
            character_path = root / "acheron.json"
            character_bytes = b'{"name":"Acheron","hitPoints":20}\n'
            character_path.write_bytes(character_bytes)
            candidate = {"actions": []}
            for index in range(4):
                operation = (
                    {"op": "hp_delta", "creature": "Goblin", "target": "Goblin", "delta": -7}
                    if index == 0 else
                    {"op": "\u00e9" * 100, "creature": "\u00e9" * 100,
                     "target": "\u00e9" * 100, "delta": "\u00e9" * 100}
                )
                candidate["actions"].append({"action": "updateEncounter", "parameters": {
                    "changes": "\u00e9" * 600, "ops": [operation],
                }})
            dependencies, calls = _dependencies()
            dependencies = replace(
                dependencies,
                enemy_boundary_precheck=lambda *_args: (False, "\u00e9" * 600),
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                    result = validate_combat_response(
                        json.dumps(candidate, ensure_ascii=True),
                        {"encounterId": "fixture", "creatures": []},
                        "continue", dependencies=dependencies,
                    )
                self.assertIn("VALIDATION FAILURE:", result)
                trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                lines = trace_path.read_bytes().splitlines()
                records = [json.loads(line.decode("ascii")) for line in lines]
                operation_records = [
                    record for record in records
                    if "operation_0_action_index" in record
                ]
                self.assertEqual(len(operation_records), 1)
                self.assertTrue(all(
                    len(line) <= combat_latency_trace.MAX_RECORD_BYTES
                    for line in lines
                ))
                record = operation_records[0]
                self.assertEqual(record["operation_0_action_index"], 0)
                self.assertEqual(record["operation_0_index"], 0)
                self.assertEqual(record["operation_0_operation"], "hp_delta")
                self.assertEqual(record["operation_0_creature"], "Goblin")
                self.assertEqual(record["operation_0_target"], "Goblin")
                self.assertEqual(record["operation_0_delta"], -7)
                self.assertEqual(record["changes"][0]["changes"], "\u00e9" * 96)
                self.assertEqual(record["changes"][0]["changes_truncated"], 504)
                self.assertEqual(record["changes"][3]["changes"], "\u00e9" * 96)
                self.assertEqual(record["changes"][3]["action_index"], 3)
                self.assertEqual(record["reason"], "\u00e9" * 128)
                self.assertEqual(record["reason_chars"], 600)
                self.assertEqual(record["reason_truncated"], 472)
                self.assertEqual(record["operations_truncated"], 0)
                self.assertEqual(record["operation_1_operation"], "\u00e9" * 16)
                self.assertEqual(record["operation_3_action_index"], 3)
                self.assertEqual(character_path.read_bytes(), character_bytes)
                self.assertEqual(calls["provider"], [])
                self.assertEqual({path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
                                  and "pycache" not in path.parts},
                                 {"acheron.json", "debug/combat_turn_trace.jsonl"})
            finally:
                os.chdir(previous_cwd)

    def test_enemy_batch_physical_writes_have_opaque_real_writer_events(self):
        with tempfile.TemporaryDirectory(prefix="combat-batch-writer-", dir="tmp") as directory:
            root = Path(directory)
            arguments, writes = _enemy_batch_apply_fixture(root)
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                    result = apply_enemy_batch(**arguments)
                trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                records = [json.loads(line) for line in trace_path.read_text(
                    encoding="ascii"
                ).splitlines()]
                write_events = [row for row in records if row.get("event_type") == "file_operation"]

                self.assertEqual(result.write_count, 3)
                self.assertEqual(len(writes), 3)
                self.assertEqual(len(write_events), 3)
                self.assertEqual({row["target_kind"] for row in write_events},
                                 {"history", "character", "encounter"})
                self.assertTrue(all(row["category"] == "write" for row in write_events))
                self.assertTrue(all(row["site"] == "enemy_batch_write" for row in write_events))
                self.assertTrue(all(row["batch_id"] == "enemy:r1" for row in write_events))
                self.assertTrue(all(len(row["target_id"]) == 12 for row in write_events))
                self.assertTrue(all(all(char in "0123456789abcdef" for char in row["target_id"])
                                    for row in write_events))
                self.assertNotIn(str(root), json.dumps(write_events, ensure_ascii=True))
                self.assertEqual(set(writes), {
                    str(root / "history.json"),
                    str(root / "characters" / "acheron.json"),
                    str(root / "encounters" / "fixture.json"),
                })
            finally:
                os.chdir(previous_cwd)

    def test_enemy_batch_trace_writer_exception_does_not_fail_apply(self):
        with tempfile.TemporaryDirectory(prefix="combat-batch-failopen-", dir="tmp") as directory:
            arguments, writes = _enemy_batch_apply_fixture(Path(directory))
            with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                    patch.object(combat_latency_trace, "emit_trace_event",
                                 side_effect=OSError("trace unavailable")):
                result = apply_enemy_batch(**arguments)
            self.assertEqual(result.changed_pc_names, ("Acheron",))
            self.assertEqual(result.write_count, 3)
            self.assertEqual(len(writes), 3)

    def test_enemy_narration_provider_receipt_remains_visible(self):
        with tempfile.TemporaryDirectory(prefix="combat-narration-provider-", dir="tmp") as directory:
            root = Path(directory)
            previous_cwd = Path.cwd()
            receipt = SimpleNamespace(
                kind="response", call_id="narration-call", attempt_id="narration-attempt",
                attempt_number=1, task="combat_main", transport_provider="openai",
                observed_upstream_provider="openai", requested_model="fixture-model",
                resolved_model="fixture-model", transport_retry=0, retry_tier=None,
                fallback=False, cost_usd=None, provider_reported_cost_usd=None,
                cost_provenance="unpriced", cost_complete=False, usage_complete=False,
                error_type=None, elapsed_ms=12.5,
            )
            try:
                os.chdir(root)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                    observer = make_legacy_receipt_observer(
                        trace_site="combat_main",
                        track_usage=False,
                        legacy_context={
                            "purpose": "combat_enemy_batch_narration",
                            "legacy_context_model": "fixture-model",
                        },
                    )
                    observer(receipt, SimpleNamespace(usage=None))
                trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                records = [json.loads(line) for line in trace_path.read_text(
                    encoding="ascii"
                ).splitlines()]
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["event_type"], "provider")
                self.assertEqual(records[0]["site"], "combat_main")
                self.assertEqual(records[0]["purpose"], "combat_enemy_batch_narration")
                self.assertEqual(records[0]["task"], "combat_main")
            finally:
                os.chdir(previous_cwd)

    def test_legacy_retry_cause_is_forwarded_to_provider_trace(self):
        with tempfile.TemporaryDirectory(prefix="combat-retry-cause-", dir="tmp") as directory:
            root = Path(directory)
            previous_cwd = Path.cwd()
            receipt = SimpleNamespace(
                kind="response", call_id="retry-call", attempt_id="retry-attempt",
                attempt_number=2, task="combat_main", transport_provider="openai",
                observed_upstream_provider="openai", requested_model="fixture-model",
                resolved_model="fixture-model", transport_retry=0, retry_tier=None,
                fallback=False, cost_usd=None, provider_reported_cost_usd=None,
                cost_provenance="unpriced", cost_complete=False, usage_complete=False,
                error_type=None, elapsed_ms=12.5,
            )
            try:
                os.chdir(root)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                    observer = make_legacy_receipt_observer(
                        trace_site="combat_main",
                        track_usage=False,
                        legacy_context={
                            "purpose": "combat_provider_retry",
                            "legacy_context_model": "fixture-model",
                            "retry_cause": "validator_rejection",
                        },
                    )
                    observer(receipt, SimpleNamespace(usage=None))
                trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                record = json.loads(trace_path.read_text(encoding="ascii").strip())
                self.assertEqual(record["event_type"], "provider")
                self.assertEqual(record["retry_cause"], "validator_rejection")
            finally:
                os.chdir(previous_cwd)

    def test_combat_exit_completion_marker_is_a_bounded_stage_event(self):
        with tempfile.TemporaryDirectory(prefix="combat-exit-marker-", dir="tmp") as directory:
            root = Path(directory)
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                        patch.object(combat_latency_trace, "_TRACE_CONTEXT", {
                            "batch_id": "enemy:r4",
                            "encounter_id": "g5t-commander-p1",
                        }):
                    self.assertTrue(combat_latency_trace.trace_combat_exit_complete(
                        encounter_id="g5t-commander-p1", batch_id="unsafe/batch"))
                trace_path = root / combat_latency_trace.DEFAULT_TRACE_PATH
                record = json.loads(trace_path.read_text(encoding="ascii").strip())
                self.assertEqual(record["event_type"], "stage")
                self.assertEqual(record["stage"], "combat_exit_complete")
                self.assertEqual(record["elapsed_ms"], 0)
                self.assertEqual(record["batch_id"], "enemy:r4")
                self.assertEqual(record["encounter_id"], "g5t-commander-p1")
                self.assertLessEqual(trace_path.stat().st_size, combat_latency_trace.MAX_RECORD_BYTES)
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
