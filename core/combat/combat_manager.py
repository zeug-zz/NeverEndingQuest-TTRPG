# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Core Engine - Combat Manager
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

# ============================================================================
# COMBAT_MANAGER.PY - TURN-BASED COMBAT SYSTEM
# TABLETOP MODE: Implementation owner moved to core/combat in decomposition task 1.1.
# ============================================================================
#
# ARCHITECTURE ROLE: Game Systems Layer - Combat Management
#
# This module provides comprehensive turn-based combat management for the 5th edition
# Dungeon Master system, implementing AI-driven combat encounters with full rule
# compliance and intelligent resource tracking.
#
# KEY RESPONSIBILITIES:
# - Turn-based combat orchestration with initiative order management
# - AI-powered combat decision making for NPCs and monsters
# - Combat state validation and rule compliance verification
# - Experience point calculation and reward distribution
# - Combat logging and debugging support with per-encounter directories
# - Real-time combat status display and resource tracking
# - Preroll dice caching system to prevent AI manipulation
#

"""
Combat Manager Module for NeverEndingQuest

Handles combat encounters between players, NPCs, and monsters.

Features:
- Manages turn-based combat with initiative order
- Processes player actions and AI responses
- Generates combat summaries and experience rewards
- Maintains combat logs for debugging and analysis
- Round-based preroll caching to ensure dice consistency
- Real-time combat state display with dynamic resource tracking

Combat Logging System:
- Creates per-encounter logs in the combat_logs/{encounter_id}/ directory
- Generates both timestamped and "latest" versions of each log
- Maintains a combined log of all encounters in all_combat_latest.json
- Filters out system messages for cleaner, more readable logs

"""
# ============================================================================
# COMBAT_MANAGER.PY - GAME SYSTEMS LAYER - COMBAT
# ============================================================================
#
# ARCHITECTURE ROLE: Game Systems Layer - Turn-Based Combat Management
#
# This module implements 5e combat mechanics using AI-driven simulation
# with strict rule validation. It demonstrates our multi-model AI strategy
# by using specialized models for combat-specific interactions.
#
# KEY RESPONSIBILITIES:
# - Manage turn-based combat encounters with initiative tracking
# - Validate combat actions against 5e rules
# - Coordinate HP tracking, status effects, and combat state
# - Generate and manage pre-rolled dice to prevent AI confusion
# - Cache prerolls per combat round to ensure consistency
# - Track combat rounds through AI responses
# - Provide specialized combat AI prompts and validation
# - Real-time dynamic state display for combat awareness
#
# COMBAT STATE DISPLAY PHILOSOPHY:
# - REAL-TIME AWARENESS: Shows current HP, spell slots, conditions during combat
# - RESOURCE TRACKING: Displays available spell slots for tactical decisions
# - DYNAMIC UPDATES: Reflects changes immediately as they occur
# - AI CLARITY: Provides authoritative current state to prevent confusion
#
# COMBAT INFORMATION ARCHITECTURE:
# - DYNAMIC STATE DISPLAY: Current HP, spell slots, active conditions
# - STATIC REFERENCE: Character abilities remain in system messages
# - SEPARATION PRINCIPLE: Combat state vs character capabilities
# - TACTICAL FOCUS: Information relevant to immediate combat decisions
#
# COMBAT FLOW:
# Encounter Start -> Initiative Roll -> Turn Management -> Action Resolution ->
# Validation -> State Update -> Dynamic State Display -> Win/Loss Conditions
#
# AI INTEGRATION:
# - Specialized combat model for turn-based interactions
# - Pre-rolled dice system prevents AI attack count confusion
# - Combat-specific validation model for rule compliance
# - Real-time HP and status tracking with state synchronization
# - Dynamic spell slot tracking for spellcaster resource management
#
# ARCHITECTURAL INTEGRATION:
# - Called by action_handler.py for combat-related actions
# - Uses generate_prerolls.py for dice management
# - Integrates with party_tracker.json for state persistence
# - Implements our "Defense in Depth" validation strategy
#
# DESIGN PATTERNS:
# - State Machine: Combat phases and turn management
# - Strategy Pattern: Different AI models for different combat aspects
# - Observer Pattern: Real-time combat state updates
#
# This module exemplifies our approach to complex game system management
# while maintaining strict 5e rule compliance through AI validation.
# ============================================================================

import copy
import json
import math
import os
import sys
import time
import re
import random
import subprocess
import threading
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

# Add project root to sys.path for direct execution
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model_config import (
    USE_COMPRESSED_COMBAT,
    COMPRESSION_ENABLED,
    VALIDATION_COMPRESSION_MIN_CHARS,
    COMBAT_PC_PHASE_NL_FAST_PATH,
)
from datetime import datetime
from utils.xp import main as calculate_xp
from utils.ai_client_factory import create_chat_client, get_chat_completion_params
from utils.llm_router import GameLLMTerminalError, llm
from utils.llm_runtime import make_legacy_receipt_observer

# Import OpenAI usage tracking (safe - won't break if fails)
try:
    from utils.openai_usage_tracker import track_response, get_usage_stats
    USAGE_TRACKING_AVAILABLE = True
    print("[COMBAT_MANAGER] OpenAI usage tracking enabled")
except Exception as e:
    USAGE_TRACKING_AVAILABLE = False
    print(f"[COMBAT_MANAGER] OpenAI usage tracking not available: {e}")
    def track_response(r): pass
    def get_usage_stats(): return {}
# Import model configurations from config.py
from config import (
    COMBAT_MAIN_MODEL,
    # Use the existing validation model instead of COMBAT_VALIDATION_MODEL
    DM_VALIDATION_MODEL,
    COMBAT_DIALOGUE_SUMMARY_MODEL,
    DM_MINI_MODEL
)
from updates.update_character_info import update_character_info, normalize_character_name
from utils.pc_manager import commit_active_character
from utils.character_state_hygiene import normalize_life_state_fields, get_supernatural_state_summary
import updates.update_encounter as update_encounter
import updates.update_party_tracker as update_party_tracker
# Import the preroll generator
from core.generators.generate_prerolls import generate_prerolls
# Import safe JSON functions
from utils.encoding_utils import safe_json_load
from utils.file_operations import safe_write_json
from utils.combat_latency_trace import (
    trace_file_operation,
    trace_provider_call,
    trace_stage,
    trace_decision,
    trace_combat_observation,
    trace_enabled,
    set_trace_context,
)
import core.ai.cumulative_summary as cumulative_summary
from utils.enhanced_logger import debug, info, warning, error, game_event, set_script_name
from utils.save_roll_contract import calculate_concentration_dc
from utils.combat_phase_integrity_precheck import (
    validate_already_applied_enemy_replay_precheck,
    validate_combat_phase_integrity_precheck,
)
from utils.combat_narration_consistency_precheck import (
    validate_combat_narration_consistency_precheck,
    validate_update_encounter_enemy_boundary_precheck,
)
from core.combat.session import CombatSession
from core.combat.bootstrap import (
    CombatInitializationDependencies,
    CombatInitializationInputs,
    CombatHistoryDependencies,
    CombatStartupNarrativeDependencies,
    CombatStartupNarrativeInputs,
    build_fresh_combat_history,
    hydrate_fresh_combat_history,
    initialize_combat_session,
    refresh_resumed_combat_history,
    run_startup_narrative,
    select_combat_history,
)
from core.combat.validation import CombatValidationDependencies
from core.combat.prompts import (
    CombatContextDependencies,
    CombatContextInputs,
    InitialCombatStateDependencies,
    InitialCombatStateInputs,
    InventoryContextInputs,
    assemble_combat_context,
    check_all_monsters_defeated,
    enhance_combat_input_with_inventory,
    prepare_initial_combat_state,
)
from core.combat.turn import (
    CombatActionTraceDependencies,
    CombatActionTraceInputs,
    CombatNormalTurnDependencies,
    CombatNormalTurnInputs,
    CombatTurnIterationDependencies,
    CombatTurnIterationInputs,
    CombatRetryDependencies,
    CombatRetryInputs,
    PhaseGateIO,
    RoundTransitionDependencies,
    begin_combat_turn_iteration,
    prepare_combat_normal_turn,
    capture_pre_round_transition_combat_context,
    handle_group_initiative_gate,
    run_input_phase_gate,
    should_consider_ally_prefetch_replan,
    should_consider_tactical_prefetch_replan,
    run_combat_provider_retry_stage,
    stage_combat_turn_snapshot,
    sync_committed_combat_turn,
    trace_combat_action_batch_metadata,
)
from core.combat.persistence import (
    CombatFinalizationDependencies,
    CombatFinalizationInputs,
    CharacterUpdateDependencies,
    CombatActionDependencies,
    apply_final_character_updates,
    finalize_combat_session,
    process_combat_action_batch,
    queue_final_character_update,
    stage_final_character_update,
    sync_multi_pc_character_state,
)
from core.combat.turn_commit import (
    COMBAT_TURN_COMMIT_MANIFEST_KEY,
    TurnCharacterEffect,
    commit_combat_turn,
    history_with_combat_turn_manifest,
)
# TABLETOP MODE: G7 preroll determinism is isolated at the injected dependency
# boundary and remains inert outside an explicitly authorized capture sandbox.
from core.combat.preroll_determinism import build_preroll_dependencies
from core.combat.enemy_batch_orchestrator import (
    complete_deterministic_enemy_batch_exit,
    EnemyBatchExecution,
    EnemyBatchOrchestrationDependencies,
    submit_tactical_prefetch_for_enemy_batch,
    try_execute_deterministic_enemy_batch,
)
from core.combat.narration import publish_combat_narration, publish_combat_output
from core.combat.commands import (
    CharacterStatCommandIO,
    DeterministicCommandIO,
    FastCommandResult,
    FastCommandIO,
    run_deterministic_command_stage,
    run_fast_commands_stage,
    run_character_stat_command,
)
from utils.validation_routing import (
    get_validation_compression_decision,
    build_validation_routing_telemetry,
)
# Import inventory context matcher for enhancing player combat actions
from core.ai.inventory_context_integration import enhance_player_input_with_inventory

# Import combat state sync helpers (plugin-style)
# TABLETOP MODE: Phase and roster synchronization helpers
try:
    from core.combat.multi_pc.sync import (
        apply_opening_batch_marker,
        normalize_multi_pc_roster,
    )
    COMBAT_STATE_SYNC_AVAILABLE = True
except ImportError:
    COMBAT_STATE_SYNC_AVAILABLE = False
    def apply_opening_batch_marker(encounter_data, starts_with):
        """Fallback: No-op if combat_state_sync not available."""
        return False
    def normalize_multi_pc_roster(encounter_data, party_tracker_data, path_manager):
        """Fallback: No-op if combat_state_sync not available."""
        return encounter_data, False

# Import multi-PC combat manager (plugin-style)
try:
    from core.combat.multi_pc.manager import (
        create_combat_manager,
        get_combat_manager,
        is_multi_pc_combat_enabled,
        modify_combat_prompt_for_multi_pc,
        get_multi_pc_initiative_narrative,
        emit_combat_event,
        temporary_combat_manager,
        CombatantType,
        PCStatus
    )
    MULTI_PC_COMBAT_AVAILABLE = True
except ImportError:
    MULTI_PC_COMBAT_AVAILABLE = False
    def get_combat_manager(): return None
    temporary_combat_manager = nullcontext
    def is_multi_pc_combat_enabled(): return False
    def modify_combat_prompt_for_multi_pc(base_prompt, pc_name, manager): return base_prompt
    def get_multi_pc_initiative_narrative(manager): return ""

# Set script name for logging
set_script_name(__name__)

# Remove color constants - no longer used
# Color codes removed per CLAUDE.md guidelines

# Temperature
TEMPERATURE = 0.8


def build_request_roll_action(
    character_name: str,
    roll_type: str,
    dc: int,
    reason: str,
    ability: str = None,
    skill: str = None,
    advantage: str = "normal",
) -> dict:
    """Build a lightweight requestRoll action payload (scaffolding helper)."""
    parameters = {
        "characterName": character_name,
        "rollType": roll_type,
        "dc": dc,
        "reason": reason,
        "advantage": advantage,
    }
    if ability:
        parameters["ability"] = ability
    if skill:
        parameters["skill"] = skill
    return {
        "action": "requestRoll",
        "parameters": parameters,
    }


def get_concentration_request_dc(damage_taken: int) -> int:
    """Return deterministic concentration save DC for requestRoll scaffolding."""
    return calculate_concentration_dc(damage_taken)

def get_combat_temperature(encounter_data, validation_attempt=0):
    """
    Calculate temperature for main combat processing based on encounter complexity.
    More creatures = lower temperature for better logical processing.
    Additional reduction applied for validation failures to improve consistency.
\x20\x20\x20\x20
    Args:
        encounter_data: The encounter data containing creature information
        validation_attempt: The current validation attempt number (0 = first try)
\x20\x20\x20\x20
    Returns:
        float: Temperature value between 0.1 and 0.8
    """
    creatures = encounter_data.get("creatures", [])
    creature_count = len(creatures)

    # Base temperature based on creature count
    if creature_count > 8:
        base_temp = 0.4
        complexity = "massive"
    elif creature_count > 6:
        base_temp = 0.5
        complexity = "very complex"
    elif creature_count > 4:
        base_temp = 0.6
        complexity = "complex"
    else:
        base_temp = 0.8
        complexity = "normal"

    # Apply reduction for validation failures
    # Each failure reduces temperature by 0.1, max reduction of 0.4
    temperature_reduction = min(validation_attempt * 0.1, 0.4)
    final_temp = max(base_temp - temperature_reduction, 0.1)  # Never go below 0.1

    # Round to 2 decimal places to avoid floating-point display issues
    final_temp = round(final_temp, 2)

    # Log the temperature selection
    if validation_attempt == 0:
        print(f"[COMBAT_MANAGER] Using temperature {final_temp} for {complexity} encounter ({creature_count} creatures)")
    else:
        print(f"[COMBAT_MANAGER] Lowering temperature from {base_temp:.1f} to {final_temp} after validation failure (attempt {validation_attempt + 1})")

    return final_temp

# AI client (factory supports OpenAI and OpenRouter)
client = create_chat_client()

conversation_history_file = "modules/conversation_history/combat_conversation_history.json"
second_model_history_file = "modules/conversation_history/second_model_history.json"
third_model_history_file = "modules/conversation_history/third_model_history.json"

# Create a combat_logs directory if it doesn't exist
os.makedirs("combat_logs", exist_ok=True)

# Constants for chat history generation
HISTORY_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def load_npc_with_fuzzy_match(npc_name, path_manager):
    """
    Load NPC data with fuzzy name matching support.
    First tries exact match, then falls back to fuzzy matching if needed.
\x20\x20\x20\x20
    Args:
        npc_name: The NPC name to look for
        path_manager: ModulePathManager instance
\x20\x20\x20\x20\x20\x20\x20\x20
    Returns:
        tuple: (npc_data, matched_filename) or (None, None) if not found
    """
    from utils.encoding_utils import safe_json_load

    # First try exact match with normalized name
    formatted_npc_name = path_manager.format_filename(npc_name)
    npc_file = path_manager.get_character_path(formatted_npc_name)
    npc_data = safe_json_load(npc_file)

    if npc_data:
        debug(f"NPC_LOAD: Exact match found for '{npc_name}' -> '{formatted_npc_name}'", category="combat_manager")
        return npc_data, formatted_npc_name

    # If exact match fails, try fuzzy matching
    debug(f"NPC_LOAD: Exact match failed for '{formatted_npc_name}', attempting fuzzy match", category="combat_manager")

    # Get all character files in the module
    import glob
    # Use the unified characters directory
    character_dir = "characters"
    character_files = glob.glob(os.path.join(character_dir, "*.json"))

    best_match = None
    best_score = 0
    best_filename = None

    for char_file in character_files:
        # Skip backup files
        if char_file.endswith(".bak") or char_file.endswith("_BU.json") or "backup" in char_file:
            continue

        # Load the character data to check if it's an NPC
        char_data = safe_json_load(char_file)
        # Check both character_type (correct field) and characterType (legacy) for compatibility
        char_type = char_data.get("character_type") or char_data.get("characterType")
        if char_data and char_type == "npc":
            char_name = char_data.get("name", "")
            # Simple fuzzy matching - check if key words from requested name are in character name
            requested_words = set(formatted_npc_name.lower().split("_"))
            char_words = set(char_name.lower().replace(" ", "_").split("_"))

            # Debug log for fuzzy matching
            debug(f"NPC_FUZZY: Comparing '{formatted_npc_name}' with '{char_name}' from {char_file}", category="combat_manager")
            debug(f"NPC_FUZZY: Requested words: {requested_words}, Character words: {char_words}", category="combat_manager")

            # Calculate match score based on word overlap
            common_words = requested_words.intersection(char_words)
            if common_words:
                score = len(common_words) / max(len(requested_words), len(char_words))

                if score > best_score:
                    best_score = score
                    best_match = char_data
                    # Extract just the filename without path for consistency
                    best_filename = os.path.splitext(os.path.basename(char_file))[0]

    # Use best match if score is high enough (threshold: 0.5)
    if best_match and best_score >= 0.5:
        info(f"NPC_FUZZY_MATCH: Success - '{npc_name}' matched to '{best_match['name']}' (score: {best_score:.2f})", category="combat_manager")
        return best_match, best_filename
    else:
        warning(f"NPC_FUZZY_MATCH: Failed for '{npc_name}' (best score: {best_score:.2f})", category="combat_manager")
        return None, None


def get_current_area_id():
    party_tracker = safe_json_load("party_tracker.json")
    if not party_tracker:
        error("FILE_OP: Failed to load party_tracker.json", category="file_operations")
        return None
    return party_tracker["worldConditions"]["currentAreaId"]

