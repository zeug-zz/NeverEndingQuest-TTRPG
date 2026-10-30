# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Combat Prompt Context - Provider-free state and prompt assembly.
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.combat.cover import cover_label, effective_ac_for_creature


def _extract_tracker_json_fence(tracker_text: str) -> Tuple[str, Optional[str]]:
    """Return tracker display text and the body of its first JSON fence."""
    json_start = tracker_text.find("```json")
    if json_start < 0:
        return tracker_text, None

    json_end = tracker_text.find("```", json_start + len("```json"))
    display_text = tracker_text[:json_start].strip()
    if json_end < 0:
        return display_text, None
    json_text = tracker_text[json_start + len("```json"):json_end].strip()
    return display_text, json_text


@dataclass(frozen=True)
class CombatPromptInputs:
    """Explicit text inputs used to assemble the current combat user prompt."""

    initiative_display: str
    dynamic_state: str
    armor_class_block: str
    multi_pc_context: str
    preroll_text: str
    player_action: str
    required_response: str


@dataclass(frozen=True)
class CombatPromptResult:
    """Explicit context-stage output for the existing owner-loop handoff."""

    return_early: bool = False
    return_value: Optional[Tuple[Any, Any]] = None
    encounter_data: Dict[str, Any] = field(default_factory=dict)
    player_info: Dict[str, Any] = field(default_factory=dict)
    player_file: Optional[str] = None
    path_manager: Any = None
    fresh_player_data: Optional[Dict[str, Any]] = None
    current_hp: Any = None
    max_hp: Any = None
    current_round: Any = None
    cached_round: Any = None
    preroll_text: str = ""
    live_tracker: Optional[str] = None
    turn_window_json: Optional[Dict[str, Any]] = None
    initiative_display: Optional[str] = None
    player_character_name: Optional[str] = None
    marked_initiative_display: Optional[str] = None
    current_turn_line: str = ""
    turn_window_text: str = ""
    dynamic_state: str = ""
    armor_class_block: str = ""
    armor_class_values: Dict[str, Any] = field(default_factory=dict)
    all_monsters_defeated: bool = False
    current_actor: Any = None
    required_response: Optional[str] = None
    multi_pc_context: str = ""
    user_input_text: str = ""
    user_prompt: Optional[str] = None


@dataclass(frozen=True)
class CombatContextInputs:
    """Explicit runtime state consumed by the post-decision context stage."""

    encounter_data: Dict[str, Any]
    multi_pc_manager: Any
    party_tracker_data: Dict[str, Any]
    player_info: Dict[str, Any]
    player_name_display: str
    current_hp: Any
    max_hp: Any
    pre_context_player_data: Optional[Dict[str, Any]]
    path_manager: Any
    json_file_path: str
    conversation_history: List[Dict[str, Any]]
    user_input_text: str
    logger_context: str = "combat_events"
    location_info: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class CombatContextDependencies:
    """Injected state, I/O, and lazy fallback seams used by prompt assembly."""

    normalize_character_name: Callable[[str], str]
    safe_json_load: Callable[[str], Optional[Dict[str, Any]]]
    load_npc_with_fuzzy_match: Callable[..., Tuple[Optional[Dict[str, Any]], Any]]
    collect_authoritative_combat_roster: Callable[..., List[Dict[str, Any]]]
    generate_prerolls: Callable[..., str]
    save_json_file: Callable[[str, Dict[str, Any]], Any]
    module_path_manager_factory: Callable[..., Any]
    file_exists: Callable[[str], bool]
    logger_debug: Callable[..., Any]
    logger_error: Callable[..., Any]
    emit: Callable[[str], Any]
    random_int: Callable[[int, int], int]
    fallback_initiative_tracker: Callable[..., Optional[str]]


@dataclass(frozen=True)
class InitialCombatStateInputs:
    """Authoritative startup state entering initial combat prompt assembly."""

    encounter_data: Dict[str, Any]
    player_info: Dict[str, Any]
    path_manager: Any
    multi_pc_manager: Any
    party_tracker_data: Dict[str, Any]
    json_file_path: str


