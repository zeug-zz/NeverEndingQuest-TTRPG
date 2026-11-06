#!/usr/bin/env python3
"""
PC Management utility for Tabletop Multiplayer.
Handles Player Character registration, removal, and selection.
Ensures PCs are correctly stored in party_tracker.json separate from NPCs.

TABLETOP MODE: Data Access Abstraction Layer
Provides centralized character data access with dual-check activation
for future database migration path.
"""

import os
import copy
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Literal, Optional, Dict, Any
from utils.file_operations import (
    SafeWriteRejected,
    register_safe_write_json_guard,
    safe_read_json,
    safe_write_json,
)
from utils.enhanced_logger import info, error, debug, warning
from utils.character_state_hygiene import normalize_life_state_fields
from utils.character_creation_prompt_builder import build_dm_creation_prompt_bundle

PARTY_TRACKER_FILE = "party_tracker.json"


class PartyTrackerSnapshot(dict):
    """A JSON-compatible party mapping carrying its own read baseline."""

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        *,
        filepath: Any = None,
        baseline: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(data or {})
        self._party_tracker_path_key = _path_key(filepath) if filepath is not None else None
        self._party_tracker_baseline = (
            copy.deepcopy(baseline) if isinstance(baseline, dict) else None
        )

    def copy(self) -> "PartyTrackerSnapshot":
        return PartyTrackerSnapshot(
            self,
            filepath=self._party_tracker_path_key,
            baseline=self._party_tracker_baseline,
        )

    def __copy__(self) -> "PartyTrackerSnapshot":
        return self.copy()

    def __deepcopy__(self, memo: Dict[int, Any]) -> "PartyTrackerSnapshot":
        copied = PartyTrackerSnapshot(
            copy.deepcopy(dict(self), memo),
            filepath=self._party_tracker_path_key,
            baseline=copy.deepcopy(self._party_tracker_baseline, memo),
        )
        memo[id(self)] = copied
        return copied

# TABLETOP MODE: Serialize canonical active-PC compare-and-set writes.
_party_tracker_lock = threading.RLock()
_party_tracker_write_local = threading.local()
_active_pc_revision_high_water: Dict[str, tuple[int, str]] = {}

# Experience points required for each level (for character creation)
XP_BY_LEVEL = {
    1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500,
    6: 14000, 7: 23000, 8: 34000, 9: 48000, 10: 64000,
    11: 85000, 12: 100000, 13: 120000, 14: 140000, 15: 165000,
    16: 195000, 17: 225000, 18: 265000, 19: 305000, 20: 355000,
}

# ============================================================================
# DATA ACCESS ABSTRACTION LAYER - TABLETOP MODE
# ============================================================================
#
# Architecture: Plugin-based abstraction for character data access
# 
# DUAL-CHECK ACTIVATION (TABLETOP MODE Standard):
#   1. Check config.MULTIPLAYER_MODE (global toggle)
#   2. Check len(partyMembers) > 1 (runtime activation)
#
# Current Implementation: JSON file-based with centralized access
# Future Implementation: Database backend
#
# Merge Safety:
#   - All logic contained in plugin file
#   - Upstream files can migrate gradually
#   - Fallback to direct file load if abstraction fails
# ============================================================================

# Storage backend configuration
# Future: "database", "redis", "hybrid"
CHARACTER_STORAGE_BACKEND = "json_file"

# Track data access patterns for optimization insights
_character_access_stats = {
    'single_player_calls': 0,
    'multiplayer_calls': 0,
    'errors': 0
}

# Thread lock for stats to prevent race conditions in multi-threaded web server
_stats_lock = threading.Lock()

# Lock for thread-safe config cache initialization
_cache_lock = threading.Lock()

# Cache MULTIPLAYER_MODE config to avoid repeated imports
_MULTIPLAYER_MODE_CACHE: Optional[bool] = None


def _is_multiplayer_enabled() -> bool:
    """
    Check MULTIPLAYER_MODE from config with caching.
    
    Caches the result after first check to avoid repeated imports.
    Thread-safe implementation using double-checked locking pattern.
    
    Returns:
        True if MULTIPLAYER_MODE is enabled, False otherwise
    """
    global _MULTIPLAYER_MODE_CACHE
    
    # First check without lock (fast path for cached values)
    if _MULTIPLAYER_MODE_CACHE is not None:
        return _MULTIPLAYER_MODE_CACHE
    
    # Need to initialize - acquire lock
    with _cache_lock:
        # Double-check after acquiring lock (another thread may have set it)
        if _MULTIPLAYER_MODE_CACHE is None:
            try:
                from config import MULTIPLAYER_MODE
                _MULTIPLAYER_MODE_CACHE = bool(MULTIPLAYER_MODE)
            except ImportError:
                _MULTIPLAYER_MODE_CACHE = False
    
    return _MULTIPLAYER_MODE_CACHE


def should_use_abstraction_layer(party_tracker_data: Optional[Dict[str, Any]] = None) -> bool:
    """
    DUAL-CHECK: Determine if abstraction layer should be used.
    
    TABLETOP MODE Standard Pattern:
    1. Check MULTIPLAYER_MODE from config.py (global toggle)
    2. Check party size > 1 (runtime activation)
    
    Args:
        party_tracker_data: Optional party tracker (loaded if not provided)
        
    Returns:
        True if both checks pass
    """
    # Check 1: Global feature toggle (cached)
    if not _is_multiplayer_enabled():
        return False
    
    # Check 2: Runtime party size
    if party_tracker_data is None:
        party_tracker_data = get_party_tracker()
    
    party_members = party_tracker_data.get('partyMembers', [])
    return len(party_members) > 1


