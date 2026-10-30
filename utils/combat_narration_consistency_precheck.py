# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Narration Consistency Precheck
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Bounded deterministic prechecks for explicit combat narration contradictions and
enemy-routing boundary violations.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


_ATTACK_OUTCOME_PATTERN = re.compile(
    r"(?P<attacker>[A-Za-z0-9_][A-Za-z0-9_ '\-]*) attacks "
    r"(?P<target>[A-Za-z0-9_][A-Za-z0-9_ '\-]*?)"
    r"(?: with [A-Za-z0-9_ '\-]+)?"
    r" \(Attack roll: (?P<roll>-?\d+)\+(?P<bonus>-?\d+)=(?P<total>-?\d+), "
    r"(?P<outcome>hits|misses) (?P<target_repeat>[A-Za-z0-9_][A-Za-z0-9_ '\-]*?) AC (?P<ac>\d+)",
    re.IGNORECASE,
)

_MISS_AS_HIT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"bone splinters",
        r"bites deep",
        r"cuts into",
        r"strikes true",
        r"draws blood",
        r"slams into",
        r"drives deep",
        r"finds its mark",
        r"lands solidly",
        r"wet crunch",
        r"cleav(?:e|ing) .*deep",
        r"buries .*in",
    )
]

_HIT_AS_MISS_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"shatter(?:s|ing) against the wall",
        r"strikes only the wall",
        r"thud(?:s)? into the wall",
        r"goes wide",
        r"misses entirely",
        r"harmlessly past",
        r"flies past",
        r"whistles past",
        r"into the stone wall",
        r"against the wall near",
        r"near [A-Za-z0-9_ '\-]+ head",
        r"buries itself in the wall",
    )
]

_MUTATION_CLAUSE_PATTERNS = (
    re.compile(r"\b(?:takes?|suffers?)\s+\d+\b[^.;!?\n]{0,80}\b(?:damage|hp)\b", re.IGNORECASE),
    re.compile(r"\b(?:deals?|heals?)\s+\d+\b[^.;!?\n]{0,80}\b(?:to|for)\b", re.IGNORECASE),
    re.compile(r"\bhp\s*-?\d+\s*->\s*-?\d+", re.IGNORECASE),
    re.compile(r"\b(?:condition|conditions|poisoned|prone|restrained|unconscious|dead)\b", re.IGNORECASE),
    re.compile(r"\b(?:expends?|uses?|spends?|loses?|restores?)\b[^.;!?\n]{0,80}\b(?:slot|spell|arrow|bolt|ammunition|resource|charge|use)\b", re.IGNORECASE),
    re.compile(r"\b(?:remove|removes)\s+\d+\s+(?:arrow|bolt)\b", re.IGNORECASE),
)
_TARGET_LEFT_MUTATION = re.compile(
    r"^(?P<name>.+?)\s+(?:takes?|suffers?|loses?|expends?|uses?|spends?|restores?)\b",
    re.IGNORECASE,
)
_TARGET_RIGHT_MUTATION = re.compile(
    r"\b(?:damage|healing|condition|conditions|resource|slot|spell|ammunition|arrow|bolt|hp|hit points?)\b"
    r"[^.;!?\n]{0,48}\b(?:to|for|on|from)\s+(?P<name>[^,;.!?\n]+)",
    re.IGNORECASE,
)
_RECIPIENT_HEAL = re.compile(
    r"\bheals?\s+\d+\b[^.;!?\n]{0,48}\b(?:to|for)\s+(?P<name>[^,;.!?\n]+)",
    re.IGNORECASE,
)
_SUBJECT_INJURY_TAIL = re.compile(r"\s+(?:was|is|gets?|suffers?)\s+(?:hit|struck|wounded|injured)\b", re.IGNORECASE)
_HP_STATE_SUBJECT = re.compile(
    r"^(?P<name>[^,;.!?\n]+?)\s+(?:has\s+)?(?:hp\s+)?(?:is\s+)?(?:now\s+)?"
    r"(?:at\s+)?-?\d+\s*(?:hp|hit points?)\b",
    re.IGNORECASE,
)
_HP_ARROW_SUBJECT = re.compile(r"^(?P<name>[^,;.!?\n]+?)\s+hp\s*-?\d+\s*->\s*-?\d+", re.IGNORECASE)


