# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the owned OpenTunnel foreground adapter."""

from __future__ import annotations

import ast
import builtins
import io
import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence
from unittest import mock

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing import native_process_info as process_info
from web.extensions.opentunnel_sharing import profile_state
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    ProfileLayout,
    prepare_profile,
)
from web.extensions.opentunnel_sharing.supervisor import (
    MAX_STARTUP_DEADLINE_SECONDS,
    MAX_STOP_DEADLINE_SECONDS,
    OUTPUT_BUFFER_BYTES,
    Identity,
    OwnedCompanion,
    probe_process_identity,
)
from web.extensions.player.constants import PLAYER_HOST, PLAYER_PORT


class FakeProcess:
    """Inert process substitute with controllable exit and signal behavior."""

    def __init__(
        self,
        *,
        pid: int = 4242,
        output: bytes = b"",
        exit_code: int | None = None,
        ignore_terminate: bool = False,
        ignore_kill: bool = False,
    ) -> None:
        self.pid = pid
        self.output_reader = io.BytesIO(output)
        self.exit_code = exit_code
        self.ignore_terminate = ignore_terminate
        self.ignore_kill = ignore_kill
        self.signals: list[str] = []
        self.wait_calls = 0
        self.reaped = False

    def poll(self) -> int | None:
        return self.exit_code

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.exit_code is None:
            raise subprocess.TimeoutExpired(["fake-opentunnel"], timeout)
        self.reaped = True
        return self.exit_code

    def terminate(self) -> None:
        self.signals.append("terminate")
        if not self.ignore_terminate:
            self.exit_code = 0

    def kill(self) -> None:
        self.signals.append("kill")
        if not self.ignore_kill:
            self.exit_code = -9


