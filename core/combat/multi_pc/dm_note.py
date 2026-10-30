# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Combat-owned narration adapters for the multi-PC facade.

The full DM-note builder remains in ``utils.multi_pc_dm_note`` because it is a
shared party/narration utility.  These adapters own the combat-only head,
party-turn, and initiative formatting entry points without importing the
shared utility or creating a second implementation.
"""

from typing import Any, Dict


def format_multi_pc_head_context(manager: Any) -> str:
    """Delegate combat head-context formatting to the active facade."""
    return manager.format_multi_pc_head_context()


def format_party_turn_summary(manager: Any) -> str:
    """Delegate combat party-turn formatting to the active facade."""
    return manager.format_party_turn_summary()


def format_initiative_tracker(manager: Any, encounter_data: Dict[str, Any]) -> str:
    """Delegate deterministic initiative formatting to the active facade."""
    return manager.format_initiative_tracker(encounter_data)


def get_multi_pc_initiative_narrative(manager: Any) -> str:
    """Delegate to the manager module's initiative narration helper."""
    # Local import preserves cold-import behavior for this narrow adapter.
    from .manager import get_multi_pc_initiative_narrative

    return get_multi_pc_initiative_narrative(manager)


__all__ = [
    "format_multi_pc_head_context",
    "format_party_turn_summary",
    "format_initiative_tracker",
    "get_multi_pc_initiative_narrative",
]
