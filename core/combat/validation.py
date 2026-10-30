# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Response Validation - Provider-backed validation stage.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple

from core.combat.prompts import _extract_tracker_json_fence
from core.combat.debug_dumps import combat_debug_dumps_enabled
# TABLETOP MODE: Filter durable history metadata at the validation provider boundary.
from core.combat.turn_commit import conversation_history_for_prompt
from utils.deterministic_mechanics_precheck import has_explicit_bookkeeping_correction_claim
from utils.inventory_possession_authority import is_possession_query_turn
from utils.validation_routing import (
    combat_validation_skip_actions,
    is_reserved_jev_validation_reason,
)


# One-line rollback: set this to False to restore unconditional LLM validation
# and the previous outer deterministic-failure retry bound.
VALIDATION_ROUTING_ENABLED = True
DETERMINISTIC_VALIDATION_RETRY_CAP = 2

_KNOWN_COMBAT_ACTIONS = frozenset({
    "createEncounter",
    "updateEncounter",
    "updateTime",
    "updatePlot",
    "exitGame",
    "transitionLocation",
    "levelUp",
    "updateCharacterInfo",
    "updatePartyNPCs",
    "createNewModule",
    "establishHub",
    "storageInteraction",
    "updatePartyTracker",
    "moveBackgroundNPC",
    "updateSceneFollower",
    "saveGame",
    "restoreGame",
    "listSaves",
    "deleteSave",
    "rest",
    "resurrectCharacter",
    "requestRoll",
    "lookupMemory",
})


@dataclass(frozen=True)
class CombatValidationDependencies:
    """Owner-provided functions and values used by the validation stage."""

    parse_json_safely: Callable[[str], Any]
    phase_precheck: Callable[..., Any]
    replay_precheck: Callable[..., Any]
    narration_precheck: Callable[..., Any]
    enemy_boundary_precheck: Callable[..., Any]
    truth_pack_builder: Callable[..., Any]
    canonical_attack_facts_builder: Callable[..., Any]
    read_prompt: Callable[[str], str]
    compressed_combat: bool
    compression_enabled: bool
    compression_threshold_chars: int
    compression_decision: Callable[..., Any]
    telemetry_builder: Callable[..., Any]
    client: Any
    validation_model: str
    completion_params: Callable[..., Dict[str, Any]]
    trace_provider_call: Callable[..., Any]
    sanitize_for_logging: Callable[[Any], str]
    debug: Callable[..., Any]
    warning: Callable[..., Any]
    emit_console: Callable[[str], Any]
    usage_tracking_available: bool
    track_usage: Callable[[Any], Any]
    log_api_call: Callable[..., Any]
    export_open: Callable[..., Any]
    makedirs: Callable[..., Any]
    now: Callable[[], Any]
    format_log_timestamp: Callable[..., str]
    perf_counter: Callable[[], float]
    llm_call: Optional[Callable[..., Any]] = None
    receipt_observer_factory: Optional[Callable[..., Callable[..., Any]]] = None
    debug_dumps_enabled: Callable[[], bool] = combat_debug_dumps_enabled


_AUTHORITATIVE_PHASE_BLOCK_HEADING = (
    "=== AUTHORITATIVE COMBAT PHASE STATE (PYTHON; NOT CANDIDATE CLAIMS) ==="
)
_MAX_AUTHORITATIVE_PHASE_BLOCK_CHARS = 8192
_MAX_PHASE_CONTEXT_ACTORS = 16
_MAX_PHASE_CONTEXT_NAME_CHARS = 64


def _validation_routing_result(skip: bool, reason: str) -> Tuple[bool, str]:
    """Keep reserved Jev names un-emittable by the current router."""
    normalized_reason = str(reason or "")
    if is_reserved_jev_validation_reason(normalized_reason):
        return (False, "reserved_jev_reason_blocked")
    return (bool(skip), normalized_reason)