def _normalize_name(value: Any) -> str:
    """Normalize a combatant name for bounded matching."""
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _build_ac_map(encounter_data: Dict[str, Any]) -> Dict[str, int]:
    """Build authoritative AC lookup from encounter data."""
    ac_map: Dict[str, int] = {}
    creatures = encounter_data.get("creatures", [])
    if not isinstance(creatures, list):
        return ac_map

    for creature in creatures:
        if not isinstance(creature, dict):
            continue
        normalized_name = _normalize_name(creature.get("name", ""))
        if not normalized_name:
            continue
        armor_class = creature.get("armorClass")
        try:
            ac_map[normalized_name] = int(armor_class)
        except (TypeError, ValueError):
            continue
    return ac_map


def _collect_text_surfaces(response_json: Dict[str, Any]) -> List[str]:
    """Collect bounded text surfaces that can contain attack math mirrors."""
    surfaces: List[str] = []
    for key in ("plan", "narration"):
        value = response_json.get(key)
        if isinstance(value, str) and value.strip():
            surfaces.append(value)

    actions = response_json.get("actions", [])
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            params = action.get("parameters", {})
            if not isinstance(params, dict):
                continue
            changes = params.get("changes")
            if isinstance(changes, str) and changes.strip():
                surfaces.append(changes)

    return surfaces


