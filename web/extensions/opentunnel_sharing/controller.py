# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Generation-bound facilitator-owned player-sharing lifecycle."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Literal, Protocol

from web.extensions.opentunnel_sharing.companion import CompanionResolution

MAX_DIAGNOSTIC_COUNTER = (1 << 31) - 1
MAX_COMPANION_START_DEADLINE_SECONDS = 120.0
MAX_COMPANION_STOP_DEADLINE_SECONDS = 30.0
MAX_ROUTE_WAIT_SECONDS = 120.0
MAX_ROUTE_POLL_INTERVAL_SECONDS = 5.0
MAX_ROUTE_POLL_ATTEMPTS = 512


class SharingState(str, Enum):
    """Public lifecycle states; STOPPED is an alias for the initial OFF state."""

    OFF = "off"
    STOPPED = "off"
    INITIALIZING_REQUIRED = "initializing_required"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"
    UNSUPPORTED_PLATFORM = "unsupported_platform"


ReasonCode = Literal[
    "off",
    "startup_in_progress",
    "ready",
    "stopped",
    "unsupported_platform",
    "companion_missing",
    "identity_not_initialized",
    "credential_not_configured",
    "local_runtime_unavailable",
    "assets_unavailable",
    "listener_failed",
    "companion_failed",
    "route_unhealthy",
    "origin_unbound",
    "origin_changed",
    "stale_generation",
    "startup_cancelled",
    "readiness_regressed",
    "cleanup_failed",
    "shutting_down",
]

_REASON_CODES = frozenset(
    {
        "off",
        "startup_in_progress",
        "ready",
        "stopped",
        "unsupported_platform",
        "companion_missing",
        "identity_not_initialized",
        "credential_not_configured",
        "local_runtime_unavailable",
        "assets_unavailable",
        "listener_failed",
        "companion_failed",
        "route_unhealthy",
        "origin_unbound",
        "origin_changed",
        "stale_generation",
        "startup_cancelled",
        "readiness_regressed",
        "cleanup_failed",
        "shutting_down",
    }
)
_OPERATION_FAILURE_REASONS = _REASON_CODES.difference(
    {"off", "startup_in_progress", "ready", "stopped"}
)


@dataclass(frozen=True, slots=True, repr=False)
class RouteStatus:
    """One route observation; its URL is intentionally excluded from repr."""

    healthy: bool
    origin: str | None
    generation: int

    def __repr__(self) -> str:
        return (
            "RouteStatus(healthy=%r, has_origin=%r, generation=%r)"
            % (self.healthy, bool(self.origin), self.generation)
        )


class CompanionHandle(Protocol):
    """The narrow synchronous portion of supervisor.OwnedCompanion."""

    @property
    def state(self) -> str: ...

    @property
    def reaped(self) -> bool: ...

    def start(self, deadline: float) -> str: ...

    def stop(self, deadline: float) -> bool: ...

    def diagnostics(self) -> dict[str, object]: ...


