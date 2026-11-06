# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Strict, bounded version-1 envelopes for player gameplay synchronization."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .limits import MAX_PLAYER_INPUT_BYTES, MAX_REPLAY_BYTES, MAX_REPLAY_EVENTS
from .limits import MAX_SNAPSHOT_BYTES, MAX_SOCKETIO_EVENT_BYTES
from .projections import (
    PLAYER_EVENT_TYPE_ALLOWLIST,
    ProjectionError,
    sanitize_player_projection,
)

PROTOCOL_VERSION = 1
MAX_IDENTITY_BYTES = 128
MAX_REQUEST_ID_BYTES = 128
MAX_CHARACTER_NAME_BYTES = 128
MAX_RECEIPT_CODE_BYTES = 64
RECEIPT_STATUSES = frozenset(
    {"accepted", "busy", "stale", "rejected", "uncertain", "duplicate"}
)
RESYNC_REASONS = frozenset(
    {
        "cursor_expired",
        "event_gap",
        "future_cursor",
        "instance_mismatch",
        "invalid_cursor",
        "session_epoch_mismatch",
    }
)

COMMAND_FIELDS = frozenset(
    {
        "schema_version",
        "instance_id",
        "session_epoch",
        "request_id",
        "character_name",
        "active_character_revision",
        "text",
    }
)
SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "instance_id",
        "session_epoch",
        "revision",
        "event_cursor",
        "projection",
    }
)
EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "instance_id",
        "session_epoch",
        "event_id",
        "revision",
        "type",
        "projection",
    }
)
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "instance_id",
        "session_epoch",
        "request_id",
        "status",
    }
)
SNAPSHOT_REQUEST_FIELDS = frozenset(
    {"schema_version", "instance_id", "session_epoch"}
)
ACTIVE_PC_SELECTION_FIELDS = frozenset(
    {
        "schema_version",
        "instance_id",
        "session_epoch",
        "character_name",
        "expected_revision",
    }
)
REPLAY_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "instance_id",
        "session_epoch",
        "after_cursor",
        "event_cursor",
        "events",
    }
)
RESYNC_FIELDS = frozenset(
    {"schema_version", "kind", "reason", "snapshot"}
)

_IDENTITY_RE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_RECEIPT_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MAX_INTEGER = (1 << 63) - 1


class EnvelopeValidationError(ValueError):
    """A player synchronization envelope failed strict contract validation."""


class EnvelopeTooLargeError(EnvelopeValidationError):
    """A valid JSON payload exceeded its configured serialized byte bound."""


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    schema_version: int
    instance_id: str
    session_epoch: str
    request_id: str
    character_name: str
    active_character_revision: int
    text: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "instance_id": self.instance_id,
            "session_epoch": self.session_epoch,
            "request_id": self.request_id,
            "character_name": self.character_name,
            "active_character_revision": self.active_character_revision,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class SnapshotRequestEnvelope:
    schema_version: int
    instance_id: str
    session_epoch: str


@dataclass(frozen=True, slots=True)
class ActivePCSelectionEnvelope:
    schema_version: int
    instance_id: str
    session_epoch: str
    character_name: str
    expected_revision: int


def canonical_json_bytes(value: object, max_bytes: int) -> bytes:
    """Serialize a JSON value deterministically and enforce its byte bound."""
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes < 1
        or not _is_json_mapping_tree(value, max_nodes=max_bytes + 1)
    ):
        raise EnvelopeValidationError("payload is not a JSON object tree")
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        chunks: list[bytes] = []
        total_size = 0
        for chunk in encoder.iterencode(value):
            encoded_chunk = chunk.encode("ascii")
            total_size += len(encoded_chunk)
            if total_size > max_bytes:
                raise EnvelopeTooLargeError("payload exceeds its configured byte bound")
            chunks.append(encoded_chunk)
        encoded = b"".join(chunks)
    except EnvelopeValidationError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError) as exc:
        raise EnvelopeValidationError("payload is not serializable JSON") from exc
    return encoded


