# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free fixture for initiative-ordered ally/hostile commit tests."""

from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from core.combat.ally_controller import build_ally_directive_history_record
from core.combat.bootstrap import recover_pending_combat_turn
from core.combat.enemy_batch_orchestrator import (
    EnemyBatchOrchestrationDependencies,
    try_execute_deterministic_enemy_batch,
)
from core.combat.enemy_narration import NarrationResult
from core.combat.enemy_resolution import plan_enemy_batch
from core.combat.multi_pc.manager import MultiPCCombatManager
from core.combat.multi_pc.state import PCCombatState, PCStatus
from core.combat.multi_pc.sync import apply_opening_batch_marker
from core.combat.multi_pc.turn_queue import Combatant, CombatantType
from core.combat.turn import RoundTransitionDependencies
from core.combat.turn_commit import (
    COMBAT_ALLY_DIRECTIVE_HISTORY_KEY,
    COMBAT_TURN_COMMIT_MANIFEST_KEY,
)
from core.combat.enemy_narration import build_enemy_batch_template_narration


FIXED_TURN_ID = "11111111-2222-4333-8444-555555555555"
SCRATCH_ROOT = Path("tmp/router-rollout/g5a/ally-tests")


class _PathManager:
    def __init__(self, root: Path):
        self.root = root

    def get_character_path(self, name: str) -> str:
        slug = "_".join(name.lower().split())
        return str(self.root / "characters" / (slug + ".json"))

    def get_encounter_path_from_id(self, encounter_id: str) -> str:
        return str(self.root / "encounters" / ("encounter_" + encounter_id + ".json"))


