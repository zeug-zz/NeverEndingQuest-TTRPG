# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free regressions for active player-origin generations."""

from __future__ import annotations

import threading
import unittest

from web.extensions.opentunnel_sharing.origin_binding import PublicOriginBinder
from web.extensions.player.auth import PlayerSecurity

LOCAL_HOST = "127.0.0.1:8370"
LOCAL_ORIGIN = "http://127.0.0.1:8370"
OLD_HOST = "old-sharing.example"
OLD_ORIGIN = "https://old-sharing.example"
NEW_HOST = "new-sharing.example"
NEW_ORIGIN = "https://new-sharing.example"


class BarrierPlayerSecurity(PlayerSecurity):
    """Pause a generation transition after its old binding has been withdrawn."""

    def __init__(self) -> None:
        self.pause_generation_start = False
        self.binding_cleared = threading.Barrier(2)
        self.resume_transition = threading.Barrier(2)
        super().__init__(lambda: None)

    def clear_public_origin(self, reason: str | None = None) -> None:
        super().clear_public_origin(reason)
        if self.pause_generation_start and reason == "generation_started":
            self.binding_cleared.wait(timeout=3)
            self.resume_transition.wait(timeout=3)


class PlayerOriginGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.security = PlayerSecurity(lambda: None)
        self.binder = PublicOriginBinder(self.security)

    def test_bound_public_pair_requires_its_active_generation(self) -> None:
        self.assertTrue(self.binder.begin_generation(4))
        self.assertEqual(self.security.active_origin_generation, 4)
        self.assertTrue(self.binder.bind(OLD_ORIGIN, 4, ready=True))
        self.assertTrue(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )
        self.assertTrue(
            self.security.request_identity_is_valid(
                LOCAL_HOST, LOCAL_ORIGIN, require_origin=True
            )
        )

    def test_new_generation_rejects_the_old_origin_until_fresh_bind(self) -> None:
        self.assertTrue(self.binder.begin_generation(1))
        self.assertTrue(self.binder.bind(OLD_ORIGIN, 1, ready=True))
        self.assertTrue(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )

        self.assertTrue(self.binder.begin_generation(2))
        self.assertEqual(self.security.active_origin_generation, 2)
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(self.binder.bind(OLD_ORIGIN, 1, ready=True))
        self.assertTrue(self.binder.bind(NEW_ORIGIN, 2, ready=True))
        self.assertTrue(
            self.security.request_identity_is_valid(
                NEW_HOST, NEW_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )

    def test_listener_stop_restart_requires_a_new_generation_and_new_origin(self) -> None:
        self.assertTrue(self.binder.begin_generation(1))
        self.assertTrue(self.binder.bind(OLD_ORIGIN, 1, ready=True))
        self.security.stop_listener()
        self.assertIsNone(self.security.active_origin_generation)
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )
        self.security.start_listener()
        self.assertIsNone(self.security.active_origin_generation)
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )

        self.assertTrue(self.binder.begin_generation(2))
        self.assertFalse(self.binder.bind(OLD_ORIGIN, 1, ready=True))
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )
        self.assertTrue(self.binder.bind(NEW_ORIGIN, 2, ready=True))
        self.assertTrue(
            self.security.request_identity_is_valid(
                NEW_HOST, NEW_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )

    def test_rotation_withdraws_origin_until_a_fresh_bind(self) -> None:
        self.assertTrue(self.binder.begin_generation(8))
        self.assertTrue(self.binder.bind(OLD_ORIGIN, 8, ready=True))
        self.binder.clear("rotation")
        self.assertIsNone(self.security.active_origin_generation)
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )

        self.assertTrue(self.binder.bind(NEW_ORIGIN, 8, ready=True))
        self.assertTrue(
            self.security.request_identity_is_valid(
                NEW_HOST, NEW_ORIGIN, require_origin=True
            )
        )
        self.assertFalse(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )

    def test_direct_security_misuse_cannot_bind_or_activate_an_older_generation(self) -> None:
        self.assertFalse(self.security.bind_public_origin(1, OLD_ORIGIN))
        self.assertTrue(self.security.set_active_origin_generation(2))
        self.assertFalse(self.security.bind_public_origin(1, OLD_ORIGIN))
        self.assertFalse(self.security.set_active_origin_generation(1))
        self.assertTrue(self.security.bind_public_origin(2, OLD_ORIGIN))
        self.assertFalse(self.security.set_active_origin_generation(1))
        self.assertTrue(
            self.security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )
        self.assertTrue(
            self.security.request_identity_is_valid(
                LOCAL_HOST, LOCAL_ORIGIN, require_origin=True
            )
        )

    def test_socket_from_old_generation_stays_denied_even_if_pair_is_rebound(self) -> None:
        self.assertTrue(self.binder.begin_generation(1))
        self.assertTrue(self.binder.bind(OLD_ORIGIN, 1, ready=True))
        grant = self.security.create_session()
        self.assertIsNotNone(grant)
        assert grant is not None
        self.assertTrue(
            self.security.register_socket(
                "old-generation-socket",
                grant.cookie_value,
                OLD_HOST,
                OLD_ORIGIN,
            )
        )
        self.assertTrue(self.security.authorize_socket_event("old-generation-socket"))

        self.assertTrue(self.binder.begin_generation(2))
        self.assertFalse(self.security.authorize_socket_event("old-generation-socket"))
        self.assertTrue(self.binder.bind(OLD_ORIGIN, 2, ready=True))
        self.assertFalse(self.security.authorize_socket_event("old-generation-socket"))
        self.assertNotIn("old-generation-socket", self.security.authorized_socket_ids())

    def test_request_racing_generation_transition_sees_binding_withdrawn(self) -> None:
        security = BarrierPlayerSecurity()
        binder = PublicOriginBinder(security)
        self.assertTrue(binder.begin_generation(1))
        self.assertTrue(binder.bind(OLD_ORIGIN, 1, ready=True))
        security.pause_generation_start = True
        result: list[bool] = []
        failures: list[BaseException] = []

        def begin_next_generation() -> None:
            try:
                result.append(binder.begin_generation(2))
            except BaseException as exc:
                failures.append(exc)

        transition = threading.Thread(target=begin_next_generation)
        transition.start()
        security.binding_cleared.wait(timeout=3)
        self.assertIsNone(security.active_origin_generation)
        accepted = security.request_identity_is_valid(
            OLD_HOST, OLD_ORIGIN, require_origin=True
        )
        security.resume_transition.wait(timeout=3)
        transition.join(timeout=3)

        self.assertFalse(transition.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(result, [True])
        self.assertFalse(accepted)
        self.assertFalse(
            security.request_identity_is_valid(
                OLD_HOST, OLD_ORIGIN, require_origin=True
            )
        )


if __name__ == "__main__":
    unittest.main()
