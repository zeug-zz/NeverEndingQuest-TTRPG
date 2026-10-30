# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Phase Integrity Precheck
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Bounded deterministic precheck for explicit combat phase-integrity contradictions.
"""

import re
from typing import Any, Dict, List, Optional, Tuple


# Attribute only a verb in the same clause immediately following the named
# actor. A short, bounded modifier allowance handles ordinary prose without
# treating targets, attack-roll nouns, or a nearby later clause as actors.
_ACTOR_ACTION_TAIL = re.compile(
    r"^\s*(?:(?:then|now|quickly|immediately|finally)\s+)?"
    r"(?P<verb>attacks?|hits?|strikes?|shoots?|casts?|uses?|moves?|charges?)\b",
    re.IGNORECASE,
)
_PLANNED_ACTOR_ACTION_TAIL = re.compile(
    r"^\s*(?P<verb>attacks?|hits?|strikes?|shoots?|casts?|uses?|moves?|charges?)\b",
    re.IGNORECASE,
)
_NEGATED_ACTOR_ACTION = re.compile(
    r"^\s*(?:takes\s+no\s+action|does\s+not\s+(?:attack|hit|strike|shoot|cast|use|move|charge))\b",
    re.IGNORECASE,
)


def _normalize_name_key(value: Any) -> str:
    """Normalize a combat identity for deterministic comparisons."""
    if not isinstance(value, str):
        return ""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_")


def _strict_int(value: Any) -> Optional[int]:
    """Return an int only when the input is already a clean integer surface."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            try:
                return int(text)
            except ValueError:
                return None
    return None


def _extract_recent_already_applied_damage(conversation_history: Any) -> Optional[Dict[str, Any]]:
    """Extract the newest committed deterministic damage result from history."""
    if not isinstance(conversation_history, list):
        return None

    damage_pattern = re.compile(
        r"\[ALREADY_APPLIED\].*?dealt\s+(?P<amount>-?\d+)\s+damage\s+\((?P<flavor>.*?)\)\s+to\s+(?P<target>[^.]+?)\.\s+Result HP:\s*(?P<hp>-?\d+)\/(?P<max_hp>-?\d+)",
        re.IGNORECASE | re.DOTALL,
    )

    for message in reversed(conversation_history):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str) or "[ALREADY_APPLIED]" not in content:
            continue

        match = damage_pattern.search(content)
        if not match:
            continue

        amount = _strict_int(match.group("amount"))
        result_hp = _strict_int(match.group("hp"))
        max_hp = _strict_int(match.group("max_hp"))
        if amount is None or result_hp is None or max_hp is None:
            continue

        return {
            "target": _normalize_name_key(match.group("target")),
            "amount": abs(amount),
            "result_hp": result_hp,
            "max_hp": max_hp,
        }

    return None


def _iter_update_encounter_actions(response_json: Dict[str, Any]):
    """Yield updateEncounter actions from a combat response."""
    actions = response_json.get("actions", [])
    if not isinstance(actions, list):
        return

    for action in actions:
        if not isinstance(action, dict):
            continue
        action_name = str(action.get("action", "")).strip().lower()
        if action_name != "updateencounter":
            continue
        params = action.get("parameters", {})
        if not isinstance(params, dict):
            continue
        yield params


def _resolve_enemy_op_target_name(op_item: Dict[str, Any]) -> str:
    """Resolve the target name from a supported enemy op."""
    for key in ("creature", "target", "name"):
        reference = op_item.get(key)
        normalized = _normalize_name_key(reference)
        if normalized:
            return normalized
    return ""


def _extract_combined_text(response_json: Dict[str, Any]) -> str:
    """Build a combined text surface for deterministic phrase matching."""
    parts: List[str] = []
    for key in ("plan", "narration"):
        value = response_json.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)

    actions = response_json.get("actions", [])
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            params = action.get("parameters", {})
            if not isinstance(params, dict):
                continue
            for field in ("changes", "reason"):
                field_value = params.get(field)
                if isinstance(field_value, str) and field_value.strip():
                    parts.append(field_value)

    return "\n".join(parts)


