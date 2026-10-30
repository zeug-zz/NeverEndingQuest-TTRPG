# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Shared, fail-closed encounter cover and ranged-weapon contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Optional


_COVER_BONUSES = {"half": 2, "three_quarters": 5}
_RANGED_WEAPON_NAMES = frozenset({
    "shortbow",
    "longbow",
    "light crossbow",
    "heavy crossbow",
    "hand crossbow",
    "sling",
    "dart",
})
_RANGED_EXPLICIT_VALUES = frozenset({
    "ranged", "ranged attack", "ranged weapon attack", "weapon attack ranged",
})
_MELEE_EXPLICIT_VALUES = frozenset({
    "melee", "melee attack", "melee weapon attack", "weapon attack melee",
})


def cover_label(cover_type: Any) -> Optional[str]:
    """Return the player-facing label for a recognized cover type."""
    if cover_type == "half":
        return "half cover"
    if cover_type == "three_quarters":
        return "three-quarters cover"
    return None


def _feature_matches(
    cover_feature_id: Any,
    cover_type: Any,
    tactical_features: Any,
    combatant_kind: Any,
) -> bool:
    if (
        not isinstance(cover_feature_id, str)
        or not cover_feature_id.strip()
        or len(cover_feature_id) > 128
        or not isinstance(tactical_features, list)
    ):
        return False
    matches = [
        feature for feature in tactical_features
        if isinstance(feature, Mapping)
        and feature.get("featureId") == cover_feature_id
    ]
    if len(matches) != 1:
        return False
    feature = matches[0]
    usable_by = feature.get("usableBy")
    allowed_kinds = {"enemy", "player", "npc"}
    return bool(
        feature.get("kind") == "cover"
        and feature.get("coverType") == cover_type
        and isinstance(feature.get("name"), str)
        and feature.get("name", "").strip()
        and isinstance(usable_by, list)
        and isinstance(combatant_kind, str)
        and combatant_kind in allowed_kinds
        and combatant_kind in usable_by
        and all(isinstance(item, str) and item in allowed_kinds for item in usable_by)
    )


def effective_ac(
    base_ac: Any,
    cover_type: Any = None,
    *,
    cover_feature_id: Any = None,
    encounter_id: Any = None,
    active_encounter_id: Any = None,
    combat_in_progress: bool = False,
    tactical_features: Any = None,
    combatant_kind: Any = None,
) -> Any:
    """Calculate base AC plus one valid cover bonus, or return base AC.

    All contextual checks are fail-closed. In particular, a cover reference is
    inert unless the matching encounter is explicitly active, combat is in
    progress, and the referenced feature remains authored for that combatant.
    """
    if (
        isinstance(base_ac, bool)
        or not isinstance(base_ac, int)
        or not isinstance(cover_type, str)
        or cover_type not in _COVER_BONUSES
        or not isinstance(encounter_id, str)
        or not encounter_id.strip()
        or not isinstance(active_encounter_id, str)
        or active_encounter_id.strip() != encounter_id.strip()
        or combat_in_progress is not True
        or not _feature_matches(
            cover_feature_id, cover_type, tactical_features, combatant_kind
        )
    ):
        return base_ac
    return base_ac + _COVER_BONUSES[cover_type]


def effective_ac_for_creature(
    base_ac: Any,
    creature: Any,
    *,
    encounter_id: Any,
    active_encounter_id: Any,
    combat_in_progress: bool,
    tactical_features: Any,
) -> Any:
    """Apply :func:`effective_ac` to one encounter creature mapping."""
    if not isinstance(creature, Mapping):
        return base_ac
    return effective_ac(
        base_ac,
        creature.get("coverType"),
        cover_feature_id=creature.get("coverFeatureId"),
        encounter_id=encounter_id,
        active_encounter_id=active_encounter_id,
        combat_in_progress=combat_in_progress,
        tactical_features=tactical_features,
        combatant_kind=creature.get("type"),
    )


def _normalize_action_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return " ".join(normalized.split())


def is_authorized_ranged_action(action_name: Any, action_data: Any = None) -> bool:
    """Classify only explicit ranged metadata or an unambiguous SRD weapon name.

    Unknown actions and the ambiguous javelin default to melee. Authored
    metadata has precedence over the small supported-name allowlist.
    """
    if isinstance(action_data, Mapping):
        for key in (
            "attackType", "attack_type", "rangeType", "range_type",
            "weaponType", "weapon_type", "type",
        ):
            if key not in action_data:
                continue
            value = action_data.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = _normalize_action_text(value)
            if normalized in _RANGED_EXPLICIT_VALUES:
                return True
            if normalized in _MELEE_EXPLICIT_VALUES:
                return False
        range_data = action_data.get("range")
        if isinstance(range_data, Mapping) and (
            "normal" in range_data or "long" in range_data
        ):
            return True

    normalized_name = _normalize_action_text(action_name)
    return normalized_name in _RANGED_WEAPON_NAMES
