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


def _follower_path() -> str:
    return FOLLOWER_STORE_PATH


def _default_store() -> Dict[str, Any]:
    return {"followers": []}


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
    return True
