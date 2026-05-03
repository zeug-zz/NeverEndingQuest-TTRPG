# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Character State Hygiene - deterministic life-state normalization.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from typing import Any, Dict, List


def is_mechanically_dead(character_data: Dict[str, Any]) -> bool:
    """Check if character is mechanically dead (status='dead' or 3 death save failures).

    This is the authoritative check -- even if HP > 0, a character with
    explicit status='dead' or deathSaves.failures >= 3 is mechanically dead.
    Only an explicit resurrection action should clear this state.
    """
    if not isinstance(character_data, dict):
        return False
    status = str(character_data.get("status") or "").strip().lower()
    if status == "dead":
        return True
    death_saves_raw = character_data.get("deathSaves")
    if isinstance(death_saves_raw, dict):
        failures = _coerce_int(death_saves_raw.get("failures", 0), 0)
    else:
        failures = _coerce_int(character_data.get("deathSaveFailures", 0), 0)
    return failures >= 3


def _coerce_int(value: Any, default: int = 0) -> int:
    """Convert a value to int with safe fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_conditions(raw_conditions: Any) -> List[str]:
    """Return lowercase, deduped conditions preserving order."""
    if not isinstance(raw_conditions, list):
        return []

    normalized: List[str] = []
    seen = set()
    for condition in raw_conditions:
        condition_text = str(condition or "").strip().lower()
        if not condition_text or condition_text in seen:
            continue
        normalized.append(condition_text)
        seen.add(condition_text)
    return normalized


def normalize_life_state_fields(character_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize HP, status, condition, and death-save coherence."""
    if not isinstance(character_data, dict):
        return character_data

    current_hp = _coerce_int(character_data.get("hitPoints", 0), 0)
    status = str(character_data.get("status") or "alive").strip().lower()
    condition = str(character_data.get("condition") or "none").strip().lower()
    if condition == "normal":
        condition = "none"

    conditions = _normalize_conditions(character_data.get("condition_affected", []))

    death_saves_raw = character_data.get("deathSaves")
    if isinstance(death_saves_raw, dict):
        successes = max(0, min(_coerce_int(death_saves_raw.get("successes", 0), 0), 3))
        failures = max(0, min(_coerce_int(death_saves_raw.get("failures", 0), 0), 3))
    else:
        successes = max(0, min(_coerce_int(character_data.get("deathSaveSuccesses", 0), 0), 3))
        failures = max(0, min(_coerce_int(character_data.get("deathSaveFailures", 0), 0), 3))

    # Dead-state authority: explicit death or 3 failed death saves wins
    # over positive HP. Only an explicit resurrection action should
    # clear this state.
    if status == "dead" or failures >= 3:
        character_data["hitPoints"] = 0
        status = "dead"
        condition = "none"
        conditions = []
        failures = max(failures, 3)
        successes = 0
    elif current_hp > 0:
        status = "alive"
        successes = 0
        failures = 0
        conditions = [entry for entry in conditions if entry != "unconscious"]
        if condition == "unconscious":
            condition = conditions[0] if conditions else "none"
        elif condition == "none" and conditions:
            condition = conditions[0]
    else:
        status = "unconscious"
        condition = "unconscious"
        if "unconscious" not in conditions:
            conditions.append("unconscious")

    if condition != "none" and condition not in conditions:
        conditions.insert(0, condition)
    if condition == "none" and conditions:
        condition = conditions[0]

    character_data["status"] = status
    character_data["condition"] = condition
    character_data["condition_affected"] = conditions
    character_data["deathSaves"] = {
        "successes": successes,
        "failures": failures,
    }
    normalize_supernatural_state_fields(character_data)
    return character_data


def _normalize_creature_types(raw_creature_types: Any) -> List[str]:
    """Return lowercase, deduped creature type list preserving order."""
    if isinstance(raw_creature_types, str):
        raw_values = [raw_creature_types]
    elif isinstance(raw_creature_types, list):
        raw_values = raw_creature_types
    else:
        return []

    normalized: List[str] = []
    seen = set()
    for value in raw_values:
        value_text = str(value or "").strip().lower()
        if not value_text or value_text in seen:
            continue
        normalized.append(value_text)
        seen.add(value_text)
    return normalized


