# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Explicit per-run state for the combat simulation.

The legacy combat entry point still accepts its historical arguments, but the
implementation binds those arguments to one ``CombatSession`` before entering
the loop.  Keeping the mutable values together prevents a second combat run
from borrowing state from another run while preserving aliases to caller-owned
encounter and history objects.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CombatSession:
    """State owned by one combat simulation lifecycle."""

    encounter: Dict[str, Any]
    multi_pc_manager: Any = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    active_pc: Optional[str] = None
    phase: str = "PC_PHASE"
    encounter_id: str = ""
    turn_iteration_id: int = 0
    last_active_encounter_sync_turn_id: Optional[int] = None

    def __post_init__(self) -> None:
        """Bind initial encounter identity to the session-owned manager."""
        self._bind_manager_encounter()

    def bind_encounter(self, encounter: Dict[str, Any]) -> Dict[str, Any]:
        """Bind and return the exact mutable encounter object supplied."""
        self.encounter = encounter
        self._bind_manager_encounter()
        return self.encounter

    def _bind_manager_encounter(self) -> None:
        """Propagate authoritative encounter identity when the manager supports it."""
        binder = getattr(self.multi_pc_manager, "bind_context_encounter", None)
        if callable(binder):
            binder(self.encounter)

    def bind_history(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Bind and return the exact mutable history object supplied."""
        self.history = history
        return self.history

    def set_phase(self, phase: str) -> str:
        """Record the current phase and return it for explicit handoffs."""
        self.phase = phase
        return self.phase

    def begin_turn_iteration(self) -> int:
        """Advance the process-local identity for the next combat-loop turn."""
        self.turn_iteration_id += 1
        return self.turn_iteration_id

    def claim_active_encounter_sync(self, turn_identity: int, *, force: bool = False) -> bool:
        """Allow one routine encounter sync per turn; commands may force one."""
        if not force and self.last_active_encounter_sync_turn_id == turn_identity:
            return False
        self.last_active_encounter_sync_turn_id = turn_identity
        return True

    def history_payloads(
        self,
        *,
        head_context: str,
        monster_templates: Dict[str, Any],
        location: Dict[str, Any],
        encounter_details: Optional[str] = None,
        npc_templates: Optional[Dict[str, Any]] = None,
        filter_dynamic_fields: Any = None,
    ) -> Dict[str, str]:
        """Build system payloads from state rather than numeric history slots."""
        payloads = {
            "head": head_context,
            "monsters": "Monster Templates:\n" + json.dumps(
                {
                    key: filter_dynamic_fields(value) if filter_dynamic_fields else value
                    for key, value in monster_templates.items()
                },
                indent=2,
            ),
            "location": "Location:\n" + json.dumps(location, indent=2),
        }
        if encounter_details is not None:
            payloads["encounter"] = encounter_details
        if npc_templates is not None and filter_dynamic_fields:
            payloads["npc_templates"] = "NPC Templates:\n" + json.dumps(
                {key: filter_dynamic_fields(value) for key, value in npc_templates.items()},
                indent=2,
            )
        return payloads

    def apply_history_payloads(self, payloads: Dict[str, str], *, fill_empty: bool = True) -> None:
        """Apply semantic payload replacements without relying on indexes.

        Resumed histories already contain populated payload messages, so an
        empty-slot-only update is insufficient.  Known markers are replaced
        in place; fresh histories may still consume their explicit empty
        placeholders in payload order.  Existing unrelated messages are never
        rewritten or reordered.
        """
        markers = {
            "head": (
                "=== AUTHORITATIVE MULTI-PC STATE (JSON) ===",
                "Player Character:",
                "Here's the player character data:",
            ),
            "monsters": ("Monster Templates:",),
            "location": ("Location:",),
            "npc_templates": ("NPC Templates:",),
            "encounter": ("Encounter Details:",),
        }
        pending = []
        for key, content in payloads.items():
            replaced = False
            for message in self.history:
                if message.get("role") != "system":
                    continue
                if any(self._has_semantic_marker(message.get("content", ""), marker) for marker in markers.get(key, ())):
                    message["content"] = content
                    replaced = True
                    break
            if not replaced:
                pending.append(content)

        if fill_empty:
            for content in pending:
                if not self.replace_first_empty_system_payload(content):
                    self.history.append({"role": "system", "content": content})

    def replace_system_payload(self, marker: str, content: str) -> bool:
        """Replace the first semantic system payload matching ``marker``."""
        for message in self.history:
            if message.get("role") == "system" and self._has_semantic_marker(message.get("content", ""), marker):
                message["content"] = content
                return True
        return False

    @staticmethod
    def _has_semantic_marker(message_content: str, marker: str) -> bool:
        """Match payload headers, not marker text embedded in other prompts."""
        if message_content.startswith(marker):
            return True
        first_line = message_content.splitlines()[0].strip() if message_content.splitlines() else ""
        return first_line == marker

    def replace_first_empty_system_payload(self, content: str) -> bool:
        """Fill the next empty system payload without relying on its position."""
        for message in self.history:
            if message.get("role") == "system" and not message.get("content"):
                message["content"] = content
                return True
        return False
