# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Explicit, bounded supervision for one active player-sharing generation."""

# TABLETOP MODE: supervise public sharing only; gameplay and input queues stay
# separate.

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from web.extensions.opentunnel_sharing.controller import (
    SharingController,
    SharingSnapshot,
    SharingState,
)

ChildState = Literal["alive", "exited", "unknown"]
ExitCodeBucket = Literal["success", "failure", "signal"]
SupervisorState = Literal[
    "idle",
    "ready",
    "degraded",
    "recovering",
    "failed",
    "stopped",
]
DelayBucket = Literal["none", "short", "medium", "long"]

_EXIT_BUCKETS = frozenset({"success", "failure", "signal"})
_SUPERVISION_REASONS = frozenset(
    {
        "off",
        "ready",
        "stopped",
        "unsupported_platform",
        "companion_missing",
        "identity_not_initialized",
        "credential_not_configured",
        "local_runtime_unavailable",
        "assets_unavailable",
        "route_unhealthy",
        "listener_failed",
        "companion_failed",
        "monitor_failed",
        "origin_unbound",
        "origin_changed",
        "stale_generation",
        "startup_cancelled",
        "readiness_regressed",
        "reconnect_budget_exhausted",
        "cleanup_failed",
        "shutting_down",
        "startup_in_progress",
    }
)


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """A finite retry schedule and bounded health observation cadence."""

    max_attempts: int = 5
    backoff_schedule: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 15.0)
    health_check_interval: float = 2.0
    max_delay: float = 60.0
    jitter_seconds: float = 0.0

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 10:
            raise ValueError("recovery_attempts_out_of_range")
        if not isinstance(self.backoff_schedule, tuple):
            raise ValueError("recovery_schedule_invalid")
        if len(self.backoff_schedule) != self.max_attempts:
            raise ValueError("recovery_schedule_length_mismatch")
        if not _finite_number(self.max_delay) or not 0 < self.max_delay <= 60:
            raise ValueError("recovery_delay_cap_out_of_range")
        if not _finite_number(self.health_check_interval) or not (
            0 < self.health_check_interval <= 60
        ):
            raise ValueError("health_check_interval_out_of_range")
        if not _finite_number(self.jitter_seconds) or self.jitter_seconds < 0:
            raise ValueError("recovery_jitter_out_of_range")

        delays: list[float] = []
        for delay in self.backoff_schedule:
            if not _finite_number(delay) or not 0 < delay <= self.max_delay:
                raise ValueError("recovery_delay_out_of_range")
            if self.jitter_seconds >= delay:
                raise ValueError("recovery_jitter_out_of_range")
            delays.append(float(delay))
        maximum_budget = sum(
            min(float(self.max_delay), delay + float(self.jitter_seconds))
            for delay in delays
        )
        if maximum_budget > 300:
            raise ValueError("recovery_budget_out_of_range")

    def delay_for(self, generation: int, attempt_index: int) -> float:
        """Return the schedule delay with optional stable generation jitter."""
        base = float(self.backoff_schedule[attempt_index])
        if self.jitter_seconds == 0:
            return base
        seed = (generation * 1103515245 + (attempt_index + 1) * 12345) & 0xFFFFFFFF
        unit = seed / 0xFFFFFFFF
        offset = (unit * 2.0 - 1.0) * float(self.jitter_seconds)
        return min(float(self.max_delay), max(0.001, base + offset))


@dataclass(frozen=True, slots=True)
class RelayHealthObservation:
    """Bounded health facts for one generation; no companion output is retained."""

    generation: int
    child_state: ChildState
    route_healthy: bool
    listener_healthy: bool
    exit_code_bucket: ExitCodeBucket | None = None


class RelayMonitor(Protocol):
    """Read a bounded companion, route, and player-listener health snapshot."""

    def observe(self, generation: int) -> RelayHealthObservation: ...


class CancellableSleeper(Protocol):
    """Wait for a delay, returning True when cancellation interrupts the wait."""

    def __call__(self, delay: float, cancel_event: threading.Event) -> bool: ...


@dataclass(frozen=True, slots=True)
class RelaySupervisionSnapshot:
    """Safe diagnostics without URLs, credentials, process output, or exceptions."""

    state: SupervisorState
    reason: str
    attempts_used: int
    attempts_max: int
    next_delay_bucket: DelayBucket
    generation: int