def validate_command_envelope(value: object) -> CommandEnvelope:
    """Validate an inbound command without admitting it to the runtime."""
    raw = _require_mapping(value, COMMAND_FIELDS, MAX_SOCKETIO_EVENT_BYTES)
    _validate_version(raw)
    instance_id = _identity(raw.get("instance_id"), "instance_id")
    session_epoch = _identity(raw.get("session_epoch"), "session_epoch")
    request_id = _request_id(raw.get("request_id"))
    character_name = _character_name(raw.get("character_name"))
    revision = _nonnegative_integer(raw.get("active_character_revision"))
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip() or "\x00" in text:
        raise EnvelopeValidationError("text must be a non-empty string")
    try:
        text_bytes = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EnvelopeValidationError("text must be valid UTF-8") from exc
    if len(text_bytes) > MAX_PLAYER_INPUT_BYTES:
        raise EnvelopeValidationError("text exceeds the configured input bound")
    if any(not character.isprintable() and character not in "\r\n\t" for character in text):
        raise EnvelopeValidationError("text contains unsupported control characters")
    command = CommandEnvelope(
        schema_version=PROTOCOL_VERSION,
        instance_id=instance_id,
        session_epoch=session_epoch,
        request_id=request_id,
        character_name=character_name,
        active_character_revision=revision,
        text=text,
    )
    canonical_json_bytes(command.as_dict(), MAX_SOCKETIO_EVENT_BYTES)
    return command


def validate_snapshot_request_envelope(value: object) -> SnapshotRequestEnvelope:
    """Validate the exact, identity-bound N1 request for a fresh snapshot."""
    raw = _require_mapping(value, SNAPSHOT_REQUEST_FIELDS, MAX_SOCKETIO_EVENT_BYTES)
    _validate_version(raw)
    return SnapshotRequestEnvelope(
        schema_version=PROTOCOL_VERSION,
        instance_id=_identity(raw.get("instance_id"), "instance_id"),
        session_epoch=_identity(raw.get("session_epoch"), "session_epoch"),
    )


def validate_active_pc_selection_envelope(value: object) -> ActivePCSelectionEnvelope:
    """Validate an identity-bound CAS selection without an input command ID."""
    raw = _require_mapping(
        value,
        ACTIVE_PC_SELECTION_FIELDS,
        MAX_SOCKETIO_EVENT_BYTES,
    )
    _validate_version(raw)
    return ActivePCSelectionEnvelope(
        schema_version=PROTOCOL_VERSION,
        instance_id=_identity(raw.get("instance_id"), "instance_id"),
        session_epoch=_identity(raw.get("session_epoch"), "session_epoch"),
        character_name=_character_name(raw.get("character_name")),
        expected_revision=_nonnegative_integer(raw.get("expected_revision")),
    )


def make_snapshot_envelope(
    instance_id: str,
    session_epoch: str,
    revision: int,
    event_cursor: int,
    projection: Mapping[str, object],
) -> dict[str, object]:
    """Create a versioned snapshot after rebuilding its safe projection."""
    safe_projection = _safe_projection(projection)
    result: dict[str, object] = {
        "schema_version": PROTOCOL_VERSION,
        "instance_id": _identity(instance_id, "instance_id"),
        "session_epoch": _identity(session_epoch, "session_epoch"),
        "revision": _nonnegative_integer(revision),
        "event_cursor": _nonnegative_integer(event_cursor),
        "projection": safe_projection,
    }
    validate_snapshot_envelope(result)
    return result


def validate_snapshot_envelope(value: object) -> dict[str, object]:
    """Validate a server-built snapshot, rejecting unknown envelope fields."""
    raw = _require_mapping(value, SNAPSHOT_FIELDS, MAX_SNAPSHOT_BYTES)
    _validate_version(raw)
    _identity(raw.get("instance_id"), "instance_id")
    _identity(raw.get("session_epoch"), "session_epoch")
    _nonnegative_integer(raw.get("revision"))
    _nonnegative_integer(raw.get("event_cursor"))
    projection = raw.get("projection")
    if not isinstance(projection, Mapping):
        raise EnvelopeValidationError("snapshot projection must be an object")
    safe_projection = _safe_projection(projection)
    if dict(projection) != safe_projection:
        raise EnvelopeValidationError("snapshot projection contains unknown fields")
    result = dict(raw)
    result["projection"] = safe_projection
    canonical_json_bytes(result, MAX_SNAPSHOT_BYTES)
    return result


