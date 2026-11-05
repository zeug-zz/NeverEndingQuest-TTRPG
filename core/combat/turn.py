# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Turn Pipeline - Explicit stage orchestration.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from core.combat.debug_dumps import combat_debug_dumps_enabled
import core.combat.validation as combat_validation
from utils.combat_latency_trace import (
    build_work_unit_trace_context,
    trace_combat_observation,
    trace_enabled,
)
from utils.pc_manager import (
    ActivePCWriteResult,
    commit_active_character,
    sync_active_pc_fields,
)
from core.combat.commands import FastCommandResult, is_usage_command_input
# TABLETOP MODE: Persist combat identity separately from model-visible content.
from core.combat.turn_commit import (
    build_accepted_input_record,
    conversation_history_for_prompt,
)
# TABLETOP MODE: Only authorized Capture_Arena copies may stop at commit boundaries.
from core.combat.turn_fault_injection import maybe_inject_combat_turn_fault


@dataclass
class InputPhaseGateResult:
    """Typed handoff from input normalization and phase gates."""

    control_action: str = "proceed"
    raw_input: str = ""
    clean_input: str = ""
    input_actor_name: Optional[str] = None
    pending_death_pc: Optional[str] = None
    pc_phase_started: bool = False


def should_consider_tactical_prefetch_replan(
    user_input_text: Any, multi_pc_manager: Any
) -> bool:
    """Allow state-edge checks during PC play, but never reinterpret DM /end."""
    if not isinstance(user_input_text, str) or is_usage_command_input(user_input_text):
        return False
    if getattr(multi_pc_manager, "combat_phase", None) != "PC_PHASE":
        return False
    clean_input = user_input_text.strip()
    if clean_input.startswith("[") and "]:" in clean_input:
        clean_input = clean_input.split("]:", 1)[1].strip()
    return clean_input.casefold() not in {"/end", "end", "enemies turn."}


def should_consider_ally_prefetch_replan(
    user_input_text: Any, multi_pc_manager: Any
) -> bool:
    """Check ally state edges on PC inputs, leaving /cmd to the accepted path."""
    if not should_consider_tactical_prefetch_replan(user_input_text, multi_pc_manager):
        return False
    clean_input = user_input_text.strip()
    if clean_input.startswith("[") and "]:" in clean_input:
        clean_input = clean_input.split("]:", 1)[1].strip()
    command = clean_input.split(None, 1)[0].casefold() if clean_input else ""
    return command != "/cmd"


def capture_pre_round_transition_combat_context(
    encounter_data: Dict[str, Any],
    multi_pc_manager: Any,
    parsed_response: Any,
    validation_accepted: bool,
    logical_turn: int,
) -> Optional[Dict[str, Any]]:
    """Capture only bounded read-only G3 phase/cohort context before round preparation."""
    if not trace_enabled():
        return None
    phase = getattr(multi_pc_manager, "combat_phase", None) if multi_pc_manager else None
    opening_pending = encounter_data.get("openingEnemyBatchPending") is True
    requested_round = parsed_response.get("combat_round") if isinstance(parsed_response, dict) else None
    prior_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    starts_dm_next = (validation_accepted and isinstance(requested_round, int) and
                      not isinstance(requested_round, bool) and requested_round > prior_round and
                      encounter_data.get("roundStartsWith") == "dmGroup")
    is_enemy_phase = bool(phase == "ENEMY_PHASE" or opening_pending or starts_dm_next)
    cohort = (multi_pc_manager.get_remaining_enemies_for_round()
              if validation_accepted and multi_pc_manager and is_enemy_phase else [])
    reason = ("opening_marker" if opening_pending else "current_enemy_phase" if phase == "ENEMY_PHASE"
              else "next_round_dm_starts" if starts_dm_next else "not_enemy_batch")
    return {
        "logical_turn": logical_turn,
        "validation_accepted": bool(validation_accepted),
        "phase": phase,
        "combat_round": encounter_data.get("combat_round"),
        "opening_batch_pending": opening_pending,
        "eligible_non_pc_cohort": list(cohort),
        "enemy_phase_expected": is_enemy_phase,
        "cohort_reason": reason,
        "round_transition_requested": requested_round,
    }


@dataclass(frozen=True)
class CombatActionTraceInputs:
    """Read-only metadata available immediately before legacy narration output."""

    actions: List[Dict[str, Any]]
    encounter_data: Dict[str, Any]
    encounter_id: str
    pre_action_context: Optional[Dict[str, Any]]
    validation_accepted: bool
    batch_id: Optional[str] = None


@dataclass(frozen=True)
class CombatActionTraceDependencies:
    trace_enabled: Callable[[], bool]
    trace_observation: Callable[..., Any]


def trace_combat_action_batch_metadata(
    inputs: CombatActionTraceInputs,
    dependencies: CombatActionTraceDependencies,
) -> None:
    """Emit the existing bounded, read-only action/actor/affected trace record."""
    if not dependencies.trace_enabled():
        return
    known_non_pc_names = [
        str(row.get("name")) for row in inputs.encounter_data.get("creatures", [])
        if isinstance(row, dict) and row.get("type") in ("enemy", "npc")
    ]
    observed_actions = []
    explicit_actor_records = []
    affected_entities = []
    for action in inputs.actions:
        parameters = action.get("parameters", {}) if isinstance(action, dict) else {}
        if not isinstance(parameters, dict):
            parameters = {}
        observed_ops = parameters.get("ops")
        if not isinstance(observed_ops, list):
            observed_ops = []
        action_index = len(observed_actions)
        action_type = str(action.get("action", ""))[:40] if isinstance(action, dict) else ""
        for field_name in ("actor", "actorName"):
            actor_value = parameters.get(field_name)
            if isinstance(actor_value, str) and actor_value:
                explicit_actor_records.append({"action_index": action_index, "name": actor_value[:80], "source": field_name})
        for field_name in ("characterName", "npcName", "creatureName", "target", "targetName"):
            affected_value = parameters.get(field_name)
            if isinstance(affected_value, str) and affected_value:
                affected_entities.append({"action_index": action_index, "name": affected_value[:80], "source": field_name})
        for operation in observed_ops:
            if isinstance(operation, dict):
                for field_name in ("creature", "target", "character"):
                    affected_value = operation.get(field_name)
                    if isinstance(affected_value, str) and affected_value:
                        affected_entities.append({
                            "action_index": action_index,
                            "name": affected_value[:80],
                            "source": "ops." + field_name,
                        })
        changes = str(parameters.get("changes", ""))
        for name in known_non_pc_names:
            if name.casefold() in changes.casefold():
                affected_entities.append({"action_index": action_index, "name": name[:80], "source": "changes_mention"})
        observed_actions.append(action_type)
    observed_actions = observed_actions[:16]
    explicit_actor_records = explicit_actor_records[:32]
    affected_entities = affected_entities[:32]
    pre_context = inputs.pre_action_context or {}
    enemy_phase_batch = bool(pre_context.get("validation_accepted") and pre_context.get("enemy_phase_expected"))
    event_fields = {
        "encounter_id": inputs.encounter_id,
        "logical_turn": pre_context.get("logical_turn"),
        "validation_accepted": bool(inputs.validation_accepted),
        "action_count": len(inputs.actions),
        "action_types": observed_actions,
        "phase_before_round_transition": pre_context.get("phase"),
        "combat_round_before_round_transition": pre_context.get("combat_round"),
        "opening_batch_pending_before_round_transition": pre_context.get("opening_batch_pending"),
        "cohort_reason": pre_context.get("cohort_reason"),
        "enemy_phase_batch": enemy_phase_batch,
        "eligible_non_pc_cohort": pre_context.get("eligible_non_pc_cohort", []),
        "explicit_actor_records": explicit_actor_records,
        "affected_entities": affected_entities,
        "round_transition_requested": pre_context.get("round_transition_requested"),
    }
    if inputs.batch_id:
        event_fields["batch_id"] = inputs.batch_id
    dependencies.trace_observation("combat_action_batch", **event_fields)


@dataclass
class PhaseGateIO:
    """Injected side effects used by the phase-gate stage."""

    emit: Callable[[str], None]
    flush: Callable[[], None]
    debug: Callable[..., None]
    save_json: Callable[[str, Any], Any]
    parse_death_save_roll: Callable[[str, bool], Any]
    commit_active_character: Optional[Callable[[str], ActivePCWriteResult]] = None


@dataclass(frozen=True)
class CombatTurnIterationInputs:
    """State at the top of one existing while-loop iteration."""

    session: Any
    encounter_id: str
    encounter_data: Dict[str, Any]
    multi_pc_manager: Any
    party_tracker_data: Dict[str, Any]
    path_manager: Any
    json_file_path: str
    conversation_history: List[Dict[str, Any]]
    conversation_history_file: str
    npc_templates: Dict[str, Any]
    player_info: Dict[str, Any]
    player_file: str
    fresh_player_data: Any
    current_hp: Any
    max_hp: Any


