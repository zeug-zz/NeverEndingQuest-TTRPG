# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded player event cursors, snapshot boundaries, replay, and input dedup."""

from __future__ import annotations

import hashlib
import re
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Mapping

from .contracts import (
    EnvelopeValidationError,
    canonical_json_bytes,
    extract_request_id,
    make_error_envelope,
    make_event_envelope,
    make_receipt_envelope,
    make_replay_envelope,
    make_resync_envelope,
    make_snapshot_envelope,
    validate_command_envelope,
)
from .gateway import PlayerGateway, PlayerInputAdmission, PlayerInputCommand
from .limits import MAX_REPLAY_BYTES, MAX_REPLAY_EVENTS, MAX_SOCKETIO_EVENT_BYTES
from .projections import sanitize_player_projection

_IDENTITY_RE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_REPLAY_SIZE_EPOCH = "E" * 43


@dataclass(frozen=True, slots=True)
class PublishedPlayerEvent:
    """Safe event facts retained for replay and immediate socket publication."""

    event_id: int
    revision: int
    event_type: str
    projection: Mapping[str, object]

    def for_session(self, instance_id: str, session_epoch: str) -> dict[str, object]:
        return make_event_envelope(
            instance_id,
            session_epoch,
            self.event_id,
            self.revision,
            self.event_type,
            self.projection,
        )


@dataclass(frozen=True, slots=True)
class _RetainedEvent:
    event: PublishedPlayerEvent
    encoded_bytes: int


