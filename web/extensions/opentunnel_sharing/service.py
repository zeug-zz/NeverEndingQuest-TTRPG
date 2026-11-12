# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Host-only facade and lazy production composition for player sharing."""

# TABLETOP MODE: This facade owns only facilitator-local sharing lifecycle controls.

from __future__ import annotations

import hashlib
import http.client
import os
import platform
import re
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from web.extensions.opentunnel_sharing.cleanup import (
    CleanupDependencies,
    ProcessIdentity,
    ProcessObservation,
    ReconcileResult,
    RouteObservation,
)
from web.extensions.opentunnel_sharing.companion import (
    CompanionResolution,
    resolve_companion,
    verify_companion_digest,
)
from web.extensions.opentunnel_sharing.controller import (
    MAX_DIAGNOSTIC_COUNTER,
    MAX_COMPANION_START_DEADLINE_SECONDS,
    MAX_ROUTE_POLL_INTERVAL_SECONDS,
    MAX_ROUTE_WAIT_SECONDS,
    RouteStatus,
    SharingController,
    SharingCounters,
    SharingDependencies,
    SharingSnapshot,
    SharingState,
    ReadinessChecks,
)
from web.extensions.opentunnel_sharing.identity_bootstrap import (
    BootstrapResult,
    DefaultCommandRunner,
    DefaultIdentityObserver,
    MAX_RESULT_FACTS,
    RunResult,
    _read_marker,
    bootstrap_identity,
)
from web.extensions.opentunnel_sharing.origin_binding import PublicOriginBinder
from web.extensions.opentunnel_sharing.production_monitor import (
    ProductionRelayMonitor,
    production_recovery_policy,
)
from web.extensions.opentunnel_sharing.profile_state import (
    DEFAULT_PROFILE,
    ProfileLayout,
    ProfileState,
    companion_environment,
    default_state_root,
    prepare_profile,
)
from web.extensions.opentunnel_sharing import native_process_info as process_info
from web.extensions.opentunnel_sharing.runtime_manifest import (
    ManifestError as RuntimeManifestError,
    load_companion_manifest as _read_companion_manifest,
)
from web.extensions.opentunnel_sharing.supervisor import (
    Identity,
    OwnedCompanion,
    probe_process_identity,
)
from web.extensions.opentunnel_sharing.relay_supervision import (
    CancellableSleeper,
    RecoveryPolicy,
    RelayMonitor,
    RelaySupervisor,
    RelaySupervisionSnapshot,
)
from web.extensions.opentunnel_sharing.verifier_store import (
    IssuedCredential,
    VerifierLoad,
    VerifierStatus,
    VerifierStoreError,
    issue_credential,
    load_verifier,
    revoke_access,
    rotate_credential,
    verifier_status,
)
from web.extensions.player.assets import PlayerClientAssetsError, load_player_client_assets
from web.extensions.player.auth import PlayerSecurity, _parse_public_https_origin
from web.extensions.player.constants import PLAYER_HOST, PLAYER_PORT
from web.extensions.player.gateway import PlayerGateway
from web.extensions.player.listener import PlayerListener

MAX_STATUS_COMMAND_SECONDS = 15.0
LOOPBACK_PROBE_TIMEOUT_SECONDS = 1.0
MAX_SUPERVISION_JOIN_SECONDS = (
    MAX_STATUS_COMMAND_SECONDS + LOOPBACK_PROBE_TIMEOUT_SECONDS + 1.0
)
MAX_PROFILE_ROUTE_BYTES = 1024
_PROFILE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?\Z")
_ROUTE_LINE_PATTERN = re.compile(r"^\s*(\S+)\s+(?:\u2192|->)\s+(\S+)\s*$")
_HOSTNAME_LINE_PATTERN = re.compile(r"(?im)^\s*Hostname:\s*(\S+)\s*$")
_SERVICE_LINE_PATTERN = re.compile(r"(?im)^\s*Service:\s*(.+?)\s*$")
_SAFE_CONTROLLER_REASONS = frozenset(
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
        "monitor_failed",
        "reconnect_budget_exhausted",
        "route_unhealthy",
        "origin_unbound",
        "origin_changed",
        "stale_generation",
        "startup_cancelled",
        "readiness_regressed",
        "cleanup_failed",
        "cleanup_ambiguous",
        "shutting_down",
    }
)
_SAFE_BOOTSTRAP_REASONS = frozenset(
    {
        "facilitator_confirmation_required",
        "profile_layout_not_ready",
        "companion_unresolved",
        "companion_unavailable",
        "companion_not_executable",
        "companion_digest_mismatch",
        "deadline_invalid",
        "bootstrap_dependency_invalid",
        "marker_valid",
        "marker_invalid",
        "profile_lock_unavailable",
        "profile_lock_timeout",
        "environment_allowlist_invalid",
        "preexisting_owned_resource",
        "precheck_unproven",
        "status_unproven",
        "up_failed_status_unproven",
        "owned_resource_remains",
        "postcheck_unproven",
        "down_failed",
        "up_failed",
        "marker_write_failed",
        "identity_initialized",
    }
)


def load_companion_manifest(install_root: Path) -> Mapping[str, Mapping[str, str]]:
    """Load the strict install-relative runtime companion manifest."""
    return _read_companion_manifest(install_root)


def validate_tunnel_target(host: object, port: object) -> str:
    """Accept only the exact player listener as an OpenTunnel route target."""
    expected_host = "127.0.0.1"
    expected_port = 8370
    if (
        PLAYER_HOST != expected_host
        or type(PLAYER_PORT) is not int
        or PLAYER_PORT != expected_port
        or not isinstance(host, str)
        or host != expected_host
        or type(port) is not int
        or port != expected_port
    ):
        raise ValueError("tunnel_target_invalid")
    return "%s:%d" % (expected_host, expected_port)


@dataclass(frozen=True, slots=True)
class SharingServiceStatus:
    """Safe status projection; it contains no raw URL, verifier, or process data."""

    lifecycle: SharingSnapshot
    profile_state: str
    identity_initialized: bool
    credential_state: str
    credential_generation: int | None = None
    credential_issued_at: str | None = None
    supervision: RelaySupervisionSnapshot | None = None
    companion_launches: int = 0
    identity_up_invocations: int = 0


@dataclass(frozen=True, slots=True, repr=False)
class SharingActionResult:
    """Bounded action result with explicit one-time/transient presentation fields."""

    operation: str
    ok: bool
    reason: str
    status: SharingServiceStatus
    bootstrap_state: str | None = None
    reconciliation_state: str | None = None
    sharing_available: bool | None = None
    credential: IssuedCredential | None = None
    invitation: str | None = None

    def __repr__(self) -> str:
        return (
            "SharingActionResult(operation=%r, ok=%r, reason=%r, state=%r)"
            % (
                self.operation,
                self.ok,
                self.reason,
                self.status.lifecycle.state.value,
            )
        )


