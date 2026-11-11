# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the isolated N3 recovery override and counters."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.controller import (
    RouteStatus,
    SharingController,
    SharingDependencies,
    SharingState,
)
from web.extensions.opentunnel_sharing.identity_bootstrap import BootstrapResult
from web.extensions.opentunnel_sharing.profile_state import ProfileLayout, ProfileState
from web.extensions.opentunnel_sharing import production_monitor
from web.extensions.opentunnel_sharing.production_monitor import (
    N3_GATE_RUN_ID_ENV,
    N3_RECOVERY_ATTEMPTS_ENV,
    production_recovery_policy,
)
from web.extensions.opentunnel_sharing.relay_supervision import RecoveryPolicy
from web.extensions.opentunnel_sharing.service import (
    PlayerSharingService,
    SharingServiceDependencies,
    create_production_player_sharing_service,
)
from web.extensions.opentunnel_sharing.verifier_store import (
    IssuedCredential,
    VerifierLoad,
    VerifierStatus,
)


_GATE_RUN_ID = "n3-run-id-123"
_DEFAULT_POLICY = RecoveryPolicy()
_DEFAULT_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0)
_ENV_NAMES = (N3_RECOVERY_ATTEMPTS_ENV, N3_GATE_RUN_ID_ENV)
_MISSING = object()


class _GateEnvironment:
    def __init__(self, **values: object) -> None:
        self._values = values
        self._patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._previous: dict[str, str | object] = {}

    def __enter__(self) -> None:
        self._patcher.start()
        self._previous = {
            name: os.environ.get(name, _MISSING) for name in _ENV_NAMES
        }
        for name in _ENV_NAMES:
            os.environ.pop(name, None)
        for name, value in self._values.items():
            if value is not _MISSING:
                os.environ[name] = str(value)

    def __exit__(self, *_exc: object) -> None:
        for name in _ENV_NAMES:
            os.environ.pop(name, None)
            previous = self._previous[name]
            if previous is not _MISSING:
                os.environ[name] = str(previous)
        self._patcher.stop()


def _sandbox_root() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    scratch = tempfile.TemporaryDirectory(dir="tmp")
    outer = Path(scratch.name)
    (outer / "AGENTS.md").write_text("sandbox marker\n", encoding="ascii")
    (outer / "model_config.py").write_text("SANDBOX_MARKER = True\n", encoding="ascii")
    root = outer / "tmp" / "combat_capture"
    root.mkdir(parents=True)
    _source_path(root)
    return scratch, root


