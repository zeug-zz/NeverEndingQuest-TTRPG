# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Thread-safe, payload-free notices from committed host state to player sync."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Literal

PlayerHostChangeKind = Literal["transcript", "active_pc", "combat"]
_MAX_REVISION = (1 << 63) - 1
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlayerHostChangeNotice:
    """The only host data crossing into the player listener's event loop."""

    kind: PlayerHostChangeKind
    revision: int | None = None


@dataclass(frozen=True, slots=True)
class _ListenerRegistration:
    token: object
    loop: asyncio.AbstractEventLoop
    dispatch: Callable[[PlayerHostChangeNotice], None]
    mark_resync_required: Callable[[], None] | None


class PlayerHostChangePublisher:
    """Enqueue typed notices without waiting for the listener event loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._registration: _ListenerRegistration | None = None

    def register(
        self,
        loop: asyncio.AbstractEventLoop,
        dispatch: Callable[[PlayerHostChangeNotice], None],
        mark_resync_required: Callable[[], None] | None = None,
    ) -> object:
        """Attach to the explicitly running player listener, replacing old state."""
        if not isinstance(loop, asyncio.AbstractEventLoop) or not callable(dispatch):
            raise TypeError("player host listener registration is invalid")
        if mark_resync_required is not None and not callable(mark_resync_required):
            raise TypeError("resync callback must be callable")
        token = object()
        with self._lock:
            self._registration = _ListenerRegistration(
                token,
                loop,
                dispatch,
                mark_resync_required,
            )
        return token

    def unregister(self, token: object) -> None:
        """Detach only the registration that owns ``token``."""
        with self._lock:
            if self._registration is None or self._registration.token is not token:
                return
            self._registration = None

    def submit(self, kind: object, revision: object = None) -> bool:
        """Schedule one bounded notice; no listener means a strict no-op."""
        notice = _validated_notice(kind, revision)
        if notice is None:
            _LOGGER.warning("Player host publication ignored an invalid notice")
            return False

        with self._lock:
            registration = self._registration
            if registration is None or not registration.loop.is_running():
                return False
            try:
                registration.loop.call_soon_threadsafe(
                    self._dispatch,
                    registration,
                    notice,
                )
            except Exception:
                self._diagnose_enqueue_failure(registration, notice)
                return False
        return True

    def _dispatch(
        self,
        registration: _ListenerRegistration,
        notice: PlayerHostChangeNotice,
    ) -> None:
        with self._lock:
            if self._registration is not registration:
                return
        try:
            registration.dispatch(notice)
        except Exception:
            self._diagnose_enqueue_failure(registration, notice)

    @staticmethod
    def _diagnose_enqueue_failure(
        registration: _ListenerRegistration,
        notice: PlayerHostChangeNotice,
    ) -> None:
        _LOGGER.warning(
            "Player host publication enqueue failed (kind=%s)",
            notice.kind,
        )
        callback = registration.mark_resync_required
        if callback is not None:
            try:
                callback()
            except Exception:
                _LOGGER.warning("Player host publication resync marker failed")


_HOST_CHANGE_PUBLISHER = PlayerHostChangePublisher()


def register_player_host_listener(
    loop: asyncio.AbstractEventLoop,
    dispatch: Callable[[PlayerHostChangeNotice], None],
    mark_resync_required: Callable[[], None] | None = None,
) -> object:
    """Register the player app on its owned loop after explicit listener start."""
    return _HOST_CHANGE_PUBLISHER.register(loop, dispatch, mark_resync_required)


def unregister_player_host_listener(token: object) -> None:
    """Remove a listener registration during its owned shutdown."""
    _HOST_CHANGE_PUBLISHER.unregister(token)


def submit_player_host_change(kind: object, revision: object = None) -> bool:
    """Submit a typed host change without payloads or a host-thread wait."""
    try:
        return _HOST_CHANGE_PUBLISHER.submit(kind, revision)
    except Exception:
        _LOGGER.warning("Player host publication enqueue failed")
        return False


def _validated_notice(
    kind: object,
    revision: object,
) -> PlayerHostChangeNotice | None:
    if not isinstance(kind, str) or kind not in {"transcript", "active_pc", "combat"}:
        return None
    if kind == "active_pc":
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 0
            or revision > _MAX_REVISION
        ):
            return None
    elif revision is not None:
        return None
    return PlayerHostChangeNotice(kind, revision)
