# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Pure, provider-free commander menus, plan validation, and perception.

This module does not apply combat state or call a model. The enemy resolver
owns batch eligibility and default attacks; this module only issues bounded
opaque options and validates a candidate against that immutable snapshot.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Union

from core.combat.enemy_resolution import (
    DECLINE_REASON_CODES,
    CombatantIdentity,
    EnemyResolutionDecline,
    EnemyResolutionLedger,
    get_legal_enemy_batch_targets,
    plan_enemy_batch,
)
from core.combat.tactical_contracts import validate_tactical_features


MAX_MENU_ACTORS = 32
MAX_LEGAL_TARGETS = 32
MAX_ATTACK_SLOTS = 8
MAX_TACTICAL_FEATURES = 32
MAX_MENU_OPTIONS = 512
MAX_IDENTITY_CHARS = 128
MAX_FEATURE_NAME_CHARS = 128
MAX_OBSERVED_ACTIONS = 32
MAX_ACTIONS_PER_VISIBLE_PC = 3
MAX_ACTION_TEXT_CHARS = 120
MAX_DISPOSITION_CHARS = 240
MAX_COMMANDER_PLAN_CONTENT_CHARS = 32000
MAX_STANDING_ORDERS_CONTENT_CHARS = 32000
MAX_STANDING_ORDER_INTENT_CHARS = 160
_COMMANDER_PLAN_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "combat" / "commander_plan_prompt.txt"
)
_STANDING_ORDERS_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "combat" / "standing_orders_prompt.txt"
)
_STANDING_ORDERS_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "combat_tactical_standing_orders_schema.json"
)
STANDING_ORDER_WHEN_VALUES = frozenset({
    "always",
    "self_bloodied",
    "self_near_death",
    "commander_down",
    "cover_available",
    "ally_departed",
})
STANDING_ORDER_DEFAULT_REASON = "STANDING_ORDERS_UNAVAILABLE"

TACTICAL_DEFAULT_REASON_CODES = frozenset({
    "INVALID_CHOICE",
    "MISSING_CHOICE",
    "UNKNOWN_ACTOR",
    "DUPLICATE_ID",
    "UNISSUED_ID",
    STANDING_ORDER_DEFAULT_REASON,
})
_MENU_FAILURE_CODES = frozenset(DECLINE_REASON_CODES) | frozenset({
    "commander_unavailable",
    "commander_ambiguous",
    "menu_limit_exceeded",
    "malformed_tactical_data",
})
_VALID_COMBATANT_KINDS = frozenset({"enemy", "player", "npc"})
_INACTIVE_STATUSES = frozenset({"dead", "defeated"})
_RECENT_ACTION_KINDS = frozenset({
    "attacked",
    "defended",
    "moved",
    "held",
    "used_feature",
})


@dataclass(frozen=True)
class TacticalOption:
    """One issued choice; mechanics remain attached to its authoritative facts."""

    option_id: str
    kind: str
    actor: CombatantIdentity
    action_name: Optional[str] = None
    target: Optional[CombatantIdentity] = None
    feature_id: Optional[str] = None
    feature_name: Optional[str] = None
    cover_type: Optional[str] = None
    conditional_on: Optional[str] = None
    attack_is_ranged: Optional[bool] = None

    def to_projection(self) -> dict[str, Any]:
        """Return only bounded choice labels, never attack mechanics or state."""
        result = {"option_id": self.option_id, "kind": self.kind}
        if self.kind == "attack":
            # TABLETOP MODE: make the existing cover/attack legality explicit
            # to the planner. Python still validates this against the menu.
            result["cover_compatible"] = self.attack_is_ranged is True
        if self.kind == "flee":
            # TABLETOP MODE: explain the authorized flight outcome without
            # changing when Python offers or accepts the option.
            result["meaning"] = (
                "Direct flee is offered to a bloodied actor. Use this actor's "
                "action to take the Disengage action, make no attack, and leave "
                "combat at turn end."
            )
            if self.conditional_on == "withdrawal_order":
                result["meaning"] = (
                    "Conditional flee: use this actor's action to take the "
                    "Disengage action, make no attack, and leave combat at turn "
                    "end; legal only with the listed withdrawal order in this plan."
                )
        if isinstance(self.action_name, str) and self.action_name.strip():
            result["action"] = self.action_name.strip()[:MAX_ACTION_TEXT_CHARS]
        if self.target:
            result["target"] = self.target.name
        if self.feature_id:
            result["feature_id"] = self.feature_id
            result["feature"] = self.feature_name or self.feature_id
            result["cover_type"] = self.cover_type or ""
        if self.conditional_on:
            result["condition"] = self.conditional_on
        return result


@dataclass(frozen=True)
class TacticalActorMenu:
    """Options for one actor, with attack slots kept in resolver order."""

    actor: CombatantIdentity
    attack_slots: tuple[tuple[TacticalOption, ...], ...]
    choices: tuple[TacticalOption, ...]
    default_option_ids: tuple[str, ...]

    @property
    def options(self) -> tuple[TacticalOption, ...]:
        return tuple(
            option
            for slot in self.attack_slots
            for option in slot
        ) + self.choices


