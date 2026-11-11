# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the primary-owned N3 lifecycle preflight."""

from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Mapping
from unittest import mock

from scripts import n3_lifecycle_gate as gate


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = REPO_ROOT / "tmp"
TEST_SHA = "a" * 40


class FakeClock:
    def __init__(self, start: float = 10_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakePortInspector:
    def __init__(self) -> None:
        self.listeners: dict[int, tuple[int, ...]] = {
            gate.HOST_PORT: (),
            gate.PLAYER_PORT: (),
        }
        self.calls: list[int] = []

    def inspect(self, port: int) -> gate.PortObservation:
        self.calls.append(port)
        pids = self.listeners.get(port, ())
        return gate.PortObservation(
            port,
            "occupied" if pids else "free",
            pids,
        )

    def set_listener(self, port: int, pids: tuple[int, ...]) -> None:
        self.listeners[port] = pids


class FakeLock:
    def __init__(self, *, acquire_ok: bool = True, release_ok: bool = True) -> None:
        self.acquire_ok = acquire_ok
        self.release_ok = release_ok
        self._acquired = False
        self.calls: list[str] = []
        self.holder: Mapping[str, object] | None = None

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self, holder_record: Mapping[str, object]) -> bool:
        self.calls.append("acquire")
        self.holder = holder_record
        self._acquired = self.acquire_ok
        return self.acquire_ok

    def release(self, _release_record: Mapping[str, object]) -> bool:
        self.calls.append("release")
        if self.release_ok:
            self._acquired = False
        return self.release_ok


class FakeHost:
    def __init__(
        self,
        inspector: FakePortInspector,
        *,
        start_ok: bool = True,
        stop_ok: bool = True,
    ) -> None:
        self.inspector = inspector
        self.start_ok = start_ok
        self.stop_ok = stop_ok
        self.started = False
        self.owner_pid = os.getpid()
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> bool:
        self.start_calls += 1
        if not self.start_ok:
            return False
        self.started = True
        self.inspector.set_listener(gate.HOST_PORT, (self.owner_pid,))
        return True

    def is_ready(self) -> bool:
        return self.started

    def stop(self) -> bool:
        self.stop_calls += 1
        if not self.stop_ok:
            return False
        self.started = False
        self.inspector.set_listener(gate.HOST_PORT, ())
        return True


class PreflightDependenciesFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.inspector = FakePortInspector()
        self.lock = FakeLock()
        self.hosts: list[FakeHost] = []
        self.harnesses: list[gate.LifecycleHarness] = []
        self.clock = FakeClock()
        source = root / gate.CAPTURE_SOURCE_RELATIVE
        (source / "areas").mkdir(parents=True)
        (source / "module_context.json").write_text(
            '{"name":"Capture Arena"}\n', encoding="ascii"
        )
        (source / "areas" / "area_1.json").write_text(
            '{"name":"fixture"}\n', encoding="ascii"
        )

    def identity_reader(self, root: Path) -> gate.WorkspaceIdentity:
        return gate.WorkspaceIdentity(
            git_sha=TEST_SHA,
            worktree_clean=True,
            platform_key="darwin-arm64",
            git_common_dir=root / ".git",
            source_files_sha256="b" * 64,
            dependency_lock_sha256="c" * 64,
            route_contract_sha256="d" * 64,
            identity_freeze_sha256="e" * 64,
        )

    def lock_factory(
        self,
        _identity: gate.WorkspaceIdentity,
        _run_id: str,
        _sha: str,
        _evidence_dir: Path,
    ) -> FakeLock:
        return self.lock

    def host_factory(
        self, _capture_copy: Path, inspector: gate.PortInspector
    ) -> FakeHost:
        assert isinstance(inspector, FakePortInspector)
        host = FakeHost(inspector)
        self.hosts.append(host)
        return host

    def lifecycle_factory(
        self,
        capture_copy: Path,
        host: gate.HostHarness,
        clock: object,
    ) -> gate.LifecycleHarness:
        harness = gate.PreflightLifecycleHarness(
            capture_copy,
            host,
            clock,  # type: ignore[arg-type]
        )
        self.harnesses.append(harness)
        return harness

    def dependencies(self) -> gate.PreflightDependencies:
        return gate.PreflightDependencies(
            root=self.root,
            identity_reader=self.identity_reader,
            port_inspector=self.inspector,
            lock_factory=self.lock_factory,
            capture_copier=gate._safe_capture_tree,
            host_factory=self.host_factory,
            lifecycle_factory=self.lifecycle_factory,
            clock=self.clock,
            utc_now=lambda: "2026-11-11T00:00:00Z",
        )


