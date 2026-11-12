# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the host-only player-sharing service facade."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from web.extensions.opentunnel_sharing import native_process_info as process_info
from web.extensions.opentunnel_sharing.cleanup import (
    ReconcileResult,
    RouteObservation,
)
from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.controller import (
    ReadinessChecks,
    SharingCounters,
    SharingSnapshot,
    SharingState,
)
from web.extensions.opentunnel_sharing.identity_bootstrap import (
    BootstrapResult,
    DefaultCommandRunner,
    DefaultIdentityObserver,
    MAX_COMMAND_OUTPUT_CHARS,
    MAX_LAUNCHCTL_PRINT_OUTPUT_BYTES,
    RunResult,
)
from web.extensions.opentunnel_sharing.profile_state import ProfileLayout, ProfileState
from web.extensions.opentunnel_sharing.service import (
    MAX_STATUS_COMMAND_SECONDS,
    PlayerSharingService,
    SharingServiceDependencies,
    _ProfileRouteTable,
    _ProductionComposition,
    _parse_companion_status,
    create_production_player_sharing_service,
    validate_tunnel_target,
    _process_uid,
)
from web.extensions.opentunnel_sharing.verifier_store import (
    IssuedCredential,
    VerifierLoad,
    VerifierStatus,
)
from web.extensions.player.auth import PlayerSecurity
from web.extensions.player.constants import PLAYER_HOST, PLAYER_PORT
from web.extensions.player.listener import PlayerListener
from utils.web_boundary import DEFAULT_WEB_HOST, resolve_web_host
from config_template import WEB_HOST as CONFIG_TEMPLATE_WEB_HOST

SENTINEL_CREDENTIAL = "SENTINEL_CREDENTIAL_VALUE"
SENTINEL_ORIGIN = "https://sharing-route.example"


def _layout(root: Path) -> ProfileLayout:
    profile_root = root / "profile"
    return ProfileLayout(
        profile="neq-share",
        state_root=root,
        profile_root=profile_root,
        config_home=profile_root / "config",
        data_home=profile_root / "data",
        state_home=profile_root / "state",
        runtime_dir=profile_root / "run",
        verifier_dir=profile_root / "verifier",
        owner_file=profile_root / "profile_owner.json",
        socket_path=profile_root / "run" / "neq-share.sock",
    )


class FakeController:
    def __init__(self) -> None:
        self.snapshot = SharingSnapshot(
            SharingState.OFF,
            "off",
            0,
            ReadinessChecks(),
            SharingCounters(),
        )
        self.calls: list[str] = []
        self.invitation_url: str | None = None

    def status(self) -> SharingSnapshot:
        return self.snapshot

    def start(self) -> SharingSnapshot:
        self.calls.append("start")
        self.snapshot = replace(
            self.snapshot,
            state=SharingState.READY,
            reason="ready",
            generation=1,
        )
        self.invitation_url = SENTINEL_ORIGIN
        return self.snapshot

    def stop(self) -> SharingSnapshot:
        self.calls.append("stop")
        self.snapshot = replace(
            self.snapshot,
            state=SharingState.OFF,
            reason="stopped",
        )
        self.invitation_url = None
        return self.snapshot

    def shutdown(self) -> SharingSnapshot:
        self.calls.append("shutdown")
        self.snapshot = replace(
            self.snapshot,
            state=SharingState.OFF,
            reason="shutting_down",
        )
        return self.snapshot

    def rotate(self, callback: object) -> SharingSnapshot:
        self.calls.append("rotate")
        callback()  # type: ignore[operator]
        return self.snapshot

    def invitation(self) -> str | None:
        self.calls.append("invitation")
        return self.invitation_url

    def reconcile_cleanup(self) -> ReconcileResult:
        self.calls.append("reconcile")
        return ReconcileResult("clean", "cleanup_complete", True, ())


