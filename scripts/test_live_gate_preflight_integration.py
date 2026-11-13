# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic SP3 row-preflight integration tests; these are not live coverage."""

from __future__ import annotations

import hashlib
import json
import errno
import os
import signal
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import live_gate_preflight_controller as controller
from scripts import live_gate_preflight_evidence as evidence
from scripts.live_gate_preflight_controller import (
    PreflightInterfaces,
    _load_frozen_row_ids,
    _load_profiles,
    _resolve_row_plan,
    planned_worker_identity,
    run_preflight_rows,
)
from scripts import live_gate_preflight_sandbox as sandbox
from scripts import live_gate_preflight_profile_runner as profile_runner
from scripts import live_gate_preflight_retained as retained
from scripts import live_gate_preflight_safety as safety
from scripts.mapping_pilot import launcher, row_runner, server


SOURCE_SHA = "a" * 40
RUN_ID = "row-integration-test"


def _synthetic_call_site(
    source_file: str = "scripts/live_gate_preflight_controller.py", count: int = 1
) -> dict[str, Any]:
    source_bytes = (PROJECT_ROOT / source_file).read_bytes()
    return {
        "source_file": source_file,
        "source_line": 1,
        "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "count": count,
    }


class _FakeDecodeScope:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeCaptureSession:
    """Fake the Socket.IO session boundary under the real script adapter."""

    def __init__(self, args: Any, sessions: list["_FakeCaptureSession"]) -> None:
        self.args = args
        self.sessions = sessions
        self.sessions.append(self)
        self.game_outputs: list[dict[str, Any]] = []
        self.sent: list[tuple[str, str, str]] = []
        self.start_readiness = {"ready": True}
        self.disconnected = False
        self.transcript_closed = False

    def open_transcript(self) -> None:
        return None

    def connect(self) -> None:
        return None

    def start_session(self, *, require_ready_quiet: bool) -> bool:
        return require_ready_quiet

    def set_active_character(self, character: str) -> bool:
        return bool(character)

    def output_count(self) -> int:
        return len(self.game_outputs)

    def send_turn(self, step_id: str, utterance: str, character: str) -> Any:
        self.sent.append((step_id, utterance, character))
        self.game_outputs.append(
            {"payload": {"content": "provider-free stub response"}}
        )
        return SimpleNamespace(
            timed_out=False,
            backend_output_count=1,
            new_game_outputs=1,
            elapsed_seconds=0.01,
        )

    def disconnect(self) -> None:
        self.disconnected = True

    def close_transcript(self) -> None:
        self.transcript_closed = True


class _FakeServerLauncher:
    def __init__(self, row_id: str, launches: list[dict[str, Any]]) -> None:
        self.row_id = row_id
        self.launches = launches

    def launch(self, **kwargs: Any) -> Any:
        self.launches.append({"row_id": self.row_id, **kwargs})
        return SimpleNamespace(row_id=self.row_id)


