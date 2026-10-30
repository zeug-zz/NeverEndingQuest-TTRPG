# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free, fixed combat fixtures for latency baseline tests."""

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from utils.combat_latency_trace import (
    build_work_unit_trace_context,
    set_trace_context,
    trace_file_operation,
    trace_stage,
)
from utils.file_operations import safe_read_json, safe_write_json


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PC_NAMES = ["Acheron", "Merisiel", "Kira", "Vitreol"]
ENEMY_NAMES = ["Goblin Alpha", "Goblin Beta"]
PC_INITIATIVES = {"Acheron": 20, "Merisiel": 18, "Kira": 16, "Vitreol": 14}
ENEMY_INITIATIVES = {"Goblin Alpha": 10, "Goblin Beta": 8}
ONE_PC_NAME = "Acheron"
ONE_PC_ENEMY_NAME = "Goblin"
ONE_PC_INITIATIVE = 18
ONE_PC_ENEMY_INITIATIVE = 10
CAPTURE_ALLIED_NPC_NAME = "Blairen"
CAPTURE_INACTIVE_ENEMY_NAME = "Inactive Goblin"
G5A_PC_WEAPONS = {
    "Acheron": ("shortsword", "1d6+2 piercing"),
    "Merisiel": ("shortsword", "1d6+2 piercing"),
    "Kira": ("shortsword", "1d6+2 piercing"),
    "Vitreol": ("light crossbow", "1d8+2 piercing"),
}
G7_ENEMY_BATCH_PREROLL_SEED = 1


class _UnexpectedCompressionRequest(BaseException):
    """Fatal local sentinel for any request escaping the fixture's compressor stub."""


def _make_mp_manager() -> Any:
    """Import the real combat manager only when exercising the fixture path.

    The production facade has import-time runtime dependencies (including the
    character update path); profile/seed construction does not need them.
    """
    from core.managers.multi_pc_combat import MultiPCCombatManager

    return MultiPCCombatManager()


def build_capture_combat_context(party_size: int, include_allied_inactive: bool = False) -> str:
    """Describe only the authored PCs and hostiles in this named seed."""
    if party_size == 1:
        context = (
            "Acheron is the only active PC. Goblin is the only active hostile and "
            "is within Acheron's reach."
        )
    elif party_size == 4:
        context = (
            "Goblin Alpha is the nearest goblin to Kira and is within her reach; "
            "Goblin Beta is farther from Kira. Vitreol targets Goblin Beta with her crossbow."
        )
    else:
        raise ValueError("capture context party size must be 1 or 4")
    if include_allied_inactive:
        context += (
            " Blairen is an allied NPC. Inactive Goblin is defeated and is not "
            "an active hostile or an eligible nearest-target candidate."
        )
    return context

# Small, fixed Capture_Arena profiles. These are intentionally not a general
# scenario format; unknown identifiers and invalid party/branch combinations
# fail before a sandbox is touched.
CAPTURE_SCENARIOS = (
    "combat-smoke",
    "combat-smoke-allied-inactive",
    "initiative-pc",
    "initiative-dm-tie",
    "death-save",
    "surrender-exit",
    "resume-replay",
)
CAPTURE_BRANCHES = ("surrender", "explicit-exit")
CAPTURE_RESUME_PHASES = ("complete", "replay")

G7_COMMIT_PATHS = ("normal", "enemy_batch")
G7_COMMIT_PHASES = ("interrupt", "recover", "complete", "replay")
G7_COMMIT_LIFECYCLE_PHASES = ("interrupt", "recover")
G7_COMMIT_REPLAY_PHASES = ("complete", "replay")
G7_LIFECYCLE_STOP_TIMEOUT_SECONDS = 180
G7_COMMIT_BOUNDARIES = (
    "before_first_character_write",
    "after_character_write:1",
    "after_encounter_write",
    "after_phase_sync",
    "during_success_publication",
    "after_success_publication",
)
G7_COMMIT_BOUNDARY_P4_NORMAL_ONLY = "after_character_write:2"


def g7_commit_boundaries(party_size: int, path: str) -> tuple[str, ...]:
    """Return G7 boundaries applicable to one party shape and commit path."""
    if party_size not in (1, 4) or isinstance(party_size, bool):
        raise ValueError("G7 capture party size must be 1 or 4")
    if path not in G7_COMMIT_PATHS:
        raise ValueError("G7 commit path must be normal or enemy_batch")
    if party_size != 4 or path != "normal":
        return G7_COMMIT_BOUNDARIES
    return (
        "before_first_character_write",
        "after_character_write:1",
        G7_COMMIT_BOUNDARY_P4_NORMAL_ONLY,
        "after_encounter_write",
        "after_phase_sync",
        "during_success_publication",
        "after_success_publication",
    )


def build_g7_turn_commit_fixture(party_size: int, path: str = "normal") -> Dict[str, Any]:
    """Build the fixed G7 seed for one legal normal or deterministic batch path."""
    if party_size not in (1, 4) or isinstance(party_size, bool):
        raise ValueError("G7 turn-commit fixture party size must be 1 or 4")
    if path not in G7_COMMIT_PATHS:
        raise ValueError("G7 turn-commit path must be normal or enemy_batch")

    party_names = [ONE_PC_NAME] if party_size == 1 else list(PC_NAMES)
    # TABLETOP MODE: Enemy-batch fixtures use unarmored legal ACs so low seeded
    # attack rolls still produce a bounded single-PC effect (Dex 6/AC 8 in P1,
    # Dex 3/AC 6 in P4). Normal-path fixtures retain their established AC.
    pc_armor_class = (
        (8 if party_size == 1 else 6) if path == "enemy_batch" else 14
    )
    pc_dexterity = (
        (6 if party_size == 1 else 3) if path == "enemy_batch" else 10
    )
    # Normal-path identities are stable. Enemy-batch IDs are selected against
    # every reachable production initiative order with the unchanged legal
    # fixture initiatives below.
    if path == "normal":
        encounter_id = "turn_commit_p1_001" if party_size == 1 else "turn_commit_p4_002"
    else:
        encounter_id = "turn_commit_p1_002" if party_size == 1 else "turn_commit_p4_130"
    encounter = copy.deepcopy(
        _one_pc_encounter_payload() if party_size == 1 else _encounter_payload()
    )
    encounter["id"] = encounter_id
    encounter["encounterId"] = encounter_id
    encounter["combat_round"] = 1
    encounter["current_round"] = 1
    encounter["combat_phase"] = "PC_PHASE"
    encounter["initiativeMode"] = "two_group_phase1"
    encounter["initiativeRolls"] = {"dmGroup": 12, "pcGroup": 18}
    encounter["initiativeWinner"] = "pcGroup"
    encounter["roundStartsWith"] = "pcGroup"
    encounter["awaitingPcGroupRoll"] = False
    encounter["openingEnemyBatchPending"] = False

    for creature in encounter["creatures"]:
        if creature.get("type") != "enemy":
            continue
        if party_size == 1:
            creature["initiative"] = 10
        elif creature.get("name") == "Goblin Alpha":
            creature["initiative"] = 10
        else:
            creature["initiative"] = 8
        creature["currentHitPoints"] = 40
        creature["maxHitPoints"] = 40
        creature["status"] = "alive"
        creature["numAttacks"] = 1
        creature["attacks"] = [{"name": "Scimitar"}]

    normal_targets = [ONE_PC_NAME] if party_size == 1 else [
        "Acheron", "Merisiel", "Kira"
    ]
    for name in party_names:
        initiative = ONE_PC_INITIATIVE if party_size == 1 else PC_INITIATIVES[name]
        below_max_hp = (
            party_size == 4 and path == "normal" and name in normal_targets
        )
        encounter["creatures"].append({
            "name": name,
            "type": "player",
            "initiative": initiative,
            "status": "alive",
            "conditions": [],
            "actions": {"actionType": "", "target": ""},
            "currentHitPoints": 20 if below_max_hp else 30,
            "maxHitPoints": 30,
            "armorClass": pc_armor_class,
        })

    spell_slots = {
        "level%d" % level: {"current": 2 if level == 1 else 0,
                            "max": 2 if level == 1 else 0}
        for level in range(1, 10)
    }
    pc_abilities = {
        "strength": 10,
        "dexterity": pc_dexterity,
        "constitution": 10,
        "intelligence": 10,
        "wisdom": 10,
        "charisma": 10,
    }
    if party_size == 1:
        normal_text = (
            "Acheron casts Bless using one 1st-level spell slot, targeting Acheron. "
            "Apply the Bless effect to Acheron for 1 minute; no roll is needed."
        )
        spell_slots = {
            "level%d" % level: {"current": 2 if level == 1 else 0,
                                "max": 2 if level == 1 else 0}
            for level in range(1, 10)
        }
        normal_spell = "Bless"
        normal_spell_level = 1
        caster_level = 1
    else:
        normal_text = (
            "Acheron casts Mass Healing Word using one 3rd-level spell slot, "
            "targeting Acheron, Merisiel, and Kira within 60 feet. The healing roll is already made: "
            "2d4 rolled 2 and 3, plus 3 for Wisdom, so each of Acheron, Merisiel, and Kira "
            "regains 8 hit points (from 20 to 28 of 30). No further roll is needed."
        )
        spell_slots = {
            "level%d" % level: {
                "current": {1: 4, 2: 3, 3: 2}.get(level, 0),
                "max": {1: 4, 2: 3, 3: 2}.get(level, 0),
            }
            for level in range(1, 10)
        }
        normal_spell = "Mass Healing Word"
        normal_spell_level = 3
        caster_level = 5
    enemy_batch_text = "/end"
    character_overrides = (
        {
            name: {
                "armorClass": pc_armor_class,
                "abilities": dict(pc_abilities),
            }
            for name in party_names
        }
        if path == "enemy_batch" else {}
    )
    character_overrides.setdefault("Acheron", {}).update({
            "class": "Cleric",
            "level": caster_level,
            "armorClass": pc_armor_class,
            "hitPoints": 20 if party_size == 4 and path == "normal" else 30,
            "maxHitPoints": 30,
            "abilities": dict(pc_abilities, wisdom=16),
            "classFeatures": [],
            "proficiencyBonus": 3 if caster_level >= 5 else 2,
            "experience_points": 6500 if caster_level >= 5 else 0,
            "exp_required_for_next_level": 14000 if caster_level >= 5 else 300,
            "spellcasting": {
                "spells": {
                    "level0": [],
                    "level1": [normal_spell] if normal_spell_level == 1 else [],
                    "level2": [],
                    "level3": [normal_spell] if normal_spell_level == 3 else [],
                },
                "spellSlots": spell_slots,
                "preparedSpells": [normal_spell],
            },
        })
    if party_size == 4 and path == "normal":
        for target_name in normal_targets:
            character_overrides.setdefault(target_name, {}).update({
                "hitPoints": 20,
                "maxHitPoints": 30,
            })
    enemy_expected = [ONE_PC_NAME] if party_size == 1 else None
    expected_changed = normal_targets if path == "normal" else enemy_expected
    return {
        "scenario_id": "turn-commit",
        "party_size": party_size,
        "path": path,
        "encounter_id": encounter_id,
        "party_names": party_names,
        "encounter": encounter,
        "character_overrides": character_overrides,
        "normal_input": normal_text,
        "enemy_batch_input": enemy_batch_text,
        "input": normal_text if path == "normal" else enemy_batch_text,
        "normal_expected_characters": normal_targets,
        "enemy_batch_expected_characters": enemy_expected,
        "expected_changed_characters": expected_changed,
        "preroll_seed": (
            G7_ENEMY_BATCH_PREROLL_SEED if path == "enemy_batch" else None
        ),
        "pc_hit_points": 30,
        "pc_armor_class": pc_armor_class,
    }