def get_location_data(location_id):
    from utils.module_path_manager import ModulePathManager
    from utils.encoding_utils import safe_json_load
    # Get current module from party tracker for consistent path resolution
    try:
        party_tracker = safe_json_load("party_tracker.json")
        current_module = party_tracker.get("module", "").replace(" ", "_") if party_tracker else None
        path_manager = ModulePathManager(current_module)
    except Exception as exc:
        warning(f"FILE_OP: Could not resolve area module from party tracker: {exc}", category="file_operations")
        path_manager = ModulePathManager()  # Fallback to reading from file

    current_area_id = get_current_area_id()
    debug(f"STATE_CHANGE: Current area ID: {current_area_id}", category="combat_events")
    area_file = path_manager.get_area_path(current_area_id)
    debug(f"FILE_OP: Attempting to load area file: {area_file}", category="file_operations")

    if not os.path.exists(area_file):
        error(f"FILE_OP: Area file {area_file} does not exist", category="file_operations")
        return None

    area_data = safe_json_load(area_file)
    if not area_data:
        error(f"FILE_OP: Failed to load area file: {area_file}", category="file_operations")
        return None
    debug(f"FILE_OP: Loaded area data: {json.dumps(area_data, indent=2)}", category="file_operations")

    for location in area_data["locations"]:
        if location["locationId"] == location_id:
            debug(f"VALIDATION: Found location data for ID {location_id}", category="combat_events")
            return location

    error(f"VALIDATION: Location with ID {location_id} not found in area data", category="combat_events")
    return None

def read_prompt_from_file(filename):
    # Prompts are now in the prompts/ directory at project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.join(script_dir, '..', '..')

    # Check if this is a combat prompt and use compressed version if toggle is on
    if USE_COMPRESSED_COMBAT:
        if filename == 'combat/combat_sim_prompt.txt':
            filename = 'combat/combat_sim_prompt_compressed.txt'
            debug("Using compressed combat prompt", category="combat_events")
        elif filename == 'combat/combat_sim_prompt_multipc.txt':
            filename = 'combat/combat_sim_prompt_multipc_compressed.txt'
            debug("Using compressed multi-pc combat prompt", category="combat_events")

    file_path = os.path.join(project_root, 'prompts', filename)
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read().strip()
    except Exception as e:
        error(f"FILE_OP: Failed to read prompt file {filename}: {str(e)}", category="file_operations")
        return ""

def load_monster_stats(monster_name):
    # Import the path manager
    from utils.module_path_manager import ModulePathManager
    from utils.encoding_utils import safe_json_load
    # Get current module from party tracker for consistent path resolution
    try:
        party_tracker = safe_json_load("party_tracker.json")
        current_module = party_tracker.get("module", "").replace(" ", "_") if party_tracker else None
        path_manager = ModulePathManager(current_module)
    except Exception as exc:
        warning(f"FILE_OP: Could not resolve monster module from party tracker: {exc}", category="file_operations")
        path_manager = ModulePathManager()  # Fallback to reading from file

    # Get the correct path for the monster file
    monster_file = path_manager.get_monster_path(monster_name)

    monster_stats = safe_json_load(monster_file)
    if not monster_stats:
        error(f"FILE_OP: Failed to load monster file: {monster_file}", category="file_operations")
    return monster_stats

def load_json_file(file_path):
    data = safe_json_load(file_path)
                # TABLETOP MODE: combat latency trace (Phase 0)
    trace_file_operation("read", "combat_history_load")
    if data is None:
        # If file doesn't exist or has invalid JSON, return an empty list
        return []
    return data

def save_json_file(file_path, data):
    try:
        safe_write_json(file_path, data)
        # TABLETOP MODE: combat latency trace (Phase 0)
        trace_file_operation("write", str(file_path))
    except Exception as e:
        error(f"FILE_OP: Failed to save {file_path}: {str(e)}", category="file_operations")


class CombatSessionAlreadyActiveError(RuntimeError):
    """Raised when a second combat loop attempts to start concurrently."""


_combat_session_lock = threading.Lock()
_active_combat_session_id = None


def _enter_combat_session(encounter_id):
    """Claim the single active combat loop slot for this process."""
    global _active_combat_session_id

    with _combat_session_lock:
        if _active_combat_session_id is not None:
            raise CombatSessionAlreadyActiveError(
                f"Combat session already active for encounter '{_active_combat_session_id}'"
            )
        _active_combat_session_id = encounter_id


def _exit_combat_session(encounter_id):
    """Release the active combat loop slot after combat exits."""
    global _active_combat_session_id

    with _combat_session_lock:
        if _active_combat_session_id == encounter_id:
            _active_combat_session_id = None

def clean_combat_state_blocks(conversation_history):
    """
    Remove the instructional combat state blocks from all but the most recent user message.
    This prevents bloating the conversation with repeated instructions while preserving
    the actual player actions and narrative.
    """
    # Find all user messages that contain combat state blocks
    user_messages_with_state = []
    for i, message in enumerate(conversation_history):
        if (message.get("role") == "user" and
            "--- CURRENT COMBAT STATE ---" in message.get("content", "")):
            user_messages_with_state.append(i)

    # If we have more than one, clean all but the last one
    if len(user_messages_with_state) > 1:
        for idx in user_messages_with_state[:-1]:  # All except the last one
            content = conversation_history[idx]["content"]

            # Extract just the player's actual message
            # Look for the pattern "Player: " after the state block ends
            if "Player: " in content:
                # Find where the state block ends (after "--- END OF STATE & DICE ---")
                if "--- END OF STATE & DICE ---" in content:
                    # Split on the end marker and then find the player message
                    parts = content.split("--- END OF STATE & DICE ---", 1)
                    if len(parts) == 2 and "Player: " in parts[1]:
                        # Extract just the player's message
                        player_parts = parts[1].split("Player: ", 1)
                        if len(player_parts) == 2:
                            player_msg = player_parts[1].split("\n\nNow, continue the combat flow", 1)[0].strip()
                            # Replace the entire message with just the player's input
                            conversation_history[idx]["content"] = f"Player: {player_msg}"
                            continue

            # Fallback: If we can't extract cleanly, at least remove the bulk of the state
            # but keep any player message
            if "Player: " in content:
                player_split = content.split("Player: ", 1)
                if len(player_split) == 2:
                    player_msg = player_split[1].split("\n\nNow, continue the combat flow", 1)[0].strip()
                    conversation_history[idx]["content"] = f"Player: {player_msg}"

    return conversation_history

def clean_old_dm_notes(conversation_history):
    """
    Clean up old Dungeon Master Notes from conversation history while preserving critical information.
    Keeps round tracking, HP status, and basic combat state for the last 2 rounds.
    This reduces token usage while maintaining enough context for proper combat flow.
    """
    # Find all DM note indices
    dm_note_indices = []
    for i, message in enumerate(conversation_history):
        if message.get("role") == "user" and "Dungeon Master Note:" in message.get("content", ""):
            dm_note_indices.append(i)

    # Keep the last 3 DM notes fully intact, clean older ones
    keep_full_count = 3

    for i, message in enumerate(conversation_history):
        if (message.get("role") == "user" and
            "Dungeon Master Note:" in message.get("content", "")):

            # Check if this is one of the recent DM notes to keep
            note_index_in_list = dm_note_indices.index(i) if i in dm_note_indices else -1
            if note_index_in_list >= len(dm_note_indices) - keep_full_count:
                # Keep this note fully intact
                continue

            # Clean older DM notes but preserve essential information
            content = message["content"]

            # Extract round information
            round_match = re.search(r"COMBAT ROUND (\d+)", content)
            round_info = f"Round {round_match.group(1)}" if round_match else ""

            # Extract HP state information
            hp_pattern = r"HP: \d+/\d+"
            hp_matches = re.findall(hp_pattern, content)
            hp_info = ", ".join(hp_matches) if hp_matches else ""

            # Extract player's message
            player_split = content.split("Player:", 1)
            player_msg = player_split[1].strip() if len(player_split) == 2 else ""

            # Construct cleaned message with essential info
            cleaned_parts = []
            if round_info:
                cleaned_parts.append(round_info)
            if hp_info:
                cleaned_parts.append(f"HP: {hp_info}")
            if player_msg:
                cleaned_parts.append(f"Player: {player_msg}")

            if cleaned_parts:
                message["content"] = f"Dungeon Master Note: {'. '.join(cleaned_parts)}"
            else:
                # Keep the original message to see what's not being extracted
                # This helps identify what other user messages are in the conversation
                # (e.g., "resuming combat", system messages, etc.)
                pass  # Don't modify the message - keep original content

    return conversation_history

def is_valid_json(json_string):
    try:
        json_object = json.loads(json_string)
        if not isinstance(json_object, dict):
            return False
        if "narration" not in json_object or not isinstance(json_object["narration"], str):
            return False
        if "actions" not in json_object or not isinstance(json_object["actions"], list):
            return False
        # Optional plan field - if present, must be a string
        if "plan" in json_object and not isinstance(json_object["plan"], str):
            return False
        return True
    except json.JSONDecodeError:
        return False

def write_debug_output(content, filename="debug_second_model.json"):
    try:
        with open(filename, "w") as debug_file:
            json.dump(content, debug_file, indent=2)
    except Exception as e:
        debug(f"FILE_OP: Writing debug output failed - {str(e)}", category="file_operations")

