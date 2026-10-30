# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free bounds and application tests for tactical combat traces."""

from __future__ import annotations

from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import model_config
from core.combat.enemy_batch_apply import apply_enemy_batch
from core.combat.enemy_narration import NarrationResult
from core.combat.enemy_resolution import (
    CombatantIdentity,
    EnemyAttackLedgerEntry,
    EnemyCoverUpdate,
    EnemyDeparture,
    EnemyResolutionLedger,
    plan_enemy_batch,
)
from core.combat.tactical_brain import (
    TacticalActorMenu,
    TacticalMenus,
    TacticalOption,
    ValidatedTacticalChoice,
    ValidatedTacticalPlan,
    build_tactical_menus,
    validate_commander_plan,
)
from core.combat.enemy_batch_orchestrator import (
    _apply_tactical_choices_to_ledger,
    _task_3_2_self_preservation_hook,
    _trace_tactical_application_outcomes,
    _trace_tactical_plan_result,
)
from utils import combat_latency_trace


class CombatTacticalTraceTests(unittest.TestCase):
    @staticmethod
    def _application_fixture(*, rejected=False, partially_defaulted=False, forged=False):
        actor_one = CombatantIdentity("Goblin One", "enemy")
        actor_two = CombatantIdentity("Goblin Two", "enemy")
        target = CombatantIdentity("Acheron", "player")
        options = (
            TacticalOption("issued-1", "attack", actor_one, "Scimitar", target),
            TacticalOption("issued-2", "attack", actor_two, "Scimitar", target),
        )
        actor_menus = (
            TacticalActorMenu(actor_one, ((options[0],),), (), ("issued-1",)),
            TacticalActorMenu(actor_two, ((options[1],),), (), ("issued-2",)),
        )
        menus = TacticalMenus(
            "fixture-r1-enemy_phase", actor_one, actor_menus, (), (target,),
            (actor_one, actor_two),
        )
        if rejected:
            choices = (
                ValidatedTacticalChoice(actor_one, "attack", ("issued-1",), True, False,
                                        default_reason="MISSING_CHOICE"),
                ValidatedTacticalChoice(actor_two, "attack", ("issued-2",), True, False,
                                        default_reason="INVALID_CHOICE"),
            )
        elif partially_defaulted:
            choices = (
                ValidatedTacticalChoice(actor_one, "attack", ("issued-1",), True, False),
                ValidatedTacticalChoice(actor_two, "attack", ("issued-2",), True, False,
                                        default_reason="MISSING_CHOICE"),
            )
        elif forged:
            choices = (ValidatedTacticalChoice(actor_one, "attack", ("forged-option",), True, False),)
        else:
            choices = tuple(
                ValidatedTacticalChoice(menu.actor, "attack", (menu.default_option_ids[0],), True, False)
                for menu in actor_menus
            )
        plan = ValidatedTacticalPlan(
            "rejected_all" if rejected else "partially_defaulted" if partially_defaulted else "accepted",
            choices, False, False, (), (), menus, (target,),
        )
        entries = []
        for actor in (actor_one, actor_two):
            if forged and actor == actor_two:
                continue
            entries.append(EnemyAttackLedgerEntry(
                actor=actor, action_name="Scimitar", target=target, d20=12,
                attack_total=14, armor_class=12, hit=True, critical=False,
                damage_dice_rolls=(3,), damage_total=3, damage_type="slashing",
                target_hp_before=10, target_hp_after=7, target_status_after="alive",
            ))
        ledger = EnemyResolutionLedger(
            encounter_id="fixture", round_number=1, batch_id="fixture-r1-enemy_phase",
            batch_kind="enemy_phase", seed=1, entries=tuple(entries), bloodied=(),
        )
        return plan, menus, ledger

    @staticmethod
    def _g5t_departure_case(party_size, round_number, hp_by_name, *,
                            side_surrender=False, choice_kinds=None):
        from scripts.combat_latency_fixtures import (
            G5T_COMMANDER_NAME,
            G5T_GOBLIN_NAMES,
        )
        from scripts.combat_tactical_test_support import build_g5t_scenario

        scenario = build_g5t_scenario(party_size)
        encounter = scenario["encounter"]
        encounter["combat_round"] = round_number
        for creature in encounter["creatures"]:
            if creature.get("type") != "enemy":
                continue
            hp = hp_by_name.get(creature["name"], 0)
            creature["currentHitPoints"] = hp
            creature["status"] = "alive" if hp > 0 else "defeated"
        enemy_window = [
            row for row in scenario["turn_order"]
            if row["kind"] == "enemy" and hp_by_name.get(row["name"], 0) > 0
        ]
        batch_id = "%s-r%d-enemy_phase" % (
            encounter["encounterId"], round_number
        )
        menus = build_tactical_menus(
            encounter,
            scenario["pc_states"],
            scenario["monster_definitions"],
            scenario["turn_order"],
            batch_id,
            batch_kind="enemy_phase",
            fixture_seed=scenario["fixture_seed"],
            enemy_turn_window=enemy_window,
            tactical_features=scenario["tactical_features"],
        )
        if not isinstance(menus, TacticalMenus):
            raise AssertionError("G5T departure case did not produce tactical menus")

        choice_rows = []
        for actor_menu in menus.actor_menus:
            option_ids = list(actor_menu.default_option_ids)
            selected_kind = (choice_kinds or {}).get(actor_menu.actor.name)
            if selected_kind is not None:
                option = next((item for item in actor_menu.choices
                               if item.kind == selected_kind), None)
                if option is None:
                    raise AssertionError(
                        "G5T departure case has no %s choice for %s" %
                        (selected_kind, actor_menu.actor.name)
                    )
                option_ids = [option.option_id]
            elif not side_surrender and actor_menu.actor.name == G5T_COMMANDER_NAME:
                option_ids = [next(
                    item.option_id for item in actor_menu.choices
                    if item.kind == "surrender"
                )]
            choice_rows.append({"actor": actor_menu.actor.name,
                                "option_ids": option_ids})
        orders = []
        if side_surrender:
            orders = [next(
                item.option_id for item in menus.commander_options
                if item.kind == "commander_side_surrender"
            )]
        plan = validate_commander_plan(
            {"choices": choice_rows, "orders": orders}, menus
        )
        resolver_arguments = (
            encounter,
            scenario["pc_states"],
            scenario["monster_definitions"],
            scenario["turn_order"],
        )
        resolver_options = {
            "batch_id": batch_id,
            "batch_kind": "enemy_phase",
            "fixture_seed": scenario["fixture_seed"],
            "enemy_turn_window": enemy_window,
            "allow_near_death": True,
            "tactical_features": scenario["tactical_features"],
        }
        default_ledger = plan_enemy_batch(*resolver_arguments, **resolver_options)
        dependencies = SimpleNamespace(
            resolve_self_preservation=None,
            plan=plan_enemy_batch,
        )
        planned = _task_3_2_self_preservation_hook(
            plan,
            menus,
            default_ledger,
            dependencies,
            resolver_arguments,
            resolver_options,
            {},
            nonattacking_actors=set(),
        )
        if planned is None:
            raise AssertionError("G5T departure case did not project departures")
        ledger = _apply_tactical_choices_to_ledger(planned, plan, menus)
        if ledger is None:
            raise AssertionError("G5T departure case did not apply tactical choices")
        expected_actor_count = sum(
            hp_by_name.get(menu.actor.name, 0) > 0 for menu in menus.actor_menus
        ) if side_surrender else 1
        if len(plan.choices) != expected_actor_count:
            raise AssertionError("G5T departure case actor window changed")
        expected_actors = (
            {menu.actor.name for menu in menus.actor_menus}
            if side_surrender else {G5T_COMMANDER_NAME}
        )
        if {choice.actor.name for choice in plan.choices} != expected_actors:
            raise AssertionError("G5T departure case actor identities changed")
        return plan, menus, ledger

    def test_gate3_surrender_shapes_count_projected_departures_as_followed(self):
        Path("tmp/router-rollout/g5t").mkdir(parents=True, exist_ok=True)
        cases = (
            (1, 4, {"Hobgoblin Captain": 9,
                    "Goblin Squad A": 0, "Goblin Squad B": 0}, False, 1, None),
            (4, 1, {"Hobgoblin Captain": 9,
                    "Goblin Squad A": 1, "Goblin Squad B": 7}, True, 3,
             {"Hobgoblin Captain": "surrender",
              "Goblin Squad A": "take_cover", "Goblin Squad B": "hold"}),
            (4, 2, {"Hobgoblin Captain": 2,
                    "Goblin Squad A": 0, "Goblin Squad B": 6}, True, 2,
             {"Hobgoblin Captain": "surrender", "Goblin Squad B": "hold"}),
        )
        with tempfile.TemporaryDirectory(
            prefix="gate3-surrender-trace-", dir="tmp/router-rollout/g5t"
        ) as directory:
            for party_size, round_number, hp, side_surrender, expected_count, choice_kinds in cases:
                plan, menus, ledger = self._g5t_departure_case(
                    party_size,
                    round_number,
                    hp,
                    side_surrender=side_surrender,
                    choice_kinds=choice_kinds,
                )
                if choice_kinds:
                    self.assertEqual(
                        {choice.actor.name: choice.kind for choice in plan.choices},
                        choice_kinds,
                    )
                trace_path = Path(directory) / (
                    "p%d-r%d.jsonl" % (party_size, round_number)
                )
                with self.subTest(party_size=party_size, round_number=round_number), \
                        patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                        patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                    _trace_tactical_application_outcomes(
                        plan,
                        menus,
                        ledger,
                        batch_id="enemy:r%d" % round_number,
                        plan_requested=True,
                    )
                rows = [
                    json.loads(line)
                    for line in trace_path.read_text(encoding="ascii").splitlines()
                ]
                squad = next(
                    row for row in rows
                    if row.get("observation") == "commander_squad_follows_orders"
                )
                legality = next(
                    row for row in rows
                    if row.get("observation") == "applied_choice_legality"
                )
                self.assertEqual(squad["issued_choice_count"], expected_count)
                self.assertEqual(squad["applied_choice_count"], expected_count)
                self.assertTrue(squad["followed_orders"])
                self.assertEqual(legality["applied_choice_count"], expected_count)
                self.assertEqual(legality["legal_applied_choice_count"], expected_count)

    def test_projected_departures_replace_actor_choices_without_side_order_flag(self):
        from scripts.combat_latency_fixtures import G5T_COMMANDER_NAME, G5T_GOBLIN_NAMES

        plan, menus, ledger = self._g5t_departure_case(
            4,
            1,
            {"Hobgoblin Captain": 9, "Goblin Squad A": 1, "Goblin Squad B": 7},
            side_surrender=True,
            choice_kinds={
                G5T_COMMANDER_NAME: "surrender",
                G5T_GOBLIN_NAMES[0]: "take_cover",
                G5T_GOBLIN_NAMES[1]: "hold",
            },
        )
        self.assertEqual(len(ledger.departures), 3)
        self.assertTrue(all(row.reason == "surrendered" for row in ledger.departures))
        plan = replace(plan, side_surrender=False)

        with tempfile.TemporaryDirectory(
            prefix="projected-surrender-trace-", dir="tmp/router-rollout/g5t"
        ) as directory:
            trace_path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                    patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                _trace_tactical_application_outcomes(
                    plan,
                    menus,
                    ledger,
                    batch_id="enemy:r1",
                    plan_requested=True,
                )
            rows = [json.loads(line) for line in trace_path.read_text(
                encoding="ascii").splitlines()]
        squad = next(row for row in rows
                     if row.get("observation") == "commander_squad_follows_orders")
        legality = next(row for row in rows
                        if row.get("observation") == "applied_choice_legality")
        self.assertEqual(squad["issued_choice_count"], 3)
        self.assertEqual(squad["applied_choice_count"], 3)
        self.assertTrue(squad["followed_orders"])
        self.assertEqual(legality["applied_choice_count"], 3)
        self.assertEqual(legality["legal_applied_choice_count"], 3)

    def test_application_observations_count_only_accepted_choices_and_recheck_menu(self):
        cases = (
            ({}, (2, 2, 2, True)),
            ({"partially_defaulted": True}, (1, 1, 1, True)),
            ({"rejected": True}, (0, 0, 0, False)),
            ({"forged": True}, (1, 0, 1, False)),
        )
        with tempfile.TemporaryDirectory(
            prefix="tactical-application-trace-", dir="tmp/router-rollout/g5t"
        ) as directory:
            trace_path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                    patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                for options, expected in cases:
                    plan, menus, ledger = self._application_fixture(**options)
                    _trace_tactical_application_outcomes(
                        plan, menus, ledger, batch_id="enemy:r1", plan_requested=True,
                    )

            rows = [json.loads(line) for line in trace_path.read_text(encoding="ascii").splitlines()]
            legality = [row for row in rows if row.get("observation") == "applied_choice_legality"]
            squad = [row for row in rows if row.get("observation") == "commander_squad_follows_orders"]
            self.assertEqual(len(legality), 3)
            self.assertEqual(len(squad), 4)
            for index, expected in enumerate((cases[0][1], cases[1][1], cases[3][1])):
                self.assertEqual((legality[index]["applied_choice_count"],
                                  legality[index]["legal_applied_choice_count"]), expected[:2])
            self.assertEqual(
                [(row["issued_choice_count"], row["applied_choice_count"], row["followed_orders"])
                 for row in squad],
                [(case[1][2], case[1][0], case[1][3]) for case in cases],
            )
            for row in rows:
                if row.get("observation") not in {
                    "applied_choice_legality", "commander_squad_follows_orders"
                }:
                    continue
                allowed_strings = {"combat_observation", row["observation"], "enemy:r1"}
                self.assertFalse(any(isinstance(value, str) and value not in allowed_strings
                                     for key, value in row.items()
                                     if key not in {"event_type", "observation", "batch_id"}))

            plan, menus, ledger = self._application_fixture()
            _trace_tactical_application_outcomes(
                plan, menus, ledger, batch_id="enemy:r2", plan_requested=False,
            )
            self.assertEqual(len(trace_path.read_text(encoding="ascii").splitlines()), len(rows))

    def test_tactical_decision_keeps_source_outcomes_and_defaults_bounded(self):
        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_decision", return_value=True) as writer:
            self.assertTrue(combat_latency_trace.trace_enemy_batch_decision(
                "resolver_supported",
                "ledger_supported",
                "enemy:r4",
                1.0,
                decision_source="llm_tactical",
                tactical_plan_outcome="partially_defaulted",
                default_reasons=[
                    {"actor_id": "actor_2", "reason_code": "MISSING_CHOICE"},
                    {"actor_id": "../secret", "reason_code": "MISSING_CHOICE"},
                    {"actor_id": "actor_3", "reason_code": "prompt text"},
                ],
                prefetch_status="prefetch_none",
            ))

        self.assertEqual(writer.call_count, 1)
        args, kwargs = writer.call_args
        self.assertEqual(args[:2], ("enemy_batch_resolution", "llm_tactical"))
        self.assertFalse(kwargs["provider_call_avoided"])
        self.assertEqual(kwargs["tactical_plan_outcome"], "partially_defaulted")
        self.assertEqual(kwargs["prefetch_status"], "prefetch_none")
        self.assertEqual(kwargs["default_reasons"], [
            {"actor_id": "actor_2", "reason_code": "MISSING_CHOICE"},
        ])
        self.assertNotIn("secret", json.dumps(kwargs))
        self.assertNotIn("prompt text", json.dumps(kwargs))

    def test_plan_prefetch_and_cover_helpers_emit_only_bounded_fields(self):
        with tempfile.TemporaryDirectory(
            prefix="tactical-trace-", dir="tmp/router-rollout/g5t"
        ) as directory:
            trace_path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                    patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                actor_ids = combat_latency_trace.build_run_local_actor_ids([
                    {"name": "Acheron", "type": "player"},
                    {"name": "Hobgoblin Captain", "type": "enemy"},
                ])
                self.assertEqual(actor_ids[("enemy", "hobgoblin captain")], "actor_2")
                self.assertTrue(combat_latency_trace.trace_tactical_plan_result(
                    "enemy:r3",
                    "plan-encounter-r3",
                    "rejected_all",
                    [{"actor_id": "actor_2", "reason_code": "INVALID_CHOICE"}],
                    prefetch_status="prefetch_none",
                    actor_ids=["actor_1", "../secret", "actor_2", "actor_1"],
                    target_ids=["actor_2", "actor_33", "actor_3"],
                ))
                self.assertTrue(combat_latency_trace.trace_tactical_prefetch_status(
                    "enemy:r3", "plan-encounter-r3", "prefetch_none",
                    standing_orders_outcome="submitted",
                    request_kind="initial",
                    request_site="combat_tactical_prefetch",
                ))
                self.assertTrue(combat_latency_trace.trace_tactical_self_preservation_outcome(
                    "enemy:r3", "actor_2", "surrendered",
                ))
                self.assertTrue(combat_latency_trace.trace_tactical_cover_outcome(
                    "enemy:r3", "actor_2", "PIT_COVER", "three_quarters", "selected",
                ))
                self.assertTrue(combat_latency_trace.trace_tactical_cover_outcome(
                    "enemy:r3", "actor_2", "/private/secret/location.json", "half", "expired",
                ))
                self.assertFalse(combat_latency_trace.trace_tactical_self_preservation_outcome(
                    "enemy:r3", "actor_2", "escaped",
                ))
                self.assertFalse(combat_latency_trace.trace_tactical_plan_result(
                    "enemy:r3", "plan-encounter-r3", "free-form", [],
                ))

            rows = [
                json.loads(line)
                for line in trace_path.read_text(encoding="ascii").splitlines()
            ]
            by_observation = {row["observation"]: row for row in rows}
            self.assertEqual(len(rows), 5)
            self.assertEqual(
                by_observation["combat_tactical_plan_result"]["tactical_plan_outcome"],
                "rejected_all",
            )
            self.assertEqual(
                by_observation["combat_tactical_plan_result"]["actor_ids"],
                ["actor_1", "actor_2"],
            )
            self.assertEqual(
                by_observation["combat_tactical_plan_result"]["target_ids"],
                ["actor_2", "actor_3"],
            )
            self.assertEqual(
                by_observation["combat_tactical_prefetch_status"]["prefetch_status"],
                "prefetch_none",
            )
            self.assertEqual(
                by_observation["combat_tactical_prefetch_status"]["request_site"],
                "combat_tactical_prefetch",
            )
            self.assertEqual(
                by_observation["combat_tactical_prefetch_status"]["request_kind"],
                "initial",
            )
            self.assertEqual(
                by_observation["combat_self_preservation_outcome"]["self_preservation_outcome"],
                "surrendered",
            )
            cover_rows = [row for row in rows if row["observation"] == "combat_cover_outcome"]
            self.assertEqual(cover_rows[0]["feature_id"], "PIT_COVER")
            self.assertEqual(cover_rows[0]["cover_state"], "selected")
            self.assertNotIn("feature_id", cover_rows[1])
            self.assertEqual(cover_rows[1]["reason_code"], "malformed_feature_id")
            self.assertTrue(all(row["batch_id"] == "enemy:r3" for row in rows))
            self.assertNotIn(directory, trace_path.read_text(encoding="ascii"))
            self.assertNotIn("private", trace_path.read_text(encoding="ascii"))

    def test_orchestrator_projects_only_actor_and_enemy_target_menu_ids(self):
        with tempfile.TemporaryDirectory(
            prefix="tactical-plan-result-trace-", dir="tmp/router-rollout/g5t"
        ) as directory:
            trace_path = Path(directory) / "trace.jsonl"
            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                    patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                plan, menus, _ledger = self._application_fixture()
                actor_ids = combat_latency_trace.build_run_local_actor_ids([
                    {"name": "Goblin One", "type": "enemy"},
                    {"name": "Goblin Two", "type": "enemy"},
                    {"name": "Acheron", "type": "player"},
                ])
                _trace_tactical_plan_result(
                    plan, batch_id="enemy:r1", menus=menus, actor_ids=actor_ids,
                )

            rows = [json.loads(line) for line in trace_path.read_text(encoding="ascii").splitlines()]
            plan_row = next(row for row in rows
                            if row.get("observation") == "combat_tactical_plan_result")
            self.assertEqual(plan_row["actor_ids"], ["actor_1", "actor_2"])
            self.assertEqual(plan_row["target_ids"], ["actor_1", "actor_2"])

    def test_trace_gate_and_writer_failures_are_non_interfering(self):
        with patch.object(combat_latency_trace, "trace_enabled", return_value=False), \
                patch.object(combat_latency_trace, "emit_trace_event") as writer:
            self.assertFalse(combat_latency_trace.trace_tactical_plan_result(
                "enemy:r1", "plan-batch", "accepted",
            ))
            self.assertFalse(combat_latency_trace.trace_tactical_prefetch_status(
                "enemy:r1", "plan-batch", "prefetch_none",
            ))
            self.assertFalse(combat_latency_trace.trace_tactical_self_preservation_outcome(
                "enemy:r1", "actor_1", "fled",
            ))
            self.assertFalse(combat_latency_trace.trace_tactical_cover_outcome(
                "enemy:r1", "actor_1", "PIT_COVER", "half", "applied",
            ))
            self.assertFalse(combat_latency_trace.trace_applied_choice_legality(
                "enemy:r1", 1, 1,
            ))
            self.assertFalse(combat_latency_trace.trace_commander_squad_follows_orders(
                "enemy:r1", 1, 1, True,
            ))
            writer.assert_not_called()

        with patch.object(combat_latency_trace, "trace_enabled", return_value=True), \
                patch.object(combat_latency_trace, "trace_combat_observation",
                             side_effect=OSError("trace unavailable")):
            self.assertFalse(combat_latency_trace.trace_tactical_self_preservation_outcome(
                "enemy:r1", "actor_1", "fled",
            ))

    def test_apply_traces_only_persisted_self_preservation_and_cover_changes(self):
        with tempfile.TemporaryDirectory(
            prefix="tactical-apply-trace-", dir="tmp/router-rollout/g5t"
        ) as directory:
            trace_path = Path(directory) / "trace.jsonl"
            encounter_before = {
                "encounterId": "fixture",
                "combat_round": 1,
                "combat_phase": "PC_PHASE",
                "creatures": [
                    {
                        "name": "Goblin One", "type": "enemy", "currentHitPoints": 4,
                        "status": "alive", "coverFeatureId": "OLD_COVER", "coverType": "half",
                    },
                    {"name": "Goblin Two", "type": "enemy", "currentHitPoints": 8, "status": "alive"},
                ],
            }
            ledger = EnemyResolutionLedger(
                encounter_id="fixture",
                round_number=1,
                batch_id="fixture-r1-enemy_phase",
                batch_kind="enemy_phase",
                seed=7,
                entries=(),
                bloodied=(),
                departures=(EnemyDeparture(
                    CombatantIdentity(name="Goblin One", kind="enemy"), "fled"
                ),),
                cover_updates=(
                    EnemyCoverUpdate(CombatantIdentity(name="Goblin One", kind="enemy")),
                    EnemyCoverUpdate(
                        CombatantIdentity(name="Goblin Two", kind="enemy"),
                        feature_id="PIT_COVER",
                        cover_type="half",
                    ),
                ),
            )

            class PathManager:
                def get_encounter_path_from_id(self, encounter_id):
                    return str(Path(directory) / "encounters" / (encounter_id + ".json"))

                def get_character_path(self, name):
                    return str(Path(directory) / "characters" / (name + ".json"))

            writes = []

            def write_json(path, payload):
                writes.append((path, payload))
                return True

            with patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True), \
                    patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                result = apply_enemy_batch(
                    ledger,
                    NarrationResult("A brief encounter outcome.", "template"),
                    user_input_text="Enemies turn.",
                    turn_id="00000000-0000-4000-8000-000000000023",
                    conversation_history=[{"role": "system", "content": "seed"}],
                    conversation_history_file=str(Path(directory) / "history.json"),
                    encounter_projection=encounter_before,
                    path_manager=PathManager(),
                    read_json=lambda _path: encounter_before,
                    write_json=write_json,
                )

            rows = [
                json.loads(line)
                for line in trace_path.read_text(encoding="ascii").splitlines()
            ]
            self_preservation = next(
                row for row in rows
                if row.get("observation") == "combat_self_preservation_outcome"
            )
            self.assertEqual(self_preservation["self_preservation_outcome"], "fled")
            self.assertEqual(self_preservation["actor_id"], "actor_1")
            cover_rows = [row for row in rows if row.get("observation") == "combat_cover_outcome"]
            self.assertEqual(
                {(row["actor_id"], row["cover_state"], row.get("feature_id")) for row in cover_rows},
                {
                    ("actor_1", "expired", "OLD_COVER"),
                    ("actor_2", "applied", "PIT_COVER"),
                },
            )
            persisted = result.encounter_projection["creatures"]
            self.assertEqual(persisted[0]["defeatReason"], "fled")
            self.assertNotIn("coverFeatureId", persisted[0])
            self.assertEqual(persisted[1]["coverFeatureId"], "PIT_COVER")
            self.assertEqual(len(writes), 2)
            self.assertNotIn(directory, trace_path.read_text(encoding="ascii"))


if __name__ == "__main__":
    unittest.main()