def make_event_envelope(
    instance_id: str,
    session_epoch: str,
    event_id: int,
    revision: int,
    event_type: str,
    projection: Mapping[str, object],
) -> dict[str, object]:
    """Create a monotonic, identity-bound player event envelope."""
    result: dict[str, object] = {
        "schema_version": PROTOCOL_VERSION,
        "instance_id": _identity(instance_id, "instance_id"),
        "session_epoch": _identity(session_epoch, "session_epoch"),
        "event_id": _positive_integer(event_id),
        "revision": _nonnegative_integer(revision),
        "type": event_type,
        "projection": _safe_projection(projection),
    }
    validate_event_envelope(result)
    return result


def validate_event_envelope(value: object) -> dict[str, object]:
    """Validate one bounded event and its exact version-1 envelope fields."""
    raw = _require_mapping(value, EVENT_FIELDS, MAX_SOCKETIO_EVENT_BYTES)
    _validate_version(raw)
    _identity(raw.get("instance_id"), "instance_id")
    _identity(raw.get("session_epoch"), "session_epoch")
    _positive_integer(raw.get("event_id"))
    _nonnegative_integer(raw.get("revision"))
    event_type = raw.get("type")
    if not isinstance(event_type, str) or event_type not in PLAYER_EVENT_TYPE_ALLOWLIST:
        raise EnvelopeValidationError("unsupported player event type")
    projection = raw.get("projection")
    if not isinstance(projection, Mapping):
        raise EnvelopeValidationError("event projection must be an object")
    safe_projection = _safe_projection(projection)
    if dict(projection) != safe_projection:
        raise EnvelopeValidationError("event projection contains unknown fields")
    result = dict(raw)
    result["projection"] = safe_projection
    canonical_json_bytes(result, MAX_SOCKETIO_EVENT_BYTES)
    return result


def make_receipt_envelope(
    instance_id: str,
    session_epoch: str,
    request_id: str,
    status: Literal["accepted", "busy", "stale", "rejected", "uncertain", "duplicate"],
    code: str | None = None,
) -> dict[str, object]:
    """Create a bounded admission-only receipt."""
    result: dict[str, object] = {
        "schema_version": PROTOCOL_VERSION,
        "instance_id": _identity(instance_id, "instance_id"),
        "session_epoch": _identity(session_epoch, "session_epoch"),
        "request_id": _request_id(request_id),
        "status": status,
    }
    if code is not None:
        if (
            not isinstance(code, str)
            or len(code) > MAX_RECEIPT_CODE_BYTES
            or _RECEIPT_CODE_RE.fullmatch(code) is None
        ):
            raise EnvelopeValidationError("invalid receipt code")
        result["code"] = code
    validate_receipt_envelope(result)
    return result


def validate_receipt_envelope(value: object) -> dict[str, object]:
    """Validate an admission receipt, including its optional bounded code."""
    raw = _require_mapping(value, RECEIPT_FIELDS, MAX_SOCKETIO_EVENT_BYTES, {"code"})
    _validate_version(raw)
    _identity(raw.get("instance_id"), "instance_id")
    _identity(raw.get("session_epoch"), "session_epoch")
    _request_id(raw.get("request_id"))
    status = raw.get("status")
    if not isinstance(status, str) or status not in RECEIPT_STATUSES:
        raise EnvelopeValidationError("unsupported receipt status")
    code = raw.get("code")
    if code is not None and (
        not isinstance(code, str)
        or len(code) > MAX_RECEIPT_CODE_BYTES
        or _RECEIPT_CODE_RE.fullmatch(code) is None
    ):
        raise EnvelopeValidationError("invalid receipt code")
    canonical_json_bytes(dict(raw), MAX_SOCKETIO_EVENT_BYTES)
    return dict(raw)