@dataclass(frozen=True)
class CombatTurnIterationDependencies:
    """Current owner callbacks for per-turn sync, status, history, and input."""

    safe_json_load: Callable[[str], Any]
    perf_counter: Callable[[], float]
    trace_file_operation: Callable[..., Any]
    trace_set_context: Callable[..., Any]
    trace_stage: Callable[..., Any]
    trace_enabled: Callable[[], bool]
    debug: Callable[..., Any]
    emit: Callable[[str], Any]
    error: Callable[..., Any]
    update_status: Callable[[str, bool], Any]
    sync_active_encounter: Callable[[Dict[str, Any], Any, int], Any]
    normalize_character_name: Callable[[str], str]
    format_character: Callable[..., str]
    load_npc_with_fuzzy_match: Callable[..., Any]
    filter_encounter: Callable[..., Any]
    filter_dynamic_fields: Callable[[Any], Any]
    save_json: Callable[[str, Any], Any]
    read_input: Callable[[str], str]
    flush: Callable[[], Any]


@dataclass(frozen=True)
class CombatTurnIterationResult:
    """Explicit mutable-state and control handoff from the loop's input prelude."""

    session: Any
    encounter_data: Any
    multi_pc_manager: Any
    party_tracker_data: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    npc_templates: Dict[str, Any]
    player_file: str
    fresh_player_data: Any
    current_hp: Any
    max_hp: Any
    player_name_display: Any
    current_round_trace_start: float
    user_input_text: Optional[str] = None
    continue_loop: bool = False
    return_early: bool = False
    return_value: Any = None
    path_manager: Any = None
    player_info: Any = None


@dataclass(frozen=True)
class CombatNormalTurnInputs:
    """State entering the current input/command/decision/context sequence."""

    iteration: CombatTurnIterationResult
    encounter_id: str
    json_file_path: str
    conversation_history_file: str
    location_info: Dict[str, Any]


@dataclass(frozen=True)
class CombatNormalTurnDependencies:
    """Injected current owner stage functions and I/O builders."""

    input_phase_gate: Callable[..., Any]
    phase_gate_io_factory: Callable[[Any], PhaseGateIO]
    initiative_gate: Callable[..., Any]
    fast_command_stage: Callable[..., Any]
    fast_command_io_factory: Callable[[], Any]
    deterministic_command_stage: Callable[..., Any]
    deterministic_command_io_factory: Callable[[Any, str, Any, Dict[str, Any]], Any]
    character_stat_command: Callable[..., bool]
    character_stat_io_factory: Callable[[Any], Any]
    normalize_character_name: Callable[[str], str]
    safe_json_load: Callable[[str], Any]
    pc_action_enabled: bool
    perf_counter: Callable[[], float]
    trace_decision: Callable[..., Any]
    enhance_inventory_context: Callable[..., Any]
    enhance_player_input_with_inventory: Callable[..., str]
    assemble_context: Callable[..., Any]
    clean_old_dm_notes: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
    clean_combat_state_blocks: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
    save_json: Callable[[str, Any], Any]
    debug: Callable[..., Any]
    emit: Callable[[str], Any]
    flush: Callable[[], Any]
    submit_standing_orders: Optional[Callable[..., Any]] = None
    submit_ally_prefetch: Optional[Callable[..., Any]] = None


@dataclass(frozen=True)
class CombatNormalTurnResult:
    """Explicit branch control and state required by the provider retry stage."""

    control_action: str
    session: Any
    encounter_data: Dict[str, Any]
    party_tracker_data: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    user_input_text: str = ""
    context_result: Any = None
    return_value: Any = None


