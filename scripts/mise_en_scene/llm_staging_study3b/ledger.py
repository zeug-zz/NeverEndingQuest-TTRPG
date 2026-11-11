# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fixed-root, append-only Study 3b reservation and cost ledger.

This module owns no provider transport or credentials. A reservation is returned
only after its hash-chained record and the ledger descriptor have been fsynced.
The production ledger root and lock identity are constants; synthetic roots are
available only beneath the designated Study 3b preparation directory.
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

from . import newrequest, protocol
from ..llm_staging.client import TransportResult
from ..llm_staging.transport import MAX_RESPONSE_BYTES
from .isolation import (
    PREP_ROOT_RELATIVE,
    STUDY3B_RUN_ROOT_RELATIVE,
    assert_study3b_write_target,
)


LEDGER_ROOT_RELATIVE = STUDY3B_RUN_ROOT_RELATIVE
DEFAULT_LEDGER_ROOT = protocol.REPO_ROOT / LEDGER_ROOT_RELATIVE
LEDGER_NAME = "attempt-ledger.jsonl"
LOCK_IDENTITY = "llm-staging-study3b-20261111"
LOCK_NAME = "." + LOCK_IDENTITY + ".lock"
LEDGER_SCHEMA = "neq.llm_staging_study3b_durable_ledger.v3"
LEDGER_SCHEMA_VERSION = 3
MAX_LEDGER_BYTES = 64 * 1024
HARD_CEILING_USD = Decimal("0.05")
RATE_LISTING_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/"
    "availability-check/model-listing.json"
)
RATE_LISTING_BYTES = 829400
RATE_LISTING_SHA256 = "d94d8370997bb6a32c8265d0c5368d98c121355ebed0c51698539d81e32bdc13"
RATE_ATTESTED_UTC = "2026-11-09T03:48:13Z"
PROMPT_RATE_USD_PER_TOKEN = "0.0000001"
COMPLETION_RATE_USD_PER_TOKEN = "0.0000005"
ESTIMATE_SCHEMA = "neq.llm_staging_study3b_cost_estimate.v1"
ESTIMATE_FORMULA = (
    "ceil(canonical_request_wire_utf8_bytes / 3) * historical prompt rate + "
    "max_tokens * historical completion rate"
)
ESTIMATE_LIMITATION = (
    "The byte/token proxy is an estimate, not a guaranteed tokenizer upper "
    "bound or provider cost guarantee."
)

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


