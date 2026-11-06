# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Resumable SP3 matrix ledger and booked-window gate.

This module owns only the durable matrix ledger and the fail-closed booking
boundary. It does not seed a sandbox, start a server, open a socket, or import a
provider/router. Later orchestration must call ``execute_booked_operation``
before invoking either the seeder or launcher.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from scripts.mapping_pilot.scoring import pre_request_guard

from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    PROJECT_ROOT,
    ManifestVerificationError,
    verify_manifest,
)


DEFAULT_EXECUTION_ROOT = Path("tmp/router-rollout/mapping-pilot/sp3")
LEDGER_FILENAME = "matrix_ledger.json"
LEDGER_SCHEMA_VERSION = 3
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TERMINAL_STATUSES = frozenset(("PASS", "FAIL", "BLOCKED"))
_VALID_STATUSES = _TERMINAL_STATUSES | {"missing"}
_CLASSIFICATION_VALUES = frozenset(("INFRASTRUCTURE", "CONTENT/RESULT", "UNRESOLVED"))
_EVIDENCE_CODES = {
    "process": frozenset(
        ("sandbox_prepare_failed", "sandbox_boot_failed", "listener_failed", "evidence_capture_failed")
    ),
    "transport": frozenset(
        (
            "socket_control_failed",
            "dns_failed",
            "tls_failed",
            "connection_reset",
            "transport_timeout",
            "no_transport_error",
        )
    ),
    "provider_status": frozenset(
        ("http_429", "http_5xx", "usable_response_returned", "no_provider_failure")
    ),
    "timing": frozenset(("row_timeout", "row_live_cap", "matrix_live_cap")),
    "artifact_presence": frozenset(
        (
            "required_artifact_missing",
            "required_artifact_present",
            "evidence_capture_failed",
            "transcript_present",
            "transcript_missing",
        )
    ),
}
_INFRASTRUCTURE_EVIDENCE = frozenset(
    (
        ("process", "sandbox_prepare_failed"),
        ("process", "sandbox_boot_failed"),
        ("process", "listener_failed"),
        ("process", "evidence_capture_failed"),
        ("transport", "socket_control_failed"),
        ("transport", "dns_failed"),
        ("transport", "tls_failed"),
        ("transport", "connection_reset"),
        ("provider_status", "http_429"),
        ("provider_status", "http_5xx"),
        ("artifact_presence", "evidence_capture_failed"),
    )
)
_EXECUTION_FIELDS = frozenset(
    (
        "row_run_id",
        "phase",
        "attempt_count",
        "timestamps",
        "live_elapsed_seconds",
        "live_interval",
        "cap_stop",
    )
)
_SLOT_DYNAMIC_FIELDS = frozenset(
    (
        "status",
        "reason",
        "evidence_path",
        "execution",
        "pre_content_classification",
        "content_review_started_at",
        "content_review_event_sequence",
        "replacement",
    )
)
_CONTROL_FIELDS = frozenset(
    ("audit_events", "infrastructure_failure_streak", "paused", "pauses")
)
_EXECUTION_TIMESTAMP_FIELDS = frozenset(
    (
        "seed_started_at",
        "seed_completed_at",
        "launch_timestamps",
        "teardown_completed_at",
        "evidence_finalized_at",
        "scored_at",
    )
)
_EXECUTION_PHASES = frozenset(
    (
        "not_started",
        "seeding",
        "seeded",
        "live",
        "teardown_complete",
        "evidence_finalized",
        "scored",
    )
)
_BOOKING_FIELDS = frozenset(
    (
        "booking_id",
        "holder",
        "window_start",
        "window_end",
        "network_non_overlap_confirmed",
        "recorded_at",
        "actual_start_timestamp",
        "release_timestamp",
        "booked_window_elapsed_seconds",
    )
)
_OPERATION_NAMES = frozenset(("seed", "launch"))
_ROW_EVENTS = frozenset(
    (
        "seed_started",
        "seed_completed",
        "sandbox_launched",
        "teardown_completed",
        "evidence_finalized",
        "scored",
    )
)
_T = TypeVar("_T")


class ExecutionLedgerError(ValueError):
    """Raised when the SP3 ledger is missing, malformed, or unsafe."""


class BookingRequiredError(ExecutionLedgerError):
    """Raised before a live side effect when no valid booked window exists."""


