# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free lifecycle and orchestration tests for tactical plan prefetch."""

from __future__ import annotations

import copy
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import model_config
import core.combat.enemy_batch_orchestrator as enemy_batch_orchestrator
from utils import combat_latency_trace
from core.combat.enemy_batch_apply import is_combat_tactical_prefetch_enabled
from core.combat.tactical_prefetch import (
    TacticalPrefetchResult,
    _reset_tactical_prefetch_for_tests,
    consume_tactical_prefetch,
    invalidate_tactical_prefetch,
    submit_tactical_prefetch,
    tactical_batch_id,
    tactical_prefetch_replan_needed,
    tactical_roster_identity,
)
from core.combat.tactical_brain import parse_standing_orders_response
from core.combat.multi_pc.manager import MultiPCCombatManager
from core.combat.multi_pc.state import PCCombatState, PCStatus
from core.combat.multi_pc.turn_queue import Combatant, CombatantType
from core.combat.turn import (
    InputPhaseGateResult,
    prepare_combat_normal_turn,
    run_input_phase_gate,
    should_consider_tactical_prefetch_replan,
)
from utils.llm_runtime import make_legacy_receipt_observer
from scripts.combat_tactical_test_support import (
    ProviderFreeTestCase,
    build_g5t_scenario,
)
from scripts import test_combat_tactical_brain as tactical_brain_tests


