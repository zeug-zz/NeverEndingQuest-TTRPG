# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Offline tests for the frozen N3 live lifecycle driver core."""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import signal
import socket
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

import scripts.n3_lifecycle_gate as preflight_gate
import scripts.n3_live_lifecycle_gate as gate


TEST_SHA = "a" * 40
TEST_RUN_ID = "n3-20261111-test-run"
TEST_BOOKING = "n3-booking-test"
TEST_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SCRATCH_ROOT = gate.REPO_ROOT / "tmp" / "n3-live-lifecycle-gate-tests"


class FakePortInspector:
    def __init__(self) -> None:
        self.host_pid: int | None = None
        self.busy_ports: set[int] = set()
        self.seen: list[int] = []

    def inspect(self, port: int) -> preflight_gate.PortObservation:
        self.seen.append(port)
        if port in self.busy_ports:
            return preflight_gate.PortObservation(port, "occupied", (999,))
        if port == gate.HOST_PORT and self.host_pid is not None:
            return preflight_gate.PortObservation(port, "occupied", (self.host_pid,))
        return preflight_gate.PortObservation(port, "free")


class FakeHost:
    def __init__(self, root: Path, sandbox: Path, state_root: Path, run_id: str, ports: FakePortInspector) -> None:
        self.owner_pid = 444
        self.owned_pids: list[int] = []
        self.environment = gate.build_host_environment(sandbox, state_root, run_id)
        self.output = gate.ManagedHostOutputCounters()
        self.ports = ports
        self.started = False
        self.stopped = False
        self.root = root
        self.sandbox = sandbox

    def start(self) -> bool:
        self.started = True
        self.ports.host_pid = self.owner_pid
        self.owned_pids.append(self.owner_pid)
        ledger = Path(self.environment["NEQ_PROVIDER_ATTEMPT_LEDGER"])
        ledger.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "event": "header",
                "schema_version": 1,
                "budget": gate.PROVIDER_BUDGET,
                "run_id": self.environment["NEQ_PROVIDER_ATTEMPT_RUN_ID"],
            },
            {
                "event": "activated",
                "schema_version": 1,
                "budget": gate.PROVIDER_BUDGET,
                "run_id": self.environment["NEQ_PROVIDER_ATTEMPT_RUN_ID"],
                "transport_guard": "httpx-client-single-request",
                "pid": self.owner_pid,
            },
        ]
        ledger.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="ascii",
        )
        return True

    def stop(self) -> bool:
        self.stopped = True
        self.ports.host_pid = None
        return True


class FakeApi:
    def __init__(self, status_values: list[Mapping[str, object]] | None = None) -> None:
        self.status_values = list(status_values or [])
        self.calls: list[tuple[str, object]] = []
        self.last_status: Mapping[str, object] = {
            "ok": True,
            "status": {"companion_launches": 0, "identity_up_invocations": 0},
        }

    def get_status(self) -> gate.HostApiResponse:
        self.calls.append(("GET", "/api/player-sharing/status"))
        if self.status_values:
            self.last_status = self.status_values.pop(0)
        return gate.HostApiResponse(200, self.last_status)

    def post(self, action: str, payload: Mapping[str, object] | None = None) -> gate.HostApiResponse:
        self.calls.append(("POST", (action, dict(payload or {}))))
        return gate.HostApiResponse(200, {"ok": True, "reason": "stopped"})


class FakeProcess:
    def __init__(self, pid: int = 101, *, term_exits: bool = False) -> None:
        self.pid = pid
        self.stdout = io.BytesIO(b"stdout-secret-sentinel")
        self.stderr = io.BytesIO(b"stderr-secret-sentinel")
        self.returncode: int | None = None
        self.term_exits = term_exits
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("owned-host", timeout)
        return self.returncode


