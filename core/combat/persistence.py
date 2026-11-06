# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Persistence - Action application and character update orchestration.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

# ============================================================================
# COMBAT PERSISTENCE - GAME SYSTEMS LAYER - COMBAT
# ============================================================================
# ARCHITECTURE ROLE: Combat Domain Persistence/Application Stage
#
# This module applies validated combat action payloads and commits the existing
# queued character updates through injected owner dependencies. Callers retain
# the legacy physical call points and persistence order.
# ============================================================================

from dataclasses import dataclass
import copy
import json
import math
from typing import Any, Callable, Dict, List, Optional, Tuple
from utils.combat_latency_trace import trace_combat_observation, trace_enabled
from utils.pc_manager import (
    ActivePCWriteResult,
    commit_active_character,
    sync_active_pc_fields,
)


@dataclass(frozen=True)
class CombatFinalizationInputs:
    """Existing exit-time state consumed after the action/commit stages."""

    party_tracker_data: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    location_info: Dict[str, Any]
    encounter_id: str
    player_file: str


@dataclass(frozen=True)
class CombatFinalizationDependencies:
    """Current owner callbacks for summary, cleanup, transcript, and final read."""

    summarize_dialogue: Callable[..., Any]
    safe_write_json: Callable[[str, Any], Any]
    generate_chat_history: Callable[[List[Dict[str, Any]], str], Any]
    safe_json_load: Callable[[str], Any]
    log_info: Callable[..., Any]
    log_debug: Callable[..., Any]


@dataclass(frozen=True)
class CombatFinalizationResult:
    """Historical public return values produced after ordered cleanup."""

    dialogue_summary: Any
    player_info: Any


def finalize_combat_session(
    inputs: CombatFinalizationInputs,
    dependencies: CombatFinalizationDependencies,
) -> CombatFinalizationResult:
    """Summarize, clear the active encounter, save history, then reload the PC."""
    world_conditions = inputs.party_tracker_data.get("worldConditions", {})
    last_encounter_id = world_conditions.get("activeCombatEncounter", "")
    dependencies.log_info("AI_CALL: Generating final combat summary...", category="ai_operations")
    dialogue_summary = dependencies.summarize_dialogue(
        inputs.conversation_history, inputs.location_info, inputs.party_tracker_data
    )
    if "worldConditions" in inputs.party_tracker_data and "activeCombatEncounter" in inputs.party_tracker_data["worldConditions"]:
        if last_encounter_id:
            inputs.party_tracker_data["worldConditions"]["lastCompletedEncounter"] = last_encounter_id
        inputs.party_tracker_data["worldConditions"]["activeCombatEncounter"] = ""
        dependencies.log_debug(
            f"STATE_CHANGE: Cleared active combat encounter. Last completed is now {last_encounter_id}",
            category="combat_events",
        )
        persisted = dependencies.safe_write_json("party_tracker.json", inputs.party_tracker_data)
        if persisted is True:
            # TABLETOP MODE: Combat teardown has committed its canonical owner;
            # publish a typed notice for a fresh player-safe projection.
            from utils.player_host_publication import submit_player_host_change

            submit_player_host_change("combat")
    dependencies.log_info("FILE_OP: Saving final combat chat history log...", category="combat_logs")
    dependencies.generate_chat_history(inputs.conversation_history, inputs.encounter_id)
    player_info = dependencies.safe_json_load(inputs.player_file)
    dependencies.log_info("SUCCESS: Combat complete. Exiting simulation.", category="combat_events")
    return CombatFinalizationResult(dialogue_summary, player_info)


