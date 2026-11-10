# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free bounded relay supervision and recovery tests."""

from __future__ import annotations

import ast
import unittest
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.controller import (
    RouteStatus,
    SharingController,
    SharingDependencies,
    SharingState,
)
from web.extensions.opentunnel_sharing.origin_binding import PublicOriginBinder
from web.extensions.opentunnel_sharing.relay_supervision import (
    RecoveryPolicy,
    RelayHealthObservation,
    RelaySupervisor,
)

PLAYER_ORIGIN = "https://sharing-route.example"
CHANGED_ORIGIN = "https://new-sharing-route.example:9443"


@dataclass(frozen=True, slots=True)
class FakeVerifier:
    state: str = "present"
    verifier: object | None = object()


class FakeSecurity:
    def __init__(self) -> None:
        self.origin: str | None = None
        self.generation: int | None = None

    @property
    def public_origin_status(self) -> tuple[bool, int | None]:
        return self.origin is not None, self.generation

    def bind_public_origin(self, generation: int, origin: object) -> bool:
        if not isinstance(origin, str):
            return False
        if self.origin is not None:
            return self.origin == origin and self.generation == generation
        self.origin = origin
        self.generation = generation
        return True

    def clear_public_origin(self, _reason: str | None = None) -> None:
        self.origin = None
        self.generation = None


class FakeCompanion:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self._state = "stopped"
        self._reaped = True
        self.start_calls = 0
        self.stop_calls = 0
        self.reap_calls = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def reaped(self) -> bool:
        return self._reaped

    def start(self, _deadline: float) -> str:
        self.start_calls += 1
        self.events.append("companion_start")
        self._state = "running"
        self._reaped = False
        return "running"

    def stop(self, _deadline: float) -> bool:
        self.stop_calls += 1
        self.events.append("companion_stop")
        if self._state == "exited":
            self.reap_calls += 1
            self.events.append("companion_reap")
        if self._state in {"running", "exited", "stopped"}:
            self._state = "stopped"
            self._reaped = True
            return True
        return self._reaped

    def diagnostics(self) -> dict[str, object]:
        return {"state": self._state}

    def exit(self) -> None:
        self._state = "exited"
        self._reaped = False


class FakeMonitor:
    def __init__(self) -> None:
        self.observations: deque[object] = deque()
        self.default = RelayHealthObservation(1, "alive", True, True)
        self.calls = 0
        self.generations: list[int] = []

    def observe(self, generation: int) -> RelayHealthObservation:
        self.calls += 1
        self.generations.append(generation)
        result = self.observations.popleft() if self.observations else self.default
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            result = result(generation)
        return result  # type: ignore[return-value]


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.delays: list[float] = []
        self.on_sleep: Callable[[], None] | None = None

    def clock(self) -> float:
        return self.now

    def sleep(self, delay: float, cancel_event: object) -> bool:
        self.delays.append(delay)
        callback = self.on_sleep
        self.on_sleep = None
        if callback is not None:
            callback()
        self.now += delay
        return bool(getattr(cancel_event, "is_set")())


class FakeLocalRuntime:
    """A local runtime/queue spy that supervision must never call."""

    def __init__(self) -> None:
        self.available = True
        self.pending = ["uncertain player input"]
        self.calls: list[str] = []

    def drain_queue(self) -> list[str]:
        self.calls.append("drain")
        return self.pending[:]

    def resubmit(self, _input: str) -> None:
        self.calls.append("resubmit")


class SharingFixture:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.local_runtime = FakeLocalRuntime()
        self.security = FakeSecurity()
        self.binder = PublicOriginBinder(self.security)  # type: ignore[arg-type]
        self.resolution = CompanionResolution(
            state="resolved", reason="resolved", path=Path("fixture-opentunnel")
        )
        self.listener_running = False
        self.listener_start_calls = 0
        self.listener_stop_calls = 0
        self.listener_probe_ok = True
        self.route_results: deque[RouteStatus] = deque()
        self.route_calls = 0
        self.companions: list[FakeCompanion] = []
        self.deps = SharingDependencies(
            local_runtime_ok=lambda: self.local_runtime.available,
            assets_ok=lambda: True,
            start_player_listener=self.start_listener,
            stop_player_listener=self.stop_listener,
            listener_authenticated_probe=lambda: self.listener_probe_ok,
            load_verifier=lambda: FakeVerifier(),
            resolve_companion=lambda: self.resolution,
            identity_initialized=lambda: True,
            start_companion=self.start_companion,
            route_status=self.route_status,
            origin_binder=self.binder,
            companion_start_deadline_seconds=1.0,
            companion_stop_deadline_seconds=1.0,
            route_wait_seconds=0.0,
        )
        self.controller = SharingController(self.deps)

    def start_listener(self) -> bool:
        self.listener_start_calls += 1
        self.listener_running = True
        return True

    def stop_listener(self) -> None:
        self.listener_stop_calls += 1
        self.listener_running = False

    def start_companion(self, _generation: int) -> FakeCompanion:
        self.events.append("companion_create")
        companion = FakeCompanion(self.events)
        self.companions.append(companion)
        return companion

    def route_status(self, _companion: object, generation: int) -> RouteStatus:
        self.route_calls += 1
        if self.route_results:
            return self.route_results.popleft()
        return RouteStatus(True, PLAYER_ORIGIN, generation)