def _split_supernatural_consequence(consequence: str) -> Dict[str, List[str]]:
    """Classify legacy consequence text into mechanical vs narrative buckets."""
    lower_text = consequence.lower()
    mechanical_markers = (
        "resistance",
        "vulnerability",
        "immune",
        "disadvantage",
        "advantage",
        "saving throw",
        "check",
        "damage",
        "speed",
        "ac",
        "hit point",
    )
    if any(marker in lower_text for marker in mechanical_markers):
        return {"mechanical": [consequence], "narrative": []}
    return {"mechanical": [], "narrative": [consequence]}


def _normalize_supernatural_state_record(raw_state: Any) -> Dict[str, Any]:
    """Normalize one supernatural state record to schema-compatible shape."""
    if not isinstance(raw_state, dict):
        return {}

    state_id = str(raw_state.get("id") or "").strip().lower().replace(" ", "_")
    label = str(raw_state.get("label") or "").strip()
    category = str(raw_state.get("category") or "other").strip().lower()
    source = str(raw_state.get("source") or "").strip()
    playable = bool(raw_state.get("playable", True))
    removal = str(raw_state.get("removal") or "").strip()

    if not state_id and label:
        state_id = label.lower().replace(" ", "_")
    if not label and state_id:
        label = state_id.replace("_", " ").title()
    if not state_id:
        return {}

    mechanical_effects: List[str] = []
    narrative_effects: List[str] = []

    raw_mechanical = raw_state.get("mechanicalEffects", [])
    if isinstance(raw_mechanical, list):
        for effect in raw_mechanical:
            text = str(effect or "").strip()
            if text and text not in mechanical_effects:
                mechanical_effects.append(text)

    raw_narrative = raw_state.get("narrativeEffects", [])
    if isinstance(raw_narrative, list):
        for effect in raw_narrative:
            text = str(effect or "").strip()
            if text and text not in narrative_effects:
                narrative_effects.append(text)

    normalized = {
        "id": state_id,
        "label": label,
        "category": category,
        "source": source,
        "playable": playable,
        "mechanicalEffects": mechanical_effects,
        "narrativeEffects": narrative_effects,
        "removal": removal,
    }
    return normalized


