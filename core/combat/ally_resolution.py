# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Resolve validated ally choices into Python-owned combat ledger entries."""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any, Optional

from core.combat.ally_controller import (
    AllyMenus,
    ValidatedAllyPlan,
)
from core.combat.cover import effective_ac_for_creature
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyAttackLedgerEntry,
    EnemyBloodiedFlag,
    EnemyCoverUpdate,
    EnemyResolutionDecline,
    EnemyResolutionLedger,
    _damage_mitigation_applies,
    _validated_attack,
    derive_enemy_batch_seed,
)


_INACTIVE_STATUSES = frozenset({
    "dead", "defeated", "departed", "fled", "surrendered", "inactive",
    "unconscious", "incapacitated", "stable",
})


def _canonical_name(value: Any) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _identity_key(identity: CombatantIdentity) -> tuple[str, str]:
    return identity.kind, _canonical_name(identity.name)


def _active(creature: Mapping[str, Any]) -> bool:
    hit_points = creature.get("currentHitPoints", creature.get("hitPoints"))
    status = creature.get("status", "alive")
    return (
        isinstance(hit_points, int)
        and not isinstance(hit_points, bool)
        and hit_points > 0
        and isinstance(status, str)
        and bool(status.strip())
        and status.strip().casefold() not in _INACTIVE_STATUSES
    )


def _decline(batch_id: str) -> EnemyResolutionDecline:
    return EnemyResolutionDecline("malformed_input", batch_id)