@dataclass(frozen=True)
class InitialCombatStateDependencies:
    """Current owner data readers, formatter inputs, and preroll write callbacks."""

    normalize_character_name: Callable[[str], str]
    safe_json_load: Callable[[str], Any]
    load_npc_with_fuzzy_match: Callable[..., Tuple[Optional[Dict[str, Any]], Any]]
    collect_authoritative_combat_roster: Callable[..., List[Dict[str, Any]]]
    generate_prerolls: Callable[..., str]
    save_json: Callable[[str, Dict[str, Any]], Any]
    random_int: Callable[[int, int], int]
    debug: Callable[..., Any]
    error: Callable[..., Any]


@dataclass(frozen=True)
class InitialCombatStateResult:
    """Explicit initial HP, state text, and cached preroll handoff."""

    encounter_data: Dict[str, Any]
    player_info: Dict[str, Any]
    player_file: str
    fresh_player_data: Any
    current_hp: Any
    max_hp: Any
    player_name_display: str
    dynamic_state: str
    current_round: Any
    preroll_text: str


@dataclass(frozen=True)
class InventoryContextInputs:
    """Inputs for the pre-baseline inventory enrichment helper."""

    user_input_text: str
    player_name_display: str
    path_manager: Any
    normalize_character_name: Callable[[str], str]
    safe_json_load: Callable[[str], Optional[Dict[str, Any]]]
    enhance_player_input_with_inventory: Callable[..., str]
    party_tracker_data: Dict[str, Any]
    debug: Callable[..., Any]
    preexisting_player_data: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class InventoryContextResult:
    """Input enrichment output including the source read for error fallback."""

    user_input_text: str
    fresh_player_data: Optional[Dict[str, Any]]


def enhance_combat_input_with_inventory(inputs: InventoryContextInputs) -> InventoryContextResult:
    """Preserve the existing pre-context input enrichment semantics."""
    user_input_text = inputs.user_input_text
    fresh_player_data = inputs.preexisting_player_data
    try:
        player_file = inputs.path_manager.get_character_path(
            inputs.normalize_character_name(inputs.player_name_display)
        )
        fresh_player_data = inputs.safe_json_load(player_file)
        user_input_text = inputs.enhance_player_input_with_inventory(
            user_input_text,
            fresh_player_data,
            inputs.party_tracker_data,
            None,
            in_combat=True,
        )
        inputs.debug("COMBAT_LOOP: Enhanced player input with inventory context", category="combat_events")
    except Exception as exc:
        inputs.debug(
            f"COMBAT_LOOP: Failed to enhance input with inventory context: {exc}",
            category="combat_events",
        )
    return InventoryContextResult(user_input_text, fresh_player_data)


