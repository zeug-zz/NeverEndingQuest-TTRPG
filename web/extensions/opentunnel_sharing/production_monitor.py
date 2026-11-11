# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded production health observations for one sharing generation."""

# TABLETOP MODE: this monitor observes sharing infrastructure only. It never
# reads or changes gameplay state or player-input queues.

from __future__ import annotations

from typing import Callable, Protocol

from web.extensions.opentunnel_sharing.controller import (
    SharingSnapshot,
    SharingState,
)
from web.extensions.opentunnel_sharing.relay_supervision import (
    RelayHealthObservation,
)


class _SupervisionController(Protocol):
    def status(self) -> SharingSnapshot: ...

    def supervision_companion_diagnostics(
        self, generation: int
    ) -> tuple[str, str | None] | None: ...

    def supervision_route_healthy(self, generation: int) -> bool: ...


class ProductionRelayMonitor:
    """Probe the owned child, its generation-bound route, and loopback listener.

    The controller delegates child diagnostics to the owned-process supervisor
    and route health to its existing bounded status-command parser. The
    listener callback must use the authenticated loopback probe. No URL,
    companion output, exception text, or credential is retained in observations.
    """

    def __init__(
        self,
        controller: _SupervisionController,
        listener_probe: Callable[[int], bool],
    ) -> None:
        if controller is None or not callable(getattr(controller, "status", None)):
            raise TypeError("sharing_controller_required")
        if not callable(
            getattr(controller, "supervision_companion_diagnostics", None)
        ) or not callable(getattr(controller, "supervision_route_healthy", None)):
            raise TypeError("sharing_supervision_probe_required")
        if not callable(listener_probe):
            raise TypeError("sharing_listener_probe_required")
        self._controller = controller
        self._listener_probe = listener_probe

    def observe(self, generation: int) -> RelayHealthObservation:
        """Return one bounded observation tagged with the requested generation."""
        if type(generation) is not int or generation < 1:
            raise ValueError("monitor_generation_invalid")
        try:
            before = self._controller.status()
            if not _is_active_generation(before, generation):
                return _unhealthy_observation(generation)

            child = self._controller.supervision_companion_diagnostics(generation)
            if (
                not isinstance(child, tuple)
                or len(child) != 2
                or not isinstance(child[0], str)
            ):
                raise RuntimeError("monitor_failed")
            child_state = (
                "alive"
                if child[0] == "running"
                else "exited"
                if child[0] in {"exited", "failed", "stopped"}
                else "unknown"
            )
            exit_code_bucket = (
                child[1]
                if child[1] in {"success", "failure", "signal"}
                else None
            )
            route_healthy = (
                self._controller.supervision_route_healthy(generation) is True
            )
            listener_healthy = self._listener_probe(generation) is True
            after = self._controller.status()
            if not _is_active_generation(after, generation):
                return _unhealthy_observation(generation)
            return RelayHealthObservation(
                generation=generation,
                child_state=child_state,  # type: ignore[arg-type]
                route_healthy=route_healthy,
                listener_healthy=listener_healthy,
                exit_code_bucket=exit_code_bucket,  # type: ignore[arg-type]
            )
        except Exception:
            # RelaySupervisor maps this fixed failure to monitor_failed. Raw
            # exception text must never reach bounded service diagnostics.
            raise RuntimeError("monitor_failed") from None


def _is_active_generation(snapshot: object, generation: int) -> bool:
    state = getattr(snapshot, "state", None)
    state = getattr(state, "value", state)
    return bool(
        getattr(snapshot, "generation", None) == generation
        and state in {SharingState.READY.value, SharingState.DEGRADED.value}
    )


def _unhealthy_observation(generation: int) -> RelayHealthObservation:
    return RelayHealthObservation(
        generation=generation,
        child_state="unknown",
        route_healthy=False,
        listener_healthy=False,
    )