def prepare_combat_normal_turn(
    inputs: CombatNormalTurnInputs,
    dependencies: CombatNormalTurnDependencies,
) -> CombatNormalTurnResult:
    """Orchestrate the existing gate/fast/deterministic/decision/context call graph."""
    from core.combat.prompts import CombatContextInputs, InventoryContextInputs

    state = inputs.iteration
    session = state.session
    encounter_data = state.encounter_data
    multi_pc_manager = state.multi_pc_manager
    party_tracker_data = state.party_tracker_data
    conversation_history = state.conversation_history
    user_input_text = state.user_input_text or ""

    raw_input = user_input_text.strip()
    clean_input = raw_input
    input_actor_name = None
    if raw_input.startswith("[") and "]:" in raw_input:
        parts = raw_input.split("]:", 1)
        if len(parts) == 2:
            input_actor_name = parts[0][1:].strip()
            clean_input = parts[1].strip()
    cmd = clean_input.lower()

    # TABLETOP MODE: A seeded PC_PHASE has no phase-start edge, so select its
    # initial ally prefetch before command handling (including an immediate /end).
    active_pc_phase = getattr(multi_pc_manager, "combat_phase", None) == "PC_PHASE"
    submit_ally_prefetch = getattr(dependencies, "submit_ally_prefetch", None)

    def submit_initial_ally_prefetch() -> None:
        if not callable(submit_ally_prefetch):
            return
        try:
            submit_ally_prefetch(
                encounter_data=encounter_data,
                encounter_id=inputs.encounter_id,
                multi_pc_manager=multi_pc_manager,
                path_manager=state.path_manager,
                party_tracker_data=party_tracker_data,
                location_info=inputs.location_info,
                npc_profiles=state.npc_templates,
                conversation_history=conversation_history,
                trigger="initial",
            )
        except Exception:
            # Ally prefetch is optional and cannot delay initiative control.
            pass

    if active_pc_phase:
        submit_initial_ally_prefetch()

    phase_gate = dependencies.input_phase_gate(
        user_input_text,
        encounter_data=encounter_data,
        multi_pc_manager=multi_pc_manager,
        party_tracker_data=party_tracker_data,
        json_file_path=inputs.json_file_path,
        conversation_history=conversation_history,
        conversation_history_file=inputs.conversation_history_file,
        io=dependencies.phase_gate_io_factory(multi_pc_manager),
        initiative_gate=dependencies.initiative_gate,
    )
    if getattr(phase_gate, "pc_phase_started", False) and callable(
        dependencies.submit_standing_orders
    ):
        try:
            dependencies.submit_standing_orders(
                encounter_data=encounter_data,
                encounter_id=inputs.encounter_id,
                multi_pc_manager=multi_pc_manager,
                path_manager=state.path_manager,
                party_tracker_data=party_tracker_data,
                location_info=inputs.location_info,
                replan=False,
            )
        except Exception:
                # Prefetch setup is fail-open and must not delay initiative control.
                pass
    if getattr(phase_gate, "pc_phase_started", False) and not active_pc_phase:
        submit_initial_ally_prefetch()
    clean_input = phase_gate.clean_input
    input_actor_name = phase_gate.input_actor_name
    if multi_pc_manager:
        session.active_pc = multi_pc_manager.current_pc_name or party_tracker_data.get("active_character")
        session.set_phase(multi_pc_manager.combat_phase)
    cmd = clean_input.lower()
    if phase_gate.control_action == "continue":
        return CombatNormalTurnResult("continue", session, encounter_data, party_tracker_data, conversation_history)
    if phase_gate.raw_input == "Enemies turn.":
        user_input_text = "Enemies turn."

    fast_command = dependencies.fast_command_stage(
        cmd=cmd,
        clean_input=clean_input,
        user_input_text=user_input_text,
        input_actor_name=input_actor_name,
        multi_pc_manager=multi_pc_manager,
        encounter_data=encounter_data,
        encounter_id=inputs.encounter_id,
        party_tracker_data=party_tracker_data,
        active_encounter_id=(
            party_tracker_data.get("worldConditions", {}).get("activeCombatEncounter")
            if isinstance(party_tracker_data.get("worldConditions", {}), dict)
            else None
        ),
        tactical_features=(
            inputs.location_info.get("tacticalFeatures")
            if isinstance(inputs.location_info, dict) else None
        ),
        conversation_history=conversation_history,
        conversation_history_file=inputs.conversation_history_file,
        io=dependencies.fast_command_io_factory(),
    )
    # TABLETOP MODE: Older injected fast-command handoffs may omit status/reason.
    if (
        getattr(fast_command, "status", None) == "accepted"
        and getattr(fast_command, "reason", None) == "accepted"
    ):
        submit_ally_prefetch = getattr(dependencies, "submit_ally_prefetch", None)
        if callable(submit_ally_prefetch):
            try:
                submit_ally_prefetch(
                    encounter_data=encounter_data,
                    encounter_id=inputs.encounter_id,
                    multi_pc_manager=multi_pc_manager,
                    path_manager=state.path_manager,
                    party_tracker_data=party_tracker_data,
                    location_info=inputs.location_info,
                    npc_profiles=state.npc_templates,
                    conversation_history=conversation_history,
                    trigger="directive",
                )
            except Exception:
                # A directive is already durable; re-planning is best-effort.
                pass
    user_input_text = fast_command.user_input_text
    if fast_command.control_action == "continue":
        return CombatNormalTurnResult("continue", session, encounter_data, party_tracker_data, conversation_history)

    current_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    deterministic_command = dependencies.deterministic_command_stage(
        cmd=cmd,
        current_round=current_round,
        encounter_id=inputs.encounter_id,
        encounter_data=encounter_data,
        party_tracker_data=party_tracker_data,
        conversation_history=conversation_history,
        location_info=inputs.location_info,
        player_file=state.player_file,
        io=dependencies.deterministic_command_io_factory(
            state.path_manager, state.player_file, session, party_tracker_data
        ),
    )
    if deterministic_command.control_action == "return":
        return CombatNormalTurnResult(
            "return", session, encounter_data, party_tracker_data, conversation_history,
            return_value=deterministic_command.return_value,
        )
    if deterministic_command.status == "exit_requested":
        return CombatNormalTurnResult(
            "exit_requested", session, encounter_data, party_tracker_data, conversation_history,
            return_value=deterministic_command,
        )
    if deterministic_command.control_action == "continue":
        return CombatNormalTurnResult("continue", session, encounter_data, party_tracker_data, conversation_history)

    if cmd.startswith("/xp") or cmd.startswith("/level"):
        if dependencies.character_stat_command(cmd, dependencies.character_stat_io_factory(state.path_manager)):
            return CombatNormalTurnResult("continue", session, encounter_data, party_tracker_data, conversation_history)

    from core.combat.decisions import (
        PCActionDecisionStatus,
        pc_action_decision_eligible,
        resolve_pc_action_actor,
        run_pc_action_decision,
    )

    parser_eligible = pc_action_decision_eligible(
        enabled=dependencies.pc_action_enabled,
        multi_pc_manager=multi_pc_manager,
        clean_input=clean_input,
        cmd=cmd,
    )
    decision_started_at = dependencies.perf_counter() if parser_eligible else 0.0
    parser_actor = resolve_pc_action_actor(
        input_actor_name,
        multi_pc_manager if parser_eligible else None,
        party_tracker_data,
    )
    pc_action_decision = run_pc_action_decision(
        eligible=parser_eligible,
        clean_input=clean_input,
        encounter_data=encounter_data,
        party_tracker_data=party_tracker_data,
        actor_name=parser_actor,
        multi_pc_manager=multi_pc_manager,
        encounter_id=inputs.encounter_id,
        decision_started_at=decision_started_at,
        trace_decision=dependencies.trace_decision,
    )
    if pc_action_decision.import_error is not None:
        dependencies.debug("Combat PC phase parser import failed; continuing to LLM path", category="combat_events")
    if pc_action_decision.status is PCActionDecisionStatus.HANDLED:
        parse_result = pc_action_decision.parse_result or {}
        mechanical_feedback = parse_result.get("mechanical_feedback")
        spoken_narration = parse_result.get("spoken_narration")
        log_message = parse_result.get("log_msg")
        if mechanical_feedback:
            dependencies.emit(mechanical_feedback)
            dependencies.flush()
        if spoken_narration:
            dependencies.emit(spoken_narration)
            dependencies.flush()
        if log_message:
            conversation_history.append({"role": "user", "content": log_message})
            dependencies.save_json(inputs.conversation_history_file, conversation_history)
        return CombatNormalTurnResult("continue", session, encounter_data, party_tracker_data, conversation_history)

    inventory_context = dependencies.enhance_inventory_context(
        InventoryContextInputs(
            user_input_text=user_input_text,
            player_name_display=state.player_name_display,
            path_manager=state.path_manager,
            normalize_character_name=dependencies.normalize_character_name,
            safe_json_load=dependencies.safe_json_load,
            enhance_player_input_with_inventory=dependencies.enhance_player_input_with_inventory,
            party_tracker_data=party_tracker_data,
            debug=dependencies.debug,
            preexisting_player_data=state.fresh_player_data,
        )
    )
    user_input_text = inventory_context.user_input_text
    context_result = dependencies.assemble_context(
        CombatContextInputs(
            encounter_data=encounter_data,
            multi_pc_manager=multi_pc_manager,
            party_tracker_data=party_tracker_data,
            player_info=state.player_info,
            player_name_display=state.player_name_display,
            current_hp=state.current_hp,
            max_hp=state.max_hp,
            pre_context_player_data=inventory_context.fresh_player_data,
            path_manager=state.path_manager,
            json_file_path=f"modules/encounters/encounter_{inputs.encounter_id}.json",
            conversation_history=conversation_history,
            user_input_text=user_input_text,
            location_info=inputs.location_info,
        )
    )
    if context_result.return_early:
        return CombatNormalTurnResult(
            "return", session, encounter_data, party_tracker_data, conversation_history,
            return_value=context_result.return_value,
        )
    conversation_history = dependencies.clean_old_dm_notes(conversation_history)
    conversation_history = dependencies.clean_combat_state_blocks(conversation_history)
    session.bind_history(conversation_history)
    # TABLETOP MODE: Keep the accepted input's durable identity outside prompt bytes.
    conversation_history.append(build_accepted_input_record(context_result.user_prompt))
    dependencies.save_json(inputs.conversation_history_file, conversation_history)
    return CombatNormalTurnResult(
        "proceed", session, context_result.encounter_data, party_tracker_data,
        conversation_history, context_result.user_input_text, context_result,
    )