class PlayerSyncCoordinator:
    """Serialize event publication with snapshot cursor capture and replay."""

    def __init__(self, instance_id: str) -> None:
        self._lock = threading.RLock()
        self._instance_id = _validated_identity(instance_id, "instance_id")
        self._next_event_id = 0
        self._events: deque[_RetainedEvent] = deque()
        self._replay_bytes = 0

    @property
    def instance_id(self) -> str:
        with self._lock:
            return self._instance_id

    @property
    def event_cursor(self) -> int:
        with self._lock:
            return self._next_event_id

    def reset_for_instance(self, instance_id: str) -> None:
        """Discard prior-instance replay state when listener identity rotates."""
        selected = _validated_identity(instance_id, "instance_id")
        with self._lock:
            if selected == self._instance_id:
                return
            self._instance_id = selected
            self._next_event_id = 0
            self._events.clear()
            self._replay_bytes = 0

    def capture_snapshot(
        self,
        session_epoch: str,
        snapshot_reader: Callable[[], object],
    ) -> dict[str, object]:
        """Read a projection and its cursor under the publication lock."""
        selected_epoch = _validated_identity(session_epoch, "session_epoch")
        with self._lock:
            return self._capture_snapshot_locked(selected_epoch, snapshot_reader)

    def publish_event(
        self,
        revision: int,
        event_type: str,
        projection: Mapping[str, object],
    ) -> PublishedPlayerEvent:
        """Assign a monotonic ID and append one safe event to the bounded window."""
        with self._lock:
            safe_projection = sanitize_player_projection(projection)
            event_id = self._next_event_id + 1
            event = PublishedPlayerEvent(
                event_id=event_id,
                revision=revision,
                event_type=event_type,
                projection=safe_projection,
            )
            sizing_envelope = event.for_session(self._instance_id, _REPLAY_SIZE_EPOCH)
            encoded_size = len(canonical_json_bytes(sizing_envelope, MAX_SOCKETIO_EVENT_BYTES))
            if encoded_size > MAX_REPLAY_BYTES:
                raise EnvelopeValidationError("event exceeds the replay byte bound")
            self._next_event_id = event_id
            self._events.append(_RetainedEvent(event, encoded_size))
            self._replay_bytes += encoded_size
            while (
                len(self._events) > MAX_REPLAY_EVENTS
                or self._replay_bytes > MAX_REPLAY_BYTES
            ):
                expired = self._events.popleft()
                self._replay_bytes -= expired.encoded_bytes
            return event

    def reconnect(
        self,
        client_instance_id: object,
        client_session_epoch: object,
        client_cursor: object,
        session_epoch: str,
        snapshot_reader: Callable[[], object],
    ) -> dict[str, object]:
        """Return contiguous replay or an explicit fresh-snapshot resync result."""
        current_epoch = _validated_identity(session_epoch, "session_epoch")
        with self._lock:
            reason = self._resync_reason_locked(
                client_instance_id,
                client_session_epoch,
                client_cursor,
                current_epoch,
            )
            if reason is not None:
                snapshot = self._capture_snapshot_locked(current_epoch, snapshot_reader)
                return make_resync_envelope(reason, snapshot)

            if not isinstance(client_cursor, int) or isinstance(client_cursor, bool):
                snapshot = self._capture_snapshot_locked(current_epoch, snapshot_reader)
                return make_resync_envelope("invalid_cursor", snapshot)
            events = [
                retained.event.for_session(self._instance_id, current_epoch)
                for retained in self._events
                if retained.event.event_id > client_cursor
            ]
            try:
                return make_replay_envelope(
                    self._instance_id,
                    current_epoch,
                    client_cursor,
                    self._next_event_id,
                    events,
                )
            except EnvelopeValidationError:
                snapshot = self._capture_snapshot_locked(current_epoch, snapshot_reader)
                return make_resync_envelope("event_gap", snapshot)

    def submit_command(
        self,
        payload: object,
        *,
        session_id: str,
        session_epoch: str,
        limiters: object,
        gateway: PlayerGateway,
    ) -> dict[str, object]:
        """Validate and deduplicate a command before calling the fail-closed seam."""
        current_epoch = _validated_identity(session_epoch, "session_epoch")
        request_id = extract_request_id(payload)
        try:
            command = validate_command_envelope(payload)
        except EnvelopeValidationError:
            if request_id is None:
                return make_error_envelope("invalid_command")
            try:
                fingerprint = _payload_fingerprint(payload)
            except EnvelopeValidationError:
                return make_error_envelope("invalid_command", request_id)
            receipt = self._deduplicate(
                limiters,
                session_id,
                current_epoch,
                request_id,
                fingerprint,
                lambda: make_receipt_envelope(
                    self.instance_id,
                    current_epoch,
                    request_id,
                    "rejected",
                    "invalid_command",
                ),
            )
            return receipt

        if command.instance_id != self.instance_id:
            return make_receipt_envelope(
                self.instance_id,
                current_epoch,
                command.request_id,
                "uncertain",
                "server_instance_changed",
            )
        if command.session_epoch != current_epoch:
            return make_receipt_envelope(
                self.instance_id,
                current_epoch,
                command.request_id,
                "uncertain",
                "session_epoch_changed",
            )

        fingerprint = hashlib.sha256(
            canonical_json_bytes(command.as_dict(), MAX_SOCKETIO_EVENT_BYTES)
        ).hexdigest()
        return self._deduplicate(
            limiters,
            session_id,
            current_epoch,
            command.request_id,
            fingerprint,
            lambda: self._admit_command(
                command,
                gateway,
                limiters=limiters,
                session_id=session_id,
            ),
        )

    def _admit_command(
        self,
        command: object,
        gateway: PlayerGateway,
        *,
        limiters: object,
        session_id: str,
    ) -> dict[str, object]:
        request_id = getattr(command, "request_id")
        admit_input = getattr(limiters, "admit_input", None)
        if not callable(admit_input):
            return make_receipt_envelope(
                self.instance_id,
                getattr(command, "session_epoch"),
                request_id,
                "rejected",
                "input_limiter_unavailable",
            )
        try:
            rate_decision = admit_input(session_id, getattr(command, "text"))
        except Exception:
            return make_receipt_envelope(
                self.instance_id,
                getattr(command, "session_epoch"),
                request_id,
                "rejected",
                "input_limiter_unavailable",
            )
        if getattr(rate_decision, "allowed", False) is not True:
            return make_receipt_envelope(
                self.instance_id,
                getattr(command, "session_epoch"),
                request_id,
                "rejected",
                "input_rate_limited",
            )
        try:
            admission = gateway.admit_input(
                PlayerInputCommand(
                    request_id=request_id,
                    character_name=getattr(command, "character_name"),
                    active_character_revision=getattr(command, "active_character_revision"),
                    text=getattr(command, "text"),
                )
            )
        except Exception:
            return make_receipt_envelope(
                self.instance_id,
                getattr(command, "session_epoch"),
                request_id,
                "uncertain",
                "runtime_admission_uncertain",
            )
        if not isinstance(admission, PlayerInputAdmission) or admission.request_id != request_id:
            return make_receipt_envelope(
                self.instance_id,
                getattr(command, "session_epoch"),
                request_id,
                "rejected",
                "invalid_gateway_receipt",
            )
        if admission.status not in {"accepted", "busy", "stale", "rejected"}:
            return make_receipt_envelope(
                self.instance_id,
                getattr(command, "session_epoch"),
                request_id,
                "rejected",
                "invalid_gateway_receipt",
            )
        return make_receipt_envelope(
            self.instance_id,
            getattr(command, "session_epoch"),
            request_id,
            admission.status,
        )

    def _deduplicate(
        self,
        limiters: object,
        session_id: str,
        session_epoch: str,
        request_id: str,
        fingerprint: str,
        make_receipt: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        process = getattr(limiters, "run_deduplicated_request", None)
        if not callable(process):
            return make_receipt_envelope(
                self.instance_id,
                session_epoch,
                request_id,
                "rejected",
                "deduplication_unavailable",
            )
        result, original = process(
            session_id,
            session_epoch,
            request_id,
            fingerprint,
            make_receipt,
        )
        if result in {"new", "duplicate"} and isinstance(original, Mapping):
            return dict(original)
        if result == "conflict":
            return make_receipt_envelope(
                self.instance_id,
                session_epoch,
                request_id,
                "rejected",
                "request_id_conflict",
            )
        if result == "capacity":
            return make_receipt_envelope(
                self.instance_id,
                session_epoch,
                request_id,
                "rejected",
                "receipt_capacity",
            )
        return make_receipt_envelope(
            self.instance_id,
            session_epoch,
            request_id,
            "rejected",
            "session_unavailable",
        )

    def _capture_snapshot_locked(
        self,
        session_epoch: str,
        snapshot_reader: Callable[[], object],
    ) -> dict[str, object]:
        snapshot = snapshot_reader()
        revision = getattr(snapshot, "revision", None)
        projection = getattr(snapshot, "projection", None)
        if not isinstance(projection, Mapping):
            raise EnvelopeValidationError("snapshot reader returned no projection")
        safe_projection = sanitize_player_projection(projection)
        return make_snapshot_envelope(
            self._instance_id,
            session_epoch,
            revision,
            self._next_event_id,
            safe_projection,
        )

    def _resync_reason_locked(
        self,
        client_instance_id: object,
        client_session_epoch: object,
        cursor: object,
        session_epoch: str,
    ) -> str | None:
        if client_instance_id != self._instance_id:
            return "instance_mismatch"
        if client_session_epoch != session_epoch:
            return "session_epoch_mismatch"
        if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
            return "invalid_cursor"
        if cursor > self._next_event_id:
            return "future_cursor"
        if cursor == self._next_event_id:
            return None
        if not self._events:
            return "cursor_expired"
        oldest_id = self._events[0].event.event_id
        if cursor < oldest_id - 1:
            return "cursor_expired"
        expected = cursor + 1
        for retained in self._events:
            event_id = retained.event.event_id
            if event_id <= cursor:
                continue
            if event_id != expected:
                return "event_gap"
            expected += 1
        if expected - 1 != self._next_event_id:
            return "event_gap"
        return None


def _validated_identity(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise EnvelopeValidationError(f"invalid {field}")
    return value


def _payload_fingerprint(payload: object) -> str:
    encoded = canonical_json_bytes(payload, MAX_SOCKETIO_EVENT_BYTES)
    return hashlib.sha256(encoded).hexdigest()