class FakeFactory:
    def __init__(
        self,
        process: FakeProcess | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.process = process or FakeProcess()
        self.error = error
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def __call__(
        self, argv: Sequence[str], *, env: Mapping[str, str]
    ) -> FakeProcess:
        self.calls.append((tuple(argv), dict(env)))
        if self.error is not None:
            raise self.error
        return self.process


class OpenTunnelSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        Path("tmp").mkdir(exist_ok=True)
        temporary_directory = tempfile.TemporaryDirectory(dir="tmp")
        self.addCleanup(temporary_directory.cleanup)
        self.scratch = Path(temporary_directory.name)
        self.install_root = self.scratch / "install-root"
        self.install_root.mkdir(mode=0o700)
        self.binary = (
            self.install_root
            / "runtime/opentunnel/v0.6.2/opentunnel-linux-arm64/opentunnel"
        )
        self.binary.parent.mkdir(mode=0o700, parents=True)
        self.binary.write_bytes(b"inert companion fixture")
        self.binary.chmod(0o700)
        self.layout = self._prepare_profile()
        self.resolution = CompanionResolution(
            state="resolved", reason="resolved", path=self.binary
        )

    def _prepare_profile(self) -> ProfileLayout:
        with (
            mock.patch.object(
                profile_state, "_REPOSITORY_ROOT", self.install_root
            ),
            mock.patch.object(profile_state, "_INSTALL_ROOT", self.install_root),
        ):
            result = prepare_profile(
                self.scratch / "state",
                install_marker="test-install-marker",
                profile=DEFAULT_PROFILE,
                create=True,
            )
        self.assertEqual(result.state, "ready")
        assert result.layout is not None
        return result.layout

    def _identity(
        self,
        factory: FakeFactory,
        pid: int,
        *,
        mode: str = "matching",
    ) -> Identity | None:
        if mode == "missing":
            return None
        argv, environment = factory.calls[-1]
        observed_pid = pid + 1 if mode == "wrong_pid" else pid
        creation_token = (
            "other-start-token" if mode == "wrong_creation_token" else "test-start-token"
        )
        executable = str(self.binary)
        if mode == "wrong_executable":
            other = self.scratch / "other-executable"
            other.write_bytes(b"other")
            executable = str(other)
        observed_argv = argv
        if mode == "wrong_profile_args":
            observed_argv = (argv[0], "serve", "--profile", "other-profile")
        observed_environment = dict(environment)
        if mode == "wrong_profile_environment":
            observed_environment["XDG_CONFIG_HOME"] = str(self.scratch / "foreign")
        return Identity(
            pid=observed_pid,
            creation_token=creation_token,
            executable_path=executable,
            argv=observed_argv,
            environment=tuple(observed_environment.items()),
            uid=os.getuid() + 1 if mode == "wrong_uid" else os.getuid(),
        )

    def test_default_identity_probe_uses_native_backend_without_ps(self) -> None:
        if platform.system() not in {"Darwin", "Linux"}:
            self.skipTest("native process backend is unsupported on this platform")
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=AssertionError("default identity probe spawned subprocess"),
        ):
            identity = probe_process_identity(os.getpid())
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.pid, os.getpid())
        self.assertEqual(identity.uid, os.getuid())
        self.assertEqual(identity.start_time is not None, True)
        self.assertNotIn("argv=", repr(identity))

    def test_unknown_executable_candidate_never_proves_owned_identity(self) -> None:
        info = process_info.ProcessInfo(
            pid=4242,
            ppid=1,
            pgid=4242,
            uid=os.getuid(),
            start_time=1_700_000_000.0,
            executable=None,
            argv=(str(self.binary), "serve", "--profile", DEFAULT_PROFILE),
            comm="opentunnel",
        )
        with mock.patch.object(process_info, "lookup", return_value=info):
            self.assertIsNone(probe_process_identity(info.pid))

    def _owner(
        self,
        *,
        process: FakeProcess | None = None,
        factory_error: BaseException | None = None,
        readiness=lambda: True,
        identity_mode: str = "matching",
        identity_probe=None,
    ) -> tuple[OwnedCompanion, FakeFactory, FakeProcess]:
        fake_process = process or FakeProcess()
        factory = FakeFactory(fake_process, error=factory_error)
        if identity_probe is None:
            identity_probe = lambda pid: self._identity(
                factory, pid, mode=identity_mode
            )
        owner = OwnedCompanion(
            self.resolution,
            self.layout,
            readiness,
            process_factory=factory,
            identity_probe=identity_probe,
        )
        return owner, factory, fake_process

    def _assert_reaped_and_drain_joined(self, owner: OwnedCompanion) -> None:
        self.assertTrue(owner.reaped)
        self.assertIsNotNone(owner._drain_thread)
        assert owner._drain_thread is not None
        self.assertFalse(owner._drain_thread.is_alive())
        self.assertTrue(owner._drain_joined)

    def test_launch_failure_is_bounded_and_leaves_no_process(self) -> None:
        owner, factory, _process = self._owner(
            factory_error=OSError("sensitive launch detail")
        )
        self.assertEqual(owner.start(1.0), "failed")
        self.assertEqual(owner.reason_code, "launch_failed")
        self.assertTrue(owner.reaped)
        self.assertEqual(len(factory.calls), 1)

    def test_early_exit_is_reaped_without_signalling(self) -> None:
        process = FakeProcess(exit_code=17, output=b"finished\n")
        owner, _factory, _process = self._owner(process=process)
        self.assertEqual(owner.start(1.0), "failed")
        self.assertEqual(owner.reason_code, "early_exit")
        self.assertEqual(process.signals, [])
        self.assertEqual(process.wait_calls, 1)
        self.assertEqual(owner.diagnostics()["exit_code_bucket"], "failure")
        self._assert_reaped_and_drain_joined(owner)

    def test_startup_timeout_terminates_then_kills_and_reaps(self) -> None:
        process = FakeProcess(ignore_terminate=True)
        owner, _factory, _process = self._owner(
            process=process, readiness=lambda: "pending"
        )
        self.assertEqual(owner.start(0.01), "failed")
        self.assertEqual(owner.reason_code, "startup_timeout")
        self.assertEqual(process.signals, ["terminate", "kill"])
        self.assertTrue(process.reaped)
        self.assertEqual(process.wait_calls, 2)
        self._assert_reaped_and_drain_joined(owner)

    def test_explicit_not_ready_fails_and_cleans_up(self) -> None:
        process = FakeProcess()
        owner, _factory, _process = self._owner(
            process=process, readiness=lambda: "not_ready"
        )
        self.assertEqual(owner.start(1.0), "failed")
        self.assertEqual(owner.reason_code, "not_ready")
        self.assertEqual(process.signals, ["terminate"])
        self._assert_reaped_and_drain_joined(owner)

    def test_successful_start_uses_minimal_env_then_stops_idempotently(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "user-path-sentinel",
                "HOME": "user-home-sentinel",
                "OPENTUNNEL_SECRET": "user-secret-sentinel",
            },
        ):
            owner, factory, process = self._owner()
            self.assertEqual(owner.start(1.0), "running")
        argv, environment = factory.calls[0]
        target = "%s:%d" % (PLAYER_HOST, PLAYER_PORT)
        self.assertEqual(
            argv,
            (str(self.binary.resolve()), "serve", "--profile", DEFAULT_PROFILE),
        )
        self.assertNotIn(target, argv)
        self.assertEqual(
            set(environment),
            {
                "HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_STATE_HOME",
                "XDG_RUNTIME_DIR",
            },
        )
        self.assertNotIn("PATH", environment)
        self.assertNotIn(target, environment.values())
        self.assertNotEqual(environment["HOME"], "user-home-sentinel")
        self.assertNotIn("API_KEY", environment)
        self.assertNotIn("SECRET", environment)
        self.assertNotIn("user-secret-sentinel", repr(environment))
        self.assertNotIn("user-secret-sentinel", repr(argv))
        self.assertEqual(owner.stop(2.0), True)
        self.assertEqual(owner.state, "stopped")
        self.assertEqual(owner.reason_code, None)
        self.assertEqual(process.signals, ["terminate"])
        first_wait_count = process.wait_calls
        self.assertTrue(owner.stop(2.0))
        self.assertEqual(process.wait_calls, first_wait_count)
        self._assert_reaped_and_drain_joined(owner)

    def test_natural_exit_is_reported_and_reaped(self) -> None:
        process = FakeProcess()
        owner, _factory, _process = self._owner(process=process)
        self.assertEqual(owner.start(1.0), "running")
        process.exit_code = 3
        self.assertEqual(owner.state, "exited")
        self.assertEqual(owner.diagnostics()["exit_code_bucket"], "failure")
        self.assertEqual(process.wait_calls, 1)
        self.assertTrue(owner.reaped)
        self.assertEqual(process.signals, [])
        self.assertTrue(owner.stop(1.0))
        self._assert_reaped_and_drain_joined(owner)

    def test_stop_deadline_escalates_to_kill_and_reaps(self) -> None:
        process = FakeProcess(ignore_terminate=True)
        owner, _factory, _process = self._owner(process=process)
        self.assertEqual(owner.start(1.0), "running")
        self.assertTrue(owner.stop(2.0))
        self.assertEqual(process.signals, ["terminate", "kill"])
        self.assertEqual(owner.state, "stopped")
        self.assertTrue(process.reaped)
        self._assert_reaped_and_drain_joined(owner)

    def test_stop_timeout_is_reported_until_the_child_is_reaped(self) -> None:
        process = FakeProcess(ignore_terminate=True, ignore_kill=True)
        owner, _factory, _process = self._owner(process=process)
        self.assertEqual(owner.start(1.0), "running")
        self.assertFalse(owner.stop(0.02))
        self.assertEqual(process.signals, ["terminate", "kill"])
        self.assertEqual(owner.reason_code, "stop_timeout")
        self.assertFalse(owner.reaped)
        process.exit_code = -9
        self.assertTrue(owner.stop(1.0))
        self.assertTrue(owner.reaped)
        self._assert_reaped_and_drain_joined(owner)

    def test_stop_refuses_to_signal_if_identity_changes(self) -> None:
        process = FakeProcess()
        factory = FakeFactory(process)
        identity_calls = 0

        def changed_identity(pid: int) -> Identity | None:
            nonlocal identity_calls
            identity_calls += 1
            mode = "matching" if identity_calls == 1 else "wrong_creation_token"
            return self._identity(factory, pid, mode=mode)

        owner = OwnedCompanion(
            self.resolution,
            self.layout,
            lambda: True,
            process_factory=factory,
            identity_probe=changed_identity,
        )
        self.assertEqual(owner.start(1.0), "running")
        self.assertFalse(owner.stop(1.0))
        self.assertEqual(owner.reason_code, "ownership_mismatch")
        self.assertEqual(process.signals, [])
        process.exit_code = 0
        self.assertTrue(owner.stop(1.0))
        self.assertEqual(process.signals, [])
        self._assert_reaped_and_drain_joined(owner)

    def test_start_ownership_mismatches_never_signal_the_fake(self) -> None:
        for mode in (
            "wrong_executable",
            "wrong_pid",
            "wrong_uid",
            "wrong_profile_args",
            "wrong_profile_environment",
            "missing",
        ):
            with self.subTest(mode=mode):
                process = FakeProcess()
                owner, _factory, _process = self._owner(
                    process=process, identity_mode=mode
                )
                self.assertEqual(owner.start(1.0), "failed")
                self.assertEqual(owner.reason_code, "ownership_mismatch")
                self.assertEqual(process.signals, [])
                process.exit_code = 0
                self.assertTrue(owner.stop(1.0))
                self.assertEqual(process.signals, [])
                self._assert_reaped_and_drain_joined(owner)

    def test_output_is_drained_bounded_and_never_written_or_diagnosed(self) -> None:
        secret_output = (
            b"https://private-route.opentunnel.xyz?token=invitation-token-canary "
            b"PASSWORD=credential-canary COOKIE=cookie-canary "
            b"-----BEGIN PRIVATE KEY-----private-key-canary-----END PRIVATE KEY-----\n"
        )
        output_size = 1024 * 1024
        output = (secret_output * ((output_size + len(secret_output) - 1) // len(secret_output)))[
            :output_size
        ]
        process = FakeProcess(output=output)
        owner, _factory, _process = self._owner(process=process)
        with (
            mock.patch.object(builtins, "open", side_effect=AssertionError("file open")),
            mock.patch.object(os, "write", side_effect=AssertionError("file write")),
        ):
            self.assertEqual(owner.start(1.0), "running")
            assert owner._drain_thread is not None
            owner._drain_thread.join(1.0)
            self.assertFalse(owner._drain_thread.is_alive())
            self.assertTrue(owner.stop(1.0))
        self.assertEqual(len(owner._output_buffer), OUTPUT_BUFFER_BYTES)
        self.assertEqual(owner.diagnostics()["bytes_drained"], output_size)
        diagnostic_text = repr(owner.diagnostics())
        for secret in (
            "private-route",
            "invitation-token-canary",
            "credential-canary",
            "cookie-canary",
            "private-key-canary",
            "BEGIN PRIVATE KEY",
        ):
            self.assertNotIn(secret, diagnostic_text)

    def test_deadlines_must_be_positive_and_bounded(self) -> None:
        owner, factory, _process = self._owner()
        for deadline in (
            0,
            -1,
            MAX_STARTUP_DEADLINE_SECONDS + 1,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(start_deadline=deadline):
                with self.assertRaisesRegex(ValueError, "deadline_out_of_range"):
                    owner.start(deadline)
        self.assertEqual(factory.calls, [])

        owner, factory, _process = self._owner()
        for deadline in (
            0,
            -0.1,
            MAX_STOP_DEADLINE_SECONDS + 1,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(stop_deadline=deadline):
                with self.assertRaisesRegex(ValueError, "deadline_out_of_range"):
                    owner.stop(deadline)
        self.assertEqual(factory.calls, [])

    def test_source_has_no_network_imports_or_shell_execution(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "web/extensions/opentunnel_sharing/supervisor.py"
        )
        source = source_path.read_text(encoding="ascii")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "shell":
                        self.assertFalse(
                            isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True
                        )
        self.assertFalse(imported.intersection({"socket", "urllib", "requests"}))
        self.assertIn("start_new_session=True", source)
        self.assertIn("close_fds=True", source)
        self.assertIn("stdin=subprocess.DEVNULL", source)
        self.assertIn("stderr=subprocess.STDOUT", source)

    # ---- Production start-time readiness probe (real OwnedCompanion) ----

    _CONNECTED_STATUS = (
        "Hostname: account.opentunnel.xyz\n"
        "Service: Connected\n"
        "neq-share.account.opentunnel.xyz -> 127.0.0.1:8370\n"
    )

    def _production_start(
        self,
        results,
        *,
        controller_state=None,
        event_set: bool = False,
        process: FakeProcess | None = None,
        deadline: float = 1.0,
        layout_override: ProfileLayout | None = None,
        recover: bool = False,
    ):
        """Start a real OwnedCompanion through the production probe wiring.

        ``results`` is a list of RunResult values (the last one repeats) or
        an Exception to raise from the fake command runner.
        """
        from web.extensions.opentunnel_sharing import service
        from web.extensions.opentunnel_sharing.controller import SharingState

        composition = service._ProductionComposition(
            object(),  # type: ignore[arg-type]
            lambda: True,
            companion_manifest=None,
            install_root=self.install_root,
            state_root=self.scratch / "state",
            state_root_provider=None,
            install_marker=None,
            profile=DEFAULT_PROFILE,
            player_build_root=None,
        )
        calls: list[tuple[str, ...]] = []

        class FakeRunner:
            def __call__(self, argv, env, timeout):
                calls.append(tuple(argv))
                if isinstance(results, BaseException):
                    raise results
                index = min(len(calls) - 1, len(results) - 1)
                return results[index]

        composition._runner = FakeRunner()  # type: ignore[assignment]
        fake_process = process or FakeProcess()
        factory = FakeFactory(fake_process)
        resolution = CompanionResolution(
            state="resolved",
            reason="resolved",
            path=self.binary,
            expected_sha256="0" * 64,
        )
        probe_layout = layout_override or self.layout

        def owned(res, layout, probe):
            return OwnedCompanion(
                res,
                layout,
                probe,
                process_factory=factory,
                identity_probe=lambda pid: self._identity(factory, pid),
            )

        with (
            mock.patch.object(
                composition, "_resolve_companion", return_value=resolution
            ),
            mock.patch.object(service, "verify_companion_digest", return_value=True),
            mock.patch.object(
                service._ProfileRouteTable, "ensure", return_value=True
            ),
            mock.patch.object(service, "OwnedCompanion", owned),
        ):
            controller = composition._controller_factory(probe_layout)
            if recover:
                from dataclasses import replace

                from web.extensions.opentunnel_sharing.controller import (
                    SharingState as _State,
                )

                # Drive the real recovery restart: DEGRADED, no prior handle.
                # Cleanup is dropped so no owner record is written for the fake.
                controller._deps = replace(controller._deps, cleanup=None)
                controller._generation = 1
                controller._state = _State.DEGRADED
                controller._companion = None
                self.recovery_result = controller._restart_companion_for_recovery(
                    1, controller._lifecycle_revision
                )
                handle = controller._companion
            else:
                handle = controller._deps.start_companion(1)
        if recover:
            return composition, controller, handle, calls, fake_process
        self.assertIsNotNone(handle)
        # Drive the controller into the state a real start would hold.
        controller._generation = 1
        controller._state = (
            SharingState.STARTING if controller_state is None else controller_state
        )
        if event_set:
            import threading

            event = threading.Event()
            event.set()
            controller._active_start_event = event
        return composition, controller, handle, calls, fake_process

    def test_production_probe_runs_status_while_starting_and_reaches_running(
        self,
    ) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        _c, _controller, handle, calls, _p = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)]
        )
        self.assertEqual(handle.start(1.0), "running")
        self.assertEqual(handle.state, "running")
        self.assertGreaterEqual(len(calls), 1)
        self.assertEqual(
            calls[0], (str(self.binary), "status", "--profile", DEFAULT_PROFILE)
        )
        handle.stop(1.0)

    def test_production_probe_negative_statuses_stay_pending_then_time_out(
        self,
    ) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        cases = {
            "not_connected": [
                RunResult(0, "Service: Disconnected\n")
            ],
            "unparseable": [RunResult(0, "garbage output\n")],
            "timed_out": [RunResult(None, "", timed_out=True)],
            "truncated": [
                RunResult(0, self._CONNECTED_STATUS, output_truncated=True)
            ],
            "nonzero_exit": [RunResult(2, self._CONNECTED_STATUS)],
            "runner_raises": RuntimeError("runner broke"),
        }
        for name, results in cases.items():
            with self.subTest(case=name):
                _c, _controller, handle, calls, _p = self._production_start(
                    results
                )
                self.assertEqual(handle.start(0.3), "failed")
                self.assertEqual(handle.reason_code, "startup_timeout")
                self.assertGreaterEqual(len(calls), 1)

    def test_production_probe_never_runs_status_on_layout_mismatch(self) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        _c, _controller, handle, calls, _p = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)]
        )
        # The probe was wired for self.layout; present a different layout.
        other = mock.Mock(spec=[])
        with mock.patch.object(
            type(handle), "profile_layout", new=property(lambda _s: other)
        ):
            self.assertEqual(handle.start(0.3), "failed")
        self.assertEqual(handle.reason_code, "startup_timeout")
        self.assertEqual(calls, [])

    def test_production_probe_never_runs_status_when_start_not_current(
        self,
    ) -> None:
        from web.extensions.opentunnel_sharing.controller import SharingState
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        scenarios = {
            "stopping": {"controller_state": SharingState.STOPPING},
            "cancel_event_set": {"event_set": True},
            "off": {"controller_state": SharingState.OFF},
        }
        for name, options in scenarios.items():
            with self.subTest(scenario=name):
                _c, _controller, handle, calls, _p = self._production_start(
                    [RunResult(0, self._CONNECTED_STATUS)], **options
                )
                self.assertEqual(handle.start(0.3), "failed")
                self.assertEqual(calls, [])

    def test_production_probe_shutdown_never_runs_status(self) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        _c, controller, handle, calls, _p = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)]
        )
        controller._shutdown_requested = True
        self.assertEqual(handle.start(0.3), "failed")
        self.assertEqual(calls, [])

    def test_production_probe_wrong_generation_never_runs_status(self) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        _c, controller, handle, calls, _p = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)]
        )
        controller._generation = 2
        self.assertEqual(handle.start(0.3), "failed")
        self.assertEqual(calls, [])

    def test_production_probe_exited_process_is_early_exit_without_ready(
        self,
    ) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        _c, _controller, handle, calls, _p = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)],
            process=FakeProcess(exit_code=3),
        )
        self.assertEqual(handle.start(1.0), "failed")
        self.assertEqual(handle.reason_code, "early_exit")
        self.assertEqual(calls, [])

    def test_start_route_status_refuses_a_process_that_exited_mid_probe(
        self,
    ) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        composition, _controller, handle, calls, process = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)]
        )
        handle._state = "starting"
        handle._process = process
        process.exit_code = 9
        status = composition._start_route_status(
            handle, 1, self.layout, lambda _generation: True
        )
        self.assertFalse(status.healthy)
        self.assertEqual(calls, [])
        for state in ("failed", "stopped", "exited"):
            with self.subTest(state=state):
                process.exit_code = None
                handle._state = state
                self.assertFalse(
                    composition._start_route_status(
                        handle, 1, self.layout, lambda _generation: True
                    ).healthy
                )
        self.assertEqual(calls, [])

    def test_recovery_restart_runs_status_while_degraded_and_reaches_running(
        self,
    ) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        _c, controller, handle, calls, _p = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)], recover=True
        )
        self.assertTrue(self.recovery_result)
        self.assertEqual(handle.state, "running")
        self.assertGreaterEqual(len(calls), 1)
        self.assertEqual(controller._counters.companion_launches, 1)
        handle.stop(1.0)

    def test_recovery_probe_negatives_in_degraded_never_run_status(self) -> None:
        from web.extensions.opentunnel_sharing.controller import SharingState
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        status = [RunResult(0, self._CONNECTED_STATUS)]
        scenarios = {
            "stop_requested": {"controller_state": SharingState.STOPPING},
            "failed": {"controller_state": SharingState.FAILED},
            "ready": {"controller_state": SharingState.READY},
            "event_set": {
                "controller_state": SharingState.DEGRADED,
                "event_set": True,
            },
        }
        for name, options in scenarios.items():
            with self.subTest(scenario=name):
                _c, _controller, handle, calls, _p = self._production_start(
                    status, **options
                )
                self.assertEqual(handle.start(0.3), "failed")
                self.assertEqual(calls, [])
        with self.subTest(scenario="shutdown"):
            _c, controller, handle, calls, _p = self._production_start(
                status, controller_state=SharingState.DEGRADED
            )
            controller._shutdown_requested = True
            self.assertEqual(handle.start(0.3), "failed")
            self.assertEqual(calls, [])
        with self.subTest(scenario="wrong_generation"):
            _c, controller, handle, calls, _p = self._production_start(
                status, controller_state=SharingState.DEGRADED
            )
            controller._generation = 2
            self.assertEqual(handle.start(0.3), "failed")
            self.assertEqual(calls, [])
        with self.subTest(scenario="exited_process"):
            _c, _controller, handle, calls, _p = self._production_start(
                status,
                controller_state=SharingState.DEGRADED,
                process=FakeProcess(exit_code=3),
            )
            self.assertEqual(handle.start(1.0), "failed")
            self.assertEqual(handle.reason_code, "early_exit")
            self.assertEqual(calls, [])
        with self.subTest(scenario="layout_mismatch"):
            _c, _controller, handle, calls, _p = self._production_start(
                status, controller_state=SharingState.DEGRADED
            )
            other = mock.Mock(spec=[])
            with mock.patch.object(
                type(handle), "profile_layout", new=property(lambda _s: other)
            ):
                self.assertEqual(handle.start(0.3), "failed")
            self.assertEqual(calls, [])

    def test_strict_route_status_still_rejects_a_starting_handle(self) -> None:
        from web.extensions.opentunnel_sharing.identity_bootstrap import RunResult

        composition, _controller, handle, calls, process = self._production_start(
            [RunResult(0, self._CONNECTED_STATUS)]
        )
        handle._state = "starting"
        handle._process = process
        self.assertFalse(composition._route_status(handle, 1, self.layout).healthy)
        self.assertEqual(calls, [])
        handle._state = "running"
        self.assertTrue(composition._route_status(handle, 1, self.layout).healthy)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
