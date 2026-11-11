# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fixed-root, durable Study 3 attempt and actual-cost ledger.

This module has no provider, transport, or credential integration. A successful
``reserve`` returns only after its append has been fsynced. The allocation path
is independent of any run ID or caller-selected run root.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
from typing import Any, Iterator

from . import protocol
from . import sizing


PREP_ROOT_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/"
    "llm-staging-study3-prep"
)
LEDGER_ROOT_RELATIVE = PREP_ROOT_RELATIVE + "/durable-ledger"
DEFAULT_LEDGER_ROOT = protocol.REPO_ROOT / LEDGER_ROOT_RELATIVE
LEDGER_NAME = "study3-attempt-ledger.jsonl"
LOCK_NAME = ".study3-attempt-ledger.lock"
COMPLETION_MARKER_NAME = ".study3-completion-pending"
LEDGER_SCHEMA = "neq.llm_staging_study3_durable_ledger.v1"
LEDGER_SCHEMA_VERSION = 1
MAX_LEDGER_BYTES = 64 * 1024
HARD_CEILING_USD = Decimal("0.05")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COST_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?$")
_GENERATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,127}$")
_ROOT_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class Study3LedgerError(RuntimeError):
    """A metadata-only, fail-closed ledger refusal."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Study3Reservation:
    """An in-process handle for exactly one durable pending reservation."""

    study_id: str
    manifest_sha256: str
    attempt_number: int
    scene_id: str
    request_sha256: str
    reservation_sha256: str
    _token: str = field(repr=False, compare=False)


@dataclass(frozen=True)
class Study3Completion:
    """Metadata-only result of reconciling one reserved attempt."""

    attempt_number: int
    scene_id: str
    outcome: str
    actual_cost_status: str
    actual_cost_usd: str | None
    stop_study: bool


@dataclass(frozen=True)
class _Pricing:
    manifest_sha256: str
    sizing_report_sha256: str
    request_hashes: tuple[str, ...]
    conservative_costs: tuple[Decimal, ...]


@dataclass(frozen=True)
class _LedgerState:
    records: tuple[dict[str, Any], ...]
    reservations: tuple[dict[str, Any], ...]
    results: tuple[dict[str, Any], ...]
    pending: dict[str, Any] | None
    pending_sha256: str | None
    stopped: bool
    unresolved_cost: bool
    actual_total: Decimal
    receipt_ids: frozenset[str]


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


class Study3Ledger:
    """Operate on the one fixed Study 3 ledger, never on a run-scoped ledger."""

    def __init__(self) -> None:
        self._root = DEFAULT_LEDGER_ROOT
        self._root_parts = _validate_root_path(self._root)
        self._synthetic = False
        self._thread_lock = _thread_lock(self._root)
        self._poisoned = False
        self._active_reservation: Study3Reservation | None = None

    @classmethod
    def _for_synthetic_test(cls, root: Path | str) -> "Study3Ledger":
        """Return a fixture-only ledger rooted at a synthetic Study 3 path."""

        instance = cls()
        candidate = _coerce_root_path(root)
        if candidate == DEFAULT_LEDGER_ROOT or not candidate.name.startswith(
            "synthetic-"
        ):
            raise Study3LedgerError("LEDGER_ROOT_INVALID")
        instance._root = candidate
        instance._root_parts = _validate_root_path(candidate)
        instance._synthetic = True
        instance._thread_lock = _thread_lock(candidate)
        return instance

    @property
    def root(self) -> Path:
        """Return the fixed or synthetic root without touching the filesystem."""

        return self._root

    @property
    def path(self) -> Path:
        """Return the ledger filename without touching the filesystem."""

        return self._root / LEDGER_NAME

    def initialize(self) -> None:
        """Create the unique ledger header; existing roots are never reset."""

        self._ensure_usable()
        pricing = _load_pinned_pricing()
        parent_fd: int | None = None
        root_fd: int | None = None
        lock_fd: int | None = None
        ledger_fd: int | None = None
        try:
            parent_fd, leaf = _open_root_parent(self._root_parts, create=True)
            try:
                os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise Study3LedgerError("LEDGER_ALREADY_INITIALIZED")

            try:
                os.mkdir(leaf, 0o700, dir_fd=parent_fd)
                _fsync_directory(parent_fd)
            except OSError:
                raise Study3LedgerError("LEDGER_ROOT_CREATE_FAILED") from None

            root_fd = _open_child_directory(parent_fd, leaf)
            os.fchmod(root_fd, 0o700)
            if os.listdir(root_fd):
                raise Study3LedgerError("LEDGER_DUPLICATE_ARTIFACT")

            lock_fd = os.open(
                LOCK_NAME,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
                0o600,
                dir_fd=root_fd,
            )
            os.fchmod(lock_fd, 0o600)
            _verify_named_regular_file(root_fd, LOCK_NAME, lock_fd)
            os.fsync(lock_fd)
            _fsync_directory(root_fd)

            ledger_fd = os.open(
                LEDGER_NAME,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
                0o600,
                dir_fd=root_fd,
            )
            os.fchmod(ledger_fd, 0o600)
            _verify_named_regular_file(root_fd, LEDGER_NAME, ledger_fd)
            _append_record(ledger_fd, _header_payload(pricing), None)
            os.fsync(ledger_fd)
            _fsync_directory(root_fd)
        except Study3LedgerError:
            raise
        except OSError:
            self._poisoned = True
            raise Study3LedgerError("LEDGER_INITIALIZATION_FAILED") from None
        finally:
            for descriptor in (ledger_fd, lock_fd, root_fd, parent_fd):
                if descriptor is not None:
                    os.close(descriptor)

    def reserve(self, *, scene_id: object, request_sha256: object) -> Study3Reservation:
        """Durably append the next exact scene reservation before returning."""

        self._ensure_usable()
        pricing = _load_pinned_pricing()
        if type(scene_id) is not str or scene_id not in protocol.SCENE_ORDER:
            raise Study3LedgerError("RESERVATION_IDENTITY_INVALID")
        if type(request_sha256) is not str or _SHA256_RE.fullmatch(request_sha256) is None:
            raise Study3LedgerError("RESERVATION_IDENTITY_INVALID")

        with self._locked_existing() as (_root_fd, ledger_fd):
            state = _read_state(ledger_fd, pricing)
            if state.pending is not None:
                raise Study3LedgerError("LEDGER_PENDING_RESERVATION")
            if state.unresolved_cost:
                raise Study3LedgerError("LEDGER_ACTUAL_COST_UNRESOLVED")
            if state.stopped:
                raise Study3LedgerError("LEDGER_STUDY_STOPPED")

            attempt_number = len(state.reservations) + 1
            if attempt_number > len(protocol.SCENE_ORDER):
                raise Study3LedgerError("LEDGER_ATTEMPT_CAP_EXHAUSTED")
            scene_index = attempt_number - 1
            if (
                scene_id != protocol.SCENE_ORDER[scene_index]
                or request_sha256 != pricing.request_hashes[scene_index]
            ):
                raise Study3LedgerError("SCENE_ORDER_OR_REQUEST_MISMATCH")

            remaining_cost = sum(
                pricing.conservative_costs[scene_index:], Decimal(0)
            )
            if state.actual_total + remaining_cost >= HARD_CEILING_USD:
                raise Study3LedgerError("PROJECTED_COST_REACHES_HARD_CEILING")

            payload = {
                "event": "reservation",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": protocol.STUDY_ID,
                "manifest_sha256": pricing.manifest_sha256,
                "attempt_number": attempt_number,
                "scene_id": scene_id,
                "request_sha256": request_sha256,
                "conservative_cost_usd_estimate": str(
                    pricing.conservative_costs[scene_index]
                ),
            }
            try:
                reservation_sha256 = _append_record(
                    ledger_fd, payload, state.records[-1]["record_sha256"]
                )
                os.fsync(ledger_fd)
            except (OSError, Study3LedgerError):
                self._poisoned = True
                raise Study3LedgerError("LEDGER_DURABILITY_UNCERTAIN") from None

            reservation = Study3Reservation(
                study_id=protocol.STUDY_ID,
                manifest_sha256=pricing.manifest_sha256,
                attempt_number=attempt_number,
                scene_id=scene_id,
                request_sha256=request_sha256,
                reservation_sha256=reservation_sha256,
                _token=secrets.token_hex(32),
            )
            self._active_reservation = reservation
            return reservation

    def complete(
        self,
        reservation: object,
        *,
        outcome: object,
        reported_cost_usd: object = None,
        cost_receipt: object = None,
    ) -> Study3Completion:
        """Persist a result and receipt, or durably stop on unresolved accounting."""

        self._ensure_usable()
        if (
            type(reservation) is not Study3Reservation
            or self._active_reservation is None
            or reservation._token != self._active_reservation._token
            or reservation != self._active_reservation
        ):
            raise Study3LedgerError("RESERVATION_HANDLE_INVALID")
        if type(outcome) is not str or outcome not in {
            "ACCEPTED",
            "CONTRACT_FAILURE",
            "STOPPED",
        }:
            raise Study3LedgerError("RESULT_OUTCOME_INVALID")

        pricing = _load_pinned_pricing()
        with self._locked_existing() as (root_fd, ledger_fd):
            state = _read_state(ledger_fd, pricing)
            pending = state.pending
            if (
                pending is None
                or pending["attempt_number"] != reservation.attempt_number
                or pending["scene_id"] != reservation.scene_id
                or pending["request_sha256"] != reservation.request_sha256
                or pending["manifest_sha256"] != reservation.manifest_sha256
                or state.pending_sha256 != reservation.reservation_sha256
            ):
                raise Study3LedgerError("LEDGER_PENDING_RESERVATION_MISMATCH")

            receipt: dict[str, Any] | None = None
            actual_cost: str | None = None
            actual_status = "UNRESOLVED"
            if cost_receipt is None or reported_cost_usd is None:
                reason = "COST_RECEIPT_MISSING"
            else:
                try:
                    receipt, receipt_cost = _validate_cost_receipt(
                        cost_receipt, pending
                    )
                except Study3LedgerError:
                    reason = "COST_RECEIPT_INVALID"
                else:
                    reported_cost = _parse_cost(reported_cost_usd)
                    if reported_cost is None:
                        reason = "COST_RECEIPT_INVALID"
                    elif reported_cost != receipt_cost:
                        reason = "COST_RECEIPT_MISMATCH"
                    elif receipt["receipt_id"] in state.receipt_ids:
                        reason = "COST_RECEIPT_DUPLICATE"
                        receipt = None
                    else:
                        reason = None
                        actual_status = "RECONCILED"
                        actual_cost = receipt["cost_usd"]

            next_scene_index = reservation.attempt_number
            remaining_estimate = sum(
                pricing.conservative_costs[next_scene_index:], Decimal(0)
            )
            if actual_status == "RECONCILED":
                projected = state.actual_total + receipt_cost + remaining_estimate
                budget_stop = projected >= HARD_CEILING_USD
            else:
                budget_stop = False
            stop_study = (
                outcome == "STOPPED"
                or actual_status != "RECONCILED"
                or budget_stop
            )
            if actual_status != "RECONCILED":
                receipt = None
            result_payload = {
                "event": "result",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": protocol.STUDY_ID,
                "manifest_sha256": pricing.manifest_sha256,
                "attempt_number": reservation.attempt_number,
                "scene_id": reservation.scene_id,
                "request_sha256": reservation.request_sha256,
                "outcome": outcome,
                "stop_study": stop_study,
                "actual_cost_status": actual_status,
                "actual_cost_usd": actual_cost,
                "cost_receipt": receipt,
                "reason_code": reason,
            }

            marker_fd: int | None = None
            try:
                marker_fd = os.open(
                    COMPLETION_MARKER_NAME,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
                    0o600,
                    dir_fd=root_fd,
                )
                os.fchmod(marker_fd, 0o600)
                _write_all(marker_fd, b"STUDY3_COMPLETION_PENDING\n")
                _verify_named_regular_file(root_fd, COMPLETION_MARKER_NAME, marker_fd)
                os.fsync(marker_fd)
                _fsync_directory(root_fd)
                _append_record(
                    ledger_fd, result_payload, state.records[-1]["record_sha256"]
                )
                os.fsync(ledger_fd)
                _verify_named_regular_file(
                    root_fd, COMPLETION_MARKER_NAME, marker_fd
                )
                os.unlink(COMPLETION_MARKER_NAME, dir_fd=root_fd)
                _fsync_directory(root_fd)
            except (OSError, Study3LedgerError):
                self._poisoned = True
                raise Study3LedgerError("LEDGER_COMPLETION_DURABILITY_UNCERTAIN") from None
            finally:
                if marker_fd is not None:
                    os.close(marker_fd)

            self._active_reservation = None
            return Study3Completion(
                attempt_number=reservation.attempt_number,
                scene_id=reservation.scene_id,
                outcome=outcome,
                actual_cost_status=actual_status,
                actual_cost_usd=actual_cost,
                stop_study=stop_study,
            )

    @contextmanager
    def _locked_existing(self) -> Iterator[tuple[int, int]]:
        """Yield root and ledger descriptors while holding thread and file locks."""

        self._ensure_usable()
        root_fd: int | None = None
        lock_fd: int | None = None
        ledger_fd: int | None = None
        self._thread_lock.acquire()
        try:
            root_fd = _open_root_directory(self._root_parts)
            names = set(os.listdir(root_fd))
            allowed = {LOCK_NAME, LEDGER_NAME, COMPLETION_MARKER_NAME}
            if not names.issubset(allowed) or not {LOCK_NAME, LEDGER_NAME}.issubset(
                names
            ):
                raise Study3LedgerError("LEDGER_DUPLICATE_OR_MISSING_ARTIFACT")
            if COMPLETION_MARKER_NAME in names:
                raise Study3LedgerError("LEDGER_COMPLETION_UNCERTAIN")

            lock_fd = os.open(
                LOCK_NAME, os.O_RDWR | _FILE_NOFOLLOW, dir_fd=root_fd
            )
            _verify_named_regular_file(root_fd, LOCK_NAME, lock_fd)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            _verify_named_regular_file(root_fd, LOCK_NAME, lock_fd)

            names_after_lock = set(os.listdir(root_fd))
            if names_after_lock != names:
                raise Study3LedgerError("LEDGER_DUPLICATE_OR_MISSING_ARTIFACT")
            ledger_fd = os.open(
                LEDGER_NAME,
                os.O_RDWR | os.O_APPEND | _FILE_NOFOLLOW,
                dir_fd=root_fd,
            )
            _verify_named_regular_file(root_fd, LEDGER_NAME, ledger_fd)
            yield root_fd, ledger_fd
        except Study3LedgerError:
            raise
        except OSError:
            raise Study3LedgerError("LEDGER_MISSING_OR_UNSAFE") from None
        finally:
            if ledger_fd is not None:
                os.close(ledger_fd)
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
            if root_fd is not None:
                os.close(root_fd)
            self._thread_lock.release()

    def _ensure_usable(self) -> None:
        if self._poisoned:
            raise Study3LedgerError("LEDGER_INSTANCE_POISONED")


def _load_pinned_pricing() -> _Pricing:
    """Rebuild and verify request and cost estimates from frozen local inputs."""

    try:
        manifest = protocol._load_manifest()
        manifest_sha256 = protocol.STUDY3_MANIFEST_SHA256
        sizing_record = manifest["artifacts"]["sizing_report"]
        if (
            type(sizing_record) is not dict
            or sizing_record.get("path")
            != protocol.PROTOCOL_RELATIVE + "/sizing-report.json"
        ):
            raise ValueError
        sizing_bytes = protocol._safe_project_read(sizing_record["path"])
        sizing_sha256 = hashlib.sha256(sizing_bytes).hexdigest()
        if sizing_sha256 != sizing_record.get("sha256"):
            raise ValueError
        frozen_report = _parse_json_object(sizing_bytes)
        rebuilt_report = sizing.build_sizing_report()
        if _canonical_bytes(frozen_report) != _canonical_bytes(rebuilt_report):
            raise ValueError
        if (
            frozen_report.get("status") != "ESTIMATE"
            or frozen_report.get("study_id") != protocol.STUDY_ID
            or frozen_report.get("scene_order") != list(protocol.SCENE_ORDER)
            or frozen_report.get("hard_ceiling_usd") != str(HARD_CEILING_USD)
        ):
            raise ValueError
        rows = frozen_report.get("scenes")
        if type(rows) is not list or len(rows) != len(protocol.SCENE_ORDER):
            raise ValueError
        request_hashes: list[str] = []
        conservative_costs: list[Decimal] = []
        for scene_id, row in zip(protocol.SCENE_ORDER, rows):
            if type(row) is not dict or row.get("scene_id") != scene_id:
                raise ValueError
            request_sha256 = row.get("request_sha256")
            if (
                type(request_sha256) is not str
                or _SHA256_RE.fullmatch(request_sha256) is None
            ):
                raise ValueError
            cost_string = row.get("conservative_cost_usd_estimate")
            amount = _parse_cost(cost_string)
            if amount is None:
                raise ValueError
            request_hashes.append(request_sha256)
            conservative_costs.append(amount)
        if sum(conservative_costs, Decimal(0)) >= HARD_CEILING_USD:
            raise ValueError
        if (
            type(frozen_report.get("conservative_total_usd_estimate")) is not str
            or _parse_cost(frozen_report["conservative_total_usd_estimate"])
            != sum(conservative_costs, Decimal(0))
        ):
            raise ValueError
        return _Pricing(
            manifest_sha256=manifest_sha256,
            sizing_report_sha256=sizing_sha256,
            request_hashes=tuple(request_hashes),
            conservative_costs=tuple(conservative_costs),
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError, sizing.SizingBlocked):
        raise Study3LedgerError("SIZING_OR_MANIFEST_BINDING_INVALID") from None


def _header_payload(pricing: _Pricing) -> dict[str, Any]:
    return {
        "event": "header",
        "schema_version": LEDGER_SCHEMA_VERSION,
        "schema": LEDGER_SCHEMA,
        "study_id": protocol.STUDY_ID,
        "allocation_scope": "studywide",
        "manifest_sha256": pricing.manifest_sha256,
        "attempt_cap": len(protocol.SCENE_ORDER),
        "scene_order": list(protocol.SCENE_ORDER),
        "hard_ceiling_usd": str(HARD_CEILING_USD),
        "sizing_report_sha256": pricing.sizing_report_sha256,
        "scene_bindings": [
            {
                "scene_id": scene_id,
                "request_sha256": request_sha256,
                "conservative_cost_usd_estimate": str(cost),
            }
            for scene_id, request_sha256, cost in zip(
                protocol.SCENE_ORDER,
                pricing.request_hashes,
                pricing.conservative_costs,
            )
        ],
    }


def _read_state(descriptor: int, pricing: _Pricing) -> _LedgerState:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > MAX_LEDGER_BYTES
    ):
        raise Study3LedgerError("LEDGER_EMPTY_OR_OVERSIZED")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = metadata.st_size
    while remaining:
        chunk = os.read(descriptor, min(remaining, 65536))
        if not chunk:
            raise Study3LedgerError("LEDGER_TRUNCATED")
        chunks.append(chunk)
        remaining -= len(chunk)
    contents = b"".join(chunks)
    if not contents.endswith(b"\n"):
        raise Study3LedgerError("LEDGER_TRUNCATED")

    try:
        records = tuple(_parse_record(line) for line in contents.splitlines())
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError, OverflowError):
        raise Study3LedgerError("LEDGER_CORRUPT") from None
    if not records or len(records) > 1 + 2 * len(protocol.SCENE_ORDER):
        raise Study3LedgerError("LEDGER_CORRUPT")

    prior_hash: str | None = None
    payloads: list[dict[str, Any]] = []
    for record in records:
        if set(record) < {"previous_sha256", "record_sha256"}:
            raise Study3LedgerError("LEDGER_HASH_CHAIN_INVALID")
        record_hash = record.get("record_sha256")
        if (
            type(record_hash) is not str
            or _SHA256_RE.fullmatch(record_hash) is None
            or record.get("previous_sha256") != prior_hash
        ):
            raise Study3LedgerError("LEDGER_HASH_CHAIN_INVALID")
        unhashed = dict(record)
        del unhashed["record_sha256"]
        if hashlib.sha256(_canonical_bytes(unhashed)).hexdigest() != record_hash:
            raise Study3LedgerError("LEDGER_HASH_CHAIN_INVALID")
        payload = dict(unhashed)
        del payload["previous_sha256"]
        payloads.append(payload)
        prior_hash = record_hash

    if _canonical_bytes(payloads[0]) != _canonical_bytes(_header_payload(pricing)):
        raise Study3LedgerError("LEDGER_HEADER_BINDING_MISMATCH")

    reservations: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    pending_sha256: str | None = None
    stopped = False
    unresolved_cost = False
    actual_total = Decimal(0)
    receipt_ids: set[str] = set()

    for index, payload in enumerate(payloads[1:], start=1):
        event = payload.get("event")
        if event == "reservation":
            if pending is not None or stopped:
                raise Study3LedgerError("LEDGER_RESERVATION_SEQUENCE_INVALID")
            attempt = len(reservations) + 1
            if attempt > len(protocol.SCENE_ORDER):
                raise Study3LedgerError("LEDGER_ATTEMPT_CAP_EXCEEDED")
            scene_index = attempt - 1
            expected = {
                "event": "reservation",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": protocol.STUDY_ID,
                "manifest_sha256": pricing.manifest_sha256,
                "attempt_number": attempt,
                "scene_id": protocol.SCENE_ORDER[scene_index],
                "request_sha256": pricing.request_hashes[scene_index],
                "conservative_cost_usd_estimate": str(
                    pricing.conservative_costs[scene_index]
                ),
            }
            if set(payload) != set(expected) or _canonical_bytes(payload) != _canonical_bytes(expected):
                raise Study3LedgerError("LEDGER_RESERVATION_BINDING_INVALID")
            remaining_cost = sum(
                pricing.conservative_costs[scene_index:], Decimal(0)
            )
            if actual_total + remaining_cost >= HARD_CEILING_USD:
                raise Study3LedgerError("LEDGER_RESERVATION_BUDGET_INVALID")
            pending = payload
            pending_sha256 = records[index]["record_sha256"]
            reservations.append(payload)
            continue

        if event != "result" or pending is None or stopped:
            raise Study3LedgerError("LEDGER_EVENT_SEQUENCE_INVALID")
        expected_fields = {
            "event",
            "schema_version",
            "study_id",
            "manifest_sha256",
            "attempt_number",
            "scene_id",
            "request_sha256",
            "outcome",
            "stop_study",
            "actual_cost_status",
            "actual_cost_usd",
            "cost_receipt",
            "reason_code",
        }
        if (
            set(payload) != expected_fields
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != LEDGER_SCHEMA_VERSION
            or payload.get("study_id") != protocol.STUDY_ID
            or payload.get("manifest_sha256") != pricing.manifest_sha256
            or type(payload.get("attempt_number")) is not int
            or payload.get("attempt_number") != pending["attempt_number"]
            or payload.get("scene_id") != pending["scene_id"]
            or payload.get("request_sha256") != pending["request_sha256"]
            or type(payload.get("outcome")) is not str
            or payload.get("outcome")
            not in {"ACCEPTED", "CONTRACT_FAILURE", "STOPPED"}
            or type(payload.get("stop_study")) is not bool
        ):
            raise Study3LedgerError("LEDGER_RESULT_BINDING_INVALID")

        status = payload.get("actual_cost_status")
        if status == "RECONCILED":
            receipt, receipt_cost = _validate_cost_receipt(
                payload.get("cost_receipt"), pending
            )
            actual_cost = payload.get("actual_cost_usd")
            parsed_actual = _parse_cost(actual_cost)
            if parsed_actual is None or parsed_actual != receipt_cost:
                raise Study3LedgerError("LEDGER_COST_RECEIPT_MISMATCH")
            receipt_id = receipt["receipt_id"]
            if receipt_id in receipt_ids:
                raise Study3LedgerError("LEDGER_COST_RECEIPT_DUPLICATE")
            next_index = pending["attempt_number"]
            remaining_estimate = sum(
                pricing.conservative_costs[next_index:], Decimal(0)
            )
            new_total = actual_total + receipt_cost
            expected_stop = (
                payload["outcome"] == "STOPPED"
                or new_total + remaining_estimate >= HARD_CEILING_USD
            )
            if (
                payload.get("reason_code") is not None
                or payload["stop_study"] is not expected_stop
            ):
                raise Study3LedgerError("LEDGER_RESULT_STOP_STATE_INVALID")
            actual_total = new_total
            receipt_ids.add(receipt_id)
        elif status == "UNRESOLVED":
            if (
                payload.get("actual_cost_usd") is not None
                or payload.get("cost_receipt") is not None
                or payload.get("stop_study") is not True
                or type(payload.get("reason_code")) is not str
                or payload.get("reason_code")
                not in {
                    "COST_RECEIPT_MISSING",
                    "COST_RECEIPT_INVALID",
                    "COST_RECEIPT_MISMATCH",
                    "COST_RECEIPT_DUPLICATE",
                }
            ):
                raise Study3LedgerError("LEDGER_COST_ACCOUNTING_INVALID")
            unresolved_cost = True
        else:
            raise Study3LedgerError("LEDGER_COST_ACCOUNTING_INVALID")

        results.append(payload)
        stopped = payload["stop_study"]
        pending = None
        pending_sha256 = None

    return _LedgerState(
        records=records,
        reservations=tuple(reservations),
        results=tuple(results),
        pending=pending,
        pending_sha256=pending_sha256,
        stopped=stopped,
        unresolved_cost=unresolved_cost,
        actual_total=actual_total,
        receipt_ids=frozenset(receipt_ids),
    )


def _validate_cost_receipt(
    value: object, reservation: dict[str, Any]
) -> tuple[dict[str, Any], Decimal]:
    fields = {
        "receipt_id",
        "study_id",
        "manifest_sha256",
        "scene_id",
        "attempt_number",
        "request_sha256",
        "response_sha256",
        "returned_model_id",
        "upstream_provider",
        "generation_id",
        "cost_usd",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
    }
    if type(value) is not dict or set(value) != fields:
        raise Study3LedgerError("COST_RECEIPT_INVALID")
    if (
        type(value.get("receipt_id")) is not str
        or type(value.get("study_id")) is not str
        or type(value.get("manifest_sha256")) is not str
        or type(value.get("scene_id")) is not str
        or type(value.get("request_sha256")) is not str
        or type(value.get("response_sha256")) is not str
        or type(value.get("returned_model_id")) is not str
        or type(value.get("upstream_provider")) is not str
        or type(value.get("generation_id")) is not str
        or type(value.get("cost_usd")) is not str
        or value.get("study_id") != protocol.STUDY_ID
        or value.get("manifest_sha256") != reservation["manifest_sha256"]
        or value.get("scene_id") != reservation["scene_id"]
        or type(value.get("attempt_number")) is not int
        or value.get("attempt_number") != reservation["attempt_number"]
        or value.get("request_sha256") != reservation["request_sha256"]
        or type(value.get("response_sha256")) is not str
        or _SHA256_RE.fullmatch(value["response_sha256"]) is None
        or value.get("returned_model_id") != protocol.MODEL_ID
        or type(value.get("upstream_provider")) is not str
        or _PROVIDER_RE.fullmatch(value["upstream_provider"]) is None
        or value["upstream_provider"].casefold() in {"unknown", "none", "n/a", "unset"}
        or type(value.get("generation_id")) is not str
        or _GENERATION_ID_RE.fullmatch(value["generation_id"]) is None
        or value.get("receipt_id") != value.get("generation_id")
    ):
        raise Study3LedgerError("COST_RECEIPT_BINDING_MISMATCH")
    for field_name in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
        if type(value.get(field_name)) is not int or value[field_name] < 0:
            raise Study3LedgerError("COST_RECEIPT_USAGE_INVALID")
    if value["reasoning_tokens"] > value["completion_tokens"]:
        raise Study3LedgerError("COST_RECEIPT_USAGE_INVALID")
    amount = _parse_cost(value.get("cost_usd"))
    if amount is None:
        raise Study3LedgerError("COST_RECEIPT_AMOUNT_INVALID")
    return {key: value[key] for key in sorted(fields)}, amount


def _parse_cost(value: object) -> Decimal | None:
    if type(value) is not str or len(value) > 64 or _COST_RE.fullmatch(value) is None:
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError):
        raise Study3LedgerError("SIZING_REPORT_INVALID") from None
    if type(value) is not dict:
        raise Study3LedgerError("SIZING_REPORT_INVALID")
    return value


def _parse_record(raw: bytes) -> dict[str, Any]:
    value = json.loads(
        raw.decode("ascii"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )
    if type(value) is not dict:
        raise ValueError("record must be an object")
    if _canonical_bytes(value) != raw:
        raise ValueError("record must be canonical")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("non-finite value")


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        raise Study3LedgerError("LEDGER_RECORD_INVALID") from None


def _append_record(
    descriptor: int, payload: dict[str, Any], previous_sha256: str | None
) -> str:
    record = dict(payload)
    record["previous_sha256"] = previous_sha256
    digest = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    record["record_sha256"] = digest
    contents = _canonical_bytes(record) + b"\n"
    if os.fstat(descriptor).st_size + len(contents) > MAX_LEDGER_BYTES:
        raise Study3LedgerError("LEDGER_SIZE_LIMIT")
    _write_all(descriptor, contents)
    return digest


def _write_all(descriptor: int, contents: bytes) -> None:
    offset = 0
    while offset < len(contents):
        written = os.write(descriptor, contents[offset:])
        if written <= 0:
            raise OSError("short ledger write")
        offset += written


def _coerce_root_path(value: Path | str) -> Path:
    try:
        raw = os.fspath(value)
    except (TypeError, ValueError, OSError):
        raise Study3LedgerError("LEDGER_ROOT_INVALID") from None
    if type(raw) is not str or "\\" in raw:
        raise Study3LedgerError("LEDGER_ROOT_INVALID")
    raw_path = Path(raw)
    if any(part in ("", ".", "..") for part in raw_path.parts):
        raise Study3LedgerError("LEDGER_ROOT_INVALID")
    candidate = raw_path if raw_path.is_absolute() else protocol.REPO_ROOT / raw_path
    try:
        candidate = Path(os.path.abspath(candidate))
    except (OSError, ValueError, TypeError):
        raise Study3LedgerError("LEDGER_ROOT_INVALID") from None
    return candidate


def _validate_root_path(path: Path) -> tuple[str, ...]:
    candidate = _coerce_root_path(path)
    try:
        relative = candidate.relative_to(protocol.REPO_ROOT)
        prep = Path(PREP_ROOT_RELATIVE)
        relative.relative_to(prep)
    except ValueError:
        raise Study3LedgerError("LEDGER_ROOT_INVALID") from None
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise Study3LedgerError("LEDGER_ROOT_INVALID")
    return tuple(relative.parts)


def _open_root_parent(
    root_parts: tuple[str, ...], *, create: bool
) -> tuple[int, str]:
    if not root_parts:
        raise Study3LedgerError("LEDGER_ROOT_INVALID")
    descriptor = os.open(protocol.REPO_ROOT, _ROOT_FLAGS)
    try:
        root_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise Study3LedgerError("LEDGER_ROOT_INVALID")
        for part in root_parts[:-1]:
            try:
                child = _open_child_directory(descriptor, part)
            except FileNotFoundError:
                if not create:
                    raise Study3LedgerError("LEDGER_ROOT_MISSING") from None
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    _fsync_directory(descriptor)
                    child = _open_child_directory(descriptor, part)
                except OSError:
                    raise Study3LedgerError("LEDGER_ROOT_CREATE_FAILED") from None
            os.close(descriptor)
            descriptor = child
        return descriptor, root_parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _open_root_directory(root_parts: tuple[str, ...]) -> int:
    parent_fd, leaf = _open_root_parent(root_parts, create=False)
    try:
        descriptor = _open_child_directory(parent_fd, leaf)
    except FileNotFoundError:
        raise Study3LedgerError("LEDGER_MISSING_OR_UNSAFE") from None
    finally:
        os.close(parent_fd)
    metadata = os.fstat(descriptor)
    if metadata.st_mode & 0o077 or metadata.st_mode & 0o700 != 0o700:
        os.close(descriptor)
        raise Study3LedgerError("LEDGER_ROOT_PERMISSIONS_INVALID")
    return descriptor


def _open_child_directory(parent_fd: int, name: str) -> int:
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        raise
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise Study3LedgerError("LEDGER_ROOT_INVALID")
    descriptor = os.open(name, _ROOT_FLAGS, dir_fd=parent_fd)
    after = os.fstat(descriptor)
    named_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(after.st_mode)
        or stat.S_ISLNK(named_after.st_mode)
        or (after.st_dev, after.st_ino) != (named_after.st_dev, named_after.st_ino)
    ):
        os.close(descriptor)
        raise Study3LedgerError("LEDGER_ROOT_INVALID")
    return descriptor


def _verify_named_regular_file(root_fd: int, name: str, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    try:
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
        raise Study3LedgerError("LEDGER_FILE_UNSAFE") from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_ISLNK(named.st_mode)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        or opened.st_nlink != 1
        or opened.st_mode & 0o077
        or opened.st_mode & 0o600 != 0o600
    ):
        raise Study3LedgerError("LEDGER_FILE_UNSAFE")
    if hasattr(os, "geteuid") and opened.st_uid != os.geteuid():
        raise Study3LedgerError("LEDGER_FILE_OWNER_INVALID")


def _fsync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError:
        raise Study3LedgerError("LEDGER_DIRECTORY_SYNC_FAILED") from None


__all__ = [
    "COMPLETION_MARKER_NAME",
    "DEFAULT_LEDGER_ROOT",
    "HARD_CEILING_USD",
    "LEDGER_NAME",
    "LEDGER_ROOT_RELATIVE",
    "LOCK_NAME",
    "PREP_ROOT_RELATIVE",
    "Study3Completion",
    "Study3Ledger",
    "Study3LedgerError",
    "Study3Reservation",
]
