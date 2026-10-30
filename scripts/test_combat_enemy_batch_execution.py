# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for deterministic enemy batch application and writes."""

import copy
import shutil
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import model_config
from core.combat.bootstrap import recover_pending_combat_turn
from core.combat.enemy_batch_orchestrator import (
    EnemyBatchExecution,
    EnemyBatchFallback,
    EnemyBatchOrchestrationDependencies,
    _batch_id,
    try_execute_deterministic_enemy_batch,
)
from core.combat.enemy_batch_apply import (
    EnemyBatchApplyError,
    apply_enemy_batch,
    is_deterministic_enemy_resolution_enabled,
)
from core.combat.enemy_narration import (
    NarrationResult,
    build_enemy_batch_template_narration,
)
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyAttackLedgerEntry,
    EnemyResolutionLedger,
)
from core.combat.turn_commit import (
    COMBAT_TURN_COMMIT_MANIFEST_KEY,
    compute_applied_id,
    read_character_applied_id,
    validate_combat_turn_commit_manifest,
)
from core.combat.multi_pc.manager import MultiPCCombatManager
from core.combat.multi_pc.state import PCCombatState, PCStatus
from core.combat.multi_pc.turn_queue import Combatant, CombatantType
from core.combat.multi_pc.sync import apply_opening_batch_marker
from core.combat.turn import (
    RoundTransitionDependencies,
)


SCRATCH_ROOT = Path("tmp/router-rollout/g5r")
FIXED_TURN_ID = "11111111-2222-4333-8444-555555555555"


def _ledger(two_changed_pcs=False):
    entries = [
        EnemyAttackLedgerEntry(
            actor=CombatantIdentity("Goblin", "enemy"),
            action_name="Scimitar",
            target=CombatantIdentity("Acheron", "player"),
            d20=13,
            attack_total=17,
            armor_class=15,
            hit=True,
            critical=False,
            damage_dice_rolls=(3,),
            damage_total=4,
            damage_type="slashing",
            target_hp_before=20,
            target_hp_after=16,
            target_status_after="alive",
        ),
        EnemyAttackLedgerEntry(
            actor=CombatantIdentity("Goblin", "enemy"),
            action_name="Scimitar",
            target=CombatantIdentity("Merisiel", "player"),
            d20=1,
            attack_total=5,
            armor_class=16,
            hit=False,
            critical=False,
            damage_dice_rolls=(),
            damage_total=0,
            damage_type="slashing",
            target_hp_before=18,
            target_hp_after=18,
            target_status_after="alive",
        ),
    ]
    if two_changed_pcs:
        entries[1] = EnemyAttackLedgerEntry(
            actor=CombatantIdentity("Goblin", "enemy"),
            action_name="Scimitar",
            target=CombatantIdentity("Merisiel", "player"),
            d20=13,
            attack_total=17,
            armor_class=16,
            hit=True,
            critical=False,
            damage_dice_rolls=(2,),
            damage_total=3,
            damage_type="slashing",
            target_hp_before=18,
            target_hp_after=15,
            target_status_after="alive",
        )
    return EnemyResolutionLedger(
        encounter_id="fixture-encounter",
        round_number=1,
        batch_id="fixture-batch-1",
        batch_kind="enemy_phase",
        seed=123,
        entries=tuple(entries),
        bloodied=(),
    )


class _PathManager:
    def __init__(self, root):
        self.root = root

    def get_character_path(self, name):
        slug = "_".join(name.lower().split())
        return str(self.root / "characters" / (slug + ".json"))

    def get_encounter_path_from_id(self, encounter_id):
        return str(self.root / "encounters" / ("encounter_" + encounter_id + ".json"))


class _ManagerSpy:
    def __init__(self):
        self.hp_updates = []

    def update_pc_hp(self, name, hp):
        self.hp_updates.append((name, hp))