@contextlib.contextmanager
def network_process_tripwires():
    """Fail any accidental real process, socket, or HTTP activity in tests."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("real subprocess.run")))
        stack.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("real subprocess.Popen")))
        stack.enter_context(patch.object(socket, "socket", side_effect=AssertionError("real socket")))
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("real socket connection")))
        stack.enter_context(patch.object(http.client, "HTTPConnection", side_effect=AssertionError("real HTTP connection")))
        yield


class N3LiveLifecycleGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self) -> None:
        self.tripwires = network_process_tripwires()
        self.tripwires.__enter__()
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH_ROOT)
        self.root = Path(self.temp.name)
        self.run_id = TEST_RUN_ID
        self.report_argument = (
            gate.EVIDENCE_BASE / self.run_id / "preflight" / "preflight.json"
        ).as_posix()
        self.sha = TEST_SHA
        self.booking_id = TEST_BOOKING
        self.common_dir = self.root / ".git"
        self.common_dir.mkdir()
        self.identity = preflight_gate.WorkspaceIdentity(
            git_sha=self.sha,
            worktree_clean=True,
            platform_key="darwin-arm64",
            git_common_dir=self.common_dir,
            source_files_sha256="1" * 64,
            dependency_lock_sha256="2" * 64,
            route_contract_sha256="3" * 64,
            identity_freeze_sha256="4" * 64,
        )
        self.ports = FakePortInspector()
        self._prepare_python()
        self._prepare_sandbox()
        self._prepare_run_root()
        self.write_preflight()
        self.write_lock()
        self.fake_host: FakeHost | None = None
        self.fake_api = FakeApi()
        self.host_factory_calls = 0
        self.dependencies = self.make_dependencies()
        self.arguments = gate.RunArguments(
            run_id=self.run_id,
            sha=self.sha,
            booking_id=self.booking_id,
            preflight_report=self.report_argument,
            party_size=1,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.tripwires.__exit__(None, None, None)

    def _prepare_python(self) -> None:
        python = self.root / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="ascii")

    def _prepare_sandbox(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        (sandbox / "web" / "frontend").mkdir(parents=True)
        (sandbox / "run_web.py").write_text("# isolated host\n", encoding="ascii")
        (sandbox / "config.py").write_text("WEB_PORT = 8360\n", encoding="ascii")
        (sandbox / "web" / "frontend" / "index.html").write_text("", encoding="ascii")

    def _prepare_run_root(self) -> None:
        (self.root / gate.EVIDENCE_BASE / self.run_id / "preflight").mkdir(
            parents=True
        )

    def write_preflight(self, document: Mapping[str, object] | None = None) -> Path:
        path = self.root / self.report_argument
        payload = {
            "schema_version": 1,
            "gate": "N3-provider-free-preflight",
            "run_id": self.run_id,
            "preflight_mode": "provider-free",
            "preflight_verdict": "READY_FOR_PRIMARY_REVIEW",
            "gate_verdict": "PENDING",
            "is_gate_pass": False,
            "identity": {
                "git_sha": self.sha,
                "worktree": "clean",
                "platform": "darwin-arm64",
                "source_files_sha256": self.identity.source_files_sha256,
                "dependency_lock_sha256": self.identity.dependency_lock_sha256,
                "route_contract_sha256": self.identity.route_contract_sha256,
                "identity_freeze_sha256": self.identity.identity_freeze_sha256,
            },
            "invocation": {
                "command": [
                    "/usr/bin/python3",
                    "scripts/n3_lifecycle_gate.py",
                    "preflight",
                    "--run-id",
                    self.run_id,
                ],
                "cwd": str(self.root),
                "pythonpath": ".",
                "expected_sha": self.sha,
            },
            "manifest": {
                "sha256": preflight_gate.SCENARIO_MANIFEST_SHA256,
                "row_ids": [row.row_id for row in preflight_gate.SCENARIO_ROWS],
                "frozen_caps": preflight_gate.asdict(preflight_gate.FROZEN_CAPS),
                "approved_platforms": list(preflight_gate.APPROVED_PLATFORMS),
            },
            "caps_match_manifest": True,
            "effective_caps": preflight_gate.asdict(preflight_gate.FROZEN_CAPS),
            "row_coverage_complete": True,
            "rows": [
                {
                    "row_id": row.row_id,
                    "expected": row.expected,
                    "observed": {"ok": True},
                    "elapsed_seconds": 0.1,
                    "verdict": "PASS",
                }
                for row in preflight_gate.SCENARIO_ROWS
            ],
            "attempts": len(preflight_gate.SCENARIO_ROWS),
            "ports": {"host": gate.HOST_PORT, "player": gate.PLAYER_PORT},
            "teardown": {
                "service_stopped": True,
                "host_stopped": True,
                "capture_copy_removed": True,
                "ports_free": True,
                "lock_released": True,
                "complete": True,
            },
            "fault_checks": {
                key: {"passed": True}
                for key in (
                    "missing_row_fail_fast",
                    "attempt_cap_fail_fast",
                    "time_cap_fail_fast",
                    "teardown_failure_retains_lock",
                )
            },
            "providers_called": 0,
            "relay_connections": 0,
            "provider_attempt_budget_used": 0,
            "relay_attempt_budget_used": 0,
            "infrastructure_failures": [],
            "semantic_failures": [],
        }
        if document is not None:
            payload = dict(document)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def lock_record(self) -> dict[str, object]:
        return {
            "booking_id": self.booking_id,
            "holder": "N agent-run",
            "gate": "N3-live",
            "authorizing_ruling": "approved-n3-booking-ruling",
            "window_start": (TEST_NOW - timedelta(minutes=30)).isoformat(),
            "window_end": (TEST_NOW + timedelta(minutes=30)).isoformat(),
            "run_id": self.run_id,
            "evidence": (gate.EVIDENCE_BASE / self.run_id / "capture").as_posix(),
            "preflight_report": self.report_argument,
            "head": self.sha,
            "frozen_caps": {
                "party_size": 1,
                "platform": "macos-arm64",
                "provider_dispatch_attempts": 0,
                "max_tunnel_creations": 2,
                "max_companion_launches": 4,
                "window_hours": 1,
            },
        }

    def write_lock(self, record: Mapping[str, object] | None = None) -> Path:
        lock = self.common_dir / "neq-coordination" / "live-window.lock"
        lock.mkdir(parents=True, exist_ok=True)
        holder = lock / "holder.json"
        holder.write_text(
            json.dumps(dict(record or self.lock_record()), separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        return lock

    def make_dependencies(
        self,
        *,
        identity: preflight_gate.WorkspaceIdentity | None = None,
        ports: FakePortInspector | None = None,
        executors: Mapping[str, gate.RowExecutor] | None = None,
        api: FakeApi | None = None,
        companion_error: str | None = None,
        sandbox_error: str | None = None,
    ) -> gate.LiveGateDependencies:
        selected_ports = ports or self.ports
        selected_api = api or self.fake_api

        def make_host(root: Path, sandbox: Path, run_id: str) -> FakeHost:
            self.host_factory_calls += 1
            self.fake_host = FakeHost(
                root, sandbox, self.root / gate.EVIDENCE_BASE / run_id / "state", run_id, selected_ports
            )
            return self.fake_host

        def check_companion(_root: Path, platform_key: str) -> Mapping[str, object]:
            if companion_error:
                raise gate.GateError(companion_error)
            return {"platform": platform_key, "sha256": "5" * 64}

        def check_sandbox(root: Path) -> Path:
            if sandbox_error:
                raise gate.GateError(sandbox_error)
            return gate.validate_prepared_sandbox(root)

        return gate.LiveGateDependencies(
            root=self.root,
            identity_reader=lambda _root: identity or self.identity,
            port_inspector=selected_ports,
            preflight_reader=gate.load_preflight_report,
            companion_verifier=check_companion,
            sandbox_validator=check_sandbox,
            host_factory=make_host,
            api_factory=lambda: selected_api,
            executor_registry=executors or gate.ROW_EXECUTORS,
            monotonic=lambda: 1000.0,
            utc_now=lambda: TEST_NOW,
        )

    def test_frozen_manifest_digest_and_contract_rows(self) -> None:
        self.assertTrue(gate.verify_frozen_manifest())
        self.assertEqual(gate.calculate_manifest_digest(), gate.FROZEN_MANIFEST_SHA256)
        self.assertEqual(gate.calculate_manifest_digest(), gate.calculate_manifest_digest())
        self.assertEqual(
            [(row.row_id, row.name) for row in gate.LIVE_ROWS],
            [
                ("L01", "sharing-off-local-play"),
                ("L02", "identity-init-once"),
                ("L03", "issue-access-start-auth-entry"),
                ("L04", "duplicate-start-idempotent"),
                ("L05", "relay-loss-bounded-recovery"),
                ("L06", "credential-rotation-revocation"),
                ("L07", "stop-sharing"),
                ("L08", "host-exit-restart"),
                ("L09", "revoke-access"),
                ("L10", "clean-teardown"),
            ],
        )
        self.assertEqual(gate.LIVE_ROWS[4].timeout_seconds, 420)
        self.assertEqual(gate.FROZEN_CAPS["driver_wall_clock_seconds"], 3600)
        self.assertEqual(gate.FROZEN_CAPS["companion_serve_launches"], 4)
        self.assertEqual(gate.FROZEN_CAPS["companion_up_invocations"], 1)
        self.assertEqual(gate.FROZEN_CAPS["relay_tunnel_creations"], 2)
        self.assertEqual(gate.FROZEN_CAPS["provider_attempts"], 0)
        self.assertEqual(gate.FROZEN_CAPS["automatic_retries"], 0)
        manifest = gate.live_manifest()
        self.assertTrue(
            all("precondition" in row and "expected" in row for row in manifest["rows"])
        )
        self.assertEqual(
            manifest["verdict_policy"]["linux-arm64"]["reason"],
            "owner-run-required",
        )
        self.assertEqual(manifest["provider_budget_ceiling"], 1)

    def test_plan_and_help_have_no_side_effects(self) -> None:
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        stdout = io.StringIO()
        with patch("sys.stdout", stdout), patch.object(
            gate, "_default_dependencies", side_effect=AssertionError("plan dependencies")
        ):
            self.assertEqual(gate.main(["plan"]), 0)
        plan = json.loads(stdout.getvalue())
        self.assertTrue(plan["plan_only"])
        self.assertFalse(plan["side_effects"])
        self.assertEqual(plan["gate_verdict"], "PENDING")
        after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        self.assertEqual(before, after)
        help_output = io.StringIO()
        with patch("sys.stdout", help_output):
            with self.assertRaises(SystemExit) as raised:
                gate.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage:", help_output.getvalue())

    def test_capture_creation_failure_returns_blocked_without_launch(self) -> None:
        original_mkdir = Path.mkdir
        capture = self.root / gate.EVIDENCE_BASE / self.run_id / "capture"

        def refuse_capture(path: Path, *args: object, **kwargs: object) -> None:
            if path == capture:
                raise PermissionError("capture create refused")
            original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", refuse_capture):
            result = gate.run_live_gate(self.dependencies, self.arguments)
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertIn(
            "capture_directory_create_failed", result["infrastructure_failures"]
        )
        self.assertIsNone(result["evidence_path"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_partial_private_state_tree_creation_is_cleaned_up(self) -> None:
        original_mkdir = Path.mkdir
        state_root = self.root / "tmp" / "partial-state"

        def refuse_config(path: Path, *args: object, **kwargs: object) -> None:
            if path == state_root / "config":
                raise PermissionError("state child create refused")
            original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", refuse_config):
            with self.assertRaises(PermissionError):
                gate._create_private_state_tree(state_root)
        self.assertFalse(state_root.exists())

    def test_preflight_report_accepts_frozen_n3_and_compact_n2_shapes(self) -> None:
        n3_path = self.write_preflight()
        self.assertEqual(
            gate.load_preflight_report(self.root, self.report_argument, self.sha)["gate"],
            "N3-provider-free-preflight",
        )
        n2 = {"head": self.sha, "infrastructure_failures": []}
        n3_path.write_text(json.dumps(n2), encoding="utf-8")
        self.assertEqual(
            gate.load_preflight_report(self.root, self.report_argument, self.sha), n2
        )
        result = gate.run_live_gate(self.dependencies, self.arguments)
        self.assertNotIn(
            "preflight_identity_mismatch", result["infrastructure_failures"]
        )
        self.assertEqual(self.host_factory_calls, 1)

    def test_compact_n2_preflight_binds_sha_and_rejects_infrastructure_failures(self) -> None:
        path = self.write_preflight(
            {"head": "b" * 40, "infrastructure_failures": []}
        )
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)
        path = self.write_preflight(
            {"head": self.sha, "infrastructure_failures": ["preflight-fault"]}
        )
        with self.assertRaisesRegex(
            gate.GateError, "preflight_infrastructure_failures"
        ):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)

    def test_preflight_refuses_incomplete_rows_faults_semantic_failures_and_attempts(self) -> None:
        mutations = (
            lambda document: document.update({"run_id": "n3-other-run"}),
            lambda document: document.update({"head": "b" * 40}),
            lambda document: document["invocation"].update({"cwd": "/outside"}),
            lambda document: document["invocation"].update({"pythonpath": ""}),
            lambda document: document.update({"row_coverage_complete": False}),
            lambda document: document["rows"][0].update({"verdict": "BLOCKED"}),
            lambda document: document["rows"][0].update({"expected": "different"}),
            lambda document: document["fault_checks"].pop("attempt_cap_fail_fast"),
            lambda document: document["fault_checks"]["time_cap_fail_fast"].update(
                {"passed": False}
            ),
            lambda document: document.update({"semantic_failures": ["semantic-failure"]}),
            lambda document: document.update({"providers_called": 1}),
            lambda document: document.update({"attempts": 0}),
            lambda document: document["teardown"].update({"complete": False}),
            lambda document: document["teardown"].update({"lock_released": False}),
        )
        for mutate in mutations:
            document = json.loads(self.write_preflight().read_text(encoding="utf-8"))
            mutate(document)
            self.write_preflight(document)
            with self.subTest(document=document), self.assertRaisesRegex(
                gate.GateError, "preflight_report_invalid"
            ):
                gate.load_preflight_report(
                    self.root, self.report_argument, self.sha
                )

    def test_preflight_report_path_must_be_bound_to_its_run_id(self) -> None:
        source = self.write_preflight()
        other_run = self.root / gate.EVIDENCE_BASE / "n3-other-run" / "preflight"
        other_run.mkdir(parents=True)
        other_path = other_run / "preflight.json"
        other_path.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(
                self.root,
                other_path.relative_to(self.root).as_posix(),
                self.sha,
            )

    def test_preflight_refuses_missing_invalid_infrastructure_and_identity_mismatch(self) -> None:
        with self.assertRaisesRegex(gate.GateError, "preflight_report_missing"):
            gate.load_preflight_report(self.root, "tmp/missing.json", self.sha)
        path = self.write_preflight()
        path.write_text("not-json", encoding="ascii")
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)
        dirty = json.loads(self.write_preflight().read_text(encoding="utf-8"))
        dirty["infrastructure_failures"] = ["fault"]
        path.write_text(json.dumps(dirty), encoding="utf-8")
        with self.assertRaisesRegex(gate.GateError, "preflight_infrastructure_failures"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)
        mismatched = json.loads(self.write_preflight().read_text(encoding="utf-8"))
        mismatched["identity"]["git_sha"] = "b" * 40
        path.write_text(json.dumps(mismatched), encoding="utf-8")
        with self.assertRaisesRegex(gate.GateError, "preflight_report_invalid"):
            gate.load_preflight_report(self.root, self.report_argument, self.sha)

    def test_workspace_dirty_sha_and_unsupported_platform_refuse_before_side_effects(self) -> None:
        cases = (
            (False, self.sha, "darwin-arm64", "worktree_dirty"),
            (True, "b" * 40, "darwin-arm64", "sha_mismatch"),
            (True, self.sha, "linux-arm64", "live_platform_not_supported"),
        )
        for clean, sha, platform_key, expected in cases:
            identity = preflight_gate.WorkspaceIdentity(
                git_sha=sha,
                worktree_clean=clean,
                platform_key=platform_key,
                git_common_dir=self.common_dir,
                source_files_sha256="1" * 64,
                dependency_lock_sha256="2" * 64,
                route_contract_sha256="3" * 64,
                identity_freeze_sha256="4" * 64,
            )
            dependencies = self.make_dependencies(identity=identity)
            result = gate.run_live_gate(dependencies, self.arguments)
            self.assertEqual(result["gate_verdict"], "BLOCKED")
            self.assertIn(expected, result["infrastructure_failures"])
            self.assertIsNone(result["evidence_path"])
            self.assertEqual(self.host_factory_calls, 0)
        invalid_party = gate.RunArguments(
            run_id=self.run_id,
            sha=self.sha,
            booking_id=self.booking_id,
            preflight_report=self.report_argument,
            party_size=True,
        )
        result = gate.run_live_gate(self.dependencies, invalid_party)
        self.assertIn("party_size_unsupported", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_preflight_identity_hashes_must_match_live_workspace(self) -> None:
        preflight = self.write_preflight()
        document = json.loads(preflight.read_text(encoding="utf-8"))
        document["identity"]["route_contract_sha256"] = "9" * 64
        self.write_preflight(document)
        result = gate.run_live_gate(self.dependencies, self.arguments)
        self.assertIn("preflight_identity_mismatch", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_lock_record_verifies_and_each_required_field_is_bound(self) -> None:
        lock = self.write_lock()
        valid = gate.verify_lock_record(
            lock,
            root=self.root,
            arguments=self.arguments,
            platform_key="macos-arm64",
            now=TEST_NOW,
        )
        self.assertEqual(valid["booking_id"], self.booking_id)
        mutations = {
            "booking_id": "other-booking",
            "holder": "other-holder",
            "gate": "N2-live",
            "authorizing_ruling": "",
            "window_start": "not-a-date",
            "window_end": "not-a-date",
            "run_id": "other-run",
            "evidence": "tmp/other/capture",
            "preflight_report": "other-report.json",
            "head": "b" * 40,
        }
        for key, value in mutations.items():
            invalid = dict(self.lock_record())
            invalid[key] = value
            self.write_lock(invalid)
            with self.subTest(field=key), self.assertRaises(gate.GateError):
                gate.verify_lock_record(
                    lock,
                    root=self.root,
                    arguments=self.arguments,
                    platform_key="macos-arm64",
                    now=TEST_NOW,
                )
        for key, value in {
            "party_size": 4,
            "platform": "linux-arm64",
            "provider_dispatch_attempts": 1,
            "max_tunnel_creations": 3,
            "max_companion_launches": 5,
            "window_hours": 4,
        }.items():
            invalid = dict(self.lock_record())
            invalid["frozen_caps"] = dict(invalid["frozen_caps"])
            invalid["frozen_caps"][key] = value
            self.write_lock(invalid)
            with self.subTest(cap=key), self.assertRaisesRegex(
                gate.GateError, "lock_caps_mismatch"
            ):
                gate.verify_lock_record(
                    lock,
                    root=self.root,
                    arguments=self.arguments,
                    platform_key="macos-arm64",
                    now=TEST_NOW,
                )

    def test_lock_window_expired_and_over_three_hours_refuse(self) -> None:
        lock = self.write_lock()
        expired = self.lock_record()
        expired["window_start"] = (TEST_NOW - timedelta(hours=5)).isoformat()
        expired["window_end"] = (TEST_NOW - timedelta(seconds=1)).isoformat()
        self.write_lock(expired)
        with self.assertRaisesRegex(gate.GateError, "lock_window_expired"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        boundary = self.lock_record()
        boundary["window_end"] = TEST_NOW.isoformat()
        self.write_lock(boundary)
        with self.assertRaisesRegex(gate.GateError, "lock_window_expired"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        too_long = self.lock_record()
        too_long["window_start"] = (TEST_NOW - timedelta(hours=2)).isoformat()
        too_long["window_end"] = (TEST_NOW + timedelta(hours=2)).isoformat()
        too_long["frozen_caps"] = dict(too_long["frozen_caps"])
        too_long["frozen_caps"]["window_hours"] = 3
        self.write_lock(too_long)
        with self.assertRaisesRegex(gate.GateError, "lock_window_expired"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )

    def test_lock_requires_single_line_json_and_existing_directory(self) -> None:
        lock = self.write_lock()
        holder = lock / "holder.json"
        holder.write_text("{}\n{}\n", encoding="ascii")
        with self.assertRaisesRegex(gate.GateError, "lock_record_invalid"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        with self.assertRaisesRegex(gate.GateError, "lock_unavailable"):
            gate.verify_lock_record(
                self.root / "absent-lock",
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )

    def test_lock_rejects_symlinked_directory_and_holder(self) -> None:
        lock = self.write_lock()
        coordination = lock.parent
        lock_link = coordination / "linked-lock"
        lock_link.symlink_to(lock, target_is_directory=True)
        with self.assertRaisesRegex(gate.GateError, "lock_record_invalid"):
            gate.verify_lock_record(
                lock_link,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )
        holder = lock / "holder.json"
        target = coordination / "holder-copy.json"
        target.write_bytes(holder.read_bytes())
        holder.unlink()
        holder.symlink_to(target)
        with self.assertRaisesRegex(gate.GateError, "lock_record_invalid"):
            gate.verify_lock_record(
                lock,
                root=self.root,
                arguments=self.arguments,
                platform_key="macos-arm64",
                now=TEST_NOW,
            )

    def test_capture_destination_ports_and_companion_refusals(self) -> None:
        capture = self.root / gate.EVIDENCE_BASE / self.run_id / "capture"
        capture.mkdir()
        result = gate.run_live_gate(self.make_dependencies(), self.arguments)
        self.assertIn("capture_destination_exists", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)
        capture.rmdir()

        busy = FakePortInspector()
        busy.busy_ports.add(gate.PLAYER_PORT)
        result = gate.run_live_gate(self.make_dependencies(ports=busy), self.arguments)
        self.assertIn("gate_port_not_free", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)
        self.assertNotIn(8357, busy.seen)

        result = gate.run_live_gate(
            self.make_dependencies(companion_error="companion_digest_invalid"), self.arguments
        )
        self.assertIn("companion_digest_invalid", result["infrastructure_failures"])
        self.assertEqual(self.host_factory_calls, 0)

    def test_prepared_sandbox_config_is_parsed_without_execution(self) -> None:
        config = self.root / gate.CAPTURE_RELATIVE / "config.py"
        config.write_text("WEB_PORT = 8360\nprint('config-executed-sentinel')\n", encoding="ascii")
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            selected = gate.validate_prepared_sandbox(self.root)
        self.assertEqual(selected, self.root / gate.CAPTURE_RELATIVE)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(gate._config_has_exact_web_port(b"WEB_PORT = 8360\n"))
        for source in (
            b"WEB_PORT = 8357\n",
            b"WEB_PORT = 8360; OTHER = 1\n",
            b"WEB_PORT = int('8360')\n",
            b"WEB_PORT = 8360\nWEB_PORT = 8360\n",
            b"def f(WEB_PORT):\n    pass\nWEB_PORT = 8360\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(gate._config_has_exact_web_port(source))

    def test_environment_allowlist_is_exact_and_contract_overrides_parent(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        overrides = {
            "NEQ_OPEN_BROWSER": "1",
            "NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS": "3",
            "NEQ_N3_GATE_RUN_ID": "wrong-run",
            "NEQ_PROVIDER_ATTEMPT_BUDGET": "30",
            "NEQ_PROVIDER_ATTEMPT_LEDGER": "/outside/ledger",
            "OPENAI_API_KEY": "secret-env-sentinel",
            "AWS_SECRET_ACCESS_KEY": "secret-env-sentinel",
        }
        with patch.dict(os.environ, overrides, clear=False):
            environment = gate.build_host_environment(sandbox, state, self.run_id)
        expected = {
            "PATH",
            "PYTHONPATH",
            "PYTHONUNBUFFERED",
            "PYTHONDONTWRITEBYTECODE",
            "NEQ_OPEN_BROWSER",
            "NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS",
            "NEQ_N3_GATE_RUN_ID",
            "NEQ_PROVIDER_ATTEMPT_BUDGET",
            "NEQ_PROVIDER_ATTEMPT_LEDGER",
            "NEQ_PROVIDER_ATTEMPT_RUN_ID",
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
            "XDG_RUNTIME_DIR",
            "TMPDIR",
        }
        self.assertEqual(set(environment), expected)
        self.assertEqual(environment["NEQ_OPEN_BROWSER"], "0")
        self.assertEqual(environment["NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS"], "1")
        self.assertEqual(environment["NEQ_N3_GATE_RUN_ID"], self.run_id)
        self.assertEqual(environment["NEQ_PROVIDER_ATTEMPT_BUDGET"], "1")
        self.assertEqual(environment["NEQ_PROVIDER_ATTEMPT_RUN_ID"], self.run_id)
        self.assertEqual(environment["PYTHONPATH"], str(sandbox))
        self.assertTrue(environment["XDG_STATE_HOME"].startswith(str(state)))
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)
        self.assertNotIn("NEQ_PLAYER_PASSWORD_VERIFIER", environment)
        self.assertNotIn("NEQ_PLAYER_DEV_LISTENER", environment)

    def test_host_api_uses_loopback_host_origin_and_json_headers_without_logging(self) -> None:
        class Response:
            status = 200

            def read(self, _limit: int) -> bytes:
                return b'{"ok":true,"credential":"credential-sentinel","invitation":"https://relay.invalid/path"}'

        class Connection:
            def __init__(self, host: str, port: int, *, timeout: float) -> None:
                self.target = (host, port, timeout)
                self.calls: list[tuple[object, ...]] = []

            def request(self, *args: object, **kwargs: object) -> None:
                self.calls.append((args, kwargs))

            def getresponse(self) -> Response:
                return Response()

            def close(self) -> None:
                return

        connections: list[Connection] = []

        def factory(host: str, port: int, *, timeout: float) -> Connection:
            connection = Connection(host, port, timeout=timeout)
            connections.append(connection)
            return connection

        client = gate.HostApiClient(connection_factory=factory)
        status = client.get_status()
        post = client.post("initialize-identity", {"confirm": True})
        self.assertEqual(status.status, 200)
        self.assertEqual(post.payload["credential"], "credential-sentinel")
        get_args, get_kwargs = connections[0].calls[0]
        self.assertEqual(get_args, ("GET", "/api/player-sharing/status"))
        self.assertEqual(get_kwargs["headers"]["Host"], "127.0.0.1:8360")
        post_args, post_kwargs = connections[1].calls[0]
        self.assertEqual(post_args, ("POST", "/api/player-sharing/initialize-identity"))
        self.assertEqual(post_kwargs["headers"]["Host"], "127.0.0.1:8360")
        self.assertEqual(post_kwargs["headers"]["Origin"], "http://127.0.0.1:8360")
        self.assertEqual(post_kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(post_kwargs["body"], b'{"confirm":true}')
        self.assertNotIn("credential-sentinel", repr(post))
        self.assertNotIn("relay.invalid", repr(post))

    def test_host_api_bounds_response_and_rejects_unknown_action(self) -> None:
        class LargeResponse:
            status = 200

            def read(self, limit: int) -> bytes:
                return b" " * limit

        class Connection:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                return

            def request(self, *_args: object, **_kwargs: object) -> None:
                return

            def getresponse(self) -> LargeResponse:
                return LargeResponse()

            def close(self) -> None:
                return

        client = gate.HostApiClient(connection_factory=Connection)
        with self.assertRaisesRegex(gate.HostApiError, "host_api_response_too_large"):
            client.get_status()
        with self.assertRaisesRegex(gate.HostApiError, "host_api_action_invalid"):
            client.post("delete-identity")

    def test_host_api_refuses_when_owned_port_guard_fails(self) -> None:
        connection_calls: list[object] = []

        def factory(*args: object, **kwargs: object) -> object:
            connection_calls.append((args, kwargs))
            raise AssertionError("must not connect without ownership")

        client = gate.HostApiClient(connection_factory=factory)
        client.bind_ownership_guard(lambda: False)
        with self.assertRaisesRegex(
            gate.HostApiError, "managed_host_ownership_failed"
        ):
            client.get_status()
        self.assertEqual(connection_calls, [])
        with self.assertRaisesRegex(
            gate.HostApiError, "host_api_ownership_guard_invalid"
        ):
            client.bind_ownership_guard(lambda: True)

    def test_verdict_derivation_never_passes_gate_with_linux_blocked(self) -> None:
        all_pass = [{"row_id": row.row_id, "verdict": "PASS"} for row in gate.LIVE_ROWS]
        result = gate.derive_verdicts(all_pass)
        self.assertEqual(result["platform_verdicts"]["macos-arm64"]["verdict"], "PASS")
        self.assertEqual(result["platform_verdicts"]["linux-arm64"]["reason"], "owner-run-required")
        self.assertEqual(result["gate_verdict"], "PENDING")
        self.assertFalse(result["is_gate_pass"])
        blocked = list(all_pass)
        blocked[0] = {"row_id": "L01", "verdict": "BLOCKED"}
        self.assertEqual(
            gate.derive_verdicts(blocked)["platform_verdicts"]["macos-arm64"]["verdict"],
            "BLOCKED",
        )
        failed = list(all_pass)
        failed[0] = {"row_id": "L01", "verdict": "FAIL"}
        self.assertEqual(gate.derive_verdicts(failed)["gate_verdict"], "FAIL")
        duplicate_failure = list(all_pass)
        duplicate_failure[0] = {"row_id": "L01", "verdict": "PASS"}
        duplicate_failure.append({"row_id": "L01", "verdict": "FAIL"})
        self.assertEqual(
            gate.derive_verdicts(duplicate_failure)["gate_verdict"], "FAIL"
        )
        self.assertFalse(gate._bounded_json({"number": float("inf")}))

    def test_placeholder_executors_block_and_driver_summary_is_not_pass(self) -> None:
        result = gate.run_live_gate(self.dependencies, self.arguments)
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertFalse(result["is_gate_pass"])
        self.assertEqual(result["rows"][0]["row_id"], "L01")
        self.assertEqual(result["rows"][0]["verdict"], "BLOCKED")
        self.assertEqual(result["rows"][0]["reason"], "executor-not-implemented")
        self.assertTrue(all(row["verdict"] == "BLOCKED" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)
        self.assertIn(("POST", ("stop", {})), self.fake_api.calls)
        self.assertTrue(result["evidence_written"])
        capture = self.root / result["evidence_path"]
        self.assertTrue((capture / "run.json").is_file())
        self.assertTrue((capture / "rows.jsonl").is_file())
        self.assertTrue((capture / "summary.json").is_file())
        self.assertTrue((capture / "managed-host-output.json").is_file())
        self.assertTrue((capture / "provider-attempt-ledger.jsonl").is_file())
        self.assertTrue((capture / "SHA256SUMS").is_file())

    def test_evidence_checksum_failure_forces_persisted_platform_block(self) -> None:
        class PassingExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                return gate.RowExecutionResult("PASS", "observed")

        registry = {row.row_id: PassingExecutor() for row in gate.LIVE_ROWS}
        with patch.object(gate, "_write_sha256sums", return_value=False):
            result = gate.run_live_gate(
                self.make_dependencies(executors=registry), self.arguments
            )
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertEqual(
            result["platform_verdicts"]["macos-arm64"]["verdict"], "BLOCKED"
        )
        self.assertFalse(result["evidence_written"])
        summary = json.loads(
            (self.root / result["evidence_path"] / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(summary["gate_verdict"], "BLOCKED")
        self.assertEqual(
            summary["platform_verdicts"]["macos-arm64"]["verdict"], "BLOCKED"
        )

    def test_executor_exception_fails_fast_and_teardown_is_always_invoked(self) -> None:
        class ExplodingExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                raise RuntimeError("executor-secret-sentinel")

        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = ExplodingExecutor()
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry), self.arguments
        )
        self.assertEqual(result["gate_verdict"], "BLOCKED")
        self.assertIn("executor_exception:L01", result["infrastructure_failures"])
        self.assertEqual(result["rows"][0]["reason"], "executor_exception")
        self.assertTrue(all(row["reason"] == "fail-fast" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)
        self.assertIn(("POST", ("stop", {})), self.fake_api.calls)
        evidence = self.root / result["evidence_path"]
        for path in evidence.iterdir():
            if path.is_file():
                self.assertNotIn("executor-secret-sentinel", path.read_text(encoding="utf-8"))

    def test_counter_cap_breach_stops_after_one_row(self) -> None:
        class PassingExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                return gate.RowExecutionResult("PASS", "observed")

        statuses = [
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 5, "identity_up_invocations": 0}},
        ]
        api = FakeApi(statuses)
        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = PassingExecutor()
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry, api=api), self.arguments
        )
        self.assertIn("companion_launch_cap_breached", result["infrastructure_failures"])
        self.assertEqual(result["rows"][0]["verdict"], "FAIL")
        self.assertTrue(all(row["verdict"] == "BLOCKED" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)

    def test_initial_companion_activity_fails_l01_without_row_dispatch(self) -> None:
        class NeverCalledExecutor:
            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                raise AssertionError("initial companion activity must fail before row")

        api = FakeApi(
            [
                {
                    "ok": True,
                    "status": {
                        "companion_launches": 1,
                        "identity_up_invocations": 0,
                    },
                }
            ]
        )
        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = NeverCalledExecutor()
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry, api=api), self.arguments
        )
        self.assertEqual(result["gate_verdict"], "FAIL")
        self.assertEqual(result["rows"][0]["row_id"], "L01")
        self.assertEqual(result["rows"][0]["verdict"], "FAIL")
        self.assertEqual(result["rows"][0]["reason"], "unexpected_initial_companion_counters")
        self.assertTrue(all(row["verdict"] == "BLOCKED" for row in result["rows"][1:]))
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)

    def test_counter_cap_is_checked_before_the_next_executor(self) -> None:
        class CountingPassExecutor:
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, _context: gate.RowContext) -> gate.RowExecutionResult:
                self.calls += 1
                return gate.RowExecutionResult("PASS", "observed")

        statuses = [
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 0, "identity_up_invocations": 0}},
            {"ok": True, "status": {"companion_launches": 5, "identity_up_invocations": 0}},
        ]
        api = FakeApi(statuses)
        first = CountingPassExecutor()
        later = CountingPassExecutor()
        registry = dict(gate.ROW_EXECUTORS)
        registry["L01"] = first
        registry["L02"] = later
        result = gate.run_live_gate(
            self.make_dependencies(executors=registry, api=api), self.arguments
        )
        self.assertEqual(first.calls, 1)
        self.assertEqual(later.calls, 0)
        self.assertEqual(result["rows"][1]["reason"], "companion_launch_cap_breached")
        self.assertEqual(result["rows"][1]["verdict"], "FAIL")
        self.assertTrue(self.fake_host is not None and self.fake_host.stopped)

    def test_teardown_never_posts_stop_to_unowned_host_port(self) -> None:
        runner = gate.LiveGateRunner(self.dependencies, self.arguments)
        runner.host = FakeHost(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.root / gate.EVIDENCE_BASE / self.run_id / "state",
            self.run_id,
            self.ports,
        )
        runner.api = self.fake_api
        runner.host_attempted = True
        runner.host_started = True
        self.ports.busy_ports.add(gate.HOST_PORT)
        runner._teardown()
        self.assertFalse(runner.teardown["sharing_stop_attempted"])
        self.assertFalse(any(call[0] == "POST" for call in self.fake_api.calls))
        self.assertIn("sharing_teardown_failed", runner.infrastructure_failures)

    def test_teardown_stops_sharing_when_failed_start_left_owned_listener(self) -> None:
        runner = gate.LiveGateRunner(self.dependencies, self.arguments)
        runner.host = FakeHost(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.root / gate.EVIDENCE_BASE / self.run_id / "state",
            self.run_id,
            self.ports,
        )
        runner.api = self.fake_api
        self.ports.host_pid = runner.host.owner_pid
        runner.host_started = False
        runner._teardown()
        self.assertTrue(runner.teardown["sharing_stop_attempted"])
        self.assertIn(("POST", ("stop", {})), self.fake_api.calls)

    def test_counter_totals_include_restarted_host_epochs(self) -> None:
        runner = gate.LiveGateRunner(self.dependencies, self.arguments)
        runner.host = FakeHost(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.root / gate.EVIDENCE_BASE / self.run_id / "state",
            self.run_id,
            self.ports,
        )
        runner._observe_counter_sample(
            {"companion_launches": 4, "identity_up_invocations": 1}
        )
        runner._observe_counter_sample(
            {"companion_launches": 5, "identity_up_invocations": 1}
        )
        runner.host.owner_pid = 555
        runner._observe_counter_sample(
            {"companion_launches": 0, "identity_up_invocations": 0}
        )
        runner._observe_counter_sample(
            {"companion_launches": 1, "identity_up_invocations": 0}
        )
        self.assertEqual(
            runner.cumulative_counters,
            {"companion_launches": 6, "identity_up_invocations": 1},
        )
        with self.assertRaisesRegex(gate.GateError, "host_counters_regressed"):
            runner._observe_counter_sample(
                {"companion_launches": 0, "identity_up_invocations": 0}
            )

    def test_provider_ledger_reservation_is_fail(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        ledger = Path(
            gate.build_host_environment(sandbox, state, self.run_id)[
                "NEQ_PROVIDER_ATTEMPT_LEDGER"
            ]
        )
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"event": "header", "schema_version": 1, "budget": 1, "run_id": self.run_id})
            + "\n"
            + json.dumps({"event": "activated", "schema_version": 1, "budget": 1, "run_id": self.run_id, "transport_guard": "httpx-client-single-request", "pid": 444})
            + "\n"
            + json.dumps({"event": "reservation", "schema_version": 1, "budget": 1, "run_id": self.run_id, "reservation_number": 1, "pid": 444, "host": "provider-secret.example"})
            + "\n",
            encoding="ascii",
        )
        result = gate._validate_provider_ledger(
            ledger, self.run_id, expected_pids=[444]
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["reservation_count"], 1)

    def test_provider_ledger_accepts_only_owned_host_restart_activations(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        ledger = Path(
            gate.build_host_environment(sandbox, state, self.run_id)[
                "NEQ_PROVIDER_ATTEMPT_LEDGER"
            ]
        )
        ledger.parent.mkdir(parents=True, exist_ok=True)
        record_base = {
            "schema_version": 1,
            "budget": 1,
            "run_id": self.run_id,
        }
        records = [
            {"event": "header", **record_base},
            {
                "event": "activated",
                **record_base,
                "pid": 444,
                "transport_guard": "httpx-client-single-request",
            },
            {
                "event": "activated",
                **record_base,
                "pid": 445,
                "transport_guard": "httpx-client-single-request",
            },
        ]
        ledger.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="ascii",
        )
        result = gate._validate_provider_ledger(
            ledger, self.run_id, expected_pids=[444, 445]
        )
        self.assertEqual(result["activation_count"], 2)
        with self.assertRaisesRegex(gate.GateError, "provider_ledger_invalid"):
            gate._validate_provider_ledger(
                ledger, self.run_id, expected_pids=[444]
            )
        reused_pid_records = records[:2] + [dict(records[1])]
        ledger.write_text(
            "".join(
                json.dumps(record) + "\n" for record in reused_pid_records
            ),
            encoding="ascii",
        )
        reused = gate._validate_provider_ledger(
            ledger, self.run_id, expected_pids=[444, 444]
        )
        self.assertEqual(reused["activation_count"], 2)

    def test_provider_ledger_rejects_boolean_counts_and_symlinks(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / gate.EVIDENCE_BASE / self.run_id / "state"
        ledger = Path(
            gate.build_host_environment(sandbox, state, self.run_id)[
                "NEQ_PROVIDER_ATTEMPT_LEDGER"
            ]
        )
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"event": "header", "schema_version": True, "budget": 1, "run_id": self.run_id})
            + "\n"
            + json.dumps({"event": "activated", "schema_version": 1, "budget": 1, "run_id": self.run_id, "transport_guard": "httpx-client-single-request", "pid": 444})
            + "\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(gate.GateError, "provider_ledger_preexisting"):
            gate._validate_provider_ledger_target(
                sandbox, self.run_id, must_not_exist=True
            )
        with self.assertRaisesRegex(gate.GateError, "provider_ledger_identity_mismatch"):
            gate._validate_provider_ledger(
                ledger, self.run_id, expected_pids=[444]
            )
        ledger.unlink()
        outside = self.root / "tmp" / "provider-ledger-outside.jsonl"
        outside.write_text("{}\n", encoding="ascii")
        ledger.symlink_to(outside)
        with self.assertRaises(gate.GateError):
            gate._validate_provider_ledger(
                ledger, self.run_id, expected_pids=[444]
            )

    def test_evidence_redacts_urls_credentials_cookies_and_tunnel_ids(self) -> None:
        evidence = {
            "invitation_url": "https://public-secret.invalid/invite",
            "tunnel_id": "tunnel-id-secret-sentinel",
            "credential": "credential-secret-sentinel",
            "cookie": "cookie-secret-sentinel",
            "note": "credential=inline-secret-sentinel",
        }
        redacted = gate.redact_live_evidence(
            evidence,
            [
                "https://public-secret.invalid/invite",
                "tunnel-id-secret-sentinel",
                "credential-secret-sentinel",
                "cookie-secret-sentinel",
                "inline-secret-sentinel",
            ],
        )
        serialized = json.dumps(redacted)
        for sentinel in (
            "public-secret.invalid",
            "tunnel-id-secret-sentinel",
            "credential-secret-sentinel",
            "cookie-secret-sentinel",
            "inline-secret-sentinel",
        ):
            self.assertNotIn(sentinel, serialized)

    def test_host_harness_start_readiness_stop_escalation_and_port_discipline(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / "tmp" / "gate-state"
        ports = FakePortInspector()
        process = FakeProcess()
        factory_calls: list[tuple[list[str], dict[str, object]]] = []
        clock = [10.0]
        readiness = [False, True]

        def process_factory(command: list[str], **kwargs: object) -> FakeProcess:
            factory_calls.append((command, kwargs))
            ports.host_pid = process.pid
            return process

        def ready() -> bool:
            return readiness.pop(0) if readiness else True

        def sleep(seconds: float) -> None:
            clock[0] += seconds

        signalled: list[int] = []

        def signal_group(pgid: int, selected_signal: int) -> None:
            signalled.append(selected_signal)
            if selected_signal == signal.SIGKILL:
                process.returncode = -signal.SIGKILL
                ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=ready,
            signal_group=signal_group,
            monotonic=lambda: clock[0],
            sleep=sleep,
            start_timeout=1,
            stop_timeout=0.3,
            poll_interval=0.1,
        )
        self.assertTrue(host.start())
        command, options = factory_calls[0]
        self.assertEqual(
            command,
            [str(self.root / ".venv" / "bin" / "python"), "-c", "import run_web; run_web.main()"],
        )
        self.assertEqual(options["cwd"], str(sandbox))
        self.assertTrue(options["start_new_session"])
        self.assertFalse(options["shell"])
        self.assertEqual(options["env"], host.environment)
        self.assertEqual(options["env"]["NEQ_OPEN_BROWSER"], "0")
        self.assertEqual(options["env"]["NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS"], "1")
        self.assertTrue(host.stop())
        self.assertEqual(signalled, [signal.SIGTERM, signal.SIGKILL])
        self.assertTrue(all(port in {8360, 8370} for port in ports.seen))
        snapshot = host.output.snapshot()
        self.assertFalse(snapshot["raw_output_retained"])
        output = json.dumps(snapshot)
        self.assertNotIn("stdout-secret-sentinel", output)
        self.assertNotIn("stderr-secret-sentinel", output)
        self.assertGreater(snapshot["processes"][0]["stdout"]["bytes_observed"], 0)

    def test_host_harness_term_success_avoids_sigkill(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / "tmp" / "gate-state-term"
        ports = FakePortInspector()
        process = FakeProcess(term_exits=True)

        def process_factory(_command: list[str], **_kwargs: object) -> FakeProcess:
            ports.host_pid = process.pid
            return process

        def signal_group(_pgid: int, selected_signal: int) -> None:
            if selected_signal == signal.SIGTERM:
                process.returncode = 0
                ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=lambda: True,
            signal_group=signal_group,
            monotonic=lambda: 100.0,
            sleep=lambda _seconds: None,
            stop_timeout=0.1,
            poll_interval=0.05,
        )
        self.assertTrue(host.start())
        self.assertTrue(host.stop())

    def test_host_harness_restarts_owned_process_with_same_private_state_tree(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / "tmp" / "gate-state-restart"
        ports = FakePortInspector()
        processes = [
            FakeProcess(pid=201, term_exits=True),
            FakeProcess(pid=202, term_exits=True),
        ]
        by_pid = {process.pid: process for process in processes}
        factory_calls = 0

        def process_factory(_command: list[str], **_kwargs: object) -> FakeProcess:
            nonlocal factory_calls
            process = processes[factory_calls]
            factory_calls += 1
            ports.host_pid = process.pid
            return process

        def signal_group(pgid: int, selected_signal: int) -> None:
            if selected_signal == signal.SIGTERM:
                by_pid[pgid].returncode = 0
                ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=lambda: True,
            signal_group=signal_group,
            monotonic=lambda: 100.0,
            sleep=lambda _seconds: None,
            stop_timeout=0.1,
            poll_interval=0.05,
        )
        self.assertTrue(host.start())
        self.assertTrue(host.stop())
        state_identity = (state.stat().st_dev, state.stat().st_ino)
        self.assertTrue(host.start())
        self.assertTrue(host.stop())
        self.assertEqual(host.process_generation, 2)
        self.assertEqual(host.owned_pids, [201, 202])
        self.assertEqual((state.stat().st_dev, state.stat().st_ino), state_identity)
        self.assertEqual(factory_calls, 2)

    def test_host_harness_refuses_replaced_private_state_tree_on_restart(self) -> None:
        sandbox = self.root / gate.CAPTURE_RELATIVE
        state = self.root / "tmp" / "gate-state-replaced"
        ports = FakePortInspector()
        process = FakeProcess(pid=301, term_exits=True)

        def process_factory(_command: list[str], **_kwargs: object) -> FakeProcess:
            ports.host_pid = process.pid
            return process

        def signal_group(_pgid: int, selected_signal: int) -> None:
            if selected_signal == signal.SIGTERM:
                process.returncode = 0
                ports.host_pid = None

        host = gate.ManagedHostHarness(
            self.root,
            sandbox,
            state,
            self.run_id,
            process_factory=process_factory,
            port_inspector=ports,
            readiness_probe=lambda: True,
            signal_group=signal_group,
            monotonic=lambda: 100.0,
            sleep=lambda _seconds: None,
            stop_timeout=0.1,
            poll_interval=0.05,
        )
        self.assertTrue(host.start())
        self.assertTrue(host.stop())
        original_root = state.rename(state.with_name("gate-state-original"))
        state.mkdir(mode=0o700)
        with self.assertRaisesRegex(gate.GateError, "gate_state_root_invalid"):
            host.start()
        self.assertTrue(original_root.is_dir())
        self.assertTrue(host.process is None)

    def test_host_harness_refuses_ports_without_touching_8357(self) -> None:
        ports = FakePortInspector()
        ports.busy_ports.add(gate.HOST_PORT)
        host = gate.ManagedHostHarness(
            self.root,
            self.root / gate.CAPTURE_RELATIVE,
            self.root / "tmp" / "state-busy",
            self.run_id,
            process_factory=lambda *_args, **_kwargs: self.fail("must not spawn"),
            port_inspector=ports,
            readiness_probe=lambda: True,
        )
        self.assertFalse(host.start())
        self.assertNotIn(8357, ports.seen)


if __name__ == "__main__":
    unittest.main()