def _get_character_path(character_name: str) -> str:
    """Resolve character storage location."""
    from utils.module_path_manager import ModulePathManager
    path_manager = ModulePathManager()
    normalized_name = character_name.lower().replace(' ', '_')
    return path_manager.get_character_path(normalized_name)


def get_character_state(character_name: str,
                       fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieve character state with automatic mode detection.
    
    TABLETOP MODE:
    - Multi-player: Uses centralized abstraction
    - Single-player: Direct file load (backward compatible)
    
    Future: Will query database in network play mode
    
    Args:
        character_name: Character name
        fields: Optional field filter (None = all)
        
    Returns:
        Character data or None
    """
    # Validate input
    if not _validate_character_name(character_name):
        return None
    
    # DUAL-CHECK: Determine mode
    if not should_use_abstraction_layer():
        # Single-player mode: Direct file load
        # This maintains backward compatibility with upstream
        # NOTE: Code paths intentionally duplicated for clarity.
        # Both single-player and multi-player modes perform the same file I/O,
        # but are kept separate to clearly distinguish behaviors.
        # Performance impact is negligible (<10ms) compared to LLM latency (3-7s).
        with _stats_lock:
            _character_access_stats['single_player_calls'] += 1
        char_path = _get_character_path(character_name)
        data = safe_read_json(char_path)
        if isinstance(data, dict):
            data = normalize_life_state_fields(data)
        
        if data and fields:
            return {k: v for k, v in data.items() if k in fields}
        return data
    
    # Multi-player mode: Centralized access with logging
    with _stats_lock:
        _character_access_stats['multiplayer_calls'] += 1
    
    try:
        char_path = _get_character_path(character_name)
        data = safe_read_json(char_path)
        
        if data is None:
            debug(f"Character not found: {character_name}", 
                  category="character_access")
            return None

        if isinstance(data, dict):
            data = normalize_life_state_fields(data)
        
        debug(f"Character loaded: {character_name}", category="character_access")
        
        if fields:
            return {k: v for k, v in data.items() if k in fields}
        return data
        
    except Exception as e:
        with _stats_lock:
            _character_access_stats['errors'] += 1
        error(f"Failed to load {character_name}: {e}", 
              exception=e, category="character_access")
        return None


def update_character_state(character_name: str,
                          updates: Dict[str, Any]) -> bool:
    """
    Update character state with automatic mode detection.
    
    TABLETOP MODE:
    - Multi-player: Centralized update with logging
    - Single-player: Direct file write
    
    Args:
        character_name: Character to update
        updates: Fields to update
        
    Returns:
        True if successful
    """
    # Validate input
    if not _validate_character_name(character_name):
        return False
    
    if not should_use_abstraction_layer():
        # Single-player: Direct write
        char_path = _get_character_path(character_name)
        existing = safe_read_json(char_path) or {}
        existing.update(updates)
        return safe_write_json(char_path, existing)
    
    # Multi-player: Centralized with validation
    try:
        char_path = _get_character_path(character_name)
        existing = safe_read_json(char_path) or {}
        existing.update(updates)
        
        success = safe_write_json(char_path, existing)
        
        if success:
            debug(f"Character updated: {character_name} - {list(updates.keys())}",
                  category="character_access")
        return success
        
    except Exception as e:
        with _stats_lock:
            _character_access_stats['errors'] += 1
        error(f"Failed to update {character_name}: {e}",
              exception=e, category="character_access")
        return False


def _validate_character_name(character_name: str) -> bool:
    """
    Validate character name parameter.
    
    Args:
        character_name: Name to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not character_name:
        error("Invalid character_name: empty or None", category="character_access")
        return False
    if not isinstance(character_name, str):
        error(f"Invalid character_name type: {type(character_name)}", category="character_access")
        return False
    return True


def get_party_character_states(party_tracker_data: Optional[Dict[str, Any]] = None
                              ) -> Dict[str, Dict[str, Any]]:
    """
    Bulk load all party member states.
    
    TABLETOP MODE: Optimized for multi-PC party management
    """
    if party_tracker_data is None:
        party_tracker_data = get_party_tracker()
    
    characters_data = {}
    party_members = party_tracker_data.get('partyMembers', [])
    
    for pc_name in party_members:
        char_data = get_character_state(pc_name)
        if char_data:
            characters_data[pc_name] = char_data
    
    return characters_data


def character_exists(character_name: str) -> bool:
    """Check if character exists."""
    char_path = _get_character_path(character_name)
    return os.path.exists(char_path)


def get_character_field(character_name: str, field_name: str) -> Any:
    """Get single field value."""
    data = get_character_state(character_name, fields=[field_name])
    return data.get(field_name) if data else None


def update_character_field(character_name: str,
                          field_name: str,
                          value: Any) -> bool:
    """Update single field."""
    return update_character_state(character_name, {field_name: value})


def get_character_access_stats() -> Dict[str, int]:
    """Get abstraction layer adoption stats."""
    return _character_access_stats.copy()


def ensure_stable_character_id(character_data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure character_data has a stable character_id (generated once)."""
    if not isinstance(character_data, dict):
        return character_data

    existing_id = str(character_data.get("character_id", "")).strip()
    if existing_id:
        return character_data

    character_data["character_id"] = str(uuid.uuid4())
    return character_data


def append_role_history_event(
    character_data: Dict[str, Any],
    action: str,
    from_role: str,
    to_role: str,
    source: str = "manage_party_add_existing",
    actor: str = "dm",
) -> Dict[str, Any]:
    """Append a role transition event to _tabletop_role_history."""
    if not isinstance(character_data, dict):
        return character_data

    history = character_data.get("_tabletop_role_history")
    if not isinstance(history, list):
        history = []

    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action": str(action),
        "from_role": str(from_role),
        "to_role": str(to_role),
        "source": str(source),
        "actor": str(actor),
    })
    character_data["_tabletop_role_history"] = history
    return character_data


def normalize_character_role_fields(character_data: Dict[str, Any], role: str) -> Dict[str, Any]:
    """Normalize all role marker fields consistently for character records."""
    if not isinstance(character_data, dict):
        return character_data

    normalized_role = str(role or "player").strip().lower()
    if normalized_role in ("pc", "player"):
        normalized_role = "player"
    elif normalized_role == "npc":
        normalized_role = "npc"
    else:
        normalized_role = "player"

    character_data["type"] = normalized_role
    character_data["character_type"] = normalized_role
    character_data["character_role"] = normalized_role
    return character_data


# DATABASE MIGRATION TODO:
# To migrate to database backend:
# 1. Update CHARACTER_STORAGE_BACKEND constant
# 2. Implement _get_character_path() to return DB query instead of file path
# 3. Update get_character_state() to use SQL/Mongo query
# 4. Update update_character_state() to use UPDATE operation
# 5. Add connection pooling and transaction management
# 6. Implement proper indexing for character_name lookups
# ============================================================================

ActivePCWriteStatus = Literal["updated", "unchanged", "stale", "rejected", "write_failed"]


@dataclass(frozen=True)
class ActivePCWriteResult:
    """Typed outcome of a canonical active-PC write attempt."""

    status: ActivePCWriteStatus
    active_character: str
    revision: int
    changed: bool = False
    reason: Optional[str] = None


def is_canonical_party_tracker_path(filepath: Any) -> bool:
    """Check whether a path resolves to the current runtime party tracker."""
    try:
        return Path(filepath).resolve(strict=False) == Path(
            PARTY_TRACKER_FILE
        ).resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return False


def _valid_revision(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _path_key(filepath: Any = None) -> str:
    target = PARTY_TRACKER_FILE if filepath is None else filepath
    try:
        return str(Path(target).resolve(strict=False))
    except (OSError, TypeError, ValueError):
        return str(target)


def tag_party_tracker_snapshot(
    filepath: Any,
    data: Any,
    *,
    baseline: Optional[Dict[str, Any]] = None,
) -> Any:
    """Attach a per-object baseline to reads of the canonical party file."""
    if not is_canonical_party_tracker_path(filepath) or not isinstance(data, dict):
        return data
    if baseline is None and isinstance(data, PartyTrackerSnapshot):
        if data._party_tracker_path_key == _path_key(filepath):
            return data
    source = data if baseline is None else baseline
    if not isinstance(source, dict):
        return data
    return PartyTrackerSnapshot(data, filepath=filepath, baseline=source)


def party_tracker_snapshot_baseline(
    filepath: Any,
    data: Any,
) -> Optional[Dict[str, Any]]:
    """Return a matching snapshot baseline without retaining global history."""
    if (
        not is_canonical_party_tracker_path(filepath)
        or not isinstance(data, PartyTrackerSnapshot)
        or data._party_tracker_path_key != _path_key(filepath)
        or not isinstance(data._party_tracker_baseline, dict)
    ):
        return None
    return copy.deepcopy(data._party_tracker_baseline)


def refresh_canonical_party_tracker_snapshot(
    filepath: Any,
    snapshot: Any,
    committed_data: Any,
) -> bool:
    """Refresh a trusted caller snapshot from the exact atomically committed payload."""
    if (
        not is_canonical_party_tracker_path(filepath)
        or not isinstance(snapshot, PartyTrackerSnapshot)
        or snapshot._party_tracker_path_key != _path_key(filepath)
        or not isinstance(snapshot._party_tracker_baseline, dict)
        or not isinstance(committed_data, dict)
    ):
        return False

    # TABLETOP MODE: Advance snapshot data and its read baseline together, but
    # only from the transformer output whose atomic replacement just succeeded.
    committed = copy.deepcopy(dict(committed_data))
    snapshot.clear()
    snapshot.update(copy.deepcopy(committed))
    snapshot._party_tracker_baseline = copy.deepcopy(committed)
    if "active_character_revision" in committed:
        active_character, revision = _read_selection_fields(committed)
        _remember_active_pc_state(active_character, revision, filepath)
    return True


_MISSING = object()


def _copy_json_value(value: Any) -> Any:
    return _MISSING if value is _MISSING else copy.deepcopy(value)


def _json_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if type(left) is not type(right):
        return False
    return left == right


def _three_way_merge(
    baseline: Any,
    incoming: Any,
    current: Any,
    path: str = "",
) -> Any:
    """Merge disjoint JSON edits and reject same-path concurrent changes."""
    if _json_values_equal(incoming, baseline):
        return _copy_json_value(current)
    if _json_values_equal(current, baseline):
        return _copy_json_value(incoming)
    if _json_values_equal(current, incoming):
        return _copy_json_value(current)

    values = (baseline, incoming, current)
    if all(value is _MISSING or isinstance(value, dict) for value in values):
        keys = set()
        for value in values:
            if isinstance(value, dict):
                keys.update(value)
        merged: Dict[str, Any] = {}
        for key in keys:
            child_path = f"{path}.{key}" if path else str(key)
            merged_value = _three_way_merge(
                baseline.get(key, _MISSING) if isinstance(baseline, dict) else _MISSING,
                incoming.get(key, _MISSING) if isinstance(incoming, dict) else _MISSING,
                current.get(key, _MISSING) if isinstance(current, dict) else _MISSING,
                child_path,
            )
            if merged_value is not _MISSING:
                merged[key] = merged_value
        return merged

    raise SafeWriteRejected(f"concurrent party-state conflict at {path or '<root>'}")


def _read_selection_fields(data: Dict[str, Any]) -> tuple[str, Any]:
    members = data.get("partyMembers")
    active = data.get("active_character")
    if "active_character" not in data:
        active = members[0] if isinstance(members, list) and members else ""
    if not isinstance(active, str):
        active = ""
    return active, data.get("active_character_revision", 0)


def _party_members(data: Dict[str, Any]) -> List[Any]:
    members = data.get("partyMembers")
    return members if isinstance(members, list) else []


def _known_active_pc_state(filepath: Any = None) -> Optional[tuple[int, str]]:
    return _active_pc_revision_high_water.get(_path_key(filepath))


def _remember_active_pc_state(name: str, revision: Any, filepath: Any = None) -> None:
    if not _valid_revision(revision):
        return
    key = _path_key(filepath)
    current = _active_pc_revision_high_water.get(key)
    if current is None or revision > current[0]:
        _active_pc_revision_high_water[key] = (revision, name)
    elif revision == current[0] and not current[1]:
        _active_pc_revision_high_water[key] = (revision, name)


def _preferred_active_pc_state(
    data: Dict[str, Any], filepath: Any = None
) -> tuple[str, Any]:
    """Prefer a newer process-observed state over a rolled-back disk snapshot."""
    active, revision = _read_selection_fields(data)
    known = _known_active_pc_state(filepath)
    if not _valid_revision(revision):
        if known is not None:
            return known[1], known[0]
        return active, revision
    if known is not None and (
        known[0] > revision or (known[0] == revision and known[1] != active)
    ):
        return known[1], known[0]
    if "active_character_revision" in data:
        _remember_active_pc_state(active, revision, filepath)
    return active, revision


def _sync_active_pc_fields(data: Dict[str, Any], name: str, revision: int) -> None:
    # TABLETOP MODE: Callers may refresh only the committed selection fields.
    data["active_character"] = name
    data["active_character_revision"] = revision


def _sync_guarded_active_pc_fields(
    data: Dict[str, Any],
    name: str,
    revision: Any,
    *,
    include_revision: bool,
) -> None:
    """Preserve legacy revision omission until a committed selection needs one."""
    data["active_character"] = name
    if include_revision:
        data["active_character_revision"] = revision
    else:
        data.pop("active_character_revision", None)


def _load_party_tracker_unlocked() -> Dict[str, Any]:
    data = safe_read_json(PARTY_TRACKER_FILE)
    if not isinstance(data, dict):
        data = {
            "module": "Unknown",
            "partyMembers": [],
            "partyNPCs": [],
            "active_character": "",
            "worldConditions": {},
        }
    data.setdefault("partyMembers", [])
    data.setdefault("partyNPCs", [])
    if "active_character" not in data:
        members = data.get("partyMembers")
        data["active_character"] = (
            members[0] if isinstance(members, list) and members else ""
        )
    return data


@contextmanager
def _authorized_party_tracker_write(mode: str = "transaction") -> Iterator[None]:
    if mode not in {"transaction", "replace"}:
        raise ValueError("party tracker write mode must be transaction or replace")
    previous = getattr(_party_tracker_write_local, "mode", None)
    _party_tracker_write_local.mode = mode
    try:
        yield
    finally:
        _party_tracker_write_local.mode = previous


def _prepare_party_replacement(data: Any, current: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise SafeWriteRejected("authorized party replacement must be a dictionary")

    replacement = copy.deepcopy(dict(data))
    members = _party_members(replacement)
    active, incoming_revision = _read_selection_fields(replacement)
    if not _valid_revision(incoming_revision):
        if "active_character_revision" in replacement:
            raise SafeWriteRejected("replacement has an invalid active-PC revision")
        incoming_revision = 0
    if active not in members:
        active = members[0] if members else ""

    has_current = isinstance(current, dict)
    current_active = ""
    current_revision = 0
    if has_current:
        current_active, current_revision = _preferred_active_pc_state(current)
    known = _known_active_pc_state()
    if has_current or known is not None:
        current_name = current_active if has_current else known[1]
        revision_floor = max(
            current_revision if _valid_revision(current_revision) else 0,
            incoming_revision,
            known[0] if known is not None else 0,
        )
        revision = revision_floor + (1 if active != current_name else 0)
    else:
        revision = incoming_revision
    _sync_active_pc_fields(replacement, active, revision)
    replacement.setdefault("partyMembers", members)
    replacement.setdefault("partyNPCs", [])
    return replacement


def prepare_canonical_party_tracker_write(
    filepath: str,
    data: Any,
    persisted: Any,
    persisted_exists: bool,
) -> Dict[str, Any]:
    """Rebase a tagged write under the atomic file lock or reject it."""
    mode = getattr(_party_tracker_write_local, "mode", None)
    if mode == "replace":
        return _prepare_party_replacement(data, persisted)

    if not persisted_exists or not isinstance(persisted, dict):
        raise SafeWriteRejected(
            "canonical party state is missing or corrupt; use an explicit replacement API"
        )
    if not isinstance(data, dict):
        raise SafeWriteRejected("canonical party payload must be a dictionary")

    baseline = party_tracker_snapshot_baseline(filepath, data)
    if baseline is None:
        if _json_values_equal(data, persisted):
            current = copy.deepcopy(dict(persisted))
            return _normalize_party_selection_after_merge(current, persisted, mode)
        raise SafeWriteRejected(
            "party payload has no canonical read baseline; use a fresh party transaction"
        )

    current = copy.deepcopy(dict(persisted))
    current_active, current_revision = _preferred_active_pc_state(current, filepath)
    if current_active != _read_selection_fields(current)[0] or (
        _valid_revision(current_revision)
        and current_revision != current.get("active_character_revision", 0)
    ):
        _sync_guarded_active_pc_fields(
            current,
            current_active,
            current_revision,
            include_revision=(
                "active_character_revision" in current
                or _known_active_pc_state(filepath) is not None
            ),
        )

    baseline_active, baseline_revision = _read_selection_fields(baseline)
    incoming_active, incoming_revision = _read_selection_fields(data)
    selection_changed_by_writer = (
        incoming_active != baseline_active
        or incoming_revision != baseline_revision
    )
    current_active, _ = _read_selection_fields(current)

    if mode != "transaction" and selection_changed_by_writer:
        incoming_members = _party_members(data)
        is_membership_fallback = (
            baseline_active not in incoming_members
            and incoming_active in {baseline_active, incoming_members[0] if incoming_members else ""}
        )
        if not is_membership_fallback:
            raise SafeWriteRejected(
                "active-PC selection changes require the canonical selection transaction"
            )

    if (
        mode == "transaction"
        and incoming_active != baseline_active
        and current_active != baseline_active
        and incoming_active != current_active
    ):
        raise SafeWriteRejected("concurrent active-PC selection conflict")

    baseline_for_merge = copy.deepcopy(dict(baseline))
    incoming_for_merge = copy.deepcopy(dict(data))
    current_for_merge = copy.deepcopy(current)
    for selection_key in ("active_character", "active_character_revision"):
        baseline_for_merge.pop(selection_key, None)
        incoming_for_merge.pop(selection_key, None)
        current_for_merge.pop(selection_key, None)

    merged = _three_way_merge(
        baseline_for_merge, incoming_for_merge, current_for_merge
    )
    if not isinstance(merged, dict):
        raise SafeWriteRejected("merged canonical party state is not a dictionary")

    selected_name = (
        incoming_active
        if mode == "transaction" and incoming_active != baseline_active
        else current_active
    )
    merged["active_character"] = selected_name

    return _normalize_party_selection_after_merge(merged, current, mode)


def _normalize_party_selection_after_merge(
    merged: Dict[str, Any],
    current: Dict[str, Any],
    mode: Optional[str],
) -> Dict[str, Any]:
    current_active, current_revision = _preferred_active_pc_state(current)
    if not _valid_revision(current_revision):
        known = _known_active_pc_state()
        if known is not None:
            current_revision = known[0]
        elif "active_character_revision" not in current:
            current_revision = 0
        else:
            raise SafeWriteRejected("persisted active-PC revision is malformed")

    members = _party_members(merged)
    desired_active = current_active
    if mode == "transaction":
        candidate = merged.get("active_character", current_active)
        if isinstance(candidate, str) and candidate != current_active:
            if candidate not in members:
                raise SafeWriteRejected("active-PC selection is not a current party member")
            desired_active = candidate

    if desired_active not in members:
        desired_active = members[0] if members else ""

    selection_changed = desired_active != current_active
    known = _known_active_pc_state()
    revision_floor = max(
        current_revision,
        known[0] if known is not None else 0,
    )
    revision = revision_floor + (1 if selection_changed else 0)
    include_revision = (
        "active_character_revision" in current
        or selection_changed
        or known is not None
    )
    _sync_guarded_active_pc_fields(
        merged, desired_active, revision, include_revision=include_revision
    )
    return merged


@contextmanager
def _guard_canonical_party_tracker_write(filepath: str, data: Any) -> Iterator[None]:
    """Serialize in-process canonical writes and observe only persisted revisions."""
    if not is_canonical_party_tracker_path(filepath):
        yield
        return

    with _party_tracker_lock:
        try:
            yield
        finally:
            # TABLETOP MODE: Only cache selection state that reached canonical disk.
            persisted_after = safe_read_json(filepath)
            if (
                isinstance(persisted_after, dict)
                and "active_character_revision" in persisted_after
            ):
                active, revision = _read_selection_fields(persisted_after)
                _remember_active_pc_state(active, revision)


register_safe_write_json_guard(_guard_canonical_party_tracker_write)


def get_party_tracker() -> Dict[str, Any]:
    """Load the party tracker, initializing it if necessary."""
    with _party_tracker_lock:
        return _load_party_tracker_unlocked()


def assign_active_character(data: Dict[str, Any], name: str) -> bool:
    """Update selection fields in memory; persisted writers must use the transaction API."""
    if not isinstance(data, dict):
        raise TypeError("party tracker must be a dictionary")
    if not isinstance(name, str):
        raise TypeError("active character must be a string")

    current_name = data.get("active_character")
    if "active_character" not in data:
        members = data.get("partyMembers")
        current_name = members[0] if isinstance(members, list) and members else ""
    revision = data.get("active_character_revision", 0)
    if not _valid_revision(revision):
        warning(
            "Malformed active character revision; treating it as 0 for host selection.",
            category="party_state",
        )  # TABLETOP MODE: Keep host mutations resilient while checked player writes fail closed.
        revision = 0
        data["active_character_revision"] = revision

    if current_name == name:
        data["active_character"] = name  # TABLETOP MODE: Materialize the unchanged effective selection.
        return False

    data["active_character"] = name  # TABLETOP MODE: Keep active-PC writes revision-aware.
    data["active_character_revision"] = revision + 1  # TABLETOP MODE: Advance the shared selection revision.
    return True


def read_active_pc_state() -> tuple[str, int]:
    """Read canonical active-PC state; legacy files without a revision are revision zero."""
    with _party_tracker_lock:
        data = get_party_tracker()
        name = data.get("active_character", "")
        if not isinstance(name, str):
            name = ""
        revision = data.get("active_character_revision", 0)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("active character revision must be a non-negative integer")
        return name, revision


def set_active_pc_checked(
    character_name: str,
    expected_revision: Optional[int] = None,
) -> ActivePCWriteResult:
    """Atomically validate membership/revision and persist an active-PC selection."""
    return _commit_active_character(
        character_name, expected_revision, reject_malformed_revision=True
    )


def commit_active_character(
    character_name: str,
    expected_revision: Optional[int] = None,
) -> ActivePCWriteResult:
    """Commit a host-authoritative selection against the current persisted party."""
    return _commit_active_character(
        character_name,
        expected_revision,
        reject_malformed_revision=expected_revision is not None,
    )


def _commit_active_character(
    character_name: str,
    expected_revision: Optional[int],
    *,
    reject_malformed_revision: bool,
) -> ActivePCWriteResult:
    if not isinstance(character_name, str):
        return ActivePCWriteResult("rejected", "", 0, reason="invalid_character_name")
    with _party_tracker_lock:
        data = _load_party_tracker_unlocked()
        if not isinstance(data, dict):
            return ActivePCWriteResult("rejected", "", 0, reason="party_state_unavailable")

        members = data.get("partyMembers")
        active_character, revision = _preferred_active_pc_state(data)
        revision_is_valid = _valid_revision(revision)
        if not revision_is_valid and reject_malformed_revision:
            return ActivePCWriteResult(
                "rejected", active_character, 0, reason="invalid_revision"
            )
        if not revision_is_valid:
            warning(
                "Malformed active character revision; normalizing in host selection transaction.",
                category="party_state",
            )  # TABLETOP MODE: Host-authoritative writes repair malformed legacy revisions.
            known = _known_active_pc_state()
            revision = known[0] if known is not None else 0
        if expected_revision is not None and (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            return ActivePCWriteResult(
                "rejected", active_character, revision, reason="invalid_expected_revision"
            )
        if not isinstance(members, list) or not isinstance(character_name, str) or character_name not in members:
            return ActivePCWriteResult(
                "rejected", active_character, revision, reason="not_party_member"
            )
        if expected_revision is not None and expected_revision != revision:
            return ActivePCWriteResult(
                "stale", active_character, revision, reason="stale_revision"
            )

        changed = active_character != character_name
        new_revision = revision + (1 if changed else 0)
        include_revision = (
            "active_character_revision" in data
            or _known_active_pc_state() is not None
            or changed
        )
        _sync_guarded_active_pc_fields(
            data,
            character_name,
            new_revision,
            include_revision=include_revision,
        )
        with _authorized_party_tracker_write():
            success = safe_write_json(PARTY_TRACKER_FILE, data)
        if not success:
            latest = safe_read_json(PARTY_TRACKER_FILE)
            if isinstance(latest, dict):
                latest_active, latest_revision = _preferred_active_pc_state(latest)
                if latest_active != active_character or latest_revision != revision:
                    return ActivePCWriteResult(
                        "stale",
                        latest_active,
                        latest_revision if _valid_revision(latest_revision) else 0,
                        reason="concurrent_party_change",
                    )
            return ActivePCWriteResult(
                "write_failed", active_character, revision, reason="party_write_failed"
            )
        persisted = safe_read_json(PARTY_TRACKER_FILE)
        if not isinstance(persisted, dict):
            return ActivePCWriteResult(
                "write_failed", active_character, revision, reason="party_state_unavailable"
            )
        persisted_active, persisted_revision = _read_selection_fields(persisted)
        if persisted_active != character_name:
            return ActivePCWriteResult(
                "stale",
                persisted_active,
                persisted_revision if _valid_revision(persisted_revision) else 0,
                reason="concurrent_party_change",
            )
        new_revision = persisted_revision if _valid_revision(persisted_revision) else 0
        if "active_character_revision" in persisted:
            _remember_active_pc_state(persisted_active, new_revision)
        if changed:
            # TABLETOP MODE: Publish only the committed revision, never the host
            # selection payload; the player listener rereads canonical state.
            from utils.player_host_publication import submit_player_host_change

            submit_player_host_change("active_pc", new_revision)
        return ActivePCWriteResult(
            "updated" if changed else "unchanged",
            persisted_active,
            new_revision,
            changed=changed,
        )


def sync_active_pc_fields(data: Dict[str, Any], result: ActivePCWriteResult) -> None:
    """Refresh only committed active-PC fields on a caller-owned party snapshot."""
    status = getattr(result, "status", None)
    active_character = getattr(result, "active_character", None)
    revision = getattr(result, "revision", None)
    if (
        not isinstance(data, dict)
        or status not in {"updated", "unchanged"}
        or not isinstance(active_character, str)
        or not _valid_revision(revision)
    ):
        return

    # TABLETOP MODE: Selection commits refresh only the two revisioned fields;
    # unrelated stale snapshot fields remain stale for the next three-way merge.
    _sync_active_pc_fields(data, active_character, revision)
    if (
        isinstance(data, PartyTrackerSnapshot)
        and data._party_tracker_path_key == _path_key(PARTY_TRACKER_FILE)
        and isinstance(data._party_tracker_baseline, dict)
    ):
        data._party_tracker_baseline["active_character"] = active_character
        data._party_tracker_baseline["active_character_revision"] = revision


def update_party_tracker(
    mutator: Callable[[Dict[str, Any]], Any],
) -> Optional[Dict[str, Any]]:
    """Mutate fresh party state under the canonical party lock and persist atomically."""
    if not callable(mutator):
        raise TypeError("party tracker mutator must be callable")
    with _party_tracker_lock:
        data = _load_party_tracker_unlocked()
        revision_present = "active_character_revision" in data
        known = _known_active_pc_state()
        current_active, current_revision = _preferred_active_pc_state(data)
        if not _valid_revision(current_revision):
            known = _known_active_pc_state()
            current_revision = known[0] if known is not None else 0
        revision_present = revision_present or known is not None
        _sync_active_pc_fields(data, current_active, current_revision)

        mutator(data)
        members = data.get("partyMembers")
        if not isinstance(members, list):
            members = []
        desired_active = data.get("active_character", current_active)
        if not isinstance(desired_active, str) or desired_active not in members:
            desired_active = members[0] if members else ""
        changed = desired_active != current_active
        new_revision = current_revision + (1 if changed else 0)
        include_revision = revision_present or changed
        _sync_guarded_active_pc_fields(
            data,
            desired_active,
            new_revision,
            include_revision=include_revision,
        )
        with _authorized_party_tracker_write():
            success = safe_write_json(PARTY_TRACKER_FILE, data)
        if not success:
            return None
        persisted = safe_read_json(PARTY_TRACKER_FILE)
        if not isinstance(persisted, dict):
            return None
        persisted_active, persisted_revision = _read_selection_fields(persisted)
        if "active_character_revision" in persisted:
            _remember_active_pc_state(persisted_active, persisted_revision)
        return persisted


def replace_party_tracker_data(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Replace party contents while keeping active-PC revisions monotonic."""
    if not isinstance(data, dict):
        raise TypeError("party tracker replacement must be a dictionary")
    with _party_tracker_lock:
        with _authorized_party_tracker_write("replace"):
            success = safe_write_json(PARTY_TRACKER_FILE, data)
        if not success:
            return None
        persisted = safe_read_json(PARTY_TRACKER_FILE)
        if not isinstance(persisted, dict):
            return None
        active, revision = _read_selection_fields(persisted)
        if "active_character_revision" in persisted:
            _remember_active_pc_state(active, revision)
        return persisted


def save_party_tracker(data: Dict[str, Any]) -> bool:
    """Save the party tracker data."""
    return safe_write_json(PARTY_TRACKER_FILE, data)

def add_pc(character_name: str) -> bool:
    """
    Explicitly add a Player Character to the party.
    This bypasses LLM guessing and hard-wires the categorization.
    """
    if not character_name:
        return False
        
    def add_to_fresh_party(data: Dict[str, Any]) -> None:
        members = data.get("partyMembers")
        if not isinstance(members, list):
            members = []
            data["partyMembers"] = members
        if character_name in members:
            info(f"PC '{character_name}' is already in the party.")
            return

        npcs = data.get("partyNPCs")
        if not isinstance(npcs, list):
            npcs = []
        npc_names = [
            npc.get("name") if isinstance(npc, dict) else str(npc)
            for npc in npcs
        ]
        if character_name in npc_names:
            info(f"Moving '{character_name}' from NPCs to PCs.")
            data["partyNPCs"] = [
                npc for npc in npcs
                if (npc.get("name") if isinstance(npc, dict) else str(npc)) != character_name
            ]

        members.append(character_name)
        data["partyMembers"] = members
        if not data.get("active_character"):
            data["active_character"] = character_name

    # TABLETOP MODE: Add-PC selection fallback is serialized with the fresh party state.
    success = update_party_tracker(add_to_fresh_party) is not None
    if success:
        info(f"Successfully added PC '{character_name}' to the party.")
    else:
        error(f"Failed to add PC '{character_name}' to the party tracker.")
    return success

def remove_pc(character_name: str) -> bool:
    """Remove a Player Character from the party."""
    removed = False

    def remove_from_fresh_party(data: Dict[str, Any]) -> None:
        nonlocal removed
        members = data.get("partyMembers")
        if not isinstance(members, list) or character_name not in members:
            info(f"PC '{character_name}' is not in the party.")
            return
        members.remove(character_name)
        data["partyMembers"] = members
        if data.get("active_character") == character_name:
            members_after = data["partyMembers"]
            data["active_character"] = members_after[0] if members_after else ""
        removed = True

    # TABLETOP MODE: Removal fallback and revision advance commit on fresh party state.
    updated = update_party_tracker(remove_from_fresh_party)
    success = updated is not None
    if success and removed:
        info(f"Successfully removed PC '{character_name}' from the party.")
    return success

def set_active_pc(character_name: str) -> bool:
    """Set the currently active PC for input context."""
    result = set_active_pc_checked(character_name)
    if result.status in {"updated", "unchanged"}:
        debug(f"Active character set to '{character_name}'.")
        return True
    if result.reason == "not_party_member":
        error(f"Cannot set active character to '{character_name}': Not a party member.")
    return False

def get_active_pc() -> str:
    """Get the currently active PC name."""
    data = get_party_tracker()
    return data.get("active_character", "")

def sync_pc_list(character_names: List[str]) -> bool:
    """Sync the partyMembers list with a provided list of names."""
    if not isinstance(character_names, list):
        return False

    def sync_fresh_party(data: Dict[str, Any]) -> None:
        members = list(character_names)
        data["partyMembers"] = members
        if data.get("active_character") not in members:
            data["active_character"] = members[0] if members else ""

    # TABLETOP MODE: Party-list synchronization preserves revision monotonicity.
    return update_party_tracker(sync_fresh_party) is not None

def get_entrance_prompt(character_name: str, character_data: Dict[str, Any], party_tracker: Dict[str, Any]) -> str:
    """
    Build a rich prompt for the LLM to narrate a character's entrance.
    """
    prompt_file = "prompts/tabletop/entrance_narration.txt"
    if not os.path.exists(prompt_file):
        return f"[SYSTEM] A new hero named '{character_name}' has joined the party. Please narrate their dramatic entrance."

    with open(prompt_file, 'r', encoding='utf-8') as f:
        template = f.read()

    # Get recent summary if available
    recent_summary = "The adventure continues..."
    try:
        summary_file = "modules/conversation_history/conversation_history.json"
        if os.path.exists(summary_file):
            history = safe_read_json(summary_file)
            if history and isinstance(history, list):
                # Look for last summary or just take last few messages
                for msg in reversed(history):
                    if isinstance(msg, dict):
                        content = str(msg.get("content", ""))
                    else:
                        continue
                    if "=== LOCATION SUMMARY ===" in content or "=== MODULE SUMMARY ===" in content:
                        recent_summary = content[:500] + "..."
                        break
    except Exception:
        pass

    world = party_tracker.get("worldConditions", {})
    
    return template.format(
        character_name=character_name,
        race=character_data.get("race", "Unknown"),
        class_name=character_data.get("class", "Unknown"),
        level=character_data.get("level", 1),
        description=character_data.get("personality_traits", character_data.get("description", "A mysterious traveler")),
        location_name=world.get("currentLocation", "the current location"),
        area_name=world.get("currentArea", "the current area"),
        party_members=", ".join(party_tracker.get("partyMembers", [])),
        recent_summary=recent_summary
    )

def get_character_creation_prompt(
    module_name: str,
    character_name: str,
    party_tracker: Dict[str, Any],
    level: int = 1,
    is_mid_campaign: bool = False,
    active_pc: str = "",
    current_location: str = "",
) -> str:
    """
    Load and format the enhanced character creation prompt for web DM interview.
    
    Args:
        module_name: Current module/campaign name
        character_name: Name of the character being created
        party_tracker: Party tracker data for context
        level: Character level (default 1)
        is_mid_campaign: Whether this is mid-campaign (affects equipment/XP)
        active_pc: Currently active PC who will set the scene
        current_location: Current location for context
        
    Returns:
        Formatted prompt string with context
    """
    try:
        prompt_bundle = build_dm_creation_prompt_bundle(
            mode="mid_campaign",
            module_name=module_name,
            character_name=character_name,
            level=level,
            party_tracker=party_tracker,
            is_mid_campaign=is_mid_campaign,
            active_pc=active_pc,
            current_location=current_location,
        )
        return prompt_bundle.get("system_prompt", "")
    except Exception as e:
        error(f"Failed to build shared character creation prompt: {e}")
        world = party_tracker.get("worldConditions", {}) if isinstance(party_tracker, dict) else {}
        party_members = party_tracker.get("partyMembers", []) if isinstance(party_tracker, dict) else []
        existing_members = [
            m for m in party_members
            if m.lower().replace(" ", "_") != character_name.lower().replace(" ", "_")
        ]
        existing_party_text = ", ".join(existing_members) if existing_members else "none yet"
        xp_for_level = XP_BY_LEVEL.get(level, 0)
        xp_next = XP_BY_LEVEL.get(level + 1, XP_BY_LEVEL[20]) if level < 20 else 0
        return (
            f"You are a friendly and knowledgeable character creation guide for 5th edition fantasy adventures. "
            f"Help create '{character_name}' for the {module_name} adventure at level {level}. "
            f"Current location: {current_location or world.get('currentLocation', 'the current location')}. "
            f"Existing party members: {existing_party_text}. "
            f"Ask one question at a time, guide the player through race, class, background, abilities, skills, "
            f"equipment, personality, and backstory, and only output a complete JSON character sheet when the "
            f"player says they are ready to finalize. "
            f"Set experience_points to {xp_for_level} and exp_required_for_next_level to {xp_next}."
        )

if __name__ == "__main__":
    # Test script
    test_name = "TestHero"
    print(f"Adding PC: {test_name}")
    add_pc(test_name)
    print(f"Active PC: {get_active_pc()}")
    print(f"Setting active PC: {test_name}")
    set_active_pc(test_name)
    print(f"Removing PC: {test_name}")
    remove_pc(test_name)