class RelaySupervisor:
    """Supervise relay health and delegate each recovery attempt to the controller.

    ``tick`` performs one health observation and at most one controller recovery
    attempt. The controller remains the sole owner of process creation, origin
    binding, readiness, and resource cleanup. This class never receives a player
    runtime or gameplay queue.
    """

    def __init__(
        self,
        controller: SharingController,
        monitor: RelayMonitor,
        policy: RecoveryPolicy,
        clock: Callable[[], float] = time.monotonic,
        sleeper: CancellableSleeper | None = None,
    ) -> None:
        if controller is None or not callable(getattr(controller, "status", None)):
            raise TypeError("sharing_controller_required")
        if monitor is None or not callable(getattr(monitor, "observe", None)):
            raise TypeError("relay_monitor_required")
        if not isinstance(policy, RecoveryPolicy):
            raise TypeError("recovery_policy_required")
        if not callable(clock):
            raise TypeError("supervisor_clock_required")
        if sleeper is not None and not callable(sleeper):
            raise TypeError("supervisor_sleeper_required")

        self._controller = controller
        self._monitor = monitor
        self._policy = policy
        self._clock = clock
        self._sleeper = sleeper or self._default_sleeper
        initial = controller.status()
        self._lock = threading.RLock()
        self._tick_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._generation = _safe_generation(initial)
        self._lifecycle_revision = _lifecycle_revision(controller)
        self._attempts_used = 0
        self._next_attempt_at: float | None = None
        self._next_delay: float | None = None
        self._state: SupervisorState = _initial_supervisor_state(initial)
        self._reason = _safe_reason(getattr(initial, "reason", "off"))
        self._stop_requested = False

    def snapshot(self) -> RelaySupervisionSnapshot:
        """Return bounded supervision state without probing external resources."""
        with self._lock:
            return RelaySupervisionSnapshot(
                state=self._state,
                reason=self._reason,
                attempts_used=self._attempts_used,
                attempts_max=self._policy.max_attempts,
                next_delay_bucket=_delay_bucket(self._next_delay),
                generation=self._generation,
            )

    def stop(self) -> RelaySupervisionSnapshot:
        """Cancel pending recovery without altering controller-owned resources."""
        with self._lock:
            self._stop_requested = True
            self._cancel_event.set()
            self._next_attempt_at = None
            self._next_delay = None
            self._state = "stopped"
            self._reason = "stopped"
            return self.snapshot()

    def tick(self) -> RelaySupervisionSnapshot:
        """Observe health once and perform at most one due, bounded recovery."""
        with self._tick_lock:
            current = self._controller.status()
            if self._synchronize_controller(current):
                return self.snapshot()
            if self._is_stopped_for_generation():
                return self.snapshot()

            controller_state = _state_value(getattr(current, "state", None))
            if controller_state not in {
                SharingState.READY.value,
                SharingState.DEGRADED.value,
            }:
                return self._follow_inactive_controller(current)

            _observation, observed_reason, stale = self._observe(self._generation)
            if stale:
                self._synchronize_controller(self._controller.status())
                return self.snapshot()

            current = self._controller.status()
            if self._synchronize_controller(current):
                return self.snapshot()
            controller_state = _state_value(getattr(current, "state", None))
            if controller_state not in {
                SharingState.READY.value,
                SharingState.DEGRADED.value,
            }:
                return self._follow_inactive_controller(current)

            if observed_reason is not None:
                if controller_state == SharingState.READY.value:
                    try:
                        current = self._controller.mark_degraded(
                            observed_reason,
                            expected_generation=self._generation,
                            expected_lifecycle_revision=self._lifecycle_revision,
                            expected_state=SharingState.READY,
                        )
                    except Exception:
                        current = self._controller.status()
                    if self._synchronize_controller(current):
                        return self.snapshot()
                    if (
                        _state_value(getattr(current, "state", None))
                        != SharingState.DEGRADED.value
                    ):
                        return self._follow_inactive_controller(current)
                    with self._lock:
                        self._state = "degraded"
                        self._reason = observed_reason
                        scheduled = self._schedule_first_attempt_locked()
                    if not scheduled:
                        return self._set_failed_without_retry("monitor_failed")
                    return self.snapshot()
                else:
                    with self._lock:
                        self._reason = observed_reason
            elif controller_state == SharingState.READY.value:
                with self._lock:
                    self._state = "ready"
                    self._reason = "ready"
                    self._clear_schedule_locked()
                return self.snapshot()

            current = self._controller.status()
            if (
                _state_value(getattr(current, "state", None))
                != SharingState.DEGRADED.value
            ):
                return self._follow_inactive_controller(current)

            schedule_failed = False
            with self._lock:
                if self._attempts_used >= self._policy.max_attempts:
                    should_exhaust = True
                    wait_for = 0.0
                    due_at = None
                    cancel_event = self._cancel_event
                else:
                    should_exhaust = False
                    if self._next_attempt_at is None:
                        schedule_failed = not self._schedule_first_attempt_locked()
                    due_at = self._next_attempt_at
                    wait_for = self._next_delay or 0.0
                    cancel_event = self._cancel_event
                    self._state = "recovering"
            if schedule_failed:
                return self._set_failed_without_retry("monitor_failed")
            if should_exhaust:
                return self._exhaust_budget()
            if due_at is None:
                return self.snapshot()

            wait_result = self._wait_for_attempt(due_at, wait_for, cancel_event)
            if wait_result != "due":
                self._synchronize_controller(self._controller.status())
                return self.snapshot()

            current = self._controller.status()
            if not self._attempt_context_is_current(current, cancel_event):
                self._synchronize_controller(current)
                return self.snapshot()

            with self._lock:
                if self._attempts_used >= self._policy.max_attempts:
                    return self.snapshot()
                self._attempts_used += 1
                self._next_attempt_at = None
                self._next_delay = None
                self._state = "recovering"
            recovery_failed = False
            try:
                self._controller.recover()
            except Exception:
                recovery_failed = True

            current = self._controller.status()
            if not self._attempt_context_is_current(
                current, cancel_event, allow_terminal=True
            ):
                self._synchronize_controller(current)
                return self.snapshot()

            current_checks = getattr(getattr(current, "checks", None), "ready", False)
            current_state = _state_value(getattr(current, "state", None))
            if current_state == SharingState.READY.value and current_checks is True:
                with self._lock:
                    self._state = "ready"
                    self._reason = "ready"
                    self._clear_schedule_locked()
                return self.snapshot()

            if current_state == SharingState.READY.value:
                try:
                    current = self._controller.mark_failed(
                        "readiness_regressed",
                        expected_generation=self._generation,
                        expected_lifecycle_revision=self._lifecycle_revision,
                        expected_state=SharingState.READY,
                    )
                except Exception:
                    current = self._controller.status()
                if self._synchronize_controller(current):
                    return self.snapshot()

            current_state = _state_value(getattr(current, "state", None))
            if current_state == SharingState.FAILED.value:
                with self._lock:
                    self._state = "failed"
                    self._reason = _safe_reason(
                        getattr(current, "reason", "readiness_regressed")
                    )
                    self._clear_schedule_locked()
                return self.snapshot()
            if current_state != SharingState.DEGRADED.value:
                return self._follow_inactive_controller(current)

            schedule_failed = False
            with self._lock:
                self._state = "degraded"
                self._reason = (
                    "readiness_regressed"
                    if recovery_failed
                    else _safe_reason(getattr(current, "reason", self._reason))
                )
                exhausted = self._attempts_used >= self._policy.max_attempts
                if not exhausted:
                    schedule_failed = not self._schedule_next_attempt_locked()
            if schedule_failed:
                return self._set_failed_without_retry("monitor_failed")
            if exhausted:
                return self._exhaust_budget()
            return self.snapshot()

    def _observe(
        self, generation: int
    ) -> tuple[RelayHealthObservation | None, str | None, bool]:
        try:
            observation = self._monitor.observe(generation)
        except Exception:
            return None, "monitor_failed", False
        if not isinstance(observation, RelayHealthObservation):
            return None, "monitor_failed", False
        if (
            type(observation.generation) is not int
            or observation.generation != generation
        ):
            return None, None, True
        if (
            not isinstance(observation.child_state, str)
            or observation.child_state not in {"alive", "exited", "unknown"}
        ):
            return None, "monitor_failed", False
        if (
            type(observation.route_healthy) is not bool
            or type(observation.listener_healthy) is not bool
        ):
            return None, "monitor_failed", False
        if observation.exit_code_bucket is not None and (
            not isinstance(observation.exit_code_bucket, str)
            or observation.exit_code_bucket not in _EXIT_BUCKETS
        ):
            return None, "monitor_failed", False
        if observation.child_state != "alive":
            return observation, "companion_failed", False
        if not observation.route_healthy:
            return observation, "route_unhealthy", False
        if not observation.listener_healthy:
            return observation, "listener_failed", False
        return observation, None, False

    def _schedule_first_attempt_locked(self) -> bool:
        if self._attempts_used >= self._policy.max_attempts:
            self._next_attempt_at = None
            self._next_delay = None
            return True
        delay = self._policy.delay_for(self._generation, self._attempts_used)
        try:
            now = self._clock_now()
        except ValueError:
            self._next_attempt_at = None
            self._next_delay = None
            return False
        self._next_delay = delay
        self._next_attempt_at = now + delay
        return True

    def _schedule_next_attempt_locked(self) -> bool:
        return self._schedule_first_attempt_locked()

    def _clear_schedule_locked(self) -> None:
        self._next_attempt_at = None
        self._next_delay = None

    def _wait_for_attempt(
        self,
        due_at: float,
        scheduled_delay: float,
        cancel_event: threading.Event,
    ) -> Literal["due", "cancelled", "not_due"]:
        try:
            now = self._clock_now()
        except ValueError:
            self._set_failed_without_retry("monitor_failed")
            return "cancelled"
        remaining = max(0.0, due_at - now)
        if remaining > 0:
            try:
                cancelled = self._sleeper(remaining, cancel_event)
            except Exception:
                self._set_failed_without_retry("monitor_failed")
                return "cancelled"
            if cancelled is True or cancel_event.is_set():
                return "cancelled"
        if cancel_event.is_set():
            return "cancelled"
        try:
            now = self._clock_now()
        except ValueError:
            self._set_failed_without_retry("monitor_failed")
            return "cancelled"
        if now < due_at:
            return "not_due"
        del scheduled_delay
        return "due"

    def _attempt_context_is_current(
        self,
        snapshot: object,
        cancel_event: threading.Event,
        *,
        allow_terminal: bool = False,
    ) -> bool:
        if cancel_event.is_set() or self._is_stopped_for_generation():
            return False
        state = _state_value(getattr(snapshot, "state", None))
        allowed_states = {SharingState.DEGRADED.value}
        if allow_terminal:
            allowed_states.update(
                {SharingState.READY.value, SharingState.FAILED.value}
            )
        return (
            _safe_generation(snapshot) == self._generation
            and state in allowed_states
            and _lifecycle_revision(self._controller) == self._lifecycle_revision
        )

    def _synchronize_controller(self, snapshot: object) -> bool:
        generation = _safe_generation(snapshot)
        revision = _lifecycle_revision(self._controller)
        state = _state_value(getattr(snapshot, "state", None))
        reason = _safe_reason(getattr(snapshot, "reason", "readiness_regressed"))
        with self._lock:
            if generation != self._generation:
                self._generation = generation
                self._lifecycle_revision = revision
                self._attempts_used = 0
                self._clear_schedule_locked()
                self._cancel_event.set()
                self._cancel_event = threading.Event()
                self._stop_requested = False
                self._state = _supervisor_state_for_controller(state)
                self._reason = reason
                return True
            if revision != self._lifecycle_revision:
                self._lifecycle_revision = revision
                self._clear_schedule_locked()
                self._cancel_event.set()
                self._cancel_event = threading.Event()
                self._stop_requested = False
                self._state = _supervisor_state_for_controller(state)
                self._reason = reason
                return True
            return False

    def _follow_inactive_controller(self, snapshot: object) -> RelaySupervisionSnapshot:
        state = _state_value(getattr(snapshot, "state", None))
        reason = _safe_reason(getattr(snapshot, "reason", "off"))
        with self._lock:
            self._clear_schedule_locked()
            if state == SharingState.READY.value:
                self._state = "ready"
                self._reason = "ready"
            elif state == SharingState.DEGRADED.value:
                self._state = "degraded"
                self._reason = reason
            elif state in {SharingState.OFF.value, SharingState.STOPPING.value}:
                self._cancel_event.set()
                self._state = "stopped"
                self._reason = "stopped" if state == SharingState.OFF.value else reason
            elif state == SharingState.FAILED.value:
                self._state = "failed"
                self._reason = reason
            elif state == SharingState.STARTING.value:
                self._state = "idle"
                self._reason = reason
            return self.snapshot()

    def _is_stopped_for_generation(self) -> bool:
        with self._lock:
            return self._stop_requested

    def _exhaust_budget(self) -> RelaySupervisionSnapshot:
        current = self._controller.status()
        if _state_value(getattr(current, "state", None)) == SharingState.DEGRADED.value:
            try:
                current = self._controller.mark_failed(
                    "reconnect_budget_exhausted",
                    expected_generation=self._generation,
                    expected_lifecycle_revision=self._lifecycle_revision,
                    expected_state=SharingState.DEGRADED,
                )
            except Exception:
                current = self._controller.status()
        if self._synchronize_controller(current):
            return self.snapshot()
        if _state_value(getattr(current, "state", None)) != SharingState.FAILED.value:
            return self._follow_inactive_controller(current)
        with self._lock:
            self._clear_schedule_locked()
            self._state = "failed"
            self._reason = _safe_reason(
                getattr(current, "reason", "reconnect_budget_exhausted")
            )
        return self.snapshot()

    def _set_failed_without_retry(self, reason: str) -> RelaySupervisionSnapshot:
        current = self._controller.status()
        if _state_value(getattr(current, "state", None)) == SharingState.DEGRADED.value:
            try:
                current = self._controller.mark_failed(
                    reason,
                    expected_generation=self._generation,
                    expected_lifecycle_revision=self._lifecycle_revision,
                    expected_state=SharingState.DEGRADED,
                )
            except Exception:
                current = self._controller.status()
        if self._synchronize_controller(current):
            return self.snapshot()
        if _state_value(getattr(current, "state", None)) != SharingState.FAILED.value:
            return self._follow_inactive_controller(current)
        with self._lock:
            self._clear_schedule_locked()
            self._state = "failed"
            self._reason = _safe_reason(getattr(current, "reason", reason))
        return self.snapshot()

    def _clock_now(self) -> float:
        try:
            value = float(self._clock())
        except Exception:
            raise ValueError("supervisor_clock_invalid") from None
        if not math.isfinite(value):
            raise ValueError("supervisor_clock_invalid")
        return value

    def _default_sleeper(
        self, delay: float, cancel_event: threading.Event
    ) -> bool:
        """Use interruptible waits and poll controller lifecycle invalidation."""
        due_at = self._clock_now() + delay
        while not cancel_event.is_set():
            current = self._controller.status()
            if not self._attempt_context_is_current(current, cancel_event):
                return True
            remaining = due_at - self._clock_now()
            if remaining <= 0:
                return False
            cancel_event.wait(
                min(remaining, self._policy.health_check_interval, 0.25)
            )
        return True


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _safe_generation(snapshot: object) -> int:
    value = getattr(snapshot, "generation", 0)
    return value if type(value) is int and value >= 0 else 0


def _lifecycle_revision(controller: object) -> int:
    value = getattr(controller, "lifecycle_revision", 0)
    return value if type(value) is int and value >= 0 else 0


def _state_value(value: object) -> str:
    selected = getattr(value, "value", value)
    return selected if isinstance(selected, str) else "unknown"


def _safe_reason(value: object) -> str:
    selected = getattr(value, "value", value)
    return (
        selected
        if isinstance(selected, str) and selected in _SUPERVISION_REASONS
        else "readiness_regressed"
    )


def _initial_supervisor_state(snapshot: object) -> SupervisorState:
    return _supervisor_state_for_controller(
        _state_value(getattr(snapshot, "state", None))
    )


def _supervisor_state_for_controller(state: str) -> SupervisorState:
    if state == SharingState.READY.value:
        return "ready"
    if state == SharingState.DEGRADED.value:
        return "degraded"
    if state == SharingState.FAILED.value:
        return "failed"
    if state in {SharingState.OFF.value, SharingState.STOPPING.value}:
        return "stopped"
    return "idle"


def _delay_bucket(delay: float | None) -> DelayBucket:
    if delay is None or delay <= 0:
        return "none"
    if delay <= 2:
        return "short"
    if delay <= 8:
        return "medium"
    return "long"
