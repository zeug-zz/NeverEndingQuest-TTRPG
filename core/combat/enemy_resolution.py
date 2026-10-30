# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts and planner for deterministic enemy batches.

Input contract for :func:`plan_enemy_batch`:

* ``encounter`` is a loaded encounter mapping with ``encounterId`` (or ``id``),
  ``combat_round`` (or ``current_round``), and a ``creatures`` list. Creature
  entries use the runtime/schema fields ``name``, ``type`` (``enemy``,
  ``player``, or ``npc``), ``initiative``, ``status``, ``currentHitPoints``,
  ``maxHitPoints``, and optionally ``monsterType``, ``leader``, ``numAttacks``,
  ``conditions``, and ``attacks``. ``attacks`` may supply complete attack
  records; the latency fixture's name-only ``attacks`` list is accepted as
  metadata while the authored monster definition supplies the mechanics.
* ``pc_states`` maps PC names to authoritative character JSON mappings or
  runtime ``PCCombatState``-like objects. The state must provide current HP,
  maximum HP, AC, and status, using either the character keys ``hitPoints``,
  ``maxHitPoints``, ``armorClass`` or runtime attributes ``current_hp``,
  ``max_hp``, ``ac``. Optional character condition, death-save, and damage
  mitigation fields are inspected but never changed. Name matching is exact
  after trimming/collapsing whitespace and case-folding.
* ``monster_definitions`` maps ``monsterType`` names to a monster definition
  with an authored ``actions`` list, or directly to an ordered list of action
  mappings. The Capture_Arena Goblin action shape (``name``, integer
  ``attackBonus``, ``damageDice`` as ``NdM``, integer ``damageBonus``, and
  ``damageType``) is supported. A fully populated per-encounter ``attacks``
  list is also accepted when no definition is supplied.
* ``turn_order`` is the complete authoritative initiative order, represented
  by identities, ``(name, kind)`` pairs, runtime combatants, or mappings with
  ``name`` and ``kind``/``type``. Kind ``pc`` aliases ``player``. An untyped
  name is accepted only when it is unique across kinds. ``enemy_turn_window``
  is the ordered scheduled actor subset; if omitted, enemy actors are selected
  from ``turn_order`` in order. A window mapping can optionally specify
  ``scheduled_action_kind`` to identify an unsupported scheduled mechanic.

Planning hashes canonical JSON of the pre-batch inputs plus encounter ID,
round, batch ID/kind, and optional fixture seed. It uses only a local
``random.Random`` and returns frozen dataclasses containing tuples. It never
reads or writes files, mutates input objects, or advances runtime state. Any
unsupported or ambiguous fact returns one code from ``DECLINE_REASON_CODES``.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Optional, Union

from core.combat.cover import effective_ac_for_creature, is_authorized_ranged_action


DECLINE_REASON_CODES = frozenset({
    "malformed_input",
    "malformed_encounter",
    "invalid_batch_identity",
    "malformed_turn_order",
    "ambiguous_identity",
    "unknown_actor",
    "npc_actor_in_window",
    "unsupported_actor_kind",
    "multiple_leaders",
    "leader_down",
    "near_death_enemy",
    "unknown_target",
    "no_eligible_target",
    "downed_target",
    "unsupported_target_state",
    "damage_mitigation",
    "unsupported_condition",
    "advantage_or_disadvantage",
    "missing_monster_definition",
    "malformed_monster_definition",
    "malformed_multiattack",
    "unknown_action",
    "ambiguous_action",
    "bare_multiattack",
    "unsupported_num_attacks",
    "unsupported_spell",
    "unsupported_save",
    "unsupported_special_action",
    "unsupported_legendary_action",
    "unsupported_reaction",
    "unsupported_action",
    "missing_attack_stats",
    "malformed_attack_stats",
    "unsupported_damage_dice",
    "missing_target_ac",
    "malformed_pc_state",
})

_VALID_KINDS = frozenset({"enemy", "npc", "player"})
_INACTIVE_PC_STATUSES = frozenset({"dead", "defeated"})
_DOWN_PC_STATUSES = frozenset({"unconscious", "incapacitated", "stable"})
_DICE_RE = re.compile(r"^([1-9][0-9]*)[dD]([2-9][0-9]*)$")
_MAX_DICE_COUNT = 100
_MAX_DIE_SIDES = 1000
_DAMAGE_TYPES = frozenset({
    "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
    "piercing", "poison", "psychic", "radiant", "slashing", "thunder",
})


@dataclass(frozen=True, order=True)
class CombatantIdentity:
    """A stable combatant identity that cannot collide across combatant kinds."""

    name: str
    kind: str


@dataclass(frozen=True)
class EnemyAttackLedgerEntry:
    """One immutable, fully resolved enemy weapon attack."""

    actor: CombatantIdentity
    action_name: str
    target: CombatantIdentity
    d20: int
    attack_total: int
    armor_class: int
    hit: bool
    critical: bool
    damage_dice_rolls: tuple[int, ...]
    damage_total: int
    damage_type: str
    target_hp_before: int
    target_hp_after: int
    target_status_after: str
    target_max_hp: Optional[int] = None
    action_is_ranged: bool = False


@dataclass(frozen=True)
class EnemyBloodiedFlag:
    """Batch-start bloodied projection for one encounter enemy."""

    enemy: CombatantIdentity
    bloodied: bool


@dataclass(frozen=True)
class EnemyDeparture:
    """A commander-authorized enemy departure persisted with the final batch."""

    enemy: CombatantIdentity
    reason: str


