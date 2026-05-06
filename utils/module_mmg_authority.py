# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest MMG authority helpers.

Provides module-local unified-assets authority resolution for the toolkit.
The helpers in this module intentionally avoid runtime campaign state such as
party_tracker.json so MMG asset classification remains module-local.
"""

import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from utils.file_operations import safe_read_json
from utils.npc_identity import canonicalize_npc_identity, canonicalize_npc_slug


def _normalize_module_name(module_name: str) -> str:
    return str(module_name or "").strip().replace(" ", "_")


def _normalize_project_root(project_root: Optional[Path | str]) -> Path:
    if project_root is None:
        return Path.cwd()
    return Path(project_root)


def _module_dir(project_root: Optional[Path | str], module_name: str) -> Path:
    root_path = _normalize_project_root(project_root)
    return root_path / "modules" / _normalize_module_name(module_name)


def _load_json_payload(file_path: Path) -> Optional[Dict[str, Any]]:
    if not file_path.exists():
        return None
    try:
        payload = safe_read_json(str(file_path))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _append_unique(values: List[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _usable_identity_prefix(prefix: str) -> bool:
    if not prefix:
        return False
    if len(prefix.split()) > 4:
        return False
    return any(char.isalpha() for char in prefix)


def _module_npc_slug(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return ""

    if "(" in text:
        prefix = text.split("(", 1)[0].strip()
        if _usable_identity_prefix(prefix):
            return canonicalize_npc_slug(prefix)

    identity = canonicalize_npc_identity(text)
    if identity.slug:
        return identity.slug

    return canonicalize_npc_slug(text)


def _normalize_monster_slug(label: str) -> str:
    try:
        from updates.update_character_info import normalize_character_name

        return normalize_character_name(str(label or ""))
    except Exception:
        normalized = str(label or "").strip().lower().replace("'", "")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized


def _prefer_display_name(existing: str, candidate: str) -> str:
    existing_name = str(existing or "").strip()
    candidate_name = str(candidate or "").strip()
    if not existing_name:
        return candidate_name
    if not candidate_name:
        return existing_name
    if len(candidate_name) > len(existing_name):
        return candidate_name
    if "(" in candidate_name and "(" not in existing_name:
        return candidate_name
    return existing_name


def _build_asset_record(
    asset_id: str,
    name: str,
    asset_type: str,
    authority_role: str,
) -> Dict[str, Any]:
    return {
        "id": asset_id,
        "name": name,
        "type": asset_type,
        "authority_role": authority_role,
        "authority_sources": [],
    }


def _merge_asset_record(
    store: Dict[str, Dict[str, Any]],
    asset_id: str,
    name: str,
    asset_type: str,
    authority_role: str,
    source_type: str,
) -> None:
    if not asset_id:
        return

    record = store.get(asset_id)
    if record is None:
        store[asset_id] = _build_asset_record(asset_id, name, asset_type, authority_role)
        record = store[asset_id]
    else:
        record["name"] = _prefer_display_name(record.get("name", ""), name)
        if authority_role == "explicit_monster" or (
            authority_role == "npc" and record.get("authority_role") != "explicit_monster"
        ):
            record["authority_role"] = authority_role

    _append_unique(record.setdefault("authority_sources", []), source_type)


def _iter_npc_labels(payload: Any) -> Iterable[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "npcs":
                if isinstance(value, dict):
                    for npc_data in value.values():
                        if isinstance(npc_data, dict):
                            label = str(npc_data.get("name") or "").strip()
                            if label:
                                yield label
                        elif isinstance(npc_data, str):
                            label = npc_data.strip()
                            if label:
                                yield label
                elif isinstance(value, list):
                    for npc_data in value:
                        if isinstance(npc_data, dict):
                            label = str(npc_data.get("name") or "").strip()
                            if label:
                                yield label
                        elif isinstance(npc_data, str):
                            label = npc_data.strip()
                            if label:
                                yield label
                elif isinstance(value, str):
                    label = value.strip()
                    if label:
                        yield label
            else:
                yield from _iter_npc_labels(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_npc_labels(item)


def _split_creature_tokens(raw_value: Any) -> List[str]:
    if not isinstance(raw_value, str):
        return []
    normalized = raw_value.replace("\n", ",").replace(";", ",")
    tokens: List[str] = []
    for piece in normalized.split(","):
        cleaned = str(piece or "").strip().strip(". ")
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _iter_structured_monster_names(payload: Any) -> Iterable[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key != "monsters":
                yield from _iter_structured_monster_names(value)
                continue

            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        label = str(entry.get("name") or entry.get("monster") or "").strip().strip(". ")
                        if label:
                            yield label
                    elif isinstance(entry, str):
                        label = entry.strip().strip(". ")
                        if label:
                            yield label
            elif isinstance(value, str):
                for token in _split_creature_tokens(value):
                    if token:
                        yield token
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_structured_monster_names(item)


def _iter_creature_names(payload: Any) -> Iterable[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "creatures":
                for token in _split_creature_tokens(value):
                    cleaned = re.sub(r"\s*\([^)]*\)", "", token).strip()
                    if cleaned:
                        yield cleaned
            else:
                yield from _iter_creature_names(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_creature_names(item)


def _iter_visible_hostile_names(payload: Any) -> Iterable[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "visibleHostiles":
                if isinstance(value, list):
                    for hostile in value:
                        if isinstance(hostile, dict):
                            label = str(hostile.get("name") or hostile.get("monsterType") or "").strip()
                            if label:
                                yield label
                elif isinstance(value, dict):
                    label = str(value.get("name") or value.get("monsterType") or "").strip()
                    if label:
                        yield label
            else:
                yield from _iter_visible_hostile_names(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_visible_hostile_names(item)


def _load_module_context_npcs(module_dir: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = OrderedDict()
    for file_name, source_type in (
        ("module_context.json", "module_context"),
        ("module_context_BU.json", "module_context_BU"),
        ("npcs_seed.json", "npcs_seed"),
    ):
        payload = _load_json_payload(module_dir / file_name)
        if not isinstance(payload, dict):
            continue
        for label in _iter_npc_labels(payload.get("npcs")):
            asset_id = _module_npc_slug(label)
            if not asset_id:
                continue
            _merge_asset_record(records, asset_id, label, "npc", "npc", source_type)
    return records


def _load_area_npcs(module_dir: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = OrderedDict()
    areas_dir = module_dir / "areas"
    if not areas_dir.exists():
        return records

    for area_path in sorted(areas_dir.glob("*_BU.json")):
        payload = _load_json_payload(area_path)
        if not isinstance(payload, dict):
            continue
        for location in payload.get("locations", []) or []:
            if not isinstance(location, dict):
                continue
            for npc in location.get("npcs") or []:
                if isinstance(npc, dict):
                    label = str(npc.get("name") or "").strip()
                else:
                    label = str(npc or "").strip()
                asset_id = _module_npc_slug(label)
                if not asset_id:
                    continue
                existing = records.get(asset_id)
                if existing is None:
                    _merge_asset_record(records, asset_id, label, "npc", "npc", "area_npcs")
                else:
                    existing["name"] = _prefer_display_name(existing.get("name", ""), label)
                    _append_unique(existing.setdefault("authority_sources", []), "area_npcs")
    return records


def _load_explicit_module_monsters(module_dir: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = OrderedDict()
    monsters_dir = module_dir / "monsters"
    if monsters_dir.exists():
        for monster_path in sorted(monsters_dir.glob("*.json")):
            payload = _load_json_payload(monster_path)
            if isinstance(payload, dict):
                label = str(payload.get("name") or monster_path.stem).strip()
            else:
                label = monster_path.stem
            asset_id = _normalize_monster_slug(label or monster_path.stem)
            if not asset_id:
                continue
            _merge_asset_record(records, asset_id, label or asset_id, "monster", "explicit_monster", "monster_file")
    return records


def _load_area_monsters(module_dir: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = OrderedDict()
    areas_dir = module_dir / "areas"
    if not areas_dir.exists():
        return records

    for area_path in sorted(areas_dir.glob("*_BU.json")):
        payload = _load_json_payload(area_path)
        if not isinstance(payload, dict):
            continue
        for location in payload.get("locations", []) or []:
            if not isinstance(location, dict):
                continue

            for monster in location.get("monsters") or []:
                if isinstance(monster, dict):
                    label = str(monster.get("name") or "").strip()
                else:
                    match = re.search(r"\d*\s*(.+?)(?:\s*\(|$)", str(monster or ""))
                    label = match.group(1).strip() if match else str(monster or "").strip()
                asset_id = _normalize_monster_slug(label)
                if not asset_id:
                    continue
                _merge_asset_record(records, asset_id, label or asset_id, "monster", "explicit_monster", "structured_monsters")

    return records


def _load_weak_monsters(module_dir: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = OrderedDict()
    areas_dir = module_dir / "areas"
    if not areas_dir.exists():
        return records

    for area_path in sorted(areas_dir.glob("*_BU.json")):
        payload = _load_json_payload(area_path)
        if not isinstance(payload, dict):
            continue
        for location in payload.get("locations", []) or []:
            if not isinstance(location, dict):
                continue

            for creature_name in _iter_creature_names(location):
                asset_id = _normalize_monster_slug(creature_name)
                if not asset_id:
                    continue
                _merge_asset_record(records, asset_id, creature_name, "monster", "weak_monster", "creatures")

            for hostile_name in _iter_visible_hostile_names(location):
                asset_id = _normalize_monster_slug(hostile_name)
                if not asset_id:
                    continue
                _merge_asset_record(records, asset_id, hostile_name, "monster", "weak_monster", "visibleHostiles")

    return records


def build_module_mmg_assets(
    module_name: str,
    *,
    project_root: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Build module-local MMG asset rows with source-aware authority."""
    module_dir = _module_dir(project_root, module_name)
    if not module_dir.exists():
        return {
            "module_name": _normalize_module_name(module_name),
            "npcs": OrderedDict(),
            "monsters": OrderedDict(),
            "suppressed_npc_slugs": [],
            "explicit_monster_authority_slugs": set(),
            "weak_monster_candidate_slugs": set(),
        }

    npc_records = _load_module_context_npcs(module_dir)
    for slug, record in _load_area_npcs(module_dir).items():
        npc_records.setdefault(slug, record)

    explicit_monsters = _load_explicit_module_monsters(module_dir)
    for slug, record in _load_area_monsters(module_dir).items():
        existing = explicit_monsters.get(slug)
        if existing is None:
            explicit_monsters[slug] = record
        else:
            existing["name"] = _prefer_display_name(existing.get("name", ""), record.get("name", ""))
            for source in record.get("authority_sources", []):
                _append_unique(existing.setdefault("authority_sources", []), source)
            if existing.get("authority_role") != "explicit_monster":
                existing["authority_role"] = "explicit_monster"

    weak_monsters = _load_weak_monsters(module_dir)

    suppressed_npc_slugs = sorted([slug for slug in npc_records if slug in explicit_monsters])

    final_npcs: Dict[str, Dict[str, Any]] = OrderedDict()
    for slug, record in npc_records.items():
        if slug in explicit_monsters:
            continue
        final_npcs[slug] = record

    final_monsters: Dict[str, Dict[str, Any]] = OrderedDict()
    for slug, record in explicit_monsters.items():
        final_monsters[slug] = record

    for slug, record in weak_monsters.items():
        if slug in final_npcs or slug in final_monsters:
            continue
        final_monsters[slug] = record

    return {
        "module_name": _normalize_module_name(module_name),
        "npcs": final_npcs,
        "monsters": final_monsters,
        "suppressed_npc_slugs": suppressed_npc_slugs,
        "explicit_monster_authority_slugs": set(explicit_monsters.keys()),
        "weak_monster_candidate_slugs": set(weak_monsters.keys()),
    }


