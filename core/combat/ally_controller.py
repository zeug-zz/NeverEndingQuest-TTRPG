# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Pure, provider-free ally menus, scoped perception, and plan validation.

This module is a choice layer only. It never calls a model, resolves an
attack, mutates an encounter, or writes campaign state. Mechanical attack
eligibility reuses the deterministic enemy resolver's existing weapon
contract; all returned options remain Python-owned snapshots.
"""

from __future__ import annotations

import hashlib
import json
import re
import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Optional, TypedDict, Union

from core.combat.cover import is_authorized_ranged_action
from core.combat.enemy_resolution import (
    CombatantIdentity,
    _action_decline_code,
    _is_attack_candidate,
    _Decline,
    _validated_attack,
)
from core.combat.tactical_contracts import validate_tactical_features
# TABLETOP MODE: Directive metadata remains durable history, outside provider messages.
from core.combat.turn_commit import (
    COMBAT_ALLY_DIRECTIVE_HISTORY_KEY,
    build_accepted_input_record,
)


MAX_ALLY_ACTORS = 32
MAX_ENCOUNTER_COMBATANTS = 128
MAX_LEGAL_TARGETS = 32
MAX_PROFILE_ACTIONS = 32
MAX_ATTACK_OPTIONS_PER_ACTOR = 256
MAX_MENU_OPTIONS = 512
MAX_IDENTITY_CHARS = 128
MAX_ACTION_TEXT_CHARS = 120
MAX_FEATURE_NAME_CHARS = 128
MAX_PLAN_CONTENT_CHARS = 32000
MAX_PROJECTION_CONTENT_CHARS = 32000
MAX_DIRECTIVE_CHARS = 240
MAX_ALLY_STANDING_ORDER_INTENT_CHARS = 160

ALLY_STANDING_ORDER_CONDITIONS = frozenset({
    "always",
    "self_bloodied",
    "self_near_death",
    "commander_down",
    "cover_available",
    "ally_departed",
})

LOYALTY_DEFAULT = "loyal"
ALLY_DEFAULT_REASON_CODES = frozenset({
    "INVALID_PLAN",
    "MISSING_CHOICE",
    "UNKNOWN_ACTOR",
    "DUPLICATE_ACTOR",
    "DUPLICATE_ID",
    "UNISSUED_ID",
})

_VALID_KINDS = frozenset({"enemy", "npc", "player"})
_INACTIVE_STATUSES = frozenset({
    "dead", "defeated", "departed", "fled", "surrendered", "inactive",
    "unconscious", "incapacitated", "stable",
})
_DEPARTURE_REASONS = frozenset({"departed", "fled", "surrendered"})
_OPAQUE_ID_RE = re.compile(r"^opt_[0-9a-f]{24}$")
_DAMAGE_DICE_RE = re.compile(r"^[1-9][0-9]*[dD][2-9][0-9]*$")


@dataclass(frozen=True)
class AllyAttackAction:
    """One source-backed weapon action that passed the shared legality check."""

    name: str
    attack_bonus: int
    damage_dice: str
    damage_bonus: int
    damage_type: str
    is_ranged: bool


@dataclass(frozen=True)
class AllyOption:
    """An opaque issued option and its Python-owned interpretation."""

    option_id: str
    kind: str
    actor: CombatantIdentity
    attack: Optional[AllyAttackAction] = None
    target: Optional[CombatantIdentity] = None
    feature_id: Optional[str] = None
    feature_name: Optional[str] = None
    cover_type: Optional[str] = None

    def to_projection(self) -> dict[str, Any]:
        """Return bounded labels only; attack mechanics never enter the plan."""
        result: dict[str, Any] = {
            "option_id": self.option_id,
            "kind": self.kind,
        }
        if self.kind == "attack" and self.attack is not None:
            result["action"] = self.attack.name[:MAX_ACTION_TEXT_CHARS]
            result["cover_compatible"] = self.attack.is_ranged
            if self.target is not None:
                result["target"] = self.target.name[:MAX_IDENTITY_CHARS]
        elif self.kind == "take_cover":
            result["feature_id"] = self.feature_id
            result["feature"] = (self.feature_name or self.feature_id or "")[:MAX_FEATURE_NAME_CHARS]
            result["cover_type"] = self.cover_type or ""
        return result


@dataclass(frozen=True)
class AllyActorMenu:
    """The legal options and deterministic default for one active allied NPC."""

    actor: CombatantIdentity
    attack_options: tuple[AllyOption, ...]
    cover_options: tuple[AllyOption, ...]
    default_option_id: str
    loyalty: str = LOYALTY_DEFAULT

    @property
    def options(self) -> tuple[AllyOption, ...]:
        return self.attack_options + self.cover_options


@dataclass(frozen=True)
class AllyMenus:
    """Immutable menu and legal-target snapshot for one scheduled ally batch."""

    batch_id: str
    actor_menus: tuple[AllyActorMenu, ...]
    legal_targets: tuple[CombatantIdentity, ...]

    @property
    def all_options(self) -> tuple[AllyOption, ...]:
        return tuple(option for menu in self.actor_menus for option in menu.options)


@dataclass(frozen=True)
class AllyMenuBuildFailure:
    """A bounded reason why an ally menu cannot be safely issued."""

    reason_code: str


class AllyDirectiveHistoryMetadata(TypedDict):
    """Versioned private directive data stored on its accepted-input record."""

    schema_version: Literal[1]
    actor_name: str
    directive: str


@dataclass(frozen=True)
class AllyDirectiveParseResult:
    """Python-validated result for one exact ``/cmd`` input."""

    status: str
    actor_name: Optional[str] = None
    directive: Optional[str] = None


@dataclass(frozen=True)
class ValidatedAllyChoice:
    """One accepted option or deterministic rule fallback for an ally."""

    actor: CombatantIdentity
    kind: str
    option_ids: tuple[str, ...]
    action: Optional[AllyAttackAction] = None
    target: Optional[CombatantIdentity] = None
    cover_feature_id: Optional[str] = None
    cover_type: Optional[str] = None
    default_reason: Optional[str] = None


@dataclass(frozen=True)
class ValidatedAllyPlan:
    """Validated actor choices; this value is not a mechanical application."""

    status: str
    choices: tuple[ValidatedAllyChoice, ...]
    rejected_reason_codes: tuple[str, ...]


class _DuplicatePlanKey(ValueError):
    pass


def _canonical_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _identity_key(identity: CombatantIdentity) -> tuple[str, str]:
    return identity.kind, _canonical_name(identity.name)


def _normalize_identity(value: Any) -> Optional[CombatantIdentity]:
    if isinstance(value, CombatantIdentity):
        name, kind = value.name, value.kind
    elif isinstance(value, Mapping):
        name = value.get("name", value.get("character_name"))
        kind = value.get("kind", value.get("type"))
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        first, second = value
        if isinstance(first, str) and first.strip().lower() in _VALID_KINDS | {"pc"}:
            kind, name = first, second
        else:
            name, kind = first, second
    else:
        return None

    if not isinstance(name, str) or not isinstance(kind, str):
        return None
    clean_name = " ".join(name.split())
    clean_kind = kind.strip().lower()
    if clean_kind == "pc":
        clean_kind = "player"
    if (
        not clean_name
        or len(clean_name) > MAX_IDENTITY_CHARS
        or clean_kind not in _VALID_KINDS
    ):
        return None
    return CombatantIdentity(clean_name, clean_kind)


def _encounter_index(
    encounter: Any,
) -> tuple[
    dict[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
    tuple[CombatantIdentity, ...],
    Optional[AllyMenuBuildFailure],
]:
    if not isinstance(encounter, Mapping):
        return {}, (), AllyMenuBuildFailure("malformed_encounter")
    creatures = encounter.get("creatures")
    if not isinstance(creatures, list):
        return {}, (), AllyMenuBuildFailure("malformed_encounter")
    if len(creatures) > MAX_ENCOUNTER_COMBATANTS:
        return {}, (), AllyMenuBuildFailure("menu_limit_exceeded")

    index: dict[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]] = {}
    order = []
    for creature in creatures:
        if not isinstance(creature, Mapping):
            return {}, (), AllyMenuBuildFailure("malformed_encounter")
        identity = _normalize_identity({
            "name": creature.get("name"),
            "kind": creature.get("type"),
        })
        if identity is None:
            return {}, (), AllyMenuBuildFailure("malformed_encounter")
        key = _identity_key(identity)
        if key in index:
            return {}, (), AllyMenuBuildFailure("ambiguous_identity")
        index[key] = (identity, creature)
        order.append(identity)
    return index, tuple(order), None


def _is_active(creature: Mapping[str, Any]) -> bool:
    hp = creature.get("currentHitPoints", creature.get("hitPoints"))
    status = creature.get("status", "alive")
    if (
        isinstance(hp, bool)
        or not isinstance(hp, int)
        or hp <= 0
        or not isinstance(status, str)
        or not status.strip()
        or status.strip().lower() in _INACTIVE_STATUSES
    ):
        return False
    departure = creature.get("defeatReason", creature.get("departureReason"))
    if isinstance(departure, str) and departure.strip().lower() in _DEPARTURE_REASONS:
        return False
    if creature.get("active") is False or creature.get("isActive") is False:
        return False
    return True


def _resolve_reference(
    value: Any,
    index: Mapping[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
) -> Optional[CombatantIdentity]:
    identity = _normalize_identity(value)
    if identity is not None:
        matched = index.get(_identity_key(identity))
        return matched[0] if matched is not None else None
    if isinstance(value, str):
        canonical = _canonical_name(value)
        matches = [
            item[0] for item in index.values()
            if _canonical_name(item[0].name) == canonical
        ]
        return matches[0] if len(matches) == 1 else None
    return None


def _ordered_active_identities(
    index: Mapping[tuple[str, str], tuple[CombatantIdentity, Mapping[str, Any]]],
    encounter_order: Sequence[CombatantIdentity],
    references: Optional[Sequence[Any]],
    *,
    kind: str,
    visible_enemies_only: bool = False,
) -> tuple[CombatantIdentity, ...]:
    candidates: Sequence[Any] = encounter_order if references is None else references
    result = []
    seen = set()
    for reference in candidates:
        identity = _resolve_reference(reference, index)
        if identity is None or identity.kind != kind:
            continue
        key = _identity_key(identity)
        row = index[key][1]
        if key in seen or not _is_active(row):
            continue
        if visible_enemies_only and not _is_visible_enemy(row):
            continue
        result.append(identity)
        seen.add(key)
    return tuple(result)


def _is_visible_enemy(creature: Mapping[str, Any]) -> bool:
    """Honor explicit encounter visibility facts without inventing geometry."""
    if (
        creature.get("hidden") is True
        or creature.get("isHidden") is True
        or creature.get("visible") is False
        or creature.get("isVisible") is False
        or creature.get("offScene") is True
        or creature.get("off_scene") is True
    ):
        return False
    visibility = creature.get("visibility")
    if isinstance(visibility, str) and visibility.strip().lower() in {
        "hidden", "off_scene", "off-scene", "offscreen", "off_screen",
    }:
        return False
    conditions = creature.get("conditions", [])
    if isinstance(conditions, str):
        conditions = [conditions]
    if isinstance(conditions, Sequence) and not isinstance(conditions, (str, bytes)):
        if any(
            isinstance(condition, str) and condition.strip().lower() == "hidden"
            for condition in conditions
        ):
            return False
    return True


def select_active_allies(
    encounter: Any,
    scheduled_allies: Optional[Sequence[Any]] = None,
) -> tuple[CombatantIdentity, ...]:
    """Select only active encounter NPCs, preserving encounter/schedule order.

    Untyped names resolve only when unique across the encounter. Invalid,
    inactive, non-NPC, and ambiguous references are omitted; caller-supplied
    references can never introduce actors that are absent from the encounter.
    """
    index, encounter_order, failure = _encounter_index(encounter)
    if failure is not None:
        return ()
    if scheduled_allies is not None and (
        not isinstance(scheduled_allies, Sequence)
        or isinstance(scheduled_allies, (str, bytes))
    ):
        return ()
    return _ordered_active_identities(
        index,
        encounter_order,
        scheduled_allies,
        kind="npc",
    )


def _opaque_option_id(
    batch_id: str,
    actor: CombatantIdentity,
    kind: str,
    *,
    action_name: Optional[str] = None,
    target: Optional[CombatantIdentity] = None,
    feature_id: Optional[str] = None,
) -> str:
    payload = {
        "batch": batch_id,
        "actor": [actor.kind, _canonical_name(actor.name)],
        "kind": kind,
        "action": action_name,
        "target": (
            [target.kind, _canonical_name(target.name)] if target is not None else None
        ),
        "feature": feature_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "opt_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _matching_npc_profile(
    actor: CombatantIdentity,
    npc_profiles: Optional[Mapping[str, Any]],
) -> tuple[Optional[Any], Optional[AllyMenuBuildFailure]]:
    if npc_profiles is None:
        return None, None
    if not isinstance(npc_profiles, Mapping) or len(npc_profiles) > MAX_ENCOUNTER_COMBATANTS:
        return None, AllyMenuBuildFailure("malformed_npc_profiles")

    actor_name = _canonical_name(actor.name)
    matches = []
    for key, profile in npc_profiles.items():
        key_matches = isinstance(key, str) and _canonical_name(key) == actor_name
        profile_name = profile.get("name") if isinstance(profile, Mapping) else None
        value_matches = isinstance(profile_name, str) and _canonical_name(profile_name) == actor_name
        if key_matches or value_matches:
            if key_matches and isinstance(profile_name, str) and not value_matches:
                return None, AllyMenuBuildFailure("npc_profile_identity_mismatch")
            matches.append(profile)
    if len(matches) > 1:
        return None, AllyMenuBuildFailure("ambiguous_npc_profile")
    return (matches[0], None) if matches else (None, None)


def _attack_rows(
    actor: CombatantIdentity,
    creature: Mapping[str, Any],
    npc_profiles: Optional[Mapping[str, Any]],
) -> tuple[tuple[AllyAttackAction, ...], Optional[AllyMenuBuildFailure]]:
    profile, failure = _matching_npc_profile(actor, npc_profiles)
    if failure is not None:
        return (), failure
    if profile is None:
        actions = creature.get("attacksAndSpellcasting", creature.get("attacks"))
    elif isinstance(profile, list):
        actions = profile
    elif isinstance(profile, Mapping):
        if "attacksAndSpellcasting" in profile:
            actions = profile.get("attacksAndSpellcasting")
        else:
            actions = profile.get("attacks")
    else:
        return (), AllyMenuBuildFailure("malformed_npc_profile")

    if not isinstance(actions, list):
        return (), AllyMenuBuildFailure("missing_attack_data")
    if len(actions) > MAX_PROFILE_ACTIONS:
        return (), AllyMenuBuildFailure("menu_limit_exceeded")

    result = []
    seen_names = set()
    for action in actions:
        if not isinstance(action, Mapping) or not _is_attack_candidate(action):
            continue
        if _action_decline_code(action) is not None:
            continue
        try:
            name, attack_bonus, damage_bonus, _dice_count, damage_type, _sides, _ = (
                _validated_attack(action)
            )
        except _Decline:
            continue
        if (
            len(name) > MAX_ACTION_TEXT_CHARS
            or not all(character.isprintable() for character in name)
            or len(damage_type) > 40
            or not all(character.isprintable() for character in damage_type)
        ):
            continue
        canonical_action = _canonical_name(name)
        if canonical_action in seen_names:
            return (), AllyMenuBuildFailure("ambiguous_attack_name")
        seen_names.add(canonical_action)
        damage_dice = action.get("damageDice")
        if not isinstance(damage_dice, str) or not _DAMAGE_DICE_RE.fullmatch(damage_dice.strip()):
            continue
        result.append(AllyAttackAction(
            name=name,
            attack_bonus=attack_bonus,
            damage_dice=damage_dice.strip(),
            damage_bonus=damage_bonus,
            damage_type=damage_type,
            is_ranged=is_authorized_ranged_action(name, action),
        ))
        if len(result) > MAX_ATTACK_OPTIONS_PER_ACTOR:
            return (), AllyMenuBuildFailure("menu_limit_exceeded")
    if not result:
        return (), AllyMenuBuildFailure("no_legal_attack")
    return tuple(result), None


def _feature_rows(features: Any) -> tuple[Mapping[str, Any], ...]:
    if (
        not isinstance(features, list)
        or len(features) > 32
        or validate_tactical_features(features)
    ):
        return ()
    required = {"featureId", "name", "kind", "coverType", "usableBy"}
    result = []
    for feature in features:
        if not isinstance(feature, Mapping) or set(feature) != required:
            continue
        feature_id = feature.get("featureId")
        name = feature.get("name")
        usable_by = feature.get("usableBy")
        if (
            not isinstance(feature_id, str)
            or not feature_id.strip()
            or len(feature_id) > MAX_IDENTITY_CHARS
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > MAX_FEATURE_NAME_CHARS
            or not all(character.isprintable() for character in name)
            or feature.get("kind") != "cover"
            or feature.get("coverType") not in {"half", "three_quarters"}
            or not isinstance(usable_by, list)
            or not usable_by
            or any(item not in _VALID_KINDS for item in usable_by)
            or "npc" not in usable_by
        ):
            continue
        result.append(feature)
    return tuple(result)


def build_ally_menus(
    encounter: Any,
    batch_id: str,
    *,
    npc_profiles: Optional[Mapping[str, Any]] = None,
    scheduled_allies: Optional[Sequence[Any]] = None,
    turn_order: Optional[Sequence[Any]] = None,
    legal_targets: Optional[Sequence[Any]] = None,
    tactical_features: Any = None,
) -> Union[AllyMenus, AllyMenuBuildFailure]:
    """Build bounded attack/cover menus from current encounter facts.

    NPC attack profiles are keyed by actor name (or carry a matching ``name``)
    and provide the repository's canonical ``attacksAndSpellcasting`` records.
    When no profile is supplied for an actor, equivalent records already in
    the encounter's ``attacksAndSpellcasting`` or ``attacks`` field are used.
    Position, range, movement, and protection are not inferred.
    """
    if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 128:
        return AllyMenuBuildFailure("invalid_batch_identity")
    if turn_order is not None and (
        not isinstance(turn_order, Sequence) or isinstance(turn_order, (str, bytes))
    ):
        return AllyMenuBuildFailure("malformed_turn_order")
    if scheduled_allies is not None and (
        not isinstance(scheduled_allies, Sequence)
        or isinstance(scheduled_allies, (str, bytes))
    ):
        return AllyMenuBuildFailure("malformed_ally_window")
    if legal_targets is not None and (
        not isinstance(legal_targets, Sequence)
        or isinstance(legal_targets, (str, bytes))
    ):
        return AllyMenuBuildFailure("malformed_legal_targets")

    index, encounter_order, failure = _encounter_index(encounter)
    if failure is not None:
        return failure
    actor_references = scheduled_allies if scheduled_allies is not None else turn_order
    actors = _ordered_active_identities(
        index, encounter_order, actor_references, kind="npc"
    )
    if len(actors) > MAX_ALLY_ACTORS:
        return AllyMenuBuildFailure("menu_limit_exceeded")

    target_references = turn_order if turn_order is not None else encounter_order
    targets = _ordered_active_identities(
        index,
        encounter_order,
        target_references,
        kind="enemy",
        visible_enemies_only=True,
    )
    if legal_targets is not None:
        requested = {
            _identity_key(identity)
            for reference in legal_targets
            if (identity := _resolve_reference(reference, index)) is not None
            and identity.kind == "enemy"
        }
        targets = tuple(target for target in targets if _identity_key(target) in requested)
    if len(targets) > MAX_LEGAL_TARGETS:
        return AllyMenuBuildFailure("menu_limit_exceeded")
    if actors and not targets:
        return AllyMenuBuildFailure("no_legal_target")

    features = _feature_rows(tactical_features)
    actor_menus = []
    all_ids = set()
    option_count = 0
    for actor in actors:
        actor_row = index[_identity_key(actor)][1]
        attacks, failure = _attack_rows(actor, actor_row, npc_profiles)
        if failure is not None:
            return failure

        attack_options = []
        for attack in attacks:
            for target in targets:
                option_id = _opaque_option_id(
                    batch_id,
                    actor,
                    "attack",
                    action_name=attack.name,
                    target=target,
                )
                attack_options.append(AllyOption(
                    option_id=option_id,
                    kind="attack",
                    actor=actor,
                    attack=attack,
                    target=target,
                ))
        if len(attack_options) > MAX_ATTACK_OPTIONS_PER_ACTOR:
            return AllyMenuBuildFailure("menu_limit_exceeded")

        cover_options = []
        for feature in features:
            option_id = _opaque_option_id(
                batch_id,
                actor,
                "take_cover",
                feature_id=feature["featureId"],
            )
            cover_options.append(AllyOption(
                option_id=option_id,
                kind="take_cover",
                actor=actor,
                feature_id=feature["featureId"],
                feature_name=feature["name"],
                cover_type=feature["coverType"],
            ))

        if not attack_options:
            return AllyMenuBuildFailure("no_legal_attack")
        option_count += len(attack_options) + len(cover_options)
        if option_count > MAX_MENU_OPTIONS:
            return AllyMenuBuildFailure("menu_limit_exceeded")
        for option in tuple(attack_options) + tuple(cover_options):
            if option.option_id in all_ids:
                return AllyMenuBuildFailure("malformed_tactical_data")
            all_ids.add(option.option_id)
        actor_menus.append(AllyActorMenu(
            actor=actor,
            attack_options=tuple(attack_options),
            cover_options=tuple(cover_options),
            default_option_id=attack_options[0].option_id,
        ))

    return AllyMenus(
        batch_id=batch_id.strip(),
        actor_menus=tuple(actor_menus),
        legal_targets=tuple(targets),
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicatePlanKey("duplicate JSON key")
        result[key] = value
    return result


def _parse_plan(plan: Any) -> Optional[Mapping[str, Any]]:
    try:
        if isinstance(plan, str):
            if len(plan) > MAX_PLAN_CONTENT_CHARS:
                return None
            return json.loads(
                plan,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        encoded = json.dumps(
            plan, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        )
        if len(encoded) > MAX_PLAN_CONTENT_CHARS:
            return None
        parsed = json.loads(encoded, object_pairs_hook=_reject_duplicate_json_keys)
        return parsed if isinstance(parsed, Mapping) else None
    except (TypeError, ValueError, OverflowError, json.JSONDecodeError):
        return None


def _default_choice(
    menu: AllyActorMenu,
    reason_code: str,
) -> ValidatedAllyChoice:
    option = next(
        item for item in menu.attack_options
        if item.option_id == menu.default_option_id
    )
    return ValidatedAllyChoice(
        actor=menu.actor,
        kind="attack",
        option_ids=(option.option_id,),
        action=option.attack,
        target=option.target,
        default_reason=reason_code,
    )


def rule_default_ally_plan(
    menus: AllyMenus,
    reason_code: str = "MISSING_CHOICE",
) -> ValidatedAllyPlan:
    """Return the first authored legal attack per actor with a bounded reason."""
    if not isinstance(menus, AllyMenus):
        raise TypeError("menus must be an AllyMenus snapshot")
    if reason_code not in ALLY_DEFAULT_REASON_CODES:
        reason_code = "INVALID_PLAN"
    choices = tuple(_default_choice(menu, reason_code) for menu in menus.actor_menus)
    return ValidatedAllyPlan(
        status="defaulted" if choices else "accepted",
        choices=choices,
        rejected_reason_codes=(reason_code,) if choices else (),
    )


def _choice_from_options(
    actor: CombatantIdentity,
    option_ids: Any,
    menu: AllyActorMenu,
) -> tuple[Optional[ValidatedAllyChoice], str]:
    if not isinstance(option_ids, list) or not option_ids or len(option_ids) > 2:
        return None, "INVALID_PLAN"
    if any(not isinstance(option_id, str) or not _OPAQUE_ID_RE.fullmatch(option_id) for option_id in option_ids):
        return None, "INVALID_PLAN"
    if len(set(option_ids)) != len(option_ids):
        return None, "DUPLICATE_ID"

    by_id = {option.option_id: option for option in menu.options}
    selected = [by_id.get(option_id) for option_id in option_ids]
    if any(option is None for option in selected):
        return None, "UNISSUED_ID"
    typed_options = [option for option in selected if option is not None]
    attack_options = [option for option in typed_options if option.kind == "attack"]
    cover_options = [option for option in typed_options if option.kind == "take_cover"]

    if len(typed_options) == 1 and len(attack_options) == 1:
        option = attack_options[0]
        return ValidatedAllyChoice(
            actor=actor,
            kind="attack",
            option_ids=(option.option_id,),
            action=option.attack,
            target=option.target,
        ), ""
    if len(typed_options) == 1 and len(cover_options) == 1:
        option = cover_options[0]
        return ValidatedAllyChoice(
            actor=actor,
            kind="take_cover",
            option_ids=(option.option_id,),
            cover_feature_id=option.feature_id,
            cover_type=option.cover_type,
        ), ""
    if len(typed_options) == 2 and len(attack_options) == 1 and len(cover_options) == 1:
        attack = attack_options[0]
        cover = cover_options[0]
        if attack.attack is None or attack.attack.is_ranged is not True:
            return None, "INVALID_PLAN"
        return ValidatedAllyChoice(
            actor=actor,
            kind="attack",
            option_ids=(attack.option_id, cover.option_id),
            action=attack.attack,
            target=attack.target,
            cover_feature_id=cover.feature_id,
            cover_type=cover.cover_type,
        ), ""
    return None, "INVALID_PLAN"


def validate_ally_plan(plan: Any, menus: AllyMenus) -> ValidatedAllyPlan:
    """Accept only current issued option IDs; default every affected ally."""
    if not isinstance(menus, AllyMenus):
        raise TypeError("menus must be an AllyMenus snapshot")
    parsed = _parse_plan(plan)
    whole_plan_invalid = (
        not isinstance(parsed, Mapping)
        or set(parsed) != {"choices"}
    )
    if whole_plan_invalid:
        parsed = {}

    raw_choices = parsed.get("choices", [])
    if not isinstance(raw_choices, list) or len(raw_choices) > MAX_ALLY_ACTORS:
        whole_plan_invalid = True
        raw_choices = []

    actor_menus = {_identity_key(menu.actor): menu for menu in menus.actor_menus}
    rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    duplicate_actors = set()
    reasons = []
    for row in raw_choices:
        if not isinstance(row, Mapping) or set(row) != {"actor", "option_ids"}:
            reasons.append("INVALID_PLAN")
            continue
        raw_actor = row.get("actor")
        if not isinstance(raw_actor, str):
            reasons.append("UNKNOWN_ACTOR")
            continue
        key = ("npc", _canonical_name(raw_actor))
        if key not in actor_menus:
            reasons.append("UNKNOWN_ACTOR")
            continue
        if key in rows:
            duplicate_actors.add(key)
            continue
        rows[key] = row

    choices = []
    actor_reasons = []
    for menu in menus.actor_menus:
        key = _identity_key(menu.actor)
        if whole_plan_invalid:
            reason = "INVALID_PLAN"
            choice = None
        elif key in duplicate_actors:
            reason = "DUPLICATE_ACTOR"
            choice = None
        elif key not in rows:
            reason = "MISSING_CHOICE"
            choice = None
        else:
            row = rows[key]
            if set(row) != {"actor", "option_ids"}:
                reason = "INVALID_PLAN"
                choice = None
            else:
                choice, reason = _choice_from_options(
                    menu.actor, row.get("option_ids"), menu
                )
        if choice is None:
            choices.append(_default_choice(menu, reason))
            actor_reasons.append(reason)
        else:
            choices.append(choice)

    for reason in actor_reasons + reasons:
        if reason not in ALLY_DEFAULT_REASON_CODES:
            # Structural row errors are bounded to the existing generic code.
            reason = "INVALID_PLAN"
        if reason not in reasons:
            reasons.append(reason)
    defaulted = sum(choice.default_reason is not None for choice in choices)
    if choices and defaulted == len(choices):
        status = "rejected_all"
    elif defaulted or reasons:
        status = "partially_defaulted"
    else:
        status = "accepted"
    return ValidatedAllyPlan(
        status=status,
        choices=tuple(choices),
        rejected_reason_codes=tuple(reasons),
    )


def _bounded_directive(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(
        "".join(
            character
            if character.isprintable()
            else " " if character.isspace() else ""
            for character in value
        ).split()
    )
    if not cleaned or len(cleaned) > MAX_DIRECTIVE_CHARS:
        return None
    return cleaned


def parse_ally_directive_command(
    command_text: Any,
    encounter: Any,
) -> AllyDirectiveParseResult:
    """Parse an exact ``/cmd`` token and resolve the longest active NPC prefix."""
    if not isinstance(command_text, str):
        return AllyDirectiveParseResult("not_command")
    raw_parts = command_text.strip().split(None, 1)
    if not raw_parts or raw_parts[0].casefold() != "/cmd":
        return AllyDirectiveParseResult("not_command")
    if len(command_text) > 4096:
        return AllyDirectiveParseResult("directive_too_long")

    cleaned_command = " ".join(
        "".join(
            character
            if character.isprintable()
            else " " if character.isspace() else ""
            for character in command_text
        ).split()
    )
    parts = cleaned_command.split(" ", 1)
    if len(parts) != 2 or parts[0].casefold() != "/cmd":
        return AllyDirectiveParseResult("invalid_syntax")

    argument_tokens = parts[1].split()
    active_allies = select_active_allies(encounter)
    matches: list[tuple[int, int, CombatantIdentity, int]] = []
    for ally in active_allies:
        name_tokens = ally.name.split()
        if len(argument_tokens) < len(name_tokens):
            continue
        if all(
            argument_tokens[index].casefold() == name_token.casefold()
            for index, name_token in enumerate(name_tokens)
        ):
            matches.append((len(name_tokens), len(ally.name), ally, len(name_tokens)))

    if not matches:
        return AllyDirectiveParseResult("unknown_ally")
    _token_count, _name_length, actor, consumed_tokens = max(
        matches, key=lambda item: (item[0], item[1])
    )
    directive_text = " ".join(argument_tokens[consumed_tokens:])
    if not directive_text:
        return AllyDirectiveParseResult("empty_directive", actor_name=actor.name)
    directive = _bounded_directive(directive_text)
    if directive is None:
        return AllyDirectiveParseResult("directive_too_long", actor_name=actor.name)
    return AllyDirectiveParseResult(
        "accepted",
        actor_name=actor.name,
        directive=directive,
    )


def build_ally_directive_history_record(
    actor_name: Any,
    directive: Any,
) -> dict[str, Any]:
    """Build a private, typed accepted-input record without retaining raw input."""
    actor = _normalize_identity({"name": actor_name, "kind": "npc"})
    cleaned_directive = _bounded_directive(directive)
    if actor is None or actor.kind != "npc" or cleaned_directive is None:
        raise ValueError("invalid_ally_directive")
    metadata: AllyDirectiveHistoryMetadata = {
        "schema_version": 1,
        "actor_name": actor.name,
        "directive": cleaned_directive,
    }
    record = build_accepted_input_record("")
    record[COMBAT_ALLY_DIRECTIVE_HISTORY_KEY] = metadata
    return record


def latest_ally_directives_from_history(
    history: Any,
    *,
    active_allies: Optional[Sequence[Any]] = None,
) -> dict[str, str]:
    """Coalesce valid private directives to the latest pending value per ally."""
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        return {}

    allowed_names: Optional[set[str]] = None
    if active_allies is not None:
        if not isinstance(active_allies, Sequence) or isinstance(active_allies, (str, bytes)):
            return {}
        allowed_names = set()
        for reference in active_allies:
            identity = _normalize_identity(reference)
            if identity is not None and identity.kind == "npc":
                allowed_names.add(_canonical_name(identity.name))
            elif isinstance(reference, str):
                canonical = _canonical_name(reference)
                if canonical:
                    allowed_names.add(canonical)

    latest: dict[str, tuple[str, Optional[str], bool]] = {}
    allowed_fields = {
        "schema_version",
        "actor_name",
        "directive",
        "consumed_by_applied_id",
    }
    for message in history:
        if not isinstance(message, Mapping):
            continue
        if (
            message.get("role") != "user"
            or not isinstance(message.get("turn_id"), str)
            or not message.get("turn_id")
        ):
            continue
        metadata = message.get(COMBAT_ALLY_DIRECTIVE_HISTORY_KEY)
        if not isinstance(metadata, Mapping):
            continue
        actor = _normalize_identity({"name": metadata.get("actor_name"), "kind": "npc"})
        if actor is None or actor.kind != "npc":
            continue
        actor_key = _canonical_name(actor.name)
        if allowed_names is not None and actor_key not in allowed_names:
            continue
        if (
            set(metadata) - allowed_fields
            or type(metadata.get("schema_version")) is not int
            or metadata.get("schema_version") != 1
        ):
            latest[actor_key] = (actor.name, None, True)
            continue
        directive = _bounded_directive(metadata.get("directive"))
        consumed = metadata.get("consumed_by_applied_id") not in (None, "")
        latest[actor_key] = (actor.name, directive, consumed)

    return {
        actor_name: directive
        for actor_name, directive, consumed in latest.values()
        if directive is not None and not consumed
    }


def mark_ally_directives_consumed(
    history: Any,
    active_allies: Sequence[Any],
    applied_id: Any,
) -> list[Any]:
    """Mark each latest pending directive for this batch in a history copy."""
    if (
        not isinstance(history, Sequence)
        or isinstance(history, (str, bytes))
        or not isinstance(active_allies, Sequence)
        or isinstance(active_allies, (str, bytes))
        or not isinstance(applied_id, str)
        or not applied_id
    ):
        raise ValueError("invalid_ally_directive_consumption")

    allowed_names = set()
    for reference in active_allies:
        identity = _normalize_identity(reference)
        if identity is not None and identity.kind == "npc":
            allowed_names.add(_canonical_name(identity.name))
        elif isinstance(reference, str):
            canonical = _canonical_name(reference)
            if canonical:
                allowed_names.add(canonical)

    copied = copy.deepcopy(list(history))
    latest_indexes: dict[str, int] = {}
    for index, message in enumerate(copied):
        if not isinstance(message, Mapping):
            continue
        metadata = message.get(COMBAT_ALLY_DIRECTIVE_HISTORY_KEY)
        if not isinstance(metadata, Mapping):
            continue
        if (
            set(metadata) - {
                "schema_version",
                "actor_name",
                "directive",
                "consumed_by_applied_id",
            }
            or type(metadata.get("schema_version")) is not int
            or metadata.get("schema_version") != 1
        ):
            continue
        actor = _normalize_identity({"name": metadata.get("actor_name"), "kind": "npc"})
        directive = _bounded_directive(metadata.get("directive"))
        if (
            message.get("role") != "user"
            or not isinstance(message.get("turn_id"), str)
            or not message.get("turn_id")
            or actor is None
            or directive is None
            or _canonical_name(actor.name) not in allowed_names
        ):
            continue
        latest_indexes[_canonical_name(actor.name)] = index

    for index in latest_indexes.values():
        message = copied[index]
        metadata = dict(message[COMBAT_ALLY_DIRECTIVE_HISTORY_KEY])
        if metadata.get("consumed_by_applied_id") in (None, ""):
            metadata["consumed_by_applied_id"] = applied_id
            message[COMBAT_ALLY_DIRECTIVE_HISTORY_KEY] = metadata
    return copied


_ALLY_PLAN_SYSTEM_PROMPT = (
    "Choose one legal option for each scheduled allied NPC from the supplied "
    "Python-built menu. Return exactly one JSON object with a choices array; "
    "each choice has actor (the exact NPC name) and option_ids (one issued ID, "
    "or one attack ID plus one compatible issued take_cover ID). Use only IDs "
    "shown for that actor. Directives are guidance, not commands. Do not invent "
    "actions, targets, mechanics, movement, protection, flight, or surrender. "
    "Return JSON only."
)


def build_ally_plan_messages(
    menus: AllyMenus,
    history: Any,
) -> list[dict[str, str]]:
    """Build the single synchronous ally-plan request from scoped legal facts."""
    if not isinstance(menus, AllyMenus):
        raise TypeError("menus must be an AllyMenus snapshot")
    projection = build_ally_perception_projection_from_history(menus, history)
    user_content = json.dumps(
        projection,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(user_content) > MAX_PROJECTION_CONTENT_CHARS:
        raise ValueError("ally_plan_payload_too_large")
    return [
        {"role": "system", "content": _ALLY_PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_ally_perception_projection(
    menus: AllyMenus,
    *,
    directives: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Project only scheduled allies, their issued options, and legal targets.

    The projection is constructed from the immutable menu rather than copying
    encounter/profile payloads. Hidden facts, enemy-private plans, inactive and
    off-scene roster entries, character resources, and unrelated prompts thus
    have no pass-through path.
    """
    if not isinstance(menus, AllyMenus):
        raise TypeError("menus must be an AllyMenus snapshot")

    directive_index: dict[str, Any] = {}
    ambiguous_directives = set()
    if isinstance(directives, Mapping):
        for name, text in directives.items():
            if not isinstance(name, str):
                continue
            key = _canonical_name(name)
            if key in directive_index:
                ambiguous_directives.add(key)
            directive_index[key] = text

    ally_rows = []
    for menu in menus.actor_menus:
        row: dict[str, Any] = {
            "actor": menu.actor.name,
            "loyalty": LOYALTY_DEFAULT,
            "options": [option.to_projection() for option in menu.options],
        }
        key = _canonical_name(menu.actor.name)
        if key not in ambiguous_directives:
            directive = _bounded_directive(directive_index.get(key))
            if directive is not None:
                row["directive"] = directive
        ally_rows.append(row)

    projection = {
        "batch_id": menus.batch_id,
        "scheduled_allies": ally_rows,
        "visible_enemies": [{"name": target.name} for target in menus.legal_targets],
    }
    encoded = json.dumps(
        projection,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(encoded) > MAX_PROJECTION_CONTENT_CHARS:
        raise ValueError("ally_projection_too_large")
    return projection


def build_ally_perception_projection_from_history(
    menus: AllyMenus,
    history: Any,
) -> dict[str, Any]:
    """Coalesce durable directives and expose each only to its named actor."""
    if not isinstance(menus, AllyMenus):
        raise TypeError("menus must be an AllyMenus snapshot")
    directives = latest_ally_directives_from_history(
        history,
        active_allies=tuple(menu.actor for menu in menus.actor_menus),
    )
    return build_ally_perception_projection(menus, directives=directives)


_ALLY_STANDING_ORDERS_SYSTEM_PROMPT = (
    "You are proposing bounded conditional standing orders for one upcoming "
    "ally batch. Python evaluates conditions against authoritative state at the "
    "DM-owned /end boundary and compiles only choices legal in the current "
    "Python-built menus. Return exactly one closed JSON object: top-level "
    "keys are actors (required array) and optional intent (string, at most "
    "160 characters); no other keys are allowed. Each actor row has exactly "
    "actor and clauses. actor has exactly name (string) and kind (the string "
    "npc). clauses is an array of up to four objects, each with exactly when "
    "and do. do must be an object. For an attack, do has exactly kind:"
    "attack, target, and optional action; target has exactly name (string) "
    "and kind (the string enemy). For cover, do has exactly kind:take_cover "
    "and optional feature_id (string). No additional fields are allowed at "
    "any level. Generic shape example: {\"actors\":[{\"actor\":{\"name\":\"<ally>\",\"kind\":\"npc\"},\"clauses\":[{\"when\":\"always\",\"do\":{\"kind\":\"attack\",\"target\":{\"name\":\"<enemy>\",\"kind\":\"enemy\"}}}]}],\"intent\":\"<brief intent>\"}. "
    "Each actor has actor {name, kind:'npc'} and up to four ordered clauses. "
    "A clause has when equal to always, self_bloodied, self_near_death, "
    "commander_down, cover_available, or ally_departed. Its do value is either "
    "attack with an enemy target identity and optional exact action name, or "
    "take_cover with an optional feature_id. Use only actors, targets, actions, "
    "and features shown in the user menu. Do not propose Dodge, movement, "
    "protection placeholders, flight, surrender, or other mechanics. Clause "
    "order matters: Python skips conditions that do not hold or actions that "
    "are not legal now, then uses the deterministic rule default. Do not emit "
    "option IDs or free-form actions. Optional intent is at most 160 characters "
    "and is not mechanical. Return JSON only, with no markdown or code fences."
)


def build_ally_standing_orders_messages(
    menus: AllyMenus,
    history: Any,
) -> list[dict[str, str]]:
    """Build an immutable bounded conditional-order projection for active allies."""
    if not isinstance(menus, AllyMenus):
        raise TypeError("menus must be an AllyMenus snapshot")
    projection = build_ally_perception_projection_from_history(menus, history)
    user_content = json.dumps(
        projection,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(user_content) > MAX_PROJECTION_CONTENT_CHARS:
        raise ValueError("ally_standing_orders_payload_too_large")
    return [
        {"role": "system", "content": _ALLY_STANDING_ORDERS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


ALLY_STANDING_ORDER_PARSE_FAILURE_CODES = frozenset({
    "unparseable_response",
    "top_level_not_object",
    "top_level_shape",
    "intent_invalid",
    "actors_invalid",
    "actor_row_shape",
    "actor_identity_invalid",
    "actor_kind_invalid",
    "duplicate_actor",
    "clauses_invalid",
    "clause_shape",
    "condition_invalid",
    "action_shape",
    "attack_shape",
    "attack_target_invalid",
    "attack_action_invalid",
    "cover_shape",
    "cover_feature_invalid",
    "unsupported_action",
})


def parse_ally_standing_orders_response_with_reason(
    response: Any,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Validate ally orders and return only an allowlisted rejection reason."""
    parsed = _parse_plan(response)
    if parsed is None:
        return None, "unparseable_response"
    if not isinstance(parsed, Mapping):
        return None, "top_level_not_object"
    if set(parsed) not in ({"actors"}, {"actors", "intent"}):
        return None, "top_level_shape"
    actors = parsed.get("actors")
    if not isinstance(actors, list) or len(actors) > MAX_ALLY_ACTORS:
        return None, "actors_invalid"
    if "intent" in parsed:
        intent = parsed.get("intent")
        if (
            not isinstance(intent, str)
            or len(intent) > MAX_ALLY_STANDING_ORDER_INTENT_CHARS
            or any(not character.isprintable() for character in intent)
        ):
            return None, "intent_invalid"

    seen_actors: set[str] = set()
    for row in actors:
        if not isinstance(row, Mapping) or set(row) != {"actor", "clauses"}:
            return None, "actor_row_shape"
        actor = row.get("actor")
        if (
            not isinstance(actor, Mapping)
            or set(actor) != {"name", "kind"}
            or not isinstance(actor.get("name"), str)
            or not actor["name"].strip()
            or len(actor["name"]) > MAX_IDENTITY_CHARS
            or any(not character.isprintable() for character in actor["name"])
        ):
            return None, "actor_identity_invalid"
        if actor.get("kind") != "npc":
            return None, "actor_kind_invalid"
        actor_key = _canonical_name(actor["name"])
        if actor_key in seen_actors:
            return None, "duplicate_actor"
        seen_actors.add(actor_key)

        clauses = row.get("clauses")
        if not isinstance(clauses, list) or len(clauses) > 4:
            return None, "clauses_invalid"
        for clause in clauses:
            if (
                not isinstance(clause, Mapping)
                or set(clause) != {"when", "do"}
            ):
                return None, "clause_shape"
            if clause.get("when") not in ALLY_STANDING_ORDER_CONDITIONS:
                return None, "condition_invalid"
            action = clause.get("do")
            if not isinstance(action, Mapping):
                return None, "action_shape"
            kind = action.get("kind")
            if kind == "attack":
                if set(action) not in ({"kind", "target"}, {"kind", "target", "action"}):
                    return None, "attack_shape"
                target = action.get("target")
                identity = _normalize_identity(target)
                if (
                    not isinstance(target, Mapping)
                    or set(target) != {"name", "kind"}
                    or identity is None
                    or identity.kind != "enemy"
                    or not all(character.isprintable() for character in identity.name)
                ):
                    return None, "attack_target_invalid"
                if "action" in action and (
                    not isinstance(action["action"], str)
                    or not action["action"].strip()
                    or len(action["action"]) > MAX_ACTION_TEXT_CHARS
                    or any(not character.isprintable() for character in action["action"])
                ):
                    return None, "attack_action_invalid"
            elif kind == "take_cover":
                if set(action) not in ({"kind"}, {"kind", "feature_id"}):
                    return None, "cover_shape"
                if "feature_id" in action and (
                    not isinstance(action["feature_id"], str)
                    or not action["feature_id"].strip()
                    or len(action["feature_id"]) > MAX_IDENTITY_CHARS
                    or any(not character.isprintable() for character in action["feature_id"])
                ):
                    return None, "cover_feature_invalid"
            else:
                return None, "unsupported_action"
    return dict(parsed), None


def parse_ally_standing_orders_response(response: Any) -> Optional[dict[str, Any]]:
    """Validate a closed ally-only subset of conditional tactical orders."""
    parsed, _rejection_reason = parse_ally_standing_orders_response_with_reason(response)
    return parsed


def _ally_standing_order_condition_holds(
    condition: str,
    actor: CombatantIdentity,
    menu: AllyActorMenu,
    encounter: Mapping[str, Any],
    *,
    ally_departed: bool,
) -> bool:
    if condition == "always":
        return True
    if condition == "cover_available":
        return bool(menu.cover_options)
    if condition == "ally_departed":
        return ally_departed
    if condition == "commander_down":
        creatures = encounter.get("creatures")
        if not isinstance(creatures, list):
            return False
        commanders = [
            row for row in creatures
            if isinstance(row, Mapping)
            and row.get("type") == "enemy"
            and row.get("leader") is True
            and row.get("tactics", "rule") == "commander"
        ]
        return len(commanders) == 1 and not _is_active(commanders[0])

    index, _order, failure = _encounter_index(encounter)
    if failure is not None:
        return False
    actor_row = index.get(_identity_key(actor))
    if actor_row is None or not _is_active(actor_row[1]):
        return False
    hit_points = actor_row[1].get("currentHitPoints", actor_row[1].get("hitPoints"))
    max_hit_points = actor_row[1].get("maxHitPoints")
    if (
        isinstance(hit_points, bool)
        or not isinstance(hit_points, int)
        or isinstance(max_hit_points, bool)
        or not isinstance(max_hit_points, int)
        or hit_points <= 0
        or max_hit_points <= 0
    ):
        return False
    if condition == "self_bloodied":
        return hit_points * 2 <= max_hit_points
    if condition == "self_near_death":
        return hit_points * 4 <= max_hit_points
    return False


def _ally_standing_order_option_id(
    action: Mapping[str, Any], menu: AllyActorMenu
) -> Optional[str]:
    kind = action.get("kind")
    if kind == "attack":
        target = _normalize_identity(action.get("target"))
        if target is None or target.kind != "enemy":
            return None
        action_name = action.get("action")
        normalized_action = (
            _canonical_name(action_name) if isinstance(action_name, str) else None
        )
        matches = [
            option for option in menu.attack_options
            if option.target is not None
            and _identity_key(option.target) == _identity_key(target)
            and (
                normalized_action is None
                or (
                    option.attack is not None
                    and _canonical_name(option.attack.name) == normalized_action
                )
            )
        ]
        if not matches:
            return None
        return matches[0].option_id
    if kind == "take_cover":
        feature_id = action.get("feature_id")
        options = [
            option for option in menu.cover_options
            if feature_id is None or option.feature_id == feature_id
        ]
        return options[0].option_id if options else None
    return None


def compile_ally_standing_orders(
    standing_orders: Any,
    menus: AllyMenus,
    encounter: Any,
    *,
    ally_departed: bool = False,
) -> Optional[dict[str, Any]]:
    """Compile the first currently legal ally clause to current opaque option IDs."""
    orders = parse_ally_standing_orders_response(standing_orders)
    if orders is None or not isinstance(menus, AllyMenus) or not isinstance(encounter, Mapping):
        return None
    source_rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in orders["actors"]:
        actor = _normalize_identity(row["actor"])
        if actor is not None:
            source_rows[_identity_key(actor)] = row

    choices = []
    for menu in menus.actor_menus:
        row = source_rows.get(_identity_key(menu.actor))
        if row is None:
            continue
        for clause in row["clauses"]:
            if not _ally_standing_order_condition_holds(
                clause["when"], menu.actor, menu, encounter,
                ally_departed=ally_departed,
            ):
                continue
            option_id = _ally_standing_order_option_id(clause["do"], menu)
            if option_id is None:
                continue
            choices.append({"actor": menu.actor.name, "option_ids": [option_id]})
            break
    return {"choices": choices}
