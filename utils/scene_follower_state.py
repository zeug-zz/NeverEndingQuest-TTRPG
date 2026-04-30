# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""
NeverEndingQuest Scene Follower State
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Persistent movement state for scene-entity followers that travel with
the party. Manages the data/runtime/scene_followers.json file.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils.file_operations import safe_read_json, safe_write_json
from utils.enhanced_logger import debug, info, warning, error


FOLLOWER_STORE_PATH = "data/runtime/scene_followers.json"

_FOLLOWER_SCHEMA_KEYS = {"entity_id", "current_location", "since_turn"}
_FOLLOWER_OPTIONAL_STRING_KEYS = {
    "display_name",
    "entity_type",
    "monster_type",
    "disposition",
    "source_module",
    "source_npc_name",
    "source_entity_slug",
    "character_file_ref",
    "recruited_from_location_id",
    "lifecycle_state",
}
_FOLLOWER_OPTIONAL_BOOL_KEYS = {"visible_in_strip"}
_FOLLOWER_VISIBLE_STATES = {
    "following",
    "present",
    "held",
    "parleying",
}
_FOLLOWER_HIDDEN_STATES = {
    "hidden",
    "released",
    "escaped",
    "dead",
    "joined_party",
    "combat_started",
}
_FOLLOWER_DISPOSITION_VALUES = _FOLLOWER_VISIBLE_STATES | _FOLLOWER_HIDDEN_STATES | {
    "hostile",
    "neutral",
    "friendly",
    "guarded_guide",
}


def _follower_path() -> str:
    return FOLLOWER_STORE_PATH


def _default_store() -> Dict[str, Any]:
    return {"followers": []}


def normalize_scene_follower_entity_id(entity_id: Any) -> str:
    """Normalize follower identity into a stable slug."""
    try:
        from updates.update_character_info import normalize_character_name

        return normalize_character_name(str(entity_id or ""))
    except Exception:
        return str(entity_id or "").strip().lower().replace(" ", "_")


def normalize_scene_follower_display_name(value: Any, fallback: Any = None) -> str:
    """Normalize follower display text while preserving authored casing when available."""
    display_name = str(value or "").strip()
    if display_name:
        return display_name
    fallback_text = str(fallback or "").strip()
    if fallback_text:
        return fallback_text.replace("_", " ").strip().title()
    return ""


