# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the explicit OpenTunnel identity bootstrap."""

from __future__ import annotations

import ast
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence
from unittest import mock

from web.extensions.opentunnel_sharing import identity_bootstrap
from web.extensions.opentunnel_sharing import native_process_info as process_info
from web.extensions.opentunnel_sharing import profile_state
from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.identity_bootstrap import (
    BOOTSTRAP_MARKER_FILENAME,
    BOOTSTRAP_SCHEMA,
    DefaultCommandRunner,
    DefaultIdentityObserver,
    Observation,
    ProcessEvidence,
    RunResult,
    StatusEvidence,
    _assess_observations,
    bootstrap_identity,
    parse_identity_status,
    parse_launchctl_entries,
    parse_launchctl_print_services,
    parse_linux_process_record,
    parse_ps_processes,
    parse_systemd_unit_files,
    redact,
)
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    ProfileLayout,
    companion_environment,
    prepare_profile,
)


STATUS_RUNNING = (
    "Hostname: identity-fixture.opentunnel.xyz\n"
    "Tunnel ID: fixture-tunnel-id\n"
    "Service: Connected PID 4242\n"
)
STATUS_STOPPED = (
    "Hostname: identity-fixture.opentunnel.xyz\n"
    "Tunnel ID: fixture-tunnel-id\n"
    "Service: Stopped\n"
)
SERVICE_ABSENT = Observation("absent", "observed_user_view")
PROCESS_ABSENT = Observation("absent", "proc_scan_complete")
HELPER_ABSENT = Observation("absent", "ps_snapshot_complete")
LAUNCHCTL_PRINT_FIXTURE = (
    "gui = {\n"
    "\tservices = {\n"
    "\t\t   64868      1 \tcom.apple.example\n"
    "\t\t     976      - \tcom.apple.helper\n"
    "\t\t       0      0 \tcom.apple.disabled\n"
    "\t\t   90375   (pe) \tcom.apple.peer\n"
    "\t\t   21538   (jt) \tcom.apple.job\n"
    "\t\t   60196    -10 \tcom.apple.exit\n"
    "\t}\n"
    "\tdisabled services = {\n"
    "\t}\n"
)


class FakeRunner:
    """Inert runner that records argv/environment without launching processes."""

    def __init__(
        self,
        results: Sequence[RunResult] | None = None,
        *,
        status_output: str = STATUS_RUNNING,
        event_log: list[str] | None = None,
    ) -> None:
        self.results = list(results or ())
        self.status_output = status_output
        self.calls: list[tuple[tuple[str, ...], dict[str, str], float]] = []
        self.event_log = event_log if event_log is not None else []

    def __call__(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        timeout: float,
    ) -> RunResult:
        selected_argv = tuple(argv)
        self.calls.append((selected_argv, dict(env), timeout))
        command = selected_argv[-1]
        self.event_log.append(command)
        index = len(self.calls) - 1
        if index < len(self.results):
            return self.results[index]
        if command == "status":
            return RunResult(0, self.status_output)
        return RunResult(0, "runner-output-sentinel")


class FakeObserver:
    """Deterministic pre/post snapshots with no OS calls."""

    def __init__(
        self,
        *,
        pre: tuple[Observation, Observation, Observation]
        | None = None,
        post: tuple[Observation, Observation, Observation]
        | None = None,
        event_log: list[str] | None = None,
    ) -> None:
        self.pre = pre or (SERVICE_ABSENT, PROCESS_ABSENT, HELPER_ABSENT)
        self.post = post or (SERVICE_ABSENT, PROCESS_ABSENT, HELPER_ABSENT)
        self.event_log = event_log if event_log is not None else []
        self.calls: list[str] = []
        self._phase = "pre"

    def _next(self, kind: str, index: int) -> Observation:
        self.calls.append(self._phase + ":" + kind)
        self.event_log.append(self._phase + ":" + kind)
        values = self.pre if self._phase == "pre" else self.post
        return values[index]

    def service_manager_entries(self, profile: str) -> Observation:
        self._check_profile(profile)
        return self._next("service", 0)

    def profile_processes(self, profile: str) -> Observation:
        self._check_profile(profile)
        return self._next("process", 1)

    def helper_processes(self) -> Observation:
        return self._next("helper", 2)

    def switch_to_post(self) -> None:
        self._phase = "post"

    @staticmethod
    def _check_profile(profile: str) -> None:
        if profile != DEFAULT_PROFILE:
            raise AssertionError("unexpected profile")


