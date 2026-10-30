# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# ============================================================================
# MULTI_PC_COMBAT.PY - Multi-Player Character Combat Manager
# ============================================================================
#
# ARCHITECTURE ROLE: Plugin-style module for multi-PC combat support
#
# This module isolates all multi-PC combat logic to enable easy upstream merging.
# It is activated when MULTIPLAYER_MODE = True in config.py.
#
# KEY RESPONSIBILITIES:
# - Track which PCs have acted in the current combat round
# - Manage PC turn order (player-selected via UI tab clicks)
# - Handle group initiative (PC Party vs Enemies)
# - Prompt incapacitated PCs for death saving throws
# - Coordinate with existing combat system via hooks
# - Manage Turn Queue (Initiative Order)
# - Handle Combat Commands (/att, /dmg) locally
#
# DESIGN PRINCIPLES:
# - Plugin architecture: minimal changes to existing files
# - All multi-PC logic contained in this module
# - Feature flag: MULTIPLAYER_MODE controls activation
# - LLM combat agency: enemies target via LLM decision
# ============================================================================

import random
import json
import re
import time
from typing import Callable, Dict, List, Optional, Any, Tuple, Generator

from .state import (
    PCStatus,
    PCCombatState,
    CombatStateManager,
    _normalize_combat_identity,
)
from . import state as _state_module
from .turn_queue import CombatantType, Combatant, TurnQueueManager
from ..context_cache import CombatContextCache, canonical_json_digest, encounter_revision
from core.combat import narration as combat_narration
from core.combat.cover import cover_label, effective_ac_for_creature
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
import os
import sys
import threading
import types

# Import config to check MULTIPLAYER_MODE
try:
    from config import MULTIPLAYER_MODE
except ImportError:
    MULTIPLAYER_MODE = False

try:
    from model_config import COMBAT_FAST_DETERMINISTIC_NARRATION
except ImportError:
    COMBAT_FAST_DETERMINISTIC_NARRATION = True

# TABLETOP MODE: Internal imports - fail fast if missing
from utils.module_path_manager import ModulePathManager
from utils.enhanced_logger import debug, info, error
from utils.combat_latency_trace import (
    build_work_unit_trace_context,
    set_trace_context,
    trace_decision,
)


# Initial real module binding; state synchronizes it on direct state-level writes.
safe_json_load = _state_module.safe_json_load

# TABLETOP MODE: Debug utilities
# Defer import to method level to handle missing module gracefully during development
_tabletop_debug_available = None

def _get_tabletop_debug():
    """Lazy import of tabletop debug utilities"""
    global _tabletop_debug_available
    if _tabletop_debug_available is None:
        try:
            from utils import tabletop_debug
            _tabletop_debug_available = tabletop_debug
        except ImportError:
            _tabletop_debug_available = None
    return _tabletop_debug_available


def _normalize_combat_identity(name: Any) -> str:
    """Normalize character/combatant names for canonical identity checks."""
    normalized = str(name or "").strip().lower()
    normalized = normalized.replace(" ", "_")
    normalized = normalized.replace("'", "_")
    normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _select_deterministic_template(seed_parts: List[Any], templates: List[str]) -> str:
    """Pick a stable narration template from combat facts."""
    return combat_narration.select_deterministic_template(seed_parts, templates)


def _build_fast_path_narration(
    kind: str,
    actor_name: str,
    target_name: str,
    weapon_name: Optional[str] = None,
    roll: Optional[int] = None,
    ac: Optional[int] = None,
    amount: Optional[int] = None,
    hp_before: Optional[int] = None,
    hp_after: Optional[int] = None,
    status_text: Optional[str] = None,
    flavor_text: Optional[str] = None,
) -> str:
    """Build deterministic ASCII-only combat narration for local fast-path commands."""
    attack_name = (weapon_name or flavor_text or "strike").strip()
    if kind == "attack_miss":
        templates = [
            "{actor}'s {attack_name} cuts empty air as {target} slips just outside the strike.",
            "{actor} commits to the blow, but {target} twists away before the {attack_name} lands.",
            "{target} jerks aside, and {actor}'s {attack_name} scrapes harmlessly past.",
            "{actor}'s {attack_name} whistles past {target} with no purchase.",
        ]
        return _select_deterministic_template([kind, actor_name, target_name, attack_name, roll, ac], templates).format(
            actor=actor_name,
            attack_name=attack_name,
            target=target_name,
        )

    if kind == "damage":
        defeated = str(status_text or "").lower() in {"dead", "defeated", "unconscious"} or (hp_after is not None and hp_after <= 0)
        bloodied = bool(hp_before is not None and hp_after is not None and hp_before > 0 and hp_after > 0 and hp_after <= (hp_before / 2))
        templates = (
            [
                "{actor}'s {attack_name} crashes through {target}, and it collapses in a broken heap.",
                "{actor} drives the final blow home, and {target} drops out of the fight.",
                "{target} buckles under {actor}'s {attack_name} and falls still.",
            ]
            if defeated
            else [
                "{actor}'s {attack_name} lands hard, driving {target} back with a sharp impact.",
                "{actor} catches {target} cleanly with the {attack_name}, forcing it to stagger.",
                "{actor}'s strike bites into {target}, leaving it reeling but still fighting.",
            ]
        )
        if bloodied and not defeated:
            templates = [
                "{actor}'s {attack_name} tears into {target}, leaving it staggered and visibly weakened.",
                "{target} reels under {actor}'s blow, its defense breaking for a dangerous moment.",
                "{actor}'s strike drives {target} back, and the fight starts to turn.",
            ]
        return _select_deterministic_template([kind, actor_name, target_name, attack_name, amount, hp_before, hp_after, status_text], templates).format(
            actor=actor_name,
            attack_name=attack_name,
            target=target_name,
        )

    return f"{actor_name} resolves the action against {target_name}."


@dataclass
class MultiPCCombatManager:
    """
    Manages combat state for multiple player characters.
\x20\x20\x20\x20
    This is the core class for multi-PC combat support. It coordinates between
    CombatStateManager (PC states) and TurnQueueManager (initiative/turns).
\x20\x20\x20\x20
    ARCHITECTURE: Facade pattern - thin coordinator over focused sub-managers
    """

    # Sub-managers (initialized in __post_init__)
    _state: CombatStateManager = field(init=False)
    _turns: TurnQueueManager = field(init=False)
    _context_cache: CombatContextCache = field(
        init=False, default_factory=CombatContextCache, repr=False
    )
    _context_encounter: Optional[Dict[str, Any]] = field(
        init=False, default=None, repr=False
    )

    # Narrative Context (stored between commands)
    last_attack_weapon: Optional[str] = None
    last_target: Optional[Combatant] = None

    # Combat constants
    DEFAULT_AC: int = 10  # Default Armor Class when not specified
    INITIATIVE_DIE: int = 20  # d20 for initiative rolls
    MAX_PARTY_SIZE: int = 6  # Maximum party size (hard limit)

    # UPSTREAM ALIGNMENT: Consolidated character updates (deferred persistence)
    # Tracks pending HP/status changes to be written at combat end
    # Format: {character_name: ["change string 1", "change string 2", ...]}
    pending_character_updates: Dict[str, List[str]] = field(default_factory=dict)

    # TABLETOP MODE: Historical PC_PHASE event ledger (compact, replay-safe)
    pc_phase_event_ledger: List[Dict[str, Any]] = field(default_factory=list)
    pc_phase_event_keys: Dict[str, int] = field(default_factory=dict)
    pc_phase_event_sequence: int = 0

    # TABLETOP MODE: Deterministic death-save tracking
    # Maps PC name -> round number when death save was resolved this PC phase.
    death_save_resolved_phases: Dict[str, int] = field(default_factory=dict)
    # Maps PC name -> round number when death-save prompt was emitted.
    death_save_prompted_phases: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize sub-managers with default state."""
        self._state = CombatStateManager()
        self._turns = TurnQueueManager(state_manager=self._state)

    def bind_context_encounter(self, encounter: Optional[Dict[str, Any]]) -> None:
        """Bind the authoritative encounter used to revision prompt cache keys."""
        self._context_encounter = encounter if isinstance(encounter, dict) else None

    def _context_render_input_snapshot(self) -> Dict[str, Any]:
        """Snapshot every mutable manager input read by the memoized renderers."""
        pc_states = []
        for name, state in self._state.pc_states.items():
            status = getattr(state.status, "value", state.status)
            pc_states.append({
                "name": name,
                "character_name": state.character_name,
                "initiative_modifier": state.initiative_modifier,
                "status": status,
                "death_save_successes": state.death_save_successes,
                "death_save_failures": state.death_save_failures,
                "current_hp": state.current_hp,
                "max_hp": state.max_hp,
                "ac": state.ac,
                "metadata": state.metadata,
            })

        turn_queue = []
        for combatant in self._turns.turn_queue:
            combatant_type = getattr(combatant.type, "value", combatant.type)
            turn_queue.append({
                "name": combatant.name,
                "type": combatant_type,
                "initiative": combatant.initiative,
                "hp": combatant.hp,
                "max_hp": combatant.max_hp,
                "ac": combatant.ac,
                "status": combatant.status,
                "metadata": combatant.metadata,
            })

        return {
            "round": self._state.current_round,
            "active_pc": self._state.current_pc_name,
            "party_initiative": self._state.party_initiative,
            "enemy_initiative": self._state.enemy_initiative,
            "party_goes_first": self._state.party_goes_first,
            "pc_phase_complete": self._turns.pc_phase_complete,
            "enemy_phase_complete": self._turns.enemy_phase_complete,
            "current_turn_index": self._turns.current_turn_index,
            "pc_states": pc_states,
            "turn_queue": turn_queue,
            "pc_phase_event_ledger": self.pc_phase_event_ledger,
        }

    def _set_pc_command_trace_context(
        self,
        encounter_data: Dict[str, Any],
        actor_name: str,
    ) -> None:
        """Attribute a PC command to the actor resolved from its input."""
        if self.combat_phase != "PC_PHASE":
            return

        normalized_actor = _normalize_combat_identity(actor_name)
        active_pc = next(
            (name for name in self._state.pc_states
             if _normalize_combat_identity(name) == normalized_actor),
            None,
        ) or self.current_pc_name
        if not active_pc:
            return

        combat_round = (
            encounter_data.get("combat_round")
            if isinstance(encounter_data, dict) else None
        )
        if not isinstance(combat_round, int) or isinstance(combat_round, bool):
            combat_round = self._state.current_round
        context = {
            "mode": "mp",
            "phase": "PC_PHASE",
            "combat_round": combat_round,
        }
        context.update(
            build_work_unit_trace_context(combat_round, "PC_PHASE", active_pc)
        )
        if "action_id" in context:
            set_trace_context(**context)

    def _memoized_context_render(
        self,
        renderer_name: str,
        renderer_arguments: Dict[str, Any],
        render: Callable[[], str],
    ) -> str:
        """Memoize only when encounter and all manager-render inputs are digestible."""
        try:
            encounter_digest = encounter_revision(self._context_encounter)
            manager_inputs_digest = canonical_json_digest(
                self._context_render_input_snapshot(),
                sort_keys=False,
            )
            renderer_key = canonical_json_digest(
                {"renderer": renderer_name, "arguments": renderer_arguments},
                sort_keys=True,
            )
            if encounter_digest is None or manager_inputs_digest is None or renderer_key is None:
                return render()

            # The fourth state-key component carries the required canonical
            # encounter revision plus the audited mutable renderer inputs.
            revision = canonical_json_digest({
                "encounter_revision": encounter_digest,
                "manager_inputs_revision": manager_inputs_digest,
            })
            if revision is None:
                return render()
            state_key = (
                self._state.current_round,
                self.combat_phase,
                self.current_pc_name,
                revision,
            )
        except Exception:
            # Cache-key construction is an optimization; legacy rendering must
            # remain available when a state snapshot cannot be digested.
            return render()
        return self._context_cache.get_or_render(state_key, renderer_key, render)

    @classmethod
    def is_enabled(cls) -> bool:
        """Check if multi-PC combat is enabled."""
        return MULTIPLAYER_MODE

    # ========================================================================
    # PHASE 1 OPTIMIZATION: Explicit Phase Tracking
    # ========================================================================

    @property
    def combat_phase(self) -> str:
        """
        Get the current combat phase as an explicit string.