@dataclass(frozen=True)
class EnemyCoverUpdate:
    """One bounded cover selection or clearing operation for an encounter actor."""

    enemy: CombatantIdentity
    feature_id: Optional[str] = None
    cover_type: Optional[str] = None


@dataclass(frozen=True)
class EnemyResolutionLedger:
    """A complete immutable resolution plan for one eligible enemy batch."""

    encounter_id: str
    round_number: int
    batch_id: str
    batch_kind: str
    seed: int
    entries: tuple[EnemyAttackLedgerEntry, ...]
    bloodied: tuple[EnemyBloodiedFlag, ...]
    departures: tuple[EnemyDeparture, ...] = ()
    cover_updates: tuple[EnemyCoverUpdate, ...] = ()


@dataclass(frozen=True)
class EnemyResolutionDecline:
    """A whole-batch fallback decision carrying only a bounded reason code."""

    reason_code: str
    batch_id: str = ""


EnemyResolutionResult = Union[EnemyResolutionLedger, EnemyResolutionDecline]


@dataclass
class _PcProjection:
    """Private mutable PC projection; never aliases or mutates caller state."""

    identity: CombatantIdentity
    hp: int
    max_hp: int
    armor_class: int
    status: str
    death_successes: int
    death_failures: int
    conditions: tuple[str, ...]
    mitigation: dict[str, Any]
    mechanically_dead: bool


@dataclass(frozen=True)
class _ActorReference:
    identity: CombatantIdentity
    scheduled_action: Optional[str] = None
    scheduled_action_kind: Optional[str] = None


class _Decline(Exception):
    def __init__(self, reason_code: str):
        if reason_code not in DECLINE_REASON_CODES:
            reason_code = "malformed_input"
        self.reason_code = reason_code


def _decline(reason_code: str, batch_id: str = "") -> EnemyResolutionDecline:
    if reason_code not in DECLINE_REASON_CODES:
        reason_code = "malformed_input"
    return EnemyResolutionDecline(reason_code=reason_code, batch_id=batch_id)


def _kind_name(raw_kind: Any) -> Optional[str]:
    if isinstance(raw_kind, Enum):
        raw_kind = raw_kind.value
    if not isinstance(raw_kind, str):
        return None
    kind = raw_kind.strip().lower()
    if kind == "pc":
        kind = "player"
    return kind if kind in _VALID_KINDS else None