def _contains_player_turn_prompt(text: str) -> bool:
    """Return True when text explicitly prompts for the next PC turn."""
    lowered = text.lower()
    prompts = (
        "what do you do",
        "it is your turn",
        "it's your turn",
        "your turn",
        "your move",
        "your action",
    )
    return any(prompt in lowered for prompt in prompts)


def _declares_pending_actor_turn(clause: str, actor: str) -> bool:
    """Recognize a few bounded actor-subject declaration forms in one clause."""
    words = [part for part in re.split(r"[^a-z0-9]+", actor.strip().lower()) if part]
    if not words:
        return False
    actor_pattern = r"[\s_-]+".join(map(re.escape, words))
    subject = re.match(
        r"^\s*(?:(?:then|now|quickly|immediately|finally|the)\s+)?"
        + actor_pattern
        + r"(?P<possessive>'s)?(?![a-z0-9])",
        clause,
        re.IGNORECASE,
    )
    if not subject:
        return False
    tail = clause[subject.end():]
    if re.match(
        r"\s+(?:attacks?|misses?|hits?|strikes?|shoots?|casts?|uses?|moves?|charges?)\b",
        tail,
        re.IGNORECASE,
    ):
        return True
    if re.match(
        r"\s*:\s*attack(?:\s+roll\b|\[\d+\](?=\s|$|[.,;])|\b)",
        tail,
        re.IGNORECASE,
    ):
        return True
    if subject.group("possessive") and re.match(
        r"\s+(?:[a-z0-9_-]+\s+){1,3}(?:attacks?|strikes?)\b",
        tail,
        re.IGNORECASE,
    ):
        return True
    return False


def _complete_enemy_batch_actor_coverage(response_json: Dict[str, Any], pending_enemies: Any) -> bool:
    """Require explicit canonical actor-subject declarations for the full cohort."""
    if not isinstance(pending_enemies, list) or not pending_enemies:
        return False
    texts: List[str] = []
    for key in ("plan", "narration"):
        value = response_json.get(key)
        if isinstance(value, str):
            texts.append(value)
    actions = response_json.get("actions", [])
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict) or str(action.get("action", "")).strip().lower() != "updateencounter":
                continue
            params = action.get("parameters", {})
            if isinstance(params, dict):
                for key in ("changes", "reason"):
                    value = params.get(key)
                    if isinstance(value, str):
                        texts.append(value)
    clauses = [
        clause.strip()
        for text in texts
        for clause in re.split(r"[.!?;\n]+", text)
        if clause.strip()
    ]
    covered = set()
    normalized_pending = set()
    for actor in pending_enemies:
        if not isinstance(actor, str) or not actor.strip():
            return False
        normalized_actor = _normalize_name_key(actor)
        if not normalized_actor or normalized_actor in normalized_pending:
            return False
        normalized_pending.add(normalized_actor)
        if any(_declares_pending_actor_turn(clause, actor) for clause in clauses):
            covered.add(normalized_actor)
    return covered == normalized_pending


def _complete_enemy_batch_handoff(response_json: Dict[str, Any], phase_state: Dict[str, Any]) -> bool:
    """Validate a trusted input seam, explicit cohort coverage, and legal round shape."""
    if phase_state.get("full_enemy_batch_intent") is not True:
        return False
    pending_enemies = phase_state.get("pending_enemies")
    if not _complete_enemy_batch_actor_coverage(response_json, pending_enemies):
        return False
    current_round = phase_state.get("current_round")
    candidate_round = response_json.get("combat_round")
    if type(current_round) is not int or type(candidate_round) is not int:
        return False
    if candidate_round == current_round:
        return True
    if candidate_round != current_round + 1:
        return False
    return (
        phase_state.get("pc_phase_complete") is True
        and phase_state.get("opening_batch_pending") is not True
    )