def normalize_scene_follower_entity_type(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_scene_follower_disposition(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    return normalized


def normalize_scene_follower_visibility(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "visible", "show", "on"}:
            return True
        if normalized in {"0", "false", "no", "hidden", "hide", "off"}:
            return False
    return bool(value)


def normalize_scene_follower_source_identity(record: Dict[str, Any]) -> Dict[str, str]:
    """Return normalized source identity fields for a follower record."""
    source_module = str(record.get("source_module", "") or "").strip()
    source_npc_name = normalize_scene_follower_display_name(
        record.get("source_npc_name"),
        record.get("display_name") or record.get("entity_id"),
    )
    source_entity_slug = normalize_scene_follower_entity_id(
        record.get("source_entity_slug") or source_npc_name or record.get("entity_id")
    )
    character_file_ref = str(record.get("character_file_ref", "") or "").strip()
    recruited_from_location_id = str(
        record.get("recruited_from_location_id", "") or ""
    ).strip().upper()

    normalized = {}
    if source_module:
        normalized["source_module"] = source_module
    if source_npc_name:
        normalized["source_npc_name"] = source_npc_name
    if source_entity_slug:
        normalized["source_entity_slug"] = source_entity_slug
    if character_file_ref:
        normalized["character_file_ref"] = character_file_ref
    if recruited_from_location_id:
        normalized["recruited_from_location_id"] = recruited_from_location_id
    return normalized


def normalize_scene_follower_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a follower record without requiring optional metadata."""
    if not isinstance(record, dict):
        return {}

    normalized = dict(record)
    entity_id = normalize_scene_follower_entity_id(
        record.get("entity_id") or record.get("entity") or record.get("name")
    )
    if entity_id:
        normalized["entity_id"] = entity_id

    current_location = str(record.get("current_location", "") or "").strip().upper()
    if current_location:
        normalized["current_location"] = current_location

    since_turn = record.get("since_turn", 1)
    normalized["since_turn"] = since_turn if since_turn is not None else 1

    display_name = normalize_scene_follower_display_name(
        record.get("display_name") or record.get("name"),
        entity_id,
    )
    if display_name:
        normalized["display_name"] = display_name

    entity_type = normalize_scene_follower_entity_type(record.get("entity_type"))
    if entity_type:
        normalized["entity_type"] = entity_type

    monster_type = normalize_scene_follower_display_name(record.get("monster_type"))
    if monster_type:
        normalized["monster_type"] = monster_type

    disposition = normalize_scene_follower_disposition(record.get("disposition"))
    if disposition:
        normalized["disposition"] = disposition

    lifecycle_state = normalize_scene_follower_disposition(
        record.get("lifecycle_state") or record.get("state")
    )
    if lifecycle_state:
        normalized["lifecycle_state"] = lifecycle_state

    if "visible_in_strip" in record:
        normalized["visible_in_strip"] = normalize_scene_follower_visibility(
            record.get("visible_in_strip")
        )

    normalized.update(normalize_scene_follower_source_identity(record))
    return normalized


def follower_identity_keys(record: Dict[str, Any]) -> List[str]:
    """Return canonical keys that identify a follower across scenes and source metadata."""
    if not isinstance(record, dict):
        return []

    keys = []
    for value in (
        record.get("entity_id"),
        record.get("display_name"),
        record.get("name"),
        record.get("monster_type"),
        record.get("source_npc_name"),
        record.get("source_entity_slug"),
        record.get("character_file_ref"),
    ):
        normalized = normalize_scene_follower_entity_id(value)
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def follower_visible_in_strip(record: Dict[str, Any]) -> bool:
    """Return True when a follower should be surfaced in the non-combat strip."""
    if not isinstance(record, dict):
        return False

    lifecycle_state = normalize_scene_follower_disposition(
        record.get("lifecycle_state") or record.get("state")
    )
    if lifecycle_state in _FOLLOWER_HIDDEN_STATES:
        return False

    if lifecycle_state and lifecycle_state not in _FOLLOWER_VISIBLE_STATES:
        if lifecycle_state not in {"hostile", "neutral", "friendly", "guarded_guide"}:
            return False

    visible_in_strip = record.get("visible_in_strip")
    if visible_in_strip is not None:
        return normalize_scene_follower_visibility(visible_in_strip)

    disposition = normalize_scene_follower_disposition(record.get("disposition"))
    if disposition in _FOLLOWER_HIDDEN_STATES:
        return False
    if disposition in _FOLLOWER_VISIBLE_STATES:
        return True
    if disposition in {"hostile", "guarded_guide", "neutral", "friendly", "held"}:
        return True

    return bool(record.get("monster_type") or record.get("entity_type") == "monster")


def follower_is_cleanup_state(record: Dict[str, Any]) -> bool:
    """Return True when the follower should be removed from strip visibility."""
    if not isinstance(record, dict):
        return False
    lifecycle_state = normalize_scene_follower_disposition(
        record.get("lifecycle_state") or record.get("state")
    )
    return lifecycle_state in _FOLLOWER_HIDDEN_STATES


def load_followers() -> Dict[str, Any]:
    try:
        path = _follower_path()
        if not os.path.isfile(path):
            return _default_store()
        data = safe_read_json(path)
        if not isinstance(data, dict):
            warning(f"scene_followers.json is not a dict, resetting", category="scene_followers")
            return _default_store()
        return data
    except Exception as e:
        warning(f"Failed to load scene_followers.json: {e}", category="scene_followers")
        return _default_store()


def save_followers(store: Dict[str, Any]) -> bool:
    try:
        if not isinstance(store, dict):
            return False
        safe_write_json(_follower_path(), store)
        return True
    except Exception as e:
        error(f"Failed to save scene_followers.json: {e}", exception=e, category="scene_followers")
        return False


def get_follower_records(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = store.get("followers")
    if not isinstance(raw, list):
        return []
    return raw


def find_follower(
    store: Dict[str, Any], entity_id: str
) -> Optional[Dict[str, Any]]:
    entity_key = str(entity_id or "").strip().lower()
    if not entity_key:
        return None
    for rec in get_follower_records(store):
        if str(rec.get("entity_id", "") or "").strip().lower() == entity_key:
            return rec
    return None


def follower_at_location(
    store: Dict[str, Any], entity_id: str, location_id: str
) -> bool:
    rec = find_follower(store, entity_id)
    if rec is None:
        return False
    current = str(rec.get("current_location", "") or "").strip().upper()
    target = str(location_id or "").strip().upper()
    return bool(current) and current == target


def create_follower_record(
    store: Dict[str, Any],
    entity_id: str,
    current_location: str,
    since_turn: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    entity_key = str(entity_id or "").strip().lower()
    if not entity_key:
        return None
    existing = find_follower(store, entity_key)
    if existing is not None:
        return existing
    record = {
        "entity_id": entity_key,
        "current_location": str(current_location or "").strip().upper(),
        "since_turn": since_turn or 1,
    }
    followers = get_follower_records(store)
    followers.append(record)
    store["followers"] = followers
    return record


def move_follower_to_location(
    store: Dict[str, Any], entity_id: str, new_location: str
) -> bool:
    entity_key = str(entity_id or "").strip().lower()
    if not entity_key:
        return False
    followers = get_follower_records(store)
    for rec in followers:
        if str(rec.get("entity_id", "") or "").strip().lower() == entity_key:
            rec["current_location"] = str(new_location or "").strip().upper()
            store["followers"] = followers
            return True
    return False


def remove_follower_record(store: Dict[str, Any], entity_id: str) -> bool:
    entity_key = str(entity_id or "").strip().lower()
    if not entity_key:
        return False
    followers = get_follower_records(store)
    updated = [rec for rec in followers
               if str(rec.get("entity_id", "") or "").strip().lower() != entity_key]
    if len(updated) == len(followers):
        return False
    store["followers"] = updated
    return True


def validate_follower_schema(store: Dict[str, Any]) -> bool:
    if not isinstance(store, dict):
        return False
    followers = store.get("followers")
    if not isinstance(followers, list):
        return False
    for rec in followers:
        if not isinstance(rec, dict):
            return False
        for key in _FOLLOWER_SCHEMA_KEYS:
            if key not in rec:
                return False
        if not normalize_scene_follower_entity_id(rec.get("entity_id")):
            return False
        if not str(rec.get("current_location", "") or "").strip():
            return False
        if "visible_in_strip" in rec and not isinstance(
            normalize_scene_follower_visibility(rec.get("visible_in_strip")), bool
        ):
            return False
        for key in _FOLLOWER_OPTIONAL_STRING_KEYS:
            if key in rec and rec.get(key) not in (None, "") and not str(rec.get(key)).strip():
                return False
    return True
