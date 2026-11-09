# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fixed, append-only Study 2 attempt ledger.

The ledger has no run-scoped path or reset operation. Its caller must separately
validate both approvals before the one-time initializer is used. Dispatches
only append to an already initialized ledger; a missing or unsafe ledger fails
closed.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
from typing import Any


STUDY_ID = "mise-en-scene-study2-20261109"
SCENE_ORDER = (
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
)
STUDY2_ROOT_RELATIVE = (
    "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2"
)
REPO_ROOT = Path(__file__).resolve().parents[3]
STUDY2_ROOT = REPO_ROOT / STUDY2_ROOT_RELATIVE
LEDGER_NAME = "study-attempt-ledger.jsonl"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID = "openai/gpt-6-luna"
MAX_LEDGER_BYTES = 64 * 1024
LEDGER_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class Study2LedgerError(RuntimeError):
    """A bounded, non-sensitive ledger failure."""


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


class Study2Ledger:
    """Operate on one fixed-root ledger; never initialize during dispatch."""

    def __init__(self) -> None:
        self.study_root = STUDY2_ROOT
        self.path = self.study_root / LEDGER_NAME
        self._lock = _thread_lock(self.path)

    def initialize(self, binding: dict[str, Any]) -> None:
        """Create one empty bound header with exclusive creation and fsync."""

        _validate_binding(binding)
        with self._lock:
            _ensure_project_directory(self.study_root)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            flags |= nofollow
            try:
                descriptor = os.open(self.path, flags, 0o600)
            except FileExistsError:
                raise Study2LedgerError("LEDGER_ALREADY_EXISTS") from None
            except OSError:
                raise Study2LedgerError("LEDGER_INITIALIZATION_FAILED") from None

            try:
                os.fchmod(descriptor, 0o600)
                opened = os.fstat(descriptor)
                named = os.lstat(self.path)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                ):
                    raise Study2LedgerError("LEDGER_UNSAFE_FILE")
                header = {
                    "event": "header",
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "study_id": STUDY_ID,
                    "allocation_scope": "studywide",
                    "attempt_cap": len(SCENE_ORDER),
                    "scene_order": list(SCENE_ORDER),
                    "binding": binding,
                }
                _append_record(descriptor, header, None)
                os.fsync(descriptor)
                _fsync_directory(self.study_root)
            except Study2LedgerError:
                raise
            except OSError:
                raise Study2LedgerError("LEDGER_INITIALIZATION_FAILED") from None
            finally:
                os.close(descriptor)

    def reserve(
        self,
        binding: dict[str, Any],
        *,
        scene_id: str,
        run_id: str,
        run_root_relative: str,
        request_sha256: str,
    ) -> int:
        """Append a reservation only to an existing, intact ledger."""

        _validate_binding(binding)
        if (
            type(scene_id) is not str
            or scene_id not in SCENE_ORDER
            or not _valid_run_identity(run_id, run_root_relative)
            or type(request_sha256) is not str
            or not _SHA256_RE.fullmatch(request_sha256)
        ):
            raise Study2LedgerError("RESERVATION_IDENTITY_INVALID")
        with self._locked_file() as descriptor:
            records = self._read_records(descriptor, expected_binding=binding)
            reservations = [row for row in records[1:] if row["event"] == "reservation"]
            results = [row for row in records[1:] if row["event"] == "result"]
            if len(reservations) != len(results):
                raise Study2LedgerError("LEDGER_PENDING_RESERVATION")
            if any(row.get("stop_study") is True for row in results):
                raise Study2LedgerError("LEDGER_STUDY_STOPPED")
            attempt_number = len(reservations) + 1
            if (
                attempt_number > len(SCENE_ORDER)
                or SCENE_ORDER[attempt_number - 1] != scene_id
                or any(row["scene_id"] == scene_id for row in reservations)
            ):
                raise Study2LedgerError("SCENE_ALLOCATION_UNAVAILABLE")
            payload = {
                "event": "reservation",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": STUDY_ID,
                "attempt_number": attempt_number,
                "scene_id": scene_id,
                "run_id": run_id,
                "run_root_relative": run_root_relative,
                "request_sha256": request_sha256,
                "binding": binding,
            }
            previous_hash = records[-1]["record_sha256"]
            _append_record(descriptor, payload, previous_hash)
            return attempt_number

    def complete(
        self,
        binding: dict[str, Any],
        *,
        attempt_number: int,
        scene_id: str,
        run_id: str,
        run_root_relative: str,
        request_sha256: str,
        outcome: str,
        failure_reason: str | None,
        stop_study: bool,
        http_status: int | None,
        response_path: str | None,
        response_sha256: str | None,
        returned_model_id: str | None,
        upstream_provider: str | None,
        generation_id: str | None,
        usage: dict[str, Any] | None,
    ) -> None:
        """Append a bounded result matched to the one pending reservation."""

        _validate_binding(binding)
        if (
            type(attempt_number) is not int
            or not 1 <= attempt_number <= len(SCENE_ORDER)
            or scene_id not in SCENE_ORDER
            or not _valid_run_identity(run_id, run_root_relative)
            or outcome not in ("succeeded", "failed")
            or type(stop_study) is not bool
            or (http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599))
            or (
                failure_reason is not None
                and (
                    type(failure_reason) is not str
                    or not re.fullmatch(r"[a-z_]{1,64}", failure_reason)
                )
            )
            or (
                response_sha256 is not None
                and (
                    type(response_sha256) is not str
                    or not _SHA256_RE.fullmatch(response_sha256)
                )
            )
            or (response_sha256 is None) != (response_path is None)
            or (response_path is not None and not _valid_relative_response_path(response_path, run_id))
        ):
            raise Study2LedgerError("RESULT_IDENTITY_INVALID")
        if type(request_sha256) is not str or not _SHA256_RE.fullmatch(request_sha256):
            raise Study2LedgerError("RESULT_IDENTITY_INVALID")

        receipt = {
            "returned_model_id": returned_model_id,
            "upstream_provider": upstream_provider,
            "generation_id": generation_id,
            "usage": usage,
        }
        if not _valid_receipt_metadata(receipt):
            raise Study2LedgerError("RESULT_RECEIPT_INVALID")

        with self._locked_file() as descriptor:
            records = self._read_records(descriptor, expected_binding=binding)
            reservations = [row for row in records[1:] if row["event"] == "reservation"]
            results = [row for row in records[1:] if row["event"] == "result"]
            if len(reservations) != len(results) + 1:
                raise Study2LedgerError("LEDGER_PENDING_RESERVATION_MISMATCH")
            reservation = reservations[-1]
            if (
                reservation["attempt_number"] != attempt_number
                or reservation["scene_id"] != scene_id
                or reservation["run_id"] != run_id
                or reservation["run_root_relative"] != run_root_relative
                or reservation["request_sha256"] != request_sha256
                or reservation["binding"] != binding
            ):
                raise Study2LedgerError("LEDGER_PENDING_RESERVATION_MISMATCH")
            payload = {
                "event": "result",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "study_id": STUDY_ID,
                "attempt_number": attempt_number,
                "scene_id": scene_id,
                "run_id": run_id,
                "run_root_relative": run_root_relative,
                "request_sha256": request_sha256,
                "outcome": outcome,
                "failure_reason": failure_reason,
                "stop_study": stop_study,
                "http_status": http_status,
                "response_path": response_path,
                "response_sha256": response_sha256,
                "receipt": receipt,
                "binding": binding,
            }
            _append_record(descriptor, payload, records[-1]["record_sha256"])

    def _locked_file(self):
        """Yield a stable existing file while holding thread and process locks."""

        class _LockContext:
            def __init__(context_self, ledger: Study2Ledger) -> None:
                context_self.ledger = ledger
                context_self.descriptor: int | None = None

            def __enter__(context_self) -> int:
                _validate_existing_project_directory(context_self.ledger.study_root)
                flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(context_self.ledger.path, flags)
                except OSError:
                    raise Study2LedgerError("LEDGER_MISSING_OR_UNSAFE") from None
                try:
                    opened = os.fstat(descriptor)
                    named = os.lstat(context_self.ledger.path)
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or stat.S_ISLNK(named.st_mode)
                        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                    ):
                        raise Study2LedgerError("LEDGER_MISSING_OR_UNSAFE")
                    if opened.st_size > MAX_LEDGER_BYTES:
                        raise Study2LedgerError("LEDGER_SIZE_LIMIT")
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                    named_after_lock = os.lstat(context_self.ledger.path)
                    if (
                        stat.S_ISLNK(named_after_lock.st_mode)
                        or (opened.st_dev, opened.st_ino)
                        != (named_after_lock.st_dev, named_after_lock.st_ino)
                    ):
                        raise Study2LedgerError("LEDGER_MISSING_OR_UNSAFE")
                    context_self.descriptor = descriptor
                    return descriptor
                except BaseException:
                    os.close(descriptor)
                    raise

            def __exit__(context_self, exc_type, exc, traceback) -> None:
                if context_self.descriptor is not None:
                    try:
                        fcntl.flock(context_self.descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(context_self.descriptor)

        class _ThreadAndFileLockContext:
            def __init__(context_self, ledger: Study2Ledger) -> None:
                context_self.ledger = ledger
                context_self.file_context: Any = None

            def __enter__(context_self) -> int:
                context_self.ledger._lock.acquire()
                context_self.file_context = _LockContext(context_self.ledger)
                try:
                    return context_self.file_context.__enter__()
                except BaseException:
                    context_self.ledger._lock.release()
                    raise

            def __exit__(context_self, exc_type, exc, traceback) -> None:
                try:
                    context_self.file_context.__exit__(exc_type, exc, traceback)
                finally:
                    context_self.ledger._lock.release()

        return _ThreadAndFileLockContext(self)

    def _read_records(
        self, descriptor: int, *, expected_binding: dict[str, Any]
    ) -> list[dict[str, Any]]:
        metadata = os.fstat(descriptor)
        if metadata.st_size <= 0 or metadata.st_size > MAX_LEDGER_BYTES:
            raise Study2LedgerError("LEDGER_EMPTY_OR_OVERSIZED")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                raise Study2LedgerError("LEDGER_TRUNCATED")
            chunks.append(chunk)
            remaining -= len(chunk)
        contents = b"".join(chunks)
        if not contents.endswith(b"\n"):
            raise Study2LedgerError("LEDGER_TRUNCATED")
        try:
            records = [
                _parse_record(line)
                for line in contents.splitlines()
            ]
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise Study2LedgerError("LEDGER_CORRUPT") from None
        if not records:
            raise Study2LedgerError("LEDGER_CORRUPT")
        _validate_records(records, expected_binding)
        return records


def _validate_records(records: list[dict[str, Any]], expected_binding: dict[str, Any]) -> None:
    header = records[0]
    if set(header) != {
        "event", "schema_version", "study_id", "allocation_scope", "attempt_cap",
        "scene_order", "binding", "previous_sha256", "record_sha256",
    }:
        raise Study2LedgerError("LEDGER_HEADER_INVALID")
    if (
        header.get("event") != "header"
        or header.get("schema_version") != LEDGER_SCHEMA_VERSION
        or header.get("study_id") != STUDY_ID
        or header.get("allocation_scope") != "studywide"
        or header.get("attempt_cap") != len(SCENE_ORDER)
        or header.get("scene_order") != list(SCENE_ORDER)
        or header.get("binding") != expected_binding
    ):
        raise Study2LedgerError("LEDGER_BINDING_MISMATCH")

    reservations: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    previous_hash: str | None = None
    stopped = False
    for index, record in enumerate(records):
        record_hash = record.get("record_sha256")
        if type(record_hash) is not str or not _SHA256_RE.fullmatch(record_hash):
            raise Study2LedgerError("LEDGER_RECORD_HASH_INVALID")
        unhashed = dict(record)
        del unhashed["record_sha256"]
        if _sha256(_canonical_bytes(unhashed)) != record_hash or record.get("previous_sha256") != previous_hash:
            raise Study2LedgerError("LEDGER_CHAIN_INVALID")
        if index == 0:
            previous_hash = record_hash
            continue
        event = record.get("event")
        if event == "reservation":
            if set(record) != {
                "event", "schema_version", "study_id", "attempt_number", "scene_id",
                "run_id", "run_root_relative",
                "request_sha256", "binding", "previous_sha256", "record_sha256",
            }:
                raise Study2LedgerError("LEDGER_RESERVATION_INVALID")
            expected_attempt = len(reservations) + 1
            if (
                stopped
                or len(reservations) != len(results)
                or expected_attempt > len(SCENE_ORDER)
                or record.get("schema_version") != LEDGER_SCHEMA_VERSION
                or record.get("study_id") != STUDY_ID
                or record.get("attempt_number") != expected_attempt
                or record.get("scene_id") != SCENE_ORDER[expected_attempt - 1]
                or not _valid_run_identity(record.get("run_id"), record.get("run_root_relative"))
                or record.get("binding") != expected_binding
                or type(record.get("request_sha256")) is not str
                or not _SHA256_RE.fullmatch(record["request_sha256"])
            ):
                raise Study2LedgerError("LEDGER_RESERVATION_SEQUENCE_INVALID")
            reservations.append(record)
        elif event == "result":
            if set(record) != {
                "event", "schema_version", "study_id", "attempt_number", "scene_id",
                "run_id", "run_root_relative",
                "request_sha256", "outcome", "failure_reason", "stop_study", "http_status",
                "response_path", "response_sha256", "receipt", "binding",
                "previous_sha256", "record_sha256",
            }:
                raise Study2LedgerError("LEDGER_RESULT_INVALID")
            if not reservations or len(reservations) != len(results) + 1:
                raise Study2LedgerError("LEDGER_RESULT_WITHOUT_RESERVATION")
            reservation = reservations[-1]
            if (
                record.get("schema_version") != LEDGER_SCHEMA_VERSION
                or record.get("study_id") != STUDY_ID
                or record.get("attempt_number") != reservation.get("attempt_number")
                or record.get("scene_id") != reservation.get("scene_id")
                or record.get("run_id") != reservation.get("run_id")
                or record.get("run_root_relative") != reservation.get("run_root_relative")
                or record.get("request_sha256") != reservation.get("request_sha256")
                or record.get("binding") != expected_binding
                or record.get("outcome") not in ("succeeded", "failed")
                or type(record.get("stop_study")) is not bool
                or (
                    record.get("failure_reason") is not None
                    and (
                        type(record["failure_reason"]) is not str
                        or not re.fullmatch(r"[a-z_]{1,64}", record["failure_reason"])
                    )
                )
                or (record.get("http_status") is not None and (type(record["http_status"]) is not int or not 100 <= record["http_status"] <= 599))
                or ((record.get("response_path") is None) != (record.get("response_sha256") is None))
                or (record.get("response_sha256") is not None and not _SHA256_RE.fullmatch(str(record["response_sha256"])))
                or (record.get("response_path") is not None and (type(record["response_path"]) is not str or not _valid_relative_response_path(record["response_path"], reservation["run_id"])))
                or not _valid_receipt_metadata(record.get("receipt"))
                or (
                    record.get("outcome") == "succeeded"
                    and (
                        record.get("failure_reason") is not None
                        or record.get("stop_study") is not False
                        or record.get("http_status") != 200
                        or record.get("response_path") is None
                        or record.get("receipt", {}).get("returned_model_id") != MODEL_ID
                        or record.get("receipt", {}).get("upstream_provider") is None
                        or record.get("receipt", {}).get("generation_id") is None
                        or record.get("receipt", {}).get("usage") is None
                    )
                )
                or (
                    record.get("outcome") == "failed"
                    and record.get("failure_reason") is None
                )
                or (
                    record.get("failure_reason")
                    in {
                        "transport_receipt_invalid",
                        "response_missing_or_oversized",
                        "returned_identity_or_usage_missing",
                        "receipt_does_not_match_raw_response",
                        "returned_model_mismatch",
                        "http_status_invalid",
                        "http_status_error",
                        "transport_failure",
                        "response_persist_failed",
                    }
                    and record.get("stop_study") is not True
                )
            ):
                raise Study2LedgerError("LEDGER_RESULT_BINDING_INVALID")
            results.append(record)
            stopped = stopped or record["stop_study"]
        else:
            raise Study2LedgerError("LEDGER_EVENT_INVALID")
        previous_hash = record_hash


def _valid_receipt_metadata(value: object) -> bool:
    if type(value) is not dict or set(value) != {
        "returned_model_id", "upstream_provider", "generation_id", "usage"
    }:
        return False
    for key in ("returned_model_id", "upstream_provider", "generation_id"):
        item = value[key]
        if item is not None and (
            type(item) is not str
            or not item
            or len(item) > 256
            or not item.isascii()
            or any(ord(character) < 32 or ord(character) == 127 for character in item)
        ):
            return False
    usage = value["usage"]
    return usage is None or _valid_usage_tree(usage)


def _valid_usage_tree(value: object, depth: int = 0) -> bool:
    if type(value) is not dict or not value or len(value) > 32 or depth > 4:
        return False
    for key, item in value.items():
        if type(key) is not str or re.fullmatch(r"[a-z_]{1,40}", key) is None:
            return False
        if key == "is_byok":
            if depth != 0 or type(item) is not bool:
                return False
        elif type(item) in (int, float):
            if item < 0 or (type(item) is float and not math.isfinite(item)):
                return False
        elif type(item) is dict:
            if not _valid_usage_tree(item, depth + 1):
                return False
        elif type(item) is list:
            if len(item) > 32 or any(
                type(child) not in (int, float)
                or child < 0
                or (type(child) is float and not math.isfinite(child))
                for child in item
            ):
                return False
        else:
            return False
    if depth == 0 and any(
        type(value.get(key)) is not int or value[key] < 0
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        return False
    return True


def _valid_relative_response_path(value: str, run_id: str) -> bool:
    try:
        path = PurePosixPath(value)
    except TypeError:
        return False
    expected_prefix = "runs/" + run_id + "/responses/"
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and not any(part in ("", ".", "..") for part in path.parts)
        and value.startswith(expected_prefix)
        and value.endswith(".provider-response.json")
        and value.isascii()
    )


def _validate_binding(value: object) -> None:
    fields = {
        "study_id", "manifest_sha256", "protocol_version", "protocol_sha256",
        "artifact_hashes", "model_id", "endpoint", "availability_attestation_sha256",
        "availability_raw_listing_sha256", "owner_approval_sha256",
        "overseer_approval_sha256", "authority_record_id", "study_root_relative",
    }
    if type(value) is not dict or set(value) != fields:
        raise Study2LedgerError("LEDGER_BINDING_INVALID")
    if value.get("study_id") != STUDY_ID:
        raise Study2LedgerError("LEDGER_BINDING_INVALID")
    if value.get("study_root_relative") != STUDY2_ROOT_RELATIVE:
        raise Study2LedgerError("LEDGER_ROOT_MISMATCH")
    if value.get("model_id") != MODEL_ID or value.get("endpoint") != OPENROUTER_ENDPOINT:
        raise Study2LedgerError("LEDGER_BINDING_INVALID")
    for key in (
        "manifest_sha256", "protocol_sha256", "availability_attestation_sha256",
        "availability_raw_listing_sha256", "owner_approval_sha256", "overseer_approval_sha256",
    ):
        if type(value.get(key)) is not str or _SHA256_RE.fullmatch(value[key]) is None:
            raise Study2LedgerError("LEDGER_BINDING_INVALID")
    artifacts = value.get("artifact_hashes")
    if (
        type(artifacts) is not dict
        or not artifacts
        or any(
            type(path) is not str
            or not path.isascii()
            or type(digest) is not str
            or _SHA256_RE.fullmatch(digest) is None
            for path, digest in artifacts.items()
        )
    ):
        raise Study2LedgerError("LEDGER_BINDING_INVALID")
    for key in ("protocol_version", "model_id", "endpoint", "authority_record_id"):
        item = value.get(key)
        if type(item) is not str or not item or len(item) > 512 or not item.isascii():
            raise Study2LedgerError("LEDGER_BINDING_INVALID")


def _append_record(descriptor: int, payload: dict[str, Any], previous_hash: str | None) -> None:
    record = dict(payload)
    record["previous_sha256"] = previous_hash
    record["record_sha256"] = _sha256(_canonical_bytes(record))
    contents = _canonical_bytes(record) + b"\n"
    if os.fstat(descriptor).st_size + len(contents) > MAX_LEDGER_BYTES:
        raise Study2LedgerError("LEDGER_SIZE_LIMIT")
    offset = 0
    while offset < len(contents):
        written = os.write(descriptor, contents[offset:])
        if written <= 0:
            raise Study2LedgerError("LEDGER_APPEND_FAILED")
        offset += written
    os.fsync(descriptor)


def _parse_record(contents: bytes) -> dict[str, Any]:
    value = json.loads(contents.decode("ascii"), object_pairs_hook=_reject_duplicate_keys)
    if type(value) is not dict:
        raise ValueError("record is not an object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


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
        raise Study2LedgerError("LEDGER_RECORD_INVALID") from None


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _valid_run_identity(run_id: object, run_root_relative: object) -> bool:
    return (
        type(run_id) is str
        and _RUN_ID_RE.fullmatch(run_id) is not None
        and type(run_root_relative) is str
        and run_root_relative == STUDY2_ROOT_RELATIVE + "/runs/" + run_id
    )


def _ensure_project_directory(path: Path) -> None:
    """Create the test/runtime directory without following any symlink."""

    try:
        repo_root = Path(__file__).resolve().parents[3]
        candidate = Path(os.path.abspath(path))
        relative = candidate.relative_to(repo_root)
    except (OSError, ValueError):
        raise Study2LedgerError("LEDGER_ROOT_INVALID") from None
    current = repo_root
    try:
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                current.mkdir(mode=0o700)
                metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise Study2LedgerError("LEDGER_ROOT_INVALID")
    except Study2LedgerError:
        raise
    except OSError:
        raise Study2LedgerError("LEDGER_ROOT_INVALID") from None


def _validate_existing_project_directory(path: Path) -> None:
    try:
        repo_root = Path(__file__).resolve().parents[3]
        candidate = Path(os.path.abspath(path))
        relative = candidate.relative_to(repo_root)
        current = repo_root
        for part in relative.parts:
            current = current / part
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise Study2LedgerError("LEDGER_ROOT_INVALID")
    except Study2LedgerError:
        raise
    except (OSError, ValueError):
        raise Study2LedgerError("LEDGER_ROOT_INVALID") from None


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise Study2LedgerError("LEDGER_DIRECTORY_SYNC_FAILED") from None
    try:
        os.fsync(descriptor)
    except OSError:
        raise Study2LedgerError("LEDGER_DIRECTORY_SYNC_FAILED") from None
    finally:
        os.close(descriptor)


__all__ = ["Study2Ledger", "Study2LedgerError"]
