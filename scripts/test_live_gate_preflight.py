# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic invocation-boundary and provider-free router tests."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.live_gate_preflight_stub as router_stub_module
from scripts import live_gate_preflight_controller as preflight_controller
from scripts import live_gate_preflight_evidence as preflight_evidence
from scripts import live_gate_preflight_sandbox as sandbox_preparation
from scripts import live_gate_preflight_profile_runner as profile_runner
import scripts.live_gate_preflight_safety as preflight_safety
from scripts.mapping_pilot import execution as sp3_execution
from scripts.mapping_pilot import row_runner as sp3_row_runner
from scripts.mapping_pilot import scoring as sp3_scoring
from scripts.live_gate_preflight_safety import (
    NetworkGuardError,
    compare_invocation_identity,
    expected_guarded_pythonpath,
)
from scripts.live_gate_preflight_stub import (
    FailClosedRouterStub,
    RouterStubError,
    install_fail_closed_router_stub,
)


def _identity() -> dict[str, Any]:
    return {
        "command": [
            sys.executable,
            "-m",
            "scripts.mapping_pilot.worker",
            "--token=synthetic-secret-command-value",
        ],
        "working_directory": "/workspace/tmp/capture-secret-directory",
        "pythonpath": os.pathsep.join(
            (
                "/workspace/scripts/guard-secret-entry",
                "/workspace/repository-secret-root",
            )
        ),
    }


class TestRealSandboxPreparationBoundary(unittest.TestCase):
    @staticmethod
    def _seed_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        from scripts.mapping_pilot.fixtures import FIXTURE_FILES

        expected = {
            fixture_id: {
                "fixture_id": fixture_id,
                "source_file": source_file,
                "source_truth": {"fixture_id": fixture_id, "location_ids": ["SRC01"]},
            }
            for fixture_id, source_file in FIXTURE_FILES.items()
        }
        module_payloads = {
            "areas/MPA001.json": {
                "areaId": "MPA001",
                "areaName": "Synthetic Test Area",
                "locations": [{"locationId": "MP01", "name": "Synthetic Test Room"}],
            },
            "map_MPA001.json": {
                "rooms": [{"id": "MP01"}],
                "startRoom": "wrong-room",
            },
            "location_id_map.json": {"runtime_location_ids": {"SRC01": "MP01"}},
        }
        plan = {
            "fixture_id": "interior_tavern",
            "arm": "A",
            "party_size": 1,
            "effective_seed": 42,
            "fixture": {},
            "source_location_id": "SRC01",
            "runtime_location_id": "MP01",
            "counterbalance": {
                "row_id": "E01",
                "row_type": "planned",
                "block": 1,
                "script": "scripts/interior.json",
                "fixed_seed": 42,
            },
        }
        return plan, module_payloads, expected

    @staticmethod
    def _worker_identity(project_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
        run_id = "pf-seed-boundary-01"
        with mock.patch.object(
            profile_runner, "_repository_python", return_value=sys.executable
        ):
            command = profile_runner._host_command(
                fixture_id=str(plan["fixture_id"]),
                party_size=int(plan["party_size"]),
                lifecycle="startup",
                source_sha="a" * 40,
                run_id=run_id,
                planned_row_id=str(plan["counterbalance"]["row_id"]),
                arm=str(plan["arm"]),
                lifecycle_id=run_id + "_s",
                resume_checkpoint_sha256=None,
            )
        return {
            "command": command,
            "working_directory": str(project_root / "tmp" / "combat_capture"),
            "pythonpath": expected_guarded_pythonpath(project_root),
        }

    @staticmethod
    def _entrypoint_args(intended: dict[str, Any]) -> list[str]:
        return [
            "--prepare",
            "--fixture-id",
            "interior_tavern",
            "--party-size",
            "1",
            "--planned-row-id",
            "E01",
            "--lifecycle",
            "startup",
            "--source-sha",
            "a" * 40,
            "--run-id",
            "pf-seed-boundary-01",
            "--intended-host-identity-json",
            json.dumps(intended, ensure_ascii=True, sort_keys=True),
        ]

    def test_each_identity_mismatch_blocks_actual_seed_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="preflight-seed-mismatch-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            project = Path(temporary_root)
            (project / "tmp").mkdir()
            plan, module_payloads, expected_payloads = self._seed_inputs()
            planned = self._worker_identity(project, plan)
            mismatched_values = {
                "command": [*planned["command"], "--row=E02"],
                "working_directory": str(project / "other" / "capture-secret-directory"),
                "pythonpath": planned["pythonpath"] + os.pathsep + "/other/guard",
            }
            for field, changed_value in mismatched_values.items():
                with self.subTest(field=field):
                    intended = copy.deepcopy(planned)
                    intended[field] = changed_value
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(sandbox_preparation, "PROJECT_ROOT", project),
                        mock.patch.object(
                            sandbox_preparation, "_require_preparation_startup_guard"
                        ),
                        mock.patch.object(
                            sandbox_preparation,
                            "_load_profile_seed_plan",
                            return_value=(plan, {"profile_id": "interior_tavern:p1"}),
                        ),
                        mock.patch.object(
                            sandbox_preparation,
                            "_load_profile_seed_inputs",
                            return_value=(module_payloads, expected_payloads),
                        ),
                        mock.patch.object(
                            profile_runner, "_repository_python", return_value=sys.executable
                        ),
                        mock.patch.object(
                            sandbox_preparation, "_prepare_new_sandbox"
                        ) as seed,
                        redirect_stderr(stderr),
                        redirect_stdout(io.StringIO()),
                    ):
                        exit_code = sandbox_preparation.main(
                            self._entrypoint_args(intended)
                        )

                    self.assertEqual(exit_code, 1)
                    seed.assert_not_called()
                    self.assertFalse((project / "tmp" / "combat_capture").exists())
                    diagnostic = stderr.getvalue()
                    self.assertTrue(diagnostic.startswith("[FAIL] profile_sandbox="))
                    self.assertNotIn("capture-secret-directory", diagnostic)
                    failure = json.loads(diagnostic.split("=", 1)[1])
                    self.assertEqual(
                        failure["failure_code"], "invocation_identity_mismatch"
                    )
                    evidence = failure["identity_evidence"]
                    self.assertEqual(
                        [item["field"] for item in evidence["mismatches"]], [field]
                    )
                    self.assertEqual(evidence["status"], "blocked")

    def test_matching_identity_runs_original_seed_flow(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="preflight-seed-match-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            project = Path(temporary_root)
            (project / "tmp").mkdir()
            plan, module_payloads, expected_payloads = self._seed_inputs()
            identity = self._worker_identity(project, plan)
            from scripts.mapping_pilot import launcher

            original_seed = sandbox_preparation._prepare_new_sandbox
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(sandbox_preparation, "PROJECT_ROOT", project),
                mock.patch.object(
                    sandbox_preparation, "_require_preparation_startup_guard"
                ),
                mock.patch.object(
                    sandbox_preparation,
                    "_load_profile_seed_plan",
                    return_value=(plan, {"profile_id": "interior_tavern:p1"}),
                ) as load_plan,
                mock.patch.object(
                    sandbox_preparation,
                    "_load_profile_seed_inputs",
                    return_value=(module_payloads, expected_payloads),
                ),
                mock.patch.object(
                    profile_runner, "_repository_python", return_value=sys.executable
                ),
                mock.patch.object(sandbox_preparation, "_copy_runtime"),
                mock.patch.object(launcher, "validate_sandbox"),
                mock.patch.object(
                    sandbox_preparation,
                    "_prepare_new_sandbox",
                    wraps=original_seed,
                ) as seed,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = sandbox_preparation.main(
                    self._entrypoint_args(copy.deepcopy(identity))
                )

            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0, stderr.getvalue())
            load_plan.assert_called_once_with("interior_tavern", 1, "E01")
            seed.assert_called_once()
            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["invocation_identity"]["status"], "matched")
            sandbox = project / "tmp" / "combat_capture"
            self.assertTrue((sandbox / "config.py").is_file())
            self.assertTrue((sandbox / "mapping_pilot" / "seed_metadata.json").is_file())


