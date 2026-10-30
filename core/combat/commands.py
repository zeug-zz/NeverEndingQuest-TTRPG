# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Deterministic fast-command stage for the combat turn pipeline."""

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class FastCommandResult:
    """Typed handoff from deterministic commands to the next turn stage."""

    control_action: str = "proceed"
    user_input_text: str = ""
    clean_input: str = ""
    input_actor_name: Optional[str] = None
    return_value: Any = None
    status: str = "ok"
    reason: str = ""
    exit_code: Optional[int] = None


def is_usage_command_input(value: Any) -> bool:
    """Recognize only the read-only usage command, including tagged player input."""
    if not isinstance(value, str):
        return False
    command = value.strip()
    if command.startswith("[") and "]:" in command:
        command = command.split("]:", 1)[1].strip()
    return command.casefold() == "/usage"


def _usage_report_count(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        count = int(value)
        if count < 0 or float(value) != count:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return count


def _format_usage_count(value: Any) -> str:
    count = _usage_report_count(value)
    return "--" if count is None else f"{count:,}"


def _format_usage_cost(value: Any) -> str:
    if isinstance(value, bool):
        return "--"
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        return "--"
    if not 0 <= amount < float("inf"):
        return "--"
    return f"${amount:,.6f} USD"


def _format_usage_completeness(value: Any) -> str:
    if value is True:
        return "complete"
    if value is False:
        return "incomplete"
    return "unknown"


def format_usage_report(router_stats: Any, session_stats: Any) -> str:
    """Render detached router and tracker snapshots without accounting a call."""
    if not isinstance(router_stats, dict):
        router_stats = {}
    if not isinstance(session_stats, dict):
        session_stats = {}

    prompt_tokens = _usage_report_count(router_stats.get("prompt_tokens"))
    completion_tokens = _usage_report_count(router_stats.get("completion_tokens"))
    total_tokens = (
        None
        if prompt_tokens is None or completion_tokens is None
        else prompt_tokens + completion_tokens
    )

    return (
        "[skipTTS] Dungeon Master: [SYSTEM] Usage:\n"
        "  Router: calls {calls}; tokens {tokens} (prompt {prompt}, cached {cached}, "
        "completion {completion}); known cost {cost}; unpriced calls {unpriced}; "
        "cost coverage {complete}.\n"
        "  Session: tokens {session_tokens}; actual {session_actual}; estimated "
        "{session_estimated}; known cost {session_cost}; unpriced calls "
        "{session_unpriced}; cost coverage {session_complete}.\n"
        "  Rolling week: tokens {week_tokens}; actual {week_actual}; estimated "
        "{week_estimated}; known cost {week_cost}; unpriced calls {week_unpriced}; "
        "cost coverage {week_complete}."
    ).format(
        calls=_format_usage_count(router_stats.get("calls")),
        tokens="--" if total_tokens is None else _format_usage_count(total_tokens),
        prompt="--" if prompt_tokens is None else _format_usage_count(prompt_tokens),
        cached=_format_usage_count(router_stats.get("cached_tokens")),
        completion=(
            "--"
            if completion_tokens is None
            else _format_usage_count(completion_tokens)
        ),
        cost=_format_usage_cost(router_stats.get("total_cost_usd")),
        unpriced=_format_usage_count(router_stats.get("unpriced_calls")),
        complete=_format_usage_completeness(router_stats.get("cost_complete")),
        session_tokens=_format_usage_count(session_stats.get("session_tokens")),
        session_actual=_format_usage_cost(
            session_stats.get("session_cost_actual_usd")
        ),
        session_estimated=_format_usage_cost(
            session_stats.get("session_cost_estimated_usd")
        ),
        session_cost=_format_usage_cost(session_stats.get("session_cost_usd")),
        session_unpriced=_format_usage_count(
            session_stats.get("session_unpriced_calls")
        ),
        session_complete=_format_usage_completeness(
            session_stats.get("session_cost_complete")
        ),
        week_tokens=_format_usage_count(session_stats.get("week_tokens")),
        week_actual=_format_usage_cost(session_stats.get("week_cost_actual_usd")),
        week_estimated=_format_usage_cost(
            session_stats.get("week_cost_estimated_usd")
        ),
        week_cost=_format_usage_cost(session_stats.get("week_cost_usd")),
        week_unpriced=_format_usage_count(session_stats.get("week_unpriced_calls")),
        week_complete=_format_usage_completeness(
            session_stats.get("week_cost_complete")
        ),
    )


def run_usage_command(
    *,
    emit: Callable[[str], Any],
    flush: Callable[[], Any],
    router_stats_getter: Optional[Callable[[], Any]] = None,
    session_stats_getter: Optional[Callable[[], Any]] = None,
) -> None:
    """Emit the shared read-only usage report from usage snapshots."""
    try:
        if router_stats_getter is None:
            from utils.llm_router import llm

            router_stats_getter = llm.get_usage_stats
        if session_stats_getter is None:
            from utils.llm_usage_tracker import get_usage_stats

            session_stats_getter = get_usage_stats
        emit(format_usage_report(router_stats_getter(), session_stats_getter()))
    except Exception:
        emit("[skipTTS] Dungeon Master: [SYSTEM] Usage data unavailable.")
    flush()


@dataclass
class FastCommandIO:
    """Injected effects keep command tests provider-free."""

    emit: Callable[[str], None]
    flush: Callable[[], None]
    debug: Callable[..., None]
    warning: Callable[..., None]
    save_json: Callable[[str, Any], Any]
    persist_encounter: Callable[[str, Any], Any]


@dataclass
class DeterministicCommandIO:
    """Injected effects for commands that own local state or control flow."""

    emit: Callable[[str], None]
    flush: Callable[[], None]
    load_json: Callable[[str], Any]
    save_json: Callable[[str, Any], Any]
    write_json: Callable[[str, Any], Any]
    path_manager: Any
    normalize_name: Callable[[str], str]
    sync_active_encounter: Callable[..., Any]
    save_manager_factory: Callable[[], Any]
    summarize_dialogue: Callable[[list, Dict[str, Any], Dict[str, Any]], Any]
    generate_chat_history: Callable[[list, str], Any]


@dataclass(frozen=True)
class CharacterStatCommandIO:
    """Injected direct-file operations for the legacy /xp and /level commands."""

    load_json: Callable[[str], Any]
    normalize_name: Callable[[str], str]
    path_manager: Any
    write_json: Callable[[str, Any], Any]
    emit: Callable[[str], Any]
    flush: Callable[[], Any]


# TABLETOP MODE: Keep ally directives in Python's fast-command boundary.
def format_ally_command_feedback(status: str, actor_name: Optional[str] = None) -> str:
    """Render bounded, truthful /cmd feedback in the established DM voice."""
    safe_actor = "your ally"
    if isinstance(actor_name, str):
        candidate = " ".join(
            "".join(
                character
                if character.isprintable()
                else " " if character.isspace() else ""
                for character in actor_name
            ).split()
        )
        if candidate and len(candidate) <= 128:
            safe_actor = candidate

    if status == "accepted":
        return (
            f"Dungeon Master: I have recorded your request for {safe_actor}; "
            "the choice of action remains theirs."
        )
    if status == "replan_already_submitted":
        return (
            "Dungeon Master: That ally has already reconsidered the current "
            "orders; no further request was recorded."
        )
    if status == "prefetch_state_unavailable":
        return (
            "Dungeon Master: I could not verify the current ally-order "
            "re-plan state; no request was recorded."
        )
    if status == "unknown_ally":
        return (
            "Dungeon Master: No active ally by that name is present in this "
            "encounter; no request was recorded."
        )
    if status == "empty_directive":
        return "Dungeon Master: I need a non-empty instruction for that ally; no request was recorded."
    if status == "directive_too_long":
        return "Dungeon Master: Keep the instruction to 240 characters or fewer; no request was recorded."
    if status == "inactive_encounter":
        return "Dungeon Master: There is no matching active encounter, so no request was recorded."
    if status == "history_persist_failed":
        return "Dungeon Master: I could not secure that request in the campaign record; no request was recorded."
    return "Dungeon Master: Name an active ally and give a brief instruction; no request was recorded."


def _ally_command_controller_enabled() -> bool:
    """Reuse the ally rollout's strict default-off dependency gate."""
    try:
        from core.combat.enemy_batch_apply import is_ally_controller_enabled
    except ImportError:
        return False
    return is_ally_controller_enabled()


def _run_ally_directive_command(
    *,
    clean_input: str,
    encounter_data: Dict[str, Any],
    encounter_id: str,
    active_encounter_id: Optional[str],
    conversation_history: list,
    conversation_history_file: str,
    io: FastCommandIO,
    result: FastCommandResult,
) -> FastCommandResult:
    """Persist a private accepted directive without touching combat state."""
    from core.combat.ally_controller import (
        build_ally_directive_history_record,
        parse_ally_directive_command,
    )

    encounter_identity = None
    if isinstance(encounter_data, dict):
        encounter_identity = encounter_data.get(
            "encounterId", encounter_data.get("id")
        )
    parsed = None
    if (
        not isinstance(active_encounter_id, str)
        or not active_encounter_id.strip()
        or active_encounter_id != encounter_id
        or encounter_identity != encounter_id
    ):
        status = "inactive_encounter"
    else:
        parsed = parse_ally_directive_command(clean_input, encounter_data)
        status = parsed.status

    if status == "accepted":
        try:
            from core.combat.enemy_batch_apply import is_ally_prefetch_enabled

            prefetch_enabled = is_ally_prefetch_enabled()
            if not isinstance(prefetch_enabled, bool):
                raise ValueError("ally prefetch gate state is invalid")
            if prefetch_enabled:
                from core.combat.ally_prefetch import (
                    ally_prefetch_batch_id,
                    has_ally_prefetch_replan_submission,
                )

                round_number = encounter_data.get(
                    "combat_round", encounter_data.get("current_round", 1)
                ) if isinstance(encounter_data, dict) else None
                batch_id = ally_prefetch_batch_id(encounter_id, round_number)
                if batch_id is None:
                    status = "prefetch_state_unavailable"
                else:
                    replan_submitted = has_ally_prefetch_replan_submission(
                        encounter_id, batch_id
                    )
                    if not isinstance(replan_submitted, bool):
                        raise ValueError("ally re-plan cap state is invalid")
                    if replan_submitted:
                        status = "replan_already_submitted"
        except Exception:
            # An enabled prefetch cap that cannot be checked must not accept input.
            status = "prefetch_state_unavailable"

    if status == "accepted":
        try:
            if not isinstance(conversation_history, list):
                raise TypeError("conversation history must be a list")
            updated_history = list(conversation_history)
            updated_history.append(
                build_ally_directive_history_record(
                    parsed.actor_name,
                    parsed.directive,
                )
            )
            saved = io.save_json(conversation_history_file, updated_history)
            if saved is False:
                raise OSError("history write returned false")
        except Exception:
            try:
                io.warning(
                    "STATE_PERSIST: Failed to save private ally directive history",
                    category="combat_events",
                )
            except Exception:
                pass
            status = "history_persist_failed"
        else:
            conversation_history[:] = updated_history
            try:
                from utils import combat_latency_trace
                from core.combat.enemy_batch_apply import is_ally_controller_enabled

                if (combat_latency_trace.trace_enabled()
                        and is_ally_controller_enabled()):
                    creatures = encounter_data.get("creatures")
                    actor_ids = combat_latency_trace.build_run_local_actor_ids(creatures)
                    actor_key = (
                        "npc",
                        " ".join(parsed.actor_name.split()).casefold(),
                    )
                    actor_id = actor_ids.get(actor_key)
                    round_number = encounter_data.get(
                        "combat_round", encounter_data.get("current_round", 1)
                    )
                    batch_id = combat_latency_trace.build_work_unit_trace_context(
                        round_number, "ENEMY_PHASE", None
                    ).get("batch_id")
                    if (isinstance(actor_id, str) and isinstance(batch_id, str)
                            and isinstance(parsed.directive, str)):
                        directive_sha256 = hashlib.sha256(
                            parsed.directive.encode("utf-8")
                        ).hexdigest()
                        combat_latency_trace.trace_ally_directive_accepted(
                            batch_id, actor_id, directive_sha256
                        )
            except Exception:
                # Accepted command history is authoritative; evidence is optional.
                pass

    io.emit(format_ally_command_feedback(status, getattr(parsed, "actor_name", None)))
    io.flush()
    result.control_action = "continue"
    result.status = "accepted" if status == "accepted" else "rejected"
    result.reason = status
    return result


def run_character_stat_command(cmd: str, io: CharacterStatCommandIO) -> bool:
    """Handle the existing /xp and /level branches, including their output order."""
    if cmd.startswith("/xp"):
        try:
            parts = cmd.split()
            if len(parts) < 2:
                io.emit("Dungeon Master: [SYSTEM] Usage: /xp [amount]")
                io.flush()
                return True
            amount = int(parts[1])
            party_data = io.load_json("party_tracker.json")
            character_name = party_data.get("active_character") or party_data.get("partyMembers", [])[0]
            character_path = io.path_manager.get_character_path(io.normalize_name(character_name))
            character_data = io.load_json(character_path)
            if character_data:
                current_xp = character_data.get("experience_points", 0)
                new_xp = max(0, current_xp + amount)
                character_data["experience_points"] = new_xp
                io.write_json(character_path, character_data)
                io.emit(
                    f"Dungeon Master: [SYSTEM] {character_name} gained {amount} XP. "
                    f"Total: {current_xp} -> {new_xp}"
                )
                io.flush()
            else:
                io.emit(f"Dungeon Master: [SYSTEM] Error: Could not load data for {character_name}")
                io.flush()
        except ValueError:
            io.emit("Dungeon Master: [SYSTEM] Usage: /xp [amount] (must be a number)")
            io.flush()
        except Exception as exc:
            io.emit(f"Dungeon Master: [SYSTEM] Error updating XP: {exc}")
            io.flush()
        return True

    if cmd.startswith("/level"):
        try:
            parts = cmd.split()
            if len(parts) < 2:
                io.emit("Dungeon Master: [SYSTEM] Usage: /level [number]")
                io.flush()
                return True
            level = int(parts[1])
            party_data = io.load_json("party_tracker.json")
            character_name = party_data.get("active_character") or party_data.get("partyMembers", [])[0]
            character_path = io.path_manager.get_character_path(io.normalize_name(character_name))
            character_data = io.load_json(character_path)
            if character_data:
                current_level = character_data.get("level", 1)
                character_data["level"] = level
                io.write_json(character_path, character_data)
                io.emit(
                    f"Dungeon Master: [SYSTEM] {character_name} level set to {level} "
                    f"(was {current_level})"
                )
                io.flush()
            else:
                io.emit(f"Dungeon Master: [SYSTEM] Error: Could not load data for {character_name}")
                io.flush()
        except ValueError:
            io.emit("Dungeon Master: [SYSTEM] Usage: /level [number] (must be a number)")
            io.flush()
        except Exception as exc:
            io.emit(f"Dungeon Master: [SYSTEM] Error updating level: {exc}")
            io.flush()
        return True
    return False


def run_deterministic_command_stage(
    *,
    cmd: str,
    current_round: int,
    encounter_id: str,
    encounter_data: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    conversation_history: list,
    location_info: Dict[str, Any],
    player_file: str,
    io: DeterministicCommandIO,
) -> FastCommandResult:
    """Handle the remaining deterministic combat commands before the LLM path."""
    result = FastCommandResult()

    if cmd.startswith("/stats"):
        _handle_stats_command(io, result)
    elif cmd.startswith("/hp"):
        _handle_hp_command(cmd, io, result)
    elif cmd in ("/save", "\\save"):
        _handle_save_command(current_round, io, result)
    elif cmd in ("/quit", "\\quit", "/exit", "\\exit"):
        io.emit("[SYSTEM] Exiting game...")
        io.flush()
        result.control_action = "quit"
        result.status = "exit_requested"
        result.reason = "user_quit"
        result.exit_code = 0
        return result
    elif cmd in ("\\end_combat", "/end_combat", "exit combat"):
        result.control_action = "return"
        result.return_value = _handle_end_combat_command(
            encounter_id,
            encounter_data,
            party_tracker_data,
            conversation_history,
            location_info,
            player_file,
            io,
        )

    return result


def _handle_stats_command(io: DeterministicCommandIO, result: FastCommandResult) -> None:
    """Render the active character's combat stats."""
    try:
        pt_data = io.load_json("party_tracker.json")
        members = pt_data.get("partyMembers", [])
        char_name = pt_data.get("active_character") or (members[0] if members else "Player")
        char_path = io.path_manager.get_character_path(io.normalize_name(char_name))
        char_data = io.load_json(char_path)
        if char_data:
            abilities = char_data.get("abilities", {})
            stats_msg = f"Dungeon Master: [SYSTEM] Stats for {char_name}:\n"
            stats_msg += f"  Level: {char_data.get('level', 1)} | XP: {char_data.get('experience_points', 0)}\n"
            stats_msg += f"  HP: {char_data.get('hitPoints', 0)}/{char_data.get('maxHitPoints', 0)} | AC: {char_data.get('armorClass', 10)}\n"
            stats_msg += f"  Speed: {char_data.get('speed', 30)} | Init: {char_data.get('initiative', 0)}\n"
            stats_msg += f"  STR: {abilities.get('strength', 10)} | DEX: {abilities.get('dexterity', 10)} | CON: {abilities.get('constitution', 10)}\n"
            stats_msg += f"  INT: {abilities.get('intelligence', 10)} | WIS: {abilities.get('wisdom', 10)} | CHA: {abilities.get('charisma', 10)}\n"
            io.emit(stats_msg)
        else:
            io.emit(f"Dungeon Master: [SYSTEM] Error: Could not load data for {char_name}")
    except Exception as exc:
        io.emit(f"Dungeon Master: [SYSTEM] Error showing stats: {exc}")
    io.flush()
    result.control_action = "continue"


def _handle_hp_command(cmd: str, io: DeterministicCommandIO, result: FastCommandResult) -> None:
    """Apply the legacy bounded HP command and sync the encounter."""
    try:
        parts = cmd.split()
        if len(parts) < 2:
            io.emit("Dungeon Master: [SYSTEM] Usage: /hp [amount]")
            result.control_action = "continue"
            return
        amount = int(parts[1])
        pt_data = io.load_json("party_tracker.json")
        members = pt_data.get("partyMembers", [])
        char_name = pt_data.get("active_character") or (members[0] if members else "Player")
        char_path = io.path_manager.get_character_path(io.normalize_name(char_name))
        char_data = io.load_json(char_path)
        if char_data:
            current_hp = char_data.get("hitPoints", 0)
            max_hp = char_data.get("maxHitPoints", 0)
            new_hp = max(0, min(max_hp, current_hp + amount))
            char_data["hitPoints"] = new_hp
            io.write_json(char_path, char_data)
            action = "healed" if amount >= 0 else "damaged"
            io.emit(f"Dungeon Master: [SYSTEM] {char_name} {action} by {abs(amount)}. HP: {current_hp} -> {new_hp}/{max_hp}")
            io.flush()
            io.sync_active_encounter(force=True)
        else:
            io.emit(f"Dungeon Master: [SYSTEM] Error: Could not load data for {char_name}")
    except ValueError:
        io.emit("Dungeon Master: [SYSTEM] Usage: /hp [amount] (must be a number)")
    except Exception as exc:
        io.emit(f"Dungeon Master: [SYSTEM] Error updating HP: {exc}")
    io.flush()
    result.control_action = "continue"


def _handle_save_command(current_round: int, io: DeterministicCommandIO, result: FastCommandResult) -> None:
    """Create the legacy essential combat save."""
    try:
        manager = io.save_manager_factory()
        _, message = manager.create_save_game(f"Combat Save - Round {current_round}", "essential")
        io.emit(f"[SYSTEM] {message}")
    except Exception as exc:
        io.emit(f"[ERROR] Save failed: {exc}")
    io.flush()
    result.control_action = "continue"


def _handle_end_combat_command(
    encounter_id: str,
    encounter_data: Dict[str, Any],
    party_tracker_data: Dict[str, Any],
    conversation_history: list,
    location_info: Dict[str, Any],
    player_file: str,
    io: DeterministicCommandIO,
) -> Any:
    """Preserve the force-end summary, cleanup, and return contract."""
    # TABLETOP MODE: Keep the acknowledgement in DM voice; runtime detail belongs in logs.
    io.emit("Dungeon Master: You bring the combat to an end.")
    conversation_history.append({"role": "user", "content": "Dungeon Master Note: Combat has been forcefully ended by the user."})
    last_encounter_id = party_tracker_data.get("worldConditions", {}).get("activeCombatEncounter", "")
    dialogue_summary_result = io.summarize_dialogue(conversation_history, location_info, party_tracker_data)
    world_conditions = party_tracker_data.get("worldConditions", {})
    if "activeCombatEncounter" in world_conditions:
        if last_encounter_id:
            world_conditions["lastCompletedEncounter"] = last_encounter_id
        world_conditions["activeCombatEncounter"] = ""
        io.save_json("party_tracker.json", party_tracker_data)
    io.generate_chat_history(conversation_history, encounter_id)
    player_info = io.load_json(player_file)
    return dialogue_summary_result, player_info


def run_fast_commands_stage(
    *,
    cmd: str,
    clean_input: str,
    user_input_text: str,
    input_actor_name: Optional[str],
    multi_pc_manager: Any,
    encounter_data: Dict[str, Any],
    encounter_id: str,
    party_tracker_data: Dict[str, Any],
    active_encounter_id: Optional[str] = None,
    tactical_features: Any = None,
    conversation_history: list,
    conversation_history_file: str,
    io: FastCommandIO,
) -> FastCommandResult:
    """Run the existing tabletop fast-command branches without provider calls."""
    result = FastCommandResult("proceed", user_input_text, clean_input, input_actor_name)

    if is_usage_command_input(clean_input):
        run_usage_command(emit=io.emit, flush=io.flush)
        result.control_action = "continue"
        return result

    if cmd == "/switch_pc_focus":
        io.debug("SWITCH: Detected PC switch command, refreshing loop", category="combat_events")
        result.control_action = "continue"
        return result

    command_parts = clean_input.strip().split(None, 1)
    if (
        command_parts
        and command_parts[0].casefold() == "/cmd"
        and _ally_command_controller_enabled()
    ):
        return _run_ally_directive_command(
            clean_input=clean_input,
            encounter_data=encounter_data,
            encounter_id=encounter_id,
            active_encounter_id=active_encounter_id,
            conversation_history=conversation_history,
            conversation_history_file=conversation_history_file,
            io=io,
            result=result,
        )

    if multi_pc_manager and cmd in ["/end", "/pass", "end turn", "end"]:
        io.debug("TURN_END: Detected explicit force enemy phase command", category="combat_events")
        target_pc = input_actor_name or multi_pc_manager.current_pc_name or party_tracker_data.get("active_character")
        if target_pc:
            multi_pc_manager.set_current_pc(target_pc)
        multi_pc_manager.force_end_pc_phase()
        io.debug("TURN_END: Forcing enemy phase injection", category="combat_events")
        # TABLETOP MODE: Acknowledge the completed transition without exposing diagnostics.
        io.emit("Dungeon Master: Your turn is over; the combat moves on.")
        io.flush()
        pending_enemies = multi_pc_manager.get_remaining_enemies_for_round()
        pending_list_str = ", ".join(pending_enemies) if pending_enemies else "all remaining enemies/NPCs"
        system_msg = (
            "System: Player has manually ended the PC Phase. PROCEED TO ENEMY PHASE.\n"
            f"Turn Order: {pending_list_str}.\n"
            "INSTRUCTIONS: Generate actions for exactly these combatants in order. Once they have acted, STOP.\n"
            "If this ends the round, increment 'combat_round' in your JSON, but DO NOT narrate the start of the next round."
        )
        conversation_history.append({"role": "user", "content": system_msg})
        io.save_json(conversation_history_file, conversation_history)
        result.user_input_text = "Enemies turn."

    if multi_pc_manager:
        actor_for_log = input_actor_name if input_actor_name else (multi_pc_manager.current_pc_name or "Player")
        mechanical_feedback, spoken_narration, log_msg, skip_llm = multi_pc_manager.handle_combat_command(
            clean_input,
            encounter_data,
            actor_name=actor_for_log,
            active_encounter_id=active_encounter_id,
            tactical_features=tactical_features,
        )
        if mechanical_feedback:
            io.emit(mechanical_feedback)
            io.flush()
        if spoken_narration:
            io.emit(spoken_narration)
            io.flush()
        if log_msg:
            conversation_history.append({"role": "user", "content": log_msg})
            io.save_json(conversation_history_file, conversation_history)
            io.debug(f"[COMBAT_MANAGER] Injected system log: {log_msg}", category="combat_events")
            if encounter_id and encounter_data:
                if not io.persist_encounter(encounter_id, encounter_data):
                    io.warning("STATE_PERSIST: Failed to persist fast-lane encounter state", category="combat_events")
                else:
                    io.debug("STATE_PERSIST: Fast-lane encounter state persisted", category="combat_events")
        if skip_llm:
            result.control_action = "continue"
            return result

        if cmd in ["/help", "\\help"]:
            help_msg = (
                "[skipTTS] Dungeon Master: [SYSTEM] Available Combat Commands:\n"
                "  /stats      - View full character stats\n"
                "  /hp [val]   - Combat Heal (positive) or damage (negative)\n"
                "  /att [target] [roll] [weapon] - Attack a target\n"
                "  /dmg [val]  - Apply damage\n"
                "  /init [1-20] - Set PC group initiative roll\n"
                "  /end        - End PC combat turn\n"
                "  /end_combat - Force end the current combat encounter\n"
                "  /save       - Save current game state\n"
                "  /quit       - Exit the game\n"
                "  /help       - Show this help message\n"
                "[SYSTEM] Reference Guides:\n"
                "  - NEQ Quick Reference Guide: /static/docs/NEQ_Quick_Reference_Guide.pdf\n"
                "  - 5e Cheat Sheet: /static/docs/5E_Actions_Cheat_Sheet.pdf\n"
                "  - 5e Rules on a Page: /static/docs/5E_Rules_On_A_Page.pdf\n"
                "  - 5e Basic Rules: https://www.dndbeyond.com/sources/dnd/basic-rules-2014"
            )
            io.emit(help_msg)
            io.flush()
            result.control_action = "continue"

    return result