def begin_combat_turn_iteration(
    inputs: CombatTurnIterationInputs,
    dependencies: CombatTurnIterationDependencies,
) -> CombatTurnIterationResult:
    """Refresh authoritative turn state and read the next line at legacy order."""
    session = inputs.session
    turn_identity = session.begin_turn_iteration()
    encounter_data = inputs.encounter_data
    multi_pc_manager = inputs.multi_pc_manager
    party_tracker_data = inputs.party_tracker_data
    conversation_history = inputs.conversation_history
    npc_templates = inputs.npc_templates
    player_file = inputs.player_file
    fresh_player_data = inputs.fresh_player_data
    current_hp = inputs.current_hp
    max_hp = inputs.max_hp

    turn_trace_start = dependencies.perf_counter()
    if dependencies.trace_enabled():
        try:
            trace_context = {"mode": "mp" if multi_pc_manager else "one_pc"}
            if isinstance(encounter_data, dict):
                combat_round = encounter_data.get("combat_round")
            else:
                combat_round = None
            if combat_round is None and multi_pc_manager:
                combat_round = getattr(multi_pc_manager, "current_round", None)
            if combat_round is not None:
                trace_context["combat_round"] = combat_round
            phase = "PC_PHASE"
            if multi_pc_manager:
                phase = getattr(multi_pc_manager, "combat_phase", None)
                if phase is not None:
                    trace_context["phase"] = phase
            if not multi_pc_manager:
                active_pc = (party_tracker_data.get("active_character") or
                             getattr(session, "active_pc", None))
                trace_context.update(build_work_unit_trace_context(
                    combat_round if combat_round is not None else 1, phase, active_pc
                ))
            dependencies.trace_set_context(**trace_context)
        except Exception:
            pass
    dependencies.trace_stage("turn_start", turn_trace_start)
    dependencies.debug("[COMBAT_MANAGER] Syncing character data to encounter", category="combat_events")
    dependencies.emit("DEBUG: [COMBAT_LOOP] Top of while loop - syncing character data")

    party_tracker_data = dependencies.safe_json_load("party_tracker.json") or party_tracker_data
    dependencies.trace_file_operation("read", "party_tracker_turn_start")

    if multi_pc_manager:
        active_pc = party_tracker_data.get("active_character")
        if active_pc:
            multi_pc_manager.set_current_pc(active_pc)
            session.active_pc = active_pc
            dependencies.debug(f"[COMBAT_MANAGER] Multi-PC Active Character: {active_pc}", category="combat_events")
        session.set_phase(multi_pc_manager.combat_phase)
        if dependencies.trace_enabled():
            try:
                trace_context.update(build_work_unit_trace_context(
                    combat_round if combat_round is not None else 1,
                    multi_pc_manager.combat_phase,
                    active_pc or getattr(multi_pc_manager, "current_pc_name", None),
                ))
                dependencies.trace_set_context(**trace_context)
            except Exception:
                pass
    try:
        dependencies.update_status("", False)
    except Exception as exc:
        dependencies.debug(f"Could not clear status: {exc}", category="status")
    dependencies.sync_active_encounter(party_tracker_data, session, turn_identity)

    if multi_pc_manager:
        temp_encounter_data = dependencies.safe_json_load(inputs.json_file_path)
        if temp_encounter_data:
            for creature in temp_encounter_data.get("creatures", []):
                if creature.get("type") == "player":
                    multi_pc_manager.update_pc_hp(creature.get("name"), creature.get("currentHitPoints", 0))
            dependencies.debug("[COMBAT_MANAGER] Multi-PC Manager HP synced from encounter", category="combat_events")

    dependencies.debug("STATE_CHANGE: Refreshing conversation history with latest character data...", category="combat_events")
    if multi_pc_manager:
        if not session.replace_system_payload(
            "=== AUTHORITATIVE MULTI-PC STATE (JSON) ===",
            multi_pc_manager.format_multi_pc_head_context(),
        ):
            session.replace_system_payload(
                "Here's the player character data:",
                multi_pc_manager.format_multi_pc_head_context(),
            )
        dependencies.debug("[COMBAT_MANAGER] Refreshed Multi-PC Head Context", category="combat_events")
    else:
        player_name = dependencies.normalize_character_name(inputs.player_info["name"])
        player_file = inputs.path_manager.get_character_path(player_name)
        try:
            fresh_player_data = dependencies.safe_json_load(player_file)
            if not fresh_player_data:
                dependencies.error(f"FAILURE: Failed to load player file: {player_file}", category="file_operations")
            else:
                formatted_player = dependencies.format_character(fresh_player_data, char_type="player")
                session.replace_system_payload(
                    "Here's the player character data:",
                    f"Here's the player character data:\n\n{formatted_player}\n",
                )
        except Exception as exc:
            dependencies.error(f"FAILURE: Failed to reload player file {player_file}", exception=exc, category="file_operations")

    json_file_path = f"modules/encounters/encounter_{inputs.encounter_id}.json"
    try:
        encounter_data = dependencies.safe_json_load(json_file_path)
        dependencies.trace_file_operation("read", "encounter_turn_start")
        if encounter_data:
            session.bind_encounter(encounter_data)
            for message in conversation_history:
                if message["role"] == "system" and "Encounter Details:" in message["content"]:
                    message["content"] = f"Encounter Details:\n{json.dumps(dependencies.filter_encounter(encounter_data), indent=2)}"
                    break
    except Exception as exc:
        dependencies.error(f"FAILURE: Failed to reload encounter file {json_file_path}", exception=exc, category="file_operations")

    for creature in encounter_data["creatures"]:
        if creature["type"] == "npc":
            npc_data, matched_filename = dependencies.load_npc_with_fuzzy_match(creature["name"], inputs.path_manager)
            if npc_data and matched_filename:
                npc_templates[matched_filename] = npc_data
            else:
                dependencies.error(f"FAILURE: Failed to reload NPC file for: {creature['name']}", category="file_operations")

    for message in conversation_history:
        if message["role"] == "system" and "NPC Templates:" in message["content"]:
            message["content"] = f"NPC Templates:\n{json.dumps({key: dependencies.filter_dynamic_fields(value) for key, value in npc_templates.items()}, indent=2)}"
            break
    dependencies.save_json(inputs.conversation_history_file, conversation_history)

    if multi_pc_manager and multi_pc_manager.combat_phase == "PC_PHASE":
        pending_death_pc = multi_pc_manager.get_next_pending_death_save_pc()
        if pending_death_pc and multi_pc_manager.should_emit_death_save_prompt(pending_death_pc):
            dependencies.emit(
                f"Dungeon Master: {pending_death_pc} falls still, breath shallow. "
                f"{pending_death_pc} needs to roll a death saving throw."
            )
            dependencies.flush()

    player_name_display = inputs.player_info["name"]
    current_hp = inputs.player_info.get("hitPoints", 0)
    max_hp = inputs.player_info.get("maxHitPoints", 0)
    current_xp = inputs.player_info.get("experience_points", 0)
    next_level_xp = inputs.player_info.get("exp_required_for_next_level", 0)
    current_time_str = party_tracker_data["worldConditions"].get("time", "Unknown")
    stats_display = f"[{current_time_str}][HP:{current_hp}/{max_hp}][XP:{current_xp}/{next_level_xp}]"
    dependencies.emit("DEBUG: [COMBAT_LOOP] About to request player input")
    dependencies.debug("COMBAT_LOOP: Requesting player input", category="combat_events")
    try:
        user_input_text = dependencies.read_input(f"{stats_display} {player_name_display}: ")
        dependencies.emit(
            f"DEBUG: [COMBAT_LOOP] Got player input: {user_input_text[:50]}..."
            if len(user_input_text) > 50 else f"DEBUG: [COMBAT_LOOP] Got player input: {user_input_text}"
        )
        dependencies.debug(f"COMBAT_LOOP: Received player input of length {len(user_input_text)}", category="combat_events")
    except EOFError:
        dependencies.error("FAILURE: EOF when reading a line in run_combat_simulation", category="combat_events")
        dependencies.emit("DEBUG: [COMBAT_LOOP] EOF encountered, breaking loop")
        return CombatTurnIterationResult(
            session, encounter_data, multi_pc_manager, party_tracker_data, conversation_history,
            npc_templates, player_file, fresh_player_data, current_hp, max_hp, player_name_display,
            turn_trace_start, return_early=True,
            return_value=FastCommandResult(
                control_action="quit", status="exit_requested", reason="input_eof", exit_code=0,
            ),
            path_manager=inputs.path_manager,
            player_info=inputs.player_info,
        )
    if not user_input_text or not user_input_text.strip():
        return CombatTurnIterationResult(
            session, encounter_data, multi_pc_manager, party_tracker_data, conversation_history,
            npc_templates, player_file, fresh_player_data, current_hp, max_hp, player_name_display,
            turn_trace_start, continue_loop=True,
            path_manager=inputs.path_manager,
            player_info=inputs.player_info,
        )
    return CombatTurnIterationResult(
        session, encounter_data, multi_pc_manager, party_tracker_data, conversation_history,
        npc_templates, player_file, fresh_player_data, current_hp, max_hp, player_name_display,
        turn_trace_start, user_input_text=user_input_text,
        path_manager=inputs.path_manager,
        player_info=inputs.player_info,
    )


@dataclass(frozen=True)
class CombatRetryInputs:
    """State entering the normal-turn provider/retry/validation boundary."""

    conversation_history: List[Dict[str, Any]]
    initial_conversation_length: int
    encounter_data: Dict[str, Any]
    party_tracker_data: Dict[str, Any]
    multi_pc_manager: Any
    user_input_text: str
    # Diagnostic handoff only; GPT-family requests do not use it for sampling.
    diagnostic_temperature: Optional[float] = None
    retry_feedback_note: Optional[str] = None
    max_retries: int = 5


@dataclass(frozen=True)
class CombatRetryDependencies:
    """Injected current owner bindings and side effects for a normal turn."""

    client: Any
    use_gpt5_models: bool
    gpt5_mini_model: str
    gpt5_high_reasoning_on_retry: bool
    combat_main_model: str
    get_completion_params: Callable[..., Dict[str, Any]]
    get_temperature: Callable[..., Any]
    perf_counter: Callable[[], float]
    trace_stage: Callable[..., Any]
    trace_provider_call: Callable[..., Any]
    export_open: Callable[..., Any]
    makedirs: Callable[..., Any]
    emit: Callable[[str], Any]
    debug: Callable[..., Any]
    warning: Callable[..., Any]
    error: Callable[..., Any]
    usage_tracking_available: bool
    track_usage: Callable[[Any], Any]
    is_valid_json: Callable[[str], bool]
    check_multiple_update_encounter: Callable[[Any], bool]
    make_multiple_update_feedback: Callable[[Any], str]
    validate_combatant_integrity: Callable[..., Any]
    validate_combat_response: Callable[..., Any]
    update_status: Callable[[str, bool], Any]
    debug_dumps_enabled: Callable[[], bool] = combat_debug_dumps_enabled
    # Private routed transport seams. Legacy fields above remain constructor-compatible.
    llm_call: Optional[Callable[..., str]] = None
    receipt_observer_factory: Optional[Callable[..., Any]] = None


@dataclass
class CombatRetryResult:
    """Complete handoff needed by the later apply/commit owner stages."""

    valid_response: bool = False
    ai_response: Optional[str] = None
    parsed_response: Optional[Dict[str, Any]] = None
    narration: Any = None
    actions: Any = None
    validation_attempts: List[Dict[str, Any]] = field(default_factory=list)
    initial_conversation_length: int = 0
    retry_feedback_note: Optional[str] = None
    retry_request_history: Optional[List[Dict[str, Any]]] = None
    retry_validation_history: Optional[List[Dict[str, Any]]] = None
    # Preserved for owner-side retry logs; never forwarded as GPT sampling config.
    temperature_used: Any = None