def resolve_ally_batch(
    menus: Any,
    plan: Any,
    encounter: Any,
    *,
    active_encounter_id: Optional[str] = None,
    combat_in_progress: bool = False,
    tactical_features: Any = None,
) -> EnemyResolutionLedger | EnemyResolutionDecline:
    """Resolve one immutable, validated ally menu without writing game state."""
    if (
        not isinstance(menus, AllyMenus)
        or not isinstance(plan, ValidatedAllyPlan)
        or not isinstance(encounter, Mapping)
        or not isinstance(encounter.get("creatures"), list)
    ):
        return _decline(menus.batch_id if isinstance(menus, AllyMenus) else "")

    encounter_id = encounter.get("encounterId", encounter.get("id"))
    round_number = encounter.get("combat_round", encounter.get("current_round", 1))
    if (
        not isinstance(encounter_id, str)
        or not encounter_id.strip()
        or not isinstance(round_number, int)
        or isinstance(round_number, bool)
        or round_number < 1
        or not isinstance(combat_in_progress, bool)
    ):
        return _decline(menus.batch_id)

    rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    for creature in encounter["creatures"]:
        if not isinstance(creature, Mapping):
            return _decline(menus.batch_id)
        name, kind = creature.get("name"), creature.get("type")
        if not isinstance(name, str) or not name.strip() or kind not in {
            "enemy", "npc", "player", "pc",
        }:
            return _decline(menus.batch_id)
        key = ("player" if kind == "pc" else kind, _canonical_name(name))
        if key in rows:
            return _decline(menus.batch_id)
        rows[key] = creature

    if len(plan.choices) != len(menus.actor_menus):
        return _decline(menus.batch_id)
    menu_by_actor = {_identity_key(menu.actor): menu for menu in menus.actor_menus}
    choice_by_actor = {}
    for choice in plan.choices:
        key = _identity_key(choice.actor)
        if key in choice_by_actor or key not in menu_by_actor:
            return _decline(menus.batch_id)
        choice_by_actor[key] = choice
    if set(choice_by_actor) != set(menu_by_actor):
        return _decline(menus.batch_id)

    target_state: dict[tuple[str, str], dict[str, Any]] = {}
    bloodied = []
    for target in menus.legal_targets:
        key = _identity_key(target)
        row = rows.get(key)
        if target.kind != "enemy" or row is None or not _active(row):
            return _decline(menus.batch_id)
        hit_points = row.get("currentHitPoints", row.get("hitPoints"))
        max_hit_points = row.get("maxHitPoints")
        armor_class = row.get("armorClass")
        if (
            not isinstance(max_hit_points, int)
            or isinstance(max_hit_points, bool)
            or max_hit_points <= 0
            or not isinstance(armor_class, int)
            or isinstance(armor_class, bool)
        ):
            return _decline(menus.batch_id)
        target_state[key] = {
            "identity": target,
            "row": row,
            "hit_points": hit_points,
            "max_hit_points": max_hit_points,
            "status": str(row.get("status", "alive")).strip(),
            "armor_class": armor_class,
        }
        bloodied.append(EnemyBloodiedFlag(
            enemy=target,
            bloodied=hit_points * 2 <= max_hit_points,
        ))

    seed = derive_enemy_batch_seed(
        {
            "encounter": encounter,
            "menus": menus,
            "plan": plan,
        },
        encounter_id=encounter_id,
        round_number=round_number,
        batch_id=menus.batch_id,
        batch_kind="ally_phase",
    )
    rng = random.Random(seed)
    entries = []
    cover_by_actor: dict[tuple[str, str], EnemyCoverUpdate] = {}

    for menu in menus.actor_menus:
        actor_key = _identity_key(menu.actor)
        actor_row = rows.get(actor_key)
        choice = choice_by_actor[actor_key]
        if actor_row is None or not _active(actor_row):
            return _decline(menus.batch_id)
        issued = {option.option_id: option for option in menu.options}
        selected = [issued.get(option_id) for option_id in choice.option_ids]
        if not selected or any(option is None for option in selected):
            return _decline(menus.batch_id)

        typed_options = [option for option in selected if option is not None]
        attack_option = next(
            (option for option in typed_options if option.kind == "attack"), None
        )
        cover_option = next(
            (option for option in typed_options if option.kind == "take_cover"), None
        )
        if choice.kind == "take_cover":
            if (
                len(typed_options) != 1
                or cover_option is None
                or cover_option.feature_id != choice.cover_feature_id
                or cover_option.cover_type != choice.cover_type
            ):
                return _decline(menus.batch_id)
        elif choice.kind == "attack":
            if (
                attack_option is None
                or attack_option.target is None
                or attack_option.attack is None
                or choice.action != attack_option.attack
                or choice.target != attack_option.target
                or len(typed_options) not in (1, 2)
                or (len(typed_options) == 2 and cover_option is None)
                or (cover_option is not None and not attack_option.attack.is_ranged)
            ):
                return _decline(menus.batch_id)
            if cover_option is not None and (
                cover_option.feature_id != choice.cover_feature_id
                or cover_option.cover_type != choice.cover_type
            ):
                return _decline(menus.batch_id)

            target_key = _identity_key(attack_option.target)
            target = target_state.get(target_key)
            if target is None:
                return _decline(menus.batch_id)
            if target["hit_points"] <= 0:
                # An earlier ally may have defeated the planned target. Select
                # the first still-active issued attack for this actor.
                attack_option = next((
                    option for option in menu.attack_options
                    if option.target is not None
                    and target_state.get(_identity_key(option.target), {}).get(
                        "hit_points", 0
                    ) > 0
                ), None)
                if attack_option is None or attack_option.attack is None:
                    return _decline(menus.batch_id)
                target_key = _identity_key(attack_option.target)
                target = target_state[target_key]

            attack = attack_option.attack
            try:
                action_name, attack_bonus, damage_bonus, dice_count, damage_type, die_sides, _ = (
                    _validated_attack({
                        "name": attack.name,
                        "attackBonus": attack.attack_bonus,
                        "damageDice": attack.damage_dice,
                        "damageBonus": attack.damage_bonus,
                        "damageType": attack.damage_type,
                    })
                )
            except Exception:
                return _decline(menus.batch_id)
            if _damage_mitigation_applies(
                {
                    key: target["row"].get(key, [])
                    for key in (
                        "damageResistances", "damageImmunities",
                        "damageVulnerabilities", "damage_resistances",
                        "damage_immunities", "damage_vulnerabilities",
                    )
                    if target["row"].get(key) not in (None, [], "")
                },
                damage_type,
            ):
                return _decline(menus.batch_id)

            ac = effective_ac_for_creature(
                target["armor_class"],
                target["row"],
                encounter_id=encounter_id,
                active_encounter_id=active_encounter_id,
                combat_in_progress=combat_in_progress,
                tactical_features=tactical_features,
            )
            d20 = rng.randint(1, 20)
            attack_total = d20 + attack_bonus
            critical = d20 == 20
            hit = critical or (d20 != 1 and attack_total >= ac)
            dice_rolls = ()
            damage_total = 0
            hp_before = target["hit_points"]
            if hit:
                roll_count = dice_count * (2 if critical else 1)
                dice_rolls = tuple(rng.randint(1, die_sides) for _ in range(roll_count))
                damage_total = max(0, sum(dice_rolls) + damage_bonus)
                target["hit_points"] = max(0, hp_before - damage_total)
                target["status"] = (
                    "defeated" if target["hit_points"] == 0 else "alive"
                )
            entries.append(EnemyAttackLedgerEntry(
                actor=menu.actor,
                action_name=action_name,
                target=target["identity"],
                d20=d20,
                attack_total=attack_total,
                armor_class=ac,
                hit=hit,
                critical=critical,
                damage_dice_rolls=dice_rolls,
                damage_total=damage_total,
                damage_type=damage_type,
                target_hp_before=hp_before,
                target_hp_after=target["hit_points"],
                target_status_after=target["status"],
                target_max_hp=target["max_hit_points"],
                action_is_ranged=attack.is_ranged,
            ))
        else:
            return _decline(menus.batch_id)

        if cover_option is not None:
            cover_by_actor[actor_key] = EnemyCoverUpdate(
                enemy=menu.actor,
                feature_id=cover_option.feature_id,
                cover_type=cover_option.cover_type,
            )

    return EnemyResolutionLedger(
        encounter_id=encounter_id.strip(),
        round_number=round_number,
        batch_id=menus.batch_id,
        batch_kind="ally_phase",
        seed=seed,
        entries=tuple(entries),
        bloodied=tuple(bloodied),
        cover_updates=tuple(cover_by_actor[key] for key in sorted(cover_by_actor)),
    )
