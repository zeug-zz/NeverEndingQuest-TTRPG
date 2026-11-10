# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free deterministic race tests for player-sharing operations."""

from __future__ import annotations

import random
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.controller import (
    CompanionHandle,
    RouteStatus,
    SharingController,
    SharingDependencies,
    SharingSnapshot,
    SharingState,
)
from web.extensions.opentunnel_sharing.origin_binding import PublicOriginBinder

PLAYER_ORIGIN = "https://sharing-route.example"
JOIN_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class FakeVerifier:
    state: str = "present"
    verifier: object | None = object()


class Gate:
    """A one-shot barrier which pauses one dependency callback."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def pause(self) -> None:
        self.entered.set()
        if not self.release.wait(JOIN_TIMEOUT):
            raise TimeoutError("test_gate_not_released")


class FakePlayerSecurity:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._origin: str | None = None
        self._generation: int | None = None

    @property
    def public_origin_status(self) -> tuple[bool, int | None]:
        with self._lock:
            return self._origin is not None, self._generation

    def bind_public_origin(self, generation: int, origin: str) -> bool:
        with self._lock:
            if self._origin is not None:
                return self._origin == origin and self._generation == generation
            self._origin = origin
            self._generation = generation
            return True

    def clear_public_origin(self, _reason: str | None = None) -> None:
        with self._lock:
            self._origin = None
            self._generation = None


class ControlledBinder:
    def __init__(self) -> None:
        self.security = FakePlayerSecurity()
        self.inner = PublicOriginBinder(self.security)  # type: ignore[arg-type]
        self._lock = threading.Lock()
        self.clear_reasons: list[str] = []
        self.stop_cleared = threading.Event()
        self.rotation_cleared = threading.Event()
        self.bind_gate: Gate | None = None

    @property
    def generation(self) -> int | None:
        return self.inner.generation

    @property
    def is_bound(self) -> bool:
        return self.inner.is_bound

    @property
    def state(self) -> str:
        return self.inner.state

    def begin_generation(self, generation: int) -> bool:
        return self.inner.begin_generation(generation)

    def bind(self, status_origin: object, status_generation: object, ready: bool) -> bool:
        gate = self.bind_gate
        if gate is not None:
            self.bind_gate = None
            gate.pause()
        return self.inner.bind(status_origin, status_generation, ready)

    def clear(self, reason: str) -> None:
        with self._lock:
            self.clear_reasons.append(reason)
        self.inner.clear(reason)
        if reason == "stop":
            self.stop_cleared.set()
        if reason == "rotation":
            self.rotation_cleared.set()


class ControlledCompanion:
    def __init__(self, owner: "RaceFixture", start_gate: Gate | None = None) -> None:
        self.owner = owner
        self.start_gate = start_gate
        self.stop_gate: Gate | None = None
        self._state = "stopped"
        self._reaped = True
        self.start_calls = 0
        self.successful_starts = 0
        self.stop_calls = 0
        self.stop_entered = threading.Event()

    @property
    def state(self) -> str:
        return self._state

    @property
    def reaped(self) -> bool:
        return self._reaped

    def start(self, _deadline: float) -> str:
        self.start_calls += 1
        if self.start_gate is not None:
            self.start_gate.pause()
        self._state = "running"
        self._reaped = False
        self.successful_starts += 1
        self.owner.note_companion_started(self)
        return "running"

    def stop(self, _deadline: float) -> bool:
        self.stop_calls += 1
        self.stop_entered.set()
        if self.stop_gate is not None:
            self.stop_gate.pause()
        if self._state != "running":
            self.owner.unexpected_companion_stop = True
            return False
        self._state = "stopped"
        self._reaped = True
        self.owner.note_companion_stopped(self)
        return True

    def diagnostics(self) -> dict[str, object]:
        return {"state": self._state}


class RaceFixture:
    def __init__(self, blocked_step: str | None = None) -> None:
        self._lock = threading.Lock()
        self.blocked_step = blocked_step
        self.gates: dict[str, Gate] = {}
        for name in ("listener_start", "listener_probe", "companion_start", "route", "binding"):
            if name == blocked_step:
                self.gates[name] = Gate()
        self.binder = ControlledBinder()
        self.binder.bind_gate = self.gates.get("binding")
        self.listener_start_calls = 0
        self.listener_started_count = 0
        self.listener_stop_calls = 0
        self.listener_running = False
        self.listener_overlap = False
        self.companions: list[ControlledCompanion] = []
        self.live_companions = 0
        self.max_live_companions = 0
        self.unexpected_companion_stop = False
        self.route_calls = 0
        self.identity_calls = 0
        self.resolution = CompanionResolution(
            state="resolved", reason="resolved", path=Path("fixture-opentunnel")
        )
        self.credential = FakeVerifier()
        self.rotation_started = threading.Event()
        self.rotation_finished = threading.Event()
        self.verifier_reads_during_rotation: list[bool] = []

        deps = SharingDependencies(
            local_runtime_ok=lambda: True,
            assets_ok=lambda: True,
            start_player_listener=self.start_listener,
            stop_player_listener=self.stop_listener,
            listener_authenticated_probe=self.listener_probe,
            load_verifier=self.load_verifier,
            resolve_companion=self.resolve_companion,
            identity_initialized=self.identity_initialized,
            start_companion=self.start_companion,
            route_status=self.route_status,
            origin_binder=self.binder,  # type: ignore[arg-type]
            route_wait_seconds=0.0,
            companion_start_deadline_seconds=1.0,
            companion_stop_deadline_seconds=1.0,
        )
        self.controller = SharingController(deps)

    def start_listener(self) -> bool:
        with self._lock:
            self.listener_start_calls += 1
            if self.listener_running:
                self.listener_overlap = True
            gate = self.gates.get("listener_start")
        if gate is not None:
            gate.pause()
        with self._lock:
            self.listener_running = True
            self.listener_started_count += 1
        return True

    def stop_listener(self) -> None:
        with self._lock:
            self.listener_stop_calls += 1
            if not self.listener_running:
                self.listener_overlap = True
                return
            self.listener_running = False

    def listener_probe(self) -> bool:
        gate = self.gates.get("listener_probe")
        if gate is not None:
            gate.pause()
        return True

    def load_verifier(self) -> FakeVerifier:
        with self._lock:
            if self.rotation_started.is_set():
                self.verifier_reads_during_rotation.append(
                    self.rotation_finished.is_set()
                )
            return self.credential

    def resolve_companion(self) -> CompanionResolution:
        return self.resolution

    def identity_initialized(self) -> bool:
        with self._lock:
            self.identity_calls += 1
        return True

    def start_companion(self, _generation: int) -> ControlledCompanion:
        handle = ControlledCompanion(self, self.gates.get("companion_start"))
        with self._lock:
            self.companions.append(handle)
        return handle

    def route_status(
        self, _companion: CompanionHandle, generation: int
    ) -> RouteStatus:
        with self._lock:
            self.route_calls += 1
            gate = self.gates.get("route")
            if gate is not None:
                del self.gates["route"]
        if gate is not None:
            gate.pause()
        return RouteStatus(True, PLAYER_ORIGIN, generation)

    def note_companion_started(self, _companion: ControlledCompanion) -> None:
        with self._lock:
            self.live_companions += 1
            self.max_live_companions = max(
                self.max_live_companions, self.live_companions
            )

    def note_companion_stopped(self, _companion: ControlledCompanion) -> None:
        with self._lock:
            self.live_companions -= 1

    def block_companion_stop(self, handle: ControlledCompanion) -> Gate:
        gate = Gate()
        handle.stop_gate = gate
        return gate


def _start_thread(
    target: Callable[[], SharingSnapshot], results: list[SharingSnapshot]
) -> threading.Thread:
    thread = threading.Thread(target=lambda: results.append(target()))
    thread.start()
    return thread


def _join(test: unittest.TestCase, *threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(JOIN_TIMEOUT)
        test.assertFalse(thread.is_alive(), "sharing operation deadlocked")


class PlayerSharingConcurrencyTests(unittest.TestCase):
    def assert_resource_invariants(self, fixture: RaceFixture) -> None:
        snapshot = fixture.controller.status()
        self.assertFalse(fixture.listener_overlap)
        self.assertLessEqual(fixture.max_live_companions, 1)
        self.assertFalse(fixture.unexpected_companion_stop)
        self.assertEqual(
            fixture.listener_started_count,
            fixture.listener_stop_calls + int(fixture.listener_running),
        )
        for companion in fixture.companions:
            self.assertEqual(
                companion.stop_calls,
                int(companion.successful_starts == 1 and companion.state != "running"),
            )
        if snapshot.state is not SharingState.READY:
            self.assertFalse(fixture.binder.is_bound)
            self.assertIsNone(fixture.controller.invitation())

    def test_start_start_is_idempotent_while_listener_start_is_blocked(self) -> None:
        fixture = RaceFixture("listener_start")
        start_results: list[SharingSnapshot] = []
        first = _start_thread(fixture.controller.start, start_results)
        gate = fixture.gates["listener_start"]
        self.assertTrue(gate.entered.wait(JOIN_TIMEOUT))

        duplicate = fixture.controller.start()

        self.assertEqual(duplicate.state, SharingState.STARTING)
        self.assertEqual(fixture.listener_start_calls, 1)
        self.assertEqual(fixture.companions, [])
        gate.release.set()
        _join(self, first)

        self.assertEqual(fixture.controller.state, SharingState.READY)
        self.assertEqual(fixture.listener_start_calls, 1)
        self.assertEqual(len(fixture.companions), 1)
        self.assertEqual(fixture.companions[0].start_calls, 1)
        self.assertEqual(fixture.controller.status().counters.successful_starts, 1)
        self.assertEqual(len(start_results), 1)
        duplicate_ready = fixture.controller.start()
        self.assertEqual(duplicate_ready.state, SharingState.READY)
        self.assertEqual(fixture.listener_start_calls, 1)
        self.assertEqual(len(fixture.companions), 1)
        self.assert_resource_invariants(fixture)

    def test_stop_cancels_start_at_every_blocking_startup_boundary(self) -> None:
        for step in (
            "listener_start",
            "listener_probe",
            "companion_start",
            "route",
            "binding",
        ):
            with self.subTest(step=step):
                fixture = RaceFixture(step)
                start_results: list[SharingSnapshot] = []
                stop_results: list[SharingSnapshot] = []
                gate = fixture.gates[step]
                starter = _start_thread(fixture.controller.start, start_results)
                self.assertTrue(gate.entered.wait(JOIN_TIMEOUT))

                stopper = _start_thread(fixture.controller.stop, stop_results)
                self.assertTrue(fixture.binder.stop_cleared.wait(JOIN_TIMEOUT))
                self.assertEqual(fixture.controller.state, SharingState.STOPPING)
                self.assertIsNone(fixture.controller.invitation())
                gate.release.set()
                _join(self, starter, stopper)

                final = fixture.controller.status()
                self.assertEqual(final.state, SharingState.OFF)
                self.assertEqual(final.reason, "startup_cancelled")
                self.assertEqual(final.counters.successful_starts, 0)
                self.assertFalse(fixture.binder.is_bound)
                self.assertEqual(len(stop_results), 1)
                if fixture.companions:
                    self.assertEqual(fixture.companions[0].successful_starts, 1)
                    self.assertEqual(fixture.companions[0].stop_calls, 1)
                self.assert_resource_invariants(fixture)

    def test_start_queued_while_stopping_runs_after_stop(self) -> None:
        fixture = RaceFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        first_companion = fixture.companions[0]
        stop_gate = fixture.block_companion_stop(first_companion)
        stop_results: list[SharingSnapshot] = []
        start_results: list[SharingSnapshot] = []
        stopper = _start_thread(fixture.controller.stop, stop_results)
        self.assertTrue(first_companion.stop_entered.wait(JOIN_TIMEOUT))
        self.assertEqual(fixture.controller.state, SharingState.STOPPING)

        with fixture.controller._condition:
            start_ticket_before = fixture.controller._next_ticket
        starter = _start_thread(fixture.controller.start, start_results)
        with fixture.controller._condition:
            accepted = fixture.controller._condition.wait_for(
                lambda: fixture.controller._next_ticket > start_ticket_before,
                timeout=JOIN_TIMEOUT,
            )
        self.assertTrue(accepted, "start was not accepted behind stop")
        self.assertEqual(fixture.listener_start_calls, 1)
        stop_gate.release.set()
        _join(self, stopper, starter)

        self.assertEqual(fixture.controller.state, SharingState.READY)
        self.assertEqual(len(fixture.companions), 2)
        self.assertEqual(first_companion.stop_calls, 1)
        self.assertEqual(fixture.listener_start_calls, 2)
        self.assertEqual(fixture.listener_stop_calls, 1)
        self.assertEqual(fixture.live_companions, 1)
        self.assertEqual(len(stop_results), 1)
        self.assertEqual(len(start_results), 1)
        self.assert_resource_invariants(fixture)

    def test_stop_stop_is_idempotent_and_cleans_each_resource_once(self) -> None:
        fixture = RaceFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        companion = fixture.companions[0]
        gate = fixture.block_companion_stop(companion)
        results: list[SharingSnapshot] = []
        first = _start_thread(fixture.controller.stop, results)
        self.assertTrue(companion.stop_entered.wait(JOIN_TIMEOUT))
        with fixture.controller._condition:
            before_second = fixture.controller._next_ticket
        second = _start_thread(fixture.controller.stop, results)
        with fixture.controller._condition:
            accepted = fixture.controller._condition.wait_for(
                lambda: fixture.controller._next_ticket > before_second,
                timeout=JOIN_TIMEOUT,
            )
        self.assertTrue(accepted, "second stop was not serialized")
        gate.release.set()
        _join(self, first, second)

        self.assertEqual(fixture.controller.state, SharingState.OFF)
        self.assertEqual(companion.stop_calls, 1)
        self.assertEqual(fixture.listener_stop_calls, 1)
        self.assertEqual(fixture.controller.status().reason, "stopped")
        self.assert_resource_invariants(fixture)

    def test_shutdown_during_start_is_terminal_and_cancels_generation(self) -> None:
        fixture = RaceFixture("listener_start")
        start_results: list[SharingSnapshot] = []
        shutdown_results: list[SharingSnapshot] = []
        starter = _start_thread(fixture.controller.start, start_results)
        gate = fixture.gates["listener_start"]
        self.assertTrue(gate.entered.wait(JOIN_TIMEOUT))
        shutdown = _start_thread(fixture.controller.shutdown, shutdown_results)
        self.assertTrue(fixture.binder.stop_cleared.wait(JOIN_TIMEOUT))
        gate.release.set()
        _join(self, starter, shutdown)

        self.assertEqual(fixture.controller.state, SharingState.OFF)
        self.assertEqual(fixture.controller.reason, "shutting_down")
        refused = fixture.controller.start()
        self.assertEqual(refused.state, SharingState.OFF)
        self.assertEqual(refused.reason, "shutting_down")
        self.assertEqual(fixture.listener_start_calls, 1)
        self.assertEqual(fixture.listener_stop_calls, 1)
        self.assertEqual(len(shutdown_results), 1)
        self.assert_resource_invariants(fixture)

    def test_shutdown_first_refuses_start_and_start_first_is_cancelled(self) -> None:
        shutdown_first = RaceFixture()
        self.assertEqual(shutdown_first.controller.start().state, SharingState.READY)
        shutdown_gate = shutdown_first.block_companion_stop(shutdown_first.companions[0])
        shutdown_results: list[SharingSnapshot] = []
        shutdown_thread = _start_thread(shutdown_first.controller.shutdown, shutdown_results)
        self.assertTrue(shutdown_first.companions[0].stop_entered.wait(JOIN_TIMEOUT))
        refused = shutdown_first.controller.start()
        self.assertEqual(refused.reason, "shutting_down")
        shutdown_gate.release.set()
        _join(self, shutdown_thread)
        self.assertEqual(shutdown_results[0].reason, "shutting_down")
        self.assertEqual(shutdown_first.controller.state, SharingState.OFF)
        self.assertEqual(shutdown_first.listener_start_calls, 1)
        self.assertEqual(shutdown_first.listener_stop_calls, 1)
        self.assert_resource_invariants(shutdown_first)

        start_first = RaceFixture("listener_start")
        start_results: list[SharingSnapshot] = []
        starter = _start_thread(start_first.controller.start, start_results)
        gate = start_first.gates["listener_start"]
        self.assertTrue(gate.entered.wait(JOIN_TIMEOUT))
        final_results: list[SharingSnapshot] = []
        shutdown_thread = _start_thread(start_first.controller.shutdown, final_results)
        self.assertTrue(start_first.binder.stop_cleared.wait(JOIN_TIMEOUT))
        gate.release.set()
        _join(self, starter, shutdown_thread)
        self.assertEqual(start_first.controller.reason, "shutting_down")
        self.assertEqual(start_first.controller.state, SharingState.OFF)
        self.assert_resource_invariants(start_first)

    def test_rotate_ready_revokes_before_reverification_and_rebinds(self) -> None:
        fixture = RaceFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        previous_generation = fixture.controller.generation
        previous_route_calls = fixture.route_calls
        callback_gate = Gate()
        callback_entered = threading.Event()
        callback_order: list[str] = []

        def revoke_and_issue() -> None:
            self.assertFalse(fixture.binder.is_bound)
            callback_order.append("revoked")
            callback_entered.set()
            callback_gate.pause()
            fixture.credential = FakeVerifier("present", object())
            fixture.rotation_finished.set()
            callback_order.append("issued")

        fixture.rotation_started.set()
        results: list[SharingSnapshot] = []
        rotator = threading.Thread(
            target=lambda: results.append(fixture.controller.rotate(revoke_and_issue))
        )
        rotator.start()
        self.assertTrue(fixture.binder.rotation_cleared.wait(JOIN_TIMEOUT))
        self.assertTrue(callback_entered.wait(JOIN_TIMEOUT))
        self.assertFalse(fixture.binder.is_bound)
        self.assertEqual(fixture.listener_start_calls, 1)
        self.assertEqual(len(fixture.companions), 1)
        callback_gate.release.set()
        _join(self, rotator)

        self.assertEqual(callback_order, ["revoked", "issued"])
        self.assertTrue(fixture.verifier_reads_during_rotation)
        self.assertTrue(all(fixture.verifier_reads_during_rotation))
        self.assertEqual(fixture.controller.state, SharingState.READY)
        self.assertEqual(fixture.controller.generation, previous_generation)
        self.assertGreater(fixture.route_calls, previous_route_calls)
        self.assertTrue(fixture.binder.is_bound)
        self.assertEqual(len(results), 1)
        self.assert_resource_invariants(fixture)

    def test_rotate_during_start_cancels_before_issuing_replacement(self) -> None:
        fixture = RaceFixture("listener_start")
        start_results: list[SharingSnapshot] = []
        rotate_results: list[SharingSnapshot] = []
        starter = _start_thread(fixture.controller.start, start_results)
        gate = fixture.gates["listener_start"]
        self.assertTrue(gate.entered.wait(JOIN_TIMEOUT))
        callback_entered = threading.Event()

        def revoke_and_issue() -> None:
            callback_entered.set()

        rotator = threading.Thread(
            target=lambda: rotate_results.append(fixture.controller.rotate(revoke_and_issue))
        )
        rotator.start()
        self.assertTrue(fixture.binder.rotation_cleared.wait(JOIN_TIMEOUT))
        self.assertFalse(callback_entered.is_set())
        gate.release.set()
        _join(self, starter, rotator)

        self.assertTrue(callback_entered.is_set())
        self.assertEqual(fixture.controller.state, SharingState.OFF)
        self.assertEqual(fixture.controller.reason, "startup_cancelled")
        self.assertEqual(fixture.listener_stop_calls, 1)
        self.assertFalse(fixture.binder.is_bound)
        self.assertEqual(len(rotate_results), 1)
        self.assert_resource_invariants(fixture)

    def test_recovery_result_is_discarded_when_stop_is_accepted_later(self) -> None:
        fixture = RaceFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        self.assertEqual(fixture.controller.mark_degraded("route_unhealthy").state, SharingState.DEGRADED)
        gate = Gate()
        fixture.gates["route"] = gate
        before_routes = fixture.route_calls
        recover_results: list[SharingSnapshot] = []
        recoverer = _start_thread(fixture.controller.recover, recover_results)
        self.assertTrue(gate.entered.wait(JOIN_TIMEOUT))
        stop_results: list[SharingSnapshot] = []
        stopper = _start_thread(fixture.controller.stop, stop_results)
        self.assertTrue(fixture.binder.stop_cleared.wait(JOIN_TIMEOUT))
        gate.release.set()
        _join(self, recoverer, stopper)

        self.assertEqual(fixture.controller.state, SharingState.OFF)
        self.assertEqual(fixture.controller.reason, "stopped")
        self.assertEqual(fixture.route_calls - before_routes, 1)
        self.assertEqual(fixture.companions[0].stop_calls, 1)
        self.assertFalse(fixture.binder.is_bound)
        self.assertEqual(len(recover_results), 1)
        self.assertNotEqual(recover_results[0].state, SharingState.READY)
        self.assert_resource_invariants(fixture)

    def test_seeded_many_thread_operation_stress_preserves_resource_invariants(self) -> None:
        fixture = RaceFixture()
        workers = 8
        operations_per_worker = 200
        start_barrier = threading.Barrier(workers)
        errors: list[BaseException] = []
        operation_names = ("start", "stop", "recover", "rotate")

        def worker(worker_id: int) -> None:
            rng = random.Random(20261111 + worker_id)
            operations = [
                rng.choice(operation_names) for _ in range(operations_per_worker)
            ]
            try:
                start_barrier.wait(JOIN_TIMEOUT)
                for operation in operations:
                    if operation == "start":
                        fixture.controller.start()
                    elif operation == "stop":
                        fixture.controller.stop()
                    elif operation == "recover":
                        fixture.controller.recover()
                    else:
                        fixture.controller.rotate(lambda: None)
            except BaseException as error:
                with fixture._lock:
                    errors.append(error)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(workers)]
        for thread in threads:
            thread.start()
        _join(self, *threads)
        self.assertEqual(errors, [])
        fixture.controller.shutdown()

        self.assertEqual(fixture.controller.state, SharingState.OFF)
        self.assertEqual(fixture.controller.reason, "shutting_down")
        self.assertEqual(fixture.listener_started_count, fixture.listener_stop_calls)
        self.assertEqual(fixture.live_companions, 0)
        self.assertLessEqual(fixture.max_live_companions, 1)
        self.assertFalse(fixture.listener_overlap)
        self.assertFalse(fixture.unexpected_companion_stop)
        self.assertFalse(fixture.binder.is_bound)
        for companion in fixture.companions:
            self.assertEqual(companion.stop_calls, companion.successful_starts)
        self.assertIsNone(fixture.controller.invitation())


if __name__ == "__main__":
    unittest.main()