def run_combat_provider_retry_stage(
    inputs: CombatRetryInputs,
    dependencies: CombatRetryDependencies,
) -> CombatRetryResult:
    """Run normal-turn provider generation, JSON checks, and validation in order.

    Initial scene setup deliberately remains in the legacy owner. This stage is
    solely the current player/enemy normal-turn retry loop.
    """
    result = CombatRetryResult(
        initial_conversation_length=inputs.initial_conversation_length,
        retry_feedback_note=inputs.retry_feedback_note,
        temperature_used=inputs.diagnostic_temperature,
    )
    conversation_history = inputs.conversation_history
    encounter_data = inputs.encounter_data
    max_retries = inputs.max_retries
    deterministic_failure_attempts = 0
    deterministic_failure_this_attempt = False
    validator_rejected_previous = False
    deterministic_retry_limit = (
        combat_validation.DETERMINISTIC_VALIDATION_RETRY_CAP
        if combat_validation.VALIDATION_ROUTING_ENABLED else max_retries
    )

    def record_deterministic_failure() -> bool:
        """Count at most one deterministic rejection for each generated response."""
        nonlocal deterministic_failure_attempts, deterministic_failure_this_attempt
        if not deterministic_failure_this_attempt:
            deterministic_failure_attempts += 1
            deterministic_failure_this_attempt = True
        return deterministic_failure_attempts >= deterministic_retry_limit

    if dependencies.llm_call is None or dependencies.receipt_observer_factory is None:
        raise RuntimeError("Combat retry stage requires routed call and receipt observer bindings")

    for attempt in range(max_retries):
        deterministic_failure_this_attempt = False
        retry_cause = "validator_rejection" if validator_rejected_previous else None
        validator_rejected_previous = False

        def receipt_legacy_context(model: str, **extra: Any) -> Dict[str, Any]:
            context = {
                "purpose": "combat_provider_retry",
                "legacy_context_model": model,
            }
            context.update(extra)
            if retry_cause is not None:
                context["retry_cause"] = retry_cause
            return context

        try:
            dependencies.emit(
                f"[COMBAT_MANAGER] Making AI call for player action (attempt {attempt + 1}/{max_retries})"
            )
            if len(inputs.user_input_text) > 50:
                dependencies.emit(f"[COMBAT_MANAGER] Processing player input: {inputs.user_input_text[:50]}...")
            else:
                dependencies.emit(f"[COMBAT_MANAGER] Processing player input: {inputs.user_input_text}")

            # TABLETOP MODE: Turn identity is durable history metadata, never prompt data.
            retry_request_history = conversation_history_for_prompt(conversation_history)
            if result.retry_feedback_note:
                retry_request_history.append({"role": "user", "content": result.retry_feedback_note})
            result.retry_request_history = retry_request_history

            try:
                dependencies.update_status("Combat AI processing your action...", True)
            except Exception as exc:
                dependencies.debug(f"Could not update status: {exc}", category="status")

            combat_model = dependencies.gpt5_mini_model if dependencies.use_gpt5_models else dependencies.combat_main_model
            if dependencies.use_gpt5_models:
                if attempt >= 1 and dependencies.gpt5_high_reasoning_on_retry:
                    dependencies.emit(f"DEBUG: [COMBAT] GPT-5 - Using HIGH reasoning effort after {attempt} attempts")
                    prompt_prep_start = dependencies.perf_counter()
                    messages_to_send = list(retry_request_history)
                    dependencies.trace_stage("prompt_prep", prompt_prep_start)
                    observer = dependencies.receipt_observer_factory(
                        trace_site="combat_main",
                        track_usage=dependencies.usage_tracking_available,
                        legacy_context=receipt_legacy_context(combat_model),
                    )
                    # TABLETOP MODE: Combat-turn validation parses a JSON object response.
                    response_text = dependencies.llm_call(
                        "combat_main", messages_to_send, json_output=False,
                        observer=observer, retry_tier="high", json_contract=True,
                    )
                else:
                    dependencies.emit(f"DEBUG: [COMBAT] Using GPT-5 model: {combat_model} (default medium reasoning)")
                    prompt_prep_start = dependencies.perf_counter()
                    messages_to_send = list(retry_request_history)
                    dependencies.trace_stage("prompt_prep", prompt_prep_start)
                    observer = dependencies.receipt_observer_factory(
                        trace_site="combat_main",
                        track_usage=dependencies.usage_tracking_available,
                        legacy_context=receipt_legacy_context(combat_model),
                    )
                    # TABLETOP MODE: Combat-turn validation parses a JSON object response.
                    response_text = dependencies.llm_call(
                        "combat_main", messages_to_send, json_output=False, observer=observer,
                        json_contract=True,
                    )
            else:
                result.temperature_used = dependencies.get_temperature(encounter_data, validation_attempt=attempt)
                dependencies.emit(
                    f"DEBUG: [COMBAT] Using GPT-4.1 model: {dependencies.combat_main_model} "
                    f"(temp: {result.temperature_used})"
                )
                prompt_prep_start = dependencies.perf_counter()
                messages_to_send = list(retry_request_history)
                dependencies.trace_stage("prompt_prep", prompt_prep_start)
                observer = dependencies.receipt_observer_factory(
                    trace_site="combat_main",
                    track_usage=dependencies.usage_tracking_available,
                    legacy_context=receipt_legacy_context(
                        dependencies.combat_main_model,
                        temperature=result.temperature_used,
                    ),
                )
                # TABLETOP MODE: Combat-turn validation parses a JSON object response.
                response_text = dependencies.llm_call(
                    "combat_main", messages_to_send, json_output=False,
                    observer=observer, temperature=result.temperature_used,
                    json_contract=True,
                )

            result.ai_response = response_text.strip()
            dependencies.emit(f"[COMBAT_MANAGER] AI response received ({len(result.ai_response)} chars)")
            if dependencies.debug_dumps_enabled():
                dependencies.makedirs("debug", exist_ok=True)
                with dependencies.export_open("debug/debug_ai_response.json", "w") as debug_file:
                    json.dump({"raw_ai_response": result.ai_response}, debug_file, indent=2)

            retry_validation_history = list(retry_request_history)
            retry_validation_history.append({"role": "assistant", "content": result.ai_response})
            result.retry_validation_history = retry_validation_history

            if not dependencies.is_valid_json(result.ai_response):
                dependencies.debug(
                    f"VALIDATION: Invalid JSON response from AI (Attempt {attempt + 1}/{max_retries})",
                    category="combat_validation",
                )
                if attempt < max_retries - 1:
                    result.retry_feedback_note = (
                        "Your previous response was not a valid JSON object with 'narration' and 'actions' fields. "
                        "Please provide a valid JSON response."
                    )
                    result.validation_attempts.append({
                        "attempt": attempt + 1, "assistant_response": result.ai_response,
                        "validation_error": result.retry_feedback_note, "error_type": "json_format",
                        "temperature_used": result.temperature_used,
                    })
                    continue
                dependencies.warning(
                    "VALIDATION: Max retries exceeded for JSON validation. Skipping this response.",
                    category="combat_validation",
                )
                break

            result.parsed_response = json.loads(result.ai_response)
            result.narration = result.parsed_response["narration"]
            result.actions = result.parsed_response["actions"]
            if dependencies.check_multiple_update_encounter(result.actions):
                cap_reached = record_deterministic_failure()
                dependencies.debug(
                    f"VALIDATION: Multiple updateEncounter actions detected (Attempt {attempt + 1}/{max_retries})",
                    category="combat_validation",
                )
                if cap_reached:
                    dependencies.warning(
                        "VALIDATION: Max retries exceeded for combat validation. Using last response.",
                        category="combat_validation",
                    )
                    break
                if attempt < max_retries - 1:
                    result.retry_feedback_note = dependencies.make_multiple_update_feedback(result.parsed_response)
                    result.validation_attempts.append({
                        "attempt": attempt + 1, "assistant_response": result.ai_response,
                        "validation_error": result.retry_feedback_note,
                        "error_type": "multiple_update_encounter", "temperature_used": result.temperature_used,
                    })
                    continue
                dependencies.warning(
                    "VALIDATION: Max retries exceeded for multiple updateEncounter correction. Using last response.",
                    category="combat_validation",
                )

            dependencies.emit(f"[COMBAT_MANAGER] Validating combat response (Attempt {attempt + 1}/{max_retries})")
            try:
                dependencies.update_status("Validating combat actions...", True)
            except Exception as exc:
                dependencies.debug(f"Could not update status: {exc}", category="status")

            integrity_check = dependencies.validate_combatant_integrity(
                result.ai_response,
                encounter_data,
                multi_pc_manager=inputs.multi_pc_manager,
                party_tracker_data=inputs.party_tracker_data,
            )
            if integrity_check is not True:
                cap_reached = record_deterministic_failure()
                dependencies.debug(
                    f"VALIDATION: Combatant Integrity Failed (Attempt {attempt + 1}/{max_retries})",
                    category="combat_validation",
                )
                dependencies.debug(f"INTEGRITY_FAIL: {integrity_check}", category="combat_validation")
                if attempt < max_retries - 1 and not cap_reached:
                    result.retry_feedback_note = integrity_check
                    result.validation_attempts.append({
                        "attempt": attempt + 1, "assistant_response": result.ai_response,
                        "validation_error": integrity_check, "error_type": "integrity_check",
                        "temperature_used": result.temperature_used,
                    })
                    continue
                dependencies.warning(
                    "VALIDATION: Max retries exceeded for Integrity Check. Skipping.",
                    category="combat_validation",
                )
                break

            validation_start = dependencies.perf_counter()
            validation_result = dependencies.validate_combat_response(
                result.ai_response,
                encounter_data,
                inputs.user_input_text,
                retry_validation_history,
                multi_pc_manager=inputs.multi_pc_manager,
            )
            dependencies.trace_stage("validation", validation_start)
            if validation_result is True:
                result.valid_response = True
                result.retry_feedback_note = None
                dependencies.emit(f"[COMBAT_MANAGER] Combat response validation PASSED on attempt {attempt + 1}")
                dependencies.debug(
                    f"SUCCESS: Response validated successfully on attempt {attempt + 1}",
                    category="combat_validation",
                )
                break

            dependencies.debug(
                f"VALIDATION: Response validation failed (Attempt {attempt + 1}/{max_retries})",
                category="combat_validation",
            )
            feedback = validation_result
            validator_rejected_previous = True
            deterministic_rejection = (
                isinstance(validation_result, str)
                and validation_result.startswith("VALIDATION FAILURE:")
            )
            cap_reached = record_deterministic_failure() if deterministic_rejection else False
            dependencies.debug(f"VALIDATION_ATTEMPT: {attempt + 1} failed", category="combat_validation")
            if attempt < max_retries - 1 and not cap_reached:
                result.retry_feedback_note = feedback
                result.validation_attempts.append({
                    "attempt": attempt + 1, "assistant_response": result.ai_response,
                    "validation_error": feedback,
                    "error_type": "deterministic_precheck" if deterministic_rejection else "combat_logic",
                    "temperature_used": result.temperature_used,
                })
                continue
            if deterministic_rejection and cap_reached:
                dependencies.warning(
                    "VALIDATION: Max retries exceeded for combat validation. Using last response.",
                    category="combat_validation",
                )
                break
            dependencies.warning(
                "VALIDATION: Max retries exceeded for combat validation. Using last response.",
                category="combat_validation",
            )
            break
        except Exception as exc:
            from utils.llm_router import GameLLMTerminalError
            if isinstance(exc, GameLLMTerminalError):
                raise
            dependencies.error(
                f"FAILURE: Failed to get or validate AI response (Attempt {attempt + 1}/{max_retries})",
                exception=exc,
                category="combat_events",
            )
            if attempt < max_retries - 1:
                continue
            dependencies.warning("VALIDATION: Max retries exceeded. Skipping this response.", category="combat_validation")
            break
    return result


