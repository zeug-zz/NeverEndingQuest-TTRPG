# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded, character-bound admission into the existing runtime input queue.

The injected host echo callback also updates the bounded host transcript cache
(`add_to_message_cache` -> `save_message_cache`). This is the same small,
host-owned cache write used for ordinary host input, not game/mechanical
persistence.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from collections.abc import Callable, Mapping
from typing import Protocol

from .gateway import PlayerInputAdmission, PlayerInputCommand, PlayerSnapshot
from .limits import MAX_PENDING_RUNTIME_INPUTS, MAX_PLAYER_INPUT_BYTES

_LOGGER = logging.getLogger(__name__)


class RuntimeInputQueue(Protocol):
    """The narrow queue surface used by the player boundary."""

    def qsize(self) -> int:
        """Return the current approximate pending item count."""

    def put_nowait(self, item: str) -> None:
        """Insert an input without waiting for the runtime consumer."""


class AdmissionGuard(Protocol):
    """A lock that can be acquired without waiting behind host operations."""

    def acquire(self, blocking: bool = True) -> bool:
        """Acquire the guard, optionally without waiting."""

    def release(self) -> None:
        """Release the guard."""


_SPEAKER_TAG_LINE = re.compile(
    r"(?:\A|(?<=[\r\n]))[ \t]*\[[^\]\r\n]{1,128}\][ \t]*:"
)


class PlayerRuntimeGateway:
    """Admit only the currently selected party member to a shared host queue.

    The caller supplies canonical state access, synchronization, transcript
    echo, and the optional safe snapshot reader. No host, Flask, mechanics,
    provider, or persistence modules are imported by this boundary.
    """

    def __init__(
        self,
        runtime_queue: RuntimeInputQueue,
        *,
        read_party_state: Callable[[], Mapping[str, object]],
        canonical_state_lock: AdmissionGuard,
        busy_probe: Callable[[], bool],
        echo_input: Callable[[Mapping[str, object]], None],
        snapshot_reader: Callable[[], PlayerSnapshot],
    ) -> None:
        self._runtime_queue = runtime_queue
        self._read_party_state = read_party_state
        self._canonical_state_lock = canonical_state_lock
        self._busy_probe = busy_probe
        self._echo_input = echo_input
        self._snapshot_reader = snapshot_reader
        self._admission_lock = threading.Lock()

    def admit_input(self, command: PlayerInputCommand) -> PlayerInputAdmission:
        """Validate current character identity, then enqueue once without waiting."""
        if not isinstance(command, PlayerInputCommand):
            return PlayerInputAdmission(request_id="", status="rejected")
        if not self._valid_text(command.text):
            return PlayerInputAdmission(command.request_id, "rejected")
        if _SPEAKER_TAG_LINE.search(command.text) is not None:
            return PlayerInputAdmission(command.request_id, "rejected")

        if not self._admission_lock.acquire(blocking=False):
            return PlayerInputAdmission(command.request_id, "busy")
        try:
            try:
                processing = self._busy_probe()
            except Exception:
                return PlayerInputAdmission(command.request_id, "busy")
            if not isinstance(processing, bool):
                return PlayerInputAdmission(command.request_id, "busy")
            if processing:
                return PlayerInputAdmission(command.request_id, "busy")

            try:
                pending_count = self._runtime_queue.qsize()
            except Exception:
                return PlayerInputAdmission(command.request_id, "rejected")
            if (
                not isinstance(pending_count, int)
                or isinstance(pending_count, bool)
                or pending_count < 0
            ):
                return PlayerInputAdmission(command.request_id, "rejected")
            if pending_count >= MAX_PENDING_RUNTIME_INPUTS:
                return PlayerInputAdmission(command.request_id, "busy")

            if not self._canonical_state_lock.acquire(blocking=False):
                return PlayerInputAdmission(command.request_id, "busy")
            try:
                try:
                    party_state = self._read_party_state()
                except Exception:
                    return PlayerInputAdmission(command.request_id, "rejected")
                admission_status = self._check_character_binding(command, party_state)
                if admission_status is not None:
                    return PlayerInputAdmission(command.request_id, admission_status)

                queued_input = f"[{command.character_name}]: {command.text}"
                message = {
                    "type": "user-input",
                    "content": command.text,
                    "author": command.character_name,
                }
                try:
                    self._echo_input(message)
                except Exception:
                    _LOGGER.exception("player transcript echo failed before runtime enqueue")
                    return PlayerInputAdmission(command.request_id, "rejected")

                try:
                    self._runtime_queue.put_nowait(queued_input)
                except queue.Full:
                    # A completed transcript echo without an enqueue is possible
                    # only for this Full path. The qsize bound and the unbounded
                    # host queue should make it unreachable in normal host use.
                    return PlayerInputAdmission(command.request_id, "busy")
            finally:
                self._canonical_state_lock.release()

            return PlayerInputAdmission(command.request_id, "accepted")
        finally:
            self._admission_lock.release()

    def read_snapshot(self) -> PlayerSnapshot:
        """Delegate safe player projections to the injected canonical reader."""
        snapshot = self._snapshot_reader()
        if not isinstance(snapshot, PlayerSnapshot):
            raise RuntimeError("player snapshot reader returned an invalid result")
        return snapshot

    @staticmethod
    def _valid_text(text: object) -> bool:
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            return False
        try:
            return len(text.encode("utf-8")) <= MAX_PLAYER_INPUT_BYTES
        except UnicodeEncodeError:
            return False

    @staticmethod
    def _check_character_binding(
        command: PlayerInputCommand,
        party_state: object,
    ) -> str | None:
        if not isinstance(party_state, Mapping):
            return "rejected"

        members = party_state.get("partyMembers")
        if not isinstance(members, list):
            return "rejected"
        if command.character_name not in members:
            return "rejected"

        startup_incomplete = party_state.get("startup_incomplete", False)
        if not isinstance(startup_incomplete, bool) or startup_incomplete:
            return "rejected"

        active_character = party_state.get("active_character")
        revision = party_state.get("active_character_revision", 0)
        if (
            not isinstance(active_character, str)
            or not active_character
            or active_character not in members
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 0
        ):
            return "rejected"
        if (
            command.character_name != active_character
            or command.active_character_revision != revision
        ):
            return "stale"
        return None