class CombatEnemyBatchApplyTests(unittest.TestCase):
    def setUp(self):
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.work_dir = SCRATCH_ROOT / ("apply-test-" + uuid.uuid4().hex)
        self.work_dir.mkdir()
        self.path_manager = _PathManager(self.work_dir)
        self.ledger = _ledger()
        self.history_path = str(self.work_dir / "combat_conversation_history.json")
        self.history = [{"role": "system", "content": "keep"}]
        self.encounter = {
            "encounterId": "fixture-encounter",
            "combat_round": 1,
            "combat_phase": "PC_PHASE",
            "openingEnemyBatchPending": False,
            "creatures": [
                {"name": "Goblin", "type": "enemy", "currentHitPoints": 7, "status": "alive"},
                {"name": "Acheron", "type": "player", "currentHitPoints": 20, "status": "alive"},
                {"name": "Merisiel", "type": "player", "currentHitPoints": 18, "status": "alive"},
                {"name": "Kira", "type": "player", "currentHitPoints": 17, "status": "alive"},
            ],
        }
        self.encounter_path = str(
            self.path_manager.get_encounter_path_from_id("fixture-encounter")
        )
        self.persisted_encounter = copy.deepcopy(self.encounter)
        self.character_data = {
            self.path_manager.get_character_path("Acheron"):
                {"name": "Acheron", "hitPoints": 20, "status": "alive", "inventory": ["torch"]},
            self.path_manager.get_character_path("Merisiel"):
                {"name": "Merisiel", "hitPoints": 18, "status": "alive", "inventory": ["rope"]},
        }
        self.writes = []

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def _dependencies(self, fail_label=None):
        path_labels = {self.history_path: "history"}
        path_labels[self.encounter_path] = "encounter"
        for name in ("Acheron", "Merisiel", "Kira"):
            path_labels[self.path_manager.get_character_path(name)] = "pc:" + name

        def read_json(path):
            if path == self.encounter_path:
                return copy.deepcopy(self.persisted_encounter)
            if path not in self.character_data:
                return None
            return copy.deepcopy(self.character_data[path])

        def write_json(path, payload):
            label = path_labels.get(path)
            if label is None:
                raise AssertionError("unexpected persistence path")
            self.assertTrue(path.startswith(str(self.work_dir)))
            self.writes.append((label, copy.deepcopy(payload)))
            if label == fail_label:
                return False
            if label.startswith("pc:"):
                self.character_data[path] = copy.deepcopy(payload)
            elif label == "encounter":
                self.persisted_encounter = copy.deepcopy(payload)
            return True

        return read_json, write_json

    def _apply(
        self,
        *,
        ledger=None,
        manager=None,
        cleaners=(None, None),
        fail_label=None,
        party_tracker_data=None,
        calculate_xp_for_encounter=None,
        check_all_monsters_defeated=None,
    ):
        read_json, write_json = self._dependencies(fail_label=fail_label)
        return apply_enemy_batch(
            ledger or self.ledger,
            NarrationResult("Goblin strikes Acheron.", "template", "outcome_mismatch"),
            user_input_text="Enemies turn.",
            turn_id=FIXED_TURN_ID,
            conversation_history=self.history,
            conversation_history_file=self.history_path,
            encounter_projection=self.encounter,
            path_manager=self.path_manager,
            multi_pc_manager=manager,
            clean_old_dm_notes=cleaners[0],
            clean_combat_state_blocks=cleaners[1],
            read_json=read_json,
            write_json=write_json,
            party_tracker_data=party_tracker_data,
            calculate_xp_for_encounter=calculate_xp_for_encounter,
            check_all_monsters_defeated=check_all_monsters_defeated,
            validate_character=lambda _name, _payload: True,
        )

    def test_writes_history_then_changed_pcs_then_one_final_encounter(self):
        manager = _ManagerSpy()
        result = self._apply(manager=manager)

        self.assertEqual([label for label, _ in self.writes], [
            "history", "pc:Acheron", "encounter",
        ])
        self.assertEqual(result.write_count, 2 + 1)
        self.assertEqual(result.changed_pc_names, ("Acheron",))
        history_payload = self.writes[0][1]
        accepted_input, narration_message = history_payload[-2:]
        self.assertEqual(
            {
                key: value for key, value in accepted_input.items()
                if key != COMBAT_TURN_COMMIT_MANIFEST_KEY
            },
            {"role": "user", "content": "Enemies turn.", "turn_id": FIXED_TURN_ID},
        )
        manifest = validate_combat_turn_commit_manifest(
            accepted_input[COMBAT_TURN_COMMIT_MANIFEST_KEY]
        )
        self.assertEqual(manifest["path"], "enemy_batch")
        self.assertEqual(manifest["turn_id"], FIXED_TURN_ID)
        self.assertEqual(
            manifest["applied_id"], compute_applied_id("fixture-encounter", FIXED_TURN_ID)
        )
        self.assertEqual(
            [row["character_name"] for row in manifest["character_effects"]],
            ["Acheron"],
        )
        self.assertEqual(
            manifest["character_effects"][0]["payload"]["last_combat_applied_id"],
            manifest["applied_id"],
        )
        self.assertEqual(manifest["staged_rewards"], [])
        self.assertEqual(manifest["receipt"]["combat_round"], 1)
        self.assertEqual(manifest["encounter_projection"]["combat_phase"], "PC_PHASE")
        self.assertEqual(
            manifest["success_narration"],
            {
                "text": "Goblin strikes Acheron.",
                "payload": "Dungeon Master: Goblin strikes Acheron.",
            },
        )
        self.assertEqual(
            narration_message,
            {"role": "assistant", "content": "Goblin strikes Acheron."},
        )
        self.assertEqual(sum(label == "history" for label, _ in self.writes), 1)
        pc_payload = self.writes[1][1]
        self.assertEqual((pc_payload["hitPoints"], pc_payload["status"]), (16, "alive"))
        self.assertEqual(pc_payload["inventory"], ["torch"])
        encounter_payload = self.writes[2][1]
        pc_row = next(row for row in encounter_payload["creatures"] if row["name"] == "Acheron")
        self.assertEqual((pc_row["currentHitPoints"], pc_row["status"]), (16, "alive"))
        self.assertEqual(encounter_payload["combat_phase"], "PC_PHASE")
        self.assertFalse(encounter_payload["openingEnemyBatchPending"])
        self.assertEqual(manager.hp_updates, [])
        self.assertEqual(
            result.applied_id,
            encounter_payload["turn_receipts"][0]["applied_id"],
        )
        self.assertEqual(
            self.character_data[self.path_manager.get_character_path("Acheron")][
                "last_combat_applied_id"
            ],
            encounter_payload["turn_receipts"][0]["applied_id"],
        )

    def test_two_changed_pcs_are_coalesced_and_write_count_is_two_plus_n(self):
        self.ledger = _ledger(two_changed_pcs=True)
        result = self._apply()
        self.assertEqual([label for label, _ in self.writes], [
            "history", "pc:Acheron", "pc:Merisiel", "encounter",
        ])
        self.assertEqual(result.write_count, 4)
        self.assertEqual(result.changed_pc_names, ("Acheron", "Merisiel"))

    def test_status_only_change_writes_pc_projection_once(self):
        entries = list(self.ledger.entries)
        entries[0] = replace(
            entries[0],
            d20=1,
            attack_total=5,
            hit=False,
            damage_dice_rolls=(),
            damage_total=0,
            target_hp_after=20,
            target_status_after="unconscious",
        )
        self.ledger = replace(self.ledger, entries=tuple(entries))

        result = self._apply()

        self.assertEqual([label for label, _ in self.writes], [
            "history", "pc:Acheron", "encounter",
        ])
        pc_payload = self.writes[1][1]
        self.assertEqual((pc_payload["hitPoints"], pc_payload["status"]), (20, "unconscious"))
        self.assertEqual(result.changed_pc_names, ("Acheron",))

    def test_history_cleaners_run_in_memory_before_single_history_write(self):
        calls = []

        def clean_notes(history):
            calls.append("notes")
            return [item for item in history if item.get("content") != "remove-note"]

        def clean_blocks(history):
            calls.append("blocks")
            return history

        self.history.append({"role": "system", "content": "remove-note"})
        self._apply(cleaners=(clean_notes, clean_blocks))
        self.assertEqual(calls, ["notes", "blocks"])
        self.assertEqual([label for label, _ in self.writes].count("history"), 1)
        self.assertNotIn("remove-note", [item.get("content") for item in self.writes[0][1]])

    def test_history_write_failure_stops_before_pc_and_encounter_writes(self):
        with self.assertRaises(EnemyBatchApplyError) as raised:
            self._apply(fail_label="history")
        self.assertEqual(raised.exception.stage, "history")
        self.assertEqual([label for label, _ in self.writes], ["history"])
        self.assertEqual(self.history, [{"role": "system", "content": "keep"}])

    def test_pc_write_failure_stops_before_later_encounter_write(self):
        with self.assertRaises(EnemyBatchApplyError) as raised:
            self._apply(fail_label="pc:Acheron")
        self.assertEqual(raised.exception.stage, "pc_write")
        self.assertEqual([label for label, _ in self.writes], [
            "history", "pc:Acheron",
        ])

    def test_encounter_write_failure_occurs_after_history_and_pc_writes(self):
        with self.assertRaises(EnemyBatchApplyError) as raised:
            self._apply(fail_label="encounter")
        self.assertEqual(raised.exception.stage, "encounter")
        self.assertEqual([label for label, _ in self.writes], [
            "history", "pc:Acheron", "encounter",
        ])

    def test_terminal_batch_reward_is_committed_once_across_partial_and_full_replay(self):
        self.encounter["creatures"][0]["currentHitPoints"] = 0
        self.encounter["creatures"][0]["status"] = "defeated"
        party_tracker = {
            "partyMembers": ["Acheron", "Merisiel"],
            "partyNPCs": [],
        }
        callbacks = {
            "party_tracker_data": party_tracker,
            "calculate_xp_for_encounter": lambda _encounter, _party: (
                "the party gains 25 XP each", 25
            ),
            "check_all_monsters_defeated": lambda projection: all(
                row.get("status") in {"dead", "defeated"}
                for row in projection["creatures"]
                if row.get("type") == "enemy"
            ),
        }

        with self.assertRaises(EnemyBatchApplyError) as raised:
            self._apply(fail_label="pc:Merisiel", **callbacks)
        self.assertEqual(raised.exception.stage, "pc_write")
        self.assertEqual(
            self.character_data[self.path_manager.get_character_path("Acheron")][
                "experience_points"
            ],
            25,
        )
        self.assertEqual(
            self.character_data[self.path_manager.get_character_path("Merisiel")].get(
                "experience_points", 0
            ),
            0,
        )
        applied_id = compute_applied_id("fixture-encounter", FIXED_TURN_ID)
        self.assertEqual(
            read_character_applied_id(
                self.character_data[self.path_manager.get_character_path("Acheron")]
            ),
            applied_id,
        )
        accepted_record = next(
            message for message in self.history
            if message.get("role") == "user"
            and message.get("turn_id") == FIXED_TURN_ID
        )
        history_manifest = accepted_record[COMBAT_TURN_COMMIT_MANIFEST_KEY]
        self.assertEqual(
            [row["character_name"] for row in history_manifest["character_effects"]],
            ["Acheron", "Merisiel"],
        )

        self.writes.clear()
        read_json, write_json = self._dependencies()
        publications = []
        recovery_dependencies = SimpleNamespace(
            safe_json_load=read_json,
            write_json=write_json,
            validate_character=lambda _name, _payload: True,
            publish_narration=lambda text, *, applied_id: publications.append(
                (text, applied_id)
            ),
        )
        recovered = recover_pending_combat_turn(
            encounter_id="fixture-encounter",
            encounter_path=self.encounter_path,
            history=self.history,
            path_manager=self.path_manager,
            encounter_data=self.persisted_encounter,
            party_tracker_data={},
            session=None,
            multi_pc_manager=None,
            dependencies=recovery_dependencies,
        )
        self.assertTrue(recovered.recovered)
        self.assertEqual(recovered.applied_id, applied_id)
        self.assertEqual([label for label, _ in self.writes], ["pc:Merisiel", "encounter"])
        self.assertEqual(publications, [("Goblin strikes Acheron.", applied_id)])
        for name in ("Acheron", "Merisiel"):
            self.assertEqual(
                self.character_data[self.path_manager.get_character_path(name)][
                    "experience_points"
                ],
                25,
            )
            self.assertEqual(
                read_character_applied_id(
                    self.character_data[self.path_manager.get_character_path(name)]
                ),
                applied_id,
            )
        self.assertEqual(
            recovered.encounter_data["turn_receipts"][0]["turn_id"], FIXED_TURN_ID
        )

        self.writes.clear()
        no_op_recovery = recover_pending_combat_turn(
            encounter_id="fixture-encounter",
            encounter_path=self.encounter_path,
            history=self.history,
            path_manager=self.path_manager,
            encounter_data=recovered.encounter_data,
            party_tracker_data={},
            session=None,
            multi_pc_manager=None,
            dependencies=recovery_dependencies,
        )
        self.assertFalse(no_op_recovery.recovered)
        self.assertEqual(self.writes, [])
        self.assertEqual(publications, [("Goblin strikes Acheron.", applied_id)])

        replay = self._apply(**callbacks)
        self.assertEqual(replay.write_count, 0)
        self.assertEqual(self.writes, [])

    def test_shipped_flag_and_accessor_are_off(self):
        self.assertIs(model_config.DETERMINISTIC_ENEMY_RESOLUTION_ENABLED, False)
        self.assertFalse(is_deterministic_enemy_resolution_enabled())
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", False):
            self.assertFalse(is_deterministic_enemy_resolution_enabled())

    def test_preflight_read_failure_performs_no_writes(self):
        read_json, write_json = self._dependencies()

        def fail_read(_path):
            raise OSError("local fixture read failure")

        with self.assertRaises(EnemyBatchApplyError) as raised:
            apply_enemy_batch(
                self.ledger,
                NarrationResult("Goblin strikes Acheron.", "template"),
                user_input_text="Enemies turn.",
                turn_id=FIXED_TURN_ID,
                conversation_history=self.history,
                conversation_history_file=self.history_path,
                encounter_projection=self.encounter,
                path_manager=self.path_manager,
                read_json=fail_read,
                write_json=write_json,
                validate_character=lambda _name, _payload: True,
            )
        self.assertEqual(raised.exception.stage, "pc_read")
        self.assertEqual(self.writes, [])