class TestRealWorkerLaunchBoundary(unittest.TestCase):
    def test_each_identity_mismatch_blocks_actual_worker_launch(self) -> None:
        declared = {
            "command": [sys.executable, "-m", "worker", "--row", "E01"],
            "working_directory": str(PROJECT_ROOT / "tmp" / "combat_capture"),
            "pythonpath": os.pathsep.join(
                (
                    str(PROJECT_ROOT / "scripts" / "live_gate_preflight_guard"),
                    str(PROJECT_ROOT),
                )
            ),
        }
        mismatched_values = {
            "command": [*declared["command"], "--row=E02"],
            "working_directory": str(PROJECT_ROOT / "tmp" / "other-worker"),
            "pythonpath": declared["pythonpath"] + os.pathsep + "other-root",
        }
        from scripts.mapping_pilot import server

        args = argparse.Namespace(
            worker=True,
            fixture_id="interior_tavern",
            party_size=1,
            lifecycle="startup",
            source_sha="a" * 40,
            run_id="identity-worker-test",
            planned_row_id="E01",
            arm="A",
            lifecycle_id="identity-worker-test_s",
            resume_checkpoint_sha256=None,
        )

        for field, changed_value in mismatched_values.items():
            with self.subTest(field=field):
                intended = copy.deepcopy(declared)
                intended[field] = changed_value
                saved_result: dict[str, Any] = {}
                safe_environment = {
                    "PYTHONPATH": declared["pythonpath"],
                    **{name: "" for name in profile_runner._KNOWN_PROVIDER_KEYS},
                }
                with (
                    mock.patch.object(
                        profile_runner, "_require_worker_startup_guard"
                    ),
                    mock.patch.object(
                        profile_runner,
                        "_require_safe_worker_root",
                        return_value=PROJECT_ROOT,
                    ),
                    mock.patch.object(
                        profile_runner,
                        "_host_command",
                        return_value=declared["command"],
                    ),
                    mock.patch.object(
                        preflight_safety,
                        "current_invocation_identity",
                        return_value=intended,
                    ),
                    mock.patch.object(
                        profile_runner,
                        "_write_json",
                        side_effect=lambda _path, value: saved_result.update(value),
                    ),
                    mock.patch.object(profile_runner.os, "environ", safe_environment),
                    mock.patch.object(server, "launch_worker") as launch,
                ):
                    exit_code = profile_runner.main(
                        [
                            "--worker",
                            "--fixture-id",
                            args.fixture_id,
                            "--party-size",
                            str(args.party_size),
                            "--lifecycle",
                            args.lifecycle,
                            "--source-sha",
                            args.source_sha,
                            "--run-id",
                            args.run_id,
                            "--planned-row-id",
                            args.planned_row_id,
                            "--arm",
                            args.arm,
                            "--lifecycle-id",
                            args.lifecycle_id,
                        ]
                    )

                self.assertEqual(exit_code, 1)
                self.assertEqual(saved_result["failure_code"], "invocation_identity_mismatch")
                self.assertEqual(saved_result["outcome"], "failed")
                self.assertEqual(saved_result["calls"], [])
                self.assertEqual(launch.call_count, 0)
                self.assertEqual(
                    [
                        item["field"]
                        for item in saved_result["invocation_identity"]["mismatches"]
                    ],
                    [field],
                )
                self.assertNotIn("other-root", repr(saved_result["invocation_identity"]))


class _CounterRouter:
    def __init__(self) -> None:
        self.upstream_requests = 0
        self.provider_budget_remaining = 3
        self.live_attempts_used = 1

    def call(self, _task: str, *_args: Any, **_kwargs: Any) -> str:
        self.upstream_requests += 1
        self.provider_budget_remaining -= 1
        self.live_attempts_used += 1
        return "upstream response"


class TestProviderFreeRouterBoundary(unittest.TestCase):
    @staticmethod
    def _make_stub() -> FailClosedRouterStub:
        with mock.patch.object(router_stub_module, "_require_network_guard"):
            return FailClosedRouterStub(
                source_sha="a" * 40,
                responses={"narration": {"text": "A declared test response."}},
                command=[sys.executable, "-m", "worker"],
                pythonpath=os.pathsep.join(("guard", "repository")),
            )

    def test_stub_response_does_not_reach_upstream_or_consume_counters(self) -> None:
        router = _CounterRouter()
        original_call = router.call
        stub = self._make_stub()
        counters_before = (
            router.upstream_requests,
            router.provider_budget_remaining,
            router.live_attempts_used,
        )

        with mock.patch.object(router_stub_module, "_require_network_guard"):
            cleanup = install_fail_closed_router_stub(router, stub)
        try:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                response = router.call("narration", prompt="not recorded")
        finally:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                cleanup()

        self.assertEqual(response, {"text": "A declared test response."})
        self.assertEqual(stub.call_count, 1)
        self.assertEqual(
            (
                router.upstream_requests,
                router.provider_budget_remaining,
                router.live_attempts_used,
            ),
            counters_before,
        )
        self.assertEqual(router.call, original_call)

    def test_unknown_router_task_fails_closed_without_upstream_use(self) -> None:
        router = _CounterRouter()
        stub = self._make_stub()
        with mock.patch.object(router_stub_module, "_require_network_guard"):
            cleanup = install_fail_closed_router_stub(router, stub)
        try:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                with self.assertRaisesRegex(
                    RouterStubError, "no explicit stub response"
                ):
                    router.call("undeclared_task")
        finally:
            with mock.patch.object(router_stub_module, "_require_network_guard"):
                cleanup()

        self.assertEqual(stub.call_count, 1)
        self.assertEqual(stub.failure_code, "router_task_has_no_stub_response")
        self.assertEqual(router.upstream_requests, 0)
        self.assertEqual(router.provider_budget_remaining, 3)
        self.assertEqual(router.live_attempts_used, 1)

    def test_router_stub_installation_requires_network_guard(self) -> None:
        router = _CounterRouter()
        original_call = router.call
        stub = self._make_stub()

        with mock.patch.object(
            router_stub_module,
            "require_guard_active",
            side_effect=NetworkGuardError("guard is unavailable"),
        ):
            with self.assertRaisesRegex(RouterStubError, "requires the active"):
                install_fail_closed_router_stub(router, stub)

        self.assertEqual(router.call, original_call)
        self.assertEqual(router.upstream_requests, 0)


class TestIdentityComparison(unittest.TestCase):
    def test_mismatch_evidence_names_fields_without_raw_identity_values(self) -> None:
        declared = _identity()
        intended = copy.deepcopy(declared)
        intended["working_directory"] = "/different/secret-path"

        evidence = compare_invocation_identity(declared, intended)

        self.assertEqual(evidence["status"], "blocked")
        self.assertEqual(evidence["mismatches"][0]["field"], "working_directory")
        serialized = repr(evidence)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("workspace", serialized)


