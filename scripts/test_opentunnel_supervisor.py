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
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence
from unittest import mock

from web.extensions.opentunnel_sharing.companion import CompanionResolution
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
        )

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


if __name__ == "__main__":
    unittest.main()
