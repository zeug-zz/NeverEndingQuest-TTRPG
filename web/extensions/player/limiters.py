# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Thread-safe reusable resource limiters for player HTTP and gameplay paths."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .limits import (
    EXPENSIVE_READS_PER_SESSION_PER_WINDOW,
    LOGIN_ATTEMPTS_PER_WINDOW,
    LOGIN_ATTEMPT_WINDOW_SECONDS,
    MAX_ACTIVE_SESSIONS,
    MAX_ADMITTED_PLAYER_COMMANDS,
    MAX_HTTP_BODY_BYTES,
    MAX_PASSWORD_BYTES,
    MAX_PLAYER_INPUT_BYTES,
    MAX_REPLAY_BYTES,
    MAX_REPLAY_EVENTS,
    MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION,
    MAX_SNAPSHOT_BYTES,
    MAX_SOCKETIO_EVENT_BYTES,
    MEDIA_READS_PER_SESSION_PER_WINDOW,
    PLAYER_INPUTS_PER_SESSION_PER_WINDOW,
    PLAYER_INPUT_WINDOW_SECONDS,
    READ_WINDOW_SECONDS,
)


@dataclass(frozen=True, slots=True)
class LimitDecision:
    """Bounded result suitable for conversion into a typed player error."""

    allowed: bool
    code: str | None = None


@dataclass(slots=True)
class _SessionCounters:
    session_epoch: str | None = None
    inputs: deque[float] = field(default_factory=deque)
    expensive_reads: deque[float] = field(default_factory=deque)
    media_reads: deque[float] = field(default_factory=deque)
    receipts: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _RetainedRequest:
    fingerprint: str
    receipt: object


class _RollingLoginWindow:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.lock = threading.Lock()
        self.attempts: deque[float] = deque()

    def allow(self) -> bool:
        now = self.clock()
        with self.lock:
            PlayerLimiters._discard_before(
                self.attempts,
                now - LOGIN_ATTEMPT_WINDOW_SECONDS,
            )
            if len(self.attempts) >= LOGIN_ATTEMPTS_PER_WINDOW:
                return False
            self.attempts.append(now)
            return True


_PROCESS_LOGIN_WINDOW = _RollingLoginWindow(time.time)


