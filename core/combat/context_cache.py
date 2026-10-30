# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Bounded, process-local cache for deterministic combat context rendering."""

from collections import OrderedDict
import hashlib
import json
import threading
from typing import Any, Callable, Optional, Tuple


CONTEXT_MEMOIZATION_ENABLED = True
DEFAULT_CONTEXT_CACHE_SIZE = 8


def canonical_json_digest(value: Any, *, sort_keys: bool = True) -> Optional[str]:
    """Return a SHA-256 digest of stable JSON, or None when it cannot serialize."""
    try:
        serialized = json.dumps(
            value,
            sort_keys=sort_keys,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
    except (TypeError, ValueError, OverflowError):
        return None
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def encounter_revision(encounter: Any) -> Optional[str]:
    """Digest authoritative encounter content without adding persisted metadata."""
    if not isinstance(encounter, dict):
        return None
    return canonical_json_digest(encounter, sort_keys=True)


class CombatContextCache:
    """Small LRU that retains entries for only the most recently seen state key."""

    def __init__(self, max_entries: int = DEFAULT_CONTEXT_CACHE_SIZE) -> None:
        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or not 1 <= max_entries <= 8:
            raise ValueError("max_entries must be between 1 and 8")
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self._current_state_key: Optional[Tuple[Any, ...]] = None
        self._lock = threading.RLock()

    @property
    def size(self) -> int:
        """Current entry count, exposed for bounded-cache tests and diagnostics."""
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        """Discard all cached renderings, for example when a new combat starts."""
        with self._lock:
            self._entries.clear()
            self._current_state_key = None

    def get_or_render(
        self,
        state_key: Tuple[Any, ...],
        renderer_key: str,
        render: Callable[[], str],
    ) -> str:
        """Return a cached value for the complete key, otherwise render and retain it."""
        if not CONTEXT_MEMOIZATION_ENABLED:
            return render()

        with self._lock:
            if state_key != self._current_state_key:
                self._entries.clear()
                self._current_state_key = state_key

            entry_key = (state_key, renderer_key)
            if entry_key in self._entries:
                self._entries.move_to_end(entry_key)
                return self._entries[entry_key]

            rendered = render()
            self._entries[entry_key] = rendered
            self._entries.move_to_end(entry_key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return rendered
