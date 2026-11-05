# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Least-privilege player projections over canonical read-only state."""

from __future__ import annotations

import re
import json
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .limits import MAX_SNAPSHOT_BYTES
from .rendering import render_safe_markdown

PLAYER_PROJECTION_FIELDS = frozenset({"party", "busy"})
PARTY_PROJECTION_FIELDS = frozenset(
    {"members", "active_character", "active_character_revision", "world"}
)
WORLD_FIELD_ALLOWLIST = frozenset(
    {
        "year",
        "month",
        "day",
        "time",
        "weather",
        "season",
        "dayNightCycle",
        "moonPhase",
        "currentLocation",
        "currentArea",
    }
)
CHARACTER_FIELD_ALLOWLIST = frozenset(
    {
        "name",
        "level",
        "race",
        "class",
        "background",
        "alignment",
        "size",
        "status",
        "condition",
        "condition_affected",
        "hitPoints",
        "maxHitPoints",
        "armorClass",
        "initiative",
        "speed",
        "abilities",
        "deathSaves",
        "savingThrows",
        "skills",
        "proficiencyBonus",
    }
)
ABILITY_FIELD_ALLOWLIST = frozenset(
    {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
)
DEATH_SAVE_FIELD_ALLOWLIST = frozenset({"successes", "failures"})
SKILL_ALLOWLIST = frozenset(
    {
        "Acrobatics",
        "Animal Handling",
        "Arcana",
        "Athletics",
        "Deception",
        "History",
        "Insight",
        "Intimidation",
        "Investigation",
        "Medicine",
        "Nature",
        "Perception",
        "Performance",
        "Persuasion",
        "Religion",
        "Sleight of Hand",
        "Stealth",
        "Survival",
    }
)
SAVING_THROW_ALLOWLIST = frozenset(
    {"Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"}
)
PLAYER_EVENT_FIELD_ALLOWLIST = frozenset(
    {"event_id", "revision", "type", "projection"}
)
PLAYER_EVENT_TYPE_ALLOWLIST = frozenset({"projection.updated"})

MAX_PARTY_NAME_BYTES = 128
MAX_PROJECTION_LIST_ITEMS = 128
_EVENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_EVENT_TYPE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


class ProjectionError(ValueError):
    """Raised when canonical data cannot be safely projected."""


class PlayerProjectionBuilder:
    """Read canonical owners via injected functions and build a safe snapshot.

    The callbacks are intentionally injected: tests can use isolated fixture
    readers, while a runtime adapter can supply the existing canonical PC
    manager readers without changing those host modules.
    """

    def __init__(
        self,
        read_party_tracker: Callable[[], Mapping[str, object]],
        read_character_state: Callable[[str], Mapping[str, object] | None],
        *,
        read_busy_state: Callable[[], object] | None = None,
        read_active_pc_state: Callable[[], tuple[str, int]] | None = None,
    ) -> None:
        self._read_party_tracker = read_party_tracker
        self._read_character_state = read_character_state
        self._read_busy_state = read_busy_state
        self._read_active_pc_state = read_active_pc_state

    @classmethod
    def from_pc_manager(
        cls,
        *,
        read_busy_state: Callable[[], object] | None = None,
    ) -> PlayerProjectionBuilder:
        """Bind the existing read-only canonical PC-manager readers lazily."""
        from utils.pc_manager import (
            get_character_state,
            get_party_tracker,
            read_active_pc_state,
        )

        return cls(
            get_party_tracker,
            get_character_state,
            read_busy_state=read_busy_state,
            read_active_pc_state=read_active_pc_state,
        )

    def build(self) -> dict[str, object]:
        """Read canonical party/PC records and return only allowlisted fields."""
        party_tracker = self._read_party_tracker()
        if not isinstance(party_tracker, Mapping):
            raise ProjectionError("canonical party state is unavailable")
        busy: object = self._read_busy_state() if self._read_busy_state is not None else None
        if self._read_active_pc_state is not None:
            active_character, active_revision = self._read_active_pc_state()
            if (
                not isinstance(active_character, str)
                or not isinstance(active_revision, int)
                or isinstance(active_revision, bool)
                or active_revision < 0
            ):
                raise ProjectionError("canonical active-PC state is invalid")
            party_tracker = dict(party_tracker)
            party_tracker["active_character"] = active_character
            party_tracker["active_character_revision"] = active_revision
        return _project_party_and_characters(
            party_tracker,
            self._read_character_state,
            busy,
        )


def project_canonical_snapshot(canonical_state: Mapping[str, object]) -> dict[str, object]:
    """Project canonical party and character records through nested allowlists."""
    if not isinstance(canonical_state, Mapping):
        raise ProjectionError("canonical snapshot must be a mapping")
    party_tracker = canonical_state.get("party_tracker")
    if not isinstance(party_tracker, Mapping):
        raise ProjectionError("canonical party state is unavailable")
    raw_characters = canonical_state.get("characters")
    character_records = raw_characters if isinstance(raw_characters, Mapping) else {}
    return _project_party_and_characters(
        party_tracker,
        lambda name: (
            character_records.get(name)
            if isinstance(character_records.get(name), Mapping)
            else None
        ),
        canonical_state.get("busy"),
    )


def _project_party_and_characters(
    party_tracker: Mapping[str, object],
    read_character_state: Callable[[str], object],
    busy: object,
) -> dict[str, object]:
    raw_members = party_tracker.get("partyMembers")
    members: list[dict[str, object]] = []
    member_names: set[str] = set()
    first_member_name: str | None = None
    member_name_bytes = 0
    projected_member_bytes = 2
    if isinstance(raw_members, list) and len(raw_members) > MAX_SNAPSHOT_BYTES:
        raise ProjectionError("party member source exceeds the projection bound")
    for name in _iter_party_member_names(raw_members):
        member_name_bytes += len(name.encode("utf-8")) + 1
        if member_name_bytes > MAX_SNAPSHOT_BYTES:
            raise ProjectionError("party member source exceeds the projection bound")
        record = read_character_state(name)
        projected = project_character(name, record)
        if projected is not None:
            projected_size = len(
                json.dumps(projected, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            )
            projected_member_bytes += projected_size + (1 if members else 0)
            if projected_member_bytes + 1024 > MAX_SNAPSHOT_BYTES:
                raise ProjectionError("player projection exceeds the snapshot bound")
            members.append(projected)
            member_names.add(name)
            if first_member_name is None:
                first_member_name = name

    active_name = _valid_character_name(party_tracker.get("active_character"))
    if active_name not in member_names:
        active_name = first_member_name
    revision = _nonnegative_integer(party_tracker.get("active_character_revision"))
    world = _project_world(party_tracker.get("worldConditions"))
    party: dict[str, object] = {
        "members": members,
        "active_character": render_safe_markdown(active_name) if active_name is not None else None,
        "active_character_revision": 0 if revision is None else revision,
        "world": world,
    }
    result: dict[str, object] = {"party": party}
    if isinstance(busy, bool):
        result["busy"] = busy
    _ensure_projection_size(result)
    return result


def sanitize_player_projection(projection: Mapping[str, object]) -> dict[str, object]:
    """Rebuild an already projected payload, dropping any unlisted fields."""
    if not isinstance(projection, Mapping):
        raise ProjectionError("player projection must be a mapping")
    raw_party = projection.get("party")
    if not isinstance(raw_party, Mapping):
        raise ProjectionError("player party projection is unavailable")
    raw_members = raw_party.get("members")
    members: list[dict[str, object]] = []
    member_names: set[str] = set()
    first_member_name: str | None = None
    projected_member_bytes = 2
    if isinstance(raw_members, list):
        if len(raw_members) > MAX_SNAPSHOT_BYTES:
            raise ProjectionError("party projection exceeds the snapshot bound")
        for record in raw_members:
            if not isinstance(record, Mapping):
                continue
            name = _valid_character_name(record.get("name"))
            projected = project_character(name, record) if name is not None else None
            if projected is not None:
                projected_size = len(
                    json.dumps(projected, ensure_ascii=True, separators=(",", ":")).encode("ascii")
                )
                projected_member_bytes += projected_size + (1 if members else 0)
                if projected_member_bytes + 1024 > MAX_SNAPSHOT_BYTES:
                    raise ProjectionError("party projection exceeds the snapshot bound")
                member_names.add(name)
                members.append(projected)
                if first_member_name is None:
                    first_member_name = name

    active_name = _valid_character_name(raw_party.get("active_character"))
    if active_name not in member_names:
        active_name = first_member_name
    revision = _nonnegative_integer(raw_party.get("active_character_revision"))
    party = {
        "members": members,
        "active_character": active_name,
        "active_character_revision": 0 if revision is None else revision,
        "world": _project_world(raw_party.get("world")),
    }
    result: dict[str, object] = {"party": party}
    busy = projection.get("busy")
    if isinstance(busy, bool):
        result["busy"] = busy
    _ensure_projection_size(result)
    return result


def project_character(name: str, record: object) -> dict[str, object] | None:
    """Project only approved PC-sheet fields and only for party-member PCs."""
    valid_name = _valid_character_name(name)
    if valid_name is None or not isinstance(record, Mapping):
        return None
    roles = [
        record.get(field)
        for field in ("character_role", "character_type", "type")
        if isinstance(record.get(field), str) and record.get(field)
    ]
    if any(role.casefold() not in {"player", "pc"} for role in roles):
        return None

    projected: dict[str, object] = {"name": render_safe_markdown(valid_name) or ""}
    string_fields = {
        "race",
        "class",
        "background",
        "alignment",
        "size",
        "status",
        "condition",
    }
    integer_fields = {
        "level",
        "hitPoints",
        "maxHitPoints",
        "armorClass",
        "initiative",
        "speed",
        "proficiencyBonus",
    }
    for field in sorted(string_fields):
        text = render_safe_markdown(record.get(field))
        if text is not None:
            projected[field] = text
    for field in sorted(integer_fields):
        value = _integer(record.get(field))
        if value is not None:
            projected[field] = value

    abilities = record.get("abilities")
    if isinstance(abilities, Mapping):
        safe_abilities = _integer_fields(abilities, ABILITY_FIELD_ALLOWLIST)
        if safe_abilities:
            projected["abilities"] = safe_abilities

    death_saves = record.get("deathSaves")
    if isinstance(death_saves, Mapping):
        safe_saves = _integer_fields(death_saves, DEATH_SAVE_FIELD_ALLOWLIST)
        if safe_saves:
            projected["deathSaves"] = safe_saves

    conditions = _safe_text_list(record.get("condition_affected"))
    if conditions is not None:
        projected["condition_affected"] = conditions
    saves = _safe_text_list(record.get("savingThrows"), allowed=SAVING_THROW_ALLOWLIST)
    if saves is not None:
        projected["savingThrows"] = saves
    skills = _project_skills(record.get("skills"))
    if skills is not None:
        projected["skills"] = skills
    return {field: value for field, value in projected.items() if field in CHARACTER_FIELD_ALLOWLIST}


def project_player_event(
    event_id: str,
    revision: int,
    event_type: str,
    projection: Mapping[str, object],
) -> dict[str, object]:
    """Build one safe player event from a server-projected snapshot."""
    if not isinstance(event_id, str) or _EVENT_ID_RE.fullmatch(event_id) is None:
        raise ProjectionError("invalid player event identifier")
    if _nonnegative_integer(revision) is None:
        raise ProjectionError("invalid player event revision")
    if (
        not isinstance(event_type, str)
        or _EVENT_TYPE_RE.fullmatch(event_type) is None
        or event_type not in PLAYER_EVENT_TYPE_ALLOWLIST
    ):
        raise ProjectionError("invalid player event type")
    safe_projection = sanitize_player_projection(projection)
    event = {
        "event_id": event_id,
        "revision": revision,
        "type": event_type,
        "projection": safe_projection,
    }
    return {
        "event_id": event["event_id"],
        "revision": event["revision"],
        "type": event["type"],
        "projection": event["projection"],
    }


def _project_world(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for field in sorted(WORLD_FIELD_ALLOWLIST):
        item = value.get(field)
        if field in {"year", "day"}:
            integer = _integer(item)
            if integer is not None:
                result[field] = integer
            continue
        text = render_safe_markdown(item)
        if text is not None:
            result[field] = text
    return result


def _project_skills(value: object) -> list[str] | dict[str, int] | None:
    if isinstance(value, list):
        selected = [
            item
            for item in value[:MAX_PROJECTION_LIST_ITEMS]
            if isinstance(item, str) and item in SKILL_ALLOWLIST
        ]
        return selected
    if isinstance(value, Mapping):
        return _integer_fields(value, SKILL_ALLOWLIST)
    return None


def _safe_text_list(
    value: object,
    *,
    allowed: frozenset[str] | None = None,
) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value[:MAX_PROJECTION_LIST_ITEMS]:
        if not isinstance(item, str) or (allowed is not None and item not in allowed):
            continue
        text = render_safe_markdown(item)
        if text is not None:
            result.append(text)
    return result


def _integer_fields(value: Mapping[str, object], fields: frozenset[str]) -> dict[str, int]:
    return {
        field: integer
        for field in sorted(fields)
        if (integer := _integer(value.get(field))) is not None
    }


def _integer(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def _nonnegative_integer(value: object) -> int | None:
    integer = _integer(value)
    return integer if integer is not None and integer >= 0 else None


def _iter_party_member_names(value: object) -> Iterator[str]:
    if not isinstance(value, list):
        return
    seen: set[str] = set()
    for item in value:
        name = _valid_character_name(item)
        if name is None or name in seen:
            continue
        seen.add(name)
        yield name


def _ensure_projection_size(projection: Mapping[str, object]) -> None:
    try:
        encoded = json.dumps(
            projection,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProjectionError("player projection is not serializable") from exc
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ProjectionError("player projection exceeds the snapshot bound")


def _valid_character_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return None
    if not name.isprintable():
        return None
    try:
        if len(name.encode("utf-8")) > MAX_PARTY_NAME_BYTES:
            return None
    except UnicodeEncodeError:
        return None
    return name
