# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Authoritative initiative and turn-queue ownership for multi-PC combat."""

import json
import os
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.encoding_utils import safe_json_load
from utils.enhanced_logger import debug
from utils.module_path_manager import ModulePathManager
from .state import CombatStateManager, PCStatus, _normalize_combat_identity

class CombatantType(Enum):
    PC = "pc"
    ENEMY = "enemy"
    NPC = "npc"

@dataclass
class Combatant:
    """Generic wrapper for any entity in the turn queue."""
    name: str
    type: CombatantType
    initiative: int
    hp: int
    max_hp: int
    ac: int
    status: str = "alive"
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TurnQueueManager:
    """
    Manages initiative order, turn advancement, and round tracking.
\x20\x20\x20\x20
    This class handles the turn queue lifecycle independent of PC state management,
    allowing for cleaner separation between state and turn flow.
    """

    # Turn Queue Management
    turn_queue: List[Combatant] = field(default_factory=list)
    current_turn_index: int = 0

    # Phase tracking
    pc_phase_complete: bool = False
    enemy_phase_complete: bool = False

    # Combat flow
    first_round: bool = True

    # Reference to state manager for PC lookups
    state_manager: Optional[CombatStateManager] = None

    def initialize_turn_queue(self, encounter_data: Dict[str, Any]) -> None:
        """
        Build the turn queue from PC states and encounter data.
        Call this at the start of combat or when initiative changes.
        """
        self.turn_queue.clear()

        # Add PCs from state manager
        if self.state_manager:
            for name, state in self.state_manager.pc_states.items():
                # Calculate initiative (d20 + mod)
                init_roll = random.randint(1, 20) + state.initiative_modifier
                self.turn_queue.append(Combatant(
                    name=name,
                    type=CombatantType.PC,
                    initiative=init_roll,
                    hp=state.current_hp,
                    max_hp=state.max_hp,
                    ac=state.ac,  # Use AC from character data
                    status=state.status.value
                ))

        # Add enemies and NPCs from encounter
        for creature in encounter_data.get("creatures", []):
            if creature.get("type") == "enemy":
                # TABLETOP MODE: Backfill armorClass from monster template if missing
                ac = creature.get("armorClass")
                if ac is None and ModulePathManager and safe_json_load:
                    monster_type = creature.get("monsterType", "").lower()
                    if monster_type:
                        try:
                            # Get current module from encounter data or party tracker
                            module_name = encounter_data.get("module", "").replace(" ", "_")
                            if not module_name:
                                party_tracker = safe_json_load("party_tracker.json") or {}
                                module_name = party_tracker.get("module", "").replace(" ", "_")

                            path_manager = ModulePathManager(module_name if module_name else None)
                            monster_file = path_manager.get_monster_path(monster_type)

                            if monster_file and os.path.exists(monster_file):
                                monster_data = safe_json_load(monster_file)
                                if monster_data:
                                    ac = monster_data.get("armorClass", 10)
                        except Exception as e:
                            # Log lookup failure for debugging, but continue with default AC
                            creature_name = creature.get("name", "Unknown")
                            debug(f"TABLETOP MODE: Monster AC lookup failed for {creature_name} (type: {monster_type}): {e}",
                                  category="combat_events")

                # Default to 10 if still not found
                if ac is None:
                    ac = 10

                self.turn_queue.append(Combatant(
                    name=creature.get("name", "Unknown"),
                    type=CombatantType.ENEMY,
                    initiative=creature.get("initiative", random.randint(1, 20)),
                    hp=creature.get("currentHitPoints", 10),
                    max_hp=creature.get("maxHitPoints", 10),
                    ac=ac,
                    status=creature.get("status", "alive")
                ))
            elif creature.get("type") == "npc":
                 self.turn_queue.append(Combatant(
                    name=creature.get("name", "Unknown"),
                    type=CombatantType.NPC,
                     initiative=creature.get("initiative", random.randint(1, 20)),
                    hp=creature.get("currentHitPoints", 10),
                    max_hp=creature.get("maxHitPoints", 10),
                    ac=creature.get("armorClass", 10),
                    status=creature.get("status", "alive")
                ))

        # Sort by Initiative (Descending)
        self.turn_queue.sort(key=lambda x: x.initiative, reverse=True)
        self.current_turn_index = 0

        # Update current PC if the first actor is a PC
        current_actor = self.get_current_actor()
        if current_actor and current_actor.type == CombatantType.PC and self.state_manager:
            self.state_manager.set_current_pc(current_actor.name)

    def get_current_actor(self) -> Optional[Combatant]:
        """Get the combatant whose turn it is."""
        if not self.turn_queue:
            return None
        return self.turn_queue[self.current_turn_index]

    def advance_turn(self) -> Tuple[Combatant, bool]:
        """
        Move to the next turn in the queue.
        Skips inactive combatants.

        Returns:
            Tuple of (next_actor, round_rolled_over)
            round_rolled_over is True if the index wrapped past the end of the queue
        """
        start_index = self.current_turn_index
        rolled_over = False

        while True:
            self.current_turn_index = (self.current_turn_index + 1) % len(self.turn_queue)

            # Detect round rollover (index wrapped to start)
            if self.current_turn_index == 0:
                rolled_over = True

            actor = self.turn_queue[self.current_turn_index]

            # Skip inactive combatants (dead/defeated/unconscious/etc.)
            if not self._is_inactive_combatant(actor):
                return actor, rolled_over

            # Infinite loop safety (if everyone is dead)
            if self.current_turn_index == start_index:
                return actor, rolled_over

    def find_target(self, partial_name: str, encounter_data: Dict[str, Any]) -> Optional[Combatant]:
        """
        Fuzzy find a target in the encounter.
        Matches partial names (case-insensitive).
        Prioritizes enemies, then living targets.
        """
        partial_raw = str(partial_name or "").strip().lower()
        partial_identity = _normalize_combat_identity(partial_name)
        if not partial_raw and not partial_identity:
            return None

        def _matches(combatant: Combatant) -> bool:
            name_raw = combatant.name.lower()
            name_identity = _normalize_combat_identity(combatant.name)
            raw_match = partial_raw and partial_raw in name_raw
            identity_match = partial_identity and partial_identity in name_identity
            return bool(raw_match or identity_match)

        def _score(combatant: Combatant) -> Tuple[int, int, int, int]:
            name_raw = combatant.name.lower()
            name_identity = _normalize_combat_identity(combatant.name)
            exact_match = int(
                (partial_raw and partial_raw == name_raw)
                or (partial_identity and partial_identity == name_identity)
            )
            prefix_match = int(
                (partial_raw and name_raw.startswith(partial_raw))
                or (partial_identity and name_identity.startswith(partial_identity))
            )
            enemy_priority = int(combatant.type == CombatantType.ENEMY)
            return (exact_match, prefix_match, enemy_priority, combatant.initiative)

        candidates = [combatant for combatant in self.turn_queue if _matches(combatant)]
        if not candidates:
            return None

        living_candidates = [
            combatant for combatant in candidates if not self._is_inactive_combatant(combatant)
        ]
        if not living_candidates:
            return None

        living_enemies = [
            combatant for combatant in living_candidates if combatant.type == CombatantType.ENEMY
        ]
        pool = living_enemies or living_candidates
        return max(pool, key=_score)

    def complete_pc_turn(self, character_name: Optional[str] = None) -> bool:
        """
        Mark a PC's turn as complete.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            character_name: Name of PC (uses current if None)
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            True if successful
        """
        if not self.state_manager:
            return False

        if character_name is None:
            character_name = self.state_manager.current_pc_name

        if not character_name or character_name not in self.state_manager.pc_states:
            return False

        state = self.state_manager.pc_states[character_name]

        # Only mark if currently ready
        if state.status == PCStatus.READY:
            state.mark_acted()
            return True

        return False

    def force_end_pc_phase(self) -> None:
        """Force the PC phase to end, even if not all PCs have acted."""
        self.pc_phase_complete = True
        # Mark all remaining ready PCs as acted
        if self.state_manager:
            for name, state in self.state_manager.pc_states.items():
                if state.status == PCStatus.READY:
                    state.mark_acted()

    @staticmethod
    def _is_inactive_combatant(combatant: Combatant) -> bool:
        """Return True if combatant should be skipped by turn progression."""
        status = (combatant.status or "").strip().lower()
        if status in ("dead", "defeated", "incapacitated", "unconscious", "stable"):
            return True

        try:
            return int(combatant.hp) <= 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_valid_enemy_phase_actor(combatant: Combatant) -> bool:
        """Return True if combatant is a living non-PC actor for enemy phase."""
        if combatant.type not in (CombatantType.ENEMY, CombatantType.NPC):
            return False

        return not TurnQueueManager._is_inactive_combatant(combatant)

    def get_remaining_enemies_for_round(self) -> List[str]:
        """Get list of enemies and allied NPCs who haven't acted this round."""
        if not self.turn_queue:
            return []

        remaining = []
        seen_names = set()

        # DETERMINISM: Ignore current_turn_index and return all living non-PC
        # actors in initiative order exactly once.
        for combatant in self.turn_queue:
            normalized_name = str(combatant.name).strip().lower()
            if normalized_name in seen_names:
                continue

            # TABLETOP MODE: C4.1 - Deterministic actor list for valid living non-PC actors
            if self._is_valid_enemy_phase_actor(combatant):
                remaining.append(combatant.name)
                seen_names.add(normalized_name)

        return remaining

    def sync_non_pc_state_from_encounter(self, encounter_data: Dict[str, Any]) -> bool:
        """Refresh enemy/NPC queue state from authoritative encounter data."""
        creatures = encounter_data.get("creatures", []) if isinstance(encounter_data, dict) else []
        if not creatures or not self.turn_queue:
            return False

        encounter_index: Dict[str, Dict[str, Any]] = {}
        for creature in creatures:
            creature_type = str(creature.get("type", "")).strip().lower()
            if creature_type not in ("enemy", "npc"):
                continue

            normalized_name = _normalize_combat_identity(creature.get("name", ""))
            if normalized_name and normalized_name not in encounter_index:
                encounter_index[normalized_name] = creature

        changed = False
        for combatant in self.turn_queue:
            if combatant.type not in (CombatantType.ENEMY, CombatantType.NPC):
                continue

            source = encounter_index.get(_normalize_combat_identity(combatant.name))
            if not source:
                continue

            try:
                new_hp = int(source.get("currentHitPoints", combatant.hp))
            except (TypeError, ValueError):
                new_hp = combatant.hp

            try:
                new_max_hp = int(source.get("maxHitPoints", combatant.max_hp))
            except (TypeError, ValueError):
                new_max_hp = combatant.max_hp

            try:
                new_ac = int(source.get("armorClass", combatant.ac))
            except (TypeError, ValueError):
                new_ac = combatant.ac

            new_status = str(source.get("status", combatant.status) or combatant.status).strip().lower()

            if combatant.hp != new_hp:
                combatant.hp = new_hp
                changed = True
            if combatant.max_hp != new_max_hp:
                combatant.max_hp = new_max_hp
                changed = True
            if combatant.ac != new_ac:
                combatant.ac = new_ac
                changed = True
            if (combatant.status or "").strip().lower() != new_status:
                combatant.status = new_status
                changed = True

        return changed
