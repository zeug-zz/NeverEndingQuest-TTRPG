# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic SP3 row-preflight integration tests; these are not live coverage."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
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


def setUpModule() -> None:
    (PROJECT_ROOT / "tmp").mkdir(parents=True, exist_ok=True)


def _require_repository_python(test_case: unittest.TestCase) -> None:
    path = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not path.is_file():
        test_case.skipTest("missing required path: %s" % path)


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
from scripts import live_gate_preflight_profiles as preflight_profiles
from scripts import live_gate_preflight_sandbox as sandbox
from scripts import live_gate_preflight_profile_runner as profile_runner
from scripts import live_gate_preflight_retained as retained
from scripts import live_gate_preflight_safety as safety
from scripts.mapping_pilot import launcher, row_runner, server


BASELINE_PROFILE_PATH = (
    PROJECT_ROOT / "scripts" / "fixtures" / "live_gate_preflight_profiles_all_missing.json"
)

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


def _measured_declaration(
    call_sites: list[dict[str, Any]],
    *,
    call_count: int | None = None,
    required: bool = True,
) -> dict[str, Any]:
    """Content-bound measured declaration; stub/driver hashes from this tree."""
    from scripts import live_gate_preflight_profiles as profiles

    hashes = profiles.tool_file_hashes()
    return {
        "status": "measured-under-stub",
        "required": required,
        "call_count": (
            call_count
            if call_count is not None
            else sum(site["count"] for site in call_sites)
        ),
        "call_sites": [dict(site) for site in call_sites],
        "stub_sha256": {
            "path": profiles.STUB_FILE,
            "sha256": hashes[profiles.STUB_FILE],
        },
        "driver_sha256": [
            {"path": path, "sha256": hashes[path]} for path in profiles.DRIVER_FILES
        ],
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


def _baseline_profile_patches() -> list[Any]:
    """Patches that make the controller read the committed all-MISSING baseline.

    The checked-in declaration now carries measured profiles; tests that build
    synthetic measured declarations on top of a MISSING baseline load this
    fixture through the same loader seam (_load_profiles imports both names from
    scripts.live_gate_preflight_profiles at call time).
    """
    original_coverage = preflight_profiles.load_profile_coverage

    def baseline_coverage(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return original_coverage(BASELINE_PROFILE_PATH)

    def baseline_document() -> dict[str, Any]:
        return json.loads(BASELINE_PROFILE_PATH.read_text(encoding="utf-8"))

    return [
        mock.patch.object(preflight_profiles, "load_profile_coverage", baseline_coverage),
        mock.patch.object(preflight_profiles, "copy_profile_document", baseline_document),
    ]


class TestPreflightRowIntegration(unittest.TestCase):
    def setUp(self) -> None:
        if self._testMethodName in {
            "test_all_26_planned_rows_cross_existing_sp3_interfaces",
            "test_capture_rejects_durable_release_log_that_differs_from_sidecar",
            "test_checkpoint_result_reconciles_late_guarded_child_evidence",
            "test_comparison_identity_is_reconciled_from_retained_worker_and_teardown",
            "test_four_pc_resume_profile_runs_on_its_declared_row",
            "test_invocation_mismatch_blocks_before_seeding_or_worker_launch",
            "test_late_parent_subprocess_events_are_preserved_and_rejected",
            "test_measured_resume_without_row_checkpoint_stays_missing_and_unverified",
            "test_measured_startup_call_count_mismatch_blocks_and_cleans_sandbox",
            "test_measured_startup_call_site_mismatch_blocks",
            "test_measured_startup_profile_matches_calls_but_resume_stays_unverified",
            "test_missing_fixture_payload_is_reported_and_never_covered",
            "test_missing_secondary_or_resume_intent_fails_closed_before_seed",
            "test_multi_fixture_row_runs_each_measured_fixture_lifecycle_independently",
            "test_retained_reconciliation_accepts_both_attributed_shutdown_forms",
            "test_retained_reconciliation_rejects_active_listener_and_incomplete_teardown",
            "test_retained_reconciliation_rejects_missing_malformed_and_tampered_files",
            "test_retained_reconciliation_rejects_unguarded_and_foreign_egress_events",
            "test_retained_teardown_sidecar_fails_closed_on_missing_tampered_and_conflicting_proof",
            "test_retained_v2_wait_proof_is_strict_and_legacy_v1_still_validates",
            "test_retained_validation_snapshot_preserves_complete_journal",
            "test_retained_validator_input_bundle_fails_closed_on_missing_or_tampered_copy",
            "test_retained_validator_inputs_are_self_contained_for_offline_revalidation",
            "test_retained_worker_checkpoint_travel_is_required_and_exact",
            "test_secondary_and_resume_intent_mismatches_block_before_seed_or_launch",
            "test_sequential_lifecycles_capture_fresh_snapshot_before_supervision",
            "test_stale_call_site_file_hash_blocks_as_profile_mismatch",
            "test_stale_id_map_file_literal_blocks_location_mapping_unresolved",
            "test_stale_stub_hash_blocks_as_profile_mismatch",
            "test_supervised_interfaces_bind_seed_worker_and_cleanup_apis",
            "test_supervised_interfaces_forward_comparison_identity_to_row_supervisor",
            "test_supervised_interfaces_pass_none_comparison_identity_in_same_sha_mode",
            "test_supplied_row_checkpoint_runs_guarded_resume_and_matches_profile",
        }:
            _require_repository_python(self)
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
        self._baseline_patches = _baseline_profile_patches()
        for baseline_patch in self._baseline_patches:
            baseline_patch.start()
            self.addCleanup(baseline_patch.stop)
        self._git_common_patch = mock.patch.object(
            profile_runner,
            "_git_common_directory",
            side_effect=self._fake_git_common_directory,
        )
        self._git_common_patch.start()
        self.addCleanup(self._git_common_patch.stop)

    def _start_fresh_preflight_run(self) -> None:
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
    def _synthetic_empty_listener_census(port: int) -> dict[str, Any]:
        output = b""
        identity = {
            "observer": "lsof",
            "census_method": "tcp-listen",
            "port": port,
            "command": [
                profile_runner.LSOF_EXECUTABLE,
                "-nP",
                "-iTCP:%d" % port,
                "-sTCP:LISTEN",
            ],
            "returncode": 1,
            "stdout_byte_count": 0,
            "stdout_sha256": hashlib.sha256(output).hexdigest(),
        }
        return {
            "schema_version": 1,
            "method": "lsof-tcp-listen",
            "port": port,
            **identity,
            "identity_sha256": profile_runner._canonical_json_sha256(identity),
            "observed": True,
            "parseable": True,
            "listener_pids": [],
            "failure_code": None,
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
        late_guarded_child: bool = False,
        teardown_schema_version: int = 1,
    ) -> tuple[dict[str, Any], str, str]:
        comparison_identity = getattr(args, "comparison_identity_json", None)
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
            comparison_identity=comparison_identity,
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
        child_evidence_path = evidence_directory / "adv-summary-child.jsonl"
        child_evidence_path.write_bytes(b"")
        child_summary = {
            "schema_version": 1,
            "adapter_installed": True,
            "launch_count": 0,
            "launches": [],
            "calls": [],
            "failure_code": None,
            "evidence_path": child_evidence_path.relative_to(
                PROJECT_ROOT
            ).as_posix(),
            "evidence_sha256": hashlib.sha256(b"").hexdigest(),
            "record_count": 0,
        }
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
        late_child_pid = 104
        if late_guarded_child:
            child_command_sha256 = "d" * 64
            child_common = {
                "schema_version": 1,
                "pid": late_child_pid,
                "process_group_id": host_worker_pid,
                "process_role": "host",
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
            late_child_events = [
                {
                    **child_common,
                    "sequence": 1,
                    "event_type": "guard_startup",
                    "observed_at_ns": 1_000_004,
                    "operation": None,
                    "decision": None,
                    "command_sha256": child_command_sha256,
                    "guard_active": True,
                    "interpreter": interpreter,
                    "working_directory": host_cwd,
                },
                {
                    **child_common,
                    "sequence": 2,
                    "event_type": "network_attempt",
                    "observed_at_ns": 1_000_005,
                    "operation": "connect",
                    "decision": "denied",
                    "target_host": "192.0.2.1",
                    "target_port": 8360,
                },
                {
                    **child_common,
                    "sequence": 3,
                    "event_type": "subprocess_attempt",
                    "observed_at_ns": 1_000_006,
                    "operation": "Popen",
                    "decision": "denied",
                    "command_sha256": "e" * 64,
                },
            ]
            journal.extend(
                [
                    {
                        "schema_version": 1,
                        "sequence": 4,
                        "event_type": "subprocess_started",
                        "pid": host_worker_pid,
                        "process_group_id": host_worker_pid,
                        "process_role": "host",
                        "run_id": args.run_id,
                        "observed_at_ns": 1_000_004,
                        "operation": "Popen",
                        "decision": "started",
                        "target_host": None,
                        "target_port": None,
                        "target_host_sha256": None,
                        "command_sha256": child_command_sha256,
                        "child_pid": late_child_pid,
                        "child_is_python": True,
                        "guard_active": None,
                        "interpreter": None,
                        "working_directory": None,
                    },
                    *late_child_events,
                ]
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
        host_ready_events = list(journal)
        if late_guarded_child:
            host_ready_events = [
                event
                for report in canaries
                for event in snapshots[report["canary_stage"]]
            ]
        for phase in ("before_host", "host_ready", "after_teardown"):
            if phase == "before_host":
                phase_events = [
                    event
                    for report in canaries[:2]
                    for event in snapshots[report["canary_stage"]]
                ]
            elif phase == "host_ready":
                phase_events = host_ready_events
            else:
                phase_events = journal
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
                "run_process_pids": sorted(
                    {event["pid"] for event in phase_events}
                    | {
                        event["child_pid"]
                        for event in phase_events
                        if event.get("event_type") == "subprocess_started"
                    }
                ),
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
        python_child_pids = sorted(
            {
                event["child_pid"]
                for event in journal
                if event.get("event_type") == "subprocess_started"
                and event.get("child_is_python") is True
            }
        )
        guarded_pids = sorted(
            {
                event["pid"]
                for event in journal
                if event.get("event_type") == "guard_startup"
            }
        )
        census = {
            "controller_pid": controller_pid,
            "driver_pid": controller_pid,
            "host_prelaunch_pid": host_prelaunch_pid,
            "host_worker_pid": host_worker_pid,
            "launched_pids": sorted((controller_pid, host_prelaunch_pid, host_worker_pid)),
            "socket_owner_pids": socket_owners,
            "python_child_pids": python_child_pids,
            "python_pids": sorted(
                set((controller_pid, host_prelaunch_pid, host_worker_pid))
                | set(python_child_pids)
                | set(socket_owners)
                | set(guarded_pids)
            ),
            "guarded_pids": guarded_pids,
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
            "adv_summary_child": child_summary,
        }
        if comparison_identity is not None:
            worker_result["comparison_identity"] = dict(comparison_identity)
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
        port_observations = {
            str(port): self._synthetic_free_bind_observation(port)
            for port in (8360, 8370)
        }
        after_teardown_sample = census_samples[2]
        teardown_wait: dict[str, Any] | None = None
        if teardown_schema_version == 2:
            wait_attempt = {
                "started_monotonic_ns": 0,
                "completed_monotonic_ns": 0,
                "listener_census": {
                    str(port): self._synthetic_empty_listener_census(port)
                    for port in (8360, 8370)
                },
                "port_observations": {
                    port: dict(observation)
                    for port, observation in port_observations.items()
                },
            }
            teardown_wait = {
                "schema_version": 1,
                "clock": "time.monotonic_ns",
                "lock_held": True,
                "status": "ports_free",
                "failure_code": None,
                "timeout_ns": 75_000_000_000,
                "poll_interval_ns": 1_000_000_000,
                "started_monotonic_ns": 0,
                "completed_monotonic_ns": 0,
                "elapsed_monotonic_ns": 0,
                "attempts": [wait_attempt],
                "initial": wait_attempt,
                "final": wait_attempt,
                "final_process_census": {
                    "phase": "after_teardown",
                    "path": after_teardown_sample["evidence_path"],
                    "sha256": after_teardown_sample["evidence_sha256"],
                    "observed": True,
                    "listener_pids": [],
                    "observed_monotonic_ns": 1,
                },
            }
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
            "teardown_evidence_schema_version": teardown_schema_version,
            "teardown_evidence_path": teardown_path,
        }
        if teardown_wait is not None:
            wait_raw = json.dumps(
                teardown_wait,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            release_record.update(
                {
                    "teardown_wait_schema_version": 1,
                    "teardown_wait_sha256": hashlib.sha256(wait_raw).hexdigest(),
                    "teardown_wait_elapsed_monotonic_ns": 0,
                    "teardown_wait_completed_monotonic_ns": 0,
                    "after_teardown_socket_sample_observed_monotonic_ns": 1,
                }
            )
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
            "schema_version": teardown_schema_version,
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
            "port_observations": port_observations,
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
        if teardown_wait is not None:
            teardown_sidecar["teardown_wait"] = teardown_wait
        if comparison_identity is not None:
            teardown_sidecar["comparison_identity"] = dict(comparison_identity)
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
            "adv_summary_child": child_summary,
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
        self,
        *,
        server_returned: bool = True,
        source_sha: str = SOURCE_SHA,
        comparison_identity: dict[str, Any] | None = None,
        late_guarded_child: bool = False,
        teardown_schema_version: int = 1,
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
            source_sha=source_sha,
            run_id=row_run_id,
            planned_row_id=plan.row_id,
            arm=plan.arm,
            resume_checkpoint_sha256=None,
            preflight_run_id=RUN_ID,
            comparison_identity_json=(
                dict(comparison_identity) if comparison_identity is not None else None
            ),
        )
        evidence, evidence_path, evidence_sha256 = self._fake_characterization(
            args,
            server_returned=server_returned,
            late_guarded_child=late_guarded_child,
            teardown_schema_version=teardown_schema_version,
        )
        intended_identity = planned_worker_identity(
            plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            source_sha=source_sha,
            row_run_id=row_run_id,
            resume_checkpoint_sha256=None,
            preflight_run_id=RUN_ID,
            comparison_identity=comparison_identity,
        )
        result = {
            "evidence": evidence,
            "evidence_path": evidence_path,
            "evidence_sha256": evidence_sha256,
        }
        if comparison_identity is not None:
            result["comparison_identity"] = dict(comparison_identity)
        return plan, row_run_id, intended_identity, result

    def _add_synthetic_checkpoint(
        self,
        plan: controller.PreflightRowPlan,
        row_run_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = result["evidence"]
        checkpoint_root = (
            "tmp/router-rollout/live-gate-preflight-checkpoints/"
            "%s/%s/%s-p%d"
            % (row_run_id, plan.row_id, plan.fixture_id, plan.party_size)
        )
        checkpoint_directory = PROJECT_ROOT / checkpoint_root
        checkpoint_run_directory = checkpoint_directory.parents[1]
        checkpoint_run_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, checkpoint_run_directory, ignore_errors=True)

        travel = {
            "step_id": "checkpoint-step-01",
            "source_location_id": "INTERIOR_01",
            "source_runtime_location_id": "INTERIOR_01",
            "target_source_location_id": "INTERIOR_02",
            "target_location_id": "INTERIOR_02",
            "response_counts": {
                "travel_action_responses": 1,
                "gameplay_validation_responses": 1,
                "transition_validation_responses": 1,
                "transition_narration_responses": 1,
            },
            "response_call_sequences": {
                "travel_action": 2,
                "transition_validation": 3,
                "gameplay_validation": 4,
                "transition_narration": 5,
            },
            "complete": True,
        }
        state_sha256 = "c" * 64
        checkpoint = {
            "checkpoint_root": checkpoint_root,
            "state_sha256": state_sha256,
            "row_id": plan.row_id,
            "fixture_id": plan.fixture_id,
            "party_size": plan.party_size,
            "arm": plan.arm,
            "fixed_seed": plan.fixed_seed,
        }
        attestation = {
            "schema_version": 1,
            "source_sha": evidence["source_sha"],
            "run_id": row_run_id,
            "row_id": plan.row_id,
            "fixture_id": plan.fixture_id,
            "party_size": plan.party_size,
            "arm": plan.arm,
            "fixed_seed": plan.fixed_seed,
            "step_id": travel["step_id"],
            "source_location_id": travel["source_location_id"],
            "source_runtime_location_id": travel["source_runtime_location_id"],
            "target_source_location_id": travel["target_source_location_id"],
            "target_location_id": travel["target_location_id"],
            "initial_location_id": travel["source_runtime_location_id"],
            "final_location_id": travel["target_location_id"],
            "initial_state_sha256": "b" * 64,
            "state_sha256": state_sha256,
            "initial_time": "day-1 08:00",
            "final_time": "day-1 08:05",
            "travel_proof": travel,
            "persistence": {
                "host_stopped_before_checkpoint": True,
                "canonical_state_hash_verified": True,
                "resume_state_validation": "passed",
            },
            "checkpoint_root": checkpoint_root,
        }
        checkpoint_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        attestation_path = checkpoint_directory / "attestation.json"
        attestation_bytes = json.dumps(
            attestation, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        attestation_path.write_bytes(attestation_bytes)
        evidence.update(
            {
                "checkpoint_travel": travel,
                "resume_checkpoint": checkpoint,
                "checkpoint_attestation": {
                    "path": checkpoint_root + "/attestation.json",
                    "sha256": hashlib.sha256(attestation_bytes).hexdigest(),
                },
            }
        )
        self._rewrite_profile_evidence(result, evidence)
        worker_path = PROJECT_ROOT / result["evidence_path"]
        worker_result_path = worker_path.with_name("worker-result.json")
        worker_result = json.loads(worker_result_path.read_text(encoding="utf-8"))
        worker_result["checkpoint_travel"] = travel
        self._rewrite_worker_result(result, worker_result)
        return checkpoint

    @staticmethod
    def _rewrite_profile_evidence(result: dict[str, Any], evidence: dict[str, Any]) -> None:
        evidence_path = PROJECT_ROOT / result["evidence_path"]
        raw = json.dumps(
            evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        evidence_path.write_bytes(raw)
        result["evidence"] = evidence
        result["evidence_sha256"] = hashlib.sha256(raw).hexdigest()

    def _rewrite_worker_result(
        self, result: dict[str, Any], worker_result: dict[str, Any]
    ) -> None:
        evidence_path = PROJECT_ROOT / result["evidence_path"]
        worker_path = evidence_path.with_name("worker-result.json")
        worker_raw = json.dumps(
            worker_result, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        worker_path.write_bytes(worker_raw)

        teardown_path = (
            PROJECT_ROOT / result["evidence"]["teardown_evidence"]["path"]
        )
        teardown = json.loads(teardown_path.read_text(encoding="utf-8"))
        teardown["worker_stop"]["worker_result_sha256"] = hashlib.sha256(
            worker_raw
        ).hexdigest()
        self._rewrite_teardown_sidecar(result, teardown)

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

    def _validate_retained_case(
        self,
        plan: controller.PreflightRowPlan,
        row_run_id: str,
        intended_identity: dict[str, Any],
        result: dict[str, Any],
        comparison_identity: dict[str, Any] | None = None,
        validation_snapshot: retained.RetainedValidationSnapshot | None = None,
    ) -> dict[str, Any]:
        source_sha = (
            comparison_identity["application"]["sha"]
            if comparison_identity is not None
            else SOURCE_SHA
        )
        evidence_directory = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / RUN_ID
            / "preflight"
            / "rows"
            / row_run_id
        )
        manifest_path = (
            evidence_directory / "retained" / "validator-inputs" / "manifest.json"
        )
        capture_validator_inputs = not manifest_path.exists()
        if capture_validator_inputs and validation_snapshot is None:
            validation_snapshot = self._synthetic_validation_snapshot(source_sha)
        elif not capture_validator_inputs:
            validation_snapshot = None
        manifest_relative = (
            manifest_path.relative_to(PROJECT_ROOT).as_posix()
            if manifest_path.exists()
            else None
        )
        manifest_sha256 = (
            hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            if manifest_path.exists()
            else None
        )
        return retained.validate_retained_supervised_evidence(
            result,
            plan=plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            intended_identity=intended_identity,
            source_sha=source_sha,
            row_run_id=row_run_id,
            preflight_run_id=RUN_ID,
            comparison_identity=comparison_identity,
            validation_snapshot=validation_snapshot,
            capture_validator_inputs=capture_validator_inputs,
            validator_input_bundle_path=manifest_relative,
            validator_input_bundle_sha256=manifest_sha256,
        )

    def _synthetic_validation_snapshot(
        self, source_sha: str = SOURCE_SHA
    ) -> retained.RetainedValidationSnapshot:
        if self.fake_common_directory is None:
            raise AssertionError("synthetic durable lock directory was not prepared")
        return retained.RetainedValidationSnapshot(
            source_sha=source_sha,
            summary_source_bytes=b"synthetic committed summary source",
            runner_source_bytes=Path(profile_runner.__file__).read_bytes(),
            git_common_directory=self.fake_common_directory,
        )

    def test_validation_snapshot_captures_git_inputs_before_journal_binding(self) -> None:
        common_directory = self.retained_run_directory / "synthetic-git-common"
        common_directory.mkdir(parents=True)
        operations: list[str] = []
        summary_source = b"trusted summary source at the declared SHA"

        def read_summary_source(source_sha: str, relative_path: str) -> bytes:
            self.assertEqual(source_sha, SOURCE_SHA)
            self.assertEqual(relative_path, "core/ai/adv_summary.py")
            operations.append("summary_source")
            return summary_source

        def read_common_directory() -> Path:
            operations.append("git_common_directory")
            return common_directory

        with (
            mock.patch.object(safety, "_GUARD_EVENT_SINK", None),
            mock.patch.object(
                profile_runner,
                "_git_source_bytes_at_sha",
                side_effect=read_summary_source,
            ) as source_lookup,
            mock.patch.object(
                profile_runner,
                "_git_common_directory",
                side_effect=read_common_directory,
            ) as common_lookup,
        ):
            snapshot = retained.capture_retained_validation_snapshot(SOURCE_SHA)

        self.assertEqual(snapshot.source_sha, SOURCE_SHA)
        self.assertEqual(snapshot.summary_source_bytes, summary_source)
        self.assertEqual(
            snapshot.runner_source_bytes,
            Path(profile_runner.__file__).read_bytes(),
        )
        self.assertEqual(snapshot.git_common_directory, common_directory)
        self.assertEqual(operations, ["summary_source", "git_common_directory"])
        source_lookup.assert_called_once_with(
            SOURCE_SHA, "core/ai/adv_summary.py"
        )
        common_lookup.assert_called_once_with()

        with (
            mock.patch.object(
                safety, "_GUARD_EVENT_SINK", common_directory / "bound.jsonl"
            ),
            mock.patch.object(profile_runner, "_git_source_bytes_at_sha") as source_lookup,
            mock.patch.object(profile_runner, "_git_common_directory") as common_lookup,
        ):
            with self.assertRaisesRegex(
                retained.RetainedEvidenceError,
                "must precede guard-event journal binding",
            ):
                retained.capture_retained_validation_snapshot(SOURCE_SHA)
        source_lookup.assert_not_called()
        common_lookup.assert_not_called()

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
        call_site: dict[str, Any], *, required: bool = True
    ) -> dict[str, Any]:
        if call_site.get("source_file") == "scripts/example_router_call.py":
            call_site = _synthetic_call_site(count=call_site["count"])
        return _measured_declaration([call_site], required=required)

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
            self.fake_common_directory = (
                self.retained_run_directory
                / "fake-git-common"
                / invocation.row_run_id
            )
            self.fake_common_directory.mkdir(parents=True, exist_ok=True)
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
                "id_map_file": "modules/%s/location_id_map.json"
                % launcher.MAPPING_PILOT_MODULE,
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

        def capture_validation_snapshot(source_sha: str) -> retained.RetainedValidationSnapshot:
            self.assertEqual(source_sha, SOURCE_SHA)
            return self._synthetic_validation_snapshot(source_sha)

        interfaces = PreflightInterfaces(
            prepare_sandbox=prepare,
            supervise_row=supervise_row,
            cleanup_sandbox=cleanup_sandbox,
            safety_counters=counters,
            capture_retained_validation_snapshot=capture_validation_snapshot,
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

    def test_retained_validator_inputs_are_self_contained_for_offline_revalidation(
        self,
    ) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        captured = self._validate_retained_case(plan, row_run_id, identity, result)
        manifest_path = PROJECT_ROOT / captured["retained_validator_inputs_path"]
        manifest_raw = manifest_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(manifest_raw).hexdigest(),
            captured["retained_validator_inputs_sha256"],
        )
        manifest = json.loads(manifest_raw)
        entries = manifest["inputs"]
        self.assertTrue(
            {
                "runner_source",
                "call_source",
                "durable_release_record",
                "durable_release_boundary",
            }.issubset({entry["kind"] for entry in entries})
        )
        for entry in entries:
            copied = PROJECT_ROOT / entry["path"]
            raw = copied.read_bytes()
            self.assertEqual(len(raw), entry["size_bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])

        teardown = json.loads(
            (
                PROJECT_ROOT
                / result["evidence"]["teardown_evidence"]["path"]
            ).read_text(encoding="utf-8")
        )
        durable_path = PROJECT_ROOT / teardown["shared_lock"]["durable_record"]["path"]
        durable_path.write_bytes(b"external durable log changed after capture\n")

        with (
            mock.patch.object(
                retained,
                "_read_project_source_bytes",
                side_effect=AssertionError("offline validation read project source"),
            ),
            mock.patch.object(
                profile_runner,
                "_git_source_bytes_at_sha",
                side_effect=AssertionError("offline validation invoked git show"),
            ),
            mock.patch.object(
                profile_runner,
                "_git_common_directory",
                side_effect=AssertionError("offline validation read Git metadata"),
            ),
        ):
            revalidated = self._validate_retained_case(
                plan, row_run_id, identity, result
            )
        self.assertEqual(revalidated["outcome"], "completed")
        self.assertEqual(
            revalidated["retained_validator_inputs_sha256"],
            captured["retained_validator_inputs_sha256"],
        )

    def test_retained_validator_input_bundle_fails_closed_on_missing_or_tampered_copy(
        self,
    ) -> None:
        for mutation, expected_message in (
            ("missing", "retained validator input file is unavailable"),
            ("tampered", "retained validator input hash differs"),
        ):
            with self.subTest(mutation=mutation):
                plan, row_run_id, identity, result = self._retained_case()
                captured = self._validate_retained_case(
                    plan, row_run_id, identity, result
                )
                manifest = json.loads(
                    (
                        PROJECT_ROOT / captured["retained_validator_inputs_path"]
                    ).read_text(encoding="utf-8")
                )
                call_source = next(
                    entry
                    for entry in manifest["inputs"]
                    if entry["kind"] == "call_source"
                )
                copied_path = PROJECT_ROOT / call_source["path"]
                if mutation == "missing":
                    copied_path.unlink()
                else:
                    copied_path.write_bytes(b"tampered validator input")
                with self.assertRaisesRegex(
                    retained.RetainedEvidenceError, expected_message
                ):
                    self._validate_retained_case(
                        plan, row_run_id, identity, result
                    )

    def test_capture_rejects_durable_release_log_that_differs_from_sidecar(self) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        sidecar = json.loads(
            (
                PROJECT_ROOT
                / result["evidence"]["teardown_evidence"]["path"]
            ).read_text(encoding="utf-8")
        )
        reference = sidecar["shared_lock"]["durable_record"]
        log_path = PROJECT_ROOT / reference["path"]
        log_raw = log_path.read_bytes()
        start = reference["byte_offset"]
        end = start + reference["byte_length"]
        fabricated_line = b" " * (reference["byte_length"] - 1) + b"\n"
        log_path.write_bytes(log_raw[:start] + fabricated_line + log_raw[end:])

        with self.assertRaisesRegex(
            retained.RetainedEvidenceError,
            "durable shared lock release line hash differs",
        ):
            self._validate_retained_case(
                plan,
                row_run_id,
                identity,
                result,
                validation_snapshot=self._synthetic_validation_snapshot(SOURCE_SHA),
            )

    def test_checkpoint_result_reconciles_late_guarded_child_evidence(self) -> None:
        plan, row_run_id, identity, result = self._retained_case(
            late_guarded_child=True
        )
        checkpoint = self._add_synthetic_checkpoint(plan, row_run_id, result)

        summary = controller._validate_supervised_result(
            result,
            plan=plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            intended_identity=identity,
            source_sha=SOURCE_SHA,
            row_run_id=row_run_id,
            preflight_run_id=RUN_ID,
            create_resume_checkpoint=True,
            validation_snapshot=self._synthetic_validation_snapshot(SOURCE_SHA),
        )

        self.assertEqual(summary["outcome"], "completed")
        self.assertTrue(summary["process_census_complete"])
        self.assertEqual(summary["resume_checkpoint"], checkpoint)
        self.assertEqual(
            result["evidence"]["process_census"]["python_child_pids"], [104]
        )

    def test_sequential_lifecycles_capture_fresh_snapshot_before_supervision(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([str(row["row_id"]) for row in rows])
        plans = [
            _resolve_row_plan(
                row_id,
                prereg_root=None,
                expected_row=next(row for row in rows if row["row_id"] == row_id),
                profiles=profiles,
            )
            for row_id in ("E01", "E02")
        ]
        order: list[tuple[str, str]] = []
        snapshots = [object(), object()]
        snapshot_index = 0
        validation_index = 0
        active_row_id: str | None = None

        def prepare(*_args: Any) -> dict[str, Any]:
            nonlocal active_row_id
            active_row_id = _args[0].row_id
            order.append(("prepare", active_row_id))
            return {"sandbox_root": "tmp/combat_capture"}

        def capture(source_sha: str) -> object:
            nonlocal snapshot_index
            self.assertEqual(source_sha, SOURCE_SHA)
            if active_row_id is None:
                raise AssertionError("snapshot captured outside a lifecycle")
            order.append(("capture", active_row_id))
            snapshot = snapshots[snapshot_index]
            snapshot_index += 1
            return snapshot

        def supervise(*_args: Any) -> dict[str, Any]:
            order.append(("supervise", _args[0].row_id))
            return {}

        def validate_seed(*_args: Any, **_kwargs: Any) -> None:
            order.append(("validate_seed", _args[0].row_id))

        def validate_launcher_sandbox(*_args: Any, **_kwargs: Any) -> None:
            if active_row_id is None:
                raise AssertionError("sandbox validation occurred outside a lifecycle")
            order.append(("launcher_validate", active_row_id))

        def validate_sandbox(*_args: Any, **_kwargs: Any) -> None:
            order.append(("validate_sandbox", _args[0].row_id))

        def validate_result(_result: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
            nonlocal validation_index
            if active_row_id is None:
                raise AssertionError("validation occurred outside a lifecycle")
            order.append(("validate", active_row_id))
            self.assertIs(
                kwargs["validation_snapshot"], snapshots[validation_index]
            )
            validation_index += 1
            return {"outcome": "completed"}

        def cleanup(plan: controller.PreflightRowPlan, *_args: Any) -> bool:
            order.append(("cleanup", plan.row_id))
            return True

        interfaces = PreflightInterfaces(
            prepare_sandbox=prepare,
            supervise_row=supervise,
            cleanup_sandbox=cleanup,
            safety_counters=lambda: {},
            capture_retained_validation_snapshot=capture,
        )
        with (
            mock.patch.object(
                controller, "_validate_seed_result", side_effect=validate_seed
            ),
            mock.patch.object(
                launcher,
                "validate_sandbox",
                side_effect=validate_launcher_sandbox,
            ),
            mock.patch.object(
                controller, "_validate_sandbox_result", side_effect=validate_sandbox
            ),
            mock.patch.object(
                controller, "_validate_supervised_result", side_effect=validate_result
            ),
        ):
            for plan in plans:
                row_run_id = self._lifecycle_row_run_id(
                    plan, plan.fixture_id, "startup"
                )
                identity = planned_worker_identity(
                    plan,
                    fixture_id=plan.fixture_id,
                    lifecycle="startup",
                    source_sha=SOURCE_SHA,
                    row_run_id=row_run_id,
                    preflight_run_id=RUN_ID,
                )
                invocation = controller.PreflightLifecycleInvocation(
                    fixture_id=plan.fixture_id,
                    lifecycle="startup",
                    row_run_id=row_run_id,
                    intended_identity=identity,
                )
                result = controller._run_lifecycle_invocation(
                    plan,
                    invocation,
                    source_sha=SOURCE_SHA,
                    preflight_run_id=RUN_ID,
                    interfaces=interfaces,
                )
                self.assertEqual(result, {"outcome": "completed"})

        self.assertEqual(snapshot_index, len(snapshots))
        self.assertEqual(validation_index, len(snapshots))
        self.assertIsNot(snapshots[0], snapshots[1])
        self.assertEqual(
            order,
            [
                (operation, plan.row_id)
                for plan in plans
                for operation in (
                    "prepare",
                    "validate_seed",
                    "launcher_validate",
                    "validate_sandbox",
                    "capture",
                    "supervise",
                    "validate",
                    "cleanup",
                )
            ],
        )

    def test_retained_validation_snapshot_preserves_complete_journal(self) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        snapshot = self._synthetic_validation_snapshot()
        journal_path = PROJECT_ROOT / result["evidence"]["guard_event_journal"]["path"]
        journal_before = journal_path.read_bytes()

        with (
            mock.patch.object(
                profile_runner,
                "_git_source_bytes_at_sha",
                side_effect=AssertionError("late Git source lookup"),
            ),
            mock.patch.object(
                profile_runner,
                "_git_common_directory",
                side_effect=AssertionError("late Git common-directory lookup"),
            ),
        ):
            summary = self._validate_retained_case(
                plan,
                row_run_id,
                identity,
                result,
                validation_snapshot=snapshot,
            )

        journal_after = journal_path.read_bytes()
        events = [json.loads(line) for line in journal_after.splitlines()]
        self.assertEqual(summary["outcome"], "completed")
        self.assertEqual(journal_after, journal_before)
        self.assertEqual(
            len(events), result["evidence"]["guard_event_journal"]["event_count"]
        )
        self.assertTrue(
            all(event.get("run_id") == row_run_id for event in events)
        )

    def test_late_parent_subprocess_events_are_preserved_and_rejected(self) -> None:
        plan, row_run_id, identity, result = self._retained_case()
        journal_descriptor = result["evidence"]["guard_event_journal"]
        journal_path = PROJECT_ROOT / journal_descriptor["path"]
        self._validate_retained_case(plan, row_run_id, identity, result)
        original_journal = journal_path.read_bytes()
        original_read_bytes = retained._read_bytes
        journal_mutated = False

        def append_late_subprocess_events() -> None:
            events = [json.loads(line) for line in journal_path.read_bytes().splitlines()]
            parent_attempt = next(
                event
                for event in events
                if event.get("pid") == 101
                and event.get("process_role") == "parent"
                and event.get("event_type") == "subprocess_attempt"
            )
            sequence = max(
                event["sequence"] for event in events if event.get("pid") == 101
            )
            observed_at_ns = max(
                event["observed_at_ns"]
                for event in events
                if event.get("pid") == 101
            )
            command_sha256 = "f" * 64
            late_attempt = dict(parent_attempt)
            late_attempt.update(
                {
                    "sequence": sequence + 1,
                    "observed_at_ns": observed_at_ns + 1,
                    "decision": "allowed",
                    "command_sha256": command_sha256,
                }
            )
            late_started = dict(late_attempt)
            late_started.update(
                {
                    "sequence": sequence + 2,
                    "observed_at_ns": observed_at_ns + 2,
                    "event_type": "subprocess_started",
                    "decision": "started",
                    "child_pid": 105,
                    "child_is_python": False,
                }
            )
            appended = b"".join(
                json.dumps(
                    event,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
                + b"\n"
                for event in (late_attempt, late_started)
            )
            with journal_path.open("ab") as journal_file:
                journal_file.write(appended)

        with (
            mock.patch.object(
                retained,
                "_read_project_source_bytes",
                side_effect=AssertionError("offline validation read project source"),
            ),
            mock.patch.object(
                profile_runner,
                "_git_common_directory",
                side_effect=AssertionError("offline validation read Git metadata"),
            ) as git_common_directory,
            mock.patch.object(
                profile_runner,
                "_git_source_bytes_at_sha",
                side_effect=AssertionError("offline validation invoked git show"),
            ) as git_source_bytes,
            mock.patch.object(retained, "_read_bytes") as read_bytes,
        ):
            def read_with_late_event(path: str, label: str) -> bytes:
                nonlocal journal_mutated
                raw = original_read_bytes(path, label)
                if label == "worker result" and not journal_mutated:
                    journal_mutated = True
                    append_late_subprocess_events()
                return raw

            read_bytes.side_effect = read_with_late_event
            with self.assertRaisesRegex(
                retained.RetainedEvidenceError,
                "guard-event journal changed during reconciliation",
            ):
                self._validate_retained_case(plan, row_run_id, identity, result)

        self.assertEqual(git_common_directory.call_count, 0)
        self.assertEqual(git_source_bytes.call_count, 0)
        self.assertTrue(journal_mutated)
        changed_journal = journal_path.read_bytes()
        self.assertTrue(changed_journal.startswith(original_journal))
        self.assertEqual(len(changed_journal.splitlines()), len(original_journal.splitlines()) + 2)

    def test_retained_worker_checkpoint_travel_is_required_and_exact(self) -> None:
        cases = (
            ("ordinary-worker-extra", False, "extra"),
            ("checkpoint-worker-missing", True, "missing"),
            ("checkpoint-worker-differs", True, "differs"),
        )
        for name, checkpoint_run, mutation in cases:
            with self.subTest(name=name):
                plan, row_run_id, identity, result = self._retained_case()
                if checkpoint_run:
                    travel = self._add_synthetic_checkpoint(
                        plan, row_run_id, result
                    )
                else:
                    travel = {"complete": True}

                worker_path = (
                    PROJECT_ROOT / result["evidence_path"]
                ).with_name("worker-result.json")
                worker_result = json.loads(
                    worker_path.read_text(encoding="utf-8")
                )
                if mutation == "extra":
                    worker_result["checkpoint_travel"] = travel
                elif mutation == "missing":
                    worker_result.pop("checkpoint_travel")
                else:
                    worker_result["checkpoint_travel"]["complete"] = False
                self._rewrite_worker_result(result, worker_result)

                with self.assertRaisesRegex(
                    retained.RetainedEvidenceError,
                    "retained worker result is incomplete or contradictory",
                ):
                    self._validate_retained_case(
                        plan, row_run_id, identity, result
                    )

    def test_comparison_identity_is_reconciled_from_retained_worker_and_teardown(self) -> None:
        from scripts.live_gate_preflight_comparison_identity import (
            APPLICATION_B_SHA,
            APPLICATION_B_TREE,
            build_comparison_identity,
        )

        identity = build_comparison_identity(
            tool_sha="a" * 40,
            tool_tree="b" * 40,
            application_sha=APPLICATION_B_SHA,
            application_tree=APPLICATION_B_TREE,
        )
        plan, row_run_id, intended, result = self._retained_case(
            source_sha=APPLICATION_B_SHA,
            comparison_identity=identity,
        )
        summary = self._validate_retained_case(
            plan,
            row_run_id,
            intended,
            result,
            comparison_identity=identity,
        )
        self.assertEqual(summary["comparison_identity"], identity)

        sidecar_path = PROJECT_ROOT / result["evidence"]["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["comparison_identity"]["tool"]["sha"] = "c" * 40
        self._rewrite_teardown_sidecar(result, sidecar)
        with self.assertRaises(retained.RetainedEvidenceError):
            self._validate_retained_case(
                plan,
                row_run_id,
                intended,
                result,
                comparison_identity=identity,
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
            self._validate_retained_case(
                plan,
                row_run_id,
                identity,
                result,
                validation_snapshot=self._synthetic_validation_snapshot(),
            )

        plan, row_run_id, identity, result = self._retained_case()
        guard_path = PROJECT_ROOT / result["evidence"]["guard_event_journal"]["path"]
        guard_path.unlink()
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "guard-event journal file is unavailable"
        ):
            self._validate_retained_case(
                plan,
                row_run_id,
                identity,
                result,
                validation_snapshot=self._synthetic_validation_snapshot(),
            )

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
            self._validate_retained_case(
                plan,
                row_run_id,
                identity,
                result,
                validation_snapshot=self._synthetic_validation_snapshot(),
            )

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

    def test_retained_v2_wait_proof_is_strict_and_legacy_v1_still_validates(
        self,
    ) -> None:
        plan, row_run_id, identity, result = self._retained_case(
            teardown_schema_version=2
        )
        sidecar_path = PROJECT_ROOT / result["evidence"]["teardown_evidence"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        wait = sidecar["teardown_wait"]
        summary = self._validate_retained_case(plan, row_run_id, identity, result)
        self.assertTrue(
            summary["worker_teardown"]["shared_live_window_lock_released"]
        )

        invalid_waits: list[tuple[str, dict[str, Any]]] = []
        missing_observation = json.loads(json.dumps(wait))
        del missing_observation["final"]["port_observations"]["8370"]
        invalid_waits.append(("missing_observation", missing_observation))

        malformed_census = json.loads(json.dumps(wait))
        malformed_census["final"]["listener_census"]["8360"][
            "identity_sha256"
        ] = "0" * 64
        invalid_waits.append(("malformed_census", malformed_census))

        unsupported_wait_version = json.loads(json.dumps(wait))
        unsupported_wait_version["schema_version"] = 2
        invalid_waits.append(("unsupported_wait_version", unsupported_wait_version))

        timeout = json.loads(json.dumps(wait))
        timeout["status"] = "failed"
        timeout["failure_code"] = "teardown_port_wait_timeout"
        timeout["elapsed_monotonic_ns"] = 75_000_000_000
        invalid_waits.append(("timeout", timeout))

        unclean_census = json.loads(json.dumps(wait))
        unclean_census["final_process_census"]["listener_pids"] = [12345]
        invalid_waits.append(("unclean_final_census", unclean_census))

        predating_census = json.loads(json.dumps(wait))
        predating_census["final_process_census"]["observed_monotonic_ns"] = 0
        invalid_waits.append(("predating_final_census", predating_census))

        polled_too_soon = json.loads(json.dumps(wait))
        first_attempt = polled_too_soon["attempts"][0]
        first_attempt["port_observations"]["8360"] = (
            self._synthetic_free_bind_observation(8360)
        )
        first_attempt["port_observations"]["8360"].update(
            {
                "bind_succeeded": False,
                "error_errno": errno.EADDRINUSE,
                "error_type": "OSError",
                "result": "occupied",
            }
        )
        second_attempt = json.loads(json.dumps(wait["attempts"][0]))
        second_attempt["started_monotonic_ns"] = 500_000_000
        second_attempt["completed_monotonic_ns"] = 500_000_001
        polled_too_soon["attempts"].append(second_attempt)
        polled_too_soon["final"] = second_attempt
        polled_too_soon["completed_monotonic_ns"] = 500_000_001
        polled_too_soon["elapsed_monotonic_ns"] = 500_000_001
        polled_too_soon["final_process_census"]["observed_monotonic_ns"] = (
            500_000_002
        )
        invalid_waits.append(("poll_interval", polled_too_soon))

        for label, invalid_wait in invalid_waits:
            with self.subTest(label=label), self.assertRaises(
                retained.RetainedEvidenceError
            ):
                retained._validate_teardown_wait_evidence(
                    invalid_wait,
                    sidecar=sidecar,
                    evidence=result["evidence"],
                    runner=profile_runner,
                )

        v2_without_wait = json.loads(json.dumps(sidecar))
        del v2_without_wait["teardown_wait"]
        self._rewrite_teardown_sidecar(result, v2_without_wait)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "teardown evidence identity differs"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        downgraded_v2 = json.loads(json.dumps(sidecar))
        downgraded_v2["schema_version"] = 1
        self._rewrite_teardown_sidecar(result, downgraded_v2)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "teardown evidence identity differs"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        downgraded_v2_without_proof = json.loads(json.dumps(sidecar))
        downgraded_v2_without_proof["schema_version"] = 1
        del downgraded_v2_without_proof["teardown_wait"]
        self._rewrite_teardown_sidecar(result, downgraded_v2_without_proof)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError,
            "retained shared lock release record identity differs",
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        tampered_sidecar = json.loads(json.dumps(sidecar))
        tampered_wait = tampered_sidecar["teardown_wait"]
        tampered_attempt = tampered_wait["attempts"][0]
        tampered_census = tampered_attempt["listener_census"]["8360"]
        tampered_census["stdout_sha256"] = "0" * 64
        census_identity = {
            "observer": "lsof",
            "census_method": "tcp-listen",
            "port": 8360,
            "command": [
                profile_runner.LSOF_EXECUTABLE,
                "-nP",
                "-iTCP:8360",
                "-sTCP:LISTEN",
            ],
            "returncode": tampered_census["returncode"],
            "stdout_byte_count": tampered_census["stdout_byte_count"],
            "stdout_sha256": tampered_census["stdout_sha256"],
        }
        tampered_census["identity_sha256"] = profile_runner._canonical_json_sha256(
            census_identity
        )
        tampered_wait["initial"] = json.loads(json.dumps(tampered_attempt))
        tampered_wait["final"] = json.loads(json.dumps(tampered_attempt))
        self._rewrite_teardown_sidecar(result, tampered_sidecar)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError,
            "retained shared lock release record identity differs",
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        plan, row_run_id, identity, result = self._retained_case()
        legacy = json.loads(
            (
                PROJECT_ROOT / result["evidence"]["teardown_evidence"]["path"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(legacy["schema_version"], 1)
        self.assertTrue(
            self._validate_retained_case(plan, row_run_id, identity, result)[
                "worker_teardown"
            ]["shared_live_window_lock_released"]
        )

        legacy_with_wait = json.loads(json.dumps(legacy))
        legacy_with_wait["teardown_wait"] = wait
        self._rewrite_teardown_sidecar(result, legacy_with_wait)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "teardown evidence identity differs"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        legacy_noninteger_version = json.loads(json.dumps(legacy))
        legacy_noninteger_version["schema_version"] = True
        self._rewrite_teardown_sidecar(result, legacy_noninteger_version)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "teardown evidence identity differs"
        ):
            self._validate_retained_case(plan, row_run_id, identity, result)

        legacy["schema_version"] = 3
        self._rewrite_teardown_sidecar(result, legacy)
        with self.assertRaisesRegex(
            retained.RetainedEvidenceError, "teardown evidence identity differs"
        ):
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

    def test_stale_id_map_file_literal_blocks_location_mapping_unresolved(self) -> None:
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
        canonical_id_map_file = "modules/%s/location_id_map.json" % (
            launcher.MAPPING_PILOT_MODULE
        )
        stale_id_map_file = "modules/mapping_pilot/location_id_map.json"

        with tempfile.TemporaryDirectory(
            prefix="live-gate-preflight-stale-id-map-", dir=PROJECT_ROOT / "tmp"
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

            def stale_id_map(*args: Any, **kwargs: Any) -> launcher.ValidatedSandbox:
                validated = validate_sandbox(*args, **kwargs)
                metadata = dict(validated.metadata)
                metadata["mapping"] = {
                    **validated.metadata["mapping"],
                    "id_map_file": stale_id_map_file,
                }
                return launcher.ValidatedSandbox(
                    root=validated.root,
                    metadata=metadata,
                    fixture_payloads=validated.fixture_payloads,
                    runtime_to_source=validated.runtime_to_source,
                )

            with mock.patch.object(
                launcher, "validate_sandbox", side_effect=stale_id_map
            ):
                report = run_preflight_rows(
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    intended_worker_identities=identities,
                    interfaces=interfaces,
                )

        self.assertNotEqual(canonical_id_map_file, stale_id_map_file)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(
            report["row_results"][0]["failure_code"], "location_mapping_unresolved"
        )
        self.assertEqual(
            report["row_results"][0]["unresolved_reference"], canonical_id_map_file
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
        profile["startup"] = _measured_declaration([call_site])
        profile["resume"] = _measured_declaration([call_site])
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
        profile["startup"] = _measured_declaration([expected_site])
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(profile_map, coverage)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["attempted_row_ids"], ["E01"])
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "startup_profile_call_sites_mismatch",
        )
        check = report["row_results"][0]["startup_profile_check"]
        self.assertEqual(check["outcome"], "profile_mismatch")
        self.assertEqual(check["mismatch_kinds"], ["call_sites_mismatch", "total_mismatch"])
        self.assertEqual(check["differences"]["total"], {"expected": 2, "observed": 1})
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
        profile["startup"] = _measured_declaration([expected_site])
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
        self.assertEqual(resume_check["profile_status"], "measured-under-stub")
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

    def test_stale_call_site_file_hash_blocks_as_profile_mismatch(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        stale_site = _synthetic_call_site()
        stale_site["source_file_sha256"] = "f" * 64
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = _measured_declaration([stale_site])
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, observed = self._run_with_profiles(profile_map, coverage)

        first_result = report["row_results"][0]
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            first_result["failure_code"], "startup_profile_file_hash_mismatch"
        )
        check = first_result["lifecycle_profile_checks"]["interior_tavern"]["startup"]
        self.assertEqual(check["outcome"], "profile_mismatch")
        self.assertEqual(
            check["differences"]["file_hashes"][0]["expected"], "f" * 64
        )
        self.assertFalse(first_result["booking_eligible"])
        self.assertEqual(observed["cleaned"], ["E01"])

    def test_stale_stub_hash_blocks_as_profile_mismatch(self) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        profile_map, coverage = _load_profiles([row["row_id"] for row in rows])
        first = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=rows[0],
            profiles=profile_map,
        )
        declaration = _measured_declaration([_synthetic_call_site()])
        declaration["stub_sha256"]["sha256"] = "0" * 64
        profile = dict(profile_map[(first.fixture_id, first.party_size)])
        profile["startup"] = declaration
        profile_map[(first.fixture_id, first.party_size)] = profile

        report, _observed = self._run_with_profiles(profile_map, coverage)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["row_results"][0]["failure_code"],
            "startup_profile_stub_hash_mismatch",
        )

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
            profile["resume"] = self._measured_lifecycle(
                call_site, required=False
            )
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
                    self._start_fresh_preflight_run()
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
                self._start_fresh_preflight_run()
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

    def test_supervised_adapter_accepts_frozen_combat_rows_before_characterize(
        self,
    ) -> None:
        args_seen: list[Any] = []
        evidence = {"outcome": "completed"}
        accepted_rows = (
            ("C01", "combat_stage_tavern_zones", 1, "A"),
            ("C05", "combat_stage_tavern_zones", 4, "D"),
        )

        def characterize(args: Any) -> tuple[dict[str, Any], str, str]:
            args_seen.append(args)
            return evidence, "tmp/evidence", "d" * 64

        with mock.patch.object(
            profile_runner, "_characterize", side_effect=characterize
        ) as characterize_mock:
            results = [
                profile_runner.supervise_preflight_row(
                    fixture_id=fixture_id,
                    party_size=party_size,
                    planned_row_id=row_id,
                    arm=arm,
                    source_sha=SOURCE_SHA,
                    row_run_id="pf-row-integration-test-" + row_id,
                    preflight_run_id=RUN_ID,
                )
                for row_id, fixture_id, party_size, arm in accepted_rows
            ]

        self.assertEqual([result["evidence"] for result in results], [evidence] * 2)
        self.assertEqual(
            [args.planned_row_id for args in args_seen], ["C01", "C05"]
        )
        self.assertEqual(characterize_mock.call_count, 2)

    def test_supervised_adapter_rejects_nonplanned_and_mismatched_rows_prelaunch(
        self,
    ) -> None:
        invalid_rows = (
            ("R01", "combat_stage_tavern_zones", 1, "A"),
            ("C0x", "combat_stage_tavern_zones", 1, "A"),
            ("C99", "combat_stage_tavern_zones", 1, "A"),
            ("C01", "interior_tavern", 1, "A"),
            ("C01", "combat_stage_tavern_zones", 4, "A"),
            ("C05", "combat_stage_tavern_zones", 4, "A"),
        )
        with mock.patch.object(profile_runner, "_characterize") as characterize:
            for row_id, fixture_id, party_size, arm in invalid_rows:
                with self.subTest(row_id=row_id, fixture_id=fixture_id):
                    with self.assertRaisesRegex(
                        profile_runner.CharacterizationError,
                        "row_preflight_identity_invalid",
                    ):
                        profile_runner.supervise_preflight_row(
                            fixture_id=fixture_id,
                            party_size=party_size,
                            planned_row_id=row_id,
                            arm=arm,
                            source_sha=SOURCE_SHA,
                            row_run_id="pf-row-integration-test-invalid",
                            preflight_run_id=RUN_ID,
                        )
            characterize.assert_not_called()

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

    def test_supervised_interfaces_forward_comparison_identity_to_row_supervisor(
        self,
    ) -> None:
        from scripts.live_gate_preflight_comparison_identity import (
            APPLICATION_B_SHA,
            APPLICATION_B_TREE,
            build_comparison_identity,
        )

        rows, _reserves = _load_frozen_row_ids(None)
        profiles, _coverage = _load_profiles([row["row_id"] for row in rows])
        plan = _resolve_row_plan(
            "E01", prereg_root=None, expected_row=rows[0], profiles=profiles
        )
        identity = build_comparison_identity(
            tool_sha="a" * 40,
            tool_tree="b" * 40,
            application_sha=APPLICATION_B_SHA,
            application_tree=APPLICATION_B_TREE,
        )
        row_run_id = "pf-%s-%s" % (RUN_ID, plan.row_id)
        intended = controller.planned_worker_identity(
            plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            source_sha=APPLICATION_B_SHA,
            row_run_id=row_run_id,
            preflight_run_id=RUN_ID,
            comparison_identity=identity,
        )
        invocation = controller.PreflightLifecycleInvocation(
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            row_run_id=row_run_id,
            intended_identity=intended,
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
            comparison_identity=identity,
        )
        seeded = {"status": "prepared", "fixture_id": plan.fixture_id}
        supervised = {"evidence": {"outcome": "completed"}}
        with mock.patch.object(
            profile_runner, "supervise_preflight_row", return_value=supervised
        ) as supervise:
            self.assertIs(
                interfaces.supervise_row(
                    plan, seeded, invocation, APPLICATION_B_SHA, RUN_ID
                ),
                supervised,
            )

        self.assertEqual(supervise.call_args.kwargs["source_sha"], APPLICATION_B_SHA)
        self.assertEqual(supervise.call_args.kwargs["comparison_identity"], identity)

    def test_supervised_interfaces_pass_none_comparison_identity_in_same_sha_mode(
        self,
    ) -> None:
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
        with mock.patch.object(
            profile_runner, "supervise_preflight_row", return_value=supervised
        ) as supervise:
            interfaces.supervise_row(plan, seeded, invocation, SOURCE_SHA, RUN_ID)

        self.assertIsNone(supervise.call_args.kwargs["comparison_identity"])

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


class TestPreflightCheckedInDeclarations(unittest.TestCase):
    """The controller loader against the real checked-in measured declarations."""

    def test_controller_loads_measured_startup_resume_and_missing_combat_resume(
        self,
    ) -> None:
        rows, _reserves = _load_frozen_row_ids(None)
        row_ids = [row["row_id"] for row in rows]
        profiles, coverage = _load_profiles(row_ids)
        self.assertEqual(len(profiles), 8)
        self.assertEqual(
            sorted(
                key for key, value in profiles.items()
                if value["startup"]["status"] == "measured-under-stub"
            ),
            sorted(profiles),
        )
        resume_measured = [
            key for key, value in profiles.items()
            if value["resume"]["status"] == "measured-under-stub"
        ]
        self.assertEqual(len(resume_measured), 6)
        for (fixture_id, party_size), value in profiles.items():
            if fixture_id == "combat_stage_tavern_zones":
                self.assertIn(party_size, (1, 4))
                self.assertEqual(value["resume"]["status"], "MISSING")
                self.assertIn("NOT APPLICABLE", value["resume"]["reason"])
        self.assertEqual(coverage["unverified_row_ids"], [])
        self.assertTrue(coverage["measured_lifecycle_complete"])
        self.assertFalse(coverage["booking_eligible"])


class TestSupervisedEvidenceIntegration(unittest.TestCase):
    def test_retained_reconciliation_failure_code_sanitizes_reason(self) -> None:
        plan = SimpleNamespace(fixture_id="fixture")
        cases = (
            ("summary child module identity differs",
             "retained_supervised_evidence_reconciliation_failed:summary_child_module_identity_differs"),
            ("/Users/x/tmp/file.json is bad",
             "retained_supervised_evidence_reconciliation_failed:users_x_tmp_file_json_is_bad"),
            ("", "retained_supervised_evidence_reconciliation_failed"),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                with mock.patch.object(
                    retained,
                    "validate_retained_supervised_evidence",
                    side_effect=retained.RetainedEvidenceError(message),
                ):
                    with self.assertRaises(controller.PreflightControllerError) as caught:
                        controller._validate_supervised_result(
                            {"evidence": {}, "evidence_path": "x", "evidence_sha256": "y"},
                            plan=plan,
                            fixture_id="fixture",
                            lifecycle="startup",
                            intended_identity={},
                            source_sha=SOURCE_SHA,
                            row_run_id="row",
                            preflight_run_id=RUN_ID,
                        )
                self.assertEqual(str(caught.exception), expected)

    def setUp(self) -> None:
        if (
            self._testMethodName
            == "test_supervised_entrypoint_persists_worker_identity_mismatch_without_host_start"
        ):
            _require_repository_python(self)
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


class TestRequiredLifecycleCheckpointPolicy(unittest.TestCase):
    """Exercise required/extra lifecycle decisions without starting a host."""

    def setUp(self) -> None:
        _require_repository_python(self)
        self.run_id = "checkpoint-policy-" + uuid.uuid4().hex[:10]
        self.rows, _reserves = _load_frozen_row_ids(None)
        loaded_profiles, self.coverage = _load_profiles(
            [str(row["row_id"]) for row in self.rows]
        )
        # These policy tests exercise controller sequencing, not whether the
        # checked-in measurement still matches edited tooling. Give the in-memory
        # fixture explicit synthetic tool identities; the dedicated hash-currency
        # test continues to check the checked-in declarations against disk.
        tool_paths = (
            preflight_profiles.STUB_FILE,
            *preflight_profiles.DRIVER_FILES,
        )
        self.simulated_tool_hashes = {
            path: hashlib.sha256(
                ("checkpoint-policy-test-tool:" + path).encode("ascii")
            ).hexdigest()
            for path in tool_paths
        }
        self.profiles = copy.deepcopy(loaded_profiles)
        for profile in self.profiles.values():
            for lifecycle in ("startup", "resume"):
                declaration = profile.get(lifecycle)
                if (
                    not isinstance(declaration, dict)
                    or declaration.get("status") != "measured-under-stub"
                ):
                    continue
                stub = declaration["stub_sha256"]
                stub["sha256"] = self.simulated_tool_hashes[stub["path"]]
                for driver in declaration["driver_sha256"]:
                    driver["sha256"] = self.simulated_tool_hashes[driver["path"]]

    @staticmethod
    def _checkpoint(plan: controller.PreflightRowPlan, fixture_id: str, sha: str) -> dict[str, Any]:
        return {
            "checkpoint_root": (
                "tmp/router-rollout/live-gate-preflight-checkpoints/"
                "provided/%s/%s-p%d" % (plan.row_id, fixture_id, plan.party_size)
            ),
            "state_sha256": sha,
            "row_id": plan.row_id,
            "fixture_id": fixture_id,
            "party_size": plan.party_size,
            "arm": plan.arm,
            "fixed_seed": plan.fixed_seed,
        }

    def _run_row(
        self,
        *,
        row_id: str = "E01",
        source_sha: str = SOURCE_SHA,
        comparison_identity: dict[str, Any] | None = None,
        resume_checkpoints: dict[str, dict[str, dict[str, Any]]] | None = None,
        auto_create: bool = True,
        mismatch_optional_resume: bool = False,
    ) -> tuple[dict[str, Any], list[Any], list[tuple[Any, ...]]]:
        frozen_row = next(row for row in self.rows if row["row_id"] == row_id)
        plan = _resolve_row_plan(
            row_id,
            prereg_root=None,
            expected_row=frozen_row,
            profiles=self.profiles,
        )
        row_run_id = "pf-%s-%s" % (self.run_id, row_id)
        intended = planned_worker_identity(
            plan,
            fixture_id=plan.fixture_id,
            lifecycle="startup",
            source_sha=source_sha,
            row_run_id=row_run_id,
            preflight_run_id=self.run_id,
            comparison_identity=comparison_identity,
        )
        invocations: list[Any] = []
        resolver_calls: list[tuple[Any, ...]] = []

        def resolve_identity(
            selected_plan: controller.PreflightRowPlan,
            fixture_id: str,
            lifecycle: str,
            checkpoint_sha256: str | None,
            create_resume_checkpoint: bool,
        ) -> dict[str, Any]:
            resolver_calls.append(
                (
                    selected_plan.row_id,
                    fixture_id,
                    lifecycle,
                    checkpoint_sha256,
                    create_resume_checkpoint,
                )
            )
            fixture_index = selected_plan.fixture_ids.index(fixture_id)
            lifecycle_run_id = (
                controller._checkpoint_lifecycle_run_id(
                    self.run_id, selected_plan.row_id, fixture_index
                )
                if create_resume_checkpoint
                else controller._lifecycle_run_id(
                    self.run_id,
                    selected_plan.row_id,
                    fixture_index,
                    lifecycle,
                    primary=False,
                )
            )
            return planned_worker_identity(
                selected_plan,
                fixture_id=fixture_id,
                lifecycle=lifecycle,
                source_sha=source_sha,
                row_run_id=lifecycle_run_id,
                resume_checkpoint_sha256=checkpoint_sha256,
                preflight_run_id=self.run_id,
                create_resume_checkpoint=create_resume_checkpoint,
                comparison_identity=comparison_identity,
            )

        def lifecycle_result(
            selected_plan: controller.PreflightRowPlan,
            invocation: controller.PreflightLifecycleInvocation,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            invocations.append(invocation)
            profile = controller._fixture_lifecycle_profile(
                selected_plan, invocation.fixture_id
            )
            if invocation.create_resume_checkpoint:
                checkpoint = self._checkpoint(
                    selected_plan, invocation.fixture_id, "e" * 64
                )
                call_count = 7
                call_sites: list[dict[str, Any]] = []
            else:
                declaration = profile[invocation.lifecycle]
                call_count = declaration["call_count"]
                call_sites = [dict(site) for site in declaration["call_sites"]]
                if mismatch_optional_resume and invocation.lifecycle == "resume":
                    call_count += 1
                checkpoint = None
            return {
                "call_count": call_count,
                "call_sites": call_sites,
                "first_exchange": {"status": "completed"},
                "worker_teardown": {
                    "server_stopped": True,
                    "port_8360_free": True,
                    "port_8370_free": True,
                    "shared_live_window_lock_released": True,
                    "guard_active": True,
                    "call_count": call_count,
                },
                "retained_evidence_path": (
                    "tmp/router-rollout/live-gate-preflight/%s/preflight/rows/%s/"
                    "profile-evidence.json" % (self.run_id, invocation.row_run_id)
                ),
                "retained_evidence_sha256": "f" * 64,
                **({"resume_checkpoint": checkpoint} if checkpoint is not None else {}),
            }

        interfaces = PreflightInterfaces(
            prepare_sandbox=lambda *_args: {},
            supervise_row=lambda *_args: {},
            cleanup_sandbox=lambda *_args: True,
            safety_counters=lambda: {
                "upstream_provider_requests": 0,
                "provider_budget_used": 0,
                "live_attempts_used": 0,
                "reserve_activations": 0,
            },
        )
        with (
            mock.patch.object(
                preflight_profiles,
                "tool_file_hashes",
                return_value=self.simulated_tool_hashes,
            ),
            mock.patch.object(
                controller, "_load_frozen_row_ids", return_value=([frozen_row], [])
            ),
            mock.patch.object(
                controller,
                "_load_profiles",
                return_value=(self.profiles, self.coverage),
            ),
            mock.patch.object(
                controller,
                "_run_lifecycle_invocation",
                side_effect=lifecycle_result,
            ),
        ):
            report = run_preflight_rows(
                source_sha=source_sha,
                run_id=self.run_id,
                intended_worker_identities={row_id: intended},
                intended_identity_resolver=resolve_identity,
                interfaces=interfaces,
                resume_checkpoints=resume_checkpoints,
                comparison_identity=comparison_identity,
                auto_create_required_resume_checkpoints=auto_create,
            )
        return report, invocations, resolver_calls

    def test_same_sha_creates_checkpoint_before_required_resume_and_counts_calls(self) -> None:
        report, invocations, resolver_calls = self._run_row()
        row = report["row_results"][0]
        checkpoint_run = next(
            item for item in invocations if item.create_resume_checkpoint
        )
        resume_run = next(item for item in invocations if item.lifecycle == "resume")
        checkpoint_result = next(
            item for item in row["lifecycle_results"]
            if item["lifecycle"] == "checkpoint"
        )
        self.assertEqual(checkpoint_run.lifecycle, "startup")
        self.assertEqual(
            [item.lifecycle for item in invocations],
            ["startup", "startup", "resume"],
        )
        self.assertEqual(
            resolver_calls,
            [
                (
                    row["row_id"],
                    "interior_tavern",
                    "startup",
                    None,
                    True,
                ),
                (
                    row["row_id"],
                    "interior_tavern",
                    "resume",
                    "e" * 64,
                    False,
                ),
            ],
        )
        self.assertIn("e" * 64, resume_run.intended_identity["command"])
        self.assertEqual(checkpoint_result["profile_check"]["status"], "not_applicable")
        self.assertEqual(checkpoint_result["resume_checkpoint_sha256"], "e" * 64)
        self.assertEqual(
            report["provider_free"]["router_stub_calls"],
            sum(
                item["worker_teardown"]["call_count"]
                for item in row["lifecycle_results"]
            ),
        )
        self.assertEqual(row["status"], "completed")

    def test_explicit_checkpoint_precedes_automatic_creation(self) -> None:
        plan = _resolve_row_plan(
            "E01",
            prereg_root=None,
            expected_row=next(row for row in self.rows if row["row_id"] == "E01"),
            profiles=self.profiles,
        )
        checkpoint = self._checkpoint(plan, "interior_tavern", "d" * 64)
        report, invocations, resolver_calls = self._run_row(
            resume_checkpoints={"E01": {"interior_tavern": checkpoint}},
        )
        self.assertEqual([item.lifecycle for item in invocations], ["startup", "resume"])
        self.assertFalse(any(item.create_resume_checkpoint for item in invocations))
        self.assertIn(
            ("E01", "interior_tavern", "resume", "d" * 64, False),
            resolver_calls,
        )
        self.assertEqual(report["row_results"][0]["status"], "completed")

    def test_unrun_optional_resume_is_unverified_but_does_not_block_row(self) -> None:
        combat_row = next(
            row
            for row in self.rows
            if controller._resolve_row_plan(
                str(row["row_id"]),
                prereg_root=None,
                expected_row=row,
                profiles=self.profiles,
            ).fixture_id
            == "combat_stage_tavern_zones"
        )
        report, invocations, _resolver_calls = self._run_row(
            row_id=str(combat_row["row_id"])
        )
        row = report["row_results"][0]
        resume_check = row["lifecycle_profile_checks"][
            "combat_stage_tavern_zones"
        ]["resume"]
        self.assertEqual([item.lifecycle for item in invocations], ["startup"])
        self.assertEqual(resume_check["status"], "unverified")
        self.assertFalse(resume_check["required"])
        self.assertEqual(row["lifecycle_profile_status"], "matched")
        self.assertEqual(row["status"], "completed")

    def test_optional_resume_mismatch_still_mismatches_row(self) -> None:
        row = next(item for item in self.rows if item["row_id"] == "E04")
        plan = _resolve_row_plan(
            "E04", prereg_root=None, expected_row=row, profiles=self.profiles
        )
        optional_fixture = "landscape_village"
        checkpoint = self._checkpoint(plan, optional_fixture, "c" * 64)
        report, _invocations, _resolver_calls = self._run_row(
            row_id="E04",
            resume_checkpoints={"E04": {optional_fixture: checkpoint}},
            mismatch_optional_resume=True,
        )
        result = report["row_results"][0]
        check = result["lifecycle_profile_checks"][optional_fixture]["resume"]
        self.assertFalse(check["required"])
        self.assertEqual(check["status"], "mismatched")
        self.assertEqual(result["lifecycle_profile_status"], "mismatched")
        self.assertEqual(result["status"], "blocked")

    def test_comparison_does_not_resume_and_refuses_checkpoint_inputs(self) -> None:
        from scripts.live_gate_preflight_comparison_identity import (
            APPLICATION_A_SHA,
            APPLICATION_A_TREE,
            build_comparison_identity,
        )

        identity = build_comparison_identity(
            tool_sha="a" * 40,
            tool_tree="b" * 40,
            application_sha=APPLICATION_A_SHA,
            application_tree=APPLICATION_A_TREE,
        )
        report, invocations, _resolver_calls = self._run_row(
            source_sha=APPLICATION_A_SHA,
            comparison_identity=identity,
            auto_create=False,
        )
        self.assertEqual([item.lifecycle for item in invocations], ["startup"])
        resume_check = report["row_results"][0]["lifecycle_profile_checks"][
            "interior_tavern"
        ]["resume"]
        self.assertTrue(resume_check["required"])
        self.assertEqual(resume_check["status"], "unverified")

        with self.assertRaisesRegex(
            controller.PreflightControllerError,
            "auto_resume_checkpoint_refused_in_comparison",
        ):
            self._run_row(
                source_sha=APPLICATION_A_SHA,
                comparison_identity=identity,
                auto_create=True,
            )
        with self.assertRaisesRegex(
            controller.PreflightControllerError,
            "resume_checkpoints_refused_in_comparison",
        ):
            self._run_row(
                source_sha=APPLICATION_A_SHA,
                comparison_identity=identity,
                resume_checkpoints={},
                auto_create=False,
            )


if __name__ == "__main__":
    unittest.main()
