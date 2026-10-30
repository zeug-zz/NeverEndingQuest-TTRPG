# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Narration-only provider boundary for completed deterministic enemy ledgers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyDeparture,
    EnemyResolutionLedger,
)
from utils.enhanced_logger import debug


_PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "combat"
    / "enemy_batch_narration_prompt.txt"
)
_MAX_LEDGER_ENTRIES = 64
_MAX_LEDGER_CHARS = 12000
_MAX_USER_CONTENT_CHARS = 16000
_MAX_SCENE_CONTEXT_CHARS = 1400
_MAX_DESCRIPTION_CHARS = 240
_MAX_DESCRIPTION_ITEMS = 12
_MAX_TACTICAL_INTENT_ITEMS = 32
_MAX_DEPARTURES = 32
_TACTICAL_DEFAULT_REASONS = frozenset({
    "INVALID_CHOICE", "MISSING_CHOICE", "UNKNOWN_ACTOR", "DUPLICATE_ID", "UNISSUED_ID",
})

_REASON_CODES = frozenset({
    "empty_response",
    "unparsable_response",
    "unknown_name",
    "number_mismatch",
    "outcome_mismatch",
    "ledger_contradiction",
    "target_claim_contradiction",
    "hit_claim_contradiction",
    "miss_claim_contradiction",
    "damage_claim_contradiction",
    "kill_claim_contradiction",
    "defeat_claim_contradiction",
    "departure_claim_contradiction",
    "claim_attribution_ambiguous",
    "ledger_entry_omitted",
    "ledger_too_large",
})

_PROPER_NAME = re.compile(r"\b[A-Z][a-z]+(?:[ '\u2018\u2019-][A-Z][a-z]*)*\b")
_PROSE_FORMAT_MARKER = re.compile(r"```|\"(?:actions?|narration)\"\s*:", re.IGNORECASE)
_NUMERIC_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:st|nd|rd|th)?%?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_NUMBER_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|once|twice|thrice)\b",
    re.IGNORECASE,
)
_NUMBER_WORD_VALUES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
    "once": 1, "twice": 2, "thrice": 3,
}
_ORDINAL_WORD = re.compile(
    r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b",
    re.IGNORECASE,
)
_ORDINAL_WORD_VALUES = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_LEADING_NAME_STOPWORDS = frozenset({
    "a", "above", "across", "after", "against", "an", "and", "around",
    "as", "at", "before", "behind", "below", "beside", "between", "both", "but",
    "by", "each", "for", "from", "he", "her", "here", "his", "in",
    "into", "it", "its", "near", "of", "on", "once", "one", "or",
    "over", "she", "since", "that", "the", "their", "then", "there",
    "they", "this", "through", "toward", "under", "upon", "while", "with",
    "rolled", "result",
    "without", "yet",
})
_NAME_EXEMPTIONS = frozenset({"AC", "DM", "HP", "NPC", "PC", "SRD"})
_PRONOUNS = re.compile(r"\b(?:he|him|his|she|her|hers|they|them|their|theirs|it|its)\b", re.IGNORECASE)
_PRONOUN_WORDS = frozenset({
    "he", "him", "his", "she", "her", "hers", "they", "them", "their",
    "theirs", "it", "its",
})
_MISS_CLAIM = re.compile(
    r"\b(?:miss(?:es|ed)?|whiff(?:s|ed)?|evade[sd]?|dodges?|goes? wide|"
    r"fails? to (?:hit|connect)|swings? wide|swung wide|glances? off|harmlessly past|"
    r"cuts? empty air|whistles? past|flies? past|twists? away|slips? aside)\b",
    re.IGNORECASE,
)
_MISS_COUNT_VERB = re.compile(
    r"\b(?:miss(?:es|ed)?|whiff(?:s|ed)?|goes? wide|"
    r"fails? to (?:hit|connect))\s*$",
    re.IGNORECASE,
)
_MISS_COUNT_AFTER = re.compile(
    r"^\s*(?:(?:longsword|shortsword|scimitar|dagger|sword|weapon)\s+)?"
    r"(?:times?|attacks?|strikes?|swings?|blows?|"
    r"hits?(?!\s+points?\b))\b\s+(?:(?:all|both)\s+)?"
    r"(?:miss(?:es|ed)?|whiff(?:s|ed)?|goes?\s+wide|"
    r"fails?\s+to\s+(?:hit|connect))\b",
    re.IGNORECASE,
)
_HIT_CLAIM = re.compile(
    r"\b(?:hits?|struck|wounds?|injures?|damages?|connects? with|"
    r"finds? (?:its|his|her|their) mark|cuts? into|pierces?|bites? into|"
    r"lands? (?:a )?(?:blow|strike)|lands? (?:solidly|hard)|"
    r"lands? (?:critically|a critical hit)|"
    r"strikes? (?:true|home|deep|cleanly)|draws? blood|"
    r"catches? .{0,30}? cleanly|slams? into|drives? .{0,30}? deep|"
    r"bone splinters|wet crunch|cleaves? .{0,30}? deep|buries? .{0,30}? in)\b",
    re.IGNORECASE,
)
_DAMAGE_CLAIM = re.compile(
    r"\b(?:damage|wounds?|wounded|injures?|injury|bleeds?|hurts?|"
    r"takes?|suffers?|deals?|(?<!hit )points?)\b",
    re.IGNORECASE,
)
_KILL_CLAIM = re.compile(
    r"\b(?:kills?|killed|murder(?:s|ed)?|slays?|slain|dies?|died|dead|death)\b",
    re.IGNORECASE,
)
_DEFEAT_CLAIM = re.compile(
    r"\b(?:defeats?|defeated|knocks?\s+.{0,40}?\s+out|incapacitates?|"
    r"falls?\s+(?:dead|still)|(?:is|was) down\b(?!\s+to\b)|drops? out of the fight|"
    r"collapses? in a broken heap)\b",
    re.IGNORECASE,
)
_FLEE_CLAIM = re.compile(
    r"\b(?:flees?|fleeing|fled|runs? away|ran away|retreats?|withdraws?)\b",
    re.IGNORECASE,
)
_SURRENDER_CLAIM = re.compile(
    r"\b(?:surrenders?|surrendered|yields?|yielded|gives? up|gave up)\b",
    re.IGNORECASE,
)
_ATTACK_ACTION_CLAIM = re.compile(
    r"\b(?:attacks?|swings?|aims?|hurls?|looses?|fires?|shoots?|"
    r"makes?\s+(?:an?\s+)?attack)\b",
    re.IGNORECASE,
)
_HIT_COUNT_CLAIM = re.compile(
    r"\b(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"once|twice|thrice)\s+(?P<unit>times?|hits?|strikes?|blows?)\b",
    re.IGNORECASE,
)
_HIT_COUNT_CUE = re.compile(
    r"\b(?:hits?|struck|wounds?|wounded|injures?|injured|lands?|landed|"
    r"connects?|connected|draws? blood|cuts? into)\b",
    re.IGNORECASE,
)
_COVER_CLAIM = re.compile(r"\bcover\b", re.IGNORECASE)
_ORDINAL_ATTACK_REFERENCE = re.compile(
    r"^\s*(?:(?:it|its|he|his|she|her|they|their)\s+)?"
    r"(?:(?:a|the)\s+)?(?:first|second|third|fourth|fifth|last|next)\s+"
    r"(?:(?:two|three|four|five|six)\s+)?"
    r"(?:(?:longsword|shortsword|scimitar|dagger|sword|weapon)\s+)?"
    r"(?:(?:attack|blow|strike|swing|hit)\b|"
    r"(?:hits?|struck|miss(?:es|ed)?|lands?|strikes?|swings?|swung|cuts?)\b)",
    re.IGNORECASE,
)
_ORDINAL_ATTACK_PHRASE = re.compile(
    r"\b(?P<ordinal>(?:first|second|third|fourth|fifth|sixth|seventh|"
    r"eighth|ninth|tenth|next|\d+(?:st|nd|rd|th)))\s+"
    r"(?:(?:two|three|four|five|six)\s+)?"
    r"(?:(?:longsword|shortsword|scimitar|dagger|sword|weapon)\s+)?"
    r"(?:(?:attack|blow|strike|swing|hit)\b|"
    r"(?:hits?|struck|miss(?:es|ed)?|lands?|strikes?|swings?|swung|cuts?)\b)",
    re.IGNORECASE,
)
_HP_PAIR_PREFIX = re.compile(
    r"\b(?:hp|hit points?)\s*(?P<current>\d[\d,]*|zero|one|two|three|four|"
    r"five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty)\s*(?:/|of)\s*"
    r"(?P<maximum>\d[\d,]*|zero|one|two|three|four|five|six|seven|eight|"
    r"nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty)\b",
    re.IGNORECASE,
)
_HP_PAIR_SUFFIX = re.compile(
    r"\b(?P<current>\d[\d,]*|zero|one|two|three|four|five|six|seven|"
    r"eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty)\s*(?:/|of)\s*"
    r"(?P<maximum>\d[\d,]*|zero|one|two|three|four|five|six|seven|eight|"
    r"nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty)\s*(?:hp|hit points?)\b",
    re.IGNORECASE,
)
_HP_TRANSITION = re.compile(
    r"\b(?:(?:hp|hit points?)\s+(?:(?:falling|dropping)\s+)?(?:from\s+)?|from\s+)"
    r"(?P<before>\d[\d,]*)\s+(?:to|->)\s*(?P<after>\d[\d,]*)\b"
    r"(?:\s*(?:hp|hit points?))?",
    re.IGNORECASE,
)
_MAX_HP_MARKER = re.compile(
    r"\b(?:max(?:imum)?\s*(?:hp|hit points?)|"
    r"(?:hp|hit points?)\s*(?:max|maximum))\b",
    re.IGNORECASE,
)
_NUMBER_CONTEXT_MARKERS = (
    ("ac", re.compile(r"\bac\b", re.IGNORECASE)),
    ("d20", re.compile(r"\b(?:d20|attack\s+roll)\b", re.IGNORECASE)),
    ("roll", re.compile(r"(?<!attack )\b(?:rolls?|rolled)\b", re.IGNORECASE)),
    ("bonus", re.compile(r"\b(?:attack\s+)?bonus\b", re.IGNORECASE)),
    ("attack_total", re.compile(r"\b(?:attack\s+)?total\b", re.IGNORECASE)),
    ("damage", re.compile(
        r"\b(?:damage|wounds?|injur(?:y|ies)|hurt|bleed|takes?|suffers?|"
        r"deals?|(?<!hit )points?|(?:hits?|strikes?|struck|lands?|cuts?)\s+for)\b",
        re.IGNORECASE,
    )),
    ("hp", re.compile(
        r"\b(?:hp|hit points?|down to|left with|now at|remained at|"
        r"(?:remains?|remained)\s+alive\s+at|"
        r"leaving(?:\s+(?:him|her|them|it))?\s+at|"
        r"dropping(?:\s+(?:him|her|them|it))?\s+to)\b",
        re.IGNORECASE,
    )),
)