@dataclass(frozen=True, slots=True, repr=False)
class SharingServiceDependencies:
    """Injectable host/service seams; construction itself performs no operations."""

    prepare_profile: Callable[[bool], ProfileState]
    identity_initialized: Callable[[ProfileLayout], bool]
    verifier_status: Callable[[ProfileLayout], VerifierStatus]
    resolve_companion: Callable[[], CompanionResolution]
    initialize_identity: Callable[
        [ProfileLayout, CompanionResolution, bool], BootstrapResult
    ]
    controller_factory: Callable[[ProfileLayout], SharingController]
    issue_credential: Callable[[ProfileLayout], IssuedCredential]
    rotate_credential: Callable[[ProfileLayout], IssuedCredential]
    revoke_access: Callable[[ProfileLayout], VerifierLoad]
    relay_monitor_factory: (
        Callable[[SharingController, int], RelayMonitor] | None
    ) = None

    def __repr__(self) -> str:
        return "SharingServiceDependencies(<injected>)"

    def __post_init__(self) -> None:
        for field_name in (
            "prepare_profile",
            "identity_initialized",
            "verifier_status",
            "resolve_companion",
            "initialize_identity",
            "controller_factory",
            "issue_credential",
            "rotate_credential",
            "revoke_access",
        ):
            if not callable(getattr(self, field_name)):
                raise TypeError("sharing_service_dependency_invalid")
        if self.relay_monitor_factory is not None and not callable(
            self.relay_monitor_factory
        ):
            raise TypeError("sharing_service_dependency_invalid")


@dataclass(slots=True)
class _SupervisionRuntime:
    """One daemon monitor owned by one controller generation/revision."""

    generation: int
    lifecycle_revision: int
    stop_event: threading.Event
    supervisor: RelaySupervisor
    thread: threading.Thread | None = None
    terminal_snapshot: RelaySupervisionSnapshot | None = None