class FakeServiceDependencies:
    def __init__(self, root: Path) -> None:
        self.layout = _layout(root)
        self.profile_state = ProfileState("absent", "profile_absent")
        self.initialized = False
        self.credential_status = VerifierStatus("absent", "verifier_absent")
        self.controller = FakeController()
        self.controller_creations = 0
        self.prepare_calls: list[bool] = []
        self.resolve_calls = 0
        self.bootstrap_calls: list[bool] = []
        self.issue_calls = 0
        self.rotate_calls = 0
        self.revoke_calls = 0
        self.issued = IssuedCredential(SENTINEL_CREDENTIAL)

    def prepare_profile(self, create: bool) -> ProfileState:
        self.prepare_calls.append(create)
        if create:
            self.profile_state = ProfileState("ready", "ready", self.layout)
        return self.profile_state

    def identity_initialized(self, _layout: ProfileLayout) -> bool:
        return self.initialized

    def verifier_status(self, _layout: ProfileLayout) -> VerifierStatus:
        return self.credential_status

    def resolve_companion(self) -> CompanionResolution:
        self.resolve_calls += 1
        return CompanionResolution("resolved", "resolved", Path("fake-opentunnel"), "a" * 64)

    def initialize_identity(
        self,
        _layout: ProfileLayout,
        _resolution: CompanionResolution,
        confirmed: bool,
    ) -> BootstrapResult:
        self.bootstrap_calls.append(confirmed)
        self.initialized = True
        return BootstrapResult("initialized", "identity_initialized", ())

    def controller_factory(self, _layout: ProfileLayout) -> FakeController:
        self.controller_creations += 1
        return self.controller

    def issue_credential(self, _layout: ProfileLayout) -> IssuedCredential:
        self.issue_calls += 1
        self.credential_status = VerifierStatus("present", "present", 1, "2026-11-11T00:00:00Z")
        return IssuedCredential(SENTINEL_CREDENTIAL)

    def rotate_credential(self, _layout: ProfileLayout) -> IssuedCredential:
        self.rotate_calls += 1
        self.credential_status = VerifierStatus("present", "present", 2, "2026-11-11T00:01:00Z")
        return IssuedCredential(SENTINEL_CREDENTIAL)

    def revoke_access(self, _layout: ProfileLayout) -> VerifierLoad:
        self.revoke_calls += 1
        self.credential_status = VerifierStatus("absent", "verifier_absent")
        return VerifierLoad("absent", "verifier_absent")

    def service(self) -> PlayerSharingService:
        return PlayerSharingService(
            SharingServiceDependencies(
                prepare_profile=self.prepare_profile,
                identity_initialized=self.identity_initialized,
                verifier_status=self.verifier_status,
                resolve_companion=self.resolve_companion,
                initialize_identity=self.initialize_identity,
                controller_factory=self.controller_factory,
                issue_credential=self.issue_credential,
                rotate_credential=self.rotate_credential,
                revoke_access=self.revoke_access,
            )
        )