@dataclass(frozen=True)
class NarrationResult:
    """The chosen narration and bounded provenance for one ledger."""

    text: str
    source: str
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None


def _canonical_name(value: Any) -> str:
    text = (str(value or "").casefold()
            .replace("\u2018", "'").replace("\u2019", "'")
            .replace("'s", " "))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _contains_name(text: str, name: str) -> bool:
    canonical_text = " " + _canonical_name(text) + " "
    canonical_name = _canonical_name(name)
    return bool(canonical_name and (" " + canonical_name + " ") in canonical_text)


def _ledger_names(ledger: EnemyResolutionLedger) -> dict[str, str]:
    names: dict[str, str] = {}
    for entry in ledger.entries:
        for identity in (entry.actor, entry.target):
            canonical = _canonical_name(identity.name)
            if canonical:
                names[canonical] = identity.name
    for item in ledger.bloodied:
        canonical = _canonical_name(item.enemy.name)
        if canonical:
            names[canonical] = item.enemy.name
    for departure in ledger.departures:
        canonical = _canonical_name(departure.enemy.name)
        if canonical:
            names[canonical] = departure.enemy.name
    for cover_update in ledger.cover_updates:
        canonical = _canonical_name(cover_update.enemy.name)
        if canonical:
            names[canonical] = cover_update.enemy.name
    for entry in ledger.entries:
        canonical = _canonical_name(entry.action_name)
        if canonical:
            names.setdefault(canonical, entry.action_name)
    return names