BASELINE_PROFILE_PATH = (
    PROJECT_ROOT / "scripts" / "fixtures" / "live_gate_preflight_profiles_all_missing.json"
)


def _load_baseline_profiles(expected_row_ids: list[str]) -> tuple[Any, Any]:
    """Run the controller's _load_profiles against the committed all-MISSING baseline.

    The checked-in declaration now carries measured profiles; this test builds its
    own synthetic measured declaration on top of a MISSING baseline.
    """
    from scripts import live_gate_preflight_profiles as content_profiles

    original_coverage = content_profiles.load_profile_coverage
    with (
        mock.patch.object(
            content_profiles,
            "load_profile_coverage",
            lambda *args, **kwargs: original_coverage(BASELINE_PROFILE_PATH),
        ),
        mock.patch.object(
            content_profiles,
            "copy_profile_document",
            lambda: json.loads(BASELINE_PROFILE_PATH.read_text(encoding="utf-8")),
        ),
    ):
        return preflight_controller._load_profiles(expected_row_ids)


class _InjectedClock:
    def __init__(self, monotonic_values: list[float]) -> None:
        self._monotonic_values = list(monotonic_values)
        self._last_monotonic = monotonic_values[0] if monotonic_values else 0.0
        self._wall = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        if self._monotonic_values:
            self._last_monotonic = self._monotonic_values.pop(0)
        return self._last_monotonic

    def wall_clock(self) -> datetime:
        self._wall += timedelta(seconds=1)
        return self._wall


class _CountingSP3Driver:
    def __init__(
        self,
        transcript_path: Path,
        counters: dict[str, int],
        *,
        ready: bool = True,
    ) -> None:
        self.transcript_path = transcript_path
        self.transcript = ""
        self.counters = counters
        self.ready = ready
        self.sent: list[str] = []

    def start(self) -> dict[str, bool]:
        return {"ready": self.ready}

    def send_turn(self, step_id: str, _utterance: str, _character: str) -> dict[str, Any]:
        self.sent.append(step_id)
        self.counters["router_stub_calls"] += 1
        return {
            "completed": True,
            "timed_out": False,
            "backend_output_count": 1,
            "game_output_count": 1,
            "elapsed_seconds": 0.01,
            "output_text": "provider-free injected response",
        }

    def close(self) -> None:
        return None