CAPTURE_GATES = ("g3", "g4", "g5", "g5r", "g5t")
G9_SCENARIOS = (
    "narrator-auto",
    "combat-auto",
    "transport-failure",
    "preferred-openai-rollback",
)
G9_PARTY_SIZES = (1, 4)
G9_REQUIRED_ROW_KEYS = tuple(
    "%s:p%d" % (scenario, party_size)
    for scenario in G9_SCENARIOS
    for party_size in G9_PARTY_SIZES
)
G9_ROLLBACK_PHASE = "rollback"
G10_SCENARIO = "full-session"
G10_PHASES = ("complete", "resume")
G10_PARTY_SIZES = (1, 4)
G10_NARRATION_INPUT = "I look across the yard and call out a challenge to the goblins."
G10_REQUIRED_ROW_KEYS = tuple(
    "%s:%s:p%d" % (G10_SCENARIO, phase, party_size)
    for party_size in G10_PARTY_SIZES
    for phase in G10_PHASES
)
CAPTURE_GATE_CHOICES = CAPTURE_GATES + ("g5a", "g7", "g9", "g10")
G5_CAPTURE_GATES = ("g5", "g5r", "g5t", "g5a")
G5A_PARTY_SIZES = (1, 4)
G5A_RUNS_PER_PARTY = 3
G5A_ALLY_NAME = CAPTURE_ALLIED_NPC_NAME
G5A_DIRECTIVE_TEXT = "take cover behind the shield racks"
G5A_COVER_FEATURE_ID = "ca02-ally-shield-racks"
G5A_COVER_LOCATION_ID = "CA02"

# Keep the CLI's named-scenario registry and gate inference on one source of
# truth. Shared scenarios such as combat-smoke retain their historical G3
# default; callers can still select G4/G5/G5R explicitly where supported.
CAPTURE_SCENARIO_GATE_REGISTRY = {
    **{scenario_id: "g3" for scenario_id in CAPTURE_SCENARIOS},
    "narrator-dialogue-travel": "g4",
    "g5t-commander-p1": "g5t",
    "g5t-commander-p4": "g5t",
    "g5a-ally-p1": "g5a",
    "g5a-ally-p4": "g5a",
    "turn-commit": "g7",
    **{scenario_id: "g9" for scenario_id in G9_SCENARIOS},
    G10_SCENARIO: "g10",
}
CAPTURE_SCENARIO_CHOICES = tuple(CAPTURE_SCENARIO_GATE_REGISTRY)


def infer_capture_gate(scenario_id: Optional[str]) -> Optional[str]:
    """Return the registered default gate for a named capture scenario."""
    if not scenario_id:
        return None
    return CAPTURE_SCENARIO_GATE_REGISTRY.get(scenario_id)

# G4 narrator profile is deliberately a single fixed case, not a scenario DSL.
# Each tuple is (label, utterance, P1 actor, P4 actor, expected location ID,
# semantic evidence kind). Startup is observed separately at CA01.
G4_NARRATOR_TURNS = (
    ("travel to CA02", "Walk east from the gate into the training pit.", "Acheron", "Acheron", "CA02", "travel"),
    ("travel to CA03", "Leave the pit and go south to the reliquary alcove.", "Acheron", "Acheron", "CA03", "travel"),
    ("ask Mira about shrine", "Ask Warden Mira what the three-ring shrine means.", "Acheron", "Merisiel", "CA03", "mira_dialogue"),
    ("return to CA02", "Return north from the reliquary to the training pit.", "Acheron", "Merisiel", "CA02", "travel"),
    ("return to CA01", "Continue west through the gate into the waystone yard.", "Acheron", "Merisiel", "CA01", "travel"),
)


def capture_turn_timeout_allowed(
    scenario_id: Any, party_size: Any, branch: Any, turn_timeout: Any
) -> bool:
    """Apply the shared named-capture turn-timeout policy.

    The ordinary finite positive bound is 150 seconds. Exactly 300 seconds is
    permitted only for the two named smoke cases at either supported party size
    or the four-PC surrender-exit surrender branch. Intermediate values above
    150 seconds are intentionally not accepted.
    """
    if (isinstance(turn_timeout, bool) or not isinstance(turn_timeout, (int, float)) or
            not math.isfinite(turn_timeout) or turn_timeout <= 0):
        return False
    if turn_timeout <= 150:
        return True
    if turn_timeout != 300 or isinstance(party_size, bool) or party_size not in (1, 4):
        return False
    return (
        scenario_id in ("combat-smoke", "combat-smoke-allied-inactive") or
        (party_size == 4 and scenario_id == "surrender-exit" and branch == "surrender")
    )
CAPTURE_STEP_BOUNDS = {
    "combat-smoke": {1: 5, 4: 22},
    "combat-smoke-allied-inactive": {1: 5, 4: 22},
    "initiative-pc": {1: 2, 4: 2},
    "initiative-dm-tie": {1: 2, 4: 2},
    "death-save": {1: 2, 4: 3},
    "surrender-exit": {1: 2, 4: 2},
    "resume-replay": {1: {"complete": 2, "replay": 0}, 4: {"complete": 2, "replay": 0}},
}


def build_capture_profile(
    scenario_id: str,
    party_size: int,
    branch: str = "",
    phase: str = "",
) -> Dict[str, Any]:
    """Return a validated, bounded seed profile for the named capture case."""
    if scenario_id not in CAPTURE_SCENARIOS:
        raise ValueError("unknown capture scenario: %s" % scenario_id)
    if party_size not in (1, 4):
        raise ValueError("capture party size must be 1 or 4")
    if scenario_id == "surrender-exit":
        if branch not in CAPTURE_BRANCHES:
            raise ValueError("surrender-exit requires --branch surrender|explicit-exit")
    elif branch:
        raise ValueError("--branch applies only to surrender-exit")
    if scenario_id == "resume-replay":
        if phase not in CAPTURE_RESUME_PHASES:
            raise ValueError("resume-replay requires --phase complete|replay")
    elif phase:
        raise ValueError("--phase applies only to resume-replay")

    step_bound = CAPTURE_STEP_BOUNDS[scenario_id][party_size]
    max_steps = step_bound[phase] if isinstance(step_bound, dict) else step_bound
    if scenario_id == "surrender-exit" and branch == "surrender":
        max_steps = 1
    if scenario_id in ("combat-smoke", "combat-smoke-allied-inactive"):
        active_switch_budget = 12 if party_size == 4 else 1
    elif scenario_id == "death-save":
        active_switch_budget = 3 if party_size == 4 else 1
    elif scenario_id == "resume-replay" and phase == "replay":
        active_switch_budget = 0
    else:
        active_switch_budget = 1
    profile: Dict[str, Any] = {
        "scenario_id": scenario_id,
        "party_size": party_size,
        "branch": branch or None,
        "phase": phase or None,
        "max_steps": max_steps,
        "max_active_switches": active_switch_budget,
        "max_health_reads": 1 if scenario_id == "surrender-exit" and branch == "explicit-exit" else 0,
        # Includes the start_game socket control, user_input controls and
        # set_active REST controls; one initial set_active is in the switch budget.
        "max_requests": max_steps + 1 + active_switch_budget,
        "applicability": {
            "party_size": party_size,
            "wrong_actor_death_save": scenario_id == "death-save" and party_size == 4,
        },
        "seed": {},
    }
    if scenario_id == "initiative-pc":
        profile["seed"] = {"awaitingPcGroupRoll": True, "dmGroup": 8, "pcGroup": None}
    elif scenario_id == "initiative-dm-tie":
        profile["seed"] = {"awaitingPcGroupRoll": True, "dmGroup": 12, "pcGroup": None, "expected_roll": 12}
    elif scenario_id == "death-save":
        profile["seed"] = {"pending_death_save_pc": "Acheron", "hitPoints": 0, "status": "unconscious"}
        profile["character_overrides"] = {
            "Acheron": {
                "hitPoints": 0,
                "status": "unconscious",
                "condition": "unconscious",
                "condition_affected": ["unconscious"],
                "deathSaves": {"successes": 0, "failures": 0},
            }
        }
    elif scenario_id in ("combat-smoke", "combat-smoke-allied-inactive"):
        if scenario_id == "combat-smoke-allied-inactive":
            profile["seed"] = {
                "allied_npc": CAPTURE_ALLIED_NPC_NAME,
                "inactive_enemy": CAPTURE_INACTIVE_ENEMY_NAME,
                "party_ally": {"name": CAPTURE_ALLIED_NPC_NAME, "role": "Ally"},
                "media_asset": "web/static/media/npcs/blairen.jpg",
            }
            profile["npc_characters"] = {
                CAPTURE_ALLIED_NPC_NAME: build_capture_allied_npc_payload(
                    CAPTURE_ALLIED_NPC_NAME
                )
            }
        # Existing encounter-summary projection carries party-specific fixture
        # facts to the combat prompt without adding product geometry/resolvers.
        profile["seed"]["encounter_context"] = build_capture_combat_context(
            party_size, include_allied_inactive=scenario_id == "combat-smoke-allied-inactive"
        )
    elif scenario_id == "surrender-exit":
        last_hostile = "Goblin Beta" if party_size == 4 else ONE_PC_ENEMY_NAME
        profile["seed"] = {
            "branch": branch,
            "last_hostile": last_hostile,
            "inactive_enemies": [name for name in (ENEMY_NAMES if party_size == 4 else [ONE_PC_ENEMY_NAME])
                                  if name != last_hostile],
            "completion_mode": "normal_backend_output" if branch == "surrender" else "canonical_clear_then_narrator_followup",
            "followup_label": "post-exit narrator handoff" if branch == "explicit-exit" else None,
        }
        if branch == "surrender":
            profile["seed"]["encounter_context"] = (
                "%s is the last living hostile. %s has voluntarily offered unconditional "
                "surrender, lowered its weapon, and awaits the party's acceptance."
                % (last_hostile, last_hostile)
            )
    elif scenario_id == "resume-replay":
        profile["seed"] = {"resume_phase": phase}
    return profile


def build_g5_script_steps(party_size: int) -> List[Dict[str, Any]]:
    """Map the existing fixed command script to driver inputs without editing it."""
    if party_size == 1:
        script = build_one_pc_command_script()
    elif party_size == 4:
        script = build_command_script()
    else:
        raise ValueError("G5 fixture party size must be 1 or 4")

    rows: List[Dict[str, Any]] = []
    round_number = 1
    commands_in_round = 0
    commands_per_round = 8 if party_size == 4 else 2
    for index, raw_command in enumerate(script):
        step_number = index + 1
        if raw_command.startswith("/init "):
            rows.append({"label": "initiative roll", "input": raw_command,
                         "character": None, "round": round_number,
                         "phase": "SETUP", "unit_type": "control",
                         "unit_id": "control-step-%03d" % step_number,
                         "step": step_number})
            continue
        if raw_command.startswith("/end"):
            label = ("round%d enemy phase (/end)" % round_number
                     if party_size == 4 else "one pc enemy phase (/end)")
            rows.append({"label": label, "input": "/end", "character": None,
                         "round": round_number, "phase": "ENEMY_PHASE",
                         "unit_type": "batch", "unit_id": "batch-step-%03d" % step_number,
                         "step": step_number})
            if party_size == 4:
                round_number += 1
            commands_in_round = 0
            continue

        character, separator, command = raw_command.partition(": ")
        if not separator or character not in (PC_NAMES if party_size == 4 else [ONE_PC_NAME]):
            raise ValueError("unsupported command in fixed G5 script")
        if command.startswith("/att "):
            action_name = "attack"
        elif command.startswith("/dmg "):
            action_name = "damage"
        else:
            raise ValueError("unsupported command in fixed G5 script")
        label = ("r%d %s %s" % (round_number, character, action_name)
                 if party_size == 4 else "one pc %s" % action_name)
        rows.append({"label": label, "input": command, "character": character,
                     "round": round_number, "phase": "PC_PHASE",
                     "unit_type": "action", "unit_id": "action-step-%03d" % step_number,
                     "step": step_number})
        commands_in_round += 1
        if commands_in_round == commands_per_round:
            next_command = script[index + 1] if index + 1 < len(script) else None
            if next_command is not None and not next_command.startswith("/end"):
                round_number += 1
            commands_in_round = 0
    return rows