class Study3bLedgerError(RuntimeError):
    """A metadata-only, fail-closed ledger refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Study3bReservation:
    """In-process handle for exactly one durable pending reservation."""

    study_id: str
    manifest_sha256: str
    attempt_number: int
    scene_id: str
    request_sha256: str
    reservation_sha256: str
    reservation_budget_usd: str
    conservative_cost_usd_estimate: str
    estimate_sha256: str
    pricing_provenance_sha256: str
    pre_dispatch_estimated_total_usd: str
    _token: str = field(repr=False, compare=False)


@dataclass(frozen=True)
class Study3bCompletion:
    """Metadata-only result of reconciling one reservation."""

    attempt_number: int
    scene_id: str
    outcome: str
    actual_cost_status: str
    actual_cost_usd: str | None
    stop_study: bool


@dataclass(frozen=True)
class _VerifiedStudy3bCostReceipt:
    """Receipt capability minted only after local response validation."""

    payload_items: tuple[tuple[str, str | int], ...]
    reservation_token: str = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)


_VERIFIED_COST_RECEIPT_SEAL = object()


@dataclass(frozen=True)
class _Binding:
    manifest_sha256: str
    protocol_sha256: str
    generation_config_sha256: str
    scene_order_sha256: str
    request_hashes: tuple[str, ...]
    pricing_provenance_items: tuple[tuple[str, str | int], ...]
    pricing_provenance_sha256: str
    scene_estimates: tuple["_SceneCostEstimate", ...]
    scene_estimates_sha256: str


@dataclass(frozen=True)
class _SceneCostEstimate:
    scene_id: str
    request_sha256: str
    canonical_request_wire_utf8_bytes: int
    input_tokens_proxy: int
    max_output_tokens: int
    prompt_rate_usd_per_token_historical: str
    completion_rate_usd_per_token_historical: str
    conservative_cost_usd: Decimal
    pricing_provenance_sha256: str

    def as_record(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "request_sha256": self.request_sha256,
            "canonical_request_wire_utf8_bytes": self.canonical_request_wire_utf8_bytes,
            "input_tokens_proxy_ceil_bytes_over_3": self.input_tokens_proxy,
            "max_output_tokens": self.max_output_tokens,
            "prompt_rate_usd_per_token_historical": self.prompt_rate_usd_per_token_historical,
            "completion_rate_usd_per_token_historical": self.completion_rate_usd_per_token_historical,
            "conservative_cost_usd_estimate": _format_cost(self.conservative_cost_usd),
            "estimate_classification": "ESTIMATE_NOT_PROVIDER_COST_GUARANTEE",
            "pricing_provenance_sha256": self.pricing_provenance_sha256,
        }


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


class Study3bLedger:
    """Operate on the fixed Study 3b root; never attach to an old ledger."""

    def __init__(self) -> None:
        self._configure(DEFAULT_LEDGER_ROOT, synthetic=False)

    @classmethod
    def _for_synthetic_test(cls, root: Path | str) -> "Study3bLedger":
        """Construct a test-only ledger under the designated prep tree."""

        instance = object.__new__(cls)
        candidate = _coerce_root_path(root)
        if candidate == DEFAULT_LEDGER_ROOT or not candidate.name.startswith(
            "synthetic-"
        ):
            raise Study3bLedgerError("LEDGER_ROOT_INVALID")
        instance._configure(candidate, synthetic=True)
        return instance

    def _configure(self, root: Path, *, synthetic: bool) -> None:
        self._root = root
        self._root_parts = _validate_root_path(root, synthetic=synthetic)
        self._synthetic = synthetic
        self._thread_lock = _thread_lock(root)
        self._process_id = os.getpid()
        self._initialized = False
        self._poisoned = False
        self._active_reservation: Study3bReservation | None = None
        self._session_token = secrets.token_hex(32)

    @property
    def root(self) -> Path:
        """Return the configured path without touching the filesystem."""

        return self._root

    @property
    def path(self) -> Path:
        """Return the JSONL path without touching the filesystem."""

        return self._root / LEDGER_NAME

    def initialize(self) -> None:
        """Create this fixed allocation exactly once; never reset or reuse it."""

        self._ensure_process()
        if self._initialized:
            raise Study3bLedgerError("LEDGER_ALREADY_INITIALIZED")
        binding = _load_binding()
        parent_fd: int | None = None
        root_fd: int | None = None
        lock_fd: int | None = None
        ledger_fd: int | None = None
        try:
            parent_fd, leaf = _open_root_parent(self._root_parts)
            try:
                os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise Study3bLedgerError("LEDGER_ALREADY_INITIALIZED")

            _assert_write_target(self._root, "write")
            try:
                os.mkdir(leaf, 0o700, dir_fd=parent_fd)
                _fsync_directory(parent_fd)
            except FileExistsError:
                raise Study3bLedgerError("LEDGER_ALREADY_INITIALIZED") from None
            except OSError:
                raise Study3bLedgerError("LEDGER_ROOT_CREATE_FAILED") from None

            root_fd = _open_child_directory(parent_fd, leaf)
            _assert_write_target(self._root, "write")
            os.fchmod(root_fd, 0o700)
            if os.listdir(root_fd):
                raise Study3bLedgerError("LEDGER_DUPLICATE_ARTIFACT")

            lock_path = self._root / LOCK_NAME
            _assert_write_target(lock_path, "write")
            lock_fd = os.open(
                LOCK_NAME,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
                0o600,
                dir_fd=root_fd,
            )
            _assert_write_target(lock_path, "write")
            os.fchmod(lock_fd, 0o600)
            _verify_named_regular_file(root_fd, LOCK_NAME, lock_fd)
            _write_all(lock_fd, _lock_contents())
            os.fsync(lock_fd)
            _fsync_directory(root_fd)

            ledger_path = self._root / LEDGER_NAME
            _assert_write_target(ledger_path, "write")
            ledger_fd = os.open(
                LEDGER_NAME,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
                0o600,
                dir_fd=root_fd,
            )
            _assert_write_target(ledger_path, "write")
            os.fchmod(ledger_fd, 0o600)
            _verify_named_regular_file(root_fd, LEDGER_NAME, ledger_fd)
            _append_record(ledger_fd, _header_payload(binding), None, ledger_path)
            os.fsync(ledger_fd)
            _fsync_directory(root_fd)
        except Study3bLedgerError:
            raise
        except (OSError, ValueError):
            self._poisoned = True
            raise Study3bLedgerError("LEDGER_INITIALIZATION_FAILED") from None
        finally:
            for descriptor in (ledger_fd, lock_fd, root_fd, parent_fd):
                if descriptor is not None:
                    os.close(descriptor)
        self._initialized = True

    def reserve(
        self, *, scene_id: object, request_sha256: object
    ) -> Study3bReservation:
        """Fsync the next fixed-order reservation before returning its handle."""

        self._ensure_initialized()
        binding = _load_binding()
        if type(scene_id) is not str or scene_id not in protocol.SCENE_ORDER:
            raise Study3bLedgerError("RESERVATION_IDENTITY_INVALID")
        if (
            type(request_sha256) is not str
            or _SHA256_RE.fullmatch(request_sha256) is None
        ):
            raise Study3bLedgerError("RESERVATION_IDENTITY_INVALID")

        with self._locked_existing() as (_root_fd, ledger_fd):
            state = _read_state(ledger_fd, binding)
            if state.pending is not None:
                raise Study3bLedgerError("LEDGER_PENDING_RESERVATION")
            if state.unresolved_cost:
                raise Study3bLedgerError("LEDGER_ACTUAL_COST_UNRESOLVED")
            if state.stopped:
                raise Study3bLedgerError("LEDGER_STUDY_STOPPED")
            if state.actual_total >= HARD_CEILING_USD:
                raise Study3bLedgerError("LEDGER_BUDGET_EXHAUSTED")

            attempt_number = len(state.reservations) + 1
            if attempt_number > len(protocol.SCENE_ORDER):
                raise Study3bLedgerError("LEDGER_ATTEMPT_CAP_EXHAUSTED")
            scene_index = attempt_number - 1
            if (
                scene_id != protocol.SCENE_ORDER[scene_index]
                or request_sha256 != binding.request_hashes[scene_index]
            ):
                raise Study3bLedgerError("SCENE_ORDER_OR_REQUEST_MISMATCH")

            estimate = binding.scene_estimates[scene_index]
            pre_dispatch_total = _require_conservative_budget_total(
                state.actual_total,
                tuple(
                    item.conservative_cost_usd
                    for item in binding.scene_estimates[scene_index:]
                ),
            )
            reservation_budget = (
                HARD_CEILING_USD
                - pre_dispatch_total
                + estimate.conservative_cost_usd
            )
            if not reservation_budget.is_finite() or reservation_budget <= 0:
                raise Study3bLedgerError(
                    "LEDGER_CONSERVATIVE_BUDGET_NOT_STRICTLY_BELOW_CEILING"
                )
            payload = {
                "event": "reservation",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": protocol.STUDY_ID,
                "lock_identity": LOCK_IDENTITY,
                "manifest_sha256": binding.manifest_sha256,
                "protocol_sha256": binding.protocol_sha256,
                "generation_config_sha256": binding.generation_config_sha256,
                "scene_order_sha256": binding.scene_order_sha256,
                "attempt_number": attempt_number,
                "scene_id": scene_id,
                "request_sha256": request_sha256,
                "conservative_cost_usd_estimate": _format_cost(
                    estimate.conservative_cost_usd
                ),
                "estimate_sha256": _estimate_sha256(estimate),
                "pricing_provenance_sha256": binding.pricing_provenance_sha256,
                "pre_dispatch_estimated_total_usd": _format_cost(pre_dispatch_total),
                "reservation_budget_usd": _format_cost(reservation_budget),
            }
            try:
                reservation_sha256 = _append_record(
                    ledger_fd,
                    payload,
                    state.records[-1]["record_sha256"],
                    self.path,
                )
                os.fsync(ledger_fd)
            except (OSError, Study3bLedgerError):
                self._poisoned = True
                raise Study3bLedgerError("LEDGER_DURABILITY_UNCERTAIN") from None

            reservation = Study3bReservation(
                study_id=protocol.STUDY_ID,
                manifest_sha256=binding.manifest_sha256,
                attempt_number=attempt_number,
                scene_id=scene_id,
                request_sha256=request_sha256,
                reservation_sha256=reservation_sha256,
                reservation_budget_usd=_format_cost(reservation_budget),
                conservative_cost_usd_estimate=_format_cost(
                    estimate.conservative_cost_usd
                ),
                estimate_sha256=_estimate_sha256(estimate),
                pricing_provenance_sha256=binding.pricing_provenance_sha256,
                pre_dispatch_estimated_total_usd=_format_cost(pre_dispatch_total),
                _token=self._session_token + secrets.token_hex(16),
            )
            self._active_reservation = reservation
            return reservation

    def complete(
        self,
        reservation: object,
        *,
        outcome: object,
        cost_receipt: object = None,
    ) -> Study3bCompletion:
        """Append a bound result and receipt, stopping on uncertain accounting."""

        self._ensure_initialized()
        if (
            type(reservation) is not Study3bReservation
            or self._active_reservation is None
            or reservation._token != self._active_reservation._token
            or reservation != self._active_reservation
        ):
            raise Study3bLedgerError("RESERVATION_HANDLE_INVALID")
        if type(outcome) is not str or outcome not in {
            "ACCEPTED",
            "CONTRACT_FAILURE",
            "STOPPED",
        }:
            raise Study3bLedgerError("RESULT_OUTCOME_INVALID")

        binding = _load_binding()
        with self._locked_existing() as (root_fd, ledger_fd):
            state = _read_state(ledger_fd, binding)
            pending = state.pending
            if (
                pending is None
                or pending["attempt_number"] != reservation.attempt_number
                or pending["scene_id"] != reservation.scene_id
                or pending["request_sha256"] != reservation.request_sha256
                or pending["manifest_sha256"] != reservation.manifest_sha256
                or state.pending_sha256 != reservation.reservation_sha256
            ):
                raise Study3bLedgerError("LEDGER_PENDING_RESERVATION_MISMATCH")

            receipt: dict[str, Any] | None = None
            actual_cost: Decimal | None = None
            actual_status = "UNRESOLVED"
            reason_code: str | None
            if cost_receipt is None:
                reason_code = "COST_RECEIPT_MISSING"
            else:
                try:
                    receipt, actual_cost = _validate_verified_cost_receipt(
                        cost_receipt,
                        pending,
                        reservation_token=reservation._token,
                    )
                except Study3bLedgerError:
                    receipt = None
                    actual_cost = None
                    reason_code = "COST_RECEIPT_INVALID"
                else:
                    if receipt["receipt_id"] in state.receipt_ids:
                        receipt = None
                        actual_cost = None
                        reason_code = "COST_RECEIPT_DUPLICATE"
                    elif actual_cost > Decimal(pending["reservation_budget_usd"]):
                        actual_status = "OVER_CAP"
                        reason_code = "ACTUAL_COST_OVER_CAP"
                    else:
                        actual_status = "RECONCILED"
                        reason_code = None

            if actual_status == "UNRESOLVED":
                receipt_for_record = None
                actual_cost_text = None
            else:
                receipt_for_record = receipt
                actual_cost_text = _format_cost(actual_cost)

            stop_study = (
                outcome != "ACCEPTED" or actual_status != "RECONCILED"
            )
            result_payload = {
                "event": "result",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": protocol.STUDY_ID,
                "lock_identity": LOCK_IDENTITY,
                "manifest_sha256": binding.manifest_sha256,
                "protocol_sha256": binding.protocol_sha256,
                "generation_config_sha256": binding.generation_config_sha256,
                "scene_order_sha256": binding.scene_order_sha256,
                "attempt_number": reservation.attempt_number,
                "scene_id": reservation.scene_id,
                "request_sha256": reservation.request_sha256,
                "conservative_cost_usd_estimate": pending[
                    "conservative_cost_usd_estimate"
                ],
                "estimate_sha256": pending["estimate_sha256"],
                "pricing_provenance_sha256": pending[
                    "pricing_provenance_sha256"
                ],
                "pre_dispatch_estimated_total_usd": pending[
                    "pre_dispatch_estimated_total_usd"
                ],
                "outcome": outcome,
                "stop_study": stop_study,
                "actual_cost_status": actual_status,
                "actual_cost_usd": actual_cost_text,
                "cost_receipt": receipt_for_record,
                "reason_code": reason_code,
            }
            try:
                _append_record(
                    ledger_fd,
                    result_payload,
                    state.records[-1]["record_sha256"],
                    self.path,
                )
                os.fsync(ledger_fd)
            except (OSError, Study3bLedgerError):
                self._poisoned = True
                raise Study3bLedgerError(
                    "LEDGER_COMPLETION_DURABILITY_UNCERTAIN"
                ) from None

            self._active_reservation = None
            return Study3bCompletion(
                attempt_number=reservation.attempt_number,
                scene_id=reservation.scene_id,
                outcome=outcome,
                actual_cost_status=actual_status,
                actual_cost_usd=actual_cost_text,
                stop_study=stop_study,
            )

    @contextmanager
    def _locked_existing(self) -> Iterator[tuple[int, int]]:
        """Yield verified descriptors while holding thread and file locks."""

        self._ensure_initialized()
        root_fd: int | None = None
        lock_fd: int | None = None
        ledger_fd: int | None = None
        self._thread_lock.acquire()
        try:
            root_fd = _open_root_directory(self._root_parts)
            names = set(os.listdir(root_fd))
            if names != {LOCK_NAME, LEDGER_NAME}:
                raise Study3bLedgerError("LEDGER_DUPLICATE_OR_MISSING_ARTIFACT")

            lock_path = self._root / LOCK_NAME
            _assert_write_target(lock_path, "append")
            lock_fd = os.open(
                LOCK_NAME, os.O_RDWR | _FILE_NOFOLLOW, dir_fd=root_fd
            )
            _verify_named_regular_file(root_fd, LOCK_NAME, lock_fd)
            if _read_descriptor(lock_fd, 256) != _lock_contents():
                raise Study3bLedgerError("LEDGER_LOCK_IDENTITY_MISMATCH")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            _verify_named_regular_file(root_fd, LOCK_NAME, lock_fd)

            if set(os.listdir(root_fd)) != names:
                raise Study3bLedgerError("LEDGER_DUPLICATE_OR_MISSING_ARTIFACT")
            ledger_path = self.path
            _assert_write_target(ledger_path, "append")
            ledger_fd = os.open(
                LEDGER_NAME,
                os.O_RDWR | os.O_APPEND | _FILE_NOFOLLOW,
                dir_fd=root_fd,
            )
            _verify_named_regular_file(root_fd, LEDGER_NAME, ledger_fd)
            yield root_fd, ledger_fd
        except Study3bLedgerError:
            raise
        except OSError:
            raise Study3bLedgerError("LEDGER_MISSING_OR_UNSAFE") from None
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

    def _ensure_process(self) -> None:
        if os.getpid() != self._process_id:
            self._poisoned = True
            raise Study3bLedgerError("LEDGER_PROCESS_IDENTITY_MISMATCH")
        if self._poisoned:
            raise Study3bLedgerError("LEDGER_INSTANCE_POISONED")

    def _ensure_initialized(self) -> None:
        self._ensure_process()
        if not self._initialized:
            raise Study3bLedgerError("LEDGER_INSTANCE_NOT_INITIALIZED")


def request_sha256_for_scene(scene_id: object) -> str:
    """Hash the exact deterministic request object bound to an approved scene."""

    if type(scene_id) is not str or scene_id not in protocol.SCENE_ORDER:
        raise Study3bLedgerError("RESERVATION_IDENTITY_INVALID")
    try:
        request_bytes = _request_wire_bytes_for_scene(scene_id)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise Study3bLedgerError("REQUEST_BINDING_UNAVAILABLE") from None
    return hashlib.sha256(request_bytes).hexdigest()


def _request_wire_bytes_for_scene(scene_id: str) -> bytes:
    request = newrequest.build_request(scene_id)
    return json.dumps(
        request,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_historical_rate_provenance() -> dict[str, str | int]:
    """Verify the exact historical pricing evidence used by Study 3 sizing."""

    try:
        raw = protocol._safe_project_read(RATE_LISTING_RELATIVE)
        if (
            len(raw) != RATE_LISTING_BYTES
            or hashlib.sha256(raw).hexdigest() != RATE_LISTING_SHA256
        ):
            raise Study3bLedgerError("HISTORICAL_RATE_EVIDENCE_MISMATCH")
        listing = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        rows = listing["data"]
        if type(rows) is not list:
            raise ValueError
        matching = [
            row for row in rows
            if type(row) is dict and row.get("id") == protocol.MODEL_ID
        ]
        if len(matching) != 1:
            raise ValueError
        pricing = matching[0]["pricing"]
        prompt_rate = pricing["prompt"]
        completion_rate = pricing["completion"]
        if (
            type(prompt_rate) is not str
            or type(completion_rate) is not str
            or prompt_rate != PROMPT_RATE_USD_PER_TOKEN
            or completion_rate != COMPLETION_RATE_USD_PER_TOKEN
        ):
            raise ValueError
        _validate_rate(prompt_rate)
        _validate_rate(completion_rate)
    except Study3bLedgerError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        OverflowError,
    ):
        raise Study3bLedgerError("HISTORICAL_RATE_EVIDENCE_INVALID") from None

    return {
        "classification": "HISTORICAL_RATE_LISTING_NOT_CURRENT_QUOTE",
        "model_id": protocol.MODEL_ID,
        "source_path": RATE_LISTING_RELATIVE,
        "source_bytes": RATE_LISTING_BYTES,
        "source_sha256": RATE_LISTING_SHA256,
        "attested_utc": RATE_ATTESTED_UTC,
        "prompt_usd_per_token_historical": prompt_rate,
        "completion_usd_per_token_historical": completion_rate,
    }


def _validate_rate(value: object) -> Decimal:
    if type(value) is not str:
        raise Study3bLedgerError("HISTORICAL_RATE_EVIDENCE_INVALID")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise Study3bLedgerError("HISTORICAL_RATE_EVIDENCE_INVALID") from None
    if not amount.is_finite() or amount <= 0:
        raise Study3bLedgerError("HISTORICAL_RATE_EVIDENCE_INVALID")
    return amount


def _build_scene_estimate(
    scene_id: str,
    request_bytes: bytes,
    *,
    max_output_tokens: int,
    pricing_provenance: dict[str, str | int],
    pricing_provenance_sha256: str,
) -> _SceneCostEstimate:
    prompt_rate = pricing_provenance["prompt_usd_per_token_historical"]
    completion_rate = pricing_provenance["completion_usd_per_token_historical"]
    if (
        type(prompt_rate) is not str
        or type(completion_rate) is not str
        or type(max_output_tokens) is not int
        or max_output_tokens <= 0
        or _SHA256_RE.fullmatch(pricing_provenance_sha256) is None
    ):
        raise Study3bLedgerError("LEDGER_ESTIMATE_INVALID")
    input_tokens_proxy = (len(request_bytes) + 2) // 3
    conservative_cost = (
        Decimal(input_tokens_proxy) * _validate_rate(prompt_rate)
        + Decimal(max_output_tokens) * _validate_rate(completion_rate)
    )
    if not conservative_cost.is_finite() or conservative_cost < 0:
        raise Study3bLedgerError("LEDGER_ESTIMATE_INVALID")
    return _SceneCostEstimate(
        scene_id=scene_id,
        request_sha256=hashlib.sha256(request_bytes).hexdigest(),
        canonical_request_wire_utf8_bytes=len(request_bytes),
        input_tokens_proxy=input_tokens_proxy,
        max_output_tokens=max_output_tokens,
        prompt_rate_usd_per_token_historical=prompt_rate,
        completion_rate_usd_per_token_historical=completion_rate,
        conservative_cost_usd=conservative_cost,
        pricing_provenance_sha256=pricing_provenance_sha256,
    )


def _load_binding() -> _Binding:
    try:
        protocol.load_manifest()
        protocol.load_protocol_text()
        generation_config = protocol.load_generation_config()
        pricing_provenance = _load_historical_rate_provenance()
        pricing_provenance_items = tuple(sorted(pricing_provenance.items()))
        pricing_provenance_sha256 = hashlib.sha256(
            _canonical_bytes(pricing_provenance)
        ).hexdigest()
        estimates = tuple(
            _build_scene_estimate(
                scene_id,
                _request_wire_bytes_for_scene(scene_id),
                max_output_tokens=generation_config["max_tokens"],
                pricing_provenance=pricing_provenance,
                pricing_provenance_sha256=pricing_provenance_sha256,
            )
            for scene_id in protocol.SCENE_ORDER
        )
        binding = _Binding(
            manifest_sha256=protocol.MANIFEST_SHA256,
            protocol_sha256=protocol.PROTOCOL_SHA256,
            generation_config_sha256=protocol.GENERATION_CONFIG_SHA256,
            scene_order_sha256=hashlib.sha256(
                _canonical_bytes(list(protocol.SCENE_ORDER))
            ).hexdigest(),
            request_hashes=tuple(item.request_sha256 for item in estimates),
            pricing_provenance_items=pricing_provenance_items,
            pricing_provenance_sha256=pricing_provenance_sha256,
            scene_estimates=estimates,
            scene_estimates_sha256=hashlib.sha256(
                _canonical_bytes([item.as_record() for item in estimates])
            ).hexdigest(),
        )
        _validate_scene_estimate_binding(binding, generation_config["max_tokens"])
        _require_conservative_budget_total(
            Decimal(0),
            tuple(item.conservative_cost_usd for item in binding.scene_estimates),
        )
        return binding
    except Study3bLedgerError:
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError):
        raise Study3bLedgerError("STUDY3B_BINDING_INVALID") from None


def _validate_scene_estimate_binding(binding: _Binding, max_output_tokens: object) -> None:
    if (
        type(binding) is not _Binding
        or type(max_output_tokens) is not int
        or max_output_tokens != 16384
        or type(binding.request_hashes) is not tuple
        or len(binding.request_hashes) != len(protocol.SCENE_ORDER)
        or type(binding.scene_estimates) is not tuple
        or len(binding.scene_estimates) != len(protocol.SCENE_ORDER)
        or type(binding.pricing_provenance_items) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) not in (str, int)
            for item in binding.pricing_provenance_items
        )
        or len({item[0] for item in binding.pricing_provenance_items})
        != len(binding.pricing_provenance_items)
    ):
        raise Study3bLedgerError("LEDGER_ESTIMATE_UNAVAILABLE")
    pricing_provenance = dict(binding.pricing_provenance_items)
    if (
        hashlib.sha256(_canonical_bytes(pricing_provenance)).hexdigest()
        != binding.pricing_provenance_sha256
        or _SHA256_RE.fullmatch(binding.pricing_provenance_sha256) is None
        or pricing_provenance.get("source_path") != RATE_LISTING_RELATIVE
        or pricing_provenance.get("source_bytes") != RATE_LISTING_BYTES
        or pricing_provenance.get("source_sha256") != RATE_LISTING_SHA256
        or pricing_provenance.get("model_id") != protocol.MODEL_ID
        or pricing_provenance.get("prompt_usd_per_token_historical")
        != PROMPT_RATE_USD_PER_TOKEN
        or pricing_provenance.get("completion_usd_per_token_historical")
        != COMPLETION_RATE_USD_PER_TOKEN
        or pricing_provenance.get("classification")
        != "HISTORICAL_RATE_LISTING_NOT_CURRENT_QUOTE"
    ):
        raise Study3bLedgerError("LEDGER_ESTIMATE_PROVENANCE_INVALID")

    prompt_rate = pricing_provenance["prompt_usd_per_token_historical"]
    completion_rate = pricing_provenance["completion_usd_per_token_historical"]
    for index, estimate in enumerate(binding.scene_estimates):
        if type(estimate) is not _SceneCostEstimate:
            raise Study3bLedgerError("LEDGER_ESTIMATE_UNAVAILABLE")
        if (
            estimate.scene_id != protocol.SCENE_ORDER[index]
            or estimate.request_sha256 != binding.request_hashes[index]
            or _SHA256_RE.fullmatch(estimate.request_sha256) is None
            or estimate.pricing_provenance_sha256
            != binding.pricing_provenance_sha256
        ):
            raise Study3bLedgerError("LEDGER_ESTIMATE_BINDING_INVALID")
        if (
            type(estimate.canonical_request_wire_utf8_bytes) is not int
            or estimate.canonical_request_wire_utf8_bytes <= 0
            or type(estimate.input_tokens_proxy) is not int
            or estimate.input_tokens_proxy
            != (estimate.canonical_request_wire_utf8_bytes + 2) // 3
            or estimate.max_output_tokens != max_output_tokens
            or estimate.prompt_rate_usd_per_token_historical != prompt_rate
            or estimate.completion_rate_usd_per_token_historical
            != completion_rate
            or type(estimate.conservative_cost_usd) is not Decimal
            or not estimate.conservative_cost_usd.is_finite()
            or estimate.conservative_cost_usd
            != (
                Decimal(estimate.input_tokens_proxy) * _validate_rate(prompt_rate)
                + Decimal(max_output_tokens) * _validate_rate(completion_rate)
            )
        ):
            raise Study3bLedgerError("LEDGER_ESTIMATE_INVALID")
    if (
        hashlib.sha256(
            _canonical_bytes([item.as_record() for item in binding.scene_estimates])
        ).hexdigest()
        != binding.scene_estimates_sha256
    ):
        raise Study3bLedgerError("LEDGER_ESTIMATE_BINDING_INVALID")


def _require_conservative_budget_total(
    actual_spent: object, estimates: object
) -> Decimal:
    if (
        type(actual_spent) is not Decimal
        or not actual_spent.is_finite()
        or actual_spent < 0
    ):
        raise Study3bLedgerError("LEDGER_ACTUAL_COST_INVALID")
    if type(estimates) not in (tuple, list) or not estimates:
        raise Study3bLedgerError("LEDGER_ESTIMATE_UNAVAILABLE")
    total = actual_spent
    try:
        for estimate in estimates:
            if (
                type(estimate) is not Decimal
                or not estimate.is_finite()
                or estimate < 0
            ):
                raise Study3bLedgerError("LEDGER_ESTIMATE_INVALID")
            total += estimate
    except (InvalidOperation, OverflowError):
        raise Study3bLedgerError("LEDGER_ESTIMATE_INVALID") from None
    if not total.is_finite() or total >= HARD_CEILING_USD:
        raise Study3bLedgerError(
            "LEDGER_CONSERVATIVE_BUDGET_NOT_STRICTLY_BELOW_CEILING"
        )
    return total


def _estimate_sha256(estimate: _SceneCostEstimate) -> str:
    return hashlib.sha256(_canonical_bytes(estimate.as_record())).hexdigest()


def _header_payload(binding: _Binding) -> dict[str, Any]:
    _validate_scene_estimate_binding(binding, 16384)
    pricing_provenance = dict(binding.pricing_provenance_items)
    total_estimate = sum(
        (item.conservative_cost_usd for item in binding.scene_estimates),
        Decimal(0),
    )
    return {
        "event": "header",
        "schema_version": LEDGER_SCHEMA_VERSION,
        "schema": LEDGER_SCHEMA,
        "study_id": protocol.STUDY_ID,
        "allocation_scope": "studywide",
        "lock_identity": LOCK_IDENTITY,
        "manifest_sha256": binding.manifest_sha256,
        "protocol_sha256": binding.protocol_sha256,
        "generation_config_sha256": binding.generation_config_sha256,
        "scene_order": list(protocol.SCENE_ORDER),
        "scene_order_sha256": binding.scene_order_sha256,
        "attempt_cap": {
            "identity": protocol.STUDY_ID,
            "total": len(protocol.SCENE_ORDER),
            "per_scene": 1,
            "scene_order": list(protocol.SCENE_ORDER),
        },
        "hard_ceiling_usd": _format_cost(HARD_CEILING_USD),
        "request_bindings": [
            {"scene_id": scene_id, "request_sha256": request_hash}
            for scene_id, request_hash in zip(
                protocol.SCENE_ORDER, binding.request_hashes
            )
        ],
        "cost_estimate_policy": {
            "schema": ESTIMATE_SCHEMA,
            "classification": "ESTIMATE_NOT_PROVIDER_COST_GUARANTEE",
            "formula": ESTIMATE_FORMULA,
            "limitation": ESTIMATE_LIMITATION,
            "pricing_provenance": pricing_provenance,
            "pricing_provenance_sha256": binding.pricing_provenance_sha256,
            "scene_estimates": [
                item.as_record() for item in binding.scene_estimates
            ],
            "scene_estimates_sha256": binding.scene_estimates_sha256,
            "conservative_total_usd_estimate": _format_cost(total_estimate),
            "strict_pre_dispatch_rule": (
                "actual_spent_usd + estimates for every not-yet-attempted scene "
                "must be strictly less than the hard ceiling"
            ),
        },
        "budget_policy": (
            "ledger-owned historical conservative estimate and remaining hard "
            "ceiling; no caller budget or estimate"
        ),
    }


def _read_state(descriptor: int, binding: _Binding) -> _LedgerState:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > MAX_LEDGER_BYTES
    ):
        raise Study3bLedgerError("LEDGER_EMPTY_OR_OVERSIZED")
    os.lseek(descriptor, 0, os.SEEK_SET)
    contents = _read_descriptor(descriptor, MAX_LEDGER_BYTES + 1)
    if len(contents) != metadata.st_size or not contents.endswith(b"\n"):
        raise Study3bLedgerError("LEDGER_TRUNCATED")
    try:
        records = tuple(_parse_record(line) for line in contents.splitlines())
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError, OverflowError):
        raise Study3bLedgerError("LEDGER_CORRUPT") from None
    if not records or len(records) > 1 + 2 * len(protocol.SCENE_ORDER):
        raise Study3bLedgerError("LEDGER_CORRUPT")

    prior_hash: str | None = None
    payloads: list[dict[str, Any]] = []
    for record in records:
        if not {"previous_sha256", "record_sha256"}.issubset(record):
            raise Study3bLedgerError("LEDGER_HASH_CHAIN_INVALID")
        record_hash = record.get("record_sha256")
        if (
            type(record_hash) is not str
            or _SHA256_RE.fullmatch(record_hash) is None
            or record.get("previous_sha256") != prior_hash
        ):
            raise Study3bLedgerError("LEDGER_HASH_CHAIN_INVALID")
        unhashed = dict(record)
        del unhashed["record_sha256"]
        if hashlib.sha256(_canonical_bytes(unhashed)).hexdigest() != record_hash:
            raise Study3bLedgerError("LEDGER_HASH_CHAIN_INVALID")
        payload = dict(unhashed)
        del payload["previous_sha256"]
        payloads.append(payload)
        prior_hash = record_hash

    if _canonical_bytes(payloads[0]) != _canonical_bytes(_header_payload(binding)):
        raise Study3bLedgerError("LEDGER_HEADER_BINDING_MISMATCH")

    reservations: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    pending_sha256: str | None = None
    stopped = False
    unresolved_cost = False
    actual_total = Decimal(0)
    receipt_ids: set[str] = set()

    for index, payload in enumerate(payloads[1:], start=1):
        if payload.get("event") == "reservation":
            if pending is not None or stopped:
                raise Study3bLedgerError("LEDGER_RESERVATION_SEQUENCE_INVALID")
            attempt_number = len(reservations) + 1
            if attempt_number > len(protocol.SCENE_ORDER):
                raise Study3bLedgerError("LEDGER_ATTEMPT_CAP_EXCEEDED")
            scene_index = attempt_number - 1
            estimate = binding.scene_estimates[scene_index]
            pre_dispatch_total = _require_conservative_budget_total(
                actual_total,
                tuple(
                    item.conservative_cost_usd
                    for item in binding.scene_estimates[scene_index:]
                ),
            )
            reservation_budget = (
                HARD_CEILING_USD
                - pre_dispatch_total
                + estimate.conservative_cost_usd
            )
            if not reservation_budget.is_finite() or reservation_budget <= 0:
                raise Study3bLedgerError(
                    "LEDGER_CONSERVATIVE_BUDGET_NOT_STRICTLY_BELOW_CEILING"
                )
            expected = {
                "event": "reservation",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": protocol.STUDY_ID,
                "lock_identity": LOCK_IDENTITY,
                "manifest_sha256": binding.manifest_sha256,
                "protocol_sha256": binding.protocol_sha256,
                "generation_config_sha256": binding.generation_config_sha256,
                "scene_order_sha256": binding.scene_order_sha256,
                "attempt_number": attempt_number,
                "scene_id": protocol.SCENE_ORDER[scene_index],
                "request_sha256": binding.request_hashes[scene_index],
                "conservative_cost_usd_estimate": _format_cost(
                    estimate.conservative_cost_usd
                ),
                "estimate_sha256": _estimate_sha256(estimate),
                "pricing_provenance_sha256": binding.pricing_provenance_sha256,
                "pre_dispatch_estimated_total_usd": _format_cost(pre_dispatch_total),
                "reservation_budget_usd": _format_cost(reservation_budget),
            }
            if (
                reservation_budget <= 0
                or set(payload) != set(expected)
                or _canonical_bytes(payload) != _canonical_bytes(expected)
            ):
                raise Study3bLedgerError("LEDGER_RESERVATION_BINDING_INVALID")
            pending = payload
            pending_sha256 = records[index]["record_sha256"]
            reservations.append(payload)
            continue

        if payload.get("event") != "result" or pending is None or stopped:
            raise Study3bLedgerError("LEDGER_EVENT_SEQUENCE_INVALID")
        expected_fields = {
            "event",
            "schema_version",
            "study_id",
            "lock_identity",
            "manifest_sha256",
            "protocol_sha256",
            "generation_config_sha256",
            "scene_order_sha256",
            "attempt_number",
            "scene_id",
            "request_sha256",
            "conservative_cost_usd_estimate",
            "estimate_sha256",
            "pricing_provenance_sha256",
            "pre_dispatch_estimated_total_usd",
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
            or payload.get("lock_identity") != LOCK_IDENTITY
            or payload.get("manifest_sha256") != binding.manifest_sha256
            or payload.get("protocol_sha256") != binding.protocol_sha256
            or payload.get("generation_config_sha256")
            != binding.generation_config_sha256
            or payload.get("scene_order_sha256") != binding.scene_order_sha256
            or type(payload.get("attempt_number")) is not int
            or payload.get("attempt_number") != pending["attempt_number"]
            or payload.get("scene_id") != pending["scene_id"]
            or payload.get("request_sha256") != pending["request_sha256"]
            or payload.get("conservative_cost_usd_estimate")
            != pending["conservative_cost_usd_estimate"]
            or payload.get("estimate_sha256") != pending["estimate_sha256"]
            or payload.get("pricing_provenance_sha256")
            != pending["pricing_provenance_sha256"]
            or payload.get("pre_dispatch_estimated_total_usd")
            != pending["pre_dispatch_estimated_total_usd"]
            or type(payload.get("outcome")) is not str
            or payload.get("outcome")
            not in {"ACCEPTED", "CONTRACT_FAILURE", "STOPPED"}
            or type(payload.get("stop_study")) is not bool
        ):
            raise Study3bLedgerError("LEDGER_RESULT_BINDING_INVALID")

        status = payload.get("actual_cost_status")
        if status in {"RECONCILED", "OVER_CAP"}:
            receipt, receipt_cost = _validate_cost_receipt_payload(
                payload.get("cost_receipt"), pending
            )
            if (
                payload.get("actual_cost_usd") != _format_cost(receipt_cost)
                or receipt["receipt_id"] in receipt_ids
            ):
                raise Study3bLedgerError("LEDGER_COST_RECEIPT_MISMATCH")
            reserved = Decimal(pending["reservation_budget_usd"])
            is_over_cap = receipt_cost > reserved
            if status == "OVER_CAP":
                if (
                    not is_over_cap
                    or payload.get("reason_code") != "ACTUAL_COST_OVER_CAP"
                    or payload.get("stop_study") is not True
                ):
                    raise Study3bLedgerError("LEDGER_COST_ACCOUNTING_INVALID")
            else:
                expected_stop = payload["outcome"] != "ACCEPTED"
                if (
                    is_over_cap
                    or payload.get("reason_code") is not None
                    or payload.get("stop_study") is not expected_stop
                ):
                    raise Study3bLedgerError("LEDGER_COST_ACCOUNTING_INVALID")
            actual_total += receipt_cost
            receipt_ids.add(receipt["receipt_id"])
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
                    "COST_RECEIPT_DUPLICATE",
                }
            ):
                raise Study3bLedgerError("LEDGER_COST_ACCOUNTING_INVALID")
            unresolved_cost = True
        else:
            raise Study3bLedgerError("LEDGER_COST_ACCOUNTING_INVALID")

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


def _make_verified_cost_receipt(
    reservation: object, transport_result: object
) -> _VerifiedStudy3bCostReceipt:
    """Derive a completion capability from the shared transport's safe reply."""

    if (
        type(reservation) is not Study3bReservation
        or type(transport_result) is not TransportResult
        or type(transport_result.http_status) is not int
        or transport_result.http_status != 200
        or type(transport_result.body) is not bytes
        or not 1 <= len(transport_result.body) <= MAX_RESPONSE_BYTES
    ):
        raise Study3bLedgerError("COST_RECEIPT_BINDING_MISMATCH")
    try:
        document = json.loads(
            transport_result.body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=int,
            parse_float=Decimal,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError, OverflowError):
        raise Study3bLedgerError("COST_RECEIPT_RESPONSE_INVALID") from None
    if type(document) is not dict:
        raise Study3bLedgerError("COST_RECEIPT_RESPONSE_INVALID")
    usage = document.get("usage")
    if type(usage) is not dict:
        raise Study3bLedgerError("COST_RECEIPT_RESPONSE_INVALID")
    safe_transport_usage = {
        key: value
        for key, value in usage.items()
        if type(key) is str
        and re.fullmatch(r"^[a-z_]{1,40}$", key) is not None
        and type(value) is int
        and value >= 0
    }
    if (
        document.get("model") != protocol.MODEL_ID
        or document.get("model") != transport_result.returned_model_id
        or type(document.get("provider")) is not str
        or document.get("provider") != transport_result.upstream_provider
        or type(document.get("id")) is not str
        or document.get("id") != transport_result.generation_id
        or type(transport_result.usage) is not dict
        or safe_transport_usage != transport_result.usage
    ):
        raise Study3bLedgerError("COST_RECEIPT_RESPONSE_IDENTITY_MISMATCH")

    cost = _provider_cost_decimal(usage.get("cost"))
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    completion_details = usage.get("completion_tokens_details")
    reasoning_flat = usage.get("reasoning_tokens")
    reasoning_nested = (
        completion_details.get("reasoning_tokens")
        if type(completion_details) is dict
        else None
    )
    if reasoning_flat is not None and reasoning_nested is not None and reasoning_flat != reasoning_nested:
        raise Study3bLedgerError("COST_RECEIPT_USAGE_INVALID")
    reasoning_tokens = reasoning_flat if reasoning_flat is not None else reasoning_nested
    if (
        cost is None
        or type(prompt_tokens) is not int
        or not 0 <= prompt_tokens <= 2_147_483_647
        or type(completion_tokens) is not int
        or not 0 <= completion_tokens <= 2_147_483_647
        or type(reasoning_tokens) is not int
        or not 0 <= reasoning_tokens <= 2_147_483_647
        or reasoning_tokens > completion_tokens
    ):
        raise Study3bLedgerError("COST_RECEIPT_USAGE_INVALID")

    binding = {
        "study_id": reservation.study_id,
        "manifest_sha256": reservation.manifest_sha256,
        "scene_id": reservation.scene_id,
        "attempt_number": reservation.attempt_number,
        "request_sha256": reservation.request_sha256,
    }
    response_sha256 = hashlib.sha256(transport_result.body).hexdigest()
    cost_text = format(cost, "f")
    if "." in cost_text:
        cost_text = cost_text.rstrip("0").rstrip(".")
    if not cost_text:
        cost_text = "0"
    generation_id = document["id"]
    payload = {
        "receipt_id": generation_id,
        "study_id": reservation.study_id,
        "manifest_sha256": reservation.manifest_sha256,
        "scene_id": reservation.scene_id,
        "attempt_number": reservation.attempt_number,
        "http_status": transport_result.http_status,
        "request_sha256": reservation.request_sha256,
        "response_sha256": response_sha256,
        "returned_model_id": document["model"],
        "upstream_provider": document["provider"],
        "generation_id": generation_id,
        "cost_usd": cost_text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
    }
    receipt, _actual_cost = _validate_cost_receipt_payload(payload, binding)
    return _VerifiedStudy3bCostReceipt(
        payload_items=tuple((key, receipt[key]) for key in sorted(receipt)),
        reservation_token=reservation._token,
        _seal=_VERIFIED_COST_RECEIPT_SEAL,
    )