class TestActualSP3DriverStopPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_root = tempfile.TemporaryDirectory(
            prefix="live-gate-driver-policy-", dir=PROJECT_ROOT / "tmp"
        )
        self.addCleanup(self.temporary_root.cleanup)
        self.base_time = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        self._reset_ledger()

    def _reset_ledger(self) -> None:
        base_root = Path(self.temporary_root.name).relative_to(PROJECT_ROOT)
        self.ledger_root = (base_root / ("run-" + uuid.uuid4().hex[:8])).as_posix()
        self.run_id = "preflight-policy-" + uuid.uuid4().hex[:10]
        sp3_execution.create_or_resume_ledger(
            self.run_id, ledger_root=self.ledger_root, now=self.base_time
        )

    def _row_runner_hooks(
        self,
        *,
        row_run_id: str,
        clock: _InjectedClock,
        safety_counters: dict[str, int],
        driver_ready: bool = True,
        pre_content_classifier: Any = None,
    ) -> tuple[sp3_row_runner.RowRunnerHooks, list[_CountingSP3Driver], list[str]]:
        drivers: list[_CountingSP3Driver] = []
        seeded_rows: list[str] = []

        def start_server(
            _row: Any, _run_token: str, _lifecycle_id: str, log_path: Path
        ) -> Any:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="ascii")
            return SimpleNamespace(log_path=log_path)

        def make_driver(**kwargs: Any) -> _CountingSP3Driver:
            driver = _CountingSP3Driver(
                kwargs["transcript_path"], safety_counters, ready=driver_ready
            )
            drivers.append(driver)
            return driver

        def evidence_writer(*_args: Any, **_kwargs: Any) -> Path:
            return Path(self.ledger_root) / self.run_id / row_run_id / "evidence.json"

        hooks = sp3_row_runner.RowRunnerHooks(
            seed=lambda row: seeded_rows.append(str(row["row_id"])) or 0,
            start_server=start_server,
            wait_server_ready=lambda _server, _timeout: True,
            stop_server=lambda _server: None,
            driver_factory=make_driver,
            load_packet_evidence=lambda _root, _lifecycle_ids: {
                "evidence_status": "not_applicable",
                "records": [],
            },
            load_router_receipts=lambda _selected_run_id: {
                "evidence_status": "recorded",
                "records": [],
            },
            state_hasher=lambda _root: {
                "status": "recorded",
                "sha256": "a" * 64,
                "files": {"party_tracker.json": "b" * 64},
            },
            write_step_context=lambda _root, _context: None,
            evidence_writer=evidence_writer,
            scorer=sp3_scoring.score_row,
            pre_content_classifier=pre_content_classifier,
            source_identity=lambda: {
                "git_head_sha": "a" * 40,
                "branch": "test/preflight-driver-policy",
                "dirty": False,
                "worktree": str(PROJECT_ROOT),
            },
            monotonic=clock.monotonic,
            wall_clock=clock.wall_clock,
        )
        return hooks, drivers, seeded_rows

    def _run_injected_cap(self, cap_kind: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, int], list[_CountingSP3Driver]]:
        row_id = "E01"
        row_run_id = "preflight-row-" + uuid.uuid4().hex[:10]
        safety_counters = {
            "upstream_provider_requests": 0,
            "provider_budget_used": 0,
            "live_attempts_used": 0,
            "reserve_activations": 0,
            "router_stub_calls": 0,
        }
        if cap_kind == "time":
            cap_seconds = float(sp3_scoring.ROW_WALL_TIME_CAP_SECONDS)
            clock = _InjectedClock([100.0, 100.0 + cap_seconds, 100.0 + cap_seconds])
        else:
            clock = _InjectedClock([100.0, 100.0, 100.0])
        hooks, drivers, seeded_rows = self._row_runner_hooks(
            row_run_id=row_run_id,
            clock=clock,
            safety_counters=safety_counters,
        )

        # These test-only stubs bypass booking and never create a booking record.
        def run_without_booking(
            _selected_run_id: str, _operation: str, action: Any, **_kwargs: Any
        ) -> Any:
            return action({})

        request_guard = sp3_execution.check_provider_request

        def inject_attempt_counter(*args: Any, **kwargs: Any) -> dict[str, Any]:
            sp3_execution.reconcile_attempt_count(
                args[0],
                args[1],
                args[2],
                sp3_scoring.ROW_ATTEMPT_CAP,
                ledger_root=kwargs["ledger_root"],
                now=kwargs["now"],
            )
            return request_guard(*args, **kwargs)

        check_patch = (
            mock.patch.object(
                sp3_row_runner,
                "check_provider_request",
                side_effect=inject_attempt_counter,
            )
            if cap_kind == "attempt"
            else mock.patch.object(
                sp3_row_runner,
                "check_provider_request",
                wraps=request_guard,
            )
        )
        with (
            mock.patch.object(
                sp3_row_runner, "require_valid_booking", return_value={"test_only": True}
            ) as booking_check,
            mock.patch.object(
                sp3_row_runner,
                "execute_booked_operation",
                side_effect=run_without_booking,
            ),
            check_patch as checked_request,
        ):
            result = sp3_row_runner.execute_row(
                self.run_id,
                row_id,
                row_run_id=row_run_id,
                ledger_root=self.ledger_root,
                evidence_root=Path(self.ledger_root) / "evidence",
                hooks=hooks,
            )

        self.assertEqual(booking_check.call_count, 1)
        self.assertEqual(checked_request.call_count, 1)
        self.assertEqual(seeded_rows, [row_id])
        ledger = sp3_execution.create_or_resume_ledger(
            self.run_id, ledger_root=self.ledger_root, now=self.base_time
        )
        self.assertEqual(ledger["bookings"], [])
        self.assertTrue(all(slot["replacement"] is None for slot in ledger["slots"] if slot["row_type"] == "replacement_only"))
        self.assertEqual(safety_counters, {
            "upstream_provider_requests": 0,
            "provider_budget_used": 0,
            "live_attempts_used": 0,
            "reserve_activations": 0,
            "router_stub_calls": 0,
        })
        return result, ledger, safety_counters, drivers

    def test_attempt_and_time_caps_stop_the_actual_row_driver_before_send(self) -> None:
        for cap_kind, reason, expected_count in (
            ("attempt", "row_attempt_cap", sp3_scoring.ROW_ATTEMPT_CAP),
            ("time", "row_wall_time_cap", 0),
        ):
            with self.subTest(cap_kind=cap_kind):
                self._reset_ledger()
                result, ledger, _counters, drivers = self._run_injected_cap(cap_kind)
                self.assertEqual(result["verdict"], "BLOCKED")
                self.assertIn(reason, result["cap_stop"]["reasons"])
                self.assertEqual(result["ledger_attempt_count"], expected_count)
                self.assertEqual(len(drivers), 1)
                self.assertEqual(drivers[0].sent, [])
                slot = next(item for item in ledger["slots"] if item["row_id"] == "E01")
                self.assertIn(reason, slot["execution"]["cap_stop"]["reasons"])
                self.assertEqual(slot["execution"]["attempt_count"], expected_count)

    def _run_classified_row(
        self,
        row_id: str,
        *,
        classification: str,
        driver_ready: bool,
        safety_counters: dict[str, int],
        classification_contexts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row_run_id = "fault-" + row_id
        evidence = (
            [{
                "kind": "transport",
                "code": "connection_reset",
                "source": "tmp/preflight-driver-policy/server.log",
            }]
            if classification == "INFRASTRUCTURE"
            else [{
                "kind": "provider_status",
                "code": "usable_response_returned",
                "source": "tmp/preflight-driver-policy/outcome.json",
            }]
        )

        def inject_classification(context: Any) -> dict[str, Any]:
            classification_contexts.append(dict(context))
            return {
                "classification": classification,
                "reason": "injected driver outcome",
                "evidence": evidence,
            }

        hooks, drivers, seeded_rows = self._row_runner_hooks(
            row_run_id=row_run_id,
            clock=_InjectedClock([100.0]),
            safety_counters=safety_counters,
            driver_ready=driver_ready,
            pre_content_classifier=inject_classification,
        )
        with (
            mock.patch.object(
                sp3_row_runner,
                "require_valid_booking",
                return_value={"test_only": True},
            ),
            mock.patch.object(
                sp3_row_runner,
                "execute_booked_operation",
                side_effect=lambda _run, _operation, action, **_kwargs: action({}),
            ),
        ):
            result = sp3_row_runner.execute_row(
                self.run_id,
                row_id,
                row_run_id=row_run_id,
                ledger_root=self.ledger_root,
                evidence_root=Path(self.ledger_root) / "evidence",
                hooks=hooks,
            )

        self.assertEqual(seeded_rows, [row_id])
        if classification == "INFRASTRUCTURE":
            self.assertEqual(drivers[0].sent, [])
            self.assertIn("DriverNotReady", classification_contexts[-1]["error_types"])
        else:
            self.assertTrue(drivers[0].sent)
        self.assertEqual(
            {
                name: safety_counters[name]
                for name in (
                    "upstream_provider_requests",
                    "provider_budget_used",
                    "live_attempts_used",
                    "reserve_activations",
                )
            },
            {
                "upstream_provider_requests": 0,
                "provider_budget_used": 0,
                "live_attempts_used": 0,
                "reserve_activations": 0,
            },
        )
        self.assertEqual(
            result["pre_content_classification"]["classification"], classification
        )
        return result

    def test_three_consecutive_infrastructure_failures_pause_before_next_row(self) -> None:
        safety_counters = {
            "upstream_provider_requests": 0,
            "provider_budget_used": 0,
            "live_attempts_used": 0,
            "reserve_activations": 0,
            "router_stub_calls": 0,
        }
        classification_contexts: list[dict[str, Any]] = []
        outcomes = (
            ("E01", "INFRASTRUCTURE", False),
            ("E02", "CONTENT/RESULT", True),
            ("E03", "INFRASTRUCTURE", False),
            ("E04", "INFRASTRUCTURE", False),
        )
        for row_id, classification, driver_ready in outcomes:
            self._run_classified_row(
                row_id,
                classification=classification,
                driver_ready=driver_ready,
                safety_counters=safety_counters,
                classification_contexts=classification_contexts,
            )

        before_third = sp3_execution.create_or_resume_ledger(
            self.run_id, ledger_root=self.ledger_root, now=self.base_time
        )
        self.assertFalse(before_third["control"]["paused"])
        self.assertEqual(
            [
                next(event["row_id"] for event in before_third["control"]["audit_events"] if event["sequence"] == sequence)
                for sequence in before_third["control"]["infrastructure_failure_streak"]
            ],
            ["E03", "E04"],
        )
        self.assertGreater(safety_counters["router_stub_calls"], 0)
        self.assertIsNone(
            sp3_execution.assert_row_start_allowed(
                self.run_id, "E05", ledger_root=self.ledger_root
            )
        )

        self._run_classified_row(
            "E05",
            classification="INFRASTRUCTURE",
            driver_ready=False,
            safety_counters=safety_counters,
            classification_contexts=classification_contexts,
        )
        paused = sp3_execution.create_or_resume_ledger(
            self.run_id, ledger_root=self.ledger_root, now=self.base_time
        )
        pause = paused["control"]["pauses"][-1]
        self.assertTrue(paused["control"]["paused"])
        self.assertEqual(pause["triggering_row_ids"], ["E03", "E04", "E05"])
        self.assertIsNone(pause["owner_review"])

        seed_calls: list[str] = []
        hooks = SimpleNamespace(
            seed=lambda row: seed_calls.append(str(row["row_id"])) or 0
        )
        with (
            mock.patch.object(
                sp3_row_runner, "require_valid_booking", return_value={"test_only": True}
            ) as booking_check,
            mock.patch.object(
                sp3_row_runner,
                "execute_booked_operation",
                side_effect=lambda _run, _operation, action, **_kwargs: action({}),
            ) as booked_operation,
            self.assertRaisesRegex(sp3_row_runner.RowExecutionError, "paused pending owner review"),
        ):
            sp3_row_runner.execute_row(
                self.run_id,
                "E06",
                row_run_id="fault-E06",
                ledger_root=self.ledger_root,
                hooks=hooks,
            )

        booking_check.assert_not_called()
        booked_operation.assert_not_called()
        self.assertEqual(seed_calls, [])
        final = sp3_execution.create_or_resume_ledger(
            self.run_id, ledger_root=self.ledger_root, now=self.base_time
        )
        next_slot = next(item for item in final["slots"] if item["row_id"] == "E06")
        self.assertEqual(next_slot["execution"]["phase"], "not_started")
        self.assertIsNone(next_slot["execution"]["row_run_id"])
        self.assertTrue(
            all(
                item["replacement"] is None
                for item in final["slots"]
                if item["row_type"] == "replacement_only"
            )
        )


class TestPreflightControllerContinuation(unittest.TestCase):
    def test_controller_continues_after_second_path_and_first_row(self) -> None:
        source_sha = "a" * 40
        run_id = "continuation-test"
        frozen_rows, _reserves = preflight_controller._load_frozen_row_ids(None)
        expected_row_ids = [str(row["row_id"]) for row in frozen_rows]
        profiles, coverage = _load_baseline_profiles(expected_row_ids)
        profiles = copy.deepcopy(profiles)
        secondary = dict(profiles[("transition_tower_approach", 1)])
        from scripts import live_gate_preflight_profiles as content_profiles

        tool_hashes = content_profiles.tool_file_hashes()
        secondary["startup"] = {
            "status": "measured-under-stub",
            "call_count": 0,
            "call_sites": [],
            "stub_sha256": {
                "path": content_profiles.STUB_FILE,
                "sha256": tool_hashes[content_profiles.STUB_FILE],
            },
            "driver_sha256": [
                {"path": path, "sha256": tool_hashes[path]}
                for path in content_profiles.DRIVER_FILES
            ],
        }
        profiles[("transition_tower_approach", 1)] = secondary

        intended_worker_identities: dict[str, dict[str, Any]] = {}
        for frozen in frozen_rows:
            row_id = str(frozen["row_id"])
            plan = preflight_controller._resolve_row_plan(
                row_id,
                prereg_root=None,
                expected_row=frozen,
                profiles=profiles,
            )
            intended_worker_identities[row_id] = preflight_controller.planned_worker_identity(
                plan,
                source_sha=source_sha,
                row_run_id="pf-%s-%s" % (run_id, row_id),
                preflight_run_id=run_id,
            )

        e04 = next(row for row in frozen_rows if row["row_id"] == "E04")
        e04_plan = preflight_controller._resolve_row_plan(
            "E04", prereg_root=None, expected_row=e04, profiles=profiles
        )
        secondary_run_id = preflight_controller._lifecycle_run_id(
            run_id, "E04", 1, "startup", primary=False
        )
        secondary_identity = preflight_controller.planned_worker_identity(
            e04_plan,
            fixture_id="transition_tower_approach",
            lifecycle="startup",
            source_sha=source_sha,
            row_run_id=secondary_run_id,
            preflight_run_id=run_id,
        )
        lifecycle_identities = {"E04": {"transition_tower_approach": {"startup": secondary_identity}}}
        for row_id in ("E05", "E06"):
            frozen = next(row for row in frozen_rows if row["row_id"] == row_id)
            plan = preflight_controller._resolve_row_plan(
                row_id, prereg_root=None, expected_row=frozen, profiles=profiles
            )
            lifecycle_run_id = preflight_controller._lifecycle_run_id(
                run_id,
                row_id,
                1,
                "startup",
                primary=False,
            )
            identity = preflight_controller.planned_worker_identity(
                plan,
                fixture_id="transition_tower_approach",
                lifecycle="startup",
                source_sha=source_sha,
                row_run_id=lifecycle_run_id,
                preflight_run_id=run_id,
            )
            lifecycle_identities[row_id] = {
                "transition_tower_approach": {"startup": identity}
            }
        lifecycle_calls: list[tuple[str, str, str]] = []

        def injected_lifecycle(
            plan: preflight_controller.PreflightRowPlan,
            invocation: preflight_controller.PreflightLifecycleInvocation,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            lifecycle_calls.append(
                (plan.row_id, invocation.fixture_id, invocation.lifecycle)
            )
            return {
                "call_count": 0,
                "call_sites": [],
                "first_exchange": {
                    "status": "completed",
                    "step_id": plan.first_turn["step_id"],
                    "injected": True,
                },
                "worker_teardown": {
                    "server_stopped": True,
                    "port_8360_free": True,
                    "port_8370_free": True,
                    "shared_live_window_lock_released": True,
                    "call_count": 1,
                },
            }

        counters = {
            "upstream_provider_requests": 0,
            "provider_budget_used": 0,
            "live_attempts_used": 0,
            "reserve_activations": 0,
        }
        with (
            mock.patch.object(
                preflight_controller,
                "_load_profiles",
                return_value=(profiles, coverage),
            ),
            mock.patch.object(
                preflight_controller,
                "_run_lifecycle_invocation",
                side_effect=injected_lifecycle,
            ),
        ):
            report = preflight_controller.run_preflight_rows(
                source_sha=source_sha,
                run_id=run_id,
                intended_worker_identities=intended_worker_identities,
                intended_lifecycle_identities=lifecycle_identities,
                interfaces=preflight_controller.PreflightInterfaces(
                    prepare_sandbox=lambda *_args: self.fail("no sandbox may be prepared"),
                    supervise_row=lambda *_args: self.fail("no worker may launch"),
                    cleanup_sandbox=lambda *_args: self.fail("no sandbox may be cleaned"),
                    safety_counters=lambda: dict(counters),
                ),
            )

        for row_id in ("E04", "E05", "E06"):
            row_calls = [call for call in lifecycle_calls if call[0] == row_id]
            self.assertEqual(
                row_calls,
                [
                    (row_id, "landscape_village", "startup"),
                    (row_id, "transition_tower_approach", "startup"),
                ],
            )
        self.assertEqual(report["attempted_row_ids"], expected_row_ids)
        self.assertEqual(len(report["row_results"]), 26)
        last_e04_path = lifecycle_calls.index(("E04", "transition_tower_approach", "startup"))
        self.assertEqual(lifecycle_calls[last_e04_path + 1][0], "E05")
        self.assertEqual(report["replacement_only_rows_activated"], [])
        self.assertFalse(report["pilot_evidence_written"])
        self.assertFalse(report["booking_eligible"])
        self.assertFalse(report["live_gate_pass"])
        self.assertEqual(
            report["provider_free"],
            {
                "upstream_provider_requests_delta": 0,
                "provider_budget_used_delta": 0,
                "live_attempts_used_delta": 0,
                "reserve_activations_delta": 0,
                "router_stub_calls": 29,
            },
        )


class TestPreflightEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.run_id = "evidence-test-" + uuid.uuid4().hex[:12]
        self.evidence_root = (
            PROJECT_ROOT
            / "tmp"
            / "router-rollout"
            / "live-gate-preflight"
            / self.run_id
        )
        self.addCleanup(self._remove_evidence)
        frozen_rows, _reserves = preflight_controller._load_frozen_row_ids(None)
        self.row_ids = [str(row["row_id"]) for row in frozen_rows]
        self.source_sha = "a" * 40
        self.routing_identity = {
            "provider": "openrouter",
            "active_profile": "production-auto",
            "simple_model": "openrouter/auto",
        }
        self.invocation_identity = {
            "command": [
                str(PROJECT_ROOT / ".venv" / "bin" / "python"),
                "scripts/live_gate_preflight.py",
                "--provider-free",
            ],
            "working_directory": str(PROJECT_ROOT),
            "pythonpath": ".",
        }

    def _remove_evidence(self) -> None:
        if self.evidence_root.exists() and not self.evidence_root.is_symlink():
            shutil.rmtree(self.evidence_root)

    def _complete_row_report(self) -> dict[str, Any]:
        row_records = [
            {"row_id": row_id, "status": "completed"}
            for row_id in self.row_ids
        ]
        return {
            "report_type": "provider-free-row-preflight",
            "source_sha": self.source_sha,
            "status": "completed",
            "planned_row_count": len(self.row_ids),
            "planned_row_ids": list(self.row_ids),
            "attempted_row_ids": list(self.row_ids),
            "fully_covered_row_ids": list(self.row_ids),
            "replacement_only_rows_activated": [],
            "row_results": row_records,
            "provider_free": {
                "upstream_provider_requests_delta": 0,
                "provider_budget_used_delta": 0,
                "live_attempts_used_delta": 0,
                "reserve_activations_delta": 0,
                "router_stub_calls": len(row_records),
            },
        }

    def _write_report(
        self,
        *,
        row_report: Any = None,
        intended_invocation: Any = None,
        observed_invocation: Any = None,
        source_sha: Any = None,
        routing_identity: Any = None,
        dependency_lock_path: str | Path | None = Path("requirements-lock.txt"),
    ) -> str:
        selected_row_report = (
            self._complete_row_report() if row_report is None else row_report
        )
        return preflight_evidence.write_preflight_evidence(
            run_id=self.run_id,
            source_sha=self.source_sha if source_sha is None else source_sha,
            routing_identity=(
                self.routing_identity if routing_identity is None else routing_identity
            ),
            intended_invocation=(
                self.invocation_identity
                if intended_invocation is None
                else intended_invocation
            ),
            observed_invocation=(
                self.invocation_identity
                if observed_invocation is None
                else observed_invocation
            ),
            row_report=selected_row_report,
            dependency_lock_path=dependency_lock_path,
        )

    def _proposed_identity(self) -> dict[str, Any]:
        return {
            "source_sha": self.source_sha,
            "dependency_lock_sha256": preflight_evidence.dependency_lock_sha256(),
            "routing_identity": copy.deepcopy(self.routing_identity),
            "invocation_identity": copy.deepcopy(self.invocation_identity),
        }

    def test_exact_identity_match_does_not_trust_caller_supplied_row_summaries(self) -> None:
        path = self._write_report()

        report = json.loads((PROJECT_ROOT / path).read_text(encoding="ascii"))
        result = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=self._proposed_identity()
        )

        self.assertEqual(
            path,
            "tmp/router-rollout/live-gate-preflight/%s/preflight/preflight.json"
            % self.run_id,
        )
        self.assertEqual(report["preflight_status"], "BLOCKED")
        self.assertFalse(report["booking_eligible"])
        self.assertNotEqual(report["pf_status"], "PASS")
        self.assertEqual(report["pf_checks"]["PF6"], "PASS")
        self.assertEqual(
            [item["scenario"] for item in report["driver_stop_policy"]["scenarios"]],
            ["attempt_cap", "time_cap", "three_failure_pause"],
        )
        self.assertEqual(
            report["driver_stop_policy"]["recorded_proof_source_sha"],
            "58ab23336d7dcc521e5ec9d8774c6dae8a002b25",
        )
        self.assertEqual(
            report["driver_stop_policy"]["proof_sha256"],
            "7253dd8374ac7838341f94125ff5ab5c7d761417136b54af80287bcc44855a64",
        )
        self.assertEqual(report["identity"]["source_sha"], self.source_sha)
        self.assertNotIn(
            "source_sha", report["driver_stop_policy"]["source_binding"]
        )
        self.assertEqual(
            report["driver_stop_policy"]["source_binding"][
                "recorded_sha_relation_to_preflight_identity"
            ],
            "not_asserted_equal_to_current_preflight_identity_source_sha",
        )
        self.assertEqual(
            report["driver_stop_policy"]["source_binding"][
                "verified_relevant_source_file_sha256"
            ],
            preflight_evidence._DRIVER_STOP_POLICY_RELEVANT_SOURCE_SHA256,
        )
        self.assertEqual(
            report["driver_stop_policy"]["upstream_provider_requests_observation"],
            "not_observed_by_this_trace",
        )
        self.assertTrue(
            all(
                item["status"] == "PASS"
                and item["observations"]["basis"] == "injected_test_assertions"
                and item["observations"][
                    "upstream_provider_requests_observation"
                ]
                == "not_observed_by_this_trace"
                and item["observations"]["injected_test_counters"][
                    "live_attempts_used"
                ]
                == 0
                and "upstream_provider_requests"
                not in item["observations"]["injected_test_counters"]
                for item in report["driver_stop_policy"]["scenarios"]
            )
        )
        self.assertTrue(result["identity_match"])
        self.assertFalse(result["eligible"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(
            all(
                row["status"] == "MISSING"
                for row in report["row_coverage"]["row_outcomes"]
            )
        )
        self.assertFalse(result["booking_ruling_issued"])
        self.assertFalse(result["live_gate_pass"])
        self.assertEqual(report["booking_ruling_issued"], False)
        self.assertEqual(report["live_gate_pass"], False)
        self.assertEqual(report["provider_free"]["status"], "MISSING")

    def test_each_source_dependency_routing_and_invocation_mismatch_blocks(self) -> None:
        self._write_report()
        candidates = {
            "source_sha": {**self._proposed_identity(), "source_sha": "b" * 40},
            "dependency_lock_sha256": {
                **self._proposed_identity(),
                "dependency_lock_sha256": "0" * 64,
            },
            "routing_identity": {
                **self._proposed_identity(),
                "routing_identity": {
                    **self.routing_identity,
                    "active_profile": "different-profile",
                },
            },
            "invocation_identity": {
                **self._proposed_identity(),
                "invocation_identity": {
                    **self.invocation_identity,
                    "command": [*self.invocation_identity["command"], "--different"],
                },
            },
        }
        fields = {
            "source_sha": "source_sha",
            "dependency_lock_sha256": "dependency_lock_sha256",
            "routing_identity": "routing_identity_sha256",
            "invocation_identity": "invocation_identity_sha256",
        }
        for mismatch, candidate in candidates.items():
            with self.subTest(identity=mismatch):
                result = preflight_evidence.check_booking_eligibility(
                    run_id=self.run_id, proposed_identity=candidate
                )
                self.assertFalse(result["eligible"])
                self.assertFalse(result["identity_match"])
                self.assertEqual(result["mismatches"], [fields[mismatch]])
                self.assertFalse(result["booking_ruling_issued"])

    def test_sensitive_invocation_and_routing_values_are_not_persisted(self) -> None:
        sensitive_values = (
            "synthetic-token-do-not-store",
            "/private/sensitive-worktree",
            "/private/sensitive-pythonpath",
            "routing-secret-placeholder",
        )
        identity = {
            "command": ["python", "--token=" + sensitive_values[0]],
            "working_directory": sensitive_values[1],
            "pythonpath": sensitive_values[2],
        }
        route = {
            "provider": "openrouter",
            "active_profile": sensitive_values[3],
        }
        self._write_report(
            row_report={"report_type": "provider-free-row-preflight"},
            intended_invocation=identity,
            observed_invocation=identity,
            routing_identity=route,
        )

        report_path = self.evidence_root / "preflight" / "preflight.json"
        raw = report_path.read_bytes().decode("ascii")
        for value in sensitive_values:
            self.assertNotIn(value, raw)
        report = json.loads(raw)
        self.assertNotIn("command", report["invocation_identity"])
        self.assertIsNotNone(report["identity"]["routing_identity_sha256"])
        self.assertFalse(report["booking_eligible"])
        self.assertFalse(report["live_gate_pass"])

    def test_plain_mapping_cannot_claim_supervised_row_provenance(self) -> None:
        report = self._complete_row_report()
        report["execution_provenance"] = "supervised-retained-evidence"
        self._write_report(row_report=report)

        document = json.loads(
            (self.evidence_root / "preflight" / "preflight.json").read_text(
                encoding="ascii"
            )
        )
        result = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=self._proposed_identity()
        )
        self.assertEqual(document["execution_provenance"], "unverified")
        self.assertEqual(document["pf_checks"]["PF6"], "PASS")
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_standalone_driver_proof_does_not_satisfy_provider_free_status(self) -> None:
        row_report = {
            "report_type": "provider-free-row-preflight",
            "provider_free": {
                "upstream_provider_requests_delta": 0,
                "provider_budget_used_delta": 0,
                "live_attempts_used_delta": 0,
                "reserve_activations_delta": 0,
                "router_stub_calls": 1,
            },
        }
        self._write_report(row_report=row_report)

        document = json.loads(
            (self.evidence_root / "preflight" / "preflight.json").read_text(
                encoding="ascii"
            )
        )
        result = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=self._proposed_identity()
        )

        self.assertEqual(document["driver_stop_policy"]["status"], "PASS")
        self.assertEqual(
            document["driver_stop_policy"]["upstream_provider_requests_observation"],
            "not_observed_by_this_trace",
        )
        self.assertEqual(document["pf_checks"]["PF6"], "PASS")
        self.assertEqual(document["provider_free"]["status"], "MISSING")
        self.assertNotEqual(document["pf_status"], "PASS")
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_untrusted_caller_pf6_summary_cannot_replace_missing_proof(self) -> None:
        report = self._complete_row_report()
        report["driver_stop_policy"] = {"status": "PASS", "scenarios": ["fake"]}
        report["pf_checks"] = {"PF6": "PASS"}
        with tempfile.TemporaryDirectory(
            prefix="missing-pf6-proof-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            missing_path = (
                Path(temporary_root).relative_to(PROJECT_ROOT) / "driver-proof.json"
            )
            with mock.patch.object(
                preflight_evidence, "_DRIVER_STOP_POLICY_PATH", missing_path
            ):
                self._write_report(row_report=report)
                document = json.loads(
                    (self.evidence_root / "preflight" / "preflight.json").read_text(
                        encoding="ascii"
                    )
                )
                result = preflight_evidence.check_booking_eligibility(
                    run_id=self.run_id, proposed_identity=self._proposed_identity()
                )

        self.assertEqual(document["pf_checks"]["PF6"], "MISSING")
        self.assertEqual(
            document["driver_stop_policy"]["failure_code"],
            "driver_stop_policy_evidence_missing",
        )
        self.assertEqual(document["provider_free"]["status"], "MISSING")
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_changed_relevant_source_hash_fails_pf6(self) -> None:
        original_read = preflight_evidence._read_project_bytes

        def changed_source(relative_path: Path, maximum_bytes: int) -> bytes:
            if relative_path == Path("scripts/mapping_pilot/row_runner.py"):
                return b"changed source"
            return original_read(relative_path, maximum_bytes)

        with mock.patch.object(
            preflight_evidence, "_read_project_bytes", side_effect=changed_source
        ):
            evidence = preflight_evidence._driver_stop_policy_evidence()

        self.assertEqual(evidence["status"], "FAIL")
        self.assertEqual(
            evidence["failure_code"], "driver_stop_policy_source_mismatch"
        )

    def test_tampered_source_bound_driver_proof_fails_pf6(self) -> None:
        original = (
            PROJECT_ROOT / preflight_evidence._DRIVER_STOP_POLICY_PATH
        ).read_bytes()
        tampered = original.replace(b'"attempt_cap": true', b'"attempt_cap": false')
        self.assertNotEqual(original, tampered)
        with tempfile.TemporaryDirectory(
            prefix="tampered-pf6-proof-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            temporary_directory = Path(temporary_root)
            tampered_path = temporary_directory / "driver-proof.json"
            tampered_path.write_bytes(tampered)
            relative_path = tampered_path.relative_to(PROJECT_ROOT)
            with mock.patch.object(
                preflight_evidence, "_DRIVER_STOP_POLICY_PATH", relative_path
            ):
                self._write_report()
                document = json.loads(
                    (self.evidence_root / "preflight" / "preflight.json").read_text(
                        encoding="ascii"
                    )
                )
                result = preflight_evidence.check_booking_eligibility(
                    run_id=self.run_id, proposed_identity=self._proposed_identity()
                )

        self.assertEqual(document["pf_checks"]["PF6"], "FAIL")
        self.assertEqual(
            document["driver_stop_policy"]["failure_code"],
            "driver_stop_policy_evidence_tampered",
        )
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_unknown_provider_activity_observation_fails_pf6_closed(self) -> None:
        original = (
            PROJECT_ROOT / preflight_evidence._DRIVER_STOP_POLICY_PATH
        ).read_bytes()
        unknown_observation = original.replace(
            b'"not_observed_by_this_trace"', b'"unknown"'
        )
        self.assertNotEqual(original, unknown_observation)
        with tempfile.TemporaryDirectory(
            prefix="unknown-pf6-observation-", dir=PROJECT_ROOT / "tmp"
        ) as temporary_root:
            temporary_directory = Path(temporary_root)
            unknown_path = temporary_directory / "driver-proof.json"
            unknown_path.write_bytes(unknown_observation)
            relative_path = unknown_path.relative_to(PROJECT_ROOT)
            with (
                mock.patch.object(
                    preflight_evidence, "_DRIVER_STOP_POLICY_PATH", relative_path
                ),
                mock.patch.object(
                    preflight_evidence,
                    "_DRIVER_STOP_POLICY_SHA256",
                    hashlib.sha256(unknown_observation).hexdigest(),
                ),
            ):
                self._write_report()
                document = json.loads(
                    (self.evidence_root / "preflight" / "preflight.json").read_text(
                        encoding="ascii"
                    )
                )
                result = preflight_evidence.check_booking_eligibility(
                    run_id=self.run_id, proposed_identity=self._proposed_identity()
                )

        self.assertEqual(document["pf_checks"]["PF6"], "FAIL")
        self.assertEqual(
            document["driver_stop_policy"]["failure_code"],
            "driver_stop_policy_provenance_mismatch",
        )
        self.assertEqual(document["provider_free"]["status"], "MISSING")
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_provider_free_counters_must_show_stub_use_and_zero_external_use(self) -> None:
        report = self._complete_row_report()
        report["provider_free"]["router_stub_calls"] = 0
        self._write_report(row_report=report)

        document = json.loads(
            (self.evidence_root / "preflight" / "preflight.json").read_text(
                encoding="ascii"
            )
        )
        result = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=self._proposed_identity()
        )
        self.assertEqual(document["provider_free"]["status"], "MISSING")
        self.assertEqual(document["execution_provenance"], "unverified")
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_missing_report_and_invalid_proposed_identity_block(self) -> None:
        missing = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=None
        )
        self.assertEqual(missing["status"], "BLOCKED")
        self.assertFalse(missing["eligible"])

        self._write_report()
        invalid = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id,
            proposed_identity={
                **self._proposed_identity(),
                "source_sha": "not-a-full-sha",
            },
        )
        self.assertFalse(invalid["eligible"])
        self.assertIn("source_sha", invalid["mismatches"])

    def test_partial_rows_missing_lifecycle_or_injected_results_cannot_be_eligible(self) -> None:
        report = self._complete_row_report()
        report["row_results"].pop()
        report["attempted_row_ids"] = report["attempted_row_ids"][:-1]
        report["fully_covered_row_ids"] = report["fully_covered_row_ids"][:-1]
        self._write_report(row_report=report)

        document = json.loads(
            (self.evidence_root / "preflight" / "preflight.json").read_text(
                encoding="ascii"
            )
        )
        result = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=self._proposed_identity()
        )
        self.assertEqual(document["pf_checks"]["PF2"], "MISSING")
        self.assertNotEqual(document["pf_status"], "PASS")
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_untrusted_row_summaries_cannot_satisfy_lifecycle_coverage(self) -> None:
        report = self._complete_row_report()
        self._write_report(row_report=report)

        document = json.loads(
            (self.evidence_root / "preflight" / "preflight.json").read_text(
                encoding="ascii"
            )
        )
        result = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=self._proposed_identity()
        )
        self.assertEqual(document["pf_checks"]["PF4"], "MISSING")
        self.assertFalse(document["booking_eligible"])
        self.assertFalse(result["eligible"])

    def test_invalid_identity_teardown_or_fake_row_origin_fails_closed(self) -> None:
        report = self._complete_row_report()
        report["execution_provenance"] = "injected-test-interface"
        self._write_report(
            row_report=report,
            source_sha="not-a-sha",
            routing_identity={"api_key": "must-not-persist"},
            intended_invocation=None,
            observed_invocation=None,
            dependency_lock_path=Path("tmp/missing/requirements-lock.txt"),
        )

        raw = (self.evidence_root / "preflight" / "preflight.json").read_bytes()
        document = json.loads(raw.decode("ascii"))
        result = preflight_evidence.check_booking_eligibility(
            run_id=self.run_id, proposed_identity=self._proposed_identity()
        )
        self.assertFalse(document["booking_eligible"])
        self.assertNotEqual(document["pf_status"], "PASS")
        self.assertFalse(result["eligible"])
        self.assertNotIn(b"must-not-persist", raw)
        self.assertFalse(document["booking_ruling_issued"])
        self.assertFalse(document["live_gate_pass"])


