# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for the fixed G10 Capture_Arena tooling."""

import copy
import contextlib
import hashlib
import io
import json
import sqlite3
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import capture_drive
from scripts import capture_evidence
from scripts import combat_latency_fixtures as fixtures
from scripts import seed_combat_capture


G10_TEST_SAVE_DIRECTORY = "modules/Capture_Arena/saved_games/save_20261030_041633"


def _receipt(run_id, number, prompt, cached, completion, provenance, cost,
             sdk_total_tokens=None):
    reported = cost if provenance == "actual" else None
    return {
        "event_type": "provider",
        "site": "llm_router",
        "run_id": run_id,
        "call_id": "call-%d" % number,
        "attempt_id": "attempt-%d" % number,
        "attempt_number": 1,
        "task": "dm_main",
        "provider": "openrouter",
        "requested_model": "openrouter/auto",
        "resolved_model": "provider/model-%d" % number,
        "retry": False,
        "fallback": False,
        "usage_available": True,
        "usage_complete": True,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "completion_tokens": completion,
        "sdk_total_tokens": (prompt + completion if sdk_total_tokens is None
                             else sdk_total_tokens),
        "provider_reported_cost_usd": reported,
        "cost_usd": cost,
        "cost_provenance": provenance,
        "cost_complete": provenance != "unpriced_unknown",
        "outcome": "response",
    }


def _usage_event(*, session_tokens=250, session_actual=0.001,
                 session_estimated=0.0005, session_known=0.0015,
                 week_tokens=250, debug_tokens=250):
    content = (
        "[SYSTEM] Usage:\n"
        "  Router: calls 3; tokens 250 (prompt 160, cached 30, completion 90); "
        "known cost $0.001500 USD; unpriced calls 1; cost coverage incomplete.\n"
        "  Session: tokens {session_tokens}; actual ${session_actual:.6f} USD; "
        "estimated ${session_estimated:.6f} USD; known cost ${session_known:.6f} USD; "
        "unpriced calls 1; cost coverage incomplete.\n"
        "  Rolling week: tokens {week_tokens}; actual $0.001000 USD; "
        "estimated $0.000500 USD; known cost $0.001500 USD; "
        "unpriced calls 1; cost coverage incomplete."
    ).format(session_tokens=session_tokens, session_actual=session_actual,
             session_estimated=session_estimated, session_known=session_known,
             week_tokens=week_tokens)
    return [{
        "source_event": "game_output",
        "source_route": "WebOutputCapture.game_output",
        "source_event_index": 7,
        "source_event_ts": 123.0,
        "driver_step": 4,
        "type": "narration",
        "content": content,
    }], [{
        "source_event": "token_update",
        "source_route": "socket.token_update",
        "source_event_index": 8,
        "ts": 124.0,
        "session_tokens": debug_tokens,
        "session_cost_actual_usd": 0.001,
        "session_cost_estimated_usd": 0.0005,
        "session_unpriced_calls": 1,
        "session_cost_complete": False,
        "week_tokens": week_tokens,
        "week_cost_actual_usd": 0.001,
        "week_cost_estimated_usd": 0.0005,
        "week_unpriced_calls": 1,
        "week_cost_complete": False,
    }]


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True), encoding="utf-8")


def _write_diary_database(database_path, entries, states):
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            "DROP TABLE IF EXISTS session_diary_entries;"
            "DROP TABLE IF EXISTS session_diary_state;"
        )
        connection.executescript(
            "CREATE TABLE session_diary_entries ("
            "diary_id INTEGER, status TEXT, save_id TEXT, draft_key TEXT, "
            "source_start_event_id INTEGER, source_end_event_id INTEGER, "
            "checkpoint_type TEXT, checkpoint_id TEXT);"
            "CREATE TABLE session_diary_state ("
            "state_id INTEGER, last_draft_event_id INTEGER, "
            "last_confirmed_event_id INTEGER, last_confirmed_save_id TEXT, "
            "last_draft_key TEXT);"
        )
        connection.executemany(
            "INSERT INTO session_diary_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(row[key] for key in (
                "diary_id", "status", "save_id", "draft_key", "source_start_event_id",
                "source_end_event_id", "checkpoint_type", "checkpoint_id",
            )) for row in entries],
        )
        connection.executemany(
            "INSERT INTO session_diary_state VALUES (?, ?, ?, ?, ?)",
            [tuple(row[key] for key in (
                "state_id", "last_draft_event_id", "last_confirmed_event_id",
                "last_confirmed_save_id", "last_draft_key",
            )) for row in states],
        )
        connection.commit()
    finally:
        connection.close()