def decide_validation_routing(
    response_json: Any,
    user_input: str,
    *,
    deterministic_prechecks_passed: bool = True,
    full_enemy_batch_intent: bool = False,
    encounter_data: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Return a conservative combat validation skip decision and stable reason."""
    if not VALIDATION_ROUTING_ENABLED:
        return _validation_routing_result(False, "validation_routing_disabled")
    if not deterministic_prechecks_passed:
        return _validation_routing_result(False, "failed_prechecks")
    if not isinstance(response_json, dict):
        return _validation_routing_result(False, "parse_failure")

    narration = response_json.get("narration")
    actions = response_json.get("actions")
    if not isinstance(narration, str) or not narration.strip() or not isinstance(actions, list):
        return _validation_routing_result(False, "parse_failure")

    # The exact enemy-batch command is never eligible, even when manager state
    # could not be supplied to this helper.
    if full_enemy_batch_intent or str(user_input or "").strip() == "Enemies turn.":
        return _validation_routing_result(False, "enemy_batch_turn")

    if "combat_round" in response_json:
        requested_round = response_json.get("combat_round")
        current_round = (encounter_data or {}).get(
            "combat_round", (encounter_data or {}).get("current_round", 1)
        )
        try:
            requested_round = int(requested_round)
            current_round = int(current_round)
        except (TypeError, ValueError, OverflowError):
            return _validation_routing_result(False, "round_state_uncertain")
        if requested_round > current_round:
            return _validation_routing_result(False, "round_advance")

    try:
        if is_possession_query_turn(user_input):
            return _validation_routing_result(False, "possession_authority_required")
    except Exception:
        return _validation_routing_result(False, "possession_check_unavailable")

    try:
        if has_explicit_bookkeeping_correction_claim(response_json, user_input=user_input):
            return _validation_routing_result(False, "explicit_bookkeeping_correction")
    except Exception:
        return _validation_routing_result(False, "bookkeeping_check_unavailable")

    safe_actions = combat_validation_skip_actions()
    for action in actions:
        if not isinstance(action, dict):
            return _validation_routing_result(False, "unknown_action:malformed_action")
        action_name = action.get("action")
        if not isinstance(action_name, str) or not action_name.strip():
            return _validation_routing_result(False, "unknown_action:missing_action")
        action_name = action_name.strip()
        if action_name not in _KNOWN_COMBAT_ACTIONS:
            return _validation_routing_result(False, f"unknown_action:{action_name[:80]}")
        if action_name not in safe_actions:
            return _validation_routing_result(False, f"unsafe_action:{action_name[:80]}")
        parameters = action.get("parameters", {})
        if not isinstance(parameters, dict):
            return _validation_routing_result(False, f"unsafe_action_shape:{action_name}")

    return _validation_routing_result(True, "low_risk_actions_only")


def _trace_validation_routing_decision(
    skip: bool,
    reason: str,
    started_at: float,
) -> None:
    """Emit bounded routing telemetry without allowing it to affect control flow."""
    from utils import combat_latency_trace

    if not combat_latency_trace.trace_enabled():
        return
    outcome = "skip" if skip else "llm_path"
    try:
        combat_latency_trace.trace_decision(
            "validation_routing",
            "deterministic",
            started_at,
            provider_call_avoided=skip,
            outcome=outcome,
            skip_llm_validation=skip,
            reason=reason,
            skip_reason=reason,
        )
    except BaseException:
        # Routing telemetry is observational and fail-open by contract.
        return


def _bounded_phase_actor_names(value: Any) -> list:
    """Return a bounded, string-only projection for validator context."""
    if not isinstance(value, list):
        return []
    return [
        name[:_MAX_PHASE_CONTEXT_NAME_CHARS]
        for name in value[:_MAX_PHASE_CONTEXT_ACTORS]
        if isinstance(name, str)
    ]


def _extract_initiative_tracker_turn_window(
    multi_pc_manager: Any,
    encounter_data: Dict[str, Any],
) -> Optional[list]:
    """Read the turn window from the manager's deterministic tracker metadata."""
    formatter = getattr(multi_pc_manager, "format_initiative_tracker", None)
    if not callable(formatter):
        return None

    try:
        tracker_text = formatter(encounter_data)
        if not isinstance(tracker_text, str):
            return None

        _display_text, json_text = _extract_tracker_json_fence(tracker_text)
        if json_text is None:
            return None

        tracker_metadata = json.loads(json_text)
        if not isinstance(tracker_metadata, dict):
            return None
        turn_window = tracker_metadata.get("turn_window")
        if not isinstance(turn_window, list):
            return None
        return _bounded_phase_actor_names(turn_window)
    except Exception:
        return None


def _derive_authoritative_phase_state(
    multi_pc_manager: Any,
    encounter_data: Dict[str, Any],
    user_input: str,
) -> tuple:
    """Derive phase-precheck inputs and a bounded authoritative prompt view.

    The precheck dictionary intentionally retains its existing key/value shape
    so adding the validator context does not alter deterministic rejection
    behavior. The prompt view is a bounded projection of those same values.
    """
    current_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    try:
        current_round = int(current_round)
    except (TypeError, ValueError):
        current_round = 1

    current_phase = multi_pc_manager.combat_phase
    forbidden_actors = multi_pc_manager.get_forbidden_actors()
    pending_enemies = multi_pc_manager.get_remaining_enemies_for_round()
    pc_phase_complete = multi_pc_manager.pc_phase_complete
    opening_batch_pending = encounter_data.get("openingEnemyBatchPending") is True

    phase_state = {
        "current_phase": current_phase,
        "forbidden_actors": forbidden_actors,
        "pending_enemies": pending_enemies,
        "pc_phase_complete": pc_phase_complete,
        "current_round": current_round,
        "opening_batch_pending": opening_batch_pending,
    }
    full_enemy_batch_intent = (
        user_input == "Enemies turn."
        and str(current_phase).strip().upper() == "ENEMY_PHASE"
        and isinstance(pending_enemies, list)
        and bool(pending_enemies)
    )
    if full_enemy_batch_intent:
        # Preserve the existing precheck contract: this key was only present
        # when the exact input seam and live enemy-phase state both matched.
        phase_state["full_enemy_batch_intent"] = True

    turn_window = _extract_initiative_tracker_turn_window(
        multi_pc_manager, encounter_data
    )

    phase_context = {
        "phase": current_phase,
        "round": current_round,
        "forbidden_actors": _bounded_phase_actor_names(forbidden_actors),
        "pending_enemies": _bounded_phase_actor_names(pending_enemies),
        "pc_phase_complete": pc_phase_complete,
        "opening_batch_pending": opening_batch_pending,
        "full_enemy_batch_intent": full_enemy_batch_intent,
    }
    if turn_window is not None:
        phase_context["current_turn_window"] = turn_window
    if isinstance(phase_context["phase"], str):
        phase_context["phase"] = phase_context["phase"][:64]
    return phase_state, phase_context


def validate_combat_response(
    response: str,
    encounter_data: Dict[str, Any],
    user_input: str,
    conversation_history: Optional[list] = None,
    multi_pc_manager: Any = None,
    *,
    dependencies: CombatValidationDependencies,
) -> Any:
    """Validate response using injected dependencies; preserve legacy order/policy."""
    parse_json_safely = dependencies.parse_json_safely
    read_prompt_from_file = dependencies.read_prompt
    USE_COMPRESSED_COMBAT = dependencies.compressed_combat
    debug = dependencies.debug
    warning = dependencies.warning
    json_decode_error = json.JSONDecodeError
    emit = dependencies.emit_console
    routing_started_at = dependencies.perf_counter()
    deterministic_prechecks_passed = True
    emit("[COMBAT_MANAGER] Starting validation for combat response")

    if multi_pc_manager:
        try:
            response_json = parse_json_safely(response)
            if response_json:
                ai_round = response_json.get("combat_round")
                current_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
                if isinstance(ai_round, int) and ai_round > current_round:
                    pending_pcs = multi_pc_manager.get_available_pcs()
                    if pending_pcs:
                        debug(f"VALIDATION_FAIL: Round advance blocked. Pending PCs: {pending_pcs}", category="combat_validation")
                        _trace_validation_routing_decision(
                            False, "failed_prechecks:round_advance", routing_started_at
                        )
                        return (
                            f"VALIDATION FAILURE: You attempted to advance to Round {ai_round}, but the following Player Characters have NOT acted in Round {current_round}: {', '.join(pending_pcs)}.\n\n"
                            "THE GOLDEN RULE OF MULTI-PC COMBAT:\n"
                            "1. You CANNOT end the round until ALL PCs have taken their turns.\n"
                            "2. STOP your narration immediately.\n"
                            f"3. Prompt {pending_pcs[0]} for their action.\n"
                            f"4. Keep 'combat_round' as {current_round}."
                        )
        except Exception as error:
            deterministic_prechecks_passed = False
            debug(f"VALIDATION_ERROR: Error in Multi-PC guardrail: {error}", category="combat_validation")

    authoritative_phase_context = None
    phase_state = None
    if multi_pc_manager:
        try:
            phase_state, authoritative_phase_context = _derive_authoritative_phase_state(
                multi_pc_manager, encounter_data, user_input
            )
        except Exception as error:
            deterministic_prechecks_passed = False
            debug(f"VALIDATION_ERROR: Phase-integrity precheck failed open due to error: {error}", category="combat_validation")

    if multi_pc_manager:
        try:
            response_json = parse_json_safely(response)
            if response_json and isinstance(response_json, dict):
                if phase_state is None:
                    raise RuntimeError("authoritative phase state unavailable")
                phase_ok, phase_reason = dependencies.phase_precheck(response_json, encounter_data, phase_state=phase_state)
                if not phase_ok:
                    if "forbidden actor" in str(phase_reason).lower():
                        try:
                            from utils.combat_latency_trace import trace_enabled, trace_combat_observation
                            if trace_enabled():
                                from utils.combat_phase_integrity_precheck import describe_forbidden_actor_rejection

                                match = describe_forbidden_actor_rejection(response_json, phase_state)
                                if match:
                                    structured_actions = []
                                    actions = response_json.get("actions", [])
                                    if isinstance(actions, list):
                                        for action_index, action in enumerate(actions[:8]):
                                            if not isinstance(action, dict):
                                                continue
                                            params = action.get("parameters", {})
                                            if not isinstance(params, dict):
                                                params = {}
                                            structured_actions.append({
                                                "action_type": str(action.get("action", ""))[:80],
                                                "actors": {
                                                    key: str(action[key])[:64]
                                                    for key in ("actor", "source", "attacker")
                                                    if action.get(key) not in (None, "")
                                                } | {
                                                    key: str(params[key])[:64]
                                                    for key in ("actor", "source", "attacker")
                                                    if params.get(key) not in (None, "")
                                                },
                                                "targets": {
                                                    key: str(action[key])[:64]
                                                    for key in ("target", "creature")
                                                    if action.get(key) not in (None, "")
                                                } | {
                                                    key: str(params[key])[:64]
                                                    for key in ("target", "creature", "name")
                                                    if params.get(key) not in (None, "")
                                                },
                                            })
                                    trace_combat_observation(
                                        "phase_precheck_forbidden_actor_reject",
                                        current_phase=str(phase_state.get("current_phase", ""))[:48],
                                        forbidden_names=[str(name)[:64] for name in phase_state.get("forbidden_actors", [])[:16]
                                                         if isinstance(name, str)],
                                        attempt_identity={
                                            "encounter_id": str(encounter_data.get("encounterId", encounter_data.get("id", "unknown")))[:96],
                                            "round": response_json.get("combat_round", phase_state.get("current_round")),
                                            "action_count": len(actions) if isinstance(actions, list) else 0,
                                        },
                                        structured_actions=structured_actions,
                                        match=match,
                                    )
                        except Exception:
                            pass
                    debug(f"VALIDATION_FAIL: Phase-integrity precheck rejected response: {phase_reason}", category="combat_validation")
                    _trace_validation_routing_decision(
                        False, "failed_prechecks:phase_integrity", routing_started_at
                    )
                    return f"VALIDATION FAILURE: {phase_reason}"
        except Exception as error:
            deterministic_prechecks_passed = False
            debug(f"VALIDATION_ERROR: Phase-integrity precheck failed open due to error: {error}", category="combat_validation")

    response_json = None
    try:
        response_json = parse_json_safely(response)
        if response_json and isinstance(response_json, dict):
            narration_ok, narration_reason = dependencies.narration_precheck(response_json, encounter_data)
            if not narration_ok:
                debug(f"VALIDATION_FAIL: Narration-consistency precheck rejected response: {narration_reason}", category="combat_validation")
                _trace_validation_routing_decision(
                    False, "failed_prechecks:narration_consistency", routing_started_at
                )
                return f"VALIDATION FAILURE: {narration_reason}"
            routing_ok, routing_reason = dependencies.enemy_boundary_precheck(response_json, encounter_data)
            if not routing_ok:
                try:
                    from utils.combat_latency_trace import trace_enabled, trace_combat_observation

                    # Check the existing gate before constructing any diagnostic payload.
                    if trace_enabled():
                        actions = response_json.get("actions", [])
                        actions = actions if isinstance(actions, list) else []
                        selected_actions = []
                        flat_operations = {}
                        operation_count = 0
                        changes_count = 0
                        captured_changes_count = 0
                        captured_operation_count = 0
                        for action_index, action in enumerate(actions):
                            if not isinstance(action, dict) or action.get("action") != "updateEncounter":
                                continue
                            params = action.get("parameters", {})
                            if not isinstance(params, dict):
                                continue
                            changes = params.get("changes", "")
                            ops = params.get("ops", [])
                            ops = ops if isinstance(ops, list) else []
                            changes_count += bool(isinstance(changes, str) and changes)
                            operation_count += len(ops)
                            if len(selected_actions) >= 4:
                                continue
                            if isinstance(changes, str) and changes:
                                captured_changes_count += 1
                            for local_op_index, op in enumerate(ops):
                                if captured_operation_count >= 4:
                                    break
                                if not isinstance(op, dict):
                                    captured_operation_count += 1
                                    continue
                                prefix = "operation_%d_" % captured_operation_count
                                flat_operations[prefix + "action_index"] = action_index
                                flat_operations[prefix + "index"] = local_op_index
                                for source_key, output_key in (("op", "operation"), ("creature", "creature"),
                                                               ("target", "target"), ("delta", "delta")):
                                    value = op.get(source_key)
                                    if value is None or isinstance(value, (str, int, float, bool)):
                                        flat_operations[prefix + output_key] = value[:16] if isinstance(value, str) else value
                                captured_operation_count += 1
                            selected_actions.append({
                                "action_index": action_index,
                                "action": "updateEncounter",
                                "changes": changes[:96] if isinstance(changes, str) else "",
                                "changes_truncated": max(0, len(changes) - 96) if isinstance(changes, str) else 0,
                            })
                        trace_combat_observation(
                            "enemy_routing_precheck_reject",
                            reason=str(routing_reason)[:128],
                            reason_chars=len(str(routing_reason)),
                            reason_truncated=max(0, len(str(routing_reason)) - 128),
                            changes=selected_actions,
                            **flat_operations,
                            action_count=len(actions),
                            captured_action_count=len(selected_actions),
                            changes_count=changes_count,
                            operation_count=operation_count,
                            changes_truncated=max(0, changes_count - captured_changes_count),
                            operations_truncated=max(0, operation_count - captured_operation_count),
                        )
                except Exception:
                    pass
                debug(f"VALIDATION_FAIL: Enemy-routing precheck rejected response: {routing_reason}", category="combat_validation")
                _trace_validation_routing_decision(
                    False, "failed_prechecks:enemy_routing", routing_started_at
                )
                return f"VALIDATION FAILURE: {routing_reason}"
    except Exception as error:
        deterministic_prechecks_passed = False
        debug(f"VALIDATION_ERROR: Narration/routing prechecks failed open due to error: {error}", category="combat_validation")

    try:
        replay_ok, replay_reason = dependencies.replay_precheck(
            response_json, encounter_data, conversation_history=conversation_history
        )
        if not replay_ok:
            debug(f"VALIDATION_FAIL: Already-applied replay precheck rejected response: {replay_reason}", category="combat_validation")
            _trace_validation_routing_decision(
                False, "failed_prechecks:replay", routing_started_at
            )
            return f"VALIDATION FAILURE: {replay_reason}"
    except Exception as error:
        deterministic_prechecks_passed = False
        debug(f"VALIDATION_ERROR: Already-applied replay precheck failed open due to error: {error}", category="combat_validation")

    routing_started_at = dependencies.perf_counter()
    should_skip_validation, validation_routing_reason = decide_validation_routing(
        response_json,
        user_input,
        deterministic_prechecks_passed=deterministic_prechecks_passed,
        full_enemy_batch_intent=bool(
            isinstance(phase_state, dict)
            and phase_state.get("full_enemy_batch_intent") is True
        ),
        encounter_data=encounter_data,
    )
    _trace_validation_routing_decision(
        should_skip_validation, validation_routing_reason, routing_started_at
    )
    if should_skip_validation:
        validation_routing_telemetry = {
            "skip_llm_validation": True,
            "skip_reason": validation_routing_reason,
            "used_validation_compression": False,
            "compression_reason": "validation_skipped",
            "validation_payload_chars": 0,
        }
        try:
            validation_routing_telemetry = dependencies.telemetry_builder(
                skip_llm_validation=True,
                skip_reason=validation_routing_reason,
                used_validation_compression=False,
                compression_reason="validation_skipped",
                validation_payload_chars=0,
            )
        except Exception:
            validation_routing_telemetry["compression_reason"] = "telemetry_builder_error_fallback"
            debug("VALIDATION: Telemetry helper failed; using fallback telemetry payload.", category="combat_validation")
        debug(
            f"VALIDATION_ROUTING_TELEMETRY: {json.dumps(validation_routing_telemetry)}",
            category="combat_validation",
        )
        debug(
            f"VALIDATION: Deterministic routing skipped LLM validation ({validation_routing_reason})",
            category="combat_validation",
        )
        return True

    debug("VALIDATION: Validating combat response...", category="combat_validation")
    try:
        response_json = json.loads(response)
        combat_round = response_json.get("combat_round", "unknown")
        num_actions = len(response_json.get("actions", []))
        has_plan = "plan" in response_json
        debug(f"VALIDATION_CONTEXT: Round={combat_round}, Actions={num_actions}, HasPlan={has_plan}", category="combat_validation")
    except Exception:
        debug("VALIDATION_CONTEXT: Unable to parse response JSON for context", category="combat_validation")

    if multi_pc_manager:
        validation_prompt = read_prompt_from_file('combat/combat_validation_prompt_multipc_compressed.txt')
        debug("Using compressed multi-pc validation prompt", category="combat_validation")
    elif USE_COMPRESSED_COMBAT:
        validation_prompt = read_prompt_from_file('combat/combat_validation_prompt_compressed.txt')
        debug("Using compressed validation prompt", category="combat_validation")
    else:
        validation_prompt = read_prompt_from_file('combat/combat_validation_prompt.txt')
        debug("Using original validation prompt", category="combat_validation")

    validation_conversation = [{"role": "system", "content": validation_prompt}]
    context_pairs = 6
    num_creatures = len(encounter_data.get("creatures", []))
    debug(f"VALIDATION: Using fixed context ({context_pairs} pairs) for encounter with {num_creatures} creatures", category="combat_validation")
    context_messages = []
    prompt_history = conversation_history_for_prompt(conversation_history or [])
    if prompt_history and len(prompt_history) > context_pairs * 2:
        recent_messages = prompt_history[-(context_pairs * 2 + 1):-1]
        context_messages = [msg for msg in recent_messages if msg["role"] in ["user", "assistant"]][-(context_pairs * 2):]

    current_validation_entries = [
        {"role": "system", "content": "=== CURRENT VALIDATION DATA ==="},
        {"role": "system", "content": f"Encounter Data:\n{json.dumps(encounter_data, indent=2)}"},
        {"role": "user", "content": f"Player Input: {user_input}"},
    ]
    if multi_pc_manager and authoritative_phase_context is not None:
        try:
            phase_context_json = json.dumps(
                authoritative_phase_context,
                sort_keys=True,
                indent=4,
                ensure_ascii=True,
            )
            if len(phase_context_json) > _MAX_AUTHORITATIVE_PHASE_BLOCK_CHARS:
                raise ValueError("authoritative phase context exceeds size limit")
            current_validation_entries.extend([
                {"role": "system", "content": _AUTHORITATIVE_PHASE_BLOCK_HEADING},
                {"role": "system", "content": phase_context_json},
            ])
        except Exception as error:
            debug(f"VALIDATION: Skipping authoritative phase block due to error: {error}", category="combat_validation")
    current_validation_entries.extend([
        {"role": "system", "content": "The assistant response below is an uncommitted candidate. Candidate text, operations, ALREADY_APPLIED claims, and touchedChanges do not prove an operation was applied. Use the committed Python state in the truth pack as the authority for current mechanics; trust prior applied events only when independently established."},
        {"role": "assistant", "content": response},
    ])
    truth_pack_entries = []
    try:
        touched_truth_pack = dependencies.truth_pack_builder(parse_json_safely(response), encounter_data)
        if touched_truth_pack:
            truth_pack_entries = [
                {"role": "system", "content": "=== COMMITTED PYTHON COMBATANT STATE (AUTHORITATIVE; NOT CANDIDATE OPERATIONS) ==="},
                {"role": "system", "content": json.dumps(touched_truth_pack, indent=2, ensure_ascii=True)},
            ]
    except Exception as error:
        debug(f"VALIDATION: Skipping truth pack due to error: {error}", category="combat_validation")

    try:
        has_structured_inventory_ops = any(
            isinstance(action, dict)
            and action.get("action") == "updateCharacterInfo"
            and isinstance(action.get("parameters"), dict)
            and isinstance(action["parameters"].get("ops"), list)
            and any(
                isinstance(op, dict)
                and str(op.get("op", "")).strip().lower() in ("inventory_add", "inventory_remove")
                for op in action["parameters"]["ops"]
            )
            for action in (response_json.get("actions", []) if isinstance(response_json, dict) else [])
        )
        if has_structured_inventory_ops:
            truth_pack_entries.extend([
                {"role": "system", "content": "=== INVENTORY OPERATION AUTHORITY ==="},
                {"role": "system", "content": (
                    "Use the committed canonical container selected by the structured operation. "
                    "inventory_remove defaults to equipment unless container=ammunition or "
                    "item_type=ammunition is explicit; item names alone do not select ammunition. "
                    "Equipment and ammunition are separate; do not duplicate or redirect items."
                )},
            ])
    except Exception:
        pass

    canonical_attack_entries = []
    try:
        canonical_attack_facts = dependencies.canonical_attack_facts_builder(encounter_data)
        if canonical_attack_facts:
            canonical_attack_entries = [
                {"role": "system", "content": "=== CANONICAL NON-PC ATTACK/STAT FACTS (SOURCE-BACKED; READ-ONLY) ==="},
                {"role": "system", "content": json.dumps(canonical_attack_facts, indent=2, ensure_ascii=True)},
            ]
    except Exception as error:
        debug(f"VALIDATION: Skipping canonical attack facts due to error: {error}", category="combat_validation")

    validation_preview = list(validation_conversation)
    if context_messages:
        validation_preview.append({"role": "system", "content": f"=== PREVIOUS COMBAT CONTEXT (last {context_pairs} exchanges) ==="})
        validation_preview.extend(context_messages)
    validation_preview.extend(truth_pack_entries)
    validation_preview.extend(current_validation_entries)
    validation_payload_chars = sum(len(json.dumps(msg)) for msg in validation_preview)
    use_validation_compression = False
    compression_reason = "decision_helper_default_uncompressed"
    try:
        use_validation_compression, compression_reason = dependencies.compression_decision(
            total_chars=validation_payload_chars,
            compression_enabled=dependencies.compression_enabled,
            threshold_chars=dependencies.compression_threshold_chars,
        )
    except Exception as error:
        use_validation_compression = False
        compression_reason = "decision_helper_error_default_uncompressed"
        debug(f"VALIDATION: Compression decision helper failed; using uncompressed fallback. Error: {error}", category="combat_validation")

    used_validation_compression = False
    if context_messages:
        if use_validation_compression:
            try:
                compressed_context = []
                user_message_count = 0
                total_user_messages = sum(1 for msg in context_messages if msg["role"] == "user")
                for msg in context_messages:
                    if msg["role"] == "user":
                        user_message_count += 1
                        if user_message_count <= total_user_messages - 2:
                            content = msg.get("content", "")
                            if isinstance(content, str) and len(content) > 1200:
                                content = content[:1200] + " [truncated]"
                            compressed_context.append({"role": "user", "content": content})
                            debug(f"VALIDATION: Compressed user message {user_message_count}/{total_user_messages}", category="combat_validation")
                        else:
                            compressed_context.append(msg)
                            debug(f"VALIDATION: Keeping user message {user_message_count}/{total_user_messages} uncompressed", category="combat_validation")
                    else:
                        compressed_context.append(msg)
                validation_conversation.append({"role": "system", "content": f"=== PREVIOUS COMBAT CONTEXT (last {context_pairs} exchanges with compression) ==="})
                validation_conversation.extend(compressed_context)
                used_validation_compression = True
            except Exception as error:
                compression_reason = "compression_apply_error_fallback_uncompressed"
                use_validation_compression = False
                used_validation_compression = False
                debug(f"VALIDATION: Compression apply failed; falling back to uncompressed context. Error: {error}", category="combat_validation")
                validation_conversation.append({"role": "system", "content": f"=== PREVIOUS COMBAT CONTEXT (last {context_pairs} exchanges) ==="})
                validation_conversation.extend(context_messages)
        else:
            validation_conversation.append({"role": "system", "content": f"=== PREVIOUS COMBAT CONTEXT (last {context_pairs} exchanges) ==="})
            validation_conversation.extend(context_messages)
    validation_conversation.extend(truth_pack_entries)
    validation_conversation.extend(canonical_attack_entries)
    validation_conversation.extend(current_validation_entries)

    validation_routing_telemetry = {
        "skip_llm_validation": False,
        "skip_reason": validation_routing_reason,
        "used_validation_compression": bool(used_validation_compression),
        "compression_reason": str(compression_reason),
        "validation_payload_chars": int(validation_payload_chars),
    }
    try:
        validation_routing_telemetry = dependencies.telemetry_builder(
            skip_llm_validation=False, skip_reason=validation_routing_reason,
            used_validation_compression=used_validation_compression,
            compression_reason=compression_reason, validation_payload_chars=validation_payload_chars,
        )
    except Exception:
        validation_routing_telemetry["compression_reason"] = "telemetry_builder_error_fallback"
        debug("VALIDATION: Telemetry helper failed; using fallback telemetry payload.", category="combat_validation")
    debug(f"VALIDATION_ROUTING_TELEMETRY: {json.dumps(validation_routing_telemetry)}", category="combat_validation")

    if dependencies.debug_dumps_enabled():
        with dependencies.export_open("validation_messages_to_api.json", "w", encoding="utf-8") as handle:
            json.dump(validation_conversation, handle, indent=2, ensure_ascii=False)
    validation_size = sum(len(json.dumps(msg)) for msg in validation_conversation)
    if dependencies.debug_dumps_enabled():
        emit("DEBUG: [VALIDATION] Exported validation messages to validation_messages_to_api.json")
    emit(f"DEBUG: [VALIDATION] Total validation context size: {validation_size:,} characters ({len(validation_conversation)} messages)")

    max_validation_retries = 5
    for attempt in range(max_validation_retries):
        try:
            observer = dependencies.receipt_observer_factory(
                endpoint_name="combat_validation",
                messages=validation_conversation,
                legacy_context={
                    "endpoint": "combat_validation",
                    "function": "validate_combat_response",
                    "purpose": "combat_validation",
                    "temperature": 0.3,
                    "attempt": attempt + 1,
                },
                trace_site="combat_validation",
                track_usage=dependencies.usage_tracking_available,
                api_log_before_tracker=True,
            ) if dependencies.receipt_observer_factory is not None else None
            validation_response = dependencies.llm_call(
                task="combat_validation",
                messages=validation_conversation,
                json_output=False,
                json_contract=True,
                temperature=0.3,
                observer=observer,
            ).strip()
            try:
                validation_json = parse_json_safely(validation_response)
                is_valid = validation_json.get("valid", False)
                feedback_obj = validation_json.get("feedback", {})
                positive = dependencies.sanitize_for_logging(feedback_obj.get("positive", "None."))
                negative = dependencies.sanitize_for_logging(feedback_obj.get("negative", "No reason provided."))
                recommendation = dependencies.sanitize_for_logging(feedback_obj.get("recommendation", "No recommendation provided."))
                if dependencies.debug_dumps_enabled():
                    dependencies.makedirs(os.path.join("debug", "combat"), exist_ok=True)
                    timestamp = dependencies.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    encounter_id = encounter_data.get("encounterId", "unknown").replace("/", "_")
                    filename = f"validation_{timestamp}_{encounter_id}_attempt{attempt + 1}.json"
                    path = os.path.join("debug", "combat", filename)
                    with dependencies.export_open(path, "w") as log_file:
                        log_entry = {
                            "timestamp": dependencies.format_log_timestamp("%Y-%m-%d %H:%M:%S"),
                            "encounter_size": num_creatures, "context_pairs": context_pairs,
                            "attempt": attempt + 1, "valid": is_valid,
                            "feedback": {"positive": dependencies.sanitize_for_logging(positive),
                                         "negative": dependencies.sanitize_for_logging(negative),
                                         "recommendation": dependencies.sanitize_for_logging(recommendation)},
                            "response": dependencies.sanitize_for_logging(response),
                        }
                        json.dump(log_entry, log_file)
                        log_file.write("\n")
                if is_valid:
                    emit("[COMBAT_MANAGER] Validation PASSED")
                    debug(f"VALIDATION: Passed. Positive feedback: {positive}", category="combat_validation")
                    return True
                emit(f"[COMBAT_MANAGER] Validation FAILED: {dependencies.sanitize_for_logging(negative)}")
                debug(f"VALIDATION: Failed. Negative feedback: {dependencies.sanitize_for_logging(negative)}", category="combat_validation")
                negative_lower = negative.lower()
                if "round" in negative_lower and ("increment" in negative_lower or "advance" in negative_lower):
                    debug("VALIDATION_RULE: ROUND_TRACKING_ACCURACY violation detected", category="combat_validation")
                elif "golden rule" in negative_lower or "mid-round" in negative_lower:
                    debug("VALIDATION_RULE: GOLDEN_RULE_VIOLATION detected", category="combat_validation")
                elif "hp" in negative_lower or "hit point" in negative_lower or "damage" in negative_lower:
                    debug("VALIDATION_RULE: HP_TRACKING violation detected", category="combat_validation")
                elif "death" in negative_lower or "dead" in negative_lower or "0 hp" in negative_lower:
                    debug("VALIDATION_RULE: DEATH_DETECTION violation detected", category="combat_validation")
                elif "initiative" in negative_lower and "order" in negative_lower:
                    debug("VALIDATION_RULE: INITIATIVE_ORDER violation detected", category="combat_validation")
                elif "player" in negative_lower and ("roll" in negative_lower or "dice" in negative_lower):
                    debug("VALIDATION_RULE: PLAYER_INTERACTION_FLOW violation detected", category="combat_validation")
                elif "plan" in negative_lower:
                    debug("VALIDATION_RULE: PLAN_VALIDATION violation detected", category="combat_validation")
                elif "json" in negative_lower or "format" in negative_lower:
                    debug("VALIDATION_RULE: JSON_STRUCTURE violation detected", category="combat_validation")
                elif "updatecharacterinfo" in negative_lower or "updateencounter" in negative_lower:
                    debug("VALIDATION_RULE: ACTION_USAGE violation detected", category="combat_validation")
                elif "ammunition" in negative_lower or "equipment" in negative_lower:
                    debug("VALIDATION_RULE: RESOURCE_USAGE violation detected", category="combat_validation")
                else:
                    debug("VALIDATION_RULE: UNKNOWN - could not categorize validation failure", category="combat_validation")
                full_feedback = (
                    f"Your previous response was invalid. Here is a breakdown:\n\n"
                    f"## What You Did Correctly (Keep This):\n- {positive}\n\n"
                    f"## What You Did Incorrectly (You Must Fix This):\n- {negative}\n\n"
                    f"## Corrective Action Required:\n- {recommendation}"
                )
                debug(f"VALIDATION: Full feedback for AI:\n{full_feedback}", category="combat_validation")
                return full_feedback
            except json_decode_error:
                debug(f"VALIDATION: Invalid JSON from validation model (Attempt {attempt + 1}/{max_validation_retries})", category="combat_validation")
                debug(f"VALIDATION: Problematic response: {validation_response}", category="combat_validation")
                continue
        except Exception as error:
            from utils.llm_router import GameLLMTerminalError
            if isinstance(error, GameLLMTerminalError):
                raise
            debug(f"VALIDATION: Validation error - {str(error)}", category="combat_validation")
            continue
    warning("VALIDATION: Validation failed after max retries, assuming response is valid", category="combat_validation")
    return True
