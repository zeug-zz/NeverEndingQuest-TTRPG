# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-tripwire tests for initiative-ordered ally and hostile batches."""

from __future__ import annotations

import copy
import json
from unittest import mock

import model_config
from core.combat.ally_controller import (
    build_ally_directive_history_record,
    rule_default_ally_plan,
)
from core.combat.ally_prefetch import AllyPrefetchSelection
from core.combat.enemy_batch_orchestrator import EnemyBatchExecution, EnemyBatchFallback
from scripts.combat_ally_test_support import AllyBatchHarness
from scripts.combat_tactical_test_support import ProviderFreeTestCase


class CombatAllyBatchTests(ProviderFreeTestCase):
    def test_both_initiative_orders_and_party_shapes_keep_distinct_batches(self):
        for starts_with in ("dmGroup", "pcGroup"):
            for party_size in (1, 4):
                with self.subTest(starts_with=starts_with, party_size=party_size):
                    harness = AllyBatchHarness(
                        party_size,
                        starts_with=starts_with,
                    )
                    try:
                        with mock.patch.multiple(
                            model_config,
                            DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=True,
                            COMBAT_ALLY_CONTROLLER_ENABLED=True,
                        ):
                            result = harness.execute()

                        self.assertIsInstance(result, EnemyBatchExecution)
                        expected_events = (
                            [
                                "hostile_plan",
                                "ally_plan",
                                "hostile_narration",
                                "ally_narration",
                            ]
                            if starts_with == "dmGroup"
                            else [
                                "ally_plan",
                                "hostile_plan",
                                "ally_narration",
                                "hostile_narration",
                            ]
                        )
                        self.assertEqual(harness.events, expected_events)
                        self.assertEqual(len(harness.provider_calls), 3)

                        actor_kinds = [entry.actor.kind for entry in result.ledger.entries]
                        expected_kinds = (
                            ["enemy", "npc"] if starts_with == "dmGroup"
                            else ["npc", "enemy"]
                        )
                        self.assertEqual(actor_kinds, expected_kinds)
                        self.assertLess(
                            next(
                                row["currentHitPoints"]
                                for row in result.encounter_data["creatures"]
                                if row["name"] == "Goblin Alpha"
                            ),
                            10,
                        )
                        self.assertLess(
                            next(
                                row["currentHitPoints"]
                                for row in result.encounter_data["creatures"]
                                if row["type"] == "player"
                            ),
                            20,
                        )
                        self.assertEqual(len(result.encounter_data["turn_receipts"]), 1)
                        self.assertEqual(len(harness.published), 1)
                        self.assertEqual(
                            harness.published[0][1], result.application.applied_id
                        )
                        ally_position = result.narration.text.index("Scout")
                        hostile_position = result.narration.text.index("Goblin Alpha")
                        self.assertLess(
                            ally_position if starts_with == "pcGroup" else hostile_position,
                            hostile_position if starts_with == "pcGroup" else ally_position,
                        )
                    finally:
                        harness.close()

    def test_near_death_preflight_hands_off_before_narration_or_commit(self):
        harness = AllyBatchHarness(1, starts_with="pcGroup")
        try:
            goblin = next(
                row for row in harness.encounter["creatures"]
                if row["name"] == "Goblin Alpha"
            )
            goblin["currentHitPoints"] = 8
            goblin["maxHitPoints"] = 36
            harness.persisted_encounter = copy.deepcopy(harness.encounter)
            harness.history[1] = build_ally_directive_history_record(
                "Scout", "take cover behind the shield racks"
            )
            before_encounter = copy.deepcopy(harness.encounter)
            scene_context = {
                "active_encounter_id": harness.encounter_id,
                "combat_in_progress": True,
                "npc_profiles": {},
                "location": {
                    "name": "Practice field",
                    "tacticalFeatures": [{
                        "featureId": "practice-shield-racks",
                        "name": "Practice Shield Racks",
                        "kind": "cover",
                        "coverType": "half",
                        "usableBy": ["npc"],
                    }],
                },
            }
            with mock.patch.multiple(
                model_config,
                DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=True,
                COMBAT_ALLY_CONTROLLER_ENABLED=True,
            ), mock.patch(
                "core.combat.enemy_batch_orchestrator.is_ally_prefetch_enabled",
                return_value=False,
            ), mock.patch(
                "core.combat.enemy_batch_orchestrator.is_combat_tactical_prefetch_enabled",
                return_value=False,
            ), mock.patch(
                "core.combat.enemy_batch_orchestrator.is_combat_tactical_brain_enabled",
                return_value=False,
            ):
                result = harness.execute(scene_context=scene_context)

            self.assertIsInstance(result, EnemyBatchFallback)
            self.assertEqual(result.reason_code, "near_death_enemy")
            self.assertEqual(harness.events, ["ally_plan", "hostile_plan"])
            self.assertEqual(len(harness.provider_calls), 1)
            ally_projection = json.loads(harness.provider_calls[0][2][-1]["content"])
            scout_menu = next(
                row for row in ally_projection["scheduled_allies"]
                if row["actor"] == "Scout"
            )
            self.assertEqual(
                scout_menu["directive"], "take cover behind the shield racks"
            )
            self.assertTrue(any(
                option["kind"] == "take_cover" for option in scout_menu["options"]
            ))
            self.assertEqual(harness.writes, [])
            self.assertIsNone(harness.persisted_history)
            self.assertEqual(harness.published, [])
            self.assertEqual(harness.encounter, before_encounter)
            self.assertEqual(harness.persisted_encounter, before_encounter)
            self.assertEqual(harness.manager.current_round, 1)
            self.assertEqual(harness.manager.combat_phase, "ENEMY_PHASE")
            scout_after = next(
                row for row in harness.encounter["creatures"]
                if row["name"] == "Scout"
            )
            self.assertNotIn("coverFeatureId", scout_after)
            self.assertNotIn("coverType", scout_after)
        finally:
            harness.close()

    def test_ally_defeating_last_hostile_skips_an_empty_hostile_batch(self):
        harness = AllyBatchHarness(1, starts_with="pcGroup")
        try:
            next(
                row for row in harness.encounter["creatures"]
                if row["name"] == "Goblin Alpha"
            )["currentHitPoints"] = 1
            with mock.patch.multiple(
                model_config,
                DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=True,
                COMBAT_ALLY_CONTROLLER_ENABLED=True,
            ):
                result = harness.execute()

            self.assertIsInstance(result, EnemyBatchExecution)
            self.assertEqual(harness.events, ["ally_plan", "ally_narration"])
            self.assertEqual(len(harness.provider_calls), 2)
            self.assertEqual(
                [entry.actor.kind for entry in result.ledger.entries],
                ["npc"],
            )
            goblin = next(
                row for row in result.encounter_data["creatures"]
                if row["name"] == "Goblin Alpha"
            )
            self.assertEqual(goblin["currentHitPoints"], 0)
            self.assertEqual(goblin["status"], "defeated")
            self.assertEqual(len(result.encounter_data["turn_receipts"]), 1)
        finally:
            harness.close()

    def test_selected_prefetch_uses_compiled_plan_without_sync_planner_call(self):
        harness = AllyBatchHarness(1, starts_with="pcGroup")
        try:
            def select_prefetch(_encounter_id, menus, _encounter):
                return AllyPrefetchSelection(
                    selected=True,
                    status="standing_orders",
                    plan=rule_default_ally_plan(menus),
                    plan_origin="standing_orders",
                )

            with (
                mock.patch.multiple(
                    model_config,
                    DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=True,
                    COMBAT_ALLY_CONTROLLER_ENABLED=True,
                ),
                mock.patch(
                    "core.combat.enemy_batch_orchestrator.is_ally_prefetch_enabled",
                    return_value=True,
                ),
                mock.patch(
                    "core.combat.enemy_batch_orchestrator.has_ally_prefetch_submission",
                    return_value=True,
                ),
                mock.patch(
                    "core.combat.enemy_batch_orchestrator.select_ally_prefetch_plan",
                    side_effect=select_prefetch,
                ),
                mock.patch(
                    "core.combat.ally_prefetch.submit_ally_prefetch",
                    return_value=None,
                ),
            ):
                result = harness.execute()

            self.assertIsInstance(result, EnemyBatchExecution)
            self.assertEqual(
                harness.events,
                ["hostile_plan", "ally_narration", "hostile_narration"],
            )
            self.assertEqual(len(harness.provider_calls), 2)
            self.assertEqual(
                [entry.actor.kind for entry in result.ledger.entries],
                ["npc", "enemy"],
            )
        finally:
            harness.close()

    def test_controller_off_keeps_the_existing_hostile_decline(self):
        harness = AllyBatchHarness(1, starts_with="pcGroup")
        try:
            with mock.patch.multiple(
                model_config,
                DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=True,
                COMBAT_ALLY_CONTROLLER_ENABLED=False,
            ):
                result = harness.execute()

            self.assertIsInstance(result, EnemyBatchFallback)
            self.assertEqual(result.reason_code, "npc_actor_in_window")
            self.assertEqual(harness.events, ["hostile_plan"])
            self.assertEqual(harness.provider_calls, [])
            self.assertEqual(harness.writes, [])
        finally:
            harness.close()