def parse_json_safely(text):
    """Extract and parse JSON from text, handling various formats"""
    # First, try to parse as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract from code block
    try:
        match = re.search(r'```json\n(.*?)```', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except json.JSONDecodeError:
        pass

    # If all else fails, try to find any JSON-like structure
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except json.JSONDecodeError:
        pass

    # If we still can't parse it, raise an exception
    raise json.JSONDecodeError("Unable to parse JSON from the given text", text, 0)

def check_multiple_update_encounter(actions):
    """Check if there are multiple updateEncounter actions that should be consolidated"""
    if not isinstance(actions, list):
        return False

    update_encounter_count = 0
    for action in actions:
        if isinstance(action, dict) and action.get("action", "").lower() == "updateencounter":
            update_encounter_count += 1

    return update_encounter_count > 1

def create_consolidation_prompt(parsed_response):
    """Create a retry prompt for consolidating multiple updateEncounter actions"""
    actions = parsed_response.get("actions", [])

    # Extract all updateEncounter changes
    encounter_changes = []
    encounter_id = None

    for action in actions:
        if action.get("action", "").lower() == "updateencounter":
            params = action.get("parameters", {})
            if not encounter_id:
                encounter_id = params.get("encounterId", "")
            changes = params.get("changes", "")
            if changes:
                encounter_changes.append(changes)

    # Create the consolidated changes description
    # Add proper punctuation between changes
    consolidated_changes = ". ".join(encounter_changes)
    if not consolidated_changes.endswith("."):
        consolidated_changes += "."

    retry_prompt = f"""Your previous response contained multiple updateEncounter actions, but these must be consolidated into ONE action.

IMPORTANT RULES:
1. ALL monster/enemy changes must be in ONE updateEncounter action
2. updateCharacterInfo is ONLY for players and NPCs (never monsters)
3. updateEncounter is ONLY for monsters/enemies (never players or NPCs)

You had {len(encounter_changes)} separate updateEncounter actions with these changes:
{chr(10).join(f'- {change}' for change in encounter_changes)}

Please provide a new response with:
1. The same narration and combat_round
2. ONE updateEncounter action combining all monster changes: "{consolidated_changes}"
3. Keep all other actions (updateCharacterInfo, exit, etc.) unchanged

Remember: One updateEncounter for ALL monster changes, separate updateCharacterInfo for each player/NPC change."""

    return retry_prompt

def create_multiple_update_requery_prompt(parsed_response):
    """Create a requery prompt when multiple updateEncounter actions are detected"""
    actions = parsed_response.get("actions", [])

    # Count updateEncounter actions
    update_encounter_count = 0
    for action in actions:
        if isinstance(action, dict) and action.get("action", "").lower() == "updateencounter":
            update_encounter_count += 1

    retry_prompt = f"""Your response contained {update_encounter_count} updateEncounter actions. This is incorrect - you must use ONLY ONE updateEncounter action that describes ALL monster changes.

CRITICAL ACTION DISTINCTION - NEVER CONFUSE THESE:
- updateCharacterInfo: Use ONLY for players (your character) and NPCs (allies/neutral characters)
  - These have their own character files that store their HP, inventory, etc.
  - Example: updateCharacterInfo for "ExampleChar_Cleric" (player) or "Scout Kira" (NPC)
\x20\x20
- updateEncounter: Use ONLY for monsters/enemies in the encounter
  - These exist only within the encounter file
  - Use ONE updateEncounter action that describes ALL monster changes
  - Example: updateEncounter describing "Goblin takes 10 damage (HP 15 -> 5). Orc takes 8 damage (HP 20 -> 12)."

REMEMBER:\x20
- The encounter file references player/NPC files but doesn't store their HP
- Monster HP is stored directly in the encounter file
- Use exactly ONE updateEncounter action for ALL monster changes in a turn

Please provide a corrected response that:
1. Uses exactly ONE updateEncounter action for all monster changes
2. Uses updateCharacterInfo for any player/NPC changes
3. Consolidates all monster updates into the single updateEncounter's changes field"""

    return retry_prompt

def sanitize_unicode_for_logging(text):
    """
    Replace common Unicode characters with ASCII equivalents for logging compatibility.
    Prevents UnicodeEncodeError when logging to files on Windows.
    """
    if not isinstance(text, str):
        return text

    # Replace common Unicode characters with ASCII equivalents
    replacements = {
        '\u2192': '->',  # Right arrow
        '\u2190': '<-',  # Left arrow
        '\u2194': '<->',  # Left-right arrow
        '\u2014': '--',  # Em dash
        '\u2013': '-',   # En dash
        '\u201c': '"',   # Left double quotation mark
        '\u201d': '"',   # Right double quotation mark
        '\u2018': "'",   # Left single quotation mark
        '\u2019': "'",   # Right single quotation mark
        '\u2026': '...',  # Horizontal ellipsis
    }

    for unicode_char, ascii_replacement in replacements.items():
        text = text.replace(unicode_char, ascii_replacement)

    return text


def _is_combat_inventory_or_ammo_change(changes_text):
    """Return True when changes text implies inventory/ammo mutation."""
    if not isinstance(changes_text, str) or not changes_text.strip():
        return False

    lower = changes_text.lower()
    inventory_terms = (
        "inventory",
        "equipment",
        "item",
        "ammo",
        "ammunition",
        "arrow",
        "bolt",
        "quiver",
        "coin",
        "gold",
        "silver",
        "copper",
        "expended",
    )
    non_inventory_terms = (
        "hp",
        "hit point",
        "damage",
        "healed",
        "condition",
        "death save",
        "spell slot",
        "slot",
        "unconscious",
        "stabil",
    )

    if any(term in lower for term in inventory_terms):
        return True
    if any(term in lower for term in non_inventory_terms):
        return False
    return False


def _extract_touched_character_updates_from_response_json(response_json):
    """Extract touched updateCharacterInfo targets and compact change metadata."""
    if not isinstance(response_json, dict):
        return {}

    actions = response_json.get("actions", [])
    if not isinstance(actions, list):
        return {}

    touched_updates = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action") != "updateCharacterInfo":
            continue

        params = action.get("parameters", {})
        if not isinstance(params, dict):
            continue

        character_name = str(params.get("characterName", "")).strip()
        if not character_name:
            continue

        changes = params.get("changes", "")
        if not isinstance(changes, str):
            changes = ""

        entry = touched_updates.setdefault(
            character_name,
            {"changes": [], "inventory_relevant": False, "inventory_containers": []},
        )

        if changes.strip():
            entry["changes"].append(changes.strip())
            if _is_combat_inventory_or_ammo_change(changes):
                entry["inventory_relevant"] = True

        ops = params.get("ops", [])
        if isinstance(ops, list):
            for op in ops:
                if not isinstance(op, dict) or str(op.get("op", "")).strip().lower() not in (
                    "inventory_add", "inventory_remove"
                ):
                    continue
                entry["inventory_relevant"] = True
                container = str(op.get("container", "equipment")).strip().lower()
                item_type = str(op.get("item_type", "")).strip().lower()
                canonical_container = "ammunition" if (
                    container == "ammunition" or item_type == "ammunition"
                ) else "equipment"
                if canonical_container not in entry["inventory_containers"]:
                    entry["inventory_containers"].append(canonical_container)

    return touched_updates


def _build_compact_combat_truth_pack(response_json, encounter_data):
    """Build compact touched-combatant truth packs for PC/allied NPC updates."""
    touched_updates = _extract_touched_character_updates_from_response_json(response_json)
    if not touched_updates:
        return []

    allowed_names = set()
    creatures = encounter_data.get("creatures", [])
    if isinstance(creatures, list):
        for creature in creatures:
            if not isinstance(creature, dict):
                continue
            creature_type = str(creature.get("type", "")).strip().lower()
            if creature_type not in ("player", "npc"):
                continue
            creature_name = str(creature.get("name", "")).strip().lower()
            if creature_name:
                allowed_names.add(creature_name)

    from utils.pc_manager import get_character_state

    truth_packs = []
    for character_name, meta in touched_updates.items():
        normalized_name = character_name.strip().lower()
        if allowed_names and normalized_name not in allowed_names:
            continue

        character_data = get_character_state(character_name)
        if not isinstance(character_data, dict):
            continue

        hp = character_data.get("hitPoints", 0)
        max_hp = character_data.get("maxHitPoints", 0)
        try:
            hp_value = int(hp or 0)
        except (TypeError, ValueError):
            hp_value = 0
        try:
            max_hp_value = int(max_hp or 0)
        except (TypeError, ValueError):
            max_hp_value = 0

        conditions = character_data.get("condition_affected", [])
        if not isinstance(conditions, list):
            conditions = []

        spell_slots_summary = {}
        spell_slots = character_data.get("spellSlots", {})
        if not isinstance(spell_slots, dict):
            spell_slots = {}
        spellcasting = character_data.get("spellcasting")
        if isinstance(spellcasting, dict):
            nested_slots = spellcasting.get("spellSlots")
            if isinstance(nested_slots, dict):
                spell_slots = nested_slots
        if isinstance(spell_slots, dict):
            for level, slot_data in spell_slots.items():
                if not isinstance(slot_data, dict):
                    continue
                try:
                    spell_slots_summary[str(level)] = {
                        "current": int(slot_data.get("current", 0) or 0),
                        "max": int(slot_data.get("max", 0) or 0),
                    }
                except (TypeError, ValueError):
                    continue

        death_saves_data = character_data.get("deathSaves")
        if isinstance(death_saves_data, dict):
            death_success = death_saves_data.get("successes", 0)
            death_fail = death_saves_data.get("failures", 0)
        else:
            death_success = character_data.get("deathSaveSuccesses", 0)
            death_fail = character_data.get("deathSaveFailures", 0)

        try:
            death_saves = {
                "successes": int(death_success or 0),
                "failures": int(death_fail or 0),
            }
        except (TypeError, ValueError):
            death_saves = {"successes": 0, "failures": 0}

        pack = {
            "characterName": str(character_data.get("name") or character_name),
            "hp": hp_value,
            "maxHp": max_hp_value,
            "conditions": [str(condition) for condition in conditions],
            "spellSlots": spell_slots_summary,
            "deathSaves": death_saves,
        }

        creature_types = character_data.get("creatureTypes", [])
        if isinstance(creature_types, list) and creature_types:
            pack["creatureTypes"] = [str(entry).strip().lower() for entry in creature_types if str(entry or "").strip()]

        supernatural_states = character_data.get("supernaturalStates", [])
        if isinstance(supernatural_states, list) and supernatural_states:
            compact_states = []
            for state in supernatural_states:
                if not isinstance(state, dict):
                    continue
                compact_states.append({
                    "id": str(state.get("id") or "").strip(),
                    "label": str(state.get("label") or "").strip(),
                    "category": str(state.get("category") or "").strip(),
                    "playable": bool(state.get("playable", True)),
                    "mechanicalEffects": [
                        str(effect).strip()
                        for effect in state.get("mechanicalEffects", [])
                        if str(effect or "").strip()
                    ][:2],
                })
            if compact_states:
                pack["supernaturalStates"] = compact_states

        features = character_data.get("classFeatures", [])
        limited_resources = []
        if isinstance(features, list):
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                feature_name = str(feature.get("name", "")).strip()
                if not feature_name:
                    continue
                nested_usage = feature.get("usage")
                has_nested_usage = isinstance(nested_usage, dict) and (
                    nested_usage.get("current") is not None or nested_usage.get("max") is not None
                )
                has_flat_usage = any(key in feature for key in ("uses", "maxUses", "currentUses", "recharge"))
                if not has_nested_usage and not has_flat_usage:
                    continue
                resource_item = {"name": feature_name}
                if has_nested_usage:
                    usage_block = {}
                    if nested_usage.get("current") is not None:
                        usage_block["current"] = nested_usage.get("current")
                    if nested_usage.get("max") is not None:
                        usage_block["max"] = nested_usage.get("max")
                    if nested_usage.get("refreshOn"):
                        usage_block["refreshOn"] = nested_usage.get("refreshOn")
                    if usage_block:
                        resource_item["usage"] = usage_block
                for key in ("uses", "maxUses", "currentUses", "recharge"):
                    if key in feature:
                        resource_item[key] = feature.get(key)
                limited_resources.append(resource_item)
                if len(limited_resources) >= 8:
                    break

        if limited_resources:
            pack["limitedResources"] = limited_resources

        if meta.get("inventory_relevant", False):
            inventory_block = {}

            selected_containers = meta.get("inventory_containers", [])
            if not isinstance(selected_containers, list):
                selected_containers = []
            # Keep legacy prose-context shape intact; structured inventory ops
            # select the committed canonical container without copying candidate data.
            include_equipment = not selected_containers or "equipment" in selected_containers
            include_ammunition = not selected_containers or "ammunition" in selected_containers

            currency = character_data.get("currency", {})
            if isinstance(currency, dict):
                inventory_block["currency"] = {
                    "gold": int(currency.get("gold", 0) or 0),
                    "silver": int(currency.get("silver", 0) or 0),
                    "copper": int(currency.get("copper", 0) or 0),
                }

            ammunition = character_data.get("ammunition", []) if include_ammunition else []
            ammo_summary = []
            if isinstance(ammunition, list):
                for ammo_item in ammunition[:10]:
                    if not isinstance(ammo_item, dict):
                        continue
                    ammo_name = ammo_item.get("name", "Unknown")
                    ammo_quantity = ammo_item.get("quantity", 0)
                    ammo_summary.append(
                        {
                            "name": str(ammo_name),
                            "quantity": ammo_quantity,
                        }
                    )
            if ammo_summary:
                inventory_block["ammunition"] = ammo_summary

            equipment = character_data.get("equipment", []) if include_equipment else []
            equipment_summary = []
            if isinstance(equipment, list):
                for equipment_item in equipment[:12]:
                    if not isinstance(equipment_item, dict):
                        continue
                    equipment_name = equipment_item.get("item_name") or equipment_item.get("name") or "Unknown"
                    equipment_quantity = equipment_item.get("quantity", 1)
                    equipment_summary.append(
                        {
                            "name": str(equipment_name),
                            "quantity": equipment_quantity,
                        }
                    )
            if equipment_summary:
                inventory_block["equipment"] = equipment_summary

            if inventory_block:
                pack["inventory"] = inventory_block

        truth_packs.append(pack)

    return truth_packs


def _build_canonical_non_pc_attack_facts(
    encounter_data,
    *,
    path_manager_factory=None,
    safe_json_loader=None,
    npc_loader=None,
):
    """Project bounded source-backed non-PC mechanics for validation only."""
    if not isinstance(encounter_data, dict):
        return []

    if path_manager_factory is None:
        from utils.module_path_manager import ModulePathManager as path_manager_factory
    if safe_json_loader is None:
        from utils.encoding_utils import safe_json_load as safe_json_loader
    if npc_loader is None:
        npc_loader = load_npc_with_fuzzy_match

    module_name = None
    try:
        party_tracker = safe_json_loader("party_tracker.json")
        module_name = party_tracker.get("module", "").replace(" ", "_") if isinstance(party_tracker, dict) else None
        path_manager = path_manager_factory(module_name or None)
    except Exception:
        path_manager = None

    selected_attack_fields = (
        "name", "attackBonus", "damageDice", "damageBonus", "damageType", "type",
        "description", "range", "reach",
    )

    def is_finite_number(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (isinstance(value, int) or math.isfinite(value))
        )

    facts = []
    creatures = encounter_data.get("creatures", [])
    if not isinstance(creatures, list):
        return facts

    for creature in creatures[:32]:
        if not isinstance(creature, dict):
            continue
        creature_type = str(creature.get("type", "")).strip().lower()
        if creature_type == "player":
            continue
        if creature_type not in ("npc", "enemy"):
            continue
        actor_name = creature.get("name")
        actor_name = actor_name.strip()[:80] if isinstance(actor_name, str) else ""
        if not actor_name:
            continue

        hp = creature.get("currentHitPoints", creature.get("hitPoints"))
        status = str(creature.get("status", "")).strip().lower()
        eligible = status not in ("inactive", "defeated", "dead")
        try:
            if hp is not None and float(hp) <= 0:
                eligible = False
        except (TypeError, ValueError):
            pass

        source_data = None
        source_identity = None
        source_path = None
        source_status = "unknown"
        try:
            if creature_type == "npc" and path_manager is not None:
                source_data, matched_filename = npc_loader(actor_name, path_manager)
                source_identity = matched_filename
                if matched_filename:
                    source_path = path_manager.get_character_path(matched_filename)
                canonical_name = source_data.get("name") if isinstance(source_data, dict) else None
                if isinstance(canonical_name, str) and canonical_name.strip().casefold() == actor_name.casefold():
                    source_status = "matched"
                elif source_data is not None:
                    source_status = "stale_or_mismatched"
                    source_data = None
            elif creature_type == "enemy" and path_manager is not None:
                monster_type = creature.get("monsterType")
                if isinstance(monster_type, str) and monster_type.strip():
                    source_identity = monster_type.strip()[:80]
                    source_path = path_manager.get_monster_path(monster_type)
                    source_data = safe_json_loader(source_path)
                    if isinstance(source_data, dict):
                        canonical_name = source_data.get("name")
                        canonical_type = source_data.get("monsterType")
                        if any(
                            isinstance(value, str) and value.strip().casefold() == monster_type.strip().casefold()
                            for value in (canonical_name, canonical_type)
                        ):
                            source_status = "matched"
                        elif canonical_name is None and canonical_type is None:
                            source_status = "unknown"
                            source_data = None
                        else:
                            source_status = "stale_or_mismatched"
                            source_data = None
        except Exception:
            source_data = None
            source_status = "unknown"

        attack_records = []
        source_attack_field = "actions" if creature_type == "enemy" else "attacksAndSpellcasting"
        field_status = {field: "unknown_missing" for field in (*selected_attack_fields, source_attack_field)}

        def record_field_status(field, status):
            current = field_status.get(field, "unknown_missing")
            if current != "unknown_malformed" and (status == "unknown_malformed" or current == "unknown_missing"):
                field_status[field] = status

        if source_status == "matched" and isinstance(source_data, dict):
            source_attacks = source_data.get(source_attack_field)
            if isinstance(source_attacks, list):
                field_status[source_attack_field] = "source_backed"
                for attack in source_attacks[:8]:
                    if not isinstance(attack, dict):
                        record_field_status(source_attack_field, "unknown_malformed")
                        continue
                    projected = {}
                    record_status = {field: "unknown_missing" for field in selected_attack_fields}
                    for field in selected_attack_fields:
                        if field not in attack:
                            continue
                        value = attack[field]
                        if field in ("attackBonus", "damageBonus"):
                            if is_finite_number(value):
                                projected[field] = value
                                record_status[field] = "source_backed"
                            else:
                                record_status[field] = "unknown_malformed"
                        elif isinstance(value, str) or is_finite_number(value):
                            projected[field] = value if not isinstance(value, str) else value[:240]
                            record_status[field] = "source_backed"
                        else:
                            record_status[field] = "unknown_malformed"
                        record_field_status(field, record_status[field])
                    if projected:
                        projected["fieldStatus"] = record_status
                        attack_records.append(projected)
            elif source_attack_field in source_data:
                record_field_status(source_attack_field, "unknown_malformed")
            top_attack_bonus = source_data.get("attackBonus")
            if is_finite_number(top_attack_bonus):
                record_field_status("attackBonus", "source_backed")
            elif "attackBonus" in source_data:
                record_field_status("attackBonus", "unknown_malformed")

        facts.append({
            "actor": {"name": actor_name, "type": creature_type, "eligible": eligible},
            "canonicalSource": {
                "status": source_status,
                "module": module_name if isinstance(module_name, str) and module_name else "unknown",
                "identity": source_identity or "unknown",
                "sourceFile": os.path.basename(source_path)[:120] if isinstance(source_path, str) else "unknown",
            },
            "attackFacts": {
                "attackBonus": source_data.get("attackBonus") if isinstance(source_data, dict)
                    and is_finite_number(source_data.get("attackBonus")) else None,
                "sourceField": source_attack_field,
                source_attack_field: attack_records,
                "fieldStatus": field_status,
            },
        })
    return facts


def _build_combat_validation_dependencies() -> CombatValidationDependencies:
    import model_config

    def validation_llm_call(task, messages, **kwargs):
        from utils.llm_router import llm
        return llm.call(task, messages, **kwargs)

    def validation_receipt_observer_factory(**kwargs):
        from utils.llm_runtime import make_legacy_receipt_observer
        return make_legacy_receipt_observer(**kwargs)

    def log_api_call(*args, **kwargs):
        from utils.api_logger import log_api_call as callback
        return callback(*args, **kwargs)

    def track_usage(result):
        from utils.openai_usage_tracker import get_global_tracker
        tracker = get_global_tracker()
        return tracker.track(result, context={"endpoint": "combat_validation", "purpose": "validate_combat_response"})

    return CombatValidationDependencies(
        parse_json_safely=parse_json_safely,
        phase_precheck=validate_combat_phase_integrity_precheck,
        replay_precheck=validate_already_applied_enemy_replay_precheck,
        narration_precheck=validate_combat_narration_consistency_precheck,
        enemy_boundary_precheck=validate_update_encounter_enemy_boundary_precheck,
        truth_pack_builder=_build_compact_combat_truth_pack,
        canonical_attack_facts_builder=_build_canonical_non_pc_attack_facts,
        read_prompt=read_prompt_from_file,
        compressed_combat=model_config.USE_COMPRESSED_COMBAT,
        compression_enabled=COMPRESSION_ENABLED,
        compression_threshold_chars=VALIDATION_COMPRESSION_MIN_CHARS,
        compression_decision=get_validation_compression_decision,
        telemetry_builder=build_validation_routing_telemetry,
        client=client, validation_model=DM_VALIDATION_MODEL,
        completion_params=get_chat_completion_params,
        trace_provider_call=trace_provider_call,
        sanitize_for_logging=sanitize_unicode_for_logging,
        debug=debug, warning=warning, emit_console=print,
        usage_tracking_available=USAGE_TRACKING_AVAILABLE, track_usage=track_usage,
        log_api_call=log_api_call, export_open=open, makedirs=os.makedirs,
        now=datetime.now, format_log_timestamp=time.strftime,
        perf_counter=time.perf_counter,
        llm_call=validation_llm_call,
        receipt_observer_factory=validation_receipt_observer_factory,
    )

def validate_combat_response(
    response: str,
    encounter_data: Dict[str, Any],
    user_input: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    multi_pc_manager: Any = None,
) -> Any:
    from core.combat.validation import validate_combat_response as validate_stage
    return validate_stage(
        response, encounter_data, user_input, conversation_history, multi_pc_manager,
        dependencies=_build_combat_validation_dependencies(),
    )


def _build_combat_retry_dependencies() -> CombatRetryDependencies:
    """Resolve compatibility/monkeypatch bindings at the legacy owner seam."""
    from config import USE_GPT5_MODELS, GPT5_MINI_MODEL, GPT5_USE_HIGH_REASONING_ON_RETRY

    def retry_llm_call(task, messages, **kwargs):
        from utils.llm_router import llm
        return llm.call(task, messages, **kwargs)

    def retry_receipt_observer_factory(**kwargs):
        from utils.llm_runtime import make_legacy_receipt_observer
        return make_legacy_receipt_observer(**kwargs)

    def update_status(message, is_processing):
        from core.managers.status_manager import status_manager
        return status_manager.update_status(message, is_processing=is_processing)

    return CombatRetryDependencies(
        client=client,
        use_gpt5_models=USE_GPT5_MODELS,
        gpt5_mini_model=GPT5_MINI_MODEL,
        gpt5_high_reasoning_on_retry=GPT5_USE_HIGH_REASONING_ON_RETRY,
        combat_main_model=COMBAT_MAIN_MODEL,
        get_completion_params=get_chat_completion_params,
        get_temperature=get_combat_temperature,
        perf_counter=time.perf_counter,
        trace_stage=trace_stage,
        trace_provider_call=trace_provider_call,
        export_open=open,
        makedirs=os.makedirs,
        emit=print,
        debug=debug,
        warning=warning,
        error=error,
        usage_tracking_available=USAGE_TRACKING_AVAILABLE,
        track_usage=track_response,
        is_valid_json=is_valid_json,
        check_multiple_update_encounter=check_multiple_update_encounter,
        make_multiple_update_feedback=create_multiple_update_requery_prompt,
        validate_combatant_integrity=validate_combatant_integrity,
        validate_combat_response=validate_combat_response,
        update_status=update_status,
        llm_call=retry_llm_call,
        receipt_observer_factory=retry_receipt_observer_factory,
    )


def _build_enemy_batch_orchestration_dependencies(session) -> EnemyBatchOrchestrationDependencies:
    """Bind the deterministic batch to the same router and lifecycle owners."""
    def enemy_batch_llm_call(task, messages, **kwargs):
        from utils.llm_router import llm
        return llm.call(task, messages, **kwargs)

    def enemy_batch_receipt_observer_factory(**kwargs):
        from utils.llm_runtime import make_legacy_receipt_observer
        return make_legacy_receipt_observer(**kwargs)

    return EnemyBatchOrchestrationDependencies(
        read_json=safe_json_load,
        write_json=safe_write_json,
        round_transition_dependencies=RoundTransitionDependencies(
            apply_opening_batch_marker=apply_opening_batch_marker,
            sync_available=COMBAT_STATE_SYNC_AVAILABLE,
            save_json=save_json_file,
            compress_old_rounds=compress_old_combat_rounds,
            log_debug=debug,
            log_info=info,
            log_warning=warning,
            bind_history=session.bind_history,
        ),
        llm_call=enemy_batch_llm_call,
        receipt_observer_factory=enemy_batch_receipt_observer_factory,
        publish_narration=lambda text, *, applied_id: publish_combat_narration(
            text, applied_id=applied_id, emit=print, flush=sys.stdout.flush
        ),
        usage_tracking_available=USAGE_TRACKING_AVAILABLE,
        combat_main_model=COMBAT_MAIN_MODEL,
        clean_old_dm_notes=clean_old_dm_notes,
        clean_combat_state_blocks=clean_combat_state_blocks,
        calculate_xp_for_encounter=lambda projection, tracker: calculate_xp(
            projection, tracker
        ),
        check_all_monsters_defeated=check_all_monsters_defeated,
        session=session,
    )


def _build_combat_initialization_dependencies() -> CombatInitializationDependencies:
    """Resolve startup imports and current owner patch bindings on demand."""
    from utils.module_path_manager import ModulePathManager
    from utils.encoding_utils import safe_json_load

    def print_startup_traceback():
        import traceback
        traceback.print_exc()

    history_dependencies = CombatHistoryDependencies(
        exists=os.path.exists,
        getsize=os.path.getsize,
        load_json=load_json_file,
        read_prompt=read_prompt_from_file,
        save_json=save_json_file,
        format_character=format_character_for_combat,
        format_npc=format_npc_for_combat,
        filter_dynamic_fields=filter_dynamic_fields,
        filter_encounter=filter_encounter_for_system_prompt,
        log_structure=log_conversation_structure,
        debug=debug,
        error=error,
        emit=print,
        remove=os.remove,
    )
    return CombatInitializationDependencies(
        module_path_manager_factory=ModulePathManager,
        safe_json_load=safe_json_load,
        session_factory=CombatSession,
        multi_pc_combat_available=MULTI_PC_COMBAT_AVAILABLE,
        is_multi_pc_enabled=is_multi_pc_combat_enabled,
        normalize_phase1_initiative=normalize_phase1_initiative,
        save_json=save_json_file,
        write_json=safe_write_json,
        get_combat_manager=get_combat_manager,
        create_combat_manager=create_combat_manager,
        history_file=conversation_history_file,
        second_model_history_file=second_model_history_file,
        third_model_history_file=third_model_history_file,
        history_dependencies=history_dependencies,
        normalize_character_name=normalize_character_name,
        load_npc_with_fuzzy_match=load_npc_with_fuzzy_match,
        file_exists=os.path.exists,
        list_directory=os.listdir,
        print_exception=print_startup_traceback,
        emit=print,
        debug=debug,
        info=info,
        warning=warning,
        error=error,
        publish_narration=lambda text, *, applied_id: publish_combat_narration(
            text,
            applied_id=applied_id,
            emit=print,
            flush=sys.stdout.flush,
        ),
    )


def _build_startup_narrative_dependencies() -> CombatStartupNarrativeDependencies:
    """Resolve live owner bindings at the startup narrative call point."""
    def startup_llm_call(task, messages, **kwargs):
        from utils.llm_router import llm
        return llm.call(task, messages, **kwargs)

    def startup_receipt_observer_factory(**kwargs):
        from utils.llm_runtime import make_legacy_receipt_observer
        return make_legacy_receipt_observer(**kwargs)

    def resume_config():
        from config import USE_GPT5_MODELS, GPT5_MINI_MODEL
        return USE_GPT5_MODELS, GPT5_MINI_MODEL

    def log_startup_api_call(*args, **kwargs):
        from utils.api_logger import log_api_call
        return log_api_call(*args, **kwargs)

    return CombatStartupNarrativeDependencies(
        client=client,
        resume_config=resume_config,
        combat_main_model=COMBAT_MAIN_MODEL,
        completion_params=get_chat_completion_params,
        get_temperature=get_combat_temperature,
        get_initiative_order=get_initiative_order,
        get_multi_pc_initiative_narrative=get_multi_pc_initiative_narrative,
        modify_prompt_for_multi_pc=modify_combat_prompt_for_multi_pc,
        is_valid_json=is_valid_json,
        validate_response=validate_combat_response,
        save_json=save_json_file,
        export_open=open,
        perf_counter=time.perf_counter,
        trace_stage=trace_stage,
        trace_provider_call=trace_provider_call,
        usage_tracking_available=USAGE_TRACKING_AVAILABLE,
        track_usage=track_response,
        log_api_call=log_startup_api_call,
        emit=print,
        flush=sys.stdout.flush,
        debug=debug,
        info=info,
        warning=warning,
        error=error,
        publish_narration=publish_combat_narration,
        publish_output=publish_combat_output,
        llm_call=startup_llm_call,
        receipt_observer_factory=startup_receipt_observer_factory,
    )


def _build_turn_iteration_dependencies(safe_json_loader) -> CombatTurnIterationDependencies:
    """Resolve per-iteration logging/status/input bindings at the loop call point."""
    def update_status(message, is_processing):
        from core.managers.status_manager import status_manager
        return status_manager.update_status(message, is_processing=is_processing)

    return CombatTurnIterationDependencies(
        safe_json_load=safe_json_loader,
        perf_counter=time.perf_counter,
        trace_file_operation=trace_file_operation,
        trace_set_context=set_trace_context,
        trace_stage=trace_stage,
        trace_enabled=trace_enabled,
        debug=debug,
        emit=print,
        error=error,
        update_status=update_status,
        sync_active_encounter=sync_active_encounter,
        normalize_character_name=normalize_character_name,
        format_character=format_character_for_combat,
        load_npc_with_fuzzy_match=load_npc_with_fuzzy_match,
        filter_encounter=filter_encounter_for_system_prompt,
        filter_dynamic_fields=filter_dynamic_fields,
        save_json=save_json_file,
        read_input=input,
        flush=sys.stdout.flush,
    )


def _build_normal_turn_dependencies(
    module_path_manager_factory,
    safe_json_loader,
    monster_definitions=None,
    preroll_generator=None,
    preroll_random_int=None,
) -> CombatNormalTurnDependencies:
    """Resolve the current owner stage bindings for one normal player turn."""
    if preroll_generator is None:
        preroll_generator = generate_prerolls
    if preroll_random_int is None:
        preroll_random_int = random.randint

    def phase_gate_io(manager):
        return PhaseGateIO(
            emit=print,
            flush=sys.stdout.flush,
            debug=debug,
            save_json=save_json_file,
            parse_death_save_roll=(
                (lambda text, gate: type(manager).parse_death_save_roll_input(text, gate))
                if manager else (lambda text, gate: (False, None, None))
            ),
            commit_active_character=commit_active_character,
        )

    def fast_command_io():
        def persist_fast_encounter(current_id, data):
            persisted = safe_write_json(
                f"modules/encounters/encounter_{current_id}.json", data
            )
            if persisted is True:
                # TABLETOP MODE: Only the confirmed deterministic encounter
                # write crosses as a typed player notice.
                from utils.player_host_publication import submit_player_host_change

                submit_player_host_change("combat")
            return persisted

        return FastCommandIO(
            emit=print,
            flush=sys.stdout.flush,
            debug=debug,
            warning=warning,
            save_json=save_json_file,
            persist_encounter=persist_fast_encounter,
        )

    def deterministic_command_io(path_manager, player_file, session, party_tracker_snapshot):
        def sync_command_encounter(*, force=False):
            return sync_active_encounter(
                party_tracker_snapshot,
                session,
                session.turn_iteration_id,
                force=force,
            )

        return DeterministicCommandIO(
            emit=print,
            flush=sys.stdout.flush,
            load_json=safe_json_loader,
            save_json=save_json_file,
            write_json=safe_write_json,
            path_manager=path_manager,
            normalize_name=normalize_character_name,
            sync_active_encounter=sync_command_encounter,
            save_manager_factory=lambda: __import__("updates.save_game_manager", fromlist=["SaveGameManager"]).SaveGameManager(),
            summarize_dialogue=summarize_dialogue,
            generate_chat_history=generate_chat_history,
        )

    def character_stat_io(path_manager):
        return CharacterStatCommandIO(
            load_json=safe_json_loader,
            normalize_name=normalize_character_name,
            path_manager=path_manager,
            write_json=safe_write_json,
            emit=print,
            flush=sys.stdout.flush,
        )

    def assemble_context(inputs):
        return assemble_combat_context(
            inputs,
            CombatContextDependencies(
                normalize_character_name=normalize_character_name,
                safe_json_load=safe_json_loader,
                load_npc_with_fuzzy_match=load_npc_with_fuzzy_match,
                collect_authoritative_combat_roster=_collect_authoritative_combat_roster,
                generate_prerolls=preroll_generator,
                save_json_file=save_json_file,
                module_path_manager_factory=module_path_manager_factory,
                file_exists=os.path.exists,
                logger_debug=debug,
                logger_error=error,
                emit=print,
                random_int=preroll_random_int,
                fallback_initiative_tracker=_generate_live_initiative_tracker_fallback,
            ),
        )

    def submit_standing_orders(
        *,
        encounter_data,
        encounter_id,
        multi_pc_manager,
        path_manager,
        party_tracker_data,
        location_info,
        replan=False,
    ):
        world_conditions = (
            party_tracker_data.get("worldConditions", {})
            if isinstance(party_tracker_data, dict) else {}
        )
        active_encounter_id = (
            world_conditions.get("activeCombatEncounter")
            if isinstance(world_conditions, dict) else None
        )

        def prefetch_llm_call(task, messages, **kwargs):
            return llm.call(task, messages, **kwargs)

        return submit_tactical_prefetch_for_enemy_batch(
            encounter_data,
            encounter_id=encounter_id,
            multi_pc_manager=multi_pc_manager,
            monster_definitions=monster_definitions,
            path_manager=path_manager,
            read_json=safe_json_loader,
            scene_context={
                "location": location_info,
                "active_encounter_id": active_encounter_id,
                "combat_in_progress": active_encounter_id == encounter_id,
            },
            llm_call=prefetch_llm_call,
            receipt_observer_factory=make_legacy_receipt_observer,
            usage_tracking_available=USAGE_TRACKING_AVAILABLE,
            combat_main_model=COMBAT_MAIN_MODEL,
            replan=replan,
        )

    def submit_ally_orders(
        *,
        encounter_data,
        encounter_id,
        multi_pc_manager,
        path_manager,
        party_tracker_data,
        location_info,
        npc_profiles=None,
        conversation_history=None,
        trigger="initial",
    ):
        from core.combat.ally_prefetch import submit_ally_prefetch

        world_conditions = (
            party_tracker_data.get("worldConditions", {})
            if isinstance(party_tracker_data, dict) else {}
        )
        active_encounter_id = (
            world_conditions.get("activeCombatEncounter")
            if isinstance(world_conditions, dict) else None
        )

        def prefetch_llm_call(task, messages, **kwargs):
            return llm.call(task, messages, **kwargs)

        return submit_ally_prefetch(
            encounter_data,
            encounter_id=encounter_id,
            multi_pc_manager=multi_pc_manager,
            active_encounter_id=active_encounter_id,
            npc_profiles=npc_profiles,
            history=conversation_history,
            tactical_features=(
                location_info.get("tacticalFeatures")
                if isinstance(location_info, dict) else None
            ),
            llm_call=prefetch_llm_call,
            trigger=trigger,
            receipt_observer_factory=make_legacy_receipt_observer,
            usage_tracking_available=USAGE_TRACKING_AVAILABLE,
            combat_main_model=COMBAT_MAIN_MODEL,
        )

    return CombatNormalTurnDependencies(
        input_phase_gate=run_input_phase_gate,
        phase_gate_io_factory=phase_gate_io,
        initiative_gate=_handle_group_initiative_gate,
        fast_command_stage=run_fast_commands_stage,
        fast_command_io_factory=fast_command_io,
        deterministic_command_stage=run_deterministic_command_stage,
        deterministic_command_io_factory=deterministic_command_io,
        character_stat_command=run_character_stat_command,
        character_stat_io_factory=character_stat_io,
        normalize_character_name=normalize_character_name,
        safe_json_load=safe_json_loader,
        pc_action_enabled=COMBAT_PC_PHASE_NL_FAST_PATH,
        perf_counter=time.perf_counter,
        trace_decision=trace_decision,
        enhance_inventory_context=enhance_combat_input_with_inventory,
        enhance_player_input_with_inventory=enhance_player_input_with_inventory,
        assemble_context=assemble_context,
        clean_old_dm_notes=clean_old_dm_notes,
        clean_combat_state_blocks=clean_combat_state_blocks,
        save_json=save_json_file,
        debug=debug,
        emit=print,
        flush=sys.stdout.flush,
        submit_standing_orders=submit_standing_orders,
        submit_ally_prefetch=submit_ally_orders,
    )


def normalize_encounter_status(encounter_data):
    """Normalizes status values in encounter data to lowercase"""
    if not encounter_data or not isinstance(encounter_data, dict):
        return encounter_data

    # Convert status values to lowercase
    for creature in encounter_data.get('creatures', []):
        if 'status' in creature:
            creature['status'] = creature['status'].lower()

    return encounter_data


def normalize_phase1_initiative(encounter_data, party_tracker_data):
    """Normalize encounter initiative fields for Phase 1 two-group flow."""
    if not encounter_data or not isinstance(encounter_data, dict):
        return encounter_data, False, None

    world_conditions = {}
    if isinstance(party_tracker_data, dict):
        world_conditions = party_tracker_data.get("worldConditions", {}) or {}

    mirror = world_conditions.get("combatInitiative", {})
    if not isinstance(mirror, dict):
        mirror = {}

    changed = False
    rolls = encounter_data.get("initiativeRolls")
    if not isinstance(rolls, dict):
        rolls = {}

    dm_group = rolls.get("dmGroup")
    pc_group = rolls.get("pcGroup")
    initiative_winner = encounter_data.get("initiativeWinner")
    round_starts_with = encounter_data.get("roundStartsWith")
    awaiting_pc_group_roll = encounter_data.get("awaitingPcGroupRoll")

    if dm_group is None and mirror.get("enemyRoll") is not None:
        dm_group = mirror.get("enemyRoll")
        changed = True
    if pc_group is None and mirror.get("partyRoll") is not None:
        pc_group = mirror.get("partyRoll")
        changed = True

    if encounter_data.get("initiativeMode") != "two_group_phase1":
        encounter_data["initiativeMode"] = "two_group_phase1"
        changed = True

    if encounter_data.get("initiativeRolls") != {"dmGroup": dm_group, "pcGroup": pc_group}:
        encounter_data["initiativeRolls"] = {"dmGroup": dm_group, "pcGroup": pc_group}
        changed = True

    if initiative_winner not in ("pcGroup", "dmGroup"):
        party_goes_first = mirror.get("partyGoesFirst")
        if party_goes_first is True:
            initiative_winner = "pcGroup"
            changed = True
        elif party_goes_first is False:
            initiative_winner = "dmGroup"
            changed = True

    if round_starts_with not in ("pcGroup", "dmGroup") and initiative_winner in ("pcGroup", "dmGroup"):
        round_starts_with = initiative_winner
        changed = True

    current_round = encounter_data.get("combat_round", encounter_data.get("current_round", 1))
    try:
        current_round_value = int(current_round)
    except Exception:
        current_round_value = 1

    if current_round_value > 1:
        desired_awaiting = False
    elif initiative_winner in ("pcGroup", "dmGroup"):
        desired_awaiting = False
    else:
        desired_awaiting = True

    if awaiting_pc_group_roll != desired_awaiting:
        awaiting_pc_group_roll = desired_awaiting
        changed = True

    encounter_data["initiativeWinner"] = initiative_winner
    encounter_data["roundStartsWith"] = round_starts_with
    encounter_data["awaitingPcGroupRoll"] = awaiting_pc_group_roll

    party_goes_first_out = None
    if initiative_winner in ("pcGroup", "dmGroup"):
        party_goes_first_out = initiative_winner == "pcGroup"

    mirror_payload = {
        "partyRoll": pc_group,
        "enemyRoll": dm_group,
        "partyGoesFirst": party_goes_first_out,
    }

    return encounter_data, changed, mirror_payload

# TABLETOP MODE: Legacy adapter; implementation ownership is core.combat.turn.
def _handle_group_initiative_gate(cmd, encounter_data, multi_pc_manager, party_tracker_data):
    return handle_group_initiative_gate(
        cmd,
        encounter_data,
        multi_pc_manager,
        party_tracker_data,
        apply_opening_batch_marker=apply_opening_batch_marker,
        sync_available=COMBAT_STATE_SYNC_AVAILABLE,
    )

def get_initiative_order(encounter_data):
    """Generate initiative order string for combat validation context"""
    if not encounter_data or not isinstance(encounter_data, dict):
        return "Initiative order unknown"

    creatures = encounter_data.get("creatures", [])
    if not creatures:
        return "No creatures in encounter"

    # Filter out dead creatures - they should not be in the initiative order
    active_creatures = [c for c in creatures if c.get("status", "unknown").lower() != "dead"]

    if not active_creatures:
        return "All creatures are dead"

    # Sort by initiative (descending), then alphabetically for ties
    sorted_creatures = sorted(active_creatures, key=lambda x: (-x.get("initiative", 0), x.get("name", "")))

    order_parts = []
    for creature in sorted_creatures:
        name = creature.get("name", "Unknown")
        initiative = creature.get("initiative", 0)
        status = creature.get("status", "unknown")
        order_parts.append(f"{name} ({initiative}, {status})")

    return " -> ".join(order_parts)

def log_conversation_structure(conversation):
    """Log the structure of the conversation history for debugging"""
    debug("VALIDATION: Conversation Structure:", category="combat_validation")
    debug(f"Total messages: {len(conversation)}", category="combat_validation")

    roles = {}
    for i, msg in enumerate(conversation):
        role = msg.get("role", "unknown")
        content_preview = msg.get("content", "")[:50].replace("\n", " ") + "..."
        roles[role] = roles.get(role, 0) + 1
        debug(f"  [{i}] {role}: {content_preview}", category="combat_validation")

    debug("Message count by role:", category="combat_validation")
    for role, count in roles.items():
        debug(f"  {role}: {count}", category="combat_validation")
    # Empty line for debug output


def summarize_dialogue(conversation_history_param, location_data, party_tracker_data):
    debug("AI_CALL: Activating the third model...", category="ai_operations")

    # Extract clean narrative content from conversation history
    clean_conversation = []
    for message in conversation_history_param:
        if message.get("role") == "system":
            continue  # Skip system messages
        elif message.get("role") == "user":
            clean_conversation.append(f"Player: {message.get('content', '')}")
        elif message.get("role") == "assistant":
            content = message.get("content", "")

            # Check for the special "Combat Summary:" message format first
            if content.strip().startswith("Combat Summary:"):
                # Extract the JSON part of the string by removing the prefix
                json_part = content.replace("Combat Summary:", "").strip()
                try:
                    parsed = json.loads(json_part)
                    if isinstance(parsed, dict) and "narration" in parsed:
                        # We found the final summary, use its clean narration
                        clean_conversation.append(f"Dungeon Master: {parsed['narration']}")
                    else:
                        # The content after the prefix was not the expected JSON, use the raw content
                        clean_conversation.append(f"Dungeon Master: {content}")
                except json.JSONDecodeError:
                    # If parsing the JSON part fails, use the raw content as fallback
                    clean_conversation.append(f"Dungeon Master: {content}")
            else:
                # This is a normal combat turn response, not the final summary
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "narration" in parsed:
                        clean_conversation.append(f"Dungeon Master: {parsed['narration']}")
                    else:
                        clean_conversation.append(f"Dungeon Master: {content}")
                except json.JSONDecodeError:
                    # If it's not JSON (e.g., an error message), use the raw content
                    clean_conversation.append(f"Dungeon Master: {content}")

    clean_text = "\n\n".join(clean_conversation)

    dialogue_summary_prompt = [
        {"role": "system", "content": "Your task is to create a vivid, colorful narrative summary of this combat encounter. Capture the dramatic highs and lows - critical hits, narrow misses, clever tactics, desperate moments, and heroic actions. Write it as an exciting story paragraph that captures the flow and feel of the battle. Include: the initial setup, key turning points, memorable moments, the final blow, total XP awarded, and what remains after combat (defeated foes, environmental changes). Write in past tense as a complete narrative summary, not a play-by-play. Make it engaging and memorable - this will be the permanent record of this battle."},
        {"role": "user", "content": clean_text}
    ]

    # Generate dialogue summary
    observer = make_legacy_receipt_observer(
        endpoint_name="combat_summary",
        messages=dialogue_summary_prompt,
        legacy_context={"temperature": TEMPERATURE, "context": "dialogue_summary"},
        trace_site="combat_dialogue_summary",
        track_usage=USAGE_TRACKING_AVAILABLE,
        api_log_before_tracker=True,
    )
    dialogue_summary = llm.call(
        task="combat_summary",
        messages=dialogue_summary_prompt,
        json_output=False,
        temperature=TEMPERATURE,
        observer=observer,
    ).strip()

    # Extract just the narration if the AI returned JSON
    try:
        parsed_summary = json.loads(dialogue_summary)
        if isinstance(parsed_summary, dict) and "narration" in parsed_summary:
            dialogue_summary = parsed_summary["narration"]
            debug("Extracted narration from JSON combat summary", category="combat_summary")
    except (json.JSONDecodeError, KeyError):
        # Not JSON or doesn't have narration field, use as-is
        pass

    current_location_id = party_tracker_data["worldConditions"]["currentLocationId"]
    debug(f"STATE_CHANGE: Current location ID: {current_location_id}", category="encounter_setup")

    if location_data and location_data.get("locationId") == current_location_id:
        encounter_id = party_tracker_data["worldConditions"].get("activeCombatEncounter", "")

        # Debug to identify why encounter_id might be empty
        debug(f"[summarize_dialogue] Retrieved activeCombatEncounter ID: '{encounter_id}'", category="encounter_setup")
        if not encounter_id:
            error("[summarize_dialogue] activeCombatEncounter ID is EMPTY or None. This is the cause of missing encounter IDs.", category="encounter_setup")
            # Try to generate a fallback ID if missing
            existing_encounters = location_data.get("encounters", [])
            next_num = len(existing_encounters) + 1
            encounter_id = f"{current_location_id}-E{next_num}"
            warning(f"[summarize_dialogue] Generated fallback encounter ID: {encounter_id}", category="encounter_setup")

        new_encounter = {
            "encounterId": encounter_id,
            "summary": dialogue_summary,
            "impact": "To be determined",
            "worldConditions": {
                "year": int(party_tracker_data["worldConditions"]["year"]),
                "month": party_tracker_data["worldConditions"]["month"],
                "day": int(party_tracker_data["worldConditions"]["day"]),
                "time": party_tracker_data["worldConditions"]["time"]
            }
        }
        if "encounters" not in location_data:
            location_data["encounters"] = []
        location_data["encounters"].append(new_encounter)
        # adventureSummary field is deprecated - no longer updated to prevent data bloat

        from utils.module_path_manager import ModulePathManager
        from utils.encoding_utils import safe_json_load
        # Get current module from party tracker for consistent path resolution
        try:
            party_tracker = safe_json_load("party_tracker.json")
            current_module = party_tracker.get("module", "").replace(" ", "_") if party_tracker else None
            path_manager = ModulePathManager(current_module)
        except Exception as exc:
            warning(f"FILE_OP: Could not resolve area module for encounter summary: {exc}", category="file_operations")
            path_manager = ModulePathManager()  # Fallback to reading from file
        current_area_id = get_current_area_id()
        area_file = path_manager.get_area_path(current_area_id)
        area_data = safe_json_load(area_file)
        if not area_data:
            error(f"FILE_OP: Failed to load area file: {area_file}", category="file_operations")
            return dialogue_summary

        for i, loc in enumerate(area_data["locations"]):
            if loc["locationId"] == current_location_id:
                area_data["locations"][i] = location_data
                break

        if not safe_write_json(area_file, area_data):
            error(f"FILE_OP: Failed to save area file: {area_file}", category="file_operations")
        debug(f"STATE_CHANGE: Encounter {encounter_id} added to {area_file}.", category="encounter_setup")

        conversation_history_param.append({"role": "assistant", "content": f"Combat Summary: {dialogue_summary}"})
        conversation_history_param.append({"role": "user", "content": "The combat has concluded. What would you like to do next?"})

        debug(f"FILE_OP: Attempting to write to file: {conversation_history_file}", category="file_operations")
        if not safe_write_json(conversation_history_file, conversation_history_param):
            error("FILE_OP: Failed to save conversation history", category="file_operations")
        else:
            debug("FILE_OP: Conversation history saved successfully", category="file_operations")
        info("SUCCESS: Conversation history updated with encounter summary.", category="combat_events")
    else:
        error(f"VALIDATION: Location {current_location_id} not found in location data or location data is incorrect.", category="combat_events")
    return dialogue_summary

def merge_updates(original_data, updated_data):
    fields_to_update = ['hitPoints', 'equipment', 'attacksAndSpellcasting', 'experience_points']

    for field in fields_to_update:
        if field in updated_data:
            if field in ['equipment', 'attacksAndSpellcasting']:
                # For arrays, replace the entire array
                original_data[field] = updated_data[field]
            elif field == 'experience_points':
                # For XP, only update if the new value is greater than the existing value
                if updated_data[field] > original_data.get(field, 0):
                    original_data[field] = updated_data[field]
            else:
                # For simple fields like hitpoints, just update the value
                original_data[field] = updated_data[field]

    return original_data

# DEPRECATED: This function is no longer used and has been replaced by the new XP awarding system
# that uses update_character_info directly with proper synchronization.
# The new system:
# 1. Awards XP through update_character_info with "Awarded X experience points" message
# 2. Uses atomic file operations with proper locking
# 3. Has XP protection to prevent reduction
# 4. Includes comprehensive debug logging
# Keeping this function for reference only - DO NOT USE
def update_json_schema(ai_response, player_info, encounter_data, party_tracker_data):
    # This old function tried to extract XP from AI responses and update characters
    # It has been replaced by the more robust XP awarding system in the main combat loop
    warning("DEPRECATED: update_json_schema called but is no longer used", category="xp_tracking")
    return player_info  # Return unchanged data

def generate_chat_history(conversation_history, encounter_id):
    """
    Generate a lightweight combat chat history without system messages
    for a specific encounter ID
    """
    # Create a formatted timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime(HISTORY_TIMESTAMP_FORMAT)

    # Create directory for this encounter if it doesn't exist
    encounter_dir = f"combat_logs/{encounter_id}"
    os.makedirs(encounter_dir, exist_ok=True)

    # Create a unique filename based on encounter ID and timestamp
    output_file = f"{encounter_dir}/combat_chat_{timestamp}.json"

    try:
        # Filter out system messages and keep only user and assistant messages
        chat_history = [msg for msg in conversation_history if msg["role"] != "system"]

        # Write the filtered chat history to the output file
        if not safe_write_json(output_file, chat_history):
            error(f"FILE_OP: Failed to save chat history to {output_file}", category="file_operations")

        # Print statistics
        system_count = len(conversation_history) - len(chat_history)
        total_count = len(conversation_history)
        user_count = sum(1 for msg in chat_history if msg["role"] == "user")
        assistant_count = sum(1 for msg in chat_history if msg["role"] == "assistant")

        info("SUCCESS: Combat chat history updated!", category="combat_events")
        debug(f"Encounter ID: {encounter_id}", category="combat_events")
        debug(f"System messages removed: {system_count}", category="combat_events")
        debug(f"SUMMARY: User messages: {user_count}", category="combat_logs")
        debug(f"SUMMARY: Assistant messages: {assistant_count}", category="combat_logs")
        debug(f"SUMMARY: Total messages (including system): {total_count}", category="combat_logs")
        info(f"SUCCESS: Output saved to: {output_file}", category="combat_logs")

        # Also create/update the latest version of this encounter for easy reference
        latest_file = f"{encounter_dir}/combat_chat_latest.json"
        if not safe_write_json(latest_file, chat_history):
            error("FILE_OP: Failed to save latest chat history", category="file_operations")
        info(f"SUCCESS: Latest version also saved to: {latest_file}", category="combat_logs")

        # Save a combined latest file for all encounters as well
        all_latest_file = f"combat_logs/all_combat_latest.json"
        try:
            # Load existing all-combat history if it exists
            if os.path.exists(all_latest_file):
                with open(all_latest_file, "r", encoding="utf-8") as f:
                    all_combat_data = json.load(f)
            else:
                all_combat_data = {}

            # Add or update this encounter's data
            all_combat_data[encounter_id] = {
                "timestamp": timestamp,
                "messageCount": len(chat_history),
                "history": chat_history
            }

            # Write the combined file
            with open(all_latest_file, "w", encoding="utf-8") as f:
                json.dump(all_combat_data, f, indent=2)

        except Exception as e:
            error(f"FAILURE: Error updating combined combat log", exception=e, category="combat_logs")

    except Exception as e:
        error(f"FAILURE: Error generating combat chat history", exception=e, category="combat_logs")

def sync_active_encounter(
    party_tracker_data: Dict[str, Any],
    session: CombatSession,
    turn_identity: int,
    *,
    force: bool = False,
):
    """Synchronize character state into the active encounter at most once per turn."""
    try:
        if not session.claim_active_encounter_sync(turn_identity, force=force):
            debug(
                f"Skipping duplicate active encounter sync for turn {turn_identity}",
                category="encounter_setup",
            )
            return

        if not isinstance(party_tracker_data, dict) or not party_tracker_data:
            error("FAILURE: Failed to load party_tracker.json", category="file_operations")
            return

        from utils.module_path_manager import ModulePathManager

        # Use the turn-start snapshot for both module resolution and encounter identity.
        module_name = party_tracker_data.get("module")
        if not isinstance(module_name, str) or not module_name.strip():
            module_name = "Keep_of_Doom"
        current_module = module_name.replace(" ", "_")
        try:
            path_manager = ModulePathManager(current_module)
        except Exception as exc:
            warning(
                f"FILE_OP: Could not resolve module for active encounter sync: {exc}",
                category="file_operations",
            )
            path_manager = ModulePathManager("Keep_of_Doom")

        active_encounter_id = party_tracker_data.get("worldConditions", {}).get(
            "activeCombatEncounter", ""
        )
        if not active_encounter_id:
            return

        encounter_file = f"modules/encounters/encounter_{active_encounter_id}.json"
        encounter_data = safe_json_load(encounter_file)
        if not encounter_data:
            error(f"FAILURE: Failed to load encounter file: {encounter_file}", category="file_operations")
            return {}

        # The loaded object is the authoritative persisted baseline. Canonicalize it
        # before mutation so a no-op sync performs neither an atomic write nor a trace.
        persisted_state = json.dumps(
            encounter_data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

        for creature in encounter_data.get("creatures", []):
            if creature["type"] == "player":
                player_file = path_manager.get_character_path(normalize_character_name(creature["name"]))
                try:
                    player_data = safe_json_load(player_file)
                    if not player_data:
                        error(f"FAILURE: Failed to load player file: {player_file}", category="file_operations")
                    else:
                        player_data = normalize_life_state_fields(player_data)
                        if creature.get("currentHitPoints") != player_data.get("hitPoints"):
                            creature["currentHitPoints"] = player_data.get("hitPoints")
                        if creature.get("maxHitPoints") != player_data.get("maxHitPoints"):
                            creature["maxHitPoints"] = player_data.get("maxHitPoints")
                        if creature.get("status") != player_data.get("status"):
                            creature["status"] = player_data.get("status")
                        if creature.get("conditions") != player_data.get("condition_affected"):
                            creature["conditions"] = player_data.get("condition_affected", [])
                except Exception as exc:
                    error("FAILURE: Failed to sync player data to encounter", exception=exc, category="encounter_setup")

            elif creature["type"] == "npc":
                try:
                    npc_data, _matched_filename = load_npc_with_fuzzy_match(creature["name"], path_manager)
                    if not npc_data:
                        error(f"FAILURE: Failed to load NPC file for: {creature['name']}", category="file_operations")
                    else:
                        npc_data = normalize_life_state_fields(npc_data)
                        if creature.get("currentHitPoints") != npc_data.get("hitPoints"):
                            creature["currentHitPoints"] = npc_data.get("hitPoints")
                        if creature.get("maxHitPoints") != npc_data.get("maxHitPoints"):
                            creature["maxHitPoints"] = npc_data.get("maxHitPoints")
                        if creature.get("status") != npc_data.get("status"):
                            creature["status"] = npc_data.get("status")
                        if creature.get("conditions") != npc_data.get("condition_affected"):
                            creature["conditions"] = npc_data.get("condition_affected", [])
                except Exception as exc:
                    error("FAILURE: Failed to sync NPC data to encounter", exception=exc, category="encounter_setup")

        synchronized_state = json.dumps(
            encounter_data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if synchronized_state == persisted_state:
            return

        if not safe_write_json(encounter_file, encounter_data):
            error(f"FAILURE: Failed to save encounter file: {encounter_file}", category="file_operations")
        else:
            # TABLETOP MODE: Notify only after the canonical encounter mirror
            # has been written successfully.
            from utils.player_host_publication import submit_player_host_change

            submit_player_host_change("combat")
            trace_file_operation("write", "active_encounter_sync")
        debug(
            f"SUCCESS: Active encounter {active_encounter_id} synced with latest character data",
            category="encounter_setup",
        )
    except Exception as exc:
        error("FAILURE: Error in sync_active_encounter", exception=exc, category="encounter_setup")

def filter_dynamic_fields(data):
    """Remove dynamic combat fields from character/monster data for system prompts"""
    dynamic_fields = ['hitPoints', 'maxHitPoints', 'status', 'condition', 'condition_affected',
                     'temporaryEffects', 'currentHitPoints']
    return {k: v for k, v in data.items() if k not in dynamic_fields}

def format_character_for_combat(char_data, char_type="player", role=None):
    """
    Format character data (player or NPC) for combat system prompts using the same format as conversation_utils.
    This ensures consistency between main conversation and combat systems.
\x20\x20\x20\x20
    Args:
        char_data: The character's data dictionary
        char_type: "player" or "npc"
        role: Optional role description (mainly for NPCs)
\x20\x20\x20\x20
    Returns:
        Formatted string matching conversation_utils format
    """
    if isinstance(char_data, dict):
        char_data = normalize_life_state_fields(dict(char_data))

    # Get equipment string - include ALL items with quantities (not just equipped)
    # Don't include item type in parentheses for combat - wastes tokens
    equipment_str = "None"
    if char_data.get('equipment'):
        equipment_list = []
        for item in char_data['equipment']:
            item_description = item['item_name']
            if item.get('quantity', 1) > 1:
                item_description = f"{item_description} x{item['quantity']}"
            equipment_list.append(item_description)
        if equipment_list:
            equipment_str = ", ".join(equipment_list)

    # Get background feature name
    bg_feature_name = "None"
    bg_feature = char_data.get('backgroundFeature', {})
    if bg_feature and isinstance(bg_feature, dict):
        bg_feature_name = bg_feature.get('name', 'None')

    # Determine header based on type
    if char_type == "player":
        header = f"CHAR: {char_data.get('name', 'Unknown')}"
        type_line = f"TYPE: {char_data.get('character_type', 'player').capitalize()}"
    else:
        header = f"NPC: {char_data.get('name', 'Unknown')}"
        type_line = f"ROLE: {role if role else 'Adventurer'} | TYPE: {char_data.get('character_type', 'npc').capitalize()}"

    # Calculate skill modifiers for display
    skills_display = ""
    skills_field = char_data.get('skills', {})
    if isinstance(skills_field, dict):
        # Legacy format - use pre-calculated values
        skills_display = ', '.join(f"{skill} +{bonus}" if bonus >= 0 else f"{skill} {bonus}"
                                 for skill, bonus in skills_field.items())
    elif isinstance(skills_field, list):
        # Array format - calculate modifiers for proficient skills
        skill_abilities = {
            'Acrobatics': 'dexterity', 'Animal Handling': 'wisdom',
            'Arcana': 'intelligence', 'Athletics': 'strength',
            'Deception': 'charisma', 'History': 'intelligence',
            'Insight': 'wisdom', 'Intimidation': 'charisma',
            'Investigation': 'intelligence', 'Medicine': 'wisdom',
            'Nature': 'intelligence', 'Perception': 'wisdom',
            'Performance': 'charisma', 'Persuasion': 'charisma',
            'Religion': 'intelligence', 'Sleight of Hand': 'dexterity',
            'Stealth': 'dexterity', 'Survival': 'wisdom'
        }

        skill_displays = []
        abilities = char_data.get('abilities', {})
        prof_bonus = char_data.get('proficiencyBonus', 2)

        for skill in skills_field:
            if skill in skill_abilities:
                ability_name = skill_abilities[skill]
                ability_score = abilities.get(ability_name, 10)
                ability_mod = (ability_score - 10) // 2
                modifier = ability_mod + prof_bonus
                if modifier >= 0:
                    skill_displays.append(f"{skill} +{modifier}")
                else:
                    skill_displays.append(f"{skill} {modifier}")
        skills_display = ', '.join(skill_displays) if skill_displays else 'none'
    else:
        skills_display = 'none'

    # Build the formatted string (exactly matching conversation_utils format)
    formatted_data = f"""{header}
{type_line} | LVL: {char_data.get('level', 1)} | RACE: {char_data.get('race', 'Unknown')} | CLASS: {char_data.get('class', 'Unknown')} | ALIGN: {char_data.get('alignment', 'neutral')[:2].upper()} | BG: {char_data.get('background', 'None')}
AC: {char_data.get('armorClass', 10)} | SPD: {char_data.get('speed', 30)}
STATUS: {char_data.get('status', 'alive')} | CONDITION: {char_data.get('condition', 'none')} | AFFECTED: {', '.join(char_data.get('condition_affected', []))}
STATS: STR {char_data.get('abilities', {}).get('strength', 10)}, DEX {char_data.get('abilities', {}).get('dexterity', 10)}, CON {char_data.get('abilities', {}).get('constitution', 10)}, INT {char_data.get('abilities', {}).get('intelligence', 10)}, WIS {char_data.get('abilities', {}).get('wisdom', 10)}, CHA {char_data.get('abilities', {}).get('charisma', 10)}
SAVES: {', '.join(char_data.get('savingThrows', []))}
SKILLS: {skills_display}
PROF BONUS: +{char_data.get('proficiencyBonus', 2)}
SENSES: {', '.join(f"{sense} {value}" for sense, value in char_data.get('senses', {}).items())}
LANGUAGES: {', '.join(char_data.get('languages', ['Common']))}
PROF: {', '.join([f"{cat}: {', '.join(items) if items else 'none'}" for cat, items in char_data.get('proficiencies', {}).items()])}
VULN: {', '.join(char_data.get('damageVulnerabilities', []))}
RES: {', '.join(char_data.get('damageResistances', []))}
IMM: {', '.join(char_data.get('damageImmunities', []))}
COND IMM: {', '.join(char_data.get('conditionImmunities', []))}
RACIAL: {', '.join([t['name'] for t in char_data.get('racialTraits', [])])}
BG FEAT: {bg_feature_name}
FEATS: {', '.join([f['name'] for f in char_data.get('feats', [])])}
TEMP FX: {', '.join([e['name'] for e in char_data.get('temporaryEffects', [])])}
EQUIP: {equipment_str}
AMMO: {', '.join([f"{a['name']} x{a['quantity']}" for a in char_data.get('ammunition', [])])}
ATK: {', '.join([f"{a['name']} ({a.get('type', 'melee')}, {a.get('damageDice', '1d4')} {a.get('damageType', 'bludgeoning')})" for a in char_data.get('attacksAndSpellcasting', [])])}"""

    supernatural_summary = get_supernatural_state_summary(char_data, include_effects=True)
    if supernatural_summary:
        formatted_data += f"""
SUPERNATURAL: {supernatural_summary}"""

    # Add spellcasting if present
    spellcasting = char_data.get('spellcasting', {})
    if spellcasting:
        formatted_data += f"""
SPELLCASTING: {spellcasting.get('ability', 'N/A')} | DC: {spellcasting.get('spellSaveDC', 'N/A')} | ATK: +{spellcasting.get('spellAttackBonus', 'N/A')}
SPELLS: {', '.join([f"{level}: {', '.join(spells)}" for level, spells in spellcasting.get('spells', {}).items() if spells])}"""

    # Add currency
    currency = char_data.get('currency', {})
    if currency:
        formatted_data += f"""
CURRENCY: {currency.get('gold', 0)}G, {currency.get('silver', 0)}S, {currency.get('copper', 0)}C"""

    # Add XP
    if 'experience_points' in char_data:
        formatted_data += f"""
XP: {char_data['experience_points']}/{char_data.get('exp_required_for_next_level', 'N/A')}"""

    # Add personality traits
    if char_data.get('personality_traits'):
        formatted_data += f"""
TRAITS: {char_data['personality_traits']}"""

    if char_data.get('ideals'):
        formatted_data += f"""
IDEALS: {char_data['ideals']}"""

    if char_data.get('bonds'):
        formatted_data += f"""
BONDS: {char_data['bonds']}"""

    if char_data.get('flaws'):
        formatted_data += f"""
FLAWS: {char_data['flaws']}"""

    # Add backstory context when present (bounded)
    if char_data.get('backstory'):
        backstory_display = str(char_data['backstory'])[:120]
        formatted_data += f"""
BACKSTORY: {backstory_display}"""

    return formatted_data

def format_npc_for_combat(npc_data, npc_role=None):
    """
    Format NPC data for combat system prompts using the same format as conversation_utils.
    This ensures consistency between main conversation and combat systems.
\x20\x20\x20\x20
    Args:
        npc_data: The NPC's character data dictionary
        npc_role: Optional role description from party tracker
\x20\x20\x20\x20
    Returns:
        Formatted string matching conversation_utils format
    """
    # Get equipment string - include ALL items with quantities (not just equipped)
    # Don't include item type in parentheses for combat - wastes tokens
    equipment_str = "None"
    if npc_data.get('equipment'):
        equipment_list = []
        for item in npc_data['equipment']:
            item_description = item['item_name']
            if item.get('quantity', 1) > 1:
                item_description = f"{item_description} x{item['quantity']}"
            equipment_list.append(item_description)
        if equipment_list:
            equipment_str = ", ".join(equipment_list)

    # Get background feature name
    bg_feature_name = "None"
    bg_feature = npc_data.get('backgroundFeature', {})
    if bg_feature and isinstance(bg_feature, dict):
        bg_feature_name = bg_feature.get('name', 'None')

    # Calculate skill modifiers for NPC display
    npc_skills_display = ""
    skills_field = npc_data.get('skills', {})
    if isinstance(skills_field, dict):
        # NPCs typically use dict format with pre-calculated values
        npc_skills_display = ', '.join(f"{skill} +{bonus}" if bonus >= 0 else f"{skill} {bonus}"
                                     for skill, bonus in skills_field.items())
    elif isinstance(skills_field, list):
        # In case NPCs use array format, calculate modifiers
        skill_abilities = {
            'Acrobatics': 'dexterity', 'Animal Handling': 'wisdom',
            'Arcana': 'intelligence', 'Athletics': 'strength',
            'Deception': 'charisma', 'History': 'intelligence',
            'Insight': 'wisdom', 'Intimidation': 'charisma',
            'Investigation': 'intelligence', 'Medicine': 'wisdom',
            'Nature': 'intelligence', 'Perception': 'wisdom',
            'Performance': 'charisma', 'Persuasion': 'charisma',
            'Religion': 'intelligence', 'Sleight of Hand': 'dexterity',
            'Stealth': 'dexterity', 'Survival': 'wisdom'
        }

        skill_displays = []
        abilities = npc_data.get('abilities', {})
        prof_bonus = npc_data.get('proficiencyBonus', 2)

        for skill in skills_field:
            if skill in skill_abilities:
                ability_name = skill_abilities[skill]
                ability_score = abilities.get(ability_name, 10)
                ability_mod = (ability_score - 10) // 2
                modifier = ability_mod + prof_bonus
                if modifier >= 0:
                    skill_displays.append(f"{skill} +{modifier}")
                else:
                    skill_displays.append(f"{skill} {modifier}")
        npc_skills_display = ', '.join(skill_displays) if skill_displays else 'none'
    else:
        npc_skills_display = 'none'

    # Build the formatted string (exactly matching conversation_utils format)
    formatted_data = f"""NPC: {npc_data.get('name', 'Unknown')}
ROLE: {npc_role if npc_role else 'Adventurer'} | TYPE: {npc_data.get('character_type', 'npc').capitalize()} | LVL: {npc_data.get('level', 1)} | RACE: {npc_data.get('race', 'Unknown')} | CLASS: {npc_data.get('class', 'Unknown')} | ALIGN: {npc_data.get('alignment', 'neutral')[:2].upper()} | BG: {npc_data.get('background', 'None')}
AC: {npc_data.get('armorClass', 10)} | SPD: {npc_data.get('speed', 30)}
STATUS: {npc_data.get('status', 'alive')} | CONDITION: {npc_data.get('condition', 'none')} | AFFECTED: {', '.join(npc_data.get('condition_affected', []))}
STATS: STR {npc_data.get('abilities', {}).get('strength', 10)}, DEX {npc_data.get('abilities', {}).get('dexterity', 10)}, CON {npc_data.get('abilities', {}).get('constitution', 10)}, INT {npc_data.get('abilities', {}).get('intelligence', 10)}, WIS {npc_data.get('abilities', {}).get('wisdom', 10)}, CHA {npc_data.get('abilities', {}).get('charisma', 10)}
SAVES: {', '.join(npc_data.get('savingThrows', []))}
SKILLS: {npc_skills_display}
PROF BONUS: +{npc_data.get('proficiencyBonus', 2)}
SENSES: {', '.join(f"{sense} {value}" for sense, value in npc_data.get('senses', {}).items())}
LANGUAGES: {', '.join(npc_data.get('languages', ['Common']))}
PROF: {', '.join([f"{cat}: {', '.join(items) if items else 'none'}" for cat, items in npc_data.get('proficiencies', {}).items()])}
VULN: {', '.join(npc_data.get('damageVulnerabilities', []))}
RES: {', '.join(npc_data.get('damageResistances', []))}
IMM: {', '.join(npc_data.get('damageImmunities', []))}
COND IMM: {', '.join(npc_data.get('conditionImmunities', []))}
RACIAL: {', '.join([t['name'] for t in npc_data.get('racialTraits', [])])}
BG FEAT: {bg_feature_name}
FEATS: {', '.join([f['name'] for f in npc_data.get('feats', [])])}
TEMP FX: {', '.join([e['name'] for e in npc_data.get('temporaryEffects', [])])}
EQUIP: {equipment_str}
AMMO: {', '.join([f"{a['name']} x{a['quantity']}" for a in npc_data.get('ammunition', [])])}
ATK: {', '.join([f"{a['name']} ({a.get('type', 'melee')}, {a.get('damageDice', '1d4')} {a.get('damageType', 'bludgeoning')})" for a in npc_data.get('attacksAndSpellcasting', [])])}"""

    supernatural_summary = get_supernatural_state_summary(npc_data, include_effects=True)
    if supernatural_summary:
        formatted_data += f"""
SUPERNATURAL: {supernatural_summary}"""

    # Add spellcasting if present
    spellcasting = npc_data.get('spellcasting', {})
    if spellcasting:
        formatted_data += f"""
SPELLCASTING: {spellcasting.get('ability', 'N/A')} | DC: {spellcasting.get('spellSaveDC', 'N/A')} | ATK: +{spellcasting.get('spellAttackBonus', 'N/A')}
SPELLS: {', '.join([f"{level}: {', '.join(spells)}" for level, spells in spellcasting.get('spells', {}).items() if spells])}"""

    # Add currency
    currency = npc_data.get('currency', {})
    if currency:
        formatted_data += f"""
CURRENCY: {currency.get('gold', 0)}G, {currency.get('silver', 0)}S, {currency.get('copper', 0)}C"""

    # Add XP
    if 'experience_points' in npc_data:
        formatted_data += f"""
XP: {npc_data['experience_points']}/{npc_data.get('exp_required_for_next_level', 'N/A')}"""

    # Add personality traits
    if npc_data.get('personality_traits'):
        formatted_data += f"""
TRAITS: {npc_data['personality_traits']}"""

    if npc_data.get('ideals'):
        formatted_data += f"""
IDEALS: {npc_data['ideals']}"""

    if npc_data.get('bonds'):
        formatted_data += f"""
BONDS: {npc_data['bonds']}"""

    if npc_data.get('flaws'):
        formatted_data += f"""
FLAWS: {npc_data['flaws']}"""

    # Add backstory context when present (bounded)
    if npc_data.get('backstory'):
        backstory_display = str(npc_data['backstory'])[:120]
        formatted_data += f"""
BACKSTORY: {backstory_display}"""

    return formatted_data

def filter_encounter_for_system_prompt(encounter_data):
    """Create minimal encounter data for system prompt with only essential fields"""
    if not encounter_data or not isinstance(encounter_data, dict):
        return encounter_data

    # Create minimal structure with only essential fields
    minimal_data = {
        "encounterId": encounter_data.get("encounterId"),
        "encounterSummary": encounter_data.get("encounterSummary", ""),
        "creatures": []
    }

    # Process each creature to keep only essential fields
    for creature in encounter_data.get("creatures", []):
        minimal_creature = {
            "name": creature.get("name")
        }

        # Add type information
        if creature.get("type"):
            minimal_creature["type"] = creature["type"]

        # Add monster/npc specific type info
        if creature.get("monsterType"):
            minimal_creature["monsterType"] = creature["monsterType"]
        if creature.get("npcType"):
            minimal_creature["npcType"] = creature["npcType"]

        # Add armor class for all creatures (important for combat)
        if "armorClass" in creature:
            minimal_creature["armorClass"] = creature["armorClass"]

        # Add conditions (will be important when not empty)
        if "conditions" in creature and creature["conditions"]:
            minimal_creature["conditions"] = creature["conditions"]

        # Add actions (even though currently bugged and empty)
        if "actions" in creature:
            minimal_creature["actions"] = creature["actions"]

        minimal_data["creatures"].append(minimal_creature)

    debug("STATE_CHANGE: Created minimal encounter data for system prompt", category="combat_events")
    return minimal_data

_MAX_DETERMINISTIC_EVENT_CHARS = 240
_MAX_DETERMINISTIC_EVENTS = 24


def _combat_history_round_marker(message):
    """Return a round marker carried by a combat history message, if any."""
    content = message.get("content", "")
    if not isinstance(content, str):
        return None
    match = None
    if message.get("role") == "user":
        match = re.search(r"COMBAT ROUND (\d+)", content)
        if not match:
            match = re.search(r"combat_round:\s*(\d+)", content)
    elif message.get("role") == "assistant" and '"combat_round"' in content:
        match = re.search(r'\{.*"combat_round"\s*:\s*(\d+).*\}', content, re.DOTALL)
    return int(match.group(1)) if match else None


def _deterministic_combat_round_summary(round_num, round_messages):
    """Build a bounded, provider-free summary from committed mechanical logs."""
    applied_events = []
    for message in round_messages:
        content = message.get("content", "")
        if not isinstance(content, str):
            continue
        for line in content.splitlines():
            lowered = line.lower()
            if "[already_applied]" not in lowered and "[system:" not in lowered:
                continue
            applied_events.append(line[:_MAX_DETERMINISTIC_EVENT_CHARS])
            if len(applied_events) >= _MAX_DETERMINISTIC_EVENTS:
                break
        if len(applied_events) >= _MAX_DETERMINISTIC_EVENTS:
            break
    return {
        "role": "assistant",
        "content": f"COMBAT ROUND {round_num} SUMMARY:\n" + json.dumps(
            {"round": round_num, "deterministic": True, "applied_events": applied_events},
            indent=2,
            ensure_ascii=True,
        ),
    }


def _combat_round_summary_message(round_num, round_messages, *, use_llm):
    """Use at most the chosen boundary LLM summary, with deterministic fallback."""
    if use_llm:
        try:
            summary = generate_combat_round_summary(round_num, round_messages)
            if summary:
                return {
                    "role": "assistant",
                    "content": f"COMBAT ROUND {round_num} SUMMARY:\n{json.dumps(summary, indent=2)}",
                }
        except Exception as exc:
            debug(
                f"COMPRESSION: Boundary summary failed for round {round_num}; using deterministic summary: {exc}",
                category="combat_events",
            )
    return _deterministic_combat_round_summary(round_num, round_messages)


def compress_old_combat_rounds(conversation_history, current_round, keep_recent_rounds=1):
    """Summarize one boundary round and deterministically replace older rounds."""
    try:
        debug(f"COMPRESSION: Called with current_round={current_round}, keep_recent_rounds={keep_recent_rounds}", category="combat_events")
        debug(f"COMPRESSION: Conversation history has {len(conversation_history)} messages", category="combat_events")

        if current_round <= keep_recent_rounds + 1:
            debug(f"COMPRESSION: Skipping - too early (round {current_round} <= {keep_recent_rounds + 1})", category="combat_events")
            return conversation_history

        eligible_rounds = range(1, current_round - keep_recent_rounds)
        rounds_to_compress = []
        for round_num in eligible_rounds:
            if any(
                msg.get("role") == "assistant"
                and f"COMBAT ROUND {round_num} SUMMARY:" in msg.get("content", "")
                for msg in conversation_history
            ):
                debug(f"COMPRESSION: Round {round_num} already compressed", category="combat_events")
            else:
                rounds_to_compress.append(round_num)

        if not rounds_to_compress:
            debug("COMPRESSION: No rounds need compression", category="combat_events")
            return conversation_history

        debug(f"COMPRESSION: Replacing rounds {rounds_to_compress}", category="combat_events")
        round_boundaries = {}
        current_tracking_round = None
        eligible_round_set = set(rounds_to_compress)
        for index, message in enumerate(conversation_history):
            marker_round = _combat_history_round_marker(message)
            if marker_round is not None:
                current_tracking_round = marker_round if marker_round in eligible_round_set else None
                if current_tracking_round is not None:
                    round_boundaries.setdefault(current_tracking_round, []).append(index)
                continue
            if current_tracking_round is not None:
                round_boundaries[current_tracking_round].append(index)

        boundary_round = current_round - keep_recent_rounds - 1
        summary_messages = {}
        for round_num, indices in round_boundaries.items():
            round_messages = [conversation_history[index] for index in indices]
            summary_messages[round_num] = _combat_round_summary_message(
                round_num,
                round_messages,
                use_llm=(round_num == boundary_round),
            )

        new_conversation = []
        processed_indices = set()
        start_rounds = {
            indices[0]: round_num
            for round_num, indices in round_boundaries.items()
            if indices
        }
        for i, msg in enumerate(conversation_history):
            if i in processed_indices:
                continue

            round_to_compress = start_rounds.get(i)
            if round_to_compress is not None:
                indices = round_boundaries[round_to_compress]
                new_conversation.append(summary_messages[round_to_compress])
                if round_to_compress < current_round - keep_recent_rounds:
                    new_conversation.append({
                        "role": "user",
                        "content": f"Round {round_to_compress} ends and Round {round_to_compress + 1} begins",
                    })
                processed_indices.update(indices)
                info(f"COMPRESSION: Replaced round {round_to_compress}", category="combat_events")
            else:
                new_conversation.append(msg)
                processed_indices.add(i)

        return new_conversation
    except Exception as e:
        error(f"COMPRESSION: Error compressing combat rounds", exception=e, category="combat_events")
        return conversation_history

def _normalize_combatant_name(name):
    """Normalize combatant names for case-insensitive fuzzy matching."""
    return str(name or "").split("(")[0].strip().lower()


def _name_matches_authoritative_roster(candidate_name, authoritative_names):
    """Return True when candidate name fuzzily matches a known roster entry."""
    if not candidate_name:
        return False

    for known_name in authoritative_names:
        if candidate_name in known_name or known_name in candidate_name:
            return True
    return False


def _collect_authoritative_combat_roster(encounter_data, multi_pc_manager=None, party_tracker_data=None):
    """Collect authoritative combat roster from encounter + active multi-PC roster."""
    roster = []
    seen = set()

    def add_entry(name, combatant_type):
        normalized_name = _normalize_combatant_name(name)
        if not normalized_name or normalized_name in seen:
            return

        seen.add(normalized_name)
        roster.append({
            "name": str(name).strip(),
            "type": str(combatant_type or "unknown").strip(),
            "normalized_name": normalized_name,
        })

    for creature in encounter_data.get("creatures", []):
        add_entry(creature.get("name", "Unknown"), creature.get("type", "unknown"))

    # TABLETOP MODE: C4.2 - Include active multi-PC roster so non-active PCs are valid targets
    if multi_pc_manager:
        for pc_name in multi_pc_manager.pc_states.keys():
            add_entry(pc_name, "player")
    elif isinstance(party_tracker_data, dict):
        for member in party_tracker_data.get("partyMembers", []):
            if isinstance(member, dict):
                add_entry(member.get("name", ""), "player")
            else:
                add_entry(member, "player")

    return roster


def validate_combatant_integrity(response_json_str, encounter_data, multi_pc_manager=None, party_tracker_data=None):
    """
    Validates that the AI has not hallucinated new combatants or acted for non-existent ones.
    Returns True if valid, or an error message string if invalid.
    """
    try:
        if not isinstance(response_json_str, str):
            return True

        response = json.loads(response_json_str)
        actions = response.get("actions", [])

        # 1. Build authoritative list of valid combat targets from encounter + multi-PC roster
        authoritative_roster = _collect_authoritative_combat_roster(
            encounter_data,
            multi_pc_manager=multi_pc_manager,
            party_tracker_data=party_tracker_data,
        )
        authoritative_names = [entry["normalized_name"] for entry in authoritative_roster]

        # 2. Validate updateCharacterInfo/updateNPCInfo targets against authoritative roster
        unknown_targets = set()

        for action in actions:
            act_type = action.get("action", "").lower()
            params = action.get("parameters", {})

            # updateCharacterInfo/updateNPCInfo target check
            if act_type in ["updatecharacterinfo", "updatenpcinfo"]:
                char_name = params.get("characterName", "") or params.get("npcName", "")
                if char_name:
                    clean_name = _normalize_combatant_name(char_name)

                    if not _name_matches_authoritative_roster(clean_name, authoritative_names):
                        unknown_targets.add(char_name)

        if unknown_targets:
            # Construct strict rejection message with expanded authoritative roster
            known_list_str = ", ".join(
                [f"{entry['name']} ({entry['type']})" for entry in authoritative_roster]
            )
            return (
                f"INTEGRITY ERROR: updateCharacterInfo/updateNPCInfo references targets not in the authoritative combat roster: {', '.join(unknown_targets)}.\n"
                f"The valid target roster is: {known_list_str}.\n"
                "PCs remain forbidden as DM-controlled actors during ENEMY_PHASE, but PCs are valid targets for enemy/NPC effects."
            )

        return True

    except json.JSONDecodeError:
        return True # JSON format errors are handled elsewhere
    except Exception as e:
        # Fail open if validation crashes, but log it
        error(f"INTEGRITY_CHECK_ERROR: {e}", category="combat_validation")
        return True

def generate_combat_round_summary(round_num, round_messages):
    """Generate a structured summary of a combat round using AI"""
    try:
        # Extract content from messages
        round_content = "\n\n".join([
            f"[{msg.get('role', 'unknown')}]: {msg.get('content', '')}"
            for msg in round_messages
        ])

        prompt = f"""Convert this combat round into a structured JSON summary optimized for AI consumption.

Round {round_num} Combat Log:
{round_content}

Create a JSON summary with EXACTLY this structure:
{{
  "round": {round_num},
  "actions": [
    {{"actor": "name", "init": number, "action": "action_type", "target": "target_name", "roll": "dice+mod=total vs AC/DC", "result": "hit/miss/save/fail", "damage": "X type" or "heal": "X", "effects": "HP changes, conditions, etc"}}
  ],
  "deaths": ["list of creatures that died this round"],
  "status_changes": ["new conditions or effects applied"],
  "resource_usage": {{"character": "resources used (spell slots, abilities, etc)"}},
  "narrative_highlights": ["2-4 evocative single sentences capturing key dramatic moments, critical hits, deaths, powerful spells, or memorable character actions"],
  "round_end_state": {{
    "alive": ["Name (current/max HP)"],
    "dead": ["Name"],
    "conditions": {{"Name": ["conditions"]}}
  }}
}}

Focus on mechanical accuracy for the actions. For narrative_highlights, extract the most dramatic or memorable moments that happened this round - critical hits, character deaths, powerful spells, clutch saves, or impactful dialogue. Keep each highlight to one evocative sentence."""

        observer = make_legacy_receipt_observer(
            legacy_context={"endpoint": "combat_dm", "purpose": "combat_turn_processing"},
            trace_site="compression",
            track_usage=USAGE_TRACKING_AVAILABLE,
        )
        summary_text = llm.call(
            task="compression",
            messages=[
                {"role": "system", "content": "You are a combat log analyzer. Extract mechanical game information and key narrative moments. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            json_output=False,
            temperature=0.1,
            observer=observer,
        )
        summary = json.loads(summary_text)
        return summary
    except GameLLMTerminalError:
        raise
    except Exception as e:
        error(f"COMPRESSION: Failed to generate round {round_num} summary", exception=e, category="combat_events")
        return None


def _queue_final_character_update(
    final_character_updates: Dict[str, List[Dict[str, Any]]],
    character_name: Optional[str],
    changes: Optional[str] = None,
    ops: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Queue a character update payload for end-of-turn persistence."""
    queue_final_character_update(final_character_updates, character_name, changes, ops)


def _sync_multi_pc_character_state(multi_pc_manager: Any, character_name: str) -> None:
    """Refresh in-memory multi-PC state from persisted character data."""
    sync_multi_pc_character_state(
        multi_pc_manager,
        character_name,
        CharacterUpdateDependencies(
            update_character_info=update_character_info,
            normalize_character_name=normalize_character_name,
            safe_json_load=safe_json_load,
            sync_character_state=lambda _manager, _name: None,
            log_info=info,
            log_debug=debug,
            log_error=error,
        ),
    )


def _apply_final_character_updates(
    final_character_updates: Dict[str, List[Dict[str, Any]]],
    multi_pc_manager: Any,
) -> None:
    """Persist queued character updates while preserving deterministic ops payloads."""
    apply_final_character_updates(
        final_character_updates,
        multi_pc_manager,
        CharacterUpdateDependencies(
            update_character_info=update_character_info,
            normalize_character_name=normalize_character_name,
            safe_json_load=safe_json_load,
            sync_character_state=_sync_multi_pc_character_state,
            log_info=info,
            log_debug=debug,
            log_error=error,
        ),
    )


def _build_turn_character_effects(final_character_updates, path_manager):
    """Resolve queued character projections without persisting them early."""
    effects = []
    for character_name, update_entries in final_character_updates.items():
        character_path = path_manager.get_character_path(character_name)
        if not isinstance(character_path, str):
            character_path = str(character_path)
        captured_entries = copy.deepcopy(update_entries)

        def stage(current, name=character_name, entries=captured_entries):
            return stage_final_character_update(
                name, entries, dict(current), update_character_info, log_error=error
            )

        effects.append(TurnCharacterEffect(
            character_name=character_name,
            character_path=character_path,
            stage=stage,
        ))
    return effects


def _sync_encounter_from_staged_characters(encounter_projection, staged_characters):
    """Mirror final staged character fields into the encounter snapshot."""
    if not isinstance(encounter_projection, dict):
        raise ValueError("encounter projection must be an object")
    character_index = {
        " ".join(name.split()).casefold(): data
        for name, data in staged_characters.items()
        if isinstance(name, str) and isinstance(data, dict)
    }
    creatures = encounter_projection.get("creatures")
    if not isinstance(creatures, list):
        raise ValueError("encounter creatures must be a list")
    for creature in creatures:
        if not isinstance(creature, dict) or creature.get("type") not in {"player", "npc"}:
            continue
        name = creature.get("name")
        if not isinstance(name, str):
            continue
        character = character_index.get(" ".join(name.split()).casefold())
        if character is None:
            continue
        if "hitPoints" in character:
            creature["currentHitPoints"] = character["hitPoints"]
        if "maxHitPoints" in character:
            creature["maxHitPoints"] = character["maxHitPoints"]
        if "status" in character:
            creature["status"] = character["status"]
        if "condition_affected" in character:
            creature["conditions"] = copy.deepcopy(character["condition_affected"])
        if "armorClass" in character:
            creature["armorClass"] = character["armorClass"]
    return encounter_projection


def _commit_normal_combat_turn(
    encounter_id,
    turn_id,
    encounter_data,
    final_character_updates,
    path_manager,
    *,
    conversation_history=None,
    conversation_history_file=None,
    narration=None,
    validate_character=None,
):
    """Commit queued character effects before the final receipt-bearing encounter."""
    encounter_path = path_manager.get_encounter_path_from_id(encounter_id)
    manifest_writer = None
    manifest_details = None
    if (
        isinstance(conversation_history, list)
        and isinstance(conversation_history_file, str)
        and isinstance(narration, str)
    ):
        def persist_manifest(manifest):
            history_payload = history_with_combat_turn_manifest(
                conversation_history, turn_id, manifest
            )
            if safe_write_json(conversation_history_file, history_payload) is False:
                return False
            conversation_history[:] = history_payload
            return True

        manifest_writer = persist_manifest
        manifest_details = {
            "path": "normal",
            "staged_rewards": [],
            "success_narration": narration,
        }
    return commit_combat_turn(
        encounter_id,
        turn_id,
        str(encounter_path),
        encounter_data,
        _build_turn_character_effects(final_character_updates, path_manager),
        read_json=safe_json_load,
        write_json=safe_write_json,
        validate_character=validate_character,
        finalize_encounter=_sync_encounter_from_staged_characters,
        manifest_details=manifest_details,
        manifest_writer=manifest_writer,
    )


def run_combat_simulation(encounter_id, party_tracker_data, location_info):
    """Run combat simulation with single-session ownership safeguards."""
    effective_encounter_id = str(encounter_id).strip()
    durable_owner = ""

    # TABLETOP MODE: Prefer durable encounter owner from party tracker if the
    # caller passed a mismatched encounter id.
    try:
        durable_tracker = safe_json_load("party_tracker.json") or {}
        world_conditions = durable_tracker.get("worldConditions", {})
        durable_owner = str(world_conditions.get("activeCombatEncounter", "")).strip()
    except Exception as e:
        warning(
            f"COMBAT_SESSION_GUARD: Could not read durable combat owner, continuing fail-open: {e}",
            category="combat_events"
        )

    if durable_owner and durable_owner != effective_encounter_id:
        warning(
            f"COMBAT_SESSION_MISMATCH: Requested encounter '{effective_encounter_id}' does not match "
            f"durable owner '{durable_owner}'. Preferring durable owner.",
            category="combat_events"
        )
        effective_encounter_id = durable_owner

    session = CombatSession(
        encounter={},
        multi_pc_manager=get_combat_manager() if MULTI_PC_COMBAT_AVAILABLE else None,
        active_pc=party_tracker_data.get("active_character"),
        encounter_id=effective_encounter_id,
    )
    try:
        _enter_combat_session(effective_encounter_id)
    except CombatSessionAlreadyActiveError as e:
        error(f"COMBAT_SESSION_GUARD: {e}", category="combat_events")
        return None, None

    try:
        result = run_combat_simulation_session(session, party_tracker_data, location_info)
        if isinstance(result, FastCommandResult) and result.status == "exit_requested":
            # Preserve the historical public tuple contract without terminating the host process.
            return None, None
        return result
    finally:
        _exit_combat_session(effective_encounter_id)


def run_combat_simulation_session(session, party_tracker_data, location_info):
    """Run one explicitly owned combat session through the legacy loop."""
    # Bind even an explicit None so this entry point cannot borrow another
    # ContextVar-bound manager. The process-wide legacy mirror remains visible
    # to unbound worker threads through the multi-PC adapter.
    with temporary_combat_manager(session.multi_pc_manager):
        return _run_combat_simulation_internal(
            session.encounter_id,
            party_tracker_data,
            location_info,
            session=session,
        )


def _generate_live_initiative_tracker_fallback(encounter_data, conversation_history, current_round):
    """Retain the AI tracker fallback as a lazy, same-condition dependency."""
    from core.combat.initiative_tracker_ai import generate_live_initiative_tracker

    return generate_live_initiative_tracker(encounter_data, conversation_history, current_round)


def _run_combat_simulation_internal(encounter_id, party_tracker_data, location_info, session=None):
   """Main function to run the combat simulation"""
   # Start each combat session's diagnostic handoff explicitly. None means no
   # earlier scene/re-engage path selected a temperature; GPT-5 requests never
   # receive this value as sampling input. This avoids an unbound log variable.
   temperature_used: Optional[float] = None
   print(f"\n[COMBAT_MANAGER] ========== COMBAT SIMULATION START ==========")
   print(f"[COMBAT_MANAGER] Encounter ID: {encounter_id}")
   print(f"[COMBAT_MANAGER] Location: {location_info.get('name', 'Unknown')}")
   debug(f"INITIALIZATION: Starting combat simulation for encounter {encounter_id}", category="combat_events")

   initialization = initialize_combat_session(
       CombatInitializationInputs(
           encounter_id=str(encounter_id),
           party_tracker_data=party_tracker_data,
           location_info=location_info,
           session=session,
       ),
       _build_combat_initialization_dependencies(),
   )
   if initialization.return_early:
       return initialization.return_value
   json_file_path = initialization.json_file_path
   path_manager = initialization.path_manager
   ModulePathManager = initialization.module_path_manager_factory
   safe_json_load = initialization.safe_json_load
   party_tracker = initialization.disk_party_tracker
   encounter_data = initialization.encounter_data
   session = initialization.session
   multi_pc_manager = initialization.multi_pc_manager
   conversation_history = initialization.conversation_history
   history_dependencies = initialization.history_dependencies
   is_resuming = initialization.is_resuming
   is_multipc = initialization.is_multipc
   player_info = initialization.player_info
   player_file = initialization.player_file
   monster_templates = initialization.monster_templates
   npc_templates = initialization.npc_templates

   if not is_resuming:
       if not hydrate_fresh_combat_history(
           history=conversation_history,
           encounter_id=encounter_id,
           encounter_data=encounter_data,
           player_info=player_info,
           monster_templates=monster_templates,
           npc_templates=npc_templates,
           party_tracker_data=party_tracker_data,
           location_info=location_info,
           multi_pc_manager=multi_pc_manager,
           history_file=conversation_history_file,
           session=session,
           dependencies=history_dependencies,
       ):
           return None, None
   else:
       refresh_resumed_combat_history(
           history=conversation_history,
           player_info=player_info,
           monster_templates=monster_templates,
           npc_templates=npc_templates,
           party_tracker_data=party_tracker_data,
            multi_pc_manager=multi_pc_manager,
            history_file=conversation_history_file,
            location_info=location_info,
           session=session,
           dependencies=history_dependencies,
       )

   # TABLETOP MODE: Use the same isolated local RNG for startup and subsequent
   # prompt-context prerolls so retained G7 rows rebuild the same cache.
   preroll_generator, preroll_random_int = build_preroll_dependencies(
        generate_prerolls,
        random.randint,
    )
   initial_state = prepare_initial_combat_state(
       InitialCombatStateInputs(
           encounter_data=encounter_data,
           player_info=player_info,
           path_manager=path_manager,
           multi_pc_manager=multi_pc_manager,
           party_tracker_data=party_tracker_data,
           json_file_path=json_file_path,
       ),
       InitialCombatStateDependencies(
           normalize_character_name=normalize_character_name,
           safe_json_load=safe_json_load,
           load_npc_with_fuzzy_match=load_npc_with_fuzzy_match,
           collect_authoritative_combat_roster=_collect_authoritative_combat_roster,
           generate_prerolls=preroll_generator,
           save_json=save_json_file,
           random_int=preroll_random_int,
           debug=debug,
           error=error,
       ),
   )
   encounter_data = initial_state.encounter_data
   player_info = initial_state.player_info
   player_file = initial_state.player_file
   fresh_player_data = initial_state.fresh_player_data
   current_hp = initial_state.current_hp
   max_hp = initial_state.max_hp
   player_name_display = initial_state.player_name_display
   all_dynamic_state = initial_state.dynamic_state
   preroll_text = initial_state.preroll_text

   startup_narrative = run_startup_narrative(
       CombatStartupNarrativeInputs(
           history=conversation_history,
           history_file=conversation_history_file,
           is_resuming=is_resuming,
           encounter_data=encounter_data,
           party_tracker_data=party_tracker_data,
           multi_pc_manager=multi_pc_manager,
           dynamic_state=all_dynamic_state,
           preroll_text=preroll_text,
            session=session,
            temperature_used=temperature_used,
            recovered_pending_turn=initialization.recovered_pending_turn,
        ),
       _build_startup_narrative_dependencies(),
   )
   conversation_history = startup_narrative.history
   is_resuming = startup_narrative.is_resuming
   session = startup_narrative.session
   is_fast_lane = startup_narrative.is_fast_lane
   initiative_order = startup_narrative.initiative_order
   initial_prompt_text = startup_narrative.initial_prompt_text
   initial_response = startup_narrative.initial_response
   narration = startup_narrative.narration
   temperature_used = startup_narrative.temperature_used
   initial_conversation_length = startup_narrative.initial_conversation_length
   initial_retry_feedback_note = startup_narrative.retry_feedback_note
   if startup_narrative.return_early:
       return startup_narrative.return_value

   # Combat loop
   debug("[COMBAT_MANAGER] Entering main combat loop", category="combat_events")
   print("DEBUG: [COMBAT_LOOP] Entering main while True combat loop")
   if is_resuming:
       print("DEBUG: [RESUME] Successfully reached main combat loop after resume")

   # Update status to show combat is active
   try:
       from core.managers.status_manager import status_manager
       status_manager.update_status("Combat in progress - awaiting your action", is_processing=False)
   except Exception as e:
       debug(f"Could not update status: {e}", category="status")
   g3_logical_turn = 0
   while True:
       turn_iteration = begin_combat_turn_iteration(
           CombatTurnIterationInputs(
               session=session,
               encounter_id=encounter_id,
               encounter_data=encounter_data,
               multi_pc_manager=multi_pc_manager,
               party_tracker_data=party_tracker_data,
               path_manager=path_manager,
               json_file_path=json_file_path,
               conversation_history=conversation_history,
               conversation_history_file=conversation_history_file,
               npc_templates=npc_templates,
               player_info=player_info,
               player_file=player_file,
               fresh_player_data=fresh_player_data,
               current_hp=current_hp,
               max_hp=max_hp,
           ),
            _build_turn_iteration_dependencies(safe_json_load),
       )
       session = turn_iteration.session
       encounter_data = turn_iteration.encounter_data
       multi_pc_manager = turn_iteration.multi_pc_manager
       party_tracker_data = turn_iteration.party_tracker_data
       conversation_history = turn_iteration.conversation_history
       npc_templates = turn_iteration.npc_templates
       path_manager = turn_iteration.path_manager
       player_info = turn_iteration.player_info
       player_file = turn_iteration.player_file
       fresh_player_data = turn_iteration.fresh_player_data
       current_hp = turn_iteration.current_hp
       max_hp = turn_iteration.max_hp
       player_name_display = turn_iteration.player_name_display
       _turn_trace_start = turn_iteration.current_round_trace_start
       if turn_iteration.return_early:
           return turn_iteration.return_value
       if turn_iteration.continue_loop:
           continue
       user_input_text = turn_iteration.user_input_text

       normal_turn_dependencies = _build_normal_turn_dependencies(
           initialization.module_path_manager_factory,
           safe_json_load,
           monster_templates,
           preroll_generator,
           preroll_random_int,
       )
       if (
           should_consider_tactical_prefetch_replan(user_input_text, multi_pc_manager)
           and callable(normal_turn_dependencies.submit_standing_orders)
       ):
           try:
               normal_turn_dependencies.submit_standing_orders(
                   encounter_data=encounter_data,
                   encounter_id=encounter_id,
                   multi_pc_manager=multi_pc_manager,
                   path_manager=path_manager,
                   party_tracker_data=party_tracker_data,
                   location_info=location_info,
                   replan=True,
               )
           except Exception:
               # A state-change re-plan is optional and fail-open.
               pass
       if (
           should_consider_ally_prefetch_replan(user_input_text, multi_pc_manager)
           and callable(normal_turn_dependencies.submit_ally_prefetch)
       ):
           try:
               normal_turn_dependencies.submit_ally_prefetch(
                   encounter_data=encounter_data,
                   encounter_id=encounter_id,
                   multi_pc_manager=multi_pc_manager,
                   path_manager=path_manager,
                   party_tracker_data=party_tracker_data,
                   location_info=location_info,
                   npc_profiles=npc_templates,
                   conversation_history=conversation_history,
                   trigger="state_edge",
               )
           except Exception:
               # State-edge ally re-planning is optional and fail-open.
               pass

       normal_turn = prepare_combat_normal_turn(
           CombatNormalTurnInputs(
               iteration=turn_iteration,
               encounter_id=encounter_id,
               json_file_path=json_file_path,
               conversation_history_file=conversation_history_file,
               location_info=location_info,
           ),
           normal_turn_dependencies,
       )
       if normal_turn.control_action == "continue":
           continue
       if normal_turn.control_action in ("return", "exit_requested"):
           return normal_turn.return_value
       session = normal_turn.session
       encounter_data = normal_turn.encounter_data
       party_tracker_data = normal_turn.party_tracker_data
       conversation_history = normal_turn.conversation_history
       context_result = normal_turn.context_result
       player_info = context_result.player_info
       player_file = context_result.player_file
       path_manager = context_result.path_manager
       fresh_player_data = context_result.fresh_player_data
       current_hp = context_result.current_hp
       max_hp = context_result.max_hp
       user_input_text = context_result.user_input_text
       if True:
        user_input_with_note = context_result.user_prompt
        def _stage_encounter_action(update_id, changes, ops=None):
            return update_encounter.stage_encounter_update(
                update_id,
                changes,
                encounter_data,
                ops=ops,
            )

        combat_action_dependencies = CombatActionDependencies(
            queue_character_update=_queue_final_character_update,
            update_encounter=_stage_encounter_action,
            normalize_encounter_status=normalize_encounter_status,
            sync_non_pc_queue_state=lambda manager, current: manager.sync_non_pc_queue_state(current),
            log_info=info,
            log_debug=debug,
            log_error=error,
            log_warning=warning,
            calculate_xp=calculate_xp,
            save_json=save_json_file,
            active_character_update_available=MULTI_PC_COMBAT_AVAILABLE,
            emit_combat_event=emit_combat_event,
            get_current_actor=lambda manager: manager.get_current_actor(),
            advance_turn=lambda manager: manager.advance_turn(),
            get_pc_state=lambda manager, name: manager.pc_states.get(name),
            pc_acted_status=PCStatus.ACTED,
            npc_combatant_type=CombatantType.NPC,
            pc_combatant_type=CombatantType.PC,
            check_all_monsters_defeated=check_all_monsters_defeated,
            commit_active_character=commit_active_character,
            calculate_xp_for_encounter=lambda projection: calculate_xp(
                projection, party_tracker_data
            ),
        )

        if isinstance(user_input_text, str) and user_input_text.strip() == "Enemies turn.":
           active_world_conditions = party_tracker_data.get("worldConditions", {})
           active_encounter_id = (
               active_world_conditions.get("activeCombatEncounter")
               if isinstance(active_world_conditions, dict) else None
           )
           deterministic_batch = try_execute_deterministic_enemy_batch(
               encounter_data,
               conversation_history,
               user_input_text,
               initial_conversation_length=len(conversation_history),
               encounter_id=encounter_id,
               conversation_history_file=conversation_history_file,
               path_manager=path_manager,
               multi_pc_manager=multi_pc_manager,
               monster_definitions=monster_templates,
                scene_context={
                    "location": location_info,
                     "round": encounter_data.get("combat_round", encounter_data.get("current_round", 1)),
                     "phase": getattr(multi_pc_manager, "combat_phase", None),
                     "active_encounter_id": active_encounter_id,
                     "combat_in_progress": True,
                     "npc_profiles": npc_templates,
                 },
                dependencies=_build_enemy_batch_orchestration_dependencies(session),
                logical_turn=g3_logical_turn,
                party_tracker_data=party_tracker_data,
            )
           if isinstance(deterministic_batch, EnemyBatchExecution):
                if deterministic_batch.logical_turn is not None:
                    g3_logical_turn = deterministic_batch.logical_turn
                encounter_data = deterministic_batch.encounter_data
                conversation_history = deterministic_batch.conversation_history
                session.bind_encounter(encounter_data)
                session.bind_history(conversation_history)
                exit_completion = complete_deterministic_enemy_batch_exit(
                    encounter_data,
                    check_all_monsters_defeated=check_all_monsters_defeated,
                    process_action_batch=process_combat_action_batch,
                    action_dependencies=combat_action_dependencies,
                    encounter_id=encounter_id,
                    conversation_history=conversation_history,
                    conversation_history_file=conversation_history_file,
                    multi_pc_manager=multi_pc_manager,
                    party_tracker_data=party_tracker_data,
                    apply_final_character_updates=_apply_final_character_updates,
                    finalize_combat_session=finalize_combat_session,
                    finalization_inputs=CombatFinalizationInputs(
                        party_tracker_data=party_tracker_data,
                        conversation_history=conversation_history,
                        location_info=location_info,
                        encounter_id=encounter_id,
                        player_file=player_file,
                    ),
                    finalization_dependencies=CombatFinalizationDependencies(
                        summarize_dialogue=summarize_dialogue,
                        safe_write_json=safe_write_json,
                        generate_chat_history=generate_chat_history,
                        safe_json_load=safe_json_load,
                        log_info=info,
                        log_debug=debug,
                    ),
                    precommitted_exit=deterministic_batch.application.exit_completed,
                )
                encounter_data = exit_completion.encounter_data
                if exit_completion.finalization is not None:
                    return (
                        exit_completion.finalization.dialogue_summary,
                        exit_completion.finalization.player_info,
                    )
                trace_stage("turn_end", _turn_trace_start)
                continue

        retry_result = run_combat_provider_retry_stage(
            CombatRetryInputs(
                conversation_history=conversation_history,
                initial_conversation_length=len(conversation_history),
                encounter_data=encounter_data,
                 party_tracker_data=party_tracker_data,
                 multi_pc_manager=multi_pc_manager,
                 user_input_text=user_input_text,
                 diagnostic_temperature=temperature_used,
             ),
            _build_combat_retry_dependencies(),
        )
        valid_response = retry_result.valid_response
        ai_response = retry_result.ai_response
        parsed_response = retry_result.parsed_response
        narration = retry_result.narration
        actions = retry_result.actions
        validation_attempts = retry_result.validation_attempts
        initial_conversation_length = retry_result.initial_conversation_length
        retry_feedback_note = retry_result.retry_feedback_note
        retry_request_history = retry_result.retry_request_history
        retry_validation_history = retry_result.retry_validation_history
        temperature_used = retry_result.temperature_used
        g3_logical_turn += 1
        g3_pre_action_context = capture_pre_round_transition_combat_context(
            encounter_data, multi_pc_manager, retry_result.parsed_response,
            valid_response, g3_logical_turn,
        )
        if g3_pre_action_context is not None:
            trace_combat_observation(
                "combat_validation_result", **{
                    **g3_pre_action_context,
                    "has_accepted_parsed_response": bool(valid_response and isinstance(retry_result.parsed_response, dict)),
                    "action_count": len(retry_result.actions),
                }
            )

        # Clean up conversation history based on validation outcome
        if valid_response or ai_response:
            # Remove all validation attempts from conversation history
            conversation_history = conversation_history[:initial_conversation_length]
            session.bind_history(conversation_history)

            # Add only the final assistant response
            if ai_response:
                conversation_history.append({"role": "assistant", "content": ai_response})

            # Log successful validation if it occurred
            if valid_response and validation_attempts:
                validation_attempts.append({
                    "attempt": "final",
                    "assistant_response": ai_response,
                    "validation_result": "success",
                    "temperature_used": temperature_used
                })

        # Write validation attempts to log file
        if validation_attempts:
            # Create debug/combat directory if it doesn't exist
            debug_combat_dir = os.path.join("debug", "combat")
            os.makedirs(debug_combat_dir, exist_ok=True)

            # Create timestamped filename
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Remove last 3 digits of microseconds
            encounter_id = encounter_data.get("encounterId", "unknown").replace("/", "_")
            validation_count = len(validation_attempts)
            validation_filename = f"validation_session_{timestamp}_{encounter_id}_attempts{validation_count}.json"
            validation_log_path = os.path.join(debug_combat_dir, validation_filename)
            try:
                # Create new validation log for this session
                validation_log = []

                # Add current validation session
                validation_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "encounter_id": encounter_data.get("encounter_id", "unknown"),
                    "user_input": user_input_text,
                    "validation_attempts": validation_attempts,
                    "final_outcome": "success" if valid_response else "failed_after_retries"
                })

                # Write updated log
                with open(validation_log_path, 'w') as f:
                    json.dump(validation_log, f, indent=2)

            except Exception as e:
                warning(f"FAILURE: Failed to write validation log", category="file_operations")

        if not ai_response:
            error("FAILURE: Failed to get a valid AI response after multiple attempts", category="combat_events")
            continue

        # Process the validated response
        try:
            parsed_response = json.loads(ai_response)
            narration = parsed_response["narration"]
            actions = parsed_response["actions"]

            print(f"[COMBAT_MANAGER] Processing {len(actions)} combat actions")

            # Update status to show actions are being processed
            if len(actions) > 0:
                try:
                    from core.managers.status_manager import status_manager
                    status_manager.update_status("Processing combat outcomes...", is_processing=True)
                except Exception as e:
                    debug(f"Could not update status: {e}", category="status")

            for i, action in enumerate(actions):
                action_type = action.get('action', action.get('type', 'unknown'))
                print(f"[COMBAT_MANAGER] Action {i+1}: {action_type}")

        except json.JSONDecodeError as e:
            debug(f"VALIDATION: JSON parsing error - {str(e)}", category="combat_events")
            debug("VALIDATION: Raw AI response:", category="combat_events")
            debug(ai_response, category="combat_events")
            continue

        # --- ACTION PROCESSING: CONSOLIDATE AND EXECUTE ---
        # This new block prevents race conditions by consolidating all character
        # updates into a single, authoritative save at the end of combat.

        # A dictionary to hold queued character update payloads for each actor.
        final_character_updates = {}

        # Check if combat is ending in this turn.
        is_combat_ending = any(a.get("action", "").lower() == "exit" for a in actions)

        trace_combat_action_batch_metadata(
            CombatActionTraceInputs(
                actions=actions,
                encounter_data=encounter_data,
                encounter_id=encounter_id,
                pre_action_context=g3_pre_action_context,
                validation_accepted=bool(valid_response),
            ),
            CombatActionTraceDependencies(
                trace_enabled=trace_enabled,
                trace_observation=trace_combat_observation,
            ),
        )

        phase_before_actions = getattr(multi_pc_manager, "combat_phase", None)
        if phase_before_actions not in ("PC_PHASE", "ENEMY_PHASE"):
            phase_before_actions = encounter_data.get("combat_phase")
        enemy_turn_input = (
            isinstance(user_input_text, str)
            and user_input_text.strip() == "Enemies turn."
        )
        if phase_before_actions not in ("PC_PHASE", "ENEMY_PHASE"):
            phase_before_actions = "ENEMY_PHASE" if enemy_turn_input else "PC_PHASE"
        opening_batch_pending_before = (
            encounter_data.get("openingEnemyBatchPending") is True
        )
        round_before_actions = encounter_data.get(
            "combat_round", encounter_data.get("current_round", 1)
        )
        round_starts_with_before = encounter_data.get("roundStartsWith", "pcGroup")

        # STEP 1: Preserve the legacy per-action encounter/queue order and
        # collect character mutations for the existing post-batch commit point.
        action_batch = process_combat_action_batch(
            actions,
            encounter_data,
            final_character_updates,
            encounter_id=encounter_id,
            conversation_history=conversation_history,
            conversation_history_file=conversation_history_file,
            multi_pc_manager=multi_pc_manager,
            party_tracker_data=party_tracker_data,
            is_combat_ending=is_combat_ending,
            dependencies=combat_action_dependencies,
        )
        encounter_data = action_batch.encounter_data
        final_character_updates = action_batch.final_character_updates
        is_combat_ending = action_batch.is_combat_ending

        # TABLETOP MODE: Derive the final counter/phase snapshot from Python's
        # accepted turn boundary; model-reported combat_round is not authority.
        round_result = stage_combat_turn_snapshot(
            encounter_data,
            conversation_history,
            phase_before=phase_before_actions,
            phase_after=getattr(multi_pc_manager, "combat_phase", None)
                if multi_pc_manager else encounter_data.get("combat_phase"),
            enemy_batch_completed=bool(
                valid_response
                and enemy_turn_input
                and phase_before_actions == "ENEMY_PHASE"
            ),
            opening_batch_pending_before=opening_batch_pending_before,
            authoritative_round_before=round_before_actions,
            round_starts_with_before=round_starts_with_before,
            dependencies=RoundTransitionDependencies(
                apply_opening_batch_marker=apply_opening_batch_marker,
                sync_available=COMBAT_STATE_SYNC_AVAILABLE,
                save_json=save_json_file,
                compress_old_rounds=compress_old_combat_rounds,
                log_debug=debug,
                log_info=info,
                log_warning=warning,
                bind_history=session.bind_history,
            ),
        )
        encounter_data = round_result.encounter_data
        conversation_history = round_result.conversation_history

        # TABLETOP MODE: Stage all final projections, then commit marked character
        # records before the single receipt-bearing encounter write.
        turn_record_index = initial_conversation_length - 1
        turn_record = (
            conversation_history[turn_record_index]
            if 0 <= turn_record_index < len(conversation_history) else None
        )
        turn_id = turn_record.get("turn_id") if isinstance(turn_record, dict) else None
        turn_commit = _commit_normal_combat_turn(
            encounter_id,
            turn_id,
            encounter_data,
            final_character_updates,
            path_manager,
            conversation_history=conversation_history,
            conversation_history_file=conversation_history_file,
            narration=narration,
        )
        encounter_data = turn_commit.encounter_data
        sync_committed_combat_turn(encounter_data, multi_pc_manager, session)
        publish_combat_narration(
            narration,
            applied_id=turn_commit.applied_id,
            emit=print,
            flush=sys.stdout.flush,
        )
        if trace_enabled() and g3_pre_action_context is not None:
            trace_combat_observation(
                "combat_logical_batch_completed",
                logical_turn=g3_pre_action_context.get("logical_turn"),
                validation_accepted=bool(valid_response),
                accepted_batch=bool(valid_response and isinstance(parsed_response, dict)),
                phase_before_round_transition=g3_pre_action_context.get("phase"),
                phase_after_processing=getattr(multi_pc_manager, "combat_phase", None)
                    if multi_pc_manager else None,
                round_before=g3_pre_action_context.get("combat_round"),
                round_after=encounter_data.get("combat_round"),
                opening_pending_before=g3_pre_action_context.get("opening_batch_pending"),
                opening_pending_after=encounter_data.get("openingEnemyBatchPending"),
                eligible_non_pc_cohort=g3_pre_action_context.get("eligible_non_pc_cohort", []),
                is_combat_ending=bool(is_combat_ending),
            )

        # STEP 3: If combat ended, perform final cleanup and exit the simulation.
        if is_combat_ending:
            finalization = finalize_combat_session(
                CombatFinalizationInputs(
                    party_tracker_data=party_tracker_data,
                    conversation_history=conversation_history,
                    location_info=location_info,
                    encounter_id=encounter_id,
                    player_file=player_file,
                ),
                CombatFinalizationDependencies(
                    summarize_dialogue=summarize_dialogue,
                    safe_write_json=safe_write_json,
                    generate_chat_history=generate_chat_history,
                    safe_json_load=safe_json_load,
                    log_info=info,
                    log_debug=debug,
                ),
            )
            return finalization.dialogue_summary, finalization.player_info

        # Save updated conversation history after processing all actions
        manifest_persisted = any(
            isinstance(message, dict)
            and message.get("turn_id") == turn_id
            and COMBAT_TURN_COMMIT_MANIFEST_KEY in message
            for message in conversation_history
        )
        if not manifest_persisted:
            save_json_file(conversation_history_file, conversation_history)
        # TABLETOP MODE: combat latency trace (Phase 0)
        trace_stage("turn_end", _turn_trace_start)

def main():
    debug("INITIALIZATION: Starting main function in combat_manager", category="combat_events")

    # Load party tracker
    try:
        party_tracker_data = safe_json_load("party_tracker.json")
        if not party_tracker_data:
            error("FAILURE: Failed to load party_tracker.json", category="file_operations")
            return
    except Exception as e:
        error(f"FAILURE: Failed to load party tracker", exception=e, category="file_operations")
        return

    # Get active combat encounter
    active_combat_encounter = party_tracker_data["worldConditions"].get("activeCombatEncounter")

    if not active_combat_encounter:
        info("STATE_CHANGE: No active combat encounter located.", category="combat_events")
        return

    # Get location data to pass to the simulation
    current_location_id = party_tracker_data["worldConditions"]["currentLocationId"]
    location_data = get_location_data(current_location_id)

    if not location_data:
        error(f"FAILURE: Failed to find location {current_location_id}", category="location_transitions")
        return

    # Run the combat simulation, passing the loaded location_data
    dialogue_summary, updated_player_info = run_combat_simulation(active_combat_encounter, party_tracker_data, location_data)

    info("SUCCESS: Combat simulation completed.", category="combat_events")
    if dialogue_summary:
        info(f"SUMMARY: Dialogue Summary: {dialogue_summary}", category="combat_events")

if __name__ == "__main__":
    main()