def handle_group_initiative_gate(
    cmd: str,
    encounter_data: Dict[str, Any],
    multi_pc_manager: Any,
    party_tracker_data: Dict[str, Any],
    *,
    apply_opening_batch_marker: Callable[[Dict[str, Any], str], bool],
    sync_available: bool,
) -> Dict[str, Any]:
    """Handle the unchanged Phase 1 ``/init <1-20>`` contract."""
    result = {
        "handled": False,
        "valid_init": False,
        "error_message": "",
        "winner": None,
        "pc_group_roll": 0,
        "dm_group_roll": 0,
        "phase_label": "",
        "encounter_updates": {},
        "marker_enabled": False,
        "mirror_payload": {},
        "needs_enemy_injection": False,
    }
    if not cmd.startswith("/init"):
        result["error_message"] = "[skipTTS][prefill:/init ] Dungeon Master: [SYSTEM] Initiative pending. Enter /init <1-20> to begin combat."
        return result
    parts = cmd.split()
    if len(parts) != 2:
        result["error_message"] = "[skipTTS][prefill:/init ] Dungeon Master: [SYSTEM] Initiative pending. Usage: /init <1-20>"
        return result
    try:
        pc_group_roll = int(parts[1])
    except ValueError:
        result["error_message"] = "[skipTTS][prefill:/init ] Dungeon Master: [SYSTEM] Initiative pending. Usage: /init <1-20>"
        return result
    if pc_group_roll < 1 or pc_group_roll > 20:
        result["error_message"] = "[skipTTS][prefill:/init ] Dungeon Master: [SYSTEM] Initiative pending. Roll must be between 1 and 20."
        return result

    result["handled"] = True
    result["valid_init"] = True
    result["pc_group_roll"] = pc_group_roll
    dm_group_roll = encounter_data.get("initiativeRolls", {}).get("dmGroup", 1)
    result["dm_group_roll"] = dm_group_roll
    winner = "pcGroup" if pc_group_roll > dm_group_roll else "dmGroup"
    result["winner"] = winner
    result["phase_label"] = "PC_PHASE" if winner == "pcGroup" else "ENEMY_PHASE"
    result["encounter_updates"] = {
        "initiativeMode": "two_group_phase1",
        "initiativeRolls": {"dmGroup": dm_group_roll, "pcGroup": pc_group_roll},
        "initiativeWinner": winner,
        "roundStartsWith": winner,
        "awaitingPcGroupRoll": False,
    }
    if sync_available:
        result["marker_enabled"] = apply_opening_batch_marker(encounter_data, winner)
    result["mirror_payload"] = {
        "partyRoll": pc_group_roll,
        "enemyRoll": dm_group_roll,
        "partyGoesFirst": winner == "pcGroup",
    }
    result["needs_enemy_injection"] = winner == "dmGroup"
    return result