def create_or_resume_ledger(
    run_id: str,
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a 30-slot ledger or load it without changing existing progress.

    The frozen counterbalance is trusted only after its manifest has verified.
    A partially-created run directory without a ledger is never silently reused.
    """
    _validate_token(run_id, "run_id")
    relative_directory, relative_ledger, absolute_directory, absolute_ledger = (
        _run_paths(run_id, ledger_root)
    )
    del relative_directory
    frozen_rows, counterbalance_hash = _load_frozen_slots()
    _reject_symlink_components(absolute_directory)

    if absolute_directory.exists():
        if absolute_directory.is_symlink() or not absolute_directory.is_dir():
            raise ExecutionLedgerError("run directory is unsafe")
        _reject_symlink_components(absolute_ledger)
        if not absolute_ledger.is_file():
            raise ExecutionLedgerError("existing run directory has no resumable ledger")
        ledger = _read_ledger(absolute_ledger)
        _validate_ledger(ledger, run_id, frozen_rows, counterbalance_hash)
        return copy.deepcopy(ledger)

    _ensure_tmp_root()
    absolute_directory.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(absolute_directory)
    _ensure_beneath_tmp(absolute_directory)
    try:
        absolute_directory.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ExecutionLedgerError("run directory already exists; reuse is refused") from exc
    except OSError as exc:
        raise ExecutionLedgerError("run directory cannot be created") from exc

    timestamp = _format_timestamp(_coerce_now(now))
    ledger = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "counterbalance_sha256": counterbalance_hash,
        "bookings": [],
        "control": _empty_matrix_control(),
        "slots": [
            {
                **copy.deepcopy(row),
                "status": "missing",
                "reason": "not_started",
                "evidence_path": None,
                "execution": _empty_row_execution(),
                "pre_content_classification": None,
                "content_review_started_at": None,
                "content_review_event_sequence": None,
                "replacement": None,
            }
            for row in frozen_rows
        ],
    }
    _validate_ledger(ledger, run_id, frozen_rows, counterbalance_hash)
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def record_booking(
    run_id: str,
    *,
    booking_id: str,
    holder: str,
    window_start: str,
    window_end: str,
    network_non_overlap_confirmed: bool,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append an Overseer booking record without authorizing an invalid window."""
    _validate_token(booking_id, "booking_id")
    _validate_identity_text(holder, "holder")
    starts_at = _parse_timestamp(window_start, "window_start")
    ends_at = _parse_timestamp(window_end, "window_end")
    if starts_at >= ends_at:
        raise ExecutionLedgerError("booking window_start must precede window_end")
    if type(network_non_overlap_confirmed) is not bool:
        raise ExecutionLedgerError("Network non-overlap confirmation must be boolean")

    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    _ensure_no_unreleased_booking(ledger)
    bookings = ledger["bookings"]
    if any(item["booking_id"] == booking_id for item in bookings):
        raise ExecutionLedgerError("booking_id has already been recorded")
    for existing in bookings:
        prior_start = _parse_timestamp(existing["window_start"], "window_start")
        prior_end = _parse_timestamp(existing["window_end"], "window_end")
        if starts_at < prior_end and prior_start < ends_at:
            raise ExecutionLedgerError("SP3 booking windows must not overlap")

    booking = {
        "booking_id": booking_id,
        "holder": holder.strip(),
        "window_start": _format_timestamp(starts_at),
        "window_end": _format_timestamp(ends_at),
        "network_non_overlap_confirmed": network_non_overlap_confirmed,
        "recorded_at": _format_timestamp(_coerce_now(now)),
        "actual_start_timestamp": None,
        "release_timestamp": None,
        "booked_window_elapsed_seconds": None,
    }
    bookings.append(booking)
    ledger["updated_at"] = _format_timestamp(_coerce_now(now))
    _validate_bookings(bookings)
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def release_booking(
    run_id: str,
    booking_id: str,
    *,
    release_timestamp: str | None = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record the release timestamp for the current unreleased booking."""
    _validate_token(booking_id, "booking_id")
    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    active = [item for item in ledger["bookings"] if item["release_timestamp"] is None]
    if len(active) != 1 or active[0]["booking_id"] != booking_id:
        raise ExecutionLedgerError("booking is not the current unreleased booking")

    release_instant = (
        _coerce_now(now)
        if release_timestamp is None
        else _parse_timestamp(release_timestamp, "release_timestamp")
    )
    release_value = _format_timestamp(release_instant)
    persisted_release_instant = _parse_timestamp(release_value, "release_timestamp")
    started_at = active[0].get("actual_start_timestamp")
    active[0]["release_timestamp"] = release_value
    active[0]["booked_window_elapsed_seconds"] = (
        max(
            0.0,
            (
                persisted_release_instant
                - _parse_timestamp(started_at, "actual_start_timestamp")
            ).total_seconds(),
        )
        if started_at is not None
        else None
    )
    ledger["updated_at"] = release_value
    _validate_bookings(ledger["bookings"])
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def require_valid_booking(
    run_id: str,
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the active booking only when it is confirmed and within its window."""
    try:
        ledger, _, _ = _load_run_ledger(run_id, ledger_root)
    except ExecutionLedgerError as exc:
        raise BookingRequiredError("a valid SP3 booking is required") from exc
    bookings = ledger["bookings"]
    active = [item for item in bookings if item["release_timestamp"] is None]
    if len(active) != 1:
        raise BookingRequiredError("a single unreleased SP3 booking is required")
    booking = active[0]
    instant = _coerce_now(now)
    starts_at = _parse_timestamp(booking["window_start"], "window_start")
    ends_at = _parse_timestamp(booking["window_end"], "window_end")
    if booking["network_non_overlap_confirmed"] is not True:
        raise BookingRequiredError("Network non-overlap is not confirmed")
    if instant < starts_at or instant >= ends_at:
        raise BookingRequiredError("current time is outside the booked SP3 window")
    return copy.deepcopy(booking)


def execute_booked_operation(
    run_id: str,
    operation: str,
    action: Callable[[Mapping[str, Any]], _T],
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> _T:
    """Run a fakeable seed/launch action only after the booking guard succeeds.

    The callback is the first possible operation-specific side effect. The guard
    itself only reads the ledger, so absent, expired, released, or overlapping
    bookings refuse before the callback can seed or launch anything.
    """
    if operation not in _OPERATION_NAMES:
        raise ExecutionLedgerError("operation must be seed or launch")
    if not callable(action):
        raise ExecutionLedgerError("booked operation action must be callable")
    booking = require_valid_booking(run_id, ledger_root=ledger_root, now=now)
    _mark_booking_started(
        run_id,
        booking["booking_id"],
        ledger_root=ledger_root,
        now=now,
    )
    return action(booking)


def record_row_event(
    run_id: str,
    row_id: str,
    row_run_id: str,
    event: str,
    *,
    event_timestamp: str | None = None,
    live_elapsed_seconds: float | None = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist one row lifecycle timestamp without altering the frozen slot."""
    _validate_token(row_id, "row_id")
    _validate_token(row_run_id, "row_run_id")
    if event not in _ROW_EVENTS:
        raise ExecutionLedgerError("row lifecycle event is invalid")
    instant = (
        _coerce_now(now)
        if event_timestamp is None
        else _parse_timestamp(event_timestamp, "row lifecycle timestamp")
    )
    timestamp = _format_timestamp(instant)
    if live_elapsed_seconds is not None and (
        not isinstance(live_elapsed_seconds, (int, float))
        or isinstance(live_elapsed_seconds, bool)
        or not math.isfinite(float(live_elapsed_seconds))
        or live_elapsed_seconds < 0
    ):
        raise ExecutionLedgerError("live interval duration must be finite and non-negative")

    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    slot = _find_slot(ledger, row_id)
    execution = slot["execution"]
    if event == "seed_started":
        if ledger["control"]["paused"]:
            raise ExecutionLedgerError("matrix is paused pending owner review")
        if execution["phase"] != "not_started" or execution["row_run_id"] is not None:
            raise ExecutionLedgerError("row execution has already started")
        replacement = slot["replacement"]
        if slot["row_type"] == "replacement_only" and (
            replacement is None or replacement["replacement_run_id"] != row_run_id
        ):
            raise ExecutionLedgerError("reserve row_run_id does not match its assignment")
        execution["row_run_id"] = row_run_id
        execution["phase"] = "seeding"
        execution["timestamps"]["seed_started_at"] = timestamp
    else:
        if execution["row_run_id"] != row_run_id:
            raise ExecutionLedgerError("row lifecycle identity does not match the ledger")
        if event == "seed_completed":
            if execution["phase"] != "seeding":
                raise ExecutionLedgerError("row is not in the seeding phase")
            execution["timestamps"]["seed_completed_at"] = timestamp
            execution["phase"] = "seeded"
        elif event == "sandbox_launched":
            if execution["phase"] not in ("seeded", "live"):
                raise ExecutionLedgerError("row must be seeded before sandbox launch")
            execution["timestamps"]["launch_timestamps"].append(timestamp)
            if execution["live_interval"]["started_at"] is None:
                execution["live_interval"]["started_at"] = timestamp
            execution["phase"] = "live"
        elif event == "teardown_completed":
            if execution["phase"] != "live":
                raise ExecutionLedgerError("row has no active live interval to tear down")
            if execution["timestamps"]["teardown_completed_at"] is not None:
                raise ExecutionLedgerError("teardown timestamp is immutable")
            execution["timestamps"]["teardown_completed_at"] = timestamp
            execution["live_interval"]["ended_at"] = timestamp
            execution["live_elapsed_seconds"] = (
                float(live_elapsed_seconds)
                if live_elapsed_seconds is not None
                else None
            )
            execution["phase"] = "teardown_complete"
        elif event == "evidence_finalized":
            if execution["timestamps"]["evidence_finalized_at"] is not None:
                raise ExecutionLedgerError("evidence finalization timestamp is immutable")
            execution["timestamps"]["evidence_finalized_at"] = timestamp
            if execution["phase"] in ("teardown_complete", "seeded"):
                execution["phase"] = (
                    "scored"
                    if execution["timestamps"]["scored_at"] is not None
                    else "evidence_finalized"
                )
        elif event == "scored":
            if execution["timestamps"]["scored_at"] is not None:
                raise ExecutionLedgerError("scoring timestamp is immutable")
            execution["timestamps"]["scored_at"] = timestamp
            if execution["phase"] == "evidence_finalized":
                execution["phase"] = "scored"

    _validate_row_execution(execution)
    ledger["updated_at"] = _format_timestamp(_coerce_now(now))
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def check_provider_request(
    run_id: str,
    row_id: str,
    row_run_id: str,
    *,
    live_started_monotonic: float | None,
    monotonic_now: float | None = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the frozen pre-request guard without counting a request."""
    return _provider_request_decision(
        run_id,
        row_id,
        row_run_id,
        live_started_monotonic=live_started_monotonic,
        monotonic_now=monotonic_now,
        ledger_root=ledger_root,
        now=now,
        increment=False,
    )


def authorize_provider_attempt(
    run_id: str,
    row_id: str,
    row_run_id: str,
    *,
    live_started_monotonic: float | None,
    monotonic_now: float | None = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Guard and durably count one issued outbound provider attempt."""
    return _provider_request_decision(
        run_id,
        row_id,
        row_run_id,
        live_started_monotonic=live_started_monotonic,
        monotonic_now=monotonic_now,
        ledger_root=ledger_root,
        now=now,
        increment=True,
    )


def reconcile_attempt_count(
    run_id: str,
    row_id: str,
    row_run_id: str,
    attempt_count: int | None,
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist a receipt-derived lower bound without reducing durable counts."""
    if attempt_count is not None and (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or attempt_count < 0
    ):
        raise ExecutionLedgerError("attempt_count must be a non-negative integer or unknown")
    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    execution = _find_slot(ledger, row_id)["execution"]
    if execution["row_run_id"] != row_run_id:
        raise ExecutionLedgerError("row lifecycle identity does not match the ledger")
    current = execution["attempt_count"]
    if attempt_count is None or current is None:
        execution["attempt_count"] = None
    else:
        execution["attempt_count"] = max(current, attempt_count)
    ledger["updated_at"] = _format_timestamp(_coerce_now(now))
    _validate_row_execution(execution)
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def matrix_totals(
    run_id: str,
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
) -> dict[str, Any]:
    """Derive durable matrix attempt and completed live-interval totals."""
    ledger, _, _ = _load_run_ledger(run_id, ledger_root)
    return _matrix_totals_from_ledger(ledger)


def cap_snapshot(
    run_id: str,
    row_id: str,
    *,
    live_elapsed_seconds: float | None = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
) -> dict[str, Any]:
    """Return row and matrix counters derived only from the durable ledger."""
    ledger, _, _ = _load_run_ledger(run_id, ledger_root)
    return _cap_snapshot_from_ledger(
        ledger,
        row_id,
        live_elapsed_seconds=live_elapsed_seconds,
    )


def set_slot_status(
    run_id: str,
    row_id: str,
    status: str,
    *,
    reason: str,
    evidence_path: str | None = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record a slot outcome; terminal outcomes cannot be changed on resume."""
    _validate_token(row_id, "row_id")
    if status not in _VALID_STATUSES:
        raise ExecutionLedgerError("status must be PASS, FAIL, BLOCKED, or missing")
    _validate_identity_text(reason, "reason")
    if status == "missing" and evidence_path is not None:
        raise ExecutionLedgerError("missing slots cannot claim an evidence path")
    if evidence_path is not None:
        _validate_tmp_reference(evidence_path, "evidence_path")

    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    slot = next((item for item in ledger["slots"] if item["row_id"] == row_id), None)
    if slot is None:
        raise ExecutionLedgerError("row_id is not a frozen slot")
    existing_status = slot["status"]
    if existing_status in _TERMINAL_STATUSES:
        raise ExecutionLedgerError("terminal slot outcomes are immutable")
    classification = slot["pre_content_classification"]
    review_sequence = slot["content_review_event_sequence"]
    if status in ("FAIL", "BLOCKED") and (
        classification is None
        or review_sequence is None
        or classification["event_sequence"] >= review_sequence
    ):
        raise ExecutionLedgerError(
            "non-PASS terminal rows require a pre-content classification before review"
        )
    if (
        status == "PASS"
        and classification is not None
        and classification["classification"] == "INFRASTRUCTURE"
    ):
        raise ExecutionLedgerError("an infrastructure-classified row cannot be recorded as PASS")

    slot["status"] = status
    slot["reason"] = reason.strip()
    slot["evidence_path"] = evidence_path
    ledger["updated_at"] = _format_timestamp(_coerce_now(now))
    frozen_rows, counterbalance_hash = _load_frozen_slots()
    _validate_ledger(ledger, run_id, frozen_rows, counterbalance_hash)
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def record_pre_content_classification(
    run_id: str,
    row_id: str,
    row_run_id: str,
    classification: str,
    *,
    reason: str,
    evidence: list[Mapping[str, Any]],
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist an explicit classification before the row's content-review marker."""
    _validate_token(row_id, "row_id")
    _validate_token(row_run_id, "row_run_id")
    if classification not in _CLASSIFICATION_VALUES:
        raise ExecutionLedgerError("pre-content classification is invalid")
    _validate_identity_text(reason, "classification reason")
    normalized_evidence = _normalize_classification_evidence(
        evidence, allow_empty=classification == "UNRESOLVED"
    )
    has_eligible_basis = any(
        (item["kind"], item["code"]) in _INFRASTRUCTURE_EVIDENCE
        for item in normalized_evidence
    )
    if classification == "INFRASTRUCTURE" and not has_eligible_basis:
        raise ExecutionLedgerError(
            "infrastructure classification requires objective qualifying evidence"
        )

    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    slot = _find_slot(ledger, row_id)
    execution = slot["execution"]
    if execution["row_run_id"] != row_run_id:
        raise ExecutionLedgerError("classification row identity does not match the ledger")
    if execution["phase"] in ("not_started", "live"):
        raise ExecutionLedgerError("classification requires a stopped row before content review")
    if slot["pre_content_classification"] is not None:
        raise ExecutionLedgerError("pre-content classification is immutable")
    if slot["content_review_started_at"] is not None:
        raise ExecutionLedgerError("classification must precede content review")
    control = ledger["control"]
    if control["paused"]:
        raise ExecutionLedgerError("matrix is paused pending owner review")

    timestamp = _format_timestamp(_coerce_now(now))
    event_sequence = len(control["audit_events"]) + 1
    classification_record = {
        "classification": classification,
        "reason": reason.strip(),
        "evidence": normalized_evidence,
        "recorded_at": timestamp,
        "row_run_id": row_run_id,
        "event_sequence": event_sequence,
        "reserve_eligible": classification == "INFRASTRUCTURE" and has_eligible_basis,
    }
    slot["pre_content_classification"] = classification_record
    control["audit_events"].append(
        {
            "sequence": event_sequence,
            "event": "pre_content_classification",
            "row_id": row_id,
            "row_run_id": row_run_id,
            "classification": classification,
            "recorded_at": timestamp,
        }
    )
    if classification == "INFRASTRUCTURE":
        control["infrastructure_failure_streak"].append(event_sequence)
    elif classification == "CONTENT/RESULT":
        control["infrastructure_failure_streak"] = []

    if len(control["infrastructure_failure_streak"]) >= 3:
        trigger_sequences = control["infrastructure_failure_streak"][-3:]
        events_by_sequence = {
            event["sequence"]: event for event in control["audit_events"]
        }
        trigger_events = [events_by_sequence[value] for value in trigger_sequences]
        pause = {
            "pause_id": "pause-%03d" % (len(control["pauses"]) + 1),
            "triggered_at": timestamp,
            "triggering_classification_sequences": list(trigger_sequences),
            "triggering_row_ids": [event["row_id"] for event in trigger_events],
            "owner_review": None,
            "resumed_at": None,
        }
        control["pauses"].append(pause)
        control["paused"] = True

    ledger["updated_at"] = timestamp
    _validate_ledger(
        ledger,
        run_id,
        *_load_frozen_slots(),
    )
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def mark_content_review_started(
    run_id: str,
    row_id: str,
    row_run_id: str,
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record the irreversible boundary after which classification is too late."""
    _validate_token(row_id, "row_id")
    _validate_token(row_run_id, "row_run_id")
    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    slot = _find_slot(ledger, row_id)
    execution = slot["execution"]
    if execution["row_run_id"] != row_run_id:
        raise ExecutionLedgerError("content-review row identity does not match the ledger")
    if execution["phase"] in ("not_started", "live"):
        raise ExecutionLedgerError("content review requires a stopped row")
    if slot["pre_content_classification"] is None:
        raise ExecutionLedgerError(
            "pre-content classification is required before content review"
        )
    if slot["content_review_started_at"] is not None:
        raise ExecutionLedgerError("content-review marker is immutable")

    timestamp = _format_timestamp(_coerce_now(now))
    event_sequence = len(ledger["control"]["audit_events"]) + 1
    slot["content_review_started_at"] = timestamp
    slot["content_review_event_sequence"] = event_sequence
    ledger["control"]["audit_events"].append(
        {
            "sequence": event_sequence,
            "event": "content_review_started",
            "row_id": row_id,
            "row_run_id": row_run_id,
            "recorded_at": timestamp,
        }
    )
    ledger["updated_at"] = timestamp
    _validate_ledger(ledger, run_id, *_load_frozen_slots())
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def record_owner_review_and_resume(
    run_id: str,
    *,
    reviewer_label: str,
    note: str,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record an explicit owner review and resume a paused matrix."""
    _validate_identity_text(reviewer_label, "reviewer_label")
    _validate_identity_text(note, "owner review note")
    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    control = ledger["control"]
    if not control["paused"] or not control["pauses"]:
        raise ExecutionLedgerError("matrix is not paused for owner review")
    pause = control["pauses"][-1]
    if pause["owner_review"] is not None:
        raise ExecutionLedgerError("paused matrix already has an owner review")

    timestamp = _format_timestamp(_coerce_now(now))
    event_sequence = len(control["audit_events"]) + 1
    review = {
        "reviewer_label": reviewer_label.strip(),
        "note": note.strip(),
        "recorded_at": timestamp,
        "event_sequence": event_sequence,
        "resume_authorized": True,
    }
    pause["owner_review"] = review
    pause["resumed_at"] = timestamp
    control["audit_events"].append(
        {
            "sequence": event_sequence,
            "event": "owner_review_resume",
            "pause_id": pause["pause_id"],
            "reviewer_label": review["reviewer_label"],
            "note": review["note"],
            "recorded_at": timestamp,
        }
    )
    control["paused"] = False
    control["infrastructure_failure_streak"] = []
    ledger["updated_at"] = timestamp
    _validate_ledger(ledger, run_id, *_load_frozen_slots())
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(ledger)


def assert_row_start_allowed(
    run_id: str,
    row_id: str,
    *,
    row_run_id: str | None = None,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
) -> dict[str, Any] | None:
    """Refuse a new row before any seeding if the matrix is paused or identity is unsafe."""
    _validate_token(row_id, "row_id")
    if row_run_id is not None:
        _validate_token(row_run_id, "row_run_id")
    ledger, _, _ = _load_run_ledger(run_id, ledger_root)
    control = ledger["control"]
    if control["paused"]:
        raise ExecutionLedgerError("matrix is paused pending owner review")
    slot = _find_slot(ledger, row_id)
    if slot["status"] in _TERMINAL_STATUSES:
        raise ExecutionLedgerError("terminal rows cannot be started again")
    execution = slot["execution"]
    if execution["phase"] != "not_started" or execution["row_run_id"] is not None:
        raise ExecutionLedgerError("started row cannot be replayed")
    replacement = slot["replacement"]
    if slot["row_type"] == "replacement_only":
        if replacement is None:
            raise ExecutionLedgerError("reserve slot has no eligible replacement assignment")
        if row_run_id is not None and row_run_id != replacement["replacement_run_id"]:
            raise ExecutionLedgerError("reserve row_run_id does not match its assignment")
        return copy.deepcopy(replacement)
    if replacement is not None:
        raise ExecutionLedgerError("planned row cannot carry a reserve assignment")
    return None


def activate_next_reserve(
    run_id: str,
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assign the next frozen reserve slot to the earliest eligible failed row."""
    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    control = ledger["control"]
    if control["paused"]:
        raise ExecutionLedgerError("matrix is paused pending owner review")
    reserve_slots = [
        slot for slot in ledger["slots"] if slot["row_type"] == "replacement_only"
    ]
    active_reserve = next(
        (
            slot
            for slot in reserve_slots
            if slot["replacement"] is not None
            and slot["status"] == "missing"
        ),
        None,
    )
    if active_reserve is not None:
        if active_reserve["execution"]["phase"] != "not_started":
            raise ExecutionLedgerError("current reserve row must finish before another is assigned")
        return copy.deepcopy(active_reserve["replacement"])

    reserve = next((slot for slot in reserve_slots if slot["replacement"] is None), None)
    if reserve is None:
        raise ExecutionLedgerError("all four frozen reserve slots have been consumed")

    used_sources = {
        slot["replacement"]["source_row_id"]
        for slot in reserve_slots
        if slot["replacement"] is not None
    }
    source_slot = None
    for event in control["audit_events"]:
        if (
            event["event"] != "pre_content_classification"
            or event["classification"] != "INFRASTRUCTURE"
            or event["row_id"] in used_sources
        ):
            continue
        candidate = _find_slot(ledger, event["row_id"])
        classification_record = candidate["pre_content_classification"]
        marker_sequence = candidate["content_review_event_sequence"]
        if (
            candidate["status"] not in ("FAIL", "BLOCKED")
            or classification_record is None
            or classification_record["row_run_id"] != event["row_run_id"]
            or classification_record["event_sequence"] != event["sequence"]
            or not classification_record["reserve_eligible"]
            or marker_sequence is None
            or classification_record["event_sequence"] >= marker_sequence
        ):
            continue
        source_slot = candidate
        break
    if source_slot is None:
        raise ExecutionLedgerError("no pre-content infrastructure failure is reserve-eligible")

    if source_slot["row_type"] == "replacement_only":
        inherited_cell = copy.deepcopy(source_slot["replacement"]["inherited_cell"])
    else:
        inherited_cell = {
            key: copy.deepcopy(source_slot[key])
            for key in ("block", "arm", "party", "script", "repeat", "matched_cohort")
        }
    used_run_ids = {
        slot["execution"]["row_run_id"]
        for slot in ledger["slots"]
        if slot["execution"]["row_run_id"] is not None
    }
    replacement_run_id = uuid.uuid4().hex
    while replacement_run_id in used_run_ids:
        replacement_run_id = uuid.uuid4().hex
    timestamp = _format_timestamp(_coerce_now(now))
    assignment = {
        "source_row_id": source_slot["row_id"],
        "source_row_run_id": source_slot["execution"]["row_run_id"],
        "replacement_run_id": replacement_run_id,
        "inherited_cell": inherited_cell,
        "reserve_seed": reserve["fixed_seed"],
        "activated_at": timestamp,
    }
    reserve["replacement"] = assignment
    reserve["reason"] = "reserve assigned to %s; execution not started" % source_slot["row_id"]
    ledger["updated_at"] = timestamp
    _validate_ledger(ledger, run_id, *_load_frozen_slots())
    _write_ledger(relative_ledger, absolute_ledger, ledger)
    return copy.deepcopy(assignment)


def get_reserve_assignment(
    run_id: str,
    row_id: str,
    *,
    ledger_root: str | Path = DEFAULT_EXECUTION_ROOT,
) -> dict[str, Any] | None:
    """Read an activated reserve assignment, returning None for a planned row."""
    ledger, _, _ = _load_run_ledger(run_id, ledger_root)
    slot = _find_slot(ledger, row_id)
    if slot["row_type"] != "replacement_only":
        return None
    if slot["replacement"] is None:
        raise ExecutionLedgerError("reserve slot has no eligible replacement assignment")
    return copy.deepcopy(slot["replacement"])


def _provider_request_decision(
    run_id: str,
    row_id: str,
    row_run_id: str,
    *,
    live_started_monotonic: float | None,
    monotonic_now: float | None,
    ledger_root: str | Path,
    now: datetime | None,
    increment: bool,
) -> dict[str, Any]:
    _validate_token(row_id, "row_id")
    _validate_token(row_run_id, "row_run_id")
    monotonic_value = _checked_monotonic(monotonic_now)
    live_started = _checked_monotonic(live_started_monotonic)
    row_elapsed: float | None = None
    if (
        monotonic_value is not None
        and live_started is not None
        and monotonic_value >= live_started
    ):
        row_elapsed = monotonic_value - live_started

    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    slot = _find_slot(ledger, row_id)
    execution = slot["execution"]
    if execution["row_run_id"] != row_run_id:
        raise ExecutionLedgerError("row lifecycle identity does not match the ledger")

    totals = _cap_snapshot_from_ledger(
        ledger,
        row_id,
        live_elapsed_seconds=row_elapsed,
    )
    matrix_attempts = totals["matrix_attempts"]
    if matrix_attempts == "unknown":
        matrix_attempts = None
    matrix_elapsed = totals["matrix_elapsed_seconds"]
    if matrix_elapsed == "unknown":
        matrix_elapsed = None
    row_attempts = totals["row_attempts"]
    if row_attempts == "unknown":
        row_attempts = None

    result = pre_request_guard(
        row_attempts,
        row_elapsed,
        matrix_attempts,
        matrix_elapsed,
    )
    result["row_id"] = row_id
    result["matrix_live_intervals_seconds"] = totals["matrix_elapsed_seconds"]

    changed = False
    if not result["allowed"]:
        reasons = result["reasons"]
        existing = execution.get("cap_stop")
        if isinstance(existing, Mapping):
            reasons = sorted(set(existing.get("reasons", [])) | set(reasons))
        execution["cap_stop"] = {
            "timestamp": _format_timestamp(_coerce_now(now)),
            "reasons": reasons,
            "actual_counts": copy.deepcopy(result["actual_counts"]),
        }
        changed = True
    elif increment:
        execution["attempt_count"] += 1
        changed = True

    if changed:
        ledger["updated_at"] = _format_timestamp(_coerce_now(now))
        _validate_row_execution(execution)
        _write_ledger(relative_ledger, absolute_ledger, ledger)
    result["issued_attempt_count"] = (
        execution["attempt_count"]
        if _is_count(execution["attempt_count"])
        else "unknown"
    )
    return result


def _matrix_totals_from_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    attempt_values = [slot["execution"]["attempt_count"] for slot in ledger["slots"]]
    matrix_attempts: int | str = (
        sum(attempt_values)
        if all(_is_count(value) for value in attempt_values)
        else "unknown"
    )
    elapsed, elapsed_known = _sum_completed_live_intervals(ledger["slots"])
    return {
        "matrix_attempts": matrix_attempts,
        "matrix_elapsed_seconds": elapsed if elapsed_known else "unknown",
    }


def _cap_snapshot_from_ledger(
    ledger: Mapping[str, Any],
    row_id: str,
    *,
    live_elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    slot = _find_slot(ledger, row_id)
    execution = slot["execution"]
    row_attempts: int | str = (
        execution["attempt_count"]
        if _is_count(execution["attempt_count"])
        else "unknown"
    )
    if execution["phase"] == "live":
        row_elapsed: float | str = (
            float(live_elapsed_seconds)
            if _is_seconds(live_elapsed_seconds)
            else "unknown"
        )
    elif execution["timestamps"]["launch_timestamps"]:
        row_elapsed = (
            float(execution["live_elapsed_seconds"])
            if _is_seconds(execution["live_elapsed_seconds"])
            else "unknown"
        )
    else:
        row_elapsed = 0.0

    attempt_values = [item["execution"]["attempt_count"] for item in ledger["slots"]]
    matrix_attempts: int | str = (
        sum(attempt_values)
        if all(_is_count(value) for value in attempt_values)
        else "unknown"
    )
    matrix_elapsed, elapsed_known = _sum_completed_live_intervals(
        ledger["slots"],
        active_row_id=row_id if execution["phase"] == "live" else None,
        active_elapsed_seconds=live_elapsed_seconds,
    )
    return {
        "row_id": row_id,
        "row_attempts": row_attempts,
        "row_elapsed_seconds": row_elapsed,
        "matrix_attempts": matrix_attempts,
        "matrix_elapsed_seconds": (
            matrix_elapsed if elapsed_known else "unknown"
        ),
        "cap_stop": copy.deepcopy(execution["cap_stop"]),
        "booking": (
            {
                key: copy.deepcopy(ledger["bookings"][-1].get(key))
                for key in (
                    "booking_id",
                    "recorded_at",
                    "actual_start_timestamp",
                    "release_timestamp",
                    "booked_window_elapsed_seconds",
                )
            }
            if ledger["bookings"]
            else None
        ),
    }


def _sum_completed_live_intervals(
    slots: Any,
    *,
    active_row_id: str | None = None,
    active_elapsed_seconds: float | None = None,
) -> tuple[float, bool]:
    total = 0.0
    for slot in slots:
        execution = slot["execution"]
        if not execution["timestamps"]["launch_timestamps"]:
            continue
        if execution["timestamps"]["teardown_completed_at"] is None:
            if (
                slot["row_id"] == active_row_id
                and execution["phase"] == "live"
                and _is_seconds(active_elapsed_seconds)
            ):
                total += float(active_elapsed_seconds)
                continue
            return 0.0, False
        elapsed = execution["live_elapsed_seconds"]
        if not _is_seconds(elapsed):
            return 0.0, False
        total += float(elapsed)
    return total, True


def _mark_booking_started(
    run_id: str,
    booking_id: str,
    *,
    ledger_root: str | Path,
    now: datetime | None,
) -> None:
    ledger, relative_ledger, absolute_ledger = _load_run_ledger(run_id, ledger_root)
    booking = next(
        (item for item in ledger["bookings"] if item["booking_id"] == booking_id),
        None,
    )
    if booking is None or booking["release_timestamp"] is not None:
        raise BookingRequiredError("booking is no longer active")
    instant = _coerce_now(now)
    formatted = _format_timestamp(instant)
    if booking["actual_start_timestamp"] is None:
        booking["actual_start_timestamp"] = formatted
    elif _parse_timestamp(booking["actual_start_timestamp"], "actual_start_timestamp") > instant:
        raise BookingRequiredError("booking start timestamp is later than the current operation")
    ledger["updated_at"] = formatted
    _validate_bookings(ledger["bookings"])
    _write_ledger(relative_ledger, absolute_ledger, ledger)


def _find_slot(ledger: Mapping[str, Any], row_id: str) -> dict[str, Any]:
    for slot in ledger["slots"]:
        if slot["row_id"] == row_id:
            return slot
    raise ExecutionLedgerError("row_id is not a frozen slot")


def _empty_row_execution() -> dict[str, Any]:
    return {
        "row_run_id": None,
        "phase": "not_started",
        "attempt_count": 0,
        "timestamps": {
            "seed_started_at": None,
            "seed_completed_at": None,
            "launch_timestamps": [],
            "teardown_completed_at": None,
            "evidence_finalized_at": None,
            "scored_at": None,
        },
        "live_elapsed_seconds": None,
        "live_interval": {"started_at": None, "ended_at": None},
        "cap_stop": None,
    }


def _empty_matrix_control() -> dict[str, Any]:
    return {
        "audit_events": [],
        "infrastructure_failure_streak": [],
        "paused": False,
        "pauses": [],
    }


def _validate_row_execution(execution: Any) -> None:
    if not isinstance(execution, Mapping) or set(execution) != _EXECUTION_FIELDS:
        raise ExecutionLedgerError("row execution ledger fields are invalid")
    row_run_id = execution.get("row_run_id")
    if row_run_id is not None:
        _validate_token(row_run_id, "row_run_id")
    if execution.get("phase") not in _EXECUTION_PHASES:
        raise ExecutionLedgerError("row execution phase is invalid")
    attempt_count = execution.get("attempt_count")
    if attempt_count is not None and not _is_count(attempt_count):
        raise ExecutionLedgerError("row attempt counter must be a non-negative integer or unknown")
    timestamps = execution.get("timestamps")
    if not isinstance(timestamps, Mapping) or set(timestamps) != _EXECUTION_TIMESTAMP_FIELDS:
        raise ExecutionLedgerError("row lifecycle timestamps are invalid")
    for key, value in timestamps.items():
        if key == "launch_timestamps":
            if not isinstance(value, list):
                raise ExecutionLedgerError("launch timestamps must be a list")
            for launch_timestamp in value:
                _parse_timestamp(launch_timestamp, "launch_timestamp")
        elif value is not None:
            _parse_timestamp(value, key)
    interval = execution.get("live_interval")
    if not isinstance(interval, Mapping) or set(interval) != {"started_at", "ended_at"}:
        raise ExecutionLedgerError("row live interval timestamps are invalid")
    for key, value in interval.items():
        if value is not None:
            _parse_timestamp(value, "live_interval.%s" % key)
    elapsed = execution.get("live_elapsed_seconds")
    if elapsed is not None and not _is_seconds(elapsed):
        raise ExecutionLedgerError("row live interval duration is invalid")
    if timestamps["launch_timestamps"] and interval["started_at"] is None:
        raise ExecutionLedgerError("launched row has no live interval start")
    if (row_run_id is None) != (timestamps["seed_started_at"] is None):
        raise ExecutionLedgerError("row identity and seed-start timestamp disagree")
    seed_started = timestamps["seed_started_at"]
    seed_completed = timestamps["seed_completed_at"]
    if seed_completed is not None:
        if seed_started is None or _parse_timestamp(seed_completed, "seed_completed_at") < _parse_timestamp(
            seed_started, "seed_started_at"
        ):
            raise ExecutionLedgerError("seed lifecycle timestamps are inconsistent")
    launch_times = [
        _parse_timestamp(value, "launch_timestamp")
        for value in timestamps["launch_timestamps"]
    ]
    if launch_times:
        if seed_completed is None or any(
            launch_time < _parse_timestamp(seed_completed, "seed_completed_at")
            for launch_time in launch_times
        ):
            raise ExecutionLedgerError("sandbox launch precedes seed completion")
        if interval["started_at"] != timestamps["launch_timestamps"][0]:
            raise ExecutionLedgerError("live interval must begin at the first sandbox launch")
    if timestamps["teardown_completed_at"] is not None:
        if interval["ended_at"] is None:
            raise ExecutionLedgerError("torn-down row has an incomplete live interval")
        teardown_time = _parse_timestamp(
            timestamps["teardown_completed_at"], "teardown_completed_at"
        )
        if not launch_times or teardown_time < launch_times[-1]:
            raise ExecutionLedgerError("teardown timestamp precedes sandbox launch")
        if interval["ended_at"] != timestamps["teardown_completed_at"]:
            raise ExecutionLedgerError("live interval end must match teardown completion")
    elif interval["ended_at"] is not None or elapsed is not None:
        raise ExecutionLedgerError("live interval duration requires teardown completion")
    if timestamps["evidence_finalized_at"] is not None:
        finalized_time = _parse_timestamp(
            timestamps["evidence_finalized_at"], "evidence_finalized_at"
        )
        interval_end = timestamps["teardown_completed_at"] or timestamps["seed_completed_at"]
        if interval_end is not None and finalized_time < _parse_timestamp(
            interval_end, "evidence lifecycle end"
        ):
            raise ExecutionLedgerError("evidence finalization precedes lifecycle completion")
    if timestamps["scored_at"] is not None:
        score_time = _parse_timestamp(timestamps["scored_at"], "scored_at")
        lifecycle_end = (
            timestamps["teardown_completed_at"]
            or timestamps["seed_completed_at"]
            or timestamps["seed_started_at"]
        )
        if lifecycle_end is not None and score_time < _parse_timestamp(
            lifecycle_end, "scoring lifecycle end"
        ):
            raise ExecutionLedgerError("scoring timestamp precedes row completion")
    cap_stop = execution.get("cap_stop")
    if cap_stop is not None:
        if not isinstance(cap_stop, Mapping) or set(cap_stop) != {
            "timestamp",
            "reasons",
            "actual_counts",
        }:
            raise ExecutionLedgerError("row cap-stop record is invalid")
        _parse_timestamp(cap_stop.get("timestamp"), "cap_stop.timestamp")
        reasons = cap_stop.get("reasons")
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) or not reason for reason in reasons
        ):
            raise ExecutionLedgerError("row cap-stop reasons are invalid")
        if not isinstance(cap_stop.get("actual_counts"), Mapping):
            raise ExecutionLedgerError("row cap-stop counts are invalid")


def _checked_monotonic(value: Any) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        return None
    return float(value)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_seconds(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    )


def _load_run_ledger(
    run_id: str, ledger_root: str | Path
) -> tuple[dict[str, Any], Path, Path]:
    _validate_token(run_id, "run_id")
    relative_directory, relative_ledger, absolute_directory, absolute_ledger = _run_paths(
        run_id, ledger_root
    )
    del relative_directory
    frozen_rows, counterbalance_hash = _load_frozen_slots()
    _reject_symlink_components(absolute_directory)
    if not absolute_directory.is_dir() or absolute_directory.is_symlink():
        raise ExecutionLedgerError("SP3 run ledger is unavailable")
    _reject_symlink_components(absolute_ledger)
    ledger = _read_ledger(absolute_ledger)
    _validate_ledger(ledger, run_id, frozen_rows, counterbalance_hash)
    return ledger, relative_ledger, absolute_ledger


def _load_frozen_slots() -> tuple[list[dict[str, Any]], str]:
    try:
        verified = verify_manifest()
    except ManifestVerificationError as exc:
        raise ExecutionLedgerError("frozen preregistration manifest verification failed") from exc
    expected_hash = verified.get("counterbalance.json")
    if not isinstance(expected_hash, str):
        raise ExecutionLedgerError("counterbalance.json is not covered by the frozen manifest")

    counterbalance_path = DEFAULT_PREREG_ROOT / "counterbalance.json"
    if counterbalance_path.is_symlink() or not counterbalance_path.is_file():
        raise ExecutionLedgerError("frozen counterbalance is missing or unsafe")
    try:
        raw = counterbalance_path.read_bytes()
    except OSError as exc:
        raise ExecutionLedgerError("frozen counterbalance cannot be read") from exc
    observed_hash = hashlib.sha256(raw).hexdigest()
    if observed_hash != expected_hash:
        raise ExecutionLedgerError("frozen counterbalance changed after manifest verification")
    try:
        counterbalance = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExecutionLedgerError("frozen counterbalance is invalid JSON") from exc
    if not isinstance(counterbalance, Mapping):
        raise ExecutionLedgerError("frozen counterbalance must be an object")

    rows = counterbalance.get("rows")
    if (
        counterbalance.get("planned_rows") != 26
        or counterbalance.get("reserve_rows") != 4
        or counterbalance.get("total_rows") != 30
        or not isinstance(rows, list)
        or len(rows) != 30
    ):
        raise ExecutionLedgerError("frozen counterbalance must contain exactly 30 slots")

    normalized_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ExecutionLedgerError("each frozen counterbalance slot must be an object")
        row_id = row.get("row_id")
        run_order = row.get("run_order")
        row_type = row.get("row_type")
        if (
            not isinstance(row_id, str)
            or not _SAFE_TOKEN.fullmatch(row_id)
            or row_id in seen_ids
            or type(run_order) is not int
            or run_order != index
            or row_type not in ("planned", "replacement_only")
            or (index <= 26 and row_type != "planned")
            or (index > 26 and row_type != "replacement_only")
        ):
            raise ExecutionLedgerError("frozen counterbalance slot identity or order is invalid")
        seen_ids.add(row_id)
        normalized_rows.append(copy.deepcopy(dict(row)))
    return normalized_rows, observed_hash


def _validate_ledger(
    ledger: Mapping[str, Any],
    run_id: str,
    frozen_rows: list[dict[str, Any]],
    counterbalance_hash: str,
) -> None:
    if (
        set(ledger)
        != {
            "schema_version",
            "run_id",
            "created_at",
            "updated_at",
            "counterbalance_sha256",
            "bookings",
            "control",
            "slots",
        }
        or
        ledger.get("schema_version") != LEDGER_SCHEMA_VERSION
        or ledger.get("run_id") != run_id
        or ledger.get("counterbalance_sha256") != counterbalance_hash
    ):
        raise ExecutionLedgerError("ledger identity does not match the frozen run")
    _parse_timestamp(ledger.get("created_at"), "created_at")
    _parse_timestamp(ledger.get("updated_at"), "updated_at")
    slots = ledger.get("slots")
    if not isinstance(slots, list) or len(slots) != len(frozen_rows):
        raise ExecutionLedgerError("ledger does not contain all 30 frozen slots")
    slots_by_id: dict[str, Mapping[str, Any]] = {}
    row_run_ids: set[str] = set()
    for slot, frozen_row in zip(slots, frozen_rows):
        if not isinstance(slot, Mapping):
            raise ExecutionLedgerError("ledger slot must be an object")
        if set(slot) != set(frozen_row) | _SLOT_DYNAMIC_FIELDS:
            raise ExecutionLedgerError("ledger slot fields are invalid")
        for key, value in frozen_row.items():
            if slot.get(key) != value:
                raise ExecutionLedgerError("ledger slot IDs, metadata, or order differ from frozen input")
        if slot.get("status") not in _VALID_STATUSES:
            raise ExecutionLedgerError("ledger slot status is invalid")
        _validate_identity_text(slot.get("reason"), "slot reason")
        if slot.get("evidence_path") is not None:
            _validate_tmp_reference(slot["evidence_path"], "evidence_path")
        execution = slot.get("execution")
        _validate_row_execution(execution)
        if execution["row_run_id"] is not None:
            if execution["row_run_id"] in row_run_ids:
                raise ExecutionLedgerError("row_run_id values must be unique")
            row_run_ids.add(execution["row_run_id"])
        classification = slot.get("pre_content_classification")
        if classification is not None:
            _validate_classification_record(classification)
            if classification["row_run_id"] != execution["row_run_id"]:
                raise ExecutionLedgerError("classification row identity is inconsistent")
        review_at = slot.get("content_review_started_at")
        review_sequence = slot.get("content_review_event_sequence")
        if review_at is None:
            if review_sequence is not None:
                raise ExecutionLedgerError("content-review timestamp and event sequence disagree")
        else:
            _parse_timestamp(review_at, "content_review_started_at")
            if not _is_count(review_sequence) or review_sequence < 1:
                raise ExecutionLedgerError("content-review event sequence is invalid")
            if classification is None:
                raise ExecutionLedgerError(
                    "content review has no pre-content classification"
                )
            if classification["event_sequence"] >= review_sequence:
                raise ExecutionLedgerError("pre-content classification must precede content review")
        if slot["status"] in ("FAIL", "BLOCKED") and (
            classification is None
            or review_sequence is None
            or classification["event_sequence"] >= review_sequence
        ):
            raise ExecutionLedgerError(
                "non-PASS terminal rows require a pre-content classification before review"
            )
        replacement = slot.get("replacement")
        _validate_replacement_record(slot, replacement)
        slots_by_id[slot["row_id"]] = slot
    _validate_replacements(slots_by_id)
    bookings = ledger.get("bookings")
    if not isinstance(bookings, list):
        raise ExecutionLedgerError("ledger bookings must be a list")
    _validate_bookings(bookings)
    _validate_matrix_control(ledger.get("control"), slots_by_id)


def _normalize_classification_evidence(
    evidence: Any,
    *,
    allow_empty: bool = False,
) -> list[dict[str, str]]:
    if (
        not isinstance(evidence, Sequence)
        or isinstance(evidence, (str, bytes))
        or (not evidence and not allow_empty)
    ):
        raise ExecutionLedgerError("classification evidence must be a non-empty list")
    normalized: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"kind", "code", "source"}:
            raise ExecutionLedgerError("classification evidence fields are invalid")
        kind = item.get("kind")
        code = item.get("code")
        source = item.get("source")
        if kind not in _EVIDENCE_CODES:
            raise ExecutionLedgerError("classification evidence kind is invalid")
        if code not in _EVIDENCE_CODES[kind]:
            raise ExecutionLedgerError("classification evidence code is invalid for its kind")
        _validate_tmp_reference(source, "classification evidence source")
        normalized.append({"kind": kind, "code": code, "source": source})
    return normalized


def _validate_classification_record(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "classification",
        "reason",
        "evidence",
        "recorded_at",
        "row_run_id",
        "event_sequence",
        "reserve_eligible",
    }:
        raise ExecutionLedgerError("pre-content classification record fields are invalid")
    classification = value.get("classification")
    if classification not in _CLASSIFICATION_VALUES:
        raise ExecutionLedgerError("pre-content classification is invalid")
    _validate_identity_text(value.get("reason"), "classification reason")
    _validate_token(value.get("row_run_id"), "classification row_run_id")
    _parse_timestamp(value.get("recorded_at"), "classification recorded_at")
    if not _is_count(value.get("event_sequence")) or value["event_sequence"] < 1:
        raise ExecutionLedgerError("classification event sequence is invalid")
    evidence = _normalize_classification_evidence(
        value.get("evidence"), allow_empty=classification == "UNRESOLVED"
    )
    has_eligible_basis = any(
        (item["kind"], item["code"]) in _INFRASTRUCTURE_EVIDENCE for item in evidence
    )
    if classification == "INFRASTRUCTURE" and not has_eligible_basis:
        raise ExecutionLedgerError("infrastructure classification has no qualifying evidence")
    expected_eligibility = classification == "INFRASTRUCTURE" and has_eligible_basis
    if type(value.get("reserve_eligible")) is not bool or value["reserve_eligible"] != expected_eligibility:
        raise ExecutionLedgerError("classification reserve eligibility is inconsistent")


def _validate_replacement_record(slot: Mapping[str, Any], value: Any) -> None:
    if value is None:
        if slot["row_type"] == "planned" and slot["status"] == "missing":
            return
        if slot["row_type"] == "planned":
            return
        if slot["status"] != "missing" or slot["execution"]["phase"] != "not_started":
            raise ExecutionLedgerError("unused reserve slot cannot have execution progress")
        return
    if slot["row_type"] != "replacement_only" or not isinstance(value, Mapping) or set(value) != {
        "source_row_id",
        "source_row_run_id",
        "replacement_run_id",
        "inherited_cell",
        "reserve_seed",
        "activated_at",
    }:
        raise ExecutionLedgerError("reserve replacement assignment fields are invalid")
    _validate_token(value.get("source_row_id"), "replacement source_row_id")
    _validate_token(value.get("source_row_run_id"), "replacement source_row_run_id")
    _validate_token(value.get("replacement_run_id"), "replacement_run_id")
    if value.get("reserve_seed") != slot.get("fixed_seed"):
        raise ExecutionLedgerError("reserve replacement must use its frozen reserve seed")
    _parse_timestamp(value.get("activated_at"), "replacement activated_at")
    inherited = value.get("inherited_cell")
    expected_cell_fields = {"block", "arm", "party", "script", "repeat", "matched_cohort"}
    if not isinstance(inherited, Mapping) or set(inherited) != expected_cell_fields:
        raise ExecutionLedgerError("reserve inherited cell fields are invalid")
    for field in expected_cell_fields:
        if not isinstance(inherited.get(field), (str, int)) or isinstance(inherited.get(field), bool):
            raise ExecutionLedgerError("reserve inherited cell values are invalid")
    if slot["execution"]["row_run_id"] is not None and (
        slot["execution"]["row_run_id"] != value["replacement_run_id"]
    ):
        raise ExecutionLedgerError("reserve row execution identity differs from its assignment")


def _validate_replacements(slots_by_id: Mapping[str, Mapping[str, Any]]) -> None:
    reserve_slots = sorted(
        (slot for slot in slots_by_id.values() if slot["row_type"] == "replacement_only"),
        key=lambda slot: slot["run_order"],
    )
    seen_unassigned = False
    seen_sources: set[str] = set()
    run_ids = {
        slot["execution"]["row_run_id"]
        for slot in slots_by_id.values()
        if slot["execution"]["row_run_id"] is not None
    }
    assignment_ids: set[str] = set()
    for reserve in reserve_slots:
        assignment = reserve["replacement"]
        if assignment is None:
            seen_unassigned = True
            continue
        if seen_unassigned:
            raise ExecutionLedgerError("frozen reserve slots must be activated in order")
        replacement_run_id = assignment["replacement_run_id"]
        if replacement_run_id in assignment_ids:
            raise ExecutionLedgerError("reserve replacement run IDs must be unique")
        assignment_ids.add(replacement_run_id)
        if replacement_run_id in run_ids and reserve["execution"]["row_run_id"] != replacement_run_id:
            raise ExecutionLedgerError("reserve replacement run ID collides with another row")
        source_row_id = assignment["source_row_id"]
        if source_row_id in seen_sources:
            raise ExecutionLedgerError("a failed row cannot consume multiple reserve slots")
        seen_sources.add(source_row_id)
        source = slots_by_id.get(source_row_id)
        if source is None or source["status"] not in ("FAIL", "BLOCKED"):
            raise ExecutionLedgerError("reserve source must be a terminal failed row")
        classification = source["pre_content_classification"]
        if (
            classification is None
            or classification["classification"] != "INFRASTRUCTURE"
            or not classification["reserve_eligible"]
            or classification["row_run_id"] != assignment["source_row_run_id"]
            or source["execution"]["row_run_id"] != assignment["source_row_run_id"]
            or source["content_review_event_sequence"] is None
            or classification["event_sequence"] >= source["content_review_event_sequence"]
        ):
            raise ExecutionLedgerError("reserve source is not pre-content infrastructure-eligible")
        expected_cell = (
            source["replacement"]["inherited_cell"]
            if source["row_type"] == "replacement_only"
            else {
                key: source[key]
                for key in ("block", "arm", "party", "script", "repeat", "matched_cohort")
            }
        )
        if dict(assignment["inherited_cell"]) != expected_cell:
            raise ExecutionLedgerError("reserve replacement does not inherit the exact source cell")


def _validate_matrix_control(
    value: Any,
    slots_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    if not isinstance(value, Mapping) or set(value) != _CONTROL_FIELDS:
        raise ExecutionLedgerError("matrix control fields are invalid")
    audit_events = value.get("audit_events")
    if not isinstance(audit_events, list):
        raise ExecutionLedgerError("matrix audit events must be a list")
    event_by_sequence: dict[int, Mapping[str, Any]] = {}
    classified_rows: set[str] = set()
    reviewed_rows: set[str] = set()
    for expected_sequence, event in enumerate(audit_events, start=1):
        if not isinstance(event, Mapping) or event.get("sequence") != expected_sequence:
            raise ExecutionLedgerError("matrix audit event sequence is invalid")
        event_type = event.get("event")
        if event_type == "pre_content_classification":
            expected_fields = {
                "sequence", "event", "row_id", "row_run_id", "classification", "recorded_at"
            }
            if set(event) != expected_fields:
                raise ExecutionLedgerError("classification audit event fields are invalid")
            row_id = event.get("row_id")
            slot = slots_by_id.get(row_id)
            if slot is None or row_id in classified_rows:
                raise ExecutionLedgerError("classification audit row is unknown or duplicated")
            classified_rows.add(row_id)
            record = slot["pre_content_classification"]
            if (
                record is None
                or record["event_sequence"] != expected_sequence
                or record["row_run_id"] != event.get("row_run_id")
                or record["classification"] != event.get("classification")
                or record["recorded_at"] != event.get("recorded_at")
                or slot["execution"]["row_run_id"] != event.get("row_run_id")
            ):
                raise ExecutionLedgerError("classification audit event disagrees with its row")
        elif event_type == "content_review_started":
            expected_fields = {"sequence", "event", "row_id", "row_run_id", "recorded_at"}
            if set(event) != expected_fields:
                raise ExecutionLedgerError("content-review audit event fields are invalid")
            row_id = event.get("row_id")
            slot = slots_by_id.get(row_id)
            if slot is None or row_id in reviewed_rows:
                raise ExecutionLedgerError("content-review audit row is unknown or duplicated")
            reviewed_rows.add(row_id)
            if (
                slot["content_review_event_sequence"] != expected_sequence
                or slot["content_review_started_at"] != event.get("recorded_at")
                or slot["execution"]["row_run_id"] != event.get("row_run_id")
            ):
                raise ExecutionLedgerError("content-review audit event disagrees with its row")
            record = slot["pre_content_classification"]
            if record is None:
                raise ExecutionLedgerError(
                    "content-review event has no pre-content classification"
                )
            if record["event_sequence"] >= expected_sequence:
                raise ExecutionLedgerError("classification was recorded after content review")
        elif event_type == "owner_review_resume":
            expected_fields = {
                "sequence", "event", "pause_id", "reviewer_label", "note", "recorded_at"
            }
            if set(event) != expected_fields:
                raise ExecutionLedgerError("owner-review audit event fields are invalid")
            _validate_identity_text(event.get("reviewer_label"), "reviewer_label")
            _validate_identity_text(event.get("note"), "owner review note")
            _parse_timestamp(event.get("recorded_at"), "owner review recorded_at")
        else:
            raise ExecutionLedgerError("matrix audit event type is invalid")
        _parse_timestamp(event.get("recorded_at"), "matrix audit event timestamp")
        event_by_sequence[expected_sequence] = event

    for row_id, slot in slots_by_id.items():
        if (slot["pre_content_classification"] is not None) != (row_id in classified_rows):
            raise ExecutionLedgerError("row classification is missing its audit event")
        if (slot["content_review_started_at"] is not None) != (row_id in reviewed_rows):
            raise ExecutionLedgerError("row content-review marker is missing its audit event")

    pauses = value.get("pauses")
    if not isinstance(pauses, list):
        raise ExecutionLedgerError("matrix pause history must be a list")
    pending_pauses = 0
    pause_ids: set[str] = set()

    def infrastructure_streak_through(sequence: int) -> list[int]:
        streak: list[int] = []
        for audit_event in audit_events:
            if audit_event["sequence"] > sequence:
                break
            if audit_event["event"] == "pre_content_classification":
                if audit_event["classification"] == "INFRASTRUCTURE":
                    streak.append(audit_event["sequence"])
                elif audit_event["classification"] == "CONTENT/RESULT":
                    streak = []
            elif audit_event["event"] == "owner_review_resume":
                streak = []
        return streak

    for index, pause in enumerate(pauses, start=1):
        if not isinstance(pause, Mapping) or set(pause) != {
            "pause_id",
            "triggered_at",
            "triggering_classification_sequences",
            "triggering_row_ids",
            "owner_review",
            "resumed_at",
        }:
            raise ExecutionLedgerError("matrix pause record fields are invalid")
        pause_id = "pause-%03d" % index
        if pause.get("pause_id") != pause_id or pause_id in pause_ids:
            raise ExecutionLedgerError("matrix pause identity is invalid")
        pause_ids.add(pause_id)
        _parse_timestamp(pause.get("triggered_at"), "pause triggered_at")
        sequences = pause.get("triggering_classification_sequences")
        row_ids = pause.get("triggering_row_ids")
        if (
            not isinstance(sequences, list)
            or len(sequences) != 3
            or not all(_is_count(item) and item > 0 for item in sequences)
            or not isinstance(row_ids, list)
            or len(row_ids) != 3
        ):
            raise ExecutionLedgerError("matrix pause trigger evidence is invalid")
        trigger_events = [event_by_sequence.get(sequence) for sequence in sequences]
        if (
            any(
                event is None or event.get("event") != "pre_content_classification"
                for event in trigger_events
            )
            or infrastructure_streak_through(sequences[-1]) != sequences
            or any(
                event["classification"] != "INFRASTRUCTURE"
                or event["row_id"] != row_id
                for event, row_id in zip(trigger_events, row_ids)
                if event is not None
            )
            or trigger_events[-1]["recorded_at"] != pause["triggered_at"]
        ):
            raise ExecutionLedgerError("matrix pause is not backed by three consecutive infrastructure failures")
        review = pause.get("owner_review")
        resumed_at = pause.get("resumed_at")
        if review is None:
            pending_pauses += 1
            if resumed_at is not None:
                raise ExecutionLedgerError("unreviewed pause cannot have a resume timestamp")
        else:
            if not isinstance(review, Mapping) or set(review) != {
                "reviewer_label",
                "note",
                "recorded_at",
                "event_sequence",
                "resume_authorized",
            }:
                raise ExecutionLedgerError("owner-review record fields are invalid")
            _validate_identity_text(review.get("reviewer_label"), "reviewer_label")
            _validate_identity_text(review.get("note"), "owner review note")
            _parse_timestamp(review.get("recorded_at"), "owner review recorded_at")
            if (
                review.get("resume_authorized") is not True
                or review.get("event_sequence") not in event_by_sequence
                or review.get("event_sequence") <= sequences[-1]
                or resumed_at != review.get("recorded_at")
            ):
                raise ExecutionLedgerError("owner review does not authorize a valid resume")
            review_event = event_by_sequence[review["event_sequence"]]
            if (
                review_event.get("event") != "owner_review_resume"
                or review_event.get("pause_id") != pause_id
                or review_event.get("reviewer_label") != review["reviewer_label"]
                or review_event.get("note") != review["note"]
                or review_event.get("recorded_at") != review["recorded_at"]
            ):
                raise ExecutionLedgerError("owner-review entry disagrees with its audit event")
    if pending_pauses > 1 or type(value.get("paused")) is not bool:
        raise ExecutionLedgerError("matrix pause state is invalid")
    if value["paused"] != (pending_pauses == 1):
        raise ExecutionLedgerError("matrix pause state disagrees with owner review history")

    expected_streak: list[int] = []
    for event in audit_events:
        if event["event"] == "pre_content_classification":
            if event["classification"] == "INFRASTRUCTURE":
                expected_streak.append(event["sequence"])
            elif event["classification"] == "CONTENT/RESULT":
                expected_streak = []
        elif event["event"] == "owner_review_resume":
            expected_streak = []
    streak = value.get("infrastructure_failure_streak")
    if not isinstance(streak, list) or streak != expected_streak:
        raise ExecutionLedgerError("infrastructure failure streak is inconsistent")


def _validate_bookings(bookings: list[Any]) -> None:
    seen_ids: set[str] = set()
    parsed_windows: list[tuple[datetime, datetime]] = []
    active_count = 0
    for booking in bookings:
        if not isinstance(booking, Mapping) or set(booking) != _BOOKING_FIELDS:
            raise ExecutionLedgerError("booking record fields are invalid")
        booking_id = booking.get("booking_id")
        _validate_token(booking_id, "booking_id")
        if booking_id in seen_ids:
            raise ExecutionLedgerError("booking IDs must be unique")
        seen_ids.add(booking_id)
        _validate_identity_text(booking.get("holder"), "booking holder")
        starts_at = _parse_timestamp(booking.get("window_start"), "window_start")
        ends_at = _parse_timestamp(booking.get("window_end"), "window_end")
        if starts_at >= ends_at:
            raise ExecutionLedgerError("booking window_start must precede window_end")
        if type(booking.get("network_non_overlap_confirmed")) is not bool:
            raise ExecutionLedgerError("Network non-overlap confirmation must be boolean")
        _parse_timestamp(booking.get("recorded_at"), "recorded_at")
        actual_start = booking.get("actual_start_timestamp")
        if actual_start is not None:
            actual_start_time = _parse_timestamp(actual_start, "actual_start_timestamp")
            if actual_start_time < starts_at or actual_start_time >= ends_at:
                raise ExecutionLedgerError("booking actual start is outside its window")
            if actual_start_time < _parse_timestamp(booking.get("recorded_at"), "recorded_at"):
                raise ExecutionLedgerError("booking actual start precedes booking record")
        release_value = booking.get("release_timestamp")
        if release_value is None:
            active_count += 1
            if booking.get("booked_window_elapsed_seconds") is not None:
                raise ExecutionLedgerError("unreleased booking cannot have elapsed duration")
        else:
            release_time = _parse_timestamp(release_value, "release_timestamp")
            if release_time < starts_at:
                raise ExecutionLedgerError("booking release precedes its window")
            if actual_start is not None and release_time < actual_start_time:
                raise ExecutionLedgerError("booking release precedes its actual start")
        elapsed = booking.get("booked_window_elapsed_seconds")
        if elapsed is not None and not _is_seconds(elapsed):
            raise ExecutionLedgerError("booked-window elapsed duration is invalid")
        if booking.get("release_timestamp") is not None:
            expected_elapsed = (
                None
                if actual_start is None
                else max(
                    0.0,
                    (
                        _parse_timestamp(release_value, "release_timestamp")
                        - actual_start_time
                    ).total_seconds(),
                )
            )
            if elapsed != expected_elapsed:
                raise ExecutionLedgerError("booked-window elapsed duration is inconsistent")
        parsed_windows.append((starts_at, ends_at))
    if active_count > 1:
        raise ExecutionLedgerError("ledger contains multiple unreleased bookings")
    for index, (starts_at, ends_at) in enumerate(parsed_windows):
        for prior_start, prior_end in parsed_windows[:index]:
            if starts_at < prior_end and prior_start < ends_at:
                raise ExecutionLedgerError("SP3 booking windows must not overlap")


def _ensure_no_unreleased_booking(ledger: Mapping[str, Any]) -> None:
    if any(item["release_timestamp"] is None for item in ledger["bookings"]):
        raise ExecutionLedgerError("release the existing booking before recording another")


def _run_paths(
    run_id: str, ledger_root: str | Path
) -> tuple[Path, Path, Path, Path]:
    root = _validate_ledger_root(ledger_root)
    relative_directory = root / run_id
    relative_ledger = relative_directory / LEDGER_FILENAME
    absolute_directory = PROJECT_ROOT / relative_directory
    absolute_ledger = PROJECT_ROOT / relative_ledger
    _reject_symlink_components(absolute_directory)
    _ensure_beneath_tmp(absolute_directory)
    return relative_directory, relative_ledger, absolute_directory, absolute_ledger


def _validate_ledger_root(ledger_root: str | Path) -> Path:
    raw_text = str(ledger_root)
    if "\\" in raw_text:
        raise ExecutionLedgerError("ledger root must use a project-relative tmp path")
    raw = Path(ledger_root)
    segments = raw_text.split("/")
    if (
        raw.is_absolute()
        or not raw.parts
        or segments[0] != "tmp"
        or any(part in ("", ".", "..") for part in segments)
        or ".." in raw.parts
    ):
        raise ExecutionLedgerError("ledger root must be a project-relative path beneath tmp/")
    return raw


def _read_ledger(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ExecutionLedgerError("matrix ledger is missing or unsafe")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExecutionLedgerError("matrix ledger is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExecutionLedgerError("matrix ledger must be an object")
    return value


def _write_ledger(relative_path: Path, absolute_path: Path, ledger: Mapping[str, Any]) -> None:
    del relative_path
    _reject_symlink_components(absolute_path)
    _ensure_beneath_tmp(absolute_path)
    from utils.file_operations import safe_write_json

    try:
        wrote = safe_write_json(
            str(absolute_path),
            dict(ledger),
            create_backup=False,
            acquire_lock=True,
            json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
        )
    except Exception as exc:
        raise ExecutionLedgerError("atomic matrix ledger write failed") from exc
    if not wrote:
        raise ExecutionLedgerError("atomic matrix ledger write failed")


def _ensure_tmp_root() -> None:
    tmp_root = PROJECT_ROOT / "tmp"
    if tmp_root.is_symlink() or not tmp_root.is_dir():
        raise ExecutionLedgerError("project tmp/ must exist and must not be a symlink")


def _ensure_beneath_tmp(path: Path) -> None:
    _ensure_tmp_root()
    try:
        path.resolve(strict=False).relative_to((PROJECT_ROOT / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExecutionLedgerError("matrix ledger path escaped project tmp/") from exc


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                raise ExecutionLedgerError("matrix ledger paths must not traverse symlinks")
        except OSError as exc:
            raise ExecutionLedgerError("matrix ledger path cannot be inspected") from exc


def _validate_tmp_reference(value: Any, label: str) -> None:
    if not isinstance(value, str) or "\\" in value:
        raise ExecutionLedgerError("%s must be a project-relative tmp path" % label)
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or parsed.parts[0] != "tmp"
        or ".." in parsed.parts
        or any(part in ("", ".") for part in value.split("/"))
    ):
        raise ExecutionLedgerError("%s must be beneath project tmp/" % label)


def _validate_token(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value) or value in (".", ".."):
        raise ExecutionLedgerError("%s must be a safe path token" % label)


def _validate_identity_text(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ExecutionLedgerError("%s must be non-empty text without control characters" % label)


def _coerce_now(value: datetime | None) -> datetime:
    result = datetime.now(timezone.utc) if value is None else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ExecutionLedgerError("timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ExecutionLedgerError("%s must be an ISO-8601 timestamp with a timezone" % label)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecutionLedgerError("%s must be an ISO-8601 timestamp with a timezone" % label) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExecutionLedgerError("%s must include a timezone" % label)
    return parsed.astimezone(timezone.utc)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value")
