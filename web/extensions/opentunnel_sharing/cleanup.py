# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Private owner records and fail-closed OpenTunnel cleanup.

Launcher startup calls :func:`reconcile_orphans` explicitly. Reconciliation
never starts sharing. An ambiguous result remains unavailable in the owning
controller until a facilitator manually resolves the resource and explicitly
reruns reconciliation; ``clear_ambiguity`` is only that guarded rerun.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol

from web.extensions.opentunnel_sharing.companion import CompanionResolution
from web.extensions.opentunnel_sharing.profile_state import ProfileLayout

OWNER_RECORD_SCHEMA = "neq.opentunnel.owned_process.v1"
OWNER_RECORD_FILENAME = "owned_process.json"
MAX_OWNER_RECORD_BYTES = 4096
MAX_PROCESS_ID = (1 << 31) - 1
MAX_CLEANUP_WAIT_SECONDS = 30.0
DEFAULT_TERM_WAIT_SECONDS = 2.0
DEFAULT_KILL_WAIT_SECONDS = 2.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.05

OwnerRecordState = Literal["absent", "valid", "ambiguous"]
ReconcileState = Literal[
    "clean", "reconciled", "stale_record_cleared", "ambiguous", "failed"
]
CleanupState = Literal["clean", "ambiguous", "failed"]
ProcessState = Literal["gone", "unknown"]
RouteState = Literal["owned", "absent", "unknown", "foreign"]

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?\Z")
_TOKEN_RE = re.compile(r"[A-Za-z0-9 .,_:+-]{1,128}\Z")
_ROUTE_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_ASSET_STEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z\Z"
)


# TABLETOP MODE: Persisted creation tokens stay opaque and are re-derived live.
@dataclass(frozen=True, slots=True, repr=False)
class OwnedProcessRecord:
    """The minimum private identity needed to recognize one NEQ child.

    Creation tokens are opaque and re-derived by the native process observer.
    Legacy tokens remain readable and are accepted only when that observer
    independently derives the same prior-format token for the live process.
    """

    profile: str
    uid: int
    pid: int
    creation_token: str
    exe_path: str
    started_at: str
    generation: int
    route_id: str | None = None

    def __repr__(self) -> str:
        return "OwnedProcessRecord(profile=%r, uid=%r, generation=%r)" % (
            self.profile,
            self.uid,
            self.generation,
        )


@dataclass(frozen=True, slots=True, repr=False)
class OwnerRecordLoad:
    state: OwnerRecordState
    reason: str
    record: OwnedProcessRecord | None = None

    def __repr__(self) -> str:
        return "OwnerRecordLoad(state=%r, reason=%r)" % (self.state, self.reason)


