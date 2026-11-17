# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded, redacted start-failure evidence for the owned serve child.

Nothing here runs on the success path. The helpers are called only after a
sharing start has already failed and before cleanup removes the profile state.
All text is redacted line by line and every collection has a fixed cap.
"""

# TABLETOP MODE: Host-only failure evidence; never part of a player projection.

from __future__ import annotations

import collections
import errno
import os
import stat
import threading
from pathlib import Path
from typing import Sequence

from web.extensions.opentunnel_sharing.identity_bootstrap import redact

MAX_TAIL_LINES = 200
MAX_TAIL_BYTES = 64 * 1024
MAX_LINE_CHARS = 512
MAX_RAW_LINE_BYTES = 4096
MAX_TIMELINE_ENTRIES = 256
MAX_STATUS_LINES = 2
MAX_DAEMON_LOG_FILE_BYTES = 8 * 1024 * 1024
DAEMON_LOG_READ_WINDOW_BYTES = 256 * 1024
MAX_PROFILE_DIRECTORIES = 8
MIN_SECRET_LENGTH = 3


class OutputTailRing:
    """Thread-safe last-N-lines ring over the child's merged output."""

    def __init__(
        self,
        max_lines: int = MAX_TAIL_LINES,
        max_bytes: int = MAX_TAIL_BYTES,
    ) -> None:
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._lines: collections.deque[bytes] = collections.deque()
        self._bytes = 0
        self._partial = bytearray()
        self._dropped = 0

    def feed(self, chunk: bytes) -> None:
        with self._lock:
            self._partial.extend(chunk)
            while True:
                index = self._partial.find(b"\n")
                if index < 0:
                    break
                line = bytes(self._partial[:index])
                del self._partial[: index + 1]
                self._append_locked(line)
            if len(self._partial) >= MAX_RAW_LINE_BYTES:
                self._append_locked(bytes(self._partial))
                self._partial.clear()

    def snapshot(self) -> tuple[list[bytes], int]:
        """Return the retained lines (including a trailing partial) and drops."""
        with self._lock:
            lines = list(self._lines)
            dropped = self._dropped
            if self._partial:
                lines.append(bytes(self._partial))
        return lines[-self._max_lines :], dropped + max(0, len(lines) - self._max_lines)

    def _append_locked(self, line: bytes) -> None:
        line = line.rstrip(b"\r")[:MAX_RAW_LINE_BYTES]
        self._lines.append(line)
        self._bytes += len(line) + 1
        while len(self._lines) > self._max_lines or self._bytes > self._max_bytes:
            removed = self._lines.popleft()
            self._bytes -= len(removed) + 1
            self._dropped += 1