def _provider_cost_decimal(value: object) -> Decimal | None:
    if type(value) is int:
        amount = Decimal(value)
    elif type(value) is Decimal:
        amount = value
    else:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    parts = amount.as_tuple()
    if (
        type(parts.exponent) is not int
        or max(0, -parts.exponent) > 12
        or len(parts.digits) + max(0, parts.exponent) > 64
    ):
        return None
    normalized = format(amount, "f")
    if len(normalized) > 64:
        return None
    return amount


def _validate_verified_cost_receipt(
    value: object,
    reservation: dict[str, Any],
    *,
    reservation_token: str,
) -> tuple[dict[str, Any], Decimal]:
    if (
        type(value) is not _VerifiedStudy3bCostReceipt
        or value._seal is not _VERIFIED_COST_RECEIPT_SEAL
        or value.reservation_token != reservation_token
    ):
        raise Study3bLedgerError("COST_RECEIPT_INVALID")
    return _validate_cost_receipt_payload(dict(value.payload_items), reservation)


def _validate_cost_receipt_payload(
    value: object, reservation: dict[str, Any]
) -> tuple[dict[str, Any], Decimal]:
    fields = {
        "receipt_id",
        "study_id",
        "manifest_sha256",
        "scene_id",
        "attempt_number",
        "http_status",
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
        raise Study3bLedgerError("COST_RECEIPT_INVALID")
    text_fields = (
        "receipt_id",
        "study_id",
        "manifest_sha256",
        "scene_id",
        "request_sha256",
        "response_sha256",
        "returned_model_id",
        "upstream_provider",
        "generation_id",
        "cost_usd",
    )
    if any(type(value.get(name)) is not str for name in text_fields):
        raise Study3bLedgerError("COST_RECEIPT_INVALID")
    if (
        value["study_id"] != protocol.STUDY_ID
        or value["manifest_sha256"] != reservation["manifest_sha256"]
        or value["scene_id"] != reservation["scene_id"]
        or type(value.get("attempt_number")) is not int
        or value["attempt_number"] != reservation["attempt_number"]
        or type(value.get("http_status")) is not int
        or value["http_status"] != 200
        or value["request_sha256"] != reservation["request_sha256"]
        or _SHA256_RE.fullmatch(value["manifest_sha256"]) is None
        or _SHA256_RE.fullmatch(value["request_sha256"]) is None
        or _SHA256_RE.fullmatch(value["response_sha256"]) is None
        or value["returned_model_id"] != protocol.MODEL_ID
        or _PROVIDER_RE.fullmatch(value["upstream_provider"]) is None
        or value["upstream_provider"].casefold()
        in {"unknown", "none", "n/a", "unset"}
        or _GENERATION_ID_RE.fullmatch(value["generation_id"]) is None
        or value["receipt_id"] != value["generation_id"]
    ):
        raise Study3bLedgerError("COST_RECEIPT_BINDING_MISMATCH")
    for field_name in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
        if type(value.get(field_name)) is not int or value[field_name] < 0:
            raise Study3bLedgerError("COST_RECEIPT_USAGE_INVALID")
    if value["reasoning_tokens"] > value["completion_tokens"]:
        raise Study3bLedgerError("COST_RECEIPT_USAGE_INVALID")
    amount = _parse_cost(value["cost_usd"])
    if amount is None:
        raise Study3bLedgerError("COST_RECEIPT_AMOUNT_INVALID")
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


def _format_cost(value: Decimal) -> str:
    return format(value, "f")


def _parse_record(raw: bytes) -> dict[str, Any]:
    value = json.loads(
        raw.decode("ascii"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )
    if type(value) is not dict or _canonical_bytes(value) != raw:
        raise ValueError("record must be a canonical object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


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
        raise Study3bLedgerError("LEDGER_RECORD_INVALID") from None


def _append_record(
    descriptor: int,
    payload: dict[str, Any],
    previous_sha256: str | None,
    ledger_path: Path,
) -> str:
    record = dict(payload)
    record["previous_sha256"] = previous_sha256
    digest = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    record["record_sha256"] = digest
    contents = _canonical_bytes(record) + b"\n"
    if os.fstat(descriptor).st_size + len(contents) > MAX_LEDGER_BYTES:
        raise Study3bLedgerError("LEDGER_SIZE_LIMIT")
    _assert_write_target(ledger_path, "append")
    _write_all(descriptor, contents)
    return digest


def _write_all(descriptor: int, contents: bytes) -> None:
    offset = 0
    while offset < len(contents):
        written = os.write(descriptor, contents[offset:])
        if written <= 0:
            raise OSError("short ledger write")
        offset += written


def _read_descriptor(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit
    while remaining:
        chunk = os.read(descriptor, min(remaining, 65536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _lock_contents() -> bytes:
    return (LOCK_IDENTITY + "\n").encode("ascii")


def _coerce_root_path(value: Path | str) -> Path:
    try:
        raw = os.fspath(value)
    except (TypeError, ValueError, OSError):
        raise Study3bLedgerError("LEDGER_ROOT_INVALID") from None
    if type(raw) is not str or "\\" in raw:
        raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    slash_parts = raw.split("/")
    if ".." in slash_parts:
        raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = protocol.REPO_ROOT / candidate
    try:
        relative = candidate.relative_to(protocol.REPO_ROOT)
    except ValueError:
        raise Study3bLedgerError("LEDGER_ROOT_INVALID") from None
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    return candidate


def _validate_root_path(path: Path, *, synthetic: bool) -> tuple[str, ...]:
    candidate = _coerce_root_path(path)
    if not synthetic:
        if candidate != DEFAULT_LEDGER_ROOT:
            raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    else:
        try:
            relative = candidate.relative_to(protocol.REPO_ROOT)
            relative.relative_to(Path(PREP_ROOT_RELATIVE))
        except ValueError:
            raise Study3bLedgerError("LEDGER_ROOT_INVALID") from None
        if candidate == DEFAULT_LEDGER_ROOT or not candidate.name.startswith("synthetic-"):
            raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    relative = candidate.relative_to(protocol.REPO_ROOT)
    return tuple(relative.parts)


def _assert_write_target(path: Path, action: str) -> None:
    assert_study3b_write_target(
        path,
        repository_root=protocol.REPO_ROOT,
        action=action,
    )


def _open_root_parent(root_parts: tuple[str, ...]) -> tuple[int, str]:
    if not root_parts:
        raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    descriptor = os.open(protocol.REPO_ROOT, _ROOT_FLAGS)
    try:
        root_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise Study3bLedgerError("LEDGER_ROOT_INVALID")
        for part in root_parts[:-1]:
            child = _open_child_directory(descriptor, part)
            os.close(descriptor)
            descriptor = child
        return descriptor, root_parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _open_root_directory(root_parts: tuple[str, ...]) -> int:
    parent_fd, leaf = _open_root_parent(root_parts)
    try:
        descriptor = _open_child_directory(parent_fd, leaf)
    except FileNotFoundError:
        raise Study3bLedgerError("LEDGER_MISSING_OR_UNSAFE") from None
    finally:
        os.close(parent_fd)
    metadata = os.fstat(descriptor)
    if metadata.st_mode & 0o077 or metadata.st_mode & 0o700 != 0o700:
        os.close(descriptor)
        raise Study3bLedgerError("LEDGER_ROOT_PERMISSIONS_INVALID")
    return descriptor


def _open_child_directory(parent_fd: int, name: str) -> int:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    descriptor = os.open(name, _ROOT_FLAGS, dir_fd=parent_fd)
    after = os.fstat(descriptor)
    named_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(after.st_mode)
        or stat.S_ISLNK(named_after.st_mode)
        or (after.st_dev, after.st_ino) != (named_after.st_dev, named_after.st_ino)
    ):
        os.close(descriptor)
        raise Study3bLedgerError("LEDGER_ROOT_INVALID")
    return descriptor


def _verify_named_regular_file(root_fd: int, name: str, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    try:
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
        raise Study3bLedgerError("LEDGER_FILE_UNSAFE") from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_ISLNK(named.st_mode)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        or opened.st_nlink != 1
        or opened.st_mode & 0o077
        or opened.st_mode & 0o600 != 0o600
    ):
        raise Study3bLedgerError("LEDGER_FILE_UNSAFE")
    if hasattr(os, "geteuid") and opened.st_uid != os.geteuid():
        raise Study3bLedgerError("LEDGER_FILE_OWNER_INVALID")


def _fsync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError:
        raise Study3bLedgerError("LEDGER_DIRECTORY_SYNC_FAILED") from None


__all__ = [
    "DEFAULT_LEDGER_ROOT",
    "HARD_CEILING_USD",
    "LEDGER_NAME",
    "LEDGER_ROOT_RELATIVE",
    "LOCK_IDENTITY",
    "LOCK_NAME",
    "Study3bCompletion",
    "Study3bLedger",
    "Study3bLedgerError",
    "Study3bReservation",
    "request_sha256_for_scene",
]
