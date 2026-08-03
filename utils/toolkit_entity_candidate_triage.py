# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Entity Candidate Triage
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Deterministic source extraction may emit broad entity candidates.
This module provides schema constants, validation helpers, and report
builders for adjudicating whether a candidate can become a canonical
entity and what semantic category it belongs to.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from typing import Any, Dict, List, Optional, Set

TRIAGE_REPORT_VERSION = "entity_candidate_triage_report.v1"

# Allowed triage decisions
DECISION_KEEP = "keep"
DECISION_REJECT = "reject"
DECISION_RECLASSIFY = "reclassify"
TRIAGE_DECISIONS: Set[str] = frozenset({
    DECISION_KEEP,
    DECISION_REJECT,
    DECISION_RECLASSIFY,
})

# Allowed adjudicated types
TYPE_TRUE_NPC = "true_npc"
TYPE_SCENE_ACTOR = "scene_actor"
TYPE_MONSTER_ACTOR = "monster_actor"
TYPE_ITEM_OR_CLUE = "item_or_clue"
TYPE_LOCATION_NAME = "location_name"
TYPE_FACTION_NAME = "faction_name"
TYPE_PLOT_NOTE = "plot_note"
TYPE_TONE_MARKER = "tone_marker"
TYPE_NARRATIVE_PHRASE = "narrative_phrase"
TYPE_UNKNOWN = "unknown"

TRIAGE_TYPES: Set[str] = frozenset({
    TYPE_TRUE_NPC,
    TYPE_SCENE_ACTOR,
    TYPE_MONSTER_ACTOR,
    TYPE_ITEM_OR_CLUE,
    TYPE_LOCATION_NAME,
    TYPE_FACTION_NAME,
    TYPE_PLOT_NOTE,
    TYPE_TONE_MARKER,
    TYPE_NARRATIVE_PHRASE,
    TYPE_UNKNOWN,
})

ADJUDICATED_TYPE_ORDER: List[str] = [
    TYPE_TRUE_NPC,
    TYPE_SCENE_ACTOR,
    TYPE_MONSTER_ACTOR,
    TYPE_ITEM_OR_CLUE,
    TYPE_LOCATION_NAME,
    TYPE_FACTION_NAME,
    TYPE_PLOT_NOTE,
    TYPE_TONE_MARKER,
    TYPE_NARRATIVE_PHRASE,
    TYPE_UNKNOWN,
]

NON_ACTOR_TYPES: Set[str] = frozenset({
    TYPE_NARRATIVE_PHRASE,
    TYPE_PLOT_NOTE,
    TYPE_TONE_MARKER,
    TYPE_UNKNOWN,
})

ACTOR_TYPES: Set[str] = frozenset({
    TYPE_TRUE_NPC,
    TYPE_SCENE_ACTOR,
    TYPE_MONSTER_ACTOR,
    TYPE_ITEM_OR_CLUE,
    TYPE_LOCATION_NAME,
    TYPE_FACTION_NAME,
})

TRIAGE_REPORT_STATUS_PASS = "pass"
TRIAGE_REPORT_STATUS_DEGRADED = "degraded"
TRIAGE_REPORT_STATUS_FAILED = "failed"
TRIAGE_REPORT_STATUS_SKIPPED = "skipped"

TRIAGE_REPORT_STATUSES: Set[str] = frozenset({
    TRIAGE_REPORT_STATUS_PASS,
    TRIAGE_REPORT_STATUS_DEGRADED,
    TRIAGE_REPORT_STATUS_FAILED,
    TRIAGE_REPORT_STATUS_SKIPPED,
})


def validate_decision(decision: str) -> bool:
    return decision in TRIAGE_DECISIONS


def validate_adjudicated_type(adjudicated_type: str) -> bool:
    return adjudicated_type in TRIAGE_TYPES


def validate_report_status(status: str) -> bool:
    return status in TRIAGE_REPORT_STATUSES


def is_non_actor_decision(decision_dict: Dict[str, Any]) -> bool:
    return decision_dict.get("adjudicated_type") in NON_ACTOR_TYPES


def is_actor_decision(decision_dict: Dict[str, Any]) -> bool:
    return decision_dict.get("adjudicated_type") in ACTOR_TYPES


def is_rejected(decision_dict: Dict[str, Any]) -> bool:
    return decision_dict.get("decision") == DECISION_REJECT


def is_kept(decision_dict: Dict[str, Any]) -> bool:
    return decision_dict.get("decision") == DECISION_KEEP


