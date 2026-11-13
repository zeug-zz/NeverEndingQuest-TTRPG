# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Hermetic invocation-boundary and provider-free router tests."""

from __future__ import annotations

import argparse
import copy
import io
import json
import os
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
        profiles, coverage = preflight_controller._load_profiles(expected_row_ids)
        profiles = copy.deepcopy(profiles)
        secondary = dict(profiles[("transition_tower_approach", 1)])
        secondary["startup"] = {
            "status": "measured-under-stub",
            "source_sha": source_sha,
            "call_count": 0,
            "call_sites": [],
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


if __name__ == "__main__":
    unittest.main()