class TacticalPrefetchReceiptTests(ProviderFreeTestCase):
    def setUp(self):
        _reset_tactical_prefetch_for_tests()

    def tearDown(self):
        _reset_tactical_prefetch_for_tests()
        super().tearDown()

    @staticmethod
    def _messages(content="snapshot-a"):
        return [
            {"role": "system", "content": "bounded commander instructions"},
            {"role": "user", "content": content},
        ]

    @staticmethod
    def _snapshot(
        roster=("goblin squad a",),
        *,
        bloodied=False,
        near_death=False,
        commander_active=True,
        pc_active=True,
        pc_zero_hp=False,
        targeted_pcs=("acheron",),
    ):
        enemies = {
            name: {
                "active": True,
                "bloodied": bloodied if name == "goblin squad a" else False,
                "near_death": near_death if name == "goblin squad a" else False,
            }
            for name in roster
        }
        return {
            "roster": sorted(roster),
            "enemies": enemies,
            "pcs": {"acheron": {"active": pc_active, "zero_hp": pc_zero_hp}},
            "commander_active": commander_active,
            "targeted_pcs": list(targeted_pcs),
        }

    def _submit(self, *, messages=None, roster=("Goblin Squad A",), state=None,
                llm_call=None, executor=None, request_kind="initial", deadline=30,
                clock=None):
        kwargs = {
            "llm_call": llm_call or (lambda *_args, **_kwargs: '{"actors":[]}'),
            "executor": executor,
            "request_kind": request_kind,
            "deadline_seconds": deadline,
        }
        if clock is not None:
            kwargs["clock"] = clock
        return submit_tactical_prefetch(
            "encounter-1",
            "encounter-1-r1-enemy_phase",
            roster,
            messages or self._messages(),
            state or self._snapshot(),
            **kwargs,
        )

    def test_default_off_and_required_flag_dependencies(self):
        calls = []
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", False), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True):
            self.assertFalse(is_combat_tactical_prefetch_enabled())
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", False), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True):
            self.assertFalse(is_combat_tactical_prefetch_enabled())
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", False):
            self.assertFalse(is_combat_tactical_prefetch_enabled())
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True):
            self.assertTrue(is_combat_tactical_prefetch_enabled())
        self.assertFalse(model_config.COMBAT_TACTICAL_PREFETCH_ENABLED)
        self.assertFalse(model_config.COMBAT_TACTICAL_BRAIN_ENABLED)
        self.assertFalse(model_config.DETERMINISTIC_ENEMY_RESOLUTION_ENABLED)
        self.assertIsNone(self._submit_fixture_prefetch(
            phase="PC_PHASE", llm_call=lambda *args, **kwargs: calls.append(args)
        ))
        self.assertEqual(calls, [])

    def test_one_submission_per_batch_and_identity_bound_completed_consume(self):
        jobs = []
        router_calls = []
        messages = self._messages()

        def fake_router(task, payload, **kwargs):
            payload[1]["content"] = "provider-mutated-copy"
            router_calls.append((task, payload, kwargs))
            return '{"actors":[]}'

        first = self._submit(messages=messages, llm_call=fake_router, executor=jobs.append)
        duplicate = self._submit(messages=messages, llm_call=fake_router, executor=jobs.append)
        self.assertTrue(first.submitted)
        self.assertEqual(duplicate.status, "already_submitted")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(router_calls, [])

        original_messages = copy.deepcopy(messages)
        jobs[0]()
        self.assertEqual(messages, original_messages)
        consumed = consume_tactical_prefetch(
            "encounter-1", "encounter-1-r1-enemy_phase",
            current_roster_members=["Goblin Squad A"],
        )
        self.assertEqual(consumed.status, "prefetch_hit")
        self.assertEqual(consumed.result, {"actors": []})
        self.assertEqual(len(router_calls), 1)
        self.assertEqual(router_calls[0][0], "combat_main")
        self.assertEqual(router_calls[0][2]["max_tokens"], 1200)
        self.assertIsNone(consume_tactical_prefetch(
            "encounter-1", "encounter-1-r1-enemy_phase",
            current_roster_members=["Goblin Squad A"],
        ).result)

    def test_roster_identity_is_stable_but_menu_changes_do_not_stale_orders(self):
        jobs = []
        messages = self._messages("menu before PC actions")
        self.assertEqual(
            tactical_roster_identity(["Goblin Squad A", "Hobgoblin Captain"]),
            tactical_roster_identity(["hobgoblin captain", "goblin squad a"]),
        )
        self.assertNotEqual(
            tactical_roster_identity(["Goblin Squad A"]),
            tactical_roster_identity(["Goblin Squad B"]),
        )
        self.assertIsNone(tactical_roster_identity(["Goblin A", "goblin a"]))
        self._submit(
            messages=messages,
            llm_call=lambda *_args, **_kwargs: '{"actors":[]}',
            executor=jobs.append,
        )
        jobs[0]()
        # Changed perception/menu content is expected after PCs act; roster
        # identity, encounter ID and batch ID remain the receipt boundary.
        self.assertEqual(
            consume_tactical_prefetch(
                "encounter-1", "encounter-1-r1-enemy_phase",
                current_roster_members=["Goblin Squad A"],
            ).status,
            "prefetch_hit",
        )

    def test_standing_orders_schema_is_strict_and_bounded(self):
        valid = {
            "actors": [{
                "actor": {"name": "Goblin Squad A", "kind": "enemy"},
                "clauses": [{
                    "when": "self_bloodied",
                    "do": {"kind": "attack", "target": {
                        "name": "Acheron", "kind": "player",
                    }},
                }],
            }],
            "commander_clauses": [{
                "when": "commander_down", "do": "withdrawal_order",
            }],
            "intent": "Hold the line.",
        }
        self.assertEqual(parse_standing_orders_response(valid), valid)
        for invalid in (
            {"actors": [], "extra": True},
            {"actors": [{"actor": {"name": "Goblin", "kind": "player"}, "clauses": []}]},
            {"actors": [{"actor": {"name": "Goblin", "kind": "enemy"}, "clauses": [
                {"when": "whenever", "do": {"kind": "flee"}},
            ]}]},
            {"actors": [], "intent": "x" * 161},
            {"actors": [{"actor": {"name": "Goblin", "kind": "enemy"}, "clauses": [
                {"when": "always", "do": {"kind": "free_form", "action": "attack"}},
            ]}]},
            {"actors": [{"actor": {"name": "   ", "kind": "enemy"}, "clauses": []}]},
            {"actors": [{"actor": {"name": "Goblin", "kind": "enemy"}, "clauses": [
                {"when": "always", "do": {"kind": "attack", "target": {
                    "name": "  ", "kind": "player",
                }}},
            ]}]},
            {"actors": [{"actor": {"name": "Goblin", "kind": "enemy"}, "clauses": [
                {"when": "always", "do": {"kind": "take_cover", "feature_id": "  "}},
            ]}]},
            {"actors": [
                {"actor": {"name": "Goblin", "kind": "enemy"}, "clauses": []},
                {"actor": {"name": " goblin ", "kind": "enemy"}, "clauses": []},
            ]},
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(parse_standing_orders_response(invalid))

    def test_replan_requires_named_state_edges_and_is_capped_at_two_requests(self):
        jobs = []
        initial_state = self._snapshot()
        self._submit(state=initial_state, executor=jobs.append)
        self.assertFalse(tactical_prefetch_replan_needed(
            "encounter-1", "encounter-1-r1-enemy_phase", initial_state
        ))
        # Arbitrary PC action counts are not part of the state-edge comparator.
        same_state_with_actions = dict(initial_state, action_count=99)
        self.assertFalse(tactical_prefetch_replan_needed(
            "encounter-1", "encounter-1-r1-enemy_phase", same_state_with_actions
        ))

        bloodied_state = self._snapshot(bloodied=True)
        self.assertTrue(tactical_prefetch_replan_needed(
            "encounter-1", "encounter-1-r1-enemy_phase", bloodied_state
        ))
        replan = self._submit(
            state=bloodied_state,
            request_kind="replan",
            executor=jobs.append,
        )
        self.assertTrue(replan.submitted)
        self.assertEqual(replan.status, "replan_submitted")
        self.assertEqual(len(jobs), 2)
        jobs[0]()
        # Even a second distinct state edge cannot exceed initial + one re-plan.
        down_state = self._snapshot(bloodied=True, commander_active=False)
        self.assertFalse(tactical_prefetch_replan_needed(
            "encounter-1", "encounter-1-r1-enemy_phase", down_state
        ))
        capped = self._submit(
            state=down_state,
            request_kind="replan",
            executor=jobs.append,
        )
        self.assertEqual(capped.status, "request_cap_reached")
        self.assertEqual(len(jobs), 2)

        # The prior completed set remains usable while the re-plan is pending.
        pending = consume_tactical_prefetch(
            "encounter-1", "encounter-1-r1-enemy_phase",
            current_roster_members=["Goblin Squad A"],
        )
        self.assertEqual(pending.status, "prefetch_hit")
        self.assertEqual(pending.result, {"actors": []})

    def test_replan_accepts_each_authorized_major_change(self):
        initial = self._snapshot()
        cases = (
            self._snapshot(bloodied=True),
            self._snapshot(near_death=True),
            self._snapshot(commander_active=False),
            self._snapshot(pc_active=False),
            self._snapshot(pc_zero_hp=True),
            self._snapshot(roster=("goblin squad a", "goblin squad b")),
        )
        for changed in cases:
            with self.subTest(changed=changed):
                _reset_tactical_prefetch_for_tests()
                jobs = []
                self._submit(state=initial, executor=jobs.append)
                self.assertTrue(tactical_prefetch_replan_needed(
                    "encounter-1", "encounter-1-r1-enemy_phase", changed
                ))

    def test_newer_completed_orders_supersede_and_keep_receipt_roster_provenance(self):
        jobs = []
        self._submit(
            llm_call=lambda *_args, **_kwargs: '{"actors":[],"intent":"older"}',
            executor=jobs.append,
        )
        changed = self._snapshot(bloodied=True)
        self._submit(
            state=changed,
            request_kind="replan",
            llm_call=lambda *_args, **_kwargs: '{"actors":[],"intent":"newer"}',
            executor=jobs.append,
        )
        jobs[0]()
        jobs[1]()
        consumed = consume_tactical_prefetch(
            "encounter-1", "encounter-1-r1-enemy_phase",
            current_roster_members=["Goblin Squad A", "Goblin Squad B"],
        )
        self.assertEqual(consumed.status, "prefetch_hit")
        self.assertEqual(consumed.result["intent"], "newer")
        self.assertEqual(consumed.roster_members, ("goblin squad a",))

    def test_pending_failed_and_expired_receipts_default_without_waiting(self):
        jobs = []
        pending_calls = []
        self._submit(
            executor=jobs.append,
            llm_call=lambda *_args, **_kwargs: pending_calls.append(True),
        )
        self.assertEqual(
            consume_tactical_prefetch(
                "encounter-1", "encounter-1-r1-enemy_phase",
                current_roster_members=["Goblin Squad A"],
            ).status,
            "standing_orders_unavailable",
        )
        invalidate_tactical_prefetch(
            "encounter-1", "encounter-1-r1-enemy_phase"
        )
        jobs[0]()
        self.assertEqual(pending_calls, [])

        _reset_tactical_prefetch_for_tests()
        failed_jobs = []

        def failed_router(*_args, **_kwargs):
            raise RuntimeError("provider failure")

        self._submit(llm_call=failed_router, executor=failed_jobs.append)
        failed_jobs[0]()
        self.assertEqual(
            consume_tactical_prefetch(
                "encounter-1", "encounter-1-r1-enemy_phase",
                current_roster_members=["Goblin Squad A"],
            ).status,
            "standing_orders_unavailable",
        )

        _reset_tactical_prefetch_for_tests()

        def fail_to_start(_job):
            raise RuntimeError("thread start failure")

        submission = self._submit(executor=fail_to_start)
        self.assertFalse(submission.submitted)
        self.assertEqual(submission.status, "failed")
        # Since no worker/request was started, the batch may use its one sync plan.
        self.assertEqual(
            consume_tactical_prefetch(
                "encounter-1", "encounter-1-r1-enemy_phase",
                current_roster_members=["Goblin Squad A"],
            ).status,
            "prefetch_none",
        )

        _reset_tactical_prefetch_for_tests()
        expired_jobs = []
        now = [10.0]
        self._submit(
            executor=expired_jobs.append, deadline=1,
            clock=lambda: now[0],
        )
        now[0] = 12.0
        expired_jobs[0]()
        self.assertEqual(
            consume_tactical_prefetch(
                "encounter-1", "encounter-1-r1-enemy_phase",
                current_roster_members=["Goblin Squad A"],
                clock=lambda: now[0],
            ).status,
            "standing_orders_unavailable",
        )

    def test_cancellation_ignores_late_result_and_does_not_write_state(self):
        workers = []
        state = {"hp": 8, "status": "alive"}
        before = copy.deepcopy(state)
        started = threading.Event()
        release = threading.Event()
        late_calls = []

        def fake_router(_task, payload, **_kwargs):
            late_calls.append(True)
            self.assertIsInstance(payload, list)
            self.assertTrue(all(set(message) == {"role", "content"} for message in payload))
            started.set()
            release.wait(2)
            return '{"choices":[]}'

        def threaded_executor(job):
            worker = threading.Thread(target=job, daemon=True)
            workers.append(worker)
            worker.start()

        submitted = self._submit(llm_call=fake_router, executor=threaded_executor)
        replacement_jobs = []
        try:
            self.assertTrue(submitted.submitted)
            self.assertTrue(started.wait(2), "worker did not enter the router call")
            self.assertEqual(
                invalidate_tactical_prefetch(
                    "encounter-1", "encounter-1-r1-enemy_phase"
                ).status,
                "prefetch_stale",
            )
            replacement = self._submit(
                llm_call=lambda *_args, **_kwargs: '{"actors":[],"intent":"replacement"}',
                executor=replacement_jobs.append,
            )
            self.assertTrue(replacement.submitted)
            replacement_jobs[0]()
        finally:
            release.set()
            for worker in workers:
                worker.join(timeout=2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(late_calls, [True])
        self.assertEqual(state, before)
        consumed = consume_tactical_prefetch(
            "encounter-1", "encounter-1-r1-enemy_phase",
            current_roster_members=["Goblin Squad A"],
        )
        self.assertEqual(consumed.status, "prefetch_hit")
        self.assertEqual(consumed.result["intent"], "replacement")

    def test_concurrent_submission_reserves_one_receipt(self):
        jobs = []
        start = threading.Barrier(12)
        results = []
        result_lock = threading.Lock()

        def submit_once():
            start.wait()
            result = self._submit(executor=jobs.append)
            with result_lock:
                results.append(result)

        workers = [threading.Thread(target=submit_once) for _ in range(12)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=2)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(sum(result.submitted for result in results), 1)
        self.assertEqual(len(jobs), 1)

    def test_batch_identity_is_bounded_and_rejects_invalid_rounds(self):
        batch_id = tactical_batch_id("campaign/encounter-123", 4)
        self.assertEqual(batch_id, "campaign_encounter-123-r4-enemy_phase")
        self.assertLessEqual(len(tactical_batch_id("x" * 200, 4)), 64)
        self.assertIsNone(tactical_batch_id("encounter", True))
        self.assertIsNone(tactical_batch_id("encounter", 0))

    def test_input_phase_gate_marks_only_successful_pc_initiative_as_phase_start(self):
        manager = SimpleNamespace(
            combat_phase="ENEMY_PHASE",
            pc_phase_complete=True,
            current_pc_name="Acheron",
            get_remaining_enemies_for_round=lambda: [],
        )
        io = SimpleNamespace(
            emit=lambda *_args, **_kwargs: None,
            flush=lambda: None,
            debug=lambda *_args, **_kwargs: None,
            save_json=lambda *_args, **_kwargs: None,
            parse_death_save_roll=lambda *_args, **_kwargs: (False, None, None),
        )

        def gate(winner):
            return lambda *_args: {
                "handled": True,
                "encounter_updates": {"awaitingPcGroupRoll": False},
                "winner": winner,
                "marker_enabled": winner == "dmGroup",
                "mirror_payload": {},
                "pc_group_roll": 10,
                "dm_group_roll": 5,
                "phase_label": "PC_PHASE" if winner == "pcGroup" else "ENEMY_PHASE",
            }

        pc_result = run_input_phase_gate(
            "/init 10",
            encounter_data={"awaitingPcGroupRoll": True},
            multi_pc_manager=manager,
            party_tracker_data={"worldConditions": {}},
            json_file_path="encounter.json",
            conversation_history=[],
            conversation_history_file="history.json",
            io=io,
            initiative_gate=gate("pcGroup"),
        )
        self.assertTrue(pc_result.pc_phase_started)

        dm_result = run_input_phase_gate(
            "/init 10",
            encounter_data={"awaitingPcGroupRoll": True},
            multi_pc_manager=manager,
            party_tracker_data={"worldConditions": {}},
            json_file_path="encounter.json",
            conversation_history=[],
            conversation_history_file="history.json",
            io=io,
            initiative_gate=gate("dmGroup"),
        )
        self.assertFalse(dm_result.pc_phase_started)

    def test_normal_turn_submits_only_when_gate_reports_pc_phase_start(self):
        submissions = []
        session = SimpleNamespace(
            active_pc=None,
            set_phase=lambda _phase: None,
        )
        manager = SimpleNamespace(
            current_pc_name="Acheron",
            combat_phase="PC_PHASE",
        )
        iteration = SimpleNamespace(
            session=session,
            encounter_data={"encounterId": "encounter-1"},
            multi_pc_manager=manager,
            party_tracker_data={"active_character": "Acheron"},
            conversation_history=[],
            user_input_text="/init 10",
            path_manager=object(),
        )
        inputs = SimpleNamespace(
            iteration=iteration,
            encounter_id="encounter-1",
            json_file_path="encounter.json",
            conversation_history_file="history.json",
            location_info={},
        )

        def prepare(pc_phase_started):
            dependencies = SimpleNamespace(
                input_phase_gate=lambda *_args, **_kwargs: InputPhaseGateResult(
                    control_action="continue",
                    raw_input="/init 10",
                    clean_input="/init 10",
                    pc_phase_started=pc_phase_started,
                ),
                phase_gate_io_factory=lambda _manager: None,
                initiative_gate=None,
                submit_standing_orders=lambda **kwargs: submissions.append(kwargs),
            )
            prepare_combat_normal_turn(inputs, dependencies)

        prepare(False)
        self.assertEqual(submissions, [])
        prepare(True)
        self.assertEqual(len(submissions), 1)
        self.assertFalse(submissions[0]["replan"])
        self.assertEqual(submissions[0]["encounter_id"], "encounter-1")

    def _submit_fixture_prefetch(
        self, *, phase, llm_call, executor=None, receipt_observer_factory=None
    ):
        scenario = build_g5t_scenario(1)
        encounter = scenario["encounter"]
        encounter_id = encounter["encounterId"]
        scratch_root = Path("tmp/router-rollout/g5t/prefetch-fixture")

        class PathManager:
            def get_character_path(self, name):
                return str(scratch_root / ("_".join(name.lower().split()) + ".json"))

        path_manager = PathManager()
        character_files = {
            path_manager.get_character_path(name): copy.deepcopy(state)
            for name, state in scenario["pc_states"].items()
        }
        manager = MultiPCCombatManager()
        manager._turns.pc_phase_complete = phase == "ENEMY_PHASE"
        manager._turns.turn_queue = [
            Combatant(
                name=row["name"],
                type={
                    "player": CombatantType.PC,
                    "enemy": CombatantType.ENEMY,
                    "npc": CombatantType.NPC,
                }[row["kind"]],
                initiative=0,
                hp=1,
                max_hp=1,
                ac=10,
            )
            for row in scenario["turn_order"]
        ]
        for name, state in scenario["pc_states"].items():
            manager._state.pc_states[name] = PCCombatState(
                character_name=name,
                status=PCStatus.READY,
                current_hp=state["hitPoints"],
                max_hp=state["maxHitPoints"],
                ac=state["armorClass"],
            )
        encounter_before = copy.deepcopy(encounter)
        manager_before = {
            "summary": copy.deepcopy(manager.get_combat_state_summary()),
            "turn_queue": copy.deepcopy(manager._turns.turn_queue),
            "phase_events": copy.deepcopy(manager.pc_phase_event_ledger),
            "phase_event_sequence": manager.pc_phase_event_sequence,
            "phase_event_keys": copy.deepcopy(manager.pc_phase_event_keys),
        }
        submission = enemy_batch_orchestrator.submit_tactical_prefetch_for_enemy_batch(
            encounter,
            encounter_id=encounter_id,
            multi_pc_manager=manager,
            monster_definitions=scenario["monster_definitions"],
            path_manager=path_manager,
            read_json=lambda path: copy.deepcopy(character_files.get(path)),
            scene_context={
                "location": {"tacticalFeatures": scenario["tactical_features"]},
                "active_encounter_id": encounter_id,
                "combat_in_progress": True,
            },
            llm_call=llm_call,
            executor=executor,
            receipt_observer_factory=receipt_observer_factory,
        )
        self.assertEqual(encounter, encounter_before)
        self.assertEqual(
            {
                "summary": manager.get_combat_state_summary(),
                "turn_queue": manager._turns.turn_queue,
                "phase_events": manager.pc_phase_event_ledger,
                "phase_event_sequence": manager.pc_phase_event_sequence,
                "phase_event_keys": manager.pc_phase_event_keys,
            },
            manager_before,
        )
        return submission

    def test_prefetch_builder_is_pc_phase_only_bounded_and_read_only(self):
        calls = []
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True):
            self.assertIsNone(self._submit_fixture_prefetch(
                phase="ENEMY_PHASE", llm_call=lambda *args, **kwargs: calls.append((args, kwargs))
            ))
        self.assertEqual(calls, [])

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True):
            jobs = []
            router_calls = []
            submitted = self._submit_fixture_prefetch(
                phase="PC_PHASE",
                llm_call=lambda task, messages, **kwargs: (
                    router_calls.append((task, copy.deepcopy(messages), kwargs))
                    or '{"actors":[]}'
                ),
                executor=jobs.append,
            )
            self.assertTrue(submitted.submitted)
            self.assertEqual(submitted.status, "submitted")
            self.assertEqual(len(jobs), 1)
            jobs[0]()
            self.assertEqual(router_calls[0][0], "combat_main")
            self.assertEqual(set(router_calls[0][1][0]), {"role", "content"})
            scenario = build_g5t_scenario(1)
            fixture_encounter_id = scenario["encounter"]["encounterId"]
            self.assertEqual(consume_tactical_prefetch(
                fixture_encounter_id,
                tactical_batch_id(fixture_encounter_id, 1),
                current_roster_members=[
                    row["name"] for row in scenario["encounter"]["creatures"]
                    if row.get("type") == "enemy"
                    and row.get("currentHitPoints", 0) > 0
                ],
            ).status, "prefetch_hit")

    def test_configured_deadline_is_passed_to_receipt(self):
        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_DEADLINE_SECONDS", 9), \
                mock.patch.object(
                    enemy_batch_orchestrator,
                    "submit_tactical_prefetch",
                    return_value=SimpleNamespace(
                        submitted=False,
                        status="failed",
                        receipt_correlation_id=None,
                    ),
                ) as submit:
            self._submit_fixture_prefetch(
                phase="PC_PHASE",
                llm_call=lambda *_args, **_kwargs: "{}",
                executor=lambda _job: None,
            )
        self.assertEqual(submit.call_count, 1)
        self.assertEqual(submit.call_args.kwargs["deadline_seconds"], 9)

    def test_initial_and_replan_trace_have_distinct_bounded_site_attribution(self):
        observations = []
        with mock.patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                mock.patch.object(
                    combat_latency_trace,
                    "trace_combat_observation",
                    side_effect=lambda name, **fields: observations.append(
                        {"observation": name, **fields}
                    ) or True,
                ):
            for request_kind, outcome in (
                ("initial", "submitted"),
                ("replan", "replan_submitted"),
            ):
                self.assertTrue(combat_latency_trace.trace_tactical_prefetch_status(
                    "enemy:r1",
                    "plan-enemy:r1",
                    "prefetch_none",
                    receipt_correlation_id="prefetch-0000000001",
                    standing_orders_outcome=outcome,
                    request_kind=request_kind,
                    request_site="combat_tactical_prefetch",
                ))
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(
            row["request_site"] == "combat_tactical_prefetch"
            and row["request_kind"] in {"initial", "replan"}
            and row["receipt_correlation_id"] == "prefetch-0000000001"
            for row in observations
        ))

    def test_background_provider_receipt_has_batch_and_request_attribution(self):
        trace_events = []

        def observer_factory(**kwargs):
            return make_legacy_receipt_observer(
                **kwargs,
                trace_gate=lambda: True,
                trace_writer=lambda event_type, **fields: trace_events.append(
                    {"event_type": event_type, **fields}
                ) or True,
            )

        def router_call(task, _messages, **kwargs):
            kwargs["observer"](
                SimpleNamespace(
                    kind="response",
                    attempt_id="prefetch-attempt-1",
                    call_id="prefetch-call-1",
                    task=task,
                    transport_provider="openai",
                    requested_model="test-model",
                    resolved_model="test-model",
                    fallback=False,
                ),
                {"usage": None},
            )
            return '{"actors":[]}'

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True):
            jobs = []
            submission = self._submit_fixture_prefetch(
                phase="PC_PHASE",
                llm_call=router_call,
                executor=jobs.append,
                receipt_observer_factory=observer_factory,
            )
            self.assertTrue(submission.submitted)
            jobs[0]()

        self.assertEqual(len(trace_events), 1)
        event = trace_events[0]
        self.assertEqual(event["event_type"], "provider")
        self.assertEqual(event["site"], "combat_tactical_prefetch")
        self.assertEqual(event["request_site"], "combat_tactical_prefetch")
        self.assertEqual(event["request_kind"], "initial")
        self.assertEqual(event["batch_id"], "enemy:r1")
        self.assertEqual(event["purpose"], "combat_enemy_batch_standing_orders")

    def test_only_nonterminal_pc_phase_inputs_check_state_edges(self):
        manager = SimpleNamespace(combat_phase="PC_PHASE")
        self.assertTrue(should_consider_tactical_prefetch_replan(
            "[Acheron]: /att Goblin", manager
        ))
        for command in ("/end", "end", "Enemies turn.", "[DM]: /end"):
            with self.subTest(command=command):
                self.assertFalse(should_consider_tactical_prefetch_replan(
                    command, manager
                ))
        manager.combat_phase = "ENEMY_PHASE"
        self.assertFalse(should_consider_tactical_prefetch_replan("/att Goblin", manager))