def build_triage_decision(
    candidate_text: str,
    candidate_slug: str,
    proposed_type: str,
    adjudicated_type: str,
    decision: str,
    reason: str,
    source_refs: Optional[List[Dict[str, Any]]] = None,
    location_bindings: Optional[List[str]] = None,
    plot_bindings: Optional[List[str]] = None,
    faction_bindings: Optional[List[str]] = None,
    source_role: Optional[str] = None,
) -> Dict[str, Any]:
    if not isinstance(candidate_text, str) or not candidate_text.strip():
        raise ValueError("candidate_text must be a non-empty string")
    if not isinstance(candidate_slug, str) or not candidate_slug.strip():
        raise ValueError("candidate_slug must be a non-empty string")
    if not validate_decision(decision):
        raise ValueError(
            f"Invalid decision '{decision}'. "
            f"Allowed: {sorted(TRIAGE_DECISIONS)}"
        )
    if not validate_adjudicated_type(adjudicated_type):
        raise ValueError(
            f"Invalid adjudicated_type '{adjudicated_type}'. "
            f"Allowed: {sorted(TRIAGE_TYPES)}"
        )

    result: Dict[str, Any] = {
        "candidate_text": candidate_text,
        "candidate_slug": candidate_slug,
        "proposed_type": proposed_type,
        "adjudicated_type": adjudicated_type,
        "decision": decision,
        "reason": reason,
    }

    if source_refs:
        result["source_refs"] = source_refs
    if location_bindings:
        result["location_bindings"] = location_bindings
    if plot_bindings:
        result["plot_bindings"] = plot_bindings
    if faction_bindings:
        result["faction_bindings"] = faction_bindings
    if source_role:
        result["source_role"] = source_role

    return result


def is_underbound_npc(decision_dict: Dict[str, Any]) -> bool:
    if decision_dict.get("decision") != DECISION_KEEP:
        return False
    if decision_dict.get("adjudicated_type") != TYPE_TRUE_NPC:
        return False
    bindings = (
        decision_dict.get("location_bindings")
        or decision_dict.get("plot_bindings")
        or decision_dict.get("faction_bindings")
        or decision_dict.get("source_role")
    )
    return not bool(bindings)


# ---------------------------------------------------------------------------
# Deterministic prefilter helpers (Step 1.2)
# ---------------------------------------------------------------------------

_PROSE_CONJUNCTION_PREFIXES: tuple = (
    "but ", "yet ", "however ", "although ", "though ",
    "while ", "when ", "because ", "if ", "unless ", "until ",
    "there is ", "there are ", "there was ", "there were ",
    "this is ", "that is ", "it is ", "it was ",
    "the ", "a ", "an ",
)


def looks_like_narrative_phrase(candidate_text: str) -> bool:
    text = candidate_text.strip()
    if not text:
        return False
    if text[0].isupper():
        return False
    lower = text.lower()
    for prefix in _PROSE_CONJUNCTION_PREFIXES:
        if lower.startswith(prefix):
            return True
    return False