class PlayerLimiters:
    """Keep player resource bounds centralized, finite, and thread-safe."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        login_window: _RollingLoginWindow | None = None,
    ) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._login_window = login_window or _RollingLoginWindow(clock)
        self._sessions: dict[str, _SessionCounters] = {}
        self._pending_commands = 0

    def allow_login_attempt(self) -> bool:
        """Consume one process-wide login attempt before password KDF work."""
        return self._login_window.allow()

    @staticmethod
    def process_login_window() -> _RollingLoginWindow:
        """Return the shared production login window for distinct listener objects."""
        return _PROCESS_LOGIN_WINDOW

    @staticmethod
    def http_body_allowed(size_bytes: int) -> bool:
        return (
            isinstance(size_bytes, int)
            and not isinstance(size_bytes, bool)
            and 0 <= size_bytes <= MAX_HTTP_BODY_BYTES
        )

    @staticmethod
    def password_allowed(password: object) -> bool:
        if not isinstance(password, str):
            return False
        if len(password) > MAX_PASSWORD_BYTES:
            return False
        try:
            return len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES
        except UnicodeEncodeError:
            return False

    @staticmethod
    def event_payload_allowed(payload: object) -> bool:
        if isinstance(payload, bytes):
            return len(payload) <= MAX_SOCKETIO_EVENT_BYTES
        try:
            encoder = json.JSONEncoder(
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            total_size = 0
            for chunk in encoder.iterencode(payload):
                total_size += len(chunk.encode("utf-8"))
                if total_size > MAX_SOCKETIO_EVENT_BYTES:
                    return False
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError):
            return False
        return True

    @staticmethod
    def snapshot_allowed(snapshot: bytes) -> bool:
        return isinstance(snapshot, bytes) and len(snapshot) <= MAX_SNAPSHOT_BYTES

    @staticmethod
    def replay_allowed(events: Sequence[bytes]) -> bool:
        if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
            return False
        if len(events) > MAX_REPLAY_EVENTS:
            return False
        total_bytes = 0
        for event in events:
            if not isinstance(event, bytes):
                return False
            total_bytes += len(event)
            if total_bytes > MAX_REPLAY_BYTES:
                return False
        return True

    def register_session(self, session_id: str, session_epoch: str | None = None) -> bool:
        if not isinstance(session_id, str) or not session_id:
            return False
        selected_epoch = session_id if session_epoch is None else session_epoch
        if not isinstance(selected_epoch, str) or not selected_epoch:
            return False
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return session_epoch is None or existing.session_epoch == selected_epoch
            if len(self._sessions) >= MAX_ACTIVE_SESSIONS:
                return False
            self._sessions[session_id] = _SessionCounters(session_epoch=selected_epoch)
            return True

    def close_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear_sessions(self) -> None:
        """Clear per-session state while preserving the process login window."""
        with self._lock:
            self._sessions.clear()

    def admit_input(self, session_id: str, text: str) -> LimitDecision:
        if not isinstance(text, str):
            return LimitDecision(False, "invalid_input")
        if len(text) > MAX_PLAYER_INPUT_BYTES:
            return LimitDecision(False, "input_too_large")
        try:
            encoded_size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            return LimitDecision(False, "invalid_input")
        if encoded_size > MAX_PLAYER_INPUT_BYTES:
            return LimitDecision(False, "input_too_large")

        now = self._clock()
        with self._lock:
            counters = self._sessions.get(session_id)
            if counters is None:
                return LimitDecision(False, "unknown_session")
            self._discard_before(counters.inputs, now - PLAYER_INPUT_WINDOW_SECONDS)
            if len(counters.inputs) >= PLAYER_INPUTS_PER_SESSION_PER_WINDOW:
                return LimitDecision(False, "input_rate_limited")
            counters.inputs.append(now)
            return LimitDecision(True)

    def allow_snapshot_read(self, session_id: str) -> bool:
        return self._allow_read(session_id, "expensive_reads", EXPENSIVE_READS_PER_SESSION_PER_WINDOW)

    def allow_expensive_read(self, session_id: str) -> bool:
        return self._allow_read(session_id, "expensive_reads", EXPENSIVE_READS_PER_SESSION_PER_WINDOW)

    def allow_media_read(self, session_id: str) -> bool:
        return self._allow_read(session_id, "media_reads", MEDIA_READS_PER_SESSION_PER_WINDOW)

    def try_admit_command(self) -> bool:
        """Acquire the single process-wide pending player command slot."""
        with self._lock:
            if self._pending_commands >= MAX_ADMITTED_PLAYER_COMMANDS:
                return False
            self._pending_commands += 1
            return True

    def finish_command(self) -> bool:
        with self._lock:
            if self._pending_commands <= 0:
                return False
            self._pending_commands -= 1
            return True

    def retain_receipt(self, session_id: str, request_id: str, receipt: object) -> bool:
        if not isinstance(request_id, str) or not request_id:
            return False
        with self._lock:
            counters = self._sessions.get(session_id)
            if counters is None:
                return False
            if request_id in counters.receipts:
                return True
            if len(counters.receipts) >= MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION:
                return False
            counters.receipts[request_id] = receipt
            return True

    def run_deduplicated_request(
        self,
        session_id: str,
        session_epoch: str,
        request_id: str,
        fingerprint: str,
        make_receipt: Callable[[], object],
    ) -> tuple[str, object | None]:
        """Atomically deduplicate and retain one original admission receipt."""
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(session_epoch, str)
            or not session_epoch
            or not isinstance(request_id, str)
            or not request_id
            or not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or not callable(make_receipt)
        ):
            return "invalid", None
        with self._lock:
            counters = self._sessions.get(session_id)
            if counters is None:
                return "unknown_session", None
            if counters.session_epoch != session_epoch:
                return "session_epoch_mismatch", None
            existing = counters.receipts.get(request_id)
            if existing is not None:
                if not isinstance(existing, _RetainedRequest):
                    return "conflict", None
                if existing.fingerprint != fingerprint:
                    return "conflict", None
                return "duplicate", existing.receipt
            if len(counters.receipts) >= MAX_RETAINED_INPUT_RECEIPTS_PER_SESSION:
                return "capacity", None
            receipt = make_receipt()
            counters.receipts[request_id] = _RetainedRequest(fingerprint, receipt)
            return "new", receipt

    def get_receipt(self, session_id: str, request_id: str) -> object | None:
        with self._lock:
            counters = self._sessions.get(session_id)
            if counters is None:
                return None
            receipt = counters.receipts.get(request_id)
            return receipt.receipt if isinstance(receipt, _RetainedRequest) else receipt

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def receipt_count(self, session_id: str) -> int:
        with self._lock:
            counters = self._sessions.get(session_id)
            return 0 if counters is None else len(counters.receipts)

    def _allow_read(self, session_id: str, counter_name: str, limit: int) -> bool:
        now = self._clock()
        with self._lock:
            counters = self._sessions.get(session_id)
            if counters is None:
                return False
            queue = getattr(counters, counter_name)
            self._discard_before(queue, now - READ_WINDOW_SECONDS)
            if len(queue) >= limit:
                return False
            queue.append(now)
            return True

    @staticmethod
    def _discard_before(queue: deque[float], cutoff: float) -> None:
        while queue and queue[0] <= cutoff:
            queue.popleft()