def build_g5_fixture_metadata(party_size: int) -> Dict[str, Any]:
    """Describe the fixed P1/P4 G5 script without copying its input text."""
    if party_size not in (1, 4):
        raise ValueError("G5 fixture party size must be 1 or 4")

    script = build_one_pc_command_script() if party_size == 1 else build_command_script()
    raw_steps = build_g5_script_steps(party_size)
    public_steps: List[Dict[str, Any]] = []
    work_units: Dict[str, Dict[str, Any]] = {"actions": {}, "batches": {}, "controls": {}}
    for index, row in enumerate(raw_steps, 1):
        unit_type = row["unit_type"]
        unit_id = row["unit_id"]
        public_steps.append({"index": index, "label": row["label"],
                             "character": row["character"], "round": row["round"],
                             "phase": row["phase"], "unit_type": unit_type,
                             "unit_id": unit_id})
        units_key = {"action": "actions", "batch": "batches", "control": "controls"}[unit_type]
        work_units[units_key][unit_id] = {
            "unit_id": unit_id, "step": index, "round": row["round"],
            "character": row["character"], "label": row["label"],
        }

    step_hash = hashlib.sha256(
        json.dumps(script, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    return {
        "fixture_id": "g5-p%d-combat-smoke" % party_size,
        "version": "g5-fixed-combat-smoke-v1",
        "party_size": party_size,
        "nominal_label": ("1 PC x 1 round" if party_size == 1 else
                          "4 PCs x 3 rounds + 1 enemy batch"),
        "script_source": ("build_one_pc_command_script" if party_size == 1 else
                          "build_command_script"),
        "scripted_step_count": len(script),
        "steps_sha256": step_hash,
        "steps": public_steps,
        "work_units": {
            "actions": [work_units["actions"][key] for key in sorted(work_units["actions"])],
            "batches": [work_units["batches"][key] for key in sorted(work_units["batches"])],
            "controls": [work_units["controls"][key] for key in sorted(work_units["controls"])],
        },
        "measurement_method": {
            "id": "g5-driver-window-work-quiet-v2",
            "version": 2,
            "work_start": "driver_socket_emit_start",
            "work_end": "last_backend_game_output_or_processing_idle",
            "quiet_end": "driver_quiet_window_completion",
            "trace_attribution": "driver_epoch_step_windows_recorded_at_ms",
        },
    }


def build_g5t_script_steps(party_size: int) -> List[Dict[str, Any]]:
    """Build the branch-aware commander/cover script without changing G5 actions."""
    if isinstance(party_size, bool) or party_size not in (1, 4):
        raise ValueError("G5T fixture party size must be 1 or 4")
    party_names = PC_NAMES[:party_size]
    rows: List[Dict[str, Any]] = []

    def add(label: str, text: str, character: Optional[str], round_number: int,
            phase: str, unit_type: str, *, target: Optional[str] = None,
            requires_hit_step: Optional[int] = None,
            requires_combat_exit: bool = False) -> None:
        step_number = len(rows) + 1
        unit_id = "%s-step-%03d" % (
            {"action": "action", "batch": "batch"}[unit_type], step_number
        )
        row = {"label": label, "input": text, "character": character,
               "round": round_number, "phase": phase, "unit_type": unit_type,
               "unit_id": unit_id, "step": step_number}
        if target is not None:
            row["target"] = target
        if requires_hit_step is not None:
            row["requires_hit_step"] = requires_hit_step
        if requires_combat_exit:
            row["requires_combat_exit"] = True
        if unit_type == "batch":
            row["trace_batch_id"] = "enemy:r%d" % round_number
        rows.append(row)

    def attack_and_damage(label: str, name: str, target: str, roll: int,
                          weapon: str, damage: int, round_number: int) -> None:
        attack_step = len(rows) + 1
        add(label, "/att %s %d %s" % (target, roll, weapon), name,
            round_number, "PC_PHASE", "action", target=target)
        add("%s damage" % label, "/dmg %d %s" % (damage, target), name,
            round_number, "PC_PHASE", "action", target=target,
            requires_hit_step=attack_step)

    # Start above both self-preservation thresholds. Scripted PC damage makes
    # those choices available only after the first commander batch.
    add("round1 commander enemy phase (/end)", "/end", None, 1,
        "ENEMY_PHASE", "batch")

    if party_size == 1:
        name = party_names[0]
        attack_and_damage("r2 %s covered-target attack" % name, name,
                          G5T_GOBLIN_NAMES[1], 19, "training blade", 4, 2)
        attack_and_damage("r2 %s Extra Attack second strike" % name, name,
                          G5T_GOBLIN_NAMES[0], 19, "training blade", 4, 2)
        add("round2 commander enemy phase (/end)", "/end", None, 2,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r3 %s Extra Attack first strike" % name, name,
                          G5T_GOBLIN_NAMES[0], 19, "training blade", 3, 3)
        attack_and_damage("r3 %s Extra Attack second strike" % name, name,
                          G5T_GOBLIN_NAMES[1], 19, "training blade", 4, 3)
        add("round3 commander enemy phase (/end)", "/end", None, 3,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r4 %s Extra Attack first strike" % name, name,
                          G5T_COMMANDER_NAME, 19, "training blade", 8, 4)
        attack_and_damage("r4 %s Extra Attack second strike" % name, name,
                          G5T_COMMANDER_NAME, 19, "training blade", 8, 4)
        add("round4 commander enemy phase (/end)", "/end", None, 4,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r5 %s finish remaining goblin" % name, name,
                          G5T_GOBLIN_NAMES[1], 19, "training blade", 3, 5)
        attack_and_damage("r5 %s wound commander" % name, name,
                          G5T_COMMANDER_NAME, 19, "training blade", 3, 5)
        add("round5 commander enemy phase (/end)", "/end", None, 5,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r6 %s Extra Attack first strike" % name, name,
                          G5T_COMMANDER_NAME, 19, "training blade", 6, 6)
        attack_and_damage("r6 %s Extra Attack second strike" % name, name,
                          G5T_COMMANDER_NAME, 19, "training blade", 5, 6)
        add("round6 commander enemy phase (/end)", "/end", None, 6,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r7 %s final Extra Attack first strike" % name, name,
                          G5T_COMMANDER_NAME, 19, "training blade", 3, 7)
        attack_and_damage("r7 %s final Extra Attack second strike" % name, name,
                          G5T_COMMANDER_NAME, 19, "training blade", 6, 7)
        add("final enemy phase (/end) combat exit", "/end", None, 7,
            "ENEMY_PHASE", "batch", requires_combat_exit=True)
    else:
        acheron, merisiel, kira, vitreol = party_names
        attack_and_damage("r2 %s covered-target attack" % acheron, acheron,
                          G5T_GOBLIN_NAMES[1], 19, "training blade", 4, 2)
        attack_and_damage("r2 %s Extra Attack second strike miss" % acheron,
                          acheron, G5T_GOBLIN_NAMES[1], 1,
                          "training blade", 3, 2)
        attack_and_damage("r2 %s wound commander" % merisiel, merisiel,
                          G5T_COMMANDER_NAME, 19, "training blade", 3, 2)
        attack_and_damage("r2 %s wound commander" % kira, kira,
                          G5T_COMMANDER_NAME, 19, "shortsword", 3, 2)
        attack_and_damage("r2 %s wound commander" % vitreol, vitreol,
                          G5T_COMMANDER_NAME, 19, "crossbow, light", 3, 2)
        add("round2 commander enemy phase (/end)", "/end", None, 2,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r3 %s Extra Attack first strike" % acheron, acheron,
                          G5T_GOBLIN_NAMES[0], 19, "training blade", 4, 3)
        attack_and_damage("r3 %s Extra Attack second strike" % acheron,
                          acheron, G5T_GOBLIN_NAMES[1], 19,
                          "training blade", 4, 3)
        attack_and_damage("r3 %s wound commander" % merisiel, merisiel,
                          G5T_COMMANDER_NAME, 19, "training blade", 3, 3)
        attack_and_damage("r3 %s wound commander" % kira, kira,
                          G5T_COMMANDER_NAME, 19, "shortsword", 3, 3)
        attack_and_damage("r3 %s wound commander" % vitreol, vitreol,
                          G5T_COMMANDER_NAME, 19, "crossbow, light", 3, 3)
        add("round3 commander enemy phase (/end)", "/end", None, 3,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r4 %s Extra Attack first strike" % acheron, acheron,
                          G5T_GOBLIN_NAMES[1], 19, "training blade", 3, 4)
        attack_and_damage("r4 %s Extra Attack second strike" % acheron, acheron,
                          G5T_COMMANDER_NAME, 19, "training blade", 3, 4)
        attack_and_damage("r4 %s wound commander" % merisiel, merisiel,
                          G5T_COMMANDER_NAME, 19, "training blade", 3, 4)
        attack_and_damage("r4 %s wound commander" % kira, kira,
                          G5T_COMMANDER_NAME, 19, "shortsword", 3, 4)
        attack_and_damage("r4 %s wound commander" % vitreol, vitreol,
                          G5T_COMMANDER_NAME, 19, "crossbow, light", 3, 4)
        add("round4 commander enemy phase (/end)", "/end", None, 4,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r5 %s finish remaining goblin" % merisiel, merisiel,
                          G5T_GOBLIN_NAMES[0], 19, "training blade", 3, 5)
        add("round5 commander surrender opportunity (/end)", "/end", None, 5,
            "ENEMY_PHASE", "batch")
        attack_and_damage("r6 %s final Extra Attack first strike" % acheron, acheron,
                          G5T_COMMANDER_NAME, 19, "training blade", 5, 6)
        attack_and_damage("r6 %s final Extra Attack second strike" % acheron,
                          acheron, G5T_COMMANDER_NAME, 19,
                          "training blade", 5, 6)
        add("final enemy phase (/end) combat exit", "/end", None, 6,
            "ENEMY_PHASE", "batch", requires_combat_exit=True)
    return rows


def build_g5t_script_active_switch_count(party_size: int) -> int:
    """Bound the initial active-PC selection plus every scripted PC switch."""
    rows = build_g5t_script_steps(party_size)
    current = PC_NAMES[0]
    switches = 1  # The capture driver explicitly selects the first PC at startup.
    for row in rows:
        character = row.get("character")
        if isinstance(character, str) and character and character != current:
            switches += 1
            current = character
    return switches


def build_g5t_fixture_metadata(party_size: int) -> Dict[str, Any]:
    """Describe one named G5T commander scenario and its trace-attribution units."""
    if isinstance(party_size, bool) or party_size not in (1, 4):
        raise ValueError("G5T fixture party size must be 1 or 4")
    rows = build_g5t_script_steps(party_size)
    work_units: Dict[str, Dict[str, Any]] = {"actions": {}, "batches": {}}
    public_steps: List[Dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        unit_type, unit_id = row["unit_type"], row["unit_id"]
        public = {key: row[key] for key in
                  ("label", "character", "round", "phase", "unit_type", "unit_id", "step")}
        for key in ("target", "requires_hit_step", "requires_combat_exit"):
            if key in row:
                public[key] = row[key]
        public["index"] = index
        if row.get("trace_batch_id"):
            public["trace_batch_id"] = row["trace_batch_id"]
        public_steps.append(public)
        bucket = "actions" if unit_type == "action" else "batches"
        work_units[bucket][unit_id] = {
            "unit_id": unit_id, "step": index, "round": row["round"],
            "character": row["character"], "label": row["label"],
        }
    raw_script = [{key: row.get(key) for key in
                   ("label", "input", "character", "round", "phase", "unit_type", "unit_id", "step",
                    "target", "requires_hit_step", "requires_combat_exit",
                    "trace_batch_id") if key in row} for row in rows]
    batch_count = len(work_units["batches"])
    return {
        "fixture_id": "g5t-commander-p%d" % party_size,
        "version": "g5t-commander-v4",
        "party_size": party_size,
        "nominal_label": ("1 PC x %d commander batches" if party_size == 1 else
                          "4 PCs x %d commander batches") % batch_count,
        "script_source": "build_g5t_script_steps",
        "scripted_step_count": len(rows),
        "steps_sha256": hashlib.sha256(
            json.dumps(raw_script, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest(),
        "steps": public_steps,
        "work_units": {
            "actions": [work_units["actions"][key] for key in sorted(work_units["actions"])],
            "batches": [work_units["batches"][key] for key in sorted(work_units["batches"])],
            "controls": [],
        },
        "measurement_method": {
            "id": "g5-driver-window-work-quiet-v2", "version": 2,
            "work_start": "driver_socket_emit_start",
            "work_end": "last_backend_game_output_or_processing_idle",
            "quiet_end": "driver_quiet_window_completion",
            "trace_attribution": "driver_epoch_step_windows_recorded_at_ms",
        },
    }


def build_g5a_script_steps(party_size: int) -> List[Dict[str, Any]]:
    """Build the fixed PC/directive/ally-batch script for one G5A party shape."""
    if isinstance(party_size, bool) or party_size not in G5A_PARTY_SIZES:
        raise ValueError("G5A fixture party size must be 1 or 4")
    party_names = [ONE_PC_NAME] if party_size == 1 else list(PC_NAMES)
    target = ONE_PC_ENEMY_NAME if party_size == 1 else ENEMY_NAMES[0]
    rows: List[Dict[str, Any]] = []

    def add(label: str, command: str, character: Optional[str], unit_type: str,
            *, target_name: Optional[str] = None,
            requires_hit_step: Optional[int] = None) -> int:
        step = len(rows) + 1
        unit_id = "%s-step-%03d" % (
            {"action": "action", "batch": "batch"}[unit_type], step
        )
        row: Dict[str, Any] = {
            "label": label,
            "input": command,
            "character": character,
            "round": 1,
            "phase": "ENEMY_PHASE" if unit_type == "batch" else "PC_PHASE",
            "unit_type": unit_type,
            "unit_id": unit_id,
            "step": step,
        }
        if target_name is not None:
            row["target"] = target_name
        if requires_hit_step is not None:
            row["requires_hit_step"] = requires_hit_step
        if unit_type == "batch":
            row["trace_batch_id"] = "enemy:r1"
        rows.append(row)
        return step

    # The directive must claim the single prefetch re-plan before scripted
    # damage can create a competing state-edge trigger in the P4 run.
    add(
        "accepted ally directive",
        "/cmd %s %s" % (G5A_ALLY_NAME, G5A_DIRECTIVE_TEXT),
        party_names[-1],
        "action",
    )

    for name in party_names:
        weapon_name = G5A_PC_WEAPONS[name][0]
        attack_step = add(
            "%s attack with declared %s" % (name, weapon_name),
            "/att %s 15 %s" % (target, weapon_name),
            name,
            "action",
            target_name=target,
        )
        add(
            "%s damage from declared %s" % (name, weapon_name),
            "/dmg 3 round 1",
            name,
            "action",
            target_name=target,
            requires_hit_step=attack_step,
        )

    add("ally and hostile phase (/end)", "/end", None, "batch")
    return rows


def build_g5a_active_switch_count(party_size: int) -> int:
    """Count startup selection and script-driven active-PC changes."""
    rows = build_g5a_script_steps(party_size)
    party_names = [ONE_PC_NAME] if party_size == 1 else list(PC_NAMES)
    current = party_names[0]
    switches = 1
    for row in rows:
        character = row.get("character")
        if isinstance(character, str) and character and character != current:
            switches += 1
            current = character
    return switches


def build_g5a_fixture_metadata(party_size: int) -> Dict[str, Any]:
    """Describe G5A script inputs and bounded trace work units."""
    rows = build_g5a_script_steps(party_size)
    damage_contract = validate_g5a_scripted_damage(party_size, rows)
    if damage_contract["status"] != "PASS":
        raise ValueError("G5A scripted damage is illegal for declared weapons")
    work_units: Dict[str, Dict[str, Any]] = {"actions": {}, "batches": {}}
    public_steps = []
    for row in rows:
        public = dict(row)
        public["index"] = row["step"]
        public_steps.append(public)
        bucket = "batches" if row["unit_type"] == "batch" else "actions"
        work_units[bucket][row["unit_id"]] = {
            "unit_id": row["unit_id"],
            "step": row["step"],
            "round": row["round"],
            "character": row["character"],
            "label": row["label"],
        }
    serialized = json.dumps(rows, separators=(",", ":"), ensure_ascii=True)
    return {
        "fixture_id": "g5a-ally-p%d" % party_size,
        "version": "g5a-ally-controller-v1",
        "party_size": party_size,
        "nominal_label": "%d-PC party with one active allied NPC" % party_size,
        "script_source": "build_g5a_script_steps",
        "scripted_step_count": len(rows),
        "steps_sha256": hashlib.sha256(serialized.encode("ascii")).hexdigest(),
        "steps": public_steps,
        "work_units": {
            "actions": [work_units["actions"][key] for key in sorted(work_units["actions"])],
            "batches": [work_units["batches"][key] for key in sorted(work_units["batches"])],
            "controls": [],
        },
        "ally": G5A_ALLY_NAME,
        "directive_sha256": hashlib.sha256(
            G5A_DIRECTIVE_TEXT.encode("ascii")
        ).hexdigest(),
        "expected_directive_choice": "take_cover",
        "directive_step": next(row["step"] for row in rows if row["input"].startswith("/cmd ")),
        "ally_batch_step": next(row["step"] for row in rows if row["unit_type"] == "batch"),
        "cover_feature_id": G5A_COVER_FEATURE_ID,
        "damage_contract": damage_contract,
        "measurement_method": {
            "id": "g5-driver-window-work-quiet-v2",
            "version": 2,
            "work_start": "driver_socket_emit_start",
            "work_end": "last_backend_game_output_or_processing_idle",
            "quiet_end": "driver_quiet_window_completion",
            "trace_attribution": "driver_epoch_step_windows_recorded_at_ms",
        },
    }


def validate_g5a_scripted_damage(
    party_size: int,
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Validate each G5A /dmg value against its actor's authored weapon data."""
    script_rows = build_g5a_script_steps(party_size) if rows is None else rows
    rows_by_step = {
        row.get("step"): row for row in script_rows if isinstance(row, dict)
    }
    observations = []
    errors = []
    for row in script_rows:
        if not isinstance(row, dict) or not isinstance(row.get("input"), str):
            errors.append("script_row_malformed")
            continue
        if re.match(r"^/dmg(?:\s|$)", row["input"], re.IGNORECASE) is None:
            continue
        damage_match = re.fullmatch(r"/dmg\s+(\d+)\s+(.+)", row["input"], re.IGNORECASE)
        if damage_match is None:
            errors.append("scripted_damage_command_malformed")
            continue
        actor = row.get("character")
        attack_step = rows_by_step.get(row.get("requires_hit_step"))
        if not isinstance(actor, str) or not isinstance(attack_step, dict):
            errors.append("damage_attack_link_missing")
            continue
        attack_match = re.fullmatch(r"/att\s+(.+)\s+(\d+)\s+(.+)",
                                    str(attack_step.get("input", "")))
        if (attack_match is None or attack_step.get("character") != actor or
                row.get("step", 0) <= attack_step.get("step", 0) or
                row.get("round") != attack_step.get("round") or
                attack_step.get("target") != row.get("target")):
            errors.append("damage_attack_actor_or_command_mismatch")
            continue
        attack_roll = int(attack_match.group(2))
        attack_round = re.fullmatch(
            r"/dmg\s+\d+\s+round\s+(\d+)", row["input"], re.IGNORECASE
        )
        if (attack_roll < 1 or attack_roll >= 20 or attack_round is None or
                int(attack_round.group(1)) != row.get("round")):
            errors.append("damage_not_linked_to_noncritical_attack_round")
            continue
        weapon_name = attack_match.group(3).strip()
        character = build_g5a_character_payload(actor, 20)
        weapons = [item for item in character.get("equipment", [])
                   if isinstance(item, dict)
                   and item.get("item_type") == "weapon"
                   and item.get("equipped") is True
                   and str(item.get("item_name", "")).casefold() == weapon_name.casefold()]
        if len(weapons) != 1:
            errors.append("declared_weapon_missing_or_ambiguous")
            continue
        damage_text = weapons[0].get("damage")
        weapon_damage = re.fullmatch(
            r"\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s+.+\s*", str(damage_text)
        )
        if weapon_damage is None:
            errors.append("declared_weapon_damage_malformed")
            continue
        dice_count = int(weapon_damage.group(1))
        die_sides = int(weapon_damage.group(2))
        modifier_text = weapon_damage.group(3) or "0"
        modifier = int(modifier_text.replace(" ", ""))
        minimum = dice_count + modifier
        maximum = dice_count * die_sides + modifier
        amount = int(damage_match.group(1))
        valid = minimum <= amount <= maximum
        observations.append({
            "step": row.get("step"),
            "actor": actor,
            "weapon": weapon_name,
            "damage": amount,
            "minimum": minimum,
            "maximum": maximum,
            "valid": valid,
        })
        if not valid:
            errors.append("damage_outside_declared_weapon_range")
    expected_count = party_size
    if len(observations) != expected_count:
        errors.append("scripted_damage_count_mismatch")
    return {
        "status": "PASS" if not errors and all(row["valid"] for row in observations) else "FAIL",
        "checked": len(observations),
        "expected": expected_count,
        "observations": observations,
        "errors": sorted(set(errors)),
    }


def build_g5a_training_pit_area() -> Dict[str, Any]:
    """Return CA02 with one authored cover feature legally usable by NPC allies."""
    return {
        "areaId": "CTR001",
        "areaName": "Capture Arena",
        "locations": [{
            "locationId": G5A_COVER_LOCATION_ID,
            "name": "Training Pit",
            "description": "A sunken practice pit ringed by shield racks.",
            "tacticalFeatures": [{
                "featureId": G5A_COVER_FEATURE_ID,
                "name": "Practice Shield Racks",
                "kind": "cover",
                "coverType": "half",
                "usableBy": ["npc"],
            }],
        }],
    }


def g9_row_key(scenario_id: str, party_size: int) -> str:
    """Return the fixed G9 row identity, rejecting values outside its matrix."""
    if scenario_id not in G9_SCENARIOS:
        raise ValueError("unknown G9 scenario: %s" % scenario_id)
    if type(party_size) is not int or party_size not in G9_PARTY_SIZES:
        raise ValueError("G9 party size must be 1 or 4")
    return "%s:p%d" % (scenario_id, party_size)


def required_g9_row_keys() -> tuple[str, ...]:
    """Return the closed eight-row G9 matrix in its canonical order."""
    return G9_REQUIRED_ROW_KEYS


def g10_row_key(phase: str, party_size: int) -> str:
    """Return one fixed G10 full-session phase identity."""
    if phase not in G10_PHASES:
        raise ValueError("G10 phase must be complete or resume")
    if type(party_size) is not int or party_size not in G10_PARTY_SIZES:
        raise ValueError("G10 party size must be 1 or 4")
    return "%s:%s:p%d" % (G10_SCENARIO, phase, party_size)


def required_g10_row_keys() -> tuple[str, ...]:
    """Return the closed four-row G10 complete/resume matrix."""
    return G10_REQUIRED_ROW_KEYS


def build_gate_profile(
    gate: str, scenario_id: str, party_size: int, branch: str = "", phase: str = "",
    path: str = "", boundary: str = "",
) -> Dict[str, Any]:
    """Build one fixed Capture_Arena profile, rejecting unsupported combinations."""
    if gate not in CAPTURE_GATE_CHOICES:
        raise ValueError("unknown capture gate: %s" % gate)
    if gate == "g10":
        if scenario_id != G10_SCENARIO:
            raise ValueError("G10 supports only the fixed full-session scenario")
        if type(party_size) is not int or party_size not in G10_PARTY_SIZES:
            raise ValueError("G10 party size must be 1 or 4")
        if phase not in G10_PHASES:
            raise ValueError("G10 full-session requires --phase complete|resume")
        if branch or path or boundary:
            raise ValueError("G10 does not support --branch, --path, or --boundary")

        combat = build_gate_profile("g5", "combat-smoke", party_size)
        combat_steps = build_g5_script_steps(party_size)
        first_pc = ONE_PC_NAME if party_size == 1 else PC_NAMES[0]
        complete_steps = [{"label": "full-session narration", "input": G10_NARRATION_INPUT,
                           "character": first_pc, "kind": "narration"}]
        complete_steps.extend({"label": row["label"], "input": row["input"],
                               "character": row["character"], "kind": "combat",
                               "script_step": row["step"]} for row in combat_steps)
        complete_steps.extend([
            {"label": "save session", "input": "/save", "character": None, "kind": "save"},
            {"label": "usage report", "input": "/usage", "character": None, "kind": "usage"},
        ])
        phase_steps = complete_steps if phase == "complete" else [
            {"label": "resumed usage report", "input": "/usage", "character": None,
             "kind": "usage"},
        ]
        session_inputs = [row["input"] for row in complete_steps]
        script_sha256 = hashlib.sha256(
            json.dumps(session_inputs, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()
        if phase == "complete":
            max_steps = len(phase_steps)
            max_active_switches = combat["max_active_switches"]
        else:
            max_steps = len(phase_steps)
            max_active_switches = 0
        return {
            "gate": "g10",
            "scenario_id": G10_SCENARIO,
            "party_size": party_size,
            "branch": None,
            "phase": phase,
            "row_key": g10_row_key(phase, party_size),
            "seed_scenario_id": "combat-smoke",
            "seed": copy.deepcopy(combat["seed"]),
            "seed_identity": combat["seed_identity"],
            "max_steps": max_steps,
            "max_inputs": max_steps,
            "max_active_switches": max_active_switches,
            "max_requests": max_steps + 1 + max_active_switches,
            "max_controls": max_steps + 1 + max_active_switches,
            "max_health_reads": 0,
            "turn_timeout_seconds": 150,
            "applicability": {
                "phase": phase,
                "script_sha256": script_sha256,
                "narration": phase == "complete",
                "combat": phase == "complete",
                "save": phase == "complete",
                "usage": True,
                "debug_provenance": True,
                "restart_resume": True,
            },
            "fixture": {
                "fixture_id": "g10-full-session-p%d" % party_size,
                "version": "g10-full-session-v1",
                "party_size": party_size,
                "narration_input": G10_NARRATION_INPUT if phase == "complete" else None,
                "combat_steps": build_g5_fixture_metadata(party_size)["steps"],
                "save_command": "/save" if phase == "complete" else None,
                "usage_command": "/usage",
                "script_sha256": script_sha256,
                "steps": phase_steps,
                "complete_steps": complete_steps,
            },
        }
    if gate == "g9":
        row_key = g9_row_key(scenario_id, party_size)
        if branch or path or boundary:
            raise ValueError("G9 does not support --branch, --path, or --boundary")
        if scenario_id == "preferred-openai-rollback":
            if phase not in ("", G9_ROLLBACK_PHASE):
                raise ValueError("preferred-openai-rollback supports only --phase rollback")
        elif phase:
            raise ValueError("--phase applies only to preferred-openai-rollback with --gate g9")

        if scenario_id == "narrator-auto":
            profile = build_gate_profile(
                "g4", "narrator-dialogue-travel", party_size
            )
            seed_scenario_id = "narrator-dialogue-travel"
            capture_kind = "narrator"
        else:
            profile = build_gate_profile("g5", "combat-smoke", party_size)
            seed_scenario_id = "combat-smoke"
            capture_kind = "combat"

        profile.update({
            "gate": "g9",
            "scenario_id": scenario_id,
            "seed_scenario_id": seed_scenario_id,
            "party_size": party_size,
            "phase": phase or None,
            "row_key": row_key,
            "capture_kind": capture_kind,
            "g9_runtime": {
                "configured_provider": (
                    "openai" if phase == G9_ROLLBACK_PHASE else "openrouter"
                ),
                "active_profile": "production-auto",
                "transport_failure_injection": scenario_id == "transport-failure",
                "operator_restart_count": (
                    1 if phase == G9_ROLLBACK_PHASE else 0
                ),
                "reseed_after_rollback": False,
            },
        })
        profile["branch"] = None
        return profile
    if gate == "g7":
        if scenario_id != "turn-commit":
            raise ValueError("G7 supports only the named turn-commit scenario")
        if party_size not in (1, 4) or isinstance(party_size, bool):
            raise ValueError("G7 capture party size must be 1 or 4")
        if path not in G7_COMMIT_PATHS:
            raise ValueError("G7 --path must be normal or enemy_batch")
        if phase not in G7_COMMIT_PHASES:
            raise ValueError("G7 --phase must be interrupt, recover, complete, or replay")
        if phase in G7_COMMIT_LIFECYCLE_PHASES and boundary not in g7_commit_boundaries(party_size, path):
            raise ValueError("unsupported G7 boundary for party size %d path %s: %s" %
                             (party_size, path, boundary or "missing"))
        if phase in G7_COMMIT_REPLAY_PHASES and boundary != "none":
            raise ValueError("G7 complete/replay phases require --boundary none")
        if branch:
            raise ValueError("--branch is not supported by G7")
        fixture = build_g7_turn_commit_fixture(party_size, path)
        step_count = 1 if phase in ("interrupt", "complete") else 0
        return {
            "gate": gate,
            "scenario_id": scenario_id,
            "party_size": party_size,
            "branch": None,
            "phase": phase,
            "path": path,
            "boundary": boundary,
            "max_steps": step_count,
            "max_inputs": step_count,
            "max_active_switches": 1 if phase in ("interrupt", "complete") else 0,
            "max_requests": 3 if phase in ("interrupt", "complete") else 1,
            "max_controls": 3 if phase in ("interrupt", "complete") else 1,
            "max_health_reads": 1,
            "turn_timeout_seconds": 150,
            "lifecycle_stop_timeout_seconds": G7_LIFECYCLE_STOP_TIMEOUT_SECONDS,
            "applicability": {
                "phase": phase,
                "path": path,
                "boundary": boundary,
                "completed_turn_replay": phase in G7_COMMIT_REPLAY_PHASES,
            },
            "seed": {
                "encounter_id": fixture["encounter_id"],
                "pc_hit_points": fixture["pc_hit_points"],
                "pc_armor_class": fixture["pc_armor_class"],
                "normal_input": fixture["normal_input"],
                "input": fixture["input"],
                "normal_expected_characters": fixture["normal_expected_characters"],
                "enemy_batch_expected_characters": fixture["enemy_batch_expected_characters"],
                "fault_point": boundary if phase == "interrupt" else None,
                "tactical_brain": False,
                "tactical_prefetch": False,
                "path": path,
                "expected_changed_characters": fixture["expected_changed_characters"],
                "preroll_seed": fixture["preroll_seed"],
            },
            "fixture": {
                "encounter_id": fixture["encounter_id"],
                "party_names": fixture["party_names"],
                "normal_expected_characters": fixture["normal_expected_characters"],
                "enemy_batch_expected_characters": fixture["enemy_batch_expected_characters"],
                "expected_changed_characters": fixture["expected_changed_characters"],
            },
        }
    if gate == "g3":
        if scenario_id in ("narrator-dialogue-travel",):
            raise ValueError("narrator-dialogue-travel is available only for --gate g4")
        return build_capture_profile(scenario_id, party_size, branch, phase)

    if gate in G5_CAPTURE_GATES:
        if gate == "g5a":
            if isinstance(party_size, bool) or party_size not in G5A_PARTY_SIZES:
                raise ValueError("G5A capture party size must be 1 or 4")
            expected_scenario = "g5a-ally-p%d" % party_size
            if scenario_id != expected_scenario:
                raise ValueError("G5A supports only the matching named P1 or P4 ally scenario")
            if branch or phase or path or boundary:
                raise ValueError("G5A does not support --branch/--phase/--path/--boundary")
            steps = build_g5a_script_steps(party_size)
            switches = build_g5a_active_switch_count(party_size)
            seed = {
                "party_ally": {"name": G5A_ALLY_NAME, "role": "Ally"},
                "hostile_hit_points": 40,
                "ally_hit_points": 12,
                "ally_armor_class": 13,
                "ally_cover_feature_id": G5A_COVER_FEATURE_ID,
                "cover_location_id": G5A_COVER_LOCATION_ID,
                "initiativeWinner": "pcGroup",
                "roundStartsWith": "pcGroup",
                "awaitingPcGroupRoll": False,
                "encounter_context": (
                    "The allied arena companion has been ordered to take cover at the "
                    "authored shield racks. The practice feature is available to allied NPCs."
                ),
            }
            return {
                "gate": gate,
                "scenario_id": scenario_id,
                "party_size": party_size,
                "branch": None,
                "phase": None,
                "max_steps": len(steps),
                "max_inputs": len(steps),
                "max_active_switches": switches,
                "max_requests": len(steps) + 1 + switches,
                "max_controls": len(steps) + 1 + switches,
                "max_health_reads": 0,
                "turn_timeout_seconds": 150,
                "applicability": {
                    "party_size": party_size,
                    "active_allied_npcs": 1,
                    "authored_cover_feature_id": G5A_COVER_FEATURE_ID,
                    "scripted_damage_weapon_validation": True,
                },
                "seed": seed,
                "seed_identity": "P%d PCs + %s + authored ally cover" % (
                    party_size, G5A_ALLY_NAME
                ),
                "npc_characters": {
                    G5A_ALLY_NAME: build_capture_allied_npc_payload(G5A_ALLY_NAME)
                },
                "fixture": build_g5a_fixture_metadata(party_size),
            }
        if gate == "g5t":
            if party_size not in (1, 4):
                raise ValueError("capture party size must be 1 or 4")
            if scenario_id != "g5t-commander-p%d" % party_size:
                raise ValueError("G5T supports only the named g5t-commander-p1 or g5t-commander-p4 scenario")
            if branch or phase:
                raise ValueError("--branch/--phase are not supported by G5T commander profiles")
            steps = build_g5t_script_steps(party_size)
            switches = build_g5t_script_active_switch_count(party_size)
            pc_hit_points = build_g5t_worst_case_pc_hit_points(party_size)
            return {
                "gate": gate, "scenario_id": scenario_id, "party_size": party_size,
                "branch": None, "phase": None, "max_steps": len(steps),
                "max_inputs": len(steps), "max_active_switches": switches,
                "max_requests": len(steps) + 1 + switches,
                "max_controls": len(steps) + 1 + switches, "max_health_reads": 0,
                "applicability": {"party_size": party_size},
                "seed": {"captain_hit_points": 39,
                         "goblin_squad_a_hit_points": 7,
                         "goblin_squad_b_hit_points": 7,
                         "goblin_squad_b_cover_type": "half",
                         "goblin_squad_b_cover_feature_id": G5T_TRAINING_PIT_FEATURE_ID,
                         "pc_hit_points": pc_hit_points,
                         "awaitingPcGroupRoll": False, "initiativeWinner": "pcGroup"},
                "seed_identity": "Hobgoblin Captain + Goblin Squad A+B",
                "fixture": build_g5t_fixture_metadata(party_size),
            }
        if scenario_id != "combat-smoke":
            raise ValueError("%s supports only the fixed combat-smoke latency fixture" % gate.upper())
        profile = build_capture_profile(scenario_id, party_size, branch, phase)
        # P1 keeps its established 5/7 capture budget. P4 runs the complete
        # default latency script (26 inputs), not the shorter G3 named scenario
        # cap. Controls follow the existing G3 rule: inputs + start_game + the
        # allowed active-PC switches.
        if party_size == 4:
            profile["max_steps"] = len(build_g5_script_steps(party_size))
            profile["max_requests"] = (
                profile["max_steps"] + 1 + profile["max_active_switches"]
            )
        profile.update({
            "gate": gate,
            "max_inputs": profile["max_steps"],
            "max_controls": profile["max_requests"],
            "seed_identity": "P1 Goblin" if party_size == 1 else "P4 Goblin Alpha+Beta",
            "fixture": build_g5_fixture_metadata(party_size),
        })
        return profile

    if branch or phase:
        raise ValueError("--branch/--phase are not supported by fixed G4 profiles")
    if scenario_id == "narrator-dialogue-travel":
        if party_size not in (1, 4):
            raise ValueError("capture party size must be 1 or 4")
        return {
            "gate": "g4",
            "scenario_id": scenario_id,
            "party_size": party_size,
            "branch": None,
            "phase": None,
            "max_steps": 6,
            "max_inputs": 6,
            "max_requests": 8 if party_size == 1 else 9,
            "max_controls": 8 if party_size == 1 else 9,
            "max_active_switches": 1 if party_size == 1 else 2,
            "max_health_reads": 3,
            "turn_timeout_seconds": 300,
            "turns": [
                {"label": label, "input": utterance,
                 "character": p1_actor if party_size == 1 else p4_actor,
                 "expected_location_id": location_id, "kind": kind}
                for label, utterance, p1_actor, p4_actor, location_id, kind in G4_NARRATOR_TURNS
            ],
            "seed": {"starting_location_id": "CA01", "active_combat_encounter": "",
                     "mira_source": "Capture_Arena areas/CTR001.json CA03 authored NPC"},
        }
    if scenario_id == "combat-smoke":
        profile = build_capture_profile(scenario_id, party_size)
        profile.update({"gate": "g4", "max_inputs": profile["max_steps"],
                        "max_controls": profile["max_requests"],
                        "max_health_reads": 3,
                        "turn_timeout_seconds": 300,
                        "seed_identity": ("P1 Goblin" if party_size == 1 else "P4 Goblin Alpha+Beta")})
        return profile
    raise ValueError("G4 supports only narrator-dialogue-travel or combat-smoke")


def apply_capture_profile(
    encounter: Dict[str, Any], party: Dict[str, Any], profile: Dict[str, Any]
) -> None:
    """Apply one named profile to existing schema-compatible fixture records."""
    scenario_id = profile["scenario_id"]
    seed = profile["seed"]
    creatures = encounter["creatures"]
    encounter.setdefault("encounterSummary", "Capture Arena named scenario seed: %s" % scenario_id)
    if scenario_id in ("combat-smoke", "combat-smoke-allied-inactive"):
        encounter["encounterSummary"] = seed["encounter_context"]
    elif scenario_id in ("g5a-ally-p1", "g5a-ally-p4"):
        encounter["encounterSummary"] = seed["encounter_context"]
    elif scenario_id == "surrender-exit" and profile.get("branch") == "surrender":
        encounter["encounterSummary"] = seed["encounter_context"]
    if scenario_id in ("initiative-pc", "initiative-dm-tie"):
        encounter["initiativeMode"] = "two_group_phase1"
        encounter["initiativeRolls"] = {"dmGroup": seed["dmGroup"], "pcGroup": None}
        encounter["initiativeWinner"] = None
        encounter["roundStartsWith"] = None
        encounter["awaitingPcGroupRoll"] = True
        encounter["openingEnemyBatchPending"] = False
    elif scenario_id == "death-save":
        pc = next(item for item in creatures if item["name"] == seed["pending_death_save_pc"])
        pc.update({"currentHitPoints": 0, "status": "unconscious", "conditions": ["unconscious"],
                   "deathSaves": {"successes": 0, "failures": 0}})
    elif scenario_id == "combat-smoke-allied-inactive":
        creatures.append({
            "name": seed["allied_npc"], "type": "npc", "npcType": "ally", "initiative": 12,
            "armorClass": 13, "currentHitPoints": 12, "maxHitPoints": 12,
            "status": "alive", "conditions": [], "actions": {"actionType": "attack", "target": "enemy"},
        })
        creatures.append({
            "name": seed["inactive_enemy"], "type": "enemy", "monsterType": "Goblin",
            "initiative": 5, "armorClass": 12, "currentHitPoints": 0,
            "maxHitPoints": 20, "status": "defeated", "conditions": [],
            "actions": {"actionType": "attack", "target": "player"},
        })
    elif scenario_id in ("g5a-ally-p1", "g5a-ally-p4"):
        for creature in creatures:
            if creature.get("type") == "enemy":
                creature["currentHitPoints"] = seed["hostile_hit_points"]
                creature["maxHitPoints"] = seed["hostile_hit_points"]
        ally_payload = build_capture_allied_npc_payload(G5A_ALLY_NAME)
        creatures.append({
            "name": G5A_ALLY_NAME,
            "type": "npc",
            "npcType": "ally",
            "initiative": 12,
            "armorClass": seed["ally_armor_class"],
            "currentHitPoints": seed["ally_hit_points"],
            "maxHitPoints": seed["ally_hit_points"],
            "status": "alive",
            "conditions": [],
            "attacksAndSpellcasting": ally_payload["attacksAndSpellcasting"],
            "actions": {"actionType": "attack", "target": "enemy"},
        })
        encounter.update({
            "initiativeMode": "two_group_phase1",
            "initiativeRolls": {"dmGroup": 12, "pcGroup": 18},
            "initiativeWinner": "pcGroup",
            "roundStartsWith": "pcGroup",
            "awaitingPcGroupRoll": False,
            "openingEnemyBatchPending": False,
            "combat_round": 1,
            "current_round": 1,
        })
    elif scenario_id == "surrender-exit":
        for enemy_name in seed["inactive_enemies"]:
            enemy = next((row for row in creatures if row.get("name") == enemy_name and row.get("type") == "enemy"), None)
            if enemy is not None:
                enemy.update({"currentHitPoints": 0, "status": "defeated"})
    for creature in creatures:
        creature.setdefault("conditions", [])
        creature.setdefault("actions", {"actionType": "", "target": ""})



def _character_payload(name: str, initiative: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "player",
        "character_type": "player",
        "hitPoints": 20,
        "maxHitPoints": 20,
        "armorClass": 14,
        "initiative": initiative,
        "status": "alive",
        "deathSaves": {"successes": 0, "failures": 0},
    }


def build_capture_character_payload(
    name: str, initiative: int, overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Build a full-schema named PC while leaving the bare latency fixture intact."""
    payload = build_capture_npc_payload(name)
    # Preserve values from the historical minimal record where those fields are
    # part of the canonical schema; named-only fields below complete the shape.
    payload.update(_character_payload(name, initiative))
    payload.update({
        "character_role": "player", "character_type": "player", "type": "player",
        "hitPoints": 20, "maxHitPoints": 20, "armorClass": 14,
        "initiative": initiative, "status": "alive", "condition": "none",
        "condition_affected": [], "deathSaves": {"successes": 0, "failures": 0},
        "abilities": {key: 10 for key in ("strength", "dexterity", "constitution",
                                          "intelligence", "wisdom", "charisma")},
        "experience_points": 0,
        "spellcasting": {"spells": {}, "spellSlots": {}, "preparedSpells": []},
    })
    if name in ("Acheron", "Merisiel"):
        payload["equipment"] = [{
            "item_name": "training blade", "item_type": "weapon",
            "description": "Capture fixture training blade.", "quantity": 1,
            "equipped": True, "damage": "1d6+2 slashing",
        }]
        if name == "Acheron":
            payload["classFeatures"] = [{
                "name": "Extra Attack",
                "description": (
                    "When you take the Attack action on your turn, you can make "
                    "two attacks instead of one."
                ),
            }]
    elif name == "Kira":
        payload["equipment"] = [{
            "item_name": "shortsword", "item_type": "weapon",
            "description": "SRD shortsword for the Capture Arena fixture.",
            "quantity": 1, "equipped": True, "damage": "1d6+2 piercing",
        }]
    elif name == "Vitreol":
        payload["equipment"] = [{
            "item_name": "crossbow, light", "item_type": "weapon",
            "description": "Light crossbow for the Capture Arena fixture.",
            "quantity": 1, "equipped": True, "damage": "1d8+2 piercing",
        }]
        payload["ammunition"] = [{
            "name": "crossbow bolts", "quantity": 3,
            "description": "Standard crossbow bolts for use with crossbows",
        }]
    if overrides:
        payload.update(overrides)
    return payload


def build_g5a_character_payload(name: str, initiative: int) -> Dict[str, Any]:
    """Build a G5A PC with the exact 5e weapon used by its scripted attack."""
    if name not in G5A_PC_WEAPONS:
        raise ValueError("unsupported G5A player weapon declaration")
    weapon_name, damage = G5A_PC_WEAPONS[name]
    equipment = {
        "item_name": weapon_name,
        "item_type": "weapon",
        "description": "SRD 5.2.1 weapon declared for the G5A capture fixture.",
        "quantity": 1,
        "equipped": True,
        "damage": damage,
    }
    if weapon_name == "light crossbow":
        equipment["weapon_type"] = "ranged"
    return build_capture_character_payload(
        name,
        initiative,
        {"equipment": [equipment]},
    )


def build_capture_npc_payload(name: str) -> Dict[str, Any]:
    """Return a static NPC companion record conforming to the existing char schema."""
    return {
        "character_role": "npc", "character_type": "npc", "name": name,
        "type": "npc", "size": "Medium", "level": 1, "race": "Human",
        "class": "Fighter", "alignment": "neutral", "background": "Soldier",
        "status": "alive", "condition": "none", "condition_affected": [],
        "hitPoints": 12, "maxHitPoints": 12, "armorClass": 13, "initiative": 12,
        "speed": 30,
        "abilities": {"strength": 12, "dexterity": 12, "constitution": 12,
                       "intelligence": 10, "wisdom": 10, "charisma": 10},
        "savingThrows": [], "skills": [], "proficiencyBonus": 2, "senses": {},
        "languages": ["Common"], "proficiencies": {"armor": [], "weapons": [], "tools": []},
        "damageVulnerabilities": [], "damageResistances": [], "damageImmunities": [],
        "conditionImmunities": [], "classFeatures": [], "racialTraits": [],
        "backgroundFeature": {"name": "Arena Ally", "description": "A practice companion."},
        "temporaryEffects": [], "injuries": [], "equipment_effects": [], "feats": [],
        "equipment": [], "attacksAndSpellcasting": [], "spellcasting": {},
        "currency": {"gold": 0, "silver": 0, "copper": 0},
        "experience_points": 0, "exp_required_for_next_level": 300,
        "personality_traits": "Steady and helpful.", "ideals": "Practice fairly.",
        "bonds": "The Capture Arena crew.", "flaws": "Overly cautious.",
        "backstory": "A training ally assigned to the Capture Arena.",
    }


def build_capture_allied_npc_payload(name: str) -> Dict[str, Any]:
    """Add authored, schema-valid weapon mechanics only to the named ally seed."""
    if name != CAPTURE_ALLIED_NPC_NAME:
        raise ValueError("capture attack profile is reserved for Blairen")
    payload = build_capture_npc_payload(name)
    payload["proficiencies"]["weapons"] = ["simple weapons", "martial weapons"]
    payload["equipment"] = [{
        "item_name": "longsword",
        "item_type": "weapon",
        "description": "SRD longsword carried by the Capture Arena ally.",
        "quantity": 1,
        "equipped": True,
        "damage": "1d8 slashing",
        "attack_bonus": 3,
        "weapon_type": "melee",
    }]
    payload["attacksAndSpellcasting"] = [{
        "name": "longsword",
        "attackBonus": 3,
        "damageDice": "1d8",
        "damageBonus": 1,
        "damageType": "slashing",
        "type": "melee",
        "description": "Melee weapon attack: +3 to hit, reach 5 ft., one target. Hit: 1d8 + 1 slashing damage.",
    }]
    return payload


def _encounter_payload() -> Dict[str, Any]:
    return {
        "id": "fixture_mp",
        "encounterId": "fixture_mp",
        "combat_round": 1,
        "initiativeMode": "two_group_phase1",
        "initiativeRolls": {"dmGroup": 12, "pcGroup": 18},
        "initiativeWinner": "pcGroup",
        "roundStartsWith": "pcGroup",
        "awaitingPcGroupRoll": False,
        "openingEnemyBatchPending": False,
        "creatures": [
            {
                "name": "Goblin Alpha",
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": ENEMY_INITIATIVES["Goblin Alpha"],
                "armorClass": 12,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "status": "alive",
            },
            {
                "name": "Goblin Beta",
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": ENEMY_INITIATIVES["Goblin Beta"],
                "armorClass": 12,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "status": "alive",
            },
        ],
    }


def _one_pc_encounter_payload() -> Dict[str, Any]:
    """Return the fixed one-PC, one-enemy encounter payload."""
    return {
        "id": "fixture_one_pc",
        "encounterId": "fixture_one_pc",
        "combat_round": 1,
        "initiativeMode": "one_pc_compatible",
        "initiativeRolls": {"dmGroup": 10, "pcGroup": 18},
        "initiativeWinner": "pcGroup",
        "roundStartsWith": "pcGroup",
        "awaitingPcGroupRoll": False,
        "openingEnemyBatchPending": False,
        "creatures": [
            {
                "name": ONE_PC_ENEMY_NAME,
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": ONE_PC_ENEMY_INITIATIVE,
                "armorClass": 12,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "status": "alive",
            }
        ],
    }


def _fixed_queue(manager: "MultiPCCombatManager") -> None:
    """Replace random initiative results with the fixture's fixed values."""
    for combatant in manager._turns.turn_queue:
        if combatant.name in PC_INITIATIVES:
            combatant.initiative = PC_INITIATIVES[combatant.name]
        elif combatant.name in ENEMY_INITIATIVES:
            combatant.initiative = ENEMY_INITIATIVES[combatant.name]
    manager._turns.turn_queue.sort(key=lambda item: item.initiative, reverse=True)
    manager._turns.current_turn_index = 0


def _fixed_one_pc_queue(manager: "MultiPCCombatManager") -> None:
    """Replace 1-PC party initiative results with the fixture's fixed values."""
    for combatant in manager._turns.turn_queue:
        if combatant.name == ONE_PC_NAME:
            combatant.initiative = ONE_PC_INITIATIVE
        elif combatant.name == ONE_PC_ENEMY_NAME:
            combatant.initiative = ONE_PC_ENEMY_INITIATIVE
    manager._turns.turn_queue.sort(key=lambda item: item.initiative, reverse=True)
    manager._turns.current_turn_index = 0


def build_mp_fixture() -> Dict[str, Any]:
    """Create a sandboxed four-PC fixture and initialize the real manager."""
    tempdir = tempfile.TemporaryDirectory(dir="tmp")
    sandbox = Path(tempdir.name)
    previous_cwd = os.getcwd()
    try:
        os.chdir(sandbox)
        (sandbox / "characters").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "fixture_module" / "areas").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "encounters").mkdir(parents=True, exist_ok=True)

        party = {
            "partyMembers": list(PC_NAMES),
            "active_character": PC_NAMES[0],
            "module": "fixture_module",
            "worldConditions": {"activeCombatEncounter": "fixture_mp"},
        }
        safe_write_json("party_tracker.json", party)
        for name in PC_NAMES:
            safe_write_json(
                str(Path("characters") / (name.lower() + ".json")),
                _character_payload(name, PC_INITIATIVES[name]),
            )
        encounter = _encounter_payload()
        safe_write_json("modules/encounters/encounter_fixture_mp.json", encounter)

        manager = _make_mp_manager()
        manager.initialize_from_party(party)
        manager.initialize_turn_queue(encounter)
        _fixed_queue(manager)
        trace_path = sandbox / "debug" / "combat_turn_trace.jsonl"
        return {
            "tempdir": tempdir,
            "sandbox": sandbox,
            "manager": manager,
            "encounter": encounter,
            "party": party,
            "trace_path": trace_path,
            "enemy_batches": 0,
            "rounds_completed": 0,
            "command_script": build_command_script(),
        }
    except Exception:
        tempdir.cleanup()
        raise
    finally:
        os.chdir(previous_cwd)


def build_one_pc_fixture() -> Dict[str, Any]:
    """Create a sandboxed one-PC fixture using the minimum-party command path."""
    tempdir = tempfile.TemporaryDirectory(dir="tmp")
    sandbox = Path(tempdir.name)
    previous_cwd = os.getcwd()
    try:
        os.chdir(sandbox)
        (sandbox / "characters").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "fixture_module" / "areas").mkdir(parents=True, exist_ok=True)
        (sandbox / "modules" / "encounters").mkdir(parents=True, exist_ok=True)

        party = {
            "partyMembers": [ONE_PC_NAME],
            "active_character": ONE_PC_NAME,
            "module": "fixture_module",
            "worldConditions": {"activeCombatEncounter": "fixture_one_pc"},
        }
        safe_write_json("party_tracker.json", party)
        safe_write_json(
            str(Path("characters") / "acheron.json"),
            _character_payload(ONE_PC_NAME, ONE_PC_INITIATIVE),
        )
        encounter = _one_pc_encounter_payload()
        safe_write_json("modules/encounters/encounter_fixture_one_pc.json", encounter)

        manager = _make_mp_manager()
        manager.initialize_from_party(party)
        manager.initialize_turn_queue(encounter)
        _fixed_one_pc_queue(manager)
        trace_path = sandbox / "debug" / "combat_turn_trace.jsonl"
        return {
            "tempdir": tempdir,
            "sandbox": sandbox,
            "manager": manager,
            "encounter": encounter,
            "party": party,
            "trace_path": trace_path,
            "rounds_completed": 0,
            "command_script": build_one_pc_command_script(),
        }
    except Exception:
        tempdir.cleanup()
        raise
    finally:
        os.chdir(previous_cwd)


def build_command_script() -> List[str]:
    """Return the fixed ordered input script used by the MP fixture."""
    commands = ["/init 18"]
    for round_number in range(1, 4):
        for name in PC_NAMES:
            commands.extend(
                [
                    f"{name}: /att Goblin Alpha 20 training blade",
                    f"{name}: /dmg 1 round {round_number}",
                ]
            )
        if round_number == 1:
            commands.append("/end (enemy batch trigger)")
    return commands


def build_one_pc_command_script() -> List[str]:
    """Return the fixed one-round 1-PC party command sequence."""
    return [
        "%s: /att %s 20 training blade" % (ONE_PC_NAME, ONE_PC_ENEMY_NAME),
        "%s: /dmg 1 round 1" % ONE_PC_NAME,
        "/end (enemy phase completion)",
    ]


def _assert_round_invariants(fixture: Dict[str, Any], round_number: int) -> None:
    manager = fixture["manager"]
    pc_names = list(manager.pc_states.keys())
    assert len(pc_names) == 4, "MP fixture round %d: expected four PCs" % round_number
    assert len({_name.lower() for _name in pc_names}) == 4, (
        "MP fixture round %d: duplicate PC roster" % round_number
    )
    assert manager.combat_phase == "ENEMY_PHASE", (
        "MP fixture round %d: PC phase did not complete" % round_number
    )
    queue_names = [combatant.name for combatant in manager._turns.turn_queue]
    for name in PC_NAMES + ENEMY_NAMES:
        assert queue_names.count(name) == 1, (
            "MP fixture round %d: queue actor mismatch for %s" % (round_number, name)
        )


def _exercise_compression_instrumentation(fixture: Dict[str, Any]) -> None:
    """Exercise the production compressor cache and trace hooks without a provider."""
    from core.ai.combat_compressor import CombatUserMessageCompressor

    # Construction is provider-free after the facade migration. Fail closed if
    # this cache/instrumentation fixture ever tries to issue a facade request.
    from core.ai import combat_compression_engine

    with patch.object(
        combat_compression_engine.llm,
        "call",
        side_effect=_UnexpectedCompressionRequest("unexpected compression request"),
    ) as facade_call:
        compressor = CombatUserMessageCompressor(
            cache_file=str(fixture["sandbox"] / "modules" / "conversation_history" / "fixture-cache.json")
        )
        assert not hasattr(compressor.combat_compressor, "client"), (
            "combat fixture: compressor retained a provider client"
        )
        facade_call.assert_not_called()
    compressor.combat_compressor.compress = lambda content: "fixture-compressed"
    first = compressor.compress_message((0, "fixture combat message"))
    second = compressor.compress_message((0, "fixture combat message"))
    assert first[1] == "fixture-compressed" and first[2] is False, (
        "MP fixture: compression miss did not call the stub"
    )
    assert second[1] == "fixture-compressed" and second[2] is True, (
        "MP fixture: compression hit did not use the cache"
    )


def run_mp_fixture(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Run three fixed rounds through the real multi-PC combat APIs."""
    manager = fixture["manager"]
    encounter = fixture["encounter"]
    previous_cwd = os.getcwd()
    try:
        os.chdir(fixture["sandbox"])
        set_trace_context(mode="mp", fixture="combat_latency_baseline")
        trace_file_operation("read", "fixture_encounter_load")
        assert safe_read_json("modules/encounters/encounter_fixture_mp.json") is not None
        _exercise_compression_instrumentation(fixture)

        for round_number in range(1, 4):
            started_at = time.perf_counter()
            for name in PC_NAMES:
                feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
                    "/att Goblin Alpha 20 training blade", encounter, actor_name=name
                )
                assert skip_llm and feedback, "round %d: attack fast path failed" % round_number
                feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
                    "/dmg 1 round %d" % round_number, encounter, actor_name=name
                )
                assert skip_llm and feedback, "round %d: damage fast path failed" % round_number
                phase_complete = manager.complete_pc_turn(name)
                expected_complete = name == PC_NAMES[-1]
                assert phase_complete == expected_complete, (
                    "round %d: unexpected PC phase completion for %s" % (round_number, name)
                )

            _assert_round_invariants(fixture, round_number)
            trace_stage("fixture_round_%d" % round_number, started_at, mode="mp")
            if round_number == 1:
                enemy_batch = manager.get_remaining_enemies_for_round()
                assert enemy_batch == ENEMY_NAMES, "MP fixture: unexpected enemy batch"
                fixture["enemy_batches"] += 1
                manager._turns.enemy_phase_complete = True
                assert manager.pc_phase_complete and manager._turns.enemy_phase_complete, (
                    "MP fixture round 1: enemy batch phase flags are incoherent"
                )
            else:
                assert manager.pc_phase_complete and not manager._turns.enemy_phase_complete, (
                    "MP fixture round %d: untriggered enemy phase flags are incoherent" % round_number
                )
            fixture["rounds_completed"] += 1
            if round_number < 3:
                manager.start_new_round()

        assert fixture["rounds_completed"] == 3, "MP fixture: expected three rounds"
        assert fixture["enemy_batches"] == 1, "MP fixture: expected one enemy batch"
        assert manager.pc_phase_complete and not manager._turns.enemy_phase_complete, (
            "MP fixture: final phase flags are incoherent"
        )
        return {
            "pc_names": list(manager.pc_states.keys()),
            "queue_names": [combatant.name for combatant in manager._turns.turn_queue],
            "rounds_completed": fixture["rounds_completed"],
            "enemy_batches": fixture["enemy_batches"],
        }
    finally:
        os.chdir(previous_cwd)


def run_one_pc_fixture(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Run exactly one round through the minimum-party tabletop command APIs."""
    manager = fixture["manager"]
    encounter = fixture["encounter"]
    previous_cwd = os.getcwd()
    try:
        os.chdir(fixture["sandbox"])
        set_trace_context(mode="one_pc", fixture="combat_latency_baseline")
        trace_file_operation("read", "fixture_one_pc_encounter_load")
        assert safe_read_json("modules/encounters/encounter_fixture_one_pc.json") is not None

        started_at = time.perf_counter()
        feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
            "/att %s 20 training blade" % ONE_PC_ENEMY_NAME,
            encounter,
            actor_name=ONE_PC_NAME,
        )
        assert skip_llm and feedback, "1-PC party fixture round 1: attack fast path failed"
        feedback, _spoken, _log, skip_llm = manager.handle_combat_command(
            "/dmg 1 round 1",
            encounter,
            actor_name=ONE_PC_NAME,
        )
        assert skip_llm and feedback, "1-PC party fixture round 1: damage fast path failed"
        assert manager.complete_pc_turn(ONE_PC_NAME), (
            "1-PC party fixture round 1: PC phase did not complete"
        )
        assert manager.combat_phase == "ENEMY_PHASE", (
            "1-PC party fixture round 1: phase did not enter enemy phase"
        )
        enemy_batch = manager.get_remaining_enemies_for_round()
        assert enemy_batch == [ONE_PC_ENEMY_NAME], "1-PC party fixture: unexpected enemy batch"
        manager._turns.enemy_phase_complete = True
        assert manager.pc_phase_complete and manager._turns.enemy_phase_complete, (
            "1-PC party fixture round 1: phase flags are incoherent"
        )
        trace_stage("fixture_one_pc_round_1", started_at, mode="one_pc")

        queue_names = [combatant.name for combatant in manager._turns.turn_queue]
        assert queue_names.count(ONE_PC_NAME) == 1, "1-PC party fixture: PC roster mismatch"
        assert queue_names.count(ONE_PC_ENEMY_NAME) == 1, "1-PC party fixture: enemy roster mismatch"
        fixture["rounds_completed"] += 1
        assert fixture["rounds_completed"] == 1, "1-PC party fixture: expected one round"
        return {
            "mode": "one_pc",
            "pc_names": list(manager.pc_states.keys()),
            "enemy_names": enemy_batch,
            "queue_names": queue_names,
            "rounds_completed": fixture["rounds_completed"],
            "pc_phase_complete": manager.pc_phase_complete,
            "enemy_phase_complete": manager._turns.enemy_phase_complete,
        }
    finally:
        os.chdir(previous_cwd)


def print_live_script() -> None:
    """Print the ordered input script for a manual live combat run."""
    for index, command in enumerate(build_command_script(), 1):
        print("%02d. %s" % (index, command))


G5T_COMMANDER_NAME = "Hobgoblin Captain"
G5T_GOBLIN_NAMES = ("Goblin Squad A", "Goblin Squad B")
G5T_TRAINING_PIT_LOCATION_ID = "CA02"
G5T_TRAINING_PIT_FEATURE_ID = "ca02-shield-racks"


def build_g5t_commander_monster() -> Dict[str, Any]:
    """Return the provider-free SRD-style Hobgoblin Captain stat block."""
    return {
        "name": G5T_COMMANDER_NAME,
        "size": "Medium",
        "type": "Humanoid",
        "alignment": "Lawful Evil",
        "armorClass": 17,
        "hitPoints": 39,
        "maxHitPoints": 39,
        "speed": 30,
        "abilities": {
            "strength": 15,
            "dexterity": 14,
            "constitution": 14,
            "intelligence": 12,
            "wisdom": 10,
            "charisma": 13,
        },
        "savingThrows": [],
        "skills": {"Athletics": 4, "Intimidation": 3},
        "damageVulnerabilities": [],
        "damageResistances": [],
        "damageImmunities": [],
        "conditionImmunities": [],
        "senses": {"darkvision": 60, "passivePerception": 10},
        "languages": "Common, Goblin",
        "challengeRating": 3,
        "description": (
            "A disciplined hobgoblin officer values survival and command. If near "
            "death after his troops have fled or fallen, he prefers to yield rather "
            "than die pointlessly; otherwise he fights with tactical discipline."
        ),
        "specialAbilities": [],
        "actions": [
            {
                "name": "Longsword",
                "attackBonus": 4,
                "damageDice": "1d8",
                "damageBonus": 2,
                "damageType": "slashing",
                "attackType": "melee",
            },
            {
                "name": "Javelin",
                "attackBonus": 4,
                "damageDice": "1d6",
                "damageBonus": 2,
                "damageType": "piercing",
                "attackType": "ranged",
                "range": {"normal": 30, "long": 120},
            },
        ],
        # The fixed resolver declaration uses one legal SRD combination:
        # two Javelin attacks with their authored thrown range.
        "multiattack": [{"action": "Javelin", "count": 2}],
        "legendaryActions": [],
        "condition": "Alive",
        "_srd_attribution": "Portions derived from SRD 5.2.1, CC BY 4.0",
    }


def build_g5t_goblin_monster() -> Dict[str, Any]:
    """Return the goblin stat block shared by G5T squad members."""
    return {
        "name": "Goblin",
        "size": "Small",
        "type": "Humanoid",
        "alignment": "Neutral Evil",
        "armorClass": 15,
        "hitPoints": 7,
        "maxHitPoints": 7,
        "speed": 30,
        "abilities": {
            "strength": 8,
            "dexterity": 14,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 8,
            "charisma": 8,
        },
        "savingThrows": [],
        "skills": {"Stealth": 6},
        "damageVulnerabilities": [],
        "damageResistances": [],
        "damageImmunities": [],
        "conditionImmunities": [],
        "senses": {"darkvision": 60, "passivePerception": 9},
        "languages": "Common, Goblin",
        "challengeRating": 0.25,
        "description": (
            "Cowardly goblins prize survival. When bloodied and offered direct flee, "
            "they prefer escape over attacking or taking cover, using Nimble Escape "
            "while free. They surrender individually only when cornered or near death."
        ),
        "specialAbilities": [
            {
                "name": "Nimble Escape",
                "attackBonus": 0,
                "damageDice": "",
                "damageBonus": 0,
                "damageType": "",
            }
        ],
        "actions": [
            {
                "name": "Scimitar",
                "attackBonus": 4,
                "damageDice": "1d6",
                "damageBonus": 2,
                "damageType": "slashing",
            },
            {
                "name": "Shortbow",
                "attackBonus": 4,
                "damageDice": "1d6",
                "damageBonus": 2,
                "damageType": "piercing",
                "attackType": "ranged",
                "range": {"normal": 80, "long": 320},
            },
        ],
        "multiattack": [{"action": "Shortbow", "count": 1}],
        "legendaryActions": [],
        "condition": "Alive",
        "_srd_attribution": "Portions derived from SRD 5.2.1, CC BY 4.0",
    }


def build_g5t_training_pit_area() -> Dict[str, Any]:
    """Return isolated CA02 data with explicitly authored enemy cover."""
    return {
        "areaId": "CTR001",
        "areaName": "Capture Arena",
        "locations": [
            {
                "locationId": G5T_TRAINING_PIT_LOCATION_ID,
                "name": "Training Pit",
                "description": "A sunken sand pit ringed by shield racks.",
                "tacticalFeatures": [
                    {
                        "featureId": G5T_TRAINING_PIT_FEATURE_ID,
                        "name": "Scarred Shield Racks",
                        "kind": "cover",
                        "coverType": "half",
                        "usableBy": ["enemy"],
                    }
                ],
            }
        ],
    }


def _g5t_max_damage_per_declared_attack(monster: Dict[str, Any]) -> int:
    """Calculate a monster's worst one-attack damage from its authored actions."""
    actions = monster.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("G5T monster definition has no authored attacks")
    by_name = {
        str(action.get("name", "")).strip().casefold(): action
        for action in actions if isinstance(action, dict)
    }
    multiattack = monster.get("multiattack")
    if not isinstance(multiattack, list) or not multiattack:
        raise ValueError("G5T monster definition has no authored multiattack")
    maximum = 0
    for entry in multiattack:
        if not isinstance(entry, dict):
            raise ValueError("G5T multiattack entry is malformed")
        action_name = entry.get("action")
        count = entry.get("count")
        if (not isinstance(action_name, str) or
                not isinstance(count, int) or isinstance(count, bool) or count < 1):
            raise ValueError("G5T multiattack action/count is invalid")
        action = by_name.get(action_name.strip().casefold())
        if action is None:
            raise ValueError("G5T multiattack references an unknown action")
        dice = action.get("damageDice")
        match = re.fullmatch(r"\s*(\d+)d(\d+)\s*", dice) if isinstance(dice, str) else None
        bonus = action.get("damageBonus", 0)
        if (match is None or not isinstance(bonus, int) or isinstance(bonus, bool) or
                bonus < 0):
            raise ValueError("G5T authored attack damage is invalid")
        maximum += count * (int(match.group(1)) * int(match.group(2)) + bonus)
    return maximum


def build_g5t_worst_case_script_damage(party_size: int) -> int:
    """Sum max enemy damage over every enemy batch in the fixed G5T script."""
    batch_count = sum(
        row.get("unit_type") == "batch" and row.get("requires_combat_exit") is not True
        for row in build_g5t_script_steps(party_size)
    )
    if batch_count < 1:
        raise ValueError("G5T script must include at least one enemy batch")
    captain_damage = _g5t_max_damage_per_declared_attack(build_g5t_commander_monster())
    goblin_damage = _g5t_max_damage_per_declared_attack(build_g5t_goblin_monster())
    return batch_count * (captain_damage + len(G5T_GOBLIN_NAMES) * goblin_damage)


def build_g5t_worst_case_pc_hit_points(party_size: int) -> int:
    """Set sandbox PCs above all maximum damage in their complete scripted fight."""
    return build_g5t_worst_case_script_damage(party_size) + 1


def build_g5t_commander_fixture(party_size: int) -> Dict[str, Any]:
    """Return named G5T encounter and authored support data without seeding files."""
    if (
        isinstance(party_size, bool)
        or not isinstance(party_size, int)
        or party_size not in (1, 4)
    ):
        raise ValueError("G5T commander fixture party size must be 1 or 4")

    scenario_id = "g5t-commander-p%d" % party_size
    party_names = PC_NAMES[:party_size]
    creatures: List[Dict[str, Any]] = []
    for index, name in enumerate(party_names):
        creatures.append(
            {
                "name": name,
                "type": "player",
                "initiative": 20 - index * 2,
                "status": "alive",
                "conditions": [],
                "actions": {"actionType": "", "target": ""},
                "currentHitPoints": build_g5t_worst_case_pc_hit_points(party_size),
                "maxHitPoints": build_g5t_worst_case_pc_hit_points(party_size),
                "armorClass": 14,
            }
        )

    creatures.append(
        {
            "name": G5T_COMMANDER_NAME,
            "type": "enemy",
            "monsterType": G5T_COMMANDER_NAME,
            "initiative": 13,
            "status": "alive",
            "conditions": [],
            "actions": {"actionType": "attack", "target": party_names[0]},
            "currentHitPoints": 39,
            "maxHitPoints": 39,
            "armorClass": 17,
            "leader": True,
            "tactics": "commander",
        }
    )

    # Two independent squad members are required so one can flee while the
    # other uses cover and remains available for the later surrender check.
    goblin_count = 2
    for index in range(goblin_count):
        goblin_name = G5T_GOBLIN_NAMES[index]
        creatures.append(
            {
                "name": goblin_name,
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": 10 - index,
                "status": "alive",
                "conditions": [],
                "actions": {"actionType": "attack", "target": party_names[0]},
                "currentHitPoints": 7,
                "maxHitPoints": 7,
                "armorClass": 15,
            }
        )
        if index == 1:
            creatures[-1].update({
                "coverFeatureId": G5T_TRAINING_PIT_FEATURE_ID,
                "coverType": "half",
            })

    encounter = {
        "encounterId": scenario_id,
        "encounterSummary": (
            "A Hobgoblin Captain directs a goblin squad in the Capture Arena training pit."
        ),
        "creatures": creatures,
    }
    return {
        "scenario_id": scenario_id,
        "party_size": party_size,
        "encounter": encounter,
        "monster_definitions": {
            G5T_COMMANDER_NAME: build_g5t_commander_monster(),
            "Goblin": build_g5t_goblin_monster(),
        },
        "training_pit_area": build_g5t_training_pit_area(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider-free combat latency fixtures")
    parser.add_argument("--print-script", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--one-pc-self-check", action="store_true")
    args = parser.parse_args()
    if args.print_script:
        print_live_script()
    if args.self_check:
        fixture = build_mp_fixture()
        try:
            result = run_mp_fixture(fixture)
            print("PASS: MP fixture rounds=%d enemy_batches=%d PCs=%d" % (
                result["rounds_completed"], result["enemy_batches"], len(result["pc_names"])
            ))
        finally:
            fixture["tempdir"].cleanup()
    if args.one_pc_self_check:
        fixture = build_one_pc_fixture()
        try:
            result = run_one_pc_fixture(fixture)
            print("PASS: 1-PC party fixture rounds=%d PCs=%d" % (
                result["rounds_completed"], len(result["pc_names"])
            ))
        finally:
            fixture["tempdir"].cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