class TacticalPrefetchOrchestrationTests(ProviderFreeTestCase):
    def setUp(self):
        _reset_tactical_prefetch_for_tests()

    def tearDown(self):
        _reset_tactical_prefetch_for_tests()
        super().tearDown()

    def _execute(self, *, prefetch_enabled, consumed_result=None):
        patches = [
            mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True),
            mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True),
            mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", prefetch_enabled),
        ]
        with patches[0], patches[1], patches[2]:
            with mock.patch.object(
                enemy_batch_orchestrator,
                "submit_tactical_prefetch_for_enemy_batch",
                return_value=None,
            ):
                if consumed_result is None:
                    result = tactical_brain_tests.CombatTacticalOrchestrationTests()._execute()
                else:
                    with mock.patch.object(
                        enemy_batch_orchestrator,
                        "has_tactical_prefetch_submission",
                        return_value=True,
                    ), mock.patch.object(
                        enemy_batch_orchestrator,
                        "consume_tactical_prefetch",
                        return_value=consumed_result,
                    ) as consume:
                        result = tactical_brain_tests.CombatTacticalOrchestrationTests()._execute()
                        self.assertEqual(consume.call_count, 1)
        return result

    def test_no_submission_uses_exactly_one_synchronous_plan(self):
        result = self._execute(prefetch_enabled=True)
        self.assertEqual(
            sum(call["kind"] == "plan" for call in result["llm_calls"]), 1
        )

    def test_phase_start_and_state_edge_hooks_do_not_use_pc_action_counts(self):
        repo_root = Path(__file__).resolve().parents[1]
        turn_source = (repo_root / "core/combat/turn.py").read_text(encoding="utf-8")
        manager_source = (repo_root / "core/combat/combat_manager.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("pc_phase_started", turn_source)
        self.assertIn("dependencies.submit_standing_orders", turn_source)
        self.assertIn("submit_tactical_prefetch_for_enemy_batch", manager_source)
        self.assertIn("replan=True", manager_source)
        self.assertIn("should_consider_tactical_prefetch_replan", manager_source)
        self.assertNotIn("all_pcs_acted", turn_source + manager_source)

        with mock.patch.object(model_config, "DETERMINISTIC_ENEMY_RESOLUTION_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_BRAIN_ENABLED", True), \
                mock.patch.object(model_config, "COMBAT_TACTICAL_PREFETCH_ENABLED", True):
            result = self._execute(prefetch_enabled=True)
        self.assertEqual(
            sum(call["kind"] == "plan" for call in result["llm_calls"]), 1
        )

    def test_submitted_unavailable_orders_use_rule_defaults_without_replanning(self):
        result = self._execute(
            prefetch_enabled=True,
            consumed_result=TacticalPrefetchResult("standing_orders_unavailable"),
        )
        self.assertEqual(
            sum(call["kind"] == "plan" for call in result["llm_calls"]), 0
        )
        self.assertTrue(any(call["kind"] == "narration" for call in result["llm_calls"]))

    def test_prefetched_response_is_validated_and_not_replanned(self):
        response = {"actors": []}
        result = self._execute(
            prefetch_enabled=True,
            consumed_result=TacticalPrefetchResult("prefetch_hit", result=response),
        )
        self.assertEqual(
            sum(call["kind"] == "plan" for call in result["llm_calls"]), 0
        )
        # The response is intentionally incomplete; validation produces safe
        # rule-tier defaults rather than bypassing the current menu contract.
        self.assertTrue(any(call["kind"] == "narration" for call in result["llm_calls"]))


if __name__ == "__main__":
    unittest.main()