@dataclass(frozen=True, slots=True, repr=False)
class ProcessIdentity:
    """Positive process-table facts; raw identity is never diagnostic output."""

    pid: int
    creation_token: str
    exe_path: str
    uid: int
    profile_marker: str | None
    legacy_creation_token: str | None = None

    def __repr__(self) -> str:
        return "ProcessIdentity(pid=%r, uid=%r, profile_proven=%r)" % (
            self.pid,
            self.uid,
            self.profile_marker is not None,
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProcessObservation:
    """Explicitly distinguish a confirmed absent PID from unknown evidence."""

    state: ProcessState

    def __repr__(self) -> str:
        return "ProcessObservation(state=%r)" % self.state


@dataclass(frozen=True, slots=True, repr=False)
class RouteObservation:
    """One route table result for the dedicated profile only."""

    state: RouteState
    profile: str | None = None
    route_id: str | None = None

    def __repr__(self) -> str:
        return "RouteObservation(state=%r, profile_proven=%r)" % (
            self.state,
            self.profile is not None,
        )


class ProcessTable(Protocol):
    def __call__(self, pid: int) -> ProcessIdentity | ProcessObservation | None: ...


class RouteTable(Protocol):
    """A profile-scoped route observer/remover; implementations must not scan siblings."""

    def lookup(self, profile: str, route_id: str | None) -> RouteObservation: ...

    def remove(self, profile: str, route_id: str) -> bool: ...


class Signaller(Protocol):
    def __call__(self, pid: int, signal_number: int) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class CleanupDependencies:
    """Injected, profile-scoped seams used by the controller and host startup."""

    layout: ProfileLayout
    process_table: ProcessTable
    route_table: RouteTable
    signaller: Signaller | None = None
    term_wait_seconds: float = DEFAULT_TERM_WAIT_SECONDS
    kill_wait_seconds: float = DEFAULT_KILL_WAIT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep

    def __repr__(self) -> str:
        return "CleanupDependencies(<injected>)"

    def __post_init__(self) -> None:
        if not isinstance(self.layout, ProfileLayout):
            raise TypeError("cleanup_layout_required")
        if not callable(self.process_table):
            raise TypeError("cleanup_process_table_required")
        if not callable(getattr(self.route_table, "lookup", None)) or not callable(
            getattr(self.route_table, "remove", None)
        ):
            raise TypeError("cleanup_route_table_required")
        if self.signaller is not None and not callable(self.signaller):
            raise TypeError("cleanup_signaller_invalid")
        if not callable(self.clock) or not callable(self.sleeper):
            raise TypeError("cleanup_waiter_invalid")
        if not _valid_deadline(self.term_wait_seconds):
            raise ValueError("cleanup_term_deadline_invalid")
        if not _valid_deadline(self.kill_wait_seconds):
            raise ValueError("cleanup_kill_deadline_invalid")
        if not _valid_deadline(self.poll_interval_seconds):
            raise ValueError("cleanup_poll_interval_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class ReconcileResult:
    state: ReconcileState
    reason: str
    sharing_available: bool
    facts: tuple[str, ...] = ()
    diagnostic: str = ""

    def __repr__(self) -> str:
        return "ReconcileResult(state=%r, reason=%r, sharing_available=%r, facts=%r)" % (
            self.state,
            self.reason,
            self.sharing_available,
            self.facts,
        )


@dataclass(frozen=True, slots=True, repr=False)
class CleanupResult:
    state: CleanupState
    reason: str
    process_reaped: bool
    route_removed: bool
    record_cleared: bool
    listener_stopped: bool
    facts: tuple[str, ...] = ()

    @property
    def sharing_available(self) -> bool:
        return self.state == "clean"

    def __repr__(self) -> str:
        return "CleanupResult(state=%r, reason=%r, facts=%r)" % (
            self.state,
            self.reason,
            self.facts,
        )


def owner_record_from_handle(
    layout: ProfileLayout,
    handle: object,
    generation: int,
    *,
    route_id: str | None = None,
) -> OwnedProcessRecord | None:
    """Snapshot the supervisor's positively verified live-child identity.

    ``OwnedCompanion`` currently keeps these values private because they are
    process-control internals. This adapter reads only those fixed fields and
    refuses handles that do not expose the same live identity contract.
    """
    if not _layout_is_private(layout):
        return None
    try:
        pid = getattr(handle, "_pid")
        creation_token = getattr(handle, "_identity_token")
        executable = getattr(handle, "_binary_path")
        handle_layout = getattr(handle, "_layout")
        state = getattr(handle, "state")
        reaped = getattr(handle, "reaped")
        uid = os.getuid()
        exe_path = str(Path(executable).resolve(strict=True))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    if (
        state != "running"
        or reaped is not False
        or handle_layout != layout
        or not _valid_pid(pid)
        or not isinstance(creation_token, str)
        or _TOKEN_RE.fullmatch(creation_token) is None
        or not _valid_companion_path(exe_path, require_exists=True)
        or type(generation) is not int
        or generation < 1
        or (route_id is not None and not _valid_route_id(route_id))
    ):
        return None
    record = OwnedProcessRecord(
        profile=layout.profile,
        uid=uid,
        pid=pid,
        creation_token=creation_token,
        exe_path=exe_path,
        started_at=_utc_now(),
        generation=generation,
        route_id=route_id,
    )
    return record if _valid_record(record, layout) else None


def load_owner_record(layout: ProfileLayout) -> OwnerRecordLoad:
    """Load one bounded, private owner record without following links."""
    state, reason, record, _metadata = _read_owner_record(layout)
    return OwnerRecordLoad(state, reason, record)


def write_owner_record(layout: ProfileLayout, record: OwnedProcessRecord) -> bool:
    """Create a 0600 owner record atomically; never overwrite invalid state."""
    if not _valid_record(record, layout):
        return False
    existing = load_owner_record(layout)
    if existing.state == "valid":
        return existing.record == record
    if existing.state != "absent":
        return False

    descriptor = _open_state_directory(layout)
    if descriptor is None:
        return False
    temporary_name = ".owned_process.%s.tmp" % secrets.token_hex(8)
    file_descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        file_descriptor = os.open(
            temporary_name, flags, 0o600, dir_fd=descriptor
        )
        os.fchmod(file_descriptor, 0o600)
        payload = _serialize_record(record)
        _write_all(file_descriptor, payload)
        os.fsync(file_descriptor)
        metadata = os.fstat(file_descriptor)
        if not _is_private_regular_file(metadata, os.getuid()):
            return False
        os.close(file_descriptor)
        file_descriptor = -1
        # link() is create-only: a raced-in record, link, or foreign file wins.
        os.link(
            temporary_name,
            OWNER_RECORD_FILENAME,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=descriptor)
        temporary_name = ""
        os.fsync(descriptor)
    except (FileExistsError, OSError, TypeError, ValueError):
        return False
    finally:
        if file_descriptor >= 0:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=descriptor)
            except (OSError, TypeError, ValueError):
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass
    loaded = load_owner_record(layout)
    return loaded.state == "valid" and loaded.record == record


def clear_owner_record(
    layout: ProfileLayout,
    expected_record: OwnedProcessRecord | None = None,
) -> bool:
    """Unlink only a valid matching owner record; invalid/foreign files persist."""
    state, _reason, record, record_metadata = _read_owner_record(layout)
    if state == "absent":
        return True
    if state != "valid" or record is None or record_metadata is None:
        return False
    if expected_record is not None and record != expected_record:
        return False
    descriptor = _open_state_directory(layout)
    if descriptor is None:
        return False
    try:
        try:
            current = os.stat(
                OWNER_RECORD_FILENAME,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
        except OSError:
            return False
        if not _same_file(current, record_metadata) or not _is_private_regular_file(
            current, os.getuid()
        ):
            return False
        # Re-read through the opened inode before unlinking the direct entry.
        opened_state, _opened_reason, opened_record, opened_metadata = (
            _read_owner_record(layout)
        )
        if (
            opened_state != "valid"
            or opened_record != record
            or opened_metadata is None
            or not _same_file(opened_metadata, record_metadata)
        ):
            return False
        os.unlink(OWNER_RECORD_FILENAME, dir_fd=descriptor)
        os.fsync(descriptor)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def reconcile_orphans(
    layout: ProfileLayout,
    resolution: CompanionResolution,
    *,
    process_table: ProcessTable,
    route_table: RouteTable,
    signaller: Signaller | None = None,
    term_wait_seconds: float = DEFAULT_TERM_WAIT_SECONDS,
    kill_wait_seconds: float = DEFAULT_KILL_WAIT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    expected_pid: int | None = None,
) -> ReconcileResult:
    """Reap only a positively identified orphan in the dedicated NEQ profile.

    The process identity and the profile-scoped route observation are checked
    before any signal. The process identity is checked again immediately before
    SIGTERM and SIGKILL. ``None`` from ``process_table`` means unknown, never
    gone; a confirmed absent PID must be represented by ``ProcessObservation``.
    """
    if not _layout_is_private(layout):
        return _reconcile_result("ambiguous", "profile_state_ambiguous")
    if not callable(process_table) or not _valid_route_table(route_table):
        return _reconcile_result("ambiguous", "cleanup_adapter_invalid")
    if signaller is not None and not callable(signaller):
        return _reconcile_result("ambiguous", "cleanup_adapter_invalid")
    if not callable(clock) or not callable(sleeper):
        return _reconcile_result("ambiguous", "cleanup_adapter_invalid")
    if not all(
        _valid_deadline(value)
        for value in (term_wait_seconds, kill_wait_seconds, poll_interval_seconds)
    ):
        return _reconcile_result("ambiguous", "cleanup_deadline_invalid")

    loaded = load_owner_record(layout)
    if loaded.state == "ambiguous":
        return _reconcile_result("ambiguous", "owner_record_ambiguous")
    if loaded.state == "absent":
        if expected_pid is not None:
            if not _valid_pid(expected_pid):
                return _reconcile_result("ambiguous", "process_identity_unknown")
            process_state, _identity = _read_process(process_table, expected_pid)
            if process_state != "gone":
                return _reconcile_result("ambiguous", "process_remains_unverified")
        route_state, _route_id = _lookup_route(route_table, layout.profile, None)
        if route_state == "absent":
            return _reconcile_result("clean", "no_owned_resources")
        return _reconcile_result("ambiguous", "route_without_owner_record")

    record = loaded.record
    if record is None:
        return _reconcile_result("ambiguous", "owner_record_ambiguous")
    process_state, identity = _read_process(process_table, record.pid)
    if process_state == "unknown":
        return _reconcile_result("ambiguous", "process_identity_unknown")
    if process_state == "present" and identity is not None:
        identity_match = _identity_matches_record(identity, record, layout)
        if identity_match != "match":
            return _reconcile_result("ambiguous", identity_match)
        if (
            not isinstance(resolution, CompanionResolution)
            or resolution.state != "resolved"
            or resolution.path is None
        ):
            return _reconcile_result("ambiguous", "companion_resolution_unknown")
        try:
            resolved_executable = str(Path(resolution.path).resolve(strict=True))
        except (OSError, RuntimeError, TypeError, ValueError):
            return _reconcile_result("ambiguous", "companion_resolution_unknown")
        if resolved_executable != record.exe_path:
            return _reconcile_result("ambiguous", "companion_identity_mismatch")

    route_state, route_id = _lookup_route(
        route_table, layout.profile, record.route_id
    )
    if route_state not in {"absent", "owned"}:
        return _reconcile_result("ambiguous", "route_ownership_unknown")

    facts: list[str] = []
    if process_state == "gone":
        if not _remove_or_confirm_absent(
            route_table,
            layout.profile,
            route_state,
            route_id,
            record.route_id,
        ):
            return _reconcile_result("ambiguous", "route_ownership_unknown")
        if not clear_owner_record(layout, record):
            return _reconcile_result("ambiguous", "owner_record_clear_failed")
        return _reconcile_result(
            "stale_record_cleared", "stale_record_cleared", ("process_gone=true",)
        )

    assert identity is not None
    process_result = _stop_verified_orphan(
        record,
        layout,
        process_table,
        signaller,
        term_wait_seconds=term_wait_seconds,
        kill_wait_seconds=kill_wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
        clock=clock,
        sleeper=sleeper,
    )
    if process_result != "gone":
        return _reconcile_result("ambiguous", process_result)
    facts.append("process_reaped=true")
    if not _remove_or_confirm_absent(
        route_table,
        layout.profile,
        route_state,
        route_id,
        record.route_id,
    ):
        return _reconcile_result("ambiguous", "route_ownership_unknown")
    facts.append("route_absent=true")
    if not clear_owner_record(layout, record):
        return _reconcile_result("ambiguous", "owner_record_clear_failed")
    facts.append("owner_record_cleared=true")
    return _reconcile_result("reconciled", "owned_orphan_reconciled", tuple(facts))


def clear_ambiguity(
    layout: ProfileLayout,
    resolution: CompanionResolution,
    *,
    facilitator_acknowledged: bool,
    process_table: ProcessTable,
    route_table: RouteTable,
    signaller: Signaller | None = None,
    term_wait_seconds: float = DEFAULT_TERM_WAIT_SECONDS,
    kill_wait_seconds: float = DEFAULT_KILL_WAIT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    expected_pid: int | None = None,
) -> ReconcileResult:
    """Clear controller ambiguity only by acknowledged fresh reconciliation."""
    if facilitator_acknowledged is not True:
        return _reconcile_result("ambiguous", "facilitator_acknowledgement_required")
    return reconcile_orphans(
        layout,
        resolution,
        process_table=process_table,
        route_table=route_table,
        signaller=signaller,
        term_wait_seconds=term_wait_seconds,
        kill_wait_seconds=kill_wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
        clock=clock,
        sleeper=sleeper,
        expected_pid=expected_pid,
    )


def cleanup_owned(
    layout: ProfileLayout,
    *,
    handle: object | None,
    route_table: RouteTable,
    stop_listener: Callable[[], None],
    deadline_seconds: float,
) -> CleanupResult:
    """Stop one in-memory owned child and unwind only its proven profile route.

    The player listener callback is always attempted, including when process or
    route ownership is ambiguous, so active player sessions are revoked.
    """
    facts: list[str] = []
    record_state, _reason, record, _metadata = _read_owner_record(layout)
    ambiguous = record_state == "ambiguous"
    failed = False
    process_reaped = handle is None
    route_removed = False
    record_cleared = record_state == "absent"
    listener_stopped = False
    route_state: RouteState = "unknown"
    route_id: str | None = None
    if not _valid_deadline(deadline_seconds) or not _valid_route_table(route_table):
        ambiguous = True

    if not ambiguous and handle is not None:
        if record_state == "valid" and record is not None:
            if not _handle_matches_record(handle, record, layout):
                ambiguous = True
        elif record_state != "absent":
            ambiguous = True
        if not ambiguous:
            route_state, route_id = _lookup_route(
                route_table,
                layout.profile,
                record.route_id if record is not None else None,
            )
            if route_state not in {"absent", "owned"}:
                ambiguous = True
            elif route_state == "owned" and record is None:
                # The live handle proves the process, but without a record the
                # route table must still identify this exact dedicated profile.
                if route_id is None:
                    ambiguous = True
    elif not ambiguous and handle is None and record_state == "valid":
        # A persisted orphan must go through reconciliation's process table.
        ambiguous = True

    if not ambiguous and handle is not None:
        try:
            already_reaped = getattr(handle, "reaped") is True
            if already_reaped:
                process_reaped = True
            else:
                process_reaped = (
                    getattr(handle, "stop")(float(deadline_seconds)) is True
                    and getattr(handle, "reaped") is True
                )
        except Exception:
            process_reaped = False
        if not process_reaped:
            failed = True
        facts.append("process_reaped=" + _bool_fact(process_reaped))

    if not ambiguous and handle is None and record_state == "absent":
        route_state, route_id = _lookup_route(route_table, layout.profile, None)
        if route_state == "absent":
            route_removed = True
        else:
            ambiguous = True

    if not ambiguous and handle is not None and route_state == "owned":
        if process_reaped:
            route_removed = _remove_or_confirm_absent(
                route_table,
                layout.profile,
                route_state,
                route_id,
                record.route_id if record is not None else None,
            )
        else:
            # Withdraw reachability even if the child cannot be reaped, but keep
            # the owner record so a later reconciliation can retry safely.
            route_removed = _remove_or_confirm_absent(
                route_table,
                layout.profile,
                route_state,
                route_id,
                record.route_id if record is not None else None,
            )
        if not route_removed:
            failed = True
            facts.append("route_absent=false")
        else:
            facts.append("route_absent=true")
    elif not ambiguous and route_state == "absent":
        route_removed = _remove_or_confirm_absent(
            route_table,
            layout.profile,
            route_state,
            None,
            record.route_id if record is not None else None,
        )
        if not route_removed:
            failed = True

    if (
        not ambiguous
        and process_reaped
        and route_removed
        and record_state == "valid"
        and record is not None
    ):
        record_cleared = clear_owner_record(layout, record)
        if not record_cleared:
            failed = True
        facts.append("owner_record_cleared=" + _bool_fact(record_cleared))

    try:
        stop_listener()
        listener_stopped = True
    except Exception:
        failed = True
    facts.append("listener_stopped=" + _bool_fact(listener_stopped))

    if ambiguous:
        state: CleanupState = "ambiguous"
        reason = "cleanup_ambiguous"
    elif failed or not process_reaped or not route_removed or not listener_stopped:
        state = "failed"
        reason = "cleanup_incomplete"
    else:
        state = "clean"
        reason = "cleanup_complete"
    return CleanupResult(
        state=state,
        reason=reason,
        process_reaped=process_reaped,
        route_removed=route_removed,
        record_cleared=record_cleared,
        listener_stopped=listener_stopped,
        facts=tuple(facts[:8]),
    )


def _stop_verified_orphan(
    record: OwnedProcessRecord,
    layout: ProfileLayout,
    process_table: ProcessTable,
    signaller: Signaller | None,
    *,
    term_wait_seconds: float,
    kill_wait_seconds: float,
    poll_interval_seconds: float,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> str:
    term_result = _send_verified_signal(
        record, layout, process_table, signaller, signal.SIGTERM
    )
    if term_result == "gone":
        return "gone"
    if term_result != "signalled":
        return term_result
    waited = _wait_for_process_exit(
        record,
        layout,
        process_table,
        term_wait_seconds,
        poll_interval_seconds,
        clock,
        sleeper,
    )
    if waited == "gone":
        return "gone"
    if waited != "running":
        return "process_identity_unknown"

    kill_result = _send_verified_signal(
        record, layout, process_table, signaller, signal.SIGKILL
    )
    if kill_result == "gone":
        return "gone"
    if kill_result != "signalled":
        return kill_result
    waited = _wait_for_process_exit(
        record,
        layout,
        process_table,
        kill_wait_seconds,
        poll_interval_seconds,
        clock,
        sleeper,
    )
    if waited == "gone":
        return "gone"
    return "process_not_reaped" if waited == "running" else "process_identity_unknown"


def _send_verified_signal(
    record: OwnedProcessRecord,
    layout: ProfileLayout,
    process_table: ProcessTable,
    signaller: Signaller | None,
    signal_number: int,
) -> str:
    """The only path to the default PID signaler; re-prove all identity fields."""
    state, identity = _read_process(process_table, record.pid)
    if state == "gone":
        return "gone"
    if state != "present" or identity is None:
        return "process_identity_unknown"
    match = _identity_matches_record(identity, record, layout)
    if match != "match":
        return match
    try:
        if signaller is None:
            _default_signaller(record.pid, signal_number)
        else:
            signaller(record.pid, signal_number)
    except ProcessLookupError:
        state, _identity = _read_process(process_table, record.pid)
        return "gone" if state == "gone" else "process_identity_unknown"
    except (OSError, TypeError, ValueError):
        return "signal_failed"
    return "signalled"


def _default_signaller(pid: int, signal_number: int) -> None:
    """Signal one PID; only called after _send_verified_signal's fresh proof."""
    os.kill(pid, signal_number)


def _wait_for_process_exit(
    record: OwnedProcessRecord,
    layout: ProfileLayout,
    process_table: ProcessTable,
    timeout: float,
    interval: float,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> Literal["gone", "running", "unknown"]:
    try:
        expires = float(clock()) + timeout
    except Exception:
        return "unknown"
    while True:
        state, identity = _read_process(process_table, record.pid)
        if state == "gone":
            return "gone"
        if state != "present" or identity is None:
            return "unknown"
        if _identity_matches_record(identity, record, layout) != "match":
            return "unknown"
        try:
            remaining = expires - float(clock())
        except Exception:
            return "unknown"
        if remaining <= 0:
            return "running"
        try:
            sleeper(min(interval, remaining))
        except Exception:
            return "unknown"


def _read_process(
    process_table: ProcessTable, pid: int
) -> tuple[Literal["present", "gone", "unknown"], ProcessIdentity | None]:
    try:
        result = process_table(pid)
    except Exception:
        return "unknown", None
    if isinstance(result, ProcessObservation):
        if result.state == "gone":
            return "gone", None
        return "unknown", None
    if isinstance(result, ProcessIdentity):
        return "present", result
    if result is None:
        return "unknown", None
    return "unknown", None


def _identity_matches_record(
    identity: ProcessIdentity,
    record: OwnedProcessRecord,
    layout: ProfileLayout,
) -> str:
    if (
        type(identity.pid) is not int
        or identity.pid != record.pid
        or type(identity.uid) is not int
        or identity.uid != record.uid
        or identity.uid != _current_uid()
        or not isinstance(identity.creation_token, str)
        or len(identity.creation_token) > 128
        or (
            identity.creation_token != record.creation_token
            and (
                not isinstance(identity.legacy_creation_token, str)
                or len(identity.legacy_creation_token) > 128
                or identity.legacy_creation_token != record.creation_token
            )
        )
    ):
        return "process_identity_mismatch"
    if identity.profile_marker is None:
        return "process_profile_unknown"
    if identity.profile_marker != record.profile or identity.profile_marker != layout.profile:
        return "process_profile_mismatch"
    if not isinstance(identity.exe_path, str):
        return "process_identity_unknown"
    try:
        observed_executable = str(Path(identity.exe_path).resolve(strict=True))
    except (OSError, RuntimeError, TypeError, ValueError):
        return "process_identity_unknown"
    if observed_executable != record.exe_path:
        return "process_identity_mismatch"
    return "match"


def _lookup_route(
    route_table: RouteTable,
    profile: str,
    expected_route_id: str | None,
) -> tuple[RouteState, str | None]:
    try:
        result = route_table.lookup(profile, expected_route_id)
    except Exception:
        return "unknown", None
    if not isinstance(result, RouteObservation):
        return "unknown", None
    if result.state == "absent":
        if result.profile not in {None, profile} or result.route_id is not None:
            return "unknown", None
        return "absent", None
    if result.state != "owned":
        return result.state if result.state in {"unknown", "foreign"} else "unknown", None
    if (
        result.profile != profile
        or not isinstance(result.route_id, str)
        or not _valid_route_id(result.route_id)
        or (expected_route_id is not None and result.route_id != expected_route_id)
    ):
        return "unknown", None
    return "owned", result.route_id


def _remove_or_confirm_absent(
    route_table: RouteTable,
    profile: str,
    previous_state: RouteState,
    previous_route_id: str | None,
    expected_route_id: str | None,
) -> bool:
    if previous_state == "absent":
        state, _route_id = _lookup_route(route_table, profile, None)
        return state == "absent"
    if previous_state != "owned" or previous_route_id is None:
        return False
    state, route_id = _lookup_route(
        route_table, profile, expected_route_id or previous_route_id
    )
    if state == "absent":
        return True
    if state != "owned" or route_id != previous_route_id:
        return False
    try:
        removed = route_table.remove(profile, previous_route_id) is True
    except Exception:
        return False
    if not removed:
        return False
    state, _route_id = _lookup_route(
        route_table, profile, expected_route_id or previous_route_id
    )
    return state == "absent"


def _handle_matches_record(
    handle: object, record: OwnedProcessRecord, layout: ProfileLayout
) -> bool:
    try:
        pid = getattr(handle, "_pid")
        token = getattr(handle, "_identity_token")
        executable = str(Path(getattr(handle, "_binary_path")).resolve(strict=True))
        handle_layout = getattr(handle, "_layout")
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return bool(
        pid == record.pid
        and token == record.creation_token
        and executable == record.exe_path
        and handle_layout == layout
        and record.profile == layout.profile
        and record.uid == _current_uid()
    )


def _read_owner_record(
    layout: ProfileLayout,
) -> tuple[OwnerRecordState, str, OwnedProcessRecord | None, os.stat_result | None]:
    descriptor = _open_state_directory(layout)
    if descriptor is None:
        return "ambiguous", "profile_state_ambiguous", None, None
    file_descriptor = -1
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            return "ambiguous", "owner_record_unsafe", None, None
        try:
            metadata = os.stat(
                OWNER_RECORD_FILENAME,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return "absent", "owner_record_absent", None, None
        except OSError:
            return "ambiguous", "owner_record_unavailable", None, None
        uid = _current_uid()
        if uid is None or not _is_private_regular_file(metadata, uid):
            return "ambiguous", "owner_record_unsafe", None, metadata
        try:
            file_descriptor = os.open(
                OWNER_RECORD_FILENAME,
                os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
                dir_fd=descriptor,
            )
            opened = os.fstat(file_descriptor)
            if (
                not _is_private_regular_file(opened, uid)
                or not _same_file(opened, metadata)
            ):
                return "ambiguous", "owner_record_unsafe", None, metadata
            payload = bytearray()
            while len(payload) <= MAX_OWNER_RECORD_BYTES:
                chunk = os.read(
                    file_descriptor,
                    min(1024, MAX_OWNER_RECORD_BYTES + 1 - len(payload)),
                )
                if not chunk:
                    break
                payload.extend(chunk)
            if len(payload) > MAX_OWNER_RECORD_BYTES:
                return "ambiguous", "owner_record_invalid", None, metadata
        except OSError:
            return "ambiguous", "owner_record_unavailable", None, metadata
        try:
            raw = json.loads(
                payload.decode("ascii"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return "ambiguous", "owner_record_invalid", None, metadata
        record = _record_from_json(raw, layout)
        if record is None:
            return "ambiguous", "owner_record_invalid", None, metadata
        return "valid", "owner_record_valid", record, metadata
    finally:
        if file_descriptor >= 0:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_state_directory(layout: ProfileLayout) -> int | None:
    if not isinstance(layout, ProfileLayout) or not _valid_profile(layout.profile):
        return None
    uid = _current_uid()
    if uid is None:
        return None
    try:
        state_root = Path(layout.state_root)
        profile_root = Path(layout.profile_root)
        state_home = Path(layout.state_home)
        expected_profile = state_root / "neq" / "opentunnel" / layout.profile
        if (
            not state_root.is_absolute()
            or profile_root != expected_profile
            or state_home != expected_profile / "state"
            or Path(layout.owner_file) != expected_profile / "profile_owner.json"
            or state_root.resolve(strict=True) != state_root
            or profile_root.resolve(strict=True) != profile_root
            or state_home.resolve(strict=True) != state_home
        ):
            return None
        for directory in (
            state_root,
            state_root / "neq",
            state_root / "neq" / "opentunnel",
            profile_root,
            state_home,
        ):
            metadata = os.lstat(directory)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != uid
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or directory.resolve(strict=True) != directory
            ):
                return None
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(state_home, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != uid
            or stat.S_IMODE(opened.st_mode) != 0o700
        ):
            os.close(descriptor)
            return None
        return descriptor
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _record_from_json(value: object, layout: ProfileLayout) -> OwnedProcessRecord | None:
    required = {
        "schema",
        "profile",
        "uid",
        "pid",
        "creation_token",
        "exe_path",
        "started_at",
        "generation",
    }
    optional = {"route_id"}
    if not isinstance(value, dict) or not required <= set(value) or not set(value) <= required | optional:
        return None
    if value.get("schema") != OWNER_RECORD_SCHEMA:
        return None
    try:
        record = OwnedProcessRecord(
            profile=value["profile"],
            uid=value["uid"],
            pid=value["pid"],
            creation_token=value["creation_token"],
            exe_path=value["exe_path"],
            started_at=value["started_at"],
            generation=value["generation"],
            route_id=value.get("route_id"),
        )
    except (KeyError, TypeError):
        return None
    return record if _valid_record(record, layout) else None


def _valid_record(record: object, layout: ProfileLayout) -> bool:
    if not isinstance(record, OwnedProcessRecord) or not isinstance(layout, ProfileLayout):
        return False
    uid = _current_uid()
    return bool(
        uid is not None
        and _valid_profile(record.profile)
        and record.profile == layout.profile
        and type(record.uid) is int
        and record.uid == uid
        and _valid_pid(record.pid)
        and isinstance(record.creation_token, str)
        and _TOKEN_RE.fullmatch(record.creation_token) is not None
        and isinstance(record.exe_path, str)
        and _valid_companion_path(record.exe_path, require_exists=False)
        and _valid_timestamp(record.started_at)
        and type(record.generation) is int
        and 1 <= record.generation <= MAX_PROCESS_ID
        and (record.route_id is None or _valid_route_id(record.route_id))
    )


def _serialize_record(record: OwnedProcessRecord) -> bytes:
    value: dict[str, object] = {
        "schema": OWNER_RECORD_SCHEMA,
        "profile": record.profile,
        "uid": record.uid,
        "pid": record.pid,
        "creation_token": record.creation_token,
        "exe_path": record.exe_path,
        "started_at": record.started_at,
        "generation": record.generation,
    }
    if record.route_id is not None:
        value["route_id"] = record.route_id
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    if len(payload) > MAX_OWNER_RECORD_BYTES:
        raise ValueError("owner_record_too_large")
    return payload


def _valid_companion_path(value: str, *, require_exists: bool) -> bool:
    try:
        path = Path(value)
        if not path.is_absolute() or path.name != "opentunnel":
            return False
        if path.parent.parent.name != "v0.6.2" or path.parent.parent.parent.name != "opentunnel":
            return False
        if path.parent.parent.parent.parent.name != "runtime":
            return False
        if _ASSET_STEM_RE.fullmatch(path.parent.name) is None:
            return False
        if os.path.normpath(os.fspath(path)) != os.fspath(path):
            return False
        if require_exists and str(path.resolve(strict=True)) != value:
            return False
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _layout_is_private(layout: ProfileLayout) -> bool:
    descriptor = _open_state_directory(layout)
    if descriptor is None:
        return False
    try:
        return True
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _valid_route_table(route_table: object) -> bool:
    return bool(
        callable(getattr(route_table, "lookup", None))
        and callable(getattr(route_table, "remove", None))
    )


def _valid_profile(value: object) -> bool:
    return isinstance(value, str) and _PROFILE_RE.fullmatch(value) is not None


def _valid_pid(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_PROCESS_ID


def _valid_route_id(value: object) -> bool:
    return isinstance(value, str) and _ROUTE_LABEL_RE.fullmatch(value) is not None


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _valid_deadline(value: object) -> bool:
    return bool(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 < value <= MAX_CLEANUP_WAIT_SECONDS
        and (not isinstance(value, float) or (value == value and abs(value) != float("inf")))
    )


def _current_uid() -> int | None:
    try:
        uid = os.getuid()
    except (AttributeError, OSError):
        return None
    return uid if type(uid) is int and uid >= 0 else None


def _is_private_regular_file(metadata: os.stat_result, uid: int) -> bool:
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == uid
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_size <= MAX_OWNER_RECORD_BYTES
    )


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_owner_record_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("invalid_json_constant")


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("owner_record_write_failed")
        remaining = remaining[written:]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _bool_fact(value: bool) -> str:
    return "true" if value else "false"


def _reconcile_result(
    state: ReconcileState,
    reason: str,
    facts: tuple[str, ...] = (),
) -> ReconcileResult:
    bounded_facts = tuple(item[:80] for item in facts[:8])
    diagnostic = (
        "Facilitator action required: manually resolve the dedicated NEQ profile, "
        "then explicitly rerun cleanup reconciliation."
        if state == "ambiguous" or state == "failed"
        else "Sharing remains off until an explicit facilitator start."
    )
    return ReconcileResult(
        state=state,
        reason=reason[:40],
        sharing_available=state in {"clean", "reconciled", "stale_record_cleared"},
        facts=bounded_facts,
        diagnostic=diagnostic[:200],
    )
