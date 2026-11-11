# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the generation-bound sharing controller.

The lifecycle is independent of party shape, so these tests intentionally do not
construct one-PC or four-PC campaigns.
"""

from __future__ import annotations

import ast
import unittest
from collections import deque
from dataclasses import dataclass, replace
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
from web.extensions.player.auth import PlayerSecurity, make_verifier

PLAYER_ORIGIN = "https://sharing-route.example"
SENTINEL_URL = "https://sentinel-invitation.example"
SENTINEL_CREDENTIAL = "SENTINEL_CREDENTIAL_VALUE"


@dataclass(frozen=True, slots=True, repr=False)
class FakeVerifierLoad:
    state: str
    verifier: object | None
    raw_verifier: str | None = None

    def __repr__(self) -> str:
        return "FakeVerifierLoad(state=%r)" % self.state


class FakeSecurity:
    """PlayerSecurity-shaped binding authority without a listener or network."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self._origin: str | None = None
        self._generation: int | None = None
        self._active_generation: int | None = None
        self._highest_generation = 0

    @property
    def public_origin_status(self) -> tuple[bool, int | None]:
        return self._origin is not None, self._generation

    def bind_public_origin(self, generation: int, origin: object) -> bool:
        if not isinstance(origin, str) or self._active_generation != generation:
            return False
        if self._origin is not None:
            return self._origin == origin and self._generation == generation
        self._origin = origin
        self._generation = generation
        self.events.append("binding_set")
        return True

    def set_active_origin_generation(self, generation: int | None) -> bool:
        if generation is None:
            self._active_generation = None
            self._origin = None
            self._generation = None
            return True
        if (
            type(generation) is not int
            or generation < self._highest_generation
        ):
            return False
        if generation == self._active_generation:
            return True
        self._active_generation = generation
        self._highest_generation = max(self._highest_generation, generation)
        self._origin = None
        self._generation = None
        return True

    def clear_public_origin(self, _reason: str | None = None) -> None:
        self._origin = None
        self._generation = None
        self._active_generation = None
        self.events.append("binding_clear")


class FakeCompanion:
    """An owned-handle fake that reports whether it actually started."""

    def __init__(
        self,
        events: list[str],
        *,
        start_result: str = "running",
    ) -> None:
        self.events = events
        self.start_result = start_result
        self._state = "stopped"
        self._reaped = True
        self.start_calls = 0
        self.stop_calls = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def reaped(self) -> bool:
        return self._reaped

    def start(self, _deadline: float) -> str:
        self.start_calls += 1
        self.events.append("companion_start")
        if self.start_result == "running":
            self._state = "running"
            self._reaped = False
        else:
            self._state = "failed"
            self._reaped = True
        return self.start_result

    def stop(self, _deadline: float) -> bool:
        self.stop_calls += 1
        if self._state != "running":
            self.events.append("unexpected_companion_stop")
            return False
        self.events.append("companion_stop")
        self._state = "stopped"
        self._reaped = True
        return True

    def diagnostics(self) -> dict[str, object]:
        return {"state": self._state}


