# SPDX-FileCopyrightText: 2026 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat PC Phase Natural-Language Action Parser
Copyright (c) 2026 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.

Conservative deterministic parser for multi-PC PC_PHASE natural-language actions.
Only handles complete, unambiguous actions. Falls back to full combat LLM on uncertainty.
"""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from utils.character_state_hygiene import is_mechanically_dead
from utils.pc_manager import get_character_state

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CANONICAL_PUNCTUATION = re.compile(r"[,;:.!?'\"]+")
_WHITESPACE = re.compile(r"\s+")
_ARTICLE_PREFIX = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_INT_SEARCH = re.compile(r"\b(\d+)\b")
_D20_ROLL = re.compile(r"\b(?:roll(?:ed)?|to\s*hit|attack\s*roll|hit\s*with)\s*(?:\s*of\s*)?(\d{1,2})\b", re.IGNORECASE)
_STANDALONE_D20 = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")
_HEAL_PATTERN = re.compile(
    r"\b(cure\s*wounds|heal(?:ing)?|healing\s*word|prayer\s*of\s*healing|lay\s*on\s*hands|goodberry)\b",
    re.IGNORECASE,
)
_MAGIC_MISSILE = re.compile(r"\b(magic\s*missile|missile)\b", re.IGNORECASE)
_MOVEMENT_VERBS = re.compile(
    r"\b(move|step|walk|run|advance|retreat|withdraw|approach|circle|dash|disengage|sprint)\b",
    re.IGNORECASE,
)
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(attack|hit|shoot|slash|stab|fire|cast|spell|damage|strike|smite|punch|kick)\b",
    re.IGNORECASE,
)
_ALLOCATION_SEGMENT = re.compile(
    r"(\d+)\s+(?:to|on|at|into)\s+([A-Za-z][A-Za-z\s'-]*)"
)
_TARGET_TAKES_DAMAGE = re.compile(
    r"([A-Za-z][A-Za-z\s'-]*?)\s+(?:takes?|receives?)\s+(\d+)",
    re.IGNORECASE,
)


def _canonicalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    t = text.lower()
    t = _CANONICAL_PUNCTUATION.sub("", t)
    t = _WHITESPACE.sub(" ", t).strip()
    return t


def _normalize_name(text: str) -> str:
    """Combat-identity normalization for name matching."""
    t = text.lower().strip()
    t = t.replace(" ", "_")
    t = t.replace("'", "_")
    t = _CANONICAL_PUNCTUATION.sub("", t)
    t = _WHITESPACE.sub("_", t).strip("_")
    return t


def _strip_article(text: str) -> str:
    """Remove leading article for fuzzy matching."""
    return _ARTICLE_PREFIX.sub("", text).strip()


def _pick_template(seed_parts: List[Any], templates: List[str]) -> str:
    """Deterministic template selection identical to multi_pc_combat logic."""
    if not templates:
        return ""
    seed = "|".join(str(p or "") for p in seed_parts)
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    return templates[digest[0] % len(templates)]


def _load_authoritative_character_state(character_name: str) -> Optional[Dict[str, Any]]:
    """Load authoritative character data when available."""
    try:
        return get_character_state(character_name)
    except Exception:
        return None


def _spell_slot_level_number(level_key: str) -> Optional[int]:
    """Extract a numeric spell slot level from a spellSlots key."""
    match = re.search(r"(\d+)", str(level_key or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _choose_lowest_available_spell_slot(character_data: Dict[str, Any]) -> Optional[str]:
    """Choose the lowest available spell slot key or None if unavailable."""
    if not isinstance(character_data, dict):
        return None
    spellcasting = character_data.get("spellcasting", {})
    if not isinstance(spellcasting, dict):
        return None
    spell_slots = spellcasting.get("spellSlots", {})
    if not isinstance(spell_slots, dict):
        return None

    available_levels: List[Tuple[int, str]] = []
    for level_key, slot_data in spell_slots.items():
        if not isinstance(slot_data, dict):
            continue
        level_num = _spell_slot_level_number(level_key)
        if level_num is None:
            continue
        try:
            current = int(slot_data.get("current", 0))
            maximum = int(slot_data.get("max", 0))
        except (TypeError, ValueError):
            continue
        if current > 0 and maximum > 0:
            available_levels.append((level_num, f"level{level_num}"))

    if not available_levels:
        return None

    available_levels.sort(key=lambda item: item[0])
    return available_levels[0][1]


def _parse_int(text: str) -> Optional[int]:
    """Return the first integer found in text, or None."""
    m = _INT_SEARCH.search(text)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None
    return None


def _extract_ints(text: str) -> List[int]:
    """Return all integers found in text."""
    return [int(m) for m in _INT_SEARCH.findall(text) if m]


# ---------------------------------------------------------------------------
# Target candidate resolution
# ---------------------------------------------------------------------------

_TargetInfo = Dict[str, Any]


def _build_target_candidates(
    encounter_data: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
) -> List[_TargetInfo]:
    """Build a list of candidate targets from encounter creatures and party members."""
    candidates: List[_TargetInfo] = []
    seen_normalized: set = set()

    # Add encounter creatures
    for creature in encounter_data.get("creatures", []):
        name = str(creature.get("name", "")).strip()
        if not name:
            continue
        norm = _normalize_name(name)
        if norm in seen_normalized:
            continue
        seen_normalized.add(norm)
        creature_type = str(creature.get("type", "")).strip().lower()
        candidates.append({
            "name": name,
            "normalized": norm,
            "canonical": _canonicalize(name),
            "type": creature_type,
            "hp": creature.get("currentHitPoints", 999),
            "max_hp": creature.get("maxHitPoints", 999),
            "ac": creature.get("armorClass", 10),
            "status": str(creature.get("status", "alive")).lower(),
            "source": "encounter",
        })

    # Add party members not already in candidates
    party_members = party_tracker_data.get("partyMembers", [])
    for member_name in party_members:
        safe_name = str(member_name or "").strip()
        if not safe_name:
            continue
        norm = _normalize_name(safe_name)
        if norm in seen_normalized:
            continue
        seen_normalized.add(norm)
        candidates.append({
            "name": safe_name,
            "normalized": norm,
            "canonical": _canonicalize(safe_name),
            "type": "player",
            "hp": None,
            "max_hp": None,
            "ac": None,
            "status": "unknown",
            "source": "party",
        })

    return candidates


def _unique_match(
    raw_text: str,
    candidates: List[_TargetInfo],
) -> Optional[_TargetInfo]:
    """Resolve raw_text to exactly one target candidate, or None if ambiguous."""
    query_raw = raw_text.strip()
    if not query_raw:
        return None

    query_canonical = _canonicalize(query_raw)
    query_norm = _normalize_name(query_raw)
    query_stripped = _canonicalize(_strip_article(query_raw))

    # Exact normalized match
    exact = [c for c in candidates if c["normalized"] == query_norm]
    if len(exact) == 1:
        return exact[0]

    # Strict canonical match (after article removal)
    strict = [c for c in candidates if _canonicalize(_strip_article(c["canonical"])) == query_stripped]
    if len(strict) == 1:
        return strict[0]

    # Contains match (one candidate's canonical contains the query)
    contains = [c for c in candidates if query_canonical in c["canonical"]]
    if len(contains) == 1:
        return contains[0]

    # Query contains candidate name
    contained_by = [c for c in candidates if c["canonical"] in query_canonical]
    if len(contained_by) == 1:
        return contained_by[0]

    return None


# ---------------------------------------------------------------------------
# Action detection helpers
# ---------------------------------------------------------------------------

def _has_attack_roll(text: str) -> Optional[int]:
    """Return the attack roll if a d20 roll is explicitly supplied, else None."""
    m = _D20_ROLL.search(text)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None

    # Fallback: standalone number between 1-20 after attack-related context
    if re.search(r"\b(?:attack|hit|shoot|strike|slash|stab)\b", text, re.IGNORECASE):
        numbers = _extract_ints(text)
        if len(numbers) == 1 and 1 <= numbers[0] <= 20:
            return numbers[0]

    return None


def _extract_weapon_flavor(text: str, known_weapon_words: Optional[List[str]] = None) -> Optional[str]:
    """Extract weapon or flavor text after 'with' or 'using'."""
    m = re.search(r"\b(?:with|using)\s+(.+?)(?:\.|,|$|\s+at\s+|\s+against\s+|\s+roll(?:ed)?\s+|\s+for\s+)", text, re.IGNORECASE)
    if m:
        weapon = m.group(1).strip()
        if weapon and len(weapon) < 40:
            # Strip trailing spaces and stopwords
            weapon = weapon.strip()
            return weapon
    return None


def _is_healing_action(text: str) -> bool:
    """Check if the text describes a healing action."""
    return bool(_HEAL_PATTERN.search(text))


def _is_magic_missile_action(text: str) -> bool:
    """Check if the text describes a Magic Missile action."""
    return bool(_MAGIC_MISSILE.search(text))


def _is_movement_only(text: str) -> bool:
    """Check if text is movement-only (no attack/spell/damage keywords)."""
    has_movement = bool(_MOVEMENT_VERBS.search(text))
    has_forbidden = bool(_FORBIDDEN_KEYWORDS.search(text))
    has_number = bool(_INT_SEARCH.search(text))
    return has_movement and not has_forbidden and not has_number


def _parse_heal_amount(text: str) -> Optional[int]:
    """Extract healing amount from text."""
    # Look for patterns like "for X", "X HP", "X points"
    heal_patterns = [
        re.compile(r"\b(\d+)\s*(?:HP|hit\s*points|points?)?\s*(?:of\s*heal(?:ing)?)?", re.IGNORECASE),
    ]
    for pat in heal_patterns:
        m = pat.search(text)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                return None

    numbers = _extract_ints(text)
    # In healing context, pick the first plausible number (1-999)
    for n in numbers:
        if 1 <= n <= 999:
            return n
    return None


def _parse_magic_missile_allocations(text: str) -> Optional[List[Dict[str, Any]]]:
    """Parse explicit Magic Missile dart allocations.

    Expects patterns like "2 darts to Goblin, 1 dart to Orc"
    or "Magic Missile: Goblin 3, Orc 2"
    Returns list of {target, damage} or None if ambiguous.
    """
    # Try structured allocation: <number> to/on/at <target>
    segments = _ALLOCATION_SEGMENT.findall(text)
    if segments:
        allocations = []
        for damage_str, target_str in segments:
            try:
                damage = int(damage_str)
            except (TypeError, ValueError):
                return None
            if damage < 1 or damage > 99:
                return None
            allocations.append({"target_raw": target_str.strip(), "damage": damage})

        if allocations:
            return allocations

    return None


# ---------------------------------------------------------------------------
# Main parse entry point
# ---------------------------------------------------------------------------

def parse_pc_phase_action(
    text: str,
    encounter_data: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    actor_name: str = "Player",
) -> Dict[str, Any]:
    """Parse a natural-language PC_PHASE action and return a parse result dict.

    Returns dict with keys:
        handled (bool): True if the action was fully parsed and can be applied
        kind (str): Action kind for routing
        mechanical_feedback (Optional[str]): [skipTTS] prefixed operator report
        spoken_narration (Optional[str]): DM Voice narration (no [skipTTS])
        log_msg (Optional[str]): History injection for LLM context
        ledger_event (Optional[dict]): Event for PC_PHASE event ledger
        fallback_reason (str): Reason if not handled
        target_name (Optional[str]): Resolved target name
        parsed_attack_roll (Optional[int]): Supplied attack roll
        parsed_heal_amount (Optional[int]): Supplied healing amount
        weapon_name (Optional[str]): Weapon/flavor text
        character_updates (List[dict]): list of {characterName, ops, changes} for updateCharacterInfo calls
        encounter_ops (List[dict]): updateEncounter ops for enemy changes (with creature field)
        changes_text (str): Prose mirror for ops
    """
    result: Dict[str, Any] = {
        "handled": False,
        "kind": "",
        "mechanical_feedback": None,
        "spoken_narration": None,
        "log_msg": None,
        "ledger_event": None,
        "fallback_reason": "",
        "target_name": None,
        "parsed_attack_roll": None,
        "parsed_heal_amount": None,
        "weapon_name": None,
        "character_updates": [],
        "encounter_ops": [],
        "changes_text": "",
    }

    clean = text.strip()
    if not clean:
        result["fallback_reason"] = "empty_input"
        return result

    candidates = _build_target_candidates(encounter_data, party_tracker_data)
    lower = clean.lower()

    # --- Magic Missile ---
    if _is_magic_missile_action(lower):
        allocations = _parse_magic_missile_allocations(clean)
        if not allocations:
            result["fallback_reason"] = "mm_unclear_allocation"
            return result

        caster_state = _load_authoritative_character_state(actor_name)
        if not caster_state:
            result["fallback_reason"] = "mm_casting_state_unavailable"
            return result

        slot_key = _choose_lowest_available_spell_slot(caster_state)
        if not slot_key:
            result["fallback_reason"] = "mm_slot_unavailable"
            return result

        # Resolve each allocation target uniquely
        for alloc in allocations:
            target = _unique_match(alloc["target_raw"], candidates)
            if not target:
                result["fallback_reason"] = f"mm_ambiguous_target:{alloc['target_raw']}"
                return result
            alloc["target"] = target

        slot_level_num = _spell_slot_level_number(slot_key) or 1
        slot_label = f"level {slot_level_num}"

        # All allocations resolved. Build ops.
        encounter_ops: List[Dict] = []
        character_updates: List[Dict] = []
        changes_parts: List[str] = []
        for alloc in allocations:
            tgt = alloc["target"]
            dmg = alloc["damage"]
            tgt_name = tgt["name"]
            tgt_type = tgt["type"]
            if tgt_type == "enemy":
                encounter_ops.append({"op": "hp_delta", "creature": tgt_name, "delta": -dmg})
            else:
                character_updates.append({
                    "characterName": tgt_name,
                    "ops": [{"op": "hp_delta", "delta": -dmg}],
                    "changes": f"{tgt_name} takes {dmg} force damage",
                })
            changes_parts.append(f"{tgt_name} takes {dmg} force damage")

        if slot_key:
            character_updates.append({
                "characterName": actor_name,
                "ops": [{"op": "spell_slot_delta", "level": slot_key, "delta": -1}],
                "changes": f"Expended a {slot_label} spell slot",
            })
            changes_parts.append(f"{actor_name} expended a {slot_label} spell slot")

        changes_text = ". ".join(changes_parts) + "."
        narration = _pick_template(
            [actor_name, "magic_missile", len(allocations)],
            [
                f"{actor_name} gestures and arcane darts streak unerringly to their marks.",
                f"Silvery darts fly from {actor_name}'s hand, each finding its target with precision.",
                f"{actor_name} speaks the incantation, and shimmering missiles race unerringly home.",
            ],
        )

        total_dmg = sum(a["damage"] for a in allocations)
        target_list = ", ".join(a["target"]["name"] for a in allocations)

        result.update({
            "handled": True,
            "kind": "magic_missile",
            "mechanical_feedback": f"[skipTTS] Dungeon Master: Magic Missile applied. {changes_text}",
            "spoken_narration": f"Dungeon Master: {narration}",
            "log_msg": f"[ALREADY_APPLIED] [System: {actor_name} cast Magic Missile. {changes_text}]",
            "encounter_ops": encounter_ops,
            "character_updates": character_updates,
            "changes_text": changes_text,
            "ledger_event": {
                "kind": "spell_damage",
                "facts": {
                    "damage_per_dart": [a["damage"] for a in allocations],
                    "targets": target_list,
                    "total_damage": total_dmg,
                    "slot_level": slot_key,
                },
            },
        })
        return result

    # --- Healing ---
    if _is_healing_action(lower):
        heal_amount = _parse_heal_amount(clean)
        if heal_amount is None:
            result["fallback_reason"] = "heal_unclear_amount"
            return result

        # Resolve target from text
        # Try "on <target>", "<target> for <n>", "heal <target>"
        target_raw = None
        for pat in [
            re.compile(r"\b(?:on|for)\s+([A-Za-z][A-Za-z\s'-]+?)(?:\s+for|\s+with|\s*$)", re.IGNORECASE),
            re.compile(r"\b(?:heal(?:ing)?|cure)\s+([A-Za-z][A-Za-z\s'-]+?)(?:\s+for|\s*$)", re.IGNORECASE),
            re.compile(r"^([A-Za-z][A-Za-z\s'-]+?)\s+(?:takes?\s+)?heal(?:ing)?", re.IGNORECASE),
        ]:
            m = pat.search(clean)
            if m:
                candidate = m.group(1).strip()
                if candidate and len(candidate) < 40:
                    target_raw = candidate
                    break

        if target_raw is None:
            result["fallback_reason"] = "heal_unclear_target"
            return result

        target = _unique_match(target_raw, candidates)
        if not target:
            result["fallback_reason"] = f"heal_ambiguous_target:{target_raw}"
            return result

        if target.get("type") != "enemy":
            authoritative_target_state = _load_authoritative_character_state(target["name"])
            if not authoritative_target_state:
                result["fallback_reason"] = "heal_target_state_unavailable"
                return result
            if is_mechanically_dead(authoritative_target_state):
                result.update({
                    "handled": True,
                    "kind": "healing_dead_rejected",
                    "mechanical_feedback": (
                        f"[skipTTS] Dungeon Master: [SYSTEM] {target['name']} is dead and cannot be healed "
                        f"by ordinary magic. A resurrection effect is required."
                    ),
                    "spoken_narration": None,
                    "log_msg": None,
                    "changes_text": "",
                    "ledger_event": None,
                })
                result["fallback_reason"] = "heal_dead_target"
                return result

        # Detect spell casting for slot spend
        has_spell_indicator = bool(re.search(r"\b(cure\s*wounds|healing\s*word|prayer|lay\s*on\s*hands|spell|cast)\b", lower))
        caster_slot_key = None
        if has_spell_indicator:
            caster_state = _load_authoritative_character_state(actor_name)
            if not caster_state:
                result["fallback_reason"] = "heal_casting_state_unavailable"
                return result
            caster_slot_key = _choose_lowest_available_spell_slot(caster_state)
            if not caster_slot_key:
                result["fallback_reason"] = "heal_slot_unavailable"
                return result

        character_updates = [{
            "characterName": target["name"],
            "ops": [{"op": "hp_delta", "delta": heal_amount}],
            "changes": f"Healed for {heal_amount} HP",
        }]
        if caster_slot_key:
            slot_level_num = _spell_slot_level_number(caster_slot_key) or 1
            character_updates.append({
                "characterName": actor_name,
                "ops": [{"op": "spell_slot_delta", "level": caster_slot_key, "delta": -1}],
                "changes": f"Expended a level {slot_level_num} spell slot",
            })

        changes_text = f"{target['name']} healed for {heal_amount} HP"
        if caster_slot_key:
            slot_level_num = _spell_slot_level_number(caster_slot_key) or 1
            changes_text += f", {actor_name} expended a level {slot_level_num} spell slot"

        narration = _pick_template(
            [actor_name, "healing", target["name"], heal_amount],
            [
                f"{actor_name}'s hands glow with warm light as {target['name']}'s wounds begin to close.",
                f"A warm radiance flows from {actor_name} into {target['name']}, mending injuries.",
                f"{target['name']} draws a steadying breath as healing energy washes over them.",
            ],
        )

        result.update({
            "handled": True,
            "kind": "healing",
            "mechanical_feedback": f"[skipTTS] Dungeon Master: Healing applied. {changes_text}.",
            "spoken_narration": f"Dungeon Master: {narration}",
            "log_msg": f"[ALREADY_APPLIED] [System: {actor_name} healed {target['name']} for {heal_amount}. {changes_text}]",
            "character_updates": character_updates,
            "changes_text": changes_text,
            "target_name": target["name"],
            "parsed_heal_amount": heal_amount,
            "ledger_event": {
                "kind": "spell_healing",
                "facts": {"amount": heal_amount, "slots_spent": 1 if caster_slot_key else 0},
            },
        })
        return result

    # --- Movement-only ---
    if _is_movement_only(lower):
        # Extract a clean movement phrase
        verb_match = _MOVEMENT_VERBS.search(clean)
        movement_phrase = verb_match.group(0) if verb_match else "moves"

        narration = _pick_template(
            [actor_name, "movement", clean],
            [
                f"{actor_name} {clean}.",
                f"{actor_name} {_strip_article(clean)}.",
                f"{clean.capitalize()}.",
            ],
        )

        result.update({
            "handled": True,
            "kind": "movement",
            "mechanical_feedback": None,
            "spoken_narration": f"Dungeon Master: {narration}",
            "log_msg": f"[ALREADY_APPLIED] [System: {actor_name} {movement_phrase}.]",
            "ledger_event": {
                "kind": "movement",
                "facts": {},
            },
        })
        return result

    # --- Weapon Attack ---
    attack_roll = _has_attack_roll(lower)
    if attack_roll is not None:
        # Extract target name: text before the roll phrase
        target_raw = _extract_target_before_roll(clean, attack_roll)
        if target_raw is None:
            # Try extracting target after "at"/"against"
            m = re.search(r"\b(?:at|against)\s+([A-Za-z][A-Za-z\s'-]+?)(?:\s+(?:with|using))?(?:\s|$|\.|,)", clean, re.IGNORECASE)
            if m:
                target_raw = m.group(1).strip()

        if target_raw is None:
            result["fallback_reason"] = "attack_unclear_target"
            return result

        target = _unique_match(target_raw, candidates)
        if not target:
            result["fallback_reason"] = f"attack_ambiguous_target:{target_raw}"
            return result

        # Extract weapon flavor
        weapon_name = _extract_weapon_flavor(clean)

        # Check for damage keywords in the same text (conservative: fallback)
        if re.search(r"\b(for|deals?|inflicts?)\s+\d+\s+(damage|dmg|hp)\b", lower, re.IGNORECASE):
            result["fallback_reason"] = "attack_with_damage_not_supported"
            return result

        # Resolve hit/miss
        target_ac = target.get("ac", 10)
        if not isinstance(target_ac, int):
            target_ac = 10

        weapon_context = f" with {weapon_name}" if weapon_name else ""

        if attack_roll >= target_ac:
            # HIT - emit hit pending damage (reuse /att hit behavior)
            result.update({
                "handled": True,
                "kind": "weapon_attack_hit",
                "mechanical_feedback": (
                    f"[skipTTS][ALREADY_APPLIED][prefill:/dmg ] Dungeon Master: Hit! "
                    f"(Rolled {attack_roll} vs AC {target_ac}). Roll damage.{weapon_context}"
                ),
                "spoken_narration": None,
                "log_msg": f"[ALREADY_APPLIED] [System: {actor_name} attacked {target['name']}{weapon_context} with roll {attack_roll} vs AC {target_ac} and HIT. Damage pending.]",
                "target_name": target["name"],
                "parsed_attack_roll": attack_roll,
                "weapon_name": weapon_name,
                "ledger_event": {
                    "kind": "attack_hit_pending_damage",
                    "facts": {"roll": attack_roll, "ac": target_ac, "weapon": weapon_name or ""},
                },
            })
        else:
            # MISS - use deterministic miss path
            miss_narration = _pick_template(
                ["attack_miss", actor_name, target["name"], attack_roll, target_ac],
                [
                    f"{actor_name}'s attack cuts empty air as {target['name']} slips just outside the strike.",
                    f"{actor_name} commits to the blow, but {target['name']} twists away.",
                    f"{target['name']} jerks aside, and {actor_name}'s attack scrapes harmlessly past.",
                ],
            )
            result.update({
                "handled": True,
                "kind": "weapon_attack_miss",
                "mechanical_feedback": (
                    f"[skipTTS][ALREADY_APPLIED] Dungeon Master: Miss. "
                    f"(Rolled {attack_roll} vs AC {target_ac}). Attack result committed.{weapon_context}"
                ),
                "spoken_narration": f"Dungeon Master: {miss_narration}",
                "log_msg": f"[ALREADY_APPLIED] [System: {actor_name} attacked {target['name']}{weapon_context} with roll {attack_roll} vs AC {target_ac} and MISSED.]",
                "target_name": target["name"],
                "parsed_attack_roll": attack_roll,
                "weapon_name": weapon_name,
                "ledger_event": {
                    "kind": "attack_miss",
                    "facts": {"roll": attack_roll, "ac": target_ac, "weapon": weapon_name or ""},
                },
            })
        return result

    # Nothing matched
    result["fallback_reason"] = "unrecognized_action"
    return result


_TARGET_STOPWORDS = {"with", "using", "the", "a", "an", "my", "his", "her", "its", "their"}


def _extract_target_before_roll(text: str, roll: int) -> Optional[str]:
    """Extract target name that appears immediately before the attack roll number."""
    roll_str = str(roll)

    # Pattern: "attack <target> with roll <N>" or "hit <target> roll <N>"
    m = re.search(
        r"\b(?:attack|hit|shoot|strike|slash|stab)\s+(.+?)\s+(?:with\s+)?(?:roll(?:ed)?|to\s*hit)\s+" + roll_str,
        text, re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        # Filter out stop words
        if candidate.lower() not in _TARGET_STOPWORDS:
            return candidate
        # Try removing leading article
        stripped = _strip_article(candidate)
        if stripped and stripped.lower() not in _TARGET_STOPWORDS:
            return stripped

    # Pattern: "roll <N> to hit <target>" or "roll <N> at <target>"
    m = re.search(
        r"roll(?:ed)?\s+" + roll_str + r"\s+(?:to\s+hit|at)\s+([A-Za-z][A-Za-z\s'-]+)",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return None


# ---------------------------------------------------------------------------
# Apply parsed result
# ---------------------------------------------------------------------------

def apply_pc_phase_parse_result(
    result: Dict[str, Any],
    multi_pc_manager: Any,
    encounter_data: Dict[str, Any],
    encounter_id: Optional[str],
    actor_name: str,
) -> bool:
    """Apply a parsed parse result to the combat state.

    Handles encounter ops persistence, character updates, ledger recording,
    and last_target/last_attack_weapon state on the manager.

    Returns True if the result was applied (handled), False if it was not.
    """
    if not result.get("handled"):
        return False

    kind = result.get("kind", "")
    target_name = result.get("target_name")
    weapon_name = result.get("weapon_name")

    # Apply encounter ops (enemy damage)
    encounter_ops = result.get("encounter_ops", [])
    if encounter_ops and encounter_id:
        try:
            from updates.update_encounter import update_encounter
            changes = result.get("changes_text", "")
            encounter_result = update_encounter(encounter_id, changes, ops=encounter_ops)
            if encounter_result is False:
                return False
        except Exception as e:
            from utils.enhanced_logger import error
            error(
                f"PARSER: Failed to apply encounter ops for {kind}: {e}",
                exception=e, category="combat_events",
            )
            return False

    # Apply character updates (PC/NPC healing, spell slots)
    character_updates = result.get("character_updates", [])
    if character_updates:
        for update in character_updates:
            char_name = str(update.get("characterName", target_name or actor_name)).strip()
            char_ops = update.get("ops", [])
            char_changes = update.get("changes", result.get("changes_text", ""))
            try:
                from updates.update_character_info import update_character_info
                if not update_character_info(char_name, char_changes, ops=char_ops):
                    return False
            except Exception as e:
                from utils.enhanced_logger import error
                error(
                    f"PARSER: Failed to apply character update for {char_name}: {e}",
                    exception=e, category="combat_events",
                )
                return False

    # Update manager state only after required deterministic mutations succeed
    if target_name:
        try:
            multi_pc_manager.last_target = multi_pc_manager.find_target(target_name, encounter_data)
        except Exception:
            pass

    if weapon_name:
        multi_pc_manager.last_attack_weapon = weapon_name

    # Record ledger event
    ledger_event = result.get("ledger_event")
    if ledger_event and multi_pc_manager:
        try:
            kind = ledger_event.get("kind", "manual_note")
            facts = ledger_event.get("facts", {})
            narration = str(result.get("spoken_narration") or "").replace("Dungeon Master: ", "")
            multi_pc_manager.record_pc_phase_event(
                kind=kind,
                actor_name=actor_name,
                target_name=target_name,
                facts=facts,
                narration=narration,
                mechanics_already_applied=True,
            )
        except Exception as e:
            from utils.enhanced_logger import error
            error(
                f"PARSER: Failed to record ledger event: {e}",
                exception=e, category="combat_events",
            )

    return True
