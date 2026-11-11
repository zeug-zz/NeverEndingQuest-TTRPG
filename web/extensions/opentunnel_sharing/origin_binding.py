# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Generation-scoped exact public-origin binding for the N1 player boundary."""

from __future__ import annotations

import threading

from web.extensions.player.auth import PlayerSecurity, _parse_public_https_origin

_CLEAR_REASONS = frozenset({"stop", "failed", "degraded", "rotation"})


class PublicOriginBinder:
    """Bind only a ready companion origin reported for the active generation."""

    __slots__ = (
        "_security",
        "_lock",
        "_generation",
        "_origin",
        "_state",
        "_terminal_generation",
    )

    def __init__(self, security: PlayerSecurity) -> None:
        self._security = security
        self._lock = threading.RLock()
        self._generation: int | None = None
        self._origin: str | None = None
        self._state = "unbound"
        self._terminal_generation = False

    @property
    def generation(self) -> int | None:
        """Return the active generation without exposing the public origin."""
        with self._lock:
            return self._generation

    @property
    def state(self) -> str:
        """Return only a bounded binding state, never the origin value."""
        with self._lock:
            self._reconcile_security_binding_locked()
            return self._state

    @property
    def is_bound(self) -> bool:
        with self._lock:
            self._reconcile_security_binding_locked()
            return self._origin is not None

    def begin_generation(self, generation: int) -> bool:
        """Start a strictly newer generation and discard any prior binding."""
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            return False
        with self._lock:
            if self._generation is not None and generation <= self._generation:
                return False
            self._security.clear_public_origin("generation_started")
            if not self._security.set_active_origin_generation(generation):
                return False
            self._generation = generation
            self._origin = None
            self._state = "unbound"
            self._terminal_generation = False
            return True

    def bind(
        self,
        status_origin: object,
        status_generation: object,
        ready: bool,
    ) -> bool:
        """Bind a valid status origin only after same-generation route readiness."""
        with self._lock:
            generation = self._generation
            if (
                generation is None
                or not isinstance(status_generation, int)
                or isinstance(status_generation, bool)
                or status_generation != generation
            ):
                return False
            if self._terminal_generation:
                return False
            if ready is not True:
                self._clear_locked("not_ready")
                return False

            parsed = _parse_public_https_origin(status_origin)
            if parsed is None:
                self._clear_locked("invalid_origin")
                return False
            canonical_origin, _authority = parsed

            if self._origin is not None and self._origin != canonical_origin:
                self._clear_locked("origin_changed")
                return False
            if not self._security.set_active_origin_generation(generation):
                return False
            if not self._security.bind_public_origin(generation, canonical_origin):
                self._clear_locked("binding_rejected")
                return False

            self._origin = canonical_origin
            self._state = "bound"
            return True

    def clear(self, reason: str) -> None:
        """Clear on stop/failure/degradation or before accepting rotated access.

        The sharing lifecycle and credential-rotation caller own these calls.
        """
        selected_reason = (
            reason if isinstance(reason, str) and reason in _CLEAR_REASONS else "cleared"
        )
        with self._lock:
            self._clear_locked(selected_reason)

    def _clear_locked(self, reason: str) -> None:
        self._security.clear_public_origin(reason)
        self._origin = None
        self._state = reason
        if reason in (
            "origin_changed",
            "invalid_origin",
            "binding_rejected",
            "stop",
            "failed",
            "cleared",
        ):
            self._terminal_generation = True

    def _reconcile_security_binding_locked(self) -> None:
        bound, generation = self._security.public_origin_status
        if self._origin is not None and (
            not bound or generation != self._generation
        ):
            self._origin = None
            self._state = "unbound"