def _find_forbidden_actor_action(
    text: str, forbidden_actors: List[str]
) -> Optional[Dict[str, Any]]:
    """Find a bounded, syntactically attributed forbidden actor action."""
    for actor_name in forbidden_actors:
        if not isinstance(actor_name, str):
            continue
        trimmed = actor_name.strip()
        if not trimmed:
            continue
        actor_pattern = re.compile(rf"\b{re.escape(trimmed)}\b", re.IGNORECASE)
        for actor_match in actor_pattern.finditer(text):
            suffix = text[actor_match.end():actor_match.end() + 48]
            if _NEGATED_ACTOR_ACTION.match(suffix):
                continue
            action_match = _ACTOR_ACTION_TAIL.match(suffix)
            if not action_match:
                # Permit the explicit imperative construction "Have X attack Y";
                # do not generalize this to arbitrary nearby plan/narration text.
                prefix = text[max(0, actor_match.start() - 8):actor_match.start()]
                if re.search(r"\bhave\s+$", prefix, re.IGNORECASE):
                    action_match = _PLANNED_ACTOR_ACTION_TAIL.match(suffix)
            if not action_match:
                continue
            start = max(actor_match.start() - 6, 0)
            end = min(actor_match.end() + action_match.end() + 48, len(text))
            return {
                "name": trimmed,
                "start": start,
                "end": end,
                "verb": action_match.group("verb"),
            }
    return None


def _has_forbidden_actor_action(text: str, forbidden_actors: List[str]) -> Optional[str]:
    """Return actor name only when the same classifier attributes an action."""
    match = _find_forbidden_actor_action(text, forbidden_actors)
    return match["name"] if match else None


