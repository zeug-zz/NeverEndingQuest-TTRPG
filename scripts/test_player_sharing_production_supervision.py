# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free integration tests for production sharing supervision."""

from __future__ import annotations

import tempfile
import threading
import unittest
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Callable
from unittest import mock

from web.extensions.opentunnel_sharing.cleanup import ReconcileResult
from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.controller import (
    ReadinessChecks,
    RouteStatus,
    SharingController,
    SharingCounters,
    SharingDependencies,
    SharingSnapshot,
    SharingState,
)
from web.extensions.opentunnel_sharing.profile_state import ProfileLayout, ProfileState
from web.extensions.opentunnel_sharing.production_monitor import ProductionRelayMonitor
from web.extensions.opentunnel_sharing.relay_supervision import (
    RecoveryPolicy,
    RelayHealthObservation,
    RelaySupervisionSnapshot,
)
from web.extensions.opentunnel_sharing.service import (
    PlayerSharingService,
    SharingServiceDependencies,
    _ProductionComposition,
)
from web.extensions.opentunnel_sharing.verifier_store import (
    IssuedCredential,
    VerifierLoad,
    VerifierStatus,
)

SENTINEL_CREDENTIAL = "SENTINEL_CREDENTIAL_VALUE"
SENTINEL_ORIGIN = "https://sentinel-private.example"
SENTINEL_OUTPUT = "SENTINEL_RAW_COMPANION_OUTPUT"
THREAD_PREFIX = "player-sharing-supervision-"


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


def _ready_checks() -> ReadinessChecks:
    return ReadinessChecks(
        platform_supported=True,
        companion_available=True,
        identity_initialized=True,
        credential_configured=True,
        local_runtime=True,
        player_assets=True,
        listener_started=True,
        listener_authenticated=True,
        owned_route_healthy=True,
        route_generation_matches=True,
        origin_bound=True,
    )