def _extract_attack_outcomes(
    response_json: Dict[str, Any],
    encounter_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract explicit attack outcomes only when AC matches authoritative state."""
    outcomes: List[Dict[str, Any]] = []
    seen: set = set()
    ac_map = _build_ac_map(encounter_data)

    for text in _collect_text_surfaces(response_json):
        for match in _ATTACK_OUTCOME_PATTERN.finditer(text):
            attacker = str(match.group("attacker")).strip()
            target = str(match.group("target_repeat") or match.group("target")).strip()
            normalized_target = _normalize_name(target)
            if normalized_target not in ac_map:
                continue

            parsed_ac = int(match.group("ac"))
            if ac_map[normalized_target] != parsed_ac:
                continue

            total = int(match.group("total"))
            outcome = {
                "attacker": attacker,
                "target": target,
                "hit": str(match.group("outcome")).strip().lower() == "hits",
                "total": total,
                "ac": parsed_ac,
            }
            dedupe_key = (
                _normalize_name(attacker),
                normalized_target,
                outcome["hit"],
                total,
                parsed_ac,
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            outcomes.append(outcome)

    return outcomes


def _find_first_name_index(text: str, names: Sequence[str], start_index: int) -> int:
    """Return earliest occurrence of any supplied name at or after start_index."""
    best_index = -1
    for name in names:
        normalized = _normalize_name(name)
        if not normalized:
            continue
        index = text.find(normalized, start_index)
        if index == -1:
            continue
        if best_index == -1 or index < best_index:
            best_index = index
    return best_index


def _segment_contains_any(segment: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    """Return True if any bounded contradiction phrase appears in the segment."""
    for pattern in patterns:
        if pattern.search(segment):
            return True
    return False


def validate_combat_narration_consistency_precheck(
    response_json: Dict[str, Any],
    encounter_data: Dict[str, Any],
) -> Tuple[bool, str]:
    """Reject explicit hit/miss narration contradictions when math is authoritative."""
    if not isinstance(response_json, dict) or not isinstance(encounter_data, dict):
        return True, ""

    narration = response_json.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        return True, ""

    attack_outcomes = _extract_attack_outcomes(response_json, encounter_data)
    if not attack_outcomes:
        return True, ""

    narration_lower = narration.lower()
    previous_end = 0

    for index, outcome in enumerate(attack_outcomes):
        current_names = [outcome.get("attacker", ""), outcome.get("target", "")]
        segment_start = _find_first_name_index(narration_lower, current_names, previous_end)
        if segment_start == -1:
            segment_start = previous_end

        segment_end = len(narration_lower)
        if index + 1 < len(attack_outcomes):
            next_outcome = attack_outcomes[index + 1]
            next_names = [next_outcome.get("attacker", ""), next_outcome.get("target", "")]
            next_start = _find_first_name_index(narration_lower, next_names, segment_start + 1)
            if next_start != -1:
                segment_end = next_start

        segment = narration_lower[segment_start:segment_end]
        previous_end = max(segment_end, previous_end)

        if outcome["hit"]:
            if _segment_contains_any(segment, _HIT_AS_MISS_PATTERNS):
                return False, (
                    "Combat narration consistency precheck failed: "
                    f"'{outcome['attacker']}' attack on '{outcome['target']}' was a confirmed hit "
                    f"({outcome['total']} vs AC {outcome['ac']}) but narration described a harmless miss."
                )
        else:
            if _segment_contains_any(segment, _MISS_AS_HIT_PATTERNS):
                return False, (
                    "Combat narration consistency precheck failed: "
                    f"'{outcome['attacker']}' attack on '{outcome['target']}' was a miss "
                    f"({outcome['total']} vs AC {outcome['ac']}) but narration described successful impact."
                )

    return True, ""


def _collect_non_enemy_names(encounter_data: Dict[str, Any]) -> List[str]:
    """Collect authoritative player and allied NPC names from the encounter."""
    names: List[str] = []
    creatures = encounter_data.get("creatures", [])
    if not isinstance(creatures, list):
        return names

    for creature in creatures:
        if not isinstance(creature, dict):
            continue
        creature_type = str(creature.get("type", "")).strip().lower()
        if creature_type == "enemy":
            continue
        name = str(creature.get("name", "")).strip()
        if name:
            names.append(name)
    return names


def _canonical_name_in_text(text: str, names: Sequence[str]) -> List[str]:
    """Return canonical encounter identities mentioned as whole names."""
    lowered = _normalize_name(text)
    found = []
    for name in names:
        normalized = _normalize_name(name)
        if not normalized:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(normalized) + r"(?![a-z0-9])", lowered):
            found.append(name)
    return found


def _canonical_subject_name(text: str, names: Sequence[str]) -> List[str]:
    """Match a complete canonical subject, optionally in possessive form."""
    normalized_text = _normalize_name(text.strip())
    return [
        name for name in names
        if normalized_text in (_normalize_name(name), _normalize_name(name) + " s")
    ]


def _mutation_clause_target(clause: str, non_enemy_names: Sequence[str], all_names: Sequence[str]) -> Optional[str]:
    """Identify only an explicit canonical recipient in a bounded clause."""
    mutation = any(pattern.search(clause) for pattern in _MUTATION_CLAUSE_PATTERNS)
    if not mutation:
        return None

    target_names: List[str] = []
    left = _TARGET_LEFT_MUTATION.match(clause.strip())
    if left:
        target_names.extend(_canonical_name_in_text(left.group("name"), non_enemy_names))
    right = _TARGET_RIGHT_MUTATION.search(clause)
    if right:
        target_names.extend(_canonical_name_in_text(right.group("name"), non_enemy_names))
    heal_recipient = _RECIPIENT_HEAL.search(clause)
    if heal_recipient:
        target_names.extend(_canonical_name_in_text(heal_recipient.group("name"), non_enemy_names))
    hp_subject = _HP_STATE_SUBJECT.match(clause.strip())
    if hp_subject:
        target_names.extend(_canonical_subject_name(hp_subject.group("name"), non_enemy_names))
    hp_arrow_subject = _HP_ARROW_SUBJECT.match(clause.strip())
    if hp_arrow_subject:
        target_names.extend(_canonical_subject_name(hp_arrow_subject.group("name"), non_enemy_names))

    unique_targets = list(dict.fromkeys(target_names))
    if len(unique_targets) == 1:
        return unique_targets[0]

    # A one-name mutation clause such as "Acheron HP 20->12" is attributable;
    # a clause containing both victim and attacker without an explicit relation is not.
    mentioned = _canonical_name_in_text(clause, all_names)
    mentioned_non_enemy = [name for name in mentioned if _normalize_name(name) in {
        _normalize_name(candidate) for candidate in non_enemy_names
    }]
    if len(mentioned) == 1 and len(mentioned_non_enemy) == 1:
        return mentioned_non_enemy[0]
    return None


def _immediate_hp_continuation_target(
    clause: str, non_enemy_names: Sequence[str], all_names: Sequence[str]
) -> Optional[str]:
    """Bind only an immediate HP-value continuation to an explicit prior subject/recipient."""
    normalized_clause = _normalize_name(clause.strip().rstrip(":"))
    exact_names = [name for name in all_names if _normalize_name(name) == normalized_clause]
    if len(exact_names) == 1 and _normalize_name(exact_names[0]) in {
        _normalize_name(name) for name in non_enemy_names
    }:
        return exact_names[0]

    subject_targets = []
    for name in non_enemy_names:
        normalized = _normalize_name(name)
        if not normalized:
            continue
        match = re.match(r"^" + re.escape(normalized) + r"(?![a-z0-9])", normalized_clause)
        if match and _SUBJECT_INJURY_TAIL.match(normalized_clause[match.end():]):
            subject_targets.append(name)
    if len(subject_targets) == 1 and len(_canonical_name_in_text(clause, non_enemy_names)) == 1:
        return subject_targets[0]

    hit_clause = re.search(
        r"\b(?:hits?|strikes?|wounds?|injures?)\s+(?P<targets>[^.;!?]+)",
        normalized_clause,
    )
    if not hit_clause:
        return None
    injury_targets = _canonical_name_in_text(hit_clause.group("targets"), non_enemy_names)
    unique_targets = list(dict.fromkeys(injury_targets))
    return unique_targets[0] if len(unique_targets) == 1 else None


def _changes_text_targets_non_enemy(changes_text: str, non_enemy_names: Sequence[str], all_names: Optional[Sequence[str]] = None) -> Optional[str]:
    """Return a non-enemy recipient only when a local clause proves its mutation."""
    canonical_names = list(all_names or non_enemy_names)
    clauses = re.split(r"[.;!?\n]+", changes_text)
    previous_hp_target: Optional[str] = None
    for clause in clauses:
        stripped = clause.strip()
        if not stripped:
            continue
        target = _mutation_clause_target(stripped, non_enemy_names, canonical_names)
        if target:
            return target
        # A value-only HP continuation can inherit only from the immediately
        # preceding clause that explicitly described a non-enemy HP mutation.
        if previous_hp_target and re.fullmatch(r"\s*(?:hp\s*)?-?\d+\s*->\s*-?\d+\s*", stripped, re.IGNORECASE):
            return previous_hp_target
        previous_hp_target = _immediate_hp_continuation_target(stripped, non_enemy_names, canonical_names)
    return None


def validate_update_encounter_enemy_boundary_precheck(
    response_json: Dict[str, Any],
    encounter_data: Dict[str, Any],
) -> Tuple[bool, str]:
    """Reject explicit updateEncounter payloads that target PC or allied NPC state."""
    if not isinstance(response_json, dict) or not isinstance(encounter_data, dict):
        return True, ""

    non_enemy_names = _collect_non_enemy_names(encounter_data)
    if not non_enemy_names:
        return True, ""

    non_enemy_lookup = {_normalize_name(name): name for name in non_enemy_names}
    all_names = [
        str(creature.get("name", "")).strip()
        for creature in encounter_data.get("creatures", [])
        if isinstance(creature, dict) and str(creature.get("name", "")).strip()
    ]
    actions = response_json.get("actions", [])
    if not isinstance(actions, list):
        return True, ""

    for action in actions:
        if not isinstance(action, dict):
            continue
        action_name = str(action.get("action", "")).strip().lower()
        if action_name != "updateencounter":
            continue

        params = action.get("parameters", {})
        if not isinstance(params, dict):
            continue

        changes_text = params.get("changes")
        if isinstance(changes_text, str) and changes_text.strip():
            offending_name = _changes_text_targets_non_enemy(changes_text, non_enemy_names, all_names)
            if offending_name:
                return False, (
                    "Combat enemy-routing precheck failed: updateEncounter prose mirror targeted "
                    f"non-enemy '{offending_name}'. Player and allied NPC state must use updateCharacterInfo."
                )

        ops_payload = params.get("ops")
        if not isinstance(ops_payload, list):
            continue

        for op_item in ops_payload:
            if not isinstance(op_item, dict):
                continue
            for key in ("creature", "target", "name", "character", "characterName"):
                reference = op_item.get(key)
                normalized_reference = _normalize_name(reference)
                if normalized_reference and normalized_reference in non_enemy_lookup:
                    return False, (
                        "Combat enemy-routing precheck failed: updateEncounter ops targeted "
                        f"non-enemy '{non_enemy_lookup[normalized_reference]}'. Player and allied NPC state must use updateCharacterInfo."
                    )

    return True, ""