def run_input_phase_gate(
    user_input_text: str,
    *,
    encounter_data: Dict[str, Any],
    multi_pc_manager: Any,
    party_tracker_data: Dict[str, Any],
    json_file_path: str,
    conversation_history: list,
    conversation_history_file: str,
    io: PhaseGateIO,
    initiative_gate: Callable[..., Dict[str, Any]],
    parse_death_save_roll: Optional[Callable[[str, bool], Any]] = None,
) -> InputPhaseGateResult:
    """Normalize input and execute initiative/death-save gates in old order."""
    raw_input = (user_input_text or "").strip()
    clean_input = raw_input
    input_actor_name = None
    if raw_input.startswith("[") and "]:" in raw_input:
        parts = raw_input.split("]:", 1)
        if len(parts) == 2:
            input_actor_name = parts[0][1:].strip()
            clean_input = parts[1].strip()

    # The usage report is observational. Bypass death-save, PC-focus, initiative,
    # and other phase handling before any of those paths can mutate combat state.
    if is_usage_command_input(clean_input):
        return InputPhaseGateResult(
            "proceed", raw_input, clean_input, input_actor_name
        )

    pending_death_pc = None
    if multi_pc_manager and multi_pc_manager.combat_phase == "PC_PHASE":
        pending_death_pc = multi_pc_manager.get_next_pending_death_save_pc()
        if pending_death_pc:
            owner_ok, _, owner_error = multi_pc_manager.validate_death_save_input_actor(
                input_actor_name,
                fallback_actor_name=multi_pc_manager.current_pc_name or party_tracker_data.get("active_character"),
            )
            if trace_enabled():
                pending_state = multi_pc_manager.pc_states.get(pending_death_pc)
                saves_before = {
                    "successes": getattr(pending_state, "death_save_successes", None),
                    "failures": getattr(pending_state, "death_save_failures", None),
                }
                trace_combat_observation(
                    "death_save_actor_gate", actor=input_actor_name or
                    party_tracker_data.get("active_character"), pending_pc=pending_death_pc,
                    accepted=bool(owner_ok), saves_before=saves_before,
                )
            if not owner_ok:
                io.emit(f"[skipTTS] Dungeon Master: [SYSTEM] {owner_error}")
                io.flush()
                return InputPhaseGateResult("continue", raw_input, clean_input, input_actor_name, pending_death_pc)

    if multi_pc_manager and input_actor_name:
        current_active = multi_pc_manager.current_pc_name
        if current_active and input_actor_name.lower() != current_active.lower():
            io.debug(
                f"SWITCH: Detected actor mismatch (Input: {input_actor_name} != Active: {current_active})",
                category="combat_events",
            )
            target_pc = next(
                (name for name in multi_pc_manager.pc_states if name.lower() == input_actor_name.lower()),
                None,
            )
            if target_pc:
                # TABLETOP MODE: The combat host commits against current persisted state.
                writer = io.commit_active_character or commit_active_character
                selection = writer(target_pc)
                if getattr(selection, "status", None) in {"updated", "unchanged"}:
                    sync_active_pc_fields(party_tracker_data, selection)
                    multi_pc_manager.set_current_pc(target_pc)
                    io.debug(f"SWITCH: Force-switched active PC to {target_pc}", category="combat_events")
                else:
                    io.debug(
                        f"SWITCH: Could not commit active PC {target_pc}",
                        category="party_state",
                    )

    cmd = clean_input.lower()
    if multi_pc_manager and encounter_data.get("awaitingPcGroupRoll", False):
        observations_enabled = trace_enabled()
        initiative_before = ({
            "winner": encounter_data.get("initiativeWinner"),
            "awaiting": encounter_data.get("awaitingPcGroupRoll"),
            "opening_batch_pending": encounter_data.get("openingEnemyBatchPending"),
            "round_starts_with": encounter_data.get("roundStartsWith"),
        } if observations_enabled else {})
        gate_result = initiative_gate(cmd, encounter_data, multi_pc_manager, party_tracker_data)
        if observations_enabled and not gate_result.get("handled"):
            trace_combat_observation(
                "initiative_gate", accepted=bool(gate_result.get("handled")),
                input=clean_input, before=initiative_before,
                after={"winner": encounter_data.get("initiativeWinner"),
                       "awaiting": encounter_data.get("awaitingPcGroupRoll"),
                       "opening_batch_pending": encounter_data.get("openingEnemyBatchPending"),
                       "round_starts_with": encounter_data.get("roundStartsWith")},
                expected_winner=gate_result.get("winner"),
                marker_enabled=gate_result.get("marker_enabled"),
                eligible_non_pc_cohort=multi_pc_manager.get_remaining_enemies_for_round()
                if gate_result.get("handled") else None,
            )
        if not gate_result["handled"]:
            if gate_result["error_message"]:
                io.emit(gate_result["error_message"])
                io.flush()
            return InputPhaseGateResult(
                "continue", raw_input, clean_input, input_actor_name, pending_death_pc
            )
        encounter_data.update(gate_result["encounter_updates"])
        multi_pc_manager.pc_phase_complete = gate_result["winner"] != "pcGroup"
        marker_text = (
            "PHASE_MARKER: Set openingEnemyBatchPending=True via /init dmGroup path"
            if gate_result["marker_enabled"]
            else "PHASE_MARKER: Cleared openingEnemyBatchPending via /init pcGroup path"
        )
        io.debug(marker_text, category="combat_events")
        io.save_json(json_file_path, encounter_data)
        party_tracker_data.setdefault("worldConditions", {})["combatInitiative"] = gate_result["mirror_payload"]
        io.save_json("party_tracker.json", party_tracker_data)
        if observations_enabled:
            trace_combat_observation(
                "initiative_gate", accepted=True,
                input=clean_input, before=initiative_before,
                after={"winner": encounter_data.get("initiativeWinner"),
                       "awaiting": encounter_data.get("awaitingPcGroupRoll"),
                       "opening_batch_pending": encounter_data.get("openingEnemyBatchPending"),
                       "round_starts_with": encounter_data.get("roundStartsWith")},
                expected_winner=gate_result.get("winner"),
                marker_enabled=gate_result.get("marker_enabled"),
                eligible_non_pc_cohort=multi_pc_manager.get_remaining_enemies_for_round(),
            )
        io.debug(
            f"INITIATIVE: Received /init {gate_result['pc_group_roll']}. DM_GROUP={gate_result['dm_group_roll']}, "
            f"winner={gate_result['winner']}, phase={gate_result['phase_label']}",
            category="combat_events",
        )
        phase_label_display = str(gate_result.get("phase_label", "")).replace("_", " ")
        io.emit(
            f"Dungeon Master: [SYSTEM] Initiative locked. DM GROUP {gate_result['dm_group_roll']} vs "
            f"PC GROUP {gate_result['pc_group_roll']}. Starting {phase_label_display}."
        )
        io.flush()
        if gate_result["winner"] == "pcGroup":
            active_pc_name = multi_pc_manager.current_pc_name or party_tracker_data.get("active_character") or "the active PC"
            io.emit(f"Dungeon Master: Your party has the initiative and strikes first, what does {active_pc_name} do?")
            io.flush()
            return InputPhaseGateResult(
                "continue", raw_input, clean_input, input_actor_name,
                pending_death_pc, pc_phase_started=True,
            )
        pending_enemies = multi_pc_manager.get_remaining_enemies_for_round()
        pending_list_str = ", ".join(pending_enemies) if pending_enemies else "all remaining enemies/NPCs"
        conversation_history.append({
            "role": "user",
            "content": (
                "System: Initiative resolved. DM_GROUP won the opening phase. PROCEED TO ENEMY PHASE.\n"
                f"Turn Order: {pending_list_str}.\n"
                "INSTRUCTIONS: Generate actions for exactly these combatants in order. Once they have acted, STOP.\n"
                "If this ends the round, increment 'combat_round' in your JSON, but DO NOT narrate the start of the next round."
            ),
        })
        io.save_json(conversation_history_file, conversation_history)
        clean_input = "Enemies turn."
        return InputPhaseGateResult("proceed", "Enemies turn.", clean_input, input_actor_name, pending_death_pc)

    if multi_pc_manager and multi_pc_manager.combat_phase == "PC_PHASE":
        pending_pc = pending_death_pc or multi_pc_manager.get_next_pending_death_save_pc()
        if pending_pc:
            parser = parse_death_save_roll or io.parse_death_save_roll
            valid, roll, error_message = parser(clean_input, True)
            observations_enabled = trace_enabled()
            saves_before = {"successes": None, "failures": None}
            if observations_enabled:
                pending_state = multi_pc_manager.pc_states.get(pending_pc)
                saves_before = {
                    "successes": getattr(pending_state, "death_save_successes", None),
                    "failures": getattr(pending_state, "death_save_failures", None),
                }
            if not valid:
                if observations_enabled:
                    trace_combat_observation(
                        "death_save_roll", actor=input_actor_name or
                        party_tracker_data.get("active_character"), pending_pc=pending_pc,
                        input=clean_input, valid=False, roll=roll, before=saves_before, after=saves_before,
                    )
                if error_message is not None:
                    io.emit(f"[skipTTS] Dungeon Master: [SYSTEM] {error_message}")
                else:
                    io.emit(f"[skipTTS] Dungeon Master: [SYSTEM] Resolve {pending_pc}'s death saving throw first. Enter 1-20 or /death <1-20>.")
                io.flush()
                return InputPhaseGateResult("continue", raw_input, clean_input, input_actor_name, pending_pc)
            ok, message = multi_pc_manager.resolve_death_save_roll(pending_pc, roll)
            if observations_enabled:
                resolved_state = multi_pc_manager.pc_states.get(pending_pc)
                saves_after = {
                    "successes": getattr(resolved_state, "death_save_successes", None),
                    "failures": getattr(resolved_state, "death_save_failures", None),
                }
                trace_combat_observation(
                    "death_save_roll", actor=input_actor_name or
                    party_tracker_data.get("active_character"), pending_pc=pending_pc,
                    input=clean_input, valid=bool(ok), roll=roll, before=saves_before, after=saves_after,
                    resolved_pc=pending_pc if ok else None,
                )
            io.emit(message)
            io.flush()
            if not ok or multi_pc_manager.get_next_pending_death_save_pc():
                return InputPhaseGateResult("continue", raw_input, clean_input, input_actor_name, pending_pc)
            return InputPhaseGateResult("continue", raw_input, clean_input, input_actor_name, pending_pc)

    return InputPhaseGateResult("proceed", raw_input, clean_input, input_actor_name, pending_death_pc)


@dataclass(frozen=True)
class RoundTransitionDependencies:
    """Current owner bindings for AI-reported round advancement."""

    apply_opening_batch_marker: Callable[[Dict[str, Any], str], bool]
    sync_available: bool
    save_json: Callable[[str, Any], Any]
    compress_old_rounds: Callable[..., List[Dict[str, Any]]]
    log_debug: Callable[..., Any]
    log_info: Callable[..., Any]
    log_warning: Callable[..., Any]
    bind_history: Callable[[List[Dict[str, Any]]], Any]