@dataclass(frozen=True)
class TacticalMenus:
    """Immutable batch-local menu snapshot used for projection and validation."""

    batch_id: str
    commander: Optional[CombatantIdentity]
    actor_menus: tuple[TacticalActorMenu, ...]
    commander_options: tuple[TacticalOption, ...]
    legal_targets: tuple[CombatantIdentity, ...]
    target_catalog: tuple[CombatantIdentity, ...]
    commander_down: bool = False

    @property
    def all_options(self) -> tuple[TacticalOption, ...]:
        return tuple(
            option
            for actor_menu in self.actor_menus
            for option in actor_menu.options
        ) + self.commander_options

    def without_departed(
        self, departed: Sequence[CombatantIdentity]
    ) -> "TacticalMenus":
        """Build a later-batch view without fled/surrendered actors or targets."""
        departed_keys = {_identity_key(item) for item in departed}

        def keep(option: TacticalOption) -> bool:
            return (
                _identity_key(option.actor) not in departed_keys
                and (option.target is None or _identity_key(option.target) not in departed_keys)
            )

        menus = []
        for actor_menu in self.actor_menus:
            if _identity_key(actor_menu.actor) in departed_keys:
                continue
            slots = tuple(
                tuple(option for option in slot if keep(option))
                for slot in actor_menu.attack_slots
            )
            choices = tuple(option for option in actor_menu.choices if keep(option))
            surviving_ids = {
                option.option_id
                for option in tuple(item for slot in slots for item in slot) + choices
            }
            defaults = tuple(
                option_id for option_id in actor_menu.default_option_ids
                if option_id in surviving_ids
            )
            menus.append(replace(
                actor_menu,
                attack_slots=slots,
                choices=choices,
                default_option_ids=defaults,
            ))

        commander = self.commander
        if commander is not None and _identity_key(commander) in departed_keys:
            commander = None
        commander_options = tuple(
            option for option in self.commander_options if keep(option)
        ) if commander else ()
        return TacticalMenus(
            batch_id=self.batch_id,
            commander=commander,
            actor_menus=tuple(menus),
            commander_options=commander_options,
            legal_targets=tuple(
                target for target in self.legal_targets
                if _identity_key(target) not in departed_keys
            ),
            target_catalog=tuple(
                target for target in self.target_catalog
                if _identity_key(target) not in departed_keys
            ),
            commander_down=self.commander_down or (
                self.commander is not None
                and _identity_key(self.commander) in departed_keys
            ),
        )


@dataclass(frozen=True)
class TacticalMenuBuildFailure:
    """A bounded reason why a commander menu cannot be issued."""

    reason_code: str


@dataclass(frozen=True)
class ValidatedTacticalChoice:
    """One immutable actor choice or its rule-tier fallback."""

    actor: CombatantIdentity
    kind: str
    option_ids: tuple[str, ...]
    action_consumed: bool
    no_attack: bool
    disengage: bool = False
    no_opportunity_attacks: bool = False
    leaves_at_turn_end: bool = False
    defeat_reason: Optional[str] = None
    cover_option_id: Optional[str] = None
    cover_feature_id: Optional[str] = None
    cover_type: Optional[str] = None
    default_reason: Optional[str] = None


@dataclass(frozen=True)
class ValidatedTacticalPlan:
    """Immutable plan result, including later menus after self-preservation."""

    status: str
    choices: tuple[ValidatedTacticalChoice, ...]
    withdrawal_order_issued: bool
    side_surrender: bool
    rejected_reason_codes: tuple[str, ...]
    departed_creatures: tuple[CombatantIdentity, ...]
    remaining_menus: TacticalMenus
    remaining_target_identities: tuple[CombatantIdentity, ...]


class _DuplicateJsonKey(ValueError):
    pass


def _canonical_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _identity_key(identity: CombatantIdentity) -> tuple[str, str]:
    return identity.kind, _canonical_name(identity.name)


def _normalize_identity(value: Any) -> Optional[CombatantIdentity]:
    if isinstance(value, CombatantIdentity):
        identity = value
    elif isinstance(value, Mapping):
        name = value.get("name")
        kind = value.get("kind", value.get("type"))
        if not isinstance(name, str) or not isinstance(kind, str):
            return None
        identity = CombatantIdentity(name=name.strip(), kind=kind.strip().lower())
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        first, second = value
        if not isinstance(first, str) or not isinstance(second, str):
            return None
        if first.strip().lower() in _VALID_COMBATANT_KINDS:
            identity = CombatantIdentity(name=second.strip(), kind=first.strip().lower())
        else:
            identity = CombatantIdentity(name=first.strip(), kind=second.strip().lower())
    else:
        return None
    if (
        not isinstance(identity.name, str)
        or not identity.name.strip()
        or len(identity.name.strip()) > MAX_IDENTITY_CHARS
        or identity.kind not in _VALID_COMBATANT_KINDS
    ):
        return None
    return CombatantIdentity(name=identity.name.strip(), kind=identity.kind)


