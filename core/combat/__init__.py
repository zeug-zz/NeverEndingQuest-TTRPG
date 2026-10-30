# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Lazy public surface for the combat package."""

import importlib
from typing import Any, List


# TABLETOP MODE: Keep package API access lazy so narrow imports do not build
# the provider-bearing combat owner.
_COMBAT_MANAGER_NAMES: List[str] = [
    "TEMPERATURE", "HISTORY_TIMESTAMP_FORMAT", "CombatSessionAlreadyActiveError",
    "build_request_roll_action", "get_concentration_request_dc", "get_combat_temperature",
    "load_npc_with_fuzzy_match", "get_current_area_id", "get_location_data",
    "read_prompt_from_file", "load_monster_stats", "load_json_file", "save_json_file",
    "_enter_combat_session", "_exit_combat_session", "clean_combat_state_blocks",
    "clean_old_dm_notes", "is_valid_json", "write_debug_output", "parse_json_safely",
    "check_multiple_update_encounter", "create_consolidation_prompt",
    "create_multiple_update_requery_prompt", "sanitize_unicode_for_logging",
    "validate_combat_response", "normalize_encounter_status", "normalize_phase1_initiative",
    "get_initiative_order", "log_conversation_structure", "summarize_dialogue",
    "merge_updates", "update_json_schema", "generate_chat_history", "sync_active_encounter",
    "filter_dynamic_fields", "format_character_for_combat", "format_npc_for_combat",
    "filter_encounter_for_system_prompt", "compress_old_combat_rounds",
    "validate_combatant_integrity", "generate_combat_round_summary", "run_combat_simulation",
    "main",
    "CombatSession",
    "run_combat_simulation_session",
    "InputPhaseGateResult", "PhaseGateIO", "handle_group_initiative_gate", "run_input_phase_gate",
    "FastCommandResult", "FastCommandIO", "run_fast_commands_stage",
]
__all__ = list(_COMBAT_MANAGER_NAMES)


def __getattr__(name: str) -> Any:
    """Resolve a public combat name on first access."""
    if name == "combat_manager":
        return importlib.import_module("core.combat.combat_manager")
    if name == "initiative_tracker_ai":
        return importlib.import_module("core.combat.initiative_tracker_ai")
    if name == "CombatSession":
        return importlib.import_module("core.combat.session").CombatSession
    if name in {"InputPhaseGateResult", "PhaseGateIO", "run_input_phase_gate", "handle_group_initiative_gate"}:
        return getattr(importlib.import_module("core.combat.turn"), name)
    if name in {"FastCommandResult", "FastCommandIO", "run_fast_commands_stage"}:
        return getattr(importlib.import_module("core.combat.commands"), name)
    if name in _COMBAT_MANAGER_NAMES:
        module = importlib.import_module("core.combat.combat_manager")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    """Expose lazy public names to introspection without importing the owner."""
    return sorted(set(globals()) | set(__all__) | {"combat_manager", "initiative_tracker_ai"})