def canonicalize_module_mmg_asset_audits(
    asset_audits: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Canonicalize same-slug MMG audit rows with source-aware authority.

    Explicit monster rows win over NPC rows; NPC rows win over weak monster
    candidates; weak-only monsters remain when no NPC authority exists.
    """
    grouped_by_slug: Dict[str, List[Dict[str, Any]]] = OrderedDict()
    for audit in asset_audits or []:
        if not isinstance(audit, dict):
            continue
        slug = str(audit.get("id") or "").strip()
        grouped_by_slug.setdefault(slug, []).append(audit)

    canonical_audits: List[Dict[str, Any]] = []
    for slug, grouped_rows in grouped_by_slug.items():
        if not slug:
            canonical_audits.extend(grouped_rows)
            continue

        explicit_rows = [
            row
            for row in grouped_rows
            if str(row.get("authority_role") or "").strip() == "explicit_monster"
        ]
        npc_rows = [
            row
            for row in grouped_rows
            if str(row.get("authority_role") or "").strip() == "npc"
        ]
        weak_rows = [
            row
            for row in grouped_rows
            if str(row.get("authority_role") or "").strip() == "weak_monster"
        ]

        chosen_row = None
        for rows in (explicit_rows, npc_rows, weak_rows, grouped_rows):
            if rows:
                chosen_row = rows[0]
                break

        if chosen_row is not None:
            canonical_audits.append(chosen_row)

    return canonical_audits