def make_replay_envelope(
    instance_id: str,
    session_epoch: str,
    after_cursor: int,
    event_cursor: int,
    events: list[dict[str, object]],
) -> dict[str, object]:
    """Create a bounded contiguous-replay response envelope."""
    selected_after_cursor = _nonnegative_integer(after_cursor)
    selected_event_cursor = _nonnegative_integer(event_cursor)
    if not isinstance(events, list) or len(events) > MAX_REPLAY_EVENTS:
        raise EnvelopeValidationError("replay event count exceeds its bound")
    safe_events = [validate_event_envelope(event) for event in events]
    selected_instance = _identity(instance_id, "instance_id")
    selected_epoch = _identity(session_epoch, "session_epoch")
    for expected, event in enumerate(safe_events, start=selected_after_cursor + 1):
        if (
            event["event_id"] != expected
            or event["instance_id"] != selected_instance
            or event["session_epoch"] != selected_epoch
        ):
            raise EnvelopeValidationError("replay event range is not contiguous")
    if safe_events and safe_events[-1]["event_id"] != selected_event_cursor:
        raise EnvelopeValidationError("replay cursor does not match the final event")
    if not safe_events and selected_after_cursor != selected_event_cursor:
        raise EnvelopeValidationError("empty replay has different cursors")
    result: dict[str, object] = {
        "schema_version": PROTOCOL_VERSION,
        "kind": "replay",
        "instance_id": selected_instance,
        "session_epoch": selected_epoch,
        "after_cursor": selected_after_cursor,
        "event_cursor": selected_event_cursor,
        "events": safe_events,
    }
    validate_replay_envelope(result)
    return result


def validate_replay_envelope(value: object) -> dict[str, object]:
    """Validate a replay response and both its count and serialized bound."""
    raw = _require_mapping(value, REPLAY_FIELDS, MAX_REPLAY_BYTES)
    _validate_version(raw)
    if raw.get("kind") != "replay":
        raise EnvelopeValidationError("invalid replay kind")
    _identity(raw.get("instance_id"), "instance_id")
    _identity(raw.get("session_epoch"), "session_epoch")
    after_cursor = _nonnegative_integer(raw.get("after_cursor"))
    event_cursor = _nonnegative_integer(raw.get("event_cursor"))
    events = raw.get("events")
    if not isinstance(events, list) or len(events) > MAX_REPLAY_EVENTS:
        raise EnvelopeValidationError("replay event count exceeds its bound")
    checked = [validate_event_envelope(event) for event in events]
    if after_cursor is None or event_cursor is None:
        raise EnvelopeValidationError("invalid replay cursor")
    instance_id = _identity(raw.get("instance_id"), "instance_id")
    session_epoch = _identity(raw.get("session_epoch"), "session_epoch")
    for expected, event in enumerate(checked, start=after_cursor + 1):
        if (
            event["event_id"] != expected
            or event["instance_id"] != instance_id
            or event["session_epoch"] != session_epoch
        ):
            raise EnvelopeValidationError("replay event range is not contiguous")
    if checked and checked[-1]["event_id"] != event_cursor:
        raise EnvelopeValidationError("replay cursor does not match the final event")
    if not checked and after_cursor != event_cursor:
        raise EnvelopeValidationError("empty replay has different cursors")
    result = dict(raw)
    result["events"] = checked
    canonical_json_bytes(result, MAX_REPLAY_BYTES)
    return result


def make_resync_envelope(reason: str, snapshot: Mapping[str, object]) -> dict[str, object]:
    """Wrap a fresh authoritative snapshot with an explicit resync reason."""
    if not isinstance(reason, str) or reason not in RESYNC_REASONS:
        raise EnvelopeValidationError("unsupported resynchronization reason")
    result: dict[str, object] = {
        "schema_version": PROTOCOL_VERSION,
        "kind": "resync_required",
        "reason": reason,
        "snapshot": validate_snapshot_envelope(snapshot),
    }
    return validate_resync_envelope(result)


def validate_resync_envelope(value: object) -> dict[str, object]:
    """Validate an explicit resync outcome with its fresh bounded snapshot."""
    raw = _require_mapping(value, RESYNC_FIELDS, MAX_SNAPSHOT_BYTES)
    _validate_version(raw)
    if raw.get("kind") != "resync_required":
        raise EnvelopeValidationError("invalid resynchronization kind")
    reason = raw.get("reason")
    if not isinstance(reason, str) or reason not in RESYNC_REASONS:
        raise EnvelopeValidationError("unsupported resynchronization reason")
    snapshot = raw.get("snapshot")
    checked_snapshot = validate_snapshot_envelope(snapshot)
    result = dict(raw)
    result["snapshot"] = checked_snapshot
    canonical_json_bytes(result, MAX_SNAPSHOT_BYTES)
    return result