def prepare_initial_combat_state(
    inputs: InitialCombatStateInputs,
    dependencies: InitialCombatStateDependencies,
) -> InitialCombatStateResult:
    """Refresh initial HP/state, roster, and prerolls at the startup call point."""
    encounter_data = inputs.encounter_data
    player_info = inputs.player_info
    player_name_display = player_info["name"]
    player_file = inputs.path_manager.get_character_path(
        dependencies.normalize_character_name(player_name_display)
    )
    fresh_player_data = None
    try:
        fresh_player_data = dependencies.safe_json_load(player_file)
        if fresh_player_data:
            current_hp = fresh_player_data.get("hitPoints", 0)
            max_hp = fresh_player_data.get("maxHitPoints", 0)
            player_status = fresh_player_data.get("status", "alive")
            player_condition = fresh_player_data.get("condition", "none")
            player_conditions = fresh_player_data.get("condition_affected", [])
            player_info["spellcasting"] = fresh_player_data.get("spellcasting", {})
        else:
            current_hp = player_info.get("hitPoints", 0)
            max_hp = player_info.get("maxHitPoints", 0)
            player_status = player_info.get("status", "alive")
            player_condition = player_info.get("condition", "none")
            player_conditions = player_info.get("condition_affected", [])
    except Exception as exc:
        dependencies.error(
            "Failed to reload player data for initial CREATURE STATES",
            exception=exc,
            category="combat_events",
        )
        current_hp = player_info.get("hitPoints", 0)
        max_hp = player_info.get("maxHitPoints", 0)
        player_status = player_info.get("status", "alive")
        player_condition = player_info.get("condition", "none")
        player_conditions = player_info.get("condition_affected", [])

    state_line = f"{player_name_display}: HP {current_hp}/{max_hp}, {player_status}"
    if player_condition != "none":
        state_line += f", {player_condition}"
    if player_conditions:
        state_line += f", conditions: {','.join(player_conditions)}"
    spellcasting = player_info.get("spellcasting", {})
    slot_parts = []
    if spellcasting and "spellSlots" in spellcasting:
        spell_slots = spellcasting["spellSlots"]
        for level in range(1, 10):
            level_key = f"level{level}"
            if level_key in spell_slots:
                slot_data = spell_slots[level_key]
                current_slots = slot_data.get("current", 0)
                max_slots = slot_data.get("max", 0)
                if max_slots > 0:
                    slot_parts.append(f"L{level}:{current_slots}/{max_slots}")
    if slot_parts:
        state_line += f", Spell Slots: {' '.join(slot_parts)}"

    dynamic_state_parts = ["Active Player Characters (User Controlled):", f"  {state_line}"]
    dm_controlled_parts = []
    enemy_parts = []
    for creature in encounter_data["creatures"]:
        if creature["type"] == "player":
            continue
        creature_name = creature.get("name", "Unknown Creature")
        creature_hp = creature.get("currentHitPoints", "Unknown")
        creature_status = creature.get("status", "alive")
        creature_condition = creature.get("condition", "none")
        if creature["type"] == "npc":
            npc_data, _ = dependencies.load_npc_with_fuzzy_match(creature_name, inputs.path_manager)
            if npc_data:
                creature_max_hp = npc_data["maxHitPoints"]
            else:
                dependencies.error(
                    f"FAILURE: Failed to get correct max HP for {creature_name}",
                    category="combat_events",
                )
                creature_max_hp = creature.get("maxHitPoints", "Unknown")
        else:
            creature_max_hp = creature.get("maxHitPoints", "Unknown")
        creature_line = f"{creature_name}: HP {creature_hp}/{creature_max_hp}, {creature_status}"
        if creature_condition != "none":
            creature_line += f", {creature_condition}"
        if creature["type"] == "npc":
            dm_controlled_parts.append(creature_line)
        elif creature["type"] == "enemy":
            enemy_parts.append(creature_line)
        else:
            dm_controlled_parts.append(creature_line)

    if dm_controlled_parts:
        dynamic_state_parts.append("Accompanied by Party NPCs (DM Controlled):")
        dynamic_state_parts.extend([f"  {part}" for part in dm_controlled_parts])
    if enemy_parts:
        dynamic_state_parts.append("Enemies (DM Controlled):")
        dynamic_state_parts.extend([f"  {part}" for part in enemy_parts])
    dynamic_state = "\n".join(dynamic_state_parts)

    roster_entries = dependencies.collect_authoritative_combat_roster(
        encounter_data,
        multi_pc_manager=inputs.multi_pc_manager,
        party_tracker_data=inputs.party_tracker_data,
    )
    roster_list = [f"- {entry['name']} ({entry['type']})" for entry in roster_entries]
    roster_str = "\n".join(roster_list) if roster_list else "- None"
    dynamic_state += (
        f"\n\n++ VALID TARGETS & ACTORS (IMMUTABLE) ++\n{roster_str}\n"
        "RULES: This is the definitive list of all beings in the scene. "
        "Do NOT narrate actions for anyone not on this list. "
        "During ENEMY_PHASE, PCs remain forbidden as actors but are valid targets."
    )

    current_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    preroll_text = dependencies.generate_prerolls(encounter_data, round_num=current_round)
    encounter_data["preroll_cache"] = {
        "round": current_round,
        "rolls": preroll_text,
        "preroll_id": f"{current_round}-{dependencies.random_int(1000, 9999)}",
    }
    dependencies.save_json(inputs.json_file_path, encounter_data)
    dependencies.debug(f"STATE_CHANGE: Saved prerolls for round {current_round}", category="combat_events")
    return InitialCombatStateResult(
        encounter_data=encounter_data,
        player_info=player_info,
        player_file=player_file,
        fresh_player_data=fresh_player_data,
        current_hp=current_hp,
        max_hp=max_hp,
        player_name_display=player_name_display,
        dynamic_state=dynamic_state,
        current_round=current_round,
        preroll_text=preroll_text,
    )