def build_prefilter_decision(
    candidate: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    text = candidate.get("candidate_text", "") or ""
    slug = candidate.get("candidate_slug", "") or ""
    proposed = candidate.get("proposed_type", "") or "unknown"

    if not text or not slug:
        return None

    # 1. Existing lowercase prose / conjunction-prefix check
    if looks_like_narrative_phrase(text):
        return build_triage_decision(
            candidate_text=text,
            candidate_slug=slug,
            proposed_type=proposed,
            adjudicated_type=TYPE_NARRATIVE_PHRASE,
            decision=DECISION_REJECT,
            reason=(
                "Deterministic prefilter: text appears to be a prose "
                "narrative phrase, not a named entity candidate."
            ),
        )

    # 2. Full sentence / long clause check (catches uppercase-starting
    #    sentences that pass the lowercase-only narrative phrase check).
    if _looks_like_full_sentence_or_clause(text):
        return build_triage_decision(
            candidate_text=text,
            candidate_slug=slug,
            proposed_type=proposed,
            adjudicated_type=TYPE_NARRATIVE_PHRASE,
            decision=DECISION_REJECT,
            reason=(
                "Deterministic prefilter: text is a full sentence or "
                "long clause, not a named entity candidate."
            ),
        )

    # 3. One-word capitalized mechanic/effect verb in trap/table/effect
    #    context.  True one-word NPC names are NOT rejected because they
    #    either are not in _MECHANIC_EFFECT_VERBS or their context does
    #    not indicate mechanics material.
    words = text.strip().split()
    if len(words) == 1:
        word = words[0].strip(".,;:!?'\"()[]")
        if word in _MECHANIC_EFFECT_VERBS and _candidate_in_mechanics_context(candidate):
            return build_triage_decision(
                candidate_text=text,
                candidate_slug=slug,
                proposed_type=proposed,
                adjudicated_type=TYPE_NARRATIVE_PHRASE,
                decision=DECISION_REJECT,
                reason=(
                    "Deterministic prefilter: one-word mechanic/effect "
                    "verb in trap/table/spell/mechanics context."
                ),
            )

    return None


# ---------------------------------------------------------------------------
# Task 3.1: Extended non-actor prefiltering
# ---------------------------------------------------------------------------

_MECHANIC_EFFECT_VERBS: tuple = (
    "Awaken", "Enrage", "Menace", "Enthrall", "Irradiate", "Overwhelm",
)

_MECHANICS_CONTEXT_KEYWORDS: tuple = (
    "trap", "effect", "spell", "mechanic", "mechanics",
    "result", "complication", "trigger", "damage", "condition",
    "passive element", "active element",
)


def _looks_like_full_sentence_or_clause(text: str) -> bool:
    """Return True if text is a full sentence or long clause.

    Detects multi-word prose even when starting with an uppercase letter.
    True NPC names (multi-word title-cased phrases) are NOT rejected.
    """
    stripped = text.strip()
    if not stripped:
        return False
    words = [w for w in stripped.split() if w]
    if len(words) < 2:
        return False

    # Full sentences end with a period and have mixed case (lowercase words
    # after the first).  NPC names rarely if ever end with a period.
    if stripped.endswith("."):
        return True

    # Long clauses: 6+ words where at least 2 words after the first start
    # with a lowercase letter (mixed-case prose rather than title-cased
    # entity names).
    if len(words) >= 6:
        lower_start_count = 0
        for w in words[1:]:
            w_clean = w.lstrip("'\"(")
            if w_clean and w_clean[0].islower():
                lower_start_count += 1
        if lower_start_count >= 2:
            return True

    return False


def _candidate_in_mechanics_context(candidate: Dict[str, Any]) -> bool:
    """Return True if candidate context fields indicate trap/effect/
    spell/mechanics material.

    Inspects direct fields (context, section, source_role,
    proposed_type) and source_refs entries.  Handles missing or
    non-dict values fail-open.

    NOTE: The candidate 'source' field (e.g. 'table_cell') is an
    extraction technical detail, NOT semantic context, so it is NOT
    scanned here.  The keyword 'table' is also excluded because it
    matches identity-bearing table mentions (e.g. 'Table: NPC Name,
    Role, Location') and would cause false positives against true
    one-word NPC names from identity-bearing tables.
    """
    # Direct context fields (source is NOT scanned -- see docstring)
    for key in ("context", "section", "source_role"):
        val = candidate.get(key)
        if isinstance(val, str) and val.strip():
            val_lower = val.lower().strip()
            for kw in _MECHANICS_CONTEXT_KEYWORDS:
                if kw in val_lower:
                    return True

    # Proposed type
    ptype = (candidate.get("proposed_type") or "").lower().strip()
    if ptype in ("mechanic", "table_effect", "trap_effect"):
        return True

    # Source refs (source key NOT scanned -- see docstring)
    source_refs = candidate.get("source_refs")
    if isinstance(source_refs, list):
        for ref in source_refs:
            if not isinstance(ref, dict):
                continue
            for key in ("context", "section", "excerpt"):
                val = ref.get(key)
                if isinstance(val, str) and val.strip():
                    val_lower = val.lower().strip()
                    for kw in _MECHANICS_CONTEXT_KEYWORDS:
                        if kw in val_lower:
                            return True

    return False


def build_underbound_npc_findings(
    decisions: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, str]]]:
    warnings: List[Dict[str, str]] = []
    blockers: List[Dict[str, str]] = []

    for d in decisions:
        if not is_underbound_npc(d):
            continue
        slug = d.get("candidate_slug", "unknown")
        text = d.get("candidate_text", "unknown")
        warnings.append({
            "finding": f"Underbound NPC '{text}' ({slug})",
            "detail": (
                f"Kept NPC '{text}' has no location binding, plot binding, "
                f"faction binding, or explicit source role. "
                f"Review and add source-backed binding or reclassify."
            ),
            "candidate_slug": slug,
        })

    return {"warnings": warnings, "blockers": blockers}


def build_entity_candidate_triage_report(
    decisions: List[Dict[str, Any]],
    status: str = TRIAGE_REPORT_STATUS_PASS,
    warnings: Optional[List[Dict[str, Any]]] = None,
    blockers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    if not validate_report_status(status):
        raise ValueError(
            f"Invalid report status '{status}'. "
            f"Allowed: {sorted(TRIAGE_REPORT_STATUSES)}"
        )

    total = len(decisions)
    rejected_count = sum(1 for d in decisions if is_rejected(d))
    kept_count = sum(1 for d in decisions if is_kept(d))
    reclassified_count = sum(
        1 for d in decisions
        if d.get("decision") == DECISION_RECLASSIFY
    )
    non_actor_count = sum(1 for d in decisions if is_non_actor_decision(d))
    underbound_count = sum(1 for d in decisions if is_underbound_npc(d))

    type_counts: Dict[str, int] = {}
    for t in ADJUDICATED_TYPE_ORDER:
        count = sum(1 for d in decisions if d.get("adjudicated_type") == t)
        if count > 0:
            type_counts[t] = count

    report: Dict[str, Any] = {
        "triage_report_version": TRIAGE_REPORT_VERSION,
        "status": status,
        "total_candidates": total,
        "summary": {
            "kept": kept_count,
            "rejected": rejected_count,
            "reclassified": reclassified_count,
            "non_actor": non_actor_count,
            "underbound_npcs": underbound_count,
        },
        "type_counts": type_counts,
        "decisions": decisions,
    }

    if warnings:
        report["warnings"] = warnings
    if blockers:
        report["blockers"] = blockers

    return report