def _migrate_legacy_supernatural_metadata(character_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert legacy _supernatural_metadata into schema-compatible state records."""
    legacy = character_data.get("_supernatural_metadata")
    if not isinstance(legacy, dict):
        return []

    mode = str(legacy.get("resurrection_mode") or "").strip().lower()
    source = str(legacy.get("resurrection_source") or "").strip()
    consequences = legacy.get("resurrection_consequences", [])
    if not isinstance(consequences, list):
        consequences = []

    category = "transformation"
    label = "Resurrection Alteration"
    state_id = "resurrection_alteration"
    if mode == "corrupted_resurrection":
        category = "corruption"
        label = "Corrupted Resurrection"
        state_id = "corrupted_resurrection"
    elif mode == "undead_resurrection":
        category = "undeath"
        label = "Undead Resurrection"
        state_id = "undead_resurrection"

    mechanical_effects: List[str] = []
    narrative_effects: List[str] = []
    for consequence in consequences:
        text = str(consequence or "").strip()
        if not text:
            continue
        split = _split_supernatural_consequence(text)
        for mechanical in split["mechanical"]:
            if mechanical not in mechanical_effects:
                mechanical_effects.append(mechanical)
        for narrative in split["narrative"]:
            if narrative not in narrative_effects:
                narrative_effects.append(narrative)

    migrated_state = {
        "id": state_id,
        "label": label,
        "category": category,
        "source": source,
        "playable": True,
        "mechanicalEffects": mechanical_effects,
        "narrativeEffects": narrative_effects,
        "removal": "",
    }
    normalized = _normalize_supernatural_state_record(migrated_state)
    if not normalized:
        return []
    return [normalized]


def normalize_supernatural_state_fields(character_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize creatureTypes/supernaturalStates and migrate legacy metadata."""
    if not isinstance(character_data, dict):
        return character_data

    creature_types = _normalize_creature_types(character_data.get("creatureTypes", []))
    if creature_types:
        character_data["creatureTypes"] = creature_types
    elif "creatureTypes" in character_data:
        character_data["creatureTypes"] = []

    raw_states = character_data.get("supernaturalStates", [])
    normalized_states: List[Dict[str, Any]] = []
    seen_ids = set()
    if isinstance(raw_states, list):
        for raw_state in raw_states:
            normalized = _normalize_supernatural_state_record(raw_state)
            state_id = normalized.get("id")
            if not state_id or state_id in seen_ids:
                continue
            normalized_states.append(normalized)
            seen_ids.add(state_id)

    legacy_states = _migrate_legacy_supernatural_metadata(character_data)
    for migrated in legacy_states:
        state_id = migrated.get("id")
        if not state_id or state_id in seen_ids:
            continue
        normalized_states.append(migrated)
        seen_ids.add(state_id)

    if normalized_states:
        character_data["supernaturalStates"] = normalized_states
    elif "supernaturalStates" in character_data:
        character_data["supernaturalStates"] = []

    if "_supernatural_metadata" in character_data:
        del character_data["_supernatural_metadata"]

    if any(state.get("category") == "undeath" for state in normalized_states):
        if "undead" not in character_data.get("creatureTypes", []):
            character_data.setdefault("creatureTypes", [])
            character_data["creatureTypes"].append("undead")
            character_data["creatureTypes"] = _normalize_creature_types(character_data["creatureTypes"])

    return character_data


def add_or_update_supernatural_state(character_data: Dict[str, Any], state_record: Dict[str, Any]) -> Dict[str, Any]:
    """Add or replace a supernatural state by id, then normalize fields."""
    if not isinstance(character_data, dict):
        return character_data

    normalized_state = _normalize_supernatural_state_record(state_record)
    if not normalized_state:
        return normalize_supernatural_state_fields(character_data)

    existing = character_data.get("supernaturalStates", [])
    if not isinstance(existing, list):
        existing = []

    replaced = False
    for index, current in enumerate(existing):
        if not isinstance(current, dict):
            continue
        if str(current.get("id") or "").strip().lower() == normalized_state["id"]:
            existing[index] = normalized_state
            replaced = True
            break
    if not replaced:
        existing.append(normalized_state)

    character_data["supernaturalStates"] = existing
    return normalize_supernatural_state_fields(character_data)


def get_supernatural_state_summary(character_data: Dict[str, Any], include_effects: bool = False) -> str:
    """Build compact one-line supernatural state summary for prompts/UI."""
    if not isinstance(character_data, dict):
        return ""

    creature_types = _normalize_creature_types(character_data.get("creatureTypes", []))
    states = character_data.get("supernaturalStates", [])
    if not isinstance(states, list):
        states = []

    labels: List[str] = []
    effects: List[str] = []
    for state in states:
        if not isinstance(state, dict):
            continue
        label = str(state.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
        if include_effects:
            raw_effects = state.get("mechanicalEffects", [])
            if isinstance(raw_effects, list):
                for effect in raw_effects:
                    effect_text = str(effect or "").strip()
                    if effect_text and effect_text not in effects:
                        effects.append(effect_text)
                    if len(effects) >= 2:
                        break
        if include_effects and len(effects) >= 2:
            break

    if not creature_types and not labels:
        return ""

    parts: List[str] = []
    if creature_types:
        parts.append(f"types={','.join(creature_types)}")
    if labels:
        parts.append(f"states={'; '.join(labels)}")
    if include_effects and effects:
        parts.append(f"effects={'; '.join(effects)}")
    return " | ".join(parts)