class CombatEnemyBatchOrchestrationTests(unittest.TestCase):
    def setUp(self):
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.work_dir = SCRATCH_ROOT / ("orchestrator-test-" + uuid.uuid4().hex)
        self.work_dir.mkdir()
        self.path_manager = _PathManager(self.work_dir)
        self.writes = []
        self.characters = {}
        self.history_path = str(self.work_dir / "combat_conversation_history.json")
        self.encounter_path = str(
            self.path_manager.get_encounter_path_from_id("batch-fixture")
        )
        self.persisted_encounter = None
        self.legacy_lifecycle_writes = []
        self.planned = None
        self.llm_tasks = []
        self.published = []
        self.observer_requests = []
        self.published_applied_ids = []

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def _scenario(self, party_size=1, *, opening=False, unsupported_npc=False):
        party_names = ["Acheron", "Merisiel", "Kira", "Vitreol"][:party_size]
        encounter = {
            "id": "batch-fixture",
            "encounterId": "batch-fixture",
            "combat_round": 1,
            "initiativeMode": "two_group_phase1",
            "initiativeRolls": {"dmGroup": 11, "pcGroup": 17},
            "initiativeWinner": "pcGroup",
            "roundStartsWith": "dmGroup" if opening else "pcGroup",
            "awaitingPcGroupRoll": False,
            "openingEnemyBatchPending": opening,
            "creatures": [
                {
                    "name": "Goblin Alpha",
                    "type": "enemy",
                    "monsterType": "Goblin",
                    "initiative": 10,
                    "armorClass": 12,
                    "currentHitPoints": 20,
                    "maxHitPoints": 20,
                    "status": "alive",
                },
            ],
        }
        manager = MultiPCCombatManager()
        manager.current_round = 1
        manager.pc_phase_complete = True
        queue = []
        for index, name in enumerate(party_names):
            data = {
                "name": name,
                "hitPoints": 20,
                "maxHitPoints": 20,
                "armorClass": 14 + index,
                "status": "alive",
                "deathSaves": {"successes": 0, "failures": 0},
                "condition_affected": [],
            }
            self.characters[self.path_manager.get_character_path(name)] = data
            manager._state.pc_states[name] = PCCombatState(
                character_name=name,
                status=PCStatus.READY,
                current_hp=20,
                max_hp=20,
                ac=14 + index,
            )
            encounter["creatures"].append({
                "name": name,
                "type": "player",
                "initiative": 20 - index,
                "currentHitPoints": 20,
                "maxHitPoints": 20,
                "armorClass": 14 + index,
                "status": "alive",
                "conditions": [],
            })
            queue.append(Combatant(
                name=name,
                type=CombatantType.PC,
                initiative=20 - index,
                hp=20,
                max_hp=20,
                ac=14 + index,
            ))

        if unsupported_npc:
            encounter["creatures"].append({
                "name": "Scout Kira",
                "type": "npc",
                "initiative": 8,
                "currentHitPoints": 12,
                "maxHitPoints": 12,
                "armorClass": 13,
                "status": "alive",
            })
            queue.append(Combatant(
                name="Scout Kira",
                type=CombatantType.NPC,
                initiative=8,
                hp=12,
                max_hp=12,
                ac=13,
            ))
        queue.append(Combatant(
            name="Goblin Alpha",
            type=CombatantType.ENEMY,
            initiative=10,
            hp=20,
            max_hp=20,
            ac=12,
        ))
        manager._turns.turn_queue = queue
        self.history = [
            {"role": "system", "content": "authoritative combat context"},
            {"role": "user", "content": "Enemies turn.", "turn_id": FIXED_TURN_ID},
        ]
        self.encounter = encounter
        self.persisted_encounter = copy.deepcopy(encounter)
        self.manager = manager
        self.party_names = party_names
        return encounter, manager

    def _dependencies(self, *, plan=None, fail_label=None):
        def read_json(path):
            if path == self.encounter_path:
                return copy.deepcopy(self.persisted_encounter)
            return copy.deepcopy(self.characters.get(path))

        def write_json(path, payload):
            if path == self.history_path:
                label = "history"
            elif path == self.encounter_path:
                label = "encounter"
            else:
                label = next((
                    "pc:" + name for name in self.party_names
                    if path == self.path_manager.get_character_path(name)
                ), None)
            if label is None:
                raise AssertionError("unexpected persistence path")
            self.writes.append((label, copy.deepcopy(payload)))
            if label == fail_label:
                return False
            if label.startswith("pc:"):
                self.characters[path] = copy.deepcopy(payload)
            elif label == "encounter":
                self.persisted_encounter = copy.deepcopy(payload)
            return True

        def plan_batch(*args, **kwargs):
            result = (plan or _actual_plan)(*args, **kwargs)
            self.planned = result
            return result

        def llm_call(task, messages, **kwargs):
            self.llm_tasks.append(task)
            if isinstance(self.planned, EnemyResolutionLedger):
                return build_enemy_batch_template_narration(self.planned)
            raise AssertionError("narration should not run without a ledger")

        def observer_factory(**kwargs):
            self.observer_requests.append(kwargs)
            return "observer"

        transition_dependencies = RoundTransitionDependencies(
            apply_opening_batch_marker=apply_opening_batch_marker,
            sync_available=True,
            save_json=lambda path, payload: self.legacy_lifecycle_writes.append(
                (path, copy.deepcopy(payload))
            ) or True,
            compress_old_rounds=lambda history, _round, keep_recent_rounds=1: history,
            log_debug=lambda *_args, **_kwargs: None,
            log_info=lambda *_args, **_kwargs: None,
            log_warning=lambda *_args, **_kwargs: None,
            bind_history=lambda _history: None,
        )

        def publish_narration(text, *, applied_id):
            self.published.append("Dungeon Master: " + text)
            self.published_applied_ids.append(applied_id)

        return EnemyBatchOrchestrationDependencies(
            read_json=read_json,
            write_json=write_json,
            round_transition_dependencies=transition_dependencies,
            llm_call=llm_call,
            receipt_observer_factory=observer_factory,
            publish_narration=publish_narration,
            usage_tracking_available=False,
            combat_main_model="provider-free-test-model",
            plan=plan_batch,
            validate_character=lambda _name, _payload: True,
        )

    def _execute(self, dependencies, *, encounter=None, manager=None, logical_turn=None):
        return try_execute_deterministic_enemy_batch(
            encounter or self.encounter,
            self.history,
            "Enemies turn.",
            initial_conversation_length=len(self.history),
            encounter_id="batch-fixture",
            conversation_history_file=self.history_path,
            path_manager=self.path_manager,
            multi_pc_manager=manager or self.manager,
            monster_definitions={
                "Goblin": {
                    "description": "A nimble green humanoid.",
                    "actions": [{
                        "name": "Scimitar",
                        "attackBonus": 4,
                        "damageDice": "1d6",
                        "damageBonus": 2,
                        "damageType": "slashing",
                    }],
                },
            },
            scene_context={"location": {"name": "Arena"}, "round": 1},
            dependencies=dependencies,
            logical_turn=logical_turn,
            party_tracker_data={
                "partyMembers": list(self.party_names),
                "partyNPCs": [],
            },
        )

    def test_batch_id_is_sanitized_and_bounded_to_64_characters(self):
        batch_id = _batch_id("encounter / " + ("x" * 100), 12)

        self.assertLessEqual(len(batch_id), 64)
        self.assertRegex(batch_id, r"^[A-Za-z0-9_-]+$")
        self.assertTrue(batch_id.endswith("-r12-enemy_phase"))

    def test_flag_off_skips_planning_and_preserves_legacy_dispatch(self):
        self._scenario()
        planner = mock.Mock()
        dependencies = self._dependencies(plan=planner)
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", False):
            result = self._execute(dependencies)

        self.assertIsNone(result)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.llm_tasks, [])
        planner.assert_not_called()

    def test_supported_pc_phase_end_for_one_and_four_pc_parties(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True):
            for party_size in (1, 4):
                with self.subTest(party_size=party_size):
                    self.writes.clear()
                    self.characters.clear()
                    self.llm_tasks.clear()
                    self.published.clear()
                    self.published_applied_ids.clear()
                    self.observer_requests.clear()
                    self.legacy_lifecycle_writes.clear()
                    self._scenario(party_size)
                    initial_initiative = copy.deepcopy(self.encounter["initiativeRolls"])
                    initial_winner = self.encounter["initiativeWinner"]
                    initial_queue = [
                        (combatant.name, combatant.type.value, combatant.initiative)
                        for combatant in self.manager._turns.turn_queue
                    ]

                    result = self._execute(self._dependencies())

                    self.assertIsInstance(result, EnemyBatchExecution)
                    self.assertEqual(result.lifecycle_case, "pc_phase_end")
                    self.assertEqual(self.llm_tasks, ["combat_main"])
                    self.assertEqual(len(self.published), 1)
                    self.assertTrue(self.published[0].startswith("Dungeon Master: "))
                    self.assertEqual(
                        self.published_applied_ids,
                        [result.application.applied_id],
                    )
                    self.assertEqual(len(self.observer_requests), 1)
                    self.assertEqual(self.writes[0][0], "history")
                    self.assertEqual(self.writes[-1][0], "encounter")
                    self.assertEqual(
                        [label for label, _payload in self.writes].count("history"), 1
                    )
                    self.assertEqual(
                        [label for label, _payload in self.writes if label.startswith("pc:")],
                        ["pc:" + name for name in result.application.changed_pc_names],
                    )
                    self.assertEqual(result.encounter_data["combat_round"], 2)
                    self.assertEqual(result.encounter_data["current_round"], 2)
                    self.assertFalse(result.encounter_data["openingEnemyBatchPending"])
                    self.assertEqual(result.encounter_data["initiativeRolls"], initial_initiative)
                    self.assertEqual(result.encounter_data["initiativeWinner"], initial_winner)
                    self.assertFalse(result.encounter_data["awaitingPcGroupRoll"])
                    self.assertEqual(self.manager.current_round, 2)
                    self.assertEqual(self.manager.combat_phase, "PC_PHASE")
                    self.assertEqual(
                        [
                            (combatant.name, combatant.type.value, combatant.initiative)
                            for combatant in self.manager._turns.turn_queue
                        ],
                        initial_queue,
                    )
                    self.assertEqual(self.legacy_lifecycle_writes, [])

    def test_partial_character_commit_replans_from_durable_encounter_hp(self):
        self._scenario()
        observed_planning_hp = []

        def plan_from_current_pc_state(_encounter, party_states, *_args, **kwargs):
            hp_before = party_states["Acheron"]["hitPoints"]
            observed_planning_hp.append(hp_before)
            entry = replace(
                _ledger().entries[0],
                actor=CombatantIdentity("Goblin Alpha", "enemy"),
                target_hp_before=hp_before,
                target_hp_after=hp_before - 4,
            )
            return replace(
                _ledger(),
                encounter_id="batch-fixture",
                batch_id=kwargs["batch_id"],
                entries=(entry,),
            )

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True):
            with self.assertRaises(EnemyBatchApplyError) as raised:
                self._execute(
                    self._dependencies(plan=plan_from_current_pc_state, fail_label="encounter")
                )
            self.assertEqual(raised.exception.stage, "encounter")
            self.assertEqual(self.published, [])

            acheron_path = self.path_manager.get_character_path("Acheron")
            partially_committed_character = copy.deepcopy(self.characters[acheron_path])
            self.assertEqual(partially_committed_character["hitPoints"], 16)
            self.assertEqual(
                read_character_applied_id(partially_committed_character),
                compute_applied_id("batch-fixture", FIXED_TURN_ID),
            )

            # Model process restart from the uncommitted encounter snapshot and
            # the same accepted input while retaining the character-file write.
            self._scenario()
            self.characters[acheron_path] = partially_committed_character
            self.writes.clear()
            result = self._execute(self._dependencies(plan=plan_from_current_pc_state))

        self.assertIsInstance(result, EnemyBatchExecution)
        self.assertEqual(observed_planning_hp, [20, 20])
        self.assertEqual(result.ledger.entries[0].target_hp_before, 20)
        self.assertEqual(result.ledger.entries[0].target_hp_after, 16)
        self.assertEqual(self.characters[acheron_path]["hitPoints"], 16)
        self.assertEqual([label for label, _ in self.writes], ["history", "encounter"])
        self.assertEqual(len(result.encounter_data["turn_receipts"]), 1)

    def test_post_commit_sync_failure_does_not_publish_success(self):
        self._scenario()
        with mock.patch.object(
            model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True
        ), mock.patch.object(
            self.manager,
            "sync_committed_turn_state",
            side_effect=RuntimeError("sync unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "sync unavailable"):
                self._execute(self._dependencies())

        self.assertEqual(self.writes[-1][0], "encounter")
        self.assertEqual(len(self.writes[-1][1]["turn_receipts"]), 1)
        self.assertEqual(self.published, [])
        self.assertEqual(self.published_applied_ids, [])

    def test_supported_batch_emits_legacy_parity_observations_with_shared_turn(self):
        self._scenario()
        observations = []
        decision_events = []
        trace_stream = []
        trace_contexts = []

        def observe(observation, **fields):
            event = {"observation": observation, **fields}
            observations.append(event)
            trace_stream.append(event)

        def decision(outcome, reason, batch_id, _started_at, *, logical_turn=None):
            event = {
                "decision_point": "enemy_batch_resolution",
                "decision_outcome": outcome,
                "decision_reason": reason,
                "batch_id": batch_id,
                "logical_turn": logical_turn,
                "decision_source": "deterministic" if outcome == "resolver_supported" else "llm_fallback",
            }
            decision_events.append(event)
            trace_stream.append(event)
            return True

        planned_entry = replace(
            _ledger().entries[0],
            actor=CombatantIdentity("Goblin Alpha", "enemy"),
        )

        def fixed_plan(*_args, **kwargs):
            return replace(
                _ledger(),
                encounter_id="batch-fixture",
                batch_id=kwargs["batch_id"],
                entries=(planned_entry,),
            )

        dependencies = replace(
            self._dependencies(plan=fixed_plan),
            narrate=lambda ledger, *_args, **_kwargs: NarrationResult(
                text=build_enemy_batch_template_narration(ledger),
                source="template",
                reason_code="ledger_contradiction",
                reason_detail="kill_claim_contradiction",
            ),
        )
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch("utils.combat_latency_trace.trace_enabled", return_value=True), \
                mock.patch("core.combat.turn.trace_enabled", return_value=True), \
                mock.patch("utils.combat_latency_trace.set_trace_context",
                           side_effect=lambda **fields: trace_contexts.append(fields) or True), \
                mock.patch("utils.combat_latency_trace.trace_combat_observation", side_effect=observe), \
                mock.patch("utils.combat_latency_trace.trace_enemy_batch_decision", side_effect=decision), \
                mock.patch("utils.combat_latency_trace.trace_batch_file_write", return_value=True):
            result = self._execute(dependencies, logical_turn=7)

        self.assertIsInstance(result, EnemyBatchExecution)
        self.assertEqual(result.logical_turn, 8)
        self.assertEqual(len(decision_events), 1)
        self.assertEqual(decision_events[0]["logical_turn"], 8)
        self.assertEqual(len(trace_contexts), 1)
        self.assertEqual(trace_contexts[0]["batch_id"], "enemy:r1")
        self.assertEqual(trace_contexts[0]["phase"], "ENEMY_PHASE")
        self.assertNotIn("action_id", trace_contexts[0])
        self.assertEqual(
            [event.get("observation", "decision") for event in trace_stream],
            ["decision", "combat_action_batch", "combat_batch_narration_result",
             "combat_apply_result", "combat_apply_result", "combat_logical_batch_completed"],
        )
        by_observation = {}
        for event in observations:
            by_observation.setdefault(event["observation"], []).append(event)
        self.assertEqual(len(by_observation["combat_action_batch"]), 1)
        action_batch = by_observation["combat_action_batch"][0]
        self.assertEqual(action_batch["logical_turn"], 8)
        self.assertEqual(action_batch["batch_id"], "enemy:r1")
        self.assertTrue(action_batch["validation_accepted"])
        self.assertEqual(action_batch["action_count"], 1)
        self.assertTrue({
            "encounter_id", "logical_turn", "validation_accepted", "action_count",
            "action_types", "phase_before_round_transition",
            "combat_round_before_round_transition", "opening_batch_pending_before_round_transition",
            "cohort_reason", "enemy_phase_batch", "eligible_non_pc_cohort",
            "explicit_actor_records", "affected_entities", "round_transition_requested",
            "batch_id",
        }.issubset(action_batch))
        self.assertEqual(action_batch["action_types"], ["updateCharacterInfo"])
        self.assertEqual(action_batch["explicit_actor_records"], [
            {"action_index": 0, "name": "Goblin Alpha", "source": "actorName"},
        ])
        self.assertEqual(action_batch["affected_entities"], [
            {"action_index": 0, "name": "Acheron", "source": "characterName"},
        ])
        narration = by_observation["combat_batch_narration_result"][0]
        self.assertEqual((narration["batch_id"], narration["logical_turn"]), ("enemy:r1", 8))
        self.assertIn(narration["source"], ("llm", "template"))
        self.assertEqual(narration["reason_detail"], "kill_claim_contradiction")
        apply_events = by_observation["combat_apply_result"]
        self.assertEqual([(event["domain"], event["operation"]) for event in apply_events], [
            ("character", "update_character_info_ops"),
            ("encounter", "update_encounter"),
        ])
        self.assertTrue(all({"target", "changes", "ops", "applied", "failure", "batch_id"}.issubset(event)
                            for event in apply_events))
        self.assertEqual(apply_events[0]["ops"], [{"op": "hp_delta", "delta": -4}])
        self.assertEqual(apply_events[1]["ops"], [
            {"op": "hp_delta", "creature": "Acheron", "delta": -4},
        ])
        completion = by_observation["combat_logical_batch_completed"][0]
        self.assertEqual(completion["logical_turn"], 8)
        self.assertEqual((completion["round_before"], completion["round_after"]), (1, 2))
        self.assertTrue(completion["accepted_batch"])

    def test_opening_dm_group_batch_clears_marker_without_advancing_round(self):
        encounter, manager = self._scenario(opening=True)
        initial_round = encounter["combat_round"]
        initial_initiative = copy.deepcopy(encounter["initiativeRolls"])
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True):
            with mock.patch("core.combat.turn.trace_enabled", return_value=False):
                result = self._execute(self._dependencies(), encounter=encounter, manager=manager)

        self.assertIsInstance(result, EnemyBatchExecution)
        self.assertEqual(result.lifecycle_case, "opening_batch")
        self.assertEqual(result.encounter_data["combat_round"], initial_round)
        self.assertTrue(result.encounter_data["roundStartsWith"] == "dmGroup")
        self.assertFalse(result.encounter_data["openingEnemyBatchPending"])
        self.assertEqual(result.encounter_data["initiativeRolls"], initial_initiative)
        self.assertEqual(manager.current_round, initial_round)
        self.assertEqual(manager.combat_phase, "PC_PHASE")
        self.assertEqual(self.llm_tasks, ["combat_main"])
        self.assertEqual([label for label, _ in self.writes][0], "history")
        self.assertEqual([label for label, _ in self.writes][-1], "encounter")
        self.assertEqual(self.legacy_lifecycle_writes, [])

    def test_unsupported_lifecycle_cases_decline_without_narration_or_writes(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True):
            for opening_pending, round_starts_with in (
                (False, "dmGroup"),
                (True, "pcGroup"),
            ):
                with self.subTest(
                    opening_pending=opening_pending,
                    round_starts_with=round_starts_with,
                ):
                    self.writes.clear()
                    self.llm_tasks.clear()
                    self.published.clear()
                    self._scenario(opening=opening_pending)
                    self.encounter["roundStartsWith"] = round_starts_with
                    result = self._execute(self._dependencies())

                    self.assertIsInstance(result, EnemyBatchFallback)
                    self.assertEqual(result.reason_code, "round_transition_unsupported")
                    self.assertEqual(self.writes, [])
                    self.assertEqual(self.llm_tasks, [])
                    self.assertEqual(self.published, [])

    def test_unsupported_scheduled_npc_declines_before_narration_or_writes(self):
        self._scenario(unsupported_npc=True)
        dependencies = self._dependencies()
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True):
            result = self._execute(dependencies)

        self.assertIsInstance(result, EnemyBatchFallback)
        self.assertEqual(result.reason_code, "npc_actor_in_window")
        self.assertEqual(self.writes, [])
        self.assertEqual(self.llm_tasks, [])
        self.assertEqual(self.published, [])
        self.assertEqual(self.manager.current_round, 1)
        self.assertEqual(self.manager.combat_phase, "ENEMY_PHASE")
        self.assertTrue(self.encounter["openingEnemyBatchPending"] is False)

    def test_planner_exception_declines_with_zero_resolver_writes(self):
        self._scenario()

        def raise_from_planner(*_args, **_kwargs):
            raise RuntimeError("private planner detail")

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True):
            result = self._execute(self._dependencies(plan=raise_from_planner))

        self.assertIsInstance(result, EnemyBatchFallback)
        self.assertEqual(result.reason_code, "preflight_error")
        self.assertEqual(self.writes, [])
        self.assertEqual(self.llm_tasks, [])
        self.assertEqual(self.published, [])

    def test_common_combat_loop_hook_precedes_legacy_retry_and_only_skips_on_execution(self):
        source = (Path(__file__).resolve().parents[1] / "core/combat/combat_manager.py").read_text(
            encoding="utf-8"
        )
        loop_start = source.index("def _run_combat_simulation_internal(")
        hook_index = source.index("try_execute_deterministic_enemy_batch(", loop_start)
        retry_index = source.index("run_combat_provider_retry_stage(", hook_index)
        hook_block = source[loop_start:retry_index]

        self.assertLess(hook_index, retry_index)
        self.assertIn('user_input_text.strip() == "Enemies turn."', hook_block)
        self.assertIn("isinstance(deterministic_batch, EnemyBatchExecution)", hook_block)
        self.assertIn("continue", hook_block)
        self.assertIn("monster_definitions=monster_templates", hook_block)


def _actual_plan(*args, **kwargs):
    from core.combat.enemy_resolution import plan_enemy_batch
    return plan_enemy_batch(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