def sanitize_line(raw: bytes | str, secrets: Sequence[str]) -> str:
    """Return one ASCII, redacted, length-capped line with no newlines."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    text = "".join(
        character if " " <= character <= "~" else "?" for character in text
    )
    ordered = sorted(
        (
            item
            for item in secrets
            if isinstance(item, str) and len(item) >= MIN_SECRET_LENGTH
        ),
        key=len,
        reverse=True,
    )
    for secret in ordered:
        text = text.replace(secret, "<redacted>")
    return redact(text, ordered)[:MAX_LINE_CHARS]


def sanitize_text_block(text: str, secrets: Sequence[str]) -> str:
    """Redact a short multi-line value into a single bounded line."""
    return sanitize_line(" | ".join(text.splitlines()), secrets)


def build_stream(
    raw_lines: Sequence[bytes],
    secrets: Sequence[str],
    *,
    dropped: int = 0,
    source_reason: str = "ok",
) -> dict[str, object]:
    """Redact raw lines per line and keep the last 200 lines / 64 KiB."""
    if source_reason != "ok":
        return {
            "reason": source_reason,
            "lines": [],
            "line_count": 0,
            "truncated": False,
        }
    try:
        selected = list(raw_lines)[-MAX_TAIL_LINES:]
        lines = [sanitize_line(line, secrets) for line in selected]
        truncated = dropped > 0 or len(raw_lines) > len(selected)
        total = sum(len(line) + 1 for line in lines)
        while lines and total > MAX_TAIL_BYTES:
            total -= len(lines[0]) + 1
            del lines[0]
            truncated = True
    except Exception:
        return {
            "reason": "redaction_failed",
            "lines": [],
            "line_count": 0,
            "truncated": False,
        }
    return {
        "reason": "ok",
        "lines": lines,
        "line_count": len(lines),
        "truncated": truncated,
    }


def read_daemon_log_tail(
    state_home: Path, profile: str
) -> tuple[list[bytes], str]:
    """Read the tail of the profile daemon.log without following symlinks.

    Every component below ``state_home`` is opened relative to the previous
    descriptor with O_NOFOLLOW; the file must be a regular file owned by the
    current user and no larger than MAX_DAEMON_LOG_FILE_BYTES. Only the last
    DAEMON_LOG_READ_WINDOW_BYTES are read. Returns (lines, reason_code).
    """
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | nofollow | os.O_CLOEXEC
    file_flags = os.O_RDONLY | nofollow | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
    opened: list[int] = []
    try:
        try:
            state_fd = os.open(state_home, directory_flags)
        except OSError as exc:
            return [], _open_reason(exc, "no_state_home")
        opened.append(state_fd)
        try:
            parent_fd = os.open("opentunnel", directory_flags, dir_fd=state_fd)
        except OSError as exc:
            return [], _open_reason(exc, "missing")
        opened.append(parent_fd)
        try:
            names = sorted(os.listdir(parent_fd))
        except OSError:
            return [], "unreadable"
        ordered = [profile] if profile in names else []
        ordered.extend(
            name for name in names if name != profile and not name.startswith(".")
        )
        best_reason = "missing"
        for name in ordered[:MAX_PROFILE_DIRECTORIES]:
            lines, reason = _read_profile_log(name, parent_fd, directory_flags, file_flags)
            if reason == "ok":
                return lines, "ok"
            if best_reason == "missing":
                best_reason = reason
        return [], best_reason
    finally:
        for descriptor in opened:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _read_profile_log(
    name: str, parent_fd: int, directory_flags: int, file_flags: int
) -> tuple[list[bytes], str]:
    try:
        profile_fd = os.open(name, directory_flags, dir_fd=parent_fd)
    except OSError as exc:
        return [], _open_reason(exc, "missing")
    file_fd = -1
    try:
        try:
            file_fd = os.open("daemon.log", file_flags, dir_fd=profile_fd)
        except OSError as exc:
            return [], _open_reason(exc, "missing")
        try:
            metadata = os.fstat(file_fd)
        except OSError:
            return [], "unreadable"
        if not stat.S_ISREG(metadata.st_mode):
            return [], "not_regular"
        if metadata.st_uid != os.getuid():
            return [], "not_owned"
        if metadata.st_size > MAX_DAEMON_LOG_FILE_BYTES:
            return [], "oversized"
        offset = max(0, metadata.st_size - DAEMON_LOG_READ_WINDOW_BYTES)
        try:
            os.lseek(file_fd, offset, os.SEEK_SET)
            payload = b""
            while len(payload) < DAEMON_LOG_READ_WINDOW_BYTES:
                chunk = os.read(
                    file_fd, DAEMON_LOG_READ_WINDOW_BYTES - len(payload)
                )
                if not chunk:
                    break
                payload += chunk
        except OSError:
            return [], "unreadable"
        lines = payload.split(b"\n")
        if offset > 0 and lines:
            del lines[0]
        if lines and lines[-1] == b"":
            lines.pop()
        return [line.rstrip(b"\r")[:MAX_RAW_LINE_BYTES] for line in lines], "ok"
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass
        try:
            os.close(profile_fd)
        except OSError:
            pass


def _open_reason(exc: OSError, missing_reason: str) -> str:
    if exc.errno == errno.ENOENT:
        return missing_reason
    if exc.errno == errno.ELOOP:
        return "symlink"
    if exc.errno == errno.ENOTDIR:
        return "not_directory"
    return "unreadable"