@dataclass
class RoundTransitionResult:
    """Staged round/phase snapshot and any boundary-compressed history."""

    encounter_data: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    phase_transitioned: bool = False
    round_advanced: bool = False


_COMBAT_PHASES = frozenset({"PC_PHASE", "ENEMY_PHASE"})


def stage_combat_turn_snapshot(
    encounter_data: Dict[str, Any],
    conversation_history: List[Dict[str, Any]],
    *,
    phase_before: Optional[str],
    phase_after: Optional[str],
    enemy_batch_completed: bool,
    opening_batch_pending_before: bool,
    authoritative_round_before: Optional[int] = None,
    round_starts_with_before: Optional[str] = None,
    dependencies: RoundTransitionDependencies,
) -> RoundTransitionResult:
    """Derive the final phase/round projection without changing runtime state.

    A completed opening enemy batch returns to PC play in the same round. A
    completed non-opening enemy phase advances exactly one round. Model output
    is deliberately not an input: the accepted turn and persisted phase marker
    own this transition.
    """
    if not isinstance(encounter_data, dict) or not isinstance(conversation_history, list):
        raise TypeError("combat turn snapshot inputs are invalid")

    current_round = (
        authoritative_round_before
        if authoritative_round_before is not None
        else encounter_data.get(
            "combat_round", encounter_data.get("current_round", 1)
        )
    )
    if (
        not isinstance(current_round, int)
        or isinstance(current_round, bool)
        or current_round < 1
    ):
        raise ValueError("authoritative combat round must be a positive integer")

    if phase_before not in _COMBAT_PHASES:
        phase_before = encounter_data.get("combat_phase")
    if phase_before not in _COMBAT_PHASES:
        phase_before = "ENEMY_PHASE" if opening_batch_pending_before else "PC_PHASE"
    if phase_after not in _COMBAT_PHASES:
        phase_after = phase_before

    opening_pending = opening_batch_pending_before is True
    round_starts_with = (
        round_starts_with_before
        if round_starts_with_before is not None
        else encounter_data.get("roundStartsWith", "pcGroup")
    )
    dmgroup_round_start = False
    if enemy_batch_completed and phase_before == "ENEMY_PHASE":
        if opening_pending:
            if round_starts_with != "dmGroup":
                raise ValueError("opening enemy batch phase markers are inconsistent")
            final_round = current_round
            final_phase = "PC_PHASE"
            final_opening_pending = False
            pcgroup_round_start = False
        else:
            final_round = current_round + 1
            if round_starts_with == "dmGroup":
                final_phase = "ENEMY_PHASE"
                final_opening_pending = True
                pcgroup_round_start = False
                dmgroup_round_start = True
            else:
                final_phase = "PC_PHASE"
                final_opening_pending = False
                pcgroup_round_start = True
    else:
        final_round = current_round
        final_phase = phase_after
        final_opening_pending = opening_pending
        pcgroup_round_start = False

    projection = copy.deepcopy(encounter_data)
    projection["combat_round"] = final_round
    if "current_round" in projection or final_round != current_round:
        projection["current_round"] = final_round
    projection["combat_phase"] = final_phase
    projection["openingEnemyBatchPending"] = final_opening_pending

    if dmgroup_round_start:
        if dependencies.sync_available:
            marker_enabled = dependencies.apply_opening_batch_marker(
                projection, "dmGroup"
            )
            if marker_enabled is not True:
                raise ValueError("round-start DM-group opening marker was not enabled")
        dependencies.log_debug(
            "STATE_CHANGE: Applied roundStartsWith=dmGroup -> ENEMY_PHASE start",
            category="combat_events",
        )
        dependencies.log_debug(
            "PHASE_MARKER: Set openingEnemyBatchPending=True via round-start dmGroup path",
            category="combat_events",
        )

    if pcgroup_round_start:
        dependencies.log_debug(
            "PHASE_MARKER: Cleared openingEnemyBatchPending via round-start pcGroup path",
            category="combat_events",
        )
        dependencies.log_debug(
            "STATE_CHANGE: Applied roundStartsWith=pcGroup -> PC_PHASE start",
            category="combat_events",
        )

    history = conversation_history
    round_advanced = final_round > current_round
    if round_advanced and final_round >= 2:
        dependencies.log_debug(
            "COMPRESSION: Checking for round compression (current round: %s)"
            % final_round,
            category="combat_events",
        )
        try:
            compressed_history = dependencies.compress_old_rounds(
                conversation_history,
                final_round,
                keep_recent_rounds=1,
            )
        except Exception as exc:
            dependencies.log_warning(
                "COMPRESSION: Boundary compression failed; retaining combat history: %s"
                % exc,
                category="combat_events",
            )
            compressed_history = conversation_history
        if compressed_history != conversation_history:
            history = compressed_history
            dependencies.bind_history(compressed_history)
            dependencies.log_info(
                "COMPRESSION: Combat history compressed in staged turn state",
                category="combat_events",
            )

    return RoundTransitionResult(
        encounter_data=projection,
        conversation_history=history,
        phase_transitioned=(
            final_phase != phase_before
            or final_opening_pending != opening_pending
            or round_advanced
        ),
        round_advanced=round_advanced,
    )


def apply_reported_round_transition(
    parsed_response: Dict[str, Any],
    encounter_data: Dict[str, Any],
    conversation_history: List[Dict[str, Any]],
    *,
    encounter_id: str,
    conversation_history_file: str,
    multi_pc_manager: Any,
    dependencies: RoundTransitionDependencies,
) -> RoundTransitionResult:
    """Ignore model-reported counters and stage the current authoritative state.

    Runtime round advancement is performed by ``stage_combat_turn_snapshot``
    from explicit Python-owned phase transitions, never from this response.
    This narrow helper remains for callers that still inspect the response at
    the former boundary.
    """
    requested_round = (
        parsed_response.get("combat_round")
        if isinstance(parsed_response, dict) else None
    )
    current_round = encounter_data.get(
        "combat_round", encounter_data.get("current_round", 1)
    )
    if requested_round != current_round:
        dependencies.log_debug(
            "ROUND_TRACKING: Ignoring model-reported combat_round=%s; authoritative round=%s"
            % (requested_round, current_round),
            category="combat_events",
        )
    phase = getattr(multi_pc_manager, "combat_phase", None)
    return stage_combat_turn_snapshot(
        encounter_data,
        conversation_history,
        phase_before=phase,
        phase_after=phase,
        enemy_batch_completed=False,
        opening_batch_pending_before=(
            encounter_data.get("openingEnemyBatchPending") is True
        ),
        dependencies=dependencies,
    )


def sync_committed_combat_turn(
    encounter_data: Dict[str, Any],
    multi_pc_manager: Any,
    session: Any = None,
) -> str:
    """Synchronize runtime managers and session from a durable turn snapshot."""
    if not isinstance(encounter_data, dict):
        raise TypeError("committed encounter snapshot must be an object")
    if multi_pc_manager is not None:
        multi_pc_manager.sync_committed_turn_state(encounter_data)
        phase = multi_pc_manager.combat_phase
    else:
        phase = encounter_data.get("combat_phase", "PC_PHASE")
        if phase not in _COMBAT_PHASES:
            raise ValueError("committed encounter phase is invalid")
    if session is not None:
        session.bind_encounter(encounter_data)
        if multi_pc_manager is not None:
            session.active_pc = (
                multi_pc_manager.current_pc_name or session.active_pc
            )
        session.set_phase(phase)
    # TABLETOP MODE: This is the durable post-commit synchronization boundary.
    maybe_inject_combat_turn_fault("after_phase_sync")
    return phase


def complete_opening_enemy_batch(
    encounter_data: Dict[str, Any],
    multi_pc_manager: Any,
    *,
    encounter_id: str,
    save_json: Callable[[str, Any], Any],
    debug: Callable[..., Any],
) -> bool:
    """Close the persisted opening batch at its existing post-action point."""
    if not multi_pc_manager or not encounter_data.get("openingEnemyBatchPending", False):
        return False
    encounter_data["openingEnemyBatchPending"] = False
    multi_pc_manager.pc_phase_complete = False
    if trace_enabled():
        trace_combat_observation(
            "opening_enemy_batch_completed", encounter_id=encounter_id,
            batch_completed=True,
            opening_marker_before=True, opening_marker_after=False,
            pc_phase_complete=multi_pc_manager.pc_phase_complete,
            round_starts_with=encounter_data.get("roundStartsWith"),
        )
    debug("PHASE_MARKER: Cleared openingEnemyBatchPending after opening enemy batch resolution", category="combat_events")
    debug("STATE_CHANGE: Opening batch complete -> PC_PHASE", category="combat_events")
    save_json(f"modules/encounters/encounter_{encounter_id}.json", encounter_data)
    return True