class PlayerSharingService:
    """Local-facilitator API over the generation-bound sharing controller."""

    def __init__(
        self,
        dependencies: SharingServiceDependencies,
        *,
        recovery_policy: RecoveryPolicy | None = None,
        supervision_clock: Callable[[], float] = time.monotonic,
        supervision_sleeper: CancellableSleeper | None = None,
        run_supervision_thread: bool = True,
    ) -> None:
        if not isinstance(dependencies, SharingServiceDependencies):
            raise TypeError("sharing_service_dependencies_required")
        selected_policy = recovery_policy or RecoveryPolicy()
        if not isinstance(selected_policy, RecoveryPolicy):
            raise TypeError("recovery_policy_required")
        if not callable(supervision_clock) or (
            supervision_sleeper is not None
            and not callable(supervision_sleeper)
        ):
            raise TypeError("supervision_waiter_invalid")
        if type(run_supervision_thread) is not bool:
            raise TypeError("supervision_thread_option_invalid")
        self._deps = dependencies
        self._lock = threading.RLock()
        self._controller: SharingController | None = None
        self._controller_layout: ProfileLayout | None = None
        self._recovery_policy = selected_policy
        self._supervision_clock = supervision_clock
        self._supervision_sleeper = supervision_sleeper
        self._run_supervision_thread = run_supervision_thread
        self._supervision: _SupervisionRuntime | None = None
        self._last_supervision_snapshot: RelaySupervisionSnapshot | None = None
        self._identity_up_invocations = 0

    def status(self) -> SharingServiceStatus:
        """Read bounded status without initializing the profile or starting work."""
        profile = self._prepare_profile(create=False)
        return self._status(profile)

    def diagnostics(self) -> SharingServiceStatus:
        """Return the same safe projection as status; never include raw output."""
        return self.status()

    def supervision_status(self) -> RelaySupervisionSnapshot | None:
        """Return bounded supervisor counters without probing resources."""
        with self._lock:
            runtime = self._supervision
            last_snapshot = self._last_supervision_snapshot
        if runtime is None:
            return last_snapshot
        thread = runtime.thread
        if thread is not None and not thread.is_alive():
            try:
                thread.join(timeout=0)
            except RuntimeError:
                pass
        snapshot = runtime.terminal_snapshot
        if snapshot is None:
            try:
                snapshot = runtime.supervisor.snapshot()
            except Exception:
                snapshot = last_snapshot
        with self._lock:
            if snapshot is not None and self._supervision is runtime:
                self._last_supervision_snapshot = snapshot
        return snapshot

    def tick_supervision(self) -> RelaySupervisionSnapshot | None:
        """Run one explicit tick for deterministic provider-free tests."""
        with self._lock:
            runtime = self._supervision
        if runtime is None or runtime.stop_event.is_set():
            return self.supervision_status()
        try:
            return runtime.supervisor.tick()
        except Exception:
            # RelaySupervisor is designed to bound probe/recovery failures; this
            # final host boundary prevents an unexpected exception escaping.
            return runtime.supervisor.snapshot()

    def initialize_identity(self, *, facilitator_confirmed: bool) -> SharingActionResult:
        """Explicitly initialize the dedicated identity profile exactly once."""
        if facilitator_confirmed is not True:
            profile = self._prepare_profile(create=False)
            return self._result(
                "initialize_identity",
                False,
                "facilitator_confirmation_required",
                profile,
            )

        profile = self._prepare_profile(create=True)
        layout = profile.layout if profile.state == "ready" else None
        if layout is None:
            return self._result("initialize_identity", False, "profile_unavailable", profile)
        if self._identity_initialized(layout):
            return self._result(
                "initialize_identity",
                True,
                "identity_initialized",
                self._prepare_profile(create=False),
                bootstrap_state="already_initialized",
            )

        try:
            resolution = self._deps.resolve_companion()
        except Exception:
            resolution = None
        if not isinstance(resolution, CompanionResolution) or resolution.state != "resolved":
            reason = (
                "unsupported_platform"
                if isinstance(resolution, CompanionResolution)
                and resolution.state == "unsupported_platform"
                else "companion_unavailable"
            )
            return self._result("initialize_identity", False, reason, profile)

        try:
            bootstrap = self._deps.initialize_identity(layout, resolution, True)
        except Exception:
            bootstrap = None
        if not isinstance(bootstrap, BootstrapResult):
            return self._result("initialize_identity", False, "identity_initialization_failed", profile)
        up_invocations = _bootstrap_up_invocations(bootstrap)
        if up_invocations:
            with self._lock:
                self._identity_up_invocations = min(
                    MAX_DIAGNOSTIC_COUNTER,
                    self._identity_up_invocations + up_invocations,
                )

        success = bootstrap.state in {"initialized", "already_initialized"}
        reason = (
            bootstrap.reason
            if bootstrap.reason in _SAFE_BOOTSTRAP_REASONS
            else "identity_initialization_failed"
        )
        return self._result(
            "initialize_identity",
            success,
            reason,
            self._prepare_profile(create=False),
            bootstrap_state=bootstrap.state,
        )

    def start(self) -> SharingActionResult:
        """Start sharing only for a previously initialized dedicated profile."""
        profile = self._prepare_profile(create=False)
        layout = profile.layout if profile.state == "ready" else None
        if layout is None:
            reason = "identity_not_initialized" if profile.state == "absent" else "profile_unavailable"
            return self._result("start", False, reason, profile)
        if not self._identity_initialized(layout):
            return self._result("start", False, "identity_not_initialized", profile)
        controller = self._controller_for(layout)
        if controller is None:
            return self._result("start", False, "controller_unavailable", profile)
        try:
            snapshot = controller.start()
        except Exception:
            return self._result("start", False, "operation_failed", profile)
        if snapshot.state is SharingState.READY and snapshot.reason == "ready":
            if not self._ensure_supervision(controller, snapshot.generation):
                snapshot = controller.status()
        reason = _safe_controller_reason(snapshot.reason)
        return self._result(
            "start",
            snapshot.state is SharingState.READY and reason == "ready",
            reason,
            profile,
        )

    def stop(self) -> SharingActionResult:
        """Stop the current sharing generation and revoke listener sessions."""
        with self._lock:
            runtime = self._cancel_supervision_locked()
            controller = self._controller
            if controller is None:
                snapshot = None
            else:
                try:
                    # The service lock closes the gap between cancelling the
                    # monitor and the controller accepting this serialized stop.
                    snapshot = controller.stop()
                except Exception:
                    snapshot = None
        self._join_supervision(runtime)
        if controller is None:
            return self._result("stop", True, "stopped", self._prepare_profile(create=False))
        if snapshot is None:
            return self._result("stop", False, "operation_failed", self._prepare_profile(create=False))
        reason = _safe_controller_reason(snapshot.reason)
        return self._result(
            "stop",
            snapshot.state is SharingState.OFF and reason in {"stopped", "startup_cancelled"},
            reason,
            self._prepare_profile(create=False),
        )

    def issue_access(self) -> SharingActionResult:
        """Issue one one-time credential for an initialized profile."""
        profile = self._prepare_profile(create=False)
        layout = profile.layout if profile.state == "ready" else None
        if layout is None:
            return self._result("issue_access", False, "profile_unavailable", profile)
        if not self._identity_initialized(layout):
            return self._result("issue_access", False, "identity_not_initialized", profile)
        try:
            credential = self._deps.issue_credential(layout)
        except VerifierStoreError as exc:
            reason = _safe_verifier_reason(exc.reason)
            return self._result("issue_access", False, reason, profile)
        except Exception:
            return self._result("issue_access", False, "credential_store_failed", profile)
        if not isinstance(credential, IssuedCredential):
            return self._result("issue_access", False, "credential_store_failed", profile)
        return self._result(
            "issue_access",
            True,
            "credential_issued",
            self._prepare_profile(create=False),
            credential=credential,
        )

    def rotate_access(self) -> SharingActionResult:
        """Invalidate old access before replacing the stored verifier."""
        profile = self._prepare_profile(create=False)
        layout = profile.layout if profile.state == "ready" else None
        if layout is None:
            return self._result("rotate_access", False, "profile_unavailable", profile)
        if not self._identity_initialized(layout):
            return self._result("rotate_access", False, "identity_not_initialized", profile)
        controller = self._controller_for(layout)
        if controller is None:
            return self._result("rotate_access", False, "controller_unavailable", profile)
        issued: IssuedCredential | None = None

        def rotate_transaction() -> None:
            nonlocal issued
            issued = self._deps.rotate_credential(layout)
            if not isinstance(issued, IssuedCredential):
                issued = None
                raise RuntimeError("credential_rotation_failed")

        with self._lock:
            runtime = self._cancel_supervision_locked()
            try:
                snapshot = controller.rotate(rotate_transaction)
            except Exception:
                snapshot = controller.status()
        self._join_supervision(runtime)
        if snapshot.state is SharingState.READY and snapshot.reason == "ready":
            self._ensure_supervision(controller, snapshot.generation)
        reason = _safe_controller_reason(snapshot.reason)
        return self._result(
            "rotate_access",
            issued is not None,
            "credential_rotated" if issued is not None else reason,
            self._prepare_profile(create=False),
            credential=issued,
        )

    def revoke_access(self) -> SharingActionResult:
        """Revoke verifier access, then stop any remaining owned sharing resources."""
        profile = self._prepare_profile(create=False)
        layout = profile.layout if profile.state == "ready" else None
        if layout is None:
            return self._result("revoke_access", False, "profile_unavailable", profile)

        controller = self._controller_for(layout)
        revoked: VerifierLoad | None = None

        def revoke_transaction() -> None:
            nonlocal revoked
            revoked = self._deps.revoke_access(layout)
            if not isinstance(revoked, VerifierLoad):
                revoked = None
                raise RuntimeError("credential_revocation_failed")

        runtime: _SupervisionRuntime | None = None
        if controller is not None:
            with self._lock:
                runtime = self._cancel_supervision_locked()
                try:
                    controller.rotate(revoke_transaction)
                except Exception:
                    pass
                try:
                    snapshot = controller.stop()
                except Exception:
                    snapshot = controller.status()
        else:
            try:
                revoke_transaction()
            except Exception:
                pass
            snapshot = _initial_snapshot(profile, self._identity_initialized(layout))
        self._join_supervision(runtime)

        verified = revoked is not None and revoked.state == "absent"
        if revoked is None:
            reason = "credential_revocation_failed"
        elif verified:
            reason = "access_revoked"
        else:
            reason = "credential_store_failed"
        status = self._status(self._prepare_profile(create=False), snapshot_override=snapshot)
        return SharingActionResult(
            operation="revoke_access",
            ok=verified,
            reason=reason,
            status=status,
        )

    def copy_invitation(self) -> SharingActionResult:
        """Return only the currently-ready HTTPS player URL to the local caller."""
        profile = self._prepare_profile(create=False)
        layout = profile.layout if profile.state == "ready" else None
        if layout is None or not self._identity_initialized(layout):
            return self._result("copy_invitation", False, "invitation_unavailable", profile)
        controller = self._existing_controller(layout)
        if controller is None:
            return self._result("copy_invitation", False, "invitation_unavailable", profile)
        try:
            origin = controller.invitation()
        except Exception:
            origin = None
        parsed = _parse_public_https_origin(origin)
        safe_origin = parsed[0] if parsed is not None else None
        return self._result(
            "copy_invitation",
            safe_origin is not None,
            "invitation_ready" if safe_origin is not None else "invitation_unavailable",
            self._prepare_profile(create=False),
            invitation=safe_origin,
        )

    def shutdown(self) -> SharingActionResult:
        """Stop host-owned sharing during launcher shutdown without creating state."""
        with self._lock:
            runtime = self._cancel_supervision_locked()
            controller = self._controller
            if controller is None:
                snapshot = None
            else:
                try:
                    snapshot = controller.shutdown()
                except Exception:
                    snapshot = controller.status()
        self._join_supervision(runtime)
        if controller is None:
            return self._result("shutdown", True, "shutting_down", self._prepare_profile(create=False))
        reason = _safe_controller_reason(snapshot.reason)
        return self._result(
            "shutdown",
            snapshot.state is SharingState.OFF and reason == "shutting_down",
            reason,
            self._prepare_profile(create=False),
        )

    def reconcile_startup(self) -> SharingActionResult:
        """Explicitly reconcile only the dedicated profile; never starts sharing."""
        profile = self._prepare_profile(create=False)
        if profile.state == "absent":
            result = ReconcileResult("clean", "profile_absent", True, ())
            return self._result(
                "reconcile_startup",
                True,
                "reconciliation_complete",
                profile,
                reconciliation_state=result.state,
                sharing_available=True,
            )
        layout = profile.layout if profile.state == "ready" else None
        if layout is None:
            return self._result(
                "reconcile_startup",
                False,
                "profile_unavailable",
                profile,
                reconciliation_state="ambiguous",
                sharing_available=False,
            )
        controller = self._controller_for(layout)
        if controller is None:
            return self._result("reconcile_startup", False, "controller_unavailable", profile)
        try:
            result = controller.reconcile_cleanup()
        except Exception:
            result = None
        if not isinstance(result, ReconcileResult):
            return self._result(
                "reconcile_startup",
                False,
                "reconciliation_failed",
                profile,
                reconciliation_state="failed",
                sharing_available=False,
            )
        return self._result(
            "reconcile_startup",
            result.sharing_available,
            "reconciliation_complete" if result.sharing_available else "reconciliation_required",
            self._prepare_profile(create=False),
            reconciliation_state=result.state,
            sharing_available=result.sharing_available,
        )

    def _prepare_profile(self, *, create: bool) -> ProfileState:
        try:
            result = self._deps.prepare_profile(create)
        except Exception:
            return ProfileState("invalid", "profile_state_unavailable")
        return result if isinstance(result, ProfileState) else ProfileState("invalid", "profile_state_unavailable")

    def _identity_initialized(self, layout: ProfileLayout) -> bool:
        try:
            return self._deps.identity_initialized(layout) is True
        except Exception:
            return False

    def _controller_for(self, layout: ProfileLayout) -> SharingController | None:
        with self._lock:
            if self._controller is not None:
                if self._controller_layout == layout:
                    return self._controller
                return None
            try:
                controller = self._deps.controller_factory(layout)
            except Exception:
                return None
            required = ("status", "start", "stop", "shutdown", "rotate", "invitation", "reconcile_cleanup")
            if any(not callable(getattr(controller, method, None)) for method in required):
                return None
            self._controller = controller
            self._controller_layout = layout
            return controller

    def _existing_controller(self, layout: ProfileLayout | None = None) -> SharingController | None:
        with self._lock:
            if self._controller is None:
                return None
            if layout is not None and self._controller_layout != layout:
                return None
            return self._controller

    def _ensure_supervision(
        self, controller: SharingController, generation: int
    ) -> bool:
        """Install exactly one monitor runtime for the current ready lifecycle."""
        monitor_factory = self._deps.relay_monitor_factory
        if monitor_factory is None:
            return True
        try:
            lifecycle_revision = controller.lifecycle_revision
        except Exception:
            return False

        while True:
            stale_runtime: _SupervisionRuntime | None = None
            failed = False
            with self._lock:
                try:
                    current = controller.status()
                    current_revision = controller.lifecycle_revision
                except Exception:
                    return False
                if (
                    current.state is not SharingState.READY
                    or current.generation != generation
                    or current_revision != lifecycle_revision
                ):
                    # A stop/rotation/new generation won the race with start.
                    return True

                existing = self._supervision
                if existing is not None:
                    if (
                        existing.generation == generation
                        and existing.lifecycle_revision == lifecycle_revision
                        and not existing.stop_event.is_set()
                    ):
                        if existing.thread is None or existing.thread.is_alive():
                            return True
                        return self._fail_supervision(
                            controller, generation, lifecycle_revision
                        )
                    stale_runtime = self._cancel_supervision_locked(existing)
                    self._supervision = None
                else:
                    try:
                        monitor = monitor_factory(controller, generation)
                        supervisor = RelaySupervisor(
                            controller,
                            monitor,
                            self._recovery_policy,
                            self._supervision_clock,
                            self._supervision_sleeper,
                        )
                    except Exception:
                        failed = True
                    else:
                        runtime = _SupervisionRuntime(
                            generation=generation,
                            lifecycle_revision=lifecycle_revision,
                            stop_event=threading.Event(),
                            supervisor=supervisor,
                        )
                        if self._run_supervision_thread:
                            runtime.thread = threading.Thread(
                                target=self._run_supervision,
                                args=(runtime, controller),
                                name="player-sharing-supervision-%d" % generation,
                                daemon=True,
                            )
                        self._supervision = runtime
                        if runtime.thread is not None:
                            try:
                                runtime.thread.start()
                            except RuntimeError:
                                self._supervision = None
                                self._last_supervision_snapshot = supervisor.snapshot()
                                failed = True
                        if not failed:
                            return True

            if stale_runtime is not None:
                self._join_supervision(stale_runtime)
                continue
            if failed:
                return self._fail_supervision(
                    controller, generation, lifecycle_revision
                )

    def _run_supervision(
        self, runtime: _SupervisionRuntime, controller: SharingController
    ) -> None:
        """Tick at the bounded policy cadence without holding the service lock."""
        try:
            while not runtime.stop_event.wait(
                self._recovery_policy.health_check_interval
            ):
                if runtime.stop_event.is_set():
                    break
                try:
                    snapshot = runtime.supervisor.tick()
                except Exception:
                    self._fail_controller_supervision(
                        controller,
                        runtime.generation,
                        runtime.lifecycle_revision,
                    )
                    current = runtime.supervisor.snapshot()
                    runtime.terminal_snapshot = RelaySupervisionSnapshot(
                        state="failed",
                        reason="monitor_failed",
                        attempts_used=current.attempts_used,
                        attempts_max=current.attempts_max,
                        next_delay_bucket="none",
                        generation=runtime.generation,
                    )
                    break
                if snapshot.state in {"failed", "stopped"}:
                    break
        except Exception:
            # A daemon worker is a host boundary: no monitor exception escapes.
            self._fail_controller_supervision(
                controller,
                runtime.generation,
                runtime.lifecycle_revision,
            )
            current = runtime.supervisor.snapshot()
            runtime.terminal_snapshot = RelaySupervisionSnapshot(
                state="failed",
                reason="monitor_failed",
                attempts_used=current.attempts_used,
                attempts_max=current.attempts_max,
                next_delay_bucket="none",
                generation=runtime.generation,
            )
        finally:
            runtime.stop_event.set()
            snapshot = runtime.terminal_snapshot
            if snapshot is None:
                try:
                    snapshot = runtime.supervisor.snapshot()
                except Exception:
                    snapshot = None
            with self._lock:
                if snapshot is not None and self._supervision is runtime:
                    self._last_supervision_snapshot = snapshot

    def _cancel_supervision_locked(
        self, runtime: _SupervisionRuntime | None = None
    ) -> _SupervisionRuntime | None:
        """Signal worker cancellation while the service-state lock is held."""
        selected = runtime if runtime is not None else self._supervision
        if selected is None:
            return None
        selected.stop_event.set()
        try:
            current = selected.supervisor.snapshot()
        except Exception:
            current = None
        if current is not None and current.state not in {"failed", "stopped"}:
            try:
                selected.supervisor.stop()
            except Exception:
                pass
        try:
            selected.terminal_snapshot = selected.supervisor.snapshot()
        except Exception:
            pass
        if selected.terminal_snapshot is not None:
            self._last_supervision_snapshot = selected.terminal_snapshot
        return selected

    @staticmethod
    def _join_supervision(runtime: _SupervisionRuntime | None) -> None:
        """Join a cancelled worker outside service/controller locks."""
        if runtime is None or runtime.thread is None:
            return
        if runtime.thread is threading.current_thread():
            return
        try:
            runtime.thread.join(timeout=MAX_SUPERVISION_JOIN_SECONDS)
        except RuntimeError:
            pass

    def _fail_supervision(
        self, controller: SharingController, generation: int, revision: int
    ) -> bool:
        """Fail closed if a ready lifecycle cannot acquire its monitor."""
        self._fail_controller_supervision(controller, generation, revision)
        with self._lock:
            runtime = self._supervision
            attempts_used = 0
            if runtime is not None and runtime.generation == generation:
                runtime.stop_event.set()
                try:
                    attempts_used = runtime.supervisor.snapshot().attempts_used
                except Exception:
                    attempts_used = 0
            failed_snapshot = RelaySupervisionSnapshot(
                state="failed",
                reason="monitor_failed",
                attempts_used=attempts_used,
                attempts_max=self._recovery_policy.max_attempts,
                next_delay_bucket="none",
                generation=generation,
            )
            if runtime is not None and runtime.generation == generation:
                runtime.terminal_snapshot = failed_snapshot
            self._last_supervision_snapshot = failed_snapshot
        return False

    @staticmethod
    def _fail_controller_supervision(
        controller: SharingController, generation: int, revision: int
    ) -> None:
        try:
            current = controller.status()
            state = current.state
            if (
                current.generation != generation
                or controller.lifecycle_revision != revision
                or state not in {SharingState.READY, SharingState.DEGRADED}
            ):
                return
            controller.mark_failed(
                "monitor_failed",
                expected_generation=generation,
                expected_lifecycle_revision=revision,
                expected_state=state,
            )
        except Exception:
            pass

    def _status(
        self,
        profile: ProfileState,
        *,
        snapshot_override: SharingSnapshot | None = None,
    ) -> SharingServiceStatus:
        layout = profile.layout if profile.state == "ready" else None
        initialized = self._identity_initialized(layout) if layout is not None else False
        if layout is None:
            credential = VerifierStatus(
                "unsafe" if profile.state not in {"absent"} else "absent",
                "profile_unavailable" if profile.state != "absent" else "profile_absent",
            )
        else:
            try:
                credential = self._deps.verifier_status(layout)
            except Exception:
                credential = VerifierStatus("unsafe", "verifier_unavailable")
            if not isinstance(credential, VerifierStatus):
                credential = VerifierStatus("unsafe", "verifier_unavailable")

        cached = snapshot_override
        if cached is None:
            controller = self._existing_controller(layout)
            if controller is not None:
                try:
                    candidate = controller.status()
                except Exception:
                    candidate = None
                if isinstance(candidate, SharingSnapshot):
                    cached = candidate

        if cached is None:
            cached = _initial_snapshot(profile, initialized)
        elif layout is None or not initialized:
            cached = SharingSnapshot(
                state=(
                    SharingState.INITIALIZING_REQUIRED
                    if profile.state in {"ready", "absent"}
                    else SharingState.FAILED
                ),
                reason=(
                    "identity_not_initialized"
                    if profile.state in {"ready", "absent"}
                    else "cleanup_ambiguous"
                ),
                generation=cached.generation,
                checks=ReadinessChecks(),
                counters=cached.counters,
            )

        return SharingServiceStatus(
            lifecycle=cached,
            profile_state=profile.state,
            identity_initialized=initialized,
            credential_state=credential.state,
            credential_generation=credential.generation,
            credential_issued_at=credential.issued_at,
            supervision=self.supervision_status(),
            companion_launches=_bounded_service_counter(
                getattr(cached.counters, "companion_launches", 0)
            ),
            identity_up_invocations=self._identity_up_invocations_snapshot(),
        )

    def _identity_up_invocations_snapshot(self) -> int:
        with self._lock:
            return self._identity_up_invocations

    def _result(
        self,
        operation: str,
        ok: bool,
        reason: str,
        profile: ProfileState,
        *,
        bootstrap_state: str | None = None,
        reconciliation_state: str | None = None,
        sharing_available: bool | None = None,
        credential: IssuedCredential | None = None,
        invitation: str | None = None,
    ) -> SharingActionResult:
        return SharingActionResult(
            operation=operation,
            ok=ok,
            reason=reason,
            status=self._status(profile),
            bootstrap_state=bootstrap_state,
            reconciliation_state=reconciliation_state,
            sharing_available=sharing_available,
            credential=credential,
            invitation=invitation,
        )


