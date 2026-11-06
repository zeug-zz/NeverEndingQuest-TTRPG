# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Least-privilege player projections over canonical read-only state."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .limits import (
    MAX_COMBATANTS,
    MAX_PLAYER_TEXT_BYTES,
    MAX_PROJECTION_LIST_ITEMS,
    MAX_SNAPSHOT_BYTES,
    MAX_TRANSCRIPT_BYTES,
    MAX_TRANSCRIPT_MESSAGES,
    MAX_TRANSCRIPT_SOURCE_ITEMS,
)
from .media import player_portrait_media_id
from .rendering import render_safe_markdown

PLAYER_PROJECTION_FIELDS = frozenset({"party", "transcript", "combat", "busy"})
PARTY_PROJECTION_FIELDS = frozenset(
    {"members", "active_character", "active_character_revision", "world"}
)
TRANSCRIPT_PROJECTION_FIELDS = frozenset({"available", "messages"})
TRANSCRIPT_MESSAGE_FIELDS = frozenset({"id", "sequence", "role", "text", "author"})
COMBAT_PROJECTION_FIELDS = frozenset(
    {"available", "active", "round", "phase", "turn_order"}
)
COMBATANT_FIELDS = frozenset({"name", "kind", "initiative", "status"})
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
        "portrait_media_id",
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
_EVENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_EVENT_TYPE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_TRANSCRIPT_ID_RE = re.compile(r"transcript-[a-f0-9]{32}\Z")
_TRANSCRIPT_ROLES = frozenset({"user", "assistant"})
_COMBATANT_KINDS = frozenset({"pc", "npc", "monster"})
_COMBATANT_STATUSES = frozenset({"alive", "unconscious", "dead", "defeated"})
_COMBAT_PHASES = frozenset({"PC_PHASE", "ENEMY_PHASE"})
_MAX_COMBAT_INITIATIVE = 1_000
_MAX_COMBAT_ROUND = 1_000_000
_LOGGER = logging.getLogger(__name__)


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
        read_transcript_state: Callable[[], object] | None = None,
        read_encounter_state: Callable[[str], object] | None = None,
    ) -> None:
        self._read_party_tracker = read_party_tracker
        self._read_character_state = read_character_state
        self._read_busy_state = read_busy_state
        self._read_active_pc_state = read_active_pc_state
        self._read_transcript_state = read_transcript_state
        self._read_encounter_state = read_encounter_state

    @classmethod
    def from_pc_manager(
        cls,
        *,
        read_busy_state: Callable[[], object] | None = None,
        read_transcript_state: Callable[[], object] | None = None,
        read_encounter_state: Callable[[str], object] | None = None,
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
            read_transcript_state=read_transcript_state,
            read_encounter_state=read_encounter_state,
        )

    def build(self) -> dict[str, object]:
        """Read canonical party/PC records and return only allowlisted fields."""
        party_tracker = self._read_party_tracker()
        if not isinstance(party_tracker, Mapping):
            raise ProjectionError("canonical party state is unavailable")
        try:
            busy: object = (
                self._read_busy_state() if self._read_busy_state is not None else None
            )
        except Exception as exc:
            raise ProjectionError("canonical busy state is unavailable") from exc
        if self._read_busy_state is not None and not isinstance(busy, bool):
            raise ProjectionError("canonical busy state is invalid")
        if self._read_active_pc_state is not None:
            try:
                active_state = self._read_active_pc_state()
            except Exception as exc:
                raise ProjectionError("canonical active-PC state is unavailable") from exc
            if not isinstance(active_state, tuple) or len(active_state) != 2:
                raise ProjectionError("canonical active-PC state is invalid")
            active_character, active_revision = active_state
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
        projection = _project_party_and_characters(
            party_tracker,
            self._read_character_state,
            busy,
        )
        if self._read_transcript_state is not None:
            projection["transcript"] = _project_transcript_section(
                self._read_transcript_state,
                set(_iter_party_member_names(party_tracker.get("partyMembers"))),
            )
        if self._read_encounter_state is not None:
            projection["combat"] = _project_combat_section(
                party_tracker,
                self._read_encounter_state,
            )
        _ensure_projection_size(projection)
        return projection


def project_canonical_snapshot(canonical_state: Mapping[str, object]) -> dict[str, object]:
    """Project canonical party and character records through nested allowlists."""
    if not isinstance(canonical_state, Mapping):
        raise ProjectionError("canonical snapshot must be a mapping")
    party_tracker = canonical_state.get("party_tracker")
    if not isinstance(party_tracker, Mapping):
        raise ProjectionError("canonical party state is unavailable")
    raw_characters = canonical_state.get("characters")
    character_records = raw_characters if isinstance(raw_characters, Mapping) else {}
    result = _project_party_and_characters(
        party_tracker,
        lambda name: (
            character_records.get(name)
            if isinstance(character_records.get(name), Mapping)
            else None
        ),
        canonical_state.get("busy"),
    )
    result.update(_project_optional_snapshot_fields(canonical_state, party_tracker))
    _ensure_projection_size(result)
    return result