@dataclass(frozen=True)
class CombatActionDependencies:
    """Current owner callbacks required while processing a validated action list."""

    queue_character_update: Callable[..., None]
    update_encounter: Callable[..., Any]
    normalize_encounter_status: Callable[[Dict[str, Any]], Dict[str, Any]]
    sync_non_pc_queue_state: Callable[[Any, Dict[str, Any]], bool]
    log_info: Callable[..., Any]
    log_debug: Callable[..., Any]
    log_error: Callable[..., Any]
    log_warning: Callable[..., Any]
    calculate_xp: Callable[[], Any]
    save_json: Callable[[str, Any], Any]
    active_character_update_available: bool
    emit_combat_event: Callable[..., Any]
    get_current_actor: Callable[[Any], Any]
    advance_turn: Callable[[Any], Any]
    get_pc_state: Callable[[Any, str], Any]
    pc_acted_status: Any
    npc_combatant_type: Any
    pc_combatant_type: Any
    check_all_monsters_defeated: Callable[[Dict[str, Any]], bool]
    calculate_xp_for_encounter: Optional[Callable[[Dict[str, Any]], Any]] = None
    commit_active_character: Optional[Callable[[str], ActivePCWriteResult]] = None


@dataclass
class CombatActionBatchResult:
    """Mutable handoff from in-order action handling to post-batch processing."""

    encounter_data: Dict[str, Any]
    final_character_updates: Dict[str, List[Dict[str, Any]]]
    is_combat_ending: bool


