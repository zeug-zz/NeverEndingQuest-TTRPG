# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free G5A fixture, evidence, and offline report contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import model_config

from core.combat.ally_controller import (
    AllyActorMenu,
    AllyMenus,
    AllyOption,
    ValidatedAllyChoice,
    ValidatedAllyPlan,
    build_ally_directive_history_record,
)
from core.combat.commands import FastCommandIO, FastCommandResult, _run_ally_directive_command
from core.combat.ally_resolution import resolve_ally_batch
from core.combat.enemy_batch_apply import apply_enemy_batch, project_combat_resolution_ledger
from core.combat.enemy_resolution import CombatantIdentity
from core.combat.enemy_batch_orchestrator import (
    NarrationResult,
    _trace_ally_choice_commit_results,
    _trace_ally_cover_selections,
)
from scripts import capture_evidence, combat_latency_fixtures as fixtures
from scripts import seed_combat_capture
from scripts.combat_tactical_test_support import ProviderFreeTestCase
from utils import combat_latency_trace, file_operations


class CombatAllyG5ATest(ProviderFreeTestCase):
    def test_g5a_hostile_hp_preserves_margin_and_legacy_profiles(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                profile = fixtures.build_gate_profile(
                    "g5a", "g5a-ally-p%d" % party_size, party_size
                )
                encounter = {
                    "creatures": [
                        {"name": name, "type": "enemy", "currentHitPoints": 20,
                         "maxHitPoints": 20}
                        for name in ([fixtures.ONE_PC_ENEMY_NAME] if party_size == 1
                                     else fixtures.ENEMY_NAMES)
                    ]
                }
                fixtures.apply_capture_profile(encounter, {}, profile)
                hostiles = [row for row in encounter["creatures"]
                            if row.get("type") == "enemy"]
                self.assertTrue(hostiles)
                self.assertTrue(all(row["currentHitPoints"] == 40 and
                                    row["maxHitPoints"] == 40 for row in hostiles))
                ally_critical = 17
                scripted_pc_damage = 12 if party_size == 4 else 3
                remaining = 40 - scripted_pc_damage - ally_critical
                self.assertEqual(remaining, 11 if party_size == 4 else 20)
                self.assertGreater(remaining, 40 * 0.25)

        legacy_profile = fixtures.build_gate_profile("g5", "combat-smoke", 4)
        legacy_encounter = {"creatures": [
            {"name": name, "type": "enemy", "currentHitPoints": 20,
             "maxHitPoints": 20}
            for name in fixtures.ENEMY_NAMES
        ]}
        fixtures.apply_capture_profile(legacy_encounter, {}, legacy_profile)
        self.assertEqual(
            [(row["currentHitPoints"], row["maxHitPoints"])
             for row in legacy_encounter["creatures"]],
            [(20, 20), (20, 20)],
        )

    def test_g5a_scenarios_register_their_gate_and_cli_prepares_the_seed_provider_free(self):
        reference = {
            "module": "Capture_Arena", "area_id": "CTR001",
            "area_name": "Capture Arena", "start_location_id": "CA01",
            "start_location_name": "Waystone Gate",
        }
        capture_evidence.G5A_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        original_seed_party = seed_combat_capture._seed_party
        for party_size in (1, 4):
            scenario = "g5a-ally-p%d" % party_size
            with self.subTest(party_size=party_size):
                self.assertEqual(fixtures.infer_capture_gate(scenario), "g5a")
                self.assertIn(scenario, fixtures.CAPTURE_SCENARIO_CHOICES)
                with tempfile.TemporaryDirectory(
                    prefix="seed-prepare-", dir=str(capture_evidence.G5A_RUN_ROOT)
                ) as scratch:
                    sandbox = Path(scratch) / "combat_capture"
                    with patch.object(seed_combat_capture, "SANDBOX_ROOT", sandbox), \
                            patch.object(seed_combat_capture, "_assert_sandbox_root",
                                         return_value=sandbox), \
                            patch.object(seed_combat_capture, "_hash_installed_sentinels",
                                         return_value={}), \
                            patch.object(seed_combat_capture, "_copy_runtime", return_value=0), \
                            patch.object(seed_combat_capture, "_patch_sandbox_config") as config_patch, \
                            patch.object(seed_combat_capture, "_patch_sandbox_model_config") as model_patch, \
                            patch.object(seed_combat_capture, "transform_g5a_ally_fixtures") as transform, \
                            patch.object(seed_combat_capture, "_read_capture_arena_reference",
                                         return_value=reference), \
                            patch.object(seed_combat_capture, "_seed_party",
                                         wraps=original_seed_party) as seed_party, \
                            redirect_stdout(StringIO()):
                        result = seed_combat_capture.main([
                            "--prepare", "--party", str(party_size), "--scenario", scenario,
                        ])

                    self.assertEqual(result, 0)
                    config_patch.assert_called_once_with()
                    model_patch.assert_called_once_with("g5a", scenario)
                    transform.assert_called_once_with(sandbox / "modules" / "Capture_Arena")
                    seed_party.assert_called_once()
                    seeded_profile = seed_party.call_args.args[3]
                    self.assertEqual(seeded_profile["gate"], "g5a")
                    self.assertEqual(seeded_profile["scenario_id"], scenario)

                    tracker = json.loads(
                        (sandbox / "party_tracker.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(
                        tracker["worldConditions"]["activeCombatEncounter"], scenario
                    )
                    self.assertEqual(tracker["partyNPCs"][0]["name"], fixtures.G5A_ALLY_NAME)
                    encounter = json.loads(
                        (sandbox / "modules" / "encounters" /
                         ("encounter_%s.json" % scenario)).read_text(encoding="utf-8")
                    )
                    self.assertEqual(encounter["encounterId"], scenario)
                    self.assertIn(
                        fixtures.G5A_ALLY_NAME,
                        [row["name"] for row in encounter["creatures"]],
                    )

    def test_explicit_gate_overrides_inference_and_rejects_mismatch_before_prepare(self):
        with patch.object(seed_combat_capture, "prepare") as prepare_mock, \
                redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as raised:
                seed_combat_capture.main([
                    "--prepare", "--party", "1", "--scenario", "g5a-ally-p1",
                    "--gate", "g3",
                ])
        self.assertEqual(raised.exception.code, 2)
        prepare_mock.assert_not_called()

    def _case(self, party_size: int = 1, run_id: str = "g5a-p1-test"):
        profile = fixtures.build_gate_profile(
            "g5a", "g5a-ally-p%d" % party_size, party_size
        )
        script = fixtures.build_g5a_script_steps(party_size)
        directive_step = next(row for row in script if row["input"].startswith("/cmd "))
        batch_step = next(row for row in script if row["unit_type"] == "batch")
        party = [fixtures.ONE_PC_NAME] if party_size == 1 else list(fixtures.PC_NAMES)
        creatures = [
            {"name": name, "type": "player", "currentHitPoints": 20,
             "maxHitPoints": 20, "status": "alive"}
            for name in party
        ]
        if party_size == 1:
            creatures.append({"name": fixtures.ONE_PC_ENEMY_NAME, "type": "enemy",
                              "currentHitPoints": 20, "maxHitPoints": 20,
                              "status": "alive"})
        else:
            creatures.extend({"name": name, "type": "enemy", "currentHitPoints": 20,
                              "maxHitPoints": 20, "status": "alive"}
                             for name in fixtures.ENEMY_NAMES)
        creatures.append({"name": fixtures.G5A_ALLY_NAME, "type": "npc",
                          "currentHitPoints": 12, "maxHitPoints": 12,
                          "status": "alive"})
        before = {"records": {
            "party_tracker.json": {"status": "ok", "partyMembers": party},
            "selected_encounter": {"status": "ok", "encounterId": profile["scenario_id"],
                                   "creatures": copy.deepcopy(creatures)},
        }}
        after = copy.deepcopy(before)
        after_ally = next(
            row for row in after["records"]["selected_encounter"]["creatures"]
            if row.get("name") == fixtures.G5A_ALLY_NAME
        )
        after_ally["coverFeatureId"] = fixtures.G5A_COVER_FEATURE_ID
        after_ally["coverType"] = "half"
        actor_ids = combat_latency_trace.build_run_local_actor_ids(creatures)
        ally_actor_id = actor_ids[("npc", fixtures.G5A_ALLY_NAME.casefold())]
        directive_sha256 = fixtures.build_g5a_fixture_metadata(party_size)["directive_sha256"]
        expected_fixture = fixtures.build_g5a_fixture_metadata(party_size)
        step_windows = [
            {"step": directive_step["step"], "unit_type": "action",
             "unit_id": "action-step-%03d" % directive_step["step"],
             "round": directive_step["round"],
             "start_epoch_ms": 100, "end_epoch_ms": 110},
            {"step": batch_step["step"], "unit_type": "batch",
             "unit_id": "batch-step-%03d" % batch_step["step"],
             "round": batch_step["round"],
             "start_epoch_ms": 120, "end_epoch_ms": 130},
        ]
        metadata = {
            "fixture": expected_fixture,
            "identity": {"run_id": run_id},
            "receipts": [
                {"step": directive_step["step"], "script_step": directive_step["step"],
                 "label": directive_step["label"], "status": "sent",
                 "work_unit": {"type": directive_step["unit_type"],
                               "id": directive_step["unit_id"],
                               "round": directive_step["round"]}},
                {"step": batch_step["step"], "script_step": batch_step["step"],
                 "label": batch_step["label"], "status": "sent",
                 "work_unit": {"type": batch_step["unit_type"],
                               "id": batch_step["unit_id"],
                               "round": batch_step["round"]}},
            ],
            "trace_windows": {"status": "captured", "steps": step_windows},
            "trace_attribution": {"status": "PASS"},
        }
        events = [
            {"event_type": "combat_observation", "observation": "ally_prefetch_submission",
             "batch_id": "enemy:r1", "request_id": "prefetch-initial-1",
             "request_kind": "initial", "run_id": run_id, "recorded_at_ms": 90},
            {"event_type": "combat_observation", "observation": "ally_directive_accepted",
             "batch_id": "enemy:r1", "actor_id": ally_actor_id,
             "directive_sha256": directive_sha256, "run_id": run_id,
             "recorded_at_ms": 105},
            {"event_type": "combat_observation", "observation": "ally_prefetch_submission",
             "batch_id": "enemy:r1", "request_id": "prefetch-replan-1",
             "request_kind": "replan", "run_id": run_id, "recorded_at_ms": 106},
            {"event_type": "combat_observation", "observation": "ally_choice_commit_result",
             "batch_id": "enemy:r1", "actor_id": ally_actor_id,
             "choice_kind": "take_cover", "choice_legal": True,
             "choice_defaulted": False, "choice_applied": True,
             "cover_feature_id": fixtures.G5A_COVER_FEATURE_ID,
              "directive_sha256": directive_sha256,
              "directive_request_kind": "replan", "run_id": run_id,
              "recorded_at_ms": 125},
            {"event_type": "combat_observation", "observation": "combat_cover_outcome",
             "batch_id": "enemy:r1", "actor_id": ally_actor_id,
             "cover_state": "selected", "feature_id": fixtures.G5A_COVER_FEATURE_ID,
             "cover_type": "half", "run_id": run_id, "recorded_at_ms": 124},
            {"event_type": "combat_observation", "observation": "combat_cover_outcome",
             "batch_id": "enemy:r1", "actor_id": ally_actor_id,
             "cover_state": "applied", "feature_id": fixtures.G5A_COVER_FEATURE_ID,
             "cover_type": "half", "run_id": run_id, "recorded_at_ms": 126},
        ]
        provider_events = [
            {"event_type": "provider", "call_id": "background-initial",
             "purpose": "combat_ally_standing_orders",
             "request_site": "combat_tactical_prefetch", "request_kind": "initial"},
            {"event_type": "provider", "call_id": "background-replan",
             "purpose": "combat_ally_standing_orders",
             "request_site": "combat_tactical_prefetch", "request_kind": "replan"},
            {"event_type": "provider", "call_id": "ally-narration-1",
             "purpose": "combat_ally_batch_narration", "batch_id": "enemy:r1",
             "run_id": run_id},
        ]
        artifacts = {"trace": "trace.jsonl", "required_evidence_status": "ok",
                     "trace_provider_events": provider_events}
        sandbox_identity = {
            "status": "ok", "flags": {
                "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED": True,
                "COMBAT_ALLY_CONTROLLER_ENABLED": True,
                "COMBAT_ALLY_PREFETCH_ENABLED": True,
            },
            "expected": {
                "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED": True,
                "COMBAT_ALLY_CONTROLLER_ENABLED": True,
                "COMBAT_ALLY_PREFETCH_ENABLED": True,
            },
        }
        return profile, before, after, artifacts, events, metadata, sandbox_identity

    def _pending_replan_attack_case(self, party_size: int):
        run_id = "g5a-p%d-initial-plan-attack" % party_size
        profile, before, after, artifacts, base_events, metadata, sandbox = self._case(
            party_size, run_id
        )
        script = metadata["fixture"]["steps"]
        damage_rows = [row for row in script if row["input"].startswith("/dmg ")]
        target = damage_rows[0]["target"]

        def set_target_hp(snapshot, value):
            creatures = snapshot["records"]["selected_encounter"]["creatures"]
            target_rows = [row for row in creatures
                           if row.get("name", "").casefold() == target.casefold()]
            self.assertEqual(len(target_rows), 1)
            target_rows[0]["currentHitPoints"] = value

        set_target_hp(before, 40)
        current_hp = 40
        step_rows = []
        source_start = 0
        for script_row in script:
            before_step = copy.deepcopy(before)
            set_target_hp(before_step, current_hp)
            before_step["observation"] = {
                "runtimeTrace": {"status": "captured", "offset_bytes": source_start},
            }
            if script_row["input"].startswith("/dmg "):
                current_hp -= int(script_row["input"].split()[1])
            elif script_row["unit_type"] == "batch":
                current_hp -= 7
            after_step = copy.deepcopy(before_step)
            set_target_hp(after_step, current_hp)
            after_step["observation"] = {
                "runtimeTrace": {
                    "status": "captured", "offset_bytes": source_start + 100,
                },
                "input": script_row["input"],
                "label": script_row["label"],
                "character": script_row.get("character"),
            }
            step_rows.append({"before": before_step, "after": after_step})
            source_start += 100
        set_target_hp(after, current_hp)
        after_ally = next(
            row for row in after["records"]["selected_encounter"]["creatures"]
            if row.get("name") == fixtures.G5A_ALLY_NAME
        )
        after_ally.pop("coverFeatureId", None)
        after_ally.pop("coverType", None)

        initial = copy.deepcopy(next(
            row for row in base_events
            if row.get("observation") == "ally_prefetch_submission" and
            row.get("request_kind") == "initial"
        ))
        accepted = copy.deepcopy(next(
            row for row in base_events
            if row.get("observation") == "ally_directive_accepted"
        ))
        replan = copy.deepcopy(next(
            row for row in base_events
            if row.get("observation") == "ally_prefetch_submission" and
            row.get("request_kind") == "replan"
        ))
        initial["_source_byte_start"], initial["_source_byte_end"] = 5, 15
        accepted["_source_byte_start"], accepted["_source_byte_end"] = 20, 30
        replan["_source_byte_start"], replan["_source_byte_end"] = 35, 45
        commit = copy.deepcopy(next(
            row for row in base_events
            if row.get("observation") == "ally_choice_commit_result"
        ))
        commit.update({
            "choice_kind": "attack",
            "choice_legal": True,
            "choice_defaulted": False,
            "choice_applied": True,
            "directive_request_kind": "initial",
            "prefetch_resolution": "current_menu_selected",
            "run_id": run_id,
        })
        commit.pop("cover_feature_id", None)
        batch_row = next(row for row in script if row["unit_type"] == "batch")
        batch_start = (batch_row["step"] - 1) * 100
        commit["_source_byte_start"], commit["_source_byte_end"] = (
            batch_start + 20, batch_start + 30
        )

        trace_events = [initial, accepted, replan]
        for script_row in damage_rows:
            step_start = (script_row["step"] - 1) * 100
            trace_events.append({
                "event_type": "decision",
                "decision_point": "combat_command_fast_path",
                "decision_source": "deterministic",
                "provider_call_avoided": True,
                "run_id": run_id,
                "_source_byte_start": step_start + 10,
                "_source_byte_end": step_start + 20,
            })
        trace_events.extend([
            {
                "event_type": "combat_observation",
                "observation": "combat_apply_result",
                "domain": "encounter",
                "operation": "update_encounter",
                "target": profile["scenario_id"],
                "ops": [],
                "applied": True,
                "batch_id": "enemy:r1",
                "run_id": run_id,
                "_source_byte_start": batch_start + 10,
                "_source_byte_end": batch_start + 20,
            },
            commit,
            {
                "event_type": "combat_observation",
                "observation": "combat_turn_success_publication",
                "batch_id": "enemy:r1",
                "run_id": run_id,
                "_source_byte_start": batch_start + 30,
                "_source_byte_end": batch_start + 40,
            },
            {
                "event_type": "combat_observation",
                "observation": "combat_logical_batch_completed",
                "batch_id": "enemy:r1",
                "accepted_batch": True,
                "validation_accepted": True,
                "run_id": run_id,
                "_source_byte_start": batch_start + 40,
                "_source_byte_end": batch_start + 50,
            },
        ])
        return profile, before, after, artifacts, step_rows, trace_events, metadata, sandbox

    def test_g5a_profiles_use_npc_authored_cover_and_validate_each_weapon(self):
        feature = fixtures.build_g5a_training_pit_area()["locations"][0]["tacticalFeatures"][0]
        self.assertEqual(feature["featureId"], fixtures.G5A_COVER_FEATURE_ID)
        self.assertEqual(feature["usableBy"], ["npc"])
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                profile = fixtures.build_gate_profile(
                    "g5a", "g5a-ally-p%d" % party_size, party_size
                )
                result = fixtures.validate_g5a_scripted_damage(party_size)
                self.assertEqual(profile["gate"], "g5a")
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["checked"], party_size)
                expected_weapons = {name: weapon for name, (weapon, _damage)
                                    in fixtures.G5A_PC_WEAPONS.items()
                                    if name in ([fixtures.ONE_PC_NAME] if party_size == 1
                                                else fixtures.PC_NAMES)}
                self.assertEqual({row["actor"]: row["weapon"]
                                  for row in result["observations"]}, expected_weapons)
                rows = fixtures.build_g5a_script_steps(party_size)
                damage_row = next(row for row in rows if row["input"].startswith("/dmg "))
                damage_row["input"] = "/dmg 99 round 1"
                invalid = fixtures.validate_g5a_scripted_damage(party_size, rows)
                self.assertEqual(invalid["status"], "FAIL")
                self.assertIn("damage_outside_declared_weapon_range", invalid["errors"])
                rows = fixtures.build_g5a_script_steps(party_size)
                damage_row = next(row for row in rows if row["input"].startswith("/dmg "))
                damage_row["input"] = "/dmg unknown round 1"
                malformed = fixtures.validate_g5a_scripted_damage(party_size, rows)
                self.assertEqual(malformed["status"], "FAIL")
                self.assertIn("scripted_damage_command_malformed", malformed["errors"])

    def test_accepted_command_traces_only_after_private_history_persists(self):
        encounter = {"encounterId": "g5a-ally-p1", "combat_round": 1,
                     "creatures": [
                         {"name": "Blairen", "type": "npc", "currentHitPoints": 12,
                          "status": "alive"},
                         {"name": "Goblin", "type": "enemy", "currentHitPoints": 20,
                          "status": "alive"},
                     ]}
        history = []
        saved = []
        order = []
        output = []
        io = FastCommandIO(
            emit=output.append, flush=lambda: None, debug=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            save_json=lambda path, value: (
                order.append("saved"), saved.append((path, copy.deepcopy(value))), True
            )[-1],
            persist_encounter=lambda *a, **k: True,
        )
        directive = "take cover behind the shield racks"
        directive_sha256 = hashlib.sha256(directive.encode("utf-8")).hexdigest()

        def fail_optional_trace(*_args):
            order.append("trace")
            raise OSError("trace unavailable")

        with patch("core.combat.enemy_batch_apply.is_ally_prefetch_enabled", return_value=False), \
                patch("core.combat.enemy_batch_apply.is_ally_controller_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(
                    combat_latency_trace, "trace_ally_directive_accepted",
                    side_effect=fail_optional_trace,
                ) as trace:
            result = _run_ally_directive_command(
                clean_input="/cmd Blairen " + directive,
                encounter_data=encounter,
                encounter_id="g5a-ally-p1",
                active_encounter_id="g5a-ally-p1",
                conversation_history=history,
                conversation_history_file="history.json",
                io=io,
                result=FastCommandResult(),
            )
        self.assertEqual(result.status, "accepted")
        self.assertEqual(len(saved), 1)
        trace.assert_called_once_with("enemy:r1", "actor_1", directive_sha256)
        self.assertEqual(order, ["saved", "trace"])

        failing_io = FastCommandIO(
            emit=lambda _text: None, flush=lambda: None, debug=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            save_json=lambda _path, _value: False,
            persist_encounter=lambda *a, **k: True,
        )
        with patch("core.combat.enemy_batch_apply.is_ally_prefetch_enabled", return_value=False), \
                patch("core.combat.enemy_batch_apply.is_ally_controller_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_ally_directive_accepted") as trace:
            failed = _run_ally_directive_command(
                clean_input="/cmd Blairen " + directive,
                encounter_data=encounter,
                encounter_id="g5a-ally-p1",
                active_encounter_id="g5a-ally-p1",
                conversation_history=[],
                conversation_history_file="history.json",
                io=failing_io,
                result=FastCommandResult(),
            )
        self.assertEqual(failed.reason, "history_persist_failed")
        trace.assert_not_called()

    def test_accepted_directive_trace_records_only_hash_not_text(self):
        directive = fixtures.G5A_DIRECTIVE_TEXT
        directive_sha256 = fixtures.build_g5a_fixture_metadata(1)["directive_sha256"]
        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_combat_observation", return_value=True) as emit:
            self.assertTrue(combat_latency_trace.trace_ally_directive_accepted(
                "enemy:r1", "actor_1", directive_sha256
            ))
            self.assertFalse(combat_latency_trace.trace_ally_directive_accepted(
                "enemy:r1", "actor_1", directive
            ))
        emit.assert_called_once()
        observation, fields = emit.call_args.args[0], emit.call_args.kwargs
        self.assertEqual(observation, "ally_directive_accepted")
        self.assertEqual(fields["directive_sha256"], directive_sha256)
        self.assertNotIn(directive, json.dumps({"observation": observation, "fields": fields}))

    def test_prefetch_submission_trace_is_bounded_and_enemy_batch_attributed(self):
        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_combat_observation", return_value=True) as emit:
            self.assertTrue(combat_latency_trace.trace_ally_prefetch_submission(
                "enemy:r1", "prefetch-request-1", "initial"
            ))
            self.assertFalse(combat_latency_trace.trace_ally_prefetch_submission(
                "enemy:r1", "prefetch-request-2", "unbounded"
            ))
        emit.assert_called_once_with(
            "ally_prefetch_submission", batch_id="enemy:r1",
            request_id="prefetch-request-1", request_kind="initial",
        )
        for observation in ("ally_directive_accepted", "ally_prefetch_submission"):
            with self.subTest(observation=observation):
                self.assertEqual(
                    combat_latency_trace._enemy_batch_work_unit_context(
                        "combat_observation",
                        {"observation": observation, "batch_id": "enemy:r1",
                         "action_id": "pc:r1:acheron"},
                    ),
                    {"batch_id": "enemy:r1"},
                )

    def test_choice_commit_trace_accepts_only_hash_correlation(self):
        directive = fixtures.G5A_DIRECTIVE_TEXT
        directive_sha256 = hashlib.sha256(directive.encode("utf-8")).hexdigest()
        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_combat_observation", return_value=True) as emit:
            self.assertTrue(combat_latency_trace.trace_ally_choice_commit_result(
                "enemy:r1", "actor_1", "take_cover", True, False, True,
                cover_feature_id=fixtures.G5A_COVER_FEATURE_ID,
                directive_sha256=directive_sha256,
                directive_request_kind="replan",
                prefetch_resolution="current_menu_selected",
            ))
            self.assertFalse(combat_latency_trace.trace_ally_choice_commit_result(
                "enemy:r1", "actor_1", "take_cover", True, False, True,
                directive_sha256=directive,
                directive_request_kind="replan",
            ))
            self.assertFalse(combat_latency_trace.trace_ally_choice_commit_result(
                "enemy:r1", "actor_1", "take_cover", True, False, True,
                prefetch_resolution="unbounded raw provider response",
            ))
        emit.assert_called_once_with(
            "ally_choice_commit_result", batch_id="enemy:r1", actor_id="actor_1",
            choice_kind="take_cover", choice_legal=True, choice_defaulted=False,
            choice_applied=True, cover_feature_id=fixtures.G5A_COVER_FEATURE_ID,
            directive_sha256=directive_sha256, directive_request_kind="replan",
            prefetch_resolution="current_menu_selected",
        )
        self.assertNotIn(directive, json.dumps(emit.call_args.kwargs))

    def test_commit_trace_links_pending_directive_by_hash_only(self):
        directive = fixtures.G5A_DIRECTIVE_TEXT
        directive_sha256 = hashlib.sha256(directive.encode("utf-8")).hexdigest()
        actor = CombatantIdentity(fixtures.G5A_ALLY_NAME, "npc")
        option_id = "opt_" + "a" * 24
        cover_option = AllyOption(
            option_id, "take_cover", actor,
            feature_id=fixtures.G5A_COVER_FEATURE_ID,
            cover_type="half",
        )
        actor_menu = AllyActorMenu(actor, (), (cover_option,), option_id)
        menus = AllyMenus("g5a-ally-r1", (actor_menu,), ())
        choice = ValidatedAllyChoice(
            actor, "take_cover", (option_id,),
            cover_feature_id=fixtures.G5A_COVER_FEATURE_ID,
            cover_type="half",
        )
        stage = SimpleNamespace(
            menus=menus,
            plan=ValidatedAllyPlan("accepted", (choice,), ()),
            plan_request_kind="replan",
            prefetch_resolution="current_menu_selected",
        )
        history = [build_ally_directive_history_record(actor.name, directive)]
        committed = {"creatures": [{
            "name": actor.name, "type": "npc",
            "coverFeatureId": fixtures.G5A_COVER_FEATURE_ID,
            "coverType": "half",
        }]}
        actor_ids = {("npc", actor.name.casefold()): "actor_1"}

        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_ally_choice_commit_result",
                             return_value=True) as emit:
            _trace_ally_choice_commit_results(
                stage, committed, history, batch_id="enemy:r1", actor_ids=actor_ids
            )

        emit.assert_called_once_with(
            "enemy:r1", "actor_1", "take_cover", True, False, True,
            cover_feature_id=fixtures.G5A_COVER_FEATURE_ID,
            directive_sha256=directive_sha256,
            directive_request_kind="replan",
            prefetch_resolution="current_menu_selected",
        )
        self.assertNotIn(directive, repr(emit.call_args))

    def test_prefetch_rejection_trace_accepts_only_allowlisted_reason_codes(self):
        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_combat_observation", return_value=True) as emit:
            self.assertTrue(combat_latency_trace.trace_ally_choice_commit_result(
                "enemy:r1", "actor_1", "attack", True, True, True,
                prefetch_resolution="response_rejected",
                prefetch_rejection_reason="actor_kind_invalid",
            ))
            self.assertFalse(combat_latency_trace.trace_ally_choice_commit_result(
                "enemy:r1", "actor_1", "attack", True, True, True,
                prefetch_resolution="response_rejected",
                prefetch_rejection_reason="provider said: malformed actor kind",
            ))
            self.assertFalse(combat_latency_trace.trace_ally_choice_commit_result(
                "enemy:r1", "actor_1", "attack", True, True, True,
                prefetch_resolution="prefetch_unavailable",
                prefetch_rejection_reason="actor_kind_invalid",
            ))

        emit.assert_called_once_with(
            "ally_choice_commit_result", batch_id="enemy:r1", actor_id="actor_1",
            choice_kind="attack", choice_legal=True, choice_defaulted=True,
            choice_applied=True, prefetch_resolution="response_rejected",
            prefetch_rejection_reason="actor_kind_invalid",
        )

    def test_g5a_checks_link_accepted_directive_to_applied_legal_cover(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                profile, before, after, artifacts, events, metadata, sandbox = self._case(
                    party_size, "g5a-test-p%d" % party_size
                )
                rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, [], events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                statuses = {row["id"]: row["status"] for row in rows}
                self.assertEqual(statuses["g5a_scripted_damage_legal"], "PASS")
                self.assertEqual(statuses["g5a_party_and_active_ally"], "PASS")
                self.assertEqual(statuses["g5a_accepted_directive"], "PASS")
                self.assertEqual(statuses["g5a_directive_take_cover"], "PASS")
                self.assertEqual(statuses["g5a_no_forbidden_ally_choice"], "PASS")
                self.assertEqual(statuses["g5a_ally_call_bounds"], "PASS")
                self.assertEqual(statuses["g5a_sandbox_flags"], "PASS")

                inactive_before = copy.deepcopy(before)
                inactive_before["records"]["selected_encounter"]["creatures"][-1][
                    "currentHitPoints"
                ] = 0
                inactive_rows = capture_evidence.observed_checks(
                    profile, inactive_before, after, artifacts, [], events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                inactive_statuses = {row["id"]: row["status"] for row in inactive_rows}
                self.assertEqual(inactive_statuses["g5a_party_and_active_ally"], "FAIL")

                invalid_events = copy.deepcopy(events)
                commit = next(row for row in invalid_events
                              if row.get("observation") == "ally_choice_commit_result")
                commit["choice_kind"] = "move_to_cover"
                invalid_rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, [], invalid_events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                invalid_statuses = {row["id"]: row["status"] for row in invalid_rows}
                self.assertEqual(invalid_statuses["g5a_no_forbidden_ally_choice"], "FAIL")
                self.assertEqual(invalid_statuses["g5a_directive_take_cover"], "FAIL")

                defaulted_events = copy.deepcopy(events)
                defaulted_commit = next(row for row in defaulted_events
                                        if row.get("observation") == "ally_choice_commit_result")
                defaulted_commit["choice_defaulted"] = True
                defaulted_rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, [], defaulted_events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                defaulted_statuses = {row["id"]: row["status"] for row in defaulted_rows}
                self.assertEqual(defaulted_statuses["g5a_directive_take_cover"], "FAIL")

                unpersisted_after = copy.deepcopy(after)
                unpersisted_ally = next(
                    row for row in unpersisted_after["records"]["selected_encounter"]["creatures"]
                    if row.get("name") == fixtures.G5A_ALLY_NAME
                )
                unpersisted_ally.pop("coverFeatureId", None)
                unpersisted_ally.pop("coverType", None)
                unpersisted_rows = capture_evidence.observed_checks(
                    profile, before, unpersisted_after, artifacts, [], events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                unpersisted_statuses = {
                    row["id"]: row["status"] for row in unpersisted_rows
                }
                self.assertEqual(
                    unpersisted_statuses["g5a_directive_take_cover"], "FAIL"
                )
                cover_observation = next(
                    row["observed"] for row in rows
                    if row["id"] == "g5a_directive_take_cover"
                )
                self.assertEqual(cover_observation["persisted_cover"]["status"], "ok")

                missing_events = [row for row in events
                                  if row.get("observation") != "ally_directive_accepted"]
                missing_rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, [], missing_events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                missing_statuses = {row["id"]: row["status"] for row in missing_rows}
                self.assertEqual(missing_statuses["g5a_accepted_directive"], "BLOCKED")

    def test_g5a_hp_reconciliation_uses_source_positioned_step_snapshots(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                profile, before, after, artifacts, _, metadata, sandbox = self._case(
                    party_size, "g5a-hp-step-p%d" % party_size
                )
                target = (
                    fixtures.ONE_PC_ENEMY_NAME if party_size == 1
                    else fixtures.ENEMY_NAMES[0]
                )

                def set_target_hp(snapshot, value):
                    creatures = snapshot["records"]["selected_encounter"]["creatures"]
                    next(row for row in creatures if row["name"] == target)[
                        "currentHitPoints"
                    ] = value

                # Run totals include an earlier scripted -3; this batch itself
                # applies -4 and must be compared only to its linked step span.
                set_target_hp(before, 20)
                set_target_hp(after, 13)
                step_before = copy.deepcopy(before)
                step_after = copy.deepcopy(before)
                set_target_hp(step_before, 17)
                set_target_hp(step_after, 13)
                step_before["observation"] = {
                    "runtimeTrace": {"status": "captured", "offset_bytes": 0}
                }
                step_after["observation"] = {
                    "runtimeTrace": {"status": "captured", "offset_bytes": 100}
                }
                steps = [{"before": step_before, "after": step_after}]
                apply_event = {
                    "event_type": "combat_observation",
                    "observation": "combat_apply_result",
                    "applied": True,
                    "domain": "encounter",
                    "target": target,
                    "ops": [{"op": "hp_delta", "creature": target, "delta": -4}],
                    "_source_byte_start": 20,
                    "_source_byte_end": 40,
                }

                rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, steps, [apply_event],
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                hp_check = next(
                    row for row in rows
                    if row["id"] == "hp_delta_snapshot_reconciliation"
                )
                self.assertEqual(hp_check["status"], "PASS")
                self.assertEqual(hp_check["observed"], [{
                    "step": 1,
                    "domain": "encounter",
                    "target": target,
                    "expected_delta": -4,
                    "observed_delta": -4,
                    "evidence_source": "source_positioned_apply_operation",
                }])

                misplaced_event = dict(apply_event)
                misplaced_event.pop("_source_byte_start")
                misplaced_event.pop("_source_byte_end")
                blocked_rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, steps, [misplaced_event],
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                blocked_hp = next(
                    row for row in blocked_rows
                    if row["id"] == "hp_delta_snapshot_reconciliation"
                )
                self.assertEqual(blocked_hp["status"], "BLOCKED")

                mismatched_step_after = copy.deepcopy(step_after)
                set_target_hp(mismatched_step_after, 12)
                mismatch_rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts,
                    [{"before": step_before, "after": mismatched_step_after}],
                    [apply_event],
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                mismatch_hp = next(
                    row for row in mismatch_rows
                    if row["id"] == "hp_delta_snapshot_reconciliation"
                )
                self.assertEqual(mismatch_hp["status"], "FAIL")

    def test_g5a_pending_replan_legal_initial_attack_is_not_observed(self):
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                (profile, before, after, artifacts, steps, events, metadata,
                 sandbox) = self._pending_replan_attack_case(party_size)
                rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, steps, events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                checks = {row["id"]: row for row in rows}
                self.assertEqual(checks["g5a_accepted_directive"]["status"], "PASS")
                self.assertEqual(checks["g5a_directive_take_cover"]["status"], "NOT_OBSERVED")
                self.assertTrue(
                    checks["g5a_directive_take_cover"]["observed"]["legal_noncover_observed"]
                )
                self.assertEqual(checks["g5a_no_forbidden_ally_choice"]["status"], "PASS")
                self.assertEqual(checks["g5a_applied_choice_legality"]["status"], "PASS")

                call_check = checks["g5a_ally_call_bounds"]
                self.assertEqual(call_check["status"], "PASS")
                self.assertEqual(call_check["observed"]["background_submission_count"], 2)
                self.assertEqual(call_check["observed"]["synchronous_calls"], 1)
                self.assertEqual(call_check["observed"]["selected_request_kind"], "initial")

                narration_event = next(
                    row for row in artifacts["trace_provider_events"]
                    if row.get("purpose") == "combat_ally_batch_narration"
                )
                ambiguous_artifacts = copy.deepcopy(artifacts)
                ambiguous_artifacts["trace_provider_events"].append(
                    copy.deepcopy(narration_event)
                )
                ambiguous_rows = capture_evidence.observed_checks(
                    profile, before, after, ambiguous_artifacts, steps, events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                ambiguous_calls = next(
                    row for row in ambiguous_rows if row["id"] == "g5a_ally_call_bounds"
                )
                self.assertEqual(ambiguous_calls["status"], "BLOCKED")
                self.assertEqual(
                    ambiguous_calls["observed"]["duplicate_synchronous_call_ids"],
                    [narration_event["call_id"]],
                )

                over_cap_artifacts = copy.deepcopy(artifacts)
                over_cap_artifacts["trace_provider_events"].extend([
                    copy.deepcopy(narration_event), copy.deepcopy(narration_event),
                ])
                over_cap_rows = capture_evidence.observed_checks(
                    profile, before, after, over_cap_artifacts, steps, events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                over_cap_calls = next(
                    row for row in over_cap_rows if row["id"] == "g5a_ally_call_bounds"
                )
                self.assertEqual(over_cap_calls["status"], "FAIL")
                self.assertEqual(
                    over_cap_calls["observed"]["synchronous_provider_event_count"], 3
                )

                hp_check = checks["hp_delta_snapshot_reconciliation"]
                self.assertEqual(hp_check["status"], "PASS")
                hp_rows = hp_check["observed"]
                damage_steps = [row["step"] for row in metadata["fixture"]["steps"]
                                if row["input"].startswith("/dmg ")]
                damage_target = next(row["target"] for row in metadata["fixture"]["steps"]
                                     if row["input"].startswith("/dmg "))
                self.assertEqual(
                    [row["expected_delta"] for row in hp_rows
                     if row["step"] in damage_steps],
                    [-3] * party_size,
                )
                batch_step = metadata["fixture"]["ally_batch_step"]
                batch_hp = next(row for row in hp_rows if row["step"] == batch_step)
                self.assertEqual(batch_hp["expected_delta"], -7)
                self.assertEqual(
                    batch_hp["evidence_source"],
                    "successful_batch_commit_and_step_snapshots",
                )

                missing_state_steps = copy.deepcopy(steps)
                missing_state = missing_state_steps[-1]["after"]["records"][
                    "selected_encounter"
                ]["creatures"]
                missing_state[:] = [row for row in missing_state
                                    if row.get("name", "").casefold() !=
                                    damage_target.casefold()]
                missing_rows = capture_evidence.observed_checks(
                    profile, before, after, artifacts, missing_state_steps, events,
                    g5a_metadata=metadata,
                    g5a_sandbox_identity=sandbox,
                )
                missing_hp = next(row for row in missing_rows
                                  if row["id"] == "hp_delta_snapshot_reconciliation")
                self.assertEqual(missing_hp["status"], "BLOCKED")

    def test_ally_cover_trace_requires_real_projected_and_committed_state(self):
        capture_evidence.G5A_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        run_id = "g5a-ally-cover-commit-test"
        profile, before, after, artifacts, events, metadata, sandbox = self._case(
            1, run_id
        )
        actor = CombatantIdentity(fixtures.G5A_ALLY_NAME, "npc")
        option_id = "opt_" + "b" * 24
        cover_option = AllyOption(
            option_id,
            "take_cover",
            actor,
            feature_id=fixtures.G5A_COVER_FEATURE_ID,
            cover_type="half",
        )
        actor_menu = AllyActorMenu(actor, (), (cover_option,), option_id)
        menus = AllyMenus("enemy:r1", (actor_menu,), ())
        choice = ValidatedAllyChoice(
            actor,
            "take_cover",
            (option_id,),
            cover_feature_id=fixtures.G5A_COVER_FEATURE_ID,
            cover_type="half",
        )
        plan = ValidatedAllyPlan("accepted", (choice,), ())
        encounter_before = {
            "encounterId": "g5a-ally-p1",
            "combat_round": 1,
            "combat_phase": "ENEMY_PHASE",
            "current_round": 1,
            "turn_receipts": [],
            "creatures": [
                {"name": "Acheron", "type": "player", "currentHitPoints": 20,
                 "maxHitPoints": 20, "status": "alive"},
                {"name": "Goblin", "type": "enemy", "currentHitPoints": 20,
                 "maxHitPoints": 20, "armorClass": 12, "status": "alive"},
                {"name": fixtures.G5A_ALLY_NAME, "type": "npc",
                 "currentHitPoints": 12, "maxHitPoints": 12, "armorClass": 13,
                 "status": "alive"},
            ],
        }
        ledger = resolve_ally_batch(menus, plan, encounter_before)
        self.assertEqual(len(ledger.cover_updates), 1)
        projected_encounter = project_combat_resolution_ledger(
            ledger, encounter_before
        )
        projected_ally = next(
            row for row in projected_encounter["creatures"]
            if row.get("name") == fixtures.G5A_ALLY_NAME
        )
        self.assertEqual(
            projected_ally.get("coverFeatureId"), fixtures.G5A_COVER_FEATURE_ID
        )
        self.assertEqual(projected_ally.get("coverType"), "half")

        history = [build_ally_directive_history_record(
            actor.name, fixtures.G5A_DIRECTIVE_TEXT
        )]
        stage = SimpleNamespace(
            menus=menus,
            plan=plan,
            plan_request_kind="replan",
            prefetch_resolution="current_menu_selected",
            prefetch_rejection_reason=None,
        )
        actor_ids = combat_latency_trace.build_run_local_actor_ids(
            encounter_before["creatures"]
        )

        with tempfile.TemporaryDirectory(
            prefix="ally-cover-commit-", dir=str(capture_evidence.G5A_RUN_ROOT)
        ) as scratch:
            root = Path(scratch)
            encounter_path = root / "encounters" / "encounter_g5a-ally-p1.json"
            history_path = root / "history.json"
            trace_path = root / "trace.jsonl"
            encounter_path.parent.mkdir(parents=True, exist_ok=True)
            self.assertTrue(file_operations.safe_write_json(
                str(encounter_path), encounter_before, create_backup=False
            ))

            class PathManager:
                def get_encounter_path_from_id(self, encounter_id):
                    return str(encounter_path)

                def get_character_path(self, name):
                    return str(root / "characters" / (name + ".json"))

            def write_json(path, payload):
                return file_operations.safe_write_json(
                    path, payload, create_backup=False
                )

            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                    patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path), \
                    patch.dict(os.environ, {"NEQ_G5_CAPTURE_RUN_ID": run_id}), \
                    patch.dict(combat_latency_trace._TRACE_CONTEXT, {}, clear=True):
                combat_latency_trace.set_trace_context(
                    mode="mp", phase="ENEMY_PHASE", combat_round=1,
                    batch_id="enemy:r1",
                )
                _trace_ally_cover_selections(
                    menus,
                    plan,
                    batch_id="enemy:r1",
                    actor_ids=actor_ids,
                )
                application = apply_enemy_batch(
                    ledger,
                    NarrationResult("Blairen takes cover.", "template"),
                    user_input_text="Enemies turn.",
                    turn_id="00000000-0000-4000-8000-000000000024",
                    conversation_history=copy.deepcopy(history),
                    conversation_history_file=str(history_path),
                    encounter_projection=projected_encounter,
                    path_manager=PathManager(),
                    read_json=file_operations.safe_read_json,
                    write_json=write_json,
                    ally_directive_actors=(actor,),
                )
                events_before_ally_trace = [
                    json.loads(line)
                    for line in trace_path.read_text(encoding="ascii").splitlines()
                ]
                self.assertTrue(any(
                    row.get("observation") == "combat_cover_outcome"
                    and row.get("cover_state") == "selected"
                    for row in events_before_ally_trace
                ))
                self.assertFalse(any(
                    row.get("observation") == "combat_cover_outcome"
                    and row.get("cover_state") == "applied"
                    for row in events_before_ally_trace
                ))
                committed = file_operations.safe_read_json(str(encounter_path))
                self.assertIsInstance(committed, dict)
                committed_ally = next(
                    row for row in committed["creatures"]
                    if row.get("name") == fixtures.G5A_ALLY_NAME
                )
                self.assertEqual(
                    committed_ally.get("coverFeatureId"), fixtures.G5A_COVER_FEATURE_ID
                )
                self.assertEqual(committed_ally.get("coverType"), "half")
                _trace_ally_choice_commit_results(
                    stage,
                    application.encounter_projection,
                    history,
                    batch_id="enemy:r1",
                    actor_ids=actor_ids,
                )
                trace_events = [
                    json.loads(line)
                    for line in trace_path.read_text(encoding="ascii").splitlines()
                ]

        cover_events = [row for row in trace_events
                        if row.get("observation") == "combat_cover_outcome"]
        self.assertEqual(
            {(row.get("cover_state"), row.get("feature_id"), row.get("cover_type"))
             for row in cover_events},
            {
                ("selected", fixtures.G5A_COVER_FEATURE_ID, "half"),
                ("applied", fixtures.G5A_COVER_FEATURE_ID, "half"),
            },
        )
        commit = next(row for row in trace_events
                      if row.get("observation") == "ally_choice_commit_result")
        self.assertIs(commit.get("choice_applied"), True)

        after["records"]["selected_encounter"] = {"status": "ok", **committed}
        evaluated_events = [
            row for row in events
            if row.get("observation") not in {
                "ally_choice_commit_result", "combat_cover_outcome",
            }
        ] + [row for row in trace_events if row.get("observation") in {
            "ally_choice_commit_result", "combat_cover_outcome",
        }]
        batch_window = next(
            row for row in metadata["trace_windows"]["steps"]
            if row.get("unit_type") == "batch"
        )
        emitted_times = [row["recorded_at_ms"] for row in trace_events
                         if row.get("observation") in {
                             "ally_choice_commit_result", "combat_cover_outcome",
                         }]
        batch_window["start_epoch_ms"] = min(emitted_times) - 1
        batch_window["end_epoch_ms"] = max(emitted_times) + 1
        rows = capture_evidence.observed_checks(
            profile, before, after, artifacts, [], evaluated_events,
            g5a_metadata=metadata,
            g5a_sandbox_identity=sandbox,
        )
        cover_check = next(row for row in rows
                           if row["id"] == "g5a_directive_take_cover")
        self.assertEqual(cover_check["status"], "PASS")
        self.assertEqual(cover_check["observed"]["persisted_cover"]["status"], "ok")

        missing_cover_commit = copy.deepcopy(application.encounter_projection)
        missing_cover_ally = next(
            row for row in missing_cover_commit["creatures"]
            if row.get("name") == fixtures.G5A_ALLY_NAME
        )
        missing_cover_ally.pop("coverFeatureId", None)
        missing_cover_ally.pop("coverType", None)
        rejected_trace_events = []

        def collect_trace_event(observation, **fields):
            rejected_trace_events.append({"observation": observation, **fields})
            return True

        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_combat_observation",
                             side_effect=collect_trace_event):
            _trace_ally_choice_commit_results(
                stage,
                missing_cover_commit,
                history,
                batch_id="enemy:r1",
                actor_ids=actor_ids,
            )
        rejected_commit = next(
            row for row in rejected_trace_events
            if row.get("observation") == "ally_choice_commit_result"
        )
        self.assertIs(rejected_commit.get("choice_applied"), False)
        self.assertFalse(any(
            row.get("observation") == "combat_cover_outcome"
            and row.get("cover_state") == "applied"
            for row in rejected_trace_events
        ))

    def test_g5a_call_bounds_uses_trace_order_for_same_millisecond_events(self):
        profile, before, after, artifacts, events, metadata, sandbox = self._case()
        directive_index = next(
            index for index, row in enumerate(events)
            if row.get("observation") == "ally_directive_accepted"
        )
        replan_index = next(
            index for index, row in enumerate(events)
            if row.get("observation") == "ally_prefetch_submission"
            and row.get("request_kind") == "replan"
        )
        events[replan_index]["recorded_at_ms"] = events[directive_index]["recorded_at_ms"]

        rows = capture_evidence.observed_checks(
            profile, before, after, artifacts, [], events,
            g5a_metadata=metadata,
            g5a_sandbox_identity=sandbox,
        )
        status = next(row["status"] for row in rows
                      if row["id"] == "g5a_ally_call_bounds")
        self.assertEqual(status, "PASS")

        reversed_events = copy.deepcopy(events)
        reversed_events[directive_index], reversed_events[replan_index] = (
            reversed_events[replan_index], reversed_events[directive_index]
        )
        reversed_rows = capture_evidence.observed_checks(
            profile, before, after, artifacts, [], reversed_events,
            g5a_metadata=metadata,
            g5a_sandbox_identity=sandbox,
        )
        reversed_status = next(row["status"] for row in reversed_rows
                               if row["id"] == "g5a_ally_call_bounds")
        self.assertEqual(reversed_status, "FAIL")

    def _report_runs(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        runs = []
        for party_size in (1, 4):
            for number in range(1, 4):
                run_id = "g5a-p%d-run-%d" % (party_size, number)
                run_dir = root / run_id
                run_dir.mkdir()
                manifest = {
                    "gate": "g5a", "run_id": run_id,
                    "party": {"size": party_size},
                    "scenario": {"id": "g5a-ally-p%d" % party_size},
                    "source": {
                        "head": "a" * 40,
                        "relevant_dirty_sha256": "c" * 64,
                        "relevant_source_sha256": {
                            "core/combat/ally_controller.py": "b" * 64,
                        },
                    },
                    "prompt_identity_sha256": capture_evidence._prompt_identity(),
                }
                (run_dir / "manifest.json").write_text(
                    json.dumps(manifest, sort_keys=True), encoding="ascii"
                )
                runs.append(run_dir)
        return runs

    def test_g5a_offline_report_requires_three_runs_per_shape_and_one_revision(self):
        with tempfile.TemporaryDirectory(
                prefix="g5a-report-", dir=str(capture_evidence.G5A_RUN_ROOT)) as scratch:
            runs = self._report_runs(Path(scratch))

            def load_bundle(run_dir):
                manifest = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="ascii"))
                checks = [
                    {"id": "g5a_accepted_directive", "status": "PASS"},
                    {"id": "g5a_directive_take_cover", "status": "PASS"},
                    {"id": "g5a_party_and_active_ally", "status": "PASS"},
                    {"id": "g5a_applied_choice_legality", "status": "PASS"},
                ]
                return {"manifest": manifest, "evaluation": {
                    "automated_status": "READY_FOR_PRIMARY_REVIEW", "checks": checks,
                }}

            with patch.object(capture_evidence, "_load_run_evidence", side_effect=load_bundle):
                output = StringIO()
                argv = ["--gate", "g5a"]
                for run_dir in runs:
                    argv.extend(("--run-dir", str(run_dir)))
                with redirect_stdout(output):
                    exit_code = capture_evidence.main(argv)
                report = json.loads(output.getvalue())
                self.assertEqual(exit_code, 0)
                self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
                self.assertEqual(report["primary_verdict"], "PENDING")
                self.assertEqual(report["same_source_revision"], True)
                self.assertTrue(report["source_revision"]["prompt_identity_sha256"])
                self.assertEqual(report["party_shapes"]["1"]["observed_runs"], 3)
                self.assertTrue(report["party_shapes"]["4"]["applied_legal_take_cover_observed"])

                bool_size_manifest = json.loads(
                    (runs[0] / "manifest.json").read_text(encoding="ascii")
                )
                bool_size_manifest["party"]["size"] = True
                bool_size_manifest["scenario"]["id"] = "g5a-ally-pTrue"
                (runs[0] / "manifest.json").write_text(
                    json.dumps(bool_size_manifest, sort_keys=True), encoding="ascii"
                )
                bool_size = capture_evidence.evaluate_g5a_matrix(runs)
                self.assertEqual(bool_size["automated_status"], "BLOCKED")
                self.assertIn("g5a_identity_missing_or_mismatched:g5a-p1-run-1",
                              bool_size["blocking_reasons"])
                bool_size_manifest["party"]["size"] = 1
                bool_size_manifest["scenario"]["id"] = "g5a-ally-p1"
                (runs[0] / "manifest.json").write_text(
                    json.dumps(bool_size_manifest, sort_keys=True), encoding="ascii"
                )

                blocked = capture_evidence.evaluate_g5a_matrix(runs[:-1])
                self.assertEqual(blocked["automated_status"], "BLOCKED")
                self.assertIn("p4_requires_exactly_three_bundles", blocked["blocking_reasons"])

                changed_manifest = json.loads(
                    (runs[-1] / "manifest.json").read_text(encoding="ascii")
                )
                changed_manifest["source"]["head"] = "d" * 40
                (runs[-1] / "manifest.json").write_text(
                    json.dumps(changed_manifest, sort_keys=True), encoding="ascii"
                )
                changed_revision = capture_evidence.evaluate_g5a_matrix(runs)
                self.assertEqual(changed_revision["automated_status"], "BLOCKED")
                self.assertFalse(changed_revision["same_source_revision"])
                self.assertIn("runs_do_not_share_one_source_revision",
                              changed_revision["blocking_reasons"])

                changed_manifest["source"]["head"] = "a" * 40
                changed_manifest["source"]["relevant_source_sha256"][
                    "core/combat/ally_controller.py"
                ] = "not-a-sha256"
                (runs[-1] / "manifest.json").write_text(
                    json.dumps(changed_manifest, sort_keys=True), encoding="ascii"
                )
                malformed_revision = capture_evidence.evaluate_g5a_matrix(runs)
                self.assertEqual(malformed_revision["automated_status"], "BLOCKED")
                self.assertFalse(malformed_revision["same_source_revision"])
                self.assertIn("p4_source_identity_missing:g5a-p4-run-3",
                              malformed_revision["blocking_reasons"])

                changed_manifest["source"]["relevant_source_sha256"][
                    "core/combat/ally_controller.py"
                ] = "b" * 64
                first_prompt = next(iter(changed_manifest["prompt_identity_sha256"]))
                changed_manifest["prompt_identity_sha256"][first_prompt] = "e" * 64
                (runs[-1] / "manifest.json").write_text(
                    json.dumps(changed_manifest, sort_keys=True), encoding="ascii"
                )
                changed_prompts = capture_evidence.evaluate_g5a_matrix(runs)
                self.assertEqual(changed_prompts["automated_status"], "BLOCKED")
                self.assertFalse(changed_prompts["same_source_revision"])
                self.assertIn("runs_do_not_share_one_source_revision",
                              changed_prompts["blocking_reasons"])

    def test_g5a_aggregate_blocks_when_either_party_shape_has_no_cover_observation(self):
        for missing_party in (1, 4):
            with self.subTest(missing_party=missing_party), tempfile.TemporaryDirectory(
                    prefix="g5a-no-cover-", dir=str(capture_evidence.G5A_RUN_ROOT)) as scratch:
                runs = self._report_runs(Path(scratch))

                def load_bundle(run_dir):
                    manifest = json.loads(
                        (Path(run_dir) / "manifest.json").read_text(encoding="ascii")
                    )
                    party_size = manifest["party"]["size"]
                    cover_status = "NOT_OBSERVED" if party_size == missing_party else "PASS"
                    checks = [
                        {"id": "g5a_accepted_directive", "status": "PASS"},
                        {"id": "g5a_directive_take_cover", "status": cover_status},
                        {"id": "g5a_party_and_active_ally", "status": "PASS"},
                        {"id": "g5a_applied_choice_legality", "status": "PASS"},
                    ]
                    return {"manifest": manifest, "evaluation": {
                        "automated_status": "READY_FOR_PRIMARY_REVIEW", "checks": checks,
                    }}

                with patch.object(capture_evidence, "_load_run_evidence",
                                  side_effect=load_bundle):
                    report = capture_evidence.evaluate_g5a_matrix(runs)

                shape = report["party_shapes"][str(missing_party)]
                self.assertEqual(report["automated_status"], "BLOCKED")
                self.assertFalse(shape["honored_directive_observed"])
                self.assertFalse(shape["applied_legal_take_cover_observed"])
                self.assertEqual(shape["coverage_status"], "BLOCKED")
                self.assertIn(
                    "p%d_honored_directive_not_observed" % missing_party,
                    report["blocking_reasons"],
                )
                self.assertIn(
                    "p%d_applied_legal_take_cover_not_observed" % missing_party,
                    report["blocking_reasons"],
                )
                self.assertEqual(report["failed_runs"], [])
                other_party = 4 if missing_party == 1 else 1
                self.assertTrue(
                    report["party_shapes"][str(other_party)]["honored_directive_observed"]
                )
                self.assertTrue(
                    report["party_shapes"][str(other_party)]["applied_legal_take_cover_observed"]
                )

    def test_g5a_prompt_inventory_includes_feature_prompts_without_changing_g5t_legacy_count(self):
        g5a_profile = fixtures.build_gate_profile(
            "g5a", "g5a-ally-p1", 1
        )
        g5a_manifest = {
            "gate": "g5a", "scenario": {"id": "g5a-ally-p1"},
            "party": {"size": 1},
            "prompt_identity_sha256": capture_evidence._prompt_identity(),
            "counts": {}, "bounds": {"turn_timeout_seconds": 150},
            "source": {}, "sandbox_runtime": {"trace_gate": {"status": "ok", "enabled": True}},
            "transport": {"client_source": "socketio.Client"},
        }
        result = capture_evidence.evaluate_evidence(
            g5a_manifest, [], {"matrix_keys": ["g5a-ally-p1:p1"],
                               "required_evidence_status": "ok"},
            run_dir=Path("tmp/router-rollout/g5a"), integrity={"failures": []},
            profile=g5a_profile,
        )
        self.assertNotIn("prompt_identity_missing", result["problems"])

        g5t_profile = fixtures.build_gate_profile(
            "g5t", "g5t-commander-p1", 1
        )
        g5t_manifest = {
            "gate": "g5t", "scenario": {"id": "g5t-commander-p1"},
            "party": {"size": 1},
            "prompt_identity_sha256": {"legacy-prompt-%d.txt" % index: "f" * 64
                                       for index in range(9)},
            "counts": {}, "bounds": {"turn_timeout_seconds": 150},
            "source": {}, "sandbox_runtime": {"trace_gate": {"status": "ok", "enabled": True}},
            "transport": {"client_source": "socketio.Client"},
        }
        legacy_result = capture_evidence.evaluate_evidence(
            g5t_manifest, [], {"matrix_keys": ["g5t-commander-p1:p1"],
                               "required_evidence_status": "ok"},
            run_dir=Path("tmp/router-rollout/g5a"), integrity={"failures": []},
            profile=g5t_profile,
        )
        self.assertNotIn("prompt_identity_missing", legacy_result["problems"])


if __name__ == "__main__":
    unittest.main()