def check_all_monsters_defeated(encounter: Optional[Dict[str, Any]]) -> bool:
    """Retain the combat-loop enemy-defeat predicate at its package owner."""
    if not encounter or "creatures" not in encounter:
        return False
    has_enemies = False
    all_defeated = True
    for creature in encounter["creatures"]:
        if creature.get("type") == "enemy":
            has_enemies = True
            current_hp = creature.get("currentHitPoints", 0)
            status = creature.get("status", "alive").lower()
            if current_hp > 0 and status not in ("dead", "defeated", "unconscious"):
                all_defeated = False
                break
    return has_enemies and all_defeated


def assemble_combat_context(
    inputs: CombatContextInputs,
    dependencies: CombatContextDependencies,
) -> CombatPromptResult:
    """Run the post-decision context/prompt stage using explicit dependencies.

    The state read order, fresh-file fallbacks, initiative tracker selection,
    preroll cache mutation/write intent, AC lookup, response-selection logic,
    and serialized user-prompt template mirror the former loop block.
    """
    encounter_data = inputs.encounter_data
    player_info = inputs.player_info
    player_name_display = inputs.player_name_display
    path_manager = inputs.path_manager
    multi_pc_manager = inputs.multi_pc_manager
    party_tracker_data = inputs.party_tracker_data
    user_input_text = inputs.user_input_text
    dynamic_state_parts = []
    user_controlled_parts = []
    dm_controlled_parts = []
    enemy_parts = []

    player_file = path_manager.get_character_path(
        dependencies.normalize_character_name(player_name_display)
    )
    fresh_player_data = inputs.pre_context_player_data
    current_hp = inputs.current_hp
    max_hp = inputs.max_hp
    player_status = "alive"
    player_condition = "none"
    player_conditions = []
    try:
        fresh_player_data = dependencies.safe_json_load(player_file)
        if fresh_player_data:
            current_hp = fresh_player_data.get("hitPoints", 0)
            max_hp = fresh_player_data.get("maxHitPoints", 0)
            player_status = fresh_player_data.get("status", "alive")
            player_condition = fresh_player_data.get("condition", "none")
            player_conditions = fresh_player_data.get("condition_affected", [])
            player_info["spellcasting"] = fresh_player_data.get("spellcasting", {})
        else:
            player_status = player_info.get("status", "alive")
            player_condition = player_info.get("condition", "none")
            player_conditions = player_info.get("condition_affected", [])
    except Exception as exc:
        dependencies.logger_error(
            "Failed to reload player data for CREATURE STATES",
            exception=exc,
            category="combat_events",
        )
        player_status = player_info.get("status", "alive")
        player_condition = player_info.get("condition", "none")
        player_conditions = player_info.get("condition_affected", [])

    class_features_names = []
    if fresh_player_data:
        class_features = fresh_player_data.get("classFeatures", [])
        class_features_names = [feature.get("name", "") for feature in class_features if feature.get("name")]

    state_line = f"{player_name_display}: HP {current_hp}/{max_hp}, {player_status}"
    if class_features_names:
        state_line += f", Class Features: {', '.join(class_features_names)}"
    if player_condition != "none":
        state_line += f", {player_condition}"
    if player_conditions:
        state_line += f", conditions: {','.join(player_conditions)}"

    spellcasting = player_info.get("spellcasting", {})
    if spellcasting and "spellSlots" in spellcasting:
        spell_slots = spellcasting["spellSlots"]
        slot_parts = []
        for level in range(1, 10):
            level_key = f"level{level}"
            if level_key in spell_slots:
                slot_data = spell_slots[level_key]
                current_slots = slot_data.get("current", 0)
                max_slots = slot_data.get("max", 0)
                if max_slots > 0:
                    slot_parts.append(f"L{level}:{current_slots}/{max_slots}")
        if slot_parts:
            state_line += f", Spell Slots: {' '.join(slot_parts)}"
    user_controlled_parts.append(state_line)

    for creature in encounter_data["creatures"]:
        if creature["type"] == "player":
            continue
        creature_name = creature.get("name", "Unknown Creature")
        creature_hp = creature.get("currentHitPoints", "Unknown")
        creature_status = creature.get("status", "alive")
        creature_condition = creature.get("condition", "none")
        npc_data = None
        if creature["type"] == "npc":
            npc_data, matched_filename = dependencies.load_npc_with_fuzzy_match(creature_name, path_manager)
            if npc_data:
                creature_max_hp = npc_data["maxHitPoints"]
            else:
                dependencies.logger_error(
                    f"FAILURE: Failed to get correct max HP for {creature_name}",
                    category="combat_events",
                )
                creature_max_hp = creature.get("maxHitPoints", "Unknown")
        else:
            creature_max_hp = creature.get("maxHitPoints", "Unknown")
        creature_line = f"{creature_name}: HP {creature_hp}/{creature_max_hp}, {creature_status}"
        if creature["type"] == "npc" and npc_data:
            npc_class_features = npc_data.get("classFeatures", [])
            if npc_class_features:
                npc_features_names = [feature.get("name", "") for feature in npc_class_features if feature.get("name")]
                if npc_features_names:
                    creature_line += f", Class Features: {', '.join(npc_features_names)}"
        if creature_condition != "none":
            creature_line += f", {creature_condition}"
        if creature["type"] == "npc" and npc_data:
            npc_spellcasting = npc_data.get("spellcasting", {})
            if npc_spellcasting and "spellSlots" in npc_spellcasting:
                npc_spell_slots = npc_spellcasting["spellSlots"]
                npc_slot_parts = []
                for level in range(1, 10):
                    level_key = f"level{level}"
                    if level_key in npc_spell_slots:
                        slot_data = npc_spell_slots[level_key]
                        current_slots = slot_data.get("current", 0)
                        max_slots = slot_data.get("max", 0)
                        if max_slots > 0:
                            npc_slot_parts.append(f"L{level}:{current_slots}/{max_slots}")
                if npc_slot_parts:
                    creature_line += f", Spell Slots: {' '.join(npc_slot_parts)}"
        if creature["type"] == "npc":
            dm_controlled_parts.append(creature_line)
        elif creature["type"] == "enemy":
            enemy_parts.append(creature_line)
        else:
            dm_controlled_parts.append(creature_line)

    roster_entries = dependencies.collect_authoritative_combat_roster(
        encounter_data,
        multi_pc_manager=multi_pc_manager,
        party_tracker_data=party_tracker_data,
    )
    dynamic_state = build_dynamic_state(
        user_controlled=user_controlled_parts,
        dm_controlled=dm_controlled_parts,
        enemies=enemy_parts,
        roster=[(entry["name"], entry["type"]) for entry in roster_entries],
    )

    current_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    cached_round = encounter_data.get("preroll_cache", {}).get("round", 0)
    if current_round > cached_round:
        preroll_text = dependencies.generate_prerolls(encounter_data, round_num=current_round)
        encounter_data["preroll_cache"] = {
            "round": current_round,
            "rolls": preroll_text,
            "preroll_id": f"{current_round}-{dependencies.random_int(1000, 9999)}",
        }
        dependencies.save_json_file(inputs.json_file_path, encounter_data)
        dependencies.logger_debug(
            f"STATE_CHANGE: Generated new prerolls for round {current_round}",
            category="combat_events",
        )
    else:
        preroll_text = encounter_data.get("preroll_cache", {}).get("rolls", "")
        if preroll_text:
            preroll_id = encounter_data.get("preroll_cache", {}).get("preroll_id", "unknown")
            dependencies.logger_debug(
                f"STATE_CHANGE: Reusing cached prerolls for round {current_round} (ID: {preroll_id})",
                category="combat_events",
            )
        else:
            preroll_text = dependencies.generate_prerolls(encounter_data, round_num=current_round)
            encounter_data["preroll_cache"] = {
                "round": current_round,
                "rolls": preroll_text,
                "preroll_id": f"{current_round}-{dependencies.random_int(1000, 9999)}",
            }
            dependencies.save_json_file(inputs.json_file_path, encounter_data)
            dependencies.logger_debug(
                f"STATE_CHANGE: Generated fallback prerolls for round {current_round}",
                category="combat_events",
            )

    live_tracker = None
    turn_window_json = None
    initiative_display = None
    if multi_pc_manager:
        dependencies.logger_debug("MULTI_PC_TRACKER: Using deterministic multi-PC initiative tracker", category="combat_events")
        try:
            live_tracker = multi_pc_manager.format_initiative_tracker(encounter_data)
            if live_tracker:
                dependencies.logger_debug("MULTI_PC_TRACKER: Successfully generated initiative tracker", category="combat_events")
                initiative_display, json_str = _extract_tracker_json_fence(live_tracker)
                if json_str is not None:
                    try:
                        turn_window_json = json.loads(json_str)
                        dependencies.logger_debug(
                            f"MULTI_PC_TRACKER: Extracted turn window: {turn_window_json.get('turn_window', [])}",
                            category="combat_events",
                        )
                    except json.JSONDecodeError as exc:
                        dependencies.logger_debug(f"MULTI_PC_TRACKER: Failed to parse JSON metadata: {exc}", category="combat_events")
        except Exception as exc:
            dependencies.logger_debug(f"MULTI_PC_TRACKER: Failed to generate tracker: {exc}", category="combat_events")

    if not live_tracker:
        try:
            recent_conversation = inputs.conversation_history[-6:] if len(inputs.conversation_history) > 6 else inputs.conversation_history
            live_tracker = dependencies.fallback_initiative_tracker(encounter_data, recent_conversation, current_round)
            if live_tracker:
                dependencies.logger_debug("AI_TRACKER: Successfully generated live initiative tracker", category="combat_events")
                initiative_display, json_str = _extract_tracker_json_fence(live_tracker)
                if json_str is not None:
                    try:
                        turn_window_json = json.loads(json_str)
                        dependencies.logger_debug(
                            f"AI_TRACKER: Extracted turn window: {turn_window_json.get('turn_window', [])}",
                            category="combat_events",
                        )
                    except json.JSONDecodeError as exc:
                        dependencies.logger_debug(f"AI_TRACKER: Failed to parse JSON metadata: {exc}", category="combat_events")
        except Exception as exc:
            from utils.llm_router import GameLLMTerminalError
            if isinstance(exc, GameLLMTerminalError):
                raise
            dependencies.logger_debug(f"AI_TRACKER: Failed to generate live tracker: {exc}", category="combat_events")

    if not live_tracker:
        dependencies.logger_error(
            "INITIATIVE_TRACKER: Failed to generate initiative tracker - combat cannot proceed properly",
            category="combat_events",
        )
        return CombatPromptResult(
            return_early=True,
            return_value=(None, None),
            encounter_data=encounter_data,
            player_info=player_info,
            player_file=player_file,
            path_manager=path_manager,
            current_hp=current_hp,
            max_hp=max_hp,
            current_round=current_round,
            cached_round=cached_round,
            preroll_text=preroll_text,
            dynamic_state=dynamic_state,
            user_input_text=user_input_text,
        )

    player_character_name = None
    if turn_window_json and "player_name" in turn_window_json:
        player_character_name = turn_window_json["player_name"]
    else:
        for creature in encounter_data["creatures"]:
            if creature["type"] == "player":
                player_character_name = creature["name"]
                break

    marked_initiative_display = initiative_display
    current_turn_marker = "[>]"
    current_turn_line = ""
    if current_turn_marker in marked_initiative_display:
        for line in marked_initiative_display.split("\n"):
            if current_turn_marker in line:
                current_turn_line = line.strip()
                break
    turn_window_text = ""
    if turn_window_json:
        turn_window_text = f"""
 --- TURN WINDOW ---
 process_until: {turn_window_json.get('process_until', 'unknown')}
 turn_window: {json.dumps(turn_window_json.get('turn_window', []))}
 """

    ac_block = ""
    ac_values = {}
    for creature in encounter_data.get("creatures", []):
        name = creature.get("name")
        ac = creature.get("armorClass")
        if name and ac is not None:
            ac_values[name] = ac
        elif name and creature.get("type") == "enemy":
            monster_type = creature.get("monsterType", "").lower()
            if monster_type:
                try:
                    path_manager = dependencies.module_path_manager_factory(
                        party_tracker_data.get("module", "").replace(" ", "_")
                    )
                    monster_file = path_manager.get_monster_path(monster_type)
                    if dependencies.file_exists(monster_file):
                        monster_data = dependencies.safe_json_load(monster_file)
                        if monster_data and "armorClass" in monster_data:
                            ac_values[name] = monster_data["armorClass"]
                except Exception as exc:
                    dependencies.logger_debug(
                        f"COMBAT_PROMPT: Failed to load AC for {name}: {exc}",
                        category="combat_events",
                    )
    if ac_values:
        ac_block = "=== ARMOR CLASS (AC) ===\n"
        world_conditions = party_tracker_data.get("worldConditions", {})
        if not isinstance(world_conditions, Mapping):
            world_conditions = {}
        active_encounter_id = world_conditions.get("activeCombatEncounter")
        encounter_id = encounter_data.get("encounterId", encounter_data.get("id"))
        combat_in_progress = (
            isinstance(active_encounter_id, str)
            and bool(active_encounter_id.strip())
            and active_encounter_id.strip() == encounter_id
        )
        tactical_features = (
            inputs.location_info.get("tacticalFeatures")
            if isinstance(inputs.location_info, Mapping) else None
        )
        sorted_creatures = sorted(
            encounter_data.get("creatures", []),
            key=lambda creature: creature.get("initiative", 0),
            reverse=True,
        )
        for creature in sorted_creatures:
            name = creature.get("name")
            if name in ac_values:
                base_ac = ac_values[name]
                effective = effective_ac_for_creature(
                    base_ac,
                    creature,
                    encounter_id=encounter_id,
                    active_encounter_id=active_encounter_id,
                    combat_in_progress=combat_in_progress,
                    tactical_features=tactical_features,
                )
                label = cover_label(creature.get("coverType"))
                if effective != base_ac and label:
                    ac_block += (
                        f"{name}: {effective} (effective AC; base {base_ac}, {label})\n"
                    )
                else:
                    ac_block += f"{name}: {base_ac}\n"
        ac_block += "\n"

    all_monsters_defeated = check_all_monsters_defeated(encounter_data)
    current_actor = None
    if all_monsters_defeated:
        dependencies.logger_debug("COMBAT_AUTO_EXIT: All monsters defeated, modifying required response", category="combat_events")
        dependencies.emit("[COMBAT_MANAGER] Auto-detecting combat end: All enemies defeated")
        required_response = """--- REQUIRED RESPONSE ---
 All monsters have been defeated. Pass the exit action to end combat:
 1. Return structured JSON with plan, narration, combat_round, and actions
 2. Include exit action with encounterId and reason: 'All enemies defeated'"""
    elif multi_pc_manager:
        current_actor = multi_pc_manager.get_current_actor()
        required_response = multi_pc_manager.get_required_response_prompt()
        dependencies.logger_debug(
            f"PROMPT_LOGIC: Generated Multi-PC response requirement for {current_actor.name if current_actor else 'Unknown'}",
            category="combat_events",
        )
    else:
        required_response = """--- REQUIRED RESPONSE ---
 1. Narrate and resolve actions for all NPCs/monsters in initiative order until:
    - The LAST creature in this round has acted, OR
    - Initiative returns to the player
 2. Stop narration at that point
 3. Return structured JSON with plan, narration, combat_round, and actions"""

    multi_pc_context = ""
    if multi_pc_manager:
        active_pc = multi_pc_manager.current_pc_name
        initiative_mode = encounter_data.get("initiativeMode", "two_group_phase1")
        initiative_rolls = encounter_data.get("initiativeRolls", {})
        dm_group_roll = initiative_rolls.get("dmGroup", "pending")
        pc_group_roll = initiative_rolls.get("pcGroup", "pending")
        initiative_winner = encounter_data.get("initiativeWinner", "pending")
        round_starts_with = encounter_data.get("roundStartsWith", initiative_winner)
        current_phase = multi_pc_manager.combat_phase
        pending_enemies = multi_pc_manager.get_remaining_enemies_for_round()
        pending_str = ", ".join(pending_enemies) if pending_enemies else "None"
        multi_pc_context = f"""
 === INITIATIVE STATE ===
 MODE: {initiative_mode}
 DM_GROUP_ROLL: {dm_group_roll}
 PC_GROUP_ROLL: {pc_group_roll}
 WINNER: {initiative_winner}
 ROUND_STARTS_WITH: {round_starts_with}

 === COMBAT PHASE STATE ===
 CURRENT_PHASE: {current_phase}
 PC_PHASE_COMPLETE: {multi_pc_manager.pc_phase_complete}
 PENDING_ENEMIES: [{pending_str}]
 DETERMINISM: In {current_phase}, ONLY the specified actors have authority to act.

 --- MULTI-PC COMBAT STATUS ---
 {multi_pc_manager.format_party_turn_summary()}

 {multi_pc_manager.format_pc_context_for_prompt(active_pc)}
 """

    prompt_result = assemble_combat_prompt(
        CombatPromptInputs(
            initiative_display=marked_initiative_display,
            dynamic_state=dynamic_state,
            armor_class_block=ac_block,
            multi_pc_context=multi_pc_context,
            preroll_text=preroll_text,
            player_action=user_input_text,
            required_response=required_response,
        )
    )
    return CombatPromptResult(
        return_early=False,
        encounter_data=encounter_data,
        player_info=player_info,
        player_file=player_file,
        path_manager=path_manager,
        fresh_player_data=fresh_player_data,
        current_hp=current_hp,
        max_hp=max_hp,
        current_round=current_round,
        cached_round=cached_round,
        preroll_text=preroll_text,
        live_tracker=live_tracker,
        turn_window_json=turn_window_json,
        initiative_display=initiative_display,
        player_character_name=player_character_name,
        marked_initiative_display=marked_initiative_display,
        current_turn_line=current_turn_line,
        turn_window_text=turn_window_text,
        dynamic_state=dynamic_state,
        armor_class_block=ac_block,
        armor_class_values=ac_values,
        all_monsters_defeated=all_monsters_defeated,
        current_actor=current_actor,
        required_response=required_response,
        multi_pc_context=multi_pc_context,
        user_input_text=user_input_text,
        user_prompt=prompt_result.user_prompt,
    )