def _observation(
    generation: int,
    *,
    child_state: str = "alive",
    route_healthy: bool = True,
    listener_healthy: bool = True,
    exit_code_bucket: str | None = None,
) -> RelayHealthObservation:
    return RelayHealthObservation(
        generation=generation,
        child_state=child_state,  # type: ignore[arg-type]
        route_healthy=route_healthy,
        listener_healthy=listener_healthy,
        exit_code_bucket=exit_code_bucket,  # type: ignore[arg-type]
    )


class PlayerSharingSupervisorTests(unittest.TestCase):
    def make_supervisor(
        self,
        fixture: SharingFixture,
        monitor: FakeMonitor | None = None,
        policy: RecoveryPolicy | None = None,
        clock: FakeTime | None = None,
    ) -> tuple[RelaySupervisor, FakeMonitor, FakeTime]:
        selected_monitor = monitor or FakeMonitor()
        selected_clock = clock or FakeTime()
        selected_policy = policy or RecoveryPolicy()
        supervisor = RelaySupervisor(
            fixture.controller,
            selected_monitor,
            selected_policy,
            selected_clock.clock,
            selected_clock.sleep,
        )
        return supervisor, selected_monitor, selected_clock

    def test_relay_loss_withdraws_invitation_and_preserves_local_play(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        runtime = fixture.local_runtime
        monitor = FakeMonitor()
        monitor.observations.append(_observation(1, route_healthy=False))
        supervisor, _monitor, clock = self.make_supervisor(fixture, monitor)

        degraded = supervisor.tick()

        self.assertEqual(degraded.state, "degraded")
        self.assertEqual(degraded.reason, "route_unhealthy")
        self.assertEqual(degraded.attempts_used, 0)
        self.assertEqual(degraded.next_delay_bucket, "short")
        self.assertEqual(fixture.controller.state, SharingState.DEGRADED)
        self.assertTrue(fixture.controller.status().checks.local_runtime)
        self.assertIsNone(fixture.controller.invitation())
        self.assertFalse(fixture.binder.is_bound)
        self.assertEqual(runtime.pending, ["uncertain player input"])
        self.assertEqual(runtime.calls, [])
        self.assertEqual(clock.delays, [])

        recovered = supervisor.tick()

        self.assertEqual(recovered.state, "ready")
        self.assertTrue(fixture.local_runtime.available)
        self.assertEqual(runtime.pending, ["uncertain player input"])
        self.assertEqual(runtime.calls, [])

    def test_recovery_succeeds_on_first_attempt_after_full_readiness(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        monitor = FakeMonitor()
        monitor.observations.append(_observation(1, route_healthy=False))
        supervisor, _monitor, clock = self.make_supervisor(fixture, monitor)

        self.assertEqual(supervisor.tick().state, "degraded")
        recovered = supervisor.tick()

        self.assertEqual(recovered.state, "ready")
        self.assertEqual(recovered.attempts_used, 1)
        self.assertEqual(recovered.next_delay_bucket, "none")
        self.assertEqual(fixture.controller.status().checks.ready, True)
        self.assertEqual(fixture.controller.invitation(), PLAYER_ORIGIN)
        self.assertEqual(clock.delays, [1.0])

    def test_recovery_succeeds_at_attempt_n_with_exact_backoff_schedule(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        policy = RecoveryPolicy(max_attempts=3, backoff_schedule=(1.0, 2.0, 4.0))
        monitor = FakeMonitor()
        monitor.default = _observation(1, route_healthy=False)
        supervisor, _monitor, clock = self.make_supervisor(
            fixture, monitor, policy
        )
        self.assertEqual(supervisor.tick().state, "degraded")
        fixture.route_results.extend(
            (
                RouteStatus(False, PLAYER_ORIGIN, 1),
                RouteStatus(False, PLAYER_ORIGIN, 1),
                RouteStatus(True, PLAYER_ORIGIN, 1),
            )
        )

        results = [supervisor.tick() for _index in range(3)]

        self.assertEqual([item.attempts_used for item in results], [1, 2, 3])
        self.assertEqual(results[-1].state, "ready")
        self.assertEqual(clock.delays, [1.0, 2.0, 4.0])
        self.assertTrue(fixture.controller.status().checks.ready)

    def test_route_recovery_does_not_override_listener_readiness_failure(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        fixture.listener_probe_ok = False
        before_routes = fixture.route_calls
        monitor = FakeMonitor()
        monitor.observations.append(
            _observation(1, route_healthy=True, listener_healthy=False)
        )
        supervisor, _monitor, _clock = self.make_supervisor(fixture, monitor)

        self.assertEqual(supervisor.tick().reason, "listener_failed")
        recovered = supervisor.tick()

        self.assertEqual(recovered.state, "degraded")
        self.assertEqual(recovered.attempts_used, 1)
        self.assertEqual(fixture.controller.reason, "listener_failed")
        self.assertFalse(fixture.controller.status().checks.ready)
        self.assertEqual(fixture.route_calls, before_routes)
        self.assertIsNone(fixture.controller.invitation())

    def test_changed_origin_is_freshly_bound_after_recovery(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        generation = fixture.controller.generation
        fixture.route_results.extend(
            (
                RouteStatus(True, CHANGED_ORIGIN, generation),
                RouteStatus(True, CHANGED_ORIGIN, generation),
            )
        )
        monitor = FakeMonitor()
        monitor.observations.append(_observation(generation, route_healthy=False))
        supervisor, _monitor, _clock = self.make_supervisor(fixture, monitor)

        self.assertEqual(supervisor.tick().state, "degraded")
        self.assertEqual(supervisor.tick().state, "ready")

        self.assertEqual(fixture.controller.invitation(), CHANGED_ORIGIN)
        self.assertEqual(fixture.security.public_origin_status, (True, generation))
        self.assertFalse(fixture.binder.bind(PLAYER_ORIGIN, generation, ready=True))
        self.assertFalse(fixture.binder.is_bound)
        self.assertIsNone(fixture.controller.invitation())

    def test_child_exit_is_reaped_before_controller_restarts_companion(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        previous = fixture.companions[0]
        previous.exit()
        monitor = FakeMonitor()
        monitor.observations.append(
            _observation(1, child_state="exited", exit_code_bucket="failure")
        )
        supervisor, _monitor, _clock = self.make_supervisor(fixture, monitor)

        self.assertEqual(supervisor.tick().state, "degraded")
        recovered = supervisor.tick()

        self.assertEqual(recovered.state, "ready")
        self.assertEqual(previous.reap_calls, 1)
        self.assertEqual(previous.stop_calls, 1)
        self.assertEqual(len(fixture.companions), 2)
        self.assertEqual(fixture.companions[1].start_calls, 1)
        self.assertLess(
            fixture.events.index("companion_reap"),
            len(fixture.events) - 1 - fixture.events[::-1].index("companion_start"),
        )

    def test_exhausted_budget_fails_and_stops_resources_until_new_start(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        policy = RecoveryPolicy(max_attempts=2, backoff_schedule=(0.5, 1.0))
        monitor = FakeMonitor()
        monitor.observations.append(_observation(1, route_healthy=False))
        supervisor, _monitor, _clock = self.make_supervisor(
            fixture, monitor, policy
        )
        self.assertEqual(supervisor.tick().state, "degraded")
        fixture.route_results.extend(
            (
                RouteStatus(False, PLAYER_ORIGIN, 1),
                RouteStatus(False, PLAYER_ORIGIN, 1),
            )
        )

        supervisor.tick()
        failed = supervisor.tick()

        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.reason, "reconnect_budget_exhausted")
        self.assertEqual(failed.attempts_used, 2)
        self.assertEqual(fixture.controller.state, SharingState.FAILED)
        self.assertEqual(fixture.controller.reason, "reconnect_budget_exhausted")
        self.assertIsNone(fixture.controller.invitation())
        self.assertFalse(fixture.binder.is_bound)
        self.assertTrue(fixture.local_runtime.available)
        self.assertEqual(
            fixture.local_runtime.pending, ["uncertain player input"]
        )
        self.assertEqual(fixture.local_runtime.calls, [])
        self.assertEqual(fixture.listener_stop_calls, 1)
        self.assertTrue(fixture.companions[0].reaped)
        self.assertEqual(fixture.companions[0].stop_calls, 1)

        monitor_calls = monitor.calls
        self.assertEqual(supervisor.tick(), failed)
        self.assertEqual(monitor.calls, monitor_calls)

        old_generation = fixture.controller.generation
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        restarted = supervisor.tick()
        self.assertGreater(restarted.generation, old_generation)
        self.assertEqual(restarted.state, "ready")
        self.assertEqual(restarted.attempts_used, 0)

    def test_supervisor_stop_during_backoff_cancels_without_recovery(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        monitor = FakeMonitor()
        monitor.observations.append(_observation(1, route_healthy=False))
        supervisor, _monitor, clock = self.make_supervisor(fixture, monitor)
        self.assertEqual(supervisor.tick().state, "degraded")
        clock.on_sleep = supervisor.stop
        before_routes = fixture.route_calls

        stopped = supervisor.tick()

        self.assertEqual(stopped.state, "stopped")
        self.assertEqual(stopped.attempts_used, 0)
        self.assertEqual(fixture.route_calls, before_routes)
        self.assertEqual(clock.delays, [1.0])

    def test_controller_stop_and_rotation_cancel_pending_recovery(self) -> None:
        for operation in ("stop", "shutdown", "rotate"):
            with self.subTest(operation=operation):
                fixture = SharingFixture()
                self.assertEqual(fixture.controller.start().state, SharingState.READY)
                monitor = FakeMonitor()
                monitor.observations.append(
                    _observation(1, route_healthy=False)
                )
                supervisor, _monitor, clock = self.make_supervisor(fixture, monitor)
                self.assertEqual(supervisor.tick().state, "degraded")
                before_routes = fixture.route_calls
                if operation == "stop":
                    clock.on_sleep = fixture.controller.stop
                elif operation == "shutdown":
                    clock.on_sleep = fixture.controller.shutdown
                else:
                    clock.on_sleep = lambda: fixture.controller.rotate(lambda: None)

                result = supervisor.tick()

                self.assertIn(result.state, {"stopped", "ready"})
                self.assertEqual(result.attempts_used, 0)
                self.assertEqual(
                    fixture.route_calls - before_routes,
                    1 if operation == "rotate" else 0,
                )

    def test_stale_generation_observations_and_ticks_are_ignored(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        monitor = FakeMonitor()
        monitor.observations.append(_observation(0, child_state="exited"))
        supervisor, _monitor, _clock = self.make_supervisor(fixture, monitor)

        stale = supervisor.tick()

        self.assertEqual(stale.state, "ready")
        self.assertEqual(stale.attempts_used, 0)
        self.assertEqual(fixture.controller.state, SharingState.READY)

        monitor.observations.append(_observation(1, route_healthy=False))
        self.assertEqual(supervisor.tick().state, "degraded")
        fixture.controller.stop()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        before_routes = fixture.route_calls

        reset = supervisor.tick()

        self.assertEqual(reset.state, "ready")
        self.assertEqual(reset.attempts_used, 0)
        self.assertEqual(reset.generation, fixture.controller.generation)
        self.assertEqual(fixture.route_calls, before_routes)

    def test_old_health_observation_cannot_degrade_a_restarted_generation(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        old_generation = fixture.controller.generation
        monitor = FakeMonitor()

        def restart_during_observation(generation: int) -> RelayHealthObservation:
            fixture.controller.stop()
            fixture.controller.start()
            return _observation(generation, route_healthy=False)

        monitor.observations.append(restart_during_observation)
        supervisor, _monitor, _clock = self.make_supervisor(fixture, monitor)

        result = supervisor.tick()

        self.assertGreater(fixture.controller.generation, old_generation)
        self.assertEqual(result.state, "ready")
        self.assertEqual(result.generation, fixture.controller.generation)
        self.assertEqual(fixture.controller.state, SharingState.READY)
        self.assertEqual(fixture.controller.invitation(), PLAYER_ORIGIN)

    def test_late_budget_failure_cannot_fail_a_new_controller_lifecycle(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        old_generation = fixture.controller.generation
        old_revision = fixture.controller.lifecycle_revision
        fixture.controller.stop()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)

        result = fixture.controller.mark_failed(
            "reconnect_budget_exhausted",
            expected_generation=old_generation,
            expected_lifecycle_revision=old_revision,
            expected_state=SharingState.DEGRADED,
        )

        self.assertEqual(result.state, SharingState.READY)
        self.assertTrue(result.checks.ready)
        self.assertTrue(fixture.listener_running)
        self.assertEqual(fixture.controller.invitation(), PLAYER_ORIGIN)

    def test_duplicate_degraded_observations_do_not_duplicate_notice(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        policy = RecoveryPolicy(max_attempts=3, backoff_schedule=(1.0, 2.0, 4.0))
        monitor = FakeMonitor()
        monitor.default = _observation(1, route_healthy=False)
        supervisor, _monitor, _clock = self.make_supervisor(
            fixture, monitor, policy
        )
        fixture.route_results.extend(
            (
                RouteStatus(False, PLAYER_ORIGIN, 1),
                RouteStatus(False, PLAYER_ORIGIN, 1),
            )
        )
        degrade_calls: list[str] = []
        original_mark_degraded = fixture.controller.mark_degraded

        def record_degraded(
            reason: object = "readiness_regressed", **options: object
        ) -> object:
            degrade_calls.append(str(reason))
            return original_mark_degraded(reason, **options)  # type: ignore[arg-type]

        setattr(fixture.controller, "mark_degraded", record_degraded)

        supervisor.tick()
        supervisor.tick()
        supervisor.tick()

        self.assertEqual(degrade_calls, ["route_unhealthy"])
        self.assertEqual(supervisor.snapshot().attempts_used, 2)

    def test_monitor_exception_is_unhealthy_and_diagnostics_are_bounded(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        monitor = FakeMonitor()
        monitor.observations.append(
            RuntimeError("SENTINEL_RAW_COMPANION_OUTPUT https://private.example")
        )
        monitor.observations.append(_observation(1))
        supervisor, _monitor, _clock = self.make_supervisor(fixture, monitor)

        degraded = supervisor.tick()

        self.assertEqual(degraded.state, "degraded")
        self.assertEqual(degraded.reason, "monitor_failed")
        self.assertNotIn("SENTINEL", repr(degraded))
        self.assertNotIn("private.example", repr(supervisor.snapshot()))
        self.assertEqual(supervisor.tick().state, "ready")

    def test_recovery_exception_uses_a_bounded_diagnostic(self) -> None:
        fixture = SharingFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        monitor = FakeMonitor()
        monitor.observations.append(_observation(1, route_healthy=False))
        supervisor, _monitor, _clock = self.make_supervisor(fixture, monitor)
        self.assertEqual(supervisor.tick().state, "degraded")

        def fail_recovery() -> object:
            raise RuntimeError("SENTINEL_PRIVATE_RECOVERY_DETAILS")

        fixture.controller.recover = fail_recovery  # type: ignore[method-assign]
        failed_attempt = supervisor.tick()

        self.assertEqual(failed_attempt.state, "degraded")
        self.assertEqual(failed_attempt.reason, "readiness_regressed")
        self.assertEqual(failed_attempt.attempts_used, 1)
        self.assertNotIn("SENTINEL", repr(failed_attempt))
        fixture.controller.stop()

    def test_recovery_policy_rejects_unbounded_values(self) -> None:
        invalid_policies = (
            {"max_attempts": 0, "backoff_schedule": ()},
            {"max_attempts": 11, "backoff_schedule": (1.0,) * 11},
            {"max_attempts": 1, "backoff_schedule": (0.0,)},
            {"max_attempts": 1, "backoff_schedule": (60.1,)},
            {"max_attempts": 1, "backoff_schedule": (1.0,), "health_check_interval": 0},
            {"max_attempts": 1, "backoff_schedule": (1.0,), "jitter_seconds": 1.0},
            {"max_attempts": 10, "backoff_schedule": (40.0,) * 10},
        )
        for options in invalid_policies:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    RecoveryPolicy(**options)  # type: ignore[arg-type]

    def test_supervisor_has_no_gameplay_or_player_input_imports(self) -> None:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "web/extensions/opentunnel_sharing/relay_supervision.py"
        )
        tree = ast.parse(module_path.read_text(encoding="ascii"))
        forbidden = (
            "utils",
            "main",
            "run_web",
            "web.extensions.player.runtime_gateway",
            "web.extensions.player.gateway",
            "web.extensions.player.sync",
        )
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
        for module in imported:
            with self.subTest(module=module):
                self.assertFalse(
                    any(
                        module == prefix or module.startswith(prefix + ".")
                        for prefix in forbidden
                    )
                )


if __name__ == "__main__":
    unittest.main()