def create_production_player_sharing_service(
    gateway: PlayerGateway,
    local_runtime_check: Callable[[], bool],
    *,
    companion_manifest: Mapping[str, object] | Callable[[], Mapping[str, object]] | None = None,
    install_root: Path | None = None,
    state_root: Path | None = None,
    state_root_provider: Callable[[], Path] | None = None,
    install_marker: str | None = None,
    profile: str = DEFAULT_PROFILE,
    player_build_root: str | os.PathLike[str] | None = None,
    recovery_policy: RecoveryPolicy | None = None,
    web_port: object = None,
    supervision_clock: Callable[[], float] = time.monotonic,
    supervision_sleeper: CancellableSleeper | None = None,
    run_supervision_thread: bool = True,
) -> PlayerSharingService:
    """Build production seams lazily; construction performs no filesystem or runtime work.

    The pinned runtime manifest is loaded lazily from the install root unless a
    caller explicitly supplies the test/integration injection seam.
    """
    if not callable(local_runtime_check):
        raise TypeError("local_runtime_check_required")
    composition = _ProductionComposition(
        gateway,
        local_runtime_check,
        companion_manifest=companion_manifest,
        install_root=install_root,
        state_root=state_root,
        state_root_provider=state_root_provider,
        install_marker=install_marker,
        profile=profile,
        player_build_root=player_build_root,
    )
    selected_recovery_policy = (
        recovery_policy
        if recovery_policy is not None
        else production_recovery_policy(web_port)
    )
    return PlayerSharingService(
        composition.dependencies(),
        recovery_policy=selected_recovery_policy,
        supervision_clock=supervision_clock,
        supervision_sleeper=supervision_sleeper,
        run_supervision_thread=run_supervision_thread,
    )


