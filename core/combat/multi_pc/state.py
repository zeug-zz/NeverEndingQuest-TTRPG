# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Authoritative PC combat state ownership for multi-PC combat."""

import json
import re
import sys
import types
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.encoding_utils import safe_json_load
from utils.enhanced_logger import debug


class _LoaderAwareCombatStateModule(types.ModuleType):
    """Keep the legacy manager's real loader binding in sync with its owner."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name == "safe_json_load":
            manager_module = sys.modules.get("core.combat.multi_pc.manager")
            if manager_module is not None:
                manager_module.__dict__[name] = value

def _normalize_combat_identity(name: Any) -> str:
    """Normalize character/combatant names for canonical identity checks."""
    normalized = str(name or "").strip().lower()
    normalized = normalized.replace(" ", "_")
    normalized = normalized.replace("'", "_")
    normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")

def _extract_death_save_counts(character_data: Dict[str, Any]) -> Tuple[int, int]:
    """Read nested or legacy death save counters from character data."""
    death_saves = character_data.get("deathSaves")
    if isinstance(death_saves, dict):
        try:
            return (
                int(death_saves.get("successes", 0) or 0),
                int(death_saves.get("failures", 0) or 0),
            )
        except (TypeError, ValueError):
            return (0, 0)

    try:
        return (
            int(character_data.get("deathSaveSuccesses", 0) or 0),
            int(character_data.get("deathSaveFailures", 0) or 0),
        )
    except (TypeError, ValueError):
        return (0, 0)


class PCStatus(Enum):
    """Status of a PC in combat."""
    READY = "ready"
    ACTED = "acted"
    INCAPACITATED = "incapacitated"
    DEAD = "dead"
    STABLE = "stable"

@dataclass
class PCCombatState:
    """Tracks a single PC's state during combat."""
    character_name: str
    initiative_modifier: int = 0
    status: PCStatus = PCStatus.READY
    death_save_successes: int = 0
    death_save_failures: int = 0
    current_hp: int = 0
    max_hp: int = 0
    ac: int = 10  # Armor Class for hit/miss determination
    # Metadata for arbitrary upstream data (position, markers, etc.)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def reset_for_new_round(self):
        """Reset PC state for a new combat round."""
        if self.status == PCStatus.ACTED:
            self.status = PCStatus.READY

    def mark_acted(self):
        """Mark this PC as having acted this round."""
        if self.status == PCStatus.READY:
            self.status = PCStatus.ACTED

    def needs_death_save(self) -> bool:
        """Check if PC needs to make a death saving throw."""
        return self.status == PCStatus.INCAPACITATED

    def apply_death_save(self, roll: int) -> Tuple[bool, str]:
        """
        Apply a death saving throw result.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            roll: The d20 roll result (1-20)
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple of (combat_continues, result_message)
        """
        if roll == 1:
            # Critical failure - two failures
            self.death_save_failures += 2
            message = f"{self.character_name} rolls a natural 1! Two death save failures!"
        elif roll == 20:
            # Critical success - regain 1 HP
            self.death_save_successes = 0
            self.death_save_failures = 0
            self.current_hp = 1
            self.status = PCStatus.READY
            message = f"{self.character_name} rolls a natural 20! They regain consciousness with 1 HP!"
            return True, message
        elif roll >= 10:
            self.death_save_successes += 1
            message = f"{self.character_name} succeeds on their death save ({self.death_save_successes}/3 successes)."
        else:
            self.death_save_failures += 1
            message = f"{self.character_name} fails their death save ({self.death_save_failures}/3 failures)."

        # Check for stabilization or death
        if self.death_save_successes >= 3:
            self.status = PCStatus.STABLE
            message += f" {self.character_name} has stabilized!"
        elif self.death_save_failures >= 3:
            self.status = PCStatus.DEAD
            message += f" {self.character_name} has died!"

        return self.status != PCStatus.DEAD, message


@dataclass
class CombatStateManager:
    """
    Manages PC combat states, HP tracking, and combat metadata.
\x20\x20\x20\x20
    This class handles all state-related operations for multi-PC combat,
    keeping state management separate from turn queue logic.
    """

    # PC states indexed by character name
    pc_states: Dict[str, PCCombatState] = field(default_factory=dict)

    # Current active PC (selected via UI)
    current_pc_name: Optional[str] = None

    # Combat tracking
    current_round: int = 1
    party_initiative: int = 0
    enemy_initiative: int = 0
    party_goes_first: bool = True

    # Encounter data reference
    encounter_data: Optional[Dict[str, Any]] = None

    # Party size limit
    MAX_PARTY_SIZE: int = 6

    def initialize_from_party(self, party_data: Dict[str, Any]) -> None:
        """
        Initialize PC states from party tracker data.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            party_data: The party_tracker.json data
        """
        self.pc_states.clear()

        party_members = party_data.get("partyMembers", [])
        requested_active_identity = _normalize_combat_identity(party_data.get("active_character"))
        deduped_members: List[str] = []
        seen_identities = set()

        for member_name in party_members:
            normalized_member = _normalize_combat_identity(member_name)
            if not normalized_member or normalized_member in seen_identities:
                continue
            seen_identities.add(normalized_member)
            deduped_members.append(str(member_name))

        party_members = deduped_members

        # Enforce party size limit
        if len(party_members) > self.MAX_PARTY_SIZE:
            party_members = party_members[:self.MAX_PARTY_SIZE]

        resolved_active_name: Optional[str] = None

        for member_name in party_members:
            # TABLETOP MODE: Load character data directly from character JSON file
            # party_tracker.json does not store nested character objects
            # Build path manually to avoid circular dependencies and import issues
            try:
                normalized_name = _normalize_combat_identity(member_name)
                char_file_path = f"characters/{normalized_name}.json"

                # Use safe_json_load if available, otherwise fall back to standard json
                if safe_json_load:
                    char_data = safe_json_load(char_file_path) or {}
                else:
                    # Use standard json module (already imported)
                    with open(char_file_path, 'r', encoding='utf-8') as f:
                        char_data = json.load(f)

                if not char_data:
                    debug(f"TABLETOP MODE: Character file not found or empty: {char_file_path}",
                          category="combat_events")
            except Exception as e:
                debug(f"TABLETOP MODE: Failed to load character {member_name}: {e}",
                      category="combat_events")
                char_data = {}

            display_name = str(char_data.get("name") or member_name).strip() or str(member_name)

            # Read HP from character schema (hitPoints is top-level, not nested under hp)
            current_hp = char_data.get("hitPoints", 10)
            max_hp = char_data.get("maxHitPoints", current_hp)
            death_successes, death_failures = _extract_death_save_counts(char_data)
            persisted_status = str(char_data.get("status") or "").strip().lower()

            # Determine initial status based on HP
            if persisted_status == "dead":
                status = PCStatus.DEAD
            elif current_hp <= 0 and death_successes >= 3:
                status = PCStatus.STABLE
            elif current_hp <= 0:
                status = PCStatus.INCAPACITATED
            else:
                status = PCStatus.READY

            # Capture any metadata (like position) from char_data
            metadata = char_data.get("metadata", {}) or {}

            self.pc_states[display_name] = PCCombatState(
                character_name=display_name,
                initiative_modifier=char_data.get("initiative", 0),
                status=status,
                death_save_successes=death_successes,
                death_save_failures=death_failures,
                current_hp=current_hp,
                max_hp=max_hp,
                ac=char_data.get("armorClass", 10),
                metadata=metadata
            )

            if requested_active_identity and _normalize_combat_identity(display_name) == requested_active_identity:
                resolved_active_name = display_name

        # Set first PC as current if none selected
        if resolved_active_name:
            self.current_pc_name = resolved_active_name
        elif not self.current_pc_name and self.pc_states:
            self.current_pc_name = list(self.pc_states.keys())[0]

    def get_available_pcs(self) -> List[str]:
        """Get list of PCs who can still act this round."""
        return [
            name for name, state in self.pc_states.items()
            if state.status == PCStatus.READY
        ]

    def get_incapacitated_pcs(self) -> List[str]:
        """Get list of PCs who need death saves."""
        return [
            name for name, state in self.pc_states.items()
            if state.status == PCStatus.INCAPACITATED
        ]

    def get_all_active_pcs(self) -> List[str]:
        """Get all PCs who are still in combat (not dead)."""
        return [
            name for name, state in self.pc_states.items()
            if state.status != PCStatus.DEAD
        ]

    def set_current_pc(self, character_name: str) -> bool:
        """
        Set the current active PC (via tab click).
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            character_name: Name of the PC to activate
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            True if successful, False if PC can't act
        """
        resolved_name = character_name if character_name in self.pc_states else None
        if resolved_name is None:
            requested_identity = _normalize_combat_identity(character_name)
            for existing_name in self.pc_states.keys():
                if _normalize_combat_identity(existing_name) == requested_identity:
                    resolved_name = existing_name
                    break

        if resolved_name is None:
            return False

        state = self.pc_states[resolved_name]

        # Can select if ready OR incapacitated (for death saves)
        if state.status in (PCStatus.READY, PCStatus.INCAPACITATED):
            self.current_pc_name = resolved_name
            return True

        return False

    def update_pc_hp(self, character_name: str, new_hp: int) -> None:
        """
        Update a PC's HP and status.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            character_name: Name of the PC
            new_hp: New HP value
        """
        if character_name not in self.pc_states:
            return

        state = self.pc_states[character_name]
        previous_status = state.status
        state.current_hp = new_hp

        if new_hp <= 0:
            if previous_status in (PCStatus.READY, PCStatus.ACTED):
                state.status = PCStatus.INCAPACITATED
                state.death_save_successes = 0
                state.death_save_failures = 0
        elif new_hp > 0 and previous_status in (PCStatus.INCAPACITATED, PCStatus.STABLE):
            state.status = PCStatus.READY
            state.death_save_successes = 0
            state.death_save_failures = 0

    def sync_pc_persistent_state(self, character_name: str, character_data: Dict[str, Any]) -> None:
        """Sync durable PC state fields loaded from character storage."""
        resolved_name = character_name if character_name in self.pc_states else None
        if resolved_name is None:
            requested_identity = _normalize_combat_identity(character_name)
            for existing_name in self.pc_states.keys():
                if _normalize_combat_identity(existing_name) == requested_identity:
                    resolved_name = existing_name
                    break

        if resolved_name is None:
            return

        state = self.pc_states.get(resolved_name)
        if not state:
            return

        try:
            state.current_hp = int(character_data.get("hitPoints", state.current_hp) or 0)
        except (TypeError, ValueError):
            pass

        try:
            state.max_hp = int(character_data.get("maxHitPoints", state.max_hp) or state.max_hp)
        except (TypeError, ValueError):
            pass

        try:
            state.ac = int(character_data.get("armorClass", state.ac) or state.ac)
        except (TypeError, ValueError):
            pass

        death_successes, death_failures = _extract_death_save_counts(character_data)
        state.death_save_successes = death_successes
        state.death_save_failures = death_failures

        persisted_status = str(character_data.get("status") or "").strip().lower()
        if persisted_status == "dead":
            state.status = PCStatus.DEAD
        elif state.current_hp <= 0 and death_successes >= 3:
            state.status = PCStatus.STABLE
        elif state.current_hp <= 0:
            state.status = PCStatus.INCAPACITATED
        else:
            state.status = PCStatus.READY


if not isinstance(sys.modules[__name__], _LoaderAwareCombatStateModule):
    sys.modules[__name__].__class__ = _LoaderAwareCombatStateModule