class TestFailureCodeDetail(unittest.TestCase):
    def test_controller_error_keeps_reason_only_path(self) -> None:
        exc = preflight_controller.PreflightControllerError(
            "preflight safety counters are malformed"
        )
        self.assertEqual(
            preflight_controller._failure_code(exc),
            "preflight_safety_counters_are_malformed",
        )

    def test_qualifying_message_is_appended(self) -> None:
        exc = RuntimeError("comparison_git_identity_unavailable")
        self.assertEqual(
            preflight_controller._failure_code(exc),
            "preflight_boundary_failed_RuntimeError:comparison_git_identity_unavailable",
        )

    def test_chain_details_are_appended_in_order(self) -> None:
        try:
            try:
                raise profile_runner.CharacterizationError(
                    "comparison_git_identity_unavailable"
                )
            except profile_runner.CharacterizationError as inner:
                raise sandbox_preparation.SandboxPreparationError(
                    "comparison_source_identity_invalid"
                ) from inner
        except sandbox_preparation.SandboxPreparationError as exc:
            code = preflight_controller._failure_code(exc)
        self.assertEqual(
            code,
            "preflight_boundary_failed_SandboxPreparationError"
            ":comparison_source_identity_invalid"
            ":comparison_git_identity_unavailable",
        )

    def test_context_chain_is_followed_when_cause_is_absent(self) -> None:
        try:
            try:
                raise RuntimeError("context_reason")
            except RuntimeError:
                raise ValueError("outer_reason")
        except ValueError as exc:
            code = preflight_controller._failure_code(exc)
        self.assertEqual(
            code,
            "preflight_boundary_failed_ValueError:outer_reason:context_reason",
        )

    def test_non_identifier_messages_are_not_appended(self) -> None:
        messages = [
            "scripts/live_gate_preflight.py",
            "Unexpected Failure",
            'value={"a": 1}',
            "trailing.",
            "x" * 81,
            "",
        ]
        for message in messages:
            with self.subTest(message=message):
                self.assertEqual(
                    preflight_controller._failure_code(RuntimeError(message)),
                    "preflight_boundary_failed_RuntimeError",
                )

    def test_unsafe_outer_message_does_not_block_inner_detail(self) -> None:
        inner = RuntimeError("inner_reason")
        outer = RuntimeError("Bad/Path: /workspace/tmp/x")
        outer.__cause__ = inner
        self.assertEqual(
            preflight_controller._failure_code(outer),
            "preflight_boundary_failed_RuntimeError:inner_reason",
        )

    def test_chain_depth_is_capped_at_four_exceptions(self) -> None:
        exc = RuntimeError("reason_4")
        for index in range(3, -1, -1):
            wrapper = RuntimeError(f"reason_{index}")
            wrapper.__cause__ = exc
            exc = wrapper
        self.assertEqual(
            preflight_controller._failure_code(exc),
            "preflight_boundary_failed_RuntimeError"
            ":reason_0:reason_1:reason_2:reason_3",
        )

    def test_cause_cycle_terminates(self) -> None:
        first = RuntimeError("first_reason")
        second = RuntimeError("second_reason")
        first.__cause__ = second
        second.__cause__ = first
        self.assertEqual(
            preflight_controller._failure_code(first),
            "preflight_boundary_failed_RuntimeError:first_reason:second_reason",
        )

    def test_code_is_truncated_to_120_characters(self) -> None:
        inner = RuntimeError("a" * 80)
        middle = RuntimeError("b" * 80)
        middle.__cause__ = inner
        outer = RuntimeError("c" * 80)
        outer.__cause__ = middle
        full = "preflight_boundary_failed_RuntimeError:" + ":".join(
            ("c" * 80, "b" * 80, "a" * 80)
        )
        code = preflight_controller._failure_code(outer)
        self.assertEqual(len(code), 120)
        self.assertEqual(code, full[:120])

    def test_codes_always_satisfy_evidence_safe_code(self) -> None:
        long_type = type("E" * 100, (RuntimeError,), {})
        inner = RuntimeError("a" * 80)
        middle = RuntimeError("b" * 80)
        middle.__cause__ = inner
        deep = RuntimeError("c" * 80)
        deep.__cause__ = middle
        samples = [
            RuntimeError("comparison_git_identity_unavailable"),
            RuntimeError("Bad/Path"),
            long_type("ok_reason"),
            deep,
            preflight_controller.PreflightControllerError("x" * 200),
        ]
        for exc in samples:
            with self.subTest(exc=type(exc).__name__):
                code = preflight_controller._failure_code(exc)
                self.assertLessEqual(len(code), 120)
                self.assertEqual(preflight_evidence._safe_code(code), code)


if __name__ == "__main__":
    unittest.main()