class _ProductionComposition:
    """Lazily construct concrete process, listener, and storage dependencies."""

    def __init__(
        self,
        gateway: PlayerGateway,
        local_runtime_check: Callable[[], bool],
        *,
        companion_manifest: Mapping[str, object] | Callable[[], Mapping[str, object]] | None,
        install_root: Path | None,
        state_root: Path | None,
        state_root_provider: Callable[[], Path] | None,
        install_marker: str | None,
        profile: str,
        player_build_root: str | os.PathLike[str] | None,
    ) -> None:
        if not isinstance(profile, str) or _PROFILE_PATTERN.fullmatch(profile) is None:
            raise ValueError("profile_slug_invalid")
        if state_root is not None and state_root_provider is not None:
            raise ValueError("state_root_configuration_ambiguous")
        self._gateway = gateway
        self._local_runtime_check = local_runtime_check
        self._install_root = (
            Path(install_root) if install_root is not None else Path(__file__).resolve().parents[3]
        )
        self._manifest = (
            companion_manifest
            if companion_manifest is not None
            else lambda: load_companion_manifest(self._install_root)
        )
        if state_root_provider is not None:
            if not callable(state_root_provider):
                raise TypeError("state_root_provider_invalid")
            self._state_root_provider = state_root_provider
        elif state_root is not None:
            fixed_state_root = Path(state_root)
            self._state_root_provider = lambda: fixed_state_root
        else:
            self._state_root_provider = default_state_root
        self._install_marker = install_marker or self._marker_for(self._install_root)
        self._profile = profile
        self._player_build_root = player_build_root
        self._lock = threading.RLock()
        self._runner: DefaultCommandRunner | None = None
        self._default_runner: DefaultCommandRunner | None = None
        self._security: PlayerSecurity | None = None
        self._listener: PlayerListener | None = None

    @staticmethod
    def _marker_for(install_root: Path) -> str:
        normalized = Path(os.path.abspath(os.fspath(install_root)))
        digest = hashlib.sha256(os.fsencode(normalized)).hexdigest()[:32]
        return "neq-" + digest

    def dependencies(self) -> SharingServiceDependencies:
        return SharingServiceDependencies(
            prepare_profile=self._prepare_profile,
            identity_initialized=self._identity_initialized,
            verifier_status=verifier_status,
            resolve_companion=self._resolve_companion,
            initialize_identity=self._initialize_identity,
            controller_factory=self._controller_factory,
            issue_credential=issue_credential,
            rotate_credential=self._rotate_access,
            revoke_access=self._revoke_access,
            relay_monitor_factory=self._relay_monitor_factory,
        )

    def _prepare_profile(self, create: bool) -> ProfileState:
        try:
            root = self._state_root_provider()
            return prepare_profile(
                Path(root),
                install_marker=self._install_marker,
                profile=self._profile,
                create=create,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return ProfileState("unsafe_path", "unsafe_state_root")

    def _identity_initialized(self, layout: ProfileLayout) -> bool:
        return _read_marker(layout) == "valid"

    def _resolve_companion(self) -> CompanionResolution:
        manifest = self._manifest
        try:
            selected_manifest = manifest() if callable(manifest) else manifest
        except RuntimeManifestError as exc:
            if exc.reason == "manifest_missing":
                return CompanionResolution("missing_asset", "manifest_missing")
            return CompanionResolution("invalid_manifest", "invalid_manifest")
        except Exception:
            return CompanionResolution("invalid_manifest", "invalid_manifest")
        return resolve_companion(self._install_root, selected_manifest)

    def _initialize_identity(
        self,
        layout: ProfileLayout,
        resolution: CompanionResolution,
        facilitator_confirmed: bool,
    ) -> BootstrapResult:
        if (
            resolution.path is None
            or resolution.expected_sha256 is None
            or not verify_companion_digest(resolution.path, resolution.expected_sha256)
        ):
            return BootstrapResult("refused", "companion_digest_mismatch")
        runner = self._command_runner()
        with self._lock:
            observer_runner = (
                self._runner if self._runner is not self._default_runner else None
            )
        # TABLETOP MODE: Keep launchctl census on the observer's platform-sized runner.
        observer = DefaultIdentityObserver(
            layout,
            resolution.path,
            **({"command_runner": observer_runner} if observer_runner is not None else {}),
        )
        return bootstrap_identity(
            layout,
            resolution,
            runner=runner,
            observer=observer,
            facilitator_confirmed=facilitator_confirmed,
        )

    def _controller_factory(self, layout: ProfileLayout) -> SharingController:
        security = self._get_security(layout)
        binder = PublicOriginBinder(security)
        route_table = _ProfileRouteTable(layout)
        cleanup = CleanupDependencies(
            layout=layout,
            process_table=lambda pid: _production_process_table(pid, layout),
            route_table=route_table,
        )

        def start_player_listener() -> bool:
            try:
                validate_tunnel_target(PLAYER_HOST, PLAYER_PORT)
                listener = self._get_listener(layout)
                listener.start(host=PLAYER_HOST, port=PLAYER_PORT)
                return listener.is_running
            except Exception:
                return False

        def stop_player_listener() -> None:
            with self._lock:
                listener = self._listener
            if listener is not None:
                listener.stop()
            elif self._security is not None:
                self._security.stop_listener()

        def start_companion(generation: int) -> OwnedCompanion | None:
            resolution = self._resolve_companion()
            if (
                resolution.state != "resolved"
                or resolution.path is None
                or resolution.expected_sha256 is None
                or not verify_companion_digest(
                    resolution.path, resolution.expected_sha256
                )
                or not route_table.ensure()
            ):
                return None

            handle_holder: dict[str, OwnedCompanion] = {}

            def readiness_probe() -> str:
                handle = handle_holder.get("handle")
                if handle is None:
                    return "pending"
                return (
                    "ready"
                    if self._route_status(handle, generation, layout).healthy
                    else "pending"
                )

            try:
                handle = OwnedCompanion(
                    resolution,
                    layout,
                    readiness_probe,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return None
            handle_holder["handle"] = handle
            return handle

        def route_status(handle: object, generation: int) -> RouteStatus:
            if not isinstance(handle, OwnedCompanion):
                return RouteStatus(False, None, generation)
            return self._route_status(handle, generation, layout)

        dependencies = SharingDependencies(
            local_runtime_ok=lambda: _strict_bool(self._local_runtime_check),
            assets_ok=lambda: self._assets_ok(),
            start_player_listener=start_player_listener,
            stop_player_listener=stop_player_listener,
            listener_authenticated_probe=lambda: self._listener_authenticated_probe(),
            load_verifier=lambda: load_verifier(layout),
            resolve_companion=self._resolve_companion,
            identity_initialized=lambda: self._identity_initialized(layout),
            start_companion=start_companion,
            route_status=route_status,
            origin_binder=binder,
            companion_start_deadline_seconds=MAX_COMPANION_START_DEADLINE_SECONDS,
            route_wait_seconds=MAX_ROUTE_WAIT_SECONDS,
            route_poll_interval_seconds=min(0.25, MAX_ROUTE_POLL_INTERVAL_SECONDS),
            cleanup=cleanup,
        )
        return SharingController(dependencies)

    def _relay_monitor_factory(
        self, controller: SharingController, generation: int
    ) -> RelayMonitor:
        """Compose production probes without exposing route-origin values."""
        def listener_probe(active_generation: int) -> bool:
            if active_generation != generation:
                return False
            before = controller.status()
            if (
                before.generation != generation
                or before.state not in {SharingState.READY, SharingState.DEGRADED}
            ):
                return False
            healthy = self._listener_authenticated_probe()
            after = controller.status()
            return bool(
                healthy is True
                and after.generation == generation
                and after.state in {SharingState.READY, SharingState.DEGRADED}
            )

        return ProductionRelayMonitor(controller, listener_probe)

    def _get_security(self, layout: ProfileLayout) -> PlayerSecurity:
        with self._lock:
            if self._security is None:
                self._security = PlayerSecurity(
                    verifier_provider=lambda: _raw_verifier(layout)
                )
            return self._security

    def _get_listener(self, layout: ProfileLayout) -> PlayerListener:
        with self._lock:
            if self._listener is None:
                self._listener = PlayerListener(
                    gateway=self._gateway,
                    security=self._get_security(layout),
                    build_root=self._player_build_root,
                )
            return self._listener

    def _command_runner(self) -> DefaultCommandRunner:
        with self._lock:
            if self._runner is None:
                self._default_runner = DefaultCommandRunner()
                self._runner = self._default_runner
            return self._runner

    def _assets_ok(self) -> bool:
        try:
            load_player_client_assets(self._player_build_root)
        except PlayerClientAssetsError:
            return False
        return True

    def _listener_authenticated_probe(self) -> bool:
        with self._lock:
            listener = self._listener
        if listener is None or not listener.is_running:
            return False
        connection: http.client.HTTPConnection | None = None
        try:
            validate_tunnel_target(PLAYER_HOST, PLAYER_PORT)
            connection = http.client.HTTPConnection(
                PLAYER_HOST,
                PLAYER_PORT,
                timeout=LOOPBACK_PROBE_TIMEOUT_SECONDS,
            )
            connection.request(
                "GET",
                "/",
                headers={"Host": "%s:%d" % (PLAYER_HOST, PLAYER_PORT)},
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "")
            response.read(1024)
            return response.status == 200 and content_type.split(";", 1)[0].strip().lower() == "text/html"
        except (OSError, http.client.HTTPException, ValueError):
            return False
        finally:
            if connection is not None:
                connection.close()

    def _route_status(
        self,
        handle: OwnedCompanion,
        generation: int,
        layout: ProfileLayout,
    ) -> RouteStatus:
        try:
            if handle.state != "running" or handle.profile_layout != layout:
                return RouteStatus(False, None, generation)
            path = handle.executable_path
            result = self._command_runner()(
                (str(path), "status", "--profile", layout.profile),
                companion_environment(layout),
                MAX_STATUS_COMMAND_SECONDS,
            )
        except Exception:
            return RouteStatus(False, None, generation)
        if (
            not isinstance(result, RunResult)
            or result.returncode != 0
            or result.timed_out
            or result.output_truncated
        ):
            return RouteStatus(False, None, generation)
        origin = _parse_companion_status(result.bounded_output, layout.profile)
        return RouteStatus(origin is not None, origin, generation)

    def _rotate_access(self, layout: ProfileLayout) -> IssuedCredential:
        with self._lock:
            listener = self._listener
            security = self._security
        was_running = bool(listener is not None and listener.is_running)

        def invalidate() -> None:
            if listener is not None and listener.is_running:
                listener.stop()
            elif security is not None:
                security.stop_listener()

        try:
            issued = rotate_credential(layout, invalidate)
        except Exception:
            if was_running and listener is not None:
                try:
                    validate_tunnel_target(PLAYER_HOST, PLAYER_PORT)
                    listener.start(host=PLAYER_HOST, port=PLAYER_PORT)
                except Exception:
                    pass
            raise
        if was_running and listener is not None:
            try:
                validate_tunnel_target(PLAYER_HOST, PLAYER_PORT)
                listener.start(host=PLAYER_HOST, port=PLAYER_PORT)
            except Exception:
                # The verifier has rotated and old sessions are invalid. The
                # controller's fresh readiness pass will keep the origin clear.
                pass
        return issued

    def _revoke_access(self, layout: ProfileLayout) -> VerifierLoad:
        with self._lock:
            listener = self._listener
            security = self._security

        def invalidate() -> None:
            if listener is not None and listener.is_running:
                listener.stop()
            elif security is not None:
                security.stop_listener()

        return revoke_access(layout, invalidate)


class _ProfileRouteTable:
    """Exact dedicated-profile TOML route ownership and removal."""

    def __init__(self, layout: ProfileLayout) -> None:
        self._layout = layout
        self._directory = layout.config_home / "opentunnel"
        self._filename = layout.profile + ".toml"
        target = validate_tunnel_target(PLAYER_HOST, PLAYER_PORT)
        self._payload = (
            '[routes]\n"%s" = "%s"\n' % (layout.profile, target)
        ).encode("ascii")

    def ensure(self) -> bool:
        if not self._layout_is_private():
            return False
        try:
            self._directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError:
            return False
        if not self._private_directory(self._directory):
            return False
        current = self._read()
        if current == "owned":
            return True
        if current != "absent":
            return False

        descriptor = -1
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(self._directory / self._filename, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            if not self._private_file_metadata(metadata):
                return False
            _write_all(descriptor, self._payload)
            os.fsync(descriptor)
        except FileExistsError:
            return self._read() == "owned"
        except OSError:
            return False
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        return self._read() == "owned"

    def lookup(self, profile: str, route_id: str | None) -> RouteObservation:
        if profile != self._layout.profile or (
            route_id is not None and route_id != self._layout.profile
        ):
            return RouteObservation("foreign", profile, route_id)
        state = self._read()
        if state == "absent":
            return RouteObservation("absent", profile)
        if state == "owned":
            return RouteObservation("owned", profile, self._layout.profile)
        if state == "foreign":
            return RouteObservation("foreign", profile, route_id)
        return RouteObservation("unknown")

    def remove(self, profile: str, route_id: str) -> bool:
        if profile != self._layout.profile or route_id != self._layout.profile:
            return False
        if self._read() == "absent":
            return True
        if self._read() != "owned" or not self._private_directory(self._directory):
            return False
        directory_fd = -1
        file_fd = -1
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            directory_fd = os.open(self._directory, flags)
            file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            file_flags |= getattr(os, "O_CLOEXEC", 0)
            file_fd = os.open(self._filename, file_flags, dir_fd=directory_fd)
            before = os.fstat(file_fd)
            if not self._private_file_metadata(before):
                return False
            content = os.read(file_fd, MAX_PROFILE_ROUTE_BYTES + 1)
            if content != self._payload:
                return False
            current = os.stat(self._filename, dir_fd=directory_fd, follow_symlinks=False)
            if not _same_file(before, current):
                return False
            os.unlink(self._filename, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError:
            return False
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            if directory_fd >= 0:
                os.close(directory_fd)
        return self._read() == "absent"

    def _read(self) -> str:
        if not self._layout_is_private():
            return "unknown"
        try:
            directory_metadata = os.lstat(self._directory)
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "unknown"
        if (
            stat.S_ISLNK(directory_metadata.st_mode)
            or not self._private_directory_metadata(directory_metadata)
        ):
            return "foreign"
        path = self._directory / self._filename
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "unknown"
        if stat.S_ISLNK(metadata.st_mode) or not self._private_file_metadata(metadata):
            return "foreign"
        descriptor = -1
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if not _same_file(metadata, opened) or not self._private_file_metadata(opened):
                return "unknown"
            content = os.read(descriptor, MAX_PROFILE_ROUTE_BYTES + 1)
            if len(content) > MAX_PROFILE_ROUTE_BYTES:
                return "foreign"
            return "owned" if content == self._payload else "foreign"
        except OSError:
            return "unknown"
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _layout_is_private(self) -> bool:
        try:
            metadata = os.lstat(self._layout.config_home)
            resolved = self._layout.config_home.resolve(strict=True)
            profile_root = self._layout.profile_root.resolve(strict=True)
            resolved.relative_to(profile_root)
        except (OSError, RuntimeError, ValueError):
            return False
        return (
            not stat.S_ISLNK(metadata.st_mode)
            and self._private_directory_metadata(metadata)
        )

    def _private_directory(self, path: Path) -> bool:
        try:
            metadata = os.lstat(path)
        except OSError:
            return False
        return not stat.S_ISLNK(metadata.st_mode) and self._private_directory_metadata(metadata)

    @staticmethod
    def _private_directory_metadata(metadata: os.stat_result) -> bool:
        try:
            uid = os.getuid()
        except (AttributeError, OSError):
            return False
        return bool(
            stat.S_ISDIR(metadata.st_mode)
            and metadata.st_uid == uid
            and stat.S_IMODE(metadata.st_mode) == 0o700
        )

    @staticmethod
    def _private_file_metadata(metadata: os.stat_result) -> bool:
        try:
            uid = os.getuid()
        except (AttributeError, OSError):
            return False
        return bool(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == uid
            and stat.S_IMODE(metadata.st_mode) == 0o600
            and metadata.st_size <= MAX_PROFILE_ROUTE_BYTES
        )


def _parse_companion_status(output: str, profile: str) -> str | None:
    """Accept only a connected status with this profile's exact loopback route."""
    if (
        not isinstance(output, str)
        or len(output) > 64 * 1024
        or not isinstance(profile, str)
        or _PROFILE_PATTERN.fullmatch(profile) is None
    ):
        return None
    hostnames = _HOSTNAME_LINE_PATTERN.findall(output)
    services = _SERVICE_LINE_PATTERN.findall(output)
    if len(hostnames) != 1 or len(services) != 1:
        return None
    hostname = hostnames[0].casefold()
    if not hostname.endswith(".opentunnel.xyz"):
        return None
    if not services[0].casefold().startswith("connected"):
        return None
    route_lines: list[tuple[str, str]] = []
    for line in output.splitlines():
        if "->" not in line and "\u2192" not in line:
            continue
        match = _ROUTE_LINE_PATTERN.fullmatch(line)
        if match is None:
            return None
        route_lines.append((match.group(1), match.group(2)))
    if len(route_lines) != 1:
        return None
    route_host, target = route_lines[0]
    try:
        expected_target = validate_tunnel_target(PLAYER_HOST, PLAYER_PORT)
    except ValueError:
        return None
    if (
        route_host.casefold() != (profile + "." + hostname).casefold()
        or target != expected_target
    ):
        return None
    origin = "https://" + route_host.casefold()
    parsed = _parse_public_https_origin(origin)
    if parsed is None:
        return None
    return parsed[0]


def _raw_verifier(layout: ProfileLayout) -> str | None:
    try:
        loaded = load_verifier(layout)
    except Exception:
        return None
    return loaded.raw_verifier if loaded.state == "present" else None


def _strict_bool(callback: Callable[[], bool]) -> bool:
    try:
        return callback() is True
    except Exception:
        return False


def _production_process_table(
    pid: int,
    layout: ProfileLayout,
) -> ProcessIdentity | ProcessObservation | None:
    if type(pid) is not int or pid <= 0:
        return None
    identity = probe_process_identity(pid)
    if identity is None:
        return ProcessObservation("gone" if _process_is_gone(pid) else "unknown")
    if type(identity.uid) is not int:
        return None
    profile_marker = _process_profile_marker(identity, layout)
    return ProcessIdentity(
        pid=identity.pid,
        creation_token=identity.creation_token,
        exe_path=identity.executable_path,
        uid=identity.uid,
        profile_marker=profile_marker,
        legacy_creation_token=identity.legacy_creation_token,
    )


def _process_is_gone(pid: int) -> bool:
    if platform.system() == "Linux":
        try:
            os.stat(Path("/proc") / str(pid))
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False


def _process_uid(pid: int) -> int | None:
    try:
        info = process_info.lookup(pid)
    except (OSError, RuntimeError, TypeError, ValueError, OverflowError):
        return None
    return info.uid if info is not None else None


def _process_profile_marker(identity: Identity, layout: ProfileLayout) -> str | None:
    expected_argv = (
        identity.executable_path,
        "serve",
        "--profile",
        layout.profile,
    )
    if identity.environment:
        observed_environment = dict(identity.environment)
        if (
            len(observed_environment) == len(identity.environment)
            and observed_environment == companion_environment(layout)
            and identity.argv == expected_argv
        ):
            return layout.profile
        return None
    if identity.command_line == " ".join(expected_argv):
        return layout.profile
    return None


def _initial_snapshot(profile: ProfileState, initialized: bool) -> SharingSnapshot:
    if profile.state not in {"ready", "absent"}:
        return SharingSnapshot(
            SharingState.FAILED,
            "cleanup_ambiguous",
            0,
            ReadinessChecks(),
            SharingCounters(),
        )
    if not initialized:
        return SharingSnapshot(
            SharingState.INITIALIZING_REQUIRED,
            "identity_not_initialized",
            0,
            ReadinessChecks(),
            SharingCounters(),
        )
    return SharingSnapshot(
        SharingState.OFF,
        "off",
        0,
        ReadinessChecks(),
        SharingCounters(),
    )


def _safe_controller_reason(value: object) -> str:
    return value if isinstance(value, str) and value in _SAFE_CONTROLLER_REASONS else "operation_failed"


def _bootstrap_up_invocations(result: BootstrapResult) -> int:
    """Count only bounded bootstrap command facts for actual ``up`` calls."""
    facts = result.facts
    if not isinstance(facts, tuple):
        return 0
    return sum(
        isinstance(fact, str) and fact.startswith("up=")
        for fact in facts[:MAX_RESULT_FACTS]
    )


def _bounded_service_counter(value: object) -> int:
    if type(value) is not int:
        return 0
    return min(max(value, 0), MAX_DIAGNOSTIC_COUNTER)


def _safe_verifier_reason(value: object) -> str:
    if value in {"already_configured", "verifier_present", "credential_already_configured"}:
        return "credential_already_configured"
    if value in {"absent", "verifier_absent"}:
        return "credential_not_configured"
    if value in {"unsafe", "invalid", "verifier_invalid", "verifier_directory_unsafe"}:
        return "credential_store_invalid"
    return "credential_store_failed"


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short_write")
        view = view[written:]


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino
