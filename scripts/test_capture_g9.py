# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the fixed G9 Capture_Arena tooling."""

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import model_config
from scripts import capture_drive
from scripts import capture_evidence
from scripts import combat_latency_fixtures as fixtures
from scripts import seed_combat_capture
from utils import openrouter_transport_fault_injection as transport_fault


EXPECTED_G9_ROWS = (
    "narrator-auto:p1", "narrator-auto:p4",
    "combat-auto:p1", "combat-auto:p4",
    "transport-failure:p1", "transport-failure:p4",
    "preferred-openai-rollback:p1", "preferred-openai-rollback:p4",
)


def _sandbox_project(parent: Path) -> tuple[Path, Path]:
    project = parent / "g9-project"
    project.mkdir()
    (project / "AGENTS.md").write_text("G9 test project\n", encoding="ascii")
    shutil.copyfile(capture_evidence.PROJECT_ROOT / "model_config.py", project / "model_config.py")
    (project / "tmp").mkdir()
    sandbox = project / "tmp" / "combat_capture"
    sandbox.mkdir()
    shutil.copyfile(capture_evidence.PROJECT_ROOT / "model_config.py", sandbox / "model_config.py")
    return project, sandbox


def _g9_receipts(scenario, run_id):
    task = "dm_main" if scenario == "narrator-auto" else "combat_main"

    def response(attempt, provider, requested, resolved, fallback=False, call_id=None,
                 attempt_number=1):
        return {
            "event_type": "provider", "site": "g9_capture", "run_id": run_id,
            "call_id": call_id or "call-%s" % attempt,
            "attempt_id": "attempt-%s" % attempt, "attempt_number": attempt_number,
            "task": task, "provider": provider,
            "observed_upstream_provider": "unknown",
            "requested_model": requested, "resolved_model": resolved,
            "retry": False, "retry_tier": None, "fallback": fallback,
            "prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0,
            "usage_complete": True, "usage_available": True,
            "provider_reported_cost_usd": None, "cost_usd": None,
            "cost_provenance": "unpriced", "cost_complete": False,
            "outcome": "response", "error_type": None,
        }

    if scenario == "transport-failure":
        return [
            {
                "event_type": "provider", "site": "g9_capture", "run_id": run_id,
                "call_id": "fallback-call", "attempt_id": "attempt-failed",
                "attempt_number": 1, "task": task, "provider": "openrouter",
                "observed_upstream_provider": "unknown",
                "requested_model": "openrouter/auto", "resolved_model": "unknown",
                "retry": False, "retry_tier": None, "fallback": False,
                "prompt_tokens": None, "cached_tokens": None, "completion_tokens": None,
                "usage_complete": False, "usage_available": False,
                "provider_reported_cost_usd": None, "cost_usd": None,
                "cost_provenance": "error", "cost_complete": False,
                "outcome": "transport_error", "error_type": "OpenRouterTransportFaultInjected",
            },
            response("fallback", "openai", "gpt-6-luna", "gpt-6-luna", True,
                     "fallback-call", attempt_number=2),
        ]
    if scenario == "preferred-openai-rollback":
        return [response("direct", "openai", "gpt-6-luna", "gpt-6-luna")]
    return [response("auto", "openrouter", "openrouter/auto", "vendor/model")]


def _transport_failure_receipts_with_followups(run_id, count=2):
    receipts = _g9_receipts("transport-failure", run_id)
    for index in range(1, count + 1):
        followup = _g9_receipts("combat-auto", run_id)[0]
        followup.update({
            "call_id": "combat-followup-%d" % index,
            "attempt_id": "attempt-combat-followup-%d" % index,
        })
        receipts.append(followup)
    return receipts