def _canonical_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _identity_key(identity: CombatantIdentity) -> tuple[str, str]:
    return identity.kind, _canonical_name(identity.name)


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _parse_identity_ref(reference: Any) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return name, kind, scheduled action, scheduled action kind."""
    name: Any = None
    raw_kind: Any = None
    action: Any = None
    action_kind: Any = None
    if isinstance(reference, CombatantIdentity):
        name, raw_kind = reference.name, reference.kind
    elif isinstance(reference, str):
        name = reference
    elif isinstance(reference, (tuple, list)) and len(reference) == 2:
        first, second = reference
        if _kind_name(first):
            raw_kind, name = first, second
        else:
            name, raw_kind = first, second
    elif isinstance(reference, Mapping):
        name = reference.get("name", reference.get("character_name"))
        raw_kind = reference.get("kind", reference.get("type"))
        action = reference.get("scheduled_action", reference.get("action_name"))
        action_kind = reference.get(
            "scheduled_action_kind", reference.get("action_kind")
        )
        # Actor-window adapters sometimes expose a typed action object.
        raw_action = reference.get("action")
        if isinstance(raw_action, str) and action is None:
            action = raw_action
        elif isinstance(raw_action, Mapping) and action_kind is None:
            action_kind = raw_action.get("actionType", raw_action.get("type"))
    else:
        name = getattr(reference, "name", None)
        raw_kind = getattr(reference, "kind", getattr(reference, "type", None))

    clean_name = name.strip() if isinstance(name, str) else None
    kind = _kind_name(raw_kind)
    clean_action = action.strip() if isinstance(action, str) and action.strip() else None
    clean_action_kind = (
        action_kind.strip().lower()
        if isinstance(action_kind, str) and action_kind.strip()
        else None
    )
    return clean_name, kind, clean_action, clean_action_kind


def _resolve_identity(
    reference: Any,
    roster: Mapping[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
    *,
    missing_code: str,
) -> tuple[CombatantIdentity, Optional[str], Optional[str]]:
    name, kind, scheduled_action, scheduled_action_kind = _parse_identity_ref(reference)
    if not name:
        raise _Decline("malformed_turn_order")
    canonical = _canonical_name(name)
    if kind:
        match = roster.get((kind, canonical))
        if match is None:
            raise _Decline(missing_code)
        return match[0], scheduled_action, scheduled_action_kind

    matches = [value for key, value in roster.items() if key[1] == canonical]
    if not matches:
        raise _Decline(missing_code)
    if len(matches) != 1:
        raise _Decline("ambiguous_identity")
    return matches[0][0], scheduled_action, scheduled_action_kind


def _json_compatible(value: Any) -> Any:
    """Convert supported runtime dataclasses/enums to canonical JSON values."""
    if isinstance(value, Enum):
        return _json_compatible(value.value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        converted = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON mappings require string keys")
            converted[key] = _json_compatible(nested)
        return converted
    if isinstance(value, (tuple, list)):
        return [_json_compatible(nested) for nested in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _json_compatible(getattr(value, item.name))
            for item in fields(value)
        }
    if hasattr(value, "__dict__"):
        return _json_compatible(vars(value))
    raise TypeError("unsupported value in canonical pre-batch state")


def derive_enemy_batch_seed(
    pre_batch_state: Mapping[str, Any],
    *,
    encounter_id: str,
    round_number: int,
    batch_id: str,
    batch_kind: str,
    fixture_seed: Optional[Union[str, int]] = None,
) -> int:
    """Derive the local RNG seed from sorted canonical JSON and SHA-256."""
    seed_payload = {
        "pre_batch_state": _json_compatible(pre_batch_state),
        "encounter_id": encounter_id,
        "round": round_number,
        "batch_id": batch_id,
        "batch_kind": batch_kind,
        "fixture_seed": fixture_seed,
    }
    canonical = json.dumps(
        seed_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return int.from_bytes(hashlib.sha256(canonical.encode("utf-8")).digest(), "big")


def _strict_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _field_from_state(state: Any, mapping_key: str, object_key: str) -> Any:
    if isinstance(state, Mapping):
        return state.get(mapping_key, state.get(object_key))
    return getattr(state, object_key, getattr(state, mapping_key, None))


def _state_mapping(state: Any) -> Mapping[str, Any]:
    if isinstance(state, Mapping):
        return state
    if is_dataclass(state) and not isinstance(state, type):
        return {item.name: getattr(state, item.name) for item in fields(state)}
    if hasattr(state, "__dict__"):
        return vars(state)
    raise _Decline("malformed_pc_state")


def _death_save_counts(state: Mapping[str, Any]) -> tuple[int, int]:
    raw = state.get("deathSaves")
    if isinstance(raw, Mapping):
        successes = raw.get("successes", 0)
        failures = raw.get("failures", 0)
    else:
        successes = state.get("deathSaveSuccesses", state.get("death_save_successes", 0))
        failures = state.get("deathSaveFailures", state.get("death_save_failures", 0))
    success_int = _strict_int(successes)
    failure_int = _strict_int(failures)
    if success_int is None or failure_int is None or success_int < 0 or failure_int < 0:
        raise _Decline("malformed_pc_state")
    return success_int, failure_int


def _normalize_condition_values(*values: Any) -> tuple[str, ...]:
    result = []
    for value in values:
        if value in (None, "", "none", "normal"):
            continue
        if isinstance(value, str):
            values_iterable = [value]
        elif isinstance(value, (list, tuple)):
            values_iterable = value
        else:
            raise _Decline("malformed_pc_state")
        for item in values_iterable:
            if not isinstance(item, str):
                raise _Decline("malformed_pc_state")
            normalized = item.strip().lower()
            if normalized and normalized not in ("none", "normal") and normalized not in result:
                result.append(normalized)
    return tuple(result)


def _load_pc_projection(
    identity: CombatantIdentity,
    encounter_creature: Mapping[str, Any],
    pc_states: Mapping[str, Any],
    *,
    encounter_id: Any = None,
    active_encounter_id: Any = None,
    combat_in_progress: bool = False,
    tactical_features: Any = None,
) -> _PcProjection:
    matched = [
        (key, value)
        for key, value in pc_states.items()
        if isinstance(key, str) and _canonical_name(key) == _canonical_name(identity.name)
    ]
    if len(matched) != 1:
        raise _Decline("unknown_target")
    state = matched[0][1]
    state_values = _state_mapping(state)
    state_name = state_values.get("name", getattr(state, "character_name", None))
    if isinstance(state_name, str) and _canonical_name(state_name) != _canonical_name(identity.name):
        raise _Decline("malformed_pc_state")

    hp = _strict_int(_field_from_state(state, "hitPoints", "current_hp"))
    max_hp = _strict_int(_field_from_state(state, "maxHitPoints", "max_hp"))
    armor_class = _strict_int(_field_from_state(state, "armorClass", "ac"))
    if hp is None or max_hp is None or hp < 0 or max_hp <= 0:
        raise _Decline("malformed_pc_state")
    if armor_class is None:
        raise _Decline("missing_target_ac")
    armor_class = effective_ac_for_creature(
        armor_class,
        encounter_creature,
        encounter_id=encounter_id,
        active_encounter_id=active_encounter_id,
        combat_in_progress=combat_in_progress,
        tactical_features=tactical_features,
    )

    status_raw = state_values.get("status", "alive")
    if isinstance(status_raw, Enum):
        status_raw = status_raw.value
    if not isinstance(status_raw, str) or not status_raw.strip():
        raise _Decline("malformed_pc_state")
    status = status_raw.strip().lower()
    if status in {"ready", "acted"}:
        status = "alive"
    elif status == "incapacitated":
        status = "unconscious"

    successes, failures = _death_save_counts(state_values)
    conditions = _normalize_condition_values(
        state_values.get("condition"),
        state_values.get("condition_affected", []),
        encounter_creature.get("condition"),
        encounter_creature.get("conditions", []),
    )
    mitigation = {}
    for key in (
        "damageResistances", "damageImmunities", "damageVulnerabilities",
        "damage_resistances", "damage_immunities", "damage_vulnerabilities",
    ):
        value = state_values.get(key, encounter_creature.get(key, []))
        if value not in (None, [], ""):
            mitigation[key] = value

    mechanically_dead = status == "dead" or failures >= 3
    return _PcProjection(
        identity=identity,
        hp=hp,
        max_hp=max_hp,
        armor_class=armor_class,
        status=status,
        death_successes=successes,
        death_failures=failures,
        conditions=conditions,
        mitigation=mitigation,
        mechanically_dead=mechanically_dead,
    )


def _normalize_roster(encounter: Mapping[str, Any]) -> dict[
    tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]
]:
    creatures = encounter.get("creatures")
    if not isinstance(creatures, list):
        raise _Decline("malformed_encounter")
    roster = {}
    for creature in creatures:
        if not isinstance(creature, Mapping):
            raise _Decline("malformed_encounter")
        name = creature.get("name")
        kind = _kind_name(creature.get("type"))
        if not isinstance(name, str) or not name.strip() or kind is None:
            raise _Decline("malformed_encounter")
        identity = CombatantIdentity(name=name.strip(), kind=kind)
        key = _identity_key(identity)
        if key in roster:
            raise _Decline("ambiguous_identity")
        roster[key] = (identity, creature)
    return roster


def _normalize_turn_order(
    turn_order: Any,
    roster: Mapping[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
) -> list[CombatantIdentity]:
    if not isinstance(turn_order, Sequence) or isinstance(turn_order, (str, bytes)) or not turn_order:
        raise _Decline("malformed_turn_order")
    normalized = []
    seen = set()
    for reference in turn_order:
        identity, _, _ = _resolve_identity(reference, roster, missing_code="unknown_actor")
        key = _identity_key(identity)
        if key in seen:
            raise _Decline("malformed_turn_order")
        normalized.append(identity)
        seen.add(key)
    return normalized


def _normalize_enemy_window(
    enemy_turn_window: Any,
    turn_order: Sequence[CombatantIdentity],
    roster: Mapping[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
) -> list[_ActorReference]:
    if enemy_turn_window is None:
        references: Sequence[Any] = [item for item in turn_order if item.kind == "enemy"]
    elif isinstance(enemy_turn_window, Sequence) and not isinstance(enemy_turn_window, (str, bytes)):
        references = enemy_turn_window
    else:
        raise _Decline("malformed_turn_order")
    if not references:
        raise _Decline("no_eligible_target")

    result = []
    seen = set()
    order_keys = {_identity_key(identity) for identity in turn_order}
    for reference in references:
        identity, scheduled_action, scheduled_action_kind = _resolve_identity(
            reference, roster, missing_code="unknown_actor"
        )
        key = _identity_key(identity)
        if key in seen or key not in order_keys:
            raise _Decline("malformed_turn_order")
        seen.add(key)
        if identity.kind == "npc":
            raise _Decline("npc_actor_in_window")
        if identity.kind != "enemy":
            raise _Decline("unsupported_actor_kind")
        result.append(_ActorReference(identity, scheduled_action, scheduled_action_kind))
    return result


def _get_monster_actions(
    creature: Mapping[str, Any], monster_definitions: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    monster_type = creature.get("monsterType")
    definition = None
    if isinstance(monster_type, str) and monster_type.strip():
        matches = [
            value for key, value in monster_definitions.items()
            if isinstance(key, str) and _canonical_name(key) == _canonical_name(monster_type)
        ]
        if len(matches) > 1:
            raise _Decline("malformed_monster_definition")
        if matches:
            definition = matches[0]

    if definition is not None:
        if isinstance(definition, Mapping):
            actions = definition.get("actions")
        else:
            actions = definition
    else:
        actions = creature.get("attacks")
        if not isinstance(actions, list) or not any(
            isinstance(item, Mapping) and _has_attack_stats(item) for item in actions
        ):
            raise _Decline("missing_monster_definition")

    if not isinstance(actions, list):
        raise _Decline("malformed_monster_definition")
    normalized = []
    for action in actions:
        if not isinstance(action, Mapping):
            raise _Decline("malformed_monster_definition")
        name = action.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _Decline("malformed_monster_definition")
        normalized.append(action)
    return tuple(normalized)


def _has_attack_stats(action: Mapping[str, Any]) -> bool:
    return any(key in action for key in ("attackBonus", "damageDice", "damageType"))


def _unsupported_category_code(raw_category: Any) -> Optional[str]:
    if not isinstance(raw_category, str):
        return None
    category = raw_category.strip().lower().replace("-", "_").replace(" ", "_")
    if category in {"spell", "spell_attack", "cantrip", "spellcasting"}:
        return "unsupported_spell"
    if category in {"save", "saving_throw", "savingthrow", "ability_check"}:
        return "unsupported_save"
    if category in {"condition", "conditions", "status_effect"}:
        return "unsupported_condition"
    if category in {"legendary", "legendary_action", "legendary_actions"}:
        return "unsupported_legendary_action"
    if category in {"reaction", "reactions"}:
        return "unsupported_reaction"
    if category in {"special", "special_action", "special_ability", "special_abilities"}:
        return "unsupported_special_action"
    return None


def _action_decline_code(action: Mapping[str, Any]) -> Optional[str]:
    for field_name in ("actionType", "type", "action_type", "kind"):
        code = _unsupported_category_code(action.get(field_name))
        if code:
            return code
    explicit_markers = (
        ("spell", "unsupported_spell"),
        ("savingThrow", "unsupported_save"),
        ("saving_throw", "unsupported_save"),
        ("save", "unsupported_save"),
        ("condition", "unsupported_condition"),
        ("conditions", "unsupported_condition"),
        ("special", "unsupported_special_action"),
        ("legendary", "unsupported_legendary_action"),
        ("reaction", "unsupported_reaction"),
    )
    for key, reason in explicit_markers:
        if key in action and action[key] not in (None, False, "", [], {}):
            return reason

    for key in (
        "advantage", "disadvantage", "hasAdvantage", "hasDisadvantage",
        "attackAdvantage", "attackDisadvantage",
    ):
        if key in action and action[key] not in (None, False, "", 0):
            return "advantage_or_disadvantage"
    if action.get("requiresAdvantage") is True or action.get("requiresDisadvantage") is True:
        return "advantage_or_disadvantage"

    action_type = action.get("type")
    if action_type is not None:
        if not isinstance(action_type, str):
            return "unsupported_action"
        normalized = action_type.strip().lower()
        supported_types = {
            "", "attack", "weapon", "melee", "ranged", "melee weapon attack",
            "ranged weapon attack", "weapon attack",
        }
        if normalized not in supported_types:
            return "unsupported_action"
    return None


def _is_attack_candidate(action: Mapping[str, Any]) -> bool:
    name = str(action.get("name", "")).strip().lower()
    if name == "multiattack":
        return False
    action_type = action.get("type")
    if isinstance(action_type, str) and action_type.strip().lower() in {
        "attack", "weapon", "melee", "ranged", "melee weapon attack",
        "ranged weapon attack", "weapon attack",
    }:
        return True
    return _has_attack_stats(action) or "attack" in name


def _validated_attack(action: Mapping[str, Any]) -> tuple[str, int, int, int, str, int, int]:
    action_name = action.get("name")
    if any(
        key not in action
        for key in ("attackBonus", "damageDice", "damageBonus", "damageType")
    ):
        raise _Decline("missing_attack_stats")
    attack_bonus = _strict_int(action.get("attackBonus"))
    damage_bonus_raw = action.get("damageBonus")
    damage_bonus = _strict_int(damage_bonus_raw)
    damage_dice = action.get("damageDice")
    damage_type = action.get("damageType")
    if attack_bonus is None or damage_bonus is None:
        raise _Decline("malformed_attack_stats")
    if not isinstance(damage_dice, str) or not isinstance(damage_type, str):
        raise _Decline("malformed_attack_stats")
    if not damage_type.strip():
        raise _Decline("missing_attack_stats")
    dice_match = _DICE_RE.fullmatch(damage_dice.strip())
    if not dice_match:
        raise _Decline("unsupported_damage_dice")
    dice_count = int(dice_match.group(1))
    die_sides = int(dice_match.group(2))
    if dice_count > _MAX_DICE_COUNT or die_sides > _MAX_DIE_SIDES:
        raise _Decline("unsupported_damage_dice")
    if isinstance(action_name, str) and action_name.strip():
        clean_name = action_name.strip()
    else:
        raise _Decline("missing_attack_stats")
    return (
        clean_name,
        attack_bonus,
        damage_bonus,
        dice_count,
        damage_type.strip(),
        die_sides,
        0,
    )


def _definition_for_creature(
    creature: Mapping[str, Any], monster_definitions: Mapping[str, Any]
) -> Any:
    monster_type = creature.get("monsterType")
    if not isinstance(monster_type, str) or not monster_type.strip():
        return None
    matches = [
        value for key, value in monster_definitions.items()
        if isinstance(key, str) and _canonical_name(key) == _canonical_name(monster_type)
    ]
    if len(matches) > 1:
        raise _Decline("malformed_monster_definition")
    return matches[0] if matches else None


def _select_actions(
    actor: _ActorReference,
    creature: Mapping[str, Any],
    definition: Any,
    actions: Sequence[Mapping[str, Any]],
) -> tuple[tuple[Mapping[str, Any], ...], tuple[tuple[str, int], ...]]:
    scheduled_code = _unsupported_category_code(actor.scheduled_action_kind)
    if scheduled_code:
        raise _Decline(scheduled_code)

    if any(str(item.get("name", "")).strip().casefold() == "multiattack" for item in actions):
        if not isinstance(definition, Mapping) or "multiattack" not in definition:
            raise _Decline("bare_multiattack")

    declaration = definition.get("multiattack") if isinstance(definition, Mapping) else None
    if definition is not None and "multiattack" in definition:
        if not isinstance(declaration, list) or not declaration:
            raise _Decline("malformed_multiattack")
        errors = validate_multiattack_declaration(definition)
        if errors:
            if "multiattack_action_ambiguous" in errors:
                raise _Decline("ambiguous_action")
            if "multiattack_action_unknown" in errors:
                raise _Decline("unknown_action")
            raise _Decline("malformed_multiattack")
        selected = []
        counts = []
        for item in declaration:
            matches = [candidate for candidate in actions if candidate.get("name") == item["action"]]
            if len(matches) != 1:
                raise _Decline("ambiguous_action" if matches else "unknown_action")
            selected.append(matches[0])
            counts.append((item["action"], item["count"]))
        return tuple(selected), tuple(counts)

    num_attacks = creature.get("numAttacks")
    if num_attacks is not None:
        count = _strict_int(num_attacks)
        if count is None or count != 1:
            raise _Decline("unsupported_num_attacks")

    selected_action: Optional[Mapping[str, Any]] = None
    first_unsupported: Optional[str] = None
    for action in actions:
        if not _is_attack_candidate(action):
            code = _action_decline_code(action)
            if code and first_unsupported is None:
                first_unsupported = code
            continue
        code = _action_decline_code(action)
        if code:
            if code == "advantage_or_disadvantage":
                raise _Decline(code)
            if first_unsupported is None:
                first_unsupported = code
            continue
        selected_action = action
        break
    if selected_action is None:
        raise _Decline(first_unsupported or "unsupported_action")
    if actor.scheduled_action and actor.scheduled_action.casefold() != str(
        selected_action.get("name", "")
    ).casefold():
        scheduled_matches = [
            item for item in actions
            if str(item.get("name", "")).casefold() == actor.scheduled_action.casefold()
        ]
        if not scheduled_matches:
            raise _Decline("unknown_action")
        if len(scheduled_matches) > 1:
            raise _Decline("ambiguous_action")
        scheduled = scheduled_matches[0]
        code = _action_decline_code(scheduled)
        if code:
            raise _Decline(code)
        # Without an authored multiattack declaration, action order is
        # authoritative; an externally selected later action is not inferred.
        raise _Decline("unsupported_action")
    return (selected_action,), ((str(selected_action["name"]), 1),)


def _damage_mitigation_applies(mitigation: Mapping[str, Any], damage_type: str) -> bool:
    target_type = damage_type.strip().lower()
    for raw in mitigation.values():
        entries = raw if isinstance(raw, (list, tuple)) else [raw]
        for entry in entries:
            if not isinstance(entry, str):
                return True
            normalized = entry.strip().lower()
            if not normalized:
                continue
            tokens = set(re.findall(r"[a-z]+", normalized))
            if target_type in tokens or "all" in tokens:
                return True
            # Unknown mitigation prose cannot be proven irrelevant. Known
            # typed entries that omit this damage type are safely irrelevant.
            if not tokens.intersection(_DAMAGE_TYPES):
                return True
    return False


def _eligible_pc_target(projection: _PcProjection) -> tuple[bool, Optional[str]]:
    if projection.mechanically_dead or projection.status in _INACTIVE_PC_STATUSES:
        return False, None
    if projection.hp <= 0 or projection.status in _DOWN_PC_STATUSES:
        return False, "downed_target"
    if projection.status != "alive":
        return False, "unsupported_target_state"
    if projection.death_successes or projection.death_failures:
        return False, "unsupported_target_state"
    if "unconscious" in projection.conditions:
        return False, "downed_target"
    if projection.conditions:
        return False, "unsupported_target_state"
    return True, None


def _next_target(
    *,
    order: Sequence[CombatantIdentity],
    actor: CombatantIdentity,
    cursor: CombatantIdentity,
    roster: Mapping[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
    projections: Mapping[tuple[str, str], _PcProjection],
) -> tuple[_PcProjection, int]:
    try:
        start = next(index for index, item in enumerate(order) if _identity_key(item) == _identity_key(cursor))
    except StopIteration:
        raise _Decline("malformed_turn_order")
    for offset in range(1, len(order) + 1):
        index = (start + offset) % len(order)
        identity = order[index]
        if identity.kind != "player":
            continue
        projection = projections.get(_identity_key(identity))
        if projection is None:
            raise _Decline("unknown_target")
        eligible, decline_code = _eligible_pc_target(projection)
        if eligible:
            return projection, index
        if decline_code:
            # Dead and defeated PCs alone are skipped. A selected 0-HP or
            # otherwise unresolved state invalidates the whole batch.
            raise _Decline(decline_code)
    raise _Decline("no_eligible_target")


def _explicit_tactical_target(
    reference: Any,
    *,
    roster: Mapping[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
    projections: Mapping[tuple[str, str], _PcProjection],
) -> _PcProjection:
    """Resolve a validated menu target against the live batch projection."""
    identity, _, _ = _resolve_identity(reference, roster, missing_code="unknown_target")
    if identity.kind != "player":
        raise _Decline("unknown_target")
    projection = projections.get(_identity_key(identity))
    if projection is None:
        raise _Decline("unknown_target")
    eligible, decline_code = _eligible_pc_target(projection)
    if not eligible:
        raise _Decline(decline_code or "unknown_target")
    return projection


def _coerce_enemy_hp(creature: Mapping[str, Any]) -> tuple[int, int, str]:
    hp = _strict_int(creature.get("currentHitPoints"))
    max_hp = _strict_int(creature.get("maxHitPoints"))
    status = creature.get("status", "alive")
    if hp is None or max_hp is None or max_hp <= 0 or hp < 0:
        raise _Decline("malformed_encounter")
    if not isinstance(status, str) or not status.strip():
        raise _Decline("malformed_encounter")
    return hp, max_hp, status.strip().lower()


def _actor_conditions(creature: Mapping[str, Any]) -> tuple[str, ...]:
    conditions = _normalize_condition_values(
        creature.get("condition"), creature.get("conditions", [])
    )
    if conditions:
        raise _Decline("unsupported_condition")
    return conditions


def _canonical_pre_batch_state(
    encounter: Mapping[str, Any],
    pc_states: Mapping[str, Any],
    monster_definitions: Mapping[str, Any],
    turn_order: Sequence[Any],
    enemy_turn_window: Optional[Sequence[Any]],
) -> Mapping[str, Any]:
    return {
        "encounter": encounter,
        "pc_states": pc_states,
        "monster_definitions": monster_definitions,
        "turn_order": turn_order,
        "enemy_turn_window": enemy_turn_window,
    }


def plan_enemy_batch(
    encounter: Mapping[str, Any],
    pc_states: Mapping[str, Any],
    monster_definitions: Mapping[str, Any],
    turn_order: Sequence[Any],
    batch_id: str,
    batch_kind: str = "enemy_phase",
    fixture_seed: Optional[Union[str, int]] = None,
    enemy_turn_window: Optional[Sequence[Any]] = None,
    allow_near_death: bool = False,
    attack_target_overrides: Optional[Mapping[tuple[str, str], Sequence[Any]]] = None,
    active_encounter_id: Optional[str] = None,
    combat_in_progress: bool = False,
    tactical_features: Any = None,
) -> EnemyResolutionResult:
    """Plan a complete enemy weapon batch, or decline it without side effects.

    ``turn_order`` contains all combatants in initiative order; the optional
    ``enemy_turn_window`` contains the ordered non-PC actors due in this batch.
    Its default schedules every enemy in the full turn order. No input mapping
    or object is mutated. The returned ledger is usable only as a plan: this
    function performs no persistence and does not apply any entry to runtime
    state. ``attack_target_overrides`` is an internal, post-validation selector
    keyed by canonical (kind, name) identity; every selected target is still
    rechecked against the evolving authoritative batch projection.
    """
    batch_label = batch_id if isinstance(batch_id, str) else ""
    try:
        if not isinstance(encounter, Mapping) or not isinstance(pc_states, Mapping):
            raise _Decline("malformed_input")
        if not isinstance(monster_definitions, Mapping):
            raise _Decline("malformed_input")
        if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 128:
            raise _Decline("invalid_batch_identity")
        if not isinstance(batch_kind, str) or not batch_kind.strip() or len(batch_kind) > 64:
            raise _Decline("invalid_batch_identity")
        if fixture_seed is not None and not isinstance(fixture_seed, (str, int)):
            raise _Decline("malformed_input")
        if isinstance(fixture_seed, bool):
            raise _Decline("malformed_input")
        if not isinstance(allow_near_death, bool):
            raise _Decline("malformed_input")
        if not isinstance(combat_in_progress, bool):
            raise _Decline("malformed_input")
        if active_encounter_id is not None and not isinstance(active_encounter_id, str):
            raise _Decline("malformed_input")
        if attack_target_overrides is not None and not isinstance(
            attack_target_overrides, Mapping
        ):
            raise _Decline("malformed_input")

        encounter_id = encounter.get("encounterId", encounter.get("id"))
        if not isinstance(encounter_id, str) or not encounter_id.strip():
            raise _Decline("malformed_encounter")
        round_number = _strict_int(encounter.get("combat_round", encounter.get("current_round", 1)))
        if round_number is None or round_number < 1:
            raise _Decline("malformed_encounter")

        roster = _normalize_roster(encounter)
        order = _normalize_turn_order(turn_order, roster)
        actor_window = _normalize_enemy_window(enemy_turn_window, order, roster)

        creatures = encounter.get("creatures", [])
        leaders = []
        enemies = []
        for identity, creature in roster.values():
            leader_value = creature.get("leader", False)
            if not isinstance(leader_value, bool):
                raise _Decline("malformed_encounter")
            if leader_value:
                leaders.append((identity, creature))
            if identity.kind == "enemy":
                enemies.append((identity, creature))
        if len(leaders) > 1:
            raise _Decline("multiple_leaders")

        projections: dict[tuple[str, str], _PcProjection] = {}
        for identity, creature in roster.values():
            if identity.kind == "player":
                projection = _load_pc_projection(
                    identity,
                    creature,
                    pc_states,
                    encounter_id=encounter_id,
                    active_encounter_id=active_encounter_id,
                    combat_in_progress=combat_in_progress,
                    tactical_features=tactical_features,
                )
                projections[_identity_key(identity)] = projection
        if leaders:
            leader_identity, leader_creature = leaders[0]
            if leader_identity.kind == "player":
                leader_projection = projections[_identity_key(leader_identity)]
                leader_down = (
                    leader_projection.mechanically_dead
                    or leader_projection.hp <= 0
                    or leader_projection.status in _INACTIVE_PC_STATUSES
                )
            else:
                leader_hp, _, leader_status = _coerce_enemy_hp(leader_creature)
                leader_down = leader_hp <= 0 or leader_status in _INACTIVE_PC_STATUSES
            if leader_down:
                raise _Decline("leader_down")

        bloodied_flags = []
        enemy_stats = {}
        for identity, creature in enemies:
            hp, max_hp, status = _coerce_enemy_hp(creature)
            enemy_stats[_identity_key(identity)] = (hp, max_hp, status)
            bloodied_flags.append(
                EnemyBloodiedFlag(
                    enemy=identity,
                    bloodied=hp > 0 and hp * 2 <= max_hp,
                )
            )

        for actor_ref in actor_window:
            actor_hp, actor_max_hp, actor_status = enemy_stats[_identity_key(actor_ref.identity)]
            if (
                not allow_near_death
                and actor_hp > 0
                and actor_hp * 4 <= actor_max_hp
            ):
                raise _Decline("near_death_enemy")
            if actor_hp <= 0 or actor_status in _INACTIVE_PC_STATUSES:
                raise _Decline("malformed_encounter")
            _, actor_creature = roster[_identity_key(actor_ref.identity)]
            _actor_conditions(actor_creature)

        pre_batch_state = _canonical_pre_batch_state(
            encounter, pc_states, monster_definitions, turn_order, enemy_turn_window
        )
        try:
            seed = derive_enemy_batch_seed(
                pre_batch_state,
                encounter_id=encounter_id,
                round_number=round_number,
                batch_id=batch_id,
                batch_kind=batch_kind,
                fixture_seed=fixture_seed,
            )
        except (TypeError, ValueError, OverflowError):
            raise _Decline("malformed_input")
        rng = random.Random(seed)
        entries = []

        for actor_ref in actor_window:
            actor_key = _identity_key(actor_ref.identity)
            _, actor_creature = roster[actor_key]
            definition = _definition_for_creature(actor_creature, monster_definitions)
            actions = _get_monster_actions(actor_creature, monster_definitions)
            selected_actions, action_counts = _select_actions(
                actor_ref, actor_creature, definition, actions
            )
            expanded_actions = []
            for selected, (_, count) in zip(selected_actions, action_counts):
                expanded_actions.extend([selected] * count)

            selected_targets = (
                attack_target_overrides.get(actor_key)
                if attack_target_overrides is not None else None
            )
            if selected_targets is not None:
                if (
                    not isinstance(selected_targets, Sequence)
                    or isinstance(selected_targets, (str, bytes))
                    or len(selected_targets) != len(expanded_actions)
                ):
                    raise _Decline("malformed_input")

            cursor = actor_ref.identity
            for action_index, action in enumerate(expanded_actions):
                action_code = _action_decline_code(action)
                if action_code:
                    raise _Decline(action_code)
                (
                    action_name,
                    attack_bonus,
                    damage_bonus,
                    dice_count,
                    damage_type,
                    die_sides,
                    _,
                ) = _validated_attack(action)
                action_is_ranged = is_authorized_ranged_action(action_name, action)
                if selected_targets is not None:
                    target_projection = _explicit_tactical_target(
                        selected_targets[action_index],
                        roster=roster,
                        projections=projections,
                    )
                else:
                    target_projection, _ = _next_target(
                        order=order,
                        actor=actor_ref.identity,
                        cursor=cursor,
                        roster=roster,
                        projections=projections,
                    )
                if _damage_mitigation_applies(target_projection.mitigation, damage_type):
                    raise _Decline("damage_mitigation")

                d20 = rng.randint(1, 20)
                attack_total = d20 + attack_bonus
                critical = d20 == 20
                hit = critical or (d20 != 1 and attack_total >= target_projection.armor_class)
                dice_rolls = ()
                damage_total = 0
                hp_before = target_projection.hp
                if hit:
                    roll_count = dice_count * (2 if critical else 1)
                    dice_rolls = tuple(rng.randint(1, die_sides) for _ in range(roll_count))
                    damage_total = max(0, sum(dice_rolls) + damage_bonus)
                    target_projection.hp = max(0, hp_before - damage_total)
                    target_projection.status = "unconscious" if target_projection.hp == 0 else "alive"
                entries.append(
                    EnemyAttackLedgerEntry(
                        actor=actor_ref.identity,
                        action_name=action_name,
                        target=target_projection.identity,
                        d20=d20,
                        attack_total=attack_total,
                        armor_class=target_projection.armor_class,
                        hit=hit,
                        critical=critical,
                        damage_dice_rolls=dice_rolls,
                        damage_total=damage_total,
                        damage_type=damage_type,
                        target_hp_before=hp_before,
                        target_hp_after=target_projection.hp,
                        target_status_after=target_projection.status,
                        target_max_hp=target_projection.max_hp,
                        action_is_ranged=action_is_ranged,
                    )
                )
                cursor = target_projection.identity

        return EnemyResolutionLedger(
            encounter_id=encounter_id.strip(),
            round_number=round_number,
            batch_id=batch_id,
            batch_kind=batch_kind.strip(),
            seed=seed,
            entries=tuple(entries),
            bloodied=tuple(bloodied_flags),
        )
    except _Decline as decline:
        return _decline(decline.reason_code, batch_label)
    except (TypeError, ValueError, KeyError, AttributeError):
        return _decline("malformed_input", batch_label)


def get_legal_enemy_batch_targets(
    encounter: Mapping[str, Any],
    pc_states: Mapping[str, Any],
    turn_order: Sequence[Any],
) -> Union[tuple[CombatantIdentity, ...], EnemyResolutionDecline]:
    """Return the resolver's ordered living-PC target set without rolling.

    This shares the resolver's identity, state, and target-eligibility helpers
    so tactical menus cannot widen the target set. Dead or defeated PCs are
    skipped exactly as they are by :func:`_next_target`; any unresolved/downed
    target state declines the projection with the same bounded reason.
    """
    try:
        if not isinstance(encounter, Mapping) or not isinstance(pc_states, Mapping):
            raise _Decline("malformed_input")
        roster = _normalize_roster(encounter)
        order = _normalize_turn_order(turn_order, roster)

        projections: dict[tuple[str, str], _PcProjection] = {}
        for identity, creature in roster.values():
            if identity.kind == "player":
                projections[_identity_key(identity)] = _load_pc_projection(
                    identity, creature, pc_states
                )

        targets = []
        for identity in order:
            if identity.kind != "player":
                continue
            projection = projections.get(_identity_key(identity))
            if projection is None:
                raise _Decline("unknown_target")
            eligible, decline_code = _eligible_pc_target(projection)
            if eligible:
                targets.append(identity)
            elif decline_code:
                raise _Decline(decline_code)

        if not targets:
            raise _Decline("no_eligible_target")
        return tuple(targets)
    except _Decline as decline:
        return _decline(decline.reason_code)
    except (TypeError, ValueError, KeyError, AttributeError):
        return _decline("malformed_input")

def validate_multiattack_declaration(monster: dict) -> list:
    """Return bounded error codes for malformed multiattack declarations."""
    if "multiattack" not in monster:
        return []

    declaration = monster["multiattack"]
    if not isinstance(declaration, list):
        return ["multiattack_not_list"]

    errors = []
    actions = monster.get("actions", [])
    action_names = [
        action.get("name")
        for action in actions
        if isinstance(action, dict)
    ] if isinstance(actions, list) else []

    for item in declaration:
        if not isinstance(item, dict):
            errors.append("multiattack_item_not_object")
            continue

        if set(item) - {"action", "count"}:
            errors.append("multiattack_item_extra_keys")

        action_name = item.get("action")
        if not isinstance(action_name, str) or not action_name.strip():
            errors.append("multiattack_action_invalid")
        else:
            matches = sum(name == action_name for name in action_names)
            if matches == 0:
                errors.append("multiattack_action_unknown")
            elif matches > 1:
                errors.append("multiattack_action_ambiguous")

        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            errors.append("multiattack_count_invalid")

    return errors


def count_encounter_leaders(encounter: dict) -> int:
    """Return the number of encounter creatures explicitly marked as leaders."""
    creatures = encounter.get("creatures", [])
    if not isinstance(creatures, list):
        return 0
    return sum(
        1
        for creature in creatures
        if isinstance(creature, dict) and creature.get("leader") is True
    )