def _source_path(root: Path, *, web_dir: str = "web") -> Path:
    source = (
        root
        / web_dir
        / "extensions"
        / "opentunnel_sharing"
        / "production_monitor.py"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# synthetic monitor source\n", encoding="ascii")
    return source


class RecoveryOverrideTests(unittest.TestCase):
    def test_missing_override_preserves_default_without_resolving_root(self) -> None:
        with _GateEnvironment():
            with mock.patch(
                "web.extensions.opentunnel_sharing.production_monitor._is_isolated_capture_root",
                side_effect=AssertionError("root must not be inspected"),
            ):
                policy = production_recovery_policy(8360)

        self.assertEqual(policy, _DEFAULT_POLICY)
        self.assertEqual(policy.max_attempts, 5)
        self.assertEqual(policy.backoff_schedule, _DEFAULT_DELAYS)

    def test_invalid_attempt_values_keep_the_production_default(self) -> None:
        scratch, root = _sandbox_root()
        self.addCleanup(scratch.cleanup)
        invalid_values = ("not-an-integer", "1.5", "0", "4", "5", "-1", "9" * 5000)

        with self.assertLogs(
            "web.extensions.opentunnel_sharing.production_monitor", level="WARNING"
        ) as captured:
            for value in invalid_values:
                with self.subTest(value_length=len(value)):
                    with _GateEnvironment(
                        **{
                            N3_RECOVERY_ATTEMPTS_ENV: value,
                            N3_GATE_RUN_ID_ENV: _GATE_RUN_ID,
                        }
                    ):
                        policy = production_recovery_policy(8360)
                    self.assertEqual(policy, _DEFAULT_POLICY)

        self.assertEqual(
            len(captured.records),
            len(invalid_values),
        )
        for record in captured.records:
            self.assertRegex(
                record.getMessage(),
                r"^N3_RECOVERY_OVERRIDE_IGNORED: recovery_override_(not_integer|out_of_range)$",
            )

    def test_override_is_honored_for_one_two_or_three_attempts_without_delay_changes(self) -> None:
        scratch, root = _sandbox_root()
        self.addCleanup(scratch.cleanup)
        for attempts in (1, 2, 3):
            with self.subTest(attempts=attempts):
                with _GateEnvironment(
                    **{
                        N3_RECOVERY_ATTEMPTS_ENV: attempts,
                        N3_GATE_RUN_ID_ENV: _GATE_RUN_ID,
                    }
                ), mock.patch.object(
                    production_monitor, "__file__", str(_source_path(root))
                ):
                    policy = production_recovery_policy(8360)

                self.assertEqual(policy.max_attempts, attempts)
                self.assertLessEqual(policy.max_attempts, _DEFAULT_POLICY.max_attempts)
                self.assertEqual(policy.backoff_schedule, _DEFAULT_DELAYS[:attempts])
                for index, delay in enumerate(_DEFAULT_DELAYS[:attempts]):
                    self.assertEqual(policy.delay_for(1, index), delay)
                self.assertEqual(policy.health_check_interval, _DEFAULT_POLICY.health_check_interval)
                self.assertEqual(policy.max_delay, _DEFAULT_POLICY.max_delay)
                self.assertEqual(policy.jitter_seconds, _DEFAULT_POLICY.jitter_seconds)

    def test_override_is_ignored_for_nonisolated_root_variations_and_symlink(self) -> None:
        scratch, root = _sandbox_root()
        self.addCleanup(scratch.cleanup)
        outer = Path(scratch.name)
        variants = (
            outer / "scratch" / "combat_capture",
            outer / "tmp" / "combat_capture-copy",
            outer / "tmp" / "nested" / "combat_capture",
        )
        for variant in variants:
            variant.mkdir(parents=True)
            _source_path(variant)

        alias_root = outer / "alias" / "tmp" / "combat_capture"
        alias_root.parent.mkdir(parents=True)
        alias_root.symlink_to(root, target_is_directory=True)
        parent_alias = outer / "parent-alias"
        parent_alias.symlink_to(outer, target_is_directory=True)
        parent_alias_root = parent_alias / "tmp" / "combat_capture"

        cases = tuple(
            (_source_path(path), "runtime_root_not_isolated") for path in variants
        ) + (
            (_source_path(alias_root), "runtime_root_symlinked"),
            (_source_path(parent_alias_root), "runtime_root_symlinked"),
        )
        for selected_source, expected_reason in cases:
            with self.subTest(
                root_kind=expected_reason, source_name=selected_source.name
            ):
                with _GateEnvironment(
                    **{
                        N3_RECOVERY_ATTEMPTS_ENV: "2",
                        N3_GATE_RUN_ID_ENV: _GATE_RUN_ID,
                    }
                ), mock.patch.object(
                    production_monitor, "__file__", str(selected_source)
                ), self.assertLogs(
                    "web.extensions.opentunnel_sharing.production_monitor",
                    level="WARNING",
                ) as captured:
                    policy = production_recovery_policy(8360)
                self.assertEqual(policy, _DEFAULT_POLICY)
                self.assertEqual(
                    captured.records[0].getMessage(),
                    "N3_RECOVERY_OVERRIDE_IGNORED: " + expected_reason,
                )

    def test_override_is_ignored_when_the_imported_source_path_is_symlinked(self) -> None:
        scratch, root = _sandbox_root()
        self.addCleanup(scratch.cleanup)
        source_alias = Path(scratch.name) / "production_monitor.py"
        source_alias.symlink_to(_source_path(root))

        with _GateEnvironment(
            **{
                N3_RECOVERY_ATTEMPTS_ENV: "1",
                N3_GATE_RUN_ID_ENV: _GATE_RUN_ID,
            }
        ), mock.patch.object(
            production_monitor, "__file__", str(source_alias)
        ), self.assertLogs(
            "web.extensions.opentunnel_sharing.production_monitor", level="WARNING"
        ) as captured:
            policy = production_recovery_policy(8360)

        self.assertEqual(policy, _DEFAULT_POLICY)
        self.assertEqual(
            captured.records[0].getMessage(),
            "N3_RECOVERY_OVERRIDE_IGNORED: runtime_root_symlinked",
        )

    def test_override_is_ignored_for_wrong_web_port_and_bad_or_missing_run_id(self) -> None:
        scratch, root = _sandbox_root()
        self.addCleanup(scratch.cleanup)

        for port in (None, 8357, 8370, 8361, True, "8360"):
            with self.subTest(port=port):
                with _GateEnvironment(
                    **{
                        N3_RECOVERY_ATTEMPTS_ENV: "1",
                        N3_GATE_RUN_ID_ENV: _GATE_RUN_ID,
                    }
                ), mock.patch.object(
                    production_monitor, "__file__", str(_source_path(root))
                ), self.assertLogs(
                    "web.extensions.opentunnel_sharing.production_monitor",
                    level="WARNING",
                ) as captured:
                    policy = production_recovery_policy(port)
                self.assertEqual(policy, _DEFAULT_POLICY)
                self.assertEqual(
                    captured.records[0].getMessage(),
                    "N3_RECOVERY_OVERRIDE_IGNORED: web_port_mismatch",
                )

        for run_id in (_MISSING, "", "short", "Uppercase-run-123", "bad.run-id", "a" * 65):
            with self.subTest(run_id_length=0 if run_id is _MISSING else len(str(run_id))):
                values = {N3_RECOVERY_ATTEMPTS_ENV: "1"}
                if run_id is not _MISSING:
                    values[N3_GATE_RUN_ID_ENV] = run_id
                with _GateEnvironment(**values), mock.patch.object(
                    production_monitor, "__file__", str(_source_path(root))
                ), self.assertLogs(
                    "web.extensions.opentunnel_sharing.production_monitor",
                    level="WARNING",
                ) as captured:
                    policy = production_recovery_policy(8360)
                self.assertEqual(policy, _DEFAULT_POLICY)
                self.assertEqual(
                    captured.records[0].getMessage(),
                    "N3_RECOVERY_OVERRIDE_IGNORED: run_id_invalid",
                )

    def test_rejected_override_logs_only_bounded_reason_and_status_omits_context(self) -> None:
        scratch, root = _sandbox_root()
        self.addCleanup(scratch.cleanup)
        override_value = "2"
        rejected_root = root.parent / "other" / "root"
        rejected_root.mkdir(parents=True)
        with _GateEnvironment(
            **{
                N3_RECOVERY_ATTEMPTS_ENV: override_value,
                N3_GATE_RUN_ID_ENV: _GATE_RUN_ID,
            }
        ), mock.patch.object(
            production_monitor, "__file__", str(_source_path(rejected_root))
        ), self.assertLogs(
            "web.extensions.opentunnel_sharing.production_monitor", level="WARNING"
        ) as captured:
            policy = production_recovery_policy(8360)

        self.assertEqual(policy, _DEFAULT_POLICY)
        message = captured.records[0].getMessage()
        self.assertEqual(
            message,
            "N3_RECOVERY_OVERRIDE_IGNORED: runtime_root_not_isolated",
        )
        self.assertNotIn(override_value, message)
        self.assertNotIn(str(root), message)

        service = create_production_player_sharing_service(
            gateway=object(),  # type: ignore[arg-type]
            local_runtime_check=lambda: True,
            state_root=root / "state",
            install_root=root,
            web_port=8360,
        )
        status_text = repr(service.status())
        self.assertNotIn(N3_RECOVERY_ATTEMPTS_ENV, status_text)
        self.assertNotIn(str(root), status_text)

    def test_production_factory_wires_valid_override_to_sharing_service(self) -> None:
        scratch, root = _sandbox_root()
        self.addCleanup(scratch.cleanup)
        with _GateEnvironment(
            **{
                N3_RECOVERY_ATTEMPTS_ENV: "3",
                N3_GATE_RUN_ID_ENV: _GATE_RUN_ID,
            }
        ), mock.patch.object(
            production_monitor, "__file__", str(_source_path(root))
        ):
            service = create_production_player_sharing_service(
                gateway=object(),  # type: ignore[arg-type]
                local_runtime_check=lambda: True,
                state_root=root / "state",
                install_root=root,
                web_port=8360,
            )

        self.assertEqual(service._recovery_policy.max_attempts, 3)
        self.assertEqual(service._recovery_policy.backoff_schedule, _DEFAULT_DELAYS[:3])


class _FakeBinder:
    def __init__(self) -> None:
        self.generation: int | None = None
        self.is_bound = False
        self.state = "unbound"

    def begin_generation(self, generation: int) -> bool:
        self.generation = generation
        self.is_bound = False
        self.state = "pending"
        return True

    def bind(self, origin: object, generation: object, ready: bool) -> bool:
        if origin != "https://n3-counter.example" or type(generation) is not int or not ready:
            return False
        self.generation = generation
        self.is_bound = True
        self.state = "bound"
        return True

    def clear(self, _reason: str) -> None:
        self.generation = None
        self.is_bound = False
        self.state = "unbound"


class _FakeCompanion:
    def __init__(self, *, start_result: str = "running") -> None:
        self._state = "stopped"
        self._reaped = True
        self.start_result = start_result
        self.start_calls = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def reaped(self) -> bool:
        return self._reaped

    def start(self, _deadline: float) -> str:
        self.start_calls += 1
        if self.start_result == "running":
            self._state = "running"
            self._reaped = False
        else:
            self._state = "failed"
            self._reaped = True
        return self.start_result

    def stop(self, _deadline: float) -> bool:
        self._state = "stopped"
        self._reaped = True
        return True

    def diagnostics(self) -> dict[str, object]:
        return {"state": self._state}


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


def _counter_service(*, identity_ready: bool = True) -> tuple[
    PlayerSharingService, list[_FakeCompanion], list[SharingController]
]:
    layout = _layout(Path("tmp/n3-sharing-counter"))
    profile = ProfileState("ready", "ready", layout)
    identity = {"ready": identity_ready}
    companions: list[_FakeCompanion] = []
    controllers: list[SharingController] = []

    def controller_factory(_layout_value: ProfileLayout) -> SharingController:
        binder = _FakeBinder()

        def start_companion(_generation: int) -> _FakeCompanion:
            companion = _FakeCompanion()
            companions.append(companion)
            return companion

        dependencies = SharingDependencies(
            local_runtime_ok=lambda: True,
            assets_ok=lambda: True,
            start_player_listener=lambda: True,
            stop_player_listener=lambda: None,
            listener_authenticated_probe=lambda: True,
            load_verifier=lambda: VerifierLoad(
                "present", "present", verifier=object()  # type: ignore[arg-type]
            ),
            resolve_companion=lambda: CompanionResolution(
                "resolved", "resolved", Path("fake-opentunnel"), "a" * 64
            ),
            identity_initialized=lambda: identity["ready"],
            start_companion=start_companion,
            route_status=lambda _companion, generation: RouteStatus(
                True, "https://n3-counter.example", generation
            ),
            origin_binder=binder,  # type: ignore[arg-type]
            route_wait_seconds=0.0,
            route_poll_interval_seconds=0.01,
        )
        controller = SharingController(dependencies)
        controllers.append(controller)
        return controller

    def initialize_identity(
        _layout_value: ProfileLayout,
        _resolution: CompanionResolution,
        _confirmed: bool,
    ) -> BootstrapResult:
        identity["ready"] = True
        return BootstrapResult(
            "initialized",
            "identity_initialized",
            ("up=returncode_0", "status=returncode_0", "down=returncode_0"),
        )

    dependencies = SharingServiceDependencies(
        prepare_profile=lambda _create: profile,
        identity_initialized=lambda _layout_value: identity["ready"],
        verifier_status=lambda _layout_value: VerifierStatus(
            "present", "present", 1, "2026-11-11T00:00:00Z"
        ),
        resolve_companion=lambda: CompanionResolution(
            "resolved", "resolved", Path("fake-opentunnel"), "a" * 64
        ),
        initialize_identity=initialize_identity,
        controller_factory=controller_factory,
        issue_credential=lambda _layout_value: IssuedCredential("credential"),
        rotate_credential=lambda _layout_value: IssuedCredential("credential"),
        revoke_access=lambda _layout_value: VerifierLoad("absent", "absent"),
    )
    service = PlayerSharingService(dependencies, run_supervision_thread=False)
    return service, companions, controllers


class SharingOperationCounterTests(unittest.TestCase):
    def test_serve_launches_count_once_per_launch_recovery_and_service_instance(self) -> None:
        service, companions, controllers = _counter_service()
        started = service.start()
        self.assertTrue(started.ok)
        self.assertEqual(service.diagnostics().companion_launches, 1)
        self.assertEqual(companions[0].start_calls, 1)

        service.start()
        self.assertEqual(service.diagnostics().companion_launches, 1)
        self.assertEqual(len(companions), 1)

        controller = controllers[0]
        companions[0]._state = "exited"
        companions[0]._reaped = True
        controller.mark_degraded("companion_failed")
        recovered = controller.recover()
        self.assertEqual(recovered.state, SharingState.READY)
        self.assertEqual(service.diagnostics().companion_launches, 2)
        self.assertEqual([item.start_calls for item in companions], [1, 1])

        second_service, second_companions, _second_controllers = _counter_service()
        self.assertTrue(second_service.start().ok)
        second_status = second_service.diagnostics()
        self.assertEqual(second_status.companion_launches, 1)
        self.assertEqual(second_status.identity_up_invocations, 0)
        self.assertEqual(second_companions[0].start_calls, 1)

    def test_failed_serve_launch_counts_once_and_bootstrap_counts_only_actual_up_fact(self) -> None:
        service, companions, _controllers = _counter_service(identity_ready=False)
        initialized = service.initialize_identity(facilitator_confirmed=True)
        self.assertTrue(initialized.ok)
        self.assertEqual(initialized.status.identity_up_invocations, 1)
        already_initialized = service.initialize_identity(facilitator_confirmed=True)
        self.assertTrue(already_initialized.ok)
        self.assertEqual(already_initialized.status.identity_up_invocations, 1)

        # A failed launch is still a serve launch attempt and consumes one cap unit.
        profile = ProfileState("ready", "ready", _layout(Path("tmp/n3-sharing-failed")))
        identity = True
        handles: list[_FakeCompanion] = []
        binder = _FakeBinder()

        def failed_controller_factory(_layout_value: ProfileLayout) -> SharingController:
            def start_companion(_generation: int) -> _FakeCompanion:
                companion = _FakeCompanion(start_result="failed")
                handles.append(companion)
                return companion

            return SharingController(
                SharingDependencies(
                    local_runtime_ok=lambda: True,
                    assets_ok=lambda: True,
                    start_player_listener=lambda: True,
                    stop_player_listener=lambda: None,
                    listener_authenticated_probe=lambda: True,
                    load_verifier=lambda: VerifierLoad(
                        "present", "present", verifier=object()  # type: ignore[arg-type]
                    ),
                    resolve_companion=lambda: CompanionResolution(
                        "resolved", "resolved", Path("fake-opentunnel"), "a" * 64
                    ),
                    identity_initialized=lambda: identity,
                    start_companion=start_companion,
                    route_status=lambda _companion, generation: RouteStatus(
                        True, "https://n3-counter.example", generation
                    ),
                    origin_binder=binder,  # type: ignore[arg-type]
                    route_wait_seconds=0.0,
                )
            )

        failed_dependencies = SharingServiceDependencies(
            prepare_profile=lambda _create: profile,
            identity_initialized=lambda _layout_value: identity,
            verifier_status=lambda _layout_value: VerifierStatus("present", "present"),
            resolve_companion=lambda: CompanionResolution(
                "resolved", "resolved", Path("fake-opentunnel"), "a" * 64
            ),
            initialize_identity=lambda _layout_value, _resolution, _confirmed: BootstrapResult(
                "initialized", "identity_initialized", ()
            ),
            controller_factory=failed_controller_factory,
            issue_credential=lambda _layout_value: IssuedCredential("credential"),
            rotate_credential=lambda _layout_value: IssuedCredential("credential"),
            revoke_access=lambda _layout_value: VerifierLoad("absent", "absent"),
        )
        failed_service = PlayerSharingService(
            failed_dependencies, run_supervision_thread=False
        )
        failed_result = failed_service.start()
        self.assertFalse(failed_result.ok)
        self.assertEqual(failed_service.diagnostics().companion_launches, 1)
        self.assertEqual(handles[0].start_calls, 1)


if __name__ == "__main__":
    unittest.main()