def stage_final_character_update(
    character_name: str,
    update_entries: List[Dict[str, Any]],
    current_data: Dict[str, Any],
    update_character_info: Callable[..., Any],
    log_error: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Apply queued updates to an in-memory character projection, in legacy order."""
    if not isinstance(current_data, dict):
        raise ValueError("character stage requires an object")
    staged = copy.deepcopy(current_data)
    ops_entries = [entry for entry in update_entries if entry.get("ops")]
    prose_changes = [
        entry.get("changes") for entry in update_entries
        if entry.get("changes") and not entry.get("ops")
    ]
    for entry in ops_entries:
        result = update_character_info(
            character_name,
            entry.get("changes") or "",
            ops=entry.get("ops"),
            _stage_only=True,
            _stage_data=staged,
        )
        # TABLETOP MODE: Match the legacy commit loop, where one rejected
        # deterministic operation does not discard later queued character work.
        if result is False:
            if log_error is not None:
                log_error(
                    f"FAILURE: Deterministic combat update failed for {character_name}.",
                    category="character_updates",
                )
            continue
        if not isinstance(result, dict):
            raise ValueError("deterministic character stage failed")
        staged = result
    if prose_changes:
        final_change_string = (
            "Following the turn's events: " + ", and ".join(prose_changes) + "."
        )
        result = update_character_info(
            character_name,
            final_change_string,
            _stage_only=True,
            _stage_data=staged,
        )
        if result is False:
            if log_error is not None:
                log_error(
                    f"FAILURE: Final consolidated update failed for {character_name}.",
                    category="character_updates",
                )
            return staged
        if not isinstance(result, dict):
            raise ValueError("prose character stage failed")
        staged = result
    return staged


def _calculate_staged_xp(
    dependencies: CombatActionDependencies,
    encounter_data: Dict[str, Any],
) -> Any:
    if dependencies.calculate_xp_for_encounter is not None:
        return dependencies.calculate_xp_for_encounter(encounter_data)
    return dependencies.calculate_xp()


def _commit_combat_active_pc(
    dependencies: CombatActionDependencies,
    party_tracker_data: Dict[str, Any],
    character_name: str,
) -> bool:
    """Commit a host-authoritative combat switch and sync only selection fields."""
    writer = dependencies.commit_active_character or commit_active_character
    result = writer(character_name)
    if getattr(result, "status", None) not in {"updated", "unchanged"}:
        dependencies.log_error(
            f"TABLETOP MODE: Combat active-PC selection failed for {character_name}.",
            category="party_state",
        )
        return False
    sync_active_pc_fields(party_tracker_data, result)
    return True


def queue_final_character_update(
    final_character_updates: Dict[str, List[Dict[str, Any]]],
    character_name: Optional[str],
    changes: Optional[str] = None,
    ops: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Queue one character update without changing deterministic ops payloads."""
    if not character_name or (not changes and not ops):
        return
    final_character_updates.setdefault(character_name, []).append({"changes": changes, "ops": ops})


def _bounded_encounter_hp_projection(encounter: Any, source: str) -> Dict[str, Any]:
    """Return flat, bounded HP evidence without changing the supplied encounter."""
    rows = encounter.get("creatures") if isinstance(encounter, dict) else None
    count = len(rows) if isinstance(rows, list) else 0
    hp_rows = []
    seen = set()
    incomplete = not isinstance(rows, list)
    truncated = count > 12
    for row in rows[:12] if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            incomplete = True
            continue
        name = row.get("name")
        hp = row.get("currentHitPoints")
        if not isinstance(name, str) or not name.strip() or len(name) > 40:
            incomplete = True
            continue
        identity = name.casefold()
        if identity in seen:
            incomplete = True
            continue
        seen.add(identity)
        if (not isinstance(hp, (int, float)) or isinstance(hp, bool) or
                not math.isfinite(hp) or int(hp) != hp):
            incomplete = True
            continue
        hp_rows.append([name, int(hp)])
    if count > 12:
        incomplete = True
    encoded = json.dumps(hp_rows, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > 480:
        encoded = "[]"
        incomplete = True
        truncated = True
    return {"hp_status": "incomplete" if incomplete else "complete",
            "hp_count": count, "hp_rows": encoded,
            "hp_truncated": truncated, "hp_source": source}


def process_combat_action_batch(
    actions: List[Dict[str, Any]],
    encounter_data: Dict[str, Any],
    final_character_updates: Dict[str, List[Dict[str, Any]]],
    *,
    encounter_id: str,
    conversation_history: List[Dict[str, Any]],
    conversation_history_file: str,
    multi_pc_manager: Any,
    party_tracker_data: Dict[str, Any],
    is_combat_ending: bool,
    dependencies: CombatActionDependencies,
) -> CombatActionBatchResult:
    """Apply encounter actions immediately and queue character changes in order."""
    for action in actions:
        action_type = action.get("action", "").lower()
        parameters = action.get("parameters", {})

        if action_type in ["updateplayerinfo", "updatecharacterinfo", "updatenpcinfo"]:
            char_name_key = "characterName" if "characterName" in parameters else "npcName"
            character_name = parameters.get(char_name_key)
            changes = parameters.get("changes")
            ops = parameters.get("ops")

            if character_name and (changes or ops):
                dependencies.queue_character_update(final_character_updates, character_name, changes, ops)
                if changes:
                    dependencies.log_info(
                        f"CONSOLIDATING: Queued change for {character_name}: '{changes}'",
                        category="combat_events",
                    )
                    if any(word in changes.lower() for word in ["arrow", "bolt", "ammunition", "ammo", "expended"]):
                        dependencies.log_debug(f"AMMO_DEBUG: Detected ammunition change for {character_name}", category="ammunition")
                        dependencies.log_debug(f"AMMO_DEBUG: Action type: {action_type}", category="ammunition")
                        dependencies.log_debug(f"AMMO_DEBUG: Changes text: '{changes}'", category="ammunition")
                        dependencies.log_debug("AMMO_DEBUG: Added to final_character_updates queue", category="ammunition")
                else:
                    dependencies.log_info(f"CONSOLIDATING: Queued deterministic ops for {character_name}", category="combat_events")

        elif action_type == "updateencounter":
            encounter_id_for_update = parameters.get("encounterId", encounter_id)
            changes = parameters.get("changes", "")
            ops = parameters.get("ops")
            dependencies.log_info(f"STATE_UPDATE: Processing immediate encounter update: {changes}", category="encounter_management")
            try:
                try:
                    capture_hp = trace_enabled()
                except Exception:
                    capture_hp = False
                hp_before = None
                if capture_hp:
                    try:
                        hp_before = _bounded_encounter_hp_projection(encounter_data, "preloaded_context")
                    except Exception:
                        hp_before = None
                updated_encounter_data = dependencies.update_encounter(encounter_id_for_update, changes, ops=ops)
                if capture_hp:
                    try:
                        hp_after = _bounded_encounter_hp_projection(
                            updated_encounter_data, "returned_persisted_state"
                        )
                    except Exception:
                        hp_after = {"hp_rows": "[]", "hp_status": "incomplete",
                                    "hp_count": 0, "hp_truncated": False,
                                    "hp_source": "returned_persisted_state"}
                    trace_combat_observation(
                        "combat_apply_result", domain="encounter", operation="update_encounter",
                        target=encounter_id_for_update, changes=changes, ops=ops,
                        applied=bool(updated_encounter_data), returned_state=updated_encounter_data,
                        hp_before=hp_before.get("hp_rows", "[]") if hp_before else "[]",
                        hp_before_status=hp_before.get("hp_status", "incomplete") if hp_before else "incomplete",
                        hp_before_count=hp_before.get("hp_count", 0) if hp_before else 0,
                        hp_before_truncated=hp_before.get("hp_truncated", False) if hp_before else False,
                        hp_before_source=hp_before.get("hp_source", "preloaded_context") if hp_before else "preloaded_context",
                        hp_after=hp_after.get("hp_rows", "[]"),
                        hp_after_status=hp_after.get("hp_status"),
                        hp_after_count=hp_after.get("hp_count"),
                        hp_after_truncated=hp_after.get("hp_truncated"),
                        hp_after_source=hp_after.get("hp_source"),
                        failure=None if updated_encounter_data else "empty_or_false_return",
                    )
                if updated_encounter_data:
                    encounter_data = dependencies.normalize_encounter_status(updated_encounter_data)
                    if multi_pc_manager and dependencies.sync_non_pc_queue_state(multi_pc_manager, encounter_data):
                        dependencies.log_debug(
                            "STATE_SYNC: Refreshed non-PC turn queue state from authoritative encounter data",
                            category="combat_events",
                        )
            except Exception as exc:
                if trace_enabled():
                    trace_combat_observation(
                        "combat_apply_result", domain="encounter", operation="update_encounter",
                        target=encounter_id_for_update, changes=changes, ops=ops,
                        applied=False, failure=type(exc).__name__,
                    )
                dependencies.log_error("FAILURE: Failed to update encounter", exception=exc, category="encounter_management")

        elif action_type == "exit" and is_combat_ending:
            dependencies.log_info("CONSOLIDATING: 'exit' action detected. Calculating final HP and XP.", category="combat_events")
            xp_narrative, xp_awarded = _calculate_staged_xp(
                dependencies, encounter_data
            )
            if trace_enabled():
                trace_combat_observation("xp_award", source="explicit_exit", amount=xp_awarded,
                                         participants=[row.get("name") for row in encounter_data.get("creatures", [])
                                                       if isinstance(row, dict) and row.get("type") in ("player", "npc")])
            dependencies.log_info(f"XP_AWARD: Calculated {xp_awarded} XP per participant.", category="xp_tracking")
            conversation_history.append({"role": "user", "content": f"XP Awarded: {xp_narrative}"})
            dependencies.save_json(conversation_history_file, conversation_history)
            for creature in encounter_data.get("creatures", []):
                if creature.get("type") in ["player", "npc"]:
                    character_name = creature.get("name")
                    if xp_awarded > 0:
                        dependencies.queue_character_update(
                            final_character_updates, character_name, f"awarded {xp_awarded} experience points"
                        )

        if not is_combat_ending and dependencies.check_all_monsters_defeated(encounter_data):
            dependencies.log_info(
                "AUTO_EXIT: All enemies defeated after action processing. LLM failed to call exit - forcing combat end.",
                category="combat_events",
            )
            is_combat_ending = True
            xp_narrative, xp_awarded = _calculate_staged_xp(
                dependencies, encounter_data
            )
            if trace_enabled():
                trace_combat_observation("xp_award", source="auto_exit", amount=xp_awarded,
                                         participants=[row.get("name") for row in encounter_data.get("creatures", [])
                                                       if isinstance(row, dict) and row.get("type") in ("player", "npc")])
            dependencies.log_info(f"XP_AWARD: Auto-exit calculated {xp_awarded} XP per participant.", category="xp_tracking")
            conversation_history.append({"role": "user", "content": f"XP Awarded: {xp_narrative}"})
            dependencies.save_json(conversation_history_file, conversation_history)
            for creature in encounter_data.get("creatures", []):
                if creature.get("type") in ["player", "npc"]:
                    character_name = creature.get("name")
                    if xp_awarded > 0:
                        dependencies.queue_character_update(
                            final_character_updates, character_name, f"awarded {xp_awarded} experience points"
                        )

        if multi_pc_manager and not is_combat_ending:
            current_actor = dependencies.get_current_actor(multi_pc_manager)
            if current_actor and current_actor.type == dependencies.npc_combatant_type:
                if actions:
                    dependencies.log_debug(f"[COMBAT_MANAGER] Auto-advancing turn for NPC {current_actor.name}", category="combat_events")
                    next_actor = dependencies.advance_turn(multi_pc_manager)
                    if next_actor.type == dependencies.pc_combatant_type:
                        # TABLETOP MODE: Combat authority advances from current persisted selection.
                        selection_committed = _commit_combat_active_pc(
                            dependencies, party_tracker_data, next_actor.name
                        )
                        if selection_committed and dependencies.active_character_update_available:
                            dependencies.emit_combat_event("active_character_update", {"character": next_actor.name})
                        if selection_committed:
                            dependencies.log_debug(f"[COMBAT_MANAGER] Advanced active character to {next_actor.name}", category="combat_events")
                    else:
                        dependencies.log_debug(f"[COMBAT_MANAGER] Advanced turn to next enemy/NPC: {next_actor.name}", category="combat_events")

            active_pc_name = multi_pc_manager.current_pc_name
            if active_pc_name:
                active_state = dependencies.get_pc_state(multi_pc_manager, active_pc_name)
                if active_state and active_state.status == dependencies.pc_acted_status:
                    dependencies.log_debug(f"[COMBAT_MANAGER] Detected ACTED status for {active_pc_name}, advancing turn queue", category="combat_events")
                    next_actor = dependencies.advance_turn(multi_pc_manager)
                    if next_actor.type == dependencies.pc_combatant_type:
                        # TABLETOP MODE: Commit the turn switch without stale party persistence.
                        selection_committed = _commit_combat_active_pc(
                            dependencies, party_tracker_data, next_actor.name
                        )
                        if selection_committed and dependencies.active_character_update_available:
                            dependencies.emit_combat_event("active_character_update", {"character": next_actor.name})
                        if selection_committed:
                            dependencies.log_debug(f"[COMBAT_MANAGER] Advanced active character to {next_actor.name}", category="combat_events")
                    else:
                        dependencies.log_debug(f"[COMBAT_MANAGER] Advanced turn to enemy/NPC: {next_actor.name}", category="combat_events")

    return CombatActionBatchResult(encounter_data, final_character_updates, is_combat_ending)


@dataclass(frozen=True)
class CharacterUpdateDependencies:
    """Current owner callbacks for end-of-turn character persistence."""

    update_character_info: Callable[..., Any]
    normalize_character_name: Callable[[str], str]
    safe_json_load: Callable[[str], Any]
    sync_character_state: Callable[[Any, str], Any]
    log_info: Callable[..., Any]
    log_debug: Callable[..., Any]
    log_error: Callable[..., Any]


def sync_multi_pc_character_state(multi_pc_manager: Any, character_name: str, dependencies: CharacterUpdateDependencies) -> None:
    """Refresh the manager cache after the authoritative character update."""
    if not multi_pc_manager:
        return
    persisted_path = f"characters/{dependencies.normalize_character_name(character_name)}.json"
    persisted_data = dependencies.safe_json_load(persisted_path)
    if trace_enabled():
        trace_combat_observation(
            "combat_apply_persisted_state", domain="character", target=character_name,
            state_path=persisted_path,
            persisted_state=persisted_data if isinstance(persisted_data, dict) else None,
        )
    if isinstance(persisted_data, dict):
        multi_pc_manager.sync_pc_persistent_state(character_name, persisted_data)


def apply_final_character_updates(
    final_character_updates: Dict[str, List[Dict[str, Any]]],
    multi_pc_manager: Any,
    dependencies: CharacterUpdateDependencies,
) -> None:
    """Persist queued character updates while preserving ops/prose fallback order."""
    if not final_character_updates:
        return
    dependencies.log_info("STATE_UPDATE: Applying all consolidated updates.", category="character_updates")
    dependencies.log_debug(f"AMMO_DEBUG: Processing {len(final_character_updates)} character updates", category="ammunition")
    for character_name, update_entries in final_character_updates.items():
        ops_entries = [entry for entry in update_entries if entry.get("ops")]
        prose_changes = [entry.get("changes") for entry in update_entries if entry.get("changes") and not entry.get("ops")]
        for entry in ops_entries:
            entry_changes = entry.get("changes") or ""
            entry_ops = entry.get("ops")
            try:
                update_success = dependencies.update_character_info(character_name, entry_changes, ops=entry_ops)
                if trace_enabled():
                    trace_combat_observation(
                        "combat_apply_result", domain="character", operation="update_character_info_ops",
                        target=character_name, changes=entry_changes, ops=entry_ops,
                        applied=bool(update_success), failure=None if update_success else "false_return",
                    )
                if not update_success:
                    dependencies.log_error(f"FAILURE: Deterministic combat update failed for {character_name}.", category="character_updates")
                    continue
                dependencies.sync_character_state(multi_pc_manager, character_name)
            except Exception as exc:
                if trace_enabled():
                    trace_combat_observation(
                        "combat_apply_result", domain="character", operation="update_character_info_ops",
                        target=character_name, changes=entry_changes, ops=entry_ops,
                        applied=False, failure=type(exc).__name__,
                    )
                dependencies.log_error(f"FAILURE: Critical error during deterministic combat update for {character_name}", exception=exc, category="character_updates")
        if prose_changes:
            final_change_string = "Following the turn's events: " + ", and ".join(prose_changes) + "."
            dependencies.log_info(f"FINAL_CHANGE_STRING for {character_name}: {final_change_string}", category="character_updates")
            if any(word in final_change_string.lower() for word in ["arrow", "bolt", "ammunition", "ammo", "expended"]):
                dependencies.log_debug(f"AMMO_DEBUG: About to update ammunition for {character_name}", category="ammunition")
                dependencies.log_debug(f"AMMO_DEBUG: Final change string: '{final_change_string}'", category="ammunition")
            try:
                update_success = dependencies.update_character_info(character_name, final_change_string)
                if trace_enabled():
                    trace_combat_observation(
                        "combat_apply_result", domain="character", operation="update_character_info_prose",
                        target=character_name, changes=final_change_string, applied=bool(update_success),
                        failure=None if update_success else "false_return",
                    )
                if not update_success:
                    dependencies.log_error(f"FAILURE: Final consolidated update failed for {character_name}.", category="character_updates")
                else:
                    dependencies.sync_character_state(multi_pc_manager, character_name)
                    if any(word in final_change_string.lower() for word in ["arrow", "bolt", "ammunition", "ammo", "expended"]):
                        dependencies.log_debug(f"AMMO_DEBUG: Successfully processed ammunition update for {character_name}", category="ammunition")
            except Exception as exc:
                if trace_enabled():
                    trace_combat_observation(
                        "combat_apply_result", domain="character", operation="update_character_info_prose",
                        target=character_name, changes=final_change_string,
                        applied=False, failure=type(exc).__name__,
                    )
                dependencies.log_error(f"FAILURE: Critical error during consolidated update for {character_name}", exception=exc, category="character_updates")
                if any(word in final_change_string.lower() for word in ["arrow", "bolt", "ammunition", "ammo", "expended"]):
                    dependencies.log_debug(f"AMMO_DEBUG: Exception during ammunition update: {str(exc)}", category="ammunition")