class PlayerSharingServiceTests(unittest.TestCase):
    def test_process_uid_uses_native_process_info(self) -> None:
        observed = process_info.ProcessInfo(
            pid=4242,
            ppid=1,
            pgid=1,
            uid=os.getuid(),
            start_time=1_700_000_000.0,
            executable="/bin/echo",
            argv=("/bin/echo",),
        )
        with mock.patch.object(process_info, "lookup", return_value=observed) as lookup:
            self.assertEqual(_process_uid(4242), os.getuid())
        lookup.assert_called_once_with(4242)
        with mock.patch.object(
            process_info,
            "lookup",
            side_effect=process_info.ProcessInfoUnavailable("process_info_unavailable"),
        ):
            self.assertIsNone(_process_uid(4242))

    def test_construction_and_uninitialized_status_do_not_initialize_or_start(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            missing_root = Path(scratch) / "missing-state"
            local_checks: list[bool] = []
            service = create_production_player_sharing_service(
                gateway=object(),  # type: ignore[arg-type]
                local_runtime_check=lambda: local_checks.append(True) is None,
                state_root=missing_root,
            )
            self.assertFalse(missing_root.exists())
            with mock.patch(
                "web.extensions.opentunnel_sharing.service.prepare_profile",
                return_value=ProfileState("absent", "profile_absent"),
            ) as prepare_profile:
                status = service.status()
            self.assertFalse(missing_root.exists())
            self.assertEqual(status.profile_state, "absent")
            self.assertFalse(status.identity_initialized)
            self.assertEqual(status.lifecycle.state, SharingState.INITIALIZING_REQUIRED)
            self.assertEqual(local_checks, [])
            prepare_profile.assert_called_once()
            self.assertFalse(prepare_profile.call_args.kwargs["create"])

    def test_identity_initialization_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service()

            refused = service.initialize_identity(facilitator_confirmed=False)
            self.assertFalse(refused.ok)
            self.assertEqual(refused.reason, "facilitator_confirmation_required")
            self.assertEqual(fake.prepare_calls, [False])
            self.assertEqual(fake.resolve_calls, 0)
            self.assertEqual(fake.bootstrap_calls, [])
            self.assertEqual(fake.controller_creations, 0)

            initialized = service.initialize_identity(facilitator_confirmed=True)
            self.assertTrue(initialized.ok)
            self.assertEqual(initialized.bootstrap_state, "initialized")
            self.assertEqual(fake.bootstrap_calls, [True])
            self.assertEqual(fake.controller_creations, 0)
            self.assertEqual(initialized.status.lifecycle.state, SharingState.OFF)

    def test_identity_initialization_is_idempotent_for_an_existing_marker(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            fake.profile_state = ProfileState("ready", "ready", fake.layout)
            fake.initialized = True
            service = fake.service()

            result = service.initialize_identity(facilitator_confirmed=True)

            self.assertTrue(result.ok)
            self.assertEqual(result.bootstrap_state, "already_initialized")
            self.assertEqual(fake.resolve_calls, 0)
            self.assertEqual(fake.bootstrap_calls, [])
            self.assertEqual(fake.controller_creations, 0)

    def test_start_and_invitation_are_host_only_transient_facade_operations(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            fake.profile_state = ProfileState("ready", "ready", fake.layout)
            fake.initialized = True
            service = fake.service()

            started = service.start()
            self.assertTrue(started.ok)
            self.assertEqual(fake.controller.calls, ["start"])
            copied = service.copy_invitation()
            self.assertTrue(copied.ok)
            self.assertEqual(copied.invitation, SENTINEL_ORIGIN)
            self.assertNotIn(SENTINEL_ORIGIN, repr(copied))
            self.assertNotIn(SENTINEL_ORIGIN, repr(service.status()))
            self.assertEqual(fake.controller.calls, ["start", "invitation"])

            stopped = service.stop()
            self.assertTrue(stopped.ok)
            self.assertEqual(fake.controller.calls[-1], "stop")
            unavailable = service.copy_invitation()
            self.assertFalse(unavailable.ok)
            self.assertIsNone(unavailable.invitation)

    def test_start_does_not_create_profile_or_controller_without_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service()

            result = service.start()

            self.assertFalse(result.ok)
            self.assertEqual(result.reason, "identity_not_initialized")
            self.assertEqual(fake.prepare_calls, [False])
            self.assertEqual(fake.controller_creations, 0)

    def test_shutdown_uses_only_an_existing_controller(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            absent = FakeServiceDependencies(Path(scratch) / "absent")
            absent_result = absent.service().shutdown()
            self.assertTrue(absent_result.ok)
            self.assertEqual(absent.controller_creations, 0)

            active = FakeServiceDependencies(Path(scratch) / "active")
            active.profile_state = ProfileState("ready", "ready", active.layout)
            active.initialized = True
            service = active.service()
            self.assertTrue(service.start().ok)
            result = service.shutdown()
            self.assertTrue(result.ok)
            self.assertIn("shutdown", active.controller.calls)

    def test_shutdown_reports_cleanup_failure_even_when_state_is_off(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            fake.profile_state = ProfileState("ready", "ready", fake.layout)
            fake.initialized = True

            class FailingShutdownController(FakeController):
                def shutdown(self) -> SharingSnapshot:
                    self.calls.append("shutdown")
                    self.snapshot = replace(
                        self.snapshot,
                        state=SharingState.OFF,
                        reason="cleanup_failed",
                    )
                    return self.snapshot

            fake.controller = FailingShutdownController()
            service = fake.service()
            self.assertTrue(service.start().ok)

            result = service.shutdown()

            self.assertFalse(result.ok)
            self.assertEqual(result.reason, "cleanup_failed")

    def test_one_time_access_issue_rotation_and_revoke_results_do_not_repr_secrets(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            fake.profile_state = ProfileState("ready", "ready", fake.layout)
            fake.initialized = True
            service = fake.service()

            issued = service.issue_access()
            self.assertTrue(issued.ok)
            self.assertIsNotNone(issued.credential)
            self.assertNotIn(SENTINEL_CREDENTIAL, repr(issued))
            self.assertEqual(issued.credential.reveal(), SENTINEL_CREDENTIAL)  # type: ignore[union-attr]
            with self.assertRaises(RuntimeError):
                issued.credential.reveal()  # type: ignore[union-attr]
            self.assertNotIn(SENTINEL_CREDENTIAL, repr(service.status()))

            rotated = service.rotate_access()
            self.assertTrue(rotated.ok)
            self.assertEqual(fake.rotate_calls, 1)
            self.assertNotIn(SENTINEL_CREDENTIAL, repr(rotated))

            revoked = service.revoke_access()
            self.assertTrue(revoked.ok)
            self.assertEqual(fake.revoke_calls, 1)
            self.assertIn("stop", fake.controller.calls)

    def test_reconciliation_absent_profile_does_not_construct_controller(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service()

            result = service.reconcile_startup()

            self.assertTrue(result.ok)
            self.assertEqual(result.reconciliation_state, "clean")
            self.assertEqual(fake.controller_creations, 0)

    def test_reconciliation_of_existing_profile_does_not_start_sharing(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            fake.profile_state = ProfileState("ready", "ready", fake.layout)
            service = fake.service()

            result = service.reconcile_startup()

            self.assertTrue(result.ok)
            self.assertEqual(result.reconciliation_state, "clean")
            self.assertEqual(fake.controller.calls, ["reconcile"])
            self.assertNotIn("start", fake.controller.calls)

    def test_private_route_config_is_exact_profile_scoped_and_removable(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            root = Path(scratch)
            profile_root = root / "profile"
            config_home = profile_root / "config"
            for path in (profile_root, config_home):
                path.mkdir(mode=0o700)
                os.chmod(path, 0o700)
            layout = _layout(root)
            route_table = _ProfileRouteTable(layout)

            self.assertTrue(route_table.ensure())
            route_contents = (config_home / "opentunnel" / "neq-share.toml").read_text(
                encoding="ascii"
            )
            self.assertEqual(
                route_contents,
                '[routes]\n"neq-share" = "127.0.0.1:8370"\n',
            )
            self.assertEqual(
                re.findall(r' = "([^\"]+)"', route_contents),
                ["127.0.0.1:8370"],
            )
            self.assertEqual(
                route_table.lookup("neq-share", None),
                RouteObservation("owned", "neq-share", "neq-share"),
            )
            self.assertTrue(route_table.remove("neq-share", "neq-share"))
            self.assertEqual(route_table.lookup("neq-share", None).state, "absent")

            foreign_directory = config_home / "opentunnel"
            foreign_config = foreign_directory / "neq-share.toml"
            foreign_config.write_text("[routes]\nother = \"127.0.0.1:8357\"\n", encoding="ascii")
            os.chmod(foreign_config, 0o600)
            self.assertFalse(route_table.ensure())
            self.assertEqual(route_table.lookup("neq-share", None).state, "foreign")
            self.assertFalse(route_table.remove("neq-share", "neq-share"))

    def test_companion_status_requires_connected_exact_player_route(self) -> None:
        accepted = (
            "Hostname: account.opentunnel.xyz\n"
            "Service: Connected (pid 17)\n"
            "neq-share.account.opentunnel.xyz -> 127.0.0.1:8370\n"
        )
        self.assertEqual(
            _parse_companion_status(accepted, "neq-share"),
            "https://neq-share.account.opentunnel.xyz",
        )
        self.assertIsNone(
            _parse_companion_status(
                accepted.replace("8370", "8357"),
                "neq-share",
            )
        )
        self.assertIsNone(
            _parse_companion_status(
                accepted.replace("Connected", "Starting"),
                "neq-share",
            )
        )
        self.assertIsNone(
            _parse_companion_status(
                accepted + "other.account.opentunnel.xyz -> 127.0.0.1:8370\n",
                "neq-share",
            )
        )
        for target in (
            "127.0.0.1:8360",
            "127.0.0.1:8357",
            "127.0.0.1:0",
            "0.0.0.0:8370",
            "localhost:8370",
            "::1:8370",
            "192.168.1.25:8370",
            "127.0.0.1:8370/player",
            "user@127.0.0.1:8370",
        ):
            with self.subTest(target=target):
                self.assertIsNone(
                    _parse_companion_status(
                        accepted.replace("127.0.0.1:8370", target),
                        "neq-share",
                    )
                )

    def test_tunnel_target_validation_and_service_listener_are_loopback_only(self) -> None:
        self.assertEqual(PLAYER_HOST, "127.0.0.1")
        self.assertEqual(PLAYER_PORT, 8370)
        self.assertEqual(CONFIG_TEMPLATE_WEB_HOST, "127.0.0.1")
        self.assertEqual(DEFAULT_WEB_HOST, "127.0.0.1")
        self.assertEqual(resolve_web_host(None), "127.0.0.1")
        target = validate_tunnel_target(PLAYER_HOST, PLAYER_PORT)
        self.assertEqual(target, "127.0.0.1:8370")

        invalid_targets = (
            ("127.0.0.1", 8360),
            ("127.0.0.1", 8357),
            ("127.0.0.1", 0),
            ("127.0.0.1", 8371),
            ("0.0.0.0", 8370),
            ("localhost", 8370),
            ("::1", 8370),
            ("192.168.1.25", 8370),
            ("127.0.0.1/player", 8370),
            ("127.0.0.1:8370/player", 8370),
            ("user@127.0.0.1", 8370),
            ("https://127.0.0.1", 8370),
        )
        for host, port in invalid_targets:
            with self.subTest(host=host, port=port):
                with self.assertRaisesRegex(ValueError, "tunnel_target_invalid"):
                    validate_tunnel_target(host, port)

        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            root = Path(scratch)
            layout = _layout(root)
            composition = _ProductionComposition(
                object(),  # type: ignore[arg-type]
                lambda: True,
                companion_manifest=None,
                install_root=root,
                state_root=root / "state",
                state_root_provider=None,
                install_marker=None,
                profile="neq-share",
                player_build_root=None,
            )

            class CapturingListener:
                is_running = True

                def __init__(self) -> None:
                    self.binds: list[tuple[str, int]] = []

                def start(self, *, host: str, port: int) -> None:
                    self.binds.append((host, port))

            listener = CapturingListener()
            controller = composition._controller_factory(layout)
            with mock.patch.object(composition, "_get_listener", return_value=listener):
                self.assertTrue(controller._deps.start_player_listener())
            self.assertEqual(listener.binds, [("127.0.0.1", 8370)])

    def test_status_probe_uses_fixed_argv_environment_and_deadline_with_fake_runner(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            root = Path(scratch)
            layout = _layout(root)
            composition = _ProductionComposition(
                object(),  # type: ignore[arg-type]
                lambda: True,
                companion_manifest=None,
                install_root=root,
                state_root=root / "state",
                state_root_provider=None,
                install_marker=None,
                profile="neq-share",
                player_build_root=None,
            )
            calls: list[tuple[tuple[str, ...], Mapping[str, str], float]] = []
            status_text = (
                "Hostname: account.opentunnel.xyz\n"
                "Service: Connected\n"
                "neq-share.account.opentunnel.xyz -> 127.0.0.1:8370\n"
            )

            class FakeHandle:
                state = "running"
                profile_layout = layout
                executable_path = root / "opentunnel"

            class FakeRunner:
                def __call__(
                    self,
                    argv: tuple[str, ...],
                    env: Mapping[str, str],
                    timeout: float,
                ) -> RunResult:
                    calls.append((argv, env, timeout))
                    return RunResult(0, status_text)

            composition._runner = FakeRunner()  # type: ignore[assignment]
            result = composition._route_status(FakeHandle(), 8, layout)  # type: ignore[arg-type]

            self.assertTrue(result.healthy)
            self.assertEqual(result.generation, 8)
            self.assertEqual(result.origin, "https://neq-share.account.opentunnel.xyz")
            self.assertEqual(calls[0][0], (str(root / "opentunnel"), "status", "--profile", "neq-share"))
            self.assertEqual(calls[0][2], MAX_STATUS_COMMAND_SECONDS)
            self.assertNotIn("127.0.0.1:8370", calls[0][0])
            self.assertNotIn("127.0.0.1:8370", calls[0][1].values())
            self.assertNotIn("PATH", calls[0][1])

    def test_identity_observer_uses_darwin_limit_without_widening_companion_runner(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            root = Path(scratch)
            layout = _layout(root)
            composition = _ProductionComposition(
                object(),  # type: ignore[arg-type]
                lambda: True,
                companion_manifest=None,
                install_root=root,
                state_root=root / "state",
                state_root_provider=None,
                install_marker=None,
                profile="neq-share",
                player_build_root=None,
            )
            shared_runner = composition._command_runner()
            resolution = CompanionResolution(
                "resolved", "resolved", root / "opentunnel", "a" * 64
            )
            captured: dict[str, object] = {}

            def capture_bootstrap(
                _layout: ProfileLayout,
                _resolution: CompanionResolution,
                **kwargs: object,
            ) -> BootstrapResult:
                captured.update(kwargs)
                return BootstrapResult("initialized", "identity_initialized")

            with (
                mock.patch(
                    "web.extensions.opentunnel_sharing.service.verify_companion_digest",
                    return_value=True,
                ),
                mock.patch(
                    "web.extensions.opentunnel_sharing.service.bootstrap_identity",
                    side_effect=capture_bootstrap,
                ),
                mock.patch(
                    "web.extensions.opentunnel_sharing.identity_bootstrap.platform.system",
                    return_value="Darwin",
                ),
            ):
                result = composition._initialize_identity(layout, resolution, True)

            self.assertEqual(result.state, "initialized")
            self.assertIs(captured["runner"], shared_runner)
            self.assertIsInstance(shared_runner, DefaultCommandRunner)
            self.assertEqual(shared_runner._max_output_bytes, MAX_COMMAND_OUTPUT_CHARS)
            observer = captured["observer"]
            self.assertIsInstance(observer, DefaultIdentityObserver)
            self.assertIsNot(observer._runner, shared_runner)
            self.assertEqual(
                observer._output_limit, MAX_LAUNCHCTL_PRINT_OUTPUT_BYTES
            )
            self.assertEqual(
                observer._runner._max_output_bytes,
                MAX_LAUNCHCTL_PRINT_OUTPUT_BYTES,
            )

    def test_identity_observer_honors_preassigned_fake_runner(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            root = Path(scratch)
            layout = _layout(root)
            composition = _ProductionComposition(
                object(),  # type: ignore[arg-type]
                lambda: True,
                companion_manifest=None,
                install_root=root,
                state_root=root / "state",
                state_root_provider=None,
                install_marker=None,
                profile="neq-share",
                player_build_root=None,
            )
            fake_runner = lambda _argv, _env, _timeout: RunResult(0, "")
            composition._runner = fake_runner  # type: ignore[assignment]
            resolution = CompanionResolution(
                "resolved", "resolved", root / "opentunnel", "a" * 64
            )
            captured: dict[str, object] = {}

            def capture_bootstrap(
                _layout: ProfileLayout,
                _resolution: CompanionResolution,
                **kwargs: object,
            ) -> BootstrapResult:
                captured.update(kwargs)
                return BootstrapResult("initialized", "identity_initialized")

            with (
                mock.patch(
                    "web.extensions.opentunnel_sharing.service.verify_companion_digest",
                    return_value=True,
                ),
                mock.patch(
                    "web.extensions.opentunnel_sharing.service.bootstrap_identity",
                    side_effect=capture_bootstrap,
                ),
            ):
                composition._initialize_identity(layout, resolution, True)

            self.assertIs(captured["runner"], fake_runner)
            observer = captured["observer"]
            self.assertIsInstance(observer, DefaultIdentityObserver)
            self.assertIs(observer._runner, fake_runner)

    def test_player_listener_accepts_injected_n1_security_without_binding(self) -> None:
        security = PlayerSecurity(lambda: None)
        listener = PlayerListener(gateway=object(), security=security)  # type: ignore[arg-type]
        self.assertIs(listener.app.security, security)
        self.assertFalse(listener.is_running)

    def test_loopback_probe_never_uses_a_public_host_or_real_socket(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            root = Path(scratch)
            composition = _ProductionComposition(
                object(),  # type: ignore[arg-type]
                lambda: True,
                companion_manifest=None,
                install_root=root,
                state_root=root / "state",
                state_root_provider=None,
                install_marker=None,
                profile="neq-share",
                player_build_root=None,
            )

            class FakeListener:
                is_running = True

            class FakeResponse:
                status = 200

                @staticmethod
                def getheader(name: str, default: str = "") -> str:
                    return "text/html" if name == "Content-Type" else default

                @staticmethod
                def read(_size: int) -> bytes:
                    return b"ok"

            class FakeConnection:
                def __init__(self, host: str, port: int, *, timeout: float) -> None:
                    self.host = host
                    self.port = port
                    self.timeout = timeout
                    self.request_args: tuple[str, str, Mapping[str, str]] | None = None

                def request(self, method: str, path: str, *, headers: Mapping[str, str]) -> None:
                    self.request_args = (method, path, headers)

                @staticmethod
                def getresponse() -> FakeResponse:
                    return FakeResponse()

                @staticmethod
                def close() -> None:
                    return None

            connections: list[FakeConnection] = []

            def connection_factory(host: str, port: int, *, timeout: float) -> FakeConnection:
                connection = FakeConnection(host, port, timeout=timeout)
                connections.append(connection)
                return connection

            composition._listener = FakeListener()  # type: ignore[assignment]
            with mock.patch(
                "web.extensions.opentunnel_sharing.service.http.client.HTTPConnection",
                side_effect=connection_factory,
            ):
                self.assertTrue(composition._listener_authenticated_probe())

            self.assertEqual(len(connections), 1)
            self.assertEqual(connections[0].host, "127.0.0.1")
            self.assertEqual(connections[0].port, PLAYER_PORT)
            self.assertEqual(connections[0].timeout, 1.0)
            self.assertEqual(connections[0].request_args[0:2], ("GET", "/"))  # type: ignore[index]
            self.assertEqual(connections[0].request_args[2]["Host"], "%s:%d" % (PLAYER_HOST, PLAYER_PORT))  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