def describe_forbidden_actor_rejection(
    response_json: Dict[str, Any], phase_state: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Return bounded, read-only context for a forbidden-actor rejection.

    This reports the same bounded actor-attribution match used by validation.
    """
    if not isinstance(response_json, dict) or not isinstance(phase_state, dict):
        return None
    forbidden_actors = phase_state.get("forbidden_actors")
    if not isinstance(forbidden_actors, list):
        return None

    texts: List[Tuple[str, str]] = []
    for key in ("plan", "narration"):
        value = response_json.get(key)
        if isinstance(value, str) and value.strip():
            texts.append((key, value))
    actions = response_json.get("actions", [])
    if isinstance(actions, list):
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            params = action.get("parameters", {})
            if not isinstance(params, dict):
                continue
            for field in ("changes", "reason"):
                value = params.get(field)
                if isinstance(value, str) and value.strip():
                    texts.append(("actions[%d].parameters.%s" % (index, field), value))

    for actor_name in forbidden_actors:
        if not isinstance(actor_name, str) or not actor_name.strip():
            continue
        name = actor_name.strip()
        for field, text in texts:
            match = _find_forbidden_actor_action(text, [name])
            if match:
                window = text[match["start"]:match["end"]]
                return {
                    "matched_name": name[:128],
                    "source_field": field[:96],
                    "window_excerpt": window[:256],
                    "matched_verb": match["verb"][:32],
                }
    return None


def _has_exit_action(response_json: Dict[str, Any]) -> bool:
    """Return True if response actions include an exit action."""
    actions = response_json.get("actions", [])
    if not isinstance(actions, list):
        return False
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_name = action.get("action")
        if isinstance(action_name, str) and action_name.strip().lower() == "exit":
            return True
    return False


def validate_already_applied_enemy_replay_precheck(
    response_json: Dict[str, Any],
    encounter_data: Dict[str, Any],
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, str]:
    """Reject duplicate enemy hp_delta ops that replay an already-applied damage result."""
    if not isinstance(response_json, dict) or not isinstance(encounter_data, dict):
        return True, ""

    committed_damage = _extract_recent_already_applied_damage(conversation_history)
    if not committed_damage:
        return True, ""

    update_actions = list(_iter_update_encounter_actions(response_json))
    if not update_actions:
        return True, ""

    for params in update_actions:
        ops_payload = params.get("ops")
        if not isinstance(ops_payload, list):
            continue

        for op_item in ops_payload:
            if not isinstance(op_item, dict):
                continue
            op_name = str(op_item.get("op", "")).strip().lower()
            if op_name != "hp_delta":
                continue

            target_name = _resolve_enemy_op_target_name(op_item)
            if not target_name:
                continue
            if target_name != committed_damage["target"]:
                continue

            delta = _strict_int(op_item.get("delta"))
            if delta is None:
                return False, (
                    "Combat replay precheck failed: duplicate enemy hp_delta after [ALREADY_APPLIED] damage used a malformed delta. "
                    "Do not replay committed damage results."
                )

            if abs(delta) == committed_damage["amount"]:
                return False, (
                    "Combat replay precheck failed: duplicate enemy hp_delta re-applied the same committed damage after [ALREADY_APPLIED] history. "
                    "Do not emit ops for the already-applied result; advance to the next distinct combat effect instead."
                )

    return True, ""


def _simulate_enemy_post_response_state(
    encounter_data: Dict[str, Any],
    response_json: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Dict[str, Any]]], str]:
    """Simulate supported same-response enemy ops and return the resulting state."""
    creatures = encounter_data.get("creatures", [])
    if not isinstance(creatures, list):
        return None, "encounter_creatures_not_list"

    state: Dict[str, Dict[str, Any]] = {}
    for creature in creatures:
        if not isinstance(creature, dict):
            continue
        if str(creature.get("type", "")).strip().lower() != "enemy":
            continue

        name = str(creature.get("name", "")).strip()
        if not name:
            continue

        current_hp = _strict_int(creature.get("currentHitPoints", creature.get("hitPoints", 0)))
        if current_hp is None:
            return None, f"enemy_hp_not_int:{name}"

        state[_normalize_name_key(name)] = {
            "name": name,
            "current_hp": current_hp,
            "status": str(creature.get("status", "alive")).strip().lower(),
        }

    if not state:
        return {}, "ok"

    update_actions = list(_iter_update_encounter_actions(response_json))
    if not update_actions:
        return state, "ok"

    for params in update_actions:
        ops_payload = params.get("ops")
        if not isinstance(ops_payload, list):
            return None, "update_encounter_ops_not_list"

        for op_index, op_item in enumerate(ops_payload):
            if not isinstance(op_item, dict):
                return None, f"op_not_object:{op_index}"

            op_name = str(op_item.get("op", "")).strip().lower()
            if op_name not in {"hp_delta", "set_hp", "set_status"}:
                return None, f"unsupported_exit_simulation_op:{op_name}"

            target_name = _resolve_enemy_op_target_name(op_item)
            if not target_name or target_name not in state:
                return None, f"unknown_enemy_target:{target_name or op_index}"

            enemy_state = state[target_name]

            if op_name == "hp_delta":
                delta = _strict_int(op_item.get("delta"))
                if delta is None:
                    return None, f"hp_delta_missing_int_delta:{op_index}"
                enemy_state["current_hp"] += delta
                if enemy_state["current_hp"] <= 0:
                    enemy_state["status"] = "dead"
            elif op_name == "set_hp":
                hp_value = _strict_int(op_item.get("hp"))
                if hp_value is None:
                    return None, f"set_hp_missing_int_hp:{op_index}"
                enemy_state["current_hp"] = hp_value
            elif op_name == "set_status":
                status_value = str(op_item.get("status", "")).strip().lower()
                if status_value not in {"alive", "dead", "unconscious", "defeated"}:
                    return None, f"set_status_invalid_status:{status_value}"
                enemy_state["status"] = status_value

    return state, "ok"


def _encounter_has_living_hostiles(encounter_data: Dict[str, Any]) -> Optional[bool]:
    """Return True/False when authoritative, else None for fail-open."""
    creatures = encounter_data.get("creatures")
    if not isinstance(creatures, list):
        return None

    has_enemy = False
    for creature in creatures:
        if not isinstance(creature, dict):
            continue
        if str(creature.get("type", "")).lower() != "enemy":
            continue

        has_enemy = True
        status = str(creature.get("status", "alive")).strip().lower()
        current_hp = creature.get("currentHitPoints", creature.get("hitPoints"))
        try:
            hp_value = int(current_hp)
        except (TypeError, ValueError):
            # Fail-open when HP cannot be interpreted deterministically.
            return None

        if hp_value > 0 and status not in ("dead", "defeated", "unconscious"):
            return True

    if not has_enemy:
        return False
    return False


def validate_combat_phase_integrity_precheck(
    response_json: Dict[str, Any],
    encounter_data: Dict[str, Any],
    phase_state: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Validate explicit combat phase-integrity contradictions.

    This precheck is intentionally bounded and fail-open on ambiguity.
    """
    if not isinstance(response_json, dict):
        return True, ""
    if not isinstance(encounter_data, dict):
        return True, ""
    if phase_state is None:
        phase_state = {}
    if not isinstance(phase_state, dict):
        return True, ""

    combined_text = _extract_combined_text(response_json)

    # Guard 1: Forbidden phase actor actions.
    forbidden_actors = phase_state.get("forbidden_actors")
    if isinstance(forbidden_actors, list) and forbidden_actors:
        offending_actor = _has_forbidden_actor_action(combined_text, forbidden_actors)
        if offending_actor:
            return False, (
                "Combat phase integrity precheck failed: "
                f"forbidden actor '{offending_actor}' attempted an explicit action in current phase."
            )

    # Guard 2: Mid-enemy-batch stop.
    current_phase = phase_state.get("current_phase")
    pending_enemies = phase_state.get("pending_enemies")
    if (
        isinstance(current_phase, str)
        and current_phase.strip().upper() == "ENEMY_PHASE"
        and isinstance(pending_enemies, list)
        and len(pending_enemies) > 0
        and _contains_player_turn_prompt(combined_text)
    ):
        if _complete_enemy_batch_handoff(response_json, phase_state):
            pass
        else:
            return False, (
                "Combat phase integrity precheck failed: response stopped or prompted during ENEMY_PHASE "
                "before enemy batch completion."
            )

    # Guard 3: Illegal exit while hostiles remain.
    if _has_exit_action(response_json):
        has_living_hostiles = _encounter_has_living_hostiles(encounter_data)
        if has_living_hostiles is True:
            simulated_state, _ = _simulate_enemy_post_response_state(encounter_data, response_json)
            if simulated_state is None:
                return False, (
                    "Combat phase integrity precheck failed: exit action requested while living hostiles remain and post-response enemy op simulation was indeterminate. "
                    "Provide exact supported enemy hp_delta, set_hp, or set_status ops before exit."
                )

            living_after_simulation = False
            for enemy_state in simulated_state.values():
                try:
                    hp_value = int(enemy_state.get("current_hp", 0))
                except (TypeError, ValueError):
                    return False, (
                        "Combat phase integrity precheck failed: exit action requested while living hostiles remain and simulated HP could not be parsed. "
                        "Provide exact supported enemy hp_delta, set_hp, or set_status ops before exit."
                    )
                status_value = str(enemy_state.get("status", "alive")).strip().lower()
                if hp_value > 0 and status_value not in ("dead", "defeated", "unconscious"):
                    living_after_simulation = True
                    break

            if living_after_simulation:
                return False, (
                    "Combat phase integrity precheck failed: exit action requested while living hostiles remain after simulating supported same-response enemy ops. "
                    "Provide exact supported enemy hp_delta, set_hp, or set_status ops before exit."
                )

    # Guard 4: Illegal round increment before all PCs acted.
    ai_round = response_json.get("combat_round")
    current_round = phase_state.get("current_round")
    pc_phase_complete = phase_state.get("pc_phase_complete")
    if (
        isinstance(ai_round, int)
        and isinstance(current_round, int)
        and isinstance(pc_phase_complete, bool)
        and ai_round > current_round
        and pc_phase_complete is False
    ):
        return False, (
            "Combat phase integrity precheck failed: combat_round advanced before all required PCs acted."
        )

    return True, ""