def _option_id(
    batch_id: str,
    actor: CombatantIdentity,
    kind: str,
    *,
    slot: Optional[int] = None,
    action_name: Optional[str] = None,
    target: Optional[CombatantIdentity] = None,
    feature_id: Optional[str] = None,
) -> str:
    payload = {
        "batch": batch_id,
        "actor": [actor.kind, _canonical_name(actor.name)],
        "kind": kind,
        "slot": slot,
        "action": action_name,
        "target": (
            [target.kind, _canonical_name(target.name)] if target else None
        ),
        "feature": feature_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "opt_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _is_option_id(value: Any) -> bool:
    """Return whether a value has the opaque option-ID wire format."""
    return (
        isinstance(value, str)
        and len(value) == 28
        and value.startswith("opt_")
        and all(character in "0123456789abcdef" for character in value[4:])
    )


def _living_enemy_creature(creature: Mapping[str, Any]) -> bool:
    hp = creature.get("currentHitPoints")
    status = creature.get("status", "alive")
    return (
        isinstance(hp, int)
        and not isinstance(hp, bool)
        and hp > 0
        and isinstance(status, str)
        and status.strip().lower() not in _INACTIVE_STATUSES
    )


def _find_commander(
    encounter: Mapping[str, Any], *, allow_commander_down: bool = False
) -> Union[CombatantIdentity, TacticalMenuBuildFailure, None]:
    creatures = encounter.get("creatures")
    if not isinstance(creatures, list):
        return TacticalMenuBuildFailure("malformed_encounter")
    designated = []
    candidates = []
    for creature in creatures:
        if not isinstance(creature, Mapping):
            continue
        if creature.get("type") != "enemy":
            continue
        if creature.get("leader") is True and creature.get("tactics", "rule") == "commander":
            identity = _normalize_identity({"name": creature.get("name"), "kind": "enemy"})
            if identity is None:
                return TacticalMenuBuildFailure("malformed_encounter")
            designated.append(identity)
            if _living_enemy_creature(creature):
                candidates.append(identity)
    if len(designated) > 1:
        return TacticalMenuBuildFailure("commander_ambiguous")
    if not candidates:
        if allow_commander_down and len(designated) == 1:
            return None
        return TacticalMenuBuildFailure("commander_unavailable")
    if len(candidates) != 1:
        return TacticalMenuBuildFailure("commander_ambiguous")
    return candidates[0]


def _feature_rows(features: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(features, list) or len(features) > MAX_TACTICAL_FEATURES:
        return ()
    if validate_tactical_features(features):
        return ()
    required = {"featureId", "name", "kind", "coverType", "usableBy"}
    valid = []
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
            or feature.get("kind") != "cover"
            or feature.get("coverType") not in {"half", "three_quarters"}
            or not isinstance(usable_by, list)
            or not usable_by
            or any(item not in _VALID_COMBATANT_KINDS for item in usable_by)
        ):
            continue
        valid.append(feature)
    return tuple(valid)


def _decline_failure(result: EnemyResolutionDecline) -> TacticalMenuBuildFailure:
    reason = result.reason_code
    return TacticalMenuBuildFailure(
        reason if reason in _MENU_FAILURE_CODES else "malformed_input"
    )


def build_tactical_menus(
    encounter: Mapping[str, Any],
    pc_states: Mapping[str, Any],
    monster_definitions: Mapping[str, Any],
    turn_order: Sequence[Any],
    batch_id: str,
    *,
    batch_kind: str = "enemy_phase",
    fixture_seed: Optional[Union[str, int]] = None,
    enemy_turn_window: Optional[Sequence[Any]] = None,
    legal_targets: Optional[Sequence[Any]] = None,
    tactical_features: Any = None,
    active_encounter_id: Optional[str] = None,
    combat_in_progress: bool = False,
    allow_commander_down: bool = False,
) -> Union[TacticalMenus, TacticalMenuBuildFailure]:
    """Build deterministic, bounded options for one explicitly-led batch.

    The resolver is run first with only its near-death guard relaxed for this
    commander-authorized preflight. All other eligibility, attack validation,
    target rotation, and default attack selection remain resolver-owned. An
    optional target list is intersected with the resolver's current legal set.
    """
    if not isinstance(encounter, Mapping):
        return TacticalMenuBuildFailure("malformed_encounter")
    commander = _find_commander(
        encounter, allow_commander_down=allow_commander_down
    )
    if isinstance(commander, TacticalMenuBuildFailure):
        return commander
    commander_down = commander is None

    resolver_args = {
        "encounter": encounter,
        "pc_states": pc_states,
        "monster_definitions": monster_definitions,
        "turn_order": turn_order,
        "batch_id": batch_id,
        "batch_kind": batch_kind,
        "fixture_seed": fixture_seed,
        "enemy_turn_window": enemy_turn_window,
        "allow_near_death": True,
        "active_encounter_id": active_encounter_id,
        "combat_in_progress": combat_in_progress,
        "tactical_features": tactical_features,
    }
    resolver_plan = plan_enemy_batch(**resolver_args)
    if isinstance(resolver_plan, EnemyResolutionDecline):
        return _decline_failure(resolver_plan)

    resolver_targets = get_legal_enemy_batch_targets(
        encounter, pc_states, turn_order
    )
    if isinstance(resolver_targets, EnemyResolutionDecline):
        return _decline_failure(resolver_targets)
    allowed_target_keys = {_identity_key(target): target for target in resolver_targets}
    if legal_targets is not None:
        if not isinstance(legal_targets, Sequence) or isinstance(legal_targets, (str, bytes)):
            return TacticalMenuBuildFailure("malformed_tactical_data")
        requested_targets = []
        for raw_target in legal_targets:
            target = _normalize_identity(raw_target)
            if target is None:
                continue
            matched = allowed_target_keys.get(_identity_key(target))
            if matched is not None and _identity_key(matched) not in {
                _identity_key(item) for item in requested_targets
            }:
                requested_targets.append(matched)
        selected_targets = tuple(requested_targets)
    else:
        selected_targets = tuple(resolver_targets)
    if not selected_targets:
        return TacticalMenuBuildFailure("no_eligible_target")
    if len(selected_targets) > MAX_LEGAL_TARGETS:
        return TacticalMenuBuildFailure("menu_limit_exceeded")

    creatures = encounter.get("creatures")
    if not isinstance(creatures, list):
        return TacticalMenuBuildFailure("malformed_encounter")
    creature_by_key = {}
    target_catalog = []
    for creature in creatures:
        if not isinstance(creature, Mapping):
            return TacticalMenuBuildFailure("malformed_encounter")
        identity = _normalize_identity({
            "name": creature.get("name"),
            "kind": creature.get("type"),
        })
        if identity is None:
            return TacticalMenuBuildFailure("malformed_encounter")
        key = _identity_key(identity)
        if key in creature_by_key:
            return TacticalMenuBuildFailure("ambiguous_identity")
        creature_by_key[key] = creature
        if identity.kind == "enemy" and _living_enemy_creature(creature):
            target_catalog.append(identity)

    entries_by_actor: dict[tuple[str, str], list[Any]] = {}
    actor_order = []
    for entry in resolver_plan.entries:
        key = _identity_key(entry.actor)
        if key not in entries_by_actor:
            entries_by_actor[key] = []
            actor_order.append(entry.actor)
        entries_by_actor[key].append(entry)
    if len(actor_order) > MAX_MENU_ACTORS:
        return TacticalMenuBuildFailure("menu_limit_exceeded")

    features = _feature_rows(tactical_features)
    actor_menus = []
    all_ids = set()
    option_count = 0
    any_above_bloodied = False
    any_near_death = False

    for actor in actor_order:
        actor_creature = creature_by_key.get(_identity_key(actor))
        if actor_creature is None:
            return TacticalMenuBuildFailure("unknown_actor")
        hp = actor_creature.get("currentHitPoints")
        max_hp = actor_creature.get("maxHitPoints")
        if (
            isinstance(hp, bool)
            or not isinstance(hp, int)
            or isinstance(max_hp, bool)
            or not isinstance(max_hp, int)
            or hp <= 0
            or max_hp <= 0
        ):
            return TacticalMenuBuildFailure("malformed_encounter")
        bloodied = hp * 2 <= max_hp
        near_death = hp * 4 <= max_hp
        any_above_bloodied = any_above_bloodied or not bloodied
        any_near_death = any_near_death or near_death

        actor_entries = entries_by_actor[_identity_key(actor)]
        if len(actor_entries) > MAX_ATTACK_SLOTS:
            return TacticalMenuBuildFailure("menu_limit_exceeded")
        attack_slots = []
        defaults = []
        for slot_index, entry in enumerate(actor_entries):
            if _identity_key(entry.target) not in allowed_target_keys:
                return TacticalMenuBuildFailure("unknown_target")
            slot_options = []
            for target in selected_targets:
                option = TacticalOption(
                    option_id=_option_id(
                        resolver_plan.batch_id,
                        actor,
                        "attack",
                        slot=slot_index,
                        action_name=entry.action_name,
                        target=target,
                    ),
                    kind="attack",
                    actor=actor,
                    action_name=entry.action_name,
                    target=target,
                    attack_is_ranged=entry.action_is_ranged,
                )
                slot_options.append(option)
            default_id = _option_id(
                resolver_plan.batch_id,
                actor,
                "attack",
                slot=slot_index,
                action_name=entry.action_name,
                target=entry.target,
            )
            if default_id not in {option.option_id for option in slot_options}:
                return TacticalMenuBuildFailure("unknown_target")
            defaults.append(default_id)
            attack_slots.append(tuple(slot_options))
            option_count += len(slot_options)

        choices = []

        def add_choice(
            kind: str,
            *,
            feature: Optional[Mapping[str, Any]] = None,
            conditional_on: Optional[str] = None,
        ) -> None:
            nonlocal option_count
            option = TacticalOption(
                option_id=_option_id(
                    resolver_plan.batch_id,
                    actor,
                    kind,
                    feature_id=feature.get("featureId") if feature else None,
                ),
                kind=kind,
                actor=actor,
                feature_id=feature.get("featureId") if feature else None,
                feature_name=feature.get("name") if feature else None,
                cover_type=feature.get("coverType") if feature else None,
                conditional_on=conditional_on,
            )
            choices.append(option)
            option_count += 1

        add_choice("hold")
        for feature in features:
            if "enemy" in feature["usableBy"]:
                add_choice("take_cover", feature=feature)
        if bloodied:
            add_choice("flee")
        elif any_above_bloodied or not bloodied:
            # This option is conditional until the commander order is selected.
            add_choice("flee", conditional_on="withdrawal_order")
        if near_death:
            add_choice("surrender")

        actor_menus.append(TacticalActorMenu(
            actor=actor,
            attack_slots=tuple(attack_slots),
            choices=tuple(choices),
            default_option_ids=tuple(defaults),
        ))

    commander_options = []
    if any_above_bloodied and commander is not None:
        commander_options.append(TacticalOption(
            option_id=_option_id(resolver_plan.batch_id, commander, "withdrawal_order"),
            kind="withdrawal_order",
            actor=commander,
        ))
    if any_near_death and commander is not None:
        commander_options.append(TacticalOption(
            option_id=_option_id(
                resolver_plan.batch_id, commander, "commander_side_surrender"
            ),
            kind="commander_side_surrender",
            actor=commander,
        ))
    option_count += len(commander_options)
    if option_count > MAX_MENU_OPTIONS:
        return TacticalMenuBuildFailure("menu_limit_exceeded")

    for option in tuple(
        option
        for menu in actor_menus
        for option in menu.options
    ) + tuple(commander_options):
        if option.option_id in all_ids:
            return TacticalMenuBuildFailure("malformed_tactical_data")
        all_ids.add(option.option_id)

    return TacticalMenus(
        batch_id=resolver_plan.batch_id,
        commander=commander,
        actor_menus=tuple(actor_menus),
        commander_options=tuple(commander_options),
        legal_targets=selected_targets,
        target_catalog=tuple(target_catalog),
        commander_down=commander_down,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey("duplicate JSON key")
        result[key] = value
    return result


def _parse_plan(plan_json: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(plan_json, str):
        try:
            plan_json = json.loads(
                plan_json,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return plan_json if isinstance(plan_json, Mapping) else None


def _reason(code: str) -> str:
    return code if code in TACTICAL_DEFAULT_REASON_CODES else "INVALID_CHOICE"


def _default_choice(
    actor_menu: TacticalActorMenu, reason_code: str
) -> ValidatedTacticalChoice:
    return ValidatedTacticalChoice(
        actor=actor_menu.actor,
        kind="attack",
        option_ids=actor_menu.default_option_ids,
        action_consumed=True,
        no_attack=False,
        default_reason=_reason(reason_code),
    )


def rule_default_tactical_plan(
    menus: TacticalMenus, reason_code: str
) -> ValidatedTacticalPlan:
    """Build the existing validated-plan shape with one bounded reason per actor."""
    if reason_code not in TACTICAL_DEFAULT_REASON_CODES:
        reason_code = "INVALID_CHOICE"
    choices = tuple(
        _default_choice(actor_menu, reason_code)
        for actor_menu in menus.actor_menus
    )
    return ValidatedTacticalPlan(
        status="rejected_all" if choices else "accepted",
        choices=choices,
        withdrawal_order_issued=False,
        side_surrender=False,
        rejected_reason_codes=(reason_code,) if choices else (),
        departed_creatures=(),
        remaining_menus=menus,
        remaining_target_identities=menus.target_catalog,
    )


def _resolve_choice(
    actor_menu: TacticalActorMenu,
    option_ids: Any,
    *,
    withdrawal_order_issued: bool,
    departed: set[tuple[str, str]],
) -> tuple[Optional[ValidatedTacticalChoice], str]:
    if not isinstance(option_ids, list) or not option_ids:
        return None, "INVALID_CHOICE"
    if any(not _is_option_id(item) for item in option_ids):
        return None, "INVALID_CHOICE"
    if len(set(option_ids)) != len(option_ids):
        return None, "DUPLICATE_ID"

    by_id = {option.option_id: option for option in actor_menu.options}
    if actor_menu.attack_slots and len(option_ids) == len(actor_menu.attack_slots) + 1:
        cover_option = by_id.get(option_ids[-1])
        if cover_option is None:
            return None, "UNISSUED_ID"
        if cover_option.kind != "take_cover":
            return None, "INVALID_CHOICE"

        attack_option_ids = option_ids[:-1]
        selected_attacks = []
        for slot, option_id in zip(actor_menu.attack_slots, attack_option_ids):
            option = next((item for item in slot if item.option_id == option_id), None)
            if option is None:
                return None, "UNISSUED_ID" if option_id not in by_id else "INVALID_CHOICE"
            if option.target and _identity_key(option.target) in departed:
                return None, "INVALID_CHOICE"
            # D5 expires cover after melee, so accepting a cover-plus-melee plan
            # would silently discard one of the commander's selected actions.
            if option.attack_is_ranged is not True:
                return None, "INVALID_CHOICE"
            selected_attacks.append(option)
        if len(selected_attacks) != len(actor_menu.attack_slots):
            return None, "INVALID_CHOICE"
        return ValidatedTacticalChoice(
            actor=actor_menu.actor,
            kind="attack",
            option_ids=tuple(option.option_id for option in selected_attacks),
            action_consumed=True,
            no_attack=False,
            cover_option_id=cover_option.option_id,
            cover_feature_id=cover_option.feature_id,
            cover_type=cover_option.cover_type,
        ), ""

    if len(actor_menu.attack_slots) > 0 and len(option_ids) == len(actor_menu.attack_slots):
        selected = []
        defaulted_slot = False
        for slot, option_id, default_option_id in zip(
            actor_menu.attack_slots, option_ids, actor_menu.default_option_ids
        ):
            option = next((item for item in slot if item.option_id == option_id), None)
            if option is None:
                if len(option_ids) == 1:
                    # Preserve the shared single-ID path for flee, surrender,
                    # hold, and cover choices even when the actor can attack.
                    selected = []
                    break
                if option_id not in by_id:
                    return None, "UNISSUED_ID"
                option = next(
                    (item for item in slot if item.option_id == default_option_id),
                    None,
                )
                if option is None:
                    return None, "INVALID_CHOICE"
                defaulted_slot = True
            if option.target and _identity_key(option.target) in departed:
                return None, "INVALID_CHOICE"
            selected.append(option)
        if selected:
            return ValidatedTacticalChoice(
                actor=actor_menu.actor,
                kind="attack",
                option_ids=tuple(option.option_id for option in selected),
                action_consumed=True,
                no_attack=False,
                default_reason="INVALID_CHOICE" if defaulted_slot else None,
            ), ""

    if len(option_ids) != 1:
        return None, "INVALID_CHOICE"
    option_id = option_ids[0]
    option = by_id.get(option_id)
    if option is None:
        return None, "UNISSUED_ID"
    if option.kind == "flee" and option.conditional_on and not withdrawal_order_issued:
        return None, "INVALID_CHOICE"
    if option.target and _identity_key(option.target) in departed:
        return None, "INVALID_CHOICE"

    if option.kind == "attack":
        # A single-attack creature still uses the slot validation above.
        return None, "INVALID_CHOICE"
    if option.kind not in {"hold", "take_cover", "flee", "surrender"}:
        return None, "INVALID_CHOICE"
    is_flee = option.kind == "flee"
    is_surrender = option.kind == "surrender"
    return ValidatedTacticalChoice(
        actor=actor_menu.actor,
        kind=option.kind,
        option_ids=(option.option_id,),
        action_consumed=True,
        no_attack=True,
        disengage=is_flee,
        no_opportunity_attacks=is_flee,
        leaves_at_turn_end=is_flee or is_surrender,
        defeat_reason="fled" if is_flee else "surrendered" if is_surrender else None,
        cover_feature_id=option.feature_id,
        cover_type=option.cover_type,
    ), ""


def _resolve_orders(
    raw_orders: Any, menus: TacticalMenus
) -> tuple[bool, bool, tuple[str, ...]]:
    if raw_orders is None:
        raw_orders = []
    if not isinstance(raw_orders, list):
        return False, False, ("INVALID_CHOICE",)
    if any(not _is_option_id(item) for item in raw_orders):
        return False, False, ("INVALID_CHOICE",)
    if len(set(raw_orders)) != len(raw_orders):
        return False, False, ("DUPLICATE_ID",)
    if len(raw_orders) > 1:
        return False, False, ("INVALID_CHOICE",)
    if not raw_orders:
        return False, False, ()
    order_options = {option.option_id: option for option in menus.commander_options}
    selected = order_options.get(raw_orders[0])
    if selected is None:
        return False, False, ("UNISSUED_ID",)
    return (
        selected.kind == "withdrawal_order",
        selected.kind == "commander_side_surrender",
        (),
    )


def validate_commander_plan(
    plan_json: Any,
    menus: TacticalMenus,
    **_ignored_context: Any,
) -> ValidatedTacticalPlan:
    """Accept only issued option IDs and otherwise use resolver defaults.

    The keyword catch is intentionally inert for the next integration task:
    authoritative state is already frozen into ``menus`` and extra data can
    never add an identity or option to that snapshot.
    """
    if not isinstance(menus, TacticalMenus):
        raise TypeError("menus must be a TacticalMenus snapshot")

    parsed = _parse_plan(plan_json)
    plan_reasons = []
    actor_rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    duplicate_actor_keys = set()
    invalid_whole_plan = parsed is None
    if invalid_whole_plan or set(parsed) - {"choices", "orders"}:
        invalid_whole_plan = True
        parsed = {}
        plan_reasons.append("INVALID_CHOICE")

    raw_choices = parsed.get("choices", [])
    invalid_choices_container = not isinstance(raw_choices, list)
    if invalid_choices_container:
        raw_choices = []
        plan_reasons.append("INVALID_CHOICE")

    actor_keys = {_identity_key(menu.actor): menu.actor for menu in menus.actor_menus}
    seen_actor_keys = set()
    malformed_actor_keys = set()
    for row in raw_choices:
        if not isinstance(row, Mapping):
            plan_reasons.append("INVALID_CHOICE")
            continue
        raw_actor = row.get("actor")
        if not isinstance(raw_actor, str):
            plan_reasons.append("UNKNOWN_ACTOR")
            continue
        actor_key = _identity_key(CombatantIdentity(raw_actor.strip(), "enemy"))
        if actor_key not in actor_keys:
            plan_reasons.append("UNKNOWN_ACTOR")
            continue
        if actor_key in seen_actor_keys:
            duplicate_actor_keys.add(actor_key)
            continue
        seen_actor_keys.add(actor_key)
        if set(row) != {"actor", "option_ids"}:
            malformed_actor_keys.add(actor_key)
            plan_reasons.append("INVALID_CHOICE")
            continue
        actor_rows[actor_key] = row

    withdrawal_order, side_surrender, order_reasons = _resolve_orders(
        parsed.get("orders", []), menus
    )
    plan_reasons.extend(order_reasons)

    choices = []
    departed = set()
    departed_identities = []
    for actor_menu in menus.actor_menus:
        actor_key = _identity_key(actor_menu.actor)
        if actor_key in duplicate_actor_keys:
            choices.append(_default_choice(actor_menu, "DUPLICATE_ID"))
            continue
        if actor_key in malformed_actor_keys:
            choices.append(_default_choice(actor_menu, "INVALID_CHOICE"))
            continue
        row = actor_rows.get(actor_key)
        if row is None:
            missing_reason = (
                "INVALID_CHOICE"
                if invalid_whole_plan or invalid_choices_container
                else "MISSING_CHOICE"
            )
            choices.append(_default_choice(actor_menu, missing_reason))
            continue
        selected, reason_code = _resolve_choice(
            actor_menu,
            row.get("option_ids"),
            withdrawal_order_issued=withdrawal_order,
            departed=departed,
        )
        if selected is None:
            choices.append(_default_choice(actor_menu, reason_code))
            continue
        choices.append(selected)
        if selected.defeat_reason:
            departed.add(actor_key)
            departed_identities.append(actor_menu.actor)

    if side_surrender:
        for enemy in menus.target_catalog:
            key = _identity_key(enemy)
            if key not in departed:
                departed.add(key)
                departed_identities.append(enemy)

    remaining_menus = menus.without_departed(tuple(departed_identities))
    remaining_targets = tuple(
        identity
        for identity in menus.target_catalog
        if _identity_key(identity) not in departed
    )
    defaulted = sum(choice.default_reason is not None for choice in choices)
    if choices and defaulted == len(choices):
        status = "rejected_all"
    elif defaulted or plan_reasons:
        status = "partially_defaulted"
    else:
        status = "accepted"

    bounded_reasons = []
    for reason_code in plan_reasons:
        code = _reason(reason_code)
        if code not in bounded_reasons:
            bounded_reasons.append(code)
    return ValidatedTacticalPlan(
        status=status,
        choices=tuple(choices),
        withdrawal_order_issued=withdrawal_order,
        side_surrender=side_surrender,
        rejected_reason_codes=tuple(bounded_reasons),
        departed_creatures=tuple(departed_identities),
        remaining_menus=remaining_menus,
        remaining_target_identities=remaining_targets,
    )


def _state_value(state: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(state, Mapping) and key in state:
            return state[key]
        if not isinstance(state, Mapping) and hasattr(state, key):
            return getattr(state, key)
    return None


def _state_for_identity(
    pc_states: Mapping[str, Any], identity: CombatantIdentity
) -> Any:
    matches = [
        value for key, value in pc_states.items()
        if isinstance(key, str) and _canonical_name(key) == _canonical_name(identity.name)
    ]
    return matches[0] if len(matches) == 1 else None


def _qualitative_wound(state: Any) -> Optional[str]:
    hp = _state_value(state, "hitPoints", "current_hp")
    max_hp = _state_value(state, "maxHitPoints", "max_hp")
    if (
        isinstance(hp, bool)
        or not isinstance(hp, int)
        or isinstance(max_hp, bool)
        or not isinstance(max_hp, int)
        or hp <= 0
        or max_hp <= 0
    ):
        return None
    if hp * 4 <= max_hp:
        return "near_death"
    if hp * 2 <= max_hp:
        return "bloodied"
    return "unhurt"


def _safe_recent_actions(
    observed_recent_actions: Any,
    *,
    visible_pc_keys: set[tuple[str, str]],
    known_target_names: set[str],
    issued_feature_ids: set[str],
) -> list[dict[str, str]]:
    if not isinstance(observed_recent_actions, Sequence) or isinstance(
        observed_recent_actions, (str, bytes)
    ):
        return []
    result = []
    counts: Counter[tuple[str, str]] = Counter()
    for row in observed_recent_actions[:MAX_OBSERVED_ACTIONS]:
        if not isinstance(row, Mapping):
            continue
        actor_name = row.get("actor")
        action = row.get("action")
        if (
            not isinstance(actor_name, str)
            or not isinstance(action, str)
            or action not in _RECENT_ACTION_KINDS
        ):
            continue
        actor = CombatantIdentity(actor_name.strip(), "player")
        actor_key = _identity_key(actor)
        if actor_key not in visible_pc_keys or not actor.name:
            continue
        target = row.get("target")
        if target is not None:
            if not isinstance(target, str) or _canonical_name(target) not in known_target_names:
                continue
        feature_id = row.get("feature_id")
        if feature_id is not None:
            if not isinstance(feature_id, str) or feature_id not in issued_feature_ids:
                continue

        counts[actor_key] += 1
        if counts[actor_key] > MAX_ACTIONS_PER_VISIBLE_PC:
            continue

        projected = {"actor": actor.name, "action": action}
        if target is not None:
            projected["target"] = target.strip()
        if feature_id is not None:
            projected["feature_id"] = feature_id
        result.append(projected)
    return result


def build_perception_projection(
    menus: TacticalMenus,
    pc_states: Mapping[str, Any],
    observed_recent_actions: Any = None,
    actor_dispositions: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Project only current menu actors, legal PCs, issued features, and observations.

    Missing or malformed optional observations are omitted. The projection is
    deliberately constructed field-by-field, so encounter rosters, coordinates,
    exact HP, PC resources, and unissued features cannot pass through.
    """
    if not isinstance(menus, TacticalMenus):
        raise TypeError("menus must be a TacticalMenus snapshot")
    if not isinstance(pc_states, Mapping):
        pc_states = {}
    if not isinstance(actor_dispositions, Mapping):
        actor_dispositions = {}

    visible_pcs = []
    visible_pc_keys = set()
    for target in menus.legal_targets:
        if target.kind != "player":
            continue
        visible_pc_keys.add(_identity_key(target))
        row = {"name": target.name}
        wound = _qualitative_wound(_state_for_identity(pc_states, target))
        if wound is not None:
            row["wound"] = wound
        visible_pcs.append(row)

    actor_rows = []
    known_target_names = {
        _canonical_name(identity.name)
        for identity in menus.legal_targets + tuple(menu.actor for menu in menus.actor_menus)
    }
    issued_features = {}
    for actor_menu in menus.actor_menus:
        attack_slots = []
        for slot in actor_menu.attack_slots:
            attack_slots.append([option.to_projection() for option in slot])
        choices = []
        for option in actor_menu.choices:
            choices.append(option.to_projection())
            if option.kind == "take_cover" and option.feature_id:
                issued_features[option.feature_id] = {
                    "feature_id": option.feature_id,
                    "name": option.feature_name or option.feature_id,
                    "cover_type": option.cover_type or "",
                }
        actor_rows.append({
            "actor": actor_menu.actor.name,
            "attack_slots": attack_slots,
            "choices": choices,
        })
        disposition = actor_dispositions.get(actor_menu.actor.name)
        if isinstance(disposition, str):
            disposition = " ".join(
                "".join(character for character in disposition if character.isprintable()).split()
            )[:MAX_DISPOSITION_CHARS]
            if disposition:
                actor_rows[-1]["disposition"] = disposition

    order_rows = [option.to_projection() for option in menus.commander_options]
    known_feature_ids = set(issued_features)
    recent = _safe_recent_actions(
        observed_recent_actions,
        visible_pc_keys=visible_pc_keys,
        known_target_names=known_target_names,
        issued_feature_ids=known_feature_ids,
    )
    projection = {
        "batch_id": menus.batch_id,
        "eligible_actors": actor_rows,
        "visible_pcs": visible_pcs,
        "commander_orders": order_rows,
        "issued_features": [issued_features[key] for key in sorted(issued_features)],
    }
    if recent:
        projection["observed_recent_actions"] = recent
    return projection


def build_commander_plan_messages(
    menus: TacticalMenus,
    pc_states: Mapping[str, Any],
    observed_recent_actions: Any = None,
    actor_dispositions: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, str]]:
    """Build one bounded JSON-only router payload from the immutable menu."""
    projection = build_perception_projection(
        menus,
        pc_states,
        observed_recent_actions=observed_recent_actions,
        actor_dispositions=actor_dispositions,
    )
    user_content = json.dumps(
        projection,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(user_content) > MAX_COMMANDER_PLAN_CONTENT_CHARS:
        raise ValueError("commander_plan_payload_too_large")
    system_content = _COMMANDER_PLAN_PROMPT_PATH.read_text(encoding="ascii")
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


@lru_cache(maxsize=1)
def _standing_orders_validator():
    """Load and compile the strict, checked-in standing-orders contract lazily."""
    from jsonschema import Draft7Validator

    schema = json.loads(_STANDING_ORDERS_SCHEMA_PATH.read_text(encoding="ascii"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _valid_standing_order_label(value: Any, max_chars: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= max_chars
        and all(character.isprintable() for character in value)
    )


def parse_standing_orders_response(response: Any) -> Optional[dict[str, Any]]:
    """Return a detached schema-valid order set, rejecting duplicates and extras."""
    try:
        if isinstance(response, str):
            if len(response) > 48_000:
                return None
        elif len(json.dumps(
            response, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        )) > 48_000:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    parsed = _parse_plan(response)
    if parsed is None:
        return None
    try:
        if next(_standing_orders_validator().iter_errors(parsed), None) is not None:
            return None
        actor_keys = set()
        for actor_row in parsed.get("actors", []):
            actor = actor_row["actor"]
            if not _valid_standing_order_label(
                actor["name"], MAX_IDENTITY_CHARS
            ):
                return None
            key = _canonical_name(actor["name"])
            if key in actor_keys:
                return None
            actor_keys.add(key)
            for clause in actor_row["clauses"]:
                action = clause["do"]
                if action["kind"] == "attack":
                    target = action["target"]
                    if not _valid_standing_order_label(
                        target["name"], MAX_IDENTITY_CHARS
                    ):
                        return None
                    if "action" in action and not _valid_standing_order_label(
                        action["action"], MAX_ACTION_TEXT_CHARS
                    ):
                        return None
                elif action["kind"] == "take_cover" and (
                    "feature_id" in action
                    and not _valid_standing_order_label(
                        action["feature_id"], MAX_IDENTITY_CHARS
                    )
                ):
                    return None
        commander_actions = [
            row["do"] for row in parsed.get("commander_clauses", [])
        ]
        if len(set(commander_actions)) != len(commander_actions):
            return None
        return copy.deepcopy(dict(parsed))
    except (KeyError, TypeError, ValueError, OSError):
        return None


def build_standing_orders_messages(
    menus: TacticalMenus,
    pc_states: Mapping[str, Any],
    observed_recent_actions: Any = None,
    actor_dispositions: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, str]]:
    """Build the separate bounded prompt; the synchronous prompt stays untouched."""
    projection = build_perception_projection(
        menus,
        pc_states,
        observed_recent_actions=observed_recent_actions,
        actor_dispositions=actor_dispositions,
    )
    user_content = json.dumps(
        projection,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(user_content) > MAX_STANDING_ORDERS_CONTENT_CHARS:
        raise ValueError("standing_orders_payload_too_large")
    system_content = _STANDING_ORDERS_PROMPT_PATH.read_text(encoding="ascii")
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _standing_order_creature(
    encounter_data: Mapping[str, Any], identity: Optional[CombatantIdentity]
) -> Optional[Mapping[str, Any]]:
    if identity is None:
        return None
    creatures = encounter_data.get("creatures")
    if not isinstance(creatures, list):
        return None
    matches = []
    for creature in creatures:
        if not isinstance(creature, Mapping):
            continue
        current = _normalize_identity({
            "name": creature.get("name"), "kind": creature.get("type")
        })
        if current is not None and _identity_key(current) == _identity_key(identity):
            matches.append(creature)
    return matches[0] if len(matches) == 1 else None


def _standing_order_condition_holds(
    condition: str,
    actor: Optional[CombatantIdentity],
    actor_menu: Optional[TacticalActorMenu],
    menus: TacticalMenus,
    encounter_data: Mapping[str, Any],
    *,
    ally_departed: bool,
) -> bool:
    if condition == "always":
        return True
    if condition == "commander_down":
        return menus.commander_down
    if condition == "ally_departed":
        return ally_departed
    if condition == "cover_available":
        return bool(actor_menu and any(
            option.kind == "take_cover" for option in actor_menu.choices
        ))
    creature = _standing_order_creature(encounter_data, actor)
    if creature is None:
        return False
    hp = creature.get("currentHitPoints")
    max_hp = creature.get("maxHitPoints")
    if (
        isinstance(hp, bool)
        or not isinstance(hp, int)
        or isinstance(max_hp, bool)
        or not isinstance(max_hp, int)
        or hp <= 0
        or max_hp <= 0
    ):
        return False
    if condition == "self_bloodied":
        return hp * 2 <= max_hp
    if condition == "self_near_death":
        return hp * 4 <= max_hp
    return False


def _standing_order_action_option_ids(
    action: Mapping[str, Any], actor_menu: TacticalActorMenu
) -> Optional[list[str]]:
    kind = action.get("kind")
    if kind == "attack":
        target_data = action.get("target")
        target = _normalize_identity(target_data)
        if target is None:
            return None
        action_name = action.get("action")
        normalized_action = (
            " ".join(action_name.split()).casefold()
            if isinstance(action_name, str) else None
        )
        selected_ids = []
        matched_slots = 0
        for slot, default_id in zip(
            actor_menu.attack_slots, actor_menu.default_option_ids
        ):
            matches = [
                option for option in slot
                if option.target is not None
                and _identity_key(option.target) == _identity_key(target)
                and (
                    normalized_action is None
                    or (
                        isinstance(option.action_name, str)
                        and " ".join(option.action_name.split()).casefold()
                        == normalized_action
                    )
                )
            ]
            if len(matches) > 1:
                return None
            if matches:
                selected_ids.append(matches[0].option_id)
                matched_slots += 1
            else:
                selected_ids.append(default_id)
        return selected_ids if matched_slots else None

    if kind == "take_cover":
        feature_id = action.get("feature_id")
        options = [
            option for option in actor_menu.choices
            if option.kind == "take_cover"
            and (feature_id is None or option.feature_id == feature_id)
        ]
        return [options[0].option_id] if options else None

    if kind in {"flee", "surrender", "hold"}:
        options = [
            option for option in actor_menu.choices if option.kind == kind
        ]
        return [options[0].option_id] if options else None
    return None


def compile_standing_orders(
    standing_orders: Any,
    menus: TacticalMenus,
    encounter_data: Mapping[str, Any],
    *,
    ally_departed: bool = False,
) -> Optional[dict[str, Any]]:
    """Compile first currently legal clauses into the existing candidate-plan shape."""
    orders = parse_standing_orders_response(standing_orders)
    if orders is None or not isinstance(encounter_data, Mapping):
        return None

    actor_menus = {
        _identity_key(actor_menu.actor): actor_menu
        for actor_menu in menus.actor_menus
    }
    source_rows = {}
    for row in orders.get("actors", []):
        identity = _normalize_identity(row.get("actor"))
        if identity is not None:
            source_rows[_identity_key(identity)] = row

    commander_identity = menus.commander
    if commander_identity is None:
        creatures = encounter_data.get("creatures", [])
        if isinstance(creatures, list):
            for creature in creatures:
                if (
                    isinstance(creature, Mapping)
                    and creature.get("type") == "enemy"
                    and creature.get("leader") is True
                    and creature.get("tactics", "rule") == "commander"
                ):
                    commander_identity = _normalize_identity({
                        "name": creature.get("name"), "kind": "enemy"
                    })
                    break

    compiled_order_ids = []
    order_by_kind = {
        option.kind: option
        for option in menus.commander_options
        if option.kind in {"withdrawal_order", "commander_side_surrender"}
    }
    for clause in orders.get("commander_clauses", []):
        action_kind = clause["do"]
        option_kind = (
            "commander_side_surrender"
            if action_kind == "side_surrender" else "withdrawal_order"
        )
        option = order_by_kind.get(option_kind)
        if (
            option is None
            or not _standing_order_condition_holds(
                clause["when"], commander_identity, None, menus,
                encounter_data, ally_departed=ally_departed,
            )
        ):
            continue
        compiled_order_ids.append(option.option_id)
        break

    withdrawal_order_issued = bool(
        compiled_order_ids
        and order_by_kind.get("withdrawal_order") is not None
        and compiled_order_ids[0] == order_by_kind["withdrawal_order"].option_id
    )
    choices = []
    for actor_menu in menus.actor_menus:
        row = source_rows.get(_identity_key(actor_menu.actor))
        if row is None:
            continue
        for clause in row.get("clauses", []):
            if not _standing_order_condition_holds(
                clause["when"], actor_menu.actor, actor_menu, menus,
                encounter_data, ally_departed=ally_departed,
            ):
                continue
            option_ids = _standing_order_action_option_ids(
                clause["do"], actor_menu
            )
            if not option_ids:
                continue
            if (
                clause["do"].get("kind") == "flee"
                and any(
                    option.kind == "flee" and option.conditional_on
                    for option in actor_menu.choices
                    if option.option_id in option_ids
                )
                and not withdrawal_order_issued
            ):
                continue
            choices.append({
                "actor": actor_menu.actor.name,
                "option_ids": option_ids,
            })
            break

    candidate = {"choices": choices, "orders": compiled_order_ids}
    return candidate


def standing_orders_intent(standing_orders: Any) -> Optional[str]:
    """Return only printable, bounded optional narration context from valid orders."""
    orders = parse_standing_orders_response(standing_orders)
    if orders is None or not isinstance(orders.get("intent"), str):
        return None
    intent = " ".join(
        "".join(
        character for character in orders["intent"] if character.isprintable()
        ).split()
    )[:MAX_STANDING_ORDER_INTENT_CHARS]
    return intent or None