class AllyBatchHarness:
    """Own per-test storage, provider stubs, and one complete combat input."""

    def __init__(self, party_size: int = 1, *, starts_with: str = "pcGroup"):
        if party_size not in (1, 4):
            raise ValueError("party_size must be one or four")
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = SCRATCH_ROOT / ("run-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.path_manager = _PathManager(self.root)
        self.history_path = str(self.root / "combat_conversation_history.json")
        self.encounter_id = "ally-batch-fixture"
        self.encounter_path = self.path_manager.get_encounter_path_from_id(
            self.encounter_id
        )
        self.party_names = ["Acheron", "Merisiel", "Kira", "Vitreol"][:party_size]
        self.characters: dict[str, dict[str, Any]] = {}
        self.writes: list[tuple[str, Any]] = []
        self.provider_calls: list[tuple[str, str, list[dict[str, Any]]]] = []
        self.events: list[str] = []
        self.published: list[tuple[str, str]] = []
        self.persisted_encounter: Optional[dict[str, Any]] = None
        self.persisted_history: Optional[list[Any]] = None
        self.fail_encounter_write = False
        self.starts_with = starts_with
        self.encounter, self.manager = self._build_scenario()
        self.persisted_encounter = copy.deepcopy(self.encounter)
        directive = build_ally_directive_history_record("Scout", "Protect the party")
        self.history = [
            {"role": "system", "content": "fixture"},
            directive,
            {
                "role": "user",
                "content": "Enemies turn.",
                "turn_id": FIXED_TURN_ID,
            },
        ]

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _build_scenario(self):
        pc_rows = []
        for index, name in enumerate(self.party_names):
            payload = {
                "name": name,
                "hitPoints": 20,
                "maxHitPoints": 20,
                "armorClass": 10,
                "status": "alive",
                "deathSaves": {"successes": 0, "failures": 0},
                "experience_points": 0,
            }
            self.characters[self.path_manager.get_character_path(name)] = payload
            pc_rows.append({
                "name": name,
                "type": "player",
                "initiative": 30 - index,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "armorClass": 10,
                "status": "alive",
                "conditions": [],
            })

        creatures = [
            {
                "name": "Goblin Alpha",
                "type": "enemy",
                "monsterType": "Goblin",
                "initiative": 15,
                "armorClass": 10,
                "currentHitPoints": 10,
                "maxHitPoints": 10,
                "status": "alive",
            },
            {
                "name": "Scout",
                "type": "npc",
                "initiative": 12,
                "armorClass": 12,
                "currentHitPoints": 18,
                "maxHitPoints": 18,
                "status": "alive",
                "attacksAndSpellcasting": [{
                    "name": "Longbow",
                    "attackBonus": 100,
                    "damageDice": "1d4",
                    "damageBonus": 0,
                    "damageType": "piercing",
                    "attackType": "ranged",
                }],
            },
            *pc_rows,
        ]
        encounter = {
            "encounterId": self.encounter_id,
            "id": self.encounter_id,
            "combat_round": 1,
            "initiativeMode": "two_group_phase1",
            "initiativeWinner": self.starts_with,
            "roundStartsWith": self.starts_with,
            "initiativeRolls": {"dmGroup": 17, "pcGroup": 12},
            "awaitingPcGroupRoll": False,
            "openingEnemyBatchPending": self.starts_with == "dmGroup",
            "combat_phase": "ENEMY_PHASE",
            "creatures": creatures,
        }

        manager = MultiPCCombatManager()
        manager.pc_phase_complete = True
        manager.current_round = 1
        manager.pc_phase_complete = True
        for index, name in enumerate(self.party_names):
            manager._state.pc_states[name] = PCCombatState(
                character_name=name,
                status=PCStatus.READY,
                current_hp=20,
                max_hp=20,
                ac=10,
            )
        if self.starts_with == "dmGroup":
            ordered = ["Goblin Alpha", "Scout", *self.party_names]
        else:
            ordered = [*self.party_names, "Scout", "Goblin Alpha"]
        index = {row["name"]: row for row in creatures}
        combatants = []
        for name in ordered:
            row = index[name]
            kind = {
                "enemy": CombatantType.ENEMY,
                "npc": CombatantType.NPC,
                "player": CombatantType.PC,
            }[row["type"]]
            combatants.append(Combatant(
                name=name,
                type=kind,
                initiative=row["initiative"],
                hp=row["currentHitPoints"],
                max_hp=row["maxHitPoints"],
                ac=row["armorClass"],
            ))
        manager._turns.turn_queue = combatants
        return encounter, manager

    def _read_json(self, path: str):
        if path == self.encounter_path:
            return copy.deepcopy(self.persisted_encounter)
        return copy.deepcopy(self.characters.get(path))

    def _write_json(self, path: str, payload: Any):
        if path == self.history_path:
            label = "history"
            self.persisted_history = copy.deepcopy(payload)
        elif path == self.encounter_path:
            label = "encounter"
            if self.fail_encounter_write:
                self.writes.append((label, copy.deepcopy(payload)))
                return False
            self.persisted_encounter = copy.deepcopy(payload)
        else:
            label = "character"
            if path not in self.characters:
                raise AssertionError("unexpected character path: " + path)
            self.characters[path] = copy.deepcopy(payload)
        self.writes.append((label, copy.deepcopy(payload)))
        return True

    def _llm_call(self, task, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        if "Choose one legal option for each scheduled allied NPC" in system:
            self.events.append("ally_plan")
            projection = json.loads(user)
            choices = []
            for actor in projection["scheduled_allies"]:
                attack = next(
                    option for option in actor["options"]
                    if option["kind"] == "attack"
                )
                cover = next(
                    (option for option in actor["options"]
                     if option["kind"] == "take_cover"),
                    None,
                )
                selected = (
                    cover
                    if cover is not None
                    and "take cover" in str(actor.get("directive", "")).casefold()
                    else attack
                )
                choices.append({
                    "actor": actor["actor"],
                    "option_ids": [selected["option_id"]],
                })
            response = json.dumps({"choices": choices})
        elif "completed allied-NPC combat batch" in system:
            self.events.append("ally_narration")
            ledger = json.loads(user)["authoritative_ledger"]
            lines = []
            for entry in ledger["entries"]:
                actor = entry["actor"]["name"]
                target = entry["target"]["name"]
                if entry["outcome"] == "hit":
                    line = f"{actor} hits {target}"
                    if entry["damage_total"] > 0:
                        line += f", dealing {entry['damage_total']} damage"
                    line += "."
                    if entry["target_status_after"] in {
                        "dead", "defeated", "unconscious",
                    }:
                        line += f" {target} is defeated."
                else:
                    line = f"{actor} misses {target}."
                lines.append(line)
            response = " ".join(lines) or "The allies hold their ground."
        else:
            self.events.append("hostile_narration")
            response = "The hostile batch resolves."
        self.provider_calls.append((task, system, copy.deepcopy(messages)))
        return response

    def _plan(self, *args, **kwargs):
        self.events.append("hostile_plan")
        return plan_enemy_batch(*args, **kwargs)

    def _transition_dependencies(self):
        return RoundTransitionDependencies(
            apply_opening_batch_marker=apply_opening_batch_marker,
            sync_available=True,
            save_json=lambda _path, _payload: True,
            compress_old_rounds=lambda history, _round, keep_recent_rounds=1: history,
            log_debug=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
            log_warning=lambda *_args, **_kwargs: None,
            bind_history=lambda _history: None,
        )

    def dependencies(self):
        def host_narrate(ledger, _scene, _descriptions, llm_call, receipt_observer=None,
                         tactical_plan_intent=None):
            text = llm_call("combat_main", [
                {"role": "system", "content": "hostile narration"},
                {"role": "user", "content": "fixture"},
            ], json_output=False, observer=receipt_observer)
            if not isinstance(text, str):
                text = ""
            return NarrationResult(
                text=build_enemy_batch_template_narration(ledger),
                source="template",
            )

        def publish(text, *, applied_id):
            self.published.append((text, applied_id))

        return EnemyBatchOrchestrationDependencies(
            read_json=self._read_json,
            write_json=self._write_json,
            round_transition_dependencies=self._transition_dependencies(),
            llm_call=self._llm_call,
            receipt_observer_factory=lambda **kwargs: kwargs,
            publish_narration=publish,
            usage_tracking_available=False,
            combat_main_model="provider-free-ally-test",
            plan=self._plan,
            narrate=host_narrate,
            validate_character=lambda _name, _payload: True,
        )

    def execute(self, *, dependencies=None, scene_context=None):
        if scene_context is None:
            scene_context = {
                "active_encounter_id": self.encounter_id,
                "combat_in_progress": True,
                "npc_profiles": {},
                "location": {"name": "Practice field", "tacticalFeatures": []},
            }
        return try_execute_deterministic_enemy_batch(
            self.encounter,
            self.history,
            "Enemies turn.",
            initial_conversation_length=len(self.history),
            encounter_id=self.encounter_id,
            conversation_history_file=self.history_path,
            path_manager=self.path_manager,
            multi_pc_manager=self.manager,
            monster_definitions={
                "Goblin": {
                    "description": "A goblin with a scimitar.",
                    "actions": [{
                        "name": "Scimitar",
                        "attackBonus": 100,
                        "damageDice": "1d4",
                        "damageBonus": 1,
                        "damageType": "slashing",
                    }],
                },
            },
            scene_context=scene_context,
            dependencies=dependencies or self.dependencies(),
            party_tracker_data={
                "partyMembers": [{"name": name} for name in self.party_names],
                "partyNPCs": [{"name": "Scout"}],
            },
        )

    def recovery_dependencies(self):
        return SimpleNamespace(
            safe_json_load=self._read_json,
            write_json=self._write_json,
            validate_character=lambda _name, _payload: True,
            publish_narration=lambda text, *, applied_id: self.published.append(
                (text, applied_id)
            ),
        )

    def recover(self, history=None):
        if history is None:
            history = self.persisted_history
        if not isinstance(history, list):
            raise AssertionError("missing persisted history")
        return recover_pending_combat_turn(
            encounter_id=self.encounter_id,
            encounter_path=self.encounter_path,
            history=history,
            path_manager=self.path_manager,
            encounter_data=self.persisted_encounter,
            party_tracker_data={},
            session=None,
            multi_pc_manager=None,
            dependencies=self.recovery_dependencies(),
        )

    def ally_directive_record(self):
        return next(
            message for message in self.persisted_history or []
            if isinstance(message, dict)
            and COMBAT_ALLY_DIRECTIVE_HISTORY_KEY in message
        )

    def commit_manifest(self):
        record = next(
            message for message in self.persisted_history or []
            if isinstance(message, dict)
            and message.get("turn_id") == FIXED_TURN_ID
        )
        return record[COMBAT_TURN_COMMIT_MANIFEST_KEY]