def build_dynamic_state(
    *,
    user_controlled: Sequence[str],
    dm_controlled: Sequence[str],
    enemies: Sequence[str],
    roster: Sequence[tuple[str, str]],
) -> str:
    """Render the established dynamic state and authoritative roster blocks."""
    parts = []
    if user_controlled:
        parts.append("Active Player Characters (User Controlled):")
        parts.extend(f"  {line}" for line in user_controlled)
    if dm_controlled:
        parts.append("Accompanied by Party NPCs (DM Controlled):")
        parts.extend(f"  {line}" for line in dm_controlled)
    if enemies:
        parts.append("Enemies (DM Controlled):")
        parts.extend(f"  {line}" for line in enemies)

    dynamic_state = "\n".join(parts)
    roster_text = "\n".join(f"- {name} ({kind})" for name, kind in roster) or "- None"
    return (
        f"{dynamic_state}\n\n++ VALID TARGETS & ACTORS (IMMUTABLE) ++\n{roster_text}\n"
        "RULES: This is the definitive list of all beings in the scene. "
        "Do NOT narrate actions for anyone not on this list. "
        f"During ENEMY_PHASE, PCs remain forbidden as actors but are valid targets."
    )


def assemble_combat_prompt(inputs: CombatPromptInputs) -> CombatPromptResult:
    """Assemble prompt bytes with the legacy ordering and whitespace unchanged."""
    prompt = f"""{inputs.initiative_display}

 --- CREATURE STATES ---
 {inputs.dynamic_state}

 {inputs.armor_class_block}
 {inputs.multi_pc_context}
 --- DICE POOLS ---
 Rules:
 - Player characters always roll their own dice
 - NPCs/monsters use pre-rolled dice pools exactly
 - Do not reuse dice; consume in order
 - For NPC/Monster ATTACK: use CREATURE ATTACKS list
 - For NPC/Monster SAVES: use SAVING THROWS list\x20\x20
 - For damage/spells/other: use GENERIC DICE pool

 {inputs.preroll_text}

 --- RULES ---
 - Initiative must be followed strictly
 - Only increment combat_round after all alive creatures have acted
 - Status updates must be reflected in JSON "actions"
 - Do not narrate beyond current round

 --- PLAYER ACTION ---
 {inputs.player_action}

 {inputs.required_response}"""
    return CombatPromptResult(dynamic_state=inputs.dynamic_state, user_prompt=prompt)