def _project_optional_snapshot_fields(
    canonical_state: Mapping[str, object],
    party_tracker: Mapping[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {}
    if "transcript" in canonical_state:
        raw_party = canonical_state.get("characters")
        names = {
            name
            for name in _iter_party_member_names(party_tracker.get("partyMembers"))
            if isinstance(raw_party, Mapping)
            and isinstance(raw_party.get(name), Mapping)
            and project_character(name, raw_party[name]) is not None
        }
        result["transcript"] = _project_transcript_section(
            lambda: canonical_state["transcript"], names
        )
    if "encounter" in canonical_state:
        result["combat"] = _project_combat_section(
            party_tracker,
            lambda _encounter_id: canonical_state["encounter"],
        )
    return result


def _project_transcript_section(
    read_transcript_state: Callable[[], object],
    party_names: set[str],
) -> dict[str, object]:
    try:
        return _project_transcript(read_transcript_state(), party_names)
    except Exception:
        _LOGGER.warning("Player transcript projection unavailable")
        return {"available": False, "messages": []}


def _project_combat_section(
    party_tracker: Mapping[str, object],
    read_encounter_state: Callable[[str], object],
) -> dict[str, object]:
    try:
        return _project_combat(party_tracker, read_encounter_state)
    except Exception:
        _LOGGER.warning("Player combat projection unavailable")
        return {
            "available": False,
            "active": True,
            "round": None,
            "phase": None,
            "turn_order": [],
        }


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
    raw_revision = party_tracker.get("active_character_revision", 0)
    revision = _nonnegative_integer(raw_revision)
    if revision is None:
        raise ProjectionError("canonical active-PC revision is invalid")
    world = _project_world(party_tracker.get("worldConditions"))
    party: dict[str, object] = {
        "members": members,
        "active_character": render_safe_markdown(active_name) if active_name is not None else None,
        "active_character_revision": revision,
        "world": world,
    }
    result: dict[str, object] = {"party": party}
    if isinstance(busy, bool):
        result["busy"] = busy
    _ensure_projection_size(result)
    return result


def _project_transcript(value: object, party_names: set[str]) -> dict[str, object]:
    """Project the bounded canonical cache with deterministic opaque IDs.

    The host cache has no source message ID or timestamp, so IDs hash only the
    allowlisted public content plus a duplicate occurrence number.
    """
    if not isinstance(value, list) or len(value) > MAX_TRANSCRIPT_SOURCE_ITEMS:
        raise ProjectionError("canonical transcript is invalid or exceeds its source bound")

    projected_messages: list[dict[str, object]] = []
    duplicate_counts: dict[str, int] = {}
    for source_message in value:
        if not isinstance(source_message, Mapping):
            raise ProjectionError("canonical transcript contains an invalid message")
        message_type = source_message.get("type")
        if not isinstance(message_type, str) or message_type not in {"narration", "user-input"}:
            continue
        raw_text = source_message.get("content")
        if not isinstance(raw_text, str):
            raise ProjectionError("canonical transcript message text is invalid")
        try:
            if len(raw_text.encode("utf-8")) > MAX_PLAYER_TEXT_BYTES:
                raise ProjectionError("canonical transcript message exceeds its text bound")
        except UnicodeEncodeError as exc:
            raise ProjectionError("canonical transcript message text is invalid") from exc
        text = render_safe_markdown(raw_text)
        if text is None:
            raise ProjectionError("canonical transcript message text is invalid")

        role = "assistant" if message_type == "narration" else "user"
        author: str | None = None
        raw_author = source_message.get("author")
        if raw_author is not None:
            if not isinstance(raw_author, str):
                raise ProjectionError("canonical transcript author is invalid")
            safe_author = render_safe_markdown(raw_author)
            if safe_author is None:
                raise ProjectionError("canonical transcript author is invalid")
            if raw_author == "You" or raw_author in party_names:
                author = safe_author

        identity_material = "\0".join((role, author or "", text))
        occurrence = duplicate_counts.get(identity_material, 0) + 1
        duplicate_counts[identity_material] = occurrence
        digest = hashlib.sha256(
            f"{identity_material}\0{occurrence}".encode("utf-8")
        ).hexdigest()[:32]
        projected_message: dict[str, object] = {
            "id": f"transcript-{digest}",
            "role": role,
            "text": text,
        }
        if author is not None:
            projected_message["author"] = author
        projected_messages.append(projected_message)

    selected = projected_messages[-MAX_TRANSCRIPT_MESSAGES:]
    while selected:
        candidate: list[dict[str, object]] = []
        for index, item in enumerate(selected, start=1):
            sequenced_item = dict(item)
            sequenced_item["sequence"] = index
            candidate.append(sequenced_item)
        encoded = json.dumps(
            candidate,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")
        if len(encoded) <= MAX_TRANSCRIPT_BYTES:
            return {"available": True, "messages": candidate}
        selected = selected[1:]
    return {"available": True, "messages": []}


def _project_combat(
    party_tracker: Mapping[str, object],
    read_encounter_state: Callable[[str], object],
) -> dict[str, object]:
    world = party_tracker.get("worldConditions")
    if not isinstance(world, Mapping):
        raise ProjectionError("canonical world state is unavailable for combat projection")
    raw_encounter_id = world.get("activeCombatEncounter")
    if raw_encounter_id in (None, ""):
        return {
            "available": True,
            "active": False,
            "round": None,
            "phase": None,
            "turn_order": [],
        }
    if not isinstance(raw_encounter_id, str) or not _valid_encounter_id(raw_encounter_id):
        raise ProjectionError("canonical active encounter identifier is invalid")
    try:
        encounter = read_encounter_state(raw_encounter_id)
    except Exception as exc:
        raise ProjectionError("canonical encounter state is unavailable") from exc
    if not isinstance(encounter, Mapping):
        raise ProjectionError("canonical encounter state is unavailable")
    encounter_id = encounter.get("encounterId")
    if encounter_id != raw_encounter_id:
        raise ProjectionError("canonical encounter identity does not match")

    raw_round = encounter.get("combat_round", encounter.get("current_round"))
    round_number = _positive_bounded_integer(raw_round, _MAX_COMBAT_ROUND)
    if round_number is None:
        raise ProjectionError("canonical combat round is invalid")
    phase = encounter.get("combat_phase")
    if phase is not None and (
        not isinstance(phase, str) or phase not in _COMBAT_PHASES
    ):
        raise ProjectionError("canonical combat phase is invalid")
    raw_creatures = encounter.get("creatures")
    if not isinstance(raw_creatures, list) or len(raw_creatures) > MAX_COMBATANTS:
        raise ProjectionError("canonical combat roster is invalid or exceeds its bound")

    ordered: list[dict[str, object]] = []
    for creature in raw_creatures:
        projected = _project_combatant(creature)
        ordered.append(projected)
    ordered.sort(key=lambda item: -int(item["initiative"]))
    return {
        "available": True,
        "active": True,
        "round": round_number,
        "phase": phase,
        "turn_order": ordered,
    }


def _project_combatant(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionError("canonical combatant is invalid")
    raw_name = value.get("name")
    name = _valid_character_name(raw_name)
    raw_kind = value.get("type")
    kind_map = {"player": "pc", "npc": "npc", "enemy": "monster"}
    kind = kind_map.get(raw_kind) if isinstance(raw_kind, str) else None
    initiative = _bounded_integer(value.get("initiative"), _MAX_COMBAT_INITIATIVE)
    status = value.get("status")
    if (
        name is None
        or kind not in _COMBATANT_KINDS
        or initiative is None
        or not isinstance(status, str)
        or status not in _COMBATANT_STATUSES
    ):
        raise ProjectionError("canonical combatant fields are invalid")
    return {
        "name": render_safe_markdown(name) or "",
        "kind": kind,
        "initiative": initiative,
        "status": status,
    }


def _valid_encounter_id(value: str) -> bool:
    return bool(value) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is not None


def _bounded_integer(value: object, bound: int) -> int | None:
    integer = _integer(value)
    if integer is None or not -bound <= integer <= bound:
        return None
    return integer


def _positive_bounded_integer(value: object, bound: int) -> int | None:
    integer = _integer(value)
    if integer is None or not 1 <= integer <= bound:
        return None
    return integer


def _sanitize_player_transcript(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionError("player transcript projection is unavailable")
    raw_messages = value.get("messages")
    if not isinstance(raw_messages, list) or len(raw_messages) > MAX_TRANSCRIPT_MESSAGES:
        raise ProjectionError("player transcript projection exceeds its bound")
    available = value.get("available")
    if available is False:
        if raw_messages:
            raise ProjectionError("unavailable player transcript contains messages")
        return {"available": False, "messages": []}
    if available is not True:
        raise ProjectionError("player transcript projection is unavailable")
    messages: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    previous_sequence = 0
    for raw_message in raw_messages:
        if not isinstance(raw_message, Mapping):
            raise ProjectionError("player transcript message is invalid")
        message_id = raw_message.get("id")
        sequence = _positive_bounded_integer(raw_message.get("sequence"), MAX_TRANSCRIPT_SOURCE_ITEMS)
        role = raw_message.get("role")
        raw_text = raw_message.get("text")
        if (
            not isinstance(message_id, str)
            or _TRANSCRIPT_ID_RE.fullmatch(message_id) is None
            or message_id in seen_ids
            or sequence is None
            or sequence <= previous_sequence
            or not isinstance(role, str)
            or role not in _TRANSCRIPT_ROLES
            or not isinstance(raw_text, str)
        ):
            raise ProjectionError("player transcript message fields are invalid")
        text = render_safe_markdown(raw_text)
        if text is None:
            raise ProjectionError("player transcript text is invalid")
        message: dict[str, object] = {
            "id": message_id,
            "sequence": sequence,
            "role": role,
            "text": text,
        }
        if "author" in raw_message:
            raw_author = raw_message.get("author")
            author = render_safe_markdown(raw_author)
            if author is None:
                raise ProjectionError("player transcript author is invalid")
            message["author"] = author
        messages.append(message)
        seen_ids.add(message_id)
        previous_sequence = sequence
    result = {"available": True, "messages": messages}
    _ensure_projection_size({"transcript": result})
    encoded = json.dumps(
        result,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("ascii")
    if len(encoded) > MAX_TRANSCRIPT_BYTES:
        raise ProjectionError("player transcript projection exceeds its byte bound")
    return result


def _sanitize_player_combat(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionError("player combat projection is unavailable")
    available = value.get("available")
    active = value.get("active")
    raw_order = value.get("turn_order")
    if not isinstance(active, bool) or not isinstance(raw_order, list):
        raise ProjectionError("player combat projection is invalid")
    if len(raw_order) > MAX_COMBATANTS:
        raise ProjectionError("player combat roster exceeds its bound")
    if available is False:
        if (
            active is not True
            or value.get("round") is not None
            or value.get("phase") is not None
            or raw_order
        ):
            raise ProjectionError("unavailable player combat projection is invalid")
        return {
            "available": False,
            "active": True,
            "round": None,
            "phase": None,
            "turn_order": [],
        }
    if available is not True:
        raise ProjectionError("player combat projection is unavailable")
    if not active:
        if raw_order or value.get("round") is not None or value.get("phase") is not None:
            raise ProjectionError("inactive player combat projection contains combat state")
        return {
            "available": True,
            "active": False,
            "round": None,
            "phase": None,
            "turn_order": [],
        }

    round_number = _positive_bounded_integer(value.get("round"), _MAX_COMBAT_ROUND)
    phase = value.get("phase")
    if round_number is None or (phase is not None and (not isinstance(phase, str) or phase not in _COMBAT_PHASES)):
        raise ProjectionError("player combat round or phase is invalid")
    turn_order = [_sanitize_combatant(item) for item in raw_order]
    turn_order.sort(key=lambda item: -int(item["initiative"]))
    return {
        "available": True,
        "active": True,
        "round": round_number,
        "phase": phase,
        "turn_order": turn_order,
    }


def _sanitize_combatant(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionError("player combatant is invalid")
    name = render_safe_markdown(value.get("name"))
    kind = value.get("kind")
    initiative = _bounded_integer(value.get("initiative"), _MAX_COMBAT_INITIATIVE)
    status = value.get("status")
    if (
        name is None
        or not isinstance(kind, str)
        or kind not in _COMBATANT_KINDS
        or initiative is None
        or not isinstance(status, str)
        or status not in _COMBATANT_STATUSES
    ):
        raise ProjectionError("player combatant fields are invalid")
    return {
        "name": name,
        "kind": kind,
        "initiative": initiative,
        "status": status,
    }


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
    if revision is None:
        raise ProjectionError("player active-PC revision is invalid")
    party = {
        "members": members,
        "active_character": active_name,
        "active_character_revision": revision,
        "world": _project_world(raw_party.get("world")),
    }
    result: dict[str, object] = {"party": party}
    if "transcript" in projection:
        result["transcript"] = _sanitize_player_transcript(projection["transcript"])
    if "combat" in projection:
        result["combat"] = _sanitize_player_combat(projection["combat"])
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
    portrait_media_id = record.get("portrait_media_id")
    if (
        isinstance(portrait_media_id, str)
        and portrait_media_id == player_portrait_media_id(valid_name)
    ):
        projected["portrait_media_id"] = portrait_media_id
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