def make_error_envelope(code: str, request_id: str | None = None) -> dict[str, object]:
    """Create a minimal bounded error for input that cannot receive a receipt."""
    if not isinstance(code, str) or _RECEIPT_CODE_RE.fullmatch(code) is None:
        raise EnvelopeValidationError("invalid error code")
    result: dict[str, object] = {"schema_version": PROTOCOL_VERSION, "code": code}
    if request_id is not None:
        result["request_id"] = _request_id(request_id)
    canonical_json_bytes(result, MAX_SOCKETIO_EVENT_BYTES)
    return result


def extract_request_id(value: object) -> str | None:
    """Read only a syntactically valid bounded request ID from a bad envelope."""
    if not isinstance(value, Mapping):
        return None
    try:
        return _request_id(value.get("request_id"))
    except EnvelopeValidationError:
        return None


def _require_mapping(
    value: object,
    required: frozenset[str],
    max_bytes: int,
    optional: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EnvelopeValidationError("envelope must be an object with string keys")
    raw = dict(value)
    keys = set(raw)
    if keys - (required | optional) or required - keys:
        raise EnvelopeValidationError("envelope fields do not match the versioned contract")
    canonical_json_bytes(raw, max_bytes)
    return raw


def _validate_version(value: Mapping[str, object]) -> None:
    version = value.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != PROTOCOL_VERSION:
        raise EnvelopeValidationError("unsupported schema version")


def _identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_IDENTITY_BYTES
        or _IDENTITY_RE.fullmatch(value) is None
    ):
        raise EnvelopeValidationError(f"invalid {field}")
    return value


def _request_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_REQUEST_ID_BYTES
        or _REQUEST_ID_RE.fullmatch(value) is None
    ):
        raise EnvelopeValidationError("invalid request_id")
    return value


def _character_name(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise EnvelopeValidationError("invalid character_name")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise EnvelopeValidationError("invalid character_name") from exc
    if (
        size > MAX_CHARACTER_NAME_BYTES
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or not value.isprintable()
    ):
        raise EnvelopeValidationError("invalid character_name")
    return value


def _nonnegative_integer(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > _MAX_INTEGER
    ):
        raise EnvelopeValidationError("expected a bounded non-negative integer")
    return value


def _positive_integer(value: object) -> int:
    result = _nonnegative_integer(value)
    if result == 0:
        raise EnvelopeValidationError("expected a positive integer")
    return result


def _safe_projection(value: Mapping[str, object]) -> dict[str, object]:
    try:
        result = sanitize_player_projection(value)
    except (ProjectionError, TypeError, ValueError, RecursionError) as exc:
        raise EnvelopeValidationError("invalid player projection") from exc
    canonical_json_bytes(result, MAX_SNAPSHOT_BYTES)
    return result


def _is_json_mapping_tree(value: object, *, max_nodes: int) -> bool:
    """Reject non-JSON objects, non-string keys, cycles, and unbounded depth."""
    seen: set[int] = set()
    pending: list[tuple[object, int]] = [(value, 0)]
    remaining_nodes = max_nodes
    while pending:
        current, depth = pending.pop()
        if depth > 64 or remaining_nodes <= 0:
            return False
        remaining_nodes -= 1
        if current is None or isinstance(current, bool):
            continue
        if isinstance(current, str):
            if len(current) > max_nodes:
                return False
            continue
        if isinstance(current, int):
            if abs(current) > _MAX_INTEGER:
                return False
            continue
        if isinstance(current, float):
            if current != current or current in (float("inf"), float("-inf")):
                return False
            continue
        if isinstance(current, Mapping):
            if len(current) > max_nodes:
                return False
            identity = id(current)
            if identity in seen:
                return False
            seen.add(identity)
            for key, item in current.items():
                if not isinstance(key, str) or len(key) > max_nodes:
                    return False
                pending.append((item, depth + 1))
            continue
        if isinstance(current, list):
            if len(current) > max_nodes:
                return False
            identity = id(current)
            if identity in seen:
                return False
            seen.add(identity)
            pending.extend((item, depth + 1) for item in current)
            continue
        return False
    return True