class OriginBinder(Protocol):
    """Generation-scoped exact-origin binder used by the N1 player boundary."""

    @property
    def generation(self) -> int | None: ...

    @property
    def is_bound(self) -> bool: ...

    @property
    def state(self) -> str: ...

    def begin_generation(self, generation: int) -> bool: ...

    def bind(self, status_origin: object, status_generation: object, ready: bool) -> bool: ...

    def clear(self, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ReadinessChecks:
    """Boolean readiness evidence only; no credential or route value is kept."""

    platform_supported: bool = False
    companion_available: bool = False
    identity_initialized: bool = False
    credential_configured: bool = False
    local_runtime: bool = False
    player_assets: bool = False
    listener_started: bool = False
    listener_authenticated: bool = False
    owned_route_healthy: bool = False
    route_generation_matches: bool = False
    origin_bound: bool = False

    @property
    def ready(self) -> bool:
        return all(
            (
                self.platform_supported,
                self.companion_available,
                self.identity_initialized,
                self.credential_configured,
                self.local_runtime,
                self.player_assets,
                self.listener_started,
                self.listener_authenticated,
                self.owned_route_healthy,
                self.route_generation_matches,
                self.origin_bound,
            )
        )


@dataclass(frozen=True, slots=True)
class SharingCounters:
    start_attempts: int = 0
    successful_starts: int = 0
    failed_starts: int = 0
    readiness_checks: int = 0
    degraded_transitions: int = 0
    stop_requests: int = 0
    cleanup_failures: int = 0


@dataclass(frozen=True, slots=True)
class SharingSnapshot:
    """Safe immutable state projection, with no verifier or origin fields."""

    state: SharingState
    reason: ReasonCode
    generation: int
    checks: ReadinessChecks
    counters: SharingCounters


@dataclass(frozen=True, slots=True, repr=False)
class SharingDependencies:
    """Injected provider-free seams for all external lifecycle observations."""

    local_runtime_ok: Callable[[], bool]
    assets_ok: Callable[[], bool]
    start_player_listener: Callable[[], bool]
    stop_player_listener: Callable[[], None]
    listener_authenticated_probe: Callable[[], bool]
    load_verifier: Callable[[], object]
    resolve_companion: Callable[[], CompanionResolution]
    identity_initialized: Callable[[], bool]
    start_companion: Callable[[int], CompanionHandle]
    route_status: Callable[[CompanionHandle, int], RouteStatus]
    origin_binder: OriginBinder
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    companion_start_deadline_seconds: float = 120.0
    companion_stop_deadline_seconds: float = 5.0
    route_wait_seconds: float = 30.0
    route_poll_interval_seconds: float = 0.25

    def __repr__(self) -> str:
        return "SharingDependencies(<injected>)"

    def __post_init__(self) -> None:
        for name in (
            "local_runtime_ok",
            "assets_ok",
            "start_player_listener",
            "stop_player_listener",
            "listener_authenticated_probe",
            "load_verifier",
            "resolve_companion",
            "identity_initialized",
            "start_companion",
            "route_status",
            "clock",
            "sleeper",
        ):
            if not callable(getattr(self, name)):
                raise TypeError("sharing_dependency_invalid")
        if self.origin_binder is None:
            raise TypeError("sharing_dependency_invalid")
        if not _bounded_seconds(
            self.companion_start_deadline_seconds,
            maximum=MAX_COMPANION_START_DEADLINE_SECONDS,
        ):
            raise ValueError("companion_start_deadline_invalid")
        if not _bounded_seconds(
            self.companion_stop_deadline_seconds,
            maximum=MAX_COMPANION_STOP_DEADLINE_SECONDS,
        ):
            raise ValueError("companion_stop_deadline_invalid")
        if not _bounded_seconds(self.route_wait_seconds, maximum=MAX_ROUTE_WAIT_SECONDS, allow_zero=True):
            raise ValueError("route_wait_deadline_invalid")
        if not _bounded_seconds(
            self.route_poll_interval_seconds,
            maximum=MAX_ROUTE_POLL_INTERVAL_SECONDS,
        ):
            raise ValueError("route_poll_interval_invalid")


class SharingController:
    """Own listener, companion, origin binding, and one active generation.

    Operation tickets are assigned under the short state lock. Ticket order is
    the linearization order for accepted operations. The queue lock is released
    while dependency callbacks run; Stop and shutdown can therefore signal the
    active generation's cancellation event without waiting for a fake or
    adapter callback to return. A start accepted while stopping queues behind
    that stop. Starts arriving while starting, ready, or already queued are
    idempotent and return the current bounded snapshot.
    """

    def __init__(self, deps: SharingDependencies) -> None:
        if not isinstance(deps, SharingDependencies):
            raise TypeError("sharing_dependencies_required")
        self._deps = deps
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._next_ticket = 0
        self._serving_ticket = 0
        self._pending_start_ticket: int | None = None
        self._pending_start_event: threading.Event | None = None
        self._active_start_ticket: int | None = None
        self._active_start_event: threading.Event | None = None
        self._shutdown_requested = False
        self._generation = 0
        self._state = SharingState.OFF
        self._reason: ReasonCode = "off"
        self._checks = ReadinessChecks()
        self._counters = SharingCounters()
        self._listener_started = False
        self._listener_generation: int | None = None
        self._companion: CompanionHandle | None = None
        self._companion_started = False
        self._companion_generation: int | None = None

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def state(self) -> SharingState:
        with self._lock:
            return self._state

    @property
    def reason(self) -> ReasonCode:
        with self._lock:
            return self._reason

    def status(self) -> SharingSnapshot:
        """Return bounded lifecycle state without probing or revealing secrets."""
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> SharingSnapshot:
        return SharingSnapshot(
            state=self._state,
            reason=self._reason,
            generation=self._generation,
            checks=self._checks,
            counters=self._counters,
        )

    def _reserve_ticket_locked(self) -> int:
        ticket = self._next_ticket
        self._next_ticket += 1
        self._condition.notify_all()
        return ticket

    def _wait_for_ticket(self, ticket: int) -> None:
        with self._condition:
            while ticket != self._serving_ticket:
                self._condition.wait()

    def _finish_ticket(self, ticket: int) -> None:
        with self._condition:
            if ticket != self._serving_ticket:
                raise RuntimeError("sharing_operation_order_invalid")
            self._serving_ticket += 1
            self._condition.notify_all()

    def _increment_counter(self, field: str) -> None:
        with self._lock:
            self._counters = _increment(self._counters, field)

    def _replace_checks(self, **changes: bool) -> None:
        with self._lock:
            self._checks = replace(self._checks, **changes)

    def _begin_start_locked(self, ticket: int, token: threading.Event) -> int:
        self._generation += 1
        generation = self._generation
        self._counters = _increment(self._counters, "start_attempts")
        self._checks = ReadinessChecks()
        self._set_state(SharingState.STARTING, "startup_in_progress")
        self._active_start_ticket = ticket
        self._active_start_event = token
        return generation

    def start(self) -> SharingSnapshot:
        """Start once, or return the current state for a duplicate request."""
        token = threading.Event()
        generation: int | None = None
        with self._condition:
            if self._shutdown_requested:
                if self._state is SharingState.OFF:
                    self._set_state(SharingState.OFF, "shutting_down")
                return self._snapshot_locked()
            if (
                self._state in {SharingState.STARTING, SharingState.READY}
                or self._pending_start_event is not None
            ):
                return self._snapshot_locked()
            ticket = self._reserve_ticket_locked()
            self._pending_start_ticket = ticket
            self._pending_start_event = token
            if ticket == self._serving_ticket:
                self._pending_start_ticket = None
                self._pending_start_event = None
                generation = self._begin_start_locked(ticket, token)

        try:
            self._wait_for_ticket(ticket)
            with self._lock:
                if self._pending_start_ticket == ticket:
                    self._pending_start_ticket = None
                    self._pending_start_event = None
                if token.is_set() or self._shutdown_requested:
                    return self._snapshot_locked()
                if self._active_start_ticket == ticket and self._active_start_event is token:
                    generation = self._generation
                elif self._state in {SharingState.STARTING, SharingState.READY}:
                    return self._snapshot_locked()
                else:
                    generation = self._begin_start_locked(ticket, token)
            if generation is None:
                return self.status()
            return self._start_generation(generation, token)
        finally:
            with self._lock:
                if self._active_start_ticket == ticket:
                    self._active_start_ticket = None
                    self._active_start_event = None
            self._finish_ticket(ticket)

    def _start_generation(
        self, generation: int, cancel_event: threading.Event
    ) -> SharingSnapshot:
        """Run one startup without holding the state/queue lock over callbacks."""
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)

        cleanup_ok = self._cleanup_resources("failed")
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        if not cleanup_ok:
            return self._fail_start(generation, "cleanup_failed", cancel_event)

        # Prerequisites are deliberately checked in this fixed order:
        # platform/companion, identity, credential, local runtime, assets.
        resolution = self._probe_companion()
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        if resolution is None:
            return self._fail_start(generation, "companion_missing", cancel_event)
        if resolution.state == "unsupported_platform":
            return self._precondition_failure(
                generation,
                SharingState.UNSUPPORTED_PLATFORM,
                "unsupported_platform",
                cancel_event,
                platform_supported=False,
            )
        if resolution.state != "resolved" or resolution.path is None:
            return self._precondition_failure(
                generation,
                SharingState.FAILED,
                "companion_missing",
                cancel_event,
                platform_supported=True,
                companion_available=False,
            )
        self._replace_checks(platform_supported=True, companion_available=True)

        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        identity_ok = self._call_bool(self._deps.identity_initialized)
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        self._replace_checks(identity_initialized=identity_ok)
        if not identity_ok:
            return self._precondition_failure(
                generation,
                SharingState.INITIALIZING_REQUIRED,
                "identity_not_initialized",
                cancel_event,
            )

        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        credential_ok = self._credential_configured()
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        self._replace_checks(credential_configured=credential_ok)
        if not credential_ok:
            return self._precondition_failure(
                generation,
                SharingState.FAILED,
                "credential_not_configured",
                cancel_event,
            )

        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        runtime_ok = self._call_bool(self._deps.local_runtime_ok)
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        self._replace_checks(local_runtime=runtime_ok)
        if not runtime_ok:
            return self._precondition_failure(
                generation,
                SharingState.FAILED,
                "local_runtime_unavailable",
                cancel_event,
            )

        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        assets_ok = self._call_bool(self._deps.assets_ok)
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        self._replace_checks(player_assets=assets_ok)
        if not assets_ok:
            return self._precondition_failure(
                generation,
                SharingState.FAILED,
                "assets_unavailable",
                cancel_event,
            )

        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        if not self._begin_binding_generation(generation):
            return self._fail_start(generation, "origin_unbound", cancel_event)
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)

        try:
            listener_started = self._deps.start_player_listener() is True
        except Exception:
            listener_started = False
        with self._lock:
            self._listener_started = listener_started
            self._listener_generation = generation if listener_started else None
            self._checks = replace(self._checks, listener_started=listener_started)
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        if not listener_started:
            return self._fail_start(generation, "listener_failed", cancel_event)

        listener_authenticated = self._call_bool(
            self._deps.listener_authenticated_probe
        )
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        self._replace_checks(listener_authenticated=listener_authenticated)
        if not listener_authenticated:
            return self._fail_start(generation, "listener_failed", cancel_event)

        try:
            companion = self._deps.start_companion(generation)
        except Exception:
            companion = None
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        if companion is None:
            return self._fail_start(generation, "companion_failed", cancel_event)
        with self._lock:
            self._companion = companion
            self._companion_generation = generation

        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        try:
            companion_state = companion.start(
                self._deps.companion_start_deadline_seconds
            )
        except Exception:
            companion_state = "failed"
        companion_started = (
            companion_state == "running"
            and self._companion_state(companion) == "running"
        )
        with self._lock:
            self._companion_started = companion_started
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        if not companion_started:
            return self._fail_start(generation, "companion_failed", cancel_event)

        route_ok, route_reason = self._wait_for_route(
            generation, companion, cancel_event
        )
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        if not route_ok:
            return self._fail_start(generation, route_reason, cancel_event)

        self._increment_counter("readiness_checks")
        checks, reason, _origin = self._evaluate_full_readiness(
            generation, SharingState.STARTING, cancel_event
        )
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        with self._lock:
            self._checks = checks
        if not checks.ready:
            return self._fail_start(generation, reason, cancel_event)

        with self._lock:
            if not self._start_is_current_locked(generation, cancel_event):
                should_cancel = True
            else:
                should_cancel = False
                self._set_state(SharingState.READY, "ready")
                self._counters = _increment(self._counters, "successful_starts")
        if should_cancel:
            return self._cancelled_start(generation)
        return self.status()

    def stop(self) -> SharingSnapshot:
        """Cancel startup promptly, then clean up in ticket order."""
        with self._condition:
            self._counters = _increment(self._counters, "stop_requests")
            has_resources = self._listener_started or self._companion is not None
            has_start = (
                self._active_start_event is not None
                or self._pending_start_event is not None
            )
            if (
                self._state is SharingState.OFF
                and not has_resources
                and not has_start
                and not self._shutdown_requested
            ):
                self._set_state(SharingState.OFF, "stopped")
                return self._snapshot_locked()

            ticket = self._reserve_ticket_locked()
            cancelled_start = self._state is SharingState.STARTING or (
                self._pending_start_event is not None
            )
            if self._active_start_event is not None:
                self._active_start_event.set()
            if self._pending_start_event is not None:
                self._pending_start_event.set()
            if not self._shutdown_requested:
                self._checks = replace(self._checks, origin_bound=False)
                self._set_state(SharingState.STOPPING, "startup_in_progress")
        self._clear_binding("stop")

        try:
            self._wait_for_ticket(ticket)
            cleanup_ok = self._cleanup_resources("stop")
            with self._lock:
                if not cleanup_ok:
                    self._counters = _increment(self._counters, "cleanup_failures")
                self._checks = ReadinessChecks()
                if not self._shutdown_requested:
                    self._set_state(
                        SharingState.OFF,
                        "startup_cancelled"
                        if cancelled_start and cleanup_ok
                        else "stopped"
                        if cleanup_ok
                        else "cleanup_failed",
                    )
                return self._snapshot_locked()
        finally:
            self._finish_ticket(ticket)

    def shutdown(self) -> SharingSnapshot:
        """Stop sharing and permanently refuse later starts for this controller."""
        with self._condition:
            if self._shutdown_requested:
                return self._snapshot_locked()
            self._shutdown_requested = True
            ticket = self._reserve_ticket_locked()
            if self._active_start_event is not None:
                self._active_start_event.set()
            if self._pending_start_event is not None:
                self._pending_start_event.set()
            has_resources = self._listener_started or self._companion is not None
            if self._state is not SharingState.OFF or has_resources:
                self._checks = replace(self._checks, origin_bound=False)
                self._set_state(SharingState.STOPPING, "shutting_down")
            else:
                self._set_state(SharingState.OFF, "shutting_down")
        self._clear_binding("stop")

        try:
            self._wait_for_ticket(ticket)
            cleanup_ok = self._cleanup_resources("stop")
            with self._lock:
                if not cleanup_ok:
                    self._counters = _increment(self._counters, "cleanup_failures")
                self._checks = ReadinessChecks()
                self._set_state(
                    SharingState.OFF,
                    "shutting_down" if cleanup_ok else "cleanup_failed",
                )
                return self._snapshot_locked()
        finally:
            self._finish_ticket(ticket)

    def rotate(
        self, revoke_and_issue: Callable[[], object]
    ) -> SharingSnapshot:
        """Rotate verifier access before rechecking a previously active stack.

        ``revoke_and_issue`` is the verifier-store transaction. It must return
        only after its revocation callback has succeeded and the replacement
        verifier is accepted; ``verifier_store.rotate_credential`` provides that
        ordering. Its one-time plaintext result is deliberately not returned by
        this controller. If startup is active, rotation cancels that generation,
        waits for its cleanup, and then performs the transaction without
        restarting sharing. A ready or degraded stack is rebound only after one
        complete readiness pass for the same generation.
        """
        if not callable(revoke_and_issue):
            return self.status()

        with self._condition:
            if self._shutdown_requested:
                return self._snapshot_locked()
            ticket = self._reserve_ticket_locked()
            was_starting = self._state is SharingState.STARTING or (
                self._pending_start_event is not None
            )
            should_reverify = self._state in {
                SharingState.READY,
                SharingState.DEGRADED,
            }
            generation = self._generation
            if self._active_start_event is not None:
                self._active_start_event.set()
            if self._pending_start_event is not None:
                self._pending_start_event.set()
            if was_starting:
                self._checks = replace(self._checks, origin_bound=False)
                self._set_state(SharingState.STOPPING, "startup_in_progress")
            elif should_reverify:
                self._checks = replace(self._checks, origin_bound=False)
                self._set_state(SharingState.DEGRADED, "readiness_regressed")
        self._clear_binding("rotation")

        try:
            self._wait_for_ticket(ticket)
            cleanup_ok = True
            if was_starting:
                cleanup_ok = self._cleanup_resources("rotation")
                if not cleanup_ok:
                    self._increment_counter("cleanup_failures")
            try:
                revoke_and_issue()
            except Exception:
                self._clear_binding("rotation")
                with self._lock:
                    if not self._shutdown_requested and self._state is not SharingState.STOPPING:
                        self._checks = replace(self._checks, origin_bound=False)
                        self._set_state(SharingState.FAILED, "readiness_regressed")
                return self.status()

            if was_starting:
                with self._lock:
                    if not self._shutdown_requested and self._state is SharingState.STOPPING:
                        self._checks = ReadinessChecks()
                        self._set_state(
                            SharingState.OFF,
                            "startup_cancelled" if cleanup_ok else "cleanup_failed",
                        )
                return self.status()

            with self._lock:
                can_reverify = (
                    should_reverify
                    and generation == self._generation
                    and self._state is SharingState.DEGRADED
                    and not self._shutdown_requested
                )
            if not can_reverify:
                return self.status()

            self._increment_counter("readiness_checks")
            checks, reason, _origin = self._evaluate_full_readiness(
                generation, SharingState.DEGRADED
            )
            with self._lock:
                if (
                    generation != self._generation
                    or self._state is not SharingState.DEGRADED
                    or self._shutdown_requested
                ):
                    stale = True
                else:
                    stale = False
                    self._checks = checks
                    if checks.ready:
                        self._set_state(SharingState.READY, "ready")
                    else:
                        self._checks = replace(checks, origin_bound=False)
                        self._set_state(SharingState.DEGRADED, reason)
            if stale or not checks.ready:
                self._clear_binding("rotation", generation)
            return self.status()
        finally:
            self._finish_ticket(ticket)

    def mark_degraded(self, reason: object = "readiness_regressed") -> SharingSnapshot:
        """Withdraw the binding while retaining resources for bounded recovery."""
        with self._lock:
            if self._shutdown_requested:
                return self._snapshot_locked()
            ticket = self._reserve_ticket_locked()
        try:
            self._wait_for_ticket(ticket)
            with self._lock:
                if self._state in {SharingState.STOPPING, SharingState.OFF}:
                    return self._snapshot_locked()
                selected_reason = _operation_failure_reason(reason)
                self._checks = replace(self._checks, origin_bound=False)
                self._set_state(SharingState.DEGRADED, selected_reason)
                self._counters = _increment(self._counters, "degraded_transitions")
            self._clear_binding("degraded")
            return self.status()
        finally:
            self._finish_ticket(ticket)

    def mark_failed(self, reason: object = "readiness_regressed") -> SharingSnapshot:
        """Withdraw the binding and expose only a bounded failure reason."""
        with self._lock:
            if self._shutdown_requested:
                return self._snapshot_locked()
            ticket = self._reserve_ticket_locked()
        try:
            self._wait_for_ticket(ticket)
            with self._lock:
                if self._state is SharingState.STOPPING:
                    return self._snapshot_locked()
                selected_reason = _operation_failure_reason(reason)
                self._checks = replace(self._checks, origin_bound=False)
                self._set_state(SharingState.FAILED, selected_reason)
            self._clear_binding("failed")
            return self.status()
        finally:
            self._finish_ticket(ticket)

    def recheck_readiness(self) -> bool:
        """Compatibility-facing boolean for one serialized recovery attempt."""
        snapshot = self.recover()
        return snapshot.state is SharingState.READY and snapshot.reason == "ready"

    def recover(self) -> SharingSnapshot:
        """Perform at most one complete readiness pass in serializer order."""
        with self._condition:
            if self._shutdown_requested:
                return self._snapshot_locked()
            ticket = self._reserve_ticket_locked()
        try:
            self._wait_for_ticket(ticket)
            with self._lock:
                generation = self._generation
                previous_state = self._state
                if generation < 1 or previous_state not in {
                    SharingState.READY,
                    SharingState.DEGRADED,
                }:
                    return self._snapshot_locked()
                self._counters = _increment(self._counters, "readiness_checks")

            checks, reason, _origin = self._evaluate_full_readiness(
                generation, previous_state
            )
            with self._lock:
                if not self._is_current_locked(generation, previous_state):
                    stale = True
                else:
                    stale = False
                    self._checks = checks
                    if checks.ready:
                        self._set_state(SharingState.READY, "ready")
                    else:
                        self._checks = replace(checks, origin_bound=False)
                        self._set_state(SharingState.DEGRADED, reason)
                        self._counters = _increment(
                            self._counters, "degraded_transitions"
                        )
            if stale:
                self._clear_binding("stop", generation)
            elif not checks.ready:
                self._clear_binding("degraded", generation)
            return self.status()
        finally:
            self._finish_ticket(ticket)

    def invitation(self) -> str | None:
        """Compute the URL-only invitation transiently from a fresh bound status."""
        with self._condition:
            if self._state is not SharingState.READY or self._shutdown_requested:
                return None
            ticket = self._reserve_ticket_locked()
        try:
            self._wait_for_ticket(ticket)
            with self._lock:
                if self._state is not SharingState.READY:
                    return None
                generation = self._generation
            checks, reason, origin = self._evaluate_full_readiness(
                generation, SharingState.READY
            )
            with self._lock:
                if not self._is_current_locked(generation, SharingState.READY):
                    stale = True
                else:
                    stale = False
                    self._checks = checks
                    if checks.ready and origin is not None:
                        return origin
                    self._checks = replace(checks, origin_bound=False)
                    self._set_state(SharingState.DEGRADED, reason)
                    self._counters = _increment(self._counters, "degraded_transitions")
            if stale:
                self._clear_binding("stop", generation)
            else:
                self._clear_binding("degraded", generation)
            return None
        finally:
            self._finish_ticket(ticket)

    def _probe_companion(self) -> CompanionResolution | None:
        try:
            result = self._deps.resolve_companion()
        except Exception:
            return None
        return result if isinstance(result, CompanionResolution) else None

    def _credential_configured(self) -> bool:
        try:
            loaded = self._deps.load_verifier()
        except Exception:
            return False
        return bool(
            getattr(loaded, "state", None) == "present"
            and getattr(loaded, "verifier", None) is not None
        )

    def _begin_binding_generation(self, generation: int) -> bool:
        try:
            return bool(
                self._deps.origin_binder.begin_generation(generation)
                and self._deps.origin_binder.generation == generation
            )
        except Exception:
            return False

    def _wait_for_route(
        self,
        generation: int,
        companion: CompanionHandle,
        cancel_event: threading.Event,
    ) -> tuple[bool, ReasonCode]:
        try:
            now = float(self._deps.clock())
            if not math.isfinite(now):
                return False, "route_unhealthy"
            expires_at = now + self._deps.route_wait_seconds
        except Exception:
            return False, "route_unhealthy"
        interval = self._deps.route_poll_interval_seconds
        max_attempts = min(
            MAX_ROUTE_POLL_ATTEMPTS,
            max(1, int(math.ceil(self._deps.route_wait_seconds / interval)) + 1),
        )
        last_reason: ReasonCode = "route_unhealthy"
        for attempt in range(max_attempts):
            if not self._start_is_current(generation, cancel_event):
                return False, "startup_cancelled"
            try:
                result = self._deps.route_status(companion, generation)
            except Exception:
                result = None
            if not self._start_is_current(generation, cancel_event):
                return False, "startup_cancelled"
            if not isinstance(result, RouteStatus):
                last_reason = "route_unhealthy"
            elif type(result.generation) is not int or result.generation != generation:
                last_reason = "stale_generation"
            elif result.healthy is not True:
                last_reason = "route_unhealthy"
            else:
                self._replace_checks(
                    owned_route_healthy=True,
                    route_generation_matches=True,
                )
                if not isinstance(result.origin, str) or not result.origin:
                    last_reason = "origin_unbound"
                else:
                    try:
                        bound = self._deps.origin_binder.bind(
                            result.origin, result.generation, ready=True
                        )
                        binder_generation = self._deps.origin_binder.generation
                        binder_bound = self._deps.origin_binder.is_bound
                        binder_state = self._deps.origin_binder.state
                    except Exception:
                        bound = False
                        binder_generation = None
                        binder_bound = False
                        binder_state = "unbound"
                    if not self._start_is_current(generation, cancel_event):
                        self._clear_binding("stop", generation)
                        return False, "startup_cancelled"
                    if (
                        bound is True
                        and binder_generation == generation
                        and binder_bound is True
                    ):
                        self._replace_checks(origin_bound=True)
                        return True, "ready"
                    last_reason = (
                        "origin_changed"
                        if binder_state == "origin_changed"
                        else "origin_unbound"
                    )

            try:
                now = float(self._deps.clock())
            except Exception:
                return False, last_reason
            if not math.isfinite(now):
                return False, last_reason
            remaining = expires_at - now
            if remaining <= 0 or attempt + 1 >= max_attempts:
                break
            if cancel_event.wait(min(interval, remaining)):
                return False, "startup_cancelled"
        return False, last_reason

    def _evaluate_full_readiness(
        self,
        generation: int,
        expected_state: SharingState,
        cancel_event: threading.Event | None = None,
    ) -> tuple[ReadinessChecks, ReasonCode, str | None]:
        def current() -> bool:
            if cancel_event is not None and cancel_event.is_set():
                return False
            return self._is_current(generation, expected_state)

        def stale_reason() -> ReasonCode:
            return (
                "startup_cancelled"
                if cancel_event is not None and cancel_event.is_set()
                else "stale_generation"
            )

        checks = ReadinessChecks()
        resolution = self._probe_companion()
        if not current():
            return checks, stale_reason(), None
        if resolution is None:
            return checks, "companion_missing", None
        if resolution.state == "unsupported_platform":
            return checks, "unsupported_platform", None
        if resolution.state != "resolved" or resolution.path is None:
            return replace(checks, platform_supported=True), "companion_missing", None
        checks = replace(
            checks,
            platform_supported=True,
            companion_available=True,
        )
        if not current():
            return checks, stale_reason(), None

        identity_ok = self._call_bool(self._deps.identity_initialized)
        if not current():
            return checks, stale_reason(), None
        checks = replace(checks, identity_initialized=identity_ok)
        if not identity_ok:
            return checks, "identity_not_initialized", None
        credential_ok = self._credential_configured()
        if not current():
            return checks, stale_reason(), None
        checks = replace(checks, credential_configured=credential_ok)
        if not credential_ok:
            return checks, "credential_not_configured", None
        runtime_ok = self._call_bool(self._deps.local_runtime_ok)
        if not current():
            return checks, stale_reason(), None
        checks = replace(checks, local_runtime=runtime_ok)
        if not runtime_ok:
            return checks, "local_runtime_unavailable", None
        assets_ok = self._call_bool(self._deps.assets_ok)
        if not current():
            return checks, stale_reason(), None
        checks = replace(checks, player_assets=assets_ok)
        if not assets_ok:
            return checks, "assets_unavailable", None
        if not current():
            return checks, stale_reason(), None

        with self._lock:
            listener_started = self._listener_started
            companion = self._companion
            companion_started = self._companion_started
        checks = replace(checks, listener_started=listener_started)
        if not listener_started:
            return checks, "listener_failed", None
        listener_authenticated = self._call_bool(
            self._deps.listener_authenticated_probe
        )
        if not current():
            return checks, stale_reason(), None
        checks = replace(checks, listener_authenticated=listener_authenticated)
        if not listener_authenticated:
            return checks, "listener_failed", None
        if not companion_started or companion is None:
            return checks, "companion_failed", None
        if self._companion_state(companion) != "running":
            return checks, "companion_failed", None
        try:
            result = self._deps.route_status(companion, generation)
        except Exception:
            result = None
        if not current():
            return checks, stale_reason(), None
        if not isinstance(result, RouteStatus):
            return checks, "route_unhealthy", None
        if type(result.generation) is not int or result.generation != generation:
            return checks, "stale_generation", None
        if result.healthy is not True:
            return checks, "route_unhealthy", None
        checks = replace(
            checks,
            owned_route_healthy=True,
            route_generation_matches=True,
        )
        if not isinstance(result.origin, str) or not result.origin:
            return checks, "origin_unbound", None
        if not current():
            return checks, stale_reason(), None
        try:
            bound = self._deps.origin_binder.bind(
                result.origin, result.generation, ready=True
            )
            binder_generation = self._deps.origin_binder.generation
            binder_bound = self._deps.origin_binder.is_bound
            binder_state = self._deps.origin_binder.state
        except Exception:
            bound = False
            binder_generation = None
            binder_bound = False
            binder_state = "unbound"
        if not current():
            self._clear_binding(
                "stop" if cancel_event is not None and cancel_event.is_set() else "degraded",
                generation,
            )
            return checks, stale_reason(), None
        if not (
            bound is True
            and binder_generation == generation
            and binder_bound is True
        ):
            reason: ReasonCode = (
                "origin_changed" if binder_state == "origin_changed" else "origin_unbound"
            )
            return checks, reason, None
        checks = replace(checks, origin_bound=True)
        return checks, "ready", result.origin

    def _fail_start(
        self,
        generation: int,
        reason: ReasonCode,
        cancel_event: threading.Event,
    ) -> SharingSnapshot:
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        cleanup_ok = self._cleanup_resources("failed", generation)
        with self._lock:
            if not self._start_is_current_locked(generation, cancel_event):
                cancelled = True
            else:
                cancelled = False
                if not cleanup_ok:
                    self._counters = _increment(self._counters, "cleanup_failures")
                    reason = "cleanup_failed"
                self._checks = replace(self._checks, origin_bound=False)
                self._counters = _increment(self._counters, "failed_starts")
                self._set_state(SharingState.FAILED, reason)
        if cancelled:
            return self._cancelled_start(generation)
        return self.status()

    def _precondition_failure(
        self,
        generation: int,
        state: SharingState,
        reason: ReasonCode,
        cancel_event: threading.Event,
        **check_changes: bool,
    ) -> SharingSnapshot:
        if check_changes:
            self._replace_checks(**check_changes)
        if not self._start_is_current(generation, cancel_event):
            return self._cancelled_start(generation)
        self._clear_binding("failed", generation)
        with self._lock:
            if not self._start_is_current_locked(generation, cancel_event):
                cancelled = True
            else:
                cancelled = False
                self._counters = _increment(self._counters, "failed_starts")
                self._set_state(state, reason)
        if cancelled:
            return self._cancelled_start(generation)
        return self.status()

    def _cancelled_start(self, generation: int) -> SharingSnapshot:
        cleanup_ok = self._cleanup_resources("stop", generation)
        if not cleanup_ok:
            self._increment_counter("cleanup_failures")
        return self.status()

    def _cleanup_resources(
        self, binding_reason: str, generation: int | None = None
    ) -> bool:
        cleanup_ok = self._clear_binding(binding_reason, generation)
        with self._lock:
            owns_companion = (
                generation is None or self._companion_generation == generation
            )
            companion = self._companion if owns_companion else None
            companion_started = self._companion_started if owns_companion else False
        companion_stopped = not companion_started
        if companion_started and companion is not None:
            try:
                stopped = companion.stop(
                    self._deps.companion_stop_deadline_seconds
                ) is True
                reaped = getattr(companion, "reaped", True) is True
                companion_stopped = stopped and reaped
                cleanup_ok = companion_stopped and cleanup_ok
            except Exception:
                cleanup_ok = False
        if owns_companion and companion_stopped:
            with self._lock:
                if self._companion is companion:
                    self._companion = None
                    self._companion_started = False
                    self._companion_generation = None

        with self._lock:
            owns_listener = (
                generation is None or self._listener_generation == generation
            )
            listener_started = self._listener_started if owns_listener else False
        listener_stopped = not listener_started
        if listener_started:
            try:
                self._deps.stop_player_listener()
                listener_stopped = True
            except Exception:
                cleanup_ok = False
        if owns_listener and listener_stopped:
            with self._lock:
                self._listener_started = False
                self._listener_generation = None
        return cleanup_ok

    def _clear_binding(self, reason: str, generation: int | None = None) -> bool:
        try:
            if generation is not None:
                binder_generation = self._deps.origin_binder.generation
                if binder_generation not in {None, generation}:
                    return True
            self._deps.origin_binder.clear(reason)
            return True
        except Exception:
            return False

    def _is_current(self, generation: int, state: SharingState) -> bool:
        with self._lock:
            return self._is_current_locked(generation, state)

    def _is_current_locked(self, generation: int, state: SharingState) -> bool:
        return self._generation == generation and self._state is state

    def _start_is_current(self, generation: int, event: threading.Event) -> bool:
        with self._lock:
            return self._start_is_current_locked(generation, event)

    def _start_is_current_locked(
        self, generation: int, event: threading.Event
    ) -> bool:
        return (
            not event.is_set()
            and not self._shutdown_requested
            and self._is_current_locked(generation, SharingState.STARTING)
        )

    def _set_state(self, state: SharingState, reason: ReasonCode) -> None:
        with self._lock:
            self._state = state
            self._reason = reason if reason in _REASON_CODES else "readiness_regressed"

    @staticmethod
    def _call_bool(callback: Callable[[], bool]) -> bool:
        try:
            return callback() is True
        except Exception:
            return False

    @staticmethod
    def _companion_state(companion: CompanionHandle) -> str | None:
        try:
            value = companion.state
        except Exception:
            return None
        return value if isinstance(value, str) else None


def _operation_failure_reason(value: object) -> ReasonCode:
    if isinstance(value, str) and value in _OPERATION_FAILURE_REASONS:
        return value  # type: ignore[return-value]
    return "readiness_regressed"


def _increment(counters: SharingCounters, field: str) -> SharingCounters:
    value = getattr(counters, field, 0)
    if type(value) is not int:
        value = 0
    return replace(counters, **{field: min(MAX_DIAGNOSTIC_COUNTER, value + 1)})


def _bounded_seconds(value: object, *, maximum: float, allow_zero: bool = False) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    number = float(value)
    lower_ok = number >= 0 if allow_zero else number > 0
    return bool(math.isfinite(number) and lower_ok and number <= maximum)