class BootstrapRunner(FakeRunner):
    """Switch the fake observer to its post-down snapshot on down."""

    def __init__(self, observer: FakeObserver, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.observer = observer

    def __call__(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        timeout: float,
    ) -> RunResult:
        result = super().__call__(argv, env, timeout)
        if tuple(argv)[-1] == "down":
            self.observer.switch_to_post()
        return result


class OpenTunnelIdentityBootstrapTests(unittest.TestCase):
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
        self.binary.write_bytes(b"inert identity bootstrap companion")
        self.binary.chmod(0o700)
        with self._profile_state_roots():
            profile = prepare_profile(
                self.scratch / "state",
                install_marker="bootstrap-test-install",
                profile=DEFAULT_PROFILE,
                create=True,
            )
        self.assertEqual(profile.state, "ready")
        assert profile.layout is not None
        self.layout: ProfileLayout = profile.layout
        self.resolution = CompanionResolution(
            state="resolved", reason="resolved", path=self.binary
        )

    def _profile_state_roots(self):
        return mock.patch.multiple(
            profile_state,
            _REPOSITORY_ROOT=self.install_root,
            _INSTALL_ROOT=self.install_root,
        )

    def _run(
        self,
        *,
        runner: FakeRunner | None = None,
        observer: FakeObserver | None = None,
        confirmed: bool = True,
        **kwargs: object,
    ):
        selected_observer = observer or FakeObserver()
        selected_runner = runner or BootstrapRunner(selected_observer)
        with self._profile_state_roots():
            result = bootstrap_identity(
                self.layout,
                self.resolution,
                runner=selected_runner,
                observer=selected_observer,
                facilitator_confirmed=confirmed,
                **kwargs,
            )
        return result, selected_runner, selected_observer

    def _marker_path(self) -> Path:
        return self.layout.state_home / BOOTSTRAP_MARKER_FILENAME

    def _assert_no_marker(self) -> None:
        self.assertFalse(self._marker_path().exists())

    def _assert_runner_environment(self, runner: FakeRunner) -> None:
        expected_keys = {
            "PATH",
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_RUNTIME_DIR",
        }
        expected = companion_environment(self.layout)
        expected["PATH"] = ""
        self.assertGreaterEqual(len(runner.calls), 1)
        for _argv, environment, _timeout in runner.calls:
            self.assertEqual(set(environment), expected_keys)
            self.assertEqual(environment, expected)
            self.assertEqual(environment["PATH"], "")

    def test_confirmation_is_exact_and_unconfirmed_runs_nothing(self) -> None:
        for value in (False, None, 1, "true"):
            with self.subTest(value=value):
                result, runner, observer = self._run(confirmed=value)  # type: ignore[arg-type]
                self.assertEqual(result.state, "not_confirmed")
                self.assertEqual(runner.calls, [])
                self.assertEqual(observer.calls, [])
                self._assert_no_marker()

    def test_happy_path_is_guarded_up_status_down_and_marker_is_atomic_private_state(self) -> None:
        event_log: list[str] = []
        observer = FakeObserver(event_log=event_log)
        runner = BootstrapRunner(observer, event_log=event_log)
        result, runner, observer = self._run(runner=runner, observer=observer)

        self.assertEqual(result.state, "initialized")
        self.assertEqual(result.reason, "identity_initialized")
        binary = str(self.binary.resolve())
        self.assertEqual(
            [call[0] for call in runner.calls],
            [
                (binary, "--profile", DEFAULT_PROFILE, "up"),
                (binary, "--profile", DEFAULT_PROFILE, "status"),
                (binary, "--profile", DEFAULT_PROFILE, "down"),
            ],
        )
        self.assertEqual(
            event_log,
            [
                "pre:service",
                "pre:process",
                "pre:helper",
                "up",
                "status",
                "down",
                "post:service",
                "post:process",
                "post:helper",
            ],
        )
        self._assert_runner_environment(runner)
        self.assertEqual(len(observer.calls), 6)
        marker = self._marker_path()
        metadata = marker.lstat()
        self.assertTrue(stat.S_ISREG(metadata.st_mode))
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.assertEqual(metadata.st_uid, os.getuid())
        payload = json.loads(marker.read_text(encoding="ascii"))
        self.assertEqual(set(payload), {"schema", "profile", "completed_at"})
        self.assertEqual(payload["schema"], BOOTSTRAP_SCHEMA)
        self.assertEqual(payload["profile"], DEFAULT_PROFILE)
        self.assertTrue(payload["completed_at"].endswith("Z"))
        self.assertFalse(any(marker.parent.glob(".identity_bootstrap.*.tmp")))

    def test_native_process_census_absence_initializes_through_fake_harness(self) -> None:
        native_absent = Observation("absent", "native_process_info_complete")
        observer = FakeObserver(
            pre=(SERVICE_ABSENT, native_absent, native_absent),
            post=(SERVICE_ABSENT, native_absent, native_absent),
        )
        result, runner, _observer = self._run(observer=observer)

        self.assertEqual(result.state, "initialized")
        self.assertEqual(result.reason, "identity_initialized")
        self.assertEqual([call[0][-1] for call in runner.calls], ["up", "status", "down"])

    def test_native_process_census_absence_requires_complete_empty_evidence(self) -> None:
        native_absent = Observation("absent", "native_process_info_complete")
        self.assertEqual(
            _assess_observations(
                (
                    ("service", SERVICE_ABSENT),
                    ("process", native_absent),
                    ("helper", native_absent),
                )
            ),
            "absent",
        )

        cases = (
            Observation("absent", "native_process_info_complete", 1),
            Observation(
                "absent",
                "native_process_info_complete",
                0,
                (ProcessEvidence(True, True, True),),
            ),
            Observation("absent", "unknown_native_basis"),
            Observation(
                "present",
                "native_process_info_complete",
                1,
                (ProcessEvidence(False, True, True),),
            ),
        )
        for observation in cases:
            with self.subTest(observation=observation):
                self.assertEqual(
                    _assess_observations((("process", observation),)), "unknown"
                )

    def test_valid_marker_is_once_per_profile_and_skips_all_observers_and_commands(self) -> None:
        first, _runner, _observer = self._run()
        self.assertEqual(first.state, "initialized")
        result, runner, observer = self._run()
        self.assertEqual(result.state, "already_initialized")
        self.assertEqual(runner.calls, [])
        self.assertEqual(observer.calls, [])

    def test_preexisting_service_entry_fails_without_invoking_companion(self) -> None:
        observer = FakeObserver(
            pre=(Observation("present", "observed_user_view", 1), PROCESS_ABSENT, HELPER_ABSENT)
        )
        result, runner, _observer = self._run(observer=observer)
        self.assertEqual(result.state, "residual_found")
        self.assertEqual(runner.calls, [])
        self._assert_no_marker()

    def test_preexisting_daemon_is_left_untouched(self) -> None:
        observer = FakeObserver(
            pre=(
                SERVICE_ABSENT,
                Observation(
                    "present",
                    "proc_scan_complete",
                    1,
                    (ProcessEvidence(True, True, True),),
                ),
                HELPER_ABSENT,
            )
        )
        result, runner, _observer = self._run(observer=observer)
        self.assertEqual(result.state, "residual_found")
        self.assertEqual(runner.calls, [])
        self._assert_no_marker()

    def test_post_down_owned_process_or_helper_is_residual_and_never_cleaned_up(self) -> None:
        cases = (
            (
                "profile_process",
                (SERVICE_ABSENT, Observation("present", "proc_scan_complete", 1, (ProcessEvidence(True, True, True),)), HELPER_ABSENT),
            ),
            (
                "helper_process",
                (SERVICE_ABSENT, PROCESS_ABSENT, Observation("present", "ps_snapshot_complete", 1, (ProcessEvidence(True, True, True),))),
            ),
        )
        for name, post in cases:
            with self.subTest(name=name):
                observer = FakeObserver(post=post)
                result, runner, _observer = self._run(observer=observer)
                self.assertEqual(result.state, "residual_found")
                self.assertEqual([call[0][-1] for call in runner.calls], ["up", "status", "down"])
                self._assert_no_marker()

    def test_unknown_observer_and_ownership_mismatches_fail_closed(self) -> None:
        cases = (
            ("unknown", Observation("unknown", "observation_failed")),
            ("executable_mismatch", ProcessEvidence(False, True, True)),
            ("profile_mismatch", ProcessEvidence(True, False, True)),
            ("uid_mismatch", ProcessEvidence(True, True, False)),
        )
        for name, evidence in cases:
            with self.subTest(name=name):
                if name == "unknown":
                    observer = FakeObserver(
                        pre=(evidence, PROCESS_ABSENT, HELPER_ABSENT)  # type: ignore[arg-type]
                    )
                else:
                    observer = FakeObserver(
                        post=(
                            SERVICE_ABSENT,
                            Observation("present", "proc_scan_complete", 1, (evidence,)),  # type: ignore[arg-type]
                            HELPER_ABSENT,
                        )
                    )
                result, runner, _observer = self._run(observer=observer)
                self.assertEqual(result.state, "uncertain")
                self.assertNotIn("kill", [call[0][-1] for call in runner.calls])
                self._assert_no_marker()

    def test_up_nonzero_and_timeout_allow_only_one_down_after_positive_status(self) -> None:
        for name, up in (
            ("nonzero", RunResult(17, "up-failure-sentinel")),
            ("timeout", RunResult(None, "", timed_out=True)),
        ):
            with self.subTest(name=name):
                observer = FakeObserver()
                runner = BootstrapRunner(observer, results=(up,))
                result, runner, _observer = self._run(runner=runner, observer=observer)
                self.assertEqual(result.state, "failed")
                self.assertEqual(result.reason, "up_failed")
                self.assertEqual([call[0][-1] for call in runner.calls], ["up", "status", "down"])
                self._assert_no_marker()

    def test_failed_up_without_positive_status_does_not_issue_down(self) -> None:
        observer = FakeObserver()
        runner = BootstrapRunner(
            observer,
            results=(RunResult(17, "up-failure"),),
            status_output=STATUS_STOPPED,
        )
        result, runner, _observer = self._run(runner=runner, observer=observer)
        self.assertEqual(result.state, "uncertain")
        self.assertEqual([call[0][-1] for call in runner.calls], ["up", "status"])
        self._assert_no_marker()

    def test_status_without_running_identity_does_not_issue_down(self) -> None:
        observer = FakeObserver()
        runner = BootstrapRunner(observer, status_output=STATUS_STOPPED)
        result, runner, _observer = self._run(runner=runner, observer=observer)
        self.assertEqual(result.state, "uncertain")
        self.assertEqual(result.reason, "status_unproven")
        self.assertEqual([call[0][-1] for call in runner.calls], ["up", "status"])
        self._assert_no_marker()

    def test_status_timeout_and_down_failure_do_not_write_marker(self) -> None:
        observer = FakeObserver()
        runner = BootstrapRunner(
            observer,
            results=(RunResult(0, ""), RunResult(None, "", timed_out=True)),
        )
        result, runner, _observer = self._run(runner=runner, observer=observer)
        self.assertEqual(result.state, "uncertain")
        self.assertEqual([call[0][-1] for call in runner.calls], ["up", "status"])
        self._assert_no_marker()

        observer = FakeObserver()
        runner = BootstrapRunner(
            observer,
            results=(RunResult(0, ""), RunResult(0, STATUS_RUNNING), RunResult(9, "down-failure")),
        )
        result, runner, _observer = self._run(runner=runner, observer=observer)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.reason, "down_failed")
        self.assertEqual([call[0][-1] for call in runner.calls], ["up", "status", "down"])
        self._assert_no_marker()

    def test_invalid_and_unsafe_markers_are_untouched_and_never_run_commands(self) -> None:
        marker = self._marker_path()
        variants = ("corrupt", "wrong_mode", "symlink", "wrong_schema")
        for variant in variants:
            with self.subTest(variant=variant):
                if marker.exists() or marker.is_symlink():
                    marker.unlink()
                outside = self.scratch / "outside-marker"
                if outside.exists():
                    outside.unlink()
                if variant == "corrupt":
                    marker.write_bytes(b"not-json")
                elif variant == "wrong_mode":
                    marker.write_text("{}", encoding="ascii")
                    marker.chmod(0o644)
                elif variant == "symlink":
                    outside.write_text("external-sentinel", encoding="ascii")
                    outside.chmod(0o600)
                    marker.symlink_to(outside)
                else:
                    marker.write_text(
                        json.dumps(
                            {
                                "schema": "wrong.schema",
                                "profile": DEFAULT_PROFILE,
                                "completed_at": "2026-01-01T00:00:00Z",
                            }
                        ),
                        encoding="ascii",
                    )
                    marker.chmod(0o600)
                before = self._snapshot(marker)
                result, runner, observer = self._run()
                self.assertEqual(result.state, "marker_invalid")
                self.assertEqual(runner.calls, [])
                self.assertEqual(observer.calls, [])
                self.assertEqual(self._snapshot(marker), before)
                if variant == "symlink":
                    self.assertEqual(outside.read_text(encoding="ascii"), "external-sentinel")

    def test_redacts_url_hosts_tunnel_ids_hex_and_base64_tokens(self) -> None:
        hex_token = "a" * 64
        base64_token = "AbCdEFghIJklMNopQRstUVwxYZ0123456789-_=="
        sample = (
            "url=https://private-route.example.com/path?token=abc "
            "host=private-route.example.com Tunnel ID=tunnel-sentinel-77 "
            "hex=" + hex_token + " b64=" + base64_token
        )
        result = redact(sample)
        for sentinel in (
            "private-route.example.com",
            "tunnel-sentinel-77",
            hex_token,
            base64_token,
        ):
            self.assertNotIn(sentinel, result)
        self.assertIn("<url>", result)
        self.assertIn("<redacted-token>", result)

    def test_secret_bearing_runner_output_never_reaches_result_or_marker(self) -> None:
        output = (
            "https://private-route.example.com Tunnel ID=credential-tunnel-id "
            "TOKEN=credential-token-sentinel "
            "COOKIE=session-cookie-canary "
            "PRIVATE_KEY=private-key-canary "
            "-----BEGIN PRIVATE KEY-----private-key-body-canary-----END PRIVATE KEY----- "
            "control=\x1b[31mredacted-test\x00 "
            + "b" * 64
        )
        observer = FakeObserver()
        runner = BootstrapRunner(
            observer,
            results=(RunResult(0, output), RunResult(0, STATUS_RUNNING + output), RunResult(0, output)),
        )
        result, _runner, _observer = self._run(runner=runner, observer=observer)
        self.assertEqual(result.state, "initialized")
        result_text = repr(result) + repr(result.facts)
        disk_text = "".join(
            path.read_text(encoding="ascii", errors="replace")
            for path in self.layout.profile_root.rglob("*")
            if path.is_file()
        )
        for sentinel in (
            "private-route.example.com",
            "credential-tunnel-id",
            "credential-token-sentinel",
            "session-cookie-canary",
            "private-key-canary",
            "private-key-body-canary",
            "\x1b[31mredacted-test\x00",
            "b" * 64,
        ):
            self.assertNotIn(sentinel, result_text)
            self.assertNotIn(sentinel, disk_text)

    def test_status_parser_requires_identity_and_running_pid_without_retaining_values(self) -> None:
        parsed = parse_identity_status(STATUS_RUNNING)
        self.assertEqual(parsed, StatusEvidence(True, True))
        self.assertEqual(parse_identity_status(STATUS_STOPPED), StatusEvidence(True, False))
        self.assertEqual(
            parse_identity_status("Hostname: invalid.example.org\nTunnel ID: x\nService: Connected PID 1"),
            StatusEvidence(False, True),
        )
        self.assertEqual(parse_identity_status("x" * (64 * 1024 + 1)), StatusEvidence(False, False))

    def test_service_manager_fixture_parsers_are_profile_scoped(self) -> None:
        launchctl = "PID\tStatus\tLabel\n-\t0\tcom.opentunnel.neq-share\n"
        systemd = (
            "UNIT FILE\tSTATE\tPRESET\n"
            "opentunnel-neq-share.service enabled enabled\n"
        )
        self.assertEqual(parse_launchctl_entries(launchctl, DEFAULT_PROFILE).state, "present")
        self.assertEqual(parse_systemd_unit_files(systemd, DEFAULT_PROFILE).state, "present")
        self.assertEqual(parse_launchctl_entries(launchctl, "other-profile").state, "absent")
        self.assertEqual(parse_systemd_unit_files(systemd, "other-profile").state, "absent")
        self.assertEqual(parse_launchctl_entries("x" * (64 * 1024 + 1), DEFAULT_PROFILE).state, "unknown")

    def test_launchctl_print_parser_reads_only_one_complete_services_block(self) -> None:
        absent = parse_launchctl_print_services(
            "outside opentunnel neq-share\n" + LAUNCHCTL_PRINT_FIXTURE,
            DEFAULT_PROFILE,
        )
        self.assertEqual(absent, Observation("absent", "observed_user_view"))

        by_label = parse_launchctl_print_services(
            LAUNCHCTL_PRINT_FIXTURE.replace(
                "com.apple.peer", "com.vendor.OpenTunnel.agent"
            ),
            DEFAULT_PROFILE,
        )
        self.assertEqual(by_label, Observation("present", "observed_user_view", 1))

        by_profile = parse_launchctl_print_services(
            LAUNCHCTL_PRINT_FIXTURE.replace(
                "com.apple.peer", "com.vendor.NEQ-SHARE.agent"
            ),
            DEFAULT_PROFILE,
        )
        self.assertEqual(by_profile, Observation("present", "observed_user_view", 1))

    def test_launchctl_print_parser_returns_unknown_for_incomplete_or_ambiguous_data(self) -> None:
        unknown = Observation("unknown", "invalid_observation")
        self.assertEqual(parse_launchctl_print_services("gui = {}\n", DEFAULT_PROFILE), unknown)
        self.assertEqual(
            parse_launchctl_print_services(
                "\tservices = {\n\t}\n", DEFAULT_PROFILE
            ),
            unknown,
        )
        self.assertEqual(
            parse_launchctl_print_services(
                LAUNCHCTL_PRINT_FIXTURE.split("\t}\n", 1)[0] + "\n",
                DEFAULT_PROFILE,
            ),
            unknown,
        )
        self.assertEqual(
            parse_launchctl_print_services(
                LAUNCHCTL_PRINT_FIXTURE + LAUNCHCTL_PRINT_FIXTURE,
                DEFAULT_PROFILE,
            ),
            unknown,
        )
        invalid_row = LAUNCHCTL_PRINT_FIXTURE.replace(
            "\t\t   64868      1 \tcom.apple.example",
            "\t\t invalid row",
        )
        self.assertEqual(
            parse_launchctl_print_services(invalid_row, DEFAULT_PROFILE), unknown
        )
        self.assertEqual(
            parse_launchctl_print_services(
                "x" * (identity_bootstrap.MAX_LAUNCHCTL_PRINT_OUTPUT_BYTES + 1),
                DEFAULT_PROFILE,
            ),
            unknown,
        )

    def test_default_macos_service_observer_uses_bounded_print_gui_command(self) -> None:
        calls: list[tuple[tuple[str, ...], Mapping[str, str], float]] = []
        large_output = (
            "x" * (identity_bootstrap.MAX_COMMAND_OUTPUT_CHARS + 1)
            + "\n"
            + LAUNCHCTL_PRINT_FIXTURE
        )

        def runner(
            argv: Sequence[str], env: Mapping[str, str], timeout: float
        ) -> RunResult:
            calls.append((tuple(argv), dict(env), timeout))
            return RunResult(0, large_output)

        with mock.patch.object(Path, "is_file", return_value=True):
            observer = DefaultIdentityObserver(
                self.layout,
                self.binary,
                command_runner=runner,
                system_name="Darwin",
            )
            result = observer.service_manager_entries(DEFAULT_PROFILE)

        self.assertEqual(result, Observation("absent", "observed_user_view"))
        self.assertEqual(len(calls), 1)
        argv, env, timeout = calls[0]
        self.assertEqual(argv, ("/bin/launchctl", "print", "gui/%d" % os.getuid()))
        self.assertEqual(env["PATH"], "")
        self.assertEqual(env["HOME"], str(self.layout.data_home))
        self.assertEqual(timeout, 10.0)
        self.assertEqual(
            observer._output_limit,
            identity_bootstrap.MAX_LAUNCHCTL_PRINT_OUTPUT_BYTES,
        )

    def test_default_macos_service_observer_rejects_failed_launchctl_print(self) -> None:
        for failed_result in (
            RunResult(1, "launchctl failed"),
            RunResult(None, "partial output", timed_out=True),
            RunResult(0, LAUNCHCTL_PRINT_FIXTURE, output_truncated=True),
        ):
            with self.subTest(result=failed_result), mock.patch.object(
                Path, "is_file", return_value=True
            ):
                observer = DefaultIdentityObserver(
                    self.layout,
                    self.binary,
                    command_runner=lambda _argv, _env, _timeout: failed_result,
                    system_name="Darwin",
                )
                result = observer.service_manager_entries(DEFAULT_PROFILE)
            self.assertEqual(result.state, "unknown")

    def test_empty_path_basis_requires_positive_resolution_check_and_no_manager_proof(self) -> None:
        calls: list[tuple[str, str | None]] = []

        def missing_from_path(command: str, path: str | None = None) -> None:
            calls.append((command, path))
            return None

        observer = DefaultIdentityObserver(
            self.layout,
            self.binary,
            command_runner=lambda _argv, _env, _timeout: RunResult(1, ""),
            system_name="Linux",
        )
        with (
            mock.patch("web.extensions.opentunnel_sharing.identity_bootstrap.shutil.which", side_effect=missing_from_path),
            mock.patch("web.extensions.opentunnel_sharing.identity_bootstrap._linux_no_service_manager_proof", return_value=True),
        ):
            absent = observer.service_manager_entries(DEFAULT_PROFILE)
        self.assertEqual(absent, Observation("absent", "unresolvable_on_empty_path"))
        self.assertIn(("systemctl", ""), calls)

        calls.clear()

        def available_outside_empty_path(command: str, path: str | None = None) -> str | None:
            calls.append((command, path))
            return "/usr/bin/systemctl" if path == os.defpath else None

        observer = DefaultIdentityObserver(
            self.layout,
            self.binary,
            command_runner=lambda _argv, _env, _timeout: RunResult(1, "manager-unavailable"),
            system_name="Linux",
        )
        with (
            mock.patch("web.extensions.opentunnel_sharing.identity_bootstrap.shutil.which", side_effect=available_outside_empty_path),
            mock.patch("web.extensions.opentunnel_sharing.identity_bootstrap._linux_no_service_manager_proof", return_value=True),
        ):
            unknown = observer.service_manager_entries(DEFAULT_PROFILE)
        self.assertEqual(unknown.state, "unknown")
        self.assertEqual(calls, [("systemctl", os.defpath)])

    def test_process_fixture_parsers_require_executable_profile_and_uid(self) -> None:
        executable = self.binary.resolve()
        line = "%d %d %s --profile %s serve" % (
            4242,
            os.getuid(),
            executable,
            DEFAULT_PROFILE,
        )
        observation = parse_ps_processes(
            line,
            profile=DEFAULT_PROFILE,
            executable_path=executable,
            uid=os.getuid(),
        )
        self.assertEqual(observation.state, "present")
        self.assertEqual(_assess_observations((("process", observation),)), "present")

        wrong_executable = self.scratch / "wrong-opentunnel"
        wrong_executable.write_bytes(b"wrong")
        wrong_executable.chmod(0o700)
        mismatch = parse_ps_processes(
            "%d %d %s --profile %s serve"
            % (4242, os.getuid(), wrong_executable, DEFAULT_PROFILE),
            profile=DEFAULT_PROFILE,
            executable_path=executable,
            uid=os.getuid(),
        )
        self.assertEqual(mismatch.state, "present")
        self.assertEqual(_assess_observations((("process", mismatch),)), "unknown")

        expected_env = companion_environment(self.layout)
        expected_env["PATH"] = ""
        linux_match = parse_linux_process_record(
            executable_path=str(executable),
            argv=(str(executable), "--profile", DEFAULT_PROFILE, "serve"),
            environment=expected_env,
            observed_uid=os.getuid(),
            profile=DEFAULT_PROFILE,
            expected_executable=executable,
            expected_environment=expected_env,
        )
        self.assertEqual(linux_match, ProcessEvidence(True, True, True))
        linux_mismatch = parse_linux_process_record(
            executable_path=str(wrong_executable),
            argv=(str(wrong_executable), "--profile", DEFAULT_PROFILE, "serve"),
            environment=expected_env,
            observed_uid=os.getuid() + 1,
            profile=DEFAULT_PROFILE,
            expected_executable=executable,
            expected_environment=expected_env,
        )
        self.assertEqual(linux_mismatch, ProcessEvidence(False, True, False))

    def test_default_process_observer_uses_native_snapshot_without_ps(self) -> None:
        record = process_info.ProcessInfo(
            pid=4242,
            ppid=1,
            pgid=4242,
            uid=os.getuid(),
            start_time=1_700_000_000.0,
            executable=str(self.binary.resolve()),
            argv=(str(self.binary.resolve()), "--profile", DEFAULT_PROFILE, "up"),
        )
        with (
            mock.patch.object(
                process_info, "snapshot_current_user", return_value=(record,)
            ) as native,
            mock.patch.object(
                identity_bootstrap.subprocess,
                "run",
                side_effect=AssertionError("default process observer spawned subprocess"),
            ),
        ):
            observer = DefaultIdentityObserver(
                self.layout,
                self.binary,
                system_name=identity_bootstrap.platform.system(),
            )
            result = observer.profile_processes(DEFAULT_PROFILE)
        self.assertEqual(result.state, "present")
        self.assertEqual(result.basis, "native_process_info_complete")
        native.assert_called_once_with()

    def test_incomplete_native_process_census_is_unknown_not_absent(self) -> None:
        def incomplete_snapshot() -> tuple[process_info.ProcessInfo, ...]:
            raise process_info.ProcessInfoUnavailable("process_list_incomplete")

        observer = DefaultIdentityObserver(
            self.layout,
            self.binary,
            system_name=identity_bootstrap.platform.system(),
            process_snapshot=incomplete_snapshot,
        )
        result = observer.profile_processes(DEFAULT_PROFILE)
        self.assertEqual(result.state, "unknown")
        self.assertEqual(result.basis, "observation_failed")

    def test_mixed_native_census_keeps_unknown_executable_candidate_uncertain(self) -> None:
        unrelated = process_info.ProcessInfo(
            pid=4241,
            ppid=1,
            pgid=4241,
            uid=os.getuid(),
            start_time=1_700_000_000.0,
            executable="/bin/echo",
            argv=("/bin/echo", "worker"),
            comm="echo",
        )
        candidate = process_info.ProcessInfo(
            pid=4242,
            ppid=1,
            pgid=4242,
            uid=os.getuid(),
            start_time=1_700_000_001.0,
            executable=None,
            argv=(str(self.binary), "--profile", DEFAULT_PROFILE, "up"),
            comm="opentunnel",
        )
        observation = identity_bootstrap.parse_process_info_processes(
            (unrelated, candidate),
            profile=DEFAULT_PROFILE,
            executable_path=self.binary,
            uid=os.getuid(),
        )
        self.assertEqual(observation.state, "present")
        self.assertEqual(observation.count, 1)
        self.assertIsNone(observation.processes[0].executable_matches)
        self.assertEqual(
            _assess_observations((("process", observation),)), "unknown"
        )

    def test_source_uses_no_shell_and_only_default_runner_invokes_subprocess(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / (
            "web/extensions/opentunnel_sharing/identity_bootstrap.py"
        )
        source = source_path.read_text(encoding="ascii")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "shell":
                        self.assertFalse(
                            isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True
                        )
        subprocess_calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                parent = _enclosing_class_method(tree, node)
                subprocess_calls.append(parent)
        self.assertEqual(subprocess_calls, ["DefaultCommandRunner.__call__"])
        self.assertNotIn("shell=True", source)

    @staticmethod
    def _snapshot(path: Path) -> tuple[int, int, int, bytes | str]:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            content: bytes | str = os.readlink(path)
        else:
            content = path.read_bytes()
        return (
            stat.S_IMODE(metadata.st_mode),
            metadata.st_uid,
            metadata.st_mtime_ns,
            content,
        )


def _enclosing_class_method(tree: ast.AST, target: ast.AST) -> str:
    result = ""

    def visit(node: ast.AST, class_name: str = "", method_name: str = "") -> None:
        nonlocal result
        if node is target:
            result = class_name + "." + method_name
            return
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                visit(child, node.name, method_name)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(node):
                visit(child, class_name, node.name)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, class_name, method_name)

    visit(tree)
    return result


if __name__ == "__main__":
    unittest.main()