def _g10_test_diary_evidence(phase, save_directory=G10_TEST_SAVE_DIRECTORY):
    save_id = "11111111-1111-4111-8111-111111111111"
    confirmed = {
        "diary_id": 1, "status": "confirmed", "save_id": save_id,
        "draft_key": None, "source_start_event_id": 1,
        "source_end_event_id": 10, "checkpoint_type": "save",
        "checkpoint_id": save_id,
    }
    saved_state = {
        "state_id": 1, "last_draft_event_id": 10,
        "last_confirmed_event_id": 10, "last_confirmed_save_id": save_id,
        "last_draft_key": None,
    }
    saved_projection = {"entries": [confirmed], "state": [saved_state]}
    saved_record = {
        "status": "captured", "source_database": "memory_db_package/memory.db",
        "projection": saved_projection,
        "projection_sha256": hashlib.sha256(json.dumps(
            saved_projection, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest(),
    }
    if phase == "complete":
        resumed_record = {"status": "not_applicable", "source_database": "data/memory.db"}
        evidence_status = "captured"
    else:
        draft = {
            "diary_id": 2, "status": "draft", "save_id": None,
            "draft_key": "active_draft", "source_start_event_id": 11,
            "source_end_event_id": 20, "checkpoint_type": None,
            "checkpoint_id": None,
        }
        resume_state = {
            "state_id": 1, "last_draft_event_id": 20,
            "last_confirmed_event_id": 10, "last_confirmed_save_id": save_id,
            "last_draft_key": "active_draft",
        }
        resumed_projection = {"entries": [confirmed, draft], "state": [resume_state]}
        resumed_record = {
            "status": "captured", "source_database": "data/memory.db",
            "projection": resumed_projection,
            "projection_sha256": hashlib.sha256(json.dumps(
                resumed_projection, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest(),
        }
        evidence_status = "captured"
    return {
        "schema_version": 1, "status": evidence_status, "phase": phase,
        "save_id": save_id, "save_directory": save_directory,
        "saved_checkpoint": saved_record, "resumed_state": resumed_record,
    }


def _rehash_diary_projection_record(record):
    projection = record["projection"]
    record["projection_sha256"] = hashlib.sha256(json.dumps(
        projection, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _rehash_g10_save_artifact(bundle, manifest):
    manifest.setdefault("artifact_sha256", {})["g10_save_state.json"] = hashlib.sha256(
        (bundle / "g10_save_state.json").read_bytes()
    ).hexdigest()


def _tracker_event(line_number, timestamp, call_number, prompt, completion,
                   sdk_total, provenance, cost):
    source_by_provenance = {
        "actual": "provider_reported", "estimated": "estimated", "unpriced": "unpriced",
    }
    return {
        "kind": "router_usage",
        "line_number": line_number,
        "source_line_sha256": hashlib.sha256(
            ("tracker-row-%d" % line_number).encode("ascii")
        ).hexdigest(),
        "timestamp_epoch": timestamp,
        "timestamp_basis": "local-naive",
        "call_id": "call-%d" % call_number,
        "attempt_id": "attempt-%d" % call_number,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "sdk_total_tokens": sdk_total,
        "cost_usd": cost,
        "cost_source": source_by_provenance[provenance],
        "cost_provenance": provenance,
        "cost_complete": provenance != "unpriced",
        "cost_estimate": provenance != "actual",
    }


def _tracker_snapshot(captured_at, events, *, present, source_bytes=0,
                      source_sha256=None, prefix=None):
    window_days = 7
    source = {
        "path": "telemetry_log.jsonl",
        "present": present,
        "bytes": source_bytes,
        "sha256": source_sha256 or hashlib.sha256(b"").hexdigest(),
        "device": 11 if present else None,
        "inode": 12 if present else None,
        "prefix": prefix,
    }
    cutoff = captured_at - window_days * 86400
    captured_local = datetime.fromtimestamp(captured_at)
    cutoff_local = datetime.fromtimestamp(cutoff)
    line_count = max((row["line_number"] for row in events), default=0)
    return {
        "status": "captured",
        "problems": [],
        "captured_at_local": captured_local.isoformat(),
        "captured_at_epoch": captured_at,
        "cutoff_local": cutoff_local.isoformat(),
        "cutoff_epoch": cutoff,
        "window_days": window_days,
        "line_count": line_count,
        "expired_count": 0,
        "expired_line_numbers": [],
        "expired_event_refs": [],
        "events": copy.deepcopy(events),
        "source": source,
    }


def _tracker_phase_fixture(phase, run_id, chain_id, seed_id, sandbox_id,
                           events, base_epoch, *, prior_link=None,
                           baseline_events=None, startup_sources=None):
    source_raw = ("\n".join(row["source_line_sha256"] for row in events) + "\n").encode(
        "ascii"
    )
    source_sha = hashlib.sha256(source_raw).hexdigest()
    source_bytes = len(source_raw)
    if phase == "complete":
        pre = _tracker_snapshot(base_epoch, [], present=False)
        post_prefix = {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest(),
                       "matches_expected": True}
        session_events = events
    else:
        baseline_events = events if baseline_events is None else baseline_events
        baseline_raw = ("\n".join(row["source_line_sha256"] for row in baseline_events) +
                        "\n").encode("ascii") if baseline_events else b""
        baseline_sha = hashlib.sha256(baseline_raw).hexdigest()
        baseline_bytes = len(baseline_raw)
        pre = _tracker_snapshot(base_epoch, baseline_events, present=True,
                                source_bytes=baseline_bytes, source_sha256=baseline_sha)
        post_prefix = {"bytes": baseline_bytes, "sha256": baseline_sha,
                       "matches_expected": True}
        session_events = [row for row in events if row.get("line_number", 0) > pre["line_count"]]
    post = _tracker_snapshot(
        base_epoch + 5, events, present=True, source_bytes=source_bytes,
        source_sha256=source_sha, prefix=post_prefix,
    )
    terminal = _tracker_snapshot(
        base_epoch + 6, events, present=True, source_bytes=source_bytes,
        source_sha256=source_sha,
        prefix={"bytes": source_bytes, "sha256": source_sha,
                "matches_expected": True},
    )
    artifact = {
        "schema_version": 1,
        "status": "captured",
        "phase": phase,
        "run_id": run_id,
        "chain_id": chain_id,
        "seed_id": seed_id,
        "sandbox_id": sandbox_id,
        "pre_run": pre,
        "post_usage": post,
        "post_shutdown": terminal,
        "prior_link": (prior_link if prior_link is not None else {
            "status": "fresh_sandbox_boundary",
            "baseline_source": "tracker_log_absent_after_seed",
            "baseline_numeric_totals": None,
        }),
        "usage_interval": {"command_sent_epoch": base_epoch + 2},
        "server_launch_epoch": base_epoch + 1,
    }
    section_events = session_events if phase == "resume" else events
    session_rollup = capture_evidence._g10_tracker_rollup(section_events)
    week_rollup = capture_evidence._g10_tracker_rollup(events)
    receipts = []
    receipt_events = events if phase == "complete" else session_events
    for row in receipt_events:
        if row["kind"] != "router_usage":
            continue
        provenance = row["cost_provenance"]
        receipt = {
            "call_id": row["call_id"],
            "attempt_id": row["attempt_id"],
            "prompt_tokens": row["prompt_tokens"],
            "cached_tokens": 0,
            "completion_tokens": row["completion_tokens"],
            "sdk_total_tokens": row["sdk_total_tokens"],
            "cost_label": "unpriced_unknown" if provenance == "unpriced" else provenance,
            "cost_usd": None if provenance == "unpriced" else row["cost_usd"],
            "outcome": "response",
        }
        receipt.update((startup_sources or {}).get(row["call_id"], {}))
        receipts.append(receipt)
    receipt_projection = {
        "status": "ok" if receipts else "none_observed",
        "receipts": receipts,
    }
    observed = {
        "sections": {
            "router": {
                "calls": len(receipts),
                "tokens": sum(row["prompt_tokens"] + row["completion_tokens"]
                              for row in receipts),
                "prompt_tokens": sum(row["prompt_tokens"] for row in receipts),
                "cached_tokens": sum(row.get("cached_tokens", 0) for row in receipts),
                "completion_tokens": sum(row["completion_tokens"] for row in receipts),
                "known_cost_usd": sum(row["cost_usd"] or 0 for row in receipts),
                "unpriced_calls": sum(row["cost_label"] == "unpriced_unknown"
                                      for row in receipts),
                "cost_coverage": ("complete" if all(
                    row["cost_label"] != "unpriced_unknown" for row in receipts
                ) else "incomplete"),
            },
            "session": session_rollup,
            "week": week_rollup,
        },
        "usage_events": [{"source_event_ts": base_epoch + 3}],
        "token_update": {"ts": base_epoch + 4},
    }
    projection = capture_evidence.project_g10_tracker_telemetry(
        artifact, observed, receipt_projection
    )
    usage_artifact = {
        "status": "ok" if projection.get("status") == "ok" else "BLOCKED",
        "observed": observed,
        "router_receipts": receipt_projection,
        "tracker_reconciliation": projection,
    }
    return artifact, usage_artifact


def _seed_saved_state(save_dir):
    roster = [fixtures.ONE_PC_NAME]
    encounter_id = "g10_encounter"
    _write_json(save_dir / "party_tracker.json", {
        "partyMembers": roster,
        "active_character": roster[0],
        "worldConditions": {
            "activeCombatEncounter": encounter_id,
            "currentLocation": "Waystone yard",
            "currentLocationId": "CA01",
        },
    })
    _write_json(save_dir / "modules" / "encounters" / ("encounter_%s.json" % encounter_id), {
        "encounterId": encounter_id,
        "combat_round": 1,
        "combat_phase": "pc",
        "creatures": [{"name": "Goblin", "currentHitPoints": 7,
                       "maxHitPoints": 7, "armorClass": 15,
                       "experience_points": 0}],
    })
    _write_json(save_dir / "characters" / "acheron.json", {
        "name": roster[0], "hitPoints": 10, "maxHitPoints": 10,
        "experience_points": 0, "currency": {"gp": 0},
        "inventory": [{"item_name": "Training sword", "quantity": 1}],
        "equipment": [],
    })
    _write_json(save_dir / "modules" / "conversation_history" / "conversation_history.json", [])
    (save_dir / "save_games").mkdir(parents=True, exist_ok=True)
    _write_json(save_dir / "save_metadata.json", {
        "description": "Manual save",
        "save_mode": "essential",
        "module": "Capture_Arena",
        "save_id": "11111111-1111-4111-8111-111111111111",
        "worldline_id": "22222222-2222-4222-8222-222222222222",
        "lineage": {
            "parent_save_id": None,
            "parent_worldline_id": None,
            "fork_origin_save_id": None,
            "created_after_restore": False,
        },
        "save_timestamp": "2026-10-30T00:00:00Z",
        "game_state": {
            "module": "Capture_Arena",
            "party_members": roster,
            "party_npcs": 0,
            "current_location": "Waystone yard",
            "current_area": "Capture Arena",
        },
        "system_info": {
            "save_format_version": "1.1",
            "created_by": "NeverEndingQuest Save System",
        },
    })
    save_id = "11111111-1111-4111-8111-111111111111"
    confirmed = {
        "diary_id": 1, "status": "confirmed", "save_id": save_id,
        "draft_key": None, "source_start_event_id": 1,
        "source_end_event_id": 10, "checkpoint_type": "save",
        "checkpoint_id": save_id,
    }
    saved_state = {
        "state_id": 1, "last_draft_event_id": 10,
        "last_confirmed_event_id": 10, "last_confirmed_save_id": save_id,
        "last_draft_key": None,
    }
    _write_diary_database(save_dir / "memory_db_package" / "memory.db",
                          [confirmed], [saved_state])
    draft = {
        "diary_id": 2, "status": "draft", "save_id": None,
        "draft_key": "active_draft", "source_start_event_id": 11,
        "source_end_event_id": 20, "checkpoint_type": None,
        "checkpoint_id": None,
    }
    resume_state = {
        "state_id": 1, "last_draft_event_id": 20,
        "last_confirmed_event_id": 10, "last_confirmed_save_id": save_id,
        "last_draft_key": "active_draft",
    }
    state_root = save_dir.parents[3]
    _write_diary_database(state_root / "data" / "memory.db",
                          [confirmed, draft], [resume_state])
    return roster, encounter_id


class _FakeG10Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _FakeG10Socket:
    """Provider-free Socket.IO peer that drives the real G10 session methods."""

    def __init__(self, game_state, party_size, failure=None):
        self.handlers = {}
        self.game_state = game_state
        self.party_size = party_size
        self.failure = failure
        self.inputs = []
        self.event_order = []
        self.connected = False
        self.combat_inputs = {
            row["input"] for row in fixtures.build_g5_script_steps(party_size)
        }
        self.saved_state = None

    def on(self, event, callback):
        self.handlers[event] = callback

    def connect(self, url, **kwargs):
        self.connected = True

    def emit(self, event, data=None):
        if event == "start_game":
            self.event_order.append("start_game")
            if self.failure == "event_without_ready":
                self.event_order.append("game_started")
                self.handlers["game_started"]({"message": "Game started successfully"})
                return
            self.event_order.append("game_output")
            self.handlers["game_output"]({
                "type": "system", "author": "Dungeon Master", "content": "Session ready."
            })
            self.event_order.append("status_update")
            self.handlers["status_update"]({"is_processing": False, "message": "ready"})
            if self.failure == "ready_without_game_started":
                return
            if self.failure == "delayed_game_started":
                time.sleep(0.06)
            self.event_order.append("game_started")
            message = ("Game started" if self.failure == "invalid_game_started"
                       else "Game started successfully")
            self.handlers["game_started"]({"message": message})
            return
        if event != "user_input":
            return
        text = data.get("input", "") if isinstance(data, dict) else ""
        self.event_order.append("user_input")
        self.inputs.append(text)
        if self.failure == "timeout" and text == fixtures.G10_NARRATION_INPUT:
            return
        if self.failure == "cap" and text == fixtures.G10_NARRATION_INPUT:
            self.handlers["game_output"]({"type": "narration", "content": "Narration began."})
            self.handlers["status_update"]({"is_processing": True, "message": "still processing"})
            return
        if text == fixtures.G10_NARRATION_INPUT:
            self.game_state["narration_count"] += 1
        elif text in self.combat_inputs:
            if not self.game_state["reward_applied"]:
                self.game_state["experience_points"] += 25
                self.game_state["currency_gp"] += 1
                self.game_state["inventory"].append({"name": "Goblin token", "quantity": 1})
                self.game_state["reward_applied"] = True
            self.game_state["combat_inputs"].append(text)
        elif text == "/save":
            self.saved_state = copy.deepcopy(self.game_state)
            save_directory = G10_TEST_SAVE_DIRECTORY
            if self.failure == "save_no_confirmation":
                save_directory = "modules/Capture_Arena/saved_games/save_../invalid"
            self.handlers["debug_output"]({
                "type": "debug",
                "content": ("[SYSTEM] Save game created successfully: %s" % save_directory),
            })
            self.handlers["status_update"]({"is_processing": False, "message": "ready"})
            return
        elif text == "/usage":
            usage_events, debug_updates = _usage_event()
            for usage in usage_events:
                self.handlers["game_output"]({
                    "type": usage["type"], "content": usage["content"],
                })
            for update in debug_updates:
                self.handlers["token_update"](update)
            self.handlers["status_update"]({"is_processing": False, "message": "idle"})
            return
        self.handlers["game_output"]({
            "type": "narration", "author": "Dungeon Master",
            "content": "The training scene continues.",
        })
        self.handlers["status_update"]({"is_processing": False, "message": "idle"})

    def disconnect(self):
        self.connected = False


class G10FixtureTests(unittest.TestCase):
    def test_fixed_matrix_has_one_complete_resume_pair_per_party_shape(self):
        self.assertEqual(fixtures.required_g10_row_keys(), (
            "full-session:complete:p1", "full-session:resume:p1",
            "full-session:complete:p4", "full-session:resume:p4",
        ))
        for party_size in fixtures.G10_PARTY_SIZES:
            complete = fixtures.build_gate_profile(
                "g10", "full-session", party_size, phase="complete"
            )
            resume = fixtures.build_gate_profile(
                "g10", "full-session", party_size, phase="resume"
            )
            self.assertEqual(complete["row_key"], fixtures.g10_row_key("complete", party_size))
            self.assertEqual(resume["row_key"], fixtures.g10_row_key("resume", party_size))
            self.assertEqual(complete["fixture"]["save_command"], "/save")
            self.assertEqual(complete["fixture"]["steps"][-2]["input"], "/save")
            self.assertGreater(len(complete["fixture"]["steps"]), 2)
            self.assertEqual(resume["fixture"]["steps"], [{
                "label": "resumed usage report", "input": "/usage",
                "character": None, "kind": "usage",
            }])
            self.assertEqual(complete["seed"], resume["seed"])
            self.assertEqual(complete["applicability"]["script_sha256"],
                             resume["applicability"]["script_sha256"])
            self.assertEqual(complete["max_requests"],
                             complete["max_steps"] + 1 + complete["max_active_switches"])

    def test_g10_rejects_unbounded_profiles(self):
        for party, phase in ((2, "complete"), (1, "replay"), (4, "")):
            with self.assertRaises(ValueError):
                fixtures.build_gate_profile("g10", "full-session", party, phase=phase)
        with self.assertRaises(ValueError):
            fixtures.build_gate_profile("g10", "combat-smoke", 1, phase="complete")
        self.assertEqual(capture_evidence.matrix_key("full-session", 4, phase="resume"),
                         "full-session:resume:p4")


class G10DriverExecutionTests(unittest.TestCase):
    @staticmethod
    def _session(root, party_size, phase, game_state, socket):
        roster = ([fixtures.ONE_PC_NAME] if party_size == 1 else list(fixtures.PC_NAMES))
        args = type("Args", (), {
            "url": "http://localhost:8360", "party": party_size,
            "transcript": str(root / (phase + ".log")),
            "trace_src": str(root / "trace.jsonl"), "trace_dst": None,
            "start_timeout": 0.05, "turn_timeout": 0.04,
            "turn_quiet_seconds": 0.001, "settle_seconds": 0,
            "init_roll": 15, "scenario": fixtures.G10_SCENARIO,
            "branch": None, "phase": phase, "gate": "g10",
            "run_dir": None, "state_root": None,
        })()
        active_requests = []

        def fake_post(url, *, json, timeout):
            active_requests.append(json["character"])
            return _FakeG10Response({"success": True})

        def fake_get(url, *, timeout):
            return _FakeG10Response({"partyMembers": roster})

        session = capture_drive.CaptureSession(
            args, socket_client=socket, http_post=fake_post, http_get=fake_get
        )
        return session, active_requests

    def test_complete_and_resume_execute_socket_scripts_without_duplicate_state(self):
        with tempfile.TemporaryDirectory(prefix="g10-driver-", dir="tmp") as temp:
            root = Path(temp)
            with patch.object(capture_drive, "POLL_INTERVAL_SECONDS", 0.001):
                for party_size in fixtures.G10_PARTY_SIZES:
                    with self.subTest(party_size=party_size):
                        game_state = {
                            "narration_count": 0, "combat_inputs": [],
                            "inventory": [{"name": "Training sword", "quantity": 1}],
                            "experience_points": 0, "currency_gp": 0,
                            "reward_applied": False,
                        }
                        complete_socket = _FakeG10Socket(game_state, party_size)
                        complete, active_requests = self._session(
                            root, party_size, "complete", game_state, complete_socket
                        )
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                complete.open_transcript()
                                complete.connect()
                                self.assertTrue(complete.start_session())
                                self.assertEqual(
                                    complete.run_named_scenario(fixtures.G10_SCENARIO),
                                    capture_drive.EXIT_OK,
                                )
                        finally:
                            complete.disconnect()
                            complete.close_transcript()

                        profile = fixtures.build_gate_profile(
                            "g10", fixtures.G10_SCENARIO, party_size, phase="complete"
                        )
                        expected_inputs = [row["input"] for row in profile["fixture"]["steps"]]
                        self.assertEqual(complete_socket.inputs, expected_inputs)
                        self.assertLess(complete_socket.event_order.index("status_update"),
                                        complete_socket.event_order.index("game_started"))
                        self.assertLess(complete_socket.event_order.index("game_started"),
                                        complete_socket.event_order.index("user_input"))
                        self.assertEqual(complete.start_readiness["game_started"]["status"],
                                         "valid")
                        self.assertEqual(complete.start_readiness["game_started"]["source_route"],
                                         "socket.game_started")
                        self.assertIsInstance(
                            complete.start_readiness["game_started"]["event_epoch_ms"], float
                        )
                        self.assertIsInstance(
                            complete.start_readiness["game_started"]["event_monotonic_ms"], float
                        )
                        self.assertEqual(complete.g10_observation["status"], "captured")
                        self.assertEqual(complete.g10_observation["narration_step"], 1)
                        self.assertEqual(complete.g10_observation["combat_steps"],
                                         len(fixtures.build_g5_script_steps(party_size)))
                        self.assertEqual(complete.g10_observation["save_step"], len(expected_inputs) - 1)
                        self.assertEqual(complete.g10_observation["usage_step"], len(expected_inputs))
                        self.assertEqual(complete.g10_observation["save_completion"], {
                            "status": "captured",
                            "source": "debug_output",
                            "save_directory": G10_TEST_SAVE_DIRECTORY,
                        })
                        self.assertEqual(complete.timeout_count, 0)
                        self.assertEqual(complete_socket.saved_state, game_state)
                        self.assertEqual(game_state["experience_points"], 25)
                        self.assertEqual(game_state["currency_gp"], 1)
                        self.assertEqual(game_state["inventory"][-1], {
                            "name": "Goblin token", "quantity": 1,
                        })
                        self.assertEqual(active_requests[0], fixtures.ONE_PC_NAME if party_size == 1
                                         else fixtures.PC_NAMES[0])
                        self.assertIn("/save", complete_socket.inputs)
                        self.assertEqual(complete_socket.inputs[-1], "/usage")
                        usage = complete.g10_observation["usage"]
                        self.assertEqual(usage["status"], "captured")
                        self.assertTrue(usage["debug_update_observed"])
                        projection = capture_evidence.project_g10_usage_observations(
                            usage["usage_events"], usage["debug_token_updates"]
                        )
                        self.assertEqual(projection["status"], "ok", projection["problems"])
                        self.assertEqual(projection["source_events"][0]["source_route"],
                                         "WebOutputCapture.game_output")
                        self.assertEqual(projection["source_events"][0]["driver_step"],
                                         complete.g10_observation["usage_step"])
                        self.assertNotIn("author", projection["source_events"][0])
                        self.assertNotIn("usage_lines", projection)
                        self.assertEqual(usage["usage_events"][0]["content"].splitlines()[0],
                                         "[SYSTEM] Usage:")
                        debug = usage["debug_token_updates"][0]
                        self.assertEqual(debug["session_cost_actual_usd"], 0.001)
                        self.assertEqual(debug["session_cost_estimated_usd"], 0.0005)
                        self.assertEqual(debug["session_unpriced_calls"], 1)
                        self.assertFalse(debug["session_cost_complete"])
                        self.assertEqual(debug["week_unpriced_calls"], 1)
                        self.assertFalse(debug["week_cost_complete"])

                        retained_state = copy.deepcopy(complete_socket.saved_state)
                        resume_socket = _FakeG10Socket(retained_state, party_size)
                        resume, resume_active_requests = self._session(
                            root, party_size, "resume", retained_state, resume_socket
                        )
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                resume.open_transcript()
                                resume.connect()
                                self.assertTrue(resume.start_session(require_ready_quiet=True))
                                self.assertEqual(
                                    resume.run_named_scenario(fixtures.G10_SCENARIO),
                                    capture_drive.EXIT_OK,
                                )
                        finally:
                            resume.disconnect()
                            resume.close_transcript()
                        self.assertEqual(resume_socket.inputs, ["/usage"])
                        self.assertLess(resume_socket.event_order.index("game_started"),
                                        resume_socket.event_order.index("user_input"))
                        self.assertEqual(resume_active_requests, [])
                        self.assertEqual(resume.g10_observation["gameplay_inputs_sent"], 0)
                        self.assertEqual(resume.g10_observation["usage"]["status"], "captured")
                        self.assertEqual(retained_state, complete_socket.saved_state)

    def test_startup_barrier_rejects_missing_invalid_delayed_and_unready_events(self):
        cases = (
            ("ready_without_game_started", "game_started_timeout", "missing"),
            ("event_without_ready", "loop_readiness_timeout", "valid"),
            ("invalid_game_started", "game_started_invalid", "invalid"),
            ("delayed_game_started", "game_started_delayed", "delayed"),
        )
        with tempfile.TemporaryDirectory(prefix="g10-startup-barrier-", dir="tmp") as temp:
            root = Path(temp)
            with patch.object(capture_drive, "POLL_INTERVAL_SECONDS", 0.001):
                for failure, expected_status, event_status in cases:
                    with self.subTest(failure=failure):
                        state = {"narration_count": 0, "combat_inputs": [],
                                 "inventory": [], "experience_points": 0,
                                 "currency_gp": 0, "reward_applied": False}
                        socket = _FakeG10Socket(state, 1, failure=failure)
                        session, active_requests = self._session(
                            root, 1, "resume", state, socket
                        )
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                session.open_transcript()
                                session.connect()
                                self.assertFalse(session.start_session(require_ready_quiet=True))
                        finally:
                            session.disconnect()
                            session.close_transcript()
                        self.assertEqual(session.start_readiness["status"], expected_status)
                        self.assertEqual(session.start_readiness["game_started"]["status"],
                                         event_status)
                        self.assertEqual(socket.inputs, [])
                        self.assertEqual(active_requests, [])
                        self.assertEqual(session.steps_sent, 0)
                        if failure == "ready_without_game_started":
                            self.assertEqual(session.health_read_attempts, 1)
                        elif failure == "event_without_ready":
                            self.assertEqual(session.health_read_attempts, 0)

    def test_save_requires_authoritative_success_even_when_ready_and_a_directory_exists(self):
        with tempfile.TemporaryDirectory(prefix="g10-save-no-confirmation-", dir="tmp") as temp:
            root = Path(temp)
            state = {"narration_count": 0, "combat_inputs": [],
                     "inventory": [], "experience_points": 0,
                     "currency_gp": 0, "reward_applied": False}
            socket = _FakeG10Socket(state, 1, failure="save_no_confirmation")
            session, _ = self._session(root, 1, "complete", state, socket)
            profile = fixtures.build_gate_profile(
                "g10", fixtures.G10_SCENARIO, 1, phase="complete"
            )
            try:
                with patch.object(capture_drive, "POLL_INTERVAL_SECONDS", 0.001):
                    with contextlib.redirect_stdout(io.StringIO()):
                        session.open_transcript()
                        session.connect()
                        self.assertTrue(session.start_session())
                        with self.assertRaises(capture_drive.DriverConnectionError):
                            session.run_named_scenario(fixtures.G10_SCENARIO)
            finally:
                session.disconnect()
                session.close_transcript()
            self.assertIsNotNone(socket.saved_state)
            self.assertEqual(socket.inputs[-1], "/save")
            self.assertNotIn("/usage", socket.inputs)
            self.assertEqual(session.timeout_count, 1)
            self.assertEqual(session.g10_observation["status"], "pending")

    def test_turn_timeout_and_processing_cap_fail_stop_before_later_inputs(self):
        with tempfile.TemporaryDirectory(prefix="g10-driver-stop-", dir="tmp") as temp:
            root = Path(temp)
            with patch.object(capture_drive, "POLL_INTERVAL_SECONDS", 0.001):
                for failure in ("timeout", "cap"):
                    with self.subTest(failure=failure):
                        state = {"narration_count": 0, "combat_inputs": [],
                                 "inventory": [], "experience_points": 0,
                                 "currency_gp": 0, "reward_applied": False}
                        socket = _FakeG10Socket(state, 1, failure=failure)
                        session, _ = self._session(root, 1, "complete", state, socket)
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                session.open_transcript()
                                session.connect()
                                self.assertTrue(session.start_session())
                                with self.assertRaises(capture_drive.DriverConnectionError):
                                    session.run_named_scenario(fixtures.G10_SCENARIO)
                        finally:
                            session.disconnect()
                            session.close_transcript()
                        self.assertEqual(socket.inputs, [fixtures.G10_NARRATION_INPUT])
                        self.assertEqual(session.steps_sent, 1)
                        self.assertEqual(session.timeout_count, 1 if failure == "timeout" else 0)
                        self.assertEqual(session.step_caps_reached, 1 if failure == "cap" else 0)

    def test_fixed_step_cap_fails_before_emitting_out_of_bound_combat_input(self):
        with tempfile.TemporaryDirectory(prefix="g10-driver-step-cap-", dir="tmp") as temp:
            root = Path(temp)
            state = {"narration_count": 0, "combat_inputs": [],
                     "inventory": [], "experience_points": 0, "currency_gp": 0,
                     "reward_applied": False}
            socket = _FakeG10Socket(state, 1)
            session, _ = self._session(root, 1, "complete", state, socket)
            profile = fixtures.build_gate_profile("g10", fixtures.G10_SCENARIO, 1,
                                                   phase="complete")
            profile["max_steps"] = 1
            session.capture_profile = profile
            try:
                with patch.object(capture_drive, "POLL_INTERVAL_SECONDS", 0.001):
                    with contextlib.redirect_stdout(io.StringIO()):
                        session.register_handlers()
                        session.connected = True
                        self.assertTrue(session.start_session())
                        with self.assertRaises(capture_drive.DriverConnectionError):
                            session.run_g10_scenario(profile)
            finally:
                session.disconnect()
                session.close_transcript()
            self.assertEqual(socket.inputs, [fixtures.G10_NARRATION_INPUT])
            self.assertEqual(session.steps_sent, 1)
            self.assertEqual(session.blocked_step_attempts, 1)


class G10SeederLifecycleTests(unittest.TestCase):
    def test_prepare_is_complete_only_and_resume_reuses_the_same_seeded_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="g10-seeder-", dir="tmp") as temp:
            scratch = Path(temp)
            project_root = scratch / "project"
            project_root.mkdir()
            project_tmp = project_root / "tmp"
            sandbox_root = project_tmp / "combat_capture"
            complete_run = project_tmp / "router-rollout" / "g10" / "complete-p1"
            resume_run = project_tmp / "router-rollout" / "g10" / "resume-p1"
            complete_relative = "tmp/router-rollout/g10/complete-p1"
            chain_id = "chain-g10-seeder-p1"
            seed_calls = []

            def create_sandbox_dirs():
                sandbox_root.mkdir(parents=True, exist_ok=True)

            def seed_party(reference, party_names, party_size, profile):
                seed_calls.append((tuple(party_names), party_size))
                (sandbox_root / "party_tracker.json").write_text(json.dumps({
                    "partyMembers": party_names,
                    "worldConditions": {"activeCombatEncounter": "g10_encounter"},
                }), encoding="ascii")
                return "g10_encounter"

            with patch.multiple(
                    seed_combat_capture,
                    PROJECT_ROOT=project_root,
                    SANDBOX_ROOT=sandbox_root,
                    SANDBOX_DISPLAY="tmp/combat_capture",
                    _hash_installed_sentinels=lambda: {"sentinel": "stable"},
                    _copy_runtime=lambda: 1,
                    _patch_sandbox_config=lambda: None,
                    _patch_sandbox_model_config=lambda gate, scenario_id: None,
                    _read_capture_arena_reference=lambda: {
                        "module": "Capture_Arena", "area_id": "CTR001",
                        "area_name": "Capture Arena", "start_location_id": "CA01",
                        "start_location_name": "Waystone Gate",
                    },
                    _create_sandbox_dirs=create_sandbox_dirs,
                    _seed_party=seed_party,
                    _directory_size_bytes=lambda path: 0,
                    _venv_python_display=lambda: ".venv/bin/python",
            ), patch.object(capture_evidence, "PROJECT_ROOT", project_root), \
                    patch.object(capture_evidence, "PROJECT_TMP", project_tmp), \
                    patch.object(capture_evidence, "G10_RUN_ROOT",
                                 project_tmp / "router-rollout" / "g10"), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(seed_combat_capture.prepare(
                    1, scenario_id=fixtures.G10_SCENARIO, phase="complete", gate="g10",
                    run_dir=complete_relative, chain_id=chain_id,
                ), 0)
                marker_path = sandbox_root / ".g10-capture.json"
                marker_before = marker_path.read_bytes()
                tracker_before = (sandbox_root / "party_tracker.json").read_bytes()
                marker = json.loads(marker_before.decode("ascii"))
                complete_run.mkdir(parents=True)
                (complete_run / "manifest.json").write_text(json.dumps({
                    "gate": "g10", "party": {"size": 1},
                    "g10": {
                        "phase": "complete", "chain_id": chain_id,
                        "seed_id": marker["seed_id"],
                        "lifecycle": {"status": "finalized"},
                        "save_state": {"status": "captured"},
                        "usage": {"status": "ok"},
                    },
                }), encoding="ascii")

                complete_profile = fixtures.build_gate_profile(
                    "g10", fixtures.G10_SCENARIO, 1, phase="complete"
                )
                complete_args = type("Args", (), {
                    "state_root": str(sandbox_root), "chain_id": chain_id,
                    "run_dir": str(complete_run),
                })()
                capture_drive._validate_g10_sandbox(complete_profile, complete_args)

                resume_profile = fixtures.build_gate_profile(
                    "g10", fixtures.G10_SCENARIO, 1, phase="resume"
                )
                resume_args = type("Args", (), {
                    "state_root": str(sandbox_root), "chain_id": chain_id,
                    "run_dir": str(resume_run),
                })()
                capture_drive._validate_g10_sandbox(resume_profile, resume_args)
                self.assertEqual(complete_args.g10_marker_observation["seed_id"],
                                 resume_args.g10_marker_observation["seed_id"])
                self.assertEqual(resume_args.g10_marker_observation["complete_run_dir"],
                                 complete_relative)

                with self.assertRaisesRegex(ValueError, "prepares only --phase complete"):
                    seed_combat_capture.prepare(
                        1, scenario_id=fixtures.G10_SCENARIO, phase="resume", gate="g10",
                        run_dir="tmp/router-rollout/g10/resume-p1", chain_id=chain_id,
                    )

                self.assertEqual(seed_calls, [((fixtures.ONE_PC_NAME,), 1)])
                self.assertEqual(marker_path.read_bytes(), marker_before)
                self.assertEqual((sandbox_root / "party_tracker.json").read_bytes(), tracker_before)


class G10ResumeStartupReceiptTests(unittest.TestCase):
    def _resume_startup_fixture(self):
        sources = [
            ("session_diary_checkpoint_summary", "llm_router", "summaries",
             "core/memory/session_diary.py:_generate_checkpoint_summary"),
            ("combat_reengage", "combat_reengage", "combat_main", None),
        ]
        events = []
        positioned = []
        tracker_rows = []
        for index, (source, site, task, source_id) in enumerate(sources, 1):
            call_number = index + 20
            event = _receipt(
                "g10-resume-test", call_number, 100 * index, 10 * index,
                20 * index, "actual", 0.001 * index,
            )
            event.update(site=site, task=task, endpoint=None)
            if source_id is not None:
                event["source_id"] = source_id
            start = 110 + 20 * (index - 1)
            positioned.append(dict(event, _source_byte_start=start,
                                   _source_byte_end=start + 8))
            events.append(event)
            tracker_rows.append({
                "kind": "router_usage", "line_number": 10 + index,
                "attempt_id": event["attempt_id"], "call_id": event["call_id"],
                "timestamp_epoch": 160 + index * 10,
                "prompt_tokens": event["prompt_tokens"],
                "completion_tokens": event["completion_tokens"],
                "sdk_total_tokens": event["sdk_total_tokens"],
                "cost_source": "provider_reported", "cost_usd": event["cost_usd"],
            })
        receipt_projection = capture_evidence.project_g10_receipts(
            events, "g10-resume-test"
        )
        profile = {"phase": "resume", "fixture": {"steps": [{"kind": "usage"}]}}
        manifest = {
            "trace_span": {"offset_before_bytes": 100},
            "trace_start_offset": {"source_byte_offset": 100},
            "g10": {"driver_observation": {"usage_step": 1}},
        }
        step_rows = [{
            "before": {"observation": {"runtimeTrace": {
                "status": "captured", "offset_bytes": 200,
            }}},
            "after": {"observation": {"runtimeTrace": {
                "status": "captured", "offset_bytes": 250,
            }}},
        }]
        tracker = {
            "pre_run": {"line_count": 10},
            "post_usage": {"events": tracker_rows},
            "server_launch_epoch": 150,
            "usage_interval": {"command_sent_epoch": 195},
        }
        return (profile, manifest, step_rows, receipt_projection, positioned,
                tracker, {"status": "none_observed", "receipts": []})

    def _validate_resume_startup(self, fixture):
        return capture_evidence._validate_g10_resume_startup_receipts(*fixture[:4],
            fixture[4], fixture[6], fixture[5])

    def test_resume_accepts_exactly_the_attributed_startup_receipts(self):
        fixture = self._resume_startup_fixture()
        result = self._validate_resume_startup(fixture)
        self.assertEqual(result["status"], "ok", result)
        usage_start = fixture[2][0]["before"]["observation"]["runtimeTrace"]["offset_bytes"]
        self.assertTrue(all(row["_source_byte_end"] <= usage_start for row in fixture[4]))
        self.assertEqual(fixture[6], {"status": "none_observed", "receipts": []})
        self.assertGreater(fixture[5]["usage_interval"]["command_sent_epoch"],
                           fixture[5]["server_launch_epoch"])
        self.assertEqual([row["source"] for row in result["receipts"]], [
            "session_diary_checkpoint_summary", "combat_reengage",
        ])
        self.assertEqual(result["receipts"][1]["source_id"] if "source_id" in
                         result["receipts"][1] else None, None)

    def test_resume_rejects_duplicate_semantics_unapproved_sources_and_usage_calls(self):
        duplicate = list(self._resume_startup_fixture())
        duplicate_events = duplicate[4]
        duplicate_receipt = copy.deepcopy(duplicate_events[0])
        duplicate_receipt["call_id"] = "call-duplicate"
        duplicate_receipt["attempt_id"] = "attempt-duplicate"
        duplicate_receipt["_source_byte_start"] = 150
        duplicate_receipt["_source_byte_end"] = 158
        duplicate_events[1] = duplicate_receipt
        duplicate[3] = capture_evidence.project_g10_receipts(
            [duplicate_receipt, duplicate[4][0]], "g10-resume-test"
        )
        duplicate[5]["post_usage"]["events"][1].update(
            call_id=duplicate_receipt["call_id"], attempt_id=duplicate_receipt["attempt_id"],
            prompt_tokens=duplicate_receipt["prompt_tokens"],
            completion_tokens=duplicate_receipt["completion_tokens"],
            sdk_total_tokens=duplicate_receipt["sdk_total_tokens"],
            cost_usd=duplicate_receipt["cost_usd"],
        )
        result = self._validate_resume_startup(duplicate)
        self.assertIn("g10_resume_startup_semantic_call_duplicated", result["failures"])

        unapproved = list(self._resume_startup_fixture())
        unapproved[4][1]["site"] = "combat_main"
        unapproved[3] = capture_evidence.project_g10_receipts(
            [unapproved[4][0], unapproved[4][1]], "g10-resume-test"
        )
        result = self._validate_resume_startup(unapproved)
        self.assertIn("g10_resume_startup_provider_source_unapproved_or_missing",
                      result["failures"])

        usage_call = list(self._resume_startup_fixture())
        usage_call[6] = {"status": "ok", "receipts": [{"attempt_id": "usage-attempt"}]}
        result = self._validate_resume_startup(usage_call)
        self.assertIn("g10_usage_command_made_or_failed_to_exclude_provider_request",
                      result["failures"])

    def test_resume_rejects_receipts_inside_usage_span_and_telemetry_mismatch(self):
        inside_usage = list(self._resume_startup_fixture())
        inside_usage[4][1]["_source_byte_start"] = 210
        inside_usage[4][1]["_source_byte_end"] = 220
        result = self._validate_resume_startup(inside_usage)
        self.assertIn("g10_usage_command_made_or_failed_to_exclude_provider_request",
                      result["failures"])

        mismatched = list(self._resume_startup_fixture())
        mismatched[5]["post_usage"]["events"][0]["cost_usd"] += 0.1
        result = self._validate_resume_startup(mismatched)
        self.assertIn("g10_resume_startup_receipt_tracker_fields_mismatch",
                      result["failures"])


class G10UsageEvidenceTests(unittest.TestCase):
    def test_usage_debug_and_actual_estimated_unpriced_receipts_reconcile(self):
        usage_events, token_updates = _usage_event(
            session_tokens=249, week_tokens=900, debug_tokens=249)
        usage = capture_evidence.project_g10_usage_observations(usage_events, token_updates)
        receipts = capture_evidence.project_g10_receipts([
            _receipt("g10-test", 1, 100, 20, 40, "actual", 0.001,
                     sdk_total_tokens=139),
            _receipt("g10-test", 2, 50, 10, 30, "estimated", 0.0005),
            _receipt("g10-test", 3, 10, 0, 20, "unpriced_unknown", None,
                     sdk_total_tokens=30),
        ], "g10-test")
        self.assertEqual(usage["status"], "ok", usage["problems"])
        self.assertEqual(usage["source_events"][0]["source_event_index"], 7)
        self.assertNotIn("content", usage["source_events"][0])
        self.assertEqual(usage["sections"]["router"]["tokens"], 250)
        self.assertEqual(usage["sections"]["session"]["tokens"], 249)
        self.assertEqual(usage["sections"]["week"]["tokens"], 900)
        self.assertEqual(
            capture_evidence.project_g10_usage_observations(usage["usage_events"], token_updates),
            usage,
        )
        self.assertEqual(receipts["status"], "ok", receipts.get("reason"))
        self.assertEqual(receipts["receipts"][0]["sdk_total_tokens"], 139)
        self.assertEqual(capture_evidence.reconcile_g10_router_usage(usage, receipts), [])

    def test_receipt_projection_accepts_registered_encounter_update_attempts_once(self):
        tasks = ["combat_main", "combat_main", "summaries", "encounter_update",
                 "combat_main", "summaries", "encounter_update"]
        events = [
            _receipt("g10-test", index, 10 + index, 0, 5, "actual", 0.001)
            for index, _task in enumerate(tasks, 1)
        ]
        for event, task in zip(events, tasks):
            event["task"] = task
        # Retry attempts may share a logical call ID, but each response attempt
        # must retain a distinct attempt ID and be projected exactly once.
        events[1]["call_id"] = events[0]["call_id"]

        result = capture_evidence.project_g10_receipts(events, "g10-test")

        self.assertEqual(result["status"], "ok", result.get("reason"))
        self.assertEqual(result["counts"]["response_receipts"], 7)
        self.assertEqual([row["task"] for row in result["receipts"]], tasks)
        self.assertEqual(len({row["attempt_id"] for row in result["receipts"]}), 7)

    def test_receipt_projection_preserves_allowlisted_source_and_blocks_unknown(self):
        allowed = _receipt("g10-test", 1, 10, 0, 5, "actual", 0.001)
        allowed["task"] = "summaries"
        allowed["source_id"] = "core/memory/story_so_far_compiler.py:_generate_story_text_with_llm"

        result = capture_evidence.project_g10_receipts([allowed], "g10-test")

        self.assertEqual(result["status"], "ok", result.get("reason"))
        self.assertEqual(result["receipts"][0]["source_id"], allowed["source_id"])

        unknown = copy.deepcopy(allowed)
        unknown["source_id"] = "https://provider.invalid/private?query=user-data"
        result = capture_evidence.project_g10_receipts([unknown], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "invalid_g10_receipt_source_id")

    def test_receipt_projection_rejects_unregistered_tasks_and_malformed_identity(self):
        unknown_task = _receipt("g10-test", 1, 10, 0, 5, "actual", 0.001)
        unknown_task["task"] = "unregistered_task"
        missing_task = _receipt("g10-test", 2, 10, 0, 5, "actual", 0.001)
        del missing_task["task"]
        missing_call_id = _receipt("g10-test", 5, 10, 0, 5, "actual", 0.001)
        del missing_call_id["call_id"]
        missing_attempt_id = _receipt("g10-test", 6, 10, 0, 5, "actual", 0.001)
        del missing_attempt_id["attempt_id"]
        duplicate_attempt = _receipt("g10-test", 3, 10, 0, 5, "actual", 0.001)
        duplicate_attempt_other_call = _receipt(
            "g10-test", 4, 10, 0, 5, "actual", 0.001)
        duplicate_attempt_other_call["attempt_id"] = duplicate_attempt["attempt_id"]

        for label, events in (
                ("unknown task", [unknown_task]),
                ("missing task", [missing_task]),
                ("missing call ID", [missing_call_id]),
                ("missing attempt ID", [missing_attempt_id]),
                ("duplicate attempt ID", [duplicate_attempt, duplicate_attempt_other_call])):
            with self.subTest(label=label):
                result = capture_evidence.project_g10_receipts(events, "g10-test")
                self.assertEqual(result["status"], "BLOCKED")
                self.assertIn("invalid_or_duplicate_receipt_identity", result["reason"])

        for field in ("call_id", "attempt_id"):
            malformed = _receipt("g10-test", 5, 10, 0, 5, "actual", 0.001)
            malformed[field] = "bad identity"
            with self.subTest(field=field):
                result = capture_evidence.project_g10_receipts([malformed], "g10-test")
                self.assertEqual(result["status"], "BLOCKED")
                self.assertIn("receipt_identity_invalid", result["reason"])

        wrong_run = _receipt("g10-test", 6, 10, 0, 5, "actual", 0.001)
        wrong_run["run_id"] = "another-run"
        result = capture_evidence.project_g10_receipts([wrong_run], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("receipt_run_id_mismatch", result["reason"])
        result = capture_evidence.project_g10_receipts([], "invalid run id")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "invalid_run_id")

    def test_receipt_projection_rejects_missing_or_incomplete_sdk_usage(self):
        missing_total = _receipt("g10-test", 1, 10, 2, 5, "actual", 0.001)
        missing_total.pop("sdk_total_tokens")
        result = capture_evidence.project_g10_receipts([missing_total], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("receipt_usage_count_invalid", result["reason"])

        incomplete = _receipt("g10-test", 2, 10, 2, 5, "actual", 0.001)
        incomplete["usage_complete"] = False
        result = capture_evidence.project_g10_receipts([incomplete], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("receipt_usage_incomplete", result["reason"])

    def test_receipt_projection_rejects_duplicate_identity_and_cost_contradictions(self):
        first = _receipt("g10-test", 1, 10, 2, 5, "actual", 0.001)
        duplicate = copy.deepcopy(first)
        duplicate["call_id"] = "call-2"
        result = capture_evidence.project_g10_receipts([first, duplicate], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("invalid_or_duplicate_receipt_identity", result["reason"])

        missing_id = _receipt("g10-test", 3, 10, 2, 5, "actual", 0.001)
        missing_id["call_id"] = ""
        result = capture_evidence.project_g10_receipts([missing_id], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("invalid_or_duplicate_receipt_identity", result["reason"])

        contradictory = _receipt("g10-test", 4, 10, 2, 5, "actual", 0.001)
        contradictory["cost_usd"] = 0.002
        result = capture_evidence.project_g10_receipts([contradictory], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("receipt_cost_provenance_contradictory", result["reason"])

        contradictory_usage = _receipt("g10-test", 5, 10, 2, 5, "actual", 0.001)
        contradictory_usage["cached_tokens"] = 11
        result = capture_evidence.project_g10_receipts([contradictory_usage], "g10-test")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("receipt_usage_components_contradictory", result["reason"])

    def test_usage_reconciliation_requires_sdk_session_total_but_accepts_cumulative_week(self):
        usage_events, token_updates = _usage_event(
            session_tokens=249, week_tokens=900, debug_tokens=249)
        usage = capture_evidence.project_g10_usage_observations(usage_events, token_updates)
        receipts = capture_evidence.project_g10_receipts([
            _receipt("g10-test", 1, 100, 20, 40, "actual", 0.001,
                     sdk_total_tokens=139),
            _receipt("g10-test", 2, 50, 10, 30, "estimated", 0.0005),
            _receipt("g10-test", 3, 10, 0, 20, "unpriced_unknown", None,
                     sdk_total_tokens=30),
        ], "g10-test")
        usage["sections"]["session"]["tokens"] = 250
        problems = capture_evidence.reconcile_g10_router_usage(usage, receipts)
        self.assertIn("g10_session_sdk_total_tokens_mismatch", problems)

        usage["sections"]["session"]["tokens"] = 249
        usage["sections"]["week"].pop("tokens")
        problems = capture_evidence.reconcile_g10_router_usage(usage, receipts)
        self.assertIn("g10_week_usage_totals_missing_or_invalid", problems)

    def test_usage_rejects_wrong_socket_route_and_debug_mismatch(self):
        usage_events, token_updates = _usage_event(debug_tokens=249)
        self.assertEqual(
            capture_evidence.project_g10_usage_observations(usage_events, token_updates)["status"],
            "BLOCKED",
        )
        usage_events, token_updates = _usage_event()
        usage_events[0]["source_route"] = "socket.debug_output"
        invalid = capture_evidence.project_g10_usage_observations(usage_events, token_updates)
        self.assertEqual(invalid["status"], "BLOCKED")
        self.assertIn("usage_output_source_invalid", invalid["problems"])

    def test_present_debug_token_fields_are_not_reported_missing_when_usage_section_is_absent(self):
        usage_events, token_updates = _usage_event()
        report_lines = usage_events[0]["content"].splitlines()
        usage_events[0]["content"] = "\n".join(
            report_lines[:2] + report_lines[3:]
        )
        invalid = capture_evidence.project_g10_usage_observations(usage_events, token_updates)
        self.assertEqual(invalid["status"], "BLOCKED")
        self.assertIn("session_usage_section_missing_or_incomplete", invalid["problems"])
        self.assertNotIn("debug_session_token_count_missing", invalid["problems"])
        self.assertNotIn("debug_week_token_count_missing", invalid["problems"])

    def test_usage_requires_exactly_one_report_and_reconciled_cost_components(self):
        _, token_updates = _usage_event()
        missing = capture_evidence.project_g10_usage_observations([], token_updates)
        self.assertEqual(missing["status"], "BLOCKED")
        self.assertIn("usage_output_missing_or_duplicated", missing["problems"])

        usage_events, token_updates = _usage_event(session_known=0.009)
        invalid = capture_evidence.project_g10_usage_observations(usage_events, token_updates)
        self.assertEqual(invalid["status"], "BLOCKED")
        self.assertNotIn("content", invalid["source_events"][0])
        duplicate, _ = _usage_event()
        duplicate.extend(copy.deepcopy(duplicate))
        invalid = capture_evidence.project_g10_usage_observations(duplicate, token_updates)
        self.assertIn("usage_output_missing_or_duplicated", invalid["problems"])
        self.assertEqual(
            capture_evidence.project_g10_usage_observations(invalid["usage_events"], token_updates),
            invalid,
        )

    def test_malformed_and_unbounded_usage_reports_fail_closed_without_retaining_raw_text(self):
        usage_events, token_updates = _usage_event()
        usage_events[0]["content"] = "[SYSTEM] Usage:\nRouter: malformed\n" + "x" * 600
        invalid = capture_evidence.project_g10_usage_observations(usage_events, token_updates)
        self.assertEqual(invalid["status"], "BLOCKED")
        self.assertIn("usage_report_line_count_invalid", invalid["problems"])
        self.assertNotIn("content", invalid["usage_events"][0])
        self.assertEqual(
            capture_evidence.project_g10_usage_observations(invalid["usage_events"], token_updates),
            invalid,
        )

        usage_events, token_updates = _usage_event()
        usage_events[0]["content"] += "x" * 2049
        invalid = capture_evidence.project_g10_usage_observations(usage_events, token_updates)
        self.assertIn("usage_output_exceeds_bound", invalid["problems"])
        self.assertNotIn("content", invalid["usage_events"][0])
        self.assertEqual(
            capture_evidence.project_g10_usage_observations(invalid["usage_events"], token_updates),
            invalid,
        )


class G10TrackerTelemetryTests(unittest.TestCase):
    def test_tracker_week_cutoff_is_inclusive_and_expired_rows_remain_counted(self):
        captured_at = datetime.now().replace(microsecond=0)
        cutoff = captured_at - timedelta(days=7)

        def row(timestamp, call_id, attempt_id):
            return {
                "timestamp": timestamp.isoformat(),
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 7,
                "context": {
                    "call_id": call_id, "attempt_id": attempt_id,
                    "cost_provenance": "actual", "cost_usd": 0.001,
                    "cost_complete": True,
                },
                "cost_usd": 0.001,
                "cost_source": "provider_reported",
                "cost_estimate": False,
            }

        raw = (json.dumps(row(cutoff, "call-a", "attempt-a")) + "\n" +
               json.dumps(row(cutoff - timedelta(seconds=1), "call-b", "attempt-b")) +
               "\n").encode("utf-8")
        snapshot = capture_evidence._g10_tracker_parse_bytes(raw, captured_at, 7)
        self.assertEqual(snapshot["status"], "captured", snapshot["problems"])
        self.assertEqual([event["line_number"] for event in snapshot["events"]], [1])
        self.assertEqual(snapshot["expired_line_numbers"], [2])
        self.assertEqual(snapshot["expired_event_refs"][0]["line_number"], 2)

    def test_tracker_projection_preserves_sdk_totals_and_cost_only_media(self):
        base_epoch = time.time() - 120
        events = [
            _tracker_event(1, base_epoch + 1.5, 1, 60, 30, 90, "actual", 0.001),
            _tracker_event(2, base_epoch + 1.6, 2, 60, 30, 89, "estimated", 0.0005),
            _tracker_event(3, base_epoch + 1.7, 3, 40, 30, 70, "unpriced", 0),
            {
                "kind": "image_cost", "line_number": 4,
                "source_line_sha256": hashlib.sha256(b"image-row").hexdigest(),
                "timestamp_epoch": base_epoch + 1.8,
                "timestamp_basis": "local-naive",
                "prompt_tokens": 0, "completion_tokens": 0, "sdk_total_tokens": 0,
                "cost_usd": 0.003, "cost_source": "estimated",
                "cost_estimate": True,
                "image_metadata": {"model": "image-model", "size": "1024x1024",
                                   "quality": "standard"},
            },
        ]
        artifact, usage = _tracker_phase_fixture(
            "complete", "tracker-complete", "chain-tracker", "seed-tracker",
            "e" * 64, events, base_epoch,
        )
        self.assertEqual(usage["status"], "ok", usage)
        projection = capture_evidence.project_g10_tracker_telemetry(
            artifact, usage["observed"], usage["router_receipts"]
        )
        self.assertEqual(projection["status"], "ok", projection)
        self.assertEqual(projection["session"]["tokens"], 249)
        self.assertEqual(projection["session"]["actual_usd"], 0.001)
        self.assertAlmostEqual(projection["session"]["estimated_usd"], 0.0035)
        self.assertAlmostEqual(projection["session"]["known_cost_usd"], 0.0045)
        self.assertEqual(projection["session"]["unpriced_calls"], 1)
        self.assertEqual(projection["session"]["image_event_count"], 1)
        self.assertEqual(projection["session"]["cost_coverage"], "incomplete")

    def test_tracker_projection_blocks_async_append_and_missing_launch_timestamp(self):
        base_epoch = time.time() - 120
        events = [
            _tracker_event(1, base_epoch + 1.5, 1, 60, 30, 90, "actual", 0.001),
            _tracker_event(2, base_epoch + 1.6, 2, 60, 30, 89, "estimated", 0.0005),
            _tracker_event(3, base_epoch + 1.7, 3, 40, 30, 70, "unpriced", 0),
        ]
        artifact, usage = _tracker_phase_fixture(
            "complete", "tracker-complete", "chain-tracker", "seed-tracker",
            "f" * 64, events, base_epoch,
        )
        async_artifact = copy.deepcopy(artifact)
        extra = _tracker_event(4, base_epoch + 5.5, 4, 1, 1, 2, "actual", 0.0001)
        terminal = async_artifact["post_shutdown"]
        terminal["events"].append(extra)
        terminal["line_count"] = 4
        source = terminal["source"]
        source_raw = ("\n".join(row["source_line_sha256"]
                                  for row in terminal["events"]) + "\n").encode("ascii")
        source["bytes"] = len(source_raw)
        source["sha256"] = hashlib.sha256(source_raw).hexdigest()
        async_projection = capture_evidence.project_g10_tracker_telemetry(
            async_artifact, usage["observed"], usage["router_receipts"]
        )
        self.assertEqual(async_projection["status"], "BLOCKED")
        self.assertIn("g10_tracker_async_events_after_usage", async_projection["problems"])

        missing_launch = copy.deepcopy(artifact)
        missing_launch["server_launch_epoch"] = None
        launch_projection = capture_evidence.project_g10_tracker_telemetry(
            missing_launch, usage["observed"], usage["router_receipts"]
        )
        self.assertEqual(launch_projection["status"], "BLOCKED")
        self.assertIn("g10_tracker_server_launch_time_missing_or_invalid",
                      launch_projection["problems"])

    def test_resume_tracker_boundary_accepts_only_finalized_complete_artifact(self):
        with tempfile.TemporaryDirectory(prefix="g10-boundary-",
                                         dir=str(capture_evidence.PROJECT_TMP)) as temp:
            project_tmp = Path(temp)
            sandbox = project_tmp / "combat_capture"
            g10_root = project_tmp / "router-rollout" / "g10"
            complete_dir = g10_root / "complete-run"
            resume_dir = g10_root / "resume-run"
            sandbox.mkdir(parents=True)
            complete_dir.mkdir(parents=True)
            resume_dir.mkdir(parents=True)
            sandbox_id = hashlib.sha256(str(sandbox.resolve()).encode("utf-8")).hexdigest()
            log_source = {"bytes": 4, "sha256": hashlib.sha256(b"data").hexdigest()}
            base_epoch = time.time() - 60
            terminal_snapshot = _tracker_snapshot(
                base_epoch + 10, [], present=True, source_bytes=log_source["bytes"],
                source_sha256=log_source["sha256"],
                prefix={"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest(),
                        "matches_expected": True},
            )
            complete_tracker = {
                "status": "captured", "phase": "complete", "run_id": "complete-run",
                "chain_id": "chain-boundary", "seed_id": "seed-boundary",
                "sandbox_id": sandbox_id,
                "post_shutdown": terminal_snapshot,
            }
            tracker_raw = json.dumps(complete_tracker, sort_keys=True).encode("utf-8")
            (complete_dir / "g10_tracker_telemetry.json").write_bytes(tracker_raw)
            (complete_dir / "manifest.json").write_text(json.dumps({
                "gate": "g10", "run_id": "complete-run", "chain_id": "chain-boundary",
                "seed": {"seed_id": "seed-boundary"}, "sandbox_id": sandbox_id,
                "artifacts": {"g10_tracker_telemetry": "g10_tracker_telemetry.json"},
                "artifact_sha256": {
                    "g10_tracker_telemetry.json": hashlib.sha256(tracker_raw).hexdigest(),
                },
            }), encoding="ascii")
            marker = {
                "status": "ok", "gate": "g10", "scenario_id": "full-session",
                "chain_id": "chain-boundary", "seed_id": "seed-boundary",
                "complete_run_dir": str(complete_dir), "party_size": 1,
                "sha256": "a" * 64,
            }
            snapshot = _tracker_snapshot(
                base_epoch + 20, [], present=True, source_bytes=log_source["bytes"],
                source_sha256=log_source["sha256"],
            )
            output = g10_root / ".tracker-boundary-resume-run.json"
            with patch.object(capture_evidence, "PROJECT_TMP", project_tmp), \
                    patch.object(capture_evidence, "G10_RUN_ROOT", g10_root), \
                    patch.object(capture_evidence, "read_sandbox_g10_marker", return_value=marker), \
                    patch.object(capture_evidence, "capture_g10_tracker_snapshot",
                                 return_value=snapshot):
                boundary = capture_evidence.capture_g10_tracker_boundary(
                    sandbox, resume_dir, output, "resume", "chain-boundary"
                )
            self.assertEqual(boundary["status"], "captured")
            self.assertEqual(boundary["prior_link"]["status"], "linked_complete_boundary")
            self.assertEqual(boundary["prior_link"]["complete_artifact_sha256"],
                             hashlib.sha256(tracker_raw).hexdigest())

    def test_resume_finalizer_binds_tracker_to_first_lifecycle_start(self):
        with tempfile.TemporaryDirectory(prefix="g10-finalizer-",
                                         dir=str(capture_evidence.PROJECT_TMP)) as temp:
            project_tmp = Path(temp)
            sandbox = project_tmp / "combat_capture"
            run_root = project_tmp / "router-rollout" / "g10"
            run_dir = run_root / "resume-finalizer"
            sandbox.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            launch_epoch = time.time() - 2
            identity = {
                "gate": "g10", "row_key": "full-session:resume:p1",
                "run_id": run_dir.name, "phase": "resume", "party_size": 1,
                "chain_id": "chain-finalizer", "seed_id": "seed-finalizer",
                "sandbox_id": "a" * 64, "source_head": "b" * 40,
                "relevant_dirty_sha256": "c" * 64,
            }
            lifecycle_events = [
                {**identity, "event": "resume_server_started", "server_pid": 123,
                 "server_launch_epoch": launch_epoch},
                {**identity, "event": "capture_completed", "driver_exit_status": 0},
                {**identity, "event": "server_stopped", "server_pid": 123,
                 "port": 8360, "remaining_listener_pids": [],
                 "server_log_artifact": "server.log"},
            ]
            lifecycle_path = run_dir / "server_lifecycle.jsonl"
            lifecycle_path.write_text("".join(json.dumps(row) + "\n"
                                                       for row in lifecycle_events),
                                      encoding="ascii")
            server_path = run_dir / "server.log"
            server_path.write_text("Capture_Arena server output\n", encoding="ascii")
            trace_path = run_dir / "trace.jsonl"
            trace_path.write_bytes(b"")
            empty_hash = hashlib.sha256(b"").hexdigest()
            tracker = {
                "status": "pending", "phase": "resume", "run_id": run_dir.name,
                "chain_id": identity["chain_id"], "seed_id": identity["seed_id"],
                "sandbox_id": identity["sandbox_id"],
                "pre_run": {"status": "captured"},
                "post_usage": {"status": "captured", "source": {
                    "bytes": 0, "sha256": empty_hash,
                }},
            }
            usage = {"status": "BLOCKED", "usage_capture": {},
                     "observed": {}, "router_receipts": {}}
            _write_json(run_dir / "g10_tracker_telemetry.json", tracker)
            _write_json(run_dir / "g10_usage.json", usage)
            _write_json(run_dir / "g10_save_state.json", {})
            _write_json(run_dir / "checks.json", {"checks": []})
            artifacts = {
                "server_lifecycle": "server_lifecycle.jsonl",
                "server_log": "server.log", "trace": "trace.jsonl",
                "g10_tracker_telemetry": "g10_tracker_telemetry.json",
                "g10_usage": "g10_usage.json", "g10_save_state": "g10_save_state.json",
                "checks": "checks.json", "step_snapshots": [],
            }
            manifest = {
                "gate": "g10", "run_id": run_dir.name, "chain_id": identity["chain_id"],
                "scenario": {"id": "full-session", "phase": "resume"},
                "party": {"size": 1}, "seed": {"seed_id": identity["seed_id"]},
                "sandbox_id": identity["sandbox_id"],
                "source": {"head": identity["source_head"],
                           "relevant_dirty_sha256": identity["relevant_dirty_sha256"]},
                "trace_span": {"offset_before_bytes": 0},
                "g10": {"row_key": identity["row_key"]},
                "artifacts": artifacts,
                "artifact_sha256": {
                    reference: hashlib.sha256((run_dir / reference).read_bytes()).hexdigest()
                    for reference in ("trace.jsonl", "g10_tracker_telemetry.json",
                                      "g10_usage.json", "g10_save_state.json")
                },
            }
            _write_json(run_dir / "manifest.json", manifest)
            usage_path = run_dir / "g10_usage.json"
            captured_usage_raw = usage_path.read_bytes()
            terminal = {"status": "captured", "source": {
                "path": "telemetry_log.jsonl", "present": False,
                "bytes": 0, "sha256": empty_hash, "device": None, "inode": None,
                "prefix": {"bytes": 0, "sha256": empty_hash,
                           "matches_expected": True},
            }}
            validation = {"reconciliation_problems": [], "expected_status": "ok",
                          "problems": [], "failures": []}
            with patch.object(capture_evidence, "PROJECT_TMP", project_tmp), \
                    patch.object(capture_evidence, "G10_RUN_ROOT", run_root), \
                    patch.object(capture_evidence, "capture_g10_tracker_snapshot",
                                 return_value=terminal) as snapshot_capture, \
                    patch.object(capture_evidence, "load_step_snapshots", return_value=([], [])), \
                    patch.object(capture_evidence, "project_g10_usage_observations",
                                 return_value={"status": "captured", "problems": []}), \
                    patch.object(capture_evidence, "project_g10_tracker_telemetry",
                                 return_value={"status": "ok", "problems": []}), \
                    patch.object(capture_evidence, "revalidate_g10_usage_artifact",
                                 return_value=validation), \
                    patch.object(capture_evidence, "build_g10_checks", return_value=[]):
                usage_path.write_bytes(captured_usage_raw + b" ")
                with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                    capture_evidence.finalize_g10_capture_bundle(
                        run_dir, lifecycle_path, server_path, sandbox
                    )
                usage_path.write_bytes(captured_usage_raw)
                result = capture_evidence.finalize_g10_capture_bundle(
                    run_dir, lifecycle_path, server_path, sandbox
                )
            self.assertEqual(result["status"], "finalized")
            self.assertEqual(snapshot_capture.call_args.kwargs["prefix_bytes"], 0)
            finalized_tracker = json.loads(
                (run_dir / "g10_tracker_telemetry.json").read_text(encoding="utf-8")
            )
            self.assertEqual(finalized_tracker["server_launch_epoch"], launch_epoch)
            self.assertEqual(finalized_tracker["status"], "captured")


class G10DiaryIdentifierTests(unittest.TestCase):
    def _write_projection(self, database_path, entries, states):
        _write_diary_database(database_path, entries, states)

    def test_saved_checkpoint_and_resumed_draft_have_disjoint_ids_and_ranges(self):
        save_id = "11111111-1111-4111-8111-111111111111"
        confirmed = {
            "diary_id": 1, "status": "confirmed", "save_id": save_id,
            "draft_key": None, "source_start_event_id": 1,
            "source_end_event_id": 10, "checkpoint_type": "save",
            "checkpoint_id": save_id,
        }
        saved_state = {
            "state_id": 1, "last_draft_event_id": 10,
            "last_confirmed_event_id": 10, "last_confirmed_save_id": save_id,
            "last_draft_key": None,
        }
        draft = {
            "diary_id": 2, "status": "draft", "save_id": None,
            "draft_key": "active_draft", "source_start_event_id": 11,
            "source_end_event_id": 20, "checkpoint_type": None,
            "checkpoint_id": None,
        }
        resume_state = {
            "state_id": 1, "last_draft_event_id": 20,
            "last_confirmed_event_id": 10, "last_confirmed_save_id": save_id,
            "last_draft_key": "active_draft",
        }
        with tempfile.TemporaryDirectory(prefix="g10-diary-", dir=str(
                capture_evidence.PROJECT_TMP)) as temp:
            sandbox = Path(temp) / "combat_capture"
            save_root = sandbox / G10_TEST_SAVE_DIRECTORY / "memory_db_package" / "memory.db"
            resume_root = sandbox / "data" / "memory.db"
            self._write_projection(save_root, [confirmed], [saved_state])
            self._write_projection(resume_root, [confirmed, draft], [resume_state])

            complete_evidence = capture_evidence._capture_g10_diary_identifier_evidence(
                sandbox, sandbox / G10_TEST_SAVE_DIRECTORY, G10_TEST_SAVE_DIRECTORY,
                save_id, "complete",
            )
            resume_evidence = capture_evidence._capture_g10_diary_identifier_evidence(
                sandbox, sandbox / G10_TEST_SAVE_DIRECTORY, G10_TEST_SAVE_DIRECTORY,
                save_id, "resume",
            )
            result = capture_evidence.validate_g10_diary_restart_evidence(
                {"save_id": save_id, "save_directory": G10_TEST_SAVE_DIRECTORY,
                 "diary_identifier_evidence": complete_evidence},
                {"save_id": save_id, "save_directory": G10_TEST_SAVE_DIRECTORY,
                 "diary_identifier_evidence": resume_evidence},
            )
            self.assertEqual(result["status"], "ok", result)
            self.assertEqual(result["confirmed_checkpoint"]["diary_id"], 1)
            self.assertEqual(result["resume_draft"]["diary_id"], 2)
            self.assertEqual(result["resume_draft"]["source_start_event_id"], 11)

            overlapping = dict(draft, source_start_event_id=10)
            self._write_projection(resume_root, [confirmed, overlapping], [resume_state])
            overlapping_projection = capture_evidence._g10_diary_identifier_projection(
                resume_root, sandbox
            )
            self.assertEqual(overlapping_projection["status"], "BLOCKED")
            self.assertEqual(overlapping_projection["reason"],
                             "diary_identifier_event_range_overlapping")

            duplicate_draft = dict(draft, diary_id=3, source_start_event_id=21,
                                   source_end_event_id=25)
            self._write_projection(resume_root, [confirmed, draft, duplicate_draft],
                                   [resume_state])
            complete_evidence = capture_evidence._capture_g10_diary_identifier_evidence(
                sandbox, sandbox / G10_TEST_SAVE_DIRECTORY, G10_TEST_SAVE_DIRECTORY,
                save_id, "complete",
            )
            resume_evidence = capture_evidence._capture_g10_diary_identifier_evidence(
                sandbox, sandbox / G10_TEST_SAVE_DIRECTORY, G10_TEST_SAVE_DIRECTORY,
                save_id, "resume",
            )
            result = capture_evidence.validate_g10_diary_restart_evidence(
                {"save_id": save_id, "save_directory": G10_TEST_SAVE_DIRECTORY,
                 "diary_identifier_evidence": complete_evidence},
                {"save_id": save_id, "save_directory": G10_TEST_SAVE_DIRECTORY,
                 "diary_identifier_evidence": resume_evidence},
            )
            self.assertEqual(result["status"], "FAIL", result)
            self.assertIn("g10_resumed_diary_checkpoint_or_draft_duplicated",
                          result["failures"])

            duplicate_id = dict(draft, source_start_event_id=21, source_end_event_id=25)
            self._write_projection(resume_root, [confirmed, draft, dict(duplicate_id, diary_id=2)],
                                   [resume_state])
            duplicate_ids = capture_evidence._g10_diary_identifier_projection(
                resume_root, sandbox
            )
            self.assertEqual(duplicate_ids["status"], "BLOCKED")
            self.assertEqual(duplicate_ids["reason"], "diary_identifier_entry_id_duplicated")


class G10SaveEvidenceTests(unittest.TestCase):
    def test_save_is_hash_projected_then_verified_after_restart(self):
        capture_evidence.G10_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="g10-state-", dir=str(capture_evidence.PROJECT_TMP)) as temp:
            workspace = Path(temp)
            state_root = workspace / "combat_capture"
            save_dir = state_root / G10_TEST_SAVE_DIRECTORY
            saved_games = state_root / "modules" / "Capture_Arena" / "saved_games"
            saved_games.mkdir(parents=True, exist_ok=True)
            before_saves = capture_evidence.g10_save_directories(state_root)
            self.assertEqual(before_saves, [])
            roster, encounter_id = _seed_saved_state(save_dir)
            metadata_path = save_dir / "save_metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["description"] = "Capture session checkpoint"
            _write_json(metadata_path, metadata)
            saved_memory_path = save_dir / "memory_db_package" / "memory.db"
            saved_memory_before = saved_memory_path.read_bytes()

            complete = capture_evidence.capture_g10_save_state(
                state_root, workspace / "complete", before_saves, roster,
                encounter_id, phase="complete",
                save_confirmation_directory=G10_TEST_SAVE_DIRECTORY,
            )
            self.assertEqual(complete["status"], "captured", complete)
            self.assertFalse((workspace / "complete" / "saved_state").exists())
            self.assertFalse(complete["raw_saved_state_copied"])
            diary_evidence = complete["diary_identifier_evidence"]
            self.assertEqual(diary_evidence["status"], "captured")
            diary_projection = diary_evidence["saved_checkpoint"]["projection"]
            self.assertEqual(set(diary_projection), {"entries", "state"})
            self.assertEqual(set(diary_projection["entries"][0]), {
                "diary_id", "status", "save_id", "draft_key", "source_start_event_id",
                "source_end_event_id", "checkpoint_type", "checkpoint_id",
            })
            self.assertNotIn("summary", json.dumps(diary_evidence).lower())
            self.assertNotIn("prompt", json.dumps(diary_evidence).lower())
            self.assertEqual(saved_memory_path.read_bytes(), saved_memory_before)

            with tempfile.TemporaryDirectory(prefix="g10-complete-", dir=str(
                    capture_evidence.G10_RUN_ROOT)) as complete_run:
                bundle = Path(complete_run)
                save_path = bundle / "g10_save_state.json"
                raw = json.dumps(complete, ensure_ascii=True, sort_keys=True).encode("utf-8")
                save_path.write_bytes(raw)
                sandbox_id = hashlib.sha256(str(state_root.resolve()).encode("utf-8")).hexdigest()
                manifest = {
                    "gate": "g10", "chain_id": "chain-g10-p1",
                    "sandbox_id": sandbox_id,
                    "scenario": {"id": "full-session", "phase": "complete"},
                    "party": {"size": 1, "roster": roster},
                    "seed": {"seed_id": "seed-g10-p1"},
                    "g10": {"phase": "complete", "chain_id": "chain-g10-p1",
                            "seed_id": "seed-g10-p1", "sandbox_id": sandbox_id},
                    "artifacts": {"g10_save_state": "g10_save_state.json"},
                    "artifact_sha256": {"g10_save_state.json": hashlib.sha256(raw).hexdigest()},
                }
                _write_json(bundle / "manifest.json", manifest)
                retained_before = capture_evidence.g10_save_directories(state_root)
                resumed_memory_path = state_root / "data" / "memory.db"
                resumed_memory_before = resumed_memory_path.read_bytes()
                retained = capture_evidence.capture_g10_save_state(
                    state_root, workspace / "resume", retained_before, roster,
                    encounter_id, phase="resume", complete_run_dir=bundle,
                    expected_chain_id="chain-g10-p1",
                )
                self.assertEqual(retained["status"], "retained", retained)
                self.assertEqual(retained["saved_state_sha256"], complete["saved_state_sha256"])
                self.assertEqual(retained["save_id"], complete["save_id"])
                self.assertEqual(retained["worldline_id"], complete["worldline_id"])
                self.assertEqual(retained["diary_identifier_evidence"]["status"], "captured")
                self.assertEqual(retained["diary_identifier_evidence"]["resumed_state"][
                    "projection"]["entries"][1]["draft_key"], "active_draft")
                self.assertEqual(resumed_memory_path.read_bytes(), resumed_memory_before)

                character_path = save_dir / "characters" / "acheron.json"
                character = json.loads(character_path.read_text(encoding="utf-8"))
                character["inventory"][0]["quantity"] = 2
                _write_json(character_path, character)
                changed = capture_evidence.capture_g10_save_state(
                    state_root, workspace / "resume-changed",
                    capture_evidence.g10_save_directories(state_root), roster,
                    encounter_id, phase="resume", complete_run_dir=bundle,
                    expected_chain_id="chain-g10-p1",
                )
                self.assertEqual(changed["status"], "BLOCKED")

    def test_save_requires_canonical_ids_and_party_identity(self):
        capture_evidence.G10_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="g10-invalid-save-", dir=str(
                capture_evidence.PROJECT_TMP)) as temp:
            workspace = Path(temp)
            state_root = workspace / "combat_capture"
            save_dir = state_root / G10_TEST_SAVE_DIRECTORY
            (state_root / "modules" / "Capture_Arena" / "saved_games").mkdir(
                parents=True, exist_ok=True
            )
            before_saves = capture_evidence.g10_save_directories(state_root)
            roster, encounter_id = _seed_saved_state(save_dir)
            metadata_path = save_dir / "save_metadata.json"
            canonical = json.loads(metadata_path.read_text(encoding="utf-8"))
            mutations = (
                ("save_id", lambda value: value.update(save_id="not-a-uuid")),
                ("worldline_id", lambda value: value.update(worldline_id="not-a-uuid")),
                ("party_roster", lambda value: value["game_state"].update(
                    party_members=["Wrong PC"])),
                ("game_state_module", lambda value: value["game_state"].update(
                    module="Other_Module")),
                ("save_mode", lambda value: value.update(save_mode="full")),
            )
            for label, mutate in mutations:
                with self.subTest(identity=label):
                    modified = copy.deepcopy(canonical)
                    mutate(modified)
                    _write_json(metadata_path, modified)
                    result = capture_evidence.capture_g10_save_state(
                        state_root, workspace / ("invalid-" + label), before_saves,
                        roster, encounter_id, phase="complete",
                        save_confirmation_directory=(
                            G10_TEST_SAVE_DIRECTORY
                        ),
                    )
                    self.assertEqual(result["status"], "BLOCKED")
                    self.assertEqual(result["reason"], "save_metadata_identity_mismatch")

    def test_save_completion_must_match_the_only_new_directory(self):
        capture_evidence.G10_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="g10-save-binding-", dir=str(
                capture_evidence.PROJECT_TMP)) as temp:
            workspace = Path(temp)
            state_root = workspace / "combat_capture"
            save_dir = state_root / G10_TEST_SAVE_DIRECTORY
            (state_root / "modules" / "Capture_Arena" / "saved_games").mkdir(
                parents=True, exist_ok=True
            )
            before_saves = capture_evidence.g10_save_directories(state_root)
            roster, encounter_id = _seed_saved_state(save_dir)
            missing = capture_evidence.capture_g10_save_state(
                state_root, workspace / "missing", before_saves, roster,
                encounter_id, phase="complete",
            )
            self.assertEqual(missing["status"], "BLOCKED")
            self.assertEqual(missing["reason"], "save_completion_confirmation_missing")
            mismatched = capture_evidence.capture_g10_save_state(
                state_root, workspace / "mismatched", before_saves, roster,
                encounter_id, phase="complete",
                save_confirmation_directory=(
                    "modules/Capture_Arena/saved_games/save_20261030_041634"
                ),
            )
            self.assertEqual(mismatched["status"], "BLOCKED")
            self.assertEqual(mismatched["reason"], "save_confirmation_new_save_mismatch")


class G10EvaluatorTests(unittest.TestCase):
    def test_incomplete_matrix_is_readiness_blocked_and_never_a_verdict(self):
        result = capture_evidence.evaluate_g10_matrix([])
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertEqual(result["primary_verdict"], "PENDING")
        self.assertEqual(result["missing_required_keys"], list(fixtures.required_g10_row_keys()))
        self.assertNotIn("PASS", result.values())

    def test_malformed_nested_evidence_fails_closed(self):
        result = capture_evidence.evaluate_g10_bundle({
            "scenario": {"id": "full-session", "phase": "complete"},
            "party": {"size": 1},
        }, None, capture_evidence.G10_RUN_ROOT / "malformed")
        self.assertEqual(result["automated_status"], "BLOCKED")
        self.assertEqual(result["primary_verdict"], "PENDING")
        self.assertEqual(result["problems"], ["malformed_or_unreadable_g10_evidence"])

    def test_synthetic_matrix_row_is_never_ready_for_primary_review(self):
        capture_evidence.G10_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="g10-synthetic-", dir=str(
                capture_evidence.G10_RUN_ROOT)) as temp:
            run_dir = Path(temp)
            profile = fixtures.build_gate_profile("g10", "full-session", 1, phase="complete")
            contract = {key: profile.get(key) for key in (
                "scenario_id", "party_size", "branch", "phase", "seed", "applicability"
            )}
            contract.update({
                "gate": "g10", "row_key": profile["row_key"],
                "seed_scenario_id": profile["seed_scenario_id"],
                "seed_identity": profile["seed_identity"],
                "script_sha256": profile["applicability"]["script_sha256"],
            })
            expected_seed = dict(profile["seed"])
            expected_seed.pop("resume_phase", None)
            seed_digest = hashlib.sha256(json.dumps(
                expected_seed, sort_keys=True
            ).encode("utf-8")).hexdigest()
            chain_id = "chain-g10-synthetic-p1"
            sandbox_id = "sandbox-g10-synthetic-p1"
            manifest = {
                "gate": "g10", "run_id": run_dir.name,
                "scenario": {
                    "id": "full-session", "phase": "complete",
                    "profile_contract": contract,
                    "sha256": hashlib.sha256(json.dumps(
                        contract, sort_keys=True
                    ).encode("utf-8")).hexdigest(),
                },
                "party": {"size": 1, "roster": [fixtures.ONE_PC_NAME]},
                "chain_id": chain_id, "sandbox_id": sandbox_id,
                "seed": {"profile_seed": expected_seed,
                         "seed_profile_sha256": seed_digest, "seed_id": seed_digest,
                         "roster": [fixtures.ONE_PC_NAME]},
                "source": {},
                "g10": {
                    "row_key": profile["row_key"], "phase": "complete",
                    "chain_id": chain_id, "seed_id": seed_digest,
                    "script_sha256": profile["applicability"]["script_sha256"],
                    "sandbox_id": sandbox_id,
                    "expected": {
                        "steps": [{key: row.get(key) for key in
                                   ("label", "input", "character", "kind")}
                                  for row in profile["fixture"]["steps"]],
                        "complete_script_sha256": profile["applicability"]["script_sha256"],
                    },
                },
                "artifacts": {"matrix_keys": [profile["row_key"]]},
                "evidence_kind": "synthetic", "live_eligible": False,
                "transport": {"client_source": "fake"},
            }
            _write_json(run_dir / "manifest.json", manifest)
            result = capture_evidence.evaluate_g10_matrix([run_dir])
            self.assertIn(result["automated_status"], ("BLOCKED", "FAIL"))
            self.assertEqual(result["primary_verdict"], "PENDING")
            self.assertIn(profile["row_key"], result["synthetic_keys"])
            self.assertIn(profile["row_key"], result["not_ready_keys"])
            self.assertNotEqual(result["automated_status"], "READY_FOR_PRIMARY_REVIEW")

    def test_degraded_full_session_report_is_rejected_by_artifact_integrity(self):
        capture_evidence.G10_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="g10-degraded-", dir=str(
                capture_evidence.G10_RUN_ROOT)) as temp:
            run_dir = Path(temp)
            report = {"status": "degraded", "input": {
                "malformed_count": 0, "total_records": 0,
            }}
            report_raw = json.dumps(report, sort_keys=True).encode("ascii")
            (run_dir / "report.json").write_bytes(report_raw)
            manifest = {
                "gate": "g10", "scenario": {"id": "full-session", "phase": "complete"},
                "artifact_sha256": {"report.json": hashlib.sha256(report_raw).hexdigest()},
                "trace_start_offset": {"status": "captured", "source_byte_offset": 0},
                "trace_span": {"offset_before_bytes": 0},
                "counts": {"steps_sent": 0},
            }
            artifacts = {
                "report": "report.json", "trace_copy": {
                    "status": "copied", "source_records": 0, "destination_records": 0,
                },
                "step_snapshots": [],
            }
            integrity = capture_evidence._artifact_integrity(run_dir, manifest, artifacts)
            self.assertIn("report:degraded", integrity["failures"])

    def test_owned_server_lifecycle_rejects_wrong_port_and_listener_cwd(self):
        capture_evidence.G10_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="g10-lifecycle-", dir=str(
                capture_evidence.G10_RUN_ROOT)) as temp:
            run_dir = Path(temp)
            server_raw = b"Capture_Arena server output\n"
            (run_dir / "server.log").write_bytes(server_raw)
            expected_cwd = str((capture_evidence.PROJECT_TMP / "combat_capture").resolve())
            source = {"head": "a" * 40, "relevant_dirty_sha256": "b" * 64}
            identity = {
                "gate": "g10", "row_key": "full-session:complete:p1",
                "run_id": run_dir.name, "phase": "complete", "party_size": 1,
                "chain_id": "chain-g10-p1", "seed_id": "seed-g10-p1",
                "sandbox_id": "sandbox-g10-p1", "source_head": source["head"],
                "relevant_dirty_sha256": source["relevant_dirty_sha256"],
            }
            events = [
                {**identity, "event": "prepare", "state_root": expected_cwd},
                {**identity, "event": "server_started", "server_pid": 123,
                  "listener_pids": [123],
                  "listener_processes": [{"pid": 123, "ancestry_pids": [123],
                                          "port": 8357, "cwd": expected_cwd}],
                 "port": 8357, "cwd": expected_cwd,
                  "ownership": "lsof_parent_pid_and_cwd",
                 "server_log_artifact": "server.log"},
                {**identity, "event": "capture_completed", "driver_exit_status": 0},
                {**identity, "event": "server_stopped", "server_pid": 123,
                 "port": 8360, "remaining_listener_pids": [],
                 "server_log_artifact": "server.log",
                 "server_log_sha256": hashlib.sha256(server_raw).hexdigest(),
                 "server_log_bytes": len(server_raw)},
            ]
            lifecycle_raw = ("".join(json.dumps(row, sort_keys=True) + "\n"
                                      for row in events)).encode("ascii")
            (run_dir / "server_lifecycle.jsonl").write_bytes(lifecycle_raw)
            manifest = {
                "run_id": run_dir.name, "scenario": {"phase": "complete"},
                "party": {"size": 1}, "chain_id": identity["chain_id"],
                "seed": {"seed_id": identity["seed_id"]}, "sandbox_id": identity["sandbox_id"],
                "source": source,
                "g10": {"row_key": identity["row_key"], "lifecycle": {
                    "status": "finalized", "artifact": "server_lifecycle.jsonl",
                    "sha256": hashlib.sha256(lifecycle_raw).hexdigest(),
                }},
            }
            result = capture_evidence._g10_lifecycle_evaluation(
                run_dir,
                {"server_lifecycle": "server_lifecycle.jsonl", "server_log": "server.log"},
                manifest,
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("g10_owned_server_assertion_failed", result["failures"])
            self.assertIn("g10_listener_port_or_cwd_mismatch", result["failures"])
            self.assertIn("g10_listener_process_identities_missing", result["problems"])
            self.assertIn("g10_lifecycle_synthetic_or_ineligible_evidence", result["problems"])

    @patch.object(capture_evidence, "_g10_diary_identifier_projection",
                  side_effect=AssertionError("pair evaluation must not read a live diary DB"))
    def test_complete_resume_pair_rejects_duplicate_state_and_unexplained_usage(
            self, live_projection_mock):
        capture_evidence.G10_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="g10-pair-", dir=str(
                capture_evidence.G10_RUN_ROOT)) as temp:
            root = Path(temp)
            complete_dir = root / "complete-run"
            resume_dir = root / "resume-run"
            complete_dir.mkdir()
            resume_dir.mkdir()
            complete_relative = str(complete_dir.resolve().relative_to(
                capture_evidence.PROJECT_ROOT.resolve()))
            projection = {"hitPoints": 10, "currency": {"gp": 0}}
            rewards = {"characters": {"characters/acheron.json": {
                "currency": {"gp": 0}, "experience_points": 0,
                "experiencePoints": None, "items": [{"item_name": "Sword", "quantity": 1}],
            }}, "encounter_rewards": []}
            saved_state = {
                "status": "captured",
                "save_id": "11111111-1111-4111-8111-111111111111",
                "worldline_id": "22222222-2222-4222-8222-222222222222",
                "save_directory": G10_TEST_SAVE_DIRECTORY,
                "save_metadata_sha256": "a" * 64,
                "saved_state_projection": projection,
                "saved_state_sha256": {"save_metadata.json": "b" * 64},
                "saved_state_snapshot": {"g10_reward_projection": rewards},
            }
            saved_state["diary_identifier_evidence"] = _g10_test_diary_evidence("complete")
            resume_save = dict(saved_state, status="retained", unchanged=True)
            resume_save["diary_identifier_evidence"] = _g10_test_diary_evidence("resume")
            common = {
                "chain_id": "chain-g10-p1", "sandbox_id": "d" * 64,
                "source": {"head": "a" * 40}, "party": {"size": 1, "roster": ["Acheron"]},
                "seed": {"seed_id": "seed-g10-p1"},
            }
            base_epoch = time.time() - 120
            tracker_events = [
                _tracker_event(1, base_epoch + 1.5, 1, 60, 30, 90, "actual", 0.001),
                _tracker_event(2, base_epoch + 1.6, 2, 60, 30, 89, "estimated", 0.0005),
                _tracker_event(3, base_epoch + 1.7, 3, 40, 30, 70, "unpriced", 0),
            ]
            startup_events = [
                _tracker_event(4, base_epoch + 31.5, 4, 100, 20, 120, "actual", 0.0001),
                _tracker_event(5, base_epoch + 31.6, 5, 200, 40, 240, "estimated", 0.0002),
            ]
            complete_tracker, complete_usage = _tracker_phase_fixture(
                "complete", "complete-run", common["chain_id"],
                common["seed"]["seed_id"], common["sandbox_id"], tracker_events,
                base_epoch,
            )
            complete_tracker_path = complete_dir / "g10_tracker_telemetry.json"
            _write_json(complete_tracker_path, complete_tracker)
            complete_tracker_digest = hashlib.sha256(
                complete_tracker_path.read_bytes()
            ).hexdigest()
            complete_terminal_source = complete_tracker["post_shutdown"]["source"]
            resume_link = {
                "status": "linked_complete_boundary",
                "complete_run_dir": complete_relative,
                "complete_artifact": "g10_tracker_telemetry.json",
                "complete_artifact_sha256": complete_tracker_digest,
                "complete_terminal_source_sha256": complete_terminal_source["sha256"],
                "complete_terminal_source_bytes": complete_terminal_source["bytes"],
            }
            resume_tracker, resume_usage = _tracker_phase_fixture(
                "resume", "resume-run", common["chain_id"],
                common["seed"]["seed_id"], common["sandbox_id"],
                tracker_events + startup_events, base_epoch + 30, prior_link=resume_link,
                baseline_events=tracker_events,
                startup_sources={
                    "call-4": {"site": "llm_router", "task": "summaries",
                               "source_id": "core/memory/session_diary.py:_generate_checkpoint_summary",
                               "cached_tokens": 10},
                    "call-5": {"site": "combat_reengage", "task": "combat_main",
                               "cached_tokens": 20},
                },
            )
            resume_startup_validation = {"status": "ok", "problems": [], "failures": [],
                "receipts": [
                    {"source": "session_diary_checkpoint_summary", "call_id": "call-4",
                     "attempt_id": "attempt-4", "timestamp_epoch": base_epoch + 31.5,
                     "trace_byte_start": 10, "trace_byte_end": 18,
                     "prompt_tokens": 100, "cached_tokens": 10,
                     "completion_tokens": 20, "sdk_total_tokens": 120,
                     "cost_label": "actual", "cost_usd": 0.0001},
                    {"source": "combat_reengage", "call_id": "call-5",
                     "attempt_id": "attempt-5", "timestamp_epoch": base_epoch + 31.6,
                     "trace_byte_start": 30, "trace_byte_end": 38,
                     "prompt_tokens": 200, "cached_tokens": 20,
                     "completion_tokens": 40, "sdk_total_tokens": 240,
                     "cost_label": "estimated", "cost_usd": 0.0002},
                ]}
            resume_evaluation = {
                "startup_receipt_validation": resume_startup_validation,
                "expected_usage_status": "ok",
                "usage_step_receipts": {"status": "none_observed", "receipts": []},
                "usage_reconciliation_problems": [],
            }
            complete_sections = complete_usage["observed"]["sections"]
            resume_sections = resume_usage["observed"]["sections"]
            complete_manifest = dict(common, run_id="complete-run", g10={
                "lifecycle": {"status": "finalized"}})
            resume_manifest = dict(common, run_id="resume-run", g10={
                "lifecycle": {"status": "finalized"}})
            snapshots = {
                "complete_after": {"mechanical_projection": projection,
                                   "g10_reward_projection": rewards},
                "resume_before": {"mechanical_projection": projection,
                                  "g10_reward_projection": rewards},
                "resume_after": {"mechanical_projection": projection,
                                 "g10_reward_projection": rewards},
            }
            for bundle, phase, save, usage, tracker, rows in (
                    (complete_dir, "complete", saved_state, complete_usage,
                     complete_tracker, {"after_snapshot": snapshots["complete_after"]}),
                    (resume_dir, "resume", resume_save, resume_usage,
                     resume_tracker, {"before_snapshot": snapshots["resume_before"],
                                      "after_snapshot": snapshots["resume_after"]})):
                marker = {"complete_run_dir": complete_relative}
                _write_json(bundle / "g10_marker.json", marker)
                _write_json(bundle / "g10_save_state.json", save)
                _write_json(bundle / "g10_usage.json", usage)
                _write_json(bundle / "g10_tracker_telemetry.json", tracker)
                for name, snapshot in rows.items():
                    _write_json(bundle / (name + ".json"), snapshot)
                (bundle / "server_lifecycle.jsonl").write_text(json.dumps({
                    "event": "server_started" if phase == "complete" else "resume_server_started",
                    "server_pid": 101 if phase == "complete" else 202,
                }) + "\n", encoding="ascii")
                refs = {"g10_marker": "g10_marker.json", "g10_save_state": "g10_save_state.json",
                        "g10_usage": "g10_usage.json",
                        "g10_tracker_telemetry": "g10_tracker_telemetry.json", **{
                            name: name + ".json" for name in rows
                        }}
                if phase == "complete":
                    complete_manifest["artifacts"] = refs
                    _rehash_g10_save_artifact(bundle, complete_manifest)
                else:
                    resume_manifest["artifacts"] = refs
                    _rehash_g10_save_artifact(bundle, resume_manifest)
            complete_row = {"run_dir": str(complete_dir), "manifest": complete_manifest}
            resume_row = {"run_dir": str(resume_dir), "manifest": resume_manifest,
                          "evaluation": resume_evaluation}
            replaced_sandbox = root / "combat_capture"
            replaced_sandbox.mkdir()
            (replaced_sandbox / "phase").write_text("old", encoding="ascii")
            shutil.rmtree(replaced_sandbox)
            replaced_sandbox.mkdir()
            (replaced_sandbox / "phase").write_text("replacement", encoding="ascii")
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertEqual(pair["status"], "READY_FOR_PRIMARY_REVIEW", pair)
            self.assertEqual(pair["resume_startup_usage"]["router"]["calls"], 2)
            self.assertEqual(pair["resume_startup_usage"]["session"]["tokens"], 360)
            live_projection_mock.assert_not_called()

            complete_save_path = complete_dir / "g10_save_state.json"
            resume_save_path = resume_dir / "g10_save_state.json"
            complete_save_raw = complete_save_path.read_bytes()
            resume_save_raw = resume_save_path.read_bytes()
            complete_digest = complete_manifest["artifact_sha256"]["g10_save_state.json"]
            resume_digest = resume_manifest["artifact_sha256"]["g10_save_state.json"]

            missing_diary = json.loads(complete_save_raw.decode("utf-8"))
            missing_diary.pop("diary_identifier_evidence")
            _write_json(complete_save_path, missing_diary)
            _rehash_g10_save_artifact(complete_dir, complete_manifest)
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertEqual(pair["status"], "BLOCKED", pair)
            self.assertIn("g10_diary_identifier_evidence_missing", pair["problems"])
            complete_save_path.write_bytes(complete_save_raw)
            complete_manifest["artifact_sha256"]["g10_save_state.json"] = complete_digest

            tampered_diary = json.loads(resume_save_raw.decode("utf-8"))
            tampered_diary["diary_identifier_evidence"]["resumed_state"]["projection"][
                "entries"][1]["diary_id"] = 9
            _write_json(resume_save_path, tampered_diary)
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertEqual(pair["status"], "FAIL", pair)
            self.assertIn("g10_diary_identifier_artifact_hash_mismatch", pair["failures"])
            resume_save_path.write_bytes(resume_save_raw)
            resume_manifest["artifact_sha256"]["g10_save_state.json"] = resume_digest

            inner_tamper = json.loads(resume_save_raw.decode("utf-8"))
            inner_tamper["diary_identifier_evidence"]["resumed_state"]["projection"][
                "entries"][1]["source_end_event_id"] = 21
            _write_json(resume_save_path, inner_tamper)
            _rehash_g10_save_artifact(resume_dir, resume_manifest)
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertEqual(pair["status"], "FAIL", pair)
            self.assertIn("g10_diary_identifier_projection_hash_mismatch", pair["failures"])
            resume_save_path.write_bytes(resume_save_raw)
            resume_manifest["artifact_sha256"]["g10_save_state.json"] = resume_digest

            for label, mutate in (
                    ("duplicate_diary_id", lambda projection: projection["entries"][1].update(
                        diary_id=1)),
                    ("overlapping_event_range", lambda projection: projection["entries"][1].update(
                        source_start_event_id=10, source_end_event_id=20)),
                    ("wrong_state_id", lambda projection: projection["state"][0].update(
                        state_id=2)),
                    ("wrong_draft_status", lambda projection: projection["entries"][1].update(
                        status="confirmed"))):
                with self.subTest(diary_projection=label):
                    changed_diary = json.loads(resume_save_raw.decode("utf-8"))
                    changed_projection = changed_diary["diary_identifier_evidence"][
                        "resumed_state"]["projection"]
                    mutate(changed_projection)
                    _rehash_diary_projection_record(
                        changed_diary["diary_identifier_evidence"]["resumed_state"]
                    )
                    _write_json(resume_save_path, changed_diary)
                    _rehash_g10_save_artifact(resume_dir, resume_manifest)
                    pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
                    self.assertEqual(pair["status"], "FAIL", pair)
                    if label in ("duplicate_diary_id", "overlapping_event_range"):
                        expected_failure = "g10_diary_identifier_projection_contradictory"
                    elif label == "wrong_state_id":
                        expected_failure = "g10_resumed_diary_draft_not_semantically_distinct"
                    else:
                        expected_failure = "g10_resumed_diary_checkpoint_or_draft_duplicated"
                    self.assertIn(expected_failure, pair["failures"])
                    resume_save_path.write_bytes(resume_save_raw)
                    resume_manifest["artifact_sha256"]["g10_save_state.json"] = resume_digest

            usage_call_evaluation = copy.deepcopy(resume_evaluation)
            usage_call_evaluation["usage_step_receipts"] = {
                "status": "ok", "receipts": [{"call_id": "usage-call"}],
            }
            resume_row["evaluation"] = usage_call_evaluation
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertIn("g10_usage_command_made_or_failed_to_exclude_provider_request",
                          pair["failures"])
            resume_row["evaluation"] = resume_evaluation

            duplicated_startup = copy.deepcopy(resume_evaluation)
            duplicated_startup["startup_receipt_validation"]["receipts"][1]["source"] = (
                "session_diary_checkpoint_summary"
            )
            pair = capture_evidence._compare_g10_chain(
                complete_row, dict(resume_row, evaluation=duplicated_startup), 1
            )
            self.assertIn("g10_resume_startup_semantic_call_duplicated", pair["failures"])

            broken_link = copy.deepcopy(resume_tracker)
            broken_link["prior_link"]["complete_artifact_sha256"] = "e" * 64
            _write_json(resume_dir / "g10_tracker_telemetry.json", broken_link)
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertEqual(pair["status"], "FAIL")
            self.assertIn("g10_tracker_complete_resume_boundary_mismatch",
                          pair["failures"])
            _write_json(resume_dir / "g10_tracker_telemetry.json", resume_tracker)

            changed_window = copy.deepcopy(resume_tracker)
            for snapshot_name in ("pre_run", "post_usage", "post_shutdown"):
                snapshot = changed_window[snapshot_name]
                snapshot["window_days"] = 6
                snapshot["cutoff_epoch"] = snapshot["captured_at_epoch"] - 6 * 86400
                snapshot["cutoff_local"] = datetime.fromtimestamp(
                    snapshot["cutoff_epoch"]
                ).isoformat()
            _write_json(resume_dir / "g10_tracker_telemetry.json", changed_window)
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertIn("g10_tracker_complete_resume_boundary_mismatch", pair["failures"])
            _write_json(resume_dir / "g10_tracker_telemetry.json", resume_tracker)

            week_mutations = (
                ("tokens", lambda week: week.update(tokens=901)),
                ("actual_cost", lambda week: week.update(actual_usd=0.002,
                                                          known_cost_usd=0.0027)),
                ("unpriced_calls", lambda week: week.update(unpriced_calls=2)),
                ("cost_coverage", lambda week: week.update(unpriced_calls=0,
                                                           cost_coverage="complete")),
            )
            for label, mutate_week in week_mutations:
                with self.subTest(week_field=label):
                    changed_week = copy.deepcopy(resume_sections)
                    mutate_week(changed_week["week"])
                    _write_json(resume_dir / "g10_usage.json", {
                        "status": "ok", "observed": {"sections": changed_week},
                        "router_receipts": {"status": "none_observed", "receipts": []},
                    })
                    pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
                    self.assertEqual(pair["status"], "FAIL")
                    self.assertIn("g10_rolling_week_usage_not_startup_receipt_derived",
                                  pair["failures"])

            _write_json(resume_dir / "g10_usage.json", resume_usage)

            changed_after = dict(
                snapshots["resume_after"],
                mechanical_projection={"hitPoints": 9, "currency": {"gp": 0}},
                g10_reward_projection={"duplicate_reward": True},
            )
            _write_json(resume_dir / "after_snapshot.json", changed_after)
            nonzero_sections = copy.deepcopy(resume_sections)
            nonzero_sections["session"]["tokens"] = 4
            _write_json(resume_dir / "g10_usage.json", {
                "status": "ok", "observed": {"sections": nonzero_sections},
                "router_receipts": {"status": "none_observed", "receipts": []},
            })
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertEqual(pair["status"], "FAIL")
            self.assertIn("g10_mechanics_or_rewards_changed_across_resume", pair["failures"])
            self.assertIn("g10_inventory_or_reward_state_changed_across_resume", pair["failures"])
            self.assertIn("g10_resume_usage_totals_not_startup_receipt_derived",
                          pair["failures"])
            self.assertIn("g10_resume_receipt_set_not_exactly_startup_calls",
                          pair["failures"])

            (resume_dir / "server_lifecycle.jsonl").write_text(json.dumps({
                "event": "resume_server_started", "server_pid": 101,
            }) + "\n", encoding="ascii")
            pair = capture_evidence._compare_g10_chain(complete_row, resume_row, 1)
            self.assertIn("g10_resume_did_not_restart_owned_server", pair["failures"])


if __name__ == "__main__":
    unittest.main()