class TestPreflightRowIntegration(unittest.TestCase):
    def setUp(self) -> None:
        global RUN_ID
        RUN_ID = "rtest-" + uuid.uuid4().hex[:12]
        self.retained_run_directory = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / RUN_ID
        )
        self.addCleanup(
            shutil.rmtree, self.retained_run_directory, ignore_errors=True
        )
        self.fake_common_directory: Path | None = None
        self._git_common_patch = mock.patch.object(
            profile_runner,
            "_git_common_directory",
            side_effect=self._fake_git_common_directory,
        )
        self._git_common_patch.start()
        self.addCleanup(self._git_common_patch.stop)

    def _fake_git_common_directory(self) -> Path:
        if self.fake_common_directory is None:
            raise AssertionError("synthetic durable lock directory was not prepared")
        return self.fake_common_directory

    @staticmethod
    def _synthetic_free_bind_observation(port: int) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "method": "exclusive-bind-close",
            "transport": "tcp",
            "address": "127.0.0.1",
            "port": port,
            "reuse_address": False,
            "observed_at_ns": 2_000_003,
            "socket_created": True,
            "bind_attempted": True,
            "bind_succeeded": True,
            "socket_closed": True,
            "result": "free",
            "error_errno": None,
            "error_type": None,
            "observation_complete": True,
        }

    @staticmethod
    def _caller_declared_identity(
        plan: controller.PreflightRowPlan,
        *,
        fixture_id: str,
        lifecycle: str,
        row_run_id: str,
        resume_checkpoint_sha256: str | None = None,
    ) -> dict[str, Any]:
        lifecycle_id = row_run_id + ("_s" if lifecycle == "startup" else "_r")
        command = [
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
            "-P",
            "-m",
            "scripts.live_gate_preflight_profile_runner",
            "--worker",
            "--fixture-id",
            fixture_id,
            "--party-size",
            str(plan.party_size),
            "--lifecycle",
            lifecycle,
            "--source-sha",
            SOURCE_SHA,
            "--run-id",
            row_run_id,
            "--planned-row-id",
            plan.row_id,
            "--arm",
            plan.arm,
            "--lifecycle-id",
            lifecycle_id,
        ]
        if resume_checkpoint_sha256 is not None:
            command.extend(("--resume-checkpoint-sha256", resume_checkpoint_sha256))
        command.extend(("--preflight-run-id", RUN_ID))
        return {
            "command": command,
            "working_directory": str(PROJECT_ROOT / "tmp" / "combat_capture"),
            "pythonpath": os.pathsep.join(
                (
                    str(PROJECT_ROOT / "scripts" / "live_gate_preflight_guard"),
                    str(PROJECT_ROOT),
                )
            ),
        }

    @staticmethod
    def _lifecycle_row_run_id(
        plan: controller.PreflightRowPlan, fixture_id: str, lifecycle: str
    ) -> str:
        base = "pf-%s-%s" % (RUN_ID, plan.row_id)
        if fixture_id == plan.fixture_id and lifecycle == "startup":
            return base
        suffix = "s" if lifecycle == "startup" else "r"
        return "%s-f%d-%s" % (base, plan.fixture_ids.index(fixture_id) + 1, suffix)

    def _lifecycle_identity_declaration(
        self,
        plan: controller.PreflightRowPlan,
        *,
        fixture_id: str,
        lifecycle: str,
        resume_checkpoint_sha256: str | None = None,
    ) -> dict[str, Any]:
        row_run_id = self._lifecycle_row_run_id(plan, fixture_id, lifecycle)
        return self._caller_declared_identity(
            plan,
            fixture_id=fixture_id,
            lifecycle=lifecycle,
            row_run_id=row_run_id,
            resume_checkpoint_sha256=resume_checkpoint_sha256,
        )

    def _fake_characterization(
        self,
        args: Any,
        *,
        driver_exchange: dict[str, Any] | None = None,
        observed_call_count: int = 1,
        observed_call_sites: list[dict[str, Any]] | None = None,
        server_returned: bool = True,
    ) -> tuple[dict[str, Any], str, str]:
        command = profile_runner._host_command(
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            lifecycle=args.lifecycle,
            source_sha=args.source_sha,
            run_id=args.run_id,
            planned_row_id=args.planned_row_id,
            arm=args.arm,
            lifecycle_id=args.run_id + ("_s" if args.lifecycle == "startup" else "_r"),
            resume_checkpoint_sha256=args.resume_checkpoint_sha256,
            preflight_run_id=args.preflight_run_id,
        )
        rows, _reserves = _load_frozen_row_ids(None)
        frozen_row = next(row for row in rows if row["row_id"] == args.planned_row_id)
        profile_map, _coverage = _load_profiles([row["row_id"] for row in rows])
        plan = _resolve_row_plan(
            args.planned_row_id,
            prereg_root=None,
            expected_row=frozen_row,
            profiles=profile_map,
        )
        call_sites = observed_call_sites or [
            _synthetic_call_site(count=observed_call_count)
        ]
        call_count = sum(site["count"] for site in call_sites)
        pythonpath = safety.expected_guarded_pythonpath(PROJECT_ROOT)
        calls = [
            {
                "sequence": sequence,
                "task": "dm_main",
                "source_file": site["source_file"],
                "source_line": site["source_line"],
                "source_file_sha256": site["source_file_sha256"],
                "source_sha": args.source_sha,
                "command": command,
                "pythonpath": pythonpath,
            }
            for sequence, site in enumerate(
                [site for site in call_sites for _ in range(site["count"])], start=1
            )
        ]
        evidence_directory = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / args.preflight_run_id
            / "preflight"
            / "rows"
            / args.run_id
        )
        evidence_directory.mkdir(parents=True, exist_ok=True)
        controller_pid, host_prelaunch_pid, host_worker_pid = 101, 102, 103
        interpreter = profile_runner._interpreter_identity()
        host_cwd = str(PROJECT_ROOT / "tmp" / "combat_capture")
        runner_command = [
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
            "-m",
            "scripts.live_gate_preflight_profile_runner",
            "--synthetic-controller",
            "--run-id",
            args.run_id,
        ]

        def command_hash(argv: list[str]) -> str:
            return hashlib.sha256(
                json.dumps(argv, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            ).hexdigest()

        def process_events(
            pid: int, role: str, argv: list[str], cwd: str
        ) -> list[dict[str, Any]]:
            common = {
                "schema_version": 1,
                "pid": pid,
                "process_group_id": pid,
                "process_role": role,
                "run_id": args.run_id,
                "target_host": None,
                "target_port": None,
                "target_host_sha256": None,
                "command_sha256": None,
                "child_pid": None,
                "child_is_python": None,
                "guard_active": None,
                "interpreter": None,
                "working_directory": None,
            }
            return [
                {
                    **common,
                    "sequence": 1,
                    "event_type": "guard_startup",
                    "observed_at_ns": 1_000_001,
                    "operation": None,
                    "decision": None,
                    "command_sha256": command_hash(argv),
                    "guard_active": True,
                    "interpreter": interpreter,
                    "working_directory": cwd,
                },
                {
                    **common,
                    "sequence": 2,
                    "event_type": "network_attempt",
                    "observed_at_ns": 1_000_002,
                    "operation": "connect",
                    "decision": "denied",
                    "target_host": "192.0.2.1",
                    "target_port": 8360,
                },
                {
                    **common,
                    "sequence": 3,
                    "event_type": "subprocess_attempt",
                    "observed_at_ns": 1_000_003,
                    "operation": "Popen",
                    "decision": "denied",
                    "command_sha256": "d" * 64,
                },
            ]

        specs = (
            (
                "controller-startup",
                "parent",
                controller_pid,
                runner_command,
                str(evidence_directory),
            ),
            (
                "host-prelaunch",
                "host",
                host_prelaunch_pid,
                command,
                host_cwd,
            ),
            ("host-startup", "host", host_worker_pid, command, host_cwd),
        )
        canaries: list[dict[str, Any]] = []
        snapshots: dict[str, list[dict[str, Any]]] = {}
        journal: list[dict[str, Any]] = []
        for stage, role, pid, argv, cwd in specs:
            events = process_events(pid, role, argv, cwd)
            snapshots[stage] = events
            journal.extend(events)
            canaries.append(
                {
                    "canary_stage": stage,
                    "process_role": role,
                    "pid": pid,
                    "startup_observed_at_ns": 1_000_000 + pid,
                    "command": argv,
                    "command_sha256": command_hash(argv),
                    "environment_sha256": "a" * 64 if role == "parent" else "b" * 64,
                    "working_directory": cwd,
                    "guard_active": True,
                    "non_loopback_connect_denied": True,
                    "subprocess_launch_denied": True,
                    "interpreter": interpreter,
                    "guard_events_complete": True,
                    "guard_events": events,
                }
            )
        journal_path = evidence_directory / "guard-events.jsonl"
        journal_bytes = b"".join(
            json.dumps(
                event, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
            + b"\n"
            for event in journal
        )
        journal_path.write_bytes(journal_bytes)
        journal_descriptor = {
            "path": journal_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": hashlib.sha256(journal_bytes).hexdigest(),
            "event_count": len(journal),
            "complete": True,
        }

        def scope(stage: str, selector: str, role: str, source: str) -> dict[str, Any]:
            report = next(item for item in canaries if item["canary_stage"] == stage)
            return {
                "selector": selector,
                "pid": report["pid"],
                "process_group_id": report["pid"],
                "process_role": role,
                "launch_source": source,
                "command_sha256": report["command_sha256"],
                "environment_sha256": report["environment_sha256"],
                "working_directory_sha256": hashlib.sha256(
                    report["working_directory"].encode("utf-8")
                ).hexdigest(),
            }

        all_scopes = [
            scope("controller-startup", "pid", "parent", "controller-startup-canary"),
            scope("host-prelaunch", "process_group", "host", "host-prelaunch-canary-session"),
            scope("host-startup", "process_group", "host", "host-worker-start-new-session"),
        ]
        rows_by_phase = {
            "before_host": [],
            "host_ready": [
                {
                    "protocol": "tcp4",
                    "local": {"host": "127.0.0.1", "port": 8360},
                    "foreign": {"host": "*", "port": None},
                    "state": "LISTEN",
                    "pid": host_worker_pid,
                },
                {
                    "protocol": "tcp4",
                    "local": {"host": "127.0.0.1", "port": 59635},
                    "foreign": {"host": "127.0.0.1", "port": 8360},
                    "state": "ESTABLISHED",
                    "pid": controller_pid,
                },
            ],
            "after_teardown": [
                {
                    "protocol": "tcp4",
                    "local": {"host": "127.0.0.1", "port": 59635},
                    "foreign": {"host": "127.0.0.1", "port": 8360},
                    "state": "TIME_WAIT",
                    "pid": controller_pid,
                }
            ],
        }
        census_samples: list[dict[str, Any]] = []
        for phase in ("before_host", "host_ready", "after_teardown"):
            phase_canaries = canaries[:2] if phase == "before_host" else canaries
            phase_events = [
                event
                for report in phase_canaries
                for event in snapshots[report["canary_stage"]]
            ]
            phase_scopes = all_scopes[:2] if phase == "before_host" else all_scopes
            rows = rows_by_phase[phase]
            pids = sorted({row["pid"] for row in rows})
            count_fields = (
                "internet_rows", "unattributed_rows", "pid_zero_rows",
                "foreign_process_rows", "run_pid_rows", "malformed_run_pid_rows",
            )
            aggregate = {key: 0 for key in count_fields}
            protocol_samples: list[dict[str, Any]] = []
            for protocol in ("tcp", "udp"):
                protocol_count = sum(row["protocol"].startswith(protocol) for row in rows)
                counts = {key: 0 for key in count_fields}
                counts["internet_rows"] = protocol_count
                counts["run_pid_rows"] = protocol_count
                for key in count_fields:
                    aggregate[key] += counts[key]
                protocol_samples.append(
                    {
                        "protocol": protocol,
                        "command_evidence": {
                            "command": ["/usr/sbin/netstat", "-anv", "-W", "-p", protocol],
                            "returncode": 0,
                            "failure": None,
                            "stdout_byte_count": 1,
                            "stdout_sha256": "e" * 64,
                            "stdout_truncated": False,
                            "stdout_prefix_base64": "",
                            "stderr_byte_count": 0,
                            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                            "stderr_truncated": False,
                            "stderr_prefix_base64": "",
                            "observed": True,
                        },
                        "counts": counts,
                        "parseable": True,
                    }
                )
            sidecar = {
                "schema_version": 3,
                "run_id": args.run_id,
                "phase": phase,
                "observer": "netstat -anv -W -p tcp and udp; PID filter precedes endpoint parsing",
                "process_scopes": phase_scopes,
                "run_process_pids": sorted({event["pid"] for event in phase_events}),
                "guard_startup_pids": sorted(
                    event["pid"]
                    for event in phase_events
                    if event["event_type"] == "guard_startup"
                ),
                "protocol_samples": protocol_samples,
                "aggregate_counts": aggregate,
                "run_owned_rows": rows,
                "pids": pids,
                "observed": True,
                "failure_code": None,
            }
            sidecar_path = evidence_directory / ("socket-sample-%s.json" % phase)
            sidecar_path.write_text(
                json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            listeners = sorted(
                row["pid"]
                for row in rows
                if row["protocol"] in ("tcp", "tcp4", "tcp6")
                and row["state"] == "LISTEN"
                and row["local"]["port"] == 8360
            )
            census_samples.append(
                {
                    "phase": phase,
                    "port": 8360,
                    "observed": True,
                    "pids": pids,
                    "listener_pids": listeners,
                    "failure_code": None,
                    "evidence_path": sidecar_path.relative_to(PROJECT_ROOT).as_posix(),
                    "evidence_sha256": hashlib.sha256(sidecar_path.read_bytes()).hexdigest(),
                }
            )
        socket_owners = sorted({pid for sample in census_samples for pid in sample["pids"]})
        canary_pids = [item["pid"] for item in canaries]
        census = {
            "controller_pid": controller_pid,
            "driver_pid": controller_pid,
            "host_prelaunch_pid": host_prelaunch_pid,
            "host_worker_pid": host_worker_pid,
            "launched_pids": sorted((controller_pid, host_prelaunch_pid, host_worker_pid)),
            "socket_owner_pids": socket_owners,
            "python_child_pids": [],
            "python_pids": sorted((controller_pid, host_prelaunch_pid, host_worker_pid)),
            "guarded_pids": canary_pids,
            "canary_pids": canary_pids,
            "uncovered_pids": [],
            "guard_events_valid": True,
            "socket_pid_samples": census_samples,
            "complete": True,
        }
        request = {
            "schema_version": 1,
            "run_id": args.run_id,
            "controller_pid": controller_pid,
            "worker_pid": host_worker_pid,
            "process_group_id": host_worker_pid,
            "signal_number": int(signal.SIGINT),
            "requested_at_ns": 2_000_000,
            "readiness_succeeded": True,
            "exchange_succeeded": True,
        }
        (evidence_directory / "shutdown-request.json").write_text(
            json.dumps(request, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        exchange = dict(driver_exchange or {})
        exchange.update(
            {
                "status": "completed",
                "step_id": plan.first_turn["step_id"],
                "start_ready": True,
                "active_character_set": True,
                "turn_completed": True,
                "turn_timed_out": False,
                "game_output_count": max(1, int(exchange.get("game_output_count", 1))),
                "failure_code": None,
                "process_pid": controller_pid,
            }
        )
        received_at_ns = 2_000_001
        startup_report = {key: value for key, value in canaries[2].items() if key != "canary_stage"}
        worker_result = {
            "schema_version": 1,
            "run_id": args.run_id,
            "source_sha": args.source_sha,
            "command": command,
            "pythonpath": pythonpath,
            "invocation_identity": safety.compare_invocation_identity(
                {"command": command, "working_directory": host_cwd, "pythonpath": pythonpath},
                {"command": command, "working_directory": host_cwd, "pythonpath": pythonpath},
            ),
            "interpreter": interpreter,
            "startup_canary_report": json.dumps(
                startup_report, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ),
            "guard_active": True,
            "provider_environment_keys_blank": True,
            "sandbox_provider_key_placeholder": safety.SANDBOX_PROVIDER_KEY_PLACEHOLDER,
            "proxy_values_blank": True,
            "real_project_config_loaded": False,
            "sandbox_config_loaded": True,
            "startup_guard_from_sitecustomize": True,
            "sandbox_config_origin_guard_active": True,
            "server_returned": server_returned,
            "interrupted": True,
            "graceful_shutdown_requested": True,
            "shutdown_request": request,
            "shutdown_signal_received_at_ns": received_at_ns,
            "outcome": "completed",
            "failure_code": None,
            "stub_failure_code": None,
            "call_count": call_count,
            "calls": calls,
        }
        (evidence_directory / "worker-result.json").write_text(
            json.dumps(worker_result, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        lock_record = profile_runner._build_live_window_lock_record(
            run_id=args.run_id,
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            lifecycle=args.lifecycle,
            planned_row_id=args.planned_row_id,
            source_sha=args.source_sha,
            now=datetime.now(timezone.utc),
        )
        evidence_path = (
            evidence_directory / "profile-evidence.json"
        ).relative_to(PROJECT_ROOT).as_posix()
        teardown_path = (
            evidence_directory / "teardown-evidence.json"
        ).relative_to(PROJECT_ROOT).as_posix()
        release_record = {
            **lock_record,
            "event": "released",
            "released_at_utc": profile_runner._format_utc_timestamp(
                datetime.now(timezone.utc)
            ),
            "server_stopped": True,
            "ports_free": {"8360": True, "8370": True},
            "after_teardown_socket_sample_observed": True,
            "after_teardown_socket_pids": census_samples[2]["pids"],
            "after_teardown_socket_sample_path": census_samples[2][
                "evidence_path"
            ],
            "after_teardown_socket_sample_sha256": census_samples[2][
                "evidence_sha256"
            ],
            "evidence_path": evidence_path,
            "teardown_evidence_schema_version": 1,
            "teardown_evidence_path": teardown_path,
        }
        self.fake_common_directory = (
            self.retained_run_directory / "fake-git-common" / args.run_id
        )
        coordination = self.fake_common_directory / "neq-coordination"
        coordination.mkdir(parents=True, exist_ok=True)
        booking_line = json.dumps(
            lock_record, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii") + b"\n"
        release_line = json.dumps(
            release_record, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii") + b"\n"
        booking_log = coordination / "bookings.log"
        booking_log.write_bytes(booking_line + release_line)
        durable_record = {
            "path": booking_log.relative_to(PROJECT_ROOT).as_posix(),
            "byte_offset": len(booking_line),
            "byte_length": len(release_line),
            "line_sha256": hashlib.sha256(release_line).hexdigest(),
        }
        after_teardown_sample = census_samples[2]
        teardown_sidecar = {
            "schema_version": 1,
            "run_id": args.run_id,
            "preflight_run_id": args.preflight_run_id,
            "source_sha": args.source_sha,
            "runner_source_sha256": hashlib.sha256(
                Path(profile_runner.__file__).read_bytes()
            ).hexdigest(),
            "booking_id": lock_record["booking_id"],
            "controller_pid": controller_pid,
            "worker_stop": {
                "observed": True,
                "worker_pid": host_worker_pid,
                "process_group_id": host_worker_pid,
                "stop_operation": "owned-process-group-wait",
                "requested_signal": int(signal.SIGINT),
                "shutdown_request_path": (
                    evidence_directory / "shutdown-request.json"
                ).relative_to(PROJECT_ROOT).as_posix(),
                "shutdown_request_sha256": hashlib.sha256(
                    (evidence_directory / "shutdown-request.json").read_bytes()
                ).hexdigest(),
                "worker_result_path": (
                    evidence_directory / "worker-result.json"
                ).relative_to(PROJECT_ROOT).as_posix(),
                "worker_result_sha256": hashlib.sha256(
                    (evidence_directory / "worker-result.json").read_bytes()
                ).hexdigest(),
                "server_returned": server_returned,
                "interrupted": True,
                "graceful_shutdown_requested": True,
                "signal_received_at_ns": received_at_ns,
                "returncode": 0,
                "reaped": True,
                "observed_at_ns": received_at_ns + 1,
            },
            "port_observations": {
                "8360": self._synthetic_free_bind_observation(8360),
                "8370": self._synthetic_free_bind_observation(8370),
            },
            "socket_census": {
                "phase": "after_teardown",
                "path": after_teardown_sample["evidence_path"],
                "sha256": after_teardown_sample["evidence_sha256"],
                "observed": after_teardown_sample["observed"],
                "pids": after_teardown_sample["pids"],
                "listener_pids": after_teardown_sample["listener_pids"],
            },
            "shared_lock": {
                "release_attempted": True,
                "lock_directory_removed": True,
                "release_succeeded": True,
                "booking_record": lock_record,
                "release_record": release_record,
                "durable_record": durable_record,
            },
        }
        teardown_file = evidence_directory / "teardown-evidence.json"
        teardown_file.write_text(
            json.dumps(
                teardown_sidecar,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="ascii",
        )
        evidence = {
            "schema_version": 1,
            "authorization_ruling_id": profile_runner.AUTHORIZATION_RULING_ID,
            "profile_id": next(
                profile["profile_id"]
                for profile in plan.lifecycle_profiles
                if profile["fixture_id"] == args.fixture_id
            ),
            "outcome": "completed",
            "run_id": args.run_id,
            "source_sha": args.source_sha,
            "planned_row_id": args.planned_row_id,
            "fixture_id": args.fixture_id,
            "party_size": args.party_size,
            "lifecycle": args.lifecycle,
            "arm": args.arm,
            "sandbox_root": "tmp/combat_capture",
            "command": command,
            "working_directory": "tmp/combat_capture",
            "pythonpath": pythonpath,
            "invocation_identity": worker_result["invocation_identity"],
            "process_canaries": canaries,
            "guard_event_journal": journal_descriptor,
            "process_census": census,
            "worker_shutdown": {
                "server_returned": server_returned,
                "interrupted": True,
                "graceful_shutdown_requested": True,
                "signal_received_at_ns": received_at_ns,
                "request": request,
            },
            "controller_interpreter": interpreter,
            "worker_interpreter": interpreter,
            "network_guard_active": True,
            "provider_environment_keys_blank": True,
            "sandbox_provider_key_placeholder": safety.SANDBOX_PROVIDER_KEY_PLACEHOLDER,
            "proxy_values_blank": True,
            "real_project_config_loaded": False,
            "sandbox_config_loaded": True,
            "startup_guard_from_sitecustomize": True,
            "sandbox_config_origin_guard_active": True,
            "driver_exchange": exchange,
            "calls": calls,
            "call_count": call_count,
            "call_sites": call_sites,
            "host_command": command,
            "runner_command": runner_command,
            "failure_code": None,
            "teardown": {
                "server_stopped": True,
                "port_8360_free": True,
                "port_8370_free": True,
                "lock_released": True,
            },
            "teardown_evidence": {
                "path": teardown_path,
                "sha256": hashlib.sha256(teardown_file.read_bytes()).hexdigest(),
            },
        }
        evidence_file = evidence_directory / "profile-evidence.json"
        evidence_file.write_text(
            json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        return (
            evidence,
            evidence_file.relative_to(PROJECT_ROOT).as_posix(),
            hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
        )

    def _retained_case(
        self, *, server_returned: bool = True
    ) -> tuple[controller.PreflightRowPlan, str, dict[str, Any], dict[str, Any]]:
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        frozen_row = next(row for row in rows if row["row_id"] == "E01")
        plan = _resolve_row_plan(
            "E01", prereg_root=None, expected_row=frozen_row, profiles=profiles
        )
        row_run_id = "pf-retained-" + uuid.uuid4().hex[:10]
        args = SimpleNamespace(
            fixture_id=plan.fixture_id,
            party_size=plan.party_size,
            lifecycle="startup",
            source_sha=SOURCE_SHA,
            run_id=row_run_id,
            planned_row_id=plan.row_id,
            arm=plan.arm,
            resume_checkpoint_sha256=None,
            preflight_run_id=RUN_ID,
        )
        evidence, evidence_path, evidence_sha256 = self._fake_characterization(
            args, server_returned=server_returned
        )
        intended_identity = planned_worker_identity(
            plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            source_sha=SOURCE_SHA,
            row_run_id=row_run_id,
            resume_checkpoint_sha256=None,
            preflight_run_id=RUN_ID,
        )
        result = {
            "evidence": evidence,
            "evidence_path": evidence_path,
            "evidence_sha256": evidence_sha256,
        }
        return plan, row_run_id, intended_identity, result

    @staticmethod
    def _rewrite_profile_evidence(result: dict[str, Any], evidence: dict[str, Any]) -> None:
        evidence_path = PROJECT_ROOT / result["evidence_path"]
        raw = json.dumps(
            evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        evidence_path.write_bytes(raw)
        result["evidence"] = evidence
        result["evidence_sha256"] = hashlib.sha256(raw).hexdigest()

    def _rewrite_teardown_sidecar(
        self, result: dict[str, Any], sidecar: dict[str, Any]
    ) -> None:
        evidence = result["evidence"]
        descriptor = evidence["teardown_evidence"]
        sidecar_path = PROJECT_ROOT / descriptor["path"]
        raw = json.dumps(
            sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        sidecar_path.write_bytes(raw)
        descriptor["sha256"] = hashlib.sha256(raw).hexdigest()
        self._rewrite_profile_evidence(result, evidence)

    def _rewrite_guard_journal(
        self,
        result: dict[str, Any],
        evidence: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        descriptor = evidence["guard_event_journal"]
        journal_path = PROJECT_ROOT / descriptor["path"]
        raw = b"".join(
            json.dumps(
                event, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
            + b"\n"
            for event in events
        )
        journal_path.write_bytes(raw)
        descriptor["sha256"] = hashlib.sha256(raw).hexdigest()
        descriptor["event_count"] = len(events)
        self._rewrite_profile_evidence(result, evidence)

    @staticmethod
    def _validate_retained_case(
        plan: controller.PreflightRowPlan,
        row_run_id: str,
        intended_identity: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return retained.validate_retained_supervised_evidence(
            result,
            plan=plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            intended_identity=intended_identity,
            source_sha=SOURCE_SHA,
            row_run_id=row_run_id,
            preflight_run_id=RUN_ID,
        )

    def _run_prelaunch_characterization_failure(
        self,
        *,
        run_id: str,
        common_directory: Path,
        canary_side_effect: Any,
    ) -> tuple[profile_runner.CharacterizationError, dict[str, Any]]:
        with tempfile.TemporaryDirectory(
            prefix="prelaunch-failure-", dir=PROJECT_ROOT / "tmp"
        ) as evidence_root_text:
            run_directory = Path(evidence_root_text) / "run"
            run_directory.mkdir()
            guard_journal = run_directory / "guard-events.jsonl"
            guard_journal.write_bytes(b"synthetic guard evidence\n")
            sandbox_root = PROJECT_ROOT / profile_runner.SANDBOX_RELATIVE
            host_command = ["python", "guarded-host-worker"]
            runner_command = ["python", "profile-runner"]
            expected_pythonpath = os.pathsep.join(
                (
                    str(PROJECT_ROOT / "scripts" / "live_gate_preflight_guard"),
                    str(PROJECT_ROOT),
                )
            )

            def validate_canary(
                report: Any,
                *,
                process_role: str,
                command: list[str],
                cwd: Path,
                environment_sha256: str,
                expected_pid: int | None = None,
            ) -> dict[str, Any]:
                return {
                    "process_role": process_role,
                    "pid": (
                        expected_pid
                        if expected_pid is not None
                        else report.get("pid", 24680)
                    ),
                    "command": list(command),
                    "environment_sha256": environment_sha256,
                    "working_directory": str(cwd),
                    "interpreter": profile_runner._interpreter_identity(),
                }

            args = SimpleNamespace(
                fixture_id="interior_tavern",
                party_size=1,
                lifecycle="startup",
                source_sha=SOURCE_SHA,
                run_id=run_id,
                resume_checkpoint_sha256=None,
                planned_row_id="E01",
                arm="A",
                preflight_run_id=RUN_ID,
            )
            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(
                        profile_runner,
                        "_require_safe_project_root",
                        return_value=PROJECT_ROOT,
                    )
                )
                stack.enter_context(
                    mock.patch.object(profile_runner, "_require_parent_startup_guard")
                )
                stack.enter_context(
                    mock.patch.object(
                        profile_runner, "_configure_sandbox_import_paths"
                    )
                )
                stack.enter_context(
                    mock.patch.object(profile_runner, "_install_sandbox_config_guard")
                )
                stack.enter_context(
                    mock.patch.object(profile_runner, "_verify_source_identity")
                )
                stack.enter_context(
                    mock.patch.object(
                        profile_runner,
                        "_validate_prepared_sandbox",
                        return_value=(
                            sandbox_root,
                            "E01",
                            "A",
                            "interior_tavern:p1",
                            {
                                "step_id": "E01-01",
                                "utterance": "Describe the room.",
                                "character": "PC-One",
                            },
                            safety.SANDBOX_PROVIDER_KEY_PLACEHOLDER,
                        ),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        profile_runner,
                        "_ensure_run_directory",
                        return_value=run_directory,
                    )
                )
                stack.enter_context(
                    mock.patch(
                        "scripts.live_gate_preflight_safety.configure_guard_event_sink"
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        profile_runner, "_host_command", return_value=host_command
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        safety,
                        "current_invocation_command",
                        return_value=runner_command,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        safety,
                        "build_guarded_sandbox_environment",
                        return_value={"PYTHONPATH": expected_pythonpath},
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        safety,
                        "_startup_canary_environment_digest",
                        return_value="b" * 64,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        safety, "_startup_environment_snapshot", return_value={}
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        safety, "_startup_environment_digest", return_value="a" * 64
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        profile_runner,
                        "_validate_startup_canary_record",
                        side_effect=validate_canary,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        profile_runner,
                        "_git_common_directory",
                        return_value=common_directory,
                    )
                )
                stack.enter_context(
                    mock.patch.object(profile_runner, "_remove_import_guard")
                )
                stack.enter_context(
                    mock.patch.object(
                        profile_runner,
                        "_read_guard_events_for_run",
                        return_value=([], guard_journal.read_bytes(), False),
                    )
                )
                port_status = stack.enter_context(
                    mock.patch.object(profile_runner, "_required_port_status")
                )
                port_observations = stack.enter_context(
                    mock.patch.object(
                        profile_runner, "_required_port_observations"
                    )
                )
                host_process_launch = stack.enter_context(
                    mock.patch.object(profile_runner.subprocess, "Popen")
                )
                stack.enter_context(
                    mock.patch.object(
                        safety,
                        "run_startup_process_canary",
                        side_effect=canary_side_effect,
                    )
                )
                stack.enter_context(
                    mock.patch.dict(
                        os.environ,
                        {
                            safety.CANARY_REPORT_ENV: json.dumps(
                                {"process_role": "parent"}
                            )
                        },
                    )
                )
                with self.assertRaises(profile_runner.CharacterizationError) as caught:
                    profile_runner._characterize(args)

            port_status.assert_not_called()
            port_observations.assert_not_called()
            host_process_launch.assert_not_called()
            failure_path = run_directory / "failure-evidence.json"
            self.assertTrue(failure_path.is_file())
            return caught.exception, json.loads(failure_path.read_text(encoding="utf-8"))

    def _intended_identities(self) -> dict[str, dict[str, Any]]:
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        identities: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_id = str(row["row_id"])
            plan = _resolve_row_plan(
                row_id,
                prereg_root=None,
                expected_row=row,
                profiles=profiles,
            )
            row_run_id = "pf-%s-%s" % (RUN_ID, row_id)
            identities[row_id] = self._caller_declared_identity(
                plan,
                fixture_id=plan.fixture_id,
                lifecycle="startup",
                row_run_id=row_run_id,
            )
        return identities

    @staticmethod
    def _measured_lifecycle(
        call_site: dict[str, Any], *, source_sha: str = SOURCE_SHA
    ) -> dict[str, Any]:
        if call_site.get("source_file") == "scripts/example_router_call.py":
            call_site = _synthetic_call_site(count=call_site["count"])
        return {
            "status": "measured-under-stub",
            "source_sha": source_sha,
            "call_count": call_site["count"],
            "call_sites": [dict(call_site)],
        }

    @staticmethod
    def _checkpoint(
        *, row_id: str, fixture_id: str, party_size: int, arm: str, seed: int, sha: str
    ) -> dict[str, Any]:
        return {
            "checkpoint_root": "tmp/resume-checkpoints/%s/%s" % (row_id, fixture_id),
            "state_sha256": sha * 64,
            "row_id": row_id,
            "fixture_id": fixture_id,
            "party_size": party_size,
            "arm": arm,
            "fixed_seed": seed,
        }

    def _fake_interfaces(
        self,
        sandbox_root: Path,
        *,
        prepared_rows: list[str],
        validated_rows: list[str],
        worker_rows: list[str],
        driver_sessions: list[row_runner.SocketScriptDriver],
        capture_sessions: list[_FakeCaptureSession],
        worker_launches: list[dict[str, Any]],
        identities: dict[str, dict[str, Any]],
        resolved_plans: list[controller.PreflightRowPlan],
        cleaned_rows: list[str] | None = None,
        observed_call_count: int = 1,
        observed_call_sites: list[dict[str, Any]] | None = None,
        use_guarded_adapter: bool = False,
        prepared_lifecycles: list[tuple[str, str, str]] | None = None,
        worker_lifecycles: list[tuple[str, str, str]] | None = None,
    ) -> tuple[PreflightInterfaces, Any]:
        from scripts import seed_combat_capture
        from scripts import combat_latency_fixtures

        party_names = {
            party_size: seed_combat_capture._party_names(party_size)
            for party_size in (1, 4)
        }
        module_payloads, expected_payloads = sandbox._load_profile_seed_inputs(
            PROJECT_ROOT
        )
        prepared_context: list[
            tuple[controller.PreflightRowPlan, controller.PreflightLifecycleInvocation]
        ] = []

        def prepare(
            plan: controller.PreflightRowPlan,
            invocation: controller.PreflightLifecycleInvocation,
            source_sha: str,
            preflight_run_id: str,
        ) -> dict[str, Any]:
            self.assertEqual(source_sha, SOURCE_SHA)
            self.assertEqual(preflight_run_id, RUN_ID)
            expected_identity = planned_worker_identity(
                plan,
                fixture_id=invocation.fixture_id,
                lifecycle=invocation.lifecycle,
                source_sha=source_sha,
                row_run_id=invocation.row_run_id,
                resume_checkpoint_sha256=(
                    invocation.resume_checkpoint.get("state_sha256")
                    if invocation.resume_checkpoint
                    else None
                ),
                preflight_run_id=preflight_run_id,
            )
            self.assertEqual(invocation.intended_identity, expected_identity)
            if invocation.fixture_id == plan.fixture_id and invocation.lifecycle == "startup":
                self.assertEqual(
                    invocation.intended_identity["command"],
                    identities[plan.row_id]["command"],
                )
            if prepared_lifecycles is not None:
                prepared_lifecycles.append(
                    (plan.row_id, invocation.fixture_id, invocation.lifecycle)
                )
            self.assertFalse(plan.row_id.startswith("R"))
            prepared_context.append((plan, invocation))
            seed_plan, _profile = sandbox._load_profile_seed_plan(
                invocation.fixture_id, plan.party_size, plan.row_id
            )
            area_id, _area, _location = sandbox._runtime_location(
                module_payloads, seed_plan["runtime_location_id"]
            )
            self.assertIn("areas/%s.json" % area_id, module_payloads)
            self.assertIn("map_%s.json" % area_id, module_payloads)
            source_map = module_payloads["location_id_map.json"]["runtime_location_ids"]
            self.assertEqual(
                source_map.get(seed_plan["source_location_id"]),
                seed_plan["runtime_location_id"],
            )
            expected_party = seed_combat_capture._party_names(plan.party_size)
            self.assertEqual(len(expected_party), plan.party_size)
            for member in expected_party:
                self.assertTrue(
                    combat_latency_fixtures.build_capture_character_payload(
                        member,
                        seed_combat_capture._party_initiative(member, plan.party_size),
                    )
                )
            if invocation.fixture_id == "combat_stage_tavern_zones":
                monster_path = sandbox._source_file(
                    PROJECT_ROOT,
                    "modules/Capture_Arena/monsters/goblin.json",
                    required=True,
                )
                self.assertIsNotNone(monster_path)
                monster = json.loads(monster_path.read_text(encoding="utf-8"))
                self.assertEqual(monster.get("name"), "Goblin")
            prepared_rows.append(plan.row_id)
            return {
                "status": "prepared",
                "sandbox_root": "tmp/combat_capture",
                "fixture_id": invocation.fixture_id,
                "party_size": plan.party_size,
                "planned_row_id": plan.row_id,
                "arm": plan.arm,
                "effective_seed": plan.fixed_seed,
            }

        def validate(
            runtime_root: Path,
            *,
            arm: str,
            fixture_id: str,
            party_size: int,
            resume: bool = False,
            resume_checkpoint_sha256: str | None = None,
            project_root: Path,
        ) -> launcher.ValidatedSandbox:
            del project_root
            plan, invocation = prepared_context[len(validated_rows)]
            self.assertEqual(resume, invocation.lifecycle == "resume")
            if resume:
                self.assertIsNotNone(resume_checkpoint_sha256)
            self.assertEqual(runtime_root, PROJECT_ROOT / "tmp" / "combat_capture")
            self.assertEqual(arm, plan.arm)
            self.assertEqual(fixture_id, invocation.fixture_id)
            self.assertEqual(party_size, plan.party_size)
            validated_rows.append(plan.row_id)
            metadata = {
                "fixture_id": invocation.fixture_id,
                "arm": plan.arm,
                "party": {
                    "size": plan.party_size,
                    "members": list(party_names[plan.party_size]),
                },
                "counterbalance": {
                    "row_id": plan.row_id,
                    "fixed_seed": plan.fixed_seed,
                    "row_type": "planned",
                },
                "mapping": {},
            }
            seed_plan, _profile = sandbox._load_profile_seed_plan(
                invocation.fixture_id, plan.party_size, plan.row_id
            )
            area_id, _area, _location = sandbox._runtime_location(
                module_payloads, seed_plan["runtime_location_id"]
            )
            source_map = module_payloads["location_id_map.json"]["runtime_location_ids"]
            runtime_to_source = {
                runtime: source for source, runtime in source_map.items()
            }
            metadata["mapping"] = {
                "module": "mapping_pilot",
                "source_location_id": seed_plan["source_location_id"],
                "runtime_location_id": seed_plan["runtime_location_id"],
                "area_id": area_id,
                "id_map_file": "modules/mapping_pilot/location_id_map.json",
            }
            fixture_payloads = {
                selected: payload["source_truth"]
                for selected, payload in expected_payloads.items()
            }
            return launcher.ValidatedSandbox(
                root=sandbox_root,
                metadata=metadata,
                fixture_payloads=fixture_payloads,
                runtime_to_source=runtime_to_source,
            )

        def driver_factory(**kwargs: Any) -> row_runner.SocketScriptDriver:
            driver = row_runner.SocketScriptDriver(
                **kwargs,
                session_factory=lambda args: _FakeCaptureSession(args, capture_sessions),
            )
            driver_sessions.append(driver)
            return driver

        def supervise_row(
            plan: controller.PreflightRowPlan,
            seeded: dict[str, Any],
            invocation: controller.PreflightLifecycleInvocation,
            source_sha: str,
            preflight_run_id: str,
        ) -> dict[str, Any]:
            self.assertEqual(seeded["planned_row_id"], plan.row_id)
            self.assertEqual(seeded["fixture_id"], invocation.fixture_id)
            self.assertEqual(source_sha, SOURCE_SHA)
            self.assertEqual(preflight_run_id, RUN_ID)
            worker_rows.append(plan.row_id)
            if use_guarded_adapter:
                result = profile_runner.supervise_preflight_row(
                    fixture_id=invocation.fixture_id,
                    party_size=plan.party_size,
                    planned_row_id=plan.row_id,
                    arm=plan.arm,
                    source_sha=source_sha,
                    row_run_id=invocation.row_run_id,
                    lifecycle=invocation.lifecycle,
                    resume_checkpoint_sha256=(
                        invocation.resume_checkpoint.get("state_sha256")
                        if invocation.resume_checkpoint
                        else None
                    ),
                    preflight_run_id=preflight_run_id,
                )
                if worker_lifecycles is not None:
                    worker_lifecycles.append(
                        (plan.row_id, invocation.fixture_id, invocation.lifecycle)
                    )
                return result
            worker = server.launch_worker(
                arm=plan.arm,
                fixture_id=invocation.fixture_id,
                party_size=plan.party_size,
                row_run_id=invocation.row_run_id,
                lifecycle_id=invocation.row_run_id
                + ("_s" if invocation.lifecycle == "startup" else "_r"),
                runtime_root="tmp/combat_capture",
                launcher=_FakeServerLauncher(plan.row_id, worker_launches),
            )
            self.assertEqual(worker.row_id, plan.row_id)
            if worker_lifecycles is not None:
                worker_lifecycles.append(
                    (plan.row_id, invocation.fixture_id, invocation.lifecycle)
                )
            exchange = profile_runner._drive_profile_exchange(
                party_size=plan.party_size,
                runtime_root=PROJECT_ROOT / "tmp" / "combat_capture",
                transcript_path=(
                    PROJECT_ROOT
                    / "tmp"
                    / "preflight-integration"
                    / invocation.row_run_id
                    / "driver.txt"
                ),
                first_turn=plan.first_turn,
                driver_factory=driver_factory,
            )
            args = SimpleNamespace(
                fixture_id=invocation.fixture_id,
                party_size=plan.party_size,
                lifecycle=invocation.lifecycle,
                source_sha=source_sha,
                run_id=invocation.row_run_id,
                planned_row_id=plan.row_id,
                arm=plan.arm,
                resume_checkpoint_sha256=(
                    invocation.resume_checkpoint.get("state_sha256")
                    if invocation.resume_checkpoint
                    else None
                ),
                preflight_run_id=preflight_run_id,
            )
            evidence, evidence_path, evidence_sha256 = self._fake_characterization(
                args,
                driver_exchange=exchange,
                observed_call_count=observed_call_count,
                observed_call_sites=observed_call_sites,
            )
            return {
                "evidence": evidence,
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_sha256,
            }

        def cleanup_sandbox(
            plan: controller.PreflightRowPlan, _seeded: dict[str, Any]
        ) -> bool:
            if cleaned_rows is not None:
                cleaned_rows.append(plan.row_id)
            return True

        def counters() -> dict[str, int]:
            return {
                "upstream_provider_requests": 0,
                "provider_budget_used": 0,
                "live_attempts_used": 0,
                "reserve_activations": 0,
            }

        interfaces = PreflightInterfaces(
            prepare_sandbox=prepare,
            supervise_row=supervise_row,
            cleanup_sandbox=cleanup_sandbox,
            safety_counters=counters,
        )
        return interfaces, validate

    def _run_with_profiles(
        self,
        profile_map: dict[tuple[str, int], Any],
        coverage: dict[str, Any],
        *,
        observed_call_count: int = 1,
        observed_call_sites: list[dict[str, Any]] | None = None,
        resume_checkpoints: dict[str, dict[str, dict[str, Any]]] | None = None,
        intended_lifecycle_identities: dict[
            str, dict[str, dict[str, dict[str, Any]]]
        ]
        | None = None,
        use_guarded_adapter: bool = False,
    ) -> tuple[dict[str, Any], dict[str, list[Any]]]:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        resolved_plans = [
            _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profile_map,
            )
            for row in rows
        ]
        observed: dict[str, list[Any]] = {
            "prepared": [],
            "validated": [],
            "workers": [],
            "cleaned": [],
            "drivers": [],
            "sessions": [],
            "launches": [],
            "prepared_lifecycles": [],
            "worker_lifecycles": [],
        }
        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-profiles-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            interfaces, validate_sandbox = self._fake_interfaces(
                Path(temp_root),
                prepared_rows=observed["prepared"],
                validated_rows=observed["validated"],
                worker_rows=observed["workers"],
                driver_sessions=observed["drivers"],
                capture_sessions=observed["sessions"],
                worker_launches=observed["launches"],
                identities=identities,
                resolved_plans=resolved_plans,
                cleaned_rows=observed["cleaned"],
                observed_call_count=observed_call_count,
                observed_call_sites=observed_call_sites,
                use_guarded_adapter=use_guarded_adapter,
                prepared_lifecycles=observed["prepared_lifecycles"],
                worker_lifecycles=observed["worker_lifecycles"],
            )
            with (
                mock.patch.object(server, "_safe_runtime_root", return_value=Path(temp_root)),
                mock.patch.object(launcher, "validate_sandbox", side_effect=validate_sandbox),
                mock.patch.object(
                    row_runner._SocketPayloadDecodeScope,
                    "acquire",
                    side_effect=_FakeDecodeScope,
                ),
                mock.patch(
                    "scripts.live_gate_preflight_profile_runner._require_parent_startup_guard"
                ),
                mock.patch.object(
                    controller, "_load_profiles", return_value=(profile_map, coverage)
                ),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    intended_lifecycle_identities=intended_lifecycle_identities,
                    interfaces=interfaces,
                    resume_checkpoints=resume_checkpoints,
                )
        return report, observed

    def test_retained_reconciliation_accepts_both_attributed_shutdown_forms(self) -> None:
        for server_returned in (True, False):
            with self.subTest(server_returned=server_returned):
                plan, row_run_id, identity, result = self._retained_case(
                    server_returned=server_returned
                )
                summary = self._validate_retained_case(
                    plan, row_run_id, identity, result
                )
                self.assertEqual(summary["outcome"], "completed")
                self.assertTrue(summary["process_census_complete"])
                self.assertEqual(summary["worker_teardown"]["call_count"], 1)
                self.assertTrue(summary["worker_teardown"]["server_stopped"])
                self.assertTrue(summary["worker_teardown"]["port_8360_free"])
                self.assertTrue(summary["worker_teardown"]["port_8370_free"])
                self.assertTrue(
                    summary["worker_teardown"]["shared_live_window_lock_released"]
                )
                teardown_path = (
                    PROJECT_ROOT / result["evidence"]["teardown_evidence"]["path"]
                )
                teardown = json.loads(teardown_path.read_text(encoding="utf-8"))
                self.assertEqual(teardown["socket_census"]["listener_pids"], [])
                self.assertTrue(
                    all(
                        teardown["port_observations"][port]["result"] == "free"
                        and teardown["port_observations"][port][
                            "observation_complete"
                        ]
                        for port in ("8360", "8370")
                    )
                )

    def test_prelaunch_guard_and_lock_contention_preserve_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="prelaunch-lock-contention-", dir=PROJECT_ROOT / "tmp"
        ) as common_root_text:
            common_root = Path(common_root_text)
            coordination = common_root / "neq-coordination"
            lock_directory = coordination / "live-window.lock"
            lock_directory.mkdir(parents=True, mode=0o700)
            holder_path = lock_directory / "holder.json"
            holder_bytes = b'{"booking_id":"foreign-holder"}\n'
            holder_path.write_bytes(holder_bytes)
            bookings_path = coordination / "bookings.log"
            booking_bytes = b'{"booking_id":"existing-booking"}\n'
            bookings_path.write_bytes(booking_bytes)

            guard_error, guard_evidence = self._run_prelaunch_characterization_failure(
                run_id="guard-failure-" + uuid.uuid4().hex[:8],
                common_directory=common_root,
                canary_side_effect=RuntimeError("synthetic guard rejection"),
            )
            self.assertEqual(guard_error.code, "host_prelaunch_canary_failed")
            self.assertEqual(guard_evidence["phase"], "host_prelaunch_canary")
            self.assertFalse(guard_evidence["guard_event_journal"]["complete"])
            self.assertIsNone(guard_evidence["guard_event_journal"]["sha256"])
            self.assertTrue(
                guard_evidence["guard_event_journal"]["path"].startswith("tmp/")
            )
            self.assertFalse(guard_evidence["host_launch_attempted"])

            contention_error, contention_evidence = (
                self._run_prelaunch_characterization_failure(
                    run_id="lock-contention-" + uuid.uuid4().hex[:8],
                    common_directory=common_root,
                    canary_side_effect=lambda **_kwargs: {"pid": 24680},
                )
            )
            self.assertEqual(
                contention_error.code, "shared_live_window_lock_unavailable"
            )
            self.assertEqual(
                contention_evidence["phase"], "shared_live_window_lock_acquire"
            )
            self.assertFalse(contention_evidence["host_launch_attempted"])
            self.assertFalse(contention_evidence["shared_live_window_lock"]["acquired"])
            self.assertEqual(holder_path.read_bytes(), holder_bytes)
            self.assertEqual(bookings_path.read_bytes(), booking_bytes)

    def test_retained_reconciliation_rejects_missing_malformed_and_tampered_files(
        self,
    ) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        guard_path = PROJECT_ROOT / result["evidence"]["guard_event_journal"]["path"]
        guard_path.write_bytes(b"not-json\n")
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "hash differs"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        guard_path = PROJECT_ROOT / result["evidence"]["guard_event_journal"]["path"]
        guard_path.unlink()
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "journal path is missing"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        guard_path = PROJECT_ROOT / evidence["guard_event_journal"]["path"]
        malformed = b"not-json\n"
        guard_path.write_bytes(malformed)
        evidence["guard_event_journal"]["sha256"] = hashlib.sha256(
            malformed
        ).hexdigest()
        evidence["guard_event_journal"]["event_count"] = 1
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "journal is invalid"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        worker_path = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / RUN_ID
            / "preflight"
            / "rows"
            / row_run_id
            / "worker-result.json"
        )
        worker_path.unlink()
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "worker result file is unavailable"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        socket_sample = result["evidence"]["process_census"]["socket_pid_samples"][2]
        census_path = PROJECT_ROOT / socket_sample["evidence_path"]
        census_path.unlink()
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError,
            "socket sample evidence path is missing",
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        socket_sample = evidence["process_census"]["socket_pid_samples"][2]
        census_path = PROJECT_ROOT / socket_sample["evidence_path"]
        malformed_census = b"{not-json"
        census_path.write_bytes(malformed_census)
        socket_sample["evidence_sha256"] = hashlib.sha256(malformed_census).hexdigest()
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "socket sample is invalid"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        shutdown_path = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / RUN_ID
            / "preflight"
            / "rows"
            / row_run_id
            / "shutdown-request.json"
        )
        shutdown_path.unlink()
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "unavailable"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        shutdown_path = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / RUN_ID
            / "preflight"
            / "rows"
            / row_run_id
            / "shutdown-request.json"
        )
        shutdown_path.write_bytes(b"{not-json")
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "shutdown request is malformed"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        worker_path = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / RUN_ID
            / "preflight"
            / "rows"
            / row_run_id
            / "worker-result.json"
        )
        worker_result = json.loads(worker_path.read_text(encoding="utf-8"))
        worker_result["server_returned"] = False
        worker_path.write_text(
            json.dumps(worker_result, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "shutdown summary differs"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        evidence["teardown"].pop("port_8370_free")
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "teardown"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        evidence["teardown"]["server_stopped"] = False
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "teardown"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        evidence["lifecycle"] = "resume"
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(
            controller.PreflightControllerError,
            "retained_supervised_evidence_reconciliation_failed",
        ):
            controller._validate_supervised_result(
                result,
                plan=plan,
                fixture_id=plan.fixture_id,
                lifecycle="startup",
                intended_identity=identity,
                source_sha=SOURCE_SHA,
                row_run_id=row_run_id,
                preflight_run_id=RUN_ID,
            )

    def test_retained_reconciliation_rejects_unguarded_and_foreign_egress_events(
        self,
    ) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        journal_path = PROJECT_ROOT / evidence["guard_event_journal"]["path"]
        events = [json.loads(line) for line in journal_path.read_text().splitlines()]
        events = [event for event in events if event["pid"] != 103]
        self._rewrite_guard_journal(result, evidence, events)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "guard-event process identity differs"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        journal_path = PROJECT_ROOT / evidence["guard_event_journal"]["path"]
        events = [json.loads(line) for line in journal_path.read_text().splitlines()]
        external_attempt = next(
            event
            for event in events
            if event["event_type"] == "network_attempt"
            and event["target_host"] == "192.0.2.1"
        )
        external_attempt["decision"] = "allowed"
        controller_canary = next(
            item
            for item in evidence["process_canaries"]
            if item["canary_stage"] == "controller-startup"
        )
        allowed_attempt = dict(external_attempt)
        allowed_attempt.update(
            {
                "pid": controller_canary["pid"],
                "process_group_id": controller_canary["pid"],
                "process_role": "parent",
                "sequence": 4,
                "observed_at_ns": 1_000_004,
                "decision": "allowed",
                "target_host": "203.0.113.1",
                "target_port": 443,
            }
        )
        events.append(allowed_attempt)
        controller_canary["guard_events"].append(dict(allowed_attempt))
        self._rewrite_guard_journal(result, evidence, events)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "egress"):
            self._validate_retained_case(plan, row_run_id, identity, result)

    def test_retained_reconciliation_rejects_active_listener_and_incomplete_teardown(
        self,
    ) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sample = evidence["process_census"]["socket_pid_samples"][2]
        sidecar_path = PROJECT_ROOT / sample["evidence_path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        listener_row = sidecar["run_owned_rows"][0]
        listener_row["local"] = {"host": "127.0.0.1", "port": 8360}
        listener_row["foreign"] = {"host": "*", "port": None}
        listener_row["state"] = "LISTEN"
        sidecar_path.write_text(
            json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        sample["listener_pids"] = [listener_row["pid"]]
        sample["evidence_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "active listener"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sample = evidence["process_census"]["socket_pid_samples"][1]
        sidecar_path = PROJECT_ROOT / sample["evidence_path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        listener_row = sidecar["run_owned_rows"][0]
        listener_row["local"] = {"host": "127.0.0.1", "port": 8370}
        listener_row["foreign"] = {"host": "*", "port": None}
        listener_row["state"] = "LISTEN"
        sidecar_path.write_text(
            json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="ascii",
        )
        sample["listener_pids"] = []
        sample["evidence_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "active listener"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        evidence["teardown"]["port_8370_free"] = False
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "teardown"):
            self._validate_retained_case(plan, row_run_id, identity, result)

    def test_retained_teardown_sidecar_fails_closed_on_missing_tampered_and_conflicting_proof(
        self,
    ) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        sidecar_path = PROJECT_ROOT / result["evidence"]["teardown_evidence"]["path"]
        sidecar_path.unlink()
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "unavailable"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        sidecar_path = PROJECT_ROOT / result["evidence"]["teardown_evidence"]["path"]
        sidecar_path.write_bytes(b"tampered teardown bytes")
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "hash differs"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sidecar_path = PROJECT_ROOT / evidence["teardown_evidence"]["path"]
        malformed_sidecar = b"{not-json"
        sidecar_path.write_bytes(malformed_sidecar)
        evidence["teardown_evidence"]["sha256"] = hashlib.sha256(
            malformed_sidecar
        ).hexdigest()
        self._rewrite_profile_evidence(result, evidence)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "teardown evidence is malformed"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sidecar_path = PROJECT_ROOT / evidence["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["port_observations"]["8360"].update(
            {
                "bind_succeeded": False,
                "error_errno": errno.EADDRINUSE,
                "error_type": "OSError",
                "result": "occupied",
            }
        )
        self._rewrite_teardown_sidecar(result, sidecar)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "port 8360 is occupied or unobservable"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sidecar_path = PROJECT_ROOT / evidence["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["port_observations"]["8370"].update(
            {
                "bind_succeeded": False,
                "socket_closed": False,
                "result": "unobservable",
                "observation_complete": False,
            }
        )
        self._rewrite_teardown_sidecar(result, sidecar)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "port 8370 is occupied or unobservable"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sidecar_path = PROJECT_ROOT / evidence["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["shared_lock"]["lock_directory_removed"] = False
        sidecar["shared_lock"]["release_succeeded"] = False
        self._rewrite_teardown_sidecar(result, sidecar)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "shared lock release"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sidecar_path = PROJECT_ROOT / evidence["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["runner_source_sha256"] = "f" * 64
        self._rewrite_teardown_sidecar(result, sidecar)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "identity differs"):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sidecar_path = PROJECT_ROOT / evidence["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["booking_id"] = sidecar["booking_id"].replace("-N-", "-S-")
        self._rewrite_teardown_sidecar(result, sidecar)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "shared lock release record identity differs"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        evidence = result["evidence"]
        sidecar_path = PROJECT_ROOT / evidence["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        durable = sidecar["shared_lock"]["durable_record"]
        durable_path = PROJECT_ROOT / durable["path"]
        durable_bytes = bytearray(durable_path.read_bytes())
        durable_bytes[durable["byte_offset"] + 2] ^= 1
        durable_path.write_bytes(durable_bytes)
        with self.assertRaisesRegex(retained.RetainedEvidenceError, "line hash differs"):
            self._validate_retained_case(plan, row_run_id, identity, result)

    def test_all_26_planned_rows_cross_existing_sp3_interfaces(self) -> None:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        resolved_plans = [
            _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profiles,
            )
            for row in rows
        ]
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        cleaned_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-integration-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox_root = Path(temp_root)
            interfaces, validate_sandbox = self._fake_interfaces(
                sandbox_root,
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=resolved_plans,
                cleaned_rows=cleaned_rows,
            )
            with (
                mock.patch.object(server, "_safe_runtime_root", return_value=sandbox_root),
                mock.patch.object(launcher, "validate_sandbox", side_effect=validate_sandbox),
                mock.patch.object(
                    row_runner._SocketPayloadDecodeScope,
                    "acquire",
                    side_effect=_FakeDecodeScope,
                ),
                mock.patch(
                    "scripts.live_gate_preflight_profile_runner._require_parent_startup_guard"
                ),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["transport_status"], "completed")
        self.assertEqual(report["lifecycle_coverage_status"], "unverified")
        self.assertEqual(report["fully_covered_row_ids"], [])
        self.assertTrue(report["preflight_only"])
        self.assertFalse(report["booking_eligible"])
        self.assertFalse(report["live_gate_pass"])
        self.assertFalse(report["pilot_evidence_written"])
        self.assertEqual(report["planned_row_count"], 26)
        self.assertEqual(report["attempted_row_ids"], report["planned_row_ids"])
        self.assertEqual(len(report["row_results"]), 26)
        self.assertEqual(report["replacement_only_row_ids"], ["R01", "R02", "R03", "R04"])
        self.assertEqual(report["replacement_only_rows_activated"], [])
        self.assertEqual(report["unverified_profile_row_ids"], report["planned_row_ids"])
        self.assertEqual(prepared_rows, report["planned_row_ids"])
        self.assertEqual(validated_rows, report["planned_row_ids"])
        self.assertEqual(worker_rows, report["planned_row_ids"])
        self.assertEqual(cleaned_rows, report["planned_row_ids"])
        self.assertEqual(len(driver_sessions), 26)
        self.assertTrue(
            all(isinstance(driver, row_runner.SocketScriptDriver) for driver in driver_sessions)
        )
        self.assertTrue(all(driver._closed for driver in driver_sessions))
        self.assertEqual(len(capture_sessions), 26)
        self.assertTrue(all(session.disconnected for session in capture_sessions))
        self.assertTrue(all(session.transcript_closed for session in capture_sessions))
        self.assertTrue(
            all(
                session.sent == [
                    (plan.first_turn["step_id"], plan.first_turn["utterance"], plan.first_turn["character"])
                ]
                and session.game_outputs[0]["payload"]["content"]
                == "provider-free stub response"
                for session, plan in zip(capture_sessions, resolved_plans)
            )
        )
        self.assertEqual([launch["row_id"] for launch in worker_launches], report["planned_row_ids"])

        disconnected_rows = {
            "E04", "E05", "E06", "E13", "E14", "E15", "E16", "E17", "E18"
        }
        observed_disconnected = {
            row["row_id"]
            for row in report["row_results"]
            if row["fixture_ids"] == ["landscape_village", "transition_tower_approach"]
        }
        self.assertEqual(observed_disconnected, disconnected_rows)
        self.assertEqual(
            {row["party_size"] for row in report["row_results"]}, {1, 4}
        )
        self.assertTrue(
            all(row["first_exchange"]["status"] == "completed" for row in report["row_results"])
        )
        self.assertTrue(
            all(
                row["worker_teardown"]["server_stopped"]
                and row["worker_teardown"]["port_8360_free"]
                and row["worker_teardown"]["port_8370_free"]
                and row["worker_teardown"]["shared_live_window_lock_released"]
                for row in report["row_results"]
            )
        )
        self.assertTrue(
            all(row["lifecycle_profile_status"] == "unverified" for row in report["row_results"])
        )
        self.assertTrue(
            all(row["startup_profile_check"]["status"] == "unverified" for row in report["row_results"])
        )
        self.assertTrue(
            all(
                row["lifecycle_profile_checks"][row["fixture_id"]]["resume"][
                    "checkpoint_status"
                ]
                == "MISSING"
                for row in report["row_results"]
            )
        )
        self.assertTrue(
            all(
                row["status"] == "transport_completed_unverified"
                for row in report["row_results"]
            )
        )
        self.assertTrue(
            all(
                all(
                    profile["startup_status"] == "MISSING"
                    and profile["resume_status"] == "MISSING"
                    for profile in row["lifecycle_profiles"]
                )
                for row in report["row_results"]
            )
        )
        self.assertEqual(
            report["provider_free"],
            {
                "upstream_provider_requests_delta": 0,
                "provider_budget_used_delta": 0,
                "live_attempts_used_delta": 0,
                "reserve_activations_delta": 0,
                "router_stub_calls": 26,
            },
        )

    def test_invocation_mismatch_blocks_before_seeding_or_worker_launch(self) -> None:
        identities = self._intended_identities()
        identities["E01"] = dict(identities["E01"])
        identities["E01"]["command"] = [*identities["E01"]["command"], "--wrong-row"]
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-identity-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            sandbox_root = Path(temp_root)
            interfaces, validate_sandbox = self._fake_interfaces(
                sandbox_root,
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=[],
            )
            with (
                mock.patch.object(server, "_safe_runtime_root", return_value=sandbox_root),
                mock.patch.object(launcher, "validate_sandbox", side_effect=validate_sandbox) as validate,
                mock.patch.object(
                    row_runner._SocketPayloadDecodeScope,
                    "acquire",
                    side_effect=_FakeDecodeScope,
                ),
                mock.patch(
                    "scripts.live_gate_preflight_profile_runner._require_parent_startup_guard"
                ),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(report["row_results"][0]["failure_code"], "invocation_identity_mismatch")
        self.assertEqual(report["row_results"][0]["invocation_identity"]["status"], "blocked")
        self.assertEqual(prepared_rows, [])
        self.assertEqual(validated_rows, [])
        self.assertEqual(worker_rows, [])
        self.assertEqual(driver_sessions, [])
        self.assertEqual(worker_launches, [])
        validate.assert_not_called()
        self.assertFalse(report["booking_eligible"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_missing_lifecycle_profile_blocks_before_sandbox_seed(self) -> None:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        profile_map.pop(("interior_tavern", 1))
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-profile-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            interfaces, _validate = self._fake_interfaces(
                Path(temp_root),
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=[],
            )
            with mock.patch.object(
                controller,
                "_load_profiles",
                return_value=(profile_map, coverage),
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "fixture-party_lifecycle_profile_is_missing",
        )
        self.assertEqual(prepared_rows, [])
        self.assertEqual(validated_rows, [])
        self.assertEqual(worker_rows, [])
        self.assertEqual(worker_launches, [])
        self.assertEqual(driver_sessions, [])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_missing_fixture_payload_is_reported_and_never_covered(self) -> None:
        identities = self._intended_identities()
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        resolved_plans = [
            _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profiles,
            )
            for row in rows
        ]
        prepared_rows: list[str] = []
        validated_rows: list[str] = []
        worker_rows: list[str] = []
        driver_sessions: list[row_runner.SocketScriptDriver] = []
        capture_sessions: list[_FakeCaptureSession] = []
        worker_launches: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-fixture-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            interfaces, validate_sandbox = self._fake_interfaces(
                Path(temp_root),
                prepared_rows=prepared_rows,
                validated_rows=validated_rows,
                worker_rows=worker_rows,
                driver_sessions=driver_sessions,
                capture_sessions=capture_sessions,
                worker_launches=worker_launches,
                identities=identities,
                resolved_plans=resolved_plans,
            )

            def missing_fixture(*args: Any, **kwargs: Any) -> launcher.ValidatedSandbox:
                validated = validate_sandbox(*args, **kwargs)
                plan = next(
                    item for item in resolved_plans if item.row_id == validated_rows[-1]
                )
                payloads = dict(validated.fixture_payloads)
                payloads.pop(plan.fixture_ids[0], None)
                return launcher.ValidatedSandbox(
                    root=validated.root,
                    metadata=validated.metadata,
                    fixture_payloads=payloads,
                    runtime_to_source=validated.runtime_to_source,
                )

            with mock.patch.object(
                launcher, "validate_sandbox", side_effect=missing_fixture
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(report["row_results"][0]["failure_code"], "fixture_payload_missing")
        self.assertEqual(
            report["row_results"][0]["unresolved_reference"],
            "mapping_pilot/expected/interior_tavern.json",
        )
        self.assertEqual(prepared_rows, ["E01"])
        self.assertEqual(validated_rows, ["E01"])
        self.assertEqual(worker_rows, [])
        self.assertEqual(worker_launches, [])
        self.assertEqual(driver_sessions, [])
        self.assertFalse(report["booking_eligible"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_measured_startup_profile_matches_calls_but_resume_stays_unverified(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = _synthetic_call_site()
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = {
            "status": "measured-under-stub",
            "source_sha": SOURCE_SHA,
            "call_count": 1,
            "call_sites": [call_site],
        }
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(
            profile_map,
            coverage,
            observed_call_sites=[call_site],
        )

        first_result = report["row_results"][0]
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(first_result["startup_profile_check"]["status"], "matched")
        self.assertTrue(first_result["startup_profile_check"]["call_sites_matched"])
        self.assertEqual(first_result["lifecycle_profile_status"], "unverified")
        self.assertEqual(first_result["status"], "transport_completed_unverified")
        self.assertEqual(
            first_result["lifecycle_profile_checks"]["interior_tavern"]["resume"][
                "checkpoint_status"
            ],
            "MISSING",
        )
        self.assertEqual(observed["workers"], report["planned_row_ids"])
        self.assertEqual(observed["cleaned"], report["planned_row_ids"])

    def test_measured_startup_call_count_mismatch_blocks_and_cleans_sandbox(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        expected_site = _synthetic_call_site(count=2)
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = {
            "status": "measured-under-stub",
            "source_sha": SOURCE_SHA,
            "call_count": 2,
            "call_sites": [expected_site],
        }
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(profile_map, coverage)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "startup_profile_call_count_mismatch",
        )
        self.assertEqual(observed["cleaned"], ["E01"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_measured_startup_call_site_mismatch_blocks(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        expected_site = _synthetic_call_site(
            source_file="scripts/test_live_gate_preflight_profiles.py"
        )
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = {
            "status": "measured-under-stub",
            "source_sha": SOURCE_SHA,
            "call_count": 1,
            "call_sites": [expected_site],
        }
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(profile_map, coverage)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "startup_profile_call_sites_mismatch",
        )
        self.assertEqual(observed["cleaned"], ["E01"])

    def test_measured_resume_without_row_checkpoint_stays_missing_and_unverified(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["resume"] = self._measured_lifecycle(call_site)
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, _observed = self._run_with_profiles(profile_map, coverage)

        first_result = report["row_results"][0]
        resume_check = first_result["lifecycle_profile_checks"]["interior_tavern"]["resume"]
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(first_result["transport_status"], "completed")
        self.assertEqual(first_result["status"], "transport_completed_unverified")
        self.assertEqual(resume_check["profile_status"], "MISSING")
        self.assertEqual(resume_check["checkpoint_status"], "MISSING")
        self.assertEqual(resume_check["reason"], "row_bound_resume_checkpoint_missing")
        self.assertFalse(
            any(
                item["lifecycle"] == "resume"
                for item in first_result["lifecycle_results"]
            )
        )

    def test_supplied_row_checkpoint_runs_guarded_resume_and_matches_profile(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = self._measured_lifecycle(call_site)
        profile["resume"] = self._measured_lifecycle(call_site)
        profile_map[(first.fixture_id, first.party_size)] = profile
        checkpoint = self._checkpoint(
            row_id="E01",
            fixture_id="interior_tavern",
            party_size=1,
            arm="A",
            seed=5101,
            sha="d",
        )
        resume_args: list[Any] = []

        def characterize(args: Any) -> tuple[dict[str, Any], str, str]:
            if args.lifecycle == "resume":
                resume_args.append(args)
            return self._fake_characterization(args)

        with mock.patch.object(profile_runner, "_characterize", side_effect=characterize):
            report, observed = self._run_with_profiles(
                profile_map,
                coverage,
                resume_checkpoints={"E01": {"interior_tavern": checkpoint}},
                intended_lifecycle_identities={
                    "E01": {
                        "interior_tavern": {
                            "resume": self._lifecycle_identity_declaration(
                                first,
                                fixture_id="interior_tavern",
                                lifecycle="resume",
                                resume_checkpoint_sha256="d" * 64,
                            )
                        }
                    }
                },
                use_guarded_adapter=True,
            )

        first_result = report["row_results"][0]
        resume_check = first_result["lifecycle_profile_checks"]["interior_tavern"]["resume"]
        self.assertEqual(len(resume_args), 1)
        self.assertEqual(resume_args[0].lifecycle, "resume")
        self.assertEqual(resume_args[0].planned_row_id, "E01")
        self.assertEqual(resume_args[0].resume_checkpoint_sha256, "d" * 64)
        self.assertEqual(resume_check["status"], "matched")
        self.assertEqual(resume_check["checkpoint_status"], "matched_moved_checkpoint")
        self.assertEqual(resume_check["checkpoint_sha256"], "d" * 64)
        self.assertEqual(first_result["status"], "completed")
        self.assertEqual(first_result["lifecycle_coverage_status"], "matched")
        self.assertIn("E01", observed["workers"])
        self.assertEqual(report["replacement_only_rows_activated"], [])

    def test_stale_resume_profile_source_blocks_resume(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["resume"] = self._measured_lifecycle(
            call_site, source_sha="f" * 40
        )
        profile_map[(first.fixture_id, first.party_size)] = profile
        checkpoint = self._checkpoint(
            row_id="E01",
            fixture_id="interior_tavern",
            party_size=1,
            arm="A",
            seed=5101,
            sha="d",
        )

        report, observed = self._run_with_profiles(
            profile_map,
            coverage,
            resume_checkpoints={"E01": {"interior_tavern": checkpoint}},
        )

        first_result = report["row_results"][0]
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(first_result["failure_code"], "resume_profile_source_mismatch")
        self.assertFalse(
            any(
                item["lifecycle"] == "resume"
                for item in first_result["lifecycle_results"]
            )
        )
        self.assertEqual(observed["cleaned"], ["E01"])

    def test_multi_fixture_row_runs_each_measured_fixture_lifecycle_independently(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        fixtures = ("landscape_village", "transition_tower_approach")
        for fixture_id in fixtures:
            profile = dict(profile_map[(fixture_id, 1)])
            profile["startup"] = self._measured_lifecycle(call_site)
            profile["resume"] = self._measured_lifecycle(call_site)
            profile_map[(fixture_id, 1)] = profile
        checkpoints = {
            "E04": {
                "landscape_village": self._checkpoint(
                    row_id="E04",
                    fixture_id="landscape_village",
                    party_size=1,
                    arm="D",
                    seed=5102,
                    sha="d",
                ),
                "transition_tower_approach": self._checkpoint(
                    row_id="E04",
                    fixture_id="transition_tower_approach",
                    party_size=1,
                    arm="D",
                    seed=5102,
                    sha="e",
                ),
            }
        }

        intended_lifecycle_identities: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            row_plan = _resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=profile_map,
            )
            for fixture_id in row_plan.fixture_ids:
                if fixture_id in fixtures and fixture_id != row_plan.fixture_id:
                    intended_lifecycle_identities.setdefault(row_plan.row_id, {}).setdefault(
                        fixture_id, {}
                    )["startup"] = self._lifecycle_identity_declaration(
                        row_plan,
                        fixture_id=fixture_id,
                        lifecycle="startup",
                    )
        e04_plan = _resolve_row_plan(
            "E04", prereg_root=None, expected_row=rows[3], profiles=profile_map
        )
        for fixture_id, checkpoint_sha in (
            ("landscape_village", "d" * 64),
            ("transition_tower_approach", "e" * 64),
        ):
            intended_lifecycle_identities.setdefault("E04", {}).setdefault(
                fixture_id, {}
            )["resume"] = self._lifecycle_identity_declaration(
                e04_plan,
                fixture_id=fixture_id,
                lifecycle="resume",
                resume_checkpoint_sha256=checkpoint_sha,
            )
        report, observed = self._run_with_profiles(
            profile_map,
            coverage,
            resume_checkpoints=checkpoints,
            intended_lifecycle_identities=intended_lifecycle_identities,
        )

        e04 = next(row for row in report["row_results"] if row["row_id"] == "E04")
        lifecycle_pairs = {
            (item["fixture_id"], item["lifecycle"])
            for item in e04["lifecycle_results"]
        }
        self.assertEqual(
            lifecycle_pairs,
            {
                ("landscape_village", "startup"),
                ("landscape_village", "resume"),
                ("transition_tower_approach", "startup"),
                ("transition_tower_approach", "resume"),
            },
        )
        self.assertEqual(e04["lifecycle_coverage_status"], "matched")
        self.assertEqual(report["replacement_only_rows_activated"], [])
        self.assertFalse(any(row_id.startswith("R") for row_id in observed["workers"]))
        self.assertIn(1, {row["party_size"] for row in report["row_results"]})
        self.assertIn(
            4,
            {row["party_size"] for row in report["row_results"]},
            [(row["row_id"], row.get("failure_code")) for row in report["row_results"]],
        )

    def test_secondary_and_resume_intent_mismatches_block_before_seed_or_launch(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        e04 = rows[3]

        for lifecycle in ("startup", "resume"):
            for field in ("command", "working_directory", "pythonpath"):
                with self.subTest(lifecycle=lifecycle, field=field):
                    profile_map, coverage = _load_profiles(
                        [row["row_id"] for row in rows]
                    )
                    plan = _resolve_row_plan(
                        "E04",
                        prereg_root=None,
                        expected_row=e04,
                        profiles=profile_map,
                    )
                    secondary_fixture = next(
                        fixture_id
                        for fixture_id in plan.fixture_ids
                        if fixture_id != plan.fixture_id
                    )
                    profile = dict(profile_map[(secondary_fixture, plan.party_size)])
                    profile[lifecycle] = self._measured_lifecycle(call_site)
                    profile_map[(secondary_fixture, plan.party_size)] = profile

                    checkpoints = None
                    checkpoint_sha256 = None
                    if lifecycle == "resume":
                        checkpoint = self._checkpoint(
                            row_id=plan.row_id,
                            fixture_id=secondary_fixture,
                            party_size=plan.party_size,
                            arm=plan.arm,
                            seed=plan.fixed_seed,
                            sha="d",
                        )
                        checkpoint_sha256 = checkpoint["state_sha256"]
                        checkpoints = {
                            plan.row_id: {secondary_fixture: checkpoint}
                        }

                    declaration = self._lifecycle_identity_declaration(
                        plan,
                        fixture_id=secondary_fixture,
                        lifecycle=lifecycle,
                        resume_checkpoint_sha256=checkpoint_sha256,
                    )
                    mutated = dict(declaration)
                    if field == "command":
                        mutated["command"] = [*declaration["command"], "--wrong-intent"]
                    elif field == "working_directory":
                        mutated["working_directory"] = str(
                            PROJECT_ROOT / "tmp" / "wrong-intended-cwd"
                        )
                    else:
                        mutated["pythonpath"] = declaration["pythonpath"] + os.pathsep + str(
                            PROJECT_ROOT / "tmp" / "wrong-intended-pythonpath"
                        )

                    report, observed = self._run_with_profiles(
                        profile_map,
                        coverage,
                        resume_checkpoints=checkpoints,
                        intended_lifecycle_identities={
                            plan.row_id: {
                                secondary_fixture: {lifecycle: mutated}
                            }
                        },
                    )

                    row_result = next(
                        result
                        for result in report["row_results"]
                        if result["row_id"] == plan.row_id
                    )
                    target = (plan.row_id, secondary_fixture, lifecycle)
                    self.assertEqual(
                        row_result["failure_code"], "invocation_identity_mismatch"
                    )
                    self.assertEqual(
                        row_result["lifecycle_invocation_identity_checks"][0]["check"][
                            "mismatches"
                        ][0]["field"],
                        field,
                    )
                    self.assertNotIn(target, observed["prepared_lifecycles"])
                    self.assertNotIn(target, observed["worker_lifecycles"])

    def test_missing_secondary_or_resume_intent_fails_closed_before_seed(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        e04 = rows[3]

        for lifecycle in ("startup", "resume"):
            with self.subTest(lifecycle=lifecycle):
                profile_map, coverage = _load_profiles(
                    [row["row_id"] for row in rows]
                )
                plan = _resolve_row_plan(
                    "E04",
                    prereg_root=None,
                    expected_row=e04,
                    profiles=profile_map,
                )
                secondary_fixture = next(
                    fixture_id
                    for fixture_id in plan.fixture_ids
                    if fixture_id != plan.fixture_id
                )
                profile = dict(profile_map[(secondary_fixture, plan.party_size)])
                profile[lifecycle] = self._measured_lifecycle(call_site)
                profile_map[(secondary_fixture, plan.party_size)] = profile
                checkpoints = None
                if lifecycle == "resume":
                    checkpoints = {
                        plan.row_id: {
                            secondary_fixture: self._checkpoint(
                                row_id=plan.row_id,
                                fixture_id=secondary_fixture,
                                party_size=plan.party_size,
                                arm=plan.arm,
                                seed=plan.fixed_seed,
                                sha="d",
                            )
                        }
                    }

                report, observed = self._run_with_profiles(
                    profile_map,
                    coverage,
                    resume_checkpoints=checkpoints,
                )

                row_result = next(
                    result
                    for result in report["row_results"]
                    if result["row_id"] == plan.row_id
                )
                target = (plan.row_id, secondary_fixture, lifecycle)
                self.assertEqual(
                    row_result["failure_code"],
                    "intended_lifecycle_identity_missing",
                )
                self.assertNotIn(target, observed["prepared_lifecycles"])
                self.assertNotIn(target, observed["worker_lifecycles"])

    def test_four_pc_resume_profile_runs_on_its_declared_row(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        four_pc_row = next(
            row
            for row in rows
            if _resolve_row_plan(
                row["row_id"],
                prereg_root=None,
                expected_row=row,
                profiles=profile_map,
            ).party_size
            == 4
        )
        plan = _resolve_row_plan(
            four_pc_row["row_id"],
            prereg_root=None,
            expected_row=four_pc_row,
            profiles=profile_map,
        )
        call_site = {
            "source_file": "scripts/example_router_call.py",
            "source_line": 1,
            "source_file_sha256": "c" * 64,
            "count": 1,
        }
        profile = dict(profile_map[(plan.fixture_id, 4)])
        profile["startup"] = self._measured_lifecycle(call_site)
        profile["resume"] = self._measured_lifecycle(call_site)
        profile_map[(plan.fixture_id, 4)] = profile
        checkpoint = self._checkpoint(
            row_id=plan.row_id,
            fixture_id=plan.fixture_id,
            party_size=4,
            arm=plan.arm,
            seed=plan.fixed_seed,
            sha="d",
        )
        resume_args: list[Any] = []

        def characterize(args: Any) -> tuple[dict[str, Any], str, str]:
            if args.lifecycle == "resume":
                resume_args.append(args)
            return self._fake_characterization(args)

        with mock.patch.object(profile_runner, "_characterize", side_effect=characterize):
            report, _observed = self._run_with_profiles(
                profile_map,
                coverage,
                resume_checkpoints={plan.row_id: {plan.fixture_id: checkpoint}},
                intended_lifecycle_identities={
                    plan.row_id: {
                        plan.fixture_id: {
                            "resume": self._lifecycle_identity_declaration(
                                plan,
                                fixture_id=plan.fixture_id,
                                lifecycle="resume",
                                resume_checkpoint_sha256=checkpoint["state_sha256"],
                            )
                        }
                    }
                },
                use_guarded_adapter=True,
            )

        row_result = next(
            result for result in report["row_results"] if result["row_id"] == plan.row_id
        )
        resume_result = next(
            result
            for result in row_result["lifecycle_results"]
            if result["lifecycle"] == "resume"
        )
        self.assertEqual(plan.party_size, 4)
        self.assertEqual(resume_args[0].party_size, 4)
        self.assertEqual(resume_args[0].planned_row_id, plan.row_id)
        self.assertEqual(resume_result["profile_check"]["status"], "matched")
        self.assertEqual(resume_result["profile_check"]["checkpoint_status"], "matched_moved_checkpoint")

    def test_supervised_adapter_uses_separate_non_characterization_scope(self) -> None:
        args_seen: list[Any] = []
        evidence = {"outcome": "completed"}
        with mock.patch.object(
            profile_runner,
            "_characterize",
            side_effect=lambda args: (args_seen.append(args) or evidence, "tmp/evidence", "d" * 64),
        ):
            result = profile_runner.supervise_preflight_row(
                fixture_id="interior_tavern",
                party_size=1,
                planned_row_id="E01",
                arm="A",
                source_sha=SOURCE_SHA,
                row_run_id="pf-row-integration-test-E01",
                preflight_run_id=RUN_ID,
                lifecycle="resume",
                resume_checkpoint_sha256="e" * 64,
            )

        self.assertIs(result["evidence"], evidence)
        self.assertEqual(args_seen[0].preflight_run_id, RUN_ID)
        self.assertEqual(args_seen[0].planned_row_id, "E01")
        self.assertEqual(args_seen[0].lifecycle, "resume")
        self.assertEqual(args_seen[0].resume_checkpoint_sha256, "e" * 64)
        with mock.patch.object(profile_runner, "_claim_characterization_attempt") as claim:
            claimed = profile_runner._claim_characterization_attempt_if_needed(
                args_seen[0],
                evidence_root=Path("tmp/unused"),
                run_directory=Path("tmp/unused/run"),
                attempt_record={},
            )
        self.assertFalse(claimed)
        claim.assert_not_called()

    def test_supervised_interfaces_bind_seed_worker_and_cleanup_apis(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        plan = _resolve_row_plan(
            "E01", prereg_root=None, expected_row=rows[0], profiles=profiles
        )
        row_run_id = "pf-%s-%s" % (RUN_ID, plan.row_id)
        identity = self._caller_declared_identity(
            plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            row_run_id=row_run_id,
        )
        invocation = controller.PreflightLifecycleInvocation(
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            row_run_id=row_run_id,
            intended_identity=identity,
        )
        counters = lambda: {
            "upstream_provider_requests": 0,
            "provider_budget_used": 0,
            "live_attempts_used": 0,
            "reserve_activations": 0,
        }
        interfaces = controller.supervised_preflight_interfaces(
            run_id=RUN_ID,
            safety_counters=counters,
        )
        seeded = {"status": "prepared", "fixture_id": plan.fixture_id}
        supervised = {"evidence": {"outcome": "completed"}}
        with (
            mock.patch.object(
                sandbox, "prepare_profile_sandbox", return_value=seeded
            ) as prepare,
            mock.patch.object(
                profile_runner, "supervise_preflight_row", return_value=supervised
            ) as supervise,
            mock.patch.object(
                sandbox, "remove_prepared_sandbox", return_value=True
            ) as cleanup,
        ):
            self.assertIs(
                interfaces.prepare_sandbox(
                    plan, invocation, SOURCE_SHA, RUN_ID
                ),
                seeded,
            )
            self.assertIs(
                interfaces.supervise_row(
                    plan, seeded, invocation, SOURCE_SHA, RUN_ID
                ),
                supervised,
            )
            self.assertTrue(interfaces.cleanup_sandbox(plan, seeded))

        self.assertEqual(prepare.call_args.kwargs["preflight_run_id"], RUN_ID)
        self.assertEqual(supervise.call_args.kwargs["preflight_run_id"], RUN_ID)
        self.assertEqual(cleanup.call_args.args[0]["row_id"], plan.row_id)

        multi_fixture_plan = _resolve_row_plan(
            "E04", prereg_root=None, expected_row=rows[3], profiles=profiles
        )
        self.assertGreater(len(multi_fixture_plan.fixture_ids), 1)
        later_fixture = multi_fixture_plan.fixture_ids[1]
        with mock.patch.object(
            sandbox, "remove_prepared_sandbox", return_value=True
        ) as cleanup:
            self.assertTrue(
                interfaces.cleanup_sandbox(
                    multi_fixture_plan,
                    {"status": "prepared", "fixture_id": later_fixture},
                )
            )
        self.assertEqual(cleanup.call_args.args[0]["fixture_id"], later_fixture)

    def test_resume_checkpoint_install_copies_only_row_bound_moved_state(self) -> None:
        from scripts.live_gate_preflight_sandbox import _install_row_resume_checkpoint

        with tempfile.TemporaryDirectory(
            prefix="preflight-resume-checkpoint-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            project_root = Path(temp_root)
            checkpoint_root = project_root / "tmp" / "checkpoint"
            active_root = project_root / "tmp" / "active"
            active_root.mkdir(parents=True)
            seed_plan, _profile = sandbox._load_profile_seed_plan(
                "interior_tavern", 1, "E01"
            )
            module_payloads, expected_payloads = sandbox._load_profile_seed_inputs(
                PROJECT_ROOT
            )
            written = sandbox._write_fixture_module(
                active_root, seed_plan, module_payloads, expected_payloads
            )
            metadata = sandbox._write_seed_state(
                PROJECT_ROOT,
                active_root,
                seed_plan,
                written["module_payloads"],
                written["mapping"],
            )
            shutil.copytree(active_root / "characters", checkpoint_root / "characters")
            shutil.copytree(
                active_root / "modules" / "Mapping_Pilot_Arena" / "areas",
                checkpoint_root / "modules" / "Mapping_Pilot_Arena" / "areas",
            )
            shutil.copy2(active_root / "party_tracker.json", checkpoint_root / "party_tracker.json")
            (checkpoint_root / "mapping_pilot").mkdir()
            shutil.copy2(
                active_root / "mapping_pilot" / "seed_metadata.json",
                checkpoint_root / "mapping_pilot" / "seed_metadata.json",
            )
            fixture = expected_payloads["interior_tavern"]["source_truth"]
            start_source = seed_plan["source_location_id"]
            start_location = next(
                item for item in fixture["locations"] if item["location_id"] == start_source
            )
            open_exits = [
                item
                for item in start_location.get("exits", [])
                if item.get("state") == "open"
                and item.get("destination_knowledge") == "known"
            ]
            self.assertEqual(len(open_exits), 1)
            destination_source = open_exits[0]["known_destination_location_id"]
            runtime_ids = module_payloads["location_id_map.json"]["runtime_location_ids"]
            destination_runtime = runtime_ids[destination_source]
            destination_area, destination_area_payload, destination_location = (
                sandbox._runtime_location(module_payloads, destination_runtime)
            )
            moved_tracker_path = checkpoint_root / "party_tracker.json"
            moved_tracker = json.loads(moved_tracker_path.read_text(encoding="utf-8"))
            moved_world = moved_tracker["worldConditions"]
            moved_world["currentLocationId"] = destination_runtime
            moved_world["currentLocation"] = destination_location.get("name")
            moved_world["currentAreaId"] = destination_area
            moved_world["currentArea"] = destination_area_payload.get("areaName")
            moved_tracker_path.write_text(
                json.dumps(moved_tracker, sort_keys=True), encoding="ascii"
            )
            checkpoint_sha = launcher._canonical_state_sha256(checkpoint_root)
            root_owner = project_root
            checkpoint = {
                "checkpoint_root": "tmp/checkpoint",
                "state_sha256": checkpoint_sha,
                "row_id": "E01",
                "fixture_id": "interior_tavern",
                "party_size": 1,
                "arm": seed_plan["arm"],
                "fixed_seed": seed_plan["effective_seed"],
            }
            plan = {
                "counterbalance": seed_plan["counterbalance"],
                "fixture_id": "interior_tavern",
                "party_size": 1,
                "arm": seed_plan["arm"],
                "effective_seed": seed_plan["effective_seed"],
            }

            def validate_resume(
                root: Path,
                *,
                arm: str,
                fixture_id: str,
                party_size: int,
                resume: bool,
                resume_checkpoint_sha256: str | None,
                project_root: Path,
            ) -> object:
                self.assertEqual(root, active_root)
                self.assertEqual(project_root, root_owner)
                self.assertEqual((fixture_id, party_size), ("interior_tavern", 1))
                self.assertEqual(arm, seed_plan["arm"])
                self.assertTrue(resume)
                self.assertEqual(resume_checkpoint_sha256, checkpoint_sha)
                self.assertEqual(launcher._canonical_state_sha256(root), checkpoint_sha)
                current_metadata = json.loads(
                    (root / "mapping_pilot" / "seed_metadata.json").read_text()
                )
                moved_tracker = json.loads((root / "party_tracker.json").read_text())
                world = moved_tracker["worldConditions"]
                id_map = json.loads(
                    (
                        root
                        / "modules"
                        / "Mapping_Pilot_Arena"
                        / "location_id_map.json"
                    ).read_text()
                )
                runtime_to_source = {
                    runtime_id: source_id
                    for source_id, runtime_id in id_map["runtime_location_ids"].items()
                }
                launcher._validate_resume_checkpoint(
                    root,
                    fixture_id="interior_tavern",
                    mapping=current_metadata["mapping"],
                    tracker=moved_tracker,
                    world=world,
                    runtime_to_source=runtime_to_source,
                    resume_checkpoint_sha256=checkpoint_sha,
                )
                return object()

            with mock.patch.object(launcher, "validate_sandbox", side_effect=validate_resume):
                _install_row_resume_checkpoint(
                    project_root,
                    active_root,
                    plan,
                    checkpoint,
                    expected_sha256=checkpoint_sha,
                )

    def test_row_guard_journal_is_scoped_to_preflight_row_evidence(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-journal-", dir=PROJECT_ROOT / "tmp"
        ) as temp_root:
            run_directory = (
                Path(temp_root)
                / RUN_ID
                / "preflight"
                / "rows"
                / "pf-row-integration-test-E01"
            )
            run_directory.mkdir(parents=True)
            journal = run_directory / "guard-events.jsonl"
            with (
                mock.patch.object(safety, "PROJECT_ROOT", PROJECT_ROOT),
                mock.patch.object(
                    safety,
                    "ROW_PREFLIGHT_GUARD_ROOT",
                    Path(temp_root).relative_to(PROJECT_ROOT),
                ),
            ):
                self.assertEqual(
                    safety._validate_guard_event_path(
                        journal, "pf-row-integration-test-E01"
                    ),
                    journal,
                )
                with self.assertRaisesRegex(
                    safety.SafetyConfigurationError,
                    "guard-event path identity is invalid",
                ):
                    safety._validate_guard_event_path(journal, "different-row")


class TestSupervisedEvidenceIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.run_id = "evidence-integration-" + uuid.uuid4().hex[:12]
        self.evidence_root = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / self.run_id
        )
        self.addCleanup(self._remove_evidence)

    def _remove_evidence(self) -> None:
        if self.evidence_root.exists() and not self.evidence_root.is_symlink():
            shutil.rmtree(self.evidence_root)

    @staticmethod
    def _zero_safety_counters() -> dict[str, int]:
        return {
            "upstream_provider_requests": 0,
            "provider_budget_used": 0,
            "live_attempts_used": 0,
            "reserve_activations": 0,
        }

    def _worker_identities(self) -> dict[str, dict[str, Any]]:
        rows, _reserves = _load_frozen_row_ids(None)
        expected_ids = [str(row["row_id"]) for row in rows]
        profiles, _coverage = _load_profiles(expected_ids)
        identities: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_id = str(row["row_id"])
            plan = _resolve_row_plan(
                row_id,
                prereg_root=None,
                expected_row=row,
                profiles=profiles,
            )
            identities[row_id] = controller.planned_worker_identity(
                plan,
                source_sha=SOURCE_SHA,
                row_run_id="pf-%s-%s" % (self.run_id, row_id),
                preflight_run_id=self.run_id,
            )
        return identities

    def test_supervised_entrypoint_persists_worker_identity_mismatch_without_host_start(
        self,
    ) -> None:
        observed_invocation = safety.current_invocation_identity()
        intended_workers = self._worker_identities()
        intended_workers["E01"] = {
            **intended_workers["E01"],
            "command": ["not-the-planned-worker"],
        }
        with (
            mock.patch.object(sandbox, "prepare_profile_sandbox") as prepare,
            mock.patch.object(profile_runner, "supervise_preflight_row") as supervise,
            mock.patch.object(sandbox, "remove_prepared_sandbox") as cleanup,
        ):
            result = controller.run_preflight_rows_supervised(
                source_sha=SOURCE_SHA,
                run_id=self.run_id,
                intended_worker_identities=intended_workers,
                safety_counters=self._zero_safety_counters,
                dependency_lock_path=PROJECT_ROOT / "requirements-lock.txt",
                routing_identity={
                    "provider": "openrouter",
                    "active_profile": "production-auto",
                },
                intended_invocation=observed_invocation,
            )

        evidence_path = PROJECT_ROOT / result["preflight_evidence_path"]
        self.assertTrue(evidence_path.is_file())
        report = json.loads(evidence_path.read_text(encoding="ascii"))
        self.assertEqual(report["preflight_status"], "BLOCKED")
        self.assertFalse(report["booking_eligible"])
        self.assertFalse(report["booking_ruling_issued"])
        self.assertFalse(report["live_gate_pass"])
        self.assertEqual(
            report["execution_provenance"], "supervised-retained-evidence"
        )
        self.assertEqual(report["identity"]["source_sha"], SOURCE_SHA)
        self.assertIsNotNone(report["identity"]["dependency_lock_sha256"])
        self.assertIsNotNone(report["identity"]["routing_identity_sha256"])
        self.assertEqual(report["invocation_identity"]["status"], "matched")
        self.assertEqual(report["row_coverage"]["attempted_row_ids"], ["E01"])
        first_row = report["row_coverage"]["row_outcomes"][0]
        self.assertEqual(first_row["row_id"], "E01")
        self.assertEqual(first_row["status"], "blocked")
        self.assertEqual(first_row["invocation_identity_status"], "blocked")
        self.assertFalse(result["booking_eligible"])
        proposed_identity = {
            "source_sha": SOURCE_SHA,
            "dependency_lock_sha256": evidence.dependency_lock_sha256(
                PROJECT_ROOT / "requirements-lock.txt"
            ),
            "routing_identity": {
                "provider": "openrouter",
                "active_profile": "production-auto",
            },
            "invocation_identity": observed_invocation,
        }
        exact = evidence.check_booking_eligibility(
            run_id=self.run_id,
            proposed_identity=proposed_identity,
        )
        self.assertTrue(exact["identity_match"])
        self.assertFalse(exact["eligible"])
        changed = evidence.check_booking_eligibility(
            run_id=self.run_id,
            proposed_identity={**proposed_identity, "source_sha": "b" * 40},
        )
        self.assertFalse(changed["identity_match"])
        self.assertFalse(changed["eligible"])
        self.assertEqual(changed["mismatches"], ["source_sha"])
        prepare.assert_not_called()
        supervise.assert_not_called()
        cleanup.assert_not_called()

    def test_declared_invocation_mismatch_persists_blocked_before_row_execution(
        self,
    ) -> None:
        observed_invocation = safety.current_invocation_identity()
        intended_invocation = {
            **observed_invocation,
            "command": [*observed_invocation["command"], "--different"],
        }
        with (
            mock.patch.object(sandbox, "prepare_profile_sandbox") as prepare,
            mock.patch.object(profile_runner, "supervise_preflight_row") as supervise,
        ):
            result = controller.run_preflight_rows_supervised(
                source_sha=SOURCE_SHA,
                run_id=self.run_id,
                safety_counters=self._zero_safety_counters,
                dependency_lock_path=PROJECT_ROOT / "requirements-lock.txt",
                routing_identity={
                    "provider": "openrouter",
                    "active_profile": "production-auto",
                },
                intended_invocation=intended_invocation,
            )

        report = json.loads(
            (PROJECT_ROOT / result["preflight_evidence_path"]).read_text(
                encoding="ascii"
            )
        )
        self.assertEqual(report["preflight_status"], "BLOCKED")
        self.assertEqual(report["invocation_identity"]["status"], "blocked")
        self.assertEqual(
            report["invocation_identity"]["mismatches"], [{"field": "command"}]
        )
        self.assertEqual(report["entrypoint_failure_code"], "invocation_identity_mismatch")
        self.assertTrue(
            all(
                row["status"] == "MISSING"
                for row in report["row_coverage"]["row_outcomes"]
            )
        )
        self.assertFalse(result["booking_eligible"])
        prepare.assert_not_called()
        supervise.assert_not_called()

    def test_missing_required_inputs_persist_blocked_evidence(self) -> None:
        with (
            mock.patch.object(sandbox, "prepare_profile_sandbox") as prepare,
            mock.patch.object(profile_runner, "supervise_preflight_row") as supervise,
        ):
            result = controller.run_preflight_rows_supervised(
                run_id=self.run_id,
                safety_counters=self._zero_safety_counters,
            )

        evidence_path = PROJECT_ROOT / result["preflight_evidence_path"]
        self.assertTrue(evidence_path.is_file())
        report = json.loads(evidence_path.read_text(encoding="ascii"))
        self.assertEqual(report["preflight_status"], "BLOCKED")
        self.assertFalse(report["booking_eligible"])
        self.assertIsNone(report["identity"]["source_sha"])
        self.assertIsNone(report["identity"]["dependency_lock_sha256"])
        self.assertIsNone(report["identity"]["routing_identity_sha256"])
        self.assertEqual(report["execution_provenance"], "unverified")
        self.assertTrue(
            all(
                row["status"] == "MISSING"
                for row in report["row_coverage"]["row_outcomes"]
            )
        )
        self.assertFalse(result["booking_eligible"])
        self.assertTrue(result.get("preflight_failure_code"))
        prepare.assert_not_called()
        supervise.assert_not_called()


if __name__ == "__main__":
    unittest.main()