class LifecycleFixture:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.security = FakeSecurity(self.events)
        self.binder = PublicOriginBinder(self.security)  # type: ignore[arg-type]
        self.resolution = CompanionResolution(
            state="resolved",
            reason="resolved",
            path=Path("fixture-opentunnel"),
        )
        self.identity_ok = True
        self.credential = FakeVerifierLoad(
            "present", object(), SENTINEL_CREDENTIAL
        )
        self.runtime_ok = True
        self.assets_ok = True
        self.listener_start_ok = True
        self.listener_probe_ok = True
        self.listener_stop_fails = False
        self.companion_factory_fails = False
        self.companion_start_result = "running"
        self.companion: FakeCompanion | None = None
        self.listener_running = False
        self.route_results: deque[RouteStatus] = deque()
        self.route_calls = 0
        self.route_callback: Callable[[FakeCompanion, int], RouteStatus] | None = None
        self.clock_value = 10.0

        self.deps = SharingDependencies(
            local_runtime_ok=lambda: self.runtime_ok,
            assets_ok=lambda: self.assets_ok,
            start_player_listener=self.start_listener,
            stop_player_listener=self.stop_listener,
            listener_authenticated_probe=lambda: self.listener_probe_ok,
            load_verifier=lambda: self.credential,
            resolve_companion=lambda: self.resolution,
            identity_initialized=lambda: self.identity_ok,
            start_companion=self.start_companion,
            route_status=self.route_status,
            origin_binder=self.binder,
            clock=lambda: self.clock_value,
            sleeper=lambda seconds: setattr(
                self, "clock_value", self.clock_value + seconds
            ),
            companion_start_deadline_seconds=1.0,
            companion_stop_deadline_seconds=1.0,
            route_wait_seconds=0.0,
        )
        self.controller = SharingController(self.deps)

    def start_listener(self) -> bool:
        self.events.append("listener_start")
        if self.listener_start_ok:
            self.listener_running = True
        return self.listener_start_ok

    def stop_listener(self) -> None:
        if not self.listener_running:
            self.events.append("unexpected_listener_stop")
            return
        if self.listener_stop_fails:
            self.events.append("listener_stop_failed")
            raise RuntimeError("sentinel listener cleanup failure")
        self.events.append("listener_stop")
        self.listener_running = False

    def start_companion(self, _generation: int) -> FakeCompanion:
        self.events.append("companion_create")
        if self.companion_factory_fails:
            raise RuntimeError("sentinel companion construction failure")
        self.companion = FakeCompanion(
            self.events,
            start_result=self.companion_start_result,
        )
        return self.companion

    def route_status(self, companion: FakeCompanion, generation: int) -> RouteStatus:
        self.route_calls += 1
        if self.route_callback is not None:
            return self.route_callback(companion, generation)
        if self.route_results:
            return self.route_results.popleft()
        return RouteStatus(True, PLAYER_ORIGIN, generation)

    def set_route_sequence(self, *results: RouteStatus) -> None:
        self.route_results = deque(results)


