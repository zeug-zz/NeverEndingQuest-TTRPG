# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free matched G5 report and target contract tests."""

import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load evidence helpers through the existing guarded capture test harness.
from scripts import test_capture_drive as guarded_capture_import

capture_evidence = guarded_capture_import.capture_evidence
fixtures = guarded_capture_import.fixtures
from scripts import combat_latency_report


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


class CombatG5ReportTests(unittest.TestCase):
    def setUp(self):
        pathlib.Path("tmp/router-rollout/g5").mkdir(parents=True, exist_ok=True)
        self.scratch = tempfile.TemporaryDirectory(dir="tmp/router-rollout/g5", prefix="task13-report-")
        self.addCleanup(self.scratch.cleanup)
        self.root = pathlib.Path(self.scratch.name)
        pathlib.Path("tmp/router-rollout/g5r").mkdir(parents=True, exist_ok=True)
        self.g5r_scratch = tempfile.TemporaryDirectory(
            dir="tmp/router-rollout/g5r", prefix="task32-report-")
        self.addCleanup(self.g5r_scratch.cleanup)
        self.g5r_root = pathlib.Path(self.g5r_scratch.name)
        self.capture_index = 0
        self.current_capture = "direct"

    def _make_bundle(self, role, party_size, settings=None):
        settings = settings or {}
        gate = settings.get("gate", "g5")
        run_suffix = settings.get("run_suffix")
        run_id = "%s-%s-p%d%s" % (
            self.current_capture, role, party_size,
            ("-" + str(run_suffix)) if run_suffix else "")
        run_dir = (self.g5r_root if gate == "g5r" else self.root) / run_id
        run_dir.mkdir()
        profile = fixtures.build_gate_profile("g5", "combat-smoke", party_size)
        fixture = profile["fixture"]
        seed_profile = dict(profile["seed"])
        seed_id = hashlib.sha256(json.dumps(seed_profile, sort_keys=True).encode("utf-8")).hexdigest()
        source_token = "a" if role == "before" else "b"
        source_hashes = {"core/combat/turn.py": source_token * 64,
                         "core/managers/combat_manager.py": ("c" if party_size == 1 else "d") * 64}
        source_identity = {"head": ("1" if role == "before" else "2") * 40,
                           "relevant_source_sha256": source_hashes}
        g5 = capture_evidence.build_g5_capture_metadata(profile, run_id, source_identity, seed_id)
        g5["identity"].update({"provider": "openai", "model": "gpt-6-luna",
                               "configured_provider": "openai", "configured_model": "gpt-6-luna"})
        g5["configured_runtime"] = {
            "status": "ok", "configured_provider": "openai", "configured_model": "gpt-6-luna",
            "model_config_sha256": "f" * 64,
            "provenance": "sandbox model_config.py AST literals",
        }
        if settings.get("configured_provider"):
            g5["configured_runtime"]["configured_provider"] = settings["configured_provider"]
            g5["identity"]["configured_provider"] = settings["configured_provider"]
        if settings.get("configured_model"):
            g5["configured_runtime"]["configured_model"] = settings["configured_model"]
            g5["identity"]["configured_model"] = settings["configured_model"]

        action_units = fixture["work_units"]["actions"]
        batch_units = fixture["work_units"]["batches"]
        fast_action_ids = set()
        if party_size == 4 and settings.get("include_fast_path", True) and action_units:
            fast_action_ids.add(action_units[0]["unit_id"])

        step_windows = []
        cursor = 2000.0
        for step in fixture["steps"]:
            duration = (120000.0 if step["unit_type"] == "batch" else
                        1000.0 if step["unit_type"] == "control" else 10000.0)
            step_windows.append({
                "step": step["index"], "unit_type": step["unit_type"],
                "unit_id": step["unit_id"], "round": step["round"],
                "label": step["label"], "start_epoch_ms": cursor,
                "end_epoch_ms": cursor + duration,
                "start_monotonic_ms": cursor + 1000000.0,
                "end_monotonic_ms": cursor + duration + 1000000.0,
            })
            cursor += duration + 1000.0
        trace_windows = {
            "status": "captured", "clock": "epoch_ms_and_monotonic_ms",
            "startup": {"start_epoch_ms": 0.0, "end_epoch_ms": step_windows[0]["start_epoch_ms"]},
            "steps": step_windows,
            "teardown": {"start_epoch_ms": step_windows[-1]["end_epoch_ms"],
                         "end_epoch_ms": cursor},
        }
        g5["trace_windows"] = trace_windows
        windows_by_id = {row["unit_id"]: row for row in step_windows}

        trace_events = []
        provider_index = 0

        def add_provider(unit, unit_type, index, site="combat_main"):
            nonlocal provider_index
            provider_index += 1
            window = windows_by_id[unit["unit_id"]]
            trace_events.append({
                "event_type": "provider", "run_id": run_id,
                "recorded_at_ms": window["start_epoch_ms"] + 100 + index,
                "phase": "PC_PHASE" if unit_type == "action" else "ENEMY_PHASE",
                "combat_round": unit["round"],
                "action_id": "pc:r%d:%s" % (unit["round"], str(unit.get("character") or "acheron").lower()),
                "batch_id": "enemy:r%d" % unit["round"] if unit_type == "batch" else None,
                "provider": "openai", "requested_model": "gpt-6-luna",
                "resolved_model": "gpt-6-luna", "site": site, "task": site,
                "call_id": "call-%04d" % provider_index,
                "attempt_id": "attempt-%04d" % provider_index,
                "attempt_number": 1, "retry": False, "fallback": False,
                "usage_available": True, "usage_complete": True,
                "provider_reported_cost_usd": 0.001, "cost_provenance": "actual",
                "cost_complete": True, "outcome": "success", "error_type": None,
            })

        def add_write(unit, unit_type, index):
            window = windows_by_id[unit["unit_id"]]
            trace_events.append({
                "event_type": "file_operation", "run_id": run_id,
                "recorded_at_ms": window["start_epoch_ms"] + 500 + index,
                "phase": "PC_PHASE" if unit_type == "action" else "ENEMY_PHASE",
                "combat_round": unit["round"],
                "action_id": "pc:r%d:%s" % (unit["round"], str(unit.get("character") or "acheron").lower()),
                "batch_id": "enemy:r%d" % unit["round"] if unit_type == "batch" else None,
                "category": "write", "site": "character_state" if unit_type == "action" else "encounter_state",
            })

        for unit in action_units:
            unit_id = unit["unit_id"]
            is_fast = unit_id in fast_action_ids
            call_count = settings.get("action_calls_by_unit", {}).get(unit_id, 0 if is_fast else 1)
            for call_index in range(call_count):
                add_provider(unit, "action", call_index)
            writes = 1 if unit.get("character") == "Acheron" else 0
            writes += settings.get("extra_writes_by_unit", {}).get(unit_id, 0)
            for write_index in range(writes):
                add_write(unit, "action", write_index)
            if is_fast:
                window = windows_by_id[unit_id]
                trace_events.append({
                    "event_type": "decision", "run_id": run_id,
                    "recorded_at_ms": window["start_epoch_ms"] + 800,
                    "phase": "PC_PHASE", "combat_round": unit["round"],
                    "action_id": "pc:r%d:%s" % (unit["round"], str(unit.get("character") or "acheron").lower()),
                    "decision_point": "combat_command_fast_path", "decision_source": "deterministic",
                    "outcome": "hit", "provider_call_avoided": True,
                })

        for unit in batch_units:
            unit_id = unit["unit_id"]
            provider_sequence = settings.get("batch_provider_sequence")
            if isinstance(provider_sequence, list):
                validation_result_index = 0
                for call_index, site in enumerate(provider_sequence):
                    add_provider(unit, "batch", call_index * 100, site=site)
                    if site == "combat_validation":
                        results = settings.get("batch_validation_results", [])
                        if validation_result_index < len(results):
                            window = windows_by_id[unit_id]
                            trace_events.append({
                                "event_type": "combat_observation", "run_id": run_id,
                                "recorded_at_ms": window["start_epoch_ms"] + 150 + call_index * 100,
                                "observation": "combat_validation_result",
                                "validation_accepted": results[validation_result_index],
                                "combat_round": unit["round"],
                                "batch_id": "enemy:r%d" % unit["round"],
                            })
                            validation_result_index += 1
            else:
                call_count = settings.get("batch_calls", 1)
                sites = settings.get("batch_provider_sites", ["combat_main"] * call_count)
                for call_index in range(call_count):
                    add_provider(unit, "batch", call_index * 100, site=sites[call_index])
            writes = 1 + settings.get("extra_writes_by_unit", {}).get(unit_id, 0)
            if gate == "g5r":
                window = windows_by_id[unit_id]
                write_kinds = settings.get("batch_write_kinds", ["history", "character", "encounter"])
                for write_index in range(settings.get("batch_raw_writes", writes)):
                    trace_events.append({
                        "event_type": "file_operation", "run_id": run_id,
                        "recorded_at_ms": window["start_epoch_ms"] + 500 + write_index,
                        "phase": "ENEMY_PHASE", "combat_round": unit["round"],
                        "batch_id": "enemy:r%d" % unit["round"], "category": "write",
                        "site": "enemy_batch_write",
                        "target_kind": write_kinds[write_index % len(write_kinds)],
                        "target_id": "target-%s-%d" % (unit_id, write_index),
                    })
            else:
                for write_index in range(writes):
                    add_write(unit, "batch", write_index)
            if gate == "g5r":
                window = windows_by_id[unit_id]
                resolver_outcome = settings.get("resolver_outcome", "resolver_supported")
                resolver_reason = settings.get(
                    "resolver_reason", "ledger_supported" if resolver_outcome == "resolver_supported"
                    else "preflight_error")
                trace_events.append({
                    "event_type": "decision", "run_id": run_id,
                    "recorded_at_ms": window["start_epoch_ms"] + 900,
                    "decision_point": "enemy_batch_resolution",
                    "decision_source": "deterministic" if resolver_outcome == "resolver_supported" else "llm_fallback",
                    "decision_outcome": resolver_outcome, "decision_reason": resolver_reason,
                    "batch_id": "enemy:r%d" % unit["round"],
                })
                if settings.get("resolver_check_observations"):
                    trace_events[-1]["logical_turn"] = 1
                    trace_events.extend([
                        {
                            "event_type": "combat_observation", "run_id": run_id,
                            "recorded_at_ms": window["start_epoch_ms"] + 200,
                            "observation": "combat_action_batch",
                            "batch_id": "enemy:r%d" % unit["round"],
                            "logical_turn": 1, "validation_accepted": True,
                        },
                        {
                            "event_type": "combat_observation", "run_id": run_id,
                            "recorded_at_ms": window["start_epoch_ms"] + 300,
                            "observation": "combat_batch_narration_result",
                            "batch_id": "enemy:r%d" % unit["round"],
                            "logical_turn": 1, "source": "llm",
                        },
                        {
                            "event_type": "combat_observation", "run_id": run_id,
                            "recorded_at_ms": window["start_epoch_ms"] + 800,
                            "observation": "combat_logical_batch_completed",
                            "batch_id": "enemy:r%d" % unit["round"],
                            "logical_turn": 1, "accepted_batch": True,
                        },
                    ])
        legacy_unit_id = settings.get("legacy_compression_unit")
        legacy_window = windows_by_id.get(legacy_unit_id)
        if legacy_window is not None:
            trace_events.append({
                "event_type": "provider", "schema_version": 1, "run_id": run_id,
                "site": "combat_compression", "mode": "mp", "combat_round": 1,
                "phase": "PC_PHASE", "action_id": "pc:r1:vitreol",
                "elapsed_ms": 4994.07, "prompt_tokens": 2680,
                "completion_tokens": 473, "total_tokens": 3153,
                "recorded_at_ms": legacy_window["start_epoch_ms"] +
                                  settings.get("legacy_compression_offset_ms", 5000.0),
            })
        router_compression_unit = settings.get("router_compression_unit")
        router_compression_window = windows_by_id.get(router_compression_unit)
        if router_compression_window is not None:
            trace_events.append({
                "event_type": "provider", "schema_version": 1, "run_id": run_id,
                "site": "combat_compression", "mode": "mp", "combat_round": 1,
                "phase": "PC_PHASE", "action_id": "pc:r1:vitreol",
                "call_id": "compression-call-%s" % run_id,
                "attempt_id": "compression-attempt-%s" % run_id,
                "attempt_number": 1, "task": "compression", "provider": "openai",
                "requested_model": "gpt-6-luna", "resolved_model": "gpt-6-luna",
                "retry": False, "retry_tier": None, "fallback": False,
                "usage_available": True, "usage_complete": True,
                "prompt_tokens": 2680, "cached_tokens": 0, "completion_tokens": 473,
                "provider_reported_cost_usd": 0.0, "cost_usd": 0.0,
                "cost_provenance": "actual", "cost_complete": True,
                "outcome": "response", "error_type": None, "elapsed_ms": 4994.07,
                "recorded_at_ms": router_compression_window["start_epoch_ms"] +
                                  settings.get("router_compression_offset_ms", 5000.0),
            })
        for event in settings.get("decision_events", []):
            step = next((row for row in step_windows if row["unit_type"] == "action"), step_windows[0])
            trace_events.append({"event_type": "decision", "run_id": run_id,
                                 "recorded_at_ms": step["start_epoch_ms"] + 900, **event})

        trace_path = run_dir / "trace.jsonl"
        trace_path.write_bytes(b"".join(_json_bytes(event) for event in trace_events))
        positioned, position_errors = capture_evidence.parse_trace_positions(trace_path, 0)
        projection = capture_evidence.project_g5_trace(positioned, run_id, position_errors, trace_windows)
        g5["trace_attribution"] = projection
        receipt_projection = capture_evidence.project_g4_receipts(
            positioned, expected_run_id=run_id
        )
        g5["observed"] = {"steps_sent": len(fixture["steps"]),
                          "rounds": projection.get("observed_rounds"),
                          "rounds_reason": None, "enemy_batches": projection.get("observed_enemy_batches"),
                          "enemy_batches_reason": None}
        receipts = []
        for index, step in enumerate(fixture["steps"], 1):
            unit_id = step.get("unit_id")
            unit_type = step.get("unit_type")
            if unit_type == "action":
                is_fast = unit_id in fast_action_ids
                default_ms = 400.0 if is_fast else (3000.0 if role == "before" else 2000.0)
                option = "fast_action_ms" if is_fast else "action_ms"
                total_ms = settings.get(option, default_ms)
            elif unit_type == "batch":
                total_ms = settings.get("batch_ms", 3000.0 if role == "before" else 2000.0)
            else:
                total_ms = 100.0
            work_only = round(float(total_ms), 3)
            if settings.get("missing_work_only") and unit_type in ("action", "batch") and not receipts:
                work_only = None
            quiet_elapsed = settings.get("quiet_step_ms", 90000.0)
            receipt = {
                "step": index, "label": step["label"], "character": step.get("character"),
                "work_only_ms": work_only,
                "work_only_reason": "test_missing_measurement" if work_only is None else None,
                "quiet_window_elapsed_ms": quiet_elapsed,
                "quiet_window_reason": "test_quiet_missing" if quiet_elapsed is None else None,
                "timed_out": False, "cap_reached": False,
                "work_unit": {"type": unit_type, "id": unit_id, "round": step["round"]},
                "trace_window": {
                    "start_epoch_ms": step_windows[index - 1]["start_epoch_ms"],
                    "end_epoch_ms": step_windows[index - 1]["end_epoch_ms"],
                    "start_monotonic_ms": step_windows[index - 1]["start_monotonic_ms"],
                    "end_monotonic_ms": step_windows[index - 1]["end_monotonic_ms"],
                    "unit_type": unit_type, "unit_id": unit_id,
                    "round": step["round"], "step": index,
                },
            }
            receipts.append(receipt)
        g5["receipts"] = receipts

        trace_report = combat_latency_report.build_report(trace_path)
        artifact_names = {
            "transcript": "transcript.log", "server_log": "server.log", "trace": "trace.jsonl",
            "report": "report.json", "before_snapshot": "snapshots/before-run.json",
            "after_snapshot": "snapshots/after-run.json", "checks": "checks.json",
        }
        (run_dir / "transcript.log").write_text(
            "".join("[driver] step=%d start input\n[driver] step=%d done completed\n" % (i, i)
                    for i in range(1, len(fixture["steps"]) + 1)), encoding="ascii")
        (run_dir / "server.log").write_text("provider-free G5 fixture server log\n", encoding="ascii")
        (run_dir / "report.json").write_bytes(_json_bytes(trace_report))
        (run_dir / "snapshots").mkdir()
        snapshot = {"records": {}, "errors": [], "numeric_errors": []}
        for key in ("before_snapshot", "after_snapshot"):
            (run_dir / artifact_names[key]).write_bytes(_json_bytes(snapshot))
        damage = settings.get("changed_pc_targets", {})
        if not isinstance(damage, dict):
            damage = {str(name): 1 for name in damage} if isinstance(damage, list) else {}
        roster = ["Acheron"] if party_size == 1 else list(fixtures.PC_NAMES)

        def step_snapshot(step, edge):
            if step.get("unit_type") != "batch":
                return snapshot
            records = {}
            projected_characters = {}
            for character_name in roster:
                amount = damage.get(character_name, 0)
                hp = 20 - amount if edge == "after" else 20
                target = "characters/%s.json" % combat_latency_report._g5r_canonical_name(character_name)
                character = {"name": character_name, "character_type": "player", "hitPoints": hp}
                records[target] = dict(character)
                projected_characters[target] = dict(character)
            return {"records": records, "mechanical_projection": {"characters": projected_characters},
                    "errors": [], "numeric_errors": []}

        step_refs = []
        for index in range(1, len(fixture["steps"]) + 1):
            step = fixture["steps"][index - 1]
            for edge in ("before", "after"):
                reference = "snapshots/step-%03d-%s.json" % (index, edge)
                (run_dir / reference).write_bytes(_json_bytes(step_snapshot(step, edge)))
                step_refs.append(reference)
        (run_dir / "checks.json").write_bytes(_json_bytes({
            "checks": [{"id": check_id, "required": True,
                        "status": "FAIL" if check_id in settings.get("failed_check_ids", []) else "PASS"}
                       for check_id in ["g5_fixture_state", *settings.get("failed_check_ids", [])]],
            "primary_verdict": "PENDING",
        }))

        profile_contract = {key: profile.get(key) for key in
                            ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
        profile_contract["gate"] = gate
        scenario_hash = hashlib.sha256(json.dumps(profile_contract, sort_keys=True).encode("utf-8")).hexdigest()
        transport = {"url": "http://127.0.0.1:8360", "kind": "socket.io + local REST",
                     "client_source": "socketio.Client", "declared_provider": "openai",
                     "requested_model": "gpt-6-luna", "resolved_response_model": "gpt-6-luna"}
        configuration = {
            "operator_declared": {"provider": "openai", "requested_model": "gpt-6-luna"},
            "actual_runtime": {"status": "PASS", "provider": "openai", "response_model": "gpt-6-luna",
                               "receipts": receipt_projection.get("receipts", [])},
        }
        artifacts = {
            **artifact_names, "step_snapshots": step_refs, "missing_step_snapshots": [],
            "required_evidence_status": "ok",
            "trace_copy": {"status": "copied", "source_records": len(trace_events),
                           "destination_records": len(trace_events)},
        }
        source_digest = hashlib.sha256(json.dumps(
            source_hashes, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        manifest = {
            "evidence_kind": "live-candidate", "live_eligible": True, "gate": gate,
            "run_id": run_id,
            "scenario": {"id": "combat-smoke", "version": "g5-capture-v1", "sha256": scenario_hash,
                         "branch": None, "phase": None, "profile_contract": profile_contract},
            "party": {"size": party_size,
                      "roster": ["Acheron"] if party_size == 1 else list(fixtures.PC_NAMES)},
            "seed": {"seed_id": seed_id, "seed_profile_sha256": seed_id,
                     "profile_seed": seed_profile},
            "source": {"head": source_identity["head"], "relevant_source_sha256": source_hashes},
            "configuration": configuration, "transport": transport,
            "counts": {"steps_sent": len(fixture["steps"]), "timeouts": 0,
                       "step_caps_reached": 0, "idle_settle_caps_reached": 0,
                       "blocked_step_attempts": 0, "blocked_control_attempts": 0},
            "trace_start_offset": {"status": "captured", "source_byte_offset": 0,
                                    "prefix_sha256": "e" * 64},
            "trace_span": {"status": "copied", "offset_before_bytes": 0,
                           "span_bytes": trace_path.stat().st_size},
            "artifacts": artifacts, "g5": g5,
            "receipt_projection": receipt_projection,
        }
        manifest["artifact_sha256"] = capture_evidence.hash_artifacts(run_dir, artifacts)
        (run_dir / "manifest.json").write_bytes(_json_bytes(manifest))
        return run_dir

    def _capture_set(self, before_settings=None, after_settings=None):
        self.capture_index += 1
        self.current_capture = "case%d" % self.capture_index
        before_settings = before_settings or {}
        after_settings = after_settings or {}
        before = [self._make_bundle("before", party, before_settings.get(party, {})) for party in (1, 4)]
        after = [self._make_bundle("after", party, after_settings.get(party, {})) for party in (1, 4)]
        return before, after

    def _evaluate(self, before_settings=None, after_settings=None):
        before, after = self._capture_set(before_settings, after_settings)
        return combat_latency_report.evaluate_g5_comparison(before, after)

    def _make_g5r_runs(self, party_size, settings_rows=None):
        settings_rows = settings_rows or [{}, {}, {}]
        self.capture_index += 1
        self.current_capture = "g5r%d" % self.capture_index
        return [self._make_bundle("after", party_size, {
            "gate": "g5r", "run_suffix": "run%d" % index,
            "batch_raw_writes": 3, **settings,
        }) for index, settings in enumerate(settings_rows, 1)]

    def _evaluate_g5r(self, after_settings=None, before_settings=None):
        before, _ = self._capture_set(before_settings=before_settings)
        after_settings = after_settings or {}
        after_runs = {party: self._make_g5r_runs(party, after_settings.get(party))
                      for party in (1, 4)}
        return combat_latency_report.evaluate_g5r_comparison(before, after_runs)

    def _g5r_comparison_sets(self):
        before, _ = self._capture_set(before_settings={
            1: {"extra_writes_by_unit": {"batch-step-003": 2}},
            4: {"extra_writes_by_unit": {"batch-step-010": 2}},
        })
        after_runs = {party: self._make_g5r_runs(party) for party in (1, 4)}
        return before, after_runs

    @staticmethod
    def _remove_saved_receipt_run_ids(run_dir):
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        receipt_lists = (
            manifest["receipt_projection"]["receipts"],
            manifest["configuration"]["actual_runtime"]["receipts"],
        )
        for rows in receipt_lists:
            for row in rows:
                row.pop("run_id", None)
        manifest_path.write_bytes(_json_bytes(manifest))
        return manifest

    def test_g5r_accepts_only_mirrored_legacy_receipts_without_run_id(self):
        before, after_runs = self._g5r_comparison_sets()
        all_runs = before + [run for party in (1, 4) for run in after_runs[party]]
        for run_dir in all_runs:
            self._remove_saved_receipt_run_ids(run_dir)

        report = combat_latency_report.evaluate_g5r_comparison(before, after_runs)
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW",
                         {"blocking_reasons": report["blocking_reasons"],
                          "target_misses": report["target_misses"]})
        self.assertFalse(any("saved_receipt_projection_mismatch" in reason
                             for reason in report["blocking_reasons"]))

    def test_standalone_g5_does_not_accept_legacy_receipt_projection_shape(self):
        before, after = self._capture_set()
        for run_dir in before + after:
            self._remove_saved_receipt_run_ids(run_dir)

        report = combat_latency_report.evaluate_g5_comparison(before, after)
        self.assertNotEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertTrue(any("saved_receipt_projection_mismatch" in reason
                            for reason in report["blocking_reasons"]))

    def test_g5r_new_saved_receipts_require_matching_run_id(self):
        for mutation in ("missing", "mismatched"):
            with self.subTest(mutation=mutation):
                before, after_runs = self._g5r_comparison_sets()
                run_dir = after_runs[1][0]
                manifest_path = run_dir / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="ascii"))
                receipt = manifest["receipt_projection"]["receipts"][0]
                if mutation == "missing":
                    receipt.pop("run_id")
                else:
                    receipt["run_id"] = "foreign-g5r-run"
                manifest_path.write_bytes(_json_bytes(manifest))

                report = combat_latency_report.evaluate_g5r_comparison(before, after_runs)
                self.assertNotEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
                self.assertTrue(any("saved_receipt_projection_mismatch" in reason
                                    for reason in report["blocking_reasons"]))

    def test_g5r_legacy_receipt_comparison_does_not_hide_other_field_differences(self):
        before, after_runs = self._g5r_comparison_sets()
        for run_dir in before + [run for party in (1, 4) for run in after_runs[party]]:
            self._remove_saved_receipt_run_ids(run_dir)
        run_dir = after_runs[1][0]
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        manifest["receipt_projection"]["receipts"][0]["retry"] = True
        manifest["configuration"]["actual_runtime"]["receipts"][0]["retry"] = True
        manifest_path.write_bytes(_json_bytes(manifest))

        report = combat_latency_report.evaluate_g5r_comparison(before, after_runs)
        self.assertNotEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertTrue(any("saved_receipt_projection_mismatch" in reason
                            for reason in report["blocking_reasons"]))

    def test_g5r_current_trace_receipts_still_require_the_bundle_run_id(self):
        for mutation in ("missing", "mismatched"):
            with self.subTest(mutation=mutation):
                before, after_runs = self._g5r_comparison_sets()
                run_dir = after_runs[1][0]
                manifest_path = run_dir / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="ascii"))
                trace_path = run_dir / manifest["artifacts"]["trace"]
                events = [json.loads(line) for line in trace_path.read_text(
                    encoding="ascii").splitlines()]
                event = next(row for row in events if row.get("event_type") == "provider")
                if mutation == "missing":
                    event.pop("run_id")
                else:
                    event["run_id"] = "x" * len(manifest["run_id"])
                trace_path.write_bytes(b"".join(_json_bytes(row) for row in events))
                manifest["trace_span"]["span_bytes"] = trace_path.stat().st_size
                manifest["artifact_sha256"] = capture_evidence.hash_artifacts(
                    run_dir, manifest["artifacts"]
                )
                manifest_path.write_bytes(_json_bytes(manifest))

                report = combat_latency_report.evaluate_g5r_comparison(before, after_runs)
                self.assertNotEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
                self.assertTrue(any("trace_attribution:" in reason
                                    for reason in report["blocking_reasons"]))

    def test_matched_bundles_meet_targets_and_preserve_both_timing_measures(self):
        report = self._evaluate()
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(report["primary_verdict"], "PENDING")
        self.assertEqual([row["party_size"] for row in report["party_comparisons"]], [1, 4])
        self.assertTrue(all(row["identity_match"]["matched"] for row in report["party_comparisons"]))
        self.assertTrue(all(row["identity_match"]["source_digest_changed"] for row in report["party_comparisons"]))
        timing = report["p4_complete_round_timing"]
        self.assertTrue(timing["work_only_is_gating_metric"])
        self.assertFalse(timing["quiet_window_is_gating_metric"])
        self.assertGreater(timing["before_quiet_window_elapsed_ms"], timing["before_work_only_ms"])
        self.assertTrue(any(row["target"] == "p4_round_latency_improvement" and row["status"] == "PASS"
                            for row in report["targets"]))

    def test_legacy_compression_counts_toward_its_window_and_remains_separate(self):
        report = self._evaluate(after_settings={4: {
            "legacy_compression_unit": "batch-step-010",
            "legacy_compression_offset_ms": 4999.934,
        }})
        p4 = next(row for row in report["party_comparisons"] if row["party_size"] == 4)
        batch = next(row for row in p4["after"]["batches"] if row["id"] == "batch-step-010")
        self.assertEqual(batch["provider_calls"], 2)
        self.assertEqual(batch["legacy_provider_calls"], 1)
        self.assertEqual(batch["legacy_provider_elapsed_ms"], 4994.07)
        self.assertEqual(p4["after"]["legacy_provider_observations"], 1)
        self.assertEqual(p4["after"]["legacy_provider_elapsed_ms"], 4994.07)
        round_one = next(row for row in p4["after"]["rounds"] if row["round"] == 1)
        self.assertEqual(round_one["provider_calls"], 9)
        self.assertEqual(round_one["legacy_provider_calls"], 1)
        self.assertEqual(round_one["legacy_provider_elapsed_ms"], 4994.07)
        batch_target = next(row for row in report["targets"]
                            if row.get("target") == "enemy_batch_provider_calls" and
                            row.get("party_size") == 4 and
                            row.get("work_unit_id") == "batch-step-010")
        self.assertEqual(batch_target["observed"], 2)
        self.assertEqual(batch_target["status"], "FAIL")
        rendered = combat_latency_report.render_g5_comparison(report)
        self.assertIn("P4 legacy compression provider observations: 1", rendered)
        self.assertIn("batch batch-step-010: 1 legacy provider call(s)", rendered)

    def test_router_compression_keeps_g5_batch_provider_counts(self):
        legacy = self._evaluate(after_settings={4: {
            "legacy_compression_unit": "batch-step-010",
            "legacy_compression_offset_ms": 4999.934,
        }})
        router = self._evaluate(after_settings={4: {
            "router_compression_unit": "batch-step-010",
            "router_compression_offset_ms": 4999.934,
        }})
        legacy_p4 = next(row for row in legacy["party_comparisons"]
                         if row["party_size"] == 4)
        router_p4 = next(row for row in router["party_comparisons"]
                         if row["party_size"] == 4)
        legacy_batch = next(row for row in legacy_p4["after"]["batches"]
                            if row["id"] == "batch-step-010")
        router_batch = next(row for row in router_p4["after"]["batches"]
                            if row["id"] == "batch-step-010")
        self.assertEqual(legacy_batch["provider_calls"], router_batch["provider_calls"])
        self.assertEqual(router_batch["provider_calls"], 2)
        self.assertEqual(legacy_batch["legacy_provider_calls"], 1)
        self.assertEqual(router_batch["legacy_provider_calls"], 0)
        self.assertEqual(legacy_p4["after"]["legacy_provider_observations"], 1)
        self.assertEqual(router_p4["after"]["legacy_provider_observations"], 0)
        legacy_target = next(row for row in legacy["targets"]
                             if row.get("target") == "enemy_batch_provider_calls" and
                             row.get("party_size") == 4 and
                             row.get("work_unit_id") == "batch-step-010")
        router_target = next(row for row in router["targets"]
                             if row.get("target") == "enemy_batch_provider_calls" and
                             row.get("party_size") == 4 and
                             row.get("work_unit_id") == "batch-step-010")
        self.assertEqual(legacy_target["observed"], router_target["observed"])
        self.assertEqual(legacy_target["status"], router_target["status"])

    def test_p1_latency_allows_nine_percent_provider_variance(self):
        report = self._evaluate(before_settings={1: {"action_ms": 7000.0}},
                                after_settings={1: {"action_ms": 7630.0}})
        target = next(row for row in report["targets"] if row["target"] == "p1_no_latency_regression")
        self.assertEqual(combat_latency_report.G5_P1_LATENCY_REGRESSION_FACTOR, 1.10)
        self.assertEqual(report["fixed_targets"]["p1_no_latency_regression"]["threshold"], 1.10)
        self.assertEqual(target["observed"], 7.63)
        self.assertEqual(target["before"], 7.0)
        self.assertEqual(target["before_factor"], 1.10)
        self.assertEqual(target["operator"], "<= before*1.10")
        self.assertEqual(target["threshold"], 7.7)
        self.assertEqual(target["status"], "PASS")
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        table = combat_latency_report.render_g5_comparison(report)
        self.assertIn("p1_no_latency_regression | P1 | 7.63 | <= before*1.10 7.7 | PASS", table)

    def test_p1_latency_fails_at_eleven_percent_provider_variance(self):
        report = self._evaluate(before_settings={1: {"action_ms": 7000.0}},
                                after_settings={1: {"action_ms": 7770.0}})
        target = next(row for row in report["targets"] if row["target"] == "p1_no_latency_regression")
        self.assertEqual(target["observed"], 7.77)
        self.assertEqual(target["threshold"], 7.7)
        self.assertEqual(target["operator"], "<= before*1.10")
        self.assertEqual(target["status"], "FAIL")
        self.assertEqual(report["automated_status"], "FAIL")
        self.assertIn("p1_no_latency_regression", {
            row["target"] for row in report["target_misses"]
        })

    def test_g5r_p1_latency_uses_all_fast_action_p50s(self):
        report = self._evaluate_g5r(
            before_settings={1: {"action_ms": 7000.0}},
            after_settings={1: [
                {"action_ms": 7400.0}, {"action_ms": 7600.0}, {"action_ms": 7800.0},
            ]},
        )
        target = next(row for row in report["targets"]
                      if row["target"] == "p1_no_latency_regression")
        self.assertIsInstance(target["observed"], (int, float))
        self.assertEqual(target["after_run_p50_ms"], [7400.0, 7600.0, 7800.0])
        self.assertEqual(target["observed"], 7.6)
        self.assertEqual(target["status"], "PASS")

    def test_each_measurable_fixed_target_miss_is_named_as_fail(self):
        cases = [
            ("pc_action_llm_p50_seconds", {}, {1: {"action_ms": 9000.0}}),
            ("pc_action_fast_p50_seconds", {}, {4: {"fast_action_ms": 1200.0}}),
            ("enemy_batch_p50_seconds", {}, {1: {"batch_ms": 16000.0}}),
            ("pc_action_llm_provider_calls", {}, {1: {"action_calls_by_unit": {"action-step-001": 3}}}),
            ("enemy_batch_provider_calls", {}, {1: {"batch_calls": 0}}),
            ("file_writes_per_combat_turn", {}, {1: {"extra_writes_by_unit": {"action-step-001": 3}}}),
            ("p4_round_latency_improvement", {4: {"action_ms": 1000.0, "batch_ms": 1000.0}},
             {4: {"action_ms": 1800.0, "batch_ms": 1800.0}}),
            ("p1_no_latency_regression", {1: {"action_ms": 2000.0}}, {1: {"action_ms": 2500.0}}),
            ("p1_no_provider_call_regression", {},
             {1: {"action_calls_by_unit": {"action-step-001": 2}}}),
            ("p1_no_file_write_regression", {},
             {1: {"extra_writes_by_unit": {"action-step-001": 1}}}),
            ("phase_provider_calls_no_increase", {},
             {4: {"action_calls_by_unit": {"action-step-002": 1}}}),
            ("phase_file_writes_no_increase", {},
             {4: {"extra_writes_by_unit": {"action-step-002": 1}}}),
        ]
        for expected_target, before_settings, after_settings in cases:
            with self.subTest(target=expected_target):
                report = self._evaluate(before_settings=before_settings, after_settings=after_settings)
                self.assertEqual(report["automated_status"], "FAIL")
                self.assertIn(expected_target, {row["target"] for row in report["target_misses"]})
                if expected_target in ("p1_no_provider_call_regression", "p1_no_file_write_regression"):
                    target = next(row for row in report["targets"]
                                  if row["target"] == expected_target)
                    self.assertEqual(target["operator"], "<= before")
                    self.assertEqual(target["threshold"], target["before"])

    def test_missing_before_role_is_blocked_and_not_replaced_by_g1(self):
        before, after = self._capture_set()
        report = combat_latency_report.evaluate_g5_comparison([before[0]], after)
        self.assertEqual(report["automated_status"], "BLOCKED")
        self.assertIn("before_role_requires_exactly_two_bundles", report["blocking_reasons"])

        g1_root = pathlib.Path("tmp/router-rollout/g1/task13-historical-only")
        report = combat_latency_report.evaluate_g5_comparison([g1_root, before[1]], after)
        self.assertEqual(report["automated_status"], "BLOCKED")
        self.assertTrue(any("unsafe_g5_run_directory" in reason for reason in report["blocking_reasons"]))
        self.assertFalse(report["g1_historical_context"]["used_as_baseline"])

    def test_model_and_script_hash_mismatches_block_comparison(self):
        before, after = self._capture_set()
        manifest_path = after[0] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        manifest["g5"]["configured_runtime"]["configured_model"] = "other-model"
        manifest["g5"]["identity"]["configured_model"] = "other-model"
        manifest_path.write_bytes(_json_bytes(manifest))
        result = combat_latency_report.evaluate_g5_comparison(before, after)
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertTrue(any("configured_model_mismatch" in reason for reason in result["blocking_reasons"]))

        before, after = self._capture_set()
        manifest_path = after[1] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        manifest["g5"]["fixture"]["steps_sha256"] = "f" * 64
        manifest_path.write_bytes(_json_bytes(manifest))
        result = combat_latency_report.evaluate_g5_comparison(before, after)
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertTrue(any("fixed_fixture_identity_mismatch" in reason for reason in result["blocking_reasons"]))

    def test_duplicate_before_role_blocks_comparison(self):
        before, after = self._capture_set()
        report = combat_latency_report.evaluate_g5_comparison([before[0], before[0]], after)
        self.assertEqual(report["automated_status"], "BLOCKED")
        self.assertIn("duplicate_bundle_path_or_role", report["blocking_reasons"])
        self.assertTrue(any("p1_before_role_missing_or_duplicate" in reason
                            for reason in report["blocking_reasons"]))

    def test_missing_work_only_measurement_is_unavailable_and_blocks(self):
        report = self._evaluate(after_settings={1: {"missing_work_only": True}})
        self.assertEqual(report["automated_status"], "BLOCKED")
        self.assertTrue(any("work_only_timing_unavailable" in reason for reason in report["blocking_reasons"]))
        p1 = next(row for row in report["party_comparisons"] if row["party_size"] == 1)
        self.assertIsNone(p1["after"]["pc_action_p50_work_only_seconds"]["llm"])

    def test_missing_quiet_window_measurement_is_unavailable_and_blocks(self):
        report = self._evaluate(after_settings={1: {"quiet_step_ms": None}})
        self.assertEqual(report["automated_status"], "BLOCKED")
        self.assertTrue(any("quiet_window_timing_unavailable" in reason
                            for reason in report["blocking_reasons"]))
        p1 = next(row for row in report["party_comparisons"] if row["party_size"] == 1)
        self.assertIsNone(p1["after"]["pc_action_p50_quiet_window_seconds"]["llm"])

    def test_decision_rates_are_unavailable_not_zero_when_events_are_absent(self):
        report = self._evaluate(before_settings={4: {"include_fast_path": False}},
                                after_settings={4: {"include_fast_path": False}})
        p4 = next(row for row in report["party_comparisons"] if row["party_size"] == 4)
        rates = p4["rates"]["after"]
        validation = rates["validation_skip"]
        self.assertIsNone(validation["skipped"]["count"])
        self.assertIsNone(validation["skipped"]["rate"])
        self.assertEqual(validation["reason"], "no_validation_routing_events")
        for outcome in rates["nl_fast_path"]["outcomes"].values():
            self.assertIsNone(outcome["count"])
            self.assertIsNone(outcome["rate"])
            self.assertEqual(outcome["reason"], "no_nl_decision_events")

    def test_validation_and_nl_outcomes_report_observed_rates_and_reasons(self):
        events = [
            {"decision_point": "combat_validation_routing", "skip_llm_validation": True,
             "reason": "safe_deterministic_action"},
            {"decision_point": "combat_validation_routing", "skip_llm_validation": False,
             "reason": "explicit_bookkeeping"},
            {"decision_point": "pc_phase_parser", "outcome": "hit", "decision_source": "deterministic"},
            {"decision_point": "pc_phase_parser", "outcome": "miss", "decision_source": "llm_fallback"},
            {"decision_point": "pc_phase_parser", "outcome": "false_positive", "decision_source": "llm_fallback"},
            {"decision_point": "pc_phase_parser", "outcome": "unavailable", "decision_source": "llm_fallback"},
        ]
        report = self._evaluate(after_settings={4: {"include_fast_path": False,
                                                     "decision_events": events}})
        p4 = next(row for row in report["party_comparisons"] if row["party_size"] == 4)
        rates = p4["rates"]["after"]
        self.assertEqual(rates["validation_skip"]["skipped"]["rate"], 0.5)
        self.assertEqual(rates["validation_skip"]["skip_reasons"], {"safe_deterministic_action": 1})
        self.assertEqual(rates["nl_fast_path"]["outcomes"]["hit"]["rate"], 0.25)
        self.assertEqual(rates["nl_fast_path"]["outcomes"]["miss"]["rate"], 0.25)
        self.assertEqual(rates["nl_fast_path"]["outcomes"]["false_positive"]["rate"], 0.25)
        self.assertEqual(rates["nl_fast_path"]["outcomes"]["unavailable"]["rate"], 0.25)
        self.assertEqual(rates["nl_fast_path"]["outcomes"]["llm_fallback"]["rate"], 0.75)

    def test_fallback_is_reported_separately_from_nl_outcomes(self):
        events = [{"decision_point": "pc_phase_parser", "outcome": "miss",
                   "decision_source": "llm_fallback", "llm_fallback": True}]
        report = self._evaluate(after_settings={4: {"decision_events": events}})
        p4 = next(row for row in report["party_comparisons"] if row["party_size"] == 4)
        outcomes = p4["rates"]["after"]["nl_fast_path"]["outcomes"]
        self.assertEqual(outcomes["miss"]["count"], 1)
        self.assertEqual(outcomes["llm_fallback"]["count"], 1)
        self.assertIsNone(outcomes["false_positive"]["count"])
        self.assertEqual(outcomes["false_positive"]["reason"], "outcome_not_observed")

    def test_required_check_failure_is_named_and_receipt_projection_is_persisted(self):
        run_dir = self._make_bundle(
            "after", 1, {"failed_check_ids": ["final_response_validation_truth"]}
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="ascii"))
        self.assertEqual(manifest["g5"]["trace_windows"]["status"], "captured")
        self.assertEqual(manifest["g5"]["identity"]["configured_provider"], "openai")
        self.assertEqual(manifest["g5"]["identity"]["configured_model"], "gpt-6-luna")
        self.assertIn("receipts", manifest["receipt_projection"])
        loaded = combat_latency_report._g5_load_bundle(run_dir)
        self.assertIn("required_checks_not_passed:final_response_validation_truth", loaded["errors"])

    def test_g5r_offline_loader_recomputes_resolver_checks_from_trace(self):
        run_dir = self._make_bundle("after", 1, {
            "gate": "g5r",
            "resolver_check_observations": True,
            "failed_check_ids": [
                "final_response_validation_truth", "accepted_logical_batch_once",
            ],
        })
        loaded = combat_latency_report._g5_load_bundle(
            run_dir, run_root=self.g5r_root, expected_gate="g5r"
        )
        self.assertEqual(loaded["checks_source"], "resolver_trace_recomputed")
        check_statuses = {row["id"]: row["status"] for row in loaded["checks"]}
        self.assertEqual(check_statuses["final_response_validation_truth"], "PASS")
        self.assertEqual(check_statuses["accepted_logical_batch_once"], "PASS")
        self.assertNotIn(
            "required_checks_not_passed:final_response_validation_truth", loaded["errors"]
        )
        self.assertNotIn(
            "required_checks_not_passed:accepted_logical_batch_once", loaded["errors"]
        )

    def test_g5r_requires_three_runs_and_reports_median_with_raw_per_run_values(self):
        report = self._evaluate_g5r(before_settings={
            1: {"extra_writes_by_unit": {"batch-step-003": 2}},
            4: {"action_ms": 7000.0,
                "extra_writes_by_unit": {"batch-step-010": 2}},
        }, after_settings={
            1: [{"batch_ms": 10000.0}, {"batch_ms": 15000.0}, {"batch_ms": 20000.0}],
            4: [{"batch_ms": 13000.0}, {"batch_ms": 14000.0}, {"batch_ms": 15000.0}],
        })
        self.assertEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        for party_size, expected_median, expected_runs in (
                (1, 15000.0, [10000.0, 15000.0, 20000.0]),
                (4, 14000.0, [13000.0, 14000.0, 15000.0])):
            party = next(row for row in report["party_comparisons"] if row["party_size"] == party_size)
            self.assertEqual(party["medians"]["enemy_batch_work_only_ms"], expected_median)
            self.assertEqual(len(party["after_runs"]), 3)
            self.assertEqual([row["batch"]["work_only_ms"] for row in party["after_runs"]],
                             expected_runs)
            self.assertTrue(all(row["batch"]["provider_calls"] == 1 for row in party["after_runs"]))
            self.assertTrue(all(row["batch"]["raw_file_writes"] == 3 for row in party["after_runs"]))
        p1_target = next(row for row in report["targets"]
                         if row["target"] == "enemy_batch_median_work_only_ms" and row["party_size"] == 1)
        self.assertEqual(p1_target["status"], "PASS")
        incomplete = combat_latency_report.evaluate_g5r_comparison(
            self._capture_set()[0], {1: self._make_g5r_runs(1)[:2], 4: self._make_g5r_runs(4)})
        self.assertEqual(incomplete["automated_status"], "BLOCKED")
        self.assertIn("p1_after_role_requires_exactly_three_bundles", incomplete["blocking_reasons"])

    def test_g5r_latency_median_boundary_is_15000_ms(self):
        pass_report = self._evaluate_g5r(after_settings={
            1: [{"batch_ms": 15000.0}] * 3,
            4: [{"batch_ms": 15000.0}] * 3,
        })
        p1_pass = next(row for row in pass_report["targets"]
                       if row["target"] == "enemy_batch_median_work_only_ms" and row["party_size"] == 1)
        self.assertEqual(p1_pass["status"], "PASS")
        fail_report = self._evaluate_g5r(after_settings={
            1: [{"batch_ms": 15001.0}] * 3,
            4: [{"batch_ms": 15001.0}] * 3,
        })
        p1_fail = next(row for row in fail_report["targets"]
                       if row["target"] == "enemy_batch_median_work_only_ms" and row["party_size"] == 1)
        self.assertEqual(p1_fail["status"], "FAIL")
        self.assertEqual(p1_fail["observed"], 15001.0)

    def test_g5r_raw_provider_and_write_targets_are_not_normalized(self):
        report = self._evaluate_g5r(after_settings={
            1: [{"batch_raw_writes": 3}, {"batch_raw_writes": 4},
                {"batch_provider_sequence": ["combat_main", "combat_validation"],
                 "batch_validation_results": [True]}],
            4: [{}, {}, {}],
        })
        self.assertEqual(report["automated_status"], "FAIL")
        p1 = next(row for row in report["party_comparisons"] if row["party_size"] == 1)
        self.assertEqual([row["batch"]["raw_file_writes"] for row in p1["after_runs"]], [3, 4, 3])
        write_targets = [row for row in report["targets"]
                         if row["target"] == "enemy_batch_raw_file_writes" and row["party_size"] == 1]
        self.assertEqual([row["status"] for row in write_targets], ["PASS", "FAIL", "PASS"])
        call_targets = [row for row in report["targets"]
                        if row["target"] == "enemy_batch_provider_calls" and row["party_size"] == 1]
        self.assertEqual([row["status"] for row in call_targets], ["PASS", "PASS", "FAIL"])
        validation_targets = [row for row in report["targets"]
                              if row["target"] == "enemy_batch_validation_provider_calls" and
                              row["party_size"] == 1]
        self.assertEqual([row["status"] for row in validation_targets], ["PASS", "PASS", "FAIL"])

    def test_g5r_retry_and_changed_pc_normalization_retains_raw_deltas(self):
        report = self._evaluate_g5r(
            before_settings={4: {"changed_pc_targets": {"Kira": 3}}},
            after_settings={
                1: [{"batch_provider_sequence": ["combat_main", "combat_validation", "combat_main",
                                                   "combat_validation"],
                     "batch_validation_results": [False, True]}] * 3,
                4: [{"changed_pc_targets": {"Kira": 3, "Vitreol": 6}}] * 3,
            })
        p1 = next(row for row in report["party_comparisons"] if row["party_size"] == 1)
        self.assertEqual([row["batch"]["validator_rejection_retry_count"] for row in p1["after_runs"]],
                         [1, 1, 1])
        self.assertTrue(all(row["batch"]["validation_provider_calls"] == 2 for row in p1["after_runs"]))
        self.assertEqual(p1["medians"]["validator_rejection_retry_count"], 1.0)
        p4 = next(row for row in report["party_comparisons"] if row["party_size"] == 4)
        self.assertEqual(p4["g5_reference_batch_attribution"]["changed_pc_target_count"], 1)
        self.assertEqual(p4["medians"]["changed_pc_target_count"], 2.0)
        normalization = p4["normalization"]
        self.assertEqual(normalization["changed_pc_target_delta"], 1.0)
        self.assertEqual(normalization["normalized_file_write_delta"],
                         normalization["raw_file_write_delta"] - 1.0)
        p1_normalization = p1["normalization"]
        self.assertEqual(p1_normalization["validator_rejection_retry_delta"], 1.0)
        self.assertEqual(p1_normalization["normalized_provider_call_delta"],
                         p1_normalization["raw_provider_call_delta"] - 1.0)
        self.assertTrue(any("normalized_delta" in row for row in p4["normalization"]["phase_deltas"]))

    def test_g5r_missing_damage_or_retry_attribution_blocks_without_zero_substitution(self):
        before, _ = self._capture_set()
        after = {party: self._make_g5r_runs(party) for party in (1, 4)}
        target = after[4][0]
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        batch_step = next(row for row in manifest["g5"]["fixture"]["steps"]
                          if row["unit_type"] == "batch")
        snapshot_path = target / ("snapshots/step-%03d-before.json" % batch_step["index"])
        snapshot = json.loads(snapshot_path.read_text(encoding="ascii"))
        snapshot["records"].pop("characters/acheron.json")
        snapshot["mechanical_projection"]["characters"].pop("characters/acheron.json")
        snapshot_path.write_bytes(_json_bytes(snapshot))
        manifest["artifact_sha256"] = capture_evidence.hash_artifacts(target, manifest["artifacts"])
        manifest_path.write_bytes(_json_bytes(manifest))
        report = combat_latency_report.evaluate_g5r_comparison(before, after)
        self.assertEqual(report["automated_status"], "BLOCKED")
        p4 = next(row for row in report["party_comparisons"] if row["party_size"] == 4)
        self.assertIsNone(p4["after_runs"][0]["batch"]["changed_pc_target_count"])
        self.assertIsNone(p4["normalization"]["changed_pc_target_delta"])
        self.assertIsNone(p4["normalization"]["normalized_file_write_delta"])
        self.assertTrue(any("snapshot_pc_missing:Acheron" in reason
                            for reason in report["blocking_reasons"]))

        missing_retry = self._make_g5r_runs(1, [{
            "batch_provider_sequence": ["combat_main", "combat_validation"]
        }] * 3)
        retry_report = combat_latency_report.evaluate_g5r_comparison(before, {1: missing_retry, 4: after[4]})
        retry_p1 = next(row for row in retry_report["party_comparisons"] if row["party_size"] == 1)
        self.assertIsNone(retry_p1["after_runs"][0]["batch"]["validator_rejection_retry_count"])
        self.assertIsNone(retry_p1["normalization"]["validator_rejection_retry_delta"])
        self.assertTrue(any("validator_outcome_unattributed_at_batch_end" in reason
                            for reason in retry_report["blocking_reasons"]))

        missing_writes = self._make_g5r_runs(1, [{"batch_raw_writes": 0}, {}, {}])
        writes_report = combat_latency_report.evaluate_g5r_comparison(
            before, {1: missing_writes, 4: after[4]})
        writes_p1 = next(row for row in writes_report["party_comparisons"] if row["party_size"] == 1)
        self.assertIsNone(writes_p1["after_runs"][0]["batch"]["raw_file_writes"])
        self.assertIn("enemy_batch_physical_write_events_missing",
                      writes_p1["after_runs"][0]["batch"]["errors"])
        self.assertEqual(writes_report["automated_status"], "BLOCKED")

    def test_g5r_unsupported_batch_is_a_deviation_and_cannot_pass(self):
        report = self._evaluate_g5r(after_settings={
            1: [{"resolver_outcome": "whole_batch_fallback", "resolver_reason": "preflight_error"}, {}, {}],
            4: [{}, {}, {}],
        })
        self.assertNotEqual(report["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(len(report["unsupported_batch_deviations"]), 1)
        deviation = report["unsupported_batch_deviations"][0]
        self.assertEqual(deviation["outcome"], "whole_batch_fallback")
        resolver_target = next(row for row in report["targets"]
                               if row["target"] == "enemy_batch_resolver_supported" and
                               row["party_size"] == 1 and row["run_id"] == deviation["run_id"])
        self.assertEqual(resolver_target["status"], "FAIL")
        self.assertIn("unsupported batch", combat_latency_report.render_g5r_comparison(report))


if __name__ == "__main__":
    unittest.main()