\x20\x20\x20\x20\x20\x20\x20\x20
        This provides clear phase indication for LLM prompts to prevent
        confusion about when enemies should act.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            "PC_PHASE" - PCs are still taking their turns
            "ENEMY_PHASE" - All PCs have acted, enemies can now resolve
        """
        if self._turns.pc_phase_complete:
            return "ENEMY_PHASE"
        return "PC_PHASE"

    @property
    def pc_states(self) -> Dict[str, PCCombatState]:
        """
        Backward compatibility property for accessing PC states.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Dictionary mapping character names to PCCombatState objects
        """
        return self._state.pc_states

    @property
    def current_pc_name(self) -> Optional[str]:
        """
        Backward compatibility property for current active PC.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Name of the currently active PC, or None
        """
        return self._state.current_pc_name

    @property
    def party_initiative(self) -> int:
        """Backward compatibility property for party initiative."""
        return self._state.party_initiative

    @party_initiative.setter
    def party_initiative(self, value: int) -> None:
        """Backward compatibility setter for party initiative."""
        self._state.party_initiative = value

    @property
    def enemy_initiative(self) -> int:
        """Backward compatibility property for enemy initiative."""
        return self._state.enemy_initiative

    @enemy_initiative.setter
    def enemy_initiative(self, value: int) -> None:
        """Backward compatibility setter for enemy initiative."""
        self._state.enemy_initiative = value

    @property
    def party_goes_first(self) -> bool:
        """Backward compatibility property for party initiative order."""
        return self._state.party_goes_first

    @party_goes_first.setter
    def party_goes_first(self, value: bool) -> None:
        """Backward compatibility setter for party initiative order."""
        self._state.party_goes_first = value

    @property
    def pc_phase_complete(self) -> bool:
        """Backward compatibility property for PC phase completion status."""
        return self._turns.pc_phase_complete

    @pc_phase_complete.setter
    def pc_phase_complete(self, value: bool) -> None:
        """Backward compatibility setter for PC phase completion status."""
        self._turns.pc_phase_complete = value

    @property
    def current_round(self) -> int:
        """Backward compatibility property for current combat round."""
        return self._state.current_round

    @current_round.setter
    def current_round(self, value: int) -> None:
        """Backward compatibility setter for current combat round."""
        self._state.current_round = value

    def get_forbidden_actors(self) -> List[str]:
        """
        Get list of combatants that MUST NOT act during the current phase.
\x20\x20\x20\x20\x20\x20\x20\x20
        During PC_PHASE: Returns all enemies and NPCs (they must wait for /end)
        During ENEMY_PHASE: Returns empty list (enemies are free to act)
\x20\x20\x20\x20\x20\x20\x20\x20
        This creates a hard block for the LLM to prevent premature enemy narration.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            List of combatant names that are forbidden from acting
        """
        if not self._turns.pc_phase_complete:
            # During PC phase, all enemies and NPCs are forbidden
            return [
                c.name for c in self._turns.turn_queue
                if self._turns._is_valid_enemy_phase_actor(c)
            ]
        # During enemy phase, no restrictions
        return []

    def get_next_pc_to_act(self) -> Optional[str]:
        """
        Get the name of the next PC who hasn't acted yet.