class FakeController:
    """Serialized-controller stand-in; recovery never touches gameplay state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.generation = 0
        self.lifecycle_revision = 0
        self.snapshot = SharingSnapshot(
            SharingState.OFF,
            "off",
            0,
            ReadinessChecks(),
            SharingCounters(),
        )
        self.recovery_results: deque[bool] = deque()
        self.recover_calls = 0
        self.mark_degraded_calls: list[str] = []
        self.mark_failed_calls: list[str] = []
        self.lifecycle_calls: list[str] = []
        self.invitation_url: str | None = SENTINEL_ORIGIN
        self.failed_event = threading.Event()

    def status(self) -> SharingSnapshot:
        with self._lock:
            return self.snapshot

    def start(self) -> SharingSnapshot:
        with self._lock:
            self.lifecycle_calls.append("start")
            if self.snapshot.state is SharingState.READY:
                return self.snapshot
            self.generation += 1
            self.lifecycle_revision += 1
            self.snapshot = SharingSnapshot(
                SharingState.READY,
                "ready",
                self.generation,
                _ready_checks(),
                self.snapshot.counters,
            )
            return self.snapshot

    def stop(self) -> SharingSnapshot:
        with self._lock:
            self.lifecycle_calls.append("stop")
            self.lifecycle_revision += 1
            self.snapshot = SharingSnapshot(
                SharingState.OFF,
                "stopped",
                self.generation,
                ReadinessChecks(),
                self.snapshot.counters,
            )
            return self.snapshot

    def shutdown(self) -> SharingSnapshot:
        with self._lock:
            self.lifecycle_calls.append("shutdown")
            self.lifecycle_revision += 1
            self.snapshot = SharingSnapshot(
                SharingState.OFF,
                "shutting_down",
                self.generation,
                ReadinessChecks(),
                self.snapshot.counters,
            )
            return self.snapshot

    def rotate(self, callback: Callable[[], object]) -> SharingSnapshot:
        with self._lock:
            self.lifecycle_calls.append("rotate")
            self.lifecycle_revision += 1
            generation = self.generation
            was_ready = self.snapshot.state is SharingState.READY
            if was_ready:
                self.snapshot = replace(
                    self.snapshot,
                    state=SharingState.DEGRADED,
                    reason="readiness_regressed",
                    checks=replace(self.snapshot.checks, origin_bound=False),
                )
        try:
            callback()
        except Exception:
            with self._lock:
                self.snapshot = replace(
                    self.snapshot,
                    state=SharingState.FAILED,
                    reason="readiness_regressed",
                    checks=ReadinessChecks(),
                )
            return self.status()
        with self._lock:
            if was_ready and self.generation == generation:
                self.snapshot = replace(
                    self.snapshot,
                    state=SharingState.READY,
                    reason="ready",
                    checks=_ready_checks(),
                )
            return self.snapshot

    def invitation(self) -> str | None:
        with self._lock:
            return self.invitation_url if self.snapshot.state is SharingState.READY else None

    def reconcile_cleanup(self) -> ReconcileResult:
        return ReconcileResult("clean", "cleanup_complete", True, ())

    def mark_degraded(
        self,
        reason: object,
        *,
        expected_generation: int | None = None,
        expected_lifecycle_revision: int | None = None,
        expected_state: SharingState | None = None,
    ) -> SharingSnapshot:
        with self._lock:
            self.mark_degraded_calls.append(str(reason))
            if (
                expected_generation not in {None, self.generation}
                or expected_lifecycle_revision
                not in {None, self.lifecycle_revision}
                or (expected_state is not None and self.snapshot.state is not expected_state)
            ):
                return self.snapshot
            self.snapshot = replace(
                self.snapshot,
                state=SharingState.DEGRADED,
                reason=str(reason),
                checks=replace(self.snapshot.checks, origin_bound=False),
            )
            return self.snapshot

    def mark_failed(
        self,
        reason: object,
        *,
        expected_generation: int | None = None,
        expected_lifecycle_revision: int | None = None,
        expected_state: SharingState | None = None,
    ) -> SharingSnapshot:
        with self._lock:
            self.mark_failed_calls.append(str(reason))
            if (
                expected_generation not in {None, self.generation}
                or expected_lifecycle_revision
                not in {None, self.lifecycle_revision}
                or (expected_state is not None and self.snapshot.state is not expected_state)
            ):
                return self.snapshot
            self.snapshot = replace(
                self.snapshot,
                state=SharingState.FAILED,
                reason=str(reason),
                checks=ReadinessChecks(),
            )
            self.failed_event.set()
            return self.snapshot

    def recover(self) -> SharingSnapshot:
        with self._lock:
            self.recover_calls += 1
            recovered = (
                self.recovery_results.popleft()
                if self.recovery_results
                else True
            )
            if recovered:
                self.snapshot = replace(
                    self.snapshot,
                    state=SharingState.READY,
                    reason="ready",
                    checks=_ready_checks(),
                )
            else:
                self.snapshot = replace(
                    self.snapshot,
                    state=SharingState.DEGRADED,
                    reason="route_unhealthy",
                    checks=replace(self.snapshot.checks, origin_bound=False),
                )
            return self.snapshot


class FakeMonitor:
    def __init__(self) -> None:
        self.observations: deque[object] = deque()
        self.default_healthy = True
        self.generations: list[int] = []
        self.calls = 0

    def observe(self, generation: int) -> RelayHealthObservation:
        self.calls += 1
        self.generations.append(generation)
        result = self.observations.popleft() if self.observations else None
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            result = result(generation)
        if result is None:
            return RelayHealthObservation(
                generation,
                "alive",
                self.default_healthy,
                self.default_healthy,
            )
        return result  # type: ignore[return-value]


class FakeClock:
    def __init__(self) -> None:
        self.now = 50.0
        self.delays: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, delay: float, cancel_event: threading.Event) -> bool:
        self.delays.append(delay)
        self.now += delay
        return cancel_event.is_set()


class FakeServiceDependencies:
    def __init__(self, root: Path) -> None:
        self.layout = _layout(root)
        self.profile = ProfileState("ready", "ready", self.layout)
        self.controller = FakeController()
        self.monitors: list[FakeMonitor] = []
        self.monitor_factory_calls: list[tuple[int, FakeMonitor]] = []
        self.credential_state = VerifierStatus(
            "present", "present", 1, "2026-11-11T00:00:00Z"
        )
        self.gameplay_calls: list[str] = []

    def make_monitor(
        self, _controller: SharingController, generation: int
    ) -> FakeMonitor:
        monitor = FakeMonitor()
        self.monitors.append(monitor)
        self.monitor_factory_calls.append((generation, monitor))
        return monitor

    def service(
        self,
        *,
        policy: RecoveryPolicy | None = None,
        clock: FakeClock | None = None,
        run_thread: bool = True,
    ) -> PlayerSharingService:
        dependencies = SharingServiceDependencies(
            prepare_profile=lambda _create: self.profile,
            identity_initialized=lambda _layout: True,
            verifier_status=lambda _layout: self.credential_state,
            resolve_companion=lambda: CompanionResolution(
                "resolved", "resolved", Path("fake-opentunnel"), "a" * 64
            ),
            initialize_identity=lambda _layout, _resolution, _confirmed: None,  # type: ignore[arg-type]
            controller_factory=lambda _layout: self.controller,
            issue_credential=lambda _layout: IssuedCredential(SENTINEL_CREDENTIAL),
            rotate_credential=self._rotate_credential,
            revoke_access=self._revoke_access,
            relay_monitor_factory=self.make_monitor,
        )
        selected_clock = clock or FakeClock()
        return PlayerSharingService(
            dependencies,
            recovery_policy=policy,
            supervision_clock=selected_clock.clock,
            supervision_sleeper=selected_clock.sleep,
            run_supervision_thread=run_thread,
        )

    def _rotate_credential(self, _layout: ProfileLayout) -> IssuedCredential:
        self.credential_state = VerifierStatus(
            "present", "present", 2, "2026-11-11T00:01:00Z"
        )
        return IssuedCredential(SENTINEL_CREDENTIAL)

    def _revoke_access(self, _layout: ProfileLayout) -> VerifierLoad:
        self.credential_state = VerifierStatus("absent", "verifier_absent")
        return VerifierLoad("absent", "verifier_absent")


def _observation(
    generation: int,
    *,
    child_state: str = "alive",
    route_healthy: bool = True,
    listener_healthy: bool = True,
) -> RelayHealthObservation:
    return RelayHealthObservation(
        generation,
        child_state,  # type: ignore[arg-type]
        route_healthy,
        listener_healthy,
    )


class FakeOwnedCompanion:
    def __init__(self, layout: ProfileLayout, executable_path: Path) -> None:
        self.state = "running"
        self.profile_layout = layout
        self.executable_path = executable_path
        self.diagnostics_calls = 0

    def diagnostics(self) -> dict[str, object]:
        self.diagnostics_calls += 1
        return {
            "state": self.state,
            "reason_code": None,
            "exit_code_bucket": None,
            "raw_output": SENTINEL_OUTPUT,
        }


class ProductionRelayMonitorTests(unittest.TestCase):
    def make_controller(
        self,
        route_probe: Callable[[object, int], RouteStatus],
    ) -> SharingController:
        class Binder:
            generation = 7
            is_bound = True
            state = "bound"

            @staticmethod
            def begin_generation(_generation: int) -> bool:
                return True

            @staticmethod
            def bind(_origin: object, _generation: object, _ready: bool) -> bool:
                return True

            @staticmethod
            def clear(_reason: str) -> None:
                return None

        dependencies = SharingDependencies(
            local_runtime_ok=lambda: True,
            assets_ok=lambda: True,
            start_player_listener=lambda: True,
            stop_player_listener=lambda: None,
            listener_authenticated_probe=lambda: True,
            load_verifier=lambda: object(),
            resolve_companion=lambda: CompanionResolution(
                "resolved", "resolved", Path("fake-opentunnel"), "a" * 64
            ),
            identity_initialized=lambda: True,
            start_companion=lambda _generation: None,  # type: ignore[arg-type]
            route_status=route_probe,
            origin_binder=Binder(),  # type: ignore[arg-type]
            route_wait_seconds=0.0,
        )
        controller = SharingController(dependencies)
        controller._generation = 7
        controller._lifecycle_revision = 3
        controller._state = SharingState.READY
        controller._reason = "ready"
        controller._checks = _ready_checks()
        controller._companion = FakeOwnedCompanion(
            _layout(Path("fixture")), Path("fixture/opentunnel")
        )  # type: ignore[assignment]
        controller._companion_generation = 7
        controller._companion_started = True
        return controller

    def test_production_monitor_uses_owned_diagnostics_route_and_loopback_probe(self) -> None:
        route_calls: list[tuple[object, int]] = []

        def route_probe(handle: object, generation: int) -> RouteStatus:
            route_calls.append((handle, generation))
            return RouteStatus(True, SENTINEL_ORIGIN, generation)

        controller = self.make_controller(route_probe)
        handle = controller._companion
        listener_generations: list[int] = []
        monitor = ProductionRelayMonitor(
            controller,
            lambda generation: listener_generations.append(generation) is None,
        )

        observation = monitor.observe(7)

        self.assertEqual(observation.generation, 7)
        self.assertEqual(observation.child_state, "alive")
        self.assertTrue(observation.route_healthy)
        self.assertTrue(observation.listener_healthy)
        self.assertEqual(listener_generations, [7])
        self.assertEqual(route_calls, [(handle, 7)])
        self.assertEqual(handle.diagnostics_calls, 1)  # type: ignore[union-attr]
        self.assertNotIn(SENTINEL_ORIGIN, repr(observation))
        self.assertNotIn(SENTINEL_OUTPUT, repr(observation))

    def test_production_monitor_tags_stale_generation_unhealthy(self) -> None:
        controller = self.make_controller(
            lambda _handle, generation: RouteStatus(True, SENTINEL_ORIGIN, generation)
        )
        listener_calls: list[int] = []
        monitor = ProductionRelayMonitor(
            controller,
            lambda generation: listener_calls.append(generation) is None,
        )

        observation = monitor.observe(8)

        self.assertEqual(observation.generation, 8)
        self.assertEqual(observation.child_state, "unknown")
        self.assertFalse(observation.route_healthy)
        self.assertFalse(observation.listener_healthy)
        self.assertEqual(listener_calls, [])

    def test_production_monitor_sanitizes_probe_exceptions(self) -> None:
        controller = self.make_controller(
            lambda _handle, generation: RouteStatus(True, SENTINEL_ORIGIN, generation)
        )

        def broken_listener(_generation: int) -> bool:
            raise RuntimeError(SENTINEL_OUTPUT + " " + SENTINEL_ORIGIN)

        monitor = ProductionRelayMonitor(controller, broken_listener)
        with self.assertRaisesRegex(RuntimeError, "^monitor_failed$") as raised:
            monitor.observe(7)
        self.assertNotIn(SENTINEL_OUTPUT, str(raised.exception))
        self.assertNotIn(SENTINEL_ORIGIN, str(raised.exception))

    def test_production_composition_supplies_the_production_monitor(self) -> None:
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
            controller = self.make_controller(
                lambda _handle, generation: RouteStatus(
                    True, SENTINEL_ORIGIN, generation
                )
            )
            dependencies = composition.dependencies()
            self.assertIsNotNone(dependencies.relay_monitor_factory)
            with mock.patch.object(
                composition, "_listener_authenticated_probe", return_value=True
            ):
                monitor = dependencies.relay_monitor_factory(controller, 7)  # type: ignore[misc]
                self.assertIsInstance(monitor, ProductionRelayMonitor)
                observation = monitor.observe(7)
            self.assertTrue(observation.listener_healthy)
            self.assertEqual(observation.generation, 7)


class PlayerSharingProductionSupervisionTests(unittest.TestCase):
    def test_monitor_setup_failure_fails_closed_with_bounded_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service(run_thread=False)

            def failed_factory(
                _controller: SharingController, _generation: int
            ) -> FakeMonitor:
                raise RuntimeError(SENTINEL_OUTPUT)

            service._deps = replace(
                service._deps,
                relay_monitor_factory=failed_factory,
            )

            result = service.start()

            self.assertFalse(result.ok)
            self.assertEqual(result.status.lifecycle.state, SharingState.FAILED)
            self.assertEqual(result.status.supervision.state, "failed")  # type: ignore[union-attr]
            self.assertEqual(result.status.supervision.reason, "monitor_failed")  # type: ignore[union-attr]
            self.assertNotIn(SENTINEL_OUTPUT, repr(result.status))

    def test_supervision_starts_only_after_ready_and_duplicate_start_reuses_thread(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service(
                policy=RecoveryPolicy(health_check_interval=60.0)
            )

            self.assertIsNone(service.supervision_status())
            self.assertEqual(service.start().status.lifecycle.state, SharingState.READY)
            self.assertEqual(len(fake.monitor_factory_calls), 1)
            runtime = service._supervision
            self.assertIsNotNone(runtime)
            self.assertTrue(runtime.thread.daemon)  # type: ignore[union-attr]
            self.assertTrue(runtime.thread.name.startswith(THREAD_PREFIX))  # type: ignore[union-attr]
            self.assertTrue(runtime.thread.is_alive())  # type: ignore[union-attr]
            self.assertEqual(service.supervision_status().state, "ready")  # type: ignore[union-attr]

            duplicate = service.start()

            self.assertTrue(duplicate.ok)
            self.assertIs(service._supervision, runtime)
            self.assertEqual(len(fake.monitor_factory_calls), 1)
            self.assertEqual(fake.monitors[0].calls, 0)
            service.stop()
            self.assertFalse(runtime.thread.is_alive())  # type: ignore[union-attr]

    def test_relay_loss_uses_bounded_controller_recovery_and_full_readiness(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            clock = FakeClock()
            policy = RecoveryPolicy(
                max_attempts=2,
                backoff_schedule=(0.5, 1.0),
                health_check_interval=60.0,
            )
            service = fake.service(policy=policy, clock=clock, run_thread=False)
            fake.controller.recovery_results.extend((False, True))
            started = service.start()
            monitor = fake.monitors[0]
            monitor.default_healthy = False
            self.assertTrue(started.ok)

            degraded = service.tick_supervision()
            first_attempt = service.tick_supervision()
            recovered = service.tick_supervision()

            self.assertEqual(degraded.state, "degraded")  # type: ignore[union-attr]
            self.assertEqual(degraded.attempts_used, 0)  # type: ignore[union-attr]
            self.assertEqual(first_attempt.state, "degraded")  # type: ignore[union-attr]
            self.assertEqual(first_attempt.attempts_used, 1)  # type: ignore[union-attr]
            self.assertEqual(recovered.state, "ready")  # type: ignore[union-attr]
            self.assertEqual(recovered.attempts_used, 2)  # type: ignore[union-attr]
            self.assertEqual(clock.delays, [0.5, 1.0])
            self.assertEqual(fake.controller.recover_calls, 2)
            self.assertEqual(monitor.generations, [1, 1, 1])
            self.assertTrue(fake.controller.status().checks.ready)
            self.assertEqual(fake.gameplay_calls, [])

    def test_monitor_exception_becomes_unhealthy_bounded_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service(run_thread=False)
            service.start()
            fake.monitors[0].observations.append(
                RuntimeError(SENTINEL_OUTPUT + " " + SENTINEL_ORIGIN)
            )

            result = service.tick_supervision()

            self.assertEqual(result.state, "degraded")  # type: ignore[union-attr]
            self.assertEqual(result.reason, "monitor_failed")  # type: ignore[union-attr]
            self.assertNotIn(SENTINEL_OUTPUT, repr(service.status()))
            self.assertNotIn(SENTINEL_ORIGIN, repr(service.status()))

    def test_exhaustion_fails_and_terminates_the_daemon_thread(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            clock = FakeClock()
            policy = RecoveryPolicy(
                max_attempts=2,
                backoff_schedule=(0.001, 0.001),
                health_check_interval=0.001,
            )
            fake.controller.recovery_results.extend((False, False))
            service = fake.service(policy=policy, clock=clock)
            self.assertTrue(service.start().ok)
            monitor = fake.monitors[0]
            monitor.default_healthy = False
            runtime = service._supervision
            self.assertTrue(fake.controller.failed_event.wait(2.0))
            self.assertIsNotNone(runtime)
            runtime.thread.join(timeout=1.0)  # type: ignore[union-attr]

            self.assertFalse(runtime.thread.is_alive())  # type: ignore[union-attr]
            self.assertEqual(fake.controller.status().state, SharingState.FAILED)
            self.assertEqual(service.supervision_status().state, "failed")  # type: ignore[union-attr]
            self.assertEqual(service.supervision_status().attempts_used, 2)  # type: ignore[union-attr]
            self.assertEqual(fake.gameplay_calls, [])

    def test_stop_shutdown_rotate_and_revoke_cancel_and_join_workers(self) -> None:
        for operation in ("stop", "shutdown", "rotate", "revoke"):
            with self.subTest(operation=operation):
                with tempfile.TemporaryDirectory(dir="tmp") as scratch:
                    fake = FakeServiceDependencies(Path(scratch))
                    service = fake.service(
                        policy=RecoveryPolicy(health_check_interval=60.0)
                    )
                    self.assertTrue(service.start().ok)
                    old_runtime = service._supervision
                    old_thread = old_runtime.thread  # type: ignore[union-attr]
                    if operation == "stop":
                        service.stop()
                    elif operation == "shutdown":
                        service.shutdown()
                    elif operation == "rotate":
                        service.rotate_access()
                    else:
                        service.revoke_access()

                    self.assertTrue(old_runtime.stop_event.is_set())  # type: ignore[union-attr]
                    self.assertFalse(old_thread.is_alive())  # type: ignore[union-attr]
                    self.assertEqual(fake.monitors[0].calls, 0)
                    if operation == "rotate":
                        self.assertIsNot(service._supervision, old_runtime)
                        self.assertTrue(service._supervision.thread.is_alive())  # type: ignore[union-attr]
                        service.stop()
                    else:
                        self.assertEqual(fake.controller.status().state, SharingState.OFF)

    def test_status_snapshot_is_bounded_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service(run_thread=False)
            service.start()
            fake.monitors[0].observations.append(RuntimeError(SENTINEL_OUTPUT))
            service.tick_supervision()

            status = service.status()
            supervision = service.supervision_status()

            self.assertIsInstance(status.supervision, RelaySupervisionSnapshot)
            self.assertEqual(status.supervision.state, "degraded")  # type: ignore[union-attr]
            self.assertEqual(status.supervision.generation, 1)  # type: ignore[union-attr]
            self.assertEqual(status.supervision.attempts_used, 0)  # type: ignore[union-attr]
            self.assertEqual(status.supervision.attempts_max, 5)  # type: ignore[union-attr]
            self.assertEqual(status.supervision.next_delay_bucket, "short")  # type: ignore[union-attr]
            self.assertEqual(supervision, status.supervision)
            self.assertNotIn(SENTINEL_CREDENTIAL, repr(status))
            self.assertNotIn(SENTINEL_ORIGIN, repr(status))
            self.assertNotIn(SENTINEL_OUTPUT, repr(status))

    def test_fifty_start_stop_cycles_leave_no_monitor_threads(self) -> None:
        with tempfile.TemporaryDirectory(dir="tmp") as scratch:
            fake = FakeServiceDependencies(Path(scratch))
            service = fake.service(
                policy=RecoveryPolicy(health_check_interval=60.0)
            )
            before = sum(
                thread.name.startswith(THREAD_PREFIX)
                for thread in threading.enumerate()
            )

            for _index in range(50):
                self.assertTrue(service.start().ok)
                runtime = service._supervision
                self.assertIsNotNone(runtime)
                service.stop()
                self.assertFalse(runtime.thread.is_alive())  # type: ignore[union-attr]

            after = sum(
                thread.name.startswith(THREAD_PREFIX)
                for thread in threading.enumerate()
            )
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