class N3LifecycleGateTests(unittest.TestCase):
    def setUp(self) -> None:
        TMP_ROOT.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(
            prefix="test_n3_lifecycle_gate_", dir=TMP_ROOT
        )
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.fixture = PreflightDependenciesFixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(
        self,
        run_id: str = "n3-provider-free-test",
        *,
        caps: gate.GateCaps = gate.FROZEN_CAPS,
    ) -> dict[str, object]:
        return gate.run_preflight(
            self.fixture.dependencies(),
            run_id=run_id,
            expected_sha=TEST_SHA,
            command=[".venv/bin/python", "scripts/n3_lifecycle_gate.py"],
            cwd=str(self.root),
            pythonpath=".",
            caps=caps,
        )

    def _standalone_harness(self) -> gate.PreflightLifecycleHarness:
        copy = self.root / "isolated-copy"
        (copy / "areas").mkdir(parents=True)
        (copy / "module_context.json").write_text("{}\n", encoding="ascii")
        host = FakeHost(self.fixture.inspector)
        self.assertTrue(host.start())
        return gate.PreflightLifecycleHarness(copy, host, self.fixture.clock)

    def test_manifest_is_frozen_with_ten_unique_rows_and_caps(self) -> None:
        self.assertEqual(len(gate.SCENARIO_ROWS), 10)
        self.assertEqual(len({row.row_id for row in gate.SCENARIO_ROWS}), 10)
        self.assertEqual(gate.FROZEN_CAPS.max_rows, 10)
        self.assertEqual(gate.FROZEN_CAPS.max_attempts, 10)
        self.assertEqual(gate.FROZEN_CAPS.max_attempts_per_row, 1)
        self.assertEqual(gate.FROZEN_CAPS.automatic_retries, 0)
        self.assertEqual(gate.FROZEN_CAPS.provider_attempts, 0)
        self.assertEqual(gate.FROZEN_CAPS.relay_connections, 0)
        self.assertTrue(gate.verify_frozen_manifest())
        self.assertRegex(gate.SCENARIO_MANIFEST_SHA256, r"^[0-9a-f]{64}$")

    def test_all_rows_use_real_service_controller_and_fake_boundaries(self) -> None:
        deps = self.fixture.dependencies()
        with (
            mock.patch.object(socket.socket, "bind", side_effect=AssertionError("bind forbidden")),
            mock.patch.object(socket.socket, "connect", side_effect=AssertionError("connect forbidden")),
            mock.patch.object(gate.subprocess, "Popen", side_effect=AssertionError("process forbidden")),
        ):
            report = self._run()

        self.assertEqual(report["preflight_verdict"], "READY_FOR_PRIMARY_REVIEW")
        self.assertEqual(report["gate_verdict"], "PENDING")
        self.assertIs(report["is_gate_pass"], False)
        self.assertTrue(report["row_coverage_complete"])
        rows = report["rows"]
        self.assertEqual(
            [row["row_id"] for row in rows],  # type: ignore[index]
            [row.row_id for row in gate.SCENARIO_ROWS],
        )
        self.assertTrue(all(row["verdict"] == "PASS" for row in rows))  # type: ignore[index]
        self.assertEqual(report["providers_called"], 0)
        self.assertEqual(report["relay_connections"], 0)
        self.assertTrue(report["caps_match_manifest"])
        self.assertEqual(self.fixture.lock.calls, ["acquire", "release"])
        self.assertEqual(len(self.fixture.hosts), 1)
        self.assertEqual(self.fixture.hosts[0].start_calls, 2)
        self.assertEqual(self.fixture.hosts[0].stop_calls, 2)
        self.assertEqual(
            report["preflight_host"]["expected_owner_pid"], os.getpid()  # type: ignore[index]
        )
        self.assertTrue(self.fixture.harnesses[0].controller() is not None)
        self.assertEqual(self.fixture.harnesses[0].state.gameplay_inputs, 0)
        self.assertTrue(set(self.fixture.inspector.calls).issubset({8360, 8370}))
        self.assertNotIn(8357, self.fixture.inspector.calls)
        self.assertTrue(report["teardown"]["complete"])  # type: ignore[index]
        self.assertTrue(
            all(
                item["passed"] is True
                for item in report["fault_checks"].values()  # type: ignore[union-attr]
            )
        )

        report_path = (
            self.root
            / gate.EVIDENCE_BASE
            / "n3-provider-free-test"
            / "preflight"
            / "preflight.json"
        )
        raw = report_path.read_text(encoding="ascii")
        self.assertNotIn(gate.FAKE_PASSWORD, raw)
        self.assertNotIn(gate.FAKE_ROTATED_PASSWORD, raw)
        self.assertNotIn(gate.FAKE_PLAINTEXT_CREDENTIAL, raw)
        saved = json.loads(raw)
        self.assertEqual(saved["invocation"]["expected_sha"], TEST_SHA)
        self.assertEqual(saved["invocation"]["cwd"], str(self.root))
        self.assertEqual(saved["invocation"]["pythonpath"], ".")

    def test_missing_row_fails_closed_and_tears_down(self) -> None:
        deps = self.fixture.dependencies()

        def omit_last(harness: gate.LifecycleHarness) -> Mapping[str, object]:
            actions = dict(harness.actions())
            actions.pop("clean-teardown")
            return actions

        deps = replace(deps, lifecycle_actions_factory=omit_last)  # type: ignore[arg-type]
        report = gate.run_preflight(
            deps,
            run_id="n3-missing-row-test",
            expected_sha=TEST_SHA,
            command=["test"],
            cwd=str(self.root),
            pythonpath=".",
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertEqual(report["gate_verdict"], "PENDING")
        self.assertTrue(
            any("missing_row:clean-teardown" in item for item in report["infrastructure_failures"])
        )
        self.assertTrue(self.fixture.hosts[0].stop_calls)
        self.assertIn("release", self.fixture.lock.calls)

    def test_infrastructure_port_failure_stops_before_lock_or_host(self) -> None:
        self.fixture.inspector.set_listener(gate.PLAYER_PORT, (4321,))
        report = self._run("n3-port-failure-test")
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("initial_port_8370_occupied_or_unknown", report["infrastructure_failures"])
        self.assertEqual(self.fixture.lock.calls, [])
        self.assertEqual(self.fixture.hosts, [])

    def test_lock_failure_stops_without_starting_host(self) -> None:
        self.fixture.lock.acquire_ok = False
        report = self._run("n3-lock-failure-test")
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("live_window_lock_unavailable", report["infrastructure_failures"])
        self.assertEqual(self.fixture.hosts, [])
        self.assertEqual(self.fixture.lock.calls, ["acquire"])

    def test_host_start_failure_still_calls_host_teardown(self) -> None:
        deps = self.fixture.dependencies()

        def failed_host_factory(
            _copy: Path, inspector: gate.PortInspector
        ) -> FakeHost:
            assert isinstance(inspector, FakePortInspector)
            host = FakeHost(inspector, start_ok=False)
            self.fixture.hosts.append(host)
            return host

        deps = replace(deps, host_factory=failed_host_factory)
        report = gate.run_preflight(
            deps,
            run_id="n3-host-start-failure-test",
            expected_sha=TEST_SHA,
            command=["test"],
            cwd=str(self.root),
            pythonpath=".",
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("preflight_host_start_failed", report["infrastructure_failures"])
        self.assertEqual(self.fixture.hosts[0].stop_calls, 1)
        self.assertTrue(report["teardown"]["complete"])  # type: ignore[index]
        self.assertEqual(self.fixture.lock.calls, ["acquire", "release"])

    def test_partial_capture_copy_is_removed_after_copy_failure(self) -> None:
        deps = self.fixture.dependencies()

        def partial_copy(source: Path, destination: Path) -> str:
            gate._safe_capture_tree(source, destination)
            raise OSError("synthetic copy interruption")

        deps = replace(deps, capture_copier=partial_copy)
        report = gate.run_preflight(
            deps,
            run_id="n3-copy-failure-test",
            expected_sha=TEST_SHA,
            command=["test"],
            cwd=str(self.root),
            pythonpath=".",
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("capture_copy_failed", report["infrastructure_failures"])
        self.assertTrue(report["teardown"]["capture_copy_removed"])  # type: ignore[index]
        self.assertTrue(report["teardown"]["complete"])  # type: ignore[index]
        self.assertEqual(self.fixture.lock.calls, ["acquire", "release"])

    def test_file_lock_uses_holder_then_booking_and_release_order(self) -> None:
        coordination = self.root / "shared-coordination"
        lock = gate.FileLiveWindowLock(
            gate.LockRequest(coordination, "n3-lock-protocol-test", "N3-test-booking")
        )
        holder = {"booking_id": "N3-test-booking", "gate": "N3-preflight"}
        self.assertTrue(lock.acquire(holder))
        lock_dir = coordination / "live-window.lock"
        self.assertTrue((lock_dir / "holder.json").is_file())
        booking_lines = (coordination / "bookings.log").read_text(
            encoding="ascii"
        ).splitlines()
        self.assertEqual(json.loads(booking_lines[0]), holder)
        self.assertTrue(
            lock.release({"event": "release", "booking_id": "N3-test-booking"})
        )
        booking_lines = (coordination / "bookings.log").read_text(
            encoding="ascii"
        ).splitlines()
        self.assertEqual(len(booking_lines), 2)
        self.assertEqual(json.loads(booking_lines[1])["event"], "release")
        self.assertFalse(lock_dir.exists())

    def test_system_port_inspector_fails_closed_on_lsof_errors(self) -> None:
        inspector = gate.SystemPortInspector()
        with (
            mock.patch.object(gate.shutil, "which", return_value="/usr/sbin/lsof"),
            mock.patch.object(
                gate.subprocess,
                "run",
                return_value=mock.Mock(returncode=1, stdout="", stderr=""),
            ),
        ):
            self.assertEqual(inspector.inspect(gate.PLAYER_PORT).state, "free")
        with (
            mock.patch.object(gate.shutil, "which", return_value="/usr/sbin/lsof"),
            mock.patch.object(
                gate.subprocess,
                "run",
                return_value=mock.Mock(
                    returncode=1, stdout="", stderr="permission denied"
                ),
            ),
        ):
            self.assertEqual(inspector.inspect(gate.PLAYER_PORT).state, "unknown")
        with mock.patch.object(gate.shutil, "which", return_value=None):
            self.assertEqual(inspector.inspect(gate.HOST_PORT).state, "unknown")

    def test_existing_run_directory_is_not_reused(self) -> None:
        run_root = self.root / gate.EVIDENCE_BASE / "n3-existing-run-test"
        run_root.mkdir(parents=True)
        report = self._run("n3-existing-run-test")
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("evidence_run_path_already_exists", report["infrastructure_failures"])
        self.assertEqual(self.fixture.lock.calls, [])
        self.assertEqual(self.fixture.hosts, [])

    def test_attempt_cap_stops_before_excess_row(self) -> None:
        harness = self._standalone_harness()
        result = gate.exercise_lifecycle_rows(
            harness,
            clock=self.fixture.clock,
            caps=replace(gate.FROZEN_CAPS, max_attempts=9),
        )
        self.assertEqual(result["attempts"], 9)
        self.assertIn("attempt_cap_exceeded", result["infrastructure_failures"])
        rows = result["rows"]
        self.assertEqual(rows[-1]["row_id"], "clean-teardown")  # type: ignore[index]
        self.assertEqual(rows[-1]["verdict"], "BLOCKED")  # type: ignore[index]

    def test_preflight_attempt_cap_blocks_and_still_tears_down(self) -> None:
        report = self._run(
            "n3-attempt-cap-test",
            caps=replace(gate.FROZEN_CAPS, max_attempts=9),
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertEqual(report["attempts"], 9)
        self.assertIn("attempt_cap_exceeded", report["infrastructure_failures"])
        self.assertTrue(report["teardown"]["complete"])  # type: ignore[index]
        self.assertEqual(self.fixture.lock.calls, ["acquire", "release"])

    def test_nonfrozen_caps_never_produce_preflight_readiness(self) -> None:
        report = self._run(
            "n3-nonfrozen-caps-test",
            caps=replace(gate.FROZEN_CAPS, max_run_seconds=7200),
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIs(report["caps_match_manifest"], False)
        self.assertIn("caps_manifest_mismatch", report["infrastructure_failures"])
        self.assertTrue(report["teardown"]["complete"])  # type: ignore[index]

    def test_time_cap_stops_and_marks_remaining_rows_blocked(self) -> None:
        harness = self._standalone_harness()
        actions = dict(harness.actions())
        original = actions["sharing-off-local-play"]

        def advances_past_cap() -> Mapping[str, object]:
            result = original()
            self.fixture.clock.advance(2.0)
            return result

        actions["sharing-off-local-play"] = advances_past_cap
        result = gate.exercise_lifecycle_rows(
            harness,
            clock=self.fixture.clock,
            caps=replace(gate.FROZEN_CAPS, max_run_seconds=1, max_row_seconds=10),
            actions=actions,
        )
        self.assertIn("run_time_cap_exceeded", result["infrastructure_failures"])
        rows = result["rows"]
        self.assertEqual(rows[0]["verdict"], "BLOCKED")  # type: ignore[index]
        self.assertTrue(
            all(row["verdict"] == "BLOCKED" for row in rows[1:])  # type: ignore[index]
        )

    def test_preflight_time_cap_blocks_and_still_tears_down(self) -> None:
        deps = self.fixture.dependencies()

        def overrun_first_row(
            harness: gate.LifecycleHarness,
        ) -> Mapping[str, object]:
            actions = dict(harness.actions())
            first = actions["sharing-off-local-play"]

            def advance() -> Mapping[str, object]:
                result = first()
                self.fixture.clock.advance(2.0)
                return result

            actions["sharing-off-local-play"] = advance
            return actions

        deps = replace(deps, lifecycle_actions_factory=overrun_first_row)  # type: ignore[arg-type]
        report = gate.run_preflight(
            deps,
            run_id="n3-time-cap-test",
            expected_sha=TEST_SHA,
            command=["test"],
            cwd=str(self.root),
            pythonpath=".",
            caps=replace(gate.FROZEN_CAPS, max_run_seconds=1, max_row_seconds=10),
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("run_time_cap_exceeded", report["infrastructure_failures"])
        self.assertTrue(report["teardown"]["complete"], report["teardown"])  # type: ignore[index]
        self.assertEqual(self.fixture.lock.calls, ["acquire", "release"])

    def test_setup_time_cap_stops_before_host_start_and_releases_lock(self) -> None:
        deps = self.fixture.dependencies()

        def slow_copy(source: Path, destination: Path) -> str:
            digest = gate._safe_capture_tree(source, destination)
            self.fixture.clock.advance(2.0)
            return digest

        deps = replace(deps, capture_copier=slow_copy)
        report = gate.run_preflight(
            deps,
            run_id="n3-setup-time-cap-test",
            expected_sha=TEST_SHA,
            command=["test"],
            cwd=str(self.root),
            pythonpath=".",
            caps=replace(gate.FROZEN_CAPS, max_run_seconds=1),
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("run_time_cap_exceeded", report["infrastructure_failures"])
        self.assertEqual(self.fixture.hosts, [])
        self.assertEqual(self.fixture.lock.calls, ["acquire", "release"])
        self.assertTrue(report["teardown"]["capture_copy_removed"])  # type: ignore[index]
        self.assertTrue(report["teardown"]["complete"])  # type: ignore[index]

    def test_row_assertion_failure_stops_later_rows_but_runs_teardown(self) -> None:
        deps = self.fixture.dependencies()

        def fail_first_row(
            harness: gate.LifecycleHarness,
        ) -> Mapping[str, object]:
            actions = dict(harness.actions())
            actions["sharing-off-local-play"] = lambda: {"ok": False, "reason": "fixture_failure"}
            return actions

        deps = replace(deps, lifecycle_actions_factory=fail_first_row)  # type: ignore[arg-type]
        report = gate.run_preflight(
            deps,
            run_id="n3-row-failure-test",
            expected_sha=TEST_SHA,
            command=["test"],
            cwd=str(self.root),
            pythonpath=".",
        )
        self.assertEqual(report["preflight_verdict"], "FAIL")
        self.assertEqual(report["rows"][0]["verdict"], "FAIL")  # type: ignore[index]
        self.assertTrue(
            all(row["verdict"] == "BLOCKED" for row in report["rows"][1:])  # type: ignore[index]
        )
        self.assertTrue(report["teardown"]["complete"])  # type: ignore[index]
        self.assertEqual(self.fixture.lock.calls, ["acquire", "release"])

    def test_teardown_failure_preserves_lock_and_blocks(self) -> None:
        deps = self.fixture.dependencies()

        def host_factory(
            _copy: Path, inspector: gate.PortInspector
        ) -> FakeHost:
            assert isinstance(inspector, FakePortInspector)
            host = FakeHost(inspector, stop_ok=False)
            self.fixture.hosts.append(host)
            return host

        deps = replace(deps, host_factory=host_factory)
        report = gate.run_preflight(
            deps,
            run_id="n3-teardown-failure-test",
            expected_sha=TEST_SHA,
            command=["test"],
            cwd=str(self.root),
            pythonpath=".",
        )
        self.assertEqual(report["preflight_verdict"], "BLOCKED")
        self.assertIn("host_teardown_failed", report["infrastructure_failures"])
        self.assertIn("teardown_port_8360_occupied_or_unknown", report["infrastructure_failures"])
        self.assertEqual(self.fixture.lock.calls, ["acquire"])
        self.assertTrue(self.fixture.lock.acquired)

    def test_redacted_evidence_writer_removes_secrets_and_urls(self) -> None:
        target = self.root / "redacted.json"
        payload = {
            "credential": gate.FAKE_PLAINTEXT_CREDENTIAL,
            "session_revoked": True,
            "message": "password=n3-private-value url=https://private.example/x",
        }
        self.assertTrue(
            gate.write_redacted_evidence(
                target,
                payload,
                (gate.FAKE_PLAINTEXT_CREDENTIAL, "n3-private-value"),
            )
        )
        raw = target.read_text(encoding="ascii")
        self.assertNotIn(gate.FAKE_PLAINTEXT_CREDENTIAL, raw)
        self.assertNotIn("n3-private-value", raw)
        self.assertNotIn("https://private.example", raw)
        saved = json.loads(raw)
        self.assertEqual(saved["credential"], "[REDACTED]")
        self.assertIs(saved["session_revoked"], True)

    def test_redaction_covers_n1_session_challenge_and_cookie_fields(self) -> None:
        redacted = gate.redact_evidence(
            {
                "csrf_nonce": "nonce-private",
                "cookie_value": "cookie-private",
                "session_id": "session-private",
                "session_revoked": True,
                "message": "csrf_nonce=nonce-private authorization=Bearer private",
            }
        )
        self.assertEqual(redacted["csrf_nonce"], "[REDACTED]")  # type: ignore[index]
        self.assertEqual(redacted["cookie_value"], "[REDACTED]")  # type: ignore[index]
        self.assertEqual(redacted["session_id"], "[REDACTED]")  # type: ignore[index]
        self.assertIs(redacted["session_revoked"], True)  # type: ignore[index]
        self.assertNotIn("nonce-private", redacted["message"])  # type: ignore[index]
        self.assertNotIn("private", redacted["message"])  # type: ignore[index]

    def test_dry_run_does_not_create_evidence_or_acquire_lock(self) -> None:
        report = gate.run_preflight(
            self.fixture.dependencies(),
            run_id="n3-dry-run-test",
            expected_sha=TEST_SHA,
            command=["test", "--dry-run"],
            cwd=str(self.root),
            pythonpath=".",
            dry_run=True,
        )
        evidence = self.root / gate.EVIDENCE_BASE / "n3-dry-run-test"
        self.assertEqual(report["preflight_verdict"], "NOT_RUN")
        self.assertEqual(report["gate_verdict"], "PENDING")
        self.assertIs(report["is_gate_pass"], False)
        self.assertFalse(evidence.exists())
        self.assertEqual(self.fixture.lock.calls, [])
        self.assertEqual(self.fixture.inspector.calls, [])
        self.assertEqual(self.fixture.hosts, [])


if __name__ == "__main__":
    unittest.main()