class PlayerSharingLifecycleTests(unittest.TestCase):
    def test_ready_requires_full_same_generation_readiness(self) -> None:
        fixture = LifecycleFixture()
        snapshot = fixture.controller.start()

        self.assertEqual(snapshot.state, SharingState.READY)
        self.assertEqual(snapshot.reason, "ready")
        self.assertEqual(snapshot.generation, 1)
        self.assertTrue(snapshot.checks.ready)
        self.assertEqual(fixture.binder.generation, snapshot.generation)
        self.assertTrue(fixture.binder.is_bound)
        self.assertEqual(fixture.controller.invitation(), PLAYER_ORIGIN)
        self.assertTrue(fixture.controller.status().checks.ready)

    def test_prerequisite_failures_are_ordered_and_start_nothing(self) -> None:
        cases: tuple[tuple[str, str, SharingState], ...] = (
            ("unsupported_platform", "unsupported_platform", SharingState.UNSUPPORTED_PLATFORM),
            ("companion_missing", "companion_missing", SharingState.FAILED),
            ("identity_not_initialized", "identity_not_initialized", SharingState.INITIALIZING_REQUIRED),
            ("credential_absent", "credential_not_configured", SharingState.FAILED),
            ("credential_invalid", "credential_not_configured", SharingState.FAILED),
            ("runtime_down", "local_runtime_unavailable", SharingState.FAILED),
            ("assets_missing", "assets_unavailable", SharingState.FAILED),
        )
        for mode, reason, state in cases:
            with self.subTest(mode=mode):
                fixture = LifecycleFixture()
                if mode == "unsupported_platform":
                    fixture.resolution = CompanionResolution(
                        state="unsupported_platform", reason="unsupported_platform"
                    )
                elif mode == "companion_missing":
                    fixture.resolution = CompanionResolution(
                        state="missing_asset", reason="binary_missing"
                    )
                elif mode == "identity_not_initialized":
                    fixture.identity_ok = False
                elif mode == "credential_absent":
                    fixture.credential = FakeVerifierLoad("absent", None)
                elif mode == "credential_invalid":
                    fixture.credential = FakeVerifierLoad("invalid", None)
                elif mode == "runtime_down":
                    fixture.runtime_ok = False
                elif mode == "assets_missing":
                    fixture.assets_ok = False

                snapshot = fixture.controller.start()

                self.assertEqual(snapshot.state, state)
                self.assertEqual(snapshot.reason, reason)
                self.assertIsNone(fixture.controller.invitation())
                self.assertNotIn("listener_start", fixture.events)
                self.assertNotIn("companion_create", fixture.events)
                self.assertNotIn("listener_stop", fixture.events)
                self.assertNotIn("companion_stop", fixture.events)

    def test_precondition_order_short_circuits_at_first_failure(self) -> None:
        fixture = LifecycleFixture()
        fixture.identity_ok = False
        fixture.credential = FakeVerifierLoad("absent", None)
        fixture.runtime_ok = False
        fixture.assets_ok = False
        calls: list[str] = []
        fixture.deps = replace(
            fixture.deps,
            resolve_companion=lambda: calls.append("companion") or fixture.resolution,
            identity_initialized=lambda: calls.append("identity") or False,
            load_verifier=lambda: calls.append("credential") or fixture.credential,
            local_runtime_ok=lambda: calls.append("runtime") or False,
            assets_ok=lambda: calls.append("assets") or False,
        )
        fixture.controller = SharingController(fixture.deps)

        snapshot = fixture.controller.start()

        self.assertEqual(snapshot.reason, "identity_not_initialized")
        self.assertEqual(calls, ["companion", "identity"])

    def test_listener_start_and_authenticated_loopback_probe_fail_closed(self) -> None:
        start_failure = LifecycleFixture()
        start_failure.listener_start_ok = False
        failed_start = start_failure.controller.start()
        self.assertEqual(failed_start.reason, "listener_failed")
        self.assertEqual(start_failure.events.count("listener_start"), 1)
        self.assertNotIn("listener_stop", start_failure.events)
        self.assertNotIn("companion_create", start_failure.events)
        self.assertIsNone(start_failure.controller.invitation())

        probe_failure = LifecycleFixture()
        probe_failure.listener_probe_ok = False
        failed_probe = probe_failure.controller.start()
        self.assertEqual(failed_probe.reason, "listener_failed")
        self.assertEqual(probe_failure.events.count("listener_stop"), 1)
        self.assertNotIn("companion_create", probe_failure.events)
        self.assertNotIn("unexpected_listener_stop", probe_failure.events)
        self.assertIsNone(probe_failure.controller.invitation())

    def test_companion_start_failure_does_not_stop_unstarted_handle(self) -> None:
        fixture = LifecycleFixture()
        fixture.companion_start_result = "failed"

        snapshot = fixture.controller.start()

        self.assertEqual(snapshot.reason, "companion_failed")
        self.assertEqual(fixture.companion.start_calls if fixture.companion else 0, 1)
        self.assertEqual(fixture.companion.stop_calls if fixture.companion else 0, 0)
        self.assertEqual(fixture.events.count("listener_stop"), 1)
        self.assertNotIn("companion_stop", fixture.events)
        self.assertNotIn("unexpected_listener_stop", fixture.events)
        self.assertIsNone(fixture.controller.invitation())

    def test_companion_factory_failure_cleans_up_listener_only(self) -> None:
        fixture = LifecycleFixture()
        fixture.companion_factory_fails = True

        snapshot = fixture.controller.start()

        self.assertEqual(snapshot.reason, "companion_failed")
        self.assertEqual(fixture.events.count("listener_stop"), 1)
        self.assertNotIn("companion_start", fixture.events)
        self.assertNotIn("companion_stop", fixture.events)
        self.assertNotIn("unexpected_listener_stop", fixture.events)

    def test_route_and_origin_failures_unwind_started_resources(self) -> None:
        cases: tuple[tuple[str, RouteStatus, str], ...] = (
            ("unhealthy", RouteStatus(False, PLAYER_ORIGIN, 1), "route_unhealthy"),
            ("absent_origin", RouteStatus(True, None, 1), "origin_unbound"),
            ("unparsable_origin", RouteStatus(True, "not a URL", 1), "origin_unbound"),
            ("http_origin", RouteStatus(True, "http://sharing.example", 1), "origin_unbound"),
            ("wildcard_origin", RouteStatus(True, "https://*.sharing.example", 1), "origin_unbound"),
            ("stale_generation", RouteStatus(True, PLAYER_ORIGIN, 0), "stale_generation"),
        )
        for label, route, reason in cases:
            with self.subTest(label=label):
                fixture = LifecycleFixture()
                fixture.set_route_sequence(route)

                snapshot = fixture.controller.start()

                self.assertEqual(snapshot.state, SharingState.FAILED)
                self.assertEqual(snapshot.reason, reason)
                self.assertIsNone(fixture.controller.invitation())
                self.assertFalse(fixture.binder.is_bound)
                self.assertTrue(fixture.companion is not None and fixture.companion.reaped)
                self.assertEqual(
                    [event for event in fixture.events if event in {
                        "companion_stop", "listener_stop", "unexpected_companion_stop",
                        "unexpected_listener_stop"
                    }],
                    ["companion_stop", "listener_stop"],
                )

    def test_partial_startup_cleanup_is_reverse_order_and_only_for_started_items(self) -> None:
        fixture = LifecycleFixture()
        fixture.set_route_sequence(RouteStatus(False, PLAYER_ORIGIN, 1))

        snapshot = fixture.controller.start()

        self.assertEqual(snapshot.reason, "route_unhealthy")
        cleanup = [
            event
            for event in fixture.events
            if event in {
                "binding_clear",
                "companion_stop",
                "listener_stop",
                "unexpected_companion_stop",
                "unexpected_listener_stop",
            }
        ]
        self.assertEqual(cleanup[-3:], ["binding_clear", "companion_stop", "listener_stop"])
        self.assertNotIn("unexpected_companion_stop", cleanup)
        self.assertNotIn("unexpected_listener_stop", cleanup)
        self.assertTrue(fixture.companion is not None and fixture.companion.reaped)

    def test_changed_origin_after_initial_binding_fails_and_clears(self) -> None:
        fixture = LifecycleFixture()
        fixture.set_route_sequence(
            RouteStatus(True, PLAYER_ORIGIN, 1),
            RouteStatus(True, "https://changed-sharing.example", 1),
        )

        snapshot = fixture.controller.start()

        self.assertEqual(snapshot.state, SharingState.FAILED)
        self.assertEqual(snapshot.reason, "origin_changed")
        self.assertFalse(fixture.binder.is_bound)
        self.assertEqual(fixture.security.public_origin_status, (False, None))
        self.assertIsNone(fixture.controller.invitation())
        self.assertTrue(fixture.companion is not None and fixture.companion.reaped)

    def test_new_start_uses_new_generation_and_discards_old_route_status(self) -> None:
        fixture = LifecycleFixture()
        fixture.set_route_sequence(
            RouteStatus(True, SENTINEL_URL, 0),
            RouteStatus(True, PLAYER_ORIGIN, 2),
            RouteStatus(True, PLAYER_ORIGIN, 2),
        )

        first = fixture.controller.start()
        self.assertEqual(first.generation, 1)
        self.assertEqual(first.reason, "stale_generation")
        self.assertIsNone(fixture.controller.invitation())
        self.assertFalse(fixture.binder.is_bound)

        second = fixture.controller.start()
        self.assertEqual(second.generation, 2)
        self.assertEqual(second.state, SharingState.READY)
        self.assertEqual(fixture.controller.invitation(), PLAYER_ORIGIN)
        self.assertNotEqual(fixture.binder.generation, 1)

    def test_recheck_regression_withdraws_binding_and_requires_fresh_full_pass(self) -> None:
        fixture = LifecycleFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        fixture.set_route_sequence(RouteStatus(False, PLAYER_ORIGIN, 1))

        self.assertFalse(fixture.controller.recheck_readiness())
        self.assertEqual(fixture.controller.state, SharingState.DEGRADED)
        self.assertEqual(fixture.controller.reason, "route_unhealthy")
        self.assertFalse(fixture.binder.is_bound)
        self.assertIsNone(fixture.controller.invitation())

        fixture.set_route_sequence(RouteStatus(True, PLAYER_ORIGIN, 1))
        self.assertTrue(fixture.controller.recheck_readiness())
        self.assertEqual(fixture.controller.state, SharingState.READY)
        self.assertTrue(fixture.binder.is_bound)
        self.assertEqual(fixture.controller.invitation(), PLAYER_ORIGIN)

    def test_stop_is_idempotent_and_clears_player_security_binding(self) -> None:
        fixture = LifecycleFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        self.assertEqual(fixture.security.public_origin_status, (True, 1))

        first_stop = fixture.controller.stop()
        first_stop_count = fixture.events.count("listener_stop")
        first_companion_stops = fixture.events.count("companion_stop")
        second_stop = fixture.controller.stop()

        self.assertEqual(first_stop.state, SharingState.OFF)
        self.assertEqual(first_stop.reason, "stopped")
        self.assertEqual(second_stop.state, SharingState.OFF)
        self.assertEqual(fixture.security.public_origin_status, (False, None))
        self.assertFalse(fixture.binder.is_bound)
        self.assertEqual(fixture.events.count("listener_stop"), first_stop_count)
        self.assertEqual(fixture.events.count("companion_stop"), first_companion_stops)
        self.assertIsNone(fixture.controller.invitation())

    def test_stop_sharing_revokes_n1_sessions_challenges_sockets_and_origin(self) -> None:
        verifier = make_verifier("stop-sharing-test-password", salt=b"s" * 16)
        security = PlayerSecurity(lambda: verifier)
        binder = PublicOriginBinder(security)
        companion = FakeCompanion([])
        stopped_socket_ids: list[str] = []
        listener_running = False

        def start_listener() -> bool:
            nonlocal listener_running
            security.start_listener()
            listener_running = True
            return True

        def stop_listener() -> None:
            nonlocal listener_running
            stopped_socket_ids.extend(security.stop_listener())
            listener_running = False

        dependencies = SharingDependencies(
            local_runtime_ok=lambda: True,
            assets_ok=lambda: True,
            start_player_listener=start_listener,
            stop_player_listener=stop_listener,
            listener_authenticated_probe=lambda: listener_running,
            load_verifier=lambda: FakeVerifierLoad("present", object()),
            resolve_companion=lambda: CompanionResolution(
                state="resolved",
                reason="resolved",
                path=Path("fixture-opentunnel"),
            ),
            identity_initialized=lambda: True,
            start_companion=lambda _generation: companion,
            route_status=lambda _companion, generation: RouteStatus(
                True, PLAYER_ORIGIN, generation
            ),
            origin_binder=binder,
            route_wait_seconds=0.0,
        )
        controller = SharingController(dependencies)
        self.assertEqual(controller.start().state, SharingState.READY)

        grant = security.create_session()
        challenge = security.issue_prelogin_challenge()
        self.assertIsNotNone(grant)
        self.assertIsNotNone(challenge)
        assert grant is not None and challenge is not None
        self.assertTrue(
            security.register_socket(
                "stop-sharing-client",
                grant.cookie_value,
                "sharing-route.example",
                PLAYER_ORIGIN,
            )
        )
        self.assertTrue(security.authorize_socket_event("stop-sharing-client"))

        stopped = controller.stop()

        self.assertEqual(stopped.state, SharingState.OFF)
        self.assertEqual(stopped_socket_ids, ["stop-sharing-client"])
        self.assertEqual(security.active_session_count, 0)
        self.assertEqual(security.active_socket_count, 0)
        self.assertIsNone(security.session_id_for_cookie(grant.cookie_value))
        self.assertFalse(security.csrf_is_valid(grant.cookie_value, grant.csrf_token))
        self.assertFalse(
            security.consume_prelogin_challenge(
                challenge.cookie_value,
                challenge.csrf_nonce,
            )
        )
        self.assertFalse(security.authorize_socket_event("stop-sharing-client"))
        self.assertFalse(binder.is_bound)
        self.assertEqual(security.public_origin_status, (False, None))

    def test_rotation_rebinds_only_after_fresh_readiness_pass(self) -> None:
        fixture = LifecycleFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        order: list[str] = []
        replacement_origin = "https://replacement-sharing.example"

        def route_status(_companion: FakeCompanion, generation: int) -> RouteStatus:
            order.append("fresh_status")
            return RouteStatus(True, replacement_origin, generation)

        fixture.route_callback = route_status

        def rotate_access() -> None:
            self.assertFalse(fixture.binder.is_bound)
            self.assertEqual(fixture.security.public_origin_status, (False, None))
            order.append("credential_replaced")

        rotated = fixture.controller.rotate(rotate_access)

        self.assertEqual(order, ["credential_replaced", "fresh_status"])
        self.assertEqual(rotated.state, SharingState.READY)
        self.assertTrue(fixture.binder.is_bound)
        self.assertEqual(fixture.controller.invitation(), replacement_origin)

    def test_rotation_readiness_failure_keeps_origin_cleared(self) -> None:
        fixture = LifecycleFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        fixture.route_callback = lambda _companion, generation: RouteStatus(
            False, PLAYER_ORIGIN, generation
        )

        rotated = fixture.controller.rotate(lambda: None)

        self.assertEqual(rotated.state, SharingState.DEGRADED)
        self.assertEqual(rotated.reason, "route_unhealthy")
        self.assertFalse(fixture.binder.is_bound)
        self.assertEqual(fixture.security.public_origin_status, (False, None))
        self.assertIsNone(fixture.controller.invitation())

    def test_stop_never_raises_and_retains_failed_cleanup_for_retry(self) -> None:
        fixture = LifecycleFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)
        fixture.listener_stop_fails = True

        failed_stop = fixture.controller.stop()

        self.assertEqual(failed_stop.state, SharingState.OFF)
        self.assertEqual(failed_stop.reason, "cleanup_failed")
        self.assertFalse(fixture.binder.is_bound)
        self.assertTrue(fixture.listener_running)

        fixture.listener_stop_fails = False
        retried_stop = fixture.controller.stop()
        self.assertEqual(retried_stop.reason, "stopped")
        self.assertFalse(fixture.listener_running)
        self.assertTrue(fixture.companion is not None and fixture.companion.reaped)

    def test_degraded_and_failed_helpers_clear_binding_without_invitation(self) -> None:
        fixture = LifecycleFixture()
        self.assertEqual(fixture.controller.start().state, SharingState.READY)

        degraded = fixture.controller.mark_degraded("route_unhealthy")
        self.assertEqual(degraded.state, SharingState.DEGRADED)
        self.assertFalse(fixture.binder.is_bound)
        self.assertIsNone(fixture.controller.invitation())

        failed = fixture.controller.mark_failed("companion_failed")
        self.assertEqual(failed.state, SharingState.FAILED)
        self.assertFalse(fixture.binder.is_bound)
        self.assertIsNone(fixture.controller.invitation())

    def test_status_repr_and_logs_exclude_verifier_and_invitation_sentinels(self) -> None:
        fixture = LifecycleFixture()
        fixture.set_route_sequence(
            RouteStatus(True, SENTINEL_URL, 1),
            RouteStatus(True, SENTINEL_URL, 1),
            RouteStatus(True, SENTINEL_URL, 1),
        )
        with self.assertNoLogs():
            snapshot = fixture.controller.start()
            invitation = fixture.controller.invitation()

        self.assertEqual(snapshot.state, SharingState.READY)
        self.assertEqual(invitation, SENTINEL_URL)
        observable = " ".join(
            (
                repr(snapshot),
                repr(fixture.controller.status()),
                repr(fixture.binder),
                repr(fixture.deps),
            )
        )
        self.assertNotIn(SENTINEL_CREDENTIAL, observable)
        self.assertNotIn(SENTINEL_URL, observable)
        self.assertNotIn("neq-scrypt", observable)

    def test_controller_source_has_no_process_or_network_imports(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "web/extensions/opentunnel_sharing/controller.py"
        )
        source = source_path.read_text(encoding="ascii")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported.intersection({"subprocess", "socket", "urllib"}))


if __name__ == "__main__":
    unittest.main()
