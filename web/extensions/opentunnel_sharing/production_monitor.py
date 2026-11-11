# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded production health observations for one sharing generation."""

# TABLETOP MODE: this monitor observes sharing infrastructure only. It never
# reads or changes gameplay state or player-input queues.

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Callable, Protocol

from web.extensions.opentunnel_sharing.controller import (
    SharingSnapshot,
    SharingState,
)
from web.extensions.opentunnel_sharing.relay_supervision import (
    RecoveryPolicy,
    RelayHealthObservation,
)
from utils.provider_attempt_budget import _is_isolated_capture_root


_LOGGER = logging.getLogger(__name__)
N3_RECOVERY_ATTEMPTS_ENV = "NEQ_N3_GATE_MAX_RECOVERY_ATTEMPTS"
N3_GATE_RUN_ID_ENV = "NEQ_N3_GATE_RUN_ID"
_N3_GATE_RUN_ID_PATTERN = re.compile(r"[a-z0-9-]{8,64}\Z")
_RECOVERY_OVERRIDE_REASONS = frozenset(
    {
        "recovery_override_not_integer",
        "recovery_override_out_of_range",
        "runtime_root_unavailable",
        "runtime_root_symlinked",
        "runtime_root_not_isolated",
        "web_port_mismatch",
        "run_id_invalid",
    }
)


def production_recovery_policy(web_port: object) -> RecoveryPolicy:
    """Select the default production policy or a valid isolated N3 test budget.

    The caller supplies only the already-selected host listener port. This helper
    intentionally does not import config.py or inspect any other configuration.
    """
    default_policy = RecoveryPolicy()
    if N3_RECOVERY_ATTEMPTS_ENV not in os.environ:
        return default_policy

    raw_attempts = os.environ.get(N3_RECOVERY_ATTEMPTS_ENV, "")
    if re.fullmatch(r"[0-9]+", raw_attempts) is None:
        return _ignored_recovery_override(
            default_policy, "recovery_override_not_integer"
        )
    try:
        attempts = int(raw_attempts)
    except ValueError:
        return _ignored_recovery_override(
            default_policy, "recovery_override_out_of_range"
        )
    if not 1 <= attempts <= 3 or attempts > default_policy.max_attempts:
        return _ignored_recovery_override(
            default_policy, "recovery_override_out_of_range"
        )

    context_reason = _n3_recovery_context_reason(web_port, source_path=__file__)
    if context_reason is not None:
        return _ignored_recovery_override(default_policy, context_reason)

    return RecoveryPolicy(
        max_attempts=attempts,
        backoff_schedule=default_policy.backoff_schedule[:attempts],
        health_check_interval=default_policy.health_check_interval,
        max_delay=default_policy.max_delay,
        jitter_seconds=default_policy.jitter_seconds,
    )


def _n3_recovery_context_reason(
    web_port: object, *, source_path: str | Path = __file__
) -> str | None:
    if type(web_port) is not int or web_port != 8360:
        return "web_port_mismatch"

    run_id = os.environ.get(N3_GATE_RUN_ID_ENV)
    if not isinstance(run_id, str) or _N3_GATE_RUN_ID_PATTERN.fullmatch(run_id) is None:
        return "run_id_invalid"

    try:
        runtime_source = Path(os.path.abspath(os.fspath(source_path)))
        resolved_source = runtime_source.resolve(strict=True)
        if runtime_source != resolved_source:
            return "runtime_root_symlinked"
        if not runtime_source.is_file():
            return "runtime_root_unavailable"
        if (
            len(runtime_source.parents) < 4
            or runtime_source.name != "production_monitor.py"
            or runtime_source.parents[0].name != "opentunnel_sharing"
            or runtime_source.parents[1].name != "extensions"
            or runtime_source.parents[2].name != "web"
        ):
            return "runtime_root_not_isolated"
        runtime_root = runtime_source.parents[3]
        if runtime_root.is_symlink():
            return "runtime_root_symlinked"
        resolved_root = runtime_root.resolve(strict=True)
    except (IndexError, OSError, RuntimeError, TypeError, ValueError):
        return "runtime_root_unavailable"

    if runtime_root != resolved_root:
        return "runtime_root_symlinked"
    if not resolved_root.is_dir():
        return "runtime_root_unavailable"
    if resolved_root.parts[-2:] != ("tmp", "combat_capture"):
        return "runtime_root_not_isolated"
    try:
        if _is_isolated_capture_root(resolved_root) is not True:
            return "runtime_root_not_isolated"
    except Exception:
        return "runtime_root_not_isolated"
    return None


def _ignored_recovery_override(
    default_policy: RecoveryPolicy, reason: str
) -> RecoveryPolicy:
    safe_reason = (
        reason if reason in _RECOVERY_OVERRIDE_REASONS else "recovery_override_not_integer"
    )
    _LOGGER.warning("N3_RECOVERY_OVERRIDE_IGNORED: %s", safe_reason)
    return default_policy


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