def _g9_candidate_bundle(run_dir, scenario, party, *, synthetic=False,
                         degraded=False, trace_override=None, lifecycle_override=None,
                         listener_processes_override=None, server_pid_override=None):
    """Write a provider-free, structurally complete candidate bundle for evaluator tests."""
    profile = fixtures.build_gate_profile(
        "g9", scenario, party, phase="rollback" if scenario == "preferred-openai-rollback" else ""
    )
    run_id = run_dir.name
    run_dir.mkdir(parents=True)
    names = ["Acheron"] if party == 1 else ["Acheron", "Merisiel", "Kira", "Vitreol"]
    narrator = profile["capture_kind"] == "narrator"
    encounter_id = None if narrator else "g9-encounter-%d" % party

    def snapshot(label, trace_offset=0, location_id="CA01", active_character=None,
                 observation=None):
        active_character = active_character or names[0]
        world_conditions = {"activeCombatEncounter": encounter_id}
        if narrator:
            world_conditions.update({"currentLocation": "Capture Arena location %s" % location_id,
                                     "currentLocationId": location_id})
        records = {
            "party_tracker.json": {
                "status": "ok", "partyMembers": names, "active_character": active_character,
                "worldConditions": world_conditions,
            },
            "selected_encounter": (
                {"status": "missing_id", "path": None} if narrator else
                {"status": "ok", "encounterId": encounter_id,
                 "creatures": [], "current_round": 1, "combat_phase": "PC_PHASE"}
            ),
            "modules/conversation_history": [], "save_games": [],
        }
        for name in names:
            records["characters/%s.json" % name.lower().replace(" ", "_")] = {
                "read_status": "ok", "name": name, "hitPoints": 20, "maxHitPoints": 20,
        }
        return {
            "label": label, "state_root": "sandbox-relative",
            "errors": ["selected_encounter"] if narrator else [],
            "numeric_errors": [], "records": records,
            "mechanical_projection": capture_evidence._state_projection({"records": records}),
            "observation": ({"runtimeTrace": {"status": "captured", "offset_bytes": trace_offset},
                             "input": "capture step", "character": active_character}
                            if observation is None else observation),
            "g4_read_only_projection": {
                "currentLocation": world_conditions.get("currentLocation"),
                "currentLocationId": world_conditions.get("currentLocationId"),
                "partyMembers": names, "active_character": active_character,
            },
        }

    events = _g9_receipts(scenario, run_id) if trace_override is None else trace_override
    trace_raw = b"".join(
        (json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        for event in events
    )
    trace_path = run_dir / "trace.jsonl"
    trace_path.write_bytes(trace_raw)
    narrator_turns = profile.get("turns", []) if narrator else []
    before = snapshot("before-run", 0, "CA01",
                      narrator_turns[0]["character"] if narrator else None)
    final_turn = narrator_turns[-1] if narrator else {}
    after = snapshot("after-run", len(trace_raw),
                     final_turn.get("expected_location_id", "CA01"),
                     final_turn.get("character") if narrator else None)
    capture_evidence._write_new(run_dir / "snapshots" / "before-run.json", before)
    capture_evidence._write_new(run_dir / "snapshots" / "after-run.json", after)
    transcript_lines = []
    if narrator:
        previous_location = "CA01"
        for index, turn in enumerate(narrator_turns, 1):
            actor = turn["character"]
            utterance = turn["input"]
            reply = ("Warden Mira explains that the three rings mark the shrine's old wards."
                     if turn["kind"] == "mira_dialogue" else
                     "You arrive at location %s." % turn["expected_location_id"])
            before_observation = {
                "label": turn["label"], "input": utterance, "character": actor,
                "runtimeTrace": {"status": "captured", "offset_bytes": 0},
            }
            after_observation = {
                "label": turn["label"], "input": utterance, "character": actor,
                "backend_output_count": 1,
                "actual_backend_outputs": [{"type": "message", "author": "Narrator", "content": reply}],
                "input_echoes": [{"type": "user-input", "content": utterance}],
                "runtimeTrace": {"status": "captured", "offset_bytes": len(trace_raw)},
            }
            step_before = snapshot("step-%03d-before" % index, 0, previous_location,
                                   actor, before_observation)
            step_after = snapshot("step-%03d-after" % index, len(trace_raw),
                                  turn["expected_location_id"], actor, after_observation)
            capture_evidence._write_new(
                run_dir / "snapshots" / ("step-%03d-before.json" % index), step_before
            )
            capture_evidence._write_new(
                run_dir / "snapshots" / ("step-%03d-after.json" % index), step_after
            )
            transcript_lines.extend([
                "[time] [driver] step=%d start label=%s character=%s input=%s" %
                (index, turn["label"], actor, utterance),
                "[time] [game_output] type=user-input author=%s content=%s" % (actor, utterance),
                "[time] [game_output] type=message author=Narrator content=%s" % reply,
                "[time] [driver] step=%d done elapsed=0.1" % index,
            ])
            previous_location = turn["expected_location_id"]
    else:
        step_before = snapshot("step-001-before", 0)
        step_after = snapshot("step-001-after", len(trace_raw))
        step_before["observation"]["runtimeTrace"] = {"status": "captured", "offset_bytes": 0}
        step_after["observation"]["runtimeTrace"] = {"status": "captured", "offset_bytes": len(trace_raw)}
        capture_evidence._write_new(run_dir / "snapshots" / "step-001-before.json", step_before)
        capture_evidence._write_new(run_dir / "snapshots" / "step-001-after.json", step_after)
        transcript_lines.extend([
            "[time] [driver] step=1 start label=capture character=%s input=capture step" % names[0],
            "[time] [driver] step=1 done elapsed=0.1",
        ])
    step_count = len(narrator_turns) if narrator else 1
    transcript_lines.extend([
        "[time] [scenario] id=%s row=%s" % (scenario, profile["row_key"]),
        "[time] [summary] party=%d steps=%d timeouts=0" % (party, step_count),
    ])
    (run_dir / "transcript.log").write_text("\n".join(transcript_lines) + "\n", encoding="ascii")
    (run_dir / "server.log").write_text("[server] sandbox listener ready on 8360\n", encoding="ascii")
    trace_records = [json.loads(line) for line in trace_raw.decode("ascii").splitlines()]
    report = {
        "status": "degraded" if degraded else "ok",
        "input": {"total_records": len(trace_records), "malformed_count": 0},
        "combat_observations": [row for row in trace_records
                                if row.get("event_type") == "combat_observation"],
    }
    capture_evidence._write_new(run_dir / "report.json", report)
    required_runtime = profile["g9_runtime"]
    contract = {key: profile.get(key) for key in
                ("scenario_id", "party_size", "branch", "phase", "seed", "applicability")}
    contract.update({"gate": "g9", "row_key": profile["row_key"],
                     "seed_scenario_id": profile["seed_scenario_id"],
                     "capture_kind": profile["capture_kind"], "g9_runtime": required_runtime})
    seed = dict(profile.get("seed", {}))
    seed_hash = hashlib.sha256(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()
    expected_provider = required_runtime["configured_provider"]
    rollback = scenario == "preferred-openai-rollback"
    marker = {
        "status": "ok", "sha256": "b" * 64,
        "gate": "g9", "row_key": profile["row_key"], "scenario_id": scenario,
        "party_size": party, "run_dir": str(run_dir.resolve().relative_to(capture_evidence.PROJECT_ROOT)),
        "initial_provider": "openrouter", "active_profile": "production-auto",
        "transport_failure_injection": scenario == "transport-failure",
        "rollback_state": "configured" if rollback else "not_required",
        "rollback_provider": "openai" if rollback else None,
        "rollback_model": "gpt-6-luna" if rollback else None,
        "operator_restart_count_required": 1 if rollback else 0,
        "reseed_after_rollback": False,
        "provenance": "sandbox .g9-capture.json",
    }
    config = {
        "status": "ok", "configured_provider": expected_provider,
        "active_profile": "production-auto", "configured_model": "gpt-6-luna",
        "openai_fallback_model": "gpt-6-luna",
        "transport_fault_injection_enabled": scenario == "transport-failure",
        "model_config_sha256": "a" * 64,
        "provenance": "sandbox model_config.py AST literals",
    }
    actual_projection = capture_evidence.project_g9_receipts(events, run_id)
    actual_runtime = capture_evidence._g9_runtime_summary(
        actual_projection.get("receipts", []), actual_projection.get("status", "BLOCKED")
    )
    current_offset = len(trace_raw)
    lifecycle_events = [{"gate": "g9", "event": "prepare", "row_key": profile["row_key"],
                         "run_id": run_id, "party_size": party}]
    first_server_pid = 101 if server_pid_override is None else server_pid_override

    def started(posture, pid):
        log_artifact = "server_before_rollback.log" if rollback and posture == "openrouter" else "server.log"
        event_server_pid = (first_server_pid
                            if server_pid_override is not None and
                            (not rollback or posture == "openrouter") else pid)
        listener_processes = listener_processes_override
        if listener_processes is None:
            listener_processes = [{
                "pid": event_server_pid, "ancestry_pids": [event_server_pid], "port": 8360,
                "cwd": str((capture_evidence.PROJECT_TMP / "combat_capture").resolve()),
            }]
        else:
            listener_processes = [dict(record) for record in listener_processes]
        return {"gate": "g9", "event": "server_started", "row_key": profile["row_key"],
                "run_id": run_id, "party_size": party, "posture": posture,
                "server_pid": event_server_pid,
                "listener_pids": [record.get("pid") for record in listener_processes],
                "listener_processes": listener_processes, "port": 8360,
                "cwd": str((capture_evidence.PROJECT_TMP / "combat_capture").resolve()),
                "ownership": "lsof_parent_pid_and_cwd",
                "server_log_artifact": log_artifact}

    def stopped(pid):
        log_artifact = "server_before_rollback.log" if rollback and pid == first_server_pid else "server.log"
        log_raw = (run_dir / log_artifact).read_bytes()
        return {"gate": "g9", "event": "server_stopped", "row_key": profile["row_key"],
                "run_id": run_id, "party_size": party, "server_pid": pid,
                "port": 8360, "remaining_listener_pids": [],
                "server_log_artifact": log_artifact,
                "server_log_sha256": hashlib.sha256(log_raw).hexdigest(),
                "server_log_bytes": len(log_raw)}

    if rollback:
        (run_dir / "server_before_rollback.log").write_text(
            "[server] sandbox listener ready on 8360 before rollback\n", encoding="ascii"
        )
        lifecycle_events.extend([started("openrouter", first_server_pid), stopped(first_server_pid),
                                 {"gate": "g9", "event": "rollback_configured",
                                  "row_key": profile["row_key"], "run_id": run_id,
                                  "party_size": party, "provider": "openai", "model": "gpt-6-luna",
                                  "reseed_after_rollback": False},
                                 started("openai", 202)])
    else:
        lifecycle_events.append(started("openrouter", first_server_pid))
    lifecycle_events.extend([
        {"gate": "g9", "event": "capture_completed", "row_key": profile["row_key"],
         "run_id": run_id, "party_size": party, "driver_exit_status": 0},
        stopped(202 if rollback else first_server_pid),
    ])
    if lifecycle_override is not None:
        lifecycle_events = lifecycle_override
    lifecycle_raw = b"".join(
        (json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        for event in lifecycle_events
    )
    (run_dir / "server_lifecycle.jsonl").write_bytes(lifecycle_raw)
    trace_copy = {"status": "copied", "source_records": len(trace_records),
                  "destination_records": len(trace_records), "offset_before_bytes": 0,
                  "offset_after_bytes": current_offset, "span_bytes": current_offset}
    artifacts = {
        "transcript": "transcript.log", "server_log": "server.log",
        "rollback_server_log": "server_before_rollback.log" if rollback else None,
        "server_lifecycle": "server_lifecycle.jsonl", "trace": "trace.jsonl",
        "report": "report.json", "before_snapshot": "snapshots/before-run.json",
        "after_snapshot": "snapshots/after-run.json", "checks": "checks.json",
        "step_snapshots": [
            "snapshots/step-%03d-%s.json" % (index, edge)
            for index in range(1, step_count + 1) for edge in ("before", "after")
        ],
        "missing_step_snapshots": [], "trace_copy": trace_copy,
        "copy_errors": [], "required_evidence_status": "degraded" if degraded else "ok",
        "trace_applicability": {"status": "required", "declared_before_run": False,
                                "reason": "required for this scenario"},
        "matrix_keys": [profile["row_key"]],
    }
    step_rows, step_errors = capture_evidence.load_step_snapshots(
        run_dir, {"counts": {"steps_sent": step_count}}
    )
    observations, provider_events = capture_evidence.trace_check_inputs(
        [{**event, "_source_byte_start": index * 10, "_source_byte_end": index * 10 + 1}
         for index, event in enumerate(trace_records)]
    )
    checks = capture_evidence.observed_checks(
        profile, before, after, artifacts, step_rows,
        observations,
    )
    if step_errors:
        checks.append({"id": "all_step_snapshots_readable", "required": True,
                       "expected": "complete before/after snapshot pair for each sent step",
                       "observed": step_errors, "status": "BLOCKED",
                       "evidence": "manifest artifact step refs"})
    capture_evidence._write_new(run_dir / "checks.json", {"checks": checks, "primary_verdict": "PENDING"})
    artifacts["trace_provider_events"] = provider_events
    artifacts["trace_position_errors"] = []
    before_digest = capture_evidence.snapshot_digest(before)
    after_digest = capture_evidence.snapshot_digest(after)
    source = capture_evidence._source_identity()
    source_hashes = source.get("relevant_source_sha256", {})
    manifest = {
        "evidence_kind": "synthetic" if synthetic else "live-candidate",
        "live_eligible": not synthetic, "gate": "g9", "run_id": run_id,
        "scenario": {"id": scenario, "version": "g9-openrouter-v1", "phase": "rollback" if rollback else None,
                     "branch": None, "profile_contract": contract,
                     "sha256": hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()},
        "party": {"size": party, "roster": names},
        "seed": {"roster": names, "active_encounter": encounter_id,
                 "profile_seed": seed, "seed_profile_sha256": seed_hash, "seed_id": seed_hash},
        "sandbox_id": "c" * 64,
        "source": source,
        "prompt_identity_sha256": capture_evidence._prompt_identity(),
        "configuration": {
            "provenance": {"operator_declared": "test-only declaration", "actual_runtime": "response receipts"},
            "operator_declared": {"provider": "openai", "profile": "ignored", "requested_model": "declared-only"},
            "actual_runtime": actual_runtime, "g9_runtime": config,
        },
        "g9": {"row_key": profile["row_key"], "sandbox_marker": marker,
               "worktree_identity": {
                   "status": "ok", "root": str(capture_evidence.PROJECT_ROOT.resolve()),
                   "head": source.get("head"),
                   "relevant_dirty_sha256": source.get("relevant_dirty_sha256"),
                   "relevant_source_sha256": hashlib.sha256(json.dumps(
                       source_hashes, sort_keys=True).encode("utf-8")).hexdigest(),
                   "provenance": "git HEAD and relevant source identity",
               },
               "response_receipts": actual_projection.get("receipts", []),
               "receipt_status": actual_projection.get("status"),
               "receipt_reason": actual_projection.get("reason"),
               "lifecycle": {"status": "finalized", "artifact": "server_lifecycle.jsonl",
                             "sha256": hashlib.sha256(lifecycle_raw).hexdigest()}},
        "sandbox_runtime": {"port": 8360, "port_provenance": "validated operator URL",
                            "trace_gate": {"status": "ok", "enabled": True},
                            "trace_observations_present": False},
        "transport": {"url": "http://localhost:8360", "kind": "socket.io + local REST",
                      "client_source": "socketio.Client", "resolved_response_model": actual_runtime["response_model"]},
        "timestamps": {"started_at": "2026-10-27T00:00:00+00:00", "manifest_written_at": "2026-10-27T00:01:00+00:00"},
        "bounds": {"max_steps": profile["max_steps"], "max_requests": profile["max_requests"],
                   "max_active_switches": profile["max_active_switches"],
                   "max_health_reads": profile.get("max_health_reads", 0),
                   "start_timeout_seconds": 30.0,
                   "turn_timeout_seconds": profile.get("turn_timeout_seconds", 150.0),
                   "turn_quiet_seconds": 1.0},
        "counts": {"step_attempts": step_count, "steps_sent": step_count,
                   "backend_output_count": step_count,
                   "control_request_attempts": 1, "control_request_calls": 1,
                   "control_request_failures": 0, "control_requests_sent": 1,
                   "active_switch_attempts": 1, "active_switch_requests_sent": 1,
                   "blocked_step_attempts": 0, "blocked_control_attempts": 0,
                   "timeouts": 0, "start_timeout": False, "step_caps_reached": 0,
                   "idle_settle_caps_reached": 0, "active_switch_failures": 0,
                   "health_read_attempts": 0, "exit_health_read_attempts": 0,
                   "provider_calls": {"count": len(actual_projection.get("receipts", [])),
                                      "source": "router-response-receipts"}},
        "trace_start_offset": {"status": "captured", "source_byte_offset": 0},
        "trace_span": trace_copy, "snapshot_chain": {
            "before_run_sha256": before_digest, "after_run_sha256": after_digest,
        },
        "artifacts": artifacts,
    }
    if degraded:
        manifest["artifacts"]["required_evidence_status"] = "degraded"
    manifest["artifact_sha256"] = capture_evidence.hash_artifacts(run_dir, artifacts)
    capture_evidence._write_new(run_dir / "manifest.json", manifest)
    return run_dir


class G9FixtureTests(unittest.TestCase):
    def test_registry_is_exactly_the_eight_required_rows(self):
        self.assertEqual(fixtures.required_g9_row_keys(), EXPECTED_G9_ROWS)
        self.assertEqual(fixtures.G9_PARTY_SIZES, (1, 4))
        for scenario in fixtures.G9_SCENARIOS:
            for party_size in fixtures.G9_PARTY_SIZES:
                phase = "rollback" if scenario == "preferred-openai-rollback" else ""
                profile = fixtures.build_gate_profile(
                    "g9", scenario, party_size, phase=phase
                )
                self.assertEqual(profile["row_key"], "%s:p%d" % (scenario, party_size))
                self.assertEqual(profile["gate"], "g9")
                self.assertEqual(profile["g9_runtime"]["active_profile"], "production-auto")
                self.assertEqual(
                    profile["g9_runtime"]["configured_provider"],
                    "openai" if phase else "openrouter",
                )
                self.assertEqual(
                    profile["g9_runtime"]["transport_failure_injection"],
                    scenario == "transport-failure",
                )

    def test_unknown_scenario_party_and_phase_are_rejected(self):
        for scenario, party, phase in (
            ("combat-smoke", 1, ""),
            ("narrator-auto", 2, ""),
            ("narrator-auto", True, ""),
            ("preferred-openai-rollback", 1, "complete"),
            ("combat-auto", 4, "rollback"),
        ):
            with self.subTest(scenario=scenario, party=party, phase=phase):
                with self.assertRaises(ValueError):
                    fixtures.build_gate_profile("g9", scenario, party, phase=phase)


class G9PreflightTests(unittest.TestCase):
    def _run_args(self, argv):
        return capture_drive.build_parser().parse_args(["--gate", "g9"] + argv)

    def _assert_rejected_before_session(self, argv):
        args = self._run_args(argv)
        with patch.object(capture_drive, "CaptureSession", side_effect=AssertionError("session constructed")) as session:
            with contextlib.redirect_stdout(io.StringIO()):
                status = capture_drive.run(args)
        self.assertEqual(status, capture_drive.EXIT_CONNECT_FAILURE)
        session.assert_not_called()

    def test_narrator_auto_inherits_g4_300_second_profile_only(self):
        for party in (1, 4):
            with self.subTest(party=party):
                args = self._run_args([
                    "--party", str(party), "--scenario", "narrator-auto",
                    "--run-dir", "tmp/router-rollout/g9/narrator-timeout-p%d" % party,
                    "--server-log", "tmp/router-rollout/g9/narrator-timeout-p%d.log" % party,
                    "--g9-lifecycle-log", "tmp/router-rollout/g9/narrator-timeout-p%d-lifecycle.jsonl" % party,
                ])
                args.turn_timeout = 150.0
                with patch.object(capture_drive, "CaptureSession",
                                  side_effect=AssertionError("session constructed")) as session:
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        status = capture_drive.run(args)
                self.assertEqual(status, capture_drive.EXIT_CONNECT_FAILURE)
                self.assertEqual(args.turn_timeout, 300)
                self.assertNotIn("timeout up to 150", output.getvalue())
                session.assert_not_called()

        for scenario, party, timeout in (("combat-auto", 1, 300.0),):
            with self.subTest(scenario=scenario, timeout=timeout):
                args = self._run_args([
                    "--party", str(party), "--scenario", scenario,
                    "--run-dir", "tmp/router-rollout/g9/rejected-timeout",
                    "--server-log", "tmp/router-rollout/g9/rejected-timeout.log",
                    "--g9-lifecycle-log", "tmp/router-rollout/g9/rejected-timeout-lifecycle.jsonl",
                ])
                args.turn_timeout = timeout
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = capture_drive.run(args)
                self.assertEqual(status, capture_drive.EXIT_CONNECT_FAILURE)
                self.assertIn("timeout up to 150", output.getvalue())

        args = self._run_args([
            "--party", "4", "--scenario", "narrator-auto",
            "--run-dir", "tmp/router-rollout/g9/rejected-narrator-timeout",
            "--server-log", "tmp/router-rollout/g9/rejected-narrator-timeout.log",
            "--g9-lifecycle-log", "tmp/router-rollout/g9/rejected-narrator-timeout-lifecycle.jsonl",
        ])
        args.turn_timeout = 150.0
        with patch.object(capture_drive.capture_fixtures, "build_gate_profile",
                          return_value={"turn_timeout_seconds": 301}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = capture_drive.run(args)
        self.assertEqual(status, capture_drive.EXIT_CONNECT_FAILURE)
        self.assertIn("timeout up to 150", output.getvalue())

    def test_missing_scenario_party_or_unique_run_dir_is_rejected_before_session(self):
        self._assert_rejected_before_session(["--party", "1", "--run-dir", "tmp/router-rollout/g9/missing-scenario"])
        self._assert_rejected_before_session(["--scenario", "combat-auto", "--run-dir", "tmp/router-rollout/g9/missing-party"])
        self._assert_rejected_before_session(["--party", "1", "--scenario", "combat-auto"])

    def test_reused_run_directory_is_rejected_before_session(self):
        capture_evidence.G9_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
                prefix="g9-reused-run-", dir=str(capture_evidence.G9_RUN_ROOT)) as run_dir:
            self._assert_rejected_before_session([
                "--party", "1", "--scenario", "combat-auto", "--run-dir", run_dir,
            ])

    def test_invalid_row_key_and_party_are_rejected_by_registry(self):
        with self.assertRaises(ValueError):
            fixtures.g9_row_key("combat-smoke", 1)
        with self.assertRaises(ValueError):
            fixtures.g9_row_key("combat-auto", 2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            capture_drive.build_parser().parse_args([
                "--gate", "g9", "--party", "1", "--scenario", "not-g9",
            ])

    def test_seeder_requires_g9_scenario_and_unique_run_dir_before_prepare(self):
        with patch.object(seed_combat_capture, "prepare") as prepare:
            for argv in (
                ["--prepare", "--gate", "g9", "--party", "1"],
                ["--prepare", "--gate", "g9", "--party", "1", "--scenario", "combat-auto"],
            ):
                with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        seed_combat_capture.main(argv)
            prepare.assert_not_called()

    def test_combat_rows_use_the_existing_fixed_socket_script(self):
        args = capture_drive.build_parser().parse_args([
            "--gate", "g9", "--party", "1", "--scenario", "transport-failure",
            "--run-dir", "tmp/router-rollout/g9/g9-driver-dispatch-test",
            "--transcript", "tmp/router-rollout/g9/g9-driver-dispatch-test.log",
        ])
        session = capture_drive.CaptureSession(args, socket_client=object())
        with patch.object(session, "set_active_character", return_value=True), \
                patch.object(session, "run_g5_scenario") as fixed_script, \
                patch.object(session, "log"):
            status = session.run_named_scenario("transport-failure")
        self.assertEqual(status, capture_drive.EXIT_OK)
        fixed_script.assert_called_once()


class G9SandboxConfigTests(unittest.TestCase):
    def test_g9_patch_changes_only_the_sandbox_copy(self):
        capture_evidence.PROJECT_TMP.mkdir(parents=True, exist_ok=True)
        installed_path = capture_evidence.PROJECT_ROOT / "model_config.py"
        installed_hash = hashlib.sha256(installed_path.read_bytes()).hexdigest()
        installed_provider = model_config.LLM_PROVIDER
        with tempfile.TemporaryDirectory(
                prefix="g9-config-sandbox-", dir=str(capture_evidence.PROJECT_TMP)) as scratch:
            project, sandbox = _sandbox_project(Path(scratch))
            with patch.object(seed_combat_capture, "PROJECT_ROOT", project), \
                    patch.object(seed_combat_capture, "SANDBOX_ROOT", sandbox):
                seed_combat_capture._patch_sandbox_model_config("g9", "narrator-auto")
            identity = capture_evidence.read_sandbox_g9_identity(sandbox)
            self.assertEqual(identity["status"], "ok")
            self.assertEqual(identity["configured_provider"], "openrouter")
            self.assertEqual(identity["active_profile"], "production-auto")
            self.assertEqual(identity["configured_model"], "gpt-6-luna")
            self.assertIs(identity["transport_fault_injection_enabled"], False)
        self.assertEqual(hashlib.sha256(installed_path.read_bytes()).hexdigest(), installed_hash)
        self.assertEqual(model_config.LLM_PROVIDER, installed_provider)

    def test_transport_failure_flag_is_enabled_only_in_its_sandbox_row(self):
        with tempfile.TemporaryDirectory(
                prefix="g9-transport-config-", dir=str(capture_evidence.PROJECT_TMP)) as scratch:
            project, sandbox = _sandbox_project(Path(scratch))
            with patch.object(seed_combat_capture, "PROJECT_ROOT", project), \
                    patch.object(seed_combat_capture, "SANDBOX_ROOT", sandbox):
                seed_combat_capture._patch_sandbox_model_config("g9", "transport-failure")
            identity = capture_evidence.read_sandbox_g9_identity(sandbox)
            self.assertEqual(identity["status"], "ok")
            self.assertIs(identity["transport_fault_injection_enabled"], True)
            self.assertEqual(identity["configured_provider"], "openrouter")

    def test_g9_patch_refuses_a_non_capture_sandbox_path(self):
        with tempfile.TemporaryDirectory(
                prefix="g9-not-sandbox-", dir=str(capture_evidence.PROJECT_TMP)) as scratch:
            bad_root = Path(scratch) / "not-combat-capture"
            bad_root.mkdir()
            source = capture_evidence.PROJECT_ROOT / "model_config.py"
            target = bad_root / "model_config.py"
            shutil.copyfile(source, target)
            before = target.read_bytes()
            with patch.object(seed_combat_capture, "SANDBOX_ROOT", bad_root):
                with self.assertRaises(RuntimeError):
                    seed_combat_capture._patch_sandbox_model_config("g9", "transport-failure")
            self.assertEqual(target.read_bytes(), before)


class G9TransportFaultTests(unittest.TestCase):
    def test_fault_is_disabled_without_flag_and_never_runs_outside_capture_sandbox(self):
        with patch.object(model_config, "OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED", False), \
                patch.object(transport_fault, "repository_root") as root_resolver:
            self.assertFalse(transport_fault.maybe_inject_openrouter_transport_failure("openrouter"))
            root_resolver.assert_not_called()
        with patch.object(model_config, "OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED", True), \
                patch.object(transport_fault, "repository_root", return_value=capture_evidence.PROJECT_ROOT):
            self.assertFalse(transport_fault.maybe_inject_openrouter_transport_failure("openrouter"))
        with patch.object(model_config, "OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED", True), \
                patch.object(transport_fault, "repository_root", return_value=capture_evidence.PROJECT_ROOT):
            self.assertFalse(transport_fault.maybe_inject_openrouter_transport_failure("openai"))

    def test_authorized_failure_is_one_shot(self):
        with tempfile.TemporaryDirectory(
                prefix="g9-fault-sandbox-", dir=str(capture_evidence.PROJECT_TMP)) as scratch:
            project, sandbox = _sandbox_project(Path(scratch))
            with patch.object(model_config, "OPENROUTER_TRANSPORT_FAULT_INJECTION_ENABLED", True), \
                    patch.object(transport_fault, "repository_root", return_value=sandbox), \
                    patch.object(transport_fault, "_INJECTED", False):
                with self.assertRaises(transport_fault.OpenRouterTransportFaultInjected):
                    transport_fault.maybe_inject_openrouter_transport_failure("openrouter")
                self.assertFalse(
                    transport_fault.maybe_inject_openrouter_transport_failure("openrouter")
                )


class G9RollbackTests(unittest.TestCase):
    def test_rollback_switches_prepared_sandbox_once_without_reseeding(self):
        with tempfile.TemporaryDirectory(
                prefix="g9-rollback-", dir=str(capture_evidence.PROJECT_TMP)) as scratch:
            project, sandbox = _sandbox_project(Path(scratch))
            run_root = project / "tmp" / "router-rollout" / "g9"
            run_root.mkdir(parents=True)
            run_dir = "tmp/router-rollout/g9/rollback-p1-test"
            with patch.object(seed_combat_capture, "PROJECT_ROOT", project), \
                    patch.object(seed_combat_capture, "SANDBOX_ROOT", sandbox):
                seed_combat_capture._patch_sandbox_model_config(
                    "g9", "preferred-openai-rollback"
                )
                seed_combat_capture._write_g9_marker({
                    "gate": "g9",
                    "row_key": "preferred-openai-rollback:p1",
                    "scenario_id": "preferred-openai-rollback",
                    "party_size": 1,
                    "run_dir": run_dir,
                    "initial_provider": "openrouter",
                    "active_profile": "production-auto",
                    "transport_failure_injection": False,
                    "rollback_state": "pending",
                    "operator_restart_count_required": 1,
                    "reseed_after_rollback": False,
                })
                with patch.object(seed_combat_capture, "prepare") as prepare:
                    self.assertEqual(seed_combat_capture.main([
                        "--rollback-openai", "--gate", "g9",
                        "--scenario", "preferred-openai-rollback", "--party", "1",
                        "--run-dir", run_dir,
                    ]), 0)
                    prepare.assert_not_called()
                identity = capture_evidence.read_sandbox_g9_identity(sandbox)
                self.assertEqual(identity["configured_provider"], "openai")
                self.assertEqual(identity["configured_model"], "gpt-6-luna")
                marker = json.loads((sandbox / seed_combat_capture._G9_MARKER_NAME).read_text(encoding="utf-8"))
                self.assertEqual(marker["rollback_state"], "configured")
                self.assertEqual(marker["operator_restart_count_required"], 1)
                self.assertIs(marker["reseed_after_rollback"], False)
                profile = fixtures.build_gate_profile(
                    "g9", "preferred-openai-rollback", 1, phase="rollback"
                )
                args = type("Args", (), {
                    "state_root": str(sandbox),
                    "run_dir": str(project / run_dir),
                    "phase": "rollback",
                })()
                with patch.object(capture_drive, "PROJECT_ROOT", project), \
                        patch.object(capture_drive, "PROJECT_TMP", project / "tmp"):
                    capture_drive._validate_g9_sandbox(profile, args)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    seed_combat_capture.main([
                        "--rollback-openai", "--gate", "g9",
                        "--scenario", "preferred-openai-rollback", "--party", "1",
                        "--run-dir", run_dir,
                    ])


class G9EvaluatorTests(unittest.TestCase):
    def setUp(self):
        capture_evidence.G9_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(
            prefix="g9-evaluator-", dir=str(capture_evidence.G9_RUN_ROOT)
        )
        self.root = Path(self.temp.name)
        self.matrix_counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def _full_matrix(self, overrides=None):
        matrix_root = self.root / ("matrix-%02d" % self.matrix_counter)
        self.matrix_counter += 1
        paths = []
        overrides = overrides or {}
        for index, row_key in enumerate(EXPECTED_G9_ROWS):
            scenario, party_text = row_key.split(":p")
            path = matrix_root / ("candidate-%02d" % index)
            options = overrides.get(row_key, {})
            paths.append(_g9_candidate_bundle(path, scenario, int(party_text), **options))
        return paths

    def _refresh_artifact_hashes(self, run):
        manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
        self.assertIsNone(error)
        manifest["artifact_sha256"] = capture_evidence.hash_artifacts(run, manifest["artifacts"])
        (run / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="ascii",
        )
        return manifest

    def test_narrator_timeout_uses_fixed_g4_300_second_profile(self):
        for party in (1, 4):
            with self.subTest(party=party):
                run = _g9_candidate_bundle(
                    self.root / ("narrator-timeout-p%d" % party), "narrator-auto", party
                )
                manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
                self.assertIsNone(error)
                self.assertEqual(manifest["bounds"]["turn_timeout_seconds"], 300)
                result = capture_evidence._evaluate_g9_run(run)["evaluation"]
                self.assertEqual(result["automated_status"], "READY_FOR_PRIMARY_REVIEW")

        for scenario, party, timeout in (
            ("narrator-auto", 1, 150.0),
            ("narrator-auto", 4, 301.0),
            ("combat-auto", 1, 300.0),
        ):
            with self.subTest(scenario=scenario, party=party, timeout=timeout):
                run = _g9_candidate_bundle(
                    self.root / ("invalid-timeout-%s-p%d-%s" % (scenario, party, timeout)),
                    scenario, party,
                )
                manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
                self.assertIsNone(error)
                manifest["bounds"]["turn_timeout_seconds"] = timeout
                (run / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
                    encoding="ascii",
                )
                result = capture_evidence._evaluate_g9_run(run)["evaluation"]
                self.assertEqual(result["automated_status"], "BLOCKED")
                self.assertIn("capture:malformed_counts_or_bounds", result["problems"])

    def test_launcher_may_differ_from_listener_with_complete_lsof_ancestry(self):
        row_key = "narrator-auto:p1"
        scenario, party_text = row_key.split(":p")
        path = self.root / "descendant-listener"
        sandbox_cwd = str((capture_evidence.PROJECT_TMP / "combat_capture").resolve())
        run = _g9_candidate_bundle(
            path, scenario, int(party_text),
            server_pid_override=48002,
            listener_processes_override=[{
                "pid": 48015, "ancestry_pids": [48015, 48002],
                "port": 8360, "cwd": sandbox_cwd,
            }],
        )
        result = capture_evidence._evaluate_g9_run(run)
        self.assertEqual(result["evaluation"]["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        lifecycle = (run / "server_lifecycle.jsonl").read_text(encoding="ascii")
        started_event = next(
            json.loads(line) for line in lifecycle.splitlines()
            if json.loads(line).get("event") == "server_started"
        )
        self.assertEqual(started_event["server_pid"], 48002)
        self.assertEqual(started_event["listener_pids"], [48015])
        self.assertEqual(started_event["listener_processes"][0]["ancestry_pids"],
                         [48015, 48002])

    def test_same_pid_listener_has_a_complete_single_node_chain(self):
        row_key = "narrator-auto:p1"
        scenario, party_text = row_key.split(":p")
        run = _g9_candidate_bundle(
            self.root / "same-pid-listener", scenario, int(party_text)
        )
        result = capture_evidence._evaluate_g9_run(run)
        self.assertEqual(result["evaluation"]["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        lifecycle = (run / "server_lifecycle.jsonl").read_text(encoding="ascii")
        started_event = next(
            json.loads(line) for line in lifecycle.splitlines()
            if json.loads(line).get("event") == "server_started"
        )
        self.assertEqual(started_event["listener_pids"], [started_event["server_pid"]])
        self.assertEqual(
            started_event["listener_processes"][0]["ancestry_pids"],
            [started_event["server_pid"]],
        )

    def test_incomplete_or_contradictory_listener_ownership_is_rejected(self):
        row_key = "narrator-auto:p1"
        scenario, party_text = row_key.split(":p")
        sandbox_cwd = str((capture_evidence.PROJECT_TMP / "combat_capture").resolve())

        def missing_processes(event):
            event.pop("listener_processes")

        def missing_ancestry(event):
            event["listener_processes"][0].pop("ancestry_pids")

        def duplicate_listener(event):
            event["listener_pids"].append(event["listener_pids"][0])

        def nonpositive_listener(event):
            event["listener_pids"] = [0]

        def contradictory_listener_set(event):
            event["listener_pids"] = [48016]

        def ancestry_cycle(event):
            event["listener_processes"][0]["ancestry_pids"] = [48015, 48002, 48015]

        def unowned_listener(event):
            event["listener_processes"][0]["ancestry_pids"] = [48015, 99999]

        def wrong_listener_port(event):
            event["listener_processes"][0]["port"] = 8357

        def wrong_listener_cwd(event):
            event["listener_processes"][0]["cwd"] = str(self.root)

        cases = (
            ("missing-processes", missing_processes, "BLOCKED"),
            ("missing-ancestry", missing_ancestry, "BLOCKED"),
            ("duplicate-listener", duplicate_listener, "FAIL"),
            ("nonpositive-listener", nonpositive_listener, "FAIL"),
            ("contradictory-listener-set", contradictory_listener_set, "FAIL"),
            ("ancestry-cycle", ancestry_cycle, "FAIL"),
            ("unowned-listener", unowned_listener, "FAIL"),
            ("wrong-listener-port", wrong_listener_port, "FAIL"),
            ("wrong-listener-cwd", wrong_listener_cwd, "FAIL"),
        )
        for name, mutate, expected_status in cases:
            with self.subTest(case=name):
                run = _g9_candidate_bundle(
                    self.root / name, scenario, int(party_text),
                    server_pid_override=48002,
                    listener_processes_override=[{
                        "pid": 48015, "ancestry_pids": [48015, 48002],
                        "port": 8360, "cwd": sandbox_cwd,
                    }],
                )
                lifecycle_path = run / "server_lifecycle.jsonl"
                lifecycle_events = [
                    json.loads(line) for line in lifecycle_path.read_text(encoding="ascii").splitlines()
                ]
                started_event = next(
                    event for event in lifecycle_events if event.get("event") == "server_started"
                )
                mutate(started_event)
                lifecycle_raw = b"".join(
                    (json.dumps(event, ensure_ascii=True, sort_keys=True,
                                separators=(",", ":")) + "\n").encode("ascii")
                    for event in lifecycle_events
                )
                lifecycle_path.write_bytes(lifecycle_raw)
                manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
                self.assertIsNone(error)
                manifest["g9"]["lifecycle"]["sha256"] = hashlib.sha256(lifecycle_raw).hexdigest()
                manifest["artifact_sha256"] = capture_evidence.hash_artifacts(
                    run, manifest["artifacts"]
                )
                (run / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
                    encoding="ascii",
                )
                result = capture_evidence._evaluate_g9_run(run)["evaluation"]
                self.assertEqual(result["automated_status"], expected_status)
                self.assertTrue(result["problems"] or result["failures"])

    def test_complete_candidate_matrix_is_ready_only_for_primary_review(self):
        paths = self._full_matrix()
        result = capture_evidence.evaluate_g9_matrix(paths)
        self.assertEqual(result["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(result["primary_verdict"], "PENDING")
        self.assertEqual(result["required_keys"], list(EXPECTED_G9_ROWS))
        first = capture_evidence._evaluate_g9_run(paths[0])
        receipt = first["manifest"]["g9"]["response_receipts"][0]
        self.assertEqual(receipt["cost_provenance"], "unpriced")
        self.assertIsNone(receipt["cost_usd"])
        self.assertIs(receipt["cost_complete"], False)
        self.assertEqual(first["manifest"]["configuration"]["actual_runtime"]["provider"], "openrouter")
        fallback = capture_evidence._evaluate_g9_run(paths[4])
        fallback_receipts = fallback["manifest"]["g9"]["response_receipts"]
        self.assertEqual(fallback["evaluation"]["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(fallback["evaluation"]["runtime_assertions"]["transport_error_count"], 1)
        self.assertEqual(fallback["evaluation"]["runtime_assertions"]["response_count"], 1)
        self.assertEqual(fallback_receipts[-1]["requested_model"], "gpt-6-luna")
        self.assertEqual(fallback_receipts[-1]["provider"], "openai")
        self.assertIs(fallback_receipts[-1]["fallback"], True)
        rollback = capture_evidence._evaluate_g9_run(paths[6])
        self.assertEqual(rollback["evaluation"]["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(rollback["evaluation"]["lifecycle"]["restart_count"], 1)
        self.assertEqual(
            rollback["manifest"]["g9"]["response_receipts"][0]["resolved_model"],
            "gpt-6-luna",
        )

    def test_transport_failure_allows_subsequent_distinct_auto_responses(self):
        for party in (1, 4):
            with self.subTest(party=party):
                run_id = "transport-followups-p%d" % party
                run = _g9_candidate_bundle(
                    self.root / run_id, "transport-failure", party,
                    trace_override=_transport_failure_receipts_with_followups(run_id),
                )
                result = capture_evidence._evaluate_g9_run(run)["evaluation"]
                self.assertEqual(result["automated_status"], "READY_FOR_PRIMARY_REVIEW")
                runtime = result["runtime_assertions"]
                self.assertEqual(runtime["status"], "PASS")
                self.assertEqual(runtime["transport_error_count"], 1)
                self.assertEqual(runtime["response_count"], 3)

    def test_transport_failure_rejects_extra_or_ambiguous_attempts(self):
        profile = fixtures.build_gate_profile("g9", "transport-failure", 4)

        def extra_auto(call_id="extra-auto-call", attempt_id="attempt-extra-auto"):
            row = _g9_receipts("combat-auto", "transport-negative")[0]
            row.update({"call_id": call_id, "attempt_id": attempt_id})
            return row

        def add_same_call_attempt(rows):
            rows.append(extra_auto("fallback-call", "attempt-extra-same-call"))

        def add_extra_error(rows):
            row = dict(rows[0])
            row.update({
                "call_id": "extra-error-call", "attempt_id": "attempt-extra-error",
                "error_type": "APITimeoutError",
            })
            rows.append(row)

        def add_extra_fallback(rows):
            row = dict(rows[1])
            row.update({"call_id": "extra-fallback-call",
                        "attempt_id": "attempt-extra-fallback"})
            rows.append(row)

        def add_unexpected_direct_response(rows):
            row = extra_auto("unexpected-direct-call", "attempt-unexpected-direct")
            row.update({
                "provider": "openai", "requested_model": "gpt-6-luna",
                "resolved_model": "gpt-6-luna",
            })
            rows.append(row)

        def remove_followup_call_id(rows):
            rows[2].pop("call_id")

        def reverse_fallback_order(rows):
            rows[0], rows[1] = rows[1], rows[0]

        def skip_fallback_attempt_number(rows):
            rows[1]["attempt_number"] = 3

        def put_auto_response_before_fallback(rows):
            rows.insert(0, extra_auto("early-auto-call", "attempt-early-auto"))

        cases = (
            ("same-call-extra", add_same_call_attempt, "transport_failure_extra_same_call_attempt"),
            ("extra-error", add_extra_error, "injected_transport_failure_not_exactly_once"),
            ("extra-fallback", add_extra_fallback, "direct_openai_fallback_not_exactly_once"),
            ("unexpected-direct", add_unexpected_direct_response,
             "transport_failure_unexpected_additional_response"),
            ("missing-call-id", remove_followup_call_id, "transport_failure_call_id_missing"),
            ("reversed-pair", reverse_fallback_order, "transport_failure_order_ambiguous"),
            ("attempt-number-gap", skip_fallback_attempt_number,
             "transport_failure_order_ambiguous"),
            ("auto-before-fallback", put_auto_response_before_fallback,
             "transport_failure_order_ambiguous"),
        )
        for name, mutate, expected_failure in cases:
            with self.subTest(case=name):
                receipts = _transport_failure_receipts_with_followups("transport-negative")
                mutate(receipts)
                result = capture_evidence._g9_runtime_assertions(profile, receipts)
                self.assertEqual(result["status"], "FAIL")
                self.assertIn(expected_failure, result["failures"])
                if name == "missing-call-id":
                    run = _g9_candidate_bundle(
                        self.root / "transport-missing-call-id",
                        "transport-failure", 4, trace_override=receipts,
                    )
                    evaluation = capture_evidence._evaluate_g9_run(run)["evaluation"]
                    self.assertEqual(evaluation["automated_status"], "BLOCKED")
                    self.assertIn(
                        "g9_response_receipts:invalid_or_duplicate_receipt_identity",
                        evaluation["problems"],
                    )

    def test_narrator_auto_applies_g4_state_contract_for_p1_and_p4(self):
        for party in (1, 4):
            with self.subTest(party=party):
                run = _g9_candidate_bundle(
                    self.root / ("narrator-g4-contract-p%d" % party), "narrator-auto", party
                )
                result = capture_evidence._evaluate_g9_run(run)
                self.assertEqual(result["evaluation"]["automated_status"], "READY_FOR_PRIMARY_REVIEW")
                self.assertIsNone(result["manifest"]["seed"]["active_encounter"])
                before, error = capture_evidence.load_bundle_json(
                    run, result["manifest"]["artifacts"]["before_snapshot"]
                )
                self.assertIsNone(error)
                self.assertEqual(before["records"]["selected_encounter"]["status"], "missing_id")
                self.assertIsNone(
                    before["records"]["party_tracker.json"]["worldConditions"]["activeCombatEncounter"]
                )

    def test_narrator_missing_or_tampered_step_state_is_not_ready(self):
        missing_run = _g9_candidate_bundle(
            self.root / "narrator-missing-step-state", "narrator-auto", 1
        )
        (missing_run / "snapshots" / "step-003-after.json").unlink()
        missing = capture_evidence._evaluate_g9_run(missing_run)["evaluation"]
        self.assertEqual(missing["automated_status"], "BLOCKED")

        tampered_run = _g9_candidate_bundle(
            self.root / "narrator-tampered-location", "narrator-auto", 4
        )
        state_path = tampered_run / "snapshots" / "step-003-after.json"
        state = json.loads(state_path.read_text(encoding="ascii"))
        state["records"]["party_tracker.json"]["worldConditions"]["currentLocationId"] = "CA04"
        state["g4_read_only_projection"]["currentLocationId"] = "CA04"
        state_path.write_text(
            json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="ascii"
        )
        self._refresh_artifact_hashes(tampered_run)
        tampered = capture_evidence._evaluate_g9_run(tampered_run)["evaluation"]
        self.assertEqual(tampered["automated_status"], "FAIL")
        self.assertTrue(any(
            failure.startswith("g9_narrator_persisted_location_or_actor_mismatch:step-003-after")
            for failure in tampered["failures"]
        ))

    def test_narrator_active_combat_is_a_failure(self):
        run = _g9_candidate_bundle(
            self.root / "narrator-active-combat", "narrator-auto", 1
        )
        manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
        self.assertIsNone(error)
        for reference in [manifest["artifacts"]["before_snapshot"],
                          manifest["artifacts"]["after_snapshot"]] + manifest["artifacts"]["step_snapshots"]:
            snapshot, snapshot_error = capture_evidence.load_bundle_json(run, reference)
            self.assertIsNone(snapshot_error)
            snapshot["records"]["party_tracker.json"]["worldConditions"][
                "activeCombatEncounter"] = "active-encounter"
            snapshot["records"]["selected_encounter"] = {
                "status": "ok", "encounterId": "active-encounter", "creatures": [],
            }
            snapshot["errors"] = [
                error for error in snapshot["errors"] if error != "selected_encounter"
            ]
            snapshot["mechanical_projection"] = capture_evidence._state_projection(snapshot)
            (run / reference).write_text(
                json.dumps(snapshot, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
                encoding="ascii",
            )
        manifest["seed"]["active_encounter"] = "active-encounter"
        before, _ = capture_evidence.load_bundle_json(run, manifest["artifacts"]["before_snapshot"])
        after, _ = capture_evidence.load_bundle_json(run, manifest["artifacts"]["after_snapshot"])
        manifest["snapshot_chain"]["before_run_sha256"] = capture_evidence.snapshot_digest(before)
        manifest["snapshot_chain"]["after_run_sha256"] = capture_evidence.snapshot_digest(after)
        manifest["artifact_sha256"] = capture_evidence.hash_artifacts(run, manifest["artifacts"])
        (run / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="ascii",
        )
        result = capture_evidence._evaluate_g9_run(run)["evaluation"]
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertTrue(any(
            failure.startswith("g9_narrator_active_combat_present:")
            for failure in result["failures"]
        ))

    def test_narrator_mira_echo_is_not_backend_dialogue(self):
        run = _g9_candidate_bundle(
            self.root / "narrator-mira-echo-only", "narrator-auto", 1
        )
        state_path = run / "snapshots" / "step-003-after.json"
        state = json.loads(state_path.read_text(encoding="ascii"))
        state["observation"]["actual_backend_outputs"] = list(state["observation"]["input_echoes"])
        state_path.write_text(
            json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="ascii"
        )
        self._refresh_artifact_hashes(run)
        result = capture_evidence._evaluate_g9_run(run)["evaluation"]
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertIn("g9_narrator_mira_backend_reply_missing_or_echo_only", result["failures"])

    def test_unexpected_fallback_on_narrator_auto_remains_a_failure(self):
        run = self.root / "narrator-auto-fallback"
        receipts = _g9_receipts("narrator-auto", run.name)
        receipts[0].update({
            "provider": "openai", "requested_model": "gpt-6-luna",
            "resolved_model": "gpt-6-luna", "fallback": True,
        })
        candidate = _g9_candidate_bundle(
            run, "narrator-auto", 1, trace_override=receipts
        )
        result = capture_evidence._evaluate_g9_run(candidate)["evaluation"]
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertIn("unexpected_auto_fallback", result["runtime_assertions"]["failures"])

    def test_combat_auto_still_requires_encounter_and_combat_checks(self):
        run = _g9_candidate_bundle(
            self.root / "combat-auto-missing-encounter", "combat-auto", 1
        )
        checks, error = capture_evidence.load_bundle_json(run, "checks.json")
        self.assertIsNone(error)
        check_by_id = {row["id"]: row for row in checks["checks"]}
        self.assertIs(check_by_id["selected_encounter_available"]["required"], True)
        self.assertEqual(check_by_id["selected_encounter_available"]["status"], "PASS")
        self.assertIs(check_by_id["mechanical_apply_outcomes"]["required"], True)
        self.assertIs(check_by_id["hp_delta_snapshot_reconciliation"]["required"], True)

        manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
        self.assertIsNone(error)
        for artifact_name in ("before_snapshot", "after_snapshot"):
            reference = manifest["artifacts"][artifact_name]
            snapshot, snapshot_error = capture_evidence.load_bundle_json(run, reference)
            self.assertIsNone(snapshot_error)
            party = snapshot["records"]["party_tracker.json"]
            party["worldConditions"]["activeCombatEncounter"] = ""
            snapshot["records"]["selected_encounter"] = {"status": "missing_id", "path": None}
            snapshot["errors"].append("selected_encounter")
            snapshot["mechanical_projection"] = capture_evidence._state_projection(snapshot)
            (run / reference).write_text(
                json.dumps(snapshot, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
                encoding="ascii",
            )
        manifest["seed"]["active_encounter"] = ""
        before, _ = capture_evidence.load_bundle_json(run, manifest["artifacts"]["before_snapshot"])
        after, _ = capture_evidence.load_bundle_json(run, manifest["artifacts"]["after_snapshot"])
        manifest["snapshot_chain"]["before_run_sha256"] = capture_evidence.snapshot_digest(before)
        manifest["snapshot_chain"]["after_run_sha256"] = capture_evidence.snapshot_digest(after)
        manifest["artifact_sha256"] = capture_evidence.hash_artifacts(run, manifest["artifacts"])
        (run / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="ascii",
        )
        result = capture_evidence._evaluate_g9_run(run)["evaluation"]
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertIn("g9_before_party_or_encounter_state_missing", result["problems"])

    def test_missing_and_duplicate_rows_are_blocked(self):
        paths = self._full_matrix()
        missing = capture_evidence.evaluate_g9_matrix(paths[:-1])
        self.assertEqual(missing["automated_status"], "BLOCKED")
        self.assertEqual(missing["missing_required_keys"], [EXPECTED_G9_ROWS[-1]])
        duplicate = capture_evidence.evaluate_g9_matrix(paths + [paths[0]])
        self.assertEqual(duplicate["automated_status"], "BLOCKED")
        self.assertEqual(duplicate["duplicate_keys"], [EXPECTED_G9_ROWS[0]])

    def test_synthetic_or_degraded_rows_cannot_be_ready(self):
        synthetic_paths = self._full_matrix({EXPECTED_G9_ROWS[0]: {"synthetic": True}})
        synthetic = capture_evidence.evaluate_g9_matrix(synthetic_paths)
        self.assertEqual(synthetic["automated_status"], "BLOCKED")
        self.assertIn(EXPECTED_G9_ROWS[0], synthetic["synthetic_keys"])

        degraded_paths = self._full_matrix({EXPECTED_G9_ROWS[1]: {"degraded": True}})
        degraded = capture_evidence.evaluate_g9_matrix(degraded_paths)
        self.assertEqual(degraded["automated_status"], "BLOCKED")
        self.assertIn(EXPECTED_G9_ROWS[1], degraded["not_ready_keys"])

    def test_missing_receipt_and_zero_fabricated_for_unpriced_cost_are_blocked(self):
        row_key = EXPECTED_G9_ROWS[0]
        scenario, party_text = row_key.split(":p")
        missing_path = self.root / "missing-receipt"
        missing_run = _g9_candidate_bundle(
            missing_path, scenario, int(party_text), trace_override=[]
        )
        missing = capture_evidence.evaluate_g9_matrix([missing_run])
        self.assertEqual(missing["automated_status"], "BLOCKED")
        self.assertIn(row_key, missing["not_ready_keys"])

        zero_path = self.root / "unpriced-zero"
        zero_receipts = _g9_receipts(scenario, zero_path.name)
        zero_receipts[0]["cost_usd"] = 0
        zero_run = _g9_candidate_bundle(
            zero_path, scenario, int(party_text), trace_override=zero_receipts
        )
        zero = capture_evidence.evaluate_g9_matrix([zero_run])
        self.assertEqual(zero["automated_status"], "BLOCKED")
        self.assertIn(row_key, zero["not_ready_keys"])

    def test_observed_auto_provider_mismatch_is_a_failure(self):
        row_key = EXPECTED_G9_ROWS[0]
        scenario, party_text = row_key.split(":p")
        path = self.root / "wrong-auto-provider"
        receipts = _g9_receipts(scenario, path.name)
        receipts[0]["provider"] = "openai"
        run = _g9_candidate_bundle(path, scenario, int(party_text), trace_override=receipts)
        result = capture_evidence.evaluate_g9_matrix([run])
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertIn(row_key, result["failed_keys"])

    def test_missing_owned_log_or_transcript_cannot_be_ready(self):
        row_key = EXPECTED_G9_ROWS[0]
        scenario, party_text = row_key.split(":p")
        path = self.root / "missing-capture-artifact"
        run = _g9_candidate_bundle(path, scenario, int(party_text))
        (run / "transcript.log").unlink()
        (run / "server.log").unlink()
        manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
        self.assertIsNone(error)
        manifest["artifacts"]["server_log"] = None
        (run / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="ascii"
        )
        result = capture_evidence.evaluate_g9_matrix([run])
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertIn(row_key, result["not_ready_keys"])

    def test_server_log_safety_rejects_encoded_and_case_varied_rate_api_keys(self):
        unsafe_logs = (
            b'[debug] https://v6.exchangerate-api.com:443 "GET '
            b'/v6/DUMMY_RATE_KEY_123/latest/USD HTTP/1.1" 200 12\n',
            b'https://V6.ExCHANGErate-API.COM/v6/DUMMY%5FRATE%5FKEY%5F456/latest/USD\n',
            b'https%3A%2F%2FV6.ExCHANGErate-API.com%2Fv6%2FDUMMY%255FRATE%255FKEY%255F789%2Flatest%2FUSD\n',
        )
        for index, raw in enumerate(unsafe_logs):
            with self.subTest(index=index):
                path = self.root / ("unsafe-rate-url-%d.log" % index)
                path.write_bytes(raw)
                safe, reason = capture_evidence.server_log_safety(path)
                self.assertFalse(safe)
                self.assertEqual(reason, "credential_or_configuration_value_detected")

        safe_path = self.root / "safe-unrelated-url.log"
        safe_path.write_bytes(b"https://example.com/v6/public/latest/USD\n")
        self.assertEqual(capture_evidence.server_log_safety(safe_path), (True, "safe"))

    def test_g9_finalizer_rejects_rate_api_key_url_without_replacing_evidence(self):
        scenario, party_text = EXPECTED_G9_ROWS[0].split(":p")
        run = _g9_candidate_bundle(
            self.root / "unsafe-rate-api-server-log", scenario, int(party_text)
        )
        lifecycle_source = self.root / "unsafe-rate-api-lifecycle.jsonl"
        lifecycle_source.write_bytes((run / "server_lifecycle.jsonl").read_bytes())
        server_source = self.root / "unsafe-rate-api-source.log"
        server_source.write_bytes(
            b'[debug] https://V6.EXCHANGERATE-API.COM:443 "GET '
            b'/v6/DUMMY_RATE_KEY_FINALIZER/latest/USD HTTP/1.1" 200 12\n'
        )
        original_server_log = (run / "server.log").read_bytes()
        original_manifest = (run / "manifest.json").read_bytes()

        with self.assertRaisesRegex(ValueError, "server log is unsafe"):
            capture_evidence.finalize_g9_capture_bundle(
                run, lifecycle_source, server_source
            )

        self.assertEqual((run / "server.log").read_bytes(), original_server_log)
        self.assertEqual((run / "manifest.json").read_bytes(), original_manifest)

    def test_finalizer_binds_complete_post_stop_logs_and_refreshes_hashes(self):
        scenario, party_text = EXPECTED_G9_ROWS[0].split(":p")
        run = _g9_candidate_bundle(
            self.root / "post-stop-finalization", scenario, int(party_text)
        )
        lifecycle_source = self.root / "lifecycle-after-stop.jsonl"
        lifecycle_source.write_bytes((run / "server_lifecycle.jsonl").read_bytes())
        server_source = self.root / "complete-server.log"
        server_source.write_text(
            "[server] sandbox listener ready on 8360\n[server] stopped cleanly\n",
            encoding="ascii",
        )
        result = capture_evidence.finalize_g9_capture_bundle(
            run, lifecycle_source, server_source
        )
        self.assertEqual(result["status"], "finalized")
        self.assertEqual((run / "server.log").read_bytes(), server_source.read_bytes())
        manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
        self.assertIsNone(error)
        self.assertEqual(
            manifest["artifact_sha256"]["server.log"],
            hashlib.sha256(server_source.read_bytes()).hexdigest(),
        )
        evaluation = capture_evidence._evaluate_g9_run(run)["evaluation"]
        self.assertEqual(evaluation["automated_status"], "READY_FOR_PRIMARY_REVIEW")

        rollback_run = _g9_candidate_bundle(
            self.root / "rollback-post-stop-finalization", "preferred-openai-rollback", 4
        )
        rollback_lifecycle = self.root / "rollback-lifecycle-after-stop.jsonl"
        rollback_lifecycle.write_bytes((rollback_run / "server_lifecycle.jsonl").read_bytes())
        rollback_server = self.root / "rollback-server.log"
        rollback_server.write_text("[server] direct OpenAI sandbox stopped\n", encoding="ascii")
        before_restart_server = self.root / "before-restart-server.log"
        before_restart_server.write_text("[server] OpenRouter sandbox stopped\n", encoding="ascii")
        capture_evidence.finalize_g9_capture_bundle(
            rollback_run, rollback_lifecycle, rollback_server, before_restart_server
        )
        self.assertEqual((rollback_run / "server.log").read_bytes(), rollback_server.read_bytes())
        self.assertEqual(
            (rollback_run / "server_before_rollback.log").read_bytes(),
            before_restart_server.read_bytes(),
        )
        rollback_evaluation = capture_evidence._evaluate_g9_run(rollback_run)["evaluation"]
        self.assertEqual(rollback_evaluation["automated_status"], "READY_FOR_PRIMARY_REVIEW")

    def test_declared_runtime_values_do_not_replace_receipt_observations(self):
        paths = self._full_matrix()
        result = capture_evidence.evaluate_g9_matrix(paths)
        self.assertEqual(result["automated_status"], "READY_FOR_PRIMARY_REVIEW")
        manifest, error = capture_evidence.load_bundle_json(paths[0], "manifest.json")
        self.assertIsNone(error)
        self.assertEqual(manifest["configuration"]["operator_declared"]["provider"], "openai")
        self.assertEqual(manifest["configuration"]["actual_runtime"]["provider"], "openrouter")

        manifest["configuration"]["actual_runtime"]["provider"] = "openai"
        (paths[0] / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="ascii"
        )
        contradicted = capture_evidence.evaluate_g9_matrix(paths)
        self.assertEqual(contradicted["automated_status"], "BLOCKED")
        self.assertIn(EXPECTED_G9_ROWS[0], contradicted["not_ready_keys"])

    def test_worktree_identity_mismatch_is_rejected(self):
        scenario, party_text = EXPECTED_G9_ROWS[0].split(":p")
        run = _g9_candidate_bundle(
            self.root / "wrong-worktree", scenario, int(party_text)
        )
        manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
        self.assertIsNone(error)
        manifest["g9"]["worktree_identity"]["root"] = str(self.root)
        (run / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="ascii"
        )
        result = capture_evidence.evaluate_g9_matrix([run])
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertIn(EXPECTED_G9_ROWS[0], result["failed_keys"])

    def test_failed_observed_assertion_is_fail(self):
        scenario, party_text = EXPECTED_G9_ROWS[2].split(":p")
        path = self.root / "failed-observation"
        events = _g9_receipts(scenario, path.name)
        events.append({"event_type": "combat_observation", "observation": "combat_apply_result",
                       "domain": "character", "operation": "hp_delta", "target": "Acheron",
                       "applied": False, "failure": "test-observed-failure"})
        run = _g9_candidate_bundle(path, scenario, int(party_text), trace_override=events)
        result = capture_evidence.evaluate_g9_matrix([run])
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertIn(EXPECTED_G9_ROWS[2], result["failed_keys"])

    def test_rollback_requires_exactly_one_observed_restart_and_no_reseed(self):
        row_key = "preferred-openai-rollback:p1"
        scenario, party_text = row_key.split(":p")
        path = self.root / "extra-restart"
        run_id = path.name
        events = [
            {"gate": "g9", "event": "prepare", "row_key": row_key,
             "run_id": run_id, "party_size": 1},
            {"gate": "g9", "event": "server_started", "row_key": row_key,
             "run_id": run_id, "party_size": 1, "posture": "openrouter", "server_pid": 101,
             "listener_pids": [101], "port": 8360,
             "cwd": str((capture_evidence.PROJECT_TMP / "combat_capture").resolve()),
             "ownership": "lsof_parent_pid_and_cwd"},
            {"gate": "g9", "event": "server_stopped", "row_key": row_key,
             "run_id": run_id, "party_size": 1, "server_pid": 101,
             "port": 8360, "remaining_listener_pids": []},
            {"gate": "g9", "event": "rollback_configured", "row_key": row_key,
             "run_id": run_id, "party_size": 1, "provider": "openai", "model": "gpt-6-luna",
             "reseed_after_rollback": False},
            {"gate": "g9", "event": "server_started", "row_key": row_key,
             "run_id": run_id, "party_size": 1, "posture": "openai", "server_pid": 202,
             "listener_pids": [202], "port": 8360,
             "cwd": str((capture_evidence.PROJECT_TMP / "combat_capture").resolve()),
             "ownership": "lsof_parent_pid_and_cwd"},
            {"gate": "g9", "event": "capture_completed", "row_key": row_key,
             "run_id": run_id, "party_size": 1, "driver_exit_status": 0},
            {"gate": "g9", "event": "server_stopped", "row_key": row_key,
             "run_id": run_id, "party_size": 1, "server_pid": 202,
             "port": 8360, "remaining_listener_pids": []},
            {"gate": "g9", "event": "server_started", "row_key": row_key,
             "run_id": run_id, "party_size": 1, "posture": "openai", "server_pid": 303,
             "listener_pids": [303], "port": 8360,
             "cwd": str((capture_evidence.PROJECT_TMP / "combat_capture").resolve()),
             "ownership": "lsof_parent_pid_and_cwd"},
        ]
        run = _g9_candidate_bundle(path, scenario, int(party_text), lifecycle_override=events)
        result = capture_evidence.evaluate_g9_matrix([run])
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertIn(row_key, result["failed_keys"])

    def test_rollback_marker_rejects_reseeding(self):
        row_key = "preferred-openai-rollback:p1"
        run = _g9_candidate_bundle(
            self.root / "rollback-reseeded", "preferred-openai-rollback", 1
        )
        manifest, error = capture_evidence.load_bundle_json(run, "manifest.json")
        self.assertIsNone(error)
        manifest["g9"]["sandbox_marker"]["reseed_after_rollback"] = True
        (run / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="ascii"
        )
        result = capture_evidence.evaluate_g9_matrix([run])
        self.assertEqual(result["automated_status"], "FAIL")
        self.assertIn(row_key, result["failed_keys"])


if __name__ == "__main__":
    unittest.main()