def _scene_context_text(scene_context: Any, limit: int = _MAX_SCENE_CONTEXT_CHARS) -> str:
    if scene_context is None:
        return ""
    if isinstance(scene_context, str):
        text = scene_context
    else:
        try:
            text = json.dumps(scene_context, ensure_ascii=True, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = str(scene_context)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _bounded_creature_descriptions(
    creature_descriptions: Any,
    known_names: Mapping[str, str],
) -> list[dict[str, str]]:
    if not isinstance(creature_descriptions, Mapping):
        return []
    rows = []
    for raw_name, raw_description in creature_descriptions.items():
        if not isinstance(raw_name, str) or not isinstance(raw_description, str):
            continue
        canonical = _canonical_name(raw_name)
        if canonical not in known_names:
            continue
        description = re.sub(r"\s+", " ", raw_description).strip()
        if description:
            rows.append((canonical, known_names[canonical], description[:_MAX_DESCRIPTION_CHARS]))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [
        {"name": name, "description": description}
        for _, name, description in rows[:_MAX_DESCRIPTION_ITEMS]
    ]


def _bounded_tactical_plan_intent(
    tactical_plan_intent: Any,
    ledger: EnemyResolutionLedger,
) -> list[dict[str, str]]:
    """Keep only menu-derived actors and fixed, bounded intent labels."""
    if not isinstance(tactical_plan_intent, Sequence) or isinstance(
        tactical_plan_intent, (str, bytes)
    ):
        return []
    known_names = _ledger_names(ledger)
    departure_reasons = {
        _canonical_name(item.enemy.name): item.reason
        for item in ledger.departures
    }
    result = []
    for row in tactical_plan_intent[:_MAX_TACTICAL_INTENT_ITEMS]:
        if not isinstance(row, Mapping):
            continue
        actor = row.get("actor")
        intent = row.get("intent")
        if not isinstance(actor, str) or _canonical_name(actor) not in known_names:
            continue
        if intent not in {"attack", "rule_default", "flee", "surrender"}:
            continue
        bounded = {"actor": known_names[_canonical_name(actor)], "intent": intent}
        if intent in {"flee", "surrender"}:
            expected_reason = "fled" if intent == "flee" else "surrendered"
            reason = row.get("defeat_reason")
            if reason != expected_reason or departure_reasons.get(
                _canonical_name(actor)
            ) != expected_reason:
                continue
            bounded["defeat_reason"] = expected_reason
        reason = row.get("default_reason")
        if isinstance(reason, str) and reason in _TACTICAL_DEFAULT_REASONS:
            bounded["default_reason"] = reason
        result.append(bounded)
    return result


def _ledger_entry_payload(entry: Any) -> dict[str, Any]:
    return {
        "actor": {"name": entry.actor.name, "kind": entry.actor.kind},
        "action": entry.action_name,
        "target": {"name": entry.target.name, "kind": entry.target.kind},
        "d20": entry.d20,
        "attack_bonus": entry.attack_total - entry.d20,
        "attack_total": entry.attack_total,
        "armor_class": entry.armor_class,
        "outcome": "hit" if entry.hit else "miss",
        "critical": entry.critical,
        "damage_dice_rolls": list(entry.damage_dice_rolls),
        "damage_total": entry.damage_total,
        "damage_type": entry.damage_type,
        "target_hp_before": entry.target_hp_before,
        "target_hp_after": entry.target_hp_after,
        "target_max_hp": entry.target_max_hp,
        "target_status_after": entry.target_status_after,
    }


def _ledger_payload(ledger: EnemyResolutionLedger) -> dict[str, Any]:
    if len(ledger.entries) > _MAX_LEDGER_ENTRIES or len(ledger.departures) > _MAX_DEPARTURES:
        raise ValueError("enemy_narration_ledger_too_large")
    departures = []
    for departure in ledger.departures:
        if (
            not isinstance(departure, EnemyDeparture)
            or not isinstance(departure.enemy, CombatantIdentity)
            or departure.enemy.kind != "enemy"
            or departure.reason not in {"fled", "surrendered"}
        ):
            raise ValueError("enemy_narration_ledger_invalid")
        departures.append({"name": departure.enemy.name, "reason": departure.reason})
    payload = {
        "encounter_id": ledger.encounter_id,
        "round": ledger.round_number,
        "batch_id": ledger.batch_id,
        "batch_kind": ledger.batch_kind,
        "entries": [_ledger_entry_payload(entry) for entry in ledger.entries],
        "departures": departures,
        "bloodied_at_batch_start": [
            {"name": item.enemy.name, "bloodied": item.bloodied}
            for item in ledger.bloodied
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if len(encoded) > _MAX_LEDGER_CHARS:
        raise ValueError("enemy_narration_ledger_too_large")
    return payload


def build_enemy_batch_narration_messages(
    ledger: EnemyResolutionLedger,
    scene_context: Any,
    creature_descriptions: Any,
    tactical_plan_intent: Any = None,
) -> list[dict[str, str]]:
    """Build a bounded prose-only request from scene context and ledger facts."""
    if not isinstance(ledger, EnemyResolutionLedger):
        raise TypeError("ledger must be a completed EnemyResolutionLedger")
    payload = _ledger_payload(ledger)
    known_names = _ledger_names(ledger)
    user_payload = {
        "scene_context": _scene_context_text(scene_context),
        "creature_descriptions": _bounded_creature_descriptions(
            creature_descriptions, known_names
        ),
        "authoritative_ledger": payload,
    }
    plan_intent = _bounded_tactical_plan_intent(tactical_plan_intent, ledger)
    if plan_intent:
        user_payload["tactical_plan_intent"] = plan_intent
    user_content = json.dumps(
        user_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(user_content) > _MAX_USER_CONTENT_CHARS:
        user_payload["scene_context"] = _scene_context_text(scene_context, limit=300)
        user_payload["creature_descriptions"] = user_payload["creature_descriptions"][:4]
        user_content = json.dumps(
            user_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    if len(user_content) > _MAX_USER_CONTENT_CHARS:
        raise ValueError("enemy_narration_ledger_too_large")
    return [
        {"role": "system", "content": _PROMPT_PATH.read_text(encoding="ascii")},
        {"role": "user", "content": user_content},
    ]


def build_enemy_batch_template_narration(ledger: EnemyResolutionLedger) -> str:
    """Compose natural deterministic combat prose with exact ledger facts."""
    if not isinstance(ledger, EnemyResolutionLedger):
        raise TypeError("ledger must be a completed EnemyResolutionLedger")

    from core.combat.multi_pc.manager import _build_fast_path_narration

    lines = []
    for entry in ledger.entries:
        roll_note = (
            f"(Rolled {entry.attack_total} vs AC {entry.armor_class}; "
            f"d20 {entry.d20})"
        )
        flavor = _build_fast_path_narration(
            kind="damage" if entry.hit else "attack_miss",
            actor_name=entry.actor.name,
            target_name=entry.target.name,
            weapon_name=entry.action_name,
            roll=entry.d20,
            ac=entry.armor_class,
            amount=entry.damage_total,
            hp_before=entry.target_hp_before,
            hp_after=entry.target_hp_after,
            status_text=entry.target_status_after,
        )
        flavor = flavor.rstrip()
        if flavor.endswith("."):
            flavor = flavor[:-1]
        sentence = f"{flavor} {roll_note}."
        if entry.hit:
            sentence += (
                f" It deals {entry.damage_total} {entry.damage_type} damage."
            )
            if entry.critical:
                sentence += " It is a critical hit."
        if entry.hit and entry.target.kind == "player":
            max_hp = entry.target_max_hp
            hp_text = (
                f"{entry.target_hp_after}/{max_hp} HP"
                if isinstance(max_hp, int) and max_hp > 0
                else f"{entry.target_hp_after} HP"
            )
            sentence += f" {entry.target.name} has {hp_text}."
            if entry.target_hp_before > 0 and entry.target_hp_after <= 0:
                sentence += f" {entry.target.name} is down."
        lines.append(sentence)
    for departure in ledger.departures:
        if departure.reason == "fled":
            lines.append(
                f"{departure.enemy.name} disengages and flees at the end of its turn."
            )
        else:
            lines.append(f"{departure.enemy.name} surrenders and leaves the fight.")
    for cover_update in ledger.cover_updates:
        if cover_update.feature_id is None:
            lines.append(f"{cover_update.enemy.name} leaves cover.")
        else:
            cover_type = {
                "half": "half cover",
                "three_quarters": "three-quarters cover",
            }.get(cover_update.cover_type, "cover")
            lines.append(f"{cover_update.enemy.name} takes {cover_type}.")
    return "\n".join(lines)


def _response_text(response: Any) -> tuple[Optional[str], Optional[str]]:
    if response is None:
        return None, "empty_response"
    if not isinstance(response, str):
        return None, "unparsable_response"
    text = response.strip()
    if not text:
        return None, "empty_response"
    if _PROSE_FORMAT_MARKER.search(text):
        return None, "unparsable_response"
    try:
        json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text, None
    return None, "unparsable_response"


def _all_allowed_names(ledger: EnemyResolutionLedger, creature_descriptions: Any) -> dict[str, str]:
    # Descriptions are atmosphere, not authorization to add combatants to the
    # completed ledger. Only ledger identities and authored attack names are
    # valid proper-name references in the returned narration.
    return _ledger_names(ledger)


def _first_unknown_name(text: str, allowed_names: Mapping[str, str]) -> Optional[str]:
    for match in _PROPER_NAME.finditer(text):
        raw = match.group(0).strip()
        if raw.upper() in _NAME_EXEMPTIONS:
            continue
        if raw.casefold() in _PRONOUN_WORDS:
            continue
        words = raw.split()
        while words and words[0].casefold() in _LEADING_NAME_STOPWORDS:
            words.pop(0)
        candidate = " ".join(words).strip()
        if candidate.casefold().endswith("'s"):
            candidate = candidate[:-2]
        if not candidate:
            continue
        canonical = _canonical_name(candidate)
        tokens = canonical.split()
        if canonical in allowed_names:
            continue
        # A narration may refer to a named squad by its shared multi-word
        # stem, but it may not invent a new suffix or a new creature name.
        if len(tokens) >= 2 and any(
                name.split()[:len(tokens)] == tokens for name in allowed_names):
            continue
        return raw
    return None


def _validate_name_mentions(text: str, allowed_names: Mapping[str, str]) -> bool:
    return _first_unknown_name(text, allowed_names) is None


def _entry_contexts(
    text: str,
    ledger: EnemyResolutionLedger,
) -> list[tuple[str, list[Any], int, int]]:
    contexts = []
    previous_entries: list[Any] = []
    previous_named_actor_entries: list[Any] = []
    actor_names = {_canonical_name(entry.actor.name) for entry in ledger.entries}
    for match in re.finditer(r"[^.!?\n]+", text):
        clause = match.group(0)
        direct = [
            entry for entry in ledger.entries
            if _contains_name(clause, entry.actor.name) or _contains_name(clause, entry.target.name)
        ]
        named_actor_names_in_clause = {
            _canonical_name(name)
            for _start, _end, name in _name_spans(clause, actor_names)
        }
        named_target_names_in_clause = {
            _canonical_name(entry.target.name)
            for entry in ledger.entries
            if _contains_name(clause, entry.target.name)
        }
        ordinal_inherited = bool(
            previous_named_actor_entries and _ORDINAL_ATTACK_REFERENCE.search(clause)
        )
        possessive_actor_entries = (
            _previous_possessive_actor_entries(
                clause, previous_named_actor_entries, actor_names
            )
            if not named_actor_names_in_clause else []
        )
        if ordinal_inherited:
            relevant = [
                entry for entry in previous_named_actor_entries
                if not named_target_names_in_clause
                or _canonical_name(entry.target.name) in named_target_names_in_clause
            ]
        elif possessive_actor_entries:
            relevant = possessive_actor_entries
        elif not named_actor_names_in_clause and previous_named_actor_entries \
                and named_target_names_in_clause:
            # A target-only follow-up sentence normally describes the outcome
            # of the immediately preceding named actor's attack, not every
            # earlier attack against that target in the batch.
            relevant = [
                entry for entry in previous_named_actor_entries
                if _canonical_name(entry.target.name) in named_target_names_in_clause
            ] or direct
        else:
            relevant = direct
        if not relevant and not ordinal_inherited and _PRONOUNS.search(clause):
            relevant = list(previous_entries)
        if direct:
            previous_entries = list(direct)
        named_actor_names = {
            _canonical_name(name)
            for _start, _end, name in _name_spans(clause, actor_names)
        }
        if named_actor_names:
            previous_named_actor_entries = [
                entry for entry in ledger.entries
                if _canonical_name(entry.actor.name) in named_actor_names
            ]
        contexts.append((clause, relevant, match.start(), match.end()))
    return contexts


def _number_value(match: re.Match[str], *, word: bool, ordinal: bool = False) -> Optional[int]:
    if word:
        mapping = _ORDINAL_WORD_VALUES if ordinal else _NUMBER_WORD_VALUES
        return mapping.get(match.group(0).casefold())
    raw = match.group(0).replace(",", "").rstrip("%")
    raw = re.sub(r"(?:st|nd|rd|th)$", "", raw, flags=re.IGNORECASE)
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if value.is_integer() else None


def _text_number_value(raw: str) -> Optional[int]:
    raw = raw.strip().casefold()
    if raw in _NUMBER_WORD_VALUES:
        return _NUMBER_WORD_VALUES[raw]
    try:
        return int(raw.replace(",", ""))
    except ValueError:
        return None


def _name_pattern(name: str) -> re.Pattern[str]:
    words = [word for word in re.split(r"[\s_-]+", _canonical_name(name)) if word]
    joined = r"[\s_-]+".join(re.escape(word) for word in words)
    return re.compile(
        rf"(?<![A-Za-z0-9]){joined}(?:'s)?(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _name_spans(clause: str, names: set[str]) -> list[tuple[int, int, str]]:
    spans = []
    for name in names:
        for match in _name_pattern(name).finditer(clause):
            spans.append((match.start(), match.end(), _canonical_name(name)))
    return spans


def _previous_possessive_actor_entries(
    clause: str,
    previous_actor_entries: list[Any],
    actor_names: set[str],
) -> list[Any]:
    """Resolve a lowercase definite possessive only to one prior named actor."""
    if not previous_actor_entries:
        return []
    for match in re.finditer(
        r"\b[Tt]he\s+(?P<actor>[a-z][a-z0-9_-]*)['\u2019]s\b", clause
    ):
        alias = match.group("actor")
        candidates = {
            name for name in actor_names
            if name.split() and name.split()[-1] == alias
        }
        if len(candidates) != 1:
            continue
        candidate = next(iter(candidates))
        selected = [
            entry for entry in previous_actor_entries
            if _canonical_name(entry.actor.name) == candidate
        ]
        if selected:
            return selected
    return []


def _entries_for_role(
    entries: list[Any],
    clause: str,
    position: int,
    role: str,
) -> list[Any]:
    if not entries:
        return []
    identity_names = {
        _canonical_name(getattr(entry, role).name)
        for entry in entries
        if getattr(entry, role, None) is not None
    }
    spans = _name_spans(clause, identity_names)
    if not spans:
        return list(entries)
    if role == "actor":
        preceding = [span for span in spans if span[1] <= position]
        if preceding:
            latest_end = max(end for _start, end, _name in preceding)
            selected = {name for _start, end, name in preceding if end == latest_end}
            return [
                entry for entry in entries
                if _canonical_name(getattr(entry, role).name) in selected
            ]
    distances = {
        name: min(max(start - position, position - end, 0) for start, end, span_name in spans
                  if span_name == name)
        for name in identity_names
        if any(span_name == name for _start, _end, span_name in spans)
    }
    if not distances:
        return list(entries)
    closest = min(distances.values())
    selected = {name for name, distance in distances.items() if distance == closest}
    return [
        entry for entry in entries
        if _canonical_name(getattr(entry, role).name) in selected
    ]


def _is_miss_count_reference(clause: str, start: int, end: int) -> bool:
    token_text = clause[start:end]
    before_text = clause[max(0, start - 48):start]
    after_text = clause[end:min(len(clause), end + 28)]
    if _MISS_COUNT_VERB.search(before_text) and (
        token_text.casefold() in {"once", "twice", "thrice"}
        or re.match(r"\s*times?\b", after_text, re.IGNORECASE)
    ):
        return True
    return bool(_MISS_COUNT_AFTER.match(after_text))


def _contextual_values(
    clause: str,
    start: int,
    end: int,
    entries: list[Any],
    token_kind: str,
) -> Optional[set[int]]:
    """Return facts for a locally classified number, or None if unclassified."""
    position = (start + end) // 2

    def scoped(role: Optional[str] = None) -> list[Any]:
        selected = entries
        if role in (None, "actor"):
            selected = _entries_for_role(selected, clause, position, "actor")
        if role in (None, "target"):
            selected = _entries_for_role(selected, clause, position, "target")
        return selected

    def target_entries() -> list[Any]:
        selected = _entries_for_role(entries, clause, position, "target")
        return _entries_for_role(selected, clause, position, "actor")

    def latest_target_entries(selected: list[Any]) -> list[Any]:
        latest: dict[str, Any] = {}
        for entry in selected:
            latest[_canonical_name(entry.target.name)] = entry
        return list(latest.values())

    def overlap(span: tuple[int, int]) -> bool:
        return span[0] < end and start < span[1]

    def pair_values(pattern: re.Pattern[str]) -> Optional[set[int]]:
        for pair in pattern.finditer(clause):
            for field, category in (("current", "hp_current"), ("maximum", "hp_max")):
                span = pair.span(field)
                if not overlap(span):
                    continue
                selected = target_entries()
                if category == "hp_current":
                    return {
                        entry.target_hp_after
                        for entry in latest_target_entries(selected)
                        if isinstance(entry.target_hp_after, int)
                        and not isinstance(entry.target_hp_after, bool)
                    }
                return {
                    entry.target_max_hp
                    for entry in selected
                    if isinstance(entry.target_max_hp, int)
                    and not isinstance(entry.target_max_hp, bool)
                }
        return None

    for pair_pattern in (_HP_PAIR_PREFIX, _HP_PAIR_SUFFIX):
        values = pair_values(pair_pattern)
        if values is not None:
            return values

    for transition in _HP_TRANSITION.finditer(clause):
        if overlap(transition.span("before")):
            return {
                entry.target_hp_before for entry in target_entries()
                if isinstance(entry.target_hp_before, int)
                and not isinstance(entry.target_hp_before, bool)
            }
        if overlap(transition.span("after")):
            return {
                entry.target_hp_after for entry in target_entries()
                if isinstance(entry.target_hp_after, int)
                and not isinstance(entry.target_hp_after, bool)
            }

    if token_kind == "ordinal":
        ordinal_span = next(
            (match.span("ordinal") for match in _ORDINAL_ATTACK_PHRASE.finditer(clause)
             if overlap(match.span("ordinal"))),
            None,
        )
        if ordinal_span is not None:
            actor_entries = _entries_for_role(entries, clause, position, "actor")
            counts: dict[str, int] = {}
            for entry in actor_entries:
                actor_key = _canonical_name(entry.actor.name)
                counts[actor_key] = counts.get(actor_key, 0) + 1
            return {
                ordinal
                for count in counts.values()
                for ordinal in range(1, count + 1)
            }

    token_text = clause[start:end]
    before_text = clause[max(0, start - 48):start]
    after_text = clause[end:min(len(clause), end + 28)]
    if _is_miss_count_reference(clause, start, end):
        actor_entries = _entries_for_role(entries, clause, position, "actor")
        misses_by_actor: dict[str, int] = {}
        for entry in actor_entries:
            actor_key = _canonical_name(entry.actor.name)
            misses_by_actor[actor_key] = misses_by_actor.get(actor_key, 0) + int(
                not entry.hit
            )
        return set(misses_by_actor.values())

    count_unit = re.search(
        r"^\s*(?:(?:longsword|shortsword|scimitar|dagger|sword|weapon)\s+)?"
        r"(?P<unit>times?|attacks?|strikes?|swings?|blows?|"
        r"hits?(?!\s+points?\b))\b",
        after_text,
        re.IGNORECASE,
    )
    prior_count_unit = re.search(
        r"\b(?:attacks?|strikes?|swings?|blows?|hits?(?!\s+points?\b))\s*$",
        before_text,
        re.IGNORECASE,
    )
    count_cue = re.search(
        r"\b(?:once|twice|thrice)\b", token_text, re.IGNORECASE
    ) or count_unit or prior_count_unit
    if count_cue:
        hit_cue = re.search(
            r"\b(?:hit|hits|struck|wounded|injured|landed|connected)\b",
            before_text,
            re.IGNORECASE,
        )
        attack_cue = re.search(
            r"\b(?:attack(?:s|ed)?|swing(?:s|ing)?|swung|strikes?|blows?)\b",
            before_text,
            re.IGNORECASE,
        )
        unit = (count_unit.group("unit").strip().casefold()
                if count_unit else "")
        prior_unit = (prior_count_unit.group(0).strip().casefold()
                      if prior_count_unit else "")
        if unit.startswith("hit") or prior_unit.startswith("hit"):
            count_category = "hit_count"
        elif unit.startswith(("attack", "strike", "swing", "blow")) or prior_unit.startswith(
            ("attack", "strike", "swing", "blow")
        ):
            count_category = "hit_count" if hit_cue and (
                not attack_cue or hit_cue.start() > attack_cue.start()
            ) else "attack_count"
        elif hit_cue or attack_cue:
            count_category = (
                "hit_count" if hit_cue and (
                    not attack_cue or hit_cue.start() > attack_cue.start()
                ) else "attack_count"
            )
        else:
            count_category = None
        if count_category:
            actor_entries = _entries_for_role(entries, clause, position, "actor")
            counts: dict[str, list[Any]] = {}
            for entry in actor_entries:
                counts.setdefault(_canonical_name(entry.actor.name), []).append(entry)
            if count_category == "attack_count":
                if re.search(r"\b(?:first|next)\s*$", before_text, re.IGNORECASE):
                    maximum = max((len(group) for group in counts.values()), default=0)
                    return set(range(1, maximum + 1))
                return {len(group) for group in counts.values()}
            return {sum(1 for entry in group if entry.hit)
                    for group in counts.values()}

    nearby_markers: list[tuple[int, str]] = []
    for category, pattern in _NUMBER_CONTEXT_MARKERS:
        for marker in pattern.finditer(clause):
            distance = max(marker.start() - end, start - marker.end(), 0)
            if distance <= 32:
                nearby_markers.append((distance, category))
    max_hp_markers = [
        max(marker.start() - end, start - marker.end(), 0)
        for marker in _MAX_HP_MARKER.finditer(clause)
    ]
    if max_hp_markers and min(max_hp_markers) <= 24:
        selected = target_entries()
        return {
            entry.target_max_hp for entry in selected
            if isinstance(entry.target_max_hp, int)
            and not isinstance(entry.target_max_hp, bool)
        }

    if not nearby_markers:
        return None
    closest = min(distance for distance, _category in nearby_markers)
    categories = {
        category for distance, category in nearby_markers if distance == closest
    }
    if len(categories) != 1:
        return None
    category = next(iter(categories))
    if category == "hp":
        selected = target_entries()
        before_claim = re.search(r"\bbefore\b", before_text, re.IGNORECASE)
        if before_claim:
            return {entry.target_hp_before for entry in selected
                    if isinstance(entry.target_hp_before, int)
                    and not isinstance(entry.target_hp_before, bool)}
        return {
            entry.target_hp_after for entry in latest_target_entries(selected)
            if isinstance(entry.target_hp_after, int)
            and not isinstance(entry.target_hp_after, bool)
        }

    selected = scoped()
    if category == "ac":
        return {entry.armor_class for entry in selected
                if isinstance(entry.armor_class, int)
                and not isinstance(entry.armor_class, bool)}
    if category == "damage":
        return {entry.damage_total for entry in selected
                if isinstance(entry.damage_total, int)
                and not isinstance(entry.damage_total, bool)}
    if category == "d20":
        return {entry.d20 for entry in selected
                if isinstance(entry.d20, int) and not isinstance(entry.d20, bool)}
    if category == "roll":
        return {
            value for entry in selected
            for value in (entry.d20, entry.attack_total)
            if isinstance(value, int) and not isinstance(value, bool)
        }
    if category == "bonus":
        return {entry.attack_total - entry.d20 for entry in selected}
    if category == "attack_total":
        return {entry.attack_total for entry in selected
                if isinstance(entry.attack_total, int)
                and not isinstance(entry.attack_total, bool)}
    return None


def _ledger_fact_values(
    clause: str,
    start: int,
    end: int,
    entries: list[Any],
) -> set[int]:
    """All numeric facts for bounded named actors/targets, for ambiguous prose."""
    position = (start + end) // 2
    selected = _entries_for_role(entries, clause, position, "actor")
    selected = _entries_for_role(selected, clause, position, "target")
    values: set[int] = set()
    per_actor: dict[str, list[Any]] = {}
    for entry in selected:
        values.update((
            entry.d20,
            entry.attack_total - entry.d20,
            entry.attack_total,
            entry.armor_class,
            entry.damage_total,
            entry.target_hp_before,
            entry.target_hp_after,
        ))
        if isinstance(entry.target_max_hp, int) and not isinstance(entry.target_max_hp, bool):
            values.add(entry.target_max_hp)
        values.update(entry.damage_dice_rolls)
        per_actor.setdefault(_canonical_name(entry.actor.name), []).append(entry)
    for actor_entries in per_actor.values():
        values.add(len(actor_entries))
        values.add(sum(1 for entry in actor_entries if entry.hit))
        values.update(range(1, len(actor_entries) + 1))
    return {value for value in values if isinstance(value, int) and not isinstance(value, bool)}


def _hp_only_fact_values(
    clause: str,
    start: int,
    end: int,
    entries: list[Any],
) -> Optional[set[int]]:
    """Return only target HP facts for an explicitly HP-marked number."""
    position = (start + end) // 2
    hp_markers = [
        match for _category, pattern in _NUMBER_CONTEXT_MARKERS if _category == "hp"
        for match in pattern.finditer(clause)
    ]
    if not hp_markers or min(
        max(marker.start() - end, start - marker.end(), 0) for marker in hp_markers
    ) > 32:
        return None

    selected = _entries_for_role(entries, clause, position, "target")
    if not selected:
        return None

    def latest_targets(rows: list[Any]) -> list[Any]:
        latest: dict[str, Any] = {}
        for entry in rows:
            latest[_canonical_name(entry.target.name)] = entry
        return list(latest.values())

    for pattern in (_HP_PAIR_PREFIX, _HP_PAIR_SUFFIX):
        for pair in pattern.finditer(clause):
            if pair.start("current") < end and start < pair.end("current"):
                return {
                    entry.target_hp_after for entry in latest_targets(selected)
                    if isinstance(entry.target_hp_after, int)
                    and not isinstance(entry.target_hp_after, bool)
                }
            if pair.start("maximum") < end and start < pair.end("maximum"):
                return {
                    entry.target_max_hp for entry in selected
                    if isinstance(entry.target_max_hp, int)
                    and not isinstance(entry.target_max_hp, bool)
                }

    for transition in _HP_TRANSITION.finditer(clause):
        if transition.start("before") < end and start < transition.end("before"):
            return {
                entry.target_hp_before for entry in selected
                if isinstance(entry.target_hp_before, int)
                and not isinstance(entry.target_hp_before, bool)
            }
        if transition.start("after") < end and start < transition.end("after"):
            return {
                entry.target_hp_after for entry in selected
                if isinstance(entry.target_hp_after, int)
                and not isinstance(entry.target_hp_after, bool)
            }

    max_hp_marked = any(
        max(marker.start() - end, start - marker.end(), 0) <= 24
        for marker in _MAX_HP_MARKER.finditer(clause)
    )
    if max_hp_marked:
        return {
            entry.target_max_hp for entry in selected
            if isinstance(entry.target_max_hp, int)
            and not isinstance(entry.target_max_hp, bool)
        }
    return {
        entry.target_hp_after for entry in latest_targets(selected)
        if isinstance(entry.target_hp_after, int)
        and not isinstance(entry.target_hp_after, bool)
    }


def _validate_number_mentions(text: str, ledger: EnemyResolutionLedger) -> bool:
    contexts = _entry_contexts(text, ledger)
    tokens = [(match, "numeric") for match in _NUMERIC_TOKEN.finditer(text)]
    tokens.extend((match, "word") for match in _NUMBER_WORD.finditer(text))
    tokens.extend((match, "ordinal") for match in _ORDINAL_WORD.finditer(text))
    for match, token_kind in sorted(tokens, key=lambda item: item[0].start()):
        clause_context = next(
            (
                (clause, entries, clause_start)
                for clause, entries, clause_start, clause_end in contexts
                if clause_start <= match.start() < clause_end
            ),
            None,
        )
        if clause_context is None:
            return False
        clause, entries, clause_start = clause_context
        if not entries:
            return False
        ordinal = token_kind == "ordinal" or (
            token_kind == "numeric"
            and bool(re.search(r"(?:st|nd|rd|th)%?$", match.group(0), re.IGNORECASE))
        )
        value = _number_value(
            match,
            word=token_kind in ("word", "ordinal"),
            ordinal=token_kind == "ordinal",
        )
        if value is None:
            return False
        if token_kind == "numeric" and match.group(0).rstrip("%") \
                .replace(",", "").find(".") >= 0:
            return False
        start = match.start() - clause_start
        end = match.end() - clause_start
        if re.search(r"\bround\s*$", clause[max(0, start - 16):start], re.IGNORECASE):
            if value != ledger.round_number:
                return False
            continue
        expected = _contextual_values(
            clause, start, end, entries,
            "ordinal" if ordinal else "number",
        )
        if expected is None:
            hp_values = _hp_only_fact_values(clause, start, end, entries)
            if hp_values is not None:
                if value not in hp_values:
                    return False
                continue
            if value in _ledger_fact_values(clause, start, end, entries):
                return False
            continue
        if value not in expected:
            return False
    return True


def _closest_names(
    spans: list[tuple[int, int, str]], position: int
) -> set[str]:
    if not spans:
        return set()
    distances: dict[str, int] = {}
    for start, end, name in spans:
        distance = max(start - position, position - end, 0)
        distances[name] = min(distance, distances.get(name, distance))
    closest = min(distances.values())
    return {name for name, distance in distances.items() if distance == closest}


def _claim_entries(
    clause: str,
    position: int,
    entries: list[Any],
) -> tuple[list[Any], Optional[str]]:
    actor_names = {
        _canonical_name(entry.actor.name) for entry in entries
    }
    target_names = {
        _canonical_name(entry.target.name) for entry in entries
    }
    actor_spans = _name_spans(clause, actor_names)
    target_spans = _name_spans(clause, target_names)
    selected_actors = _closest_names(actor_spans, position)
    selected_targets = _closest_names(target_spans, position)

    plural_scope = re.search(
        r"\b(?:both|each|all)\b[^.;!?]{0,80}?\b(?:attacks?|hits?|miss(?:es|ed)?|"
        r"wounds?|injures?|damages?|strikes?|lands?)\b",
        clause,
        re.IGNORECASE,
    )
    if plural_scope and plural_scope.start() <= position <= plural_scope.end():
        if len(actor_names) > 1:
            selected_actors = actor_names
        if len(target_names) > 1:
            selected_targets = target_names

    candidates = [
        entry for entry in entries
        if not selected_actors
        or _canonical_name(entry.actor.name) in selected_actors
    ]
    if selected_targets:
        matched = [
            entry for entry in candidates
            if _canonical_name(entry.target.name) in selected_targets
        ]
        if not matched:
            if selected_actors:
                return [], "target_claim_contradiction"
            # A target-only statement can refer to any ledger attack on that
            # target; its truth is evaluated against the combined outcomes.
            matched = [
                entry for entry in entries
                if _canonical_name(entry.target.name) in selected_targets
            ]
        candidates = matched
    if not candidates:
        return [], "claim_attribution_ambiguous"
    return candidates, None


def _claim_matches(pattern: re.Pattern[str], clause: str) -> list[re.Match[str]]:
    matches = []
    for match in pattern.finditer(clause):
        if pattern is _HIT_CLAIM:
            prefix = clause[max(0, match.start() - 24):match.start()]
            if re.search(
                r"\b(?:fails? to|does not|did not|never|cannot|can't)\s*$",
                prefix,
                re.IGNORECASE,
            ):
                continue
            # "hit points" names a resource, not a successful attack claim.
            if re.match(r"\s+points?\b", clause[match.end():], re.IGNORECASE):
                continue
        if pattern is _DAMAGE_CLAIM and match.group(0).casefold().startswith("take"):
            if re.match(r"\s+.{0,24}\bcover\b", clause[match.end():], re.IGNORECASE):
                continue
        matches.append(match)
    return matches


def _has_specific_actor_attribution(clause: str, entries: list[Any]) -> bool:
    actor_names = {
        _canonical_name(entry.actor.name)
        for entry in entries
        if getattr(entry, "actor", None) is not None
    }
    return bool(_name_spans(clause, actor_names))


def _validate_departure_claims(
    text: str,
    ledger: EnemyResolutionLedger,
) -> Optional[str]:
    """Accept flee/surrender wording only for ledger-recorded enemy outcomes."""
    enemy_names = {
        _canonical_name(item.enemy.name)
        for item in ledger.bloodied
        if item.enemy.kind == "enemy"
    }
    enemy_names.update(
        _canonical_name(entry.actor.name)
        for entry in ledger.entries
        if entry.actor.kind == "enemy"
    )
    departure_reasons = {
        _canonical_name(item.enemy.name): item.reason
        for item in ledger.departures
        if isinstance(item, EnemyDeparture)
    }
    if not enemy_names:
        enemy_names.update(departure_reasons)

    for clause_match in re.finditer(r"[^.;!?\n]+", text):
        clause = clause_match.group(0)
        name_spans = _name_spans(clause, enemy_names)
        claims = sorted(
            (
                (claim, expected_reason)
                for pattern, expected_reason in (
                    (_FLEE_CLAIM, "fled"),
                    (_SURRENDER_CLAIM, "surrendered"),
                )
                for claim in pattern.finditer(clause)
            ),
            key=lambda item: item[0].start(),
        )
        for claim_index, (claim, expected_reason) in enumerate(claims):
            selected_names = _closest_names(name_spans, claim.start())
            if not selected_names:
                return "claim_attribution_ambiguous"
            # In a coordinated subject such as "Goblin Alpha and Goblin
            # Beta flee", validate every joined identity, not only the
            # final (nearest) name. Other clause wording breaks the chain.
            ordered_spans = sorted(name_spans)
            nearest_spans = [
                span for span in ordered_spans
                if span[2] in selected_names
                and max(span[0] - claim.start(), claim.start() - span[1], 0)
                == min(
                    max(item[0] - claim.start(), claim.start() - item[1], 0)
                    for item in ordered_spans
                )
            ]
            for nearest in nearest_spans:
                if nearest[1] > claim.start():
                    continue
                current_start = nearest[0]
                preceding = [
                    span for span in ordered_spans
                    if span[1] <= current_start and span[1] <= claim.start()
                ]
                for previous in reversed(preceding):
                    connector = clause[previous[1]:current_start]
                    if not re.fullmatch(
                        r"[\s,&]*(?:(?:and|or)[\s,&]*)?", connector, re.IGNORECASE
                    ):
                        break
                    selected_names.add(previous[2])
                    current_start = previous[0]

            claim_stop = (
                claims[claim_index + 1][0].start()
                if claim_index + 1 < len(claims) else len(clause)
            )
            after_claim = clause[claim.end():claim_stop]
            followed_by = re.search(
                r"\bfollowed\s+by\b", after_claim, re.IGNORECASE
            )
            if followed_by:
                subjects = after_claim[followed_by.end():]
                subject_spans = sorted(_name_spans(subjects, enemy_names))
                connector_pattern = (
                    r"[\s,&]*(?:(?:and|or)[\s,&]*)?"
                    r"(?:(?:the|a|an)[\s]+)?"
                )
                if subject_spans and re.fullmatch(
                    connector_pattern,
                    subjects[:subject_spans[0][0]],
                    re.IGNORECASE,
                ):
                    selected_names.add(subject_spans[0][2])
                    previous_end = subject_spans[0][1]
                    for subject in subject_spans[1:]:
                        connector = subjects[previous_end:subject[0]]
                        if not re.fullmatch(
                            connector_pattern, connector, re.IGNORECASE
                        ):
                            break
                        selected_names.add(subject[2])
                        previous_end = subject[1]

            for name in selected_names:
                if departure_reasons.get(name) != expected_reason:
                    return "departure_claim_contradiction"
    return None


def _claim_contexts(
    text: str,
    ledger: EnemyResolutionLedger,
) -> list[tuple[str, list[Any], bool]]:
    """Split outcome claims at clause boundaries without changing number scope."""
    contexts = []
    previous_entries: list[Any] = []
    previous_named_actor_entries: list[Any] = []
    actor_names = {
        _canonical_name(entry.actor.name) for entry in ledger.entries
    }
    for match in re.finditer(r"[^.;!?\n]+", text):
        clause = match.group(0)
        direct = [
            entry for entry in ledger.entries
            if _contains_name(clause, entry.actor.name)
            or _contains_name(clause, entry.target.name)
        ]
        named_actor_spans = _name_spans(clause, actor_names)
        named_actor_names = {span[2] for span in named_actor_spans}
        inherited_actor_attribution = bool(
            previous_named_actor_entries and _ORDINAL_ATTACK_REFERENCE.search(clause)
        )
        possessive_actor_entries = (
            _previous_possessive_actor_entries(
                clause, previous_named_actor_entries, actor_names
            )
            if not named_actor_spans else []
        )
        if possessive_actor_entries:
            inherited_actor_attribution = True
        relevant = (
            previous_named_actor_entries
            if inherited_actor_attribution and not possessive_actor_entries
            else (possessive_actor_entries or direct)
        )
        if not direct and not inherited_actor_attribution and _PRONOUNS.search(clause):
            relevant = list(previous_entries)
        if direct:
            previous_entries = list(direct)
        if named_actor_names:
            previous_named_actor_entries = [
                entry for entry in ledger.entries
                if _canonical_name(entry.actor.name) in named_actor_names
            ]
        contexts.append((clause, relevant, inherited_actor_attribution))
    return contexts


def _validate_claims(text: str, ledger: EnemyResolutionLedger) -> Optional[str]:
    for clause, entries, inherited_actor_attribution in _claim_contexts(text, ledger):
        if not entries:
            continue

        claim_groups = (
            (_ATTACK_ACTION_CLAIM, "target"),
            (_KILL_CLAIM, "kill"),
            (_DEFEAT_CLAIM, "defeat"),
            (_MISS_CLAIM, "miss"),
            (_HIT_CLAIM, "hit"),
            (_DAMAGE_CLAIM, "damage"),
        )
        for pattern, claim_kind in claim_groups:
            for match in _claim_matches(pattern, clause):
                candidates, attribution_error = _claim_entries(
                    clause, match.start(), entries
                )
                if attribution_error:
                    return attribution_error
                if claim_kind == "target":
                    continue
                if claim_kind == "kill":
                    if not any(entry.target_status_after == "dead" for entry in candidates):
                        return "kill_claim_contradiction"
                elif claim_kind == "defeat":
                    if not any(
                        entry.target_status_after in {"dead", "defeated", "unconscious"}
                        for entry in candidates
                    ):
                        return "defeat_claim_contradiction"
                elif claim_kind == "miss":
                    ordinal_entry = _ordinal_attack_entry(
                        clause, match.start(), candidates
                    )
                    if ordinal_entry is not None:
                        if ordinal_entry.hit:
                            return "miss_claim_contradiction"
                        continue
                    outcomes = {entry.hit for entry in candidates}
                    if outcomes == {True}:
                        return "miss_claim_contradiction"
                    if (outcomes == {False, True}
                            and not _has_specific_actor_attribution(clause, candidates)
                            and not inherited_actor_attribution):
                        return "claim_attribution_ambiguous"
                elif claim_kind == "hit":
                    ordinal_entry = _ordinal_attack_entry(
                        clause, match.start(), candidates
                    )
                    if ordinal_entry is not None:
                        if not ordinal_entry.hit:
                            return "hit_claim_contradiction"
                        continue
                    outcomes = {entry.hit for entry in candidates}
                    if outcomes == {False}:
                        return "hit_claim_contradiction"
                    if (outcomes == {False, True}
                            and not _has_specific_actor_attribution(clause, candidates)
                            and not inherited_actor_attribution):
                        return "claim_attribution_ambiguous"
                elif claim_kind == "damage":
                    if not any(entry.hit and entry.damage_total > 0 for entry in candidates):
                        return "damage_claim_contradiction"
    return None


def _number_context_category(clause: str, start: int, end: int) -> Optional[str]:
    """Return the nearest bounded numeric-claim category around one number."""
    if _is_miss_count_reference(clause, start, end):
        return "miss_count"

    max_hp_distances = [
        max(marker.start() - end, start - marker.end(), 0)
        for marker in _MAX_HP_MARKER.finditer(clause)
    ]
    if max_hp_distances and min(max_hp_distances) <= 24:
        return "max_hp"

    nearby = []
    for category, pattern in _NUMBER_CONTEXT_MARKERS:
        for marker in pattern.finditer(clause):
            distance = max(marker.start() - end, start - marker.end(), 0)
            if distance <= 32:
                nearby.append((distance, category))
    if not nearby:
        return None
    closest = min(distance for distance, _category in nearby)
    categories = {
        category for distance, category in nearby if distance == closest
    }
    return next(iter(categories)) if len(categories) == 1 else None


def _scoped_hit_groups(
    entries: list[Any], clause: str, position: int, *, damage_value: Optional[int] = None
) -> set[tuple[str, str]]:
    selected = _entries_for_role(entries, clause, position, "actor")
    selected = _entries_for_role(selected, clause, position, "target")
    return {
        (_canonical_name(entry.actor.name), _canonical_name(entry.target.name))
        for entry in selected
        if entry.hit
        and entry.damage_total > 0
        and (damage_value is None or entry.damage_total == damage_value)
    }


def _scoped_hit_entries(
    entries: list[Any],
    clause: str,
    position: int,
    *,
    damage_value: Optional[int] = None,
    hp_before: Optional[int] = None,
    hp_after: Optional[int] = None,
) -> list[Any]:
    selected = _entries_for_role(entries, clause, position, "actor")
    selected = _entries_for_role(selected, clause, position, "target")
    return [
        entry for entry in selected
        if entry.hit
        and entry.damage_total > 0
        and (damage_value is None or entry.damage_total == damage_value)
        and (hp_before is None or entry.target_hp_before == hp_before)
        and (hp_after is None or entry.target_hp_after == hp_after)
    ]


def _ordinal_attack_entry(
    clause: str,
    position: int,
    entries: list[Any],
) -> Optional[Any]:
    ordinals = [
        match for match in _ORDINAL_ATTACK_PHRASE.finditer(clause)
        if match.start() < position and position - match.end() <= 48
    ]
    if not ordinals:
        following_ordinals = [
            match for match in _ORDINAL_ATTACK_PHRASE.finditer(clause)
            if position <= match.start() <= position + 32
        ]
        attached_ordinal = next(
            (
                match for match in following_ordinals
                if re.search(
                    r"\b(?:with|on|during)\s+(?:(?:a|the|its|his|her|their)\s+)?$",
                    clause[position:match.start()],
                    re.IGNORECASE,
                )
            ),
            None,
        )
        if attached_ordinal is not None:
            ordinals = [attached_ordinal]
    if not ordinals:
        # In sequential prose, an unnumbered opening hit is the first attack
        # when the same clause explicitly identifies a later ordinal swing.
        later_ordinals = [
            match for match in _ORDINAL_ATTACK_PHRASE.finditer(clause)
            if match.start() >= position
        ]
        if later_ordinals:
            later_value = _ORDINAL_WORD_VALUES.get(
                later_ordinals[0].group("ordinal").casefold(),
                _text_number_value(later_ordinals[0].group("ordinal")),
            )
            if later_value and later_value > 1:
                ordinals = [None]
    if not ordinals:
        return None
    match = max((item for item in ordinals if item is not None), key=lambda item: item.end(), default=None)
    if match is None:
        ordinal = 1
    else:
        raw = match.group("ordinal")
        if raw.casefold() == "next":
            previous_ordinal = None
            for earlier in _ORDINAL_ATTACK_PHRASE.finditer(clause):
                if earlier.start() >= match.start():
                    break
                earlier_raw = earlier.group("ordinal")
                if earlier_raw.casefold() == "next":
                    if previous_ordinal is not None:
                        previous_ordinal += 1
                    continue
                previous_ordinal = _ORDINAL_WORD_VALUES.get(
                    earlier_raw.casefold(), _text_number_value(earlier_raw)
                )
            ordinal = previous_ordinal + 1 if previous_ordinal is not None else None
        else:
            ordinal = _ORDINAL_WORD_VALUES.get(raw.casefold(), _text_number_value(raw))
    if ordinal is None or ordinal < 1:
        return None
    actor_names = {_canonical_name(entry.actor.name) for entry in entries}
    target_names = {_canonical_name(entry.target.name) for entry in entries}
    selected_actors = _closest_names(_name_spans(clause, actor_names), position)
    selected_targets = _closest_names(_name_spans(clause, target_names), position)
    scoped = [
        entry for entry in entries
        if (not selected_actors or _canonical_name(entry.actor.name) in selected_actors)
        and (not selected_targets or _canonical_name(entry.target.name) in selected_targets)
    ]
    actor_keys = {_canonical_name(entry.actor.name) for entry in scoped}
    if len(actor_keys) != 1:
        return None
    actor_entries = [
        entry for entry in scoped
        if _canonical_name(entry.actor.name) in actor_keys
    ]
    if ordinal > len(actor_entries):
        return None
    return actor_entries[ordinal - 1]


def _ordinal_hit_entry(
    clause: str,
    position: int,
    entries: list[Any],
) -> Optional[Any]:
    selected = _ordinal_attack_entry(clause, position, entries)
    if selected is None or not selected.hit or selected.damage_total <= 0:
        return None
    return selected


def _validate_hit_entry_coverage(text: str, ledger: EnemyResolutionLedger) -> bool:
    """Require every damaging ledger event, while allowing omitted miss-only actors."""
    required: dict[tuple[str, str], int] = {}
    for entry in ledger.entries:
        if entry.hit and entry.damage_total > 0:
            group = (
                _canonical_name(entry.actor.name),
                _canonical_name(entry.target.name),
            )
            required[group] = required.get(group, 0) + 1
    if not required:
        return True

    covered_entries: set[int] = set()
    damage_mentions_seen: dict[tuple[tuple[str, str], int], int] = {}

    for clause, entries, _clause_start, _clause_end in _entry_contexts(text, ledger):
        for word, pattern in ((False, _NUMERIC_TOKEN), (True, _NUMBER_WORD)):
            for match in pattern.finditer(clause):
                if _number_context_category(clause, match.start(), match.end()) != "damage":
                    continue
                value = _number_value(match, word=word)
                if value is None:
                    continue
                position = (match.start() + match.end()) // 2
                candidates = _scoped_hit_entries(
                    entries, clause, position, damage_value=value
                )
                uncovered = [item for item in candidates if id(item) not in covered_entries]
                if len(uncovered) == 1:
                    covered_entries.add(id(uncovered[0]))
                elif len(candidates) > 1:
                    groups = {
                        (_canonical_name(item.actor.name), _canonical_name(item.target.name))
                        for item in candidates
                    }
                    if len(groups) == 1:
                        group = next(iter(groups))
                        key = (group, value)
                        occurrence = damage_mentions_seen.get(key, 0)
                        matching = [
                            item for item in candidates
                            if (_canonical_name(item.actor.name), _canonical_name(item.target.name)) == group
                        ]
                        if occurrence < len(matching):
                            covered_entries.add(id(matching[occurrence]))
                        damage_mentions_seen[key] = occurrence + 1

        for match in _claim_matches(_HIT_CLAIM, clause):
            candidates, attribution_error = _claim_entries(
                clause, match.start(), entries
            )
            if attribution_error:
                continue
            ordinal_entry = _ordinal_hit_entry(clause, match.start(), candidates)
            if ordinal_entry is not None:
                covered_entries.add(id(ordinal_entry))
                continue
            hits = _scoped_hit_entries(candidates, clause, match.start())
            uncovered = [item for item in hits if id(item) not in covered_entries]
            if len(uncovered) == 1:
                covered_entries.add(id(uncovered[0]))

        for match in _claim_matches(_DAMAGE_CLAIM, clause):
            candidates, attribution_error = _claim_entries(
                clause, match.start(), entries
            )
            if attribution_error:
                continue
            hits = _scoped_hit_entries(candidates, clause, match.start())
            uncovered = [item for item in hits if id(item) not in covered_entries]
            if len(uncovered) == 1:
                covered_entries.add(id(uncovered[0]))

        for transition in _HP_TRANSITION.finditer(clause):
            before = _text_number_value(transition.group("before"))
            after = _text_number_value(transition.group("after"))
            if before is None or after is None or after >= before:
                continue
            candidates = _scoped_hit_entries(
                entries,
                clause,
                transition.start("after"),
                hp_before=before,
                hp_after=after,
            )
            if len(candidates) == 1:
                covered_entries.add(id(candidates[0]))

        for match in list(_NUMERIC_TOKEN.finditer(clause)) + list(_NUMBER_WORD.finditer(clause)):
            kind, _transition = _hp_result_token(
                clause, match.start(), match.end()
            )
            if kind not in {"result", "snapshot"}:
                continue
            value = _number_value(match, word=match.re is _NUMBER_WORD)
            if value is None:
                continue
            position = (match.start() + match.end()) // 2
            targets = _hp_targets_for_claim(clause, position, entries, ledger)
            scoped = _entries_for_role(entries, clause, position, "actor")
            scoped = _entries_for_role(scoped, clause, position, "target")
            candidates = [
                entry for entry in scoped
                if entry.hit
                and entry.damage_total > 0
                and _canonical_name(entry.target.name) in targets
                and entry.target_hp_after == value
            ]
            if len(candidates) == 1:
                covered_entries.add(id(candidates[0]))

        for match in _HIT_COUNT_CLAIM.finditer(clause):
            count = _text_number_value(match.group("count"))
            if count is None:
                continue
            prefix = clause[max(0, match.start() - 60):match.start()]
            suffix = clause[match.end():min(len(clause), match.end() + 40)]
            if not (_HIT_COUNT_CUE.search(prefix) or _HIT_COUNT_CUE.search(suffix)):
                continue
            candidates = _scoped_hit_entries(entries, clause, match.start())
            groups = {
                (_canonical_name(item.actor.name), _canonical_name(item.target.name))
                for item in candidates
            }
            if len(groups) != 1:
                continue
            group = next(iter(groups))
            group_entries = [
                entry for entry in ledger.entries
                if ( _canonical_name(entry.actor.name), _canonical_name(entry.target.name)) == group
            ]
            group_hits = [entry for entry in group_entries if entry.hit and entry.damage_total > 0]
            group_misses = [entry for entry in group_entries if not entry.hit]
            if count == len(group_hits) and not group_misses:
                covered_entries.update(id(item) for item in group_hits)

    return all(
        id(entry) in covered_entries
        for entry in ledger.entries
        if entry.hit and entry.damage_total > 0
    )


def _hp_result_token(
    clause: str, start: int, end: int
) -> tuple[Optional[str], Optional[re.Match[str]]]:
    """Classify an HP number as a result, transition endpoint, or non-result."""
    for pattern in (_HP_PAIR_PREFIX, _HP_PAIR_SUFFIX):
        for pair in pattern.finditer(clause):
            if pair.start("current") < end and start < pair.end("current"):
                return "snapshot", None
            if pair.start("maximum") < end and start < pair.end("maximum"):
                return None, None

    for transition in _HP_TRANSITION.finditer(clause):
        if transition.start("before") < end and start < transition.end("before"):
            return None, None
        if transition.start("after") < end and start < transition.end("after"):
            kind = (
                "outcome_transition"
                if re.search(r"\b(?:falling|dropping)\b", transition.group(0), re.IGNORECASE)
                else "transition"
            )
            return kind, transition

    if _number_context_category(clause, start, end) == "hp":
        return "result", None
    return None, None


def _hp_targets_for_claim(
    clause: str,
    position: int,
    context_entries: list[Any],
    ledger: EnemyResolutionLedger,
) -> set[str]:
    target_names = {
        _canonical_name(entry.target.name) for entry in ledger.entries
    }
    spans = _name_spans(clause, target_names)
    if spans:
        return _closest_names(spans, position)
    contextual = {
        _canonical_name(entry.target.name) for entry in context_entries
    }
    if len(contextual) == 1:
        return contextual
    if not contextual and len(target_names) == 1:
        return target_names
    return set()


def _intermediate_hp_is_tied_to_strike(
    clause: str,
    transition: Optional[re.Match[str]],
    position: int,
    target_names: set[str],
    context_entries: list[Any],
    hp_after: int,
    ledger: EnemyResolutionLedger,
) -> bool:
    actor_names = {
        _canonical_name(entry.actor.name) for entry in ledger.entries
    }
    named_actors = {
        span[2] for span in _name_spans(clause, actor_names)
    }
    matching_ordinals = [
        match for match in _ORDINAL_ATTACK_PHRASE.finditer(clause)
        if match.start() < position
    ]
    if not named_actors and matching_ordinals:
        named_actors = {
            _canonical_name(entry.actor.name) for entry in context_entries
        }
    if not named_actors or not target_names:
        return False

    before_value = (
        _text_number_value(transition.group("before"))
        if transition is not None else None
    )
    after_value = (
        _text_number_value(transition.group("after"))
        if transition is not None else hp_after
    )
    if after_value != hp_after:
        return False

    if matching_ordinals:
        ordinal_match = min(
            matching_ordinals,
            key=lambda match: position - match.start(),
        )
        raw_ordinal = ordinal_match.group("ordinal")
        ordinal = _ORDINAL_WORD_VALUES.get(
            raw_ordinal.casefold(), _text_number_value(raw_ordinal)
        )
        if ordinal is None or ordinal < 1:
            return False
        for actor_name in named_actors:
            for target_name in target_names:
                actor_entries = [
                    entry for entry in ledger.entries
                    if _canonical_name(entry.actor.name) == actor_name
                    and _canonical_name(entry.target.name) == target_name
                ]
                if ordinal <= len(actor_entries):
                    selected = actor_entries[ordinal - 1]
                    if (
                        selected.hit
                        and selected.target_hp_after == after_value
                        and (before_value is None or selected.target_hp_before == before_value)
                    ):
                        return True
        return False

    count_claims = [
        match for match in _HIT_COUNT_CLAIM.finditer(clause)
        if match.start() < position
        and _HIT_COUNT_CUE.search(clause[max(0, match.start() - 60):match.start()])
    ]
    if any(
        (_text_number_value(match.group("count")) or 0) > 1
        for match in count_claims
    ):
        return False

    attack_claims = [
        match for pattern in (_HIT_CLAIM, _ATTACK_ACTION_CLAIM)
        for match in pattern.finditer(clause)
        if match.start() < position and position - match.end() <= 80
    ]
    if not attack_claims:
        return False

    matches = [
        entry for entry in ledger.entries
        if _canonical_name(entry.actor.name) in named_actors
        and _canonical_name(entry.target.name) in target_names
        and entry.hit
        and entry.target_hp_after == after_value
        and (before_value is None or entry.target_hp_before == before_value)
    ]
    return len(matches) == 1


def _validate_final_hp_claims(text: str, ledger: EnemyResolutionLedger) -> bool:
    final_hp = {}
    for entry in ledger.entries:
        final_hp[_canonical_name(entry.target.name)] = entry.target_hp_after

    for clause, context_entries, _clause_start, _clause_end in _entry_contexts(text, ledger):
        number_matches = list(_NUMERIC_TOKEN.finditer(clause))
        number_matches.extend(_NUMBER_WORD.finditer(clause))
        for match in number_matches:
            kind, transition = _hp_result_token(
                clause, match.start(), match.end()
            )
            if kind not in {"result", "outcome_transition"}:
                continue
            value = _number_value(
                match,
                word=match.re is _NUMBER_WORD,
            )
            if value is None:
                return False
            targets = _hp_targets_for_claim(
                clause,
                (match.start() + match.end()) // 2,
                context_entries,
                ledger,
            )
            if not targets or any(target not in final_hp for target in targets):
                return False
            if all(final_hp[target] == value for target in targets):
                continue
            if _intermediate_hp_is_tied_to_strike(
                clause,
                transition,
                (match.start() + match.end()) // 2,
                targets,
                context_entries,
                value,
                ledger,
            ):
                continue
            return False
    return True


def _validate_defeat_entry_coverage(
    text: str, ledger: EnemyResolutionLedger
) -> bool:
    final_entries = {}
    for entry in ledger.entries:
        final_entries[_canonical_name(entry.target.name)] = entry

    required = [
        entry for entry in final_entries.values()
        if entry.target_status_after in {"dead", "defeated", "unconscious"}
    ]
    if not required:
        return True

    covered = set()
    for clause, entries, _inherited_actor_attribution in _claim_contexts(text, ledger):
        for pattern in (_KILL_CLAIM, _DEFEAT_CLAIM):
            for match in _claim_matches(pattern, clause):
                candidates, attribution_error = _claim_entries(
                    clause, match.start(), entries
                )
                if attribution_error:
                    continue
                covered.update(candidates)

    return all(entry in covered for entry in required)


def _validate_departure_entry_coverage(
    text: str, ledger: EnemyResolutionLedger
) -> bool:
    for departure in ledger.departures:
        pattern = _FLEE_CLAIM if departure.reason == "fled" else _SURRENDER_CLAIM
        if not any(
            _contains_name(clause, departure.enemy.name) and pattern.search(clause)
            for clause in re.split(r"[.;!?\n]+", text)
        ):
            return False
    return True


def _validate_cover_entry_coverage(
    text: str, ledger: EnemyResolutionLedger
) -> bool:
    for update in ledger.cover_updates:
        # Clearing cover is implicit in a narrated melee action, defeat, or
        # departure. Acquiring or changing cover is a distinct event that must
        # be stated in the prose.
        if update.feature_id is None:
            continue
        if not any(
            _contains_name(clause, update.enemy.name) and _COVER_CLAIM.search(clause)
            for clause in re.split(r"[.;!?\n]+", text)
        ):
            return False
    return True


def _validate_narration_completeness(
    text: str, ledger: EnemyResolutionLedger
) -> bool:
    """Ensure prose does not omit mechanical events or report stale final HP."""
    return (
        _validate_hit_entry_coverage(text, ledger)
        and _validate_defeat_entry_coverage(text, ledger)
        and _validate_departure_entry_coverage(text, ledger)
        and _validate_cover_entry_coverage(text, ledger)
        and _validate_final_hp_claims(text, ledger)
    )


def _check_narration(
    text: str,
    ledger: EnemyResolutionLedger,
    creature_descriptions: Any,
) -> Optional[str]:
    if not _validate_name_mentions(text, _all_allowed_names(ledger, creature_descriptions)):
        return "unknown_name"
    departure_reason = _validate_departure_claims(text, ledger)
    if departure_reason:
        return departure_reason
    if not _validate_number_mentions(text, ledger):
        return "number_mismatch"

    claim_reason = _validate_claims(text, ledger)
    if claim_reason:
        return claim_reason

    if not _validate_narration_completeness(text, ledger):
        return "ledger_entry_omitted"

    return None


def _template_result(ledger: EnemyResolutionLedger, reason_code: str) -> NarrationResult:
    if reason_code not in _REASON_CODES:
        reason_code = "ledger_contradiction"
    return NarrationResult(
        text=build_enemy_batch_template_narration(ledger),
        source="template",
        reason_code=reason_code,
        reason_detail=reason_code,
    )


def _log_rejected_narration(
    response: Any,
    reason_detail: str,
    offending_token: Optional[str] = None,
) -> None:
    """Keep rejected provider prose diagnosable without adding it to trace/UI."""
    try:
        rejected_text = response if isinstance(response, str) else repr(response)
        token = " ".join(str(offending_token or "").split())[:80]
        diagnostic = f"ENEMY_BATCH_NARRATION_REJECTED rule={reason_detail} "
        if token:
            diagnostic += f"offending_token={token!r} "
        message = f"{diagnostic}text={rejected_text}"
        debug(message[:1000], category="combat_events")
    except Exception:
        # Diagnostic logging cannot change the authoritative fallback path.
        pass


def narrate_enemy_batch(
    ledger: EnemyResolutionLedger,
    scene_context: Any,
    creature_descriptions: Any,
    llm_call: Callable[..., Any],
    receipt_observer: Optional[Callable[..., Any]] = None,
    tactical_plan_intent: Any = None,
) -> NarrationResult:
    """Make one combat-main narration call, or use exact deterministic ledger prose.

    The observer is a prebuilt router receipt callback, following the existing
    ``observer=...`` combat-main call convention. Router errors intentionally
    propagate so terminal outcomes remain owned by the router and combat loop.
    """
    if not isinstance(ledger, EnemyResolutionLedger):
        raise TypeError("ledger must be a completed EnemyResolutionLedger")
    try:
        messages = build_enemy_batch_narration_messages(
            ledger,
            scene_context,
            creature_descriptions,
            tactical_plan_intent=tactical_plan_intent,
        )
    except ValueError as exc:
        if str(exc) == "enemy_narration_ledger_too_large":
            return _template_result(ledger, "ledger_too_large")
        raise

    response = llm_call(
        "combat_main",
        messages,
        json_output=False,
        observer=receipt_observer,
    )
    text, parse_reason = _response_text(response)
    if parse_reason:
        _log_rejected_narration(response, parse_reason)
        return _template_result(ledger, parse_reason)
    reason = _check_narration(text or "", ledger, creature_descriptions)
    if reason:
        offending_token = (
            _first_unknown_name(
                text or "", _all_allowed_names(ledger, creature_descriptions)
            ) if reason == "unknown_name" else None
        )
        _log_rejected_narration(text or "", reason, offending_token)
        return _template_result(ledger, reason)
    return NarrationResult(text=text or "", source="llm", reason_code=None)