\x20\x20\x20\x20\x20\x20\x20\x20
        Used for the "What does [PC_NAME] do?" prompt continuation.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Name of next PC to act, or None if all have acted
        """
        available = self.get_available_pcs()
        if not available:
            return None
        # Return first available PC that isn't the current one
        for pc in available:
            if pc != self._state.current_pc_name:
                return pc
        # If current PC is the only one left, return them
        return available[0] if available else None

    def initialize_from_party(self, party_data: Dict[str, Any]) -> None:
        """
        Initialize PC states from party tracker data.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to CombatStateManager - see CombatStateManager.initialize_from_party() for details.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            party_data: The party_tracker.json data
        """
        # TABLETOP MODE: Debug party loading
        tt_debug = _get_tabletop_debug()
        if tt_debug:
            party_members = party_data.get("partyMembers", [])
            tt_debug.log_tabletop_event("party_load_start", {
                "member_count": len(party_members),
                "members": party_members
            }, verbose=tt_debug.is_tabletop_verbose())

        self._state.initialize_from_party(party_data)

        # TABLETOP MODE: Debug party loaded
        if tt_debug:
            tt_debug.log_tabletop_event("party_load_complete", {
                "pc_count": len(self._state.pc_states),
                "loaded_pcs": list(self._state.pc_states.keys())
            }, verbose=tt_debug.is_tabletop_verbose())

    def initialize_turn_queue(self, encounter_data: Dict[str, Any]) -> None:
        """
        Build the turn queue from PC states and encounter data.
        Call this at the start of combat or when initiative changes.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to TurnQueueManager - see TurnQueueManager.initialize_turn_queue() for details.
        """
        self._context_cache.clear()
        self.bind_context_encounter(encounter_data)
        # TABLETOP MODE: Debug queue initialization
        tt_debug = _get_tabletop_debug()
        if tt_debug:
            tt_debug.log_tabletop_event("turn_queue_init_start", {
                "encounter_id": encounter_data.get("id", "unknown"),
                "creature_count": len(encounter_data.get("creatures", []))
            }, verbose=tt_debug.is_tabletop_verbose())

        self._turns.initialize_turn_queue(encounter_data)

        # TABLETOP MODE: Debug queue initialized
        if tt_debug:
            current_actor = self._turns.get_current_actor()
            tt_debug.log_tabletop_event("turn_queue_init_complete", {
                "queue_size": len(self._turns.turn_queue),
                "current_actor": current_actor.name if current_actor else None
            }, verbose=tt_debug.is_tabletop_verbose())

    def get_current_actor(self) -> Optional[Combatant]:
        """Get the combatant whose turn it is.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to TurnQueueManager - see TurnQueueManager.get_current_actor() for details.
        """
        return self._turns.get_current_actor()

    def advance_turn(self) -> Combatant:
        """
        Move to the next turn in the queue.
        Skips dead combatants. Handles round rollover coordination.

        Delegates to TurnQueueManager.advance_turn() and performs
        cross-manager coordination if the round rolls over.

        Returns:
            The next active Combatant
        """
        # TABLETOP MODE: Debug turn advancement
        tt_debug = _get_tabletop_debug()
        old_actor = self.get_current_actor()
        old_name = old_actor.name if old_actor else None

        result, rolled_over = self._turns.advance_turn()

        # Coordination: handle round rollover
        if rolled_over:
            self._state.current_round += 1
            for state in self._state.pc_states.values():
                state.reset_for_new_round()
            self._turns.pc_phase_complete = False
            self._turns.enemy_phase_complete = False

        # Coordination: update active PC if next actor is a PC
        if result.type == CombatantType.PC:
            self._state.set_current_pc(result.name)

        # TABLETOP MODE: Debug turn advanced
        if tt_debug:
            new_name = result.name if result else None

            if old_name != new_name:
                tt_debug.log_tabletop_event("turn_advanced", {
                    "from_actor": old_name,
                    "to_actor": new_name,
                    "round": self._state.current_round,
                    "queue_index": self._turns.current_turn_index,
                    "round_rolled_over": rolled_over
                }, verbose=tt_debug.is_tabletop_verbose())

                if result and result.type == CombatantType.PC and new_name:
                    tt_debug.log_state_transition(new_name, "waiting", "acting", reason="turn_advanced")

        return result

    def find_target(self, partial_name: str, encounter_data: Dict[str, Any]) -> Optional[Combatant]:
        """
        Fuzzy find a target in the encounter.
        Matches partial names (case-insensitive).
        Prioritizes enemies, then living targets.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to TurnQueueManager - see TurnQueueManager.find_target() for details.
        """
        return self._turns.find_target(partial_name, encounter_data)

    def _compact_ledger_text(self, value: Any) -> str:
        """Return an ASCII-safe compact string for ledger storage."""
        text = "" if value is None else str(value)
        text = text.encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _normalize_ledger_value(self, value: Any) -> Any:
        """Recursively normalize ledger values for compact ASCII-safe storage."""
        if isinstance(value, dict):
            return {
                self._compact_ledger_text(key): self._normalize_ledger_value(subvalue)
                for key, subvalue in value.items()
            }
        if isinstance(value, list):
            return [self._normalize_ledger_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._normalize_ledger_value(item) for item in value]
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return value
        return self._compact_ledger_text(value)

    def _build_pc_phase_ledger_source_key(
        self,
        *,
        kind: str,
        actor_name: str,
        target_name: Optional[str],
        facts: Dict[str, Any],
        mechanics_already_applied: bool,
        round_number: Optional[int] = None,
    ) -> str:
        payload = {
            "round": round_number if round_number is not None else self._state.current_round,
            "kind": self._compact_ledger_text(kind).lower(),
            "actor": self._compact_ledger_text(actor_name).lower(),
            "target": self._compact_ledger_text(target_name or "").lower(),
            "facts": self._normalize_ledger_value(facts),
            "mechanics_already_applied": mechanics_already_applied,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def record_pc_phase_event(
        self,
        kind: str,
        actor_name: str,
        target_name: Optional[str] = None,
        *,
        facts: Optional[Dict[str, Any]] = None,
        narration: Optional[str] = None,
        mechanics_already_applied: bool = True,
        source_key: Optional[str] = None,
        round_number: Optional[int] = None,
        phase: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record a compact historical PC_PHASE event if it has not been seen."""
        normalized_kind = self._compact_ledger_text(kind).lower()
        allowed_kinds = {
            "attack_miss",
            "attack_hit_pending_damage",
            "attack_damage",
            "spell_damage",
            "spell_healing",
            "movement",
            "death_save",
            "manual_note",
        }
        if normalized_kind not in allowed_kinds:
            return None

        normalized_source_key = source_key or self._build_pc_phase_ledger_source_key(
            kind=normalized_kind,
            actor_name=actor_name,
            target_name=target_name,
            facts=facts or {},
            mechanics_already_applied=mechanics_already_applied,
        )
        if normalized_source_key in self.pc_phase_event_keys:
            return None

        event = {
            "round": round_number if round_number is not None else self._state.current_round,
            "sequence": self.pc_phase_event_sequence + 1,
            "phase": self._compact_ledger_text(phase or self.combat_phase),
            "actor": self._compact_ledger_text(actor_name),
            "kind": normalized_kind,
            "target": self._compact_ledger_text(target_name) if target_name else "",
            "facts": self._normalize_ledger_value(facts or {}),
            "narration": self._compact_ledger_text(narration),
            "mechanics_already_applied": bool(mechanics_already_applied),
        }

        self.pc_phase_event_sequence = event["sequence"]
        self.pc_phase_event_ledger.append(event)
        self.pc_phase_event_keys[normalized_source_key] = event["sequence"]

        if len(self.pc_phase_event_ledger) > 64:
            trimmed = self.pc_phase_event_ledger.pop(0)
            for key, seq in list(self.pc_phase_event_keys.items()):
                if seq == trimmed.get("sequence"):
                    self.pc_phase_event_keys.pop(key, None)
                    break

        return event

    def get_pc_phase_event_ledger(self, round_number: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return a shallow copy of ledger entries, optionally filtered by round."""
        if round_number is None:
            return list(self.pc_phase_event_ledger)
        return [entry for entry in self.pc_phase_event_ledger if entry.get("round") == round_number]

    def format_pc_phase_event_ledger_for_prompt(
        self,
        round_number: Optional[int] = None,
        limit: int = 8,
    ) -> str:
        """Format historical ledger facts for optional prompt context."""
        return self._memoized_context_render(
            "pc_phase_event_ledger",
            {"round_number": round_number, "limit": limit},
            lambda: self._render_pc_phase_event_ledger_for_prompt(round_number, limit),
        )

    def _render_pc_phase_event_ledger_for_prompt(
        self,
        round_number: Optional[int] = None,
        limit: int = 8,
    ) -> str:
        """Render ledger content without memoization."""
        entries = self.get_pc_phase_event_ledger(round_number=round_number)
        if not entries:
            return ""

        selected = entries[-max(1, limit):]
        lines = ["=== PC PHASE RECAP FACTS (HISTORICAL ONLY; DO NOT REPLAY MECHANICS) ==="]
        for entry in selected:
            facts = entry.get("facts", {}) if isinstance(entry.get("facts"), dict) else {}
            kind = entry.get("kind", "")
            actor = entry.get("actor", "")
            target = entry.get("target", "")
            parts = [f"Round {entry.get('round', '?')}:" ]
            if actor:
                parts.append(actor)

            if kind == "attack_miss":
                detail = ["missed"]
                if target:
                    detail.append(target)
                if facts.get("weapon"):
                    detail.append(f"with {facts.get('weapon')}")
                if facts.get("roll") is not None and facts.get("ac") is not None:
                    detail.append(f"roll {facts.get('roll')} vs AC {facts.get('ac')}")
                parts.append(" ".join(detail))
            elif kind in ("attack_hit_pending_damage", "attack_damage", "spell_damage"):
                detail = [kind.replace("_", " ")]
                if target:
                    detail.append(target)
                damage = facts.get("damage") if facts.get("damage") is not None else facts.get("amount")
                if damage is not None:
                    detail.append(f"for {damage}")
                if facts.get("hp_before") is not None and facts.get("hp_after") is not None:
                    detail.append(f"HP {facts.get('hp_before')} -> {facts.get('hp_after')}")
                if facts.get("status"):
                    detail.append(f"status {facts.get('status')}")
                parts.append(" ".join(detail))
            elif kind == "spell_healing":
                detail = ["healed"]
                if target:
                    detail.append(target)
                healing = facts.get("healing") if facts.get("healing") is not None else facts.get("amount")
                if healing is not None:
                    detail.append(f"for {healing}")
                if facts.get("hp_before") is not None and facts.get("hp_after") is not None:
                    detail.append(f"HP {facts.get('hp_before')} -> {facts.get('hp_after')}")
                parts.append(" ".join(detail))
            elif kind == "death_save":
                detail = ["death save"]
                if target:
                    detail.append(target)
                if facts.get("roll") is not None:
                    detail.append(f"roll {facts.get('roll')}")
                if facts.get("result"):
                    detail.append(self._compact_ledger_text(facts.get("result")))
                parts.append(" ".join(detail))
            elif kind == "movement":
                detail = ["moved"]
                if target:
                    detail.append(target)
                destination = facts.get("destination") if facts.get("destination") is not None else facts.get("location")
                if destination:
                    detail.append(f"to {destination}")
                parts.append(" ".join(detail))
            else:
                note = entry.get("narration") or facts.get("note") or "manual note"
                parts.append(self._compact_ledger_text(note))

            lines.append("- " + " ".join(bit for bit in parts if bit))

        return "\n".join(lines)

    def clear_pc_phase_event_ledger(self) -> None:
        """Clear the historical PC_PHASE ledger at combat completion."""
        self.pc_phase_event_ledger.clear()
        self.pc_phase_event_keys.clear()
        self.pc_phase_event_sequence = 0

    def handle_combat_command(
        self,
        cmd: str,
        encounter_data: Dict[str, Any],
        actor_name: str = "Player",
        *,
        active_encounter_id: Optional[str] = None,
        tactical_features: Any = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
        """
        Process a local combat command.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            cmd: The user input string (e.g., "/att goblin 18")
            encounter_data: Current encounter state
            actor_name: Name of the character performing the action
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple(MechanicalFeedback, SpokenNarration, SystemLogInjection, SkipLLM)
            - MechanicalFeedback: [skipTTS] string to show user immediately (or None)
            - SpokenNarration: Deterministic DM narration spoken by TTS (or None)
            - SystemLogInjection: String to inject into LLM history (or None)
            - SkipLLM: True when the combat loop should continue without a fresh combat LLM prompt
        """
        # TABLETOP MODE: Debug entry
        tt_debug = _get_tabletop_debug()
        if tt_debug:
            tt_debug.log_tabletop_event("combat_command_entry", {
                "cmd": cmd[:50] if len(cmd) > 50 else cmd,
                "actor": actor_name,
                "encounter_id": encounter_data.get("id", "unknown")
            }, verbose=tt_debug.is_tabletop_verbose())

        parts = cmd.strip().split()
        if not parts:
            return None, None, None, False

        command = parts[0].lower()
        args = parts[1:]
        if command in ("/att", "/dmg"):
            # The active PC can change between commands in one round. The turn
            # loop's context was established before input processing, so refresh
            # attribution from this command's already-resolved actor.
            self._set_pc_command_trace_context(encounter_data, actor_name)
        # TABLETOP MODE: combat latency trace (Phase 0)
        _decision_start = time.perf_counter()
        fast_path_enabled = COMBAT_FAST_DETERMINISTIC_NARRATION

        normalized_actor = _normalize_combat_identity(actor_name)
        acting_pc_state: Optional[PCCombatState] = None
        for pc_name, pc_state in self._state.pc_states.items():
            if _normalize_combat_identity(pc_name) == normalized_actor:
                acting_pc_state = pc_state
                break

        if command in ("/att", "/dmg") and acting_pc_state and acting_pc_state.status in (
            PCStatus.INCAPACITATED,
            PCStatus.DEAD,
            PCStatus.STABLE,
        ):
            return (
                f"[skipTTS] Dungeon Master: [SYSTEM] {acting_pc_state.character_name} cannot use {command} while at 0 HP. Resolve the required death save first.",
                None,
                None,
                True,
            )

        if command == "/att":
            # Syntax: /att [target] [roll] [optional: weapon]
            if len(args) < 2:
                return "Dungeon Master: [SYSTEM] Usage: /att [target] [roll] [weapon]", None, None, False

            # Check if optional weapon argument is present (last argument if not a number)
            # Standard args: target... roll
            # Enhanced args: target... roll weapon...

            # Find the roll (first number from the right)
            roll_index = -1
            roll = None
            weapon_parts = []

            # Iterate backwards to find the roll
            for i in range(len(args) - 1, -1, -1):
                try:
                    roll = int(args[i])
                    roll_index = i
                    break
                except ValueError:
                    weapon_parts.insert(0, args[i])

            if roll is None:
                return "Dungeon Master: [SYSTEM] Invalid roll. Usage: /att [target] [roll] [weapon]", None, None, False

            # Target is everything before the roll
            target_name = " ".join(args[:roll_index])

            # Weapon is everything after the roll (already collected in weapon_parts)
            weapon_name = " ".join(weapon_parts) if weapon_parts else None

            # Store weapon for context carry-over
            if weapon_name:
                self.last_attack_weapon = weapon_name
            else:
                self.last_attack_weapon = None

            target = self.find_target(target_name, encounter_data)
            if not target:
                return f"Dungeon Master: [SYSTEM] Target '{target_name}' not found.", None, None, False

            # Store as last target for /dmg command
            self.last_target = target

            # Check Hit (AC) from the authoritative encounter projection.
            target_rows = [
                creature for creature in encounter_data.get("creatures", [])
                if isinstance(creature, dict)
                and _normalize_combat_identity(creature.get("name"))
                == _normalize_combat_identity(target.name)
            ]
            target_creature = target_rows[0] if len(target_rows) == 1 else None
            base_ac = (
                target_creature.get("armorClass")
                if target_creature is not None else None
            )
            if base_ac is None or base_ac == 0:
                base_ac = target.ac
            if base_ac is None or base_ac == 0:
                base_ac = MultiPCCombatManager.DEFAULT_AC
            encounter_id = encounter_data.get("encounterId", encounter_data.get("id"))
            combat_in_progress = (
                isinstance(active_encounter_id, str)
                and bool(active_encounter_id.strip())
                and active_encounter_id.strip() == encounter_id
            )
            ac = effective_ac_for_creature(
                base_ac,
                target_creature,
                encounter_id=encounter_id,
                active_encounter_id=active_encounter_id,
                combat_in_progress=combat_in_progress,
                tactical_features=tactical_features,
            )
            applied_cover = (
                cover_label(target_creature.get("coverType"))
                if target_creature is not None and ac != base_ac else None
            )
            ac_display = f"{ac} ({applied_cover})" if applied_cover else str(ac)

            if roll >= ac:
                # TABLETOP MODE: Debug hit
                if tt_debug:
                    tt_debug.log_tabletop_event("combat_command_hit", {
                        "target": target.name,
                        "roll": roll,
                        "ac": ac,
                        "base_ac": base_ac,
                        "cover": applied_cover or "",
                        "result": "waiting_for_damage"
                    }, verbose=tt_debug.is_tabletop_verbose())

                # TABLETOP MODE: Add prefill marker so UI auto-populates /dmg command
                self.record_pc_phase_event(
                    kind="attack_hit_pending_damage",
                    actor_name=actor_name,
                    target_name=target.name,
                    facts={
                        "roll": roll,
                        "ac": ac,
                        "cover": applied_cover or "",
                        "weapon": weapon_name or "",
                        "damage_pending": True,
                    },
                    narration=f"{actor_name} hit {target.name}; damage pending.",
                    mechanics_already_applied=True,
                    source_key=self._build_pc_phase_ledger_source_key(
                        kind="attack_hit_pending_damage",
                        actor_name=actor_name,
                        target_name=target.name,
                        facts={"roll": roll, "ac": ac, "cover": applied_cover or "", "weapon": weapon_name or "", "damage_pending": True},
                        mechanics_already_applied=True,
                    ),
                )
                # TABLETOP MODE: combat latency trace (Phase 0)
                trace_decision(
                    "combat_command_fast_path",
                    "deterministic",
                    _decision_start,
                    True,
                )
                return (
                    f"[skipTTS][ALREADY_APPLIED][prefill:/dmg ] Dungeon Master: Hit! (Rolled {roll} vs AC {ac_display}). Roll damage.",
                    None,
                    None,
                    True,
                )
            else:
                # Miss logic - pass to LLM for narration
                weapon_context = f" with {weapon_name}" if weapon_name else ""
                log_msg = f"[ALREADY_APPLIED] [System: {actor_name} attacked {target.name}{weapon_context} with roll {roll} vs AC {ac_display} and MISSED.]"
                narration = _build_fast_path_narration(
                    kind="attack_miss",
                    actor_name=actor_name,
                    target_name=target.name,
                    weapon_name=weapon_name,
                    roll=roll,
                    ac=ac,
                )

                # TABLETOP MODE: Debug miss
                if tt_debug:
                    tt_debug.log_tabletop_event("combat_command_miss", {
                        "target": target.name,
                        "roll": roll,
                        "ac": ac,
                        "base_ac": base_ac,
                        "cover": applied_cover or "",
                        "has_feedback": True,
                        "has_log_msg": True,
                        "result": "continue_to_llm"
                    }, verbose=tt_debug.is_tabletop_verbose())

                self.record_pc_phase_event(
                    kind="attack_miss",
                    actor_name=actor_name,
                    target_name=target.name,
                    facts={
                        "roll": roll,
                        "ac": ac,
                        "cover": applied_cover or "",
                        "weapon": weapon_name or "",
                    },
                    narration=narration,
                    mechanics_already_applied=True,
                    source_key=self._build_pc_phase_ledger_source_key(
                        kind="attack_miss",
                        actor_name=actor_name,
                        target_name=target.name,
                        facts={"roll": roll, "ac": ac, "cover": applied_cover or "", "weapon": weapon_name or ""},
                        mechanics_already_applied=True,
                    ),
                )

                if fast_path_enabled:
                    # TABLETOP MODE: combat latency trace (Phase 0)
                    trace_decision(
                        "combat_command_fast_path",
                        "deterministic",
                        _decision_start,
                        True,
                    )
                    return (
                        f"[skipTTS][ALREADY_APPLIED] Dungeon Master: Miss. (Rolled {roll} vs AC {ac_display}). Attack result committed.",
                        f"Dungeon Master: {narration}",
                        log_msg,
                        True,
                    )

                # TABLETOP MODE: combat latency trace (Phase 0)
                trace_decision(
                    "combat_command_fast_path",
                    "llm_fallback",
                    _decision_start,
                    False,
                )
                return (None, None, log_msg, False)

        elif command == "/dmg":
            # Syntax: /dmg [amount] [flavor text...]
            if len(args) < 1:
                return "[skipTTS] Dungeon Master: [SYSTEM] Usage: /dmg [amount] [optional flavor]", None, None, False

            try:
                amount = int(args[0])
            except ValueError:
                return "[skipTTS] Dungeon Master: [SYSTEM] Invalid amount. Usage: /dmg [amount] [flavor]", None, None, False

            # Determine flavor text
            if len(args) > 1:
                # User provided explicit flavor
                flavor_text = " ".join(args[1:])
            elif self.last_attack_weapon:
                # Fallback to context carry-over
                flavor_text = f"{self.last_attack_weapon} damage"
            else:
                # Generic fallback
                flavor_text = "damage"

            target = getattr(self, 'last_target', None)

            if not target:
                return "[skipTTS] Dungeon Master: [SYSTEM] No target selected. Use /att first or specify target.", None, None, False

            # Apply Damage
            previous_hp = target.hp
            target.hp -= amount
            status_update = ""
            status_text = ""
            if target.hp <= 0:
                target.status = "dead" # or defeated/unconscious
                target.hp = 0
                status_update = " [Target Defeated]"
                status_text = "defeated"
            elif target.hp < target.max_hp / 2:
                status_update = " [Bloodied]"
                status_text = "bloodied"

            # UPSTREAM ALIGNMENT: Queue character update for deferred persistence
            if target.type == CombatantType.PC:
                damage_taken = previous_hp - target.hp
                change_desc = f"took {damage_taken} damage from {actor_name}"
                if status_text:
                    change_desc += f", now {status_text}"
                change_desc += f" (HP: {target.hp}/{target.max_hp})"
                self._queue_character_update(target.name, change_desc)

            # Sync enemy HP changes back to encounter_data for persistence
            # TABLETOP MODE: This ensures encounter file has updated HP when saved
            if target.type == CombatantType.ENEMY:
                for creature in encounter_data.get("creatures", []):
                    if creature.get("name") == target.name:
                        creature["currentHitPoints"] = target.hp
                        if target.status == "dead":
                            creature["status"] = "dead"
                        break

            result_hp_text = f"Result HP: {target.hp}/{target.max_hp}{status_update}."
            log_msg = f"[ALREADY_APPLIED] [System: {actor_name} dealt {amount} damage ({flavor_text}) to {target.name}. {result_hp_text}]"

            narration = _build_fast_path_narration(
                kind="damage",
                actor_name=actor_name,
                target_name=target.name,
                weapon_name=self.last_attack_weapon,
                amount=amount,
                hp_before=previous_hp,
                hp_after=target.hp,
                status_text=status_text,
                flavor_text=flavor_text,
            )

            self.record_pc_phase_event(
                kind="attack_damage",
                actor_name=actor_name,
                target_name=target.name,
                facts={
                    "damage": amount,
                    "hp_before": previous_hp,
                    "hp_after": target.hp,
                    "status": status_text or target.status,
                    "weapon": self.last_attack_weapon or "",
                    "flavor": flavor_text,
                },
                narration=narration,
                mechanics_already_applied=True,
                source_key=self._build_pc_phase_ledger_source_key(
                    kind="attack_damage",
                    actor_name=actor_name,
                    target_name=target.name,
                    facts={
                        "damage": amount,
                        "hp_before": previous_hp,
                        "hp_after": target.hp,
                        "status": status_text or target.status,
                        "weapon": self.last_attack_weapon or "",
                        "flavor": flavor_text,
                    },
                    mechanics_already_applied=True,
                ),
            )

            if fast_path_enabled:
                # TABLETOP MODE: combat latency trace (Phase 0)
                trace_decision(
                    "combat_command_fast_path",
                    "deterministic",
                    _decision_start,
                    True,
                )
                return (
                    f"[skipTTS][ALREADY_APPLIED] Dungeon Master: Damage applied ({amount}). {result_hp_text}",
                    f"Dungeon Master: {narration}",
                    log_msg,
                    True,
                )

            # TABLETOP MODE: combat latency trace (Phase 0)
            trace_decision(
                "combat_command_fast_path",
                "llm_fallback",
                _decision_start,
                False,
            )
            return (None, None, log_msg, False)

        return None, None, None, False



    def roll_group_initiative(self) -> Tuple[int, int, bool]:
        """
        Roll group initiative for PC party vs enemies.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple of (party_roll, enemy_roll, party_goes_first)
        """
        # Roll d20 for each side
        party_roll = random.randint(1, self.INITIATIVE_DIE)
        enemy_roll = random.randint(1, self.INITIATIVE_DIE)

        # Add highest PC initiative modifier to party roll
        max_pc_mod = max(
            (pc.initiative_modifier for pc in self._state.pc_states.values()),
            default=0
        )
        self._state.party_initiative = party_roll + max_pc_mod
        self._state.enemy_initiative = enemy_roll

        # Determine who goes first (party wins ties)
        self._state.party_goes_first = self._state.party_initiative >= self._state.enemy_initiative

        return party_roll, enemy_roll, self._state.party_goes_first

    def get_available_pcs(self) -> List[str]:
        """Get list of PCs who can still act this round.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to CombatStateManager - see CombatStateManager.get_available_pcs() for details.
        """
        return self._state.get_available_pcs()

    def get_incapacitated_pcs(self) -> List[str]:
        """Get list of PCs who need death saves.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to CombatStateManager.get_incapacitated_pcs().
        """
        return self._state.get_incapacitated_pcs()

    def get_all_active_pcs(self) -> List[str]:
        """Get all PCs who are still in combat (not dead).
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to CombatStateManager.get_all_active_pcs().
        """
        return self._state.get_all_active_pcs()

    def sync_pc_persistent_state(self, character_name: str, character_data: Dict[str, Any]) -> None:
        """Sync persisted HP/status/death saves into in-memory combat state."""
        self._state.sync_pc_persistent_state(character_name, character_data)

    def set_current_pc(self, character_name: str) -> bool:
        """
        Set the current active PC (via tab click).
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            character_name: Name of the PC to activate
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            True if successful, False if PC can't act
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to CombatStateManager.set_current_pc().
        """
        return self._state.set_current_pc(character_name)

    def complete_pc_turn(self, character_name: Optional[str] = None) -> bool:
        """
        Mark a PC's turn as complete and check if PC phase is done.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            character_name: PC who completed turn (uses current if None)
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            True if all PCs have acted (PC phase complete)
        """
        name = character_name or self._state.current_pc_name

        # Delegate marking to TurnQueueManager (includes READY guard)
        marked = self._turns.complete_pc_turn(name)

        if not marked:
            # PC wasn't ready or doesn't exist - still check phase status
            # (another path may have already marked them)
            pass

        # Coordination: check if all PCs have acted
        available = self.get_available_pcs()
        incapacitated = self.get_incapacitated_pcs()
        self._turns.pc_phase_complete = len(available) == 0 and len(incapacitated) == 0

        return self._turns.pc_phase_complete

    def force_end_pc_phase(self) -> None:
        """
        Forcefully mark all PCs as having acted this round.
        Used when the DM manually triggers the enemy phase via /end.
        This ensures the prompt context reflects that the PC phase is over.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to TurnQueueManager.force_end_pc_phase().
        """
        self._turns.force_end_pc_phase()

    def get_remaining_enemies_for_round(self) -> List[str]:
        """
        Get a list of enemies/NPCs that should act in the enemy phase.
        Uses pc_phase_complete state + initiative order (Option B approach).
\x20\x20\x20\x20\x20\x20\x20\x20
        DETERMINISM RULE: This function MUST ignore current_turn_index.
        It returns ALL living non-PCs. The LLM then processes them in initiative order.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates to TurnQueueManager - see TurnQueueManager.get_remaining_enemies_for_round() for details.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            List of combatant names (Enemies and NPCs) in initiative order
        """
        return self._turns.get_remaining_enemies_for_round()

    def start_new_round(self) -> int:
        """
        Start a new combat round.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            The new round number
        """
        self._state.current_round += 1
        self._turns.pc_phase_complete = False
        self._turns.enemy_phase_complete = False

        # Reset Turn Queue Pointer to the top of initiative
        self._turns.current_turn_index = 0

        # Update active PC if the new first actor is a PC
        current_actor = self.get_current_actor()
        if current_actor and current_actor.type == CombatantType.PC:
            self.set_current_pc(current_actor.name)

        # Reset all PC states for new round
        for state in self._state.pc_states.values():
            state.reset_for_new_round()

        return self._state.current_round

    def sync_round_from_encounter(self, encounter_data: Dict[str, Any]) -> bool:
        """
        Sync manager round state from persisted encounter file.
\x20\x20\x20\x20\x20\x20\x20\x20
        Called on combat start/resume to ensure the manager's current_round
        matches the encounter file's combat_round. The encounter file is the
        single source of truth for persisted round state.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            encounter_data: The encounter JSON data
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            True if round was synced (values differed), False if already in sync
        """
        encounter_round = encounter_data.get('combat_round', encounter_data.get('current_round', 1))
        if encounter_round > 0 and encounter_round != self._state.current_round:
            self._state.current_round = encounter_round
            return True
        return False

    def sync_committed_turn_state(self, encounter_data: Dict[str, Any]) -> str:
        """Synchronize phase, round, and queue state from a committed snapshot.

        This method is idempotent so startup recovery after an encounter receipt
        does not advance the round or replay any turn effects.
        """
        if not isinstance(encounter_data, dict):
            raise TypeError("committed encounter state must be an object")
        encounter_round = encounter_data.get(
            "combat_round", encounter_data.get("current_round", 1)
        )
        if (
            not isinstance(encounter_round, int)
            or isinstance(encounter_round, bool)
            or encounter_round < 1
        ):
            raise ValueError("committed combat round must be a positive integer")

        round_changed = encounter_round != self._state.current_round
        if round_changed:
            self._state.current_round = encounter_round
            for state in self._state.pc_states.values():
                state.reset_for_new_round()
            self._turns.current_turn_index = 0

        phase = encounter_data.get("combat_phase")
        if phase not in ("PC_PHASE", "ENEMY_PHASE"):
            phase = (
                "ENEMY_PHASE"
                if encounter_data.get("openingEnemyBatchPending") is True
                else "PC_PHASE"
            )
        self._turns.pc_phase_complete = phase == "ENEMY_PHASE"
        self._turns.enemy_phase_complete = False

        creatures = encounter_data.get("creatures", [])
        if isinstance(creatures, list):
            pc_index = {
                _normalize_combat_identity(creature.get("name", "")): creature
                for creature in creatures
                if isinstance(creature, dict)
                and creature.get("type") == "player"
                and _normalize_combat_identity(creature.get("name", ""))
            }
            for name, state in self._state.pc_states.items():
                creature = pc_index.get(_normalize_combat_identity(name))
                if creature is None:
                    continue
                try:
                    hp = int(creature.get("currentHitPoints", state.current_hp))
                except (TypeError, ValueError):
                    hp = state.current_hp
                try:
                    max_hp = int(creature.get("maxHitPoints", state.max_hp))
                except (TypeError, ValueError):
                    max_hp = state.max_hp
                try:
                    armor_class = int(creature.get("armorClass", state.ac))
                except (TypeError, ValueError):
                    armor_class = state.ac
                state.current_hp = hp
                state.max_hp = max_hp
                state.ac = armor_class
                persisted_status = str(creature.get("status", "alive")).strip().lower()
                if persisted_status == "dead":
                    state.status = PCStatus.DEAD
                elif persisted_status == "stable":
                    state.status = PCStatus.STABLE
                elif hp <= 0 or persisted_status in {"unconscious", "incapacitated"}:
                    state.status = PCStatus.INCAPACITATED
                elif state.status in (PCStatus.INCAPACITATED, PCStatus.STABLE):
                    state.status = PCStatus.READY

                normalized_name = _normalize_combat_identity(name)
                for combatant in self._turns.turn_queue:
                    if (
                        combatant.type == CombatantType.PC
                        and _normalize_combat_identity(combatant.name) == normalized_name
                    ):
                        combatant.hp = hp
                        combatant.max_hp = max_hp
                        combatant.ac = armor_class
                        combatant.status = persisted_status
                        break

        self._turns.sync_non_pc_state_from_encounter(encounter_data)
        if round_changed:
            current_actor = self.get_current_actor()
            if current_actor and current_actor.type == CombatantType.PC:
                self.set_current_pc(current_actor.name)
        self.bind_context_encounter(encounter_data)
        self._context_cache.clear()
        return phase

    def sync_non_pc_queue_state(self, encounter_data: Dict[str, Any]) -> bool:
        """Sync enemy/NPC queue state from authoritative encounter data."""
        return self._turns.sync_non_pc_state_from_encounter(encounter_data)

    def update_pc_hp(self, character_name: str, new_hp: int) -> None:
        """
        Update a PC's HP and status.
\x20\x20\x20\x20\x20\x20\x20\x20
        Delegates HP/status update to CombatStateManager.update_pc_hp().
\x20\x20\x20\x20\x20\x20\x20\x20
        Note: Turn queue Combatant objects have their own hp field set at
        initialization. If turn queue HP sync becomes needed, add it here
        as coordination logic after the delegation call.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            character_name: Name of the PC
            new_hp: New HP value
        """
        self._state.update_pc_hp(character_name, new_hp)
        # TABLETOP MODE: Clear death-save tracking if healed above 0
        if new_hp > 0:
            self.death_save_resolved_phases.pop(character_name, None)
            self.death_save_prompted_phases.pop(character_name, None)

    def _queue_character_update(self, character_name: str, change_description: str) -> None:
        """
        Queue a character update for deferred persistence.
\x20\x20\x20\x20\x20\x20\x20\x20
        UPSTREAM ALIGNMENT: Implements consolidated update pattern matching
        combat_manager.py. Changes are batched and applied at combat end.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            character_name: Name of the character
            change_description: Description of the change (e.g., "took 15 damage")
        """
        if character_name not in self.pending_character_updates:
            self.pending_character_updates[character_name] = []
        self.pending_character_updates[character_name].append(change_description)

    def persist_combat_changes(self) -> Dict[str, bool]:
        """
        Persist all queued combat changes to character files.
\x20\x20\x20\x20\x20\x20\x20\x20
        UPSTREAM ALIGNMENT: Implements deferred persistence pattern matching
        combat_manager.py behavior. Called when combat ends to save all HP
        and status changes accumulated during combat.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Dictionary mapping character names to success status
        """
        results = {}

        if not self.pending_character_updates:
            # No pending updates - still save current HP state
            for pc_name, pc_state in self._state.pc_states.items():
                try:
                    # Import here to avoid circular dependencies
                    from updates.update_character_info import update_character_info

                    change_str = f"HP updated to {pc_state.current_hp} after combat"
                    if pc_state.status == PCStatus.DEAD:
                        change_str += ", status: dead"
                    elif pc_state.status == PCStatus.INCAPACITATED:
                        change_str += ", status: unconscious"
                    elif pc_state.status == PCStatus.STABLE:
                        change_str += ", status: stable"

                    success = update_character_info(pc_name, change_str)
                    results[pc_name] = success
                except Exception as e:
                    error(f"Failed to persist combat changes for {pc_name}: {e}", category="combat_persistence")
                    results[pc_name] = False
            return results

        # Process consolidated updates
        for character_name, changes_list in self.pending_character_updates.items():
            try:
                # Import here to avoid circular dependencies
                from updates.update_character_info import update_character_info

                # Build consolidated change string (upstream pattern)
                final_change_string = "Combat results: " + "; ".join(changes_list) + "."

                success = update_character_info(character_name, final_change_string)
                results[character_name] = success

                if success:
                    info(f"Saved combat changes for {character_name}", category="combat_persistence")
                else:
                    error(f"Failed to save changes for {character_name}", category="combat_persistence")

            except Exception as e:
                error(f"Exception persisting combat changes for {character_name}: {e}", exception=e, category="combat_persistence")
                results[character_name] = False

        # Clear pending updates after processing
        self.pending_character_updates.clear()

        return results

    # ========================================================================
    # TABLETOP MODE: Deterministic Death-Save Gate
    # ========================================================================

    def get_pending_death_save_pcs_for_phase(self) -> List[str]:
        """Get PCs that must resolve a death save in the current PC phase
        but have not yet done so this phase.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            List of PC names needing death saves, stable sort order
        """
        current_round = self._state.current_round
        pending = []
        seen = set()

        if self._turns.turn_queue:
            for combatant in self._turns.turn_queue:
                if combatant.type != CombatantType.PC:
                    continue

                name = combatant.name
                if not name or name in seen:
                    continue

                state = self._state.pc_states.get(name)
                if not state or state.status != PCStatus.INCAPACITATED:
                    continue
                if self.death_save_resolved_phases.get(name) == current_round:
                    continue

                pending.append(name)
                seen.add(name)

        for name, state in self._state.pc_states.items():
            if name in seen:
                continue
            if state.status != PCStatus.INCAPACITATED:
                continue
            if self.death_save_resolved_phases.get(name) == current_round:
                continue
            pending.append(name)
        return pending

    def has_unresolved_death_save_obligations(self) -> bool:
        """Return True if any PC has a pending unresolved death save for the current PC phase."""
        return len(self.get_pending_death_save_pcs_for_phase()) > 0

    def get_next_pending_death_save_pc(self) -> Optional[str]:
        """Get the first PC who must resolve a death save this phase.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            PC name or None if no pending death saves
        """
        pending = self.get_pending_death_save_pcs_for_phase()
        return pending[0] if pending else None

    def should_emit_death_save_prompt(self, pc_name: str) -> bool:
        """Check if we should emit the initial death-save prompt for this PC.
\x20\x20\x20\x20\x20\x20\x20\x20
        Only emits once per PC phase per PC. Subsequent loop iterations
        after prompt but before resolution will not re-prompt.
        """
        current_round = self._state.current_round
        if self.death_save_prompted_phases.get(pc_name) == current_round:
            return False
        self.death_save_prompted_phases[pc_name] = current_round
        return True

    def validate_death_save_input_actor(
        self,
        input_actor_name: Optional[str],
        fallback_actor_name: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], str]:
        """Validate that the current input actor owns the pending death save.

        Returns:
            Tuple of (allowed, pending_pc_name_or_None, guidance_message)
        """
        pending_pc = self.get_next_pending_death_save_pc()
        if not pending_pc:
            return True, None, ""

        source_actor = input_actor_name or fallback_actor_name
        if not source_actor:
            return False, pending_pc, (
                f"{pending_pc} must roll this death saving throw. Select {pending_pc}'s tab and enter 1-20 or /death <1-20>."
            )

        if _normalize_combat_identity(source_actor) != _normalize_combat_identity(pending_pc):
            return False, pending_pc, (
                f"{pending_pc} must roll this death saving throw. Select {pending_pc}'s tab and enter 1-20 or /death <1-20>."
            )

        return True, pending_pc, ""

    @staticmethod
    def parse_death_save_roll_input(user_input: str, gate_active: bool) -> Tuple[bool, Optional[int], Optional[str]]:
        """Parse death-save roll input.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            user_input: Raw user input string
            gate_active: Whether the deterministic death-save gate is active.
                         Bare integers are only accepted when gate is active.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple of (valid, roll_or_None, error_or_empty_message)
            When not a death-save input at all, returns (False, None, None).
            When invalid roll value, returns (False, None, error_string).
        """
        if not isinstance(user_input, str):
            return False, None, "Enter a death saving throw roll (1-20)." if gate_active else None

        text = user_input.strip().lower()
        if not text:
            return False, None, "Enter a death saving throw roll (1-20)." if gate_active else None

        # /death <roll> or /ds <roll> command syntax
        command_match = re.fullmatch(r"/(?:death|ds)\s+(\d{1,2})", text)
        if command_match:
            try:
                roll = int(command_match.group(1))
                if 1 <= roll <= 20:
                    return True, roll, ""
                return False, None, "Death save roll must be 1-20."
            except (ValueError, TypeError):
                return False, None, "Death save roll must be a number 1-20."

        # "roll 3", "i roll 3" - extract first number
        natural_match = re.fullmatch(r"(?:i\s+)?roll\s+(\d{1,2})", text)
        if natural_match:
            try:
                roll = int(natural_match.group(1))
                if 1 <= roll <= 20:
                    return True, roll, ""
            except (ValueError, TypeError):
                pass
            return False, None, "Death save roll must be a number 1-20."

        # Bare integer: only accept while death-save gate is active
        if gate_active and text.isdigit():
            try:
                roll = int(text)
                if 1 <= roll <= 20:
                    return True, roll, ""
                return False, None, "Death save roll must be 1-20."
            except (ValueError, TypeError):
                pass

        # Not a death-save input
        if gate_active:
            return False, None, "Enter a death saving throw roll (1-20)."
        return False, None, None

    def resolve_death_save_roll(self, pc_name: str, roll: int) -> Tuple[bool, str]:
        """Apply a death-save roll deterministically and persist the result.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            pc_name: Name of the PC making the save
            roll: The d20 roll result (1-20)
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple of (success, user_message)
        """
        if pc_name not in self._state.pc_states:
            return False, f"[SYSTEM] Unknown PC: {pc_name}"

        state = self._state.pc_states[pc_name]

        if state.status != PCStatus.INCAPACITATED:
            return False, f"[skipTTS] Dungeon Master: [SYSTEM] {pc_name} does not need a death saving throw."

        # Snapshot for rollback on persistence failure
        snapshot_successes = state.death_save_successes
        snapshot_failures = state.death_save_failures
        snapshot_status = state.status
        snapshot_hp = state.current_hp

        # Apply the death save
        combat_continues, result_message = state.apply_death_save(roll)

        try:
            if roll == 20:
                ops = [
                    {"op": "death_saves_set", "successes": 0, "failures": 0},
                    {"op": "set_hp", "value": 1},
                ]
            elif state.status == PCStatus.DEAD:
                ops = [
                    {"op": "death_saves_set", "successes": 0, "failures": 3},
                    {"op": "set_hp", "value": 0},
                ]
            elif state.status == PCStatus.STABLE:
                ops = [
                    {"op": "death_saves_set", "successes": 3, "failures": 0},
                    {"op": "set_hp", "value": 0},
                ]
            else:
                ops = [
                    {"op": "death_saves_set",
                     "successes": state.death_save_successes,
                     "failures": state.death_save_failures},
                    {"op": "set_hp", "value": state.current_hp},
                ]

            from updates.update_character_info import update_character_info
            persist_ok = update_character_info(pc_name, "", ops=ops)

            if not persist_ok:
                state.death_save_successes = snapshot_successes
                state.death_save_failures = snapshot_failures
                state.status = snapshot_status
                state.current_hp = snapshot_hp
                return False, f"[skipTTS] Dungeon Master: [SYSTEM] Failed to persist death save for {pc_name}. Try again."

            # Mark resolved for this phase
            self.death_save_resolved_phases[pc_name] = self._state.current_round

            # Sync turn queue combatant
            self._sync_pc_queue_actor_state(pc_name)

            self.record_pc_phase_event(
                kind="death_save",
                actor_name=pc_name,
                target_name=pc_name,
                facts={
                    "roll": roll,
                    "successes": state.death_save_successes,
                    "failures": state.death_save_failures,
                    "hp_before": snapshot_hp,
                    "hp_after": state.current_hp,
                    "status": state.status.value,
                    "result": result_message,
                },
                narration=result_message,
                mechanics_already_applied=True,
                source_key=self._build_pc_phase_ledger_source_key(
                    kind="death_save",
                    actor_name=pc_name,
                    target_name=pc_name,
                    facts={
                        "roll": roll,
                        "successes": state.death_save_successes,
                        "failures": state.death_save_failures,
                        "hp_before": snapshot_hp,
                        "hp_after": state.current_hp,
                        "status": state.status.value,
                    },
                    mechanics_already_applied=True,
                ),
            )

            # If natural 20 brought PC to READY, mark turn complete
            if state.status == PCStatus.READY:
                self._turns.complete_pc_turn(pc_name)

            return True, f"Dungeon Master: {result_message}"

        except Exception as e:
            error(f"Death save persistence failed for {pc_name}: {e}", category="combat_persistence")
            state.death_save_successes = snapshot_successes
            state.death_save_failures = snapshot_failures
            state.status = snapshot_status
            state.current_hp = snapshot_hp
            return False, f"[skipTTS] Dungeon Master: [SYSTEM] System error persisting death save for {pc_name}."

    def _sync_pc_queue_actor_state(self, pc_name: str) -> None:
        """Sync turn queue combatant HP/status for a PC after death-save resolution."""
        normalized_name = _normalize_combat_identity(pc_name)
        state = self._state.pc_states.get(pc_name)
        if not state:
            return
        for combatant in self._turns.turn_queue:
            if combatant.type == CombatantType.PC and _normalize_combat_identity(combatant.name) == normalized_name:
                combatant.hp = state.current_hp
                combatant.status = state.status.value
                break

    def mark_death_save_obligation_complete(self, pc_name: str) -> None:
        """Mark a PC's death-save obligation as resolved for the current PC phase.
\x20\x20\x20\x20\x20\x20\x20\x20
        If the PC regained consciousness (natural 20), they are also marked
        as having acted this phase.
        """
        self.death_save_resolved_phases[pc_name] = self._state.current_round
        state = self._state.pc_states.get(pc_name)
        if state and state.status == PCStatus.READY:
            self._turns.complete_pc_turn(pc_name)

    def get_combat_state_summary(self) -> Dict[str, Any]:
        """
        Get a summary of current combat state for the UI.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Dictionary with combat state info
        """
        return {
            "current_round": self._state.current_round,
            "party_initiative": self._state.party_initiative,
            "enemy_initiative": self._state.enemy_initiative,
            "party_goes_first": self._state.party_goes_first,
            "current_pc": self._state.current_pc_name,
            "pc_phase_complete": self._turns.pc_phase_complete,
            "enemy_phase_complete": self._turns.enemy_phase_complete,
            "pcs": {
                name: {
                    "status": state.status.value,
                    "hp": state.current_hp,
                    "max_hp": state.max_hp,
                    "death_saves": {
                        "successes": state.death_save_successes,
                        "failures": state.death_save_failures
                    },
                    "metadata": state.metadata
                }
                for name, state in self._state.pc_states.items()
            },
            "available_pcs": self.get_available_pcs(),
            "incapacitated_pcs": self.get_incapacitated_pcs()
        }

    def format_pc_context_for_prompt(self, pc_name: str) -> str:
        """
        Format PC-specific context for combat prompt.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            pc_name: Name of the PC
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Formatted context string for prompt insertion
        """
        return self._memoized_context_render(
            "pc_context",
            {"pc_name": pc_name},
            lambda: self._render_pc_context_for_prompt(pc_name),
        )

    def _render_pc_context_for_prompt(self, pc_name: str) -> str:
        """Render active-PC context without memoization."""
        if pc_name not in self._state.pc_states:
            return ""

        state = self._state.pc_states[pc_name]
        current_phase = "PC_PHASE" if not self._turns.pc_phase_complete else "ENEMY_PHASE"

        lines = [
            f"CURRENT_PHASE: {current_phase}",
            f"HP: {state.current_hp}/{state.max_hp}",
            f"Status: {state.status.value}",
        ]

        if not self._turns.pc_phase_complete:
            lines.insert(0, f"!!! CRITICAL OVERRIDE: THE CURRENT ACTIVE PLAYER CHARACTER IS: [{pc_name}] !!!")
            lines.insert(1, f"IGNORE all other turn indicators. Only [{pc_name}] can act now.")

        if state.status == PCStatus.INCAPACITATED:
            lines.append(f"Death Saves - Successes: {state.death_save_successes}/3, Failures: {state.death_save_failures}/3")
            lines.append("ACTION REQUIRED: This PC must make a death saving throw!")

        return "\n".join(lines)

    def format_party_turn_summary(self) -> str:
        """
        Format summary of which PCs have/haven't acted.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Formatted summary string
        """
        return self._memoized_context_render(
            "party_turn_summary",
            {},
            self._render_party_turn_summary,
        )

    def _render_party_turn_summary(self) -> str:
        """Render party turn summary without memoization."""
        lines = [f"=== PC PARTY TURN STATUS (Round {self._state.current_round}) ==="]

        for name, state in self._state.pc_states.items():
            marker = "[>]" if (not self._turns.pc_phase_complete and name == self._state.current_pc_name) else "   "
            status_icon = {
                PCStatus.READY: "[WAIT] Ready",
                PCStatus.ACTED: "[DONE] Acted",
                PCStatus.INCAPACITATED: "[DOWN] Down",
                PCStatus.DEAD: "[DEAD] Dead",
                PCStatus.STABLE: "[STBL] Stable"
            }.get(state.status, "?")

            lines.append(f"{marker} {name}: {status_icon} (HP: {state.current_hp}/{state.max_hp})")

        available = self.get_available_pcs()
        if available:
            lines.append(f"\nPCs who can still act: {', '.join(available)}")
        else:
            lines.append("\nAll PCs have acted this round.")

        return "\n".join(lines)

    def format_multi_pc_head_context(self) -> str:
        """
        Generate a structured JSON context block for the prompt "Head".
        This contains authoritative state for ALL PCs in the combat.
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Formatted JSON string for system prompt injection
        """
        return self._memoized_context_render(
            "multi_pc_head_context",
            {},
            self._render_multi_pc_head_context,
        )

    def _render_multi_pc_head_context(self) -> str:
        """Render authoritative multi-PC state without memoization."""
        context = {
            "type": "multi_pc_combat_state",
            "combat_round": self._state.current_round,
            "active_pc": self._state.current_pc_name,
            "party_initiative": self._state.party_initiative,
            "enemy_initiative": self._state.enemy_initiative,
            "party_goes_first": self._state.party_goes_first,
            "pc_phase_complete": self._turns.pc_phase_complete,
            "player_characters": []
        }

        for name, state in self._state.pc_states.items():
            pc_data = {
                "name": name,
                "hp": f"{state.current_hp}/{state.max_hp}",
                "status": state.status.value,
                "metadata": state.metadata
            }

            # Include death save info if relevant
            if state.status == PCStatus.INCAPACITATED:
                pc_data["death_saves"] = {
                    "successes": state.death_save_successes,
                    "failures": state.death_save_failures
                }

            context["player_characters"].append(pc_data)

        return f"=== AUTHORITATIVE MULTI-PC STATE (JSON) ===\n{json.dumps(context, indent=2)}\n"

    def get_required_response_prompt(self) -> str:
        """
        Generate the appropriate 'REQUIRED RESPONSE' system instruction for the AI.
\x20\x20\x20\x20\x20\x20\x20\x20
        PHASE 1 OPTIMIZATION: Enhanced with explicit phase indicator and forbidden actors.
\x20\x20\x20\x20\x20\x20\x20\x20
        This logic enforces:
        1. STRICT TURN ISOLATION during PC_PHASE (no enemy narration allowed).
        2. BATCH RESOLUTION during ENEMY_PHASE (after /end command).
\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            The instruction string to inject into the user prompt.
        """
        # Get forbidden actors for PC phase enforcement
        forbidden = self.get_forbidden_actors()
        forbidden_str = ", ".join(forbidden) if forbidden else "None"

        # ====================================================================
        # ENEMY_PHASE: BATCH MODE (after /end command)
        # ====================================================================
        if self._turns.pc_phase_complete:
            pending = self.get_remaining_enemies_for_round()
            actors_str = ", ".join(pending) if pending else "remaining enemies"

            # Explicitly identify Player Characters to forbid them from acting
            pc_names = list(self._state.pc_states.keys())
            pc_forbidden_str = ", ".join(pc_names) if pc_names else "None"

            return f"""
==============================================================================
CURRENT PHASE: ENEMY_PHASE | PC PHASE COMPLETE: TRUE
MODE: ENEMY AND NPC BATCH RESOLUTION
RESOLVE IN ORDER: {actors_str[:60]}
[BLOCKED] FORBIDDEN ACTORS (DO NOT NARRATE): {pc_forbidden_str[:70]}
REQUIRED RESPONSE:
1. Resolve turns for ALL listed ENEMIES and NPC ALLIES in order.
2. STRICT: Only narrate for DM-controlled entities (Enemies/NPC Allies).
3. NEVER narrate actions for Forbidden Player Characters listed above.
4. PCs may appear in updateCharacterInfo ONLY as targets of enemy/NPC effects.
5. STOP immediately after the last enemy/NPC ally acts.
6. Announce round completion and ask for PC actions.
7. Return structured JSON with plan, narration, combat_round, actions.
==============================================================================
"""

        # PC_PHASE: STRICT TURN ISOLATION MODE
        current_actor = self.get_current_actor()
        actor_name = self._state.current_pc_name or (current_actor.name if current_actor else "Current Actor")

        return f"""
==============================================================================
CURRENT PHASE: PC_PHASE | ACTIVE ACTOR: {actor_name}
AWAITING /end COMMAND: YES (enemies cannot act yet)
[BLOCKED] FORBIDDEN ACTORS (DO NOT NARRATE): {forbidden_str[:70]}
REQUIRED RESPONSE:
1. Narrate ONLY the result of {actor_name}'s declared action.
2. FLAVOR TEXT: Treat shouts/battle cries as roleplay from {actor_name}.
3. STOP IMMEDIATELY after this single resolution.
4. DO NOT narrate actions for other PCs. Await /end for enemy phase.
5. DO NOT name or prompt the next PC. The facilitator controls turn order.
6. Return structured JSON with plan, narration, combat_round, actions.
[WARNING] VIOLATION = CRITICAL FAILURE: Narrating for forbidden actors will
cause combat desync. Only [{actor_name}] has authority to act now.
==============================================================================
"""

    def _get_combatant_marker(self, combatant: Combatant) -> Tuple[str, str]:
        """
        Determine state marker and status for a combatant in initiative tracker.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            combatant: The combatant to get marker for
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple of (marker, state_description)
        """
        status = combatant.status.lower()
        name = combatant.name

        if TurnQueueManager._is_inactive_combatant(combatant) and combatant.type != CombatantType.PC:
            return "[D]", "Dead"

        if status == "dead":
            return "[D]", "Dead"

        if combatant.type == CombatantType.PC:
            pc_state = self._state.pc_states.get(name)
            if pc_state:
                if pc_state.status == PCStatus.ACTED:
                    return "[X]", "Acted"
                elif not self._turns.pc_phase_complete and name == self._state.current_pc_name:
                    return "[>]", "CURRENT TURN"
            return "[ ]", "Waiting"

        # NPCs/Enemies default to Waiting
        return "[ ]", "Waiting"

    def _build_initiative_lines(self, sorted_queue: List[Combatant]) -> Tuple[List[str], List[str]]:
        """
        Build initiative and tracker lines from sorted queue.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            sorted_queue: List of combatants sorted by initiative
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple of (initiative_lines, tracker_lines)
        """
        initiative_lines = []
        tracker_lines = []

        for combatant in sorted_queue:
            name = combatant.name
            init = combatant.initiative
            status = "dead" if TurnQueueManager._is_inactive_combatant(combatant) and combatant.type != CombatantType.PC else combatant.status.lower()
            marker, state = self._get_combatant_marker(combatant)

            initiative_lines.append(f"- {name} ({init}) - {status}")
            tracker_lines.append(f"- {marker} {name} ({init}) - {state}")

        return initiative_lines, tracker_lines

    def _determine_instruction_block(self, sorted_queue: List[Combatant]) -> Tuple[str, List[str]]:
        """
        Determine instruction block and turn window based on combat phase.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            sorted_queue: List of combatants sorted by initiative
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Tuple of (instruction_block, turn_window)
        """
        current_round = self._state.current_round

        if self._turns.pc_phase_complete:
            # ENEMY_PHASE
            pending_enemies = self.get_remaining_enemies_for_round()
            if pending_enemies:
                enemy_list = "\n".join([f"- {name}" for name in pending_enemies])
                instruction = f""">>> PROCESS TO END ROUND:
{enemy_list}
>>> THEN: End Round {current_round}, Start Round {current_round + 1}"""
                return instruction, pending_enemies
            else:
                instruction = ">>> ROUND COMPLETE\nAll creatures have acted. Increment combat_round."
                return instruction, []

        # PC_PHASE
        active_pc_name: str = self._state.current_pc_name or "Current PC"
        active_pc_index = next((i for i, combatant in enumerate(sorted_queue) if combatant.name == active_pc_name), -1)

        if active_pc_index < 0:
            return f">>> CURRENT: {active_pc_name} - PLAYER TURN (await input)", [active_pc_name]

        active_init = sorted_queue[active_pc_index].initiative
        instruction = f">>> CURRENT: {active_pc_name} ({active_init}) - PLAYER TURN (await input)"
        return instruction, [active_pc_name]

    def format_initiative_tracker(self, encounter_data: Dict[str, Any]) -> str:
        """
        Generate Live Initiative Tracker markdown matching AI tracker format.
        This replaces the AI initiative tracker in multi-PC mode for deterministic,
        accurate tracking that correctly handles all PCs.
\x20\x20\x20\x20\x20\x20\x20\x20
        Args:
            encounter_data: The encounter data with creatures list
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
        Returns:
            Formatted initiative tracker string matching AI tracker output format
        """
        self.bind_context_encounter(encounter_data)
        return self._memoized_context_render(
            "initiative_tracker",
            {},
            lambda: self._render_initiative_tracker(encounter_data),
        )

    def _render_initiative_tracker(self, encounter_data: Dict[str, Any]) -> str:
        """Render initiative context without memoization."""
        current_round = self._state.current_round

        # Sort turn queue by initiative (highest first)
        sorted_queue = sorted(self._turns.turn_queue, key=lambda x: x.initiative, reverse=True)

        # Build initiative lines
        initiative_lines, tracker_lines = self._build_initiative_lines(sorted_queue)

        # Determine instructions
        instruction_block, turn_window = self._determine_instruction_block(sorted_queue)

        # Build tracker output
        tracker_output = f"""--- ROUND INFO ---
combat_round: {current_round}
player_name: {self._state.current_pc_name}
initiative_order:
{chr(10).join(initiative_lines)}

--- LIVE TRACKER ---
**Live Initiative Tracker:**
{chr(10).join(tracker_lines)}

{instruction_block}

```json
{{
  "combat_round": {current_round},
  "player_name": "{self._state.current_pc_name}",
  "turn_window": {json.dumps(turn_window)},
  "pc_phase_complete": {str(self._turns.pc_phase_complete).lower()}
}}
```"""

        return tracker_output


# Global instance for combat session
_active_combat_manager: Optional[MultiPCCombatManager] = None
_combat_callback: Optional[Any] = None  # Callback for combat events (e.g., to web UI)
# TABLETOP MODE: An unset context value differs from an explicit None.  This
# prevents an ended/reset session from falling through to a stale compatibility
# mirror owned by another context.
_SESSION_UNSET = object()
_legacy_owner_lock = threading.RLock()
_legacy_manager_owner_thread: Optional[int] = None
_legacy_callback_owner_thread: Optional[int] = None
_session_manager: ContextVar[Any] = ContextVar(
    "combat_session_manager", default=_SESSION_UNSET
)
_session_callback: ContextVar[Any] = ContextVar(
    "combat_session_callback", default=_SESSION_UNSET
)


def _legacy_manager_for_current_context() -> Optional[MultiPCCombatManager]:
    """Read the process-wide legacy handle when no context override is bound.

    The web runtime installs the callback/manager on its startup thread and
    emits socket events from worker threads.  ContextVar overrides remain
    isolated, while the legacy process-wide handle remains visible to those
    unbound workers.
    """
    with _legacy_owner_lock:
        return _active_combat_manager


def _legacy_callback_for_current_context() -> Optional[Any]:
    """Read the process-wide legacy callback for unbound worker contexts."""
    with _legacy_owner_lock:
        return _combat_callback


@contextmanager
def temporary_combat_manager(manager: Optional[MultiPCCombatManager]) -> Generator[Optional[MultiPCCombatManager], None, None]:
    """
    Temporarily replace global combat manager for testing.

    Usage:
        with temporary_combat_manager(mock_manager):
            # All code here sees mock_manager as the active combat manager
            result = get_combat_manager()
            assert result == mock_manager
        # Original manager restored automatically
    """
    token = _session_manager.set(manager)
    try:
        yield manager
    finally:
        _session_manager.reset(token)


@contextmanager
def temporary_combat_callback(callback: Optional[Any]) -> Generator[Optional[Any], None, None]:
    """
    Temporarily replace global callback for testing.

    Usage:
        captured_events = []
        with temporary_combat_callback(lambda event, data: captured_events.append((event, data))):
            emit_combat_event("test_event", {"data": "value"})
            assert len(captured_events) == 1
    """
    token = _session_callback.set(callback)
    try:
        yield callback
    finally:
        _session_callback.reset(token)


def reset_combat_state() -> None:
    """
    Reset global combat state - USE ONLY IN TESTS.
    Clears both active manager and callback.
    """
    global _active_combat_manager, _combat_callback
    global _legacy_manager_owner_thread, _legacy_callback_owner_thread
    _session_manager.set(None)
    _session_callback.set(None)
    with _legacy_owner_lock:
        _active_combat_manager = None
        _combat_callback = None
        _legacy_manager_owner_thread = threading.get_ident()
        _legacy_callback_owner_thread = threading.get_ident()
    info("Combat state reset", category="combat_lifecycle")


def set_combat_callback(callback: Any) -> None:
    """
    Set the callback function for combat events.
\x20\x20\x20\x20
    Args:
        callback: Function to call with event data
    """
    global _combat_callback, _legacy_callback_owner_thread
    _session_callback.set(callback)
    with _legacy_owner_lock:
        _combat_callback = callback
        _legacy_callback_owner_thread = threading.get_ident()


def emit_combat_event(event_type: str, data: Dict[str, Any]) -> None:
    """
    Emit a combat event to the callback.
\x20\x20\x20\x20
    Args:
        event_type: Type of event (e.g., 'multi_pc_combat_started')
        data: Event payload
    """
    callback = _session_callback.get()
    if callback is _SESSION_UNSET:
        callback = _legacy_callback_for_current_context()
    if callback:
        try:
            callback(event_type, data)
        except Exception as e:
            error(f"Error in combat callback: {e}", exception=e, category="combat_events")


def get_combat_manager() -> Optional[MultiPCCombatManager]:
    """Get the active combat manager instance."""
    manager = _session_manager.get()
    if manager is not _SESSION_UNSET:
        return manager
    return _legacy_manager_for_current_context()


def create_combat_manager(party_data: Dict[str, Any]) -> MultiPCCombatManager:
    """
    Create a new combat manager for a combat session.
\x20\x20\x20\x20
    Args:
        party_data: Party tracker data
\x20\x20\x20\x20\x20\x20\x20\x20
    Returns:
        New MultiPCCombatManager instance
    """
    global _active_combat_manager, _legacy_manager_owner_thread

    manager = MultiPCCombatManager()
    manager.initialize_from_party(party_data)
    _session_manager.set(manager)
    with _legacy_owner_lock:
        _active_combat_manager = manager
        _legacy_manager_owner_thread = threading.get_ident()

    # Emit start event
    emit_combat_event("multi_pc_combat_started", manager.get_combat_state_summary())

    return manager


def end_combat_session() -> None:
    """End the current combat session and clean up."""
    global _active_combat_manager, _legacy_manager_owner_thread
    manager = _session_manager.get()
    if manager is _SESSION_UNSET:
        manager = _legacy_manager_for_current_context()
    if manager:
        # UPSTREAM ALIGNMENT: Persist all combat changes before ending
        info("Ending combat session - persisting damage to character files...", category="combat_lifecycle")
        results = manager.persist_combat_changes()
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        info(f"Persisted changes for {success_count}/{total_count} characters", category="combat_lifecycle")
        manager.clear_pc_phase_event_ledger()

        emit_combat_event("combat_ended", {})
    _session_manager.set(None)
    with _legacy_owner_lock:
        _active_combat_manager = None
        _legacy_manager_owner_thread = threading.get_ident()


def cleanup_combat_manager() -> None:
    """
    Clean up the combat manager after combat ends.
\x20\x20\x20\x20
    This is an alias for end_combat_session() provided for clarity
    when called from action_handler.py post-combat save logic.
    """
    end_combat_session()


def is_multi_pc_combat_enabled() -> bool:
    """Check if multi-PC combat mode is enabled."""
    return MULTIPLAYER_MODE


# ============================================================================
# PROMPT MODIFICATION UTILITIES
# ============================================================================

def modify_combat_prompt_for_multi_pc(
    base_prompt: str,
    pc_name: str,
    manager: MultiPCCombatManager
) -> str:
    """
    Modify the combat prompt to support multi-PC mode.
\x20\x20\x20\x20
    This replaces generic "you/your" references with PC-specific language
    and adds multi-PC context.
\x20\x20\x20\x20
    Args:
        base_prompt: Original single-PC combat prompt
        pc_name: Name of the currently active PC
        manager: The combat manager instance
\x20\x20\x20\x20\x20\x20\x20\x20
    Returns:
        Modified prompt for multi-PC combat
    """
    # Add multi-PC header section
    current_phase = "PC_PHASE" if not manager.pc_phase_complete else "ENEMY_PHASE"
    multi_pc_header = f"""
++ MULTI-PC COMBAT MODE ACTIVE ++
This combat involves multiple player characters. Each PC takes their turn when\x20
selected by the player via the character tabs. Address the current PC by name
using [{pc_name}] instead of generic "you" references.

CURRENT_PHASE: {current_phase}
CURRENT_PHASE overrides any [>] marker. [>] is PC_PHASE-only.

{manager.format_party_turn_summary()}

{manager.format_pc_context_for_prompt(pc_name)}

IMPORTANT MULTI-PC RULES:
1. Address actions to [{pc_name}] specifically, not generic "you"
2. When prompting for actions, ask "[{pc_name}], what do you do?"
3. Other PCs are treated as player-controlled allies, not AI NPCs
4. Only process the current PC's turn, then await the next PC selection
5. Death saves: Incapacitated PCs roll death saves on their turn

"""

    # Insert header after the first section of the prompt
    insert_point = base_prompt.find("++ HOW TO USE")
    if insert_point > 0:
        modified = base_prompt[:insert_point] + multi_pc_header + base_prompt[insert_point:]
    else:
        modified = multi_pc_header + base_prompt

    return modified


def get_multi_pc_initiative_narrative(manager: MultiPCCombatManager) -> str:
    """
    Generate narrative text for group initiative roll.
\x20\x20\x20\x20
    Args:
        manager: Combat manager with initiative already rolled
\x20\x20\x20\x20\x20\x20\x20\x20
    Returns:
        Narrative description of initiative
    """
    party_roll, enemy_roll, party_first = (
        manager.party_initiative,
        manager.enemy_initiative,
        manager.party_goes_first
    )

    pc_names = list(manager.pc_states.keys())
    pc_list = ", ".join(pc_names[:-1]) + f" and {pc_names[-1]}" if len(pc_names) > 1 else pc_names[0]

    if party_first:
        return f"""The party rolls for initiative as one! {pc_list} ready themselves for battle.
Party Initiative: {party_roll} | Enemy Initiative: {enemy_roll}
The heroes act first! Select which party member takes the opening move."""
    else:
        return f"""The party rolls for initiative as one! {pc_list} ready themselves for battle.
Party Initiative: {party_roll} | Enemy Initiative: {enemy_roll}
The enemies act first! Brace yourselves as the foes make their move."""


class _ContextAwareCombatModule(types.ModuleType):
    """Expose narrow legacy attributes as effective package-owned values."""

    def __getattribute__(self, name: str) -> Any:
        if name == "safe_json_load":
            return _state_module.safe_json_load
        if name == "_active_combat_manager":
            override = _session_manager.get()
            if override is not _SESSION_UNSET:
                return override
            return _legacy_manager_for_current_context()
        if name == "_combat_callback":
            override = _session_callback.get()
            if override is not _SESSION_UNSET:
                return override
            return _legacy_callback_for_current_context()
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Keep old monkeypatch targets writable without manufacturing a second
        # implementation or using dynamic code generation.
        if name == "safe_json_load":
            _state_module.safe_json_load = value
            return
        if name == "_active_combat_manager":
            override = _session_manager.get()
            if override is not _SESSION_UNSET:
                _session_manager.set(value)
                return
            with _legacy_owner_lock:
                self.__dict__[name] = value
                globals()[name] = value
                globals()["_legacy_manager_owner_thread"] = threading.get_ident()
            return
        if name == "_combat_callback":
            override = _session_callback.get()
            if override is not _SESSION_UNSET:
                _session_callback.set(value)
                return
            with _legacy_owner_lock:
                self.__dict__[name] = value
                globals()[name] = value
                globals()["_legacy_callback_owner_thread"] = threading.get_ident()
            return
        super().__setattr__(name, value)

# Narrow compatibility adapter: old tests and integrations may inspect the
# private mirrors directly, while ContextVar-bound overrides remain isolated.
if not isinstance(sys.modules[__name__], _ContextAwareCombatModule):
    sys.modules[__name__].__class__ = _ContextAwareCombatModule
