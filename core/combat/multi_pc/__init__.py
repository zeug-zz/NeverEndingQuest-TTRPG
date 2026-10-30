# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Lazy public surface for package-owned multi-PC combat."""

import importlib
from typing import Any, Dict, List


_MODULE_NAMES: List[str] = ["dm_note", "manager", "state", "sync", "turn_queue"]
_PUBLIC_EXPORTS: Dict[str, str] = {
    "MultiPCCombatManager": "manager",
    "temporary_combat_manager": "manager",
    "temporary_combat_callback": "manager",
    "reset_combat_state": "manager",
    "set_combat_callback": "manager",
    "emit_combat_event": "manager",
    "get_combat_manager": "manager",
    "create_combat_manager": "manager",
    "end_combat_session": "manager",
    "cleanup_combat_manager": "manager",
    "is_multi_pc_combat_enabled": "manager",
    "modify_combat_prompt_for_multi_pc": "manager",
    "get_multi_pc_initiative_narrative": "manager",
    "PCStatus": "state",
    "PCCombatState": "state",
    "CombatStateManager": "state",
    "CombatantType": "turn_queue",
    "Combatant": "turn_queue",
    "TurnQueueManager": "turn_queue",
    "apply_opening_batch_marker": "sync",
    "normalize_multi_pc_roster": "sync",
    "format_multi_pc_head_context": "dm_note",
    "format_party_turn_summary": "dm_note",
    "format_initiative_tracker": "dm_note",
}

# TABLETOP MODE: Explicit public exports preserve the old package surface while
# keeping owner modules unloaded until a symbol is accessed.
__all__ = list(_MODULE_NAMES) + list(_PUBLIC_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a module or public multi-PC symbol lazily."""
    module_name = _PUBLIC_EXPORTS.get(name, name if name in _MODULE_NAMES else "")
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f"{__name__}.{module_name}")
    if name in _PUBLIC_EXPORTS:
        return getattr(module, name)
    return module


def __dir__() -> List[str]:
    """Expose lazy module and public symbol names to introspection."""
    return sorted(set(globals()) | set(__all__))
