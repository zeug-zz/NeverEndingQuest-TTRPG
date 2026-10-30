# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free synthetic bundle tests for the G5T comparison report."""

import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import test_capture_drive as guarded_capture_import

capture_evidence = guarded_capture_import.capture_evidence
fixtures = guarded_capture_import.fixtures
from scripts import combat_latency_report


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("ascii")


class CombatG5TReportTests(unittest.TestCase):
    def setUp(self):
        pathlib.Path("tmp/router-rollout/g5t").mkdir(parents=True, exist_ok=True)
        self.scratch = tempfile.TemporaryDirectory(
            dir="tmp/router-rollout/g5t", prefix="task52-report-")
        self.addCleanup(self.scratch.cleanup)
        self.root = pathlib.Path(self.scratch.name)
        self.capture_index = 0

    def _make_bundle(self, party_size, run_label, settings=None, capture_mode="primary"):
        settings = dict(settings or {})
        self.capture_index += 1
        scenario_id = "g5t-commander-p%d" % party_size
        run_id = "%s-%s-p%d-%03d" % (
            run_label, capture_mode, party_size, self.capture_index)
        run_dir = self.root / run_id
        run_dir.mkdir()

        fixture = fixtures.build_g5t_fixture_metadata(party_size)
        fixture["id"] = scenario_id
        batch_steps = [row for row in fixture["steps"] if row.get("unit_type") == "batch"]
        skipped_round = settings.get("skip_batch_round")
        configured_outcomes = list(settings.get(
            "g5t_self_preservation_outcomes", ("fled", "surrendered")))
        configured_outcomes = [outcome for outcome in configured_outcomes
                               if outcome not in settings.get(
                                   "omit_self_preservation_outcomes", [])]
        removed_by_exit = settings.get("removed_by_exit", False) is True
        exit_outcome = settings.get("removed_by_exit_outcome", "surrendered")
        exit_round = (1 if exit_outcome == "fled" else 2) if removed_by_exit else None
        executed_batches = [
            row for row in batch_steps
            if row.get("round") != skipped_round and
            (exit_round is None or row.get("round", 0) <= exit_round)
        ]
        encounter_fixture = fixtures.build_g5t_commander_fixture(party_size)["encounter"]
        party_character_names = (
            ("Acheron",) if party_size == 1 else
            ("Acheron", "Merisiel", "Kira", "Vitreol")
        )
        prose_character_count = settings.get("g5t_changed_characters", 1)
        prose_character_states = {
            name: {
                "name": name, "status": "alive",
                "hitPoints": 100, "maxHitPoints": 100,
            }
            for name in party_character_names[:prose_character_count]
        }
        from utils.combat_latency_trace import build_run_local_actor_ids

        run_local_actor_ids = build_run_local_actor_ids(encounter_fixture["creatures"])
        self_actor_ids = {
            "fled": run_local_actor_ids[("enemy", fixtures.G5T_GOBLIN_NAMES[0].casefold())],
            "surrendered": run_local_actor_ids[("enemy", fixtures.G5T_GOBLIN_NAMES[1].casefold())],
        }
        trace_events = []
        plan_outcome = settings.get("g5t_plan_outcome", "accepted")
        default_reasons = settings.get("g5t_default_reasons", [])
        decision_source = settings.get("g5t_decision_source", "llm_tactical")
        receipts = []
        for batch_index, batch in enumerate(executed_batches):
            batch_id = batch["trace_batch_id"]
            start_ms = 1000.0 + batch_index * 5000.0
            end_ms = start_ms + 4000.0

            if batch.get("requires_combat_exit") is True:
                trace_events.append({
                    "event_type": "decision", "schema_version": 1, "run_id": run_id,
                    "recorded_at_ms": start_ms + 300,
                    "decision_point": "enemy_batch_resolution",
                    "decision_source": "deterministic",
                    "decision_outcome": "resolver_supported",
                    "decision_reason": "ledger_supported", "batch_id": batch_id,
                })
                if (settings.get("include_cover_events", True) and
                        batch_index == len(executed_batches) - 1 and
                        settings.get("cover_expiration_status", "PASS") != "NOT_OBSERVED"):
                    trace_events.append({
                        "event_type": "combat_observation", "schema_version": 1,
                        "run_id": run_id, "recorded_at_ms": start_ms + 601,
                        "observation": "combat_cover_outcome", "batch_id": batch_id,
                        "actor_id": self_actor_ids["surrendered"],
                        "feature_id": fixtures.G5T_TRAINING_PIT_FEATURE_ID,
                        "cover_type": "half", "cover_state": "expired",
                    })
                receipts.append({
                    "step": batch["index"], "script_step": batch["index"],
                    "status": "sent",
                    "work_unit": {"type": "batch", "id": batch["unit_id"],
                                  "round": batch["round"]},
                    "trace_window": {"start_epoch_ms": start_ms, "end_epoch_ms": end_ms},
                    "work_only_ms": settings.get("g5t_batch_ms", 10000.0),
                    "work_only_reason": None, "timed_out": False, "cap_reached": False,
                })
                continue

            def add_provider(purpose, site, index):
                trace_events.append({
                    "event_type": "provider", "schema_version": 1, "run_id": run_id,
                    "recorded_at_ms": start_ms + 100 + index,
                    "site": site, "task": site, "purpose": purpose,
                    "attempt_id": "%s-attempt-%s-%d-%d" % (
                        run_id, purpose, batch_index, index),
                    "attempt_number": 1, "batch_id": batch_id,
                    "provider": "openai", "requested_model": "gpt-6-luna",
                    "resolved_model": "gpt-6-luna", "outcome": "success",
                })

            for index in range(settings.get("g5t_plan_calls", 1)):
                add_provider("combat_enemy_batch_commander_plan", "combat_main", index)
            for index in range(settings.get("g5t_narration_calls", 1)):
                add_provider("combat_enemy_batch_narration", "combat_main", 20 + index)
            for index in range(settings.get("g5t_validation_calls", 0)):
                add_provider("combat_validation", "combat_validation", 40 + index)
            changed_character_count = settings.get("g5t_changed_characters", 1)
            for index in range(changed_character_count):
                if settings.get("g5t_prose_character_batch") == batch_id:
                    character_name = party_character_names[index]
                    persisted_state = prose_character_states[character_name]
                    trace_events.extend([
                        {
                            "event_type": "combat_observation", "schema_version": 1,
                            "run_id": run_id, "recorded_at_ms": start_ms + 350 + index,
                            "observation": "combat_apply_result", "batch_id": batch_id,
                            "domain": "character",
                            "operation": "update_character_info_prose",
                            "target": character_name,
                            "changes": "Following the turn's events: awarded experience points.",
                            "applied": True,
                        },
                        {
                            "event_type": "combat_observation", "schema_version": 1,
                            "run_id": run_id, "recorded_at_ms": start_ms + 350 + index,
                            "observation": "combat_apply_persisted_state", "batch_id": batch_id,
                            "domain": "character", "target": character_name,
                            "state_path": "characters/%s.json" % character_name.casefold(),
                            "persisted_state": persisted_state,
                        },
                    ])
                else:
                    trace_events.append({
                        "event_type": "combat_observation", "schema_version": 1,
                        "run_id": run_id, "recorded_at_ms": start_ms + 350 + index,
                        "observation": "combat_apply_result", "batch_id": batch_id,
                        "domain": "character", "operation": "update_character_info_ops",
                        "target": "Changed PC %d" % (index + 1), "applied": True,
                        "ops": [{"op": "hp_delta", "delta": -1}],
                    })
            if settings.get("include_plan_marker", True) and settings.get("g5t_plan_calls", 1):
                trace_events.append({
                    "event_type": "provider", "schema_version": 1, "run_id": run_id,
                    "recorded_at_ms": start_ms + 99, "site": "combat_tactical_plan",
                    "task": "combat_tactical_plan", "batch_id": batch_id,
                    "provider": "openai", "resolved_model": "gpt-6-luna",
                })

            departed_actor_ids = set()
            departed_target_ids = set()
            for outcome in configured_outcomes:
                outcome_round = 1 if outcome == "fled" else 2
                if batch.get("round", 0) <= outcome_round:
                    continue
                if settings.get("actor_removed", True) is not False:
                    departed_actor_ids.add(self_actor_ids[outcome])
                if settings.get("target_removed", True) is not False:
                    departed_target_ids.add(self_actor_ids[outcome])
            all_enemy_ids = [
                run_local_actor_ids[("enemy", name.casefold())]
                for name in (fixtures.G5T_COMMANDER_NAME,) + fixtures.G5T_GOBLIN_NAMES
            ]
            plan_actor_ids = [actor_id for actor_id in all_enemy_ids
                              if actor_id not in departed_actor_ids]
            plan_target_ids = [actor_id for actor_id in all_enemy_ids
                               if actor_id not in departed_target_ids]
            trace_events.extend([
                {"event_type": "combat_observation", "schema_version": 1,
                 "run_id": run_id, "recorded_at_ms": start_ms + 200,
                 "observation": "combat_tactical_plan_result", "batch_id": batch_id,
                 "plan_correlation_id": "plan-r%d" % batch["round"],
                 "tactical_plan_outcome": plan_outcome, "default_reasons": default_reasons,
                 "actor_ids": plan_actor_ids, "target_ids": plan_target_ids},
                {"event_type": "decision", "schema_version": 1, "run_id": run_id,
                 "recorded_at_ms": start_ms + 300,
                 "decision_point": "enemy_batch_resolution",
                 "decision_source": decision_source,
                 "decision_outcome": "resolver_supported", "decision_reason": "ledger_supported",
                 "batch_id": batch_id, "tactical_plan_outcome": plan_outcome,
                 "default_reasons": default_reasons},
            ])

            write_kinds = (
                ["history"]
                + ["character"] * changed_character_count
                + ["encounter"]
            )
            for index in range(settings.get("g5t_raw_writes", 3)):
                trace_events.append({
                    "event_type": "file_operation", "schema_version": 1, "run_id": run_id,
                    "recorded_at_ms": start_ms + 400 + index,
                    "category": "write", "site": "enemy_batch_write", "batch_id": batch_id,
                    "target_kind": settings.get(
                        "malformed_write_kind",
                        write_kinds[index] if index < len(write_kinds) else "history",
                    ),
                    "target_id": "target-%d-%d" % (batch_index, index),
                })

            if settings.get("include_behavior_events", True):
                for index, outcome in enumerate(configured_outcomes, 1):
                    outcome_batch = "enemy:r1" if outcome == "fled" else "enemy:r2"
                    if batch_id == outcome_batch:
                        actor_id = self_actor_ids[outcome]
                        trace_events.append({
                            "event_type": "combat_observation", "schema_version": 1,
                            "run_id": run_id, "recorded_at_ms": start_ms + 500 + index,
                            "observation": "combat_self_preservation_outcome",
                            "batch_id": batch_id, "actor_id": actor_id,
                            "self_preservation_outcome": outcome,
                        })
            if (settings.get("include_cover_events", True) and
                    settings.get("include_cover_applied_event", True) and batch_index == 0 and
                    settings.get("cover_effective_status", "PASS") != "NOT_OBSERVED"):
                trace_events.append({
                    "event_type": "combat_observation", "schema_version": 1,
                    "run_id": run_id, "recorded_at_ms": start_ms + 600,
                    "observation": "combat_cover_outcome", "batch_id": batch_id,
                    "actor_id": self_actor_ids["surrendered"], "feature_id": fixtures.G5T_TRAINING_PIT_FEATURE_ID,
                    "cover_type": "half", "cover_state": "applied",
                })
            if (settings.get("include_cover_events", True) and
                    batch_index == len(executed_batches) - 1 and
                    settings.get("cover_expiration_status", "PASS") != "NOT_OBSERVED"):
                trace_events.append({
                    "event_type": "combat_observation", "schema_version": 1,
                    "run_id": run_id, "recorded_at_ms": start_ms + 601,
                    "observation": "combat_cover_outcome", "batch_id": batch_id,
                    "actor_id": self_actor_ids["surrendered"], "feature_id": fixtures.G5T_TRAINING_PIT_FEATURE_ID,
                    "cover_type": "half", "cover_state": "expired",
                })
            if settings.get("include_squad_trace_event", decision_source == "llm_tactical"):
                followed_orders = settings.get("g5t_squad_followed_orders", True)
                issued_choice_count = settings.get("g5t_squad_issued_count", 2)
                applied_choice_count = settings.get(
                    "g5t_squad_applied_count",
                    0 if issued_choice_count == 0 else issued_choice_count if followed_orders else 1,
                )
                trace_events.append({
                    "event_type": "combat_observation", "schema_version": 1,
                    "run_id": run_id, "recorded_at_ms": start_ms + 650,
                    "observation": "commander_squad_follows_orders", "batch_id": batch_id,
                    "followed_orders": followed_orders,
                    "issued_choice_count": issued_choice_count,
                    "applied_choice_count": applied_choice_count,
                })
            for index, prefetch_status in enumerate(
                    settings.get("g5t_prefetch_statuses", []) if batch_index == 0 else []):
                trace_events.append({
                    "event_type": "combat_observation", "schema_version": 1,
                    "run_id": run_id, "recorded_at_ms": start_ms + 700 + index,
                    "observation": "combat_tactical_prefetch_status", "batch_id": batch_id,
                    "plan_correlation_id": "plan-r%d" % batch["round"],
                    "prefetch_status": prefetch_status,
                    "receipt_correlation_id": "receipt-%d" % index,
                })
            for index, request in enumerate(
                    settings.get("g5t_prefetch_requests", []) if batch_index == 0 else []):
                request_kind = request.get("request_kind", "initial")
                receipt_id = "prefetch-receipt-%d" % index
                trace_events.append({
                    "event_type": "combat_observation", "schema_version": 1,
                    "run_id": run_id, "recorded_at_ms": start_ms + 720 + index,
                    "observation": "combat_tactical_prefetch_status", "batch_id": batch_id,
                    "plan_correlation_id": "plan-r%d" % batch["round"],
                    "prefetch_status": "prefetch_none",
                    "standing_orders_outcome": (
                        "replan_submitted" if request_kind == "replan" else "submitted"
                    ),
                    "request_kind": request_kind,
                    "request_site": "combat_tactical_prefetch",
                    "receipt_correlation_id": receipt_id,
                })
                trace_events.append({
                    "event_type": "provider", "schema_version": 1,
                    "run_id": run_id, "recorded_at_ms": start_ms + 740 + index,
                    "site": "combat_tactical_prefetch",
                    "request_site": "combat_tactical_prefetch",
                    "request_kind": request_kind,
                    "purpose": "combat_enemy_batch_standing_orders",
                    "call_id": "%s-prefetch-call-%d" % (run_id, index),
                    "attempt_id": "%s-prefetch-attempt-%d" % (run_id, index),
                    "attempt_number": 1, "batch_id": batch_id,
                    "provider": "openai", "requested_model": "gpt-6-luna",
                    "resolved_model": "gpt-6-luna", "outcome": "response",
                })
            receipts.append({
                "step": batch["index"], "script_step": batch["index"],
                "status": "sent",
                "work_unit": {"type": "batch", "id": batch["unit_id"],
                              "round": batch["round"]},
                "trace_window": {"start_epoch_ms": start_ms, "end_epoch_ms": end_ms},
                "work_only_ms": settings.get("g5t_batch_ms", 10000.0),
                "work_only_reason": None, "timed_out": False, "cap_reached": False,
            })
        if executed_batches:
            exit_batch_id = executed_batches[-1]["trace_batch_id"]
            trace_events.append({
                "event_type": "combat_observation", "schema_version": 1,
                "run_id": run_id,
                "recorded_at_ms": 1000.0 + (len(executed_batches) - 1) * 5000.0 + 4200.0,
                "observation": "xp_award", "source": "auto_exit",
                "batch_id": exit_batch_id, "amount": 100,
            })
        for batch in batch_steps:
            if (batch not in executed_batches and
                    (batch.get("round") == skipped_round or
                     exit_round is not None and batch.get("round", 0) > exit_round)):
                receipts.append({
                    "step": batch["index"], "script_step": batch["index"],
                    "status": "skipped", "skip_reason": "combat_ended",
                    "work_only_ms": None,
                    "work_unit": {"type": "batch", "id": batch["unit_id"],
                                  "round": batch["round"]},
                })

        covered_step = next(row for row in fixtures.build_g5t_script_steps(party_size)
                            if "covered-target attack" in row.get("label", ""))
        receipts.append({
            "step": covered_step["step"], "script_step": covered_step["step"],
            "status": settings.get("cover_attack_status", "sent"),
            "skip_reason": settings.get("cover_attack_skip_reason"),
            "work_unit": {"type": "action", "id": covered_step["unit_id"],
                          "round": covered_step["round"]},
        })

        for index, raw_provider_row in enumerate(settings.get("exit_flow_provider_rows", [])):
            provider_row = dict(raw_provider_row)
            provider_row.setdefault("event_type", "provider")
            provider_row.setdefault("schema_version", 1)
            provider_row.setdefault("run_id", run_id)
            provider_row.setdefault("recorded_at_ms", 50000.0 + index)
            provider_row.setdefault("batch_id", "enemy:r4")
            provider_row.setdefault("attempt_id", "%s-exit-%d" % (run_id, index))
            trace_events.append(provider_row)

        trace_path = run_dir / "trace.jsonl"
        trace_bytes = b"".join(_json_bytes(event) for event in trace_events)
        trace_path.write_bytes(trace_bytes)
        trace_report = combat_latency_report.build_report(trace_path)

        evidence_dir = run_dir / "evidence"
        evidence_dir.mkdir()
        evidence_path = evidence_dir / "commander-check.txt"
        evidence_path.write_text("synthetic evidence reference\n", encoding="ascii")
        evidence_ref = ("../outside.txt" if settings.get("unsafe_evidence_ref") else
                        "evidence/commander-check.txt")
        snapshot_dir = run_dir / "snapshots"
        snapshot_dir.mkdir()
        before_snapshot = {
            "records": {
                "selected_encounter": {
                    "status": "ok", "encounterId": scenario_id,
                    "creatures": copy.deepcopy(encounter_fixture["creatures"]),
                },
                "party_tracker.json": {
                    "status": "ok", "worldConditions": {
                        "activeCombatEncounter": scenario_id,
                    },
                },
            },
            "errors": [], "numeric_errors": [],
        }
        after_creatures = copy.deepcopy(encounter_fixture["creatures"])
        for outcome in configured_outcomes:
            outcome_batch = "enemy:r1" if outcome == "fled" else "enemy:r2"
            if outcome_batch not in {row["trace_batch_id"] for row in executed_batches}:
                continue
            actor_id = self_actor_ids[outcome]
            actor_name = next(name for (kind, name), candidate_id in run_local_actor_ids.items()
                              if kind == "enemy" and candidate_id == actor_id)
            creature = next(row for row in after_creatures
                            if row.get("name", "").casefold() == actor_name)
            creature["defeatReason"] = settings.get("defeat_reason_%s" % outcome, outcome)
            creature["status"] = settings.get("encounter_status_%s" % outcome, "defeated")
            creature["currentHitPoints"] = settings.get(
                "current_hit_points_%s" % outcome,
                settings.get("current_hit_points", 6 if outcome == "fled" else 9),
            )
            if settings.get("encounter_state_consistent") is False:
                creature["status"] = "alive"
        active_after = settings.get(
            "active_encounter_after", None if executed_batches else scenario_id
        )
        after_snapshot = {
            "records": {
                "selected_encounter": {
                    "status": "ok", "encounterId": scenario_id,
                    "creatures": after_creatures,
                },
                    "party_tracker.json": {
                        "status": "ok", "worldConditions": {
                         "activeCombatEncounter": active_after,
                    },
                },
            },
            "errors": [], "numeric_errors": [],
        }
        if settings.get("g5t_prose_character_batch"):
            for name, state in prose_character_states.items():
                after_snapshot["records"]["characters/%s.json" % name.casefold()] = state
        if settings.get("cover_state_observed") is False:
            for snapshot in (before_snapshot, after_snapshot):
                creatures = snapshot["records"]["selected_encounter"]["creatures"]
                covered_target = next(
                    row for row in creatures
                    if row.get("name") == fixtures.G5T_GOBLIN_NAMES[1]
                )
                covered_target.pop("coverFeatureId", None)
                covered_target.pop("coverType", None)
        (snapshot_dir / "before.json").write_bytes(_json_bytes(before_snapshot))
        (snapshot_dir / "after.json").write_bytes(_json_bytes(after_snapshot))
        (snapshot_dir / "after-run.json").write_bytes(_json_bytes(after_snapshot))
        covered_before = copy.deepcopy(before_snapshot)
        covered_before["observation"] = {
            "label": covered_step["label"], "input": covered_step["input"],
        }
        if settings.get("cover_effective_status") == "NOT_OBSERVED":
            covered_target = next(
                row for row in covered_before["records"]["selected_encounter"]["creatures"]
                if row.get("name") == fixtures.G5T_GOBLIN_NAMES[1]
            )
            covered_target.pop("coverFeatureId", None)
            covered_target.pop("coverType", None)
        covered_after = copy.deepcopy(covered_before)
        covered_after["observation"] = {
            "actual_backend_outputs": [{
                "type": "narration",
                "content": "Dungeon Master: Hit! (Rolled 19 vs AC %d). Attack result committed."
                % (15 if settings.get("cover_effective_status") == "NOT_OBSERVED" else 17),
            }],
        }
        (snapshot_dir / ("step-%03d-before.json" % covered_step["step"])).write_bytes(
            _json_bytes(covered_before)
        )
        (snapshot_dir / ("step-%03d-after.json" % covered_step["step"])).write_bytes(
            _json_bytes(covered_after)
        )

        check_rows = []
        omitted = set(settings.get("omit_check_ids", []))
        if "applied_choice_legality" not in omitted:
            legal_count = settings.get("g5t_legal_choice_count", 2)
            applied_count = settings.get("g5t_applied_choice_count", 2)
            legality_status = settings.get("g5t_legality_status", "PASS")
            if decision_source != "llm_tactical":
                legality_status = "NOT_APPLICABLE"
            check_rows.append({
                "id": "applied_choice_legality", "required": True,
                "status": legality_status,
                "evidence_refs": [evidence_ref],
                "observations": [
                    {"batch_id": batch["trace_batch_id"], "status": legality_status,
                      "observed": {"applied_choice_count": applied_count,
                                   "legal_applied_choice_count": legal_count},
                      "evidence_refs": [
                          "snapshots/step-%03d-after.json" % batch["index"]
                          if settings.get("missing_final_batch_after_reference") and
                           batch == next(
                               row for row in reversed(batch_steps)
                               if row.get("requires_combat_exit") is not True
                           ) else evidence_ref
                      ]}
                    for batch in executed_batches
                ],
            })
        if "commander_squad_follows_orders" not in omitted:
            followed_orders = settings.get("g5t_squad_followed_orders", True)
            issued_choice_count = settings.get("g5t_squad_issued_count", 2)
            applied_choice_count = settings.get(
                "g5t_squad_applied_count",
                0 if issued_choice_count == 0 else issued_choice_count if followed_orders else 1,
            )
            no_commander_plan = decision_source != "llm_tactical"
            squad_status = ("BLOCKED" if no_commander_plan else
                            "NOT_APPLICABLE" if issued_choice_count == 0 and not followed_orders else
                            "BLOCKED" if issued_choice_count == 0 else
                            "FAIL" if followed_orders is False else "PASS")
            check_rows.append({
                "id": "commander_squad_follows_orders", "required": True,
                "status": squad_status,
                "observations": [
                    {"batch_id": batch["trace_batch_id"], "status": squad_status,
                     "observed": {
                         "followed_orders": None if no_commander_plan else followed_orders,
                         "issued_choice_count": None if no_commander_plan else issued_choice_count,
                         "applied_choice_count": None if no_commander_plan else applied_choice_count,
                     }, "evidence_refs": [evidence_ref]}
                    for batch in executed_batches
                ],
                "evidence_refs": [evidence_ref],
            })
        if "self_preservation_removal" not in omitted:
            self_observations = []
            for index, outcome in enumerate(configured_outcomes, 1):
                outcome_batch = "enemy:r1" if outcome == "fled" else "enemy:r2"
                if outcome_batch not in {row["trace_batch_id"] for row in executed_batches}:
                    continue
                satisfied_by_exit = (removed_by_exit and outcome == exit_outcome)
                actor_removed = None if satisfied_by_exit else settings.get("actor_removed", True)
                target_removed = None if satisfied_by_exit else settings.get("target_removed", True)
                row_status = ("FAIL" if settings.get("actor_removed") is False or
                              settings.get("target_removed") is False or
                              settings.get("encounter_state_consistent") is False or
                              settings.get("defeat_reason_%s" % outcome, outcome) != outcome or
                              settings.get("encounter_status_%s" % outcome, "defeated") != "defeated"
                              else "BLOCKED" if not satisfied_by_exit and
                              (not isinstance(actor_removed, bool) or
                               not isinstance(target_removed, bool)) else "PASS")
                self_observations.append({
                    "actor_id": self_actor_ids[outcome], "outcome": outcome,
                    "batch_id": outcome_batch,
                    "defeat_reason": settings.get("defeat_reason_%s" % outcome, outcome),
                    "encounter_status": settings.get("encounter_status_%s" % outcome, "defeated"),
                    "current_hit_points": settings.get("current_hit_points", 0),
                    "actor_removed_from_later_actor_menus": actor_removed,
                    "actor_removed_from_later_target_menus": target_removed,
                    "encounter_state_consistent": settings.get("encounter_state_consistent", True),
                    "satisfied_by_exit": satisfied_by_exit,
                    "status": row_status,
                    "evidence_refs": [evidence_ref],
                })
            removal_status = (
                "FAIL" if any(row["status"] == "FAIL" for row in self_observations) else
                "PASS" if self_observations else "NOT_OBSERVED"
            )
            check_rows.append({
                "id": "self_preservation_removal", "required": True,
                "status": removal_status,
                "observed": {"observations": self_observations},
                "evidence_refs": [evidence_ref],
            })
        if "cover_changes_effective_ac" not in omitted:
            cover_values = {
                "base_ac": settings.get("cover_base_ac", 14),
                "cover_bonus": settings.get("cover_bonus", 2),
                "effective_ac": settings.get("cover_effective_ac", 16),
                "attack_effective_ac": settings.get("attack_effective_ac", 16),
            }
            check_rows.append({
                "id": "cover_changes_effective_ac", "required": True,
                "status": ("FAIL" if settings.get("cover_check_fail") else
                           settings.get("cover_effective_status", "PASS")),
                "observed": cover_values, "evidence_refs": [evidence_ref],
            })
        if "cover_expiration" not in omitted:
            expiration_values = {
                "base_ac": settings.get("post_exit_base_ac", 14),
                "effective_ac_after_exit": settings.get("post_exit_effective_ac", 14),
                "cover_inert_after_exit": settings.get("cover_inert_after_exit", True),
            }
            check_rows.append({
                "id": "cover_expiration", "required": True,
                "status": ("FAIL" if settings.get("expiration_check_fail") else
                           settings.get("cover_expiration_status", "PASS")),
                "observed": expiration_values, "evidence_refs": [evidence_ref],
            })
        checks_path = run_dir / "checks.json"
        checks_path.write_bytes(_json_bytes({"checks": check_rows, "primary_verdict": "PENDING"}))

        artifacts = {
            "trace": "trace.jsonl", "checks": "checks.json", "report": "report.json",
            "before_snapshot": "snapshots/before.json", "after_snapshot": "snapshots/after.json",
            "trace_copy": {"status": "copied", "source_records": len(trace_events),
                            "destination_records": len(trace_events)},
        }
        (run_dir / "report.json").write_bytes(_json_bytes(trace_report))

        source_hashes = {
            "core/combat/enemy_batch_orchestrator.py": "a" * 64,
            "core/combat/enemy_batch_apply.py": "b" * 64,
        }
        source_digest = hashlib.sha256(json.dumps(
            source_hashes, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        manifest = {
            "gate": "g5t", "run_id": run_id, "evidence_kind": "live-candidate",
            "live_eligible": True, "scenario": {"id": scenario_id},
            "party": {"size": party_size},
            "source": {"relevant_source_sha256": source_hashes},
            "configuration": {"actual_runtime": {"provider": "openai",
                                                     "response_model": "gpt-6-luna"}},
            "transport": {"client_source": "socketio.Client",
                          "declared_provider": "openai",
                          "resolved_response_model": "gpt-6-luna"},
            "trace_start_offset": {"status": "captured", "source_byte_offset": 0},
            "trace_span": {"status": "copied", "offset_before_bytes": 0,
                            "span_bytes": len(trace_bytes)},
            "artifacts": artifacts,
            "g5t": {
                "capture_mode": capture_mode,
                "prefetch_enabled": capture_mode == "prefetch",
                "identity": {"source_digest": source_digest},
                "fixture": fixture,
                "receipts": receipts,
            },
        }
        manifest["artifact_sha256"] = capture_evidence.hash_artifacts(run_dir, artifacts)
        (run_dir / "manifest.json").write_bytes(_json_bytes(manifest))
        return run_dir

    def _make_runs(self, party_size, run_label, settings_rows=None, capture_mode="primary"):
        settings_rows = settings_rows or [{}, {}, {}]
        return [self._make_bundle(party_size, "%s-r%d" % (run_label, index), settings,
                                  capture_mode=capture_mode)
                for index, settings in enumerate(settings_rows, 1)]

    def _evaluate(self, settings_by_party=None, prefetch_settings=None):
        settings_by_party = settings_by_party or {}
        self.capture_index += 1
        label = "case-%03d" % self.capture_index
        primary_runs = {
            party_size: self._make_runs(
                party_size, label,
                settings_by_party.get(party_size, settings_by_party.get(str(party_size))))
            for party_size in combat_latency_report.G5T_PARTY_SIZES
        }
        prefetch_runs = None
        if prefetch_settings is not None:
            prefetch_runs = {
                party_size: self._make_runs(
                    party_size, label + "-prefetch",
                    prefetch_settings.get(party_size, prefetch_settings.get(str(party_size))),
                    capture_mode="prefetch")
                for party_size in combat_latency_report.G5T_PARTY_SIZES
            }
        return combat_latency_report.evaluate_g5t_comparison(
            primary_runs, prefetch_runs_by_party=prefetch_runs, run_root=self.root)

    @staticmethod
    def _target(report, name, party_size=1, run_id=None):
        rows = [row for row in report["targets"]
                if row.get("target") == name and row.get("party_size") == party_size]
        if run_id is not None:
            rows = [row for row in rows if row.get("run_id") == run_id]
        return rows[0]

    def test_primary_report_counts_calls_writes_legality_and_three_run_medians(self):
        report = self._evaluate(settings_by_party={1: [
            {"g5t_batch_ms": 15000.0, "g5t_prefetch_requests": [
                {"request_kind": "initial"},
            ]}, {"g5t_batch_ms": 12000.0},
            {"g5t_batch_ms": 13000.0}], 4: [{}, {}, {}]})
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(report["optional_prefetch"]["status"], "NOT_RUN")
        p1 = report["party_comparisons"][0]
        self.assertEqual(p1["run_level_work_only_ms"], [15000.0, 12000.0, 13000.0])
        self.assertEqual(p1["median_batch_work_only_ms"], 13000.0)
        batch = p1["after_runs"][0]["batch_observations"][0]
        self.assertEqual(batch["provider_calls"], 2)
        self.assertEqual(batch["counted_provider_calls"], 2)
        self.assertEqual(batch["provider_calls_by_site"], {"combat_main": 2})
        self.assertNotIn("g5t_batch_provider_kind_unavailable:batch-step-001", batch["errors"])
        self.assertEqual(batch["plan_provider_calls"], 1)
        self.assertEqual(batch["narration_provider_calls"], 1)
        self.assertEqual(batch["validation_provider_calls"], 0)
        self.assertEqual(batch["raw_file_writes"], 3)
        self.assertEqual(batch["changed_character_count"], 1)
        self.assertEqual(batch["raw_file_write_limit"], 3)
        self.assertEqual(batch["applied_choice_legality_percent"], 100.0)
        self.assertEqual(len(p1["commander_behavior_references"]), 3)
        self.assertEqual(len(p1["after_runs"][0]["batch_observations"]), 7)
        self.assertEqual(len(p1["after_runs"][1]["batch_observations"]), 7)
        self.assertEqual(len(p1["after_runs"][2]["batch_observations"]), 7)
        self.assertTrue(all(len(row["batch_observations"]) == 6
                            for row in report["party_comparisons"][1]["after_runs"]))
        self.assertEqual(self._target(report, "commander_batch_provider_calls")["status"], "PASS")
        self.assertEqual(self._target(report, "commander_batch_raw_file_writes")["status"], "PASS")
        self.assertEqual(self._target(report, "commander_batch_validation_provider_calls")["status"], "PASS")
        rendered = combat_latency_report.render_g5t_comparison(report)
        self.assertIn("Optional prefetch [NOT_RUN]", rendered)
        self.assertIn("median_ms=13000.0", rendered)

    def test_exit_flow_provider_calls_are_reported_outside_the_batch_limit(self):
        exit_flow_rows = [
            {"site": "compression", "task": "compression",
             "purpose": "combat_turn_processing", "elapsed_ms": 8000.0},
            {"site": "combat_dialogue_summary", "task": "combat_summary",
             "purpose": None, "elapsed_ms": 4000.0},
            {"site": "main_dm", "task": "dm_main",
             "purpose": "primary_game_response", "elapsed_ms": 3000.0},
        ]
        report = self._evaluate(settings_by_party={1: [{
            "exit_flow_provider_rows": exit_flow_rows,
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        batch = next(row for row in run["batch_observations"]
                     if row.get("batch_id") == "enemy:r4")
        exit_flow = run["exit_flow_provider_calls"]
        self.assertEqual(batch["counted_provider_calls"], 2)
        self.assertEqual(batch["provider_calls_by_site"], {"combat_main": 2})
        self.assertEqual(self._target(
            report, "commander_batch_provider_calls", run_id=run["run_id"]
        )["status"], "PASS")
        self.assertEqual(exit_flow["total_calls"], 3)
        self.assertEqual(exit_flow["by_batch"]["enemy:r4"], {
            "combat_dialogue_summary": 1, "compression": 1, "main_dm": 1,
        })
        self.assertEqual(len(exit_flow["calls"]), 3)
        rendered = combat_latency_report.render_g5t_comparison(report)
        self.assertIn("exit_flow_calls=3", rendered)
        for site in ("compression", "combat_dialogue_summary", "main_dm"):
            self.assertIn("exit_flow enemy:r4 %s" % site, rendered)

    def test_router_compression_is_attributed_as_exit_flow_not_batch_budget(self):
        router_compression = {
            "site": "combat_compression", "task": "compression",
            "purpose": "combat_turn_processing", "call_id": "compression-call-1",
            "attempt_id": "compression-attempt-1", "attempt_number": 1,
            "provider": "openai", "requested_model": "gpt-6-luna",
            "resolved_model": "gpt-6-luna", "retry": False, "fallback": False,
            "outcome": "response", "elapsed_ms": 8000.0,
        }
        report = self._evaluate(settings_by_party={1: [{
            "exit_flow_provider_rows": [router_compression],
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        batch = next(row for row in run["batch_observations"]
                     if row.get("batch_id") == "enemy:r4")
        exit_flow = run["exit_flow_provider_calls"]
        self.assertEqual(batch["provider_calls"], 2)
        self.assertEqual(batch["counted_provider_calls"], 2)
        self.assertEqual(batch["provider_calls_by_site"], {"combat_main": 2})
        self.assertEqual(exit_flow["total_calls"], 1)
        self.assertEqual(exit_flow["by_batch"], {"enemy:r4": {"compression": 1}})
        self.assertEqual(exit_flow["calls"][0]["site"], "compression")
        self.assertEqual(exit_flow["calls"][0]["purpose"], "combat_turn_processing")
        rendered = combat_latency_report.render_g5t_comparison(report)
        self.assertIn("exit_flow enemy:r4 compression purpose=combat_turn_processing", rendered)

    def test_provider_call_and_write_limits_at_and_over_boundaries(self):
        baseline = self._evaluate()
        first_id = baseline["party_comparisons"][0]["after_runs"][0]["run_id"]
        self.assertEqual(self._target(baseline, "commander_batch_provider_calls", run_id=first_id)["status"], "PASS")
        self.assertEqual(self._target(baseline, "commander_batch_raw_file_writes", run_id=first_id)["status"], "PASS")

        over = self._evaluate(settings_by_party={1: [
            {"g5t_narration_calls": 2, "g5t_raw_writes": 4}, {}, {}]})
        run_id = over["party_comparisons"][0]["after_runs"][0]["run_id"]
        self.assertEqual(self._target(over, "commander_batch_provider_calls", run_id=run_id)["observed"], 3)
        self.assertEqual(self._target(over, "commander_batch_provider_calls", run_id=run_id)["status"], "FAIL")
        self.assertEqual(self._target(over, "commander_batch_raw_file_writes", run_id=run_id)["observed"], 4)
        self.assertEqual(self._target(over, "commander_batch_raw_file_writes", run_id=run_id)["status"], "FAIL")

    def test_multi_target_write_budget_tracks_distinct_changed_characters(self):
        report = self._evaluate(settings_by_party={1: [
            {"g5t_changed_characters": 2, "g5t_raw_writes": 4}, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        batch = run["batch_observations"][0]
        self.assertEqual(batch["changed_character_count"], 2)
        self.assertEqual(batch["raw_file_writes"], 4)
        self.assertEqual(batch["raw_file_write_limit"], 4)
        self.assertEqual(self._target(
            report, "commander_batch_raw_file_writes", run_id=run["run_id"]
        )["status"], "PASS")

        single_target = self._evaluate(settings_by_party={1: [
            {"g5t_changed_characters": 1, "g5t_raw_writes": 3}, {}, {}]})
        single_run = single_target["party_comparisons"][0]["after_runs"][0]
        single_batch = single_run["batch_observations"][0]
        self.assertEqual(single_batch["raw_file_write_limit"], 3)
        self.assertEqual(self._target(
            single_target, "commander_batch_raw_file_writes", run_id=single_run["run_id"]
        )["status"], "PASS")

    def test_plan_call_is_exactly_one_and_validation_is_zero(self):
        over = self._evaluate(settings_by_party={1: [
            {"g5t_plan_calls": 2, "g5t_validation_calls": 1}, {}, {}]})
        run_id = over["party_comparisons"][0]["after_runs"][0]["run_id"]
        self.assertEqual(self._target(over, "commander_batch_plan_provider_calls", run_id=run_id)["observed"], 2)
        self.assertEqual(self._target(over, "commander_batch_plan_provider_calls", run_id=run_id)["status"], "FAIL")
        self.assertEqual(self._target(over, "commander_batch_validation_provider_calls", run_id=run_id)["observed"], 1)
        self.assertEqual(self._target(over, "commander_batch_validation_provider_calls", run_id=run_id)["status"], "FAIL")

    def test_latency_boundary_15000_passes_and_15001_fails(self):
        at_limit = self._evaluate(settings_by_party={
            1: [{"g5t_batch_ms": 15000.0}] * 3,
            4: [{"g5t_batch_ms": 15000.0}] * 3,
        })
        self.assertEqual(self._target(at_limit, "median_batch_work_only_ms", 1)["observed"], 15000.0)
        self.assertEqual(self._target(at_limit, "median_batch_work_only_ms", 1)["status"], "PASS")
        over_limit = self._evaluate(settings_by_party={
            1: [{"g5t_batch_ms": 15001.0}] * 3,
            4: [{"g5t_batch_ms": 15001.0}] * 3,
        })
        self.assertEqual(self._target(over_limit, "median_batch_work_only_ms", 1)["observed"], 15001.0)
        self.assertEqual(self._target(over_limit, "median_batch_work_only_ms", 1)["status"], "FAIL")

    def test_applied_choice_legality_failure_is_a_gate_failure(self):
        report = self._evaluate(settings_by_party={1: [
            {"g5t_legal_choice_count": 1, "g5t_applied_choice_count": 2}, {}, {}]})
        run_id = report["party_comparisons"][0]["after_runs"][0]["run_id"]
        target = self._target(report, "applied_choice_legality_percent", run_id=run_id)
        self.assertEqual(target["observed"], 50.0)
        self.assertEqual(target["status"], "FAIL")
        batch = report["party_comparisons"][0]["after_runs"][0]["batch_observations"][0]
        self.assertEqual(batch["tactical_plan_outcome"], "accepted")

    def test_rule_tier_fallback_is_reported_as_deviation_not_commander_target_failure(self):
        report = self._evaluate(settings_by_party={1: [{
            "g5t_decision_source": "deterministic",
            "g5t_plan_calls": 0,
            "g5t_narration_calls": 0,
            "g5t_legal_choice_count": 0,
            "g5t_applied_choice_count": 0,
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        batch = run["batch_observations"][0]
        self.assertEqual(report["automated_status"], "BLOCKED")
        self.assertEqual(batch["deviation"]["kind"], "rule_tier_fallback")
        self.assertEqual(batch["provider_calls"], 0)
        self.assertEqual(batch["plan_provider_calls"], 0)
        self.assertEqual(batch["narration_provider_calls"], 0)
        self.assertEqual(batch["validation_provider_calls"], 0)
        self.assertIsNone(batch["applied_choice_legality_percent"])
        self.assertEqual(batch["applied_choice_legality_status"], "NOT_APPLICABLE")
        batch_targets = [row for row in report["targets"]
                         if row.get("run_id") == run["run_id"] and
                         row.get("work_unit_id") == batch["unit_id"]]
        self.assertEqual([row["target"] for row in batch_targets], [
            "commander_batch_raw_file_writes",
        ])

    def test_fallback_batch_without_raw_writes_is_not_applicable_not_missing(self):
        report = self._evaluate(settings_by_party={1: [{
            "g5t_decision_source": "llm_fallback", "g5t_plan_calls": 0,
            "g5t_narration_calls": 0, "g5t_raw_writes": 0,
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        batch = run["batch_observations"][0]
        self.assertEqual(batch["raw_file_writes"], None)
        self.assertEqual(batch["raw_file_write_status"], "NOT_APPLICABLE")
        self.assertNotIn("g5t_batch_raw_writes_unavailable:%s" % batch["unit_id"], batch["errors"])
        self.assertFalse(any(row.get("target") == "commander_batch_raw_file_writes" and
                             row.get("run_id") == run["run_id"] and
                             row.get("work_unit_id") == batch["unit_id"]
                             for row in report["targets"]))

    def test_cover_behavior_is_rederived_from_snapshots_and_trace(self):
        report = self._evaluate(settings_by_party={1: [{
            "cover_check_fail": True,
            "include_cover_applied_event": False,
            "cover_base_ac": 1, "cover_bonus": 99,
            "cover_effective_ac": 100, "attack_effective_ac": 100,
            "expiration_check_fail": True,
            "post_exit_base_ac": 1, "post_exit_effective_ac": 100,
            "cover_inert_after_exit": False,
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        behavior = run["behavioral_evidence"]
        self.assertEqual(behavior["cover_effective_ac"]["status"], "PASS")
        self.assertEqual(behavior["cover_effective_ac"]["base_ac"], 15)
        self.assertEqual(behavior["cover_effective_ac"]["effective_ac"], 17)
        self.assertEqual(behavior["cover_effective_ac"]["attack_effective_ac"], 17)
        self.assertEqual(behavior["cover_expiration"]["status"], "PASS")
        self.assertEqual(behavior["cover_expiration"]["base_ac"], 15)
        self.assertEqual(behavior["cover_expiration"]["effective_ac_after_exit"], 15)

        still_active = self._evaluate(settings_by_party={1: [{
            "cover_expiration_status": "PASS",
            "active_encounter_after": "g5t-commander-p1",
        }, {}, {}]})
        active_run = still_active["party_comparisons"][0]["after_runs"][0]
        expiration = active_run["behavioral_evidence"]["cover_expiration"]
        self.assertEqual(expiration["status"], "FAIL")
        self.assertFalse(expiration["cover_inert_after_exit"])
        self.assertEqual(expiration["active_combat_encounter_after_run"], "g5t-commander-p1")

    def test_squad_followthrough_aggregates_one_event_per_commander_batch(self):
        def batch(batch_id, followed=None):
            events = [] if followed is None else [{
                "event_type": "combat_observation",
                "observation": "commander_squad_follows_orders",
                "batch_id": batch_id, "followed_orders": followed,
                "issued_choice_count": 2,
                "applied_choice_count": 2 if followed else 1,
            }]
            return {"accepted_commander_batch": True, "batch_id": batch_id,
                    "_events": events}

        all_followed = combat_latency_report._g5t_squad_followthrough(
            [batch("enemy:r1", True), batch("enemy:r2", True)])
        self.assertEqual(all_followed["status"], "PASS")
        self.assertEqual(all_followed["followed_orders"], True)
        self.assertEqual(all_followed["issued_choice_count"], 4)
        self.assertEqual(all_followed["applied_choice_count"], 4)

        one_failed = combat_latency_report._g5t_squad_followthrough(
            [batch("enemy:r1", True), batch("enemy:r2", False)])
        self.assertEqual(one_failed["status"], "FAIL")
        self.assertEqual(one_failed["followed_orders"], False)

        missing = combat_latency_report._g5t_squad_followthrough(
            [batch("enemy:r1", True), batch("enemy:r2")])
        self.assertEqual(missing["status"], "BLOCKED")
        self.assertIsNone(missing["followed_orders"])

        no_commander_batches = combat_latency_report._g5t_squad_followthrough([
            {"accepted_commander_batch": False, "batch_id": "enemy:r1", "_events": []}
        ])
        self.assertEqual(no_commander_batches["status"], "BLOCKED")

        no_choices = combat_latency_report._g5t_squad_followthrough([
            {"accepted_commander_batch": True, "batch_id": "enemy:r1", "_events": [{
                "event_type": "combat_observation",
                "observation": "commander_squad_follows_orders",
                "batch_id": "enemy:r1", "followed_orders": False,
                "issued_choice_count": 0, "applied_choice_count": 0,
            }]}
        ])
        self.assertEqual(no_choices["status"], "NOT_APPLICABLE")
        self.assertIsNone(no_choices["followed_orders"])
        self.assertEqual(no_choices["issued_choice_count"], 0)
        self.assertEqual(no_choices["observations"][0]["observed"]["applicability"],
                         "no_commander_plan_contribution")

    def test_squad_followthrough_trace_failure_is_a_gate_failure(self):
        report = self._evaluate(settings_by_party={1: [{
            "g5t_squad_followed_orders": False,
            "g5t_squad_issued_count": 2,
            "g5t_squad_applied_count": 1,
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        squad = run["behavioral_evidence"]["commander_squad_follows_orders"]
        self.assertEqual(squad["status"], "FAIL")
        self.assertIs(squad["followed_orders"], False)
        target = self._target(report, "commander_squad_follows_orders", run_id=run["run_id"])
        self.assertEqual(target["observed"], 0)
        self.assertEqual(target["status"], "FAIL")

    def test_zero_issued_squad_followthrough_is_not_applicable(self):
        report = self._evaluate(settings_by_party={1: [{
            "g5t_squad_followed_orders": False,
            "g5t_squad_issued_count": 0,
            "g5t_squad_applied_count": 0,
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        squad = run["behavioral_evidence"]["commander_squad_follows_orders"]
        self.assertEqual(squad["status"], "NOT_APPLICABLE")
        self.assertIsNone(squad["followed_orders"])
        self.assertFalse(any("commander_squad_capture_check_mismatch" in error or
                             "commander_squad_followed_orders_not_pass" in error
                             for error in run["behavioral_evidence"].get("errors", [])))
        self.assertFalse(any(row.get("target") == "commander_squad_follows_orders" and
                             row.get("run_id") == run["run_id"]
                             for row in report["targets"]))

    def test_legality_not_applicable_is_distinct_from_missing_commander_evidence(self):
        deviation = self._evaluate(settings_by_party={1: [{
            "g5t_decision_source": "deterministic", "g5t_plan_calls": 0,
            "g5t_narration_calls": 0, "g5t_legal_choice_count": 0,
            "g5t_applied_choice_count": 0,
        }, {}, {}]})
        deviation_run = deviation["party_comparisons"][0]["after_runs"][0]
        deviation_batch = deviation_run["batch_observations"][0]
        self.assertEqual(deviation_batch["applied_choice_legality_status"], "NOT_APPLICABLE")
        self.assertFalse(any(row.get("target") == "applied_choice_legality_percent" and
                             row.get("run_id") == deviation_run["run_id"]
                             for row in deviation["targets"]))

        missing = self._evaluate(settings_by_party={1: [{
            "omit_check_ids": ["applied_choice_legality"],
        }, {}, {}]})
        missing_run = missing["party_comparisons"][0]["after_runs"][0]
        missing_batch = missing_run["batch_observations"][0]
        self.assertEqual(missing_batch["applied_choice_legality_status"], "BLOCKED")
        missing_target = self._target(
            missing, "applied_choice_legality_percent", run_id=missing_run["run_id"])
        self.assertEqual(missing_target["status"], "BLOCKED")

        no_applied_choices = self._evaluate(settings_by_party={1: [{
            "g5t_legality_status": "NOT_APPLICABLE",
            "g5t_legal_choice_count": 0, "g5t_applied_choice_count": 0,
            "g5t_squad_followed_orders": False,
            "g5t_squad_issued_count": 2, "g5t_squad_applied_count": 0,
        }, {}, {}]})
        no_applied_run = no_applied_choices["party_comparisons"][0]["after_runs"][0]
        no_applied_batch = no_applied_run["batch_observations"][0]
        self.assertEqual(no_applied_batch["applied_choice_legality_status"], "NOT_APPLICABLE")
        self.assertIsNone(no_applied_batch["applied_choice_legality_percent"])
        self.assertFalse(any(row.get("target") == "applied_choice_legality_percent" and
                             row.get("run_id") == no_applied_run["run_id"]
                             for row in no_applied_choices["targets"]))

    def test_missing_plan_and_behavior_evidence_blocks_without_zero_fill(self):
        report = self._evaluate(settings_by_party={1: [{
            "g5t_plan_calls": 0,
            "omit_check_ids": ["commander_squad_follows_orders"],
        }, {}, {}]})
        self.assertEqual(report["automated_status"], "BLOCKED")
        run_id = report["party_comparisons"][0]["after_runs"][0]["run_id"]
        plan_target = self._target(report, "commander_batch_plan_provider_calls", run_id=run_id)
        self.assertIsNone(plan_target["observed"])
        self.assertEqual(plan_target["status"], "BLOCKED")
        squad_target = self._target(report, "commander_squad_follows_orders", run_id=run_id)
        self.assertIsNone(squad_target["observed"])
        self.assertEqual(squad_target["status"], "BLOCKED")
        self.assertTrue(any("commander_squad_follows_orders" in reason
                            for reason in report["blocking_reasons"]))

    def test_self_preservation_report_keeps_reasons_and_actor_target_removal(self):
        report = self._evaluate()
        run = report["party_comparisons"][0]["after_runs"][0]
        observed = run["behavioral_evidence"]["self_preservation"]
        self.assertEqual([(row["actor_id"], row["outcome"], row["defeat_reason"],
                           row["encounter_status"]) for row in observed], [
                                ("actor_3", "fled", "fled", "defeated"),
                                ("actor_4", "surrendered", "surrendered", "defeated"),
                           ])
        self.assertTrue(all(row["actor_removed_from_later_actor_menus"] and
                            row["actor_removed_from_later_target_menus"] and
                            row["trace_observed"] for row in observed))

        failed = self._evaluate(settings_by_party={1: [{"target_removed": False}, {}, {}]})
        run_id = failed["party_comparisons"][0]["after_runs"][0]["run_id"]
        target = self._target(failed, "fled_actor_target_removal", run_id=run_id)
        self.assertEqual(target["observed"], 0)
        self.assertEqual(target["status"], "FAIL")

    def test_self_preservation_accepts_positive_hp_and_satisfied_by_exit(self):
        report = self._evaluate(settings_by_party={1: [{
            "g5t_self_preservation_outcomes": ["surrendered"],
            "current_hit_points": 9,
            "removed_by_exit": True,
        }, {}, {}]})
        run = report["party_comparisons"][0]["after_runs"][0]
        behavior = run["behavioral_evidence"]
        row = behavior["self_preservation"][0]
        target = self._target(
            report, "surrendered_actor_target_removal", run_id=run["run_id"]
        )
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["current_hit_points"], 9)
        self.assertTrue(row["encounter_state_consistent"])
        self.assertTrue(row["satisfied_by_exit"])
        self.assertIsNone(row["actor_removed_from_later_actor_menus"])
        self.assertIsNone(row["actor_removed_from_later_target_menus"])
        self.assertEqual(target["observed"], 1)
        self.assertEqual(target["status"], "PASS")

    def test_unobserved_self_preservation_kind_does_not_inherit_another_kind_block(self):
        report = self._evaluate(settings_by_party={4: [{
            "g5t_self_preservation_outcomes": ["fled"],
        }, {}, {}]})
        run = report["party_comparisons"][1]["after_runs"][0]
        outcomes = run["behavioral_evidence"]["self_preservation_by_outcome"]
        self.assertEqual(outcomes["fled"], "PASS")
        self.assertEqual(outcomes["surrendered"], "NOT_OBSERVED")
        target = self._target(
            report, "surrendered_actor_target_removal", party_size=4,
            run_id=run["run_id"]
        )
        self.assertEqual(target["status"], "NOT_OBSERVED")

    def test_unobserved_outcomes_are_not_blocked_per_run_but_require_cross_run_coverage(self):
        unobserved = {
            "g5t_self_preservation_outcomes": [],
            "cover_effective_status": "NOT_OBSERVED",
            "cover_expiration_status": "NOT_OBSERVED",
            "cover_state_observed": False,
        }
        report = self._evaluate(settings_by_party={1: [unobserved, unobserved, unobserved]})
        self.assertEqual(report["automated_status"], "BLOCKED")
        run = report["party_comparisons"][0]["after_runs"][0]
        behavior = run["behavioral_evidence"]
        self.assertEqual(behavior["self_preservation_by_outcome"], {
            "fled": "NOT_OBSERVED", "surrendered": "NOT_OBSERVED",
        })
        self.assertEqual(behavior["cover_effective_ac"]["status"], "NOT_OBSERVED")
        self.assertEqual(behavior["cover_expiration"]["status"], "NOT_OBSERVED")
        for target_name in (
                "fled_actor_target_removal", "surrendered_actor_target_removal",
                "cover_effective_ac", "cover_expiration"):
            self.assertEqual(self._target(report, target_name, run_id=run["run_id"])["status"],
                             "NOT_OBSERVED")
        for required_outcome in (
                "fled_actor_target_removal", "surrendered_actor_target_removal",
                "cover_effective_ac", "cover_expiration"):
            self.assertTrue(any(
                "g5t_outcome_not_observed_across_runs:%s:p1" % required_outcome == reason
                for reason in report["blocking_reasons"]
            ), required_outcome)

    def test_outcomes_observed_once_across_runs_satisfy_coverage_without_zero_fill(self):
        report = self._evaluate(settings_by_party={1: [
            {"g5t_self_preservation_outcomes": ["fled"],
             },
            {"g5t_self_preservation_outcomes": ["surrendered"],
             "cover_effective_status": "NOT_OBSERVED",
             },
            {"g5t_self_preservation_outcomes": [],
             "cover_effective_status": "NOT_OBSERVED",
             "cover_expiration_status": "NOT_OBSERVED",
             "cover_state_observed": False},
        ]})
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        p1 = report["party_comparisons"][0]
        self.assertEqual(p1["status"], "READY_FOR_PRIMARY_REVIEW")
        run1, run2, run3 = p1["after_runs"]
        self.assertEqual(run1["behavioral_evidence"]["self_preservation_by_outcome"]["fled"],
                         "PASS")
        self.assertEqual(run1["behavioral_evidence"]["self_preservation_by_outcome"]["surrendered"],
                         "NOT_OBSERVED")
        self.assertEqual(run2["behavioral_evidence"]["self_preservation_by_outcome"]["surrendered"],
                         "PASS")
        self.assertEqual(run2["behavioral_evidence"]["cover_effective_ac"]["status"],
                         "NOT_OBSERVED")
        self.assertEqual(run3["behavioral_evidence"]["self_preservation_status"],
                         "NOT_OBSERVED")

    def test_skipped_combat_ended_batch_keeps_receipt_without_blocking_run(self):
        final_batch = next(
            row for row in fixtures.build_g5t_fixture_metadata(1)["steps"]
            if row.get("unit_type") == "batch" and
            row.get("requires_combat_exit") is True
        )
        report = self._evaluate(settings_by_party={1: [
            {"skip_batch_round": final_batch["round"]}, {}, {},
        ]})
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        run = report["party_comparisons"][0]["after_runs"][0]
        self.assertEqual(len(run["batch_observations"]), 6)
        receipt_rows = json.loads(
            (pathlib.Path(run["run_dir"]) / "manifest.json").read_text(encoding="utf-8")
        )["g5t"]["receipts"]
        skipped = [row for row in receipt_rows if row.get("status") == "skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["skip_reason"], "combat_ended")
        self.assertEqual(skipped[0]["work_unit"]["round"], final_batch["round"])
        self.assertNotIn("trace_window", skipped[0])
        self.assertFalse(any(final_batch["unit_id"] in reason
                             for reason in report["blocking_reasons"]))

    def test_cover_behavior_is_rederived_without_saved_check_and_bad_reference_is_rejected(self):
        missing = self._evaluate(settings_by_party={1: [{
            "omit_check_ids": ["cover_expiration"],
        }, {}, {}]})
        self.assertEqual(missing["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        run_id = missing["party_comparisons"][0]["after_runs"][0]["run_id"]
        cover_target = self._target(missing, "cover_expiration", run_id=run_id)
        self.assertEqual(cover_target["observed"], 1)
        self.assertEqual(cover_target["status"], "PASS")

        unsafe = self._evaluate(settings_by_party={1: [{"unsafe_evidence_ref": True}, {}, {}]})
        self.assertEqual(unsafe["automated_status"], "BLOCKED")
        self.assertTrue(any("evidence_reference_invalid" in reason
                            for reason in unsafe["blocking_reasons"]))

    def test_missing_final_batch_after_snapshot_reference_uses_after_run_snapshot(self):
        report = self._evaluate(settings_by_party={4: [{
            "missing_final_batch_after_reference": True,
        }, {}, {}]})
        run = report["party_comparisons"][1]["after_runs"][0]
        last_batch = next(row for row in reversed(run["batch_observations"])
                          if row.get("accepted_commander_batch") is True)
        self.assertEqual(last_batch["legality_evidence_refs"][-1], "snapshots/after-run.json")
        self.assertFalse(any("g5t_evidence_reference_invalid" in reason
                             for reason in report["blocking_reasons"]))
        self.assertFalse(any("evidence_reference_invalid" in error
                             for error in last_batch["errors"]))

    def test_final_batch_counts_persisted_character_updates_from_after_run_snapshot(self):
        report = self._evaluate(settings_by_party={
            1: [{"g5t_prose_character_batch": "enemy:r6"}, {}, {}],
            4: [{"g5t_prose_character_batch": "enemy:r5",
                 "g5t_changed_characters": 4}, {}, {}],
        })
        p1_run = report["party_comparisons"][0]["after_runs"][0]
        p4_run = report["party_comparisons"][1]["after_runs"][0]
        p1_last = next(row for row in p1_run["batch_observations"]
                       if row.get("batch_id") == "enemy:r6")
        p4_last = next(row for row in p4_run["batch_observations"]
                       if row.get("batch_id") == "enemy:r5")
        self.assertEqual(p1_last["changed_character_count"], 1)
        self.assertEqual(p1_last["raw_file_write_limit"], 3)
        self.assertNotIn("g5t_batch_changed_character_count_unavailable:batch-step-026",
                         p1_last["errors"])
        self.assertEqual(p4_last["changed_character_count"], 4)
        self.assertEqual(p4_last["raw_file_write_limit"], 6)
        self.assertNotIn("g5t_batch_changed_character_count_unavailable:batch-step-037",
                         p4_last["errors"])

    def test_prefetch_is_optional_and_reported_separately(self):
        primary_only = self._evaluate()
        self.assertEqual(primary_only["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(primary_only["optional_prefetch"]["status"], "NOT_RUN")

        prefetch = self._evaluate(prefetch_settings={
            1: [{"g5t_prefetch_statuses": ["prefetch_hit"],
                 "g5t_prefetch_requests": [{"request_kind": "initial"}]},
                {"g5t_prefetch_statuses": ["prefetch_stale"],
                 "g5t_prefetch_requests": [
                     {"request_kind": "initial"}, {"request_kind": "replan"}]},
                {"g5t_prefetch_statuses": ["prefetch_none"],
                 "g5t_prefetch_requests": [{"request_kind": "initial"}]}],
            4: [{"g5t_prefetch_statuses": ["prefetch_hit"],
                 "g5t_prefetch_requests": [{"request_kind": "initial"}]},
                {"g5t_prefetch_statuses": ["prefetch_stale"],
                 "g5t_prefetch_requests": [
                     {"request_kind": "initial"}, {"request_kind": "replan"}]},
                {"g5t_prefetch_statuses": ["prefetch_none"],
                 "g5t_prefetch_requests": [{"request_kind": "initial"}]}],
        })
        self.assertEqual(prefetch["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(prefetch["optional_prefetch"]["status"], "OBSERVED")
        self.assertEqual(prefetch["optional_prefetch"]["outcomes"], {
            "prefetch_hit": 2, "prefetch_none": 2, "prefetch_stale": 2,
        })
        optional = prefetch["optional_prefetch"]
        self.assertEqual(optional["background_request_site"], "combat_tactical_prefetch")
        self.assertEqual(optional["background_request_count"], 8)
        self.assertEqual(optional["background_provider_call_count"], 8)
        self.assertEqual(optional["background_provider_attempt_count"], 8)
        self.assertEqual(optional["request_outcomes"], {
            "replan_submitted": 2, "submitted": 6,
        })
        p1_second_batch = optional["party_comparisons"][0]["runs"][1]["batches"][0]
        self.assertEqual(p1_second_batch["request_count"], 2)
        self.assertEqual(p1_second_batch["request_counts_by_kind"], {
            "initial": 1, "replan": 1,
        })
        self.assertEqual(p1_second_batch["provider_call_count"], 2)
        rendered = combat_latency_report.render_g5t_comparison(prefetch)
        self.assertIn("background_requests=8", rendered)
        self.assertIn("requests=2 by_kind={\"initial\": 1, \"replan\": 1}", rendered)

    def test_optional_prefetch_request_cap_fails_only_its_subgate(self):
        report = self._evaluate(prefetch_settings={
            1: [{
                "g5t_prefetch_statuses": ["prefetch_hit"],
                "g5t_prefetch_requests": [
                    {"request_kind": "initial"},
                    {"request_kind": "replan"},
                    {"request_kind": "replan"},
                ],
            }, {}, {}],
            4: [{"g5t_prefetch_statuses": ["prefetch_none"],
                 "g5t_prefetch_requests": [{"request_kind": "initial"}]}, {}, {}],
        })
        optional = report["optional_prefetch"]
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(optional["status"], "FAIL")
        self.assertEqual(len(optional["cap_violations"]), 1)
        self.assertEqual(
            {key: optional["cap_violations"][0][key]
             for key in ("party_size", "batch_id", "request_count", "limit")},
            {"party_size": 1, "batch_id": "enemy:r1", "request_count": 3, "limit": 2},
        )


if __name__ == "__main__":
    unittest.main()
